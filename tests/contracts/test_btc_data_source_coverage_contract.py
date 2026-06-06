from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from scripts.build_btc_data_status_report import build_btc_data_status_report


SCHEMA = Path("schemas/btc_data_status_report.schema.json")
REPORT = Path("artifacts/btc_data_status/latest/btc_data_status_report.json")


def test_btc_data_source_coverage_schema_valid() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    jsonschema.validate(payload, schema)


def test_btc_data_status_records_okx_perpetual_evidence_and_regime_blocker() -> None:
    payload = build_btc_data_status_report(generated_at="2026-05-19T00:00:00Z")

    assert payload["metadata"]["is_placeholder"] is False
    assert payload["metadata"]["is_data_dependent"] is True
    assert payload["instrument"]["symbol"] == "BTCUSDT"
    assert payload["instrument"]["exchange"] == "okx_swap"
    assert payload["instrument"]["market_type"] == "usds_m_perpetual"
    assert payload["data_sources"]["klines_available"] is True
    assert payload["data_sources"]["funding_rate_available"] is True
    assert payload["data_sources"]["funding_info_available"] is True
    assert payload["data_sources"]["mark_price_klines_available"] is True
    assert payload["data_sources"]["premium_index_klines_available"] is True
    assert payload["data_sources"]["exchange_info_available"] is True
    assert "1h" in payload["coverage"]["intervals_available"]
    assert payload["coverage"]["missing_bar_count_by_interval"]["1h"] == 0
    assert payload["coverage"]["duplicate_bar_count_by_interval"]["1h"] == 0
    assert payload["data_quality"]["manifest_hash"]
    assert "btc_funding_info_missing" not in payload["blockers"]
    assert "btc_exchange_info_missing" not in payload["blockers"]
    assert "btc_regime_contract_not_pass" in payload["blockers"]
    assert "btc_liquidation_snapshot_missing_diagnostic_only" not in payload["blockers"]
    assert "btc_liquidation_snapshot_missing_diagnostic_only" in payload["diagnostic_warnings"]


def test_liquidation_snapshot_is_diagnostic_not_complete_history() -> None:
    payload = build_btc_data_status_report(generated_at="2026-05-19T00:00:00Z")

    assert payload["data_sources"]["liquidation_snapshot_available"] is False
    assert payload["data_sources"]["liquidation_snapshot_status"] == "diagnostic_missing_not_complete_history"
    assert payload["promotion_ready"] is False
