from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from quant_crypto.oms.execution_quality import (
    BTC_EXECUTION_QUALITY_VERSION,
    BTCExecutionFill,
    build_btc_execution_quality_report,
)
from quant_crypto.oms.lifecycle import BTCPaperOMS
from quant_crypto.trading_contracts import OrderIntent, OrderSide, OrderType, TimeInForce


TS = datetime(2026, 6, 26, 8, 0, tzinfo=timezone.utc)


def _intent(client_order_id: str, *, side: OrderSide = OrderSide.BUY, quantity: float = 0.20) -> OrderIntent:
    return OrderIntent(
        timestamp_utc=TS,
        strategy_id="btc_intraday_short_cycle",
        symbol="BTCUSDT",
        side=side,
        quantity=quantity,
        order_type=OrderType.MARKET,
        time_in_force=TimeInForce.IOC,
        client_order_id=client_order_id,
        target_position_id=f"tgt_{client_order_id}",
        metadata={"arrival_price": 50_000.0},
    )


def _filled_order(client_order_id: str, *, quantity: float = 0.20, fill_price: float = 50_010.0):
    order = BTCPaperOMS().create_order(_intent(client_order_id, quantity=quantity))
    order.mark_risk_checked(approved=True)
    order.mark_submitted(broker_order_id=f"broker-{client_order_id}")
    order.mark_accepted(broker_order_id=f"broker-{client_order_id}")
    order.apply_fill(fill_quantity=quantity, fill_id=f"fill-{client_order_id}", price=fill_price)
    order.reconcile(metadata={"position_reconciled": True, "cash_reconciled": True})
    fill = BTCExecutionFill(
        client_order_id=client_order_id,
        fill_id=f"fill-{client_order_id}",
        filled_quantity=quantity,
        arrival_price=50_000.0,
        fill_price=fill_price,
        benchmark_price=50_020.0,
        submitted_at_utc=TS,
        filled_at_utc=TS + timedelta(milliseconds=250),
        fee=0.40,
        spread_cost=0.10,
        market_impact_cost=0.20,
        delay_cost=0.30,
    )
    return order, fill


def test_btc_execution_quality_reports_shortfall_rates_latency_and_cost_components() -> None:
    order, fill = _filled_order("coid-filled", quantity=0.20, fill_price=50_010.0)

    report = build_btc_execution_quality_report([order], [fill], opportunity_benchmark_price=50_020.0)
    payload = report.to_dict()

    assert payload["execution_quality_version"] == BTC_EXECUTION_QUALITY_VERSION
    assert payload["order_count"] == 1
    assert payload["filled_order_count"] == 1
    assert payload["requested_quantity"] == pytest.approx(0.20)
    assert payload["filled_quantity"] == pytest.approx(0.20)
    assert payload["unfilled_quantity"] == pytest.approx(0.0)
    assert payload["fill_rate"] == pytest.approx(1.0)
    assert payload["reject_rate"] == pytest.approx(0.0)
    assert payload["cancel_rate"] == pytest.approx(0.0)
    assert payload["average_latency_ms"] == pytest.approx(250.0)
    assert payload["implementation_shortfall"] == pytest.approx(2.0)
    assert payload["unfilled_opportunity_cost"] == pytest.approx(0.0)
    assert payload["fee"] == pytest.approx(0.40)
    assert payload["spread_cost"] == pytest.approx(0.10)
    assert payload["market_impact_cost"] == pytest.approx(0.20)
    assert payload["delay_cost"] == pytest.approx(0.30)
    assert payload["blocker_reasons"] == []
    assert payload["fill_details"][0]["implementation_shortfall"] == pytest.approx(2.0)


def test_btc_execution_quality_counts_partial_cancel_and_unfilled_opportunity_cost() -> None:
    oms = BTCPaperOMS()
    order = oms.create_order(_intent("coid-partial-cancel", quantity=0.20))
    order.mark_risk_checked(approved=True)
    order.mark_submitted(broker_order_id="broker-partial")
    order.mark_accepted(broker_order_id="broker-partial")
    order.apply_fill(fill_quantity=0.05, fill_id="fill-partial", price=50_005.0)
    order.request_cancel()
    order.confirm_cancelled()
    order.reconcile(metadata={"remaining_qty_cancelled": 0.15})
    fill = BTCExecutionFill(
        client_order_id="coid-partial-cancel",
        fill_id="fill-partial",
        filled_quantity=0.05,
        arrival_price=50_000.0,
        fill_price=50_005.0,
        benchmark_price=50_100.0,
        submitted_at_utc=TS,
        filled_at_utc=TS + timedelta(milliseconds=100),
    )

    report = build_btc_execution_quality_report([order], [fill], opportunity_benchmark_price=50_100.0)

    assert report.filled_order_count == 0
    assert report.cancelled_order_count == 1
    assert report.fill_rate == pytest.approx(0.25)
    assert report.cancel_rate == pytest.approx(1.0)
    assert report.unfilled_quantity == pytest.approx(0.15)
    assert report.unfilled_opportunity_cost == pytest.approx(15.0)
    assert report.implementation_shortfall == pytest.approx(0.25)
    assert report.blocker_reasons == []


def test_btc_execution_quality_counts_reject_rate_from_lifecycle_history() -> None:
    order = BTCPaperOMS().create_order(_intent("coid-reject", quantity=0.20))
    order.mark_risk_checked(approved=True)
    order.mark_submitted(broker_order_id="broker-reject")
    order.reject(reject_code="MIN_NOTIONAL", reject_reason="min notional", next_action="do_not_retry")
    order.reconcile(metadata={"reject_acknowledged": True})

    report = build_btc_execution_quality_report([order], [], opportunity_benchmark_price=50_100.0)

    assert report.rejected_order_count == 1
    assert report.reject_rate == pytest.approx(1.0)
    assert report.fill_rate == pytest.approx(0.0)
    assert report.unfilled_quantity == pytest.approx(0.20)
    assert report.unfilled_opportunity_cost == pytest.approx(20.0)
    assert report.blocker_reasons == []


def test_btc_execution_quality_blocks_unreconciled_orders() -> None:
    order = BTCPaperOMS().create_order(_intent("coid-open", quantity=0.20))
    order.mark_risk_checked(approved=True)
    order.mark_submitted(broker_order_id="broker-open")
    order.mark_accepted(broker_order_id="broker-open")

    report = build_btc_execution_quality_report([order], [], opportunity_benchmark_price=50_100.0)

    assert "btc_execution_quality_unreconciled_orders" in report.blocker_reasons


def test_btc_execution_quality_blocks_fill_without_matching_order() -> None:
    fill = BTCExecutionFill(
        client_order_id="missing-order",
        fill_id="orphan-fill",
        filled_quantity=0.01,
        arrival_price=50_000.0,
        fill_price=50_010.0,
        benchmark_price=50_020.0,
        submitted_at_utc=TS,
        filled_at_utc=TS + timedelta(milliseconds=10),
    )

    report = build_btc_execution_quality_report([], [fill], opportunity_benchmark_price=50_020.0)

    assert "btc_execution_quality_no_orders" in report.blocker_reasons
    assert "btc_execution_quality_fill_without_order" in report.blocker_reasons
