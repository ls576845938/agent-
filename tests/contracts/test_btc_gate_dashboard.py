from __future__ import annotations

from datetime import datetime, timezone

from quant_crypto.monitoring.artifact_schema import validate_btc_artifact_schema
from quant_crypto.monitoring.gate_dashboard import build_btc_gate_dashboard


TS = datetime(2026, 6, 26, 8, 0, tzinfo=timezone.utc)
HASH = "a" * 64


def _artifact(status: str = "complete") -> dict[str, object]:
    return {
        "status": status,
        "decision": "ok",
        "generated_at": "2026-06-26T08:00:00Z",
        "next_required_action": "none",
        "blockers": ["blocked"] if status == "blocked" else [],
        "artifact_hash": HASH,
    }


def test_btc_gate_dashboard_completes_for_paper_observing_live_frozen_with_complete_artifacts() -> None:
    payload = build_btc_gate_dashboard(
        generated_at_utc=TS,
        current_status={"status": "paper_observing", "live_status": "frozen"},
        registry={"assets": {"btc": {"paper_queue_status": "approved", "candidate_passed_internal_gate": 1}}},
        paper_readiness={"status": "ready_for_paper_start", "paper_queue_status": "approved", "paper_start_allowed": True},
        artifacts={
            "paper_validation_start": _artifact(),
            "paper_validation_runtime": _artifact(),
            "paper_validation_evaluation": _artifact(),
            "api_key_permission_audit": _artifact(),
            "order_surface_audit": _order_surface_audit_artifact(),
            "account_attestation": _account_attestation_artifact(),
            "trend_boundary": _artifact(),
        },
    )

    assert payload["status"] == "complete"
    assert payload["live_state"]["live_order_allowed"] is False
    assert payload["sources"]["current_status"]["status"] == "paper_observing"
    assert payload["artifacts"]["paper_validation_start"]["generated_at"] == "2026-06-26T08:00:00Z"
    assert payload["artifacts"]["paper_validation_start"]["next_action"] == "none"
    assert payload["root_cause_dag"]["root_node_id"] == "btc_gate_dashboard_blocked"
    assert payload["root_cause_summary"]["root_cause_count"] == 0
    assert payload["coverage"]["account_attestation"] is True
    assert payload["security_attestation_state"]["account_attestation_status"] == "verified_research_only"
    assert payload["security_attestation_state"]["account_attestation_manual_only"] is True
    assert validate_btc_artifact_schema(payload) == []


def test_btc_gate_dashboard_covers_daily_cost_funding_and_live_readiness_without_unlocking_live() -> None:
    payload = build_btc_gate_dashboard(
        generated_at_utc=TS,
        current_status={
            "status": "paper_observing",
            "live_status": "frozen",
            "generated_at": "2026-06-26T08:00:00Z",
        },
        registry={"assets": {"btc": {"status": "research_sandbox", "paper_queue_status": "approved", "candidate_passed_internal_gate": 1}}},
        paper_readiness={"status": "ready_for_paper_start", "paper_queue_status": "approved", "paper_start_allowed": True},
        artifacts={
            "exchange_runtime_contract": _artifact(),
            "daily_observation": {
                **_artifact("PASS"),
                "forward_observation": {"observation_days": 5},
                "guardrails": {
                    "simulated_only": True,
                    "private_endpoint_used": False,
                    "order_endpoint_used": False,
                    "real_order_submitted": False,
                },
            },
            "cost_model": _artifact("pass"),
            "funding_ledger": {
                "generated_at": "2026-06-26T08:00:00Z",
                "blockers": [],
                "artifact_hash": HASH,
                "funding_adjusted_net_pnl_reconciled": True,
                "funding_payment_in_ledger": True,
            },
            "perpetual_route_request": {
                **_artifact("complete_research_only"),
                "perpetual_route_requested": True,
                "gate": {"paper_queue_write_allowed": False, "live_unlock_allowed": False},
            },
            "perpetual_policy_status": {
                **_artifact("complete"),
                "policy_decision": "perpetual_path_disabled_for_current_strategy",
                "current_route": "spot_or_unlevered_path_perpetual_disabled",
                "current_strategy_uses_perpetual": False,
                "gate": {"perpetual_allowed": False, "live_unlock_allowed": False},
            },
            "perpetual_execution_evidence": {
                **_artifact("complete_research_only"),
                "summary": {"blocker_count": 0},
            },
            "paper_validation_start": _artifact(),
            "paper_validation_runtime": _artifact(),
            "paper_validation_evaluation": _artifact(),
            "api_key_permission_audit": _artifact(),
            "order_surface_audit": _order_surface_audit_artifact(),
            "account_attestation": _account_attestation_artifact(),
            "live_readiness": {
                **_artifact("live_readiness_blocked"),
                "live_order_allowed": False,
                "real_order_submitted": False,
                "forward_observation": {"minimum_complete_days": 30},
                "blockers": ["btc_live_readiness_forward_observation_less_than_30_days"],
            },
            "trend_boundary": _artifact(),
        },
    )

    assert payload["status"] == "complete"
    assert payload["coverage"] == {
        "current_status": True,
        "paper_validation": True,
        "daily_observation": True,
        "cost_model": True,
        "funding_ledger": True,
        "perpetual_route_request": True,
        "perpetual_policy_status": True,
        "perpetual_execution_evidence": True,
        "live_readiness": True,
        "micro_live_preflight": False,
        "api_key_permission_audit": True,
        "order_surface_audit": True,
        "account_attestation": True,
        "exchange_runtime": True,
    }
    assert payload["forward_observation"]["observation_days"] == 5
    assert payload["forward_observation"]["minimum_complete_days"] == 30
    assert payload["live_state"]["live_order_allowed"] is False
    assert payload["live_state"]["micro_live_allowed"] is False
    assert payload["live_state"]["live_readiness_status"] == "live_readiness_blocked"
    assert payload["live_state"]["live_readiness_blockers"] == [
        "btc_live_readiness_forward_observation_less_than_30_days"
    ]
    assert payload["artifacts"]["cost_model"]["status"] == "pass"
    assert payload["artifacts"]["funding_ledger"]["status"] == "funding_ledger_reconciled"
    assert payload["security_attestation_state"]["order_surface_audit_decision"] == "non_oms_order_surface_clean"
    assert payload["security_attestation_state"]["order_surface_audit_clean"] is True
    assert payload["security_attestation_state"]["order_surface_finding_count"] == 0
    assert payload["perpetual_state"]["current_strategy_uses_perpetual"] is False
    assert payload["perpetual_state"]["perpetual_allowed"] is False
    assert validate_btc_artifact_schema(payload) == []


