from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True, slots=True)
class ReferenceItem:
    title: str
    path: str
    category: str = "references"
    stages: tuple[str, ...] = ()
    evidence_types: tuple[str, ...] = ()
    content: str = ""
    metadata: dict[str, Any] | None = None


def _split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    for idx, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            raw_meta = "\n".join(lines[1:idx])
            body = "\n".join(lines[idx + 1 :]).strip()
            try:
                metadata = yaml.safe_load(raw_meta) or {}
            except Exception:
                metadata = {}
            return metadata if isinstance(metadata, dict) else {}, body
    return {}, text


def _keywords(query: str) -> list[str]:
    cleaned = (query or "").lower()
    for token in "，。、：:；;,.!?？\n\t":
        cleaned = cleaned.replace(token, " ")
    words = [item.strip() for item in cleaned.split() if len(item.strip()) >= 2]
    # 中文短句没有空格时，保留整句作为弱匹配项。
    if not words and len(cleaned.strip()) >= 2:
        words.append(cleaned.strip())
    return words[:16]


class ReferenceIndex:
    def __init__(self, items: list[ReferenceItem]) -> None:
        self.items = list(items)

    @classmethod
    def from_skill_dir(cls, skill_dir: Path) -> "ReferenceIndex":
        refs_dir = skill_dir / "references"
        if not refs_dir.exists():
            return cls([])
        items: list[ReferenceItem] = []
        for file_path in sorted(refs_dir.rglob("*.md")):
            raw = file_path.read_text(encoding="utf-8")
            metadata, body = _split_frontmatter(raw)
            rel_path = str(file_path.relative_to(skill_dir))
            items.append(
                ReferenceItem(
                    title=str(metadata.get("title") or file_path.stem),
                    path=rel_path,
                    category=str(metadata.get("category") or "references"),
                    stages=tuple(str(item) for item in metadata.get("stages") or ()),
                    evidence_types=tuple(str(item) for item in metadata.get("evidence_types") or ()),
                    content=body or raw,
                    metadata=metadata,
                )
            )
        return cls(items)

    def search(self, query: str, *, stage: str = "", top_k: int = 3) -> list[ReferenceItem]:
        terms = _keywords(query)
        scored: list[tuple[int, ReferenceItem]] = []
        for item in self.items:
            if stage and item.stages and stage not in item.stages:
                continue
            haystack = f"{item.title}\n{item.category}\n{' '.join(item.evidence_types)}\n{item.content}".lower()
            score = sum(3 if term in item.title.lower() else 1 for term in terms if term in haystack)
            if stage and stage in item.stages:
                score += 2
            scored.append((score, item))
        scored.sort(key=lambda pair: (-pair[0], pair[1].path))
        return [item for _, item in scored[: max(1, top_k)]]


__all__ = ["ReferenceIndex", "ReferenceItem"]
