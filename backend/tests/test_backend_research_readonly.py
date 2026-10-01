from __future__ import annotations

from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from backend.app.api import app_factory


READONLY_ENVIRONMENT = {
    "QS_ALLOW_FIXTURE_FALLBACK": "false",
    "QS_BACKEND_EVIDENCE_PROFILE": "research_readonly",
    "QS_BTC_DEMO_CONTROL_ENABLED": "false",
}


def _readonly_client(
    monkeypatch: pytest.MonkeyPatch,
    *,
    repo_root: Path | None = None,
) -> TestClient:
    monkeypatch.setattr(
        app_factory,
        "settings",
        replace(
            app_factory.settings,
            repo_root=repo_root or app_factory.settings.repo_root,
            backend_evidence_profile="research_readonly",
            btc_demo_control_enabled=False,
            btc_runtime_artifact_root="",
            btc_private_readonly_observation_root="",
        ),
    )
    return TestClient(app_factory.create_app())


def test_readonly_profile_does_not_import_or_construct_demo_runtime() -> None:
    script = """
import json
import sys
import backend.app.core.deps as deps
print(json.dumps({
    'demo_module_loaded': 'backend.app.services.btc_demo_runtime' in sys.modules,
    'demo_service_is_none': deps.btc_demo_runtime_service is None,
}))
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[2],
        env={**os.environ, **READONLY_ENVIRONMENT},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "demo_module_loaded": False,
        "demo_service_is_none": True,
    }


def test_unknown_readonly_profile_fails_closed_during_cold_config_import() -> None:
    result = subprocess.run(
        [sys.executable, "-c", "import backend.app.core.config"],
        cwd=Path(__file__).resolve().parents[2],
        env={
            **os.environ,
            **READONLY_ENVIRONMENT,
            "QS_BACKEND_EVIDENCE_PROFILE": "research_readonly_typo",
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "backend_evidence_profile_invalid" in result.stderr


def test_cold_readonly_app_creation_avoids_runtime_and_external_side_effects() -> None:
    script = r"""
import builtins
import json
from pathlib import Path
import socket
import sqlite3
import sys
import urllib.request

from backend.app.api import app_factory

forbidden_modules = {
    'backend.app.services.btc_demo_runtime',
    'backend.app.services.us_ibkr_runtime',
    'quant_us.live.ibkr_runtime_provider',
}
before = {name: name in sys.modules for name in forbidden_modules}

def reject(*_args, **_kwargs):
    raise AssertionError('research_readonly_create_app_external_side_effect')

original_path_open = Path.open
def guarded_path_open(self, mode='r', *args, **kwargs):
    if any(flag in mode for flag in ('w', 'a', 'x', '+')):
        return reject(self, mode, *args, **kwargs)
    return original_path_open(self, mode, *args, **kwargs)

original_import = builtins.__import__
def guarded_import(name, *args, **kwargs):
    if name == 'backend.app.services.btc_private_readonly_observation':
        raise AssertionError('private_projection_must_not_be_imported_by_create_app')
    return original_import(name, *args, **kwargs)

builtins.__import__ = guarded_import
Path.mkdir = reject
Path.open = guarded_path_open
Path.write_text = reject
Path.write_bytes = reject
socket.create_connection = reject
urllib.request.urlopen = reject
sqlite3.connect = reject
app = app_factory.create_app()
after = {name: name in sys.modules for name in forbidden_modules}
print(json.dumps({'before': before, 'after': after, 'route_count': len(app.routes)}))
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[2],
        env={**os.environ, **READONLY_ENVIRONMENT},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["before"] == {name: False for name in payload["before"]}
    assert payload["after"] == {name: False for name in payload["after"]}
    assert payload["route_count"] > 0


