"""Versioned market capabilities for the shared factory, with no downloads."""
from __future__ import annotations

import hashlib
import math
import re
import subprocess
from pathlib import Path

import pandas as pd

from quant_shared.alpha_factory.contracts import FactoryError, SAFETY, digest
from quant_shared.alpha_factory.evaluation import validate_panel
from .profiles import REPO, list_profiles
from .schemas import read_json, resolve_git_commit, write_json, load_yaml_file


def market_profiles() -> list[dict]:
    btc = next(p for p in list_profiles() if p["profile_id"] == "okx_btc_trend_1h")
    common = {"schema_version": "alpha_market_profile_v1", "training_engine": "qlib_lightgbm",
        "generation_modes": ["registered", "template", "genetic"], "previously_observed_audit": True,
        "nomination_rules": {"version": "research_nomination_v1", "primary_metric": "rank_ic",
            "minimum_rank_ic": .02, "minimum_coverage": .90, "minimum_effective_samples": 30,
            "minimum_folds": 4, "minimum_consistent_folds": 3, "fdr_method": "BY", "fdr_q": .10,
            "correlation_ceiling": .90}, **SAFETY}
    output = [
        {**common, "profile_id": "okx_btc_trend_1h", "label": "BTC · OKX 永续 / 1h",
            "market": "crypto", "asset_class": "crypto", "bar_size": "1h", "calendar": "UTC_24x7",
            "metric_mode": "time_series", "symbols": btc["symbols"], "annualization": 8760,
            "label_horizon": 12, "entry_delay": 2, "data_version": btc["data_version"],
            "data_mode": "existing_qlib_profile", "training_enabled": True, "blockers": [],
            "round_trip_cost_bps": 24.0, "cost_scenarios_bps": {"base": 24.0, "conservative": 36.0, "stress": 48.0},
            "cost_limitations": ["funding_requires_timestamped_trade_replay", "not_a_fill_cost_simulator"],
            "unavailable_fields": ["open_interest", "liquidation"],
            "data_limitations": ["historical_observed_audit", "reconstructed_availability_not_original_receipts"]},
        {**common, "profile_id": "us_equity_daily", "label": "美股 · 共享日线横截面",
            "market": "us_equity", "asset_class": "equity", "bar_size": "1d", "calendar": "XNYS",
            "metric_mode": "cross_sectional", "symbols": ["SPY", "QQQ", "IWM", "TLT"], "annualization": 252,
            "label_horizon": 5, "entry_delay": 1, "data_version": None, "data_mode": "sealed_panel",
            "training_enabled": False, "blockers": ["verified_daily_bundle_missing",
                "minute_bundle_insufficient_complete_session_cross_section", "point_in_time_adjustment_missing"],
            "data_limitations": ["no_silent_partial_minute_to_daily_aggregation"],
            "unavailable_fields": ["funding_rate", "open_interest", "liquidation"]},
        {**common, "profile_id": "cn_equity_daily", "label": "A 股 · 共享日线横截面",
            "market": "cn_equity", "asset_class": "equity", "bar_size": "1d", "calendar": "XSHG",
            "metric_mode": "cross_sectional", "symbols": [], "annualization": 252,
            "label_horizon": 5, "entry_delay": 1, "data_version": None, "data_mode": "sealed_panel",
            "training_enabled": False, "blockers": ["committed_cn_dataset_missing",
                "pit_universe_adjustment_suspension_and_market_rule_contract_required"],
            "unavailable_fields": ["funding_rate", "open_interest", "liquidation"]},
        {**common, "profile_id": "other_market", "label": "其他标的 · 扩展合同",
            "market": "other", "asset_class": "unknown", "bar_size": "unknown", "calendar": "unknown",
            "metric_mode": "unknown", "symbols": [], "data_version": None, "data_mode": "sealed_panel",
            "training_enabled": False, "blockers": ["market_calendar_label_cost_and_immutable_data_binding_required"]},
    ]
    registry = REPO / "configs/qlib/alpha_factory_markets.yaml"
    extensions = load_yaml_file(registry).get("profiles", []) if registry.exists() else []
    for configured in extensions:
        profile = validate_registered_profile({**common, **configured, **SAFETY})
        output = [item for item in output if item["profile_id"] != profile["profile_id"]]
        output.append(profile)
    for profile in output: profile["profile_hash"] = digest(profile)
    return output


