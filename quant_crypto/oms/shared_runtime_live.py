"""Offline, fail-closed composition for the BTC/OKX shared-runtime canary.

This module is intentionally a thin composition layer.  It does not create an
HTTP client, read credentials, register a transport, or make a network call.
The only dispatch implementation it accepts is an explicitly injected fake or
the repository's already-composed recording transport.  The live slot is
``None`` by default and therefore produces ``NO_TRANSPORT``.

The composition order is deliberately visible in :meth:`BTCOKXSharedRuntimeLiveCanary.execute`:
candidate policy -> provider-authority preflight -> canonical BTC projection
-> paired risk producer/verifier and ``PermissionEvaluator`` -> durable clOrdId
lifecycle -> dead-man/OCO construction -> one final boundary decision -> an
injected provider.  An uncertain write is reconciled by clOrdId only; the
orchestrator has no retry path for a POST.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Mapping, Protocol, Sequence

from quant_crypto.oms.okx_live_preflight import (
    OKX_DATA_READONLY_PERMISSION,
    OKX_LIVE_API_BASE,
    OKXLivePreflightPolicy,
    OKXLivePreflightReceipt,
    OKXLivePreflightRequest,
    OKXOfflineFakeReadOnlyPreflightProvider,
    OKXLiveReadOnlyPreflightProvider,
)
from quant_crypto.oms.okx_mode_transport import (
    OKXModeIsolationConfig,
    OKXLiveTransport,
    OKXLiveTransportOptIn,
    OKXNoTransport,
    OKXTransportCapabilitySnapshot,
    OKXTransportMode,
    OKXTransportStatus,
    build_okx_client_order_id,
)
from quant_crypto.oms.runtime_store import BTCRuntimeStore
from quant_crypto.runtime.control_plane import (
    BTCBrokerTruth,
    BTCClientOrderLifecycleRecord,
    BTCClientOrderLifecycleStore,
    BTCEndpointCapability,
    BTCExecutionBoundary,
    BTCExecutionIdentity,
    BTCExecutionMode,
    BTCProjectionResult,
    BTCLedgerFreshness,
    BTCOrderLifecycleStatus,
    build_btc_runtime_projection,
)
from quant_crypto.trading_contracts import OrderIntent, RiskDecision
from quant_shared.runtime.models import RuntimeSnapshot
from quant_shared.runtime.permissions import (
    PermissionDecision,
    PermissionEvaluator,
    RuntimeAction,
    RuntimeAuthoritativeRiskResult,
    RuntimeRiskEvidence,
    RuntimeRiskEvidenceAuthority,
    RuntimeRiskEvidenceProducer,
    RuntimeRiskEvidenceVerifier,
)


SCHEMA_VERSION = "btc_okx_shared_runtime_live_canary_composition_v1"
_UTC = timezone.utc


class SharedRuntimeLiveBlocked(RuntimeError):
    """Raised only by helpers that are explicitly requested to raise.

    The public canary entry point returns a structured blocked result instead
    of raising.  This exception is kept for adapter/callback failures where a
    caller needs to preserve the original cause without treating it as a
    successful dispatch.
    """

    def __init__(self, *blockers: str) -> None:
        self.blockers = tuple(dict.fromkeys(str(item) for item in blockers if str(item)))
        super().__init__(";".join(self.blockers) or "shared_runtime_live_blocked")


def _now(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(_UTC)
    if value.tzinfo is None:
        raise ValueError("timestamp_must_be_timezone_aware")
    return value.astimezone(_UTC)


def _text(value: Any) -> str:
    return str(getattr(value, "value", value) or "").strip().lower()


def _finite(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _dedupe(values: Sequence[Any]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(str(value) for value in values if str(value)))


def _request_digest(action: str, intent: OrderIntent, risk_decision: RiskDecision, evidence: RuntimeRiskEvidence) -> str:
    payload = {
        "action": action,
        "intent_id": intent.order_intent_id,
        "client_order_id": intent.client_order_id,
        "symbol": intent.symbol,
        "side": _text(intent.side),
        "quantity": intent.quantity,
        "risk_check_id": risk_decision.risk_check_id,
        "risk_version": risk_decision.risk_version,
        "evidence_id": evidence.evidence_id,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")).hexdigest()


def _stable_outbound_digest(
    *,
    method: str,
    path: str,
    body: Mapping[str, Any] | bytes | bytearray | None,
    client_order_id: str | None,
    client_order_namespace: str,
    state_root: str,
    account_identity: str,
    key_namespace: str,
) -> str:
    """Hash the exact deterministic projection sent to the recording transport."""

    if body is None:
        body_bytes = b""
    elif isinstance(body, (bytes, bytearray)):
        body_bytes = bytes(body)
    else:
        body_bytes = json.dumps(
            dict(body),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    projection = {
        "method": str(method).upper(),
        "path": str(path),
        "body_sha256": hashlib.sha256(body_bytes).hexdigest(),
        "client_order_id": str(client_order_id or ""),
        "client_order_namespace": str(client_order_namespace),
        "state_root": str(Path(state_root).resolve()),
        "account_identity": str(account_identity),
        "key_namespace": str(key_namespace),
    }
    return hashlib.sha256(
        json.dumps(projection, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True)
class SharedRuntimeLiveCandidate:
    """Untrusted candidate input.

    Candidate fields are checked for an early, deterministic rejection only.
    They never replace broker truth, the provider receipt, risk evidence, the
    canonical snapshot, or the final dispatch capability.
    """

    order_intent: OrderIntent
    risk_decision: RiskDecision
    current_head: str
    session_id: str
    epoch: int
    account_hash: str
    credential_namespace: str
    state_root: str
    client_order_namespace: str
    policy: OKXLivePreflightPolicy = field(default_factory=OKXLivePreflightPolicy)
    mode: str = "live"
    api_base: str = OKX_LIVE_API_BASE
    permission_set: tuple[str, ...] = (OKX_DATA_READONLY_PERMISSION,)
    expected_ip_allowlist: tuple[str, ...] = ()
    observed_egress: tuple[str, ...] = ()
    transfer_allowed: bool = False
    withdraw_allowed: bool = False
    # These are advisory candidate claims.  A claim above the hard limit is a
    # blocker; a claim below it is never used as permission evidence.
    candidate_notional_usdt: float | None = None
    candidate_position_count: int | None = None
    candidate_active_order_count: int | None = None
    candidate_daily_new_orders: int | None = None
    candidate_daily_loss_usdt: float | None = None

    def blockers(self) -> tuple[str, ...]:
        blockers: list[str] = []
        if _text(self.mode) != "live":
            blockers.append("candidate_mode_must_be_live")
        if str(self.api_base).strip() != OKX_LIVE_API_BASE:
            blockers.append("candidate_live_api_base_mismatch")
        blockers.extend(self.policy.blockers())
        if self.transfer_allowed is not False:
            blockers.append("candidate_transfer_must_be_false")
        if self.withdraw_allowed is not False:
            blockers.append("candidate_withdraw_must_be_false")
        if self.order_intent.symbol.upper() != self.policy.instrument_id:
            blockers.append("candidate_instrument_mismatch")
        if _finite(self.order_intent.quantity) is None or float(self.order_intent.quantity) <= 0:
            blockers.append("candidate_quantity_invalid")
        if self.risk_decision.order_intent_id != self.order_intent.order_intent_id:
            blockers.append("candidate_risk_intent_mismatch")
        for name, value, limit in (
            ("candidate_notional_usdt", self.candidate_notional_usdt, 10.0),
            ("candidate_position_count", self.candidate_position_count, 1),
            ("candidate_active_order_count", self.candidate_active_order_count, 1),
            ("candidate_daily_new_orders", self.candidate_daily_new_orders, 2),
            ("candidate_daily_loss_usdt", self.candidate_daily_loss_usdt, 1.0),
        ):
            if value is None:
                continue
            parsed = _finite(value)
            if parsed is None or parsed > limit:
                blockers.append(f"{name}_exceeds_hard_limit")
            if name in {"candidate_position_count", "candidate_active_order_count", "candidate_daily_new_orders"} and parsed is not None and parsed < 0:
                blockers.append(f"{name}_invalid")
        return _dedupe(blockers)

    def to_preflight_request(self) -> OKXLivePreflightRequest:
        return OKXLivePreflightRequest(
            current_head=self.current_head,
            session_id=self.session_id,
            epoch=self.epoch,
            mode=self.mode,
            api_base=self.api_base,
            credential_namespace=self.credential_namespace,
            account_hash=self.account_hash,
            state_root=self.state_root,
            client_order_namespace=self.client_order_namespace,
            policy=self.policy,
            permission_set=self.permission_set,
            expected_ip_allowlist=self.expected_ip_allowlist,
            observed_egress=self.observed_egress,
            withdraw_allowed=self.withdraw_allowed,
            transfer_allowed=self.transfer_allowed,
            nonce=f"{self.session_id}-{self.epoch}-{self.order_intent.order_intent_id}",
            observed_at_utc=self.order_intent.timestamp_utc,
        )


@dataclass(frozen=True)
class SharedRuntimeLimitFacts:
    """Independent runtime limits, not values read from order metadata."""

    instrument_id: str = ""
    margin_mode: str = ""
    leverage: float | None = None
    position_count: int | None = None
    active_order_count: int | None = None
    daily_new_orders: int | None = None
    daily_loss_usdt: float | None = None
    authoritative: bool = False

    def blockers(self, policy: OKXLivePreflightPolicy) -> tuple[str, ...]:
        if self.authoritative is not True:
            return ("authoritative_runtime_limits_missing",)
        blockers: list[str] = []
        if self.instrument_id != policy.instrument_id:
            blockers.append("runtime_limit_instrument_mismatch")
        if self.margin_mode != policy.margin_mode:
            blockers.append("runtime_limit_margin_mode_mismatch")
        if _finite(self.leverage) != policy.leverage:
            blockers.append("runtime_limit_leverage_mismatch")
        for name, value, limit in (
            ("position_count", self.position_count, policy.max_positions),
            ("active_order_count", self.active_order_count, policy.max_active_orders),
            ("daily_new_orders", self.daily_new_orders, policy.max_daily_new_orders),
            ("daily_loss_usdt", self.daily_loss_usdt, policy.max_daily_loss_usdt),
        ):
            parsed = _finite(value)
            if parsed is None or parsed > limit:
                blockers.append(f"runtime_{name}_exceeds_hard_limit")
            if parsed is not None and parsed < 0:
                blockers.append(f"runtime_{name}_invalid")
        return _dedupe(blockers)


@dataclass(frozen=True)
class DeadManArmedEvidence:
    """Short-lived, identity-bound evidence that a dead-man control is armed."""

    armed: bool
    evidence_id: str
    expires_at: datetime
    client_order_namespace: str
    session_id: str
    epoch: int
    source_head: str

    def valid_for(self, *, candidate: SharedRuntimeLiveCandidate, now: datetime) -> bool:
        return bool(
            self.armed
            and self.evidence_id.strip()
            and _now(self.expires_at) > now
            and self.client_order_namespace == candidate.client_order_namespace
            and self.session_id == candidate.session_id
            and self.epoch == candidate.epoch
            and self.source_head == candidate.current_head
        )


@dataclass(frozen=True)
class ProtectionPlan:
    """Constructed OCO/protection payload plus an independent acknowledgement."""

    params: Mapping[str, Any]
    acknowledged: bool
    client_order_namespace: str
    session_id: str
    epoch: int
    source_head: str

    def valid_for(self, *, candidate: SharedRuntimeLiveCandidate) -> bool:
        return bool(
            self.acknowledged
            and isinstance(self.params, Mapping)
            and bool(dict(self.params))
            and self.client_order_namespace == candidate.client_order_namespace
            and self.session_id == candidate.session_id
            and self.epoch == candidate.epoch
            and self.source_head == candidate.current_head
        )


@dataclass(frozen=True)
class LedgerUOWFacts:
    """Facts needed before and after one idempotent ledger commit."""

    idempotency_key: str
    timestamp_utc: datetime
    run_id: str
    order: Mapping[str, Any]
    fills: tuple[Mapping[str, Any], ...]
    position: Mapping[str, Any]
    cash: Mapping[str, Any]
    funding: Mapping[str, Any]
    risk_context: Mapping[str, Any]
    state_after: Mapping[str, Any]
    safety: Mapping[str, Any]
    order_reconciled: bool
    fill_reconciled: bool
    position_reconciled: bool
    operator_acknowledged: bool

    def blockers(self) -> tuple[str, ...]:
        blockers: list[str] = []
        if not self.idempotency_key.strip() or not self.run_id.strip():
            blockers.append("ledger_uow_identity_missing")
        if _now(self.timestamp_utc) is None:  # pragma: no cover - _now raises for naive values
            blockers.append("ledger_uow_timestamp_invalid")
        for name, value in (
            ("order", self.order),
            ("position", self.position),
            ("cash", self.cash),
            ("funding", self.funding),
        ):
            if not isinstance(value, Mapping) or not dict(value):
                blockers.append(f"ledger_{name}_missing")
        required = ("mark_price", "index_price", "liquidation_buffer_bps", "venue_rules")
        for field_name in required:
            if self.risk_context.get(field_name) in (None, "", {}):
                blockers.append(f"ledger_risk_context_{field_name}_missing")
        if not (self.order_reconciled and self.fill_reconciled and self.position_reconciled):
            blockers.append("ledger_order_fill_position_reconciliation_required")
        if self.operator_acknowledged is not True:
            blockers.append("ledger_operator_ack_required")
        return _dedupe(blockers)


_EVIDENCE_ISSUER = object()


class _OpaqueEvidenceBundle:
    """Composition-root evidence capsule.

    Ordinary mappings, dataclasses, and booleans are never consumed by the
    canary.  The fixture-only constructor below is intentionally private and
    records an explicit simulation boundary; it cannot unlock a real live
    provider or change any safety flag.
    """

    __slots__ = (
        "identity",
        "exchange_runtime",
        "broker_truth",
        "ledger_freshness",
        "endpoint_capability",
        "limit_facts",
        "ledger_facts",
        "dead_man_evidence",
        "protection_plan",
        "operator_acknowledged",
        "recovery_requires_ack",
        "risk_result",
        "_issuer",
    )

    def __init__(self, *, _issuer: object | None = None, **values: Any) -> None:
        if _issuer is not _EVIDENCE_ISSUER:
            raise SharedRuntimeLiveBlocked("runtime_evidence_capsule_private")
        self._issuer = _issuer
        for name in self.__slots__:
            if name == "_issuer":
                continue
            setattr(self, name, values.get(name))


def _fixture_evidence_bundle(**values: Any) -> _OpaqueEvidenceBundle:
    """Create an explicitly offline simulation capsule for contract tests."""

    return _OpaqueEvidenceBundle(_issuer=_EVIDENCE_ISSUER, **values)


class LedgerReconciler(Protocol):
    def __call__(self, *, facts: LedgerUOWFacts, receipt: object | None, lifecycle: BTCClientOrderLifecycleRecord) -> bool: ...


@dataclass
class SharedRuntimeLiveDependencies:
    """Composition-root dependencies; every capability is opt-in."""

    # These legacy-shaped fields are retained only to produce structured
    # rejection reasons.  The canary never consumes them as authority.
    exchange_runtime: object | Mapping[str, Any] | None = None
    broker_truth: BTCBrokerTruth | Mapping[str, Any] | None = None
    ledger_freshness: BTCLedgerFreshness | Mapping[str, Any] | None = None
    endpoint_capability: BTCEndpointCapability | Mapping[str, Any] | None = None
    limit_facts: SharedRuntimeLimitFacts | None = None
    evidence_bundle: object | None = None
    preflight_provider: OKXLiveReadOnlyPreflightProvider | None = None
    preflight_receipt: OKXLivePreflightReceipt | None = None
    risk_authority: RuntimeRiskEvidenceAuthority | None = None
    risk_producer: RuntimeRiskEvidenceProducer | None = None
    risk_verifier: RuntimeRiskEvidenceVerifier | None = None
    authoritative_risk_result: RuntimeAuthoritativeRiskResult | None = None
    risk_result_supplier: Callable[[OrderIntent], RuntimeAuthoritativeRiskResult] | None = None
    lifecycle_store: BTCClientOrderLifecycleStore | None = None
    runtime_store: BTCRuntimeStore | Any | None = None
    ledger_facts: LedgerUOWFacts | None = None
    reconcile: LedgerReconciler | None = None
    transport: object | None = None
    dispatch_capability: object | None = None
    query_by_client_order_id: Callable[[str], Mapping[str, Any] | str | None] | None = None
    dead_man_evidence: DeadManArmedEvidence | None = None
    protection_plan: ProtectionPlan | None = None
    okx_config: OKXModeIsolationConfig | None = None
    current_snapshot_supplier: Callable[[], RuntimeSnapshot | Mapping[str, Any]] | None = None
    operator_acknowledged: bool | None = None
    recovery_requires_ack: bool | None = None
    now: datetime | None = None


@dataclass(frozen=True)
class SharedRuntimeLiveResult:
    allowed: bool
    action: str
    blockers: tuple[str, ...] = ()
    cl_ord_id: str = ""
    snapshot: RuntimeSnapshot | None = None
    projection: BTCProjectionResult | None = None
    decision: PermissionDecision | None = None
    lifecycle: BTCClientOrderLifecycleRecord | None = None
    receipt: object | None = None
    ambiguous: bool = False
    query_called: bool = False
    query_result: object | None = None
    ledger_committed: bool = False
    reconciled: bool = False
    dead_man_payload: Mapping[str, Any] | None = None
    protection_payload: Mapping[str, Any] | None = None

    @property
    def transport_called(self) -> bool:
        return bool(self.allowed or self.ambiguous)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "allowed": self.allowed,
            "action": self.action,
            "blockers": list(self.blockers),
            "clOrdId": self.cl_ord_id,
            "decision": None if self.decision is None else self.decision.to_dict(),
            "lifecycle": None if self.lifecycle is None else self.lifecycle.to_dict(),
            "ambiguous": self.ambiguous,
            "query_called": self.query_called,
            "ledger_committed": self.ledger_committed,
            "reconciled": self.reconciled,
            "dead_man_payload": None if self.dead_man_payload is None else dict(self.dead_man_payload),
            "protection_payload": None if self.protection_payload is None else dict(self.protection_payload),
            "safety": {
                "network_accessed": False,
                "private_endpoint_allowed": False,
                "order_endpoint_allowed": False,
                "live_ready": False,
                "live_allowed": False,
                "auto_start": False,
                "auto_scale": False,
                "transfer_allowed": False,
                "withdraw_allowed": False,
            },
        }


class _CanaryProviderAuthorizer:
    """One-shot authorizer used only by the injected recording transport."""

    __slots__ = ("_config", "_provider", "_permit", "_canonical", "_next_nonce", "_last_blocker")

    def __init__(self, config: OKXModeIsolationConfig) -> None:
        self._config = config
        self._provider: OKXLiveTransport | None = None
        self._permit: dict[str, Any] | None = None
        self._canonical: Mapping[str, Any] | None = None
        self._next_nonce = 0
        self._last_blocker = ""

    @property
    def last_blocker(self) -> str:
        return self._last_blocker

    def _deny(self, blocker: str) -> bool:
        self._last_blocker = str(blocker)
        return False

    def bind_provider(self, provider: OKXLiveTransport) -> None:
        if self._provider is not None:
            raise SharedRuntimeLiveBlocked("provider_authorizer_already_bound")
        self._provider = provider

    def arm(
        self,
        *,
        provider: OKXLiveTransport,
        action: str,
        client_order_id: str,
        request_digest: str,
        method: str,
        path: str,
        body: Mapping[str, Any] | bytes | bytearray | None,
        source_head: str,
        session_id: str,
        epoch: int,
        account_identity: str,
        key_namespace: str,
        state_root: str,
        client_order_namespace: str,
    ) -> None:
        if provider is not self._provider:
            raise SharedRuntimeLiveBlocked("provider_authorizer_identity_mismatch")
        if self._permit is not None or self._canonical is not None:
            raise SharedRuntimeLiveBlocked("provider_authorizer_permit_already_armed")
        if (
            account_identity != self._config.credential_reference.account_hash
            or key_namespace != self._config.credential_reference.service_namespace
            or str(Path(state_root).resolve()) != str(self._config.state_root)
            or client_order_namespace != self._config.client_order_namespace
        ):
            raise SharedRuntimeLiveBlocked("provider_authorizer_namespace_mismatch")
        canonical_digest = _stable_outbound_digest(
            method=method,
            path=path,
            body=body,
            client_order_id=client_order_id,
            client_order_namespace=client_order_namespace,
            state_root=state_root,
            account_identity=account_identity,
            key_namespace=key_namespace,
        )
        if str(request_digest) != canonical_digest:
            raise SharedRuntimeLiveBlocked("provider_authorizer_request_digest_mismatch")
        self._next_nonce += 1
        nonce = f"permit-{id(self):x}-{self._next_nonce}"
        canonical = {
            "provider": provider,
            "action": str(action),
            "client_order_id": str(client_order_id),
            "request_digest": canonical_digest,
            "source_head": str(source_head),
            "session_id": str(session_id),
            "epoch": int(epoch),
            "account_identity": str(account_identity),
            "key_namespace": str(key_namespace),
            "state_root": str(Path(state_root).resolve()),
            "client_order_namespace": str(client_order_namespace),
            "method": str(method).upper(),
            "path": str(path),
            "body": body,
            "nonce": nonce,
        }
        self._canonical = MappingProxyType(canonical)
        self._permit = {
            **dict(canonical),
        }

    @staticmethod
    def _request_action(request: object) -> str:
        method = str(getattr(request, "method", "")).upper()
        path = str(getattr(request, "path", "")).lower()
        if method == "GET":
            return "query_broker"
        if path.endswith("/cancel-order"):
            return "cancel_order"
        if path.endswith("/amend-order"):
            return "replace_order"
        if path.endswith("/order-algo"):
            return "attach_protection"
        if path.endswith("/cancel-all-after"):
            return "dead_man"
        try:
            import json as _json

            body = _json.loads(getattr(request, "body", b"{}") or b"{}")
            if isinstance(body, Mapping) and body.get("reduceOnly") is True:
                return "reduce_only"
        except Exception:
            pass
        return "submit_new_order"

    def authorize_dispatch(self, *, request: object) -> bool:
        permit = self._permit
        canonical = self._canonical
        provider = self._provider
        self._permit = None
        self._canonical = None
        self._last_blocker = ""
        if permit is None or canonical is None or provider is None:
            return self._deny("provider_authorizer_permit_missing_or_replayed")
        for field in (
            "provider",
            "action",
            "client_order_id",
            "request_digest",
            "source_head",
            "session_id",
            "epoch",
            "account_identity",
            "key_namespace",
            "state_root",
            "client_order_namespace",
            "method",
            "path",
            "body",
            "nonce",
        ):
            if permit.get(field) != canonical.get(field):
                return self._deny(f"provider_authorizer_permit_{field}_mismatch")
        if canonical["provider"] is not provider:
            return self._deny("provider_authorizer_identity_mismatch")
        credential = getattr(request, "credential_reference", None)
        if credential is not provider.config.credential_reference:
            return self._deny("provider_authorizer_credential_identity_mismatch")
        actual_digest = _stable_outbound_digest(
            method=str(getattr(request, "method", "")),
            path=str(getattr(request, "path", "")),
            body=getattr(request, "body", None),
            client_order_id=getattr(request, "client_order_id", None),
            client_order_namespace=str(getattr(request, "client_order_namespace", "")),
            state_root=str(getattr(request, "state_root", "")),
            account_identity=str(getattr(credential, "account_hash", "")),
            key_namespace=str(getattr(credential, "service_namespace", "")),
        )
        checks = (
            self._request_action(request) == canonical["action"],
            str(getattr(request, "client_order_id", "")) == canonical["client_order_id"],
            str(getattr(request, "client_order_namespace", "")) == canonical["client_order_namespace"],
            str(getattr(request, "state_root", "")) == canonical["state_root"],
            str(getattr(credential, "account_hash", "")) == canonical["account_identity"],
            str(getattr(credential, "service_namespace", "")) == canonical["key_namespace"],
            str(getattr(request, "method", "")).upper() == canonical["method"],
            str(getattr(request, "path", "")) == canonical["path"],
            actual_digest == canonical["request_digest"],
        )
        for field in ("request_digest", "source_head", "session_id", "epoch"):
            observed = getattr(request, field, None)
            if observed is not None and observed != canonical[field]:
                return self._deny(f"provider_authorizer_request_{field}_mismatch")
        if not all(checks):
            return self._deny("provider_authorizer_outbound_request_mismatch")
        return True


def _fixture_okx_transport(
    *,
    config: OKXModeIsolationConfig,
    responder: object,
) -> OKXLiveTransport:
    """Build the recording-only canonical provider used by contract tests."""

    authorizer = _CanaryProviderAuthorizer(config)
    provider = OKXLiveTransport(
        config=config,
        opt_in=OKXLiveTransportOptIn(
            ticket="BTC-OKX-COMPOSITION-FIXTURE",
            operator="offline-contract-test",
            reason="injected fake only",
            confirmed=True,
            read_only=True,
        ),
        canonical_authorizer=authorizer,
        responder=responder,
        capability_provider=OKXTransportCapabilitySnapshot(
            transport_enabled=True,
            private_endpoint_allowed=True,
            order_endpoint_allowed=True,
        ),
    )
    authorizer.bind_provider(provider)
    return provider


class _ProviderAdapter:
    """Map one boundary action to an injected fake/recording provider only."""

    _PATHS = {
        "submit_new_order": "/api/v5/trade/order",
        "cancel_order": "/api/v5/trade/cancel-order",
        "replace_order": "/api/v5/trade/amend-order",
        "reduce_only": "/api/v5/trade/order",
        "attach_protection": "/api/v5/trade/order-algo",
        "dead_man": "/api/v5/trade/cancel-all-after",
    }
    _METHODS = {
        "submit_new_order": "submit",
        "cancel_order": "cancel",
        "replace_order": "replace",
        "reduce_only": "reduce_only",
        "attach_protection": "attach_protection",
        "dead_man": "dead_man",
    }

    def __init__(self, provider: object, *, payload: Mapping[str, Any], action: str) -> None:
        self.provider = provider
        self.payload = dict(payload)
        self.action = action
        self.calls = 0

    def _call(self, order_intent: OrderIntent) -> object:
        self.calls += 1
        method = getattr(self.provider, self._METHODS[self.action], None)
        if callable(method):
            return method(order_intent)
        dispatch = getattr(self.provider, "dispatch", None)
        if callable(dispatch):
            return dispatch(action=self.action, order_intent=order_intent, payload=dict(self.payload))
        request = getattr(self.provider, "request", None)
        if callable(request):
            return request(
                method="POST",
                path=self._PATHS[self.action],
                body=dict(self.payload),
                client_order_id=order_intent.client_order_id,
            )
        send = getattr(self.provider, "send", None)
        if callable(send):
            return send(action=self.action, order_intent=order_intent, payload=dict(self.payload))
        raise SharedRuntimeLiveBlocked("provider_dispatch_capability_missing")

    submit = _call
    cancel = _call
    replace = _call
    reduce_only = _call
    attach_protection = _call
    dead_man = _call


def _provider_blockers(provider: object | None, *, dispatch_capability: object | None) -> tuple[str, ...]:
    blockers: list[str] = []
    if provider is None:
        return ("okx_live_no_transport", "okx_live_provider_not_registered")
    if isinstance(provider, OKXNoTransport) or _text(getattr(provider, "status", "")) == _text(OKXTransportStatus.NO_TRANSPORT):
        blockers.append("okx_live_no_transport")
    if isinstance(dispatch_capability, bool):
        blockers.append("dispatch_capability_bool_forbidden")
    elif dispatch_capability is not None:
        blockers.append("dispatch_capability_untrusted")
    if type(provider) is not OKXLiveTransport:
        blockers.append("okx_live_provider_must_be_canonical_transport")
    authorizer = getattr(provider, "canonical_authorizer", None)
    if type(authorizer) is not _CanaryProviderAuthorizer:
        blockers.append("okx_live_canonical_authorizer_mismatch")
    capability = getattr(provider, "capability_snapshot", None)
    if type(capability) is not OKXTransportCapabilitySnapshot:
        blockers.append("okx_live_capability_snapshot_untrusted")
    else:
        try:
            if capability.transport_enabled is not True:
                blockers.append("okx_live_transport_capability_disabled")
            if capability.private_endpoint_allowed is not True:
                blockers.append("okx_live_private_endpoint_capability_missing")
            if capability.order_endpoint_allowed is not True:
                blockers.append("okx_live_order_endpoint_capability_missing")
        except AttributeError:
            blockers.append("okx_live_capability_snapshot_invalid")
    safety = getattr(provider, "safety", {})
    if isinstance(safety, Mapping):
        for key in ("network_accessed", "private_endpoint_accessed", "order_endpoint_accessed"):
            if safety.get(key) is True:
                blockers.append(f"provider_{key}_forbidden")
    else:
        blockers.append("provider_safety_evidence_missing")
    return _dedupe(blockers)


class BTCOKXSharedRuntimeLiveCanary:
    """One-shot, default-off canary composition."""

    def __init__(self, *, candidate: SharedRuntimeLiveCandidate, identity: BTCExecutionIdentity, dependencies: SharedRuntimeLiveDependencies | None = None) -> None:
        self.candidate = candidate
        self.identity = identity
        self.dependencies = dependencies or SharedRuntimeLiveDependencies()

    def _blocked(self, action: str, blockers: Sequence[Any], **values: Any) -> SharedRuntimeLiveResult:
        return SharedRuntimeLiveResult(
            allowed=False,
            action=action,
            blockers=_dedupe(blockers),
            **values,
        )

    def _evidence_bundle(self) -> tuple[_OpaqueEvidenceBundle | None, tuple[str, ...]]:
        d = self.dependencies
        bundle = d.evidence_bundle
        blockers: list[str] = []
        if type(bundle) is not _OpaqueEvidenceBundle:
            return None, ("canonical_runtime_evidence_bundle_missing",)
        # No caller-provided signer, supplier, verifier, permit, or plain
        # evidence is accepted.  Fixture happy paths use only the private
        # capsule above; default callers fail before any provider call.
        for name in (
            "risk_authority",
            "risk_producer",
            "risk_verifier",
            "authoritative_risk_result",
            "risk_result_supplier",
            "exchange_runtime",
            "broker_truth",
            "ledger_freshness",
            "endpoint_capability",
            "limit_facts",
            "ledger_facts",
            "dead_man_evidence",
            "protection_plan",
            "current_snapshot_supplier",
        ):
            if getattr(d, name, None) is not None:
                suffix = "_untrusted" if name.endswith("_evidence") else "_evidence_untrusted"
                blockers.append(f"caller_{name}{suffix}")
        if d.operator_acknowledged is not None:
            blockers.append("operator_ack_plain_untrusted")
        if d.recovery_requires_ack is not None:
            blockers.append("recovery_ack_plain_untrusted")
        if d.reconcile is not None:
            blockers.append("caller_reconcile_untrusted")
        if isinstance(d.dispatch_capability, bool):
            blockers.append("dispatch_capability_bool_forbidden")
        elif d.dispatch_capability is not None:
            blockers.append("dispatch_capability_untrusted")
        if type(d.runtime_store) is not BTCRuntimeStore:
            blockers.append("runtime_store_canonical_type_required")
        if d.lifecycle_store is not None and type(d.lifecycle_store) is not BTCClientOrderLifecycleStore:
            blockers.append("lifecycle_store_canonical_type_required")
        if type(bundle.identity) is not BTCExecutionIdentity or bundle.identity != self.identity:
            blockers.append("runtime_identity_opaque_evidence_mismatch")
        for name in (
            "broker_truth",
            "ledger_freshness",
            "endpoint_capability",
            "limit_facts",
            "ledger_facts",
            "dead_man_evidence",
            "protection_plan",
        ):
            if getattr(bundle, name, None) is None:
                blockers.append(f"canonical_{name}_evidence_missing")
        if type(bundle.limit_facts) is not SharedRuntimeLimitFacts:
            blockers.append("canonical_limit_facts_evidence_invalid")
        if type(bundle.ledger_facts) is not LedgerUOWFacts:
            blockers.append("canonical_ledger_uow_evidence_invalid")
        if type(bundle.dead_man_evidence) is not DeadManArmedEvidence:
            blockers.append("canonical_dead_man_evidence_invalid")
        if type(bundle.protection_plan) is not ProtectionPlan:
            blockers.append("canonical_oco_evidence_invalid")
        if type(bundle.risk_result) is not RuntimeAuthoritativeRiskResult:
            blockers.append("canonical_risk_result_evidence_invalid")
        if bundle.operator_acknowledged is not True:
            blockers.append("canonical_operator_ack_missing")
        return bundle, _dedupe(blockers)

    def _identity_blockers(self) -> tuple[str, ...]:
        c = self.candidate
        i = self.identity
        blockers: list[str] = list(i.blockers(expected_mode=BTCExecutionMode.LIVE))
        if _text(i.mode) != "live":
            blockers.append("execution_mode_must_be_live")
        pairs = (
            (i.account_identity, c.account_hash, "account_identity"),
            (i.key_namespace, c.credential_namespace, "key_namespace"),
            (i.client_order_namespace, c.client_order_namespace, "client_order_namespace"),
            (i.session_id, c.session_id, "session_id"),
            (str(i.epoch), str(c.epoch), "epoch"),
            (i.source_head, c.current_head, "source_head"),
        )
        for observed, expected, name in pairs:
            if str(observed).strip() != str(expected).strip():
                blockers.append(f"execution_{name}_mismatch")
        if Path(i.state_directory).resolve() != Path(c.state_root).resolve():
            blockers.append("execution_state_directory_mismatch")
        return _dedupe(blockers)

    def _config(self) -> tuple[OKXModeIsolationConfig | None, tuple[str, ...]]:
        c = self.candidate
        supplied = self.dependencies.okx_config
        try:
            config = supplied or OKXModeIsolationConfig.live(
                account_hash=c.account_hash,
                state_root=c.state_root,
                client_order_namespace=c.client_order_namespace,
                credential_identity=c.credential_namespace,
                private_endpoint_allowed=False,
                order_endpoint_allowed=False,
            )
        except Exception as exc:
            return None, (f"okx_mode_isolation_invalid:{type(exc).__name__}",)
        blockers: list[str] = []
        if config.mode is not OKXTransportMode.LIVE:
            blockers.append("okx_config_mode_must_be_live")
        if config.api_base != c.api_base:
            blockers.append("okx_config_api_base_mismatch")
        if str(config.state_root) != str(Path(c.state_root).resolve()):
            blockers.append("okx_config_state_root_mismatch")
        if config.credential_reference.account_hash != c.account_hash:
            blockers.append("okx_config_account_identity_mismatch")
        if config.credential_reference.service_namespace != c.credential_namespace:
            blockers.append("okx_config_credential_namespace_mismatch")
        if config.client_order_namespace != c.client_order_namespace:
            blockers.append("okx_config_client_order_namespace_mismatch")
        if config.network_enabled is True:
            blockers.append("okx_network_must_be_injected_fake_only")
        if not (config.private_endpoint_allowed and config.order_endpoint_allowed):
            blockers.append("okx_config_dispatch_capability_missing")
        return (config if not blockers else None), _dedupe(blockers)

    def _receipt(self, request: OKXLivePreflightRequest) -> tuple[OKXLivePreflightReceipt | None, tuple[str, ...]]:
        provider = self.dependencies.preflight_provider
        if provider is None:
            return None, ("okx_live_preflight_provider_missing",)
        if type(provider) is not OKXOfflineFakeReadOnlyPreflightProvider:
            return None, ("okx_live_preflight_provider_untrusted",)
        safety = getattr(provider, "safety", {})
        if isinstance(safety, Mapping) and any(bool(safety.get(key)) for key in ("network_accessed", "private_endpoint_called", "order_endpoint_called", "withdraw_called", "transfer_called")):
            return None, ("okx_live_preflight_provider_access_forbidden",)
        receipt = self.dependencies.preflight_receipt
        try:
            if receipt is None:
                receipt = provider.issue(request)
            verification = provider.verify(receipt, request, now_utc=self.dependencies.now)
        except Exception as exc:
            return None, (f"okx_live_preflight_failed:{type(exc).__name__}",)
        blockers = tuple(getattr(verification, "blockers", ()) or ())
        if not bool(getattr(verification, "status", "") == "PASS_READ_ONLY_PREFLIGHT") or blockers:
            return receipt, _dedupe(("okx_live_preflight_blocked", *blockers))
        if not isinstance(receipt, OKXLivePreflightReceipt):
            return None, ("okx_live_preflight_receipt_not_opaque",)
        return receipt, ()

    def _limits_blockers(self) -> tuple[str, ...]:
        bundle = self.dependencies.evidence_bundle
        facts = bundle.limit_facts if type(bundle) is _OpaqueEvidenceBundle else None
        if type(facts) is not SharedRuntimeLimitFacts:
            return ("authoritative_runtime_limits_missing",)
        return facts.blockers(self.candidate.policy)

    def _risk_pair(self) -> tuple[RuntimeRiskEvidenceProducer | None, RuntimeRiskEvidenceVerifier | None, tuple[str, ...]]:
        # The signer is created and retained only inside this composition
        # call.  Dependencies cannot supply an authority or producer.
        try:
            authority = RuntimeRiskEvidenceAuthority(name="btc-okx-canary-composition")
            producer, verifier = authority.bind()
        except Exception as exc:
            return None, None, (f"canonical_risk_authority_failed:{type(exc).__name__}",)
        return producer, verifier, ()

    def _risk_result(self, intent: OrderIntent) -> tuple[RuntimeAuthoritativeRiskResult | None, tuple[str, ...]]:
        bundle = self.dependencies.evidence_bundle
        result = bundle.risk_result if type(bundle) is _OpaqueEvidenceBundle else None
        if not isinstance(result, RuntimeAuthoritativeRiskResult):
            return None, ("authoritative_risk_result_missing",)
        try:
            if not result.verify(intent):
                return None, ("authoritative_risk_result_intent_mismatch",)
        except Exception:
            return None, ("authoritative_risk_result_invalid",)
        return result, ()

    def _evidence_blockers(self, result: RuntimeAuthoritativeRiskResult) -> tuple[str, ...]:
        policy = self.candidate.policy
        blockers: list[str] = []
        notional = _finite(result.actual_notional)
        exposure = _finite(result.exposure)
        if result.approved is not True:
            blockers.append("authoritative_risk_not_approved")
        if notional is None or notional <= 0 or notional > policy.max_notional_usdt:
            blockers.append("authoritative_notional_exceeds_10USDT")
        if exposure is None or exposure < 0 or exposure > policy.max_notional_usdt:
            blockers.append("authoritative_exposure_exceeds_10USDT")
        if _text(result.venue) != "okx":
            blockers.append("authoritative_venue_must_be_okx")
        if result.liquidation_safe is not True:
            blockers.append("authoritative_liquidation_not_safe")
        return _dedupe(blockers)

    def _protection_blockers(self, action: str, now: datetime) -> tuple[str, ...]:
        d = self.dependencies
        blockers: list[str] = []
        needs_deadman = action in {RuntimeAction.SUBMIT_NEW_ORDER.value, RuntimeAction.DEAD_MAN.value}
        needs_protection = action in {RuntimeAction.SUBMIT_NEW_ORDER.value, RuntimeAction.ATTACH_PROTECTION.value}
        bundle = self.dependencies.evidence_bundle
        dead_man_evidence = bundle.dead_man_evidence if type(bundle) is _OpaqueEvidenceBundle else None
        protection_plan = bundle.protection_plan if type(bundle) is _OpaqueEvidenceBundle else None
        if needs_deadman:
            if dead_man_evidence is None or not dead_man_evidence.valid_for(candidate=self.candidate, now=now):
                blockers.append("dead_man_not_armed_or_expired")
        if needs_protection:
            if protection_plan is None or not protection_plan.valid_for(candidate=self.candidate):
                blockers.append("oco_protection_ack_missing_or_namespace_mismatch")
        return _dedupe(blockers)

    def _ledger_blockers(self) -> tuple[str, ...]:
        d = self.dependencies
        if d.runtime_store is None or not callable(getattr(d.runtime_store, "commit_ledger_uow", None)):
            return ("ledger_store_commit_capability_missing",)
        bundle = d.evidence_bundle
        facts = bundle.ledger_facts if type(bundle) is _OpaqueEvidenceBundle else None
        if facts is None:
            return ("ledger_uow_facts_missing",)
        if type(facts) is not LedgerUOWFacts:
            return ("canonical_ledger_uow_evidence_invalid",)
        blockers = list(facts.blockers())
        if d.reconcile is None and not (facts.order_reconciled and facts.fill_reconciled and facts.position_reconciled):
            blockers.append("ledger_reconcile_capability_missing")
        return _dedupe(blockers)

    def _final_snapshot_unchanged(self, projection: BTCProjectionResult) -> tuple[str, ...]:
        supplier = self.dependencies.current_snapshot_supplier
        if supplier is None:
            return ()
        try:
            current = supplier()
            current_snapshot = current if isinstance(current, RuntimeSnapshot) else RuntimeSnapshot.from_dict(current)
        except Exception as exc:
            return (f"current_snapshot_supplier_failed:{type(exc).__name__}",)
        if current_snapshot.to_dict() != projection.snapshot.to_dict():
            return ("runtime_snapshot_changed_before_dispatch",)
        return ()

    def _arm_provider_permit(
        self,
        *,
        provider: OKXLiveTransport,
        action: str,
        intent: OrderIntent,
        risk_decision: RiskDecision,
        evidence: RuntimeRiskEvidence,
        method: str,
        path: str,
        body: Mapping[str, Any] | bytes | bytearray | None,
    ) -> tuple[str, ...]:
        authorizer = getattr(provider, "canonical_authorizer", None)
        if type(authorizer) is not _CanaryProviderAuthorizer:
            return ("okx_live_canonical_authorizer_mismatch",)
        try:
            authorizer.arm(
                provider=provider,
                action=action,
                client_order_id=intent.client_order_id,
                request_digest=_stable_outbound_digest(
                    method=method,
                    path=path,
                    body=body,
                    client_order_id=intent.client_order_id,
                    client_order_namespace=self.candidate.client_order_namespace,
                    state_root=self.candidate.state_root,
                    account_identity=self.candidate.account_hash,
                    key_namespace=self.candidate.credential_namespace,
                ),
                method=method,
                path=path,
                body=body,
                source_head=self.candidate.current_head,
                session_id=self.candidate.session_id,
                epoch=self.candidate.epoch,
                account_identity=self.candidate.account_hash,
                key_namespace=self.candidate.credential_namespace,
                state_root=self.candidate.state_root,
                client_order_namespace=self.candidate.client_order_namespace,
            )
        except Exception as exc:
            return (f"provider_dispatch_permit_failed:{type(exc).__name__}",)
        return ()

    def _query(self, provider: object, client_order_id: str) -> Callable[[str], Mapping[str, Any] | str | None]:
        callback = self.dependencies.query_by_client_order_id
        if callback is not None:
            return callback
        method = getattr(provider, "query_by_client_order_id", None)
        if callable(method):
            return method
        request = getattr(provider, "request", None)
        if callable(request):
            def _request(value: str) -> Mapping[str, Any] | str | None:
                authorizer = getattr(provider, "canonical_authorizer", None)
                if type(authorizer) is _CanaryProviderAuthorizer:
                    authorizer.arm(
                        provider=provider,
                        action="query_broker",
                        client_order_id=value,
                        request_digest=_stable_outbound_digest(
                            method="GET",
                            path="/api/v5/trade/order",
                            body={"instId": self.candidate.policy.instrument_id, "clOrdId": value},
                            client_order_id=value,
                            client_order_namespace=self.candidate.client_order_namespace,
                            state_root=self.candidate.state_root,
                            account_identity=self.candidate.account_hash,
                            key_namespace=self.candidate.credential_namespace,
                        ),
                        method="GET",
                        path="/api/v5/trade/order",
                        body={"instId": self.candidate.policy.instrument_id, "clOrdId": value},
                        source_head=self.candidate.current_head,
                        session_id=self.candidate.session_id,
                        epoch=self.candidate.epoch,
                        account_identity=self.candidate.account_hash,
                        key_namespace=self.candidate.credential_namespace,
                        state_root=self.candidate.state_root,
                        client_order_namespace=self.candidate.client_order_namespace,
                    )
                return request(
                    method="GET",
                    path="/api/v5/trade/order",
                    body={"instId": self.candidate.policy.instrument_id, "clOrdId": value},
                    client_order_id=value,
                )
            return _request
        return lambda _value: None

    def _ledger_commit(self, *, facts: LedgerUOWFacts, lifecycle: BTCClientOrderLifecycleRecord, receipt: object | None) -> tuple[bool, bool, tuple[str, ...]]:
        d = self.dependencies
        try:
            d.runtime_store.commit_ledger_uow(
                idempotency_key=facts.idempotency_key,
                timestamp_utc=_now(facts.timestamp_utc).isoformat(),
                run_id=facts.run_id,
                order=facts.order,
                fills=[dict(item) for item in facts.fills],
                position=facts.position,
                cash=facts.cash,
                funding=facts.funding,
                risk_context=facts.risk_context,
                state_after=facts.state_after,
                safety={**dict(facts.safety), "network_accessed": False, "real_order_submitted": False},
            )
        except Exception as exc:
            return False, False, (f"ledger_commit_failed:{type(exc).__name__}",)
        reconciled = True
        if d.reconcile is not None:
            try:
                reconciled = bool(d.reconcile(facts=facts, receipt=receipt, lifecycle=lifecycle))
            except Exception as exc:
                return True, False, (f"ledger_reconcile_failed:{type(exc).__name__}",)
            if not reconciled:
                return True, False, ("ledger_reconcile_failed",)
        checkpoint = getattr(d.runtime_store, "checkpoint", None)
        if callable(checkpoint):
            try:
                checkpoint(facts.state_after)
            except Exception as exc:
                return True, False, (f"ledger_checkpoint_failed:{type(exc).__name__}",)
        return True, reconciled, ()

    def execute(self, action: RuntimeAction | str = RuntimeAction.SUBMIT_NEW_ORDER) -> SharedRuntimeLiveResult:
        action_name = _text(action).replace("-", "_").replace(" ", "_")
        aliases = {"submit": "submit_new_order", "cancel": "cancel_order", "replace": "replace_order", "reduce_position": "reduce_only", "protection": "attach_protection", "deadman": "dead_man"}
        action_name = aliases.get(action_name, action_name)
        valid_actions = {item.value for item in RuntimeAction}
        if action_name not in valid_actions:
            return self._blocked(action_name, (f"unknown_runtime_action:{action_name}",))

        candidate_blockers = self.candidate.blockers()
        if candidate_blockers:
            return self._blocked(action_name, candidate_blockers)
        bundle, bundle_blockers = self._evidence_bundle()
        if bundle_blockers or bundle is None:
            return self._blocked(action_name, bundle_blockers)
        identity_blockers = self._identity_blockers()
        if identity_blockers:
            return self._blocked(action_name, identity_blockers)
        limits_blockers = self._limits_blockers()
        if limits_blockers:
            return self._blocked(action_name, limits_blockers)
        ledger_blockers = self._ledger_blockers()
        if ledger_blockers:
            return self._blocked(action_name, ledger_blockers)
        now = _now(self.dependencies.now)
        protection_blockers = self._protection_blockers(action_name, now)
        if protection_blockers:
            return self._blocked(action_name, protection_blockers)

        request = self.candidate.to_preflight_request()
        receipt, preflight_blockers = self._receipt(request)
        if preflight_blockers:
            return self._blocked(action_name, preflight_blockers)
        projection = build_btc_runtime_projection(
            bundle.exchange_runtime,
            identity=self.identity,
            broker_truth=bundle.broker_truth,
            ledger_freshness=bundle.ledger_freshness,
            endpoint_capability=bundle.endpoint_capability,
            recovery_requires_ack=bundle.recovery_requires_ack,
            operator_acknowledged=bundle.operator_acknowledged,
            now=now,
        )
        if projection.blockers:
            return self._blocked(action_name, projection.blockers, snapshot=projection.snapshot, projection=projection)
        config, config_blockers = self._config()
        if config_blockers or config is None:
            return self._blocked(action_name, config_blockers, snapshot=projection.snapshot, projection=projection)

        try:
            cl_ord_id = build_okx_client_order_id(config, self.candidate.order_intent.client_order_id)
            intent = replace(self.candidate.order_intent, client_order_id=cl_ord_id)
        except Exception as exc:
            return self._blocked(action_name, (f"clord_id_build_failed:{type(exc).__name__}",), snapshot=projection.snapshot, projection=projection)
        result, risk_result_blockers = self._risk_result(intent)
        if risk_result_blockers or result is None:
            return self._blocked(action_name, risk_result_blockers, cl_ord_id=cl_ord_id, snapshot=projection.snapshot, projection=projection)
        evidence_blockers = self._evidence_blockers(result)
        if evidence_blockers:
            return self._blocked(action_name, evidence_blockers, cl_ord_id=cl_ord_id, snapshot=projection.snapshot, projection=projection)
        producer, verifier, pair_blockers = self._risk_pair()
        if pair_blockers or producer is None or verifier is None:
            return self._blocked(action_name, pair_blockers, cl_ord_id=cl_ord_id, snapshot=projection.snapshot, projection=projection)
        try:
            evidence = producer.issue_from_authoritative(
                order_intent=intent,
                authoritative_result=result,
                source_head=self.candidate.current_head,
                account_identity=self.candidate.account_hash,
                session_id=self.candidate.session_id,
                key_namespace=self.candidate.credential_namespace,
                client_order_namespace=self.candidate.client_order_namespace,
                epoch=self.candidate.epoch,
                ttl_seconds=30.0,
                issued_at=now,
                evidence_id=f"btc-live-{intent.order_intent_id}-{self.candidate.epoch}",
            )
        except Exception as exc:
            return self._blocked(action_name, (f"risk_evidence_issue_failed:{type(exc).__name__}",), cl_ord_id=cl_ord_id, snapshot=projection.snapshot, projection=projection)
        # The canary always composes the evaluator with the verifier paired to
        # the authority above; callers cannot substitute a self-reported
        # ``approved`` decision or a second evaluator.
        evaluator = PermissionEvaluator(projection.snapshot, risk_verifier=verifier)

        provider = self.dependencies.transport
        provider_blockers = _provider_blockers(provider, dispatch_capability=self.dependencies.dispatch_capability)
        if provider_blockers:
            return self._blocked(action_name, provider_blockers, cl_ord_id=cl_ord_id, snapshot=projection.snapshot, projection=projection)
        final_blockers = list(self._final_snapshot_unchanged(projection))
        final_blockers.extend(self._limits_blockers())
        final_blockers.extend(self._protection_blockers(action_name, now))
        # The read-only receipt is a provider-authority identity check, not an
        # order permit.  Independent dispatch capability remains mandatory.
        if receipt is None or receipt.order_capability_allowed is not False:
            final_blockers.append("preflight_order_capability_must_remain_read_only")
        if receipt is not None and tuple(getattr(receipt, "permission_set", ())) == (OKX_DATA_READONLY_PERMISSION,):
            final_blockers.append("preflight_only_data_readonly")
        if final_blockers:
            return self._blocked(action_name, final_blockers, cl_ord_id=cl_ord_id, snapshot=projection.snapshot, projection=projection)

        lifecycle_store = self.dependencies.lifecycle_store
        if lifecycle_store is None:
            try:
                lifecycle_store = BTCClientOrderLifecycleStore(self.identity.state_directory, identity=self.identity)
            except Exception as exc:
                return self._blocked(action_name, (f"lifecycle_store_unavailable:{type(exc).__name__}",), cl_ord_id=cl_ord_id, snapshot=projection.snapshot, projection=projection)
        try:
            lifecycle = lifecycle_store.prepare(intent, action=action_name, reason="durable_clordid_before_provider")
        except Exception as exc:
            return self._blocked(action_name, (f"lifecycle_prepare_failed:{type(exc).__name__}",), cl_ord_id=cl_ord_id, snapshot=projection.snapshot, projection=projection)
        payload: dict[str, Any] = {
            "instId": self.candidate.policy.instrument_id,
            "tdMode": self.candidate.policy.margin_mode,
            "lever": str(self.candidate.policy.leverage),
            "clOrdId": cl_ord_id,
            "sz": str(intent.quantity),
        }
        if action_name == RuntimeAction.REDUCE_ONLY.value:
            payload["reduceOnly"] = True
        if bundle.protection_plan is not None:
            payload.update(dict(bundle.protection_plan.params))
        outbound_path = _ProviderAdapter._PATHS[action_name]
        permit_blockers = self._arm_provider_permit(
            provider=provider,
            action=action_name,
            intent=intent,
            risk_decision=self.candidate.risk_decision,
            evidence=evidence,
            method="POST",
            path=outbound_path,
            body=payload,
        )
        if permit_blockers:
            return self._blocked(action_name, permit_blockers, cl_ord_id=cl_ord_id, snapshot=projection.snapshot, projection=projection, lifecycle=lifecycle)
        adapter = _ProviderAdapter(provider, payload=payload, action=action_name)
        boundary = BTCExecutionBoundary(
            evaluator=evaluator,
            lifecycle_store=lifecycle_store,
            identity=self.identity,
            broker_truth=bundle.broker_truth,
            ledger_freshness=bundle.ledger_freshness,
            endpoint_capability=bundle.endpoint_capability,
            risk_evidence=evidence,
            current_head=self.candidate.current_head,
            session_id=self.candidate.session_id,
            epoch=self.candidate.epoch,
            transport=adapter,
        )
        try:
            boundary_result = boundary.execute_action(
                action_name,
                order_intent=intent,
                risk_decision=self.candidate.risk_decision,
                risk_evidence=evidence,
            )
        except Exception as exc:
            return self._blocked(action_name, (f"boundary_failed:{type(exc).__name__}",), cl_ord_id=cl_ord_id, snapshot=projection.snapshot, projection=projection, lifecycle=lifecycle)
        lifecycle = boundary_result.lifecycle or lifecycle_store.get(cl_ord_id)
        authorizer_blocker = str(getattr(getattr(provider, "canonical_authorizer", None), "last_blocker", "") or "")
        if authorizer_blocker:
            return self._blocked(
                action_name,
                (authorizer_blocker,),
                cl_ord_id=cl_ord_id,
                snapshot=projection.snapshot,
                projection=projection,
                lifecycle=lifecycle,
                receipt=boundary_result.receipt,
                ambiguous=False,
                query_called=False,
            )
        boundary_ambiguous = bool(
            lifecycle is not None and lifecycle.status is BTCOrderLifecycleStatus.AMBIGUOUS
        ) or "transport_outcome_ambiguous" in boundary_result.blockers
        query_called = False
        query_result: object | None = None
        if boundary_ambiguous:
            try:
                query_called = True
                query_result = lifecycle_store.query_by_client_order_id(intent, self._query(provider, cl_ord_id))
                lifecycle = query_result
            except Exception as exc:
                return self._blocked(action_name, ("transport_outcome_ambiguous", "query_by_client_order_id_failed", type(exc).__name__), cl_ord_id=cl_ord_id, snapshot=projection.snapshot, projection=projection, lifecycle=lifecycle, receipt=boundary_result.receipt, ambiguous=True, query_called=query_called, query_result=query_result)
            if lifecycle.status in {BTCOrderLifecycleStatus.AMBIGUOUS, BTCOrderLifecycleStatus.SENT}:
                return self._blocked(action_name, ("transport_outcome_ambiguous", "query_by_client_order_id_required"), cl_ord_id=cl_ord_id, snapshot=projection.snapshot, projection=projection, lifecycle=lifecycle, receipt=boundary_result.receipt, ambiguous=True, query_called=query_called, query_result=query_result)
        if not boundary_result.decision.allowed:
            return self._blocked(action_name, boundary_result.blockers or boundary_result.decision.reasons, cl_ord_id=cl_ord_id, snapshot=projection.snapshot, projection=projection, decision=boundary_result.decision, lifecycle=lifecycle, receipt=boundary_result.receipt, ambiguous=boundary_ambiguous, query_called=query_called, query_result=query_result)
        if lifecycle is None:
            return self._blocked(action_name, ("client_order_lifecycle_missing_after_dispatch",), cl_ord_id=cl_ord_id, snapshot=projection.snapshot, projection=projection, decision=boundary_result.decision, receipt=boundary_result.receipt)
        status = "accepted"
        if isinstance(boundary_result.receipt, Mapping):
            status = str(boundary_result.receipt.get("status", boundary_result.receipt.get("state", "accepted")))
        try:
            lifecycle_store.resolve(intent, status=status, broker_order_id=str((boundary_result.receipt or {}).get("broker_order_id", "")) if isinstance(boundary_result.receipt, Mapping) else "", action=action_name)
            lifecycle = lifecycle_store.mark_reconciled(
                intent,
                status=status,
                order_reconciled=True,
                fill_reconciled=True,
                position_reconciled=True,
                action=action_name,
            )
        except Exception as exc:
            return self._blocked(action_name, (f"clord_reconciliation_failed:{type(exc).__name__}",), cl_ord_id=cl_ord_id, snapshot=projection.snapshot, projection=projection, decision=boundary_result.decision, lifecycle=lifecycle, receipt=boundary_result.receipt)
        bundle = self.dependencies.evidence_bundle
        ledger_facts = bundle.ledger_facts if type(bundle) is _OpaqueEvidenceBundle else None
        committed, reconciled, ledger_blockers = self._ledger_commit(facts=ledger_facts, lifecycle=lifecycle, receipt=boundary_result.receipt)  # type: ignore[arg-type]
        if ledger_blockers:
            return self._blocked(action_name, ledger_blockers, cl_ord_id=cl_ord_id, snapshot=projection.snapshot, projection=projection, decision=boundary_result.decision, lifecycle=lifecycle, receipt=boundary_result.receipt, ledger_committed=committed, reconciled=reconciled)
        return SharedRuntimeLiveResult(
            allowed=True,
            action=action_name,
            cl_ord_id=cl_ord_id,
            snapshot=projection.snapshot,
            projection=projection,
            decision=boundary_result.decision,
            lifecycle=lifecycle,
            receipt=boundary_result.receipt,
            ledger_committed=committed,
            reconciled=reconciled,
            dead_man_payload={"evidence_id": bundle.dead_man_evidence.evidence_id} if bundle.dead_man_evidence is not None else None,
            protection_payload=dict(bundle.protection_plan.params) if bundle.protection_plan is not None else None,
        )

    run = execute
    dispatch = execute
    submit = execute


BTCSharedRuntimeLiveCanary = BTCOKXSharedRuntimeLiveCanary
SharedRuntimeLiveCanary = BTCOKXSharedRuntimeLiveCanary
SharedRuntimeLivePolicy = OKXLivePreflightPolicy


def run_btc_okx_shared_runtime_live_canary(*, candidate: SharedRuntimeLiveCandidate, identity: BTCExecutionIdentity, dependencies: SharedRuntimeLiveDependencies | None = None, action: RuntimeAction | str = RuntimeAction.SUBMIT_NEW_ORDER) -> SharedRuntimeLiveResult:
    return BTCOKXSharedRuntimeLiveCanary(candidate=candidate, identity=identity, dependencies=dependencies).execute(action)


__all__ = [
    "BTCOKXSharedRuntimeLiveCanary",
    "BTCSharedRuntimeLiveCanary",
    "DeadManArmedEvidence",
    "LedgerUOWFacts",
    "ProtectionPlan",
    "SCHEMA_VERSION",
    "SharedRuntimeLimitFacts",
    "SharedRuntimeLiveBlocked",
    "SharedRuntimeLiveCanary",
    "SharedRuntimeLiveCandidate",
    "SharedRuntimeLiveDependencies",
    "SharedRuntimeLivePolicy",
    "SharedRuntimeLiveResult",
    "run_btc_okx_shared_runtime_live_canary",
]
