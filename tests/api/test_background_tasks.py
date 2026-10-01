from __future__ import annotations

from time import sleep

from fastapi.testclient import TestClient
import pytest


def _wait_for_task(client: TestClient, task_id: str, timeout_s: float = 5.0) -> dict:
    deadline = timeout_s
    last: dict = {}
    while deadline > 0:
        response = client.get(f"/api/tasks/{task_id}")
        assert response.status_code == 200
        last = response.json()
        if last.get("status") not in {"queued", "running"}:
            return last
        sleep(0.05)
        deadline -= 0.05
    return last


def _crypto_closure_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "source": "sqlite",
        "symbol": "BTCUSDT",
        "interval": "1h",
        "start": "2024-01-01T00:00:00Z",
        "end": "2024-01-02T00:00:00Z",
        "capital": 100000,
        "commission_rate": 0.0004,
        "slippage": 4,
        "leverage": 1,
        "position_basis": "equity",
        "data_db_path": "data/market_data.sqlite",
        "target_intervals": ["5m", "15m", "1h"],
    }
    payload.update(overrides)
    return payload


def test_task_queue_service_tracks_status_and_blockers() -> None:
    from backend.app.services.task_queue import TaskQueueService

    queue = TaskQueueService(max_workers=1)

    task = queue.submit(
        kind="unit_test",
        label="unit test task",
        request={"foo": "bar"},
        job=lambda ctx: {"status": "completed", "blockers": ["missing manifest"], "value": 7},
    )

    assert task["task_id"]
    assert task["status"] in {"queued", "running", "completed"}

    finished = queue.get(task["task_id"])
    while finished["status"] in {"queued", "running"}:
        sleep(0.05)
        finished = queue.get(task["task_id"])

    assert finished["status"] == "completed"
    assert finished["result"]["value"] == 7
    assert finished["blockers"] == ["missing manifest"]
    assert queue.list(kind="unit_test", limit=5)[0]["task_id"] == task["task_id"]


def test_task_queue_service_exposes_nested_promotion_gate_blockers() -> None:
    from backend.app.services.task_queue import TaskQueueService

    queue = TaskQueueService(max_workers=1)

    task = queue.submit(
        kind="unit_test",
        label="nested gate blocker task",
        request={},
        job=lambda ctx: {
            "status": "completed",
            "promotion_gate": {
                "decision": "fail",
                "gates": [
                    {"name": "cpcv_dsr_pbo", "status": "fail", "message": "DSR below threshold"},
                    {"name": "data_quality", "status": "pass", "message": "ok"},
                ],
            },
        },
    )

    finished = queue.get(task["task_id"])
    while finished["status"] in {"queued", "running"}:
        sleep(0.05)
        finished = queue.get(task["task_id"])

    assert finished["status"] == "completed"
    assert finished["blockers"] == ["cpcv_dsr_pbo: DSR below threshold"]
    assert queue.list(kind="unit_test", limit=5)[0]["blockers"] == ["cpcv_dsr_pbo: DSR below threshold"]


def test_crypto_closure_task_endpoint_returns_task_and_result(monkeypatch) -> None:
    from backend.app.api import app_factory as app_module
    from backend.app.api.app_factory import create_app
    from backend.app.services.task_queue import TaskQueueService

    monkeypatch.setattr(app_module, "task_queue_service", TaskQueueService(max_workers=1))
    monkeypatch.setattr(
        app_module.crypto_closure_service,
        "run",
        lambda payload: {
            "status": "completed",
            "decision": "pass",
            "next_stage": "paper_review",
            "blockers": [],
            "recommendations": ["promote"],
            "symbol": payload["symbol"],
        },
    )

    client = TestClient(create_app())
    response = client.post(
        "/api/tasks/crypto/closure",
        json={
            "source": "sqlite",
            "symbol": "BTCUSDT",
            "interval": "1h",
            "start": "2024-01-01T00:00:00Z",
            "end": "2024-01-02T00:00:00Z",
            "capital": 100000,
            "commission_rate": 0.0004,
            "slippage": 4,
            "leverage": 1,
            "position_basis": "equity",
            "data_db_path": "data/market_data.sqlite",
            "target_intervals": ["5m", "15m", "1h"],
        },
    )
    assert response.status_code == 200
    submitted = response.json()
    assert submitted["task_id"]
    assert submitted["status"] in {"queued", "running", "completed"}

    finished = _wait_for_task(client, submitted["task_id"])
    assert finished["status"] == "completed"
    assert finished["result"]["decision"] == "pass"
    assert finished["result"]["symbol"] == "BTCUSDT"
    assert finished["blockers"] == []


