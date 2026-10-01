from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from quant_us.backtest.canonical_portfolio_evidence import (
    build_canonical_portfolio_evidence_report,
    build_delay_cost_evidence,
    build_month_end_t_plus_one_evidence,
)


SCHEMA = Path("schemas/us_v3_canonical_backtest_portfolio_evidence.schema.json")
HASH = "a" * 64
COMMIT = "b" * 40


def test_month_end_uses_last_actual_session_and_next_actual_session() -> None:
    evidence = build_month_end_t_plus_one_evidence(
        [
            "2026-01-29",
            "2026-01-30",
            "2026-02-02",
            "2026-02-27",
            "2026-03-02",
        ]
    )

    assert evidence["all_t_plus_one"] is True
    assert evidence["calendar_month_end_label_used"] is False
    assert evidence["rows"][0]["decision_session"] == "2026-01-30"
    assert evidence["rows"][0]["execution_session"] == "2026-02-02"
    assert evidence["rows"][1]["decision_session"] == "2026-02-27"
    assert evidence["rows"][1]["execution_session"] == "2026-03-02"


def test_delay_cost_is_attributed_from_decision_close_to_t_plus_one_fill() -> None:
    evidence = build_delay_cost_evidence(
        [
            {
                "side": "buy",
                "quantity": 10.0,
                "arrival_price": 101.0,
                "gap_return": 0.01,
            },
            {
                "side": "sell",
                "quantity": 5.0,
                "arrival_price": 99.0,
                "gap_return": -0.01,
            },
        ]
    )

    assert evidence["modeled"] is True
    assert evidence["attributed_fill_count"] == 2
    assert evidence["total_delay_cost"] == 15.0
    assert evidence["double_charged"] is False


def test_full_chain_is_version_bound_and_remains_research_only() -> None:
    report = _report()

    _validate(report)
    assert report["status"] == "complete_research_only_blocked"
    assert report["chain"]["complete"] is True
    assert [item["layer"] for item in report["chain"]["layers"]] == [
        "data",
        "signal",
        "forecast",
        "target_portfolio",
        "risk",
        "order_intent",
        "simulated_fill",
        "position_cash_ledger",
        "pnl",
        "report",
    ]
    assert report["engineering_checks"]["all_layers_version_bound"] is True
    assert report["guardrails"]["promotion_evidence_ready"] is False


def test_production_pit_corporate_action_delisting_and_survivorship_fail_closed() -> None:
    report = _report()

    assert report["g06_dependency"]["production_pit_accepted"] is False
    assert report["corporate_actions"]["adjustment_available_time_replay"] is False
    assert report["corporate_actions"]["delisted_symbol_events_available"] is False
    assert report["survivorship"]["survivorship_clean"] is False
    assert "production_pit_required_for_promotion" in report["blockers"]


def test_fixture_ledger_never_counts_as_production_event_ledger() -> None:
    report = _report()
    isolation = report["fixture_isolation"]

    assert isolation["fixture_ledger_can_validate_plumbing"] is True
    assert isolation["fixture_ledger_can_be_production_event_ledger"] is False
    assert isolation["fixture_ledger_can_unlock_promotion"] is False
    assert isolation["production_event_ledger_present"] is False
    assert report["artifacts"]["full_replay_outputs_persisted_in_git"] is False
    assert report["artifacts"]["full_replay_outputs_reproducible_by_script"] is True


def test_schema_rejects_promotion_unlock() -> None:
    report = _report()
    report["guardrails"]["promotion_credit_allowed"] = True

    try:
        _validate(report)
    except jsonschema.ValidationError:
        return
    raise AssertionError("schema accepted promotion_credit_allowed=true")


def test_artifact_identity_is_generation_time_independent() -> None:
    first = _report(generated_at="2026-07-24T00:00:00Z")
    second = _report(generated_at="2026-07-24T01:00:00Z")

    assert first["artifact_identity_sha256"] == second["artifact_identity_sha256"]


