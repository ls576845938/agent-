"""Fail-closed OKX mode and live-transport contracts.

This module intentionally contains no HTTP, socket, environment, credential-store,
or secret-reading code.  A caller may inject a deterministic fake responder for
contract tests, but the registry never supplies a live provider by default.

The legacy recording builder is retained for the existing Demo/micro-live
contract tests.  New code should use :class:`OKXTransportRegistry` and an
explicit :class:`OKXLiveTransportOptIn` when it needs to exercise an injected
fake live transport.
"""

from __future__ import annotations

import ipaddress
import hashlib
import json
import re
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, Sequence


OKX_DEMO_API_BASE = "https://www.okx.com"
OKX_LIVE_API_BASE = "https://openapi.okx.com"
OKX_LIVE_READ_ONLY_PERMISSION = "data_readonly"
OKX_LIVE_TRANSPORT_CONTRACT_VERSION = "okx_live_transport_contract_v1"
OKX_LIVE_ATTESTATION_SCHEMA_VERSION = "okx_live_read_only_attestation_v1"
_IDENTITY_HASH_RE = re.compile(r"[0-9a-f]{64}\Z")
_FINGERPRINT_RE = re.compile(r"[0-9a-f]{64}\Z")
_SAFE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_FORBIDDEN_CAPABILITY_TOKENS = (
    "/withdraw",
    "/transfer",
    "withdrawal",
    "asset/transfer",
    "account/transfer",
)
_ORDER_SUBMIT_PATHS = (
    "/api/v5/trade/order",
    "/api/v5/trade/order-algo",
)


class OKXTransportMode(str, Enum):
    DEMO = "demo"
    LIVE = "live"


class OKXTransportStatus(str, Enum):
    """Transport availability; ``NO_TRANSPORT`` is the safe default."""

    AVAILABLE = "available"
    NO_TRANSPORT = "no_transport"


class OKXModeTransportError(RuntimeError):
    """Base error for local mode/transport contract violations."""


class OKXModeIsolationError(OKXModeTransportError):
    """Demo and live identity/configuration would cross-contaminate."""


class OKXLiveOptInRequired(OKXModeTransportError):
    """A live provider was requested without an explicit auditable opt-in."""


class OKXTransportUnavailable(OKXModeTransportError):
    """A registry resolved to the fail-closed NO_TRANSPORT sentinel."""


class OKXCapabilityError(OKXModeTransportError):
    """A forbidden transfer/withdraw or unsupported capability was requested."""


class OKXTransportError(OKXModeTransportError):
    """An injected transport responder failed."""


class OKXCanonicalAuthorizer(Protocol):
    """Opaque boundary for the canonical runtime authorizer.

    The live transport deliberately does not define a permission or runtime
    snapshot schema.  The injected canonical implementation owns the current
    RuntimeSnapshot, endpoint capability, session/account/client namespace,
    epoch, and current-head checks.  A transport dispatch is allowed only
    when this method returns the literal boolean ``True``.  There is no cached
    permit: the method is called for every fake dispatch attempt.
    """

    def authorize_dispatch(self, *, request: "OKXRecordedRequest") -> Any: ...


class OKXAmbiguousSubmitError(OKXTransportError):
    """A non-GET order submit has an unknown outcome.

    The transport deliberately does not retry.  The upper durable OMS layer
    must reconcile the supplied ``client_order_id`` before any further action.
    """

    def __init__(self, client_order_id: str, cause: BaseException) -> None:
        self.client_order_id = str(client_order_id)
        self.reconciliation_required = True
        self.retry_performed = False
        self.cause_type = type(cause).__name__
        super().__init__(
            "okx_ambiguous_submit_requires_clordid_reconciliation:"
            f"{self.client_order_id}"
        )


# Short aliases make the contract easy to consume without weakening semantics.
AmbiguousSubmitError = OKXAmbiguousSubmitError
NoTransportError = OKXTransportUnavailable


def _mode(value: OKXTransportMode | str) -> OKXTransportMode:
    return value if isinstance(value, OKXTransportMode) else OKXTransportMode(str(value))


def _valid_hash(value: str) -> bool:
    return bool(_IDENTITY_HASH_RE.fullmatch(str(value)))


def _valid_identifier(value: str) -> bool:
    return bool(_SAFE_ID_RE.fullmatch(str(value)))


def _canonical_path(path: str) -> str:
    normalized = str(path or "").strip()
    if not normalized.startswith("/"):
        normalized = "/" + normalized
    return normalized


def _forbidden_capability_path(path: str) -> bool:
    lowered = _canonical_path(path).lower()
    return any(token in lowered for token in _FORBIDDEN_CAPABILITY_TOKENS)


def _is_order_submit(path: str) -> bool:
    lowered = _canonical_path(path).lower().split("?", 1)[0]
    return lowered in _ORDER_SUBMIT_PATHS


def _as_utc_iso(value: datetime | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        observed = value
    else:
        text = str(value).strip()
        if not text:
            return None
        try:
            observed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return str(value)
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=timezone.utc)
    return observed.astimezone(timezone.utc).isoformat()


@dataclass(frozen=True)
class OKXCredentialReference:
    """Non-secret credential/account identity used by a mode-bound session."""

    mode: OKXTransportMode
    service_namespace: str
    account_hash: str
    credential_identity: str = ""

    def __post_init__(self) -> None:
        selected_mode = _mode(self.mode)
        object.__setattr__(self, "mode", selected_mode)
        expected = {
            OKXTransportMode.DEMO: "quant-system.okx-demo.",
            OKXTransportMode.LIVE: "quant-system.okx-live.",
        }[selected_mode]
        namespace = str(self.service_namespace).strip()
        if not namespace.startswith(expected):
            raise OKXModeIsolationError("okx_credential_namespace_mode_mismatch")
        if not _valid_hash(str(self.account_hash)):
            raise OKXModeIsolationError("okx_account_hash_invalid")
        identity = str(self.credential_identity).strip()
        if not identity:
            identity = namespace
        if not _valid_identifier(identity):
            raise OKXModeIsolationError("okx_credential_identity_invalid")
        if any(token in identity.lower() for token in ("secret", "passphrase", "token", "api_key")):
            raise OKXModeIsolationError("okx_credential_identity_must_not_contain_secret")
        mode_prefix = f"quant-system.okx-{selected_mode.value}."
        if not identity.startswith(mode_prefix):
            raise OKXModeIsolationError("okx_credential_identity_mode_mismatch")
        object.__setattr__(self, "service_namespace", namespace)
        object.__setattr__(self, "account_hash", str(self.account_hash))
        object.__setattr__(self, "credential_identity", identity)


