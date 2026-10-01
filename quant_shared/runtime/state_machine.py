"""Fail-closed runtime state machine.

This module owns the canonical transition graph.  It contains no broker or
network code; adapters and recovery orchestrators report observations through
the small methods below.  Every accepted *and rejected* transition is emitted
as an audit event so an illegal state change cannot disappear silently.
"""

from __future__ import annotations

from datetime import datetime
from typing import Callable, Iterable, Mapping

from quant_shared.core.time import ensure_utc, utc_now
from quant_shared.runtime.models import (
    ReconciliationStatus,
    RuntimeAuditEvent,
    RuntimeSnapshot,
    RuntimeState,
    TradingMode,
)


class RuntimeTransitionError(ValueError):
    """Raised when a requested runtime transition is not permitted."""


# Public aliases keep integrations from inventing their own exception type.
InvalidRuntimeTransition = RuntimeTransitionError
InvalidTransitionError = RuntimeTransitionError
IllegalTransitionError = RuntimeTransitionError


class RecoveryAcknowledgementRequired(RuntimeTransitionError):
    """Raised when recovery would be resumed without an operator ack."""


class RecoveryBlocked(RuntimeTransitionError):
    """Raised when recovery ack exists but safety blockers remain."""


def _enum_state(value: RuntimeState | str) -> RuntimeState:
    try:
        return value if isinstance(value, RuntimeState) else RuntimeState(str(value))
    except (TypeError, ValueError) as exc:
        raise RuntimeTransitionError(f"unknown_runtime_state:{value}") from exc


def _enum_mode(value: TradingMode | str) -> TradingMode:
    try:
        return value if isinstance(value, TradingMode) else TradingMode(str(value))
    except (TypeError, ValueError) as exc:
        raise RuntimeTransitionError(f"unknown_trading_mode:{value}") from exc


def _detail_pairs(details: Mapping[str, object] | None) -> tuple[tuple[str, str], ...]:
    if not details:
        return ()
    return tuple(sorted((str(key), str(value)) for key, value in details.items()))


# Self transitions are intentional: repeated callbacks are idempotent but still
# auditable.  All non-self transitions are explicit and have no implicit
# fallback path.
TRANSITION_GRAPH: dict[RuntimeState, frozenset[RuntimeState]] = {
    RuntimeState.OFFLINE: frozenset({RuntimeState.OFFLINE, RuntimeState.CONNECTING, RuntimeState.HALTED}),
    RuntimeState.CONNECTING: frozenset(
        {RuntimeState.CONNECTING, RuntimeState.AUTHENTICATING, RuntimeState.DEGRADED, RuntimeState.RECONNECTING, RuntimeState.HALTED}
    ),
    RuntimeState.AUTHENTICATING: frozenset(
        {RuntimeState.AUTHENTICATING, RuntimeState.BROKER_SYNCING, RuntimeState.DEGRADED, RuntimeState.RECONNECTING, RuntimeState.HALTED}
    ),
    RuntimeState.BROKER_SYNCING: frozenset(
        {RuntimeState.BROKER_SYNCING, RuntimeState.RECONCILING, RuntimeState.DEGRADED, RuntimeState.RECONNECTING, RuntimeState.HALTED}
    ),
    RuntimeState.RECONCILING: frozenset(
        {RuntimeState.RECONCILING, RuntimeState.READY, RuntimeState.RECOVERY_PENDING, RuntimeState.DEGRADED, RuntimeState.HALTED}
    ),
    RuntimeState.READY: frozenset({RuntimeState.READY, RuntimeState.DEGRADED, RuntimeState.RECONNECTING, RuntimeState.HALTED}),
    RuntimeState.DEGRADED: frozenset(
        {RuntimeState.DEGRADED, RuntimeState.RECONNECTING, RuntimeState.BROKER_SYNCING, RuntimeState.RECONCILING, RuntimeState.HALTED}
    ),
    RuntimeState.RECONNECTING: frozenset(
        {RuntimeState.RECONNECTING, RuntimeState.BROKER_SYNCING, RuntimeState.DEGRADED, RuntimeState.RECONCILING, RuntimeState.RECOVERY_PENDING, RuntimeState.HALTED}
    ),
    RuntimeState.RECOVERY_PENDING: frozenset(
        {RuntimeState.RECOVERY_PENDING, RuntimeState.READY, RuntimeState.DEGRADED, RuntimeState.HALTED}
    ),
    RuntimeState.HALTED: frozenset({RuntimeState.HALTED}),
}

