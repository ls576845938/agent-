from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from scripts.build_btc_true_scalping_l2_aligned_capture_quality_report import (
    build_btc_true_scalping_l2_aligned_capture_quality_report,
)


SCHEMA = Path("schemas/btc_true_scalping_l2_aligned_capture_quality_report.schema.json")
REPORT = Path("artifacts/btc_scalping_readiness/latest/btc_true_scalping_l2_aligned_capture_quality_report.json")


def test_btc_true_scalping_l2_aligned_capture_quality_schema_valid() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    jsonschema.validate(payload, schema)


def test_current_btc_true_scalping_l2_aligned_capture_quality_keeps_scalping_locked() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    validation = payload["validation"]

    assert payload["status"] in {
        "aligned_l2_capture_format_verified_research_only_history_insufficient",
        "aligned_l2_capture_missing_or_invalid_research_only",
    }
    assert payload["decision"] == "continue_public_l2_capture_until_research_and_event_history_thresholds_are_met"
    assert payload["contract_satisfied"] is False
    assert payload["event_ledger_feature_validation_allowed"] is False
    assert payload["true_scalping_allowed"] is False
    assert payload["candidate_generation_allowed"] is False
    assert payload["strategy_skeleton_generation_allowed"] is False
    assert payload["paper_or_live_unlock_allowed"] is False
    assert validation["execution_latency_model_ready"] is False
    assert validation["queue_model_ready"] is False
    assert payload["guardrails"]["broker_calls_allowed"] is False
    assert payload["guardrails"]["private_endpoints_allowed"] is False
    assert payload["guardrails"]["order_endpoints_allowed"] is False
    assert "btc_execution_latency_model_missing_rest_latency_is_not_execution_latency" in payload["blockers"]
    assert "btc_queue_model_missing_visible_depth_is_proxy_only" in payload["blockers"]


def test_l2_aligned_capture_quality_builder_accepts_format_preflight_but_blocks_history(tmp_path: Path) -> None:
    _write_fixture_contract_and_capture(tmp_path)
    _write_aligned_capture_files(tmp_path)

    payload = build_btc_true_scalping_l2_aligned_capture_quality_report(
        repo_root=tmp_path,
        generated_at="2026-06-20T00:00:00Z",
    )

    validation = payload["validation"]
    alignment = payload["alignment_quality"]
    assert payload["status"] == "aligned_l2_capture_format_verified_research_only_history_insufficient"
    assert payload["format_contract_satisfied"] is True
    assert payload["contract_satisfied"] is False
    assert validation["files_ready"] is True
    assert validation["public_source_boundary_satisfied"] is True
    assert validation["same_window_trade_book_alignment_satisfied"] is True
    assert validation["spread_slippage_queue_replay_inputs_partial"] is True
    assert validation["minimum_research_capture_seconds_satisfied"] is False
    assert validation["minimum_event_ledger_history_days_satisfied"] is False
    assert alignment["same_capture_sequence_count"] == 2
    assert alignment["aligned_sequence_count"] == 2
    assert alignment["max_book_level"] == 50
    assert "btc_aligned_l2_research_capture_duration_below_contract" in payload["blockers"]
    assert "btc_timestamp_aligned_l2_history_missing_for_event_ledger_window" in payload["blockers"]
    assert payload["true_scalping_allowed"] is False


def test_l2_aligned_capture_quality_builder_blocks_missing_files(tmp_path: Path) -> None:
    _write_fixture_contract_and_capture(tmp_path)

    payload = build_btc_true_scalping_l2_aligned_capture_quality_report(
        repo_root=tmp_path,
        generated_at="2026-06-20T00:00:00Z",
    )

    assert payload["status"] == "aligned_l2_capture_missing_or_invalid_research_only"
    assert payload["format_contract_satisfied"] is False
    assert "btc_agg_trades_aligned_missing" in payload["blockers"]
    assert "btc_order_book_depth_aligned_missing" in payload["blockers"]
    assert "btc_l2_alignment_manifest_missing" in payload["blockers"]
    assert payload["paper_or_live_unlock_allowed"] is False


def test_l2_aligned_capture_quality_schema_rejects_unlock() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    payload["event_ledger_feature_validation_allowed"] = True

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)


