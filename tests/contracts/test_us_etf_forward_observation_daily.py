from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import jsonschema

from scripts.run_us_etf_forward_observation_daily import run_us_etf_forward_observation_daily


SCHEMA = Path("schemas/us_etf_forward_observation_daily_run_report.schema.json")


def test_us_etf_forward_daily_runs_roll_and_evaluation_without_unlocking(tmp_path: Path) -> None:
    calls: list[str] = []
    _write_safe_data_gate_reports(tmp_path)

    def roll_fn(**_: Any) -> Mapping[str, Any]:
        calls.append("roll")
        return {
            "status": "PASS",
            "cycle_status": "SKIPPED_ALREADY_COMPLETED",
            "blockers": [],
            "guardrails": {
                "paper_or_live_unlock_allowed": False,
                "live_order_allowed": False,
            },
        }

    def evaluation_fn(**_: Any) -> Mapping[str, Any]:
        calls.append("evaluation")
        provisional = tmp_path / "out/daily.json"
        assert provisional.exists()
        provisional_payload = json.loads(provisional.read_text(encoding="utf-8"))
        assert provisional_payload["status"] == "PASS"
        assert provisional_payload["steps"]["data_gate"]["status"] == "pass"
        assert provisional_payload["steps"]["evaluation"]["status"] == "not_run"
        return {
            "status": "forward_observing",
            "minimum_complete_days": 30,
            "metrics": {"observation_days": 1},
            "blockers": [],
            "guardrails": {
                "paper_or_live_unlock_allowed": False,
                "live_order_allowed": False,
            },
        }

    payload = run_us_etf_forward_observation_daily(
        repo_root=tmp_path,
        output=Path("out/daily.json"),
        generated_at="2026-06-25T00:00:00Z",
        roll_fn=roll_fn,
        evaluation_fn=evaluation_fn,
    )

    assert calls == ["roll", "evaluation"]
    assert payload["schema_version"] == "us_etf_forward_observation_daily_run_v1"
    _validate_schema(payload)
    assert payload["status"] == "PASS"
    assert payload["forward_observation"]["already_processed"] is True
    assert payload["forward_observation"]["observation_days"] == 1
    assert payload["guardrails"]["daily_run_is_not_alpha_validation"] is True
    assert payload["guardrails"]["paper_or_live_unlock_allowed"] is False
    assert payload["guardrails"]["live_order_allowed"] is False
    assert (tmp_path / "out/daily.json").exists()


def test_us_etf_forward_daily_blocks_when_roll_fails_and_skips_evaluation(tmp_path: Path) -> None:
    calls: list[str] = []
    _write_safe_data_gate_reports(tmp_path)

    def roll_fn(**_: Any) -> Mapping[str, Any]:
        calls.append("roll")
        return {"status": "BLOCKED", "blockers": ["validation_report_missing"]}

    def evaluation_fn(**_: Any) -> Mapping[str, Any]:
        calls.append("evaluation")
        return {"status": "forward_observing", "metrics": {"observation_days": 1}}

    payload = run_us_etf_forward_observation_daily(
        repo_root=tmp_path,
        output=Path("out/daily.json"),
        generated_at="2026-06-25T00:00:00Z",
        roll_fn=roll_fn,
        evaluation_fn=evaluation_fn,
    )

    assert calls == ["roll"]
    assert payload["status"] == "BLOCKED"
    _validate_schema(payload)
    assert "validation_report_missing" in payload["blockers"]
    assert "us_etf_forward_daily_roll_not_pass" in payload["blockers"]
    assert payload["steps"]["evaluation"]["status"] == "not_run"
    assert payload["guardrails"]["real_order_submitted"] is False