def validate_registered_profile(profile: dict) -> dict:
    """Trusted, versioned registry extension; never an HTTP market override."""
    from .schemas import build_run_paths
    build_run_paths(profile.get("profile_id", ""))
    if profile.get("data_mode") != "immutable_panel": raise FactoryError("registered_profile_requires_immutable_panel")
    if profile.get("metric_mode") not in {"time_series", "cross_sectional"}: raise FactoryError("registered_metric_mode_invalid")
    if profile.get("bar_size") not in {"1d", "1h"}: raise FactoryError("registered_bar_size_not_supported")
    if profile.get("asset_class") not in {"equity", "crypto"}: raise FactoryError("registered_asset_class_invalid")
    for name in ("market", "calendar", "source", "data_version", "label"):
        if not isinstance(profile.get(name), str) or not profile[name] or profile[name] == "latest":
            raise FactoryError("registered_profile_missing:" + name)
    for name in ("label_horizon", "entry_delay", "annualization"):
        if type(profile.get(name)) is not int or profile[name] <= 0: raise FactoryError("registered_profile_invalid:" + name)
    symbols = profile.get("symbols")
    reserved = {"CON", "PRN", "AUX", "NUL", *[f"COM{i}" for i in range(1,10)], *[f"LPT{i}" for i in range(1,10)]}
    if (not isinstance(symbols,list) or not symbols or
        not all(isinstance(x,str) and re.fullmatch(r"[A-Z0-9][A-Z0-9_.-]{0,39}",x) and not x.endswith(".")
            and x.split(".")[0] not in reserved for x in symbols) or len(set(symbols)) != len(symbols)):
        raise FactoryError("registered_symbols_invalid")
    if profile["metric_mode"] == "cross_sectional" and len(symbols) < 3: raise FactoryError("cross_section_requires_three_symbols")
    if any(type(profile.get("cost_scenarios_bps", {}).get(key)) not in {float,int} or
        not math.isfinite(profile["cost_scenarios_bps"][key]) or profile["cost_scenarios_bps"][key] <= 0
        for key in ("base", "conservative", "stress")):
        raise FactoryError("registered_cost_contract_invalid")
    binding = profile.get("data_binding", {})
    for name in ("manifest_path", "manifest_sha256", "dataset_id", "dataset_version", "aggregate_sha256"):
        if not isinstance(binding.get(name),str) or not binding[name]: raise FactoryError("registered_binding_missing:" + name)
    if binding["dataset_version"] != profile["data_version"]: raise FactoryError("registered_data_version_mismatch")
    for name in ("manifest_sha256", "aggregate_sha256"):
        if not re.fullmatch(r"[a-f0-9]{64}",binding[name]): raise FactoryError("registered_binding_hash_invalid")
    for name in ("panel", "calendar", "quality"):
        item = binding.get("files",{}).get(name,{})
        if not isinstance(item.get("path"),str) or not item["path"] or not re.fullmatch(r"[a-f0-9]{64}",str(item.get("sha256",""))):
            raise FactoryError("registered_binding_file_invalid:" + name)
    # New registry entries remain historical/observed until an independent,
    # one-time confirmation authority is implemented; config cannot assert it.
    return {**profile, "round_trip_cost_bps": profile["cost_scenarios_bps"]["base"],
        "previously_observed_audit": True, "training_enabled": True, "blockers": [], **SAFETY}


def resolve_profile(profile_id: str) -> dict:
    profile = next((p for p in market_profiles() if p["profile_id"] == profile_id), None)
    if profile is None: raise FactoryError("unknown_factory_profile")
    if not profile["training_enabled"]: raise FactoryError("profile_blocked:" + ";".join(profile["blockers"]))
    return profile


