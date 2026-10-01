from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from quant_crypto.portfolio.forecast import (
    BTC_TARGET_FROM_FORECAST_VERSION,
    BTCRiskBudget,
    BTCRiskState,
    BTCForecastQuality,
    btc_forecast_to_target_position,
    signal_to_btc_forecast,
)
from quant_crypto.trading_contracts import Signal, SignalDirection


def _signal(direction: SignalDirection = SignalDirection.LONG, strength: float = 0.8) -> Signal:
    return Signal(
        timestamp_utc=datetime(2026, 6, 26, 8, 0, tzinfo=timezone.utc),
        strategy_id="btc_intraday_short_cycle",
        symbol="btcusdt",
        direction=direction,
        strength=strength,
        horizon="60m",
        reason="contract test",
    )


def _quality(**overrides: object) -> BTCForecastQuality:
    values = {
        "ic": 0.08,
        "hit_rate": 0.58,
        "sample_size": 120,
        "evidence_path": "artifacts/btc_trial_registry/latest/btc_trial_registry.json",
        "evidence_hash": "sha256:test",
    }
    values.update(overrides)
    return BTCForecastQuality(**values)


def _risk_state(**overrides: object) -> BTCRiskState:
    values = {
        "cash_fraction": 0.80,
        "daily_loss_pct": 0.0,
        "current_drawdown_pct": 0.0,
        "cooldown_until_utc": None,
        "funding_rate": 0.0001,
        "exchange_available": True,
        "data_anomaly": False,
    }
    values.update(overrides)
    return BTCRiskState(**values)


def _high_confidence_forecast():
    return signal_to_btc_forecast(
        _signal(strength=1.0),
        quality=_quality(ic=0.20, hit_rate=None, sample_size=200),
        horizon="60m",
    )


def test_signal_to_btc_forecast_requires_predictive_quality() -> None:
    with pytest.raises(ValueError, match="IC or hit-rate evidence"):
        signal_to_btc_forecast(
            _signal(),
            quality=BTCForecastQuality(),
            horizon="60m",
        )


def test_signal_to_btc_forecast_records_required_forecast_contract() -> None:
    signal = _signal()

    forecast = signal_to_btc_forecast(
        signal,
        quality=_quality(),
        horizon="60m",
        unit="bps",
        expiry_bars=12,
        bar_minutes=5,
        max_expected_return_bps=90.0,
    )

    assert forecast.symbol == "BTCUSDT"
    assert forecast.horizon == "60m"
    assert forecast.unit == "bps"
    assert forecast.confidence > 0.0
    assert forecast.expiry_utc == signal.timestamp_utc + timedelta(minutes=60)
    assert forecast.expected_return_bps == pytest.approx(72.0)
    assert forecast.source_signal_id == signal.signal_id

    metadata = forecast.to_metadata()
    assert metadata["forecast_horizon"] == "60m"
    assert metadata["forecast_unit"] == "bps"
    assert metadata["forecast_confidence"] == forecast.confidence
    assert metadata["forecast_expiry_utc"] == forecast.expiry_utc.isoformat()
    assert metadata["forecast_ic"] == 0.08
    assert metadata["forecast_hit_rate"] == 0.58
    assert metadata["forecast_sample_size"] == 120


def test_btc_target_position_requires_forecast_not_signal() -> None:
    with pytest.raises(ValueError, match="requires a Forecast"):
        btc_forecast_to_target_position(
            None,
            risk_budget=BTCRiskBudget(
                max_btc_exposure=0.25,
                strategy_risk_budget=0.5,
                target_volatility=0.20,
            ),
            risk_state=_risk_state(),
            account_equity=25_000.0,
            mark_price=50_000.0,
        )


