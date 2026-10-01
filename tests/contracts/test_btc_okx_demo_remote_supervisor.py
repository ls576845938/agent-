from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import pytest

from quant_crypto.monitoring.okx_demo_remote_supervisor import (
    OkxDemoRemoteSupervisor,
    OkxDemoRemoteSupervisorConfig,
    OkxDemoRemoteSupervisorError,
)
from quant_crypto.oms.okx_demo import OkxDemoResponse


class ReadOnlyExchange:
    def __init__(self, rows: Mapping[str, list[dict[str, Any]]]) -> None:
        self.rows = dict(rows)
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def private_get(self, path: str, params: Mapping[str, Any] | None = None) -> OkxDemoResponse:
        self.calls.append(("GET", path, dict(params or {})))
        return OkxDemoResponse(
            method="GET", path=path, http_status=200, code="0", message="", data=tuple(self.rows.get(path, []))
        )


def _heartbeat(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "worker_id": "worker-a",
        "worker_host_id": "host-a",
        "runtime": {
            "run_id": "runtime-a",
            "active": True,
            "last_heartbeat_utc": "2026-08-05T00:00:00+00:00",
            "last_reconciled_at_utc": "2026-08-05T00:00:00+00:00",
        },
        "risk_control": {
            "mode": "RUNNING",
            "dead_man": {"armed": True, "last_ack_utc": "2026-08-05T00:00:00+00:00", "timeout_seconds": 30},
            "pending_order_intents": {},
            "active_protection": {},
            "owned_client_order_ids": ["known-order"],
        },
        "private_ws": {"connected": True, "listener_alive": True},
        "ledger_reconciliation": {"status": "reconciled", "current_state_exchange_snapshot_match": True},
        "safety": {"live_order_allowed": False, "transfer_allowed": False, "withdraw_allowed": False},
    }
    payload.update(overrides)
    return payload


def _config(tmp_path: Path, *, supervisor_host_id: str = "host-b") -> OkxDemoRemoteSupervisorConfig:
    return OkxDemoRemoteSupervisorConfig(
        deployment_id="supervisor-deployment-a",
        expected_worker_id="worker-a",
        heartbeat_url="https://worker.example.test/health/btc-demo",
        heartbeat_allowlist=("worker.example.test",),
        receipt_external_root=tmp_path,
        supervisor_host_id=supervisor_host_id,
        worker_heartbeat_stale_seconds=90,
        reconcile_stale_seconds=120,
    )


def test_supervisor_rejects_non_https_or_non_allowlisted_heartbeat(tmp_path: Path) -> None:
    with pytest.raises(OkxDemoRemoteSupervisorError, match="https_required"):
        OkxDemoRemoteSupervisorConfig(
            deployment_id="d", expected_worker_id="w", heartbeat_url="http://worker.example.test/x",
            heartbeat_allowlist=("worker.example.test",), receipt_external_root=tmp_path,
        )
    with pytest.raises(OkxDemoRemoteSupervisorError, match="host_not_allowlisted"):
        OkxDemoRemoteSupervisorConfig(
            deployment_id="d", expected_worker_id="w", heartbeat_url="https://evil.test/x",
            heartbeat_allowlist=("worker.example.test",), receipt_external_root=tmp_path,
        )


def test_remote_supervisor_detects_stale_worker_unknown_order_and_missing_protection(tmp_path: Path) -> None:
    exchange = ReadOnlyExchange({
        "/api/v5/account/config": [{"acctLv": "2"}],
        "/api/v5/account/balance": [{"totalEq": "100"}],
        "/api/v5/account/positions": [{"instId": "BTC-USDT-SWAP", "posSide": "long", "pos": "0.01"}],
        "/api/v5/trade/orders-pending": [{"instId": "BTC-USDT-SWAP", "clOrdId": "unknown-order", "state": "live"}],
        "/api/v5/trade/orders-algo-pending": [],
    })
    now = datetime(2026, 8, 5, 0, 5, tzinfo=timezone.utc)
    supervisor = OkxDemoRemoteSupervisor(
        _config(tmp_path),
        exchange_reader=exchange,
        heartbeat_fetcher=lambda _: _heartbeat(),
        clock=lambda: now,
    )

    receipt = supervisor.run_once()
    codes = {alert["code"] for alert in receipt["alerts"]}

    assert receipt["status"] == "critical"
    assert "okx_demo_watchdog_worker_heartbeat_stale" in codes
    assert "okx_demo_remote_supervisor_reconcile_stale" in codes
    assert "okx_demo_remote_supervisor_unknown_order" in codes
    assert "okx_demo_watchdog_nonflat_without_exchange_protection" in codes
    assert receipt["capabilities"]["independent_host_verified"] is True
    assert all(method == "GET" for method, _, _ in exchange.calls)
    assert Path(receipt["receipt_path"]).is_file()


def test_same_host_is_never_independent_host_verified(tmp_path: Path) -> None:
    exchange = ReadOnlyExchange({})
    receipt = OkxDemoRemoteSupervisor(
        _config(tmp_path, supervisor_host_id="host-a"),
        exchange_reader=exchange,
        heartbeat_fetcher=lambda _: _heartbeat(),
        clock=lambda: datetime(2026, 8, 5, 0, 0, 1, tzinfo=timezone.utc),
    ).run_once()

    assert receipt["capabilities"]["independent_host_verified"] is False
    assert "okx_demo_remote_supervisor_same_host_not_independent" in {
        alert["code"] for alert in receipt["alerts"]
    }


def test_supervisor_interface_never_requires_post_cancel_or_order_methods(tmp_path: Path) -> None:
    exchange = ReadOnlyExchange({})
    supervisor = OkxDemoRemoteSupervisor(
        _config(tmp_path),
        exchange_reader=exchange,
        heartbeat_fetcher=lambda _: _heartbeat(),
        clock=lambda: datetime(2026, 8, 5, 0, 0, 1, tzinfo=timezone.utc),
    )
    supervisor.run_once()
    assert not hasattr(exchange, "submit_order")
    assert not hasattr(exchange, "cancel_order")
    assert not hasattr(exchange, "cancel_all_after")
