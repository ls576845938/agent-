from time import sleep
from concurrent.futures import Future as ConcurrentFuture, ThreadPoolExecutor
from dataclasses import replace
import hashlib
import importlib
import inspect
import json
from pathlib import Path
from threading import Event, Lock

from fastapi.testclient import TestClient
import pytest


class _LocalOnlyResearchArchive:
    """Test double for the fixed M1 archive; it never adds external fixtures."""

    @staticmethod
    def _location(kind, root, run_id, qlib_root=None):
        from backend.app.services.research_archive_discovery import ReadonlyRunLocation

        parent = "qlib_runs" if kind == "qlib" else "alpha_factory_runs"
        return ReadonlyRunLocation(
            run_id=run_id,
            run_root=Path(root) / run_id,
            qlib_root=Path(qlib_root or root),
            logical_root=f"artifacts/{parent}/{run_id}",
            provenance={"storage": "repo_local", "consumer_read_only": True},
        )

    def list_qlib_runs(self, root):
        return tuple(self._location("qlib", root, path.name) for path in Path(root).iterdir()
                     if path.is_dir()) if Path(root).exists() else ()

    def resolve_qlib_run(self, root, run_id):
        return self._location("qlib", root, run_id) if (Path(root) / run_id).exists() else None

    def list_factory_runs(self, root, qlib_root):
        return tuple(self._location("factory", root, path.name, qlib_root)
                     for path in Path(root).iterdir()
                     if path.is_dir() and (path / "state.json").is_file()) if Path(root).exists() else ()

    def resolve_factory_run(self, root, qlib_root, run_id):
        return (self._location("factory", root, run_id, qlib_root)
                if (Path(root) / run_id / "state.json").is_file() else None)


def _external_candidate_catalog(app_factory, tmp_path):
    from quant_shared.strategy_delivery.models import digest

    root = tmp_path / "external-candidate-catalog"
    (root / "factory").mkdir(parents=True)
    (root / "qlib").mkdir()
    payload = {
        "schema_version": "candidate_offline_catalog_v1",
        "repository_owner": digest({"repository": str(app_factory.settings.repo_root.resolve())}),
        "revision": "fixture-v1",
        "factory_root": "factory",
        "qlib_root": "qlib",
        "sources": [],
        "inputs": [],
    }
    path = root / "catalog.json"
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    return root, path, replace(
        app_factory.settings,
        backend_evidence_profile="research_readonly",
        candidate_delivery_root="",
        candidate_offline_catalog=str(path),
        candidate_offline_catalog_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        candidate_offline_catalog_revision="fixture-v1",
    )


def _client(monkeypatch):
    from backend.app.api import app_factory
    from backend.app.services.task_queue import TaskQueueService
    monkeypatch.setattr(app_factory,"task_queue_service",TaskQueueService(max_workers=1))
    return TestClient(app_factory.create_app())


def _qlib_list_endpoint_with_catalog(monkeypatch, tmp_path, catalog):
    from backend.app.api import app_factory

    class ObservedFuture(ConcurrentFuture):
        def result(self, *args, **kwargs):
            catalog.follower_waiting.set()
            return super().result(*args, **kwargs)

    monkeypatch.setattr(
        app_factory,
        "settings",
        replace(app_factory.settings, backend_evidence_profile="research_readonly"),
    )
    monkeypatch.setattr(app_factory, "QLIB_ARTIFACTS_ROOT", tmp_path / "missing")
    monkeypatch.setattr(app_factory, "build_m1_research_archive_catalog", lambda **_: catalog)
    monkeypatch.setattr(app_factory, "Future", ObservedFuture)
    app = app_factory.create_app()
    candidate_routes = list(app.routes)
    for outer_route in app.routes:
        nested_app = getattr(outer_route, "app", None)
        if hasattr(nested_app, "routes"):
            candidate_routes.extend(nested_app.routes)
        included_router = getattr(outer_route, "original_router", None)
        if hasattr(included_router, "routes"):
            candidate_routes.extend(included_router.routes)
    return next(
        route.endpoint
        for route in candidate_routes
        if getattr(route, "path", "") == "/api/integrations/qlib/runs"
    )


class _BlockingQlibCatalog:
    def __init__(self, *, fail: bool = False):
        self.calls = 0
        self.fail = fail
        self.entered = Event()
        self.second_call = Event()
        self.follower_waiting = Event()
        self.release = Event()
        self.lock = Lock()

    def list_qlib_runs(self, _root):
        from backend.app.services.research_archive_discovery import ResearchArchiveUnavailable

        with self.lock:
            self.calls += 1
            if self.calls == 2:
                self.second_call.set()
        self.entered.set()
        assert self.release.wait(timeout=3)
        if self.fail:
            raise ResearchArchiveUnavailable("fixture_archive_unavailable")
        return ()


