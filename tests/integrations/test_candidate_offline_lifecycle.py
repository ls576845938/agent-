"""Real default composition + real HTTP routes, complete sealed synthetic inputs."""
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import time
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from tests.contracts.test_registered_candidate_execution import prepared, cases, ROOT
from quant_shared.strategy_delivery.models import digest
from backend.app.services.candidate_delivery_bootstrap import build_delivery_service, build_offline_service
from backend.app.services.research_archive_discovery import ResearchArchiveCatalog
from backend.app.api.candidate_delivery import build_candidate_delivery_router
from backend.app.api.candidate_offline import build_candidate_offline_router
from backend.app.core.backend_access_policy import evaluate_backend_access

KEY = "synthetic-local-management-only"


def default_fixture(tmp_path, case, *, enabled=True, profile="candidate_management"):
    old, oldrow, kw, _ = prepared(tmp_path, case)
    management = tmp_path / "new-management"; management.mkdir()
    (management / "accounts.json").write_bytes(old.accounts.path.read_bytes())
    artifact = json.loads((tmp_path / "delivery.json").read_text())
    authored = artifact["candidate"]["delivery_contract"]
    frozen = {"frozen_policy": authored["frozen_policy"], "calibration": authored["contracts"]["calibration"],
              "model_dependencies": authored["model_dependencies"],
              "feature_dependencies": authored["feature_implementation"]["dependencies"],
              "settlement_evidence": authored["settlement_evidence"]}
    def write(name, value):
        path = tmp_path / name
        raw = json.dumps(value, default=str, ensure_ascii=False).encode()
        path.write_bytes(raw)
        return {"path": name, "sha256": hashlib.sha256(raw).hexdigest()}
    frozen_ref = write("frozen.json", frozen)
    input_row = {"input_revision_id": "synthetic-input-v1", "evidence_kind": "synthetic_fixture", "input_head": old.head,
        "bars": write("bars.json", json.loads(kw["bars"].to_json(orient="records", date_format="iso", double_precision=15))),
        "observations": write("observations.json", [asdict(o) for o in kw["observations"]]),
        "manifest": write("manifest.json", kw["market_manifest"])}
    input_row["content_digest"] = digest(input_row)
    catalog = {"schema_version": "candidate_offline_catalog_v1", "repository_owner": digest({"repository": str(ROOT.resolve())}),
        "revision": "fixture-v1", "factory_root": "factory", "qlib_root": ".",
        "sources": [{"source_revision_id": "synthetic-source-v1", "source": oldrow["source"],
                     "frozen_evidence": frozen_ref["path"], "frozen_evidence_sha256": frozen_ref["sha256"]}],
        "inputs": [input_row]}
    ref = write("offline-catalog.json", catalog)
    settings = SimpleNamespace(repo_root=ROOT, candidate_delivery_root=str(management),
        btc_demo_account_facts_approval_registry="", candidate_delivery_operator="operator", web_api_key=KEY,
        candidate_offline_catalog=str(tmp_path / ref["path"]), candidate_offline_catalog_sha256=ref["sha256"],
        candidate_offline_catalog_revision="fixture-v1", candidate_offline_enabled=enabled, backend_evidence_profile=profile)
    before = sorted(str(p) for p in tmp_path.rglob("*"))
    delivery = build_delivery_service(settings, archive=ResearchArchiveCatalog(repo_root=ROOT), qlib_root=tmp_path, head=old.head)
    offline = build_offline_service(settings, delivery)
    assert before == sorted(str(p) for p in tmp_path.rglob("*"))
    app = FastAPI()
    @app.middleware("http")
    async def access(request: Request, call_next):
        decision = evaluate_backend_access(profile=profile, method=request.method, path=request.url.path)
        if not decision.allowed: return JSONResponse({"detail": decision.reason}, status_code=403)
        return await call_next(request)
    app.include_router(build_candidate_delivery_router(service=delivery, enabled=profile == "candidate_management",
        operator="operator", management_key=KEY), prefix="/api")
    app.include_router(build_candidate_offline_router(offline), prefix="/api")
    return app, delivery, offline, input_row, kw, settings


def publish_register(client, source):
    def post(path, body, key):
        response = client.post("/api/" + path, json=body, headers={"Idempotency-Key": key})
        assert response.is_success, response.text
        return response.json()
    publication = post("candidate-offline/publish", {"source_revision_id": "synthetic-source-v1", "expected_revision": 0}, "publish1")
    assert publication == post("candidate-offline/publish", {"source_revision_id": "synthetic-source-v1", "expected_revision": 0}, "publish1")
    assert client.post("/api/candidate-offline/publish", json={"source_revision_id": "synthetic-source-v1", "expected_revision": 0},
                       headers={"Idempotency-Key": "conflicting-publication"}).status_code == 409
    row = post("strategy-delivery/packages", {"source": source, "target": "offline"}, "create1")
    for action, extra in (("bind", {"account_ref": "fixture-account"}), ("review", {"decision": "approve", "reason": "synthetic fixture acceptance"}), ("register", {})):
        row = post("strategy-delivery/packages/" + row["id"] + "/" + action, {"expected_revision": row["revision"], **extra}, action + "1")
    assert row["content_digest"] == publication["package_digest"]
    return row


