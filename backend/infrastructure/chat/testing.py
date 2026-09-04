"""受控对话离线验收使用的外部 Port 确定性实现。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import date

from src.conversation.contracts import (
    ConversationRequest,
    ConversationResult,
    EvidenceDimension,
    EvidenceFact,
    ModelSynthesisChunk,
    ModelSynthesisRequest,
    ToolCall,
    ToolObservation,
    WorkflowEvent,
)
from src.memory.contracts import WorkingState
from src.memory.working_state import reduce_working_state
from src.conversation.errors import ContractViolationError, ToolTimeoutError

from backend.application.chat.contracts import (
    ChatCommand,
    ChatContextWindowData,
    PreparedChatTurn,
)


@dataclass(slots=True)
class FakeModelProvider:
    """只读取 AnswerContextPack 的离线模型 Port。"""

    calls: list[ModelSynthesisRequest] = field(default_factory=list)
    chunk_delay_seconds: float = 0.0

    async def stream_synthesize(self, request: ModelSynthesisRequest):
        """记录结构化请求并生成一个显式离线增量。"""
        self.calls.append(request)
        if self.chunk_delay_seconds > 0:
            await asyncio.sleep(self.chunk_delay_seconds)
        entity = request.context.entity
        sources = sorted({item.source for item in request.context.accepted_evidence})
        subject = f"{entity.symbol}（{entity.name}）" if entity is not None else "当前主题"
        yield ModelSynthesisChunk(
            content=f"{subject}的离线只读证据来自：{'、'.join(sources)}。",
            index=1,
        )


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

        if self.behavior == "missing_market" or (
            self.behavior == "recover_market_with_alternative"
            and call.tool_name == "get_market_bars"
        ):
            facts = (
                (EvidenceFact(key="name", value="贵州茅台"),)
                if call.evidence_dimension is EvidenceDimension.BASIC_PROFILE
                else ()
            )
        else:
            dimension_facts = {
                EvidenceDimension.BASIC_PROFILE: (EvidenceFact(key="name", value="贵州茅台"),),
                EvidenceDimension.MARKET_SNAPSHOT: (EvidenceFact(key="close", value="1688.00"),),
                EvidenceDimension.FINANCIAL_INDICATOR: (EvidenceFact(key="roe", value="12.3"),),
                EvidenceDimension.INCOME_STATEMENT: (EvidenceFact(key="revenue", value="100"),),
                EvidenceDimension.BALANCE_SHEET: (EvidenceFact(key="total_assets", value="200"),),
                EvidenceDimension.CASHFLOW_STATEMENT: (
                    EvidenceFact(key="n_cashflow_act", value="30"),
                ),
                EvidenceDimension.FUND_BASIC: (EvidenceFact(key="fund_name", value="离线基金"),),
                EvidenceDimension.ETF_BASIC: (EvidenceFact(key="fund_name", value="离线 ETF"),),
                EvidenceDimension.FUND_NAV: (EvidenceFact(key="unit_nav", value="1.1"),),
                EvidenceDimension.FUND_MARKET: (EvidenceFact(key="close", value="1.2"),),
                EvidenceDimension.FUND_SHARE: (EvidenceFact(key="fd_share", value="1000"),),
                EvidenceDimension.INDEX_DAILY: (EvidenceFact(key="close", value="3500"),),
                EvidenceDimension.SECTOR_SNAPSHOT: (
                    EvidenceFact(key="pct_change", value="2.1"),
                ),
                EvidenceDimension.SECTOR_CONSTITUENTS: (
                    EvidenceFact(key="constituent", value="离线成分股"),
                ),
                EvidenceDimension.WEB_NEWS: (
                    EvidenceFact(key="W1.title", value="离线新闻线索"),
                    EvidenceFact(key="W1.domain", value="news.example.com"),
                    EvidenceFact(key="W1.summary", value="仅供离线弱证据测试"),
                ),
            }
            facts = dimension_facts[call.evidence_dimension]
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
    """不连接数据库的事务型 Repository Port。"""

    saved: list[SavedConversation] = field(default_factory=list)
    committed: bool = False
    rolled_back: bool = False
    working_state: WorkingState = field(default_factory=WorkingState)
    compaction_checks: int = 0

    async def prepare_turn(self, command: ChatCommand) -> PreparedChatTurn:
        """为离线案例返回固定或调用方指定的会话标识。"""
        return PreparedChatTurn(session_id=command.session_id or "session-offline")

    async def save_result(
        self,
        request: ConversationRequest,
        result: ConversationResult,
    ) -> ChatContextWindowData:
        """把一轮唯一终态保存到测试进程内。"""
        self.saved.append(SavedConversation(request=request, result=result))
        return ChatContextWindowData()

    async def apply_working_state(
        self,
        request: ConversationRequest,
        result: ConversationResult,
    ) -> WorkingState:
        """在内存中应用与生产相同的确定性状态归并。"""
        if result.working_state_update is None:
            return self.working_state
        transition = reduce_working_state(
            self.working_state,
            result.working_state_update,
            session_id=request.session_id,
            source_message_id=max(1, self.working_state.state_version + 1),
            trace_id=result.context.trace_id,
        )
        self.working_state = transition.state
        return transition.state

    async def maybe_enqueue_compaction(
        self,
        request: ConversationRequest,
        result: ConversationResult,
    ) -> bool:
        """记录后台排队检查；纯内存案例默认不创建任务。"""
        del request, result
        self.compaction_checks += 1
        return False

    async def commit(self) -> None:
        """记录 Application 已决定提交。"""
        self.committed = True

    async def rollback(self) -> None:
        """记录 Application 已决定回滚。"""
        self.rolled_back = True
        self.saved.clear()


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
