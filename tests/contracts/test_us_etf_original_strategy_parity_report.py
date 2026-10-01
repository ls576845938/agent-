from __future__ import annotations

import json
from pathlib import Path

import jsonschema


REPORT_PATH = Path("artifacts/us_equity_etf_macro_rotation/latest/us_etf_original_strategy_parity_report.json")
SCHEMA = Path("schemas/us_etf_original_strategy_parity_report.schema.json")


def test_original_strategy_parity_report_is_diagnostic_only() -> None:
    payload = json.loads(REPORT_PATH.read_text(encoding="utf-8"))

    assert payload["schema_version"] == "us_etf_original_strategy_parity_report_v1"
    _validate_schema(payload)
    assert payload["status"] == "diagnostic_research_only"
    assert payload["live_ready"] is False
    assert payload["paper_ready"] is False
    assert payload["canonical_original_baseline"]["baseline_id"] == "original_v8_2_semantics"
    assert payload["canonical_original_baseline"]["eligible_for_direct_comparison_with_integrated_candidates"] is False


def test_original_strategy_rebalance_semantics_are_documented() -> None:
    payload = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    original = payload["original_external_v8_2"]

    assert original["status"] == "available"
    assert original["rebalance_calendar"]["calendar_month_end_count"] > original["rebalance_calendar"]["used_by_original_count"]
    assert original["rebalance_calendar"]["skipped_month_count"] > 0
    assert "skips months" in payload["diagnosis"]["primary_reason"]


def test_original_strategy_did_not_beat_spy_or_qqq_on_true_cagr() -> None:
    payload = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    metrics = payload["original_external_v8_2"]["metrics"]

    assert metrics["strategy"]["true_cagr"] < metrics["SPY"]["true_cagr"]
    assert metrics["strategy"]["true_cagr"] < metrics["QQQ"]["true_cagr"]
    assert metrics["strategy"]["arithmetic_annualized_return"] > metrics["strategy"]["true_cagr"]
    assert "arithmetic annualized return" in payload["diagnosis"]["metric_label_issue"]
    assert "original_v8_2_semantics" in payload["diagnosis"]["next_action"]


def test_integrated_backtest_changed_rebalance_semantics_and_lowered_cagr() -> None:
    payload = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    original = payload["original_external_v8_2"]["metrics"]
    integrated = payload["integrated_research_backtest"]["metrics"]

    assert payload["integrated_research_backtest"]["rebalance_calendar"]["semantics"] == "actual_last_trading_day_each_month"
    assert integrated["strategy"]["true_cagr"] < original["strategy"]["true_cagr"]
    assert integrated["turnover"] > original["turnover"]


def test_original_strategy_parity_schema_rejects_direct_comparison_unlock() -> None:
    payload = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    payload["canonical_original_baseline"]["eligible_for_direct_comparison_with_integrated_candidates"] = True

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError:
        return
    raise AssertionError("schema accepted direct comparison unlock")


def _validate_schema(payload: dict) -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError as exc:
        raise AssertionError(f"schema validation failed: {exc.message}") from exc
