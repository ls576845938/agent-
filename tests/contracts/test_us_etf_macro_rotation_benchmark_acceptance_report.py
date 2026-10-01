from __future__ import annotations

import json
from pathlib import Path

import jsonschema


REPORT_PATH = Path(
    "artifacts/us_equity_etf_macro_rotation/latest/us_etf_macro_rotation_benchmark_acceptance_report.json"
)
SCHEMA = Path("schemas/us_etf_macro_rotation_benchmark_acceptance_report.schema.json")


def test_benchmark_acceptance_report_is_research_only() -> None:
    payload = json.loads(REPORT_PATH.read_text(encoding="utf-8"))

    assert payload["schema_version"] == "us_etf_macro_rotation_benchmark_acceptance_report_v1"
    _validate_schema(payload)
    assert payload["status"] == "research_only"
    assert payload["live_ready"] is False
    assert payload["paper_ready"] is False
    assert payload["decision"]["live_order_allowed"] is False
    assert payload["decision"]["paper_promotion_allowed"] is False
    assert payload["protected_original_baseline"]["baseline_id"] == "original_v8_2_semantics"
    assert payload["protected_original_baseline"]["included_in_candidate_ranking"] is False


def test_benchmark_acceptance_uses_spy_qqq_and_static_alternatives() -> None:
    payload = json.loads(REPORT_PATH.read_text(encoding="utf-8"))

    assert set(payload["benchmarks"]) == {
        "SPY",
        "QQQ",
        "60_40_SPY_IEF",
        "equal_offensive_etf",
    }
    assert payload["benchmarks"]["QQQ"]["cagr"] > payload["benchmarks"]["SPY"]["cagr"]
    assert payload["benchmarks"]["SPY"]["cagr"] > 0.0


def test_no_candidate_is_misclassified_as_spy_qqq_replacement_without_cagr_edge() -> None:
    payload = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    qqq_cagr = payload["benchmarks"]["QQQ"]["cagr"]

    for row in payload["candidates"]:
        if row["offensive_replacement_pass"]:
            assert row["metrics_50bps"]["cagr"] > qqq_cagr
            assert row["gate_status"] == "offensive_replacement_pass"
    if payload["summary"]["offensive_replacement_pass_count"] == 0:
        assert payload["decision"]["status"] != "offensive_replacement_candidate_for_manual_review"


def test_defensive_candidates_must_have_drawdown_improvement() -> None:
    payload = json.loads(REPORT_PATH.read_text(encoding="utf-8"))

    assert payload["summary"]["candidate_count"] >= 20
    defensive = [row for row in payload["candidates"] if row["defensive_candidate_pass"]]
    assert defensive
    for row in defensive:
        assert row["excess_vs_spy"]["max_drawdown_improvement"] > 0.0
        assert row["metrics_50bps"]["sharpe"] > payload["benchmarks"]["SPY"]["sharpe"]


def test_original_semantics_baseline_is_not_mixed_into_rankings() -> None:
    payload = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    protected = payload["protected_original_baseline"]

    assert protected["status"] == "available"
    assert protected["metrics"]["strategy_true_cagr"] > 0.0
    ranked_families = {row["family"] for row in payload["candidates"]}
    assert protected["baseline_id"] not in ranked_families
    assert "not mixed into rankings" in payload["methodology"]["original_semantics_boundary"]


def test_benchmark_acceptance_schema_rejects_paper_promotion() -> None:
    payload = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    payload["decision"]["paper_promotion_allowed"] = True

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError:
        return
    raise AssertionError("schema accepted paper_promotion_allowed=true")


def _validate_schema(payload: dict) -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError as exc:
        raise AssertionError(f"schema validation failed: {exc.message}") from exc
