"""定义进程内 Skill 发布使用的有限生命周期状态机。"""

from __future__ import annotations

from enum import StrEnum


class SkillStatus(StrEnum):
    """表示从草稿验证到激活、弃用或回滚的稳定状态。"""

    DRAFT = "draft"
    DISABLED = "disabled"
    SHADOW = "shadow"
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    ROLLED_BACK = "rolled_back"


class SkillLifecycleError(ValueError):
    """表示未知状态或被治理规则禁止的状态转换。"""


_TRANSITIONS: dict[SkillStatus, frozenset[SkillStatus]] = {
    SkillStatus.DRAFT: frozenset({SkillStatus.SHADOW, SkillStatus.DISABLED}),
    SkillStatus.DISABLED: frozenset({SkillStatus.DRAFT, SkillStatus.SHADOW}),
    SkillStatus.SHADOW: frozenset(
        {SkillStatus.ACTIVE, SkillStatus.DISABLED, SkillStatus.ROLLED_BACK}
    ),
    SkillStatus.ACTIVE: frozenset(
        {SkillStatus.SHADOW, SkillStatus.DEPRECATED, SkillStatus.ROLLED_BACK}
    ),
    SkillStatus.DEPRECATED: frozenset({SkillStatus.ROLLED_BACK}),
    SkillStatus.ROLLED_BACK: frozenset({SkillStatus.SHADOW, SkillStatus.DISABLED}),
}


def normalize_status(value: str | SkillStatus) -> SkillStatus:
    """把外部状态值收敛为稳定枚举。

    Args:
        value: 已知枚举或字符串状态。

    Returns:
        规范化后的 `SkillStatus`。

    Raises:
        SkillLifecycleError: 输入不是已登记状态。
    """
    if isinstance(value, SkillStatus):
        return value
    try:
        return SkillStatus(str(value or "").strip())
    except ValueError as exc:
        raise SkillLifecycleError(f"unknown skill status: {value}") from exc


def can_transition(current: str | SkillStatus, target: str | SkillStatus) -> bool:
    """判断生命周期转换是否属于治理白名单。"""
    current_status = normalize_status(current)
    target_status = normalize_status(target)
    return target_status in _TRANSITIONS[current_status]


def transition(current: str | SkillStatus, target: str | SkillStatus) -> SkillStatus:
    """执行一次受控状态转换并返回目标状态。

    Raises:
        SkillLifecycleError: 转换不在治理白名单中。
    """
    current_status = normalize_status(current)
    target_status = normalize_status(target)
    if not can_transition(current_status, target_status):
        raise SkillLifecycleError(
            f"illegal skill status transition: {current_status.value}->{target_status.value}"
        )
    return target_status


__all__ = ["SkillLifecycleError", "SkillStatus", "can_transition", "normalize_status", "transition"]