def align_available_field(panel: pd.DataFrame, observations: pd.DataFrame, field: str, *, max_age="8h"):
    """Join by availability at EACH historical decision, never by final cutoff."""
    rows = observations.copy()
    for key in ("event_time", "available_time"):
        rows[key] = pd.to_datetime(rows[key], utc=True, errors="raise")
    if rows[["event_time", "available_time"]].isna().any().any() or (rows.available_time < rows.event_time).any():
        raise FactoryError("invalid_field_availability")
    if rows.available_time.duplicated().any(): raise FactoryError("ambiguous_field_availability")
    left = pd.DataFrame({"decision_time": panel.index.get_level_values("datetime")})
    result = pd.merge_asof(left, rows.sort_values("available_time"), left_on="decision_time",
        right_on="available_time", direction="backward", tolerance=pd.Timedelta(max_age))
    return pd.Series(pd.to_numeric(result[field], errors="coerce").to_numpy(), index=panel.index)


def load_factory_input(profile: dict, *, qlib_root: Path, input_run_id: str):
    from .build_qlib_dataset import build_qlib_dataset
    from .research_pipeline import seal_run
    if profile["data_mode"] == "immutable_panel":
        return _export_immutable_panel(profile, qlib_root=qlib_root, input_run_id=input_run_id)
    if profile["data_mode"] != "existing_qlib_profile": raise FactoryError("verified_market_input_adapter_not_bound")
    source = next(p for p in list_profiles() if p["profile_id"] == profile["profile_id"])
    result = build_qlib_dataset(universe_path=REPO / source["universe"], start_date=source["start_date"],
        end_date=source["end_date"], data_version=source["data_version"], run_id=input_run_id,
        artifacts_root=qlib_root, source=source["source"], asset_class=source["asset_class"], bar_size=source["bar_size"])
    if result.status != "completed": raise FactoryError("factory_input_export_failed:" + str(result.error))
    root = qlib_root / input_run_id
    pipeline = {"schema_version": "qlib_pipeline_v1", "run_id": input_run_id, "status": "dataset_only",
        "asset_class": profile["asset_class"], "bar_size": profile["bar_size"], "profile_id": profile["profile_id"],
        "source_head": resolve_git_commit(REPO), "factory_input_only": True, **SAFETY}
    write_json(root / "pipeline_result.json", pipeline)
    seal_run(root)
    return read_factory_input(profile, qlib_root=qlib_root, input_run_id=input_run_id)


def read_factory_input(profile: dict, *, qlib_root: Path, input_run_id: str):
    from .research_pipeline import read_sealed_evidence
    from .schemas import build_run_paths
    root = build_run_paths(input_run_id, qlib_root).run_root
    verified = read_sealed_evidence(root)
    if verified["integrity_status"] != "passed": raise FactoryError("factory_input_seal_invalid")
    manifest = read_json(root / "qlib_input/dataset_manifest.json")
    bar_path = root / "qlib_input/daily_bars.parquet"
    if hashlib.sha256(bar_path.read_bytes()).hexdigest() != manifest["input_sha256"]:
        raise FactoryError("factory_input_hash_mismatch")
    contract = manifest["input_contract"]
    if (contract["asset_class"] != profile["asset_class"] or contract["bar_size"] != profile["bar_size"] or
        contract["data_version_request"] != profile["data_version"]): raise FactoryError("factory_input_profile_identity_mismatch")
    if profile["data_mode"] == "immutable_panel":
        raw = pd.read_parquet(root / "qlib_input/factory_panel.parquet")
        panel = validate_panel(raw)
    else:
        raw = pd.read_parquet(bar_path)
        frame = raw.assign(datetime=raw.decision_time, instrument=raw.symbol)
        panel = validate_panel(frame[["datetime", "instrument", "open", "high", "low", "close", "volume"]])
        panel["funding_rate"] = align_available_field(panel,
            pd.read_parquet(root / "qlib_input/funding.parquet"), "fundingRate")
    return panel, {"input_run_id": input_run_id, "data_version": profile["data_version"],
        "input_sha256": manifest["input_sha256"], "source_manifest": manifest["source_manifests"],
        "dataset_manifest": manifest, "input_seal_sha256": digest(verified["seal"]),
        "calendar": profile["calendar"], "as_of": panel.index.get_level_values("datetime").max().isoformat()}