@pytest.mark.parametrize("failure_stage",["dataset","training","scores","metrics","candidate","decisions"])
def test_qlib_pipeline_task_reports_computation_failure(monkeypatch,failure_stage):
    from integrations.qlib_adapter.schemas import QlibAdapterError
    module = importlib.import_module("integrations.qlib_adapter.research_pipeline")
    def fail(request, **kwargs):
        raise QlibAdapterError("qlib_pipeline_failed:api-fixture:"+failure_stage+":fixture_failure")
    monkeypatch.setattr(module,"run_research_pipeline",fail)
    client = _client(monkeypatch)
    response = client.post("/api/tasks/integrations/qlib/run-pipeline",json={"profile_id":"okx_btc_trend_1h","run_id":"api-fixture"})
    assert response.status_code == 200,response.text
    task_id = response.json()["task_id"]
    for _ in range(100):
        task = client.get("/api/tasks/"+task_id).json()
        if task["status"] not in {"running","queued"}:
            break
        sleep(.02)
    assert task["status"] == "failed"
    assert failure_stage in task["error"]
    assert not task.get("result")


def test_qlib_pipeline_api_rejects_permission_and_path_overrides(monkeypatch):
    client = _client(monkeypatch)
    for override in ({"private":True},{"live":True},{"config":"arbitrary.yaml"},{"run_id":"../other"}):
        response = client.post("/api/tasks/integrations/qlib/run-pipeline",json={"profile_id":"okx_btc_trend_1h",**override})
        assert response.status_code == 400


def test_qlib_run_listing_has_market_profiles(monkeypatch,tmp_path):
    from backend.app.api import app_factory
    monkeypatch.setattr(app_factory, "QLIB_ARTIFACTS_ROOT", tmp_path/"missing")
    client = _client(monkeypatch)
    response = client.get("/api/integrations/qlib/runs")
    assert response.status_code == 200
    payload = response.json()
    assert {item["asset_class"] for item in payload["profiles"]} == {"crypto","equity"}
    assert payload["daily_only"] is False and payload["live_enabled"] is False
    assert not (tmp_path/"missing").exists()


def test_qlib_gets_use_validated_external_candidate_catalog(monkeypatch, tmp_path):
    from backend.app.api import app_factory
    from integrations.qlib_adapter.research_pipeline import seal_run
    from integrations.qlib_adapter.schemas import write_json

    external, _catalog_path, configured = _external_candidate_catalog(app_factory, tmp_path)
    run_root = external / "qlib" / "external-run"
    write_json(run_root / "pipeline_result.json", {
        "run_id": "external-run", "profile_id": "okx_btc_trend_1h",
        "asset_class": "crypto", "bar_size": "1h", "status": "completed",
    })
    seal_run(run_root)
    legacy = tmp_path / "legacy"
    write_json(legacy / "legacy-decoy" / "pipeline_result.json", {
        "run_id": "legacy-decoy", "status": "completed",
    })
    seal_run(legacy / "legacy-decoy")
    monkeypatch.setattr(app_factory, "settings", configured)
    monkeypatch.setattr(app_factory, "QLIB_ARTIFACTS_ROOT", legacy)
    monkeypatch.setattr(
        app_factory,
        "build_m1_research_archive_catalog",
        lambda **_: _LocalOnlyResearchArchive(),
    )

    with TestClient(app_factory.create_app()) as client:
        listing = client.get("/api/integrations/qlib/runs")
        detail = client.get("/api/integrations/qlib/runs/external-run")
        missing = client.get("/api/integrations/qlib/runs/legacy-decoy")

    assert listing.status_code == 200, listing.text
    assert [row["run_id"] for row in listing.json()["runs"]] == ["external-run"]
    assert listing.json()["runs"][0]["evidence_provenance"]["storage"] == "external_candidate_catalog"
    assert str(external) not in listing.text
    assert detail.status_code == 200, detail.text
    assert detail.json()["summary"]["evidence_provenance"]["catalog_revision"] == "fixture-v1"
    assert missing.status_code == 404


def test_configured_catalog_tamper_fails_closed_without_legacy_fallback(monkeypatch, tmp_path):
    from backend.app.api import app_factory

    external, catalog_path, configured = _external_candidate_catalog(app_factory, tmp_path)
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    monkeypatch.setattr(app_factory, "settings", configured)
    monkeypatch.setattr(app_factory, "QLIB_ARTIFACTS_ROOT", legacy)
    monkeypatch.setattr(
        app_factory,
        "build_m1_research_archive_catalog",
        lambda **_: _LocalOnlyResearchArchive(),
    )
    with TestClient(app_factory.create_app()) as client:
        catalog_path.write_text("{}", encoding="utf-8")
        qlib = client.get("/api/integrations/qlib/runs")
        factory = client.get("/api/research/alpha-factory")
        research_write = client.post(
            "/api/tasks/research/alpha-factory",
            json={"profile_id": "okx_btc_trend_1h", "run_id": "must-not-write"},
        )

    assert qlib.status_code == 503 and "offline_input_hash_mismatch" in qlib.text
    assert factory.status_code == 503 and "offline_input_hash_mismatch" in factory.text
    assert research_write.status_code == 423
    assert not (external / "factory" / "must-not-write").exists()


