from pathlib import Path
from dataclasses import replace
import hashlib
import json
import time

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from backend.app.api.alpha_factory import build_alpha_factory_router
from backend.app.services.alpha_factory import AlphaFactoryService
from backend.app.services.task_queue import TaskQueueService
from quant_shared.alpha_factory.contracts import SAFETY, FactoryError


def fixture_client(tmp_path):
    service = AlphaFactoryService(root=tmp_path/"factory",qlib_root=tmp_path/"qlib",queue=TaskQueueService(max_workers=1))
    app=FastAPI();app.include_router(build_alpha_factory_router(service=service,verify_api_key=lambda:None),prefix="/api")
    return TestClient(app),service


def wait_run(service,run_id):
    for _ in range(200):
        result=service.get(run_id)
        if result["status"] not in {"queued","running"}: return result
        time.sleep(.02)
    raise AssertionError("task timeout")


def test_get_is_readonly_and_lists_disabled_markets(tmp_path):
    client,service=fixture_client(tmp_path)
    result=client.get("/api/research/alpha-factory")
    assert result.status_code==200
    assert result.json()["runs"]==[]
    assert all(result.json()[key] is False for key in SAFETY)
    assert not service.root.exists() and not service.qlib_root.exists()


def test_app_factory_reads_alpha_run_from_validated_external_catalog(monkeypatch, tmp_path):
    from backend.app.api import app_factory
    from quant_shared.strategy_delivery.models import digest

    external = tmp_path / "external-candidate-catalog"
    factory_root = external / "factory"
    qlib_root = external / "qlib"
    run_root = factory_root / "external-factory"
    run_root.mkdir(parents=True)
    qlib_root.mkdir()
    state = {
        "run_id": "external-factory", "profile_id": "okx_btc_trend_1h",
        "status": "failed", "created_at": "2026-09-30T00:00:00+00:00",
        "updated_at": "2026-09-30T00:01:00+00:00", "source_head": "a" * 40,
        "owner": {}, "decision": "blocked", "blockers": ["fixture"], "stages": {},
        "request_hash": "b" * 64, "parent_run_id": None, "event_count": 0,
        "last_event_hash": "",
    }
    for name, value in (("state.json", state), ("request.json", {}), ("profile.json", {})):
        (run_root / name).write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    (run_root / "events.jsonl").write_text("", encoding="utf-8")
    files = {
        name: hashlib.sha256((run_root / name).read_bytes()).hexdigest()
        for name in ("state.json", "request.json", "profile.json", "events.jsonl")
    }
    (run_root / "seal.json").write_text(json.dumps({
        "schema_version": "alpha_factory_seal_v1",
        "run_id": "external-factory",
        "files": files,
    }, sort_keys=True), encoding="utf-8")
    catalog = {
        "schema_version": "candidate_offline_catalog_v1",
        "repository_owner": digest({"repository": str(app_factory.settings.repo_root.resolve())}),
        "revision": "factory-fixture-v1", "factory_root": "factory", "qlib_root": "qlib",
        "sources": [], "inputs": [],
    }
    catalog_path = external / "catalog.json"
    catalog_path.write_text(json.dumps(catalog, sort_keys=True), encoding="utf-8")
    monkeypatch.setattr(app_factory, "settings", replace(
        app_factory.settings,
        backend_evidence_profile="candidate_management",
        candidate_delivery_root="",
        candidate_offline_catalog=str(catalog_path),
        candidate_offline_catalog_sha256=hashlib.sha256(catalog_path.read_bytes()).hexdigest(),
        candidate_offline_catalog_revision="factory-fixture-v1",
    ))

    with TestClient(app_factory.create_app()) as client:
        overview = client.get("/api/research/alpha-factory")
        detail = client.get("/api/research/alpha-factory/runs/external-factory")
        missing = client.get("/api/research/alpha-factory/runs/missing")

    assert overview.status_code == 200, overview.text
    external_row = next(row for row in overview.json()["runs"] if row["run_id"] == "external-factory")
    provenance = external_row["evidence_provenance"]
    assert provenance["storage"] == "external_candidate_catalog"
    assert provenance["catalog_revision"] == "factory-fixture-v1"
    assert str(external) not in overview.text
    assert detail.status_code == 200 and detail.json()["integrity_status"] == "passed"
    assert missing.status_code == 404


