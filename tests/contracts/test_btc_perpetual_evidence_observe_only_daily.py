from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import scripts.run_btc_perpetual_evidence_observe_only_daily as runner


def test_perpetual_evidence_daily_runner_sequences_public_evidence_and_keeps_gate_closed(
    monkeypatch,
    tmp_path: Path,
) -> None:
    calls: list[str] = []

    def fake_l2(**kwargs: Any) -> dict[str, Any]:
        calls.append("l2")
        assert kwargs["execute_network"] is True
        assert kwargs["sample_count"] == 4
        return {
            "status": "free_public_l2_depth_observation_completed_research_only",
            "decision": "continue_accumulating_free_public_l2_depth_evidence_fail_closed_no_paper_no_live",
            "evidence_snapshot": {
                "depth_snapshot_coverage": {
                    "two_sided_snapshot_count": 48,
                    "two_sided_coverage_days": 0.25,
                }
            },
            "gate": _closed_gate(),
            "blockers": ["btc_depth_aware_slippage_history_insufficient"],
        }

    def fake_liquidation(**kwargs: Any) -> dict[str, Any]:
        calls.append("liquidation")
        assert kwargs["execute_network"] is True
        return {
            "status": "complete_research_only",
            "decision": "okx_liquidation_snapshots_observe_only_diagnostic_not_gate_evidence_no_paper_no_live",
            "data": {"new_row_count": 10, "merged_row_count": 20},
            "gate_interpretation": {"liquidation_snapshot_gate_eligible": False},
            "gate": _closed_gate(),
            "blockers": ["btc_okx_liquidation_snapshot_observe_only_not_complete_1h_history"],
        }

    def fake_cost(**_kwargs: Any) -> dict[str, Any]:
        calls.append("cost")
        return {
            "status": "pass",
            "blockers": [],
            "liquidation_data": {"liquidation_snapshot_status": "diagnostic_snapshot_observe_only_not_complete_history"},
            "slippage_model": {"depth_aware_slippage_history_verified": False},
        }

    def fake_write_cost(_payload: dict[str, Any], _output_root: Path) -> str:
        calls.append("write_cost")
        return "artifacts/btc_cost_model/latest/btc_cost_model_report.json"

    def fake_paper_runtime(**_kwargs: Any) -> dict[str, Any]:
        calls.append("paper_runtime")
        return {
            "status": "incomplete_research_only",
            "decision": "perpetual_paper_runtime_replay_incomplete_fail_closed_no_paper_no_live",
            "summary": {
                "theoretical_order_count": 0,
                "simulated_fill_count": 0,
                "gate_eligible_current_capture_count": 0,
                "current_non_flat_sample_capture_status": "flat_waiting_no_false_positive",
                "current_non_flat_sample_capture_contract": {"status": "flat_waiting_no_false_positive"},
            },
            "gate": _closed_gate(),
            "blockers": ["btc_perpetual_paper_runtime_replay_no_simulated_fills"],
        }

    def fake_fill_mapping(**_kwargs: Any) -> dict[str, Any]:
        calls.append("fill_mapping")
        return {
            "status": "incomplete_research_only",
            "decision": "strategy_fill_to_okx_depth_mapping_incomplete_fail_closed_no_paper_no_live",
            "fill_mapping_state": "no_gate_eligible_fill",
            "strategy_fill_mapping_verified": False,
            "summary": {
                "gate_fill_count": 0,
                "mapped_gate_fill_count": 0,
                "gate_depth_not_visible_count": 0,
                "gate_mapping_logic_failure_count": 0,
            },
            "gate": _closed_gate(),
            "blockers": ["btc_depth_strategy_fill_mapping_no_gate_eligible_strategy_fills"],
        }

    def fake_depth_slippage(**_kwargs: Any) -> dict[str, Any]:
        calls.append("depth_slippage")
        return {
            "status": "partial_diagnostic_only",
            "decision": "depth_snapshot_positive_floor_available_history_incomplete_no_paper_no_live",
            "depth_aware_slippage_history_verified": False,
            "selected_venue_depth_evidence": {"strategy_fill_mapping_verified": False},
            "gate": _closed_gate(),
            "blockers": ["btc_depth_strategy_fill_mapping_no_gate_eligible_strategy_fills"],
        }

    def fake_runtime_gap(**_kwargs: Any) -> dict[str, Any]:
        calls.append("runtime_gap")
        return {
            "status": "incomplete_research_only",
            "decision": "runtime_replay_gap_incomplete_fail_closed_no_paper_no_live",
            "summary": {"blocker_count": 1},
            "gate": _closed_gate(),
            "blockers": ["btc_paper_runtime_replay_not_ready"],
        }

    def fake_perpetual_evidence(**_kwargs: Any) -> dict[str, Any]:
        calls.append("perpetual_evidence")
        return {
            "status": "incomplete_research_only",
            "decision": "perpetual_execution_evidence_incomplete_fail_closed_no_paper_no_live",
            "summary": {"pass_count": 19, "fail_count": 3, "blocker_count": 3},
            "gate": _closed_gate(),
            "blockers": [
                "btc_perp_exec_depth_aware_slippage_history_verified",
                "btc_perp_exec_liquidation_history_or_snapshots_available",
                "btc_perp_exec_exchange_runtime_real_or_paper_replay_ready",
            ],
        }

    def fake_dashboard(**_kwargs: Any) -> dict[str, Any]:
        calls.append("dashboard")
        return {
            "status": "blocked",
            "decision": "btc_gate_dashboard_blocked",
            "blockers": [
                "btc_gate_dashboard_artifact_blocker:perpetual_execution_evidence:btc_perp_exec_depth_aware_slippage_history_verified"
            ],
        }

    monkeypatch.setattr(runner, "run_btc_okx_l2_depth_observation_daily", fake_l2)
    monkeypatch.setattr(runner, "run_btc_okx_liquidation_snapshot_observer", fake_liquidation)
    monkeypatch.setattr(runner, "build_btc_cost_model_report", fake_cost)
    monkeypatch.setattr(runner, "write_btc_cost_model_report", fake_write_cost)
    monkeypatch.setattr(runner, "build_btc_perpetual_paper_runtime_replay_report", fake_paper_runtime)
    monkeypatch.setattr(runner, "build_btc_depth_slippage_fill_mapping_report", fake_fill_mapping)
    monkeypatch.setattr(runner, "build_btc_depth_slippage_report", fake_depth_slippage)
    monkeypatch.setattr(runner, "build_btc_exchange_runtime_replay_gap_report", fake_runtime_gap)
    monkeypatch.setattr(runner, "build_btc_perpetual_execution_evidence_pack", fake_perpetual_evidence)
    monkeypatch.setattr(runner, "build_btc_gate_dashboard_file", fake_dashboard)

    report = runner.run_btc_perpetual_evidence_observe_only_daily(
        repo_root=tmp_path,
        output_root=Path("artifacts/btc_perpetual_evidence_observe_only_daily/latest"),
        execute_network=True,
        l2_sample_count=4,
        generated_at="2026-07-01T00:00:00Z",
    )

    assert calls == [
        "l2",
        "liquidation",
        "cost",
        "write_cost",
        "paper_runtime",
        "fill_mapping",
        "depth_slippage",
        "cost",
        "write_cost",
        "runtime_gap",
        "perpetual_evidence",
        "dashboard",
    ]
    assert report["status"] == "complete_research_only"
    assert report["requested"]["free_public_sources_only"] is True
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["live_unlock_allowed"] is False
    assert report["guardrails"]["private_endpoint_used"] is False
    assert report["guardrails"]["order_endpoint_used"] is False
    assert "btc_perp_exec_depth_aware_slippage_history_verified" in report["blockers"]
    assert "btc_perp_exec_exchange_runtime_real_or_paper_replay_ready" in report["blockers"]
    assert report["evidence_snapshot"]["depth_snapshot_coverage"]["two_sided_snapshot_count"] == 48
    assert report["evidence_snapshot"]["liquidation_snapshot"]["merged_row_count"] == 20
    assert report["evidence_snapshot"]["paper_runtime_replay"]["simulated_fill_count"] == 0
    assert report["evidence_snapshot"]["paper_runtime_replay"]["current_non_flat_sample_capture_status"] == (
        "flat_waiting_no_false_positive"
    )
    assert report["evidence_snapshot"]["depth_fill_mapping"]["fill_mapping_state"] == "no_gate_eligible_fill"

    out = tmp_path / "artifacts/btc_perpetual_evidence_observe_only_daily/latest"
    assert (out / "btc_perpetual_evidence_observe_only_daily_report.json").exists()
    assert (out / "btc_perpetual_evidence_observe_only_daily_summary_cn.md").exists()
    safety = json.loads((out / "paper_live_safety_status.json").read_text(encoding="utf-8"))
    assert safety["paper_queue_write_allowed"] is False
    assert safety["live_unlock_allowed"] is False
    assert safety["broker_access_allowed"] is False


