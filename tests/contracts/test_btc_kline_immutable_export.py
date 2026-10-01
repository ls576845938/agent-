from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import subprocess
import sys

import jsonschema
import pytest

import quant_crypto.data.dataready_consumer as dataready_consumer_module
from quant_crypto.data.dataready_consumer import consume_btc_dataready
from quant_crypto.data.immutable_kline_export import (
    ATTESTATION_NAME,
    DATASET_ID,
    KlineExportBlocked,
    _canonical_numeric_text,
    export_immutable_klines,
)
from tools.agent_governance.shared_data import (
    publish_dataset,
    resolve_manifest_payload,
)


ROOT = Path(__file__).resolve().parents[2]
SCHEMA = ROOT / "schemas/btc_kline_dataready_attestation.schema.json"
HEAD = "a" * 40
VERSION = "btc-kline-fixture-20260726-v1"
NOW = datetime(2026, 7, 26, 0, 5, tzinfo=timezone.utc)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _create_source(
    path: Path,
    *,
    legacy: bool = False,
    unsupported_legacy: bool = False,
    omit_middle: bool = False,
    duplicate: bool = False,
) -> Path:
    connection = sqlite3.connect(path)
    try:
        if legacy:
            connection.execute(
                """
                CREATE TABLE market_klines (
                    exchange TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    interval TEXT NOT NULL,
                    open_time_ms INTEGER NOT NULL,
                    open_time TEXT NOT NULL,
                    close_time_ms INTEGER NOT NULL,
                    close_time TEXT NOT NULL,
                    open REAL NOT NULL,
                    high REAL NOT NULL,
                    low REAL NOT NULL,
                    close REAL NOT NULL,
                    volume REAL NOT NULL
                )
                """
            )
            connection.executemany(
                "INSERT INTO market_klines VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        "okx",
                        "BTC-USDT-SWAP",
                        "1m",
                        1785023940000,
                        "2026-07-25T23:59:00+00:00",
                        1785023999999,
                        "2026-07-25T23:59:59.999000+00:00",
                        100,
                        102,
                        99,
                        101,
                        10,
                    ),
                    (
                        "okx",
                        "BTC-USDT-SWAP",
                        "1m",
                        1785024000000,
                        "2026-07-26T00:00:00+00:00",
                        1785024059999,
                        "2026-07-26T00:00:59.999000+00:00",
                        101,
                        103,
                        100,
                        102,
                        11,
                    ),
                    (
                        "okx",
                        "BTC-USDT-SWAP",
                        "1m",
                        1785024300000,
                        "2026-07-26T00:05:00+00:00",
                        1785024359999,
                        "2026-07-26T00:05:59.999000+00:00",
                        102,
                        104,
                        101,
                        103,
                        12,
                    ),
                ],
            )
        elif unsupported_legacy:
            connection.execute(
                """
                CREATE TABLE market_klines (
                    exchange TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    interval TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    open REAL NOT NULL,
                    high REAL NOT NULL,
                    low REAL NOT NULL,
                    close REAL NOT NULL,
                    volume REAL NOT NULL
                )
                """
            )
            connection.execute(
                """
                INSERT INTO market_klines
                VALUES ('okx', 'BTC-USDT-SWAP', '1m', '2026-07-26T00:00:00Z',
                        100, 102, 99, 101, 10)
                """
            )
        else:
            connection.execute(
                """
                CREATE TABLE market_klines (
                    exchange TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    interval TEXT NOT NULL,
                    event_time TEXT NOT NULL,
                    available_time TEXT NOT NULL,
                    is_finalized INTEGER NOT NULL,
                    open REAL NOT NULL,
                    high REAL NOT NULL,
                    low REAL NOT NULL,
                    close REAL NOT NULL,
                    volume REAL NOT NULL
                )
                """
            )
            rows = [
                (
                    "okx",
                    "BTC-USDT-SWAP",
                    "1m",
                    "2026-07-26T00:00:00Z",
                    "2026-07-26T00:01:00Z",
                    1,
                    100,
                    102,
                    99,
                    101,
                    10,
                ),
                (
                    "okx",
                    "BTC-USDT-SWAP",
                    "1m",
                    "2026-07-26T00:01:00Z",
                    "2026-07-26T00:02:00Z",
                    1,
                    101,
                    103,
                    100,
                    102,
                    11,
                ),
                (
                    "okx",
                    "BTC-USDT-SWAP",
                    "1m",
                    "2026-07-26T00:02:00Z",
                    "2026-07-26T00:03:00Z",
                    1,
                    102,
                    104,
                    101,
                    103,
                    12,
                ),
                (
                    "okx",
                    "BTC-USDT-SWAP",
                    "1m",
                    "2026-07-26T00:03:00Z",
                    "2026-07-26T00:04:00Z",
                    0,
                    103,
                    105,
                    102,
                    104,
                    13,
                ),
            ]
            if omit_middle:
                rows.pop(1)
            if duplicate:
                rows.insert(1, rows[0])
            connection.executemany(
                "INSERT INTO market_klines VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
        connection.commit()
    finally:
        connection.close()
    return path


def _export(
    source: Path,
    output: Path,
    *,
    now: datetime = NOW,
    required_partitions: tuple[tuple[str, str, str], ...] | None = None,
) -> dict[str, object]:
    return export_immutable_klines(
        source_sqlite=source,
        expected_source_sha256=_sha256(source),
        output_dir=output,
        dataset_version=VERSION,
        source_head=HEAD,
        now=now,
        required_partitions=required_partitions,
    )


def _add_stale_partition(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.executemany(
            "INSERT INTO market_klines VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    "coinbase",
                    "BTC-USD",
                    "1m",
                    1704240000000,
                    "2024-01-03T00:00:00+00:00",
                    1704240059999,
                    "2024-01-03T00:00:59.999000+00:00",
                    40_000,
                    40_100,
                    39_900,
                    40_050,
                    1,
                ),
                (
                    "coinbase",
                    "BTC-USD",
                    "1m",
                    1704240060000,
                    "2024-01-03T00:01:00+00:00",
                    1704240119999,
                    "2024-01-03T00:01:59.999000+00:00",
                    40_050,
                    40_150,
                    39_950,
                    40_100,
                    1,
                ),
            ],
        )


