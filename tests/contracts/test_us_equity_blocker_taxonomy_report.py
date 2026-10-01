from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from scripts.build_us_equity_blocker_taxonomy_report import build_us_equity_blocker_taxonomy_report


SCHEMA = Path("schemas/us_equity_blocker_taxonomy_report.schema.json")


def test_blocker_taxonomy_classifies_current_external_and_time_blockers(tmp_path: Path) -> None:
    payload = build_us_equity_blocker_taxonomy_report(
        repo_root=Path("."),
        output=tmp_path / "taxonomy.json",
        markdown_output=tmp_path / "taxonomy.md",
        generated_at="2026-06-27T00:00:00Z",
    )

    _validate_schema(payload)
    assert payload["schema_version"] == "us_equity_blocker_taxonomy_report_v1"
    assert payload["status"] == "blocked_external_and_time_dependencies"
    categories = {item["category"]: item for item in payload["categories"]}
    assert categories["external_data"]["blocker_count"] > 0
    assert categories["natural_time"]["blocker_count"] > 0
    assert payload["summary"]["uncategorized_blockers"] == 0
    assert payload["uncategorized"] == []
    assert payload["summary"]["remediation_ticket_count"] == len(payload["remediation_tickets"])
    for category in categories.values():
        assert category["blocker_count"] == len(set(category["blockers"]))
        assert category["blocker_count"] == len(category["blocker_details"])
    tickets = {item["category"]: item for item in payload["remediation_tickets"]}
    assert tickets["external_data"]["owner"] == "operator_data_vendor"
    assert tickets["external_data"]["dependency_type"] == "external_user_action"
    assert tickets["external_data"]["status"] == "waiting_external_input"
    assert "fail-closed vendor-drop pipeline" in tickets["external_data"]["next_action"]
    assert "us_equity_vendor_drop_pipeline_run_report.status" in tickets["external_data"]["acceptance_evidence"][0]
    assert tickets["natural_time"]["owner"] == "daily_forward_observation_scheduler"
    assert tickets["natural_time"]["dependency_type"] == "natural_time"
    assert tickets["natural_time"]["status"] == "waiting_observation_window"
    assert tickets["execution_infra"]["status"] == "waiting_broker_local_review"
    assert "execution_evidence" in tickets["execution_infra"]["source_reports"]
    assert any("production" in item or "pit" in item for item in categories["external_data"]["blockers"])
    assert payload["guardrails"]["live_order_allowed"] is False
    assert payload["guardrails"]["paper_or_live_unlock_allowed"] is False
    assert (tmp_path / "taxonomy.md").exists()


def test_blocker_taxonomy_uses_pit_operator_next_actions(tmp_path: Path) -> None:
    _write_json(tmp_path / "dev.json", {"blockers": ["production_bundle_missing"]})
    _write_json(tmp_path / "live.json", {"blockers": ["us_equity_live_readiness_manual_reviewer_not_recorded"]})
    _write_json(tmp_path / "forward.json", {"blockers": ["us_equity_live_readiness_forward_observation_less_than_30_days"]})
    _write_json(
        tmp_path / "handoff.json",
        {
            "blockers": ["source_dir_missing"],
            "operator_next_actions": ["Copy licensed CSV files into manual vendor drop."],
        },
    )
    _write_json(
        tmp_path / "broker_handoff.json",
        {
            "blockers": ["broker_credentials_local_review_missing"],
            "operator_next_actions": ["Fill broker credentials local review."],
        },
    )
    _write_json(tmp_path / "daily.json", {"blockers": []})

    payload = build_us_equity_blocker_taxonomy_report(
        repo_root=tmp_path,
        output=Path("out/taxonomy.json"),
        markdown_output=Path("out/taxonomy.md"),
        development_audit=Path("dev.json"),
        live_readiness=Path("live.json"),
        forward_evaluation=Path("forward.json"),
        pit_handoff=Path("handoff.json"),
        broker_handoff=Path("broker_handoff.json"),
        daily_line=Path("daily.json"),
        generated_at="2026-06-27T00:00:00Z",
    )

    _validate_schema(payload)
    assert payload["operator_next_actions"] == [
        "Copy licensed CSV files into manual vendor drop.",
        "Fill broker credentials local review.",
    ]
    categories = {item["category"]: item for item in payload["categories"]}
    assert categories["external_data"]["blocker_count"] == 2
    assert categories["natural_time"]["blocker_count"] == 1
    assert categories["manual_review"]["blocker_count"] == 1
    tickets = {item["category"]: item for item in payload["remediation_tickets"]}
    assert tickets["external_data"]["source_reports"] == ["development_audit", "pit_handoff"]
    assert tickets["execution_infra"]["source_reports"] == ["broker_handoff"]
    assert tickets["execution_infra"]["status"] == "waiting_broker_local_review"
    assert "us_equity_broker_credentials_operator_handoff.status" in tickets["execution_infra"]["acceptance_evidence"][0]
    assert tickets["manual_review"]["owner"] == "human_reviewer"
    assert tickets["manual_review"]["status"] == "blocked_until_upstream_ready"


