from quant_us.research.btc_canonical import decide_paper_queue_from_canonical


def test_paper_queue_locked_without_passed_candidates() -> None:
    decision = decide_paper_queue_from_canonical(
        [{"strategy_id": "btc_perp_dual_trend_v3", "status": "candidate_gate_failed", "passed": False}]
    )

    assert decision["paper_review_queue_locked"] is True
    assert decision["paper_review_pending"] == []
    assert decision["paper_auto_start"] is False
    assert decision["live_frozen"] is True
    assert decision["max_state"] == "candidate_gate_failed"
