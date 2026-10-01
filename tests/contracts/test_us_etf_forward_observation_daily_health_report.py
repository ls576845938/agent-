from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import jsonschema

from scripts.build_us_etf_forward_observation_daily_health_report import build_us_etf_forward_observation_daily_health_report


SCHEMA = Path("schemas/us_etf_forward_observation_daily_health_report.schema.json")


def test_us_etf_forward_daily_health_passes_for_consistent_operational_loop(tmp_path: Path) -> None:
    _write_fixture(tmp_path)

    payload = build_us_etf_forward_observation_daily_health_report(
        repo_root=tmp_path,
        output=Path("out/health.json"),
        markdown_output=Path("out/health.md"),
        generated_at="2026-06-25T00:00:00Z",
    )

    assert payload["schema_version"] == "us_etf_forward_observation_daily_health_report_v1"
    _validate_schema(payload)
    assert payload["status"] == "daily_health_pass"
    assert payload["decision"] == "continue_forward_observation"
    assert payload["observation_days"] == 1
    assert payload["observation_continuity"]["passed"] is True
    assert payload["observation_continuity"]["unique_observation_days"] == 1
    assert payload["ledger"]["target_position_rows"] == 1
    assert payload["ledger"]["fill_rows"] == 2
    assert payload["guardrails"]["daily_health_is_not_alpha_validation"] is True
    assert payload["guardrails"]["paper_or_live_unlock_allowed"] is False
    assert payload["guardrails"]["live_order_allowed"] is False
    assert (tmp_path / "out/health.json").exists()
    assert (tmp_path / "out/health.md").exists()


def test_us_etf_forward_daily_health_blocks_failed_daily_run(tmp_path: Path) -> None:
    _write_fixture(tmp_path, daily_status="BLOCKED")

    payload = build_us_etf_forward_observation_daily_health_report(
        repo_root=tmp_path,
        output=Path("out/health.json"),
        markdown_output=Path("out/health.md"),
        generated_at="2026-06-25T00:00:00Z",
    )

    assert payload["status"] == "daily_health_blocked"
    _validate_schema(payload)
    assert "us_etf_forward_daily_health_daily_run_passed_failed" in payload["blockers"]
    assert payload["guardrails"]["paper_simulation_allowed"] is False


def test_us_etf_forward_daily_health_blocks_inconsistent_ledger_state(tmp_path: Path) -> None:
    _write_fixture(tmp_path, state_overrides={"fill_count": 99})

    payload = build_us_etf_forward_observation_daily_health_report(
        repo_root=tmp_path,
        output=Path("out/health.json"),
        markdown_output=Path("out/health.md"),
        generated_at="2026-06-25T00:00:00Z",
    )

    assert payload["status"] == "daily_health_blocked"
    _validate_schema(payload)
    assert "us_etf_forward_daily_health_ledger_state_consistent_failed" in payload["blockers"]


def test_us_etf_forward_daily_health_reports_stale_without_unlocking(tmp_path: Path) -> None:
    _write_fixture(tmp_path, daily_generated_at="2026-06-20T00:00:00Z")

    payload = build_us_etf_forward_observation_daily_health_report(
        repo_root=tmp_path,
        output=Path("out/health.json"),
        markdown_output=Path("out/health.md"),
        generated_at="2026-06-25T00:00:00Z",
    )

    assert payload["status"] == "daily_health_observing_stale"
    _validate_schema(payload)
    assert "us_etf_forward_daily_health_generated_at_stale" in payload["warnings"]
    assert payload["blockers"] == []
    assert payload["guardrails"]["live_order_allowed"] is False


def test_us_etf_forward_daily_health_schema_rejects_live_unlock(tmp_path: Path) -> None:
    _write_fixture(tmp_path)
    payload = build_us_etf_forward_observation_daily_health_report(
        repo_root=tmp_path,
        output=Path("out/health.json"),
        markdown_output=Path("out/health.md"),
        generated_at="2026-06-25T00:00:00Z",
    )
    payload["guardrails"]["paper_or_live_unlock_allowed"] = True

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError:
        return
    raise AssertionError("schema accepted paper_or_live_unlock_allowed=true")


