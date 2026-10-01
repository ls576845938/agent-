from __future__ import annotations

import hashlib
import math
import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from quant_us.core.clock import utc_now
from quant_us.core.enums import OrderSide, OrderStatus, OrderType, TimeInForce
from quant_us.core.types import AccountState, Fill, Order, Position
from quant_us.execution.broker_base import BrokerBase
from quant_us.execution.ibkr_broker_truth import (
    BrokerTruthSnapshot,
    build_broker_truth_snapshot,
    map_broker_order_identity,
)


IBKR_PAPER_PORTS: tuple[int, ...] = (4002, 7497)
IBKR_LIVE_PORTS: tuple[int, ...] = (4001, 7496)
ALLOWED_IBKR_PAPER_PORTS = IBKR_PAPER_PORTS
IBKR_LIVE_ENDPOINT_PORTS = IBKR_LIVE_PORTS
_ACCOUNT_HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_SECRET_KEY_PATTERN = re.compile(
    r"(api[_-]?key|secret|token|passphrase|password|credential|authorization)",
    re.IGNORECASE,
)


class IBKRPaperAdapterMode(str, Enum):
    """Explicit execution state; the default is deliberately disabled."""

    DISABLED = "disabled"
    READONLY = "readonly"
    PAPER_SUBMIT = "paper-submit"


IBKRAdapterMode = IBKRPaperAdapterMode
IBKRPaperExecutionMode = IBKRPaperAdapterMode


def _coerce_mode(value: IBKRPaperAdapterMode | str) -> IBKRPaperAdapterMode:
    if isinstance(value, IBKRPaperAdapterMode):
        return value
    normalized = str(value).strip().lower().replace("_", "-")
    try:
        return IBKRPaperAdapterMode(normalized)
    except ValueError as exc:
        raise ValueError(f"ibkr_paper_adapter_mode_not_supported:{value}") from exc


@dataclass(frozen=True)
class IBKRPaperExecutionConfig:
    """Configuration for the standalone IBKR paper execution boundary.

    The adapter accepts account hashes only.  It never reads credentials and
    never creates a client by importing a broker SDK.
    """

    mode: IBKRPaperAdapterMode | str = IBKRPaperAdapterMode.DISABLED
    host: str = "127.0.0.1"
    port: int = 7497
    client_id: int = 1
    account_hash_allowlist: tuple[str, ...] = ()
    connect_timeout_seconds: float = 10.0
    reconnect_attempts: int = 3
    reconnect_backoff_seconds: float = 0.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "mode", _coerce_mode(self.mode))
        if isinstance(self.account_hash_allowlist, str):
            values = (self.account_hash_allowlist,)
        else:
            values = tuple(self.account_hash_allowlist)
        normalized = tuple(sorted({str(value).strip().lower() for value in values if value}))
        invalid = [value for value in normalized if not _ACCOUNT_HASH_PATTERN.fullmatch(value)]
        if invalid:
            raise ValueError("ibkr_account_hash_allowlist_requires_sha256_hashes")
        object.__setattr__(self, "account_hash_allowlist", normalized)
        if self.port not in IBKR_PAPER_PORTS and self.port not in IBKR_LIVE_PORTS:
            raise ValueError(f"ibkr_paper_port_not_allowed:{self.port}")
        if self.connect_timeout_seconds < 0:
            raise ValueError("ibkr_connect_timeout_must_be_non_negative")
        if self.reconnect_attempts < 1:
            raise ValueError("ibkr_reconnect_attempts_must_be_positive")
        if self.reconnect_backoff_seconds < 0:
            raise ValueError("ibkr_reconnect_backoff_must_be_non_negative")

    @property
    def allowed_account_hashes(self) -> tuple[str, ...]:
        """Compatibility alias that still exposes hashes, never account IDs."""

        return self.account_hash_allowlist


@dataclass(frozen=True)
class IBKRContractPayload:
    """SDK-neutral contract payload passed to an injected client."""

    symbol: str
    secType: str = "STK"
    exchange: str = "SMART"
    currency: str = "USD"


@dataclass(frozen=True)
class IBKROrderPayload:
    """SDK-neutral order payload with IBKR's wire field names."""

    action: str
    totalQuantity: float
    orderType: str
    tif: str
    orderRef: str
    lmtPrice: float | None = None

    @property
    def client_order_id(self) -> str:
        return self.orderRef

    @property
    def timeInForce(self) -> str:
        return self.tif


@dataclass(frozen=True)
class IBKRCancelPayload:
    orderId: str


@dataclass(frozen=True)
class IBKRStructuredError:
    code: str
    operation: str
    message: str
    retryable: bool = False
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "operation": self.operation,
            "message": self.message,
            "retryable": self.retryable,
            "details": dict(self.details),
        }


