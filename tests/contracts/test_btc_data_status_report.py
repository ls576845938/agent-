from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import jsonschema

from scripts.build_btc_data_status_report import (
    build_btc_data_status_report,
    write_btc_data_status_report,
)
from scripts.build_global_research_registry import build_global_registry

SCHEMA = Path("schemas/btc_data_status_report.schema.json")
REPORT = Path("artifacts/btc_data_status/latest/btc_data_status_report.json")


def test_btc_data_status_report_schema_file_exists() -> None:
    assert SCHEMA.exists()


def test_current_btc_data_status_passes_from_drift_guarded_regime_source() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    jsonschema.validate(payload, schema)
    assert payload["status"] == "pass"
    assert payload["source_run_dir"] == (
        "artifacts/btc_intraday_event_ledger/20260620T000000Z_high_vol_non_expansion_trend_guard_eventledger"
    )
    assert payload["fold_contract_status"] == "pass"
    assert payload["regime_contract_status"] == "pass"
    assert payload["regime_gate_pass_rate"] == 0.8
    assert payload["blockers"] == []
    assert payload["data_quality"]["blockers"] == []
    intervals = {row["interval"]: row for row in payload["intervals"]}
    assert intervals["1m"]["status"] == "pass"
    assert intervals["1m"]["manifest_status"] == "pass"
    assert intervals["1m"]["data_version"].startswith("qs-sqlite-BTCUSDT-1m-")
    assert payload["paper_queue_status"] == "locked"
    assert payload["live_status"] == "frozen"
    current_sqlite = payload["current_sqlite_coverage"]
    assert current_sqlite["status"] == "pass"
    assert current_sqlite["latest_closed_bar"]["event_time"] == "2026-06-27T08:59:59.999000+00:00"
    assert current_sqlite["latest_closed_bar"]["available_time"] == "2026-06-27T08:59:59.999000+00:00"
    assert current_sqlite["pit_contract"]["ingested_at_field"] == "ingested_at"
    assert current_sqlite["pit_contract"]["processed_at_field"] == "updated_at"
    assert current_sqlite["finalization"]["closed_bar_only"] is True
    assert current_sqlite["coverage"]["latest_close_time_by_interval"]["1h"] == "2026-06-27T08:59:59.999000+00:00"


def test_btc_data_status_report_summarizes_fold_regime_contract(tmp_path: Path) -> None:
    run_dir = tmp_path / "artifacts/btc_candidate_validation/run_fixture"
    _write_json(
        run_dir / "btc_data_fold_regime_status_report.json",
        {
            "schema_version": "btc_data_fold_regime_status_report_v1",
            "sqlite": {"status": "pass", "symbol": "BTCUSDT"},
            "intervals": [
                {
                    "interval": "1h",
                    "status": "pass",
                    "manifest_status": "pass",
                    "row_count": 10,
                    "expected_rows": 10,
                    "missing_rows": 0,
                    "data_version": "qs-sqlite-BTCUSDT-1h-fixture",
                    "latest_manifest_path": "data/manifests/btc-1h.json",
                },
                {
                    "interval": "4h",
                    "status": "pass",
                    "manifest_status": "pass",
                    "row_count": 5,
                    "expected_rows": 5,
                    "missing_rows": 0,
                    "data_version": "qs-sqlite-BTCUSDT-4h-fixture",
                    "latest_manifest_path": "data/manifests/btc-4h.json",
                },
            ],
            "manifest_lineage": {"status": "pass"},
        },
    )
    _write_json(
        run_dir / "fold_regime_contract_audit.json",
        {
            "schema_version": "btc_fold_regime_contract_audit_v1",
            "fold_contract": {
                "status": "pass",
                "fold_count": 2,
                "folds": [
                    {
                        "fold_id": "1",
                        "validation_start": "2024-01-01",
                        "validation_end": "2024-03-31",
                        "validation_rows": 100,
                        "passed": True,
                    }
                ],
            },
            "regime_contract": {
                "status": "fail",
                "pass_rate": 0.50,
                "dragging_regimes": ["trending_down"],
            },
        },
    )

    payload = build_btc_data_status_report(
        repo_root=tmp_path,
        source_run_dir=Path("artifacts/btc_candidate_validation/run_fixture"),
        generated_at="2026-05-18T00:00:00Z",
    )

    assert payload["schema_version"] == "btc_data_status_report_v1"
    assert payload["asset"] == "btc"
    assert payload["symbol"] == "BTCUSDT"
    assert payload["promotion_ready"] is False
    assert payload["paper_queue_status"] == "locked"
    assert payload["live_status"] == "frozen"
    assert payload["fold_definition_version"] == "btc_walk_forward_fold_contract_v1"
    assert payload["regime_classifier_version"] == "classify_btc_regimes_v1"
    assert payload["fold_contract_status"] == "pass"
    assert payload["regime_contract_status"] == "fail"
    assert payload["regime_gate_pass_rate"] == 0.50
    assert payload["intervals"][0]["data_version"] == "qs-sqlite-BTCUSDT-1h-fixture"
    assert "btc_regime_contract_not_pass" in payload["blockers"]
    assert payload["fee_model_status"] == "required"
    assert "btc_fee_model_required" not in payload["blockers"]

    output = write_btc_data_status_report(payload, tmp_path / "artifacts/btc_data_status/latest")
    persisted = json.loads(Path(output).read_text(encoding="utf-8"))
    assert persisted["source_fold_regime_contract_audit"].endswith("fold_regime_contract_audit.json")


