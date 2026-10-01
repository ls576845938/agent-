"""Persistent local OKX Demo private-read observation runtime.

This runtime is intentionally separate from the normal Demo trading start.  It
accepts only a capability-minimal private GET snapshot provider and a private
WebSocket subscriber/reader.  No order, cancel, transfer, withdraw, or live
capability is reachable from the service graph.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, Sequence

from quant_crypto.application.btc_demo_start_attempt import (
    authoritative_account_identity_snapshot,
)
from quant_crypto.oms.okx_demo import (
    OKX_DEMO_INSTRUMENT_ID,
    OkxDemoReadOnlyClient,
    OkxDemoResponse,
)
from quant_crypto.research.btc_demo_observation_accumulator import (
    PRIVATE_READONLY_EVIDENCE_CLASS,
    append_hourly_observation_receipt,
    build_hourly_observation_receipt,
    load_observation_receipt_ledger,
    stable_payload_hash,
)


BTC_DEMO_PRIVATE_READONLY_RUNTIME_VERSION = (
    "btc_demo_private_readonly_observation_runner_v1"
)
STATE_SCHEMA_VERSION = "btc_demo_private_readonly_observation_state_v1"
OWNER_SCHEMA_VERSION = "btc_demo_private_readonly_observation_owner_v1"
EVENT_SCHEMA_VERSION = "btc_demo_private_readonly_observation_event_v1"
PRIVATE_RECEIPT_SCHEMA_VERSION = (
    "btc_demo_private_readonly_hourly_observation_extension_v1"
)
EXPECTED_PRIVATE_GET_PATHS = (
    "/api/v5/account/config",
    "/api/v5/account/balance",
    "/api/v5/account/positions",
    "/api/v5/account/leverage-info",
    "/api/v5/trade/orders-pending",
    "/api/v5/trade/orders-algo-pending",
    "/api/v5/trade/orders-history",
    "/api/v5/trade/fills",
    "/api/v5/account/bills",
)
DENIED_WRITE_MEMBERS = (
    "post",
    "private_post",
    "submit_order",
    "amend_order",
    "cancel_order",
    "cancel_algo_orders",
    "cancel_all_after",
    "transfer",
    "withdraw",
    "live_post",
)
_HEX_HEAD = re.compile(r"^[0-9a-f]{40,64}$")
_SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{7,127}$")
_SAFE_ERROR_FIELDS = (
    "endpoint",
    "http_status",
    "okx_code",
    "message",
    "demo_status",
    "region",
    "clock_status",
)
_SENSITIVE_ASSIGNMENT = re.compile(
    r"(?i)\b(?:api[ _-]?key|secret(?:[ _-]?key)?|passphrase|signature|token|"
    r"authorization|ok-access-(?:key|sign|passphrase))\b\s*[:=]\s*"
    r"(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)"
)
_LONG_TOKEN = re.compile(r"(?<![A-Za-z0-9])[A-Za-z0-9+/=_-]{20,}(?![A-Za-z0-9])")
_SAFE_MESSAGE_LIMIT = 160


@dataclass(frozen=True, slots=True)
class PrivateReadonlySafeError:
    """Strictly bounded exchange failure facts safe for logs and state."""

    endpoint: str
    http_status: int | None
    okx_code: str
    message: str
    demo_status: str
    region: str
    clock_status: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "endpoint", _safe_endpoint(self.endpoint))
        object.__setattr__(
            self,
            "http_status",
            int(self.http_status)
            if isinstance(self.http_status, int)
            and not isinstance(self.http_status, bool)
            else None,
        )
        object.__setattr__(self, "okx_code", _safe_okx_code(self.okx_code))
        object.__setattr__(self, "message", _sanitize_safe_message(self.message))
        object.__setattr__(
            self,
            "demo_status",
            self.demo_status
            if self.demo_status in {"simulated_trading", "environment_mismatch"}
            else "unknown",
        )
        object.__setattr__(self, "region", _normalize_region(self.region))
        object.__setattr__(
            self,
            "clock_status",
            self.clock_status
            if self.clock_status in {"unverified", "timestamp_expired"}
            else "unknown",
        )

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in _SAFE_ERROR_FIELDS}


class BTCPrivateReadonlyObservationError(RuntimeError):
    """The observation runtime could not preserve its read-only contract."""

    def __init__(
        self,
        error_code: str,
        *,
        safe_error: PrivateReadonlySafeError | None = None,
    ) -> None:
        super().__init__(error_code)
        self.error_code = str(error_code)
        self.safe_error = safe_error


class _SingleWriterLease:
    """Process-scoped OS lease; a crash releases the byte-range lock."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._handle: Any | None = None

    def acquire(self) -> None:
        if self._handle is not None:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        handle = self._path.open("a+b")
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, BlockingIOError) as exc:
            handle.close()
            raise BTCPrivateReadonlyObservationError(
                "private_readonly_single_writer_lease_held"
            ) from exc
        self._handle = handle

    def release(self) -> None:
        handle = self._handle
        self._handle = None
        if handle is None:
            return
        try:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()


@dataclass(frozen=True, slots=True)
class PrivateReadonlyCapability:
    environment: str = "OKX Demo"
    methods: tuple[str, ...] = ("GET",)
    private_get_paths: tuple[str, ...] = EXPECTED_PRIVATE_GET_PATHS
    websocket_operations: tuple[str, ...] = ("subscribe", "read")
    allow_private_read: bool = True
    allow_demo_orders: bool = False
    allow_demo_cancels: bool = False
    allow_transfer: bool = False
    allow_withdraw: bool = False
    allow_live: bool = False


class PrivateReadonlySnapshotProvider(Protocol):
    capability: PrivateReadonlyCapability

    def read_snapshot(self) -> Mapping[str, Any]: ...