@pytest.mark.parametrize("override", [{"private":True},{"order":True},{"data_root":"x"},
    {"artifact_root":"x"},{"config":"evil.yaml"},{"run_id":"../escape"},{"run_id":"latest"},
    {"run_id":"CON"},{"run_id":"a"*65},{"generations":100},{"model_trials":True},{"profile_id":"us_equity_daily"},{"profile_id":"cn_equity_daily"}])
def test_post_rejects_unsafe_or_unavailable_requests_without_writes(tmp_path,override):
    client,service=fixture_client(tmp_path)
    response=client.post("/api/tasks/research/alpha-factory",json={"profile_id":"okx_btc_trend_1h","run_id":"test-1",**override})
    assert response.status_code==400,response.text
    assert not service.root.exists()


def test_failed_run_is_durable_idempotent_and_sealed_and_resume_preserves_original(tmp_path,monkeypatch):
    import backend.app.services.alpha_factory as module
    def fail(*args,**kwargs):raise FactoryError("fixture_data_unavailable")
    monkeypatch.setattr(module,"load_factory_input",fail)
    client,service=fixture_client(tmp_path)
    payload={"profile_id":"okx_btc_trend_1h","run_id":"test-failed"}
    response=client.post("/api/tasks/research/alpha-factory",json=payload)
    assert response.status_code==200,response.text
    result=wait_run(service,"test-failed")
    assert result["status"]=="failed" and result["integrity_status"]=="passed"
    assert result["blockers"]==["fixture_data_unavailable"]
    before=(service.root/"test-failed"/"seal.json").read_bytes()
    repeated=client.post("/api/tasks/research/alpha-factory",json=payload)
    assert repeated.status_code==200 and repeated.json()["run_id"]=="test-failed"
    resumed=client.post("/api/tasks/research/alpha-factory/test-failed/resume",json={})
    assert resumed.status_code==200,resumed.text
    new=wait_run(service,resumed.json()["run_id"])
    assert new["parent_run_id"]=="test-failed" and new["run_id"]!="test-failed"
    assert (service.root/"test-failed"/"seal.json").read_bytes()==before
    assert client.post("/api/tasks/research/alpha-factory/test-failed/resume",json={"seed":18}).status_code==400
    (service.root/"test-failed"/"state.json").write_text('{}',encoding='utf-8')
    corrupt=client.get("/api/research/alpha-factory/runs/test-failed").json()
    assert corrupt["integrity_status"]=="blocked" and "result" not in corrupt
    assert client.post("/api/tasks/research/alpha-factory/test-failed/resume",json={}).status_code==400


def test_run_id_collision_is_not_a_new_statistical_trial(tmp_path,monkeypatch):
    import backend.app.services.alpha_factory as module
    monkeypatch.setattr(module,"load_factory_input",lambda *a,**k: (_ for _ in ()).throw(FactoryError("fixture")))
    client,service=fixture_client(tmp_path)
    request={"profile_id":"okx_btc_trend_1h","run_id":"same"}
    client.post("/api/tasks/research/alpha-factory",json=request);wait_run(service,"same")
    response=client.post("/api/tasks/research/alpha-factory",json={**request,"seed":18})
    assert response.status_code==400 and "conflict" in response.text


def test_get_path_escape_and_unknown_run_do_not_create_storage(tmp_path):
    client,service=fixture_client(tmp_path)
    assert client.get("/api/research/alpha-factory/runs/missing").status_code==404
    assert client.get("/api/research/alpha-factory/runs/latest").status_code==400
    assert not service.root.exists()


