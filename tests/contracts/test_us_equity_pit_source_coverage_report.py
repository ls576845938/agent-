from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pandas as pd

from scripts.build_us_equity_pit_source_coverage_report import build_us_equity_pit_source_coverage_report


SCHEMA = Path("schemas/us_equity_pit_source_coverage_report.schema.json")


def test_pit_source_coverage_marks_price_and_macro_cache_as_partial_not_clean(tmp_path: Path) -> None:
    kline_root = tmp_path / "kline"
    macro_path = tmp_path / "macro/FRED_MACRO.parquet"
    csv_root = tmp_path / "csv_cache"
    kline_root.mkdir(parents=True)
    csv_root.mkdir(parents=True)
    pd.DataFrame(
        [{"datetime": "2026-01-02", "Open": 1.0, "High": 1.0, "Low": 1.0, "Close": 1.0, "Volume": 100}]
    ).to_parquet(kline_root / "SPY.parquet", index=False)
    macro_path.parent.mkdir(parents=True)
    pd.DataFrame([{"datetime": "2026-01-02", "DGS10": 4.0}]).to_parquet(macro_path, index=False)
    (csv_root / "SPY.csv").write_text("Date,Open,High,Low,Close,Volume\n2026-01-02,1,1,1,1,100\n", encoding="utf-8")

    payload = build_us_equity_pit_source_coverage_report(
        repo_root=tmp_path,
        tiingo_kline_root=kline_root,
        external_kline_root=kline_root,
        external_macro=macro_path,
        akshare_cache_root=csv_root,
        output=Path("out/source_coverage.json"),
        markdown_output=Path("out/source_coverage.md"),
        generated_at="2026-06-28T00:00:00Z",
    )

    _validate_schema(payload)
    assert payload["status"] == "source_coverage_partial_not_pit_clean"
    assert payload["summary"] == {
        "required_file_count": 6,
        "satisfied_count": 0,
        "partial_count": 2,
        "missing_count": 4,
        "paper_or_live_unlock_allowed": False,
        "live_order_allowed": False,
    }
    coverage = {item["filename"]: item for item in payload["pit_file_coverage"]}
    assert coverage["adjustment_replay.csv"]["coverage_status"] == "partial"
    assert coverage["macro_release_calendar.csv"]["coverage_status"] == "partial"
    assert coverage["universe_membership_events.csv"]["coverage_status"] == "missing"
    assert coverage["delisted_symbols.csv"]["coverage_status"] == "missing"
    assert all(item["promotion_clean_satisfied"] is False for item in payload["pit_file_coverage"])
    assert payload["guardrails"]["files_copied"] is False
    assert payload["guardrails"]["vendor_data_imported"] is False
    assert payload["guardrails"]["live_order_allowed"] is False
    assert (tmp_path / "out/source_coverage.json").exists()
    assert (tmp_path / "out/source_coverage.md").exists()


def test_pit_source_coverage_schema_rejects_live_unlock(tmp_path: Path) -> None:
    payload = build_us_equity_pit_source_coverage_report(
        repo_root=tmp_path,
        output=Path("out/source_coverage.json"),
        markdown_output=Path("out/source_coverage.md"),
        generated_at="2026-06-28T00:00:00Z",
    )
    payload["guardrails"]["live_order_allowed"] = True

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError:
        return
    raise AssertionError("schema accepted live_order_allowed=true")


def _validate_schema(payload: dict[str, object]) -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    jsonschema.validate(payload, schema)
