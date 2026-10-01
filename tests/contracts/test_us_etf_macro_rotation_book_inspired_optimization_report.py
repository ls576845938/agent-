from __future__ import annotations

import json
from pathlib import Path

import jsonschema


REPORT_PATH = Path(
    "artifacts/us_equity_etf_macro_rotation/latest/us_etf_macro_rotation_book_inspired_optimization_report.json"
)
SCHEMA_PATH = Path("schemas/us_etf_macro_rotation_book_inspired_optimization_report.schema.json")


def _validate_schema(payload: dict) -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(payload, schema)


def test_book_inspired_report_is_research_only() -> None:
    payload = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    _validate_schema(payload)

    assert payload["schema_version"] == "us_etf_macro_rotation_book_inspired_optimization_report_v1"
    assert payload["status"] == "research_only"
    assert payload["live_ready"] is False
    assert payload["paper_ready"] is False
    assert payload["stress_cost_bps"] == [10, 25, 50]


def test_book_inspired_report_covers_expected_families_and_sources() -> None:
    payload = json.loads(REPORT_PATH.read_text(encoding="utf-8"))

    expected_core = {
        "baseline_v2_turnover_guard",
        "dual_momentum_absolute_relative",
        "ensemble_forecast_blend",
        "macro_vol_scaled_overlay",
        "multi_speed_trend_forecast",
        "quality_momentum_12_1",
    }
    expected_151 = {
        "alpha_rotation_residual_151",
        "channel_breakout_151",
        "etf_mean_reversion_151",
        "low_volatility_anomaly_151",
        "multi_asset_tsmom_151",
        "multifactor_portfolio_151",
        "r_squared_trend_quality_151",
        "sector_dual_momentum_151",
        "sector_momentum_ma_filter_151",
        "sector_price_momentum_rotation_151",
        "single_moving_average_151",
        "support_resistance_breakout_151",
        "three_moving_averages_151",
        "two_moving_averages_151",
    }
    families = set(payload["families"])
    assert expected_core.issubset(families)
    assert expected_151.issubset(families)
    assert len(payload["ranking"]) >= len(expected_core | expected_151)
    assert len(payload["book_sources"]) >= 5
    source_paths = {source["path"] for source in payload["book_sources"]}
    assert any("Dual Momentum Investing" in path for path in source_paths)
    assert any("151 Trading Strategies" in path for path in source_paths)


def test_151_inventory_is_parsed_and_not_reduced_to_five_ideas() -> None:
    payload = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    inventory = payload["strategy_inventory_151"]

    assert inventory["source_found"] is True
    assert inventory["total_strategy_entries"] >= 150
    assert inventory["directly_tested_count"] >= 14
    assert inventory["chapter_counts"]["Exchange-Traded Funds (ETFs)"] >= 8
    assert "options" in inventory["deferred_groups"]


def test_each_book_inspired_family_has_cost_stress_and_t_plus_1() -> None:
    payload = json.loads(REPORT_PATH.read_text(encoding="utf-8"))

    for family, summary in payload["families"].items():
        assert summary["candidate_count"] >= 1
        best = summary["best"]
        assert set(best["stress"]) == {"10bps", "25bps", "50bps"}
        assert best["stress"]["50bps"]["diagnostics"]["t_plus_1_execution"] is True
        assert best["stress"]["50bps"]["metrics"]["turnover"] >= 0.0
        if family != "baseline_v2_turnover_guard":
            assert best["source_idea"]


def test_best_non_baseline_is_distinct_from_existing_baseline() -> None:
    payload = json.loads(REPORT_PATH.read_text(encoding="utf-8"))

    assert payload["baseline"]["family"] == "baseline_v2_turnover_guard"
    assert payload["highest_cagr_candidate"]["stress"]["50bps"]["metrics"]["cagr"] >= payload["best_overall"]["stress"]["50bps"]["metrics"]["cagr"]
    assert payload["best_non_baseline"]["family"] != "baseline_v2_turnover_guard"
    assert payload["best_non_baseline"]["survives_50bps"] in {True, False}
    assert payload["methodology"]["primary_cost_bps"] == 50


def test_turnover_profiles_include_aggressive_no_turnover_guard() -> None:
    payload = json.loads(REPORT_PATH.read_text(encoding="utf-8"))

    aggressive = [
        row
        for row in payload["ranking"]
        if row["parameters"].get("turnover_profile") == "aggressive_no_turnover_guard"
    ]
    assert aggressive
    assert max(row["stress"]["50bps"]["metrics"]["turnover"] for row in aggressive) > 100.0
    assert "turnover is reported but no longer penalized" in payload["methodology"]["score_50bps"]


def test_book_inspired_schema_rejects_live_ready() -> None:
    payload = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    payload["live_ready"] = True
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError:
        return

    raise AssertionError("schema accepted live_ready=true")
