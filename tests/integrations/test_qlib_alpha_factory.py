import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from integrations.qlib_adapter.build_qlib_dataset import _build_native_file_provider
from integrations.qlib_adapter.factory_trainer import train_feature_trial, MODEL_CATALOG
from integrations.qlib_adapter.research_pipeline import seal_run, read_sealed_evidence
from integrations.qlib_adapter.schemas import resolve_git_commit, write_json
from integrations.qlib_adapter.profiles import REPO
from quant_shared.alpha_factory.contracts import SAFETY, digest
from backend.app.services.alpha_factory import REAL_ACCEPTANCE_PROTECTION_POLICY


def input_fixture(root, symbols, frequency, market):
    size = 680
    times = pd.date_range("2020-01-01", periods=size, freq=frequency, tz="UTC")
    index = pd.MultiIndex.from_product([times, symbols], names=["datetime","instrument"])
    rng = np.random.default_rng(17)
    features = pd.DataFrame({"signal":rng.normal(size=len(index)),"momentum":rng.normal(size=len(index))},index=index)
    labels = (.01*features.signal + rng.normal(0,.001,len(index))).rename("label")
    frame = pd.DataFrame({"date":index.get_level_values("datetime").strftime("%Y-%m-%d %H:%M:%S" if frequency=="h" else "%Y-%m-%d"),
        "symbol":index.get_level_values("instrument"),"open":100.,"high":102.,"low":99.,"close":101.,"volume":100.,"factor":1.})
    source = root/"fixture-input"
    (source/"qlib_input").mkdir(parents=True)
    bars_path = source/"qlib_input/daily_bars.parquet";frame.to_parquet(bars_path,index=False)
    manifest = {"run_id":"fixture-input","status":"completed","symbols_exported":list(symbols),
        "universe":{"universe_id":"synthetic-fixture"},"source_manifests":[{"symbol":symbol,"data_version":"synthetic-v1"} for symbol in symbols],
        "calendar":{"qlib_freq":"60min" if frequency=="h" else "day","trading_days":frame.date.unique().tolist()},
        "files":{"daily_bars_parquet":str(bars_path)},"input_sha256":hashlib.sha256(bars_path.read_bytes()).hexdigest(),
        "input_contract":{"asset_class":"crypto" if market=="crypto" else "equity","bar_size":"1h" if frequency=="h" else "1d"}}
    write_json(source/"qlib_input/dataset_manifest.json",manifest)
    _build_native_file_provider(dataset_manifest=manifest,provider_dir=source/"qlib_provider")
    seal = seal_run(source)
    lineage = {"input_run_id":"fixture-input","input_seal_sha256":digest(seal),"dataset_manifest":manifest,
        "split_plan":{"label":"synthetic_causal_fixture_label"}}
    profile = {"profile_id":"fixture-"+market,"market":market,"asset_class":manifest["input_contract"]["asset_class"],
        "bar_size":manifest["input_contract"]["bar_size"],"profile_hash":digest({"market":market}),**SAFETY}
    segments = {"train":[times[0].isoformat(),times[399].isoformat()],
        "valid":[times[420].isoformat(),times[499].isoformat()],"test":[times[520].isoformat(),times[659].isoformat()]}
    return features, labels, profile, lineage, segments


@pytest.mark.parametrize("symbols,frequency,market", [(("BTC-USDT-SWAP",),"h","crypto"),
    (("AAPL","MSFT","SPY"),"B","us_equity"),(("000001","600000","000002"),"B","cn_equity")])
