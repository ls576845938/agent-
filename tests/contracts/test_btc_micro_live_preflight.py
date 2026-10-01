from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from pathlib import Path

from quant_crypto.research.btc_micro_live_preflight import build_btc_micro_live_preflight


TS = datetime(2026, 7, 1, 9, 0, tzinfo=timezone.utc)


def test_micro_live_preflight_blocks_current_like_incomplete_evidence(tmp_path: Path) -> None:
    paths = _write_inputs(tmp_path, blocked=True)
    report = _build(tmp_path, paths)

    assert report["status"] == "blocked_fail_closed_research_only"
    assert report["decision"] == "btc_micro_live_preflight_blocked_fail_closed_no_live"
    assert report["policy_state"]["micro_live_allowed"] is False
    assert report["policy_state"]["live_unlock_allowed"] is False
    assert report["policy_state"]["paper_order_intake_allowed"] is False
    assert report["summary"]["observe_only_60d_complete"] is False
    assert report["summary"]["paper_runtime_current_simulated_fill_count"] == 0
    assert report["summary"]["paper_runtime_health_status"] == "current_flat_heartbeat_healthy_waiting_for_trade_sample"
    assert report["summary"]["paper_runtime_current_flat_heartbeat_healthy"] is True
    assert report["summary"]["paper_runtime_trade_execution_evidence_available"] is False
    assert (
        report["summary"]["paper_runtime_trade_execution_evidence_pending_reason"]
        == "waiting_for_current_gate_eligible_non_flat_fill"
    )
    assert report["summary"]["paper_exchange_current_order_sample_status"] == "current_flat_heartbeat_waiting_for_order_sample"
    assert report["summary"]["paper_exchange_current_order_sample_available"] is False
    assert report["summary"]["paper_exchange_current_flat_no_order_healthy"] is True
    assert (
        report["summary"]["paper_exchange_current_order_sample_pending_reason"]
        == "current_observe_only_signal_flat_waiting_for_exchange_filter_sample"
    )
    assert report["summary"]["kill_switch_engaged"] is True
    assert "observe_only_health:60d_observe_only_not_complete" in report["blockers"]
    assert "strategy_promotion_readiness:no_line_ready_for_manual_paper_review" in report["blockers"]
    assert "paper_runtime_replay:current_flat_heartbeat_waiting_for_trade_sample" in report["blockers"]
    assert "paper_exchange_rule_preflight:current_flat_waiting_for_order_filter_sample" in report["blockers"]
    assert "manual_approval_missing" in report["blockers"]
    assert (tmp_path / "out" / "btc_micro_live_preflight_report.json").exists()
    assert (tmp_path / "out" / "btc_micro_live_preflight_matrix.csv").exists()
    assert (tmp_path / "out" / "btc_micro_live_preflight_summary_cn.md").exists()
    assert (tmp_path / "out" / "paper_live_safety_status.json").exists()


def test_micro_live_preflight_requires_manual_gate_and_size_envelope_even_if_sources_are_clean(tmp_path: Path) -> None:
    paths = _write_inputs(tmp_path, blocked=False)
    report = _build(tmp_path, paths)

    assert report["status"] == "blocked_fail_closed_research_only"
    assert report["summary"]["failed_source_check_count"] == 0
    assert report["summary"]["upstream_blocker_count"] == 0
    assert report["summary"]["manual_approval_recorded"] is False
    assert report["summary"]["operator_paper_intake_envelope_recorded"] is False
    assert report["manual_gate"]["approved_initial_principal_usdt"] == 0.0
    assert "operator_paper_intake_envelope_missing" in report["blockers"]
    assert "manual_approval_missing" in report["blockers"]
    assert "micro_live_initial_principal_not_approved" in report["blockers"]
    assert "micro_live_order_notional_not_approved" in report["blockers"]
    assert "micro_live_leverage_not_approved" in report["blockers"]
    assert "micro_live_daily_order_limit_not_approved" in report["blockers"]
    assert report["micro_live_envelope"]["automatic_live_unlock_allowed"] is False
    assert report["gate"]["strategy_skeleton_generated"] is False
    assert report["guardrails"]["broker_access_allowed"] is False


