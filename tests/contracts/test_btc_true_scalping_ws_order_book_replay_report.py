from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from scripts.build_btc_true_scalping_ws_order_book_replay_report import (
    build_btc_true_scalping_ws_order_book_replay_report,
)


SCHEMA = Path("schemas/btc_true_scalping_ws_order_book_replay_report.schema.json")
REPORT = Path("artifacts/btc_scalping_readiness/latest/btc_true_scalping_ws_order_book_replay_report.json")


def test_btc_true_scalping_ws_order_book_replay_schema_valid() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    jsonschema.validate(payload, schema)


def test_current_btc_true_scalping_ws_order_book_replay_keeps_scalping_locked() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    validation = payload["validation"]

    assert payload["status"] in {
        "ws_order_book_replay_sequence_policy_verified_research_only_history_insufficient",
        "ws_order_book_replay_missing_or_invalid_research_only",
    }
    assert (
        payload["decision"]
        == "continue_public_ws_l2_capture_with_sequence_reconnect_latency_queue_validation_before_true_scalping"
    )
    assert payload["okx_checksum_deprecation_policy"]["production_deprecation_date"] == "2026-06-23"
    assert payload["okx_checksum_deprecation_policy"]["required_integrity_check"] == "seqId_prevSeqId_continuity"
    assert payload["contract_satisfied"] is False
    assert payload["event_ledger_feature_validation_allowed"] is False
    assert payload["true_scalping_allowed"] is False
    assert payload["candidate_generation_allowed"] is False
    assert payload["strategy_skeleton_generation_allowed"] is False
    assert payload["paper_or_live_unlock_allowed"] is False
    assert validation["independent_checksum_validated"] is False
    assert validation["checksum_deprecation_policy_recorded"] is True
    assert validation["execution_latency_model_ready"] is False
    assert validation["queue_model_ready"] is False
    assert payload["independent_checksum_validated"] is False
    assert "btc_ws_l2_independent_checksum_validation_missing" not in payload["blockers"]


def test_ws_order_book_replay_builder_validates_sequence_and_metrics(tmp_path: Path) -> None:
    _write_replay_fixture(tmp_path, prev_seq_id_for_update=10)

    payload = build_btc_true_scalping_ws_order_book_replay_report(
        repo_root=tmp_path,
        generated_at="2026-06-20T00:00:00Z",
    )

    summary = payload["replay_summary"]
    metrics = payload["replay_metrics"]
    validation = payload["validation"]
    assert payload["status"] == "ws_order_book_replay_sequence_policy_verified_research_only_history_insufficient"
    assert payload["replay_sequence_ready"] is True
    assert summary["snapshot_count"] == 1
    assert summary["update_count"] == 1
    assert summary["applied_update_count"] == 1
    assert summary["sequence_continuity_pass"] is True
    assert summary["sequence_gap_count"] == 0
    assert summary["crossed_book_count"] == 0
    assert summary["checksum_observed_count"] == 2
    assert summary["seq_id_observed_count"] == 2
    assert summary["prev_seq_id_observed_count"] == 2
    assert summary["connection_count"] == 1
    assert summary["forced_reconnect_count"] == 0
    assert summary["transport_gap_count"] == 0
    assert summary["final_best_bid"] == pytest.approx(99.9)
    assert summary["final_best_ask"] == pytest.approx(100.1)
    assert metrics["spread_bps"]["mean"] == pytest.approx(20.0)
    assert validation["replay_sequence_ready"] is True
    assert validation["sequence_integrity_policy_satisfied"] is True
    assert validation["checksum_deprecation_policy_recorded"] is True
    assert validation["independent_checksum_validated"] is False
    assert "btc_ws_l2_independent_checksum_validation_missing" not in payload["blockers"]
    assert payload["true_scalping_allowed"] is False


def test_ws_order_book_replay_builder_blocks_sequence_gap(tmp_path: Path) -> None:
    _write_replay_fixture(tmp_path, prev_seq_id_for_update=999)

    payload = build_btc_true_scalping_ws_order_book_replay_report(
        repo_root=tmp_path,
        generated_at="2026-06-20T00:00:00Z",
    )

    assert payload["status"] == "ws_order_book_replay_missing_or_invalid_research_only"
    assert payload["replay_sequence_ready"] is False
    assert payload["replay_summary"]["sequence_continuity_pass"] is False
    assert payload["replay_summary"]["sequence_gap_count"] == 1
    assert "btc_ws_l2_replay_sequence_continuity_failed" in payload["blockers"]
    assert "btc_ws_l2_sequence_integrity_policy_not_satisfied" in payload["blockers"]
    assert payload["paper_or_live_unlock_allowed"] is False


def test_ws_order_book_replay_schema_rejects_unlock() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    payload["event_ledger_feature_validation_allowed"] = True

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)


def _write_replay_fixture(root: Path, *, prev_seq_id_for_update: int) -> None:
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
            "channel": "books",
            "raw": json.dumps(
                {
                    "arg": {"channel": "books", "instId": "BTC-USDT-SWAP"},
                    "action": "snapshot",
                    "data": [
                        {
                            "bids": [["99.9", "1", "0", "1"], ["99.8", "2", "0", "1"]],
                            "asks": [["100.1", "1", "0", "1"], ["100.2", "2", "0", "1"]],
                            "ts": "1781960000000",
                            "seqId": 10,
                            "prevSeqId": -1,
                            "checksum": 123,
                        }
                    ],
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
                    "action": "update",
                    "data": [
                        {
                            "bids": [["99.8", "0", "0", "0"]],
                            "asks": [["100.2", "3", "0", "1"]],
                            "ts": "1781960000100",
                            "seqId": 11,
                            "prevSeqId": prev_seq_id_for_update,
                            "checksum": 456,
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
            "public_channels": ["books"],
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