def wait_terminal(client, identity, timeout=600):
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        value = client.get("/api/candidate-offline/jobs/" + identity).json()
        if value["status"] in {"complete", "blocked", "interrupted", "stopped"}: return value
        time.sleep(.5)
    import sys, traceback, threading
    stacks = {t.name: ''.join(traceback.format_stack(sys._current_frames()[t.ident]))
              for t in threading.enumerate() if t.name.startswith("candidate-offline-") and t.ident in sys._current_frames()}
    pytest.fail("offline worker timeout: " + json.dumps({"status": value, "stacks": stacks}))


def assert_sealed_identity(value, row, input_row, delivery, offline):
    expected = {"schema_version": "candidate_offline_job_identity_v1", "job_id": value["job"]["id"],
        "registration_id": row["id"], "content_digest": row["content_digest"],
        "binding_digest": row["binding_digest"], "account_ref": row["binding"]["account_ref"],
        "account_identity_hash": row["binding"]["identity_hash"],
        "runtime_contract_digest": row["binding"]["offline_runtime"]["contract_digest"],
        "state_directory_sha256": row["binding"]["offline_runtime"]["state_directory_sha256"],
        "input_revision_id": input_row["input_revision_id"], "input_digest": input_row["content_digest"],
        "input_head": input_row["input_head"], "input_evidence_kind": input_row["evidence_kind"],
        "source_head": row["package"]["source_head"], "execution_head": delivery.head,
        "catalog_sha256": offline.inputs.checksum}
    for record in [value["job"], value["result"], *value["decisions"]]:
        if record is None: continue
        assert record["job_identity"] == expected
        assert record["job_identity_digest"] == digest(expected)
        assert all(record[k] == v for k,v in expected.items() if k != "schema_version")


@pytest.mark.parametrize("number", [0, 1])
def test_default_bootstrap_publish_http_start_result_and_idempotency(tmp_path, cases, number):
    app, delivery, offline, input_row, kw, settings = default_fixture(tmp_path, cases[number])
    with TestClient(app, headers={"X-API-Key": KEY}) as client:
        row = publish_register(client, cases[number][0]["source"])
        body = {"registration_id": row["id"], "content_digest": row["content_digest"], "expected_revision": row["revision"],
                "input_revision_id": input_row["input_revision_id"], "input_digest": input_row["content_digest"]}
        first = client.post("/api/candidate-offline/jobs", json=body, headers={"Idempotency-Key": "start1"})
        assert first.status_code == 202, first.text
        identity = first.json()["job_id"]
        assert client.post("/api/candidate-offline/jobs", json={**body,"input_digest":"0"*64},
                           headers={"Idempotency-Key": "start1"}).status_code == 409
        assert first.json() == client.post("/api/candidate-offline/jobs", json=body, headers={"Idempotency-Key": "start1"}).json()
        terminal = wait_terminal(client, identity)
        assert terminal["status"] == "complete", terminal
        result = client.get("/api/candidate-offline/jobs/" + identity + "/result").json()
        assert_sealed_identity(result, row, input_row, delivery, offline)
        assert result["result"]["fill_count"] == 2 and result["result"]["position_contracts"] == "0"
        assert result["result"]["ledger"]["reconciled"] is True
        assert result["result"]["input_evidence_kind"] == "synthetic_fixture"
        assert not any(result["permissions"].values())
        assert client.post("/api/candidate-offline/jobs", json=body, headers={"Idempotency-Key": "new-job-attempt"}).status_code == 409
        restarted = build_offline_service(settings, build_delivery_service(settings,
            archive=ResearchArchiveCatalog(repo_root=ROOT), qlib_root=tmp_path, head=delivery.head))
        assert restarted.result(identity)["result"] == result["result"]
        assert not restarted._threads
        from tests.cli.test_candidate_offline_cli import local_backend, cli
        with local_backend(app) as url:
            code, cached_publication = cli(url, KEY, "publish", "synthetic-source-v1", "--expected-revision", "0", "--request-key", "publish1")
            assert code == 0 and cached_publication["package_digest"] == row["content_digest"]
            code, repeated = cli(url, KEY, "start", row["id"], "--content-digest", row["content_digest"],
                "--expected-revision", str(row["revision"]), "--input-revision-id", input_row["input_revision_id"],
                "--input-digest", input_row["content_digest"], "--request-key", "start1")
            assert code == 0 and repeated == first.json()
            code, linked = cli(url, KEY, "result", identity)
            assert code == 0 and linked["result"] == result["result"]