class IBKRAdapterError(RuntimeError):
    """Structured, fail-closed adapter error."""

    def __init__(
        self,
        code: str,
        operation: str,
        message: str,
        *,
        retryable: bool = False,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        self.error = IBKRStructuredError(
            code=code,
            operation=operation,
            message=message,
            retryable=retryable,
            details=dict(details or {}),
        )
        super().__init__(f"{code}:{message}")

    @property
    def code(self) -> str:
        return self.error.code

    @property
    def operation(self) -> str:
        return self.error.operation

    @property
    def retryable(self) -> bool:
        return self.error.retryable

    def to_dict(self) -> dict[str, Any]:
        return self.error.to_dict()


def account_id_hash(account_id: str) -> str:
    """Return the allowlist key without retaining or exposing the raw ID."""

    return hashlib.sha256(str(account_id).strip().encode("utf-8")).hexdigest()


def _field(value: Any, *names: str, default: Any = None) -> Any:
    for name in names:
        if isinstance(value, Mapping) and name in value:
            candidate = value[name]
        else:
            candidate = getattr(value, name, None)
        if candidate is not None:
            return candidate
    return default


def _rows(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (str, bytes)):
        return [value]
    try:
        return list(value)
    except TypeError:
        return [value]


def _float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _utc_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    return utc_now()


def _compact_text(value: Any) -> str:
    return " ".join(str(value or "").split())[:500]


def _safe_external_value(value: Any, *, depth: int = 0) -> Any:
    """Keep audit snapshots useful while redacting credential-shaped fields."""

    if depth > 3:
        return "<nested>"
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            lowered_key = key_text.lower()
            if _SECRET_KEY_PATTERN.search(key_text) or lowered_key in {
                "account",
                "account_id",
                "accountid",
                "managedaccounts",
            }:
                result[key_text] = "<redacted>"
            else:
                result[key_text] = _safe_external_value(item, depth=depth + 1)
        return result
    attributes = getattr(value, "__dict__", None)
    if isinstance(attributes, dict):
        return _safe_external_value(attributes, depth=depth + 1)
    return _compact_text(value)


def _normalise_status(value: Any, default: OrderStatus = OrderStatus.UNKNOWN) -> OrderStatus:
    text = re.sub(r"[^a-z]", "", str(value or "").lower())
    if text in {"created", "presubmitted", "pendingsubmit"}:
        return OrderStatus.SUBMITTED
    if text in {"submitted", "accepted", "apipending", "pending"}:
        return OrderStatus.ACCEPTED if text == "accepted" else OrderStatus.SUBMITTED
    if text in {"partiallyfilled", "partialfill", "partial"}:
        return OrderStatus.PARTIALLY_FILLED
    if text in {"filled", "complete", "completed"}:
        return OrderStatus.FILLED
    if text in {"pendingcancel", "cancelpending", "cancelrequested"}:
        return OrderStatus.CANCEL_PENDING
    if text in {"cancelled", "canceled", "apicancelled"}:
        return OrderStatus.CANCELLED
    if text in {"rejected", "inactive", "error", "apierror"}:
        return OrderStatus.REJECTED
    if text in {"expired"}:
        return OrderStatus.EXPIRED
    return default


def _order_type(value: Any) -> OrderType:
    text = str(value or "MKT").upper()
    if text in {"LMT", "LIMIT"}:
        return OrderType.LIMIT
    if text in {"STP", "STOP"}:
        return OrderType.STOP
    return OrderType.MARKET


def _time_in_force(value: Any) -> TimeInForce:
    text = str(value or "DAY").upper()
    return {
        "GTC": TimeInForce.GTC,
        "IOC": TimeInForce.IOC,
        "FOK": TimeInForce.FOK,
    }.get(text, TimeInForce.DAY)


def _side(value: Any) -> OrderSide:
    return OrderSide.SELL if str(value or "BUY").upper() in {"SELL", "SLD"} else OrderSide.BUY


def _is_terminal(status: OrderStatus) -> bool:
    return status in {
        OrderStatus.FILLED,
        OrderStatus.CANCELLED,
        OrderStatus.REJECTED,
        OrderStatus.EXPIRED,
    }


class IBKRPaperExecutionAdapter(BrokerBase):
    """Standalone IBKR paper execution adapter with no automatic wiring.

    Only an injected client is used.  Importing and constructing this class do
    not open sockets, import ``ib_insync``, read credentials, or generate any
    signal, position, or risk decision.
    """

    broker_name = "ibkr_paper_execution"

    def __init__(
        self,
        config: IBKRPaperExecutionConfig,
        *,
        client: Any | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        self._validate_endpoint(config.port)
        if config.mode is not IBKRPaperAdapterMode.DISABLED and not config.account_hash_allowlist:
            raise IBKRAdapterError(
                "account_hash_allowlist_required",
                "constructor",
                "active IBKR paper modes require an account hash allowlist",
            )
        self.config = config
        self.mode = config.mode
        self._client = client
        self._sleep = sleep or time.sleep
        self._connected = False
        self._account_id = ""
        self._account_hash = ""
        self._orders_by_local_id: dict[str, Order] = {}
        self._orders_by_client_id: dict[str, Order] = {}
        self._orders_by_broker_id: dict[str, Order] = {}
        self._raw_orders_by_broker_id: dict[str, Any] = {}
        self._fills_by_id: dict[str, Fill] = {}
        self._external_responses: list[dict[str, Any]] = []
        self._last_error: IBKRStructuredError | None = None
        self._connection_epoch = 0
        self._last_broker_truth: BrokerTruthSnapshot | None = None
        self._global_cancel_audit: list[dict[str, Any]] = []
        self.submit_attempt_count = 0
        self.submit_call_count = 0
        self.cancel_attempt_count = 0
        self.cancel_call_count = 0
        self.global_cancel_attempt_count = 0
        self.global_cancel_call_count = 0

    @staticmethod
    def _validate_endpoint(port: int) -> None:
        if port in IBKR_LIVE_PORTS:
            raise IBKRAdapterError(
                "ibkr_live_endpoint_forbidden",
                "constructor",
                f"live IBKR port is forbidden:{port}",
                details={"port": port, "live_ports": list(IBKR_LIVE_PORTS)},
            )
        if port not in IBKR_PAPER_PORTS:
            raise IBKRAdapterError(
                "ibkr_paper_port_not_allowed",
                "constructor",
                f"only IBKR paper ports are allowed:{port}",
                details={"port": port, "paper_ports": list(IBKR_PAPER_PORTS)},
            )

    @classmethod
    def contract_capabilities(cls) -> dict[str, bool]:
        return {
            "submit_order": True,
            "cancel_order": True,
            "poll_orders": True,
            "sync_open_orders": True,
            "sync_fills": True,
            "sync_account": True,
            "sync_positions": True,
            "reconnect": True,
            "broker_truth_snapshot": True,
            "global_cancel": False,
            "readiness_report": True,
        }

    @property
    def state(self) -> str:
        return self.mode.value

    @property
    def is_disabled(self) -> bool:
        return self.mode is IBKRPaperAdapterMode.DISABLED

    @property
    def is_readonly(self) -> bool:
        return self.mode is IBKRPaperAdapterMode.READONLY

    @property
    def is_paper_submit(self) -> bool:
        return self.mode is IBKRPaperAdapterMode.PAPER_SUBMIT

    @property
    def is_connected(self) -> bool:
        return self._client_is_connected()

    @property
    def account_hash(self) -> str:
        return self._account_hash

    @property
    def connection_epoch(self) -> int:
        """Monotonic broker-session epoch; it advances only after a verified connect."""

        return self._connection_epoch

    @property
    def broker_truth_snapshot(self) -> BrokerTruthSnapshot | None:
        return self._last_broker_truth

    @property
    def last_broker_truth(self) -> BrokerTruthSnapshot | None:
        return self._last_broker_truth

    @property
    def supports_global_cancel(self) -> bool:
        if self._client is None or self.is_disabled or not self.is_paper_submit:
            return False
        return any(
            callable(getattr(self._client, name, None))
            for name in ("reqGlobalCancel", "req_global_cancel", "globalCancel", "global_cancel")
        )

    @property
    def global_cancel_capable(self) -> bool:
        return self.supports_global_cancel

    @property
    def last_error(self) -> IBKRStructuredError | None:
        return self._last_error

    @property
    def external_response_log(self) -> tuple[dict[str, Any], ...]:
        return tuple(dict(item) for item in self._external_responses)

    def readiness_report(self) -> dict[str, Any]:
        submit_state = self.is_paper_submit
        connected = self._client_is_connected()
        account_verified = bool(self._account_hash)
        blocked_reason = ""
        if self.is_disabled:
            blocked_reason = "ibkr_paper_adapter_disabled_fail_closed"
        elif not connected:
            blocked_reason = "ibkr_paper_client_not_connected"
        elif not account_verified:
            blocked_reason = "ibkr_paper_account_not_verified"
        elif not submit_state:
            blocked_reason = "ibkr_paper_readonly_submit_cancel_disabled_fail_closed"
        return {
            "adapter": self.broker_name,
            "state": self.state,
            "mode": self.state,
            "disabled": self.is_disabled,
            "readonly": self.is_readonly,
            "paper_submit": submit_state,
            "paper_only": True,
            "host": self.config.host,
            "port": self.config.port,
            "allowed_ports": list(IBKR_PAPER_PORTS),
            "live_ports_rejected": list(IBKR_LIVE_PORTS),
            "connected": connected,
            "account_allowlist_configured": bool(self.config.account_hash_allowlist),
            "account_verified": account_verified,
            "account_hash": self._account_hash,
            "submit_capable": submit_state,
            "cancel_capable": submit_state,
            "submit_ready": submit_state and connected and account_verified,
            "cancel_ready": submit_state and connected and account_verified,
            "submit_blocked_reason": "" if submit_state and connected and account_verified else blocked_reason,
            "fail_closed": not (submit_state and connected and account_verified),
            "no_auto_connect": True,
            "submit_attempt_count": self.submit_attempt_count,
            "submit_call_count": self.submit_call_count,
            "cancel_attempt_count": self.cancel_attempt_count,
            "cancel_call_count": self.cancel_call_count,
            "global_cancel_capable": self.global_cancel_capable,
            "supports_global_cancel": self.supports_global_cancel,
            "connection_epoch": self._connection_epoch,
            "broker_truth_status": self._last_broker_truth.status if self._last_broker_truth else "unknown",
            "broker_truth_fresh": bool(self._last_broker_truth and self._last_broker_truth.complete),
            "global_cancel_attempt_count": self.global_cancel_attempt_count,
            "global_cancel_call_count": self.global_cancel_call_count,
        }

    def health_check(self) -> dict[str, Any]:
        report = self.readiness_report()
        return {
            "ok": bool(report["connected"] and report["account_verified"]),
            "broker": self.broker_name,
            "state": self.state,
            "connected": report["connected"],
            "account_verified": report["account_verified"],
            "endpoint_kind": "paper",
            "port": self.config.port,
            "readonly": self.is_readonly,
            "submit_capable": report["submit_capable"],
            "cancel_capable": report["cancel_capable"],
            "connection_epoch": self._connection_epoch,
            "broker_truth_status": report["broker_truth_status"],
            "broker_truth_fresh": report["broker_truth_fresh"],
            "global_cancel_capable": report["global_cancel_capable"],
        }

    def _fail(
        self,
        code: str,
        operation: str,
        message: str,
        *,
        retryable: bool = False,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        error = IBKRAdapterError(
            code,
            operation,
            message,
            retryable=retryable,
            details=details,
        )
        self._last_error = error.error
        self._external_responses.append(
            {
                "timestamp_utc": utc_now().isoformat(),
                "operation": operation,
                "status": "error",
                "error": error.to_dict(),
            }
        )
        raise error

    def _record_response(self, operation: str, response: Any, *, status: str = "ok") -> None:
        self._external_responses.append(
            {
                "timestamp_utc": utc_now().isoformat(),
                "operation": operation,
                "status": status,
                "response": _safe_external_value(response),
            }
        )

    def _client_is_connected(self) -> bool:
        if self._client is None:
            return False
        for name in ("isConnected", "is_connected"):
            checker = getattr(self._client, name, None)
            if callable(checker):
                try:
                    return bool(checker())
                except Exception:
                    return False
        connected = getattr(self._client, "connected", None)
        return bool(connected) if connected is not None else self._connected

    def _require_active(self, operation: str) -> None:
        if self.is_disabled:
            self._fail(
                "adapter_disabled",
                operation,
                "IBKR paper execution adapter is disabled by default",
            )
        if self._client is None:
            self._fail(
                "ibkr_paper_client_not_injected",
                operation,
                "an injected client is required; no broker SDK is auto-created",
            )
        if not self._client_is_connected() or not self._connected:
            self._fail(
                "ibkr_paper_client_not_connected",
                operation,
                "connect must be explicitly completed before adapter use",
                retryable=True,
            )
        if not self._account_hash:
            self._fail(
                "ibkr_paper_account_not_verified",
                operation,
                "account identity was not verified against the hash allowlist",
            )

    def _require_write(self, operation: str) -> None:
        self._require_active(operation)
        if not self.is_paper_submit:
            self._fail(
                "paper_submit_disabled_fail_closed",
                operation,
                "submit and cancel require explicit paper-submit mode",
            )

    def _surface(self, names: tuple[str, ...], operation: str) -> tuple[bool, Any]:
        if self._client is None:
            self._fail("ibkr_paper_client_not_injected", operation, "client is not injected")
        for name in names:
            value = getattr(self._client, name, None)
            if callable(value):
                try:
                    return True, value()
                except IBKRAdapterError:
                    raise
                except Exception as exc:
                    duplicate = self._duplicate_code(exc)
                    self._fail(
                        duplicate or f"{operation}_failed",
                        operation,
                        _compact_text(exc),
                        retryable=duplicate is None,
                        details={"exception_type": type(exc).__name__},
                    )
            if value is not None:
                return True, value
        return False, None

    @staticmethod
    def _duplicate_code(exc: BaseException) -> str | None:
        code = _field(exc, "errorCode", "error_code", "code")
        text = str(exc).lower()
        if (
            str(code) in {"326", "501", "507"}
            or re.search(r"\b(?:326|501|507)\b", text)
            or "duplicate client" in text
            or "client id already in use" in text
        ):
            return "duplicate_client_id"
        return None

    @classmethod
    def _connection_error_code(cls, exc: BaseException) -> str:
        """Classify connection failures for bounded, fail-closed reconnect."""

        duplicate = cls._duplicate_code(exc)
        if duplicate:
            return duplicate
        text = str(exc).lower()
        code = str(_field(exc, "errorCode", "error_code", "code", default=""))
        if any(token in text for token in ("authentication", "auth failed", "not authorized", "unauthorized")):
            return "authentication_failed"
        if any(token in text for token in ("configuration", "config error", "invalid config", "bad config")):
            return "configuration_error"
        if code in {"321", "322"} and "account" in text:
            return "account_mismatch"
        return "ibkr_connect_failed"

    def _invoke_connection(self, operation: str) -> Any:
        if self._client is None:
            self._fail("ibkr_paper_client_not_injected", operation, "client is not injected")
        connector = getattr(self._client, "connect", None)
        if not callable(connector):
            self._fail("connect_surface_missing", operation, "injected client has no connect method")
        try:
            return connector(
                self.config.host,
                self.config.port,
                clientId=self.config.client_id,
                readonly=not self.is_paper_submit,
                timeout=self.config.connect_timeout_seconds,
            )
        except Exception as exc:
            code = self._connection_error_code(exc)
            self._fail(
                code,
                operation,
                _compact_text(exc),
                retryable=code not in {
                    "duplicate_client_id",
                    "account_mismatch",
                    "authentication_failed",
                    "configuration_error",
                },
                details={"exception_type": type(exc).__name__},
            )

    def connect(self) -> dict[str, Any]:
        operation = "connect"
        self._require_active_mode(operation)
        if self._client is None:
            self._fail(
                "ibkr_paper_client_not_injected",
                operation,
                "an injected fake/client is required; constructor never connects",
            )
        if self._client_is_connected() and self._connected and self._account_hash:
            self.replay_open_orders()
            return self.readiness_report()
        result = self._invoke_connection(operation)
        if result is False or not self._client_is_connected():
            self._connected = False
            self._fail(
                "ibkr_connect_failed",
                operation,
                "injected client did not report a connected paper session",
                retryable=True,
            )
        self._connected = True
        try:
            self._verify_account()
            self.replay_open_orders()
        except IBKRAdapterError:
            self._safe_disconnect()
            raise
        self._connection_epoch += 1
        self._capture_broker_truth()
        self._record_response(operation, {"connected": True, "readonly": not self.is_paper_submit})
        return self.readiness_report()

    def _require_active_mode(self, operation: str) -> None:
        if self.is_disabled:
            self._fail(
                "adapter_disabled",
                operation,
                "disabled mode cannot connect or access a broker client",
            )
        if not self.config.account_hash_allowlist:
            self._fail(
                "account_hash_allowlist_required",
                operation,
                "account hash allowlist is required before connection",
            )

    def _discover_account_ids(self) -> list[str]:
        if self._client is None:
            return []
        identities: set[str] = set()
        found, summary = self._surface(("accountSummary", "account_summary"), "account_identity")
        if found:
            for row in _rows(summary):
                account = _field(row, "account", "account_id", "accountId", default="")
                if account:
                    identities.add(str(account).strip())
        if not identities:
            for name in ("managedAccounts", "managed_accounts"):
                value = getattr(self._client, name, None)
                if callable(value):
                    try:
                        value = value()
                    except Exception as exc:
                        self._fail(
                            "account_identity_failed",
                            "account_identity",
                            _compact_text(exc),
                            retryable=True,
                            details={"exception_type": type(exc).__name__},
                        )
                if isinstance(value, str):
                    identities.update(item.strip() for item in value.split(",") if item.strip())
                elif value is not None:
                    identities.update(str(item).strip() for item in _rows(value) if str(item).strip())
        if not identities:
            account = _field(self._client, "account_id", "accountId", default="")
            if account:
                identities.add(str(account).strip())
        return sorted(identities)

    def _verify_account(self) -> None:
        operation = "account_identity"
        account_ids = self._discover_account_ids()
        if not account_ids:
            self._fail(
                "account_identity_unavailable",
                operation,
                "connected client did not provide an account identity",
            )
        if len(account_ids) != 1:
            hashes = [account_id_hash(account_id) for account_id in account_ids]
            self._fail(
                "account_identity_ambiguous",
                operation,
                "exactly one account identity is required for fail-closed execution",
                details={"account_hashes": hashes},
            )
        candidate_hash = account_id_hash(account_ids[0])
        if candidate_hash not in set(self.config.account_hash_allowlist):
            self._fail(
                "account_not_allowlisted",
                operation,
                "connected account hash is not in the configured allowlist",
                details={"account_hash": candidate_hash},
            )
        self._account_id = account_ids[0]
        self._account_hash = candidate_hash

    def _safe_disconnect(self) -> None:
        self._connected = False
        self._last_broker_truth = None
        if self._client is None:
            return
        for name in ("disconnect",):
            method = getattr(self._client, name, None)
            if callable(method):
                try:
                    method()
                except Exception:
                    pass
                break
        self._account_id = ""
        self._account_hash = ""

    def disconnect(self) -> None:
        self._safe_disconnect()

    def reconnect(self, *, max_attempts: int | None = None) -> dict[str, Any]:
        operation = "reconnect"
        self._require_active_mode(operation)
        attempts = max_attempts if max_attempts is not None else self.config.reconnect_attempts
        if attempts < 1:
            self._fail("reconnect_attempts_invalid", operation, "max_attempts must be positive")
        last_error: IBKRAdapterError | None = None
        self._safe_disconnect()
        for attempt in range(1, attempts + 1):
            try:
                report = self.connect()
                self._record_response(operation, {"attempt": attempt, "connected": True})
                return report
            except IBKRAdapterError as exc:
                last_error = exc
                if not exc.retryable or exc.code in {
                    "duplicate_client_id",
                    "account_not_allowlisted",
                    "account_identity_ambiguous",
                    "account_identity_unavailable",
                    "account_mismatch",
                    "authentication_failed",
                    "configuration_error",
                }:
                    raise
                if attempt < attempts and self.config.reconnect_backoff_seconds:
                    self._sleep(self.config.reconnect_backoff_seconds)
        assert last_error is not None
        self._fail(
            "reconnect_failed",
            operation,
            "bounded reconnect attempts exhausted",
            retryable=True,
            details={"attempts": attempts, "last_error": last_error.to_dict()},
        )

    def _truth_surface(self, names: tuple[str, ...]) -> tuple[bool, Any, str]:
        """Read one injected broker surface without turning a partial snapshot into success."""

        if self._client is None:
            return False, None, "client_not_injected"
        for name in names:
            value = getattr(self._client, name, None)
            if callable(value):
                try:
                    return True, value(), ""
                except Exception as exc:
                    return False, None, f"surface_error:{name}:{type(exc).__name__}"
            if value is not None:
                return True, value, ""
        return False, None, "surface_missing"

    def _truth_client_value(self, names: tuple[str, ...], default: Any = None) -> Any:
        if self._client is None:
            return default
        for name in names:
            value = getattr(self._client, name, None)
            if callable(value):
                try:
                    value = value()
                except Exception:
                    continue
            if value is not None:
                return value
        return default

    @staticmethod
    def _truth_account_values(rows: Any) -> tuple[float | None, float | None, float | None, float | None]:
        cash: float | None = None
        net_liquidation: float | None = None
        buying_power: float | None = None
        margin: float | None = None
        for row in _rows(rows):
            tag = str(_field(row, "tag", default="")).strip().lower().replace("_", "")
            value = _field(row, "value", default=None)
            number = _float(value, default=0.0) if value is not None else None
            if tag in {"totalcashvalue", "cashbalance", "availablefunds", "cash"}:
                cash = number
            elif tag in {"netliquidation", "netliquidationvalue", "equity"}:
                net_liquidation = number
            elif tag in {"buyingpower", "buyingpowervalue"}:
                buying_power = number
            elif tag in {"maintmarginreq", "totalmaintmarginreq", "margin", "marginrequirement"}:
                margin = number
        return cash, net_liquidation, buying_power, margin

    def _capture_broker_truth(self) -> BrokerTruthSnapshot:
        """Capture a best-effort immutable snapshot; missing surfaces stay blocked."""

        self._require_active("broker_truth_snapshot")
        captured_at = utc_now()
        found_orders, raw_orders, orders_error = self._truth_surface(
            ("openTrades", "open_trades", "openOrders", "open_orders")
        )
        found_executions, raw_executions, executions_error = self._truth_surface(
            ("fills", "executions", "fill_records")
        )
        found_positions, raw_positions, positions_error = self._truth_surface(
            ("positions", "position_records")
        )
        found_account, raw_account, account_error = self._truth_surface(
            ("accountSummary", "account_summary")
        )
        cash, net_liquidation, buying_power, margin = self._truth_account_values(raw_account)
        flags: list[str] = []
        if not found_orders:
            flags.append("orders_snapshot_incomplete")
        if not found_executions:
            flags.append("executions_snapshot_incomplete")
        if not found_positions:
            flags.append("positions_snapshot_incomplete")
        if not found_account or cash is None or net_liquidation is None or buying_power is None:
            flags.append("account_snapshot_incomplete")
        for error in (orders_error, executions_error, positions_error, account_error):
            if error and not error.endswith(":") and "missing" not in error:
                flags.append(error)

        transport_connected = self._client_is_connected()
        account_verified = bool(self._account_hash) and transport_connected
        raw_sequence_watermark = self._truth_client_value(
            ("sequence_watermark", "snapshot_sequence", "sequence")
        )
        sequence_watermark = _field(raw_sequence_watermark, "value", default=raw_sequence_watermark)
        sequence_watermark = _float(sequence_watermark, default=0.0) if sequence_watermark is not None else None
        if sequence_watermark is not None and float(sequence_watermark).is_integer():
            sequence_watermark = int(sequence_watermark)
        raw_server_time = self._truth_client_value(("broker_server_time", "server_time", "serverTime"))
        broker_server_time = _field(raw_server_time, "value", default=raw_server_time)
        freshness = self._truth_client_value(("broker_truth_freshness", "truth_freshness", "freshness"), "fresh")
        snapshot = build_broker_truth_snapshot(
            connection_epoch=self._connection_epoch,
            captured_at=captured_at,
            broker_server_time=broker_server_time or captured_at,
            client_id=self.config.client_id,
            account_hash=self._account_hash,
            transport_connected=transport_connected,
            account_verified=account_verified,
            open_orders=raw_orders if found_orders else (),
            executions=raw_executions if found_executions else (),
            positions=raw_positions if found_positions else (),
            cash=cash,
            net_liquidation=net_liquidation,
            buying_power=buying_power,
            margin=margin,
            orders_snapshot_complete=found_orders,
            executions_snapshot_complete=found_executions,
            positions_snapshot_complete=found_positions,
            account_snapshot_complete=found_account and cash is not None and net_liquidation is not None and buying_power is not None,
            sequence_watermark=sequence_watermark,
            freshness=freshness,
            expected_connection_epoch=self._connection_epoch,
            status_flags=tuple(flags),
        )
        self._last_broker_truth = snapshot
        self._record_response("broker_truth_snapshot", snapshot.to_dict())
        return snapshot

    def capture_broker_truth(self) -> BrokerTruthSnapshot:
        return self._capture_broker_truth()

    def sync_broker_truth(self) -> BrokerTruthSnapshot:
        return self._capture_broker_truth()

    def snapshot_broker_truth(self) -> BrokerTruthSnapshot:
        return self._capture_broker_truth()

    def get_broker_truth(self) -> BrokerTruthSnapshot:
        return self._last_broker_truth or self._capture_broker_truth()

    def accept_broker_truth(self, snapshot: BrokerTruthSnapshot) -> BrokerTruthSnapshot:
        """Accept an injected snapshot only when it belongs to this session/account."""

        operation = "accept_broker_truth"
        self._require_active(operation)
        if not isinstance(snapshot, BrokerTruthSnapshot):
            self._fail("invalid_broker_truth_snapshot", operation, "snapshot must be BrokerTruthSnapshot")
        if snapshot.connection_epoch != self._connection_epoch:
            self._fail(
                "epoch_mismatch",
                operation,
                "broker truth belongs to a different connection epoch",
                details={"expected_epoch": self._connection_epoch, "received_epoch": snapshot.connection_epoch},
            )
        if snapshot.account_hash != self._account_hash:
            self._fail(
                "account_mismatch",
                operation,
                "broker truth account hash does not match the verified session",
            )
        previous = self._last_broker_truth
        if previous and previous.sequence_watermark is not None and snapshot.sequence_watermark is not None:
            if snapshot.sequence_watermark == previous.sequence_watermark:
                self._fail("duplicate_broker_truth", operation, "broker truth sequence was replayed")
            if snapshot.sequence_watermark < previous.sequence_watermark:
                self._fail("sequence_regression", operation, "broker truth sequence regressed")
            if snapshot.sequence_watermark > previous.sequence_watermark + 1:
                self._fail("sequence_gap", operation, "broker truth sequence gap detected")
        self._last_broker_truth = snapshot
        return snapshot

    ingest_broker_truth = accept_broker_truth

    def _call_global_cancel(self) -> Any:
        if self._client is None:
            self._fail("ibkr_paper_client_not_injected", "global_cancel", "client is not injected")
        for name in ("reqGlobalCancel", "req_global_cancel", "globalCancel", "global_cancel"):
            method = getattr(self._client, name, None)
            if callable(method):
                self.global_cancel_call_count += 1
                try:
                    return method()
                except Exception as exc:
                    self._fail(
                        "global_cancel_request_failed",
                        "global_cancel",
                        _compact_text(exc),
                        retryable=True,
                        details={"exception_type": type(exc).__name__},
                    )
        self._fail("global_cancel_surface_missing", "global_cancel", "injected client has no global cancel method")

    @staticmethod
    def _run_gate_callback(callback: Any, response: Any) -> bool:
        if isinstance(callback, bool):
            return callback
        if callable(callback):
            try:
                result = callback(response)
            except TypeError:
                result = callback()
            return result is not False
        return False

    def request_global_cancel(
        self,
        reason: str,
        policy_authorized: bool = False,
        operator_authorized: bool = False,
        audit: Any = None,
        confirmation: Any = None,
        reconciliation: Any = None,
        confirm: Any = None,
        reconcile: Any = None,
        audit_event: Any = None,
        confirmation_callback: Any = None,
        reconciliation_callback: Any = None,
        policy_authorization: bool | None = None,
        operator_authorization: bool | None = None,
    ) -> dict[str, Any]:
        """Explicit emergency capability; disconnect never calls this method."""

        operation = "global_cancel"
        self.global_cancel_attempt_count += 1
        self._require_write(operation)
        reason_text = str(reason or "").strip()
        if policy_authorization is not None:
            policy_authorized = bool(policy_authorization)
        if operator_authorization is not None:
            operator_authorized = bool(operator_authorization)
        audit = audit if audit is not None else audit_event
        confirmation = confirmation if confirmation is not None else confirmation_callback
        reconciliation = reconciliation if reconciliation is not None else reconciliation_callback
        if not reason_text:
            self._fail("global_cancel_reason_required", operation, "an explicit emergency reason is required")
        if not policy_authorized or not operator_authorized:
            self._fail(
                "global_cancel_authorization_required",
                operation,
                "policy and operator authorization are both required",
            )
        if audit is None:
            self._fail("global_cancel_audit_required", operation, "an audit sink is required")
        confirmation = confirmation if confirmation is not None else confirm
        reconciliation = reconciliation if reconciliation is not None else reconcile
        if confirmation is None:
            self._fail("global_cancel_confirmation_required", operation, "explicit cancellation confirmation is required")
        if reconciliation is None:
            self._fail("global_cancel_reconciliation_required", operation, "post-cancel reconciliation is required")

        event = {
            "operation": operation,
            "reason": reason_text,
            "connection_epoch": self._connection_epoch,
            "account_hash": self._account_hash,
            "policy_authorized": True,
            "operator_authorized": True,
        }
        try:
            if callable(audit):
                audit_result = audit(dict(event))
            elif hasattr(audit, "record") and callable(audit.record):
                audit_result = audit.record(dict(event))
            elif hasattr(audit, "append") and callable(audit.append):
                audit_result = audit.append(dict(event))
            elif isinstance(audit, Mapping):
                audit_result = True
            else:
                audit_result = False
        except Exception as exc:
            self._fail("global_cancel_audit_failed", operation, _compact_text(exc))
        if audit_result is False:
            self._fail("global_cancel_audit_failed", operation, "audit sink rejected the emergency request")
        self._global_cancel_audit.append(dict(event))

        response = self._call_global_cancel()
        self._record_response(operation, response)
        confirmed = self._run_gate_callback(confirmation, response)
        reconciled = self._run_gate_callback(reconciliation, response)
        if not confirmed:
            self._fail("global_cancel_confirmation_failed", operation, "cancellation was not explicitly confirmed")
        if not reconciled:
            self._fail("global_cancel_reconciliation_failed", operation, "post-cancel reconciliation did not pass")
        result = {
            "operation": operation,
            "accepted": True,
            "confirmed": True,
            "reconciled": True,
            "reason": reason_text,
            "connection_epoch": self._connection_epoch,
            "account_hash": self._account_hash,
            "audit_recorded": True,
            "response": _safe_external_value(response),
        }
        self._global_cancel_audit.append({**event, "accepted": True, "confirmed": True, "reconciled": True})
        return result

    global_cancel = request_global_cancel

    def _call_place_order(self, contract: IBKRContractPayload, payload: IBKROrderPayload) -> Any:
        if self._client is None:
            self._fail("ibkr_paper_client_not_injected", "submit_order", "client is not injected")
        for name in ("placeOrder", "place_order"):
            method = getattr(self._client, name, None)
            if callable(method):
                try:
                    self.submit_call_count += 1
                    return method(contract, payload)
                except Exception as exc:
                    duplicate = self._duplicate_code(exc)
                    text = str(exc).lower()
                    if duplicate is None and "duplicate" in text and "order" in text:
                        duplicate = "duplicate_client_order_ref"
                    self._fail(
                        duplicate or "submit_request_failed",
                        "submit_order",
                        _compact_text(exc),
                        retryable=False,
                        details={"exception_type": type(exc).__name__},
                    )
        self._fail("submit_surface_missing", "submit_order", "injected client has no place-order method")

    def _call_cancel_order(self, payload: Any) -> Any:
        if self._client is None:
            self._fail("ibkr_paper_client_not_injected", "cancel_order", "client is not injected")
        for name in ("cancelOrder", "cancel_order"):
            method = getattr(self._client, name, None)
            if callable(method):
                try:
                    self.cancel_call_count += 1
                    return method(payload)
                except Exception as exc:
                    self._fail(
                        "cancel_request_failed",
                        "cancel_order",
                        _compact_text(exc),
                        retryable=True,
                        details={"exception_type": type(exc).__name__},
                    )
        self._fail("cancel_surface_missing", "cancel_order", "injected client has no cancel-order method")

    def _build_payload(self, order: Order) -> tuple[IBKRContractPayload, IBKROrderPayload]:
        if not isinstance(order, Order):
            self._fail("invalid_order", "submit_order", "submit_order accepts quant_us.core.types.Order")
        if not order.client_order_id:
            self._fail("client_order_id_required", "submit_order", "broker orderRef is required for idempotency")
        if not order.symbol or order.quantity <= 0 or not math.isfinite(float(order.quantity)):
            self._fail("invalid_order_quantity", "submit_order", "order quantity must be positive and finite")
        if order.order_type not in {OrderType.MARKET, OrderType.LIMIT}:
            self._fail("order_type_not_supported", "submit_order", "IBKR paper adapter supports market and limit only")
        if order.time_in_force is not TimeInForce.DAY:
            self._fail("time_in_force_not_supported", "submit_order", "IBKR paper adapter supports DAY only")
        if order.order_type is OrderType.LIMIT:
            if order.limit_price is None or order.limit_price <= 0 or not math.isfinite(float(order.limit_price)):
                self._fail("limit_price_required", "submit_order", "limit orders require a positive finite limit price")
        order_type = "MKT" if order.order_type is OrderType.MARKET else "LMT"
        contract = IBKRContractPayload(symbol=order.symbol.upper())
        payload = IBKROrderPayload(
            action="SELL" if order.side is OrderSide.SELL else "BUY",
            totalQuantity=float(order.quantity),
            orderType=order_type,
            tif="DAY",
            orderRef=order.client_order_id,
            lmtPrice=float(order.limit_price) if order.limit_price is not None else None,
        )
        return contract, payload

    def _same_order_identity(self, left: Order, right: Order) -> bool:
        return (
            left.symbol.upper() == right.symbol.upper()
            and left.side is right.side
            and math.isclose(float(left.quantity), float(right.quantity))
            and left.order_type is right.order_type
            and left.time_in_force is right.time_in_force
            and (
                left.limit_price is None
                and right.limit_price is None
                or left.limit_price is not None
                and right.limit_price is not None
                and math.isclose(float(left.limit_price), float(right.limit_price))
            )
        )

    def submit_order(self, order: Order) -> Order:
        operation = "submit_order"
        self.submit_attempt_count += 1
        self._require_write(operation)
        contract, payload = self._build_payload(order)
        self.replay_open_orders()
        existing = self._orders_by_client_id.get(order.client_order_id)
        if existing is not None:
            if not self._same_order_identity(existing, order):
                self._fail(
                    "duplicate_client_order_ref",
                    operation,
                    "client_order_id already maps to a different order fingerprint",
                    details={"client_order_id": order.client_order_id},
                )
            return existing
        response = self._call_place_order(contract, payload)
        self._record_response(operation, response)
        broker_order_id = str(
            _field(
                response,
                "orderId",
                "order_id",
                default=_field(_field(response, "order", default=None), "orderId", "order_id", default=""),
            )
        )
        if not broker_order_id:
            self._fail(
                "submit_ack_missing_broker_order_id",
                operation,
                "broker acknowledgement did not contain an order ID",
                retryable=True,
            )
        status_source = _field(response, "orderStatus", "status", default=response)
        status = _normalise_status(_field(status_source, "status", default=status_source), OrderStatus.SUBMITTED)
        order.broker_order_id = broker_order_id
        order.status = status if status is not OrderStatus.UNKNOWN else OrderStatus.SUBMITTED
        order.updated_at = utc_now()
        self._update_order_metadata(order, response)
        self._remember_order(order, response)
        if order.status is OrderStatus.REJECTED:
            self._last_error = IBKRStructuredError(
                code="broker_order_rejected",
                operation=operation,
                message="broker acknowledged the order as rejected",
                details=self._reject_details(response),
            )
        return order

    def cancel_order(self, order_id: str) -> Order:
        operation = "cancel_order"
        self.cancel_attempt_count += 1
        self._require_write(operation)
        self.replay_open_orders()
        order = self._resolve_order(order_id)
        if order is None:
            self._fail("order_not_found", operation, "no local or replayed broker order matches the identifier")
        if _is_terminal(order.status):
            return order
        if order.status is OrderStatus.CANCEL_PENDING:
            return order
        broker_id = order.broker_order_id
        if not broker_id:
            self._fail("broker_order_id_required", operation, "cancel requires a broker order ID")
        order.status = OrderStatus.CANCEL_PENDING
        order.updated_at = utc_now()
        raw_payload = self._raw_orders_by_broker_id.get(broker_id)
        payload = raw_payload if raw_payload is not None else IBKRCancelPayload(orderId=broker_id)
        response = self._call_cancel_order(payload)
        self._record_response(operation, response)
        status_source = _field(response, "orderStatus", "status", default=response)
        status = _normalise_status(
            _field(status_source, "status", default=status_source),
            OrderStatus.CANCEL_PENDING,
        )
        if status is OrderStatus.REJECTED:
            order.status = OrderStatus.ERROR
            self._update_order_metadata(order, response)
            self._fail(
                "cancel_rejected",
                operation,
                "broker rejected the cancellation request",
                details=self._reject_details(response),
            )
        order.status = status if status is not OrderStatus.UNKNOWN else OrderStatus.CANCEL_PENDING
        order.updated_at = utc_now()
        self._update_order_metadata(order, response)
        self._remember_order(order, response)
        return order

    def _resolve_order(self, order_id: str) -> Order | None:
        key = str(order_id)
        return (
            self._orders_by_local_id.get(key)
            or self._orders_by_broker_id.get(key)
            or self._orders_by_client_id.get(key)
        )

    def _reject_details(self, raw: Any) -> dict[str, Any]:
        source = _field(raw, "orderStatus", "error", default=raw)
        code = _field(source, "errorCode", "error_code", "code", "rejectCode", "reject_code", default="")
        reason = _field(source, "whyHeld", "reason", "rejectReason", "reject_reason", default="")
        return {
            "reject_code": _compact_text(code),
            "reject_reason": _compact_text(reason),
            "raw": _safe_external_value(source),
        }

    def _update_order_metadata(self, order: Order, raw: Any) -> None:
        status_source = _field(raw, "orderStatus", default=raw)
        filled = _field(status_source, "filled", "filledQuantity", "filled_quantity", default=None)
        remaining = _field(status_source, "remaining", "remainingQuantity", "remaining_quantity", default=None)
        if filled is not None:
            order.metadata["broker_reported_filled_quantity"] = _float(filled)
            order.metadata["filled_quantity"] = _float(filled)
        if remaining is not None:
            order.metadata["remaining_quantity"] = _float(remaining)
        avg_price = _field(status_source, "avgFillPrice", "avg_fill_price", default=None)
        if avg_price is not None:
            order.metadata["average_fill_price"] = _float(avg_price)
        if order.status is OrderStatus.REJECTED:
            order.metadata["reject"] = self._reject_details(raw)
        order.metadata["ibkr_order_ref"] = order.client_order_id
        identity = map_broker_order_identity(
            raw,
            client_id=self.config.client_id,
            internal_order_id=order.order_id,
            strategy_order_id=order.strategy_id,
        )
        order.metadata["ibkr_order_id"] = identity.ibkr_order_id
        order.metadata["ibkr_perm_id"] = identity.ibkr_perm_id
        order.metadata["ibkr_client_id"] = identity.client_id
        order.metadata["broker_order_stable_key"] = identity.stable_key
        order.metadata["connection_epoch"] = self._connection_epoch
        order.metadata["ibkr_response"] = _safe_external_value(raw)

    def _remember_order(self, order: Order, raw: Any | None = None) -> None:
        self._orders_by_local_id[order.order_id] = order
        if order.client_order_id:
            self._orders_by_client_id[order.client_order_id] = order
        if order.broker_order_id:
            self._orders_by_broker_id[order.broker_order_id] = order
            if raw is not None:
                self._raw_orders_by_broker_id[order.broker_order_id] = _field(
                    raw,
                    "order",
                    default=raw,
                )

    def replay_open_orders(self) -> list[Order]:
        operation = "open_order_replay"
        self._require_active(operation)
        found, raw_orders = self._surface(
            ("openTrades", "open_trades", "openOrders", "open_orders"),
            operation,
        )
        if not found:
            self._fail(
                "open_order_replay_surface_missing",
                operation,
                "injected client must expose open orders for idempotent execution",
            )
        replayed: list[Order] = []
        for raw in _rows(raw_orders):
            candidate = self._map_order(raw)
            existing = self._orders_by_client_id.get(candidate.client_order_id)
            if existing is not None:
                if not self._same_order_identity(existing, candidate):
                    self._fail(
                        "duplicate_client_order_ref",
                        operation,
                        "open-order replay found the same orderRef with a different fingerprint",
                        details={"client_order_id": candidate.client_order_id},
                    )
                existing.broker_order_id = candidate.broker_order_id or existing.broker_order_id
                existing.status = candidate.status
                existing.metadata.update(candidate.metadata)
                self._remember_order(existing, raw)
                replayed.append(existing)
                continue
            self._remember_order(candidate, raw)
            replayed.append(candidate)
        self._record_response(operation, {"count": len(replayed), "orders": replayed})
        return replayed

    def sync_open_orders(self) -> list[Order]:
        return self.replay_open_orders()

    def poll_orders(self) -> list[Order]:
        return self.sync_open_orders()

    def get_open_orders(self) -> list[Order]:
        return self.sync_open_orders()

    def get_orders(self) -> list[Order]:
        self._require_active("get_orders")
        self.replay_open_orders()
        return list(self._orders_by_local_id.values())

    def sync_fills(self, order_id: str | None = None) -> list[Fill]:
        operation = "sync_fills"
        self._require_active(operation)
        found, raw_fills = self._surface(("fills", "executions", "fill_records"), operation)
        if not found:
            self._fail("fill_surface_missing", operation, "injected client has no fill surface")
        result: list[Fill] = []
        for raw in _rows(raw_fills):
            fill = self._map_fill(raw)
            cached = self._fills_by_id.get(fill.fill_id)
            if cached is None:
                self._fills_by_id[fill.fill_id] = fill
                cached = fill
                self._apply_fill_to_order(cached)
            elif cached != fill:
                self._fail(
                    "duplicate_fill_conflict",
                    operation,
                    f"execution identity {fill.fill_id} changed across replay",
                )
            result.append(cached)
        if order_id is not None:
            expected = str(order_id)
            expected_order = self._resolve_order(expected)
            result = [
                fill
                for fill in result
                if fill.order_id == expected
                or fill.broker_order_id == expected
                or expected_order is not None
                and expected_order.order_id == fill.order_id
            ]
        self._record_response(operation, {"count": len(result)})
        return result

    def get_fills(self, order_id: str | None = None) -> list[Fill]:
        return self.sync_fills(order_id)

    def _apply_fill_to_order(self, fill: Fill) -> None:
        order = self._orders_by_broker_id.get(fill.broker_order_id) or self._orders_by_local_id.get(fill.order_id)
        if order is None:
            return
        fill_total = sum(
            cached.quantity
            for cached in self._fills_by_id.values()
            if cached.broker_order_id == order.broker_order_id
            or cached.order_id == order.order_id
        )
        broker_reported = _float(order.metadata.get("broker_reported_filled_quantity"))
        filled_quantity = max(broker_reported, fill_total)
        order.metadata["filled_quantity"] = filled_quantity
        order.metadata["remaining_quantity"] = max(0.0, float(order.quantity) - filled_quantity)
        order.metadata["commission"] = sum(
            cached.commission
            for cached in self._fills_by_id.values()
            if cached.broker_order_id == order.broker_order_id
            or cached.order_id == order.order_id
        )
        if filled_quantity >= float(order.quantity):
            order.status = OrderStatus.FILLED
        elif filled_quantity > 0:
            order.status = OrderStatus.PARTIALLY_FILLED
        order.updated_at = utc_now()

    def sync_account(self) -> AccountState:
        operation = "sync_account"
        self._require_active(operation)
        found, summary = self._surface(("accountSummary", "account_summary"), operation)
        if not found:
            self._fail("account_summary_surface_missing", operation, "injected client has no account summary surface")
        values: dict[str, float] = {}
        for row in _rows(summary):
            tag = str(_field(row, "tag", default=""))
            if tag:
                values[tag] = _float(_field(row, "value", default=0.0))
        positions = self.sync_positions()
        return AccountState(
            timestamp_utc=utc_now(),
            account_id=self._account_id,
            cash=values.get("TotalCashValue", values.get("CashBalance", 0.0)),
            equity=values.get("NetLiquidation", 0.0),
            buying_power=values.get("BuyingPower", 0.0),
            positions=positions,
        )

    def get_account(self) -> AccountState:
        return self.sync_account()

    def sync_positions(self) -> dict[str, Position]:
        operation = "sync_positions"
        self._require_active(operation)
        found, raw_positions = self._surface(("positions", "position_records"), operation)
        if not found:
            self._fail("positions_surface_missing", operation, "injected client has no positions surface")
        result: dict[str, Position] = {}
        for raw in _rows(raw_positions):
            contract = _field(raw, "contract", default=raw)
            symbol = str(_field(contract, "symbol", default=_field(raw, "symbol", default=""))).upper()
            if not symbol:
                continue
            result[symbol] = Position(
                symbol=symbol,
                quantity=_float(_field(raw, "position", "quantity", default=0.0)),
                avg_price=_float(_field(raw, "avgCost", "avg_price", default=0.0)),
                market_price=_float(_field(raw, "marketPrice", "market_price", default=0.0)),
                unrealized_pnl=_float(_field(raw, "unrealizedPNL", "unrealized_pnl", default=0.0)),
            )
        return result

    def get_positions(self) -> dict[str, Position]:
        return self.sync_positions()

    def _map_order(self, raw: Any) -> Order:
        if isinstance(raw, Order):
            return raw
        contract = _field(raw, "contract", default=raw)
        source_order = _field(raw, "order", default=raw)
        source_status = _field(raw, "orderStatus", default=raw)
        broker_order_id = str(_field(source_order, "orderId", "order_id", default=_field(raw, "orderId", "order_id", default="")))
        client_order_id = str(_field(source_order, "orderRef", "order_ref", "client_order_id", default="") or f"ibkr-replay-{broker_order_id}")
        status = _normalise_status(_field(source_status, "status", default=source_status), OrderStatus.SUBMITTED)
        order = Order(
            timestamp_utc=_utc_datetime(_field(raw, "timestamp_utc", "time", default=None)),
            strategy_id="ibkr_paper_execution_replay",
            symbol=str(_field(contract, "symbol", default=_field(raw, "symbol", default=""))).upper(),
            side=_side(_field(source_order, "action", "side", default="BUY")),
            quantity=_float(_field(source_order, "totalQuantity", "quantity", default=0.0)),
            order_type=_order_type(_field(source_order, "orderType", "order_type", default="MKT")),
            time_in_force=_time_in_force(_field(source_order, "tif", "timeInForce", "time_in_force", default="DAY")),
            client_order_id=client_order_id,
            broker_order_id=broker_order_id,
            limit_price=(
                _float(_field(source_order, "lmtPrice", "limit_price", default=0.0))
                if _order_type(_field(source_order, "orderType", "order_type", default="MKT")) is OrderType.LIMIT
                else None
            ),
            metadata={"source": "ibkr_paper_open_order_replay"},
            status=status,
        )
        self._update_order_metadata(order, raw)
        return order

    def _map_fill(self, raw: Any) -> Fill:
        if isinstance(raw, Fill):
            return raw
        contract = _field(raw, "contract", default=raw)
        execution = _field(raw, "execution", default=raw)
        commission_report = _field(raw, "commissionReport", "commission_report", default=raw)
        broker_order_id = str(_field(execution, "orderId", "order_id", default=_field(raw, "orderId", "order_id", default="")))
        execution_id = str(_field(execution, "execId", "exec_id", "fill_id", default=""))
        fill_id = execution_id or f"ibkr-fill-{broker_order_id}-{_float(_field(execution, 'shares', 'quantity', default=0.0))}-{_float(_field(execution, 'price', default=0.0))}"
        local_order = self._orders_by_broker_id.get(broker_order_id)
        return Fill(
            order_id=local_order.order_id if local_order is not None else broker_order_id,
            symbol=str(_field(contract, "symbol", default=_field(raw, "symbol", default=""))).upper(),
            side=_side(_field(execution, "side", default="BOT")),
            quantity=_float(_field(execution, "shares", "quantity", default=0.0)),
            price=_float(_field(execution, "price", default=0.0)),
            commission=_float(_field(commission_report, "commission", default=_field(raw, "commission", default=0.0))),
            filled_at=_utc_datetime(_field(execution, "time", "filled_at", default=None)),
            broker="ibkr_paper",
            broker_order_id=broker_order_id,
            fill_id=fill_id,
        )