def test_us_etf_forward_daily_blocks_when_evaluation_blocks(tmp_path: Path) -> None:
    _write_safe_data_gate_reports(tmp_path)

    def roll_fn(**_: Any) -> Mapping[str, Any]:
        return {"status": "PASS", "cycle_status": "COMPLETED", "blockers": []}

    def evaluation_fn(**_: Any) -> Mapping[str, Any]:
        return {"status": "forward_blocked", "metrics": {"observation_days": 1}, "blockers": ["ledger_mismatch"]}

    payload = run_us_etf_forward_observation_daily(
        repo_root=tmp_path,
        output=Path("out/daily.json"),
        generated_at="2026-06-25T00:00:00Z",
        roll_fn=roll_fn,
        evaluation_fn=evaluation_fn,
    )

    assert payload["status"] == "BLOCKED"
    _validate_schema(payload)
    assert payload["forward_observation"]["new_observation_written"] is True
    assert "ledger_mismatch" in payload["blockers"]
    assert "us_etf_forward_daily_evaluation_blocked" in payload["blockers"]
    assert payload["guardrails"]["paper_simulation_allowed"] is False


def test_us_etf_forward_daily_blocks_stale_data_before_roll(tmp_path: Path) -> None:
    calls: list[str] = []
    _write_json(
        tmp_path / "artifacts/us_equity_data_status/latest/us_equity_data_freshness_daily_report.json",
        {"status": "blocked_stale", "blockers": ["price_data_stale"]},
    )
    _write_json(
        tmp_path / "artifacts/us_equity_data_status/latest/us_equity_etf_kline_quality_daily_report.json",
        {"status": "pass", "blockers": []},
    )
    _write_json(
        tmp_path / "artifacts/us_equity_data_status/latest/us_equity_fred_macro_preflight_report.json",
        {"status": "fred_macro_preflight_warn", "blockers": []},
    )

    def roll_fn(**_: Any) -> Mapping[str, Any]:
        calls.append("roll")
        return {"status": "PASS", "cycle_status": "COMPLETED", "blockers": []}

    def evaluation_fn(**_: Any) -> Mapping[str, Any]:
        calls.append("evaluation")
        return {"status": "forward_observing", "metrics": {"observation_days": 1}}

    payload = run_us_etf_forward_observation_daily(
        repo_root=tmp_path,
        output=Path("out/daily.json"),
        generated_at="2026-06-25T00:00:00Z",
        roll_fn=roll_fn,
        evaluation_fn=evaluation_fn,
    )

    assert calls == []
    assert payload["status"] == "BLOCKED"
    _validate_schema(payload)
    assert payload["steps"]["data_gate"]["status"] == "blocked"
    assert payload["steps"]["roll"]["status"] == "not_run"
    assert "us_etf_forward_daily_data_freshness_status_not_safe:blocked_stale" in payload["blockers"]
    assert "us_etf_forward_daily_data_freshness:price_data_stale" in payload["blockers"]


def test_us_etf_forward_daily_schema_rejects_live_unlock(tmp_path: Path) -> None:
    _write_safe_data_gate_reports(tmp_path)

    payload = run_us_etf_forward_observation_daily(
        repo_root=tmp_path,
        output=Path("out/daily.json"),
        generated_at="2026-06-25T00:00:00Z",
        roll_fn=lambda **_: {"status": "PASS", "cycle_status": "COMPLETED", "blockers": []},
        evaluation_fn=lambda **_: {"status": "forward_observing", "metrics": {"observation_days": 1}, "blockers": []},
    )
    payload["guardrails"]["paper_or_live_unlock_allowed"] = True

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError:
        return
    raise AssertionError("schema accepted paper_or_live_unlock_allowed=true")


def _write_safe_data_gate_reports(root: Path) -> None:
    _write_json(
        root / "artifacts/us_equity_data_status/latest/us_equity_data_freshness_daily_report.json",
        {"status": "pass", "blockers": []},
    )
    _write_json(
        root / "artifacts/us_equity_data_status/latest/us_equity_etf_kline_quality_daily_report.json",
        {"status": "warn", "blockers": [], "warnings": ["research_warning_only"]},
    )
    _write_json(
        root / "artifacts/us_equity_data_status/latest/us_equity_fred_macro_preflight_report.json",
        {"status": "fred_macro_preflight_warn", "blockers": [], "warnings": ["release_calendar_missing"]},
    )


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(payload)), encoding="utf-8")


def _validate_schema(payload: Mapping[str, Any]) -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError as exc:
        raise AssertionError(f"schema validation failed: {exc.message}") from exc
