from __future__ import annotations

import json
from pathlib import Path

from scripts.build_global_research_registry import build_global_registry


def test_global_registry_contains_failure_explanations() -> None:
    registry = build_global_registry(generated_at="2026-05-19T00:00:00Z")

    explanations = registry["failure_explanations"]
    assert set(explanations) == {"data_lineage", "factor_evidence", "portfolio", "btc", "paper_live"}


def test_failure_explanations_use_actual_blockers(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "artifacts/us_equity_data_status/latest/data_status_report.json",
        {"schema_version": "us_equity_data_status_report_v1", "blockers": ["point_in_time_universe_not_confirmed"]},
    )
    _write_json(
        tmp_path / "artifacts/us_equity_factor_evidence/latest/factor_evidence_pack.json",
        {
            "schema_version": "us_equity_factor_evidence_pack_v1",
            "status": "partial",
            "factor_count": 1,
            "factor_pass_count": 0,
            "factor_fail_count": 1,
            "blockers": ["data_lineage_gate_failed"],
            "data_lineage": {"promotion_clean": False},
        },
    )
    _write_json(
        tmp_path / "artifacts/us_equity_portfolio/latest/portfolio_canonical_report.json",
        {
            "schema_version": "us_equity_portfolio_canonical_report_v1",
            "status": "partial",
            "event_ledger_status": {"status": "missing"},
            "blockers": ["us_equity_event_ledger_portfolio_backtest_required"],
            "promotion_ready": False,
        },
    )

    registry = build_global_registry(repo_root=tmp_path, generated_at="2026-05-19T00:00:00Z")
    explanations = registry["failure_explanations"]

    assert "point_in_time_universe_not_confirmed" in explanations["data_lineage"]["top_reasons"]
    assert "data_lineage_gate_failed" in explanations["factor_evidence"]["top_reasons"]
    assert "us_equity_event_ledger_portfolio_backtest_required" in explanations["portfolio"]["top_reasons"]


def test_failure_explanations_do_not_change_gate_state() -> None:
    registry = build_global_registry(generated_at="2026-05-19T00:00:00Z")

    assert registry["paper_queue_status"] == "locked"
    assert registry["live_status"] == "frozen"
    assert registry["candidate_passed_internal_gate"] == 0
    assert registry["failure_explanations"]["paper_live"]["status"] == "locked"


def test_failure_explanations_next_actions_are_conservative() -> None:
    registry = build_global_registry(generated_at="2026-05-19T00:00:00Z")
    explanations = registry["failure_explanations"]

    assert explanations["data_lineage"]["next_required_action"] == "manual_data_acquisition"
    assert explanations["factor_evidence"]["next_required_action"] == "rerun_after_L4_data"
    assert explanations["portfolio"]["next_required_action"] == "portfolio_event_ledger_after_factor_pass"
    assert explanations["btc"]["next_required_action"] == "manual_capture_from_allowed_network"
    assert explanations["paper_live"]["next_required_action"] == "none_until_internal_gate_pass"


def test_btc_failure_explanation_uses_objective_audit_summary() -> None:
    registry = build_global_registry(generated_at="2026-05-19T00:00:00Z")
    btc = registry["failure_explanations"]["btc"]

    assert btc["status"] == "incomplete"
    assert btc["incomplete_requirements"] == [
        "manual_exchange_info_capture",
        "funding_info_endpoint_policy_repair",
    ]
    assert "funding_ledger_net_pnl_integration" in btc["complete_requirements"]
    assert "archive_compression_expansion_breakout" in btc["complete_requirements"]
    assert "btc_hypothesis_lab_v2_controlled_search" in btc["complete_requirements"]
    assert "btc_objective_incomplete:manual_exchange_info_capture" in btc["top_reasons"]
    assert "btc_objective_incomplete:funding_info_endpoint_policy_repair" in btc["top_reasons"]


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
