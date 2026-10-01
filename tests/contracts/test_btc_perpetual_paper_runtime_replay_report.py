from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from quant_crypto.application.btc_strategy_registry import (
    ATTACK_OBSERVER_CANDIDATE_ID,
    HIGH_YIELD_CANDIDATE_ID,
    btc_strategy_registry,
)
from quant_crypto.research.btc_perpetual_paper_runtime_replay import (
    build_btc_perpetual_paper_runtime_replay_drill_report,
    build_btc_perpetual_paper_runtime_replay_fixture_drill_report,
    build_btc_perpetual_paper_runtime_replay_report,
)


LONG_SHORT_TOP1_CANDIDATE_ID = btc_strategy_registry.get("long_short_donchian_top5").candidate_id


def test_perpetual_paper_runtime_replay_blocks_current_flat_without_unlocking(tmp_path: Path) -> None:
    paths = _write_fixture(tmp_path, exposure=0.0, evidence_blockers=[])

    report = build_btc_perpetual_paper_runtime_replay_report(
        repo_root=tmp_path,
        output_dir=Path("out"),
        config_path=paths["config"],
        long_short_observations_path=paths["long_short"],
        attack_observations_path=paths["attack"],
        high_yield_observations_path=paths["high_yield"],
        cost_model_report_path=paths["cost"],
        perpetual_evidence_report_path=paths["evidence"],
        generated_at_utc=datetime(2026, 7, 1, tzinfo=timezone.utc),
    )

    safety = json.loads((tmp_path / "out/btc_perpetual_paper_runtime_replay_safety_status.json").read_text(encoding="utf-8"))
    assert report["status"] == "pending_research_only"
    assert report["decision"] == "perpetual_paper_runtime_replay_current_gate_evidence_pending_no_paper_no_live"
    assert "btc_perpetual_paper_runtime_replay_no_theoretical_orders_current_flat" not in report["blockers"]
    assert "btc_perpetual_paper_runtime_replay_no_simulated_fills" not in report["blockers"]
    assert report["blockers"] == []
    assert report["summary"]["flat_heartbeat_count"] == 3
    assert report["summary"]["current_flat_heartbeat_healthy"] is True
    assert report["summary"]["trade_execution_evidence_available"] is False
    assert report["summary"]["liquidation_buffer_visible_in_replay"] is False
    assert report["summary"]["liquidation_buffer_evidence"]["simulated_fill_count"] == 0
    assert report["summary"]["trade_execution_evidence_pending_reason"] == "waiting_for_current_gate_eligible_non_flat_fill"
    assert report["summary"]["paper_runtime_health_status"] == "current_flat_heartbeat_healthy_waiting_for_trade_sample"
    assert report["summary"]["gate_eligible_current_capture_count"] == 0
    assert report["summary"]["paper_runtime_replay_ready"] is False
    assert report["summary"]["paper_runtime_gate_evidence"] is False
    assert report["summary"]["current_observe_only_gate_evidence_state"] == "pending"
    assert report["summary"]["current_observe_only_gate_evidence_passed"] is False
    assert report["summary"]["flat_no_gate_eligible_trade"] is True
    assert report["summary"]["current_non_flat_sample_capture_status"] == "flat_waiting_no_false_positive"
    assert report["summary"]["evidence_layers"]["fixture_capability_passed"] is False
    assert report["summary"]["evidence_layers"]["historical_drill_passed"] is False
    assert report["summary"]["evidence_layers"]["current_observe_only_gate_evidence_pending"] is True
    assert report["summary"]["current_non_flat_sample_capture_contract"]["flat_false_positive"] is False
    assert report["summary"]["current_non_flat_sample_capture_contract"]["requirements"]["theoretical_order_recorded"] is False
    assert (
        report["summary"]["current_non_flat_sample_capture_contract"]["depth_fill_mapping_status"]
        == "no_gate_eligible_fill"
    )
    assert report["summary"]["current_non_flat_sample_capture_contract"]["depth_fill_mapping_contract"]["current_state"] == "no_gate_eligible_fill"
    assert report["summary"]["current_non_flat_sample_capture_contract"]["depth_fill_mapping_contract"]["mapping_logic_failed"] is False
    assert report["summary"]["non_blocking_pending_conditions"] == [
        "flat_no_gate_eligible_trade",
        "waiting_for_current_gate_eligible_non_flat_fill"
    ]
    assert report["summary"]["observation_line_counts"]["high_yield_donchian_v2"] == 1
    assert report["summary"]["theoretical_order_count"] == 0
    assert report["summary"]["event_type_counts"] == {"flat_heartbeat": 3}
    assert report["summary"]["event_ledger_row_count"] == 3
    assert report["summary"]["order_ledger_row_count"] == 0
    assert report["summary"]["fill_ledger_row_count"] == 0
    assert report["summary"]["oms_session_unreconciled_count"] == 0
    assert report["summary"]["oms_session_reconciliation_status"] == "blocked"
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["live_unlock_allowed"] is False
    assert safety["order_endpoint_used"] is False
    assert safety["broker_access_allowed"] is False


