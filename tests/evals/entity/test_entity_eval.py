import asyncio
from pathlib import Path
import sys

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
AGENT_ROOT = PROJECT_ROOT / "Financial-MCP-Agent"
for import_root in (PROJECT_ROOT, AGENT_ROOT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from src.conversation.contracts import (  # noqa: E402
    ContextPacket,
    Entity,
    EntityModelRequest,
    EntityModelResolution,
    EntityType,
)
from src.conversation.entity import AuthoritativeEntityResolver  # noqa: E402
from tests.evals.runner import load_jsonl  # noqa: E402


@pytest.mark.eval_smoke
def test_entity_eval_executes_authoritative_resolver() -> None:
    """执行版本化实体样例并验证确定性、模型兜底、拒绝和继承结果。"""
    rows = load_jsonl(Path("tests/evals/entity/data/smoke.jsonl"))

    for row in rows:
        model = _EvalModel(tuple(_entity(item) for item in row.get("model_candidates", [])))
        catalog = _EvalCatalog(tuple(_entity(item) for item in row.get("catalog_entities", [])))
        resolver = AuthoritativeEntityResolver(model=model, catalog=catalog)
        turns = row["turns"]
        result = asyncio.run(
            resolver.resolve(
                ContextPacket(
                    current_message=str(turns[-1]["content"]),
                    recent_messages=tuple(str(turn["content"]) for turn in turns[:-1]),
                )
            )
        )
        gold = row["gold"]
        actual_status = (
            "ambiguous"
            if result.error_code is not None and result.error_code.value == "AMBIGUOUS_ENTITY"
            else "clarification"
            if result.clarification
            else "resolved_multi"
            if len(result.resolved_entities) > 1
            else "resolved"
            if result.entity is not None
            else "no_entity"
        )
        assert actual_status == gold["resolution_status"], row["case_id"]
        assert (result.entity.entity_type.value if result.entity else "none") == gold["entity_type"]
        assert (result.entity.symbol if result.entity else "") == gold["canonical_id"]
        assert result.inherited is bool(gold["inherited"])
        if "candidate_ids" in gold:
            assert [item.symbol for item in result.candidates] == gold["candidate_ids"]
        if "resolved_ids" in gold:
            assert [item.symbol for item in result.resolved_entities] == gold["resolved_ids"]
        if "resolver_path" in gold:
            assert result.resolver_path.value == gold["resolver_path"], row["case_id"]
        if "error_code" in gold:
            assert result.error_code is not None
            assert result.error_code.value == gold["error_code"], row["case_id"]
        assert result.model_calls <= 1, row["case_id"]
        assert model.calls == int(bool(row.get("model_candidates"))), row["case_id"]


def _entity(row: dict[str, object]) -> Entity:
    """把固定 eval 数据转换为领域实体。"""
    return Entity(
        symbol=str(row["symbol"]),
        name=str(row["name"]),
        entity_type=EntityType(str(row["entity_type"])),
    )


class _EvalModel:
    """为离线评测提供确定性的模型后置候选。"""

    def __init__(self, candidates: tuple[Entity, ...]) -> None:
        self._candidates = candidates
        self.calls = 0

    async def resolve(self, request: EntityModelRequest) -> EntityModelResolution:
        """返回固定候选并记录一次逻辑调用。"""
        del request
        self.calls += 1
        return EntityModelResolution(
            candidates=self._candidates,
            confidence=0.95,
            model_calls=1,
            repair_count=0,
        )


class _EvalCatalog:
    """为离线评测提供固定 canonical 目录。"""

    def __init__(self, entities: tuple[Entity, ...]) -> None:
        self._entities = {item.symbol: item for item in entities}

    async def lookup(self, symbol: str) -> Entity | None:
        """按代码返回目录实体。"""
        return self._entities.get(symbol)
