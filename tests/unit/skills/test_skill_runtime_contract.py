"""冻结 Skills 治理运行时需要提供的版本、生命周期、快照和 Loader 合同。"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, cast

import pytest

ROOT = Path(__file__).resolve().parents[3]
AGENT_ROOT = ROOT / "Financial-MCP-Agent"
if str(AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(AGENT_ROOT))


def _require_module(module_name: str) -> ModuleType:
    """导入目标治理模块；缺失时给出清晰的迁移红灯。"""
    try:
        return importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        pytest.fail(f"missing planned Skills runtime module: {module_name}: {exc}")


@pytest.mark.unit
@pytest.mark.parametrize(
    ("module_name", "symbols"),
    (
        ("src.skills.schema_gate", ("SkillValidationReport", "validate_skill")),
        ("src.skills.version", ("SkillVersion", "stable_hash_text")),
        (
            "src.skills.lifecycle",
            ("SkillStatus", "SkillLifecycleError", "can_transition", "transition"),
        ),
        (
            "src.skills.snapshot",
            ("SkillSnapshotEntry", "RegistrySnapshot", "SkillSnapshotManager", "build_registry_snapshot"),
        ),
        ("src.skills.reference_index", ("ReferenceItem", "ReferenceIndex")),
        ("src.skills.loader", ("LoadedSkillContext", "SkillLoader")),
    ),
)
def test_skills_runtime_exposes_frozen_governance_boundaries(
    module_name: str,
    symbols: tuple[str, ...],
) -> None:
    """治理职责必须拆为明确模块，不能继续堆在薄 Registry 单文件。"""
    module = _require_module(module_name)
    missing = [symbol for symbol in symbols if not hasattr(module, symbol)]
    assert not missing, f"{module_name} missing public contracts: {missing}"


@pytest.mark.unit
def test_skill_version_normalizes_line_endings_and_declared_version() -> None:
    """同内容不同换行必须得到相同 hash，声明版本必须稳定规范化。"""
    module = _require_module("src.skills.version")
    assert module.stable_hash_text("a\r\nb\n") == module.stable_hash_text("a\nb")
    assert module.SkillVersion("1.2.3").normalized == "1.2.3"
    assert module.SkillVersion("").normalized == "0.1.0"


@pytest.mark.unit
def test_skill_lifecycle_allows_shadow_activation_and_rejects_deprecated_revival() -> None:
    """生命周期允许受控激活，但禁止 deprecated 直接回到 active。"""
    module = _require_module("src.skills.lifecycle")
    assert module.can_transition("shadow", "active") is True
    assert module.transition("shadow", "active") == module.SkillStatus.ACTIVE
    assert module.can_transition("deprecated", "active") is False
    with pytest.raises(module.SkillLifecycleError):
        module.transition("deprecated", "active")


@pytest.mark.unit
def test_snapshot_manager_keeps_active_snapshot_immutable_and_last_known_good() -> None:
    """新快照只有显式激活后生效，active/LKG 映射不可被请求侧修改。"""
    module = _require_module("src.skills.snapshot")
    active_entry = module.SkillSnapshotEntry(
        skill_id="old-skill",
        status="active",
        skill_version="1.0.0",
        spec_hash="spec-old",
        reference_hash="ref-old",
    )
    new_entry = module.SkillSnapshotEntry(
        skill_id="new-skill",
        status="active",
        skill_version="1.1.0",
        spec_hash="spec-new",
        reference_hash="ref-new",
    )
    manager = module.SkillSnapshotManager(
        module.build_registry_snapshot((active_entry,), registry_version="registry-old")
    )

    pending = manager.propose_snapshot(
        module.build_registry_snapshot((new_entry,), registry_version="registry-new")
    )
    assert pending.registry_version == "registry-new"
    assert manager.get_active_snapshot().get("old-skill") is not None

    activated = manager.activate_snapshot("registry-new")
    assert activated.get("new-skill") is not None
    assert manager.get_last_known_good_snapshot().registry_version == "registry-new"
    with pytest.raises(TypeError):
        activated.entries["mutated"] = new_entry


@pytest.mark.unit
def test_registry_loader_exposes_three_isolated_stage_views() -> None:
    """Loader 必须分别提供 rewrite、planner、synthesis 上下文和加载证据。"""
    from src.skills.skill_registry import SkillRegistry

    registry = SkillRegistry()
    loader_factory = getattr(registry, "get_loader", None)
    assert callable(loader_factory), "SkillRegistry must expose a validated stage loader"
    loader = cast(Callable[[], Any], loader_factory)()

    rewrite = loader.load_for_rewrite("fund-compare", query="比较两只黄金 ETF")
    planner = loader.load_for_planner("fund-compare", query="比较两只黄金 ETF")
    synthesis = loader.load_for_synthesis("fund-compare", query="比较两只黄金 ETF")

    assert rewrite.stage == "rewrite"
    assert planner.stage == "planner"
    assert synthesis.stage == "synthesis"
    assert "allowed_tools" not in rewrite.artifact()["spec_view"]
    assert planner.artifact()["spec_view"]["allowed_tools"]
    assert synthesis.artifact()["spec_view"]["output_template"]
    assert all(item["content_hash"] for item in planner.artifact()["references_loaded"])
