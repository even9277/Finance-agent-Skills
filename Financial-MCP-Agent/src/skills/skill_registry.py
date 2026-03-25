from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any

from src.utils.logging_config import setup_logger

_SRC_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_SKILLS_DIR = _SRC_ROOT / "skills"
_DEFAULT_VENDOR_SKILLS_DIR = _SRC_ROOT.parent.parent / "vendor" / "tushare-skills"
logger = setup_logger("skill_registry")


@dataclass(slots=True)
class SkillMetadata:
    name: str
    description: str
    official_name: str = ""
    execution_mode: str = "agent"
    allowed_tools: list[str] = field(default_factory=list)
    compatibility: dict[str, Any] = field(default_factory=dict)
    skill_dir: Path | None = None
    skill_file: Path | None = None
    references_dir: Path | None = None
    source: str = "workspace"
    meta_file: Path | None = None
    version: str | None = None
    aliases: list[str] = field(default_factory=list)
    reference_index: list[dict[str, str]] = field(default_factory=list)
    scripts_dir: Path | None = None


def _parse_scalar(value: str) -> Any:
    raw = value.strip()
    if raw.startswith(("'", '"')) and raw.endswith(("'", '"')) and len(raw) >= 2:
        return raw[1:-1]
    lowered = raw.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    return raw


def _parse_frontmatter(text: str) -> dict[str, Any]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}

    end_index = None
    for idx, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end_index = idx
            break
    if end_index is None:
        return {}

    payload = lines[1:end_index]
    parsed: dict[str, Any] = {}
    current_key: str | None = None
    current_list: list[Any] | None = None
    current_map: dict[str, Any] | None = None

    for raw_line in payload:
        if not raw_line.strip():
            continue

        if raw_line.startswith("  - ") and current_key:
            if current_list is None:
                parsed[current_key] = []
                current_list = parsed[current_key]
                current_map = None
            current_list.append(_parse_scalar(raw_line[4:]))
            continue

        if raw_line.startswith("  ") and current_key and ":" in raw_line:
            if current_map is None:
                parsed[current_key] = {}
                current_map = parsed[current_key]
                current_list = None
            child_key, child_value = raw_line.strip().split(":", 1)
            current_map[child_key.strip()] = _parse_scalar(child_value)
            continue

        if ":" not in raw_line:
            continue

        key, value = raw_line.split(":", 1)
        key = key.strip()
        value = value.strip()
        current_key = key
        current_list = None
        current_map = None

        if value == "":
            parsed[key] = None
        elif value == "[]":
            parsed[key] = []
            current_list = parsed[key]
        else:
            parsed[key] = _parse_scalar(value)

    return parsed


