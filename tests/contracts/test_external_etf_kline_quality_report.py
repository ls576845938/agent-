from __future__ import annotations

import copy
import json
from pathlib import Path

import jsonschema


REPORT_PATH = Path("artifacts/us_equity_etf_macro_rotation/latest/external_etf_kline_quality_report.json")
SCHEMA_PATH = Path("schemas/external_etf_kline_quality_report.schema.json")


def test_external_etf_kline_quality_report_matches_schema_and_current_pass_state() -> None:
    payload = _load_report()
    _validate_schema(payload)

    assert payload["schema_version"] == "external_etf_kline_quality_report_v1"
    assert payload["status"] == "pass"
    assert payload["promotion_clean"] is True
    assert payload["blockers"] == []
    assert len(payload["symbols"]) >= 20


def test_each_external_etf_symbol_has_before_after_quality_stats() -> None:
    payload = _load_report()

    for symbol, row in payload["symbols"].items():
        assert row["status"] == "pass", symbol
        assert row["blockers"] == [], symbol
        assert row["before"]["rows"] > 0, symbol
        assert row["after"]["rows"] > 0, symbol
        assert row["after"]["nonpositive_ohlc_rows"] == 0, symbol
        assert row["after"]["short_gap_abs_ret_gt_threshold"] == 0, symbol
        assert row["repair_source"] in {"akshare_raw", "yahoo_chart_raw"}


def test_external_etf_kline_quality_schema_rejects_unknown_status() -> None:
    payload = _load_report()
    payload["status"] = "paper_ready"

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError:
        return

    raise AssertionError("schema accepted unknown status")


def test_external_etf_kline_quality_schema_rejects_malformed_symbol_stats() -> None:
    payload = _load_report()
    mutated = copy.deepcopy(next(iter(payload["symbols"].values())))
    mutated["after"].pop("rows")
    payload["symbols"]["BROKEN"] = mutated

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError:
        return

    raise AssertionError("schema accepted symbol stats without rows")


def _load_report() -> dict:
    return json.loads(REPORT_PATH.read_text(encoding="utf-8"))


def _validate_schema(payload: dict) -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(payload, schema)
