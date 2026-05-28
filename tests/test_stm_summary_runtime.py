import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

_AGENT_ROOT = Path(__file__).resolve().parent.parent / "Financial-MCP-Agent"
if str(_AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENT_ROOT))

from backend.db.database import Base
from backend.db.models import Message, Session, SessionSummary, SummaryAuditLog, User
from backend.services import stm_summary_runtime as runtime


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
  "constraints": ["保留 600519.SH 与关键指标"],
  "open_loops": ["继续回答估值、业绩和风险问题"],
  "session_record_summary": "用户请分析贵州茅台是否值得继续跟踪，助手建议先看估值、业绩和风险。"
}"""
        )


class _FailingSummaryLLM:
    async def ainvoke(self, _messages):
        raise RuntimeError("summary model unavailable")


class _SchemaInvalidSummaryLLM:
    async def ainvoke(self, _messages):
        return _FakeResponse(
            """{
  "reply_preference_hint": "先给结论，再展开",
  "active_entities": [{"canonical_id": "688981.SH", "display_name": "中芯国际"}],
  "constraints": ["当前只看 A 股口径"],
  "open_loops": ["补充估值对比"],
  "session_record_summary": "用户要求分析中芯国际。",
  "unexpected": "should_fail"
}"""
        )


class _NonJsonSummaryLLM:
    async def ainvoke(self, _messages):
        return _FakeResponse("这不是 JSON 输出")


class StmSummaryRuntimeTests(unittest.IsolatedAsyncioTestCase):
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
                    Message(session_id=session.id, role="user", content="请分析贵州茅台最近是否值得继续跟踪，代码 600519.SH"),
                    Message(session_id=session.id, role="assistant", content="先看估值、业绩和风险。"),
                ]
            )
            await db.commit()
            return session.id

    async def test_run_summary_compaction_commits_summary_and_marks_messages(self):
        session_id = await self._seed_session()

        async with self.SessionFactory() as db:
            session = await db.get(Session, session_id)
            rows = list(
                (
                    await db.execute(
                        select(Message)
                        .where(Message.session_id == session_id)
                        .order_by(Message.created_at.asc())
                    )
                ).scalars().all()
            )
            with patch.object(runtime, "_build_summary_llm", return_value=_StructuredSummaryLLM()):
                result = await runtime.run_summary_compaction(
                    db,
                    session,
                    source_rows=rows,
                    cutoff_message_id=rows[-1].id,
                    trigger="worker_message_count",
                )

            self.assertTrue(result.compacted)
            self.assertEqual(result.reason, "ok")
            self.assertIn("## Decisions", result.summary_text or "")

        async with self.SessionFactory() as db:
            session = await db.get(Session, session_id)
            summaries = list(
                (
                    await db.execute(
                        select(SessionSummary).where(SessionSummary.session_id == session_id)
                    )
                ).scalars().all()
            )
            messages = list(
                (
                    await db.execute(
                        select(Message).where(Message.session_id == session_id)
                    )
                ).scalars().all()
            )
            self.assertEqual(int(session.summary_version or 0), 1)
            self.assertIn("## Exact identifiers", session.running_summary or "")
            self.assertEqual(len(summaries), 1)
            self.assertTrue(all(bool(message.is_compressed) for message in messages))

    async def test_try_commit_summary_with_cas_rejects_stale_base_version(self):
        session_id = await self._seed_session()

        async with self.SessionFactory() as db:
            rows = list(
                (
                    await db.execute(
                        select(Message)
                        .where(Message.session_id == session_id)
                        .order_by(Message.created_at.asc())
                    )
                ).scalars().all()
            )
            committed = await runtime.try_commit_summary_with_cas(
                db,
                session_id,
                base_summary_version=0,
                new_summary="## Decisions\n- first\n## Open TODOs\n- first\n## Constraints/Rules\n- first\n## Pending user asks\n- first\n## Exact identifiers\n- 600519.SH",
                compressed_message_ids=[],
                trigger="test_cas_first",
                total_message_count=len(rows),
            )
            self.assertTrue(committed)

        async with self.SessionFactory() as db:
            rejected = await runtime.try_commit_summary_with_cas(
                db,
                session_id,
                base_summary_version=0,
                new_summary="## Decisions\n- second\n## Open TODOs\n- second\n## Constraints/Rules\n- second\n## Pending user asks\n- second\n## Exact identifiers\n- 600519.SH",
                compressed_message_ids=[],
                trigger="test_cas_stale",
                total_message_count=2,
            )
            self.assertFalse(rejected)

            session = await db.get(Session, session_id)
            summaries = list(
                (
                    await db.execute(
                        select(SessionSummary).where(SessionSummary.session_id == session_id)
                    )
                ).scalars().all()
            )
            self.assertEqual(int(session.summary_version or 0), 1)
            self.assertIn("first", session.running_summary or "")
            self.assertEqual(len(summaries), 1)

    async def test_run_summary_compaction_uses_structured_fallback_when_model_fails(self):
        session_id = await self._seed_session()

        async with self.SessionFactory() as db:
            session = await db.get(Session, session_id)
            rows = list(
                (
                    await db.execute(
                        select(Message)
                        .where(Message.session_id == session_id)
                        .order_by(Message.created_at.asc())
                    )
                ).scalars().all()
            )
            with patch.object(runtime, "_build_summary_llm", return_value=_FailingSummaryLLM()):
                result = await runtime.run_summary_compaction(
                    db,
                    session,
                    source_rows=rows,
                    cutoff_message_id=rows[-1].id,
                    trigger="overflow_fallback_compaction",
                )

            self.assertTrue(result.compacted)
            self.assertEqual(result.reason, "ok")
            self.assertEqual(result.final_strategy, "fallback_on_error")
            self.assertIn("## Decisions", result.summary_text or "")
            self.assertIn("## Pending user asks", result.summary_text or "")
            self.assertIn("600519.SH", result.summary_text or "")

    async def test_fallback_summary_does_not_embed_legacy_markdown_headers(self):
        previous_summary = """## Decisions
