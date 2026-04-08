from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass, field
from typing import Any

from src.tools.skill_trace import new_evidence_id


@dataclass(slots=True)
class ToolEvidence:
    evidence_id: str
    tool_name: str
    ok: bool
    evidence_type: str = ""
    tool_result_id: str | None = None
    symbol: str = ""
    error: str | None = None
    payload: Any = None
    source_api: str | None = None
    trade_date: str | None = None


@dataclass(slots=True)
class EvidenceValidationResult:
    used_tools: bool
    evidence_ok: bool
    successful_tools: list[str] = field(default_factory=list)
    evidences: list[ToolEvidence] = field(default_factory=list)
    missing_evidence_reasons: list[str] = field(default_factory=list)
    accepted_evidences: list[dict[str, Any]] = field(default_factory=list)
    rejected_evidences: list[dict[str, Any]] = field(default_factory=list)


_MARKET_TOOLS = {"get_market_bars", "get_daily_bars", "get_index_bars"}
_FUNDAMENTAL_TOOLS = {"get_fina_indicator", "get_income", "get_balance_sheet", "get_cashflow"}
_SECTOR_TOOLS = {"get_sector_snapshot", "get_sector_constituents", "get_index_bars"}
_FUND_CANDIDATE_TOOLS = {"get_fund_basic_info", "get_etf_basic_info"}
_FUND_SUPPORT_TOOLS = {"get_fund_nav", "get_fund_share", "get_fund_market_bars"}
_SELECTION_CANDIDATE_TOOLS = {"get_stock_basic_info", "get_sector_snapshot", "get_sector_constituents"} | _FUND_CANDIDATE_TOOLS
_SELECTION_SUPPORT_TOOLS = _MARKET_TOOLS | _FUNDAMENTAL_TOOLS | _FUND_SUPPORT_TOOLS
_TOOL_EVIDENCE_TYPES = {
    "get_stock_basic_info": "stock_basic",
    "get_daily_bars": "stock_daily",
    "get_market_bars": "stock_market",
    "get_index_bars": "index_daily",
    "get_fina_indicator": "financial_indicator",
    "get_income": "income_statement",
    "get_balance_sheet": "balance_sheet",
    "get_cashflow": "cashflow_statement",
    "get_sector_snapshot": "sector_snapshot",
    "get_sector_constituents": "sector_constituents",
    "get_fund_basic_info": "fund_basic",
    "get_etf_basic_info": "fund_basic",
    "get_fund_nav": "fund_nav",
    "get_fund_market_bars": "fund_daily",
    "get_fund_share": "fund_share",
}


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


def _evidence_ref(item: ToolEvidence, *, reason: str | None = None) -> dict[str, Any]:
    payload = {
        "evidence_id": item.evidence_id,
        "tool_result_id": item.tool_result_id,
        "tool_name": item.tool_name,
        "evidence_type": item.evidence_type or _TOOL_EVIDENCE_TYPES.get(item.tool_name, "unknown"),
        "symbol": item.symbol,
        "source_api": item.source_api,
        "trade_date": item.trade_date,
    }
    if reason:
        payload["reason"] = reason
    if item.error:
        payload["error"] = item.error
    return payload


def extract_tool_evidences(response: Any) -> EvidenceValidationResult:
    if not isinstance(response, dict):
        return EvidenceValidationResult(used_tools=False, evidence_ok=False)
    messages = response.get("messages")
    if not isinstance(messages, list):
        return EvidenceValidationResult(used_tools=False, evidence_ok=False)

    evidences: list[ToolEvidence] = []
    rejected: list[dict[str, Any]] = []
    for message in messages:
        message_type = getattr(message, "type", None)
        if message_type != "tool" and message.__class__.__name__ != "ToolMessage":
            continue
        tool_name = str(getattr(message, "name", None) or getattr(message, "tool_name", None) or "unknown")
        data = _parse_content_to_dict(getattr(message, "content", None))
        if not isinstance(data, dict):
            item = ToolEvidence(evidence_id=new_evidence_id(), tool_name=tool_name, ok=False, error="unparseable tool output")
            evidences.append(item)
            rejected.append(_evidence_ref(item, reason="unparseable_tool_output"))
            continue
        item = ToolEvidence(
            evidence_id=str(data.get("evidence_id") or "") or new_evidence_id(),
            tool_name=tool_name,
            ok=bool(data.get("ok")),
            evidence_type=str(data.get("evidence_type") or _TOOL_EVIDENCE_TYPES.get(tool_name, "unknown")),
            tool_result_id=str(data.get("tool_result_id") or "") or None,
            symbol=str(data.get("symbol") or ""),
            error=str(data.get("error") or "") or None,
            payload=data.get("payload"),
            source_api=str(data.get("source_api") or "") or None,
            trade_date=str(data.get("trade_date") or "") or None,
        )
        evidences.append(item)
        if not item.ok or item.payload in (None, [], {}):
            rejected.append(_evidence_ref(item, reason="empty_or_failed_payload"))

    successful_tools = [
        item.tool_name
        for item in evidences
        if item.ok and item.payload not in (None, [], {})
    ]
    return EvidenceValidationResult(
        used_tools=bool(evidences),
        evidence_ok=bool(successful_tools),
        successful_tools=successful_tools,
        evidences=evidences,
        accepted_evidences=[_evidence_ref(item) for item in evidences if item.ok and item.payload not in (None, [], {})],
        rejected_evidences=rejected,
    )