def test_micro_live_preflight_loads_redacted_operator_paper_intake_envelope_without_unlocking(
    tmp_path: Path,
) -> None:
    paths = _write_inputs(tmp_path, blocked=False)
    paths["operator_envelope"] = _write_operator_envelope(tmp_path)

    report = _build(tmp_path, paths)

    assert report["summary"]["operator_paper_intake_envelope_recorded"] is True
    assert report["manual_gate"]["operator_paper_intake_envelope_recorded"] is True
    assert report["manual_gate"]["approved_initial_principal_usdt"] == 100.0
    assert report["manual_gate"]["approved_max_order_notional_usdt"] == 100.0
    assert report["manual_gate"]["approved_max_leverage"] == 10.0
    assert report["manual_gate"]["approved_max_daily_orders"] == 3
    assert report["operator_paper_intake_envelope"]["status"] == "recorded_redacted"
    assert "operator_paper_intake_envelope_missing" not in report["blockers"]
    assert "micro_live_initial_principal_not_approved" not in report["blockers"]
    assert "micro_live_order_notional_not_approved" not in report["blockers"]
    assert "micro_live_leverage_not_approved" not in report["blockers"]
    assert "micro_live_daily_order_limit_not_approved" not in report["blockers"]
    assert "manual_approval_missing" in report["blockers"]
    assert report["policy_state"]["paper_order_intake_allowed"] is False
    assert report["policy_state"]["live_unlock_allowed"] is False
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["paper_order_intake_allowed"] is False


def test_micro_live_preflight_detects_any_upstream_order_or_live_true_flag(tmp_path: Path) -> None:
    paths = _write_inputs(tmp_path, blocked=False)
    readiness = json.loads(paths["strategy_promotion_readiness"].read_text(encoding="utf-8"))
    readiness["gate"]["live_unlock_allowed"] = True
    readiness["guardrails"]["order_endpoint_used"] = True
    paths["strategy_promotion_readiness"].write_text(json.dumps(readiness), encoding="utf-8")

    report = _build(tmp_path, paths)

    assert report["summary"]["true_safety_flag_count"] == 2
    assert "strategy_promotion_readiness:true_safety_flag:gate.live_unlock_allowed" in report["blockers"]
    assert "strategy_promotion_readiness:true_safety_flag:guardrails.order_endpoint_used" in report["blockers"]
    assert report["policy_state"]["fail_closed"] is True
    assert report["policy_state"]["micro_live_allowed"] is False


def test_micro_live_preflight_filters_dashboard_self_reference_blocker(tmp_path: Path) -> None:
    paths = _write_inputs(tmp_path, blocked=False)
    dashboard = json.loads(paths["gate_dashboard"].read_text(encoding="utf-8"))
    dashboard["status"] = "blocked"
    dashboard["blockers"] = ["btc_gate_dashboard_micro_live_preflight_blocked", "external_dashboard_blocker"]
    paths["gate_dashboard"].write_text(json.dumps(dashboard), encoding="utf-8")

    report = _build(tmp_path, paths)

    assert "gate_dashboard:source_blocker:btc_gate_dashboard_micro_live_preflight_blocked" not in report["blockers"]
    assert "gate_dashboard:source_blocker:external_dashboard_blocker" in report["blockers"]
    gate_row = next(row for row in report["source_matrix"] if row["source_id"] == "gate_dashboard")
    assert gate_row["blocker_count"] == 1
    assert gate_row["ignored_self_reference_blocker_count"] == 1


def test_micro_live_preflight_writes_fail_closed_safety_status(tmp_path: Path) -> None:
    paths = _write_inputs(tmp_path, blocked=True)
    _build(tmp_path, paths)

    safety = json.loads((tmp_path / "out" / "paper_live_safety_status.json").read_text(encoding="utf-8"))
    assert safety["research_only"] is True
    assert safety["micro_live_preflight_only"] is True
    assert safety["paper_queue_write_allowed"] is False
    assert safety["paper_candidate_created"] is False
    assert safety["paper_order_intake_allowed"] is False
    assert safety["position_increase_allowed"] is False
    assert safety["strategy_skeleton_generated"] is False
    assert safety["micro_live_allowed"] is False
    assert safety["live_unlock_allowed"] is False
    assert safety["live_order_allowed"] is False
    assert safety["oms_access_allowed"] is False
    assert safety["broker_access_allowed"] is False
    assert safety["private_endpoint_used"] is False
    assert safety["order_endpoint_used"] is False
    assert safety["real_order_submitted"] is False


