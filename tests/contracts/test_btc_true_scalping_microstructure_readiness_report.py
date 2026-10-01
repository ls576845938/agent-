from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from scripts.build_btc_true_scalping_microstructure_readiness_report import (
    build_btc_true_scalping_microstructure_readiness_report,
)


SCHEMA = Path("schemas/btc_true_scalping_microstructure_readiness_report.schema.json")
REPORT = Path("artifacts/btc_scalping_readiness/latest/btc_true_scalping_microstructure_readiness_report.json")


def test_btc_true_scalping_microstructure_readiness_schema_valid() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    jsonschema.validate(payload, schema)


def test_current_btc_true_scalping_microstructure_readiness_is_research_only_ready() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    one_minute = payload["evidence"]["one_minute_klines"]
    tick_history = payload["evidence"]["tick_or_agg_trade_history"]
    order_book = payload["evidence"]["order_book_depth_history"]
    spread_model = payload["evidence"]["spread_model"]
    latency_model = payload["evidence"]["latency_model"]
    queue_model = payload["evidence"]["queue_position_model"]

    assert payload["status"] == "microstructure_evidence_ready_research_only"
    assert payload["decision"] == "manual_review_before_research_only_scalping_strategy_design"
    assert payload["next_required_action"] == "manual_review_before_research_only_scalping_strategy_design"
    assert one_minute["status"] == "pass"
    assert one_minute["data_version"].startswith("qs-sqlite-BTCUSDT-1m-")
    assert "btc_1m_kline_manifest_missing_or_not_pass" not in payload["blockers"]
    assert tick_history["status"] == "pass"
    assert tick_history["files"] == [
        "data/external/btc_perpetual/okx_swap/bundles/btc_okx_swap_btcusdt_history_365d_v1/agg_trades.csv"
    ]
    assert order_book["status"] == "pass"
    assert order_book["files"] == [
        "data/external/btc_perpetual/okx_swap/bundles/btc_okx_swap_btcusdt_history_365d_v1/order_book_depth.csv"
    ]
    assert "btc_tick_or_agg_trade_history_missing" not in payload["blockers"]
    assert "btc_order_book_depth_history_missing" not in payload["blockers"]
    assert spread_model["status"] == "pass"
    assert latency_model["status"] == "pass"
    assert queue_model["status"] == "pass"
    assert spread_model["model_status"] == "pass"
    assert latency_model["model_status"] == "pass"
    assert queue_model["model_status"] == "pass"
    assert payload["blockers"] == []
    assert payload["true_scalping_research_design_allowed"] is True
    assert payload["true_scalping_allowed"] is False
    assert payload["candidate_generation_allowed"] is False
    assert payload["strategy_skeleton_generation_allowed"] is False
    assert payload["paper_or_live_unlock_allowed"] is False
    assert payload["guardrails"]["private_endpoints_allowed"] is False
    assert payload["guardrails"]["order_endpoints_allowed"] is False
    assert payload["guardrails"]["broker_calls_allowed"] is False


def test_btc_true_scalping_microstructure_readiness_ready_state_still_research_only(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "artifacts/btc_data_status/latest/btc_data_status_report.json",
        {
            "perpetual_provider_verification": {
                "selected_provider": "okx_swap",
                "selected_bundle_id": "fixture_bundle",
            }
        },
    )
    _write_json(
        tmp_path / "data/manifests/qs-sqlite-BTCUSDT-1m-fixture.json",
        {
            "data_version": "qs-sqlite-BTCUSDT-1m-fixture",
            "source": "sqlite",
            "symbol": "BTCUSDT",
            "interval": "1m",
            "row_count": 1440,
            "expected_rows": 1440,
            "coverage_pct": 100.0,
            "quality_score": 100.0,
            "start": "2026-01-01T00:00:00+00:00",
            "end": "2026-01-01T23:59:00+00:00",
        },
    )
    bundle = tmp_path / "data/external/btc_perpetual/okx_swap/bundles/fixture_bundle"
    for name in ("agg_trades.csv", "order_book_depth.csv"):
        _write_text(bundle / name, "timestamp,price,qty\n")
    for path in (
        tmp_path / "configs/risk/btc_spread_model.json",
        tmp_path / "configs/risk/btc_latency_model.json",
        tmp_path / "configs/risk/btc_queue_position_model.json",
    ):
        _write_json(path, {"status": "pass"})

    payload = build_btc_true_scalping_microstructure_readiness_report(
        repo_root=tmp_path,
        generated_at="2026-06-20T00:00:00Z",
    )

    assert payload["status"] == "microstructure_evidence_ready_research_only"
    assert payload["blockers"] == []
    assert payload["true_scalping_research_design_allowed"] is True
    assert payload["true_scalping_allowed"] is False
    assert payload["paper_or_live_unlock_allowed"] is False
    assert payload["guardrails"]["paper_queue"] == "LOCKED"
    assert payload["guardrails"]["live"] == "FROZEN"


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_text(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding="utf-8")
