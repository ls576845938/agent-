from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from scripts.build_btc_intraday_short_cycle_remaining_external_evidence_status import (
    build_btc_intraday_short_cycle_remaining_external_evidence_status,
)


SCHEMA = Path("schemas/btc_intraday_short_cycle_remaining_external_evidence_status.schema.json")
REPORT = Path("artifacts/btc_candidate_gate/latest/btc_intraday_short_cycle_remaining_external_evidence_status_report.json")


def test_btc_intraday_short_cycle_remaining_external_evidence_status_schema_valid() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    jsonschema.validate(payload, schema)


def test_current_btc_intraday_short_cycle_remaining_external_evidence_status_is_external_only() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))

    assert payload["status"] == "candidate_definition_ready_external_evidence_pending"
    assert payload["decision"] == "continue_external_evidence_collection_no_candidate_no_paper_no_live"
    assert payload["next_required_action"] == (
        "collect_long_ws_l2_history_private_execution_latency_queue_evidence_then_paper_gate"
    )
    assert payload["checks"]["manual_approval_satisfied"] is True
    assert payload["checks"]["research_candidate_definition_manifest_ready"] is True
    assert payload["checks"]["candidate_generation_still_locked"] is True
    assert payload["checks"]["strategy_skeleton_still_locked"] is True
    assert payload["checks"]["paper_live_still_locked"] is True
    assert payload["checks"]["true_scalping_still_locked"] is True
    assert payload["checks"]["ws_l2_public_source_boundary_satisfied"] is True
    assert payload["checks"]["ws_l2_required_channels_observed"] is True
    assert payload["checks"]["ws_l2_resync_policy_exercised"] is True
    assert payload["checks"]["ws_proxy_diagnostics_ready"] is True
    assert payload["checks"]["ws_l2_coverage_contract_satisfied"] is False
    assert payload["checks"]["long_horizon_l2_tick_import_contract_satisfied"] is False
    assert payload["checks"]["long_horizon_l2_tick_history_contract_satisfied"] is False
    assert payload["checks"]["public_ws_receive_latency_is_private_order_execution_latency"] is False
    assert payload["checks"]["public_l2_visible_queue_is_exchange_queue_position"] is False
    assert payload["checks"]["execution_queue_external_evidence_contract_satisfied"] is False
    assert payload["checks"]["execution_latency_evidence_contract_satisfied"] is False
    assert payload["checks"]["queue_position_evidence_contract_satisfied"] is False
    assert payload["checks"]["private_order_execution_latency_model_ready"] is False
    assert payload["checks"]["exchange_queue_position_model_ready"] is False
    assert payload["checks"]["paper_gate_ready"] is False
    assert payload["remaining_blocker_summary"]["only_external_evidence_blockers_remain"] is True
    assert payload["remaining_blocker_summary"]["automated_engineering_blockers"] == []
    assert set(payload["remaining_external_evidence_categories"]) == {
        "real_long_horizon_market_data",
        "execution_evidence",
        "queue_evidence",
        "paper_gate",
    }
    assert payload["remaining_external_evidence_blockers"] == [
        "btc_true_scalping_long_horizon_l2_tick_history_missing",
        "btc_true_scalping_execution_latency_model_missing",
        "btc_true_scalping_queue_position_model_missing",
        "btc_paper_gate_approval_and_observation_missing",
    ]
    assert "btc_external_evidence_long_horizon_l2_coverage_not_satisfied" in payload["blockers"]
    assert "btc_external_evidence_private_execution_latency_model_missing" in payload["blockers"]
    assert "btc_external_evidence_exchange_queue_position_model_missing" in payload["blockers"]
    assert "btc_external_evidence_paper_gate_not_ready" in payload["blockers"]
    assert payload["candidate_generation_allowed"] is False
    assert payload["strategy_skeleton_generation_allowed"] is False
    assert payload["paper_or_live_unlock_allowed"] is False
    assert payload["true_scalping_allowed"] is False


def test_btc_intraday_short_cycle_remaining_external_evidence_status_missing_inputs_fail_closed(
    tmp_path: Path,
) -> None:
    payload = build_btc_intraday_short_cycle_remaining_external_evidence_status(
        repo_root=tmp_path,
        generated_at="2026-06-21T00:00:00Z",
    )

    assert payload["status"] == "blocked_candidate_definition_or_manual_approval_required"
    assert payload["candidate_generation_allowed"] is False
    assert payload["strategy_skeleton_generation_allowed"] is False
    assert payload["paper_or_live_unlock_allowed"] is False
    assert payload["true_scalping_allowed"] is False
    assert "btc_external_evidence_status_manual_approval_not_satisfied" in payload["blockers"]
    assert "btc_external_evidence_status_candidate_definition_manifest_not_ready" in payload["blockers"]


def test_btc_intraday_short_cycle_remaining_external_evidence_status_schema_rejects_unlock() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    payload["paper_or_live_unlock_allowed"] = True

    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError:
        pass
    else:  # pragma: no cover - assertion branch.
        raise AssertionError("schema must reject paper/live unlock")

    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    payload["guardrails"]["broker_calls_allowed"] = True

    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError:
        pass
    else:  # pragma: no cover - assertion branch.
        raise AssertionError("schema must reject broker unlock")
