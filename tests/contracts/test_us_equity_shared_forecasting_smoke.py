from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import numpy as np
import pandas as pd

from quant_shared.forecasting.baseline_adapter import DriftForecastAdapter
from quant_us.research.us_etf_macro_momentum_rotation import UsEtfMacroMomentumRotationConfig
from scripts.research.compare_us_equity_shared_forecast_vs_baseline import (
    run_us_equity_shared_forecast_smoke,
)


SCHEMA_PATH = Path("schemas/us_equity_shared_forecast_vs_baseline_smoke.schema.json")


def _validate(payload: dict) -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(payload, schema)


def test_us_equity_smoke_uses_shared_forecasting_contract_and_baselines(tmp_path: Path) -> None:
    cfg = UsEtfMacroMomentumRotationConfig(min_rows=80)
    prices = _synthetic_price_matrix(cfg.required_symbols(), periods=320)

    report = run_us_equity_shared_forecast_smoke(
        repo_root=tmp_path,
        output_dir=Path("artifacts/shared_forecasting/us_equity/latest"),
        prices=prices,
        macro_data=pd.DataFrame(),
        adapter=DriftForecastAdapter(lookback_steps=10),
        adapter_mode="drift",
        config=cfg,
        lookback_days=60,
        horizon_days=5,
        holdout_days=180,
        max_decisions=4,
        cost_bps=10.0,
    )

    _validate(report)
    assert report["status"] == "COMPLETE_RESEARCH_ONLY_SMOKE"
    assert report["contract"]["shared_package"] == "quant_shared.forecasting"
    assert report["contract"]["allowed_usage"] == "research_only"
    assert report["forecast_request_audit"]["asset_namespace"] == "us_equity"
    assert report["forecast_request_audit"]["lookahead_violation_count"] == 0
    assert report["forecast_request_audit"]["all_requests_research_only"] is True
    strategy_ids = {row["strategy_id"] for row in report["comparison"]["metrics"]}
    assert {
        "shared_forecast_topn",
        "existing_us_etf_rotation",
        "spy_buy_hold",
        "qqq_buy_hold",
        "equal_weight_required_universe",
    }.issubset(strategy_ids)
    assert report["safety_flags"]["paper_queue_write_allowed"] is False
    assert report["safety_flags"]["live_order_allowed"] is False
    assert (tmp_path / report["report_paths"]["rows_csv"]).exists()


def test_us_equity_smoke_blocks_when_history_is_too_short(tmp_path: Path) -> None:
    cfg = UsEtfMacroMomentumRotationConfig(min_rows=20)
    prices = _synthetic_price_matrix(cfg.required_symbols(), periods=30)

    report = run_us_equity_shared_forecast_smoke(
        repo_root=tmp_path,
        output_dir=Path("artifacts/shared_forecasting/us_equity/latest"),
        prices=prices,
        macro_data=pd.DataFrame(),
        adapter=DriftForecastAdapter(lookback_steps=5),
        config=cfg,
        lookback_days=60,
        horizon_days=5,
        holdout_days=60,
        max_decisions=4,
    )

    _validate(report)
    assert report["status"] == "BLOCKED"
    assert report["blockers"] == ["insufficient_decision_points"]
    assert report["safety_flags"]["live_order_allowed"] is False


def test_us_equity_smoke_schema_rejects_paper_or_live_unlock(tmp_path: Path) -> None:
    cfg = UsEtfMacroMomentumRotationConfig(min_rows=80)
    prices = _synthetic_price_matrix(cfg.required_symbols(), periods=320)
    report = run_us_equity_shared_forecast_smoke(
        repo_root=tmp_path,
        output_dir=Path("artifacts/shared_forecasting/us_equity/latest"),
        prices=prices,
        macro_data=pd.DataFrame(),
        adapter=DriftForecastAdapter(lookback_steps=10),
        config=cfg,
        lookback_days=60,
        horizon_days=5,
        holdout_days=180,
        max_decisions=4,
    )
    report["safety_flags"]["paper_queue_write_allowed"] = True
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    try:
        jsonschema.validate(report, schema)
    except jsonschema.ValidationError:
        return
    raise AssertionError("schema accepted paper_queue_write_allowed=true")


def _synthetic_price_matrix(symbols: tuple[str, ...], *, periods: int) -> pd.DataFrame:
    dates = pd.bdate_range("2024-01-02", periods=periods, tz="UTC")
    x = np.arange(periods, dtype=float)
    frame = pd.DataFrame(index=dates)
    for index, symbol in enumerate(symbols):
        drift = 0.025 + index * 0.002
        seasonal = np.sin(x / (17.0 + index)) * (0.6 + index * 0.02)
        close = 50.0 + index * 2.5 + x * drift + seasonal
        frame[symbol] = np.maximum(close, 5.0)
    return frame
