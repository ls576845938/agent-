from copy import deepcopy
from pathlib import Path
import hashlib
import importlib
import json

import numpy as np
import pandas as pd
import pytest

from integrations.qlib_adapter.schemas import QlibAdapterError, load_yaml_file, write_json, build_run_paths
from integrations.qlib_adapter.market_data import normalize_hourly_input, normalize_funding_input, bind_instrument_identity, validate_instrument_metadata
from integrations.qlib_adapter.build_qlib_dataset import _build_native_file_provider
from integrations.qlib_adapter.profiles import REPO, resolve_pipeline_request
from integrations.qlib_adapter.time_series_evaluation import validate_time_series_config
from integrations.qlib_adapter.research_pipeline import read_sealed_evidence, seal_run, run_research_pipeline
from integrations.qlib_adapter.research_trace import reconcile_research_ledger


def hourly_fixture():
    times = pd.date_range("2026-01-01", periods=48, freq="h", tz="UTC")
    return pd.DataFrame({"event_time": times, "available_time": times + pd.Timedelta(hours=1),
        "symbol": "BTC-USDT-SWAP", "confirm": 1, "open": 100., "close": 101.,
        "high": 102., "low": 99., "volume_base": 3.})


def immutable_identity_fixture(kind="bars"):
    rows = hourly_fixture()
    if kind == "funding":
        rows = rows.iloc[::8].copy()
        rows["fundingRate"] = .0001
        rows["instId"] = "BTC-USDT-SWAP"
    if kind == "premium":
        rows["mark_close"], rows["index_close"] = 101., 100.
    prefix = {"bars": "okx", "mark": "okx-mark", "premium": "okx-premium", "funding": "okx-funding"}[kind]
    rows["symbol"] = "BTCUSDT"
    rows["source_record_id"] = rows.event_time.map(lambda stamp: f"{prefix}:BTC-USDT-SWAP:{stamp.value // 1_000_000}")
    return rows


def instrument_metadata_fixture():
    return {"symbol": "BTCUSDT", "venue_symbol": "BTC-USDT-SWAP", "raw_symbol_info": {
        "instId": "BTC-USDT-SWAP", "instType": "SWAP", "ctType": "linear", "settleCcy": "USDT"}}


@pytest.mark.parametrize("kind", ["bars", "mark", "premium", "funding"])
def test_immutable_identity_mapping_preserves_original_lineage(kind):
    rows = immutable_identity_fixture(kind)
    original = rows.copy(deep=True)
    validate_instrument_metadata(instrument_metadata_fixture(), canonical_symbol="BTCUSDT", instrument="BTC-USDT-SWAP")
    bound = bind_instrument_identity(rows, canonical_symbol="BTCUSDT", instrument="BTC-USDT-SWAP", kind=kind)
    result = normalize_funding_input(bound, symbol="BTC-USDT-SWAP") if kind == "funding" else normalize_hourly_input(bound, symbol="BTC-USDT-SWAP", kind=kind)
    assert result.symbol.eq("BTC-USDT-SWAP").all() and result.source_symbol.eq("BTCUSDT").all()
    assert result.source_record_id.equals(rows.source_record_id)
    pd.testing.assert_frame_equal(rows, original)


@pytest.mark.parametrize("corruption", ["spot", "mixed", "prefix", "event_ms", "raw_symbol", "missing_identity", "unfinalized"])
def test_immutable_identity_mapping_rejects_false_instrument_or_finality(corruption):
    rows = immutable_identity_fixture()
    if corruption in {"spot", "mixed"}:
        rows.loc[0, "source_record_id"] = rows.loc[0, "source_record_id"].replace("BTC-USDT-SWAP", "BTC-USDT" if corruption == "spot" else "ETH-USDT-SWAP")
    elif corruption == "prefix":
        rows.loc[0, "source_record_id"] = rows.loc[0, "source_record_id"].replace("okx:", "okx-mark:")
    elif corruption == "event_ms":
        rows.loc[0, "source_record_id"] += "0"
    elif corruption == "raw_symbol":
        rows.loc[0, "symbol"] = "BTC-USDT-SWAP"
    elif corruption == "missing_identity":
        rows = rows.drop(columns="source_record_id")
    else:
        rows.loc[0, "confirm"] = 0
    with pytest.raises(QlibAdapterError):
        bound = bind_instrument_identity(rows, canonical_symbol="BTCUSDT", instrument="BTC-USDT-SWAP", kind="bars")
        normalize_hourly_input(bound, symbol="BTC-USDT-SWAP")