def test_ready_fixture_exports_schema_valid_deterministic_finalized_tables(
    tmp_path: Path,
) -> None:
    source = _create_source(tmp_path / "snapshot.sqlite")
    source_hash = _sha256(source)
    first = tmp_path / "export-a"
    second = tmp_path / "export-b"

    report = _export(source, first)
    _export(source, second)

    assert report["status"] == "quality_checked"
    assert report["readiness"] == {
        "quality_checked": True,
        "research_ready": False,
        "backtest_ready": False,
        "promotion_evidence_ready": False,
    }
    assert _sha256(source) == source_hash
    assert not list(first.rglob("*.db"))
    assert not list(first.rglob("*.sqlite"))
    assert not list(first.rglob("*.sqlite3"))

    attestation = json.loads((first / ATTESTATION_NAME).read_text(encoding="utf-8"))
    jsonschema.validate(
        attestation,
        json.loads(SCHEMA.read_text(encoding="utf-8")),
    )
    assert attestation == json.loads(
        (second / ATTESTATION_NAME).read_text(encoding="utf-8")
    )
    assert attestation["lineage"]["source_sha256"] == source_hash
    assert attestation["common_end"] == "2026-07-26T00:02:00Z"
    assert attestation["intervals"][0]["in_progress_count"] == 1
    assert attestation["intervals"][0]["in_progress_excluded"] is True

    table = first / attestation["files"][0]["path"]
    rows = [json.loads(line) for line in table.read_text(encoding="utf-8").splitlines()]
    assert [row["event_time"] for row in rows] == [
        "2026-07-26T00:00:00Z",
        "2026-07-26T00:01:00Z",
        "2026-07-26T00:02:00Z",
    ]
    assert all(row["is_finalized"] is True for row in rows)
    assert _sha256(table) == attestation["files"][0]["sha256"]
    assert table.read_bytes() == (
        second / attestation["files"][0]["path"]
    ).read_bytes()


def test_export_canonicalizes_float_tails_and_boundary_ohlcv_values(
    tmp_path: Path,
) -> None:
    source = _create_source(tmp_path / "decimal-tail.sqlite")
    with sqlite3.connect(source) as connection:
        connection.executemany(
            "UPDATE market_klines SET volume = ? WHERE event_time = ?",
            [
                (0.0012000000000000001, "2026-07-26T00:00:00Z"),
                (0.000000000000000001, "2026-07-26T00:01:00Z"),
                (1_000_000_000_000_000_000.0, "2026-07-26T00:02:00Z"),
            ],
        )
        connection.execute(
            "UPDATE market_klines SET open = ? WHERE event_time = ?",
            (100.00000000000001, "2026-07-26T00:00:00Z"),
        )
        connection.commit()

    output = tmp_path / "decimal-tail-export"
    _export(source, output)
    attestation = json.loads(
        (output / ATTESTATION_NAME).read_text(encoding="utf-8")
    )
    table = output / attestation["files"][0]["path"]
    raw = table.read_text(encoding="utf-8")
    assert "0.0012000000000000001" not in raw
    assert '"volume":0.0012' in raw
    assert '"volume":0.000000000000000001' in raw
    assert '"volume":1000000000000000000' in raw

    rows = [json.loads(line) for line in raw.splitlines()]
    for row in rows:
        for field in ("open", "high", "low", "close", "volume"):
            value, reason = dataready_consumer_module._strict_payload_decimal(
                row[field]
            )
            assert value is not None and reason == "", (field, row[field], reason)


