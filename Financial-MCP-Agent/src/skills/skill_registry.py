from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any

import yaml

from src.skills_v2.lifecycle import SkillStatus
from src.skills_v2.loader import SkillLoader
from src.skills_v2.schema_gate import validate_skill
from src.skills_v2.snapshot import SkillSnapshotEntry, SkillSnapshotManager, build_registry_snapshot
from src.skills_v2.version import SkillVersion, stable_hash_text
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
    spec_file: Path | None = None
    has_skill_file: bool = True
    has_skill_spec: bool = False
    route_metadata: dict[str, Any] = field(default_factory=dict)


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


def _load_yaml_file(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("[skill_registry] failed to read yaml %s: %s", path, exc, exc_info=True)
        return None
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        logger.warning("[skill_registry] yaml root must be a mapping: %s", path)
        return None
    return payload


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
        self._snapshot_manager = SkillSnapshotManager()
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

                existing_key = self._find_existing_skill_key(skills, meta)
                if existing_key is not None:
                    existing = skills[existing_key]
                    if source == "workspace" and existing.source != "workspace":
                        logger.info(
                            "[skill_registry] workspace skill overrides vendor skill: %s -> %s",
                            existing_key,
                            meta.name,
                        )
                        if existing_key != meta.name:
                            del skills[existing_key]
                        skills[meta.name] = meta
                        continue
                    raise ValueError(
                        f"Duplicate skill identity detected: incoming={meta.name}, existing={existing.name}"
                    )
                skills[meta.name] = meta

        self._skills = skills
        self._snapshot_manager = SkillSnapshotManager(self._build_snapshot())
        logger.info("[skill_registry] loaded %s skills", len(self._skills))

    @staticmethod
    def _identity_keys(skill: SkillMetadata) -> set[str]:
        keys = {skill.name.strip(), skill.official_name.strip()}
        keys.update(alias.strip() for alias in skill.aliases if alias and alias.strip())
        return {item for item in keys if item}

    def _find_existing_skill_key(
        self,
        skills: dict[str, SkillMetadata],
        incoming: SkillMetadata,
    ) -> str | None:
        incoming_keys = self._identity_keys(incoming)
        for key, existing in skills.items():
            if incoming_keys & self._identity_keys(existing):
                return key
        return None

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
        canonical_name = canonical_name.strip()
        if canonical_name and canonical_name not in aliases:
            aliases.append(canonical_name)

        references_dir = skill_file.parent / "references" if (skill_file.parent / "references").exists() else None
        scripts_dir = skill_file.parent / "scripts" if (skill_file.parent / "scripts").exists() else None
        spec_file = skill_file.parent / "skill_spec.yaml"

        spec_payload = _load_yaml_file(spec_file) if spec_file.exists() else None
        route_metadata = {}
        if isinstance(spec_payload, dict) and isinstance(spec_payload.get("route_metadata"), dict):
            route_metadata = dict(spec_payload.get("route_metadata") or {})

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
            spec_file=spec_file if spec_file.exists() else None,
            has_skill_file=skill_file.exists(),
            has_skill_spec=spec_file.exists(),
            route_metadata=route_metadata,
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
                "has_skill_file": str(skill.has_skill_file).lower(),
                "has_skill_spec": str(skill.has_skill_spec).lower(),
            }
            for skill in self.list_skills()
        ]

    def discoverable_sop_skills(self) -> list[SkillMetadata]:
        """含 skill_spec.yaml 的 SOP：可被确定性执行器可靠执行。"""
        return [
            skill
            for skill in self.list_skills()
            if skill.source == "workspace"
            and skill.name != "tushare-data"
            and skill.has_skill_file
            and skill.has_skill_spec
        ]

    def workspace_sop_skills_for_router(self) -> list[SkillMetadata]:
        """进入路由提示词的工作区 SOP（仅需 SKILL.md）；无 spec 时仍可被 LLM 选中，执行前会降级。"""
        return [
            skill
            for skill in self.list_skills()
            if skill.source == "workspace"
            and skill.name != "tushare-data"
            and skill.has_skill_file
        ]

    def discoverable_sop_skills_for_router(self) -> list[dict[str, Any]]:
        """Lightweight metadata for stage1 routing; never exposes full SKILL.md."""
        from src.skills.route_metadata import RouteMetadataIndex

        index = RouteMetadataIndex.build_from_registry(self)
        return [item.prompt_summary() for item in index.items]

    def load_skill_spec(self, name: str) -> dict[str, Any] | None:
        skill = self.get_skill(name)
        if skill is None or skill.spec_file is None:
            return None
        return _load_yaml_file(skill.spec_file)

    def load_skill_markdown(self, name: str) -> str:
        skill = self.get_skill(name)
        if skill is None or skill.skill_file is None or not skill.skill_file.exists():
            return ""
        try:
            return skill.skill_file.read_text(encoding="utf-8")
        except Exception as exc:
            logger.warning("[skill_registry] failed to read skill markdown %s: %s", name, exc, exc_info=True)
            return ""

    def load_reference_texts(self, name: str, query: str, limit: int = 3) -> list[dict[str, str]]:
        skill = self.get_skill(name)
        if skill is None or skill.skill_dir is None:
            return []

        results: list[dict[str, str]] = []
        for item in self.find_references(name, query, limit=limit):
            rel_path = item.get("path") or ""
            if not rel_path:
                continue
            file_path = skill.skill_dir / rel_path
            try:
                content = file_path.read_text(encoding="utf-8")
            except Exception as exc:
                logger.warning(
                    "[skill_registry] failed to read reference %s for %s: %s",
                    rel_path,
                    name,
                    exc,
                    exc_info=True,
                )
                continue
            results.append(
                {
                    "title": item.get("title", ""),
                    "category": item.get("category", ""),
                    "path": rel_path,
                    "content": content,
                }
            )
        return results

    def _skill_hashes(self, skill: SkillMetadata) -> tuple[str, str]:
        spec_text = ""
        if skill.spec_file and skill.spec_file.exists():
            spec_text = skill.spec_file.read_text(encoding="utf-8")
        skill_text = ""
        if skill.skill_file and skill.skill_file.exists():
            skill_text = skill.skill_file.read_text(encoding="utf-8")
        reference_texts: list[str] = []
        if skill.skill_dir is not None:
            for ref in sorted((skill.skill_dir / "references").rglob("*.md")) if (skill.skill_dir / "references").exists() else []:
                reference_texts.append(ref.read_text(encoding="utf-8"))
        return stable_hash_text(spec_text or skill_text), stable_hash_text("\n".join(reference_texts))

    def _build_snapshot(self):
        try:
            from src.agents.tool_discovery.executable_registry import default_tool_specs
        except Exception:
            tool_specs = {}
        else:
            tool_specs = default_tool_specs()
        evidence_types = {spec.evidence_type for spec in tool_specs.values()}
        allowed_tool_names = set(tool_specs)
        entries: list[SkillSnapshotEntry] = []
        for skill in self._skills.values():
            spec = self.load_skill_spec(skill.name) or {}
            spec_hash, reference_hash = self._skill_hashes(skill)
            report = validate_skill(
                spec,
                allowed_tool_names=allowed_tool_names,
                evidence_types=evidence_types,
                spec_hash=spec_hash,
                reference_hash=reference_hash,
            ) if skill.has_skill_spec else None
            status = SkillStatus.ACTIVE if (report is None or report.passed) else SkillStatus.DISABLED
            entries.append(
                SkillSnapshotEntry(
                    skill_id=skill.name,
                    status=status,
                    skill_version=SkillVersion(str(spec.get("version") or skill.version or "0.1.0")).normalized,
                    spec_hash=spec_hash,
                    reference_hash=reference_hash,
                    source=skill.source,
                    disabled_reason=report.disabled_reason if report else "",
                )
            )
        return build_registry_snapshot(entries)

    def propose_snapshot(self):
        """提出新快照但不立即切换，给 schema gate / shadow 流程留缓冲。"""
        return self._snapshot_manager.propose_snapshot(self._build_snapshot())

    def activate_snapshot(self, registry_version: str | None = None):
        return self._snapshot_manager.activate_snapshot(registry_version)

    def rollback_snapshot(self):
        return self._snapshot_manager.rollback_snapshot()

    def get_active_snapshot(self):
        return self._snapshot_manager.get_active_snapshot()

    def get_last_known_good_snapshot(self):
        return self._snapshot_manager.get_last_known_good_snapshot()

    def get_loader(self, token_budget_per_stage: int = 2048) -> SkillLoader:
        return SkillLoader(registry=self, token_budget_per_stage=token_budget_per_stage)

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