@pytest.mark.parametrize("field", ["symbol", "venue_symbol", "instId", "instType", "ctType", "settleCcy"])
def test_immutable_instrument_metadata_rejects_wrong_contract(field):
    metadata = instrument_metadata_fixture()
    (metadata if field in {"symbol", "venue_symbol"} else metadata["raw_symbol_info"])[field] = "wrong"
    with pytest.raises(QlibAdapterError, match="metadata identity/type"):
        validate_instrument_metadata(metadata, canonical_symbol="BTCUSDT", instrument="BTC-USDT-SWAP")


def test_funding_requires_matching_venue_instrument():
    rows = immutable_identity_fixture("funding")
    rows.loc[0, "instId"] = "BTC-USDT"
    with pytest.raises(QlibAdapterError, match="identity mismatch"):
        bind_instrument_identity(rows, canonical_symbol="BTCUSDT", instrument="BTC-USDT-SWAP", kind="funding")


@pytest.mark.parametrize("corruption", ["hash", "path"])
def test_immutable_instrument_metadata_hash_and_containment(monkeypatch, tmp_path, corruption):
    from integrations.qlib_adapter.schemas import load_universe_config
    from integrations.qlib_adapter.market_data import export_immutable_input
    import tools.agent_governance.shared_data as shared
    module = importlib.import_module("integrations.qlib_adapter.market_data")
    universe = load_universe_config(REPO/"configs/universe/okx_btc_perpetual_1h.yaml")
    universe.data_binding["manifest_sha256"] = hashlib.sha256(b"fixture").hexdigest()
    monkeypatch.setattr(module.subprocess,"check_output",lambda *a,**kw:b"fixture")
    monkeypatch.setattr(shared,"load_manifest_from_git",lambda *a,**kw:{
        "dataset_id":universe.data_binding["dataset_id"],"dataset_version":universe.data_binding["dataset_version"],
        "aggregate_sha256":universe.data_binding["aggregate_sha256"]})
    monkeypatch.setattr(shared,"resolve_manifest_payload",lambda *a,**kw:tmp_path)
    write_json(tmp_path/"exchange_info.json",instrument_metadata_fixture())
    universe.data_binding["instrument_metadata"]["sha256"] = "0"*64
    if corruption == "path":
        universe.data_binding["instrument_metadata"]["path"] = "../exchange_info.json"
    with pytest.raises(QlibAdapterError,match="metadata hash/path"):
        export_immutable_input(universe=universe,start_date="2026-01-01",end_date="2026-01-02",
            data_version=universe.data_binding["dataset_version"],run_id="metadata-test",
            artifacts_root=tmp_path/"output",requested_source="okx")
    assert not (tmp_path/"output").exists()


@pytest.mark.parametrize("corruption", ["duplicate", "gap", "future", "unfinalized", "price"])
def test_hourly_input_rejects_invalid_facts(corruption):
    rows = hourly_fixture()
    if corruption == "duplicate":
        rows.loc[1, "event_time"] = rows.loc[0, "event_time"]
    elif corruption == "gap":
        rows = rows.drop(index=5)
    elif corruption == "future":
        rows.loc[2, "available_time"] = rows.loc[2, "event_time"]
    elif corruption == "unfinalized":
        rows.loc[3, "confirm"] = 0
    else:
        rows.loc[5, "close"] = np.inf
    with pytest.raises(QlibAdapterError):
        normalize_hourly_input(rows, symbol="BTC-USDT-SWAP")


