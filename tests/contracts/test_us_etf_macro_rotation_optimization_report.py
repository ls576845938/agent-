from __future__ import annotations

import json
from pathlib import Path

import jsonschema


REPORT_PATH = Path("artifacts/us_equity_etf_macro_rotation/latest/us_etf_macro_rotation_optimization_report.json")
SCHEMA_PATH = Path("schemas/us_etf_macro_rotation_optimization_report.schema.json")


def _validate_schema(payload: dict) -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(payload, schema)


def test_us_etf_rotation_optimization_report_contains_all_five_schemes() -> None:
    payload = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    _validate_schema(payload)

    assert payload["schema_version"] == "us_etf_macro_rotation_optimization_report_v1"
    assert payload["status"] == "research_only"
    assert payload["live_ready"] is False
    assert payload["paper_ready"] is False
    assert set(payload["schemes"]) == {
        "v1_macro_floor",
        "v1_turnover_guard",
        "v1_risk_capped_selection",
        "v1_defense_regime_cap",
        "v1_combined_conservative",
    }


def test_each_optimization_scheme_has_best_candidate_and_focus_years() -> None:
    payload = json.loads(REPORT_PATH.read_text(encoding="utf-8"))

    for scheme in payload["schemes"].values():
        assert scheme["candidate_count"] >= 1
        assert scheme["best"]["parameters"]
        assert set(scheme["best"]["focus_years"]) == {"2015", "2022", "2023", "2024"}
        assert scheme["best"]["diagnostics"]["t_plus_1_execution"] is True
        assert scheme["best"]["metrics"]["turnover"] >= 0.0


def test_best_overall_is_selected_from_one_of_the_optimized_schemes() -> None:
    payload = json.loads(REPORT_PATH.read_text(encoding="utf-8"))

    best = payload["best_overall"]
    assert best["scheme_id"] in payload["schemes"]
    matching_scheme = payload["schemes"][best["scheme_id"]]
    assert best["parameters"] == matching_scheme["best"]["parameters"]


def test_us_etf_rotation_optimization_schema_rejects_live_ready() -> None:
    payload = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    payload["live_ready"] = True
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError:
        return

    raise AssertionError("schema accepted live_ready=true")
