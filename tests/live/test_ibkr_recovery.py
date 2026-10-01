from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from quant_us.live.ibkr_paper_reconciliation import (
    CashLedgerRecord,
    FillLedgerRecord,
    IBKROpenOrderSnapshot,
    IBKRPositionSnapshot,
    OMSOrderLifecycleRecord,
    PositionLedgerRecord,
)
from quant_us.live.ibkr_recovery import (
    IBKRRecoveryOrchestrator,
    RecoveryState,
)
from quant_us.live.ibkr_paper_reconciliation import IBKRPaperReconciliationInput


UTC = timezone.utc
HEAD = "a" * 40
RUN_ID = "ibkr-recovery-fake-run-01"
ACCOUNT_HASH = "sha256:" + "b" * 64
NOW = datetime(2026, 8, 7, 1, 0, tzinfo=UTC)


class FakeRecoveryBroker:
    """No-network broker fake exposing only the recovery read/reconnect port."""

    def __init__(
        self,
        *,
        epoch: int = 7,
        truth_epoch: int | None = None,
        captured_at: datetime = NOW,
        account_hash: str = ACCOUNT_HASH,
        cash: float = 8_999.0,
        commission: float = 1.0,
        open_orders: tuple[Any, ...] = (),
        executions: tuple[Any, ...] = (),
        positions: tuple[Any, ...] = (),
        reconnect_connected: bool = True,
        fail_at: str | None = None,
        complete: bool = True,
    ) -> None:
        self.epoch = epoch
        self.truth_epoch = epoch if truth_epoch is None else truth_epoch
        self.captured_at = captured_at
        self.account_hash = account_hash
        self.cash = cash
        self.commission = commission
        self.open_orders = open_orders
        self.executions = executions
        self.positions = positions
        self.reconnect_connected = reconnect_connected
        self.fail_at = fail_at
        self.complete = complete
        self.calls: list[tuple[str, int | None]] = []
        self.global_cancel_calls = 0
        self.cancel_calls = 0

    def _maybe_fail(self, name: str) -> None:
        if self.fail_at == name:
            raise RuntimeError(f"fake failure at {name}")

    def reconnect(self, *, max_attempts: int) -> dict[str, Any]:
        self.calls.append(("reconnect", max_attempts))
        self._maybe_fail("reconnect")
        return {
            "connected": self.reconnect_connected,
            "connection_epoch": self.epoch,
            "attempts": 1,
        }

    def broker_truth_snapshot(self) -> dict[str, Any]:
        self.calls.append(("broker_truth", None))
        self._maybe_fail("broker_truth")
        return {
            "snapshot_id": "truth-7",
            "connection_epoch": self.truth_epoch,
            "captured_at": self.captured_at,
            "account_hash": self.account_hash,
            "transport_connected": True,
            "account_verified": True,
            "orders_snapshot_complete": self.complete,
            "executions_snapshot_complete": self.complete,
            "positions_snapshot_complete": self.complete,
            "account_snapshot_complete": self.complete,
            "sequence_watermark": 1,
        }

    def sync_open_orders(self) -> tuple[Any, ...]:
        self.calls.append(("open_orders", None))
        self._maybe_fail("open_orders")
        return self.open_orders

    def sync_executions(self) -> tuple[Any, ...]:
        self.calls.append(("executions", None))
        self._maybe_fail("executions")
        return self.executions

    def sync_positions(self) -> tuple[Any, ...]:
        self.calls.append(("positions", None))
        self._maybe_fail("positions")
        return self.positions

    def sync_account(self) -> dict[str, Any]:
        self.calls.append(("account", None))
        self._maybe_fail("account")
        return {
            "account_hash": self.account_hash,
            "cash": self.cash,
            "commission_total": self.commission,
            "cash_present": True,
        }


def _fill(
    execution_id: str = "exec-1",
    *,
    sequence: int = 1,
    quantity: float = 10.0,
    commission: float = 1.0,
) -> FillLedgerRecord:
    return FillLedgerRecord(
        execution_id=execution_id,
        order_id="order-1",
        client_order_id="client-1",
        broker_order_id="broker-1",
        symbol="AAPL",
        side="buy",
        quantity=quantity,
        price=100.0,
        commission=commission,
        sequence=sequence,
        executed_at=NOW,
    )