@pytest.mark.parametrize("fault", ["hash", "owner", "revision"])
def test_invalid_configured_catalog_is_503_not_empty_legacy(monkeypatch, tmp_path, fault):
    from backend.app.api import app_factory

    _external, catalog_path, configured = _external_candidate_catalog(app_factory, tmp_path)
    if fault == "hash":
        configured = replace(configured, candidate_offline_catalog_sha256="0" * 64)
        expected = "offline_input_hash_mismatch"
    else:
        payload = json.loads(catalog_path.read_text(encoding="utf-8"))
        payload["repository_owner" if fault == "owner" else "revision"] = "wrong"
        catalog_path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        configured = replace(
            configured,
            candidate_offline_catalog_sha256=hashlib.sha256(catalog_path.read_bytes()).hexdigest(),
        )
        expected = "offline_catalog_identity_mismatch"
    monkeypatch.setattr(app_factory, "settings", configured)
    monkeypatch.setattr(
        app_factory,
        "build_m1_research_archive_catalog",
        lambda **_: _LocalOnlyResearchArchive(),
    )
    with TestClient(app_factory.create_app()) as client:
        qlib = client.get("/api/integrations/qlib/runs")
        factory = client.get("/api/research/alpha-factory")

    assert qlib.status_code == 503 and expected in qlib.text
    assert factory.status_code == 503 and expected in factory.text


@pytest.mark.parametrize("fault", ["missing", "malformed_json", "malformed_shape"])
def test_unreadable_configured_catalog_is_stable_503(monkeypatch, tmp_path, fault):
    from backend.app.api import app_factory

    _external, catalog_path, configured = _external_candidate_catalog(app_factory, tmp_path)
    if fault == "missing":
        catalog_path.unlink()
    else:
        catalog_path.write_text("{" if fault == "malformed_json" else "[{}]", encoding="utf-8")
        configured = replace(
            configured,
            candidate_offline_catalog_sha256=hashlib.sha256(catalog_path.read_bytes()).hexdigest(),
        )
    monkeypatch.setattr(app_factory, "settings", configured)
    monkeypatch.setattr(
        app_factory,
        "build_m1_research_archive_catalog",
        lambda **_: _LocalOnlyResearchArchive(),
    )

    with TestClient(app_factory.create_app()) as client:
        qlib = client.get("/api/integrations/qlib/runs")
        factory = client.get("/api/research/alpha-factory")

    assert qlib.status_code == 503 and "offline_catalog_unreadable" in qlib.text
    assert factory.status_code == 503 and "offline_catalog_unreadable" in factory.text


def test_catalog_deleted_after_startup_is_stable_503(monkeypatch, tmp_path):
    from backend.app.api import app_factory

    _external, catalog_path, configured = _external_candidate_catalog(app_factory, tmp_path)
    monkeypatch.setattr(app_factory, "settings", configured)
    monkeypatch.setattr(
        app_factory,
        "build_m1_research_archive_catalog",
        lambda **_: _LocalOnlyResearchArchive(),
    )
    with TestClient(app_factory.create_app()) as client:
        catalog_path.unlink()
        qlib = client.get("/api/integrations/qlib/runs")
        factory = client.get("/api/research/alpha-factory")

    assert qlib.status_code == 503 and "offline_catalog_unreadable" in qlib.text
    assert factory.status_code == 503 and "offline_catalog_unreadable" in factory.text


def test_failed_dataset_keeps_sealed_crypto_identity_in_summary(monkeypatch, tmp_path):
    from backend.app.api import app_factory
    from integrations.qlib_adapter.schemas import write_json
    from integrations.qlib_adapter.research_pipeline import seal_run
    monkeypatch.setattr(app_factory, "QLIB_ARTIFACTS_ROOT", tmp_path)
    root = tmp_path/"failed-crypto"
    write_json(root/"pipeline_result.json", {"run_id": "failed-crypto", "profile_id": "okx_btc_trend_1h",
        "asset_class": "crypto", "bar_size": "1h", "status": "failed", "failure_stage": "dataset"})
    seal_run(root)
    client = _client(monkeypatch)
    detail = client.get("/api/integrations/qlib/runs/failed-crypto").json()
    listing = client.get("/api/integrations/qlib/runs").json()["runs"][0]
    for summary in (detail["summary"], listing):
        assert summary["asset_class"] == "crypto" and summary["bar_size"] == "1h"
        assert summary["pipeline_status"] == "failed"
    assert detail["execution_permission"] is False
    unknown_root = tmp_path/"unknown-identity"
    write_json(unknown_root/"workflow_run_result.json", {"status": "failed"})
    seal_run(unknown_root)
    unknown = client.get("/api/integrations/qlib/runs/unknown-identity").json()
    assert unknown["summary"]["asset_class"] == "unknown" and unknown["summary"]["bar_size"] == "unknown"


