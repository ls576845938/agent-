from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jsonschema
import pytest

from quant_us.live.ibkr_paper_reconciliation import (
    CashLedgerRecord,
    FillLedgerRecord,
    IBKRAccountSnapshot,
    IBKRBrokerSnapshot,
    IBKRExecutionSnapshot,
    IBKROpenOrderSnapshot,
    IBKRPositionSnapshot,
    OMSOrderLifecycleRecord,
    PositionLedgerRecord,
    reconcile_ibkr_paper_snapshot,
)


UTC = timezone.utc
HEAD = "d3f1e3f7f770bfdf35336257cf1eaecc18f3d6b6"
RUN_ID = "ibkr-reconciliation-fake-run-01"
ACCOUNT_HASH = "sha256:" + "a" * 64
CAPTURED_AT = datetime(2026, 8, 6, 1, 0, tzinfo=UTC)


def _fill(
    execution_id: str = "exec-1",
    *,
    sequence: int = 1,
    quantity: float = 10.0,
    price: float = 100.0,
    commission: float = 1.0,
) -> FillLedgerRecord:
    return FillLedgerRecord(
        execution_id=execution_id,
        order_id="order-1",
        client_order_id="client-1",
        broker_order_id="broker-order-1",
        symbol="AAPL",
        side="buy",
        quantity=quantity,
        price=price,
        commission=commission,
        sequence=sequence,
        executed_at=CAPTURED_AT,
    )


def _broker_fill(fill: FillLedgerRecord) -> IBKRExecutionSnapshot:
    return IBKRExecutionSnapshot(
        execution_id=fill.execution_id,
        order_id=fill.order_id,
        client_order_id=fill.client_order_id,
        broker_order_id=fill.broker_order_id,
        symbol=fill.symbol,
        side=fill.side,
        quantity=fill.quantity,
        price=fill.price,
        commission=fill.commission,
        sequence=fill.sequence,
        executed_at=fill.executed_at,
    )


def _order(status: str = "filled", quantity: float = 10.0) -> OMSOrderLifecycleRecord:
    return OMSOrderLifecycleRecord(
        order_id="order-1",
        client_order_id="client-1",
        broker_order_id="broker-order-1",
        symbol="AAPL",
        side="buy",
        quantity=quantity,
        status=status,
        sequence=2,
        updated_at=CAPTURED_AT,
    )


def _snapshot(
    *,
    status: str = "filled",
    quantity: float = 10.0,
    cash: float = 8_999.0,
    commission: float = 1.0,
    fills: tuple[IBKRExecutionSnapshot, ...] | None = None,
    open_orders: tuple[IBKROpenOrderSnapshot, ...] = (),
    positions: tuple[IBKRPositionSnapshot, ...] | None = None,
    sequence: int = 1,
    reconnect: bool = False,
    replay: bool = False,
) -> IBKRBrokerSnapshot:
    if fills is None:
        fills = (_broker_fill(_fill(quantity=quantity, commission=commission)),)
    if positions is None:
        positions = (IBKRPositionSnapshot("AAPL", quantity, 100.0),) if quantity else ()
    return IBKRBrokerSnapshot(
        snapshot_id="snapshot-1",
        sequence=sequence,
        captured_at=CAPTURED_AT,
        account=IBKRAccountSnapshot(
            account_hash=ACCOUNT_HASH,
            cash=cash,
            commission_total=commission,
        ),
        positions=positions,
        open_orders=open_orders,
        fills=fills,
        reconnect=reconnect,
        replay=replay,
    )


def _reconcile(
    snapshot: IBKRBrokerSnapshot,
    *,
    order: OMSOrderLifecycleRecord | None = None,
    fills: tuple[FillLedgerRecord, ...] | None = None,
    positions: tuple[PositionLedgerRecord, ...] | None = None,
    cash: float = 8_999.0,
    commission: float = 1.0,
    **kwargs: object,
):
    fill_records = fills if fills is not None else (_fill(),)
    position_records = positions if positions is not None else (
        (PositionLedgerRecord("AAPL", 10.0, 100.0),) if fill_records else ()
    )
    return reconcile_ibkr_paper_snapshot(
        snapshot,
        oms_orders=() if order is None else (order,),
        fill_ledger=fill_records,
        position_ledger=position_records,
        cash_ledger=(CashLedgerRecord(cash_balance=cash, commission_total=commission),),
        current_head=HEAD,
        run_id=RUN_ID,
        account_hash=ACCOUNT_HASH,
        now=CAPTURED_AT,
        **kwargs,
    )


