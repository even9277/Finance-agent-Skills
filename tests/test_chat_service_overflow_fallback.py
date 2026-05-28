import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

_AGENT_ROOT = Path(__file__).resolve().parent.parent / "Financial-MCP-Agent"
if str(_AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENT_ROOT))

from backend.db.database import Base
from backend.db.models import Message, Session, User
from backend.services import chat_service


class _FakeResponse:
    def __init__(self, content: str):
        self.content = content


class _StructuredSummaryLLM:
    async def ainvoke(self, _messages):
        return _FakeResponse(
            """{
  "reply_preference_hint": "先给结论，再展开",
  "active_entities": [
    {
      "canonical_id": "600519.SH",
      "display_name": "贵州茅台",
      "entity_type": "stock",
      "market": "CN-A",
      "confidence": "high",
      "source": "user_explicit",
      "status": "active"
    }
  ],
  "constraints": ["保留 600519.SH 与估值风险约束"],
  "open_loops": ["继续回答最新的估值追问"],
  "session_record_summary": "用户继续追问贵州茅台估值，助手保留早期核心结论。"
}"""
        )


class ChatServiceOverflowFallbackTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.temp_db.close()
        self.sqlite_url = f"sqlite+aiosqlite:///{self.temp_db.name}"
        self.engine = create_async_engine(self.sqlite_url)
        self.SessionFactory = async_sessionmaker(self.engine, expire_on_commit=False)

        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def asyncTearDown(self):
        await self.engine.dispose()
        if os.path.exists(self.temp_db.name):
            os.unlink(self.temp_db.name)

    async def _seed_session(self) -> str:
        async with self.SessionFactory() as db:
            user = User(id="user-test", display_name="test", cold_start_done=True)
            session = Session(
                id="session-test",
                user_id=user.id,
                mode="chat",
                title="test",
                summary_version=0,
                compression_status="idle",
            )
            db.add(user)
            db.add(session)
            await db.flush()
            db.add_all(
                [
                    Message(session_id=session.id, role="user", content="请分析贵州茅台，代码 600519.SH"),
                    Message(session_id=session.id, role="assistant", content="先看估值、业绩和风险。"),
                    Message(session_id=session.id, role="user", content="请继续分析贵州茅台估值"),
                ]
            )
            await db.commit()
            return session.id

    async def test_compress_if_needed_force_bypasses_threshold(self):
        session_id = await self._seed_session()

        async with self.SessionFactory() as db:
            with patch.object(chat_service.settings, "enable_stm", True):
                with patch.object(chat_service.settings, "stm_keep_recent", 2):
                    with patch.object(
                        chat_service.settings, "stm_fallback_min_uncompressed_messages", 10
                    ):
                        with patch(
                            "backend.services.stm_summary_runtime._build_summary_llm",
                            return_value=_StructuredSummaryLLM(),
                        ):
                            skipped = await chat_service.compress_if_needed(db, session_id)
                            forced = await chat_service.compress_if_needed(
                                db,
                                session_id,
                                trigger="overflow_fallback_compaction",
                                force=True,
                            )

        self.assertIsNone(skipped)
        self.assertIsNotNone(forced)
        self.assertEqual(forced["reason"], "ok")
        self.assertGreater(forced["compressed_message_count"], 0)
        self.assertIn(
            forced["final_strategy"],
            {"model_summary", "fallback_after_audit", "fallback_on_error"},
        )

    async def test_force_overflow_recovery_uses_force_compaction_trigger(self):
        fake_db = SimpleNamespace(refresh=AsyncMock(), commit=AsyncMock(), rollback=AsyncMock())
        fake_session = SimpleNamespace(id="session-test")

        with patch.object(chat_service.settings, "enable_stm", True):
            with patch.object(
                chat_service,
                "compress_if_needed",
                new=AsyncMock(
                    return_value={
                        "compressed_message_count": 2,
                        "final_strategy": "fallback_on_error",
                    }
                ),
            ) as compress_mock:
                with patch.object(
                    chat_service,
                    "refresh_session_context_metrics",
                    new=AsyncMock(),
                ):
                    recovered = await chat_service._force_overflow_recovery_compaction(
                        fake_db,
                        fake_session,
                        user_message="继续分析贵州茅台估值",
                        exc=RuntimeError("context length exceeded"),
                    )

        self.assertTrue(recovered)
        compress_mock.assert_awaited_once_with(
            fake_db,
            "session-test",
            trigger="overflow_fallback_compaction",
            force=True,
        )


if __name__ == "__main__":
    unittest.main()