def test_blocker_taxonomy_classifies_open_remediation_ticket_blockers(tmp_path: Path) -> None:
    _write_json(tmp_path / "dev.json", {"blockers": ["us_equity_live_readiness_remediation_tickets_open"]})
    _write_json(tmp_path / "live.json", {"blockers": []})
    _write_json(tmp_path / "forward.json", {"blockers": []})
    _write_json(tmp_path / "handoff.json", {"blockers": []})
    _write_json(tmp_path / "broker_handoff.json", {"blockers": []})
    _write_json(tmp_path / "daily.json", {"blockers": []})

    payload = build_us_equity_blocker_taxonomy_report(
        repo_root=tmp_path,
        output=Path("out/taxonomy.json"),
        markdown_output=Path("out/taxonomy.md"),
        development_audit=Path("dev.json"),
        live_readiness=Path("live.json"),
        forward_evaluation=Path("forward.json"),
        pit_handoff=Path("handoff.json"),
        broker_handoff=Path("broker_handoff.json"),
        daily_line=Path("daily.json"),
        generated_at="2026-06-27T00:00:00Z",
    )

    _validate_schema(payload)
    assert payload["uncategorized"] == []
    categories = {item["category"]: item for item in payload["categories"]}
    assert categories["remediation_governance"]["blockers"] == ["us_equity_live_readiness_remediation_tickets_open"]
    tickets = {item["category"]: item for item in payload["remediation_tickets"]}
    assert tickets["remediation_governance"]["owner"] == "quant_architect"
    assert tickets["remediation_governance"]["dependency_type"] == "governance_dependency"
    assert tickets["remediation_governance"]["status"] == "waiting_upstream_ticket_closure"
    assert tickets["remediation_governance"]["next_action"] != "Inspect manually."
    assert "remediation_tickets_open" in tickets["remediation_governance"]["next_action"]
    assert "uncategorized_blockers == 0" in tickets["remediation_governance"]["next_action"]


def test_blocker_taxonomy_classifies_daily_schema_orchestration_blockers_as_governance(tmp_path: Path) -> None:
    _write_json(tmp_path / "dev.json", {"blockers": ["daily_production_line_not_pass"]})
    _write_json(tmp_path / "live.json", {"blockers": []})
    _write_json(tmp_path / "forward.json", {"blockers": []})
    _write_json(tmp_path / "handoff.json", {"blockers": []})
    _write_json(tmp_path / "broker_handoff.json", {"blockers": []})
    _write_json(
        tmp_path / "daily.json",
        {
            "blockers": [
                "us_equity_daily_step_not_safe:standard_report_schema_audit:schema_audit_action_required",
                "us_equity_standard_schema_field_missing:production_control_schema",
                "us_equity_daily_step_not_safe:production_control_health:fail",
            ]
        },
    )

    payload = build_us_equity_blocker_taxonomy_report(
        repo_root=tmp_path,
        output=Path("out/taxonomy.json"),
        markdown_output=Path("out/taxonomy.md"),
        development_audit=Path("dev.json"),
        live_readiness=Path("live.json"),
        forward_evaluation=Path("forward.json"),
        pit_handoff=Path("handoff.json"),
        broker_handoff=Path("broker_handoff.json"),
        daily_line=Path("daily.json"),
        generated_at="2026-06-27T00:00:00Z",
    )

    _validate_schema(payload)
    assert payload["summary"]["uncategorized_blockers"] == 0
    assert payload["uncategorized"] == []
    categories = {item["category"]: item for item in payload["categories"]}
    assert categories["remediation_governance"]["blocker_count"] == 4
    assert categories["other"]["blocker_count"] == 0
    tickets = {item["category"]: item for item in payload["remediation_tickets"]}
    assert tickets["remediation_governance"]["status"] == "waiting_upstream_ticket_closure"
    assert "other" not in tickets


