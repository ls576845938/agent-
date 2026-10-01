import json
from pathlib import Path


RUN = Path("artifacts/btc_hypothesis/20260518T010000Z_range_reclaim_lifecycle")


def test_range_reclaim_safety_status_locked_and_frozen() -> None:
    safety = json.loads((RUN / "paper_live_safety_status.json").read_text(encoding="utf-8"))

    assert safety["candidate_passed_internal_gate"] == 0
    assert safety["paper_queue"] == "LOCKED"
    assert safety["paper_queue_locked"] is True
    assert safety["paper_auto_start"] is False
    assert safety["live"] == "FROZEN"
    assert safety["live_frozen"] is True
    assert safety["real_broker_api_called"] is False
    assert safety["real_orders_created"] is False