def test_actual_shared_qlib_trains_generated_features_across_markets(tmp_path,symbols,frequency,market):
    pytest.importorskip("qlib");pytest.importorskip("lightgbm")
    features,labels,profile,lineage,segments = input_fixture(tmp_path,symbols,frequency,market)
    pred,ref = train_feature_trial(features=features,labels=labels,segments=segments,profile=profile,lineage=lineage,
        model_spec=MODEL_CATALOG[0],seed=17,qlib_root=tmp_path,run_id="factory-fixture-trial",factory_run_id="factory-fixture",trial_number=1)
    assert len(pred) == 140 * len(symbols)
    assert set(pred.index.get_level_values("instrument")) == set(symbols)
    assert np.isfinite(pred).all() and pred.nunique() > 1
    assert ref["recorder_id"] and (tmp_path/ref["qlib_run_id"]/"model.txt").stat().st_size > 100
    verified = read_sealed_evidence(tmp_path/ref["qlib_run_id"])
    assert verified["integrity_status"] == "passed"
    assert "factory_trial.json" in verified["seal"]["files"]
    assert all(verified[key] is False for key in ("execution_permission","promotion","paper","live","private","order"))
    (tmp_path/ref["qlib_run_id"]/"model.txt").write_text("tampered",encoding="utf-8")
    assert read_sealed_evidence(tmp_path/ref["qlib_run_id"])["integrity_status"] == "blocked"


