from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from quant_us.live.manual_review_packet import evaluate_manual_review_packet
from scripts.build_us_equity_manual_review_packet import build_us_equity_manual_review_packet


SCHEMA = Path("schemas/us_equity_manual_review_packet.schema.json")


def test_manual_review_packet_report_rules_live_in_live_service() -> None:
    assert build_us_equity_manual_review_packet.__module__ == "quant_us.live.manual_review_packet_report"


def test_manual_review_packet_tracks_milestones_and_stays_pending_before_30_days(tmp_path: Path) -> None:
    _write_fixture_reports(tmp_path, observation_days=1, forward_status="forward_observing")

    payload = build_us_equity_manual_review_packet(
        repo_root=tmp_path,
        output=Path("out/manual.json"),
        markdown_output=Path("out/manual.md"),
        generated_at="2026-06-25T00:00:00Z",
    )

    assert payload["schema_version"] == "us_equity_manual_review_packet_v1"
    _validate_schema(payload)
    assert payload["status"] == "manual_review_pending"
    assert "us_equity_manual_review_forward_observation_not_complete" in payload["blockers"]
    assert payload["forward_review_progress"]["observation_days"] == 1
    assert payload["forward_review_progress"]["minimum_complete_days"] == 30
    assert payload["forward_review_progress"]["completed_milestones"] == []
    assert payload["forward_review_progress"]["next_milestone"] == 30
    assert payload["forward_review_progress"]["days_until_minimum"] == 29
    assert payload["forward_review_progress"]["manual_review_required"] is False
    assert payload["forward_review_progress"]["alpha_validation_claim_allowed"] is False
    assert payload["forward_review_progress"]["paper_or_live_unlock_allowed"] is False
    assert payload["review_milestones"][0]["days"] == 30
    assert payload["review_milestones"][0]["reached"] is False
    checks = {item["check_id"]: item for item in payload["evidence_checklist"]}
    assert checks["forward_observation_30_day_complete"]["passed"] is False
    assert checks["strategy_validation_evidence_audit_ready"]["passed"] is True
    assert checks["forward_review_progress_manual_only"]["passed"] is False
    assert checks["forward_data_gate_no_blocked_runs"]["passed"] is True
    assert checks["forward_observation_continuity_passed"]["passed"] is True
    assert payload["paper_or_live_unlock_decision"]["manual_review_can_unlock_paper_by_itself"] is False
    assert payload["paper_or_live_unlock_decision"]["manual_review_can_unlock_live_by_itself"] is False
    assert payload["guardrails"]["paper_simulation_allowed"] is False
    assert payload["guardrails"]["live_order_allowed"] is False
    assert payload["guardrails"]["manual_approval_recorded"] is False
    assert (tmp_path / "out/manual.md").exists()


def test_manual_review_packet_malformed_source_report_fails_closed(tmp_path: Path) -> None:
    _write_fixture_reports(tmp_path, observation_days=30, forward_status="forward_complete_for_manual_review")
    strategy_gate = tmp_path / "artifacts/us_equity_etf_macro_rotation/latest/us_etf_strategy_validation_gate_report.json"
    strategy_gate.write_text("{not-json", encoding="utf-8")

    payload = build_us_equity_manual_review_packet(
        repo_root=tmp_path,
        output=Path("out/manual.json"),
        markdown_output=Path("out/manual.md"),
        generated_at="2026-06-25T00:00:00Z",
    )

    _validate_schema(payload)
    assert payload["status"] == "manual_review_pending"
    assert "us_equity_manual_review_strategy_validation_not_passed" in payload["blockers"]
    assert payload["guardrails"]["paper_simulation_allowed"] is False
    assert payload["guardrails"]["live_order_allowed"] is False