@pytest.mark.parametrize(
    ("method", "path"),
    (
        ("GET", "/api/us/paper/status"),
        ("GET", "/api/us/paper/daily-results"),
        ("GET", "/api/research/candidates/example/lineage"),
        ("POST", "/api/tasks/integrations/qlib/run-pipeline"),
        ("POST", "/api/tasks/research/alpha-factory"),
    ),
)
def test_readonly_profile_blocks_side_effecting_or_unreviewed_routes_before_handler(
    monkeypatch: pytest.MonkeyPatch,
    method: str,
    path: str,
) -> None:
    client = _readonly_client(monkeypatch)

    response = client.request(method, path)

    assert response.status_code == 423
    assert response.headers["Cache-Control"] == "no-store"
    payload = response.json()
    assert payload["error"] == "backend_research_readonly_route_blocked"
    assert payload["evidence_profile"] == "research_readonly"
    assert payload["read_only"] is True
    assert payload["controls_disabled"] is True
    assert payload["paper_allowed"] is False
    assert payload["live_allowed"] is False
    assert payload["broker_or_order_allowed"] is False


def test_readonly_middleware_rejects_before_business_handlers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        app_factory,
        "_system_overview_payload",
        lambda *_args, **_kwargs: pytest.fail("system overview handler must not run"),
    )
    monkeypatch.setattr(
        app_factory.task_queue_service,
        "submit",
        lambda *_args, **_kwargs: pytest.fail("task submit handler must not run"),
    )
    client = _readonly_client(monkeypatch)

    assert client.get("/api/us/paper/status").status_code == 423
    assert client.post("/api/tasks/integrations/qlib/run-pipeline", json={}).status_code == 423


@pytest.mark.parametrize(
    "path",
    (
        "/api/system/overview",
        "/api/research/experiments",
        "/api/research/candidates",
        "/api/research/features",
        "/api/research/factors",
        "/api/research/strategy-manifests",
        "/api/research/paper-review/pending",
        "/api/research/paper-review/entry-state",
        "/api/research/evidence-registry",
        "/api/research/global-registry",
        "/api/research/btc/strategy-registry",
        "/api/research/strategy-history/catalog",
        "/api/integrations/qlib/runs",
        "/api/integrations/portfolio/runs",
        "/api/portfolio/status",
    ),
)
def test_readonly_profile_opens_reviewed_page_gets_without_opening_controls(
    monkeypatch: pytest.MonkeyPatch,
    path: str,
) -> None:
    client = _readonly_client(monkeypatch)

    response = client.get(path)

    assert response.status_code != 423, response.text


def test_readonly_page_gets_bypass_write_managers_and_external_side_effects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_root = tmp_path / "data" / "research"
    fixtures = {
        data_root / "experiments" / "exp-safe" / "manifest.json": {
            "experiment_id": "exp-safe",
            "strategy_id": "factor_rank",
            "created_at": "2026-09-13T01:00:00+00:00",
        },
        data_root / "candidates" / "cand-safe" / "candidate.json": {
            "candidate_id": "cand-safe",
            "experiment_id": "exp-safe",
            "strategy_id": "factor_rank",
            "created_at": "2026-09-13T02:00:00+00:00",
        },
        data_root / "manifests" / "manifest-safe" / "manifest.json": {
            "strategy_candidate_id": "manifest-safe",
            "source_candidate_id": "cand-safe",
            "source_experiment_id": "exp-safe",
            "promotion_status": "BLOCKED",
            "created_at": "2026-09-13T03:00:00+00:00",
        },
        data_root / "paper_reviews" / "review-safe" / "review.json": {
            "paper_review_id": "review-safe",
            "strategy_manifest_id": "manifest-safe",
            "status": "PENDING_HUMAN_REVIEW",
            "proposed_symbols": ["SPY"],
            "proposed_capital": 1000,
            "created_at": "2026-09-13T04:00:00+00:00",
        },
    }
    for path, payload in fixtures.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")

    client = _readonly_client(monkeypatch, repo_root=tmp_path)

    def reject(*_args, **_kwargs):
        raise AssertionError("research_readonly_request_side_effect")

    monkeypatch.setattr(Path, "mkdir", reject)
    monkeypatch.setattr(Path, "write_text", reject)
    monkeypatch.setattr(Path, "write_bytes", reject)
    monkeypatch.setattr(app_factory, "_system_overview_payload", reject)
    monkeypatch.setattr("socket.create_connection", reject)
    monkeypatch.setattr("sqlite3.connect", reject)
    monkeypatch.setattr("urllib.request.urlopen", reject)
    monkeypatch.setattr("quant_us.research.lab.manifest.ExperimentManager", reject)
    monkeypatch.setattr("quant_us.research.strategy_manifest.StrategyManifestManager", reject)
    monkeypatch.setattr("quant_us.research.paper_review_bridge.PaperReviewManager", reject)

    assert client.get("/api/research/experiments").json()[0]["experiment_id"] == "exp-safe"
    assert client.get("/api/research/candidates").json()[0]["candidate_id"] == "cand-safe"
    assert client.get("/api/research/strategy-manifests").json()[0]["strategy_candidate_id"] == "manifest-safe"
    assert client.get("/api/research/paper-review/pending").json()[0]["paper_review_id"] == "review-safe"
    overview = client.get("/api/system/overview").json()
    assert overview["mode"] == "research_readonly"
    assert overview["execution"]["permission"] is False
    assert overview["broker_credentials"]["checked"] is False
    entry = client.get("/api/research/paper-review/entry-state").json()
    assert entry["entry_allowed"] is False
    assert entry["creation"]["creation_allowed"] is False


