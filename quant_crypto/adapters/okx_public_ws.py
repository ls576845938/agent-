"""Public-only OKX WebSocket L2 normalization and recovery contracts.

The adapter deliberately has no strategy, risk, OMS, account, private-stream,
or order-entry dependency.  Network construction is opt-in and injectable;
the deterministic state machine consumes supplied public messages and emits
normalized market events only.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import zlib
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from importlib import import_module
from importlib.metadata import PackageNotFoundError, distribution
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from quant_crypto.monitoring.artifact_schema import stable_payload_hash
from quant_shared.core.time import ensure_utc


OKX_PUBLIC_WS_CONTRACT_VERSION = "okx_public_ws_l2_v1"
OKX_PUBLIC_WS_PACKAGE = "websocket-client>=1.8,<2"
OKX_PUBLIC_DISPLAY_INSTRUMENT_ID = "BTC-USDT-SWAP"
OKX_PUBLIC_DISPLAY_CHANNELS = ("trades", "books5")
OKX_PUBLIC_DISPLAY_URLS = (
    "wss://ws.okx.com:8443/ws/v5/public",
    "wss://wsaws.okx.com:8443/ws/v5/public",
)


class OKXPublicWSState(str, Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    SNAPSHOT_REQUIRED = "snapshot_required"
    READY = "ready"
    DEGRADED = "degraded"
    CANCEL_ONLY = "cancel_only"


class OKXPublicWSContractError(RuntimeError):
    """Stable fail-closed public market-data adapter error."""


@dataclass(frozen=True)
class OKXNormalizedL2Event:
    venue: str
    instrument_id: str
    channel: str
    action: str
    event_time_utc: datetime
    received_time_utc: datetime
    sequence: int
    previous_sequence: int
    checksum: int | None
    bids: tuple[tuple[str, str], ...]
    asks: tuple[tuple[str, str], ...]
    source_payload_hash: str
    recovery: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_type": "normalized_market_l2",
            "contract_version": OKX_PUBLIC_WS_CONTRACT_VERSION,
            "venue": self.venue,
            "instrument_id": self.instrument_id,
            "channel": self.channel,
            "action": self.action,
            "event_time_utc": ensure_utc(self.event_time_utc).isoformat(),
            "received_time_utc": ensure_utc(self.received_time_utc).isoformat(),
            "sequence": self.sequence,
            "previous_sequence": self.previous_sequence,
            "checksum": self.checksum,
            "bids": [list(row) for row in self.bids],
            "asks": [list(row) for row in self.asks],
            "source_payload_hash": self.source_payload_hash,
            "recovery": self.recovery,
        }


def load_public_websocket_dependency() -> Any:
    """Load the public client lazily without constructing a connection."""

    try:
        module = import_module("websocket")
    except ModuleNotFoundError as exc:
        raise OKXPublicWSContractError(
            "btc_okx_websocket_client_dependency_missing"
        ) from exc
    if not callable(getattr(module, "create_connection", None)):
        raise OKXPublicWSContractError(
            "btc_okx_websocket_client_dependency_invalid"
        )
    return module


def public_websocket_dependency_receipt(
    loader: Callable[[], Any] = load_public_websocket_dependency,
) -> dict[str, Any]:
    """Return an import-only dependency receipt; never opens a socket."""

    blockers: list[str] = []
    module_name = ""
    module_version = ""
    distribution_name = ""
    distribution_version = ""
    distribution_root = ""
    module_path = ""
    module_sha256 = ""
    package_sha256 = ""
    allowlist_roots: list[str] = []
    for prefix in (sys.prefix, sys.base_prefix):
        root = str((Path(prefix) / "Lib" / "site-packages").resolve())
        if root not in allowlist_roots:
            allowlist_roots.append(root)
    allowlist_valid = False
    try:
        module = loader()
        module_name = str(getattr(module, "__name__", "websocket"))
        module_version = str(getattr(module, "__version__", "unknown"))
        raw_module_path = str(getattr(module, "__file__", "") or "")
        if raw_module_path:
            resolved_module_path = Path(raw_module_path).resolve()
            module_path = str(resolved_module_path)
            module_sha256 = hashlib.sha256(
                resolved_module_path.read_bytes()
            ).hexdigest()
            try:
                package = distribution("websocket-client")
            except PackageNotFoundError as exc:
                raise OKXPublicWSContractError(
                    "btc_okx_websocket_client_distribution_missing"
                ) from exc
            distribution_name = str(package.metadata.get("Name") or "")
            distribution_version = str(package.version or "")
            resolved_distribution_root = Path(
                package.locate_file("")
            ).resolve()
            distribution_root = str(resolved_distribution_root)
            record_path = Path(
                package.locate_file(
                    f"{package.metadata['Name'].replace('-', '_')}-"
                    f"{distribution_version}.dist-info/RECORD"
                )
            ).resolve()
            if not record_path.is_file():
                matches = tuple(
                    resolved_distribution_root.glob(
                        "websocket_client-*.dist-info/RECORD"
                    )
                )
                if len(matches) != 1:
                    raise OKXPublicWSContractError(
                        "btc_okx_websocket_client_record_missing"
                    )
                record_path = matches[0].resolve()
            package_sha256 = hashlib.sha256(
                record_path.read_bytes()
            ).hexdigest()
            allowed_roots = tuple(Path(root) for root in allowlist_roots)
            allowlist_valid = any(
                resolved_distribution_root == allowed_root
                and resolved_module_path.is_relative_to(allowed_root)
                for allowed_root in allowed_roots
            ) and (
                distribution_name.lower() == "websocket-client"
                and distribution_version == module_version
                and _supported_websocket_client_version(distribution_version)
            )
            if not allowlist_valid:
                blockers.append(
                    "btc_okx_websocket_client_dependency_not_allowlisted"
                )
    except OKXPublicWSContractError as exc:
        blockers.append(str(exc))
    return {
        "contract_version": "btc_okx_public_ws_dependency_v1",
        "package_requirement": OKX_PUBLIC_WS_PACKAGE,
        "distribution_name": distribution_name,
        "distribution_version": distribution_version,
        "distribution_root": distribution_root,
        "module_name": module_name,
        "module_version": module_version,
        "module_path": module_path,
        "module_sha256": module_sha256,
        "package_sha256": package_sha256,
        "allowlist_roots": allowlist_roots,
        "allowlist_valid": allowlist_valid,
        "user_site_consumed": bool(module_path) and not allowlist_valid,
        "import_safe": not blockers,
        "public_only": True,
        "network_accessed": False,
        "private_endpoint_accessed": False,
        "order_endpoint_accessed": False,
        "blockers": blockers,
    }


def _supported_websocket_client_version(version: str) -> bool:
    match = re.fullmatch(r"(\d+)\.(\d+)(?:\.(\d+))?", version)
    if not match:
        return False
    major, minor = (int(match.group(1)), int(match.group(2)))
    return major == 1 and minor >= 8


def build_public_display_subscription(
    *,
    instrument_id: str = OKX_PUBLIC_DISPLAY_INSTRUMENT_ID,
    channels: Sequence[str] = OKX_PUBLIC_DISPLAY_CHANNELS,
    public_url: str = OKX_PUBLIC_DISPLAY_URLS[0],
) -> dict[str, Any]:
    """Build the only subscription envelope allowed for display-only market data.

    This validates before any websocket construction and intentionally does not
    accept a credential, a private channel, or a caller-selected instrument.
    """
    if public_url not in OKX_PUBLIC_DISPLAY_URLS:
        raise OKXPublicWSContractError("btc_okx_public_display_url_not_allowlisted")
    if instrument_id != OKX_PUBLIC_DISPLAY_INSTRUMENT_ID:
        raise OKXPublicWSContractError("btc_okx_public_display_instrument_not_allowlisted")
    normalized = tuple(str(value) for value in channels)
    if normalized != OKX_PUBLIC_DISPLAY_CHANNELS:
        raise OKXPublicWSContractError("btc_okx_public_display_channel_not_allowlisted")
    return {
        "op": "subscribe",
        "args": [
            {"channel": channel, "instId": instrument_id}
            for channel in normalized
        ],
    }


class OKXPublicWSL2Adapter:
    """Fail-closed sequence/checksum/timestamp state for one public L2 book."""

    def __init__(
        self,
        *,
        instrument_id: str,
        channel: str = "books",
        checksum_required: bool = True,
        max_timestamp_gap_ms: int = 5_000,
    ) -> None:
        if not instrument_id:
            raise ValueError("instrument_id is required")
        if max_timestamp_gap_ms <= 0:
            raise ValueError("max_timestamp_gap_ms must be positive")
        self.instrument_id = instrument_id
        self.channel = channel
        self.checksum_required = bool(checksum_required)
        self.max_timestamp_gap_ms = int(max_timestamp_gap_ms)
        self.state = OKXPublicWSState.DISCONNECTED
        self.last_sequence: int | None = None
        self.last_event_time_ms: int | None = None
        self.bids: dict[str, str] = {}
        self.asks: dict[str, str] = {}
        self.gaps: list[dict[str, Any]] = []
        self.reconnect_count = 0
        self.cancel_only = True

    def on_connected(self) -> None:
        self.state = OKXPublicWSState.SNAPSHOT_REQUIRED
        self.cancel_only = True

    def on_disconnect(self, *, reason: str, occurred_at_utc: datetime) -> None:
        self.reconnect_count += 1
        self.state = OKXPublicWSState.DEGRADED
        self.cancel_only = True
        self.gaps.append(
            {
                "reason": str(reason),
                "gap_start_time": ensure_utc(occurred_at_utc).isoformat(),
                "last_good_sequence": self.last_sequence,
                "recovery_method": "fresh_public_snapshot_then_contiguous_updates",
                "trading_blocked": True,
                "recovered": False,
            }
        )

    def ingest(
        self,
        raw_message: str | bytes | Mapping[str, Any],
        *,
        received_time_utc: datetime,
        recovery: bool = False,
    ) -> list[OKXNormalizedL2Event]:
        payload = _decode_payload(raw_message)
        arg = payload.get("arg")
        if not isinstance(arg, Mapping):
            return []
        if str(arg.get("channel") or "") != self.channel:
            return []
        if str(arg.get("instId") or "") != self.instrument_id:
            return []
        action = str(payload.get("action") or "")
        if action not in {"snapshot", "update"}:
            return []
        rows = payload.get("data")
        if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
            return self._fail("btc_okx_l2_data_rows_invalid")
        output: list[OKXNormalizedL2Event] = []
        for row in rows:
            if not isinstance(row, Mapping):
                return self._fail("btc_okx_l2_data_row_invalid")
            output.append(
                self._ingest_row(
                    payload=payload,
                    row=row,
                    action=action,
                    received_time_utc=received_time_utc,
                    recovery=recovery,
                )
            )
        return output

    def recovery_receipt(self) -> dict[str, Any]:
        return {
            "contract_version": OKX_PUBLIC_WS_CONTRACT_VERSION,
            "state": self.state.value,
            "instrument_id": self.instrument_id,
            "last_sequence": self.last_sequence,
            "last_event_time_ms": self.last_event_time_ms,
            "reconnect_count": self.reconnect_count,
            "gap_count": len(self.gaps),
            "gaps": [dict(row) for row in self.gaps],
            "sequence_contiguous": self.state == OKXPublicWSState.READY,
            "timestamp_contiguous": self.state == OKXPublicWSState.READY,
            "checksum_policy": (
                "required_and_validated" if self.checksum_required
                else "validate_when_present"
            ),
            "cancel_only": self.cancel_only,
            "new_risk_allowed": False,
            "market_event_only": True,
        }

    def _ingest_row(
        self,
        *,
        payload: Mapping[str, Any],
        row: Mapping[str, Any],
        action: str,
        received_time_utc: datetime,
        recovery: bool,
    ) -> OKXNormalizedL2Event:
        seq = _required_int(row.get("seqId"), "btc_okx_l2_sequence_missing")
        prev = _required_int(
            row.get("prevSeqId"), "btc_okx_l2_previous_sequence_missing"
        )
        event_ms = _required_int(
            row.get("ts"), "btc_okx_l2_event_timestamp_missing"
        )
        checksum = _optional_int(row.get("checksum"))
        if self.checksum_required and checksum is None:
            return self._fail("btc_okx_l2_checksum_missing")
        if action == "snapshot":
            if self.state not in {
                OKXPublicWSState.SNAPSHOT_REQUIRED,
                OKXPublicWSState.DEGRADED,
                OKXPublicWSState.CANCEL_ONLY,
            }:
                return self._fail("btc_okx_l2_unexpected_snapshot")
            self.bids.clear()
            self.asks.clear()
        else:
            if self.state != OKXPublicWSState.READY:
                return self._fail("btc_okx_l2_update_before_snapshot")
            if self.last_sequence is None or prev != self.last_sequence:
                return self._fail("btc_okx_l2_sequence_gap")
            if seq <= self.last_sequence:
                return self._fail("btc_okx_l2_sequence_not_monotonic")
        if self.last_event_time_ms is not None:
            if event_ms < self.last_event_time_ms:
                return self._fail("btc_okx_l2_timestamp_not_monotonic")
            if (
                action != "snapshot"
                and event_ms - self.last_event_time_ms > self.max_timestamp_gap_ms
            ):
                return self._fail("btc_okx_l2_timestamp_gap")
        bids = _normalize_levels(row.get("bids"), "btc_okx_l2_bids_invalid")
        asks = _normalize_levels(row.get("asks"), "btc_okx_l2_asks_invalid")
        _apply_levels(self.bids, bids)
        _apply_levels(self.asks, asks)
        if not self.bids or not self.asks:
            return self._fail("btc_okx_l2_two_sided_book_missing")
        if checksum is not None and checksum != 0:
            calculated = okx_l2_checksum(self.bids, self.asks)
            if calculated != checksum:
                return self._fail("btc_okx_l2_checksum_mismatch")
        self.last_sequence = seq
        self.last_event_time_ms = event_ms
        self.state = OKXPublicWSState.READY
        self.cancel_only = False
        if recovery and self.gaps:
            self.gaps[-1].update(
                {
                    "first_recovered_sequence": seq,
                    "gap_end_time": datetime.fromtimestamp(
                        event_ms / 1000.0, tz=timezone.utc
                    ).isoformat(),
                    "recovered": True,
                    "trading_blocked": False,
                }
            )
        source_hash = stable_payload_hash(payload)
        return OKXNormalizedL2Event(
            venue="OKX",
            instrument_id=self.instrument_id,
            channel=self.channel,
            action=action,
            event_time_utc=datetime.fromtimestamp(
                event_ms / 1000.0, tz=timezone.utc
            ),
            received_time_utc=ensure_utc(received_time_utc),
            sequence=seq,
            previous_sequence=prev,
            checksum=checksum,
            bids=tuple(bids),
            asks=tuple(asks),
            source_payload_hash=source_hash,
            recovery=recovery,
        )

    def _fail(self, blocker: str) -> Any:
        self.state = OKXPublicWSState.CANCEL_ONLY
        self.cancel_only = True
        raise OKXPublicWSContractError(blocker)


def okx_l2_checksum(
    bids: Mapping[str, str], asks: Mapping[str, str]
) -> int:
    """Return OKX signed CRC32 over the interleaved top-25 price/size levels."""

    bid_rows = sorted(
        bids.items(), key=lambda row: float(row[0]), reverse=True
    )[:25]
    ask_rows = sorted(asks.items(), key=lambda row: float(row[0]))[:25]
    parts: list[str] = []
    for index in range(max(len(bid_rows), len(ask_rows))):
        if index < len(bid_rows):
            parts.extend(bid_rows[index])
        if index < len(ask_rows):
            parts.extend(ask_rows[index])
    value = zlib.crc32(":".join(parts).encode("utf-8"))
    return value if value < 2**31 else value - 2**32


def _decode_payload(
    raw_message: str | bytes | Mapping[str, Any],
) -> dict[str, Any]:
    if isinstance(raw_message, Mapping):
        return dict(raw_message)
    try:
        payload = json.loads(
            raw_message.decode("utf-8")
            if isinstance(raw_message, bytes)
            else raw_message
        )
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError) as exc:
        raise OKXPublicWSContractError(
            "btc_okx_public_ws_payload_invalid"
        ) from exc
    if not isinstance(payload, dict):
        raise OKXPublicWSContractError(
            "btc_okx_public_ws_payload_not_object"
        )
    return payload


def _required_int(value: Any, blocker: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise OKXPublicWSContractError(blocker) from exc


def _optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    return _required_int(value, "btc_okx_l2_checksum_invalid")


def _normalize_levels(value: Any, blocker: str) -> list[tuple[str, str]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise OKXPublicWSContractError(blocker)
    rows: list[tuple[str, str]] = []
    for raw in value:
        if (
            not isinstance(raw, Sequence)
            or isinstance(raw, (str, bytes))
            or len(raw) < 2
        ):
            raise OKXPublicWSContractError(blocker)
        price = str(raw[0])
        size = str(raw[1])
        try:
            if float(price) <= 0 or float(size) < 0:
                raise ValueError
        except ValueError as exc:
            raise OKXPublicWSContractError(blocker) from exc
        rows.append((price, size))
    return rows


def _apply_levels(book: dict[str, str], levels: Sequence[tuple[str, str]]) -> None:
    for price, size in levels:
        if float(size) == 0:
            book.pop(price, None)
        else:
            book[price] = size


__all__ = [
    "OKXNormalizedL2Event",
    "OKXPublicWSContractError",
    "OKXPublicWSL2Adapter",
    "OKXPublicWSState",
    "OKX_PUBLIC_WS_CONTRACT_VERSION",
    "OKX_PUBLIC_DISPLAY_CHANNELS",
    "OKX_PUBLIC_DISPLAY_INSTRUMENT_ID",
    "OKX_PUBLIC_DISPLAY_URLS",
    "OKX_PUBLIC_WS_PACKAGE",
    "load_public_websocket_dependency",
    "build_public_display_subscription",
    "okx_l2_checksum",
    "public_websocket_dependency_receipt",
]
