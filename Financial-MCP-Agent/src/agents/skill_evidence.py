from __future__ import annotations

import ast
import json
import logging
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.tools.skill_trace import new_evidence_id

# FIX-4: reuse canonical symbol utility from stock_resolver
_BACKEND_DIR = str(Path(__file__).resolve().parent.parent.parent.parent / "backend")
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)
from services.stock_resolver import canonicalize_symbol  # noqa: E402

logger = logging.getLogger(__name__)


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
    # FIX-2: tiered evidence classification
    tier: str = ""                    # "full" | "partial" | "none"
    missing_dimensions: list[str] = field(default_factory=list)
    allowed_claim_level: str = ""     # "advisory" | "analytical" | "descriptive"
    reason_codes: list[str] = field(default_factory=list)


_MARKET_TOOLS = {"get_market_bars", "get_daily_bars", "get_index_bars"}
_FUNDAMENTAL_TOOLS = {"get_fina_indicator", "get_income", "get_balance_sheet", "get_cashflow"}
_SECTOR_TOOLS = {"get_sector_snapshot", "get_sector_constituents", "get_index_bars"}
_FUND_CANDIDATE_TOOLS = {"get_fund_basic_info"}
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
    "get_fund_nav": "fund_nav",
    "get_fund_market_bars": "fund_daily",
    "get_fund_share": "fund_share",
    "search_web_news": "web_news",
}


def _normalize_symbol(symbol: str | None) -> str:
    """Delegate to the single canonical implementation in stock_resolver."""
    return canonicalize_symbol(symbol)


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


def _compute_evidence_tier(
    *,
    evidence_ok: bool,
    relevant: list[ToolEvidence],
    reasons: list[str],
    analysis_mode: str,
) -> tuple[str, list[str], str, list[str]]:
    """Derive (tier, missing_dimensions, allowed_claim_level, reason_codes).

    tier:
      - "full"    – all required evidence present
      - "partial" – some evidence available, some missing
      - "none"    – no usable evidence at all

    allowed_claim_level:
      - "advisory"    – full evidence → investment suggestions OK
      - "analytical"  – partial evidence → factual analysis only
      - "descriptive" – no evidence → description / refusal only
    """
    if not relevant:
        return "none", ["no_evidence"], "descriptive", list(reasons)

    if evidence_ok:
        return "full", [], "advisory", []

    missing_dims: list[str] = []
    reason_codes: list[str] = list(reasons)
    evidence_types = {item.evidence_type for item in relevant}
    tool_names = {item.tool_name for item in relevant}

    if analysis_mode in ("single_stock_fundamental", "single_stock_data"):
        if not (tool_names & _MARKET_TOOLS):
            missing_dims.append("market_missing")
        if not (tool_names & _FUNDAMENTAL_TOOLS):
            missing_dims.append("fundamental_missing")
    elif analysis_mode == "sector_market":
        if not (tool_names & _SECTOR_TOOLS):
            missing_dims.append("sector_missing")
    elif analysis_mode == "stock_selection":
        if not (tool_names & _SELECTION_CANDIDATE_TOOLS):
            missing_dims.append("candidate_missing")

    return "partial", missing_dims, "analytical", reason_codes


def _skill_evidence_validation_enabled() -> bool:
    """Off by default: strict required_evidence / mode checks often misfire in prod."""
    return os.getenv("ENABLE_SKILL_EVIDENCE_VALIDATION", "").lower() in ("1", "true", "yes")


def validate_evidence(
    *,
    analysis_mode: str,
    resolved_symbol: str | None,
    response: Any,
    skill_spec: dict[str, Any] | None = None,
) -> EvidenceValidationResult:
    base = extract_tool_evidences(response)
    if not _skill_evidence_validation_enabled():
        if not base.used_tools:
            return base
        tools = list(base.successful_tools) or [e.tool_name for e in base.evidences]
        return EvidenceValidationResult(
            used_tools=True,
            evidence_ok=True,
            successful_tools=tools,
            evidences=list(base.evidences),
            missing_evidence_reasons=[],
            accepted_evidences=list(base.accepted_evidences),
            rejected_evidences=list(base.rejected_evidences),
            tier="full",
            missing_dimensions=[],
            allowed_claim_level="analytical",
            reason_codes=[],
        )
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

    # FIX-2: compute tier, missing_dimensions, allowed_claim_level
    tier, missing_dims, claim_level, reason_codes = _compute_evidence_tier(
        evidence_ok=evidence_ok,
        relevant=relevant,
        reasons=reasons,
        analysis_mode=analysis_mode,
    )

    return EvidenceValidationResult(
        used_tools=base.used_tools,
        evidence_ok=evidence_ok,
        successful_tools=successful_tools,
        evidences=relevant,
        missing_evidence_reasons=reasons,
        accepted_evidences=accepted,
        rejected_evidences=rejected,
        tier=tier,
        missing_dimensions=missing_dims,
        allowed_claim_level=claim_level,
        reason_codes=reason_codes,
    )
