"""从当前轮窄抽取可验证的市场、分析和时间约束。"""

from __future__ import annotations

import re

from .contracts import ConstraintOperation, ConstraintSet

_MARKET_PATTERN = re.compile(r"(?:只看|仅看)\s*(A\s*股|港\s*股|美\s*股)", re.IGNORECASE)


class ConstraintExtractor:
    """仅识别有限白名单约束，不从历史摘要推断新限制。"""

    def extract(self, text: str) -> ConstraintSet:
        """抽取本轮显式约束。

        Args:
            text: 当前用户问题。

        Returns:
            去重且保持规则顺序的约束集合和更新语义。
        """
        if re.search(r"(取消|清除|不要).{0,6}(之前|当前)?.{0,4}(约束|限制)", text or ""):
            return ConstraintSet(
                operation=ConstraintOperation.CLEAR,
                confidence=0.9,
            )
        items: list[str] = []
        market = _MARKET_PATTERN.search(text or "")
        if market:
            normalized_market = re.sub(r"\s+", "", market.group(1)).upper()
            items.append(f"只看{normalized_market}口径")
        if re.search(r"(?:不要|别|不)\s*(?:展开)?\s*(?:技术面|技术分析)", text or ""):
            items.append("不展开技术面分析")
        if re.search(r"(?:不要|别)\s*(?:给)?\s*(?:买卖点|荐股|直接推荐)", text or ""):
            items.append("不提供直接买卖建议")
        return ConstraintSet(
            items=tuple(dict.fromkeys(items)),
            operation=ConstraintOperation.MERGE if items else ConstraintOperation.NO_UPDATE,
            confidence=0.88 if items else 0.0,
        )
