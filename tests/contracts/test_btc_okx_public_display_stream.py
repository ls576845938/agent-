from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from threading import Event
import time

import pytest
from types import SimpleNamespace
from urllib import request as proxy_request

import backend.app.services.btc_public_market_stream as stream_module

from backend.app.services.btc_public_market_stream import BtcPublicMarketStreamHub
from quant_crypto.adapters.okx_public_ws import OKXPublicWSContractError, build_public_display_subscription


def test_public_connection_uses_system_https_proxy(monkeypatch):
    calls = []
    monkeypatch.setattr(proxy_request, "getproxies", lambda: {"https": "http://127.0.0.1:12334"})
    monkeypatch.setattr(proxy_request, "proxy_bypass", lambda host: False)
    monkeypatch.setattr(stream_module, "load_public_websocket_dependency", lambda: SimpleNamespace(
        create_connection=lambda url, **kwargs: calls.append((url, kwargs))))
    BtcPublicMarketStreamHub()._new_connection()
    assert calls == [("wss://ws.okx.com:8443/ws/v5/public", {
        "timeout": 5, "http_proxy_host": "127.0.0.1", "http_proxy_port": 12334, "proxy_type": "http"})]


def test_public_connection_respects_proxy_bypass(monkeypatch):
    calls = []
    monkeypatch.setattr(proxy_request, "getproxies", lambda: {"https": "http://127.0.0.1:12334"})
    monkeypatch.setattr(proxy_request, "proxy_bypass", lambda host: True)
    monkeypatch.setattr(stream_module, "load_public_websocket_dependency", lambda: SimpleNamespace(
        create_connection=lambda url, **kwargs: calls.append(kwargs)))
    BtcPublicMarketStreamHub()._new_connection()
    assert calls == [{"timeout": 5}]


@pytest.mark.parametrize("proxy", ["socks5://127.0.0.1:12334", "http://user:password@localhost:12334", "http://"])
def test_public_proxy_rejects_unsupported_configuration_without_connecting(monkeypatch, proxy):
    monkeypatch.setattr(proxy_request, "getproxies", lambda: {"https": proxy})
    monkeypatch.setattr(proxy_request, "proxy_bypass", lambda host: False)
    monkeypatch.setattr(stream_module, "load_public_websocket_dependency", lambda: SimpleNamespace(
        create_connection=lambda *args, **kwargs: pytest.fail("must not connect")))
    with pytest.raises(ValueError, match="^public_display_proxy_unsupported$"):
        BtcPublicMarketStreamHub()._new_connection()


def test_public_connection_without_proxy_preserves_tls_defaults(monkeypatch):
    calls = []
    monkeypatch.setattr(proxy_request, "getproxies", lambda: {})
    monkeypatch.setattr(proxy_request, "proxy_bypass", lambda host: False)
    monkeypatch.setattr(stream_module, "load_public_websocket_dependency", lambda: SimpleNamespace(
        create_connection=lambda url, **kwargs: calls.append(kwargs)))
    BtcPublicMarketStreamHub()._new_connection()
    assert calls == [{"timeout": 5}]

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from backend.app.api.btc_demo_runtime import build_btc_demo_runtime_router
    _SSE_TEST_AVAILABLE = True
except (ImportError, RuntimeError):
    _SSE_TEST_AVAILABLE = False


def _trade(*, trade_id: str = "7", price: str = "65000", size: str = "0.01", ts: str = "1720000000000") -> dict:
    return {"arg": {"channel": "trades", "instId": "BTC-USDT-SWAP"}, "data": [{"tradeId": trade_id, "px": price, "sz": size, "side": "buy", "ts": ts}]}


def _books5(*, ts: str = "1720000000001", seq: str = "11") -> dict:
    return {"arg": {"channel": "books5", "instId": "BTC-USDT-SWAP"}, "data": [{"ts": ts, "seqId": seq, "bids": [[str(64999 - step), "1", "0", "3"] for step in range(5)], "asks": [[str(65001 + step), "2", "0", "4"] for step in range(5)]}]}


