from copy import deepcopy
import random

import numpy as np
import pandas as pd
import pytest

from quant_shared.alpha_factory.contracts import FactorSpec, FactoryError, validate_expression, validate_budget
from quant_shared.alpha_factory.evaluation import (validate_panel, split_plan, forward_labels, segment,
    evaluate_expression, signal_metrics, select_decorrelated, nomination_gate, by_fdr, purged_selection_folds)
from quant_shared.alpha_factory.search import search_factors
from integrations.qlib_adapter.factory_data import align_available_field, market_profiles
from integrations.qlib_adapter.factory_factors import crossover, build_primitives, seed_factors


def fixture_panel(symbols=("BTC",), frequency="h", size=2200):
    rng = np.random.default_rng(42)
    times = pd.date_range("2021-01-01", periods=size, freq=frequency, tz="UTC")
    parts = []
    for index, symbol in enumerate(symbols):
        returns = .002 * np.sin(np.arange(size) / 30 + index) + rng.normal(0, .001, size)
        close = 100 * np.exp(returns.cumsum())
        parts.append(pd.DataFrame({"datetime": times, "instrument": symbol, "open": close * .999,
            "high": close * 1.01, "low": close * .99, "close": close, "volume": 100 + rng.uniform(0, 100, size)}))
    return validate_panel(pd.concat(parts))


@pytest.mark.parametrize("override", [{"private": True}, {"market": "crypto"}, {"data_root": "other"},
    {"population": True}, {"population": 0}, {"generations": 5}, {"model_trials": 99},
    {"seed": float("nan")}, {"generators": ["python"]}, {"generators": [["genetic"]]}])
def test_budget_and_permission_overrides_fail_closed(override):
    with pytest.raises(FactoryError): validate_budget({"profile_id": "okx_btc_trend_1h", **override})


def test_real_acceptance_profile_freezes_registered_only_budget():
    from quant_shared.alpha_factory.contracts import REAL_ACCEPTANCE_PROFILE
    value=validate_budget({"profile_id":"okx_btc_trend_1h","acceptance_profile":REAL_ACCEPTANCE_PROFILE})
    assert {key:value[key] for key in ("seed","max_features","model_trials","generators")}=={
        "seed":17,"max_features":6,"model_trials":1,"generators":["registered"]}
    for override in ({"seed":18},{"max_features":5},{"model_trials":2},{"generators":["template"]}):
        with pytest.raises(FactoryError,match="fixed_budget_mismatch"):
            validate_budget({"profile_id":"okx_btc_trend_1h","acceptance_profile":REAL_ACCEPTANCE_PROFILE,**override})


def test_real_acceptance_keeps_full_research_split_and_covers_fixed_48_offline_decisions():
    from quant_shared.alpha_factory.engine import _validate_real_acceptance_offline_window
    times=pd.date_range("2025-12-22T01:00:00Z",periods=5280,freq="h")
    index=pd.MultiIndex.from_product([times,["BTC-USDT-SWAP"]],names=["datetime","instrument"])
    plan=split_plan(index,horizon=12,delay=2)
    _validate_real_acceptance_offline_window(index,plan)
    assert plan["method"]=="purged_chronological_four_way"
    assert plan["segments"]=={
        "train":["2025-12-22T01:00:00+00:00","2026-04-10T09:00:00+00:00"],
        "valid":["2026-04-11T01:00:00+00:00","2026-05-13T09:00:00+00:00"],
        "selection":["2026-05-14T01:00:00+00:00","2026-06-15T09:00:00+00:00"],
        "audit":["2026-06-16T01:00:00+00:00","2026-07-29T09:00:00+00:00"]}
    assert len(times[(times>=pd.Timestamp("2026-06-16T01:00:00Z")) &
        (times<pd.Timestamp("2026-06-18T01:00:00Z"))])==48


@pytest.mark.parametrize("node", [{"op": "eval", "value": "__import__('os')"},
    {"op": "primitive", "primitive": "open_interest"}, {"op": "const", "value": float("inf")},
    {"op": "rolling_z", "window": -5, "args": [{"op":"primitive","primitive":"close"}]}])
def test_ast_rejects_unavailable_unsafe_or_future_operators(node):
    with pytest.raises(FactoryError): validate_expression(node, {"close"})