def test_blocker_taxonomy_classifies_manual_approval_as_manual_review(tmp_path: Path) -> None:
    _write_json(tmp_path / "dev.json", {"blockers": []})
    _write_json(tmp_path / "live.json", {"blockers": ["us_equity_live_readiness_manual_approval_not_recorded"]})
    _write_json(tmp_path / "forward.json", {"blockers": []})
    _write_json(tmp_path / "handoff.json", {"blockers": []})
    _write_json(tmp_path / "broker_handoff.json", {"blockers": []})
    _write_json(tmp_path / "daily.json", {"blockers": []})

    payload = build_us_equity_blocker_taxonomy_report(
        repo_root=tmp_path,
        output=Path("out/taxonomy.json"),
        markdown_output=Path("out/taxonomy.md"),
        development_audit=Path("dev.json"),
        live_readiness=Path("live.json"),
        forward_evaluation=Path("forward.json"),
        pit_handoff=Path("handoff.json"),
        broker_handoff=Path("broker_handoff.json"),
        daily_line=Path("daily.json"),
        generated_at="2026-06-27T00:00:00Z",
    )

    _validate_schema(payload)
    assert payload["summary"]["uncategorized_blockers"] == 0
    categories = {item["category"]: item for item in payload["categories"]}
    assert categories["manual_review"]["blockers"] == ["us_equity_live_readiness_manual_approval_not_recorded"]
    assert categories["other"]["blocker_count"] == 0
    tickets = {item["category"]: item for item in payload["remediation_tickets"]}
    assert tickets["manual_review"]["dependency_type"] == "manual_review"
    assert "other" not in tickets


def test_blocker_taxonomy_deduplicates_blockers_and_preserves_sources(tmp_path: Path) -> None:
    duplicate = "production_bundle_missing"
    _write_json(tmp_path / "dev.json", {"blockers": [duplicate]})
    _write_json(tmp_path / "live.json", {"blockers": [duplicate]})
    _write_json(tmp_path / "forward.json", {"blockers": []})
    _write_json(tmp_path / "handoff.json", {"blockers": []})
    _write_json(tmp_path / "broker_handoff.json", {"blockers": []})
    _write_json(tmp_path / "daily.json", {"blockers": []})

    payload = build_us_equity_blocker_taxonomy_report(
        repo_root=tmp_path,
        output=Path("out/taxonomy.json"),
        markdown_output=Path("out/taxonomy.md"),
        development_audit=Path("dev.json"),
        live_readiness=Path("live.json"),
        forward_evaluation=Path("forward.json"),
        pit_handoff=Path("handoff.json"),
        broker_handoff=Path("broker_handoff.json"),
        daily_line=Path("daily.json"),
        generated_at="2026-06-27T00:00:00Z",
    )

    _validate_schema(payload)
    categories = {item["category"]: item for item in payload["categories"]}
    external = categories["external_data"]
    assert external["blocker_count"] == 1
    assert external["blockers"] == [duplicate]
    assert external["blocker_details"] == [
        {
            "blocker": duplicate,
            "category": "external_data",
            "source_reports": ["development_audit", "live_readiness"],
            "source_paths": ["development_audit:blockers", "live_readiness:blockers"],
        }
    ]
    tickets = payload["remediation_tickets"]
    assert len(tickets) == 1
    assert tickets[0]["category"] == "external_data"
    assert tickets[0]["blocker_count"] == 1


def test_blocker_taxonomy_schema_rejects_live_unlock() -> None:
    payload = build_us_equity_blocker_taxonomy_report(
        repo_root=Path("."),
        output=Path("artifacts/tmp/us_equity_blocker_taxonomy_report_test.json"),
        markdown_output=Path("artifacts/tmp/us_equity_blocker_taxonomy_report_test.md"),
        generated_at="2026-06-27T00:00:00Z",
    )
    payload["guardrails"]["live_order_allowed"] = True

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError:
        return
    raise AssertionError("schema accepted live_order_allowed=true")


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _validate_schema(payload: dict[str, object]) -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    jsonschema.validate(payload, schema)