def test_manual_review_ready_still_does_not_unlock_paper_or_live(tmp_path: Path) -> None:
    _write_fixture_reports(tmp_path, observation_days=30, forward_status="forward_complete_for_manual_review")

    payload = build_us_equity_manual_review_packet(
        repo_root=tmp_path,
        output=Path("out/manual.json"),
        markdown_output=Path("out/manual.md"),
        generated_at="2026-06-25T00:00:00Z",
    )

    assert payload["status"] == "manual_review_ready"
    _validate_schema(payload)
    assert payload["blockers"] == []
    assert payload["forward_review_progress"]["observation_days"] == 30
    assert payload["forward_review_progress"]["completed_milestones"] == [30]
    assert payload["forward_review_progress"]["next_milestone"] == 60
    assert payload["forward_review_progress"]["days_until_minimum"] == 0
    assert payload["forward_review_progress"]["manual_review_required"] is True
    assert payload["forward_review_progress"]["manual_review_only_no_paper_or_live_unlock"] is True
    assert payload["forward_review_progress"]["paper_or_live_unlock_allowed"] is False
    checks = {item["check_id"]: item for item in payload["evidence_checklist"]}
    assert all(item["passed"] for item in checks.values())
    assert all(item["recorded"] is False for item in payload["signoff_requirements"])
    assert payload["review_items"]["forward_observation"]["data_gate_blocked_count"] == 0
    assert payload["review_items"]["strategy_evidence"]["evidence_audit_status"] == "validation_evidence_audit_ready_for_forward_observation"
    assert payload["review_items"]["strategy_evidence"]["evidence_complete_count"] == 12
    assert payload["review_items"]["forward_observation"]["continuity_passed"] is True
    assert payload["remediation_tickets"]["ticket_count"] == 0
    assert payload["review_items"]["remediation_tickets"]["ticket_count"] == 0
    assert checks["remediation_tickets_closed"]["passed"] is True
    assert checks["manual_decision_record_valid"]["passed"] is True
    assert payload["review_items"]["manual_decision_record"]["status"] == "manual_decision_record_valid"
    assert payload["review_items"]["manual_decision_record"]["decision"] == "paper_simulation_review_candidate"
    assert payload["guardrails"]["manual_approval_recorded"] is True
    assert payload["guardrails"]["paper_simulation_allowed"] is False
    assert payload["guardrails"]["live_order_allowed"] is False


def test_manual_review_packet_service_ready_is_manual_only(tmp_path: Path) -> None:
    _write_fixture_reports(tmp_path, observation_days=30, forward_status="forward_complete_for_manual_review")

    evaluation = evaluate_manual_review_packet(_service_reports(tmp_path))

    assert evaluation.status == "manual_review_ready"
    assert evaluation.blockers == []
    assert evaluation.guardrails["manual_approval_recorded"] is True
    assert evaluation.guardrails["paper_simulation_allowed"] is False
    assert evaluation.guardrails["live_order_allowed"] is False
    assert evaluation.paper_or_live_unlock_decision["manual_review_can_unlock_paper_by_itself"] is False
    assert evaluation.paper_or_live_unlock_decision["manual_review_can_unlock_live_by_itself"] is False
    checks = {item["check_id"]: item for item in evaluation.evidence_checklist}
    assert checks["manual_decision_record_valid"]["passed"] is True
    assert checks["no_unsafe_flags"]["passed"] is True


def test_manual_review_packet_service_blocks_unsafe_flags(tmp_path: Path) -> None:
    _write_fixture_reports(tmp_path, observation_days=30, forward_status="forward_complete_for_manual_review")
    live = tmp_path / "artifacts/us_equity_etf_macro_rotation/latest/us_equity_live_readiness_risk_constitution_report.json"
    payload = json.loads(live.read_text(encoding="utf-8"))
    payload["live_order_allowed"] = True
    live.write_text(json.dumps(payload), encoding="utf-8")

    evaluation = evaluate_manual_review_packet(_service_reports(tmp_path))

    assert evaluation.status == "manual_review_pending"
    assert any(item.startswith("us_equity_manual_review_unsafe_flag:live_readiness.live_order_allowed=true") for item in evaluation.blockers)
    checks = {item["check_id"]: item for item in evaluation.evidence_checklist}
    assert checks["no_unsafe_flags"]["passed"] is False


def test_manual_review_packet_blocks_unsafe_live_flag(tmp_path: Path) -> None:
    _write_fixture_reports(tmp_path, observation_days=30, forward_status="forward_complete_for_manual_review")
    live = tmp_path / "artifacts/us_equity_etf_macro_rotation/latest/us_equity_live_readiness_risk_constitution_report.json"
    payload = json.loads(live.read_text(encoding="utf-8"))
    payload["live_order_allowed"] = True
    live.write_text(json.dumps(payload), encoding="utf-8")

    report = build_us_equity_manual_review_packet(
        repo_root=tmp_path,
        output=Path("out/manual.json"),
        markdown_output=Path("out/manual.md"),
        generated_at="2026-06-25T00:00:00Z",
    )

    assert report["status"] == "manual_review_pending"
    _validate_schema(report)
    assert any(item.startswith("us_equity_manual_review_unsafe_flag:live_readiness.live_order_allowed=true") for item in report["blockers"])
    checks = {item["check_id"]: item for item in report["evidence_checklist"]}
    assert checks["no_unsafe_flags"]["passed"] is False