- 已经有旧结论
## Open TODOs
- 继续跟踪
## Constraints/Rules
- 只看 A 股
## Pending user asks
- 还要补估值
## Exact identifiers
- 518880
"""
        fallback_summary = runtime.build_structured_fallback_summary(
            previous_payload=runtime._extract_summary_payload(previous_summary),
            source_rows=[],
            latest_focus="请分析中芯国际 688981.SH",
            fresh_identifiers=["688981.SH"],
        )

        self.assertEqual(fallback_summary.count("## Decisions"), 1)
        self.assertNotIn("- ## Decisions", fallback_summary)
        self.assertNotIn("Historical summary carry-over", fallback_summary)

    async def test_fallback_does_not_inherit_stale_identifiers(self):
        session_id = await self._seed_session()

        async with self.SessionFactory() as db:
            session = await db.get(Session, session_id)
            session.running_summary_state = runtime._normalize_summary_payload(
                {
                    "active_entities": [
                        {"canonical_id": "518880", "display_name": "黄金 ETF", "status": "active"},
                        {"canonical_id": "159516", "display_name": "半导体 ETF", "status": "active"},
                    ],
                    "constraints": ["当前只看 A 股口径"],
                    "open_loops": ["继续跟踪"],
                    "session_record_summary": "历史上讨论过 ETF。",
                }
            )
            session.running_summary = runtime._render_summary_payload_to_markdown(session.running_summary_state)
            await db.flush()
            db.add(Message(session_id=session.id, role="user", content="现在只分析 688981.SH 中芯国际"))
            await db.commit()

        async with self.SessionFactory() as db:
            session = await db.get(Session, session_id)
            rows = list(
                (
                    await db.execute(
                        select(Message)
                        .where(Message.session_id == session_id)
                        .order_by(Message.created_at.asc())
                    )
                ).scalars().all()
            )
            with patch.object(runtime, "_build_summary_llm", return_value=_FailingSummaryLLM()):
                result = await runtime.run_summary_compaction(
                    db,
                    session,
                    source_rows=rows,
                    cutoff_message_id=rows[-1].id,
                    trigger="overflow_fallback_compaction",
                )

        identifiers = {item.get("canonical_id") for item in result.summary_payload.get("active_entities") or []}
        self.assertIn("688981.SH", identifiers)
        self.assertNotIn("518880", identifiers)
        self.assertNotIn("159516", identifiers)
        self.assertNotIn("518880", result.summary_text or "")
        self.assertNotIn("159516", result.summary_text or "")

    async def test_schema_fail_reuses_last_good_payload_without_fallback(self):
        session_id = await self._seed_session()

        async with self.SessionFactory() as db:
            session = await db.get(Session, session_id)
            session.running_summary_state = runtime._normalize_summary_payload(
                {
                    "reply_preference_hint": "先给结论，再展开",
                    "active_entities": [{"canonical_id": "600519.SH", "display_name": "贵州茅台", "status": "active"}],
                    "constraints": ["保留 600519.SH 与关键指标"],
                    "open_loops": ["继续回答估值、业绩和风险问题"],
                    "session_record_summary": "上一版结构化摘要。",
                    "field_updated_at": {"constraints": "2026-04-21T00:00:00Z"},
                }
            )
            session.running_summary = runtime._render_summary_payload_to_markdown(session.running_summary_state)
            await db.commit()

        async with self.SessionFactory() as db:
            session = await db.get(Session, session_id)
            rows = list(
                (
                    await db.execute(
                        select(Message)
                        .where(Message.session_id == session_id)
                        .order_by(Message.created_at.asc())
                    )
                ).scalars().all()
            )
            with patch.object(runtime, "_build_summary_llm", return_value=_SchemaInvalidSummaryLLM()):
                result = await runtime.run_summary_compaction(
                    db,
                    session,
                    source_rows=rows,
                    cutoff_message_id=rows[-1].id,
                    trigger="worker_message_count",
                )

        self.assertTrue(result.compacted)
        self.assertEqual(result.final_strategy, "reuse_last_good_on_schema_fail")
        self.assertEqual(result.summary_mode, "normal")
        self.assertIn("field_not_allowed_in_stage", result.schema_reasons)
        self.assertEqual(result.summary_payload.get("session_record_summary"), "上一版结构化摘要。")
        self.assertEqual(result.summary_payload.get("summary_quality", {}).get("mode"), "normal")

    async def test_non_json_model_output_triggers_fallback(self):
        session_id = await self._seed_session()

        async with self.SessionFactory() as db:
            session = await db.get(Session, session_id)
            rows = list(
                (
                    await db.execute(
                        select(Message)
                        .where(Message.session_id == session_id)
                        .order_by(Message.created_at.asc())
                    )
                ).scalars().all()
            )
            with patch.object(runtime, "_build_summary_llm", return_value=_NonJsonSummaryLLM()):
                result = await runtime.run_summary_compaction(
                    db,
                    session,
                    source_rows=rows,
                    cutoff_message_id=rows[-1].id,
                    trigger="overflow_fallback_compaction",
                )

        self.assertTrue(result.compacted)
        self.assertEqual(result.summary_mode, "fallback")
        self.assertEqual(result.final_strategy, "fallback_on_error")
        self.assertIn("model_error", result.summary_payload.get("summary_quality", {}).get("audit_reasons", []))

    async def test_compaction_refreshes_field_updated_at_without_overwriting_unchanged_field(self):
        session_id = await self._seed_session()

        async with self.SessionFactory() as db:
            session = await db.get(Session, session_id)
            session.running_summary_state = runtime._normalize_summary_payload(
                {
                    "reply_preference_hint": "先给结论，再展开",
                    "active_entities": [{"canonical_id": "600519.SH", "display_name": "贵州茅台", "status": "active"}],
                    "constraints": ["保留 600519.SH 与关键指标"],
                    "open_loops": ["旧待办"],
                    "session_record_summary": "旧摘要。",
                    "field_updated_at": {"constraints": "2026-04-21T00:00:00Z"},
                }
            )
            session.running_summary = runtime._render_summary_payload_to_markdown(session.running_summary_state)
            await db.commit()

        async with self.SessionFactory() as db:
            session = await db.get(Session, session_id)
            rows = list(
                (
                    await db.execute(
                        select(Message)
                        .where(Message.session_id == session_id)
                        .order_by(Message.created_at.asc())
                    )
                ).scalars().all()
            )
            with patch.object(runtime, "_build_summary_llm", return_value=_StructuredSummaryLLM()):
                result = await runtime.run_summary_compaction(
                    db,
                    session,
                    source_rows=rows,
                    cutoff_message_id=rows[-1].id,
                    trigger="worker_message_count",
                )

        field_updated_at = result.summary_payload.get("field_updated_at") or {}
        self.assertEqual(field_updated_at.get("constraints"), "2026-04-21T00:00:00Z")
        self.assertTrue(field_updated_at.get("open_loops"))
        self.assertTrue(field_updated_at.get("session_record_summary"))
        self.assertNotEqual(field_updated_at.get("open_loops"), "2026-04-21T00:00:00Z")

    async def test_hot_field_prompts_include_schema_examples_and_guardrails(self):
        prompts = [
            runtime._build_prompt_active_entities("请分析中芯国际，先给结论", ["只看 A 股"]),
            runtime._build_prompt_constraints("只看 A 股，不要技术面", ["先给结论"]),
            runtime._build_prompt_reply_preference_hint("先给结论，简洁一点", ["风险优先"]),
        ]

        for prompt in prompts:
            self.assertIn("任务目标：", prompt)
            self.assertIn("输入来源与优先级：", prompt)
            self.assertIn("Do：", prompt)
            self.assertIn("Don't：", prompt)
            self.assertIn("输出 schema：", prompt)
            self.assertIn("正例：", prompt)
            self.assertIn("反例：", prompt)

    async def test_hot_update_schema_gate_allows_empty_non_hot_fields(self):
        payload = runtime._normalize_summary_payload(
            {
                "reply_preference_hint": "先给结论，再展开",
                "active_entities": [{"canonical_id": "300750.SZ", "display_name": "宁德时代", "status": "active"}],
                "constraints": ["当前只看 A 股口径"],
            }
        )

        gate = runtime.run_summary_schema_gate(payload, stage="hot_update")

        self.assertTrue(gate["pass"])
        self.assertEqual(gate["payload"]["reply_preference_hint"], "先给结论，再展开")

    async def test_extract_hot_entities_prefers_real_catalog_symbols_over_topic_phrases(self):
        fake_catalog = [
            {"name": "宁德时代", "ts_code": "300750.SZ"},
            {"name": "比亚迪", "ts_code": "002594.SZ"},
        ]
        with patch("backend.services.entity_resolver._load_stock_catalog", return_value=fake_catalog):
            payload = await runtime.extract_hot_summary_fields(
                current_user_message="先按 A 股口径，对比宁德时代和比亚迪最近一年的盈利能力与估值，先给结论，再给三条依据。",
                recent_user_messages=[],
                previous_payload=None,
            )

        entities = payload.get("active_entities") or []
        display_names = {item.get("display_name") for item in entities}
        canonical_ids = {item.get("canonical_id") for item in entities}
        self.assertEqual(display_names, {"宁德时代", "比亚迪"})
        self.assertEqual(canonical_ids, {"300750.SZ", "002594.SZ"})

    async def test_extract_hot_entities_replaces_target_slot_on_replace_followup(self):
        fake_catalog = [
            {"name": "宁德时代", "ts_code": "300750.SZ"},
            {"name": "比亚迪", "ts_code": "002594.SZ"},
            {"name": "阳光电源", "ts_code": "300274.SZ"},
        ]
        previous_payload = {
            "active_entities": [
                {"canonical_id": "300750.SZ", "display_name": "宁德时代", "status": "active"},
                {"canonical_id": "002594.SZ", "display_name": "比亚迪", "status": "active"},
            ]
        }
        with patch("backend.services.entity_resolver._load_stock_catalog", return_value=fake_catalog):
            payload = await runtime.extract_hot_summary_fields_parallel(
                current_user_message="把第二家公司换成阳光电源，再回答一遍，还是先结论后依据。",
                recent_user_messages=["如果只保留动力电池主线，你更看好谁？沿用刚才的回答风格。"],
                previous_payload=previous_payload,
            )

        entities = payload.get("active_entities") or []
        canonical_ids = [item.get("canonical_id") for item in entities]
        self.assertEqual(canonical_ids, ["300750.SZ", "300274.SZ"])
        self.assertNotIn("002594.SZ", canonical_ids)

    async def test_extract_hot_entities_keeps_anchor_for_additive_followup(self):
        previous_payload = {
            "active_entities": [
                {"canonical_id": "601318.SH", "display_name": "中国平安", "status": "active"},
            ]
        }
        payload = await runtime._resolve_hot_active_entities(
            current_user_message="延续上一题，把它和招行放一起，还是先给结论，再列三条依据。",
            recent_user_messages=[],
            previous_payload=previous_payload,
            candidate_entities=[
                {"canonical_id": "600036.SH", "display_name": "招商银行", "status": "active"},
            ],
        )

        canonical_ids = [item.get("canonical_id") for item in payload]
        self.assertEqual(canonical_ids, ["601318.SH", "600036.SH"])

    async def test_extract_hot_entities_does_not_reuse_recent_entities_for_new_topic(self):
        previous_payload = {
            "active_entities": [
                {"canonical_id": "300750.SZ", "display_name": "宁德时代", "status": "active"},
                {"canonical_id": "300274.SZ", "display_name": "阳光电源", "status": "active"},
            ]
        }
        payload = await runtime._resolve_hot_active_entities(
            current_user_message="平安现在怎么看？",
            recent_user_messages=["把第二家公司换成阳光电源，再回答一遍，还是先结论后依据。"],
            previous_payload=previous_payload,
            candidate_entities=[],
        )

        self.assertEqual(payload, [])

    async def test_resolve_session_rolling_payload_prefers_structured_state(self):
        session = Session(
            id="session-resolve",
            user_id="user-test",
            mode="chat",
            title="resolve",
            running_summary="## Decisions\n- legacy\n## Open TODOs\n- old\n## Constraints/Rules\n- old\n## Pending user asks\n- old\n## Exact identifiers\n- 000001.SH",
        )
        session.running_summary_state = {
            "reply_preference_hint": "先给结论，再展开",
            "active_entities": [{"canonical_id": "600519.SH", "display_name": "贵州茅台", "status": "active"}],
            "constraints": ["当前只看 A 股口径"],
            "open_loops": ["补估值"],
            "session_record_summary": "结构化真源。",
        }

        payload = runtime.resolve_session_rolling_payload(session)
        self.assertEqual(payload.get("session_record_summary"), "结构化真源。")
        self.assertEqual(payload.get("active_entities")[0].get("canonical_id"), "600519.SH")

    async def test_resolve_session_rolling_payload_falls_back_to_markdown(self):
        session = Session(
            id="session-markdown",
            user_id="user-test",
            mode="chat",
            title="markdown",
            running_summary=(
                "## Decisions\n- 讨论贵州茅台\n"
                "## Open TODOs\n- 继续补估值\n"
                "## Constraints/Rules\n- 当前只看 A 股口径\n"
                "## Pending user asks\n- 看估值\n"
                "## Exact identifiers\n- 600519.SH"
            ),
        )
        session.running_summary_state = {"unexpected": "invalid"}

        payload = runtime.resolve_session_rolling_payload(session)
        self.assertEqual(payload.get("session_record_summary"), "讨论贵州茅台")
        self.assertEqual(payload.get("constraints"), ["当前只看 A 股口径"])

    async def test_build_route_summary_slice_only_keeps_active_entities(self):
        payload = runtime.build_route_summary_slice(
            {
                "active_entities": [
                    {
                        "canonical_id": "600519.SH",
                        "display_name": "贵州茅台",
                        "entity_type": "stock",
                        "market": "CN-A",
                        "confidence": "high",
                        "status": "active",
                        "source": "user_explicit",
                    }
                ],
                "constraints": ["当前只看 A 股口径"],
                "reply_preference_hint": "先给结论",
            }
        )
        self.assertEqual(set(payload.keys()), {"active_entities"})
        self.assertEqual(payload["active_entities"][0]["canonical_id"], "600519.SH")
        self.assertNotIn("constraints", payload)

    async def test_build_answer_policy_slice_only_keeps_constraints_and_preference(self):
        payload = runtime.build_answer_policy_slice(
            {
                "active_entities": [{"canonical_id": "600519.SH", "display_name": "贵州茅台"}],
                "constraints": ["当前只看 A 股口径", "回答中不展开技术面分析"],
                "reply_preference_hint": "先给结论，再展开；风险提示优先",
                "open_loops": ["补估值"],
            }
        )
        self.assertEqual(set(payload.keys()), {"constraints", "reply_preference_hint"})
        self.assertEqual(payload["constraints"][0], "当前只看 A 股口径")
        self.assertEqual(payload["reply_preference_hint"], "先给结论，再展开；风险提示优先")

    async def test_format_route_and_answer_policy_context_skip_empty_payload(self):
        self.assertEqual(runtime.format_route_active_entities_context({}), "")
        self.assertEqual(runtime.format_answer_policy_context({}), "")

        route_text = runtime.format_route_active_entities_context(
            {"active_entities": [{"canonical_id": "688981.SH", "display_name": "中芯国际", "status": "active"}]}
        )
        answer_text = runtime.format_answer_policy_context(
            {
                "constraints": ["当前只看 A 股口径"],
                "reply_preference_hint": "先给结论，再展开",
            }
        )
        self.assertIn("Rolling Summary / Route Slice", route_text)
        self.assertIn("688981.SH", route_text)
        self.assertIn("回答策略上下文", answer_text)
        self.assertIn("当前只看 A 股口径", answer_text)

    async def test_apply_route_entity_hot_update_syncs_success_entities(self):
        session_id = await self._seed_session()

        async with self.SessionFactory() as db:
            session = await db.get(Session, session_id)
            session.running_summary_state = {
                "active_entities": [
                    {"canonical_id": "300274.SZ", "display_name": "阳光电源", "status": "active"},
                ],
                "constraints": ["先给结论"],
                "reply_preference_hint": "先给结论，再展开",
                "open_loops": [],
                "session_record_summary": "",
            }
            session.summary_version = 2
            payload, updated_fields = await runtime.apply_route_entity_hot_update(
                session,
                user_message="延续上一题，把它和招行放一起，还是先给结论，再列三条依据。",
                candidate_entities=[
                    {"canonical_id": "601318.SH", "display_name": "中国平安", "entity_type": "stock"},
                    {"canonical_id": "600036.SH", "display_name": "招商银行", "entity_type": "stock"},
                ],
            )

        self.assertEqual(updated_fields, ["active_entities"])
        identifiers = {item.get("canonical_id") for item in payload.get("active_entities") or []}
        self.assertEqual(identifiers, {"300274.SZ", "601318.SH", "600036.SH"})

    async def test_apply_route_entity_hot_update_replaces_target_slot(self):
        session_id = await self._seed_session()

        async with self.SessionFactory() as db:
            session = await db.get(Session, session_id)
            session.running_summary_state = {
                "active_entities": [
                    {"canonical_id": "300750.SZ", "display_name": "宁德时代", "status": "active"},
                    {"canonical_id": "002594.SZ", "display_name": "比亚迪", "status": "active"},
                ],
                "constraints": [],
                "reply_preference_hint": "",
                "open_loops": [],
                "session_record_summary": "",
            }
            session.summary_version = 3
            payload, updated_fields = await runtime.apply_route_entity_hot_update(
                session,
                user_message="把第二家公司换成阳光电源，再回答一遍。",
                candidate_entities=[
                    {"canonical_id": "300750.SZ", "display_name": "宁德时代", "entity_type": "stock"},
                    {"canonical_id": "300274.SZ", "display_name": "阳光电源", "entity_type": "stock"},
                ],
            )

        self.assertEqual(updated_fields, ["active_entities"])
        identifiers = [item.get("canonical_id") for item in payload.get("active_entities") or []]
        self.assertEqual(identifiers, ["300750.SZ", "300274.SZ"])

    async def test_preflight_no_source_rows_writes_skipped_audit_log(self):
        session_id = await self._seed_session()

        async with self.SessionFactory() as db:
            session = await db.get(Session, session_id)
            session.context_token_count = 9999
            await db.commit()

        async with self.SessionFactory() as db:
            session = await db.get(Session, session_id)
            message_ids = [
                row.id
                for row in (
                    await db.execute(
                        select(Message)
                        .where(Message.session_id == session_id)
                        .order_by(Message.created_at.asc())
                    )
                ).scalars().all()
            ]
            with patch.object(runtime, "commit_hot_summary_fields_with_cas", return_value=({}, [])):
                with patch.object(runtime, "refresh_session_context_metrics", return_value=None):
                    with patch.object(runtime.settings, "chat_context_window_tokens", 100):
                        with patch.object(runtime.settings, "stm_summary_reserve_tokens_floor", 1):
                            with patch.object(runtime.settings, "stm_summary_soft_threshold_tokens", 1):
                                with patch.object(runtime.settings, "stm_keep_recent", 10):
                                    result = await runtime.maybe_run_preflight_summary_compaction(
                                        db=db,
                                        session=session,
                                        pending_user_message="继续分析 600519.SH",
                                        exclude_message_ids=set(message_ids),
                                        trigger="preflight_budget_sync_chat",
                                    )

            audit_logs = list(
                (
                    await db.execute(
                        select(SummaryAuditLog)
                        .where(SummaryAuditLog.session_id == session_id)
                        .order_by(SummaryAuditLog.id.asc())
                    )
                ).scalars().all()
            )

        self.assertFalse(result.compacted)
        self.assertEqual(result.reason, "no_preflight_source_rows")
        self.assertTrue(audit_logs)
        self.assertEqual(audit_logs[-1].status, "skipped")
        self.assertEqual(audit_logs[-1].reason, "no_preflight_source_rows")

    async def test_should_run_preflight_summary_compaction_uses_threshold(self):
        session = Session(
            id="session-preflight",
            user_id="user-test",
            mode="chat",
            title="test",
            context_token_count=93000,
        )
        with patch.object(runtime.settings, "chat_context_window_tokens", 100000):
            with patch.object(runtime.settings, "stm_summary_reserve_tokens_floor", 5000):
                with patch.object(runtime.settings, "stm_summary_soft_threshold_tokens", 2000):
                    with patch.object(runtime.settings, "stm_summary_overhead_tokens", 1000):
                        decision = runtime.should_run_preflight_summary_compaction(
                            session,
                            "继续分析 600519.SH",
                        )

        self.assertTrue(decision.should_compact)
        self.assertEqual(decision.threshold_tokens, 93000)
        self.assertGreaterEqual(decision.projected_tokens, 93000)

    async def test_preflight_runtime_emits_observation_logs(self):
        session_id = await self._seed_session()

        async with self.SessionFactory() as db:
            session = await db.get(Session, session_id)
            with patch.object(runtime.settings, "enable_stm", True):
                with patch.object(runtime.settings, "stm_summary_preflight_enabled", True):
                    with patch.object(runtime.settings, "stm_keep_recent", 1):
                        with patch.object(runtime.settings, "chat_context_window_tokens", 40):
                            with patch.object(runtime.settings, "stm_summary_reserve_tokens_floor", 4):
                                with patch.object(runtime.settings, "stm_summary_soft_threshold_tokens", 4):
                                    with patch.object(runtime.settings, "stm_summary_overhead_tokens", 4):
                                        with patch.object(runtime, "_build_summary_llm", return_value=_StructuredSummaryLLM()):
                                            with self.assertLogs("stm_summary_runtime", level="INFO") as captured:
                                                result = await runtime.maybe_run_preflight_summary_compaction(
                                                    db=db,
                                                    session=session,
                                                    pending_user_message="继续分析 600519.SH",
                                                    system_prompt_text="system",
                                                    memory_prompt_text="memory",
                                                    trigger="preflight_budget_sync_chat",
                                                )

        self.assertTrue(result.compacted)
        joined = "\n".join(captured.output)
        self.assertIn("event=preflight_decision", joined)
        self.assertIn("event=preflight_result", joined)


if __name__ == "__main__":
    unittest.main()