def test_failure_first_rejects_non_public_subscription_before_socket_construction() -> None:
    assert build_public_display_subscription() == {"op": "subscribe", "args": [{"channel": "trades", "instId": "BTC-USDT-SWAP"}, {"channel": "books5", "instId": "BTC-USDT-SWAP"}]}
    with pytest.raises(OKXPublicWSContractError, match="allowlisted"):
        build_public_display_subscription(channels=("account",))
    with pytest.raises(OKXPublicWSContractError, match="instrument"):
        build_public_display_subscription(instrument_id="ETH-USDT-SWAP")
    with pytest.raises(OKXPublicWSContractError, match="allowlisted"):
        build_public_display_subscription(channels=("orders",))


def test_trade_dedup_and_books5_snapshot_are_display_only_and_bounded() -> None:
    hub = BtcPublicMarketStreamHub(now=lambda: 100.0)
    first = hub.ingest(_trade(), received_at=datetime.now(timezone.utc))
    duplicate = hub.ingest(_trade(), received_at=datetime.now(timezone.utc))
    book = hub.ingest(_books5(), received_at=datetime.now(timezone.utc))
    assert first["trade"]["trade_id"] == "7"
    assert duplicate["duplicate"] is True
    assert book["depth"]["spread"] == "2"
    assert len(book["depth"]["bids"]) == 5
    assert hub.snapshot()["public_only"] is True
    assert hub.snapshot()["strategy_signal_compatible"] is False
    assert hub.snapshot()["persisted"] is False


def test_trade_batch_validates_each_row_and_exposes_only_the_latest_trade() -> None:
    hub = BtcPublicMarketStreamHub(now=lambda: 100.0)
    payload = _trade(trade_id="8")
    payload["data"].append({"tradeId": "9", "px": "65001", "sz": "0.02", "side": "sell", "ts": "1720000000001"})

    result = hub.ingest(payload, received_at=datetime.now(timezone.utc))

    assert result["trade"]["trade_id"] == "9"
    assert hub.snapshot()["trade"]["side"] == "sell"


def test_invalid_or_regressing_book_marks_stream_stale_without_execution_side_effect() -> None:
    hub = BtcPublicMarketStreamHub(now=lambda: 100.0)
    hub.ingest(_books5(seq="11"), received_at=datetime.now(timezone.utc))
    with pytest.raises(OKXPublicWSContractError):
        hub.ingest(_books5(seq="10"), received_at=datetime.now(timezone.utc))
    snapshot = hub.snapshot()
    assert snapshot["status"] == "stale"
    assert snapshot["private_endpoint_accessed"] is False
    assert snapshot["order_endpoint_accessed"] is False


def test_reconnect_requires_a_new_complete_books5_snapshot_before_live() -> None:
    hub = BtcPublicMarketStreamHub(now=lambda: 100.0)
    hub.ingest(_books5(), received_at=datetime.now(timezone.utc))
    assert hub.snapshot()["status"] == "live"
    hub.disconnected()
    assert hub.snapshot()["status"] == "stale"
    hub.ingest(_trade(trade_id="8"), received_at=datetime.now(timezone.utc))
    assert hub.snapshot()["status"] == "reconnecting"
    hub.ingest(_books5(seq="12"), received_at=datetime.now(timezone.utc))
    assert hub.snapshot()["status"] == "live"


def test_multiple_subscribers_share_one_lazy_worker_and_close_without_network_in_test() -> None:
    starts: list[int] = []
    hub = BtcPublicMarketStreamHub(worker_factory=lambda: starts.append(1), now=lambda: 100.0)
    one = hub.subscribe()
    two = hub.subscribe()
    assert starts == [1]
    hub.unsubscribe(one)
    hub.unsubscribe(two)
    assert hub.snapshot()["subscriber_count"] == 0