class PrivateReadonlyWebSocket(Protocol):
    capability: PrivateReadonlyCapability

    def start(self) -> Mapping[str, Any]: ...

    def status(self) -> Mapping[str, Any]: ...

    def reconcile_current(self) -> Mapping[str, Any]: ...

    def drain_events(self) -> Sequence[Mapping[str, Any]]: ...

    def stop(self) -> Mapping[str, Any]: ...


@dataclass(frozen=True, slots=True)
class BTCPrivateReadonlyObservationConfig:
    runtime_root: Path
    source_head: str
    run_id: str
    private_read_authorized: bool
    private_authorization_ticket_hash: str
    runtime_version: str = BTC_DEMO_PRIVATE_READONLY_RUNTIME_VERSION
    strategy_version: str = "btc_demo_private_readonly_observation_v1"
    data_version: str = "okx_demo_private_rest_ws_observation_v1"

    def __post_init__(self) -> None:
        root = Path(self.runtime_root)
        if not root.is_absolute() or root == Path(root.anchor):
            raise BTCPrivateReadonlyObservationError(
                "private_readonly_runtime_root_invalid"
            )
        if not _HEX_HEAD.fullmatch(str(self.source_head or "")):
            raise BTCPrivateReadonlyObservationError(
                "private_readonly_source_head_invalid"
            )
        if not _SAFE_RUN_ID.fullmatch(str(self.run_id or "")):
            raise BTCPrivateReadonlyObservationError(
                "private_readonly_run_id_invalid"
            )
        if not self.runtime_version.strip():
            raise BTCPrivateReadonlyObservationError(
                "private_readonly_runtime_version_missing"
            )
        if not re.fullmatch(
            r"[0-9a-f]{64}", str(self.private_authorization_ticket_hash or "")
        ):
            raise BTCPrivateReadonlyObservationError(
                "private_readonly_authorization_ticket_hash_invalid"
            )

    @property
    def safety(self) -> dict[str, bool]:
        return {
            "allow_demo_orders": False,
            "allow_demo_cancels": False,
            "allow_transfer": False,
            "allow_withdraw": False,
            "allow_live": False,
            "real_order_allowed": False,
            "promotion_allowed": False,
            "paper_allowed": False,
        }

    @property
    def policy_digest(self) -> str:
        return stable_payload_hash(
            {
                "runtime_version": self.runtime_version,
                "environment": "OKX Demo",
                "private_rest_methods": ["GET"],
                "private_ws_operations": ["subscribe", "read"],
                "private_get_paths": list(EXPECTED_PRIVATE_GET_PATHS),
                "private_authorization_ticket_hash": (
                    self.private_authorization_ticket_hash
                ),
                "safety": self.safety,
            }
        )


class OkxDemoPrivateReadObservationProvider:
    """Snapshot adapter over the capability-minimal OKX Demo reader."""

    capability = PrivateReadonlyCapability()

    def __init__(self, client: OkxDemoReadOnlyClient) -> None:
        self._client = client
        self._last_snapshot: dict[str, Any] = {}

    def _private_get(
        self,
        path: str,
        params: Mapping[str, Any] | None = None,
    ) -> list[Mapping[str, Any]]:
        if path not in EXPECTED_PRIVATE_GET_PATHS:
            raise BTCPrivateReadonlyObservationError(
                "private_readonly_private_get_path_forbidden"
            )
        return _response_rows(self._client.private_get(path, params), path=path)

    def _public_get(
        self,
        path: str,
        params: Mapping[str, Any] | None = None,
    ) -> list[Mapping[str, Any]]:
        return _response_rows(self._client.public_get(path, params), path=path)

    def read_snapshot(self) -> Mapping[str, Any]:
        account = self._private_get("/api/v5/account/config")
        balance = self._private_get(
            "/api/v5/account/balance", {"ccy": "USDT"}
        )
        positions = self._private_get(
            "/api/v5/account/positions",
            {"instType": "SWAP", "instId": OKX_DEMO_INSTRUMENT_ID},
        )
        pending = self._private_get(
            "/api/v5/trade/orders-pending",
            {"instType": "SWAP", "instId": OKX_DEMO_INSTRUMENT_ID},
        )
        algos = self._private_get(
            "/api/v5/trade/orders-algo-pending",
            {"instId": OKX_DEMO_INSTRUMENT_ID, "ordType": "oco"},
        )
        orders = self._private_get(
            "/api/v5/trade/orders-history",
            {
                "instType": "SWAP",
                "instId": OKX_DEMO_INSTRUMENT_ID,
                "limit": "100",
            },
        )
        fills = self._private_get(
            "/api/v5/trade/fills",
            {
                "instType": "SWAP",
                "instId": OKX_DEMO_INSTRUMENT_ID,
                "limit": "100",
            },
        )
        bills = self._private_get(
            "/api/v5/account/bills",
            {
                "instType": "SWAP",
                "instId": OKX_DEMO_INSTRUMENT_ID,
                "limit": "100",
            },
        )
        leverage = self._private_get(
            "/api/v5/account/leverage-info",
            {"instId": OKX_DEMO_INSTRUMENT_ID, "mgnMode": "isolated"},
        )
        funding = self._public_get(
            "/api/v5/public/funding-rate",
            {"instId": OKX_DEMO_INSTRUMENT_ID},
        )
        snapshot = {
            "environment": "OKX Demo",
            "instrument_id": OKX_DEMO_INSTRUMENT_ID,
            "captured_at_utc": _iso(datetime.now(timezone.utc)),
            "account_config": dict(account[0]) if account else {},
            "balance": dict(balance[0]) if balance else {},
            "positions": positions,
            "pending_orders": pending,
            "pending_algo_orders": algos,
            "orders": orders,
            "fills": fills,
            "bills": bills,
            "leverage": leverage,
            "funding": dict(funding[0]) if funding else {},
        }
        self._last_snapshot = snapshot
        return json.loads(json.dumps(snapshot))

    def observed_client_order_ids(self) -> tuple[str, ...]:
        """Return account-observed IDs solely for read-side WS reconciliation.

        These IDs are not claimed as locally submitted or owned.  They prevent
        the existing reconnect reconciler from discarding account truth while
        the private-readonly runner has intentionally registered no OMS.
        """

        snapshot = self._last_snapshot or dict(self.read_snapshot())
        values: list[str] = []
        for container in (
            "pending_orders",
            "pending_algo_orders",
            "orders",
            "fills",
        ):
            for row in _rows(snapshot.get(container)):
                value = str(row.get("clOrdId") or row.get("client_order_id") or "")
                if value:
                    values.append(value)
        return tuple(_dedupe(values))


