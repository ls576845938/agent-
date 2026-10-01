from __future__ import annotations

from datetime import datetime, timezone

import pytest

from quant_crypto.oms.lifecycle import (
    BTC_PAPER_OMS_LIFECYCLE_VERSION,
    BTCPaperOMS,
    BTCPaperOrderStatus,
)
from quant_crypto.trading_contracts import OrderIntent, OrderSide, OrderType, TimeInForce


def _intent(client_order_id: str = "btc-paper-coid-001", quantity: float = 0.25) -> OrderIntent:
    return OrderIntent(
        timestamp_utc=datetime(2026, 6, 26, 8, 0, tzinfo=timezone.utc),
        strategy_id="btc_intraday_short_cycle",
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        quantity=quantity,
        order_type=OrderType.MARKET,
        time_in_force=TimeInForce.IOC,
        target_position_id="tgt_fixture",
        client_order_id=client_order_id,
        metadata={"source_boundary": "cost_gate_to_order_intent_no_broker_submit"},
    )


def test_btc_paper_oms_rejects_duplicate_client_order_id() -> None:
    oms = BTCPaperOMS()
    oms.create_order(_intent("same-coid"))

    with pytest.raises(ValueError, match="duplicate_client_order_id"):
        oms.create_order(_intent("same-coid"))


def test_btc_paper_order_records_full_fill_lifecycle_and_history() -> None:
    order = BTCPaperOMS().create_order(_intent(quantity=0.25))

    order.mark_risk_checked(approved=True)
    order.mark_submitted(broker_order_id="paper-broker-1")
    order.mark_accepted(broker_order_id="paper-broker-1")
    order.apply_fill(fill_quantity=0.10, fill_id="fill-1", price=50_000.0)
    order.apply_fill(fill_quantity=0.15, fill_id="fill-2", price=50_010.0)
    order.reconcile(metadata={"position_reconciled": True, "cash_reconciled": True})

    payload = order.to_dict()
    assert payload["lifecycle_version"] == BTC_PAPER_OMS_LIFECYCLE_VERSION
    assert payload["client_order_id"] == "btc-paper-coid-001"
    assert payload["status"] == "reconciled"
    assert payload["filled_quantity"] == pytest.approx(0.25)
    assert payload["remaining_quantity"] == pytest.approx(0.0)
    assert [event["status"] for event in payload["events"]] == [
        "created",
        "risk_checked",
        "submitted",
        "accepted",
        "partially_filled",
        "filled",
        "reconciled",
    ]


def test_btc_paper_order_rejects_invalid_lifecycle_transition() -> None:
    order = BTCPaperOMS().create_order(_intent())

    with pytest.raises(ValueError, match="created -> submitted"):
        order.mark_submitted(broker_order_id="paper-broker-1")


def test_btc_paper_order_requires_status_query_before_retry_after_unknown_submit() -> None:
    order = BTCPaperOMS().create_order(_intent())
    order.mark_risk_checked(approved=True)
    order.mark_submitted(broker_order_id="paper-broker-timeout", unknown_outcome=True)

    assert order.status == BTCPaperOrderStatus.UNKNOWN
    assert order.events[-1].metadata["retry_allowed_without_status_query"] is False

    with pytest.raises(ValueError, match="unknown -> submitted"):
        order.mark_submitted(broker_order_id="paper-broker-timeout-retry")


def test_btc_paper_order_cancel_request_is_separate_from_cancel_confirmation() -> None:
    order = BTCPaperOMS().create_order(_intent(quantity=0.25))
    order.mark_risk_checked(approved=True)
    order.mark_submitted(broker_order_id="paper-broker-1")
    order.mark_accepted(broker_order_id="paper-broker-1")
    order.request_cancel()

    assert order.status == BTCPaperOrderStatus.CANCEL_REQUESTED
    assert order.remaining_quantity == pytest.approx(0.25)

    order.apply_fill(fill_quantity=0.05, fill_id="late-fill", price=50_020.0)
    assert order.status == BTCPaperOrderStatus.PARTIALLY_FILLED
    assert order.remaining_quantity == pytest.approx(0.20)

    order.request_cancel(reason="cancel_remaining")
    order.confirm_cancelled()
    order.reconcile(metadata={"remaining_qty_cancelled": 0.20})

    assert order.status == BTCPaperOrderStatus.RECONCILED
    assert [event.status.value for event in order.events][-5:] == [
        "cancel_requested",
        "partially_filled",
        "cancel_requested",
        "cancelled",
        "reconciled",
    ]


def test_btc_paper_order_reject_records_required_reject_audit_fields() -> None:
    order = BTCPaperOMS().create_order(_intent())
    order.mark_risk_checked(approved=True)
    order.mark_submitted(broker_order_id="paper-broker-1")
    order.reject(
        reject_code="MIN_NOTIONAL",
        reject_reason="min notional rejected",
        risk_state={"cash_fraction": 0.8},
        exchange_response={"code": "-1013", "msg": "Filter failure: MIN_NOTIONAL"},
        next_action="do_not_retry_rebuild_target",
    )
    order.reconcile(metadata={"reject_acknowledged": True})

    payload = order.to_dict()
    assert payload["status"] == "reconciled"
    reject = payload["reject_record"]
    assert reject["reject_code"] == "MIN_NOTIONAL"
    assert reject["reject_reason"] == "min notional rejected"
    assert reject["original_order_intent_id"] == order.order_intent.order_intent_id
    assert reject["risk_state"] == {"cash_fraction": 0.8}
    assert reject["exchange_response"]["code"] == "-1013"
    assert reject["next_action"] == "do_not_retry_rebuild_target"


def test_btc_paper_order_cannot_reconcile_non_terminal_external_status() -> None:
    order = BTCPaperOMS().create_order(_intent())
    order.mark_risk_checked(approved=True)
    order.mark_submitted(broker_order_id="paper-broker-1")
    order.mark_accepted(broker_order_id="paper-broker-1")

    with pytest.raises(ValueError, match="terminal external statuses"):
        order.reconcile()
