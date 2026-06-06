from __future__ import annotations

import json
from pathlib import Path


BTC_REGISTRY = Path("artifacts/btc_research_registry/research_registry.json")
GLOBAL_REGISTRY = Path("artifacts/global_research_registry/research_registry.json")


def test_public_data_landing_does_not_change_compression_strategy_boundary() -> None:
    btc = json.loads(BTC_REGISTRY.read_text(encoding="utf-8"))["btc"]
    boundary = btc["compression_boundary"]

    assert boundary["status"] == "archived"
    assert boundary["allowed_next_action"] == "archive_only"
    assert boundary["archive_recommended"] is True
    assert boundary["limited_retest_allowed"] is False
    assert boundary["paper_review_pending_allowed"] is False
    assert btc["current_candidates"] == []
    assert "compression_expansion_breakout" in btc["archived_or_rejected"]


def test_public_data_landing_does_not_unlock_paper_live_or_internal_gate() -> None:
    registry = json.loads(GLOBAL_REGISTRY.read_text(encoding="utf-8"))
    btc = registry["assets"]["btc"]

    assert registry["paper_queue_status"] == "locked"
    assert registry["live_status"] == "frozen"
    assert registry["candidate_passed_internal_gate"] == 0
    assert btc["paper_queue_status"] == "locked"
    assert btc["live_status"] == "frozen"
    assert btc["candidate_passed_internal_gate"] == 0
    assert btc["current_candidates"] == []


def test_no_new_btc_strategy_skeleton_directory_from_public_data_landing() -> None:
    strategy_paths = [
        path
        for path in Path(".").glob("**/*compression*v2*")
        if ".git" not in path.parts and "artifacts" not in path.parts and "docs" not in path.parts
    ]

    assert strategy_paths == []
