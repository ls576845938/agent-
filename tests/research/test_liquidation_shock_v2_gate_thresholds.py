import json
from pathlib import Path


RUN = Path("artifacts/btc_candidate_attribution/20260517T010000Z_liquidation_shock_attribution")


def test_liquidation_shock_v2_gate_thresholds_block_failed_ablations() -> None:
    decision = json.loads((RUN / "liquidation_shock_skeleton_decision.json").read_text(encoding="utf-8"))
    lifecycle = json.loads((RUN / "liquidation_shock_exit_lifecycle_ablation.json").read_text(encoding="utf-8"))
    confirmation = json.loads((RUN / "liquidation_shock_recovery_confirmation_report.json").read_text(encoding="utf-8"))

    assert decision["status"] == "research_failed"
    assert "no_ablation_simultaneously_passed_event_PF_WF_and_cost_stress_base" in decision["reasons"]
    assert lifecycle["best_by_event_PF"]["event_PF"] < 1.15
    assert confirmation["best_confirmation"]["event_PF"] < 1.15
    assert decision["paper_queue"] == "LOCKED"
    assert decision["live"] == "FROZEN"
