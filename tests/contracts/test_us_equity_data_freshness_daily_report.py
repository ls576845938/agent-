from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from scripts.build_us_equity_data_freshness_daily_report import build_us_equity_data_freshness_daily_report


SCHEMA = Path("schemas/us_equity_data_freshness_daily_report.schema.json")


def test_data_freshness_blocks_when_fred_macro_missing(tmp_path: Path) -> None:
    tiingo, data_status = _write_reports(tmp_path, latest_common_date="2026-06-24")

    payload = build_us_equity_data_freshness_daily_report(
        repo_root=tmp_path,
        tiingo_report=tiingo,
        data_status=data_status,
        output=tmp_path / "freshness.json",
        markdown_output=tmp_path / "freshness.md",
        as_of_date="2026-06-25",
        generated_at="2026-06-25T00:00:00Z",
    )

    assert payload["status"] == "blocked"
    _validate_schema(payload)
    assert payload["price_freshness"]["passed"] is True
    assert payload["price_freshness"]["stale_calendar_days"] == 1
    assert payload["macro_freshness"]["status"] == "missing"
    assert "us_equity_freshness_fred_macro_data_missing" in payload["blockers"]
    assert payload["guardrails"]["live_order_allowed"] is False
    assert (tmp_path / "freshness.md").exists()


def test_data_freshness_blocks_stale_prices(tmp_path: Path) -> None:
    tiingo, data_status = _write_reports(tmp_path, latest_common_date="2026-06-01")
    fred = tmp_path / "artifacts/us_equity_data_status/latest/fred_macro_import_report.json"
    fred.parent.mkdir(parents=True)
    fred.write_text(json.dumps({"latest_common_date": "2026-06-24"}), encoding="utf-8")

    payload = build_us_equity_data_freshness_daily_report(
        repo_root=tmp_path,
        tiingo_report=tiingo,
        data_status=data_status,
        output=tmp_path / "freshness.json",
        markdown_output=tmp_path / "freshness.md",
        as_of_date="2026-06-25",
        generated_at="2026-06-25T00:00:00Z",
    )

    assert payload["status"] == "blocked"
    _validate_schema(payload)
    assert "us_equity_freshness_prices_stale" in payload["blockers"]
    assert payload["macro_freshness"]["status"] == "present"


def test_data_freshness_passes_when_prices_and_fred_are_fresh(tmp_path: Path) -> None:
    tiingo, data_status = _write_reports(tmp_path, latest_common_date="2026-06-24")
    fred = tmp_path / "artifacts/us_equity_data_status/latest/fred_macro_import_report.json"
    fred.parent.mkdir(parents=True)
    fred.write_text(json.dumps({"latest_common_date": "2026-06-24"}), encoding="utf-8")

    payload = build_us_equity_data_freshness_daily_report(
        repo_root=tmp_path,
        tiingo_report=tiingo,
        data_status=data_status,
        output=tmp_path / "freshness.json",
        markdown_output=tmp_path / "freshness.md",
        as_of_date="2026-06-25",
        generated_at="2026-06-25T00:00:00Z",
    )

    assert payload["status"] == "pass"
    _validate_schema(payload)
    assert payload["blockers"] == []
    assert payload["macro_freshness"]["passed"] is True
    assert payload["guardrails"]["forward_runner_must_block_on_status_blocked"] is True


def test_data_freshness_blocks_failed_fred_import_report(tmp_path: Path) -> None:
    tiingo, data_status = _write_reports(tmp_path, latest_common_date="2026-06-24")
    fred = tmp_path / "artifacts/us_equity_data_status/latest/fred_macro_import_report.json"
    fred.parent.mkdir(parents=True)
    fred.write_text(
        json.dumps(
            {
                "status": "blocked",
                "latest_common_date": None,
                "blockers": ["fred_series_fetch_failed:DGS10"],
            }
        ),
        encoding="utf-8",
    )

    payload = build_us_equity_data_freshness_daily_report(
        repo_root=tmp_path,
        tiingo_report=tiingo,
        data_status=data_status,
        output=tmp_path / "freshness.json",
        markdown_output=tmp_path / "freshness.md",
        as_of_date="2026-06-25",
        generated_at="2026-06-25T00:00:00Z",
    )

    assert payload["status"] == "blocked"
    _validate_schema(payload)
    assert payload["macro_freshness"]["source_status"] == "blocked"
    assert "us_equity_freshness_fred_macro_data_missing" in payload["blockers"]


