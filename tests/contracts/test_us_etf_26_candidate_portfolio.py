from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import jsonschema
import pandas as pd

from quant_us.portfolio.us_etf_26_candidate_portfolio import (
    FALSE_GUARDRAILS,
    _portfolio_reconciliation,
    _risk_model,
    analyze_candidate_portfolio,
)


ROOT = Path(__file__).resolve().parents[2]
SCHEMA = ROOT / "schemas/us_etf_26_candidate_portfolio_report.schema.json"


def test_forecast_alpha_target_and_instrument_models_are_explicit() -> None:
    analysis = _analysis()
    construction = analysis["portfolio_construction"]
    decision = analysis["risk_decisions"][0]

    assert decision["signal"]["strength"] == 1.0
    assert decision["forecast"]["value"] == 1.0
    assert decision["alpha"]["score"] == 1.0
    assert decision["alpha"]["expected_active_return"] is None
    assert decision["target_position"]["target_weight"] == 3.0
    assert decision["risk_decision"]["approved_for_promotion"] is False
    assert "max_single_asset_weight" in decision["risk_decision"]["breaches"]
    assert decision["risk_decision"]["current_daily_return"] == 0.0
    assert decision["risk_decision"]["stale_data_trading_sessions"] == 0
    assert decision["risk_decision"]["stale_data_check_passed"] is True
    assert construction["data_freshness_risk"]["stale_data_check_passed"] is True
    assert construction["data_freshness_risk"]["available_time_field_present"] is False
    assert construction["risk_budget"]["effective_asset_count"] == 1
    assert construction["risk_budget"]["diversification_used"] is False
    assert construction["equivalence"]["qqq_one_x_equals_qqq_synthetic_three_x"] is False
    assert construction["equivalence"]["qqq_synthetic_three_x_equals_tqqq_intrinsic_leverage"] is False
    assert construction["instrument_models"]["qqq_synthetic_three_x"]["broker_executable"] is False
    assert construction["instrument_models"]["tqqq_intrinsic_leverage"]["daily_reset_path_dependency"] is True


def test_portfolio_pnl_is_ledger_derived_and_replayable() -> None:
    analysis = _analysis()
    pnl = analysis["ledger_pnl"]
    recon = analysis["reconciliation"]
    event_ledger = analysis["portfolio_event_ledger"]

    assert pnl["status"] == "pass"
    assert pnl["pnl_source"] == "fills_plus_positions_plus_cash_plus_corporate_action_ledger"
    assert pnl["price_series_nav_substitution_used"] is False
    assert pnl["exposure_timeline_used"] is False
    assert pnl["final_equity"] == 1005.0
    assert pnl["total_pnl"] == 5.0
    assert recon["passed"] is True
    assert recon["ledger_inputs_reconciled"] is True
    assert recon["exposure_timeline_used"] is False
    assert recon["cash_delta"] == 0.0
    assert recon["quantity_delta"] == 0.0
    assert recon["equity_delta"] == 0.0
    assert recon["deterministic_replay_hash_match"] is True
    assert recon["portfolio_event_id_unique"] is True
    assert len({row["portfolio_event_id"] for row in event_ledger}) == len(event_ledger)
    required = {
        "run_id",
        "strategy_id",
        "data_version",
        "decision_time",
        "signal",
        "forecast",
        "alpha",
        "target_position",
        "risk_decision",
        "order_id",
        "fill_id",
        "error_code",
    }
    assert all(required <= set(row) for row in event_ledger)


def test_cost_liquidity_exposure_and_promotion_fail_closed() -> None:
    analysis = _analysis()
    cost = analysis["cost_stress"]
    liquidity = analysis["liquidity_capacity"]
    exposure = analysis["sector_style_exposure"]
    promotion = analysis["promotion_evidence"]
    report = analysis["report"]

    assert cost["cost_monotonic_nonincreasing_final_equity"] is True
    assert liquidity["fills_below_minimum_order_notional"] == 1
    assert liquidity["minimum_order_notional_passed"] is False
    assert exposure["sector_exposure"]["status"] == "unavailable"
    assert exposure["style_exposure"]["status"] == "unavailable"
    assert exposure["diversification_claimed"] is False
    assert promotion["status"] == "blocked"
    assert promotion["promotion_credit_allowed"] is False
    assert "production_pit_intake_blocked_external_data" in report["blockers"]
    assert "canonical_fills_below_minimum_order_notional:1" in report["blockers"]
    assert all(report["guardrails"][key] is False for key in FALSE_GUARDRAILS)
    assert report["guardrails"]["research_only"] is True
    assert report["guardrails"]["fail_closed"] is True


