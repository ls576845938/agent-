from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from scripts.build_btc_true_scalping_ws_latency_queue_diagnostics_report import (
    build_btc_true_scalping_ws_latency_queue_diagnostics_report,
)


SCHEMA = Path("schemas/btc_true_scalping_ws_latency_queue_diagnostics_report.schema.json")
REPORT = Path("artifacts/btc_scalping_readiness/latest/btc_true_scalping_ws_latency_queue_diagnostics_report.json")


def test_btc_true_scalping_ws_latency_queue_diagnostics_schema_valid() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    jsonschema.validate(payload, schema)


def test_current_btc_true_scalping_ws_latency_queue_diagnostics_keeps_scalping_locked() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    validation = payload["validation"]

    assert payload["status"] in {
        "ws_latency_queue_proxy_ready_research_only_execution_latency_history_insufficient",
        "ws_latency_queue_proxy_missing_or_invalid_research_only",
    }
    assert payload["decision"] == "continue_long_public_ws_l2_capture_and_keep_execution_latency_queue_unlocked_false"
    assert payload["proxy_diagnostics_ready"] is True
    assert validation["receive_latency_proxy_ready"] is True
    assert validation["receive_latency_proxy_is_execution_latency"] is False
    assert validation["visible_queue_proxy_ready"] is True
    assert validation["visible_queue_proxy_is_exchange_queue_position"] is False
    assert validation["execution_latency_model_ready"] is False
    assert validation["queue_model_ready"] is False
    assert payload["execution_latency_model_ready"] is False
    assert payload["queue_model_ready"] is False
    assert payload["contract_satisfied"] is False
    assert payload["event_ledger_feature_validation_allowed"] is False
    assert payload["true_scalping_allowed"] is False
    assert payload["candidate_generation_allowed"] is False
    assert payload["strategy_skeleton_generation_allowed"] is False
    assert payload["paper_or_live_unlock_allowed"] is False
    assert "btc_execution_latency_model_missing_ws_receive_latency_is_not_order_execution_latency" in payload["blockers"]
    assert "btc_queue_model_missing_public_l2_visible_depth_is_not_exchange_queue_position" in payload["blockers"]


def test_ws_latency_queue_diagnostics_builder_derives_public_proxy_metrics(tmp_path: Path) -> None:
    _write_fixture(tmp_path)

    payload = build_btc_true_scalping_ws_latency_queue_diagnostics_report(
        repo_root=tmp_path,
        generated_at="2026-06-20T00:00:00Z",
    )

    receive_latency = payload["receive_latency_proxy"]
    visible_queue = payload["visible_queue_proxy"]
    validation = payload["validation"]
    assert payload["status"] == "ws_latency_queue_proxy_ready_research_only_execution_latency_history_insufficient"
    assert payload["proxy_diagnostics_ready"] is True
    assert receive_latency["sample_count"] == 2
    assert receive_latency["book_sample_count"] == 1
    assert receive_latency["trade_sample_count"] == 1
    assert receive_latency["receive_clock_delta_ms"]["mean"] == pytest.approx(550.0)
    assert visible_queue["sample_count"] == 1
    assert visible_queue["best_bid_visible_queue_btc"]["mean"] == pytest.approx(2.0)
    assert visible_queue["best_ask_visible_queue_btc"]["mean"] == pytest.approx(1.5)
    assert visible_queue["spread_bps"]["mean"] == pytest.approx(20.0)
    assert validation["receive_latency_proxy_is_execution_latency"] is False
    assert validation["visible_queue_proxy_is_exchange_queue_position"] is False
    assert validation["minimum_research_capture_seconds_satisfied"] is False
    assert validation["minimum_event_ledger_history_days_satisfied"] is False
    assert payload["execution_latency_model_ready"] is False
    assert payload["queue_model_ready"] is False
    assert payload["true_scalping_allowed"] is False


def test_ws_latency_queue_diagnostics_builder_blocks_missing_inputs(tmp_path: Path) -> None:
    payload = build_btc_true_scalping_ws_latency_queue_diagnostics_report(
        repo_root=tmp_path,
        generated_at="2026-06-20T00:00:00Z",
    )

    assert payload["status"] == "ws_latency_queue_proxy_missing_or_invalid_research_only"
    assert payload["proxy_diagnostics_ready"] is False
    assert "btc_ws_latency_queue_raw_capture_not_verified_preflight" in payload["blockers"]
    assert "btc_ws_latency_queue_order_book_replay_not_ready" in payload["blockers"]
    assert "btc_ws_receive_latency_proxy_missing" in payload["blockers"]
    assert "btc_ws_visible_queue_proxy_missing" in payload["blockers"]
    assert payload["paper_or_live_unlock_allowed"] is False


def test_ws_latency_queue_diagnostics_schema_rejects_unlock() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    payload["execution_latency_model_ready"] = True

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)

    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    payload["guardrails"]["order_endpoints_allowed"] = True

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)


def _write_fixture(root: Path) -> None:
    bundle = root / "data/external/btc_perpetual/okx_swap/bundles/fixture"
    _write_json(
        root / "artifacts/btc_scalping_readiness/latest/btc_okx_public_ws_l2_raw_capture_report.json",
        {
            "status": "verified_preflight",
            "selected_bundle_dir": "data/external/btc_perpetual/okx_swap/bundles/fixture",
            "private_endpoint_used": False,
            "order_endpoint_used": False,
            "broker_calls_used": False,
        },
    )
    _write_json(
        root / "artifacts/btc_scalping_readiness/latest/btc_true_scalping_ws_order_book_replay_report.json",
        {
            "status": "ws_order_book_replay_sequence_policy_verified_research_only_history_insufficient",
            "replay_sequence_ready": True,
            "validation": {"sequence_integrity_policy_satisfied": True},
        },
    )
    rows = [
        {
            "capture_sequence": 1,
            "connection_sequence": 1,
            "local_receive_ts": "2026-06-20T00:00:01.500Z",
            "monotonic_ns": 1000,
            "channel": "trades",
            "raw": json.dumps(
                {
                    "arg": {"channel": "trades", "instId": "BTC-USDT-SWAP"},
                    "data": [{"tradeId": "1", "px": "100.0", "sz": "0.1", "side": "buy", "ts": "1781913601000"}],
                }
            ),
        },
        {
            "capture_sequence": 2,
            "connection_sequence": 1,
            "local_receive_ts": "2026-06-20T00:00:01.600Z",
            "monotonic_ns": 2000,
            "channel": "books",
            "raw": json.dumps(
                {
                    "arg": {"channel": "books", "instId": "BTC-USDT-SWAP"},
                    "action": "snapshot",
                    "data": [
                        {
                            "bids": [["99.9", "2.0", "0", "3"]],
                            "asks": [["100.1", "1.5", "0", "2"]],
                            "ts": "1781913601000",
                            "seqId": 10,
                            "prevSeqId": -1,
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
            "capture_duration_seconds": 2.0,
            "message_count": 2,
            "data_message_count": 2,
            "connection_count": 1,
            "forced_reconnect_count": 0,
            "public_ws_only": True,
            "private_endpoint_used": False,
            "order_endpoint_used": False,
            "broker_calls_used": False,
        },
    )


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
