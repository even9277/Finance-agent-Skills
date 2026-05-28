from __future__ import annotations

from enum import StrEnum


class SkillStatus(StrEnum):
    DRAFT = "draft"
    DISABLED = "disabled"
    SHADOW = "shadow"
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    ROLLED_BACK = "rolled_back"


class SkillLifecycleError(ValueError):
    pass


_TRANSITIONS: dict[SkillStatus, set[SkillStatus]] = {
    SkillStatus.DRAFT: {SkillStatus.SHADOW, SkillStatus.DISABLED},
    SkillStatus.DISABLED: {SkillStatus.DRAFT, SkillStatus.SHADOW},
    SkillStatus.SHADOW: {SkillStatus.ACTIVE, SkillStatus.DISABLED, SkillStatus.ROLLED_BACK},
    SkillStatus.ACTIVE: {SkillStatus.SHADOW, SkillStatus.DEPRECATED, SkillStatus.ROLLED_BACK},
    SkillStatus.DEPRECATED: {SkillStatus.ROLLED_BACK},
    SkillStatus.ROLLED_BACK: {SkillStatus.SHADOW, SkillStatus.DISABLED},
}


def normalize_status(value: str | SkillStatus) -> SkillStatus:
    if isinstance(value, SkillStatus):
        return value
    try:
        return SkillStatus(str(value or "").strip())
    except ValueError as exc:
        raise SkillLifecycleError(f"unknown skill status: {value}") from exc


def can_transition(current: str | SkillStatus, target: str | SkillStatus) -> bool:
    current_status = normalize_status(current)
    target_status = normalize_status(target)
    return target_status in _TRANSITIONS.get(current_status, set())


def transition(current: str | SkillStatus, target: str | SkillStatus) -> SkillStatus:
    current_status = normalize_status(current)
    target_status = normalize_status(target)
    if not can_transition(current_status, target_status):
        raise SkillLifecycleError(f"illegal skill status transition: {current_status.value}->{target_status.value}")
    return target_status


__all__ = ["SkillLifecycleError", "SkillStatus", "can_transition", "normalize_status", "transition"]
