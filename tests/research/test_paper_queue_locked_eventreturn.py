import json
from pathlib import Path


RUN = Path("artifacts/btc_canonical/20260516T100000Z_eventreturn_alpha")


def test_paper_queue_locked_for_eventreturn_archive_decision() -> None:
    promotion = json.loads((RUN / "promotion_decision.json").read_text(encoding="utf-8"))

    assert promotion["alpha_renewal_decision"] == "archive_perp_dual_trend"
    assert promotion["paper_review"]["paper_review_queue_locked"] is True
    assert promotion["paper_review"]["paper_review_pending"] == []
    assert promotion["paper_auto_start"] is False
