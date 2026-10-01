from __future__ import annotations

from typing import Any

import pytest

from backend.app.api.us_ibkr_runtime import build_us_ibkr_runtime_router
from backend.app.services.us_ibkr_runtime import IBKRRuntimeStatusService


try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    TESTCLIENT_AVAILABLE = True
except (ImportError, RuntimeError):
    TESTCLIENT_AVAILABLE = False


class FixtureProvider:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def snapshot(self) -> dict[str, Any]:
        return self.payload


def _client(service: IBKRRuntimeStatusService):
    app = FastAPI()
    app.include_router(
        build_us_ibkr_runtime_router(
            service=service,
            verify_api_key=lambda: True,
        ),
        prefix="/api",
    )
    return TestClient(app)


@pytest.mark.skipif(not TESTCLIENT_AVAILABLE, reason="FastAPI TestClient dependencies are unavailable")
def test_runtime_without_provider_is_explicitly_unavailable_and_fail_closed() -> None:
    payload = _client(IBKRRuntimeStatusService()).get("/api/us/ibkr/runtime")

    assert payload.status_code == 200
    body = payload.json()
    assert body["status"] == "unavailable_fail_closed"
    assert body["data_available"] is False
    assert body["runtime_state"] == "offline"
    assert body["gateway"]["connected"] is False
    assert body["gateway"]["status"] == "unavailable"
    assert body["block_new_orders"] is True
    assert body["read_only"] is True
    assert body["safety"] == {
        "live_ready": False,
        "broker_access_allowed": False,
        "private_endpoint_allowed": False,
        "order_endpoint_allowed": False,
    }
    assert body["blockers"]
    assert "healthy" not in body["status"]


@pytest.mark.skipif(not TESTCLIENT_AVAILABLE, reason="FastAPI TestClient dependencies are unavailable")
def test_ready_fixture_exposes_ibkr_runtime_sections_without_wiring_real_gateway() -> None:
    provider = FixtureProvider(
        {
            "runtime_state": "ready",
            "trading_mode": "normal",
            "block_new_orders": False,
            "gateway": {
                "data_available": True,
                "connected": True,
                "client_id": 7,
                "paper_port": 4002,
                "connection_epoch": 14,
                "reconnect_attempts": 2,
            },
            "account": {"data_available": True, "verified": True, "account_hash": "sha256:abc"},
            "market_data": {
                "data_available": True,
                "healthy": True,
                "last_tick_age_seconds": 0.3,
                "subscription_epoch": 14,
                "sequence_gap": False,
            },
            "broker_truth": {
                "data_available": True,
                "fresh": True,
                "open_orders_count": 3,
                "executions_count": 1,
                "positions_count": 5,
            },
            "reconciliation": {
                "data_available": True,
                "status": "pass",
                "unknown_orders": 0,
                "unknown_executions": 0,
                "position_mismatches": 0,
                "cash_mismatch": False,
            },
            "kill_switch": {"data_available": True, "tripped": False},
            "recovery": {"data_available": True, "requires_operator_ack": False},
            "incidents": [],
        }
    )
    body = _client(IBKRRuntimeStatusService(provider)).get("/api/us/ibkr/runtime").json()

    assert body["status"] == "available"
    assert body["runtime_state"] == "ready"
    assert body["trading_mode"] == "normal"
    assert body["gateway"]["paper_port"] == 4002
    assert body["account"]["account_hash"] == "sha256:abc"
    assert body["market_data"]["healthy"] is True
    assert body["broker_truth"]["fresh"] is True
    assert body["reconciliation"]["status"] == "pass"
    assert body["oms"]["new_orders_allowed"] is True
    assert body["block_new_orders"] is False
    assert body["blockers"] == []
    assert body["safety"]["live_ready"] is False


@pytest.mark.skipif(not TESTCLIENT_AVAILABLE, reason="FastAPI TestClient dependencies are unavailable")
def test_stale_broker_truth_and_reconciliation_failure_remain_blocked() -> None:
    provider = FixtureProvider(
        {
            "runtime_state": "degraded",
            "trading_mode": "reduce_only",
            "gateway": {"data_available": True, "connected": True, "paper_port": 4002},
            "account": {"data_available": True, "verified": True, "account_hash": "hash"},
            "market_data": {"data_available": True, "healthy": True},
            "broker_truth": {"data_available": True, "fresh": False},
            "reconciliation": {"data_available": True, "status": "failed", "cash_mismatch": True},
            "kill_switch": {"data_available": True, "tripped": False},
        }
    )
    client = _client(IBKRRuntimeStatusService(provider))

    runtime = client.get("/api/us/ibkr/runtime").json()
    reconciliation = client.get("/api/us/ibkr/reconciliation").json()

    assert runtime["broker_truth"]["status"] == "stale"
    assert runtime["reconciliation"]["status"] == "fail"
    assert runtime["block_new_orders"] is True
    assert runtime["oms"]["new_orders_allowed"] is False
    blocker_codes = {item["code"] for item in runtime["blockers"]}
    assert "BROKER_TRUTH_STALE" in blocker_codes
    assert "RECONCILIATION_NOT_PASS" in blocker_codes
    assert reconciliation["status"] == "fail"
    assert reconciliation["cash_mismatch"] is True