def test_perpetual_paper_runtime_replay_simulates_fill_for_visible_perp_signal(tmp_path: Path) -> None:
    paths = _write_fixture(tmp_path, exposure=1.0, evidence_blockers=[])

    report = build_btc_perpetual_paper_runtime_replay_report(
        repo_root=tmp_path,
        output_dir=Path("out"),
        config_path=paths["config"],
        long_short_observations_path=paths["long_short"],
        attack_observations_path=paths["attack"],
        high_yield_observations_path=paths["high_yield"],
        cost_model_report_path=paths["cost"],
        perpetual_evidence_report_path=paths["evidence"],
        generated_at_utc=datetime(2026, 7, 1, tzinfo=timezone.utc),
    )

    assert report["status"] == "complete_research_only"
    assert report["decision"] == "paper_runtime_replay_ready_for_manual_review"
    assert report["summary"]["theoretical_order_count"] == 1
    assert report["summary"]["simulated_fill_count"] == 1
    assert report["summary"]["gate_eligible_current_capture_count"] == 1
    assert report["summary"]["current_non_flat_sample_capture_status"] == "gate_eligible_non_flat_capture_ready"
    capture = report["summary"]["current_non_flat_sample_capture_contract"]
    assert capture["requirements"] == {
        "flat_does_not_create_order_or_fill": True,
        "theoretical_order_recorded": True,
        "risk_decision_recorded": True,
        "simulated_fill_recorded": True,
        "oms_lifecycle_recorded": True,
        "funding_cashflow_recorded": True,
        "mark_index_price_recorded": True,
        "liquidation_buffer_recorded": True,
        "depth_fill_mapping_ready_for_downstream": True,
    }
    assert capture["contract_blockers"] == []
    assert capture["depth_fill_mapping_contract"]["rows_exported"] is True
    assert capture["depth_fill_mapping_contract"]["current_state"] == "current_gate_fill_mapped"
    assert capture["depth_fill_mapping_contract"]["no_gate_eligible_fill"] is False
    assert capture["depth_fill_mapping_contract"]["mapping_logic_failed"] is False
    assert "fill_time" in capture["depth_fill_mapping_contract"]["required_row_fields"]
    assert capture["depth_fill_mapping_status"] == "downstream_fill_mapping_can_consume_current_gate_eligible_fill"
    assert report["summary"]["fill_ledger_event_count"] == 1
    assert report["summary"]["funding_cashflow_event_count"] == 1
    assert report["summary"]["order_ledger_row_count"] == 1
    assert report["summary"]["fill_ledger_row_count"] == 1
    assert report["summary"]["oms_session_reconciliation_status"] == "complete"
    assert report["summary"]["oms_session_unreconciled_count"] == 0
    assert report["summary"]["liquidation_buffer_visible_in_replay"] is True
    assert report["summary"]["liquidation_buffer_evidence"]["buffer_row_count"] == 1
    assert report["summary"]["liquidation_buffer_evidence"]["uses_mark_price_reference"] is True
    assert report["summary"]["fee_amount_total_usdt"] > 0
    assert report["blockers"] == []
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["live_unlock_allowed"] is False
    row = next(item for item in report["replay_rows"] if item["theoretical_order_created"])
    assert row["fill_time"] == "2026-06-29T00:00:00+00:00"
    assert row["risk_approved"] is True
    assert row["risk_decision"] == "approved"
    assert row["risk_decision_detail"]["risk_model_version"] == "btc_perp_liquidation_risk_v1"
    assert row["mark_price"] == 60000.0
    assert row["index_price"] == 60020.0
    assert row["liquidation_buffer_bps"] > 0
    assert row["target_exposure"] == 1.0
    assert row["actual_exposure"] < row["target_exposure"]
    assert row["requested_contracts"] > row["rounded_contracts"]
    assert row["rounded_contracts"] == 16.66
    assert row["quantity_btc"] == 0.1666
    assert row["sizing_status"] == "rounded_down_to_exchange_lot"
    assert row["sizing_remainder_notional_usdt"] > 0
    assert row["paper_runtime_gate_eligible"] is True
    assert row["venue"] == "OKX"
    assert row["venue_symbol"] == "BTC-USDT-SWAP"
    assert row["instrument_id"] == "BTC-USDT-SWAP"
    assert row["instrument_type"] == "SWAP"
    assert row["account_id"] == "observe_only_no_private_account"
    assert row["account_mode"] == "unknown_or_unattested"
    assert row["position_mode"] == "unknown_or_unattested"
    assert row["margin_mode"] == "unknown_or_unattested"
    assert row["margin_asset"] == "USDT"
    assert row["order_type"] == "market"
    assert row["time_in_force"] == "ioc"
    assert row["fee_side"] == "taker"
    assert row["paper_queue_write_allowed"] is False
    rows_header = _read_csv(tmp_path / "out/btc_perpetual_paper_runtime_replay_rows.csv")[0].keys()
    assert {
        "venue",
        "venue_symbol",
        "instrument_id",
        "instrument_type",
        "account_id",
        "account_mode",
        "position_mode",
        "margin_mode",
        "margin_asset",
        "order_type",
        "time_in_force",
        "fee_side",
        "mark_price",
        "index_price",
        "liquidation_price",
        "liquidation_buffer_bps",
        "risk_decision",
    }.issubset(set(rows_header))
    assert (tmp_path / "out/btc_perpetual_paper_runtime_replay_rows.csv").exists()
    assert (tmp_path / "out/btc_perpetual_paper_runtime_replay_event_ledger.csv").exists()
    assert (tmp_path / "out/btc_perpetual_paper_runtime_replay_order_ledger.csv").exists()
    assert (tmp_path / "out/btc_perpetual_paper_runtime_replay_fill_ledger.csv").exists()
    assert (tmp_path / "out/btc_perpetual_paper_runtime_replay_oms_session_reconciliation_report.json").exists()
    ledger_events = _read_event_types(tmp_path / "out/btc_perpetual_paper_runtime_replay_event_ledger.csv")
    assert {"order_intent_created", "risk_checked", "simulated_fill", "fee_cashflow", "funding_cashflow"}.issubset(
        set(ledger_events)
    )
    order_rows = _read_csv(tmp_path / "out/btc_perpetual_paper_runtime_replay_order_ledger.csv")
    fill_rows = _read_csv(tmp_path / "out/btc_perpetual_paper_runtime_replay_fill_ledger.csv")
    oms_reconciliation = json.loads(
        (tmp_path / "out/btc_perpetual_paper_runtime_replay_oms_session_reconciliation_report.json").read_text(
            encoding="utf-8"
        )
    )
    assert order_rows[0]["status"] == "reconciled"
    assert order_rows[0]["venue"] == "OKX"
    assert order_rows[0]["instrument_id"] == "BTC-USDT-SWAP"
    assert order_rows[0]["account_mode"] == "unknown_or_unattested"
    assert order_rows[0]["position_mode"] == "unknown_or_unattested"
    assert order_rows[0]["margin_mode"] == "unknown_or_unattested"
    assert order_rows[0]["order_type"] == "market"
    assert order_rows[0]["time_in_force"] == "ioc"
    assert order_rows[0]["fee_side"] == "taker"
    assert order_rows[0]["arrival_price"] == "60000.0"
    assert order_rows[0]["benchmark_price"] == "60020.0"
    assert order_rows[0]["risk_decision"] == "approved"
    assert fill_rows[0]["client_order_id"] == order_rows[0]["client_order_id"]
    assert fill_rows[0]["venue"] == "OKX"
    assert fill_rows[0]["instrument_id"] == "BTC-USDT-SWAP"
    assert fill_rows[0]["account_mode"] == "unknown_or_unattested"
    assert fill_rows[0]["position_mode"] == "unknown_or_unattested"
    assert fill_rows[0]["margin_mode"] == "unknown_or_unattested"
    assert fill_rows[0]["side"] == "buy"
    assert fill_rows[0]["fee_side"] == "taker"
    assert fill_rows[0]["arrival_price"] == "60000.0"
    assert fill_rows[0]["fill_price"] == "60000.0"
    assert fill_rows[0]["benchmark_price"] == "60020.0"
    assert fill_rows[0]["slippage_bps"] == "0.0"
    assert fill_rows[0]["implementation_shortfall"] == "0.0"
    assert fill_rows[0]["risk_decision"] == "approved"
    assert oms_reconciliation["status"] == "complete"
    assert oms_reconciliation["blockers"] == []