@dataclass(frozen=True)
class OKXModeIsolationConfig:
    """Mode-bound, non-secret configuration for one OKX runtime namespace."""

    mode: OKXTransportMode
    credential_reference: OKXCredentialReference
    state_root: Path | str
    client_order_namespace: str
    api_base: str = ""
    explicit_live_opt_in: bool = False
    private_endpoint_allowed: bool = False
    order_endpoint_allowed: bool = False
    network_enabled: bool = False

    def __post_init__(self) -> None:
        selected_mode = _mode(self.mode)
        object.__setattr__(self, "mode", selected_mode)
        if self.credential_reference.mode != selected_mode:
            raise OKXModeIsolationError("okx_config_credential_mode_mismatch")
        base = str(self.api_base).strip() or (
            OKX_DEMO_API_BASE if selected_mode is OKXTransportMode.DEMO else OKX_LIVE_API_BASE
        )
        expected_base = (
            OKX_DEMO_API_BASE if selected_mode is OKXTransportMode.DEMO else OKX_LIVE_API_BASE
        )
        if base != expected_base:
            raise OKXModeIsolationError("okx_api_base_mode_mismatch")
        raw_root = str(self.state_root).strip()
        if not raw_root:
            raise OKXModeIsolationError("okx_state_root_missing")
        root = Path(raw_root).expanduser().resolve()
        namespace = str(self.client_order_namespace).strip()
        if not _valid_identifier(namespace):
            raise OKXModeIsolationError("okx_client_order_namespace_invalid")
        required_prefix = f"btc-okx-{selected_mode.value}-"
        if not namespace.startswith(required_prefix):
            raise OKXModeIsolationError("okx_client_order_namespace_mode_mismatch")
        if self.network_enabled:
            raise OKXModeIsolationError("okx_network_must_be_injected_fake_only")
        if selected_mode is OKXTransportMode.DEMO and self.explicit_live_opt_in:
            raise OKXModeIsolationError("okx_demo_cannot_opt_in_live")
        if selected_mode is OKXTransportMode.DEMO and (
            self.private_endpoint_allowed is False and self.order_endpoint_allowed is True
        ):
            # A Demo order capability must never be smuggled in without the
            # Demo private capability being explicitly represented.
            raise OKXModeIsolationError("okx_demo_order_requires_private_capability")
        object.__setattr__(self, "api_base", base)
        object.__setattr__(self, "state_root", root)
        object.__setattr__(self, "client_order_namespace", namespace)

    @classmethod
    def demo(
        cls,
        *,
        account_hash: str,
        state_root: Path | str,
        client_order_namespace: str = "btc-okx-demo-",
        credential_identity: str = "",
        private_endpoint_allowed: bool = False,
        order_endpoint_allowed: bool = False,
    ) -> "OKXModeIsolationConfig":
        reference = OKXCredentialReference(
            mode=OKXTransportMode.DEMO,
            service_namespace="quant-system.okx-demo.trade",
            account_hash=account_hash,
            credential_identity=credential_identity,
        )
        return cls(
            mode=OKXTransportMode.DEMO,
            credential_reference=reference,
            state_root=state_root,
            client_order_namespace=client_order_namespace,
            private_endpoint_allowed=private_endpoint_allowed,
            order_endpoint_allowed=order_endpoint_allowed,
        )

    @classmethod
    def live(
        cls,
        *,
        account_hash: str,
        state_root: Path | str,
        client_order_namespace: str = "btc-okx-live-",
        credential_identity: str = "",
        explicit_live_opt_in: bool = False,
        private_endpoint_allowed: bool = False,
        order_endpoint_allowed: bool = False,
    ) -> "OKXModeIsolationConfig":
        reference = OKXCredentialReference(
            mode=OKXTransportMode.LIVE,
            service_namespace="quant-system.okx-live.trade",
            account_hash=account_hash,
            credential_identity=credential_identity,
        )
        return cls(
            mode=OKXTransportMode.LIVE,
            credential_reference=reference,
            state_root=state_root,
            client_order_namespace=client_order_namespace,
            explicit_live_opt_in=explicit_live_opt_in,
            private_endpoint_allowed=private_endpoint_allowed,
            order_endpoint_allowed=order_endpoint_allowed,
        )

    def to_public_dict(self) -> dict[str, Any]:
        """Return an audit-safe view; no raw credential material is accepted."""

        return {
            "mode": self.mode.value,
            "api_base": self.api_base,
            "credential_identity": self.credential_reference.credential_identity,
            "credential_namespace": self.credential_reference.service_namespace,
            "account_hash": self.credential_reference.account_hash,
            "state_root": str(self.state_root),
            "client_order_namespace": self.client_order_namespace,
            "private_endpoint_allowed": bool(self.private_endpoint_allowed),
            "order_endpoint_allowed": bool(self.order_endpoint_allowed),
            "network_enabled": False,
            "live_unlock_allowed": False,
            "secrets_read": False,
        }


def validate_okx_mode_isolation(
    demo: OKXModeIsolationConfig,
    live: OKXModeIsolationConfig,
) -> tuple[str, ...]:
    """Return deterministic blockers when Demo/live namespaces are reused."""

    blockers: list[str] = []
    if demo.mode is not OKXTransportMode.DEMO:
        blockers.append("okx_demo_config_mode_must_be_demo")
    if live.mode is not OKXTransportMode.LIVE:
        blockers.append("okx_live_config_mode_must_be_live")
    if demo.api_base == live.api_base:
        blockers.append("okx_demo_live_api_base_reused")
    if demo.credential_reference.credential_identity == live.credential_reference.credential_identity:
        blockers.append("okx_demo_live_credential_identity_reused")
    if demo.credential_reference.service_namespace == live.credential_reference.service_namespace:
        blockers.append("okx_demo_live_credential_namespace_reused")
    if demo.credential_reference.account_hash == live.credential_reference.account_hash:
        blockers.append("okx_demo_live_account_identity_reused")
    if demo.state_root == live.state_root:
        blockers.append("okx_demo_live_state_root_reused")
    elif demo.state_root in live.state_root.parents or live.state_root in demo.state_root.parents:
        blockers.append("okx_demo_live_state_root_overlaps")
    if demo.client_order_namespace == live.client_order_namespace:
        blockers.append("okx_demo_live_client_order_namespace_reused")
    elif demo.client_order_namespace.startswith(live.client_order_namespace) or live.client_order_namespace.startswith(demo.client_order_namespace):
        blockers.append("okx_demo_live_client_order_namespace_overlaps")
    return tuple(dict.fromkeys(blockers))


def assert_okx_mode_isolated(
    demo: OKXModeIsolationConfig,
    live: OKXModeIsolationConfig,
) -> None:
    blockers = validate_okx_mode_isolation(demo, live)
    if blockers:
        raise OKXModeIsolationError(";".join(blockers))


def build_okx_client_order_id(
    config: OKXModeIsolationConfig,
    local_id: str,
) -> str:
    """Create a deterministic, mode-prefixed client order id.

    The local suffix is deliberately constrained so a caller cannot inject a
    second mode namespace or a separator that makes ownership ambiguous.
    """

    suffix = str(local_id).strip()
    if not suffix or not _valid_identifier(suffix):
        raise OKXModeIsolationError("okx_client_order_suffix_invalid")
    if suffix.startswith("btc-okx-"):
        raise OKXModeIsolationError("okx_client_order_suffix_must_not_include_namespace")
    return f"{config.client_order_namespace}{suffix}"


@dataclass(frozen=True)
class OKXRecordedRequest:
    mode: OKXTransportMode
    method: str
    path: str
    headers: Mapping[str, str]
    body: bytes | None
    credential_reference: OKXCredentialReference
    api_base: str = ""
    state_root: str = ""
    client_order_namespace: str = ""
    client_order_id: str | None = None
    attempt: int = 1

    def audit_dict(self) -> dict[str, Any]:
        return {
            "mode": _mode(self.mode).value,
            "method": str(self.method).upper(),
            "path": self.path,
            "api_base": self.api_base,
            "header_names": sorted(key.lower() for key in self.headers),
            "body_sha256_recorded_by_caller": False,
            "credential": {
                "credential_identity": self.credential_reference.credential_identity,
                "service_namespace": self.credential_reference.service_namespace,
                "account_hash": self.credential_reference.account_hash,
            },
            "state_root": self.state_root,
            "client_order_namespace": self.client_order_namespace,
            "client_order_id": self.client_order_id,
            "attempt": int(self.attempt),
            "secret_values_recorded": False,
            "network_accessed": False,
        }