def test_btc_gate_dashboard_surfaces_and_blocks_micro_live_preflight() -> None:
    payload = build_btc_gate_dashboard(
        generated_at_utc=TS,
        current_status={"status": "paper_observing", "live_status": "frozen"},
        registry={"assets": {"btc": {"paper_queue_status": "approved", "candidate_passed_internal_gate": 1}}},
        paper_readiness={"status": "ready_for_paper_start", "paper_queue_status": "approved", "paper_start_allowed": True},
        artifacts={
            "micro_live_preflight": {
                **_artifact("blocked_fail_closed_research_only"),
                "decision": "btc_micro_live_preflight_blocked_fail_closed_no_live",
                "blockers": ["observe_only_health:60d_observe_only_not_complete", "manual_approval_missing"],
                "policy_state": {"micro_live_allowed": False, "live_unlock_allowed": False},
            },
        },
    )

    assert payload["status"] == "blocked"
    assert payload["coverage"]["micro_live_preflight"] is True
    assert payload["live_state"]["micro_live_allowed"] is False
    assert payload["live_state"]["micro_live_preflight_status"] == "blocked_fail_closed_research_only"
    assert payload["live_state"]["micro_live_preflight_blocker_count"] == 2
    assert "btc_gate_dashboard_micro_live_preflight_blocked" in payload["blockers"]
    root_ids = {row["root_cause_id"] for row in payload["root_cause_matrix"]}
    assert "runtime_not_connected" not in root_ids
    assert "strategy_overfit_or_forward_gap" in root_ids
    assert "manual_review_approval_missing" in root_ids
    assert validate_btc_artifact_schema(payload) == []


def test_btc_gate_dashboard_blocks_perpetual_execution_evidence_blockers() -> None:
    payload = build_btc_gate_dashboard(
        generated_at_utc=TS,
        current_status={"status": "paper_observing", "live_status": "frozen"},
        registry={"assets": {"btc": {"paper_queue_status": "approved", "candidate_passed_internal_gate": 1}}},
        paper_readiness={"status": "ready_for_paper_start", "paper_queue_status": "approved", "paper_start_allowed": True},
        artifacts={
            "perpetual_execution_evidence": {
                **_artifact("incomplete_research_only"),
                "blockers": ["btc_perp_exec_depth_aware_slippage_history_verified"],
            },
        },
    )

    assert payload["status"] == "blocked"
    assert (
        "btc_gate_dashboard_artifact_blocker:perpetual_execution_evidence:"
        "btc_perp_exec_depth_aware_slippage_history_verified"
    ) in payload["blockers"]


def test_btc_gate_dashboard_blocks_missing_blocked_artifacts_and_live_unfrozen() -> None:
    payload = build_btc_gate_dashboard(
        generated_at_utc=TS,
        current_status={"status": "paper_observing", "live_status": "enabled"},
        registry={"assets": {"btc": {"paper_queue_status": "pending_review"}}},
        paper_readiness={"status": "blocked", "paper_queue_status": "pending_review", "paper_start_allowed": False},
        artifacts={
            "paper_validation_start": _artifact(),
            "paper_validation_runtime": _artifact("blocked"),
            "trend_boundary": None,
        },
    )

    assert payload["status"] == "blocked"
    assert "btc_gate_dashboard_live_status_not_frozen" in payload["blockers"]
    assert "btc_gate_dashboard_registry_paper_queue_not_approved" in payload["blockers"]
    assert "btc_gate_dashboard_artifact_blocked:paper_validation_runtime" in payload["blockers"]
    assert "btc_gate_dashboard_artifact_missing:trend_boundary" in payload["blockers"]
    root_ids = {row["root_cause_id"] for row in payload["root_cause_matrix"]}
    assert "uncategorized_blocker" not in root_ids
    assert "manual_review_approval_missing" in root_ids
    assert "runtime_not_connected" in root_ids