def test_perpetual_paper_runtime_replay_execution_evidence_blocker_triggers_circuit_breaker(tmp_path: Path) -> None:
    paths = _write_fixture(tmp_path, exposure=-1.0, evidence_blockers=["btc_perp_exec_depth_aware_slippage_history_verified"])

    report = build_btc_perpetual_paper_runtime_replay_report(
        repo_root=tmp_path,
        output_dir=Path("out"),
        config_path=paths["config"],
        long_short_observations_path=paths["long_short"],
        attack_observations_path=paths["attack"],
        high_yield_observations_path=paths["high_yield"],
        cost_model_report_path=paths["cost"],
        perpetual_evidence_report_path=paths["evidence"],
        generated_at_utc=datetime(2026, 7, 1, tzinfo=timezone.utc),
    )

    assert report["status"] == "incomplete_research_only"
    assert "btc_perpetual_paper_runtime_replay_execution_evidence_blocked" in report["blockers"]
    assert "paper_promotion_blocked_by_execution_evidence" in report["blockers"]
    assert report["summary"]["theoretical_order_count"] == 1
    assert report["summary"]["simulated_fill_count"] == 1
    assert report["summary"]["gate_eligible_current_capture_count"] == 1
    assert report["summary"]["current_non_flat_sample_capture_status"] == "gate_eligible_non_flat_capture_ready"
    assert report["summary"]["order_ledger_row_count"] == 1
    assert report["summary"]["fill_ledger_row_count"] == 1
    assert report["summary"]["liquidation_buffer_visible_in_replay"] is True
    row = next(item for item in report["replay_rows"] if item["theoretical_order_created"])
    assert row["risk_decision"] == "approved"
    assert row["paper_runtime_gate_eligible"] is True
    assert row["paper_promotion_blockers"] == ["btc_perp_exec_depth_aware_slippage_history_verified"]
    assert row["capture_only_warning_flags"] == ["current_sample_captured_but_paper_promotion_remains_blocked"]
    assert row["mark_price"] > 0
    assert row["index_price"] > 0
    assert row["liquidation_buffer_bps"] > 0
    assert report["summary"]["oms_session_unreconciled_count"] == 0
    assert report["summary"]["circuit_breaker_count"] == 1
    assert report["summary"]["event_type_counts"]["circuit_breaker_triggered"] == 1
    assert report["summary"]["event_type_counts"]["simulated_fill"] == 1
    assert report["gate"]["paper_queue_write_allowed"] is False


