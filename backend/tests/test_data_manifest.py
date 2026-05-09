from __future__ import annotations

import hashlib
import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from quant_us.data.storage.data_manifest import (
    DataManifest,
    DataManifestStore,
    build_manifest_from_quality,
    validate_manifest_for_promotion,
)


class TestDataManifestConstruction(unittest.TestCase):
    """DataManifest dataclass construction, properties manifest_id and is_usable."""

    def test_default_construction(self) -> None:
        m = DataManifest(
            data_version="qs-v1-test-AAPL-1d-20240101",
            source="test",
            symbol="AAPL",
            interval="1d",
        )
        self.assertEqual(m.data_version, "qs-v1-test-AAPL-1d-20240101")
        self.assertEqual(m.source, "test")
        self.assertEqual(m.symbol, "AAPL")
        self.assertEqual(m.interval, "1d")
        self.assertEqual(m.asset_class, "equity")  # default
        self.assertEqual(m.timezone, "UTC")
        self.assertEqual(m.adjustment, "raw")
        self.assertEqual(m.adjustment_policy, "")
        self.assertEqual(m.corporate_action_adjustment, "")
        self.assertEqual(m.checksum, "")
        self.assertEqual(m.effective_checksum, "")
        self.assertEqual(m.start, "")
        self.assertEqual(m.end, "")
        self.assertEqual(m.row_count, 0)
        self.assertEqual(m.expected_rows, 0)
        self.assertEqual(m.coverage_pct, 0.0)
        self.assertEqual(m.quality_score, 0.0)
        self.assertEqual(m.fields, [])
        self.assertEqual(m.issues, [])
        self.assertEqual(m.cleaning, {})
        self.assertEqual(m.raw_path, "")
        self.assertEqual(m.cleaned_path, "")
        self.assertEqual(m.git_commit, "")
        self.assertEqual(m.universe_id, "")
        self.assertEqual(m.universe_source, "")
        self.assertEqual(m.survivorship_bias_risk, "unknown")
        self.assertIsInstance(m.created_at, str)

    def test_manifest_id_is_deterministic(self) -> None:
        m1 = DataManifest(
            data_version="qs-v1-test-AAPL-1d-20240101",
            source="test",
            symbol="AAPL",
            interval="1d",
            start="2024-01-01",
            end="2024-12-31",
            row_count=252,
        )
        m2 = DataManifest(
            data_version="qs-v1-test-AAPL-1d-20240101",
            source="test",
            symbol="AAPL",
            interval="1d",
            start="2024-01-01",
            end="2024-12-31",
            row_count=252,
        )
        self.assertEqual(m1.manifest_id, m2.manifest_id)
        self.assertEqual(len(m1.manifest_id), 16)

    def test_manifest_id_format(self) -> None:
        m = DataManifest(
            data_version="v1",
            source="src",
            symbol="SPY",
            interval="1h",
            start="2024-01-01",
            end="2024-01-02",
            row_count=10,
        )
        payload = "src:SPY:1h:2024-01-01:2024-01-02:10"
        expected_hash = hashlib.sha256(payload.encode()).hexdigest()[:16]
        self.assertEqual(m.manifest_id, expected_hash)

    def test_manifest_id_differs_when_fields_change(self) -> None:
        m_a = DataManifest(
            data_version="v1", source="src", symbol="AAPL", interval="1d", row_count=100
        )
        m_b = DataManifest(
            data_version="v1", source="src", symbol="AAPL", interval="1d", row_count=200
        )
        self.assertNotEqual(m_a.manifest_id, m_b.manifest_id)

    def test_is_usable_true_when_both_above_threshold(self) -> None:
        m = DataManifest(
            data_version="v1",
            source="test",
            symbol="AAPL",
            interval="1d",
            coverage_pct=95.0,
            quality_score=85.0,
        )
        self.assertTrue(m.is_usable)

    def test_is_usable_false_when_coverage_below_90(self) -> None:
        m = DataManifest(
            data_version="v1",
            source="test",
            symbol="AAPL",
            interval="1d",
            coverage_pct=89.99,
            quality_score=85.0,
        )
        self.assertFalse(m.is_usable)

    def test_is_usable_false_when_quality_score_below_80(self) -> None:
        m = DataManifest(
            data_version="v1",
            source="test",
            symbol="AAPL",
            interval="1d",
            coverage_pct=95.0,
            quality_score=79.999,
        )
        self.assertFalse(m.is_usable)

    def test_is_usable_false_when_both_below_threshold(self) -> None:
        m = DataManifest(
            data_version="v1",
            source="test",
            symbol="AAPL",
            interval="1d",
            coverage_pct=50.0,
            quality_score=40.0,
        )
        self.assertFalse(m.is_usable)

    def test_is_usable_exact_boundary_passes(self) -> None:
        """Boundary: coverage_pct == 90.0 exactly and quality_score == 80.0 exactly."""
        m = DataManifest(
            data_version="v1",
            source="test",
            symbol="AAPL",
            interval="1d",
            coverage_pct=90.0,
            quality_score=80.0,
        )
        self.assertTrue(m.is_usable)


