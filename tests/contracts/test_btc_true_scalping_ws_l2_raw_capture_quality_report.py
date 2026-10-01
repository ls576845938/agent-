from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from scripts.build_btc_true_scalping_ws_l2_raw_capture_quality_report import (
    build_btc_true_scalping_ws_l2_raw_capture_quality_report,
)


SCHEMA = Path("schemas/btc_true_scalping_ws_l2_raw_capture_quality_report.schema.json")
REPORT = Path("artifacts/btc_scalping_readiness/latest/btc_true_scalping_ws_l2_raw_capture_quality_report.json")


def test_btc_true_scalping_ws_l2_raw_capture_quality_schema_valid() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    jsonschema.validate(payload, schema)


def test_current_btc_true_scalping_ws_l2_raw_capture_quality_keeps_scalping_locked() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    validation = payload["validation"]

    assert payload["status"] in {
        "ws_l2_raw_capture_format_verified_research_only_history_insufficient",
        "ws_l2_raw_capture_missing_or_invalid_research_only",
    }
    assert (
        payload["decision"]
        == "continue_public_ws_l2_capture_then_build_order_book_replay_and_resync_policy_before_true_scalping"
    )
    assert payload["contract_satisfied"] is False
    assert payload["event_ledger_feature_validation_allowed"] is False
    assert payload["true_scalping_allowed"] is False
    assert payload["candidate_generation_allowed"] is False
    assert payload["strategy_skeleton_generation_allowed"] is False
    assert payload["paper_or_live_unlock_allowed"] is False
    assert validation["order_book_replay_ready"] is False
    assert validation["execution_latency_model_ready"] is False
    assert validation["queue_model_ready"] is False
    assert payload["guardrails"]["broker_calls_allowed"] is False
    assert payload["guardrails"]["private_endpoints_allowed"] is False
    assert payload["guardrails"]["order_endpoints_allowed"] is False
    assert "btc_ws_l2_order_book_replay_not_validated" in payload["blockers"]
    assert "btc_execution_latency_model_missing_ws_receive_latency_is_not_execution_latency" in payload["blockers"]


def test_ws_l2_raw_capture_quality_builder_accepts_format_but_blocks_replay_and_history(tmp_path: Path) -> None:
    _write_ws_fixture(tmp_path)

    payload = build_btc_true_scalping_ws_l2_raw_capture_quality_report(
        repo_root=tmp_path,
        generated_at="2026-06-20T00:00:00Z",
    )

    validation = payload["validation"]
    quality = payload["capture_quality"]
    assert payload["status"] == "ws_l2_raw_capture_format_verified_research_only_history_insufficient"
    assert payload["format_contract_satisfied"] is True
    assert payload["contract_satisfied"] is False
    assert validation["files_ready"] is True
    assert validation["public_source_boundary_satisfied"] is True
    assert validation["required_channels_observed"] is True
    assert validation["raw_message_timestamps_ready"] is True
    assert validation["raw_l2_sequence_or_checksum_observed"] is True
    assert validation["raw_l2_capture_format_satisfied"] is True
    assert validation["minimum_research_capture_seconds_satisfied"] is False
    assert validation["minimum_event_ledger_history_days_satisfied"] is False
    assert quality["trade_message_count"] == 1
    assert quality["book_message_count"] == 1
    assert quality["exchange_ts_observed"] is True
    assert "btc_ws_l2_research_capture_duration_below_contract" in payload["blockers"]
    assert "btc_ws_l2_history_missing_for_event_ledger_window" in payload["blockers"]
    assert "btc_ws_l2_order_book_replay_not_validated" in payload["blockers"]
    assert payload["true_scalping_allowed"] is False


def test_ws_l2_raw_capture_quality_builder_blocks_missing_files(tmp_path: Path) -> None:
    payload = build_btc_true_scalping_ws_l2_raw_capture_quality_report(
        repo_root=tmp_path,
        generated_at="2026-06-20T00:00:00Z",
    )

    assert payload["status"] == "ws_l2_raw_capture_missing_or_invalid_research_only"
    assert payload["format_contract_satisfied"] is False
    assert "btc_ws_l2_raw_messages_missing" in payload["blockers"]
    assert "btc_ws_l2_raw_capture_manifest_missing" in payload["blockers"]
    assert payload["paper_or_live_unlock_allowed"] is False


def test_ws_l2_raw_capture_quality_schema_rejects_unlock() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    payload["true_scalping_allowed"] = True

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)


def _write_ws_fixture(root: Path) -> None:
    bundle = root / "data/external/btc_perpetual/okx_swap/bundles/fixture"
    _write_json(
        root / "artifacts/btc_scalping_readiness/latest/btc_okx_public_ws_l2_raw_capture_report.json",
        {
            "status": "verified_preflight",
            "selected_bundle_dir": "data/external/btc_perpetual/okx_swap/bundles/fixture",
            "private_endpoint_used": False,
            "order_endpoint_used": False,
            "blockers": [],
        },
    )
    rows = [
        {
            "capture_sequence": 1,
            "local_receive_ts": "2026-06-20T00:00:00Z",
            "monotonic_ns": 1000,
            "channel": "trades",
            "raw": json.dumps(
                {
                    "arg": {"channel": "trades", "instId": "BTC-USDT-SWAP"},
                    "data": [{"tradeId": "1", "px": "100.0", "sz": "0.1", "side": "buy", "ts": "1781960000000"}],
                }
            ),
        },
        {
            "capture_sequence": 2,
            "local_receive_ts": "2026-06-20T00:00:01Z",
            "monotonic_ns": 2000,
            "channel": "books",
            "raw": json.dumps(
                {
                    "arg": {"channel": "books", "instId": "BTC-USDT-SWAP"},
                    "action": "snapshot",
                    "data": [
                        {
                            "bids": [["99.9", "1", "0", "1"]],
                            "asks": [["100.1", "1", "0", "1"]],
                            "ts": "1781960000100",
                            "seqId": 10,
                            "prevSeqId": 9,
                            "checksum": 123,
                        }
                    ],
                }
            ),
        },
    ]
    bundle.mkdir(parents=True, exist_ok=True)
    (bundle / "okx_public_ws_l2_raw_messages.jsonl").write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    _write_json(
        bundle / "okx_public_ws_l2_raw_capture_manifest.json",
        {
            "data_version": "fixture",
            "capture_start": "2026-06-20T00:00:00Z",
            "capture_end": "2026-06-20T00:00:02Z",
            "capture_duration_seconds": 2.0,
            "public_ws_url": "wss://ws.okx.com:8443/ws/v5/public",
            "public_channels": ["trades", "books"],
            "public_ws_only": True,
            "private_endpoint_used": False,
            "order_endpoint_used": False,
            "broker_calls_used": False,
            "clock_source": "system_utc_and_python_monotonic_ns",
            "checksum_or_sequence_policy": "raw_ws_capture_before_order_book_replay_sequence_validation",
        },
    )


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
