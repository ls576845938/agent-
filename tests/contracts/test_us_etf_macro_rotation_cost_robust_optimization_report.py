from __future__ import annotations

import json
from pathlib import Path

import jsonschema


REPORT_PATH = Path(
    "artifacts/us_equity_etf_macro_rotation/latest/us_etf_macro_rotation_cost_robust_optimization_report.json"
)
SCHEMA_PATH = Path("schemas/us_etf_macro_rotation_cost_robust_optimization_report.schema.json")


def _validate_schema(payload: dict) -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(payload, schema)


def test_cost_robust_optimization_report_is_research_only() -> None:
    payload = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    _validate_schema(payload)

    assert payload["schema_version"] == "us_etf_macro_rotation_cost_robust_optimization_report_v1"
    assert payload["status"] == "research_only"
    assert payload["live_ready"] is False
    assert payload["paper_ready"] is False
    assert payload["stress_cost_bps"] == [10, 25, 50]


def test_cost_robust_optimization_contains_v1_and_v2_families() -> None:
    payload = json.loads(REPORT_PATH.read_text(encoding="utf-8"))

    assert set(payload["families"]) == {
        "v1_turnover_guard",
        "v1_combined_conservative",
        "v2_turnover_guard_refined",
        "v2_cost_robust_combined",
    }
    for family in payload["families"].values():
        assert family["candidate_count"] >= 1
        best = family["best"]
        assert set(best["stress"]) == {"10bps", "25bps", "50bps"}
        assert best["stress"]["50bps"]["diagnostics"]["t_plus_1_execution"] is True


def test_v2_cost_robust_best_reduces_turnover_vs_v1_turnover_guard() -> None:
    payload = json.loads(REPORT_PATH.read_text(encoding="utf-8"))

    best = payload["best_overall"]
    v1 = payload["families"]["v1_turnover_guard"]["best"]
    assert best["family"] == "v2_turnover_guard_refined"
    assert best["stress"]["50bps"]["metrics"]["turnover"] < v1["stress"]["50bps"]["metrics"]["turnover"]
    assert best["stress"]["50bps"]["metrics"]["max_drawdown"] > v1["stress"]["50bps"]["metrics"]["max_drawdown"]
    assert "max_monthly_turnover" in best["parameters"]


def test_cost_robust_schema_rejects_live_ready() -> None:
    payload = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    payload["live_ready"] = True
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError:
        return

    raise AssertionError("schema accepted live_ready=true")
