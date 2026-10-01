"""Capability and input boundaries through default composition, no economic writes."""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.app.services.candidate_delivery_bootstrap import build_delivery_service, build_offline_service
from backend.app.services.research_archive_discovery import ResearchArchiveCatalog
from backend.app.api.candidate_offline import build_candidate_offline_router
from backend.app.core.backend_access_policy import evaluate_backend_access
from quant_shared.strategy_delivery.models import digest, DeliveryError

ROOT = Path(__file__).resolve().parents[2]


def empty_service(tmp_path, profile="candidate_management", enabled=False):
    catalog = {"schema_version": "candidate_offline_catalog_v1", "repository_owner": digest({"repository": str(ROOT)}),
               "revision": "empty-v1", "factory_root": "factory", "qlib_root": "qlib", "sources": [], "inputs": []}
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(catalog), encoding="utf-8")
    import subprocess
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    settings = SimpleNamespace(repo_root=ROOT, candidate_delivery_root=str(tmp_path / "management"),
        candidate_offline_catalog=str(path), candidate_offline_catalog_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        candidate_offline_catalog_revision="empty-v1", btc_demo_account_facts_approval_registry="",
        candidate_offline_enabled=enabled, backend_evidence_profile=profile, candidate_delivery_operator="operator", web_api_key="test-only")
    delivery = build_delivery_service(settings, archive=ResearchArchiveCatalog(repo_root=ROOT), qlib_root=tmp_path / "qlib", head=head)
    return settings, build_offline_service(settings, delivery)


@pytest.mark.parametrize("profile,enabled", [("candidate_management", False), ("research_readonly", True), ("demo_quasi_live", True)])
def test_independent_capability_blocks_all_writes_even_with_key(tmp_path, profile, enabled):
    settings, service = empty_service(tmp_path, profile, enabled)
    app = FastAPI(); app.include_router(build_candidate_offline_router(service), prefix="/api")
    client = TestClient(app, headers={"X-API-Key": "test-only", "Idempotency-Key": "same-key"})
    before = list(tmp_path.rglob("*"))
    assert client.get("/api/candidate-offline/capabilities").json()["offline_commands_enabled"] is False
    for path in ("publish", "jobs", "jobs/coff_" + "a" * 32 + "/stop", "jobs/coff_" + "a" * 32 + "/resume"):
        assert client.post("/api/candidate-offline/" + path, json={}).status_code == 423
    assert client.get("/api/candidate-offline/jobs").json()["jobs"] == []
    assert before == list(tmp_path.rglob("*"))


def test_local_auth_opaque_fields_no_get_side_effects(tmp_path):
    settings, service = empty_service(tmp_path, enabled=True)
    app = FastAPI(); app.include_router(build_candidate_offline_router(service), prefix="/api")
    client = TestClient(app)
    before = list(tmp_path.rglob("*"))
    assert client.get("/api/candidate-offline/jobs").status_code == 403
    assert client.get("/api/candidate-offline/capabilities", headers={"Host": "evil.example"}).status_code == 403
    assert client.get("/api/candidate-offline/capabilities", headers={"Origin": "https://evil.example"}).status_code == 403
    assert client.get("/api/candidate-offline/capabilities?mode=live").status_code == 422
    assert client.get("/api/candidate-offline/jobs/coff_" + "a" * 32 + "/result?before=1&before=2").status_code == 422
    for name in ("bars", "observations", "path", "state_dir", "manifest", "verified", "truth_kind", "mode", "recovery_only"):
        response = client.post("/api/candidate-offline/jobs", headers={"X-API-Key": "test-only", "Idempotency-Key": "opaque"},
            json={"registration_id": "delivery_" + "a" * 32, "content_digest": "a" * 64, "expected_revision": 4,
                  "input_revision_id": "input-1", "input_digest": "b" * 64, name: "not-allowed"})
        assert response.status_code == 422
    assert before == list(tmp_path.rglob("*"))
    for path in ("../escape", "C:/escape", "a/../../escape", "a\\escape"):
        with pytest.raises(DeliveryError): service.inputs.path_for(path)
    Path(settings.candidate_offline_catalog).write_text("{}")
    with pytest.raises(DeliveryError, match="hash"): service.inputs.catalog()


