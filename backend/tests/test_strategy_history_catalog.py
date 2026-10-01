from __future__ import annotations

import hashlib
import inspect
import json
import subprocess
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api.strategy_history_catalog import build_strategy_history_catalog_router
from backend.app.services import strategy_history_catalog as catalog_module
from backend.app.services.strategy_history_catalog import StrategyHistoryCatalogService


TRUSTED_EXPERIMENTS = [f"exp_trusted_{index}" for index in range(6)]


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _experiment(
    experiment_id: str,
    *,
    status: str,
    run_id: str = "",
    metrics: dict | None = None,
    run_result_path: str | None = None,
    backtest_manifest_path: str | None = None,
) -> dict:
    if run_id:
        run_result_path = run_result_path or (
            f"data/research/experiments/{experiment_id}/run_result.json"
        )
        backtest_manifest_path = backtest_manifest_path or f"data/manifests/run_{run_id}.json"
    return {
        "experiment_id": experiment_id,
        "strategy_id": "trend_momentum",
        "strategy_family": f"family_{experiment_id}",
        "status": status,
        "params": {"lookback": 20},
        "metrics": metrics if metrics is not None else {},
        "run_result_path": run_result_path,
        "backtest_manifest_path": backtest_manifest_path,
        "created_at": "2026-01-01T00:00:00+00:00",
    }


@pytest.fixture()
def sparse_main_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    repo = tmp_path / "main"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.name", "Catalog Test")
    _git(repo, "config", "user.email", "catalog@example.invalid")
    (repo / "backend").mkdir()
    (repo / "backend" / ".keep").write_text("", encoding="utf-8")

    for index, experiment_id in enumerate(TRUSTED_EXPERIMENTS):
        run_id = f"ubt_{index:02d}"
        _write_json(
            repo / "data" / "research" / "experiments" / experiment_id / "manifest.json",
            _experiment(
                experiment_id,
                status="PROMOTED_TO_CANDIDATE",
                run_id=run_id,
                metrics={
                    "sharpe_ratio": 0.5 + index,
                    "total_return_pct": 1.0 + index,
                    "backtest_manifest_path": f"C:/private/should-not-leak/{index}",
                },
            ),
        )
        _write_json(
            repo / "data" / "research" / "candidates" / f"cand_{index}" / "candidate.json",
            {
                "candidate_id": f"cand_{index}",
                "experiment_id": experiment_id,
                "strategy_id": "trend_momentum",
                "params_hash": f"params_{index}",
                "promotion_status": "RESEARCH_ONLY",
            },
        )
        _write_json(
            repo / "data" / "research" / "manifests" / f"sman_{index}" / "manifest.json",
            {
                "strategy_candidate_id": f"sman_{index}",
                "source_candidate_id": f"cand_{index}",
                "source_experiment_id": experiment_id,
                "promotion_status": "BLOCKED",
                "promotion_gate_decision": "BLOCKED",
            },
        )

    excluded = [
        ("exp_failed_0", "FAILED"),
        ("exp_failed_1", "FAILED"),
        ("exp_failed_2", "FAILED"),
        ("exp_running", "RUNNING"),
        ("exp_stub_0", "COMPLETED"),
        ("exp_stub_1", "COMPLETED"),
        ("exp_stub_2", "COMPLETED"),
        ("exp_stub_3", "COMPLETED"),
    ]
    for experiment_id, status in excluded:
        _write_json(
            repo / "data" / "research" / "experiments" / experiment_id / "manifest.json",
            _experiment(experiment_id, status=status),
        )
    for index in range(3):
        _write_json(
            repo / "data" / "research" / "candidates" / f"stub_{index}" / "candidate.json",
            {
                "candidate_id": f"stub_{index}",
                "experiment_id": f"exp_stub_{index}",
                "strategy_id": "trend_momentum",
                "promotion_status": "PAPER_ELIGIBLE",
            },
        )

    _git(repo, "add", "backend", "data/research")
    _git(repo, "commit", "-m", "test catalog fixtures")
    _git(repo, "sparse-checkout", "init", "--cone")
    _git(repo, "sparse-checkout", "set", "backend")
    assert not (repo / "data" / "research").exists()
    monkeypatch.setattr(catalog_module, "_code_repository_root", lambda: repo)
    return repo


def test_git_head_catalog_reads_six_records_when_sparse_data_is_absent(
    sparse_main_repo: Path,
) -> None:
    payload = StrategyHistoryCatalogService().get_catalog()

    assert payload["schema_version"] == "strategy_history_catalog_v1"
    assert payload["status"] == "complete", payload["coverage"]["us_equity"]["errors"]
    assert payload["head"] == _git(sparse_main_repo, "rev-parse", "HEAD")
    assert len(payload["records"]) == 6
    assert {record["experiment_id"] for record in payload["records"]} == set(
        TRUSTED_EXPERIMENTS
    )
    assert {record["record_kind"] for record in payload["records"]} == {"research_run"}
    assert {record["candidate_id"] for record in payload["records"]} == {
        f"cand_{index}" for index in range(6)
    }
    assert {record["promotion_status"] for record in payload["records"]} == {"blocked"}
    assert payload["coverage"]["us_equity"] == {
        "status": "complete",
        "source": "tracked_git_object",
        "git_record_count": 6,
        "runtime_record_count": 0,
        "runtime_user_runs": "empty",
        "record_count": 6,
        "errors": [],
    }
    assert payload["coverage"]["btc"]["status"] == "existing_endpoint_separate"
    assert payload["coverage"]["cn"]["status"] == "unavailable"

    source_path = "data/research/experiments/exp_trusted_0/manifest.json"
    raw = subprocess.run(
        ["git", "-C", str(sparse_main_repo), "cat-file", "blob", f"HEAD:{source_path}"],
        check=True,
        capture_output=True,
    ).stdout
    first = next(record for record in payload["records"] if record["experiment_id"] == "exp_trusted_0")
    assert first["artifact_sha256"] == hashlib.sha256(raw).hexdigest()
    assert first["artifact_path"] == source_path
    assert first["report_href"] == ""
    assert "backtest_manifest_path" not in first["metrics"]
    assert str(sparse_main_repo) not in json.dumps(payload)


