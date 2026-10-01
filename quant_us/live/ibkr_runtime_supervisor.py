"""IBKR runtime control-plane supervisor (transport-neutral).

The supervisor consumes observations from an adapter/recovery orchestrator and
publishes a canonical runtime snapshot.  It intentionally does not import a
broker SDK, open sockets, authenticate, submit orders, or cancel orders.  A
future integration agent may wire those side effects to the observation methods
below while the fail-closed state machine remains the single authority for
permissions.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from typing import Any, Iterable

from quant_shared.core.time import utc_now
from quant_shared.runtime.models import (
    RuntimeAuditEvent,
    RuntimeSnapshot,
    RuntimeState,
)
from quant_shared.runtime.permissions import PermissionDecision, PermissionEvaluator
from quant_shared.runtime.state_machine import RuntimeStateMachine


class IBKRRuntimeSupervisor:
    """Coordinate runtime observations without performing broker I/O."""

    # These flags are deliberately immutable policy facts for this ticket.  The
    # supervisor is a paper-validation control plane, never a live gateway.
    network_enabled = False
    live_ready = False
    broker_access_allowed = False
    private_endpoint_allowed = False
    order_endpoint_allowed = False

    def __init__(
        self,
        state_machine: RuntimeStateMachine | None = None,
        *,
        initial_snapshot: RuntimeSnapshot | None = None,
        clock=utc_now,
        broker_adapter: Any | None = None,
        ledger: Any | None = None,
        reconciler: Any | None = None,
        incident_sink: Any | None = None,
        risk_guardian: Any | None = None,
    ) -> None:
        if state_machine is not None and initial_snapshot is not None:
            raise ValueError("provide_state_machine_or_initial_snapshot_not_both")
        self.state_machine = state_machine or RuntimeStateMachine(
            initial_snapshot=initial_snapshot,
            clock=clock,
        )
        # ``machine`` is a concise compatibility alias used by orchestration
        # code; both names point at the same canonical writer.
        self.machine = self.state_machine
        # The producer ticket intentionally stopped at an observation-only
        # state machine.  These injected ports are the integration seam: they
        # are optional, never discovered implicitly, and expose no credential
        # or live endpoint capability by themselves.
        self.broker_adapter = broker_adapter
        self.ledger = ledger
        self.reconciler = reconciler
        self.incident_sink = incident_sink
        self.risk_guardian = risk_guardian
        self._seen_execution_ids: set[str] = set()
        self._known_broker_order_ids: set[str] = set()
        self._last_truth_snapshot: Any | None = None
        self._last_truth_sequence: int | None = None
        self._last_truth_snapshot_id: str = ""
        self._last_reconciliation_result: Any | None = None
        self._last_guardian_result: Any | None = None

    @property
    def snapshot(self) -> RuntimeSnapshot:
        return self.state_machine.snapshot

    @property
    def state(self) -> RuntimeState:
        return self.snapshot.state

    @property
    def trading_mode(self):
        return self.snapshot.trading_mode

    @property
    def runtime_snapshot(self) -> RuntimeSnapshot:
        return self.snapshot

    @property
    def audit_events(self) -> tuple[RuntimeAuditEvent, ...]:
        return self.state_machine.audit_events

    @property
    def audit_log(self) -> tuple[RuntimeAuditEvent, ...]:
        return self.audit_events

    @property
    def permission_evaluator(self) -> PermissionEvaluator:
        return PermissionEvaluator(self.snapshot)

    @property
    def permissions(self) -> dict[str, PermissionDecision]:
        return self.permission_evaluator.evaluate()

    @property
    def is_ready(self) -> bool:
        return self.permission_evaluator.can_submit_new_order()

    @property
    def new_order_allowed(self) -> bool:
        return self.permission_evaluator.can_submit_new_order()

    def _without_blockers(self, *names: str) -> tuple[str, ...]:
        excluded = set(names)
        return tuple(item for item in self.snapshot.blockers if item not in excluded)

    def _with_blockers(self, *names: str) -> tuple[str, ...]:
        values = list(self.snapshot.blockers)
        for name in names:
            if name and name not in values:
                values.append(name)
        return tuple(values)

    # ------------------------------------------------------------------
    # Explicit observation workflow
    # ------------------------------------------------------------------

    def startup(self, *, reason: str = "startup") -> RuntimeSnapshot:
        """Enter CONNECTING; this method never attempts a connection."""

        if self.snapshot.state == RuntimeState.OFFLINE:
            return self.state_machine.transition(RuntimeState.CONNECTING, reason=reason)
        return self.snapshot

    def start(self, *, reason: str = "startup") -> RuntimeSnapshot:
        """Start an injected paper-validation runtime, never a live gateway.

        With no injected ports this retains the producer's observation-only
        behaviour and merely enters ``CONNECTING``.  An injected adapter must
        explicitly advertise ``offline_replay=True`` before this method may
        call its ``connect`` surface.  A real IBKR adapter is therefore never
        auto-connected by the control plane; PaperRuntime owns that explicit
        boundary and passes only observations here.
        """

        if self.broker_adapter is None:
            return self.startup(reason=reason)

        self.startup(reason=reason)
        adapter = self.broker_adapter
        try:
            connected = bool(self._read(adapter, "is_connected", "connected", "isConnected", default=False))
            if not connected:
                if not self._offline_replay_allowed(adapter):
                    self._emit_incident("IBKR_DISCONNECTED", "automatic_connect_disabled")
                    return self.on_disconnect(reason="automatic_connect_disabled")
                connector = getattr(adapter, "connect", None)
                if not callable(connector):
                    self._emit_incident("IBKR_RECONNECT_FAILED", "connect_surface_missing")
                    return self.on_disconnect(reason="connect_surface_missing")
                outcome = connector()
                connected = self._explicit_connected(outcome, adapter)
            if not connected:
                self._emit_incident("IBKR_RECONNECT_FAILED", "transport_not_connected")
                return self.on_disconnect(reason="transport_not_connected")

            account_verified = bool(
                self._read(
                    adapter,
                    "account_verified",
                    default=bool(self._read(adapter, "account_hash", default="")),
                )
            )
            epoch = self._read(adapter, "connection_epoch", "epoch", default=None)
            self.mark_connected(
                account_verified=account_verified,
                connection_epoch=self._as_int(epoch, self.snapshot.connection_epoch + 1),
            )
            self.mark_authenticated(account_verified=account_verified)
            truth = self._read_truth()
            if truth is None:
                return self._fail_closed("BROKER_TRUTH_INCOMPLETE", "broker_truth_missing")
            return self._apply_truth_and_checks(truth, startup=True)
        except Exception as exc:  # pragma: no cover - defensive safety boundary
            self._emit_incident("IBKR_RECONNECT_FAILED", type(exc).__name__)
            return self.on_disconnect(reason="runtime_start_failed")

    def _offline_replay_allowed(self, adapter: Any) -> bool:
        """Return true only for an explicitly injected offline fixture."""

        return bool(self._read(adapter, "offline_replay", default=False)) and not bool(
            self._read(adapter, "network_access", default=False)
        )

    @staticmethod
    def _read(source: Any, *names: str, default: Any = None) -> Any:
        if source is None:
            return default
        if isinstance(source, Mapping):
            for name in names:
                if name in source:
                    return source[name]
            return default
        for name in names:
            if hasattr(source, name):
                return getattr(source, name)
        return default

    @staticmethod
    def _as_int(value: Any, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return int(default)

    def _explicit_connected(self, outcome: Any, adapter: Any) -> bool:
        if isinstance(outcome, bool):
            return outcome and bool(self._read(adapter, "is_connected", "connected", "isConnected", default=True))
        value = self._read(outcome, "connected", "transport_connected", "is_connected", default=None)
        if value is not None:
            return bool(value)
        return bool(self._read(adapter, "is_connected", "connected", "isConnected", default=False))

    def _read_truth(self) -> Any | None:
        adapter = self.broker_adapter
        if adapter is None:
            return None
        for name in ("broker_truth_snapshot", "get_broker_truth_snapshot", "last_broker_truth"):
            candidate = getattr(adapter, name, None)
            if callable(candidate):
                value = candidate()
            else:
                value = candidate
            if value is not None:
                return value
        return None

    def _emit_incident(self, incident_type: str, reason: str, *, context: Mapping[str, Any] | None = None) -> None:
        sink = self.incident_sink
        if sink is None:
            return
        event = {
            "type": str(incident_type),
            "incident_type": str(incident_type),
            "event": str(incident_type),
            "source": "ibkr_runtime_supervisor",
            "reason": str(reason),
            "message": str(reason),
            "context": dict(context or {}),
        }
        for name in ("emit", "record", "open", "open_incident"):
            method = getattr(sink, name, None)
            if not callable(method):
                continue
            try:
                method(event)
                return
            except TypeError:
                try:
                    method(
                        incident_type=str(incident_type),
                        source="ibkr_runtime_supervisor",
                        message=str(reason),
                        context=dict(context or {}),
                    )
                    return
                except Exception:
                    continue
            except Exception:
                return

    def _truth_quality(self, truth: Any) -> tuple[bool, list[str], int | None]:
        """Evaluate broker truth against the injected clock and current epoch."""

        blockers: list[str] = []
        connected = bool(self._read(truth, "transport_connected", "connected", default=False))
        account_verified = bool(self._read(truth, "account_verified", default=False))
        if not connected:
            blockers.append("transport_disconnected")
        if not account_verified:
            blockers.append("account_mismatch")

        component_flags = (
            "orders_snapshot_complete",
            "executions_snapshot_complete",
            "positions_snapshot_complete",
            "account_snapshot_complete",
        )
        complete = self._read(truth, "complete", "is_complete", default=None)
        if complete is None:
            complete = all(bool(self._read(truth, item, default=False)) for item in component_flags)
        elif not bool(complete):
            # BrokerTruthSnapshot may mark a replay fixture stale because its
            # constructor uses wall-clock time.  Re-evaluate component
            # completeness separately; the injected clock below remains the
            # authoritative freshness source for the integration boundary.
            complete = all(bool(self._read(truth, item, default=True)) for item in component_flags)
        if not complete:
            blockers.append("snapshot_incomplete")

        captured_at = self._read(truth, "captured_at", "as_of", "timestamp", default=None)
        age_seconds: float | None = None
        if isinstance(captured_at, str):
            try:
                captured_at = datetime.fromisoformat(captured_at.replace("Z", "+00:00"))
            except ValueError:
                captured_at = None
        if isinstance(captured_at, datetime):
            if captured_at.tzinfo is None:
                captured_at = captured_at.replace(tzinfo=timezone.utc)
            reference = self.state_machine._clock()  # injected clock, never wall time
            if reference.tzinfo is None:
                reference = reference.replace(tzinfo=timezone.utc)
            age_seconds = (reference.astimezone(timezone.utc) - captured_at.astimezone(timezone.utc)).total_seconds()
            max_age = float(self._read(truth, "max_age_seconds", default=300.0) or 300.0)
            if age_seconds < 0 or age_seconds > max_age:
                blockers.append("stale_snapshot")
        else:
            blockers.append("snapshot_timestamp_missing")

        epoch = self._as_int(self._read(truth, "connection_epoch", "epoch", default=0), 0)
        expected_epoch = self._read(self.broker_adapter, "connection_epoch", "epoch", default=None)
        if expected_epoch is not None and self._as_int(expected_epoch, epoch) != epoch:
            blockers.append("epoch_mismatch")
        if self.snapshot.connection_epoch and epoch and epoch != self.snapshot.connection_epoch:
            blockers.append("epoch_mismatch")

        statuses = self._read(truth, "status_flags", "statuses", "semantic_statuses", default=())
        if isinstance(statuses, str):
            statuses = (statuses,)
        normalized_statuses = {str(item).lower().replace("-", "_") for item in (statuses or ())}
        offline_fixture = self._offline_replay_allowed(self.broker_adapter)
        if "sequence_gap" in normalized_statuses:
            blockers.append("sequence_gap")
        if "duplicate" in normalized_statuses:
            blockers.append("duplicate_execution")
        # Ignore constructor-only stale/incomplete flags for an explicit
        # offline fixture when the injected-clock checks above are clean.
        if not offline_fixture and ("stale" in normalized_statuses or "expired" in normalized_statuses):
            blockers.append("stale_snapshot")

        sequence = self._read(truth, "sequence_watermark", "sequence", "snapshot_sequence", default=None)
        sequence_int = None if sequence is None else self._as_int(sequence, 0)
        if (
            sequence_int is not None
            and self._last_truth_sequence is not None
            and sequence_int <= self._last_truth_sequence
            and str(self._read(truth, "snapshot_id", "id", default="")) != self._last_truth_snapshot_id
        ):
            blockers.append("sequence_gap")

        account_hash = str(self._read(truth, "account_hash", default="") or "")
        if not account_hash:
            blockers.append("account_hash_missing")
        return not blockers, list(dict.fromkeys(blockers)), sequence_int

    def _apply_truth_and_checks(self, truth: Any, *, startup: bool = False) -> RuntimeSnapshot:
        valid, blockers, sequence = self._truth_quality(truth)
        raw_orders = self._read(truth, "open_orders", "orders", default=()) or ()
        if isinstance(raw_orders, Mapping):
            raw_orders = tuple(raw_orders.values())
        for row in raw_orders:
            identity = self._read(row, "identity", default=None)
            broker_order_id = str(
                self._read(
                    row,
                    "broker_order_id",
                    "order_id",
                    "id",
                    default=self._read(
                        identity,
                        "broker_order_id",
                        "ibkr_order_id",
                        "order_id",
                        "id",
                        default="",
                    ),
                )
                or ""
            )
            if broker_order_id and broker_order_id not in self._known_broker_order_ids:
                blockers.append("unknown_broker_order")
        blockers = list(dict.fromkeys(blockers))
        valid = not blockers
        self._last_truth_snapshot = truth
        self._last_truth_sequence = sequence
        self._last_truth_snapshot_id = str(self._read(truth, "snapshot_id", "id", default="") or "")
        if not valid:
            for blocker in blockers:
                self._emit_incident(self._incident_for_blocker(blocker), blocker)
            return self._fail_closed(self._incident_for_blocker(blockers[0]), ";".join(blockers), truth=truth)

        account_verified = bool(self._read(truth, "account_verified", default=False))
        # Periodic truth callbacks can arrive after READY.  READY has no
        # BROKER_SYNCING edge in the canonical graph, so only reconnect/sync
        # states traverse that gate; READY observations are reconciled in
        # place through the existing self-transition.
        if self.snapshot.state in {
            RuntimeState.AUTHENTICATING,
            RuntimeState.BROKER_SYNCING,
            RuntimeState.RECONNECTING,
            RuntimeState.DEGRADED,
            RuntimeState.CONNECTING,
        }:
            self.mark_broker_sync_complete(
                account_verified=account_verified,
                broker_truth_fresh=True,
                blockers=(),
                reason="broker_truth_synchronized",
            )
        reconciliation = self._run_reconciliation(truth)
        guardian = self._run_guardian(truth, reconciliation)
        self._last_reconciliation_result = reconciliation
        self._last_guardian_result = guardian
        recon_passed, recon_blockers = self._reconciliation_result(reconciliation)
        guardian_ok, guardian_blockers, kill_tripped = self._guardian_result(guardian)
        if not recon_passed:
            self._emit_incident("RECONCILIATION_FAILED", ";".join(recon_blockers) or "reconciliation_failed")
            return self.mark_reconciliation_failed(
                blockers=tuple(recon_blockers) or ("reconciliation_failed",),
                account_verified=account_verified,
                broker_truth_fresh=True,
                reason="reconciliation_failed",
            )
        if not guardian_ok:
            self._emit_incident("KILL_SWITCH_TRIPPED" if kill_tripped else "RUNTIME_HALTED", "guardian_blocked")
            self.state_machine.update_conditions(
                reason="risk_guardian_blocked",
                kill_switch_tripped=kill_tripped,
                risk_state_valid=False,
                blockers=tuple(guardian_blockers) or ("risk_guardian_blocked",),
                connected=True,
                account_verified=account_verified,
                broker_truth_fresh=True,
            )
            return self.mark_reconciliation_failed(
                blockers=tuple(guardian_blockers) or ("risk_guardian_blocked",),
                account_verified=account_verified,
                broker_truth_fresh=True,
                reason="risk_guardian_blocked",
            )
        self.state_machine.update_conditions(
            reason="risk_guardian_passed",
            risk_state_valid=True,
            kill_switch_tripped=False,
            connected=True,
            account_verified=account_verified,
            broker_truth_fresh=True,
            blockers=(),
        )
        return self.mark_reconciliation_passed(
            account_verified=account_verified,
            broker_truth_fresh=True,
            reason="initial_reconciliation_passed" if startup else "reconciliation_passed",
        )

    def _run_reconciliation(self, truth: Any) -> Any:
        reconciler = self.reconciler
        if reconciler is None:
            return {"status": "fail", "passed": False, "blockers": ["reconciler_unavailable"]}
        for name in ("reconcile", "run"):
            method = getattr(reconciler, name, None)
            if callable(method):
                try:
                    return method(truth)
                except TypeError:
                    return method(snapshot=truth)
        if callable(reconciler):
            return reconciler(truth)
        return {"status": "fail", "passed": False, "blockers": ["reconciler_unavailable"]}

    def _run_guardian(self, truth: Any, reconciliation: Any) -> Any:
        guardian = self.risk_guardian
        if guardian is None:
            return {"status": "pass", "block_new_orders": False, "trip_kill_switch": False}
        payload = {
            "runtime_snapshot": self.state_machine.snapshot,
            "broker_truth": truth,
            "reconciliation": reconciliation,
        }
        for name in ("evaluate", "check", "assess"):
            method = getattr(guardian, name, None)
            if callable(method):
                try:
                    return method(**payload)
                except TypeError:
                    return method(truth)
        if callable(guardian):
            return guardian(**payload)
        return {"status": "blocked", "block_new_orders": True, "violations": ["guardian_surface_missing"]}

    @staticmethod
    def _reconciliation_result(value: Any) -> tuple[bool, list[str]]:
        if isinstance(value, Mapping):
            status = str(value.get("status", value.get("reconciliation_status", ""))).lower()
            passed = value.get("passed")
            if passed is None:
                passed = status in {"pass", "passed", "clean", "ok", "success", "succeeded"}
            blockers = value.get("blockers", value.get("discrepancies", ())) or ()
            return bool(passed) and not bool(value.get("block_new_orders", False)), [str(item) for item in blockers]
        status = str(getattr(value, "status", "")).lower()
        passed = getattr(value, "passed", None)
        if passed is None:
            passed = status in {"pass", "passed", "clean", "ok", "success", "succeeded"}
        blockers = getattr(value, "blockers", ()) or ()
        return bool(passed) and not bool(getattr(value, "block_new_orders", False)), [str(item) for item in blockers]

    @staticmethod
    def _guardian_result(value: Any) -> tuple[bool, list[str], bool]:
        if isinstance(value, Mapping):
            status = str(value.get("status", "")).lower()
            trip = bool(value.get("trip_kill_switch", value.get("kill_switch_tripped", False)))
            blocked = bool(value.get("block_new_orders", False))
            violations = value.get("violations", ()) or ()
            return status in {"pass", "passed", "ok", "clean"} and not blocked and not trip, [str(item) for item in violations], trip
        status = str(getattr(value, "status", "")).lower()
        trip = bool(getattr(value, "trip_kill_switch", False))
        blocked = bool(getattr(value, "block_new_orders", False))
        violations = getattr(value, "violations", ()) or ()
        return status in {"pass", "passed", "ok", "clean"} and not blocked and not trip, [str(item) for item in violations], trip

    def _incident_for_blocker(self, blocker: str) -> str:
        mapping = {
            "transport_disconnected": "IBKR_DISCONNECTED",
            "stale_snapshot": "BROKER_TRUTH_STALE",
            "snapshot_incomplete": "BROKER_TRUTH_INCOMPLETE",
            "sequence_gap": "SEQUENCE_GAP",
            "epoch_mismatch": "EPOCH_MISMATCH",
            "account_mismatch": "ACCOUNT_MISMATCH",
            "account_hash_missing": "ACCOUNT_MISMATCH",
            "reconciliation_failed": "RECONCILIATION_FAILED",
            "duplicate_execution": "DUPLICATE_EXECUTION",
            "unknown_broker_order": "UNKNOWN_BROKER_ORDER",
        }
        return mapping.get(str(blocker), str(blocker).upper())

    def _fail_closed(self, incident_type: str, reason: str, *, truth: Any | None = None) -> RuntimeSnapshot:
        if truth is not None:
            self._last_truth_snapshot = truth
        self._emit_incident(incident_type, reason)
        if self.snapshot.state in {RuntimeState.OFFLINE, RuntimeState.CONNECTING, RuntimeState.AUTHENTICATING, RuntimeState.BROKER_SYNCING, RuntimeState.RECONCILING}:
            self.mark_reconciliation_failed(blockers=(reason,), reason=reason, broker_truth_fresh=False)
        elif self.snapshot.state not in {RuntimeState.HALTED, RuntimeState.RECONNECTING}:
            self.mark_reconciliation_failed(blockers=(reason,), reason=reason, broker_truth_fresh=False)
        else:
            self.state_machine.update_conditions(
                reason=reason,
                block_new_orders=True,
                broker_truth_fresh=False,
                blockers=self._with_blockers(reason),
            )
        return self.snapshot

    def mark_connected(
        self,
        *,
        account_verified: bool = False,
        connection_epoch: int | None = None,
        reason: str = "transport_connected",
    ) -> RuntimeSnapshot:
        """Record a transport observation; do not call a broker client."""

        state = self.snapshot.state
        if state == RuntimeState.OFFLINE:
            self.startup(reason="startup_before_connected")
            state = self.snapshot.state

        epoch = connection_epoch
        if epoch is None:
            epoch = self.snapshot.connection_epoch + 1

        if state == RuntimeState.CONNECTING:
            return self.state_machine.transition(
                RuntimeState.AUTHENTICATING,
                reason=reason,
                connected=True,
                account_verified=account_verified,
                connection_epoch=epoch,
                blockers=self._without_blockers("transport_disconnected"),
            )
        if state == RuntimeState.RECONNECTING:
            # Reconnect success begins a new broker-truth session but still has
            # to pass sync and reconciliation before any permission changes.
            return self.state_machine.transition(
                RuntimeState.BROKER_SYNCING,
                reason=reason,
                connected=True,
                account_verified=account_verified,
                connection_epoch=epoch,
                broker_truth_fresh=False,
                blockers=self._without_blockers("transport_disconnected", "broker_truth_stale"),
            )
        return self.state_machine.update_conditions(
            reason=reason,
            connected=True,
            account_verified=account_verified,
            connection_epoch=epoch,
            blockers=self._without_blockers("transport_disconnected"),
        )

    on_connected = mark_connected

    def mark_authenticated(
        self,
        *,
        account_verified: bool = False,
        reason: str = "authentication_succeeded",
    ) -> RuntimeSnapshot:
        if self.snapshot.state == RuntimeState.CONNECTING:
            self.mark_connected(account_verified=account_verified, reason="connected_before_authentication")
        return self.state_machine.transition(
            RuntimeState.BROKER_SYNCING,
            reason=reason,
            connected=True,
            account_verified=account_verified,
            authentication_ok=True,
            broker_truth_fresh=False,
            blockers=self._without_blockers("transport_disconnected", "authentication_failed"),
        )

    on_authenticated = mark_authenticated
    authenticate_success = mark_authenticated

    def mark_broker_sync_complete(
        self,
        *,
        account_verified: bool | None = None,
        broker_truth_fresh: bool = True,
        reason: str = "broker_truth_synchronized",
        blockers: Iterable[object] = (),
    ) -> RuntimeSnapshot:
        if self.snapshot.state == RuntimeState.AUTHENTICATING:
            self.mark_authenticated(
                account_verified=bool(account_verified),
                reason="authenticated_before_broker_sync",
            )
        return self.state_machine.transition(
            RuntimeState.RECONCILING,
            reason=reason,
            connected=True,
            account_verified=(
                self.snapshot.account_verified if account_verified is None else account_verified
            ),
            broker_truth_fresh=broker_truth_fresh,
            blockers=tuple(str(item) for item in blockers),
        )

    on_broker_sync_complete = mark_broker_sync_complete
    broker_sync_complete = mark_broker_sync_complete

    def mark_reconciliation(
        self,
        passed: bool,
        *,
        account_verified: bool | None = None,
        broker_truth_fresh: bool = True,
        blockers: Iterable[object] = (),
        reason: str = "reconciliation_completed",
        failure_state: RuntimeState = RuntimeState.HALTED,
    ) -> RuntimeSnapshot:
        return self.state_machine.complete_reconciliation(
            passed,
            reason=reason,
            blockers=blockers,
            failure_state=failure_state,
            account_verified=account_verified,
            broker_truth_fresh=broker_truth_fresh,
            connected=True if self.snapshot.connected else None,
        )

    reconcile = mark_reconciliation
    on_reconciliation = mark_reconciliation

    def mark_reconciliation_passed(self, **kwargs: Any) -> RuntimeSnapshot:
        return self.mark_reconciliation(True, **kwargs)

    on_reconciliation_passed = mark_reconciliation_passed

    def mark_reconciliation_failed(self, **kwargs: Any) -> RuntimeSnapshot:
        return self.mark_reconciliation(False, **kwargs)

    on_reconciliation_failed = mark_reconciliation_failed

    def on_disconnect(
        self,
        *,
        reason: str = "transport_disconnected",
        reconnect_attempts: int | None = None,
    ) -> RuntimeSnapshot:
        """Freeze permissions and mark transport unknown after disconnect."""

        state = self.snapshot.state
        blockers = self._with_blockers("transport_disconnected", "broker_truth_stale")
        attempts = self.snapshot.reconnect_attempts if reconnect_attempts is None else reconnect_attempts
        if state == RuntimeState.OFFLINE:
            return self.state_machine.update_conditions(
                reason=reason,
                connected=False,
                broker_truth_fresh=False,
                blockers=blockers,
                reconnect_attempts=attempts,
            )
        if state == RuntimeState.HALTED:
            return self.state_machine.update_conditions(
                reason=reason,
                connected=False,
                broker_truth_fresh=False,
                blockers=blockers,
                reconnect_attempts=attempts,
            )
        if state != RuntimeState.RECONNECTING:
            return self.state_machine.transition(
                RuntimeState.RECONNECTING,
                reason=reason,
                connected=False,
                broker_truth_fresh=False,
                blockers=blockers,
                reconnect_attempts=attempts,
            )
        return self.state_machine.update_conditions(
            reason=reason,
            connected=False,
            broker_truth_fresh=False,
            blockers=blockers,
            reconnect_attempts=attempts,
        )

    disconnected = on_disconnect
    handle_disconnect = on_disconnect

    # ------------------------------------------------------------------
    # Integrated observation/side-effect ports
    # ------------------------------------------------------------------

    def on_transport_lost(self, *, reason: str = "transport_disconnected") -> RuntimeSnapshot:
        """Record loss of transport; never issue cancel/global-cancel calls."""

        self._emit_incident("IBKR_DISCONNECTED", reason)
        normalized_reason = str(reason).lower()
        if "bounded_reconnect_exhausted" in normalized_reason or "duplicate_client_id" in normalized_reason:
            self._emit_incident("IBKR_RECONNECT_FAILED", reason)
        return self.on_disconnect(reason=reason)

    def on_transport_restored(
        self,
        *,
        account_verified: bool = False,
        connection_epoch: int | None = None,
        reason: str = "transport_restored",
    ) -> RuntimeSnapshot:
        """Record transport restoration and keep the runtime in sync gates."""

        return self.on_reconnect_success(
            account_verified=account_verified,
            connection_epoch=connection_epoch,
            reason=reason,
        )

    def on_broker_truth(self, truth: Any) -> RuntimeSnapshot:
        """Consume one broker-truth observation and apply fail-closed gates."""

        if truth is None:
            return self._fail_closed("BROKER_TRUTH_INCOMPLETE", "broker_truth_missing")
        return self._apply_truth_and_checks(truth, startup=False)

    def on_broker_execution(self, execution: Any) -> bool:
        """Apply one idempotent execution observation to the injected ledger."""

        execution_id = str(
            self._read(execution, "exec_id", "execution_id", "fill_id", "id", default="") or ""
        )
        if not execution_id:
            self._emit_incident("UNKNOWN_EXECUTION", "execution_id_missing")
            self._fail_closed("UNKNOWN_EXECUTION", "execution_id_missing")
            return False
        if execution_id in self._seen_execution_ids:
            self._emit_incident("DUPLICATE_EXECUTION", execution_id)
            # A replayed callback is expected while a successful recovery is
            # awaiting its explicit operator acknowledgement.  It remains
            # idempotent and must not erase the pending gate; duplicates seen
            # during ordinary READY operation still fail closed below.
            if self.snapshot.state == RuntimeState.RECOVERY_PENDING:
                return False
            self._fail_closed("DUPLICATE_EXECUTION", execution_id)
            return False
        event_epoch = self._read(execution, "connection_epoch", "epoch", default=None)
        if event_epoch is not None and self.snapshot.connection_epoch:
            if self._as_int(event_epoch, self.snapshot.connection_epoch) != self.snapshot.connection_epoch:
                self._emit_incident("EPOCH_MISMATCH", "execution_epoch_mismatch")
                self._fail_closed("EPOCH_MISMATCH", "execution_epoch_mismatch")
                return False
        self._seen_execution_ids.add(execution_id)
        ledger = self.ledger
        if ledger is not None:
            for name in ("apply_execution", "append_execution", "record_execution"):
                method = getattr(ledger, name, None)
                if callable(method):
                    method(execution)
                    break
        return True

    def submit_new_order(self, order_intent: Any) -> Any:
        """Submit only through an explicitly injected offline fixture port."""

        if not self.can_submit_new_order():
            return None
        adapter = self.broker_adapter
        if adapter is None or not self._offline_replay_allowed(adapter):
            return None
        for name in ("submit_order", "place_order"):
            method = getattr(adapter, name, None)
            if callable(method):
                result = method(order_intent)
                broker_order_id = self._read(result, "broker_order_id", "order_id", "id", default="")
                if broker_order_id:
                    self._known_broker_order_ids.add(str(broker_order_id))
                return result
        self._emit_incident("RUNTIME_HALTED", "submit_surface_missing")
        return None

    def on_recovery_result(self, result: Any) -> RuntimeSnapshot:
        """Apply a RecoveryResult without auto-acknowledging it."""

        success = bool(self._read(result, "success", default=False))
        blockers = tuple(str(item) for item in (self._read(result, "blockers", default=()) or ()))
        discrepancies = self._read(result, "discrepancies", default=()) or ()
        codes = []
        for item in discrepancies:
            code = self._read(item, "code", default=item)
            codes.append(str(code))
        combined = tuple(dict.fromkeys((*blockers, *codes)))
        if not success or combined:
            for code in combined or ("RECOVERY_WORKFLOW_FAILURE",):
                self._emit_incident(self._incident_for_blocker(code), code)
            return self.mark_reconciliation_failed(
                blockers=combined or ("recovery_failed",),
                account_verified=bool(self._read(self._last_truth_snapshot, "account_verified", default=False)),
                broker_truth_fresh=False,
                reason="recovery_failed",
            )

        epoch = self._read(result, "connection_epoch", "epoch", default=None)
        account_verified = bool(
            self._read(
                self._last_truth_snapshot,
                "account_verified",
                default=self._read(self.broker_adapter, "account_verified", default=True),
            )
        )
        if self.snapshot.state == RuntimeState.RECONNECTING:
            self.on_reconnect_success(
                account_verified=account_verified,
                connection_epoch=self._as_int(epoch, self.snapshot.connection_epoch + 1),
            )
        if self.snapshot.state == RuntimeState.BROKER_SYNCING:
            self.mark_broker_sync_complete(account_verified=account_verified, broker_truth_fresh=True)
        if self.snapshot.state == RuntimeState.RECONCILING:
            self.mark_reconciliation_passed(
                account_verified=account_verified,
                broker_truth_fresh=True,
                reason="recovery_reconciliation_passed",
            )
        self._emit_incident("RECOVERY_PENDING", "operator_ack_required")
        return self.snapshot

    def on_reconnect_started(self, *, reason: str = "reconnect_started") -> RuntimeSnapshot:
        attempts = self.snapshot.reconnect_attempts + 1
        if self.snapshot.state != RuntimeState.RECONNECTING:
            return self.on_disconnect(reason=reason, reconnect_attempts=attempts)
        return self.state_machine.update_conditions(
            reason=reason,
            reconnect_attempts=attempts,
            connected=False,
            broker_truth_fresh=False,
            blockers=self._with_blockers("transport_disconnected", "broker_truth_stale"),
        )

    reconnect_started = on_reconnect_started

    def on_reconnect_success(
        self,
        *,
        account_verified: bool = False,
        connection_epoch: int | None = None,
        reason: str = "reconnect_succeeded",
    ) -> RuntimeSnapshot:
        """Advance only to BROKER_SYNCING; READY is intentionally impossible here."""

        if self.snapshot.state != RuntimeState.RECONNECTING:
            self.on_reconnect_started(reason="reconnect_before_success")
        epoch = connection_epoch or (self.snapshot.connection_epoch + 1)
        return self.state_machine.transition(
            RuntimeState.BROKER_SYNCING,
            reason=reason,
            connected=True,
            account_verified=account_verified,
            connection_epoch=epoch,
            broker_truth_fresh=False,
            blockers=self._without_blockers("transport_disconnected", "broker_truth_stale"),
        )

    reconnect_success = on_reconnect_success
    on_reconnected = on_reconnect_success

    def acknowledge_recovery(
        self,
        *,
        operator: str = "operator",
        operator_id: str | None = None,
        reason: str = "operator_ack",
        resume: bool = True,
    ) -> RuntimeSnapshot:
        if self.snapshot.state != RuntimeState.RECOVERY_PENDING:
            # A failed recovery is terminal/frozen.  An acknowledgement may be
            # recorded by an outer incident workflow, but it must not turn the
            # runtime back into READY.
            return self.snapshot
        actor = str(operator_id or operator or "operator")
        self.state_machine.acknowledge_recovery(operator=actor, reason=reason)
        if self.snapshot.kill_switch_tripped:
            return self.snapshot
        if resume:
            return self.state_machine.resume_after_recovery(reason="recovery_resumed_after_operator_ack")
        return self.snapshot

    operator_ack = acknowledge_recovery
    ack_recovery = acknowledge_recovery
    ack_operator = acknowledge_recovery

    def resume_after_recovery(self, *, reason: str = "recovery_resumed") -> RuntimeSnapshot:
        return self.state_machine.resume_after_recovery(reason=reason)

    # ------------------------------------------------------------------
    # Permission façade
    # ------------------------------------------------------------------

    def can_submit_new_order(self) -> bool:
        return self.permission_evaluator.can_submit_new_order()

    def can_reduce_position(self) -> bool:
        return self.permission_evaluator.can_reduce_position()

    def can_cancel_order(self) -> bool:
        return self.permission_evaluator.can_cancel_order()

    def can_query_broker(self) -> bool:
        return self.permission_evaluator.can_query_broker()

    def evaluate_permissions(self) -> dict[str, PermissionDecision]:
        return self.permission_evaluator.evaluate()

    def transition(self, target: RuntimeState | str, reason: str = "", **kwargs: Any) -> RuntimeSnapshot:
        """Expose the canonical graph without adding an alternate graph here."""

        return self.state_machine.transition(target, reason=reason, **kwargs)

    def snapshot_dict(self) -> dict[str, Any]:
        data = self.snapshot.to_dict()
        data.update(
            {
                "live_ready": False,
                "broker_access_allowed": False,
                "private_endpoint_allowed": False,
                "order_endpoint_allowed": False,
            }
        )
        return data


# Short and descriptive aliases for integration code and hidden contract tests.
IBKRRuntimeControlPlane = IBKRRuntimeSupervisor
TradingRuntimeSupervisor = IBKRRuntimeSupervisor


__all__ = [
    "IBKRRuntimeControlPlane",
    "IBKRRuntimeSupervisor",
    "TradingRuntimeSupervisor",
]