def test_resume_reuses_exact_sealed_qlib_fit_without_retraining(tmp_path,monkeypatch):
    import pandas as pd
    import backend.app.services.alpha_factory as module
    from integrations.qlib_adapter.research_pipeline import seal_run
    from quant_shared.alpha_factory.contracts import digest
    idx=pd.MultiIndex.from_product([pd.date_range("2020-01-01",periods=10,tz="UTC"),["BTC"]],names=["datetime","instrument"])
    frame=pd.DataFrame({"signal":range(10)},index=idx)
    labels=pd.Series(.01,index=idx)
    input_root=tmp_path/"qlib/input-fixture";input_root.mkdir(parents=True)
    (input_root/"pipeline_result.json").write_text('{"status":"dataset_only"}',encoding="utf-8")
    lineage={"input_run_id":"input-fixture","input_sha256":"fixture-bars-hash","data_version":"fixture-v1","as_of":"2020-01-10",
        "input_seal_sha256":digest(seal_run(input_root))}
    monkeypatch.setattr(module,"load_factory_input",lambda *a,**k:(frame,lineage))
    monkeypatch.setattr(module,"read_factory_input",lambda *a,**k:(frame,lineage))
    monkeypatch.setattr(module,"build_primitives",lambda *a,**k:(frame,[]))
    monkeypatch.setattr(module,"seed_factors",lambda *a,**k:[])
    counts={"fit":0,"campaign":0}
    def fake_fit(**kwargs):
        counts["fit"]+=1
        root=kwargs["qlib_root"]/kwargs["run_id"];root.mkdir(parents=True)
        pd.DataFrame({"datetime":idx.get_level_values("datetime"),"symbol":"BTC","score":.01}).to_parquet(root/"pred_score.parquet")
        (root/"model.txt").write_text("synthetic-model-fixture",encoding="utf-8")
        seal=seal_run(root)
        return labels,{"qlib_run_id":kwargs["run_id"],"seal_sha256":digest(seal)}
    monkeypatch.setattr(module,"train_feature_trial",fake_fit)
    def campaign(**kwargs):
        counts["campaign"]+=1
        pred,reference=kwargs["trainer"](features=frame,labels=labels,segments={"test":["2020-01-01","2020-01-10"]},
            plan={"label":"fixture"},model_spec={"model_id":"fixture"},trial_number=1,phase="fold1")
        if counts["campaign"]==1:raise FactoryError("fixture_interruption_after_sealed_fit")
        assert reference["reused_sealed_trial"] is True
        return {"decision":"rejected","blockers":["synthetic_fixture_only"],**SAFETY}
    monkeypatch.setattr(module,"run_campaign",campaign)
    client,service=fixture_client(tmp_path)
    client.post("/api/tasks/research/alpha-factory",json={"profile_id":"okx_btc_trend_1h","run_id":"cache-fixture"})
    first=wait_run(service,"cache-fixture")
    assert first["status"]=="failed" and counts["fit"]==1
    response=client.post("/api/tasks/research/alpha-factory/cache-fixture/resume",json={})
    assert response.status_code==200,response.text
    second=wait_run(service,response.json()["run_id"])
    assert second["status"]=="completed" and counts["fit"]==1,second
    child=next(service.qlib_root.glob("cache-fixture-t1-fold1"))
    (child/"model.txt").write_text("tampered",encoding="utf-8")
    assert service.get(second["run_id"])["integrity_status"]=="blocked"


