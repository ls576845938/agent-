from __future__ import annotations

import json
from pathlib import Path

import jsonschema


REPORT_PATH = Path(
    "artifacts/us_equity_etf_macro_rotation/latest/us_etf_original_semantics_optimization_report.json"
)
SCHEMA_PATH = Path("schemas/us_etf_original_semantics_optimization_report.schema.json")


def _validate_schema(payload: dict) -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(payload, schema)


def test_original_semantics_optimization_report_is_research_only() -> None:
    payload = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    _validate_schema(payload)

    assert payload["schema_version"] == "us_etf_original_semantics_optimization_report_v1"
    assert payload["status"] == "research_only_original_semantics"
    assert payload["live_ready"] is False
    assert payload["paper_ready"] is False
    assert payload["baseline_id"] == "original_v8_2_semantics"
    assert payload["rebalance_semantics"] == "calendar_month_end_only_skip_if_not_trading_day"


def test_limited_optimization_preserves_original_semantics_and_improves_baseline() -> None:
    payload = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    baseline_cagr = payload["baseline"]["metrics"]["strategy"]["true_cagr"]
    best = payload["highest_cagr_candidate"]

    assert payload["candidate_count"] >= 8
    assert best["candidate_id"] != payload["baseline_id"]
    assert best["metrics"]["strategy"]["true_cagr"] > baseline_cagr
    assert payload["decision"]["highest_cagr_improvement_vs_original"] > 0.0


def test_optimized_original_semantics_is_not_qqq_replacement() -> None:
    payload = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    best = payload["highest_cagr_candidate"]

    assert best["beats_spy_cagr"] is True
    assert best["beats_qqq_cagr"] is False
    assert payload["decision"]["live_ready"] is False
    assert payload["decision"]["paper_ready"] is False


def test_allowed_and_forbidden_changes_are_explicit() -> None:
    payload = json.loads(REPORT_PATH.read_text(encoding="utf-8"))

    assert "TOP_N" in payload["methodology"]["allowed_changes"]
    assert "TARGET_VOL" in payload["methodology"]["allowed_changes"]
    assert "rebalance semantics" in payload["methodology"]["forbidden_changes"]
    assert "live/paper unlock" in payload["methodology"]["forbidden_changes"]


def test_original_semantics_schema_rejects_live_ready() -> None:
    payload = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    payload["live_ready"] = True
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError:
        return

    raise AssertionError("schema accepted live_ready=true")