def test_fully_filled_order_reconciles_cleanly_and_stays_read_only() -> None:
    report = _reconcile(_snapshot(), order=_order())

    assert report.status == "clean"
    assert report.decision == "allow_new_orders"
    assert report.fail_closed is False
    assert report.block_new_orders is False
    assert report.fills["matched"][0]["execution_id"] == "exec-1"
    assert report.orders["matched"][0]["match_status"] == "terminal_not_in_open_snapshot"
    assert report.positions["drifts"] == []
    assert report.cash["matched"] is True
    assert all(value is False for value in report.safety_flags.values())


def test_partial_fill_matches_open_order_and_ledger_values() -> None:
    partial = _fill(quantity=5.0, commission=0.5)
    report = _reconcile(
        _snapshot(
            status="partially_filled",
            quantity=5.0,
            cash=9_499.5,
            commission=0.5,
            fills=(_broker_fill(partial),),
            open_orders=(
                IBKROpenOrderSnapshot(
                    order_id="order-1",
                    client_order_id="client-1",
                    broker_order_id="broker-order-1",
                    symbol="AAPL",
                    side="buy",
                    quantity=10.0,
                    status="partially_filled",
                    filled_quantity=5.0,
                ),
            ),
            positions=(IBKRPositionSnapshot("AAPL", 5.0, 100.0),),
        ),
        order=_order("partially_filled"),
        fills=(partial,),
        positions=(PositionLedgerRecord("AAPL", 5.0, 100.0),),
        cash=9_499.5,
        commission=0.5,
    )

    assert report.block_new_orders is False
    assert report.orders["status_drift"] == []
    assert report.fills["unmatched_local"] == []


@pytest.mark.parametrize("status", ["rejected", "cancelled"])
def test_rejected_and_cancelled_terminal_orders_are_clean_without_open_order(
    status: str,
) -> None:
    empty_snapshot = _snapshot(
        status=status,
        quantity=0.0,
        cash=10_000.0,
        commission=0.0,
        fills=(),
        positions=(),
    )
    report = _reconcile(
        empty_snapshot,
        order=_order(status, quantity=10.0),
        fills=(),
        positions=(),
        cash=10_000.0,
        commission=0.0,
    )

    assert report.status == "clean"
    assert report.block_new_orders is False
    assert report.orders["unmatched_local"] == []
    assert report.orders["unmatched_broker"] == []


def test_duplicate_execution_is_reported_and_fail_closed() -> None:
    fill = _broker_fill(_fill())
    report = _reconcile(
        _snapshot(fills=(fill, fill)),
        order=_order(),
    )

    assert report.block_new_orders is True
    assert "duplicate_execution" in report.blockers
    assert report.fills["duplicates"][0]["source"] == "broker"
    assert report.fills["duplicates"][0]["count"] == 2


def test_execution_out_of_order_is_detected_from_injected_sequence() -> None:
    first = _fill("exec-1", sequence=1, quantity=5.0, commission=0.5)
    second = _fill("exec-2", sequence=2, quantity=5.0, commission=0.5)
    report = _reconcile(
        _snapshot(
            fills=(_broker_fill(second), _broker_fill(first)),
            positions=(IBKRPositionSnapshot("AAPL", 10.0, 100.0),),
        ),
        order=_order(),
        fills=(first, second),
        positions=(PositionLedgerRecord("AAPL", 10.0, 100.0),),
        cash=8_999.0,
        commission=1.0,
    )

    assert report.block_new_orders is True
    assert "execution_out_of_order" in report.blockers
    assert report.fills["out_of_order"] is True


def test_reconnect_repeated_snapshot_is_a_replay_blocker() -> None:
    report = _reconcile(
        _snapshot(sequence=7, reconnect=True),
        order=_order(),
        last_snapshot_sequence=7,
    )

    assert report.block_new_orders is True
    assert "snapshot_replayed" in report.replay_blockers
    assert "reconnect_replayed_snapshot" in report.replay_blockers


def test_stale_missing_sequence_and_restart_baseline_are_explicit_blockers() -> None:
    stale = replace(_snapshot(), captured_at=CAPTURED_AT - timedelta(minutes=6))
    stale_report = _reconcile(stale, order=_order())
    assert stale_report.snapshot["stale_snapshot"] is True
    assert "stale_snapshot" in stale_report.blockers

    missing_sequence = replace(_snapshot(), sequence=None)
    missing_report = _reconcile(missing_sequence, order=_order())
    assert missing_report.snapshot["missing_sequence"] is True
    assert "snapshot_sequence_missing" in missing_report.blockers

    restart_report = _reconcile(_snapshot(), order=_order(), restart=True)
    assert "restart_sequence_baseline_missing" in restart_report.restart_blockers
    assert "restart_execution_baseline_missing" in restart_report.restart_blockers


