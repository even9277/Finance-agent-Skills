"""锁定 D09 共享实体解析器的受控兜底与目录回查合同。"""

from __future__ import annotations

import asyncio
import inspect
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
AGENT_ROOT = ROOT / "Financial-MCP-Agent"
for import_root in (ROOT, AGENT_ROOT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from src.conversation.contracts import (  # noqa: E402
    ContextPacket,
    Entity,
    EntityModelRequest,
    EntityModelResolution,
    EntityResolutionResult,
    EntityType,
)
from src.conversation.entity import AuthoritativeEntityResolver  # noqa: E402


class _RecordingModel:
    """记录模型调用次数，确保确定性路径不会产生费用。"""

    def __init__(self, *decisions: EntityModelResolution) -> None:
        self._decisions = list(decisions)
        self.calls = 0

    async def resolve(self, request: EntityModelRequest) -> EntityModelResolution:
        """返回下一条严格候选，不保存请求正文。"""
        del request
        self.calls += 1
        return self._decisions.pop(0)


class _RecordingCatalog:
    """以固定映射模拟权威证券目录。"""

    def __init__(self, *entities: Entity) -> None:
        self._entities = {entity.symbol: entity for entity in entities}
        self.lookups: list[str] = []

    async def lookup(self, symbol: str) -> Entity | None:
        """按 canonical symbol 返回目录实体。"""
        self.lookups.append(symbol)
        return self._entities.get(symbol)


def _run(resolver: AuthoritativeEntityResolver, text: str) -> EntityResolutionResult:
    """执行异步 Resolver，并让同步回退实现明确违反测试合同。"""
    pending = resolver.resolve(ContextPacket(current_message=text))
    assert inspect.isawaitable(pending), "D09 Resolver 必须是非阻塞 async 接口"
    return asyncio.run(pending)


@pytest.mark.unit
def test_resolver_exposes_one_async_contract() -> None:
    """I/O 兜底接入后不得继续保留同步 Resolver 双轨。"""
    result = _run(AuthoritativeEntityResolver(), "贵州茅台今天怎么样")

    assert result.entity is not None
    assert result.entity.symbol == "600519.SH"


@pytest.mark.unit
def test_deterministic_exact_match_never_calls_model() -> None:
    """本地精确名称命中必须在模型之前完成。"""
    model = _RecordingModel()
    result = _run(AuthoritativeEntityResolver(model=model), "帮我分析贵州茅台")

    assert result.entity is not None and result.entity.symbol == "600519.SH"
    assert result.resolver_path.value == "exact_name"
    assert result.model_calls == 0
    assert model.calls == 0


@pytest.mark.unit
def test_deterministic_fuzzy_match_handles_typo_without_model() -> None:
    """高置信中文 typo 应由有阈值和差距的确定性模糊匹配收敛。"""
    model = _RecordingModel()
    result = _run(AuthoritativeEntityResolver(model=model), "贵州矛台最近怎么样")

    assert result.entity is not None and result.entity.symbol == "600519.SH"
    assert result.resolver_path.value == "fuzzy"
    assert result.model_calls == 0
    assert model.calls == 0


@pytest.mark.unit
def test_long_tail_model_candidate_requires_catalog_grounding() -> None:
    """长尾模型候选只有被目录确认后才能成为 canonical entity。"""
    entity = Entity("601012.SH", "隆基绿能", EntityType.STOCK)
    model = _RecordingModel(EntityModelResolution((entity,), 0.95, 1, 0))
    catalog = _RecordingCatalog(entity)

    result = _run(
        AuthoritativeEntityResolver(model=model, catalog=catalog),
        "帮我分析一下隆基绿能最近的基本面",
    )

    assert result.entity == entity
    assert result.resolver_path.value == "model_fallback"
    assert result.catalog_status.value == "verified"
    assert result.model_calls == 1
    assert result.repair_count == 0
    assert catalog.lookups == ["601012.SH"]


@pytest.mark.unit
def test_hallucinated_model_code_is_rejected_without_semantic_retry() -> None:
    """目录不存在的模型代码不得被采用，也不得用第二次模型调用修补语义。"""
    hallucination = Entity("999999.SH", "虚构股份", EntityType.STOCK)
    model = _RecordingModel(EntityModelResolution((hallucination,), 0.95, 1, 0))
    result = _run(
        AuthoritativeEntityResolver(model=model, catalog=_RecordingCatalog()),
        "分析一下虚构股份",
    )

    assert result.entity is None
    assert result.error_code is not None and result.error_code.value == "ENTITY_NOT_FOUND"
    assert result.resolver_path.value == "model_fallback"
    assert result.model_calls == 1
    assert model.calls == 1


@pytest.mark.unit
def test_explicit_invalid_code_is_not_repaired_by_model() -> None:
    """显式无效证券代码必须目录拒绝，不能调用模型猜测另一个代码。"""
    model = _RecordingModel()
    result = _run(
        AuthoritativeEntityResolver(model=model, catalog=_RecordingCatalog()),
        "查询 999999.SH 的行情",
    )

    assert result.entity is None
    assert result.error_code is not None and result.error_code.value == "ENTITY_NOT_FOUND"
    assert result.resolver_path.value == "explicit_code"
    assert model.calls == 0


@pytest.mark.unit
def test_conflicting_explicit_name_and_code_require_clarification() -> None:
    """名称与代码分别指向不同实体时不得按文本顺序任选其一。"""
    result = _run(AuthoritativeEntityResolver(), "贵州茅台 002594.SZ 最近怎么样")

    assert result.entity is None
    assert result.error_code is not None and result.error_code.value == "ENTITY_CONFLICT"
    assert result.clarification
    assert result.model_calls == 0


@pytest.mark.unit
def test_multiple_grounded_model_candidates_remain_ambiguous() -> None:
    """模型提出多个均有效候选时必须澄清，不能按置信度强选。"""
    power = Entity("600011.SH", "华能国际", EntityType.STOCK)
    hydro = Entity("600025.SH", "华能水电", EntityType.STOCK)
    model = _RecordingModel(EntityModelResolution((power, hydro), 0.70, 1, 0))
    result = _run(
        AuthoritativeEntityResolver(model=model, catalog=_RecordingCatalog(power, hydro)),
        "分析一下华能这家公司",
    )

    assert result.entity is None
    assert result.error_code is not None and result.error_code.value == "AMBIGUOUS_ENTITY"
    assert [item.symbol for item in result.candidates] == ["600011.SH", "600025.SH"]
    assert result.clarification
