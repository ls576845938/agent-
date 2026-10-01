from quant_us.research.btc_alpha_hardening import decide_paper_review_queue


def test_paper_review_queue_locked_without_internal_gate_pass() -> None:
    decision = decide_paper_review_queue(
        [{"strategy_id": "btc_perp_dual_trend_v2", "status": "candidate_gate_failed", "passed": False}]
    )

    assert decision["paper_review_queue_locked"] is True
    assert decision["paper_review_pending"] == []
    assert decision["max_state"] == "candidate_gate_failed"
    assert decision["paper_auto_start"] is False
    assert decision["live_frozen"] is True


def test_paper_review_queue_is_manual_only_after_gate_pass() -> None:
    decision = decide_paper_review_queue(
        [{"strategy_id": "btc_perp_dual_trend_v2", "status": "candidate_passed_internal_gate", "passed": True}]
    )

    assert decision["paper_review_queue_locked"] is False
    assert decision["paper_review_pending"] == ["btc_perp_dual_trend_v2"]
    assert decision["max_state"] == "paper_review_pending"
    assert decision["paper_auto_start"] is False
    assert decision["live_frozen"] is True
