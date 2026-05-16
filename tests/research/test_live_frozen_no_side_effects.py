import json
from pathlib import Path


def test_btc_canonical_research_code_has_no_live_or_broker_side_effects() -> None:
    combined = "\n".join(
        [
            Path("quant_us/research/btc_canonical.py").read_text(encoding="utf-8"),
            Path("scripts/run_btc_canonical_attribution.py").read_text(encoding="utf-8"),
        ]
    )

    assert "quant_us.live" not in combined
    assert "run_live" not in combined
    assert "submit_order" not in combined
    assert "live_enabled = True" not in combined


def test_canonical_promotion_decision_keeps_live_frozen() -> None:
    decision = json.loads(
        Path("artifacts/btc_canonical/20260516T061000Z_attribution/promotion_decision.json").read_text(encoding="utf-8")
    )

    assert decision["paper_review"]["paper_review_queue_locked"] is True
    assert decision["paper_review"]["paper_auto_start"] is False
    assert decision["paper_review"]["live_frozen"] is True
    assert decision["live_frozen"] is True
