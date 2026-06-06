from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from scripts.build_btc_perpetual_data_source_decision_report import (
    build_btc_perpetual_data_source_decision_report,
)


SCHEMA = Path("schemas/btc_perpetual_data_source_decision_report.schema.json")
REPORT = Path("artifacts/btc_data_status/latest/btc_perpetual_data_source_decision_report.json")


def test_btc_perpetual_data_source_decision_schema_valid() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    jsonschema.validate(payload, schema)


def test_btc_perpetual_data_source_decision_separates_research_history_from_execution() -> None:
    payload = build_btc_perpetual_data_source_decision_report(generated_at="2026-06-06T00:00:00Z")
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    jsonschema.validate(payload, schema)
    assert payload["status"] == "research_history_overlay_ready_execution_provider_not_switched"
    assert payload["decision"] == "switch_research_history_source_keep_execution_locked"
    assert payload["next_required_action"] == "run_research_only_funding_carry_distribution_on_history_overlay"
    assert payload["current_evidence_provider"]["provider"] == "okx_swap"
    assert payload["current_evidence_provider"]["bundle_id"] == "btc_okx_swap_btcusdt_history_365d_v1"
    assert payload["current_evidence_provider"]["duration_days"] == 94.333333
    assert payload["current_evidence_provider"]["research_history_sufficient"] is False

    overlay = payload["selected_research_history_source"]
    assert overlay["provider"] == "binance_usdm"
    assert overlay["bundle_id"] == "btc_usdm_binance_btcusdt_20240101_20260512_v1"
    assert overlay["source_role"] == "local_history_candidate"
    assert overlay["research_history_sufficient"] is True
    assert overlay["duration_days"] > 365.0
    assert overlay["klines_1h_record_count"] >= 8760
    assert overlay["funding_rate_record_count"] >= 1095
    assert "funding_carry_hypothesis_distribution_diagnostics" in overlay["allowed_uses"]
    assert "candidate_generation" in overlay["forbidden_uses"]
    assert "paper_or_live_execution" in overlay["forbidden_uses"]

    guardrails = payload["guardrails"]
    assert guardrails["cross_venue_history_may_unlock_hypothesis_diagnostics_only"] is True
    assert guardrails["cross_venue_history_may_unlock_candidate_or_paper"] is False
    assert guardrails["broker_calls_allowed"] is False
    assert guardrails["order_endpoints_allowed"] is False
    assert "btc_selected_research_overlay_is_not_user_execution_provider" in payload["blockers"]
    assert "btc_data_source_decision_does_not_unlock_candidate_or_paper" in payload["blockers"]


def test_btc_perpetual_data_source_decision_missing_repo_stays_blocked(tmp_path: Path) -> None:
    payload = build_btc_perpetual_data_source_decision_report(
        repo_root=tmp_path,
        generated_at="2026-06-06T00:00:00Z",
    )
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    jsonschema.validate(payload, schema)
    assert payload["status"] == "research_history_source_blocked"
    assert payload["guardrails"]["cross_venue_history_may_unlock_hypothesis_diagnostics_only"] is False
    assert "btc_research_history_overlay_not_ready" in payload["blockers"]
