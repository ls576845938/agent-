from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from scripts.build_btc_true_scalping_l2_sample_quality_report import (
    build_btc_true_scalping_l2_sample_quality_report,
)


SCHEMA = Path("schemas/btc_true_scalping_l2_sample_quality_report.schema.json")
REPORT = Path("artifacts/btc_scalping_readiness/latest/btc_true_scalping_l2_sample_quality_report.json")


def test_btc_true_scalping_l2_sample_quality_schema_valid() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    jsonschema.validate(payload, schema)


def test_current_btc_true_scalping_l2_sample_quality_is_research_only_locked() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    quality = payload["sample_quality"]

    assert payload["status"] == "public_l2_sample_evidence_ready_research_only"
    assert payload["decision"] == "use_l2_sample_for_microstructure_feature_diagnostics_only"
    assert payload["bounded_public_rest_sample_only"] is True
    assert payload["network_called"] is True
    assert payload["public_rest_only"] is True
    assert quality["completed_sample_count"] >= payload["thresholds"]["min_completed_samples"]
    assert quality["trade_row_count"] > 0
    assert quality["book_level_row_count"] > 0
    assert quality["valid_top_of_book_snapshot_count"] >= payload["thresholds"]["min_valid_book_snapshots"]
    assert quality["latency_sample_count"] >= payload["thresholds"]["min_latency_samples"]
    assert payload["blockers"] == []
    assert payload["true_scalping_allowed"] is False
    assert payload["candidate_generation_allowed"] is False
    assert payload["strategy_skeleton_generation_allowed"] is False
    assert payload["paper_or_live_unlock_allowed"] is False
    assert payload["guardrails"]["broker_calls_allowed"] is False
    assert payload["guardrails"]["private_endpoints_allowed"] is False
    assert payload["guardrails"]["order_endpoints_allowed"] is False
    assert payload["guardrails"]["paper_queue"] == "LOCKED"
    assert payload["guardrails"]["live"] == "FROZEN"


def test_l2_sample_quality_builder_passes_with_public_fixture(tmp_path: Path) -> None:
    bundle = tmp_path / "data/external/btc_perpetual/okx_swap/bundles/fixture"
    _write_text(
        bundle / "agg_trades_samples.csv",
        "\n".join(
            [
                "sample_index,sample_captured_at,timestamp,ts,symbol,trade_id,price,size,side,source_record_id",
                "1,2026-06-20T00:00:00Z,2026-06-20T00:00:00Z,1781960000000,BTCUSDT,1,100.0,0.1,buy,t1",
                "2,2026-06-20T00:00:01Z,2026-06-20T00:00:01Z,1781960001000,BTCUSDT,2,100.1,0.2,sell,t2",
            ]
        )
        + "\n",
    )
    _write_text(
        bundle / "order_book_depth_samples.csv",
        "\n".join(
            [
                "sample_index,sample_captured_at,timestamp,ts,symbol,side,level,price,size,liquidation_orders,order_count,source_record_id",
                "1,2026-06-20T00:00:00Z,2026-06-20T00:00:00Z,1781960000100,BTCUSDT,bid,1,99.9,1.0,0,1,b1",
                "1,2026-06-20T00:00:00Z,2026-06-20T00:00:00Z,1781960000100,BTCUSDT,ask,1,100.1,1.0,0,1,a1",
                "2,2026-06-20T00:00:01Z,2026-06-20T00:00:01Z,1781960001100,BTCUSDT,bid,1,100.0,1.0,0,1,b2",
                "2,2026-06-20T00:00:01Z,2026-06-20T00:00:01Z,1781960001100,BTCUSDT,ask,1,100.2,1.0,0,1,a2",
            ]
        )
        + "\n",
    )
    _write_json(
        tmp_path / "artifacts/btc_scalping_readiness/latest/btc_okx_l2_microstructure_sample_capture_report.json",
        {
            "status": "verified",
            "network_called": True,
            "public_rest_only": True,
            "private_endpoint_used": False,
            "order_endpoint_used": False,
            "selected_bundle_dir": "data/external/btc_perpetual/okx_swap/bundles/fixture",
            "requested_sample_count": 2,
            "completed_sample_count": 2,
            "latency_samples": [
                {"endpoint": "/api/v5/market/history-trades", "network_called": True, "duration_ms": 10.0},
                {"endpoint": "/api/v5/market/books", "network_called": True, "duration_ms": 12.0},
            ],
            "blockers": [],
        },
    )

    payload = build_btc_true_scalping_l2_sample_quality_report(
        repo_root=tmp_path,
        min_completed_samples=2,
        min_valid_book_snapshots=2,
        min_latency_samples=2,
        generated_at="2026-06-20T00:00:00Z",
    )

    assert payload["status"] == "public_l2_sample_evidence_ready_research_only"
    assert payload["blockers"] == []
    assert payload["sample_quality"]["trade_row_count"] == 2
    assert payload["sample_quality"]["book_level_row_count"] == 4
    assert payload["sample_quality"]["valid_top_of_book_snapshot_count"] == 2
    assert payload["sample_quality"]["spread_bps"]["mean"] == pytest.approx(19.990009990010274)
    assert payload["true_scalping_allowed"] is False
    assert payload["paper_or_live_unlock_allowed"] is False


def test_l2_sample_quality_builder_blocks_missing_capture(tmp_path: Path) -> None:
    payload = build_btc_true_scalping_l2_sample_quality_report(
        repo_root=tmp_path,
        generated_at="2026-06-20T00:00:00Z",
    )

    assert payload["status"] == "public_l2_sample_evidence_partial_research_only"
    assert "btc_l2_sample_capture_report_not_verified" in payload["blockers"]
    assert "btc_l2_sample_agg_trades_file_missing" in payload["blockers"]
    assert "btc_l2_sample_order_book_depth_file_missing" in payload["blockers"]
    assert payload["candidate_generation_allowed"] is False
    assert payload["paper_or_live_unlock_allowed"] is False


def test_l2_sample_quality_schema_rejects_unlock() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    payload["guardrails"]["order_endpoints_allowed"] = True

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_text(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding="utf-8")
