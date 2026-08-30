"""验证 reference 索引的身份、阶段、词法、预算与路径边界。"""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest

ROOT = Path(__file__).resolve().parents[3]
AGENT_ROOT = ROOT / "Financial-MCP-Agent"
SKILLS_ROOT = AGENT_ROOT / "src" / "skills"
if str(AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(AGENT_ROOT))

from src.skills.reference_index import (  # noqa: E402
    LoadStage,
    ReferenceIndex,
    ReferenceIndexError,
    ReferenceItem,
)


def _item(*, path: str, stages: tuple[str, ...]) -> ReferenceItem:
    """构造最小 reference item 以测试索引边界。"""
    return ReferenceItem(
        skill_id="demo",
        title="财务风险",
        path=path,
        category="financial_sop_reference",
        stages=cast(tuple[LoadStage, ...], stages),
        tags=("财务", "风险"),
        evidence_types=("financial_indicator",),
        source_note="test fixture",
        updated_at="2026-08-26",
        content="现金流与利润质量需要交叉验证。",
        content_hash="hash",
        token_estimate=16,
    )


@pytest.mark.unit
def test_reference_index_hard_filters_stage_and_ranks_lexical_match() -> None:
    """阶段不匹配的文档即使关键词命中也不能被加载。"""
    planner_only = _item(path="references/planner.md", stages=("planner",))
    synthesis_only = _item(path="references/synthesis.md", stages=("synthesis",))
    index = ReferenceIndex(
        skill_id="demo",
        skill_root=SKILLS_ROOT / "stock-first-pass",
        items=(planner_only, synthesis_only),
    )

    planner = index.search("现金流风险", stage="planner", top_k=3, token_budget=100)
    rewrite = index.search("现金流风险", stage="rewrite", top_k=3, token_budget=100)

    assert planner == (planner_only,)
    assert rewrite == ()


@pytest.mark.unit
def test_reference_index_enforces_budget_and_returns_content_hash() -> None:
    """索引不得为了命中结果突破请求 token 预算。"""
    index = ReferenceIndex.from_skill_dir(
        "stock-first-pass", SKILLS_ROOT / "stock-first-pass"
    )
    too_small = index.search("财务现金流", stage="planner", top_k=3, token_budget=1)
    selected = index.search("财务现金流", stage="planner", top_k=3, token_budget=2_048)

    assert too_small == ()
    assert selected
    assert sum(item.token_estimate for item in selected) <= 2_048
    assert all(len(item.content_hash) == 64 for item in selected)
    assert all("planner" in item.stages for item in selected)


@pytest.mark.unit
def test_reference_index_rejects_relative_escape_before_read() -> None:
    """相对越界和跨 Skill item 都在索引构造阶段直接拒绝。"""
    with pytest.raises(ReferenceIndexError, match="escapes"):
        ReferenceIndex(
            skill_id="demo",
            skill_root=SKILLS_ROOT / "stock-first-pass",
            items=(_item(path="../secret.md", stages=("planner",)),),
        )
    with pytest.raises(ReferenceIndexError, match="identity"):
        ReferenceIndex(
            skill_id="demo",
            skill_root=SKILLS_ROOT / "stock-first-pass",
            items=(
                replace(
                    _item(path="references/other.md", stages=("planner",)),
                    skill_id="other-skill",
                ),
            ),
        )
