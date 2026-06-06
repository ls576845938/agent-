from __future__ import annotations

import json
from pathlib import Path

from scripts.build_global_research_registry import build_global_registry


ATTRIBUTION = Path("artifacts/btc_candidate_attribution/latest_compression_expansion_attribution/attribution_report.json")


def test_compression_expansion_allowed_next_action_is_archive_only() -> None:
    registry = build_global_registry(generated_at="2026-05-19T00:00:00Z")
    btc = registry["assets"]["btc"]

    assert btc["current_candidates"] == []
    assert btc["attribution_only"] == []
    assert "compression_expansion_breakout" in btc["archived_or_rejected"]
    assert btc["compression_boundary"]["allowed_next_action"] == "archive_only"


def test_btc_paper_review_pending_not_allowed() -> None:
    registry = build_global_registry(generated_at="2026-05-19T00:00:00Z")
    btc = registry["assets"]["btc"]
    attribution = json.loads(ATTRIBUTION.read_text(encoding="utf-8"))

    assert btc["candidate_gate_audit"]["paper_review_pending_allowed"] is False
    assert attribution["paper_review_pending_created"] is False
    assert attribution["paper_review_pending_allowed"] is False
    assert attribution["promotion_ready"] is False


def test_archived_btc_alpha_not_skeleton_allowed() -> None:
    registry = build_global_registry(generated_at="2026-05-19T00:00:00Z")
    archived = registry["assets"]["btc"]["archived_or_rejected"]

    assert "liquidation_shock_recovery" in archived
    assert "low_vol_uptrend" in archived
    assert "compression_expansion_breakout" in archived


def test_btc_current_candidates_do_not_enter_paper_queue() -> None:
    registry = build_global_registry(generated_at="2026-05-19T00:00:00Z")

    assert registry["paper_queue_status"] == "locked"
    assert registry["live_status"] == "frozen"
    assert registry["candidate_passed_internal_gate"] == 0
    assert registry["assets"]["btc"]["current_candidates"] == []
    assert registry["assets"]["btc"]["attribution_only"] == []


def test_btc_fold_regime_blockers_are_explained_by_registry() -> None:
    registry = build_global_registry(generated_at="2026-05-19T00:00:00Z")
    btc = registry["assets"]["btc"]
    explanation = registry["failure_explanations"]["btc"]

    assert explanation["status"] == "incomplete"
    assert btc["compression_boundary"]["status"] == "archived"
    assert explanation["top_reasons"]
    assert explanation["incomplete_requirements"] == [
        "manual_exchange_info_capture",
        "funding_info_endpoint_policy_repair",
    ]
    assert explanation["next_required_action"] == "manual_capture_from_allowed_network"
