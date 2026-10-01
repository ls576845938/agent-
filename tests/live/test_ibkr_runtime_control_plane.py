from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from quant_shared.runtime.models import RuntimeSnapshot, RuntimeState, TradingMode
from quant_shared.runtime.permissions import PermissionEvaluator
from quant_shared.runtime.state_machine import (
    RecoveryAcknowledgementRequired,
    RuntimeStateMachine,
    RuntimeTransitionError,
)
from quant_us.live.ibkr_runtime_supervisor import IBKRRuntimeSupervisor


def _ready_supervisor() -> IBKRRuntimeSupervisor:
    supervisor = IBKRRuntimeSupervisor()
    supervisor.startup()
    supervisor.mark_connected(account_verified=True)
    supervisor.mark_authenticated(account_verified=True)
    supervisor.mark_broker_sync_complete(account_verified=True)
    supervisor.mark_reconciliation_passed(account_verified=True, broker_truth_fresh=True)
    # T1 makes risk_state_valid an explicit new-order invariant; this fixture
    # represents the trusted guardian/reconciliation observation required for
    # the legacy non-kill supervisor contract.
    supervisor.state_machine.update_conditions(reason="fixture_risk_state_valid", risk_state_valid=True)
    return supervisor


def test_startup_transition_graph_reaches_ready_only_after_reconciliation() -> None:
    supervisor = IBKRRuntimeSupervisor()

    assert supervisor.snapshot.state == RuntimeState.OFFLINE
    assert supervisor.startup().state == RuntimeState.CONNECTING
    assert supervisor.mark_connected(account_verified=True).state == RuntimeState.AUTHENTICATING
    assert supervisor.mark_authenticated(account_verified=True).state == RuntimeState.BROKER_SYNCING
    assert supervisor.mark_broker_sync_complete(account_verified=True).state == RuntimeState.RECONCILING

    snapshot = supervisor.mark_reconciliation_passed(
        account_verified=True,
        broker_truth_fresh=True,
    )
    supervisor.state_machine.update_conditions(reason="fixture_risk_state_valid", risk_state_valid=True)

    assert snapshot.state == RuntimeState.READY
    assert snapshot.trading_mode == TradingMode.NORMAL
    assert snapshot.block_new_orders is False
    assert supervisor.can_submit_new_order() is True


def test_disconnect_enters_no_transport_and_blocks_new_orders() -> None:
    supervisor = _ready_supervisor()

    snapshot = supervisor.on_disconnect()

    assert snapshot.state == RuntimeState.RECONNECTING
    assert snapshot.trading_mode == TradingMode.NO_TRANSPORT
    assert snapshot.block_new_orders is True
    assert supervisor.can_submit_new_order() is False


def test_reconciliation_failure_halts_and_is_fail_closed() -> None:
    supervisor = _ready_supervisor()
    supervisor.on_disconnect()
    supervisor.on_reconnect_success(account_verified=True)
    supervisor.mark_broker_sync_complete(account_verified=True)

    snapshot = supervisor.mark_reconciliation_failed(
        blockers=("position_mismatch",),
        account_verified=True,
    )

    assert snapshot.state == RuntimeState.HALTED
    assert snapshot.block_new_orders is True
    assert snapshot.trading_mode == TradingMode.FROZEN
    assert supervisor.can_submit_new_order() is False


def test_reconnect_success_cannot_skip_recovery_pending_or_ack() -> None:
    supervisor = _ready_supervisor()
    supervisor.on_disconnect()
    reconnecting = supervisor.on_reconnect_success(account_verified=True)

    assert reconnecting.state == RuntimeState.BROKER_SYNCING
    assert reconnecting.trading_mode != TradingMode.NORMAL

    supervisor.mark_broker_sync_complete(account_verified=True)
    pending = supervisor.mark_reconciliation_passed(account_verified=True)

    assert pending.state == RuntimeState.RECOVERY_PENDING
    assert pending.recovery_requires_ack is True
    assert supervisor.can_submit_new_order() is False
    with pytest.raises(RecoveryAcknowledgementRequired):
        supervisor.state_machine.transition(RuntimeState.READY)


