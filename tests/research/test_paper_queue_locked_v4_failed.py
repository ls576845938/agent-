import json
from pathlib import Path


RUN = Path("artifacts/btc_canonical/20260516T080000Z_eventpf_wf")


def test_paper_queue_locked_when_v4_failed() -> None:
    promotion = json.loads((RUN / "promotion_decision.json").read_text(encoding="utf-8"))

    assert promotion["candidate_gate_results"][0]["status"] == "candidate_gate_failed"
    assert promotion["paper_review"]["paper_review_queue_locked"] is True
    assert promotion["paper_review"]["paper_review_pending"] == []
    assert promotion["paper_auto_start"] is False