def test_dead_owner_is_readonly_interrupted_and_only_explicit_resume_claims_lock(tmp_path,monkeypatch):
    import backend.app.services.alpha_factory as module
    from integrations.qlib_adapter.schemas import write_json
    class DeferredQueue:
        def submit(self,**kwargs):return {"task_id":"fixture-not-started","status":"queued"}
    service=AlphaFactoryService(root=tmp_path/"factory",qlib_root=tmp_path/"qlib",queue=DeferredQueue())
    service.submit({"profile_id":"okx_btc_trend_1h","run_id":"orphan"})
    before=(service.root/"orphan/state.json").read_bytes()
    assert service.get("orphan")["status"]=="queued"
    monkeypatch.setattr(module,"_owner_alive",lambda _:False)
    assert service.get("orphan")["status"]=="interrupted"
    assert (service.root/"orphan/state.json").read_bytes()==before
    with pytest.raises(FactoryError,match="recovery_required"):
        service.submit({"profile_id":"okx_btc_trend_1h","run_id":"unrelated"})
    resumed=service.resume("orphan")
    assert resumed["run_id"]!="orphan" and service.get(resumed["run_id"])["parent_run_id"]=="orphan"
    assert (service.root/"orphan/state.json").read_bytes()==before


def test_windows_atomic_state_retries_transient_reader_handle_only(tmp_path,monkeypatch):
    import backend.app.services.alpha_factory as module
    original=module.os.replace
    calls=[]
    def sharing_violation(source,target):
        calls.append(1)
        if len(calls)<3:raise PermissionError("synthetic_windows_reader_handle")
        return original(source,target)
    monkeypatch.setattr(module.os,"replace",sharing_violation)
    monkeypatch.setattr(module.time,"sleep",lambda _:None)
    module._atomic_json(tmp_path/"state.json",{"status":"completed"})
    assert len(calls)==3
    assert (tmp_path/"state.json").read_text(encoding="utf-8")=='{"status": "completed"}'


def test_concurrent_dead_owner_resume_has_one_writer_and_old_release_cannot_delete_winner(tmp_path,monkeypatch):
    import threading
    from concurrent.futures import ThreadPoolExecutor
    import backend.app.services.alpha_factory as module
    from integrations.qlib_adapter.schemas import read_json
    class DeferredQueue:
        def submit(self,**kwargs):return {"task_id":"fixture-not-started","status":"queued"}
    service=AlphaFactoryService(root=tmp_path/"factory",qlib_root=tmp_path/"qlib",queue=DeferredQueue())
    service.submit({"profile_id":"okx_btc_trend_1h","run_id":"orphan"})
    lock=service.root/".writer.lock";old_owner=read_json(lock)
    monkeypatch.setattr(module,"_owner_alive",lambda owner:owner["run_id"]!="orphan")
    original_unlink=Path.unlink
    def delayed_unlink(path,*args,**kwargs):
        result=original_unlink(path,*args,**kwargs)
        if path==lock:time.sleep(.1)  # deterministic opportunity to race reclaim/claim
        return result
    monkeypatch.setattr(Path,"unlink",delayed_unlink)
    barrier=threading.Barrier(2)
    def resume():
        barrier.wait()
        try:return service.resume("orphan")
        except FactoryError as exc:return {"error":str(exc)}
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:resume(),range(2)))
    accepted=[row for row in results if "run_id" in row]
    assert len(accepted)==1 and sum("error" in row for row in results)==1,results
    assert read_json(lock)["run_id"]==accepted[0]["run_id"]
    module._release_owned_lock(lock,old_owner)
    assert read_json(lock)["run_id"]==accepted[0]["run_id"]


def test_initialization_failure_does_not_publish_unrecoverable_writer_lock(tmp_path,monkeypatch):
    import backend.app.services.alpha_factory as module
    class DeferredQueue:
        def submit(self,**kwargs):return {"task_id":"fixture-not-started","status":"queued"}
    service=AlphaFactoryService(root=tmp_path/"factory",qlib_root=tmp_path/"qlib",queue=DeferredQueue())
    original=module._atomic_json
    def fail_state(path,value):
        if path.name=="state.json" and path.parent.name=="init-failed":raise OSError("fixture_init_interruption")
        return original(path,value)
    monkeypatch.setattr(module,"_atomic_json",fail_state)
    with pytest.raises(OSError,match="init_interruption"):
        service.submit({"profile_id":"okx_btc_trend_1h","run_id":"init-failed"})
    assert not (service.root/".writer.lock").exists()
    assert service.submit({"profile_id":"okx_btc_trend_1h","run_id":"new-attempt"})["status"]=="queued"


