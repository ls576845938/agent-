"""Fail-closed OKX Demo private WebSocket transport.

The connector is created only by an explicitly started Demo runtime.  It
authenticates and subscribes to read-only private channels; order submission
continues to use the existing REST adapter.
"""

from __future__ import annotations

import ast
import base64
import hashlib
import hmac
import json
import os
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Protocol, Sequence
from urllib.parse import urlsplit

from quant_crypto.oms.okx_demo import (
    OKX_DEMO_INSTRUMENT_ID,
    OkxDemoCredentials,
)
from quant_crypto.oms.private_ws_reconciliation import (
    BTCPrivateWSReconciliationTransport,
    BTCPrivateWSRuntimeReconciler,
    BTCPrivateWSStartupSnapshot,
)


OKX_DEMO_PRIVATE_WS_URL = "wss://wspap.okx.com:8443/ws/v5/private"
OKX_DEMO_WS_PROXY_ENV = "QS_OKX_DEMO_WS_PROXY_URL"
OKX_PRIVATE_WS_LOGIN_PATH = "/users/self/verify"
OKX_DEMO_PRIVATE_WS_VERSION = "okx_demo_private_ws_v1"
OKX_DEMO_PRIVATE_WS_SUBSCRIPTIONS: tuple[Mapping[str, str], ...] = (
    {
        "channel": "orders",
        "instType": "SWAP",
        "instId": OKX_DEMO_INSTRUMENT_ID,
    },
    {
        "channel": "positions",
        "instType": "SWAP",
        "instId": OKX_DEMO_INSTRUMENT_ID,
    },
    {"channel": "balance_and_position"},
    {"channel": "account"},
)
_HEX_HEAD = re.compile(r"^[0-9a-f]{40,64}$")
_SAFE_PROTOCOL_CODE = re.compile(r"^\d{1,8}$")
_SAFE_SUBSCRIPTION_CHANNELS = frozenset(
    {"orders", "positions", "balance_and_position", "account"}
)
_RECONCILIATION_BLOCKER_CATEGORIES = {
    "btc_okx_demo_private_ws:probe_wallclock_timeout": "transport",
    "btc_private_ws:private_stream_not_connected": "transport",
    "btc_private_ws:snapshot_transport_failed": "transport",
    "btc_private_ws:rest_snapshot_not_ok": "snapshot",
    "btc_private_ws:snapshot_sequence_invalid": "snapshot",
    "btc_private_ws:unknown_open_order": "identity",
    "btc_private_ws:unknown_fill": "identity",
    "btc_private_ws:multiple_positions_present": "identity",
    "btc_private_ws:balance_snapshot_missing": "account",
}
_DIAGNOSTIC_FIELD_RE = re.compile(
    r"(?i)(?P<prefix>[\"']?(?:api[_-]?key|secret(?:[_-]?key)?|"
    r"passphrase|password|token|account(?:id)?|acct|subacct|uid|"
    r"proxy(?:[_-]?(?:url|host|port))?|host|port|sCode|channel|"
    r"observed[_-]?channels|expected[_-]?channels)[\"']?\s*(?:=|:)\s*)"
    r"(?P<value>\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|"
    r"[^,\s;}\]]+)"
)


class OkxDemoPrivateWSError(RuntimeError):
    pass


class _ProbeStageFailure(OkxDemoPrivateWSError):
    """Internal stage failure carrying only sanitized diagnostic evidence."""

    def __init__(self, detail: Mapping[str, Any]) -> None:
        self.detail = json.loads(json.dumps(dict(detail)))
        super().__init__(str(self.detail.get("message") or "private_ws_probe_failed"))


def _safe_diagnostic_text(
    value: Any,
    *,
    credentials: OkxDemoCredentials | None = None,
    max_length: int = 256,
) -> str:
    """Keep diagnostics useful while excluding credentials and identities."""

    text = str(value or "").strip()
    if not text:
        return ""
    structured = _parse_structured_diagnostic(text)
    if structured is not None:
        return json.dumps(
            _sanitize_structured_diagnostic(structured),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )[:max(1, int(max_length))]
    sensitive = []
    if credentials is not None:
        sensitive.extend(
            [
                credentials.api_key,
                credentials.secret_key,
                credentials.passphrase,
            ]
        )
    proxy = os.environ.get(OKX_DEMO_WS_PROXY_ENV, "")
    sensitive.append(proxy)
    if proxy:
        try:
            parsed = urlsplit(proxy)
            sensitive.extend(
                [
                    parsed.hostname or "",
                    str(parsed.port or ""),
                ]
            )
        except ValueError:
            pass
    for token in sorted(
        {str(item) for item in sensitive if str(item)},
        key=len,
        reverse=True,
    ):
        text = text.replace(token, "<redacted>")
    text = _redact_labeled_diagnostic_fields(text)
    text = re.sub(
        r"(?i)\b[A-Za-z0-9]+[_-]s[_-]?code[_-][A-Za-z0-9_-]+\b",
        "<redacted-code>",
        text,
    )
    text = re.sub(r"(?i)https?://[^\s,;]+", "<redacted-url>", text)
    text = re.sub(
        r"(?i)(?:127\.0\.0\.1|localhost)(?::\d+)?",
        "<redacted-proxy>",
        text,
    )
    text = re.sub(
        r"(?i)\b(?:acct|account|subacct|uid)[-_]?[A-Za-z0-9._-]*\b",
        "<redacted-account>",
        text,
    )
    return text[:max(1, int(max_length))]


def _safe_diagnostic_code(value: Any) -> str:
    code = str(value or "").strip()
    if not code:
        return ""
    return re.sub(r"[^A-Za-z0-9_.-]", "", code)[:64]


def _safe_protocol_code(value: Any) -> str:
    code = str(value or "").strip()
    if not code:
        return ""
    return code if _SAFE_PROTOCOL_CODE.fullmatch(code) else "<redacted-code>"


