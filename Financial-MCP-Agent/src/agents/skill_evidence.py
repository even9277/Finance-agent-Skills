from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ToolEvidence:
    tool_name: str
    ok: bool
    symbol: str = ""
    error: str | None = None
    payload: Any = None


@dataclass(slots=True)
class EvidenceValidationResult:
    used_tools: bool
    evidence_ok: bool
    successful_tools: list[str] = field(default_factory=list)
    evidences: list[ToolEvidence] = field(default_factory=list)


_MARKET_TOOLS = {"get_market_bars", "get_daily_bars", "get_index_bars"}
_FUNDAMENTAL_TOOLS = {"get_fina_indicator", "get_income", "get_balance_sheet", "get_cashflow"}
_SECTOR_TOOLS = {"get_sector_snapshot", "get_sector_constituents", "get_index_bars"}
_FUND_CANDIDATE_TOOLS = {"get_fund_basic_info", "get_etf_basic_info"}
_FUND_SUPPORT_TOOLS = {"get_fund_nav", "get_fund_share", "get_fund_market_bars"}
_SELECTION_CANDIDATE_TOOLS = {"get_stock_basic_info", "get_sector_snapshot", "get_sector_constituents"} | _FUND_CANDIDATE_TOOLS
_SELECTION_SUPPORT_TOOLS = _MARKET_TOOLS | _FUNDAMENTAL_TOOLS | _FUND_SUPPORT_TOOLS


def _normalize_symbol(symbol: str | None) -> str:
    raw = str(symbol or "").strip()
    if not raw:
        return ""
    upper = raw.upper()
    if "." in upper and upper.endswith((".SH", ".SZ", ".BJ")) and len(upper.split(".", 1)[0]) == 6:
        return upper
    lower = raw.lower()
    if lower.startswith(("sh.", "sz.", "bj.")):
        exchange, code = lower.split(".", 1)
        return f"{code}.{exchange.upper()}"
    digits = "".join(ch for ch in raw if ch.isdigit())
    if len(digits) == 6:
        if digits.startswith("6"):
            return f"{digits}.SH"
        if digits.startswith(("0", "3")):
            return f"{digits}.SZ"
        if digits.startswith(("4", "8")):
            return f"{digits}.BJ"
    return upper


def _parse_content_to_dict(content: Any) -> dict[str, Any] | None:
    if isinstance(content, dict):
        return content
    if isinstance(content, list):
        text = "\n".join(str(item) for item in content)
    else:
        text = str(content or "").strip()
    if not text:
        return None

    normalized_text = re.sub(r"\bNaN\b", "null", text)
    normalized_text = re.sub(r"\bInfinity\b", "null", normalized_text)
    normalized_text = re.sub(r"\b-Infinity\b", "null", normalized_text)

    for candidate in (text, normalized_text):
        for parser in (json.loads, ast.literal_eval):
            try:
                data = parser(candidate)
                if isinstance(data, dict):
                    return data
            except Exception:
                continue
    return None


def extract_tool_evidences(response: Any) -> EvidenceValidationResult:
    if not isinstance(response, dict):
        return EvidenceValidationResult(used_tools=False, evidence_ok=False)
    messages = response.get("messages")
    if not isinstance(messages, list):
        return EvidenceValidationResult(used_tools=False, evidence_ok=False)

    evidences: list[ToolEvidence] = []
    for message in messages:
        message_type = getattr(message, "type", None)
        if message_type != "tool" and message.__class__.__name__ != "ToolMessage":
            continue
        tool_name = str(getattr(message, "name", None) or getattr(message, "tool_name", None) or "unknown")
        data = _parse_content_to_dict(getattr(message, "content", None))
        if not isinstance(data, dict):
            evidences.append(ToolEvidence(tool_name=tool_name, ok=False, error="unparseable tool output"))
            continue
        evidences.append(
            ToolEvidence(
                tool_name=tool_name,
                ok=bool(data.get("ok")),
                symbol=str(data.get("symbol") or ""),
                error=str(data.get("error") or "") or None,
                payload=data.get("payload"),
            )
        )

    successful_tools = [item.tool_name for item in evidences if item.ok and item.payload not in (None, [], {})]
    return EvidenceValidationResult(
        used_tools=bool(evidences),
        evidence_ok=bool(successful_tools),
        successful_tools=successful_tools,
        evidences=evidences,
    )


def validate_evidence(
    *,
    analysis_mode: str,
    resolved_symbol: str | None,
    response: Any,
) -> EvidenceValidationResult:
    base = extract_tool_evidences(response)
    if not base.used_tools or not base.evidence_ok:
        return base

    relevant = []
    normalized_symbol = _normalize_symbol(resolved_symbol)
    for item in base.evidences:
        if not item.ok or item.payload in (None, [], {}):
            continue
        item_symbol = _normalize_symbol(item.symbol)
        if normalized_symbol and item_symbol and item_symbol != normalized_symbol:
            continue
        relevant.append(item)

    if analysis_mode == "single_stock_fundamental":
        has_market = any(item.tool_name in _MARKET_TOOLS for item in relevant)
        has_fundamental = any(item.tool_name in _FUNDAMENTAL_TOOLS for item in relevant)
        evidence_ok = has_market and has_fundamental
    elif analysis_mode == "sector_market":
        evidence_ok = any(item.tool_name in _SECTOR_TOOLS for item in relevant)
    elif analysis_mode == "stock_selection":
        has_fund_candidate = any(item.tool_name in _FUND_CANDIDATE_TOOLS for item in relevant)
        has_fund_support = any(item.tool_name in _FUND_SUPPORT_TOOLS for item in relevant)
        if has_fund_candidate or has_fund_support:
            evidence_ok = has_fund_candidate and has_fund_support
        else:
            has_candidate = any(item.tool_name in _SELECTION_CANDIDATE_TOOLS for item in relevant)
            has_support = any(item.tool_name in _SELECTION_SUPPORT_TOOLS for item in relevant)
            evidence_ok = has_candidate and has_support
    else:
        evidence_ok = bool(relevant)

    successful_tools = [item.tool_name for item in relevant if item.ok]
    return EvidenceValidationResult(
        used_tools=base.used_tools,
        evidence_ok=evidence_ok,
        successful_tools=successful_tools,
        evidences=relevant,
    )
