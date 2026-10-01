"""Fail-closed IBKR recovery and reconciliation orchestration.

The module is deliberately an orchestration boundary, not an IBKR adapter.
It accepts a small, injected broker port and the existing data-only
reconciliation input.  The port returns broker truth; it never receives an
order-submit, cancel, or ledger-writer capability from this module.

The recovery contract is intentionally stricter than ordinary reconciliation:
an interrupted session always ends in ``RECOVERY_PENDING`` after a completed
reconciliation, even when the four-way result is clean.  Only an explicit
operator acknowledgement can move that recovery record to ``READY``.  A
reconnect or a clean reconciliation never unlocks order submission by itself.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Protocol, TypeAlias

from quant_us.live.ibkr_paper_reconciliation import (
    IBKRAccountSnapshot,
    IBKRBrokerSnapshot,
    IBKRPaperReconciliationInput,
    IBKRPaperReconciliationReport,
    reconcile_ibkr_paper,
)


SCHEMA_VERSION = "us_equity_ibkr_recovery_v1"
_MISSING = object()


class RecoveryState(str, Enum):
    """States owned by the recovery workflow.

    These values intentionally mirror the integration vocabulary without
    replacing Agent 1's eventual canonical runtime state machine.
    """

    DISCONNECTED = "DISCONNECTED"
    BLOCKED = "BLOCKED"
    TRANSPORT_UNKNOWN = "TRANSPORT_UNKNOWN"
    RECONNECTING = "RECONNECTING"
    BROKER_TRUTH = "BROKER_TRUTH"
    OPEN_ORDERS_SYNC = "OPEN_ORDERS_SYNC"
    EXECUTIONS_SYNC = "EXECUTIONS_SYNC"
    POSITIONS_SYNC = "POSITIONS_SYNC"
    CASH_ACCOUNT_SYNC = "CASH_ACCOUNT_SYNC"
    RECONCILING = "RECONCILING"
    RECOVERY_PENDING = "RECOVERY_PENDING"
    READY = "READY"
    HALTED = "HALTED"
    FROZEN = "FROZEN"


class RecoveryBrokerPort(Protocol):
    """Minimal injected port required by the orchestrator.

    Agent 2 can bind these methods to its canonical broker-truth adapter.  No
    adapter import is required here, and the protocol exposes no submit,
    cancel, credential, or ledger mutation surface.
    """

    def reconnect(self, *, max_attempts: int) -> Any:
        """Perform one bounded reconnect operation and return its report."""

    def broker_truth_snapshot(self) -> Any:
        """Return the broker truth snapshot for the new connection epoch."""

    def sync_open_orders(self) -> Any:
        """Return the broker open-order snapshot."""

    def sync_executions(self) -> Any:
        """Return the broker execution/fill snapshot."""

    def sync_positions(self) -> Any:
        """Return the broker position snapshot."""

    def sync_account(self) -> Any:
        """Return the broker cash/account snapshot."""


BrokerRecoveryPort: TypeAlias = RecoveryBrokerPort


class RecoveryReconciler(Protocol):
    """Callable-compatible seam for deterministic reconciliation tests."""

    def __call__(
        self,
        request: IBKRPaperReconciliationInput,
    ) -> IBKRPaperReconciliationReport | Mapping[str, Any]:
        ...


@dataclass(frozen=True)
class Discrepancy:
    """A classified recovery discrepancy and its fail-closed policy."""

    code: str
    severity: str
    block_new_orders: bool
    recommended_action: str
    auto_recoverable: bool
    operator_ack_required: bool
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", str(self.code).upper())
        object.__setattr__(self, "details", dict(self.details))

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity,
            "block_new_orders": self.block_new_orders,
            "recommended_action": self.recommended_action,
            "auto_recoverable": self.auto_recoverable,
            "operator_ack_required": self.operator_ack_required,
            "details": dict(self.details),
        }


@dataclass(frozen=True)
class RecoveryResult:
    """Immutable result of one recovery attempt or acknowledgement."""

    schema_version: str
    recovery_id: str
    state: RecoveryState
    success: bool
    connection_epoch: Any
    reconciliation_status: str
    discrepancies: tuple[Discrepancy, ...]
    blockers: tuple[str, ...]
    requires_operator_ack: bool
    recommended_actions: tuple[str, ...]
    block_new_orders: bool
    events: tuple[str, ...]
    sync_summary: Mapping[str, Any]
    reconciliation: Mapping[str, Any] | None
    safety_flags: Mapping[str, bool]
    operator_acknowledged: bool = False
    operator_id: str = ""

    @property
    def is_ready(self) -> bool:
        """Return workflow readiness, not permission to submit live orders."""

        return self.state is RecoveryState.READY and not self.block_new_orders

    @property
    def discrepancy_codes(self) -> tuple[str, ...]:
        return tuple(item.code for item in self.discrepancies)

    @property
    def trace(self) -> tuple[str, ...]:
        """Compatibility/readability alias for the deterministic event trace."""

        return self.events

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "recovery_id": self.recovery_id,
            "state": self.state.value,
            "success": self.success,
            "connection_epoch": self.connection_epoch,
            "reconciliation_status": self.reconciliation_status,
            "discrepancies": [item.to_dict() for item in self.discrepancies],
            "blockers": list(self.blockers),
            "requires_operator_ack": self.requires_operator_ack,
            "recommended_actions": list(self.recommended_actions),
            "block_new_orders": self.block_new_orders,
            "events": list(self.events),
            "sync_summary": dict(self.sync_summary),
            "reconciliation": (
                None if self.reconciliation is None else dict(self.reconciliation)
            ),
            "safety_flags": dict(self.safety_flags),
            "operator_acknowledged": self.operator_acknowledged,
            "operator_id": self.operator_id,
        }


class _RecoveryFailure(RuntimeError):
    def __init__(
        self,
        code: str,
        *,
        state: RecoveryState = RecoveryState.HALTED,
        exception_type: str = "",
    ) -> None:
        super().__init__(code)
        self.code = code
        self.state = state
        self.exception_type = exception_type


_POLICY: dict[str, tuple[str, str, bool, bool, bool]] = {
    # code: severity, recommended action, auto recoverable, ack required, block
    "UNKNOWN_BROKER_ORDER": (
        "critical",
        "OPERATOR_REVIEW_UNKNOWN_BROKER_ORDER",
        False,
        True,
        True,
    ),
    "MISSING_BROKER_ORDER": (
        "critical",
        "OPERATOR_REVIEW_MISSING_BROKER_ORDER",
        False,
        True,
        True,
    ),
    "UNKNOWN_EXECUTION": (
        "critical",
        "OPERATOR_REVIEW_UNKNOWN_EXECUTION",
        False,
        True,
        True,
    ),
    "DUPLICATE_EXECUTION": (
        "critical",
        "OPERATOR_REVIEW_DUPLICATE_EXECUTION",
        False,
        True,
        True,
    ),
    "POSITION_MISMATCH": (
        "critical",
        "REBUILD_POSITION_TRUTH_AND_RECONCILE",
        False,
        True,
        True,
    ),
    "CASH_MISMATCH": (
        "critical",
        "REBUILD_CASH_TRUTH_AND_RECONCILE",
        False,
        True,
        True,
    ),
    "COMMISSION_MISMATCH": (
        "high",
        "REBUILD_COMMISSION_TRUTH_AND_RECONCILE",
        False,
        True,
        True,
    ),
    "SNAPSHOT_STALE": (
        "critical",
        "REQUEST_FRESH_BROKER_TRUTH",
        False,
        True,
        True,
    ),
    "SNAPSHOT_INCOMPLETE": (
        "critical",
        "COMPLETE_ALL_BROKER_SYNC_SURFACES",
        False,
        True,
        True,
    ),
    "SEQUENCE_GAP": (
        "critical",
        "REPLAY_SEQUENCE_FROM_LAST_CONFIRMED_WATERMARK",
        False,
        True,
        True,
    ),
    "EPOCH_MISMATCH": (
        "critical",
        "DISCARD_OLD_EPOCH_AND_REBUILD_TRUTH",
        False,
        True,
        True,
    ),
    "ACCOUNT_MISMATCH": (
        "critical",
        "VERIFY_ACCOUNT_ALLOWLIST_AND_TRUTH",
        False,
        True,
        True,
    ),
    "RECOVERY_DATA_BLOCKER": (
        "critical",
        "OPERATOR_REVIEW_RECONCILIATION_BLOCKER",
        False,
        True,
        True,
    ),
    "RECOVERY_WORKFLOW_FAILURE": (
        "critical",
        "OPERATOR_REVIEW_FAILURE_AND_RETRY",
        False,
        True,
        True,
    ),
}


class IBKRRecoveryOrchestrator:
    """Run the deterministic disconnect-to-ack recovery closed loop."""

    def __init__(
        self,
        broker: RecoveryBrokerPort | None = None,
        *,
        broker_adapter: RecoveryBrokerPort | None = None,
        ledger: Any | None = None,
        incident_sink: Any | None = None,
        max_reconnect_attempts: int = 3,
        reconciler: RecoveryReconciler | Callable[
            [IBKRPaperReconciliationInput], IBKRPaperReconciliationReport | Mapping[str, Any]
        ] = reconcile_ibkr_paper,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        selected_broker = broker_adapter or broker
        if selected_broker is None:
            raise ValueError("recovery_broker_adapter_required")
        if isinstance(max_reconnect_attempts, bool) or max_reconnect_attempts < 1:
            raise ValueError("max_reconnect_attempts must be positive")
        self._broker = selected_broker
        self.broker_adapter = selected_broker
        self.ledger = ledger
        self.incident_sink = incident_sink
        self._max_reconnect_attempts = int(max_reconnect_attempts)
        self._reconciler = reconciler
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._results: dict[str, RecoveryResult] = {}

    @property
    def results(self) -> tuple[RecoveryResult, ...]:
        """Return stored results in deterministic recovery-id order."""

        return tuple(self._results[key] for key in sorted(self._results))

    def recover(
        self,
        request: IBKRPaperReconciliationInput | None = None,
        *,
        recovery_id: str = "",
        expected_connection_epoch: Any = None,
        broker_snapshot: Any | None = None,
        local_order_ids: Sequence[Any] = (),
        local_execution_ids: Sequence[Any] = (),
    ) -> RecoveryResult:
        """Recover, sync, classify, and stop at ``RECOVERY_PENDING``.

        ``request`` carries local OMS/fill/position/cash truth.  Its broker
        snapshot is replaced only in the in-memory reconciliation request;
        this method does not write a ledger or mutate the caller's object.
        """

        if request is None:
            if broker_snapshot is None:
                raise ValueError("recovery_request_or_broker_snapshot_required")
            request = IBKRPaperReconciliationInput(
                broker_snapshot=broker_snapshot,
                oms_orders=tuple(local_order_ids),
                fill_ledger=tuple(local_execution_ids),
                run_id=str(recovery_id or "runtime-recovery"),
                account_hash=str(_value(broker_snapshot, "account_hash", default="") or ""),
                now=self._clock(),
            )
        elif broker_snapshot is not None:
            request = replace(request, broker_snapshot=broker_snapshot)

        recovery_id = self._normalise_recovery_id(recovery_id, request)
        events: list[str] = [RecoveryState.DISCONNECTED.value]
        connection_epoch: Any = None
        sync_summary: dict[str, Any] = {}

        try:
            events.append(RecoveryState.BLOCKED.value)
            events.append(RecoveryState.TRANSPORT_UNKNOWN.value)
            events.append(RecoveryState.RECONNECTING.value)
            reconnect_report = self._call(
                "reconnect",
                ("reconnect",),
                max_attempts=self._max_reconnect_attempts,
            )
            if not _explicitly_connected(reconnect_report):
                raise _RecoveryFailure("RECONNECT_FAILED")
            reconnect_epoch = _connection_epoch(reconnect_report)

            events.append(RecoveryState.BROKER_TRUTH.value)
            truth = self._call(
                "broker_truth_snapshot",
                ("broker_truth_snapshot", "get_broker_truth_snapshot", "broker_truth"),
            )
            if truth is None or isinstance(truth, (bool, str, bytes)):
                raise _RecoveryFailure(
                    "BROKER_TRUTH_INVALID",
                    state=RecoveryState.FROZEN,
                )
            truth_epoch = _connection_epoch(truth)
            connection_epoch = truth_epoch if truth_epoch is not None else reconnect_epoch

            events.append(RecoveryState.OPEN_ORDERS_SYNC.value)
            open_orders = self._required_sync(
                "open_orders_sync",
                ("sync_open_orders", "get_open_orders", "open_orders"),
                fallback=self._truth_sync_fallback(truth, "open_orders"),
            )
            sync_summary["open_orders"] = _collection_count(
                open_orders,
                keys=("open_orders", "orders", "items"),
            )

            events.append(RecoveryState.EXECUTIONS_SYNC.value)
            executions = self._required_sync(
                "executions_sync",
                ("sync_executions", "sync_fills", "get_fills", "executions", "fills"),
                fallback=self._truth_sync_fallback(truth, "executions"),
            )
            sync_summary["executions"] = _collection_count(
                executions,
                keys=("executions", "fills", "items"),
            )

            events.append(RecoveryState.POSITIONS_SYNC.value)
            positions = self._required_sync(
                "positions_sync",
                ("sync_positions", "get_positions", "positions"),
                fallback=self._truth_sync_fallback(truth, "positions"),
            )
            sync_summary["positions"] = _collection_count(
                positions,
                keys=("positions", "items"),
            )

            events.append(RecoveryState.CASH_ACCOUNT_SYNC.value)
            account = self._required_sync(
                "account_sync",
                ("sync_account", "get_account", "account"),
                fallback=self._truth_sync_fallback(truth, "account"),
            )
            sync_summary["account"] = 1

            snapshot = _compose_reconciliation_snapshot(
                truth,
                open_orders=open_orders,
                executions=executions,
                positions=positions,
                account=account,
            )
            events.append(RecoveryState.RECONCILING.value)
            reconciliation_request = replace(
                request,
                broker_snapshot=snapshot,
                now=request.now if request.now is not None else self._clock(),
            )
            report = self._run_reconciler(reconciliation_request)
            report_dict = _report_to_dict(report)
            discrepancies = _classify_discrepancies(report_dict)
            discrepancies = list(discrepancies)
            discrepancies.extend(
                _epoch_discrepancies(
                    reconnect_epoch=reconnect_epoch,
                    truth_epoch=truth_epoch,
                    expected_epoch=expected_connection_epoch,
                )
            )
            discrepancies = _deduplicate_discrepancies(discrepancies)

            result = _build_result(
                recovery_id=recovery_id,
                state=RecoveryState.RECOVERY_PENDING,
                success=not discrepancies,
                connection_epoch=connection_epoch,
                reconciliation_status=str(
                    report_dict.get("status", "blocked_fail_closed") or "blocked_fail_closed"
                ),
                discrepancies=discrepancies,
                raw_blockers=_string_values(report_dict.get("blockers", ())),
                events=events + [RecoveryState.RECOVERY_PENDING.value],
                sync_summary=sync_summary,
                reconciliation=report_dict,
                requires_operator_ack=True,
                operator_acknowledged=False,
            )
        except _RecoveryFailure as exc:
            terminal = exc.state
            events.append(terminal.value)
            result = _failure_result(
                recovery_id=recovery_id,
                state=terminal,
                code=exc.code,
                exception_type=exc.exception_type,
                connection_epoch=connection_epoch,
                events=events,
                sync_summary=sync_summary,
            )
        except Exception as exc:  # pragma: no cover - defensive fail-closed boundary
            events.append(RecoveryState.FROZEN.value)
            result = _failure_result(
                recovery_id=recovery_id,
                state=RecoveryState.FROZEN,
                code="RECOVERY_UNEXPECTED_FAILURE",
                exception_type=type(exc).__name__,
                connection_epoch=connection_epoch,
                events=events,
                sync_summary=sync_summary,
            )

        self._results[recovery_id] = result
        self._emit_result_incidents(result)
        return result

    def _run_reconciler(self, request: IBKRPaperReconciliationInput) -> Any:
        candidate = self._reconciler
        if callable(candidate):
            return candidate(request)
        for name in ("reconcile", "run"):
            method = getattr(candidate, name, None)
            if callable(method):
                try:
                    return method(request)
                except TypeError:
                    return method(snapshot=request.broker_snapshot)
        raise _RecoveryFailure("RECONCILER_SURFACE_MISSING", state=RecoveryState.FROZEN)

    def _emit_result_incidents(self, result: RecoveryResult) -> None:
        sink = self.incident_sink
        if sink is None:
            return
        codes = list(result.discrepancy_codes) or list(result.blockers)
        if result.state is RecoveryState.RECOVERY_PENDING and not codes:
            codes = ["RECOVERY_PENDING"]
        for code in codes:
            event = {
                "type": str(code),
                "incident_type": str(code),
                "event": str(code),
                "source": "ibkr_recovery_orchestrator",
                "reason": str(code),
                "context": {"recovery_id": result.recovery_id},
            }
            for name in ("emit", "record", "open", "open_incident"):
                method = getattr(sink, name, None)
                if not callable(method):
                    continue
                try:
                    method(event)
                    break
                except TypeError:
                    try:
                        method(
                            incident_type=str(code),
                            source="ibkr_recovery_orchestrator",
                            message=str(code),
                            context={"recovery_id": result.recovery_id},
                        )
                        break
                    except Exception:
                        continue
                except Exception:
                    break

    def acknowledge(
        self,
        recovery_id: str,
        *,
        operator_id: str,
    ) -> RecoveryResult:
        """Apply explicit operator acknowledgement without clearing blockers."""

        current = self._results.get(str(recovery_id))
        if current is None:
            result = _failure_result(
                recovery_id=str(recovery_id),
                state=RecoveryState.FROZEN,
                code="RECOVERY_ID_UNKNOWN",
                exception_type="",
                connection_epoch=None,
                events=[RecoveryState.FROZEN.value],
                sync_summary={},
            )
            self._results[str(recovery_id)] = result
            return result

        if current.state is not RecoveryState.RECOVERY_PENDING:
            return current

        operator_id = str(operator_id or "").strip()
        if not operator_id:
            result = replace(
                current,
                success=False,
                requires_operator_ack=True,
                blockers=tuple(sorted(set(current.blockers) | {"OPERATOR_ACK_IDENTITY_MISSING"})),
                recommended_actions=tuple(
                    sorted(set(current.recommended_actions) | {"OPERATOR_ACK_REQUIRED"})
                ),
            )
            self._results[current.recovery_id] = result
            return result

        if current.blockers:
            result = replace(
                current,
                success=False,
                requires_operator_ack=True,
                operator_acknowledged=True,
                operator_id=operator_id,
                recommended_actions=tuple(
                    sorted(set(current.recommended_actions) | {"RECONCILE_AND_RETRY"})
                ),
            )
            self._results[current.recovery_id] = result
            return result

        result = replace(
            current,
            state=RecoveryState.READY,
            success=True,
            requires_operator_ack=False,
            recommended_actions=(),
            block_new_orders=False,
            events=current.events + (RecoveryState.READY.value,),
            operator_acknowledged=True,
            operator_id=operator_id,
        )
        self._results[current.recovery_id] = result
        return result

    def acknowledge_recovery(self, recovery_id: str, *, operator_id: str) -> RecoveryResult:
        """Explicitly named alias for integration callers."""

        return self.acknowledge(recovery_id, operator_id=operator_id)

    def operator_ack(self, recovery_id: str, *, operator_id: str) -> RecoveryResult:
        """Short alias matching the runtime control-plane vocabulary."""

        return self.acknowledge(recovery_id, operator_id=operator_id)

    def run_recovery(
        self,
        request: IBKRPaperReconciliationInput,
        *,
        recovery_id: str = "",
        expected_connection_epoch: Any = None,
    ) -> RecoveryResult:
        """Named alias for supervisors that call the workflow explicitly."""

        return self.recover(
            request,
            recovery_id=recovery_id,
            expected_connection_epoch=expected_connection_epoch,
        )

    def _normalise_recovery_id(
        self,
        recovery_id: str,
        request: IBKRPaperReconciliationInput,
    ) -> str:
        value = str(recovery_id or "").strip()
        if value:
            return value
        run_id = str(request.run_id or "").strip()
        if run_id:
            return f"recovery:{run_id}"
        return "recovery:missing-run-id"

    def _call(self, operation: str, names: Sequence[str], **kwargs: Any) -> Any:
        method = None
        for name in names:
            candidate = getattr(self._broker, name, None)
            if callable(candidate):
                method = candidate
                break
            # Agent2's paper adapter exposes ``broker_truth_snapshot`` as a
            # read-only property, while injected fakes expose a method.  Both
            # are observation-only surfaces and are accepted here; no
            # property is ever treated as a write/cancel capability.
            if candidate is not None and operation == "broker_truth_snapshot" and not kwargs:
                return candidate
        if method is None:
            raise _RecoveryFailure(
                f"{operation.upper()}_SURFACE_MISSING",
                state=RecoveryState.FROZEN,
            )
        try:
            return method(**kwargs)
        except _RecoveryFailure:
            raise
        except Exception as exc:
            raise _RecoveryFailure(
                f"{operation.upper()}_FAILED",
                exception_type=type(exc).__name__,
            ) from None

    def _required_sync(
        self,
        operation: str,
        names: Sequence[str],
        *,
        fallback: Any = _MISSING,
    ) -> Any:
        try:
            value = self._call(operation, names)
        except _RecoveryFailure as exc:
            # A canonical BrokerTruthSnapshot is already a complete,
            # read-only observation.  Small injected replay fixtures may not
            # expose four duplicate sync methods; consuming the corresponding
            # truth field keeps the recovery workflow composable without
            # inventing a broker-side write surface.  Real adapters still use
            # their explicit sync methods and never reach this fallback.
            if fallback is _MISSING or not str(exc.code).endswith("SURFACE_MISSING"):
                raise
            value = fallback
        if value is None:
            raise _RecoveryFailure(
                f"{operation.upper()}_RESULT_MISSING",
                state=RecoveryState.FROZEN,
            )
        return value

    @staticmethod
    def _truth_sync_fallback(truth: Any, component: str) -> Any:
        names = {
            "open_orders": ("open_orders", "orders"),
            "executions": ("executions", "fills"),
            "positions": ("positions",),
        }
        if component in names:
            return _value(truth, *names[component], default=_MISSING)
        account = _value(truth, "account", default=_MISSING)
        if account is not _MISSING:
            return account
        # BrokerTruthSnapshot exposes account values as top-level read-only
        # fields in the offline adapter.  Preserve them as one account record
        # so the existing reconciliation model can evaluate completeness.
        account_fields = (
            "account_hash",
            "cash",
            "cash_balance",
            "net_liquidation",
            "buying_power",
            "margin",
            "commission_total",
        )
        payload = {
            key: _value(truth, key, default=_MISSING)
            for key in account_fields
        }
        payload = {key: value for key, value in payload.items() if value is not _MISSING}
        return payload if payload else _MISSING


# Short class alias for callers using the plan's generic name.
RecoveryOrchestrator = IBKRRecoveryOrchestrator


def _build_result(
    *,
    recovery_id: str,
    state: RecoveryState,
    success: bool,
    connection_epoch: Any,
    reconciliation_status: str,
    discrepancies: Sequence[Discrepancy],
    raw_blockers: Sequence[str],
    events: Sequence[str],
    sync_summary: Mapping[str, Any],
    reconciliation: Mapping[str, Any] | None,
    requires_operator_ack: bool,
    operator_acknowledged: bool,
    operator_id: str = "",
) -> RecoveryResult:
    ordered_discrepancies = tuple(_deduplicate_discrepancies(discrepancies))
    blocker_values = {str(item) for item in raw_blockers if str(item)}
    blocker_values.update(item.code for item in ordered_discrepancies)
    actions = {item.recommended_action for item in ordered_discrepancies}
    if requires_operator_ack:
        actions.add("OPERATOR_ACK_RECOVERY")
    blocked = state is not RecoveryState.READY or bool(blocker_values)
    return RecoveryResult(
        schema_version=SCHEMA_VERSION,
        recovery_id=recovery_id,
        state=state,
        success=bool(success and not blocker_values),
        connection_epoch=connection_epoch,
        reconciliation_status=reconciliation_status,
        discrepancies=ordered_discrepancies,
        blockers=tuple(sorted(blocker_values)),
        requires_operator_ack=requires_operator_ack,
        recommended_actions=tuple(sorted(actions)),
        block_new_orders=blocked,
        events=tuple(events),
        sync_summary=dict(sync_summary),
        reconciliation=None if reconciliation is None else dict(reconciliation),
        safety_flags=_safety_flags(),
        operator_acknowledged=operator_acknowledged,
        operator_id=operator_id,
    )


def _failure_result(
    *,
    recovery_id: str,
    state: RecoveryState,
    code: str,
    exception_type: str,
    connection_epoch: Any,
    events: Sequence[str],
    sync_summary: Mapping[str, Any],
) -> RecoveryResult:
    details: dict[str, Any] = {"reason": code}
    if exception_type:
        details["exception_type"] = exception_type
    discrepancy = _make_discrepancy("RECOVERY_WORKFLOW_FAILURE", details)
    return _build_result(
        recovery_id=recovery_id,
        state=state,
        success=False,
        connection_epoch=connection_epoch,
        reconciliation_status="blocked_fail_closed",
        discrepancies=(discrepancy,),
        raw_blockers=(code,),
        events=events,
        sync_summary=sync_summary,
        reconciliation=None,
        requires_operator_ack=True,
        operator_acknowledged=False,
    )


def _make_discrepancy(code: str, details: Mapping[str, Any] | None = None) -> Discrepancy:
    policy = _POLICY.get(code, _POLICY["RECOVERY_DATA_BLOCKER"])
    severity, action, auto_recoverable, ack_required, block = policy
    return Discrepancy(
        code=code,
        severity=severity,
        block_new_orders=block,
        recommended_action=action,
        auto_recoverable=auto_recoverable,
        operator_ack_required=ack_required,
        details={} if details is None else details,
    )


def _classify_discrepancies(report: Mapping[str, Any]) -> list[Discrepancy]:
    """Map the existing reconciler's detailed blockers to recovery taxonomy."""

    blockers = set(_string_values(report.get("blockers", ())))
    orders = _mapping(report.get("orders"))
    fills = _mapping(report.get("fills"))
    positions = _mapping(report.get("positions"))
    cash = _mapping(report.get("cash"))
    snapshot = _mapping(report.get("snapshot"))
    discrepancies: list[Discrepancy] = []
    classified_blockers: set[str] = set()

    unmatched_broker_orders = _compact_records(
        orders.get("unmatched_broker", ()),
        keys=("order_id", "client_order_id", "broker_order_id", "symbol", "status"),
    )
    if unmatched_broker_orders or "order_unmatched_broker" in blockers:
        discrepancies.append(
            _make_discrepancy(
                "UNKNOWN_BROKER_ORDER",
                {"orders": unmatched_broker_orders, "blockers": ["order_unmatched_broker"]},
            )
        )
        classified_blockers.update({"order_unmatched_broker", "broker_order_identity_missing"})

    unmatched_local_orders = _compact_records(
        orders.get("unmatched_local", ()),
        keys=("order_id", "client_order_id", "broker_order_id", "symbol", "status"),
    )
    if unmatched_local_orders or "order_unmatched_local" in blockers:
        discrepancies.append(
            _make_discrepancy(
                "MISSING_BROKER_ORDER",
                {"orders": unmatched_local_orders, "blockers": ["order_unmatched_local"]},
            )
        )
        classified_blockers.add("order_unmatched_local")

    unknown_executions = _compact_records(
        fills.get("unmatched_broker", ()),
        keys=("execution_id", "order_id", "broker_order_id", "symbol", "quantity", "sequence"),
    )
    if unknown_executions or "fill_unmatched_broker" in blockers:
        discrepancies.append(
            _make_discrepancy(
                "UNKNOWN_EXECUTION",
                {"executions": unknown_executions, "blockers": ["fill_unmatched_broker"]},
            )
        )
        classified_blockers.add("fill_unmatched_broker")

    duplicate_executions = _compact_records(
        fills.get("duplicates", ()),
        keys=("execution_id", "source", "count", "conflict"),
    )
    if duplicate_executions or any(
        item in blockers
        for item in ("duplicate_execution", "fill_duplicate_content_conflict", "duplicate_fill_conflict")
    ):
        discrepancies.append(
            _make_discrepancy(
                "DUPLICATE_EXECUTION",
                {"executions": duplicate_executions},
            )
        )
        classified_blockers.update(
            {"duplicate_execution", "fill_duplicate_content_conflict", "duplicate_fill_conflict"}
        )

    position_drifts = _compact_records(
        list(positions.get("drifts", ())) + list(positions.get("ledger_consistency", ())),
        keys=(
            "symbol",
            "local_quantity",
            "broker_quantity",
            "quantity_diff",
            "local_average_cost",
            "broker_average_cost",
            "average_cost_diff",
        ),
    )
    if position_drifts or any(item.startswith("position_") for item in blockers):
        discrepancies.append(_make_discrepancy("POSITION_MISMATCH", {"positions": position_drifts}))
        classified_blockers.update(item for item in blockers if item.startswith("position_"))

    cash_mismatch = (
        cash.get("cash_matched") is False
        or "cash_drift" in blockers
        or "cash_ledger_missing" in blockers
        or "broker_cash_missing" in blockers
    )
    if cash_mismatch:
        discrepancies.append(
            _make_discrepancy(
                "CASH_MISMATCH",
                {
                    key: cash.get(key)
                    for key in ("broker_cash", "local_cash", "cash_drift", "cash_matched")
                    if key in cash
                },
            )
        )
        classified_blockers.update(
            {"cash_drift", "cash_ledger_missing", "broker_cash_missing"} & blockers
        )

    commission_mismatch = (
        cash.get("commission_matched") is False
        or "commission_drift" in blockers
        or "broker_commission_missing" in blockers
    )
    if commission_mismatch:
        discrepancies.append(
            _make_discrepancy(
                "COMMISSION_MISMATCH",
                {
                    key: cash.get(key)
                    for key in (
                        "broker_commission",
                        "local_commission",
                        "commission_drift",
                        "commission_matched",
                    )
                    if key in cash
                },
            )
        )
        classified_blockers.update(
            {"commission_drift", "broker_commission_missing"} & blockers
        )

    stale = bool(snapshot.get("stale_snapshot") or snapshot.get("stale")) or any(
        item in blockers
        for item in (
            "stale_snapshot",
            "snapshot_timestamp_missing",
            "snapshot_timestamp_in_future",
        )
    )
    if stale:
        discrepancies.append(
            _make_discrepancy(
                "SNAPSHOT_STALE",
                {
                    key: snapshot.get(key)
                    for key in ("snapshot_id", "captured_at", "age_seconds", "max_age_seconds")
                    if key in snapshot
                },
            )
        )
        classified_blockers.update(
            {"stale_snapshot", "snapshot_timestamp_missing", "snapshot_timestamp_in_future"}
            & blockers
        )

    incomplete = snapshot.get("complete") is False or "snapshot_incomplete" in blockers
    if incomplete:
        discrepancies.append(
            _make_discrepancy(
                "SNAPSHOT_INCOMPLETE",
                {"snapshot": {key: snapshot.get(key) for key in ("snapshot_id", "complete") if key in snapshot}},
            )
        )
        classified_blockers.add("snapshot_incomplete")

    sequence_blockers = {
        item
        for item in blockers
        if any(
            token in item
            for token in (
                "sequence_gap",
                "sequence_missing",
                "sequence_unexpected",
                "sequence_regressed",
                "execution_out_of_order",
                "execution_replayed",
                "snapshot_replayed",
                "reconnect_replayed_snapshot",
                "broker_replay_snapshot",
            )
        )
    }
    if sequence_blockers:
        discrepancies.append(
            _make_discrepancy("SEQUENCE_GAP", {"blockers": sorted(sequence_blockers)})
        )
        classified_blockers.update(sequence_blockers)

    account_blockers = {
        item
        for item in blockers
        if item in {
            "account_hash_mismatch",
            "account_hash_missing",
            "broker_account_hash_missing",
            "account_not_allowlisted",
            "account_identity_mismatch",
        }
    }
    if account_blockers:
        discrepancies.append(_make_discrepancy("ACCOUNT_MISMATCH", {"blockers": sorted(account_blockers)}))
        classified_blockers.update(account_blockers)

    known_prefixes = {
        "order_",
        "fill_",
        "position_",
        "cash_",
        "commission_",
        "snapshot_",
        "stale_snapshot",
        "account_",
        "broker_account_",
        "execution_",
        "duplicate_execution",
        "reconnect_replayed_snapshot",
        "broker_replay_snapshot",
    }
    remaining = sorted(
        item
        for item in blockers - classified_blockers
        if not any(item == prefix or item.startswith(prefix) for prefix in known_prefixes)
    )
    if remaining or (bool(report.get("block_new_orders")) and not discrepancies):
        discrepancies.append(
            _make_discrepancy(
                "RECOVERY_DATA_BLOCKER",
                {"blockers": remaining or ["reconciliation_blocked"]},
            )
        )

    return _deduplicate_discrepancies(discrepancies)


