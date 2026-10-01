from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pandas as pd

from quant_us.research.us_etf_macro_momentum_rotation import UsEtfMacroMomentumRotationConfig
from scripts.build_us_equity_macro_release_lag_policy_report import (
    build_us_equity_macro_release_lag_policy_report,
)


SCHEMA = Path("schemas/us_equity_macro_release_lag_policy_report.schema.json")


def test_macro_release_lag_policy_reports_research_lag_when_release_calendar_missing(tmp_path: Path) -> None:
    _write_macro_csv(tmp_path / "data/external/us_equity_macro/fred_macro.csv", include_release_fields=False)
    _write_fred_import_report(tmp_path)

    payload = build_us_equity_macro_release_lag_policy_report(
        repo_root=tmp_path,
        output=Path("out/macro_lag.json"),
        markdown_output=Path("out/macro_lag.md"),
        generated_at="2026-06-25T00:00:00Z",
    )

    assert payload["schema_version"] == "us_equity_macro_release_lag_policy_report_v1"
    _validate_schema(payload)
    assert payload["status"] == "research_lag_only_release_calendar_missing"
    assert payload["policy"]["macro_lag_days"] == 2
    assert payload["source_checks"]["alpha_uses_cfg_macro_lag_shift"] is True
    assert payload["source_checks"]["research_uses_cfg_macro_lag_shift"] is True
    assert payload["macro_source"]["release_calendar_fields_present"] is False
    assert "fred_release_calendar_missing" in payload["blockers"]
    assert "macro_revision_vintage_missing" in payload["blockers"]
    assert payload["guardrails"]["research_lag_proxy_is_not_production_pit"] is True
    assert payload["guardrails"]["promotion_clean_granted_by_this_report"] is False
    assert payload["guardrails"]["live_order_allowed"] is False
    assert (tmp_path / "out/macro_lag.json").exists()
    assert (tmp_path / "out/macro_lag.md").exists()


def test_macro_release_lag_policy_blocks_when_macro_data_missing(tmp_path: Path) -> None:
    payload = build_us_equity_macro_release_lag_policy_report(
        repo_root=tmp_path,
        output=Path("out/macro_lag.json"),
        markdown_output=Path("out/macro_lag.md"),
        generated_at="2026-06-25T00:00:00Z",
    )

    assert payload["status"] == "blocked"
    _validate_schema(payload)
    assert "fred_macro_data_missing" in payload["blockers"]
    assert payload["guardrails"]["live_order_allowed"] is False


def test_macro_release_lag_policy_ready_when_release_fields_exist(tmp_path: Path) -> None:
    _write_macro_csv(tmp_path / "data/external/us_equity_macro/fred_macro.csv", include_release_fields=True)
    _write_fred_import_report(tmp_path)

    payload = build_us_equity_macro_release_lag_policy_report(
        repo_root=tmp_path,
        output=Path("out/macro_lag.json"),
        markdown_output=Path("out/macro_lag.md"),
        generated_at="2026-06-25T00:00:00Z",
    )

    assert payload["status"] == "macro_release_lag_policy_ready_for_validation"
    _validate_schema(payload)
    assert payload["blockers"] == []
    assert payload["macro_source"]["release_calendar_fields_present"] is True
    assert payload["guardrails"]["promotion_clean_granted_by_this_report"] is False
    assert payload["guardrails"]["paper_simulation_allowed"] is False


def test_macro_release_lag_policy_still_requires_release_calendar_with_vintage_only(tmp_path: Path) -> None:
    _write_macro_csv(
        tmp_path / "data/external/us_equity_macro/fred_macro.csv",
        include_release_fields=False,
        include_vintage_fields=True,
    )
    _write_fred_import_report(tmp_path)

    payload = build_us_equity_macro_release_lag_policy_report(
        repo_root=tmp_path,
        output=Path("out/macro_lag.json"),
        markdown_output=Path("out/macro_lag.md"),
        generated_at="2026-06-25T00:00:00Z",
    )

    assert payload["status"] == "research_lag_only_release_calendar_missing"
    _validate_schema(payload)
    assert "fred_release_calendar_missing" in payload["blockers"]
    assert "macro_revision_vintage_missing" not in payload["blockers"]
    assert payload["macro_source"]["vintage_fields_present"] is True
    assert payload["macro_source"]["release_date_fields_present"] is False
    assert payload["guardrails"]["promotion_clean_granted_by_this_report"] is False


def test_macro_release_lag_policy_blocks_when_config_lag_is_zero(tmp_path: Path) -> None:
    _write_macro_csv(tmp_path / "data/external/us_equity_macro/fred_macro.csv", include_release_fields=True)
    _write_fred_import_report(tmp_path)

    payload = build_us_equity_macro_release_lag_policy_report(
        repo_root=tmp_path,
        output=Path("out/macro_lag.json"),
        markdown_output=Path("out/macro_lag.md"),
        config=UsEtfMacroMomentumRotationConfig(macro_lag_days=0),
        generated_at="2026-06-25T00:00:00Z",
    )

    assert payload["status"] == "blocked"
    _validate_schema(payload)
    assert "macro_lag_days_lt_1" in payload["blockers"]


def test_macro_release_lag_policy_schema_rejects_promotion_clean_claim(tmp_path: Path) -> None:
    _write_macro_csv(tmp_path / "data/external/us_equity_macro/fred_macro.csv", include_release_fields=True)
    _write_fred_import_report(tmp_path)
    payload = build_us_equity_macro_release_lag_policy_report(
        repo_root=tmp_path,
        output=Path("out/macro_lag.json"),
        markdown_output=Path("out/macro_lag.md"),
        generated_at="2026-06-25T00:00:00Z",
    )
    payload["guardrails"]["promotion_clean_granted_by_this_report"] = True

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError:
        return
    raise AssertionError("schema accepted promotion_clean_granted_by_this_report=true")


def _write_macro_csv(path: Path, *, include_release_fields: bool, include_vintage_fields: bool | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if include_vintage_fields is None:
        include_vintage_fields = include_release_fields
    dates = pd.bdate_range("2026-01-01", periods=5, tz="UTC")
    frame = pd.DataFrame(
        {
            "timestamp_utc": dates,
            "WALCL": [1, 2, 3, 4, 5],
            "WTREGEN": [0.1, 0.1, 0.1, 0.1, 0.1],
            "RRPONTSYD": [0.2, 0.2, 0.2, 0.2, 0.2],
            "BAMLC0A0CM": [1.0, 0.9, 0.8, 0.9, 1.0],
            "DGS10": [4.0, 4.1, 4.2, 4.1, 4.0],
            "DGS2": [3.5, 3.6, 3.7, 3.6, 3.5],
        }
    )
    if include_release_fields:
        frame["release_date"] = dates + pd.Timedelta(days=1)
    if include_vintage_fields:
        frame["realtime_start"] = dates + pd.Timedelta(days=1)
    frame.to_csv(path, index=False)


def _write_fred_import_report(root: Path) -> None:
    path = root / "artifacts/us_equity_data_status/latest/fred_macro_import_report.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "status": "pass",
                "latest_common_date": "2026-06-24",
                "token_written_to_artifacts": False,
            }
        ),
        encoding="utf-8",
    )


def _validate_schema(payload: dict[str, object]) -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError as exc:
        raise AssertionError(f"schema validation failed: {exc.message}") from exc