def test_real_acceptance_final_fit_predicts_validation_then_audit_once_without_signal_record(tmp_path,monkeypatch):
    pytest.importorskip("qlib");pytest.importorskip("lightgbm")
    from importlib.metadata import version
    from qlib.contrib.model.gbdt import LGBModel
    predict_calls=[];fit_calls=[]
    original_predict,original_fit=LGBModel.predict,LGBModel.fit
    def counted_predict(self,dataset,segment="test",**kwargs):
        predict_calls.append(segment);return original_predict(self,dataset,segment=segment,**kwargs)
    def counted_fit(self,dataset,**kwargs):
        fit_calls.append(1);return original_fit(self,dataset,**kwargs)
    monkeypatch.setattr(LGBModel,"predict",counted_predict);monkeypatch.setattr(LGBModel,"fit",counted_fit)
    features,labels,profile,lineage,segments=input_fixture(tmp_path,("BTC-USDT-SWAP",),"h","crypto")
    from quant_shared.alpha_factory.contracts import FactorSpec
    specs=[FactorSpec({"op":"primitive","primitive":"momentum_20d"},"registered","fixture").to_dict(),
        FactorSpec({"op":"primitive","primitive":"volatility_20d"},"registered","fixture").to_dict()]
    features.columns=[row["factor_id"] for row in specs]
    lineage["data_version"]="synthetic-v1"
    contract={"schema_version":"btc_real_candidate_research_contract_v1","policy_committed_at":"2026-09-29T00:00:00Z",
        "source_head":resolve_git_commit(REPO),
        "dependency_versions":{"numpy":version("numpy"),"pandas":version("pandas"),
            "lightgbm":version("lightgbm"),"qlib":version("pyqlib")},
        "calibration":{"kind":"ols_validation_only","slope_clip":.05,"applications":1},
        "position":{"version":"qlib_candidate_policy_v1","risk_budget_fraction":.01,"max_weight":.1,
            "volatility_target_annual_configured":.2,"volatility_target_applied":False},
        "exit":{"version":"qlib_candidate_policy_v1","hard_stop_fraction":.04,"take_profit_fraction":.08,
            "trailing_stop_fraction":.03,"maximum_holding_bars":12,
            "protection":dict(REAL_ACCEPTANCE_PROTECTION_POLICY)},
        "cost":{"version":"qlib_candidate_policy_v1","execution_delay_bars":2,"fee_bps_per_side":5,
            "slippage_bps_per_side":2,"spread_bps_per_side":2,"impact_bps_per_side":2,"funding":"visible_rate"},
        "output":{"version":"return_forecast_v1","kind":"return_forecast","unit":"return_fraction",
            "horizon_bars":12,"valid_for_bars":2,"score_rule":"absolute_return_fraction_unit_multiplier"}}
    prediction,ref=train_feature_trial(features=features,labels=labels,segments=segments,profile=profile,lineage=lineage,
        model_spec=MODEL_CATALOG[0],seed=17,qlib_root=tmp_path,run_id="acceptance-final-fixture",
        factory_run_id="acceptance-fixture",trial_number=1,phase="final",candidate_id="alpha_fixture",research_contract=contract)
    receipt=json.loads((tmp_path/ref["qlib_run_id"]/"factory_finalization_receipt.json").read_text())
    calibration=json.loads((tmp_path/ref["qlib_run_id"]/"factory_calibration_seal.json").read_text())
    assert receipt["prediction_calls"]==["validation_once","audit_once"]
    assert receipt["signal_record_generated"] is False and receipt["audit_opened_after_calibration_seal"] is True
    assert receipt["model_sha256"]==calibration["model_sha256"]
    assert receipt["policy_sha256"]==calibration["policy_sha256"]
    assert receipt["source_head"]==calibration["source_head"]==contract["source_head"]
    assert receipt["operation_order"]==["policy_freeze","final_fit","model_seal","validation_prediction",
        "calibration_seal","audit_prediction"]
    assert set(receipt["wall_operations"])==set(["policy_committed_at","final_fit_started_at","final_fit_completed_at",
        "model_sealed_at","validation_prediction_started_at","validation_prediction_completed_at",
        "calibration_sealed_at","audit_prediction_started_at","audit_prediction_completed_at"])
    assert fit_calls==[1] and predict_calls==["valid","test"]
    assert calibration["quality_passed"] is True and len(prediction)==140
    assert read_sealed_evidence(tmp_path/ref["qlib_run_id"])["integrity_status"]=="passed"
    from integrations.qlib_adapter.factory_delivery import publish_factory_delivery
    from quant_shared.alpha_factory.evaluation import signal_metrics
    from quant_shared.strategy_delivery.runtime_contract import validate_runtime_contract
    source={"kind":"factory","run_id":"acceptance-fixture","candidate_id":"alpha_fixture"}
    model_spec=MODEL_CATALOG[0]
    audit_metrics=signal_metrics(prediction,labels.reindex(prediction.index),"time_series")
    candidate={"candidate_id":source["candidate_id"],"factory_run_id":source["run_id"],
        "qlib_run_id":ref["qlib_run_id"],"data_version":"synthetic-v1","feature_specs":specs,
        "frozen_champion":{"model_spec":model_spec,"feature_spec_hash":digest(specs),"audit_used_for_selection":False},
        "strategy_config":{"strategy_id":"qlib_forecast"},"gate":{"status":"research_candidate","blockers":[]},
        "audit_metrics":audit_metrics,"audit_qlib_reference":ref}
    result={"source_head":contract["source_head"],"request":{"acceptance_profile":"btc_real_candidate_offline_20260930_v1"},
        "candidates":[candidate],"factor_specs":specs,
        "profile":{"market":"crypto","symbols":["BTC-USDT-SWAP"],"bar_size":"1h","data_version":"synthetic-v1",
            "label_horizon":12,"entry_delay":2,"annualization":8760,"metric_mode":"time_series"},
        "split_plan":{"horizon_bars":12,"entry_delay_bars":2,"label":lineage["split_plan"]["label"],
            "segments":{"train":[segments["train"][0],features.index.get_level_values("datetime")[200].isoformat()],
                "valid":[features.index.get_level_values("datetime")[201].isoformat(),segments["train"][1]],
                "selection":segments["valid"],"audit":segments["test"]}}}
    evidence=ref["acceptance_delivery_evidence"]
    evidence["frozen_policy"]["feature_specs_sha256"]=digest(specs)
    produced=publish_factory_delivery(source,{"source_head":contract["source_head"],"integrity_status":"passed",
        "run_id":source["run_id"],"result":result},tmp_path/ref["qlib_run_id"],frozen_evidence=evidence,
        destination=tmp_path/"acceptance-delivery.json")
    package=produced["artifact"]["package"]
    assert validate_runtime_contract(package)==[]
    from quant_crypto.application.btc_registered_candidate import registered_protection_policy
    assert registered_protection_policy(package).validate()==[]
    damaged=json.loads(json.dumps(package));damaged["model"]["text"]+="tamper"
    assert "model_hash_mismatch" in validate_runtime_contract(damaged)
    damaged=json.loads(json.dumps(package));damaged["contracts"]["position"]["max_weight"]=.2
    assert "frozen_policy_binding_mismatch" in validate_runtime_contract(damaged)
    damaged=json.loads(json.dumps(package));damaged["contracts"]["time"]["temporal_receipt"]["operation_order"].reverse()
    assert "temporal_receipt_v2_invalid" in validate_runtime_contract(damaged)