def _build(tmp_path: Path, paths: dict[str, Path]) -> dict[str, object]:
    return build_btc_micro_live_preflight(
        output_dir=tmp_path / "out",
        observe_only_health_report_path=paths["observe_only_health"],
        strategy_promotion_readiness_report_path=paths["strategy_promotion_readiness"],
        kill_switch_status_report_path=paths["paper_live_kill_switch_status"],
        exchange_runtime_gap_report_path=paths["exchange_runtime_gap"],
        paper_runtime_replay_report_path=paths["paper_runtime_replay"],
        paper_runtime_reconciliation_report_path=paths["paper_runtime_reconciliation"],
        paper_exchange_rule_preflight_report_path=paths["paper_exchange_rule_preflight"],
        paper_risk_circuit_breaker_drill_report_path=paths["paper_risk_circuit_breaker_drill"],
        perpetual_execution_evidence_report_path=paths["perpetual_execution_evidence"],
        gate_dashboard_report_path=paths["gate_dashboard"],
        manual_paper_review_approval_report_path=paths["manual_paper_review_approval"],
        operator_paper_intake_envelope_path=paths.get("operator_envelope", tmp_path / "missing_operator_envelope.json"),
        generated_at_utc=TS,
    )


def _write_inputs(tmp_path: Path, *, blocked: bool) -> dict[str, Path]:
    payloads = _clean_payloads()
    if blocked:
        payloads["observe_only_health"]["status"] = "blocked_research_only"
        payloads["observe_only_health"]["decision"] = "btc_observe_only_health_blocked_collect_more_days_no_paper_no_live"
        payloads["observe_only_health"]["blockers"] = ["long_short_donchian_top5:forward_observation_under_60d"]
        payloads["observe_only_health"]["summary"]["all_lines_target_60d_complete"] = False
        payloads["observe_only_health"]["summary"]["all_lines_minimum_30d_complete"] = False
        payloads["strategy_promotion_readiness"]["status"] = "blocked_research_only"
        payloads["strategy_promotion_readiness"]["decision"] = "btc_strategy_promotion_readiness_blocked_no_paper_no_live"
        payloads["strategy_promotion_readiness"]["blockers"] = ["observe_only_under_60d"]
        payloads["strategy_promotion_readiness"]["summary"]["ready_for_paper_count"] = 0
        payloads["paper_live_kill_switch_status"]["status"] = "fail_closed_research_only"
        payloads["paper_live_kill_switch_status"]["decision"] = "btc_paper_live_kill_switch_engaged_fail_closed_no_paper_no_live"
        payloads["paper_live_kill_switch_status"]["blockers"] = ["manual_approval_missing"]
        payloads["paper_live_kill_switch_status"]["policy_state"]["kill_switch_engaged"] = True
        payloads["exchange_runtime_gap"]["status"] = "incomplete_research_only"
        payloads["exchange_runtime_gap"]["blockers"] = ["runtime_gap_missing"]
        payloads["paper_runtime_replay"]["status"] = "incomplete_research_only"
        payloads["paper_runtime_replay"]["decision"] = "perpetual_paper_runtime_replay_incomplete_fail_closed_no_paper_no_live"
        payloads["paper_runtime_replay"]["blockers"] = ["paper_runtime_no_fills"]
        payloads["paper_runtime_replay"]["summary"]["paper_runtime_replay_ready"] = False
        payloads["paper_runtime_replay"]["summary"]["simulated_fill_count"] = 0
        payloads["paper_runtime_replay"]["summary"]["current_flat_heartbeat_healthy"] = True
        payloads["paper_runtime_replay"]["summary"]["trade_execution_evidence_available"] = False
        payloads["paper_runtime_replay"]["summary"][
            "trade_execution_evidence_pending_reason"
        ] = "waiting_for_current_gate_eligible_non_flat_fill"
        payloads["paper_runtime_replay"]["summary"][
            "paper_runtime_health_status"
        ] = "current_flat_heartbeat_healthy_waiting_for_trade_sample"
        payloads["paper_exchange_rule_preflight"]["status"] = "incomplete_research_only"
        payloads["paper_exchange_rule_preflight"]["blockers"] = ["account_mode_unverified"]
        payloads["paper_exchange_rule_preflight"]["summary"]["current_order_count"] = 0
        payloads["paper_exchange_rule_preflight"]["summary"]["current_flat_no_order_healthy"] = True
        payloads["paper_exchange_rule_preflight"]["summary"]["current_order_sample_available"] = False
        payloads["paper_exchange_rule_preflight"]["summary"][
            "current_order_sample_status"
        ] = "current_flat_heartbeat_waiting_for_order_sample"
        payloads["paper_exchange_rule_preflight"]["summary"][
            "current_order_sample_pending_reason"
        ] = "current_observe_only_signal_flat_waiting_for_exchange_filter_sample"
        payloads["perpetual_execution_evidence"]["status"] = "incomplete_research_only"
        payloads["perpetual_execution_evidence"]["blockers"] = ["depth_slippage_history_missing"]
        payloads["perpetual_execution_evidence"]["summary"]["fail_count"] = 1
        payloads["gate_dashboard"]["status"] = "blocked"
        payloads["gate_dashboard"]["blockers"] = ["dashboard_blocked"]

    paths = {name: tmp_path / f"{name}.json" for name in payloads}
    for name, path in paths.items():
        path.write_text(json.dumps(payloads[name], ensure_ascii=False, indent=2), encoding="utf-8")
    return paths


