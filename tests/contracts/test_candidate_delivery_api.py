from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from backend.app.api.candidate_delivery import build_candidate_delivery_router
from backend.app.core.backend_access_policy import evaluate_backend_access, is_research_surface_profile
from backend.app.services.candidate_delivery_sources import ResearchDeliverySources
from quant_crypto.application.btc_registered_candidate import resolve_btc_registered_candidate
from tests.contracts.test_strategy_delivery import setup, package, approve, command


def client(service, **kwargs):
    app = FastAPI()
    app.include_router(build_candidate_delivery_router(service=service, **kwargs), prefix="/api")
    return TestClient(app)


AUTH = {"X-API-Key": "fixture-management-only", "Origin": "http://127.0.0.1:3000", "Idempotency-Key": "api-create-1"}


def test_api_defaults_closed_and_no_storage(setup):
    service, store, _, _, _ = setup
    web = client(service)
    assert web.get("/api/strategy-delivery/capabilities").json()["commands_enabled"] is False
    assert web.post("/api/strategy-delivery/packages", json={"source": package()["source"], "target": "offline"}, headers=AUTH).status_code == 423
    assert not store.root.exists()


def test_auth_origin_fields_and_actor_are_server_owned(setup):
    service, store, _, _, _ = setup
    web = client(service, enabled=True, operator="server-operator", management_key=AUTH["X-API-Key"])
    body = {"source": package()["source"], "target": "offline"}
    assert web.post("/api/strategy-delivery/packages", json=body).status_code == 403
    assert web.post("/api/strategy-delivery/packages", json=body, headers={**AUTH,"Origin":"http://evil.test"}).status_code == 403
    assert web.post("/api/strategy-delivery/packages", json={**body,"approved":True}, headers=AUTH).status_code == 422
    assert web.post("/api/strategy-delivery/packages", json={**body,"actor":"fake"}, headers=AUTH).status_code == 422
    assert not store.root.exists()
    response = web.post("/api/strategy-delivery/packages", json=body, headers=AUTH)
    assert response.status_code == 200, response.text
    assert response.json()["actor"] == "server-operator"
    assert AUTH["X-API-Key"] not in response.text
    assert web.get("/api/strategy-delivery/packages", headers=AUTH).status_code == 200


def test_management_policy_never_opens_other_mutations():
    assert is_research_surface_profile("candidate_management")
    path = "/api/strategy-delivery/packages/delivery_" + "a" * 32 + "/register"
    assert evaluate_backend_access(profile="candidate_management", method="POST", path=path).allowed
    assert not evaluate_backend_access(profile="research_readonly", method="POST", path=path).allowed
    for method, target in [("POST","/api/research/btc/demo-paper/start"), ("GET","/api/research/btc/demo-paper/status"),
                           ("POST","/api/integrations/qlib/run"), ("POST","/api/research/alpha-factory/run"),
                           ("DELETE",path), ("GET","/api/strategy-delivery/packages/latest"),
                           ("POST","/api/strategy-delivery/packages/delivery_" + "a" * 32 + "/start")]:
        assert not evaluate_backend_access(profile="candidate_management", method=method, path=target).allowed


def test_qlib_fixture_cannot_be_consumed_as_arbitrary_runtime_adapter(setup):
    service, _, _, _, _ = setup
    row = command(service, approve(service), "register")
    with pytest.raises(ValueError):
        resolve_btc_registered_candidate(service, row["id"], content_digest=row["content_digest"],
            account_identity_hash="d" * 64, adapter_id="fixture-offline-v1")


def test_committed_donchian_spec_compiles_without_inference_or_network():
    repo = Path(__file__).resolve().parents[2]
    sources = ResearchDeliverySources(repo, archive=None, qlib_root=repo / "missing-not-created")
    from quant_crypto.application.btc_strategy_registry import btc_strategy_registry, OKX_NATIVE_STRATEGY_LINE
    from quant_shared.strategy_delivery.models import validate_package
    spec = btc_strategy_registry.get(OKX_NATIVE_STRATEGY_LINE)
    package = sources.compile({"kind":"registered_rule", "run_id":"donchian-long-50usdt-20260921", "candidate_id":spec.candidate_id})
    assert validate_package(package, "offline") == []
    assert "target_adapter_unsupported" in validate_package(package, "okx_demo")
    assert package["contracts"]["position"]["contracts"] == "0.01"
    assert package["contracts"]["position"]["max_notional_usdt"] == "50"
    assert package["settlement_currency"] == "USDT"


