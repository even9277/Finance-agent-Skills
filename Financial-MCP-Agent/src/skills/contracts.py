"""定义金融 SOP Skill 资产的类型化机器合同。"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from .version import SkillVersion

REQUIRED_SKILL_SECTIONS: tuple[str, ...] = (
    "Purpose",
    "When to Use",
    "When Not to Use",
    "Required Inputs",
    "Workflow",
    "Tool Use Guide",
    "Evidence Rules",
    "Degrade Policy",
    "Output Contract",
    "References",
)

SUPPORTED_FINANCIAL_SOP_EVIDENCE_TYPES: frozenset[str] = frozenset(
    {
        "stock_basic",
        "stock_market",
        "financial_indicator",
        "income_statement",
        "balance_sheet",
        "cashflow_statement",
        "fund_basic",
        "etf_basic",
        "fund_nav",
        "fund_daily",
        "fund_share",
        "index_daily",
        "sector_snapshot",
        "sector_constituents",
        "web_news",
    }
)

NonEmptyText = Annotated[str, Field(min_length=1)]


class FrozenContract(BaseModel):
    """为版本化 Skill 资产提供不可变且拒绝未知字段的公共基类。"""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class SkillDocumentMetadata(FrozenContract):
    """描述 `SKILL.md` frontmatter 的发现与权限元数据。"""

    name: NonEmptyText = Field(description="Skill 的稳定目录名和公开标识。")
    description: NonEmptyText = Field(description="仅供发现阶段使用的简短能力说明。")
    execution_mode: Literal["deterministic"] = "deterministic"
    allowed_tools: tuple[NonEmptyText, ...] = Field(min_length=1)
    aliases: tuple[NonEmptyText, ...] = ()


class RouteMetadata(FrozenContract):
    """保存路由阶段可见的正反边界和代表性样例。"""

    when_to_use: tuple[NonEmptyText, ...] = Field(min_length=1)
    when_not_to_use: tuple[NonEmptyText, ...] = Field(min_length=1)
    positive_examples: tuple[NonEmptyText, ...] = Field(min_length=1)
    negative_examples: tuple[NonEmptyText, ...] = Field(min_length=1)
    supported_entity_types: tuple[NonEmptyText, ...] = Field(min_length=1)


class InputContract(FrozenContract):
    """定义 rewrite 阶段必须补齐的槽位和主体基数。"""

    required_slots: tuple[NonEmptyText, ...] = Field(min_length=1)
    optional_slots: tuple[NonEmptyText, ...] = ()
    entity_cardinality: Literal["exactly_one", "at_least_two", "zero_or_more"]
    supported_entity_types: tuple[NonEmptyText, ...] = ()
    on_missing_slots: Literal["ask_clarification"] = "ask_clarification"
    comparison_required: bool = False


class ToolPlanStep(FrozenContract):
    """定义 Planner 可生成的一步只读工具调用模板。"""

    step: NonEmptyText
    tool: NonEmptyText
    required: bool
    repeat_for_each_subject: bool = False
    arguments: dict[str, JsonValue] = Field(default_factory=dict)


class RequiredEvidence(FrozenContract):
    """定义允许形成结论所需的证据集合与多主体约束。"""

    min_distinct_symbols: int | None = Field(default=None, ge=1, le=10)
    must_have_all: tuple[NonEmptyText, ...] = ()
    must_have_any: tuple[NonEmptyText, ...] = ()
    per_symbol_must_have_any: tuple[NonEmptyText, ...] = ()
    optional: tuple[NonEmptyText, ...] = ()

    @model_validator(mode="after")
    def require_evidence_dimension(self) -> RequiredEvidence:
        """拒绝没有任何证据门槛的空合同。"""
        if not (
            self.must_have_all
            or self.must_have_any
            or self.per_symbol_must_have_any
        ):
            raise ValueError("required_evidence must declare at least one required dimension")
        return self

    def dimensions(self) -> frozenset[str]:
        """返回合同声明的全部必需和可选证据维度。"""
        return frozenset(
            (*self.must_have_all, *self.must_have_any, *self.per_symbol_must_have_any, *self.optional)
        )


class OutputVariant(FrozenContract):
    """定义特定回答偏好对应的章节顺序和风格标识。"""

    section_order: tuple[NonEmptyText, ...] = Field(min_length=1)
    style_variant: NonEmptyText


class OutputTemplate(FrozenContract):
    """定义 synthesis 输出章节及可选偏好覆盖。"""

    default_section_order: tuple[NonEmptyText, ...] = Field(min_length=1)
    response_pref_overrides: dict[NonEmptyText, OutputVariant] = Field(default_factory=dict)


class DegradeStage(FrozenContract):
    """定义证据或工具不足时的一步有限降级状态转换。"""

    name: NonEmptyText
    next_stage: NonEmptyText | None


class DegradePolicy(FrozenContract):
    """定义 Skill 失败时可解释且有终点的降级链。"""

    stages: tuple[DegradeStage, ...] = Field(min_length=1)
    when_missing_evidence: Literal["graceful_decline", "partial", "clarify"]

    @model_validator(mode="after")
    def require_unique_terminating_stages(self) -> DegradePolicy:
        """拒绝重复状态以及没有终止节点的降级链。"""
        names = tuple(stage.name for stage in self.stages)
        if len(names) != len(set(names)):
            raise ValueError("degrade stages must be unique")
        if not any(stage.next_stage is None or stage.next_stage == "none" for stage in self.stages):
            raise ValueError("degrade policy must contain a terminal stage")
        unknown_targets: set[str] = set()
        for stage in self.stages:
            target = stage.next_stage
            if target is not None and target != "none" and target not in set(names):
                unknown_targets.add(target)
        if unknown_targets:
            raise ValueError(f"degrade policy points to unknown stages: {sorted(unknown_targets)}")
        return self


class ConcurrencyPolicy(FrozenContract):
    """限制单个 Skill 计划可使用的有界并发批量。"""

    enabled: bool
    batch_size: int = Field(ge=1, le=20)


class CandidateExpansion(FrozenContract):
    """定义候选筛选类 Skill 的受控候选扩展规则。"""

    trigger_tools: tuple[NonEmptyText, ...] = Field(min_length=1)
    top_n: int = Field(ge=1, le=10)


class SkillSpec(FrozenContract):
    """表示五类金融 SOP 的完整、版本化机器执行合同。"""

    skill_name: NonEmptyText
    skill_family: Literal["financial-sop"]
    version: NonEmptyText
    execution_policy: Literal["deterministic"]
    depends_on_tools: tuple[NonEmptyText, ...] = Field(min_length=1)
    min_tool_schema_version: NonEmptyText
    output_schema_version: NonEmptyText
    skill_md_section_map: dict[NonEmptyText, NonEmptyText]
    requires_web_news: bool
    route_metadata: RouteMetadata
    input_contract: InputContract
    allowed_tools: tuple[NonEmptyText, ...] = Field(min_length=1)
    tool_plan_steps: tuple[ToolPlanStep, ...] = Field(min_length=1)
    required_evidence: RequiredEvidence
    output_template: OutputTemplate
    degrade_policy: DegradePolicy
    concurrency: ConcurrencyPolicy
    candidate_expansion: CandidateExpansion | None = None

    @model_validator(mode="after")
    def close_machine_contract(self) -> SkillSpec:
        """保证工具、章节、版本和 Web News 声明内部闭合。"""
        for field_name, value in (
            ("version", self.version),
            ("min_tool_schema_version", self.min_tool_schema_version),
            ("output_schema_version", self.output_schema_version),
        ):
            if not SkillVersion(value).is_semver:
                raise ValueError(f"{field_name} must be semantic version")

        allowed_tools = set(self.allowed_tools)
        if len(allowed_tools) != len(self.allowed_tools):
            raise ValueError("allowed_tools must be unique")
        if not set(self.depends_on_tools) <= allowed_tools:
            raise ValueError("depends_on_tools must be a subset of allowed_tools")
        if any(step.tool not in allowed_tools for step in self.tool_plan_steps):
            raise ValueError("tool_plan_steps must only reference allowed_tools")
        if self.candidate_expansion and not set(self.candidate_expansion.trigger_tools) <= allowed_tools:
            raise ValueError("candidate expansion tools must be allowed")
        if self.requires_web_news != ("search_web_news" in allowed_tools):
            raise ValueError("requires_web_news must match search_web_news permission")
        if not set(REQUIRED_SKILL_SECTIONS) <= set(self.skill_md_section_map.values()):
            raise ValueError("skill_md_section_map is incomplete")
        return self


class ReferenceMetadata(FrozenContract):
    """描述可按阶段检索且具备来源说明的 reference frontmatter。"""

    title: NonEmptyText
    category: Literal["financial_sop_reference"]
    stages: tuple[Literal["rewrite", "planner", "synthesis"], ...] = Field(min_length=1)
    tags: tuple[NonEmptyText, ...] = Field(min_length=1)
    evidence_types: tuple[NonEmptyText, ...] = Field(min_length=1)
    source_note: NonEmptyText
    updated_at: date


__all__ = [
    "CandidateExpansion",
    "ConcurrencyPolicy",
    "DegradePolicy",
    "DegradeStage",
    "InputContract",
    "OutputTemplate",
    "OutputVariant",
    "REQUIRED_SKILL_SECTIONS",
    "ReferenceMetadata",
    "RequiredEvidence",
    "RouteMetadata",
    "SkillDocumentMetadata",
    "SkillSpec",
    "SUPPORTED_FINANCIAL_SOP_EVIDENCE_TYPES",
    "ToolPlanStep",
]