def _write_fixture(
    root: Path,
    *,
    daily_status: str = "PASS",
    daily_generated_at: str = "2026-06-25T00:00:00Z",
    state_overrides: Mapping[str, Any] | None = None,
) -> None:
    latest = root / "artifacts/us_equity_etf_macro_rotation/latest"
    latest.mkdir(parents=True, exist_ok=True)
    ledger = root / "data/forward_observation/us_etf_rotation_v1"
    ledger.mkdir(parents=True, exist_ok=True)
    _write_json(
        latest / "us_etf_forward_observation_daily_run_report.json",
        {
            "schema_version": "us_etf_forward_observation_daily_run_v1",
            "generated_at": daily_generated_at,
            "status": daily_status,
            "scheduler": {"intended_frequency": "daily_or_after_rebalance_signal_refresh"},
            "forward_observation": {
                "ledger_root": "data/forward_observation/us_etf_rotation_v1",
                "cycle_status": "SKIPPED_ALREADY_COMPLETED",
                "evaluation_status": "forward_observing",
                "observation_days": 1,
                "minimum_complete_days": 30,
            },
            "blockers": [] if daily_status == "PASS" else ["daily_failed"],
            "guardrails": {
                "daily_run_is_not_alpha_validation": True,
                "paper_or_live_unlock_allowed": False,
                "paper_simulation_allowed": False,
                "live_order_allowed": False,
                "private_endpoint_allowed": False,
                "order_endpoint_allowed": False,
            },
        },
    )
    _write_json(
        latest / "us_etf_forward_observation_roll_report.json",
        {
            "status": "PASS",
            "cycle_status": "SKIPPED_ALREADY_COMPLETED",
            "operational_checks": {"status": "PASS"},
            "guardrails": {
                "forward_observation_is_not_alpha_validation": True,
                "paper_or_live_unlock_allowed": False,
                "live_order_allowed": False,
            },
            "blockers": [],
        },
    )
    _write_json(
        latest / "us_etf_forward_observation_evaluation_report.json",
        {
            "status": "forward_observing",
            "minimum_complete_days": 30,
            "metrics": {
                "observation_days": 1,
                "target_position_rows": 1,
                "portfolio_snapshot_rows": 1,
                "simulated_fill_count": 2,
                "latest_observation_date": "2026-06-24",
            },
            "observation_continuity": {
                "passed": True,
                "first_observation_date": "2026-06-24",
                "latest_observation_date": "2026-06-24",
                "unique_observation_days": 1,
                "duplicate_target_dates": [],
                "duplicate_snapshot_dates": [],
                "missing_snapshot_for_target": [],
                "missing_target_for_snapshot": [],
                "state_last_processed_timestamp": "2026-06-24",
                "fill_dates_without_snapshot": [],
                "calendar_gaps": [],
                "max_calendar_gap_days": 0,
                "note": "fixture",
            },
            "guardrails": {
                "forward_evaluation_is_not_alpha_validation": True,
                "paper_or_live_unlock_allowed": False,
                "paper_simulation_allowed": False,
                "live_order_allowed": False,
            },
            "blockers": [],
        },
    )
    _write_jsonl(ledger / "target_positions.jsonl", [{"timestamp": "2026-06-24", "reason": "fixture"}])
    _write_jsonl(
        ledger / "fills.jsonl",
        [
            {"timestamp": "2026-06-24", "symbol": "SPY", "simulated_only": True},
            {"timestamp": "2026-06-24", "symbol": "SHV", "simulated_only": True},
        ],
    )
    _write_jsonl(ledger / "portfolio_snapshots.jsonl", [{"timestamp": "2026-06-24", "reconciliation_status": "clean"}])
    state = {
        "schema_version": "us_etf_rotation_forward_observation_state_v1",
        "days_completed": 1,
        "target_position_count": 1,
        "fill_count": 2,
        "last_processed_timestamp": "2026-06-24",
    }
    if state_overrides:
        state.update(state_overrides)
    _write_json(ledger / "validation_state.json", state)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(payload), ensure_ascii=False), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(dict(row), ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")


def _validate_schema(payload: Mapping[str, Any]) -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError as exc:
        raise AssertionError(f"schema validation failed: {exc.message}") from exc