def test_risk_model_estimates_universe_without_claiming_diversification() -> None:
    sessions = pd.date_range("2025-01-01", periods=130, freq="B").strftime("%Y-%m-%d")
    close = pd.DataFrame(
        {
            "QQQ": [100.0 + index * 0.2 + (index % 5) * 0.1 for index in range(130)],
            "SPY": [90.0 + index * 0.1 + (index % 7) * 0.05 for index in range(130)],
        },
        index=sessions,
    )
    model = _risk_model(
        daily_close=close,
        universe=["QQQ", "SPY"],
        benchmark_symbol="SPY",
        risk_estimation={
            "lookback_sessions": 120,
            "minimum_symbol_sessions": 20,
            "minimum_pairwise_sessions": 20,
            "annualization_sessions": 252,
            "target_annual_volatility": 0.2,
        },
    )

    assert model["estimated_symbol_count"] == 2
    assert model["correlation"]["QQQ"]["QQQ"] == 1.0
    assert model["correlation"]["QQQ"]["SPY"] is not None
    assert model["effective_candidate_asset_count"] == 1
    assert model["diversification_used_for_candidate"] is False
    assert model["promotion_credit_allowed"] is False


def test_exposure_timeline_tamper_cannot_change_ledger_pnl() -> None:
    canonical = _canonical()
    baseline = _analysis(canonical=canonical)
    canonical["exposure"][-1].update(
        {"cash": -999999.0, "quantity": 12345.0, "market_price": 0.01, "equity": -999998.0}
    )
    tampered = _analysis(canonical=canonical)

    assert tampered["ledger_pnl"] == baseline["ledger_pnl"]
    assert tampered["reconciliation"]["passed"] is True
    assert tampered["ledger_pnl"]["exposure_timeline_used"] is False


def test_reconciliation_detects_tampered_fill() -> None:
    canonical = _canonical()
    canonical["fills"][0]["quantity"] = 0.6
    result = _reconciliation(canonical)

    assert result["ledger_inputs_reconciled"] is False
    assert result["quantity_delta"] == 0.1
    assert result["fill_settlement_max_delta"] == 10.0


def test_reconciliation_detects_tampered_position() -> None:
    canonical = _canonical()
    canonical["positions"][-1]["quantity_after"] = 0.6
    result = _reconciliation(canonical)

    assert result["ledger_inputs_reconciled"] is False
    assert result["final_position_quantity_delta"] == 0.1


def test_reconciliation_detects_tampered_cash() -> None:
    canonical = _canonical()
    tampered = [dict(item) for item in canonical["cash"]]
    tampered[-1]["amount"] = -49.0
    result = _portfolio_reconciliation(
        report=canonical["report"],
        fills=canonical["fills"],
        positions=canonical["positions"],
        cash=tampered,
        corporate_actions=canonical["corporate_actions"],
    )

    assert result["cash_delta"] == 1.0
    assert result["equity_delta"] == 1.0
    assert result["cash_balance_chain_max_delta"] == 1.0
    assert result["fill_settlement_max_delta"] == 1.0
    assert result["ledger_inputs_reconciled"] is False


def test_current_main_candidate_portfolio_fixture_contract() -> None:
    report = _analysis()["report"]
    assert report["code_commit"] == "a" * 40
    assert report["canonical_dependency"]["run_id"] == "canonical-test"
    assert report["canonical_dependency"]["fill_count"] == 1
    assert report["ledger_reconciliation"]["passed"] is True
    assert report["promotion_evidence"]["status"] == "blocked"
    assert report["promotion_evidence"]["promotion_credit_allowed"] is False
    assert report["counts"]["portfolio_event_ledger_count"] > 1
    assert report["data"]["universe_data"]["loaded_symbol_count"] == 2
    assert report["sector_style_exposure"]["diversification_claimed"] is False
    assert all(report["guardrails"][key] is False for key in FALSE_GUARDRAILS)


def test_schema_rejects_any_promotion_unlock() -> None:
    report = _analysis()["report"]
    report["guardrails"]["promotion_unlock_allowed"] = True
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(report, schema)
    except jsonschema.ValidationError:
        return
    raise AssertionError("schema accepted promotion_unlock_allowed=true")


