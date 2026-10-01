from __future__ import annotations

import hashlib
import json
from pathlib import Path

import jsonschema
import pytest

from scripts.build_btc_true_scalping_long_horizon_l2_tick_import_contract_report import (
    build_btc_true_scalping_long_horizon_l2_tick_import_contract_report,
)


SCHEMA = Path("schemas/btc_true_scalping_long_horizon_l2_tick_import_contract_report.schema.json")
REPORT = Path("artifacts/btc_scalping_readiness/latest/btc_true_scalping_long_horizon_l2_tick_import_contract_report.json")


def test_btc_true_scalping_long_horizon_l2_tick_import_contract_schema_valid() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    jsonschema.validate(payload, schema)


def test_current_btc_true_scalping_long_horizon_l2_tick_import_contract_fails_closed() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))

    assert payload["status"] == "long_horizon_l2_tick_import_contract_missing_or_invalid_research_only"
    assert payload["validation"]["contract_satisfied"] is False
    assert payload["contract_satisfied"] is False
    assert payload["long_horizon_l2_tick_history_ready"] is False
    assert payload["candidate_generation_allowed"] is False
    assert payload["strategy_skeleton_generation_allowed"] is False
    assert payload["paper_or_live_unlock_allowed"] is False
    assert payload["true_scalping_allowed"] is False
    assert "btc_long_horizon_l2_tick_import_manifest_missing" in payload["blockers"]
    assert "btc_long_horizon_l2_tick_import_tick_history_missing" in payload["blockers"]
    assert "btc_long_horizon_l2_tick_import_l2_order_book_history_missing" in payload["blockers"]


def test_btc_true_scalping_long_horizon_l2_tick_import_contract_accepts_valid_archive_manifest(
    tmp_path: Path,
) -> None:
    tick_file = tmp_path / "data/external/btc_perpetual/okx_swap/historical_l2_tick_imports/tick.csv"
    l2_file = tmp_path / "data/external/btc_perpetual/okx_swap/historical_l2_tick_imports/l2.csv"
    _write_text(tick_file, "ts,price,size\n2026-01-01T00:00:00Z,1,1\n")
    _write_text(l2_file, "ts,side,price,size\n2026-01-01T00:00:00Z,bid,1,1\n")
    manifest = tmp_path / "data/external/btc_perpetual/okx_swap/historical_l2_tick_imports/okx_30d_manifest.json"
    _write_json(
        manifest,
        {
            "schema_version": "btc_true_scalping_l2_tick_external_history_manifest_v1",
            "manifest_id": "okx_fixture_30d",
            "source_type": "okx_historical_data_download",
            "venue": "okx",
            "venue_symbol": "BTC-USDT-SWAP",
            "symbol": "BTCUSDT",
            "public_or_licensed_archive_only": True,
            "private_endpoint_used": False,
            "order_endpoint_used": False,
            "broker_calls_used": False,
            "files": [
                {
                    "role": "tick_trades",
                    "path": str(tick_file.relative_to(tmp_path)),
                    "format": "csv",
                    "source_endpoint_or_archive": "okx_historical_data_download_trade_history",
                    "record_count": 100,
                    "sample_start": "2026-01-01T00:00:00Z",
                    "sample_end": "2026-02-01T00:00:00Z",
                    "sha256": _sha256(tick_file),
                },
                {
                    "role": "l2_order_book",
                    "path": str(l2_file.relative_to(tmp_path)),
                    "format": "csv",
                    "source_endpoint_or_archive": "okx_historical_data_download_order_book",
                    "record_count": 100,
                    "sample_start": "2026-01-01T00:00:00Z",
                    "sample_end": "2026-02-01T00:00:00Z",
                    "sha256": _sha256(l2_file),
                },
            ],
        },
    )

    payload = build_btc_true_scalping_long_horizon_l2_tick_import_contract_report(
        repo_root=tmp_path,
        generated_at="2026-06-21T00:00:00Z",
    )

    assert payload["status"] == "long_horizon_l2_tick_import_contract_satisfied_research_only"
    assert payload["validation"]["contract_satisfied"] is True
    assert payload["contract_satisfied"] is True
    assert payload["coverage_totals"]["tick_history_days"] == pytest.approx(31.0)
    assert payload["coverage_totals"]["l2_history_days"] == pytest.approx(31.0)
    assert payload["coverage_totals"]["common_calendar_span_days"] == pytest.approx(31.0)
    assert payload["coverage_totals"]["remaining_tick_history_days"] == pytest.approx(0.0)
    assert payload["coverage_totals"]["remaining_l2_history_days"] == pytest.approx(0.0)
    assert payload["coverage_totals"]["remaining_common_calendar_span_days"] == pytest.approx(0.0)
    assert payload["blockers"] == []
    assert payload["true_scalping_allowed"] is False
    assert payload["paper_or_live_unlock_allowed"] is False
    assert payload["guardrails"]["private_endpoints_allowed"] is False
    assert payload["guardrails"]["order_endpoints_allowed"] is False
    assert payload["guardrails"]["broker_calls_allowed"] is False


def test_btc_true_scalping_long_horizon_l2_tick_import_contract_rejects_private_or_order_boundary(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "data/external/btc_perpetual/okx_swap/historical_l2_tick_imports/bad_manifest.json"
    _write_json(
        manifest,
        {
            "source_type": "okx_historical_data_download",
            "public_or_licensed_archive_only": True,
            "private_endpoint_used": True,
            "order_endpoint_used": True,
            "broker_calls_used": False,
            "files": [],
        },
    )

    payload = build_btc_true_scalping_long_horizon_l2_tick_import_contract_report(
        repo_root=tmp_path,
        generated_at="2026-06-21T00:00:00Z",
    )

    assert payload["contract_satisfied"] is False
    assert "btc_long_horizon_import_private_endpoint_used" in payload["blockers"]
    assert "btc_long_horizon_import_order_endpoint_used" in payload["blockers"]
    assert payload["paper_or_live_unlock_allowed"] is False


def test_btc_true_scalping_long_horizon_l2_tick_import_contract_schema_rejects_unlock() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    payload["true_scalping_allowed"] = True

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)

    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    payload["guardrails"]["order_endpoints_allowed"] = True

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_text(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