@pytest.mark.parametrize("frequency,symbols", [("h", ("BTC",)), ("B", ("SPY", "QQQ", "TLT")), ("B", ("000001", "600000", "000002"))])
def test_market_neutral_bar_splits_and_label_purge(frequency, symbols):
    panel = fixture_panel(symbols, frequency)
    plan = split_plan(panel.index, horizon=5, delay=2)
    labels = forward_labels(panel, plan)
    calendar = panel.index.get_level_values("datetime").unique()
    windows = [plan["segments"][name] for name in ("train", "valid", "selection", "audit")]
    for left, right in zip(windows, windows[1:]):
        assert calendar.get_loc(pd.Timestamp(left[1])) + 7 < calendar.get_loc(pd.Timestamp(right[0]))
    for fold in purged_selection_folds(panel.index, plan):
        assert pd.Timestamp(fold["train"][1]) < pd.Timestamp(fold["valid"][0]) < pd.Timestamp(fold["test"][0])
        for a,b in (("train","valid"),("valid","test")):
            assert calendar.get_loc(pd.Timestamp(fold[a][1])) + 7 < calendar.get_loc(pd.Timestamp(fold[b][0]))
    symbol = symbols[0]
    raw = panel.xs(symbol, level="instrument")
    assert labels.xs(symbol, level="instrument").iloc[4] == pytest.approx(raw.open.iloc[11] / raw.open.iloc[6] - 1)


def test_late_derivative_data_cannot_rewrite_historical_factor():
    panel = fixture_panel(size=10)
    timestamps = panel.index.get_level_values("datetime")
    rows = pd.DataFrame({"event_time":[timestamps[0]], "available_time":[timestamps[5]], "fundingRate":[.001]})
    joined = align_available_field(panel, rows, "fundingRate")
    assert joined.iloc[:5].isna().all()
    assert joined.iloc[5:].eq(.001).all()
    rows.loc[0,"available_time"] = timestamps[7]
    assert align_available_field(panel, rows, "fundingRate").iloc[:7].isna().all()


def test_real_turnover_and_metric_modes_are_not_interchangeable():
    from quant_shared.alpha_factory.evaluation import effective_temporal_samples
    panel = fixture_panel(("A","B","C"), size=120)
    values = pd.Series(np.tile([-1.,0,1.], 120), index=panel.index)
    values.iloc[30:60] *= -1
    metrics = signal_metrics(values, values * .01, "cross_sectional")
    assert metrics["rank_ic"] == pytest.approx(1)
    assert metrics["factor_signal_turnover"] > 0
    single = values.xs("A",level="instrument",drop_level=False)
    assert signal_metrics(single, single * .01, "cross_sectional")["ic"] is None
    assert signal_metrics(single, single * .01, "time_series")["ic"] is not None
    plan={"horizon_bars":5,"entry_delay_bars":1}
    assert effective_temporal_samples(values.index,plan)==effective_temporal_samples(single.index,plan)==20


def test_future_mutation_does_not_change_generation_features_or_train_selection():
    panel = fixture_panel()
    plan = split_plan(panel.index, horizon=12, delay=2)
    altered = panel.copy()
    audit_start = pd.Timestamp(plan["segments"]["audit"][0])
    mask = altered.index.get_level_values("datetime") >= audit_start
    altered.loc[mask, ["open","high","low","close"]] *= 3
    a, _ = build_primitives(panel, bar_size="1h", annualization=8760)
    b, _ = build_primitives(altered, bar_size="1h", annualization=8760)
    pd.testing.assert_frame_equal(segment(a,plan,"train"), segment(b,plan,"train"))
    request = validate_budget({"seed":17,"population":4,"generations":1,"max_features":3})
    results = []
    for source, primitives in ((panel,a),(altered,b)):
        results.append(search_factors(segment(primitives,plan,"train"), segment(forward_labels(source,plan),plan,"train"),
            seed_factors(list(primitives),template_budget=4), request, mode="time_series", crossover=crossover))
    assert [spec.to_dict() for spec in results[0]["specs"]] == [spec.to_dict() for spec in results[1]["specs"]]
    assert results[0]["trials"] == results[1]["trials"]