def test_btc_data_status_records_current_sqlite_closed_bar_and_pit_fields(tmp_path: Path) -> None:
    run_dir = tmp_path / "artifacts/btc_candidate_validation/run_fixture"
    _write_json(
        run_dir / "btc_data_fold_regime_status_report.json",
        {
            "sqlite": {"status": "pass", "symbol": "BTCUSDT", "db_path": "data/market_data.sqlite"},
            "intervals": [
                {
                    "interval": "1h",
                    "status": "pass",
                    "manifest_status": "pass",
                    "row_count": 2,
                    "expected_rows": 2,
                    "missing_rows": 0,
                    "data_version": "qs-sqlite-BTCUSDT-1h-fixture",
                    "latest_manifest_path": "data/manifests/btc-1h.json",
                    "start": "2026-06-27T07:59:59.999000+00:00",
                    "end": "2026-06-27T08:59:59.999000+00:00",
                }
            ],
            "manifest_lineage": {"status": "pass"},
        },
    )
    _write_json(
        run_dir / "fold_regime_contract_audit.json",
        {
            "fold_contract": {"status": "pass", "fold_count": 1, "folds": []},
            "regime_contract": {"status": "pass", "pass_rate": 1.0, "dragging_regimes": []},
        },
    )
    _write_market_db(tmp_path / "data/market_data.sqlite")

    payload = build_btc_data_status_report(
        repo_root=tmp_path,
        source_run_dir=Path("artifacts/btc_candidate_validation/run_fixture"),
        generated_at="2026-06-27T10:00:00+00:00",
    )

    current_sqlite = payload["current_sqlite_coverage"]
    assert current_sqlite["status"] == "partial"
    assert current_sqlite["intervals"]["1h"]["status"] == "pass"
    assert current_sqlite["intervals"]["1h"]["missing_rows"] == 0
    assert current_sqlite["intervals"]["1h"]["duplicate_rows"] == 0
    assert current_sqlite["latest_closed_bar"] == {
        "event_time": "2026-06-27T08:59:59.999000+00:00",
        "available_time": "2026-06-27T08:59:59.999000+00:00",
        "ingested_at": "2026-06-27T09:00:05+00:00",
        "processed_at": "2026-06-27T09:00:07+00:00",
        "open_time": "2026-06-27T08:00:00+00:00",
        "close_time": "2026-06-27T08:59:59.999000+00:00",
        "close": 60454.67,
        "volume": 0.20325,
        "source": "binance_rest",
    }
    assert current_sqlite["pit_contract"]["available_time_policy"].startswith("closed kline")
    assert current_sqlite["finalization"]["latest_bar_final"] is True


