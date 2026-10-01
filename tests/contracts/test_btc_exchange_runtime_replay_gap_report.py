from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from quant_crypto.research import btc_exchange_runtime_replay_gap as gap


def test_runtime_replay_gap_keeps_simulated_contract_and_short_public_ws_fail_closed(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime.json"
    coverage = tmp_path / "coverage.json"
    public_probe = tmp_path / "public_probe.json"
    paper = tmp_path / "missing_paper.json"
    reconciliation = tmp_path / "missing_reconciliation.json"
    _write_json(runtime, _runtime_contract(evidence_type="simulated_contract_probe"))
    _write_json(public_probe, _public_runtime_probe())
    _write_json(coverage, _coverage_report(coverage_ok=False, event_days=0.04, calendar_days=0.5, latency_ready=False, queue_ready=False))

    report = gap.build_btc_exchange_runtime_replay_gap_report(
        output_dir=tmp_path / "out",
        generated_at_utc=datetime(2026, 7, 1, tzinfo=timezone.utc),
        runtime_contract_path=runtime,
        public_runtime_dry_probe_path=public_probe,
        public_ws_coverage_path=coverage,
        paper_runtime_replay_path=paper,
        paper_runtime_reconciliation_path=reconciliation,
        aggregation_batch_id="batch-test",
    )

    assert report["schema_version"] == "btc_exchange_runtime_replay_gap_report_v1"
    assert report["aggregation_batch_id"] == "batch-test"
    assert report["status"] == "incomplete_research_only"
    assert report["decision"] == "runtime_replay_gap_incomplete_fail_closed_no_paper_no_live"
    assert "btc_runtime_contract_still_simulated_contract_probe" not in report["blockers"]
    assert "btc_runtime_contract_local_fixture_only_public_or_paper_runtime_layer_required" not in report["blockers"]
    assert report["summary"]["runtime_local_contract_is_simulated_probe"] is True
    assert report["summary"]["runtime_contract_is_simulated_probe"] is False
    assert report["summary"]["runtime_contract_effective_layer"] == "public_runtime_dry_probe_verified"
    assert report["summary"]["public_runtime_dry_probe_passed"] is True
    assert "btc_public_ws_l2_event_history_days_insufficient" in report["blockers"]
    assert "btc_execution_latency_model:data_insufficient" in report["blockers"]
    assert "btc_queue_model:data_insufficient" in report["blockers"]
    assert report["latency_model"]["schema_version"] == "btc_execution_latency_model_artifact_v1"
    assert {
        "decision_time_utc",
        "send_time_utc",
        "ack_time_utc",
        "fill_time_utc",
        "clock_offset_ms",
    } <= set(report["latency_model"]["field_schema"])
    assert report["latency_model"]["gate_blocker_type"] == "data_insufficient"
    assert report["queue_model"]["schema_version"] == "btc_queue_model_artifact_v1"
    assert {
        "visible_depth",
        "order_size",
        "level_consumption",
        "estimated_queue_position",
    } <= set(report["queue_model"]["field_schema"])
    assert report["queue_model"]["gate_blocker_type"] == "data_insufficient"
    assert "btc_paper_runtime_replay_missing" in report["blockers"]
    assert report["gap_analysis"]["public_ws_replay_sequence_ready"] is True
    assert report["runtime_capability_layers"]["schema_version"] == "btc_runtime_capability_layers_v1"
    assert report["runtime_capability_layers"]["local_deterministic_fixture"]["status"] == "passed"
    assert report["runtime_capability_layers"]["public_runtime_dry_probe"]["status"] == "passed"
    assert (
        report["runtime_capability_layers"]["paper_private_order_simulated_entry"]["status"]
        == "disabled_interface_ready_waiting_for_authorization_or_current_sample"
    )
    assert report["runtime_capability_layers"]["public_runtime_dry_probe"]["paper_gate_eligible"] is False
    assert report["runtime_capability_layers"]["paper_private_order_simulated_entry"]["paper_gate_eligible"] is False
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["live_unlock_allowed"] is False
    assert report["guardrails"]["order_endpoint_used"] is False

    safety = json.loads((tmp_path / "out" / "paper_live_safety_status.json").read_text(encoding="utf-8"))
    assert safety["paper_queue_write_allowed"] is False
    assert safety["live_unlock_allowed"] is False


def test_public_ws_coverage_alone_is_not_paper_runtime_replay(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime.json"
    coverage = tmp_path / "coverage.json"
    public_probe = tmp_path / "public_probe.json"
    paper = tmp_path / "missing_paper.json"
    reconciliation = tmp_path / "missing_reconciliation.json"
    _write_json(runtime, _runtime_contract(evidence_type="real_public_ws_replay", decision="runtime_ready_for_paper"))
    _write_json(public_probe, _public_runtime_probe())
    _write_json(coverage, _coverage_report(coverage_ok=True, event_days=31.0, calendar_days=31.0, latency_ready=True, queue_ready=True))

    report = gap.build_btc_exchange_runtime_replay_gap_report(
        output_dir=tmp_path / "out",
        generated_at_utc=datetime(2026, 7, 1, tzinfo=timezone.utc),
        runtime_contract_path=runtime,
        public_runtime_dry_probe_path=public_probe,
        public_ws_coverage_path=coverage,
        paper_runtime_replay_path=paper,
        paper_runtime_reconciliation_path=reconciliation,
    )

    assert report["status"] == "incomplete_research_only"
    assert report["gap_analysis"]["public_ws_coverage_contract_satisfied"] is True
    assert report["gap_analysis"]["paper_runtime_replay_ready"] is False
    assert report["blockers"] == ["btc_paper_runtime_replay_missing"]
    assert "public_market_replay_is_not_paper_execution_replay" in report["warnings"]
    assert report["gate"]["paper_queue_write_allowed"] is False


def test_runtime_replay_gap_distinguishes_flat_heartbeat_from_missing_trade_sample(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime.json"
    coverage = tmp_path / "coverage.json"
    public_probe = tmp_path / "public_probe.json"
    paper = tmp_path / "paper.json"
    reconciliation = tmp_path / "missing_reconciliation.json"
    _write_json(runtime, _runtime_contract(evidence_type="real_public_ws_replay", decision="runtime_ready_for_paper"))
    _write_json(public_probe, _public_runtime_probe())
    _write_json(coverage, _coverage_report(coverage_ok=True, event_days=31.0, calendar_days=31.0, latency_ready=True, queue_ready=True))
    _write_json(
        paper,
        {
            "status": "pending_research_only",
            "decision": "perpetual_paper_runtime_replay_current_gate_evidence_pending_no_paper_no_live",
            "summary": {
                "current_flat_heartbeat_healthy": True,
                "trade_execution_evidence_available": False,
                "trade_execution_evidence_pending_reason": "waiting_for_current_gate_eligible_non_flat_fill",
                "paper_runtime_health_status": "current_flat_heartbeat_healthy_waiting_for_trade_sample",
                "non_blocking_pending_conditions": [
                    "flat_no_gate_eligible_trade",
                    "waiting_for_current_gate_eligible_non_flat_fill"
                ],
            },
            "blockers": [],
            "private_endpoint_used": False,
            "order_endpoint_used": False,
            "real_order_submitted": False,
        },
    )

    report = gap.build_btc_exchange_runtime_replay_gap_report(
        output_dir=tmp_path / "out",
        generated_at_utc=datetime(2026, 7, 1, tzinfo=timezone.utc),
        runtime_contract_path=runtime,
        public_runtime_dry_probe_path=public_probe,
        public_ws_coverage_path=coverage,
        paper_runtime_replay_path=paper,
        paper_runtime_reconciliation_path=reconciliation,
    )

    assert report["status"] == "incomplete_research_only"
    assert "btc_runtime_ready_waiting_non_flat_sample" in report["blockers"]
    assert "btc_paper_runtime_replay_not_ready" not in report["blockers"]
    assert "btc_perpetual_paper_runtime_replay_no_simulated_fills" not in report["blockers"]
    assert "btc_perpetual_paper_runtime_replay_no_theoretical_orders_current_flat" not in report["blockers"]
    assert report["summary"]["paper_runtime_current_flat_heartbeat_healthy"] is True
    assert report["summary"]["paper_runtime_trade_execution_evidence_available"] is False
    assert (
        report["summary"]["paper_runtime_trade_execution_evidence_pending_reason"]
        == "waiting_for_current_gate_eligible_non_flat_fill"
    )
    assert report["summary"]["paper_runtime_health_status"] == "current_flat_heartbeat_healthy_waiting_for_trade_sample"
    assert report["summary"]["paper_runtime_ready_waiting_non_flat_sample"] is True
    assert report["summary"]["runtime_gate_wait_state"] == "runtime_ready_waiting_non_flat_sample"
    assert report["evidence_layers"]["current_observe_only_gate_evidence"]["status"] == "pending"
    assert report["evidence_layers"]["current_observe_only_gate_evidence"]["paper_gate_eligible"] is False
    assert report["evidence_layers"]["promotion_rule"]["fixture_or_drill_cannot_satisfy_gate"] is True
    assert "paper_runtime_currently_flat_heartbeat_healthy_but_trade_sample_missing" in report["warnings"]
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["live_unlock_allowed"] is False


def test_runtime_replay_gap_separates_fixture_drill_historical_drill_and_current_gate_evidence(
    tmp_path: Path,
) -> None:
    runtime = tmp_path / "runtime.json"
    coverage = tmp_path / "coverage.json"
    public_probe = tmp_path / "public_probe.json"
    paper = tmp_path / "paper.json"
    drill = tmp_path / "drill.json"
    fixture_drill = tmp_path / "fixture_drill.json"
    reconciliation = tmp_path / "missing_reconciliation.json"
    _write_json(runtime, _runtime_contract(evidence_type="real_public_ws_replay", decision="runtime_ready_for_paper"))
    _write_json(public_probe, _public_runtime_probe())
    _write_json(coverage, _coverage_report(coverage_ok=True, event_days=31.0, calendar_days=31.0, latency_ready=True, queue_ready=True))
    _write_json(
        paper,
        {
            "status": "pending_research_only",
            "decision": "perpetual_paper_runtime_replay_current_gate_evidence_pending_no_paper_no_live",
            "summary": {
                "current_flat_heartbeat_healthy": True,
                "trade_execution_evidence_available": False,
                "trade_execution_evidence_pending_reason": "waiting_for_current_gate_eligible_non_flat_fill",
                "paper_runtime_health_status": "current_flat_heartbeat_healthy_waiting_for_trade_sample",
            },
            "blockers": [],
            "private_endpoint_used": False,
            "order_endpoint_used": False,
            "real_order_submitted": False,
        },
    )
    _write_json(
        drill,
        {
            "status": "complete_research_only",
            "decision": "perpetual_paper_runtime_replay_drill_complete_not_gate_evidence_no_paper_no_live",
            "summary": {
                "simulated_fill_count": 3,
                "event_ledger_row_count": 15,
                "oms_session_reconciliation_status": "complete",
                "oms_session_unreconciled_count": 0,
                "paper_runtime_gate_evidence": False,
            },
            "blockers": [],
        },
    )
    _write_json(
        fixture_drill,
        {
            "status": "complete_research_only",
            "decision": "perpetual_paper_runtime_replay_fixture_drill_complete_not_gate_evidence_no_paper_no_live",
            "summary": {
                "paper_runtime_fixture_drill_ready": True,
                "simulated_fill_count": 2,
                "event_ledger_row_count": 10,
                "oms_session_reconciliation_status": "complete",
                "oms_session_unreconciled_count": 0,
                "paper_runtime_gate_evidence": False,
            },
            "blockers": [],
        },
    )

    report = gap.build_btc_exchange_runtime_replay_gap_report(
        output_dir=tmp_path / "out",
        generated_at_utc=datetime(2026, 7, 1, tzinfo=timezone.utc),
        runtime_contract_path=runtime,
        public_runtime_dry_probe_path=public_probe,
        public_ws_coverage_path=coverage,
        paper_runtime_replay_path=paper,
        paper_runtime_drill_path=drill,
        paper_runtime_fixture_drill_path=fixture_drill,
        paper_runtime_reconciliation_path=reconciliation,
    )

    layers = report["evidence_layers"]
    assert layers["schema_version"] == "btc_runtime_replay_evidence_layers_v1"
    assert layers["layer_order"] == [
        "fixture_capability",
        "historical_drill",
        "current_observe_only_gate_evidence",
    ]
    assert layers["fixture_capability"]["status"] == "passed"
    assert layers["fixture_capability"]["paper_gate_eligible"] is False
    assert layers["historical_drill"]["status"] == "passed"
    assert layers["historical_drill"]["paper_gate_eligible"] is False
    assert layers["current_observe_only_gate_evidence"]["status"] == "pending"
    assert layers["current_observe_only_gate_evidence"]["paper_gate_eligible"] is False
    assert layers["current_observe_only_gate_evidence"]["pending_reason"] == (
        "waiting_for_current_gate_eligible_non_flat_fill"
    )
    assert layers["promotion_rule"]["paper_gate_may_consider_only_layer"] == "current_observe_only_gate_evidence"
    assert layers["promotion_rule"]["fixture_or_drill_cannot_satisfy_gate"] is True
    assert report["summary"]["fixture_capability_passed"] is True
    assert report["summary"]["historical_drill_passed"] is True
    assert report["summary"]["current_observe_only_gate_evidence_passed"] is False
    assert report["summary"]["fixture_or_drill_cannot_satisfy_paper_gate"] is True
    assert "btc_runtime_ready_waiting_non_flat_sample" in report["blockers"]
    assert "btc_paper_runtime_replay_not_ready" not in report["blockers"]
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["live_unlock_allowed"] is False


def test_runtime_replay_gap_can_be_ready_for_manual_review_without_auto_promotion(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime.json"
    coverage = tmp_path / "coverage.json"
    public_probe = tmp_path / "public_probe.json"
    paper = tmp_path / "paper.json"
    reconciliation = tmp_path / "reconciliation.json"
    _write_json(runtime, _runtime_contract(evidence_type="real_public_ws_replay", decision="runtime_ready_for_paper"))
    _write_json(public_probe, _public_runtime_probe())
    _write_json(coverage, _coverage_report(coverage_ok=True, event_days=31.0, calendar_days=31.0, latency_ready=True, queue_ready=True))
    _write_json(
        paper,
        {
            "status": "complete_research_only",
            "decision": "paper_runtime_replay_ready_for_manual_review",
            "summary": {
                "trade_execution_evidence_available": True,
                "current_non_flat_sample_capture_status": "gate_eligible_non_flat_capture_ready",
                "gate_eligible_current_capture_count": 1,
            },
            "blockers": [],
            "private_endpoint_used": False,
            "order_endpoint_used": False,
            "real_order_submitted": False,
        },
    )
    _write_json(
        reconciliation,
        {
            "status": "complete_research_only",
            "decision": "paper_runtime_event_ledger_reconciled_research_only_no_paper_no_live",
            "summary": {
                "paper_runtime_reconciliation_passed": True,
                "violation_count": 0,
                "event_row_count": 10,
                "fill_event_count": 2,
                "funding_cashflow_event_count": 2,
            },
            "warnings": [],
        },
    )

    report = gap.build_btc_exchange_runtime_replay_gap_report(
        output_dir=tmp_path / "out",
        generated_at_utc=datetime(2026, 7, 1, tzinfo=timezone.utc),
        runtime_contract_path=runtime,
        public_runtime_dry_probe_path=public_probe,
        public_ws_coverage_path=coverage,
        paper_runtime_replay_path=paper,
        paper_runtime_reconciliation_path=reconciliation,
    )

    assert report["status"] == "complete_research_only"
    assert report["blockers"] == []
    assert report["summary"]["paper_runtime_replay_ready"] is True
    assert report["summary"]["paper_runtime_reconciliation_passed"] is True
    assert report["evidence_layers"]["current_observe_only_gate_evidence"]["paper_gate_eligible"] is True
    assert report["runtime_capability_layers"]["paper_private_order_simulated_entry"]["paper_gate_eligible"] is False
    assert (
        report["runtime_capability_layers"]["paper_private_order_simulated_entry"][
            "current_observe_only_gate_evidence_layer_required"
        ]
        is True
    )
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["live_unlock_allowed"] is False


def test_runtime_replay_gap_requires_reconciliation_when_paper_runtime_is_ready(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime.json"
    coverage = tmp_path / "coverage.json"
    public_probe = tmp_path / "public_probe.json"
    paper = tmp_path / "paper.json"
    missing_reconciliation = tmp_path / "missing_reconciliation.json"
    _write_json(runtime, _runtime_contract(evidence_type="real_public_ws_replay", decision="runtime_ready_for_paper"))
    _write_json(public_probe, _public_runtime_probe())
    _write_json(coverage, _coverage_report(coverage_ok=True, event_days=31.0, calendar_days=31.0, latency_ready=True, queue_ready=True))
    _write_json(
        paper,
        {
            "status": "complete_research_only",
            "decision": "paper_runtime_replay_ready_for_manual_review",
            "blockers": [],
            "private_endpoint_used": False,
            "order_endpoint_used": False,
            "real_order_submitted": False,
        },
    )

    report = gap.build_btc_exchange_runtime_replay_gap_report(
        output_dir=tmp_path / "out",
        generated_at_utc=datetime(2026, 7, 1, tzinfo=timezone.utc),
        runtime_contract_path=runtime,
        public_runtime_dry_probe_path=public_probe,
        public_ws_coverage_path=coverage,
        paper_runtime_replay_path=paper,
        paper_runtime_reconciliation_path=missing_reconciliation,
    )

    assert report["status"] == "incomplete_research_only"
    assert "btc_paper_runtime_reconciliation_not_passed" in report["blockers"]
    assert report["summary"]["paper_runtime_replay_ready"] is True
    assert report["summary"]["paper_runtime_reconciliation_passed"] is False
    assert report["gate"]["paper_queue_write_allowed"] is False


def _runtime_contract(*, evidence_type: str, decision: str = "runtime_tradeable_for_simulated_paper") -> dict:
    return {
        "status": "complete",
        "decision": decision,
        "venue": "okx",
        "mode": "paper",
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "real_order_submitted": False,
        "notes": {
            "evidence_type": evidence_type,
            "private_endpoint_used": False,
            "order_endpoint_used": False,
            "real_order_submitted": False,
        },
    }


def _public_runtime_probe() -> dict:
    return {
        "status": "verified_research_only",
        "decision": "btc_exchange_public_runtime_dry_probe_verified_no_order_no_private",
        "network_called": True,
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "real_order_submitted": False,
        "runtime_layer": {
            "status": "passed",
            "server_time_verified": True,
            "symbol_rules_visible": True,
            "mark_price_available": True,
            "index_price_available": True,
            "funding_available": True,
            "public_depth_available": True,
            "open_interest_available": True,
            "public_ws_replay_verified": True,
            "public_ws_resync_policy_verified": True,
            "paper_gate_eligible": False,
        },
        "public_ws_runtime_state": {
            "verified_public_session_count": 8,
            "public_ws_replay_verified": True,
            "public_ws_resync_policy_verified": True,
            "required_channels_observed": True,
        },
        "blockers": [],
        "gate": {"paper_queue_write_allowed": False, "live_unlock_allowed": False},
    }


def _coverage_report(*, coverage_ok: bool, event_days: float, calendar_days: float, latency_ready: bool, queue_ready: bool) -> dict:
    return {
        "status": "complete_research_only" if coverage_ok else "ws_l2_capture_coverage_accumulating_research_only_history_insufficient",
        "decision": "coverage_ready" if coverage_ok else "continue_accumulating_public_ws_l2_history_before_true_scalping",
        "coverage_contract_satisfied": coverage_ok,
        "execution_latency_model_ready": latency_ready,
        "queue_model_ready": queue_ready,
        "blockers": [] if coverage_ok else ["coverage_short"],
        "coverage_totals": {
            "verified_public_session_count": 8,
            "total_capture_duration_seconds": 4000.0,
            "total_event_ledger_history_days": event_days,
            "calendar_span_days": calendar_days,
            "replay_sequence_ready_session_count": 8,
            "resync_policy_ready_session_count": 8,
            "actual_reconnect_or_gap_exercised_session_count": 6,
        },
        "validation": {
            "coverage_contract_satisfied": coverage_ok,
            "all_verified_sessions_have_replay_sequence_ready": True,
            "resync_policy_exercised": True,
            "required_channels_observed": True,
            "minimum_event_ledger_history_days_satisfied": event_days >= 30.0,
            "minimum_calendar_span_days_satisfied": calendar_days >= 30.0,
            "execution_latency_model_ready": latency_ready,
            "queue_model_ready": queue_ready,
        },
    }


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
