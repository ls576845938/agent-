from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from quant_crypto.research.btc_strategy_promotion_readiness_review import build_btc_strategy_promotion_readiness_review


TS = datetime(2026, 7, 1, 8, 0, tzinfo=timezone.utc)


def test_btc_strategy_promotion_readiness_blocks_non_data_gates(tmp_path: Path) -> None:
    paths = _write_inputs(tmp_path)
    report = build_btc_strategy_promotion_readiness_review(
        output_dir=tmp_path / "out",
        generated_at_utc=TS,
        bar_replay_report_path=paths["bar_replay"],
        leakage_audit_report_path=paths["leakage"],
        long_short_observer_report_path=paths["long_short"],
        attack_observer_report_path=paths["attack"],
        high_yield_followup_report_path=paths["high_yield"],
        observe_only_health_report_path=paths["observe_health"],
        perp_execution_evidence_report_path=paths["perp"],
        paper_runtime_replay_report_path=paths["paper_runtime"],
        exchange_runtime_gap_report_path=paths["exchange_gap"],
        gate_dashboard_report_path=paths["gate_dashboard"],
    )

    assert report["status"] == "blocked_research_only"
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["live_unlock_allowed"] is False
    assert report["summary"]["strategy_line_count"] == 3
    assert report["summary"]["ready_for_paper_count"] == 0
    assert report["summary"]["observe_only_health_status"] == "blocked_research_only"
    assert report["summary"]["observe_only_health_blocker_count"] == 2
    assert report["summary"]["paper_runtime_health_status"] == "current_flat_heartbeat_healthy_waiting_for_trade_sample"
    assert report["summary"]["paper_runtime_current_flat_heartbeat_healthy"] is True
    assert report["summary"]["paper_runtime_trade_execution_evidence_available"] is False
    assert (
        report["summary"]["paper_runtime_trade_execution_evidence_pending_reason"]
        == "waiting_for_current_gate_eligible_non_flat_fill"
    )

    by_line = {row["strategy_line"]: row for row in report["matrix"]}
    assert set(by_line) == {
        "long_short_donchian_top5",
        "high_octane_attack_sleeve_v2",
        "high_yield_donchian_v2",
    }
    assert by_line["long_short_donchian_top5"]["holdout_lock_enforced"] is True
    assert by_line["long_short_donchian_top5"]["observation_days"] == 2
    assert by_line["long_short_donchian_top5"]["minimum_30d_complete"] is False
    assert by_line["long_short_donchian_top5"]["paper_runtime_current_flat_heartbeat_healthy"] is True
    assert "long_short_top5_forward_observation_under_30d" in by_line["long_short_donchian_top5"]["line_blockers"]

    assert by_line["high_octane_attack_sleeve_v2"]["best_margin_over_40pct_threshold"] == 0.011869
    assert "high_octane_40pct_survival_threshold_boundary_margin_too_small" in by_line["high_octane_attack_sleeve_v2"]["line_blockers"]
    assert "high_octane_parameter_mining_overfit_risk" in by_line["high_octane_attack_sleeve_v2"]["line_blockers"]

    assert by_line["high_yield_donchian_v2"]["bar_replay_status"] == "covered_with_model_boundary_warning"
    assert by_line["high_yield_donchian_v2"]["observation_days"] == 2
    assert "high_yield_v2_not_in_current_bar_replay_visibility_audit" not in by_line["high_yield_donchian_v2"]["line_blockers"]
    assert "high_yield_v2_bar_replay_model_boundary_requires_execution_replay" in by_line["high_yield_donchian_v2"]["line_blockers"]
    assert "high_yield_v2_loss_control_v3_retained_count_zero" in by_line["high_yield_donchian_v2"]["line_blockers"]

    assert "perp_execution:btc_perp_exec_depth_aware_slippage_history_verified" in report["global_gate"]["blockers"]
    assert "observe_only_health:long_short_donchian_top5:forward_observation_under_30d" in report["blockers"]
    assert any("paper_runtime:btc_perpetual_paper_runtime_replay_no_simulated_fills" in item for item in report["blockers"])
    assert (tmp_path / "out" / "btc_strategy_promotion_readiness_report.json").exists()
    assert (tmp_path / "out" / "btc_strategy_promotion_readiness_matrix.csv").exists()
    assert (tmp_path / "out" / "btc_strategy_promotion_readiness_summary_cn.md").exists()
    assert (tmp_path / "out" / "paper_live_safety_status.json").exists()


def test_btc_strategy_promotion_readiness_safety_status_is_fail_closed(tmp_path: Path) -> None:
    paths = _write_inputs(tmp_path)
    build_btc_strategy_promotion_readiness_review(
        output_dir=tmp_path / "out",
        generated_at_utc=TS,
        bar_replay_report_path=paths["bar_replay"],
        leakage_audit_report_path=paths["leakage"],
        long_short_observer_report_path=paths["long_short"],
        attack_observer_report_path=paths["attack"],
        high_yield_followup_report_path=paths["high_yield"],
        observe_only_health_report_path=paths["observe_health"],
        perp_execution_evidence_report_path=paths["perp"],
        paper_runtime_replay_report_path=paths["paper_runtime"],
        exchange_runtime_gap_report_path=paths["exchange_gap"],
        gate_dashboard_report_path=paths["gate_dashboard"],
    )

    safety = json.loads((tmp_path / "out" / "paper_live_safety_status.json").read_text(encoding="utf-8"))
    assert safety["paper_queue_write_allowed"] is False
    assert safety["paper_candidate_created"] is False
    assert safety["strategy_skeleton_generated"] is False
    assert safety["broker_access_allowed"] is False
    assert safety["oms_access_allowed"] is False
    assert safety["order_endpoint_used"] is False
    assert safety["private_endpoint_used"] is False
    assert safety["real_order_submitted"] is False
    assert safety["live_order_allowed"] is False
    assert safety["live_unlock_allowed"] is False