def test_export_rejects_nextafter_above_decimal18_boundary_but_accepts_exact_limit():
    exact = _canonical_numeric_text(1_000_000_000_000_000_000.0)
    assert exact == "1000000000000000000"
    above = math.nextafter(1_000_000_000_000_000_000.0, math.inf)
    with pytest.raises(KlineExportBlocked) as caught:
        _canonical_numeric_text(above)
    assert caught.value.blockers == ("export_numeric_range_invalid",)
    value, reason = dataready_consumer_module._strict_payload_decimal(above)
    assert value is None and reason == "range"


def test_current_main_close_time_source_derives_pit_and_excludes_future_row(
    tmp_path: Path,
) -> None:
    source = _create_source(tmp_path / "legacy.sqlite", legacy=True)
    output = tmp_path / "exported"

    report = _export(source, output)

    assert report["status"] == "quality_checked"
    attestation = json.loads(
        (output / ATTESTATION_NAME).read_text(encoding="utf-8")
    )
    jsonschema.validate(
        attestation,
        json.loads(SCHEMA.read_text(encoding="utf-8")),
    )
    assert attestation["source_time_semantics"] == "derived_from_close_time"
    assert attestation["lineage"]["explicit_time_derivation_used"] is True
    assert attestation["lineage"]["explicit_finalized_derivation_used"] is True
    assert attestation["lineage"]["source_event_time_field"] == "close_time"
    assert attestation["lineage"]["source_available_time_field"] == "close_time"
    assert (
        attestation["lineage"]["source_finalized_policy"]
        == "close_time_lte_generated_at"
    )
    assert attestation["lineage"]["source_close_time_ms_field"] == "close_time_ms"
    assert (
        attestation["lineage"]["source_close_time_validation_policy"]
        == "close_time_ms_equals_iso_epoch_ms_and_inclusive_interval_end"
    )
    assert attestation["lineage"]["source_open_time_ms_field"] == "open_time_ms"
    assert (
        attestation["lineage"]["source_open_close_duration_policy"]
        == "open_aligned_close_minus_open_equals_interval_ms_minus_one"
    )
    assert attestation["intervals"][0]["finalized_count"] == 2
    assert attestation["intervals"][0]["in_progress_count"] == 1
    table = output / attestation["files"][0]["path"]
    rows = [
        json.loads(line)
        for line in table.read_text(encoding="utf-8").splitlines()
    ]
    assert [row["event_time"] for row in rows] == [
        "2026-07-25T23:59:59.999000Z",
        "2026-07-26T00:00:59.999000Z",
    ]
    assert all(row["available_time"] == row["event_time"] for row in rows)
    assert all(row["is_finalized"] is True for row in rows)


def test_timestamp_only_legacy_source_remains_blocked(
    tmp_path: Path,
) -> None:
    source = _create_source(
        tmp_path / "unsupported-legacy.sqlite",
        unsupported_legacy=True,
    )
    output = tmp_path / "must-not-exist"

    with pytest.raises(KlineExportBlocked) as caught:
        _export(source, output)

    assert "source_schema_supported_time_contract_missing" in caught.value.blockers
    assert not output.exists()