def test_app_composition_skips_demo_in_management_mode():
    # Companion subprocess import check is performed in release review; this
    # protects the import guard without constructing any default runtime here.
    repo = Path(__file__).resolve().parents[2]
    source = (repo / "backend/app/core/deps.py").read_text(encoding="utf-8")
    assert "if is_research_surface_profile(settings.backend_evidence_profile):" in source
    assert "btc_demo_runtime_service = None" in source


def test_real_frozen_qlib_stays_blocked_without_training(tmp_path):
    from backend.app.services.research_archive_discovery import build_m1_research_archive_catalog
    from backend.app.services.candidate_delivery_store import DeliveryStore
    from quant_shared.strategy_delivery.models import validate_package
    from quant_shared.strategy_delivery.service import DeliveryService
    import subprocess
    repo = Path(__file__).resolve().parents[2]
    sources = ResearchDeliverySources(repo, archive=build_m1_research_archive_catalog(repo_root=repo), qlib_root=tmp_path / "empty")
    source = {"kind":"qlib","run_id":"m1-okx-qlib","candidate_id":"qlib_manifest_0de835a36fc243c1"}
    value = sources.compile(source)
    assert value["adapter_id"] == "btc_frozen_qlib_offline_v1"
    assert value["settlement_currency"] == "USDT"
    assert value["artifacts"]["model.txt"] == "8b44ef4bc97be069c21240cbf70a78b7e2f29fc182b057925328503196e16b74"
    assert "no_simulated_fills" in validate_package(value, "offline")
    assert "target_adapter_unsupported" in validate_package(value, "okx_demo")
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    service = DeliveryService(DeliveryStore(tmp_path / "management", "fixture-owner"), sources, object(), head=head)
    row = service.create(source, "offline", key="m1-new-diagnostic-record", actor="operator")
    assert row["status"] == "validated"
    assert row["diagnostic_admission"]["status"] == "admitted"
    assert row["diagnostic_admission"]["research_blockers"] == ["no_simulated_fills", "research_admission_not_proven"]
    assert row["package"]["admission_blockers"] == ["no_simulated_fills", "research_admission_not_proven"]
    assert not any(row["permissions"].values())