def _validate_legacy_analysis_mode(
    analysis_mode: str,
    evidences: list[ToolEvidence],
) -> tuple[bool, list[str]]:
    reasons: list[str] = []

    if analysis_mode == "single_stock_fundamental":
        has_market = any(item.tool_name in _MARKET_TOOLS for item in evidences)
        has_fundamental = any(item.tool_name in _FUNDAMENTAL_TOOLS for item in evidences)
        if not has_market:
            reasons.append("missing market evidence for single_stock_fundamental")
        if not has_fundamental:
            reasons.append("missing fundamental evidence for single_stock_fundamental")
        return has_market and has_fundamental, reasons

    if analysis_mode == "sector_market":
        ok = any(item.tool_name in _SECTOR_TOOLS for item in evidences)
        if not ok:
            reasons.append("missing sector evidence for sector_market")
        return ok, reasons

    if analysis_mode == "stock_selection":
        has_fund_candidate = any(item.tool_name in _FUND_CANDIDATE_TOOLS for item in evidences)
        has_fund_support = any(item.tool_name in _FUND_SUPPORT_TOOLS for item in evidences)
        if has_fund_candidate or has_fund_support:
            if not has_fund_candidate:
                reasons.append("missing fund candidate evidence for stock_selection")
            if not has_fund_support:
                reasons.append("missing fund support evidence for stock_selection")
            return has_fund_candidate and has_fund_support, reasons

        has_candidate = any(item.tool_name in _SELECTION_CANDIDATE_TOOLS for item in evidences)
        has_support = any(item.tool_name in _SELECTION_SUPPORT_TOOLS for item in evidences)
        if not has_candidate:
            reasons.append("missing candidate evidence for stock_selection")
        if not has_support:
            reasons.append("missing support evidence for stock_selection")
        return has_candidate and has_support, reasons

    ok = bool(evidences)
    if not ok:
        reasons.append("no relevant evidence")
    return ok, reasons


def _validate_skill_spec_evidence(
    required_evidence: dict[str, Any],
    evidences: list[ToolEvidence],
) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    evidence_types = {item.evidence_type for item in evidences}
    distinct_symbols = {_normalize_symbol(item.symbol) for item in evidences if _normalize_symbol(item.symbol)}

    min_distinct_symbols = int(required_evidence.get("min_distinct_symbols") or 0)
    if min_distinct_symbols and len(distinct_symbols) < min_distinct_symbols:
        reasons.append(
            f"need at least {min_distinct_symbols} distinct symbols, got {len(distinct_symbols)}"
        )

    for evidence_type in required_evidence.get("must_have_all") or []:
        if evidence_type not in evidence_types:
            reasons.append(f"missing required evidence type: {evidence_type}")

    per_symbol_any = [str(item) for item in required_evidence.get("per_symbol_must_have_any") or [] if str(item)]
    if per_symbol_any:
        for symbol in sorted(distinct_symbols):
            symbol_types = {
                item.evidence_type
                for item in evidences
                if _normalize_symbol(item.symbol) == symbol
            }
            if not any(item in symbol_types for item in per_symbol_any):
                reasons.append(
                    f"symbol {symbol} missing any of required evidence types: {', '.join(per_symbol_any)}"
                )

    for evidence_type in required_evidence.get("must_have_any") or []:
        if evidence_type in evidence_types:
            break
    else:
        must_have_any = [str(item) for item in required_evidence.get("must_have_any") or [] if str(item)]
        if must_have_any:
            reasons.append(f"missing any-of evidence types: {', '.join(must_have_any)}")

    return not reasons and bool(evidences), reasons


def validate_evidence(
    *,
    analysis_mode: str,
    resolved_symbol: str | None,
    response: Any,
    skill_spec: dict[str, Any] | None = None,
) -> EvidenceValidationResult:
    base = extract_tool_evidences(response)
    if not base.used_tools:
        if skill_spec:
            base.missing_evidence_reasons = ["no tool evidence collected"]
        return base

    relevant: list[ToolEvidence] = []
    rejected = list(base.rejected_evidences)
    normalized_symbol = _normalize_symbol(resolved_symbol)

    for item in base.evidences:
        if not item.ok or item.payload in (None, [], {}):
            continue
        item_symbol = _normalize_symbol(item.symbol)
        if normalized_symbol and item_symbol and item_symbol != normalized_symbol:
            rejected.append(_evidence_ref(item, reason="symbol_mismatch"))
            continue
        relevant.append(item)

    if skill_spec and isinstance(skill_spec.get("required_evidence"), dict):
        evidence_ok, reasons = _validate_skill_spec_evidence(
            skill_spec.get("required_evidence") or {},
            relevant,
        )
    else:
        evidence_ok, reasons = _validate_legacy_analysis_mode(analysis_mode, relevant)

    successful_tools = [item.tool_name for item in relevant]
    accepted = [_evidence_ref(item) for item in relevant]
    return EvidenceValidationResult(
        used_tools=base.used_tools,
        evidence_ok=evidence_ok,
        successful_tools=successful_tools,
        evidences=relevant,
        missing_evidence_reasons=reasons,
        accepted_evidences=accepted,
        rejected_evidences=rejected,
    )
