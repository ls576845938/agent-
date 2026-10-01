from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from scripts.build_us_equity_remediation_ticket_closure_report import (
    build_us_equity_remediation_ticket_closure_report,
)


SCHEMA = Path("schemas/us_equity_remediation_ticket_closure_report.schema.json")


def test_remediation_ticket_closure_report_keeps_current_tickets_open(tmp_path: Path) -> None:
    _write_required_sources(tmp_path)

    payload = build_us_equity_remediation_ticket_closure_report(
        repo_root=tmp_path,
        output=Path("out/closure.json"),
        markdown_output=Path("out/closure.md"),
        generated_at="2026-06-27T00:00:00Z",
    )

    _validate_schema(payload)
    assert payload["status"] == "remediation_tickets_open"
    assert payload["ticket_count"] == 6
    assert payload["open_count"] == 6
    assert payload["closed_count"] == 0
    assert payload["summary"]["ticket_count"] == 6
    assert payload["summary"]["open_count"] == 6
    assert payload["summary"]["closed_count"] == 0
    assert payload["summary"]["missing_source_count"] == 0
    assert payload["summary"]["unsafe_flag_count"] == 0
    assert payload["summary"]["external_or_time_dependency_count"] == 2
    assert payload["summary"]["manual_dependency_count"] == 1
    assert payload["summary"]["engineering_dependency_count"] == 2
    assert payload["summary"]["governance_dependency_count"] == 1
    assert payload["summary"]["other_dependency_count"] == 0
    assert payload["summary"]["open_by_category"]["external_data"] == 1
    assert payload["summary"]["first_open_ticket_id"] == "us_equity_remediate_external_data"
    assert "vendor_drop_pipeline_ready_for_manual_config_review" in payload["summary"]["first_open_blocking_evidence"]
    assert payload["summary"]["paper_or_live_unlock_allowed"] is False
    assert payload["summary"]["live_order_allowed"] is False
    assert payload["closure_progress"]["ticket_count"] == 6
    assert payload["closure_progress"]["open_count"] == 6
    assert payload["closure_progress"]["closed_count"] == 0
    assert payload["closure_progress"]["all_tickets_closed"] is False
    assert payload["closure_progress"]["paper_or_live_unlock_allowed"] is False
    assert payload["closure_progress"]["by_category"]["external_data"] == {
        "ticket_count": 1,
        "open_count": 1,
        "closed_count": 0,
    }
    assert payload["closure_progress"]["by_source_report"]["broker_review"] == 1
    assert payload["closure_progress"]["by_source_report"]["vendor_drop_pipeline"] == 1
    checks = {item["category"]: item for item in payload["closure_checks"]}
    assert checks["external_data"]["closed"] is False
    assert "us_equity_vendor_drop_pipeline_run_report.status == vendor_drop_pipeline_ready_for_manual_config_review" in checks["external_data"]["blocking_evidence"]
    assert "us_equity_pit_data_intake_status_report.status == production_pit_data_intake_ready" in checks["external_data"]["blocking_evidence"]
    assert checks["natural_time"]["closed"] is False
    assert checks["execution_infra"]["closed"] is False
    assert "us_equity_broker_credentials_operator_handoff.status == broker_credentials_handoff_ready_for_manual_review" in checks["execution_infra"]["blocking_evidence"]
    assert "us_equity_broker_credentials_review_report.status == broker_credentials_review_proven" in checks["execution_infra"]["blocking_evidence"]
    assert payload["guardrails"]["live_order_allowed"] is False
    assert payload["guardrails"]["paper_or_live_unlock_allowed"] is False
    assert (tmp_path / "out/closure.json").exists()
    assert (tmp_path / "out/closure.md").exists()