def validate_immutable_panel(frame: pd.DataFrame, calendar: pd.DataFrame, profile: dict, attestation: dict):
    requirements = ("complete_calendar", "pit_universe", "pit_adjustment", "available_time_verified")
    if any(attestation.get(name) is not True for name in requirements):
        raise FactoryError("immutable_panel_quality_attestation_missing")
    if not {"event_time", "available_time", "decision_time", "instrument"}.issubset(frame):
        raise FactoryError("immutable_panel_temporal_contract_missing")
    if not {"event_time", "decision_time"}.issubset(calendar): raise FactoryError("immutable_calendar_contract_missing")
    raw, cal = frame.copy(), calendar.copy()
    for key in ("event_time", "available_time", "decision_time"):
        # Naive timestamps are not silently interpreted as UTC.
        if any(pd.Timestamp(value).tzinfo is None for value in raw[key]): raise FactoryError("immutable_panel_timezone_missing")
        raw[key] = pd.to_datetime(raw[key], utc=True)
        if raw[key].isna().any(): raise FactoryError("immutable_panel_timestamp_missing")
    for key in ("event_time", "decision_time"):
        if any(pd.Timestamp(value).tzinfo is None for value in cal[key]): raise FactoryError("immutable_calendar_timezone_missing")
        cal[key] = pd.to_datetime(cal[key], utc=True)
        if cal[key].isna().any(): raise FactoryError("immutable_calendar_timestamp_missing")
    if (raw.available_time < raw.event_time).any() or (raw.available_time > raw.decision_time).any():
        raise FactoryError("immutable_panel_not_available_at_decision")
    if (cal.empty or cal.event_time.duplicated().any() or cal.decision_time.duplicated().any() or
        not cal.event_time.is_monotonic_increasing or not cal.decision_time.is_monotonic_increasing or
        (cal.decision_time < cal.event_time).any()):
        raise FactoryError("immutable_calendar_duplicates_or_order")
    fmt = "%Y-%m-%d" if profile["bar_size"] == "1d" else "%Y-%m-%d %H:%M:%S"
    if cal.decision_time.dt.strftime(fmt).duplicated().any():
        raise FactoryError("immutable_calendar_qlib_frequency_key_collision")
    if profile["bar_size"] == "1h" and cal.event_time.dt.floor("h").duplicated().any():
        raise FactoryError("immutable_calendar_multiple_bars_in_hour")
    if set(raw.instrument) != set(profile["symbols"]): raise FactoryError("immutable_universe_mismatch")
    for _, rows in raw.groupby("instrument"):
        rows = rows.sort_values("event_time")
        if list(rows.event_time) != list(cal.event_time) or list(rows.decision_time) != list(cal.decision_time):
            raise FactoryError("incomplete_calendar_no_gap_compression_allowed")
    raw["datetime"] = raw.decision_time
    # This contract covers OHLCV availability only. Derivatives/fundamentals must
    # have their own per-decision availability join before becoming primitives.
    return validate_panel(raw[["datetime","instrument","open","high","low","close","volume"]]), raw, cal


