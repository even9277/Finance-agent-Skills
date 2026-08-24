"""受控对话离线验收使用的外部 Port 确定性实现。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from src.conversation.contracts import (
    ConversationRequest,
    ConversationResult,
    EvidenceDimension,
    EvidenceFact,
    ModelSynthesisRequest,
    ToolCall,
    ToolObservation,
    WorkflowEvent,
)
from src.conversation.errors import ContractViolationError, ToolTimeoutError


@dataclass(slots=True)
class FakeModelProvider:
    """只读取 AnswerContextPack 的离线模型 Port。"""

    calls: list[ModelSynthesisRequest] = field(default_factory=list)

    async def synthesize(self, request: ModelSynthesisRequest) -> str:
        """记录结构化请求并生成不访问网络的固定回答。"""
        self.calls.append(request)
        entity = request.context.entity
        sources = sorted({item.source for item in request.context.accepted_evidence})
        subject = f"{entity.symbol}（{entity.name}）" if entity is not None else "当前主题"
        return f"{subject}的离线只读证据来自：{'、'.join(sources)}。"


@dataclass(slots=True)
class FakeToolProvider:
    """模拟成功、市场超时或市场空证据的只读工具 Port。"""

    behavior: str = "success"
    calls: list[ToolCall] = field(default_factory=list)

    def __post_init__(self) -> None:
        allowed = {
            "success",
            "timeout_market",
            "missing_market",
            "recover_market_with_alternative",
        }
        if self.behavior not in allowed:
            raise ContractViolationError("unsupported fake tool behavior")

    async def execute(self, call: ToolCall) -> ToolObservation:
        """按固定模式返回与当前只读工具意图一致的结果。"""
        self.calls.append(call)
        if self.behavior == "timeout_market" and call.tool_name == "get_market_bars":
            raise ToolTimeoutError("fixture timeout")

        if call.evidence_dimension is EvidenceDimension.BASIC_PROFILE:
            facts = (
                EvidenceFact(key="name", value="贵州茅台"),
                EvidenceFact(key="industry", value="白酒"),
            )
        elif self.behavior == "missing_market" or (
            self.behavior == "recover_market_with_alternative"
            and call.tool_name == "get_market_bars"
        ):
            facts = ()
        else:
            facts = (
                EvidenceFact(key="close", value="1688.00", unit="CNY"),
                EvidenceFact(key="trade_date", value=date.today().isoformat()),
            )
        return ToolObservation(
            step_id=call.step_id,
            tool_name=call.tool_name,
            symbol=call.symbol,
            evidence_dimension=call.evidence_dimension,
            facts=facts,
            source=f"fixture:{call.tool_name}:v1",
            observed_at=date.today(),
            attempts=1,
        )


@dataclass(frozen=True, slots=True)
class SavedConversation:
    """内存 Repository 保存的一轮请求与唯一结果。"""

    request: ConversationRequest
    result: ConversationResult


@dataclass(slots=True)
class InMemoryConversationRepository:
    """不连接数据库的 M2 Repository Port。"""

    saved: list[SavedConversation] = field(default_factory=list)

    async def save_result(
        self,
        request: ConversationRequest,
        result: ConversationResult,
    ) -> None:
        """把一轮唯一终态保存到测试进程内。"""
        self.saved.append(SavedConversation(request=request, result=result))


@dataclass(slots=True)
class InMemoryTraceSink:
    """收集阶段事件或模拟可选观测出口故障。"""

    fail_on_emit: bool = False
    events: list[WorkflowEvent] = field(default_factory=list)

    def emit(self, event: WorkflowEvent) -> None:
        """记录事件；启用故障模式时不保留任何载荷。"""
        if self.fail_on_emit:
            raise RuntimeError("fixture trace sink unavailable")
        self.events.append(event)
