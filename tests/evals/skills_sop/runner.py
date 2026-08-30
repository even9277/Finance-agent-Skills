"""执行五类金融 Skills 的确定性离线全链评测并生成脱敏 artifact。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[3]
AGENT_ROOT = PROJECT_ROOT / "Financial-MCP-Agent"
for import_root in (PROJECT_ROOT, AGENT_ROOT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from backend.application.chat.contracts import ChatCommand  # noqa: E402
from backend.application.chat.use_case import ControlledChatUseCase  # noqa: E402
from backend.infrastructure.chat.testing import (  # noqa: E402
    FakeModelProvider,
    FakeToolProvider,
    InMemoryConversationRepository,
    InMemoryTraceSink,
)
from src.conversation.contracts import (  # noqa: E402
    ClaimLevel,
    SkillCatalogSnapshot,
    TerminalStatus,
)
from src.conversation.tool_governance import ToolGovernanceCatalog  # noqa: E402
from src.conversation.workflow import ControlledConversationWorkflow  # noqa: E402
from src.skills.loader import SkillLoader  # noqa: E402
from src.skills.skill_registry import SkillRegistry  # noqa: E402

RUNNER_VERSION = "skills-sop-eval-v1"
PROVIDER_NAME = "deterministic"
_OVERCLAIM_TERMS = (
    "必然",
    "一定",
    "确定导致",
    "唯一原因",
    "保证",
    "直接买入",
    "强烈买入",
    "will definitely",
    "guaranteed",
)
_EVIDENCE_ALIASES = {
    "stock_basic": "basic_profile",
    "stock_market": "market_snapshot",
}


def _canonical_json(value: object) -> str:
    """返回稳定 JSON，用于跨 repeat 的内容指纹。"""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_text(value: str) -> str:
    """计算 UTF-8 文本的完整 SHA-256。"""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _git_commit_short() -> str:
    """尽力读取当前提交；Git 不可用时返回稳定占位值。"""
    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return commit or "unknown"


def _safe_rate(numerator: int, denominator: int) -> float:
    """计算六位小数的比例；空分母明确返回 0。"""
    return round(numerator / denominator, 6) if denominator else 0.0


def _evidence_coverage(expected: set[str], actual: set[str]) -> float:
    """计算 gold evidence 被已验收维度覆盖的比例。"""
    if not expected:
        return 1.0
    normalized = {_EVIDENCE_ALIASES.get(item, item) for item in expected}
    return _safe_rate(len(normalized & actual), len(normalized))


async def _predict_case(
    row: dict[str, Any],
    *,
    repeat_index: int,
    catalog: SkillCatalogSnapshot,
    loader: SkillLoader,
) -> dict[str, Any]:
    """通过真实 Workflow 和离线 Ports 执行一条数据集案例。

    Args:
        row: 已从版本化 JSONL 读取的单条 gold 案例。
        repeat_index: 从 1 开始的重复序号，仅用于 artifact 定位。
        catalog: 本轮评测固定的请求级 SkillCatalogSnapshot。
        loader: 与 catalog 来源相同的不可变 SkillLoader。

    Returns:
        不含用户原文、trace ID、模型正文或证据事实值的预测记录。
    """
    case_id = str(row["case_id"])
    gold = dict(row["gold"])
    outcome = await ControlledChatUseCase(
        workflow=ControlledConversationWorkflow(
            model=FakeModelProvider(),
            tool=FakeToolProvider(),
            trace=InMemoryTraceSink(),
            skill_catalog=catalog,
            skill_loader=loader,
        ),
        repository=InMemoryConversationRepository(),
    ).execute(
        ChatCommand(
            user_id="skills-sop-eval-user",
            session_id=f"skills-sop-{case_id}-{repeat_index}",
            message=str(row["user_message"]),
            explicit_skill=(
                str(row["explicit_skill"]) if row.get("explicit_skill") else None
            ),
        )
    )
    result = outcome.workflow_result
    route = result.route if result is not None else None
    plan = result.plan if result is not None else None
    verification = result.verification if result is not None else None
    planned_tools = sorted({item.tool_name for item in plan.steps}) if plan else []
    accepted_evidence = sorted(
        {item.evidence_dimension.value for item in verification.accepted}
    ) if verification else []
    claim_level = (
        verification.claim_level.value
        if verification is not None
        else ClaimLevel.REFUSE.value
        if outcome.status is TerminalStatus.NEEDS_CLARIFICATION
        else ClaimLevel.DESCRIPTIVE.value
    )
    should_clarify = outcome.status is TerminalStatus.NEEDS_CLARIFICATION
    allowed_tools = {str(item) for item in gold.get("allowed_tools", [])}
    forbidden_tools = {str(item) for item in gold.get("forbidden_tools", [])}
    actual_tools = set(planned_tools)
    plan_compliant = actual_tools <= allowed_tools and actual_tools.isdisjoint(forbidden_tools)
    expected_evidence = {str(item) for item in gold.get("expected_evidence_types", [])}
    coverage = _evidence_coverage(expected_evidence, set(accepted_evidence))
    overclaim = any(term in outcome.reply for term in _OVERCLAIM_TERMS)
    prediction = {
        "route_family": route.family.value if route is not None else None,
        "skill_id": route.skill_name if route is not None else None,
        "terminal_status": outcome.status.value,
        "should_clarify": should_clarify,
        "planned_tools": planned_tools,
        "accepted_evidence_types": accepted_evidence,
        "claim_level": claim_level,
        "plan_compliant": plan_compliant,
        "evidence_coverage": coverage,
        "overclaim": overclaim,
        "activation_match": (
            route is not None
            and route.family.value == gold.get("gold_route")
            and route.skill_name == gold.get("gold_skill_id")
        ),
        "clarification_match": should_clarify is bool(gold.get("should_clarify")),
        "claim_level_match": claim_level.casefold()
        == str(gold.get("allowed_claim_level") or "").casefold(),
    }
    return {
        "case_id": case_id,
        "repeat_index": repeat_index,
        "gold_skill_id": gold.get("gold_skill_id"),
        "prediction": prediction,
        "prediction_hash": _sha256_text(_canonical_json(prediction)),
    }


def _metric_summary(records: list[dict[str, Any]], *, case_count: int) -> dict[str, Any]:
    """从真实预测记录计算全局和单 Skill 指标。"""
    prediction_count = len(records)
    predictions = [dict(item["prediction"]) for item in records]
    predicted_skill_count = sum(1 for item in predictions if item["skill_id"] is not None)
    gold_skill_count = sum(1 for item in records if item["gold_skill_id"] is not None)
    correct_skill_count = sum(
        1
        for item in records
        if item["gold_skill_id"] is not None
        and item["prediction"]["skill_id"] == item["gold_skill_id"]
    )
    hashes_by_case: dict[str, set[str]] = defaultdict(set)
    for item in records:
        hashes_by_case[str(item["case_id"])].add(str(item["prediction_hash"]))

    per_skill: dict[str, dict[str, float | int]] = {}
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in records:
        grouped[str(item["gold_skill_id"] or "no-skill")].append(item)
    for skill_id, items in sorted(grouped.items()):
        per_skill[skill_id] = {
            "prediction_count": len(items),
            "activation_accuracy": _safe_rate(
                sum(1 for item in items if item["prediction"]["activation_match"]),
                len(items),
            ),
            "plan_compliance_rate": _safe_rate(
                sum(1 for item in items if item["prediction"]["plan_compliant"]),
                len(items),
            ),
            "evidence_coverage_rate": round(
                sum(float(item["prediction"]["evidence_coverage"]) for item in items)
                / len(items),
                6,
            ),
            "overclaim_rate": _safe_rate(
                sum(1 for item in items if item["prediction"]["overclaim"]),
                len(items),
            ),
        }

    return {
        "skill_activation_accuracy": _safe_rate(
            sum(1 for item in predictions if item["activation_match"]),
            prediction_count,
        ),
        "activation_precision": _safe_rate(correct_skill_count, predicted_skill_count),
        "activation_recall": _safe_rate(correct_skill_count, gold_skill_count),
        "plan_compliance_rate": _safe_rate(
            sum(1 for item in predictions if item["plan_compliant"]),
            prediction_count,
        ),
        "evidence_coverage_rate": round(
            sum(float(item["evidence_coverage"]) for item in predictions) / prediction_count,
            6,
        ) if prediction_count else 0.0,
        "clarification_accuracy": _safe_rate(
            sum(1 for item in predictions if item["clarification_match"]),
            prediction_count,
        ),
        "claim_level_accuracy": _safe_rate(
            sum(1 for item in predictions if item["claim_level_match"]),
            prediction_count,
        ),
        "overclaim_rate": _safe_rate(
            sum(1 for item in predictions if item["overclaim"]),
            prediction_count,
        ),
        "deterministic_stability_rate": _safe_rate(
            sum(1 for hashes in hashes_by_case.values() if len(hashes) == 1),
            case_count,
        ),
        "per_skill": per_skill,
    }


def _atomic_write(path: Path, content: str) -> None:
    """同目录写临时文件后原子替换，避免留下半份评测 artifact。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