class TestDataManifestStoreRoundTrip(unittest.TestCase):
    """DataManifestStore write/read round-trip consistency."""

    def test_write_and_read_returns_same_manifest(self) -> None:
        with TemporaryDirectory() as directory:
            store = DataManifestStore(root=directory)
            original = DataManifest(
                data_version="qs-v1-test-AAPL-1d-20240101",
                source="test",
                symbol="AAPL",
                interval="1d",
                asset_class="equity",
                timezone="UTC",
                adjustment="split_adjusted",
                adjustment_policy="split_adjusted",
                corporate_action_adjustment="split_adjusted",
                start="2024-01-01T00:00:00+00:00",
                end="2024-12-31T23:59:59+00:00",
                row_count=252,
                expected_rows=252,
                coverage_pct=100.0,
                fingerprint="abc123",
                checksum="abc123",
                quality_score=95.0,
                fields=["timestamp_utc", "open", "high", "low", "close", "volume"],
                issues=[],
                cleaning={"duplicate_timestamps_removed": 0, "invalid_ohlc_removed": 0},
                raw_path="/data/raw/test.parquet",
                cleaned_path="/data/cleaned/test.parquet",
                git_commit="abc123def456",
                universe_id="us-core-v1",
                universe_source="universe_builder",
                survivorship_bias_risk="clean",
            )

            store.write(original)
            loaded = store.read(original.data_version)

            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.data_version, original.data_version)
            self.assertEqual(loaded.source, original.source)
            self.assertEqual(loaded.symbol, original.symbol)
            self.assertEqual(loaded.interval, original.interval)
            self.assertEqual(loaded.asset_class, original.asset_class)
            self.assertEqual(loaded.timezone, original.timezone)
            self.assertEqual(loaded.adjustment, original.adjustment)
            self.assertEqual(loaded.adjustment_policy, original.adjustment_policy)
            self.assertEqual(loaded.corporate_action_adjustment, original.corporate_action_adjustment)
            self.assertEqual(loaded.start, original.start)
            self.assertEqual(loaded.end, original.end)
            self.assertEqual(loaded.row_count, original.row_count)
            self.assertEqual(loaded.expected_rows, original.expected_rows)
            self.assertEqual(loaded.coverage_pct, original.coverage_pct)
            self.assertEqual(loaded.fingerprint, original.fingerprint)
            self.assertEqual(loaded.checksum, original.checksum)
            self.assertEqual(loaded.quality_score, original.quality_score)
            self.assertEqual(loaded.fields, original.fields)
            self.assertEqual(loaded.issues, original.issues)
            self.assertEqual(loaded.cleaning, original.cleaning)
            self.assertEqual(loaded.raw_path, original.raw_path)
            self.assertEqual(loaded.cleaned_path, original.cleaned_path)
            self.assertEqual(loaded.git_commit, original.git_commit)
            self.assertEqual(loaded.universe_id, original.universe_id)
            self.assertEqual(loaded.universe_source, original.universe_source)
            self.assertEqual(loaded.survivorship_bias_risk, original.survivorship_bias_risk)

    def test_read_legacy_manifest_defaults_v2_fields(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            payload = {
                "data_version": "qs-v1-test-AAPL-1d-legacy",
                "source": "test",
                "symbol": "AAPL",
                "interval": "1d",
                "adjustment": "raw",
                "coverage_pct": 100.0,
                "quality_score": 95.0,
                "row_count": 252,
                "checksum": "a" * 64,
            }
            (root / "qs-v1-test-AAPL-1d-legacy.json").write_text(json.dumps(payload), encoding="utf-8")

            loaded = DataManifestStore(root=directory).read("qs-v1-test-AAPL-1d-legacy")

            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.adjustment, "raw")
            self.assertEqual(loaded.adjustment_policy, "raw")
            self.assertEqual(loaded.corporate_action_adjustment, "raw")
            self.assertEqual(loaded.universe_id, "")
            self.assertEqual(loaded.universe_source, "")
            self.assertEqual(loaded.survivorship_bias_risk, "unknown")

    def test_read_returns_none_for_missing_version(self) -> None:
        with TemporaryDirectory() as directory:
            store = DataManifestStore(root=directory)
            result = store.read("nonexistent")
            self.assertIsNone(result)

    def test_read_returns_none_for_non_data_manifest_payload(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "run_ubt.json"
            path.write_text(
                json.dumps(
                    {
                        "run_id": "ubt_1",
                        "engine": "event_driven",
                        "data_version": "qs-yfinance-AAPL-1d-test",
                        "source": "yfinance",
                        "symbol": "AAPL",
                        "interval": "1d",
                    }
                )
            )
            store = DataManifestStore(root=directory)
            self.assertIsNone(store.read("run_ubt"))

    def test_overwrite_existing_manifest(self) -> None:
        with TemporaryDirectory() as directory:
            store = DataManifestStore(root=directory)
            m1 = DataManifest(
                data_version="qs-v1-test-AAPL-1d-v1",
                source="test",
                symbol="AAPL",
                interval="1d",
                row_count=100,
            )
            m2 = DataManifest(
                data_version="qs-v1-test-AAPL-1d-v1",
                source="test",
                symbol="AAPL",
                interval="1d",
                row_count=200,
            )

            store.write(m1)
            store.write(m2)
            loaded = store.read("qs-v1-test-AAPL-1d-v1")
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.row_count, 200)