def test_manual_review_packet_blocks_incomplete_strategy_evidence_audit(tmp_path: Path) -> None:
    _write_fixture_reports(tmp_path, observation_days=30, forward_status="forward_complete_for_manual_review")
    audit = tmp_path / "artifacts/us_equity_etf_macro_rotation/latest/us_etf_strategy_validation_evidence_audit.json"
    payload = json.loads(audit.read_text(encoding="utf-8"))
    payload["status"] = "validation_evidence_audit_blocked_data_quality"
    payload["summary"]["complete_count"] = 11
    payload["summary"]["blocked_count"] = 1
    payload["incomplete_requirements"] = ["data_quality_pit"]
    audit.write_text(json.dumps(payload), encoding="utf-8")

    report = build_us_equity_manual_review_packet(
        repo_root=tmp_path,
        output=Path("out/manual.json"),
        markdown_output=Path("out/manual.md"),
        generated_at="2026-06-25T00:00:00Z",
    )

    assert report["status"] == "manual_review_pending"
    _validate_schema(report)
    assert "us_equity_manual_review_strategy_validation_evidence_audit_not_ready" in report["blockers"]
    assert "us_equity_manual_review_strategy_validation_evidence_blocked" in report["blockers"]
    checks = {item["check_id"]: item for item in report["evidence_checklist"]}
    assert checks["strategy_validation_evidence_audit_ready"]["passed"] is False


def test_manual_review_packet_blocks_forward_data_gate_failures(tmp_path: Path) -> None:
    _write_fixture_reports(tmp_path, observation_days=30, forward_status="forward_complete_for_manual_review")
    forward = tmp_path / "artifacts/us_equity_etf_macro_rotation/latest/us_etf_forward_observation_evaluation_report.json"
    payload = json.loads(forward.read_text(encoding="utf-8"))
    payload["daily_data_gate"] = {
        "daily_run_count": 2,
        "pass_count": 1,
        "blocked_count": 1,
        "blocked_reports": ["daily_blocked.json"],
    }
    payload["checks"]["daily_data_gate"] = {"passed": False, "blocked_count": 1}
    forward.write_text(json.dumps(payload), encoding="utf-8")

    report = build_us_equity_manual_review_packet(
        repo_root=tmp_path,
        output=Path("out/manual.json"),
        markdown_output=Path("out/manual.md"),
        generated_at="2026-06-25T00:00:00Z",
    )

    assert report["status"] == "manual_review_pending"
    _validate_schema(report)
    assert "us_equity_manual_review_forward_data_gate_had_blocked_runs" in report["blockers"]
    checks = {item["check_id"]: item for item in report["evidence_checklist"]}
    assert checks["forward_data_gate_no_blocked_runs"]["passed"] is False
    assert report["review_items"]["forward_observation"]["data_gate_blocked_count"] == 1


def test_manual_review_packet_blocks_forward_continuity_failures(tmp_path: Path) -> None:
    _write_fixture_reports(tmp_path, observation_days=30, forward_status="forward_complete_for_manual_review")
    forward = tmp_path / "artifacts/us_equity_etf_macro_rotation/latest/us_etf_forward_observation_evaluation_report.json"
    payload = json.loads(forward.read_text(encoding="utf-8"))
    payload["observation_continuity"]["passed"] = False
    payload["observation_continuity"]["duplicate_target_dates"] = ["2026-06-24"]
    payload["checks"]["observation_continuity"] = {"passed": False}
    forward.write_text(json.dumps(payload), encoding="utf-8")

    report = build_us_equity_manual_review_packet(
        repo_root=tmp_path,
        output=Path("out/manual.json"),
        markdown_output=Path("out/manual.md"),
        generated_at="2026-06-25T00:00:00Z",
    )

    assert report["status"] == "manual_review_pending"
    _validate_schema(report)
    assert "us_equity_manual_review_forward_observation_continuity_not_passed" in report["blockers"]
    checks = {item["check_id"]: item for item in report["evidence_checklist"]}
    assert checks["forward_observation_continuity_passed"]["passed"] is False
    assert report["review_items"]["forward_observation"]["continuity_passed"] is False