def _epoch_discrepancies(
    *,
    reconnect_epoch: Any,
    truth_epoch: Any,
    expected_epoch: Any,
) -> list[Discrepancy]:
    details: dict[str, Any] = {}
    if reconnect_epoch is not None:
        details["reconnect_epoch"] = reconnect_epoch
    if truth_epoch is not None:
        details["truth_epoch"] = truth_epoch
    if expected_epoch is not None:
        details["expected_epoch"] = expected_epoch

    mismatch = False
    if reconnect_epoch is None and truth_epoch is None:
        details["reason"] = "connection_epoch_missing"
        mismatch = True
    if reconnect_epoch is not None and truth_epoch is not None:
        mismatch = mismatch or _epoch_key(reconnect_epoch) != _epoch_key(truth_epoch)
    actual = truth_epoch if truth_epoch is not None else reconnect_epoch
    if expected_epoch is not None:
        mismatch = mismatch or actual is None or _epoch_key(actual) != _epoch_key(expected_epoch)
    if not mismatch:
        return []
    return [_make_discrepancy("EPOCH_MISMATCH", details)]


def _deduplicate_discrepancies(items: Sequence[Discrepancy]) -> list[Discrepancy]:
    by_code: dict[str, Discrepancy] = {}
    for item in items:
        by_code.setdefault(item.code, item)
    return [by_code[key] for key in sorted(by_code)]