def test_perpetual_paper_runtime_replay_fails_closed_when_index_price_missing(tmp_path: Path) -> None:
    paths = _write_fixture(tmp_path, exposure=1.0, evidence_blockers=[])
    _write_csv(
        tmp_path / "data/external/btc_perpetual/okx_swap/bundles/current/premium_index_klines_1h.csv",
        ["timestamp", "event_time", "available_time", "mark_close", "index_close"],
        [["2026-06-28T23:00:00Z", "2026-06-28T23:00:00Z", "2026-06-29T00:00:00Z", "60000", ""]],
    )

    report = build_btc_perpetual_paper_runtime_replay_report(
        repo_root=tmp_path,
        output_dir=Path("out"),
        config_path=paths["config"],
        long_short_observations_path=paths["long_short"],
        attack_observations_path=paths["attack"],
        high_yield_observations_path=paths["high_yield"],
        cost_model_report_path=paths["cost"],
        perpetual_evidence_report_path=paths["evidence"],
        generated_at_utc=datetime(2026, 7, 1, tzinfo=timezone.utc),
    )

    row = next(item for item in report["replay_rows"] if item["theoretical_order_created"])
    assert report["status"] == "incomplete_research_only"
    assert "btc_index_price_missing" in row["risk_blockers"]
    assert "btc_index_price_missing" in report["blockers"]
    assert "btc_perpetual_paper_runtime_replay_liquidation_risk_fields_missing" in report["blockers"]
    assert row["risk_decision"] == "rejected"
    assert row["mark_price"] > 0
    assert row["index_price"] == 0.0
    assert row["liquidation_buffer_bps"] > 0
    assert report["summary"]["liquidation_buffer_visible_in_replay"] is False
    assert report["summary"]["liquidation_buffer_evidence"]["missing_index_price_count"] == 1
    assert report["gate"]["paper_queue_write_allowed"] is False