def _safe_subscription_channel(value: Any) -> str:
    channel = str(value or "").strip()
    if channel in _SAFE_SUBSCRIPTION_CHANNELS:
        return channel
    return "<redacted-channel>"


def _safe_subscription_channels(value: Any) -> list[str]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        values = value
    elif value is None:
        values = ()
    else:
        values = (value,)
    return sorted(
        {
            _safe_subscription_channel(item)
            for item in values
            if str(item or "").strip()
        }
    )


def _diagnostic_field_kind(key: Any) -> str:
    normalized = re.sub(r"[^a-z0-9]", "", str(key or "").lower())
    if (
        normalized in {
            "apikey",
            "secret",
            "secretkey",
            "passphrase",
            "password",
            "token",
            "account",
            "accountid",
            "acct",
            "acctid",
            "subacct",
            "uid",
            "proxy",
            "proxyurl",
            "proxyhost",
            "proxyport",
            "host",
            "port",
        }
        or normalized.startswith("account")
    ):
        return "secret"
    if normalized in {"scode", "sccode"}:
        return "scode"
    if normalized in {
        "channel",
        "channels",
        "observedchannels",
        "expectedchannels",
    }:
        return "channel"
    return ""


def _sanitize_structured_diagnostic(value: Any) -> Any:
    if isinstance(value, Mapping):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            kind = _diagnostic_field_kind(key)
            if kind == "secret":
                sanitized[str(key)] = "<redacted>"
            elif kind == "scode":
                sanitized[str(key)] = _safe_protocol_code(item)
            elif kind == "channel":
                if isinstance(item, Sequence) and not isinstance(
                    item, (str, bytes)
                ):
                    sanitized[str(key)] = [
                        _safe_subscription_channel(row) for row in item
                    ]
                else:
                    sanitized[str(key)] = _safe_subscription_channel(item)
            else:
                sanitized[str(key)] = _sanitize_structured_diagnostic(item)
        return sanitized
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [_sanitize_structured_diagnostic(item) for item in value]
    return value


def _parse_structured_diagnostic(text: str) -> Any | None:
    for parser in (json.loads, ast.literal_eval):
        try:
            value = parser(text)
        except (ValueError, SyntaxError, TypeError, json.JSONDecodeError):
            continue
        if isinstance(value, (Mapping, list, tuple)):
            return value
    return None


def _redact_labeled_diagnostic_fields(text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        prefix = match.group("prefix")
        key = re.search(
            r"(?i)(api[_-]?key|secret(?:[_-]?key)?|passphrase|password|"
            r"token|account(?:id)?|acct|subacct|uid|proxy(?:[_-]?(?:url|host|port))?|"
            r"host|port|sCode|channel|observed[_-]?channels|expected[_-]?channels)",
            prefix,
        )
        kind = _diagnostic_field_kind(key.group(1) if key else "")
        if kind == "scode":
            replacement = "<redacted-code>"
        elif kind == "channel":
            replacement = "<redacted-channel>"
        else:
            replacement = "<redacted>"
        return f"{prefix}{replacement}"

    return _DIAGNOSTIC_FIELD_RE.sub(replace, text)


def _dedupe_probe_diagnostics(
    values: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, Mapping):
            continue
        normalized = json.loads(json.dumps(dict(value)))
        identity = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
        if identity in seen:
            continue
        seen.add(identity)
        result.append(normalized)
    return result


def _project_reconciliation_blocker_evidence(value: Any) -> dict[str, Any]:
    """Return only stable, non-identifying reconciliation blocker evidence."""

    values = value if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) else ()
    codes: set[str] = set()
    for raw in values:
        text = str(raw or "").strip()
        normalized = next(
            (
                candidate
                for candidate in _RECONCILIATION_BLOCKER_CATEGORIES
                if text == candidate
                or (
                    candidate == "btc_private_ws:snapshot_transport_failed"
                    and text.startswith(candidate + ":")
                )
            ),
            "unknown_reconciliation_blocker",
        )
        codes.add(normalized)
    ordered_codes = sorted(codes)
    categories = sorted(
        {
            _RECONCILIATION_BLOCKER_CATEGORIES.get(code, "unknown")
            for code in ordered_codes
        }
    )
    category_set = set(categories)
    return {
        "reconciliation_blocker_codes": ordered_codes,
        "reconciliation_blocker_categories": categories,
        "reconciliation_blocker_count": len(ordered_codes),
        "reconciliation_blocker_set_sha256": hashlib.sha256(
            "\n".join(ordered_codes).encode("utf-8")
        ).hexdigest(),
        "identity_projection": {
            "account_blocker_present": "account" in category_set,
            "blocker_code_count": len(ordered_codes),
            "identity_blocker_present": "identity" in category_set,
            "snapshot_blocker_present": "snapshot" in category_set,
            "transport_blocker_present": "transport" in category_set,
            "unknown_blocker_present": "unknown" in category_set,
        },
    }


class PrivateWSConnection(Protocol):
    def send(self, payload: str) -> Any: ...

    def recv(self) -> Any: ...

    def close(self) -> Any: ...


class PrivateWSConnectionFactory(Protocol):
    def __call__(self, *, url: str, timeout_seconds: float) -> PrivateWSConnection: ...


class _WebsocketClientFactory:
    def __call__(
        self,
        *,
        url: str,
        timeout_seconds: float,
    ) -> PrivateWSConnection:
        import websocket

        return websocket.create_connection(
            url,
            timeout=timeout_seconds,
            **_dedicated_ws_proxy_options(
                timeout_seconds=timeout_seconds,
            ),
        )