def test_btc_target_position_requires_current_risk_state() -> None:
    with pytest.raises(ValueError, match="current risk state"):
        btc_forecast_to_target_position(
            _high_confidence_forecast(),
            risk_budget=BTCRiskBudget(
                max_btc_exposure=0.25,
                strategy_risk_budget=0.5,
                target_volatility=0.20,
            ),
            risk_state=None,
            account_equity=25_000.0,
            mark_price=50_000.0,
        )


def test_btc_forecast_to_target_position_records_risk_cost_and_constraints() -> None:
    forecast = _high_confidence_forecast()

    target = btc_forecast_to_target_position(
        forecast,
        risk_budget=BTCRiskBudget(
            max_btc_exposure=0.25,
            strategy_risk_budget=0.50,
            target_volatility=0.20,
            current_weight=0.0,
            max_turnover=1.0,
            estimated_round_trip_cost_bps=18.0,
            min_cash_fraction=0.10,
            max_daily_loss_pct=0.03,
            max_drawdown_pct=0.12,
            max_abs_funding_rate=0.001,
        ),
        risk_state=_risk_state(),
        account_equity=25_000.0,
        mark_price=50_000.0,
    )

    assert target.symbol == "BTCUSDT"
    assert target.target_weight == pytest.approx(0.25)
    assert target.target_quantity == pytest.approx(0.125)
    assert target.signal_id == forecast.source_signal_id

    metadata = target.metadata
    assert metadata["target_construction_version"] == BTC_TARGET_FROM_FORECAST_VERSION
    assert metadata["forecast_id"] == forecast.forecast_id
    assert metadata["forecast_horizon"] == "60m"
    assert metadata["forecast_unit"] == "bps"
    assert metadata["forecast_confidence"] == 1.0
    assert metadata["target_notional"] == pytest.approx(6_250.0)
    assert metadata["expected_volatility"] == 0.20
    assert metadata["risk_budget"] == 0.50
    assert metadata["max_btc_exposure"] == 0.25
    assert metadata["min_cash_fraction"] == 0.10
    assert metadata["max_daily_loss_pct"] == 0.03
    assert metadata["max_drawdown_pct"] == 0.12
    assert metadata["max_abs_funding_rate"] == 0.001
    assert metadata["risk_state"]["funding_rate"] == 0.0001
    assert metadata["risk_state"]["perp_risk_decision"] is None
    assert metadata["risk_state"]["perp_risk_decision_status"] == "not_required_spot_or_unlevered_path"
    assert metadata["perpetual_risk_policy"] == {
        "perpetual_allowed": False,
        "liquidation_risk_required": False,
        "funding_rate_required": True,
        "status": "not_applicable_spot_or_unlevered_path",
        "reason": "current BTC target path is spot or unlevered; perpetual risk is not part of promotion evidence",
    }
    assert metadata["order_generation_allowed"] is True
    assert metadata["turnover"] == pytest.approx(0.25)
    assert metadata["cost_estimate"]["round_trip_cost_bps"] == 18.0
    assert metadata["cost_estimate"]["estimated_cost_bps"] == pytest.approx(4.5)
    assert metadata["constraint_violations"] == ["max_btc_exposure"]
    assert metadata["rebalance_reason"] == "forecast_to_target_position"
    assert metadata["source_boundary"] == "forecast_to_target_position_no_order_intent"


def test_btc_forecast_to_target_position_caps_turnover() -> None:
    forecast = _high_confidence_forecast()

    target = btc_forecast_to_target_position(
        forecast,
        risk_budget=BTCRiskBudget(
            max_btc_exposure=0.50,
            strategy_risk_budget=0.50,
            target_volatility=0.20,
            current_weight=0.0,
            max_turnover=0.10,
            estimated_round_trip_cost_bps=20.0,
        ),
        risk_state=_risk_state(),
        account_equity=25_000.0,
        mark_price=50_000.0,
    )

    assert target.target_weight == pytest.approx(0.10)
    assert target.metadata["turnover"] == pytest.approx(0.10)
    assert target.metadata["turnover_scale"] == pytest.approx(0.20)
    assert target.metadata["cost_estimate"]["estimated_cost_bps"] == pytest.approx(2.0)
    assert target.metadata["constraint_violations"] == ["max_turnover"]