def _report(generated_at: str = "2026-07-24T00:00:00Z") -> dict[str, object]:
    return build_canonical_portfolio_evidence_report(
        canonical_report=_canonical(),
        portfolio_report=_portfolio(),
        g06_report=_g06(),
        exposure_sessions=[
            "2026-01-29",
            "2026-01-30",
            "2026-02-02",
            "2026-02-27",
            "2026-03-02",
        ],
        fill_records=[
            {
                "side": "buy",
                "quantity": 10.0,
                "arrival_price": 101.0,
                "gap_return": 0.01,
            }
        ],
        artifacts={
            "canonical_report_sha256": HASH,
            "portfolio_report_sha256": HASH,
            "full_replay_outputs_persisted_in_git": False,
            "full_replay_outputs_reproducible_by_script": True,
        },
        code_commit=COMMIT,
        code_tree_hash="c" * 40,
        generated_at=generated_at,
    )


def _canonical() -> dict[str, object]:
    return {
        "run_id": "canonical-run",
        "candidate": {
            "candidate_id": "us-etf26-complete-return-qqq-1d-v1",
            "strategy_version": "us_etf_complete_return_fixed_signal_v1",
            "symbol": "QQQ",
            "timeframe": "1D",
            "params_hash": HASH,
            "parameter_tuning_performed": False,
            "symbol_or_timeframe_reselection_performed": False,
        },
        "data": {
            "data_version": "immutable-etf26-v1",
            "manifest_sha256": HASH,
            "aggregate_sha256": HASH,
        },
        "hashes": {
            "strategy_config_sha256": HASH,
            "cost_model_hash": HASH,
            "slippage_model_hash": HASH,
            "run_inputs_hash": HASH,
            "data_aggregate_sha256": HASH,
        },
        "event_chain": {
            "sequence": [
                "MarketData",
                "Signal",
                "Forecast",
                "TargetPosition",
                "RiskDecision",
                "OrderIntent",
                "SimulatedFill",
                "PositionCashLedger",
                "Report",
            ],
            "deterministic_replay_hash_match": True,
            "hashes": {
                "event_log": HASH,
                "orders": HASH,
                "fills": HASH,
                "position_ledger": HASH,
                "cash_ledger": HASH,
            },
        },
        "no_lookahead": {
            "decision_before_fill_passed": True,
            "truncation_invariance_passed": True,
            "same_bar_fill_count": 0,
        },
        "corporate_actions": {"coverage_record_count": 1},
        "cost_model": {
            "commission_bps": 1.0,
            "spread_bps": 2.0,
            "slippage_bps": 3.0,
            "impact_bps": 4.0,
        },
        "performance": {"turnover": 1.0},
        "guardrails": {"promotion_credit_allowed": False},
    }


def _portfolio() -> dict[str, object]:
    return {
        "run_id": "portfolio-run",
        "hashes": {
            "run_inputs_hash": HASH,
            "portfolio_event_ledger_content_hash": HASH,
            "risk_decisions_content_hash": HASH,
            "ledger_pnl_content_hash": HASH,
        },
        "ledger_reconciliation": {
            "passed": True,
            "deterministic_replay_hash_match": True,
        },
        "ledger_pnl": {
            "pnl_source": "fills_plus_positions_plus_cash_plus_corporate_action_ledger",
            "price_series_nav_substitution_used": False,
        },
        "cost_stress": {
            "cost_monotonic_nonincreasing_final_equity": True,
        },
        "forecast_to_portfolio": {
            "expected_volatility": 0.2,
            "turnover": 1.0,
        },
        "risk_adjusted_contribution": {
            "active_risk_pct": 5.0,
            "residual_risk_pct": 3.0,
        },
        "liquidity_capacity": {"status": "research_proxy"},
        "sector_style_exposure": {"status": "blocked_for_promotion"},
        "guardrails": {"promotion_credit_allowed": False},
    }


def _g06() -> dict[str, object]:
    return {
        "status": "blocked_external_data",
        "decision": "wait_for_data_steward_immutable_production_pit_handoff",
        "artifact_identity_sha256": HASH,
        "blockers": ["production_pit_bundle_root_not_supplied"],
        "production_pit": {"accepted": False},
        "readiness": {
            "research_ready": True,
            "promotion_evidence_ready": False,
        },
    }


def _validate(report: dict[str, object]) -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    jsonschema.validate(report, schema, format_checker=jsonschema.FormatChecker())
