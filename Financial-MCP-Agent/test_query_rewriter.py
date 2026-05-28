import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.agents.query_rewriter import (
    EntityResolution,
    FallbackRewriteResult,
    SopRewriteResult,
    ToolPlanStep,
    TushareRewriteResult,
    _FALLBACK_REWRITER_SYSTEM_PROMPT,
    _SOP_REWRITER_SYSTEM_PROMPT,
    _TUSHARE_REWRITER_SYSTEM_PROMPT,
    _build_toolkit_catalog,
    _sanitize_effective_query,
    _load_skill_doc_sections,
    _schema_json,
    _validate_tushare_plan,
    rewrite_for_fallback,
    rewrite_for_sop,
    rewrite_for_tushare,
)
from src.agents.skill_spec_planner import build_skill_tool_plan
from src.agents.skill_router_node import SkillRouteDecision
from src.agents.tushare_plan_executor import execute_tushare_plan
from src.skills.skill_registry import get_skill_registry


class QueryRewriterTests(unittest.TestCase):
    def test_load_skill_doc_sections_reads_required_blocks(self):
        sections = _load_skill_doc_sections("fund-compare")
        self.assertIn("inputs", sections)
        self.assertIn("decision_rules", sections)
        self.assertIn("output_template", sections)
        self.assertIn("fallbacks", sections)
        self.assertTrue(isinstance(sections.get("allowed_tools"), list))

    def test_build_toolkit_catalog_uses_tool_names(self):
        catalog = _build_toolkit_catalog()
        self.assertIn("get_stock_basic_info", catalog)
        self.assertIn("get_market_bars", catalog)

    def test_rewriter_prompts_limit_summary_usage_to_active_entities(self):
        self.assertIn("rolling-summary 可用字段只有 active_entities", _SOP_REWRITER_SYSTEM_PROMPT)
        self.assertIn("这是 route slice + 最近对话，不是全文 STM", _SOP_REWRITER_SYSTEM_PROMPT)
        self.assertIn("rolling-summary 可用字段只有 active_entities", _FALLBACK_REWRITER_SYSTEM_PROMPT)
        self.assertIn("[Latest User Message]", _TUSHARE_REWRITER_SYSTEM_PROMPT)
        self.assertIn("以最新用户消息为准", _TUSHARE_REWRITER_SYSTEM_PROMPT)

    def test_schema_json_disallows_additional_properties(self):
        schema = _schema_json(SopRewriteResult)
        self.assertIn('"additionalProperties": false', schema)

    def test_validate_tushare_plan_rejects_cycle(self):
        payload = TushareRewriteResult(
            effective_query="test",
            entities=[],
            tool_plan=[
                ToolPlanStep(tool_name="get_stock_basic_info", arguments={"query": "a"}, depends_on=[1]),
                ToolPlanStep(tool_name="get_fina_indicator", arguments={"query": "a"}, depends_on=[0]),
            ],
        )
        with self.assertRaises(ValueError):
            _validate_tushare_plan(payload)

    def test_validate_tushare_plan_rejects_out_of_range_dependency(self):
        payload = TushareRewriteResult(
            effective_query="test",
            entities=[],
            tool_plan=[
                ToolPlanStep(tool_name="get_stock_basic_info", arguments={"query": "a"}, depends_on=[2]),
            ],
        )
        with self.assertRaises(ValueError):
            _validate_tushare_plan(payload)

    def test_validate_tushare_plan_rejects_empty_plan(self):
        payload = TushareRewriteResult(
            effective_query="test",
            entities=[],
            tool_plan=[],
        )
        with self.assertRaises(ValueError):
            _validate_tushare_plan(payload)

    def test_rewrite_for_sop_degrades_when_parse_failed(self):
        decision = SkillRouteDecision(route="sop", skill_id="fund-compare", execution_policy="deterministic")
        with patch(
            "src.agents.query_rewriter._invoke_structured",
            new=AsyncMock(side_effect=RuntimeError("parse error")),
        ):
            result = asyncio.run(
                rewrite_for_sop(
                    decision,
                    user_message="帮我比较华安黄金ETF和博时黄金ETF",
                    stm_snapshot="用户: 比较这两个ETF",
                    ltm_summary="风险偏好: balanced",
                )
            )
        self.assertEqual(result.effective_query, "帮我比较华安黄金ETF和博时黄金ETF")
        self.assertEqual(result.entities, [])
        self.assertEqual(result.skill_params, {})

    def test_rewrite_for_sop_keeps_structured_output(self):
        decision = SkillRouteDecision(route="sop", skill_id="fund-compare", execution_policy="deterministic")
        mocked = SopRewriteResult(
            effective_query="对比华安黄金ETF和博时黄金ETF",
            entities=[],
            skill_params={"response_pref": "risk_first"},
        )
        with patch("src.agents.query_rewriter._invoke_structured", new=AsyncMock(return_value=mocked)):
            result = asyncio.run(
                rewrite_for_sop(
                    decision,
                    user_message="帮我对比这两个黄金ETF",
                    stm_snapshot="用户: 对比这两个",
                    ltm_summary="风险偏好: balanced",
                )
            )
        self.assertEqual(result.effective_query, "对比华安黄金ETF和博时黄金ETF")
        self.assertEqual(result.skill_params.get("response_pref"), "risk_first")

    def test_rewrite_for_sop_injects_resolver_hint_entity(self):
        decision = SkillRouteDecision(route="sop", skill_id="stock-first-pass", execution_policy="deterministic")
        mocked = SopRewriteResult(
            effective_query="它现在估值怎么样",
            entities=[],
            skill_params={},
        )
        with patch("src.agents.query_rewriter._invoke_structured", new=AsyncMock(return_value=mocked)):
            result = asyncio.run(
                rewrite_for_sop(
                    decision,
                    user_message="它现在估值怎么样",
                    stm_snapshot="用户: 刚才聊过贵州茅台",
                    ltm_summary="",
                    resolver_hint={
                        "display_name": "贵州茅台",
                        "asset_type": "stock",
                        "symbol": "600519.SH",
                        "confidence": 0.98,
                    },
                )
            )
        self.assertTrue(result.entities)
        self.assertEqual(result.entities[0].display_name, "贵州茅台")
        self.assertEqual(result.entities[0].symbol, "600519.SH")

    def test_rewrite_for_sop_normalizes_sector_contract(self):
        decision = SkillRouteDecision(route="sop", skill_id="sector-hotspot-brief", execution_policy="deterministic")
        mocked = SopRewriteResult(
            effective_query="新能源板块最近行情怎么样",
            entities=[],
            skill_params={},
        )
        sector_resolution = {
            "requested_name": "新能源板块最近行情怎么样",
            "cleaned_name": "新能源",
            "normalized_sector_name": "电力设备",
            "index_code": "801730.SI",
            "match_confidence": 0.84,
            "candidate_sector_names": ["电力设备", "汽车", "公用事业"],
            "failure_code": "",
            "error": "",
        }
        with patch("src.agents.query_rewriter._invoke_structured", new=AsyncMock(return_value=mocked)):
            with patch("src.agents.query_rewriter.resolve_sector_request", new=AsyncMock(return_value=sector_resolution)):
                result = asyncio.run(
                    rewrite_for_sop(
                        decision,
                        user_message="新能源板块最近行情怎么样",
                        stm_snapshot="",
                        ltm_summary="",
                    )
                )
        self.assertEqual(result.skill_params.get("sector_name"), "电力设备")
        self.assertEqual(result.skill_params.get("index_code"), "801730.SI")
        self.assertFalse(result.skill_params.get("need_clarification"))
        self.assertAlmostEqual(result.skill_params.get("match_confidence"), 0.84)

    def test_rewrite_for_sop_marks_sector_ambiguity_for_clarification(self):
        decision = SkillRouteDecision(route="sop", skill_id="sector-hotspot-brief", execution_policy="deterministic")
        mocked = SopRewriteResult(
            effective_query="科技板块怎么样",
            entities=[],
            skill_params={},
        )
        sector_resolution = {
            "requested_name": "科技板块怎么样",
            "cleaned_name": "科技",
            "normalized_sector_name": "",
            "index_code": "",
            "match_confidence": 0.0,
            "candidate_sector_names": ["电子", "计算机", "通信", "传媒"],
            "failure_code": "sector_ambiguous",
            "error": "multiple sector candidates matched",
        }
        with patch("src.agents.query_rewriter._invoke_structured", new=AsyncMock(return_value=mocked)):
            with patch("src.agents.query_rewriter.resolve_sector_request", new=AsyncMock(return_value=sector_resolution)):
                result = asyncio.run(
                    rewrite_for_sop(
                        decision,
                        user_message="科技板块怎么样",
                        stm_snapshot="",
                        ltm_summary="",
                    )
                )
        self.assertTrue(result.skill_params.get("need_clarification"))
        self.assertEqual(result.skill_params.get("failure_code"), "sector_ambiguous")
        self.assertIn("电子", result.skill_params.get("clarification_question", ""))

    def test_rewrite_for_sop_sanitizes_punctuation_only_query(self):
        decision = SkillRouteDecision(route="sop", skill_id="fund-compare", execution_policy="deterministic")
        mocked = SopRewriteResult(
            effective_query=":",
            entities=[],
            skill_params={},
        )
        with patch("src.agents.query_rewriter._invoke_structured", new=AsyncMock(return_value=mocked)):
            result = asyncio.run(
                rewrite_for_sop(
                    decision,
                    user_message="518880.SH和159937.SZ对比",
                    stm_snapshot="用户: 对比两个黄金ETF",
                    ltm_summary="",
                )
            )
        self.assertEqual(result.effective_query, "518880.SH和159937.SZ对比")

    def test_rewrite_for_tushare_illegal_tool_degrades_to_single_step(self):
        decision = SkillRouteDecision(route="tushare", skill_id=None, execution_policy="deterministic")
        bad = {
            "effective_query": "贵州茅台今天怎么样",
            "entities": [],
            "tool_plan": [
                {
                    "tool_name": "get_not_exists_tool",
                    "arguments": {"query": "贵州茅台"},
                    "depends_on": None,
                }
            ],
        }
        with patch("src.agents.query_rewriter._invoke_structured", new=AsyncMock(side_effect=[bad, bad])):
            result = asyncio.run(
                rewrite_for_tushare(
                    decision,
                    user_message="贵州茅台今天怎么样",
                    stm_snapshot="用户: 今天怎么样",
                    ltm_summary="",
                )
            )
        self.assertEqual(len(result.tool_plan), 1)
        self.assertEqual(result.tool_plan[0].tool_name, "get_market_bars")

    def test_rewrite_for_tushare_refine_second_pass(self):
        decision = SkillRouteDecision(route="tushare", skill_id=None, execution_policy="deterministic")
        first = TushareRewriteResult(
            effective_query="贵州茅台今天怎么样",
            entities=[],
            tool_plan=[
                ToolPlanStep(tool_name="get_stock_basic_info", arguments={"query": "贵州茅台"}, depends_on=None),
            ],
        )
        second = TushareRewriteResult(
            effective_query="贵州茅台今天怎么样",
            entities=[],
            tool_plan=[
                ToolPlanStep(tool_name="get_stock_basic_info", arguments={"query": "贵州茅台"}, depends_on=None),
                ToolPlanStep(tool_name="get_market_bars", arguments={"query": "贵州茅台"}, depends_on=[0]),
            ],
        )
        with patch("src.agents.query_rewriter._invoke_structured", new=AsyncMock(side_effect=[first, second])):
            result = asyncio.run(
                rewrite_for_tushare(
                    decision,
                    user_message="贵州茅台今天怎么样",
                    stm_snapshot="用户: 今天怎么样",
                    ltm_summary="",
                )
        )
        self.assertEqual(len(result.tool_plan), 2)
        self.assertEqual(result.tool_plan[1].depends_on, [0])

    def test_rewrite_for_tushare_refine_empty_plan_falls_back_to_first_pass(self):
        decision = SkillRouteDecision(route="tushare", skill_id=None, execution_policy="deterministic")
        first = TushareRewriteResult(
            effective_query="贵州茅台今天怎么样",
            entities=[],
            tool_plan=[
                ToolPlanStep(tool_name="get_stock_basic_info", arguments={"query": "贵州茅台"}, depends_on=None),
            ],
        )
        second = TushareRewriteResult(
            effective_query="贵州茅台今天怎么样",
            entities=[],
            tool_plan=[],
        )
        with patch("src.agents.query_rewriter._invoke_structured", new=AsyncMock(side_effect=[first, second])):
            result = asyncio.run(
                rewrite_for_tushare(
                    decision,
                    user_message="贵州茅台今天怎么样",
                    stm_snapshot="用户: 今天怎么样",
                    ltm_summary="",
                )
            )
        self.assertEqual(len(result.tool_plan), 1)
        self.assertEqual(result.tool_plan[0].tool_name, "get_stock_basic_info")

    def test_rewrite_for_tushare_sanitizes_punctuation_only_query(self):
        decision = SkillRouteDecision(route="tushare", skill_id=None, execution_policy="deterministic")
        first = TushareRewriteResult(
            effective_query="贵州茅台今天怎么样",
            entities=[],
            tool_plan=[
                ToolPlanStep(tool_name="get_stock_basic_info", arguments={"query": "贵州茅台"}, depends_on=None),
            ],
        )
        second = TushareRewriteResult(
            effective_query=":",
            entities=[],
            tool_plan=[
                ToolPlanStep(tool_name="get_stock_basic_info", arguments={"query": "贵州茅台"}, depends_on=None),
            ],
        )
        with patch("src.agents.query_rewriter._invoke_structured", new=AsyncMock(side_effect=[first, second])):
            result = asyncio.run(
                rewrite_for_tushare(
                    decision,
                    user_message="贵州茅台今天怎么样",
                    stm_snapshot="",
                    ltm_summary="",
                )
            )
        self.assertEqual(result.effective_query, "贵州茅台今天怎么样")

    def test_sanitize_effective_query_rejects_stale_prior_question(self):
        candidate = "对比宁德时代和比亚迪最近一年的盈利能力与估值"
        latest = "如果只保留动力电池主线，你更看好谁？沿用刚才的回答风格。"
        self.assertEqual(_sanitize_effective_query(candidate, latest), latest)

    def test_rewrite_for_tushare_prefers_latest_follow_up_intent(self):
        decision = SkillRouteDecision(route="tushare", skill_id=None, execution_policy="deterministic")
        stale = TushareRewriteResult(
            effective_query="对比宁德时代和比亚迪最近一年的盈利能力与估值",
            entities=[],
            tool_plan=[
                ToolPlanStep(tool_name="get_stock_basic_info", arguments={"query": "宁德时代"}, depends_on=None),
            ],
        )
        with patch("src.agents.query_rewriter._invoke_structured", new=AsyncMock(side_effect=[stale, stale])):
            result = asyncio.run(
                rewrite_for_tushare(
                    decision,
                    user_message="如果只保留动力电池主线，你更看好谁？沿用刚才的回答风格。",
                    stm_snapshot="【Rolling Summary / Route Slice】\n- 宁德时代\n- 比亚迪",
                    ltm_summary="",
                )
            )
        self.assertEqual(result.effective_query, "如果只保留动力电池主线，你更看好谁？沿用刚才的回答风格。")

    def test_rewrite_for_tushare_injects_resolver_hint_entity(self):
        decision = SkillRouteDecision(route="tushare", skill_id=None, execution_policy="deterministic")
        first = TushareRewriteResult(
            effective_query="新能源板块最近行情怎么样",
            entities=[],
            tool_plan=[
                ToolPlanStep(tool_name="get_sector_snapshot", arguments={"query": "新能源板块"}, depends_on=None),
            ],
        )
        second = TushareRewriteResult(
            effective_query="新能源板块最近行情怎么样",
            entities=[],
            tool_plan=[
                ToolPlanStep(tool_name="get_sector_snapshot", arguments={"query": "新能源板块"}, depends_on=None),
            ],
        )
        with patch("src.agents.query_rewriter._invoke_structured", new=AsyncMock(side_effect=[first, second])):
            result = asyncio.run(
                rewrite_for_tushare(
                    decision,
                    user_message="新能源板块最近行情怎么样",
                    stm_snapshot="",
                    ltm_summary="",
                    resolver_hint={
                        "display_name": "电力设备",
                        "asset_type": "sector",
                        "symbol": "801730.SI",
                        "confidence": 0.84,
                    },
                )
            )
        self.assertTrue(result.entities)
        self.assertEqual(result.entities[0], EntityResolution(display_name="电力设备", asset_type="sector", symbol="801730.SI"))

    def test_rewrite_for_fallback_degrades_to_original_query(self):
        with patch("src.agents.query_rewriter._invoke_structured", new=AsyncMock(side_effect=RuntimeError("bad json"))):
            result = asyncio.run(
                rewrite_for_fallback(
                    user_message="继续上一个问题",
                    stm_snapshot="用户: 我问了半导体",
                    ltm_summary="风险偏好: balanced",
                )
            )
        self.assertIsInstance(result, FallbackRewriteResult)
        self.assertEqual(result.effective_query, "继续上一个问题")

    def test_planner_does_not_blindly_inject_non_executable_skill_params(self):
        skill_spec = get_skill_registry().load_skill_spec("etf-screen") or {}
        plan = build_skill_tool_plan(
            skill_name="etf-screen",
            skill_spec=skill_spec,
            user_message="给我筛选黄金ETF",
            resolved_entities=[],
            skill_params={"holding_period": "6m", "response_pref": "risk_first", "effective_query": ":"},
        )
        self.assertGreater(len(plan.tool_calls), 0)
        self.assertTrue(
            all("holding_period" not in call.arguments for call in plan.tool_calls),
            "diagnostic or preference-only skill_params should not leak into tool arguments",
        )
        self.assertTrue(
            all(call.arguments.get("query") == "给我筛选黄金ETF" for call in plan.tool_calls),
            "planner should fallback to user_message when effective_query is punctuation-only",
        )

    def test_sector_skill_planner_injects_only_executable_sector_args(self):
        skill_spec = get_skill_registry().load_skill_spec("sector-hotspot-brief") or {}
        plan = build_skill_tool_plan(
            skill_name="sector-hotspot-brief",
            skill_spec=skill_spec,
            user_message="新能源板块最近行情怎么样",
            resolved_entities=[],
            skill_params={
                "sector_name": "电力设备",
                "index_code": "801730.SI",
                "match_confidence": 0.84,
                "candidate_sector_names": ["电力设备", "汽车", "公用事业"],
            },
        )
        calls_by_tool = {item.tool_name: item.arguments for item in plan.tool_calls}
        self.assertEqual(calls_by_tool["get_sector_snapshot"].get("sector_name"), "电力设备")
        self.assertEqual(calls_by_tool["get_sector_constituents"].get("sector_name"), "电力设备")
        self.assertEqual(calls_by_tool["get_index_bars"].get("symbol"), "801730.SI")
        self.assertNotIn("match_confidence", calls_by_tool["get_sector_snapshot"])

    def test_execute_tushare_plan_returns_executor_trace_shape(self):
        class _FakeTool:
            name = "get_market_bars"
            description = "fake market bars"

            async def ainvoke(self, arguments):
                return {
                    "ok": True,
                    "source": "tushare",
                    "trade_date": "20260410",
                    "data_time": "2026-04-10T00:00:00+08:00",
                    "payload": [{"close": 1}],
                    "symbol": arguments.get("query", ""),
                }

        with patch("src.agents.tushare_plan_executor.get_tushare_toolkit", return_value=[_FakeTool()]):
            result = asyncio.run(
                execute_tushare_plan(
                    tool_plan=[
                        {
                            "tool_name": "get_market_bars",
                            "arguments": {"query": "贵州茅台"},
                            "depends_on": None,
                        }
                    ],
                    entities=[],
                    session_id="s1",
                    user_id="u1",
                    decision=None,
                    user_message="贵州茅台",
                )
            )
        self.assertTrue(result.get("ok"))
        trace = result.get("executor_trace") or {}
        for key in ("reply_mode", "used_tools", "planned_tools", "prefetched_tool_names", "evidence_ok"):
            self.assertIn(key, trace)

    def test_execute_tushare_plan_normalizes_ts_code_alias_to_symbol(self):
        seen_arguments = {}

        class _FakeTool:
            name = "get_stock_basic_info"
            description = "fake stock basic"

            async def ainvoke(self, arguments):
                seen_arguments.update(arguments)
                return {
                    "ok": True,
                    "source": "tushare",
                    "payload": [{"ts_code": arguments.get("symbol") or ""}],
                    "symbol": arguments.get("symbol") or "",
                }

        with patch("src.agents.tushare_plan_executor.get_tushare_toolkit", return_value=[_FakeTool()]):
            result = asyncio.run(
                execute_tushare_plan(
                    tool_plan=[
                        {
                            "tool_name": "get_stock_basic_info",
                            "arguments": {"ts_code": "300750.SZ"},
                            "depends_on": None,
                        }
                    ],
                    entities=[],
                    session_id="s1",
                    user_id="u1",
                    decision=None,
                    user_message="宁德时代",
                )
            )
        self.assertTrue(result.get("ok"))
        self.assertEqual(seen_arguments.get("symbol"), "300750.SZ")
        self.assertEqual(seen_arguments.get("ts_code"), "300750.SZ")


if __name__ == "__main__":
    unittest.main()