@pytest.mark.parametrize("symbols,market,calendar", [(["AAPL","MSFT","SPY"],"us_equity","XNYS"),
    (["000001","600000","000002"],"cn_equity","XSHG")])
def test_generic_immutable_panel_export_preserves_market_identity_and_seal(tmp_path,monkeypatch,symbols,market,calendar):
    """Synthetic resolver fixture, real typed export/provider/seals; not market-data acceptance."""
    import json
    import integrations.qlib_adapter.factory_data as module
    import tools.agent_governance.shared_data as shared
    source=tmp_path/"immutable-fixture";source.mkdir()
    times=pd.date_range("2020-01-01",periods=100,freq="B",tz="UTC")
    idx=pd.MultiIndex.from_product([times,symbols],names=["event_time","instrument"])
    panel=idx.to_frame(index=False)
    panel["available_time"]=panel.event_time+pd.Timedelta(minutes=1)
    panel["decision_time"]=panel.event_time+pd.Timedelta(minutes=2)
    for key,value in {"open":100.,"high":102.,"low":99.,"close":101.,"volume":100.}.items():panel[key]=value
    panel.to_parquet(source/"panel.parquet",index=False)
    panel[["event_time","decision_time"]].drop_duplicates().to_parquet(source/"calendar.parquet",index=False)
    write_json(source/"quality.json",{"market":market,"calendar":calendar,**{key:True for key in
        ("complete_calendar","pit_universe","pit_adjustment","available_time_verified")}})
    manifest={"dataset_id":"fixture","dataset_version":"synthetic-v1","aggregate_sha256":"c"*64}
    raw_manifest=json.dumps(manifest).encode()
    original_check_output=module.subprocess.check_output
    monkeypatch.setattr(module.subprocess,"check_output",lambda args,**kwargs: raw_manifest if args[:2]==["git","show"] else original_check_output(args,**kwargs))
    monkeypatch.setattr(shared,"load_manifest_from_git",lambda *a,**k:manifest)
    monkeypatch.setattr(shared,"resolve_manifest_payload",lambda *a,**k:source)
    profile=module.validate_registered_profile({"profile_id":"fixture-"+market,"market":market,"asset_class":"equity",
        "bar_size":"1d","metric_mode":"cross_sectional","calendar":calendar,"symbols":symbols,"data_mode":"immutable_panel",
        "data_version":"synthetic-v1","label":"synthetic only","source":"synthetic_fixture","label_horizon":5,"entry_delay":1,
        "annualization":252,"cost_scenarios_bps":{"base":10,"conservative":20,"stress":30},
        "data_binding":{**manifest,"manifest_path":".agent/data_manifests/fixture.json",
            "manifest_sha256":hashlib.sha256(raw_manifest).hexdigest(),"files":{name:{"path":path.name,
                "sha256":hashlib.sha256(path.read_bytes()).hexdigest()} for name,path in
                {"panel":source/"panel.parquet","calendar":source/"calendar.parquet","quality":source/"quality.json"}.items()}}})
    actual,lineage=module.load_factory_input(profile,qlib_root=tmp_path/"qlib",input_run_id="export-fixture")
    assert set(actual.index.get_level_values("instrument"))==set(symbols) and len(actual)==300
    assert lineage["calendar"]==calendar and lineage["data_version"]=="synthetic-v1"
    root=tmp_path/"qlib/export-fixture"
    assert read_sealed_evidence(root)["integrity_status"]=="passed"
    assert (root/"qlib_provider/instruments/all.txt").read_text(encoding="utf-8").splitlines()[0].split("\t")[0] in symbols
    (root/"qlib_input/factory_panel.parquet").write_bytes(b"tampered")
    with pytest.raises(module.FactoryError,match="seal_invalid"):
        module.read_factory_input(profile,qlib_root=tmp_path/"qlib",input_run_id="export-fixture")
