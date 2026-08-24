"""提供 M2 单股切片的确定性实体解析基线。"""

from __future__ import annotations

import re

from .contracts import (
    ContextPacket,
    Entity,
    EntityResolutionResult,
    EntityType,
    ErrorCode,
)

_STOCK_CODE_PATTERN = re.compile(r"(?P<symbol>\d{6}\.(?:SH|SZ))", re.IGNORECASE)
_MOUTAI = Entity(symbol="600519.SH", name="贵州茅台", entity_type=EntityType.STOCK)
_PINGAN_CANDIDATES = (
    Entity(symbol="000001.SZ", name="平安银行", entity_type=EntityType.STOCK),
    Entity(symbol="601318.SH", name="中国平安", entity_type=EntityType.STOCK),
)


class DeterministicEntityResolver:
    """解析显式股票代码/名称，并对“平安”歧义保守澄清。"""

    def resolve(self, packet: ContextPacket) -> EntityResolutionResult:
        """解析当前问题的权威主实体。

        Args:
            packet: 当前轮优先的上下文包。

        Returns:
            单一实体、歧义候选或无需实体的概念问题结果。
        """
        message = packet.current_message
        match = _STOCK_CODE_PATTERN.search(message)
        if match:
            symbol = match.group("symbol").upper()
            if symbol == _MOUTAI.symbol:
                return EntityResolutionResult(
                    entity=_MOUTAI,
                    candidates=(_MOUTAI,),
                    inherited=False,
                    confidence=1.0,
                )
            entity = Entity(symbol=symbol, name=symbol, entity_type=EntityType.STOCK)
            return EntityResolutionResult(
                entity=entity,
                candidates=(entity,),
                inherited=False,
                confidence=0.98,
            )
        if "贵州茅台" in message or "茅台" in message:
            return EntityResolutionResult(
                entity=_MOUTAI,
                candidates=(_MOUTAI,),
                inherited=False,
                confidence=0.99,
            )
        if "平安" in message:
            return EntityResolutionResult(
                entity=None,
                candidates=_PINGAN_CANDIDATES,
                inherited=False,
                confidence=0.45,
                clarification="你指的是平安银行（000001.SZ）还是中国平安（601318.SH）？",
                error_code=ErrorCode.AMBIGUOUS_ENTITY,
            )
        if "ETF" in message.upper() and "LOF" in message.upper():
            return EntityResolutionResult(
                entity=None,
                candidates=(),
                inherited=False,
                confidence=1.0,
            )
        return EntityResolutionResult(
            entity=None,
            candidates=(),
            inherited=False,
            confidence=0.0,
            clarification="请提供明确的股票名称或代码后再查询。",
            error_code=ErrorCode.ENTITY_REQUIRED,
        )