async def run_skills_sop_eval(
    *,
    dataset_path: Path,
    output_dir: Path,
    repeat: int,
    mode: str,
) -> Path:
    """执行确定性 Skills SOP 评测并写 metrics/records 两份 artifact。

    Args:
        dataset_path: 当前 mode 对应的版本化 JSONL 路径。
        output_dir: 调用方显式指定的安全输出目录。
        repeat: 每条案例重复次数，范围 1 到 10。
        mode: `smoke` 或 `full`，写入数据集版本元数据。

    Returns:
        生成的 `skills_sop_metrics.json` 路径。

    Raises:
        ValueError: repeat 越界或数据集为空。
        FileNotFoundError: 指定 mode 的数据集不存在。
    """
    if not 1 <= repeat <= 10:
        raise ValueError("repeat must be between 1 and 10")
    raw_dataset = dataset_path.read_text(encoding="utf-8")
    rows = [json.loads(line) for line in raw_dataset.splitlines() if line.strip()]
    if not rows:
        raise ValueError("skills_sop dataset must not be empty")

    registry = SkillRegistry()
    catalog = registry.conversation_snapshot()
    loader = registry.get_loader()
    records: list[dict[str, Any]] = []
    for repeat_index in range(1, repeat + 1):
        for row in rows:
            records.append(
                await _predict_case(
                    row,
                    repeat_index=repeat_index,
                    catalog=catalog,
                    loader=loader,
                )
            )

    records_text = "".join(
        f"{_canonical_json(record)}\n" for record in records
    )
    records_hash = _sha256_text(records_text)
    metrics = _metric_summary(records, case_count=len(rows))
    reproducibility_payload = {
        "dataset_version": f"skills-sop-{mode}-v1",
        "dataset_hash": _sha256_text(raw_dataset),
        "runner_version": RUNNER_VERSION,
        "registry_snapshot_hash": catalog.registry_snapshot_hash or catalog.snapshot_hash,
        "tool_schema_version": ToolGovernanceCatalog.default().version,
        "provider": PROVIDER_NAME,
        "repeat": repeat,
        "case_count": len(rows),
        "records_hash": records_hash,
        "metrics": metrics,
    }
    report = {
        "target": "skills_sop",
        "mode": mode,
        "count": len(rows),
        "prediction_count": len(records),
        "repeat": repeat,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "git_commit": _git_commit_short(),
        **{key: reproducibility_payload[key] for key in (
            "dataset_version",
            "dataset_hash",
            "runner_version",
            "registry_snapshot_hash",
            "tool_schema_version",
            "provider",
        )},
        "model_provider": "FakeModelProvider",
        "tool_provider": "FakeToolProvider",
        "metrics": metrics,
        "historical_metrics": {
            "status": "not_reproduced",
            "reason": "历史 75×3 原始数据集和 artifact 不存在；本报告仅为当前 15-case 新基线。",
        },
        "artifacts": {
            "records": {
                "path": "skills_sop_records.jsonl",
                "sha256": records_hash,
            }
        },
        "reproducibility_hash": _sha256_text(
            _canonical_json(reproducibility_payload)
        ),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    records_path = output_dir / "skills_sop_records.jsonl"
    report_path = output_dir / "skills_sop_metrics.json"
    _atomic_write(records_path, records_text)
    _atomic_write(report_path, json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return report_path


def run_from_cli(*, dataset_path: Path, output_dir: Path, repeat: int, mode: str) -> Path:
    """从同步 CLI 边界执行异步 runner。"""
    return asyncio.run(
        run_skills_sop_eval(
            dataset_path=dataset_path,
            output_dir=output_dir,
            repeat=repeat,
            mode=mode,
        )
    )


__all__ = ["RUNNER_VERSION", "run_from_cli", "run_skills_sop_eval"]
