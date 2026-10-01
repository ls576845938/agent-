from __future__ import annotations

from datetime import datetime, timezone

from quant_crypto.portfolio.forecast import (
    BTCForecastQuality,
    BTCRiskBudget,
    BTCRiskState,
    btc_forecast_to_target_position,
    signal_to_btc_forecast,
)
from quant_crypto.risk.liquidation import (
    BTCPerpPositionState,
    BTCReferencePriceState,
    BTCLiquidationPolicy,
    evaluate_btc_perp_liquidation_risk,
)
from quant_crypto.trading_contracts import Signal, SignalDirection


TS = datetime(2026, 6, 26, 8, 0, tzinfo=timezone.utc)


def _reference_prices(**overrides: object) -> BTCReferencePriceState:
    kwargs = {
        "observed_at_utc": TS,
        "signal_price": 100_000.0,
        "execution_price": 100_000.0,
        "mark_price": 99_950.0,
        "index_price": 99_900.0,
        "current_mark_price": 99_960.0,
        "spread_bps": 2.0,
        "cross_venue_deviation_bps": 4.0,
        "data_age_ms": 500,
        "order_book_depth_usd": 1_000_000.0,
        "source": "test",
    }
    kwargs.update(overrides)
    return BTCReferencePriceState(**kwargs)


def _policy(**overrides: object) -> BTCLiquidationPolicy:
    kwargs = {
        "max_leverage": 2.0,
        "maintenance_margin_rate": 0.005,
        "min_liquidation_buffer_bps": 2_000.0,
        "max_reference_price_age_ms": 2_000,
        "max_cross_venue_deviation_bps": 50.0,
        "max_spread_bps": 20.0,
        "min_order_book_depth_usd": 100_000.0,
    }
    kwargs.update(overrides)
    return BTCLiquidationPolicy(**kwargs)


def test_btc_perp_liquidation_risk_approves_when_mark_index_and_buffer_are_valid() -> None:
    decision = evaluate_btc_perp_liquidation_risk(
        reference_prices=_reference_prices(),
        position=BTCPerpPositionState(current_quantity=0.0, proposed_quantity=0.01, account_equity=10_000.0),
        policy=_policy(),
    )

    assert decision.approved is True
    assert decision.blockers == []
    assert decision.action == "approve"
    assert decision.liquidation_price is not None
    assert decision.liquidation_buffer_bps is not None


def test_btc_perp_liquidation_risk_blocks_missing_reference_prices_and_stale_data() -> None:
    decision = evaluate_btc_perp_liquidation_risk(
        reference_prices=_reference_prices(
            mark_price=None,
            index_price=None,
            current_mark_price=None,
            data_age_ms=10_000,
            cross_venue_deviation_bps=500.0,
            spread_bps=100.0,
            order_book_depth_usd=10_000.0,
        ),
        position=BTCPerpPositionState(current_quantity=0.0, proposed_quantity=0.01, account_equity=10_000.0),
        policy=_policy(),
    )

    assert decision.approved is False
    assert "btc_mark_price_missing" in decision.blockers
    assert "btc_index_price_missing" in decision.blockers
    assert "btc_current_mark_price_missing" in decision.blockers
    assert "btc_reference_price_stale" in decision.blockers
    assert "btc_cross_venue_deviation_breach" in decision.blockers
    assert "btc_spread_breach" in decision.blockers
    assert "btc_order_book_depth_breach" in decision.blockers


def test_btc_target_position_requires_liquidation_risk_when_budget_demands_it() -> None:
    forecast = _forecast()
    target = btc_forecast_to_target_position(
        forecast,
        risk_budget=BTCRiskBudget(
            max_btc_exposure=0.2,
            strategy_risk_budget=1.0,
            target_volatility=0.3,
            require_funding_rate=False,
            require_liquidation_risk=True,
            current_weight=0.05,
        ),
        risk_state=BTCRiskState(
            cash_fraction=0.9,
            daily_loss_pct=0.0,
            current_drawdown_pct=0.0,
            funding_rate=0.0,
            perp_risk_decision=None,
        ),
        account_equity=10_000.0,
        mark_price=100_000.0,
    )

    assert target.target_weight == 0.05
    assert target.metadata["order_generation_allowed"] is False
    assert "liquidation_risk_missing" in target.metadata["constraint_violations"]


def test_btc_target_position_reduces_when_liquidation_buffer_fails() -> None:
    forecast = _forecast()
    decision = evaluate_btc_perp_liquidation_risk(
        reference_prices=_reference_prices(),
        position=BTCPerpPositionState(current_quantity=0.01, proposed_quantity=0.5, account_equity=10_000.0),
        policy=_policy(max_leverage=1.0, min_liquidation_buffer_bps=8_000.0),
    )

    target = btc_forecast_to_target_position(
        forecast,
        risk_budget=BTCRiskBudget(
            max_btc_exposure=0.8,
            strategy_risk_budget=1.0,
            target_volatility=0.3,
            require_funding_rate=False,
            require_liquidation_risk=True,
            current_weight=0.2,
        ),
        risk_state=BTCRiskState(
            cash_fraction=0.9,
            daily_loss_pct=0.0,
            current_drawdown_pct=0.0,
            funding_rate=0.0,
            perp_risk_decision=decision,
        ),
        account_equity=10_000.0,
        mark_price=100_000.0,
    )

    assert target.target_weight == 0.0
    assert target.metadata["order_generation_allowed"] is False
    assert "btc_leverage_breach" in target.metadata["constraint_violations"]
    assert target.metadata["risk_state"]["perp_risk_decision"]["risk_model_version"] == "btc_perp_liquidation_risk_v1"


def _forecast():
    signal = Signal(
        timestamp_utc=TS,
        strategy_id="btc_trend_v0",
        symbol="BTCUSDT",
        direction=SignalDirection.LONG,
        strength=1.0,
        horizon="12x5m",
        reason="test",
    )
    return signal_to_btc_forecast(
        signal,
        quality=BTCForecastQuality(ic=0.05, sample_size=100, evidence_path="test", evidence_hash="a" * 64),
        horizon="12x5m",
    )
