import json
from pathlib import Path


RUN = Path("artifacts/btc_hypothesis/20260517T020000Z_hypothesis_lab_v2_lifecycle")


def test_hypothesis_lab_v2_skeleton_guard() -> None:
    decision = json.loads((RUN / "hypothesis_decision_v2.json").read_text(encoding="utf-8"))

    assert decision["decision"] != "hypothesis_passed_for_strategy_skeleton"
    assert decision["strategy_skeleton_generated"] is False
    assert decision["strategy_skeleton_path"] == ""
    assert decision["skeleton_guard_decision"] == "do_not_generate_skeleton"
    assert decision["paper_queue"] == "LOCKED"
    assert decision["live"] == "FROZEN"