# A descriptive alias used by a few operator-facing consumers.
ALLOWED_TRANSITIONS = TRANSITION_GRAPH


class RuntimeStateMachine:
    """Canonical state machine with immutable snapshots and an audit log."""

    def __init__(
        self,
        initial_snapshot: RuntimeSnapshot | None = None,
        *,
        clock: Callable[[], datetime] = utc_now,
        audit_sink: Callable[[RuntimeAuditEvent], None] | None = None,
    ) -> None:
        self._clock = clock
        self._audit_sink = audit_sink
        self._snapshot = initial_snapshot or RuntimeSnapshot()
        self._audit_events: list[RuntimeAuditEvent] = []
        self._recovery_flow = bool(
            self._snapshot.recovery_requires_ack
            or self._snapshot.state in {RuntimeState.RECONNECTING, RuntimeState.RECOVERY_PENDING}
        )

    @property
    def snapshot(self) -> RuntimeSnapshot:
        return self._snapshot

    @property
    def current_snapshot(self) -> RuntimeSnapshot:
        return self.snapshot

    @property
    def state(self) -> RuntimeState:
        return self._snapshot.state

    @property
    def current_state(self) -> RuntimeState:
        return self.state

    @property
    def trading_mode(self) -> TradingMode:
        return self._snapshot.trading_mode

    @property
    def audit_events(self) -> tuple[RuntimeAuditEvent, ...]:
        return tuple(self._audit_events)

    @property
    def audit_log(self) -> tuple[RuntimeAuditEvent, ...]:
        return self.audit_events

    @property
    def recovery_flow_active(self) -> bool:
        return self._recovery_flow

    @property
    def transition_graph(self) -> dict[RuntimeState, frozenset[RuntimeState]]:
        return TRANSITION_GRAPH

    def _emit(
        self,
        *,
        event_type: str,
        from_state: RuntimeState | None,
        to_state: RuntimeState | None,
        reason: str,
        accepted: bool,
        details: Mapping[str, object] | None = None,
    ) -> RuntimeAuditEvent:
        event = RuntimeAuditEvent(
            timestamp=ensure_utc(self._clock()),
            event_type=event_type,
            from_state=from_state,
            to_state=to_state,
            reason=reason,
            accepted=accepted,
            details=_detail_pairs(details),
        )
        self._audit_events.append(event)
        if self._audit_sink is not None:
            self._audit_sink(event)
        return event

    @staticmethod
    def _base_ready(snapshot: RuntimeSnapshot) -> bool:
        """Evaluate the seven cross-module new-order invariants."""

        return (
            snapshot.state == RuntimeState.READY
            and snapshot.trading_mode == TradingMode.NORMAL
            and snapshot.reconciliation_passed
            and not snapshot.block_new_orders
            and not snapshot.kill_switch_tripped
            and snapshot.broker_truth_fresh
            and snapshot.account_verified
        )

    def _build_snapshot(
        self,
        target: RuntimeState,
        *,
        reason: str,
        now: datetime | None = None,
        trading_mode: TradingMode | str | None = None,
        block_new_orders: bool | None = None,
        connected: bool | None = None,
        account_verified: bool | None = None,
        authentication_ok: bool | None = None,
        reconciliation_status: ReconciliationStatus | str | bool | None = None,
        recovery_requires_ack: bool | None = None,
        operator_acknowledged: bool | None = None,
        connection_epoch: int | None = None,
        reconnect_attempts: int | None = None,
        blockers: Iterable[object] | None = None,
        broker_truth_fresh: bool | None = None,
        kill_switch_tripped: bool | None = None,
        risk_state_valid: bool | None = None,
    ) -> RuntimeSnapshot:
        old = self._snapshot
        is_recovery_pending = target == RuntimeState.RECOVERY_PENDING
        recovery_required = old.recovery_requires_ack if recovery_requires_ack is None else bool(recovery_requires_ack)
        operator_ack = old.operator_acknowledged if operator_acknowledged is None else bool(operator_acknowledged)

        if is_recovery_pending:
            recovery_required = True
            operator_ack = False if operator_acknowledged is None else operator_ack

        connected_value = old.connected if connected is None else bool(connected)
        mode = old.trading_mode if trading_mode is None else _enum_mode(trading_mode)
        block = old.block_new_orders if block_new_orders is None else bool(block_new_orders)

        if target == RuntimeState.OFFLINE:
            mode, block, connected_value = TradingMode.NO_TRANSPORT, True, False
        elif target == RuntimeState.HALTED:
            mode, block = TradingMode.FROZEN, True
        elif target in {
            RuntimeState.CONNECTING,
            RuntimeState.AUTHENTICATING,
            RuntimeState.BROKER_SYNCING,
            RuntimeState.RECONCILING,
        }:
            mode, block = (TradingMode.FROZEN if connected_value else TradingMode.NO_TRANSPORT), True
        elif target == RuntimeState.RECONNECTING:
            mode, block = TradingMode.NO_TRANSPORT, True
        elif target == RuntimeState.RECOVERY_PENDING:
            mode = TradingMode.CANCEL_ONLY if connected_value and (broker_truth_fresh if broker_truth_fresh is not None else old.broker_truth_fresh) else TradingMode.FROZEN
            block = True
        elif target == RuntimeState.READY:
            # The state can be observed as READY while an invariant is still
            # blocked, but mode/permissions remain fail-closed until every
            # explicit condition is true.
            prospective = RuntimeSnapshot(
                state=target,
                trading_mode=TradingMode.NORMAL,
                block_new_orders=False,
                connected=connected_value,
                account_verified=old.account_verified if account_verified is None else bool(account_verified),
                authentication_ok=old.authentication_ok if authentication_ok is None else bool(authentication_ok),
                reconciliation_status=old.reconciliation_status if reconciliation_status is None else reconciliation_status,
                recovery_requires_ack=recovery_required,
                operator_acknowledged=operator_ack,
                last_transition_at=now or self._clock(),
                transition_reason=reason,
                connection_epoch=old.connection_epoch if connection_epoch is None else connection_epoch,
                reconnect_attempts=old.reconnect_attempts if reconnect_attempts is None else reconnect_attempts,
                blockers=old.blockers if blockers is None else tuple(str(item) for item in blockers),
                broker_truth_fresh=old.broker_truth_fresh if broker_truth_fresh is None else bool(broker_truth_fresh),
                kill_switch_tripped=old.kill_switch_tripped if kill_switch_tripped is None else bool(kill_switch_tripped),
                risk_state_valid=old.risk_state_valid if risk_state_valid is None else bool(risk_state_valid),
            )
            if (
                self._base_ready(prospective)
                and not recovery_required
                and not old.blockers
                and not prospective.blockers
            ):
                mode, block = TradingMode.NORMAL, False
            else:
                mode, block = (TradingMode.FROZEN if connected_value else TradingMode.NO_TRANSPORT), True

        return RuntimeSnapshot(
            state=target,
            trading_mode=mode,
            block_new_orders=block,
            connected=connected_value,
            account_verified=old.account_verified if account_verified is None else bool(account_verified),
            authentication_ok=old.authentication_ok if authentication_ok is None else bool(authentication_ok),
            reconciliation_status=old.reconciliation_status if reconciliation_status is None else reconciliation_status,
            recovery_requires_ack=recovery_required,
            operator_acknowledged=operator_ack,
            last_transition_at=now or self._clock(),
            transition_reason=reason,
            connection_epoch=old.connection_epoch if connection_epoch is None else connection_epoch,
            reconnect_attempts=old.reconnect_attempts if reconnect_attempts is None else reconnect_attempts,
            blockers=old.blockers if blockers is None else tuple(str(item) for item in blockers),
            broker_truth_fresh=old.broker_truth_fresh if broker_truth_fresh is None else bool(broker_truth_fresh),
            kill_switch_tripped=old.kill_switch_tripped if kill_switch_tripped is None else bool(kill_switch_tripped),
            risk_state_valid=old.risk_state_valid if risk_state_valid is None else bool(risk_state_valid),
        )

    def transition(
        self,
        target: RuntimeState | str,
        reason: str = "",
        *,
        at: datetime | None = None,
        trading_mode: TradingMode | str | None = None,
        block_new_orders: bool | None = None,
        connected: bool | None = None,
        account_verified: bool | None = None,
        authentication_ok: bool | None = None,
        reconciliation_status: ReconciliationStatus | str | bool | None = None,
        recovery_requires_ack: bool | None = None,
        operator_acknowledged: bool | None = None,
        connection_epoch: int | None = None,
        reconnect_attempts: int | None = None,
        blockers: Iterable[object] | None = None,
        broker_truth_fresh: bool | None = None,
        kill_switch_tripped: bool | None = None,
        risk_state_valid: bool | None = None,
    ) -> RuntimeSnapshot:
        """Apply one explicit graph transition or raise a clear exception."""

        from_state = self._snapshot.state
        try:
            target_state = _enum_state(target)
        except RuntimeTransitionError as exc:
            self._emit(
                event_type="runtime_transition_rejected",
                from_state=from_state,
                to_state=None,
                reason=reason or str(exc),
                accepted=False,
                details={"requested_state": str(target), "error": str(exc)},
            )
            raise

        if target_state not in TRANSITION_GRAPH.get(from_state, frozenset()):
            error = RuntimeTransitionError(
                f"illegal_runtime_transition:{from_state.value}->{target_state.value}"
            )
            self._emit(
                event_type="runtime_transition_rejected",
                from_state=from_state,
                to_state=target_state,
                reason=reason or str(error),
                accepted=False,
                details={"error": str(error)},
            )
            raise error

        # A recovered session must always pass through RECOVERY_PENDING and an
        # explicit operator acknowledgement.  Never silently jump to READY.
        if (
            target_state == RuntimeState.READY
            and self._recovery_flow
            and not (self._snapshot.operator_acknowledged or bool(operator_acknowledged))
        ):
            error = RecoveryAcknowledgementRequired("recovery_operator_ack_required")
            self._emit(
                event_type="runtime_transition_rejected",
                from_state=from_state,
                to_state=target_state,
                reason=reason or str(error),
                accepted=False,
                details={"error": str(error)},
            )
            raise error

        if (
            target_state == RuntimeState.READY
            and from_state == RuntimeState.RECOVERY_PENDING
            and (
                self._snapshot.blockers
                or (blockers is not None and tuple(str(item) for item in blockers))
                or not self._snapshot.reconciliation_passed
                or not self._snapshot.broker_truth_fresh
                or not self._snapshot.account_verified
                or self._snapshot.kill_switch_tripped
            )
        ):
            error = RecoveryBlocked("recovery_blockers_not_cleared")
            self._emit(
                event_type="runtime_transition_rejected",
                from_state=from_state,
                to_state=target_state,
                reason=reason or str(error),
                accepted=False,
                details={"error": str(error)},
            )
            raise error

        if target_state == RuntimeState.RECONNECTING and from_state not in {
            RuntimeState.OFFLINE,
            RuntimeState.CONNECTING,
            RuntimeState.AUTHENTICATING,
            RuntimeState.BROKER_SYNCING,
        }:
            self._recovery_flow = True
        if target_state == RuntimeState.RECOVERY_PENDING:
            self._recovery_flow = True
        if target_state == RuntimeState.HALTED:
            self._recovery_flow = False
        if target_state == RuntimeState.READY and (
            self._snapshot.operator_acknowledged or bool(operator_acknowledged)
        ):
            self._recovery_flow = False

        self._snapshot = self._build_snapshot(
            target_state,
            reason=reason,
            now=at,
            trading_mode=trading_mode,
            block_new_orders=block_new_orders,
            connected=connected,
            account_verified=account_verified,
            authentication_ok=authentication_ok,
            reconciliation_status=reconciliation_status,
            recovery_requires_ack=recovery_requires_ack,
            operator_acknowledged=operator_acknowledged,
            connection_epoch=connection_epoch,
            reconnect_attempts=reconnect_attempts,
            blockers=blockers,
            broker_truth_fresh=broker_truth_fresh,
            kill_switch_tripped=kill_switch_tripped,
            risk_state_valid=risk_state_valid,
        )
        self._emit(
            event_type="runtime_transition",
            from_state=from_state,
            to_state=target_state,
            reason=reason,
            accepted=True,
        )
        return self._snapshot

    def update_conditions(
        self,
        reason: str = "conditions_updated",
        *,
        trading_mode: TradingMode | str | None = None,
        block_new_orders: bool | None = None,
        connected: bool | None = None,
        account_verified: bool | None = None,
        authentication_ok: bool | None = None,
        reconciliation_status: ReconciliationStatus | str | bool | None = None,
        recovery_requires_ack: bool | None = None,
        operator_acknowledged: bool | None = None,
        connection_epoch: int | None = None,
        reconnect_attempts: int | None = None,
        blockers: Iterable[object] | None = None,
        broker_truth_fresh: bool | None = None,
        kill_switch_tripped: bool | None = None,
        risk_state_valid: bool | None = None,
    ) -> RuntimeSnapshot:
        """Publish observations without changing the lifecycle state."""

        current = self._snapshot.state
        self._snapshot = self._build_snapshot(
            current,
            reason=reason,
            trading_mode=trading_mode,
            block_new_orders=block_new_orders,
            connected=connected,
            account_verified=account_verified,
            authentication_ok=authentication_ok,
            reconciliation_status=reconciliation_status,
            recovery_requires_ack=recovery_requires_ack,
            operator_acknowledged=operator_acknowledged,
            connection_epoch=connection_epoch,
            reconnect_attempts=reconnect_attempts,
            blockers=blockers,
            broker_truth_fresh=broker_truth_fresh,
            kill_switch_tripped=kill_switch_tripped,
            risk_state_valid=risk_state_valid,
        )
        self._emit(
            event_type="runtime_conditions_updated",
            from_state=current,
            to_state=current,
            reason=reason,
            accepted=True,
        )
        return self._snapshot

    def complete_reconciliation(
        self,
        passed: bool,
        *,
        reason: str = "reconciliation_completed",
        blockers: Iterable[object] = (),
        failure_state: RuntimeState = RuntimeState.HALTED,
        account_verified: bool | None = None,
        broker_truth_fresh: bool = True,
        connected: bool | None = None,
    ) -> RuntimeSnapshot:
        """Close reconciliation and enforce the recovery acknowledgement gate."""

        if not passed:
            target = _enum_state(failure_state)
            if target not in {RuntimeState.DEGRADED, RuntimeState.HALTED}:
                raise RuntimeTransitionError("reconciliation_failure_state_must_be_degraded_or_halted")
            return self.transition(
                target,
                reason=reason,
                reconciliation_status=ReconciliationStatus.FAILED,
                blockers=tuple(str(item) for item in blockers) or ("reconciliation_failed",),
                block_new_orders=True,
                connected=connected,
                broker_truth_fresh=False,
            )

        if self._recovery_flow:
            return self.transition(
                RuntimeState.RECOVERY_PENDING,
                reason=reason,
                reconciliation_status=ReconciliationStatus.PASS,
                blockers=tuple(str(item) for item in blockers),
                connected=connected,
                account_verified=account_verified,
                broker_truth_fresh=broker_truth_fresh,
                recovery_requires_ack=True,
                operator_acknowledged=False,
            )

        return self.transition(
            RuntimeState.READY,
            reason=reason,
            reconciliation_status=ReconciliationStatus.PASS,
            blockers=tuple(str(item) for item in blockers),
            connected=connected,
            account_verified=account_verified,
            broker_truth_fresh=broker_truth_fresh,
            recovery_requires_ack=False,
            operator_acknowledged=False,
        )

    def acknowledge_recovery(self, *, operator: str = "operator", reason: str = "operator_ack") -> RuntimeSnapshot:
        """Record explicit recovery acknowledgement without bypassing blockers."""

        if self.state != RuntimeState.RECOVERY_PENDING:
            error = RuntimeTransitionError("recovery_ack_only_valid_in_recovery_pending")
            self._emit(
                event_type="operator_ack_rejected",
                from_state=self.state,
                to_state=self.state,
                reason=reason or str(error),
                accepted=False,
                details={"operator": operator, "error": str(error)},
            )
            raise error
        self._snapshot = self.update_conditions(
            reason=reason,
            operator_acknowledged=True,
            recovery_requires_ack=True,
        )
        self._emit(
            event_type="operator_acknowledged",
            from_state=self.state,
            to_state=self.state,
            reason=reason,
            accepted=True,
            details={"operator": operator},
        )
        return self._snapshot

    # Short aliases used by supervisor/integration callers.
    operator_ack = acknowledge_recovery
    ack_recovery = acknowledge_recovery
    ack_operator = acknowledge_recovery

    def resume_after_recovery(self, *, reason: str = "recovery_resumed") -> RuntimeSnapshot:
        if self.state != RuntimeState.RECOVERY_PENDING:
            raise RuntimeTransitionError("resume_requires_recovery_pending")
        if not self._snapshot.operator_acknowledged:
            error = RecoveryAcknowledgementRequired("recovery_operator_ack_required")
            self._emit(
                event_type="runtime_transition_rejected",
                from_state=self.state,
                to_state=RuntimeState.READY,
                reason=reason or str(error),
                accepted=False,
                details={"error": str(error)},
            )
            raise error
        return self.transition(
            RuntimeState.READY,
            reason=reason,
            trading_mode=TradingMode.NORMAL,
            block_new_orders=False,
            recovery_requires_ack=False,
        )


__all__ = [
    "ALLOWED_TRANSITIONS",
    "IllegalTransitionError",
    "InvalidRuntimeTransition",
    "InvalidTransitionError",
    "RecoveryAcknowledgementRequired",
    "RecoveryBlocked",
    "RuntimeStateMachine",
    "RuntimeTransitionError",
    "TRANSITION_GRAPH",
]
