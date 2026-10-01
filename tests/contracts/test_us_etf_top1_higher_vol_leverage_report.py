from __future__ import annotations

import json
from pathlib import Path

import jsonschema


REPORT_PATH = Path("artifacts/us_equity_etf_macro_rotation/latest/us_etf_top1_higher_vol_leverage_report.json")
SCHEMA_PATH = Path("schemas/us_etf_top1_higher_vol_leverage_report.schema.json")


def _validate_schema(payload: dict) -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(payload, schema)


def test_leverage_report_is_research_only_and_asset_neutral() -> None:
    payload = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    _validate_schema(payload)

    assert payload["schema_version"] == "us_etf_top1_higher_vol_leverage_report_v1"
    assert payload["status"] == "research_only_no_live_or_paper"
    assert payload["live_ready"] is False
    assert payload["paper_ready"] is False
    assert "No QQQ/sector/technology preference" in payload["asset_selection_bias_guard"]
    assert payload["leverage_model"] == "portfolio_return_overlay_no_asset_selection_changes"


def test_leverage_report_includes_financing_and_benchmarks() -> None:
    payload = json.loads(REPORT_PATH.read_text(encoding="utf-8"))

    assert payload["financing_rate"] > 0.0
    assert set(payload["benchmarks"]) == {"SPY", "QQQ"}
    assert payload["base_unlevered"]["metrics"]["true_cagr"] > payload["benchmarks"]["SPY"]["true_cagr"]
    assert payload["base_unlevered"]["metrics"]["true_cagr"] < payload["benchmarks"]["QQQ"]["true_cagr"]


def test_some_leveraged_variants_beat_qqq_with_lower_drawdown() -> None:
    payload = json.loads(REPORT_PATH.read_text(encoding="utf-8"))

    qqq = payload["benchmarks"]["QQQ"]
    qualified = [row for row in payload["variants"] if row["beats_QQQ_with_lower_drawdown"]]
    assert qualified
    for row in qualified:
        assert row["metrics"]["true_cagr"] > qqq["true_cagr"]
        assert row["metrics"]["max_drawdown"] > qqq["max_drawdown"]
    assert payload["decision"]["qqq_beater_count"] == len(qualified)
    assert payload["decision"]["live_ready"] is False
    assert payload["decision"]["paper_ready"] is False


def test_vol_target_variants_are_present() -> None:
    payload = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    variant_ids = {row["variant_id"] for row in payload["variants"]}

    assert "fixed_2x" in variant_ids
    assert "vol_target_20pct_cap1.5x" in variant_ids
    assert "vol_target_25pct_cap1.5x" in variant_ids
    assert any(row["variant_id"].endswith("_dd_delever") for row in payload["variants"])


def test_leverage_schema_rejects_live_ready() -> None:
    payload = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    payload["live_ready"] = True
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError:
        return

    raise AssertionError("schema accepted live_ready=true")
