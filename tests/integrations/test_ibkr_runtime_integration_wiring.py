"""Isolated integration contracts for the IBKR runtime recovery wiring.

These tests only use in-memory fakes and ``tmp_path``.  They do not bootstrap a
real broker, write the registered paper ledger, or open any endpoint.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from backend.app.api.app_factory import create_app
from quant_shared.runtime.models import (
    ReconciliationStatus,
    RuntimeSnapshot,
    RuntimeState,
    TradingMode,
)
from quant_shared.runtime.permissions import PermissionDecision, PermissionEvaluator
from quant_shared.runtime.state_machine import RuntimeStateMachine
from quant_us.core.enums import OrderSide, OrderType, TimeInForce
from quant_us.core.types import AccountState, OrderIntent, Position
from quant_us.live.ibkr_runtime_provider import get_ibkr_runtime_provider_registry
from quant_us.live.ibkr_runtime_supervisor import IBKRRuntimeSupervisor
from quant_us.live.paper_runtime import PaperRuntime, PaperRuntimeConfig, PaperSessionMetrics


UTC_NOW = datetime(2026, 8, 7, 1, 0, tzinfo=timezone.utc)


class RecordingOMS:
    reduce_only = False

    def __init__(self) -> None:
        self.calls: list[object] = []

    def handle_intent(self, *args: object, **kwargs: object) -> object:
        self.calls.append((args, kwargs))
        return SimpleNamespace(
            risk_decision=SimpleNamespace(approved=False),
            order=None,
            fills=[],
        )


class SafeKillSwitch:
    triggered = False
    reason = ""


class TrackingPermissions:
    def __init__(self, *, reduce_allowed: bool = False, new_allowed: bool = False) -> None:
        self.reduce_allowed = reduce_allowed
        self.new_allowed = new_allowed
        self.reduce_calls = 0
        self.new_calls = 0

    def can_reduce_position(self) -> bool:
        self.reduce_calls += 1
        return self.reduce_allowed

    def can_submit_new_order(self) -> bool:
        self.new_calls += 1
        return self.new_allowed

    def reduce_position_decision(self) -> PermissionDecision:
        return PermissionDecision("reduce_position", self.reduce_allowed, ("fixture_block",))

    def new_order_decision(self) -> PermissionDecision:
        return PermissionDecision("submit_new_order", self.new_allowed, ("fixture_block",))


def _intent(*, side: OrderSide = OrderSide.BUY, quantity: float = 1.0) -> OrderIntent:
    return OrderIntent(
        timestamp_utc=UTC_NOW,
        strategy_id="integration-fixture",
        symbol="AAPL",
        side=side,
        quantity=quantity,
        order_type=OrderType.MARKET,
        time_in_force=TimeInForce.DAY,
    )


def _account(*, quantity: float = 0.0) -> AccountState:
    positions = {}
    if quantity:
        positions["AAPL"] = Position(symbol="AAPL", quantity=quantity, market_price=100.0)
    return AccountState(
        timestamp_utc=UTC_NOW,
        account_id="paper-fixture",
        cash=100_000.0,
        equity=100_000.0,
        buying_power=100_000.0,
        positions=positions,
    )


def _runtime_for_intent() -> tuple[PaperRuntime, RecordingOMS]:
    runtime = PaperRuntime(PaperRuntimeConfig(submit_orders=True))
    oms = RecordingOMS()
    runtime.oms = oms
    runtime.kill_switch = SafeKillSwitch()
    runtime._halt_reconciliation = False
    runtime._with_paper_attribution = lambda intent, signal: intent
    runtime._paper_submit_gate_allows = lambda intent: (True, "fixture_ok", {})
    runtime._audit_runtime_event = lambda *args, **kwargs: None
    return runtime, oms


def _ready_snapshot() -> RuntimeSnapshot:
    return RuntimeSnapshot(
        state=RuntimeState.READY,
        trading_mode=TradingMode.NORMAL,
        block_new_orders=False,
        connected=True,
        account_verified=True,
        authentication_ok=True,
        reconciliation_status=ReconciliationStatus.PASS,
        broker_truth_fresh=True,
        kill_switch_tripped=False,
        risk_state_valid=True,
    )


def test_default_flag_keeps_provider_unregistered_and_legacy_runtime_idle() -> None:
    registry = get_ibkr_runtime_provider_registry()
    registry.clear()
    runtime = PaperRuntime(PaperRuntimeConfig())

    assert runtime.config.ibkr_runtime_supervisor_enabled is False
    assert runtime._ibkr_runtime_provider is None
    assert registry.provider is None
    assert runtime._check_runtime_entry_gate()["ok"] is True


def test_non_ibkr_paper_flag_is_fail_closed(tmp_path) -> None:
    runtime = PaperRuntime(
        PaperRuntimeConfig(
            ibkr_runtime_supervisor_enabled=True,
            paper_broker="simulated",
            ledger_root=str(tmp_path / "ledger"),
            data_root=str(tmp_path / "data"),
        )
    )

    with pytest.raises(RuntimeError, match="ibkr_runtime_supervisor_requires_ibkr_paper"):
        runtime.bootstrap()


def test_runtime_permission_rejection_happens_before_oms() -> None:
    runtime, oms = _runtime_for_intent()
    runtime._ibkr_runtime_supervisor = IBKRRuntimeSupervisor()

    runtime._handle_intent(
        _intent(),
        None,
        _account(),
        {"AAPL": 100.0},
        SimpleNamespace(timestamp_utc=UTC_NOW),
        PaperSessionMetrics(),
    )

    assert oms.calls == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("state", RuntimeState.RECONCILING),
        ("trading_mode", TradingMode.FROZEN),
        ("reconciliation_status", ReconciliationStatus.FAILED),
        ("block_new_orders", True),
        ("kill_switch_tripped", True),
        ("broker_truth_fresh", False),
        ("account_verified", False),
    ],
)
def test_each_new_order_invariant_missing_keeps_oms_at_zero_calls(field, value) -> None:
    runtime, oms = _runtime_for_intent()
    snapshot = replace(_ready_snapshot(), **{field: value})
    runtime._ibkr_runtime_supervisor = IBKRRuntimeSupervisor(
        state_machine=RuntimeStateMachine(initial_snapshot=snapshot)
    )

    runtime._handle_intent(
        _intent(),
        None,
        _account(),
        {"AAPL": 100.0},
        SimpleNamespace(timestamp_utc=UTC_NOW),
        PaperSessionMetrics(),
    )

    assert oms.calls == []


def test_actual_reduction_uses_reduce_permission_and_increase_uses_new_order_permission() -> None:
    runtime, oms = _runtime_for_intent()
    permissions = TrackingPermissions(reduce_allowed=False, new_allowed=True)
    runtime._ibkr_runtime_supervisor = SimpleNamespace(permission_evaluator=permissions)

    # SELL 2 against a long 10 is a provable risk reduction even though the
    # global ``reduce_only`` mode is disabled.
    runtime._handle_intent(
        _intent(side=OrderSide.SELL, quantity=2.0),
        None,
        _account(quantity=10.0),
        {"AAPL": 100.0},
        SimpleNamespace(timestamp_utc=UTC_NOW),
        PaperSessionMetrics(),
    )
    assert permissions.reduce_calls == 1
    assert permissions.new_calls == 0
    assert oms.calls == []

    # BUY 2 against that long increases exposure, so it must use the normal
    # new-order permission instead of the reduction port.
    runtime._handle_intent(
        _intent(side=OrderSide.BUY, quantity=2.0),
        None,
        _account(quantity=10.0),
        {"AAPL": 100.0},
        SimpleNamespace(timestamp_utc=UTC_NOW),
        PaperSessionMetrics(),
    )
    assert permissions.reduce_calls == 1
    assert permissions.new_calls == 1
    assert len(oms.calls) == 1


def test_us_paper_reduction_stays_blocked_by_legacy_gate_during_kill() -> None:
    runtime, oms = _runtime_for_intent()
    snapshot = replace(_ready_snapshot(), kill_switch_tripped=True)
    runtime._ibkr_runtime_supervisor = SimpleNamespace(
        permission_evaluator=PermissionEvaluator(snapshot),
    )

    # This is the existing paper dispatcher path: it consults the legacy
    # can_reduce_position() boolean before OMS and carries no V3 proof.
    runtime._handle_intent(
        _intent(side=OrderSide.SELL, quantity=2.0),
        None,
        _account(quantity=10.0),
        {"AAPL": 100.0},
        SimpleNamespace(timestamp_utc=UTC_NOW),
        PaperSessionMetrics(),
    )

    assert oms.calls == []


def test_unregistered_registry_keeps_api_unavailable() -> None:
    registry = get_ibkr_runtime_provider_registry()
    registry.clear()
    response = TestClient(create_app()).get("/api/us/ibkr/runtime")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "unavailable_fail_closed"
    assert payload["data_available"] is False
    assert payload["block_new_orders"] is True
    assert payload["safety"] == {
        "live_ready": False,
        "broker_access_allowed": False,
        "private_endpoint_allowed": False,
        "order_endpoint_allowed": False,
    }
