"""构建具备路径隔离、阶段过滤和预算约束的 Skill reference 索引。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal, Mapping, cast

import yaml

from .contracts import ReferenceMetadata
from .version import stable_hash_text

LoadStage = Literal["rewrite", "planner", "synthesis"]
_FRONTMATTER_PATTERN = re.compile(r"^---\r?\n(.*?)\r?\n---\r?\n", flags=re.DOTALL)


class ReferenceIndexError(ValueError):
    """表示 reference 元数据、身份、阶段或路径违反索引合同。"""


@dataclass(frozen=True, slots=True)
class ReferenceItem:
    """保存一个经过 containment 校验的不可变 reference 文档。"""

    skill_id: str
    title: str
    path: str
    category: str
    stages: tuple[LoadStage, ...]
    tags: tuple[str, ...]
    evidence_types: tuple[str, ...]
    source_note: str
    updated_at: str
    content: str
    content_hash: str
    token_estimate: int

    def artifact(self) -> dict[str, object]:
        """返回不含正文、可安全写入 Trace 或评测 artifact 的加载证据。"""
        return {
            "skill_id": self.skill_id,
            "title": self.title,
            "path": self.path,
            "stages": list(self.stages),
            "evidence_types": list(self.evidence_types),
            "content_hash": self.content_hash,
            "token_estimate": self.token_estimate,
        }


def _split_frontmatter(text: str) -> tuple[Mapping[str, object], str]:
    """解析已经通过 schema gate 的 reference frontmatter 和正文。"""
    match = _FRONTMATTER_PATTERN.match(text)
    if match is None:
        raise ReferenceIndexError("reference is missing YAML frontmatter")
    payload = yaml.safe_load(match.group(1))
    if not isinstance(payload, dict):
        raise ReferenceIndexError("reference frontmatter root must be a mapping")
    return cast(Mapping[str, object], payload), text[match.end() :].strip()


def _estimate_tokens(text: str) -> int:
    """以偏保守字符估算限制中英文 reference 的上下文体积。"""
    return max(1, len(text))


def _query_terms(query: str) -> tuple[str, ...]:
    """提取有界中英文词项；中文连续短句额外生成二至四字片段。"""
    chunks = re.findall(r"[a-z0-9._-]{2,}|[\u4e00-\u9fff]{2,}", (query or "").lower())
    terms: list[str] = []
    for chunk in chunks:
        if chunk not in terms:
            terms.append(chunk)
        if re.fullmatch(r"[\u4e00-\u9fff]+", chunk):
            for size in (2, 3, 4):
                for index in range(max(0, len(chunk) - size + 1)):
                    term = chunk[index : index + size]
                    if term not in terms:
                        terms.append(term)
                    if len(terms) >= 32:
                        return tuple(terms)
        if len(terms) >= 32:
            break
    return tuple(terms)


@dataclass(frozen=True, slots=True)
class ReferenceIndex:
    """保存单一 Skill 的不可变 reference 索引，不持有执行权限。"""

    skill_id: str
    skill_root: Path
    items: tuple[ReferenceItem, ...]

    def __post_init__(self) -> None:
        root = self.skill_root.resolve()
        paths: list[str] = []
        for item in self.items:
            relative = PurePosixPath(item.path)
            if item.skill_id != self.skill_id:
                raise ReferenceIndexError("reference skill identity mismatch")
            if relative.is_absolute() or ".." in relative.parts:
                raise ReferenceIndexError("reference path escapes skill root")
            paths.append(item.path)
        if len(paths) != len(set(paths)):
            raise ReferenceIndexError("reference index contains duplicate paths")
        object.__setattr__(self, "skill_root", root)

    @classmethod
    def from_skill_dir(cls, skill_id: str, skill_dir: Path) -> ReferenceIndex:
        """从通过 gate 的目录构建索引并再次验证 resolved path containment。

        Args:
            skill_id: Registry 使用的稳定 Skill 标识。
            skill_dir: Skill 根目录；只允许加载其 `references` 子目录。

        Returns:
            内容和元数据均已固定的不可变索引。

        Raises:
            ReferenceIndexError: 文件越界、frontmatter 无效或读取失败。
        """
        root = skill_dir.resolve(strict=True)
        references_dir = (root / "references").resolve(strict=True)
        try:
            references_dir.relative_to(root)
        except ValueError as exc:
            raise ReferenceIndexError("references directory escapes skill root") from exc

        items: list[ReferenceItem] = []
        for file_path in sorted(references_dir.rglob("*.md")):
            try:
                resolved = file_path.resolve(strict=True)
                resolved.relative_to(references_dir)
                raw = resolved.read_text(encoding="utf-8")
                raw_metadata, body = _split_frontmatter(raw)
                metadata = ReferenceMetadata.model_validate(raw_metadata)
            except (OSError, ValueError, yaml.YAMLError) as exc:
                raise ReferenceIndexError(f"invalid reference asset: {file_path.name}") from exc
            relative_path = resolved.relative_to(root).as_posix()
            content_hash = stable_hash_text(body)
            items.append(
                ReferenceItem(
                    skill_id=skill_id,
                    title=metadata.title,
                    path=relative_path,
                    category=metadata.category,
                    stages=metadata.stages,
                    tags=metadata.tags,
                    evidence_types=metadata.evidence_types,
                    source_note=metadata.source_note,
                    updated_at=metadata.updated_at.isoformat(),
                    content=body,
                    content_hash=content_hash,
                    token_estimate=_estimate_tokens(body),
                )
            )
        if not items:
            raise ReferenceIndexError("reference index must contain at least one item")
        return cls(skill_id=skill_id, skill_root=root, items=tuple(items))

    def search(
        self,
        query: str,
        *,
        stage: LoadStage,
        top_k: int = 3,
        token_budget: int = 2_048,
    ) -> tuple[ReferenceItem, ...]:
        """按 Skill、阶段、词法分数和 token 预算选择 reference。

        Args:
            query: 当前阶段的最小有效查询，不写入 artifact。
            stage: 只允许 rewrite、planner 或 synthesis。
            top_k: 最多返回数量，范围为 1 到 10。
            token_budget: reference 正文总字符预算，必须为正数。

        Returns:
            稳定排序且总估算体积不超过预算的 reference 元组。

        Raises:
            ValueError: 数量或预算越界。
        """
        if not 1 <= top_k <= 10:
            raise ValueError("top_k must be between 1 and 10")
        if token_budget < 1:
            raise ValueError("token_budget must be positive")

        terms = _query_terms(query)
        scored: list[tuple[int, ReferenceItem]] = []
        for item in self.items:
            # Stage 是强过滤条件；没有显式授权的 reference 不得进入当前上下文。
            if item.skill_id != self.skill_id or stage not in item.stages:
                continue
            title = item.title.lower()
            metadata_text = " ".join((*item.tags, *item.evidence_types)).lower()
            body = item.content.lower()
            score = 2
            for term in terms:
                if term in title:
                    score += 6
                elif term in metadata_text:
                    score += 3
                elif term in body:
                    score += 1
            scored.append((score, item))

        scored.sort(key=lambda pair: (-pair[0], pair[1].path))
        selected: list[ReferenceItem] = []
        consumed = 0
        for _, item in scored:
            if consumed + item.token_estimate > token_budget:
                continue
            selected.append(item)
            consumed += item.token_estimate
            if len(selected) >= top_k:
                break
        return tuple(selected)


__all__ = ["LoadStage", "ReferenceIndex", "ReferenceIndexError", "ReferenceItem"]