class TestDataManifestStoreReadLatest(unittest.TestCase):
    """DataManifestStore.read_latest returns the most recent manifest."""

    def test_read_latest_returns_most_recent(self) -> None:
        with TemporaryDirectory() as directory:
            store = DataManifestStore(root=directory)
            early = DataManifest(
                data_version="qs-test-AAPL-1d-20240101",
                source="test",
                symbol="AAPL",
                interval="1d",
                start="2024-01-01",
                end="2024-06-30",
                row_count=125,
            )
            later = DataManifest(
                data_version="qs-test-AAPL-1d-20240701",
                source="test",
                symbol="AAPL",
                interval="1d",
                start="2024-07-01",
                end="2024-12-31",
                row_count=127,
            )
            store.write(early)
            store.write(later)

            latest = store.read_latest(source="test", symbol="AAPL", interval="1d")
            self.assertIsNotNone(latest)
            self.assertEqual(latest.data_version, "qs-test-AAPL-1d-20240701")

    def test_read_latest_returns_none_when_no_match(self) -> None:
        with TemporaryDirectory() as directory:
            store = DataManifestStore(root=directory)
            result = store.read_latest(source="test", symbol="AAPL", interval="1d")
            self.assertIsNone(result)

    def test_read_latest_respects_glob_pattern(self) -> None:
        """Only manifests matching source, symbol, interval are candidates."""
        with TemporaryDirectory() as directory:
            store = DataManifestStore(root=directory)
            aapl = DataManifest(
                data_version="qs-test-AAPL-1d-v1",
                source="test",
                symbol="AAPL",
                interval="1d",
            )
            spy = DataManifest(
                data_version="qs-test-SPY-1d-v1",
                source="test",
                symbol="SPY",
                interval="1d",
            )
            store.write(aapl)
            store.write(spy)

            latest = store.read_latest(source="test", symbol="AAPL", interval="1d")
            self.assertIsNotNone(latest)
            self.assertEqual(latest.symbol, "AAPL")


