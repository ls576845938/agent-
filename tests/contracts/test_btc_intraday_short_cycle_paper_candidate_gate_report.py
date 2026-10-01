from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from scripts.build_btc_intraday_short_cycle_paper_candidate_gate_report import (
    build_btc_intraday_short_cycle_paper_candidate_gate_report,
)


SCHEMA = Path("schemas/btc_intraday_short_cycle_paper_candidate_gate_report.schema.json")


def test_btc_intraday_short_cycle_paper_candidate_gate_schema_valid() -> None:
    payload = build_btc_intraday_short_cycle_paper_candidate_gate_report(
        generated_at="2026-06-22T00:00:00Z"
    )
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    jsonschema.validate(payload, schema)


def test_current_btc_intraday_short_cycle_paper_candidate_gate_is_ready_for_manual_paper_review() -> None:
    payload = build_btc_intraday_short_cycle_paper_candidate_gate_report(
        generated_at="2026-06-22T00:00:00Z"
    )
    lineage = payload["source_lineage"]

    assert payload["status"] == "ready_for_manual_paper_review"
    assert payload["decision"] == "allow_manual_paper_review_only"
    assert payload["next_required_action"] == "human_paper_review_approval"
    assert payload["paper_candidate_generation_allowed"] is True
    assert payload["paper_review_pending_allowed"] is True
    assert payload["paper_execution_authorized"] is False
    assert payload["paper_or_live_unlock_allowed"] is False
    assert payload["true_scalping_allowed"] is False
    assert payload["guardrails"]["broker_calls_allowed"] is False
    assert payload["guardrails"]["private_endpoints_allowed"] is False
    assert payload["guardrails"]["order_endpoints_allowed"] is False
    assert payload["guardrails"]["real_orders_created"] is False
    assert lineage["current_run_manifest_exists"] is True
    assert lineage["current_run_manifest_data_version_matches"] is True
    assert lineage["current_run_manifest_params_hash_matches"] is True
    assert lineage["current_cost_stress_report_exists"] is True
    assert lineage["current_cost_stress_required_scenarios_present"] is True
    assert lineage["current_cost_stress_all_scenarios_survive"] is True
    assert lineage["latest_cost_model_matches_current_candidate_run"] is True
    assert lineage["latest_funding_ledger_matches_current_candidate_trade_ledger"] is True
    assert payload["blockers"] == []


def test_btc_intraday_short_cycle_paper_candidate_gate_fails_closed_without_inputs(tmp_path: Path) -> None:
    payload = build_btc_intraday_short_cycle_paper_candidate_gate_report(
        repo_root=tmp_path,
        generated_at="2026-06-22T00:00:00Z",
    )

    assert payload["status"] == "blocked_paper_candidate_gate"
    assert payload["paper_candidate_generation_allowed"] is False
    assert payload["paper_review_pending_allowed"] is False
    assert payload["paper_execution_authorized"] is False
    assert payload["paper_or_live_unlock_allowed"] is False
    assert payload["true_scalping_allowed"] is False
    assert "btc_intraday_paper_candidate_gate_current_status_present_failed" in payload["blockers"]