def _write_fixture_contract_and_capture(root: Path) -> None:
    _write_json(
        root / "artifacts/btc_scalping_readiness/latest/btc_true_scalping_timestamp_aligned_l2_data_contract_report.json",
        {
            "status": "timestamp_aligned_l2_capture_required_research_only",
            "selected_bundle_dir": "data/external/btc_perpetual/okx_swap/bundles/fixture",
            "minimum_capture_contract": {
                "minimum_research_capture_seconds": 3600,
                "minimum_event_ledger_history_days": 30,
                "minimum_book_depth_levels": 50,
                "required_alignment_max_clock_skew_ms": 250,
            },
        },
    )
    _write_json(
        root / "artifacts/btc_scalping_readiness/latest/btc_okx_timestamp_aligned_l2_capture_report.json",
        {
            "status": "verified_preflight",
            "selected_bundle_dir": "data/external/btc_perpetual/okx_swap/bundles/fixture",
            "private_endpoint_used": False,
            "order_endpoint_used": False,
        },
    )


def _write_aligned_capture_files(root: Path) -> None:
    bundle = root / "data/external/btc_perpetual/okx_swap/bundles/fixture"
    _write_text(
        bundle / "agg_trades_aligned.csv",
        "\n".join(
            [
                "capture_sequence,exchange_ts,exchange_ts_ms,local_receive_ts,monotonic_ns,venue_symbol,symbol,trade_id,price,size,side,source_record_id",
                "1,2026-06-20T00:00:00Z,1781960000000,2026-06-20T00:00:00Z,1000,BTC-USDT-SWAP,BTCUSDT,1,100.0,0.1,buy,t1",
                "2,2026-06-20T00:00:01Z,1781960001000,2026-06-20T00:00:01Z,2000,BTC-USDT-SWAP,BTCUSDT,2,100.1,0.2,sell,t2",
            ]
        )
        + "\n",
    )
    book_rows = [
        "capture_sequence,exchange_ts,exchange_ts_ms,local_receive_ts,monotonic_ns,venue_symbol,symbol,side,level,price,size,best_bid,best_ask,spread_bps,bid_depth_notional,ask_depth_notional,liquidation_orders,order_count,source_record_id"
    ]
    for sequence, receive_ts, monotonic_ns in [(1, "2026-06-20T00:00:00.100Z", 1100), (2, "2026-06-20T00:00:01.100Z", 2100)]:
        for level in range(1, 51):
            book_rows.append(
                f"{sequence},2026-06-20T00:00:0{sequence - 1}Z,1781960000{sequence - 1}00,{receive_ts},{monotonic_ns},BTC-USDT-SWAP,BTCUSDT,bid,{level},{100 - level * 0.1},1.0,99.9,100.1,20.0,5000,6000,0,1,b{sequence}-{level}"
            )
            book_rows.append(
                f"{sequence},2026-06-20T00:00:0{sequence - 1}Z,1781960000{sequence - 1}00,{receive_ts},{monotonic_ns},BTC-USDT-SWAP,BTCUSDT,ask,{level},{100 + level * 0.1},1.0,99.9,100.1,20.0,5000,6000,0,1,a{sequence}-{level}"
            )
    _write_text(bundle / "order_book_depth_aligned.csv", "\n".join(book_rows) + "\n")
    _write_json(
        bundle / "l2_alignment_manifest.json",
        {
            "data_version": "fixture",
            "capture_start": "2026-06-20T00:00:00Z",
            "capture_end": "2026-06-20T00:00:02Z",
            "capture_duration_seconds": 2.0,
            "venue_symbol": "BTC-USDT-SWAP",
            "public_channels": ["GET /api/v5/market/history-trades", "GET /api/v5/market/books"],
            "public_rest_only": True,
            "private_endpoint_used": False,
            "order_endpoint_used": False,
            "broker_calls_used": False,
            "clock_source": "system_utc_and_python_monotonic_ns",
            "gap_count": 0,
            "checksum_or_sequence_policy": "rest_snapshot_no_exchange_sequence_checksum_available_capture_sequence_recorded",
        },
    )


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_text(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding="utf-8")
