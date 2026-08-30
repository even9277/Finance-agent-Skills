from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from threading import RLock
from typing import Any

import yaml

from src.conversation.contracts import SkillCatalogSnapshot, SkillDescriptor
from src.conversation.tool_governance import ToolGovernanceCatalog
from src.skills.contracts import SUPPORTED_FINANCIAL_SOP_EVIDENCE_TYPES
from src.skills.lifecycle import SkillStatus
from src.skills.loader import SkillLoader
from src.skills.reference_index import ReferenceIndex, ReferenceIndexError
from src.skills.schema_gate import SkillValidationReport, validate_skill_directory
from src.skills.snapshot import (
    RegistrySnapshot,
    SkillSnapshotEntry,
    SkillSnapshotError,
    SkillSnapshotManager,
    build_registry_snapshot,
)
from src.utils.logging_config import setup_logger

_SRC_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_SKILLS_DIR = _SRC_ROOT / "skills"
_DEFAULT_VENDOR_SKILLS_DIR = _SRC_ROOT.parent.parent / "vendor" / "tushare-skills"
logger = setup_logger("skill_registry")


class SkillRegistryRefreshError(RuntimeError):
    """表示候选资产未能形成完整快照，active/LKG 保持不变。"""


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
                current_list = []
                parsed[current_key] = current_list
                current_map = None
            current_list.append(_parse_scalar(raw_line[4:]))
            continue

        if raw_line.startswith("  ") and current_key and ":" in raw_line:
            if current_map is None:
                current_map = {}
                parsed[current_key] = current_map
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
    except (OSError, json.JSONDecodeError):
        logger.warning(
            "stage=skill_registry.metadata status=FAILED error_code=META_JSON_INVALID"
        )
        return {}