def test_btc_gate_dashboard_blocks_unsafe_artifact_flags() -> None:
    payload = build_btc_gate_dashboard(
        generated_at_utc=TS,
        current_status={"status": "paper_observing", "live_status": "frozen"},
        registry={"assets": {"btc": {"paper_queue_status": "approved", "candidate_passed_internal_gate": 1}}},
        paper_readiness={"status": "ready_for_paper_start", "paper_queue_status": "approved", "paper_start_allowed": True},
        artifacts={
            "daily_observation": {
                **_artifact("PASS"),
                "guardrails": {"order_endpoint_used": True, "real_order_submitted": False},
            },
        },
    )

    assert payload["status"] == "blocked"
    assert "btc_gate_dashboard_unsafe_flag:daily_observation.guardrails.order_endpoint_used=true" in payload["blockers"]
    assert "safety_fail_closed" in {row["root_cause_id"] for row in payload["root_cause_matrix"]}


def test_btc_gate_dashboard_blocks_unsafe_micro_live_flag() -> None:
    payload = build_btc_gate_dashboard(
        generated_at_utc=TS,
        current_status={"status": "paper_observing", "live_status": "frozen"},
        registry={"assets": {"btc": {"paper_queue_status": "approved", "candidate_passed_internal_gate": 1}}},
        paper_readiness={"status": "ready_for_paper_start", "paper_queue_status": "approved", "paper_start_allowed": True},
        artifacts={
            "micro_live_preflight": {
                **_artifact("complete_research_only"),
                "policy_state": {"micro_live_allowed": True, "live_unlock_allowed": False},
            },
        },
    )

    assert payload["status"] == "blocked"
    assert "btc_gate_dashboard_unsafe_flag:micro_live_preflight.policy_state.micro_live_allowed=true" in payload["blockers"]
    assert "safety_fail_closed" in {row["root_cause_id"] for row in payload["root_cause_matrix"]}


def test_btc_gate_dashboard_uses_promotion_root_cause_as_display_source() -> None:
    promotion_root_matrix = [
        {
            "root_cause_id": "runtime_ready_waiting_non_flat_sample",
            "blocker_count": 1,
            "source_count": 1,
            "representative_blockers": ["trade_execution_evidence_pending_reason:waiting_for_current_gate_eligible_non_flat_fill"],
        }
    ]
    payload = build_btc_gate_dashboard(
        generated_at_utc=TS,
        current_status={"status": "paper_observing", "live_status": "frozen"},
        registry={"assets": {"btc": {"paper_queue_status": "pending_review"}}},
        paper_readiness={
            "status": "current_packet_review_only_approved_promotion_blocked",
            "paper_queue_status": "current_packet_review_only_approved_promotion_blocked",
            "paper_start_allowed": False,
        },
        artifacts={
            "micro_live_preflight": {
                **_artifact("blocked_fail_closed_research_only"),
                "blockers": ["manual_approval_missing", "runtime_not_connected"],
            },
        },
        promotion_gate_control={
            "status": "blocked_research_only",
            "decision": "btc_promotion_gate_control_blocked_fail_closed",
            "root_cause_summary": {"root_cause_count": 1},
            "root_cause_matrix": promotion_root_matrix,
            "root_cause_task_queue": {"dashboard_should_show_root_causes_only": True},
            "root_cause_dag": {
                "schema_version": "btc_root_cause_dag_v1",
                "root_node_id": "btc_promotion_gate_control_blocked",
                "root_cause_count": 1,
                "root_cause_matrix": promotion_root_matrix,
                "task_queue": {"dashboard_should_show_root_causes_only": True},
            },
        },
    )

    assert payload["root_cause_source"] == "promotion_gate_control"
    assert {row["root_cause_id"] for row in payload["root_cause_matrix"]} == {
        "runtime_ready_waiting_non_flat_sample"
    }
    dashboard_source_ids = {row["root_cause_id"] for row in payload["dashboard_source_root_cause_matrix"]}
    assert "manual_review_approval_missing" in dashboard_source_ids
    assert "runtime_not_connected" in dashboard_source_ids
    assert "promotion_gate_control" in payload["sources"]


def _account_attestation_artifact() -> dict[str, object]:
    return {
        **_artifact("verified_research_only"),
        "decision": "btc_paper_account_runtime_attestation_verified_manual_review_only_no_auto_paper_no_live",
        "attestation_current": True,
        "credential_permissions_verified": True,
        "credential_separation_verified": True,
        "manual_approval_recorded": True,
        "gate": {"manual_attestation_only": True, "paper_order_intake_allowed": False, "live_unlock_allowed": False},
    }


def _order_surface_audit_artifact() -> dict[str, object]:
    return {
        **_artifact("complete"),
        "decision": "non_oms_order_surface_clean",
        "blockers": [],
        "findings": [],
        "non_blocking_match_count": 3,
    }
