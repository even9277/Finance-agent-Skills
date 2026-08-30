"""在 Skill 进入 Registry 前校验资产、权限、证据和路径合同。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Mapping, cast

import yaml
from pydantic import JsonValue, ValidationError

from .contracts import (
    REQUIRED_SKILL_SECTIONS,
    ReferenceMetadata,
    SkillDocumentMetadata,
    SkillSpec,
)
from .lifecycle import SkillStatus
from .version import combine_hashes, stable_hash_mapping, stable_hash_text

_FRONTMATTER_PATTERN = re.compile(r"^---\r?\n(.*?)\r?\n---\r?\n", flags=re.DOTALL)


@dataclass(frozen=True, slots=True)
class SchemaGateIssue:
    """描述一项不含资产正文的稳定校验失败。"""

    code: str
    message: str
    field: str = ""
    severity: str = "error"


@dataclass(frozen=True, slots=True)
class SkillValidationReport:
    """汇总 Skill gate 结果、类型化 spec 和可追溯内容哈希。"""

    skill_name: str
    status: SkillStatus
    issues: tuple[SchemaGateIssue, ...] = field(default_factory=tuple)
    spec_hash: str = ""
    document_hash: str = ""
    reference_hash: str = ""
    typed_spec: SkillSpec | None = field(default=None, repr=False)

    @property
    def passed(self) -> bool:
        """仅当不存在 error 级问题且 spec 已类型化时通过。"""
        return self.typed_spec is not None and not any(
            issue.severity == "error" for issue in self.issues
        )

    @property
    def disabled_reason(self) -> str:
        """返回可用于状态/Trace 的低基数失败码集合。"""
        return ";".join(issue.code for issue in self.issues if issue.severity == "error")


def _issue_from_validation(error: Mapping[str, object], *, code: str) -> SchemaGateIssue:
    """把 Pydantic 细节压缩为不泄露原始资产内容的 gate issue。"""
    raw_location = error.get("loc")
    location = (
        ".".join(str(item) for item in raw_location)
        if isinstance(raw_location, (tuple, list))
        else ""
    )
    message = str(error.get("msg") or "invalid contract")
    return SchemaGateIssue(code=code, message=message, field=location)


def _parse_frontmatter(text: str) -> Mapping[str, object]:
    """解析 Markdown frontmatter；格式错误由调用方转为 fail-closed issue。"""
    match = _FRONTMATTER_PATTERN.match(text)
    if match is None:
        raise ValueError("missing YAML frontmatter")
    payload = yaml.safe_load(match.group(1))
    if not isinstance(payload, dict):
        raise ValueError("frontmatter root must be a mapping")
    return cast(Mapping[str, object], payload)


def _canonical_spec_hash(spec: SkillSpec) -> str:
    """根据类型化 JSON 视图计算与 YAML 排版无关的 spec hash。"""
    payload = cast(Mapping[str, JsonValue], spec.model_dump(mode="json"))
    return stable_hash_mapping(payload)


def validate_skill(
    spec: Mapping[str, object] | None,
    *,
    allowed_tool_names: Iterable[str],
    evidence_types: Iterable[str],
    expected_skill_name: str | None = None,
    aliases: Iterable[str] = (),
    spec_hash: str = "",
    reference_hash: str = "",
) -> SkillValidationReport:
    """校验单个机器 spec 以及外部工具/证据治理交集。

    Args:
        spec: YAML 解析后的未信任 mapping。
        allowed_tool_names: 当前唯一工具治理目录允许的工具名。
        evidence_types: 当前证据合同允许的维度名。
        expected_skill_name: 目录或 Registry 期望的稳定 Skill 名。
        aliases: 允许解析到同一 Skill 的显式别名。
        spec_hash: 调用方已有的原始 spec hash；空值时根据类型化内容计算。
        reference_hash: 同一资产版本对应的 reference 集合哈希。

    Returns:
        不抛出资产格式异常的 fail-closed 报告；通过时包含 `typed_spec`。
    """
    issues: list[SchemaGateIssue] = []
    typed_spec: SkillSpec | None = None
    payload: object = dict(spec or {})
    try:
        typed_spec = SkillSpec.model_validate(payload)
    except ValidationError as exc:
        issues.extend(
            _issue_from_validation(error, code="invalid_skill_spec") for error in exc.errors()
        )

    skill_name = str((spec or {}).get("skill_name") or expected_skill_name or "unknown")
    if typed_spec is not None:
        skill_name = typed_spec.skill_name
        accepted_names = {expected_skill_name, *aliases} - {None, ""}
        if accepted_names and typed_spec.skill_name not in accepted_names:
            issues.append(
                SchemaGateIssue(
                    code="skill_name_mismatch",
                    message="spec skill_name does not match directory identity or aliases",
                    field="skill_name",
                )
            )

        governed_tools = {str(item).strip() for item in allowed_tool_names if str(item).strip()}
        unknown_tools = sorted(set(typed_spec.allowed_tools) - governed_tools)
        if unknown_tools:
            issues.append(
                SchemaGateIssue(
                    code="unknown_allowed_tool",
                    message=f"unknown governed tools: {','.join(unknown_tools)}",
                    field="allowed_tools",
                )
            )

        known_evidence = {str(item).strip() for item in evidence_types if str(item).strip()}
        unknown_evidence = sorted(typed_spec.required_evidence.dimensions() - known_evidence)
        if unknown_evidence:
            issues.append(
                SchemaGateIssue(
                    code="unknown_evidence_type",
                    message=f"unknown evidence types: {','.join(unknown_evidence)}",
                    field="required_evidence",
                )
            )

    resolved_spec_hash = spec_hash or (_canonical_spec_hash(typed_spec) if typed_spec else "")
    status = SkillStatus.ACTIVE if typed_spec is not None and not issues else SkillStatus.DISABLED
    return SkillValidationReport(
        skill_name=skill_name,
        status=status,
        issues=tuple(issues),
        spec_hash=resolved_spec_hash,
        reference_hash=reference_hash,
        typed_spec=typed_spec,
    )


def validate_skill_directory(
    skill_dir: Path,
    *,
    allowed_tool_names: Iterable[str],
    evidence_types: Iterable[str],
) -> SkillValidationReport:
    """校验一个 Skill 目录的 Markdown、spec、references 和 cases 四层资产。

    Args:
        skill_dir: 必须包含 `SKILL.md` 与 `skill_spec.yaml` 的目录。
        allowed_tool_names: 当前唯一工具治理目录的权限上界。
        evidence_types: 当前证据合同允许的维度名。

    Returns:
        资产内容哈希和全部低敏校验问题；任一层异常均禁用该 Skill。
    """
    root = skill_dir.resolve()
    skill_path = skill_dir / "SKILL.md"
    spec_path = skill_dir / "skill_spec.yaml"
    cases_path = skill_dir / "tests" / "cases.md"
    issues: list[SchemaGateIssue] = []
    markdown = ""
    document_metadata: SkillDocumentMetadata | None = None
    raw_spec: Mapping[str, object] | None = None

    try:
        markdown = skill_path.read_text(encoding="utf-8")
        document_metadata = SkillDocumentMetadata.model_validate(_parse_frontmatter(markdown))
    except (OSError, ValueError, ValidationError, yaml.YAMLError) as exc:
        issues.append(
            SchemaGateIssue("invalid_skill_markdown", str(exc), field="SKILL.md")
        )

    try:
        payload = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("skill_spec.yaml root must be a mapping")
        raw_spec = cast(Mapping[str, object], payload)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        issues.append(
            SchemaGateIssue("invalid_skill_yaml", str(exc), field="skill_spec.yaml")
        )

    base_report = validate_skill(
        raw_spec,
        allowed_tool_names=allowed_tool_names,
        evidence_types=evidence_types,
        expected_skill_name=skill_dir.name,
        aliases=document_metadata.aliases if document_metadata else (),
    )
    issues.extend(base_report.issues)

    if document_metadata and base_report.typed_spec:
        if document_metadata.name != skill_dir.name:
            issues.append(
                SchemaGateIssue("skill_name_mismatch", "frontmatter name must match directory", "name")
            )
        if set(document_metadata.allowed_tools) != set(base_report.typed_spec.allowed_tools):
            issues.append(
                SchemaGateIssue(
                    "frontmatter_tool_mismatch",
                    "frontmatter tools must equal spec allowed_tools",
                    "allowed_tools",
                )
            )
        missing_sections = [
            section for section in REQUIRED_SKILL_SECTIONS if f"## {section}" not in markdown
        ]
        if missing_sections:
            issues.append(
                SchemaGateIssue(
                    "missing_skill_section",
                    f"missing sections: {','.join(missing_sections)}",
                    "SKILL.md",
                )
            )

    if not cases_path.is_file():
        issues.append(SchemaGateIssue("missing_cases", "tests/cases.md is required", "tests/cases.md"))

    reference_parts: list[str] = []
    reference_paths = sorted((skill_dir / "references").rglob("*.md"))
    if not reference_paths:
        issues.append(SchemaGateIssue("missing_references", "at least one reference is required", "references"))
    known_evidence = {str(item).strip() for item in evidence_types if str(item).strip()}
    for reference_path in reference_paths:
        try:
            resolved = reference_path.resolve(strict=True)
            resolved.relative_to(root)
            content = resolved.read_text(encoding="utf-8")
            metadata = ReferenceMetadata.model_validate(_parse_frontmatter(content))
            unknown = sorted(set(metadata.evidence_types) - known_evidence)
            if unknown:
                issues.append(
                    SchemaGateIssue(
                        "unknown_reference_evidence",
                        f"unknown evidence types: {','.join(unknown)}",
                        str(reference_path.relative_to(skill_dir)),
                    )
                )
            relative_path = resolved.relative_to(root).as_posix()
            reference_parts.append(f"{relative_path}:{stable_hash_text(content)}")
        except (OSError, ValueError, ValidationError, yaml.YAMLError) as exc:
            issues.append(
                SchemaGateIssue(
                    "invalid_reference",
                    str(exc),
                    str(reference_path),
                )
            )

    reference_hash = combine_hashes(*reference_parts) if reference_parts else ""
    status = SkillStatus.ACTIVE if base_report.typed_spec is not None and not issues else SkillStatus.DISABLED
    return SkillValidationReport(
        skill_name=base_report.skill_name,
        status=status,
        issues=tuple(issues),
        spec_hash=base_report.spec_hash,
        document_hash=stable_hash_text(markdown) if markdown else "",
        reference_hash=reference_hash,
        typed_spec=base_report.typed_spec,
    )


__all__ = [
    "SchemaGateIssue",
    "SkillValidationReport",
    "validate_skill",
    "validate_skill_directory",
]
