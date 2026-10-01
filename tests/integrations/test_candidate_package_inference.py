"""Actual LightGBM and factory calculations on synthetic fixtures, no research fitting."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from integrations.qlib_adapter.package_inference import infer_package, load_package_model
from integrations.qlib_adapter.factory_package import compile_factory_package, export_package
from quant_shared.strategy_delivery.models import DeliveryError, canonical, digest
from quant_shared.strategy_delivery.runtime_contract import feature_warmup
from tests.contracts.test_candidate_package_runtime import portable_package, attach_test_receipt


@pytest.fixture(scope="module")
def cases():
    lgb = pytest.importorskip("lightgbm")
    from quant_shared.alpha_factory.contracts import FactorSpec
    from quant_shared.alpha_factory.evaluation import validate_panel, evaluate_expression
    from integrations.qlib_adapter.factory_factors import build_primitives
    rng = np.random.default_rng(625)
    close = 100 + np.cumsum(rng.normal(0, .2, 260))
    times = pd.date_range("2020-02-01", periods=len(close), freq="h", tz="UTC")
    bars = pd.DataFrame({"event_time": times, "decision_time": times + pd.Timedelta(hours=1),
        "available_time": times + pd.Timedelta(hours=1), "instrument": "BTC-USDT-SWAP",
        "open": close, "high": close + 1, "low": close - 1, "close": close,
        "volume": rng.uniform(10, 100, len(close))})
    primitives, _ = build_primitives(validate_panel(bars.assign(datetime=bars.decision_time)), bar_size="1h", annualization=8760)
    output = []
    for number, exprs in enumerate([
        [{"op":"primitive", "primitive":"momentum_20d"}],
        [{"op":"tanh", "args":[{"op":"primitive", "primitive":"reversal_1d"}]},
         {"op":"primitive", "primitive":"volatility_20d"}]], 1):
        specs = [FactorSpec(expr, "registered", "synthetic").to_dict() for expr in exprs]
        features = pd.DataFrame({s["factor_id"]: evaluate_expression(s["expression"], primitives) for s in specs})
        # Tiny test-only model, deterministic labels; no data/candidate training pipeline.
        model = lgb.train({"objective":"regression", "verbosity":-1, "num_threads":1,
            "num_leaves":3, "min_data_in_leaf":5, "seed":number},
            lgb.Dataset(features, label=.02 + .01 * np.nan_to_num(features.iloc[:, 0].to_numpy())), num_boost_round=3)
        p = portable_package(model.model_to_string())
        p["model"]["dependencies"]["lightgbm"] = lgb.__version__
        p["source"]["candidate_id"] = "synthetic-candidate-" + str(number)
        p["contracts"]["features"].update(specs=specs, names=list(features), warmup_bars=feature_warmup(specs))
        evidence = p["contracts"]["calibration"]["evidence"]
        evidence["candidate_id"] = p["source"]["candidate_id"]
        evidence["feature_specs_sha256"] = digest(specs)
        p["contracts"]["calibration"]["evidence_sha256"] = digest(evidence)
        def sample_rows(times, frame):
            values = model.predict(frame, num_threads=1)
            return [{"event_time":t.isoformat(), "instrument":"BTC-USDT-SWAP",
                     "features":[None if pd.isna(v) else float(v) for v in fs],
                     "raw_score":float(x), "label":float(x)} for t,fs,x in zip(times,frame.to_numpy(),values)]
        attach_test_receipt(p,
            fit_rows=sample_rows(pd.date_range("2020-01-01",periods=100,freq="h",tz="UTC"),features.iloc[80:180]),
            audit_rows=sample_rows(bars.event_time,features))
        output.append((p, bars, features, model))
    return output


def test_two_different_models_and_feature_sets_share_adapter_with_actual_parity(cases):
    digests = []
    for p, bars, features, model in cases:
        result = infer_package(p, bars, data_version=p["data_version"], visible_through=bars.decision_time.iloc[-1])
        rows = result["rows"]
        expected = features.iloc[p["contracts"]["features"]["warmup_bars"]-1:]
        np.testing.assert_array_equal(rows[p["contracts"]["features"]["names"]].to_numpy(), expected.to_numpy())
        np.testing.assert_allclose(rows.raw_score, model.predict(expected, num_threads=1), atol=0, rtol=0)
        assert not any(result["permissions"].values()) and result["execution_status"] == "not_executed"
        digests.append(result["model_sha256"])
    assert len(set(digests)) == 2


def test_batch_per_bar_restart_and_future_append_are_identical(cases):
    for p, bars, _, _ in cases:
        cutoff = bars.decision_time.iloc[180]
        full = infer_package(p, bars, data_version=p["data_version"], visible_through=cutoff)["rows"]
        prefix = bars.iloc[:181].copy()
        repeated = infer_package(json.loads(canonical(p)), prefix, data_version=p["data_version"], visible_through=cutoff, mode="one_by_one")["rows"]
        pd.testing.assert_frame_equal(full, repeated)
        for count in (181, 182, 183):
            step = infer_package(p, bars.iloc[:count], data_version=p["data_version"], visible_through=bars.decision_time.iloc[count-1])["rows"]
            whole = infer_package(p, bars, data_version=p["data_version"], visible_through=bars.decision_time.iloc[-1])["rows"]
            pd.testing.assert_frame_equal(step, whole.iloc[:len(step)].reset_index(drop=True))


def test_parallel_readers_are_stateless_and_input_drift_is_visible(cases):
    from concurrent.futures import ThreadPoolExecutor
    p,bars,_,_=cases[0]
    def run(frame): return infer_package(p,frame,data_version=p["data_version"],visible_through=bars.decision_time.iloc[-1])
    with ThreadPoolExecutor(max_workers=2) as pool:
        first,second=list(pool.map(run,[bars,bars.copy()]))
    assert first["predictions_sha256"]==second["predictions_sha256"]
    assert first["visible_input_sha256"]==second["visible_input_sha256"]
    changed=bars.copy();changed.loc[150,"volume"]+=1
    assert run(changed)["visible_input_sha256"]!=first["visible_input_sha256"]


@pytest.mark.parametrize("damage,reason", [("gap","time_or_gap"),("late","time_or_gap"),("naive","timestamp"),
    ("instrument","instrument_mismatch"),("model","model_hash"),("version","version_mismatch"),("data","data_version")])
def test_bad_market_model_or_identity_fails_closed(cases, damage, reason):
    p, bars, _, _ = cases[0]; p, bars = deepcopy(p), bars.copy()
    version = p["data_version"]
    if damage == "gap": bars = bars.drop(100)
    if damage == "late": bars.loc[100,"available_time"] += pd.Timedelta(hours=1)
    if damage == "naive": bars["event_time"] = bars.event_time.dt.tz_localize(None)
    if damage == "instrument": bars["instrument"] = "ETH-USDT-SWAP"
    if damage == "model": p["model"]["text"] += "tamper"
    if damage == "version": p["model"]["dependencies"]["lightgbm"] = "0.0.0"
    if damage == "data": version = "other"
    with pytest.raises(DeliveryError, match=reason):
        infer_package(p, bars, data_version=version, visible_through=bars.decision_time.iloc[-1])


def sealed_factory(tmp_path, p):
    import yaml
    import subprocess
    from integrations.qlib_adapter.research_pipeline import seal_run
    root = tmp_path / "audit-a"; root.mkdir()
    windows = deepcopy(p["evidence_receipt"]["windows"])
    head = subprocess.check_output(["git","rev-parse","HEAD"],text=True).strip()
    model_spec = {"model_id":"fixture-lgbm", "num_leaves":3}
    trial = {"status":"completed", "run_id":root.name, "factory_run_id":"factory-a", "segments":windows,
        "feature_ids":p["contracts"]["features"]["names"], "model_spec":model_spec, "source_head":head}
    config = {"mode":"research_only", "paper_enabled":False, "live_enabled":False,
        "model":{"strategy_version":"shared_alpha_factory_v1","label":"open[t+14]/open[t+2]-1"}, "task":{"model":{"class":"LGBModel","module_path":"qlib.contrib.model.gbdt"},
        "dataset":{"kwargs":{"handler":{"kwargs":{"infer_processors":[], "data_loader":{"class":"FactoryParquetLoader",
        "module_path":"integrations.qlib_adapter.factory_loader"}}}}}}}
    config["delivery_policy"] = {k:p["evidence_receipt"]["frozen_policy"][k] for k in ("policies","clip_fraction","frozen_at")}
    (root/"model.txt").write_text(p["model"]["text"], encoding="utf-8", newline="")
    (root/"factory_trial.json").write_text(json.dumps(trial),encoding="utf-8")
    (root/"factory_config.yaml").write_text(yaml.safe_dump(config),encoding="utf-8")
    rows = p["evidence_receipt"]["fit_rows"] + p["evidence_receipt"]["audit_rows"]
    idx = pd.MultiIndex.from_tuples([(pd.Timestamp(r["event_time"]),r["instrument"]) for r in rows],names=["datetime","instrument"])
    pd.DataFrame([r["features"] for r in rows],index=idx,columns=trial["feature_ids"]).to_parquet(root/"factory_features.parquet")
    pd.DataFrame({"label":[r["label"] for r in rows]},index=idx).to_parquet(root/"factory_labels.parquet")
    audit_rows = p["evidence_receipt"]["audit_rows"]
    scores = pd.DataFrame({"datetime":[pd.Timestamp(r["event_time"]) for r in audit_rows],
        "symbol":[r["instrument"] for r in audit_rows],"score":[r["raw_score"] for r in audit_rows]})
    scores.to_parquet(root/"pred_score.parquet",index=False)
    (root/"qlib_input").mkdir()
    (root/"qlib_input/dataset_manifest.json").write_text(json.dumps({"run_id":root.name,
        "data_version":p["data_version"],"symbols":[p["instrument"]],"bar_size":p["bar_size"],
        "files":{"features":"factory_features.parquet","labels":"factory_labels.parquet"}}))
    (root/"recorder_metrics.json").write_text(json.dumps({"id":"synthetic-recorder","metrics":{}}))
    seal = seal_run(root)
    specs = p["contracts"]["features"]["specs"]
    candidate = {"candidate_id":p["source"]["candidate_id"], "factory_run_id":"factory-a", "qlib_run_id":root.name,
        "data_version":p["data_version"], "feature_specs":specs,
        "frozen_champion":{"model_spec":model_spec,"feature_spec_hash":digest(specs),"audit_used_for_selection":False},
        "strategy_config":{"strategy_id":p["strategy_id"]}, "gate":{"status":"research_candidate","blockers":[]},
        "audit_qlib_reference":{"qlib_run_id":root.name,"seal_sha256":digest(seal),"segments":windows,
        "feature_ids":trial["feature_ids"],"model_spec":model_spec},
        "delivery_contract":{"contracts":deepcopy(p["contracts"]),"model_dependencies":p["model"]["dependencies"],
        "settlement_evidence":p["settlement_evidence"],"feature_implementation":p["feature_implementation"]}}
    from quant_shared.alpha_factory.evaluation import signal_metrics
    audit_series = scores.rename(columns={"symbol":"instrument"}).set_index(["datetime","instrument"]).score
    candidate["audit_metrics"] = signal_metrics(audit_series,audit_series,"time_series")
    candidate["delivery_contract"]["frozen_policy"] = deepcopy(p["evidence_receipt"]["frozen_policy"])
    result = {"source_head":head,"candidates":[candidate],"factor_specs":specs,"profile":{"market":"crypto","symbols":["BTC-USDT-SWAP"],
        "bar_size":"1h","data_version":p["data_version"],"label_horizon":12,"entry_delay":2,"annualization":8760,"metric_mode":"time_series"},
        "split_plan":{"horizon_bars":12,"entry_delay_bars":2,"label":"open[t+14]/open[t+2]-1",
        "segments":{"train":[windows["train"][0],"2018-03-01T00:00:00Z"],"valid":["2018-04-01T00:00:00Z",windows["train"][1]],
        "selection":windows["valid"],"audit":windows["test"]}}}
    envelope = {"source_head":head,"integrity_status":"passed","run_id":"factory-a","result":result}
    # Use the real producer to create receipts; do not hand-write passed flags.
    from integrations.qlib_adapter.factory_delivery import publish_factory_delivery
    authored = candidate.pop("delivery_contract")
    produced = publish_factory_delivery(p["source"],envelope,root,frozen_contract=authored,destination=tmp_path/"delivery.json")
    envelope["delivery_contract"] = produced["artifact"]["candidate"]["delivery_contract"]
    return root, envelope


def test_final_audit_export_is_complete_immutable_and_keeps_original_seal(tmp_path, cases):
    p = cases[0][0]
    root, envelope = sealed_factory(tmp_path, p)
    before = (root/"run_seal.json").read_bytes()
    compiled = compile_factory_package(p["source"], envelope, root)
    assert compiled["package_validation"]["status"] == "passed"
    path = tmp_path/"package.json"
    receipt = export_package(compiled, path)
    assert receipt["content_digest"] == digest(json.loads(path.read_text()))
    with pytest.raises(FileExistsError): export_package(compiled, path)
    assert (root/"run_seal.json").read_bytes() == before
    assert load_package_model(compiled).num_trees() == 3


def test_real_factory_shape_without_runtime_evidence_reports_gaps(tmp_path, cases):
    p = cases[0][0]; root, envelope = sealed_factory(tmp_path,p)
    candidate = envelope["result"]["candidates"][0]
    envelope.pop("delivery_contract")
    candidate["gate"] = {"status":"rejected","blockers":["no_nonzero_ledger_evidence"]}
    compiled = compile_factory_package(p["source"], envelope, root)
    assert "calibration_contract_missing" in compiled["package_validation"]["blockers"]
    assert "no_nonzero_ledger_evidence" in compiled["admission_blockers"]
    assert compiled["settlement_currency"] is None
    with pytest.raises(DeliveryError, match="package_export_blocked"):
        export_package(compiled,tmp_path/"must-not-exist.json")
    assert not (tmp_path/"must-not-exist.json").exists()


def test_nonmapping_authored_model_dependencies_remain_blocked(tmp_path, cases):
    p = cases[0][0]; root, envelope = sealed_factory(tmp_path, p)
    envelope["delivery_contract"]["model_dependencies"] = None
    compiled = compile_factory_package(p["source"], envelope, root, produce_evidence=True)
    assert compiled["model"]["dependencies"] == {}
    assert "model_dependency_missing" in compiled["package_validation"]["blockers"]


def test_v1_delivery_contract_preserves_authored_dependency_mapping(tmp_path, cases):
    from integrations.qlib_adapter.factory_delivery import build_factory_delivery_contract
    p = cases[0][0]; _, envelope = sealed_factory(tmp_path, p)
    authored = envelope["delivery_contract"]
    evidence = {"frozen_policy": authored["frozen_policy"],
        "calibration": authored["contracts"]["calibration"],
        "model_dependencies": {**authored["model_dependencies"], "qlib": "0.9.7"},
        "feature_dependencies": authored["feature_implementation"]["dependencies"],
        "settlement_evidence": authored["settlement_evidence"]}
    built = build_factory_delivery_contract(p["source"], envelope, evidence)
    assert built["model_dependencies"] == evidence["model_dependencies"]


@pytest.mark.parametrize("target,damage", [
    ("model_dependencies", "missing"), ("model_dependencies", "extra"),
    ("feature_dependencies", "missing"), ("feature_dependencies", "extra")])
def test_v2_delivery_contract_rejects_incomplete_or_extra_dependency_sets(tmp_path, cases, target, damage):
    from integrations.qlib_adapter.factory_delivery import build_factory_delivery_contract
    p = cases[0][0]; _, envelope = sealed_factory(tmp_path, p)
    envelope["result"]["request"] = {"acceptance_profile": "btc_real_candidate_offline_20260930_v1"}
    authored = envelope["delivery_contract"]
    evidence = {"receipt_version": "factory_delivery_evidence_v2",
        "frozen_policy": authored["frozen_policy"], "calibration": authored["contracts"]["calibration"],
        "model_dependencies": {"lightgbm": "4.7.0", "qlib": "0.9.7"},
        "feature_dependencies": {"numpy": "2.4.6", "pandas": "3.0.4"},
        "settlement_evidence": authored["settlement_evidence"]}
    key = next(iter(evidence[target]))
    if damage == "missing":
        del evidence[target][key]
    else:
        evidence[target]["unexpected"] = "1.0"
    with pytest.raises(DeliveryError, match="factory_frozen_dependency_versions_invalid"):
        build_factory_delivery_contract(p["source"], envelope, evidence)


@pytest.mark.parametrize("damage",["fold","spec","seal","id","calibration","source_head"])
def test_wrong_final_audit_identity_rejected(tmp_path,cases,damage):
    p=cases[0][0];root,envelope=sealed_factory(tmp_path,p)
    candidate=envelope["result"]["candidates"][0]
    if damage=="fold": candidate["audit_qlib_reference"]["segments"]["test"]=["2018-01-01","2018-02-01"]
    if damage=="spec": candidate["frozen_champion"]["feature_spec_hash"]="f"*64
    if damage=="seal": (root/"model.txt").write_text("tampered")
    if damage=="id": candidate["qlib_run_id"]="other"
    if damage=="calibration": envelope["delivery_contract"]["contracts"]["calibration"]["evidence"]["fitted_through"]="2020-02-01T00:00:00Z"
    if damage=="source_head": envelope["source_head"]="f"*40
    with pytest.raises(DeliveryError): compile_factory_package(p["source"],envelope,root)


def test_backend_factory_resolution_uses_final_package_without_fixed_candidate_id(tmp_path,cases):
    from pathlib import Path
    from types import SimpleNamespace
    from backend.app.services.candidate_delivery_sources import ResearchDeliverySources
    for number, (p, _, _, _) in enumerate(cases):
        sub=tmp_path/str(number);sub.mkdir()
        root,envelope=sealed_factory(sub,p)
        class Reader:
            def get(self,run_id):
                assert run_id==p["source"]["run_id"]
                return envelope
        class Archive:
            def resolve_qlib_run(self,qlib_root,run_id):
                assert run_id==root.name
                return SimpleNamespace(run_root=root,qlib_root=root.parent)
        sources=ResearchDeliverySources(Path(__file__).resolve().parents[2],archive=Archive(),qlib_root=sub,factory_reader=Reader())
        compiled=sources.compile(p["source"])
        assert compiled["source"]==p["source"]
        assert compiled["package_validation"]["status"]=="passed"


def test_final_label_horizon_cannot_be_redeclared_even_with_rehashed_calibration(tmp_path,cases):
    p=cases[0][0];root,envelope=sealed_factory(tmp_path,p)
    envelope["result"]["split_plan"]["horizon_bars"]=12
    contracts=envelope["delivery_contract"]["contracts"]
    contracts["output"]["horizon_bars"]=24
    contracts["calibration"]["evidence"]["output_sha256"]=digest(contracts["output"])
    contracts["calibration"]["evidence_sha256"]=digest(contracts["calibration"]["evidence"])
    with pytest.raises(DeliveryError,match="factory_label_contract_mismatch"):
        compile_factory_package(p["source"],envelope,root)


@pytest.mark.parametrize("name",["factory_features.parquet","factory_labels.parquet","pred_score.parquet",
    "qlib_input/dataset_manifest.json","recorder_metrics.json"])
def test_review_valid_seal_without_required_audit_contents_is_rejected(tmp_path,cases,name):
    p=cases[0][0];root,envelope=sealed_factory(tmp_path,p)
    seal=json.loads((root/"run_seal.json").read_text())
    del seal["files"][name]
    (root/name).unlink()  # isolated synthetic artifact only
    (root/"run_seal.json").write_text(json.dumps(seal))
    envelope["result"]["candidates"][0]["audit_qlib_reference"]["seal_sha256"]=digest(seal)
    with pytest.raises(DeliveryError,match="package_artifact_missing"):
        compile_factory_package(p["source"],envelope,root)


@pytest.mark.parametrize("damage",["prediction","label","metrics","manifest_asset","policy"])
def test_review_resealed_content_must_reproduce_not_merely_hash(tmp_path,cases,damage):
    p=cases[0][0];root,envelope=sealed_factory(tmp_path,p)
    seal=json.loads((root/"run_seal.json").read_text())
    if damage in {"prediction","label"}:
        name="pred_score.parquet" if damage=="prediction" else "factory_labels.parquet"
        frame=pd.read_parquet(root/name);frame.iloc[-1,-1]+=.1;frame.to_parquet(root/name)
    elif damage=="manifest_asset":
        name="qlib_input/dataset_manifest.json"
        manifest=json.loads((root/name).read_text());manifest["symbols"]=["ETH-USDT-SWAP"]
        (root/name).write_text(json.dumps(manifest))
    elif damage=="metrics":
        name=None;envelope["result"]["candidates"][0]["audit_metrics"]["ic"]=-1
    else:
        name=None
        authored=envelope["delivery_contract"]
        authored["contracts"]["position"]["risk_budget_fraction"]=1.
        authored["frozen_policy"]["policies"]["position"]["risk_budget_fraction"]=1.
    if name:
        seal["files"][name]=hashlib.sha256((root/name).read_bytes()).hexdigest()
        (root/"run_seal.json").write_text(json.dumps(seal))
        envelope["result"]["candidates"][0]["audit_qlib_reference"]["seal_sha256"]=digest(seal)
    with pytest.raises(DeliveryError): compile_factory_package(p["source"],envelope,root)


def test_actual_producer_assembly_and_explicit_source_revision_roundtrip(tmp_path,cases):
    from integrations.qlib_adapter.factory_delivery import publish_factory_delivery,FactoryDeliveryReader
    from backend.app.services.candidate_delivery_sources import ResearchDeliverySources
    from types import SimpleNamespace
    p=cases[0][0];root,envelope=sealed_factory(tmp_path,p)
    authored=envelope.pop("delivery_contract")
    evidence={"frozen_policy":authored["frozen_policy"],"calibration":authored["contracts"]["calibration"],
        "model_dependencies":authored["model_dependencies"],"feature_dependencies":authored["feature_implementation"]["dependencies"],
        "settlement_evidence":authored["settlement_evidence"]}
    target=tmp_path/"assembled.json"
    produced=publish_factory_delivery(p["source"],envelope,root,frozen_evidence=evidence,destination=target)
    class Reader:
        def get(self,run_id): return deepcopy(envelope)
    class Archive:
        def resolve_qlib_run(self,qlib_root,run_id): return SimpleNamespace(run_root=root,qlib_root=root.parent)
    source=ResearchDeliverySources(Path(__file__).resolve().parents[2],archive=Archive(),qlib_root=root.parent,
        factory_reader=Reader(),delivery_artifacts=[(target,produced["content_digest"])])
    actual=source.compile(p["source"])
    assert digest(actual)==produced["package_digest"]
    assert actual["evidence_validation"]["status"]=="passed"
    with pytest.raises(FileExistsError):
        publish_factory_delivery(p["source"],envelope,root,frozen_evidence=evidence,destination=target)
    target.write_text("{}")
    with pytest.raises(DeliveryError,match="artifact_changed"): source.compile(p["source"])
