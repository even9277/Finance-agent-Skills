"""只执行 validated plan，并对瞬时工具超时进行有限重试。"""

from __future__ import annotations

from dataclasses import replace
from datetime import date

from .contracts import (
    ConversationRunContext,
    ErrorCode,
    ExecutionResult,
    StepStatus,
    ToolCall,
    ToolObservation,
    ValidatedToolPlan,
)
from .errors import ToolTimeoutError
from .ports import ToolPort


class ControlledExecutor:
    """在冻结调用预算内顺序执行 M2 的只读 DAG。"""

    def __init__(self, tool: ToolPort) -> None:
        self._tool = tool

    async def execute(
        self,
        plan: ValidatedToolPlan,
        context: ConversationRunContext,
    ) -> ExecutionResult:
        """执行权限已验证的工具步骤并归一化错误。

        Args:
            plan: PlanValidator 输出的唯一可执行合同。
            context: 包含单工具尝试次数上限的运行上下文。

        Returns:
            顺序稳定的工具观察及真实调用次数。
        """
        observations: list[ToolObservation] = []
        call_count = 0
        for step in plan.plan.steps:
            call = ToolCall(
                step_id=step.step_id,
                tool_name=step.tool_name,
                symbol=step.symbol,
                evidence_dimension=step.evidence_dimension,
            )
            for attempt in range(1, context.budget.max_tool_attempts + 1):
                call_count += 1
                try:
                    observation = await self._tool.execute(call)
                    observations.append(replace(observation, attempts=attempt))
                    break
                except ToolTimeoutError:
                    if attempt == context.budget.max_tool_attempts:
                        observations.append(
                            ToolObservation(
                                step_id=step.step_id,
                                tool_name=step.tool_name,
                                symbol=step.symbol,
                                evidence_dimension=step.evidence_dimension,
                                facts=(),
                                source="tool-port",
                                observed_at=date.today(),
                                attempts=attempt,
                                status=StepStatus.FAILED,
                                error_code=ErrorCode.TOOL_TIMEOUT,
                                error_message="只读工具在调用预算内超时。",
                            )
                        )
                except Exception:
                    # 未知 Provider 异常转换为安全错误码，不把异常原文写入状态或 Trace。
                    observations.append(
                        ToolObservation(
                            step_id=step.step_id,
                            tool_name=step.tool_name,
                            symbol=step.symbol,
                            evidence_dimension=step.evidence_dimension,
                            facts=(),
                            source="tool-port",
                            observed_at=date.today(),
                            attempts=attempt,
                            status=StepStatus.FAILED,
                            error_code=ErrorCode.TOOL_EXECUTION_FAILED,
                            error_message="只读工具执行失败。",
                        )
                    )
                    break
        return ExecutionResult(observations=tuple(observations), tool_call_count=call_count)