def _write_inputs(tmp_path: Path) -> dict[str, Path]:
    high_yield_ledger = tmp_path / "high_yield_observations.jsonl"
    high_yield_ledger.write_text(
        "\n".join(
            [
                json.dumps({"decision_time": "2026-06-28T23:59:59.999000+00:00"}),
                json.dumps({"decision_time": "2026-07-01T03:59:59.999000+00:00"}),
            ]
        ),
        encoding="utf-8",
    )
    paths = {
        "bar_replay": tmp_path / "bar_replay.json",
        "leakage": tmp_path / "leakage.json",
        "long_short": tmp_path / "long_short.json",
        "attack": tmp_path / "attack.json",
        "high_yield": tmp_path / "high_yield.json",
        "observe_health": tmp_path / "observe_health.json",
        "perp": tmp_path / "perp.json",
        "paper_runtime": tmp_path / "paper_runtime.json",
        "exchange_gap": tmp_path / "exchange_gap.json",
        "gate_dashboard": tmp_path / "gate_dashboard.json",
    }
    _write(
        paths["bar_replay"],
        {
            "status": "complete_research_only",
            "summary": {"check_fail_count": 0},
            "long_short_top5_bar_replay": {
                "current_shift_violation_count": 0,
                "derivatives_available_time_violation_count": 0,
                "verdict": "bar_replay_no_shift_or_visibility_violations",
            },
            "high_octane_v2_visibility_replay": {"verdict": "visibility_replay_completed_but_execution_replay_required_before_paper"},
            "high_yield_v2_bar_replay": {
                "row_count": 100,
                "model_boundary_row_count": 100,
                "prior_exposure_return_violation_count": 5,
                "derivatives_available_time_violation_count": 0,
                "verdict": "bar_replay_completed_but_stateful_same_bar_execution_proxy_requires_mark_index_paper_runtime_replay",
            },
        },
    )
    _write(
        paths["leakage"],
        {
            "status": "complete_research_only",
            "summary": {"check_fail_count": 0, "check_warn_count": 5},
            "long_short_top5_audit": {"overfit_verdict": "no_direct_leakage_detected_but_concentration_requires_forward_confirmation"},
            "high_octane_v2_audit": {
                "overfit_verdict": "high_overfit_and_threshold_boundary_risk_research_only",
                "best_margin_over_40pct_threshold": 0.011869,
            },
        },
    )
    _write(paths["long_short"], _observer(days=2, count=10))
    _write(paths["attack"], _observer(days=3, count=2))
    _write(
        paths["high_yield"],
        {
            "status": "complete_research_only",
            "step_1_daily_observation_automation": {
                "observation_count": 2,
                "observation_ledger_path": str(high_yield_ledger),
                "holdout_lock": _lock(),
            },
            "step_2_loss_control_v3_narrow_experiment": {"retained_count": 0},
            "gate": {"paper_queue_write_allowed": False, "live_unlock_allowed": False},
        },
    )
    _write(
        paths["observe_health"],
        {
            "status": "blocked_research_only",
            "blockers": [
                "long_short_donchian_top5:forward_observation_under_30d",
                "high_octane_attack_sleeve_v2:forward_observation_under_30d",
            ],
            "summary": {
                "line_count": 3,
                "minimum_30d_complete_count": 0,
                "target_60d_complete_count": 0,
                "paper_queue_write_allowed": False,
                "live_unlock_allowed": False,
            },
            "gate": {"paper_queue_write_allowed": False, "live_unlock_allowed": False},
            "guardrails": {"order_endpoint_used": False, "private_endpoint_used": False, "real_order_submitted": False},
        },
    )
    _write(
        paths["perp"],
        {
            "status": "incomplete_research_only",
            "blockers": [
                "btc_perp_exec_perp_data_covers_latest_strategy_decision",
                "btc_perp_exec_depth_aware_slippage_history_verified",
            ],
        },
    )
    _write(
        paths["paper_runtime"],
        {
            "status": "incomplete_research_only",
            "blockers": ["btc_perpetual_paper_runtime_replay_no_simulated_fills"],
            "summary": {
                "paper_runtime_replay_ready": False,
                "simulated_fill_count": 0,
                "current_flat_heartbeat_healthy": True,
                "trade_execution_evidence_available": False,
                "trade_execution_evidence_pending_reason": "waiting_for_current_gate_eligible_non_flat_fill",
                "paper_runtime_health_status": "current_flat_heartbeat_healthy_waiting_for_trade_sample",
                "non_blocking_pending_conditions": [
                    "waiting_for_current_gate_eligible_non_flat_fill"
                ],
            },
        },
    )
    _write(paths["exchange_gap"], {"status": "incomplete_research_only", "blockers": ["btc_runtime_contract_still_simulated_contract_probe"]})
    _write(paths["gate_dashboard"], {"status": "blocked", "blockers": ["btc_gate_dashboard_artifact_blocker:perpetual_execution_evidence:x"]})
    return paths


def _observer(*, days: int, count: int) -> dict[str, object]:
    return {
        "status": "complete_research_only",
        "observation_progress": {"observation_days": days, "observation_count": count},
        "holdout_lock": _lock(),
        "gate": {"paper_queue_write_allowed": False, "live_unlock_allowed": False},
    }


def _lock() -> dict[str, object]:
    return {
        "lock_config_present": True,
        "observe_only_violation_count": 0,
        "selection_use_blocked_by_lock": True,
    }


def _write(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
