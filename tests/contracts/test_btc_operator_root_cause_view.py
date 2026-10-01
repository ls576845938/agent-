from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from quant_crypto.research.btc_operator_root_cause_view import build_btc_operator_root_cause_view


TS = "2026-07-06T00:00:00+00:00"


def test_operator_root_cause_view_is_root_cause_only_and_manual_review_not_authorization(tmp_path: Path) -> None:
    _write_sources(tmp_path, manual_current=False)

    report = build_btc_operator_root_cause_view(
        repo_root=tmp_path,
        output_dir=Path("out"),
        generated_at_utc=datetime(2026, 7, 6, 1, tzinfo=timezone.utc),
    )

    assert report["schema_version"] == "btc_operator_root_cause_view_v1"
    assert report["status"] == "blocked_research_only"
    assert report["root_cause_task_queue"]["dashboard_should_show_root_causes_only"] is True
    assert report["raw_blocker_drilldown"]["raw_blockers_hidden_by_default"] is True
    assert report["raw_blocker_drilldown"]["raw_blocker_sample"] == []
    assert report["raw_blocker_drilldown"]["raw_blocker_count"] == 4
    assert report["unique_next_action"]["action_id"] == "manual_review_sign_current_packet"
    assert report["unique_next_action"]["owner"] == "operator/manual reviewer"
    assert report["manual_review"]["status"] == "missing_or_invalid_review_only"
    assert report["manual_review"]["approval_is_authorization"] is False
    assert report["paper_live_forbidden"]["approval_is_authorization"] is False
    assert report["paper_live_forbidden"]["fixture_or_drill_can_clear_paper_gate"] is False
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["live_unlock_allowed"] is False
    assert report["gate"]["broker_or_order_allowed"] is False
    assert "禁止写 paper 队列" in report["forbidden_actions"]
    assert (tmp_path / "out/btc_operator_root_cause_view_report.json").exists()
    assert (tmp_path / "out/btc_operator_root_cause_view_summary_cn.md").exists()
    assert (tmp_path / "out/paper_live_safety_status.json").exists()


def test_operator_view_routes_data_wait_as_wait_only_after_manual_review_is_current(tmp_path: Path) -> None:
    _write_sources(tmp_path, manual_current=True, immediate_items=[])

    report = build_btc_operator_root_cause_view(
        repo_root=tmp_path,
        output_dir=Path("out"),
        generated_at_utc=datetime(2026, 7, 6, 1, tzinfo=timezone.utc),
    )

    assert report["manual_review"]["status"] == "recorded_current_review_only"
    assert report["unique_next_action"]["category"] == "wait_only"
    assert report["unique_next_action"]["action_id"] == "data_wait"
    assert report["unique_next_action"]["owner"] == "data-runtime automation"
    assert "数据等待不是程序员手动修代码任务" in report["unique_next_action"]["why"]
    assert report["paper_live_forbidden"]["approval_is_authorization"] is False
    assert "manual_review_recorded_does_not_authorize_paper_or_live" in report["warnings"]


def test_operator_view_explains_strategy_forward_wait_without_calling_it_data_collection(tmp_path: Path) -> None:
    _write_sources(
        tmp_path,
        manual_current=True,
        immediate_items=[],
        data_wait_items=[
            {
                "root_cause_id": "strategy_overfit_or_forward_gap",
                "label_cn": "策略 forward / 过拟合治理等待",
                "owner": "strategy governance",
                "source_reports": ["artifacts/btc_strategy_leakage_overfit_audit/latest/report.json"],
                "next_command": "continue_observe_only_forward_window_no_new_strategy_mining",
                "raw_blocker_count": 2,
                "affected_gates": ["strategy_gate", "leakage_overfit_gate"],
                "acceptance_criteria": ["30/60 day observe-only window reaches required minimum"],
            }
        ],
    )

    report = build_btc_operator_root_cause_view(
        repo_root=tmp_path,
        output_dir=Path("out"),
        generated_at_utc=datetime(2026, 7, 6, 1, tzinfo=timezone.utc),
    )

    assert report["unique_next_action"]["action_id"] == "strategy_overfit_or_forward_gap"
    assert report["unique_next_action"]["category"] == "wait_only"
    assert "observe-only" in report["unique_next_action"]["why"]
    assert "数据等待" not in report["unique_next_action"]["why"]
    assert report["gate"]["paper_queue_write_allowed"] is False


