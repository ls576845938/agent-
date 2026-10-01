from __future__ import annotations

import json
from pathlib import Path

import jsonschema


REPORT_PATH = Path("artifacts/us_equity_etf_macro_rotation/latest/us_etf_top1_higher_vol_validation_report.json")
SCHEMA_PATH = Path("schemas/us_etf_top1_higher_vol_validation_report.schema.json")


def _validate_schema(payload: dict) -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(payload, schema)


def test_top1_higher_vol_validation_report_is_research_only() -> None:
    payload = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    _validate_schema(payload)

    assert payload["schema_version"] == "us_etf_top1_higher_vol_validation_report_v1"
    assert payload["status"] == "research_only_validation"
    assert payload["live_ready"] is False
    assert payload["paper_ready"] is False
    assert payload["strategy_id"] == "top1_higher_vol"
    assert payload["rebalance_semantics"] == "calendar_month_end_only_skip_if_not_trading_day"


def test_top1_higher_vol_improves_original_but_does_not_unlock_live() -> None:
    payload = json.loads(REPORT_PATH.read_text(encoding="utf-8"))

    assert payload["primary_metrics"]["strategy"]["true_cagr"] > payload["baseline_metrics"]["strategy"]["true_cagr"]
    assert payload["decision"]["primary_improves_baseline"] is True
    assert payload["decision"]["status"] == "manual_review_candidate"
    assert payload["decision"]["live_ready"] is False
    assert payload["decision"]["paper_ready"] is False


def test_cost_stress_and_parameter_neighborhood_are_present() -> None:
    payload = json.loads(REPORT_PATH.read_text(encoding="utf-8"))

    assert set(payload["cost_stress"]) == {"0x", "1x", "2x", "3x"}
    assert payload["cost_stress"]["3x"]["metrics"]["strategy"]["true_cagr"] > payload["baseline_metrics"]["strategy"]["true_cagr"]
    assert payload["parameter_neighborhood"]["candidate_count"] == 18
    assert payload["parameter_neighborhood"]["alive_rate"] >= 0.60
    assert payload["parameter_neighborhood"]["best"]["parameters"] == payload["primary_parameters"]


def test_walk_forward_exists_and_remains_below_qqq() -> None:
    payload = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    wf = payload["walk_forward"]

    assert wf["fold_count"] >= 5
    assert wf["aggregate_oos"]["metrics"]["strategy"]["true_cagr"] > 0.0
    assert (
        wf["aggregate_oos"]["metrics"]["strategy"]["true_cagr"]
        < wf["aggregate_oos"]["metrics"]["QQQ"]["true_cagr"]
    )
    for fold in wf["folds"]:
        assert fold["selected_parameters"]
        assert "test_metrics" in fold


def test_yearly_breakdown_covers_current_sample() -> None:
    payload = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    years = {row["year"] for row in payload["yearly_breakdown"]}

    assert min(years) == 2018
    assert max(years) >= 2026
    assert any(row["strategy_return"] < 0.0 for row in payload["yearly_breakdown"])


def test_top1_higher_vol_validation_schema_rejects_live_ready() -> None:
    payload = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    payload["live_ready"] = True
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError:
        return

    raise AssertionError("schema accepted live_ready=true")
