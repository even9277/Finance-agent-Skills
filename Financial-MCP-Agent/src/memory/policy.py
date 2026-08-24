"""定义不依赖模型或 Provider 的记忆权威基础规则。"""

from __future__ import annotations

from .contracts import (
    ActivationSource,
    MemoryContractError,
    MemoryRecord,
    MemorySource,
    ProfileField,
)

HIGH_IMPACT_PROFILE_FIELDS = frozenset(
    {
        ProfileField.RISK_LEVEL,
        ProfileField.INVESTMENT_HORIZON,
        ProfileField.EXPECTED_RETURN_MIN,
        ProfileField.EXPECTED_RETURN_MAX,
        ProfileField.SECTORS,
        ProfileField.WATCHLIST,
        ProfileField.CONSTRAINTS,
    }
)


def requires_user_confirmation(field: ProfileField, source: MemorySource) -> bool:
    """判断画像候选是否必须取得用户确认。

    Args:
        field: 候选准备影响的结构化画像字段。
        source: 候选证据来源。

    Returns:
        模型推断高影响字段时返回 ``True``；显式用户来源返回 ``False``。
    """
    return source is MemorySource.MODEL_INFERRED and field in HIGH_IMPACT_PROFILE_FIELDS


def validate_record_authority(record: MemoryRecord) -> None:
    """拒绝把模型推断的高影响画像直接标记为自动生效。

    Args:
        record: 准备写入 PostgreSQL 权威表的领域记录。

    Raises:
        MemoryContractError: 记录绕过了冻结的用户确认边界。
    """
    if (
        record.profile_field is not None
        and requires_user_confirmation(record.profile_field, record.source)
        and record.activation_source is ActivationSource.POLICY_AUTO
    ):
        raise MemoryContractError(
            "model-inferred high-impact profile cannot be auto-activated"
        )