def test_failure_first_last_subscriber_resubscribe_reuses_or_restarts_worker_without_loss() -> None:
    """The last-subscriber stop cannot strand a fast new subscriber.

    The fake socket blocks in ``recv`` until hub shutdown closes it; no real
    public endpoint is contacted.  A second socket proves that the same
    upstream worker either continued or safely reconnected after the stop
    boundary instead of being lost in the alive-but-exiting race.
    """

    sockets: list[object] = []

    class FakeSocket:
        def __init__(self) -> None:
            self.started = Event()
            self.closed = Event()

        def send(self, value: str) -> None:
            assert '"trades"' in value

        def recv(self) -> str:
            self.started.set()
            self.closed.wait(timeout=1.0)
            raise RuntimeError("fake_socket_closed")

        def close(self) -> None:
            self.closed.set()

    def factory() -> FakeSocket:
        socket = FakeSocket()
        sockets.append(socket)
        return socket

    hub = BtcPublicMarketStreamHub(
        socket_factory=factory,
        reconnect_initial_seconds=0.005,
        reconnect_max_seconds=0.01,
    )
    first = hub.subscribe()
    assert _eventually(lambda: bool(sockets) and sockets[0].started.is_set())

    hub.unsubscribe(first)
    second = hub.subscribe()
    assert _eventually(lambda: len(sockets) >= 2)
    assert hub.snapshot()["subscriber_count"] == 1

    hub.unsubscribe(second)
    hub.close()
    assert _eventually(lambda: hub._worker is None or not hub._worker.is_alive())


def test_public_worker_accepts_okx_subscription_ack_before_trade_and_books5() -> None:
    """OKX control acknowledgements must not be parsed as market rows."""

    sockets: list[object] = []

    class FakeSocket:
        def __init__(self) -> None:
            self.closed = Event()
            self.messages = iter(
                (
                    json.dumps(
                        {
                            "event": "subscribe",
                            "arg": {
                                "channel": "trades",
                                "instId": "BTC-USDT-SWAP",
                            },
                            "connId": "public-test",
                        }
                    ),
                    json.dumps(
                        {
                            "event": "subscribe",
                            "arg": {
                                "channel": "books5",
                                "instId": "BTC-USDT-SWAP",
                            },
                            "connId": "public-test",
                        }
                    ),
                    json.dumps(_books5(seq="12")),
                    json.dumps(_trade(trade_id="ack-live")),
                )
            )

        def send(self, value: str) -> None:
            assert '"trades"' in value
            assert '"books5"' in value

        def recv(self) -> str:
            try:
                return next(self.messages)
            except StopIteration:
                self.closed.wait(timeout=1.0)
                raise RuntimeError("fake_socket_closed")

        def close(self) -> None:
            self.closed.set()

    def factory() -> FakeSocket:
        socket = FakeSocket()
        sockets.append(socket)
        return socket

    hub = BtcPublicMarketStreamHub(
        socket_factory=factory,
        reconnect_initial_seconds=0.005,
        reconnect_max_seconds=0.01,
    )
    token = hub.subscribe()

    assert _eventually(
        lambda: hub.snapshot()["status"] == "live"
        and (hub.snapshot()["trade"] or {}).get("trade_id") == "ack-live"
    )
    assert len(sockets) == 1
    assert hub.snapshot()["last_error_code"] == ""

    hub.unsubscribe(token)
    hub.close()


def test_last_update_ms_is_received_at_utc_epoch_not_monotonic_clock() -> None:
    hub = BtcPublicMarketStreamHub(now=lambda: 123.456)
    received_at = datetime(2026, 8, 17, 1, 2, 3, 456000, tzinfo=timezone.utc)

    hub.ingest(_trade(), received_at=received_at)

    assert hub.snapshot()["last_update_ms"] == 1_786_928_523_456


def _eventually(predicate, *, timeout_seconds: float = 1.0) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return bool(predicate())


@pytest.mark.skipif(not _SSE_TEST_AVAILABLE, reason="FastAPI SSE test dependencies unavailable")
def test_local_sse_uses_no_cache_and_public_only_event_schema() -> None:
    class StreamService:
        def public_market_stream(self):
            class OneEventHub:
                def subscribe(self) -> str:
                    return "one"

                def sse_events(self, token: str):
                    assert token == "one"
                    yield 'event: market\ndata: {"public_only":true,"display_only":true,"persisted":false,"strategy_signal_compatible":false,"private_endpoint_accessed":false,"order_endpoint_accessed":false}\n\n'

            return OneEventHub()

    app = FastAPI()
    app.include_router(
        build_btc_demo_runtime_router(
            service=StreamService(),
            verify_api_key=lambda: True,
            repo_root=Path.cwd(),
        ),
        prefix="/api",
    )
    response = TestClient(app).get("/api/research/btc/demo-paper/market-stream")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache, no-transform"
    assert '"public_only":true' in response.text
    assert '"private_endpoint_accessed":false' in response.text
    assert '"order_endpoint_accessed":false' in response.text
