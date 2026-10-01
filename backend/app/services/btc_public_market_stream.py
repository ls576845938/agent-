"""In-memory, public-only OKX trade and top-five depth display stream."""

from __future__ import annotations

import json
import threading
import time
import uuid
from collections import deque
from collections.abc import Callable, Generator, Mapping, Sequence
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib import request as proxy_request
from urllib.parse import urlsplit

from quant_crypto.adapters.okx_public_ws import (
    OKX_PUBLIC_DISPLAY_INSTRUMENT_ID,
    OKX_PUBLIC_DISPLAY_URLS,
    OKXPublicWSContractError,
    build_public_display_subscription,
    load_public_websocket_dependency,
)


class BtcPublicMarketStreamHub:
    """One lazy upstream public connection, shared by local SSE subscribers.

    All state is bounded memory.  It never imports a Demo client, controller,
    credential provider, ledger, OMS, risk, strategy, or private transport.
    """

    def __init__(
        self,
        *,
        worker_factory: Callable[[], Any] | None = None,
        socket_factory: Callable[[], Any] | None = None,
        now: Callable[[], float] = time.monotonic,
        stale_after_seconds: float = 30.0,
        reconnect_initial_seconds: float = 1.0,
        reconnect_max_seconds: float = 10.0,
    ) -> None:
        self._worker_factory = worker_factory
        self._socket_factory = socket_factory
        self._now = now
        self._stale_after_seconds = float(stale_after_seconds)
        self._reconnect_initial_seconds = float(reconnect_initial_seconds)
        self._reconnect_max_seconds = float(reconnect_max_seconds)
        self._lock = threading.Condition(threading.RLock())
        self._stop = threading.Event()
        self._worker: threading.Thread | None = None
        self._connection: Any | None = None
        self._worker_started_by_factory = False
        self._worker_generation = 0
        self._closed = False
        self._subscribers: set[str] = set()
        self._version = 0
        self._status = "reconnecting"
        self._last_update_monotonic = 0.0
        self._last_update_epoch_ms = 0
        self._last_error = ""
        self._last_sequence: int | None = None
        self._next_public_url_index = 0
        self._book_snapshot_current = False
        self._trade_ids: deque[str] = deque(maxlen=2_000)
        self._trade_seen: set[str] = set()
        self._trade: dict[str, Any] | None = None
        self._depth: dict[str, Any] | None = None

    def subscribe(self) -> str:
        token = f"subscriber-{uuid.uuid4().hex}"
        with self._lock:
            if self._closed:
                raise RuntimeError("btc_okx_public_display_stream_closed")
            self._subscribers.add(token)
            # A last-subscriber stop may already have been observed by the
            # worker.  Clearing it lets a still-running worker continue; its
            # generation-finalizer restarts exactly once if it has already
            # crossed the stop boundary.
            self._stop.clear()
            self._ensure_worker_locked()
            self._touch_locked()
        return token

    def unsubscribe(self, token: str) -> None:
        with self._lock:
            self._subscribers.discard(str(token))
            if not self._subscribers:
                self._stop.set()
                self._close_connection_locked()
                if self._worker is None:
                    self._worker_started_by_factory = False
            self._touch_locked()

    def sse_events(self, token: str) -> Generator[str, None, None]:
        version = -1
        try:
            while True:
                with self._lock:
                    if token not in self._subscribers:
                        return
                    self._mark_stale_locked()
                    if version == self._version:
                        self._lock.wait(timeout=15.0)
                        self._mark_stale_locked()
                    version = self._version
                    payload = self.snapshot()
                yield f"event: market\ndata: {json.dumps(payload, separators=(',', ':'))}\n\n"
        finally:
            self.unsubscribe(token)

    def ingest(self, raw: Mapping[str, Any] | str | bytes, *, received_at: datetime) -> dict[str, Any]:
        received_at_epoch_ms = _utc_epoch_ms(received_at)
        payload = _payload(raw)
        arg = _mapping(payload.get("arg"), "btc_okx_public_display_arg_invalid")
        channel = str(arg.get("channel") or "")
        instrument = str(arg.get("instId") or "")
        if instrument != OKX_PUBLIC_DISPLAY_INSTRUMENT_ID or channel not in {"trades", "books5"}:
            raise OKXPublicWSContractError("btc_okx_public_display_message_not_allowlisted")
        rows = payload.get("data")
        if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)) or not rows:
            self._degrade("btc_okx_public_display_data_shape_invalid")
            raise OKXPublicWSContractError("btc_okx_public_display_data_shape_invalid")
        with self._lock:
            try:
                if channel == "trades":
                    results = [
                        self._ingest_trade_locked(
                            _mapping(row, "btc_okx_public_display_row_invalid")
                        )
                        for row in rows
                    ]
                    result = results[-1]
                else:
                    if len(rows) != 1:
                        raise OKXPublicWSContractError("btc_okx_public_display_books5_snapshot_ambiguous")
                    result = self._ingest_books5_locked(
                        _mapping(rows[0], "btc_okx_public_display_row_invalid")
                    )
            except OKXPublicWSContractError as exc:
                self._degrade(str(exc))
                raise
            self._last_update_monotonic = self._now()
            self._last_update_epoch_ms = received_at_epoch_ms
            self._status = "live" if self._book_snapshot_current else "reconnecting"
            self._last_error = ""
            self._touch_locked()
            return result

    def disconnected(self, reason: str = "socket_disconnected") -> None:
        self._degrade(str(reason) or "socket_disconnected")

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            self._mark_stale_locked()
            return {
                "schema_version": "btc_okx_public_market_stream_v1",
                "instrument_id": OKX_PUBLIC_DISPLAY_INSTRUMENT_ID,
                "public_only": True,
                "display_only": True,
                "persisted": False,
                "strategy_signal_compatible": False,
                "private_endpoint_accessed": False,
                "order_endpoint_accessed": False,
                "status": self._status,
                "last_error_code": self._last_error,
                "last_update_ms": self._last_update_epoch_ms,
                "subscriber_count": len(self._subscribers),
                "trade": dict(self._trade) if self._trade else None,
                "depth": _copy_depth(self._depth),
            }

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._stop.set()
            self._subscribers.clear()
            self._close_connection_locked()
            self._touch_locked()
            worker = self._worker
        if worker is not None:
            worker.join(timeout=0.25)

    def _ensure_worker_locked(self) -> None:
        if self._worker_started_by_factory:
            return
        if self._worker is not None and self._worker.is_alive():
            return
        self._stop.clear()
        if self._worker_factory is not None:
            self._worker_factory()
            self._worker_started_by_factory = True
            return
        self._worker_generation += 1
        generation = self._worker_generation
        self._worker = threading.Thread(
            target=self._run,
            args=(generation,),
            name="btc-public-market-stream",
            daemon=True,
        )
        self._worker.start()

    def _run(self, generation: int) -> None:
        delay = self._reconnect_initial_seconds
        try:
            while not self._stop.is_set():
                connection = None
                try:
                    connection = self._new_connection()
                    connection.send(json.dumps(build_public_display_subscription(), separators=(",", ":")))
                    with self._lock:
                        self._connection = connection
                        self._status = "reconnecting"
                        self._touch_locked()
                    last_ping = self._now()
                    while not self._stop.is_set():
                        if self._now() - last_ping >= 20.0:
                            ping = getattr(connection, "ping", None)
                            if callable(ping):
                                ping()
                            last_ping = self._now()
                        raw = connection.recv()
                        if self._accept_control_frame(raw):
                            continue
                        self.ingest(raw, received_at=datetime.now(timezone.utc))
                    delay = self._reconnect_initial_seconds
                except Exception as exc:  # display failure is visible and never an execution signal.
                    self._degrade(f"btc_okx_public_display_{type(exc).__name__}")
                    self._stop.wait(delay)
                    delay = min(delay * 2.0, self._reconnect_max_seconds)
                finally:
                    with self._lock:
                        if self._connection is connection:
                            self._connection = None
                    close = getattr(connection, "close", None)
                    if callable(close):
                        try:
                            close()
                        except Exception:
                            pass
        finally:
            self._worker_finished(generation)

    def _worker_finished(self, generation: int) -> None:
        with self._lock:
            if generation != self._worker_generation:
                return
            self._worker = None
            self._worker_started_by_factory = False
            if self._subscribers and not self._closed:
                self._stop.clear()
                self._ensure_worker_locked()

    def _close_connection_locked(self) -> None:
        close = getattr(self._connection, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                pass

    def _new_connection(self) -> Any:
        if self._socket_factory is not None:
            return self._socket_factory()
        module = load_public_websocket_dependency()
        public_url = OKX_PUBLIC_DISPLAY_URLS[
            self._next_public_url_index % len(OKX_PUBLIC_DISPLAY_URLS)
        ]
        self._next_public_url_index += 1
        # websocket-client reads environment proxies, but not Windows Internet
        # Settings. Resolve the existing OS proxy for this public socket only.
        # Do not change process environment, private transports or TLS settings.
        options: dict[str, Any] = {}
        host = urlsplit(public_url).hostname
        if host and not proxy_request.proxy_bypass(host):
            proxies = proxy_request.getproxies()
            proxy_url = proxies.get("https") or proxies.get("http")
            if proxy_url:
                proxy = urlsplit(proxy_url)
                if proxy.scheme != "http" or not proxy.hostname or proxy.username or proxy.password:
                    raise ValueError("public_display_proxy_unsupported")
                options = {"http_proxy_host": proxy.hostname,
                           "http_proxy_port": proxy.port or 80, "proxy_type": "http"}
        return module.create_connection(public_url, timeout=5, **options)

    def _accept_control_frame(self, raw: Mapping[str, Any] | str | bytes) -> bool:
        """Accept only the public subscription acknowledgement and pong.

        OKX sends one ``event=subscribe`` control message per requested
        channel before the first market row.  It is transport metadata, not a
        trade/depth payload, so it must never enter ``ingest``.  Rejected or
        unexpected control events remain fail-closed and trigger reconnect.
        """

        if isinstance(raw, bytes):
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise OKXPublicWSContractError(
                    "btc_okx_public_display_payload_invalid"
                ) from exc
        elif isinstance(raw, str):
            text = raw
        else:
            text = ""
        if text.strip() == "pong":
            return True

        payload = _payload(raw)
        event = str(payload.get("event") or "")
        if not event:
            return False
        if event == "error":
            raise OKXPublicWSContractError(
                "btc_okx_public_display_subscription_rejected"
            )
        if event != "subscribe":
            raise OKXPublicWSContractError(
                "btc_okx_public_display_control_event_not_allowlisted"
            )
        arg = _mapping(
            payload.get("arg"),
            "btc_okx_public_display_control_arg_invalid",
        )
        channel = str(arg.get("channel") or "")
        instrument = str(arg.get("instId") or "")
        if (
            channel not in {"trades", "books5"}
            or instrument != OKX_PUBLIC_DISPLAY_INSTRUMENT_ID
        ):
            raise OKXPublicWSContractError(
                "btc_okx_public_display_control_arg_not_allowlisted"
            )
        return True

    def _ingest_trade_locked(self, row: Mapping[str, Any]) -> dict[str, Any]:
        trade_id = _text(row.get("tradeId"), "btc_okx_public_display_trade_id_invalid")
        price = _positive_text(row.get("px"), "btc_okx_public_display_trade_price_invalid")
        size = _positive_text(row.get("sz"), "btc_okx_public_display_trade_size_invalid")
        side = str(row.get("side") or "")
        if side not in {"buy", "sell"}:
            raise OKXPublicWSContractError("btc_okx_public_display_trade_side_invalid")
        timestamp_ms = _int(row.get("ts"), "btc_okx_public_display_trade_timestamp_invalid")
        if trade_id in self._trade_seen:
            return {"duplicate": True, "trade": dict(self._trade or {})}
        evicted = self._trade_ids[0] if len(self._trade_ids) == self._trade_ids.maxlen else None
        self._trade_seen.add(trade_id)
        self._trade_ids.append(trade_id)
        if evicted is not None:
            self._trade_seen.discard(evicted)
        self._trade = {"trade_id": trade_id, "price": price, "size": size, "side": side, "timestamp_ms": timestamp_ms}
        return {"duplicate": False, "trade": dict(self._trade)}

    def _ingest_books5_locked(self, row: Mapping[str, Any]) -> dict[str, Any]:
        timestamp_ms = _int(row.get("ts"), "btc_okx_public_display_book_timestamp_invalid")
        sequence = _int(row.get("seqId"), "btc_okx_public_display_book_sequence_invalid")
        if self._last_sequence is not None and sequence < self._last_sequence:
            self._degrade("btc_okx_public_display_book_sequence_regressed")
            raise OKXPublicWSContractError("btc_okx_public_display_book_sequence_regressed")
        bids = _levels(row.get("bids"), reverse=True)
        asks = _levels(row.get("asks"), reverse=False)
        if len(bids) != 5 or len(asks) != 5 or Decimal(bids[0]["price"]) >= Decimal(asks[0]["price"]):
            self._degrade("btc_okx_public_display_book_invalid")
            raise OKXPublicWSContractError("btc_okx_public_display_book_invalid")
        self._last_sequence = sequence
        self._book_snapshot_current = True
        bid_total = sum(Decimal(item["size"]) for item in bids)
        ask_total = sum(Decimal(item["size"]) for item in asks)
        self._depth = {
            "bids": bids, "asks": asks, "spread": _decimal_text(Decimal(asks[0]["price"]) - Decimal(bids[0]["price"])),
            "top5_imbalance": float(bid_total / (bid_total + ask_total)) if bid_total + ask_total else 0.0,
            "timestamp_ms": timestamp_ms, "sequence": sequence,
        }
        return {"duplicate": False, "depth": _copy_depth(self._depth)}

    def _degrade(self, reason: str) -> None:
        with self._lock:
            self._book_snapshot_current = False
            self._status = "stale"
            self._last_error = reason
            self._touch_locked()

    def _mark_stale_locked(self) -> None:
        if self._last_update_monotonic and self._now() - self._last_update_monotonic > self._stale_after_seconds:
            self._status = "stale"
            self._last_error = self._last_error or "btc_okx_public_display_stream_stale"

    def _touch_locked(self) -> None:
        self._version += 1
        self._lock.notify_all()


def _payload(value: Mapping[str, Any] | str | bytes) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    try:
        decoded = json.loads(value.decode("utf-8") if isinstance(value, bytes) else value)
    except Exception as exc:
        raise OKXPublicWSContractError("btc_okx_public_display_payload_invalid") from exc
    return _mapping(decoded, "btc_okx_public_display_payload_invalid")


def _utc_epoch_ms(value: datetime) -> int:
    if value.tzinfo is None or value.utcoffset() is None:
        raise OKXPublicWSContractError("btc_okx_public_display_received_at_invalid")
    return int(value.astimezone(timezone.utc).timestamp() * 1_000)


def _mapping(value: Any, blocker: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise OKXPublicWSContractError(blocker)
    return value


def _text(value: Any, blocker: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise OKXPublicWSContractError(blocker)
    return text


def _int(value: Any, blocker: str) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise OKXPublicWSContractError(blocker) from exc
    if result < 0:
        raise OKXPublicWSContractError(blocker)
    return result


def _positive_text(value: Any, blocker: str) -> str:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise OKXPublicWSContractError(blocker) from exc
    if not number.is_finite() or number <= 0:
        raise OKXPublicWSContractError(blocker)
    return _decimal_text(number)


def _levels(value: Any, *, reverse: bool) -> list[dict[str, str]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or len(value) < 5:
        raise OKXPublicWSContractError("btc_okx_public_display_book_levels_invalid")
    rows: list[dict[str, str]] = []
    for raw in value[:5]:
        if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)) or len(raw) < 2:
            raise OKXPublicWSContractError("btc_okx_public_display_book_levels_invalid")
        rows.append({"price": _positive_text(raw[0], "btc_okx_public_display_book_levels_invalid"), "size": _positive_text(raw[1], "btc_okx_public_display_book_levels_invalid"), "count": str(raw[3]) if len(raw) > 3 else "0"})
    if rows != sorted(rows, key=lambda item: Decimal(item["price"]), reverse=reverse):
        raise OKXPublicWSContractError("btc_okx_public_display_book_not_sorted")
    return rows


def _decimal_text(value: Decimal) -> str:
    return format(value.normalize(), "f")


def _copy_depth(value: dict[str, Any] | None) -> dict[str, Any] | None:
    if value is None:
        return None
    return {**value, "bids": [dict(row) for row in value["bids"]], "asks": [dict(row) for row in value["asks"]]}
