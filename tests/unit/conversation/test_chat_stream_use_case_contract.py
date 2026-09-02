"""锁定 Application 流式生命周期与事务终态。"""

from __future__ import annotations

import asyncio
import hashlib
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[3]
AGENT_ROOT = ROOT / "Financial-MCP-Agent"
for import_root in (ROOT, AGENT_ROOT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from backend.application.chat.contracts import (  # noqa: E402
    ChatCommand,
    ChatContentDelta,
    ChatStreamCompleted,
    ChatStreamFailed,
    ChatStreamStarted,
)
from backend.application.chat.use_case import ControlledChatUseCase  # noqa: E402
from backend.infrastructure.chat.testing import InMemoryConversationRepository  # noqa: E402
from src.conversation.contracts import (  # noqa: E402
    ConversationResult,
    ConversationRunContext,
    TerminalStatus,
)


def _result(
    *,
    status: TerminalStatus = TerminalStatus.SUCCEEDED,
    reply: str | None = None,
) -> ConversationResult:
    """构造可被 Application 持久化的最小领域终态。"""
    effective_reply = reply or (
        "部分可用回答" if status is TerminalStatus.PARTIAL else "单段应用回答"
    )
    return ConversationResult(
        status=status,
        reply=effective_reply,
        context=ConversationRunContext(
            trace_id="trace-stream-contract",
            run_id="run-stream-contract",
            session_id="session-stream-contract",
            request_id="request-stream-contract",
            turn_index=1,
        ),
        events=(),
    )


class _StaticWorkflow:
    """返回固定业务终态且不产生模型增量的非模型分支替身。"""

    def __init__(self, result: ConversationResult) -> None:
        self._result = result

    async def run(self, *args: Any, **kwargs: Any) -> ConversationResult:
        del args, kwargs
        return self._result


class _FailingWorkflow:
    """模拟会话已准备后发生的技术异常。"""

    async def run(self, *args: Any, **kwargs: Any) -> ConversationResult:
        del args, kwargs
        raise RuntimeError("provider-internal-detail")


class _DeltaWorkflow:
    """模拟工作流按模型原始顺序推送两个内容增量。"""

    async def run(self, *args: Any, **kwargs: Any) -> ConversationResult:
        del args
        on_content_delta = kwargs["on_content_delta"]
        await on_content_delta("第一段")
        await on_content_delta("第二段")
        return _result(reply="第一段第二段")


class _PartialFailingWorkflow:
    """模拟模型发送一个增量后发生技术失败。"""

    async def run(self, *args: Any, **kwargs: Any) -> ConversationResult:
        del args
        on_content_delta = kwargs["on_content_delta"]
        await on_content_delta("已展示片段")
        raise RuntimeError("provider-mid-stream-internal-detail")


class _HangingWorkflow:
    """模拟产生首个内容增量后仍在等待上游的长连接工作流。"""

    async def run(self, *args: Any, **kwargs: Any) -> ConversationResult:
        del args
        on_content_delta = kwargs["on_content_delta"]
        await on_content_delta("尚未完成")
        await asyncio.Event().wait()
        raise AssertionError("工作流被取消后不得继续返回")


class _CommitFailingRepository(InMemoryConversationRepository):
    """模拟保存完成后数据库提交失败的事务仓库。"""

    async def commit(self) -> None:
        """在提交点抛出技术异常，验证 Application 回滚已暂存结果。"""
        raise RuntimeError("database-commit-internal-detail")


@pytest.mark.unit
@pytest.mark.parametrize("status", [TerminalStatus.SUCCEEDED, TerminalStatus.PARTIAL])
def test_non_model_or_partial_reply_uses_single_delta_and_committed_completion(
    status: TerminalStatus,
) -> None:
    """没有上游 chunk 的业务终态必须显式降级为单 delta 后提交完成。"""

    async def run_case() -> None:
        repository = InMemoryConversationRepository()
        result = _result(status=status)
        use_case = ControlledChatUseCase(
            workflow=_StaticWorkflow(result),  # type: ignore[arg-type]
            repository=repository,
        )

        events = [
            event
            async for event in use_case.stream(
                ChatCommand(
                    user_id="user-stream-contract",
                    message="固定问题",
                    session_id="session-stream-contract",
                    request_id="request-stream-contract",
                )
            )
        ]

        assert isinstance(events[0], ChatStreamStarted)
        assert isinstance(events[1], ChatContentDelta)
        assert events[1].content == result.reply
        assert events[1].chunk_index == 1
        assert isinstance(events[2], ChatStreamCompleted)
        assert events[2].outcome.status is status
        assert events[2].chunk_count == 1
        assert events[2].content_sha256 == hashlib.sha256(result.reply.encode()).hexdigest()
        assert repository.committed is True
        assert repository.rolled_back is False
        assert len(repository.saved) == 1

    asyncio.run(run_case())


@pytest.mark.unit
def test_streaming_technical_failure_yields_safe_failed_event_after_rollback() -> None:
    """技术异常不得变成可提交业务回答，也不得暴露内部异常正文。"""

    async def run_case() -> None:
        repository = InMemoryConversationRepository()
        use_case = ControlledChatUseCase(
            workflow=_FailingWorkflow(),  # type: ignore[arg-type]
            repository=repository,
        )

        events = [
            event
            async for event in use_case.stream(
                ChatCommand(
                    user_id="user-stream-contract",
                    message="触发技术失败",
                    session_id="session-stream-contract",
                    request_id="request-stream-contract",
                )
            )
        ]

        assert isinstance(events[0], ChatStreamStarted)
        assert isinstance(events[1], ChatStreamFailed)
        assert events[1].error_code == "CHAT_STREAM_FAILED"
        assert "provider-internal-detail" not in repr(events[1])
        assert repository.rolled_back is True
        assert repository.committed is False
        assert repository.saved == []

    asyncio.run(run_case())


@pytest.mark.unit
def test_model_deltas_preserve_order_and_commit_only_before_completed() -> None:
    """多增量必须按序重建权威回复，并在提交后才公开 Completed。"""

    async def run_case() -> None:
        repository = InMemoryConversationRepository()
        use_case = ControlledChatUseCase(
            workflow=_DeltaWorkflow(),  # type: ignore[arg-type]
            repository=repository,
        )

        events = [
            event
            async for event in use_case.stream(
                ChatCommand(
                    user_id="user-stream-contract",
                    message="触发多个模型增量",
                    session_id="session-stream-contract",
                    request_id="request-stream-contract",
                )
            )
        ]

        assert isinstance(events[0], ChatStreamStarted)
        deltas = [event for event in events if isinstance(event, ChatContentDelta)]
        assert [event.content for event in deltas] == ["第一段", "第二段"]
        assert [event.chunk_index for event in deltas] == [1, 2]
        assert isinstance(events[-1], ChatStreamCompleted)
        assert events[-1].outcome.reply == "第一段第二段"
        assert events[-1].chunk_count == 2
        assert events[-1].content_sha256 == hashlib.sha256("第一段第二段".encode()).hexdigest()
        assert repository.committed is True
        assert repository.rolled_back is False
        assert len(repository.saved) == 1

    asyncio.run(run_case())


@pytest.mark.unit
def test_closing_stream_cancels_execution_and_rolls_back_uncommitted_turn() -> None:
    """消费端关闭流后必须取消仍在运行的工作流并回滚未提交事务。"""

    async def run_case() -> None:
        repository = InMemoryConversationRepository()
        use_case = ControlledChatUseCase(
            workflow=_HangingWorkflow(),  # type: ignore[arg-type]
            repository=repository,
        )
        stream = use_case.stream(
            ChatCommand(
                user_id="user-stream-contract",
                message="模拟断连",
                session_id="session-stream-contract",
                request_id="request-stream-contract",
            )
        )

        assert isinstance(await anext(stream), ChatStreamStarted)
        assert isinstance(await anext(stream), ChatContentDelta)
        await stream.aclose()

        assert repository.rolled_back is True
        assert repository.committed is False
        assert repository.saved == []

    asyncio.run(run_case())


@pytest.mark.unit
def test_commit_failure_yields_failed_event_and_clears_saved_result() -> None:
    """提交失败不得产生 Completed，也不得保留已保存的助手终态。"""

    async def run_case() -> None:
        repository = _CommitFailingRepository()
        use_case = ControlledChatUseCase(
            workflow=_StaticWorkflow(_result()),  # type: ignore[arg-type]
            repository=repository,
        )

        events = [
            event
            async for event in use_case.stream(
                ChatCommand(
                    user_id="user-stream-contract",
                    message="模拟提交失败",
                    session_id="session-stream-contract",
                    request_id="request-stream-contract",
                )
            )
        ]

        assert [type(event) for event in events] == [
            ChatStreamStarted,
            ChatContentDelta,
            ChatStreamFailed,
        ]
        assert repository.rolled_back is True
        assert repository.committed is False
        assert repository.saved == []
        assert "database-commit-internal-detail" not in repr(events[-1])

    asyncio.run(run_case())


@pytest.mark.unit
def test_failure_after_first_delta_preserves_visible_chunk_but_rolls_back() -> None:
    """中途失败应公开已发送 chunk 数并回滚，不能伪装成成功或业务 PARTIAL。"""

    async def run_case() -> None:
        repository = InMemoryConversationRepository()
        use_case = ControlledChatUseCase(
            workflow=_PartialFailingWorkflow(),  # type: ignore[arg-type]
            repository=repository,
        )

        events = [
            event
            async for event in use_case.stream(
                ChatCommand(
                    user_id="user-stream-contract",
                    message="模拟流中失败",
                    session_id="session-stream-contract",
                    request_id="request-stream-contract",
                )
            )
        ]

        assert [type(event) for event in events] == [
            ChatStreamStarted,
            ChatContentDelta,
            ChatStreamFailed,
        ]
        assert isinstance(events[1], ChatContentDelta)
        assert events[1].content == "已展示片段"
        assert isinstance(events[2], ChatStreamFailed)
        assert events[2].chunk_count == 1
        assert "provider-mid-stream-internal-detail" not in repr(events[2])
        assert repository.rolled_back is True
        assert repository.committed is False
        assert repository.saved == []

    asyncio.run(run_case())
