from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from src.skills_v2.reference_index import ReferenceIndex, ReferenceItem

LoadStage = Literal["rewrite", "planner", "synthesis"]


@dataclass(slots=True)
class LoadedSkillContext:
    skill_id: str
    stage: LoadStage
    spec: dict[str, Any] = field(default_factory=dict)
    sections: dict[str, str] = field(default_factory=dict)
    references: list[ReferenceItem] = field(default_factory=list)
    token_estimate: int = 0
    missing_sections: list[str] = field(default_factory=list)

    def artifact(self) -> dict[str, Any]:
        return {
            "skill_id": self.skill_id,
            "stage": self.stage,
            "section_names": list(self.sections),
            "reference_paths": [item.path for item in self.references],
            "token_estimate": self.token_estimate,
            "missing_sections": list(self.missing_sections),
        }


def _extract_markdown_sections(markdown: str) -> dict[str, str]:
    sections: dict[str, list[str]] = {}
    current = "root"
    for line in (markdown or "").splitlines():
        if line.startswith("#"):
            current = line.lstrip("#").strip()
            sections.setdefault(current, [line])
        else:
            sections.setdefault(current, []).append(line)
    return {name: "\n".join(lines).strip() for name, lines in sections.items()}


def _estimate_tokens(*chunks: str) -> int:
    return sum(max(1, len(chunk) // 2) for chunk in chunks if chunk)


class SkillLoader:
    def __init__(self, *, registry: Any, token_budget_per_stage: int = 2048) -> None:
        self.registry = registry
        self.token_budget_per_stage = token_budget_per_stage

    def load_for_rewrite(self, skill_id: str, *, query: str = "") -> LoadedSkillContext:
        return self._load(skill_id, stage="rewrite", query=query)

    def load_for_planner(self, skill_id: str, *, query: str = "") -> LoadedSkillContext:
        return self._load(skill_id, stage="planner", query=query)

    def load_for_synthesis(self, skill_id: str, *, query: str = "") -> LoadedSkillContext:
        return self._load(skill_id, stage="synthesis", query=query)

    def _load(self, skill_id: str, *, stage: LoadStage, query: str) -> LoadedSkillContext:
        skill = self.registry.get_skill(skill_id)
        spec = self.registry.load_skill_spec(skill_id) or {}
        markdown = self.registry.load_skill_markdown(skill_id)
        section_map = spec.get("skill_md_section_map") or {}
        wanted = [str(item) for item in section_map.get(stage, [])]
        sections_by_name = _extract_markdown_sections(markdown)
        selected: dict[str, str] = {}
        missing: list[str] = []
        for section_name in wanted:
            text = sections_by_name.get(section_name, "")
            if text:
                selected[section_name] = text
            else:
                missing.append(section_name)

        references: list[ReferenceItem] = []
        if skill and getattr(skill, "skill_dir", None):
            references = ReferenceIndex.from_skill_dir(Path(skill.skill_dir)).search(query, stage=stage, top_k=3)

        chunks = list(selected.values()) + [item.content for item in references]
        token_estimate = _estimate_tokens(*chunks)
        if token_estimate > self.token_budget_per_stage:
            references = references[:1]
            chunks = list(selected.values()) + [item.content for item in references]
            token_estimate = _estimate_tokens(*chunks)

        return LoadedSkillContext(
            skill_id=skill_id,
            stage=stage,
            spec=spec,
            sections=selected,
            references=references,
            token_estimate=token_estimate,
            missing_sections=missing,
        )


__all__ = ["LoadedSkillContext", "SkillLoader"]
