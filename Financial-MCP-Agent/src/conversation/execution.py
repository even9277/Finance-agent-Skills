"""仅执行 Validated Tool DAG，并实施并发、去重、超时与重试预算。"""

from __future__ import annotations

import asyncio
import time
from dataclasses import replace
from datetime import date

from .contracts import (
    ConversationRunContext,
    ErrorCode,
    ExecutionResult,
    StepStatus,
    ToolCall,
    ToolObservation,
    ToolPlanStep,
    ValidatedToolPlan,
)
from .errors import (
    ContractViolationError,
    ToolPermanentError,
    ToolTimeoutError,
    ToolTransientError,
)
from .ports import ToolPort


class ControlledExecutor:
    """按冻结权限和 DAG 层执行只读工具，不接受原始 ToolPlan。"""

    def __init__(self, tool: ToolPort) -> None:
        self._tool = tool

    async def execute(
        self,
        plan: ValidatedToolPlan,
        context: ConversationRunContext,
    ) -> ExecutionResult:
        """在请求预算内执行已校验计划并归一化步骤结果。

        Args:
            plan: Validator 生成、携带同一权限快照和执行层的计划。
            context: 单次/总超时、尝试次数和并发上限的运行上下文。

        Returns:
            按原计划顺序排列的观察、真实调用数和批次统计。

        Raises:
            ContractViolationError: 调用方绕过 Validator 或执行层引用未知节点。
        """
        if not isinstance(plan, ValidatedToolPlan):
            raise ContractViolationError("executor accepts ValidatedToolPlan only")
        by_id = {step.step_id: step for step in plan.plan.steps}
        if any(step_id not in by_id for layer in plan.execution_layers for step_id in layer):
            raise ContractViolationError("validated execution layers reference unknown steps")

        semaphore = asyncio.Semaphore(context.budget.max_concurrency)
        seen_actions: set[str] = set()
        observations: dict[str, ToolObservation] = {}
        tool_call_count = 0
        deduplicated_count = 0
        started = time.perf_counter()
        batches_completed = 0

        for layer_index, layer in enumerate(plan.execution_layers):
            remaining_ms = context.budget.total_tool_timeout_ms - int(
                (time.perf_counter() - started) * 1000
            )
            if remaining_ms <= 0:
                self._mark_budget_exhausted(plan, layer_index, observations)
                break
            tasks = [
                self._run_step(
                    step=by_id[step_id],
                    validated=plan,
                    context=context,
                    previous=observations,
                    seen_actions=seen_actions,
                    semaphore=semaphore,
                )
                for step_id in layer
            ]
            try:
                results = await asyncio.wait_for(
                    asyncio.gather(*tasks),
                    timeout=max(0.001, remaining_ms / 1000),
                )
            except TimeoutError:
                self._mark_budget_exhausted(plan, layer_index, observations)
                break
            for observation, calls, deduplicated in results:
                observations[observation.step_id] = observation
                tool_call_count += calls
                deduplicated_count += int(deduplicated)
            batches_completed += 1

        ordered = tuple(
            observations.get(step.step_id) or self._budget_observation(step)
            for step in plan.plan.steps
        )
        return ExecutionResult(
            observations=ordered,
            tool_call_count=tool_call_count,
            batch_count=batches_completed,
            deduplicated_count=deduplicated_count,
            failed_count=sum(item.status is StepStatus.FAILED for item in ordered),
        )

    async def _run_step(
        self,
        *,
        step: ToolPlanStep,
        validated: ValidatedToolPlan,
        context: ConversationRunContext,
        previous: dict[str, ToolObservation],
        seen_actions: set[str],
        semaphore: asyncio.Semaphore,
    ) -> tuple[ToolObservation, int, bool]:
        if any(previous[item].status is not StepStatus.SUCCEEDED for item in step.depends_on):
            return (
                self._failure_observation(
                    step,
                    attempts=0,
                    status=StepStatus.SKIPPED,
                    error_code=ErrorCode.TOOL_DEPENDENCY_FAILED,
                    message="上游工具步骤失败，本步骤未执行。",
                ),
                0,
                False,
            )
        if step.idempotency_key in seen_actions:
            return (
                self._failure_observation(
                    step,
                    attempts=0,
                    status=StepStatus.SKIPPED,
                    error_code=ErrorCode.DUPLICATE_TOOL_ACTION,
                    message="相同只读动作已执行，本步骤已去重。",
                ),
                0,
                True,
            )
        seen_actions.add(step.idempotency_key)

        policy = validated.permissions.require(step.tool_name)
        max_attempts = context.budget.max_tool_attempts if policy.retryable else 1
        call = ToolCall(
            step_id=step.step_id,
            tool_name=step.tool_name,
            symbol=step.symbol,
            evidence_dimension=step.evidence_dimension,
            arguments=step.arguments,
            idempotency_key=step.idempotency_key,
        )
        calls = 0
        for attempt in range(1, max_attempts + 1):
            calls += 1
            try:
                async with semaphore:
                    observation = await asyncio.wait_for(
                        self._tool.execute(call),
                        timeout=max(0.001, context.budget.per_tool_timeout_ms / 1000),
                    )
                if not self._matches_call(observation, call):
                    return (
                        self._failure_observation(
                            step,
                            attempts=attempt,
                            error_code=ErrorCode.TOOL_INVALID_RESULT,
                            message="工具结果与已授权调用合同不一致。",
                        ),
                        calls,
                        False,
                    )
                return replace(observation, attempts=attempt), calls, False
            except (ToolTimeoutError, TimeoutError):
                if attempt == max_attempts:
                    return (
                        self._failure_observation(
                            step,
                            attempts=attempt,
                            error_code=ErrorCode.TOOL_TIMEOUT,
                            message="只读工具在调用预算内超时。",
                        ),
                        calls,
                        False,
                    )
            except ToolTransientError:
                if attempt == max_attempts:
                    return (
                        self._failure_observation(
                            step,
                            attempts=attempt,
                            error_code=ErrorCode.TOOL_TRANSIENT_FAILURE,
                            message="只读工具的瞬时故障在重试预算内未恢复。",
                        ),
                        calls,
                        False,
                    )
            except ToolPermanentError:
                return (
                    self._failure_observation(
                        step,
                        attempts=attempt,
                        error_code=ErrorCode.TOOL_EXECUTION_FAILED,
                        message="只读工具返回不可重试失败。",
                    ),
                    calls,
                    False,
                )
            except Exception:
                # 未知 Provider 异常只保留稳定错误码，不让原始消息进入状态或 Trace。
                return (
                    self._failure_observation(
                        step,
                        attempts=attempt,
                        error_code=ErrorCode.TOOL_EXECUTION_FAILED,
                        message="只读工具执行失败。",
                    ),
                    calls,
                    False,
                )
        raise ContractViolationError("tool retry loop exited without a normalized result")

    @staticmethod
    def _matches_call(observation: ToolObservation, call: ToolCall) -> bool:
        return (
            observation.step_id == call.step_id
            and observation.tool_name == call.tool_name
            and observation.symbol == call.symbol
            and observation.evidence_dimension is call.evidence_dimension
        )

    def _mark_budget_exhausted(
        self,
        plan: ValidatedToolPlan,
        start_layer: int,
        observations: dict[str, ToolObservation],
    ) -> None:
        by_id = {step.step_id: step for step in plan.plan.steps}
        for layer in plan.execution_layers[start_layer:]:
            for step_id in layer:
                observations.setdefault(step_id, self._budget_observation(by_id[step_id]))

    def _budget_observation(self, step: ToolPlanStep) -> ToolObservation:
        return self._failure_observation(
            step,
            attempts=0,
            error_code=ErrorCode.EXECUTION_BUDGET_EXHAUSTED,
            message="工具计划已达到总执行预算。",
        )

    @staticmethod
    def _failure_observation(
        step: ToolPlanStep,
        *,
        attempts: int,
        error_code: ErrorCode,
        message: str,
        status: StepStatus = StepStatus.FAILED,
    ) -> ToolObservation:
        return ToolObservation(
            step_id=step.step_id,
            tool_name=step.tool_name,
            symbol=step.symbol,
            evidence_dimension=step.evidence_dimension,
            facts=(),
            source="tool-port",
            observed_at=date.today(),
            attempts=attempts,
            status=status,
            error_code=error_code,
            error_message=message,
        )