def test_data_freshness_uses_local_fred_csv_when_current_import_fetch_fails(tmp_path: Path) -> None:
    tiingo, data_status = _write_reports(tmp_path, latest_common_date="2026-06-24")
    fred = tmp_path / "artifacts/us_equity_data_status/latest/fred_macro_import_report.json"
    fred.parent.mkdir(parents=True)
    fred.write_text(
        json.dumps(
            {
                "status": "blocked",
                "latest_common_date": None,
                "blockers": ["fred_series_fetch_failed:DGS10"],
            }
        ),
        encoding="utf-8",
    )
    macro_csv = tmp_path / "data/external/us_equity_macro/fred_macro.csv"
    macro_csv.parent.mkdir(parents=True)
    macro_csv.write_text("timestamp_utc,DGS10,DGS2\n2026-06-24T00:00:00Z,4.0,3.8\n", encoding="utf-8")

    payload = build_us_equity_data_freshness_daily_report(
        repo_root=tmp_path,
        tiingo_report=tiingo,
        data_status=data_status,
        output=tmp_path / "freshness.json",
        markdown_output=tmp_path / "freshness.md",
        as_of_date="2026-06-25",
        generated_at="2026-06-25T00:00:00Z",
    )

    assert payload["status"] == "pass"
    _validate_schema(payload)
    assert payload["macro_freshness"]["status"] == "present"
    assert payload["macro_freshness"]["source_status"] == "fallback_after_blocked_import"
    assert "us_equity_freshness_fred_import_blocked_using_local_csv_snapshot" in payload["warnings"]
    assert payload["guardrails"]["live_order_allowed"] is False


def test_data_freshness_schema_rejects_live_order_allowed(tmp_path: Path) -> None:
    tiingo, data_status = _write_reports(tmp_path, latest_common_date="2026-06-24")
    fred = tmp_path / "artifacts/us_equity_data_status/latest/fred_macro_import_report.json"
    fred.parent.mkdir(parents=True)
    fred.write_text(json.dumps({"latest_common_date": "2026-06-24"}), encoding="utf-8")
    payload = build_us_equity_data_freshness_daily_report(
        repo_root=tmp_path,
        tiingo_report=tiingo,
        data_status=data_status,
        output=tmp_path / "freshness.json",
        markdown_output=tmp_path / "freshness.md",
        as_of_date="2026-06-25",
        generated_at="2026-06-25T00:00:00Z",
    )
    payload["guardrails"]["live_order_allowed"] = True

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError:
        return
    raise AssertionError("schema accepted live_order_allowed=true")


def _write_reports(tmp_path: Path, *, latest_common_date: str) -> tuple[Path, Path]:
    tiingo = tmp_path / "tiingo.json"
    data_status = tmp_path / "data_status.json"
    tiingo.write_text(
        json.dumps(
            {
                "status": "pass",
                "provider": "tiingo",
                "symbol_count": 24,
                "missing_symbols": [],
                "summary": {"latest_common_date": latest_common_date},
                "guardrails": {
                    "live_order_allowed": False,
                    "private_endpoint_used": False,
                    "order_endpoint_used": False,
                    "real_order_submitted": False,
                },
            }
        ),
        encoding="utf-8",
    )
    data_status.write_text(
        json.dumps(
            {
                "status": "partial",
                "promotion_clean": False,
                "data_lineage_grade": "research",
                "blockers": ["point_in_time_universe_not_confirmed"],
                "guardrails": {
                    "live_order_allowed": False,
                    "private_endpoint_used": False,
                    "order_endpoint_used": False,
                    "real_order_submitted": False,
                },
            }
        ),
        encoding="utf-8",
    )
    return tiingo, data_status


def _validate_schema(payload: dict[str, object]) -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError as exc:
        raise AssertionError(f"schema validation failed: {exc.message}") from exc
