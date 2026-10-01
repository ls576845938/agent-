from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from backend.app.api.btc_demo_runtime import build_btc_demo_runtime_router
from backend.app.services.btc_private_readonly_observation import (
    BTCPrivateReadonlyObservationProjection,
    BTCPrivateReadonlyObservationProjectionError,
)

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    TESTCLIENT_AVAILABLE = True
except (ImportError, RuntimeError):
    TESTCLIENT_AVAILABLE = False


HEAD = "1" * 40
RUN_ID = "btc-private-readonly-test-run"
RUNTIME_VERSION = "btc_demo_private_readonly_observation_runner_v1"
SAFE_RUNTIME_FLAGS = {
    "allow_demo_orders": False,
    "allow_demo_cancels": False,
    "allow_transfer": False,
    "allow_withdraw": False,
    "allow_live": False,
    "real_order_allowed": False,
    "promotion_allowed": False,
    "paper_allowed": False,
}


def _write_runtime(
    root: Path,
    *,
    last_observed: datetime,
    source_head: str = HEAD,
    eligible_since: str = "2026-09-02T00:00:00+00:00",
) -> None:
    root.mkdir(parents=True)
    owner = {
        "schema_version": "btc_demo_private_readonly_observation_owner_v1",
        "source_head": source_head,
        "run_id": RUN_ID,
        "runtime_version": RUNTIME_VERSION,
        "policy_digest": "a" * 64,
        "private_authorization_ticket_hash": "b" * 64,
        "safety": SAFE_RUNTIME_FLAGS,
    }
    state = {
        "schema_version": "btc_demo_private_readonly_observation_state_v1",
        "source_head": source_head,
        "run_id": RUN_ID,
        "runtime_version": RUNTIME_VERSION,
        "policy_digest": "a" * 64,
        "private_authorization_ticket_hash": "b" * 64,
        "account_identity_hash": "c" * 64,
        "phase": "observing",
        "started_at_utc": "2026-09-02T00:00:00+00:00",
        "eligible_since_utc": eligible_since,
        "last_observed_at_utc": last_observed.isoformat(),
        "last_receipt_hour_utc": "",
        "current_hour_gap_flags": [],
        "blockers": [],
        "restart_count": 0,
        "recovery_count": 1,
        "state_revision": 4,
        "private_ws": {
            "connected": True,
            "listener_alive": True,
            "reconciled": True,
            "reconnect_login_observed": True,
            "reconnect_resubscribed": True,
            "blockers": [],
        },
        "reconciliation": {
            "snapshot_reconciled": True,
            "rest_snapshot_observed": True,
            "private_ws_reconciled": True,
            "private_ws_connected": True,
            "snapshot_sha256": "d" * 64,
            "blockers": [],
        },
        "funding": {
            "observation_count": 0,
            "cashflow": 0.0,
            "funding_rate": "0.0001",
            "funding_bill_set_sha256": "e" * 64,
            "reconciled": True,
            "blockers": [],
        },
        "safety": SAFE_RUNTIME_FLAGS,
    }
    (root / "owner.json").write_text(json.dumps(owner), encoding="utf-8")
    (root / "state.json").write_text(json.dumps(state), encoding="utf-8")


def _projection(tmp_path: Path, *, now: datetime) -> BTCPrivateReadonlyObservationProjection:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    runtime_root = tmp_path / "runtime"
    return BTCPrivateReadonlyObservationProjection(
        runtime_root=runtime_root,
        repo_root=repo_root,
        head_resolver=lambda: HEAD,
        clock=lambda: now,
    )


def test_projection_is_read_only_sanitized_current_head_progress(tmp_path: Path) -> None:
    now = datetime(2026, 9, 2, 0, 30, tzinfo=timezone.utc)
    projection = _projection(tmp_path, now=now)
    _write_runtime(tmp_path / "runtime", last_observed=now - timedelta(seconds=30))

    payload = projection.read()

    assert payload["schema_version"] == "btc_private_readonly_observation_projection_v1"
    assert payload["status"] == "observing"
    assert payload["freshness"] == "current"
    assert payload["source_head"] == HEAD
    assert payload["current_head"] == HEAD
    assert payload["head_match"] is True
    assert payload["runner_active"] is True
    assert payload["gate_eligible"] is False
    assert payload["run_id"] == RUN_ID
    assert payload["progress"]["required_hours"] == 25
    assert payload["progress"]["completed_hours"] == 0
    assert payload["progress"]["current_hour_fraction"] == pytest.approx(0.5)
    assert payload["progress"]["progress_hours"] == pytest.approx(0.5)
    assert payload["private_ws"] == {
        "connected": True,
        "listener_alive": True,
        "reconciled": True,
    }
    assert payload["reconciliation"] == {
        "rest_snapshot_observed": True,
        "snapshot_reconciled": True,
        "funding_reconciled": True,
    }
    assert payload["safety_flags"] == {
        "promotion": False,
        "paper": False,
        "live": False,
        "private": False,
        "order": False,
        "real_order": False,
        "transfer": False,
        "withdraw": False,
    }
    serialized = json.dumps(payload, sort_keys=True)
    for forbidden in (
        "account_identity_hash",
        "policy_digest",
        "private_authorization_ticket_hash",
        "snapshot_sha256",
        str(tmp_path),
    ):
        assert forbidden not in serialized


