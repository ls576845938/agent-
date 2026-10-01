from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import scripts.run_btc_okx_l2_depth_observation_batch as runner


def test_l2_depth_observation_batch_repeats_observe_only_cycles_and_reports_progress(
    monkeypatch,
    tmp_path: Path,
) -> None:
    calls: list[dict[str, Any]] = []

    def fake_daily(**kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        cycle = len(calls)
        two_sided_days = 0.25 + cycle * 0.1
        return {
            "status": "free_public_l2_depth_observation_completed_research_only",
            "decision": "continue_accumulating_free_public_l2_depth_evidence_fail_closed_no_paper_no_live",
            "post_capture_reports_built": True,
            "depth_gate_progress": {
                "two_sided_snapshot_count": 48 + cycle,
                "two_sided_coverage_days": two_sided_days,
                "remaining_two_sided_coverage_days": round(14.0 - two_sided_days, 6),
                "required_two_sided_coverage_days": 14.0,
                "gate_fill_count": 0,
                "mapped_gate_fill_count": 0,
                "gate_ready": False,
            },
            "blockers": [
                "btc_depth_aware_slippage_history_insufficient",
                "btc_depth_strategy_fill_mapping_no_gate_eligible_strategy_fills",
            ],
        }

    monkeypatch.setattr(runner, "run_btc_okx_l2_depth_observation_daily", fake_daily)

    report = runner.run_btc_okx_l2_depth_observation_batch(
        repo_root=tmp_path,
        output_root=Path("artifacts/btc_l2_depth_observation/latest"),
        execute_network=True,
        cycles=2,
        cycle_sleep_seconds=0,
        sample_count=3,
        request_sleep_seconds=0,
        generated_at="2026-07-01T00:00:00Z",
    )

    safety = json.loads(
        (
            tmp_path
            / "artifacts/btc_l2_depth_observation/latest/btc_okx_l2_depth_observation_batch_safety_status.json"
        ).read_text(encoding="utf-8")
    )
    assert len(calls) == 2
    assert all(call["execute_network"] is True for call in calls)
    assert all(call["sample_count"] == 3 for call in calls)
    assert report["status"] == "free_public_l2_depth_batch_completed_research_only"
    assert report["completed_cycles"] == 2
    assert report["schema_version"] == "btc_okx_l2_depth_observation_batch_v2"
    assert report["data_version"] == "unpublished"
    assert report["run_id"].startswith("btc-l2-observation-")
    assert len(report["params_hash"]) == 64
    assert len(report["output_hash"]) == 64
    assert report["evidence_class"] == "fixture_or_diagnostic_only"
    assert report["promotion_evidence_ready"] is False
    assert "immutable_snapshot_not_published" in report["blockers"]
    assert "data_steward_attestation_required" in report["blockers"]
    assert report["depth_gate_progress_before"]["two_sided_coverage_days"] == 0.35
    assert report["depth_gate_progress_after"]["two_sided_coverage_days"] == 0.45
    assert report["depth_gate_progress_delta"]["two_sided_snapshot_count_delta"] == 1
    assert report["depth_gate_progress_delta"]["two_sided_coverage_days_delta"] == 0.1
    assert "btc_depth_aware_slippage_history_insufficient" in report["blockers"]
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["live_unlock_allowed"] is False
    assert report["gate"]["withdraw_allowed"] is False
    assert safety["paper_queue_write_allowed"] is False
    assert safety["live_unlock_allowed"] is False
    assert safety["broker_access_allowed"] is False
    assert safety["withdraw_allowed"] is False
    assert (tmp_path / "artifacts/btc_l2_depth_observation/latest/btc_okx_l2_depth_observation_batch_report.json").exists()
    assert (tmp_path / "artifacts/btc_l2_depth_observation/latest/btc_okx_l2_depth_observation_batch_summary_cn.md").exists()


def test_l2_depth_observation_batch_stops_when_gate_ready(monkeypatch, tmp_path: Path) -> None:
    calls = 0

    def fake_daily(**_kwargs: Any) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        return {
            "status": "free_public_l2_depth_observation_completed_research_only",
            "decision": "continue_accumulating_free_public_l2_depth_evidence_fail_closed_no_paper_no_live",
            "post_capture_reports_built": True,
            "depth_gate_progress": {
                "two_sided_snapshot_count": 60,
                "two_sided_coverage_days": 14.1,
                "remaining_two_sided_coverage_days": 0.0,
                "required_two_sided_coverage_days": 14.0,
                "gate_fill_count": 2,
                "mapped_gate_fill_count": 2,
                "gate_ready": True,
            },
            "blockers": [],
        }

    monkeypatch.setattr(runner, "run_btc_okx_l2_depth_observation_daily", fake_daily)

    report = runner.run_btc_okx_l2_depth_observation_batch(
        repo_root=tmp_path,
        output_root=Path("artifacts/btc_l2_depth_observation/latest"),
        execute_network=True,
        cycles=5,
        cycle_sleep_seconds=0,
        generated_at="2026-07-01T00:00:00Z",
    )

    assert calls == 1
    assert report["completed_cycles"] == 1
    assert report["stopped_reason"] == "depth_gate_ready"
    assert report["depth_gate_progress_after"]["gate_ready"] is True
    assert report["promotion_evidence_ready"] is False
    assert report["evidence_class"] == "fixture_or_diagnostic_only"
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["live_unlock_allowed"] is False
