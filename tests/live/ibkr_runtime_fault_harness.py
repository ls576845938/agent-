"""Deterministic, offline harness for the IBKR runtime fault contract.

This module deliberately imports the public interfaces that Agent 1, Agent 2,
and Agent 3 are expected to publish.  It does not implement a second runtime
state machine.  The fakes only model broker observations and record calls so
that the tests can prove the implementation under test failed closed.

Expected integration contract
------------------------------

* ``quant_shared.runtime.models`` exports ``RuntimeState``, ``TradingMode``
  and immutable ``RuntimeSnapshot``.
* ``quant_shared.runtime.permissions.PermissionEvaluator`` exposes
  ``can_submit_new_order()``, ``can_reduce_position()``,
  ``can_cancel_order()`` and ``can_query_broker()``.
* ``quant_us.execution.ibkr_broker_truth.BrokerTruthSnapshot`` is the
  canonical broker snapshot value object.
* ``quant_us.live.ibkr_runtime_supervisor.IBKRRuntimeSupervisor`` accepts the
  injected dependencies below and exposes ``start()``, ``snapshot()``
  (returning ``RuntimeSnapshot``), ``submit_new_order()``,
  ``on_transport_lost()``, ``on_transport_restored()``,
  ``on_recovery_result()`` and ``acknowledge_recovery()``.
* ``quant_us.live.ibkr_recovery.IBKRRecoveryOrchestrator`` accepts the same
  broker/ledger/reconciliation dependencies and exposes ``recover()`` which
  returns ``RecoveryResult``.

The contract is intentionally strict.  Missing upstream modules or renamed
interfaces must fail collection/test; no skip/xfail fallback is provided.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from quant_shared.runtime.models import RuntimeSnapshot, RuntimeState, TradingMode
from quant_shared.runtime.permissions import PermissionEvaluator
from quant_us.core.enums import OrderSide, OrderType, TimeInForce
from quant_us.core.types import OrderIntent
from quant_us.execution.ibkr_broker_truth import BrokerTruthSnapshot
from quant_us.live.ibkr_recovery import IBKRRecoveryOrchestrator, RecoveryResult
from quant_us.live.ibkr_runtime_supervisor import IBKRRuntimeSupervisor


UTC = timezone.utc
BASE_TIME = datetime(2026, 8, 7, 1, 0, tzinfo=UTC)
ACCOUNT_HASH = "account-hash-offline-fixture"


@dataclass
class FakeClock:
    """Monotonic deterministic clock; it never reads wall-clock state."""

    current: datetime = BASE_TIME

    def now(self) -> datetime:
        return self.current

    def __call__(self) -> datetime:
        return self.current

    def advance(self, seconds: float) -> None:
        self.current += timedelta(seconds=seconds)


@dataclass(frozen=True)
class FakeExecution:
    exec_id: str
    order_id: str
    quantity: float
    price: float
    commission: float = 0.0
    connection_epoch: int = 1

    def as_mapping(self) -> dict[str, Any]:
        return {
            "exec_id": self.exec_id,
            "execution_id": self.exec_id,
            "order_id": self.order_id,
            "quantity": self.quantity,
            "price": self.price,
            "commission": self.commission,
            "connection_epoch": self.connection_epoch,
            "executed_at": BASE_TIME,
        }


@dataclass
class RecordingLedger:
    """Non-idempotent sink: duplicate protection belongs to production code."""

    execution_events: list[Mapping[str, Any]] = field(default_factory=list)
    audit_events: list[Mapping[str, Any]] = field(default_factory=list)

    def apply_execution(self, execution: Mapping[str, Any] | Any) -> None:
        self.execution_events.append(_as_mapping(execution))

    def append_execution(self, execution: Mapping[str, Any] | Any) -> None:
        self.apply_execution(execution)

    def record_event(self, event: Mapping[str, Any] | Any) -> None:
        self.audit_events.append(_as_mapping(event))

    @property
    def execution_ids(self) -> list[str]:
        return [
            str(row.get("exec_id") or row.get("execution_id") or row.get("fill_id"))
            for row in self.execution_events
        ]


@dataclass
class RecordingIncidentSink:
    events: list[Mapping[str, Any]] = field(default_factory=list)

    def emit(self, event: Mapping[str, Any] | Any) -> None:
        self.events.append(_as_mapping(event))

    def record(self, event: Mapping[str, Any] | Any) -> None:
        self.emit(event)

    def open(self, event: Mapping[str, Any] | Any) -> None:
        self.emit(event)

    @property
    def types(self) -> list[str]:
        return [
            str(row.get("type") or row.get("incident_type") or row.get("event"))
            for row in self.events
        ]


@dataclass
class FakeReconciler:
    passed: bool = True
    calls: list[Mapping[str, Any]] = field(default_factory=list)

    def reconcile(self, snapshot: Any = None, **kwargs: Any) -> dict[str, Any]:
        payload = {"snapshot": snapshot, **kwargs}
        self.calls.append(payload)
        return {
            "status": "pass" if self.passed else "fail",
            "passed": self.passed,
            "reconciliation_status": "pass" if self.passed else "fail",
            "block_new_orders": not self.passed,
            "discrepancies": [] if self.passed else ["POSITION_MISMATCH"],
        }

    def run(self, snapshot: Any = None, **kwargs: Any) -> dict[str, Any]:
        return self.reconcile(snapshot, **kwargs)


@dataclass
class FakeRiskGuardian:
    kill_switch_tripped: bool = False
    calls: list[Mapping[str, Any]] = field(default_factory=list)

    def evaluate(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return {
            "status": "trip" if self.kill_switch_tripped else "pass",
            "trip_kill_switch": self.kill_switch_tripped,
            "block_new_orders": self.kill_switch_tripped,
            "violations": ["FIXTURE_KILL_SWITCH"] if self.kill_switch_tripped else [],
        }

    def check(self, **kwargs: Any) -> dict[str, Any]:
        return self.evaluate(**kwargs)


@dataclass
class FakeIBKRTransport:
    """A paper-only transport fixture; it cannot reach any endpoint."""

    connection_epoch: int = 0
    connected: bool = False
    account_verified: bool = True
    client_id: int = 42
    submitted_orders: list[Any] = field(default_factory=list)
    open_orders: dict[str, dict[str, Any]] = field(default_factory=dict)
    executions: list[FakeExecution] = field(default_factory=list)
    network_calls: list[str] = field(default_factory=list)
    live_endpoint_calls: list[str] = field(default_factory=list)
    snapshot_sequence: int = 0

    # Explicit safety attestations consumed by tests and by adapters that
    # support the offline fixture contract.
    offline_replay: bool = True
    network_access: bool = False
    private_endpoint_allowed: bool = False
    order_endpoint_allowed: bool = False
    live_ready: bool = False
    broker_access_allowed: bool = False

    def connect(self, *_args: Any, **_kwargs: Any) -> bool:
        self.network_calls.append("connect")
        self.connected = True
        self.connection_epoch += 1
        return True

    def reconnect(self, *_args: Any, **_kwargs: Any) -> bool:
        return self.connect(*_args, **_kwargs)

    def disconnect(self, reason: str = "fixture_disconnect") -> None:
        self.network_calls.append(f"disconnect:{reason}")
        self.connected = False

    def restart(self) -> None:
        self.disconnect("fixture_restart")
        self.connect()

    def is_connected(self) -> bool:
        return self.connected

    def isConnected(self) -> bool:  # noqa: N802 - IBKR spelling
        return self.connected

    def submit_order(self, order: Any) -> dict[str, Any]:
        if not self.offline_replay:
            raise AssertionError("fixture must remain offline_replay")
        self.submitted_orders.append(order)
        order_id = "broker-order-100"
        row = {
            "order_id": order_id,
            "internal_order_id": "internal-order-100",
            "strategy_order_id": "strategy-order-100",
            "broker_order_id": order_id,
            "client_id": self.client_id,
            "perm_id": 900100,
            "symbol": "AAPL",
            "side": "BUY",
            "quantity": 100.0,
            "filled_quantity": 0.0,
            "remaining_quantity": 100.0,
            "status": "submitted",
            "connection_epoch": self.connection_epoch,
        }
        self.open_orders[order_id] = row
        return row

    def place_order(self, order: Any) -> dict[str, Any]:
        return self.submit_order(order)

    def cancel_order(self, order: Any) -> None:
        self.network_calls.append("cancel_order")

    def add_fill(
        self,
        *,
        exec_id: str = "exec-40",
        quantity: float = 40.0,
        order_id: str = "broker-order-100",
        price: float = 100.0,
        commission: float = 0.4,
        epoch: int | None = None,
    ) -> FakeExecution:
        execution = FakeExecution(
            exec_id=exec_id,
            order_id=order_id,
            quantity=quantity,
            price=price,
            commission=commission,
            connection_epoch=epoch or self.connection_epoch,
        )
        self.executions.append(execution)
        row = self.open_orders.get(order_id)
        if row is not None:
            row["filled_quantity"] = float(row["filled_quantity"]) + quantity
            row["remaining_quantity"] = max(
                0.0, float(row["quantity"]) - float(row["filled_quantity"])
            )
            row["status"] = "filled" if row["remaining_quantity"] == 0.0 else "partially_filled"
        return execution

    def replay_fill(self, execution: FakeExecution) -> None:
        self.executions.append(execution)

    def broker_truth_snapshot(
        self,
        *,
        stale: bool = False,
        complete: bool = True,
        sequence_gap: bool = False,
        epoch: int | None = None,
        positions: tuple[Mapping[str, Any], ...] | None = None,
        cash: Mapping[str, Any] | None = None,
        buying_power: float | None = None,
    ) -> BrokerTruthSnapshot:
        self.snapshot_sequence += 1
        snapshot_epoch = self.connection_epoch if epoch is None else epoch
        captured_at = BASE_TIME - timedelta(seconds=600) if stale else BASE_TIME
        return BrokerTruthSnapshot(
            snapshot_id=f"snapshot-{self.snapshot_sequence}",
            connection_epoch=snapshot_epoch,
            captured_at=captured_at,
            broker_server_time=BASE_TIME,
            client_id=self.client_id,
            account_hash=ACCOUNT_HASH,
            transport_connected=self.connected,
            account_verified=self.account_verified,
            open_orders=tuple(self.open_orders.values()),
            executions=tuple(item.as_mapping() for item in self.executions),
            positions=positions
            or ({"symbol": "AAPL", "quantity": 40.0, "average_cost": 100.0},),
            cash=cash or {"cash": 95_999.6, "currency": "USD"},
            net_liquidation=100_000.0,
            buying_power=99_999.6 if buying_power is None else buying_power,
            margin=0.0,
            orders_snapshot_complete=complete,
            executions_snapshot_complete=complete,
            positions_snapshot_complete=complete,
            account_snapshot_complete=complete,
            sequence_watermark=self.snapshot_sequence - (1 if sequence_gap else 0),
            freshness="stale" if stale else "fresh",
        )


@dataclass
class RuntimeHarness:
    clock: FakeClock
    broker: FakeIBKRTransport
    ledger: RecordingLedger
    reconciler: FakeReconciler
    incidents: RecordingIncidentSink
    guardian: FakeRiskGuardian
    supervisor: IBKRRuntimeSupervisor
    recovery: IBKRRecoveryOrchestrator


def make_order_intent(quantity: float = 100.0) -> OrderIntent:
    return OrderIntent(
        timestamp_utc=BASE_TIME,
        strategy_id="chaos-fixture-strategy",
        symbol="AAPL",
        side=OrderSide.BUY,
        quantity=quantity,
        order_type=OrderType.MARKET,
        time_in_force=TimeInForce.DAY,
        run_id="chaos-fixture-run",
        client_order_id="client-order-100",
    )


def make_harness(
    *,
    reconciliation_passed: bool = True,
    kill_switch_tripped: bool = False,
) -> RuntimeHarness:
    clock = FakeClock()
    broker = FakeIBKRTransport()
    ledger = RecordingLedger()
    reconciler = FakeReconciler(passed=reconciliation_passed)
    incidents = RecordingIncidentSink()
    guardian = FakeRiskGuardian(kill_switch_tripped=kill_switch_tripped)
    supervisor = IBKRRuntimeSupervisor(
        broker_adapter=broker,
        ledger=ledger,
        reconciler=reconciler,
        incident_sink=incidents,
        risk_guardian=guardian,
        clock=clock,
    )
    recovery = IBKRRecoveryOrchestrator(
        broker_adapter=broker,
        ledger=ledger,
        reconciler=reconciler,
        incident_sink=incidents,
        clock=clock,
    )
    return RuntimeHarness(
        clock=clock,
        broker=broker,
        ledger=ledger,
        reconciler=reconciler,
        incidents=incidents,
        guardian=guardian,
        supervisor=supervisor,
        recovery=recovery,
    )


def boot_ready(harness: RuntimeHarness) -> RuntimeSnapshot:
    harness.broker.connect()
    harness.supervisor.start()
    snapshot = harness.supervisor.snapshot()
    assert isinstance(snapshot, RuntimeSnapshot)
    assert snapshot.state is RuntimeState.READY
    assert snapshot.trading_mode is TradingMode.NORMAL
    assert snapshot.block_new_orders is False
    return snapshot


def assert_fail_closed(snapshot: RuntimeSnapshot) -> None:
    assert snapshot.block_new_orders is True
    assert snapshot.state is not RuntimeState.READY
    assert snapshot.trading_mode is not TradingMode.NORMAL


def recover_after_disconnect(harness: RuntimeHarness) -> RecoveryResult:
    harness.supervisor.on_transport_lost(reason="fixture_disconnect")
    harness.broker.reconnect()
    broker_snapshot = harness.broker.broker_truth_snapshot()
    result = harness.recovery.recover(
        broker_snapshot=broker_snapshot,
        local_order_ids=tuple(harness.broker.open_orders),
        local_execution_ids=tuple(harness.ledger.execution_ids),
    )
    assert isinstance(result, RecoveryResult)
    harness.supervisor.on_recovery_result(result)
    return result


def _as_mapping(value: Mapping[str, Any] | Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if hasattr(value, "model_dump"):
        return dict(value.model_dump())
    if hasattr(value, "__dict__"):
        return dict(vars(value))
    return {"value": value}


__all__ = [
    "ACCOUNT_HASH",
    "BASE_TIME",
    "FakeClock",
    "FakeExecution",
    "FakeIBKRTransport",
    "FakeReconciler",
    "FakeRiskGuardian",
    "RecordingIncidentSink",
    "RecordingLedger",
    "RuntimeHarness",
    "assert_fail_closed",
    "boot_ready",
    "make_harness",
    "make_order_intent",
    "recover_after_disconnect",
]