def test_remediation_ticket_closure_report_closes_when_no_tickets(tmp_path: Path) -> None:
    _write_required_sources(tmp_path, tickets=[])

    payload = build_us_equity_remediation_ticket_closure_report(
        repo_root=tmp_path,
        output=Path("out/closure.json"),
        markdown_output=Path("out/closure.md"),
        generated_at="2026-06-27T00:00:00Z",
    )

    _validate_schema(payload)
    assert payload["status"] == "remediation_tickets_closed"
    assert payload["summary"]["ticket_count"] == 0
    assert payload["summary"]["open_count"] == 0
    assert payload["summary"]["first_open_ticket_id"] == ""
    assert payload["ticket_count"] == 0
    assert payload["open_count"] == 0
    assert payload["closed_count"] == 0
    assert payload["closure_progress"]["all_tickets_closed"] is True
    assert payload["closure_progress"]["open_ticket_ids"] == []
    assert payload["closure_progress"]["paper_or_live_unlock_allowed"] is False
    assert payload["blockers"] == []


def test_remediation_ticket_closure_report_blocks_missing_sources(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "artifacts/us_equity_strategy_production_line/latest/us_equity_blocker_taxonomy_report.json",
        {"status": "blocked_external_and_time_dependencies", "remediation_tickets": [_ticket("external_data")]},
    )

    payload = build_us_equity_remediation_ticket_closure_report(
        repo_root=tmp_path,
        output=Path("out/closure.json"),
        markdown_output=Path("out/closure.md"),
        generated_at="2026-06-27T00:00:00Z",
    )

    _validate_schema(payload)
    assert payload["status"] == "remediation_ticket_closure_source_missing"
    assert payload["summary"]["missing_source_count"] > 0
    assert "manual_review" in payload["missing_sources"]
    assert "us_equity_remediation_ticket_closure_source_missing:manual_review" in payload["blockers"]


def test_remediation_ticket_closure_schema_rejects_live_order_flag(tmp_path: Path) -> None:
    _write_required_sources(tmp_path, tickets=[])
    payload = build_us_equity_remediation_ticket_closure_report(
        repo_root=tmp_path,
        output=Path("out/closure.json"),
        markdown_output=Path("out/closure.md"),
        generated_at="2026-06-27T00:00:00Z",
    )
    payload["guardrails"]["live_order_allowed"] = True

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError:
        return
    raise AssertionError("schema accepted live_order_allowed=true")


def test_remediation_ticket_closure_schema_rejects_progress_unlock(tmp_path: Path) -> None:
    _write_required_sources(tmp_path, tickets=[])
    payload = build_us_equity_remediation_ticket_closure_report(
        repo_root=tmp_path,
        output=Path("out/closure.json"),
        markdown_output=Path("out/closure.md"),
        generated_at="2026-06-27T00:00:00Z",
    )
    payload["closure_progress"]["paper_or_live_unlock_allowed"] = True

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError:
        return
    raise AssertionError("schema accepted closure_progress.paper_or_live_unlock_allowed=true")


def test_remediation_ticket_closure_schema_rejects_summary_live_unlock(tmp_path: Path) -> None:
    _write_required_sources(tmp_path, tickets=[])
    payload = build_us_equity_remediation_ticket_closure_report(
        repo_root=tmp_path,
        output=Path("out/closure.json"),
        markdown_output=Path("out/closure.md"),
        generated_at="2026-06-27T00:00:00Z",
    )
    payload["summary"]["live_order_allowed"] = True

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError:
        return
    raise AssertionError("schema accepted summary.live_order_allowed=true")


