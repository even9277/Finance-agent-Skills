from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Literal
import asyncio
import json
import time
import uuid

from pydantic import BaseModel, Field

from src.agents.executor.budget import ExecutionBudget
from src.agents.executor.evidence_envelope import EvidenceEnvelope, normalize_evidence_envelope
from src.agents.planner.plan_validator import ToolPlanStepV2, ToolPlanV2
from src.agents.tool_discovery.executable_registry import (
    ExecutableToolRegistry,
    build_default_registry,
)

StepStatus = Literal["succeeded", "failed", "skipped", "timeout", "rate_limited"]


class StepResult(BaseModel):
    step_id: str
    tool_name: str
    status: StepStatus
    action_fingerprint: str
    error_type: str | None = None
    error_message: str | None = None
    is_retryable: bool = False
    new_evidence: bool = False
    evidence: EvidenceEnvelope | None = None
    started_at: str
    finished_at: str
    elapsed_ms: int


class BatchResult(BaseModel):
    batch_index: int
    step_results: list[StepResult] = Field(default_factory=list)
    batch_elapsed_ms: int
    rate_limited_count: int = 0
    timeout_count: int = 0


ToolInvoker = Callable[[str, dict[str, Any]], Awaitable[Any]]
StepStatusCallback = Callable[[ToolPlanStepV2, Literal["running", "succeeded", "failed", "skipped"], StepResult | None], Awaitable[None] | None]


def _now_text() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="milliseconds")


def action_fingerprint(tool_name: str, arguments: dict[str, Any]) -> str:
    return f"{tool_name}:{json.dumps(arguments or {}, ensure_ascii=False, sort_keys=True, default=str)}"


def plan_execution_layers(plan: ToolPlanV2) -> list[list[ToolPlanStepV2]]:
    steps_by_id = {step.step_id: step for step in plan.steps}
    remaining = set(steps_by_id)
    completed: set[str] = set()
    layers: list[list[ToolPlanStepV2]] = []
    while remaining:
        ready = [
            steps_by_id[step_id]
            for step_id in sorted(remaining)
            if set(steps_by_id[step_id].depends_on).issubset(completed)
        ]
        if not ready:
            raise ValueError("plan dependency cycle or unresolved dependency")
        layers.append(ready)
        for step in ready:
            remaining.remove(step.step_id)
            completed.add(step.step_id)
    return layers


