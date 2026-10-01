from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from pathlib import Path

from quant_crypto.research.btc_paper_live_kill_switch_status import build_btc_paper_live_kill_switch_status


def test_kill_switch_fail_closed_when_upstream_reports_are_blocked(tmp_path: Path) -> None:
    paths = _write_inputs(tmp_path, blocked=True)
    report = _build(tmp_path, paths)

    assert report["status"] == "fail_closed_research_only"
    assert report["policy_state"]["kill_switch_engaged"] is True
    assert report["policy_state"]["cancel_only_mode"] is True
    assert report["policy_state"]["paper_order_intake_allowed"] is False
    assert report["policy_state"]["position_increase_allowed"] is False
    assert report["policy_state"]["micro_live_allowed"] is False
    assert report["clearance_checklist"]["schema_version"] == "btc_kill_switch_clearance_checklist_v1"
    assert report["clearance_checklist"]["status"] == "blocked_clearance_required"
    assert report["clearance_checklist"]["state_verification"]["cancel_only_verified"] is True
    assert report["clearance_checklist"]["state_verification"]["reduce_only_verified"] is True
    assert report["clearance_checklist"]["state_verification"]["paper_order_intake_disabled_verified"] is True
    assert report["clearance_checklist"]["reset_drill_boundary"]["can_clear_paper_intake_blocker"] is True
    assert report["clearance_checklist"]["reset_drill_boundary"]["can_clear_live_blocker"] is False
    assert report["clearance_checklist"]["manual_confirmation_required"]
    assert report["clearance_checklist"]["rerun_reports_required"]
    assert report["clearance_checklist"]["data_backfill_required"]
    clearance = report["clearance_checklist"]["blocker_clearance"]
    assert clearance["schema_version"] == "btc_kill_switch_blocker_clearance_classes_v1"
    assert report["clearance_checklist"]["auto_unlock_after_clearance_allowed"] is False
    assert clearance["counts"]["clearable"] >= 1
    assert clearance["counts"]["wait_only"] >= 1
    assert "perpetual_execution_evidence:source_blocker:depth_missing" in clearance["data_wait"]
    assert "strategy_promotion_readiness:status:blocked_research_only" in clearance["strategy_forward_gap"]
    assert clearance["non_clearable_after_all_clearance"] == [
        "paper_queue_write_allowed_remains_false_until_separate_operator_enablement",
        "live_unlock_allowed_remains_false_until_separate_live_governance",
        "broker_order_private_endpoints_remain_disabled_by_this_report",
    ]
    assert "strategy_promotion_readiness:status:blocked_research_only" in report["blockers"]
    assert "exchange_runtime_gap:status:incomplete_research_only" in report["blockers"]
    assert "perpetual_execution_evidence:source_blocker:depth_missing" in report["blockers"]


def test_kill_switch_detects_accidental_paper_or_live_true_flags(tmp_path: Path) -> None:
    paths = _write_inputs(tmp_path, blocked=False)
    readiness = json.loads(paths["readiness"].read_text(encoding="utf-8"))
    readiness["gate"]["live_unlock_allowed"] = True
    readiness["guardrails"]["paper_queue_write_allowed"] = True
    paths["readiness"].write_text(json.dumps(readiness), encoding="utf-8")

    report = _build(tmp_path, paths)

    assert report["summary"]["true_safety_flag_blocker_count"] == 2
    assert "strategy_promotion_readiness:true_flag:gate.live_unlock_allowed" in report["blockers"]
    assert "strategy_promotion_readiness:true_flag:guardrails.paper_queue_write_allowed" in report["blockers"]
    assert "strategy_promotion_readiness:true_flag:gate.live_unlock_allowed" in report["clearance_checklist"]["non_clearable_blockers"]
    assert "strategy_promotion_readiness:true_flag:guardrails.paper_queue_write_allowed" in report["clearance_checklist"]["non_clearable_blockers"]
    assert report["policy_state"]["kill_switch_engaged"] is True
    assert report["gate"]["live_unlock_allowed"] is False


def test_kill_switch_requires_manual_approval_even_when_inputs_are_clean(tmp_path: Path) -> None:
    paths = _write_inputs(tmp_path, blocked=False)
    report = _build(tmp_path, paths)

    assert report["blockers"] == [
        "manual_paper_review_approval:manual_approval_not_recorded",
        "manual_paper_review_approval:manual_review_missing_not_cleared",
    ]
    assert report["summary"]["check_fail_count"] == 1
    assert report["policy_state"]["manual_approval_required"] is True
    assert report["policy_state"]["manual_approval_recorded"] is False
    assert report["policy_state"]["paper_order_intake_allowed"] is False
    assert report["policy_state"]["micro_live_allowed"] is False
    assert report["clearance_checklist"]["status"] == "blocked_clearance_required"
    assert report["clearance_checklist"]["manual_confirmation_required"] == [
        "manual_paper_review_approval:manual_approval_not_recorded",
        "manual_paper_review_approval:manual_review_missing_not_cleared",
    ]
    assert report["clearance_checklist"]["clearable_blockers"] == [
        "manual_paper_review_approval:manual_approval_not_recorded",
        "manual_paper_review_approval:manual_review_missing_not_cleared",
    ]
    assert report["clearance_checklist"]["wait_only_blockers"] == []
    assert report["clearance_checklist"]["non_clearable_blockers"] == []
    assert report["clearance_checklist"]["reset_drill_boundary"]["live_remains_frozen_after_reset_drill"] is True