def test_builder_direct_script_help_imports_quant_us() -> None:
    completed = subprocess.run(
        [sys.executable, "scripts/build_us_etf_26_candidate_portfolio.py", "--help"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert completed.returncode == 0, completed.stderr
    assert "candidate-specific ETF26 portfolio" in completed.stdout


def _analysis(*, canonical: dict[str, object] | None = None) -> dict[str, object]:
    sessions = pd.date_range("2025-01-01", periods=130, freq="B").strftime("%Y-%m-%d")
    close = pd.DataFrame(
        {
            "QQQ": [100.0 + index * 0.2 + (index % 5) * 0.1 for index in range(130)],
            "SPY": [90.0 + index * 0.1 + (index % 7) * 0.05 for index in range(130)],
        },
        index=sessions,
    )
    volume = pd.DataFrame({"QQQ": [10_000_000.0] * 130, "SPY": [20_000_000.0] * 130}, index=sessions)
    return analyze_candidate_portfolio(
        config=_config(),
        candidate=_candidate(),
        goal2={"status": "blocked_external_data"},
        canonical=canonical or _canonical(),
        daily_close=close,
        daily_dollar_volume=volume,
        universe_data={"universe_count": 2, "loaded_symbol_count": 2},
        code_commit="a" * 40,
        code_tree_hash="b" * 40,
        generated_at="2026-07-13T00:00:00+00:00",
        config_sha256="c" * 64,
        candidate_sha256="d" * 64,
        goal2_sha256="e" * 64,
        data_manifest_sha256="f" * 64,
    )


def _config() -> dict[str, object]:
    return {
        "dataset_id": "us-equity-hf-etf26-1min",
        "dataset_version": "test-data",
        "aggregate_sha256": "1" * 64,
        "benchmark_symbol": "SPY",
        "risk_estimation": {
            "lookback_sessions": 120,
            "minimum_symbol_sessions": 20,
            "minimum_pairwise_sessions": 20,
            "annualization_sessions": 252,
            "target_annual_volatility": 0.2,
        },
        "forecast_conversion": {
            "forecast_unit": "binary_long_state_not_expected_return",
            "alpha_score_rule": "signal_strength_x_forecast_confidence",
            "expected_return_blocker": "forecast_alpha_calibration_unavailable_without_clean_oos_ic",
            "canonical_target_rule": "alpha_score_x_frozen_exposure_multiplier_3x",
        },
        "constraints": {
            "long_only": True,
            "max_single_asset_weight": 1.0,
            "max_sector_weight": 0.4,
            "max_style_weight": 0.6,
            "max_gross_exposure": 1.0,
            "max_net_exposure": 1.0,
            "max_leverage": 1.0,
            "minimum_cash_weight": 0.0,
            "max_turnover_per_rebalance": 3.0,
            "max_annualized_turnover": 50.0,
            "minimum_order_notional": 100.0,
            "max_volume_participation_pct": 1.0,
            "max_drawdown": 0.2,
            "max_daily_loss": 0.075,
            "max_stale_trading_sessions": 1,
        },
        "instrument_models": {
            "qqq_one_x": {"symbol": "QQQ", "exposure_multiplier": 1.0},
            "qqq_synthetic_three_x": {
                "symbol": "QQQ",
                "exposure_multiplier": 3.0,
                "broker_executable": False,
            },
            "tqqq_intrinsic_leverage": {
                "symbol": "TQQQ",
                "daily_reset_path_dependency": True,
            },
        },
    }


def _candidate() -> dict[str, object]:
    return {
        "candidate_id": "us-etf26-complete-return-qqq-1d-v1",
        "strategy_version": "test-v1",
        "selection": {"symbol": "QQQ", "timeframe": "1D", "exposure_multiplier": 3.0},
        "universe": ["QQQ", "SPY"],
    }


def _canonical() -> dict[str, object]:
    strategy_id = "us-etf26-complete-return-qqq-1d-v1:test-v1"
    run_id = "canonical-test"
    fill = {
        "fill_id": "fill-1",
        "order_id": "order-1",
        "signal_id": "signal-1",
        "forecast_id": "forecast-1",
        "target_position_id": "target-1",
        "risk_check_id": "risk-1",
        "decision_time": "2026-01-01T21:00:00+00:00",
        "filled_at": "2026-01-02T14:30:00+00:00",
        "symbol": "QQQ",
        "side": "buy",
        "quantity": 0.5,
        "arrival_price": 100.0,
        "fill_price": 100.0,
        "commission": 0.0,
        "spread_cost": 0.0,
        "slippage_cost": 0.0,
        "impact_cost": 0.0,
        "volume_participation_pct": 0.01,
        "error_code": None,
    }
    events = [
        {
            "event_type": "TargetPosition",
            "run_id": run_id,
            "strategy_id": strategy_id,
            "data_version": "test-data",
            "decision_time": "2026-01-01T21:00:00+00:00",
            "timestamp_utc": "2026-01-01T21:00:00+00:00",
            "signal": {"signal_id": "signal-1", "strength": 1.0},
            "forecast": {"forecast_id": "forecast-1", "value": 1.0, "confidence": 1.0},
            "target_position": {"target_position_id": "target-1", "target_weight": 3.0},
        },
        {
            "event_type": "RiskDecision",
            "target_position": {"target_position_id": "target-1", "target_weight": 3.0},
            "risk_decision": {"risk_check_id": "risk-1", "approved": True},
        },
    ]
    exposure = [
        {
            "session": "2026-01-01",
            "timestamp_utc": "2026-01-01T21:00:00+00:00",
            "cash": 1000.0,
            "quantity": 0.0,
            "market_price": 100.0,
            "position_value": 0.0,
            "equity": 1000.0,
            "gross_exposure": 0.0,
            "net_exposure": 0.0,
            "leverage": 0.0,
            "drawdown": 0.0,
        },
        {
            "session": "2026-01-02",
            "timestamp_utc": "2026-01-02T21:00:00+00:00",
            "cash": 950.0,
            "quantity": 0.5,
            "market_price": 110.0,
            "position_value": 55.0,
            "equity": 1005.0,
            "gross_exposure": 55.0,
            "net_exposure": 55.0,
            "leverage": 55.0 / 1005.0,
            "drawdown": 0.0,
        },
    ]
    return {
        "manifest_sha256": "2" * 64,
        "report_sha256": "3" * 64,
        "report": {
            "run_id": run_id,
            "code_commit": "4" * 40,
            "status": "complete_research_only_blocked",
            "blockers": ["independent_confirmation_window_not_complete:0_of_252"],
            "candidate": {
                "strategy_id": strategy_id,
                "params_hash": "5" * 64,
                "parameter_tuning_performed": False,
            },
            "data": {"data_version": "test-data"},
            "performance": {
                "initial_cash": 1000.0,
                "max_drawdown_abs_pct": 0.0,
                "turnover_notional": 50.0,
                "turnover_ratio": 0.05,
                "costs": {"total": 0.0},
            },
            "ledger_reconciliation": {
                "passed": True,
                "final_market_price": 110.0,
                "reported_final_cash": 950.0,
                "reported_final_quantity": 0.5,
                "reported_final_equity": 1005.0,
            },
            "cost_model": {"canonical_cost_model_hash": "6" * 64},
            "cost_stress": {
                "rows": [
                    {"total_cost_bps": 0.0, "final_equity": 1010.0},
                    {"total_cost_bps": 5.0, "final_equity": 1008.0},
                    {"total_cost_bps": 10.0, "final_equity": 1005.0},
                    {"total_cost_bps": 25.0, "final_equity": 1000.0},
                    {"total_cost_bps": 50.0, "final_equity": 990.0},
                ]
            },
            "walk_forward": {
                "method": "test",
                "fold_count": 1,
                "positive_fold_count": 1,
                "parameter_selection_performed": False,
                "folds": [{"parameters_frozen": True, "purge_sessions": 1, "embargo_sessions": 1}],
            },
            "independent_confirmation": {"status": "incomplete", "observed_complete_sessions": 0},
            "event_chain": {"order_count": 1},
        },
        "events": events,
        "fills": [fill],
        "positions": [
            {
                "entry_id": "position-mark-0",
                "entry_type": "mark",
                "timestamp_utc": "2026-01-01T21:00:00+00:00",
                "fill_id": None,
                "quantity_before": 0.0,
                "quantity_after": 0.0,
                "market_price": 100.0,
                "error_code": None,
            },
            {
                "entry_id": "position-fill-1",
                "entry_type": "fill",
                "timestamp_utc": "2026-01-02T14:30:00+00:00",
                "fill_id": "fill-1",
                "quantity_before": 0.0,
                "quantity_after": 0.5,
                "market_price": None,
                "error_code": None,
            },
            {
                "entry_id": "position-mark-1",
                "entry_type": "mark",
                "timestamp_utc": "2026-01-02T21:00:00+00:00",
                "fill_id": None,
                "quantity_before": 0.5,
                "quantity_after": 0.5,
                "market_price": 110.0,
                "error_code": None,
            },
        ],
        "cash": [
            {
                "entry_id": "cash-0",
                "entry_type": "initial_cash",
                "timestamp_utc": "2026-01-01T14:30:00+00:00",
                "amount": 1000.0,
                "balance_after": 1000.0,
                "fill_id": None,
                "order_id": None,
                "error_code": None,
            },
            {
                "entry_id": "cash-1",
                "entry_type": "fill_settlement",
                "timestamp_utc": "2026-01-02T14:30:00+00:00",
                "amount": -50.0,
                "balance_after": 950.0,
                "fill_id": "fill-1",
                "order_id": "order-1",
                "error_code": None,
            },
        ],
        "corporate_actions": [{"event_id": "coverage-1", "pnl_adjustment": 0.0}],
        "exposure": exposure,
    }


def _reconciliation(canonical: dict[str, object]) -> dict[str, object]:
    return _portfolio_reconciliation(
        report=canonical["report"],
        fills=canonical["fills"],
        positions=canonical["positions"],
        cash=canonical["cash"],
        corporate_actions=canonical["corporate_actions"],
    )
