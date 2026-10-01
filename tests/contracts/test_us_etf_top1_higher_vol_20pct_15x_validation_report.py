from __future__ import annotations

import json
from pathlib import Path

import jsonschema


REPORT_PATH = Path("artifacts/us_equity_etf_macro_rotation/latest/us_etf_top1_higher_vol_20pct_15x_validation_report.json")
SCHEMA = Path("schemas/us_etf_top1_higher_vol_20pct_15x_validation_report.schema.json")


def _payload() -> dict:
    return json.loads(REPORT_PATH.read_text(encoding="utf-8"))


def test_dedicated_vol_target_report_is_research_only() -> None:
    payload = _payload()

    assert payload["schema_version"] == "us_etf_top1_higher_vol_20pct_15x_validation_report_v1"
    _validate_schema(payload)
    assert payload["status"] == "research_only_manual_review_required"
    assert payload["live_ready"] is False
    assert payload["paper_ready"] is False
    assert payload["strategy_id"] == "top1_higher_vol__vol_target_20pct_cap1.5x"
    assert payload["overlay"]["target_vol"] == 0.20
    assert payload["overlay"]["max_leverage"] == 1.50


def test_formal_comparison_contains_required_benchmarks() -> None:
    payload = _payload()

    assert set(payload["comparison"]) == {
        "selected_vol_target_20pct_cap1.5x",
        "SPY",
        "QQQ",
        "60_40_SPY_IEF",
        "SHV",
        "original_v8_2_semantics",
        "top1_higher_vol_unlevered",
    }
    selected = payload["comparison"]["selected_vol_target_20pct_cap1.5x"]
    assert selected["true_cagr"] > payload["comparison"]["QQQ"]["true_cagr"]
    assert selected["max_drawdown"] > payload["comparison"]["QQQ"]["max_drawdown"]
    assert selected["true_cagr"] > payload["comparison"]["top1_higher_vol_unlevered"]["true_cagr"]
    for metrics in payload["comparison"].values():
        assert "annualized_volatility" in metrics
        assert "calmar" in metrics


def test_standardized_report_schema_covers_all_benchmarks() -> None:
    payload = _payload()
    schema = payload["standardized_report_schema"]

    assert schema["schema_version"] == "us_etf_standardized_comparison_schema_v1"
    assert schema["required_fields"] == ["CAGR", "Vol", "Sharpe", "MDD", "Calmar", "Turnover", "CostStressedReturn", "LiquidityPass"]
    assert {row["id"] for row in schema["rows"]} == set(payload["comparison"])
    assert "SHV" in {row["id"] for row in schema["rows"]}
    for row in schema["rows"]:
        for field in schema["required_fields"]:
            assert field in row
        assert isinstance(row["LiquidityPass"], bool)


def test_financing_margin_and_slippage_models_are_explicit() -> None:
    payload = _payload()

    assert payload["financing_model"]["type"] == "time_varying_DGS2_plus_broker_spread"
    assert payload["financing_model"]["average_annual_rate"] > 0.0
    assert payload["margin_model"]["passes_margin_constraint"] is True
    assert payload["margin_model"]["observed_max_leverage"] <= 1.5
    assert set(payload["cost_stress"]) == {"0bps", "10bps", "25bps", "50bps"}
    assert payload["cost_stress"]["25bps"]["total_slippage_drag"] > payload["cost_stress"]["10bps"]["total_slippage_drag"]
    assert payload["cost_stress"]["25bps"]["metrics"]["true_cagr"] < payload["comparison"]["QQQ"]["true_cagr"]


def test_tradability_model_surfaces_liquidity_concerns() -> None:
    payload = _payload()
    tradability = payload["tradability"]

    assert tradability["missing_volume_symbols"] == []
    assert tradability["reference_aum"] == 100000.0
    assert tradability["passes_reference_aum_liquidity_check"] is False
    assert tradability["max_single_name_participation"] > tradability["max_participation_review_threshold"]
    assert tradability["worst_participation_events"]
    assert any(event["symbol"] == "DBMF" for event in tradability["worst_participation_events"])


