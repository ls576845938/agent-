from dataclasses import replace
from urllib.parse import parse_qs, urlsplit

import pytest

from backend.app.core.backend_access_policy import evaluate_backend_access


BASE = "/api/research/btc/public-market"
NOW_MS = 1_790_000_000_000


@pytest.mark.parametrize("path", [f"{BASE}/view", f"{BASE}/ticker", f"{BASE}/stream"])
def test_reviewed_public_gets_are_admitted(path):
    assert evaluate_backend_access(profile="research_readonly", method="GET", path=path).allowed
    assert not evaluate_backend_access(profile="research_readonly", method="POST", path=path).allowed
    assert not evaluate_backend_access(profile="research_readonly", method="GET", path=f"{path}/extra").allowed


class PublicTransport:
    def __init__(self):
        self.calls = []
        self.fail = False
        self.depth_fail = False
        self.timestamp_ms = NOW_MS

    def send(self, **request):
        from quant_crypto.oms.okx_demo import OkxDemoResponse

        self.calls.append(request)
        route = urlsplit(request["url"])
        assert route.hostname == "www.okx.com"
        assert request["method"] == "GET"
        assert request["body"] is None
        assert not any("access" in key.lower() or "authorization" in key.lower() for key in request["headers"])
        assert parse_qs(route.query)["instId"] == ["BTC-USDT-SWAP"]
        if self.fail or (self.depth_fail and route.path.endswith("/books")):
            raise RuntimeError("transport_fixture_failure_do_not_expose")
        if route.path == "/api/v5/market/ticker":
            data = [{"ts": str(self.timestamp_ms), "last": "65000", "bidPx": "64999", "askPx": "65001"}]
        elif route.path == "/api/v5/market/candles":
            data = [[str(NOW_MS - step * 60000), "65000", "65002", "64990", "65001", "12", "0", "0", str(int(step > 0))] for step in range(2)]
        elif route.path == "/api/v5/market/books":
            assert parse_qs(route.query)["sz"] == ["5"]
            data = [{"ts": str(self.timestamp_ms), "bids": [[str(64999-step), "1", "0", "2"] for step in range(5)], "asks": [[str(65001+step), "1", "0", "2"] for step in range(5)]}]
        else:
            pytest.fail(f"nonpublic path: {route.path}")
        return OkxDemoResponse("GET", route.path, 200, "0", "", tuple(data))


def service_fixture():
    from backend.app.services.btc_public_market_view import BTCPublicMarketViewService
    from quant_crypto.oms.okx_demo import OkxDemoPublicMarketClient

    transport = PublicTransport()
    clock = [0.0]
    service = BTCPublicMarketViewService(
        client=OkxDemoPublicMarketClient(transport=transport),
        monotonic=lambda: clock[0],
        now_ms=lambda: NOW_MS,
    )
    return service, transport, clock


class ReadonlyStreamFixture:
    def subscribe(self):
        return "readonly-stream"

    def sse_events(self, token):
        assert token == "readonly-stream"
        yield (
            "event: market\n"
            'data: {"schema_version":"btc_okx_public_market_stream_v1",'
            '"public_only":true,"display_only":true,"persisted":false,'
            '"strategy_signal_compatible":false,"private_endpoint_accessed":false,'
            '"order_endpoint_accessed":false,"status":"live"}\n\n'
        )


def test_existing_public_client_is_reused_without_credentials_state_or_orders():
    service, transport, _ = service_fixture()
    assert transport.calls == []  # No HTTP work on construction/startup.
    view = service.view(timeframe="1m", limit=300)
    assert len(view["candles"]) == 2
    assert len(view["depth"]["bids"]) == len(view["depth"]["asks"]) == 5
    assert view["public_only"] is view["read_only"] is True
    for flag in ("private_endpoint_used", "order_endpoint_used", "persisted_market_rows", "strategy_signal_compatible"):
        assert view[flag] is False
    assert view["stale"] is False
    assert {urlsplit(row["url"]).path for row in transport.calls} == {
        "/api/v5/market/ticker", "/api/v5/market/candles", "/api/v5/market/books",
    }
    assert not any(hasattr(service, name) for name in ("start", "status", "submit_order", "private_get", "controller", "ledger"))