def _order(status: str = "filled", quantity: float = 10.0) -> OMSOrderLifecycleRecord:
    return OMSOrderLifecycleRecord(
        order_id="order-1",
        client_order_id="client-1",
        broker_order_id="broker-1",
        symbol="AAPL",
        side="buy",
        quantity=quantity,
        status=status,
        sequence=2,
        updated_at=NOW,
    )


def _open_order(
    *,
    status: str = "submitted",
    quantity: float = 10.0,
    filled_quantity: float = 0.0,
) -> IBKROpenOrderSnapshot:
    return IBKROpenOrderSnapshot(
        order_id="order-1",
        client_order_id="client-1",
        broker_order_id="broker-1",
        symbol="AAPL",
        side="buy",
        quantity=quantity,
        status=status,
        filled_quantity=filled_quantity,
    )


def _request(
    *,
    orders: tuple[Any, ...] = (_order(),),
    fills: tuple[FillLedgerRecord, ...] = (_fill(),),
    positions: tuple[PositionLedgerRecord, ...] = (
        PositionLedgerRecord("AAPL", 10.0, 100.0),
    ),
    cash: float = 8_999.0,
    commission: float = 1.0,
    restart: bool = False,
) -> IBKRPaperReconciliationInput:
    return IBKRPaperReconciliationInput(
        oms_orders=orders,
        fill_ledger=fills,
        position_ledger=positions,
        cash_ledger=(
            CashLedgerRecord(
                cash_balance=cash,
                commission_total=commission,
            ),
        ),
        current_head=HEAD,
        run_id=RUN_ID,
        account_hash=ACCOUNT_HASH,
        now=NOW,
        restart=restart,
    )


def _broker(
    *,
    open_orders: tuple[Any, ...] = (),
    executions: tuple[Any, ...] = (_fill(),),
    positions: tuple[Any, ...] = (IBKRPositionSnapshot("AAPL", 10.0, 100.0),),
    **kwargs: Any,
) -> FakeRecoveryBroker:
    return FakeRecoveryBroker(
        open_orders=open_orders,
        executions=executions,
        positions=positions,
        **kwargs,
    )


def _recover(
    broker: FakeRecoveryBroker,
    request: IBKRPaperReconciliationInput | None = None,
    *,
    recovery_id: str = "recovery-1",
    expected_epoch: Any = 7,
) -> tuple[IBKRRecoveryOrchestrator, Any]:
    orchestrator = IBKRRecoveryOrchestrator(broker, max_reconnect_attempts=3)
    result = orchestrator.recover(
        request or _request(),
        recovery_id=recovery_id,
        expected_connection_epoch=expected_epoch,
    )
    return orchestrator, result


def test_clean_disconnect_recovery_is_pending_until_explicit_ack() -> None:
    broker = _broker()
    orchestrator, result = _recover(broker)

    assert result.success is True
    assert result.state is RecoveryState.RECOVERY_PENDING
    assert result.block_new_orders is True
    assert result.requires_operator_ack is True
    assert result.discrepancies == ()
    assert result.events == (
        "DISCONNECTED",
        "BLOCKED",
        "TRANSPORT_UNKNOWN",
        "RECONNECTING",
        "BROKER_TRUTH",
        "OPEN_ORDERS_SYNC",
        "EXECUTIONS_SYNC",
        "POSITIONS_SYNC",
        "CASH_ACCOUNT_SYNC",
        "RECONCILING",
        "RECOVERY_PENDING",
    )
    assert broker.calls == [
        ("reconnect", 3),
        ("broker_truth", None),
        ("open_orders", None),
        ("executions", None),
        ("positions", None),
        ("account", None),
    ]
    assert all(value is False for value in result.safety_flags.values())

    acknowledged = orchestrator.acknowledge("recovery-1", operator_id="operator-a")
    assert acknowledged.state is RecoveryState.READY
    assert acknowledged.block_new_orders is False
    assert acknowledged.operator_acknowledged is True
    assert acknowledged.events[-1] == "READY"
    assert acknowledged.safety_flags["live_ready"] is False
    assert acknowledged.safety_flags["order_submission_allowed"] is False


def test_disconnect_before_order_has_no_false_order_or_fill() -> None:
    broker = _broker(executions=(), positions=(), cash=10_000.0, commission=0.0)
    _, result = _recover(
        broker,
        _request(orders=(), fills=(), positions=(), cash=10_000.0, commission=0.0),
    )
    assert result.success is True
    assert result.state is RecoveryState.RECOVERY_PENDING
    assert result.sync_summary == {"open_orders": 0, "executions": 0, "positions": 0, "account": 1}