def test_evidence_root_is_server_owned_and_invalid_seal_exposes_no_facts(monkeypatch,tmp_path):
    from backend.app.api import app_factory
    from integrations.qlib_adapter.schemas import write_json
    from integrations.qlib_adapter.research_pipeline import seal_run
    monkeypatch.setattr(app_factory,"QLIB_ARTIFACTS_ROOT",tmp_path)
    client = _client(monkeypatch)
    for path in ("/api/integrations/qlib/runs","/api/integrations/qlib/runs/sealed-test"):
        assert client.get(path,params={"artifacts_root":str(tmp_path)}).status_code == 400
    root = tmp_path/"sealed-test"
    write_json(root/"pipeline_result.json",{"run_id":"sealed-test","status":"completed"})
    write_json(root/"signal_evaluation.json",{"run_id":"sealed-test","test":{"mse":1}})
    write_json(root/"recorder_metrics.json",{"id":"recorder-test"})
    seal_run(root)
    url = "/api/integrations/qlib/runs/sealed-test"
    assert client.get(url).json()["integrity_status"] == "passed"
    write_json(root/"recorder_metrics.json",{"id":"tampered"})
    payload = client.get(url).json()
    assert payload["integrity_status"] == "blocked"
    assert payload["summary"]["run_id"] == "sealed-test"
    assert not ({"pipeline","signal_evaluation","dataset_manifest","provider_manifest","workflow_result",
        "failure_report","recorder_metrics","strategy_manifest","scores_preview","research_trace"} & payload.keys())
    assert payload["execution_permission"] is False
    listing = client.get("/api/integrations/qlib/runs").json()["runs"][0]
    assert listing["integrity_status"] == "blocked" and "score_rows" not in listing


def test_qlib_list_applies_limit_before_seal_verification(monkeypatch, tmp_path):
    from backend.app.api import app_factory
    from integrations.qlib_adapter import research_pipeline
    from integrations.qlib_adapter.schemas import write_json

    monkeypatch.setattr(app_factory, "QLIB_ARTIFACTS_ROOT", tmp_path)
    for index in range(4):
        run_root = tmp_path / f"run-{index}"
        write_json(
            run_root / "pipeline_result.json",
            {"run_id": run_root.name, "status": "completed"},
        )
        research_pipeline.seal_run(run_root)
        stamp = 1_700_000_000 + index
        import os

        os.utime(run_root, (stamp, stamp))

    calls: list[str] = []
    original = research_pipeline.read_sealed_evidence

    def counted(run_root: Path, **kwargs):
        calls.append(run_root.name)
        return original(run_root, **kwargs)

    monkeypatch.setattr(research_pipeline, "read_sealed_evidence", counted)
    response = _client(monkeypatch).get("/api/integrations/qlib/runs", params={"limit": 2})

    assert response.status_code == 200
    assert [row["run_id"] for row in response.json()["runs"]] == ["run-3", "run-2"]
    assert calls == ["run-3", "run-2"]


def test_qlib_list_validates_run_summaries_with_bounded_parallelism(monkeypatch, tmp_path):
    from backend.app.services.research_archive_discovery import ReadonlyRunLocation
    from integrations.qlib_adapter import research_pipeline

    locations = tuple(
        ReadonlyRunLocation(
            run_id=f"parallel-{index}",
            run_root=tmp_path / f"parallel-{index}",
            qlib_root=tmp_path,
            logical_root=f"artifacts/qlib_runs/parallel-{index}",
            provenance={"storage": "repo_local", "consumer_read_only": True},
        )
        for index in range(8)
    )
    catalog = _BlockingQlibCatalog()

    def list_runs(_root):
        catalog.calls += 1
        return locations

    catalog.list_qlib_runs = list_runs
    endpoint = _qlib_list_endpoint_with_catalog(monkeypatch, tmp_path, catalog)
    state_lock = Lock()
    first_entered = Event()
    four_active = Event()
    release = Event()
    calls = 0
    active = 0
    max_active = 0

    def blocking_reader(_run_root, **_kwargs):
        nonlocal calls, active, max_active
        with state_lock:
            calls += 1
            active += 1
            max_active = max(max_active, active)
            first_entered.set()
            if active == 4:
                four_active.set()
        try:
            assert release.wait(timeout=3)
            return {
                "integrity_status": "blocked",
                "blockers": ["fixture_blocked"],
                "execution_permission": False,
            }
        finally:
            with state_lock:
                active -= 1

    monkeypatch.setattr(research_pipeline, "read_sealed_evidence", blocking_reader)
    with ThreadPoolExecutor(max_workers=1) as caller:
        response = caller.submit(endpoint, limit=8)
        assert first_entered.wait(timeout=2)
        reached_bound = four_active.wait(timeout=1)
        release.set()
        payload = response.result(timeout=5)

    assert reached_bound
    assert max_active == 4
    assert calls == 8
    assert catalog.calls == 1
    assert [row["run_id"] for row in payload["runs"]] == [
        location.run_id for location in locations
    ]
    assert all(row["integrity_status"] == "blocked" for row in payload["runs"])


