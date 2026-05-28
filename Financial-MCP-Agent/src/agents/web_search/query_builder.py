from __future__ import annotations

import re

_FORBIDDEN_PATTERNS = (
    re.compile(r"api[_ -]?key|token|secret|password", re.I),
    re.compile(r"持仓|金额|成本价|身份证|手机号|邮箱"),
)
_NOISE = ("请", "帮我", "分析", "看看", "一下", "最近", "今天", "为什么")


def minimize_query(query: str, *, freshness_days: int = 7) -> tuple[str, list[str]]:
    """只保留公开实体和事件词，避免把用户隐私或整段上下文发给搜索服务。"""
    raw = re.sub(r"\s+", " ", str(query or "")).strip()
    warnings: list[str] = []
    for pattern in _FORBIDDEN_PATTERNS:
        if pattern.search(raw):
            warnings.append("forbidden_term_removed")
            raw = pattern.sub(" ", raw)
    for word in _NOISE:
        raw = raw.replace(word, " ")
    raw = re.sub(r"\s+", " ", raw).strip()
    if "公告" not in raw and "新闻" not in raw and "消息" not in raw:
        raw = f"{raw} 公告 新闻".strip()
    if freshness_days <= 3 and "今日" not in raw:
        raw = f"{raw} 今日"
    return raw[:120], warnings


def classify_search_trigger(query: str, *, requires_web_news: bool = False) -> str:
    if requires_web_news:
        return "required"
    text = str(query or "")
    if any(word in text for word in ("新闻", "公告", "消息", "催化", "为什么", "异动", "利好", "利空")):
        return "optional"
    return "skip"


__all__ = ["classify_search_trigger", "minimize_query"]
