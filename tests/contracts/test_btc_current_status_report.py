from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from scripts.build_btc_current_status_report import build_btc_current_status_report


SCHEMA = Path("schemas/btc_current_status_report.schema.json")


def test_btc_current_status_schema_valid() -> None:
    payload = build_btc_current_status_report(generated_at="2026-06-22T00:00:00Z")
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    jsonschema.validate(payload, schema)


def test_btc_current_status_separates_research_definition_from_paper_execution() -> None:
    payload = build_btc_current_status_report(generated_at="2026-06-22T00:00:00Z")
    selected = payload["selected_candidate_definition"]
    policy = payload["execution_evidence_policy"]
    external = payload["external_evidence"]

    assert payload["status"] == "paper_observing"
    assert payload["state_machine"]["authoritative_state"] == "paper_observing"
    assert payload["state_machine"]["allowed_sequence"] == [
        "research_only",
        "backtest_validated",
        "paper_candidate_ready",
        "paper_review_pending",
        "paper_observing",
    ]
    assert payload["state_machine"]["live_status"] == "frozen"
    assert payload["state_machine"]["live_transition_allowed"] is False
    assert payload["active_current_research_focus"] == "pullback_reclaim_intraday_v0"
    assert payload["research_gate_status"] == "passed_for_manual_review"
    assert payload["research_candidate_definition_status"] == "ready"
    assert payload["research_definition_passed_internal_gate"] == 1
    assert payload["paper_candidate_passed_internal_gate"] == 1
    assert payload["current_research_candidate_definitions"] == [
        "btc_pullback_reclaim_intraday_high_vol_non_expansion_trend_guard_v1:"
        "high_vol_non_expansion_trend_guard_repair_v1:research_candidate_definition_v1"
    ]
    assert payload["current_paper_candidates"] == [
        "btc_pullback_reclaim_intraday_high_vol_non_expansion_trend_guard_v1:"
        "high_vol_non_expansion_trend_guard_repair_v1:paper_candidate_v1"
    ]
    assert selected["family_id"] == "pullback_reclaim_intraday_v0"
    assert selected["strategy_id"] == "btc_pullback_reclaim_intraday_high_vol_non_expansion_trend_guard_v1"
    assert selected["variant_id"] == "high_vol_non_expansion_trend_guard_repair_v1"
    assert payload["metrics"]["event_profit_factor"] == pytest.approx(1.4397)
    assert payload["metrics"]["walk_forward_pass_rate"] == pytest.approx(0.833333)
    assert payload["metrics"]["regime_pass_rate"] == pytest.approx(0.8)
    assert payload["paper_readiness_status"] == "ready_for_paper_start"
    assert payload["paper_queue_status"] == "approved"
    assert payload["live_status"] == "frozen"
    assert payload["guardrails"]["broker_calls_allowed"] is False
    assert policy["current_scope"] == "intraday_5m_15m_simulated_paper_not_true_scalping"
    assert policy["true_scalping_requirements_are_diagnostic_for_current_scope"] is True
    assert external["intraday_paper_sim_hard_blockers"] == []
    assert "btc_external_evidence_exchange_queue_position_model_missing" in external["true_scalping_only_blockers"]
    assert "btc_external_evidence_paper_gate_not_ready" not in external["true_scalping_only_blockers"]
    assert payload["readiness_summary"]["paper_candidate_generation_allowed"] is True
    assert payload["readiness_summary"]["paper_review_pending_allowed"] is True
    assert payload["readiness_summary"]["paper_blockers"] == []
    assert payload["readiness_summary"]["next_required_action"] == "start_paper_validation"
    assert payload["status_source_conflicts"] == []
    assert payload["blockers"] == []


def test_btc_current_status_fails_closed_without_manifest(tmp_path: Path) -> None:
    payload = build_btc_current_status_report(
        repo_root=tmp_path,
        generated_at="2026-06-22T00:00:00Z",
    )

    assert payload["status"] == "research_only"
    assert payload["active_current_research_focus"] == "none"
    assert payload["research_definition_passed_internal_gate"] == 0
    assert payload["current_research_candidate_definitions"] == []
    assert payload["current_paper_candidates"] == []
    assert payload["readiness_summary"]["next_required_action"] == "repair_current_btc_research_status"


def test_btc_current_status_detects_registry_readiness_queue_conflict(tmp_path: Path) -> None:
    _copy_current_btc_status_inputs(tmp_path)
    _write_json(
        tmp_path / "artifacts/btc_paper_readiness/latest/btc_paper_readiness_report.json",
        {
            "schema_version": "btc_paper_readiness_report_v1",
            "status": "ready_for_paper_start",
            "paper_queue_status": "approved",
            "paper_start_allowed": True,
            "next_required_action": "start_paper_validation",
        },
    )
    _write_json(
        tmp_path / "artifacts/btc_research_registry/research_registry.json",
        {"btc": {"paper_queue_status": "pending_review"}},
    )
    _write_json(
        tmp_path / "artifacts/global_research_registry/research_registry.json",
        {"paper_queue_status": "pending_review"},
    )

    payload = build_btc_current_status_report(
        repo_root=tmp_path,
        generated_at="2026-06-22T00:00:00Z",
    )

    assert payload["status"] == "paper_observing"
    assert payload["paper_queue_status"] == "approved"
    assert payload["status_source_conflicts"] == [
        "btc_current_status_btc_registry_queue_conflict",
        "btc_current_status_global_registry_queue_conflict",
    ]
    assert payload["blockers"] == payload["status_source_conflicts"]


def _copy_current_btc_status_inputs(tmp_path: Path) -> None:
    for relative in [
        "artifacts/btc_candidate_gate/latest/btc_intraday_short_cycle_promotion_gate_report.json",
        "artifacts/btc_candidate_gate/latest/btc_intraday_short_cycle_manual_review_packet.json",
        "artifacts/btc_candidate_gate/latest/btc_intraday_short_cycle_research_candidate_definition_preflight.json",
        "artifacts/btc_candidate_gate/latest/btc_intraday_short_cycle_research_candidate_definition_manifest.json",
        "artifacts/btc_candidate_gate/latest/btc_intraday_short_cycle_remaining_external_evidence_status_report.json",
        "artifacts/btc_candidate_gate/latest/btc_intraday_short_cycle_paper_candidate_gate_report.json",
        "artifacts/btc_candidate_gate/latest/candidate_gate_audit_report.json",
        "artifacts/btc_candidate_gate/latest/candidate_metric_repair_report.json",
    ]:
        source = Path(relative)
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
