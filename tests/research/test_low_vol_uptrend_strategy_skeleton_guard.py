import json
from pathlib import Path

from quant_us.research.btc_low_vol_uptrend import write_strategy_skeleton


RUN = Path("artifacts/btc_hypothesis/20260516T120000Z_lowvol_uptrend")
SKELETON = Path("configs/btc/hypothesis/low_vol_uptrend_event_continuation_v1.yaml")


def test_low_vol_uptrend_rejected_decision_does_not_generate_skeleton() -> None:
    decision = json.loads((RUN / "low_vol_uptrend_hypothesis_decision.json").read_text(encoding="utf-8"))

    assert decision["strategy_skeleton_generated"] is False
    assert not SKELETON.exists()


def test_low_vol_uptrend_skeleton_is_research_only_when_allowed(tmp_path) -> None:
    skeleton = tmp_path / "low_vol_uptrend_event_continuation_v1.yaml"
    write_strategy_skeleton(skeleton)
    text = skeleton.read_text(encoding="utf-8")

    assert "promotion_status: research_candidate" in text
    assert "side: long_only" in text
    assert "orderflow_entry_trigger: false" in text
    assert "paper_ready: false" in text
    assert "live_ready: false" in text
    assert "live_enabled: false" in text
    assert "broker_api_allowed: false" in text
