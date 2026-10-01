"""IBKR runtime failure matrix against the Agent 1/2/3 public contract.

These are paper-validation tests only.  Every broker interaction is the
offline fake from :mod:`ibkr_runtime_fault_harness`; a real Gateway, private
endpoint, order endpoint, credential, or secret is outside this test's scope.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import pytest

from quant_shared.runtime.models import RuntimeSnapshot, RuntimeState, TradingMode
from quant_shared.runtime.permissions import PermissionEvaluator

from tests.live.ibkr_runtime_fault_harness import (
    RuntimeHarness,
    assert_fail_closed,
    boot_ready,
    make_harness,
    make_order_intent,
    recover_after_disconnect,
)


@dataclass(frozen=True)
class FailureCase:
    name: str
    category: str
    trigger: Callable[[RuntimeHarness], None]
    expected_incident: str


def _transport_loss(case: str) -> Callable[[RuntimeHarness], None]:
    def trigger(harness: RuntimeHarness) -> None:
        boot_ready(harness)
        harness.supervisor.on_transport_lost(reason=case)

    return trigger


def _account_mismatch(harness: RuntimeHarness) -> None:
    harness.broker.account_verified = False
    harness.broker.connect()
    harness.supervisor.start()
    harness.supervisor.on_broker_truth(harness.broker.broker_truth_snapshot())


def _duplicate_client_id(harness: RuntimeHarness) -> None:
    harness.broker.client_id = -1
    harness.broker.connect()
    harness.supervisor.start()
    harness.supervisor.on_transport_lost(reason="duplicate_client_id")


def _stale_snapshot(harness: RuntimeHarness) -> None:
    boot_ready(harness)
    harness.supervisor.on_broker_truth(
        harness.broker.broker_truth_snapshot(stale=True)
    )


def _incomplete_snapshot(harness: RuntimeHarness) -> None:
    boot_ready(harness)
    harness.supervisor.on_broker_truth(
        harness.broker.broker_truth_snapshot(complete=False)
    )


def _sequence_gap(harness: RuntimeHarness) -> None:
    boot_ready(harness)
    harness.supervisor.on_broker_truth(
        harness.broker.broker_truth_snapshot(sequence_gap=True)
    )


def _epoch_mismatch(harness: RuntimeHarness) -> None:
    boot_ready(harness)
    harness.broker.reconnect()
    harness.supervisor.on_broker_truth(
        harness.broker.broker_truth_snapshot(epoch=1)
    )


def _reconciliation_failure(harness: RuntimeHarness) -> None:
    # No shortcut to READY is allowed when the startup reconciliation fails.
    harness.reconciler.passed = False
    harness.broker.connect()
    harness.supervisor.start()


def _kill_switch(harness: RuntimeHarness) -> None:
    harness.guardian.kill_switch_tripped = True
    harness.broker.connect()
    harness.supervisor.start()


def _submit_then_disconnect(harness: RuntimeHarness) -> None:
    boot_ready(harness)
    harness.supervisor.submit_new_order(make_order_intent(quantity=100.0))
    harness.broker.disconnect("submit_then_disconnect")
    harness.supervisor.on_transport_lost(reason="submit_then_disconnect")


def _ack_lost(harness: RuntimeHarness) -> None:
    boot_ready(harness)
    harness.supervisor.submit_new_order(make_order_intent(quantity=100.0))
    harness.broker.disconnect("ack_lost")
    harness.supervisor.on_transport_lost(reason="ack_lost")


def _broker_orphan_order(harness: RuntimeHarness) -> None:
    boot_ready(harness)
    harness.broker.open_orders["orphan-order-1"] = {
        "order_id": "orphan-order-1",
        "broker_order_id": "orphan-order-1",
        "client_id": harness.broker.client_id,
        "quantity": 10.0,
        "filled_quantity": 0.0,
        "remaining_quantity": 10.0,
        "status": "submitted",
        "connection_epoch": harness.broker.connection_epoch,
    }
    harness.supervisor.on_broker_truth(harness.broker.broker_truth_snapshot())


def _local_orphan_order(harness: RuntimeHarness) -> None:
    boot_ready(harness)
    harness.supervisor.on_broker_truth(harness.broker.broker_truth_snapshot())
    harness.supervisor.on_transport_lost(reason="local_orphan_order")


def _partial_fill_disconnect(harness: RuntimeHarness) -> None:
    boot_ready(harness)
    harness.supervisor.submit_new_order(make_order_intent(quantity=100.0))
    fill = harness.broker.add_fill(exec_id="exec-partial-1", quantity=40.0)
    harness.supervisor.on_broker_execution(fill.as_mapping())
    harness.broker.disconnect("partial_fill_disconnect")
    harness.supervisor.on_transport_lost(reason="partial_fill_disconnect")


def _duplicate_execution(harness: RuntimeHarness) -> None:
    boot_ready(harness)
    harness.supervisor.submit_new_order(make_order_intent(quantity=100.0))
    fill = harness.broker.add_fill(exec_id="exec-duplicate-1", quantity=40.0)
    harness.supervisor.on_broker_execution(fill.as_mapping())
    harness.broker.replay_fill(fill)
    harness.supervisor.on_broker_execution(fill.as_mapping())


def _out_of_order_execution(harness: RuntimeHarness) -> None:
    boot_ready(harness)
    harness.supervisor.on_broker_execution(
        {
            "exec_id": "exec-old-sequence",
            "order_id": "broker-order-100",
            "quantity": 40.0,
            "price": 100.0,
            "connection_epoch": 0,
            "sequence": 0,
        }
    )


def _late_commission(harness: RuntimeHarness) -> None:
    boot_ready(harness)
    harness.supervisor.on_broker_execution(
        {
            "exec_id": "exec-late-commission",
            "order_id": "broker-order-100",
            "quantity": 40.0,
            "price": 100.0,
            "commission": 0.4,
            "connection_epoch": harness.broker.connection_epoch,
        }
    )
    harness.supervisor.on_transport_lost(reason="commission_arrives_late")


def _market_subscription_lost(harness: RuntimeHarness) -> None:
    boot_ready(harness)
    harness.supervisor.on_transport_lost(reason="subscription_lost")


def _market_epoch_mismatch(harness: RuntimeHarness) -> None:
    _epoch_mismatch(harness)


def _duplicate_tick(harness: RuntimeHarness) -> None:
    boot_ready(harness)
    harness.supervisor.on_transport_lost(reason="duplicate_tick")


def _position_drift(harness: RuntimeHarness) -> None:
    boot_ready(harness)
    harness.reconciler.passed = False
    harness.supervisor.on_broker_truth(
        harness.broker.broker_truth_snapshot(
            positions=({"symbol": "AAPL", "quantity": 999.0, "average_cost": 100.0},)
        )
    )


def _cash_drift(harness: RuntimeHarness) -> None:
    boot_ready(harness)
    harness.reconciler.passed = False
    harness.supervisor.on_broker_truth(
        harness.broker.broker_truth_snapshot(cash={"cash": -1.0, "currency": "USD"})
    )


def _buying_power_unavailable(harness: RuntimeHarness) -> None:
    boot_ready(harness)
    harness.reconciler.passed = False
    harness.supervisor.on_broker_truth(
        harness.broker.broker_truth_snapshot(buying_power=0.0)
    )


def _runtime_crash(harness: RuntimeHarness) -> None:
    boot_ready(harness)
    harness.supervisor.on_transport_lost(reason="runtime_crash")


def _restart_from_ledger(harness: RuntimeHarness) -> None:
    boot_ready(harness)
    harness.supervisor.on_transport_lost(reason="restart_from_ledger")


def _restart_during_reconciliation(harness: RuntimeHarness) -> None:
    harness.reconciler.passed = False
    harness.broker.connect()
    harness.supervisor.start()
    harness.supervisor.on_transport_lost(reason="restart_during_reconciliation")


def _restart_during_recovery(harness: RuntimeHarness) -> None:
    boot_ready(harness)
    harness.supervisor.on_transport_lost(reason="restart_during_recovery")


FAILURE_MATRIX = (
    FailureCase("gateway_disconnect", "transport", _transport_loss("gateway_disconnect"), "IBKR_DISCONNECTED"),
    FailureCase("gateway_restart", "transport", _transport_loss("gateway_restart"), "IBKR_DISCONNECTED"),
    FailureCase("socket_timeout", "transport", _transport_loss("socket_timeout"), "IBKR_DISCONNECTED"),
    FailureCase("heartbeat_stale", "transport", _transport_loss("heartbeat_stale"), "IBKR_DISCONNECTED"),
    FailureCase("bounded_reconnect_exhausted", "transport", _transport_loss("bounded_reconnect_exhausted"), "IBKR_RECONNECT_FAILED"),
    FailureCase("duplicate_client_id", "identity", _duplicate_client_id, "IBKR_RECONNECT_FAILED"),
    FailureCase("account_mismatch", "identity", _account_mismatch, "ACCOUNT_MISMATCH"),
    FailureCase("snapshot_stale", "broker_truth", _stale_snapshot, "BROKER_TRUTH_STALE"),
    FailureCase("snapshot_incomplete", "broker_truth", _incomplete_snapshot, "BROKER_TRUTH_INCOMPLETE"),
    FailureCase("sequence_gap", "broker_truth", _sequence_gap, "SEQUENCE_GAP"),
    FailureCase("epoch_mismatch", "broker_truth", _epoch_mismatch, "EPOCH_MISMATCH"),
    FailureCase("reconciliation_failed", "reconciliation", _reconciliation_failure, "RECONCILIATION_FAILED"),
    FailureCase("kill_switch_tripped", "risk", _kill_switch, "KILL_SWITCH_TRIPPED"),
    FailureCase("submit_then_disconnect", "orders", _submit_then_disconnect, "IBKR_DISCONNECTED"),
    FailureCase("ack_lost", "orders", _ack_lost, "IBKR_DISCONNECTED"),
    FailureCase("broker_orphan_order", "orders", _broker_orphan_order, "UNKNOWN_BROKER_ORDER"),
    FailureCase("local_orphan_order", "orders", _local_orphan_order, "IBKR_DISCONNECTED"),
    FailureCase("partial_fill_then_disconnect", "fills", _partial_fill_disconnect, "IBKR_DISCONNECTED"),
    FailureCase("duplicate_execution", "fills", _duplicate_execution, "DUPLICATE_EXECUTION"),
    FailureCase("out_of_order_execution", "fills", _out_of_order_execution, "EPOCH_MISMATCH"),
    FailureCase("commission_arrives_late", "fills", _late_commission, "IBKR_DISCONNECTED"),
    FailureCase("subscription_lost", "market_data", _market_subscription_lost, "IBKR_DISCONNECTED"),
    FailureCase("market_data_epoch_mismatch", "market_data", _market_epoch_mismatch, "EPOCH_MISMATCH"),
    FailureCase("duplicate_tick", "market_data", _duplicate_tick, "IBKR_DISCONNECTED"),
    FailureCase("position_drift", "account", _position_drift, "RECONCILIATION_FAILED"),
    FailureCase("cash_drift", "account", _cash_drift, "RECONCILIATION_FAILED"),
    FailureCase("buying_power_unavailable", "account", _buying_power_unavailable, "RECONCILIATION_FAILED"),
    FailureCase("snapshot_incomplete_account", "account", _incomplete_snapshot, "BROKER_TRUTH_INCOMPLETE"),
    FailureCase("runtime_crash", "process", _runtime_crash, "IBKR_DISCONNECTED"),
    FailureCase("restart_from_ledger", "process", _restart_from_ledger, "IBKR_DISCONNECTED"),
    FailureCase("restart_during_reconciliation", "process", _restart_during_reconciliation, "RECONCILIATION_FAILED"),
    FailureCase("restart_during_recovery", "process", _restart_during_recovery, "IBKR_DISCONNECTED"),
)


def _snapshot(harness: RuntimeHarness) -> RuntimeSnapshot:
    snapshot = harness.supervisor.snapshot()
    assert isinstance(snapshot, RuntimeSnapshot)
    return snapshot


@pytest.mark.integration
@pytest.mark.parametrize("case", FAILURE_MATRIX, ids=lambda item: item.name)
def test_failure_matrix_is_fail_closed(case: FailureCase) -> None:
    """Every known runtime/broker fault blocks new orders and leaves NORMAL."""

    harness = make_harness()
    case.trigger(harness)
    submitted_before_block = tuple(harness.broker.submitted_orders)
    submitted_before_count = len(submitted_before_block)
    snapshot = _snapshot(harness)

    assert_fail_closed(snapshot)
    harness.supervisor.submit_new_order(make_order_intent(quantity=1.0))
    submitted_after_block = tuple(harness.broker.submitted_orders)
    assert submitted_after_block == submitted_before_block
    assert len(submitted_after_block) == submitted_before_count
    assert harness.broker.private_endpoint_allowed is False
    assert harness.broker.order_endpoint_allowed is False
    assert harness.broker.live_ready is False
    assert case.expected_incident in harness.incidents.types


def test_public_permission_evaluator_contract_is_not_optional() -> None:
    """The shared permission evaluator must expose all four policy checks."""

    for method_name in (
        "can_submit_new_order",
        "can_reduce_position",
        "can_cancel_order",
        "can_query_broker",
    ):
        method = getattr(PermissionEvaluator, method_name, None)
        assert callable(method), f"missing PermissionEvaluator.{method_name}()"


def test_disconnected_runtime_can_never_be_normal_or_ready() -> None:
    harness = make_harness()
    boot_ready(harness)

    harness.broker.disconnect("operator_fault")
    harness.supervisor.on_transport_lost(reason="operator_fault")
    snapshot = _snapshot(harness)

    assert snapshot.connected is False
    assert snapshot.state in {
        RuntimeState.RECONNECTING,
        RuntimeState.DEGRADED,
        RuntimeState.HALTED,
    }
    assert snapshot.trading_mode is TradingMode.NO_TRANSPORT
    assert_fail_closed(snapshot)


def test_blocked_runtime_rejects_new_order_without_touching_broker() -> None:
    harness = make_harness()
    boot_ready(harness)
    harness.supervisor.on_transport_lost(reason="submit_then_disconnect")

    harness.supervisor.submit_new_order(make_order_intent())

    assert harness.broker.submitted_orders == []
    assert_fail_closed(_snapshot(harness))


def test_reconciliation_failure_can_never_publish_ready() -> None:
    harness = make_harness(reconciliation_passed=False)
    harness.broker.connect()
    harness.supervisor.start()

    snapshot = _snapshot(harness)
    assert snapshot.state is not RuntimeState.READY
    assert snapshot.trading_mode is not TradingMode.NORMAL
    assert snapshot.block_new_orders is True
    assert "RECONCILIATION_FAILED" in harness.incidents.types


def test_successful_reconnect_requires_recovery_ack_before_ready() -> None:
    harness = make_harness()
    boot_ready(harness)

    result = recover_after_disconnect(harness)
    pending = _snapshot(harness)

    assert result.success is True
    assert pending.state is RuntimeState.RECOVERY_PENDING
    assert pending.block_new_orders is True
    assert pending.trading_mode is not TradingMode.NORMAL
    harness.supervisor.submit_new_order(make_order_intent())
    assert harness.broker.submitted_orders == []

    harness.supervisor.acknowledge_recovery(operator_id="operator-fixture")
    ready = _snapshot(harness)
    assert ready.state is RuntimeState.READY
    assert ready.trading_mode is TradingMode.NORMAL
    assert ready.block_new_orders is False


def test_failed_recovery_never_auto_clears_blockers() -> None:
    harness = make_harness(reconciliation_passed=False)
    harness.broker.connect()
    harness.supervisor.start()
    harness.supervisor.on_transport_lost(reason="recovery_reconcile_fail")
    harness.broker.reconnect()
    result = harness.recovery.recover(
        broker_snapshot=harness.broker.broker_truth_snapshot(),
        local_order_ids=tuple(harness.broker.open_orders),
        local_execution_ids=tuple(harness.ledger.execution_ids),
    )
    harness.supervisor.on_recovery_result(result)
    harness.supervisor.acknowledge_recovery(operator_id="operator-fixture")

    snapshot = _snapshot(harness)
    assert result.success is False
    assert snapshot.state in {RuntimeState.HALTED, RuntimeState.DEGRADED}
    assert snapshot.block_new_orders is True
    assert snapshot.trading_mode is not TradingMode.NORMAL
    assert harness.broker.submitted_orders == []


def test_stale_epoch_event_is_not_consumed_as_current_truth() -> None:
    harness = make_harness()
    boot_ready(harness)
    old_epoch = harness.broker.connection_epoch
    harness.broker.reconnect()

    harness.supervisor.on_broker_truth(
        harness.broker.broker_truth_snapshot(epoch=old_epoch)
    )

    snapshot = _snapshot(harness)
    assert_fail_closed(snapshot)
    assert "EPOCH_MISMATCH" in harness.incidents.types
    assert harness.ledger.execution_events == []


def test_kill_switch_is_not_auto_cleared_by_reconnect_or_ack() -> None:
    harness = make_harness(kill_switch_tripped=True)
    harness.broker.connect()
    harness.supervisor.start()
    harness.supervisor.on_transport_lost(reason="kill_switch_fixture")
    harness.broker.reconnect()
    result = harness.recovery.recover(
        broker_snapshot=harness.broker.broker_truth_snapshot(),
        local_order_ids=tuple(harness.broker.open_orders),
        local_execution_ids=tuple(harness.ledger.execution_ids),
    )
    harness.supervisor.on_recovery_result(result)
    harness.supervisor.acknowledge_recovery(operator_id="operator-fixture")

    snapshot = _snapshot(harness)
    assert snapshot.block_new_orders is True
    assert snapshot.trading_mode is not TradingMode.NORMAL
    assert harness.broker.submitted_orders == []