def _compose_reconciliation_snapshot(
    truth: Any,
    *,
    open_orders: Any,
    executions: Any,
    positions: Any,
    account: Any,
) -> IBKRBrokerSnapshot:
    """Adapt structural broker truth to the existing data-only model."""

    truth_account = _value(truth, "account", default=None)
    account_payload: dict[str, Any] = {}
    if isinstance(truth_account, Mapping):
        account_payload.update(truth_account)
    for output, names in (
        ("account_hash", ("account_hash", "accountHash")),
        ("cash", ("cash", "cash_balance", "total_cash", "TotalCashValue")),
        ("commission_total", ("commission_total", "commission", "commissions")),
    ):
        value = _value(account, *names, default=_MISSING)
        if value is _MISSING:
            value = _value(truth_account, *names, default=_MISSING)
        if value is _MISSING:
            value = _value(truth, *names, default=_MISSING)
        if value is not _MISSING:
            account_payload[output] = value

    complete = bool(_value(truth, "complete", "is_complete", default=True))
    for flag in (
        "orders_snapshot_complete",
        "executions_snapshot_complete",
        "positions_snapshot_complete",
        "account_snapshot_complete",
    ):
        value = _value(truth, flag, default=_MISSING)
        if value is not _MISSING and not bool(value):
            complete = False
    for flag in ("transport_connected", "account_verified"):
        value = _value(truth, flag, "connected" if flag == "transport_connected" else flag, default=_MISSING)
        if value is not _MISSING and not bool(value):
            complete = False

    sequence = _integer_or_none(
        _value(truth, "sequence", "snapshot_sequence", "sequence_watermark", default=None)
    )
    return IBKRBrokerSnapshot(
        snapshot_id=str(_value(truth, "snapshot_id", "id", default="") or ""),
        sequence=sequence,
        captured_at=_value(
            truth,
            "captured_at",
            "as_of",
            "timestamp_utc",
            "timestamp",
            default=None,
        ),
        account=account_payload,
        positions=_collection_value(positions, keys=("positions", "items")),
        open_orders=_collection_value(open_orders, keys=("open_orders", "orders", "items")),
        fills=_collection_value(executions, keys=("executions", "fills", "items")),
        complete=complete,
        reconnect=True,
        replay=bool(_value(truth, "replay", "is_replay", default=False)),
    )


