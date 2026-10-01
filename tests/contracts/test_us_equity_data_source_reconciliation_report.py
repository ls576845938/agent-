from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from scripts.build_us_equity_data_source_reconciliation_report import (
    build_us_equity_data_source_reconciliation_report,
)


SCHEMA = Path("schemas/us_equity_data_source_reconciliation_report.schema.json")


def test_data_source_reconciliation_reconciles_research_source_but_keeps_promotion_blocked(tmp_path: Path) -> None:
    _write_research_report(tmp_path, selected_source="tiingo_eod", missing_symbols=[])
    _write_tiingo_import(tmp_path, status="pass")
    _write_data_status(tmp_path, promotion_clean=False)
    _write_external_quality(tmp_path)
    _write_macro_lag(tmp_path)

    payload = build_us_equity_data_source_reconciliation_report(
        repo_root=tmp_path,
        output=Path("out/reconciliation.json"),
        markdown_output=Path("out/reconciliation.md"),
        generated_at="2026-06-25T00:00:00Z",
    )

    assert payload["schema_version"] == "us_equity_data_source_reconciliation_report_v1"
    _validate_schema(payload)
    assert payload["status"] == "research_reconciled_promotion_blocked"
    assert payload["selected_price_source"] == "tiingo_eod"
    assert payload["summary"]["required_symbol_count"] == 2
    assert payload["summary"]["available_symbol_count"] == 2
    assert payload["summary"]["tiingo_import_status"] == "pass"
    assert payload["summary"]["data_promotion_clean"] is False
    assert payload["symbol_reconciliation"][0]["selected_end"] == "2026-06-24"
    assert "us_equity_data_lineage_not_promotion_clean" in payload["blockers"]
    assert payload["guardrails"]["promotion_clean_granted_by_this_report"] is False
    assert payload["guardrails"]["live_order_allowed"] is False
    assert (tmp_path / "out/reconciliation.json").exists()
    assert (tmp_path / "out/reconciliation.md").exists()


def test_data_source_reconciliation_blocks_when_research_report_missing(tmp_path: Path) -> None:
    payload = build_us_equity_data_source_reconciliation_report(
        repo_root=tmp_path,
        output=Path("out/reconciliation.json"),
        markdown_output=Path("out/reconciliation.md"),
        generated_at="2026-06-25T00:00:00Z",
    )

    assert payload["status"] == "blocked"
    _validate_schema(payload)
    assert "us_equity_research_report_missing" in payload["blockers"]
    assert "us_equity_tiingo_import_not_pass" in payload["blockers"]
    assert payload["guardrails"]["paper_simulation_allowed"] is False


def test_data_source_reconciliation_blocks_missing_required_symbol(tmp_path: Path) -> None:
    _write_research_report(tmp_path, selected_source="tiingo_eod", missing_symbols=["QQQ"])
    _write_tiingo_import(tmp_path, status="pass")
    _write_data_status(tmp_path, promotion_clean=True)
    _write_external_quality(tmp_path)
    _write_macro_lag(tmp_path)

    payload = build_us_equity_data_source_reconciliation_report(
        repo_root=tmp_path,
        output=Path("out/reconciliation.json"),
        markdown_output=Path("out/reconciliation.md"),
        generated_at="2026-06-25T00:00:00Z",
    )

    assert payload["status"] == "blocked"
    _validate_schema(payload)
    assert payload["summary"]["missing_symbols"] == ["QQQ"]
    assert "us_equity_selected_source_missing_required_symbols" in payload["blockers"]


def test_data_source_reconciliation_schema_rejects_promotion_clean_unlock(tmp_path: Path) -> None:
    _write_research_report(tmp_path, selected_source="tiingo_eod", missing_symbols=[])
    _write_tiingo_import(tmp_path, status="pass")
    _write_data_status(tmp_path, promotion_clean=False)
    _write_external_quality(tmp_path)
    _write_macro_lag(tmp_path)
    payload = build_us_equity_data_source_reconciliation_report(
        repo_root=tmp_path,
        output=Path("out/reconciliation.json"),
        markdown_output=Path("out/reconciliation.md"),
        generated_at="2026-06-25T00:00:00Z",
    )
    payload["guardrails"]["promotion_clean_granted_by_this_report"] = True

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError:
        return
    raise AssertionError("schema accepted promotion_clean_granted_by_this_report=true")


def _write_research_report(root: Path, *, selected_source: str, missing_symbols: list[str]) -> None:
    required = ["SPY", "QQQ"]
    available = [symbol for symbol in required if symbol not in missing_symbols]
    coverage = {
        symbol: {
            "status": "available" if symbol in available else "missing",
            "start": "2000-01-03" if symbol in available else None,
            "end": "2026-06-24" if symbol in available else None,
            "rows": 1000 if symbol in available else 0,
        }
        for symbol in required
    }
    path = root / "artifacts/us_equity_etf_macro_rotation/latest/us_etf_macro_rotation_research_report.json"
    _write_json(
        path,
        {
            "status": "partial",
            "data": {
                "price_source": selected_source,
                "price_root": "data/external/us_equity_eod/tiingo",
                "required_symbols": required,
                "available_symbols": available,
                "missing_symbols": missing_symbols,
                "coverage": coverage,
                "tiingo_eod_coverage": coverage,
                "canonical_cleaned_coverage": {
                    "SPY": {"status": "available_unread"},
                    "QQQ": {"status": "available_unread"},
                },
                "external_data_lake_coverage": coverage,
            },
        },
    )


def _write_tiingo_import(root: Path, *, status: str) -> None:
    _write_json(
        root / "artifacts/us_equity_data_status/latest/tiingo_eod_import_report.json",
        {
            "status": status,
            "summary": {
                "available_symbol_count": 2,
                "latest_common_date": "2026-06-24",
            },
        },
    )


def _write_data_status(root: Path, *, promotion_clean: bool) -> None:
    _write_json(
        root / "artifacts/us_equity_data_status/latest/data_status_report.json",
        {
            "status": "pass" if promotion_clean else "partial",
            "promotion_clean": promotion_clean,
            "blockers": [] if promotion_clean else ["data_lineage_not_promotion_clean"],
        },
    )


def _write_external_quality(root: Path) -> None:
    _write_json(
        root / "artifacts/us_equity_etf_macro_rotation/latest/external_etf_kline_quality_report.json",
        {"status": "pass", "promotion_clean": True, "blockers": []},
    )


def _write_macro_lag(root: Path) -> None:
    _write_json(
        root / "artifacts/us_equity_data_lineage/latest/us_equity_macro_release_lag_policy_report.json",
        {"status": "research_lag_only_release_calendar_missing", "blockers": ["fred_release_calendar_missing"]},
    )


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _validate_schema(payload: dict[str, object]) -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError as exc:
        raise AssertionError(f"schema validation failed: {exc.message}") from exc