def test_precise_route_allowlist_readonly_never_writes():
    for action in ("stop", "resume"):
        path = "/api/candidate-offline/jobs/coff_" + "a" * 32 + "/" + action
        assert not evaluate_backend_access(profile="research_readonly", method="POST", path=path).allowed
        assert evaluate_backend_access(profile="candidate_management", method="POST", path=path).allowed
    assert not evaluate_backend_access(profile="candidate_management", method="POST", path="/api/candidate-offline/run-anything").allowed
    assert evaluate_backend_access(profile="research_readonly", method="GET", path="/api/candidate-offline/jobs/coff_" + "a" * 32 + "/result").allowed


def test_app_factory_installs_real_default_offline_router(monkeypatch, tmp_path):
    # Full app composition must not instantiate a Demo/IBKR controller.
    from dataclasses import replace
    from backend.app.api import app_factory
    settings, _ = empty_service(tmp_path)
    monkeypatch.setattr(app_factory, "settings", replace(app_factory.settings,
        **{k:v for k,v in vars(settings).items() if k != "repo_root"}))
    app = app_factory.create_app()
    client = TestClient(app)
    value = client.get("/api/candidate-offline/capabilities")
    assert value.status_code == 200, value.text
    assert value.json()["offline_commands_enabled"] is False