@pytest.mark.parametrize(
    ("case", "expected_blocker"),
    [
        ("mismatch", "source_close_time_ms_mismatch"),
        ("boundary", "source_close_time_interval_boundary_invalid"),
        ("open_boundary", "source_open_time_interval_boundary_invalid"),
        ("duration", "source_open_close_duration_invalid"),
    ],
)
def test_legacy_close_time_milliseconds_and_boundary_are_verified(
    tmp_path: Path,
    case: str,
    expected_blocker: str,
) -> None:
    source = _create_source(tmp_path / f"{case}.sqlite", legacy=True)
    with sqlite3.connect(source) as connection:
        if case == "mismatch":
            connection.execute(
                """
                UPDATE market_klines
                SET close_time_ms = close_time_ms + 123
                WHERE open_time_ms = 1785023940000
                """
            )
        else:
            if case == "boundary":
                connection.execute(
                    """
                    UPDATE market_klines
                    SET close_time_ms = 1785024029999,
                        close_time = '2026-07-26T00:00:29.999000+00:00'
                    WHERE open_time_ms = 1785023940000
                    """
                )
            elif case == "open_boundary":
                connection.execute(
                    """
                    UPDATE market_klines
                    SET open_time_ms = open_time_ms + 1
                    WHERE open_time_ms = 1785023940000
                    """
                )
            else:
                connection.execute(
                    """
                    UPDATE market_klines
                    SET open_time_ms = 1785023880000
                    WHERE open_time_ms = 1785023940000
                    """
                )

    with pytest.raises(KlineExportBlocked) as caught:
        _export(source, tmp_path / "must-not-exist")

    assert any(
        blocker.startswith(expected_blocker)
        for blocker in caught.value.blockers
    )


def test_partition_selection_is_explicit_and_default_all_remains_strict(
    tmp_path: Path,
) -> None:
    source = _create_source(tmp_path / "mixed-freshness.sqlite", legacy=True)
    _add_stale_partition(source)

    with pytest.raises(KlineExportBlocked) as caught:
        _export(source, tmp_path / "default-all")
    assert "kline_common_end_freshness_sla_breached" in caught.value.blockers

    output = tmp_path / "selected"
    report = _export(
        source,
        output,
        required_partitions=(("okx", "BTC-USDT-SWAP", "1m"),),
    )
    assert report["status"] == "quality_checked"
    attestation = json.loads(
        (output / ATTESTATION_NAME).read_text(encoding="utf-8")
    )
    selection = attestation["partition_selection"]
    assert selection["mode"] == "explicit_required_partitions"
    assert selection["policy_id"] == "explicit_required_partitions_v1"
    assert selection["required_partitions"] == [
        {
            "venue": "okx",
            "instrument_id": "BTC-USDT-SWAP",
            "interval": "1m",
        }
    ]
    assert selection["included_partitions"] == selection["required_partitions"]
    assert selection["excluded_partitions"] == [
        {
            "venue": "coinbase",
            "instrument_id": "BTC-USD",
            "interval": "1m",
            "reason": "excluded_non_required",
        }
    ]
    inventory = attestation["source_partition_inventory"]
    assert {
        (
            item["venue"],
            item["instrument_id"],
            item["interval"],
            item["selection_status"],
            item["selection_policy"],
        )
        for item in inventory
    } == {
        (
            "okx",
            "BTC-USDT-SWAP",
            "1m",
            "included_required",
            "explicit_required_partitions_v1",
        ),
        (
            "coinbase",
            "BTC-USD",
            "1m",
            "excluded_non_required",
            "explicit_required_partitions_v1",
        ),
    }
    assert all(item["total_row_count"] > 0 for item in inventory)
    assert all(len(item["partition_inventory_sha256"]) == 64 for item in inventory)
    assert len(attestation["source_partition_inventory_sha256"]) == 64
    assert {
        (
            item["venue"],
            item["instrument_id"],
            item["interval"],
        )
        for item in attestation["intervals"]
    } == {("okx", "BTC-USDT-SWAP", "1m")}


def test_missing_required_partition_blocks_without_output(tmp_path: Path) -> None:
    source = _create_source(tmp_path / "snapshot.sqlite", legacy=True)
    output = tmp_path / "must-not-exist"

    with pytest.raises(KlineExportBlocked) as caught:
        _export(
            source,
            output,
            required_partitions=(("binance_spot", "BTCUSDT", "1h"),),
        )

    assert (
        "required_partition_missing:binance_spot:BTCUSDT:1h"
        in caught.value.blockers
    )
    assert not output.exists()


def test_current_main_binance_source_rejects_nonapproved_subset(
    tmp_path: Path,
) -> None:
    source = _create_source(tmp_path / "current-main.sqlite", legacy=True)
    connection = sqlite3.connect(source)
    try:
        connection.execute(
            """
            UPDATE market_klines
            SET exchange = 'binance_spot', symbol = 'BTCUSDT', interval = '1h'
            """
        )
        connection.commit()
    finally:
        connection.close()
    output = tmp_path / "must-not-exist"

    with pytest.raises(KlineExportBlocked) as caught:
        _export(
            source,
            output,
            required_partitions=(("binance_spot", "BTCUSDT", "1h"),),
        )

    assert (
        "approved_current_main_required_partition_set_mismatch"
        in caught.value.blockers
    )
    assert not output.exists()


