"""Server-owned research profiles; a market is configuration, not another platform."""
from pathlib import Path
from .schemas import QlibAdapterError, build_run_paths, load_universe_config, load_yaml_file, make_run_id

REPO = Path(__file__).resolve().parents[2]
PROFILES = {
    "us_equity_daily": {"label": "美股 · Alpha158 日线", "config": "configs/qlib/us_lgbm_alpha158_daily.yaml",
        "universe": "configs/universe/us_core_liquid.yaml", "asset_class": "equity", "bar_size": "1d"},
    "okx_btc_trend_1h": {"label": "OKX BTC 永续 · 趋势小时线", "config": "configs/qlib/okx_btc_trend_1h.yaml",
        "universe": "configs/universe/okx_btc_perpetual_1h.yaml", "asset_class": "crypto", "bar_size": "1h"},
}


def list_profiles() -> list[dict]:
    output = []
    for key, value in PROFILES.items():
        universe = load_universe_config(REPO / value["universe"])
        config = load_yaml_file(REPO / value["config"])
        output.append({"profile_id": key, **value, "source": universe.source, "symbols": universe.symbols,
            "data_version": universe.data_binding.get("dataset_version", ""),
            "start_date": str(config.get("data", {}).get("start_date", "2020-01-01")),
            "end_date": str(config.get("data", {}).get("end_date", "2025-12-31")),
            "execution_permission": False})
    return output


def resolve_pipeline_request(request: dict) -> dict:
    allowed = {"profile_id", "data_version", "run_id", "dry_run", "start_date", "end_date"}
    if set(request) - allowed:
        raise QlibAdapterError("Profile requests reject path, market, permission or arbitrary overrides.")
    profile = next((p for p in list_profiles() if p["profile_id"] == request.get("profile_id")), None)
    if profile is None:
        raise QlibAdapterError("Unknown research profile_id.")
    version = str(request.get("data_version") or profile["data_version"])
    if not version or version == "latest":
        raise QlibAdapterError("Pipeline requires an explicit data version.")
    if profile["data_version"] and version != profile["data_version"]:
        raise QlibAdapterError("Data version conflicts with immutable profile.")
    for field in ("start_date", "end_date"):
        if request.get(field) and str(request[field]) != profile[field]:
            raise QlibAdapterError("Frozen train/valid/test profile does not accept date overrides.")
    run_id = str(request.get("run_id") or make_run_id("qlib"))
    build_run_paths(run_id)
    if type(request.get("dry_run", False)) is not bool:
        raise QlibAdapterError("dry_run must be a boolean.")
    return {**profile, "data_version": version, "run_id": run_id, "dry_run": request.get("dry_run", False)}