def test_qlib_list_different_keys_share_app_summary_worker_bound(monkeypatch, tmp_path):
    from backend.app.services.research_archive_discovery import ReadonlyRunLocation
    from integrations.qlib_adapter import research_pipeline

    locations = tuple(
        ReadonlyRunLocation(
            run_id=f"shared-bound-{index}",
            run_root=tmp_path / f"shared-bound-{index}",
            qlib_root=tmp_path,
            logical_root=f"artifacts/qlib_runs/shared-bound-{index}",
            provenance={"storage": "repo_local", "consumer_read_only": True},
        )
        for index in range(8)
    )
    catalog = _BlockingQlibCatalog()

    def list_runs(_root):
        with catalog.lock:
            catalog.calls += 1
        return locations

    catalog.list_qlib_runs = list_runs
    endpoint = _qlib_list_endpoint_with_catalog(monkeypatch, tmp_path, catalog)
    state_lock = Lock()
    four_active = Event()
    release = Event()
    calls = 0
    active = 0
    max_active = 0

    def blocking_reader(_run_root, **_kwargs):
        nonlocal calls, active, max_active
        with state_lock:
            calls += 1
            active += 1
            max_active = max(max_active, active)
            if active == 4:
                four_active.set()
        try:
            assert release.wait(timeout=3)
            return {
                "integrity_status": "blocked",
                "blockers": ["fixture_blocked"],
                "execution_permission": False,
            }
        finally:
            with state_lock:
                active -= 1

    monkeypatch.setattr(research_pipeline, "read_sealed_evidence", blocking_reader)
    with ThreadPoolExecutor(max_workers=2) as callers:
        first = callers.submit(endpoint, limit=8)
        second = callers.submit(endpoint, limit=7)
        assert four_active.wait(timeout=2)
        release.set()
        assert len(first.result(timeout=5)["runs"]) == 8
        assert len(second.result(timeout=5)["runs"]) == 7

    assert max_active == 4
    assert calls == 15
    assert catalog.calls == 2


def test_qlib_list_parallel_summary_error_is_fail_closed_and_revalidated(monkeypatch, tmp_path):
    from backend.app.services.research_archive_discovery import ReadonlyRunLocation
    from integrations.qlib_adapter import research_pipeline

    locations = tuple(
        ReadonlyRunLocation(
            run_id=f"mixed-{index}",
            run_root=tmp_path / f"mixed-{index}",
            qlib_root=tmp_path,
            logical_root=f"artifacts/qlib_runs/mixed-{index}",
            provenance={"storage": "repo_local", "consumer_read_only": True},
        )
        for index in range(3)
    )
    catalog = _BlockingQlibCatalog()

    def list_runs(_root):
        catalog.calls += 1
        return locations

    catalog.list_qlib_runs = list_runs
    endpoint = _qlib_list_endpoint_with_catalog(monkeypatch, tmp_path, catalog)
    calls = {location.run_id: 0 for location in locations}
    fail = True
    leader_held = Event()
    release_leader = Event()

    def mixed_reader(run_root, **_kwargs):
        nonlocal fail
        calls[run_root.name] += 1
        if run_root.name == "mixed-0" and fail:
            leader_held.set()
            assert release_leader.wait(timeout=3)
        if run_root.name == "mixed-2" and fail:
            raise ValueError("fixture_summary_failure")
        if run_root.name == "mixed-1":
            return {
                "integrity_status": "blocked",
                "blockers": ["fixture_blocked"],
                "execution_permission": False,
            }
        return {"integrity_status": "passed"}

    monkeypatch.setattr(research_pipeline, "read_sealed_evidence", mixed_reader)
    with ThreadPoolExecutor(max_workers=2) as callers:
        responses = [callers.submit(endpoint, limit=3)]
        assert leader_held.wait(timeout=2)
        responses.append(callers.submit(endpoint, limit=3))
        assert catalog.follower_waiting.wait(timeout=2)
        release_leader.set()
        for response in responses:
            with pytest.raises(ValueError, match="fixture_summary_failure"):
                response.result(timeout=5)

    assert calls == {"mixed-0": 1, "mixed-1": 1, "mixed-2": 1}
    fail = False
    payload = endpoint(limit=3)

    assert catalog.calls == 2
    assert calls == {"mixed-0": 2, "mixed-1": 2, "mixed-2": 2}
    assert [row["run_id"] for row in payload["runs"]] == [
        "mixed-0",
        "mixed-1",
        "mixed-2",
    ]
    assert payload["runs"][0]["pipeline_status"] == "not_run"
    assert payload["runs"][1]["integrity_status"] == "blocked"
    assert payload["runs"][2]["pipeline_status"] == "not_run"


