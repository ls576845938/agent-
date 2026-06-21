from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from scripts.build_btc_true_scalping_timestamp_aligned_l2_data_contract_report import (
    build_btc_true_scalping_timestamp_aligned_l2_data_contract_report,
)


SCHEMA = Path("schemas/btc_true_scalping_timestamp_aligned_l2_data_contract_report.schema.json")
REPORT = Path("artifacts/btc_scalping_readiness/latest/btc_true_scalping_timestamp_aligned_l2_data_contract_report.json")


def test_btc_true_scalping_timestamp_aligned_l2_data_contract_schema_valid() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    jsonschema.validate(payload, schema)


def test_current_btc_true_scalping_timestamp_aligned_l2_data_contract_keeps_scalping_locked() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    evidence = payload["current_evidence"]
    contract = payload["minimum_capture_contract"]
    gates = {gate["gate_id"]: gate for gate in payload["validation_gates"]}

    assert payload["status"] == "timestamp_aligned_l2_capture_required_research_only"
    assert payload["decision"] == "collect_timestamp_aligned_public_l2_tick_window_before_true_scalping_event_ledger"
    assert payload["contract_satisfied"] is False
    assert payload["event_ledger_feature_validation_allowed"] is False
    assert payload["true_scalping_allowed"] is False
    assert payload["candidate_generation_allowed"] is False
    assert payload["strategy_skeleton_generation_allowed"] is False
    assert payload["paper_or_live_unlock_allowed"] is False
    assert payload["guardrails"]["broker_calls_allowed"] is False
    assert payload["guardrails"]["private_endpoints_allowed"] is False
    assert payload["guardrails"]["order_endpoints_allowed"] is False
    assert evidence["sample_quality_status"] == "public_l2_sample_evidence_ready_research_only"
    assert evidence["feature_diagnostics_status"] == "l2_feature_diagnostics_ready_research_only_backtest_blocked"
    assert evidence["public_rest_only"] is True
    assert evidence["bounded_public_rest_sample_only"] is True
    assert evidence["timestamp_aligned_l2_history_available"] is False
    assert evidence["same_window_trade_book_alignment_available"] is False
    assert evidence["causal_event_ledger_join_allowed"] is False
    assert contract["minimum_research_capture_seconds"] >= 3600
    assert contract["minimum_event_ledger_history_days"] >= 30
    assert contract["minimum_book_depth_levels"] >= 50
    assert contract["private_endpoints_allowed"] is False
    assert contract["order_endpoints_allowed"] is False
    assert gates["public_source_boundary"]["satisfied"] is True
    assert gates["same_window_trade_book_alignment"]["satisfied"] is False
    assert gates["historical_event_ledger_coverage"]["satisfied"] is False
    assert gates["execution_latency_model_separated_from_rest_latency"]["satisfied"] is False
    assert "btc_same_window_public_trade_book_alignment_missing" in payload["blockers"]
    assert "btc_l2_alignment_manifest_missing" in payload["blockers"]


def test_timestamp_aligned_l2_data_contract_builder_records_fixture_requirements(tmp_path: Path) -> None:
    _write_source_reports(tmp_path)

    payload = build_btc_true_scalping_timestamp_aligned_l2_data_contract_report(
        repo_root=tmp_path,
        generated_at="2026-06-20T00:00:00Z",
    )

    evidence = payload["current_evidence"]
    datasets = {item["dataset_id"]: item for item in payload["required_datasets"]}
    assert payload["status"] == "timestamp_aligned_l2_capture_required_research_only"
    assert payload["selected_bundle_dir"] == "data/external/btc_perpetual/okx_swap/bundles/fixture"
    assert evidence["completed_sample_count"] == 5
    assert evidence["trade_row_count"] == 500
    assert evidence["book_level_row_count"] == 500
    assert evidence["joined_sample_count"] == 5
    assert evidence["overlaps_backtest_window"] is False
    assert evidence["timestamp_aligned_l2_history_available"] is False
    assert payload["contract_satisfied"] is False
    assert datasets["agg_trades_aligned"]["timestamp_alignment_required"] is True
    assert "monotonic_ns" in datasets["agg_trades_aligned"]["required_fields"]
    assert "spread_bps" in datasets["order_book_depth_aligned"]["required_fields"]
    assert "checksum_or_sequence_policy" in datasets["l2_alignment_manifest"]["required_fields"]
    assert "btc_timestamp_aligned_l2_history_missing_for_event_ledger_window" in payload["blockers"]
    assert payload["true_scalping_allowed"] is False