class OKXRecordingTransport:
    """In-memory transport with no URL, socket, or HTTP implementation."""

    def __init__(self, *, mode: OKXTransportMode) -> None:
        self.mode = _mode(mode)
        self.requests: list[OKXRecordedRequest] = []
        self.network_accessed = False
        self.private_endpoint_accessed = False
        self.order_endpoint_accessed = False
        self.withdraw_transfer_accessed = False

    @property
    def safety(self) -> dict[str, bool]:
        """Derive access flags from the recording transport's single source.

        The object intentionally exposes a fresh mapping so callers cannot
        manufacture a safer receipt by mutating a cached dictionary.
        """

        return {
            "network_accessed": bool(self.network_accessed),
            "private_endpoint_accessed": bool(self.private_endpoint_accessed),
            "order_endpoint_accessed": bool(self.order_endpoint_accessed),
            "withdraw_transfer_accessed": bool(self.withdraw_transfer_accessed),
        }

    @property
    def status(self) -> OKXTransportStatus:
        return OKXTransportStatus.AVAILABLE

    def record(self, request: OKXRecordedRequest) -> None:
        if request.mode != self.mode:
            raise OKXModeIsolationError("okx_transport_mode_mismatch")
        if _forbidden_capability_path(request.path):
            self.withdraw_transfer_accessed = True
            raise OKXCapabilityError("okx_withdraw_transfer_forbidden")
        self.private_endpoint_accessed = True
        self.order_endpoint_accessed = self.order_endpoint_accessed or _is_order_submit(request.path)
        self.requests.append(request)

    def send(self, request: OKXRecordedRequest) -> OKXRecordedRequest:
        self.record(request)
        return request


class OKXModeIsolatedRequestBuilder:
    """Build a mode-specific request for an injected recording transport."""

    def __init__(
        self,
        *,
        credential_reference: OKXCredentialReference,
        transport: OKXRecordingTransport,
        config: OKXModeIsolationConfig | None = None,
    ) -> None:
        if credential_reference.mode != transport.mode:
            raise OKXModeIsolationError("okx_transport_credential_mode_mismatch")
        if config is not None and (
            config.mode != transport.mode
            or config.credential_reference != credential_reference
        ):
            raise OKXModeIsolationError("okx_builder_config_mode_mismatch")
        self.credential_reference = credential_reference
        self.transport = transport
        self.config = config

    def record_private_request(
        self,
        *,
        method: str,
        path: str,
        body: Mapping[str, Any] | None = None,
    ) -> OKXRecordedRequest:
        request = self.build_private_request(method=method, path=path, body=body)
        self.transport.record(request)
        return request

    def build_private_request(
        self,
        *,
        method: str,
        path: str,
        body: Mapping[str, Any] | None = None,
    ) -> OKXRecordedRequest:
        """Build without recording so a live dispatch can authorize first."""

        normalized_method = str(method).upper()
        if normalized_method not in {"GET", "POST", "PUT", "DELETE"}:
            raise OKXCapabilityError("okx_request_method_not_allowed")
        normalized_path = _canonical_path(path)
        if not normalized_path.startswith("/api/v5/"):
            raise OKXCapabilityError("okx_request_path_not_allowed")
        if _forbidden_capability_path(normalized_path):
            raise OKXCapabilityError("okx_withdraw_transfer_forbidden")
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-Credential-Namespace": self.credential_reference.service_namespace,
        }
        if self.credential_reference.mode is OKXTransportMode.DEMO:
            headers["x-simulated-trading"] = "1"
        elif any(key.lower() == "x-simulated-trading" for key in headers):
            raise OKXModeIsolationError("okx_live_simulated_trading_header_forbidden")
        encoded = (
            None
            if body is None
            else json.dumps(
                dict(body), ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        )
        client_order_id = None
        if isinstance(body, Mapping):
            candidate = body.get("clOrdId") or body.get("client_order_id")
            client_order_id = str(candidate) if candidate else None
        request = OKXRecordedRequest(
            mode=self.credential_reference.mode,
            method=normalized_method,
            path=normalized_path,
            headers=headers,
            body=encoded,
            credential_reference=self.credential_reference,
            api_base=self.config.api_base if self.config else "",
            state_root=str(self.config.state_root) if self.config else "",
            client_order_namespace=(self.config.client_order_namespace if self.config else ""),
            client_order_id=client_order_id,
        )
        return request


class OKXInjectedResponder(Protocol):
    def __call__(self, request: OKXRecordedRequest) -> Any: ...


@dataclass(frozen=True)
class OKXLiveTransportOptIn:
    """Auditable opt-in token for an injected fake live provider only."""

    ticket: str
    operator: str
    reason: str
    confirmed: bool = False
    read_only: bool = True

    def blockers(self) -> tuple[str, ...]:
        blockers: list[str] = []
        for field_name in ("ticket", "operator", "reason"):
            if not str(getattr(self, field_name)).strip():
                blockers.append(f"okx_live_opt_in_{field_name}_missing")
        if self.confirmed is not True:
            blockers.append("okx_live_opt_in_confirmation_missing")
        if self.read_only is not True:
            blockers.append("okx_live_opt_in_must_be_read_only_fake")
        return tuple(blockers)

    def valid(self) -> bool:
        return not self.blockers()

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticket": self.ticket,
            "operator": self.operator,
            "reason": self.reason,
            "confirmed": bool(self.confirmed),
            "read_only": bool(self.read_only),
            "network_accessed": False,
            "real_order_submitted": False,
        }


def _strict_capability_bool(value: Any) -> bool:
    """Only an actual boolean ``True`` can enable a B capability."""

    return value is True


