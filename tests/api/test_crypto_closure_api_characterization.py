from __future__ import annotations

from fastapi.testclient import TestClient


def _request_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "source": "sqlite",
        "symbol": "BTCUSDT",
        "interval": "1h",
        "start": "2024-01-01T00:00:00Z",
        "end": "2024-01-02T00:00:00Z",
        "capital": 100_000,
        "commission_rate": 0.0004,
        "slippage": 4,
        "leverage": 1,
        "position_basis": "equity",
        "data_db_path": "data/market_data.sqlite",
        "target_intervals": ["5m", "1h"],
    }
    payload.update(overrides)
    return payload


def _service_response() -> dict[str, object]:
    return {
        "status": "blocked",
        "selected_priority": "P0",
        "symbol": "BTCUSDT",
        "source": "sqlite",
        "interval": "1h",
        "target_intervals": ["5m", "1h"],
        "data_integrity": {"status": "completed"},
        "candidate_screen": {"status": "completed"},
        "selected_candidate": None,
        "event_backtest": {},
        "cost_stress": {},
        "walk_forward": {},
        "promotion_gate": {"decision": "fail"},
        "closure_evidence_paths": [],
        "decision": "fail",
        "next_stage": "blocked",
        "blockers": ["promotion evidence incomplete"],
        "recommendations": ["Keep paper/live closed."],
    }


def test_sync_crypto_closure_preserves_request_mapping_and_response_schema(monkeypatch) -> None:
    from backend.app.api import app_factory as app_module
    from backend.app.api.app_factory import create_app

    observed: dict[str, object] = {}

    def fake_run(payload: dict[str, object]) -> dict[str, object]:
        observed.update(payload)
        return _service_response()

    monkeypatch.setattr(app_module.crypto_closure_service, "run", fake_run)

    response = TestClient(create_app()).post("/api/crypto/research/closure", json=_request_payload())

    assert response.status_code == 200
    assert response.json() == _service_response()
    assert observed["symbol"] == "BTCUSDT"
    assert observed["target_intervals"] == ["5m", "1h"]
    assert observed["start"].isoformat() == "2024-01-01T00:00:00+00:00"


def test_sync_crypto_closure_maps_value_error_to_http_400(monkeypatch) -> None:
    from backend.app.api import app_factory as app_module
    from backend.app.api.app_factory import create_app

    def fake_run(payload: dict[str, object]) -> dict[str, object]:
        raise ValueError(f"invalid closure request for {payload['symbol']}")

    monkeypatch.setattr(app_module.crypto_closure_service, "run", fake_run)

    response = TestClient(create_app()).post("/api/crypto/research/closure", json=_request_payload())

    assert response.status_code == 400
    assert response.json() == {"detail": "invalid closure request for BTCUSDT"}


def test_sync_crypto_closure_rejects_order_flags_before_service_call(monkeypatch) -> None:
    from backend.app.api import app_factory as app_module
    from backend.app.api.app_factory import create_app

    called = False

    def fake_run(payload: dict[str, object]) -> dict[str, object]:
        nonlocal called
        called = True
        return _service_response()

    monkeypatch.setattr(app_module.crypto_closure_service, "run", fake_run)

    response = TestClient(create_app()).post(
        "/api/crypto/research/closure",
        json=_request_payload(submit_orders=True),
    )

    assert response.status_code == 422
    assert "extra_forbidden" in response.text
    assert called is False
