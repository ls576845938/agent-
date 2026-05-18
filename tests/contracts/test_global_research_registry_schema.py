from __future__ import annotations

import json
from pathlib import Path

from scripts.build_global_research_registry import build_global_registry


SCHEMA = Path("schemas/global_research_registry.schema.json")


def test_global_research_registry_schema_has_required_constraints() -> None:
    assert SCHEMA.exists()

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    assert schema["required"] == [
        "schema_version",
        "generated_at",
        "commit",
        "branch",
        "paper_queue_status",
        "live_status",
        "candidate_passed_internal_gate",
        "assets",
    ]
    assert schema["properties"]["paper_queue_status"]["const"] == "locked"
    assert schema["properties"]["live_status"]["const"] == "frozen"
    assert schema["properties"]["candidate_passed_internal_gate"]["const"] == 0
    assert schema["properties"]["assets"]["required"] == ["us_equity", "btc"]
    us_equity_schema = schema["properties"]["assets"]["properties"]["us_equity"]
    assert us_equity_schema["properties"]["status"]["const"] == "mainline"
    assert "data_lineage" in us_equity_schema["required"]
    assert "factor_evidence" in us_equity_schema["required"]
    assert "portfolio_evidence" in us_equity_schema["required"]
    assert us_equity_schema["properties"]["current_candidates"]["items"]["properties"]["allowed_next_action"]["const"] == (
        "internal_event_backtest_required"
    )
    assert schema["properties"]["assets"]["properties"]["btc"]["properties"]["status"]["const"] == "research_sandbox"


def test_build_global_registry_minimum_structure_matches_policy() -> None:
    registry = build_global_registry(generated_at="2026-05-18T00:00:00Z")

    assert registry["schema_version"] == "global_research_registry_v1"
    assert registry["generated_at"] == "2026-05-18T00:00:00Z"
    assert registry["paper_queue_status"] == "locked"
    assert registry["live_status"] == "frozen"
    assert registry["candidate_passed_internal_gate"] == 0
    assert registry["assets"]["us_equity"]["status"] == "mainline"
    assert registry["assets"]["us_equity"]["data_lineage"]["status"] in {"missing", "partial", "complete"}
    assert registry["assets"]["us_equity"]["factor_evidence"]["status"] in {"missing", "partial", "complete"}
    assert registry["assets"]["us_equity"]["portfolio_evidence"]["status"] in {"missing", "research_only", "complete"}
    assert "internal_event_backtest_required" in registry["assets"]["us_equity"]["allowed_next_actions"]
    assert all(
        not data_version.startswith("qs-sqlite-BTC")
        for data_version in registry["assets"]["us_equity"]["data_lineage"]["data_versions"]
    )
    assert registry["assets"]["btc"]["status"] == "research_sandbox"

    btc_candidates = registry["assets"]["btc"]["current_candidates"]
    assert len(btc_candidates) == 1
    assert btc_candidates[0]["name"] == "compression_expansion_breakout"
    assert btc_candidates[0]["allowed_next_action"] == "attribution_only"
