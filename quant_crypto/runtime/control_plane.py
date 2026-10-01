"""BTC projection and fail-closed execution boundary.

This module is intentionally transport-free.  It consumes already captured
BTC/OKX observations and projects them into the canonical
``quant_shared.runtime`` contract.  A caller may inject a fake transport for a
unit test, but the default identity is ``NO_TRANSPORT`` and no method creates a
socket, HTTP client, or broker connection.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, Sequence

from quant_shared.core.time import ensure_utc, isoformat_utc, utc_now
from quant_shared.runtime.models import (
    ReconciliationStatus,
    RuntimeSnapshot,
    RuntimeState,
    TradingMode,
)
from quant_shared.runtime.permissions import (
    PermissionDecision,
    PermissionEvaluator,
    RuntimeAction,
    RuntimeAuthoritativeRiskResult,
    RuntimePermissionContext,
    RuntimeRiskEvidence,
    RuntimeRiskEvidenceAuthority,
)
from quant_crypto.trading_contracts import OrderIntent, RiskDecision


BTC_RUNTIME_PROJECTION_VERSION = "btc_shared_runtime_projection_v1"
BTC_ORDER_LIFECYCLE_VERSION = "btc_client_order_lifecycle_v1"


class BTCExecutionBlocked(RuntimeError):
    """Raised when a boundary operation cannot prove it is safe."""


class BTCExecutionMode(str, Enum):
    READ_ONLY = "read_only"
    PAPER = "paper"
    DEMO = "demo"
    LIVE = "live"


class BTCOrderLifecycleStatus(str, Enum):
    PREPARED = "prepared"
    SENT = "sent"
    AMBIGUOUS = "ambiguous"
    ACCEPTED = "accepted"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCEL_REQUESTED = "cancel_requested"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    RESOLVED = "resolved"


def _read(value: object | Mapping[str, Any] | None, *names: str, default: Any = None) -> Any:
    if value is None:
        return default
    if isinstance(value, Mapping):
        for name in names:
            if name in value:
                return value[name]
        return default
    for name in names:
        try:
            return getattr(value, name)
        except AttributeError:
            continue
    return default


def _as_bool(value: Any, *, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "ok", "pass", "passed", "fresh"}
    return bool(value)


def _value_text(value: Any, *, default: str = "") -> str:
    candidate = getattr(value, "value", value)
    if candidate is None:
        return default
    return str(candidate).strip().lower()


def _dedupe(values: Sequence[object]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(str(value) for value in values if str(value)))


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _mode(value: object, default: BTCExecutionMode = BTCExecutionMode.READ_ONLY) -> BTCExecutionMode:
    try:
        return value if isinstance(value, BTCExecutionMode) else BTCExecutionMode(str(value).strip().lower())
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class BTCExecutionIdentity:
    """Non-secret mode/account/key namespace identity.

    ``account_identity`` is an opaque account hash/reference.  Raw API keys,
    passphrases, tokens, and account numbers are never accepted or serialized
    by this contract.
    """

    mode: BTCExecutionMode | str = BTCExecutionMode.LIVE
    state_directory: str = ""
    account_identity: str = ""
    key_namespace: str = ""
    client_order_namespace: str = ""
    account_verified: bool = False
    transport_enabled: bool = False
    live_execution_allowed: bool = False
    auto_start: bool = False
    auto_scale: bool = False
    session_id: str = ""
    epoch: int | None = None
    source_head: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "mode", _mode(self.mode))
        object.__setattr__(self, "state_directory", str(self.state_directory or ""))
        object.__setattr__(self, "account_identity", str(self.account_identity or ""))
        object.__setattr__(self, "key_namespace", str(self.key_namespace or ""))
        object.__setattr__(self, "client_order_namespace", str(self.client_order_namespace or ""))
        object.__setattr__(self, "session_id", str(self.session_id or ""))
        object.__setattr__(self, "source_head", str(self.source_head or ""))
        if self.epoch is not None:
            object.__setattr__(self, "epoch", int(self.epoch))

    @property
    def account_hash(self) -> str:
        return self.account_identity

    @property
    def clord_namespace(self) -> str:
        return self.client_order_namespace

    def blockers(self, *, expected_mode: BTCExecutionMode | str | None = None) -> tuple[str, ...]:
        mode = _mode(self.mode)
        reasons: list[str] = []
        if expected_mode is not None and mode != _mode(expected_mode):
            reasons.append("execution_mode_mismatch")
        for name, value in {
            "state_directory": self.state_directory,
            "account_identity": self.account_identity,
            "key_namespace": self.key_namespace,
            "client_order_namespace": self.client_order_namespace,
        }.items():
            if not value.strip():
                reasons.append(f"execution_{name}_missing")
        lowered_state = self.state_directory.lower()
        lowered_key = self.key_namespace.lower()
        lowered_client = self.client_order_namespace.lower()
        if mode in {BTCExecutionMode.DEMO, BTCExecutionMode.LIVE}:
            opposite = "live" if mode == BTCExecutionMode.DEMO else "demo"
            if opposite in lowered_state:
                reasons.append("execution_state_directory_mode_crossed")
            if opposite in lowered_key:
                reasons.append("execution_key_namespace_mode_crossed")
            if opposite in lowered_client:
                reasons.append("execution_client_order_namespace_mode_crossed")
            expected_prefix = f"quant-system.okx-{mode.value}."
            if self.key_namespace and not lowered_key.startswith(expected_prefix):
                reasons.append("execution_key_namespace_mode_mismatch")
        if not self.transport_enabled:
            reasons.append("execution_transport_disabled")
        if self.auto_start:
            reasons.append("auto_start_forbidden")
        if self.auto_scale:
            reasons.append("auto_scale_forbidden")
        if mode == BTCExecutionMode.LIVE and not self.live_execution_allowed:
            reasons.append("live_execution_not_authorized")
        return _dedupe(reasons)

    def isolation_blockers(self, other: "BTCExecutionIdentity") -> tuple[str, ...]:
        reasons: list[str] = []
        if self.mode != other.mode:
            reasons.append("execution_mode_crossed")
        if self.state_directory and other.state_directory and Path(self.state_directory).resolve() == Path(other.state_directory).resolve():
            reasons.append("execution_state_directory_reused_across_modes")
        if self.account_identity and other.account_identity and self.account_identity == other.account_identity and self.mode != other.mode:
            reasons.append("execution_account_identity_reused_across_modes")
        if self.key_namespace and self.key_namespace == other.key_namespace:
            reasons.append("execution_key_namespace_reused")
        if self.client_order_namespace and self.client_order_namespace == other.client_order_namespace:
            reasons.append("execution_client_order_namespace_reused")
        return _dedupe(reasons)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode.value,
            "state_directory": self.state_directory,
            "account_identity": self.account_identity,
            "key_namespace": self.key_namespace,
            "client_order_namespace": self.client_order_namespace,
            "account_verified": bool(self.account_verified),
            "transport_enabled": bool(self.transport_enabled),
            "live_execution_allowed": bool(self.live_execution_allowed),
            "auto_start": bool(self.auto_start),
            "auto_scale": bool(self.auto_scale),
            "session_id": self.session_id,
            "epoch": self.epoch,
            "source_head": self.source_head,
            "secret_values_recorded": False,
        }


@dataclass(frozen=True)
class BTCBrokerTruth:
    fresh: bool = False
    valid: bool = False
    account_verified: bool = False
    observed_at_utc: datetime | None = None
    source: str = "fixture"
    authoritative_account_verified: bool = False
    account_verification_source: str = ""
    account_identity: str = ""
    venue: str = "okx"
    kill_switch_tripped: bool = False
    source_head: str = ""
    session_id: str = ""
    epoch: int | None = None

    def __post_init__(self) -> None:
        if self.observed_at_utc is not None:
            object.__setattr__(self, "observed_at_utc", ensure_utc(self.observed_at_utc))

    def to_dict(self) -> dict[str, Any]:
        return {
            "fresh": bool(self.fresh),
            "valid": bool(self.valid),
            "account_verified": bool(self.account_verified),
            "authoritative_account_verified": bool(self.authoritative_account_verified),
            "account_verification_source": self.account_verification_source,
            "account_identity": self.account_identity,
            "venue": self.venue,
            "kill_switch_tripped": bool(self.kill_switch_tripped),
            "source_head": self.source_head,
            "session_id": self.session_id,
            "epoch": self.epoch,
            "observed_at_utc": None if self.observed_at_utc is None else isoformat_utc(self.observed_at_utc),
            "source": self.source,
            "network_accessed": False,
        }


@dataclass(frozen=True)
class BTCLedgerFreshness:
    fresh: bool = False
    reconciled: bool = False
    observed_at_utc: datetime | None = None
    source: str = "fixture"

    def __post_init__(self) -> None:
        if self.observed_at_utc is not None:
            object.__setattr__(self, "observed_at_utc", ensure_utc(self.observed_at_utc))

    def to_dict(self) -> dict[str, Any]:
        return {
            "fresh": bool(self.fresh),
            "reconciled": bool(self.reconciled),
            "observed_at_utc": None if self.observed_at_utc is None else isoformat_utc(self.observed_at_utc),
            "source": self.source,
        }


@dataclass(frozen=True)
class BTCEndpointCapability:
    mode: BTCExecutionMode | str = BTCExecutionMode.READ_ONLY
    transport_enabled: bool = False
    submit_new_order: bool = False
    cancel_order: bool = False
    replace_order: bool = False
    reduce_only: bool = False
    attach_protection: bool = False
    dead_man: bool = False
    private_endpoint_allowed: bool = False
    order_endpoint_allowed: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "mode", _mode(self.mode))

    def allows(self, action: RuntimeAction | str) -> bool:
        name = action.value if isinstance(action, RuntimeAction) else str(action)
        field_name = {
            "submit_new_order": "submit_new_order",
            "cancel_order": "cancel_order",
            "replace_order": "replace_order",
            "reduce_only": "reduce_only",
            "reduce_position": "reduce_only",
            "attach_protection": "attach_protection",
            "dead_man": "dead_man",
        }.get(name, name)
        return bool(getattr(self, field_name, False))

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode.value,
            "transport_enabled": bool(self.transport_enabled),
            "submit_new_order": bool(self.submit_new_order),
            "cancel_order": bool(self.cancel_order),
            "replace_order": bool(self.replace_order),
            "reduce_only": bool(self.reduce_only),
            "attach_protection": bool(self.attach_protection),
            "dead_man": bool(self.dead_man),
            "private_endpoint_allowed": bool(self.private_endpoint_allowed),
            "order_endpoint_allowed": bool(self.order_endpoint_allowed),
            "network_accessed": False,
        }


@dataclass(frozen=True)
class BTCProjectionResult:
    snapshot: RuntimeSnapshot
    blockers: tuple[str, ...]
    broker_truth: BTCBrokerTruth
    ledger_freshness: BTCLedgerFreshness
    endpoint_capability: BTCEndpointCapability
    identity: BTCExecutionIdentity

    def to_dict(self) -> dict[str, Any]:
        return {
            "projection_version": BTC_RUNTIME_PROJECTION_VERSION,
            "snapshot": self.snapshot.to_dict(),
            "blockers": list(self.blockers),
            "broker_truth": self.broker_truth.to_dict(),
            "ledger_freshness": self.ledger_freshness.to_dict(),
            "endpoint_capability": self.endpoint_capability.to_dict(),
            "identity": self.identity.to_dict(),
            "safety": {
                "network_accessed": False,
                "private_endpoint_accessed": False,
                "order_endpoint_accessed": False,
                "live_ready": False,
                "live_allowed": False,
                "auto_start": False,
                "auto_scale": False,
            },
        }


def build_btc_runtime_projection(
    exchange_runtime: object | Mapping[str, Any] | None,
    *,
    identity: BTCExecutionIdentity | Mapping[str, Any] | None = None,
    broker_truth: BTCBrokerTruth | Mapping[str, Any] | None = None,
    ledger_freshness: BTCLedgerFreshness | Mapping[str, Any] | None = None,
    endpoint_capability: BTCEndpointCapability | Mapping[str, Any] | None = None,
    account_verified: bool | None = None,
    kill_switch_tripped: bool | None = None,
    recovery_requires_ack: bool = False,
    operator_acknowledged: bool = False,
    now: datetime | None = None,
) -> BTCProjectionResult:
    """Project BTC/OKX observations into one canonical runtime snapshot.

    The exchange object is observation-only.  If it exposes ``validate`` the
    method is used only to collect deterministic blockers; it is never a
    transport hook.  Live mode is always ``NO_TRANSPORT`` unless the caller
    explicitly supplies all live authorization flags, and automatic start or
    scaling is never inferred from an observation.
    """

    identity_obj = _identity_from(identity)
    broker_obj = _broker_from(broker_truth, exchange_runtime, now=now)
    ledger_obj = _ledger_from(ledger_freshness)
    capability_obj = _capability_from(endpoint_capability, identity_obj)
    observed_at = _timestamp(_read(exchange_runtime, "observed_at_utc", "observed_at", default=None)) or ensure_utc(now or utc_now())

    blockers: list[str] = list(identity_obj.blockers(expected_mode=identity_obj.mode))
    blockers.extend(_exchange_blockers(exchange_runtime))
    if not broker_obj.fresh:
        blockers.append("btc_broker_truth_not_fresh")
    if not broker_obj.valid:
        blockers.append("btc_broker_truth_invalid")
    if not ledger_obj.fresh:
        blockers.append("btc_ledger_not_fresh")
    if not ledger_obj.reconciled:
        blockers.append("btc_ledger_not_reconciled")
    if capability_obj.mode != identity_obj.mode:
        blockers.append("btc_endpoint_capability_mode_mismatch")

    # ``account_verified`` is retained only for source compatibility.  A
    # caller assertion can never override the independently observed broker
    # verification and the execution identity.
    if account_verified is not None:
        blockers.append("btc_caller_account_verification_untrusted")
    if kill_switch_tripped is not None:
        blockers.append("btc_caller_kill_switch_untrusted")
    account_ok = bool(
        broker_obj.valid
        and broker_obj.fresh
        and broker_obj.account_verified
        and broker_obj.authoritative_account_verified
        and bool(str(broker_obj.account_verification_source).strip())
        and identity_obj.account_verified
    )
    if not broker_obj.account_verified or not broker_obj.authoritative_account_verified:
        blockers.append("btc_authoritative_account_verification_missing")
    if not str(broker_obj.account_verification_source).strip():
        blockers.append("btc_account_verification_source_missing")
    if broker_obj.account_identity and broker_obj.account_identity != identity_obj.account_identity:
        blockers.append("btc_authoritative_account_identity_mismatch")
    if not account_ok:
        blockers.append("btc_account_identity_not_verified")

    if not capability_obj.transport_enabled:
        blockers.append("btc_endpoint_transport_disabled")
    if not capability_obj.private_endpoint_allowed:
        blockers.append("btc_private_endpoint_capability_missing")
    if not capability_obj.order_endpoint_allowed:
        blockers.append("btc_order_endpoint_capability_missing")
    if broker_obj.kill_switch_tripped:
        blockers.append("btc_kill_switch_tripped")

    runtime_mode = _value_text(_read(exchange_runtime, "mode", default=identity_obj.mode.value), default=identity_obj.mode.value)
    if runtime_mode and runtime_mode != identity_obj.mode.value:
        # A mode supplied by an observation cannot silently override the
        # identity selected for this process.
        blockers.append("btc_runtime_identity_mode_mismatch")

    exchange_status = _value_text(_read(exchange_runtime, "exchange_status", "status", default="unknown"), default="unknown")
    private_status = _value_text(_read(exchange_runtime, "private_ws_status", default="unknown"), default="unknown")
    public_status = _value_text(_read(exchange_runtime, "public_ws_status", default="unknown"), default="unknown")
    rest_status = _value_text(_read(exchange_runtime, "rest_status", default="unknown"), default="unknown")
    connected = public_status == "connected" and private_status == "connected" and rest_status == "ok"

    mode = TradingMode.FROZEN
    state = RuntimeState.DEGRADED if connected else RuntimeState.RECONNECTING
    block_new = True
    if identity_obj.mode == BTCExecutionMode.LIVE and not identity_obj.transport_enabled:
        state = RuntimeState.OFFLINE
        mode = TradingMode.NO_TRANSPORT
        connected = False
        blockers.extend(("btc_live_default_no_transport", "btc_live_auto_start_disabled", "btc_live_auto_scale_disabled"))
    elif not identity_obj.transport_enabled:
        state = RuntimeState.OFFLINE
        mode = TradingMode.NO_TRANSPORT
        connected = False
    elif exchange_status == "cancel_only" or _as_bool(_read(exchange_runtime, "cancel_only", default=False)):
        state = RuntimeState.DEGRADED
        mode = TradingMode.CANCEL_ONLY
        blockers.append("btc_exchange_cancel_only")
    elif exchange_status in {"outage", "maintenance", "unknown"}:
        state = RuntimeState.HALTED if exchange_status == "unknown" else RuntimeState.DEGRADED
        mode = TradingMode.FROZEN
    elif connected and not blockers:
        state = RuntimeState.RECOVERY_PENDING if recovery_requires_ack and not operator_acknowledged else RuntimeState.READY
        mode = TradingMode.CANCEL_ONLY if recovery_requires_ack and not operator_acknowledged else TradingMode.NORMAL
        block_new = state != RuntimeState.READY

    if recovery_requires_ack and not operator_acknowledged:
        blockers.append("btc_recovery_operator_ack_required")
        block_new = True
        if connected and mode not in {TradingMode.NO_TRANSPORT, TradingMode.FROZEN}:
            mode = TradingMode.CANCEL_ONLY
            state = RuntimeState.RECOVERY_PENDING

    blockers_tuple = _dedupe(blockers)
    if blockers_tuple:
        block_new = True
        if state == RuntimeState.READY:
            state = RuntimeState.DEGRADED if connected else RuntimeState.RECONNECTING
            mode = TradingMode.CANCEL_ONLY if connected else TradingMode.NO_TRANSPORT
    snapshot = RuntimeSnapshot(
        state=state,
        trading_mode=mode,
        block_new_orders=block_new,
        connected=connected,
        account_verified=account_ok,
        authentication_ok=account_ok,
        reconciliation_status=ReconciliationStatus.PASS if ledger_obj.reconciled else ReconciliationStatus.FAILED,
        recovery_requires_ack=recovery_requires_ack,
        operator_acknowledged=operator_acknowledged,
        last_transition_at=observed_at,
        transition_reason="btc_runtime_projection",
        blockers=blockers_tuple,
        broker_truth_fresh=broker_obj.fresh,
        kill_switch_tripped=bool(broker_obj.kill_switch_tripped),
        risk_state_valid=ledger_obj.fresh and ledger_obj.reconciled,
    )
    return BTCProjectionResult(
        snapshot=snapshot,
        blockers=blockers_tuple,
        broker_truth=broker_obj,
        ledger_freshness=ledger_obj,
        endpoint_capability=capability_obj,
        identity=identity_obj,
    )


def project_btc_runtime_snapshot(
    *args: Any,
    return_result: bool = False,
    **kwargs: Any,
) -> RuntimeSnapshot | BTCProjectionResult:
    """Return the canonical snapshot (or the full projection with opt-in).

    The default return value is deliberately the shared ``RuntimeSnapshot`` so
    consumers cannot accidentally treat a BTC-specific wrapper as a second
    runtime state type.  ``return_result=True`` is useful for audit/report
    callers that also need the normalized evidence objects.
    """

    result = build_btc_runtime_projection(*args, **kwargs)
    return result if return_result else result.snapshot


class BTCPermissionEvaluator(PermissionEvaluator):
    """BTC spelling that always delegates to the canonical shared evaluator."""

    def evaluate_btc_action(
        self,
        action: RuntimeAction | str,
        *,
        order_intent: OrderIntent,
        risk_decision: RiskDecision,
        broker_truth: BTCBrokerTruth | Mapping[str, Any],
        ledger_freshness: BTCLedgerFreshness | Mapping[str, Any],
        endpoint_capability: BTCEndpointCapability | Mapping[str, Any],
        identity: BTCExecutionIdentity | Mapping[str, Any],
        lifecycle: object | Mapping[str, Any] | None = None,
        risk_evidence: RuntimeRiskEvidence | Mapping[str, Any] | None = None,
        current_head: str | None = None,
        session_id: str | None = None,
        epoch: int | None = None,
    ) -> PermissionDecision:
        return self.evaluate_action(
            action,
            RuntimePermissionContext(
                order_intent=order_intent,
                risk_decision=risk_decision,
                broker_truth=broker_truth,
                ledger_freshness=ledger_freshness,
                endpoint_capability=endpoint_capability,
                execution_identity=identity,
                lifecycle=lifecycle,
                expected_mode=_value_text(_read(identity, "mode", default="")),
                risk_evidence=risk_evidence,
                current_head=current_head,
                session_id=session_id,
                epoch=epoch,
            ),
        )


@dataclass(frozen=True)
class BTCClientOrderLifecycleRecord:
    client_order_id: str
    order_intent_id: str
    mode: BTCExecutionMode
    client_order_namespace: str
    status: BTCOrderLifecycleStatus
    sequence: int
    timestamp_utc: datetime
    broker_order_id: str = ""
    reason: str = ""
    query_required_before_retry: bool = False
    reconciliation_complete: bool = False
    action: str = RuntimeAction.SUBMIT_NEW_ORDER.value

    @property
    def cl_ord_id(self) -> str:
        return self.client_order_id

    @property
    def clOrdId(self) -> str:  # noqa: N802 - venue spelling is part of the contract
        return self.client_order_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "lifecycle_version": BTC_ORDER_LIFECYCLE_VERSION,
            "client_order_id": self.client_order_id,
            "clOrdId": self.client_order_id,
            "order_intent_id": self.order_intent_id,
            "mode": self.mode.value,
            "client_order_namespace": self.client_order_namespace,
            "status": self.status.value,
            "sequence": self.sequence,
            "timestamp_utc": isoformat_utc(self.timestamp_utc),
            "broker_order_id": self.broker_order_id,
            "reason": self.reason,
            "query_required_before_retry": self.query_required_before_retry,
            "reconciliation_complete": self.reconciliation_complete,
            "action": self.action,
        }


class BTCClientOrderLifecycleStore:
    """Append-only, fsync-backed clOrdId lifecycle for fake/paper tests.

    ``prepare`` is the only entry point that creates a sendable record and it
    must succeed before a transport callback is invoked.  ``AMBIGUOUS`` and
    ``SENT`` records can only be resolved by ``query_by_client_order_id``;
    there is no blind resend method.
    """

    def __init__(self, root: Path | str, *, identity: BTCExecutionIdentity) -> None:
        self.root = Path(root).resolve()
        self.identity = identity
        if identity.state_directory and self.root != Path(identity.state_directory).resolve():
            raise BTCExecutionBlocked("execution_state_directory_mismatch")
        if identity.mode in {BTCExecutionMode.DEMO, BTCExecutionMode.LIVE} and identity.mode.value not in self.root.name.lower():
            raise BTCExecutionBlocked("execution_state_directory_mode_marker_missing")
        self.events_path = self.root / "client_order_lifecycle.jsonl"
        self._records: dict[str, BTCClientOrderLifecycleRecord] = {}
        self._load()

    def _load(self) -> None:
        if not self.events_path.exists():
            return
        for line in self.events_path.read_bytes().splitlines():
            try:
                event = json.loads(line)
                if str(event.get("mode")) != self.identity.mode.value:
                    raise BTCExecutionBlocked("execution_lifecycle_mode_crossed")
                if str(event.get("client_order_namespace")) != self.identity.client_order_namespace:
                    raise BTCExecutionBlocked("execution_lifecycle_namespace_crossed")
                record = BTCClientOrderLifecycleRecord(
                    client_order_id=str(event["client_order_id"]),
                    order_intent_id=str(event["order_intent_id"]),
                    mode=self.identity.mode,
                    client_order_namespace=self.identity.client_order_namespace,
                    status=BTCOrderLifecycleStatus(str(event["status"])),
                    sequence=int(event["sequence"]),
                    timestamp_utc=ensure_utc(datetime.fromisoformat(str(event["timestamp_utc"]).replace("Z", "+00:00"))),
                    broker_order_id=str(event.get("broker_order_id", "")),
                    reason=str(event.get("reason", "")),
                    query_required_before_retry=bool(event.get("query_required_before_retry", False)),
                    reconciliation_complete=bool(event.get("reconciliation_complete", False)),
                    action=str(event.get("action", RuntimeAction.SUBMIT_NEW_ORDER.value)),
                )
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                raise BTCExecutionBlocked("execution_lifecycle_corrupt") from exc
            previous = self._records.get(record.client_order_id)
            if previous is not None and record.sequence <= previous.sequence:
                raise BTCExecutionBlocked("execution_lifecycle_sequence_invalid")
            self._records[record.client_order_id] = record

    def _append(
        self,
        *,
        intent: OrderIntent,
        status: BTCOrderLifecycleStatus,
        reason: str,
        broker_order_id: str = "",
        query_required_before_retry: bool = False,
        reconciliation_complete: bool = False,
        action: RuntimeAction | str = RuntimeAction.SUBMIT_NEW_ORDER,
    ) -> BTCClientOrderLifecycleRecord:
        existing = self._records.get(intent.client_order_id)
        if existing is not None and existing.order_intent_id != intent.order_intent_id:
            raise BTCExecutionBlocked("client_order_id_semantic_conflict")
        sequence = 1 if existing is None else existing.sequence + 1
        record = BTCClientOrderLifecycleRecord(
            client_order_id=intent.client_order_id,
            order_intent_id=intent.order_intent_id,
            mode=self.identity.mode,
            client_order_namespace=self.identity.client_order_namespace,
            status=status,
            sequence=sequence,
            timestamp_utc=ensure_utc(utc_now()),
            broker_order_id=broker_order_id,
            reason=reason,
            query_required_before_retry=query_required_before_retry,
            reconciliation_complete=reconciliation_complete,
            action=(action.value if isinstance(action, RuntimeAction) else str(action)),
        )
        self.root.mkdir(parents=True, exist_ok=True)
        with self.events_path.open("ab") as handle:
            handle.write(_canonical(record.to_dict()) + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        self._records[intent.client_order_id] = record
        return record

    def prepare(
        self,
        order_intent: OrderIntent,
        *,
        reason: str = "before_transport",
        action: RuntimeAction | str = RuntimeAction.SUBMIT_NEW_ORDER,
    ) -> BTCClientOrderLifecycleRecord:
        if not order_intent.client_order_id:
            raise BTCExecutionBlocked("client_order_id_missing")
        existing = self._records.get(order_intent.client_order_id)
        if existing is not None:
            if existing.order_intent_id != order_intent.order_intent_id:
                raise BTCExecutionBlocked("client_order_id_semantic_conflict")
            return existing
        return self._append(intent=order_intent, status=BTCOrderLifecycleStatus.PREPARED, reason=reason, action=action)

    def get(self, client_order_id: str) -> BTCClientOrderLifecycleRecord | None:
        return self._records.get(str(client_order_id))

    def mark_sent(
        self,
        order_intent: OrderIntent,
        *,
        broker_order_id: str = "",
        action: RuntimeAction | str = RuntimeAction.SUBMIT_NEW_ORDER,
    ) -> BTCClientOrderLifecycleRecord:
        current = self.prepare(order_intent)
        if current.status not in {BTCOrderLifecycleStatus.PREPARED, BTCOrderLifecycleStatus.SENT}:
            raise BTCExecutionBlocked("client_order_lifecycle_not_sendable")
        return self._append(
            intent=order_intent,
            status=BTCOrderLifecycleStatus.SENT,
            reason="transport_called",
            broker_order_id=broker_order_id,
            query_required_before_retry=True,
            action=action,
        )

    def mark_ambiguous(
        self,
        order_intent: OrderIntent,
        *,
        reason: str = "transport_outcome_ambiguous",
        action: RuntimeAction | str = RuntimeAction.SUBMIT_NEW_ORDER,
    ) -> BTCClientOrderLifecycleRecord:
        current = self.prepare(order_intent)
        if current.status not in {BTCOrderLifecycleStatus.PREPARED, BTCOrderLifecycleStatus.SENT, BTCOrderLifecycleStatus.AMBIGUOUS}:
            raise BTCExecutionBlocked("client_order_lifecycle_not_ambiguous")
        return self._append(
            intent=order_intent,
            status=BTCOrderLifecycleStatus.AMBIGUOUS,
            reason=reason,
            broker_order_id=current.broker_order_id,
            query_required_before_retry=True,
            action=action,
        )

    def resolve(
        self,
        order_intent: OrderIntent,
        *,
        status: str,
        broker_order_id: str = "",
        reason: str = "query_by_client_order_id",
        action: RuntimeAction | str = RuntimeAction.SUBMIT_NEW_ORDER,
    ) -> BTCClientOrderLifecycleRecord:
        normalized = str(status).strip().lower()
        mapping = {
            "accepted": BTCOrderLifecycleStatus.ACCEPTED,
            "partially_filled": BTCOrderLifecycleStatus.PARTIALLY_FILLED,
            "filled": BTCOrderLifecycleStatus.FILLED,
            "cancelled": BTCOrderLifecycleStatus.CANCELLED,
            "canceled": BTCOrderLifecycleStatus.CANCELLED,
            "rejected": BTCOrderLifecycleStatus.REJECTED,
            "resolved": BTCOrderLifecycleStatus.RESOLVED,
        }
        if normalized not in mapping:
            return self.mark_ambiguous(
                order_intent,
                reason="query_by_client_order_id_unknown",
                action=action,
            )
        return self._append(
            intent=order_intent,
            status=mapping[normalized],
            reason=reason,
            broker_order_id=broker_order_id,
            query_required_before_retry=False,
            action=action,
        )

    def mark_reconciled(
        self,
        order_intent: OrderIntent,
        *,
        status: str = "resolved",
        broker_order_id: str = "",
        order_reconciled: bool = False,
        fill_reconciled: bool = False,
        position_reconciled: bool = False,
        action: RuntimeAction | str = RuntimeAction.SUBMIT_NEW_ORDER,
    ) -> BTCClientOrderLifecycleRecord:
        """Close the clOrdId lifecycle only after all reconciliation legs pass."""

        if not (order_reconciled and fill_reconciled and position_reconciled):
            raise BTCExecutionBlocked("clord_order_fill_position_reconciliation_required")
        current = self.get(order_intent.client_order_id)
        if current is None:
            raise BTCExecutionBlocked("client_order_lifecycle_missing_before_reconciliation")
        resolved = self.resolve(
            order_intent,
            status=status,
            broker_order_id=broker_order_id or current.broker_order_id,
            reason="order_fill_position_reconciled",
            action=action,
        )
        # ``resolve`` deliberately emits the broker observation first.  The
        # final immutable event marks the reconciliation contract complete.
        return self._append(
            intent=order_intent,
            status=BTCOrderLifecycleStatus.RESOLVED,
            reason="order_fill_position_reconciled",
            broker_order_id=broker_order_id or resolved.broker_order_id,
            query_required_before_retry=False,
            reconciliation_complete=True,
            action=action,
        )

    def query_by_client_order_id(
        self,
        order_intent: OrderIntent,
        query: Callable[[str], Mapping[str, Any] | str | None],
    ) -> BTCClientOrderLifecycleRecord:
        current = self.get(order_intent.client_order_id)
        if current is None:
            raise BTCExecutionBlocked("client_order_lifecycle_missing_before_query")
        if current.status not in {BTCOrderLifecycleStatus.SENT, BTCOrderLifecycleStatus.AMBIGUOUS}:
            return current
        result = query(order_intent.client_order_id)
        if result is None:
            return self.mark_ambiguous(order_intent, reason="query_by_client_order_id_no_result")
        if isinstance(result, Mapping):
            status = str(result.get("status", "unknown"))
            broker_order_id = str(result.get("broker_order_id", result.get("ordId", "")))
        else:
            status = str(result)
            broker_order_id = ""
        return self.resolve(order_intent, status=status, broker_order_id=broker_order_id)

    def retry_decision(self, client_order_id: str) -> dict[str, Any]:
        record = self.get(client_order_id)
        if record is None:
            return {
                "allowed": False,
                "action": "block",
                "reason": "client_order_lifecycle_missing",
                "query_by_client_order_id_required": True,
            }
        if record.status in {BTCOrderLifecycleStatus.SENT, BTCOrderLifecycleStatus.AMBIGUOUS}:
            return {
                "allowed": False,
                "action": "query_by_client_order_id",
                "reason": "ambiguous_order_query_required_before_retry",
                "query_by_client_order_id_required": True,
            }
        if record.status is BTCOrderLifecycleStatus.PREPARED and not record.reconciliation_complete:
            return {
                "allowed": True,
                "action": "send_once",
                "reason": "durable_clordid_prepared",
                "query_by_client_order_id_required": False,
            }
        return {
            "allowed": False,
            "action": "block",
            "reason": "client_order_lifecycle_terminal",
            "query_by_client_order_id_required": False,
        }

    @property
    def records(self) -> tuple[BTCClientOrderLifecycleRecord, ...]:
        return tuple(self._records.values())


_DISPATCH_ISSUER = object()


class BTCDispatchAuthorization:
    """Short-lived, boundary-issued authorization for one dispatch.

    The private issuer token prevents a normal transport caller from creating
    or cloning an authorization object.  The object is also bound to the
    request digest, lifecycle sequence, immutable snapshot fingerprint, source
    head, and all execution identity namespaces; any change invalidates it.
    """

    __slots__ = (
        "_action",
        "_request_digest",
        "_client_order_id",
        "_source_head",
        "_session_id",
        "_key_namespace",
        "_account_identity",
        "_client_order_namespace",
        "_epoch",
        "_snapshot_fingerprint",
        "_lifecycle_sequence",
        "_issued_at",
        "_expires_at",
        "_revoked",
    )

    def __init__(
        self,
        *,
        _issuer: object | None = None,
        action: str = "",
        request_digest: str = "",
        client_order_id: str = "",
        source_head: str = "",
        session_id: str = "",
        key_namespace: str = "",
        account_identity: str = "",
        client_order_namespace: str = "",
        epoch: int | None = None,
        snapshot_fingerprint: str = "",
        lifecycle_sequence: int = 0,
        issued_at: datetime | None = None,
        expires_at: datetime | None = None,
    ) -> None:
        if _issuer is not _DISPATCH_ISSUER:
            raise BTCExecutionBlocked("dispatch_authorization_private")
        self._action = str(action)
        self._request_digest = str(request_digest)
        self._client_order_id = str(client_order_id)
        self._source_head = str(source_head)
        self._session_id = str(session_id)
        self._key_namespace = str(key_namespace)
        self._account_identity = str(account_identity)
        self._client_order_namespace = str(client_order_namespace)
        self._epoch = epoch
        self._snapshot_fingerprint = str(snapshot_fingerprint)
        self._lifecycle_sequence = int(lifecycle_sequence)
        self._issued_at = ensure_utc(issued_at or utc_now())
        self._expires_at = ensure_utc(expires_at or self._issued_at)
        self._revoked = False

    @classmethod
    def _issue(cls, **values: Any) -> "BTCDispatchAuthorization":
        return cls(_issuer=_DISPATCH_ISSUER, **values)

    @property
    def action(self) -> str:
        return self._action

    @property
    def request_digest(self) -> str:
        return self._request_digest

    @property
    def client_order_id(self) -> str:
        return self._client_order_id

    @property
    def source_head(self) -> str:
        return self._source_head

    @property
    def expires_at(self) -> datetime:
        return self._expires_at

    @property
    def revoked(self) -> bool:
        return self._revoked

    def revoke(self) -> None:
        self._revoked = True

    def valid_for(
        self,
        *,
        action: RuntimeAction | str,
        request_digest: str,
        client_order_id: str,
        source_head: str,
        session_id: str,
        key_namespace: str,
        account_identity: str,
        client_order_namespace: str,
        epoch: int | None,
        snapshot_fingerprint: str,
        lifecycle_sequence: int,
        now: datetime | None = None,
    ) -> bool:
        if self._revoked:
            return False
        when = ensure_utc(now or utc_now())
        if when >= self._expires_at:
            return False
        normalized = action.value if isinstance(action, RuntimeAction) else str(action)
        return all(
            (
                self._action == normalized,
                self._request_digest == str(request_digest),
                self._client_order_id == str(client_order_id),
                self._source_head == str(source_head),
                self._session_id == str(session_id),
                self._key_namespace == str(key_namespace),
                self._account_identity == str(account_identity),
                self._client_order_namespace == str(client_order_namespace),
                self._epoch == epoch,
                self._snapshot_fingerprint == str(snapshot_fingerprint),
                self._lifecycle_sequence == int(lifecycle_sequence),
            )
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self._action,
            "request_digest": self._request_digest,
            "client_order_id": self._client_order_id,
            "source_head": self._source_head,
            "session_id": self._session_id,
            "key_namespace": self._key_namespace,
            "account_identity": self._account_identity,
            "client_order_namespace": self._client_order_namespace,
            "epoch": self._epoch,
            "snapshot_fingerprint": self._snapshot_fingerprint,
            "lifecycle_sequence": self._lifecycle_sequence,
            "issued_at": isoformat_utc(self._issued_at),
            "expires_at": isoformat_utc(self._expires_at),
            "revoked": self._revoked,
        }


class BTCDispatchAuthorizer:
    """Boundary-owned authorizer contract exposed to a broker adapter."""

    __slots__ = ("_boundary",)

    def __init__(self, *, _issuer: object | None = None, boundary: "BTCExecutionBoundary" | None = None) -> None:
        if _issuer is not _DISPATCH_ISSUER or boundary is None:
            raise BTCExecutionBlocked("dispatch_authorizer_private")
        self._boundary = boundary

    def issue(
        self,
        action: RuntimeAction | str,
        *,
        order_intent: OrderIntent,
        risk_decision: RiskDecision,
        risk_evidence: RuntimeRiskEvidence | Mapping[str, Any] | None = None,
    ) -> BTCDispatchAuthorization:
        return self._boundary.issue_dispatch_authorization(
            action,
            order_intent=order_intent,
            risk_decision=risk_decision,
            risk_evidence=risk_evidence,
        )

    def revoke(self, authorization: BTCDispatchAuthorization) -> None:
        authorization.revoke()


@dataclass(frozen=True)
class BTCExecutionResult:
    decision: PermissionDecision
    lifecycle: BTCClientOrderLifecycleRecord | None
    transport_called: bool
    receipt: object | None = None
    blockers: tuple[str, ...] = ()
    action: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision.to_dict(),
            "lifecycle": None if self.lifecycle is None else self.lifecycle.to_dict(),
            "transport_called": bool(self.transport_called),
            "receipt_present": self.receipt is not None,
            "blockers": list(self.blockers),
            "action": self.action,
            "network_accessed": False,
            "live_allowed": False,
        }


class BTCExecutionBoundary:
    """One final, fake-only boundary shared by all six BTC actions."""

    _HANDLERS = {
        RuntimeAction.SUBMIT_NEW_ORDER.value: ("submit", "submit_new_order"),
        RuntimeAction.CANCEL_ORDER.value: ("cancel", "cancel_order"),
        RuntimeAction.REPLACE_ORDER.value: ("replace", "replace_order"),
        RuntimeAction.REDUCE_ONLY.value: ("reduce_only", "reduce_position"),
        RuntimeAction.ATTACH_PROTECTION.value: ("attach_protection", "attach_stop"),
        RuntimeAction.DEAD_MAN.value: ("dead_man", "dead_man_switch", "deadman"),
    }

    def __init__(
        self,
        *,
        evaluator: PermissionEvaluator,
        lifecycle_store: BTCClientOrderLifecycleStore,
        identity: BTCExecutionIdentity,
        broker_truth: BTCBrokerTruth | Mapping[str, Any],
        ledger_freshness: BTCLedgerFreshness | Mapping[str, Any],
        endpoint_capability: BTCEndpointCapability | Mapping[str, Any],
        risk_evidence: RuntimeRiskEvidence | Mapping[str, Any] | None = None,
        current_head: str | None = None,
        session_id: str | None = None,
        epoch: int | None = None,
        transport: object | None = None,
        dispatch_ttl_seconds: float = 5.0,
    ) -> None:
        self.evaluator = evaluator
        self.lifecycle_store = lifecycle_store
        self.identity = identity
        self.broker_truth = broker_truth
        self.ledger_freshness = ledger_freshness
        self.endpoint_capability = endpoint_capability
        self.risk_evidence = risk_evidence
        self.current_head = str(current_head or identity.source_head or "")
        self.session_id = str(session_id or identity.session_id or "")
        self.epoch = identity.epoch if epoch is None else int(epoch)
        self.transport = transport
        self.dispatch_ttl_seconds = max(0.1, min(float(dispatch_ttl_seconds), 30.0))
        self._active_authorizations: dict[tuple[str, str], BTCDispatchAuthorization] = {}
        self._dispatch_authorizer = BTCDispatchAuthorizer(_issuer=_DISPATCH_ISSUER, boundary=self)

    @property
    def dispatch_authorizer(self) -> BTCDispatchAuthorizer:
        return self._dispatch_authorizer

    @property
    def current_snapshot(self) -> RuntimeSnapshot:
        return self.evaluator.snapshot

    def _context(
        self,
        *,
        order_intent: OrderIntent,
        risk_decision: RiskDecision,
        risk_evidence: RuntimeRiskEvidence | Mapping[str, Any] | None,
        lifecycle: object | Mapping[str, Any] | None,
    ) -> RuntimePermissionContext:
        return RuntimePermissionContext(
            order_intent=order_intent,
            risk_decision=risk_decision,
            risk_evidence=self.risk_evidence if risk_evidence is None else risk_evidence,
            broker_truth=self.broker_truth,
            ledger_freshness=self.ledger_freshness,
            endpoint_capability=self.endpoint_capability,
            execution_identity=self.identity,
            lifecycle=lifecycle,
            expected_mode=self.identity.mode.value,
            current_head=self.current_head,
            session_id=self.session_id,
            epoch=self.epoch,
        )

    def authorize(
        self,
        action: RuntimeAction | str,
        *,
        order_intent: OrderIntent,
        risk_decision: RiskDecision,
        risk_evidence: RuntimeRiskEvidence | Mapping[str, Any] | None = None,
        lifecycle: object | Mapping[str, Any] | None = None,
    ) -> PermissionDecision:
        return self.evaluator.evaluate_action(
            action,
            self._context(
                order_intent=order_intent,
                risk_decision=risk_decision,
                risk_evidence=risk_evidence,
                lifecycle=lifecycle,
            ),
        )

    def _action_name(self, action: RuntimeAction | str) -> str:
        value = action.value if isinstance(action, RuntimeAction) else str(action)
        normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "new_order": RuntimeAction.SUBMIT_NEW_ORDER.value,
            "submit_order": RuntimeAction.SUBMIT_NEW_ORDER.value,
            "cancel": RuntimeAction.CANCEL_ORDER.value,
            "replace": RuntimeAction.REPLACE_ORDER.value,
            "reduce_position": RuntimeAction.REDUCE_ONLY.value,
            "protection": RuntimeAction.ATTACH_PROTECTION.value,
            "deadman": RuntimeAction.DEAD_MAN.value,
        }
        return aliases.get(normalized, normalized)

    def _snapshot_fingerprint(self) -> str:
        return _digest(self.current_snapshot.to_dict())

    def _request_digest(
        self,
        action: str,
        order_intent: OrderIntent,
        risk_decision: RiskDecision,
        risk_evidence: RuntimeRiskEvidence | Mapping[str, Any] | None,
    ) -> str:
        return _digest(
            {
                "action": action,
                "intent_id": order_intent.order_intent_id,
                "client_order_id": order_intent.client_order_id,
                "symbol": order_intent.symbol,
                "side": _value_text(order_intent.side),
                "quantity": order_intent.quantity,
                "order_type": _value_text(order_intent.order_type),
                "risk_intent_id": risk_decision.order_intent_id,
                "risk_check_id": risk_decision.risk_check_id,
                "risk_version": risk_decision.risk_version,
                "risk_evidence": (
                    risk_evidence.to_dict()
                    if isinstance(risk_evidence, RuntimeRiskEvidence)
                    else dict(risk_evidence or {})
                ),
            }
        )

    def issue_dispatch_authorization(
        self,
        action: RuntimeAction | str,
        *,
        order_intent: OrderIntent,
        risk_decision: RiskDecision,
        risk_evidence: RuntimeRiskEvidence | Mapping[str, Any] | None = None,
    ) -> BTCDispatchAuthorization:
        name = self._action_name(action)
        lifecycle = self.lifecycle_store.get(order_intent.client_order_id)
        decision = self.authorize(
            name,
            order_intent=order_intent,
            risk_decision=risk_decision,
            risk_evidence=risk_evidence,
            lifecycle=lifecycle,
        )
        if not decision.allowed:
            raise BTCExecutionBlocked("dispatch_authorization_denied:" + ",".join(decision.reasons))
        if lifecycle is None or lifecycle.status is not BTCOrderLifecycleStatus.PREPARED:
            raise BTCExecutionBlocked("dispatch_authorization_lifecycle_not_prepared")
        key = (name, order_intent.client_order_id)
        previous = self._active_authorizations.pop(key, None)
        if previous is not None:
            previous.revoke()
        now = ensure_utc(utc_now())
        authorization = BTCDispatchAuthorization._issue(
            action=name,
            request_digest=self._request_digest(
                name,
                order_intent,
                risk_decision,
                self.risk_evidence if risk_evidence is None else risk_evidence,
            ),
            client_order_id=order_intent.client_order_id,
            source_head=self.current_head,
            session_id=self.session_id,
            key_namespace=self.identity.key_namespace,
            account_identity=self.identity.account_identity,
            client_order_namespace=self.identity.client_order_namespace,
            epoch=self.epoch,
            snapshot_fingerprint=self._snapshot_fingerprint(),
            lifecycle_sequence=lifecycle.sequence,
            issued_at=now,
            expires_at=now + timedelta(seconds=self.dispatch_ttl_seconds),
        )
        self._active_authorizations[key] = authorization
        return authorization

    def _authorization_valid(
        self,
        authorization: BTCDispatchAuthorization,
        *,
        action: str,
        order_intent: OrderIntent,
        risk_decision: RiskDecision,
        risk_evidence: RuntimeRiskEvidence | Mapping[str, Any] | None,
        lifecycle: BTCClientOrderLifecycleRecord,
    ) -> bool:
        expected = self._active_authorizations.get((action, order_intent.client_order_id))
        if expected is not authorization:
            return False
        evidence = self.risk_evidence if risk_evidence is None else risk_evidence
        return authorization.valid_for(
            action=action,
            request_digest=self._request_digest(action, order_intent, risk_decision, evidence),
            client_order_id=order_intent.client_order_id,
            source_head=self.current_head,
            session_id=self.session_id,
            key_namespace=self.identity.key_namespace,
            account_identity=self.identity.account_identity,
            client_order_namespace=self.identity.client_order_namespace,
            epoch=self.epoch,
            snapshot_fingerprint=self._snapshot_fingerprint(),
            lifecycle_sequence=lifecycle.sequence,
        )

    def execute_action(
        self,
        action: RuntimeAction | str,
        *,
        order_intent: OrderIntent,
        risk_decision: RiskDecision,
        risk_evidence: RuntimeRiskEvidence | Mapping[str, Any] | None = None,
        authorization: BTCDispatchAuthorization | None = None,
    ) -> BTCExecutionResult:
        name = self._action_name(action)
        if name not in self._HANDLERS:
            decision = PermissionDecision(name, False, (f"unknown_runtime_action:{name}",))
            return BTCExecutionResult(decision, None, False, blockers=decision.reasons, action=name)

        existing = self.lifecycle_store.get(order_intent.client_order_id)
        if existing is not None and existing.status in {
            BTCOrderLifecycleStatus.SENT,
            BTCOrderLifecycleStatus.AMBIGUOUS,
        }:
            blocked = PermissionDecision(
                name,
                False,
                ("ambiguous_order_query_required_before_retry", "blind_resend_forbidden"),
            )
            return BTCExecutionResult(blocked, existing, False, blockers=blocked.reasons, action=name)
        if existing is not None and existing.status is not BTCOrderLifecycleStatus.PREPARED:
            blocked = PermissionDecision(
                name,
                False,
                ("clord_order_fill_position_reconciliation_required", "client_order_lifecycle_terminal"),
            )
            return BTCExecutionResult(blocked, existing, False, blockers=blocked.reasons, action=name)
        if existing is not None and existing.action not in {name, RuntimeAction.SUBMIT_NEW_ORDER.value}:
            blocked = PermissionDecision(name, False, ("client_order_lifecycle_action_mismatch",))
            return BTCExecutionResult(blocked, existing, False, blockers=blocked.reasons, action=name)
        try:
            lifecycle = self.lifecycle_store.prepare(order_intent, action=name)
        except BTCExecutionBlocked as exc:
            decision = PermissionDecision(name, False, (str(exc),))
            return BTCExecutionResult(decision, None, False, blockers=decision.reasons, action=name)

        decision = self.authorize(
            name,
            order_intent=order_intent,
            risk_decision=risk_decision,
            risk_evidence=risk_evidence,
            lifecycle=lifecycle,
        )
        if not decision.allowed:
            return BTCExecutionResult(decision, lifecycle, False, blockers=decision.reasons, action=name)
        if self.transport is None:
            blocked = PermissionDecision(name, False, ("transport_not_configured", "btc_live_default_no_transport"))
            return BTCExecutionResult(blocked, lifecycle, False, blockers=blocked.reasons, action=name)

        if authorization is None:
            try:
                authorization = self.issue_dispatch_authorization(
                    name,
                    order_intent=order_intent,
                    risk_decision=risk_decision,
                    risk_evidence=risk_evidence,
                )
            except BTCExecutionBlocked as exc:
                blocked = PermissionDecision(name, False, (str(exc),))
                return BTCExecutionResult(blocked, lifecycle, False, blockers=blocked.reasons, action=name)
        if not self._authorization_valid(
            authorization,
            action=name,
            order_intent=order_intent,
            risk_decision=risk_decision,
            risk_evidence=risk_evidence,
            lifecycle=lifecycle,
        ):
            blocked = PermissionDecision(name, False, ("dispatch_authorization_invalid",))
            return BTCExecutionResult(blocked, lifecycle, False, blockers=blocked.reasons, action=name)

        handler_names = self._HANDLERS[name]
        handler = None
        handler_name = handler_names[0]
        for candidate in handler_names:
            maybe_handler = getattr(self.transport, candidate, None)
            if callable(maybe_handler):
                handler_name = candidate
                handler = maybe_handler
                break
        if handler is None:
            blocked = PermissionDecision(name, False, (f"transport_handler_missing:{handler_name}",))
            return BTCExecutionResult(blocked, lifecycle, False, blockers=blocked.reasons, action=name)
        try:
            receipt = handler(order_intent)
        except Exception as exc:  # every post-dispatch uncertainty is ambiguous
            lifecycle = self.lifecycle_store.mark_ambiguous(
                order_intent,
                reason=f"transport_dispatch_exception:{type(exc).__name__}",
                action=name,
            )
            blocked = PermissionDecision(
                name,
                False,
                (
                    "transport_outcome_ambiguous",
                    "query_by_client_order_id_required",
                    f"transport_dispatch_exception:{type(exc).__name__}",
                ),
            )
            authorization.revoke()
            self._active_authorizations.pop((name, order_intent.client_order_id), None)
            return BTCExecutionResult(blocked, lifecycle, True, blockers=blocked.reasons, action=name)
        lifecycle = self.lifecycle_store.mark_sent(order_intent, action=name)
        authorization.revoke()
        self._active_authorizations.pop((name, order_intent.client_order_id), None)
        return BTCExecutionResult(decision, lifecycle, True, receipt=receipt, action=name)

    dispatch_action = execute_action
    dispatch = execute_action

    def submit(self, *, order_intent: OrderIntent, risk_decision: RiskDecision, risk_evidence: RuntimeRiskEvidence | Mapping[str, Any] | None = None, authorization: BTCDispatchAuthorization | None = None) -> BTCExecutionResult:
        return self.execute_action(RuntimeAction.SUBMIT_NEW_ORDER, order_intent=order_intent, risk_decision=risk_decision, risk_evidence=risk_evidence, authorization=authorization)

    submit_new_order = submit

    def cancel(self, *, order_intent: OrderIntent, risk_decision: RiskDecision, risk_evidence: RuntimeRiskEvidence | Mapping[str, Any] | None = None, authorization: BTCDispatchAuthorization | None = None) -> BTCExecutionResult:
        return self.execute_action(RuntimeAction.CANCEL_ORDER, order_intent=order_intent, risk_decision=risk_decision, risk_evidence=risk_evidence, authorization=authorization)

    cancel_order = cancel

    def replace(self, *, order_intent: OrderIntent, risk_decision: RiskDecision, risk_evidence: RuntimeRiskEvidence | Mapping[str, Any] | None = None, authorization: BTCDispatchAuthorization | None = None) -> BTCExecutionResult:
        return self.execute_action(RuntimeAction.REPLACE_ORDER, order_intent=order_intent, risk_decision=risk_decision, risk_evidence=risk_evidence, authorization=authorization)

    replace_order = replace

    def reduce_only(self, *, order_intent: OrderIntent, risk_decision: RiskDecision, risk_evidence: RuntimeRiskEvidence | Mapping[str, Any] | None = None, authorization: BTCDispatchAuthorization | None = None) -> BTCExecutionResult:
        return self.execute_action(RuntimeAction.REDUCE_ONLY, order_intent=order_intent, risk_decision=risk_decision, risk_evidence=risk_evidence, authorization=authorization)

    reduce_position = reduce_only

    def attach_protection(self, *, order_intent: OrderIntent, risk_decision: RiskDecision, risk_evidence: RuntimeRiskEvidence | Mapping[str, Any] | None = None, authorization: BTCDispatchAuthorization | None = None) -> BTCExecutionResult:
        return self.execute_action(RuntimeAction.ATTACH_PROTECTION, order_intent=order_intent, risk_decision=risk_decision, risk_evidence=risk_evidence, authorization=authorization)

    attach_stop = attach_protection

    def dead_man(self, *, order_intent: OrderIntent, risk_decision: RiskDecision, risk_evidence: RuntimeRiskEvidence | Mapping[str, Any] | None = None, authorization: BTCDispatchAuthorization | None = None) -> BTCExecutionResult:
        return self.execute_action(RuntimeAction.DEAD_MAN, order_intent=order_intent, risk_decision=risk_decision, risk_evidence=risk_evidence, authorization=authorization)

    dead_man_switch = dead_man

    @property
    def safety_flags(self) -> dict[str, bool]:
        return {
            "network_accessed": False,
            "private_endpoint_allowed": False,
            "order_endpoint_allowed": False,
            "paper_allowed": False,
            "live_allowed": False,
            "live_ready": False,
            "auto_start": False,
            "auto_scale": False,
            "withdraw_allowed": False,
        }


class BTCExecutionCapabilityAdapter(Protocol):
    """Backend-owned view of the actual Demo transport capability."""

    def capability_for(
        self,
        *,
        action: RuntimeAction,
        transport_context: object,
    ) -> BTCEndpointCapability: ...


class BTCDemoClientCapabilityAdapter:
    """Read Demo-only capability from the injected client configuration."""

    def capability_for(
        self,
        *,
        action: RuntimeAction,
        transport_context: object,
    ) -> BTCEndpointCapability:
        config = getattr(transport_context, "config", None)
        credential_service = str(
            getattr(config, "credential_service", "") or ""
        )
        private_read = bool(getattr(config, "allow_private_read", False))
        orders = bool(getattr(config, "allow_demo_orders", False))
        cancels = bool(getattr(config, "allow_demo_cancels", False))
        demo_identity = credential_service == "quant-system.okx-demo.trade"
        return BTCEndpointCapability(
            mode=BTCExecutionMode.DEMO,
            transport_enabled=demo_identity and private_read and (
                orders if action in {
                    RuntimeAction.SUBMIT_NEW_ORDER,
                    RuntimeAction.REDUCE_ONLY,
                    RuntimeAction.ATTACH_PROTECTION,
                } else cancels
            ),
            submit_new_order=demo_identity and private_read and orders,
            cancel_order=demo_identity and private_read and cancels,
            replace_order=False,
            reduce_only=demo_identity and private_read and orders,
            attach_protection=demo_identity and private_read and orders,
            dead_man=demo_identity and private_read and cancels,
            private_endpoint_allowed=demo_identity and private_read,
            order_endpoint_allowed=demo_identity and (orders or cancels),
        )


@dataclass(frozen=True)
class BTCExecutionDispatchFacts:
    """Fresh observations supplied to the backend-owned execution dispatcher."""

    exchange_snapshot: Mapping[str, Any]
    private_ws: Mapping[str, Any]
    ledger_reconciliation: Mapping[str, Any]
    credential_service: str
    runtime_run_id: str
    source_head: str
    epoch: int
    runtime_active: bool
    opening_allowed: bool
    cancel_only: bool
    risk_mode: str
    attached_protection: Mapping[str, Any] = field(default_factory=dict)


class _BTCExecutionCallbackTransport:
    """Maps the final boundary handler to the one callback supplied by OMS."""

    def __init__(self, callback: Callable[[OrderIntent], object]) -> None:
        self._callback = callback

    def submit_new_order(self, intent: OrderIntent) -> object:
        return self._callback(intent)

    submit = submit_new_order
    cancel_order = submit_new_order
    cancel = submit_new_order
    reduce_only = submit_new_order
    reduce_position = submit_new_order
    attach_protection = submit_new_order
    attach_stop = submit_new_order
    dead_man = submit_new_order
    dead_man_switch = submit_new_order


class BTCDemoExecutionDispatcher:
    """Composition-root-only Demo dispatcher for actual exchange actions.

    The authority and its paired verifier remain private to this object.  OMS
    can provide current raw observations and a final callback, but cannot mint
    risk evidence or substitute a permissive endpoint capability.
    """

    _PROTECTIVE_AUTHORITY_MAX_AGE = timedelta(seconds=120)

    def __init__(
        self,
        *,
        expected_source_head: str,
        state_directory: str | Path,
        capability_adapter: BTCExecutionCapabilityAdapter,
        credential_service: str,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._expected_source_head = str(expected_source_head)
        self._state_directory = str(Path(state_directory).resolve())
        self._capability_adapter = capability_adapter
        self._credential_service = str(credential_service)
        # Only the exchange-snapshot freshness decision uses this dependency.
        # Demo callers retain the wall-clock default; deterministic offline
        # replay may bind a sealed observation clock without changing TTLs.
        self._clock = clock or utc_now
        self._authority = RuntimeRiskEvidenceAuthority(
            name="btc-demo-backend-composition"
        )
        self._producer, self._verifier = self._authority.bind()

    def dispatch(
        self,
        *,
        action: RuntimeAction,
        order_intent: OrderIntent,
        risk_decision: RiskDecision,
        facts: BTCExecutionDispatchFacts,
        transport_context: object,
        callback: Callable[[OrderIntent], object],
    ) -> BTCExecutionResult:
        if action not in {
            RuntimeAction.SUBMIT_NEW_ORDER,
            RuntimeAction.CANCEL_ORDER,
            RuntimeAction.REDUCE_ONLY,
            RuntimeAction.ATTACH_PROTECTION,
            RuntimeAction.DEAD_MAN,
        }:
            raise BTCExecutionBlocked("btc_demo_dispatch_action_not_allowlisted")
        if (
            facts.source_head != self._expected_source_head
            or not _is_git_head(facts.source_head)
        ):
            raise BTCExecutionBlocked("btc_demo_dispatch_source_head_mismatch")
        if facts.credential_service != self._credential_service or not (
            facts.credential_service.startswith("quant-system.okx-demo.")
        ):
            raise BTCExecutionBlocked("btc_demo_dispatch_credential_namespace_invalid")
        raw_account = facts.exchange_snapshot.get("account")
        account = dict(raw_account) if isinstance(raw_account, Mapping) else {}
        permissions = {
            str(item)
            for item in account.get("permissions", [])
            if isinstance(item, (str, int, float))
        }
        account_verified = (
            account.get("account_level") == "2"
            and account.get("position_mode") == "long_short_mode"
            and "trade" in permissions
            and "withdraw" not in permissions
        )
        private_ws_current = (
            facts.private_ws.get("connected") is True
            and facts.private_ws.get("listener_alive") is True
            and facts.private_ws.get("opening_allowed_after_reconciliation")
            is True
        )
        ledger_current = (
            facts.ledger_reconciliation.get("status") == "reconciled"
            and facts.ledger_reconciliation.get(
                "current_state_exchange_snapshot_match"
            )
            is True
            and facts.ledger_reconciliation.get("funding_cashflow_reconciled")
            is True
        )
        if not facts.runtime_run_id or facts.epoch < 0:
            raise BTCExecutionBlocked("btc_demo_dispatch_runtime_identity_invalid")
        if action is RuntimeAction.SUBMIT_NEW_ORDER and (
            not facts.runtime_active
            or not facts.opening_allowed
            or facts.cancel_only
            or facts.risk_mode != "RUNNING"
        ):
            raise BTCExecutionBlocked("btc_demo_dispatch_opening_runtime_not_permitted")
        if action in {
            RuntimeAction.CANCEL_ORDER,
            RuntimeAction.REDUCE_ONLY,
            RuntimeAction.DEAD_MAN,
        } and facts.risk_mode not in {
            "RUNNING",
            "STARTUP_RECONCILING",
            "RISK_REDUCING",
            "FROZEN_UNKNOWN",
        }:
            raise BTCExecutionBlocked("btc_demo_dispatch_reduction_runtime_invalid")
        capability = self._capability_adapter.capability_for(
            action=action,
            transport_context=transport_context,
        )
        if not isinstance(capability, BTCEndpointCapability):
            raise BTCExecutionBlocked("btc_demo_dispatch_capability_adapter_invalid")
        account_identity = _digest(account)
        namespace = _demo_client_order_namespace(order_intent.client_order_id)
        if not namespace:
            raise BTCExecutionBlocked("btc_demo_dispatch_client_order_namespace_invalid")
        lifecycle_directory = Path(self._state_directory) / (
            "demo-namespace-"
            + hashlib.sha256(namespace.encode("utf-8")).hexdigest()[:16]
        )
        identity = BTCExecutionIdentity(
            mode=BTCExecutionMode.DEMO,
            state_directory=str(lifecycle_directory),
            account_identity=account_identity,
            key_namespace=facts.credential_service,
            client_order_namespace=namespace,
            account_verified=account_verified,
            transport_enabled=capability.transport_enabled,
            live_execution_allowed=False,
            auto_start=False,
            auto_scale=False,
            session_id=facts.runtime_run_id,
            epoch=facts.epoch,
            source_head=facts.source_head,
        )
        observed_at = _timestamp(facts.exchange_snapshot.get("captured_at_utc"))
        observation_now = ensure_utc(self._clock())
        snapshot_fresh = (
            observed_at is not None
            and timedelta(seconds=-5)
            <= observation_now - observed_at
            <= timedelta(seconds=30)
        )
        protective_snapshot_age_ok = (
            observed_at is not None
            and timedelta(seconds=-5)
            <= observation_now - observed_at
            <= self._PROTECTIVE_AUTHORITY_MAX_AGE
        )
        if observed_at is None:
            observed_at = observation_now
        ticker = _read(facts.exchange_snapshot, "ticker", default={})
        book = _read(facts.exchange_snapshot, "book", default={})
        market_current = (
            isinstance(ticker, Mapping)
            and isinstance(book, Mapping)
            and bool(_read(ticker, "bid", "ask", default=""))
            and bool(_read(book, "bids", default=[]))
            and bool(_read(book, "asks", default=[]))
        )
        protective_action = action in {
            RuntimeAction.CANCEL_ORDER,
            RuntimeAction.REDUCE_ONLY,
            RuntimeAction.DEAD_MAN,
        }
        # A protective action must remain available after a slow, successful
        # REST + Private WS + ledger authority chain.  Its exchange observation
        # keeps the original captured_at_utc (never rewritten), while the
        # independently verified WS and ledger facts prove that this dispatch
        # is reduction-only.  New risk and attached protection remain bound to
        # the strict 30-second exchange snapshot TTL below.
        protective_authority_current = (
            protective_action
            and protective_snapshot_age_ok
            and account_verified
            and private_ws_current
            and ledger_current
        )
        rest_current = account_verified and (
            snapshot_fresh or protective_authority_current
        )
        public_current = market_current and (
            snapshot_fresh or protective_authority_current
        )
        verified_reduction_projection = (
            action is RuntimeAction.REDUCE_ONLY
            and facts.risk_mode in {"RUNNING", "RISK_REDUCING"}
            and facts.runtime_active
            and not facts.cancel_only
            and protective_authority_current
            and public_current
            and capability.allows(action)
        )
        if verified_reduction_projection:
            # A reduction is not an exchange cancel-only condition.  First let
            # the canonical projection prove the complete healthy authority
            # chain, then narrow only this action to REDUCE_ONLY below.
            exchange_status = "ok"
        elif (
            action in {
                RuntimeAction.CANCEL_ORDER,
                RuntimeAction.DEAD_MAN,
            }
            and rest_current
        ):
            exchange_status = "cancel_only"
        elif facts.cancel_only or facts.risk_mode == "FROZEN_UNKNOWN":
            exchange_status = "cancel_only"
        elif action is RuntimeAction.REDUCE_ONLY:
            # An unverified reduction must never inherit the generic healthy
            # opening projection, including contradictory STARTUP facts.
            exchange_status = "unknown"
        elif facts.runtime_active and facts.opening_allowed and rest_current:
            exchange_status = "ok"
        else:
            exchange_status = "unknown"
        broker_truth = BTCBrokerTruth(
            fresh=rest_current,
            valid=account_verified,
            account_verified=account_verified,
            authoritative_account_verified=account_verified,
            account_verification_source=(
                "okx_demo_private_account_snapshot"
                if account_verified
                else ""
            ),
            account_identity=account_identity,
            venue="okx",
            source_head=facts.source_head,
            session_id=facts.runtime_run_id,
            epoch=facts.epoch,
            observed_at_utc=observed_at,
        )
        ledger = BTCLedgerFreshness(
            fresh=ledger_current,
            reconciled=ledger_current,
            observed_at_utc=observed_at,
            source="okx_demo_ledger_reconciliation",
        )
        projection = build_btc_runtime_projection(
            {
                "exchange_status": exchange_status,
                "public_ws_status": "connected" if public_current else "unknown",
                "private_ws_status": (
                    "connected" if private_ws_current else "unknown"
                ),
                "rest_status": "ok" if rest_current else "unknown",
                "mode": BTCExecutionMode.DEMO.value,
                "observed_at_utc": observed_at,
            },
            identity=identity,
            broker_truth=broker_truth,
            ledger_freshness=ledger,
            endpoint_capability=capability,
            now=observation_now,
        )
        if verified_reduction_projection and not projection.blockers:
            if (
                projection.snapshot.state is not RuntimeState.READY
                or projection.snapshot.trading_mode is not TradingMode.NORMAL
            ):
                raise BTCExecutionBlocked(
                    "btc_demo_dispatch_reduction_projection_not_ready"
                )
            projection = replace(
                projection,
                snapshot=replace(
                    projection.snapshot,
                    trading_mode=TradingMode.REDUCE_ONLY,
                    block_new_orders=True,
                    transition_reason=(
                        "btc_runtime_projection_verified_reduce_only"
                    ),
                ),
            )
        tolerated_blockers = (
            {
                "btc_exchange_cancel_only",
                "btc_exchange_exchange_status_not_ok:cancel_only",
            }
            if action in {
                RuntimeAction.CANCEL_ORDER,
                RuntimeAction.DEAD_MAN,
            }
            else set()
        )
        blocking_projection = [
            blocker
            for blocker in projection.blockers
            if blocker not in tolerated_blockers
        ]
        if blocking_projection:
            raise BTCExecutionBlocked(
                "btc_demo_dispatch_projection_blocked:"
                + ",".join(blocking_projection)
            )
        actual_notional = _demo_actual_notional(
            facts.exchange_snapshot,
            order_intent,
        )
        threshold = float(risk_decision.threshold or 0.0)
        if (
            risk_decision.order_intent_id != order_intent.order_intent_id
            or not risk_decision.approved
            or actual_notional <= 0
            or threshold <= 0
            or actual_notional > threshold
        ):
            raise BTCExecutionBlocked("btc_demo_dispatch_risk_evidence_invalid")
        authoritative = RuntimeAuthoritativeRiskResult.from_order_intent(
            order_intent,
            approved=True,
            actual_notional=actual_notional,
            venue="okx",
            liquidation_safe=(
                action in {
                    RuntimeAction.CANCEL_ORDER,
                    RuntimeAction.REDUCE_ONLY,
                    RuntimeAction.DEAD_MAN,
                }
                or _verified_attached_protection_policy(
                    facts.attached_protection,
                    order_intent,
                )
            ),
            exposure=abs(float(order_intent.quantity)),
        )
        evidence = self._producer.issue_from_authoritative(
            order_intent=order_intent,
            authoritative_result=authoritative,
            source_head=facts.source_head,
            account_identity=account_identity,
            session_id=facts.runtime_run_id,
            key_namespace=facts.credential_service,
            client_order_namespace=namespace,
            epoch=facts.epoch,
            # Runtime authorization remains on its existing short-lived wall
            # clock.  The injected clock above is only the sealed market/account
            # observation clock; it must not alter token or permission TTLs.
            issued_at=utc_now(),
            evidence_id="btc-demo-dispatch-" + _digest(
                {
                    "action": action.value,
                    "client_order_id": order_intent.client_order_id,
                    "source_head": facts.source_head,
                }
            )[:24],
        )
        lifecycle_store = BTCClientOrderLifecycleStore(
            lifecycle_directory,
            identity=identity,
        )
        boundary = BTCExecutionBoundary(
            evaluator=PermissionEvaluator(
                projection.snapshot,
                risk_verifier=self._verifier,
            ),
            lifecycle_store=lifecycle_store,
            identity=identity,
            broker_truth=broker_truth,
            ledger_freshness=ledger,
            endpoint_capability=capability,
            risk_evidence=evidence,
            current_head=facts.source_head,
            session_id=facts.runtime_run_id,
            epoch=facts.epoch,
            transport=_BTCExecutionCallbackTransport(callback),
        )
        return boundary.execute_action(
            action,
            order_intent=order_intent,
            risk_decision=risk_decision,
            risk_evidence=evidence,
        )


def _is_git_head(value: object) -> bool:
    text = str(value or "")
    return len(text) == 40 and all(character in "0123456789abcdef" for character in text)


def _demo_client_order_namespace(value: object) -> str:
    client_order_id = str(value or "")
    if not client_order_id.startswith("btcDP") or len(client_order_id) < 10:
        return ""
    return client_order_id[:13]


def _demo_actual_notional(
    snapshot: Mapping[str, Any],
    intent: OrderIntent,
) -> float:
    price = float(intent.limit_price or 0.0)
    if price <= 0:
        ticker = _read(snapshot, "ticker", default={})
        price = float(_read(ticker, "bid", "ask", default=0.0) or 0.0)
    instrument = _read(snapshot, "instrument", default={})
    contract_value = float(
        _read(instrument, "contract_value_btc", "ctVal", default=0.0) or 0.0
    )
    return abs(float(intent.quantity)) * price * contract_value


def _verified_attached_protection_policy(
    protection: Mapping[str, Any],
    intent: OrderIntent,
) -> bool:
    """Require the persisted, exact OCO policy before a new Demo order.

    This deliberately consumes the order plan's actual transport payload rather
    than a caller supplied `liquidation_safe` boolean.
    """

    return (
        str(protection.get("attachAlgoClOrdId") or "")
        == f"{intent.client_order_id}A"
        and str(protection.get("tpTriggerPx") or "") not in {"", "0"}
        and str(protection.get("slTriggerPx") or "") not in {"", "0"}
        and str(protection.get("tpTriggerPxType") or "") == "mark"
        and str(protection.get("slTriggerPxType") or "") == "mark"
        and str(protection.get("tpOrdPx") or "") == "-1"
        and str(protection.get("slOrdPx") or "") == "-1"
        and isinstance(protection.get("policy"), Mapping)
    )


def _identity_from(value: BTCExecutionIdentity | Mapping[str, Any] | None) -> BTCExecutionIdentity:
    if isinstance(value, BTCExecutionIdentity):
        return value
    if value is None:
        return BTCExecutionIdentity()
    data = dict(value)
    if "account_hash" in data and "account_identity" not in data:
        data["account_identity"] = data.pop("account_hash")
    if "state_dir" in data and "state_directory" not in data:
        data["state_directory"] = data.pop("state_dir")
    if "credential_namespace" in data and "key_namespace" not in data:
        data["key_namespace"] = data.pop("credential_namespace")
    if "clord_namespace" in data and "client_order_namespace" not in data:
        data["client_order_namespace"] = data.pop("clord_namespace")
    if "session" in data and "session_id" not in data:
        data["session_id"] = data.pop("session")
    if "connection_epoch" in data and "epoch" not in data:
        data["epoch"] = data.pop("connection_epoch")
    if "source_commit" in data and "source_head" not in data:
        data["source_head"] = data.pop("source_commit")
    allowed = {field for field in BTCExecutionIdentity.__dataclass_fields__}
    return BTCExecutionIdentity(**{key: item for key, item in data.items() if key in allowed})


def _broker_from(
    value: BTCBrokerTruth | Mapping[str, Any] | None,
    exchange_runtime: object | Mapping[str, Any] | None,
    *,
    now: datetime | None,
) -> BTCBrokerTruth:
    if isinstance(value, BTCBrokerTruth):
        return value
    if value is not None:
        return BTCBrokerTruth(
            fresh=_as_bool(_read(value, "fresh", "broker_truth_fresh", default=False)),
            valid=_as_bool(_read(value, "valid", "complete", default=False)),
            account_verified=_as_bool(_read(value, "account_verified", default=False)),
            authoritative_account_verified=_as_bool(
                _read(
                    value,
                    "authoritative_account_verified",
                    "account_verified_authoritative",
                    "authoritative_account_verification",
                    default=False,
                )
            ),
            account_verification_source=str(
                _read(value, "account_verification_source", "verification_source", default="")
            ),
            account_identity=str(
                _read(value, "account_identity", "account_hash", "account_id_hash", default="")
            ),
            venue=str(_read(value, "venue", "exchange", default="okx")),
            kill_switch_tripped=_as_bool(_read(value, "kill_switch_tripped", "kill_switch", default=False)),
            source_head=str(_read(value, "source_head", "source_commit", default="")),
            session_id=str(_read(value, "session_id", "session", default="")),
            epoch=(
                None
                if _read(value, "epoch", "connection_epoch", "session_epoch", default=None) is None
                else int(_read(value, "epoch", "connection_epoch", "session_epoch", default=0))
            ),
            observed_at_utc=_timestamp(_read(value, "observed_at_utc", "observed_at", default=None)),
            source=str(_read(value, "source", default="fixture")),
        )
    # A BTC exchange snapshot is broker truth only when all private and
    # reconciliation observations are present and fresh.  Missing observations
    # remain false; no caller-provided ``ready`` flag is consulted.
    status = _value_text(_read(exchange_runtime, "private_ws_status", default="unknown"), default="unknown")
    reconciliation = _read(exchange_runtime, "last_reconciliation_time_utc", "last_reconciliation_time", default=None)
    fresh = status == "connected" and reconciliation is not None
    observed = _timestamp(_read(exchange_runtime, "observed_at_utc", "observed_at", default=None)) or ensure_utc(now or utc_now())
    account_verified = _as_bool(_read(exchange_runtime, "account_verified", default=False))
    authoritative_account_verified = _as_bool(
        _read(
            exchange_runtime,
            "authoritative_account_verified",
            "account_verified_authoritative",
            default=False,
        )
    )
    return BTCBrokerTruth(
        fresh=fresh,
        valid=fresh,
        account_verified=account_verified,
        authoritative_account_verified=authoritative_account_verified,
        account_verification_source=str(_read(exchange_runtime, "account_verification_source", default="")),
        account_identity=str(_read(exchange_runtime, "account_identity", "account_hash", default="")),
        venue=str(_read(exchange_runtime, "venue", "exchange", default="okx")),
        kill_switch_tripped=_as_bool(_read(exchange_runtime, "kill_switch_tripped", "kill_switch", default=False)),
        source_head=str(_read(exchange_runtime, "source_head", "source_commit", default="")),
        session_id=str(_read(exchange_runtime, "session_id", "session", default="")),
        epoch=(
            None
            if _read(exchange_runtime, "epoch", "connection_epoch", "session_epoch", default=None) is None
            else int(_read(exchange_runtime, "epoch", "connection_epoch", "session_epoch", default=0))
        ),
        observed_at_utc=observed,
        source="btc_exchange_runtime_observation",
    )


def _ledger_from(value: BTCLedgerFreshness | Mapping[str, Any] | None) -> BTCLedgerFreshness:
    if isinstance(value, BTCLedgerFreshness):
        return value
    if value is None:
        return BTCLedgerFreshness()
    return BTCLedgerFreshness(
        fresh=_as_bool(_read(value, "fresh", "ledger_fresh", default=False)),
        reconciled=_as_bool(_read(value, "reconciled", "reconciliation_passed", default=False)),
        observed_at_utc=_timestamp(_read(value, "observed_at_utc", "observed_at", default=None)),
        source=str(_read(value, "source", default="fixture")),
    )


def _capability_from(
    value: BTCEndpointCapability | Mapping[str, Any] | None,
    identity: BTCExecutionIdentity,
) -> BTCEndpointCapability:
    if isinstance(value, BTCEndpointCapability):
        return value
    if value is None:
        return BTCEndpointCapability(mode=identity.mode, transport_enabled=identity.transport_enabled)
    data = dict(value)
    allowed = {field for field in BTCEndpointCapability.__dataclass_fields__}
    return BTCEndpointCapability(**{key: item for key, item in data.items() if key in allowed})


def _exchange_blockers(exchange_runtime: object | Mapping[str, Any] | None) -> list[str]:
    if exchange_runtime is None:
        return ["btc_exchange_runtime_missing"]
    validate = getattr(exchange_runtime, "validate", None)
    if callable(validate):
        try:
            return [str(value) for value in validate()]
        except Exception:
            return ["btc_exchange_runtime_validation_failed"]
    blockers: list[str] = []
    for name, expected in {
        "exchange_status": "ok",
        "public_ws_status": "connected",
        "private_ws_status": "connected",
        "rest_status": "ok",
    }.items():
        observed = _value_text(_read(exchange_runtime, name, default="unknown"), default="unknown")
        if observed != expected:
            blockers.append(f"btc_exchange_{name}_not_{expected}:{observed}")
    return blockers


def _timestamp(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return ensure_utc(value)
    try:
        return ensure_utc(datetime.fromisoformat(str(value).replace("Z", "+00:00")))
    except (TypeError, ValueError):
        return None


__all__ = [
    "BTCBrokerTruth",
    "BTCClientOrderLifecycleRecord",
    "BTCClientOrderLifecycleStore",
    "BTCEndpointCapability",
    "BTCExecutionBlocked",
    "BTCExecutionBoundary",
    "BTCExecutionCapabilityAdapter",
    "BTCExecutionDispatchFacts",
    "BTCDemoClientCapabilityAdapter",
    "BTCDemoExecutionDispatcher",
    "BTCExecutionIdentity",
    "BTCExecutionMode",
    "BTCExecutionResult",
    "BTCDispatchAuthorization",
    "BTCDispatchAuthorizer",
    "BTCLedgerFreshness",
    "BTCOrderLifecycleStatus",
    "BTCPermissionEvaluator",
    "BTCProjectionResult",
    "BTC_RUNTIME_PROJECTION_VERSION",
    "build_btc_runtime_projection",
    "project_btc_runtime_snapshot",
]