def _export_immutable_panel(profile: dict, *, qlib_root: Path, input_run_id: str):
    from tools.agent_governance.shared_data import load_manifest_from_git, resolve_manifest_payload, default_shared_data_root
    from .schemas import build_run_paths, ExportResult, utc_now_iso
    from .build_qlib_dataset import build_qlib_provider
    from .research_pipeline import seal_run
    binding = profile["data_binding"]
    git_path = binding["manifest_path"]
    if not git_path.startswith(".agent/data_manifests/") or ".." in git_path.split("/"): raise FactoryError("invalid_shared_manifest_path")
    raw_manifest = subprocess.check_output(["git","show",f"HEAD:{git_path}"],cwd=REPO)
    if hashlib.sha256(raw_manifest).hexdigest() != binding["manifest_sha256"]: raise FactoryError("immutable_manifest_hash_mismatch")
    manifest = load_manifest_from_git(REPO, f"HEAD:{git_path}")
    for key in ("dataset_id", "dataset_version", "aggregate_sha256"):
        if manifest.get(key) != binding[key]: raise FactoryError("immutable_dataset_identity_mismatch:" + key)
    source_root = resolve_manifest_payload(manifest, shared_root=default_shared_data_root(REPO), verify_files=True)
    def file(name):
        record = binding["files"][name]
        path = (source_root / record["path"]).resolve()
        if not path.is_relative_to(source_root.resolve()) or not path.is_file(): raise FactoryError("immutable_panel_path_escape")
        if hashlib.sha256(path.read_bytes()).hexdigest() != record["sha256"]: raise FactoryError("immutable_panel_file_hash_mismatch")
        return path
    quality = read_json(file("quality"))
    if quality.get("calendar") != profile["calendar"] or quality.get("market") != profile["market"]:
        raise FactoryError("immutable_quality_market_calendar_mismatch")
    panel, raw, calendar = validate_immutable_panel(pd.read_parquet(file("panel")), pd.read_parquet(file("calendar")), profile, quality)
    paths = build_run_paths(input_run_id, qlib_root)
    if paths.run_root.exists(): raise FactoryError("immutable_input_run_already_exists")
    paths.qlib_input_csv_dir.mkdir(parents=True)
    # Preserve the original temporal contract for the optional observation sidecar.
    # Existing factor/provider frames and their index/values remain unchanged.
    environment_bars = paths.qlib_input_dir / "environment_bars.parquet"
    environment_calendar = paths.qlib_input_dir / "environment_calendar.parquet"
    raw.to_parquet(environment_bars, index=False)
    calendar.to_parquet(environment_calendar, index=False)
    panel.reset_index().to_parquet(paths.qlib_input_dir / "factory_panel.parquet", index=False)
    bars = panel.reset_index().rename(columns={"instrument":"symbol"})
    fmt = "%Y-%m-%d" if profile["bar_size"] == "1d" else "%Y-%m-%d %H:%M:%S"
    bars["date"] = bars.datetime.dt.strftime(fmt); bars["factor"] = 1.0
    bars_path = paths.qlib_input_dir / "daily_bars.parquet"; bars.to_parquet(bars_path,index=False)
    for symbol, rows in bars.groupby("symbol"): rows.to_csv(paths.qlib_input_csv_dir / f"{symbol}.csv",index=False)
    input_manifest = {"run_id":input_run_id,"status":"completed","mode":"research_only","symbols_requested":profile["symbols"],
        "symbols_exported":profile["symbols"],"universe":{"universe_id":profile["profile_id"]},
        "input_contract":{"asset_class":profile["asset_class"],"bar_size":profile["bar_size"],"source":profile["source"],
            "data_version_request":profile["data_version"],"calendar":profile["calendar"]},
        "calendar":{"qlib_freq":"day" if profile["bar_size"]=="1d" else "60min", "trading_days":calendar.decision_time.dt.strftime(fmt).tolist()},
        "files":{"daily_bars_parquet":str(bars_path.resolve()),"input_csv_dir":str(paths.qlib_input_csv_dir.resolve())},
        "input_sha256":hashlib.sha256(bars_path.read_bytes()).hexdigest(),"validation":quality,
        "environment_contract":{"calendar":profile["calendar"],"periods_per_year":profile["annualization"],
            "availability_semantics":"verified_panel_event_available_decision_contract",
            "bars_hash":hashlib.sha256(environment_bars.read_bytes()).hexdigest(),
            "calendar_hash":hashlib.sha256(environment_calendar.read_bytes()).hexdigest()},
        "source_manifests":[{"symbol":s,"data_version":profile["data_version"],"manifest_path":git_path,
            "manifest_sha256":binding["manifest_sha256"],"aggregate_sha256":binding["aggregate_sha256"]} for s in profile["symbols"]]}
    manifest_path = paths.qlib_input_dir / "dataset_manifest.json"; write_json(manifest_path,input_manifest)
    result = build_qlib_provider(export_result=ExportResult(input_run_id,"completed",str(manifest_path),str(bars_path),
        len(panel),profile["symbols"],profile["symbols"],utc_now_iso()),artifacts_root=qlib_root)
    if result.status != "completed": raise FactoryError("immutable_panel_provider_failed:" + str(result.error))
    write_json(paths.run_root / "pipeline_result.json", {"run_id":input_run_id,"status":"dataset_only","factory_input_only":True,
        "asset_class":profile["asset_class"],"bar_size":profile["bar_size"],"profile_id":profile["profile_id"],**SAFETY})
    seal_run(paths.run_root)
    return read_factory_input(profile, qlib_root=qlib_root, input_run_id=input_run_id)
