from __future__ import annotations

from datetime import datetime, timezone

from scripts.check_btc_runtime_gate_local_ci import build_local_ci_report


def test_runtime_gate_local_ci_allows_expected_blocked_gate_without_unlocking() -> None:
    report = build_local_ci_report(
        generated_at_utc=datetime(2026, 7, 6, tzinfo=timezone.utc),
        command_rows=[{"command": "py scripts/build_btc_gate_aggregation_chain.py", "returncode": 0}],
        promotion={
            "status": "blocked_research_only",
            "blockers": ["btc_runtime_ready_waiting_non_flat_sample"],
            "safety_violation_count": 0,
            "artifact_freshness": {"status": "pass"},
            "root_cause_summary": {"root_cause_count": 4},
            "root_cause_matrix": [
                {"root_cause_id": "runtime_ready_waiting_non_flat_sample", "label_cn": "runtime 已就绪，等待非空样本"}
            ],
            "root_cause_task_queue": {
                "dashboard_should_show_root_causes_only": True,
                "immediate_development_items": [],
                "data_wait_items": [
                    {"root_cause_id": "runtime_ready_waiting_non_flat_sample", "label_cn": "runtime 已就绪，等待非空样本"}
                ],
            },
            "safety_violations": [],
        },
        runtime_gap={
            "evidence_layers": {
                "fixture_capability": {"status": "passed", "passed": True, "paper_gate_eligible": False},
                "historical_drill": {"status": "passed", "passed": True, "paper_gate_eligible": False},
                "current_observe_only_gate_evidence": {
                    "status": "pending",
                    "passed": False,
                    "paper_gate_eligible": False,
                    "pending_reason": "waiting_for_current_gate_eligible_non_flat_fill",
                },
            }
        },
        order_audit={"finding_count": 0},
        strict_promotion=False,
    )

    assert report["ci_passed"] is True
    assert report["promotion_gate_blocked"] is True
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["live_unlock_allowed"] is False
    assert report["runtime_evidence_layers"]["fixture_or_drill_cannot_satisfy_paper_gate"] is True


def test_runtime_gate_local_ci_strict_promotion_fails_when_gate_blocked() -> None:
    report = build_local_ci_report(
        generated_at_utc=datetime(2026, 7, 6, tzinfo=timezone.utc),
        command_rows=[{"command": "py scripts/build_btc_gate_aggregation_chain.py", "returncode": 0}],
        promotion={
            "status": "blocked_research_only",
            "blockers": ["runtime_not_connected"],
            "safety_violation_count": 0,
            "artifact_freshness": {"status": "pass"},
            "safety_violations": [],
        },
        runtime_gap={
            "evidence_layers": {
                "fixture_capability": {"status": "passed", "passed": True, "paper_gate_eligible": False},
                "historical_drill": {"status": "passed", "passed": True, "paper_gate_eligible": False},
                "current_observe_only_gate_evidence": {"status": "pending", "passed": False, "paper_gate_eligible": False},
            }
        },
        order_audit={"finding_count": 0},
        strict_promotion=True,
    )

    assert report["ci_passed"] is False
    assert report["strict_promotion"] is True
    assert report["gate"]["broker_or_order_allowed"] is False