class ExecutionScheduler:
    def __init__(
        self,
        *,
        registry: ExecutableToolRegistry | None = None,
        budget: ExecutionBudget | None = None,
        tool_invoker: ToolInvoker | None = None,
    ) -> None:
        self.registry = registry or build_default_registry()
        self.budget = budget or ExecutionBudget()
        self.tool_invoker = tool_invoker
        self._global_semaphore = asyncio.Semaphore(max(1, self.budget.max_concurrency))
        self._family_semaphores: dict[str, asyncio.Semaphore] = defaultdict(
            lambda: asyncio.Semaphore(max(1, self.budget.per_api_family_limit))
        )
        self._last_call_by_family: dict[str, float] = defaultdict(float)
        self._seen_fingerprints: set[str] = set()

    async def run(
        self,
        plan: ToolPlanV2,
        *,
        on_step_status: StepStatusCallback | None = None,
    ) -> list[BatchResult]:
        if len(plan.steps) > self.budget.max_steps:
            raise ValueError("plan exceeds max_steps budget")
        old_global_semaphore = self._global_semaphore
        skill_concurrency = (plan.metadata or {}).get("skill_concurrency") if hasattr(plan, "metadata") else None
        if isinstance(skill_concurrency, dict) and skill_concurrency.get("enabled", True):
            batch_size = int(skill_concurrency.get("batch_size") or self.budget.max_concurrency)
            if batch_size > 0:
                # Skill 可把并发上限收紧，但不能突破全局预算上限。
                self._global_semaphore = asyncio.Semaphore(max(1, min(self.budget.max_concurrency, batch_size)))
        batches: list[BatchResult] = []
        try:
            for index, layer in enumerate(plan_execution_layers(plan), start=1):
                started_perf = time.perf_counter()
                results = await asyncio.gather(
                    *(self._run_step(plan, step, on_step_status=on_step_status) for step in layer)
                )
                elapsed = int((time.perf_counter() - started_perf) * 1000)
                batches.append(
                    BatchResult(
                        batch_index=index,
                        step_results=list(results),
                        batch_elapsed_ms=elapsed,
                        rate_limited_count=sum(1 for item in results if item.status == "rate_limited"),
                        timeout_count=sum(1 for item in results if item.status == "timeout"),
                    )
                )
        finally:
            self._global_semaphore = old_global_semaphore
        return batches

    async def _run_step(
        self,
        plan: ToolPlanV2,
        step: ToolPlanStepV2,
        *,
        on_step_status: StepStatusCallback | None,
    ) -> StepResult:
        fp = action_fingerprint(step.tool_name, step.arguments)
        if fp in self._seen_fingerprints:
            result = self._step_result(
                step=step,
                status="skipped",
                fingerprint=fp,
                error_type="duplicate_action_fingerprint",
                started_at=_now_text(),
                elapsed_ms=0,
            )
            await self._emit(on_step_status, step, "skipped", result)
            return result
        self._seen_fingerprints.add(fp)

        await self._emit(on_step_status, step, "running", None)
        started_at = _now_text()
        started_perf = time.perf_counter()
        spec = self.registry.spec(step.tool_name)
        attempts = max(0, int(self.budget.per_tool_retry_limit)) + 1
        last_error_type = "tool_error"
        last_error_message = ""
        for attempt in range(attempts):
            tool_call_id = f"toolcall_{uuid.uuid4().hex}"
            try:
                raw = await self._invoke_with_limits(step.tool_name, step.arguments, spec.api_family)
                envelope = normalize_evidence_envelope(
                    raw=raw,
                    spec=spec,
                    step_id=step.step_id,
                    plan_id=plan.plan_id,
                    trace_id=plan.trace_id,
                    tool_call_id=tool_call_id,
                    tool_name=step.tool_name,
                    retry_count=attempt,
                )
                if envelope.ok:
                    result = self._step_result(
                        step=step,
                        status="succeeded",
                        fingerprint=fp,
                        started_at=started_at,
                        elapsed_ms=int((time.perf_counter() - started_perf) * 1000),
                        evidence=envelope,
                        new_evidence=True,
                    )
                    await self._emit(on_step_status, step, "succeeded", result)
                    return result
                last_error_type = envelope.error_type or "tool_error"
                last_error_message = envelope.error_message or ""
                if attempt >= attempts - 1 or not spec.can_retry:
                    result = self._step_result(
                        step=step,
                        status="failed",
                        fingerprint=fp,
                        error_type=last_error_type,
                        error_message=last_error_message,
                        started_at=started_at,
                        elapsed_ms=int((time.perf_counter() - started_perf) * 1000),
                        evidence=envelope,
                        is_retryable=spec.can_retry,
                    )
                    await self._emit(on_step_status, step, "failed", result)
                    return result
            except TimeoutError as exc:
                last_error_type = "timeout"
                last_error_message = str(exc)
                if attempt >= attempts - 1:
                    result = self._step_result(
                        step=step,
                        status="timeout",
                        fingerprint=fp,
                        error_type=last_error_type,
                        error_message=last_error_message,
                        started_at=started_at,
                        elapsed_ms=int((time.perf_counter() - started_perf) * 1000),
                        is_retryable=True,
                    )
                    await self._emit(on_step_status, step, "failed", result)
                    return result
            except Exception as exc:
                last_error_type = "tool_internal_error"
                last_error_message = str(exc)
                if attempt >= attempts - 1:
                    result = self._step_result(
                        step=step,
                        status="failed",
                        fingerprint=fp,
                        error_type=last_error_type,
                        error_message=last_error_message,
                        started_at=started_at,
                        elapsed_ms=int((time.perf_counter() - started_perf) * 1000),
                        is_retryable=spec.can_retry,
                    )
                    await self._emit(on_step_status, step, "failed", result)
                    return result

        result = self._step_result(
            step=step,
            status="failed",
            fingerprint=fp,
            error_type=last_error_type,
            error_message=last_error_message,
            started_at=started_at,
            elapsed_ms=int((time.perf_counter() - started_perf) * 1000),
            is_retryable=spec.can_retry,
        )
        await self._emit(on_step_status, step, "failed", result)
        return result

    async def _invoke_with_limits(self, tool_name: str, arguments: dict[str, Any], api_family: str) -> Any:
        async with self._global_semaphore:
            async with self._family_semaphores[api_family]:
                await self._respect_min_interval(api_family)
                try:
                    return await asyncio.wait_for(
                        self._invoke_tool(tool_name, arguments),
                        timeout=max(0.001, self.budget.per_tool_timeout_ms / 1000),
                    )
                except asyncio.TimeoutError as exc:
                    raise TimeoutError(f"tool timeout: {tool_name}") from exc
                finally:
                    self._last_call_by_family[api_family] = time.perf_counter()

    async def _respect_min_interval(self, api_family: str) -> None:
        min_interval = max(0, self.budget.min_interval_ms) / 1000
        if min_interval <= 0:
            return
        last_call = self._last_call_by_family.get(api_family, 0.0)
        wait_for = min_interval - (time.perf_counter() - last_call)
        if wait_for > 0:
            await asyncio.sleep(wait_for)

    async def _invoke_tool(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        if self.tool_invoker is not None:
            return await self.tool_invoker(tool_name, arguments)
        handler = self.registry.handler(tool_name)
        if hasattr(handler, "ainvoke"):
            return await handler.ainvoke(arguments)
        if asyncio.iscoroutinefunction(handler):
            return await handler(**arguments)
        result = handler(**arguments)
        if asyncio.iscoroutine(result):
            return await result
        return result

    @staticmethod
    def _step_result(
        *,
        step: ToolPlanStepV2,
        status: StepStatus,
        fingerprint: str,
        started_at: str,
        elapsed_ms: int,
        error_type: str | None = None,
        error_message: str | None = None,
        is_retryable: bool = False,
        new_evidence: bool = False,
        evidence: EvidenceEnvelope | None = None,
    ) -> StepResult:
        return StepResult(
            step_id=step.step_id,
            tool_name=step.tool_name,
            status=status,
            action_fingerprint=fingerprint,
            error_type=error_type,
            error_message=error_message,
            is_retryable=is_retryable,
            new_evidence=new_evidence,
            evidence=evidence,
            started_at=started_at,
            finished_at=_now_text(),
            elapsed_ms=elapsed_ms,
        )

    @staticmethod
    async def _emit(
        callback: StepStatusCallback | None,
        step: ToolPlanStepV2,
        status: Literal["running", "succeeded", "failed", "skipped"],
        result: StepResult | None,
    ) -> None:
        if callback is None:
            return
        maybe = callback(step, status, result)
        if asyncio.iscoroutine(maybe):
            await maybe


__all__ = [
    "BatchResult",
    "ExecutionScheduler",
    "StepResult",
    "action_fingerprint",
    "plan_execution_layers",
]