def test_projection_marks_head_mismatch_historical_and_rejects_unsafe_runtime(tmp_path: Path) -> None:
    now = datetime(2026, 9, 2, 0, 30, tzinfo=timezone.utc)
    projection = _projection(tmp_path, now=now)
    _write_runtime(
        tmp_path / "runtime",
        last_observed=now - timedelta(seconds=30),
        source_head="2" * 40,
    )
    historical = projection.read()
    assert historical["status"] == "historical"
    assert historical["freshness"] == "current"
    assert historical["head_match"] is False
    assert historical["runner_active"] is True
    assert historical["gate_eligible"] is False
    assert historical["source_head"] == "2" * 40
    assert historical["current_head"] == HEAD
    assert "private_readonly_projection_current_head_mismatch" in historical["blockers"]

    _write_runtime(tmp_path / "unsafe-runtime", last_observed=now)
    state_path = tmp_path / "unsafe-runtime" / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["safety"]["allow_demo_orders"] = True
    state_path.write_text(json.dumps(state), encoding="utf-8")
    unsafe = BTCPrivateReadonlyObservationProjection(
        runtime_root=tmp_path / "unsafe-runtime",
        repo_root=tmp_path / "repo",
        head_resolver=lambda: HEAD,
        clock=lambda: now,
    )
    with pytest.raises(
        BTCPrivateReadonlyObservationProjectionError,
        match="private_readonly_projection_safety_mismatch",
    ):
        unsafe.read()


def test_stale_projection_preserves_receipt_progress_but_stops_partial_clock(tmp_path: Path) -> None:
    now = datetime(2026, 9, 2, 2, 0, tzinfo=timezone.utc)
    projection = _projection(tmp_path, now=now)
    _write_runtime(tmp_path / "runtime", last_observed=now - timedelta(minutes=10))

    payload = projection.read()

    assert payload["status"] == "blocked"
    assert payload["freshness"] == "stale"
    assert payload["runner_active"] is False
    assert payload["gate_eligible"] is False
    assert payload["progress"]["current_hour_fraction"] == 0
    assert "private_readonly_projection_state_stale" in payload["blockers"]


def test_partial_progress_starts_at_first_complete_utc_hour(tmp_path: Path) -> None:
    now = datetime(2026, 9, 2, 1, 30, tzinfo=timezone.utc)
    projection = _projection(tmp_path, now=now)
    _write_runtime(
        tmp_path / "runtime",
        last_observed=now - timedelta(seconds=30),
        eligible_since="2026-09-02T00:22:00+00:00",
    )

    payload = projection.read()

    assert payload["status"] == "observing"
    assert payload["progress"]["completed_hours"] == 0
    assert payload["progress"]["current_hour_fraction"] == pytest.approx(0.5)
    assert payload["progress"]["progress_hours"] == pytest.approx(0.5)


@pytest.mark.skipif(not TESTCLIENT_AVAILABLE, reason="FastAPI TestClient unavailable")
def test_get_route_exposes_only_projection_and_never_invokes_demo_runtime(tmp_path: Path) -> None:
    now = datetime(2026, 9, 2, 0, 30, tzinfo=timezone.utc)
    projection = _projection(tmp_path, now=now)
    _write_runtime(tmp_path / "runtime", last_observed=now - timedelta(seconds=30))

    class DemoServiceMustNotBeCalled:
        def __getattr__(self, name: str):
            raise AssertionError(f"demo runtime method must not be called: {name}")

    app = FastAPI()
    app.include_router(
        build_btc_demo_runtime_router(
            service=DemoServiceMustNotBeCalled(),
            verify_api_key=lambda: True,
            repo_root=tmp_path / "repo",
            private_readonly_observation=projection,
        ),
        prefix="/api",
    )
    response = TestClient(app).get(
        "/api/research/btc/demo-paper/private-readonly-observation"
    )
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["run_id"] == RUN_ID

    unavailable = FastAPI()
    unavailable.include_router(
        build_btc_demo_runtime_router(
            service=DemoServiceMustNotBeCalled(),
            verify_api_key=lambda: True,
            repo_root=tmp_path / "repo",
        ),
        prefix="/api",
    )
    blocked = TestClient(unavailable).get(
        "/api/research/btc/demo-paper/private-readonly-observation"
    )
    assert blocked.status_code == 503
    assert blocked.json()["detail"] == "private_readonly_projection_not_configured"
