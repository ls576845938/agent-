"""Pure frozen Qlib candidate policy used by research and offline replay.

The function in this module owns no clock, file, model, account, OMS or
transport.  Callers supply every visible forecast, account/risk fact and frozen
policy identity.  The output never grants execution permission.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import math
from typing import Any, Callable, Mapping
import hashlib
import json
import re

from quant_crypto.portfolio.decision import BTCPortfolioDecision, build_btc_portfolio_decision
from quant_crypto.portfolio.forecast import (
    BTCForecast,
    BTCRiskBudget,
    BTCRiskState,
    btc_forecast_to_target_position,
)
from quant_crypto.portfolio.order_intent import (
    BTCExecutionCostEstimate,
    BTCOrderIntentDecision,
    btc_target_to_cost_aware_order_intent,
)
from quant_crypto.risk import RiskAssessment, RiskConstitution, assess_btc_risk
from quant_crypto.risk.liquidation import BTCReferencePriceState
from quant_crypto.trading_contracts import TargetPosition


POLICY_VERSION = "qlib_candidate_policy_v1"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def policy_binding_digest(value: Mapping[str, Any]) -> str:
    raw = json.dumps(dict(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CandidatePolicyVersions:
    policy_version: str
    position_policy_sha256: str
    exit_policy_sha256: str
    cost_policy_sha256: str

    def __post_init__(self) -> None:
        if self.policy_version != POLICY_VERSION:
            raise ValueError("candidate_policy_version_mismatch")
        for name in (
            "position_policy_sha256",
            "exit_policy_sha256",
            "cost_policy_sha256",
        ):
            if _SHA256.fullmatch(str(getattr(self, name))) is None:
                raise ValueError(f"candidate_{name}_invalid")

    def to_dict(self) -> dict[str, str]:
        return {
            "policy_version": self.policy_version,
            "position_policy_sha256": self.position_policy_sha256,
            "exit_policy_sha256": self.exit_policy_sha256,
            "cost_policy_sha256": self.cost_policy_sha256,
        }


@dataclass(frozen=True)
class CandidateExitPolicy:
    hard_stop_fraction: float
    trailing_stop_fraction: float
    maximum_holding_bars: int

    def __post_init__(self) -> None:
        if not (
            math.isfinite(self.hard_stop_fraction)
            and math.isfinite(self.trailing_stop_fraction)
            and 0 < self.hard_stop_fraction < 1
            and 0 < self.trailing_stop_fraction < 1
            and isinstance(self.maximum_holding_bars, int)
            and self.maximum_holding_bars > 0
        ):
            raise ValueError("candidate_exit_policy_invalid")


@dataclass(frozen=True)
class CandidateExitState:
    quantity: float
    average_price: float
    favorable_price: float | None
    holding_bars: int

    def __post_init__(self) -> None:
        values = (self.quantity, self.average_price)
        if not all(math.isfinite(float(value)) for value in values):
            raise ValueError("candidate_exit_state_non_finite")
        if self.favorable_price is not None and not math.isfinite(float(self.favorable_price)):
            raise ValueError("candidate_exit_state_non_finite")
        if self.holding_bars < 0:
            raise ValueError("candidate_exit_holding_bars_invalid")
        if self.quantity != 0 and (
            self.average_price <= 0 or self.favorable_price is None or self.favorable_price <= 0
        ):
            raise ValueError("candidate_exit_open_position_state_incomplete")


@dataclass(frozen=True)
class CandidateExitObservation:
    close_price: float
    calibrated_prediction: float
    has_score: bool
    end_of_window: bool

    def __post_init__(self) -> None:
        if not (
            math.isfinite(float(self.close_price))
            and self.close_price > 0
            and math.isfinite(float(self.calibrated_prediction))
        ):
            raise ValueError("candidate_exit_observation_invalid")


@dataclass(frozen=True)
class CandidateExitDecision:
    state: CandidateExitState
    reasons: tuple[str, ...]


def evaluate_candidate_exit(
    state: CandidateExitState,
    observation: CandidateExitObservation,
    policy: CandidateExitPolicy,
) -> CandidateExitDecision:
    """Pure extraction of the immutable research exit ordering.

    Only bars carrying a forecast update holding/favourable state.  Issuing an
    exit does not reset that state; the caller may reset it only after a real
    fill makes the position flat.
    """

    if not observation.has_score:
        return CandidateExitDecision(state=state, reasons=())
    reasons: list[str] = []
    updated = state
    if state.quantity != 0:
        holding = state.holding_bars + 1
        favorable = (
            max(float(state.favorable_price), observation.close_price)
            if state.quantity > 0
            else min(float(state.favorable_price), observation.close_price)
        )
        updated = CandidateExitState(
            quantity=state.quantity,
            average_price=state.average_price,
            favorable_price=favorable,
            holding_bars=holding,
        )
        signed = math.copysign(1.0, state.quantity)
        if signed * (observation.close_price / state.average_price - 1.0) <= -policy.hard_stop_fraction:
            reasons.append("close_observed_hard_stop")
        if signed * (observation.close_price / favorable - 1.0) <= -policy.trailing_stop_fraction:
            reasons.append("close_observed_trailing_stop")
        if holding >= policy.maximum_holding_bars:
            reasons.append("maximum_holding_period")
        if state.quantity * observation.calibrated_prediction <= 0:
            reasons.append("forecast_reversal_flat_first")
    if observation.end_of_window:
        reasons.append("end_of_research_window")
    return CandidateExitDecision(state=updated, reasons=tuple(reasons))


@dataclass(frozen=True)
class CandidatePolicyFacts:
    decision_id: str
    forecast: BTCForecast
    expected_source_signal_id: str
    risk_budget: BTCRiskBudget
    risk_state: BTCRiskState
    account_equity: float
    mark_price: float
    current_quantity: float
    reference_prices: BTCReferencePriceState | Callable[[TargetPosition], BTCReferencePriceState]
    constitution: RiskConstitution
    combined_loss: Any
    protection_before: Any
    protection_after: Callable[[float], Any]
    cost_estimate: BTCExecutionCostEstimate
    min_quantity: float
    blockers: tuple[str, ...]
    exit_state: CandidateExitState
    exit_observation: CandidateExitObservation
    exit_policy: CandidateExitPolicy
    versions: CandidatePolicyVersions


@dataclass(frozen=True)
class CandidatePolicyDecision:
    forecast: BTCForecast
    target: TargetPosition
    reference_prices: BTCReferencePriceState
    assessment: RiskAssessment
    portfolio: BTCPortfolioDecision
    cost_decision: BTCOrderIntentDecision
    approved: bool
    reasons: tuple[str, ...]
    exit_reasons: tuple[str, ...]
    exit_state: CandidateExitState
    reduction_plan: Any
    policy_versions: CandidatePolicyVersions
    execution_permission: bool = False

    def __post_init__(self) -> None:
        if self.execution_permission is not False:
            raise ValueError("candidate_policy_never_grants_execution_permission")


def _dedupe(values: list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(str(value) for value in values if str(value)))


def evaluate_candidate_policy(facts: CandidatePolicyFacts) -> CandidatePolicyDecision:
    """Apply the frozen position, exit, risk, reduction and cost rules once."""

    if not isinstance(facts.forecast, BTCForecast):
        raise TypeError("candidate_forecast_required")
    if not facts.decision_id or not facts.expected_source_signal_id:
        raise ValueError("candidate_decision_identity_missing")
    if facts.forecast.source_signal_id != facts.expected_source_signal_id:
        raise ValueError("candidate_forecast_source_signal_mismatch")
    if facts.forecast.timestamp_utc >= facts.forecast.expiry_utc:
        raise ValueError("candidate_forecast_expired")

    exit_decision = evaluate_candidate_exit(
        facts.exit_state,
        facts.exit_observation,
        facts.exit_policy,
    )
    target = btc_forecast_to_target_position(
        facts.forecast,
        risk_budget=facts.risk_budget,
        risk_state=facts.risk_state,
        account_equity=float(facts.account_equity),
        mark_price=float(facts.mark_price),
    )
    proposal_metadata = {
        key: value
        for key, value in target.metadata.items()
        if key not in {"perpetual_risk_policy", "risk_state"}
    }
    target = replace(
        target,
        target_position_id=facts.decision_id + ":target",
        metadata={
            **proposal_metadata,
            "source_kind": "forecast",
            "source_forecast_id": facts.forecast.forecast_id,
            "source_signal_id": facts.forecast.source_signal_id,
            "sizing_scope": "unlevered_exposure_proposal",
            "production_perpetual_sizing_ready": False,
            "volatility_target_applied": False,
            "policy_versions": facts.versions.to_dict(),
        },
    )
    if exit_decision.reasons:
        target = replace(
            target,
            target_quantity=0.0,
            target_weight=0.0,
            metadata={
                **target.metadata,
                "order_generation_allowed": True,
                "research_exit_reasons": list(exit_decision.reasons),
            },
        )

    reference_prices = (
        facts.reference_prices(target)
        if callable(facts.reference_prices)
        else facts.reference_prices
    )
    if not isinstance(reference_prices, BTCReferencePriceState):
        raise TypeError("candidate_reference_prices_required")

    def assessment_for(candidate: TargetPosition) -> RiskAssessment:
        return assess_btc_risk(
            constitution=facts.constitution,
            position_before=float(facts.current_quantity),
            position_after=float(candidate.target_quantity or 0.0),
            reference_prices=reference_prices,
            account_equity=float(facts.account_equity),
            combined_loss=facts.combined_loss,
            protection_before=facts.protection_before,
            protection_after=facts.protection_after(float(candidate.target_quantity or 0.0)),
        )

    assessment = assessment_for(target)
    portfolio = build_btc_portfolio_decision(
        target,
        current_quantity=float(facts.current_quantity),
        risk_assessment=assessment,
        decision_time_utc=facts.forecast.timestamp_utc,
        source="qlib_research",
        forecast=facts.forecast,
    )
    reduction = portfolio.reduction_plan
    if reduction is not None and reduction.target_quantity != target.target_quantity:
        target = replace(
            target,
            target_quantity=reduction.target_quantity,
            target_weight=(
                reduction.target_quantity * float(facts.mark_price) / float(facts.account_equity)
            ),
        )
        assessment = assessment_for(target)
        portfolio = build_btc_portfolio_decision(
            target,
            current_quantity=float(facts.current_quantity),
            risk_assessment=assessment,
            decision_time_utc=facts.forecast.timestamp_utc,
            source="qlib_research",
            forecast=facts.forecast,
        )
        reduction = portfolio.reduction_plan

    reduce_only = reduction is not None
    if reduce_only:
        if not (
            reduction.current_quantity == facts.current_quantity
            and reduction.target_quantity == target.target_quantity
            and facts.current_quantity * reduction.target_quantity >= 0
            and abs(reduction.target_quantity) < abs(facts.current_quantity)
            and reduction.reduction_quantity
            == abs(facts.current_quantity) - abs(reduction.target_quantity)
            and reduction.source_target_position_id == target.target_position_id
            and reduction.source_forecast_id == facts.forecast.forecast_id
            and reduction.symbol == target.symbol
            and reduction.strategy_id == target.strategy_id
            and reduction.decision_time_utc == facts.forecast.timestamp_utc
            and assessment.metadata.get("position_before") == facts.current_quantity
            and assessment.metadata.get("position_after") == target.target_quantity
            and assessment.execution_permission is False
        ):
            raise ValueError("candidate_reduction_plan_binding_mismatch")

    cost_decision = btc_target_to_cost_aware_order_intent(
        target,
        current_quantity=float(facts.current_quantity),
        cost_estimate=facts.cost_estimate,
        min_quantity=float(facts.min_quantity),
    )
    target_quantity = float(target.target_quantity or 0.0)
    reducing = (
        facts.current_quantity != 0
        and target_quantity * facts.current_quantity >= 0
        and abs(target_quantity) < abs(facts.current_quantity)
    )
    approved = bool(
        reduce_only
        or (
            not facts.blockers
            and portfolio.order_generation_allowed
            and (reducing or cost_decision.approved)
        )
    )
    reasons = _dedupe(
        [
            *facts.blockers,
            *assessment.blockers,
            *portfolio.reason_codes,
            *([] if reducing else cost_decision.blockers),
        ]
    )
    return CandidatePolicyDecision(
        forecast=facts.forecast,
        target=target,
        reference_prices=reference_prices,
        assessment=assessment,
        portfolio=portfolio,
        cost_decision=cost_decision,
        approved=approved,
        reasons=reasons,
        exit_reasons=exit_decision.reasons,
        exit_state=exit_decision.state,
        reduction_plan=reduction,
        policy_versions=facts.versions,
    )


__all__ = [
    "CandidatePolicyDecision",
    "CandidateExitDecision",
    "CandidateExitObservation",
    "CandidateExitPolicy",
    "CandidateExitState",
    "CandidatePolicyFacts",
    "CandidatePolicyVersions",
    "POLICY_VERSION",
    "evaluate_candidate_policy",
    "evaluate_candidate_exit",
    "policy_binding_digest",
]