def test_recovery_requires_operator_ack_then_resumes() -> None:
    supervisor = _ready_supervisor()
    supervisor.on_disconnect()
    supervisor.on_reconnect_success(account_verified=True)
    supervisor.mark_broker_sync_complete(account_verified=True)
    supervisor.mark_reconciliation_passed(account_verified=True)

    pending = supervisor.acknowledge_recovery(resume=False)
    assert pending.state == RuntimeState.RECOVERY_PENDING
    assert pending.operator_acknowledged is True
    assert supervisor.can_submit_new_order() is False

    ready = supervisor.resume_after_recovery()
    supervisor.state_machine.update_conditions(reason="fixture_risk_state_valid", risk_state_valid=True)
    assert ready.state == RuntimeState.READY
    assert ready.trading_mode == TradingMode.NORMAL
    assert ready.block_new_orders is False
    assert supervisor.can_submit_new_order() is True


def test_illegal_transition_raises_and_emits_rejected_audit_event() -> None:
    machine = RuntimeStateMachine()

    with pytest.raises(RuntimeTransitionError, match="illegal_runtime_transition"):
        machine.transition(RuntimeState.READY, reason="test_illegal")

    rejected = machine.audit_events[-1]
    assert rejected.accepted is False
    assert rejected.event_type == "runtime_transition_rejected"
    assert rejected.from_state == RuntimeState.OFFLINE
    assert rejected.to_state == RuntimeState.READY


@pytest.mark.parametrize(
    "changes",
    [
        {"trading_mode": TradingMode.REDUCE_ONLY},
        {"reconciliation_status": "failed"},
        {"block_new_orders": True},
        {"kill_switch_tripped": True},
        {"broker_truth_fresh": False},
        {"account_verified": False},
    ],
)
def test_ready_normal_requires_every_new_order_invariant(changes: dict[str, object]) -> None:
    snapshot = RuntimeSnapshot(
        state=RuntimeState.READY,
        trading_mode=TradingMode.NORMAL,
        block_new_orders=False,
        connected=True,
        account_verified=True,
        reconciliation_status="pass",
        broker_truth_fresh=True,
        kill_switch_tripped=False,
        blockers=(),
    )
    data = snapshot.to_dict()
    data.update(changes)

    assert PermissionEvaluator(RuntimeSnapshot.from_dict(data)).can_submit_new_order() is False


def test_degraded_cannot_submit_new_order_even_when_truth_is_fresh() -> None:
    snapshot = RuntimeSnapshot(
        state=RuntimeState.DEGRADED,
        trading_mode=TradingMode.REDUCE_ONLY,
        block_new_orders=True,
        connected=True,
        account_verified=True,
        reconciliation_status="pass",
        broker_truth_fresh=True,
    )
    evaluator = PermissionEvaluator(snapshot)

    assert evaluator.can_submit_new_order() is False
    assert evaluator.can_reduce_position() is True


def test_unknown_state_defaults_to_frozen_and_blocked() -> None:
    snapshot = RuntimeSnapshot(state="unknown_state", trading_mode="normal")

    assert snapshot.state == RuntimeState.HALTED
    assert snapshot.trading_mode == TradingMode.FROZEN
    assert snapshot.block_new_orders is True
    assert PermissionEvaluator(snapshot).can_submit_new_order() is False
    assert any(item.startswith("unknown_runtime_state:") for item in snapshot.blockers)


def test_snapshot_is_immutable_and_supervisor_has_no_live_permissions() -> None:
    snapshot = RuntimeSnapshot()
    with pytest.raises(FrozenInstanceError):
        snapshot.state = RuntimeState.READY  # type: ignore[misc]

    supervisor = IBKRRuntimeSupervisor()
    assert supervisor.network_enabled is False
    assert supervisor.live_ready is False
    assert supervisor.broker_access_allowed is False
    assert supervisor.private_endpoint_allowed is False
    assert supervisor.order_endpoint_allowed is False