def test_disconnect_after_submit_before_ack_reuses_broker_order() -> None:
    broker = _broker(
        open_orders=(_open_order(status="submitted"),),
        executions=(),
        positions=(),
        cash=10_000.0,
        commission=0.0,
    )
    _, result = _recover(
        broker,
        _request(
            orders=(_order("submitted"),),
            fills=(),
            positions=(),
            cash=10_000.0,
            commission=0.0,
        ),
    )
    assert result.success is True
    assert result.discrepancies == ()
    assert result.state is RecoveryState.RECOVERY_PENDING


def test_partial_fill_does_not_rebook_remaining_quantity() -> None:
    partial = _fill(quantity=40.0, commission=1.0)
    broker = _broker(
        open_orders=(_open_order(status="partially_filled", quantity=100.0, filled_quantity=40.0),),
        executions=(partial,),
        positions=(IBKRPositionSnapshot("AAPL", 40.0, 100.0),),
        cash=5_999.0,
    )
    _, result = _recover(
        broker,
        _request(
            orders=(_order("partially_filled", quantity=100.0),),
            fills=(partial,),
            positions=(PositionLedgerRecord("AAPL", 40.0, 100.0),),
            cash=5_999.0,
        ),
    )
    assert result.success is True
    assert result.discrepancy_codes == ()
    assert result.sync_summary["executions"] == 1


def test_symbol_keyed_position_surface_is_consumed_without_copying_adapter_models() -> None:
    broker = _broker(
        positions={"AAPL": IBKRPositionSnapshot("AAPL", 10.0, 100.0)},
    )
    _, result = _recover(broker)
    assert result.success is True
    assert result.sync_summary["positions"] == 1


def test_unknown_broker_order_is_blocked_and_never_adopted_or_cancelled() -> None:
    orphan = IBKROpenOrderSnapshot(
        order_id="orphan-order",
        client_order_id="orphan-client",
        broker_order_id="orphan-broker",
        symbol="MSFT",
        side="sell",
        quantity=2.0,
        status="submitted",
    )
    broker = _broker(open_orders=(orphan,), executions=(), positions=(), cash=10_000.0, commission=0.0)
    _, result = _recover(
        broker,
        _request(orders=(), fills=(), positions=(), cash=10_000.0, commission=0.0),
    )
    assert "UNKNOWN_BROKER_ORDER" in result.discrepancy_codes
    assert result.block_new_orders is True
    assert result.success is False
    assert broker.global_cancel_calls == 0
    assert broker.cancel_calls == 0
    assert all(value is False for value in result.safety_flags.values())


def test_local_active_order_missing_from_broker_is_distinct() -> None:
    broker = _broker(executions=(), positions=(), cash=10_000.0, commission=0.0)
    _, result = _recover(
        broker,
        _request(
            orders=(_order("submitted"),),
            fills=(),
            positions=(),
            cash=10_000.0,
            commission=0.0,
        ),
    )
    assert "MISSING_BROKER_ORDER" in result.discrepancy_codes
    assert "UNKNOWN_BROKER_ORDER" not in result.discrepancy_codes


def test_unknown_execution_is_blocked_without_automatic_adoption() -> None:
    unknown = _fill("broker-only-exec", quantity=2.0, commission=0.2)
    broker = _broker(
        executions=(unknown,),
        positions=(IBKRPositionSnapshot("AAPL", 2.0, 100.0),),
        cash=9_799.8,
        commission=0.2,
    )
    _, result = _recover(
        broker,
        _request(orders=(), fills=(), positions=(), cash=10_000.0, commission=0.0),
    )
    assert "UNKNOWN_EXECUTION" in result.discrepancy_codes
    assert result.safety_flags["ledger_mutated"] is False


def test_duplicate_exec_id_is_idempotent_in_classification_and_fail_closed() -> None:
    fill = _fill()
    broker = _broker(executions=(fill, fill))
    _, result = _recover(broker)
    assert "DUPLICATE_EXECUTION" in result.discrepancy_codes
    assert result.block_new_orders is True
    assert result.safety_flags["ledger_mutated"] is False