def test_qlib_summary_executor_shutdown_waits_without_cancelling(monkeypatch):
    from backend.app.api import app_factory

    shutdown_calls = []

    class ObservedExecutor(ThreadPoolExecutor):
        def shutdown(self, wait=True, *, cancel_futures=False):
            shutdown_calls.append((wait, cancel_futures))
            return super().shutdown(wait=wait, cancel_futures=cancel_futures)

    monkeypatch.setattr(
        app_factory,
        "settings",
        replace(app_factory.settings, backend_evidence_profile="research_readonly"),
    )
    monkeypatch.setattr(app_factory, "ThreadPoolExecutor", ObservedExecutor)
    monkeypatch.setattr(
        app_factory,
        "build_m1_research_archive_catalog",
        lambda **_: _BlockingQlibCatalog(),
    )

    with TestClient(app_factory.create_app()):
        pass

    assert shutdown_calls == [(True, False)]


def test_qlib_list_coalesces_only_overlapping_identical_reads(monkeypatch, tmp_path):
    catalog = _BlockingQlibCatalog()
    endpoint = _qlib_list_endpoint_with_catalog(monkeypatch, tmp_path, catalog)

    with ThreadPoolExecutor(max_workers=2) as executor:
        reads = [executor.submit(endpoint, limit=20)]
        assert catalog.entered.wait(timeout=2)
        reads.append(executor.submit(endpoint, limit=20))
        follower_joined = catalog.follower_waiting.wait(timeout=2)
        catalog.release.set()
        payloads = [read.result(timeout=3) for read in reads]

    assert follower_joined
    assert catalog.calls == 1
    assert payloads[0] == payloads[1]
    assert payloads[0]["runs"] == []

    endpoint(limit=20)
    assert catalog.calls == 2


def test_qlib_list_does_not_coalesce_different_limits(monkeypatch, tmp_path):
    catalog = _BlockingQlibCatalog()
    endpoint = _qlib_list_endpoint_with_catalog(monkeypatch, tmp_path, catalog)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(endpoint, limit=1)
        second = executor.submit(endpoint, limit=2)
        assert catalog.entered.wait(timeout=2)
        assert catalog.second_call.wait(timeout=2)
        catalog.release.set()
        assert first.result(timeout=3)["runs"] == []
        assert second.result(timeout=3)["runs"] == []

    assert catalog.calls == 2


def test_qlib_list_coalesces_fail_closed_error_and_revalidates(monkeypatch, tmp_path):
    from fastapi import HTTPException

    catalog = _BlockingQlibCatalog(fail=True)
    endpoint = _qlib_list_endpoint_with_catalog(monkeypatch, tmp_path, catalog)

    with ThreadPoolExecutor(max_workers=2) as executor:
        reads = [executor.submit(endpoint, limit=20)]
        assert catalog.entered.wait(timeout=2)
        reads.append(executor.submit(endpoint, limit=20))
        follower_joined = catalog.follower_waiting.wait(timeout=2)
        catalog.release.set()
        failures = []
        for read in reads:
            with pytest.raises(HTTPException) as raised:
                read.result(timeout=3)
            failures.append((raised.value.status_code, raised.value.detail))

    assert follower_joined
    assert catalog.calls == 1
    assert failures == [
        (503, "fixture_archive_unavailable"),
        (503, "fixture_archive_unavailable"),
    ]

    catalog.fail = False
    assert endpoint(limit=20)["runs"] == []
    assert catalog.calls == 2


def test_qlib_list_rejects_selector_before_inflight_join(monkeypatch, tmp_path):
    from fastapi import HTTPException

    catalog = _BlockingQlibCatalog()
    endpoint = _qlib_list_endpoint_with_catalog(monkeypatch, tmp_path, catalog)

    with pytest.raises(HTTPException) as raised:
        endpoint(limit=20, manifest="forbidden")

    assert raised.value.status_code == 400
    assert raised.value.detail == "readonly_archive_selector_is_server_owned"
    assert catalog.calls == 0

    with pytest.raises(HTTPException) as raised:
        endpoint(limit=20, artifacts_root=str(tmp_path))
    assert raised.value.status_code == 400
    assert catalog.calls == 0


