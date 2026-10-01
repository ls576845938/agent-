from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from quant_shared.core.time import ensure_utc

from quant_crypto.adapters.shared_platform import new_btc_id
from quant_crypto.trading_contracts import Signal, SignalDirection, TargetPosition


FORECAST_SCHEMA_VERSION = "btc_forecast_v1"
BTC_TARGET_FROM_FORECAST_VERSION = "btc_target_from_forecast_v1"


@dataclass(frozen=True)
class BTCForecastQuality:
    ic: float | None = None
    hit_rate: float | None = None
    sample_size: int = 0
    evidence_path: str = ""
    evidence_hash: str = ""

    @property
    def has_predictive_evidence(self) -> bool:
        return self.sample_size > 0 and (self.ic is not None or self.hit_rate is not None)


@dataclass(frozen=True)
class BTCForecast:
    timestamp_utc: datetime
    strategy_id: str
    symbol: str
    direction: SignalDirection
    score: float
    horizon: str
    unit: str
    expected_return_bps: float
    confidence: float
    expiry_utc: datetime
    source_signal_id: str
    quality: BTCForecastQuality
    reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    forecast_id: str = field(default_factory=lambda: new_btc_id("fcst"))

    def __post_init__(self) -> None:
        object.__setattr__(self, "timestamp_utc", ensure_utc(self.timestamp_utc))
        object.__setattr__(self, "expiry_utc", ensure_utc(self.expiry_utc))
        object.__setattr__(self, "symbol", self.symbol.upper())
        object.__setattr__(self, "score", max(0.0, min(1.0, float(self.score))))
        object.__setattr__(self, "confidence", max(0.0, min(1.0, float(self.confidence))))
        if self.expiry_utc <= self.timestamp_utc:
            raise ValueError("BTC forecast expiry must be after timestamp.")
        if not self.horizon:
            raise ValueError("BTC forecast horizon is required.")
        if not self.unit:
            raise ValueError("BTC forecast unit is required.")
        if not self.quality.has_predictive_evidence:
            raise ValueError("BTC forecast requires IC or hit-rate evidence with sample_size > 0.")

    def to_metadata(self) -> dict[str, Any]:
        return {
            "forecast_schema_version": FORECAST_SCHEMA_VERSION,
            "forecast_id": self.forecast_id,
            "forecast_horizon": self.horizon,
            "forecast_unit": self.unit,
            "forecast_confidence": self.confidence,
            "forecast_expiry_utc": self.expiry_utc.isoformat(),
            "forecast_expected_return_bps": self.expected_return_bps,
            "forecast_ic": self.quality.ic,
            "forecast_hit_rate": self.quality.hit_rate,
            "forecast_sample_size": self.quality.sample_size,
            "forecast_evidence_path": self.quality.evidence_path,
            "forecast_evidence_hash": self.quality.evidence_hash,
            "source_signal_id": self.source_signal_id,
            **dict(self.metadata),
        }


@dataclass(frozen=True)
class BTCRiskBudget:
    max_btc_exposure: float
    strategy_risk_budget: float
    target_volatility: float
    current_weight: float = 0.0
    max_turnover: float = 1.0
    estimated_round_trip_cost_bps: float = 0.0
    min_cash_fraction: float = 0.0
    max_daily_loss_pct: float = 1.0
    max_drawdown_pct: float = 1.0
    max_abs_funding_rate: float = 1.0
    require_funding_rate: bool = True
    require_liquidation_risk: bool = False

    def __post_init__(self) -> None:
        for field_name in [
            "max_btc_exposure",
            "strategy_risk_budget",
            "target_volatility",
            "max_turnover",
            "estimated_round_trip_cost_bps",
            "min_cash_fraction",
            "max_daily_loss_pct",
            "max_drawdown_pct",
            "max_abs_funding_rate",
        ]:
            value = float(getattr(self, field_name))
            if value < 0.0:
                raise ValueError(f"{field_name} must be non-negative.")
            object.__setattr__(self, field_name, value)
        object.__setattr__(self, "current_weight", float(self.current_weight))
        object.__setattr__(self, "min_cash_fraction", min(1.0, self.min_cash_fraction))


@dataclass(frozen=True)
class BTCRiskState:
    cash_fraction: float
    daily_loss_pct: float
    current_drawdown_pct: float
    cooldown_until_utc: datetime | None = None
    funding_rate: float | None = None
    exchange_available: bool = True
    data_anomaly: bool = False
    perp_risk_decision: Any | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "cash_fraction", max(0.0, min(1.0, float(self.cash_fraction))))
        object.__setattr__(self, "daily_loss_pct", max(0.0, float(self.daily_loss_pct)))
        object.__setattr__(self, "current_drawdown_pct", max(0.0, float(self.current_drawdown_pct)))
        if self.cooldown_until_utc is not None:
            object.__setattr__(self, "cooldown_until_utc", ensure_utc(self.cooldown_until_utc))
        if self.funding_rate is not None:
            object.__setattr__(self, "funding_rate", float(self.funding_rate))