def _load_yaml_file(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        logger.warning(
            "stage=skill_registry.metadata status=FAILED error_code=YAML_INVALID"
        )
        return None
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        logger.warning(
            "stage=skill_registry.metadata status=FAILED error_code=YAML_ROOT_INVALID"
        )
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
    """加载 workspace/vendor Skill 元数据并提供受控只读视图。"""

    def __init__(
        self,
        skills_dir: Path | None = None,
        vendor_skills_dir: Path | None = None,
        *,
        token_budget_per_stage: int = 4_096,
    ) -> None:
        """初始化 Registry，并在存在 SOP 资产时发布首个合法快照。

        Args:
            skills_dir: workspace Skill 根目录；默认使用当前包目录。
            vendor_skills_dir: 官方 vendor Skill 根目录。
            token_budget_per_stage: Loader 每阶段的保守字符预算，至少 256。
        """
        if token_budget_per_stage < 256:
            raise ValueError("token_budget_per_stage must be at least 256")
        self.skills_dir = skills_dir or _DEFAULT_SKILLS_DIR
        self.vendor_skills_dir = vendor_skills_dir or _DEFAULT_VENDOR_SKILLS_DIR
        self._lock = RLock()
        self._skills: dict[str, SkillMetadata] = {}
        self._snapshot_manager = SkillSnapshotManager()
        self._validation_reports: tuple[SkillValidationReport, ...] = ()
        self._last_rejected_reports: tuple[SkillValidationReport, ...] = ()
        self._token_budget_per_stage = token_budget_per_stage
        self.refresh()

    def refresh(self) -> None:
        """扫描候选并原子发布完整快照；失败时保留 active/LKG。

        Raises:
            SkillRegistryRefreshError: SOP 候选缺失、校验失败或索引构建失败。
            ValueError: workspace/vendor 身份冲突。
        """
        with self._lock:
            skills = self._scan_metadata()
            candidate, reports = self._build_candidate_snapshot(skills)
            if candidate is None:
                if self._snapshot_manager.has_active_snapshot():
                    raise SkillRegistryRefreshError(
                        "refresh rejected because no complete workspace SOP asset set was found"
                    )
                # 仅 vendor/兼容 Skill 的 Registry 仍可用于历史 metadata API；
                # conversation_snapshot/get_loader 会因没有 active 快照而 fail closed。
                self._skills = skills
                self._validation_reports = reports
                logger.info(
                    "stage=skill_registry.refresh status=SKIPPED active_count=0 rejected_count=0"
                )
                return

            self._snapshot_manager.propose_snapshot(candidate)
            active = self._snapshot_manager.activate_snapshot(candidate.registry_version)
            self._skills = skills
            self._validation_reports = reports
            self._last_rejected_reports = ()
            logger.info(
                "stage=skill_registry.refresh status=SUCCEEDED registry_version=%s "
                "snapshot_hash=%s active_count=%d rejected_count=0",
                active.registry_version,
                active.snapshot_hash,
                len(active.active_skill_ids()),
            )

    def _scan_metadata(self) -> dict[str, SkillMetadata]:
        """保持原有 vendor→workspace precedence 扫描并拒绝身份冲突。"""
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
                except (OSError, json.JSONDecodeError, yaml.YAMLError):
                    logger.warning(
                        "stage=skill_registry.scan status=FAILED "
                        "error_code=SKILL_METADATA_READ_FAILED source=%s",
                        source,
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
        return skills

    def _build_candidate_snapshot(
        self,
        skills: dict[str, SkillMetadata],
    ) -> tuple[RegistrySnapshot | None, tuple[SkillValidationReport, ...]]:
        """将 workspace SOP 目录完整 join 到 Gate、索引和快照条目。"""
        if not self.skills_dir.exists():
            return None, ()
        asset_dirs = tuple(
            path
            for path in sorted(self.skills_dir.iterdir())
            if path.is_dir() and (path / "skill_spec.yaml").is_file()
        )
        if not asset_dirs:
            return None, ()

        metadata_by_dir = {
            metadata.skill_dir.resolve(): metadata
            for metadata in skills.values()
            if metadata.source == "workspace" and metadata.skill_dir is not None
        }
        governed_tools = {
            policy.tool_name for policy in ToolGovernanceCatalog.default().policies
        }
        # Web News 是冻结计划已批准的资产权限；实际治理 policy/handler 在 Milestone 6 接入。
        governed_tools.add("search_web_news")
        reports: list[SkillValidationReport] = []
        entries: list[SkillSnapshotEntry] = []
        try:
            for skill_dir in asset_dirs:
                metadata = metadata_by_dir.get(skill_dir.resolve())
                if metadata is None:
                    raise SkillRegistryRefreshError(
                        f"workspace SOP metadata is incomplete: {skill_dir.name}"
                    )
                report = validate_skill_directory(
                    skill_dir,
                    allowed_tool_names=governed_tools,
                    evidence_types=SUPPORTED_FINANCIAL_SOP_EVIDENCE_TYPES,
                )
                reports.append(report)
                if not report.passed or report.typed_spec is None:
                    continue
                reference_index = ReferenceIndex.from_skill_dir(metadata.name, skill_dir)
                markdown = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
                entries.append(
                    SkillSnapshotEntry(
                        skill_id=metadata.name,
                        status=SkillStatus.ACTIVE,
                        skill_version=report.typed_spec.version,
                        spec_hash=report.spec_hash,
                        document_hash=report.document_hash,
                        reference_hash=report.reference_hash,
                        description=metadata.description,
                        execution_mode=report.typed_spec.execution_policy,
                        source=metadata.source,
                        aliases=tuple(sorted(set(metadata.aliases))),
                        allowed_tools=report.typed_spec.allowed_tools,
                        reference_paths=tuple(item.path for item in reference_index.items),
                        skill_dir=skill_dir.resolve(),
                        spec=report.typed_spec,
                        markdown=markdown,
                        reference_index=reference_index,
                    )
                )
        except (OSError, ReferenceIndexError, SkillSnapshotError) as exc:
            self._last_rejected_reports = tuple(reports)
            logger.warning(
                "stage=skill_registry.refresh status=FAILED error_code=ASSET_BUILD_FAILED "
                "active_preserved=%s rejected_count=%d",
                self._snapshot_manager.has_active_snapshot(),
                len(reports),
            )
            raise SkillRegistryRefreshError("failed to build complete Skill snapshot") from exc

        rejected = tuple(report for report in reports if not report.passed)
        if rejected or len(entries) != len(asset_dirs):
            self._last_rejected_reports = tuple(reports)
            logger.warning(
                "stage=skill_registry.refresh status=FAILED error_code=SCHEMA_GATE_REJECTED "
                "active_preserved=%s rejected_count=%d",
                self._snapshot_manager.has_active_snapshot(),
                len(rejected) or len(asset_dirs) - len(entries),
            )
            raise SkillRegistryRefreshError("Skill schema gate rejected candidate snapshot")

        try:
            return build_registry_snapshot(entries), tuple(reports)
        except SkillSnapshotError as exc:
            self._last_rejected_reports = tuple(reports)
            raise SkillRegistryRefreshError("candidate snapshot is not publishable") from exc

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
        canonical_name = canonical_name.strip()
        if canonical_name and canonical_name not in aliases:
            aliases.append(canonical_name)

        references_dir = skill_file.parent / "references" if (skill_file.parent / "references").exists() else None
        scripts_dir = skill_file.parent / "scripts" if (skill_file.parent / "scripts").exists() else None
        spec_file = skill_file.parent / "skill_spec.yaml"

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
        )

    def list_skills(self) -> list[SkillMetadata]:
        """返回当前成功刷新对应的 metadata 浅拷贝。"""
        with self._lock:
            return list(self._skills.values())

    def get_skill(self, name: str) -> SkillMetadata | None:
        """按稳定名称或别名读取当前 metadata。"""
        with self._lock:
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
        """只返回当前 active 快照已发布的 workspace SOP metadata。"""
        if not self._snapshot_manager.has_active_snapshot():
            return []
        active_names = set(self.runtime_snapshot().active_skill_ids())
        return [skill for skill in self.list_skills() if skill.name in active_names]

    def runtime_snapshot(self) -> RegistrySnapshot:
        """返回当前 active 的请求可固定 Registry 快照。"""
        return self._snapshot_manager.get_active_snapshot()

    def validation_reports(self) -> tuple[SkillValidationReport, ...]:
        """返回当前 active 快照对应的 Gate 报告，不含资产正文。"""
        with self._lock:
            return self._validation_reports

    def last_rejected_reports(self) -> tuple[SkillValidationReport, ...]:
        """返回最近一次失败刷新已完成的 Gate 报告。"""
        with self._lock:
            return self._last_rejected_reports

    def get_loader(
        self,
        snapshot: RegistrySnapshot | None = None,
        *,
        token_budget_per_stage: int | None = None,
    ) -> SkillLoader:
        """创建固定快照的分阶段 Loader。

        Args:
            snapshot: 请求已固定的快照；空值时固定调用瞬间的 active 引用。
            token_budget_per_stage: 可选请求级预算覆盖，不改变 Registry 默认值。

        Returns:
            后续刷新不会改变其内容的 `SkillLoader`。
        """
        return SkillLoader(
            snapshot or self.runtime_snapshot(),
            token_budget_per_stage=(
                self._token_budget_per_stage
                if token_budget_per_stage is None
                else token_budget_per_stage
            ),
        )

    def conversation_snapshot(
        self,
        snapshot: RegistrySnapshot | None = None,
    ) -> SkillCatalogSnapshot:
        """构建受控对话 Stage1 使用的不可变 Skill 快照。

        Args:
            snapshot: 可选的请求级固定快照；用于与 Loader 共享完全相同的发布版本。

        Returns:
            仅包含可发现 workspace SOP 的元数据、执行白名单和已登记引用路径；
            不读取或暴露完整 Skill 正文。
        """
        frozen_snapshot = snapshot or self.runtime_snapshot()
        descriptors = tuple(
            SkillDescriptor(
                name=entry.skill_id,
                description=entry.description,
                version=entry.skill_version,
                execution_mode=entry.execution_mode,
                allowed_tools=entry.allowed_tools,
                reference_paths=entry.reference_paths,
                spec_hash=entry.spec_hash,
                document_hash=entry.document_hash,
                reference_hash=entry.reference_hash,
                when_to_use=entry.spec.route_metadata.when_to_use,
                when_not_to_use=entry.spec.route_metadata.when_not_to_use,
                positive_examples=entry.spec.route_metadata.positive_examples,
                negative_examples=entry.spec.route_metadata.negative_examples,
                supported_entity_types=entry.spec.route_metadata.supported_entity_types,
            )
            for entry in frozen_snapshot.entries.values()
            if entry.status.value == "active" and entry.spec is not None
        )
        return SkillCatalogSnapshot.create(
            version="workspace-skills-v1",
            skills=descriptors,
            registry_version=frozen_snapshot.registry_version,
            registry_snapshot_hash=frozen_snapshot.snapshot_hash,
        )

    def _active_entry(self, name: str) -> SkillSnapshotEntry | None:
        """按名称或冻结别名读取 active 条目。"""
        if not self._snapshot_manager.has_active_snapshot():
            return None
        snapshot = self.runtime_snapshot()
        direct = snapshot.get(name)
        if direct is not None:
            return direct
        for entry in snapshot.entries.values():
            if name in entry.aliases:
                return entry
        return None

    def load_skill_spec(self, name: str) -> dict[str, Any] | None:
        """兼容旧调用方返回 active typed spec 的 Python mapping。"""
        entry = self._active_entry(name)
        if entry is not None and entry.spec is not None:
            return entry.spec.model_dump(mode="python")
        skill = self.get_skill(name)
        if skill is None or skill.spec_file is None:
            return None
        return _load_yaml_file(skill.spec_file)

    def load_skill_markdown(self, name: str) -> str:
        """优先返回 active 快照固定的 Markdown；vendor 走兼容只读路径。"""
        entry = self._active_entry(name)
        if entry is not None:
            return entry.markdown
        skill = self.get_skill(name)
        if skill is None or skill.skill_file is None or not skill.skill_file.exists():
            return ""
        try:
            return skill.skill_file.read_text(encoding="utf-8")
        except OSError:
            logger.warning(
                "stage=skill_registry.read status=FAILED error_code=SKILL_MARKDOWN_READ_FAILED"
            )
            return ""

    def load_reference_texts(
        self,
        name: str,
        query: str,
        limit: int = 3,
    ) -> list[dict[str, str]]:
        """兼容旧调用方，从固定索引返回 synthesis reference 正文。"""
        entry = self._active_entry(name)
        if entry is not None and entry.reference_index is not None:
            selected = entry.reference_index.search(
                query,
                stage="synthesis",
                top_k=min(10, max(1, limit)),
                token_budget=max(2_048, self._token_budget_per_stage * 4),
            )
            return [
                {
                    "title": item.title,
                    "category": item.category,
                    "path": item.path,
                    "content": item.content,
                }
                for item in selected
            ]
        return self._load_legacy_reference_texts(name, query, limit)

    def _load_legacy_reference_texts(
        self,
        name: str,
        query: str,
        limit: int,
    ) -> list[dict[str, str]]:
        """为未进入金融 SOP 快照的 vendor Skill 保留历史只读行为。"""
        skill = self.get_skill(name)
        if skill is None or skill.skill_dir is None:
            return []
        results: list[dict[str, str]] = []
        for item in self._find_legacy_references(name, query, limit=limit):
            rel_path = item.get("path") or ""
            if not rel_path:
                continue
            try:
                resolved = (skill.skill_dir / rel_path).resolve(strict=True)
                resolved.relative_to(skill.skill_dir.resolve())
                content = resolved.read_text(encoding="utf-8")
            except (OSError, ValueError):
                logger.warning(
                    "stage=skill_registry.read status=FAILED "
                    "error_code=REFERENCE_READ_FAILED skill=%s",
                    skill.name,
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

    def find_references(self, name: str, query: str, limit: int = 5) -> list[dict[str, str]]:
        """返回不含正文的固定 reference 元数据；vendor 使用兼容索引。"""
        entry = self._active_entry(name)
        if entry is not None and entry.reference_index is not None:
            selected = entry.reference_index.search(
                query,
                stage="synthesis",
                top_k=min(10, max(1, limit)),
                token_budget=max(2_048, self._token_budget_per_stage * 4),
            )
            return [
                {
                    "title": item.title,
                    "category": item.category,
                    "path": item.path,
                }
                for item in selected
            ]
        return self._find_legacy_references(name, query, limit=limit)

    def _find_legacy_references(
        self,
        name: str,
        query: str,
        *,
        limit: int,
    ) -> list[dict[str, str]]:
        """检索未迁移 vendor Skill 的历史 metadata-only reference 索引。"""
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