def test_position_cash_and_commission_mismatches_are_separate() -> None:
    broker = _broker(
        positions=(IBKRPositionSnapshot("AAPL", 11.0, 101.0),),
        cash=8_998.0,
        commission=2.0,
    )
    _, result = _recover(broker)
    assert "POSITION_MISMATCH" in result.discrepancy_codes
    assert "CASH_MISMATCH" in result.discrepancy_codes
    assert "COMMISSION_MISMATCH" in result.discrepancy_codes
    assert result.state is RecoveryState.RECOVERY_PENDING


def test_stale_incomplete_sequence_epoch_and_account_are_fail_closed() -> None:
    broker = _broker(
        captured_at=NOW - timedelta(minutes=10),
        truth_epoch=9,
        complete=False,
        account_hash="sha256:" + "c" * 64,
    )
    _, result = _recover(broker, expected_epoch=7)
    assert "SNAPSHOT_STALE" in result.discrepancy_codes
    assert "SNAPSHOT_INCOMPLETE" in result.discrepancy_codes
    assert "EPOCH_MISMATCH" in result.discrepancy_codes
    assert "ACCOUNT_MISMATCH" in result.discrepancy_codes
    assert result.block_new_orders is True


def test_sequence_gap_is_classified_from_execution_watermark() -> None:
    first = _fill("exec-1", sequence=1, quantity=5.0, commission=0.5)
    third = _fill("exec-3", sequence=3, quantity=5.0, commission=0.5)
    broker = _broker(
        executions=(first, third),
        positions=(IBKRPositionSnapshot("AAPL", 10.0, 100.0),),
        cash=8_999.0,
        commission=1.0,
    )
    _, result = _recover(
        broker,
        _request(
            fills=(first, third),
            positions=(PositionLedgerRecord("AAPL", 10.0, 100.0),),
        ),
    )
    assert "SEQUENCE_GAP" in result.discrepancy_codes
    assert result.block_new_orders is True


def test_reconnect_is_bounded_and_failure_enters_halted_without_sync() -> None:
    broker = _broker(fail_at="reconnect")
    _, result = _recover(broker)
    assert result.success is False
    assert result.state is RecoveryState.HALTED
    assert "RECONNECT_FAILED" in result.blockers
    assert broker.calls == [("reconnect", 3)]


def test_sync_failure_enters_halted_and_does_not_continue_pipeline() -> None:
    broker = _broker(fail_at="positions")
    _, result = _recover(broker)
    assert result.state is RecoveryState.HALTED
    assert "POSITIONS_SYNC_FAILED" in result.blockers
    assert [name for name, _ in broker.calls] == [
        "reconnect",
        "broker_truth",
        "open_orders",
        "executions",
        "positions",
    ]


def test_operator_ack_cannot_clear_unresolved_discrepancy() -> None:
    broker = _broker(
        open_orders=(_open_order(status="submitted"),),
        executions=(),
        positions=(),
        cash=10_000.0,
        commission=0.0,
    )
    orchestrator, result = _recover(
        broker,
        _request(orders=(), fills=(), positions=(), cash=10_000.0, commission=0.0),
    )
    acknowledged = orchestrator.acknowledge(result.recovery_id, operator_id="operator-a")
    assert acknowledged.state is RecoveryState.RECOVERY_PENDING
    assert acknowledged.block_new_orders is True
    assert acknowledged.operator_acknowledged is True
    assert "UNKNOWN_BROKER_ORDER" in acknowledged.blockers
    assert "RECONCILE_AND_RETRY" in acknowledged.recommended_actions


def test_missing_operator_identity_does_not_acknowledge() -> None:
    orchestrator, result = _recover(_broker())
    acknowledged = orchestrator.acknowledge(result.recovery_id, operator_id=" ")
    assert acknowledged.state is RecoveryState.RECOVERY_PENDING
    assert acknowledged.success is False
    assert acknowledged.operator_acknowledged is False
    assert "OPERATOR_ACK_IDENTITY_MISSING" in acknowledged.blockers


@pytest.mark.parametrize("method_name", ["submit_order", "cancel_order", "global_cancel"])
def test_recovery_port_never_invokes_order_or_global_cancel_surfaces(method_name: str) -> None:
    broker = _broker()
    setattr(broker, method_name, lambda: pytest.fail(f"unexpected call: {method_name}"))
    _, result = _recover(broker)
    assert result.state is RecoveryState.RECOVERY_PENDING
    assert result.safety_flags["order_submitted"] is False
    assert result.safety_flags["order_cancelled"] is False
    assert result.safety_flags["global_cancel_executed"] is False