def test_native_provider_keeps_weekend_and_60min(tmp_path):
    frame = normalize_hourly_input(hourly_fixture(), symbol="BTC-USDT-SWAP")
    path = tmp_path / "input.parquet"
    frame.to_parquet(path)
    provider = tmp_path / "provider"
    manifest = {"calendar": {"trading_days": frame.date.tolist(), "qlib_freq": "60min"},
        "symbols_exported": ["BTC-USDT-SWAP"], "files": {"daily_bars_parquet": str(path)}}
    _build_native_file_provider(dataset_manifest=manifest, provider_dir=provider)
    assert len((provider / "calendars/60min.txt").read_text().splitlines()) == 48
    assert not (provider / "calendars/day.txt").exists()
    assert np.fromfile(provider / "features/btc-usdt-swap/close.60min.bin", dtype="<f4").shape == (49,)
    with pytest.raises(QlibAdapterError, match="overwrite"):
        _build_native_file_provider(dataset_manifest=manifest, provider_dir=provider)


def test_profile_is_exact_and_research_only():
    profile = resolve_pipeline_request({"profile_id": "okx_btc_trend_1h", "run_id": "fixture"})
    assert profile["source"] == "okx" and profile["bar_size"] == "1h"
    for payload in ({"order": True}, {"config": "/tmp/evil.yaml"}, {"data_version": "latest"}, {"run_id": "../escape"}):
        with pytest.raises(QlibAdapterError):
            resolve_pipeline_request({"profile_id": "okx_btc_trend_1h", **payload})


def test_workflow_global_context_is_single_writer():
    module = importlib.import_module("integrations.qlib_adapter.run_qlib_workflow")
    module._WORKFLOW_LOCK.acquire()
    try:
        with pytest.raises(QlibAdapterError,match="concurrent"):
            module.run_qlib_workflow(config_path=REPO/"configs/qlib/okx_btc_trend_1h.yaml",run_id="unused")
    finally:
        module._WORKFLOW_LOCK.release()


def test_time_split_requires_purge_and_final_label_coverage():
    config = load_yaml_file(REPO / "configs/qlib/okx_btc_trend_1h.yaml")
    calendar = pd.date_range(config["data"]["start_date"], config["data"]["end_date"], freq="h")
    manifest = {"calendar": {"trading_days": calendar.astype(str).tolist()},
        "input_contract": {"asset_class": "crypto", "bar_size": "1h"}}
    validate_time_series_config(config, manifest)
    bad = deepcopy(config)
    bad["task"]["dataset"]["kwargs"]["segments"]["valid"][0] = "2026-04-29 01:00:00"
    with pytest.raises(QlibAdapterError, match="purge"):
        validate_time_series_config(bad, manifest)
    bad = deepcopy(config)
    bad["task"]["dataset"]["kwargs"]["segments"]["test"][1] = config["data"]["end_date"]
    with pytest.raises(QlibAdapterError, match="Final test"):
        validate_time_series_config(bad, manifest)
    bad = deepcopy(config)
    bad["model"]["label"] = "Ref($open, -200) / Ref($open, -2) - 1"
    bad["task"]["dataset"]["kwargs"]["handler"]["kwargs"]["data_loader"]["kwargs"]["config"]["label"][0][0] = bad["model"]["label"]
    with pytest.raises(QlibAdapterError, match="actual offsets"):
        validate_time_series_config(bad, manifest)


