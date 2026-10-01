"""Canonical models for the trading runtime control plane.

The runtime control plane is deliberately independent from a broker adapter.  It
models what the system *believes* about a broker session and the permissions that
follow from that belief.  The defaults are conservative: a newly created
snapshot cannot submit orders and an unknown value is converted to a frozen,
fail-closed representation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Iterable, Mapping

from quant_shared.core.time import ensure_utc, isoformat_utc, utc_now


class RuntimeState(str, Enum):
    """Lifecycle states for a broker runtime session."""

    OFFLINE = "offline"
    CONNECTING = "connecting"
    AUTHENTICATING = "authenticating"
    BROKER_SYNCING = "broker_syncing"
    RECONCILING = "reconciling"
    READY = "ready"
    DEGRADED = "degraded"
    RECONNECTING = "reconnecting"
    RECOVERY_PENDING = "recovery_pending"
    HALTED = "halted"


class TradingMode(str, Enum):
    """Actions that the runtime is permitted to perform."""

    NORMAL = "normal"
    REDUCE_ONLY = "reduce_only"
    CANCEL_ONLY = "cancel_only"
    FROZEN = "frozen"
    NO_TRANSPORT = "no_transport"


class ReconciliationStatus(str, Enum):
    """Small, transport-neutral reconciliation status vocabulary."""

    UNKNOWN = "unknown"
    PASS = "pass"
    FAILED = "failed"


def _stringify_blockers(values: Iterable[object] | None) -> tuple[str, ...]:
    if values is None:
        return ()
    result: list[str] = []
    for value in values:
        text = str(value)
        if text and text not in result:
            result.append(text)
    return tuple(result)


def _is_reconciliation_passed(value: object) -> bool:
    if value is True:
        return True
    if value is False or value is None:
        return False
    if isinstance(value, ReconciliationStatus):
        value = value.value
    return str(value).strip().lower() in {
        "pass",
        "passed",
        "ok",
        "clean",
        "success",
        "succeeded",
        "true",
    }


@dataclass(frozen=True)
class RuntimeAuditEvent:
    """Immutable audit record emitted for accepted and rejected transitions."""

    timestamp: datetime
    event_type: str
    from_state: RuntimeState | None
    to_state: RuntimeState | None
    reason: str = ""
    accepted: bool = True
    details: tuple[tuple[str, str], ...] = ()

    @property
    def event(self) -> str:
        """Compatibility alias used by existing audit consumers."""

        return self.event_type

    @property
    def allowed(self) -> bool:
        return self.accepted

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": isoformat_utc(self.timestamp),
            "event_type": self.event_type,
            "event": self.event_type,
            "from_state": self.from_state.value if self.from_state else None,
            "to_state": self.to_state.value if self.to_state else None,
            "reason": self.reason,
            "accepted": self.accepted,
            "allowed": self.accepted,
            "details": dict(self.details),
        }


@dataclass(frozen=True)
class RuntimeSnapshot:
    """Read-only point-in-time view of runtime state and safety conditions.

    ``RuntimeSnapshot`` intentionally carries the conditions needed by the
    permission evaluator rather than asking callers to infer semantics from a
    single boolean such as ``connected``.  ``blockers`` is stored as a tuple so
    a snapshot cannot be mutated after publication.
    """

    state: RuntimeState | str = RuntimeState.OFFLINE
    trading_mode: TradingMode | str = TradingMode.NO_TRANSPORT
    block_new_orders: bool = True
    connected: bool = False
    account_verified: bool = False
    reconciliation_status: ReconciliationStatus | str | bool = ReconciliationStatus.UNKNOWN
    recovery_requires_ack: bool = False
    operator_acknowledged: bool = False
    last_transition_at: datetime = field(default_factory=utc_now)
    transition_reason: str = "initial"
    connection_epoch: int = 0
    reconnect_attempts: int = 0
    blockers: tuple[str, ...] | Iterable[object] = ()
    # Additional observations are explicit so consumers do not equate
    # transport connectivity with trading readiness.
    authentication_ok: bool = False
    broker_truth_fresh: bool = False
    kill_switch_tripped: bool = False
    risk_state_valid: bool = False

    def __post_init__(self) -> None:
        raw_state = self.state
        raw_mode = self.trading_mode
        blockers = list(_stringify_blockers(self.blockers))

        try:
            state = raw_state if isinstance(raw_state, RuntimeState) else RuntimeState(str(raw_state))
        except (TypeError, ValueError):
            state = RuntimeState.HALTED
            marker = f"unknown_runtime_state:{raw_state}"
            if marker not in blockers:
                blockers.append(marker)
            object.__setattr__(self, "block_new_orders", True)

        try:
            mode = raw_mode if isinstance(raw_mode, TradingMode) else TradingMode(str(raw_mode))
        except (TypeError, ValueError):
            mode = TradingMode.FROZEN
            marker = f"unknown_trading_mode:{raw_mode}"
            if marker not in blockers:
                blockers.append(marker)
            object.__setattr__(self, "block_new_orders", True)

        # A terminal/transport-absent state can never be normal.  This also
        # makes direct construction from untrusted JSON safe by default.
        if state == RuntimeState.HALTED:
            mode = TradingMode.FROZEN
            object.__setattr__(self, "block_new_orders", True)
        elif state in {
            RuntimeState.OFFLINE,
            RuntimeState.CONNECTING,
            RuntimeState.AUTHENTICATING,
            RuntimeState.BROKER_SYNCING,
            RuntimeState.RECONCILING,
            RuntimeState.RECONNECTING,
        }:
            object.__setattr__(self, "block_new_orders", True)

        if mode == TradingMode.NO_TRANSPORT:
            object.__setattr__(self, "block_new_orders", True)

        if self.recovery_requires_ack and not self.operator_acknowledged:
            mode = TradingMode.CANCEL_ONLY if self.connected else TradingMode.NO_TRANSPORT
            object.__setattr__(self, "block_new_orders", True)

        timestamp = self.last_transition_at
        if timestamp is None:
            timestamp = utc_now()
        elif isinstance(timestamp, str):
            timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))

        object.__setattr__(self, "state", state)
        object.__setattr__(self, "trading_mode", mode)
        object.__setattr__(self, "blockers", _stringify_blockers(blockers))
        object.__setattr__(self, "last_transition_at", ensure_utc(timestamp))
        object.__setattr__(self, "connection_epoch", max(0, int(self.connection_epoch)))
        object.__setattr__(self, "reconnect_attempts", max(0, int(self.reconnect_attempts)))

    @property
    def reconciliation_passed(self) -> bool:
        return _is_reconciliation_passed(self.reconciliation_status)

    @property
    def runtime_state(self) -> RuntimeState:
        return self.state

    @property
    def mode(self) -> TradingMode:
        return self.trading_mode

    @property
    def frozen(self) -> bool:
        return self.trading_mode in {TradingMode.FROZEN, TradingMode.NO_TRANSPORT}

    @property
    def has_blockers(self) -> bool:
        return bool(self.blockers)

    @property
    def transport_ok(self) -> bool:
        return bool(self.connected)

    @property
    def ready_for_new_orders(self) -> bool:
        """Convenience view; the canonical decision remains the evaluator."""

        return (
            self.state == RuntimeState.READY
            and self.trading_mode == TradingMode.NORMAL
            and not self.block_new_orders
            and self.reconciliation_passed
            and not self.kill_switch_tripped
            and self.broker_truth_fresh
            and self.account_verified
            and not self.recovery_requires_ack
            and not self.blockers
        )

    def __call__(self) -> "RuntimeSnapshot":
        """Return this immutable snapshot for legacy callable consumers.

        The control-plane contract originally exposed ``snapshot`` as a
        property, while the recovery harness uses ``snapshot()``.  Making the
        value itself callable preserves both spellings without introducing a
        second mutable state source or changing the permission semantics.
        """

        return self

    def to_dict(self) -> dict[str, Any]:
        """Serialize without exposing any broker secret or raw account id."""

        return {
            "state": self.state.value,
            "runtime_state": self.state.value,
            "trading_mode": self.trading_mode.value,
            "block_new_orders": self.block_new_orders,
            "connected": self.connected,
            "account_verified": self.account_verified,
            "authentication_ok": self.authentication_ok,
            "reconciliation_status": (
                self.reconciliation_status.value
                if isinstance(self.reconciliation_status, Enum)
                else self.reconciliation_status
            ),
            "reconciliation_passed": self.reconciliation_passed,
            "recovery_requires_ack": self.recovery_requires_ack,
            "operator_acknowledged": self.operator_acknowledged,
            "last_transition_at": isoformat_utc(self.last_transition_at),
            "transition_reason": self.transition_reason,
            "connection_epoch": self.connection_epoch,
            "reconnect_attempts": self.reconnect_attempts,
            "blockers": list(self.blockers),
            "broker_truth_fresh": self.broker_truth_fresh,
            "kill_switch_tripped": self.kill_switch_tripped,
            "risk_state_valid": self.risk_state_valid,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RuntimeSnapshot":
        """Build a fail-closed snapshot from a JSON-like mapping."""

        data = dict(value)
        if "state" not in data and "runtime_state" in data:
            data["state"] = data["runtime_state"]
        if "reconciliation_status" not in data and "reconciliation_passed" in data:
            data["reconciliation_status"] = (
                ReconciliationStatus.PASS if data["reconciliation_passed"] else ReconciliationStatus.FAILED
            )
        allowed = {
            "state",
            "trading_mode",
            "block_new_orders",
            "connected",
            "account_verified",
            "reconciliation_status",
            "recovery_requires_ack",
            "operator_acknowledged",
            "last_transition_at",
            "transition_reason",
            "connection_epoch",
            "reconnect_attempts",
            "blockers",
            "authentication_ok",
            "broker_truth_fresh",
            "kill_switch_tripped",
            "risk_state_valid",
        }
        data = {key: item for key, item in data.items() if key in allowed}
        timestamp = data.get("last_transition_at")
        if isinstance(timestamp, str):
            data["last_transition_at"] = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        return cls(**data)


__all__ = [
    "ReconciliationStatus",
    "RuntimeAuditEvent",
    "RuntimeSnapshot",
    "RuntimeState",
    "TradingMode",
]