@pytest.mark.parametrize(
    ("path", "expected_status"),
    (
        ("/api/health", 200),
        ("/api/strategies", 200),
        ("/api/tasks", 200),
        ("/api/integrations/qlib/runs", 200),
        ("/api/research/alpha-factory", 200),
        ("/api/research/evidence-registry", 200),
        ("/api/research/btc/domain-read-model", 503),
    ),
)
def test_readonly_profile_allows_only_reviewed_get_surfaces(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    path: str,
    expected_status: int,
) -> None:
    client = _readonly_client(monkeypatch)
    query = {"data_root": "data"} if path.endswith("evidence-registry") else None

    response = client.get(path, params=query)

    assert response.status_code == expected_status
    if path == "/api/health":
        payload = response.json()
        assert payload["evidence_profile"] == "research_readonly"
        assert payload["read_only"] is True
        assert payload["controls_disabled"] is True
        assert payload["paper_allowed"] is False
        assert payload["live_allowed"] is False
        assert payload["broker_or_order_allowed"] is False


@pytest.mark.parametrize(
    ("path", "query", "expected_status"),
    (
        ("/api/research/experiments", {"data_root": "../data"}, 400),
        ("/api/research/evidence-registry", {"data_root": "C:/outside"}, 400),
        ("/api/integrations/portfolio/runs", {"artifacts_root": "D:/outside"}, 400),
        ("/api/integrations/portfolio/runs/bad$id", {}, 423),
    ),
)
def test_readonly_profile_rejects_caller_selected_roots_and_invalid_ids(
    monkeypatch: pytest.MonkeyPatch,
    path: str,
    query: dict[str, str],
    expected_status: int,
) -> None:
    response = _readonly_client(monkeypatch).get(path, params=query)

    assert response.status_code == expected_status
    assert response.headers["Cache-Control"] == "no-store"
    payload = response.json()
    controls = payload if expected_status == 423 else payload["detail"]
    assert controls["controls_disabled"] is True


def test_readonly_profile_reports_damaged_json_as_conflict(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = tmp_path / "data/research/experiments/broken/manifest.json"
    record.parent.mkdir(parents=True)
    record.write_text("{not-json", encoding="utf-8")

    response = _readonly_client(monkeypatch, repo_root=tmp_path).get(
        "/api/research/experiments"
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "research_readonly_record_unreadable"


def test_readonly_profile_reports_damaged_feature_manifest_as_conflict(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = tmp_path / "data/features/snapshots/broken/manifest.json"
    record.parent.mkdir(parents=True)
    record.write_text("{not-json", encoding="utf-8")

    response = _readonly_client(monkeypatch, repo_root=tmp_path).get(
        "/api/research/features"
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "research_readonly_record_unreadable"


def test_readonly_registry_rebuild_query_remains_method_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = _readonly_client(monkeypatch).get(
        "/api/research/evidence-registry",
        params={"rebuild": "true"},
    )

    assert response.status_code == 405
    assert response.json()["detail"]["code"] == "registry_rebuild_requires_post"


def test_readonly_profile_returns_cors_preflight_without_opening_controls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = _readonly_client(monkeypatch).options(
        "/api/tasks/research/alpha-factory",
        headers={
            "Origin": "http://127.0.0.1:3000",
            "Access-Control-Request-Method": "POST",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:3000"
