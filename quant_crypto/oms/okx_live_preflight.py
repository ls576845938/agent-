"""Offline, read-only OKX live-preflight authority contracts.

This module deliberately has no HTTP, socket, environment, credential-store,
or secret-reading implementation.  ``OKXOfflineFakeReadOnlyPreflightProvider``
is a deterministic fixture for contract tests; it never registers a POST
provider and never unlocks paper, private, order, or live execution.

The receipt type is provider-authority opaque.  It cannot be built by calling a
dataclass constructor or by deserializing a mapping.  A receipt is issued only
by the provider instance that owns its private authority marker, and its digest
binds every identity, policy, permission, egress, expiry, and replay field.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import math
import re
import weakref
from dataclasses import dataclass
from dataclasses import field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence, runtime_checkable


OKX_LIVE_PREFLIGHT_SCHEMA_VERSION = "okx_live_read_only_preflight_v1"
OKX_LIVE_PREFLIGHT_RECEIPT_SCHEMA_VERSION = "okx_live_read_only_receipt_v1"
OKX_LIVE_MODE = "live"
OKX_LIVE_API_BASE = "https://openapi.okx.com"
OKX_DATA_READONLY_PERMISSION = "data_readonly"
OKX_READONLY_PERMISSIONS = frozenset(
    {
        OKX_DATA_READONLY_PERMISSION,
        "account_readonly",
        "market_readonly",
    }
)
_HASH_RE = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?\Z")
_ACCOUNT_HASH_RE = re.compile(r"[0-9a-f]{64}\Z")
_SAFE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_LIVE_CREDENTIAL_PREFIX = "quant-system.okx-live."
_LIVE_CLIENT_NAMESPACE_PREFIX = "btc-okx-live-"
_WILDCARD_IP_TOKENS = frozenset(
    {
        "*",
        "any",
        "all",
        "unrestricted",
        "0/0",
        "0.0.0.0/0",
        "::/0",
    }
)
_WILDCARD_TOKENS = frozenset({"*", "any", "all", "unrestricted", "none"})
_ORDER_PERMISSION_TOKENS = frozenset(
    {
        "order",
        "orders",
        "trade",
        "trading",
        "write",
        "withdraw",
        "transfer",
        "cancel",
        "amend",
    }
)
_AUTHORITY_MARKER = object()


class OKXLivePreflightError(ValueError):
    """A fail-closed preflight request or receipt contract violation."""


class OKXLivePreflightStatus(str):
    """String constants kept local to this standalone contract module."""

    PASS_READ_ONLY = "PASS_READ_ONLY_PREFLIGHT"
    BLOCKED = "BLOCKED"


def _utc(value: datetime | str | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime | str | None) -> str | None:
    parsed = _utc(value)
    return parsed.isoformat() if parsed is not None else None


def _canonical_json(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(
        dict(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _sha256(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _number_text(value: Any) -> str:
    parsed = _number(value)
    return "invalid" if parsed is None else format(parsed, ".12g")


def _is_absolute_state_root(value: str) -> bool:
    text = str(value).strip()
    if not text or any(token in text.lower() for token in _WILDCARD_TOKENS):
        return False
    # Path.is_absolute() is correct on Windows, while the drive-prefix check
    # keeps the contract deterministic if a fixture is inspected elsewhere.
    return Path(text).is_absolute() or bool(re.match(r"^[A-Za-z]:[\\/]", text))


def _normalize_permissions(values: Sequence[str] | frozenset[str] | None) -> tuple[str, ...]:
    if values is None or isinstance(values, (str, bytes)):
        return ()
    try:
        normalized = tuple(sorted(str(value).strip().lower() for value in values))
    except TypeError:
        return ()
    return normalized


def _normalize_ips(values: Sequence[str] | None) -> tuple[str, ...]:
    if values is None or isinstance(values, (str, bytes)):
        return ()
    try:
        result = []
        for value in values:
            text = str(value).strip()
            try:
                parsed = ipaddress.ip_address(text)
            except ValueError:
                result.append(text)
                continue
            result.append(str(parsed))
        return tuple(sorted(result))
    except TypeError:
        return ()


def _ip_blockers(values: Sequence[str] | None, label: str) -> tuple[str, ...]:
    blockers: list[str] = []
    if values is None or isinstance(values, (str, bytes)):
        return (f"{label}_missing",)
    try:
        raw = tuple(str(value).strip() for value in values)
    except TypeError:
        return (f"{label}_missing",)
    if not raw:
        blockers.append(f"{label}_missing")
    if len(raw) != len(set(raw)):
        blockers.append(f"{label}_duplicate")
    for value in raw:
        lowered = value.lower()
        if lowered in _WILDCARD_IP_TOKENS:
            blockers.append(f"{label}_wildcard_forbidden")
            continue
        if "/" in value:
            blockers.append(f"{label}_network_or_range_forbidden")
            continue
        try:
            parsed = ipaddress.ip_address(value)
        except ValueError:
            blockers.append(f"{label}_invalid")
            continue
        if parsed.is_unspecified or parsed.is_multicast:
            blockers.append(f"{label}_wildcard_forbidden")
    return tuple(dict.fromkeys(blockers))


@dataclass(frozen=True)
class OKXLivePreflightPolicy:
    """The mandatory, bounded BTC live-read-only policy facts."""

    instrument_id: str = "BTC-USDT-SWAP"
    margin_mode: str = "isolated"
    leverage: float = 1.0
    max_notional_usdt: float = 10.0
    max_positions: int = 1
    max_active_orders: int = 1
    max_daily_loss_usdt: float = 1.0
    max_daily_new_orders: int = 2
    auto_start: bool = False
    auto_scale: bool = False

    def blockers(self) -> tuple[str, ...]:
        blockers: list[str] = []
        if self.instrument_id != "BTC-USDT-SWAP":
            blockers.append("policy_instrument_must_be_BTC-USDT-SWAP")
        if self.margin_mode != "isolated":
            blockers.append("policy_margin_mode_must_be_isolated")
        if _number(self.leverage) != 1.0:
            blockers.append("policy_leverage_must_be_1x")
        notional = _number(self.max_notional_usdt)
        if notional is None or notional <= 0 or notional > 10.0:
            blockers.append("policy_max_notional_must_be_at_most_10USDT")
        if self.max_positions != 1:
            blockers.append("policy_max_positions_must_be_1")
        if self.max_active_orders != 1:
            blockers.append("policy_max_active_orders_must_be_1")
        loss = _number(self.max_daily_loss_usdt)
        if loss is None or loss != 1.0:
            blockers.append("policy_daily_loss_must_be_1USDT")
        if self.max_daily_new_orders != 2:
            blockers.append("policy_max_daily_new_orders_must_be_2")
        if self.auto_start is not False:
            blockers.append("policy_auto_start_must_be_false")
        if self.auto_scale is not False:
            blockers.append("policy_auto_scale_must_be_false")
        return tuple(dict.fromkeys(blockers))

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "instrument_id": self.instrument_id,
            "margin_mode": self.margin_mode,
            "leverage": _number_text(self.leverage),
            "max_notional_usdt": _number_text(self.max_notional_usdt),
            "max_positions": self.max_positions,
            "max_active_orders": self.max_active_orders,
            "max_daily_loss_usdt": _number_text(self.max_daily_loss_usdt),
            "max_daily_new_orders": self.max_daily_new_orders,
            "auto_start": self.auto_start is True,
            "auto_scale": self.auto_scale is True,
        }

    @property
    def digest(self) -> str:
        return _sha256(self.canonical_payload())

    def to_dict(self) -> dict[str, Any]:
        return dict(self.canonical_payload(), policy_digest=self.digest)


@dataclass(frozen=True)
class OKXLivePreflightRequest:
    """Redacted input presented to a provider authority; never a receipt."""

    current_head: str
    session_id: str
    epoch: int
    mode: str
    api_base: str
    credential_namespace: str
    account_hash: str
    state_root: str
    client_order_namespace: str
    policy: OKXLivePreflightPolicy
    permission_set: tuple[str, ...] = (OKX_DATA_READONLY_PERMISSION,)
    expected_ip_allowlist: tuple[str, ...] = ()
    observed_egress: tuple[str, ...] = ()
    withdraw_allowed: bool | None = None
    transfer_allowed: bool | None = None
    nonce: str = ""
    observed_at_utc: datetime | str | None = None
    # Aliases mirror the repository's existing attestation vocabulary.  The
    # canonical digest fields remain ``expected_ip_allowlist`` and
    # ``observed_egress``.
    expected_ip_whitelist: tuple[str, ...] | None = None
    attested_ip_whitelist: tuple[str, ...] | None = None
    fixed_ip_allowlist: tuple[str, ...] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "current_head", str(self.current_head).strip().lower())
        object.__setattr__(self, "session_id", str(self.session_id).strip())
        object.__setattr__(self, "mode", str(self.mode).strip().lower())
        object.__setattr__(self, "api_base", str(self.api_base).strip())
        object.__setattr__(self, "credential_namespace", str(self.credential_namespace).strip())
        object.__setattr__(self, "account_hash", str(self.account_hash).strip().lower())
        object.__setattr__(self, "state_root", str(self.state_root).strip())
        object.__setattr__(self, "client_order_namespace", str(self.client_order_namespace).strip())
        object.__setattr__(self, "permission_set", _normalize_permissions(self.permission_set))
        expected_ips = (
            self.expected_ip_allowlist
            or self.expected_ip_whitelist
            or self.fixed_ip_allowlist
        )
        observed_ips = self.observed_egress or self.attested_ip_whitelist
        expected_ips = _normalize_ips(expected_ips)
        observed_ips = _normalize_ips(observed_ips)
        object.__setattr__(self, "expected_ip_allowlist", expected_ips)
        object.__setattr__(self, "observed_egress", observed_ips)
        object.__setattr__(self, "expected_ip_whitelist", expected_ips)
        object.__setattr__(self, "attested_ip_whitelist", observed_ips)
        object.__setattr__(self, "fixed_ip_allowlist", expected_ips)
        object.__setattr__(self, "nonce", str(self.nonce).strip())

    @property
    def policy_digest(self) -> str:
        return self.policy.digest if isinstance(self.policy, OKXLivePreflightPolicy) else ""

    @property
    def requested_permissions(self) -> tuple[str, ...]:
        """Compatibility spelling; the bound field remains ``permission_set``."""

        return self.permission_set

    @property
    def permissions(self) -> tuple[str, ...]:
        return self.permission_set

    def blockers(self) -> tuple[str, ...]:
        blockers: list[str] = []
        if not _HASH_RE.fullmatch(self.current_head):
            blockers.append("current_head_missing_or_invalid")
        if not _SAFE_ID_RE.fullmatch(self.session_id):
            blockers.append("session_id_missing_or_invalid")
        if isinstance(self.epoch, bool) or not isinstance(self.epoch, int) or self.epoch <= 0:
            blockers.append("epoch_missing_or_invalid")
        if self.mode != OKX_LIVE_MODE:
            blockers.append("mode_must_be_live")
        if self.api_base != OKX_LIVE_API_BASE:
            blockers.append("live_api_base_mismatch")
        if not self.credential_namespace.startswith(_LIVE_CREDENTIAL_PREFIX):
            blockers.append("credential_namespace_must_be_live")
        if not _SAFE_ID_RE.fullmatch(self.credential_namespace):
            blockers.append("credential_namespace_invalid")
        if any(token in self.credential_namespace.lower() for token in ("secret", "token", "api_key", "passphrase")):
            blockers.append("credential_namespace_must_not_contain_secret")
        if not _ACCOUNT_HASH_RE.fullmatch(self.account_hash):
            blockers.append("account_hash_missing_or_invalid")
        if not _is_absolute_state_root(self.state_root):
            blockers.append("live_state_root_missing_or_not_absolute")
        if not self.client_order_namespace.startswith(_LIVE_CLIENT_NAMESPACE_PREFIX):
            blockers.append("client_order_namespace_must_be_live")
        if not _SAFE_ID_RE.fullmatch(self.client_order_namespace):
            blockers.append("client_order_namespace_invalid")
        if not isinstance(self.policy, OKXLivePreflightPolicy):
            blockers.append("policy_type_invalid")
        else:
            blockers.extend(self.policy.blockers())
        permissions = self.permission_set
        if not permissions:
            blockers.append("permission_set_missing")
        if len(permissions) != len(set(permissions)):
            blockers.append("permission_set_duplicate")
        if any(permission in _WILDCARD_TOKENS for permission in permissions):
            blockers.append("permission_set_wildcard_forbidden")
        if any(permission in _ORDER_PERMISSION_TOKENS for permission in permissions):
            blockers.append("order_or_write_permission_forbidden")
        if any(permission not in OKX_READONLY_PERMISSIONS for permission in permissions):
            blockers.append("permission_set_not_read_only")
        if OKX_DATA_READONLY_PERMISSION not in permissions:
            blockers.append("data_readonly_permission_required")
        blockers.extend(_ip_blockers(self.expected_ip_allowlist, "expected_ip_allowlist"))
        blockers.extend(_ip_blockers(self.observed_egress, "observed_egress"))
        if _normalize_ips(self.expected_ip_allowlist) != _normalize_ips(self.observed_egress):
            blockers.append("expected_observed_egress_mismatch")
        if self.withdraw_allowed is not False:
            blockers.append("withdraw_must_be_explicitly_false")
        if self.transfer_allowed is not False:
            blockers.append("transfer_must_be_explicitly_false")
        if not _SAFE_ID_RE.fullmatch(self.nonce):
            blockers.append("nonce_missing_or_invalid")
        if _utc(self.observed_at_utc) is None:
            blockers.append("observed_at_utc_missing_or_invalid")
        return tuple(dict.fromkeys(blockers))

    def validate(self) -> list[str]:
        return list(self.blockers())

    def binding_payload(
        self,
        *,
        issued_at_utc: str,
        expires_at_utc: str,
    ) -> dict[str, Any]:
        return {
            "schema_version": OKX_LIVE_PREFLIGHT_RECEIPT_SCHEMA_VERSION,
            "current_head": self.current_head,
            "session_id": self.session_id,
            "epoch": self.epoch,
            "mode": self.mode,
            "api_base": self.api_base,
            "credential_namespace": self.credential_namespace,
            "account_hash": self.account_hash,
            "state_root": self.state_root,
            "client_order_namespace": self.client_order_namespace,
            "policy_digest": self.policy_digest,
            "permission_set": list(self.permission_set),
            "expected_ip_allowlist": list(self.expected_ip_allowlist),
            "observed_egress": list(self.observed_egress),
            "withdraw_allowed": self.withdraw_allowed is True,
            "transfer_allowed": self.transfer_allowed is True,
            "order_capability_allowed": False,
            "issued_at_utc": issued_at_utc,
            "expires_at_utc": expires_at_utc,
            "nonce": self.nonce,
        }


@dataclass(frozen=True, init=False, slots=True, weakref_slot=True, eq=False)
class OKXLivePreflightReceipt:
    """Opaque provider-issued receipt; ordinary construction is forbidden."""

    schema_version: str
    current_head: str
    session_id: str
    epoch: int
    mode: str
    api_base: str
    credential_namespace: str
    account_hash: str
    state_root: str
    client_order_namespace: str
    policy_digest: str
    permission_set: tuple[str, ...]
    expected_ip_allowlist: tuple[str, ...]
    observed_egress: tuple[str, ...]
    withdraw_allowed: bool
    transfer_allowed: bool
    order_capability_allowed: bool
    issued_at_utc: str
    expires_at_utc: str
    nonce: str
    digest: str

    def __init__(self, *_: Any, **__: Any) -> None:
        raise TypeError("okx_live_preflight_receipt_provider_issued_only")

    def __copy__(self) -> "OKXLivePreflightReceipt":
        raise TypeError("okx_live_preflight_receipt_copy_forbidden")

    def __deepcopy__(
        self, memo: dict[int, Any] | None = None
    ) -> "OKXLivePreflightReceipt":
        raise TypeError("okx_live_preflight_receipt_deepcopy_forbidden")

    def __reduce__(self) -> Any:
        raise TypeError("okx_live_preflight_receipt_pickle_forbidden")

    def __reduce_ex__(self, protocol: int) -> Any:
        raise TypeError("okx_live_preflight_receipt_pickle_forbidden")

    def _payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "current_head": self.current_head,
            "session_id": self.session_id,
            "epoch": self.epoch,
            "mode": self.mode,
            "api_base": self.api_base,
            "credential_namespace": self.credential_namespace,
            "account_hash": self.account_hash,
            "state_root": self.state_root,
            "client_order_namespace": self.client_order_namespace,
            "policy_digest": self.policy_digest,
            "permission_set": list(self.permission_set),
            "expected_ip_allowlist": list(self.expected_ip_allowlist),
            "observed_egress": list(self.observed_egress),
            "withdraw_allowed": self.withdraw_allowed,
            "transfer_allowed": self.transfer_allowed,
            "order_capability_allowed": self.order_capability_allowed,
            "issued_at_utc": self.issued_at_utc,
            "expires_at_utc": self.expires_at_utc,
            "nonce": self.nonce,
        }

    def digest_valid(self) -> bool:
        return self.digest == _sha256(self._payload())

    @property
    def permissions(self) -> tuple[str, ...]:
        return self.permission_set

    @property
    def fixed_ip_allowlist(self) -> tuple[str, ...]:
        return self.expected_ip_allowlist

    @property
    def expected_ip_whitelist(self) -> tuple[str, ...]:
        return self.expected_ip_allowlist

    @property
    def attested_ip_whitelist(self) -> tuple[str, ...]:
        return self.observed_egress

    def expired(self, now_utc: datetime | str | None) -> bool:
        now = _utc(now_utc)
        expiry = _utc(self.expires_at_utc)
        return now is None or expiry is None or now >= expiry

    def to_dict(self) -> dict[str, Any]:
        """Return a redacted view; there is intentionally no ``from_dict``."""

        return {
            **self._payload(),
            "permissions": list(self.permission_set),
            "fixed_ip_allowlist": list(self.expected_ip_allowlist),
            "digest": self.digest,
            "status": OKXLivePreflightStatus.PASS_READ_ONLY,
            "secrets_read": False,
            "network_accessed": False,
            "private_endpoint_called": False,
            "order_endpoint_called": False,
            "withdraw_called": False,
            "transfer_called": False,
            "live_unlock_allowed": False,
        }


@dataclass(frozen=True, slots=True)
class _IssuedReceiptRecord:
    """Provider-only issuance record; never exposed through the receipt API."""

    nonce: str
    digest: str
    normalized_payload: Any
    receipt_identity: OKXLivePreflightReceipt
    capability: object


@dataclass(slots=True)
class _ProviderState:
    ttl_seconds: int
    issued: dict[str, _IssuedReceiptRecord] = field(default_factory=dict)
    consumed_nonces: set[str] = field(default_factory=set)


_PROVIDER_STATES: weakref.WeakKeyDictionary[object, _ProviderState] = weakref.WeakKeyDictionary()
_RECEIPT_CAPABILITIES: weakref.WeakKeyDictionary[
    OKXLivePreflightReceipt, object
] = weakref.WeakKeyDictionary()
_RECEIPT_OWNERS: weakref.WeakKeyDictionary[OKXLivePreflightReceipt, int] = weakref.WeakKeyDictionary()


def _freeze_payload(value: Any) -> Any:
    """Freeze nested JSON-like values for exact provider-record comparison."""

    if isinstance(value, Mapping):
        return tuple(sorted((str(key), _freeze_payload(item)) for key, item in value.items()))
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_payload(item) for item in value)
    return value


def _provider_state(provider: object) -> _ProviderState | None:
    return _PROVIDER_STATES.get(provider)


@dataclass(frozen=True)
class OKXLivePreflightVerification:
    status: str
    blockers: tuple[str, ...]
    receipt_digest: str = ""
    order_capability_allowed: bool = False

    @property
    def passed(self) -> bool:
        return self.status == OKXLivePreflightStatus.PASS_READ_ONLY and not self.blockers

    @property
    def valid(self) -> bool:
        return self.passed

    @property
    def live_unlock_allowed(self) -> bool:
        return False

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "blockers": list(self.blockers),
            "receipt_digest": self.receipt_digest,
            "order_capability_allowed": False,
            "live_unlock_allowed": False,
        }


@runtime_checkable
class OKXLiveReadOnlyPreflightProvider(Protocol):
    """Provider authority boundary; implementations may be fake-only here."""

    def issue(self, request: OKXLivePreflightRequest) -> OKXLivePreflightReceipt: ...

    def verify(
        self,
        receipt: OKXLivePreflightReceipt | Mapping[str, Any],
        request: OKXLivePreflightRequest,
        *,
        now_utc: datetime | str | None = None,
    ) -> OKXLivePreflightVerification: ...


class OKXOfflineFakeReadOnlyPreflightProvider:
    """Deterministic provider-authority fixture with no network capability."""

    __slots__ = ("__weakref__",)

    def __init__(self, *, ttl_seconds: int = 300) -> None:
        if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, int) or not 0 < ttl_seconds <= 300:
            raise OKXLivePreflightError("ttl_seconds_must_be_1_to_300")
        _PROVIDER_STATES[self] = _ProviderState(ttl_seconds=ttl_seconds)

    @property
    def network_accessed(self) -> bool:
        return False

    @property
    def private_endpoint_called(self) -> bool:
        return False

    @property
    def order_endpoint_called(self) -> bool:
        return False

    @property
    def withdraw_called(self) -> bool:
        return False

    @property
    def transfer_called(self) -> bool:
        return False

    @property
    def post_provider_registered(self) -> bool:
        return False

    @property
    def read_only(self) -> bool:
        return True

    @property
    def safety(self) -> dict[str, bool]:
        return {
            "network_accessed": bool(self.network_accessed),
            "private_endpoint_called": bool(self.private_endpoint_called),
            "order_endpoint_called": bool(self.order_endpoint_called),
            "withdraw_called": bool(self.withdraw_called),
            "transfer_called": bool(self.transfer_called),
            "post_provider_registered": bool(self.post_provider_registered),
            "order_capability_allowed": False,
            "live_unlock_allowed": False,
        }

    def issue(self, request: OKXLivePreflightRequest) -> OKXLivePreflightReceipt:
        state = _provider_state(self)
        if state is None:
            raise OKXLivePreflightError("provider_authority_missing")
        if not isinstance(request, OKXLivePreflightRequest):
            raise OKXLivePreflightError("preflight_request_type_invalid")
        blockers = request.blockers()
        if blockers:
            raise OKXLivePreflightError(";".join(blockers))
        if request.nonce in state.issued or request.nonce in state.consumed_nonces:
            raise OKXLivePreflightError("preflight_nonce_replay")
        issued = _utc(request.observed_at_utc)
        if issued is None:
            raise OKXLivePreflightError("observed_at_utc_missing_or_invalid")
        expires = issued + timedelta(seconds=state.ttl_seconds)
        issued_text = issued.isoformat()
        expires_text = expires.isoformat()
        payload = request.binding_payload(
            issued_at_utc=issued_text,
            expires_at_utc=expires_text,
        )
        receipt = object.__new__(OKXLivePreflightReceipt)
        for name, value in payload.items():
            if name == "permission_set":
                value = tuple(value)
            elif name in {"expected_ip_allowlist", "observed_egress"}:
                value = tuple(value)
            object.__setattr__(receipt, name, value)
        object.__setattr__(receipt, "digest", _sha256(payload))
        capability = object()
        state.issued[request.nonce] = _IssuedReceiptRecord(
            nonce=request.nonce,
            digest=receipt.digest,
            normalized_payload=_freeze_payload(payload),
            receipt_identity=receipt,
            capability=capability,
        )
        _RECEIPT_CAPABILITIES[receipt] = capability
        _RECEIPT_OWNERS[receipt] = id(state)
        return receipt

    def preflight(self, request: OKXLivePreflightRequest) -> OKXLivePreflightReceipt:
        """Read-only spelling for callers that name the operation preflight."""

        return self.issue(request)

    def verify(
        self,
        receipt: OKXLivePreflightReceipt | Mapping[str, Any],
        request: OKXLivePreflightRequest,
        *,
        now_utc: datetime | str | None = None,
    ) -> OKXLivePreflightVerification:
        blockers: list[str] = []
        state = _provider_state(self)
        if state is None:
            blockers.append("provider_authority_missing")
        digest = getattr(receipt, "digest", "") if isinstance(receipt, OKXLivePreflightReceipt) else ""
        if not isinstance(receipt, OKXLivePreflightReceipt):
            blockers.append("receipt_must_be_provider_opaque_instance")
        if not isinstance(request, OKXLivePreflightRequest):
            blockers.append("preflight_request_type_invalid")
        else:
            blockers.extend(request.blockers())
        if isinstance(receipt, OKXLivePreflightReceipt):
            if not receipt.digest_valid():
                blockers.append("receipt_digest_invalid")
            if receipt.schema_version != OKX_LIVE_PREFLIGHT_RECEIPT_SCHEMA_VERSION:
                blockers.append("receipt_schema_version_invalid")
            if receipt.order_capability_allowed is not False:
                blockers.append("data_readonly_cannot_upgrade_order_capability")
            if receipt.withdraw_allowed is not False:
                blockers.append("receipt_withdraw_must_be_false")
            if receipt.transfer_allowed is not False:
                blockers.append("receipt_transfer_must_be_false")
            blockers.extend(_ip_blockers(receipt.expected_ip_allowlist, "receipt_expected_ip_allowlist"))
            blockers.extend(_ip_blockers(receipt.observed_egress, "receipt_observed_egress"))
            if receipt.expected_ip_allowlist != receipt.observed_egress:
                blockers.append("receipt_expected_observed_egress_mismatch")
            record = state.issued.get(receipt.nonce) if state is not None else None
            if record is None:
                if state is not None and _RECEIPT_OWNERS.get(receipt) not in {
                    None,
                    id(state),
                }:
                    blockers.append("receipt_provider_authority_mismatch")
                blockers.append("receipt_nonce_not_issued_by_provider")
            else:
                if record.receipt_identity is not receipt:
                    blockers.append("receipt_object_identity_mismatch")
                capability = _RECEIPT_CAPABILITIES.get(receipt)
                if capability is not record.capability:
                    blockers.append("receipt_opaque_capability_mismatch")
                if record.digest != receipt.digest or record.digest != _sha256(receipt._payload()):
                    blockers.append("receipt_digest_does_not_match_issued_record")
                if record.normalized_payload != _freeze_payload(receipt._payload()):
                    blockers.append("receipt_payload_does_not_match_issued_record")
            if receipt.nonce in (state.consumed_nonces if state is not None else set()):
                blockers.append("receipt_nonce_replay")
            if receipt.expired(now_utc if now_utc is not None else datetime.now(timezone.utc)):
                blockers.append("receipt_expired")
        if isinstance(receipt, OKXLivePreflightReceipt) and isinstance(
            request, OKXLivePreflightRequest
        ):
            expected = request.binding_payload(
                issued_at_utc=receipt.issued_at_utc,
                expires_at_utc=receipt.expires_at_utc,
            )
            if receipt._payload() != expected:
                fields = (
                    "current_head",
                    "session_id",
                    "epoch",
                    "mode",
                    "api_base",
                    "credential_namespace",
                    "account_hash",
                    "state_root",
                    "client_order_namespace",
                    "policy_digest",
                    "permission_set",
                    "expected_ip_allowlist",
                    "observed_egress",
                    "withdraw_allowed",
                    "transfer_allowed",
                    "order_capability_allowed",
                    "issued_at_utc",
                    "expires_at_utc",
                    "nonce",
                )
                for field_name in fields:
                    if _freeze_payload(getattr(receipt, field_name)) != _freeze_payload(
                        expected.get(field_name)
                    ):
                        blockers.append(f"request_{field_name}_mismatch")
        blockers = list(dict.fromkeys(blockers))
        if blockers:
            return OKXLivePreflightVerification(
                status=OKXLivePreflightStatus.BLOCKED,
                blockers=tuple(blockers),
                receipt_digest=str(digest),
                order_capability_allowed=False,
            )
        if state is None:
            return OKXLivePreflightVerification(
                status=OKXLivePreflightStatus.BLOCKED,
                blockers=("provider_authority_missing",),
                receipt_digest=str(digest),
                order_capability_allowed=False,
            )
        state.consumed_nonces.add(receipt.nonce)
        return OKXLivePreflightVerification(
            status=OKXLivePreflightStatus.PASS_READ_ONLY,
            blockers=(),
            receipt_digest=receipt.digest,
            order_capability_allowed=False,
        )

    def verify_receipt(
        self,
        receipt: OKXLivePreflightReceipt | Mapping[str, Any],
        request: OKXLivePreflightRequest,
        *,
        now_utc: datetime | str | None = None,
    ) -> OKXLivePreflightVerification:
        return self.verify(receipt, request, now_utc=now_utc)


# Descriptive aliases for callers that prefer the shorter fake/provider names.
OKXLivePreflightProvider = OKXLiveReadOnlyPreflightProvider
OKXFakeReadOnlyPreflightProvider = OKXOfflineFakeReadOnlyPreflightProvider
OKXLiveReadOnlyPreflightReceipt = OKXLivePreflightReceipt


__all__ = [
    "OKX_DATA_READONLY_PERMISSION",
    "OKX_LIVE_API_BASE",
    "OKX_LIVE_MODE",
    "OKX_LIVE_PREFLIGHT_RECEIPT_SCHEMA_VERSION",
    "OKX_LIVE_PREFLIGHT_SCHEMA_VERSION",
    "OKX_READONLY_PERMISSIONS",
    "OKXFakeReadOnlyPreflightProvider",
    "OKXLivePreflightError",
    "OKXLivePreflightPolicy",
    "OKXLivePreflightProvider",
    "OKXLivePreflightReceipt",
    "OKXLivePreflightRequest",
    "OKXLivePreflightStatus",
    "OKXLivePreflightVerification",
    "OKXLiveReadOnlyPreflightProvider",
    "OKXLiveReadOnlyPreflightReceipt",
    "OKXOfflineFakeReadOnlyPreflightProvider",
]
