"""Pure BTC portfolio decision and reduction contracts for V3 T3.

The portfolio layer owns the decision boundary between a ``TargetPosition``
and a risk-constrained exit proposal.  It deliberately does not construct an
``OrderIntent`` and does not know about an OMS, runtime, broker, filesystem,
environment or clock.  Callers provide every fact, including decision time.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import isfinite
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Mapping

from quant_shared.core.time import ensure_utc

from quant_crypto.risk import ActionRiskEffect, RiskAssessment, classify_action_risk_effect
from quant_crypto.trading_contracts import TargetPosition

if TYPE_CHECKING:
    # Forecast imports the BTC adapter only for its ID factory.  Keeping this
    # annotation-only avoids pulling an adapter into the pure decision module.
    from quant_crypto.portfolio.forecast import BTCForecast


BTC_PORTFOLIO_DECISION_VERSION = "btc_shared_platform_v3_t3"
BTC_RISK_REDUCTION_PLAN_LEGACY_VERSION = (
    "btc_shared_platform_v3_t3_risk_reduction_plan_v1"
)
BTC_RISK_REDUCTION_PLAN_VERSION = "btc_shared_platform_v3_t3_risk_reduction_plan_v2"
BTC_RISK_REDUCTION_SOURCE_KINDS = frozenset({"signal", "forecast"})


# T2 already supplies the risk vocabulary.  T3 only orders the additional
# portfolio facts deterministically; unknown caller strings sort last.
_REASON_ORDER = (
    "risk_assessment_missing",
    "assessment_metadata_missing",
    "assessment_position_before_missing",
    "assessment_position_before_invalid",
    "assessment_position_before_mismatch",
    "assessment_position_after_missing",
    "assessment_position_after_invalid",
    "assessment_position_after_mismatch",
    "assessment_effect_unresolved",
    "assessment_effect_mismatch",
    "assessment_approved_requires_reduction_conflict",
    "assessment_approved_with_blockers",
    "assessment_execution_permission",
    "source_forecast_id_missing",
    "source_target_position_id_missing",
    "nonfinite_input",
    "current_position_flat",
    "target_quantity_missing",
    "max_safe_quantity_missing",
    "max_safe_quantity_invalid",
    "cross_zero_position",
    "target_increase",
    "target_not_reducing",
    "risk_assessment_blocked",
    "risk_reduction_required",
    "target_blocks_order_generation",
    "max_safe_quantity_cap",
    "target_flatten",
)
_REASON_RANK = {value: index for index, value in enumerate(_REASON_ORDER)}


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if isfinite(number) else None


def _canonical_reason_codes(*groups: Any) -> tuple[str, ...]:
    values: list[str] = []
    for group in groups:
        if group is None:
            continue
        if isinstance(group, str):
            items = (group,)
        else:
            try:
                items = iter(group)
            except TypeError:
                items = (str(group),)
        for item in items:
            if item is None:
                continue
            normalized = str(item).strip().lower().replace(" ", "_")
            if normalized:
                values.append(normalized)
    return tuple(
        sorted(
            set(values),
            key=lambda value: (_REASON_RANK.get(value, len(_REASON_ORDER)), value),
        )
    )


def _target_metadata(target: TargetPosition) -> Mapping[str, Any]:
    metadata = target.metadata
    return metadata if isinstance(metadata, Mapping) else {}


def _target_reason_codes(target: TargetPosition) -> tuple[str, ...]:
    metadata = _target_metadata(target)
    return _canonical_reason_codes(metadata.get("constraint_violations"))


def _reduction_source_identity(
    target: TargetPosition,
    forecast: BTCForecast | None,
) -> tuple[str, str, str] | None:
    """Resolve one explicit direct source without inventing a Forecast.

    Legacy forecast targets remain valid when they carry ``forecast_id``.
    A rule Signal is accepted only when the target explicitly declares
    ``source_kind=signal`` and repeats the exact upstream ``signal_id``.
    """

    metadata = _target_metadata(target)
    declared_kind = str(metadata.get("source_kind") or "").strip().lower()
    if declared_kind and declared_kind not in BTC_RISK_REDUCTION_SOURCE_KINDS:
        return None
    forecast_id_field = str(metadata.get("forecast_id") or "").strip()
    source_forecast_id_field = str(
        metadata.get("source_forecast_id") or ""
    ).strip()
    if (
        forecast_id_field
        and source_forecast_id_field
        and forecast_id_field != source_forecast_id_field
    ):
        return None
    metadata_forecast_id = forecast_id_field or source_forecast_id_field
    metadata_signal_id = str(metadata.get("source_signal_id") or "").strip()
    target_signal_id = str(target.signal_id or "").strip()

    if forecast is not None:
        if declared_kind == "signal":
            return None
        forecast_id = str(forecast.forecast_id or "").strip()
        if not forecast_id or (metadata_forecast_id and metadata_forecast_id != forecast_id):
            return None
        if str(forecast.source_signal_id or "").strip() != target_signal_id:
            return None
        if metadata_signal_id and metadata_signal_id != target_signal_id:
            return None
        return ("forecast", "", forecast_id)

    if declared_kind == "signal":
        if metadata_forecast_id:
            return None
        if not metadata_signal_id or metadata_signal_id != target_signal_id:
            return None
        return ("signal", metadata_signal_id, "")

    # Backward-compatible Forecast path.  A target with no forecast identity
    # is not silently reclassified as a Signal target.
    if not metadata_forecast_id:
        return None
    if metadata_signal_id and metadata_signal_id != target_signal_id:
        return None
    return ("forecast", "", metadata_forecast_id)


def _resolve_time(
    decision_time_utc: datetime | None,
    decision_time: datetime | None,
) -> datetime | None:
    try:
        if decision_time_utc is not None and decision_time is not None:
            if ensure_utc(decision_time_utc) != ensure_utc(decision_time):
                return None
    except (TypeError, ValueError):
        return None
    value = decision_time_utc if decision_time_utc is not None else decision_time
    if value is None:
        return None
    try:
        return ensure_utc(value)
    except (TypeError, ValueError):
        return None


def _deep_copy_value(value: Any) -> Any:
    """Return a detached, JSON-friendly copy without exposing frozen state."""

    if isinstance(value, Mapping):
        return {key: _deep_copy_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_deep_copy_value(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted(_deep_copy_value(item) for item in value)
    if isinstance(value, datetime):
        return ensure_utc(value).isoformat()
    if hasattr(value, "value") and value.__class__.__module__.startswith("enum"):
        return value.value
    return value


def _freeze_value(value: Any) -> Any:
    """Recursively freeze caller-owned target metadata for a decision snapshot."""

    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze_value(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_value(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(_freeze_value(item) for item in value)
    return value


def _snapshot_target(target: TargetPosition) -> TargetPosition:
    """Copy all target identity fields and recursively freeze metadata."""

    return TargetPosition(
        timestamp_utc=target.timestamp_utc,
        strategy_id=target.strategy_id,
        symbol=target.symbol,
        target_weight=target.target_weight,
        target_quantity=target.target_quantity,
        signal_id=target.signal_id,
        metadata=_freeze_value(_target_metadata(target)),
        target_position_id=target.target_position_id,
    )


def _assessment_binding_reasons(
    target: TargetPosition,
    current_quantity: Any,
    assessment: RiskAssessment,
) -> tuple[str, ...]:
    """Validate that a T2 result was calculated for this exact decision."""

    reasons: list[str] = []
    metadata = assessment.metadata
    if not isinstance(metadata, Mapping):
        reasons.append("assessment_metadata_missing")
        metadata = {}

    current = _finite_number(current_quantity)
    target_quantity = _finite_number(target.target_quantity)

    if "position_before" not in metadata:
        reasons.append("assessment_position_before_missing")
    else:
        before = _finite_number(metadata.get("position_before"))
        if before is None:
            reasons.append("assessment_position_before_invalid")
        elif current is None or before != current:
            reasons.append("assessment_position_before_mismatch")

    if "position_after" not in metadata:
        reasons.append("assessment_position_after_missing")
    else:
        after = _finite_number(metadata.get("position_after"))
        if after is None:
            reasons.append("assessment_position_after_invalid")
        elif target_quantity is None or after != target_quantity:
            reasons.append("assessment_position_after_mismatch")

    expected_effect = classify_action_risk_effect(current, target_quantity)
    if not isinstance(assessment.effect, ActionRiskEffect):
        reasons.append("assessment_effect_mismatch")
    elif assessment.effect is not expected_effect:
        reasons.append(
            "assessment_effect_unresolved"
            if expected_effect is ActionRiskEffect.UNKNOWN
            else "assessment_effect_mismatch"
        )

    if assessment.approved and assessment.requires_reduction:
        reasons.append("assessment_approved_requires_reduction_conflict")
    if assessment.approved and _canonical_reason_codes(assessment.blockers, assessment.reasons):
        reasons.append("assessment_approved_with_blockers")
    if assessment.execution_permission is not False:
        reasons.append("assessment_execution_permission")

    safe = _finite_number(assessment.max_safe_quantity)
    if assessment.max_safe_quantity is None:
        reasons.append("max_safe_quantity_missing")
    elif safe is None or safe < 0.0:
        reasons.append("max_safe_quantity_invalid")
    return _canonical_reason_codes(reasons)


@dataclass(frozen=True)
class RiskReductionPlan:
    """Immutable, auditable plan for reducing an existing signed position.

    This is a decision record only.  It intentionally contains no venue,
    order, client or adapter identifier and can never grant execution.
    """

    symbol: str
    strategy_id: str
    decision_time_utc: datetime
    source_forecast_id: str
    source_target_position_id: str
    current_quantity: float
    target_quantity: float
    reduction_quantity: float
    max_safe_quantity: float
    reason_codes: tuple[str, ...]
    action: ActionRiskEffect = ActionRiskEffect.DECREASE_ABS_EXPOSURE
    plan_version: str = BTC_RISK_REDUCTION_PLAN_LEGACY_VERSION
    source_kind: str = "forecast"
    source_signal_id: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", str(self.symbol).strip().upper())
        object.__setattr__(self, "strategy_id", str(self.strategy_id).strip())
        object.__setattr__(self, "source_forecast_id", str(self.source_forecast_id).strip())
        object.__setattr__(self, "source_signal_id", str(self.source_signal_id).strip())
        object.__setattr__(self, "source_kind", str(self.source_kind).strip().lower())
        object.__setattr__(self, "plan_version", str(self.plan_version).strip())
        object.__setattr__(self, "source_target_position_id", str(self.source_target_position_id).strip())
        object.__setattr__(self, "decision_time_utc", ensure_utc(self.decision_time_utc))
        object.__setattr__(self, "reason_codes", _canonical_reason_codes(self.reason_codes))

        current = _finite_number(self.current_quantity)
        target = _finite_number(self.target_quantity)
        reduction = _finite_number(self.reduction_quantity)
        safe = _finite_number(self.max_safe_quantity)
        if not self.symbol or not self.strategy_id:
            raise ValueError("symbol and strategy_id are required")
        if not self.source_target_position_id:
            raise ValueError("source target identifier is required")
        if self.plan_version not in {
            BTC_RISK_REDUCTION_PLAN_LEGACY_VERSION,
            BTC_RISK_REDUCTION_PLAN_VERSION,
        }:
            raise ValueError("risk reduction plan version is unsupported")
        if self.source_kind not in BTC_RISK_REDUCTION_SOURCE_KINDS:
            raise ValueError("risk reduction source kind is invalid")
        if self.source_kind == "signal":
            if self.plan_version == BTC_RISK_REDUCTION_PLAN_LEGACY_VERSION:
                raise ValueError("legacy risk reduction plan cannot use signal source")
            if not self.source_signal_id or self.source_forecast_id:
                raise ValueError("signal source requires one signal identifier only")
        elif not self.source_forecast_id or self.source_signal_id:
            raise ValueError("forecast source requires one forecast identifier only")
        if current is None or target is None or reduction is None or safe is None:
            raise ValueError("risk reduction quantities must be finite")
        if current == 0.0:
            raise ValueError("risk reduction requires a non-flat current position")
        if safe < 0.0:
            raise ValueError("max_safe_quantity must be non-negative")
        if current * target < 0.0:
            raise ValueError("risk reduction cannot cross zero")
        if abs(target) >= abs(current):
            raise ValueError("risk reduction target must decrease absolute exposure")
        if reduction <= 0.0 or reduction != abs(current) - abs(target):
            raise ValueError("reduction_quantity must match the absolute exposure decrease")
        if self.action is not ActionRiskEffect.DECREASE_ABS_EXPOSURE:
            raise ValueError("risk reduction action must be DECREASE_ABS_EXPOSURE")
        object.__setattr__(self, "current_quantity", current)
        object.__setattr__(self, "target_quantity", target)
        object.__setattr__(self, "reduction_quantity", reduction)
        object.__setattr__(self, "max_safe_quantity", safe)

    @property
    def decision_time(self) -> datetime:
        return self.decision_time_utc

    @property
    def forecast_id(self) -> str:
        return self.source_forecast_id

    @property
    def source_id(self) -> str:
        return (
            self.source_signal_id
            if self.source_kind == "signal"
            else self.source_forecast_id
        )

    @property
    def strategy(self) -> str:
        return self.strategy_id

    @property
    def target_position_id(self) -> str:
        return self.source_target_position_id

    @property
    def reasons(self) -> tuple[str, ...]:
        return self.reason_codes

    @property
    def reduction(self) -> float:
        return self.reduction_quantity

    @property
    def effect(self) -> ActionRiskEffect:
        return self.action

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "schema_version": self.plan_version,
            "plan_version": self.plan_version,
            "symbol": self.symbol,
            "strategy_id": self.strategy_id,
            "decision_time_utc": self.decision_time_utc.isoformat(),
            "source_forecast_id": self.source_forecast_id,
            "source_target_position_id": self.source_target_position_id,
            "current_quantity": self.current_quantity,
            "target_quantity": self.target_quantity,
            "reduction_quantity": self.reduction_quantity,
            "max_safe_quantity": self.max_safe_quantity,
            "reason_codes": list(self.reason_codes),
            "action": self.action.value,
            "effect": self.action.value,
            "execution_permission": False,
        }
        if self.plan_version != BTC_RISK_REDUCTION_PLAN_LEGACY_VERSION:
            payload.update(
                {
                    "source_kind": self.source_kind,
                    "source_signal_id": self.source_signal_id,
                }
            )
        return payload

    to_metadata = to_dict


@dataclass(frozen=True)
class BTCPortfolioDecision:
    """Decision bundle retaining the original target and optional exit plan."""

    target_position: TargetPosition
    risk_assessment: RiskAssessment | None
    reduction_plan: RiskReductionPlan | None
    decision_time_utc: datetime
    source: str
    reason_codes: tuple[str, ...]
    order_generation_allowed: bool
    execution_permission: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.target_position, TargetPosition):
            raise TypeError("target_position must be a TargetPosition")
        object.__setattr__(self, "target_position", _snapshot_target(self.target_position))
        object.__setattr__(self, "decision_time_utc", ensure_utc(self.decision_time_utc))
        source = str(self.source).strip().lower()
        if not source:
            raise ValueError("decision source is required")
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "reason_codes", _canonical_reason_codes(self.reason_codes))
        if self.execution_permission is not False:
            raise ValueError("portfolio decision never grants execution permission")
        object.__setattr__(self, "order_generation_allowed", bool(self.order_generation_allowed))

    @property
    def target(self) -> TargetPosition:
        return self.target_position

    @property
    def plan(self) -> RiskReductionPlan | None:
        return self.reduction_plan

    @property
    def approved(self) -> bool:
        return bool(
            self.risk_assessment is not None
            and self.risk_assessment.approved
            and self.order_generation_allowed
        )

    @property
    def blocked(self) -> bool:
        return not self.approved

    @property
    def requires_reduction(self) -> bool:
        return self.reduction_plan is not None

    def to_dict(self) -> dict[str, Any]:
        target = self.target_position
        target_payload = {
            "target_position_id": target.target_position_id,
            "timestamp_utc": target.timestamp_utc.isoformat(),
            "strategy_id": target.strategy_id,
            "symbol": target.symbol,
            "target_weight": target.target_weight,
            "target_quantity": target.target_quantity,
            "signal_id": target.signal_id,
            "metadata": _deep_copy_value(target.metadata),
        }
        return {
            "schema_version": BTC_PORTFOLIO_DECISION_VERSION,
            "decision_time_utc": self.decision_time_utc.isoformat(),
            "source": self.source,
            "approved": self.approved,
            "blocked": self.blocked,
            "order_generation_allowed": self.order_generation_allowed,
            "execution_permission": False,
            "reason_codes": list(self.reason_codes),
            "target_position": target_payload,
            "risk_assessment": (
                None if self.risk_assessment is None else self.risk_assessment.to_dict()
            ),
            "reduction_plan": (
                None if self.reduction_plan is None else self.reduction_plan.to_dict()
            ),
        }


def _build_plan_reasons(
    target: TargetPosition,
    assessment: RiskAssessment,
    *,
    capped: bool,
    target_quantity: float,
) -> tuple[str, ...]:
    metadata = _target_metadata(target)
    extras: list[str] = []
    if not assessment.approved:
        extras.append("risk_assessment_blocked")
    if assessment.requires_reduction:
        extras.append("risk_reduction_required")
    if metadata.get("order_generation_allowed") is False:
        extras.append("target_blocks_order_generation")
    if capped:
        extras.append("max_safe_quantity_cap")
    if target_quantity == 0.0:
        extras.append("target_flatten")
    return _canonical_reason_codes(
        assessment.blockers,
        assessment.reasons,
        metadata.get("constraint_violations"),
        extras,
    )


def build_risk_reduction_plan(
    target_position: TargetPosition | None = None,
    current_quantity: float | None = None,
    risk_assessment: RiskAssessment | None = None,
    decision_time_utc: datetime | None = None,
    *,
    forecast: BTCForecast | None = None,
    target: TargetPosition | None = None,
    assessment: RiskAssessment | None = None,
    current_position: float | None = None,
    decision_time: datetime | None = None,
) -> RiskReductionPlan | None:
    """Build one safe reduction plan, or ``None`` when no plan is admissible.

    The function is deliberately fail-closed: a missing T2 assessment,
    missing safe quantity, unknown quantity, flat current position, increase,
    or cross-zero proposal never becomes a synthetic reduction plan.
    """

    if target_position is None:
        target_position = target
    elif target is not None and target is not target_position:
        return None
    if risk_assessment is None:
        risk_assessment = assessment
    elif assessment is not None and assessment is not risk_assessment:
        return None
    if current_quantity is None:
        current_quantity = current_position
    elif current_position is not None and current_position != current_quantity:
        return None
    resolved_time = _resolve_time(decision_time_utc, decision_time)
    if not isinstance(target_position, TargetPosition):
        return None
    if not isinstance(risk_assessment, RiskAssessment) or resolved_time is None:
        return None

    current = _finite_number(current_quantity)
    target_value = _finite_number(target_position.target_quantity)
    safe = _finite_number(risk_assessment.max_safe_quantity)
    if _assessment_binding_reasons(target_position, current_quantity, risk_assessment):
        return None
    if classify_action_risk_effect(current, target_value) is not ActionRiskEffect.DECREASE_ABS_EXPOSURE:
        return None
    if current is None or target_value is None:
        return None
    if current == 0.0 or safe is None or safe < 0.0:
        return None
    if current * target_value < 0.0:
        return None
    if abs(target_value) >= abs(current):
        return None

    source_identity = _reduction_source_identity(target_position, forecast)
    source_target_id = str(target_position.target_position_id or "").strip()
    if source_identity is None or not source_target_id:
        return None
    source_kind, source_signal_id, source_forecast_id = source_identity
    if forecast is not None and (
        str(forecast.strategy_id) != str(target_position.strategy_id)
        or str(forecast.symbol).upper() != str(target_position.symbol).upper()
    ):
        return None
    metadata_forecast_id = str(
        _target_metadata(target_position).get("forecast_id")
        or _target_metadata(target_position).get("source_forecast_id")
        or ""
    ).strip()
    if forecast is not None and metadata_forecast_id and metadata_forecast_id != source_forecast_id:
        return None

    order_blocked = _target_metadata(target_position).get("order_generation_allowed") is False
    if not (risk_assessment.requires_reduction or not risk_assessment.approved or order_blocked):
        return None

    desired_abs = abs(target_value)
    safe_abs = min(desired_abs, safe)
    capped = safe_abs < desired_abs
    signed_target = (1.0 if current > 0.0 else -1.0) * safe_abs
    if abs(signed_target) >= abs(current):
        return None
    reduction = abs(current) - abs(signed_target)
    return RiskReductionPlan(
        symbol=target_position.symbol,
        strategy_id=target_position.strategy_id,
        decision_time_utc=resolved_time,
        source_forecast_id=source_forecast_id,
        source_kind=source_kind,
        source_signal_id=source_signal_id,
        plan_version=(
            BTC_RISK_REDUCTION_PLAN_VERSION
            if source_kind == "signal"
            else BTC_RISK_REDUCTION_PLAN_LEGACY_VERSION
        ),
        source_target_position_id=source_target_id,
        current_quantity=current,
        target_quantity=signed_target,
        reduction_quantity=reduction,
        max_safe_quantity=safe,
        reason_codes=_build_plan_reasons(
            target_position,
            risk_assessment,
            capped=capped,
            target_quantity=signed_target,
        ),
    )


def build_btc_portfolio_decision(
    target_position: TargetPosition,
    *,
    current_quantity: float | None = None,
    risk_assessment: RiskAssessment | None = None,
    decision_time_utc: datetime | None = None,
    source: str = "research",
    forecast: BTCForecast | None = None,
    current_position: float | None = None,
    assessment: RiskAssessment | None = None,
    decision_time: datetime | None = None,
    mode: str | None = None,
) -> BTCPortfolioDecision:
    """Return the same decision contract for research and runtime callers."""

    if risk_assessment is None:
        risk_assessment = assessment
    if current_quantity is None:
        current_quantity = current_position
    resolved_time = _resolve_time(decision_time_utc, decision_time)
    if resolved_time is None:
        raise ValueError("decision_time_utc is required and must be explicit")
    resolved_source = str(mode if mode is not None else source).strip().lower()
    if not resolved_source:
        raise ValueError("decision source is required")

    plan = build_risk_reduction_plan(
        target_position,
        current_quantity,
        risk_assessment,
        resolved_time,
        forecast=forecast,
    )
    metadata = _target_metadata(target_position)
    order_allowed = metadata.get("order_generation_allowed", True) is not False
    reasons: list[Any] = [_target_reason_codes(target_position)]
    current = _finite_number(current_quantity)
    target_value = _finite_number(target_position.target_quantity)
    if current is None or target_value is None:
        order_allowed = False
        reasons.append("nonfinite_input" if current is None else "target_quantity_missing")
    elif current != 0.0 and current * target_value < 0.0:
        order_allowed = False
        reasons.append("cross_zero_position")
    elif current != 0.0 and abs(target_value) > abs(current):
        order_allowed = False
        reasons.append("target_increase")
    if not isinstance(risk_assessment, RiskAssessment):
        reasons.append("risk_assessment_missing")
        order_allowed = False
    else:
        reasons.extend((risk_assessment.blockers, risk_assessment.reasons))
        assessment_reasons = _assessment_binding_reasons(
            target_position,
            current_quantity,
            risk_assessment,
        )
        reasons.append(assessment_reasons)
        if assessment_reasons:
            order_allowed = False
        if not risk_assessment.approved or risk_assessment.requires_reduction:
            order_allowed = False
    if plan is not None:
        reasons.append(plan.reason_codes)
    return BTCPortfolioDecision(
        target_position=target_position,
        risk_assessment=risk_assessment,
        reduction_plan=plan,
        decision_time_utc=resolved_time,
        source=resolved_source,
        reason_codes=_canonical_reason_codes(*reasons),
        order_generation_allowed=order_allowed,
    )


# Explicit aliases keep the one T3 contract discoverable without introducing
# a second implementation or a mode-specific algorithm.
build_btc_exit_decision = build_btc_portfolio_decision
build_exit_decision = build_btc_portfolio_decision
build_portfolio_decision = build_btc_portfolio_decision
build_reduction_plan = build_risk_reduction_plan
build_btc_reduction_plan = build_risk_reduction_plan
BTCDecisionBundle = BTCPortfolioDecision
PortfolioDecision = BTCPortfolioDecision


__all__ = [
    "BTC_PORTFOLIO_DECISION_VERSION",
    "BTC_RISK_REDUCTION_PLAN_LEGACY_VERSION",
    "BTC_RISK_REDUCTION_PLAN_VERSION",
    "RiskReductionPlan",
    "BTCPortfolioDecision",
    "BTCDecisionBundle",
    "PortfolioDecision",
    "build_risk_reduction_plan",
    "build_reduction_plan",
    "build_btc_portfolio_decision",
    "build_btc_exit_decision",
    "build_exit_decision",
    "build_portfolio_decision",
    "build_btc_reduction_plan",
]