def test_decorrelation_is_train_scoped_and_duplicate_trials_retained():
    panel = fixture_panel(size=600)
    x = pd.Series(np.sin(np.arange(len(panel))/30), index=panel.index)
    primitive = pd.DataFrame({"x":x,"y":-x})
    specs = [FactorSpec({"op":"primitive","primitive":name},"registered",name) for name in ("x","y","x")]
    request = validate_budget({"generators":["registered"],"max_features":3})
    result = search_factors(primitive,x*.01,specs,request,mode="time_series",crossover=crossover)
    assert len(result["trials"]) == 3 and result["trials"][-1]["reason"] == "duplicate_expression"
    assert len(result["selected"]) == 1
    assert result["selection_rejections"][0]["reason"].startswith("correlated_with:")


def test_historical_audit_never_creates_confirmatory_research_candidate():
    good = {"coverage":1,"block_count":4,"rank_ic":.1,"positive_block_fraction":1,"mse":.01,"zero_forecast_mse":.02}
    old = nomination_gate(good,good,observed_audit=True)
    assert old["status"] == "exploratory_nomination" and old["confirmatory_holdout"] is False
    assert nomination_gate(good,{**good,"rank_ic":-.1},observed_audit=True)["status"] == "rejected"
    assert by_fdr([.001,.04,None])[0] == pytest.approx(.0055)
    assert by_fdr([.001,.04,None])[2] is None


def test_missing_market_data_disables_profiles_without_invented_metrics():
    profiles = {p["profile_id"]:p for p in market_profiles()}
    assert profiles["okx_btc_trend_1h"]["metric_mode"] == "time_series"
    assert profiles["us_equity_daily"]["metric_mode"] == "cross_sectional"
    for name in ("us_equity_daily","cn_equity_daily","other_market"):
        assert profiles[name]["training_enabled"] is False and profiles[name]["blockers"]
    assert "open_interest" in profiles["okx_btc_trend_1h"]["unavailable_fields"]


@pytest.mark.parametrize("eligible", [True,False])
def test_full_engine_freezes_champion_before_audit_and_does_not_reselect_on_audit(monkeypatch,eligible):
    import quant_shared.alpha_factory.engine as engine
    from quant_shared.alpha_factory.engine import run_campaign
    from integrations.qlib_adapter.factory_trainer import MODEL_CATALOG
    panel = fixture_panel(size=4000)  # enough horizon-adjusted observations to pass the real sample floor
    profile = market_profiles()[0]
    primitives,catalog = build_primitives(panel,bar_size="1h",annualization=8760)
    request=validate_budget({"run_id":"engine-fixture","profile_id":profile["profile_id"],"population":4,"generations":1,"model_trials":2})
    # Isolate orchestration here; statistics and real Qlib fitting have their
    # own non-mocked tests. Both branches must conserve the audit boundary.
    monkeypatch.setattr(engine,"hac_p_value",lambda metrics:.001 if eligible else .9)
    monkeypatch.setattr(engine,"signal_metrics",lambda *a,**k:{"coverage":1,"block_count":4,"rank_ic":.1,
        "positive_block_fraction":1,"mse":.01,"zero_forecast_mse":.02})
    events, fits = [], []
    def emit(stage,status,detail):events.append((stage,status,detail))
    def trainer(**kwargs):
        fits.append(kwargs)
        start,end=map(pd.Timestamp,kwargs["segments"]["test"])
        index=kwargs["features"].index
        selected=(index.get_level_values("datetime")>=start)&(index.get_level_values("datetime")<=end)
        if kwargs["phase"]=="audit":
            assert any("frozen_champion" in detail for _,_,detail in events)
        score=(kwargs["features"].iloc[:,0].fillna(0)*.1).loc[selected]
        return score,{"qlib_run_id":"synthetic-"+str(len(fits)),"seal_sha256":"synthetic-fixture-not-real"}
    result=run_campaign(panel=panel,profile=profile,request=request,primitives=primitives,primitive_catalog=catalog,
        seed_specs=seed_factors(list(primitives),template_budget=4),crossover=crossover,model_catalog=MODEL_CATALOG,trainer=trainer,emit=emit)
    assert len(fits)==(9 if eligible else 8) and result["qlib_fit_count"]==len(fits),result["model_trials"]
    assert [fit["phase"] for fit in fits].count("audit")==int(eligible)
    assert all(trial["fit_used_audit"] is False for trial in result["model_trials"])
    if eligible:
        assert result["candidates"][0]["frozen_champion"]["audit_used_for_selection"] is False
        assert result["candidates"][0]["status"] in {"rejected","exploratory_nomination"}
    else:
        assert result["candidates"]==[] and result["audit_status"]=="not_run_selection_failed"
        assert result["decision"]=="rejected"
    assert result["promotion"] is False and result["runtime_observed"] is False