def test_missing_local_order_and_missing_local_fill_are_distinct_blockers() -> None:
    open_order = IBKROpenOrderSnapshot(
        order_id="order-1",
        client_order_id="client-1",
        broker_order_id="broker-order-1",
        symbol="AAPL",
        side="buy",
        quantity=10.0,
        status="submitted",
    )
    missing_order = _reconcile(
        _snapshot(
            status="submitted",
            quantity=0.0,
            cash=10_000.0,
            commission=0.0,
            fills=(),
            positions=(),
            open_orders=(open_order,),
        ),
        order=None,
        fills=(),
        positions=(),
        cash=10_000.0,
        commission=0.0,
    )
    assert "order_unmatched_broker" in missing_order.blockers
    assert missing_order.orders["unmatched_broker"]

    # The broker has the execution, but the local fill ledger is empty.
    missing_fill = _reconcile(_snapshot(), order=_order(), fills=())
    assert "fill_unmatched_broker" in missing_fill.blockers
    assert missing_fill.fills["unmatched_broker"]


def test_position_and_cash_drift_block_new_orders_without_repair() -> None:
    report = _reconcile(
        _snapshot(
            cash=8_998.0,
            positions=(IBKRPositionSnapshot("AAPL", 11.0, 101.0),),
        ),
        order=_order(),
    )

    assert report.block_new_orders is True
    assert "position_quantity_drift" in report.blockers
    assert "position_average_cost_drift" in report.blockers
    assert "cash_drift" in report.blockers
    assert report.safety_flags["ledger_mutated"] is False
    assert report.safety_flags["order_submitted"] is False


def test_tolerance_boundary_is_inclusive_and_beyond_boundary_blocks() -> None:
    at_boundary = _reconcile(
        _snapshot(
            cash=8_999.000001,
            positions=(IBKRPositionSnapshot("AAPL", 10.000001, 100.000001),),
        ),
        order=_order(),
    )
    beyond = _reconcile(
        _snapshot(
            cash=8_999.000002,
            positions=(IBKRPositionSnapshot("AAPL", 10.000002, 100.000002),),
        ),
        order=_order(),
    )

    assert at_boundary.block_new_orders is False
    assert beyond.block_new_orders is True
    assert "cash_drift" in beyond.blockers
    assert "position_quantity_drift" in beyond.blockers


def test_mapping_input_is_deterministic_and_validates_against_schema() -> None:
    snapshot = {
        "snapshot_id": "snapshot-1",
        "sequence": 1,
        "captured_at": "2026-08-06T01:00:00Z",
        "account": {
            "account_hash": ACCOUNT_HASH,
            "cash": 8_999.0,
            "commission_total": 1.0,
        },
        "positions": [{"symbol": "AAPL", "quantity": 10.0, "average_cost": 100.0}],
        "open_orders": [],
        "fills": [
            {
                "execId": "exec-1",
                "orderId": "order-1",
                "order_ref": "client-1",
                "permId": "broker-order-1",
                "symbol": "AAPL",
                "side": "BOT",
                "shares": 10.0,
                "price": 100.0,
                "commission": 1.0,
                "sequence": 1,
                "time": "2026-08-06T01:00:00Z",
            }
        ],
    }
    order = {
        "order_id": "order-1",
        "client_order_id": "client-1",
        "broker_order_id": "broker-order-1",
        "symbol": "AAPL",
        "side": "BUY",
        "quantity": 10.0,
        "status": "FILLED",
    }
    fill = _fill()
    report = reconcile_ibkr_paper_snapshot(
        snapshot,
        oms_orders=(order,),
        fill_ledger=(fill,),
        position_ledger=(PositionLedgerRecord("AAPL", 10.0, 100.0),),
        cash_ledger=(CashLedgerRecord(cash_balance=8_999.0, commission_total=1.0),),
        current_head=HEAD,
        run_id=RUN_ID,
        account_hash=ACCOUNT_HASH,
        now=CAPTURED_AT,
    )
    schema = json.loads(
        (Path(__file__).resolve().parents[2] / "schemas/us_equity_ibkr_paper_reconciliation_report.schema.json")
        .read_text(encoding="utf-8")
    )
    jsonschema.validate(report.to_dict(), schema, format_checker=jsonschema.FormatChecker())
    assert report.to_dict() == report.to_dict()
    assert report.safety_flags["broker_called"] is False