class OkxDemoPrivateReadonlyWSAdapter:
    """Read-only facade around the existing private WS transport.

    The injected factory receives observation callbacks.  The facade never
    exposes the transport object, so no future write member on the transport is
    accidentally registered in the runner composition root.
    """

    capability = PrivateReadonlyCapability(
        private_get_paths=(), websocket_operations=("subscribe", "read")
    )

    def __init__(
        self,
        transport_factory: Callable[
            [Callable[[str], None], Callable[[Mapping[str, Any]], None]], Any
        ],
    ) -> None:
        self._factory = transport_factory
        self._transport: Any | None = None
        self._events: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    def _on_disconnect(self, reason: str) -> None:
        with self._lock:
            self._events.append(
                {"kind": "private_ws_disconnected", "reason_code": str(reason)}
            )

    def _on_reconciled(self, receipt: Mapping[str, Any]) -> None:
        with self._lock:
            self._events.append(
                {
                    "kind": "private_ws_reconciled",
                    "reconciled": receipt.get("opening_allowed") is True,
                    "blockers": _blockers(receipt),
                }
            )

    def start(self) -> Mapping[str, Any]:
        if self._transport is not None:
            return self.status()
        transport = self._factory(self._on_disconnect, self._on_reconciled)
        _assert_no_write_surface(transport)
        probe = transport.run_startup_reconnect_probe()
        if probe.get("opening_allowed_after_reconciliation") is not True:
            try:
                transport.stop()
            finally:
                raise BTCPrivateReadonlyObservationError(
                    "private_readonly_private_ws_startup_reconciliation_failed"
                )
        transport.start_monitoring()
        self._transport = transport
        return self.status()

    def status(self) -> Mapping[str, Any]:
        raw = self._transport.status() if self._transport is not None else {}
        connected = raw.get("connected") is True
        listener_alive = raw.get("listener_alive") is True
        return {
            "connected": connected,
            "listener_alive": listener_alive,
            "reconnect_login_observed": raw.get("reconnect_login_observed") is True,
            "reconnect_resubscribed": raw.get("reconnect_resubscribed") is True,
            "observation_healthy": connected and listener_alive,
            "blockers": _blockers(raw),
        }

    def reconcile_current(self) -> Mapping[str, Any]:
        if self._transport is None:
            return {
                "reconciled": False,
                "blockers": ["private_readonly_private_ws_not_started"],
            }
        raw = self._transport.reconcile_current()
        return {
            "reconciled": (
                raw.get("opening_allowed_after_reconciliation") is True
                and raw.get("connected") is True
                and raw.get("listener_alive") is True
            ),
            "blockers": _blockers(raw),
        }

    def drain_events(self) -> Sequence[Mapping[str, Any]]:
        with self._lock:
            events = [dict(row) for row in self._events]
            self._events.clear()
        return events

    def stop(self) -> Mapping[str, Any]:
        if self._transport is None:
            return {"stopped": True}
        try:
            result = self._transport.stop()
            return {"stopped": True, "listener_joined": result.get("listener_joined")}
        finally:
            self._transport = None


