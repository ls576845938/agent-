from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from scripts.build_us_equity_kill_switch_drill_report import build_us_equity_kill_switch_drill_report


SCHEMA = Path("schemas/us_equity_kill_switch_drill_report.schema.json")


def test_kill_switch_drill_reports_partial_policy_evidence_without_live_unlock(tmp_path: Path) -> None:
    _write_sources(tmp_path, monitoring=True, daily=True, health=True, order_reconciliation=True, live=True)

    payload = build_us_equity_kill_switch_drill_report(
        repo_root=tmp_path,
        output=Path("out/kill_switch.json"),
        markdown_output=Path("out/kill_switch.md"),
        generated_at="2026-06-27T00:00:00Z",
    )

    _validate_schema(payload)
    assert payload["status"] == "kill_switch_drill_partial"
    assert payload["scenario_count"] == 5
    scenarios = {item["scenario_id"]: item for item in payload["scenarios"]}
    assert scenarios["data_stale_stop"]["status"] == "proven"
    assert scenarios["unsafe_endpoint_flag_stop"]["status"] == "proven"
    assert scenarios["drawdown_loss_stop"]["status"] == "proven"
    assert scenarios["reconciliation_failure_stop"]["status"] == "proven"
    assert scenarios["manual_stop_reset"]["status"] == "blocked"
    assert payload["proven_count"] == 4
    assert payload["blocked_count"] == 1
    assert "manual_stop_reset_drill_not_proven" in payload["blockers"]
    assert payload["guardrails"]["live_order_allowed"] is False
    assert payload["guardrails"]["order_endpoint_allowed"] is False
    assert payload["guardrails"]["broker_calls_used"] is False
    assert (tmp_path / "out/kill_switch.json").exists()
    assert (tmp_path / "out/kill_switch.md").exists()


def test_kill_switch_drill_blocks_when_sources_missing(tmp_path: Path) -> None:
    payload = build_us_equity_kill_switch_drill_report(
        repo_root=tmp_path,
        output=Path("out/kill_switch.json"),
        markdown_output=Path("out/kill_switch.md"),
        generated_at="2026-06-27T00:00:00Z",
    )

    _validate_schema(payload)
    assert payload["status"] == "kill_switch_drill_blocked"
    assert payload["proven_count"] == 0
    assert "data_stale_stop_contract_not_proven" in payload["blockers"]
    assert "unsafe_endpoint_flag_stop_contract_not_proven" in payload["blockers"]


def test_kill_switch_drill_can_be_fully_proven_with_manual_reset_evidence(tmp_path: Path) -> None:
    _write_sources(tmp_path, monitoring=True, daily=True, health=True, order_reconciliation=True, live=True, manual_reset=True)

    payload = build_us_equity_kill_switch_drill_report(
        repo_root=tmp_path,
        output=Path("out/kill_switch.json"),
        markdown_output=Path("out/kill_switch.md"),
        generated_at="2026-06-27T00:00:00Z",
    )

    _validate_schema(payload)
    assert payload["status"] == "kill_switch_drill_proven"
    assert payload["proven_count"] == 5
    assert payload["blocked_count"] == 0
    assert payload["blockers"] == []


def test_kill_switch_schema_rejects_live_order_allowed(tmp_path: Path) -> None:
    _write_sources(tmp_path, monitoring=True, daily=True, health=True, order_reconciliation=True, live=True)
    payload = build_us_equity_kill_switch_drill_report(
        repo_root=tmp_path,
        output=Path("out/kill_switch.json"),
        markdown_output=Path("out/kill_switch.md"),
        generated_at="2026-06-27T00:00:00Z",
    )
    payload["guardrails"]["live_order_allowed"] = True

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError:
        return
    raise AssertionError("schema accepted live_order_allowed=true")


def _write_sources(
    tmp_path: Path,
    *,
    monitoring: bool,
    daily: bool,
    health: bool,
    order_reconciliation: bool,
    live: bool,
    manual_reset: bool = False,
) -> None:
    if monitoring:
        _write_json(tmp_path / "artifacts/us_equity_etf_macro_rotation/latest/us_equity_monitoring_rules_report.json", _monitoring_payload())
    if daily:
        _write_json(tmp_path / "artifacts/us_equity_strategy_production_line/latest/us_equity_daily_production_line_run_report.json", _daily_payload())
    if health:
        _write_json(tmp_path / "artifacts/us_equity_etf_macro_rotation/latest/us_etf_forward_observation_daily_health_report.json", _health_payload())
    if order_reconciliation:
        _write_json(
            tmp_path / "artifacts/us_equity_etf_macro_rotation/latest/us_equity_order_reconciliation_drill_report.json",
            _order_reconciliation_payload(),
        )
    if manual_reset:
        _write_json(
            tmp_path / "artifacts/us_equity_etf_macro_rotation/latest/us_equity_manual_stop_reset_drill_report.json",
            _manual_stop_payload(),
        )
    if live:
        _write_json(
            tmp_path / "artifacts/us_equity_etf_macro_rotation/latest/us_equity_live_readiness_report.json",
            _live_payload(),
        )


def _monitoring_payload() -> dict[str, object]:
    return {
        "status": "monitoring_rules_defined",
        "rules": {
            "data_monitors": {"etf_price_stale_stop": {"severity": "block"}},
            "position_and_execution_monitors": {
                "kill_switch_required": {"severity": "block"},
                "cash_and_financing_reconciliation": {"severity": "block"},
            },
            "retirement_rules": {"risk_limit_failure": {"severity": "manual_review"}},
        },
        "guardrails": {"live_order_allowed": False},
    }


def _daily_payload() -> dict[str, object]:
    return {
        "status": "PASS",
        "unsafe_flags": [],
        "guardrails": {
            "live_order_allowed": False,
            "private_endpoint_allowed": False,
            "order_endpoint_allowed": False,
            "broker_calls_used": False,
        },
    }


def _health_payload() -> dict[str, object]:
    return {
        "status": "daily_health_pass",
        "observation_continuity": {
            "passed": True,
            "unique_observation_days": 1,
        },
    }


def _live_payload() -> dict[str, object]:
    return {
        "status": "live_readiness_blocked",
        "live_order_allowed": False,
        "risk_constitution": {
            "loss_limits": {"max_daily_loss_pct": 0.02},
            "manual_reset_required_after_stop": True,
        },
        "execution_readiness": {
            "status": "execution_readiness_blocked",
            "blockers": ["order_reconciliation_drill_not_proven"],
        },
        "guardrails": {"live_order_allowed": False},
    }


def _order_reconciliation_payload() -> dict[str, object]:
    return {
        "status": "order_reconciliation_drill_proven",
        "blocked_count": 0,
        "reconciliation": {
            "cash_recomputable": True,
            "positions_recomputable": True,
            "fees_recomputable": True,
        },
        "guardrails": {"live_order_allowed": False},
    }


def _manual_stop_payload() -> dict[str, object]:
    return {
        "status": "manual_stop_reset_proven",
        "event_count": 4,
        "checklist_count": 6,
        "blockers": [],
        "guardrails": {"live_order_allowed": False},
    }


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _validate_schema(payload: dict[str, object]) -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    jsonschema.validate(payload, schema)
