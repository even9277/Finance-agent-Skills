from backend.config import settings


_STM_FALLBACK_MIN_UNCOMPRESSED_MESSAGES = int(
    settings.stm_fallback_min_uncompressed_messages
)
_CHAT_STREAM_CHUNK_SIZE = 48
_STM_OVERFLOW_ERROR_PATTERNS = (
    "context length",
    "context window",
    "maximum context",
    "max context",
    "too many tokens",
    "token limit",
    "prompt is too long",
    "context too long",
)
_ROUTE_SNAPSHOT_ASSISTANT_TRUNCATE = 500


_RISK_LEVEL_ALLOWED = {
    "conservative",
    "moderate",
    "balanced_conservative",
    "balanced",
    "aggressive",
    "speculative",
    "very_aggressive",
}

_HORIZON_ALLOWED = {"ultra_short", "short", "swing", "long"}
_RESPONSE_PREF_ALLOWED = {"concise", "balanced", "detailed", "risk_first"}


_SECTOR_CANONICAL = [
    "科技/半导体", "消费/白酒", "金融/银行", "医疗/医药",
    "能源/煤炭", "新能源/电动车", "红利/央国企", "黄金/贵金属",
    "AI/大模型", "房地产", "军工", "农业",
]

_SECTOR_SYNONYMS: dict[str, str] = {
    # 常见简称 → 规范名
    "半导体": "科技/半导体",
    "芯片": "科技/半导体",
    "科技": "科技/半导体",
    "黄金": "黄金/贵金属",
    "贵金属": "黄金/贵金属",
    "红利": "红利/央国企",
    "高股息": "红利/央国企",
    "央国企": "红利/央国企",
    "大模型": "AI/大模型",
    "AI": "AI/大模型",
    "人工智能": "AI/大模型",
    "新能源": "新能源/电动车",
    "电动车": "新能源/电动车",
    "白酒": "消费/白酒",
    "消费": "消费/白酒",
    "银行": "金融/银行",
    "金融": "金融/银行",
    "医药": "医疗/医药",
    "医疗": "医疗/医药",
}

_RISK_LEVEL_SYNONYMS: dict[str, str] = {
    # 中文/常见别名 → 枚举
    "保守": "conservative",
    "稳健": "balanced_conservative",
    "偏稳健": "balanced_conservative",
    "中性": "balanced",
    "平衡": "balanced",
    "进取": "aggressive",
    "激进": "very_aggressive",
    "超激进": "very_aggressive",
    # 兼容历史枚举
    "moderate": "balanced_conservative",
    "speculative": "very_aggressive",
}

_HORIZON_SYNONYMS: dict[str, str] = {
    "超短": "ultra_short",
    "超短线": "ultra_short",
    "短线": "short",
    "短期": "short",
    "波段": "swing",
    "中期": "swing",
    "中长线": "long",
    "长线": "long",
    "长期": "long",
}

_RESPONSE_PREF_SYNONYMS: dict[str, str] = {
    "简洁": "concise",
    "精简": "concise",
    "均衡": "balanced",
    "详细": "detailed",
    "先讲风险": "risk_first",
    "风险优先": "risk_first",
    "先风险后机会": "risk_first",
}


def _normalize_sectors(value) -> list[str] | None:
    if value is None:
        return None

    raw_list: list[str] = []
    if isinstance(value, str):
        # 允许模型输出 "半导体, 黄金" 或 "半导体、黄金" 这种形式
        separators = [",", "，", "、", ";", "；", "|", "\n"]
        tmp = value
        for sep in separators:
            tmp = tmp.replace(sep, ",")
        raw_list = [x.strip() for x in tmp.split(",") if x.strip()]
    elif isinstance(value, list):
        raw_list = [str(x).strip() for x in value if str(x).strip()]
    else:
        return None

    normalized: list[str] = []
    for item in raw_list:
        # 若直接是规范名则保留
        if item in _SECTOR_CANONICAL:
            norm = item
        else:
            norm = _SECTOR_SYNONYMS.get(item, item)
            # 进一步：有些模型会输出 "科技/半导体/芯片" 这种，取前两段
            if isinstance(norm, str) and norm.count("/") >= 2:
                parts = [p for p in norm.split("/") if p]
                norm = "/".join(parts[:2])

        if norm and norm not in normalized:
            normalized.append(norm)

    # 限制长度，避免异常污染
    return normalized[:20]


def _normalize_profile_action(field: str, value):
    """
    规范化 action 值：
    - risk_level / investment_horizon / response_pref：必须映射到允许枚举，否则拒绝写入
    - sectors：做去重/清洗/同义归一，返回 list[str]
    返回：(field, normalized_value) 或 None（表示无效/不写入）
    """
    if not field:
        return None
    field = str(field).strip()

    if field == "risk_level":
        if value is None:
            return None
        v = str(value).strip()
        v = _RISK_LEVEL_SYNONYMS.get(v, v)
        if v not in _RISK_LEVEL_ALLOWED:
            return None
        return field, v

    if field == "investment_horizon":
        if value is None:
            return None
        v = str(value).strip()
        v = _HORIZON_SYNONYMS.get(v, v)
        if v not in _HORIZON_ALLOWED:
            return None
        return field, v

    if field == "response_pref":
        if value is None:
            return None
        v = str(value).strip()
        v = _RESPONSE_PREF_SYNONYMS.get(v, v)
        if v not in _RESPONSE_PREF_ALLOWED:
            return None
        return field, v

    if field == "sectors":
        sectors = _normalize_sectors(value)
        if sectors is None:
            return None
        return field, sectors

    return None


class InvalidSopSkillError(ValueError):
    """Raised when the user explicitly selects an unknown SOP skill."""


def _chunk_text(text: str, chunk_size: int = _CHAT_STREAM_CHUNK_SIZE) -> list[str]:
    if not text:
        return []
    return [text[i:i + chunk_size] for i in range(0, len(text), chunk_size)]


def _context_window_to_payload(context_window) -> dict:
    if context_window is None:
        return {}
    if hasattr(context_window, "model_dump"):
        return context_window.model_dump(mode="json")
    if hasattr(context_window, "dict"):
        return context_window.dict()
    return dict(context_window)


def _unique_strings(values: list[object], *, limit: int = 6) -> list[str]:
    items: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in items:
            continue
        items.append(text)
        if len(items) >= limit:
            break
    return items


def _is_context_overflow_error(exc: Exception) -> bool:
    message = str(exc or "").lower()
    return any(pattern in message for pattern in _STM_OVERFLOW_ERROR_PATTERNS)
