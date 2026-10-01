from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT_PATH = Path("scripts/check_btc_promotion_gate_root_cause_ci.py")


def _load_module():
    spec = importlib.util.spec_from_file_location("btc_promotion_gate_root_cause_ci", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_ci_payload_is_root_cause_first_and_hides_raw_blockers_by_default(tmp_path: Path) -> None:
    module = _load_module()
    report = _blocked_report()

    payload = module.build_ci_payload(report, report_path=tmp_path / "gate.json")

    assert payload["schema_version"] == "btc_promotion_gate_root_cause_ci_v1"
    assert payload["ci_passed"] is False
    assert module.exit_code_for_payload(payload) == 1
    assert payload["root_cause_task_queue"]["dashboard_should_show_root_causes_only"] is True
    assert payload["root_cause_task_queue"]["data_wait_items"][0]["root_cause_id"] == "data_wait"
    assert payload["root_cause_task_queue"]["data_wait_items"][0]["source_reports"] == [
        "artifacts/btc_perpetual_gate_objective_status/latest/btc_perpetual_gate_objective_status_report.json"
    ]
    assert payload["root_cause_task_queue"]["data_wait_items"][0]["next_command"] == "wait_for_depth_then_rebuild"
    assert payload["root_causes"][0]["root_cause_id"] == "data_wait"
    assert payload["root_causes"][0]["blocker_examples"] == ["depth_missing", "gate_fill_count_zero"]
    assert payload["raw_blocker_drilldown"]["raw_blocker_count"] == 4
    assert payload["raw_blocker_drilldown"]["raw_blockers_hidden_by_default"] is True
    assert len(payload["raw_blocker_drilldown"]["sample"]) == 3
    assert payload["gate"] == {
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
        "broker_or_order_allowed": False,
    }


def test_ci_payload_can_include_raw_blocker_samples_for_drilldown(tmp_path: Path) -> None:
    module = _load_module()

    payload = module.build_ci_payload(_blocked_report(), report_path=tmp_path / "gate.json", include_raw_blockers=True)

    assert payload["raw_blocker_drilldown"]["raw_blockers_hidden_by_default"] is False
    assert payload["raw_blocker_drilldown"]["sample"] == [
        "depth_missing",
        "gate_fill_count_zero",
        "manual_approval_missing",
        "paper_runtime_not_ready",
    ]


def test_ci_payload_passes_only_when_gate_has_no_blockers_or_safety_violations(tmp_path: Path) -> None:
    module = _load_module()
    report = {
        "status": "complete_research_only",
        "decision": "btc_promotion_gate_control_complete_research_only_no_auto_paper_no_live",
        "blockers": [],
        "safety_violation_count": 0,
        "root_cause_matrix": [],
        "root_cause_task_queue": {"schema_version": "btc_root_cause_task_queue_v1"},
    }

    payload = module.build_ci_payload(report, report_path=tmp_path / "gate.json")

    assert payload["ci_passed"] is True
    assert module.exit_code_for_payload(payload) == 0


def _blocked_report() -> dict:
    return {
        "status": "blocked_research_only",
        "decision": "btc_promotion_gate_control_blocked_no_paper_no_live",
        "generated_at_utc": "2026-07-06T00:00:00+00:00",
        "aggregation_batch_id": "btc_gate_20260706T000000Z",
        "safety_violation_count": 0,
        "blockers": [
            "depth_missing",
            "gate_fill_count_zero",
            "manual_approval_missing",
            "paper_runtime_not_ready",
        ],
        "root_cause_summary": {
            "raw_blocker_count": 4,
            "root_cause_count": 3,
            "dominant_root_cause_id": "data_wait",
        },
        "root_cause_task_queue": {
            "schema_version": "btc_root_cause_task_queue_v1",
            "dashboard_should_show_root_causes_only": True,
            "data_wait_items": [
                {
                    "root_cause_id": "data_wait",
                    "label_cn": "数据等待",
                    "owner": "data-runtime automation",
                    "source_reports": [
                        "artifacts/btc_perpetual_gate_objective_status/latest/btc_perpetual_gate_objective_status_report.json"
                    ],
                    "next_command": "wait_for_depth_then_rebuild",
                    "raw_blocker_count": 2,
                    "affected_gates": ["data_gate"],
                    "acceptance_criteria": ["depth coverage passes"],
                }
            ],
            "immediate_development_items": [
                {
                    "root_cause_id": "runtime_not_connected",
                    "label_cn": "runtime 未接通",
                    "owner": "runtime/replay engineer",
                    "source_reports": [
                        "artifacts/btc_exchange_runtime/latest/btc_exchange_runtime_replay_gap_report.json"
                    ],
                    "next_command": "py scripts/build_btc_gate_aggregation_chain.py",
                    "raw_blocker_count": 1,
                    "affected_gates": ["execution_gate"],
                    "acceptance_criteria": ["runtime sample captured"],
                }
            ],
        },
        "root_cause_matrix": [
            {
                "root_cause_id": "data_wait",
                "label_cn": "数据等待",
                "raw_blocker_count": 2,
                "unique_blocker_count": 2,
                "affected_gates": ["data_gate"],
                "owner": "data-runtime automation",
                "source_reports": [
                    "artifacts/btc_perpetual_gate_objective_status/latest/btc_perpetual_gate_objective_status_report.json"
                ],
                "next_command": "wait_for_depth_then_rebuild",
                "acceptance_criteria": ["depth coverage passes"],
                "blocker_examples": ["depth_missing", "gate_fill_count_zero"],
            }
        ],
        "required_rebuild_reports": [
            {
                "source_id": "exchange_runtime_gap",
                "rebuild_command": "py scripts/build_btc_exchange_runtime_replay_gap_report.py",
            }
        ],
    }
