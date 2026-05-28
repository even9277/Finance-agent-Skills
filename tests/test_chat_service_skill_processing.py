import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from backend.services import chat_service
from backend.schemas.chat import ChatContextWindow

_AGENT_ROOT = Path(__file__).resolve().parent.parent / "Financial-MCP-Agent"
if str(_AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENT_ROOT))


class ChatServiceSkillProcessingTests(unittest.IsolatedAsyncioTestCase):
    def test_validate_requested_sop_skill_id_normalizes_blank(self):
        self.assertIsNone(chat_service.validate_requested_sop_skill_id("   "))

    def test_validate_requested_sop_skill_id_rejects_unknown_skill(self):
        with self.assertRaises(chat_service.InvalidSopSkillError):
            chat_service.validate_requested_sop_skill_id("not-exist")

    def test_resolve_sop_skill_id_prefers_skill_name_over_family(self):
        from src.agents.skill_router_node import SkillRouteDecision

        decision = SkillRouteDecision(route="sop", skill_id="stock-first-pass", execution_policy="deterministic")
        route_trace = {
            "selected_skill_family": "financial-sop",
            "selected_skill": "financial-sop",
            "skill_name": "stock-first-pass",
        }
        self.assertEqual(
            chat_service._resolve_sop_skill_id(route_trace, decision),
            "stock-first-pass",
        )

    def test_resolve_sop_skill_id_falls_back_to_decision_skill_id(self):
        from src.agents.skill_router_node import SkillRouteDecision

        decision = SkillRouteDecision(route="sop", skill_id="fund-compare", execution_policy="deterministic")
        route_trace = {"selected_skill": "financial-sop", "selected_skill_family": "financial-sop"}
        self.assertEqual(chat_service._resolve_sop_skill_id(route_trace, decision), "fund-compare")

    async def test_run_skill_chat_sop_v2_loads_spec_by_concrete_skill_id(self):
        from src.agents.skill_router_node import SkillRouteDecision

        fake_session = SimpleNamespace(
            id="sess-sop-v2",
            running_summary="",
            running_summary_state={},
            working_state={},
        )
        rewrite_result = SimpleNamespace(
            effective_query="中芯国际最近怎么样",
            skill_params={},
            entities=[],
        )
        decision = SkillRouteDecision(route="sop", skill_id="stock-first-pass", execution_policy="deterministic")
        registry_mock = MagicMock()
        registry_mock.load_skill_spec.return_value = {"skill_name": "stock-first-pass"}
        v2_result = SimpleNamespace(tool_data=lambda: {"executor_trace": {"plan_id": "p1"}})

        with patch.object(chat_service.settings, "enable_chat_skills", True):
            with patch.object(chat_service.settings, "enable_sop_v2", True):
                with patch.object(chat_service.settings, "enable_entity_resolver_v2", False):
                    with patch.object(chat_service, "_ensure_skill_runtime_ready"):
                        with patch.object(
                            chat_service,
                            "_load_memory_context_for_chat",
                            new=AsyncMock(return_value=({}, "")),
                        ):
                            with patch.object(
                                chat_service,
                                "_build_skill_route_context",
                                new=AsyncMock(return_value="route ctx"),
                            ):
                                with patch.object(
                                    chat_service,
                                    "_resolve_entity_hint_for_route",
                                    new=AsyncMock(return_value=None),
                                ):
                                    with patch.object(
                                        chat_service,
                                        "route_chat_skill",
                                        new=AsyncMock(return_value=decision),
                                    ):
                                        with patch.object(
                                            chat_service,
                                            "rewrite_for_sop",
                                            new=AsyncMock(return_value=rewrite_result),
                                        ):
                                            with patch.object(
                                                chat_service,
                                                "_run_post_rewrite_extractors_if_enabled",
                                                new=AsyncMock(),
                                            ):
                                                with patch.object(
                                                    chat_service,
                                                    "get_skill_registry",
                                                    return_value=registry_mock,
                                                ):
                                                    with patch.object(
                                                        chat_service,
                                                        "run_sop_v2_pipeline",
                                                        new=AsyncMock(return_value=v2_result),
                                                    ) as pipeline_mock:
                                                        with patch.object(
                                                            chat_service,
                                                            "summarize_sop_reply",
                                                            new=AsyncMock(return_value="SOP v2 回复"),
                                                        ):
                                                            reply, _, trace, _ = await chat_service._run_skill_chat_if_enabled(
                                                                db=object(),
                                                                session=fake_session,
                                                                user_id="user-1",
                                                                user_message="中芯国际最近怎么样",
                                                            )

        registry_mock.load_skill_spec.assert_called_once_with("stock-first-pass")
        pipeline_mock.assert_awaited_once()
        self.assertEqual(pipeline_mock.await_args.kwargs["skill_name"], "stock-first-pass")
        self.assertEqual(reply, "SOP v2 回复")
        self.assertEqual(trace.get("skill_name"), "stock-first-pass")
        self.assertEqual(trace.get("selected_skill"), "financial-sop")

    async def test_prepare_reply_handles_action_before_strip(self):
        raw_reply = (
            "这是正常回答。\n"
            '<action>{"action":"update_profile","field":"sectors","value":["黄金"]}</action>'
        )
        fake_db = object()

        with patch.object(chat_service.settings, "enable_memory", True):
            with patch.object(
                chat_service,
                "_handle_profile_action_in_reply",
                new=AsyncMock(),
            ) as handle_mock:
                cleaned = await chat_service._prepare_reply_for_user(
                    raw_reply,
                    user_id="user-1",
                    db=fake_db,
                )

        handle_mock.assert_awaited_once_with(raw_reply, "user-1", fake_db)
        self.assertIn("这是正常回答", cleaned)
        self.assertNotIn("<action>", cleaned)

    async def test_run_skill_chat_uses_explicit_sop_without_llm_router(self):
        fake_session = SimpleNamespace(
            id="sess-1",
            running_summary="旧全文摘要不应再注入",
            running_summary_state={
                "active_entities": [{"canonical_id": "518880.SH", "display_name": "黄金ETF", "status": "active"}],
                "constraints": ["当前只看 A 股口径"],
                "reply_preference_hint": "先给结论，再展开",
                "open_loops": [],
                "session_record_summary": "结构化摘要",
            },
            working_state={},
        )
        rewrite_result = SimpleNamespace(effective_query="对比两只黄金 ETF", skill_params={}, entities=[])
        execute_result = SimpleNamespace(trace={"reply_mode": "skill", "used_tools": True})

        with patch.object(chat_service.settings, "enable_chat_skills", True):
            with patch.object(chat_service.settings, "enable_sop_v2", False):
                with patch.object(chat_service.settings, "enable_entity_resolver_v2", False):
                    with patch.object(
                        chat_service,
                        "_load_memory_context_for_chat",
                        new=AsyncMock(return_value=({}, "")),
                    ):
                        with patch.object(
                            chat_service,
                            "_build_skill_route_context",
                            new=AsyncMock(return_value="route ctx"),
                        ):
                            with patch.object(
                                chat_service,
                                "route_chat_skill",
                                new=AsyncMock(),
                            ) as router_mock:
                                with patch.object(
                                    chat_service,
                                    "rewrite_for_sop",
                                    new=AsyncMock(return_value=rewrite_result),
                                ):
                                    with patch.object(
                                        chat_service,
                                        "_run_post_rewrite_extractors_if_enabled",
                                        new=AsyncMock(),
                                    ):
                                        with patch.object(
                                            chat_service,
                                            "execute_skill",
                                            new=AsyncMock(return_value=execute_result),
                                        ) as execute_mock:
                                            with patch.object(
                                                chat_service,
                                                "summarize_sop_reply",
                                                new=AsyncMock(return_value="显式 SOP 回复"),
                                            ) as summarize_mock:
                                                reply, _, trace, _ = await chat_service._run_skill_chat_if_enabled(
                                                    db=object(),
                                                    session=fake_session,
                                                    user_id="user-1",
                                                    user_message="帮我比较两只黄金 ETF",
                                                    sop_skill_id="fund-compare",
                                                )

        router_mock.assert_not_awaited()
        self.assertEqual(execute_mock.await_args.kwargs["answer_policy_context"].splitlines()[0], "【回答策略上下文】")
        self.assertNotIn("旧全文摘要不应再注入", execute_mock.await_args.kwargs["answer_policy_context"])
        self.assertIn("当前只看 A 股口径", summarize_mock.await_args.kwargs["answer_policy_context"])
        self.assertEqual(reply, "显式 SOP 回复")
        self.assertEqual(trace.get("selected_skill"), "financial-sop")
        self.assertEqual(trace.get("skill_name"), "fund-compare")
        self.assertEqual(trace.get("confidence"), 1.0)

    async def test_build_fallback_chat_messages_uses_answer_policy_context_instead_of_full_summary(self):
        fake_session = SimpleNamespace(
            id="sess-fallback",
            running_summary="旧全文摘要",
            running_summary_state={
                "constraints": ["当前只看 A 股口径"],
                "reply_preference_hint": "先给结论，再展开",
                "active_entities": [{"canonical_id": "600519.SH", "display_name": "贵州茅台", "status": "active"}],
                "open_loops": [],
                "session_record_summary": "摘要",
            },
            turn_count=3,
        )
        fake_result = SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: []))
        fake_db = SimpleNamespace(execute=AsyncMock(return_value=fake_result))

        with patch.object(chat_service.settings, "enable_stm", True):
            messages = await chat_service._build_fallback_chat_messages(
                fake_db,
                fake_session,
                memory_system_prompt="",
            )

        system_contents = [getattr(item, "content", "") for item in messages if item.__class__.__name__ == "SystemMessage"]
        joined = "\n".join(system_contents)
        self.assertIn("【回答策略上下文】", joined)
        self.assertIn("当前只看 A 股口径", joined)
        self.assertNotIn("旧全文摘要", joined)

    async def test_chat_single_turn_runs_preflight_before_skill_execution(self):
        next_message_id = 100

        def add_obj(obj):
            nonlocal next_message_id
            if getattr(obj, "id", None) is None and hasattr(obj, "role"):
                obj.id = next_message_id
                next_message_id += 1

        fake_db = SimpleNamespace(
            add=add_obj,
            flush=AsyncMock(),
            commit=AsyncMock(),
            refresh=AsyncMock(),
        )
        fake_session = SimpleNamespace(
            id="sess-1",
            title="",
            running_summary="",
            turn_count=0,
            updated_at=None,
        )
        order: list[str] = []
        context_window = ChatContextWindow(
            used_tokens=100,
            budget_tokens=900,
            usage_percent=10,
            counting_mode="estimated",
            compression_status="idle",
            strategy="message_count",
        )

        async def _prepare_inputs(*args, **kwargs):
            order.append("prepare")
            return {}, "memory prompt"

        async def _preflight(*args, **kwargs):
            order.append("preflight")

        async def _run_skill(*args, **kwargs):
            order.append("skill")
            return "同步回复", {}, {}, "memory prompt"

        with patch.object(chat_service, "get_or_create_session", new=AsyncMock(return_value=fake_session)):
            with patch.object(chat_service.settings, "enable_chat_skills", False):
                with patch.object(chat_service.settings, "enable_memory", False):
                    with patch.object(chat_service, "_handle_profile_action_in_user_message", new=AsyncMock(side_effect=lambda _db, _uid, msg: msg)):
                        with patch.object(chat_service, "_prepare_chat_preflight_inputs", new=AsyncMock(side_effect=_prepare_inputs)):
                            with patch.object(chat_service, "_run_chat_preflight_compaction", new=AsyncMock(side_effect=_preflight)):
                                with patch.object(chat_service, "_run_skill_chat_if_enabled", new=AsyncMock(side_effect=_run_skill)):
                                    with patch.object(chat_service, "_prepare_reply_for_user", new=AsyncMock(return_value="同步回复")):
                                        with patch.object(chat_service, "_record_route_runtime_with_log"):
                                            with patch.object(chat_service, "_build_route_summary", return_value=None):
                                                with patch.object(chat_service, "refresh_session_context_metrics", new=AsyncMock(return_value=context_window)):
                                                    result = await chat_service.chat_single_turn(
                                                        db=fake_db,
                                                        user_id="user-1",
                                                        user_message="继续分析贵州茅台",
                                                    )

        self.assertEqual(result[0], "同步回复")
        self.assertEqual(order[:3], ["prepare", "preflight", "skill"])

    def test_route_trace_to_summary_entities_collects_resolved_and_compared_entities(self):
        route_trace = {
            "selected_skill": "tushare-data",
            "arguments": {
                "resolved_entity_hint": {
                    "symbol": "601318.SH",
                    "display_name": "中国平安",
                    "asset_type": "stock",
                },
                "entities": [
                    {"symbol": "601318.SH", "display_name": "中国平安", "asset_type": "stock"},
                    {"symbol": "600036.SH", "display_name": "招商银行", "asset_type": "stock"},
                ],
            },
            "executor": {
                "evidence_ok": True,
                "resolved_symbol": "601318.SH",
                "resolved_company": "中国平安",
            },
        }

        entities = chat_service._route_trace_to_summary_entities(route_trace)
        identifiers = {item["canonical_id"] for item in entities}
        self.assertEqual(identifiers, {"601318.SH", "600036.SH"})

    async def test_apply_route_entities_to_stm_with_log_skips_fallback(self):
        fake_db = SimpleNamespace(flush=AsyncMock())
        fake_session = SimpleNamespace(id="sess-1")

        with patch.object(chat_service.settings, "enable_stm", True):
            with patch.object(chat_service, "apply_route_entity_hot_update", new=AsyncMock()) as update_mock:
                updated = await chat_service._apply_route_entities_to_stm_with_log(
                    db=fake_db,
                    session=fake_session,
                    user_message="平安现在怎么看？",
                    route_trace={"selected_skill": "fallback", "executor": {"evidence_ok": False}},
                )

        self.assertEqual(updated, [])
        update_mock.assert_not_awaited()

    async def test_stream_chat_single_turn_emits_pre_compaction_status_frames(self):
        next_message_id = 200

        def add_obj(obj):
            nonlocal next_message_id
            if getattr(obj, "id", None) is None and hasattr(obj, "role"):
                obj.id = next_message_id
                next_message_id += 1

        fake_db = SimpleNamespace(
            add=add_obj,
            flush=AsyncMock(),
            commit=AsyncMock(),
            refresh=AsyncMock(),
        )
        fake_session = SimpleNamespace(
            id="sess-stream",
            title="",
            running_summary="新的摘要",
            running_summary_mode="hot_update",
            turn_count=0,
            updated_at=None,
            compression_status="idle",
        )
        context_window = ChatContextWindow(
            used_tokens=120,
            budget_tokens=880,
            usage_percent=12,
            counting_mode="estimated",
            compression_status="idle",
            strategy="message_count",
        )
        preflight_result = SimpleNamespace(compacted=True, reason="ok")

        with patch.object(chat_service, "get_or_create_session", new=AsyncMock(return_value=fake_session)):
            with patch.object(chat_service.settings, "enable_chat_skills", False):
                with patch.object(chat_service.settings, "enable_memory", False):
                    with patch.object(chat_service.settings, "enable_stm", True):
                        with patch.object(chat_service.settings, "stm_summary_preflight_enabled", True):
                            with patch.object(chat_service, "_handle_profile_action_in_user_message", new=AsyncMock(side_effect=lambda _db, _uid, msg: msg)):
                                with patch.object(chat_service, "_prepare_chat_preflight_inputs", new=AsyncMock(return_value=({}, "memory prompt"))):
                                    with patch.object(
                                        chat_service,
                                        "should_run_preflight_summary_compaction",
                                        return_value=SimpleNamespace(should_compact=True),
                                    ):
                                        with patch.object(chat_service, "refresh_session_context_metrics", new=AsyncMock(return_value=context_window)):
                                            with patch.object(chat_service, "maybe_run_preflight_summary_compaction", new=AsyncMock(return_value=preflight_result)):
                                                with patch.object(chat_service, "_run_skill_chat_if_enabled", new=AsyncMock(return_value=("流式回复", {}, {}, "memory prompt"))):
                                                    with patch.object(chat_service, "_prepare_reply_for_user", new=AsyncMock(return_value="流式回复")):
                                                        with patch.object(chat_service, "_record_route_runtime_with_log"):
                                                            with patch.object(chat_service, "_build_route_summary", return_value=None):
                                                                frames = []
                                                                async for chunk in chat_service.stream_chat_single_turn(
                                                                    db=fake_db,
                                                                    user_id="user-1",
                                                                    user_message="继续分析贵州茅台",
                                                                ):
                                                                    frames.append(chunk)

        joined = "\n".join(frames)
        self.assertIn('"type": "task_status_running"', joined)
        self.assertIn('"task_kind": "pre_compaction"', joined)
        self.assertIn('"type": "task_status_done"', joined)


if __name__ == "__main__":
    unittest.main()
