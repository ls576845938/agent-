from __future__ import annotations

import json
from pathlib import Path

import jsonschema


REPORT_PATH = Path("artifacts/us_equity_etf_macro_rotation/latest/us_etf_macro_rotation_cost_stress_report.json")
SCHEMA = Path("schemas/us_etf_macro_rotation_cost_stress_report.schema.json")


def test_cost_stress_report_covers_required_bps_levels() -> None:
    payload = json.loads(REPORT_PATH.read_text(encoding="utf-8"))

    assert payload["schema_version"] == "us_etf_macro_rotation_cost_stress_report_v1"
    _validate_schema(payload)
    assert payload["status"] == "research_only"
    assert payload["live_ready"] is False
    assert payload["paper_ready"] is False
    assert payload["stress_cost_bps"] == [10, 25, 50]


def test_cost_stress_report_covers_baseline_and_all_optimized_schemes() -> None:
    payload = json.loads(REPORT_PATH.read_text(encoding="utf-8"))

    assert set(payload["schemes"]) == {
        "baseline_current",
        "v1_macro_floor",
        "v1_turnover_guard",
        "v1_risk_capped_selection",
        "v1_defense_regime_cap",
        "v1_combined_conservative",
    }
    for scheme in payload["schemes"].values():
        assert set(scheme["stress"]) == {"10bps", "25bps", "50bps"}
        assert scheme["stress"]["50bps"]["metrics"]["turnover"] >= 0.0
        assert "survives_50bps" in scheme


def test_turnover_guard_survives_50bps_and_baseline_does_not() -> None:
    payload = json.loads(REPORT_PATH.read_text(encoding="utf-8"))

    assert payload["best_50bps"]["scheme_id"] == "v1_turnover_guard"
    assert payload["schemes"]["v1_turnover_guard"]["survives_50bps"] is True
    assert payload["schemes"]["baseline_current"]["survives_50bps"] is False


def test_cost_stress_schema_rejects_live_ready() -> None:
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