def test_perpetual_paper_runtime_replay_simulates_high_yield_v2_observation(tmp_path: Path) -> None:
    paths = _write_fixture(tmp_path, exposure=0.0, high_yield_exposure=2.5, evidence_blockers=[])

    report = build_btc_perpetual_paper_runtime_replay_report(
        repo_root=tmp_path,
        output_dir=Path("out"),
        config_path=paths["config"],
        long_short_observations_path=paths["long_short"],
        attack_observations_path=paths["attack"],
        high_yield_observations_path=paths["high_yield"],
        cost_model_report_path=paths["cost"],
        perpetual_evidence_report_path=paths["evidence"],
        generated_at_utc=datetime(2026, 7, 1, tzinfo=timezone.utc),
    )

    assert report["status"] == "complete_research_only"
    assert report["summary"]["observation_line_counts"]["high_yield_donchian_v2"] == 1
    assert report["summary"]["theoretical_order_count"] == 1
    assert report["summary"]["simulated_fill_count"] == 1
    assert report["summary"]["fill_ledger_event_count"] == 1
    row = next(item for item in report["replay_rows"] if item["strategy_line"] == "high_yield_donchian_v2")
    assert row["side"] == "long"
    assert row["target_exposure"] == 2.5
    assert row["simulated_fill_created"] is True
    assert row["paper_queue_write_allowed"] is False
    assert report["gate"]["live_unlock_allowed"] is False


def test_perpetual_paper_runtime_replay_drill_uses_historical_bar_replay_without_gate_unlock(tmp_path: Path) -> None:
    paths = _write_fixture(
        tmp_path,
        exposure=0.0,
        high_yield_exposure=0.0,
        evidence_blockers=["btc_perp_exec_depth_aware_slippage_history_verified"],
    )

    report = build_btc_perpetual_paper_runtime_replay_drill_report(
        repo_root=tmp_path,
        output_dir=Path("out"),
        config_path=paths["config"],
        bar_replay_rows_path=paths["bar_replay"],
        cost_model_report_path=paths["cost"],
        perpetual_evidence_report_path=paths["evidence"],
        sample_per_line=2,
        generated_at_utc=datetime(2026, 7, 1, tzinfo=timezone.utc),
    )

    assert report["status"] == "complete_research_only"
    assert report["summary"]["observation_line_counts"] == {
        "high_octane_attack_sleeve_v2": 1,
        "high_yield_donchian_v2": 1,
        "long_short_donchian_top5": 1,
    }
    assert report["summary"]["theoretical_order_count"] == 3
    assert report["summary"]["simulated_fill_count"] == 3
    assert report["summary"]["risk_approved_count"] == 3
    assert report["summary"]["liquidation_buffer_visible_in_replay"] is True
    assert report["summary"]["liquidation_buffer_evidence"]["buffer_row_count"] == 3
    assert report["summary"]["liquidation_buffer_evidence"]["uses_mark_price_reference"] is True
    assert report["summary"]["event_ledger_row_count"] == 15
    assert report["summary"]["order_ledger_row_count"] == 3
    assert report["summary"]["fill_ledger_row_count"] == 3
    assert report["summary"]["oms_session_reconciliation_status"] == "complete"
    assert report["summary"]["oms_session_unreconciled_count"] == 0
    assert report["summary"]["event_type_counts"]["simulated_fill"] == 3
    assert report["summary"]["event_type_counts"]["funding_cashflow"] == 3
    assert report["summary"]["paper_runtime_gate_evidence"] is False
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["live_unlock_allowed"] is False
    assert "current_execution_evidence_blockers_intentionally_ignored_for_diagnostic_drill" in report["warnings"]
    assert all(row["diagnostic_drill_only"] is True for row in report["replay_rows"])
    assert all(row["paper_runtime_gate_eligible"] is False for row in report["replay_rows"])
    assert (tmp_path / "out/btc_perpetual_paper_runtime_replay_drill_rows.csv").exists()
    assert (tmp_path / "out/btc_perpetual_paper_runtime_replay_drill_event_ledger.csv").exists()
    assert (tmp_path / "out/btc_perpetual_paper_runtime_replay_drill_order_ledger.csv").exists()
    assert (tmp_path / "out/btc_perpetual_paper_runtime_replay_drill_fill_ledger.csv").exists()
    assert (tmp_path / "out/btc_perpetual_paper_runtime_replay_drill_oms_session_reconciliation_report.json").exists()