def _build(tmp_path: Path, paths: dict[str, Path]) -> dict[str, object]:
    return build_btc_paper_live_kill_switch_status(
        output_dir=tmp_path / "out",
        readiness_report_path=paths["readiness"],
        exchange_runtime_gap_report_path=paths["runtime_gap"],
        paper_runtime_reconciliation_report_path=paths["reconciliation"],
        paper_exchange_rule_preflight_report_path=paths["exchange_preflight"],
        paper_risk_circuit_breaker_drill_report_path=paths["risk_circuit_breaker"],
        perp_execution_evidence_report_path=paths["perp_evidence"],
        gate_dashboard_report_path=paths["gate_dashboard"],
        manual_paper_review_approval_report_path=paths["manual_paper_review_approval"],
        generated_at_utc=datetime(2026, 7, 1, tzinfo=timezone.utc),
    )


def _write_inputs(tmp_path: Path, *, blocked: bool) -> dict[str, Path]:
    clean_payloads = _clean_payloads()
    if blocked:
        clean_payloads["readiness"]["status"] = "blocked_research_only"
        clean_payloads["readiness"]["decision"] = "btc_strategy_promotion_readiness_blocked_no_paper_no_live"
        clean_payloads["readiness"]["blockers"] = ["observe_under_30d"]
        clean_payloads["runtime_gap"]["status"] = "incomplete_research_only"
        clean_payloads["runtime_gap"]["decision"] = "runtime_replay_gap_incomplete_fail_closed_no_paper_no_live"
        clean_payloads["runtime_gap"]["blockers"] = ["paper_runtime_not_ready"]
        clean_payloads["perp_evidence"]["status"] = "incomplete_research_only"
        clean_payloads["perp_evidence"]["decision"] = "perpetual_execution_evidence_incomplete_fail_closed_no_paper_no_live"
        clean_payloads["perp_evidence"]["blockers"] = ["depth_missing"]
        clean_payloads["gate_dashboard"]["status"] = "blocked"
        clean_payloads["gate_dashboard"]["blockers"] = ["dashboard_blocker"]

    paths = {
        "readiness": tmp_path / "readiness.json",
        "runtime_gap": tmp_path / "runtime_gap.json",
        "reconciliation": tmp_path / "reconciliation.json",
        "exchange_preflight": tmp_path / "exchange_preflight.json",
        "risk_circuit_breaker": tmp_path / "risk_circuit_breaker.json",
        "perp_evidence": tmp_path / "perp_evidence.json",
        "gate_dashboard": tmp_path / "gate_dashboard.json",
        "manual_paper_review_approval": tmp_path / "manual_paper_review_approval.json",
    }
    for key, path in paths.items():
        path.write_text(json.dumps(clean_payloads[key]), encoding="utf-8")
    return paths


def _clean_payloads() -> dict[str, dict[str, object]]:
    base_gate = {
        "paper_queue_write_allowed": False,
        "paper_candidate_created": False,
        "live_unlock_allowed": False,
        "live_order_allowed": False,
        "oms_access_allowed": False,
        "broker_access_allowed": False,
        "strategy_skeleton_generated": False,
    }
    base_guardrails = {
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "real_order_submitted": False,
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
        "oms_access_allowed": False,
        "broker_access_allowed": False,
    }
    return {
        "readiness": {
            "status": "complete_research_only",
            "decision": "btc_strategy_promotion_readiness_research_only_no_paper_no_live",
            "blockers": [],
            "gate": copy.deepcopy(base_gate),
            "guardrails": copy.deepcopy(base_guardrails),
        },
        "runtime_gap": {
            "status": "complete_research_only",
            "decision": "runtime_replay_ready_for_manual_review_research_only_no_auto_paper_no_live",
            "blockers": [],
            "gate": copy.deepcopy(base_gate),
            "guardrails": copy.deepcopy(base_guardrails),
        },
        "reconciliation": {
            "status": "complete_research_only",
            "decision": "paper_runtime_event_ledger_reconciled_research_only_no_paper_no_live",
            "blockers": [],
            "summary": {"paper_runtime_reconciliation_passed": True, "violation_count": 0},
            "gate": copy.deepcopy(base_gate),
            "guardrails": copy.deepcopy(base_guardrails),
        },
        "perp_evidence": {
            "status": "complete_research_only",
            "decision": "perpetual_execution_evidence_present_manual_review_required_no_auto_paper_no_live",
            "blockers": [],
            "gate": copy.deepcopy(base_gate),
            "guardrails": copy.deepcopy(base_guardrails),
        },
        "exchange_preflight": {
            "status": "complete_research_only",
            "decision": "btc_paper_exchange_rule_preflight_complete_manual_review_required_no_auto_paper_no_live",
            "blockers": [],
            "gate": copy.deepcopy(base_gate),
            "guardrails": copy.deepcopy(base_guardrails),
        },
        "risk_circuit_breaker": {
            "status": "complete_research_only",
            "decision": "btc_paper_risk_circuit_breaker_drill_passed_research_only_no_paper_no_live",
            "blockers": [],
            "gate": copy.deepcopy(base_gate),
            "guardrails": copy.deepcopy(base_guardrails),
        },
        "gate_dashboard": {
            "status": "pass",
            "decision": "gate_dashboard_pass_research_only",
            "blockers": [],
            "gate": copy.deepcopy(base_gate),
            "guardrails": copy.deepcopy(base_guardrails),
        },
        "manual_paper_review_approval": {
            "status": "complete_research_only",
            "decision": "btc_manual_paper_review_approval_missing_or_invalid_no_paper_no_live",
            "manual_approval_recorded": False,
            "manual_review_missing_cleared": False,
            "paper_queue_write_allowed": False,
            "paper_order_intake_allowed": False,
            "live_unlock_allowed": False,
            "blockers": [],
            "gate": copy.deepcopy(base_gate),
            "guardrails": copy.deepcopy(base_guardrails),
        },
    }