def test_frontend_components_and_selectors_without_worktree_server():
    import subprocess
    script = "const e=require('esbuild');const r=e.buildSync({entryPoints:['e2e/candidate-offline.spec.ts'],bundle:true,platform:'node',format:'cjs',write:false,external:['react','react-dom/server','react-router-dom']});eval(r.outputFiles[0].text);"
    result = subprocess.run(["node", "-e", script], cwd=ROOT / "frontend", capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr


def test_store_integrity_owner_reservation_and_idempotency_are_fail_closed(tmp_path):
    from backend.app.services.candidate_offline_store import OfflineStore
    store = OfflineStore(tmp_path / "orchestration", "owner-a")
    with store.transaction() as conn:
        store.reserve(conn, "same-account-state", "job-a")
        store.cache(conn, "same-key", "request-a", {"job": "job-a"})
        store.put(conn, "job", "job-a", {"id": "job-a"})
    with pytest.raises(DeliveryError, match="idempotency_conflict"):
        with store.transaction() as conn: store.cached(conn, "same-key", "request-b")
    with pytest.raises(DeliveryError, match="already_reserved"):
        with store.transaction() as conn: store.reserve(conn, "same-account-state", "job-b")
    with pytest.raises(DeliveryError, match="owner_mismatch"): OfflineStore(store.root, "owner-b").read("job")
    with store.transaction() as conn: conn.execute("UPDATE records SET payload='{}' WHERE kind='job'")
    with pytest.raises(DeliveryError, match="integrity_invalid"): store.read("job")


def test_explicit_input_hash_and_timezone_fail_before_runtime(tmp_path):
    settings, service = empty_service(tmp_path, enabled=True)
    path = Path(settings.candidate_offline_catalog)
    catalog = json.loads(path.read_text())
    def write(name, value):
        p = tmp_path / name; p.write_text(json.dumps(value))
        return {"path": name, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
    row = {"input_revision_id": "naive-fixture", "input_head": service.delivery.head, "evidence_kind": "synthetic_fixture",
        "manifest": write("m.json", {}), "observations": write("o.json", []),
        "bars": write("b.json", [{"event_time": "2020-01-01", "available_time": "2020-01-01", "decision_time": "2020-01-01"}])}
    row["content_digest"] = digest(row); catalog["inputs"] = [row]
    path.write_text(json.dumps(catalog)); service.inputs.checksum = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(DeliveryError, match="timezone_missing"): service.inputs.load(row["input_revision_id"], row["content_digest"])
    (tmp_path / "b.json").write_text("[]")
    with pytest.raises(DeliveryError, match="hash_mismatch"): service.inputs.load(row["input_revision_id"], row["content_digest"])
    assert not service.store.path.exists()


def test_v2_input_routes_unpriced_funding_and_bound_dataset_contract(tmp_path):
    settings,service=empty_service(tmp_path,enabled=True)
    path=Path(settings.candidate_offline_catalog);catalog=json.loads(path.read_text())
    def write(name,value):
        p=tmp_path/name;p.write_text(json.dumps(value),encoding="utf-8")
        return {"path":name,"sha256":hashlib.sha256(p.read_bytes()).hexdigest()}
    instrument={"venue":"OKX","instrument_id":"BTC-USDT-SWAP","contract_value_btc":"0.01",
        "lot_size_contracts":"0.01","minimum_size_contracts":"0.01","maximum_market_size_contracts":"35000",
        "source_record_id":"BTC-USDT-SWAP","source_version":"bound-v1",
        "source_sha256":"1a3be93ab5be07d8d0625ff37c077a461cba075876e44e8517266c9a28e336e8",
        "observed_at":"2026-07-30T11:45:48Z","available_time":"2026-07-30T11:45:48Z",
        "historical_availability_assumption":"frozen_engineering_contract_assumption_not_june_pit_proof"}
    contract_ref=write("dataset-contract.json",{"schema_version":"btc_real_candidate_dataset_contract_v1",
        "instrument_contract":instrument})
    history=[{"event_time":"2026-06-16T00:00:00Z","available_time":"2026-06-16T00:00:01Z","rate":-0.0000130999107801,
        "source_record_id":"funding-prior","source_dataset":"okx-public-funding","source_version":"bound-v1",
        "source_sha256":"b"*64}]
    history_ref=write("funding-rate-history.json",history)
    manifest={"schema_version":"registered_offline_market_v2","dataset_contract_sha256":contract_ref["sha256"],
        "funding_rate_history_sha256":history_ref["sha256"],"instrument_contract":instrument}
    fact={"event_id":"funding-1","event_time_utc":"2026-06-16T08:00:00Z","rate":.0001,
        "source_record_id":"funding-row-1","source_dataset":"okx-public-funding","source_version":"bound-v1",
        "source_sha256":"a"*64,"valuation_policy":"minute_close_sampled_valuation_not_exchange_actual_settlement"}
    observation={"event_time_utc":"2026-06-16T07:00:00Z","close_price":60000,"mark_price":60001,
        "index_price":60000,"delayed_open_price":60010,"funding_rate":-0.0000130999107801,"funding_cashflow_usdt":0,
        "blockers":[],"end_of_window":False,"maintenance_facts":[{"observed_at_utc":"2026-06-16T08:00:00Z",
            "mark_price":60001,"index_price":60000}],"funding_settlements":[fact]}
    bars=[{"event_time":"2026-06-16T07:00:00Z","available_time":"2026-06-16T08:00:00Z",
        "decision_time":"2026-06-16T08:00:00Z"}]
    row={"schema_version":"candidate_offline_input_v2","input_revision_id":"real-v2",
        "input_head":service.delivery.head,"evidence_kind":"verified_historical_observations",
        "manifest":write("market-v2.json",manifest),"bars":write("bars-v2.json",bars),
        "observations":write("observations-v2.json",[observation]),"dataset_contract":contract_ref,
        "funding_rate_history":history_ref}
    row["content_digest"]=digest(row);catalog["inputs"]=[row]
    path.write_text(json.dumps(catalog),encoding="utf-8");service.inputs.checksum=hashlib.sha256(path.read_bytes()).hexdigest()
    _,loaded=service.inputs.load("real-v2",row["content_digest"])
    assert loaded["observations"][0].funding_cashflow_usdt==0
    assert loaded["observations"][0].funding_settlements[0].event_id=="funding-1"
    base_row=json.loads(json.dumps(row))
    for extra in (dict(history[0]),{**history[0],"rate":.0002,"source_record_id":"conflicting-source"}):
        bad_history_ref=write("funding-rate-history-bad.json",history+[extra])
        bad_manifest={**manifest,"funding_rate_history_sha256":bad_history_ref["sha256"]}
        bad_row={**base_row,"funding_rate_history":bad_history_ref,"manifest":write("market-v2-bad.json",bad_manifest)}
        bad_row["content_digest"]=digest({k:v for k,v in bad_row.items() if k!="content_digest"})
        catalog["inputs"]=[bad_row];path.write_text(json.dumps(catalog),encoding="utf-8")
        service.inputs.checksum=hashlib.sha256(path.read_bytes()).hexdigest()
        with pytest.raises(DeliveryError,match="funding_rate_history_invalid"):
            service.inputs.load("real-v2",bad_row["content_digest"])
    catalog["inputs"]=[base_row];path.write_text(json.dumps(catalog),encoding="utf-8")
    service.inputs.checksum=hashlib.sha256(path.read_bytes()).hexdigest();row=base_row
    bad=json.loads((tmp_path/"observations-v2.json").read_text());bad[0]["funding_settlements"][0]["amount_usdt"]=-1
    (tmp_path/"observations-v2.json").write_text(json.dumps(bad));row["observations"]["sha256"]=hashlib.sha256((tmp_path/"observations-v2.json").read_bytes()).hexdigest()
    row["content_digest"]=digest({k:v for k,v in row.items() if k!="content_digest"});catalog["inputs"]=[row]
    path.write_text(json.dumps(catalog));service.inputs.checksum=hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(DeliveryError,match="funding_facts_missing_or_extra"):service.inputs.load("real-v2",row["content_digest"])


def test_worker_rejects_management_only_adapter_before_creating_job_store(tmp_path, monkeypatch):
    _, service = empty_service(tmp_path, enabled=True)
    row = {
        "id": "delivery_" + "a" * 32, "revision": 4, "status": "registered", "target": "offline",
        "content_digest": "b" * 64, "package": {"adapter_id": "btc_frozen_qlib_offline_v1"},
    }
    monkeypatch.setattr(service.delivery, "get", lambda identity: row)
    body = {"registration_id": row["id"], "content_digest": row["content_digest"], "expected_revision": 4,
            "input_revision_id": "input-1", "input_digest": "c" * 64}
    with pytest.raises(DeliveryError, match="offline_runtime_adapter_unsupported"):
        service.start(body, key="unsupported-worker", credential="test-only")
    import sqlite3
    with sqlite3.connect(service.store.path) as conn:
        assert conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == []


def test_worker_preflight_keeps_supported_factory_adapter_available(tmp_path, monkeypatch):
    _, service = empty_service(tmp_path, enabled=True)
    row = {
        "id": "delivery_" + "a" * 32, "revision": 4, "status": "registered", "target": "offline",
        "content_digest": "b" * 64, "package": {"adapter_id": "factory_lgbm_ast_v1"},
    }
    monkeypatch.setattr(service.delivery, "get", lambda identity: row)
    body = {"registration_id": row["id"], "content_digest": row["content_digest"], "expected_revision": 4,
            "input_revision_id": "input-1", "input_digest": "c" * 64}
    assert service._start_row(body) == row
    capabilities = service.capabilities("test-only")
    assert capabilities["supported_adapter_ids"] == ["factory_lgbm_ast_v1"]
    assert capabilities["protection_execution_supported"] is True
    assert capabilities["protection_execution_scope"] == "new_current_code_runs_explicit_sampled_mark_only"
    assert capabilities["protection_execution_limitations"] == [
        "intrainterval_mark_path_not_inferred",
        "legacy_blocked_results_remain_authoritative",
    ]
    assert not service.store.path.exists()


IDENTITY_FIELDS = ("job_id", "registration_id", "content_digest", "binding_digest",
    "account_ref", "account_identity_hash", "runtime_contract_digest", "state_directory_sha256",
    "input_revision_id", "input_digest", "input_head", "input_evidence_kind",
    "source_head", "execution_head", "catalog_sha256")


def identity_records(tmp_path):
    """Small real-store projection test; not a substitute for runtime E2E."""
    _, service = empty_service(tmp_path, enabled=True)
    from quant_shared.strategy_delivery.offline_contract import job_id
    registration = "delivery_" + "a" * 32
    identity = {"schema_version": "candidate_offline_job_identity_v1", "job_id": job_id(registration),
        "registration_id": registration, "content_digest": "a" * 64, "binding_digest": "b" * 64,
        "account_ref": "fixture-account", "account_identity_hash": "c" * 64,
        "runtime_contract_digest": "d" * 64, "state_directory_sha256": "e" * 64,
        "input_revision_id": "fixture-input", "input_digest": "f" * 64, "input_head": "1" * 40,
        "input_evidence_kind": "synthetic_fixture", "source_head": "2" * 40,
        "execution_head": service.delivery.head, "catalog_sha256": service.inputs.checksum}
    bound = {k: identity[k] for k in IDENTITY_FIELDS}
    bound.update(job_identity=identity, job_identity_digest=digest(identity))
    job = {**bound, "schema_version": "candidate_offline_job_v2", "id": identity["job_id"],
           "status": "stopped", "cursor": 1, "revision": 3, "worker": None}
    result = {**bound, "schema_version": "candidate_offline_result_v2",
              "decision_receipt": {"event": "one"}, "decision_receipt_sha256": digest({"event": "one"})}
    result["sha256"] = digest(result)
    decision = {**bound, "schema_version": "candidate_offline_decision_v2",
                "cursor": 1, "receipt": {"event": "one"}, "receipt_sha256": digest({"event": "one"})}
    with service.store.transaction() as conn:
        for kind, value in (("job", job), ("result", result), ("decision", decision)):
            key = job["id"] + ":0000000001" if kind == "decision" else job["id"]
            service.store.put(conn, kind, key, value)
    return service, job, result, decision


def test_current_protection_capability_does_not_upgrade_legacy_blocked_result(tmp_path):
    service, job, _, _ = identity_records(tmp_path)
    job = {**job, "status": "blocked", "blocker": "registered_protection_execution_unsupported"}
    with service.store.transaction() as conn:
        service.store.put(conn, "job", job["id"], job)
    before = service.store.path.read_bytes()

    capabilities = service.capabilities("test-only")
    observed = service.status(job["id"])

    assert capabilities["protection_execution_supported"] is True
    assert observed["status"] == "blocked"
    assert observed["blocker"] == "registered_protection_execution_unsupported"
    assert service.store.path.read_bytes() == before


@pytest.mark.parametrize("kind", ["result", "decision"])
@pytest.mark.parametrize("field", IDENTITY_FIELDS)
def test_identity_rehashed_foreign_evidence_is_rejected(tmp_path, kind, field):
    from copy import deepcopy
    service, job, result, decision = identity_records(tmp_path)
    assert service.result(job["id"])["result_bound"] is True
    value = deepcopy(result if kind == "result" else decision)
    # Both duplicate projection fields and nested identity are changed consistently.
    # Rehashing the entire foreign evidence must not turn it into this job's evidence.
    wrong = ("coff_" + "0" * 32 if field == "job_id" else
             "verified_historical_observations" if field == "input_evidence_kind" else
             "0" * len(value[field]) if "head" in field or len(value[field]) == 64 else "other-ref")
    value[field] = value["job_identity"][field] = wrong
    value["job_identity_digest"] = digest(value["job_identity"])
    if kind == "result": value["sha256"] = digest({k:v for k,v in value.items() if k != "sha256"})
    with service.store.transaction() as conn:
        key = job["id"] + ":0000000001" if kind == "decision" else job["id"]
        service.store.put(conn, kind, key, value)
    before = service.store.path.read_bytes()
    with pytest.raises(DeliveryError, match="identity"): service.result(job["id"])
    assert before == service.store.path.read_bytes()  # GET never repairs/rebinds evidence.


@pytest.mark.parametrize("kind", ["job", "result", "decision"])
@pytest.mark.parametrize("missing", ["job_identity", "job_identity_digest", "account_ref"])
def test_identity_old_or_incomplete_records_fail_closed(tmp_path, kind, missing):
    from copy import deepcopy
    service, job, result, decision = identity_records(tmp_path)
    value = deepcopy({"job": job, "result": result, "decision": decision}[kind])
    value.pop(missing)
    if kind == "result": value["sha256"] = digest({k:v for k,v in value.items() if k != "sha256"})
    with service.store.transaction() as conn:
        service.store.put(conn, kind, job["id"] + ":0000000001" if kind == "decision" else job["id"], value)
    with pytest.raises(DeliveryError, match="identity"): service.result(job["id"])


def test_identity_cannot_be_mutated_by_worker_update(tmp_path):
    service, job, _, _ = identity_records(tmp_path)
    job["worker"] = {"generation": "generation", "instance": service._instance, "pid": 1}
    with service.store.transaction() as conn: service.store.put(conn, "job", job["id"], job)
    with pytest.raises(DeliveryError, match="identity"):
        service._update(job["id"], "generation", source_head="0" * 40)
    assert service.store.read("job", job["id"]) == job


def test_identity_complete_cross_job_exchange_and_alias_only_tamper(tmp_path):
    from copy import deepcopy
    from quant_shared.strategy_delivery.offline_contract import job_id
    service, job, result, decision = identity_records(tmp_path)
    for kind, original in (("result", result), ("decision", decision)):
        key = job["id"] + ":0000000001" if kind == "decision" else job["id"]
        variants = []
        foreign = deepcopy(original)
        foreign["registration_id"] = foreign["job_identity"]["registration_id"] = "delivery_" + "b" * 32
        foreign["job_id"] = foreign["job_identity"]["job_id"] = job_id(foreign["registration_id"])
        foreign["job_identity_digest"] = digest(foreign["job_identity"])
        variants.append(foreign)
        for field in IDENTITY_FIELDS:
            altered = deepcopy(original); altered[field] = "wrong-alias"
            variants.append(altered)
        legacy = deepcopy(original)
        legacy["schema_version"] = "candidate_offline_" + kind + "_v1"
        variants.append(legacy)
        for value in variants:
            if kind == "result": value["sha256"] = digest({k:v for k,v in value.items() if k != "sha256"})
            with service.store.transaction() as conn: service.store.put(conn, kind, key, value)
            with pytest.raises(DeliveryError, match="identity"): service.result(job["id"])
        with service.store.transaction() as conn: service.store.put(conn, kind, key, original)


def test_identity_resume_rechecks_binding_and_never_reseals_old_job(tmp_path, monkeypatch):
    from quant_shared.strategy_delivery.offline_contract import seal_job_identity, identity_fields
    service, job, _, _ = identity_records(tmp_path)
    runtime = {"state_directory_sha256": "e" * 64}
    runtime["contract_digest"] = digest(runtime)
    binding = {"account_ref": "fixture-account", "identity_hash": "c" * 64, "offline_runtime": runtime}
    package = {"source_head": "2" * 40}
    row = {"id": job["registration_id"], "package": package, "content_digest": digest(package),
           "binding": binding, "binding_digest": digest(binding)}
    ref = {"input_revision_id": "fixture-input", "input_head": "1" * 40, "evidence_kind": "synthetic_fixture"}
    ref["content_digest"] = digest(ref)
    sealed = seal_job_identity(job["id"], row, ref, service.delivery.head, service.inputs.checksum)
    job.update(identity_fields(sealed))
    with service.store.transaction() as conn: service.store.put(conn, "job", job["id"], job)
    monkeypatch.setattr(service.delivery, "get", lambda _: row)
    monkeypatch.setattr(service.inputs, "catalog", lambda: {"inputs": [ref]})
    monkeypatch.setattr(service, "_dispatch", lambda *_: pytest.fail("changed identity must not dispatch"))
    row["binding"]["account_ref"] = "different-account"
    row["binding_digest"] = digest(row["binding"])
    with pytest.raises(DeliveryError, match="identity"):
        service.command(job["id"], "resume", expected_revision=3, key="resume", credential="test-only")
    assert service.store.read("job", job["id"]) == job
    old = dict(job); old.pop("job_identity")
    with service.store.transaction() as conn: service.store.put(conn, "job", job["id"], old)
    with pytest.raises(DeliveryError, match="identity"):
        service.command(job["id"], "resume", expected_revision=3, key="old-resume", credential="test-only")
    assert service.store.read("job", job["id"]) == old