class TestDataManifestStoreListManifests(unittest.TestCase):
    """DataManifestStore.list_manifests filtering."""

    def test_list_all_manifests(self) -> None:
        with TemporaryDirectory() as directory:
            store = DataManifestStore(root=directory)
            store.write(
                DataManifest(
                    data_version="v1-a", source="src1", symbol="AAPL", interval="1d"
                )
            )
            store.write(
                DataManifest(
                    data_version="v1-b", source="src2", symbol="SPY", interval="1h"
                )
            )
            store.write(
                DataManifest(
                    data_version="v1-c", source="src1", symbol="MSFT", interval="1d"
                )
            )

            all_ = store.list_manifests()
            self.assertEqual(len(all_), 3)

    def test_list_filter_by_source(self) -> None:
        with TemporaryDirectory() as directory:
            store = DataManifestStore(root=directory)
            store.write(
                DataManifest(
                    data_version="v1", source="src1", symbol="AAPL", interval="1d"
                )
            )
            store.write(
                DataManifest(
                    data_version="v2", source="src2", symbol="SPY", interval="1d"
                )
            )
            filtered = store.list_manifests(source="src1")
            self.assertEqual(len(filtered), 1)
            self.assertEqual(filtered[0].source, "src1")

    def test_list_filter_by_symbol_case_insensitive(self) -> None:
        with TemporaryDirectory() as directory:
            store = DataManifestStore(root=directory)
            store.write(
                DataManifest(
                    data_version="v1", source="src", symbol="AAPL", interval="1d"
                )
            )
            filtered = store.list_manifests(symbol="aapl")
            self.assertEqual(len(filtered), 1)
            self.assertEqual(filtered[0].symbol, "AAPL")

    def test_list_filter_by_interval(self) -> None:
        with TemporaryDirectory() as directory:
            store = DataManifestStore(root=directory)
            store.write(
                DataManifest(
                    data_version="v1", source="src", symbol="AAPL", interval="1d"
                )
            )
            store.write(
                DataManifest(
                    data_version="v2", source="src", symbol="AAPL", interval="1h"
                )
            )
            filtered = store.list_manifests(interval="1h")
            self.assertEqual(len(filtered), 1)
            self.assertEqual(filtered[0].interval, "1h")

    def test_list_filter_combined(self) -> None:
        with TemporaryDirectory() as directory:
            store = DataManifestStore(root=directory)
            store.write(
                DataManifest(
                    data_version="v1",
                    source="src1",
                    symbol="AAPL",
                    interval="1d",
                )
            )
            store.write(
                DataManifest(
                    data_version="v2",
                    source="src1",
                    symbol="AAPL",
                    interval="1h",
                )
            )
            store.write(
                DataManifest(
                    data_version="v3",
                    source="src2",
                    symbol="AAPL",
                    interval="1d",
                )
            )
            filtered = store.list_manifests(source="src1", symbol="AAPL", interval="1d")
            self.assertEqual(len(filtered), 1)
            self.assertEqual(filtered[0].data_version, "v1")

    def test_list_empty_store_returns_empty_list(self) -> None:
        with TemporaryDirectory() as directory:
            store = DataManifestStore(root=directory)
            self.assertEqual(store.list_manifests(), [])

    def test_list_nonexistent_directory(self) -> None:
        store = DataManifestStore(root="/tmp/does_not_exist_xyz")
        self.assertEqual(store.list_manifests(), [])
        self.assertIsNone(store.read_latest(source="x", symbol="y", interval="z"))

    def test_list_skips_backtest_run_manifests(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            store = DataManifestStore(root=root)
            store.write(
                DataManifest(
                    data_version="qs-yfinance-AAPL-1d-v1",
                    source="yfinance",
                    symbol="AAPL",
                    interval="1d",
                )
            )
            (root / "run_ubt_1.json").write_text(
                json.dumps(
                    {
                        "run_id": "ubt_1",
                        "engine": "event_driven",
                        "data_version": "qs-yfinance-SPY-1d-run",
                        "source": "yfinance",
                        "symbol": "SPY",
                        "interval": "1d",
                    }
                )
            )

            manifests = store.list_manifests()
            self.assertEqual(len(manifests), 1)
            self.assertEqual(manifests[0].data_version, "qs-yfinance-AAPL-1d-v1")


class TestBuildManifestFromQuality(unittest.TestCase):
    """build_manifest_from_quality with complete and incomplete data."""

    def test_complete_quality_dict(self) -> None:
        quality = {
            "data_version": "qs-v1-test-AAPL-1d-20240101",
            "first_timestamp": "2024-01-01T00:00:00+00:00",
            "last_timestamp": "2024-12-31T23:59:59+00:00",
            "row_count": 252,
            "expected_rows": 252,
            "coverage_pct": 100.0,
            "fingerprint": "a" * 64,
            "quality_score": 95.0,
            "issues": [{"code": "test_warning", "message": "nothing serious"}],
            "duplicate_timestamps": 0,
            "invalid_ohlc": 1,
            "non_positive_prices": 0,
            "cleaning_loss_rows": 1,
            "missing_bars": 0,
        }
        manifest = build_manifest_from_quality(
            quality=quality,
            source="test",
            symbol="aapl",  # should be uppercased
            interval="1d",
            asset_class="equity",
            raw_path="/data/raw/test.parquet",
            cleaned_path="/data/cleaned/test.parquet",
            git_commit="abc123",
        )

        self.assertEqual(manifest.data_version, "qs-v1-test-AAPL-1d-20240101")
        self.assertEqual(manifest.source, "test")
        self.assertEqual(manifest.symbol, "AAPL")  # uppercased
        self.assertEqual(manifest.interval, "1d")
        self.assertEqual(manifest.asset_class, "equity")
        self.assertEqual(manifest.timezone, "UTC")
        self.assertEqual(manifest.adjustment, "raw")
        self.assertEqual(manifest.adjustment_policy, "raw")
        self.assertEqual(manifest.corporate_action_adjustment, "raw")
        self.assertEqual(manifest.start, "2024-01-01T00:00:00+00:00")
        self.assertEqual(manifest.end, "2024-12-31T23:59:59+00:00")
        self.assertEqual(manifest.row_count, 252)
        self.assertEqual(manifest.expected_rows, 252)
        self.assertEqual(manifest.coverage_pct, 100.0)
        self.assertEqual(manifest.fingerprint, "a" * 64)
        self.assertEqual(manifest.checksum, "a" * 64)
        self.assertEqual(manifest.quality_score, 95.0)
        self.assertEqual(
            manifest.fields,
            ["timestamp_utc", "symbol", "open", "high", "low", "close", "volume"],
        )
        self.assertEqual(
            manifest.issues, [{"code": "test_warning", "message": "nothing serious"}]
        )
        self.assertEqual(
            manifest.cleaning,
            {
                "duplicate_timestamps_removed": 0,
                "invalid_ohlc_removed": 1,
                "non_positive_prices_removed": 0,
                "cleaning_loss_rows": 1,
                "missing_bars": 0,
            },
        )
        self.assertEqual(manifest.raw_path, "/data/raw/test.parquet")
        self.assertEqual(manifest.cleaned_path, "/data/cleaned/test.parquet")
        self.assertEqual(manifest.git_commit, "abc123")
        self.assertEqual(manifest.universe_id, "")
        self.assertEqual(manifest.universe_source, "")
        self.assertEqual(manifest.survivorship_bias_risk, "unknown")
        self.assertIsInstance(manifest.created_at, str)

    def test_missing_keys_uses_defaults(self) -> None:
        """Empty dict should not crash; all fields get defaults."""
        quality: dict = {}
        manifest = build_manifest_from_quality(
            quality=quality,
            source="test",
            symbol="AAPL",
            interval="1d",
        )

        self.assertEqual(manifest.data_version, "")
        self.assertEqual(manifest.source, "test")
        self.assertEqual(manifest.symbol, "AAPL")
        self.assertEqual(manifest.interval, "1d")
        self.assertEqual(manifest.start, "")
        self.assertEqual(manifest.end, "")
        self.assertEqual(manifest.row_count, 0)
        self.assertEqual(manifest.expected_rows, 0)
        self.assertEqual(manifest.coverage_pct, 0.0)
        self.assertEqual(manifest.fingerprint, "")
        self.assertEqual(manifest.checksum, "")
        self.assertEqual(manifest.quality_score, 0.0)
        self.assertEqual(manifest.fields, ["timestamp_utc", "symbol", "open", "high", "low", "close", "volume"])
        self.assertEqual(manifest.issues, [])
        self.assertEqual(
            manifest.cleaning,
            {
                "duplicate_timestamps_removed": 0,
                "invalid_ohlc_removed": 0,
                "non_positive_prices_removed": 0,
                "cleaning_loss_rows": 0,
                "missing_bars": 0,
            },
        )
        self.assertEqual(manifest.raw_path, "")
        self.assertEqual(manifest.cleaned_path, "")
        self.assertEqual(manifest.git_commit, "")
        self.assertEqual(manifest.adjustment_policy, "raw")
        self.assertEqual(manifest.corporate_action_adjustment, "raw")
        self.assertEqual(manifest.survivorship_bias_risk, "unknown")

    def test_partial_quality_dict(self) -> None:
        """Only some keys provided; missing ones get defaults."""
        quality = {
            "data_version": "partial-v1",
            "row_count": 100,
            "quality_score": 75.0,
        }
        manifest = build_manifest_from_quality(
            quality=quality,
            source="polygon",
            symbol="MSFT",
            interval="1min",
        )

        self.assertEqual(manifest.data_version, "partial-v1")
        self.assertEqual(manifest.source, "polygon")
        self.assertEqual(manifest.symbol, "MSFT")
        self.assertEqual(manifest.interval, "1min")
        self.assertEqual(manifest.row_count, 100)
        self.assertEqual(manifest.quality_score, 75.0)
        # fields not provided -> defaults
        self.assertEqual(manifest.start, "")
        self.assertEqual(manifest.end, "")
        self.assertEqual(manifest.expected_rows, 0)
        self.assertEqual(manifest.coverage_pct, 0.0)
        self.assertEqual(manifest.fingerprint, "")

    def test_cleaning_dict_keys_mapped_correctly(self) -> None:
        quality = {
            "duplicate_timestamps": 3,
            "invalid_ohlc": 5,
            "non_positive_prices": 1,
            "cleaning_loss_rows": 9,
            "missing_bars": 2,
        }
        manifest = build_manifest_from_quality(
            quality=quality, source="s", symbol="S", interval="1d"
        )
        self.assertEqual(manifest.cleaning["duplicate_timestamps_removed"], 3)
        self.assertEqual(manifest.cleaning["invalid_ohlc_removed"], 5)
        self.assertEqual(manifest.cleaning["non_positive_prices_removed"], 1)
        self.assertEqual(manifest.cleaning["cleaning_loss_rows"], 9)
        self.assertEqual(manifest.cleaning["missing_bars"], 2)

    def test_unexpected_extra_keys_ignored(self) -> None:
        """Extra keys in quality dict are ignored without error."""
        quality = {
            "data_version": "v1",
            "row_count": 50,
            "quality_score": 90.0,
            "some_random_extra_key": "should_not_cause_error",
            "another_weird_one": [1, 2, 3],
        }
        manifest = build_manifest_from_quality(
            quality=quality, source="s", symbol="S", interval="1d"
        )
        self.assertEqual(manifest.data_version, "v1")
        self.assertEqual(manifest.row_count, 50)

    def test_none_values_in_quality_use_defaults(self) -> None:
        quality = {"row_count": None, "coverage_pct": None, "quality_score": None,
                   "issues": None, "duplicate_timestamps": None}
        manifest = build_manifest_from_quality(
            quality=quality, source="s", symbol="S", interval="1d"
        )
        self.assertEqual(manifest.row_count, 0)
        self.assertEqual(manifest.coverage_pct, 0.0)
        self.assertEqual(manifest.quality_score, 0.0)
        self.assertEqual(manifest.issues, [])
        self.assertEqual(manifest.cleaning["duplicate_timestamps_removed"], 0)

    def test_symbol_is_uppercased(self) -> None:
        quality = {"data_version": "v1"}
        manifest = build_manifest_from_quality(
            quality=quality, source="src", symbol="aapl", interval="1d"
        )
        self.assertEqual(manifest.symbol, "AAPL")


class TestBuildManifestFromQualityRoundTrip(unittest.TestCase):
    """Full pipeline: build_manifest_from_quality -> write -> read -> verify."""

    def test_full_round_trip_via_store(self) -> None:
        quality = {
            "data_version": "qs-v2-polygon-SPY-1min-20250101",
            "first_timestamp": "2025-01-01T09:30:00+00:00",
            "last_timestamp": "2025-01-01T16:00:00+00:00",
            "row_count": 390,
            "expected_rows": 390,
            "coverage_pct": 100.0,
            "fingerprint": "deadbeef" * 8,
            "quality_score": 99.5,
            "issues": [],
            "duplicate_timestamps": 0,
            "invalid_ohlc": 0,
            "non_positive_prices": 0,
            "cleaning_loss_rows": 0,
            "missing_bars": 0,
        }
        with TemporaryDirectory() as directory:
            store = DataManifestStore(root=directory)
            manifest = build_manifest_from_quality(
                quality=quality,
                source="polygon",
                symbol="SPY",
                interval="1min",
                raw_path="/raw/spy.parquet",
                cleaned_path="/clean/spy.parquet",
                git_commit="def789",
            )

            store.write(manifest)
            loaded = store.read(manifest.data_version)

            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.data_version, manifest.data_version)
            self.assertEqual(loaded.source, manifest.source)
            self.assertEqual(loaded.symbol, manifest.symbol)
            self.assertEqual(loaded.interval, manifest.interval)
            self.assertEqual(loaded.start, manifest.start)
            self.assertEqual(loaded.end, manifest.end)
            self.assertEqual(loaded.row_count, manifest.row_count)
            self.assertEqual(loaded.coverage_pct, manifest.coverage_pct)
            self.assertEqual(loaded.quality_score, manifest.quality_score)
            self.assertEqual(loaded.fields, manifest.fields)
            self.assertEqual(loaded.cleaning, manifest.cleaning)
            self.assertEqual(loaded.raw_path, manifest.raw_path)
            self.assertEqual(loaded.cleaned_path, manifest.cleaned_path)
            self.assertEqual(loaded.git_commit, manifest.git_commit)


