from __future__ import annotations

import json
from pathlib import Path

import jsonschema


REPORT_PATH = Path(
    "artifacts/us_equity_etf_macro_rotation/latest/us_etf_macro_rotation_walk_forward_stability_report.json"
)
SCHEMA = Path("schemas/us_etf_macro_rotation_walk_forward_stability_report.schema.json")


def test_walk_forward_stability_report_is_research_only() -> None:
    payload = json.loads(REPORT_PATH.read_text(encoding="utf-8"))

    assert payload["schema_version"] == "us_etf_macro_rotation_walk_forward_stability_report_v1"
    _validate_schema(payload)
    assert payload["status"] == "research_only"
    assert payload["live_ready"] is False
    assert payload["paper_ready"] is False
    assert payload["primary_cost_bps"] == 50


def test_parameter_stability_checks_a_neighborhood_not_single_parameter() -> None:
    payload = json.loads(REPORT_PATH.read_text(encoding="utf-8"))

    assert payload["parameter_grid"]["candidate_count"] == 36
    assert len(payload["all_candidates"]) == 36
    assert payload["parameter_grid"]["base_parameters"] in [
        candidate["parameters"] for candidate in payload["all_candidates"]
    ]
    assert payload["stability"]["candidate_count"] == 36
    assert 0.0 <= payload["stability"]["alive_rate"] <= 1.0
    assert "median" in payload["stability"]


def test_walk_forward_has_rolling_oos_folds_and_aggregate_metrics() -> None:
    payload = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    walk_forward = payload["walk_forward"]

    assert walk_forward["fold_count"] >= 8
    assert 0.0 <= walk_forward["oos_alive_rate"] <= 1.0
    assert walk_forward["aggregate_oos_metrics"]["turnover"] >= 0.0
    for fold in walk_forward["folds"]:
        assert len(fold["train_years"]) == payload["train_years"]
        assert fold["test_year"] not in fold["train_years"]
        assert fold["selected_parameters"]
        assert "test_metrics" in fold


def test_walk_forward_best_candidate_remains_t_plus_1_safe() -> None:
    payload = json.loads(REPORT_PATH.read_text(encoding="utf-8"))

    assert payload["base_candidate"]["t_plus_1_execution"] is True
    assert payload["best_full_sample"]["t_plus_1_execution"] is True


def test_walk_forward_stability_schema_rejects_live_ready() -> None:
    payload = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    payload["live_ready"] = True

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError:
        return
    raise AssertionError("schema accepted live_ready=true")


def _validate_schema(payload: dict) -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError as exc:
        raise AssertionError(f"schema validation failed: {exc.message}") from exc