def test_queue_rejection_is_persisted_failed_not_eternally_queued(tmp_path):
    class FailingQueue:
        def submit(self,**kwargs):raise RuntimeError("fixture_queue_closed")
    service=AlphaFactoryService(root=tmp_path/"factory",qlib_root=tmp_path/"qlib",queue=FailingQueue())
    with pytest.raises(RuntimeError,match="queue_closed"):
        service.submit({"profile_id":"okx_btc_trend_1h","run_id":"queue-rejected"})
    result=service.get("queue-rejected")
    assert result["status"]=="failed" and result["integrity_status"]=="passed"
    assert result["blockers"]==["queue_submission_failed:fixture_queue_closed"]
    assert not (service.root/".writer.lock").exists()


def test_owner_publication_failure_after_state_is_recoverable_failed(tmp_path,monkeypatch):
    import backend.app.services.alpha_factory as module
    original=module._atomic_json
    def fail_owner(path,value):
        if path.name==".writer.lock":raise OSError("fixture_owner_publication_failed")
        return original(path,value)
    monkeypatch.setattr(module,"_atomic_json",fail_owner)
    _,service=fixture_client(tmp_path)
    with pytest.raises(OSError,match="owner_publication_failed"):
        service.submit({"profile_id":"okx_btc_trend_1h","run_id":"owner-failed"})
    result=service.get("owner-failed")
    assert result["status"]=="failed" and result["integrity_status"]=="passed"
    assert result["recovery"]["explicit_resume_required"] is True
    assert result["blockers"]==["factory_initialization_failed:fixture_owner_publication_failed"]
    assert not (service.root/".writer.lock").exists()