def test_manual_review_packet_blocks_open_remediation_tickets(tmp_path: Path) -> None:
    _write_fixture_reports(tmp_path, observation_days=30, forward_status="forward_complete_for_manual_review")
    blocker_taxonomy = tmp_path / "artifacts/us_equity_strategy_production_line/latest/us_equity_blocker_taxonomy_report.json"
    blocker_taxonomy.write_text(
        json.dumps(
            {
                "status": "blocked_external_and_time_dependencies",
                "remediation_tickets": [
                    {
                        "ticket_id": "us_equity_remediate_external_data",
                        "category": "external_data",
                        "owner": "operator_data_vendor",
                        "dependency_type": "external_user_action",
                        "status": "waiting_external_input",
                        "blocker_count": 3,
                        "source_reports": ["development_audit", "pit_handoff"],
                        "next_action": "Place production PIT files into the manual vendor drop.",
                        "acceptance_evidence": ["pit intake ready"],
                    }
                ],
                "guardrails": {"live_order_allowed": False},
            }
        ),
        encoding="utf-8",
    )

    report = build_us_equity_manual_review_packet(
        repo_root=tmp_path,
        output=Path("out/manual.json"),
        markdown_output=Path("out/manual.md"),
        generated_at="2026-06-25T00:00:00Z",
    )

    assert report["status"] == "manual_review_pending"
    _validate_schema(report)
    assert "us_equity_manual_review_remediation_tickets_open" in report["blockers"]
    assert report["remediation_tickets"]["ticket_count"] == 1
    assert report["review_items"]["remediation_tickets"]["ticket_count"] == 1
    checks = {item["check_id"]: item for item in report["evidence_checklist"]}
    assert checks["remediation_tickets_closed"]["passed"] is False


def test_manual_review_packet_blocks_missing_manual_decision_record(tmp_path: Path) -> None:
    _write_fixture_reports(
        tmp_path,
        observation_days=30,
        forward_status="forward_complete_for_manual_review",
        manual_decision_status="manual_decision_record_missing_or_invalid",
    )

    report = build_us_equity_manual_review_packet(
        repo_root=tmp_path,
        output=Path("out/manual.json"),
        markdown_output=Path("out/manual.md"),
        generated_at="2026-06-25T00:00:00Z",
    )

    assert report["status"] == "manual_review_pending"
    _validate_schema(report)
    assert "us_equity_manual_review_decision_record_not_valid" in report["blockers"]
    checks = {item["check_id"]: item for item in report["evidence_checklist"]}
    assert checks["manual_decision_record_valid"]["passed"] is False
    assert report["guardrails"]["manual_approval_recorded"] is False


def test_manual_review_packet_blocks_untraceable_manual_decision_evidence(tmp_path: Path) -> None:
    _write_fixture_reports(tmp_path, observation_days=30, forward_status="forward_complete_for_manual_review")
    decision_path = tmp_path / "artifacts/us_equity_etf_macro_rotation/latest/us_equity_manual_decision_record_report.json"
    decision = json.loads(decision_path.read_text(encoding="utf-8"))
    decision["evidence_path_details"] = [{"traceable_report_artifact": False}]
    decision_path.write_text(json.dumps(decision), encoding="utf-8")

    report = build_us_equity_manual_review_packet(
        repo_root=tmp_path,
        output=Path("out/manual.json"),
        markdown_output=Path("out/manual.md"),
        generated_at="2026-06-25T00:00:00Z",
    )

    assert report["status"] == "manual_review_pending"
    _validate_schema(report)
    checks = {item["check_id"]: item for item in report["evidence_checklist"]}
    assert checks["manual_decision_record_valid"]["passed"] is False
    assert checks["manual_decision_record_valid"]["evidence"]["traceable_evidence_path_count"] == 0
    assert report["review_items"]["manual_decision_record"]["traceable_evidence_path_count"] == 0


