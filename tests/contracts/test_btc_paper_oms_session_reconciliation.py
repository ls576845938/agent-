from __future__ import annotations

from datetime import datetime, timedelta, timezone

from quant_crypto.monitoring.artifact_schema import validate_btc_artifact_schema
from quant_crypto.oms.execution_quality import BTCExecutionFill
from quant_crypto.oms.lifecycle import BTCPaperOMS
from quant_crypto.oms.session_reconciliation import build_btc_paper_oms_session_reconciliation
from quant_crypto.trading_contracts import OrderIntent, OrderSide, OrderType, TimeInForce


TS = datetime(2026, 6, 26, 8, 0, tzinfo=timezone.utc)
HASH = "a" * 64


def _intent(client_order_id: str = "coid_1") -> OrderIntent:
    return OrderIntent(
        timestamp_utc=TS,
        strategy_id="btc_strategy",
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        quantity=0.1,
        order_type=OrderType.MARKET,
        time_in_force=TimeInForce.IOC,
        client_order_id=client_order_id,
        metadata={"arrival_price": 100_000.0},
    )


def _filled_reconciled_order():
    order = BTCPaperOMS().create_order(_intent())
    order.mark_risk_checked(approved=True)
    order.mark_submitted(broker_order_id="simulated")
    order.mark_accepted(broker_order_id="simulated")
    order.apply_fill(fill_quantity=0.1, fill_id="fill_1", price=100_010.0, timestamp_utc=TS + timedelta(seconds=1))
    order.reconcile()
    return order


def test_btc_paper_oms_session_reconciliation_accepts_clean_session() -> None:
    order = _filled_reconciled_order()
    fill = BTCExecutionFill(
        client_order_id=order.client_order_id,
        fill_id="fill_1",
        filled_quantity=0.1,
        arrival_price=100_000.0,
        fill_price=100_010.0,
        benchmark_price=100_020.0,
        submitted_at_utc=TS,
        filled_at_utc=TS + timedelta(seconds=1),
        fee=0.5,
    )

    payload = build_btc_paper_oms_session_reconciliation(
        session_id="session_1",
        orders=[order],
        fills=[fill],
        ledger_hash=HASH,
        generated_at_utc=TS,
        opportunity_benchmark_price=100_020.0,
    )

    assert payload["status"] == "complete"
    assert payload["decision"] == "paper_oms_session_reconciled"
    assert payload["real_order_submitted"] is False
    assert payload["private_endpoint_used"] is False
    assert payload["order_endpoint_used"] is False
    assert payload["execution_quality"]["fill_rate"] == 1.0
    assert payload["unreconciled_order_count"] == 0
    assert payload["unreconciled_client_order_ids"] == []
    assert validate_btc_artifact_schema(payload) == []


def test_btc_paper_oms_session_reconciliation_blocks_unreconciled_order_and_missing_ledger_hash() -> None:
    order = BTCPaperOMS().create_order(_intent())
    order.mark_risk_checked(approved=True)

    payload = build_btc_paper_oms_session_reconciliation(
        session_id="session_1",
        orders=[order],
        fills=[],
        ledger_hash="",
        generated_at_utc=TS,
        opportunity_benchmark_price=100_000.0,
    )

    assert payload["status"] == "blocked"
    assert payload["unreconciled_order_count"] == 1
    assert payload["unreconciled_client_order_ids"] == ["coid_1"]
    assert "btc_paper_oms_session_ledger_hash_missing" in payload["blockers"]
    assert "btc_paper_oms_session_unreconciled_order_lifecycle" in payload["blockers"]


def test_btc_paper_oms_session_reconciliation_blocks_fill_without_order() -> None:
    fill = BTCExecutionFill(
        client_order_id="unknown",
        fill_id="fill_unknown",
        filled_quantity=0.1,
        arrival_price=100_000.0,
        fill_price=100_010.0,
        benchmark_price=100_020.0,
        submitted_at_utc=TS,
        filled_at_utc=TS + timedelta(seconds=1),
    )

    payload = build_btc_paper_oms_session_reconciliation(
        session_id="session_1",
        orders=[],
        fills=[fill],
        ledger_hash=HASH,
        generated_at_utc=TS,
        opportunity_benchmark_price=100_020.0,
    )

    assert payload["status"] == "blocked"
    assert "btc_paper_oms_session_no_orders" in payload["blockers"]
    assert "btc_paper_oms_session_fill_without_order" in payload["blockers"]


def test_btc_paper_oms_session_reconciliation_accepts_partial_cancel_reject_and_expire_mix() -> None:
    partial_cancel = BTCPaperOMS().create_order(_intent("coid_partial_cancel"))
    partial_cancel.mark_risk_checked(approved=True)
    partial_cancel.mark_submitted(broker_order_id="simulated-partial")
    partial_cancel.mark_accepted(broker_order_id="simulated-partial")
    partial_cancel.apply_fill(
        fill_quantity=0.04,
        fill_id="fill_partial",
        price=100_005.0,
        timestamp_utc=TS + timedelta(seconds=1),
    )
    partial_cancel.request_cancel(reason="cancel_remaining")
    partial_cancel.confirm_cancelled()
    partial_cancel.reconcile(metadata={"remaining_qty_cancelled": 0.06})

    rejected = BTCPaperOMS().create_order(_intent("coid_rejected"))
    rejected.mark_risk_checked(approved=True)
    rejected.mark_submitted(broker_order_id="simulated-reject")
    rejected.reject(
        reject_code="MIN_NOTIONAL",
        reject_reason="min notional",
        next_action="do_not_retry",
    )
    rejected.reconcile(metadata={"reject_acknowledged": True})

    expired = BTCPaperOMS().create_order(_intent("coid_expired"))
    expired.mark_risk_checked(approved=True)
    expired.mark_submitted(broker_order_id="simulated-expire")
    expired.mark_accepted(broker_order_id="simulated-expire")
    expired.expire(reason="time_in_force_expired")
    expired.reconcile(metadata={"expiry_acknowledged": True})

    fill = BTCExecutionFill(
        client_order_id=partial_cancel.client_order_id,
        fill_id="fill_partial",
        filled_quantity=0.04,
        arrival_price=100_000.0,
        fill_price=100_005.0,
        benchmark_price=100_010.0,
        submitted_at_utc=TS,
        filled_at_utc=TS + timedelta(seconds=1),
        fee=0.25,
    )

    payload = build_btc_paper_oms_session_reconciliation(
        session_id="session_mixed_lifecycle",
        orders=[partial_cancel, rejected, expired],
        fills=[fill],
        ledger_hash=HASH,
        generated_at_utc=TS,
        opportunity_benchmark_price=100_010.0,
    )

    assert payload["status"] == "complete"
    assert payload["decision"] == "paper_oms_session_reconciled"
    assert payload["order_count"] == 3
    assert payload["fill_count"] == 1
    assert payload["unreconciled_order_count"] == 0
    assert payload["unreconciled_client_order_ids"] == []
    assert payload["missing_fill_client_order_ids"] == []
    assert payload["unknown_fill_client_order_ids"] == []
    assert payload["execution_quality"]["cancelled_order_count"] == 1
    assert payload["execution_quality"]["rejected_order_count"] == 1
    assert payload["execution_quality"]["expired_order_count"] == 1
    assert 0.0 < payload["execution_quality"]["fill_rate"] < 1.0
    assert payload["execution_quality"]["fee"] == 0.25
    assert payload["blockers"] == []
    assert payload["real_order_submitted"] is False
    assert payload["private_endpoint_used"] is False
    assert payload["order_endpoint_used"] is False
    assert validate_btc_artifact_schema(payload) == []
