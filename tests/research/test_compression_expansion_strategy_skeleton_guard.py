import json
from pathlib import Path

from quant_us.research.btc_hypothesis_lab import SKELETON_PATH


RUN = Path("artifacts/btc_hypothesis/20260516T122000Z_compression_expansion")


def test_compression_expansion_skeleton_only_generated_after_pass() -> None:
    decision = json.loads((RUN / "hypothesis_decision.json").read_text(encoding="utf-8"))

    assert decision["decision"] == "hypothesis_passed_for_strategy_skeleton"
    assert decision["strategy_skeleton_generated"] is True
    assert Path(decision["strategy_skeleton_path"]) == SKELETON_PATH
    assert SKELETON_PATH.exists()


def test_compression_expansion_skeleton_contains_no_paper_or_live_ready_state() -> None:
    text = SKELETON_PATH.read_text(encoding="utf-8")

    assert "status: research_candidate" in text
    assert "event_ledger_required: true" in text
    assert "paper_ready: false" in text
    assert "live_ready: false" in text
    assert "live_enabled: false" in text
    assert "broker_api_allowed: false" in text
    assert "real_orders_allowed: false" in text
    assert "paper_ready: true" not in text
    assert "live_ready: true" not in text
    assert "live_enabled: true" not in text