def test_catalog_route_is_get_only_has_no_caller_root_and_keeps_safety_false(
    sparse_main_repo: Path,
) -> None:
    app = FastAPI()
    router = build_strategy_history_catalog_router(StrategyHistoryCatalogService())
    assert len(router.routes) == 1
    route = router.routes[0]
    assert route.methods == {"GET"}
    assert not inspect.signature(route.endpoint).parameters
    app.include_router(router, prefix="/api")

    client = TestClient(app)
    response = client.get(
        "/api/research/strategy-history/catalog",
        params={"data_root": "C:/private/ignored"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert len(payload["records"]) == 6
    for key in (
        "paper_allowed",
        "live_allowed",
        "broker_or_order_allowed",
        "private_endpoint_used",
        "order_endpoint_used",
        "real_order_submitted",
    ):
        assert payload[key] is False
    for record in payload["records"]:
        assert record["paper_allowed"] is False
        assert record["live_allowed"] is False
        assert record["private_endpoint_used"] is False
        assert record["order_endpoint_used"] is False
        assert record["real_order_submitted"] is False
    assert client.post("/api/research/strategy-history/catalog").status_code == 405
    assert "C:/private/ignored" not in json.dumps(payload)


def test_absent_runtime_directories_have_zero_side_effects(
    sparse_main_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_mkdir(*args, **kwargs):
        raise AssertionError("catalog GET must never mkdir")

    monkeypatch.setattr(Path, "mkdir", fail_mkdir)
    payload = StrategyHistoryCatalogService().get_catalog()
    assert len(payload["records"]) == 6
    assert payload["coverage"]["us_equity"]["runtime_user_runs"] == "empty"


def test_runtime_completed_run_is_discovered_and_deduplicated_by_run_key(
    sparse_main_repo: Path,
) -> None:
    experiments = sparse_main_repo / "data" / "research" / "experiments"
    _write_json(
        experiments / "exp_runtime_new" / "manifest.json",
        _experiment(
            "exp_runtime_new",
            status="COMPLETED",
            run_id="ubt_runtime_new",
            metrics={"sharpe_ratio": 1.25, "total_return_pct": 4.2},
        ),
    )
    _write_json(
        experiments / "exp_runtime_duplicate" / "manifest.json",
        _experiment(
            "exp_runtime_duplicate",
            status="COMPLETED",
            run_id="ubt_00",
            metrics={"sharpe_ratio": 99.0},
        ),
    )
    _write_json(
        experiments / "exp_runtime_escape" / "manifest.json",
        _experiment(
            "exp_runtime_escape",
            status="COMPLETED",
            run_id="ubt_escape",
            metrics={"sharpe_ratio": 99.0},
            run_result_path="../private/run_result.json",
        ),
    )

    payload = StrategyHistoryCatalogService().get_catalog()
    assert len(payload["records"]) == 7
    runtime = next(record for record in payload["records"] if record["run_id"] == "ubt_runtime_new")
    assert runtime["source"] == "registered_main_runtime"
    assert runtime["freshness"]["status"] == "runtime_uncommitted"
    assert not any(record["experiment_id"] == "exp_runtime_duplicate" for record in payload["records"])
    assert not any(record["experiment_id"] == "exp_runtime_escape" for record in payload["records"])
    coverage = payload["coverage"]["us_equity"]
    assert coverage["git_record_count"] == 6
    assert coverage["runtime_record_count"] == 1
    assert coverage["runtime_user_runs"] == "available"


def test_runtime_symlink_is_rejected_without_losing_git_head_records(
    sparse_main_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    experiments = sparse_main_repo / "data" / "research" / "experiments"
    _write_json(
        experiments / "evil" / "manifest.json",
        _experiment(
            "evil",
            status="COMPLETED",
            run_id="ubt_evil",
            metrics={"sharpe_ratio": 100.0},
        ),
    )
    original_is_symlink = Path.is_symlink

    def simulated_symlink(path: Path) -> bool:
        if path == experiments:
            return True
        return original_is_symlink(path)

    monkeypatch.setattr(Path, "is_symlink", simulated_symlink)

    payload = StrategyHistoryCatalogService().get_catalog()
    assert len(payload["records"]) == 6
    assert payload["status"] == "partial"
    assert payload["coverage"]["us_equity"]["runtime_user_runs"] == "partial"
    assert "experiments_runtime_symlink_rejected" in payload["coverage"]["us_equity"]["errors"]
    assert not any(record["experiment_id"] == "evil" for record in payload["records"])