def signal_to_btc_forecast(
    signal: Signal,
    *,
    quality: BTCForecastQuality,
    horizon: str,
    unit: str = "bps",
    expiry_bars: int = 12,
    bar_minutes: int = 5,
    max_expected_return_bps: float = 100.0,
) -> BTCForecast:
    if signal.direction == SignalDirection.FLAT:
        expected_return_bps = 0.0
    else:
        sign = 1.0 if signal.direction == SignalDirection.LONG else -1.0
        expected_return_bps = sign * float(max_expected_return_bps) * float(signal.strength)
    confidence = _confidence_from_quality(quality)
    expiry = ensure_utc(signal.timestamp_utc) + timedelta(minutes=int(expiry_bars) * int(bar_minutes))
    return BTCForecast(
        timestamp_utc=signal.timestamp_utc,
        strategy_id=signal.strategy_id,
        symbol=signal.symbol,
        direction=signal.direction,
        score=float(signal.strength),
        horizon=horizon,
        unit=unit,
        expected_return_bps=expected_return_bps,
        confidence=confidence,
        expiry_utc=expiry,
        source_signal_id=signal.signal_id,
        quality=quality,
        reason=signal.reason,
        metadata={"source": "signal_to_btc_forecast", "signal_reason": signal.reason},
    )


