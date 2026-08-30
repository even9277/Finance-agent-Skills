"""把工具观察归一化为可审计 Evidence Envelope 并执行硬门控。"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import replace
from datetime import date

from .contracts import (
    ClaimLevel,
    EvidenceDimension,
    EvidenceEnvelope,
    EvidenceRejectionCode,
    EvidenceRequirement,
    EvidenceRole,
    EvidenceScoreBreakdown,
    EvidenceStatus,
    StepStatus,
    ToolObservation,
    ToolPlan,
    ToolPlanStep,
    VerificationResult,
)

_FRESHNESS_DAYS: dict[EvidenceDimension, int] = {
    EvidenceDimension.MARKET_SNAPSHOT: 7,
    EvidenceDimension.FUND_NAV: 7,
    EvidenceDimension.FUND_MARKET: 7,
    EvidenceDimension.FUND_SHARE: 31,
    EvidenceDimension.INDEX_DAILY: 7,
    EvidenceDimension.SECTOR_SNAPSHOT: 7,
    EvidenceDimension.SECTOR_CONSTITUENTS: 31,
    EvidenceDimension.FINANCIAL_INDICATOR: 550,
    EvidenceDimension.INCOME_STATEMENT: 550,
    EvidenceDimension.BALANCE_SHEET: 550,
    EvidenceDimension.CASHFLOW_STATEMENT: 550,
    EvidenceDimension.BASIC_PROFILE: 3_650,
    EvidenceDimension.FUND_BASIC: 3_650,
    EvidenceDimension.ETF_BASIC: 3_650,
    EvidenceDimension.WEB_NEWS: 31,
}

_HARD_GATE_CODES = frozenset(
    {
        EvidenceRejectionCode.CONTRACT_MISMATCH,
        EvidenceRejectionCode.ENTITY_MISMATCH,
        EvidenceRejectionCode.FUTURE_DATED,
        EvidenceRejectionCode.CONFLICT,
    }
)

_QUALITY_FIELDS: dict[EvidenceDimension, frozenset[str]] = {
    EvidenceDimension.BASIC_PROFILE: frozenset({"name", "ts_code", "symbol"}),
    EvidenceDimension.MARKET_SNAPSHOT: frozenset({"close", "trade_date", "pct_change"}),
    EvidenceDimension.FINANCIAL_INDICATOR: frozenset(
        {"roe", "roa", "revenue", "net_profit", "grossprofit_margin", "debt_to_assets"}
    ),
    EvidenceDimension.INCOME_STATEMENT: frozenset(
        {"revenue", "total_revenue", "n_income", "net_profit"}
    ),
    EvidenceDimension.BALANCE_SHEET: frozenset(
        {"total_assets", "total_liab", "money_cap", "total_hldr_eqy_exc_min_int"}
    ),
    EvidenceDimension.CASHFLOW_STATEMENT: frozenset(
        {"n_cashflow_act", "n_cashflow_inv_act", "n_cash_flows_fnc_act", "free_cashflow"}
    ),
    EvidenceDimension.FUND_BASIC: frozenset({"fund_name", "name", "ts_code"}),
    EvidenceDimension.ETF_BASIC: frozenset({"fund_name", "name", "ts_code"}),
    EvidenceDimension.FUND_NAV: frozenset({"unit_nav", "accum_nav", "nav_date"}),
    EvidenceDimension.FUND_MARKET: frozenset({"close", "trade_date", "pct_change"}),
    EvidenceDimension.FUND_SHARE: frozenset({"fd_share", "share", "trade_date"}),
    EvidenceDimension.INDEX_DAILY: frozenset({"close", "trade_date", "pct_change"}),
    EvidenceDimension.SECTOR_SNAPSHOT: frozenset(
        {"pct_change", "close", "trade_date", "up_count", "down_count"}
    ),
    EvidenceDimension.SECTOR_CONSTITUENTS: frozenset(
        {"constituent", "symbol", "ts_code", "name"}
    ),
    EvidenceDimension.WEB_NEWS: frozenset(
        {"title", "url", "domain", "summary", "published_at", "retrieved_at"}
    ),
}


class EvidenceVerifier:
    """统一验收主语、时间、维度、角色、质量和事实冲突。"""

    def verify(
        self,
        *,
        plan: ToolPlan,
        observations: tuple[ToolObservation, ...],
        as_of: date,
    ) -> VerificationResult:
        """把执行结果分为 accepted/rejected 并裁定结论强度。

        Args:
            plan: 当前根计划与已合并补证步骤的结构化计划。
            observations: Executor 归一化后的全部步骤结果。
            as_of: 本轮分析时钟日期，用于判定未来数据和新鲜度。

        Returns:
            唯一证据验收结果；被拒绝事实不会进入回答上下文。
        """
        steps = {step.step_id: step for step in plan.steps}
        accepted_candidates: list[EvidenceEnvelope] = []
        rejected: list[EvidenceEnvelope] = []
        for observation in observations:
            envelope = self._normalize(
                plan=plan,
                step=steps.get(observation.step_id),
                observation=observation,
                as_of=as_of,
            )
            if envelope.status is EvidenceStatus.ACCEPTED:
                accepted_candidates.append(envelope)
            else:
                rejected.append(envelope)

        accepted, conflicts = self._reject_conflicts(tuple(accepted_candidates))
        rejected.extend(conflicts)
        missing = self._missing_requirements(plan.requirements, accepted)
        missing_groups, group_dimensions, distinct_shortfall = self._missing_skill_groups(
            plan,
            accepted,
        )
        missing_dimensions = tuple(
            dict.fromkeys((*tuple(item.dimension for item in missing), *group_dimensions))
        )
        hard_failures = tuple(
            dict.fromkeys(
                code
                for item in rejected
                if (code := item.rejection_code) is not None
                and code in _HARD_GATE_CODES
            )
        )
        has_strong_evidence = any(
            item.evidence_dimension is not EvidenceDimension.WEB_NEWS
            for item in accepted
        )
        if (
            accepted
            and has_strong_evidence
            and not missing
            and not missing_groups
            and distinct_shortfall == 0
            and not hard_failures
        ):
            claim_level = ClaimLevel.ANALYTICAL
        elif accepted:
            claim_level = ClaimLevel.DESCRIPTIVE
        else:
            claim_level = ClaimLevel.REFUSE
        return VerificationResult(
            accepted=accepted,
            rejected=tuple(rejected),
            missing_dimensions=missing_dimensions,
            missing_requirements=missing,
            claim_level=claim_level,
            recoverable=bool(missing or missing_groups or distinct_shortfall),
            score=self._score(
                requirements=plan.requirements,
                accepted=accepted,
                rejected=tuple(rejected),
            ),
            hard_gate_failures=hard_failures,
            missing_evidence_groups=missing_groups,
            distinct_symbol_shortfall=distinct_shortfall,
        )

    def _normalize(
        self,
        *,
        plan: ToolPlan,
        step: ToolPlanStep | None,
        observation: ToolObservation,
        as_of: date,
    ) -> EvidenceEnvelope:
        freshness_days = (as_of - observation.observed_at).days
        rejection = self._rejection_code(
            step=step,
            observation=observation,
            freshness_days=freshness_days,
            enforce_field_quality=plan.evidence_contract is not None,
        )
        role = (
            EvidenceRole.REQUIRED
            if step is not None and step.required
            else EvidenceRole.OPTIONAL
        )
        identity = "|".join(
            (
                plan.plan_id,
                observation.step_id,
                observation.tool_name,
                observation.source,
                observation.observed_at.isoformat(),
            )
        )
        return EvidenceEnvelope(
            evidence_id=f"ev-{hashlib.sha256(identity.encode()).hexdigest()[:20]}",
            plan_id=plan.plan_id,
            step_id=observation.step_id,
            tool_name=observation.tool_name,
            entity_symbol=observation.symbol,
            evidence_dimension=observation.evidence_dimension,
            role=role,
            facts=observation.facts,
            source=observation.source,
            observed_at=observation.observed_at,
            status=(
                EvidenceStatus.REJECTED
                if rejection is not None
                else EvidenceStatus.ACCEPTED
            ),
            quality_score=self._quality_score(observation),
            freshness_days=freshness_days,
            rejection_code=rejection,
            source_error_code=observation.error_code,
        )

    @staticmethod
    def _rejection_code(
        *,
        step: ToolPlanStep | None,
        observation: ToolObservation,
        freshness_days: int,
        enforce_field_quality: bool,
    ) -> EvidenceRejectionCode | None:
        if observation.status is not StepStatus.SUCCEEDED:
            return EvidenceRejectionCode.STEP_FAILED
        if step is None:
            return EvidenceRejectionCode.UNKNOWN_STEP
        if observation.symbol != step.symbol:
            return EvidenceRejectionCode.ENTITY_MISMATCH
        if (
            observation.tool_name != step.tool_name
            or observation.evidence_dimension is not step.evidence_dimension
        ):
            return EvidenceRejectionCode.CONTRACT_MISMATCH
        if not observation.facts:
            return EvidenceRejectionCode.EMPTY_FACTS
        if any(not item.key.strip() or not item.value.strip() for item in observation.facts):
            return EvidenceRejectionCode.INVALID_FACT
        if not observation.source.strip():
            return EvidenceRejectionCode.SOURCE_MISSING
        if freshness_days < 0:
            return EvidenceRejectionCode.FUTURE_DATED
        if freshness_days > _FRESHNESS_DAYS[observation.evidence_dimension]:
            return EvidenceRejectionCode.STALE
        if enforce_field_quality:
            expected = _QUALITY_FIELDS[observation.evidence_dimension]
            actual = {
                item.key.strip().lower().rsplit(".", maxsplit=1)[-1]
                for item in observation.facts
            }
            if not actual.intersection(expected):
                return EvidenceRejectionCode.FIELD_QUALITY
        return None

    @staticmethod
    def _missing_skill_groups(
        plan: ToolPlan,
        accepted: tuple[EvidenceEnvelope, ...],
    ) -> tuple[tuple[str, ...], tuple[EvidenceDimension, ...], int]:
        """验收 Skill 的 any/per-symbol/min-distinct 证据组。

        Args:
            plan: 带可选 Skill 证据合同的当前合并计划。
            accepted: 已通过单条证据硬门控和冲突检查的证据。

        Returns:
            稳定缺口标识、缺失维度并集和最小主体数差额。
        """
        contract = plan.evidence_contract
        if contract is None:
            return (), (), 0
        groups: list[str] = []
        dimensions: list[EvidenceDimension] = []
        accepted_dimensions = {item.evidence_dimension for item in accepted}
        for dimension in contract.must_have_all:
            if dimension not in accepted_dimensions:
                groups.append(f"must_have_all:{dimension.value}")
                dimensions.append(dimension)
        if contract.must_have_any and not accepted_dimensions.intersection(contract.must_have_any):
            groups.append("must_have_any")
            dimensions.extend(contract.must_have_any)
        if contract.per_symbol_must_have_any:
            for entity in plan.entities:
                if not entity.symbol:
                    continue
                if not any(
                    item.entity_symbol == entity.symbol
                    and item.evidence_dimension in contract.per_symbol_must_have_any
                    for item in accepted
                ):
                    groups.append(f"per_symbol:{entity.symbol}")
                    dimensions.extend(contract.per_symbol_must_have_any)
        accepted_symbols = {item.entity_symbol for item in accepted if item.entity_symbol}
        distinct_shortfall = max(
            0,
            (contract.min_distinct_symbols or 0) - len(accepted_symbols),
        )
        if distinct_shortfall:
            groups.append("min_distinct_symbols")
        return tuple(groups), tuple(dict.fromkeys(dimensions)), distinct_shortfall

    @staticmethod
    def _quality_score(observation: ToolObservation) -> int:
        if observation.status is not StepStatus.SUCCEEDED or not observation.facts:
            return 0
        valid_facts = sum(
            bool(item.key.strip()) and bool(item.value.strip()) for item in observation.facts
        )
        fact_score = round(80 * valid_facts / len(observation.facts))
        return min(100, fact_score + (20 if observation.source.strip() else 0))

    @staticmethod
    def _reject_conflicts(
        candidates: tuple[EvidenceEnvelope, ...],
    ) -> tuple[tuple[EvidenceEnvelope, ...], tuple[EvidenceEnvelope, ...]]:
        values: dict[tuple[str, EvidenceDimension, date, str], set[tuple[str, str | None]]] = (
            defaultdict(set)
        )
        for envelope in candidates:
            for fact in envelope.facts:
                values[
                    (
                        envelope.entity_symbol,
                        envelope.evidence_dimension,
                        envelope.observed_at,
                        fact.key,
                    )
                ].add((fact.value, fact.unit))
        conflict_keys = {key for key, fact_values in values.items() if len(fact_values) > 1}
        accepted: list[EvidenceEnvelope] = []
        rejected: list[EvidenceEnvelope] = []
        for envelope in candidates:
            has_conflict = any(
                (
                    envelope.entity_symbol,
                    envelope.evidence_dimension,
                    envelope.observed_at,
                    fact.key,
                )
                in conflict_keys
                for fact in envelope.facts
            )
            if has_conflict:
                rejected.append(
                    replace(
                        envelope,
                        status=EvidenceStatus.REJECTED,
                        rejection_code=EvidenceRejectionCode.CONFLICT,
                    )
                )
            else:
                accepted.append(envelope)
        return tuple(accepted), tuple(rejected)

    @staticmethod
    def _missing_requirements(
        requirements: tuple[EvidenceRequirement, ...],
        accepted: tuple[EvidenceEnvelope, ...],
    ) -> tuple[EvidenceRequirement, ...]:
        coverage = {
            (item.evidence_dimension, item.entity_symbol or None) for item in accepted
        }
        missing: list[EvidenceRequirement] = []
        seen: set[tuple[EvidenceDimension, str | None]] = set()
        for requirement in requirements:
            key = (requirement.dimension, requirement.entity_symbol)
            covered = (
                key in coverage
                if requirement.entity_symbol is not None
                else any(
                    dimension is requirement.dimension for dimension, _ in coverage
                )
            )
            if requirement.required and not covered and key not in seen:
                missing.append(requirement)
                seen.add(key)
        return tuple(missing)

    @staticmethod
    def _score(
        *,
        requirements: tuple[EvidenceRequirement, ...],
        accepted: tuple[EvidenceEnvelope, ...],
        rejected: tuple[EvidenceEnvelope, ...],
    ) -> EvidenceScoreBreakdown:
        required_keys = {
            (item.dimension, item.entity_symbol)
            for item in requirements
            if item.required
        }
        accepted_keys = {
            (item.evidence_dimension, item.entity_symbol or None) for item in accepted
        }
        coverage_ratio = (
            len(required_keys & accepted_keys) / len(required_keys) if required_keys else 1.0
        )
        entity = 0 if any(
            item.rejection_code
            in {
                EvidenceRejectionCode.ENTITY_MISMATCH,
                EvidenceRejectionCode.CONTRACT_MISMATCH,
            }
            for item in rejected
        ) else 25
        freshness = 0 if any(
            item.rejection_code
            in {EvidenceRejectionCode.STALE, EvidenceRejectionCode.FUTURE_DATED}
            for item in rejected
        ) else 20
        coverage = round(25 * coverage_ratio)
        role = round(15 * coverage_ratio)
        quality = (
            round(15 * sum(item.quality_score for item in accepted) / (100 * len(accepted)))
            if accepted
            else 0
        )
        return EvidenceScoreBreakdown(
            entity=entity,
            freshness=freshness,
            coverage=coverage,
            role=role,
            quality=quality,
            total=entity + freshness + coverage + role + quality,
        )