class BTCPrivateReadonlyObservationRunner:
    def __init__(
        self,
        *,
        config: BTCPrivateReadonlyObservationConfig,
        snapshot_provider: PrivateReadonlySnapshotProvider,
        private_ws: PrivateReadonlyWebSocket,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.config = config
        self._snapshot_provider = snapshot_provider
        self._private_ws = private_ws
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._state: dict[str, Any] = {}
        self._lease: _SingleWriterLease | None = None

    @property
    def _state_path(self) -> Path:
        return self.config.runtime_root / "state.json"

    @property
    def _owner_path(self) -> Path:
        return self.config.runtime_root / "owner.json"

    @property
    def _event_path(self) -> Path:
        return self.config.runtime_root / "events.jsonl"

    @property
    def _receipt_path(self) -> Path:
        return (
            self.config.runtime_root
            / "observation"
            / "hourly_observation_receipts.jsonl"
        )

    def start(self) -> dict[str, Any]:
        self._validate_graph()
        self._prepare_root()
        self._lease = _SingleWriterLease(self.config.runtime_root / "writer.lock")
        self._lease.acquire()
        try:
            return self._start_locked()
        except Exception:
            try:
                self._private_ws.stop()
            finally:
                self._release_lease()
            raise

    def _start_locked(self) -> dict[str, Any]:
        previous = self._load_state()
        restart_count = int(previous.get("restart_count") or 0)
        if previous:
            self._validate_persisted_identity(previous)
            restart_count += 1
        try:
            snapshot = self._read_snapshot()
        except BTCPrivateReadonlyObservationError as exc:
            self._state = self._blocked_state(
                previous=previous,
                blocker="private_readonly_snapshot_failed",
                restart_count=restart_count,
                safe_error=exc.safe_error,
            )
            self._persist_state()
            self._append_event(
                "runner_blocked",
                blockers=["private_readonly_snapshot_failed"],
            )
            raise
        account_hash = self._account_hash(snapshot)
        previous_hash = str(previous.get("account_identity_hash") or "")
        if previous_hash and account_hash != previous_hash:
            self._state = self._blocked_state(
                previous=previous,
                blocker="private_readonly_account_identity_changed",
                restart_count=restart_count,
            )
            self._persist_state()
            raise BTCPrivateReadonlyObservationError(
                "private_readonly_account_identity_changed"
            )
        try:
            self._private_ws.start()
            ws_status = dict(self._private_ws.status())
            ws_reconcile = dict(self._private_ws.reconcile_current())
        except Exception as exc:
            self._state = self._blocked_state(
                previous=previous,
                blocker="private_readonly_private_ws_start_failed",
                restart_count=restart_count,
            )
            self._persist_state()
            raise BTCPrivateReadonlyObservationError(
                "private_readonly_private_ws_start_failed"
            ) from exc
        health = self._health(snapshot, ws_status, ws_reconcile)
        now = _utc(self._clock())
        self._state = {
            "schema_version": STATE_SCHEMA_VERSION,
            "runtime_version": self.config.runtime_version,
            "source_head": self.config.source_head,
            "run_id": self.config.run_id,
            "policy_digest": self.config.policy_digest,
            "private_authorization_ticket_hash": (
                self.config.private_authorization_ticket_hash
            ),
            "account_identity_hash": account_hash,
            "phase": "observing" if health["healthy"] else "blocked",
            "started_at_utc": str(previous.get("started_at_utc") or _iso(now)),
            "last_started_at_utc": _iso(now),
            "last_observed_at_utc": _iso(now),
            "eligible_since_utc": _iso(now),
            "current_hour_gap_flags": [],
            "restart_count": restart_count,
            "recovery_count": int(previous.get("recovery_count") or 0),
            "state_revision": int(previous.get("state_revision") or 0) + 1,
            "last_receipt_hour_utc": str(
                previous.get("last_receipt_hour_utc") or ""
            ),
            "reconciliation": self._reconciliation_projection(
                snapshot, ws_status, ws_reconcile, health
            ),
            "funding": self._funding_projection(snapshot),
            "private_ws": self._ws_projection(ws_status, ws_reconcile),
            "blockers": health["blockers"],
            "safety": self.config.safety,
        }
        self._persist_state()
        self._append_event("runner_started", blockers=health["blockers"])
        if not health["healthy"]:
            raise BTCPrivateReadonlyObservationError(
                "private_readonly_start_reconciliation_failed"
            )
        return self.status()

    def poll(self) -> dict[str, Any]:
        if self._state.get("phase") != "observing":
            raise BTCPrivateReadonlyObservationError(
                "private_readonly_runner_not_observing"
            )
        try:
            snapshot = self._read_snapshot()
        except BTCPrivateReadonlyObservationError as exc:
            self._block(
                "private_readonly_snapshot_failed",
                safe_error=exc.safe_error,
            )
            raise
        account_hash = self._account_hash(snapshot)
        if account_hash != self._state.get("account_identity_hash"):
            self._block("private_readonly_account_identity_changed")
            raise BTCPrivateReadonlyObservationError(
                "private_readonly_account_identity_changed"
            )
        events = [dict(row) for row in self._private_ws.drain_events()]
        ws_status = dict(self._private_ws.status())
        ws_reconcile = dict(self._private_ws.reconcile_current())
        health = self._health(snapshot, ws_status, ws_reconcile)
        if any(row.get("kind") == "private_ws_disconnected" for row in events):
            self._state["recovery_count"] = int(
                self._state.get("recovery_count") or 0
            ) + 1
            self._state["eligible_since_utc"] = _iso(_utc(self._clock()))
            self._state["current_hour_gap_flags"] = _dedupe(
                [
                    *list(self._state.get("current_hour_gap_flags") or []),
                    "private_readonly_private_ws_gap_observed",
                ]
            )
        if not health["healthy"]:
            self._state["eligible_since_utc"] = _iso(_utc(self._clock()))
            self._state["current_hour_gap_flags"] = _dedupe(
                [
                    *list(self._state.get("current_hour_gap_flags") or []),
                    *list(health["blockers"]),
                ]
            )
        self._state.update(
            {
                "last_observed_at_utc": _iso(_utc(self._clock())),
                "state_revision": int(self._state.get("state_revision") or 0) + 1,
                "reconciliation": self._reconciliation_projection(
                    snapshot, ws_status, ws_reconcile, health
                ),
                "funding": self._funding_projection(snapshot),
                "private_ws": self._ws_projection(ws_status, ws_reconcile),
                "phase": "observing" if health["healthy"] else "blocked",
                "blockers": health["blockers"],
                "safety": self.config.safety,
            }
        )
        self._capture_hourly_receipt(snapshot=snapshot, health=health)
        self._persist_state()
        for event in events:
            self._append_event(
                str(event.get("kind") or "private_ws_event"),
                blockers=_blockers(event),
            )
        if not health["healthy"]:
            raise BTCPrivateReadonlyObservationError(
                "private_readonly_observation_degraded"
            )
        return self.status()

    def stop(self) -> dict[str, Any]:
        try:
            result = dict(self._private_ws.stop())
            if not self._state:
                self._state = self._load_state()
            if self._state:
                was_blocked = self._state.get("phase") == "blocked"
                self._state.update(
                    {
                        "phase": "blocked" if was_blocked else "stopped",
                        "stopped_at_utc": _iso(_utc(self._clock())),
                        "state_revision": int(
                            self._state.get("state_revision") or 0
                        )
                        + 1,
                        "blockers": (
                            list(self._state.get("blockers") or [])
                            if was_blocked
                            else []
                        ),
                        "safety": self.config.safety,
                    }
                )
                self._persist_state()
                self._append_event("runner_stopped")
            return {**self.status(), "stop_receipt": result}
        finally:
            self._release_lease()

    def status(self) -> dict[str, Any]:
        return json.loads(json.dumps(self._state))

    def _validate_graph(self) -> None:
        if self.config.private_read_authorized is not True:
            raise BTCPrivateReadonlyObservationError(
                "private_readonly_private_permission_required"
            )
        for dependency in (self._snapshot_provider, self._private_ws):
            _assert_no_write_surface(dependency)
            capability = getattr(dependency, "capability", None)
            if not isinstance(capability, PrivateReadonlyCapability):
                raise BTCPrivateReadonlyObservationError(
                    "private_readonly_capability_missing"
                )
            if (
                capability.environment != "OKX Demo"
                or capability.methods != ("GET",)
                or capability.allow_private_read is not True
                or capability.allow_demo_orders
                or capability.allow_demo_cancels
                or capability.allow_transfer
                or capability.allow_withdraw
                or capability.allow_live
            ):
                raise BTCPrivateReadonlyObservationError(
                    "private_readonly_write_capability_forbidden"
                )
            if any(
                operation not in {"subscribe", "read"}
                for operation in capability.websocket_operations
            ):
                raise BTCPrivateReadonlyObservationError(
                    "private_readonly_ws_operation_forbidden"
                )
            if any(
                path not in EXPECTED_PRIVATE_GET_PATHS
                for path in capability.private_get_paths
            ):
                raise BTCPrivateReadonlyObservationError(
                    "private_readonly_private_get_path_forbidden"
                )

    def _prepare_root(self) -> None:
        self.config.runtime_root.mkdir(parents=True, exist_ok=True)
        owner = {
            "schema_version": OWNER_SCHEMA_VERSION,
            "source_head": self.config.source_head,
            "run_id": self.config.run_id,
            "runtime_version": self.config.runtime_version,
            "policy_digest": self.config.policy_digest,
            "private_authorization_ticket_hash": (
                self.config.private_authorization_ticket_hash
            ),
            "safety": self.config.safety,
        }
        if self._owner_path.is_file():
            existing = _read_json(self._owner_path)
            if existing != owner:
                raise BTCPrivateReadonlyObservationError(
                    "private_readonly_runtime_owner_mismatch"
                )
        else:
            _write_json_atomic(self._owner_path, owner)

    def _validate_persisted_identity(self, state: Mapping[str, Any]) -> None:
        expected = {
            "schema_version": STATE_SCHEMA_VERSION,
            "runtime_version": self.config.runtime_version,
            "source_head": self.config.source_head,
            "run_id": self.config.run_id,
            "policy_digest": self.config.policy_digest,
            "private_authorization_ticket_hash": (
                self.config.private_authorization_ticket_hash
            ),
        }
        if any(state.get(key) != value for key, value in expected.items()):
            raise BTCPrivateReadonlyObservationError(
                "private_readonly_persisted_identity_mismatch"
            )

    def _read_snapshot(self) -> dict[str, Any]:
        try:
            snapshot = dict(self._snapshot_provider.read_snapshot())
        except BTCPrivateReadonlyObservationError as exc:
            raise BTCPrivateReadonlyObservationError(
                "private_readonly_snapshot_failed",
                safe_error=exc.safe_error,
            ) from None
        except Exception:
            raise BTCPrivateReadonlyObservationError(
                "private_readonly_snapshot_failed"
            ) from None
        if (
            snapshot.get("environment") != "OKX Demo"
            or snapshot.get("instrument_id") != OKX_DEMO_INSTRUMENT_ID
            or not isinstance(snapshot.get("account_config"), Mapping)
            or not str(snapshot.get("captured_at_utc") or "")
        ):
            raise BTCPrivateReadonlyObservationError(
                "private_readonly_snapshot_invalid"
            )
        return snapshot

    def _account_hash(self, snapshot: Mapping[str, Any]) -> str:
        identity = authoritative_account_identity_snapshot(
            _mapping(snapshot.get("account_config")),
            captured_at_utc=str(snapshot.get("captured_at_utc") or ""),
        )
        value = str(identity.get("hash") or "")
        if not re.fullmatch(r"[0-9a-f]{64}", value):
            raise BTCPrivateReadonlyObservationError(
                "private_readonly_account_identity_missing"
            )
        return value

    def _health(
        self,
        snapshot: Mapping[str, Any],
        ws_status: Mapping[str, Any],
        ws_reconcile: Mapping[str, Any],
    ) -> dict[str, Any]:
        blockers = [*_blockers(ws_status), *_blockers(ws_reconcile)]
        if ws_status.get("connected") is not True:
            blockers.append("private_readonly_private_ws_not_connected")
        if ws_status.get("listener_alive") is not True:
            blockers.append("private_readonly_private_ws_listener_not_alive")
        if ws_reconcile.get("reconciled") is not True:
            blockers.append("private_readonly_private_ws_not_reconciled")
        if not _mapping(snapshot.get("balance")):
            blockers.append("private_readonly_balance_missing")
        blockers.extend(self._permission_projection(snapshot)["blockers"])
        funding = self._funding_projection(snapshot)
        blockers.extend(funding["blockers"])
        normalized = _dedupe(blockers)
        return {"healthy": not normalized, "blockers": normalized}

    def _reconciliation_projection(
        self,
        snapshot: Mapping[str, Any],
        ws_status: Mapping[str, Any],
        ws_reconcile: Mapping[str, Any],
        health: Mapping[str, Any],
    ) -> dict[str, Any]:
        containers = {
            name: _rows(snapshot.get(name))
            for name in (
                "positions",
                "pending_orders",
                "pending_algo_orders",
                "orders",
                "fills",
                "bills",
                "leverage",
            )
        }
        digest_payload = {
            "balance": _mapping(snapshot.get("balance")),
            **containers,
        }
        return {
            "snapshot_reconciled": health.get("healthy") is True,
            "rest_snapshot_observed": True,
            "private_ws_reconciled": ws_reconcile.get("reconciled") is True,
            "private_ws_connected": ws_status.get("connected") is True,
            "snapshot_sha256": stable_payload_hash(digest_payload),
            "counts": {name: len(rows) for name, rows in containers.items()},
            "captured_at_utc": str(snapshot.get("captured_at_utc") or ""),
            "permission": self._permission_projection(snapshot),
            "blockers": list(health.get("blockers") or []),
        }

    def _permission_projection(self, snapshot: Mapping[str, Any]) -> dict[str, Any]:
        raw = str(_mapping(snapshot.get("account_config")).get("perm") or "")
        permissions = sorted(
            {item.strip().lower() for item in raw.split(",") if item.strip()}
        )
        allowed = {"read", "readonly", "read_only"}
        blockers: list[str] = []
        if not permissions:
            blockers.append("private_readonly_account_permission_missing")
        elif any(item not in allowed for item in permissions):
            blockers.append("private_readonly_account_permission_not_readonly")
        return {
            "readonly_proven": bool(permissions) and not blockers,
            "permission_set_sha256": stable_payload_hash(permissions),
            "blockers": blockers,
        }

    def _funding_projection(self, snapshot: Mapping[str, Any]) -> dict[str, Any]:
        bills = [
            row
            for row in _rows(snapshot.get("bills"))
            if str(row.get("type") or "") == "8"
            or str(row.get("sub_type") or row.get("subType") or "") == "173"
        ]
        total = Decimal("0")
        blockers: list[str] = []
        for row in bills:
            raw = row.get("balance_change", row.get("balChg"))
            observed = row.get("balance_change_observed")
            try:
                value = Decimal(str(raw))
            except (InvalidOperation, TypeError, ValueError):
                blockers.append("private_readonly_funding_cashflow_invalid")
                continue
            if not value.is_finite() or observed is False:
                blockers.append("private_readonly_funding_cashflow_unknown")
                continue
            total += value
        return {
            "observation_count": len(bills),
            "cashflow": float(total),
            "funding_rate": str(
                _mapping(snapshot.get("funding")).get("funding_rate")
                or _mapping(snapshot.get("funding")).get("fundingRate")
                or ""
            ),
            "funding_bill_set_sha256": stable_payload_hash(bills),
            "reconciled": not blockers,
            "blockers": _dedupe(blockers),
        }

    def _ws_projection(
        self,
        status: Mapping[str, Any],
        reconcile: Mapping[str, Any],
    ) -> dict[str, Any]:
        return {
            "connected": status.get("connected") is True,
            "listener_alive": status.get("listener_alive") is True,
            "reconciled": reconcile.get("reconciled") is True,
            "reconnect_login_observed": (
                status.get("reconnect_login_observed") is True
            ),
            "reconnect_resubscribed": (
                status.get("reconnect_resubscribed") is True
            ),
            "blockers": _dedupe([*_blockers(status), *_blockers(reconcile)]),
        }

    def _capture_hourly_receipt(
        self,
        *,
        snapshot: Mapping[str, Any],
        health: Mapping[str, Any],
    ) -> None:
        now = _utc(self._clock())
        started = _parse_utc(self._state.get("started_at_utc"))
        if started is None or (now - started).total_seconds() < 3600:
            return
        hour = now.replace(minute=0, second=0, microsecond=0)
        hour_key = _iso(hour)
        if self._state.get("last_receipt_hour_utc") == hour_key:
            return
        existing = load_observation_receipt_ledger(self._receipt_path)
        if any(row.get("observation_hour_utc") == hour_key for row in existing):
            self._state["last_receipt_hour_utc"] = hour_key
            return
        eligible_since = _parse_utc(self._state.get("eligible_since_utc"))
        gap_flags = list(self._state.get("current_hour_gap_flags") or [])
        if eligible_since is None or eligible_since > hour - timedelta(hours=1):
            gap_flags.append("private_readonly_incomplete_hour")
        gap_flags.extend(list(health.get("blockers") or []))
        interval_start = hour - timedelta(hours=1)
        hourly_fills, fill_blockers = _hourly_unique_rows(
            _rows(snapshot.get("fills")),
            interval_start=interval_start,
            interval_end=hour,
            identity_fields=("fill_id", "fillId", "tradeId"),
            timestamp_fields=("timestamp_ms", "ts", "fillTime", "timestamp"),
            blocker_prefix="private_readonly_fill",
        )
        hourly_bills, funding_blockers = _hourly_unique_rows(
            [
                row
                for row in _rows(snapshot.get("bills"))
                if str(row.get("type") or "") == "8"
                or str(row.get("sub_type") or row.get("subType") or "") == "173"
            ],
            interval_start=interval_start,
            interval_end=hour,
            identity_fields=("bill_id", "billId"),
            timestamp_fields=("timestamp_ms", "ts", "timestamp"),
            blocker_prefix="private_readonly_funding",
        )
        gap_flags.extend(fill_blockers)
        gap_flags.extend(funding_blockers)
        gap_flags = _dedupe(gap_flags)
        hourly_funding = self._funding_projection({
            "bills": hourly_bills,
            "funding": snapshot.get("funding", {}),
        })
        gap_flags.extend(hourly_funding["blockers"])
        gap_flags = _dedupe(gap_flags)
        previous_hash = (
            str(existing[-1].get("receipt_sha256") or "") if existing else None
        )
        receipt = build_hourly_observation_receipt(
            source_head=self.config.source_head,
            strategy_version=self.config.strategy_version,
            data_version=self.config.data_version,
            runtime_version=self.config.runtime_version,
            observed_at_utc=now,
            heartbeat_status="healthy" if health.get("healthy") is True else "degraded",
            natural_sample_count=1,
            fill_count=len(hourly_fills),
            funding_observation_count=int(hourly_funding["observation_count"]),
            funding_cashflow=float(hourly_funding["cashflow"]),
            reconciliation_status=(
                "reconciled" if health.get("healthy") is True else "mismatch"
            ),
            outage_count=(
                1
                if any(
                    "outage" in flag
                    or "private_ws_gap" in flag
                    or "disconnected" in flag
                    for flag in gap_flags
                )
                else 0
            ),
            gap_flags=gap_flags,
            previous_receipt_sha256=previous_hash,
            authorized_runtime_observed=True,
            runtime_run_id=self.config.run_id,
            evidence_class=PRIVATE_READONLY_EVIDENCE_CLASS,
            private_read_authorized=True,
            private_read_used=True,
            private_endpoint_called=True,
            network_used=True,
            secret_read=True,
            demo_runtime_started=True,
        )
        receipt["private_readonly_observation"] = {
            "schema_version": PRIVATE_RECEIPT_SCHEMA_VERSION,
            "account_identity_hash": self._state["account_identity_hash"],
            "policy_digest": self.config.policy_digest,
            "snapshot_sha256": self._reconciliation_projection(
                snapshot,
                self._state.get("private_ws", {}),
                {"reconciled": health.get("healthy") is True},
                health,
            )["snapshot_sha256"],
            "private_rest_method": "GET",
            "private_ws_operations": ["subscribe", "read"],
            "funding_reconciled": hourly_funding["reconciled"],
            "event_interval_start_utc": _iso(interval_start),
            "event_interval_end_utc": _iso(hour),
            "orders_registered": False,
            "cancels_registered": False,
        }
        receipt["receipt_sha256"] = stable_payload_hash(
            receipt, exclude={"receipt_sha256"}
        )
        append_hourly_observation_receipt(
            ledger_path=self._receipt_path, receipt=receipt
        )
        self._state["last_receipt_hour_utc"] = hour_key
        self._state["last_receipt_sha256"] = receipt["receipt_sha256"]
        self._state["current_hour_gap_flags"] = []

    def _blocked_state(
        self,
        *,
        previous: Mapping[str, Any],
        blocker: str,
        restart_count: int,
        safe_error: PrivateReadonlySafeError | None = None,
    ) -> dict[str, Any]:
        state = {
            "schema_version": STATE_SCHEMA_VERSION,
            "runtime_version": self.config.runtime_version,
            "source_head": self.config.source_head,
            "run_id": self.config.run_id,
            "policy_digest": self.config.policy_digest,
            "private_authorization_ticket_hash": (
                self.config.private_authorization_ticket_hash
            ),
            "account_identity_hash": str(
                previous.get("account_identity_hash") or ""
            ),
            "phase": "blocked",
            "started_at_utc": str(previous.get("started_at_utc") or ""),
            "last_observed_at_utc": _iso(_utc(self._clock())),
            "restart_count": restart_count,
            "recovery_count": int(previous.get("recovery_count") or 0),
            "state_revision": int(previous.get("state_revision") or 0) + 1,
            "blockers": [blocker],
            "reconciliation": {"snapshot_reconciled": False},
            "funding": {"reconciled": False},
            "private_ws": {"connected": False, "reconciled": False},
            "safety": self.config.safety,
        }
        if safe_error is not None:
            state["safe_error"] = safe_error.to_dict()
        return state

    def _block(
        self,
        blocker: str,
        *,
        safe_error: PrivateReadonlySafeError | None = None,
    ) -> None:
        self._state.update(
            {
                "phase": "blocked",
                "blockers": [blocker],
                "state_revision": int(self._state.get("state_revision") or 0) + 1,
                "safety": self.config.safety,
            }
        )
        if safe_error is not None:
            self._state["safe_error"] = safe_error.to_dict()
        self._persist_state()
        self._append_event("runner_blocked", blockers=[blocker])

    def _load_state(self) -> dict[str, Any]:
        return dict(_read_json(self._state_path)) if self._state_path.is_file() else {}

    def _persist_state(self) -> None:
        _write_json_atomic(self._state_path, self._state)

    def _release_lease(self) -> None:
        lease = self._lease
        self._lease = None
        if lease is not None:
            lease.release()

    def _append_event(
        self,
        kind: str,
        *,
        blockers: Sequence[str] = (),
    ) -> None:
        previous_hash = ""
        if self._event_path.is_file():
            lines = [
                line
                for line in self._event_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            if lines:
                previous_hash = str(json.loads(lines[-1]).get("event_sha256") or "")
        event = {
            "schema_version": EVENT_SCHEMA_VERSION,
            "event_kind": kind,
            "observed_at_utc": _iso(_utc(self._clock())),
            "source_head": self.config.source_head,
            "run_id": self.config.run_id,
            "policy_digest": self.config.policy_digest,
            "state_revision": int(self._state.get("state_revision") or 0),
            "previous_event_sha256": previous_hash or None,
            "blockers": _dedupe(blockers),
            "safety": self.config.safety,
        }
        event["event_sha256"] = stable_payload_hash(event)
        self._event_path.parent.mkdir(parents=True, exist_ok=True)
        with self._event_path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(event, sort_keys=True, separators=(",", ":")))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())