def btc_forecast_to_target_position(
    forecast: BTCForecast | None,
    *,
    risk_budget: BTCRiskBudget,
    risk_state: BTCRiskState | None,
    account_equity: float,
    mark_price: float,
) -> TargetPosition:
    if forecast is None:
        raise ValueError("BTC TargetPosition requires a Forecast; Signal cannot be sized directly.")
    if risk_state is None:
        raise ValueError("BTC TargetPosition requires current risk state.")
    if account_equity <= 0.0:
        raise ValueError("account_equity must be positive.")
    if mark_price <= 0.0:
        raise ValueError("mark_price must be positive.")
    directional_sign = 0.0
    if forecast.direction == SignalDirection.LONG:
        directional_sign = 1.0
    elif forecast.direction == SignalDirection.SHORT:
        directional_sign = -1.0
    raw_weight = directional_sign * forecast.score * forecast.confidence * risk_budget.strategy_risk_budget
    exposure_capped = max(-risk_budget.max_btc_exposure, min(risk_budget.max_btc_exposure, raw_weight))
    cash_cap = max(0.0, 1.0 - risk_budget.min_cash_fraction)
    cash_capped = max(-cash_cap, min(cash_cap, exposure_capped))
    turnover = abs(exposure_capped - risk_budget.current_weight)
    turnover_scale = 1.0
    if risk_budget.max_turnover > 0.0 and abs(cash_capped - risk_budget.current_weight) > risk_budget.max_turnover:
        turnover = abs(cash_capped - risk_budget.current_weight)
        turnover_scale = risk_budget.max_turnover / turnover
        cash_capped = risk_budget.current_weight + (cash_capped - risk_budget.current_weight) * turnover_scale
    target_weight = cash_capped
    constraint_violations: list[str] = []
    if abs(raw_weight) > risk_budget.max_btc_exposure:
        constraint_violations.append("max_btc_exposure")
    if abs(exposure_capped) > cash_cap:
        constraint_violations.append("cash_floor")
    if turnover_scale < 1.0:
        constraint_violations.append("max_turnover")
    order_generation_allowed = True
    rebalance_reason = "forecast_to_target_position"
    if risk_state.daily_loss_pct >= risk_budget.max_daily_loss_pct:
        constraint_violations.append("daily_loss_stop")
        target_weight = 0.0
        order_generation_allowed = False
        rebalance_reason = "risk_daily_loss_stop"
    if risk_state.current_drawdown_pct >= risk_budget.max_drawdown_pct:
        constraint_violations.append("drawdown_stop")
        target_weight = 0.0
        order_generation_allowed = False
        rebalance_reason = "risk_drawdown_stop"
    if risk_state.cooldown_until_utc is not None and risk_state.cooldown_until_utc > forecast.timestamp_utc:
        constraint_violations.append("cooldown_active")
        target_weight = 0.0
        order_generation_allowed = False
        rebalance_reason = "risk_cooldown_active"
    if risk_budget.require_funding_rate and risk_state.funding_rate is None:
        constraint_violations.append("funding_rate_missing")
        target_weight = 0.0
        order_generation_allowed = False
        rebalance_reason = "risk_funding_rate_missing"
    if risk_state.funding_rate is not None and abs(risk_state.funding_rate) > risk_budget.max_abs_funding_rate:
        constraint_violations.append("funding_risk")
        target_weight = 0.0
        order_generation_allowed = False
        rebalance_reason = "risk_funding_risk"
    if not risk_state.exchange_available:
        constraint_violations.append("exchange_outage")
        target_weight = risk_budget.current_weight
        order_generation_allowed = False
        rebalance_reason = "risk_exchange_outage_hold"
    if risk_state.data_anomaly:
        constraint_violations.append("data_anomaly")
        target_weight = risk_budget.current_weight
        order_generation_allowed = False
        rebalance_reason = "risk_data_anomaly_hold"
    perp_risk_metadata: dict[str, Any] | None = None
    if risk_budget.require_liquidation_risk:
        if risk_state.perp_risk_decision is None:
            constraint_violations.append("liquidation_risk_missing")
            target_weight = risk_budget.current_weight
            order_generation_allowed = False
            rebalance_reason = "risk_liquidation_missing_hold"
        else:
            perp_risk_metadata = risk_state.perp_risk_decision.to_metadata()
            if not bool(perp_risk_metadata.get("approved")):
                constraint_violations.extend(str(item) for item in perp_risk_metadata.get("blockers", []))
                action = str(perp_risk_metadata.get("action", "hold"))
                target_weight = 0.0 if action == "reduce_or_reject" else risk_budget.current_weight
                order_generation_allowed = False
                rebalance_reason = f"risk_liquidation_{action}"
    perpetual_risk_policy = {
        "perpetual_allowed": bool(risk_budget.require_liquidation_risk),
        "liquidation_risk_required": bool(risk_budget.require_liquidation_risk),
        "funding_rate_required": bool(risk_budget.require_funding_rate),
        "status": (
            "perpetual_risk_required"
            if risk_budget.require_liquidation_risk
            else "not_applicable_spot_or_unlevered_path"
        ),
        "reason": (
            "liquidation risk evidence is required before this target can represent a perpetual path"
            if risk_budget.require_liquidation_risk
            else "current BTC target path is spot or unlevered; perpetual risk is not part of promotion evidence"
        ),
    }
    perp_risk_decision_status = (
        "present"
        if perp_risk_metadata is not None
        else ("missing_required" if risk_budget.require_liquidation_risk else "not_required_spot_or_unlevered_path")
    )
    target_notional = float(account_equity) * target_weight
    target_quantity = target_notional / float(mark_price)
    realized_turnover = abs(target_weight - risk_budget.current_weight)
    estimated_cost_bps = realized_turnover * risk_budget.estimated_round_trip_cost_bps
    return TargetPosition(
        timestamp_utc=forecast.timestamp_utc,
        strategy_id=forecast.strategy_id,
        symbol=forecast.symbol,
        target_weight=target_weight,
        target_quantity=target_quantity,
        signal_id=forecast.source_signal_id,
        metadata={
            **forecast.to_metadata(),
            "target_construction_version": BTC_TARGET_FROM_FORECAST_VERSION,
            "target_notional": target_notional,
            "expected_volatility": risk_budget.target_volatility,
            "risk_budget": risk_budget.strategy_risk_budget,
            "max_btc_exposure": risk_budget.max_btc_exposure,
            "min_cash_fraction": risk_budget.min_cash_fraction,
            "max_daily_loss_pct": risk_budget.max_daily_loss_pct,
            "max_drawdown_pct": risk_budget.max_drawdown_pct,
            "max_abs_funding_rate": risk_budget.max_abs_funding_rate,
            "current_weight": risk_budget.current_weight,
            "turnover": realized_turnover,
            "turnover_scale": turnover_scale,
            "risk_state": {
                "cash_fraction": risk_state.cash_fraction,
                "daily_loss_pct": risk_state.daily_loss_pct,
                "current_drawdown_pct": risk_state.current_drawdown_pct,
                "cooldown_until_utc": (
                    None if risk_state.cooldown_until_utc is None else risk_state.cooldown_until_utc.isoformat()
                ),
                "funding_rate": risk_state.funding_rate,
                "exchange_available": risk_state.exchange_available,
                "data_anomaly": risk_state.data_anomaly,
                "perp_risk_decision": perp_risk_metadata,
                "perp_risk_decision_status": perp_risk_decision_status,
            },
            "perpetual_risk_policy": perpetual_risk_policy,
            "order_generation_allowed": order_generation_allowed,
            "cost_estimate": {
                "round_trip_cost_bps": risk_budget.estimated_round_trip_cost_bps,
                "estimated_cost_bps": estimated_cost_bps,
                "basis": "abs(target_weight-current_weight)*round_trip_cost_bps",
            },
            "constraint_violations": constraint_violations,
            "rebalance_reason": rebalance_reason,
            "source_boundary": "forecast_to_target_position_no_order_intent",
        },
    )


def _confidence_from_quality(quality: BTCForecastQuality) -> float:
    ic_component = 0.0 if quality.ic is None else min(1.0, abs(float(quality.ic)) / 0.10)
    hit_component = 0.0 if quality.hit_rate is None else min(1.0, max(0.0, (float(quality.hit_rate) - 0.50) / 0.20))
    sample_component = min(1.0, max(0.0, float(quality.sample_size) / 100.0))
    evidence_component = max(ic_component, hit_component)
    return round(max(0.0, min(1.0, evidence_component * sample_component)), 8)
