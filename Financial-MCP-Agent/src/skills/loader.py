"""从固定 RegistrySnapshot 构建最小权限的分阶段 Skill 上下文。"""

from __future__ import annotations

from dataclasses import dataclass

from .contracts import (
    CandidateExpansion,
    ConcurrencyPolicy,
    DegradePolicy,
    InputContract,
    OutputTemplate,
    RequiredEvidence,
    RouteMetadata,
    SkillSpec,
    ToolPlanStep,
)
from .reference_index import LoadStage, ReferenceIndex, ReferenceItem
from .snapshot import RegistrySnapshot, SkillSnapshotEntry
from .version import stable_hash_text


class SkillLoadError(RuntimeError):
    """表示固定快照缺少资产、章节或超出阶段上下文预算。"""


@dataclass(frozen=True, slots=True)
class RewriteSkillView:
    """仅向 rewrite 暴露输入槽位和路由边界，不包含工具权限。"""

    input_contract: InputContract
    route_metadata: RouteMetadata

    def artifact(self) -> dict[str, object]:
        """返回可审计的 JSON 视图。"""
        return {
            "input_contract": self.input_contract.model_dump(mode="json"),
            "route_metadata": self.route_metadata.model_dump(mode="json"),
        }


@dataclass(frozen=True, slots=True)
class PlannerSkillView:
    """仅向 Planner 暴露已校验工具计划、证据和有界并发。"""

    allowed_tools: tuple[str, ...]
    tool_plan_steps: tuple[ToolPlanStep, ...]
    required_evidence: RequiredEvidence
    concurrency: ConcurrencyPolicy
    candidate_expansion: CandidateExpansion | None

    def artifact(self) -> dict[str, object]:
        """返回不包含 reference 正文的 Planner 合同。"""
        return {
            "allowed_tools": list(self.allowed_tools),
            "tool_plan_steps": [item.model_dump(mode="json") for item in self.tool_plan_steps],
            "required_evidence": self.required_evidence.model_dump(mode="json"),
            "concurrency": self.concurrency.model_dump(mode="json"),
            "candidate_expansion": (
                self.candidate_expansion.model_dump(mode="json")
                if self.candidate_expansion
                else None
            ),
        }


@dataclass(frozen=True, slots=True)
class SynthesisSkillView:
    """仅向 synthesis 暴露输出、降级和证据边界，不携带工具计划。"""

    output_template: OutputTemplate
    degrade_policy: DegradePolicy
    required_evidence: RequiredEvidence

    def artifact(self) -> dict[str, object]:
        """返回输出与降级合同的 JSON 视图。"""
        return {
            "output_template": self.output_template.model_dump(mode="json"),
            "degrade_policy": self.degrade_policy.model_dump(mode="json"),
            "required_evidence": self.required_evidence.model_dump(mode="json"),
        }


StageSpecView = RewriteSkillView | PlannerSkillView | SynthesisSkillView


@dataclass(frozen=True, slots=True)
class LoadedSection:
    """保存一个固定 Markdown 章节及其可追溯哈希。"""

    name: str
    content: str
    content_hash: str
    token_estimate: int

    def artifact(self) -> dict[str, object]:
        """返回不含正文的章节加载证据。"""
        return {
            "name": self.name,
            "content_hash": self.content_hash,
            "token_estimate": self.token_estimate,
        }


@dataclass(frozen=True, slots=True)
class LoadedSkillContext:
    """表示一次请求从固定快照加载出的阶段最小上下文。"""

    skill_id: str
    skill_version: str
    stage: LoadStage
    registry_version: str
    registry_snapshot_hash: str
    spec_hash: str
    reference_hash: str
    spec_view: StageSpecView
    sections: tuple[LoadedSection, ...]
    references: tuple[ReferenceItem, ...]
    token_estimate: int
    token_budget: int

    def artifact(self) -> dict[str, object]:
        """返回可观测但不含 Skill/reference 正文的加载摘要。"""
        return {
            "skill_id": self.skill_id,
            "skill_version": self.skill_version,
            "stage": self.stage,
            "registry_version": self.registry_version,
            "registry_snapshot_hash": self.registry_snapshot_hash,
            "spec_hash": self.spec_hash,
            "reference_hash": self.reference_hash,
            "spec_view": self.spec_view.artifact(),
            "sections_loaded": [item.artifact() for item in self.sections],
            "references_loaded": [item.artifact() for item in self.references],
            "token_estimate": self.token_estimate,
            "token_budget": self.token_budget,
        }


_STAGE_SECTION_KEYS: dict[LoadStage, tuple[str, ...]] = {
    "rewrite": ("purpose", "when_to_use", "when_not_to_use", "required_inputs"),
    "planner": ("workflow", "tool_use_guide", "evidence_rules"),
    "synthesis": ("degrade_policy", "output_contract", "references"),
}


def _extract_markdown_sections(markdown: str) -> dict[str, str]:
    """按二级标题切分 SKILL.md，忽略 frontmatter 和一级标题。"""
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in markdown.splitlines():
        if line.startswith("## "):
            current = line[3:].strip()
            sections[current] = [line]
        elif current is not None:
            sections[current].append(line)
    return {name: "\n".join(lines).strip() for name, lines in sections.items()}