def test_btc_forecast_to_target_position_caps_cash_floor() -> None:
    forecast = _high_confidence_forecast()

    target = btc_forecast_to_target_position(
        forecast,
        risk_budget=BTCRiskBudget(
            max_btc_exposure=0.95,
            strategy_risk_budget=0.95,
            target_volatility=0.20,
            current_weight=0.0,
            max_turnover=1.0,
            min_cash_fraction=0.30,
            estimated_round_trip_cost_bps=10.0,
        ),
        risk_state=_risk_state(),
        account_equity=25_000.0,
        mark_price=50_000.0,
    )

    assert target.target_weight == pytest.approx(0.70)
    assert target.metadata["target_notional"] == pytest.approx(17_500.0)
    assert target.metadata["constraint_violations"] == ["cash_floor"]
    assert target.metadata["order_generation_allowed"] is True


@pytest.mark.parametrize(
    ("risk_state", "expected_violation", "expected_reason"),
    [
        (_risk_state(daily_loss_pct=0.031), "daily_loss_stop", "risk_daily_loss_stop"),
        (_risk_state(current_drawdown_pct=0.121), "drawdown_stop", "risk_drawdown_stop"),
        (
            _risk_state(cooldown_until_utc=datetime(2026, 6, 26, 8, 30, tzinfo=timezone.utc)),
            "cooldown_active",
            "risk_cooldown_active",
        ),
        (_risk_state(funding_rate=None), "funding_rate_missing", "risk_funding_rate_missing"),
        (_risk_state(funding_rate=0.002), "funding_risk", "risk_funding_risk"),
    ],
)
def test_btc_risk_stops_flatten_target_and_block_order_generation(
    risk_state: BTCRiskState,
    expected_violation: str,
    expected_reason: str,
) -> None:
    target = btc_forecast_to_target_position(
        _high_confidence_forecast(),
        risk_budget=BTCRiskBudget(
            max_btc_exposure=0.50,
            strategy_risk_budget=0.50,
            target_volatility=0.20,
            current_weight=0.20,
            max_turnover=1.0,
            max_daily_loss_pct=0.03,
            max_drawdown_pct=0.12,
            max_abs_funding_rate=0.001,
        ),
        risk_state=risk_state,
        account_equity=25_000.0,
        mark_price=50_000.0,
    )

    assert target.target_weight == 0.0
    assert expected_violation in target.metadata["constraint_violations"]
    assert target.metadata["rebalance_reason"] == expected_reason
    assert target.metadata["order_generation_allowed"] is False


@pytest.mark.parametrize(
    ("risk_state", "expected_violation", "expected_reason"),
    [
        (_risk_state(exchange_available=False), "exchange_outage", "risk_exchange_outage_hold"),
        (_risk_state(data_anomaly=True), "data_anomaly", "risk_data_anomaly_hold"),
    ],
)
def test_btc_exchange_or_data_anomaly_holds_current_weight_and_blocks_orders(
    risk_state: BTCRiskState,
    expected_violation: str,
    expected_reason: str,
) -> None:
    target = btc_forecast_to_target_position(
        _high_confidence_forecast(),
        risk_budget=BTCRiskBudget(
            max_btc_exposure=0.50,
            strategy_risk_budget=0.50,
            target_volatility=0.20,
            current_weight=0.20,
            max_turnover=1.0,
        ),
        risk_state=risk_state,
        account_equity=25_000.0,
        mark_price=50_000.0,
    )

    assert target.target_weight == pytest.approx(0.20)
    assert target.metadata["turnover"] == pytest.approx(0.0)
    assert expected_violation in target.metadata["constraint_violations"]
    assert target.metadata["rebalance_reason"] == expected_reason
    assert target.metadata["order_generation_allowed"] is False