@dataclass(frozen=True)
class OKXTransportCapabilitySnapshot:
    """B-owned, read-only view of the live transport capability boundary.

    This is deliberately not the runtime permission schema owned by agent1.
    The optional input digest is treated as opaque evidence and is folded into
    a deterministic digest together with the three capability bits.  A change
    in either the bits or the opaque digest therefore invalidates a dispatch
    fence without caching or accepting a permit locally.
    """

    transport_enabled: bool
    private_endpoint_allowed: bool
    order_endpoint_allowed: bool
    capability_digest: str = ""

    def __post_init__(self) -> None:
        transport_enabled = _strict_capability_bool(self.transport_enabled)
        private_endpoint_allowed = _strict_capability_bool(self.private_endpoint_allowed)
        order_endpoint_allowed = _strict_capability_bool(self.order_endpoint_allowed)
        declared_digest = str(self.capability_digest or "").strip()
        payload = {
            "transport_enabled": transport_enabled,
            "private_endpoint_allowed": private_endpoint_allowed,
            "order_endpoint_allowed": order_endpoint_allowed,
            "declared_capability_digest": declared_digest,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        derived_digest = hashlib.sha256(encoded).hexdigest()
        object.__setattr__(self, "transport_enabled", transport_enabled)
        object.__setattr__(self, "private_endpoint_allowed", private_endpoint_allowed)
        object.__setattr__(self, "order_endpoint_allowed", order_endpoint_allowed)
        object.__setattr__(self, "capability_digest", derived_digest)

    @classmethod
    def from_source(cls, source: Any) -> "OKXTransportCapabilitySnapshot":
        """Normalize an injected fake/mapping; missing values stay disabled."""

        if isinstance(source, cls):
            return source
        view: Mapping[str, Any] | None = source if isinstance(source, Mapping) else None
        if view is None:
            to_dict = getattr(source, "to_dict", None)
            if callable(to_dict):
                try:
                    supplied = to_dict()
                except Exception:
                    supplied = None
                if isinstance(supplied, Mapping):
                    view = supplied
        def value(name: str) -> Any:
            if view is not None:
                return view.get(name)
            return getattr(source, name, None)

        declared_digest = value("capability_digest")
        if declared_digest is None:
            declared_digest = value("digest")
        return cls(
            transport_enabled=value("transport_enabled"),
            private_endpoint_allowed=value("private_endpoint_allowed"),
            order_endpoint_allowed=value("order_endpoint_allowed"),
            capability_digest="" if declared_digest is None else str(declared_digest),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "transport_enabled": self.transport_enabled,
            "private_endpoint_allowed": self.private_endpoint_allowed,
            "order_endpoint_allowed": self.order_endpoint_allowed,
            "capability_digest": self.capability_digest,
        }


class OKXNoTransport:
    """Registry sentinel returned when no explicit live provider is present."""

    mode = OKXTransportMode.LIVE
    status = OKXTransportStatus.NO_TRANSPORT
    network_accessed = False
    private_endpoint_accessed = False
    order_endpoint_accessed = False
    withdraw_transfer_accessed = False
    requests: tuple[OKXRecordedRequest, ...] = ()

    @property
    def safety(self) -> dict[str, bool]:
        return {
            "network_accessed": False,
            "private_endpoint_accessed": False,
            "order_endpoint_accessed": False,
            "withdraw_transfer_accessed": False,
            "real_order_submitted": False,
            "secrets_read": False,
            "live_unlock_allowed": False,
        }

    def request(self, **_: Any) -> Any:
        raise OKXTransportUnavailable("NO_TRANSPORT:okx_live_provider_not_registered")

    send = request


class OKXLiveTransport(OKXRecordingTransport):
    """Injected fake live transport with strict mode/capability semantics.

    It never constructs a URL and never calls a network library.  The optional
    responder is a test double supplied by the caller.  Non-GET requests are
    dispatched once; an uncertain order submit is raised as an
    :class:`OKXAmbiguousSubmitError` for durable clOrdId reconciliation.
    """

    def __init__(
        self,
        *,
        config: OKXModeIsolationConfig,
        responder: OKXInjectedResponder | None = None,
        opt_in: OKXLiveTransportOptIn | None = None,
        canonical_authorizer: OKXCanonicalAuthorizer | None = None,
        canonical_context_provider: Callable[[OKXRecordedRequest], Mapping[str, Any]] | None = None,
        capability_provider: Callable[[], Any] | Any | None = None,
        transport_capability_provider: Callable[[], Any] | Any | None = None,
        max_get_attempts: int = 1,
    ) -> None:
        if config.mode is not OKXTransportMode.LIVE:
            raise OKXModeIsolationError("okx_live_transport_requires_live_config")
        if opt_in is None or not opt_in.valid():
            raise OKXLiveOptInRequired(";".join(opt_in.blockers() if opt_in else ("okx_live_opt_in_missing",)))
        if int(max_get_attempts) < 1:
            raise OKXModeTransportError("okx_get_attempts_must_be_positive")
        super().__init__(mode=OKXTransportMode.LIVE)
        self.config = config
        self.opt_in = opt_in
        self._responder = responder
        self._canonical_authorizer = canonical_authorizer
        self._canonical_context_provider = canonical_context_provider
        if capability_provider is not None and transport_capability_provider is not None:
            raise OKXModeTransportError("okx_capability_provider_ambiguous")
        supplied_capability_provider = (
            capability_provider
            if capability_provider is not None
            else transport_capability_provider
        )
        if supplied_capability_provider is None:
            self._capability_provider: Callable[[], Any] | None = None
        elif callable(supplied_capability_provider):
            self._capability_provider = supplied_capability_provider
        else:
            self._capability_provider = lambda supplied=supplied_capability_provider: supplied
        self._max_get_attempts = int(max_get_attempts)
        self.attempts: list[tuple[str, str]] = []

    @property
    def canonical_authorizer(self) -> OKXCanonicalAuthorizer | None:
        return self._canonical_authorizer

    @property
    def capability_snapshot(self) -> OKXTransportCapabilitySnapshot:
        """Read the current B capability state from its injected source."""

        return self._current_capability_snapshot()

    @property
    def safety(self) -> dict[str, bool]:
        """Return transport-derived safety state; never a caller-settable cache."""

        return {
            **super().safety,
            "real_order_submitted": False,
            "secrets_read": False,
            "live_unlock_allowed": False,
        }

    def _default_capability_snapshot(self) -> OKXTransportCapabilitySnapshot:
        return OKXTransportCapabilitySnapshot(
            # ``network_enabled`` is rejected by the config.  A constructed
            # transport therefore represents an injected fake transport, not
            # real network access.
            transport_enabled=self.config.network_enabled is not True,
            private_endpoint_allowed=self.config.private_endpoint_allowed,
            order_endpoint_allowed=self.config.order_endpoint_allowed,
        )

    def _current_capability_snapshot(self) -> OKXTransportCapabilitySnapshot:
        provider = self._capability_provider
        if provider is None:
            return self._default_capability_snapshot()
        try:
            source = provider()
        except Exception as exc:
            return OKXTransportCapabilitySnapshot(
                transport_enabled=False,
                private_endpoint_allowed=False,
                order_endpoint_allowed=False,
                capability_digest=f"provider-error:{type(exc).__name__}",
            )
        try:
            supplied = OKXTransportCapabilitySnapshot.from_source(source)
        except Exception as exc:
            return OKXTransportCapabilitySnapshot(
                transport_enabled=False,
                private_endpoint_allowed=False,
                order_endpoint_allowed=False,
                capability_digest=f"capability-normalize-error:{type(exc).__name__}",
            )
        # An injected source may further restrict B, but it cannot smuggle
        # capabilities past explicit config-level false values.
        return OKXTransportCapabilitySnapshot(
            transport_enabled=(
                supplied.transport_enabled
                and self.config.network_enabled is not True
            ),
            private_endpoint_allowed=(
                supplied.private_endpoint_allowed
                and self.config.private_endpoint_allowed is True
            ),
            order_endpoint_allowed=(
                supplied.order_endpoint_allowed
                and self.config.order_endpoint_allowed is True
            ),
            capability_digest=supplied.capability_digest,
        )

    @staticmethod
    def _assert_capability_allowed(
        request: OKXRecordedRequest,
        snapshot: OKXTransportCapabilitySnapshot,
    ) -> None:
        if snapshot.transport_enabled is not True:
            raise OKXCapabilityError("okx_transport_capability_transport_disabled")
        # The builder only constructs /api/v5 private requests, so every
        # dispatch is private even when its action is a read-only GET.
        if snapshot.private_endpoint_allowed is not True:
            raise OKXCapabilityError("okx_transport_capability_private_endpoint_disabled")
        if request.method != "GET" and snapshot.order_endpoint_allowed is not True:
            action = OKXLiveTransport._action_for_request(request)
            raise OKXCapabilityError(
                f"okx_transport_capability_order_endpoint_disabled:{action}"
            )

    def _assert_capability_unchanged(
        self,
        request: OKXRecordedRequest,
        expected_digest: str,
    ) -> OKXTransportCapabilitySnapshot:
        current = self._current_capability_snapshot()
        if current.capability_digest != expected_digest:
            raise OKXTransportError("okx_transport_capability_changed")
        self._assert_capability_allowed(request, current)
        return current

    def _authorize_dispatch(self, request: OKXRecordedRequest) -> str:
        """Invoke the opaque canonical authorizer immediately before dispatch.

        No local permit is retained.  Missing, malformed, or false decisions
        fail closed and the responder is never called.  The canonical
        authorizer is responsible for reading current runtime state and
        invalidating any state/epoch/current-head change.
        """

        before = self._current_capability_snapshot()
        self._assert_capability_allowed(request, before)
        authorizer = self._canonical_authorizer
        if authorizer is None:
            raise OKXTransportError("okx_canonical_authorizer_missing")
        context: Mapping[str, Any] = {}
        provider = self._canonical_context_provider
        if provider is not None:
            try:
                supplied = provider(request)
            except Exception as exc:
                raise OKXTransportError(
                    f"okx_canonical_context_failed:{type(exc).__name__}"
                ) from exc
            if not isinstance(supplied, Mapping):
                raise OKXTransportError("okx_canonical_context_invalid")
            context = supplied

        method = getattr(authorizer, "authorize_dispatch", None)
        if callable(method):
            try:
                decision = method(request=request)
            except Exception as exc:
                raise OKXTransportError(
                    f"okx_canonical_authorizer_failed:{type(exc).__name__}"
                ) from exc
            if decision is not True:
                raise OKXTransportError("okx_canonical_authorization_denied")
            after = self._current_capability_snapshot()
            if after.capability_digest != before.capability_digest:
                raise OKXTransportError("okx_transport_capability_changed")
            self._assert_capability_allowed(request, after)
            return after.capability_digest

        action = str(context.get("action") or self._action_for_request(request))
        issue = getattr(authorizer, "issue", None)
        if callable(issue):
            required = {
                "order_intent": context.get("order_intent"),
                "risk_decision": context.get("risk_decision"),
            }
            if required["order_intent"] is None or required["risk_decision"] is None:
                raise OKXTransportError("okx_canonical_context_missing_execution_evidence")
            if "risk_evidence" in context:
                required["risk_evidence"] = context.get("risk_evidence")
            try:
                permit = issue(action, **required)
            except Exception as exc:
                raise OKXTransportError(
                    f"okx_canonical_authorization_denied:{type(exc).__name__}"
                ) from exc
            if permit is None or bool(getattr(permit, "revoked", False)):
                raise OKXTransportError("okx_canonical_authorization_denied")
            if not callable(getattr(permit, "valid_for", None)) or not callable(
                getattr(permit, "to_dict", None)
            ):
                raise OKXTransportError("okx_canonical_authorization_not_canonical")
            try:
                permit_record = permit.to_dict()
            except Exception as exc:
                raise OKXTransportError(
                    f"okx_canonical_authorization_invalid:{type(exc).__name__}"
                ) from exc
            if not isinstance(permit_record, Mapping):
                raise OKXTransportError("okx_canonical_authorization_invalid")
            expected_client_order_id = request.client_order_id
            if expected_client_order_id and str(permit_record.get("client_order_id") or "") != expected_client_order_id:
                raise OKXTransportError("okx_canonical_authorization_identity_mismatch")
            if str(permit_record.get("client_order_namespace") or "") != request.client_order_namespace:
                raise OKXTransportError("okx_canonical_authorization_identity_mismatch")
            if str(permit_record.get("account_identity") or "") != request.credential_reference.account_hash:
                raise OKXTransportError("okx_canonical_authorization_identity_mismatch")
            for field_name in ("source_head", "session_id", "key_namespace", "epoch"):
                expected = context.get(field_name)
                if expected is not None and permit_record.get(field_name) != expected:
                    raise OKXTransportError("okx_canonical_authorization_identity_mismatch")
            if permit_record.get("action") not in {None, action}:
                raise OKXTransportError("okx_canonical_authorization_action_mismatch")
            after = self._current_capability_snapshot()
            if after.capability_digest != before.capability_digest:
                raise OKXTransportError("okx_transport_capability_changed")
            self._assert_capability_allowed(request, after)
            return after.capability_digest

        evaluate = getattr(authorizer, "authorize", None)
        if callable(evaluate):
            try:
                decision = evaluate(
                    action,
                    order_intent=context.get("order_intent"),
                    risk_decision=context.get("risk_decision"),
                    risk_evidence=context.get("risk_evidence"),
                    lifecycle=context.get("lifecycle"),
                )
            except Exception as exc:
                raise OKXTransportError(
                    f"okx_canonical_authorizer_failed:{type(exc).__name__}"
                ) from exc
            if getattr(decision, "allowed", None) is not True:
                raise OKXTransportError("okx_canonical_authorization_denied")
            after = self._current_capability_snapshot()
            if after.capability_digest != before.capability_digest:
                raise OKXTransportError("okx_transport_capability_changed")
            self._assert_capability_allowed(request, after)
            return after.capability_digest

        raise OKXTransportError("okx_canonical_authorizer_missing")

    @staticmethod
    def _action_for_request(request: OKXRecordedRequest) -> str:
        path = request.path.lower().split("?", 1)[0]
        if request.method == "GET":
            return "query_broker"
        if path.endswith("/cancel-order") or path.endswith("/cancel-algos"):
            return "cancel_order"
        if path.endswith("/amend-order") or path.endswith("/amend-algos"):
            return "replace_order"
        if "dead-man" in path or "deadman" in path:
            return "dead_man"
        if "algo" in path or "stop-loss" in path or "take-profit" in path:
            return "attach_protection"
        if request.body:
            try:
                body = json.loads(request.body.decode("utf-8"))
            except (TypeError, ValueError, UnicodeDecodeError):
                body = {}
            if isinstance(body, Mapping) and (
                body.get("reduceOnly") is True or body.get("reduce_only") is True
            ):
                return "reduce_only"
        if path.endswith("/close-position") or bool(request.client_order_id and "reduce" in path):
            return "reduce_only"
        return "submit_new_order"

    @property
    def api_base(self) -> str:
        return str(self.config.api_base)

    def request(
        self,
        *,
        method: str,
        path: str,
        body: Mapping[str, Any] | None = None,
        client_order_id: str | None = None,
    ) -> Any:
        normalized_method = str(method).upper()
        normalized_path = _canonical_path(path)
        if normalized_method not in {"GET", "POST", "PUT", "DELETE"}:
            raise OKXCapabilityError("okx_request_method_not_allowed")
        if not normalized_path.startswith("/api/v5/"):
            raise OKXCapabilityError("okx_request_path_not_allowed")
        if _forbidden_capability_path(normalized_path):
            self.withdraw_transfer_accessed = True
            raise OKXCapabilityError("okx_live_withdraw_transfer_forbidden")
        payload = dict(body or {})
        resolved_clord_id = client_order_id or payload.get("clOrdId") or payload.get("client_order_id")
        resolved_clord_id = str(resolved_clord_id) if resolved_clord_id else None
        if _is_order_submit(normalized_path) and not resolved_clord_id:
            raise OKXCapabilityError("okx_order_submit_requires_durable_clordid")
        builder = OKXModeIsolatedRequestBuilder(
            credential_reference=self.config.credential_reference,
            transport=self,
            config=self.config,
        )
        request = builder.build_private_request(
            method=normalized_method,
            path=normalized_path,
            body=payload or None,
        )
        if resolved_clord_id and request.client_order_id != resolved_clord_id:
            request = OKXRecordedRequest(
                **{**request.__dict__, "client_order_id": resolved_clord_id}
            )
        # B capability state is checked before any canonical permit call or
        # local recording.  A canonical A permit cannot override B=false.
        self._assert_capability_allowed(request, self._current_capability_snapshot())
        self.attempts.append((normalized_method, normalized_path))
        # Keep one local recording even when no responder is supplied.  This
        # is not a network dispatch and therefore does not require a live
        # authorization decision.
        self.record(request)
        if self._responder is None:
            return request
        max_attempts = self._max_get_attempts if normalized_method == "GET" else 1
        for attempt in range(1, max_attempts + 1):
            dispatched = request if attempt == 1 else OKXRecordedRequest(
                **{**request.__dict__, "attempt": attempt}
            )
            if attempt > 1:
                # Recording is local and deterministic; authorization is the
                # dispatch fence and is evaluated again for every retry.
                self.record(dispatched)
            authorized_capability_digest = self._authorize_dispatch(dispatched)
            # Final immediate check closes the dispatch TOCTOU window: a
            # capability change after permit acceptance means zero responder
            # calls, even when the canonical permit was true.
            self._assert_capability_unchanged(dispatched, authorized_capability_digest)
            try:
                responder = self._responder
                if callable(responder):
                    return responder(dispatched)
                send = getattr(responder, "send", None)
                if callable(send):
                    return send(dispatched)
                raise TypeError("responder_not_callable")
            except Exception as exc:
                if normalized_method != "GET":
                    if _is_order_submit(normalized_path) and resolved_clord_id:
                        raise OKXAmbiguousSubmitError(resolved_clord_id, exc) from exc
                    raise OKXTransportError(f"okx_non_get_write_failed:{type(exc).__name__}") from exc
                if attempt >= max_attempts:
                    raise OKXTransportError(f"okx_get_failed:{type(exc).__name__}") from exc
        raise AssertionError("unreachable")

    def send(
        self,
        *,
        method: str,
        path: str,
        body: Mapping[str, Any] | None = None,
        client_order_id: str | None = None,
    ) -> Any:
        """Transport-shaped alias; it has exactly the same retry contract."""

        return self.request(
            method=method,
            path=path,
            body=body,
            client_order_id=client_order_id,
        )


class OKXTransportRegistry:
    """Mode registry whose live slot is ``NO_TRANSPORT`` until explicit opt-in."""

    def __init__(
        self,
        *,
        demo_provider: Any | None = None,
        demo_config: OKXModeIsolationConfig | None = None,
        live_config: OKXModeIsolationConfig | None = None,
    ) -> None:
        self._providers: dict[OKXTransportMode, Any | None] = {
            OKXTransportMode.DEMO: demo_provider,
            OKXTransportMode.LIVE: None,
        }
        self._demo_config = demo_config
        self._live_config = live_config
        self._activation_blockers: tuple[str, ...] = ()
        self._live_opt_in: OKXLiveTransportOptIn | None = None

    @classmethod
    def default(cls) -> "OKXTransportRegistry":
        """Return a registry with no live provider and no implicit capabilities."""

        return cls()

    @property
    def live_provider(self) -> Any | None:
        return self._providers[OKXTransportMode.LIVE]

    @property
    def live_opt_in(self) -> OKXLiveTransportOptIn | None:
        return self._live_opt_in

    @property
    def activation_blockers(self) -> tuple[str, ...]:
        return self._activation_blockers

    def _validate_live_pair(
        self,
        *,
        demo_config: OKXModeIsolationConfig | None = None,
        live_config: OKXModeIsolationConfig | None = None,
    ) -> tuple[str, ...]:
        demo = demo_config if demo_config is not None else self._demo_config
        live = live_config if live_config is not None else self._live_config
        if demo is None or live is None:
            return ("okx_live_activation_mode_pair_missing",)
        return tuple(validate_okx_mode_isolation(demo, live))

    def resolve(self, mode: OKXTransportMode | str) -> Any:
        selected_mode = _mode(mode)
        provider = self._providers.get(selected_mode)
        if provider is not None:
            return provider
        return OKXNoTransport() if selected_mode is OKXTransportMode.LIVE else OKXNoTransportForMode(selected_mode)

    def resolve_live(self) -> Any:
        return self.resolve(OKXTransportMode.LIVE)

    def status_for(self, mode: OKXTransportMode | str) -> OKXTransportStatus:
        resolved = self.resolve(mode)
        return getattr(resolved, "status", OKXTransportStatus.AVAILABLE)

    get = resolve
    transport_for = resolve

    def register(
        self,
        mode: OKXTransportMode | str,
        provider: Any,
        *,
        opt_in: OKXLiveTransportOptIn | None = None,
        demo_config: OKXModeIsolationConfig | None = None,
        live_config: OKXModeIsolationConfig | None = None,
    ) -> Any:
        selected_mode = _mode(mode)
        if provider is None:
            raise OKXModeTransportError("okx_provider_missing")
        provider_mode = getattr(provider, "mode", selected_mode)
        if _mode(provider_mode) is not selected_mode:
            raise OKXModeIsolationError("okx_provider_mode_mismatch")
        if selected_mode is OKXTransportMode.LIVE:
            blockers = self._validate_live_pair(
                demo_config=demo_config,
                live_config=live_config,
            )
            if blockers:
                self._activation_blockers = blockers
                self.disable_live()
                return OKXNoTransport()
            if demo_config is not None:
                self._demo_config = demo_config
            if live_config is not None:
                self._live_config = live_config
            provider_config = getattr(provider, "config", None)
            if not isinstance(provider_config, OKXModeIsolationConfig):
                self._activation_blockers = ("okx_live_activation_provider_config_missing",)
                self.disable_live()
                return OKXNoTransport()
            if provider_config != self._live_config:
                self._activation_blockers = ("okx_live_activation_provider_config_mismatch",)
                self.disable_live()
                return OKXNoTransport()
            if opt_in is None or not opt_in.valid():
                raise OKXLiveOptInRequired(";".join(opt_in.blockers() if opt_in else ("okx_live_opt_in_missing",)))
            if bool(getattr(provider, "network_accessed", False)):
                raise OKXCapabilityError("okx_live_provider_network_not_allowed")
            self._live_opt_in = opt_in
            self._activation_blockers = ()
        self._providers[selected_mode] = provider
        return provider

    def register_live(
        self,
        provider: Any,
        *,
        opt_in: OKXLiveTransportOptIn | None = None,
        explicit_opt_in: bool = False,
        ticket: str = "",
        operator: str = "",
        reason: str = "",
        demo_config: OKXModeIsolationConfig | None = None,
        live_config: OKXModeIsolationConfig | None = None,
    ) -> Any:
        if opt_in is None and explicit_opt_in:
            opt_in = OKXLiveTransportOptIn(
                ticket=ticket,
                operator=operator,
                reason=reason,
                confirmed=True,
                read_only=True,
            )
        return self.register(
            OKXTransportMode.LIVE,
            provider,
            opt_in=opt_in,
            demo_config=demo_config,
            live_config=live_config,
        )

    def disable_live(self) -> None:
        self._providers[OKXTransportMode.LIVE] = None
        self._live_opt_in = None

    def capability_matrix(self) -> dict[str, Any]:
        live = self.live_provider
        safety = dict(getattr(live, "safety", {}) or {}) if live is not None else {}
        return {
            "demo_provider_registered": self._providers[OKXTransportMode.DEMO] is not None,
            "live_provider_registered": live is not None,
            "live_status": (
                OKXTransportStatus.AVAILABLE.value
                if live is not None
                else OKXTransportStatus.NO_TRANSPORT.value
            ),
            "live_status_code": (
                "AVAILABLE" if live is not None else "NO_TRANSPORT"
            ),
            "explicit_live_opt_in": self._live_opt_in is not None,
            "activation_blockers": list(self._activation_blockers),
            "mode_isolation_validated": not bool(self._activation_blockers)
            and self._demo_config is not None
            and self._live_config is not None,
            "network_accessed": bool(safety.get("network_accessed", False)),
            "private_endpoint_accessed": bool(safety.get("private_endpoint_accessed", False)),
            "order_endpoint_accessed": bool(safety.get("order_endpoint_accessed", False)),
            "withdraw_transfer_accessed": bool(safety.get("withdraw_transfer_accessed", False)),
            "private_endpoint_allowed": False,
            "order_endpoint_allowed": False,
            "withdraw_allowed": False,
            "transfer_allowed": False,
            "real_order_submitted": False,
            "live_unlock_allowed": False,
        }


@dataclass(frozen=True)
class _ModeNoTransport:
    mode: OKXTransportMode
    status: OKXTransportStatus = OKXTransportStatus.NO_TRANSPORT
    network_accessed: bool = False

    def request(self, **_: Any) -> Any:
        raise OKXTransportUnavailable(f"NO_TRANSPORT:{self.mode.value}_provider_not_registered")

    send = request


def OKXNoTransportForMode(mode: OKXTransportMode) -> _ModeNoTransport:
    return _ModeNoTransport(mode=_mode(mode))


class OKXLocalAttestationVerifier(Protocol):
    """Injected local verifier for a future read-only live preflight.

    This is intentionally separate from the runtime permission contract.  A
    verifier implementation is trusted by injection and must return the
    opaque result issued by its own verifier; strings in the attestation are
    never sufficient to produce a PASS status.
    """

    def verify(self, attestation: "OKXLiveReadOnlyPreflightAttestation") -> Any: ...


_TRUSTED_ATTESTATION_MARKER = object()


@dataclass(frozen=True)
class OKXLocalVerificationResult:
    """Opaque, verifier-issued local attestation result."""

    verifier_id: str
    verification_id: str
    attestation_digest: str
    checked_at_utc: datetime | str | None = None
    _marker: object = field(default=None, repr=False, compare=False)

    @property
    def verified(self) -> bool:
        return self._marker is _TRUSTED_ATTESTATION_MARKER

    @classmethod
    def _issue(
        cls,
        *,
        verifier_id: str,
        verification_id: str,
        attestation_digest: str,
        checked_at_utc: datetime | str | None,
    ) -> "OKXLocalVerificationResult":
        return cls(
            verifier_id=str(verifier_id),
            verification_id=str(verification_id),
            attestation_digest=str(attestation_digest),
            checked_at_utc=checked_at_utc,
            _marker=_TRUSTED_ATTESTATION_MARKER,
        )


class OKXInjectedLocalAttestationVerifier:
    """Deterministic offline verifier used by contract tests only."""

    def __init__(self, *, verifier_id: str = "injected-local-verifier") -> None:
        if not _valid_identifier(verifier_id):
            raise OKXModeTransportError("okx_attestation_verifier_id_invalid")
        self.verifier_id = str(verifier_id)

    def verify(self, attestation: "OKXLiveReadOnlyPreflightAttestation") -> OKXLocalVerificationResult:
        digest = attestation.attestation_digest()
        return OKXLocalVerificationResult._issue(
            verifier_id=self.verifier_id,
            verification_id=f"{self.verifier_id}:{digest[:16]}",
            attestation_digest=digest,
            checked_at_utc=datetime.now(timezone.utc),
        )


@dataclass(frozen=True)
class OKXLiveReadOnlyPreflightAttestation:
    """Local, redacted proof contract for a future live read-only preflight."""

    account_hash: str
    credential_identity: str
    api_base: str = OKX_LIVE_API_BASE
    permission_class: str = OKX_LIVE_READ_ONLY_PERMISSION
    withdraw_permission_disabled: bool = False
    transfer_permission_disabled: bool = False
    ip_whitelist_enforced: bool = False
    expected_ip_whitelist: tuple[str, ...] = ()
    attested_ip_whitelist: tuple[str, ...] = ()
    config_fingerprint: str = ""
    reviewer: str = ""
    reviewed_at_utc: datetime | str | None = None
    approval_ticket: str = ""
    external_proof_id: str = ""
    mode: OKXTransportMode = OKXTransportMode.LIVE
    secrets_read: bool = False
    network_accessed: bool = False
    private_endpoint_accessed: bool = False
    order_endpoint_accessed: bool = False
    live_orders_allowed: bool = False
    _trusted_verification: OKXLocalVerificationResult | None = field(
        default=None,
        repr=False,
        compare=False,
    )

    def attestation_digest(self) -> str:
        """Hash only redacted, immutable attestation inputs."""

        payload = {
            "account_hash": str(self.account_hash),
            "credential_identity": str(self.credential_identity),
            "api_base": str(self.api_base),
            "permission_class": str(self.permission_class),
            "withdraw_permission_disabled": bool(self.withdraw_permission_disabled),
            "transfer_permission_disabled": bool(self.transfer_permission_disabled),
            "ip_whitelist_enforced": bool(self.ip_whitelist_enforced),
            "expected_ip_whitelist": list(self.expected_ip_whitelist),
            "attested_ip_whitelist": list(self.attested_ip_whitelist),
            "config_fingerprint": str(self.config_fingerprint),
            "reviewer": str(self.reviewer),
            "reviewed_at_utc": _as_utc_iso(self.reviewed_at_utc),
            "approval_ticket": str(self.approval_ticket),
            "external_proof_id": str(self.external_proof_id),
            "mode": _mode(self.mode).value,
            "secrets_read": bool(self.secrets_read),
            "network_accessed": bool(self.network_accessed),
            "private_endpoint_accessed": bool(self.private_endpoint_accessed),
            "order_endpoint_accessed": bool(self.order_endpoint_accessed),
            "live_orders_allowed": bool(self.live_orders_allowed),
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def verify_with(self, verifier: OKXLocalAttestationVerifier | None) -> "OKXLiveReadOnlyPreflightAttestation":
        """Attach a verifier-issued result; missing/invalid results stay blocked."""

        method = getattr(verifier, "verify", None) if verifier is not None else None
        if not callable(method):
            return replace(self, _trusted_verification=None)
        try:
            result = method(self)
        except Exception:
            return replace(self, _trusted_verification=None)
        if not isinstance(result, OKXLocalVerificationResult):
            return replace(self, _trusted_verification=None)
        if (
            result.verified is not True
            or not _valid_identifier(result.verifier_id)
            or not str(result.verification_id).strip()
            or result.attestation_digest != self.attestation_digest()
        ):
            return replace(self, _trusted_verification=None)
        return replace(self, _trusted_verification=result)

    def blockers(self) -> tuple[str, ...]:
        blockers: list[str] = []
        if _mode(self.mode) is not OKXTransportMode.LIVE:
            blockers.append("okx_live_attestation_mode_must_be_live")
        if not _valid_hash(self.account_hash):
            blockers.append("okx_live_attestation_account_hash_invalid")
        identity = str(self.credential_identity).strip()
        if not identity:
            blockers.append("okx_live_attestation_credential_identity_missing")
        elif not identity.startswith("quant-system.okx-live."):
            blockers.append("okx_live_attestation_credential_identity_mode_mismatch")
        if str(self.api_base).strip() != OKX_LIVE_API_BASE:
            blockers.append("okx_live_attestation_api_base_mismatch")
        if self.permission_class != OKX_LIVE_READ_ONLY_PERMISSION:
            blockers.append("okx_live_attestation_permission_must_be_data_readonly")
        if self.withdraw_permission_disabled is not True:
            blockers.append("okx_live_attestation_withdraw_must_be_disabled")
        if self.transfer_permission_disabled is not True:
            blockers.append("okx_live_attestation_transfer_must_be_disabled")
        expected = tuple(str(value).strip() for value in self.expected_ip_whitelist if str(value).strip())
        observed = tuple(str(value).strip() for value in self.attested_ip_whitelist if str(value).strip())
        if self.ip_whitelist_enforced is not True:
            blockers.append("okx_live_attestation_ip_whitelist_not_enforced")
        if not expected:
            blockers.append("okx_live_attestation_expected_ip_whitelist_missing")
        if not observed:
            blockers.append("okx_live_attestation_attested_ip_whitelist_missing")
        for label, values in (("expected", expected), ("attested", observed)):
            for value in values:
                try:
                    parsed = ipaddress.ip_address(value)
                except ValueError:
                    blockers.append(f"okx_live_attestation_{label}_ip_invalid:{value}")
                    continue
                if parsed.version not in {4, 6}:
                    blockers.append(f"okx_live_attestation_{label}_ip_invalid:{value}")
        if tuple(sorted(set(expected))) != tuple(sorted(set(observed))):
            blockers.append("okx_live_attestation_ip_whitelist_mismatch")
        if not _FINGERPRINT_RE.fullmatch(str(self.config_fingerprint).strip()):
            blockers.append("okx_live_attestation_config_fingerprint_invalid")
        for name in ("reviewer", "approval_ticket", "external_proof_id"):
            if not str(getattr(self, name)).strip():
                blockers.append(f"okx_live_attestation_{name}_missing")
        if _as_utc_iso(self.reviewed_at_utc) is None:
            blockers.append("okx_live_attestation_reviewed_at_missing")
        if self.secrets_read:
            blockers.append("okx_live_attestation_secrets_read_forbidden")
        if self.network_accessed:
            blockers.append("okx_live_attestation_network_accessed_forbidden")
        if self.private_endpoint_accessed:
            blockers.append("okx_live_attestation_private_endpoint_accessed_forbidden")
        if self.order_endpoint_accessed:
            blockers.append("okx_live_attestation_order_endpoint_accessed_forbidden")
        if self.live_orders_allowed:
            blockers.append("okx_live_attestation_live_orders_must_remain_disabled")
        verification = self._trusted_verification
        if verification is None or verification.verified is not True:
            blockers.append("okx_live_attestation_trusted_local_verification_missing")
        return tuple(dict.fromkeys(blockers))

    def validate(self) -> list[str]:
        return list(self.blockers())

    @property
    def status(self) -> str:
        if self._trusted_verification is None or self._trusted_verification.verified is not True:
            return "BLOCKED_UNVERIFIED"
        return "PASS_READ_ONLY_ATTESTATION" if not self.blockers() else "BLOCKED"

    def to_dict(self) -> dict[str, Any]:
        blockers = list(self.blockers())
        return {
            "schema_version": OKX_LIVE_ATTESTATION_SCHEMA_VERSION,
            "status": self.status,
            "blockers": blockers,
            "mode": _mode(self.mode).value,
            "api_base": self.api_base,
            "permission_class": self.permission_class,
            "credential_identity": self.credential_identity,
            "account_hash": self.account_hash,
            "withdraw_permission_disabled": bool(self.withdraw_permission_disabled),
            "transfer_permission_disabled": bool(self.transfer_permission_disabled),
            "ip_whitelist_enforced": bool(self.ip_whitelist_enforced),
            "expected_ip_whitelist": list(self.expected_ip_whitelist),
            "attested_ip_whitelist": list(self.attested_ip_whitelist),
            "config_fingerprint": self.config_fingerprint,
            "reviewer": self.reviewer,
            "reviewed_at_utc": _as_utc_iso(self.reviewed_at_utc),
            "approval_ticket": self.approval_ticket,
            "external_proof_id": self.external_proof_id,
            "trusted_verifier_id": (
                self._trusted_verification.verifier_id
                if self._trusted_verification is not None
                else ""
            ),
            "verification_id": (
                self._trusted_verification.verification_id
                if self._trusted_verification is not None
                else ""
            ),
            "verification_digest": self.attestation_digest(),
            "secret_fields_allowed": False,
            "secrets_read": bool(self.secrets_read),
            "network_accessed": bool(self.network_accessed),
            "private_endpoint_accessed": bool(self.private_endpoint_accessed),
            "order_endpoint_accessed": bool(self.order_endpoint_accessed),
            "live_orders_allowed": bool(self.live_orders_allowed),
            "live_unlock_allowed": False,
        }


# Descriptive aliases for consumers that prefer the shorter preflight name.
OKXLiveReadOnlyAttestation = OKXLiveReadOnlyPreflightAttestation
OKXLivePreflightAttestation = OKXLiveReadOnlyPreflightAttestation
OKXLiveTransportConfig = OKXModeIsolationConfig
OKXModeIsolation = OKXModeIsolationConfig
OKXLivePermissionAttestation = OKXLiveReadOnlyPreflightAttestation


__all__ = [
    "AmbiguousSubmitError",
    "NoTransportError",
    "OKXAmbiguousSubmitError",
    "OKXCapabilityError",
    "OKXCanonicalAuthorizer",
    "OKXCredentialReference",
    "OKX_DEMO_API_BASE",
    "OKXInjectedResponder",
    "OKXLivePreflightAttestation",
    "OKXLiveReadOnlyAttestation",
    "OKXLiveReadOnlyPreflightAttestation",
    "OKXLocalAttestationVerifier",
    "OKXLocalVerificationResult",
    "OKXInjectedLocalAttestationVerifier",
    "OKXLivePermissionAttestation",
    "OKXLiveTransport",
    "OKXLiveTransportConfig",
    "OKXLiveOptInRequired",
    "OKXLiveTransportOptIn",
    "OKXModeIsolationConfig",
    "OKXModeIsolation",
    "OKXModeIsolationError",
    "OKXModeIsolatedRequestBuilder",
    "OKXModeTransportError",
    "OKXNoTransport",
    "OKXRecordedRequest",
    "OKXRecordingTransport",
    "OKXTransportError",
    "OKXTransportCapabilitySnapshot",
    "OKXTransportMode",
    "OKXTransportRegistry",
    "OKXTransportStatus",
    "OKXTransportUnavailable",
    "OKX_LIVE_API_BASE",
    "OKX_LIVE_ATTESTATION_SCHEMA_VERSION",
    "OKX_LIVE_READ_ONLY_PERMISSION",
    "OKX_LIVE_TRANSPORT_CONTRACT_VERSION",
    "assert_okx_mode_isolated",
    "build_okx_client_order_id",
    "validate_okx_mode_isolation",
]
