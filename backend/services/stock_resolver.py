"""把共享 canonical 实体适配为报告 Agent 的股票输入格式。"""

from __future__ import annotations

from backend.infrastructure.chat.entity_resolution import get_entity_resolver
from src.conversation.contracts import ContextPacket, Entity, EntityType


class ReportEntityResolutionError(RuntimeError):
    """表示报告入口未能确认唯一且合法的 A 股实体。"""

    error_code = "REPORT_ENTITY_UNRESOLVED"

    def __init__(self, message: str, *, resolver_error_code: str | None = None) -> None:
        super().__init__(message)
        self.resolver_error_code = resolver_error_code


async def resolve_stock(query: str) -> tuple[str, str]:
    """通过唯一共享 Resolver 解析报告所需的单只 A 股。

    Args:
        query: 用户当前报告指令；只作为 `ContextPacket.current_message` 传入。

    Returns:
        公司简称和报告 Agent 兼容的 `sh.600519` / `sz.000001` 代码。

    Raises:
        ReportEntityResolutionError: 结果未确认、不是单只股票或代码格式异常。
    """
    result = await get_entity_resolver().resolve(ContextPacket(current_message=query))
    entities = result.resolved_entities or ((result.entity,) if result.entity is not None else ())
    if len(entities) != 1:
        resolver_code = result.error_code.value if result.error_code is not None else None
        raise ReportEntityResolutionError(
            "report requires one confirmed stock entity",
            resolver_error_code=resolver_code,
        )
    entity = entities[0]
    if entity.entity_type is not EntityType.STOCK:
        raise ReportEntityResolutionError("report entity is not a stock")
    return entity.name, _to_report_stock_code(entity)


def _to_report_stock_code(entity: Entity) -> str:
    """把领域 canonical 代码转换为旧报告工作流所需格式。"""
    parts = entity.symbol.upper().split(".")
    if (
        len(parts) != 2
        or len(parts[0]) != 6
        or not parts[0].isdigit()
        or parts[1] not in {"SH", "SZ"}
    ):
        raise ReportEntityResolutionError("report entity has an invalid stock symbol")
    return f"{parts[1].lower()}.{parts[0]}"
