"""P0 partial-fill/disconnect/recovery scenario using only offline fakes."""

from __future__ import annotations

import pytest

from quant_shared.runtime.models import RuntimeState, TradingMode

from tests.live.ibkr_runtime_fault_harness import (
    assert_fail_closed,
    boot_ready,
    make_harness,
    make_order_intent,
)


@pytest.mark.integration
@pytest.mark.e2e
def test_partial_fill_disconnect_replay_is_idempotent_and_ack_gated() -> None:
    """READY → 100/40 fill → disconnect → replay → ack → READY.

    The fake ledger intentionally counts every ``apply_execution`` call.  A
    passing test therefore proves that the runtime/recovery implementation,
    rather than the fixture, deduplicates ``exec-40`` and does not turn the
    broker's remaining quantity into a fresh order.
    """

    harness = make_harness()
    ready = boot_ready(harness)
    assert ready.state is RuntimeState.READY
    assert ready.trading_mode is TradingMode.NORMAL

    # 1–3. Submit 100 and accept exactly one broker-side partial fill of 40.
    harness.supervisor.submit_new_order(make_order_intent(quantity=100.0))
    assert len(harness.broker.submitted_orders) == 1
    broker_order = harness.broker.open_orders["broker-order-100"]
    assert broker_order["quantity"] == 100.0
    fill_40 = harness.broker.add_fill(exec_id="exec-40", quantity=40.0)
    harness.supervisor.on_broker_execution(fill_40.as_mapping())
    assert harness.ledger.execution_ids == ["exec-40"]
    assert broker_order["filled_quantity"] == 40.0
    assert broker_order["remaining_quantity"] == 60.0

    # 4–7. Transport loss is an explicit NO_TRANSPORT fail-closed state.
    harness.broker.disconnect("partial_fill_disconnect")
    harness.supervisor.on_transport_lost(reason="partial_fill_disconnect")
    disconnected = harness.supervisor.snapshot()
    assert disconnected.state in {
        RuntimeState.RECONNECTING,
        RuntimeState.DEGRADED,
        RuntimeState.HALTED,
    }
    assert disconnected.trading_mode is TradingMode.NO_TRANSPORT
    assert_fail_closed(disconnected)
    harness.supervisor.submit_new_order(make_order_intent(quantity=1.0))
    assert len(harness.broker.submitted_orders) == 1

    # 8–13. Reconnect, replay the broker order/fill, and reconcile.
    harness.broker.reconnect()
    broker_snapshot = harness.broker.broker_truth_snapshot()
    result = harness.recovery.recover(
        broker_snapshot=broker_snapshot,
        local_order_ids=tuple(harness.broker.open_orders),
        local_execution_ids=tuple(harness.ledger.execution_ids),
    )
    harness.supervisor.on_recovery_result(result)
    assert result.success is True
    assert result.reconciliation_status in {"pass", "clean"}
    assert broker_order["remaining_quantity"] == 60.0

    # Duplicate callback after reconnect must not double-count the fill.
    harness.supervisor.on_broker_execution(fill_40.as_mapping())
    assert harness.ledger.execution_ids == ["exec-40"]
    assert len(harness.ledger.execution_events) == 1

    # 14–15. Successful abnormal recovery still requires explicit operator ack.
    pending = harness.supervisor.snapshot()
    assert pending.state is RuntimeState.RECOVERY_PENDING
    assert pending.block_new_orders is True
    assert pending.trading_mode is not TradingMode.NORMAL
    harness.supervisor.submit_new_order(make_order_intent(quantity=1.0))
    assert len(harness.broker.submitted_orders) == 1

    # 16–17. Only an explicit acknowledgement can restore READY + NORMAL.
    harness.supervisor.acknowledge_recovery(operator_id="operator-fixture")
    resumed = harness.supervisor.snapshot()
    assert resumed.state is RuntimeState.READY
    assert resumed.trading_mode is TradingMode.NORMAL
    assert resumed.block_new_orders is False


def test_replayed_fill_does_not_create_a_second_remaining_order() -> None:
    """The 60-share broker remainder is recovered, never resubmitted locally."""

    harness = make_harness()
    boot_ready(harness)
    harness.supervisor.submit_new_order(make_order_intent(quantity=100.0))
    harness.broker.add_fill(exec_id="exec-40", quantity=40.0)
    harness.supervisor.on_broker_execution(harness.broker.executions[0].as_mapping())
    harness.broker.disconnect("replay_remaining")
    harness.supervisor.on_transport_lost(reason="replay_remaining")
    harness.broker.reconnect()
    result = harness.recovery.recover(
        broker_snapshot=harness.broker.broker_truth_snapshot(),
        local_order_ids=tuple(harness.broker.open_orders),
        local_execution_ids=tuple(harness.ledger.execution_ids),
    )
    harness.supervisor.on_recovery_result(result)

    assert result.success is True
    assert len(harness.broker.submitted_orders) == 1
    assert harness.broker.open_orders["broker-order-100"]["remaining_quantity"] == 60.0
    assert harness.ledger.execution_ids == ["exec-40"]