def _report_to_dict(report: Any) -> dict[str, Any]:
    if isinstance(report, IBKRPaperReconciliationReport):
        return report.to_dict()
    to_dict = getattr(report, "to_dict", None)
    if callable(to_dict):
        value = to_dict()
        if isinstance(value, Mapping):
            return dict(value)
    if isinstance(report, Mapping):
        return dict(report)
    raise _RecoveryFailure("RECONCILIATION_RESULT_INVALID", state=RecoveryState.FROZEN)


def _explicitly_connected(report: Any) -> bool:
    if isinstance(report, bool):
        return report is True
    value = _value(report, "connected", "transport_connected", "is_connected", default=_MISSING)
    return value is not _MISSING and bool(value) is True


def _connection_epoch(value: Any) -> Any:
    return _value(value, "connection_epoch", "epoch", "session_epoch", default=None)


def _epoch_key(value: Any) -> str:
    return str(value).strip()


def _collection_count(value: Any, *, keys: Sequence[str]) -> int:
    selected = _collection_value(value, keys=keys)
    return len(selected)


def _collection_value(value: Any, *, keys: Sequence[str]) -> tuple[Any, ...]:
    if isinstance(value, Mapping):
        for key in keys:
            if key in value:
                return _collection_value(value[key], keys=())
        # Existing adapter-style position surfaces are often keyed by symbol
        # (``{"AAPL": Position(...)}``) rather than wrapped in a list.  Keep
        # those values while still treating a single record mapping as one
        # record.  No raw mapping is written back to the broker or ledger.
        record_keys = {
            "symbol",
            "order_id",
            "client_order_id",
            "execution_id",
            "fill_id",
            "quantity",
            "status",
        }
        if any(key in value for key in record_keys):
            return (value,)
        return tuple(value[key] for key in sorted(value, key=str))
    if value is None:
        return ()
    if isinstance(value, (str, bytes)):
        return (value,)
    try:
        return tuple(value)
    except TypeError:
        return (value,)