def _estimate_tokens(text: str) -> int:
    """使用保守字符计数约束中英文阶段上下文。"""
    return max(1, len(text))


class SkillLoader:
    """从请求固定的 `RegistrySnapshot` 生成三类隔离上下文。"""

    def __init__(
        self,
        snapshot: RegistrySnapshot,
        *,
        token_budget_per_stage: int = 4_096,
        max_references: int = 3,
    ) -> None:
        if token_budget_per_stage < 256:
            raise ValueError("token_budget_per_stage must be at least 256")
        if not 1 <= max_references <= 10:
            raise ValueError("max_references must be between 1 and 10")
        self._snapshot = snapshot
        self._token_budget = token_budget_per_stage
        self._max_references = max_references

    @property
    def snapshot(self) -> RegistrySnapshot:
        """返回本 Loader 固定的请求级快照引用。"""
        return self._snapshot

    def load_for_rewrite(self, skill_id: str, *, query: str = "") -> LoadedSkillContext:
        """加载输入合同和路由边界，不暴露任何工具权限。"""
        return self._load(skill_id, stage="rewrite", query=query)

    def load_for_planner(self, skill_id: str, *, query: str = "") -> LoadedSkillContext:
        """加载工具计划、证据和并发合同。"""
        return self._load(skill_id, stage="planner", query=query)

    def load_for_synthesis(self, skill_id: str, *, query: str = "") -> LoadedSkillContext:
        """加载输出、降级和 accepted-evidence 边界。"""
        return self._load(skill_id, stage="synthesis", query=query)

    def _load(self, skill_id: str, *, stage: LoadStage, query: str) -> LoadedSkillContext:
        entry = self._snapshot.require(skill_id)
        spec, reference_index = self._require_complete_entry(entry)
        sections_by_name = _extract_markdown_sections(entry.markdown)
        section_names = tuple(
            spec.skill_md_section_map[key] for key in _STAGE_SECTION_KEYS[stage]
        )
        loaded_sections: list[LoadedSection] = []
        for section_name in section_names:
            content = sections_by_name.get(section_name, "")
            if not content:
                raise SkillLoadError(f"required stage section is missing: {section_name}")
            loaded_sections.append(
                LoadedSection(
                    name=section_name,
                    content=content,
                    content_hash=stable_hash_text(content),
                    token_estimate=_estimate_tokens(content),
                )
            )

        section_tokens = sum(item.token_estimate for item in loaded_sections)
        if section_tokens > self._token_budget:
            raise SkillLoadError("required Skill sections exceed stage token budget")
        reference_budget = self._token_budget - section_tokens
        references = reference_index.search(
            query,
            stage=stage,
            top_k=self._max_references,
            token_budget=max(1, reference_budget),
        )
        total_tokens = section_tokens + sum(item.token_estimate for item in references)
        return LoadedSkillContext(
            skill_id=entry.skill_id,
            skill_version=entry.skill_version,
            stage=stage,
            registry_version=self._snapshot.registry_version,
            registry_snapshot_hash=self._snapshot.snapshot_hash,
            spec_hash=entry.spec_hash,
            reference_hash=entry.reference_hash,
            spec_view=self._build_spec_view(entry, stage),
            sections=tuple(loaded_sections),
            references=references,
            token_estimate=total_tokens,
            token_budget=self._token_budget,
        )

    @staticmethod
    def _require_complete_entry(entry: SkillSnapshotEntry) -> tuple[SkillSpec, ReferenceIndex]:
        """拒绝测试占位条目或未完整发布的快照内容。"""
        if entry.spec is None or entry.reference_index is None or not entry.markdown:
            raise SkillLoadError(f"skill snapshot entry is incomplete: {entry.skill_id}")
        return entry.spec, entry.reference_index

    @staticmethod
    def _build_spec_view(entry: SkillSnapshotEntry, stage: LoadStage) -> StageSpecView:
        """按阶段投影 typed spec，避免 reference 或上游阶段扩大权限。"""
        if entry.spec is None:
            raise SkillLoadError(f"skill snapshot entry is incomplete: {entry.skill_id}")
        spec = entry.spec
        if stage == "rewrite":
            return RewriteSkillView(
                input_contract=spec.input_contract,
                route_metadata=spec.route_metadata,
            )
        if stage == "planner":
            return PlannerSkillView(
                allowed_tools=spec.allowed_tools,
                tool_plan_steps=spec.tool_plan_steps,
                required_evidence=spec.required_evidence,
                concurrency=spec.concurrency,
                candidate_expansion=spec.candidate_expansion,
            )
        return SynthesisSkillView(
            output_template=spec.output_template,
            degrade_policy=spec.degrade_policy,
            required_evidence=spec.required_evidence,
        )


__all__ = [
    "LoadedSection",
    "LoadedSkillContext",
    "PlannerSkillView",
    "RewriteSkillView",
    "SkillLoadError",
    "SkillLoader",
    "SynthesisSkillView",
]