def test_crypto_closure_task_endpoint_exposes_stage_and_progress(monkeypatch) -> None:
    from backend.app.api import app_factory as app_module
    from backend.app.api.app_factory import create_app
    from backend.app.services.task_queue import TaskQueueService

    monkeypatch.setattr(app_module, "task_queue_service", TaskQueueService(max_workers=1))

    def fake_run(payload):
        sleep(0.2)
        return {
            "status": "completed",
            "decision": "fail",
            "next_stage": "blocked",
            "blockers": ["coverage below threshold"],
            "recommendations": ["Keep paper/live closed."],
            "symbol": payload["symbol"],
        }

    monkeypatch.setattr(app_module.crypto_closure_service, "run", fake_run)

    client = TestClient(create_app())
    response = client.post(
        "/api/tasks/crypto/closure",
        json={
            "source": "sqlite",
            "symbol": "BTCUSDT",
            "interval": "1h",
            "start": "2024-01-01T00:00:00Z",
            "end": "2024-01-02T00:00:00Z",
            "capital": 100000,
            "commission_rate": 0.0004,
            "slippage": 4,
            "leverage": 1,
            "position_basis": "equity",
            "data_db_path": "data/market_data.sqlite",
            "target_intervals": ["5m", "15m", "1h"],
        },
    )
    assert response.status_code == 200
    submitted = response.json()
    assert submitted["task_id"]

    running = submitted
    deadline = 2.0
    while deadline > 0 and running["stage"] == "running":
        running = client.get(f"/api/tasks/{submitted['task_id']}").json()
        if running["stage"] == "data_integrity":
            break
        sleep(0.02)
        deadline -= 0.02

    assert running["stage"] == "data_integrity"
    assert running["progress"] == 12
    assert running["message"] == "BTC production closure: checking data integrity"

    finished = _wait_for_task(client, submitted["task_id"])
    assert finished["status"] == "completed"
    assert finished["result"]["decision"] == "fail"
    assert finished["blockers"] == ["coverage below threshold"]


def test_crypto_closure_task_endpoint_rejects_live_submit_flags(monkeypatch) -> None:
    from backend.app.api import app_factory as app_module
    from backend.app.api.app_factory import create_app
    from backend.app.services.task_queue import TaskQueueService

    monkeypatch.setattr(app_module, "task_queue_service", TaskQueueService(max_workers=1))
    monkeypatch.setattr(app_module.crypto_closure_service, "run", lambda payload: {"status": "completed", "blockers": []})

    client = TestClient(create_app())
    response = client.post(
        "/api/tasks/crypto/closure",
        json={
            "source": "sqlite",
            "symbol": "BTCUSDT",
            "interval": "1h",
            "start": "2024-01-01T00:00:00Z",
            "end": "2024-01-02T00:00:00Z",
            "capital": 100000,
            "commission_rate": 0.0004,
            "slippage": 4,
            "leverage": 1,
            "position_basis": "equity",
            "data_db_path": "data/market_data.sqlite",
            "target_intervals": ["5m", "15m", "1h"],
            "live_submit": True,
        },
    )
    assert response.status_code == 422
    assert "extra_forbidden" in response.text


@pytest.mark.parametrize(
    ("path", "extra_field", "extra_value"),
    [
        ("/api/crypto/research/closure", "live_submit", True),
        ("/api/crypto/research/closure", "submit_orders", True),
        ("/api/crypto/research/closure", "allow_live_orders", True),
        ("/api/crypto/research/closure", "runtime_mode", "live"),
        ("/api/crypto/research/closure", "broker", "alpaca"),
        ("/api/crypto/research/closure", "paper_ready", True),
        ("/api/crypto/research/closure", "live_ready", True),
        ("/api/tasks/crypto/closure", "live_submit", True),
        ("/api/tasks/crypto/closure", "submit_orders", True),
        ("/api/tasks/crypto/closure", "allow_live_orders", True),
        ("/api/tasks/crypto/closure", "runtime_mode", "live"),
        ("/api/tasks/crypto/closure", "broker", "alpaca"),
        ("/api/tasks/crypto/closure", "paper_ready", True),
        ("/api/tasks/crypto/closure", "live_ready", True),
    ],
)
def test_crypto_closure_api_and_task_reject_live_runtime_extra_fields(
    monkeypatch,
    path: str,
    extra_field: str,
    extra_value: object,
) -> None:
    from backend.app.api import app_factory as app_module
    from backend.app.api.app_factory import create_app
    from backend.app.services.task_queue import TaskQueueService

    monkeypatch.setattr(app_module, "task_queue_service", TaskQueueService(max_workers=1))

    def fail_if_called(payload):
        raise AssertionError(f"closure service should not receive forbidden field payload: {payload}")

    monkeypatch.setattr(app_module.crypto_closure_service, "run", fail_if_called)

    client = TestClient(create_app())
    response = client.post(path, json=_crypto_closure_payload(**{extra_field: extra_value}))

    assert response.status_code == 422
    assert "extra_forbidden" in response.text


def test_promotion_gate_task_endpoint_records_failures(monkeypatch) -> None:
    from backend.app.api import app_factory as app_module
    from backend.app.api.app_factory import create_app
    from backend.app.services.task_queue import TaskQueueService

    monkeypatch.setattr(app_module, "task_queue_service", TaskQueueService(max_workers=1))
    monkeypatch.setattr(
        app_module.promotion_gate_service,
        "evaluate",
        lambda payload: {"status": "completed", "decision": "fail", "next_stage": "blocked", "gates": [{"name": "data_quality", "status": "fail", "message": "coverage below threshold"}]},
    )

    client = TestClient(create_app())
    response = client.post(
        "/api/tasks/research/promotion-gate",
        json={
            "source": "sqlite",
            "symbol": "BTCUSDT",
            "interval": "1h",
            "start": "2024-01-01T00:00:00Z",
            "end": "2024-01-02T00:00:00Z",
            "capital": 100000,
            "commission_rate": 0.0004,
            "slippage": 4,
            "leverage": 1,
            "position_basis": "equity",
            "data_db_path": "data/market_data.sqlite",
            "mode": "single",
            "strategy_id": "trend_macd",
            "strategy_params": {},
            "weights": [],
            "symbols": ["BTCUSDT"],
        },
    )
    assert response.status_code == 200
    submitted = response.json()
    finished = _wait_for_task(client, submitted["task_id"])
    assert finished["status"] == "completed"
    assert finished["result"]["decision"] == "fail"
    assert "data_quality" in finished["blockers"][0]