def test_qlib_list_inflight_reads_are_isolated_per_app(monkeypatch, tmp_path):
    catalog = _BlockingQlibCatalog()
    first_endpoint = _qlib_list_endpoint_with_catalog(monkeypatch, tmp_path, catalog)
    second_endpoint = _qlib_list_endpoint_with_catalog(monkeypatch, tmp_path, catalog)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(first_endpoint, limit=20)
        assert catalog.entered.wait(timeout=2)
        second = executor.submit(second_endpoint, limit=20)
        assert catalog.second_call.wait(timeout=2)
        catalog.release.set()
        assert first.result(timeout=3)["runs"] == []
        assert second.result(timeout=3)["runs"] == []

    assert catalog.calls == 2


def test_qlib_list_authentication_precedes_inflight_join(monkeypatch, tmp_path):
    from backend.app.api import app_factory

    catalog = _BlockingQlibCatalog()
    monkeypatch.setattr(
        app_factory,
        "settings",
        replace(
            app_factory.settings,
            backend_evidence_profile="research_readonly",
            web_api_key="fixture-secret",
        ),
    )
    monkeypatch.setattr(app_factory, "QLIB_ARTIFACTS_ROOT", tmp_path / "missing")
    monkeypatch.setattr(app_factory, "build_m1_research_archive_catalog", lambda **_: catalog)
    client = TestClient(app_factory.create_app())

    denied = client.get("/api/integrations/qlib/runs")
    assert denied.status_code == 403
    assert catalog.calls == 0

    catalog.release.set()
    allowed = client.get(
        "/api/integrations/qlib/runs",
        headers={"X-API-Key": "fixture-secret"},
    )
    assert allowed.status_code == 200
    assert catalog.calls == 1


def test_qlib_detail_reuses_single_seal_verification(monkeypatch, tmp_path):
    from backend.app.api import app_factory
    from integrations.qlib_adapter import research_pipeline
    from integrations.qlib_adapter.schemas import write_json

    monkeypatch.setattr(app_factory, "QLIB_ARTIFACTS_ROOT", tmp_path)
    run_root = tmp_path / "detail-once"
    write_json(run_root / "pipeline_result.json", {"run_id": run_root.name, "status": "completed"})
    research_pipeline.seal_run(run_root)
    calls: list[str] = []
    original = research_pipeline.read_sealed_evidence

    def counted(path: Path, **kwargs):
        calls.append(path.name)
        return original(path, **kwargs)

    monkeypatch.setattr(research_pipeline, "read_sealed_evidence", counted)
    response = _client(monkeypatch).get("/api/integrations/qlib/runs/detail-once")

    assert response.status_code == 200
    assert response.json()["integrity_status"] == "passed"
    assert calls == ["detail-once"]


def test_qlib_detail_route_offloads_blocking_archive_reads(monkeypatch):
    from backend.app.api import app_factory

    app = app_factory.create_app()
    candidate_routes = list(app.routes)
    for outer_route in app.routes:
        nested_app = getattr(outer_route, "app", None)
        if hasattr(nested_app, "routes"):
            candidate_routes.extend(nested_app.routes)
        included_router = getattr(outer_route, "original_router", None)
        if hasattr(included_router, "routes"):
            candidate_routes.extend(included_router.routes)
    endpoint = next(
        route.endpoint
        for route in candidate_routes
        if getattr(route, "path", "") == "/api/integrations/qlib/runs/{run_id}"
    )

    assert not inspect.iscoroutinefunction(endpoint)


def test_qlib_summary_only_still_validates_decision_identity_and_seal_version(tmp_path):
    from integrations.qlib_adapter.research_pipeline import read_sealed_evidence, seal_run
    from integrations.qlib_adapter.schemas import write_json

    run_root = tmp_path / "summary-safe"
    write_json(run_root / "pipeline_result.json", {"run_id": run_root.name, "status": "completed"})
    decisions = run_root / "research_decisions.jsonl"
    decisions.write_text(
        json.dumps({"qlib_run_id": "wrong-run", "decision": "hold"}) + "\n",
        encoding="utf-8",
    )
    seal_run(run_root)

    assert read_sealed_evidence(run_root, summary_only=True)["integrity_status"] == "blocked"

    decisions.write_text(
        json.dumps({"qlib_run_id": run_root.name, "decision": "hold"}) + "\n",
        encoding="utf-8",
    )
    seal_path = run_root / "run_seal.json"
    seal = json.loads(seal_path.read_text(encoding="utf-8"))
    import hashlib

    seal["files"]["research_decisions.jsonl"] = hashlib.sha256(decisions.read_bytes()).hexdigest()
    seal["schema_version"] = "qlib_run_seal_wrong"
    seal_path.write_text(json.dumps(seal), encoding="utf-8")

    wrong_version = read_sealed_evidence(run_root, summary_only=True)
    assert wrong_version["integrity_status"] == "blocked"
    assert wrong_version["blockers"] == ["seal_schema_mismatch"]


