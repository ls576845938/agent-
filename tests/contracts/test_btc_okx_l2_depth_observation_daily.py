from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import scripts.run_btc_okx_l2_depth_observation_daily as runner


def test_okx_l2_depth_observation_dry_run_keeps_all_trading_boundaries_closed(
    monkeypatch,
    tmp_path: Path,
) -> None:
    def fake_capture(**kwargs: Any) -> dict[str, Any]:
        assert kwargs["execute_network"] is False
        assert kwargs["append_existing"] is True
        return {
            "status": "dry_run",
            "network_called": False,
            "completed_sample_count": 0,
            "capture_summary": {},
            "current_capture_summary": {},
            "selected_bundle_dir": "data/external/btc_perpetual/okx_swap/bundles/fixture",
            "blockers": [],
        }

    def fail_builder(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise AssertionError("post-capture evidence builders should not run in dry-run")

    monkeypatch.setattr(runner, "capture_okx_timestamp_aligned_l2_public_data", fake_capture)
    monkeypatch.setattr(runner, "build_btc_true_scalping_l2_aligned_capture_quality_report", fail_builder)
    monkeypatch.setattr(runner, "build_btc_depth_slippage_fill_mapping_report", fail_builder)
    monkeypatch.setattr(runner, "build_btc_depth_slippage_report", fail_builder)
    monkeypatch.setattr(runner, "build_btc_cost_model_report", fail_builder)
    monkeypatch.setattr(runner, "build_btc_perpetual_execution_evidence_pack", fail_builder)

    report = runner.run_btc_okx_l2_depth_observation_daily(
        repo_root=tmp_path,
        output_root=Path("artifacts/btc_l2_depth_observation/latest"),
        execute_network=False,
        generated_at="2026-07-01T00:00:00Z",
    )

    safety = json.loads(
        (
            tmp_path
            / "artifacts/btc_l2_depth_observation/latest/paper_live_safety_status.json"
        ).read_text(encoding="utf-8")
    )
    assert report["status"] == "dry_run_free_public_l2_depth_observation_planned"
    assert report["post_capture_reports_built"] is False
    assert report["requested"]["free_data_sources_only"] is True
    assert "btc_okx_l2_depth_observation_dry_run_no_network_executed" in report["blockers"]
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["live_unlock_allowed"] is False
    assert report["guardrails"]["private_endpoint_used"] is False
    assert report["guardrails"]["order_endpoint_used"] is False
    assert safety["paper_queue_write_allowed"] is False
    assert safety["live_unlock_allowed"] is False
    assert safety["broker_access_allowed"] is False


def test_okx_l2_depth_observation_execute_rebuilds_evidence_in_order_and_reports_blockers(
    monkeypatch,
    tmp_path: Path,
) -> None:
    calls: list[str] = []

    def fake_capture(**kwargs: Any) -> dict[str, Any]:
        calls.append("capture")
        assert kwargs["execute_network"] is True
        assert kwargs["append_existing"] is True
        assert kwargs["sample_count"] == 3
        return {
            "status": "verified_preflight",
            "network_called": True,
            "completed_sample_count": 3,
            "capture_summary": {"same_capture_sequence_count": 3},
            "current_capture_summary": {"same_capture_sequence_count": 3},
            "selected_bundle_dir": "data/external/btc_perpetual/okx_swap/bundles/fixture",
            "alignment_manifest": {
                "latest_capture_end": "2026-07-01T00:02:00Z",
                "capture_end": "2026-07-01T00:02:00Z",
            },
            "blockers": [],
        }

    def fake_l2_quality(**kwargs: Any) -> dict[str, Any]:
        calls.append("l2_quality")
        assert kwargs["generated_at"] == "2026-07-01T00:02:00Z"
        return {
            "status": "aligned_l2_capture_missing_or_invalid_research_only",
            "blockers": ["btc_same_window_public_trade_book_alignment_missing"],
        }

    def fake_depth(**kwargs: Any) -> dict[str, Any]:
        calls.append("depth_slippage")
        assert kwargs["generated_at_utc"].isoformat() == "2026-07-01T00:02:00+00:00"
        return {
            "status": "partial_diagnostic_only",
            "depth_aware_slippage_history_verified": False,
            "snapshot_coverage": {"two_sided_snapshot_count": 3, "two_sided_coverage_days": 0.25},
            "blockers": ["btc_depth_aware_slippage_history_insufficient"],
        }

    def fake_fill_mapping(**kwargs: Any) -> dict[str, Any]:
        calls.append("depth_fill_mapping")
        assert kwargs["generated_at_utc"].isoformat() == "2026-07-01T00:02:00+00:00"
        return {
            "status": "incomplete_research_only",
            "strategy_fill_mapping_verified": False,
            "summary": {
                "gate_fill_count": 0,
                "mapped_gate_fill_count": 0,
            },
            "blockers": ["btc_depth_strategy_fill_mapping_no_gate_eligible_strategy_fills"],
        }

    def fake_cost(**kwargs: Any) -> dict[str, Any]:
        calls.append("cost_model")
        assert kwargs["generated_at"] == "2026-07-01T00:02:00Z"
        return {"status": "fail", "blockers": ["btc_slippage_depth_not_ready"]}

    def fake_write_cost(_payload: dict[str, Any], _output_root: Path) -> str:
        calls.append("write_cost_model")
        return "artifacts/btc_cost_model/latest/btc_cost_model_report.json"

    def fake_evidence(**kwargs: Any) -> dict[str, Any]:
        calls.append("perpetual_evidence")
        assert kwargs["generated_at_utc"].isoformat() == "2026-07-01T00:02:00+00:00"
        return {
            "status": "incomplete_research_only",
            "decision": "perpetual_execution_evidence_incomplete_fail_closed_no_paper_no_live",
            "summary": {"blocker_count": 1},
            "blockers": ["btc_perp_exec_liquidation_history_or_snapshots_available"],
        }

    monkeypatch.setattr(runner, "capture_okx_timestamp_aligned_l2_public_data", fake_capture)
    monkeypatch.setattr(runner, "build_btc_true_scalping_l2_aligned_capture_quality_report", fake_l2_quality)
    monkeypatch.setattr(runner, "build_btc_depth_slippage_fill_mapping_report", fake_fill_mapping)
    monkeypatch.setattr(runner, "build_btc_depth_slippage_report", fake_depth)
    monkeypatch.setattr(runner, "build_btc_cost_model_report", fake_cost)
    monkeypatch.setattr(runner, "write_btc_cost_model_report", fake_write_cost)
    monkeypatch.setattr(runner, "build_btc_perpetual_execution_evidence_pack", fake_evidence)

    report = runner.run_btc_okx_l2_depth_observation_daily(
        repo_root=tmp_path,
        output_root=Path("artifacts/btc_l2_depth_observation/latest"),
        execute_network=True,
        sample_count=3,
        request_sleep_seconds=0,
        generated_at="2026-07-01T00:00:00Z",
    )

    assert calls == [
        "capture",
        "l2_quality",
        "depth_fill_mapping",
        "depth_slippage",
        "cost_model",
        "write_cost_model",
        "perpetual_evidence",
    ]
    assert report["status"] == "free_public_l2_depth_observation_completed_research_only"
    assert report["post_capture_reports_built"] is True
    assert report["capture_request_generated_at_utc"] == "2026-07-01T00:00:00+00:00"
    assert report["post_capture_evidence_asof_utc"] == "2026-07-01T00:02:00+00:00"
    assert report["capture_snapshot"]["completed_sample_count"] == 3
    assert report["evidence_snapshot"]["depth_fill_mapping_verified"] is False
    assert report["depth_gate_progress"]["two_sided_snapshot_count"] == 3
    assert report["depth_gate_progress"]["remaining_two_sided_coverage_days"] == 13.75
    assert report["depth_gate_progress"]["gate_fill_count"] == 0
    assert "wait_for_or_replay_gate_eligible_non_flat_strategy_fill" in report["depth_gate_progress"]["next_required_evidence"]
    assert "btc_perp_exec_liquidation_history_or_snapshots_available" in report["blockers"]
    assert "btc_perp_exec_liquidation_history_or_snapshots_available" in report["free_data_policy"]["cannot_clear_with_free_data_yet"]
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["live_unlock_allowed"] is False
    assert (tmp_path / "artifacts/btc_l2_depth_observation/latest/btc_okx_l2_depth_observation_daily_run_report.json").exists()
    assert (tmp_path / "artifacts/btc_l2_depth_observation/latest/btc_okx_l2_depth_observation_daily_summary_cn.md").exists()


def test_depth_gate_progress_requires_continuous_okx_depth_history() -> None:
    progress = runner._depth_gate_progress(
        depth_slippage={
            "depth_aware_slippage_history_verified": False,
            "snapshot_coverage": {
                "two_sided_snapshot_count": 80,
                "two_sided_coverage_days": 14.5,
                "max_two_sided_gap_hours": 48.0,
                "two_sided_continuity_satisfied": False,
            },
        },
        fill_mapping={
            "strategy_fill_mapping_verified": True,
            "summary": {
                "gate_fill_count": 2,
                "mapped_gate_fill_count": 2,
            },
        },
    )

    assert progress["history_snapshot_requirement_satisfied"] is True
    assert progress["history_continuity_requirement_satisfied"] is False
    assert progress["history_coverage_days_requirement_satisfied"] is False
    assert progress["max_two_sided_gap_hours"] == 48.0
    assert "close_okx_two_sided_depth_history_gaps" in progress["next_required_evidence"]
    assert progress["gate_ready"] is False