def test_perpetual_paper_runtime_replay_fixture_drill_generates_full_chain_without_gate_unlock(
    tmp_path: Path,
) -> None:
    report = build_btc_perpetual_paper_runtime_replay_fixture_drill_report(
        repo_root=tmp_path,
        output_dir=Path("out"),
        generated_at_utc=datetime(2026, 7, 1, tzinfo=timezone.utc),
    )

    safety = json.loads(
        (tmp_path / "out/btc_perpetual_paper_runtime_replay_fixture_drill_safety_status.json").read_text(
            encoding="utf-8"
        )
    )
    assert report["status"] == "complete_research_only"
    assert report["decision"] == "perpetual_paper_runtime_replay_fixture_drill_complete_not_gate_evidence_no_paper_no_live"
    assert report["summary"]["deterministic_fixture_drill"] is True
    assert report["summary"]["fixture_scenario_count"] == 7
    assert report["summary"]["theoretical_order_count"] == 7
    assert report["summary"]["simulated_fill_count"] == 5
    assert report["summary"]["fill_ledger_event_count"] == 5
    assert report["summary"]["funding_cashflow_event_count"] == 5
    assert report["summary"]["order_ledger_row_count"] == 7
    assert report["summary"]["fill_ledger_row_count"] == 5
    assert report["summary"]["oms_session_reconciliation_status"] == "complete"
    assert report["summary"]["oms_session_unreconciled_count"] == 0
    coverage = report["summary"]["chaos_drill_coverage"]
    assert coverage["scope"] == "diagnostic_fixture_only_not_current_gate_evidence"
    assert coverage["all_required_checks_passed"] is True
    for key in [
        "partial_fill",
        "cancel",
        "reject",
        "retry",
        "reduce_only",
        "cancel_only",
        "funding_cashflow",
        "liquidation_buffer",
        "ws_gapfill_replay",
        "oms_reconciliation",
    ]:
        assert coverage["required_checks"][key] is True
    lifecycle_counts = coverage["lifecycle_status_counts"]
    assert lifecycle_counts["partially_filled"] >= 1
    assert lifecycle_counts["cancel_requested"] >= 1
    assert lifecycle_counts["cancelled"] >= 1
    assert lifecycle_counts["rejected"] >= 1
    assert lifecycle_counts["unknown"] >= 1
    assert report["summary"]["mark_index_price_visible"] is True
    assert report["summary"]["liquidation_buffer_visible_in_replay"] is True
    assert report["summary"]["liquidation_buffer_evidence"]["buffer_row_count"] == 7
    assert report["summary"]["paper_runtime_gate_evidence"] is False
    assert report["summary"]["paper_runtime_fixture_drill_ready"] is True
    assert report["summary"]["evidence_layers"]["fixture_capability_passed"] is True
    assert report["summary"]["evidence_layers"]["historical_drill_passed"] is False
    assert report["summary"]["evidence_layers"]["fixture_or_drill_can_clear_paper_gate"] is False
    assert report["blockers"] == []
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["live_unlock_allowed"] is False
    assert safety["paper_runtime_fixture_drill_ready"] is True
    assert safety["paper_runtime_gate_evidence"] is False
    assert safety["paper_queue_write_allowed"] is False
    assert safety["order_endpoint_used"] is False
    assert safety["broker_access_allowed"] is False
    assert all(row["theoretical_order_created"] is True for row in report["replay_rows"])
    assert any(row["fixture_lifecycle_scenario"] == "partial_cancel" for row in report["replay_rows"])
    assert any(row["fixture_lifecycle_scenario"] == "exchange_reject" for row in report["replay_rows"])
    assert any(row["fixture_lifecycle_scenario"] == "submit_unknown_retry_fill" for row in report["replay_rows"])
    assert any(row["cancel_only_mode"] is True for row in report["replay_rows"])
    assert any(row["reduce_only"] is True for row in report["replay_rows"])
    assert any(row["ws_sequence_gap_detected"] is True for row in report["replay_rows"])
    assert sum(1 for row in report["replay_rows"] if row["simulated_fill_created"] is True) == 5
    assert all(row["mark_price"] > 0 for row in report["replay_rows"])
    assert all(row["index_price"] > 0 for row in report["replay_rows"])
    assert all(row["liquidation_buffer_bps"] > 0 for row in report["replay_rows"])
    assert all(row["paper_runtime_gate_eligible"] is False for row in report["replay_rows"])
    assert all(row["deterministic_fixture_drill_only"] is True for row in report["replay_rows"])
    ledger_events = _read_event_types(tmp_path / "out/btc_perpetual_paper_runtime_replay_fixture_drill_event_ledger.csv")
    assert {
        "order_intent_created",
        "risk_checked",
        "simulated_fill",
        "fee_cashflow",
        "funding_cashflow",
        "reduce_only_intent_validated",
        "cancel_only_guard_checked",
        "retry_state_checked",
        "ws_sequence_gap_detected",
        "ws_gapfill_replay_completed",
    }.issubset(set(ledger_events))
    assert (tmp_path / "out/btc_perpetual_paper_runtime_replay_fixture_drill_rows.csv").exists()
    fixture_rows = _read_csv(tmp_path / "out/btc_perpetual_paper_runtime_replay_fixture_drill_rows.csv")
    assert len(fixture_rows) == 7
    assert {
        "mark_price",
        "index_price",
        "liquidation_price",
        "liquidation_buffer_bps",
        "risk_decision",
        "venue",
        "venue_symbol",
        "instrument_id",
        "instrument_type",
        "account_id",
        "account_mode",
        "position_mode",
        "margin_mode",
        "margin_asset",
        "order_type",
        "time_in_force",
        "fee_side",
        "fixture_lifecycle_scenario",
        "reduce_only",
        "cancel_only_mode",
        "retry_required",
        "ws_sequence_gap_detected",
        "gapfill_replay_applied",
    }.issubset(fixture_rows[0].keys())
    assert all(float(row["mark_price"]) > 0 for row in fixture_rows)
    assert all(float(row["index_price"]) > 0 for row in fixture_rows)
    assert all(row["liquidation_price"] not in {"", None} for row in fixture_rows)
    assert all(float(row["liquidation_buffer_bps"]) > 0 for row in fixture_rows)
    assert all(row["risk_decision"] for row in fixture_rows)
    assert (tmp_path / "out/btc_perpetual_paper_runtime_replay_fixture_drill_summary_cn.md").exists()
    assert (tmp_path / "out/btc_perpetual_paper_runtime_replay_fixture_drill_order_ledger.csv").exists()
    assert (tmp_path / "out/btc_perpetual_paper_runtime_replay_fixture_drill_fill_ledger.csv").exists()
    assert (
        tmp_path / "out/btc_perpetual_paper_runtime_replay_fixture_drill_oms_session_reconciliation_report.json"
    ).exists()


