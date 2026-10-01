from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import scripts.build_btc_gate_aggregation_chain as chain


TS = datetime(2026, 7, 5, 8, 0, tzinfo=timezone.utc)


def test_btc_gate_aggregation_chain_rebuilds_in_read_only_batch_order(tmp_path: Path, monkeypatch) -> None:
    calls: list[str] = []

    def fake_builder(name: str):
        def _build(**kwargs: Any) -> dict[str, Any]:
            calls.append(name)
            return {
                "status": "blocked" if name != "promotion_gate_control" else "blocked_research_only",
                "decision": f"{name}_decision",
                "generated_at_utc": TS.isoformat(),
                "aggregation_batch_id": kwargs.get("aggregation_batch_id", ""),
                "blockers": ["still_blocked"],
                "gate": {
                    "paper_queue_write_allowed": False,
                    "live_unlock_allowed": False,
                    "broker_or_order_allowed": False,
                },
                "artifact_freshness": {
                    "status": "pass",
                    "stale_source_count": 0,
                    "dependency_newer_than_consumer_count": 0,
                    "source_timeline_consistent": True,
                },
                "root_cause_summary": {"root_cause_count": 1},
                "required_rebuild_reports": [],
                "paper_candidate_packet": {"packet_status": "not_ready"},
            }

        return _build

    monkeypatch.setattr(chain, "build_btc_paper_exchange_rule_preflight", fake_builder("paper_exchange_rule"))
    monkeypatch.setattr(chain, "build_btc_manual_paper_review_approval", fake_builder("manual_paper_review_approval"))
    monkeypatch.setattr(chain, "_build_btc_paper_readiness_file", fake_builder("paper_readiness"))
    monkeypatch.setattr(chain, "build_btc_perpetual_paper_runtime_replay_report", fake_builder("paper_runtime_replay_current"))
    monkeypatch.setattr(
        chain,
        "build_btc_perpetual_paper_runtime_replay_drill_report",
        fake_builder("paper_runtime_replay_historical_drill"),
    )
    monkeypatch.setattr(
        chain,
        "build_btc_perpetual_paper_runtime_replay_fixture_drill_report",
        fake_builder("paper_runtime_replay_fixture_drill"),
    )
    monkeypatch.setattr(
        chain,
        "build_btc_perpetual_paper_runtime_reconciliation_report",
        fake_builder("paper_runtime_reconciliation"),
    )
    monkeypatch.setattr(
        chain,
        "build_btc_depth_slippage_fill_mapping_report",
        fake_builder("depth_slippage_fill_mapping"),
    )
    monkeypatch.setattr(chain, "build_btc_depth_slippage_report", fake_builder("depth_slippage"))
    monkeypatch.setattr(chain, "_build_btc_cost_model_file", fake_builder("cost_model"))
    monkeypatch.setattr(
        chain,
        "build_btc_perpetual_execution_evidence_pack",
        fake_builder("perpetual_execution_evidence"),
    )
    monkeypatch.setattr(
        chain,
        "build_btc_perpetual_gate_objective_status",
        fake_builder("perpetual_gate_objective"),
    )
    monkeypatch.setattr(chain, "build_btc_order_surface_audit_report", fake_builder("order_surface_audit"))
    monkeypatch.setattr(chain, "build_btc_exchange_public_runtime_dry_probe", fake_builder("public_runtime_dry_probe"))
    monkeypatch.setattr(chain, "build_btc_exchange_runtime_replay_gap_report", fake_builder("exchange_runtime_gap"))
    monkeypatch.setattr(chain, "build_btc_strategy_promotion_readiness_review", fake_builder("strategy_promotion_readiness"))
    monkeypatch.setattr(chain, "build_btc_paper_live_kill_switch_status", fake_builder("kill_switch"))
    monkeypatch.setattr(chain, "build_btc_gate_dashboard_file", fake_builder("gate_dashboard"))
    monkeypatch.setattr(chain, "build_btc_micro_live_preflight", fake_builder("micro_live_preflight"))
    monkeypatch.setattr(chain, "build_btc_gate_report_consistency", fake_builder("gate_report_consistency"))
    monkeypatch.setattr(chain, "build_btc_dirty_worktree_boundary_report", fake_builder("dirty_worktree_boundary"))
    monkeypatch.setattr(chain, "build_btc_promotion_gate_control", fake_builder("promotion_gate_control"))
    monkeypatch.setattr(chain, "build_btc_paper_candidate_packet", fake_builder("paper_candidate_packet_current"))

    report = chain.build_btc_gate_aggregation_chain(
        repo_root=tmp_path,
        output_dir=tmp_path / "out",
        generated_at_utc=TS,
        aggregation_batch_id="batch-test",
        publish_snapshot=False,
    )

    assert calls == [
        "manual_paper_review_approval",
        "paper_readiness",
        "paper_runtime_replay_current",
        "paper_runtime_replay_historical_drill",
        "paper_runtime_replay_fixture_drill",
        "paper_runtime_reconciliation",
        "depth_slippage_fill_mapping",
        "depth_slippage",
        "cost_model",
        "order_surface_audit",
        "paper_exchange_rule",
        "public_runtime_dry_probe",
        "exchange_runtime_gap",
        "perpetual_execution_evidence",
        "perpetual_gate_objective",
        "gate_dashboard",
        "strategy_promotion_readiness",
        "kill_switch",
        "paper_exchange_rule",
        "kill_switch",
        "micro_live_preflight",
        "gate_dashboard",
        "strategy_promotion_readiness",
        "kill_switch",
        "micro_live_preflight",
        "gate_dashboard",
        "gate_report_consistency",
        "dirty_worktree_boundary",
        "promotion_gate_control",
        "gate_dashboard",
        "gate_report_consistency",
        "promotion_gate_control",
        "paper_candidate_packet_current",
    ]
    assert calls.index("paper_runtime_replay_current") < calls.index("depth_slippage_fill_mapping")
    assert calls.index("depth_slippage_fill_mapping") < calls.index("depth_slippage")
    assert calls.index("depth_slippage") < calls.index("perpetual_execution_evidence")
    assert calls.index("exchange_runtime_gap") < calls.index("perpetual_execution_evidence")
    assert calls.index("perpetual_execution_evidence") < calls.index("perpetual_gate_objective")
    assert calls.index("perpetual_gate_objective") < calls.index("promotion_gate_control")
    assert calls.index("gate_report_consistency") < calls.index("promotion_gate_control")
    assert calls.index("dirty_worktree_boundary") < calls.index("promotion_gate_control")
    assert calls[-2] == "promotion_gate_control"
    assert report["aggregation_batch_id"] == "batch-test"
    assert report["status"] == "complete_read_only_research_only"
    assert report["source_timeline_consistent"] is True
    assert report["stale_source_count"] == 0
    assert report["dependency_newer_than_consumer_count"] == 0
    assert report["required_rebuild_reports"] == []
    assert report["paper_candidate_packet_status"] == "not_ready"
    assert "promotion_gate_control_initial" in report["step_order"]
    assert "gate_report_consistency" in report["step_order"]
    assert "gate_report_consistency_after_promotion_control" in report["step_order"]
    assert "paper_candidate_packet_current" in report["step_order"]
    assert "paper_candidate_packet_current_snapshot" not in report["step_order"]
    assert "paper_candidate_packet_template" not in report["step_order"]
    assert all(step["aggregation_batch_id"] == "batch-test" for step in report["steps"])
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["live_unlock_allowed"] is False
    assert report["gate"]["broker_or_order_allowed"] is False

    saved = json.loads((tmp_path / "out" / "btc_gate_aggregation_chain_report.json").read_text(encoding="utf-8"))
    assert saved["step_order"] == report["step_order"]
    safety = json.loads((tmp_path / "out" / "paper_live_safety_status.json").read_text(encoding="utf-8"))
    assert safety["paper_queue_write_allowed"] is False
    assert safety["live_unlock_allowed"] is False
