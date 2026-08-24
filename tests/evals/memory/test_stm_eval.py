"""执行版本化、完全离线的 STM 字段与预算回归集。"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
AGENT_ROOT = PROJECT_ROOT / "Financial-MCP-Agent"
for path in (PROJECT_ROOT, AGENT_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from backend.application.memory.context import (  # noqa: E402
    ContextBudgetPolicy,
    ContextTextItem,
)
from src.memory.contracts import (  # noqa: E402
    StateOperation,
    WorkingEntity,
    WorkingState,
    WorkingStateUpdate,
)
from src.memory.working_state import reduce_working_state  # noqa: E402

DATA_PATH = Path(__file__).resolve().parent / "data" / "stm_v1.jsonl"


def _load_cases() -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in DATA_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


@pytest.mark.eval_smoke
@pytest.mark.parametrize("case", _load_cases(), ids=lambda item: item["case_id"])
def test_stm_offline_regression(case: dict[str, Any]) -> None:
    """按固定样例检查状态版本和上下文裁剪，不调用任何 Provider。"""
    if case["kind"] == "context":
        messages = tuple(
            ContextTextItem(
                message_id=message_id,
                text=f"user: 第 {message_id} 条历史消息" * 4,
            )
            for message_id in case["message_ids"]
        )
        packed = ContextBudgetPolicy(120, 30, 10, 10).pack(
            current_message=case["current_message"],
            recent_messages=messages,
            running_summary="更早摘要" * 8,
        )
        assert packed.recent_messages[-1].message_id == case["gold"]["newest_message_id"]
        assert packed.dropped_message_count >= case["gold"]["dropped_min"]
        assert packed.used_tokens <= packed.input_budget_tokens
        return

    current_payload = case["current"]
    update_payload = case["update"]
    current = WorkingState(
        active_entity=_entity(current_payload.get("active_entity")),
        constraints=tuple(current_payload.get("constraints", ())),
        reply_preference_hint=current_payload.get("reply_preference_hint", ""),
        state_version=current_payload["state_version"],
    )
    update = WorkingStateUpdate(
        active_entity=_entity(update_payload.get("active_entity")),
        active_entity_operation=StateOperation(
            update_payload.get("active_entity_operation", "noop")
        ),
        constraints=tuple(update_payload.get("constraints", ())),
        constraints_operation=StateOperation(
            update_payload.get("constraints_operation", "noop")
        ),
        reply_preference_operation=StateOperation(
            update_payload.get("reply_preference_operation", "noop")
        ),
    )
    transition = reduce_working_state(
        current,
        update,
        session_id="eval-session",
        source_message_id=10,
        trace_id="tr_eval",
    )
    gold = case["gold"]
    assert transition.state.state_version == gold["state_version"]
    assert len(transition.events) == gold["event_count"]
    if "active_entity" in gold:
        assert transition.state.active_entity is not None
        assert transition.state.active_entity.symbol == gold["active_entity"]
    if "constraints" in gold:
        assert list(transition.state.constraints) == gold["constraints"]
    if "reply_preference_hint" in gold:
        assert transition.state.reply_preference_hint == gold["reply_preference_hint"]


def _entity(payload: dict[str, str] | None) -> WorkingEntity | None:
    if payload is None:
        return None
    return WorkingEntity(**payload)