def test_read_seal_is_readonly_and_tampering_blocks(tmp_path):
    missing = tmp_path / "missing"
    assert read_sealed_evidence(missing)["integrity_status"] == "unknown"
    assert not missing.exists()
    root = tmp_path / "run"
    write_json(root / "pipeline_result.json", {"run_id": "run", "status": "completed"})
    seal_run(root)
    assert read_sealed_evidence(root)["integrity_status"] == "passed"
    write_json(root / "pipeline_result.json", {"run_id": "other"})
    assert read_sealed_evidence(root)["integrity_status"] == "blocked"


def test_unsealed_fact_cannot_be_appended_to_sealed_run(tmp_path):
    root = tmp_path/"run"
    write_json(root/"pipeline_result.json",{"run_id":"run","status":"completed"})
    seal_run(root)
    write_json(root/"recorder_metrics.json",{"id":"unsealed"})
    assert read_sealed_evidence(root)["integrity_status"] == "blocked"


def test_immutable_manifest_aggregate_binding_is_required(monkeypatch,tmp_path):
    from integrations.qlib_adapter.schemas import load_universe_config
    from integrations.qlib_adapter.market_data import export_immutable_input
    import tools.agent_governance.shared_data as shared
    module = importlib.import_module("integrations.qlib_adapter.market_data")
    universe = load_universe_config(REPO/"configs/universe/okx_btc_perpetual_1h.yaml")
    universe.data_binding["manifest_sha256"] = hashlib.sha256(b"fixture").hexdigest()
    monkeypatch.setattr(module.subprocess,"check_output",lambda *a,**kw:b"fixture")
    monkeypatch.setattr(shared,"load_manifest_from_git",lambda *a,**kw:{
        "dataset_id":universe.data_binding["dataset_id"],"dataset_version":universe.data_binding["dataset_version"],
        "aggregate_sha256":"0"*64})
    with pytest.raises(QlibAdapterError,match="aggregate hash"):
        export_immutable_input(universe=universe,start_date="2026-01-01",end_date="2026-01-02",
            data_version=universe.data_binding["dataset_version"],run_id="aggregate-test",
            artifacts_root=tmp_path,requested_source="okx")
    assert not (tmp_path/"aggregate-test").exists()


def test_pipeline_failure_does_not_call_downstream(monkeypatch, tmp_path):
    from integrations.qlib_adapter.schemas import BuildQlibDatasetResult
    module = importlib.import_module("integrations.qlib_adapter.build_qlib_dataset")
    monkeypatch.setattr(module, "build_qlib_dataset", lambda **kw: BuildQlibDatasetResult(
        kw["run_id"], "failed", "", "", "", "", "fixture_missing_data"))
    with pytest.raises(QlibAdapterError, match="dataset"):
        run_research_pipeline({"profile_id": "okx_btc_trend_1h", "run_id": "failed-run"}, artifacts_root=tmp_path)
    receipt = json.loads((tmp_path / "failed-run/pipeline_result.json").read_text())
    assert receipt["stages"]["training"]["status"] == "not_run"
    assert receipt["status"] == "failed" and not receipt["order"]
    with pytest.raises(QlibAdapterError, match="already exists"):
        run_research_pipeline({"profile_id": "okx_btc_trend_1h", "run_id": "failed-run"}, artifacts_root=tmp_path)


def test_ledger_reconciliation_is_derived_from_fills_and_cash():
    rows = [
        {"kind": "fill", "quantity_delta": 1., "price": 100., "fee_rate": .001,
            "cash_after": 999.9, "position_after": 1., "mark": 102., "equity_after": 1001.9},
        {"kind": "funding", "valuation_mark": 102., "rate": .01, "cash_delta": -1.02,
            "cash_after": 998.88, "position_after": 1., "mark": 103., "equity_after": 1001.88},
        {"kind": "fill", "quantity_delta": -1., "price": 110., "fee_rate": .001,
            "cash_after": 1008.77, "position_after": 0., "mark": 110., "equity_after": 1008.77},
    ]
    assert reconcile_research_ledger(rows, 1000)["status"] == "passed"
    rows[-1]["cash_after"] += 1
    assert reconcile_research_ledger(rows, 1000)["status"] == "blocked"


