from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pandas as pd

from scripts.build_us_equity_candidate_bundle_evidence_report import (
    build_us_equity_candidate_bundle_evidence_report,
)


SCHEMA = Path("schemas/us_equity_candidate_bundle_evidence_report.schema.json")


def test_candidate_bundle_evidence_reports_research_inputs_without_promotion(tmp_path: Path) -> None:
    kline_root = tmp_path / "tiingo/kline"
    kline_root.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "datetime": "2026-06-23T00:00:00Z",
                "symbol": "SPY",
                "Open": 10.0,
                "High": 11.0,
                "Low": 9.0,
                "Close": 10.5,
                "Volume": 1000,
                "RawOpen": 10.0,
                "RawHigh": 11.0,
                "RawLow": 9.0,
                "RawClose": 10.5,
                "RawVolume": 1000,
                "DivCash": 0.1,
                "SplitFactor": 1.0,
                "source": "tiingo_eod",
            }
        ]
    ).to_parquet(kline_root / "SPY.parquet")
    fred = tmp_path / "fred_macro.csv"
    fred.write_text(
        "timestamp_utc,DGS10,realtime_start,realtime_end\n"
        "2026-06-23T00:00:00Z,4.5,2026-06-24,2026-06-24\n",
        encoding="utf-8",
    )

    payload = build_us_equity_candidate_bundle_evidence_report(
        repo_root=tmp_path,
        tiingo_kline_root=kline_root,
        fred_macro_path=fred,
        output=Path("out/evidence.json"),
        markdown_output=Path("out/evidence.md"),
        generated_at="2026-06-25T00:00:00Z",
    )

    _validate_schema(payload)
    assert payload["status"] == "candidate_evidence_ready_for_manual_bundle_build"
    assert payload["evidence_available"]["price_bars"] is True
    assert payload["evidence_available"]["fred_realtime_columns"] is True
    assert "pit_universe_membership_events" in payload["missing_production_contract_groups"]
    assert "candidate_evidence_does_not_grant_promotion_clean" in payload["blockers"]
    assert payload["guardrails"]["promotion_clean_granted_by_this_report"] is False
    assert payload["guardrails"]["live_order_allowed"] is False
    assert (tmp_path / "out/evidence.json").exists()
    assert (tmp_path / "out/evidence.md").exists()


def test_candidate_bundle_evidence_blocks_when_research_inputs_are_missing(tmp_path: Path) -> None:
    payload = build_us_equity_candidate_bundle_evidence_report(
        repo_root=tmp_path,
        tiingo_kline_root=Path("missing/kline"),
        fred_macro_path=Path("missing/fred_macro.csv"),
        output=Path("out/evidence.json"),
        markdown_output=Path("out/evidence.md"),
        generated_at="2026-06-25T00:00:00Z",
    )

    _validate_schema(payload)
    assert payload["status"] == "candidate_evidence_blocked"
    assert "tiingo_research_price_bars_missing" in payload["blockers"]
    assert "fred_macro_csv_missing" in payload["blockers"]


def test_candidate_bundle_evidence_schema_rejects_live_unlock(tmp_path: Path) -> None:
    payload = build_us_equity_candidate_bundle_evidence_report(
        repo_root=tmp_path,
        tiingo_kline_root=Path("missing/kline"),
        fred_macro_path=Path("missing/fred_macro.csv"),
        output=Path("out/evidence.json"),
        markdown_output=Path("out/evidence.md"),
        generated_at="2026-06-25T00:00:00Z",
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