def registered_fixture_profile(symbols=("SPY","QQQ","TLT")):
    return {"profile_id":"test_daily","data_mode":"immutable_panel","metric_mode":"cross_sectional",
        "bar_size":"1d","asset_class":"equity","market":"us_equity","calendar":"XNYS","source":"synthetic_fixture",
        "label":"synthetic only","data_version":"fixture-v1","label_horizon":5,"entry_delay":1,"annualization":252,
        "symbols":list(symbols),"cost_scenarios_bps":{"base":10,"conservative":20,"stress":30},
        "data_binding":{"dataset_id":"fixture","dataset_version":"fixture-v1","manifest_path":".agent/data_manifests/fixture.json",
            "manifest_sha256":"a"*64,"aggregate_sha256":"b"*64,
            "files":{name:{"path":name+".parquet","sha256":"c"*64} for name in ("panel","calendar","quality")}}}


@pytest.mark.parametrize("override", [{"symbols":["../escape","QQQ","SPY"]}, {"symbols":["CON","QQQ","SPY"]},
    {"symbols":["spy","QQQ","SPY"]},{"cost_scenarios_bps":{"base":float("nan"),"conservative":20,"stress":30}}])
def test_shared_market_registry_rejects_unsafe_identity_and_cost(override):
    from integrations.qlib_adapter.factory_data import validate_registered_profile
    with pytest.raises(FactoryError):validate_registered_profile({**registered_fixture_profile(),**override})


def test_registered_market_cannot_self_authorize_confirmation_or_execution():
    from integrations.qlib_adapter.factory_data import validate_registered_profile
    from quant_shared.alpha_factory.contracts import SAFETY
    p=validate_registered_profile({**registered_fixture_profile(("000001","600000","000002")),
        "previously_observed_audit":False,**{key:True for key in SAFETY}})
    assert p["previously_observed_audit"] is True and all(p[key] is False for key in SAFETY)
    assert p["symbols"][0]=="000001" and p["round_trip_cost_bps"]==10


def test_immutable_panel_requires_each_complete_available_calendar_and_excludes_uncontracted_fields():
    from integrations.qlib_adapter.factory_data import validate_immutable_panel
    profile=registered_fixture_profile()
    raw=fixture_panel(tuple(profile["symbols"]),"B",100).reset_index().rename(columns={"datetime":"event_time"})
    raw["available_time"]=raw.event_time+pd.Timedelta(minutes=1)
    raw["decision_time"]=raw.event_time+pd.Timedelta(minutes=2)
    raw["open_interest"]=999  # No field-specific availability contract: not admitted.
    calendar=raw[["event_time","decision_time"]].drop_duplicates().sort_values("event_time")
    quality={key:True for key in ("complete_calendar","pit_universe","pit_adjustment","available_time_verified")}
    panel,_,_=validate_immutable_panel(raw,calendar,profile,quality)
    assert "open_interest" not in panel and len(panel)==300
    with pytest.raises(FactoryError,match="gap_compression"):
        validate_immutable_panel(raw.iloc[1:],calendar,profile,quality)
    delayed=raw.copy();delayed.loc[0,"available_time"]=delayed.loc[0,"decision_time"]+pd.Timedelta(seconds=1)
    with pytest.raises(FactoryError,match="not_available"):
        validate_immutable_panel(delayed,calendar,profile,quality)
    naive=raw.copy();naive["event_time"]=naive.event_time.dt.tz_localize(None)
    with pytest.raises(FactoryError,match="timezone_missing"):
        validate_immutable_panel(naive,calendar,profile,quality)
    with pytest.raises(FactoryError,match="attestation_missing"):
        validate_immutable_panel(raw,calendar,profile,{**quality,"pit_adjustment":False})
    double=raw.iloc[:6].copy()
    first=double.event_time.min()
    double.loc[double.event_time>first,"event_time"]=first+pd.Timedelta(hours=1)
    double["available_time"]=double.event_time+pd.Timedelta(minutes=1)
    double["decision_time"]=double.event_time+pd.Timedelta(minutes=2)
    cal=double[["event_time","decision_time"]].drop_duplicates()
    with pytest.raises(FactoryError,match="frequency_key_collision"):
        validate_immutable_panel(double,cal,profile,quality)