def _write_required_sources(tmp_path: Path, tickets: list[dict[str, object]] | None = None) -> None:
    if tickets is None:
        tickets = [
            _ticket("external_data", dependency_type="external_user_action"),
            _ticket("natural_time", dependency_type="natural_time"),
            _ticket("manual_review", dependency_type="manual_review"),
            _ticket("execution_infra", dependency_type="engineering"),
            _ticket("research_data_quality", dependency_type="engineering_after_data"),
            _ticket("remediation_governance", dependency_type="governance_dependency"),
        ]
    _write_json(
        tmp_path / "artifacts/us_equity_strategy_production_line/latest/us_equity_blocker_taxonomy_report.json",
        {"status": "blocked_external_and_time_dependencies", "summary": {"uncategorized_blockers": 0}, "remediation_tickets": tickets},
    )
    _write_json(
        tmp_path / "artifacts/us_equity_etf_macro_rotation/latest/us_equity_manual_review_packet.json",
        {"status": "manual_review_pending", "blockers": ["us_equity_manual_review_remediation_tickets_open"], "guardrails": _safe_guardrails()},
    )
    _write_json(
        tmp_path / "artifacts/us_equity_etf_macro_rotation/latest/us_equity_paper_simulation_readiness_report.json",
        {"status": "paper_simulation_blocked", "blockers": ["us_equity_paper_readiness_remediation_tickets_open"], "guardrails": _safe_guardrails()},
    )
    _write_json(
        tmp_path / "artifacts/us_equity_etf_macro_rotation/latest/us_equity_live_readiness_report.json",
        {
            "status": "live_readiness_blocked",
            "blockers": ["us_equity_live_readiness_remediation_tickets_open"],
            "gate_checks": {
                "broker_credentials_review_complete": False,
                "order_reconciliation_proven": False,
                "kill_switch_drill_complete": False,
                "monitoring_and_alerting_proven": False,
            },
            "guardrails": _safe_guardrails(),
        },
    )
    _write_json(
        tmp_path / "artifacts/us_equity_data_lineage/latest/us_equity_pit_data_intake_status_report.json",
        {"status": "production_pit_data_intake_blocked", "blockers": ["source_dir_missing"], "guardrails": _safe_guardrails()},
    )
    _write_json(
        tmp_path / "artifacts/us_equity_data_lineage/latest/us_equity_pit_bundle_acceptance_run_report.json",
        {"status": "acceptance_blocked", "blockers": ["source_dir_missing"], "guardrails": _safe_guardrails()},
    )
    _write_json(
        tmp_path / "artifacts/us_equity_data_lineage/latest/us_equity_vendor_drop_pipeline_run_report.json",
        {"status": "vendor_drop_pipeline_blocked", "blockers": ["source_dir_missing"], "guardrails": _safe_guardrails()},
    )
    _write_json(
        tmp_path / "artifacts/us_equity_etf_macro_rotation/latest/us_etf_forward_observation_evaluation_report.json",
        {"status": "forward_observing", "observation_continuity": {"passed": False}, "guardrails": _safe_guardrails()},
    )
    _write_json(
        tmp_path / "artifacts/us_equity_etf_macro_rotation/latest/us_etf_strategy_validation_gate_report.json",
        {"status": "blocked_data_quality", "guardrails": _safe_guardrails()},
    )
    _write_json(
        tmp_path / "artifacts/us_equity_etf_macro_rotation/latest/us_equity_broker_credentials_operator_handoff.json",
        {"status": "broker_credentials_handoff_blocked", "blockers": ["broker_credentials_local_review_missing"], "guardrails": _safe_guardrails()},
    )
    _write_json(
        tmp_path / "artifacts/us_equity_etf_macro_rotation/latest/us_equity_broker_credentials_review_report.json",
        {"status": "broker_credentials_review_blocked", "blockers": ["broker_credentials_review_input_missing"], "guardrails": _safe_guardrails()},
    )


def _ticket(category: str, *, dependency_type: str = "engineering") -> dict[str, object]:
    return {
        "ticket_id": f"us_equity_remediate_{category}",
        "category": category,
        "owner": "owner",
        "dependency_type": dependency_type,
        "status": "open",
        "blocker_count": 1,
        "source_reports": ["source"],
        "next_action": "fix",
        "acceptance_evidence": ["evidence"],
    }


def _safe_guardrails() -> dict[str, bool]:
    return {
        "paper_or_live_unlock_allowed": False,
        "paper_simulation_allowed": False,
        "live_order_allowed": False,
        "private_endpoint_allowed": False,
        "private_endpoint_used": False,
        "order_endpoint_allowed": False,
        "order_endpoint_used": False,
        "real_order_submitted": False,
        "broker_calls_used": False,
    }


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _validate_schema(payload: dict[str, object]) -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    jsonschema.validate(payload, schema)
