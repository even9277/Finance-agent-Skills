"""验证记忆迁移的版本化离线 case inventory 与当前支持基线。"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import Any

import pytest

DATA_PATH = Path(__file__).resolve().parent / "data" / "characterization_v1.jsonl"
DATASET_VERSION = "memory-characterization-v1"
REQUIRED_MODULES = {
    "stm_budget",
    "context_gateway",
    "working_state",
    "rolling_summary",
    "redis_cache",
    "candidate_governance",
    "memory_governance",
    "hybrid_retrieval",
    "memory_command",
    "memory_api",
    "observability",
}


def _load_cases() -> list[dict[str, Any]]:
    """读取固定 JSONL 数据集并保留原始记录顺序。"""
    return [
        json.loads(line)
        for line in DATA_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


@pytest.mark.eval_smoke
def test_memory_characterization_dataset_is_versioned_and_complete() -> None:
    """确认数据集覆盖全部记忆模块并且 case ID 稳定唯一。"""
    cases = _load_cases()
    case_ids = [str(case["case_id"]) for case in cases]

    evidence_tests = [str(case["evidence_test"]) for case in cases]

    assert len(cases) == 14
    assert len(case_ids) == len(set(case_ids))
    assert len(evidence_tests) == len(set(evidence_tests))
    assert {case["dataset_version"] for case in cases} == {DATASET_VERSION}
    assert {case["module"] for case in cases} == REQUIRED_MODULES
    assert all(case.get("scenario") and case.get("gold") for case in cases)
    assert all(str(case["evidence_test"]).startswith("tests/") for case in cases)
    for evidence_test in evidence_tests:
        relative_path, node_id = evidence_test.split("::", maxsplit=1)
        test_path = DATA_PATH.parents[3] / Path(relative_path).relative_to("tests")
        assert test_path.is_file()
        tree = ast.parse(test_path.read_text(encoding="utf-8"))
        function_names = {
            node.name
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        assert node_id in function_names


@pytest.mark.eval_smoke
def test_memory_characterization_baseline_distinguishes_support_from_target_gaps() -> None:
    """确认 M1 基线不把模块文件存在或待实现口径冒充已完成能力。"""
    cases = _load_cases()
    supported = [case for case in cases if case["expected_current_status"] == "supported"]
    target_gaps = [case for case in cases if case["expected_current_status"] == "target_gap"]

    assert len(supported) == 9
    assert len(target_gaps) == 5
    assert all(case.get("issue") == "#24" for case in target_gaps)
    assert all(case.get("target_milestone") in {"M2", "M3", "M5", "M6", "M7", "M8"} for case in target_gaps)
    assert all(case.get("evidence_level") == "tripwire" for case in target_gaps)
    assert all(case.get("strict_xfail") is True for case in target_gaps)
    assert all("issue" not in case for case in supported)


@pytest.mark.eval_smoke
def test_memory_characterization_fixtures_are_synthetic_and_secret_free() -> None:
    """确认离线样例只含虚拟标识，不包含凭证或真实个人数据。"""
    raw = DATA_PATH.read_text(encoding="utf-8")
    forbidden_patterns = (
        r"sk-[A-Za-z0-9_-]{16,}",
        r"gh[opusr]_[A-Za-z0-9]{20,}",
        r"(?i)(api[_-]?key|password|secret)\s*[:=]",
        r"(?i)postgres(?:ql)?://[^\s]+:[^\s]+@",
    )

    assert all(re.search(pattern, raw) is None for pattern in forbidden_patterns)