def test_dbmf_liquidity_remediation_candidates_are_evaluated() -> None:
    payload = _payload()
    constraints = payload["tradability_constraints"]

    assert constraints["dbmf_max_weight"] == 0.10
    assert constraints["min_20d_adv_usd"] == 10_000_000.0
    assert constraints["replacement_asset"] == "SHV"
    assert constraints["selected_constrained_variant"] == "min_adv_10m_to_shv"
    candidate_ids = {row["variant_id"] for row in constraints["candidates"]}
    assert {"dbmf_cap_10pct", "dbmf_replace_with_shv", "min_adv_10m_to_shv"} <= candidate_ids
    selected = next(row for row in constraints["candidates"] if row["variant_id"] == constraints["selected_constrained_variant"])
    assert selected["tradability_pass"] is True
    assert selected["metrics"]["true_cagr"] > payload["metrics"]["selected_variant"]["true_cagr"]
    assert payload["constrained_tradability"]["passes_reference_aum_liquidity_check"] is True


def test_capacity_tests_cover_requested_account_sizes() -> None:
    payload = _payload()
    requested = {"10000", "50000", "100000", "500000", "1000000"}

    assert set(payload["capacity_tests"]["aums"]) == requested
    assert set(payload["constrained_capacity_tests"]["aums"]) == requested
    assert payload["capacity_tests"]["aums"]["10000"]["passes_reference_aum_liquidity_check"] is True
    assert payload["capacity_tests"]["aums"]["50000"]["passes_reference_aum_liquidity_check"] is False
    assert payload["capacity_tests"]["max_passing_aum"] == 10_000.0
    assert payload["constrained_capacity_tests"]["aums"]["500000"]["passes_reference_aum_liquidity_check"] is True
    assert payload["constrained_capacity_tests"]["aums"]["1000000"]["passes_reference_aum_liquidity_check"] is False
    assert payload["constrained_capacity_tests"]["all_requested_aums_pass"] is False
    assert payload["constrained_capacity_tests"]["max_passing_aum"] == 500_000.0


def test_source_attribution_splits_selection_leverage_financing_and_slippage() -> None:
    payload = _payload()
    attribution = payload["source_attribution"]

    assert attribution["asset_selection_and_parameter_effect_cagr"] > 0.0
    assert attribution["gross_leverage_effect_cagr"] > 0.0
    assert attribution["financing_effect_cagr"] < 0.0
    assert attribution["slippage_25bps_effect_cagr"] < 0.0
    assert attribution["net_selected_cagr"] == payload["metrics"]["selected_variant"]["true_cagr"]


def test_small_account_10k_profile_is_explicit() -> None:
    payload = _payload()
    profile = payload["small_account_10k_profile"]

    assert profile["account_equity"] == 10_000.0
    assert profile["positioning"] == "small_account_research_profile"
    assert profile["original_strategy_capacity_pass"] is True
    assert profile["constrained_strategy_capacity_pass"] is True
    assert profile["recommended_research_variant"] == payload["tradability_constraints"]["selected_constrained_variant"]
    assert profile["financing_note"]["uses_margin"] is True
    assert profile["financing_note"]["max_borrow_notional"] == 5_000.0
    assert profile["whole_share_warning"]["status"] == "review_required"
    assert profile["original_latest_target"]["target_count"] >= 1
    assert profile["constrained_latest_target"]["target_count"] >= 1
    assert profile["original_latest_target"]["gross_exposure"] <= 1.5 + 1e-9
    assert profile["constrained_latest_target"]["gross_exposure"] <= 1.5 + 1e-9


def test_walk_forward_yearly_and_extreme_year_attribution_exist() -> None:
    payload = _payload()

    assert payload["walk_forward"]["fold_count"] >= 5
    assert payload["walk_forward"]["aggregate_oos"]["metrics"]["strategy"]["true_cagr"] > 0.0
    years = {row["year"] for row in payload["yearly_breakdown"]}
    assert min(years) == 2018
    assert max(years) >= 2026
    extreme_years = {row["year"] for row in payload["extreme_year_attribution"]["selected_years"]}
    assert {2022, 2023, 2025, 2026}.issubset(extreme_years)
    assert "financing_drag_sum" in payload["extreme_year_attribution"]["worst_return_year"]


def test_decision_does_not_promote_because_concerns_remain() -> None:
    payload = _payload()

    assert payload["decision"]["clears_qqq_cagr_with_lower_drawdown"] is True
    assert payload["decision"]["tradability_pass"] is False
    assert payload["decision"]["constrained_tradability_pass"] is True
    assert payload["decision"]["status"] == "research_concerns"
    assert payload["decision"]["live_ready"] is False
    assert payload["decision"]["paper_ready"] is False


def test_dedicated_vol_target_schema_rejects_paper_ready() -> None:
    payload = _payload()
    payload["paper_ready"] = True

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError:
        return
    raise AssertionError("schema accepted paper_ready=true")


def _validate_schema(payload: dict) -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError as exc:
        raise AssertionError(f"schema validation failed: {exc.message}") from exc