def test_timestamp_aligned_l2_data_contract_builder_blocks_missing_source_reports(tmp_path: Path) -> None:
    payload = build_btc_true_scalping_timestamp_aligned_l2_data_contract_report(
        repo_root=tmp_path,
        generated_at="2026-06-20T00:00:00Z",
    )

    assert payload["status"] == "timestamp_aligned_l2_contract_blocked_missing_source_evidence"
    assert "btc_l2_sample_capture_report_not_verified" in payload["blockers"]
    assert "btc_l2_sample_quality_not_ready" in payload["blockers"]
    assert "btc_l2_feature_diagnostics_not_ready" in payload["blockers"]
    assert payload["contract_satisfied"] is False
    assert payload["paper_or_live_unlock_allowed"] is False


def test_timestamp_aligned_l2_data_contract_schema_rejects_unlock() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    payload["true_scalping_allowed"] = True

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)


def _write_source_reports(root: Path) -> None:
    _write_json(
        root / "artifacts/btc_scalping_readiness/latest/btc_okx_l2_microstructure_sample_capture_report.json",
        {
            "status": "verified",
            "network_called": True,
            "public_rest_only": True,
            "private_endpoint_used": False,
            "order_endpoint_used": False,
            "selected_bundle_dir": "data/external/btc_perpetual/okx_swap/bundles/fixture",
        },
    )
    _write_json(
        root / "artifacts/btc_scalping_readiness/latest/btc_true_scalping_l2_sample_quality_report.json",
        {
            "status": "public_l2_sample_evidence_ready_research_only",
            "bounded_public_rest_sample_only": True,
            "selected_bundle_dir": "data/external/btc_perpetual/okx_swap/bundles/fixture",
            "sample_quality": {
                "completed_sample_count": 5,
                "trade_row_count": 500,
                "book_level_row_count": 500,
                "valid_top_of_book_snapshot_count": 5,
                "latency_sample_count": 10,
            },
        },
    )
    _write_json(
        root / "artifacts/btc_scalping_readiness/latest/btc_true_scalping_l2_feature_diagnostics_report.json",
        {
            "status": "l2_feature_diagnostics_ready_research_only_backtest_blocked",
            "selected_bundle_dir": "data/external/btc_perpetual/okx_swap/bundles/fixture",
            "feature_diagnostics": {
                "book_snapshot_count": 5,
                "trade_flow_sample_count": 5,
                "joined_sample_count": 5,
            },
            "feature_candidates": [
                {"feature_id": "spread_filter_bps"},
                {"feature_id": "depth_imbalance_top5"},
            ],
            "source_files": {
                "agg_trades_samples": {
                    "path": "data/external/btc_perpetual/okx_swap/bundles/fixture/agg_trades_samples.csv",
                    "exists": True,
                    "row_count": 500,
                },
                "order_book_depth_samples": {
                    "path": "data/external/btc_perpetual/okx_swap/bundles/fixture/order_book_depth_samples.csv",
                    "exists": True,
                    "row_count": 500,
                },
            },
            "historical_alignment": {
                "status": "not_timestamp_aligned_to_backtest",
                "sample_capture_start": "2026-06-20T00:00:00+00:00",
                "sample_capture_end": "2026-06-20T00:05:00+00:00",
                "backtest_start": "2025-05-12T00:00:00+00:00",
                "backtest_end": "2026-05-12T00:00:00+00:00",
                "overlaps_backtest_window": False,
                "timestamp_aligned_l2_history_available": False,
                "causal_event_ledger_join_allowed": False,
            },
            "blockers": [
                "btc_l2_features_bounded_sample_not_historical_l2",
                "btc_l2_feature_event_ledger_validation_blocked_without_timestamp_aligned_history",
            ],
        },
    )


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