def test_cache_is_bounded_detached_and_failure_is_explicitly_stale():
    service, transport, clock = service_fixture()
    original = service.view(timeframe="1m", limit=300)
    original["candles"].clear()
    assert len(service.view(timeframe="1m", limit=300)["candles"]) == 2
    assert len(transport.calls) == 3
    clock[0] = 20
    transport.fail = True
    stale = service.view(timeframe="1m", limit=300)
    assert stale["stale"] is True
    assert stale["cache_age_ms"] == 20000
    assert stale["last_error_code"] == "okx_public_market_unavailable"
    assert "transport_fixture" not in str(stale)
    with pytest.raises(RuntimeError, match="^okx_public_market_unavailable$"):
        service.view(timeframe="1h", limit=300)
    transport.fail = False
    for limit in range(2, 40):
        service.view(timeframe="1h", limit=limit)
    assert len(service._cache) <= 32


def test_missing_depth_and_old_timestamps_are_not_reported_as_live():
    service, transport, clock = service_fixture()
    transport.depth_fail = True
    view = service.view(timeframe="1m", limit=300)
    assert view["depth"] is None
    assert view["depth_error_code"] == "okx_public_depth_unavailable"
    assert len(view["candles"]) == 2
    clock[0] = 20
    transport.timestamp_ms = NOW_MS - 120000
    assert service.view(timeframe="1m", limit=300)["stale"] is True
    assert service.ticker()["stale"] is True


@pytest.mark.parametrize("timeframe,limit", [("1s", 300), ("1m", 0), ("1m", 301), ("1m", True)])
def test_invalid_input_never_reaches_transport(timeframe, limit):
    service, transport, _ = service_fixture()
    with pytest.raises(ValueError):
        service.view(timeframe=timeframe, limit=limit)
    assert transport.calls == []


def test_full_app_readonly_public_routes_do_not_mount_demo_or_grant_controls(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    from backend.app.api import app_factory
    import quant_crypto.oms.okx_demo as okx

    service, transport, _ = service_fixture()
    monkeypatch.setattr(app_factory, "settings", replace(
        app_factory.settings, backend_evidence_profile="research_readonly",
        btc_demo_control_enabled=False, allow_fixture_fallback=False, web_api_key="",
    ))
    monkeypatch.setattr(app_factory, "BTCPublicMarketViewService", lambda: service)
    monkeypatch.setattr(app_factory, "BtcPublicMarketStreamHub", lambda: ReadonlyStreamFixture())
    monkeypatch.setattr(okx, "load_windows_keyring_credentials", lambda *_: pytest.fail("must not read credentials"))
    monkeypatch.setattr(okx, "OkxDemoClient", lambda **_: pytest.fail("must not construct private/order client"))
    monkeypatch.setattr(app_factory, "build_btc_demo_runtime_router", lambda **_: pytest.fail("Demo router must stay unmounted"))
    client = TestClient(app_factory.create_app())
    assert client.get(f"{BASE}/view?timeframe=1m&limit=300").status_code == 200
    assert client.get(f"{BASE}/ticker").json()["public_only"] is True
    stream = client.get(f"{BASE}/stream")
    assert stream.status_code == 200
    assert stream.headers["content-type"].startswith("text/event-stream")
    assert stream.headers["cache-control"] == "no-cache, no-transform"
    assert '"public_only":true' in stream.text
    assert '"private_endpoint_accessed":false' in stream.text
    assert '"order_endpoint_accessed":false' in stream.text
    before = len(transport.calls)
    for suffix in ("catalog", "status", "operator-v2/contract", "klines", "private-readonly-observation", "market-stream", "market-view"):
        response = client.get(f"/api/research/btc/demo-paper/{suffix}")
        assert response.status_code == 423
    for method in ("post", "put", "delete"):
        assert getattr(client, method)(f"{BASE}/view").status_code == 423
    assert client.get(f"{BASE}/view?timeframe=1s").status_code == 422
    assert client.get(f"{BASE}/view?limit=999").status_code == 422
    assert client.get(f"{BASE}/view?url=https://invalid").status_code == 422
    assert client.get(f"{BASE}/ticker?instrument=ETH-USDT-SWAP").status_code == 422
    assert len(transport.calls) == before
    health = client.get("/api/health").json()
    assert health["read_only"] is health["controls_disabled"] is True
    assert health["paper_allowed"] is health["live_allowed"] is health["broker_or_order_allowed"] is False
    transport.fail = True
    failure = client.get(f"{BASE}/view?timeframe=1h")
    assert failure.status_code == 503
    assert failure.json()["detail"] == "okx_public_market_unavailable"
    assert "transport_fixture" not in failure.text