def test_real_acceptance_reserves_each_actual_fit_and_refuses_sixth(tmp_path,monkeypatch):
    import pandas as pd
    import backend.app.services.alpha_factory as module
    from integrations.qlib_adapter.research_pipeline import seal_run
    from integrations.qlib_adapter.factory_factors import seed_factors
    from integrations.qlib_adapter.schemas import read_json
    from quant_shared.alpha_factory.contracts import REAL_ACCEPTANCE_PROFILE,digest
    times=pd.date_range("2025-12-22",periods=200,freq="h",tz="UTC")
    idx=pd.MultiIndex.from_product([times,["BTC-USDT-SWAP"]],names=["datetime","instrument"])
    panel=pd.DataFrame({"open":100.,"high":101.,"low":99.,"close":100.,"volume":100.},index=idx)
    lineage={"input_run_id":"fit-budget-input","input_sha256":"input-hash","data_version":"fixture-v1",
        "as_of":times[-1].isoformat(),"input_seal_sha256":"input-seal"}
    source=tmp_path/"qlib/fit-budget-input";source.mkdir(parents=True)
    (source/"pipeline_result.json").write_text('{"status":"dataset_only"}',encoding="utf-8")
    lineage["input_seal_sha256"]=digest(seal_run(source))
    monkeypatch.setattr(module,"load_factory_input",lambda *a,**k:(panel,lineage))
    monkeypatch.setattr(module,"read_factory_input",lambda *a,**k:(panel,lineage))
    monkeypatch.setattr(module,"_research_dependency_versions",lambda:{"numpy":"fixture","pandas":"fixture",
        "lightgbm":"fixture","qlib":"fixture"})
    primitive_names=("momentum_20d","momentum_60d","momentum_120d","volatility_20d",
        "volatility_60d","liquidity_20d","reversal_1d","volume_20d")
    primitives=pd.DataFrame({name:range(len(idx)) for name in primitive_names},index=idx,dtype=float)
    monkeypatch.setattr(module,"build_primitives",lambda *a,**k:(primitives,[]))
    monkeypatch.setattr(module,"seed_factors",lambda names:seed_factors(names,template_budget=0))
    labels=pd.Series(.01,index=idx)
    fit_calls=[]
    def fake_fit(**kwargs):
        fit_calls.append(kwargs["run_id"])
        if len(fit_calls)==5: raise RuntimeError("fixture_fit_failure_consumes_reservation")
        root=kwargs["qlib_root"]/kwargs["run_id"];root.mkdir(parents=True)
        pd.DataFrame({"datetime":times[:30],"symbol":"BTC-USDT-SWAP","score":.01}).to_parquet(root/"pred_score.parquet")
        (root/"model.txt").write_text("fixture",encoding="utf-8")
        seal=seal_run(root)
        return labels.iloc[:30],{"qlib_run_id":kwargs["run_id"],"seal_sha256":digest(seal)}
    monkeypatch.setattr(module,"train_feature_trial",fake_fit)
    def campaign(**kwargs):
        for number in range(5):
            if number==4:
                with pytest.raises(RuntimeError,match="failure_consumes_reservation"):
                    kwargs["trainer"](features=primitives,labels=labels,
                        segments={"test":[times[number].isoformat(),times[number+30].isoformat()]},
                        plan={"label":"fixture"},model_spec={"model_id":"lgbm_small"},trial_number=1,phase=f"fold{number+1}")
            else:
                kwargs["trainer"](features=primitives,labels=labels,
                    segments={"test":[times[number].isoformat(),times[number+30].isoformat()]},
                    plan={"label":"fixture"},model_spec={"model_id":"lgbm_small"},trial_number=1,phase=f"fold{number+1}")
        with pytest.raises(FactoryError,match="fit_budget_exhausted"):
            kwargs["trainer"](features=primitives,labels=labels,
                segments={"test":[times[10].isoformat(),times[50].isoformat()]},
                plan={"label":"fixture"},model_spec={"model_id":"lgbm_small"},trial_number=1,phase="sixth")
        return {"decision":"rejected","blockers":["fixture_only"],**SAFETY}
    monkeypatch.setattr(module,"run_campaign",campaign)
    _,service=fixture_client(tmp_path)
    result=service.submit({"profile_id":"okx_btc_trend_1h","run_id":"fit-budget",
        "acceptance_profile":REAL_ACCEPTANCE_PROFILE})
    finished=wait_run(service,result["run_id"])
    assert finished["status"]=="completed"
    research_contract=read_json(service.root/"fit-budget/research_contract.json")
    assert research_contract["exit"]["protection"]==module.REAL_ACCEPTANCE_PROTECTION_POLICY
    budget=read_json(service.root/"fit-budget/fit_budget.json")
    assert len(budget["reservations"])==5 and [row["status"] for row in budget["reservations"]]==[
        "completed","completed","completed","completed","failed"]
    baseline_calls=len(fit_calls)
    parent_budget=service.root/"fit-budget/fit_budget.json"
    cases=[("missing",None),("expanded",{**budget,"maximum_actual_fits":6}),
        ("duplicate_attempt",{**budget,"reservations":[budget["reservations"][0],
            {**budget["reservations"][1],"attempt":1},*budget["reservations"][2:]]})]
    for ordinal,(name,value) in enumerate(cases,1):
        if value is None: parent_budget.unlink()
        else: parent_budget.write_text(json.dumps(value),encoding="utf-8")
        child=service.submit({"profile_id":"okx_btc_trend_1h","run_id":f"fit-budget-invalid-{ordinal}",
            "acceptance_profile":REAL_ACCEPTANCE_PROFILE},parent_run_id="fit-budget")
        failed=wait_run(service,child["run_id"])
        assert failed["status"]=="failed" and any(name.split("_")[0] in blocker or "fit_budget_invalid" in blocker
            or "budget_or_contract_missing" in blocker for blocker in failed["blockers"])
        assert len(fit_calls)==baseline_calls
        parent_budget.write_text(json.dumps(budget),encoding="utf-8")
