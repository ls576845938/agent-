from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from scripts.build_btc_true_scalping_microstructure_models import build_btc_true_scalping_microstructure_models


SCHEMA = Path("schemas/btc_true_scalping_microstructure_model_report.schema.json")
REPORT = Path("artifacts/btc_scalping_readiness/latest/btc_true_scalping_microstructure_model_report.json")


def test_btc_true_scalping_microstructure_model_report_schema_valid() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    jsonschema.validate(payload, schema)


def test_current_btc_true_scalping_microstructure_models_are_research_only() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))

    assert payload["status"] == "pass"
    assert payload["decision"] == "models_ready_for_manual_review_research_only"
    assert payload["blockers"] == []
    assert payload["models"]["spread_model"]["status"] == "pass"
    assert payload["models"]["latency_model"]["status"] == "pass"
    assert payload["models"]["queue_position_model"]["status"] == "pass"
    assert payload["models"]["spread_model"]["sample_count"] >= 1
    assert payload["models"]["latency_model"]["sample_count"] >= 1
    assert payload["models"]["queue_position_model"]["sample_count"] >= 1
    assert payload["guardrails"]["production_ready"] is False
    assert payload["guardrails"]["paper_or_live_usable"] is False
    assert payload["guardrails"]["order_endpoints_allowed"] is False
    assert payload["guardrails"]["broker_calls_allowed"] is False


def test_btc_true_scalping_microstructure_model_builder_derives_models_from_evidence(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "artifacts/btc_data_status/latest/btc_data_status_report.json",
        {
            "perpetual_provider_verification": {
                "selected_provider": "okx_swap",
                "selected_bundle_id": "fixture_bundle",
            }
        },
    )
    bundle = tmp_path / "data/external/btc_perpetual/okx_swap/bundles/fixture_bundle"
    _write_text(
        bundle / "agg_trades.csv",
        "\n".join(
            [
                "timestamp,ts,symbol,trade_id,price,size,side,source_record_id",
                "2026-06-20T00:00:00+00:00,1781960000000,BTCUSDT,1,100.0,0.1,buy,fixture-trade-1",
            ]
        )
        + "\n",
    )
    _write_text(
        bundle / "order_book_depth.csv",
        "\n".join(
            [
                "timestamp,ts,symbol,side,level,price,size,liquidation_orders,order_count,source_record_id",
                "2026-06-20T00:00:00+00:00,1781960000100,BTCUSDT,bid,1,99.9,2.0,0,3,fixture-bid-1",
                "2026-06-20T00:00:00+00:00,1781960000100,BTCUSDT,ask,1,100.1,1.5,0,2,fixture-ask-1",
            ]
        )
        + "\n",
    )
    _write_json(
        tmp_path / "artifacts/btc_scalping_readiness/latest/btc_okx_microstructure_capture_report.json",
        {
            "latency_samples": [
                {
                    "endpoint": "/api/v5/market/history-trades",
                    "network_called": True,
                    "duration_ms": 123.4,
                },
                {
                    "endpoint": "/api/v5/market/books",
                    "network_called": True,
                    "duration_ms": 98.7,
                },
            ]
        },
    )

    payload = build_btc_true_scalping_microstructure_models(
        repo_root=tmp_path,
        generated_at="2026-06-20T00:00:00Z",
    )

    assert payload["status"] == "pass"
    assert payload["blockers"] == []
    assert payload["models"]["spread_model"]["sample_count"] == 1
    assert payload["models"]["latency_model"]["sample_count"] == 2
    assert payload["models"]["queue_position_model"]["sample_count"] == 1
    assert (tmp_path / payload["models"]["spread_model"]["path"]).exists()
    assert (tmp_path / payload["models"]["latency_model"]["path"]).exists()
    assert (tmp_path / payload["models"]["queue_position_model"]["path"]).exists()


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_text(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding="utf-8")