@pytest.mark.parametrize("force_reduction", [False, True])
def test_real_qlib_60min_training_and_domain_replay_on_synthetic_fixture(tmp_path, monkeypatch, force_reduction):
    """Runs installed Qlib/LightGBM, never claims this fixture is market evidence."""
    import yaml
    from integrations.qlib_adapter.run_qlib_workflow import run_qlib_workflow
    from integrations.qlib_adapter.import_pred_score import import_pred_score
    from integrations.qlib_adapter.research_trace import build_research_trace
    from integrations.qlib_adapter.compile_qlib_strategy_manifest import compile_qlib_strategy_manifest
    run_id = "synthetic-engine-test"
    paths = build_run_paths(run_id, tmp_path)
    paths.qlib_input_dir.mkdir(parents=True)
    config = load_yaml_file(REPO / "configs/qlib/okx_btc_trend_1h.yaml")
    times = pd.date_range(config["data"]["start_date"], config["data"]["end_date"], freq="h", tz="UTC")
    rng = np.random.default_rng(17)
    close = 50000 * np.exp(np.cumsum(.0002*np.sin(np.arange(len(times))/50) + rng.normal(0,.001,len(times))))
    raw = pd.DataFrame({"event_time": times, "available_time": times+pd.Timedelta(hours=1),
        "symbol": "BTC-USDT-SWAP", "confirm": 1, "open": close*.9998, "high": close*1.01,
        "low": close*.99, "close": close, "volume_base": rng.uniform(50,100,len(times))})
    bars = normalize_hourly_input(raw, symbol="BTC-USDT-SWAP")
    frames = {"daily_bars_parquet": bars, "mark": bars,
        "premium": pd.DataFrame({"event_time":times,"index_close":close*.9999}),
        "funding": pd.DataFrame({"event_time":times[::8],"available_time":times[::8],"fundingRate":.0001})}
    files, hashes = {}, {}
    for name,frame in frames.items():
        path = paths.qlib_input_dir / (name+".parquet")
        frame.to_parquet(path,index=False)
        files[name],hashes[name] = str(path),hashlib.sha256(path.read_bytes()).hexdigest()
    manifest = {"run_id":run_id,"status":"completed","symbols_exported":["BTC-USDT-SWAP"],
        "universe":{"universe_id":"synthetic-test"}, "calendar":{"trading_days":bars.date.tolist(),"qlib_freq":"60min"},
        "input_contract":{"asset_class":"crypto","bar_size":"1h","data_version_request":"SYNTHETIC"},
        "source_manifests":[{"symbol":"BTC-USDT-SWAP","data_version":"SYNTHETIC"}],"files":files,"file_hashes":hashes}
    write_json(paths.qlib_input_dir / "dataset_manifest.json",manifest)
    _build_native_file_provider(dataset_manifest=manifest,provider_dir=paths.qlib_provider_dir)
    write_json(paths.run_root / "provider_manifest.json",{"run_id":run_id,"status":"completed"})
    config_path = tmp_path / "test_config.yaml"
    if force_reduction:
        config["research_simulation"]["maximum_holding_bars"] = 1
    config_path.write_text(yaml.safe_dump(config),encoding="utf-8")
    result = run_qlib_workflow(config_path=config_path,run_id=run_id,artifacts_root=tmp_path)
    assert result.status == "completed", result.error
    assert import_pred_score(run_id=run_id,artifacts_root=tmp_path).status == "completed"
    predictions = pd.read_parquet(paths.run_root / "research_model_scores.parquet")
    assert len(predictions)>1000 and predictions["rank"].isna().all()
    assert np.isfinite(predictions.score).all()
    with pytest.raises(QlibAdapterError,match="immutable"):
        run_qlib_workflow(config_path=config_path,run_id=run_id,artifacts_root=tmp_path)
    # Inject explicitly synthetic, pre-test calibration/scores to exercise nonflat replay.
    predictions["score"] = .006 * np.sign(np.sin(np.arange(len(predictions))/48)+.01)
    predictions.to_parquet(paths.run_root / "research_model_scores.parquet",index=False)
    evaluation = json.loads((paths.run_root / "signal_evaluation.json").read_text())
    assert evaluation["calibrated_test"]["sample_size"] == len(predictions)
    evaluation["calibration"].update({"slope":1.0,"intercept":0.0,"quality_passed":True,
        "quality":{"time_series_ic":.3,"direction_hit_rate":.7,"sample_size":697}})
    write_json(paths.run_root / "signal_evaluation.json",evaluation)
    compile_qlib_strategy_manifest(run_id=run_id,config_path=config_path,artifacts_root=tmp_path)
    if force_reduction:
        from dataclasses import replace
        import quant_crypto.risk as risk_module
        original_assess = risk_module.assess_btc_risk
        def forced_loss_assessment(**kwargs):
            assessed = original_assess(**kwargs)
            return replace(assessed, approved=False, status="blocked", requires_reduction=True,
                max_safe_quantity=0.0, blockers=("fixture_forced_daily_loss",)) if kwargs["position_before"] else assessed
        monkeypatch.setattr(risk_module, "assess_btc_risk", forced_loss_assessment)
    trace = build_research_trace(run_id=run_id,artifacts_root=tmp_path)
    assert trace["decision_count"] == len(predictions)
    assert trace["simulated_fill_count"] > 0
    assert trace["reconciliation"]["status"] == "passed"
    assert trace["reconciliation"]["position"] == 0
    assert trace["status"] == "research_flow_completed"
    assert trace["execution_permission"] is False and trace["runtime_observed"] is False
    decision = json.loads((paths.run_root/"research_decisions.jsonl").read_text().splitlines()[0])
    assert decision["layers"]["alpha"]["truth_kind"] == "research_derived"
    assert decision["layers"]["execution"]["truth_kind"] == "research_simulated"
    assert decision["layers"]["allocation"]["production_perpetual_sizing_ready"] is False
    assert decision["layers"]["alpha"]["quality_evidence_sha256"] == hashlib.sha256((paths.run_root/"signal_evaluation.json").read_bytes()).hexdigest()
    events = [json.loads(line) for line in (paths.run_root/"research_ledger.jsonl").read_text().splitlines()]
    assert all(row["truth_kind"] == "research_simulated" for row in events)
    if force_reduction:
        all_decisions = [json.loads(line) for line in (paths.run_root/"research_decisions.jsonl").read_text().splitlines()]
        first_exit = next(row for row in all_decisions if row["layers"]["execution"]["research_reduce_only"])
        assert first_exit["layers"]["execution"]["status"] == "passed", "Repeated exits must not postpone the first safe pending reduction"
        assert pd.Timestamp(first_exit["layers"]["execution"]["fill_time"]) == pd.Timestamp(first_exit["decision_time"])+pd.Timedelta(hours=1)
    candidate_path = paths.run_root/"qlib_strategy_manifest.json"
    candidate = json.loads(candidate_path.read_text())
    assert trace["identity"]["candidate_id"] == candidate["candidate_id"] == candidate["manifest_id"]
    write_json(candidate_path,{**candidate,"run_id":"wrong-run"})
    with pytest.raises(QlibAdapterError,match="candidate identity"):
        build_research_trace(run_id=run_id,artifacts_root=tmp_path)
    write_json(candidate_path,candidate)
    sealed = seal_run(paths.run_root)
    assert read_sealed_evidence(paths.run_root)["integrity_status"] == "passed"
    with pytest.raises(QlibAdapterError,match="immutable"):
        import_pred_score(run_id=run_id,artifacts_root=tmp_path)
