from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping

import pytest

from backend.app.api import app_factory
from backend.app.api.btc_demo_runtime import build_btc_demo_runtime_router
from backend.app.core.config import load_settings


try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    TESTCLIENT_AVAILABLE = True
except (ImportError, RuntimeError):
    TESTCLIENT_AVAILABLE = False


class FakeDemoService:
    def __init__(self, *, kline_payload: dict[str, Any] | None = None) -> None:
        self.start_calls = 0
        self.emergency_calls: list[dict[str, Any]] = []
        self.stop_and_flatten_calls: list[dict[str, Any]] = []
        self.kline_payload = kline_payload

    def catalog(self) -> dict[str, Any]:
        return {"environment": "OKX Demo", "strategies": [], "safety": {"live_order_allowed": False}}

    def status(self) -> dict[str, Any]:
        return {
            "runtime": {"active": False, "opening_allowed": False},
            "safety": {"live_order_allowed": False, "auto_start_on_backend_launch": False},
        }

    def readonly_klines(self, *, limit: int) -> dict[str, Any]:
        if self.kline_payload is not None:
            return {**self.kline_payload, "limit": limit}
        return {"rows": [], "read_only": True, "schema_maintenance_performed": False, "limit": limit}

    def readonly_market_view(self, *, timeframe: str, limit: int) -> dict[str, Any]:
        return {
            "source_kind": "okx_public_market_view_v1",
            "timeframe": timeframe,
            "limit": limit,
            "public_only": True,
            "private_endpoint_used": False,
            "strategy_signal_compatible": False,
            "read_only": True,
            "candles": [],
        }

    def readonly_market_ticker(self) -> dict[str, Any]:
        return {
            "schema_version": "okx_public_market_ticker_v1",
            "source_kind": "okx_public_market_ticker_v1",
            "instrument_id": "BTC-USDT-SWAP",
            "read_only": True,
            "public_only": True,
            "private_endpoint_used": False,
            "order_endpoint_used": False,
            "strategy_signal_compatible": False,
            "captured_at_ms": 1783994400000,
            "cache_age_ms": 0,
            "stale": False,
            "last_error_code": "",
            "ticker": {
                "bid": "62043",
                "ask": "62045",
                "last": "62044",
                "timestamp_ms": 1783994400000,
            },
        }

    def public_market_stream(self) -> Any:
        class FakeStream:
            def subscribe(self) -> str:
                return "test-subscriber"

            def sse_events(self, token: str):
                assert token == "test-subscriber"
                yield 'event: market\ndata: {"public_only":true,"display_only":true,"persisted":false,"strategy_signal_compatible":false,"private_endpoint_accessed":false,"order_endpoint_accessed":false}\n\n'

        return FakeStream()

    def start(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        self.start_calls += 1
        return {"runtime": {"active": True}, "request": dict(payload)}

    def stop(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return {"runtime": {"active": False}, "request": dict(payload)}

    def stop_and_flatten(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        self.stop_and_flatten_calls.append(dict(payload))
        return {
            "decision": "stopped_and_flattened",
            "orders_posted": 0,
            "final_flat": True,
            "runtime": {"active": False, "cancel_only": True},
        }

    def reconcile(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return {"runtime": {"active": False}, "request": dict(payload)}

    def cancel_only(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return {"runtime": {"active": False, "cancel_only": True}, "request": dict(payload)}

    def emergency_reduce_only_exit(
        self,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        self.emergency_calls.append(dict(payload))
        return {
            "decision": "fresh_state_emergency_reduce_only_exit_completed",
            "orders_posted": 1,
            "runtime": {
                "active": False,
                "opening_allowed": False,
                "cancel_only": True,
            },
        }


class DurableFakeDemoService(FakeDemoService):
    def __init__(self) -> None:
        super().__init__()
        self.operation_calls: list[tuple[dict[str, Any], str | None]] = []

    def start_operation(
        self,
        payload: Mapping[str, Any],
        *,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        self.operation_calls.append((dict(payload), idempotency_key))
        return {
            "schema_version": "btc_demo_start_operation_v1",
            "accepted": True,
            "operation_id": "op-1",
            "attempt_id": "attempt-1",
            "state": "queued",
            "phase": "requested",
            "revision": 1,
            "start_operation": {
                "operation_id": "op-1",
                "attempt_id": "attempt-1",
                "idempotency_key": idempotency_key or "",
                "request_fingerprint": "f" * 64,
                "state": "queued",
                "phase": "requested",
                "revision": 1,
                "started_at_utc": "2026-08-22T00:00:00+00:00",
                "updated_at_utc": "2026-08-22T00:00:00+00:00",
                "deadline_utc": "2026-08-22T00:05:00+00:00",
                "source_head": "a" * 40,
                "blockers": [],
                "terminal_error": "",
            },
        }


class OperatorAcknowledgementFakeService(FakeDemoService):
    def __init__(self) -> None:
        super().__init__()
        self.acknowledgements: list[tuple[str, dict[str, Any]]] = []

    def acknowledge_operator_operation_v2(
        self,
        operation_id: str,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        self.acknowledgements.append((operation_id, dict(payload)))
        return {
            "schema_version": "btc_demo_operation_read_model_v2",
            "operation_id": operation_id,
            "action": "authoritative_preflight_start",
            "request_digest": "a" * 64,
            "state": "failed",
            "phase": "dispatch_failed",
            "blocker_codes": ["btc_demo_runtime_output_root_not_configured"],
            "created_at_utc": "2026-08-25T00:00:00Z",
            "updated_at_utc": "2026-08-25T00:01:00Z",
            "state_revision": 4,
            "result_present": False,
            "retryable": False,
            "replayed": False,
            "idempotent_replay": False,
            "acknowledged": True,
            "acknowledged_at_utc": "2026-08-25T00:01:00Z",
            "safety_flags": {
                "promotion_eligible": False,
                "paper": False,
                "live": False,
                "private": False,
                "order": False,
                "real_order": False,
                "transfer": False,
                "withdraw": False,
            },
        }


def _emergency_payload() -> dict[str, Any]:
    return {
        "operator_action": "fresh_state_emergency_reduce_only_exit",
        "confirmation_text": "BTC DEMO",
        "expected_environment": "OKX Demo",
        "expected_instrument_id": "BTC-USDT-SWAP",
        "expected_margin_mode": "isolated",
        "expected_position_side": "long",
        "expected_entry_cl_ord_id": "btcDP20a8d1650001",
        "expected_entry_ord_id": "3816659792351170560",
        "expected_oco_algo_cl_ord_id": "btcDP20a8d1650001A",
        "expected_oco_algo_id": "3816659794069377024",
        "expected_position_contracts": "0.01",
        "max_position_contracts": "0.01",
    }


def _client(
    service: FakeDemoService,
    *,
    repo_root: Path | None = None,
    control_enabled: bool = False,
):
    app = FastAPI()
    app.include_router(
        build_btc_demo_runtime_router(
            service=service,
            verify_api_key=lambda: True,
            repo_root=repo_root or Path.cwd(),
            control_enabled=control_enabled,
        ),
        prefix="/api",
    )
    return TestClient(app)


@pytest.mark.skipif(not TESTCLIENT_AVAILABLE, reason="FastAPI TestClient dependencies are unavailable")
def test_demo_status_is_read_only_and_control_is_fail_closed_by_default() -> None:
    service = FakeDemoService()
    client = _client(service)

    status = client.get("/api/research/btc/demo-paper/status")
    assert status.status_code == 200
    assert status.json()["runtime"]["active"] is False
    assert service.start_calls == 0

    blocked_origin = client.post(
        "/api/research/btc/demo-paper/start",
        headers={"Origin": "https://example.com"},
        json={"confirmation_text": "BTC DEMO"},
    )
    assert blocked_origin.status_code == 403
    assert service.start_calls == 0

    locked = client.post(
        "/api/research/btc/demo-paper/start",
        headers={"Origin": "http://127.0.0.1:3000"},
        json={"confirmation_text": "BTC DEMO"},
    )
    assert locked.status_code == 423
    assert locked.json()["detail"] == "btc_demo_control_not_enabled_by_integrator"
    assert service.start_calls == 0


@pytest.mark.skipif(not TESTCLIENT_AVAILABLE, reason="FastAPI TestClient dependencies are unavailable")
def test_start_operation_returns_202_and_forwards_idempotency_key() -> None:
    service = DurableFakeDemoService()
    client = _client(service, control_enabled=True)

    response = client.post(
        "/api/research/btc/demo-paper/start",
        headers={
            "Origin": "http://127.0.0.1:3000",
            "Idempotency-Key": "operator-attempt-1",
        },
        json={"confirmation_text": "BTC DEMO"},
    )

    assert response.status_code == 202
    assert response.json()["operation_id"] == "op-1"
    assert response.json()["start_operation"]["phase"] == "requested"
    assert service.operation_calls == [
        ({"confirmation_text": "BTC DEMO"}, "operator-attempt-1")
    ]


@pytest.mark.skipif(not TESTCLIENT_AVAILABLE, reason="FastAPI TestClient dependencies are unavailable")
def test_operator_terminal_acknowledgement_is_local_guarded_and_forwarded() -> None:
    service = OperatorAcknowledgementFakeService()
    locked = _client(service, control_enabled=False).post(
        "/api/research/btc/demo-paper/operator-v2/operations/op-terminal/acknowledge",
        headers={"Origin": "http://127.0.0.1:3000"},
        json={
            "action": "authoritative_preflight_start",
            "expected_state_revision": 3,
        },
    )
    assert locked.status_code == 423
    assert service.acknowledgements == []

    response = _client(service, control_enabled=True).post(
        "/api/research/btc/demo-paper/operator-v2/operations/op-terminal/acknowledge",
        headers={"Origin": "http://127.0.0.1:3000"},
        json={
            "action": "authoritative_preflight_start",
            "expected_state_revision": 3,
        },
    )
    assert response.status_code == 200
    assert response.json()["acknowledged"] is True
    assert service.acknowledgements == [
        (
            "op-terminal",
            {
                "action": "authoritative_preflight_start",
                "expected_state_revision": 3,
            },
        )
    ]


@pytest.mark.skipif(not TESTCLIENT_AVAILABLE, reason="FastAPI TestClient dependencies are unavailable")
def test_local_fixture_control_requires_explicit_integrator_enablement() -> None:
    service = FakeDemoService()
    client = _client(service, control_enabled=True)

    started = client.post(
        "/api/research/btc/demo-paper/start",
        headers={"Origin": "http://127.0.0.1:3000"},
        json={"confirmation_text": "BTC DEMO"},
    )

    assert started.status_code == 200
    assert started.json()["runtime"]["active"] is True
    assert service.start_calls == 1


@pytest.mark.skipif(not TESTCLIENT_AVAILABLE, reason="FastAPI TestClient dependencies are unavailable")
def test_demo_kline_endpoint_is_explicitly_read_only() -> None:
    service = FakeDemoService()
    client = _client(service)

    response = client.get("/api/research/btc/demo-paper/klines?limit=321")

    assert response.status_code == 200
    assert response.json()["read_only"] is True
    assert response.json()["schema_maintenance_performed"] is False
    assert response.json()["limit"] == 321


@pytest.mark.skipif(not TESTCLIENT_AVAILABLE, reason="FastAPI TestClient dependencies are unavailable")
def test_demo_market_view_is_read_only_public_only_and_bounded() -> None:
    client = _client(FakeDemoService())

    response = client.get("/api/research/btc/demo-paper/market-view?timeframe=1M&limit=120")
    rejected = client.get("/api/research/btc/demo-paper/market-view?timeframe=1Mutc&limit=999")

    assert response.status_code == 200
    assert response.json()["public_only"] is True
    assert response.json()["private_endpoint_used"] is False
    assert response.json()["strategy_signal_compatible"] is False
    assert response.json()["timeframe"] == "1M"
    assert rejected.status_code == 400


@pytest.mark.skipif(not TESTCLIENT_AVAILABLE, reason="FastAPI TestClient dependencies are unavailable")
def test_demo_market_ticker_is_read_only_public_only() -> None:
    client = _client(FakeDemoService())

    response = client.get("/api/research/btc/demo-paper/market-ticker")

    assert response.status_code == 200
    assert response.json()["schema_version"] == "okx_public_market_ticker_v1"
    assert response.json()["public_only"] is True
    assert response.json()["private_endpoint_used"] is False
    assert response.json()["order_endpoint_used"] is False
    assert response.json()["strategy_signal_compatible"] is False


@pytest.mark.skipif(not TESTCLIENT_AVAILABLE, reason="FastAPI TestClient dependencies are unavailable")
def test_demo_market_stream_is_local_sse_with_no_cache_and_public_only_schema() -> None:
    client = _client(FakeDemoService())

    response = client.get("/api/research/btc/demo-paper/market-stream")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache, no-transform"
    assert "event: market" in response.text
    assert '"public_only":true' in response.text
    assert '"private_endpoint_accessed":false' in response.text
    assert '"order_endpoint_accessed":false' in response.text


@pytest.mark.skipif(
    not TESTCLIENT_AVAILABLE,
    reason="FastAPI TestClient dependencies are unavailable",
)
def test_demo_kline_endpoint_redacts_physical_paths_without_changing_safety(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    service = FakeDemoService(
        kline_payload={
            "db_path": str(repo_root / "data" / "market_data.sqlite"),
            "rows": [],
            "read_only": True,
            "schema_maintenance_performed": False,
            "source_head": "b" * 40,
            "error_context": r"failed to read D:\private\market_data.sqlite",
            "reference_url": "https://example.com/public-market-data",
            "strategy_label": "donchian_long/short_v2",
            "provenance": [
                {"source_report_path": r"D:\quant\report.json"},
                {"selected_bundle_dir": "D:/quant/bundle"},
                {"source_report_path": r"\\server\share\report.json"},
                {"selected_bundle_dir": "/srv/quant/bundle"},
            ],
        },
    )
    client = _client(service, repo_root=repo_root)

    response = client.get("/api/research/btc/demo-paper/klines?limit=321")

    assert response.status_code == 200
    payload = response.json()
    assert payload["db_path"] == "data/market_data.sqlite"
    assert payload["read_only"] is True
    assert payload["schema_maintenance_performed"] is False
    assert payload["source_head"] == "b" * 40
    assert payload["limit"] == 321
    assert payload["error_context"] == "failed to read [redacted-physical-path]"
    assert payload["reference_url"] == "https://example.com/public-market-data"
    assert payload["strategy_label"] == "donchian_long/short_v2"
    assert {item[next(iter(item))] for item in payload["provenance"]} == {
        "[redacted-physical-path]"
    }


@pytest.mark.skipif(not TESTCLIENT_AVAILABLE, reason="FastAPI TestClient dependencies are unavailable")
def test_shared_app_factory_wires_btc_router_without_enabling_control(monkeypatch) -> None:
    service = FakeDemoService()
    monkeypatch.setattr(app_factory, "btc_demo_runtime_service", service)
    monkeypatch.setattr(
        app_factory,
        "settings",
        replace(
            app_factory.settings,
            web_api_key="",
            btc_demo_control_enabled=False,
        ),
    )

    client = TestClient(app_factory.create_app())

    status = client.get("/api/research/btc/demo-paper/status")
    assert status.status_code == 200
    assert status.json()["runtime"]["active"] is False
    assert service.start_calls == 0

    locked = client.post(
        "/api/research/btc/demo-paper/start",
        headers={"Origin": "http://127.0.0.1:3000"},
        json={"confirmation_text": "BTC DEMO"},
    )
    assert locked.status_code == 423
    assert locked.json()["detail"] == "btc_demo_control_not_enabled_by_integrator"
    assert service.start_calls == 0


@pytest.mark.skipif(not TESTCLIENT_AVAILABLE, reason="FastAPI TestClient dependencies are unavailable")
def test_shared_app_factory_enables_btc_control_only_for_local_opt_in(monkeypatch) -> None:
    service = FakeDemoService()
    monkeypatch.setattr(app_factory, "btc_demo_runtime_service", service)
    monkeypatch.setattr(
        app_factory,
        "settings",
        replace(
            app_factory.settings,
            web_api_key="",
            btc_demo_control_enabled=True,
        ),
    )

    client = TestClient(app_factory.create_app())

    rejected = client.post(
        "/api/research/btc/demo-paper/start",
        headers={"Origin": "https://example.com"},
        json={"confirmation_text": "BTC DEMO"},
    )
    assert rejected.status_code == 403
    assert service.start_calls == 0

    accepted = client.post(
        "/api/research/btc/demo-paper/start",
        headers={"Origin": "http://127.0.0.1:3000"},
        json={"confirmation_text": "BTC DEMO"},
    )
    assert accepted.status_code == 200
    assert service.start_calls == 1


def test_btc_demo_control_environment_setting_is_fail_closed(monkeypatch) -> None:
    monkeypatch.delenv("QS_BTC_DEMO_CONTROL_ENABLED", raising=False)
    assert load_settings().btc_demo_control_enabled is False

    monkeypatch.setenv("QS_BTC_DEMO_CONTROL_ENABLED", "true")
    assert load_settings().btc_demo_control_enabled is True


@pytest.mark.skipif(not TESTCLIENT_AVAILABLE, reason="FastAPI TestClient dependencies are unavailable")
def test_emergency_exit_route_requires_local_control_and_forwards_canonical_payload() -> None:
    service = FakeDemoService()
    client = _client(service, control_enabled=True)
    payload = _emergency_payload()

    rejected = client.post(
        "/api/research/btc/demo-paper/emergency-reduce-only-exit",
        headers={"Origin": "https://example.com"},
        json=payload,
    )
    assert rejected.status_code == 403
    assert service.emergency_calls == []

    accepted = client.post(
        "/api/research/btc/demo-paper/emergency-reduce-only-exit",
        headers={"Origin": "http://127.0.0.1:3000"},
        json=payload,
    )
    assert accepted.status_code == 200
    assert accepted.json()["orders_posted"] == 1
    assert service.emergency_calls == [payload]

    invalid = {**payload, "runtime_root": "forbidden"}
    rejected_extra = client.post(
        "/api/research/btc/demo-paper/emergency-reduce-only-exit",
        headers={"Origin": "http://127.0.0.1:3000"},
        json=invalid,
    )
    assert rejected_extra.status_code == 400
    assert service.emergency_calls == [payload]


@pytest.mark.skipif(not TESTCLIENT_AVAILABLE, reason="FastAPI TestClient dependencies are unavailable")
def test_emergency_exit_route_stays_locked_without_integrator_enablement() -> None:
    service = FakeDemoService()
    client = _client(service, control_enabled=False)

    response = client.post(
        "/api/research/btc/demo-paper/emergency-reduce-only-exit",
        headers={"Origin": "http://127.0.0.1:3000"},
        json={"operator_action": "fresh_state_emergency_reduce_only_exit"},
    )

    assert response.status_code == 423
    assert service.emergency_calls == []


@pytest.mark.skipif(not TESTCLIENT_AVAILABLE, reason="FastAPI TestClient dependencies are unavailable")
def test_stop_and_flatten_route_requires_exact_confirmation_and_forwards_once() -> None:
    service = FakeDemoService()
    client = _client(service, control_enabled=True)

    rejected = client.post(
        "/api/research/btc/demo-paper/stop-and-flatten",
        headers={"Origin": "http://127.0.0.1:3000"},
        json={"confirmation_text": "BTC DEMO", "contracts": 0.01},
    )
    assert rejected.status_code == 400
    assert service.stop_and_flatten_calls == []

    accepted = client.post(
        "/api/research/btc/demo-paper/stop-and-flatten",
        headers={"Origin": "http://127.0.0.1:3000"},
        json={"confirmation_text": "STOP AND FLATTEN"},
    )
    assert accepted.status_code == 200
    assert accepted.json()["final_flat"] is True
    assert service.stop_and_flatten_calls == [{"confirmation_text": "STOP AND FLATTEN"}]


def test_btc_demo_stress_profile_is_explicit_and_demo_scoped(
    monkeypatch,
) -> None:
    monkeypatch.delenv("QS_BTC_DEMO_RISK_PROFILE", raising=False)
    monkeypatch.delenv("QS_DEFAULT_LEVERAGE", raising=False)
    baseline = load_settings()
    assert baseline.btc_demo_risk_profile == "baseline_1x"
    assert baseline.default_leverage == 1.0

    monkeypatch.setenv("QS_BTC_DEMO_RISK_PROFILE", "stress_3x")
    stress = load_settings()
    assert stress.btc_demo_risk_profile == "stress_3x"
    assert stress.default_leverage == 1.0

    monkeypatch.setenv(
        "QS_BTC_DEMO_RISK_PROFILE",
        "unsafe_unknown_profile",
    )
    invalid = load_settings()
    assert invalid.btc_demo_risk_profile == "baseline_1x"
    assert invalid.default_leverage == 1.0
