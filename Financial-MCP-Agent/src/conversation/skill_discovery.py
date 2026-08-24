"""基于冻结 Skill 元数据执行确定性、可审计的 SOP Discovery。"""

from __future__ import annotations

import re

from .contracts import (
    Entity,
    EntityType,
    RouteStage1Outcome,
    SkillCatalogSnapshot,
    SkillMatch,
)

_COMPARE_HINTS = ("对比", "比较", "PK", "VS", "哪个好", "哪个适合", "二选一")
_SCREEN_HINTS = ("筛选", "筛", "推荐", "候选", "配置", "选几个", "找几只", "shortlist")
_MOVE_HINTS = ("为什么涨", "为什么跌", "为什么突然", "异动", "拉升", "跳水", "大涨", "大跌")
_HOTSPOT_HINTS = ("热点", "热度", "强势", "弱势", "龙头", "轮动", "还能追", "继续看")
_FIRST_PASS_HINTS = ("能买吗", "还能买吗", "值不值得", "财报怎么看", "核心风险", "继续跟踪")
_GENERIC_ANALYSIS_HINTS = ("分析一下", "怎么看", "研判一下")
_FUND_TOKEN = re.compile(r"(ETF|基金|LOF|QDII)", re.IGNORECASE)
_STOCK_CODE = re.compile(r"(?<!\d)\d{6}(?:\.(?:SH|SZ))?(?!\d)", re.IGNORECASE)


class SkillDiscovery:
    """只使用 routing view 识别五类已登记 SOP，不读取 Skill 正文。"""

    def __init__(self, snapshot: SkillCatalogSnapshot) -> None:
        self._routing_view = snapshot.routing_view()
        self._available = {item.name for item in self._routing_view}

    def discover(self, query: str, *, entities: tuple[Entity, ...]) -> SkillMatch:
        """按互斥优先级返回高置信、低置信或未命中。

        Args:
            query: 当前轮有效问题。
            entities: 实体阶段已经确认的实体，不允许本模块修改。

        Returns:
            Skill 名、置信度、候选和稳定原因；未登记 Skill 永远不会被返回。
        """
        text = (query or "").strip()
        rules = (
            ("fund-compare", self._is_fund_compare(text), "multiple fund subjects with compare intent"),
            ("market-move-explain", self._is_market_move(text), "market object with move intent"),
            ("etf-screen", self._is_etf_screen(text), "fund universe with screening intent"),
            ("sector-hotspot-brief", self._is_sector_hotspot(text), "sector with hotspot intent"),
            ("stock-first-pass", self._is_stock_first_pass(text, entities), "stock first-pass intent"),
        )
        for skill_name, matched, reason in rules:
            if matched and skill_name in self._available:
                return SkillMatch(
                    skill_name=skill_name,
                    confidence=0.92 if skill_name != "stock-first-pass" else 0.9,
                    outcome=RouteStage1Outcome.HIT_HIGH,
                    shortlist=(skill_name,),
                    reason=reason,
                )

        has_stock = any(item.entity_type is EntityType.STOCK for item in entities) or bool(
            _STOCK_CODE.search(text)
        )
        if (
            "stock-first-pass" in self._available
            and has_stock
            and any(token in text for token in _GENERIC_ANALYSIS_HINTS)
        ):
            return SkillMatch(
                skill_name="stock-first-pass",
                confidence=0.72,
                outcome=RouteStage1Outcome.HIT_LOW,
                shortlist=("stock-first-pass",),
                reason="generic stock analysis requires confirmation",
            )

        return SkillMatch(
            skill_name=None,
            confidence=0.0,
            outcome=RouteStage1Outcome.MISS,
            shortlist=tuple(item.name for item in self._routing_view[:5]),
            reason="no stable SOP metadata rule matched",
        )

    @staticmethod
    def _is_fund_compare(text: str) -> bool:
        return len(_FUND_TOKEN.findall(text)) >= 2 and any(token in text for token in _COMPARE_HINTS)

    @staticmethod
    def _is_etf_screen(text: str) -> bool:
        if SkillDiscovery._is_fund_compare(text):
            return False
        return bool(_FUND_TOKEN.search(text)) and any(token in text for token in _SCREEN_HINTS)

    @staticmethod
    def _is_market_move(text: str) -> bool:
        has_object = any(
            token in text
            for token in ("股票", "个股", "ETF", "指数", "板块", "行业", "茅台", "宁德时代")
        ) or bool(_STOCK_CODE.search(text))
        return has_object and any(token in text for token in _MOVE_HINTS)

    @staticmethod
    def _is_sector_hotspot(text: str) -> bool:
        return any(token in text for token in ("板块", "行业", "概念", "主题")) and any(
            token in text for token in _HOTSPOT_HINTS
        )

    @staticmethod
    def _is_stock_first_pass(text: str, entities: tuple[Entity, ...]) -> bool:
        if _FUND_TOKEN.search(text) or any(token in text for token in ("板块", "行业", "概念")):
            return False
        has_stock = any(item.entity_type is EntityType.STOCK for item in entities) or any(
            token in text for token in ("股票", "个股", "茅台", "比亚迪", "宁德时代")
        ) or bool(_STOCK_CODE.search(text))
        return has_stock and any(token in text for token in _FIRST_PASS_HINTS)