def test_manual_review_packet_blocks_non_candidate_manual_decision(tmp_path: Path) -> None:
    _write_fixture_reports(
        tmp_path,
        observation_days=30,
        forward_status="forward_complete_for_manual_review",
        manual_decision="continue_observation",
    )

    report = build_us_equity_manual_review_packet(
        repo_root=tmp_path,
        output=Path("out/manual.json"),
        markdown_output=Path("out/manual.md"),
        generated_at="2026-06-25T00:00:00Z",
    )

    assert report["status"] == "manual_review_pending"
    _validate_schema(report)
    assert "us_equity_manual_review_decision_record_not_paper_candidate" in report["blockers"]
    checks = {item["check_id"]: item for item in report["evidence_checklist"]}
    assert checks["manual_decision_record_valid"]["passed"] is False
    assert report["guardrails"]["manual_approval_recorded"] is False


def test_manual_review_packet_schema_rejects_paper_unlock(tmp_path: Path) -> None:
    _write_fixture_reports(tmp_path, observation_days=30, forward_status="forward_complete_for_manual_review")
    payload = build_us_equity_manual_review_packet(
        repo_root=tmp_path,
        output=Path("out/manual.json"),
        markdown_output=Path("out/manual.md"),
        generated_at="2026-06-25T00:00:00Z",
    )
    payload["paper_or_live_unlock_decision"]["manual_review_can_unlock_paper_by_itself"] = True

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError:
        return
    raise AssertionError("schema accepted manual_review_can_unlock_paper_by_itself=true")


def test_manual_review_packet_schema_rejects_forward_progress_unlock(tmp_path: Path) -> None:
    _write_fixture_reports(tmp_path, observation_days=30, forward_status="forward_complete_for_manual_review")
    payload = build_us_equity_manual_review_packet(
        repo_root=tmp_path,
        output=Path("out/manual.json"),
        markdown_output=Path("out/manual.md"),
        generated_at="2026-06-25T00:00:00Z",
    )
    payload["forward_review_progress"]["paper_or_live_unlock_allowed"] = True

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError:
        return
    raise AssertionError("schema accepted forward_review_progress.paper_or_live_unlock_allowed=true")


