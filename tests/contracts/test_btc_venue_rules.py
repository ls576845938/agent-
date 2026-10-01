from __future__ import annotations

from datetime import datetime, timezone

import pytest

from quant_crypto.oms.venue_rules import (
    BTC_VENUE_RULES_VERSION,
    BTCVenueRules,
    apply_btc_venue_rules,
    normalize_btc_price,
    normalize_btc_quantity,
)
from quant_crypto.trading_contracts import OrderIntent, OrderSide, OrderType, TimeInForce


def _rules(**overrides: object) -> BTCVenueRules:
    values = {
        "venue": "binance_usdm",
        "venue_symbol": "BTCUSDT",
        "tick_size": 0.10,
        "step_size": 0.001,
        "min_quantity": 0.001,
        "min_notional": 100.0,
        "price_precision": 2,
        "quantity_precision": 3,
        "maker_fee_bps": 2.0,
        "taker_fee_bps": 4.0,
        "funding_interval_hours": 8.0,
        "metadata": {"source": "contract_fixture"},
    }
    values.update(overrides)
    return BTCVenueRules(**values)


def _intent(side: OrderSide = OrderSide.BUY, quantity: float = 0.123456) -> OrderIntent:
    return OrderIntent(
        timestamp_utc=datetime(2026, 6, 26, 8, 0, tzinfo=timezone.utc),
        strategy_id="btc_intraday_short_cycle",
        symbol="BTCUSDT",
        side=side,
        quantity=quantity,
        order_type=OrderType.MARKET,
        time_in_force=TimeInForce.IOC,
        client_order_id="btc-venue-coid",
        target_position_id="tgt_fixture",
    )


def test_btc_price_and_quantity_normalization_use_tick_and_step_not_precision() -> None:
    assert normalize_btc_price(50000.04, 0.10, OrderSide.BUY) == pytest.approx(50000.10)
    assert normalize_btc_price(50000.04, 0.10, OrderSide.SELL) == pytest.approx(50000.00)
    assert normalize_btc_quantity(0.123456, 0.001) == pytest.approx(0.123)


def test_btc_venue_rules_approve_valid_order_and_record_execution_metadata() -> None:
    validation = apply_btc_venue_rules(
        _intent(quantity=0.123456),
        venue_rules=_rules(),
        reference_price=50_000.04,
        post_only=False,
    )

    assert validation.approved is True
    assert validation.blockers == []
    assert validation.normalized_price == pytest.approx(50_000.10)
    assert validation.normalized_quantity == pytest.approx(0.123)
    assert validation.notional == pytest.approx(6_150.0123)
    assert validation.fee_bps == 4.0

    metadata = validation.metadata
    assert metadata["venue_rules_version"] == BTC_VENUE_RULES_VERSION
    assert metadata["venue"] == "binance_usdm"
    assert metadata["venue_symbol"] == "BTCUSDT"
    assert metadata["tick_size"] == 0.10
    assert metadata["step_size"] == 0.001
    assert metadata["min_notional"] == 100.0
    assert metadata["price_precision"] == 2
    assert metadata["quantity_precision"] == 3
    assert metadata["fee_side"] == "taker"
    assert metadata["fee_bps"] == 4.0
    assert metadata["funding_interval_hours"] == 8.0
    assert metadata["trading_calendar"] == "24/7"
    assert metadata["best_execution_basis"] == "venue_rules_tick_step_min_notional_fee_calendar"


def test_btc_venue_rules_use_maker_fee_for_post_only_orders() -> None:
    validation = apply_btc_venue_rules(
        _intent(quantity=0.10),
        venue_rules=_rules(maker_fee_bps=1.5, taker_fee_bps=5.0),
        reference_price=50_000.0,
        post_only=True,
    )

    assert validation.approved is True
    assert validation.fee_bps == 1.5
    assert validation.metadata["fee_side"] == "maker"
    assert validation.metadata["fee_bps"] == 1.5


def test_btc_venue_rules_fail_closed_on_min_quantity_and_min_notional() -> None:
    validation = apply_btc_venue_rules(
        _intent(quantity=0.0014),
        venue_rules=_rules(min_quantity=0.002, min_notional=100.0),
        reference_price=50_000.0,
    )

    assert validation.approved is False
    assert validation.normalized_quantity == pytest.approx(0.001)
    assert validation.notional == pytest.approx(50.0)
    assert validation.blockers == ["btc_quantity_below_min_quantity", "btc_notional_below_min_notional"]
    assert validation.metadata["venue_rule_blockers"] == validation.blockers


def test_btc_venue_rules_reject_non_247_calendar() -> None:
    with pytest.raises(ValueError, match="24/7"):
        _rules(trading_calendar="weekday_regular")


def test_btc_venue_rules_reject_missing_positive_execution_constraints() -> None:
    with pytest.raises(ValueError, match="tick_size"):
        _rules(tick_size=0.0)
    with pytest.raises(ValueError, match="funding_interval_hours"):
        _rules(funding_interval_hours=0.0)