def test_perpetual_evidence_daily_runner_fails_closed_when_a_step_errors(
    monkeypatch,
    tmp_path: Path,
) -> None:
    def failing_l2(**_kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("network unavailable")

    monkeypatch.setattr(runner, "run_btc_okx_l2_depth_observation_daily", failing_l2)
    monkeypatch.setattr(runner, "run_btc_okx_liquidation_snapshot_observer", lambda **_kwargs: {"status": "dry_run", "gate": _closed_gate(), "blockers": []})
    monkeypatch.setattr(runner, "build_btc_cost_model_report", lambda **_kwargs: {"status": "pass", "blockers": []})
    monkeypatch.setattr(runner, "write_btc_cost_model_report", lambda *_args, **_kwargs: "cost.json")
    monkeypatch.setattr(runner, "build_btc_perpetual_paper_runtime_replay_report", lambda **_kwargs: {"status": "incomplete_research_only", "summary": {}, "gate": _closed_gate(), "blockers": []})
    monkeypatch.setattr(runner, "build_btc_depth_slippage_fill_mapping_report", lambda **_kwargs: {"status": "incomplete_research_only", "summary": {}, "gate": _closed_gate(), "blockers": []})
    monkeypatch.setattr(runner, "build_btc_depth_slippage_report", lambda **_kwargs: {"status": "partial_diagnostic_only", "summary": {}, "gate": _closed_gate(), "blockers": []})
    monkeypatch.setattr(runner, "build_btc_exchange_runtime_replay_gap_report", lambda **_kwargs: {"status": "incomplete_research_only", "summary": {}, "gate": _closed_gate(), "blockers": []})
    monkeypatch.setattr(runner, "build_btc_perpetual_execution_evidence_pack", lambda **_kwargs: {"status": "incomplete_research_only", "summary": {}, "gate": _closed_gate(), "blockers": []})
    monkeypatch.setattr(runner, "build_btc_gate_dashboard_file", lambda **_kwargs: {"status": "blocked", "blockers": []})

    report = runner.run_btc_perpetual_evidence_observe_only_daily(
        repo_root=tmp_path,
        output_root=Path("artifacts/btc_perpetual_evidence_observe_only_daily/latest"),
        execute_network=True,
        generated_at="2026-07-01T00:00:00Z",
    )

    assert report["status"] == "partial_research_only"
    assert "okx_l2_depth_observation_failed" in report["blockers"]
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["live_unlock_allowed"] is False


def _closed_gate() -> dict[str, bool]:
    return {
        "paper_queue_write_allowed": False,
        "paper_candidate_created": False,
        "live_unlock_allowed": False,
        "live_order_allowed": False,
        "oms_access_allowed": False,
        "broker_access_allowed": False,
    }