def test_qlib_reader_reuses_same_request_manifest_hashes_without_weakening_checks(
    tmp_path,
    monkeypatch,
):
    import hashlib
    from integrations.qlib_adapter import research_pipeline
    from integrations.qlib_adapter.schemas import write_json

    run_root = tmp_path / "manifest-verified"
    write_json(
        run_root / "pipeline_result.json",
        {"run_id": run_root.name, "status": "completed"},
    )
    research_pipeline.seal_run(run_root)
    verified_files = {
        path.relative_to(run_root).as_posix(): {
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "bytes": path.stat().st_size,
        }
        for path in run_root.rglob("*")
        if path.is_file()
    }

    original_hash = research_pipeline._hash_file

    def only_seal_may_be_rehashed(path: Path) -> str:
        if path.name != "run_seal.json":
            raise AssertionError(f"same-request manifest hash was ignored for {path.name}")
        return original_hash(path)

    monkeypatch.setattr(research_pipeline, "_hash_file", only_seal_may_be_rehashed)
    result = research_pipeline.read_sealed_evidence(
        run_root,
        summary_only=True,
        verified_manifest_files=verified_files,
    )

    assert result["integrity_status"] == "passed"
    assert result["validation_scope"] == "manifest_hashes_and_summary_identity"


def test_qlib_reader_rejects_manifest_hash_conflict_without_fallback(tmp_path):
    import hashlib
    from integrations.qlib_adapter import research_pipeline
    from integrations.qlib_adapter.schemas import write_json

    run_root = tmp_path / "manifest-conflict"
    write_json(
        run_root / "pipeline_result.json",
        {"run_id": run_root.name, "status": "completed"},
    )
    research_pipeline.seal_run(run_root)
    verified_files = {
        path.relative_to(run_root).as_posix(): {
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "bytes": path.stat().st_size,
        }
        for path in run_root.rglob("*")
        if path.is_file()
    }
    verified_files["pipeline_result.json"]["sha256"] = "0" * 64

    result = research_pipeline.read_sealed_evidence(
        run_root,
        summary_only=True,
        verified_manifest_files=verified_files,
    )

    assert result["integrity_status"] == "blocked"
    assert result["blockers"] == [
        "manifest_and_seal_hash_mismatch:pipeline_result.json"
    ]


def test_qlib_list_surfaces_sealed_but_unreadable_summary_artifact(monkeypatch, tmp_path):
    from backend.app.api import app_factory
    from integrations.qlib_adapter.research_pipeline import seal_run

    monkeypatch.setattr(app_factory, "QLIB_ARTIFACTS_ROOT", tmp_path)
    run_root = tmp_path / "unreadable-summary"
    run_root.mkdir()
    (run_root / "pipeline_result.json").write_text("{", encoding="utf-8")
    seal_run(run_root)

    response = _client(monkeypatch).get("/api/integrations/qlib/runs")

    assert response.status_code == 200
    summary = response.json()["runs"][0]
    assert summary["integrity_status"] == "blocked"
    assert summary["blockers"] == ["summary_artifact_unreadable:pipeline_result.json"]
    assert summary["execution_permission"] is False

    detail = _client(monkeypatch).get("/api/integrations/qlib/runs/unreadable-summary").json()
    assert detail["integrity_status"] == "blocked"
    assert detail["blockers"] == ["summary_artifact_unreadable:pipeline_result.json"]
    assert detail["execution_permission"] is False
    assert "pipeline" not in detail


def test_qlib_reader_blocks_non_object_seal_files(tmp_path):
    from integrations.qlib_adapter.research_pipeline import read_sealed_evidence, seal_run
    from integrations.qlib_adapter.schemas import write_json

    run_root = tmp_path / "invalid-seal-files"
    write_json(run_root / "pipeline_result.json", {"run_id": run_root.name, "status": "completed"})
    seal_run(run_root)
    seal_path = run_root / "run_seal.json"
    seal = json.loads(seal_path.read_text(encoding="utf-8"))
    seal["files"] = "pipeline_result.json"
    seal_path.write_text(json.dumps(seal), encoding="utf-8")

    result = read_sealed_evidence(run_root)

    assert result["integrity_status"] == "blocked"
    assert result["blockers"] == ["seal_files_invalid"]
    assert result["execution_permission"] is False
