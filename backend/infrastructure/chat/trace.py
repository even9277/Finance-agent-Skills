"""把领域 WorkflowEvent 桥接到现有本地 JSONL 和可选 exporter。"""

from __future__ import annotations

from src.conversation.contracts import WorkflowEvent
from src.tools.skill_trace import log_workflow_event


class SkillTraceSink:
    """生产受控对话 Trace Adapter；不持有业务状态或外部客户端。"""

    def emit(self, event: WorkflowEvent) -> None:
        """写入一个低风险阶段事件。

        Args:
            event: 领域工作流产生的版本化阶段事件。

        Returns:
            无返回值；JSONL/exporter 失败由 `skill_trace` 自身隔离。
        """
        log_workflow_event(
            sequence=event.sequence,
            trace_id=event.trace_id,
            run_id=event.run_id,
            session_id=event.session_id,
            stage=event.stage.value,
            status=event.status.value,
            elapsed_ms=event.elapsed_ms,
            error_code=event.error_code.value if event.error_code is not None else None,
            attributes={item.key: item.value for item in event.attributes},
            contract_version=event.version,
            workflow_name="controlled-conversation-mainline",
        )