def test_cli_returns_nonzero_for_legacy_source_without_publishing(
    tmp_path: Path,
) -> None:
    source = _create_source(
        tmp_path / "legacy.sqlite",
        unsupported_legacy=True,
    )
    output = tmp_path / "must-not-exist"

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/build_btc_kline_immutable_export.py",
            "--source",
            str(source),
            "--source-sha256",
            _sha256(source),
            "--output-dir",
            str(output),
            "--dataset-version",
            VERSION,
            "--source-head",
            HEAD,
            "--now",
            "2026-07-26T00:05:00Z",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert completed.returncode == 2
    report = json.loads(completed.stdout)
    assert report["status"] == "blocked"
    assert "source_schema_supported_time_contract_missing" in report["blockers"]
    assert not output.exists()


@pytest.mark.parametrize(
    ("source_kwargs", "now", "expected_blocker"),
    [
        ({"omit_middle": True}, NOW, "kline_missing_rows:okx:BTC-USDT-SWAP:1m"),
        ({"duplicate": True}, NOW, "source_finalized_duplicate_key_groups:1"),
        ({}, datetime(2026, 7, 29, tzinfo=timezone.utc), "kline_common_end_freshness_sla_breached"),
    ],
)
def test_quality_defects_fail_closed_without_partial_output(
    tmp_path: Path,
    source_kwargs: dict[str, bool],
    now: datetime,
    expected_blocker: str,
) -> None:
    source = _create_source(tmp_path / "snapshot.sqlite", **source_kwargs)
    output = tmp_path / "must-not-exist"

    with pytest.raises(KlineExportBlocked) as caught:
        _export(source, output, now=now)

    assert expected_blocker in caught.value.blockers
    assert not output.exists()


def test_source_hash_mismatch_blocks_before_export(tmp_path: Path) -> None:
    source = _create_source(tmp_path / "snapshot.sqlite")
    output = tmp_path / "must-not-exist"

    with pytest.raises(KlineExportBlocked) as caught:
        export_immutable_klines(
            source_sqlite=source,
            expected_source_sha256="0" * 64,
            output_dir=output,
            dataset_version=VERSION,
            source_head=HEAD,
            now=NOW,
        )

    assert caught.value.blockers == ("source_sqlite_sha256_mismatch",)
    assert not output.exists()


def test_export_is_accepted_by_shared_data_and_dataready_consumer(
    tmp_path: Path,
) -> None:
    source = _create_source(tmp_path / "snapshot.sqlite")
    exported = tmp_path / "exported"
    report = _export(source, exported)
    attestation = json.loads(
        (exported / ATTESTATION_NAME).read_text(encoding="utf-8")
    )
    shared_root = tmp_path / "shared"
    published = publish_dataset(
        source=exported,
        shared_root=shared_root,
        dataset_id=DATASET_ID,
        dataset_version=VERSION,
        readiness_class="quality_checked",
        quality_status="pass",
        producer_role="data_steward",
        producer_commit=HEAD,
        schema_name="btc_kline_dataready_attestation_v1",
        coverage_start=attestation["coverage_start"],
        coverage_end=attestation["coverage_end"],
    )
    manifest = published["manifest"]

    resolved = resolve_manifest_payload(
        manifest,
        shared_root=shared_root,
        verify_files=True,
    )
    assert (resolved / ATTESTATION_NAME).is_file()

    consumption = consume_btc_dataready(
        runtime_pointer={
            "schema_version": "mutable_runtime_storage_pointer_v1",
            "owner_role": "data_steward",
            "immutable_publication": {
                "dataset_id": DATASET_ID,
                "status": "published",
                "blockers": [],
            },
            "guardrails": {
                "runtime_database_is_promotion_evidence": False,
                "promotion_unlock_allowed": False,
                "paper_or_live_unlock_allowed": False,
                "private_endpoint_used": False,
                "order_endpoint_used": False,
            },
        },
        snapshot_manifest=manifest,
        l2_manifest=None,
        shared_root=shared_root,
        current_head=HEAD,
        now=NOW,
        commit_exists=lambda commit: commit == HEAD,
    )
    assert consumption["manifest_checks"]["kline_snapshot"]["status"] == "pass"
    assert consumption["data_checks"]["klines"]["status"] == "pass"
    assert consumption["status"] == "blocked"
    assert "okx_timestamp_aligned_l2_manifest_not_published" in consumption["blockers"]
    assert report["guardrails"]["shared_data_published"] is False