def _write_fixture(
    tmp_path: Path,
    *,
    exposure: float,
    evidence_blockers: list[str],
    high_yield_exposure: float = 0.0,
) -> dict[str, Path]:
    root = tmp_path / "data/external/btc_perpetual/okx_swap"
    bundle = root / "bundles/current"
    bundle.mkdir(parents=True, exist_ok=True)
    config = tmp_path / "configs/data/btc_perpetual_sources.yaml"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(
        "\n".join(
            [
                "providers:",
                "  okx_swap:",
                "    enabled: true",
                f"    root: {root.relative_to(tmp_path).as_posix()}",
                "    selected_bundle_id: current",
                "    allow_network: false",
                "    allow_private_endpoints: false",
                "    allow_order_endpoints: false",
                "selected_provider: okx_swap",
            ]
        ),
        encoding="utf-8",
    )
    _write_csv(
        bundle / "klines_1h.csv",
        ["timestamp", "event_time", "available_time", "close"],
        [
            ["2026-06-28T23:00:00Z", "2026-06-28T23:00:00Z", "2026-06-29T00:00:00Z", "60000"],
            ["2026-06-29T00:00:00Z", "2026-06-29T00:00:00Z", "2026-06-29T01:00:00Z", "60100"],
        ],
    )
    _write_csv(
        bundle / "mark_price_klines_1h.csv",
        ["timestamp", "event_time", "available_time", "close"],
        [
            ["2026-06-28T23:00:00Z", "2026-06-28T23:00:00Z", "2026-06-29T00:00:00Z", "60000"],
            ["2026-06-29T00:00:00Z", "2026-06-29T00:00:00Z", "2026-06-29T01:00:00Z", "60100"],
        ],
    )
    _write_csv(
        bundle / "premium_index_klines_1h.csv",
        ["timestamp", "event_time", "available_time", "mark_close", "index_close"],
        [
            ["2026-06-28T23:00:00Z", "2026-06-28T23:00:00Z", "2026-06-29T00:00:00Z", "60000", "60020"],
            ["2026-06-29T00:00:00Z", "2026-06-29T00:00:00Z", "2026-06-29T01:00:00Z", "60100", "60120"],
        ],
    )
    _write_csv(
        bundle / "funding_rate.csv",
        ["timestamp", "event_time", "available_time", "fundingRate", "markPrice"],
        [["2026-06-29T00:00:00Z", "2026-06-29T00:00:00Z", "2026-06-29T00:00:00Z", "0.0001", "60000"]],
    )
    (bundle / "exchange_info.json").write_text(
        json.dumps(
            {
                "private_endpoint_used": False,
                "order_endpoint_used": False,
                "api_key_used": False,
                "raw_symbol_info": {
                    "instId": "BTC-USDT-SWAP",
                    "instType": "SWAP",
                    "state": "live",
                    "ctVal": "0.01",
                    "tickSz": "0.1",
                    "lotSz": "0.01",
                    "minSz": "0.01",
                    "maxMktSz": "35000",
                },
            }
        ),
        encoding="utf-8",
    )
    long_short = tmp_path / "obs/long_short.csv"
    _write_csv(
        long_short,
        ["candidate_id", "decision_time", "rank", "decision_signal", "theoretical_exposure"],
        [
            [
                LONG_SHORT_TOP1_CANDIDATE_ID,
                "2026-06-28T23:59:59.999000+00:00",
                "1",
                json.dumps({"side": "long" if exposure > 0 else ("short" if exposure < 0 else "flat"), "value": exposure}),
                json.dumps({"side": "long" if exposure > 0 else ("short" if exposure < 0 else "flat"), "value": exposure}),
            ]
        ],
    )
    attack = tmp_path / "obs/attack.csv"
    _write_csv(
        attack,
        ["top_scenario_id", "decision_time", "daily_signal.side", "theoretical_sleeve_exposure.gross_leverage_sum"],
        [[ATTACK_OBSERVER_CANDIDATE_ID, "2026-06-28T23:59:59.999000+00:00", "flat", "0"]],
    )
    high_yield = tmp_path / "obs/high_yield.csv"
    _write_csv(
        high_yield,
        [
            "decision_time",
            "theoretical_exposure",
            "theoretical_side",
            "variant_id",
            "paper_queue_write_allowed",
            "live_unlock_allowed",
            "paper_candidate_created",
            "strategy_skeleton_generated",
        ],
        [
            [
                "2026-06-28T23:59:59.999000+00:00",
                str(high_yield_exposure),
                "long" if high_yield_exposure > 0 else ("short" if high_yield_exposure < 0 else "flat"),
                HIGH_YIELD_CANDIDATE_ID,
                "False",
                "False",
                "False",
                "False",
            ]
        ],
    )
    cost = tmp_path / "cost.json"
    cost.write_text(json.dumps({"fee_model": {"taker_fee_bps": 5.0}}), encoding="utf-8")
    evidence = tmp_path / "evidence.json"
    evidence.write_text(json.dumps({"status": "complete_research_only", "blockers": evidence_blockers}), encoding="utf-8")
    bar_replay = tmp_path / "obs/bar_replay.csv"
    _write_csv(
        bar_replay,
        [
            "line",
            "candidate_id",
            "rank",
            "decision_time",
            "raw_signal",
            "current_bar_exposure",
            "next_bar_exposure",
            "model_boundary_flag",
            "execution_replay_required_before_paper",
        ],
        [
            [
                "long_short_top5",
                "candidate_a",
                "1",
                "2026-06-28T23:59:59.999000+00:00",
                "1.0",
                "0.0",
                "1.0",
                "False",
                "False",
            ],
            [
                "high_octane_v2",
                "attack_a",
                "",
                "2026-06-28T23:59:59.999000+00:00",
                "-1.0",
                "-1.0",
                "",
                "True",
                "True",
            ],
            [
                "high_yield_v2",
                "hy_a",
                "",
                "2026-06-28T23:59:59.999000+00:00",
                "2.5",
                "0.0",
                "2.5",
                "True",
                "True",
            ],
        ],
    )
    return {
        "config": config,
        "long_short": long_short,
        "attack": attack,
        "high_yield": high_yield,
        "bar_replay": bar_replay,
        "cost": cost,
        "evidence": evidence,
    }


def _write_csv(path: Path, headers: list[str], rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        writer.writerows(rows)


def _read_event_types(path: Path) -> list[str]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return [row["event_type"] for row in csv.DictReader(handle)]


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]