def test_stop_at_committed_boundary_resume_same_job_across_service_restart(tmp_path,cases,monkeypatch):
    import threading
    from quant_crypto.application.qlib_offline_replay import QlibFixtureOfflineReplay
    app, delivery, offline, input_row, kw, settings = default_fixture(tmp_path, cases[0])
    reached, release = threading.Event(), threading.Event()
    original = QlibFixtureOfflineReplay.execute_registered
    def boundary(runtime, index):
        result = original(runtime, index)
        if index == 0:
            reached.set()
            assert release.wait(600)
        return result
    monkeypatch.setattr(QlibFixtureOfflineReplay, "execute_registered", boundary)
    with TestClient(app, headers={"X-API-Key": KEY}) as client:
        row = publish_register(client, cases[0][0]["source"])
        body = {"registration_id": row["id"], "content_digest": row["content_digest"], "expected_revision": row["revision"],
                "input_revision_id": input_row["input_revision_id"], "input_digest": input_row["content_digest"]}
        identity = client.post("/api/candidate-offline/jobs", json=body, headers={"Idempotency-Key": "start1"}).json()["job_id"]
        try:
            assert reached.wait(600)
            current = client.get("/api/candidate-offline/jobs/" + identity).json()
            stop = client.post("/api/candidate-offline/jobs/" + identity + "/stop", json={"expected_revision": current["revision"]},
                               headers={"Idempotency-Key": "stop1"})
            assert stop.status_code == 200, stop.text
        finally: release.set()
        terminal = wait_terminal(client, identity)
        assert terminal["status"] == "stopped" and terminal["cursor"] == 1
        for thread in offline._threads.values(): thread.join(60)
        before = offline.result(identity)["result"]
        assert before["fill_count"] == 1 and before["position_contracts"] != "0"
        resumed = build_offline_service(settings, build_delivery_service(settings,
            archive=ResearchArchiveCatalog(repo_root=ROOT), qlib_root=tmp_path, head=delivery.head))
        assert not resumed._threads and resumed.status(identity)["status"] == "stopped"
        from tests.cli.test_candidate_offline_cli import local_backend, cli
        resume_app = FastAPI(); resume_app.include_router(build_candidate_offline_router(resumed), prefix="/api")
        with local_backend(resume_app) as url:
            code, receipt = cli(url, KEY, "resume", identity, "--expected-revision", str(terminal["revision"]), "--request-key", "resume1")
            assert code == 0 and receipt["job_id"] == identity
            for thread in resumed._threads.values(): thread.join(600)
        final = resumed.result(identity)
        assert_sealed_identity(final, row, input_row, delivery, resumed)
        assert final["job"]["job_identity_digest"] == terminal["job_identity_digest"] == before["job_identity_digest"]
        assert final["job"]["status"] == "complete", final["job"]
        assert final["result"]["fill_count"] == 2 and final["result"]["orders"][0] == before["orders"][0]
        assert final["result"]["ledger"]["reconciled"] is True


def test_worker_crash_after_authority_commit_before_projection_resumes_without_duplicate(tmp_path,cases,monkeypatch):
    app, delivery, offline, input_row, kw, settings = default_fixture(tmp_path, cases[0])
    original = offline._update
    injected = []
    def fail_projection(*args, **changes):
        if changes.get("cursor") == 1 and not injected:
            injected.append(True)
            raise RuntimeError("test_after_authority_before_projection")
        return original(*args, **changes)
    monkeypatch.setattr(offline, "_update", fail_projection)
    with TestClient(app, headers={"X-API-Key": KEY}) as client:
        row = publish_register(client, cases[0][0]["source"])
        body = {"registration_id": row["id"], "content_digest": row["content_digest"], "expected_revision": row["revision"],
                "input_revision_id": input_row["input_revision_id"], "input_digest": input_row["content_digest"]}
        identity = client.post("/api/candidate-offline/jobs", json=body, headers={"Idempotency-Key": "start1"}).json()["job_id"]
        interrupted = wait_terminal(client, identity)
        assert interrupted["status"] == "interrupted" and interrupted["cursor"] == 0
        for thread in offline._threads.values(): thread.join(60)
        venue = json.loads((kw["state_dir"] / "offline_venue.json").read_text())
        original_fill = venue["fills"][0]
        assert len(venue["fills"]) == 1
        assert client.post("/api/candidate-offline/jobs", json=body, headers={"Idempotency-Key": "attempt-new-job"}).status_code == 409
        restarted = build_offline_service(settings, build_delivery_service(settings,
            archive=ResearchArchiveCatalog(repo_root=ROOT), qlib_root=tmp_path, head=delivery.head))
        assert not restarted._threads
        restarted.command(identity, "resume", expected_revision=interrupted["revision"], key="resume-crash", credential=KEY)
        for thread in restarted._threads.values(): thread.join(600)
        result = restarted.result(identity)
        assert_sealed_identity(result, row, input_row, delivery, restarted)
        assert result["job"]["job_identity_digest"] == interrupted["job_identity_digest"]
        assert result["job"]["status"] == "complete", result["job"]
        assert result["result"]["fill_count"] == 2 and result["result"]["fills"][0] == original_fill
        assert len(result["decisions"]) == 2
        assert len(restarted.result(identity, before=2)["decisions"]) == 1
        assert_sealed_identity(restarted.result(identity, before=2), row, input_row, delivery, restarted)