def _hourly_unique_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    interval_start: datetime,
    interval_end: datetime,
    identity_fields: Sequence[str],
    timestamp_fields: Sequence[str],
    blocker_prefix: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    selected: dict[str, dict[str, Any]] = {}
    blockers: list[str] = []
    for source in rows:
        row = dict(source)
        event_time = _row_event_time(row, timestamp_fields)
        if event_time is None:
            blockers.append(f"{blocker_prefix}_timestamp_invalid")
            continue
        if not interval_start <= event_time < interval_end:
            continue
        identity = next(
            (
                str(row.get(field) or "").strip()
                for field in identity_fields
                if str(row.get(field) or "").strip()
            ),
            "",
        )
        if not identity:
            blockers.append(f"{blocker_prefix}_identity_missing")
            continue
        prior = selected.get(identity)
        if prior is not None and stable_payload_hash(prior) != stable_payload_hash(row):
            blockers.append(f"{blocker_prefix}_conflicting_duplicate")
            continue
        selected[identity] = row
    return list(selected.values()), _dedupe(blockers)


def _row_event_time(
    row: Mapping[str, Any],
    timestamp_fields: Sequence[str],
) -> datetime | None:
    for field in timestamp_fields:
        raw = row.get(field)
        if raw is None or str(raw).strip() == "":
            continue
        text = str(raw).strip()
        if re.fullmatch(r"\d{10,16}", text):
            try:
                milliseconds = int(text)
                if len(text) == 10:
                    milliseconds *= 1000
                return datetime.fromtimestamp(
                    milliseconds / 1000, tz=timezone.utc
                )
            except (OverflowError, OSError, ValueError):
                return None
        return _parse_utc(text)
    return None