def _write_fixture_reports(
    root: Path,
    *,
    observation_days: int,
    forward_status: str,
    manual_decision_status: str = "manual_decision_record_valid",
    manual_decision: str = "paper_simulation_review_candidate",
) -> None:
    _write_json(
        root / "artifacts/us_equity_etf_macro_rotation/latest/us_etf_strategy_validation_gate_report.json",
        {
            "status": "validation_passed_for_forward_observation",
            "paper_simulation_allowed": False,
            "live_order_allowed": False,
        },
    )
    _write_json(
        root / "artifacts/us_equity_etf_macro_rotation/latest/us_etf_strategy_validation_evidence_audit.json",
        {
            "status": "validation_evidence_audit_ready_for_forward_observation",
            "summary": {
                "requirement_count": 12,
                "complete_count": 12,
                "blocked_count": 0,
                "incomplete_count": 0,
                "paper_or_live_unlock_allowed": False,
                "live_order_allowed": False,
            },
            "incomplete_requirements": [],
            "guardrails": {
                "paper_or_live_unlock_allowed": False,
                "paper_simulation_allowed": False,
                "live_order_allowed": False,
            },
        },
    )
    completed_milestones = [days for days in [30, 60, 90] if observation_days >= days]
    next_milestone = next((days for days in [30, 60, 90] if observation_days < days), None)
    _write_json(
        root / "artifacts/us_equity_etf_macro_rotation/latest/us_etf_forward_observation_evaluation_report.json",
        {
            "status": forward_status,
            "metrics": {"observation_days": observation_days},
            "review_progress": {
                "observation_days": observation_days,
                "minimum_complete_days": 30,
                "review_milestones": [30, 60, 90],
                "completed_milestones": completed_milestones,
                "next_milestone": next_milestone,
                "days_until_minimum": max(0, 30 - observation_days),
                "manual_review_required": forward_status == "forward_complete_for_manual_review",
                "manual_review_only_no_paper_or_live_unlock": forward_status == "forward_complete_for_manual_review",
                "alpha_validation_claim_allowed": False,
                "paper_or_live_unlock_allowed": False,
            },
            "checks": {
                "ledger_recalculation": {"passed": True},
                "target_fill_consistency": {"passed": True},
                "daily_data_gate": {"passed": True, "blocked_count": 0},
            },
            "daily_data_gate": {"daily_run_count": 1, "pass_count": 1, "blocked_count": 0, "blocked_reports": []},
            "observation_continuity": {
                "passed": True,
                "duplicate_target_dates": [],
                "duplicate_snapshot_dates": [],
                "missing_snapshot_for_target": [],
                "missing_target_for_snapshot": [],
            },
            "guardrails": {
                "forward_evaluation_is_not_alpha_validation": True,
                "paper_simulation_allowed": False,
                "live_order_allowed": False,
            },
        },
    )
    _write_json(root / "artifacts/us_equity_data_status/latest/us_equity_data_freshness_daily_report.json", {"status": "pass", "macro_freshness": {"status": "present"}})
    _write_json(root / "artifacts/us_equity_etf_macro_rotation/latest/us_etf_small_account_execution_preflight_report.json", {"status": "pass_observation_only"})
    _write_json(
        root / "artifacts/us_equity_etf_macro_rotation/latest/us_equity_live_readiness_risk_constitution_report.json",
        {
            "status": "live_readiness_blocked",
            "paper_simulation_allowed": False,
            "live_order_allowed": False,
            "private_endpoint_used": False,
            "order_endpoint_used": False,
        },
    )
    _write_json(
        root / "artifacts/us_equity_etf_macro_rotation/latest/us_equity_manual_decision_record_report.json",
        {
            "status": manual_decision_status,
            "record_summary": {
                "decision": manual_decision,
                "reviewer_recorded": manual_decision_status == "manual_decision_record_valid",
                "evidence_path_count": 1 if manual_decision_status == "manual_decision_record_valid" else 0,
            },
            "evidence_path_details": (
                [{"traceable_report_artifact": True}]
                if manual_decision_status == "manual_decision_record_valid"
                else []
            ),
            "guardrails": {
                "paper_or_live_unlock_allowed": False,
                "paper_simulation_allowed": False,
                "live_order_allowed": False,
            },
        },
    )
    _write_json(
        root / "artifacts/us_equity_data_lineage/latest/us_equity_pit_data_intake_status_report.json",
        {"status": "production_pit_data_intake_ready", "current_blocking_stage": None},
    )
    _write_json(
        root / "artifacts/us_equity_data_lineage/latest/us_equity_pit_bundle_acceptance_run_report.json",
        {"status": "acceptance_ready_for_manual_config_apply", "current_blocking_step": None},
    )
    _write_json(
        root / "artifacts/us_equity_strategy_production_line/latest/us_equity_blocker_taxonomy_report.json",
        {"status": "no_blockers_detected", "remediation_tickets": [], "guardrails": {"live_order_allowed": False}},
    )


def _service_reports(root: Path) -> dict[str, dict[str, object]]:
    latest = root / "artifacts/us_equity_etf_macro_rotation/latest"
    return {
        "strategy_gate": _read_json(latest / "us_etf_strategy_validation_gate_report.json"),
        "strategy_evidence_audit": _read_json(latest / "us_etf_strategy_validation_evidence_audit.json"),
        "forward_evaluation": _read_json(latest / "us_etf_forward_observation_evaluation_report.json"),
        "data_freshness": _read_json(root / "artifacts/us_equity_data_status/latest/us_equity_data_freshness_daily_report.json"),
        "small_account_preflight": _read_json(latest / "us_etf_small_account_execution_preflight_report.json"),
        "live_readiness": _read_json(latest / "us_equity_live_readiness_risk_constitution_report.json"),
        "manual_decision_record": _read_json(latest / "us_equity_manual_decision_record_report.json"),
        "production_pit_intake_status": _read_json(root / "artifacts/us_equity_data_lineage/latest/us_equity_pit_data_intake_status_report.json"),
        "pit_bundle_acceptance": _read_json(root / "artifacts/us_equity_data_lineage/latest/us_equity_pit_bundle_acceptance_run_report.json"),
        "blocker_taxonomy": _read_json(root / "artifacts/us_equity_strategy_production_line/latest/us_equity_blocker_taxonomy_report.json"),
    }


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _validate_schema(payload: dict[str, object]) -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError as exc:
        raise AssertionError(f"schema validation failed: {exc.message}") from exc
