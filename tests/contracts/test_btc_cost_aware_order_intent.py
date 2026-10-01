from __future__ import annotations

from datetime import datetime, timezone

import pytest

from quant_crypto.portfolio.forecast import (
    BTCRiskBudget,
    BTCRiskState,
    BTCForecastQuality,
    btc_forecast_to_target_position,
    signal_to_btc_forecast,
)
from quant_crypto.portfolio.order_intent import (
    BTC_COST_AWARE_ORDER_INTENT_VERSION,
    BTCExecutionCostEstimate,
    btc_target_to_cost_aware_order_intent,
)
from quant_crypto.trading_contracts import (
    OrderSide,
    OrderType,
    Signal,
    SignalDirection,
    TimeInForce,
)


def _target(expected_return_bps: float = 80.0, *, daily_loss_stop: bool = False):
    signal = Signal(
        timestamp_utc=datetime(2026, 6, 26, 8, 0, tzinfo=timezone.utc),
        strategy_id="btc_intraday_short_cycle",
        symbol="BTCUSDT",
        direction=SignalDirection.LONG,
        strength=1.0,
        horizon="60m",
        reason="cost gate contract",
    )
    forecast = signal_to_btc_forecast(
        signal,
        quality=BTCForecastQuality(
            ic=0.20,
            sample_size=200,
            evidence_path="artifacts/btc_trial_registry/latest/btc_trial_registry.json",
            evidence_hash="sha256:test",
        ),
        horizon="60m",
        max_expected_return_bps=expected_return_bps,
    )
    target = btc_forecast_to_target_position(
        forecast,
        risk_budget=BTCRiskBudget(
            max_btc_exposure=0.50,
            strategy_risk_budget=0.50,
            target_volatility=0.20,
            current_weight=0.0,
            max_turnover=1.0,
            estimated_round_trip_cost_bps=15.0,
            max_daily_loss_pct=0.03,
            max_abs_funding_rate=0.001,
        ),
        risk_state=BTCRiskState(
            cash_fraction=0.80,
            daily_loss_pct=0.031 if daily_loss_stop else 0.0,
            current_drawdown_pct=0.0,
            funding_rate=0.0001,
        ),
        account_equity=25_000.0,
        mark_price=50_000.0,
    )
    return target


def _complete_cost(**overrides: object) -> BTCExecutionCostEstimate:
    values = {
        "fee_bps": 4.0,
        "spread_bps": 2.0,
        "slippage_bps": 3.0,
        "funding_bps": 1.0,
        "impact_bps": 2.0,
        "source": "contract_fixture",
    }
    values.update(overrides)
    return BTCExecutionCostEstimate(**values)


def test_btc_order_intent_rejected_when_execution_cost_estimate_incomplete() -> None:
    decision = btc_target_to_cost_aware_order_intent(
        _target(),
        current_quantity=0.0,
        cost_estimate=_complete_cost(spread_bps=None),
        min_quantity=0.001,
    )

    assert decision.approved is False
    assert decision.order_intent is None
    assert "execution_cost_estimate_incomplete" in decision.blockers
    assert decision.metadata["cost_estimate"]["missing_components"] == ["spread_bps"]
    assert decision.metadata["alpha_cost_gate"]["total_cost_bps"] is None


def test_btc_order_intent_rejected_when_alpha_does_not_clear_cost() -> None:
    decision = btc_target_to_cost_aware_order_intent(
        _target(expected_return_bps=10.0),
        current_quantity=0.0,
        cost_estimate=_complete_cost(fee_bps=4.0, spread_bps=3.0, slippage_bps=2.0, funding_bps=1.0, impact_bps=1.0),
        min_quantity=0.001,
        min_alpha_to_cost_ratio=1.0,
    )

    assert decision.approved is False
    assert decision.order_intent is None
    assert "alpha_increment_not_cost_effective" in decision.blockers
    assert decision.metadata["alpha_cost_gate"]["expected_return_bps"] == 10.0
    assert decision.metadata["alpha_cost_gate"]["total_cost_bps"] == 11.0
    assert decision.metadata["alpha_cost_gate"]["cost_adjusted_alpha_bps"] == pytest.approx(-1.0)


def test_btc_order_intent_rejected_when_risk_target_blocks_order_generation() -> None:
    decision = btc_target_to_cost_aware_order_intent(
        _target(daily_loss_stop=True),
        current_quantity=0.0,
        cost_estimate=_complete_cost(),
        min_quantity=0.001,
    )

    assert decision.approved is False
    assert decision.order_intent is None
    assert "target_blocks_order_generation" in decision.blockers


def test_btc_order_intent_rejected_when_delta_below_minimum() -> None:
    target = _target()

    decision = btc_target_to_cost_aware_order_intent(
        target,
        current_quantity=target.target_quantity or 0.0,
        cost_estimate=_complete_cost(),
        min_quantity=0.001,
    )

    assert decision.approved is False
    assert decision.order_intent is None
    assert "delta_quantity_below_minimum" in decision.blockers


def test_btc_order_intent_created_only_after_cost_gate_passes() -> None:
    target = _target(expected_return_bps=80.0)

    decision = btc_target_to_cost_aware_order_intent(
        target,
        current_quantity=0.0,
        cost_estimate=_complete_cost(),
        min_quantity=0.001,
        min_alpha_to_cost_ratio=1.5,
        order_type=OrderType.MARKET,
        time_in_force=TimeInForce.IOC,
    )

    assert decision.approved is True
    assert decision.blockers == []
    assert decision.order_intent is not None
    intent = decision.order_intent
    assert intent.side == OrderSide.BUY
    assert intent.quantity == pytest.approx(target.target_quantity)
    assert intent.order_type == OrderType.MARKET
    assert intent.time_in_force == TimeInForce.IOC
    assert intent.target_position_id == target.target_position_id
    assert intent.metadata["order_intent_construction_version"] == BTC_COST_AWARE_ORDER_INTENT_VERSION
    assert intent.metadata["source_boundary"] == "cost_gate_to_order_intent_no_broker_submit"
    assert intent.metadata["alpha_cost_gate"]["total_cost_bps"] == 12.0
    assert intent.metadata["alpha_cost_gate"]["required_alpha_bps"] == 18.0
    assert intent.metadata["alpha_cost_gate"]["cost_adjusted_alpha_bps"] == pytest.approx(62.0)