def test_frontend_diagnostic_admission_contract_without_browser_server():
    import json, subprocess
    repo = Path(__file__).resolve().parents[2]
    gitdir = Path((repo / ".git").read_text(encoding="utf-8").removeprefix("gitdir:").strip())
    frontend = gitdir.parents[2] / "frontend"
    script = ("const e=require(" + json.dumps(str(frontend / "node_modules" / "esbuild")) + ");"
        "const r=e.buildSync({entryPoints:[" + json.dumps(str(repo / "frontend" / "e2e" / "candidate-diagnostic-admission.spec.ts")) +
        "],bundle:true,platform:'node',format:'cjs',write:false,external:['react','react-dom/server','react-router-dom']});eval(r.outputFiles[0].text);")
    result = subprocess.run(["node", "-e", script], cwd=frontend, capture_output=True,
                            text=True, encoding="utf-8", errors="replace", timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr


def test_actual_factory_backed_v2_recompile_never_dispatches_to_v3(tmp_path):
    from backend.app.services.research_archive_discovery import build_m1_research_archive_catalog
    from integrations.qlib_adapter.research_pipeline import read_sealed_evidence
    from quant_shared.strategy_delivery.models import SCHEMA,digest
    repo=Path(__file__).resolve().parents[2]
    archive=build_m1_research_archive_catalog(repo_root=repo)
    location=archive.resolve_qlib_run(tmp_path/"empty","m1-okx-qlib")
    seal=read_sealed_evidence(location.run_root)["seal"]
    nomination={"candidate_id":"legacy-factory-candidate","factory_run_id":"legacy-factory",
        "qlib_run_id":"m1-okx-qlib","audit_qlib_reference":{"qlib_run_id":"m1-okx-qlib","seal_sha256":digest(seal)},
        "gate":{"blockers":[]}}
    class Reader:
        def get(self,run_id):return {"integrity_status":"passed","result":{"candidates":[nomination]}}
    sources=ResearchDeliverySources(repo,archive=archive,qlib_root=tmp_path/"empty",factory_reader=Reader())
    ref={"kind":"factory","run_id":"legacy-factory","candidate_id":"legacy-factory-candidate"}
    old=sources.compile(ref,package_schema=SCHEMA)
    assert old["schema_version"]==SCHEMA and old["factory_nomination_digest"]==digest(nomination)
    assert sources.recompile(ref,package_schema=SCHEMA)==old
    # Configuring a separate V3 revision must not route historical V2 resolution
    # through that revision reader (or require it to have a matching artifact).
    mixed=ResearchDeliverySources(repo,archive=archive,qlib_root=tmp_path/"empty",factory_reader=Reader(),
        delivery_artifacts=[(tmp_path/"unrelated-v3-not-loaded.json","0"*64)])
    assert mixed.recompile(ref,package_schema=SCHEMA)==old


def test_real_rule_registers_and_resolves_to_existing_history_spec(setup):
    service, _, _, accounts, _ = setup
    repo = Path(__file__).resolve().parents[2]
    service.sources = ResearchDeliverySources(repo, archive=None, qlib_root=repo / "not-used")
    from quant_crypto.application.btc_strategy_registry import btc_strategy_registry, OKX_NATIVE_STRATEGY_LINE
    spec = btc_strategy_registry.get(OKX_NATIVE_STRATEGY_LINE)
    row = service.create({"kind":"registered_rule", "run_id":"donchian-long-50usdt-20260921", "candidate_id":spec.candidate_id},
                         "offline", key="actual-rule", actor="operator")
    accounts.value["currency"] = "USD"
    from quant_shared.strategy_delivery.models import DeliveryError
    with pytest.raises(DeliveryError, match="account_settlement_currency_mismatch"):
        command(service, row, "bind", account_ref="fixture-account")
    accounts.value["currency"] = "USDT"
    row = command(service, row, "bind", account_ref="fixture-account")
    row = command(service, row, "review", decision="approve", reason="software test explicit simulated account")
    row = command(service, row, "register")
    resolved = resolve_btc_registered_candidate(service, row["id"], content_digest=row["content_digest"],
        account_identity_hash="d"*64, adapter_id="btc_donchian_history_offline_v1")
    assert resolved["binding"]["execution"]["max_loss_usdt"] == "10"
    assert resolved["binding"]["execution"]["max_notional_usdt"] == "50"
    assert not any(resolved["permissions"].values())


def test_full_app_management_routes_do_not_construct_demo_or_accept_training(monkeypatch, tmp_path):
    from dataclasses import replace
    from backend.app.api import app_factory
    monkeypatch.setattr(app_factory, "settings", replace(app_factory.settings,
        backend_evidence_profile="candidate_management", web_api_key=AUTH["X-API-Key"],
        candidate_delivery_operator="local-fixture", candidate_delivery_root=str(tmp_path / "management")))
    def forbidden(*args, **kwargs): raise AssertionError("Demo constructed in management mode")
    monkeypatch.setattr(app_factory, "build_btc_demo_runtime_router", forbidden)
    app = app_factory.create_app()
    web = TestClient(app)
    assert web.get("/api/strategy-delivery/capabilities", headers=AUTH).json()["commands_enabled"] is True
    assert web.get("/api/strategy-delivery/packages", headers=AUTH).json()["records"] == []
    assert not (tmp_path / "management").exists()
    for path in ("/api/research/btc/demo-paper/start", "/api/integrations/qlib/run", "/api/research/paper-review/create"):
        assert web.post(path, json={}, headers=AUTH).status_code == 423
    assert web.get("/api/research/btc/demo-paper/status", headers=AUTH).status_code == 423


def test_account_catalog_never_trusts_client_hash_or_verified_boolean(tmp_path):
    import json
    from backend.app.services.candidate_delivery_accounts import DeliveryAccounts
    from quant_shared.strategy_delivery.models import DeliveryError
    path = tmp_path / "accounts.json"
    port = DeliveryAccounts(path, repo_root=tmp_path / "repo")
    assert port.list() == []
    valid = {"account_ref":"offline-test","environment":"offline","simulation_namespace":"explicit-test",
             "revision":1,"market":"crypto","instruments":["BTC-USDT-SWAP"],"currency":"USDT","expires_at":"2027-01-01T00:00:00Z"}
    path.write_text(json.dumps({"schema_version":"delivery_account_catalog_v1","accounts":[valid]}), encoding="utf-8")
    assert port.get("offline-test")["verified"] is True
    for addition in ({"identity_hash":"a"*64},{"verified":True},{"api_key":"not-a-real-key"}):
        path.write_text(json.dumps({"schema_version":"delivery_account_catalog_v1","accounts":[{**valid,**addition}]}), encoding="utf-8")
        with pytest.raises(DeliveryError): port.list()


def test_http_lifecycle_receipt_catalog_and_revoke(setup):
    service, store, _, _, _ = setup
    web = client(service, enabled=True, operator="server-operator", management_key=AUTH["X-API-Key"])
    response = web.post("/api/strategy-delivery/packages", json={"source":package()["source"],"target":"offline"}, headers=AUTH)
    assert response.status_code == 200
    row = response.json()
    for action, payload in [("bind", {"account_ref":"fixture-account"}),
                            ("review", {"decision":"approve","reason":"HTTP fixture only"}), ("register", {})]:
        headers = {**AUTH, "Idempotency-Key":"http-"+action}
        body = {"expected_revision":row["revision"], **payload}
        response = web.post(f"/api/strategy-delivery/packages/{row['id']}/{action}", json=body, headers=headers)
        assert response.status_code == 200, response.text
        row = response.json()
        assert web.get("/api/strategy-delivery/requests/http-"+action, headers=AUTH).json() == row
        assert web.post(f"/api/strategy-delivery/packages/{row['id']}/{action}", json=body, headers=headers).json() == row
    assert len(store.history(row["id"])) == 4
    catalog = web.get("/api/strategy-delivery/catalog", headers=AUTH).json()
    assert len(catalog["records"]) == 1 and catalog["start_allowed"] is False
    assert web.post(f"/api/strategy-delivery/packages/{row['id']}/revoke",
        json={"expected_revision":row["revision"],"reason":"fixture end"}, headers={**AUTH,"Idempotency-Key":"http-revoke"}).status_code == 200
    assert web.get("/api/strategy-delivery/catalog", headers=AUTH).json()["records"] == []


def test_management_import_never_constructs_demo_in_fresh_process():
    import os
    import subprocess
    import sys
    repo = Path(__file__).resolve().parents[2]
    script = """
import socket
def deny(*a, **k): raise AssertionError('network forbidden')
socket.create_connection = deny
socket.socket.connect = deny
from backend.app.core import deps
assert deps.btc_demo_runtime_service is None
from backend.app.api.app_factory import create_app
app = create_app()
assert not any(getattr(route, 'path', '').endswith('/demo-paper/start') for route in app.routes)
print('management import: no Demo controller, no network')
"""
    env = {**os.environ, "QS_BACKEND_EVIDENCE_PROFILE":"candidate_management", "QS_CANDIDATE_DELIVERY_ROOT":""}
    result = subprocess.run([sys.executable,"-c",script], cwd=repo, env=env, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr[-2000:]
    assert "no Demo controller" in result.stdout


def test_management_root_rejects_other_registered_worktrees():
    from backend.app.services.candidate_delivery_bootstrap import build_delivery_service
    from tools.agent_governance.git_metadata import main_repository_root
    from quant_shared.strategy_delivery.models import DeliveryError
    repo = Path(__file__).resolve().parents[2]
    settings = SimpleNamespace(repo_root=repo, candidate_delivery_root=str(main_repository_root(repo)/"never-created-management"))
    with pytest.raises(DeliveryError, match="delivery_root_must_be_external_absolute"):
        build_delivery_service(settings, archive=None, qlib_root=repo/"unused", head="a"*40)


def _offline_account_catalog(tmp_path):
    import json
    from backend.app.services.candidate_delivery_accounts import DeliveryAccounts
    root=tmp_path/"management";root.mkdir()
    path=root/"accounts.json"
    row={"account_ref":"offline-test","environment":"offline","simulation_namespace":"explicit-test",
        "revision":1,"market":"crypto","instruments":["BTC-USDT-SWAP"],"currency":"USDT","expires_at":"2027-01-01T00:00:00Z"}
    def write(rows): path.write_text(json.dumps({"schema_version":"delivery_account_catalog_v1","accounts":rows}),encoding="utf-8")
    write([row])
    return DeliveryAccounts(path,repo_root=Path(__file__).resolve().parents[2]),row,write


def test_offline_runtime_is_explicit_private_path_redacted_and_legacy_projection_unchanged(tmp_path):
    from quant_shared.strategy_delivery.models import digest
    import json
    port,row,write=_offline_account_catalog(tmp_path)
    legacy=port.get(row["account_ref"])
    expected={k:row[k] for k in ("account_ref","environment","revision","market","instruments","currency","expires_at")}
    expected.update(identity_hash=digest({"simulation_namespace":"explicit-test","environment":"offline"}),
        evidence_ref="explicit_simulation:explicit-test",verified=True)
    assert legacy==expected and "offline_runtime" not in legacy
    state=tmp_path/"economic"
    row["offline_runtime"]={"schema_version":"delivery_offline_runtime_v1","state_directory":str(state),
        "initial_equity_usdt":5000.,"currency":"USDT","equity_unit":"USDT"}
    write([row]);new=port.get(row["account_ref"])
    assert new["identity_hash"]==legacy["identity_hash"] and digest(new)!=digest(legacy)
    assert new["offline_runtime"]["simulated_venue_identity_hash"]!=new["identity_hash"]
    assert str(state) not in json.dumps(new) and "state_directory" not in new["offline_runtime"]
    assert not state.exists()
    first=digest(new);row["offline_runtime"]["initial_equity_usdt"]=5001.;write([row])
    assert digest(port.get(row["account_ref"]))!=first and not state.exists()


@pytest.mark.parametrize("damage",["missing","zero","negative","nan","currency","unit","repo","drive","relative","management","nested","same","client_hash"])
def test_offline_runtime_bad_initialization_and_directory_overlap_fail_readonly(tmp_path,damage):
    from copy import deepcopy
    from quant_shared.strategy_delivery.models import DeliveryError
    port,row,write=_offline_account_catalog(tmp_path)
    runtime={"schema_version":"delivery_offline_runtime_v1","state_directory":str(tmp_path/"economic"),
        "initial_equity_usdt":5000.,"currency":"USDT","equity_unit":"USDT"}
    if damage=="missing":runtime.pop("initial_equity_usdt")
    if damage in {"zero","negative","nan"}:runtime["initial_equity_usdt"]={"zero":0.,"negative":-1.,"nan":float("nan")}[damage]
    if damage=="currency":runtime["currency"]="USD"
    if damage=="unit":runtime["equity_unit"]="BTC"
    if damage=="repo":runtime["state_directory"]=str(Path(__file__).resolve().parents[2]/"never-created")
    if damage=="drive":runtime["state_directory"]=tmp_path.anchor
    if damage=="relative":runtime["state_directory"]="relative"
    if damage=="management":runtime["state_directory"]=str(port.path.parent/"child")
    if damage=="client_hash":runtime["verified"]=True
    row["offline_runtime"]=runtime;rows=[row]
    if damage in {"nested","same"}:
        other=deepcopy(row);other["account_ref"]="second";other["simulation_namespace"]="second"
        other["offline_runtime"]["state_directory"]=str(tmp_path/"economic"/("nested" if damage=="nested" else "."))
        rows.append(other)
    write(rows)
    with pytest.raises(DeliveryError):port.list()
    assert not (tmp_path/"economic").exists()