@pytest.mark.skipif(not TESTCLIENT_AVAILABLE, reason="FastAPI TestClient dependencies are unavailable")
def test_account_number_and_live_port_are_not_exposed() -> None:
    provider = FixtureProvider(
        {
            "runtime_state": "ready",
            "gateway": {"data_available": True, "connected": True, "port": 7496},
            "account": {
                "data_available": True,
                "verified": True,
                "account_number": "DU1234567",
            },
            "market_data": {"data_available": True, "healthy": True},
            "broker_truth": {"data_available": True, "fresh": True},
            "reconciliation": {"data_available": True, "status": "pass"},
            "kill_switch": {"data_available": True, "tripped": False},
        }
    )
    body = _client(IBKRRuntimeStatusService(provider)).get("/api/us/ibkr/runtime").json()
    serialized = str(body)

    assert body["account"]["account_hash"] is None
    assert "account_number" not in serialized
    assert "DU1234567" not in serialized
    assert body["gateway"]["paper_port"] is None
    assert body["block_new_orders"] is True
    assert any(item["code"] == "LIVE_ENDPOINT_NOT_ALLOWED" for item in body["blockers"])


@pytest.mark.skipif(not TESTCLIENT_AVAILABLE, reason="FastAPI TestClient dependencies are unavailable")
def test_recovery_pending_requires_ack_and_incidents_are_read_only() -> None:
    provider = FixtureProvider(
        {
            "runtime_state": "recovery_pending",
            "trading_mode": "cancel_only",
            "gateway": {"data_available": True, "connected": True, "paper_port": 4002},
            "account": {"data_available": True, "verified": True, "account_hash": "hash"},
            "market_data": {"data_available": True, "healthy": True},
            "broker_truth": {"data_available": True, "fresh": True},
            "reconciliation": {"data_available": True, "status": "pass"},
            "recovery": {"data_available": True, "requires_operator_ack": True, "operator_acknowledged": False},
            "kill_switch": {"data_available": True, "tripped": False},
            "incidents": [
                {
                    "incident_id": "inc-1",
                    "type": "RECOVERY_PENDING",
                    "severity": "CRITICAL",
                    "message": "operator review required for DU1234567",
                    "context": {"account_number": "DU1234567", "connection_epoch": 14},
                }
            ],
        }
    )
    client = _client(IBKRRuntimeStatusService(provider))
    runtime = client.get("/api/us/ibkr/runtime").json()
    incidents = client.get("/api/us/ibkr/incidents").json()

    assert runtime["runtime_state"] == "recovery_pending"
    assert runtime["recovery"]["requires_operator_ack"] is True
    assert runtime["recovery"]["operator_acknowledged"] is False
    assert runtime["block_new_orders"] is True
    assert incidents["data_available"] is True
    assert incidents["incidents"][0]["type"] == "recovery_pending"
    assert "DU1234567" not in str(incidents)
    assert "account_number" not in str(incidents)

    assert client.post("/api/us/ibkr/runtime", json={}).status_code == 405
    assert client.post("/api/us/ibkr/reconciliation", json={}).status_code == 405
    assert client.post("/api/us/ibkr/incidents", json={}).status_code == 405


@pytest.mark.skipif(not TESTCLIENT_AVAILABLE, reason="FastAPI TestClient dependencies are unavailable")
def test_provider_error_is_unavailable_not_paper_loop_healthy() -> None:
    class BrokenProvider:
        def snapshot(self) -> dict[str, Any]:
            raise RuntimeError("transport failed")

    client = _client(IBKRRuntimeStatusService(BrokenProvider()))
    body = client.get("/api/us/ibkr/runtime").json()

    assert body["status"] == "unavailable_fail_closed"
    assert body["data_available"] is False
    assert body["gateway"]["connected"] is False
    assert body["block_new_orders"] is True
    assert body["live_ready"] is False
