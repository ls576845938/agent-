from __future__ import annotations

from scripts.build_global_research_registry import build_global_registry


CURRENT_BTC_PAPER_CANDIDATE = (
    "btc_pullback_reclaim_intraday_high_vol_non_expansion_trend_guard_v1:"
    "high_vol_non_expansion_trend_guard_repair_v1:paper_candidate_v1"
)


def test_compression_archive_recommended_boundary_is_registry_visible() -> None:
    registry = build_global_registry(generated_at="2026-05-19T00:00:00Z")
    btc = registry["assets"]["btc"]
    boundary = btc["compression_boundary"]

    assert boundary["status"] == "archived"
    assert boundary["allowed_next_action"] == "archive_only"
    assert boundary["archive_recommended"] is True
    assert boundary["limited_retest_allowed"] is False
    assert boundary["paper_review_pending_allowed"] is False
    assert btc["current_candidates"] == [CURRENT_BTC_PAPER_CANDIDATE]
    assert "compression_expansion_breakout" not in btc["current_candidates"]
    assert "compression_expansion_breakout" in btc["archived_or_rejected"]
