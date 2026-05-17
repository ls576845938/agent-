import json
from pathlib import Path


RUN = Path("artifacts/btc_candidate_attribution/20260517T010000Z_liquidation_shock_attribution")


def test_liquidation_shock_paper_live_safety_status() -> None:
    safety = json.loads((RUN / "paper_live_safety_status.json").read_text(encoding="utf-8"))
    promotion = json.loads((RUN / "promotion_decision.json").read_text(encoding="utf-8"))

    assert safety["candidate_passed_internal_gate"] == 0
    assert safety["paper_queue"] == "LOCKED"
    assert safety["paper_queue_locked"] is True
    assert safety["paper_auto_start"] is False
    assert safety["live"] == "FROZEN"
    assert safety["live_frozen"] is True
    assert safety["real_broker_api_called"] is False
    assert safety["real_orders_created"] is False
    assert promotion["candidate_passed_internal_gate_count"] == 0
    assert promotion["paper_review"]["paper_review_queue_locked"] is True
    assert promotion["paper_review"]["paper_review_pending"] == []
    assert promotion["live_frozen"] is True
