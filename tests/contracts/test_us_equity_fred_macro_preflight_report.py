from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import jsonschema

from scripts.build_us_equity_fred_macro_preflight_report import build_us_equity_fred_macro_preflight_report


SCHEMA = Path("schemas/us_equity_fred_macro_preflight_report.schema.json")


def test_fred_macro_preflight_warns_when_session_key_missing_but_research_data_available(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    _write_fixture(tmp_path)

    payload = build_us_equity_fred_macro_preflight_report(
        repo_root=tmp_path,
        output=Path("out/preflight.json"),
        markdown_output=Path("out/preflight.md"),
        generated_at="2026-06-25T00:00:00Z",
    )

    assert payload["schema_version"] == "us_equity_fred_macro_preflight_report_v1"
    _validate_schema(payload)
    assert payload["status"] == "fred_macro_preflight_warn"
    assert payload["current_session_api_key_present"] is False
    assert "previous_fred_import_used_api_key_but_current_session_key_missing" in payload["warnings"]
    assert "fred_release_calendar_missing" in payload["warnings"]
    assert payload["blockers"] == []
    assert payload["guardrails"]["api_key_value_recorded"] is False
    assert payload["guardrails"]["live_order_allowed"] is False
    assert (tmp_path / "out/preflight.json").exists()
    assert (tmp_path / "out/preflight.md").exists()


def test_fred_macro_preflight_passes_when_key_present_and_release_policy_clean(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FRED_API_KEY", "SECRET_SHOULD_NOT_BE_WRITTEN")
    _write_fixture(tmp_path, macro_lag_status="production_lag_policy_ready", macro_lag_blockers=[])

    payload = build_us_equity_fred_macro_preflight_report(
        repo_root=tmp_path,
        output=Path("out/preflight.json"),
        markdown_output=Path("out/preflight.md"),
        generated_at="2026-06-25T00:00:00Z",
    )

    assert payload["status"] == "fred_macro_preflight_pass"
    _validate_schema(payload)
    text = (tmp_path / "out/preflight.json").read_text(encoding="utf-8")
    assert "SECRET_SHOULD_NOT_BE_WRITTEN" not in text


def test_fred_macro_preflight_warns_failed_import_when_local_csv_snapshot_is_usable(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    _write_fixture(tmp_path, import_status="blocked", import_blockers=["fred_series_fetch_failed:DGS10"])

    payload = build_us_equity_fred_macro_preflight_report(
        repo_root=tmp_path,
        output=Path("out/preflight.json"),
        markdown_output=Path("out/preflight.md"),
        generated_at="2026-06-25T00:00:00Z",
    )

    assert payload["status"] == "fred_macro_preflight_warn"
    _validate_schema(payload)
    assert "fred_import_blocked_using_existing_macro_csv_snapshot" in payload["warnings"]
    assert "fred_series_fetch_failed:DGS10" in payload["warnings"]
    assert payload["blockers"] == []
    assert payload["guardrails"]["paper_simulation_allowed"] is False


def test_fred_macro_preflight_blocks_failed_import_when_local_csv_missing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    _write_fixture(tmp_path, import_status="blocked", import_blockers=["fred_series_fetch_failed:DGS10"], write_macro_csv=False)

    payload = build_us_equity_fred_macro_preflight_report(
        repo_root=tmp_path,
        output=Path("out/preflight.json"),
        markdown_output=Path("out/preflight.md"),
        generated_at="2026-06-25T00:00:00Z",
    )

    assert payload["status"] == "fred_macro_preflight_blocked"
    _validate_schema(payload)
    assert "fred_series_fetch_failed:DGS10" in payload["blockers"]
    assert "fred_macro_csv_missing_or_empty" in payload["blockers"]
    assert payload["guardrails"]["paper_simulation_allowed"] is False


def test_fred_macro_preflight_schema_rejects_api_key_recorded(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FRED_API_KEY", "SECRET_SHOULD_NOT_BE_WRITTEN")
    _write_fixture(tmp_path, macro_lag_status="production_lag_policy_ready", macro_lag_blockers=[])
    payload = build_us_equity_fred_macro_preflight_report(
        repo_root=tmp_path,
        output=Path("out/preflight.json"),
        markdown_output=Path("out/preflight.md"),
        generated_at="2026-06-25T00:00:00Z",
    )
    payload["api_key_value_recorded"] = True

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError:
        return
    raise AssertionError("schema accepted api_key_value_recorded=true")


def _write_fixture(
    root: Path,
    *,
    import_status: str = "pass",
    import_blockers: list[str] | None = None,
    macro_lag_status: str = "research_lag_only_release_calendar_missing",
    macro_lag_blockers: list[str] | None = None,
    write_macro_csv: bool = True,
) -> None:
    data_status = root / "artifacts/us_equity_data_status/latest"
    data_lineage = root / "artifacts/us_equity_data_lineage/latest"
    macro_dir = root / "data/external/us_equity_macro"
    data_status.mkdir(parents=True, exist_ok=True)
    data_lineage.mkdir(parents=True, exist_ok=True)
    macro_dir.mkdir(parents=True, exist_ok=True)
    _write_json(
        data_status / "fred_macro_import_report.json",
        {
            "status": import_status,
            "source_type": "fred_api_observations",
            "latest_common_date": "2026-06-17",
            "series": ["DGS10", "DGS2"],
            "latest_by_series": {"DGS10": "2026-06-24", "DGS2": "2026-06-24"},
            "blockers": import_blockers or [],
            "guardrails": {
                "api_key_used_for_macro_data": True,
                "token_written_to_artifacts": False,
                "live_order_allowed": False,
                "private_endpoint_used": False,
                "order_endpoint_used": False,
            },
        },
    )
    _write_json(
        data_status / "us_equity_data_freshness_daily_report.json",
        {
            "status": "pass",
            "macro_freshness": {"status": "pass"},
            "blockers": [],
            "guardrails": {
                "freshness_gate_only": True,
                "live_order_allowed": False,
                "private_endpoint_allowed": False,
                "order_endpoint_allowed": False,
            },
        },
    )
    _write_json(
        data_lineage / "us_equity_macro_release_lag_policy_report.json",
        {
            "status": macro_lag_status,
            "policy": {"macro_lag_days": 2},
            "macro_source": {"release_calendar_fields_present": macro_lag_status != "research_lag_only_release_calendar_missing"},
            "blockers": macro_lag_blockers
            if macro_lag_blockers is not None
            else ["fred_release_calendar_missing", "macro_revision_vintage_missing"],
            "guardrails": {
                "research_lag_proxy_is_not_production_pit": macro_lag_status == "research_lag_only_release_calendar_missing",
                "paper_simulation_allowed": False,
                "live_order_allowed": False,
                "private_endpoint_allowed": False,
                "order_endpoint_allowed": False,
            },
        },
    )
    if write_macro_csv:
        (macro_dir / "fred_macro.csv").write_text(
            "timestamp_utc,DGS10,DGS2\n2026-06-24T00:00:00Z,4.0,3.8\n",
            encoding="utf-8",
        )


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(payload), ensure_ascii=False), encoding="utf-8")


def _validate_schema(payload: Mapping[str, Any]) -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError as exc:
        raise AssertionError(f"schema validation failed: {exc.message}") from exc
