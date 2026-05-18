import json
from pathlib import Path


RUN = Path("artifacts/btc_hypothesis/20260518T010000Z_range_reclaim_lifecycle")


def test_range_reclaim_gate_requires_full_lifecycle_and_folds() -> None:
    decision = json.loads((RUN / "range_reclaim_hypothesis_decision_v2.json").read_text(encoding="utf-8"))

    assert decision["paper_queue"] == "LOCKED"
    assert decision["live"] == "FROZEN"
    if decision["decision"] != "hypothesis_passed_for_strategy_skeleton":
        assert decision["strategy_skeleton_generated"] is False
        assert decision["strategy_skeleton_path"] == ""
    assert "full_lifecycle_event_PF_proxy" in decision["checks"]
    assert "fold_pass_rate_lifecycle" in decision["checks"]
    assert "cost_stress_proxy_base" in decision["checks"]
    assert "top5_positive_contribution" in decision["checks"]


def test_range_reclaim_skeleton_guard_blocks_unpassed_hypothesis() -> None:
    decision = json.loads((RUN / "range_reclaim_hypothesis_decision_v2.json").read_text(encoding="utf-8"))

    if decision["decision"] != "hypothesis_passed_for_strategy_skeleton":
        assert decision["skeleton_guard_decision"] == "do_not_generate_skeleton"
        assert not Path("configs/btc/hypotheses/range_reclaim_momentum_v1_skeleton.yaml").exists()
