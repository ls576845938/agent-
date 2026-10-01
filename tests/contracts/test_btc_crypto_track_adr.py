from __future__ import annotations

from pathlib import Path


ADR = Path("docs/btc_crypto_research_paper_track_adr.md")


def test_btc_crypto_track_adr_exists_and_defines_independent_boundary() -> None:
    text = ADR.read_text(encoding="utf-8")

    assert "**Status:** Accepted" in text
    assert "BTC is an independent crypto research/paper track" in text
    assert "US equity V1 remains the mainline equity track" in text
    assert "live_status` remains `frozen" in text
    assert "This ADR does not authorize live trading" in text


def test_btc_crypto_track_adr_pins_authoritative_state_machine_and_followups() -> None:
    text = ADR.read_text(encoding="utf-8")

    assert "research_only -> backtest_validated -> paper_candidate_ready -> paper_review_pending -> paper_observing" in text
    assert "btc_current_status` is the BTC state reconciler" in text
    assert "event_time`, `available_time`, `ingested_at`, `processed_at" in text
    assert "Build a BTC evidence-pack aggregator" in text
    assert "Add a BTC trial registry" in text
    assert "Add no-lookahead and truncation-consistency tests" in text


def test_btc_crypto_track_adr_blocks_us_equity_boundary_bleed() -> None:
    text = ADR.read_text(encoding="utf-8")

    assert "US equity schemas cannot be used as the BTC source of truth" in text
    assert "cannot reuse US equity broker assumptions without an explicit adapter contract" in text
    assert "BTC changes must avoid editing US equity files" in text