def _write_operator_envelope(root: Path) -> Path:
    path = root / "configs/btc/paper_runtime/operator_paper_intake_envelope.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": "btc_operator_paper_intake_envelope_v1",
                "redacted_operator_envelope": True,
                "reviewer": "operator_review_only",
                "decision_date_utc": "2026-07-01T00:00:00Z",
                "expiry_utc": "2026-07-20T00:00:00Z",
                "approval_scope": "paper_intake_envelope_review_only_no_auto_paper_no_live",
                "approved_initial_principal_usdt": 100.0,
                "approved_max_order_notional_usdt": 100.0,
                "approved_max_leverage": 10.0,
                "approved_max_daily_orders": 3,
                "paper_queue_write_allowed": False,
                "paper_order_intake_allowed": False,
                "live_unlock_allowed": False,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return path


def _clean_payloads() -> dict[str, dict[str, object]]:
    gate = {
        "paper_queue_write_allowed": False,
        "paper_candidate_created": False,
        "paper_order_intake_allowed": False,
        "position_increase_allowed": False,
        "strategy_skeleton_generated": False,
        "micro_live_allowed": False,
        "live_unlock_allowed": False,
        "live_order_allowed": False,
        "oms_access_allowed": False,
        "broker_access_allowed": False,
    }
    guardrails = {
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "real_order_submitted": False,
        "paper_queue_write_allowed": False,
        "paper_candidate_created": False,
        "paper_order_intake_allowed": False,
        "position_increase_allowed": False,
        "micro_live_allowed": False,
        "live_unlock_allowed": False,
        "live_order_allowed": False,
        "oms_access_allowed": False,
        "broker_access_allowed": False,
    }
    clean = {
        "status": "complete_research_only",
        "decision": "research_only_no_auto_paper_no_live",
        "blockers": [],
        "gate": copy.deepcopy(gate),
        "guardrails": copy.deepcopy(guardrails),
    }
    return {
        "observe_only_health": {
            **copy.deepcopy(clean),
            "summary": {
                "all_lines_target_60d_complete": True,
                "all_lines_minimum_30d_complete": True,
                "safety_violation_count": 0,
            },
        },
        "strategy_promotion_readiness": {
            **copy.deepcopy(clean),
            "summary": {"ready_for_paper_count": 1},
        },
        "paper_live_kill_switch_status": {
            **copy.deepcopy(clean),
            "policy_state": {
                "kill_switch_engaged": False,
                "paper_order_intake_allowed": False,
                "micro_live_allowed": False,
            },
        },
        "exchange_runtime_gap": copy.deepcopy(clean),
        "paper_runtime_replay": {
            **copy.deepcopy(clean),
            "summary": {
                "paper_runtime_replay_ready": True,
                "simulated_fill_count": 12,
                "current_flat_heartbeat_healthy": False,
                "trade_execution_evidence_available": True,
                "trade_execution_evidence_pending_reason": None,
                "paper_runtime_health_status": "trade_execution_sample_present",
            },
        },
        "paper_runtime_reconciliation": {
            **copy.deepcopy(clean),
            "summary": {"paper_runtime_reconciliation_passed": True, "violation_count": 0},
        },
        "paper_exchange_rule_preflight": {
            **copy.deepcopy(clean),
            "summary": {
                "current_order_count": 12,
                "current_flat_no_order_healthy": False,
                "current_order_sample_available": True,
                "current_order_sample_status": "current_order_sample_present",
                "current_order_sample_pending_reason": None,
                "order_filter_violation_count": 0,
                "quantity_lot_violation_count": 0,
            },
        },
        "paper_risk_circuit_breaker_drill": {
            **copy.deepcopy(clean),
            "summary": {"unexpected_allow_count": 0},
        },
        "perpetual_execution_evidence": {
            **copy.deepcopy(clean),
            "summary": {"fail_count": 0},
        },
        "gate_dashboard": {
            **copy.deepcopy(clean),
            "status": "pass",
            "decision": "gate_dashboard_pass_research_only",
        },
        "manual_paper_review_approval": {
            **copy.deepcopy(clean),
            "manual_approval_recorded": False,
            "manual_review_missing_cleared": False,
            "paper_queue_write_allowed": False,
            "paper_order_intake_allowed": False,
            "live_unlock_allowed": False,
            "reviewed_packet": {"sha256": ""},
        },
    }