def test_operator_view_reclassifies_runtime_not_connected_when_flat_heartbeat_is_healthy(tmp_path: Path) -> None:
    _write_sources(
        tmp_path,
        manual_current=True,
        immediate_items=[
            {
                "root_cause_id": "runtime_not_connected",
                "label_cn": "runtime 未接通",
                "owner": "runtime/replay engineer",
                "source_reports": ["artifacts/btc_exchange_runtime/latest/replay.json"],
                "next_command": "py scripts/build_btc_gate_aggregation_chain.py",
                "raw_blocker_count": 32,
                "affected_gates": ["execution_gate"],
                "acceptance_criteria": ["current non-flat sample captured"],
            }
        ],
    )

    report = build_btc_operator_root_cause_view(
        repo_root=tmp_path,
        output_dir=Path("out"),
        generated_at_utc=datetime(2026, 7, 6, 1, tzinfo=timezone.utc),
    )

    immediate = report["root_cause_task_queue"]["immediate_development_items"]
    assert immediate == []
    assert report["unique_next_action"]["category"] == "wait_only"
    assert report["unique_next_action"]["action_id"] == "data_wait"
    assert "runtime_not_connected_reclassified_to_waiting_non_flat_sample" in report["root_cause_task_queue"][
        "operator_view_normalizations"
    ]


def test_operator_view_records_source_freshness_and_hashes_and_flags_missing_generated_at(tmp_path: Path) -> None:
    _write_sources(tmp_path, manual_current=True)
    promotion_path = tmp_path / "artifacts/btc_promotion_gate_control/latest/btc_promotion_gate_control_report.json"
    promotion = json.loads(promotion_path.read_text(encoding="utf-8"))
    promotion.pop("generated_at_utc", None)
    promotion.pop("generated_at", None)
    _write_json(promotion_path, promotion)

    report = build_btc_operator_root_cause_view(
        repo_root=tmp_path,
        output_dir=Path("out"),
        generated_at_utc=datetime(2026, 7, 6, 1, tzinfo=timezone.utc),
    )

    assert set(report["source_hashes"]) == {
        "gate_dashboard",
        "promotion_gate_control",
        "manual_approval",
        "kill_switch",
        "runtime_replay",
    }
    assert "promotion_gate_control:generated_at_missing" in report["source_freshness"]["stale_source_ids"]
    assert "btc_operator_root_cause_view_source_stale:promotion_gate_control:generated_at_missing" in report["blockers"]