def _read_meta_json(skill_dir: Path) -> dict[str, Any]:
    meta_file = skill_dir / "_meta.json"
    if not meta_file.exists():
        return {}
    try:
        return json.loads(meta_file.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("[skill_registry] failed to read %s: %s", meta_file, exc, exc_info=True)
        return {}


def _build_reference_index(skill_dir: Path) -> list[dict[str, str]]:
    references_dir = skill_dir / "references"
    if not references_dir.exists():
        return []

    items: list[dict[str, str]] = []
    for file_path in sorted(references_dir.rglob("*.md")):
        rel_path = file_path.relative_to(skill_dir)
        parts = rel_path.parts
        category = parts[1] if len(parts) >= 3 else "references"
        title = file_path.stem
        items.append(
            {
                "title": title,
                "category": category,
                "path": str(rel_path),
                "title_lower": title.lower(),
                "category_lower": category.lower(),
            }
        )
    return items


def _query_keywords(query: str) -> list[str]:
    text = (query or "").strip().lower()
    if not text:
        return []

    normalized = (
        text.replace("，", " ")
        .replace("。", " ")
        .replace("、", " ")
        .replace(",", " ")
        .replace("？", " ")
        .replace("?", " ")
        .replace("：", " ")
        .replace(":", " ")
    )
    keywords: list[str] = []
    for token in normalized.split():
        token = token.strip()
        if len(token) >= 2 and token not in keywords:
            keywords.append(token)

    for candidate in (
        "半导体",
        "板块",
        "行业",
        "指数",
        "行情",
        "分钟",
        "日线",
        "财务",
        "财报",
        "指标",
        "利润",
        "现金流",
        "资产负债",
        "股票",
        "基金",
        "期货",
        "选股",
        "推荐",
        "估值",
    ):
        if candidate in text and candidate not in keywords:
            keywords.append(candidate)

    return keywords[:16]


class SkillRegistry:
    def __init__(self, skills_dir: Path | None = None, vendor_skills_dir: Path | None = None):
        self.skills_dir = skills_dir or _DEFAULT_SKILLS_DIR
        self.vendor_skills_dir = vendor_skills_dir or _DEFAULT_VENDOR_SKILLS_DIR
        self._skills: dict[str, SkillMetadata] = {}
        self.refresh()

    def refresh(self) -> None:
        skills: dict[str, SkillMetadata] = {}
        candidate_dirs: list[tuple[Path, str]] = []
        if self.vendor_skills_dir.exists():
            candidate_dirs.append((self.vendor_skills_dir, "official_vendor"))
        else:
            logger.warning("[skill_registry] vendor skills dir missing: %s", self.vendor_skills_dir)
        if self.skills_dir.exists():
            candidate_dirs.append((self.skills_dir, "workspace"))
        else:
            logger.warning("[skill_registry] skills dir missing: %s", self.skills_dir)

        for base_dir, source in candidate_dirs:
            for skill_file in sorted(base_dir.glob("*/SKILL.md")):
                try:
                    meta = self._load_skill(skill_file, source=source)
                except ValueError:
                    raise
                except Exception as exc:
                    logger.warning(
                        "[skill_registry] failed to load skill metadata from %s: %s",
                        skill_file,
                        exc,
                        exc_info=True,
                    )
                    continue

                if meta.name in skills:
                    if source == "workspace":
                        logger.info(
                            "[skill_registry] workspace skill overrides vendor skill: %s",
                            meta.name,
                        )
                        skills[meta.name] = meta
                        continue
                    raise ValueError(f"Duplicate skill name detected: {meta.name}")
                skills[meta.name] = meta

        self._skills = skills
        logger.info("[skill_registry] loaded %s skills", len(self._skills))

    def _load_skill(self, skill_file: Path, *, source: str) -> SkillMetadata:
        meta = _parse_frontmatter(skill_file.read_text(encoding="utf-8"))
        official_name = str(meta.get("name") or "").strip()
        description = str(meta.get("description") or "").strip()
        if not official_name or not description:
            raise ValueError(f"Skill metadata missing required fields: {skill_file}")

        upstream_meta = _read_meta_json(skill_file.parent)
        canonical_name = str(upstream_meta.get("slug") or official_name).strip() or official_name

        allowed_tools = meta.get("allowed_tools") or []
        if not isinstance(allowed_tools, list):
            allowed_tools = [str(allowed_tools)]
        if not allowed_tools and canonical_name == "tushare-data":
            allowed_tools = [
                "get_stock_basic_info",
                "get_daily_bars",
                "get_market_bars",
                "get_index_bars",
                "get_sector_snapshot",
                "get_sector_constituents",
                "get_fund_basic_info",
                "get_etf_basic_info",
                "get_fund_nav",
                "get_fund_market_bars",
                "get_fund_share",
                "get_fina_indicator",
                "get_income",
                "get_balance_sheet",
                "get_cashflow",
            ]

        compatibility = meta.get("compatibility") or {}
        if not isinstance(compatibility, dict):
            compatibility = {}
        if upstream_meta:
            compatibility = {
                **compatibility,
                "upstream_slug": str(upstream_meta.get("slug") or ""),
                "upstream_version": str(upstream_meta.get("version") or ""),
            }

        aliases = [official_name]
        slug = str(upstream_meta.get("slug") or "").strip()
        if slug and slug not in aliases:
            aliases.append(slug)

        references_dir = skill_file.parent / "references" if (skill_file.parent / "references").exists() else None
        scripts_dir = skill_file.parent / "scripts" if (skill_file.parent / "scripts").exists() else None

        return SkillMetadata(
            name=canonical_name,
            description=description,
            official_name=official_name,
            execution_mode=str(meta.get("execution_mode") or "agent"),
            allowed_tools=[str(item) for item in allowed_tools],
            compatibility=compatibility,
            skill_dir=skill_file.parent,
            skill_file=skill_file,
            references_dir=references_dir,
            source=source,
            meta_file=skill_file.parent / "_meta.json" if (skill_file.parent / "_meta.json").exists() else None,
            version=str(upstream_meta.get("version") or "") or None,
            aliases=aliases,
            reference_index=_build_reference_index(skill_file.parent),
            scripts_dir=scripts_dir,
        )

    def list_skills(self) -> list[SkillMetadata]:
        return list(self._skills.values())

    def get_skill(self, name: str) -> SkillMetadata | None:
        direct = self._skills.get(name)
        if direct is not None:
            return direct
        for skill in self._skills.values():
            if name in skill.aliases:
                return skill
        return None

    def matchable_descriptions(self) -> list[dict[str, str]]:
        return [
            {
                "name": skill.name,
                "official_name": skill.official_name,
                "description": skill.description,
                "source": skill.source,
                "execution_mode": skill.execution_mode,
                "version": skill.version or "",
            }
            for skill in self.list_skills()
        ]

    def find_references(self, name: str, query: str, limit: int = 5) -> list[dict[str, str]]:
        skill = self.get_skill(name)
        if skill is None or not skill.reference_index:
            return []

        keywords = _query_keywords(query)
        if not keywords:
            return skill.reference_index[:limit]

        scored_items: list[tuple[int, dict[str, str]]] = []
        for item in skill.reference_index:
            score = 0
            title_lower = item.get("title_lower", "")
            category_lower = item.get("category_lower", "")
            path_lower = item.get("path", "").lower()

            for keyword in keywords:
                if keyword in title_lower:
                    score += 4
                if keyword in category_lower:
                    score += 2
                if keyword in path_lower:
                    score += 1

            if "板块" in keywords or "行业" in keywords or "指数" in keywords:
                if "板块" in title_lower or "指数" in title_lower or "行业" in title_lower:
                    score += 3
            if "财务" in keywords or "财报" in keywords or "利润" in keywords or "现金流" in keywords:
                if any(token in title_lower for token in ("财务", "利润", "现金流", "资产负债")):
                    score += 3
            if "行情" in keywords or "日线" in keywords or "分钟" in keywords:
                if any(token in title_lower for token in ("行情", "日线", "分钟")):
                    score += 3

            if score > 0:
                scored_items.append((score, item))

        if not scored_items:
            return skill.reference_index[:limit]

        scored_items.sort(key=lambda pair: (-pair[0], pair[1].get("path", "")))
        unique_paths: set[str] = set()
        results: list[dict[str, str]] = []
        for _, item in scored_items:
            path = item.get("path", "")
            if path in unique_paths:
                continue
            unique_paths.add(path)
            results.append(
                {
                    "title": item.get("title", ""),
                    "category": item.get("category", ""),
                    "path": path,
                }
            )
            if len(results) >= limit:
                break
        return results


_DEFAULT_REGISTRY: SkillRegistry | None = None


def get_skill_registry(refresh: bool = False) -> SkillRegistry:
    global _DEFAULT_REGISTRY
    if _DEFAULT_REGISTRY is None:
        _DEFAULT_REGISTRY = SkillRegistry()
    elif refresh:
        _DEFAULT_REGISTRY.refresh()
    return _DEFAULT_REGISTRY