def _assert_no_write_surface(value: Any) -> None:
    if any(hasattr(value, member) for member in DENIED_WRITE_MEMBERS):
        raise BTCPrivateReadonlyObservationError(
            "private_readonly_write_surface_reachable"
        )


def _response_rows(
    response: Any,
    *,
    path: str,
    region: str = "global",
) -> list[Mapping[str, Any]]:
    if (
        not isinstance(response, OkxDemoResponse)
        or response.method != "GET"
        or response.path.split("?", 1)[0] != path
        or response.ok is not True
    ):
        safe_error = (
            _safe_response_error(response, path=path, region=region)
            if isinstance(response, OkxDemoResponse)
            else None
        )
        raise BTCPrivateReadonlyObservationError(
            "private_readonly_get_response_invalid",
            safe_error=safe_error,
        )
    return [dict(row) for row in response.data if isinstance(row, Mapping)]


def _safe_response_error(
    response: OkxDemoResponse,
    *,
    path: str,
    region: str,
) -> PrivateReadonlySafeError:
    code = _safe_okx_code(response.code)
    return PrivateReadonlySafeError(
        endpoint=_safe_endpoint(path),
        http_status=(
            int(response.http_status)
            if isinstance(response.http_status, int)
            and not isinstance(response.http_status, bool)
            else None
        ),
        okx_code=code,
        message=_sanitize_safe_message(response.message),
        demo_status=(
            "environment_mismatch" if code == "50101" else "simulated_trading"
        ),
        region=_normalize_region(region),
        clock_status=("timestamp_expired" if code == "50102" else "unverified"),
    )