class TestDataManifestPromotionValidation(unittest.TestCase):
    """Promotion-grade manifest validation should fail fast on unsafe data lineage."""

    def _valid_manifest(self, **overrides) -> DataManifest:
        payload = {
            "data_version": "qs-yfinance-AAPL-1d-test",
            "source": "yfinance",
            "symbol": "AAPL",
            "interval": "1d",
            "asset_class": "equity",
            "timezone": "UTC",
            "adjustment": "raw",
            "start": "2024-01-01T00:00:00+00:00",
            "end": "2024-12-31T00:00:00+00:00",
            "row_count": 252,
            "expected_rows": 252,
            "coverage_pct": 100.0,
            "fingerprint": "a" * 64,
            "checksum": "a" * 64,
            "quality_score": 98.0,
            "cleaning": {
                "duplicate_timestamps_removed": 0,
                "invalid_ohlc_removed": 0,
                "non_positive_prices_removed": 0,
                "cleaning_loss_rows": 0,
                "missing_bars": 0,
            },
        }
        payload.update(overrides)
        return DataManifest(**payload)

    def test_valid_manifest_passes(self) -> None:
        result = validate_manifest_for_promotion(
            self._valid_manifest(),
            now=datetime(2026, 5, 9, tzinfo=timezone.utc),
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.reasons, [])
        self.assertEqual(result.metrics["source"], "yfinance")
        self.assertIn("universe_id_missing", result.warnings)
        self.assertIn("universe_source_missing", result.warnings)
        self.assertIn("survivorship_bias_risk_unmarked", result.warnings)

    def test_explicit_clean_universe_passes_without_metadata_warnings(self) -> None:
        result = validate_manifest_for_promotion(
            self._valid_manifest(
                universe_id="us-core-v2",
                universe_source="universe_builder:v2",
                survivorship_bias_risk="clean",
                adjustment_policy="split_adjusted",
            ),
            now=datetime(2026, 5, 9, tzinfo=timezone.utc),
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.reasons, [])
        self.assertNotIn("universe_id_missing", result.warnings)
        self.assertNotIn("universe_source_missing", result.warnings)
        self.assertNotIn("survivorship_bias_risk_unmarked", result.warnings)
        self.assertNotIn("adjustment_policy:unknown", result.warnings)

    def test_survivorship_bias_risk_prone_is_warning(self) -> None:
        result = validate_manifest_for_promotion(
            self._valid_manifest(
                universe_id="sp500-current-members",
                universe_source="manual_snapshot",
                survivorship_bias_risk="prone",
            )
        )
        self.assertTrue(result.ok)
        self.assertIn("survivorship_bias_risk:prone", result.warnings)

    def test_unknown_adjustment_policy_is_warning(self) -> None:
        result = validate_manifest_for_promotion(
            self._valid_manifest(
                universe_id="us-core-v2",
                universe_source="universe_builder:v2",
                survivorship_bias_risk="clean",
                adjustment="mystery_adjustment",
                adjustment_policy="mystery_adjustment",
            )
        )
        self.assertTrue(result.ok)
        self.assertIn("adjustment_policy:unknown", result.warnings)

    def test_fixture_manifest_is_blocked(self) -> None:
        result = validate_manifest_for_promotion(self._valid_manifest(source="fixture"))
        self.assertFalse(result.ok)
        self.assertIn("fixture_data_not_allowed", result.reasons)

    def test_crypto_asset_is_blocked(self) -> None:
        result = validate_manifest_for_promotion(self._valid_manifest(asset_class="crypto"))
        self.assertFalse(result.ok)
        self.assertIn("asset_class_not_allowed:crypto", result.reasons)

    def test_missing_checksum_is_blocked(self) -> None:
        result = validate_manifest_for_promotion(
            self._valid_manifest(fingerprint="", checksum="")
        )
        self.assertFalse(result.ok)
        self.assertIn("missing_checksum", result.reasons)

    def test_future_timestamp_is_blocked(self) -> None:
        result = validate_manifest_for_promotion(
            self._valid_manifest(end="2027-01-01T00:00:00+00:00"),
            now=datetime(2026, 5, 9, tzinfo=timezone.utc),
        )
        self.assertFalse(result.ok)
        self.assertTrue(any(reason.startswith("future_timestamp") for reason in result.reasons))

    def test_bad_bar_cleaning_counts_are_blocked(self) -> None:
        result = validate_manifest_for_promotion(
            self._valid_manifest(
                cleaning={
                    "duplicate_timestamps_removed": 1,
                    "invalid_ohlc_removed": 2,
                    "non_positive_prices_removed": 3,
                    "cleaning_loss_rows": 6,
                    "missing_bars": 4,
                }
            )
        )
        self.assertFalse(result.ok)
        self.assertIn("duplicate_timestamps:1", result.reasons)
        self.assertIn("invalid_ohlc:2", result.reasons)
        self.assertIn("non_positive_prices:3", result.reasons)
        self.assertIn("missing_bars:4", result.warnings)


if __name__ == "__main__":
    unittest.main()