def test_btc_data_status_filters_diagnostic_only_gaps_from_hard_blockers(tmp_path: Path) -> None:
    run_dir = tmp_path / "artifacts/btc_candidate_validation/run_fixture"
    _write_json(
        run_dir / "btc_data_fold_regime_status_report.json",
        {
            "sqlite": {"status": "pass", "symbol": "BTCUSDT"},
            "intervals": [
                {
                    "interval": "1h",
                    "status": "pass",
                    "manifest_status": "pass",
                    "row_count": 10,
                    "expected_rows": 10,
                    "missing_rows": 0,
                    "data_version": "qs-sqlite-BTCUSDT-1h-fixture",
                    "latest_manifest_path": "data/manifests/btc-1h.json",
                }
            ],
            "manifest_lineage": {"status": "pass"},
        },
    )
    _write_json(
        run_dir / "fold_regime_contract_audit.json",
        {
            "fold_contract": {"status": "pass", "fold_count": 1, "folds": []},
            "regime_contract": {"status": "pass", "pass_rate": 1.0, "dragging_regimes": []},
        },
    )
    _write_json(
        tmp_path / "artifacts/btc_data_status/latest/btc_perpetual_provider_verification_report.json",
        {
            "perpetual_evidence_ready": True,
            "mark_price_klines_verified": True,
            "premium_index_klines_verified": True,
            "funding_rate_verified": True,
            "funding_info_verified": True,
            "exchange_info_verified": True,
            "open_interest_verified": False,
            "open_interest_coverage_type": "missing",
            "liquidation_snapshot_available": False,
            "diagnostic_warnings": ["btc_open_interest_history_not_verified_diagnostic_partial"],
            "blockers": [],
        },
    )

    payload = build_btc_data_status_report(
        repo_root=tmp_path,
        source_run_dir=Path("artifacts/btc_candidate_validation/run_fixture"),
        generated_at="2026-05-18T00:00:00Z",
    )

    assert payload["status"] == "pass"
    assert "btc_open_interest_history_not_verified_diagnostic_partial" not in payload["blockers"]
    assert "btc_agg_trades_missing" not in payload["blockers"]
    assert "btc_liquidation_snapshot_missing_diagnostic_only" not in payload["blockers"]
    assert "btc_open_interest_history_not_verified_diagnostic_partial" in payload["diagnostic_warnings"]
    assert "btc_agg_trades_missing" in payload["diagnostic_warnings"]
    assert "btc_liquidation_snapshot_missing_diagnostic_only" in payload["diagnostic_warnings"]
    assert payload["data_sources"]["open_interest_available"] is False
    assert payload["data_sources"]["liquidation_snapshot_gate_eligible"] is False


def test_global_registry_surfaces_btc_data_status_report(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "artifacts/btc_data_status/latest/btc_data_status_report.json",
        {
            "schema_version": "btc_data_status_report_v1",
            "status": "partial",
            "fold_definition_version": "btc_walk_forward_fold_contract_v1",
            "regime_classifier_version": "classify_btc_regimes_v1",
            "fold_contract_status": "pass",
            "regime_contract_status": "fail",
            "blockers": ["btc_regime_contract_not_pass"],
        },
    )

    registry = build_global_registry(
        repo_root=tmp_path,
        generated_at="2026-05-18T00:00:00Z",
    )
    btc = registry["assets"]["btc"]

    assert btc["latest_data_status"] == "artifacts/btc_data_status/latest/btc_data_status_report.json"
    assert btc["data_status"]["report_path"] == "artifacts/btc_data_status/latest/btc_data_status_report.json"
    assert btc["data_status"]["fold_contract_status"] == "pass"
    assert btc["data_status"]["regime_contract_status"] == "fail"
    assert "btc_regime_contract_not_pass" in btc["data_status"]["blockers"]


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_market_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            create table market_klines (
                exchange text, symbol text, interval text, open_time_ms integer,
                open_time text, close_time_ms integer, close_time text,
                open real, high real, low real, close real, volume real,
                quote_volume real, trade_count integer, taker_buy_base_volume real,
                taker_buy_quote_volume real, source text, ingested_at text, updated_at text
            )
            """
        )
        rows = [
            (
                "binance_spot",
                "BTCUSDT",
                "1h",
                1782543600000,
                "2026-06-27T07:00:00+00:00",
                1782547199999,
                "2026-06-27T07:59:59.999000+00:00",
                60400.0,
                60500.0,
                60300.0,
                60410.0,
                0.1,
                6041.0,
                10,
                0.05,
                3020.5,
                "binance_rest",
                "2026-06-27T08:00:05+00:00",
                "2026-06-27T08:00:07+00:00",
            ),
            (
                "binance_spot",
                "BTCUSDT",
                "1h",
                1782547200000,
                "2026-06-27T08:00:00+00:00",
                1782550799999,
                "2026-06-27T08:59:59.999000+00:00",
                60541.01,
                60541.01,
                60416.0,
                60454.67,
                0.20325,
                12284.7202026,
                14,
                0.05464,
                3304.1396243,
                "binance_rest",
                "2026-06-27T09:00:05+00:00",
                "2026-06-27T09:00:07+00:00",
            ),
        ]
        connection.executemany(
            """
            insert into market_klines values (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            rows,
        )