def _safe_endpoint(path: str) -> str:
    endpoint = str(path).split("?", 1)[0]
    endpoint = "".join(character for character in endpoint if character.isprintable())
    return endpoint if endpoint in EXPECTED_PRIVATE_GET_PATHS else "unknown"


def _safe_okx_code(value: Any) -> str:
    text = str(value or "unknown").strip()
    return text if re.fullmatch(r"[A-Za-z0-9_-]{1,16}", text) else "unknown"


def _normalize_region(value: Any) -> str:
    text = str(value or "unknown").strip().lower().replace("_", "-")
    aliases = {
        "global": "global",
        "www.okx.com": "global",
        "openapi.okx.com": "global",
        "us": "us",
        "eu": "eu",
    }
    return aliases.get(text, "unknown")


def _sanitize_safe_message(value: Any) -> str:
    text = " ".join(
        "".join(character if character.isprintable() else " " for character in str(value or ""))
        .split()
    )
    text = _SENSITIVE_ASSIGNMENT.sub("<redacted>", text)
    text = _LONG_TOKEN.sub("<redacted>", text)
    return text[:_SAFE_MESSAGE_LIMIT]


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(
        prefix=path.name + ".", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, ensure_ascii=True, sort_keys=True, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def _read_json(path: Path) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BTCPrivateReadonlyObservationError(
            "private_readonly_persisted_json_invalid"
        ) from exc
    if not isinstance(value, Mapping):
        raise BTCPrivateReadonlyObservationError(
            "private_readonly_persisted_object_required"
        )
    return value


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _rows(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [dict(row) for row in value if isinstance(row, Mapping)]
    return []


def _blockers(value: Mapping[str, Any]) -> list[str]:
    raw = value.get("blockers")
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes, bytearray)):
        return []
    return _dedupe(str(row) for row in raw if str(row))


def _dedupe(values: Sequence[str] | Any) -> list[str]:
    return list(dict.fromkeys(str(value) for value in values if str(value)))


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise BTCPrivateReadonlyObservationError(
            "private_readonly_clock_timezone_required"
        )
    return value.astimezone(timezone.utc)


def _parse_utc(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return _utc(value).isoformat()


__all__ = [
    "BTC_DEMO_PRIVATE_READONLY_RUNTIME_VERSION",
    "BTCPrivateReadonlyObservationConfig",
    "BTCPrivateReadonlyObservationError",
    "BTCPrivateReadonlyObservationRunner",
    "OkxDemoPrivateReadObservationProvider",
    "OkxDemoPrivateReadonlyWSAdapter",
    "PrivateReadonlyCapability",
]