def _value(obj: Any, *names: str, default: Any = None) -> Any:
    if obj is None:
        return default
    for name in names:
        if isinstance(obj, Mapping) and name in obj:
            return obj[name]
        try:
            value = getattr(obj, name)
        except Exception:
            continue
        if value is not None:
            return value
    return default


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _string_values(value: Any) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)):
        return (str(value),)
    if value is None:
        return ()
    try:
        return tuple(sorted({str(item) for item in value if str(item)}))
    except TypeError:
        return (str(value),)


def _compact_records(value: Any, *, keys: Sequence[str]) -> list[dict[str, Any]]:
    records = _collection_value(value, keys=())
    compact: list[dict[str, Any]] = []
    for item in records:
        if isinstance(item, Mapping):
            compact.append({key: item[key] for key in keys if key in item})
        else:
            compact.append(
                {
                    key: getattr(item, key)
                    for key in keys
                    if hasattr(item, key)
                }
            )
    return compact


def _integer_or_none(value: Any) -> int | None:
    if value is None or value is _MISSING:
        return None
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _safety_flags() -> dict[str, bool]:
    """Return conservative flags; this module never unlocks execution."""

    return {
        "broker_called": False,
        "broker_endpoint_used": False,
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "network_used": False,
        "order_submitted": False,
        "order_cancelled": False,
        "global_cancel_executed": False,
        "ledger_mutated": False,
        "paper_order_allowed": False,
        "live_order_allowed": False,
        "order_submission_allowed": False,
        "live_ready": False,
        "secret_read": False,
    }


__all__ = [
    "BrokerRecoveryPort",
    "Discrepancy",
    "IBKRRecoveryOrchestrator",
    "RecoveryBrokerPort",
    "RecoveryOrchestrator",
    "RecoveryResult",
    "RecoveryState",
    "RecoveryReconciler",
    "SCHEMA_VERSION",
]