def _write_sources(
    tmp_path: Path,
    *,
    manual_current: bool,
    immediate_items: list[dict] | None = None,
    data_wait_items: list[dict] | None = None,
) -> None:
    task_queue = {
        "schema_version": "btc_root_cause_task_queue_v1",
        "dashboard_should_show_root_causes_only": True,
        "data_wait_items": data_wait_items
        if data_wait_items is not None
        else [
            {
                "root_cause_id": "data_wait",
                "label_cn": "数据等待",
                "owner": "data-runtime automation",
                "source_reports": ["artifacts/btc_perpetual_gate_objective_status/latest/report.json"],
                "next_command": "wait_for_depth_then_rebuild",
                "raw_blocker_count": 2,
                "affected_gates": ["data_gate"],
                "acceptance_criteria": ["depth coverage passes"],
            }
        ],
        "immediate_development_items": immediate_items
        if immediate_items is not None
        else [
            {
                "root_cause_id": "runtime_ready_waiting_non_flat_sample",
                "label_cn": "等待非空样本",
                "owner": "runtime/replay engineer",
                "source_reports": ["artifacts/btc_exchange_runtime/latest/replay.json"],
                "next_command": "py scripts/build_btc_gate_aggregation_chain.py",
                "raw_blocker_count": 1,
                "affected_gates": ["execution_gate"],
                "acceptance_criteria": ["current non-flat sample captured"],
            }
        ],
    }
    promotion = {
        "status": "blocked_research_only",
        "decision": "btc_promotion_gate_control_blocked_no_paper_no_live",
        "generated_at_utc": TS,
        "blockers": ["depth_missing", "gate_fill_zero", "manual_approval_missing", "runtime_pending"],
        "root_cause_summary": {"raw_blocker_count": 4, "root_cause_count": 2, "dominant_root_cause_id": "data_wait"},
        "root_cause_task_queue": task_queue,
        "root_cause_matrix": [
            {
                "root_cause_id": "data_wait",
                "label_cn": "数据等待",
                "owner": "data-runtime automation",
                "raw_blocker_count": 2,
                "affected_gates": ["data_gate"],
                "next_command": "wait_for_depth_then_rebuild",
            }
        ],
    }
    dashboard = {
        "status": "blocked",
        "decision": "btc_gate_dashboard_blocked",
        "generated_at_utc": TS,
        "root_cause_task_queue": task_queue,
        "root_cause_summary": promotion["root_cause_summary"],
        "root_cause_matrix": promotion["root_cause_matrix"],
        "blockers": ["dashboard_blocked"],
    }
    manual = _manual_current() if manual_current else _manual_invalid()
    kill_switch = {
        "status": "blocked_research_only",
        "decision": "kill_switch_engaged",
        "generated_at_utc": TS,
        "policy_state": {"kill_switch_engaged": True, "cancel_only_mode": True},
        "blockers": ["kill_switch_engaged"],
    }
    runtime = {
        "status": "incomplete_research_only",
        "decision": "runtime_pending",
        "generated_at_utc": TS,
        "summary": {
            "current_flat_heartbeat_healthy": True,
            "trade_execution_evidence_pending_reason": "waiting_for_current_gate_eligible_non_flat_fill",
            "paper_runtime_gate_evidence": False,
        },
        "blockers": [],
    }
    _write_json(tmp_path / "artifacts/btc_gate_dashboard/latest/btc_gate_dashboard.json", dashboard)
    _write_json(
        tmp_path / "artifacts/btc_promotion_gate_control/latest/btc_promotion_gate_control_report.json",
        promotion,
    )
    _write_json(
        tmp_path / "artifacts/btc_manual_paper_review_approval/latest/btc_manual_paper_review_approval_report.json",
        manual,
    )
    _write_json(
        tmp_path / "artifacts/btc_exchange_runtime/latest/btc_paper_live_kill_switch_status_report.json",
        kill_switch,
    )
    _write_json(
        tmp_path / "artifacts/btc_exchange_runtime/latest/btc_perpetual_paper_runtime_replay_report.json",
        runtime,
    )


def _manual_current() -> dict:
    return {
        "status": "complete_research_only",
        "decision": "manual_review_recorded_current_no_paper_no_live",
        "generated_at_utc": TS,
        "manual_approval_recorded": True,
        "manual_review_missing_cleared": True,
        "blockers": [],
        "approval_record": {
            "reviewer": "reviewer-a",
            "reviewed_packet_sha256": "a" * 64,
            "reviewed_source_code_commit": "b" * 40,
            "expiry_utc": "2026-07-20T00:00:00+00:00",
        },
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
    }


def _manual_invalid() -> dict:
    payload = _manual_current()
    payload.update(
        {
            "status": "missing_or_invalid_research_only",
            "decision": "manual_review_missing_or_invalid",
            "manual_approval_recorded": False,
            "manual_review_missing_cleared": False,
            "blockers": ["btc_manual_paper_review_approval_packet_sha256_mismatch"],
        }
    )
    return payload


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
