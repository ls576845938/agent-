from __future__ import annotations

import json
from pathlib import Path

import jsonschema


REPORT_PATH = Path("artifacts/us_equity_etf_macro_rotation/latest/us_etf_macro_rotation_year_attribution_report.json")
QUALITY_PATH = Path("artifacts/us_equity_etf_macro_rotation/latest/external_etf_kline_quality_report.json")
SCHEMA = Path("schemas/us_etf_macro_rotation_year_attribution_report.schema.json")


def test_us_etf_rotation_year_attribution_report_covers_requested_years() -> None:
    payload = json.loads(REPORT_PATH.read_text(encoding="utf-8"))

    assert payload["schema_version"] == "us_etf_macro_rotation_year_attribution_v1"
    _validate_schema(payload)
    assert set(payload["years"]) == {"2015", "2022", "2023", "2024"}
    for year in payload["years"].values():
        assert "macro_equity_exposure_effect" in year["attribution_additive"]
        assert "momentum_selection_effect" in year["attribution_additive"]
        assert "defense_asset_contribution" in year["attribution_additive"]
        assert "cost_effect" in year["attribution_additive"]
        assert year["exposure"]["avg_actual_offensive_weight"] + year["exposure"]["avg_defense_weight"] <= 1.0000001
        assert year["exposure"]["avg_total_weight"] <= 1.0000001


def test_external_etf_kline_quality_is_promotion_clean_after_qqq_repair() -> None:
    payload = json.loads(QUALITY_PATH.read_text(encoding="utf-8"))
    qqq = payload["symbols"]["QQQ"]

    assert payload["status"] == "pass"
    assert payload["promotion_clean"] is True
    assert payload["blockers"] == []
    assert qqq["repair_source"] == "yahoo_chart_raw"
    assert qqq["after"]["large_calendar_gaps_gt_10d"] == 0
    assert qqq["after"]["abs_ret_gt_threshold"] == 0


def test_us_etf_rotation_year_attribution_schema_rejects_missing_2024() -> None:
    payload = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    del payload["years"]["2024"]

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError:
        return
    raise AssertionError("schema accepted missing 2024 attribution")


def _validate_schema(payload: dict) -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError as exc:
        raise AssertionError(f"schema validation failed: {exc.message}") from exc