def _dedicated_ws_proxy_options(
    *,
    timeout_seconds: float,
) -> dict[str, str | int | float]:
    raw_proxy_url = os.environ.get(OKX_DEMO_WS_PROXY_ENV)
    if raw_proxy_url is None:
        return {}
    try:
        parsed = urlsplit(raw_proxy_url)
        port = parsed.port
    except ValueError:
        raise OkxDemoPrivateWSError(
            "okx_demo_private_ws_proxy_invalid"
        ) from None
    host = (parsed.hostname or "").lower()
    if (
        not raw_proxy_url
        or raw_proxy_url != raw_proxy_url.strip()
        or parsed.scheme.lower() != "http"
        or host not in {"127.0.0.1", "localhost"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path
        or parsed.query
        or parsed.fragment
        or port is None
        or not 1 <= port <= 65535
    ):
        raise OkxDemoPrivateWSError(
            "okx_demo_private_ws_proxy_invalid"
        )
    return {
        "http_proxy_host": host,
        "http_proxy_port": port,
        "proxy_type": "http",
        "http_proxy_timeout": timeout_seconds,
    }


@dataclass(frozen=True)
class OkxDemoPrivateWSProbeReceipt:
    source_head: str
    runtime_version: str
    generated_at_utc: str
    startup_reconciled: bool
    disconnect_cancel_only_observed: bool
    reconnect_login_observed: bool
    reconnect_resubscribed: bool
    reconnect_rest_reconciled: bool
    subscribed_channels: tuple[str, ...]
    received_event_count: int
    probe_generation: int
    blockers: tuple[str, ...]
    probe_diagnostics: tuple[Mapping[str, Any], ...] = ()

    @property
    def opening_allowed(self) -> bool:
        return (
            self.startup_reconciled
            and self.disconnect_cancel_only_observed
            and self.reconnect_login_observed
            and self.reconnect_resubscribed
            and self.reconnect_rest_reconciled
            and not self.blockers
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "btc_okx_demo_private_ws_reconnect_probe_v1",
            "source_head": self.source_head,
            "runtime_version": self.runtime_version,
            "generated_at_utc": self.generated_at_utc,
            "environment": "OKX Demo",
            "endpoint_class": "demo_private_websocket",
            "instrument_id": OKX_DEMO_INSTRUMENT_ID,
            "fixture": False,
            "evidence_class": "current_head_runtime_observation",
            "startup_reconciled": self.startup_reconciled,
            "disconnect_cancel_only_observed": (
                self.disconnect_cancel_only_observed
            ),
            "reconnect_login_observed": self.reconnect_login_observed,
            "reconnect_resubscribed": self.reconnect_resubscribed,
            "reconnect_rest_reconciled": self.reconnect_rest_reconciled,
            "subscribed_channels": list(self.subscribed_channels),
            "received_event_count": self.received_event_count,
            "probe_generation": self.probe_generation,
            "opening_allowed_after_reconciliation": self.opening_allowed,
            "blockers": list(self.blockers),
            "probe_diagnostics": [
                json.loads(json.dumps(dict(row)))
                for row in self.probe_diagnostics
            ],
            "credentials_redacted": True,
            "credential_material_persisted": False,
            "standard_proxy_environment_supported": True,
            "proxy_values_persisted": False,
            "websocket_order_submission_supported": False,
            "private_ws_observed": False,
            "private_ws_promotion_gate_retired": False,
            "promotion_evidence_ready": False,
            "paper_allowed": False,
            "live_allowed": False,
            "real_order_allowed": False,
        }


class _SnapshotTransport(BTCPrivateWSReconciliationTransport):
    def __init__(
        self,
        *,
        snapshot_loader: Callable[[], Mapping[str, Any]],
        sequence: Callable[[], int],
        diagnostic_factory: Callable[..., Mapping[str, Any]],
        stage: str,
    ) -> None:
        self._snapshot_loader = snapshot_loader
        self._sequence = sequence
        self._diagnostic_factory = diagnostic_factory
        self._stage = stage
        self._diagnostics: list[dict[str, Any]] = []

    @property
    def probe_diagnostics(self) -> tuple[Mapping[str, Any], ...]:
        return tuple(self._diagnostics)

    def set_stage(self, stage: str) -> None:
        self._stage = stage

    def record_receipt(self, receipt: Mapping[str, Any]) -> None:
        blockers = receipt.get("blockers") or []
        if not blockers:
            return
        evidence = _project_reconciliation_blocker_evidence(blockers)
        for diagnostic in self._diagnostics:
            if isinstance(diagnostic, Mapping) and str(
                diagnostic.get("stage") or ""
            ) == self._stage:
                diagnostic.update(evidence)
                return
        self._diagnostics.append(
            dict(
                self._diagnostic_factory(
                    stage=self._stage,
                    exception_type="ReconciliationBlocked",
                    message="okx_demo_private_ws_reconciliation_blocked",
                    blocker_count=len(blockers),
                    reconciliation_blockers=blockers,
                )
            )
        )

    def fetch_startup_snapshot(self) -> BTCPrivateWSStartupSnapshot:
        try:
            snapshot = self._snapshot_loader()
        except Exception as exc:
            self._diagnostics.append(
                dict(
                    self._diagnostic_factory(
                        stage=self._stage,
                        exception=exc,
                    )
                )
            )
            raise
        captured = _parse_utc(snapshot.get("captured_at_utc"))
        if captured is None:
            raise OkxDemoPrivateWSError("okx_demo_private_ws_snapshot_time_invalid")
        balance = snapshot.get("balance")
        if not isinstance(balance, Mapping):
            balance = {}
        return BTCPrivateWSStartupSnapshot(
            open_orders=tuple(_rows(snapshot.get("pending_orders"))),
            fills=tuple(_rows(snapshot.get("fills"))),
            positions=tuple(_rows(snapshot.get("positions"))),
            balance=dict(balance),
            funding_bills=tuple(_rows(snapshot.get("bills"))),
            last_sequence=self._sequence(),
            private_ws_status="connected",
            rest_status="ok",
            captured_at_utc=captured,
        )


class OkxDemoPrivateWS:
    def __init__(
        self,
        *,
        credentials: OkxDemoCredentials,
        source_head: str,
        runtime_version: str,
        snapshot_loader: Callable[[], Mapping[str, Any]],
        owned_client_order_ids: Callable[[], Sequence[str]],
        on_disconnect: Callable[[str], None],
        on_reconciled: Callable[[Mapping[str, Any]], None] | None = None,
        connection_factory: PrivateWSConnectionFactory | None = None,
        clock: Callable[[], datetime] | None = None,
        timeout_seconds: float = 20.0,
        startup_reconnect_probe_timeout_seconds: float | None = None,
        reconnect_initial_delay_seconds: float = 0.25,
        reconnect_max_delay_seconds: float = 5.0,
    ) -> None:
        if not _HEX_HEAD.fullmatch(source_head):
            raise OkxDemoPrivateWSError("okx_demo_private_ws_source_head_invalid")
        if not runtime_version.strip():
            raise OkxDemoPrivateWSError(
                "okx_demo_private_ws_runtime_version_missing"
            )
        if timeout_seconds <= 0:
            raise OkxDemoPrivateWSError("okx_demo_private_ws_timeout_invalid")
        if (
            startup_reconnect_probe_timeout_seconds is not None
            and startup_reconnect_probe_timeout_seconds <= 0
        ):
            raise OkxDemoPrivateWSError(
                "okx_demo_private_ws_probe_wallclock_timeout_invalid"
            )
        if (
            reconnect_initial_delay_seconds < 0
            or reconnect_max_delay_seconds < reconnect_initial_delay_seconds
        ):
            raise OkxDemoPrivateWSError(
                "okx_demo_private_ws_reconnect_backoff_invalid"
            )
        self._credentials = credentials
        self._source_head = source_head
        self._runtime_version = runtime_version
        self._snapshot_loader = snapshot_loader
        self._owned_client_order_ids = owned_client_order_ids
        self._on_disconnect = on_disconnect
        self._on_reconciled = on_reconciled
        self._connection_factory = connection_factory or _WebsocketClientFactory()
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._timeout_seconds = timeout_seconds
        self._startup_reconnect_probe_timeout_seconds = (
            float(startup_reconnect_probe_timeout_seconds)
            if startup_reconnect_probe_timeout_seconds is not None
            else min(180.0, max(120.0, float(timeout_seconds) * 8.0))
        )
        self._reconnect_initial_delay_seconds = reconnect_initial_delay_seconds
        self._reconnect_max_delay_seconds = reconnect_max_delay_seconds
        self._connection: PrivateWSConnection | None = None
        self._connected = False
        self._received_event_count = 0
        self._reconnect_attempt_count = 0
        self._consecutive_reconnect_failures = 0
        self._last_reconciled_at_utc = ""
        self._last_blockers: list[str] = []
        self._last_probe_diagnostics: list[dict[str, Any]] = []
        self._last_subscription_progress: dict[str, Any] = {
            "observed_channels": [],
            "expected_channels": sorted(
                {str(row["channel"]) for row in OKX_DEMO_PRIVATE_WS_SUBSCRIPTIONS}
            ),
            "complete": False,
        }
        self._listener: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._controlled_reconnect_event = threading.Event()
        self._reconciled_event = threading.Event()
        self._lock = threading.RLock()
        self._probe_token = 0
        self._probe_generation = 0

    def run_startup_reconnect_probe(self) -> dict[str, Any]:
        with self._lock:
            self._probe_token += 1
            probe_token = self._probe_token
            self._probe_generation = 1
        deadline = time.monotonic() + self._startup_reconnect_probe_timeout_seconds
        blockers: list[str] = []
        startup, startup_timed_out = self._run_probe_attempt(
            reconnect=False,
            probe_token=probe_token,
            deadline=deadline,
            timeout_stage="startup_snapshot",
        )
        diagnostics = list(startup.get("probe_diagnostics") or [])
        startup_reconciled = startup.get("opening_allowed") is True
        disconnect_observed = False
        if startup_reconciled:
            self._on_disconnect("private_ws_startup_probe_local_disconnect")
            disconnect_observed = True
            self._close_connection()
        reconnect: dict[str, Any] = {}
        reconnect_timed_out = False
        if startup_reconciled:
            with self._lock:
                self._probe_generation = 2
            reconnect, reconnect_timed_out = self._run_probe_attempt(
                reconnect=True,
                probe_token=probe_token,
                deadline=deadline,
                timeout_stage="reconnect",
            )
        diagnostics.extend(reconnect.get("probe_diagnostics") or [])
        if not startup_reconciled:
            blockers.extend(startup.get("blockers") or [])
        if reconnect and reconnect.get("opening_allowed") is not True:
            blockers.extend(reconnect.get("blockers") or [])
        if startup_timed_out or reconnect_timed_out:
            blockers.append("btc_okx_demo_private_ws:probe_wallclock_timeout")
        with self._lock:
            probe_generation = self._probe_generation
        receipt = OkxDemoPrivateWSProbeReceipt(
            source_head=self._source_head,
            runtime_version=self._runtime_version,
            generated_at_utc=_iso(self._clock()),
            startup_reconciled=startup_reconciled,
            disconnect_cancel_only_observed=disconnect_observed,
            reconnect_login_observed=bool(
                reconnect.get("login_observed") is True
            ),
            reconnect_resubscribed=bool(
                reconnect.get("subscriptions_observed") is True
            ),
            reconnect_rest_reconciled=bool(
                reconnect.get("snapshot_reconciled") is True
            ),
            subscribed_channels=tuple(
                str(row["channel"]) for row in OKX_DEMO_PRIVATE_WS_SUBSCRIPTIONS
            ),
            received_event_count=self._received_event_count,
            probe_generation=probe_generation,
            blockers=tuple(_dedupe(blockers)),
            probe_diagnostics=tuple(_dedupe_probe_diagnostics(diagnostics)),
        )
        payload = receipt.to_dict()
        with self._lock:
            self._last_probe_diagnostics = list(receipt.probe_diagnostics)
        if not receipt.opening_allowed:
            self._invalidate_probe_token(probe_token)
            self._close_connection()
        if (
            receipt.opening_allowed
            and self._probe_token_is_current(probe_token)
            and self._on_reconciled is not None
        ):
            self._on_reconciled(payload)
        return payload

    def _run_probe_attempt(
        self,
        *,
        reconnect: bool,
        probe_token: int,
        deadline: float,
        timeout_stage: str,
    ) -> tuple[dict[str, Any], bool]:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return self._probe_wallclock_timeout(
                stage=timeout_stage,
                probe_token=probe_token,
            ), True
        result: dict[str, Any] = {}
        complete = threading.Event()

        def run() -> None:
            try:
                result["payload"] = self._connect_and_reconcile(
                    reconnect=reconnect,
                    probe_token=probe_token,
                )
            except BaseException as exc:  # defensive: worker must always settle.
                result["exception"] = exc
            finally:
                complete.set()

        worker = threading.Thread(
            target=run,
            name="btc-okx-demo-private-ws-probe",
            daemon=True,
        )
        worker.start()
        if not complete.wait(remaining):
            return self._probe_wallclock_timeout(
                stage=timeout_stage,
                probe_token=probe_token,
            ), True
        exception = result.get("exception")
        if isinstance(exception, BaseException):
            diagnostic = self._build_probe_diagnostic(
                stage=timeout_stage,
                exception=exception,
            )
            blocker = f"btc_okx_demo_private_ws:{type(exception).__name__}"
            with self._lock:
                if self._probe_token == probe_token:
                    self._last_blockers = [blocker]
                    self._last_probe_diagnostics = [diagnostic]
            return {
                "opening_allowed": False,
                "login_observed": False,
                "subscriptions_observed": False,
                "snapshot_reconciled": False,
                "blockers": [blocker],
                "probe_diagnostics": [diagnostic],
            }, False
        payload = result.get("payload")
        return (dict(payload) if isinstance(payload, Mapping) else {}), False

    def _probe_wallclock_timeout(
        self,
        *,
        stage: str,
        probe_token: int,
    ) -> dict[str, Any]:
        diagnostic = self._build_probe_diagnostic(
            stage=stage,
            exception_type="ProbeWallClockTimeout",
            message="okx_demo_private_ws_probe_wallclock_timeout",
        )
        self._invalidate_probe_token(probe_token)
        self._close_connection()
        with self._lock:
            self._last_blockers = [
                "btc_okx_demo_private_ws:probe_wallclock_timeout"
            ]
            self._last_probe_diagnostics = [diagnostic]
        return {
            "opening_allowed": False,
            "login_observed": False,
            "subscriptions_observed": False,
            "snapshot_reconciled": False,
            "blockers": ["btc_okx_demo_private_ws:probe_wallclock_timeout"],
            "probe_diagnostics": [diagnostic],
        }

    def _probe_token_is_current(self, probe_token: int | None) -> bool:
        with self._lock:
            return probe_token is None or self._probe_token == probe_token

    def _invalidate_probe_token(self, probe_token: int) -> None:
        with self._lock:
            if self._probe_token == probe_token:
                self._probe_token += 1

    def start_monitoring(self) -> None:
        with self._lock:
            if self._connection is None:
                raise OkxDemoPrivateWSError(
                    "okx_demo_private_ws_not_connected"
                )
            if self._listener is not None and self._listener.is_alive():
                return
            self._stop_event.clear()
            self._listener = threading.Thread(
                target=self._listen,
                name="btc-okx-demo-private-ws",
                daemon=True,
            )
            self._listener.start()

    def disconnect_for_reconnect(self, reason: str) -> dict[str, Any]:
        """Close only the current socket while retaining the listener owner."""

        with self._lock:
            listener = self._listener
            if listener is None or not listener.is_alive():
                raise OkxDemoPrivateWSError(
                    "okx_demo_private_ws_controlled_disconnect_listener_missing"
                )
            if self._stop_event.is_set():
                raise OkxDemoPrivateWSError(
                    "okx_demo_private_ws_terminal_stop_already_requested"
                )
            self._controlled_reconnect_event.set()
            self._reconciled_event.clear()
        self._on_disconnect(str(reason or "controlled_disconnect"))
        self._close_connection()
        deadline = time.monotonic() + self._timeout_seconds
        while not self._reconciled_event.wait(0.01):
            if self._stop_event.is_set():
                break
            if time.monotonic() >= deadline:
                raise OkxDemoPrivateWSError(
                    "okx_demo_private_ws_controlled_reconnect_timed_out"
                )
        status = self.status()
        if not (
            status["connected"] is True
            and status["listener_alive"] is True
            and status["opening_allowed_after_reconciliation"] is True
        ):
            raise OkxDemoPrivateWSError(
                "okx_demo_private_ws_controlled_reconnect_not_reconciled"
            )
        return {
            "terminal_stop_requested": False,
            "connected": True,
            "listener_alive": True,
            "login_observed": True,
            "resubscribed": True,
            "rest_reconciled": True,
        }

    def stop(self, *, join_timeout_seconds: float = 5.0) -> dict[str, Any]:
        self._stop_event.set()
        self._close_connection()
        with self._lock:
            listener = self._listener
        if (
            listener is not None
            and listener is not threading.current_thread()
        ):
            listener.join(max(0.0, float(join_timeout_seconds)))
        joined = (
            listener is None
            or listener is threading.current_thread()
            or not listener.is_alive()
        )
        if not joined:
            raise OkxDemoPrivateWSError(
                "okx_demo_private_ws_listener_join_timed_out"
            )
        return {
            "terminal_stop_requested": True,
            "listener_joined": joined,
        }

    def status(self) -> dict[str, Any]:
        with self._lock:
            listener_alive = bool(
                self._listener is not None and self._listener.is_alive()
            )
            connected = self._connected and self._connection is not None
            monitoring_started = self._listener is not None
            opening_allowed = (
                connected
                and bool(self._last_reconciled_at_utc)
                and (not monitoring_started or listener_alive)
                and not self._last_blockers
            )
            return {
                "status": "connected" if connected else "disconnected",
                "connected": connected,
                "listener_alive": listener_alive,
                "monitoring_started": monitoring_started,
                "last_reconciled_at_utc": self._last_reconciled_at_utc,
                "received_event_count": self._received_event_count,
                "probe_generation": self._probe_generation,
                "reconnect_attempt_count": self._reconnect_attempt_count,
                "consecutive_reconnect_failures": (
                    self._consecutive_reconnect_failures
                ),
                "reconnect_login_observed": connected,
                "reconnect_resubscribed": connected,
                "reconnect_rest_reconciled": opening_allowed,
                "opening_allowed_after_reconciliation": opening_allowed,
                "blockers": list(self._last_blockers),
                "probe_diagnostics": [
                    json.loads(json.dumps(dict(row)))
                    for row in self._last_probe_diagnostics
                ],
                "credentials_redacted": True,
                "promotion_evidence_ready": False,
                "paper_allowed": False,
                "live_allowed": False,
            }

    def reconcile_current(self) -> dict[str, Any]:
        with self._lock:
            if not self._connected or self._connection is None:
                return self._current_reconciliation_receipt(
                    opening_allowed=False,
                    blockers=("btc_okx_demo_private_ws:not_connected",),
                )
        try:
            transport = _SnapshotTransport(
                snapshot_loader=self._snapshot_loader,
                sequence=lambda: self._received_event_count,
                diagnostic_factory=self._build_probe_diagnostic,
                stage="startup_snapshot",
            )
            receipt = BTCPrivateWSRuntimeReconciler(
                transport=transport,
                owned_client_order_ids=self._owned_client_order_ids(),
            ).startup().to_dict()
            opening_allowed = receipt.get("opening_allowed") is True
            blockers = tuple(str(row) for row in receipt.get("blockers") or [])
            with self._lock:
                self._last_blockers = list(blockers)
                self._last_probe_diagnostics = _dedupe_probe_diagnostics(
                    transport.probe_diagnostics
                )
                if opening_allowed:
                    self._last_reconciled_at_utc = _iso(self._clock())
            return self._current_reconciliation_receipt(
                opening_allowed=opening_allowed,
                blockers=blockers,
            )
        except Exception as exc:
            blocker = f"btc_okx_demo_private_ws:{type(exc).__name__}"
            with self._lock:
                self._last_blockers = [blocker]
            return self._current_reconciliation_receipt(
                opening_allowed=False,
                blockers=(blocker,),
            )

    def _current_reconciliation_receipt(
        self,
        *,
        opening_allowed: bool,
        blockers: Sequence[str],
        schema_version: str = "btc_okx_demo_private_ws_current_reconciliation_v1",
    ) -> dict[str, Any]:
        status = self.status()
        return {
            "schema_version": schema_version,
            "source_head": self._source_head,
            "runtime_version": self._runtime_version,
            "generated_at_utc": _iso(self._clock()),
            "fixture": False,
            "connected": status["connected"],
            "listener_alive": status["listener_alive"],
            "reconnect_login_observed": status["connected"],
            "reconnect_resubscribed": status["connected"],
            "reconnect_rest_reconciled": opening_allowed,
            "opening_allowed_after_reconciliation": (
                opening_allowed and status["connected"]
            ),
            "blockers": list(blockers),
            "probe_diagnostics": [
                json.loads(json.dumps(dict(row)))
                for row in self._last_probe_diagnostics
            ],
            "credentials_redacted": True,
            "promotion_evidence_ready": False,
            "paper_allowed": False,
            "live_allowed": False,
        }

    def _connect_and_reconcile(
        self,
        *,
        reconnect: bool,
        probe_token: int | None = None,
    ) -> dict[str, Any]:
        stage = "reconnect" if reconnect else "connect"
        transport: _SnapshotTransport | None = None
        connection: PrivateWSConnection | None = None
        try:
            connection = self._connection_factory(
                url=OKX_DEMO_PRIVATE_WS_URL,
                timeout_seconds=self._timeout_seconds,
            )
            if not self._probe_token_is_current(probe_token):
                self._close_connection_value(connection)
                return self._cancelled_probe_result()
            with self._lock:
                self._connection = connection
            stage = "login"
            self._login(connection)
            if not self._probe_token_is_current(probe_token):
                self._close_connection_if_current(connection)
                return self._cancelled_probe_result()
            stage = "subscribe"
            self._subscribe(connection)
            if not self._probe_token_is_current(probe_token):
                self._close_connection_if_current(connection)
                return self._cancelled_probe_result()
            transport = _SnapshotTransport(
                snapshot_loader=self._snapshot_loader,
                sequence=lambda: self._received_event_count,
                diagnostic_factory=self._build_probe_diagnostic,
                stage="reconnect" if reconnect else "startup_snapshot",
            )
            reconciler = BTCPrivateWSRuntimeReconciler(
                transport=transport,
                owned_client_order_ids=self._owned_client_order_ids(),
            )
            if reconnect:
                runtime_receipt = _reconcile_after_reconnect(
                    reconciler,
                    transport=transport,
                )
            else:
                runtime_receipt = reconciler.startup().to_dict()
                transport.record_receipt(runtime_receipt)
            if not self._probe_token_is_current(probe_token):
                self._close_connection_if_current(connection)
                return self._cancelled_probe_result()
            opening_allowed = runtime_receipt.get("opening_allowed") is True
            blockers = [
                str(row) for row in runtime_receipt.get("blockers") or []
            ]
            with self._lock:
                if not self._probe_token_is_current(probe_token):
                    stale = True
                else:
                    stale = False
                    self._connected = opening_allowed
                    self._last_blockers = blockers
                    if opening_allowed:
                        self._last_reconciled_at_utc = _iso(self._clock())
                        self._consecutive_reconnect_failures = 0
                    self._last_probe_diagnostics = _dedupe_probe_diagnostics(
                        transport.probe_diagnostics
                    )
            if stale:
                self._close_connection_if_current(connection)
                return self._cancelled_probe_result()
            return {
                **runtime_receipt,
                "login_observed": True,
                "subscriptions_observed": True,
                "probe_diagnostics": [
                    json.loads(json.dumps(dict(row)))
                    for row in transport.probe_diagnostics
                ],
            }
        except Exception as exc:
            if not self._probe_token_is_current(probe_token):
                self._close_connection_if_current(connection)
                return self._cancelled_probe_result()
            self._close_connection_if_current(connection)
            diagnostics = list(transport.probe_diagnostics) if transport else []
            if not diagnostics:
                diagnostics = [
                    self._build_probe_diagnostic(stage=stage, exception=exc)
                ]
            diagnostics = _dedupe_probe_diagnostics(diagnostics)
            blocker_type = (
                "OkxDemoPrivateWSError"
                if isinstance(exc, _ProbeStageFailure)
                else type(exc).__name__
            )
            blocker = f"btc_okx_demo_private_ws:{blocker_type}"
            with self._lock:
                self._last_blockers = [blocker]
                self._last_probe_diagnostics = diagnostics
            self._on_disconnect(
                f"private_ws_connect_or_reconcile_failed:{type(exc).__name__}"
            )
            return {
                "opening_allowed": False,
                "login_observed": False,
                "subscriptions_observed": False,
                "snapshot_reconciled": False,
                "blockers": [blocker],
                "probe_diagnostics": diagnostics,
            }

    @staticmethod
    def _cancelled_probe_result() -> dict[str, Any]:
        return {
            "opening_allowed": False,
            "login_observed": False,
            "subscriptions_observed": False,
            "snapshot_reconciled": False,
            "blockers": ["btc_okx_demo_private_ws:probe_cancelled"],
            "probe_diagnostics": [],
        }

    def _close_connection_if_current(
        self,
        connection: PrivateWSConnection | None,
    ) -> None:
        if connection is None:
            return
        with self._lock:
            if self._connection is connection:
                self._connection = None
                self._connected = False
        self._close_connection_value(connection)

    @staticmethod
    def _close_connection_value(connection: PrivateWSConnection) -> None:
        try:
            connection.close()
        except Exception:
            pass

    def _build_probe_diagnostic(
        self,
        *,
        stage: str,
        exception: BaseException | None = None,
        exception_type: str = "",
        message: str = "",
        protocol_scode: Any = "",
        protocol_msg: Any = "",
        blocker_count: int | None = None,
        reconciliation_blockers: Sequence[Any] | None = None,
        subscription_progress: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        if isinstance(exception, _ProbeStageFailure):
            return json.loads(json.dumps(dict(exception.detail)))
        normalized_stage = stage if stage in {
            "connect",
            "login",
            "subscribe",
            "startup_snapshot",
            "reconnect",
        } else "unknown"
        if exception is not None:
            exception_type = type(exception).__name__
            message = str(exception)
        progress = dict(
            subscription_progress
            or self._last_subscription_progress
        )
        normalized_progress = {
            "observed_channels": _safe_subscription_channels(
                progress.get("observed_channels")
            ),
            "expected_channels": _safe_subscription_channels(
                progress.get("expected_channels")
            ),
            "complete": progress.get("complete") is True,
        }
        detail: dict[str, Any] = {
            "stage": normalized_stage,
            "exception_type": _safe_diagnostic_code(exception_type)
            or "ProbeFailure",
            "message": _safe_diagnostic_text(
                message or "okx_demo_private_ws_probe_failed",
                credentials=self._credentials,
            ),
            "protocol": {
                "sCode": _safe_protocol_code(protocol_scode),
                "msg": _safe_diagnostic_text(
                    protocol_msg,
                    credentials=self._credentials,
                ),
            },
            "subscription_progress": normalized_progress,
        }
        if blocker_count is not None:
            detail["blocker_count"] = max(0, int(blocker_count))
        if reconciliation_blockers is not None:
            detail.update(
                _project_reconciliation_blocker_evidence(
                    reconciliation_blockers
                )
            )
        return detail

    def _login(self, connection: PrivateWSConnection) -> None:
        timestamp = str(int(self._clock().timestamp()))
        prehash = timestamp + "GET" + OKX_PRIVATE_WS_LOGIN_PATH
        signature = base64.b64encode(
            hmac.new(
                self._credentials.secret_key.encode("utf-8"),
                prehash.encode("utf-8"),
                hashlib.sha256,
            ).digest()
        ).decode("ascii")
        connection.send(
            json.dumps(
                {
                    "op": "login",
                    "args": [
                        {
                            "apiKey": self._credentials.api_key,
                            "passphrase": self._credentials.passphrase,
                            "timestamp": timestamp,
                            "sign": signature,
                        }
                    ],
                },
                separators=(",", ":"),
            )
        )
        self._expect_ack(connection, operation="login")

    def _subscribe(self, connection: PrivateWSConnection) -> None:
        connection.send(
            json.dumps(
                {
                    "op": "subscribe",
                    "args": [dict(row) for row in OKX_DEMO_PRIVATE_WS_SUBSCRIPTIONS],
                },
                separators=(",", ":"),
            )
        )
        observed: set[str] = set()
        expected = {
            str(row["channel"]) for row in OKX_DEMO_PRIVATE_WS_SUBSCRIPTIONS
        }
        self._last_subscription_progress = {
            "observed_channels": [],
            "expected_channels": sorted(expected),
            "complete": False,
        }
        for _ in range(20):
            try:
                message = _message(connection.recv())
            except Exception as exc:
                raise _ProbeStageFailure(
                    self._build_probe_diagnostic(
                        stage="subscribe",
                        exception=exc,
                    )
                ) from None
            event = str(message.get("event") or "")
            if event == "error":
                raise _ProbeStageFailure(
                    self._build_probe_diagnostic(
                        stage="subscribe",
                        exception_type="ProtocolError",
                        message="okx_demo_private_ws_subscribe_failed",
                        protocol_scode=message.get("sCode") or message.get("code"),
                        protocol_msg=message.get("msg"),
                    )
                )
            if event == "subscribe":
                channel = str(_mapping(message.get("arg")).get("channel") or "")
                if channel:
                    observed.add(channel)
                self._last_subscription_progress = {
                    "observed_channels": sorted(observed),
                    "expected_channels": sorted(expected),
                    "complete": observed == expected,
                }
                if observed == expected:
                    return
            elif message.get("data"):
                self._received_event_count += 1
        raise _ProbeStageFailure(
            self._build_probe_diagnostic(
                stage="subscribe",
                exception_type="SubscriptionAckIncomplete",
                message="okx_demo_private_ws_subscription_ack_incomplete",
            )
        )

    def _expect_ack(
        self,
        connection: PrivateWSConnection,
        *,
        operation: str,
    ) -> None:
        for _ in range(10):
            try:
                message = _message(connection.recv())
            except Exception as exc:
                raise _ProbeStageFailure(
                    self._build_probe_diagnostic(
                        stage=operation,
                        exception=exc,
                    )
                ) from None
            if str(message.get("event") or "") == operation:
                if str(message.get("code") or message.get("sCode") or "0") != "0":
                    raise _ProbeStageFailure(
                        self._build_probe_diagnostic(
                            stage=operation,
                            exception_type="ProtocolError",
                            message=f"okx_demo_private_ws_{operation}_failed",
                            protocol_scode=message.get("sCode") or message.get("code"),
                            protocol_msg=message.get("msg"),
                        )
                    )
                return
            if str(message.get("event") or "") == "error":
                raise _ProbeStageFailure(
                    self._build_probe_diagnostic(
                        stage=operation,
                        exception_type="ProtocolError",
                        message=f"okx_demo_private_ws_{operation}_failed",
                        protocol_scode=message.get("sCode") or message.get("code"),
                        protocol_msg=message.get("msg"),
                    )
                )
        raise OkxDemoPrivateWSError(
            f"okx_demo_private_ws_{operation}_ack_missing"
        )

    def _listen(self) -> None:
        while not self._stop_event.is_set():
            with self._lock:
                connection = self._connection
            if connection is None:
                if self._controlled_reconnect_event.is_set():
                    self._reconnect_until_current()
                    continue
                return
            try:
                raw = connection.recv()
                if raw == "ping":
                    connection.send("pong")
                    continue
                message = _message(raw)
                if message.get("data"):
                    self._received_event_count += 1
            except Exception as exc:
                if self._stop_event.is_set():
                    return
                controlled = self._controlled_reconnect_event.is_set()
                if not controlled:
                    self._on_disconnect(
                        f"private_ws_disconnected:{type(exc).__name__}"
                    )
                self._close_connection()
                self._reconnect_until_current()
                continue

    def _reconnect_until_current(self) -> None:
        delay = self._reconnect_initial_delay_seconds
        while not self._stop_event.is_set():
            with self._lock:
                self._reconnect_attempt_count += 1
            reconnect = self._connect_and_reconcile(reconnect=True)
            if reconnect.get("opening_allowed") is True:
                self._controlled_reconnect_event.clear()
                receipt = self._current_reconciliation_receipt(
                    opening_allowed=True,
                    blockers=(),
                    schema_version=(
                        "btc_okx_demo_private_ws_runtime_reconnect_v1"
                    ),
                )
                if self._on_reconciled is not None:
                    self._on_reconciled(receipt)
                self._reconciled_event.set()
                return
            self._close_connection()
            with self._lock:
                self._consecutive_reconnect_failures += 1
            if self._stop_event.wait(delay):
                return
            delay = min(
                self._reconnect_max_delay_seconds,
                max(delay * 2, 0.001),
            )

    def _close_connection(self) -> None:
        with self._lock:
            connection = self._connection
            self._connection = None
            self._connected = False
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass


def _reconcile_after_reconnect(
    reconciler: BTCPrivateWSRuntimeReconciler,
    *,
    transport: _SnapshotTransport,
):
    # This socket has already logged in and subscribed after the actual
    # disconnect. A fresh reconciler can enter RECONNECT_RECONCILING directly:
    # on_reconnect performs the same full snapshot validation as startup.
    # Running startup() here first fetched an extra full REST snapshot on the
    # same socket, wasting the shared wall-clock budget. Never cache or reuse
    # the pre-disconnect snapshot, and retain all reconnect safety checks.
    reconciler.on_disconnect()
    transport.set_stage("reconnect")
    reconnect = reconciler.on_reconnect()
    transport.record_receipt(reconnect.to_dict())
    return {
        **reconnect.to_dict(),
        "probe_diagnostics": [
            json.loads(json.dumps(dict(row)))
            for row in transport.probe_diagnostics
        ],
    }


def _message(value: Any) -> Mapping[str, Any]:
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    if not isinstance(value, str):
        raise OkxDemoPrivateWSError("okx_demo_private_ws_text_message_required")
    try:
        payload = json.loads(value)
    except json.JSONDecodeError as exc:
        raise OkxDemoPrivateWSError(
            "okx_demo_private_ws_json_message_required"
        ) from exc
    if not isinstance(payload, Mapping):
        raise OkxDemoPrivateWSError("okx_demo_private_ws_object_required")
    return payload


def _rows(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [row for row in value if isinstance(row, Mapping)]


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _parse_utc(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        raise OkxDemoPrivateWSError("okx_demo_private_ws_clock_not_utc")
    return value.astimezone(timezone.utc).isoformat()


def _dedupe(values: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(str(value) for value in values if str(value)))


__all__ = [
    "OKX_DEMO_PRIVATE_WS_SUBSCRIPTIONS",
    "OKX_DEMO_PRIVATE_WS_URL",
    "OkxDemoPrivateWS",
    "OkxDemoPrivateWSError",
]
