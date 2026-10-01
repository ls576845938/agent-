"""
Tests for scripts/generate_data_manifest.py CLI entrypoint.

Covers argparse flags, main() flow, error handling, symbol uppercasing.
Uses unittest.mock.patch to isolate from network / database dependencies.
"""

from __future__ import annotations

import sys
import unittest
from io import StringIO
from unittest.mock import MagicMock, patch

from quant_us.data.storage.data_manifest import DataManifest, DataManifestValidation


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _import_main():
    """Import and return ``main`` from the CLI script once."""
    from scripts.generate_data_manifest import main  # noqa: F401
    from scripts.generate_data_manifest import main
    return main


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------

class TestGenerateDataManifestCLI(unittest.TestCase):
    """CLI entrypoint tests for scripts/generate_data_manifest.py."""

    maxDiff = None

    # ---- helpers ----

    def _run_main(self, args: list[str]) -> tuple[str, str, Exception | None]:
        """Run ``main()`` with *args* appended to sys.argv.

        Returns (stdout, stderr, exception).
        ``exception`` is *None* when the function returned normally.
        """
        main = _import_main()
        with patch.object(sys, "argv", ["generate_data_manifest", *args]):
            out = StringIO()
            err = StringIO()
            exc = None
            with patch("sys.stdout", out), patch("sys.stderr", err):
                try:
                    main()
                except BaseException as e:
                    exc = e
            return out.getvalue(), err.getvalue(), exc

    # ---- --list (empty store) ----

    @patch("scripts.generate_data_manifest.DataManifestStore")
    def test_list_empty_store(self, mock_store_cls: MagicMock) -> None:
        """--list on an empty store prints 'No manifests found.'."""
        mock_store = MagicMock()
        mock_store.list_manifests.return_value = []
        mock_store_cls.return_value = mock_store

        out, err, exc = self._run_main(["--list"])

        self.assertIn("No manifests found.", out)
        self.assertIsNone(exc)

    # ---- --list (with manifests) ----

    @patch("scripts.generate_data_manifest.DataManifestStore")
    def test_list_with_manifests(self, mock_store_cls: MagicMock) -> None:
        """--list with pre-existing manifests prints a formatted table."""
        manifests = [
            DataManifest(
                data_version="qs-sqlite-AAPL-1d-v1",
                source="sqlite",
                symbol="AAPL",
                interval="1d",
                coverage_pct=95.0,
                quality_score=90.0,
                row_count=252,
            ),
            DataManifest(
                data_version="qs-sqlite-SPY-1h-v1",
                source="sqlite",
                symbol="SPY",
                interval="1h",
                coverage_pct=98.5,
                quality_score=92.0,
                row_count=500,
            ),
        ]
        mock_store = MagicMock()
        mock_store.list_manifests.return_value = manifests
        mock_store_cls.return_value = mock_store

        out, err, exc = self._run_main(["--list"])

        self.assertIn("AAPL", out)
        self.assertIn("SPY", out)
        self.assertIn("qs-sqlite-AAPL-1d-v1", out)
        self.assertIn("data_version", out)  # header row present
        self.assertIsNone(exc)

    # ---- single generation ----

    @patch("scripts.generate_data_manifest.get_git_commit", return_value="abc123")
    @patch("scripts.generate_data_manifest.build_manifest_from_quality")
    @patch("scripts.generate_data_manifest.inspect_market_data_quality")
    @patch("scripts.generate_data_manifest.DataManifestStore")
    def test_single_generation_writes_manifest(
        self,
        mock_store_cls: MagicMock,
        mock_inspect: MagicMock,
        mock_build: MagicMock,
        mock_git: MagicMock,
    ) -> None:
        """Single manifest generation calls build_manifest_from_quality and writes."""
        mock_inspect.return_value = {
            "data_version": "qs-sqlite-AAPL-1d-abc123",
            "first_timestamp": "2024-01-01T00:00:00+00:00",
            "last_timestamp": "2024-12-31T23:59:59+00:00",
            "row_count": 252,
            "expected_rows": 252,
            "coverage_pct": 100.0,
            "fingerprint": "a" * 64,
            "quality_score": 95.0,
            "issues": [],
            "duplicate_timestamps": 0,
            "invalid_ohlc": 0,
            "non_positive_prices": 0,
            "cleaning_loss_rows": 0,
            "missing_bars": 0,
        }

        mock_manifest = DataManifest(
            data_version="qs-sqlite-AAPL-1d-abc123",
            source="sqlite",
            symbol="AAPL",
            interval="1d",
            coverage_pct=100.0,
            quality_score=95.0,
            row_count=252,
        )
        mock_build.return_value = mock_manifest

        mock_store = MagicMock()
        mock_store.list_manifests.return_value = []
        mock_store_cls.return_value = mock_store

        out, err, exc = self._run_main(
            [
                "--source", "sqlite",
                "--symbol", "AAPL",
                "--interval", "1d",
                "--start", "2024-01-01",
                "--end", "2024-12-31",
            ]
        )

        self.assertIsNone(exc)
        mock_inspect.assert_called_once_with(
            source="sqlite", symbol="AAPL", interval="1d",
            start="2024-01-01", end="2024-12-31", db_path="",
        )
        mock_build.assert_called_once()
        mock_store.write.assert_called_once_with(mock_manifest)
        self.assertIn(mock_manifest.data_version, out)

    # ---- --all iterates over all combos ----

    @patch("scripts.generate_data_manifest.get_git_commit", return_value="abc123")
    @patch("scripts.generate_data_manifest.build_manifest_from_quality")
    @patch("scripts.generate_data_manifest.inspect_market_data_quality")
    @patch("scripts.generate_data_manifest.DataManifestStore")
    def test_all_flag_iterates_all_combinations(
        self,
        mock_store_cls: MagicMock,
        mock_inspect: MagicMock,
        mock_build: MagicMock,
        mock_git: MagicMock,
    ) -> None:
        """--all generates manifests for every (symbol, interval) pair (9x3=27)."""
        mock_inspect.return_value = {
            "data_version": "qs-sqlite-XXX-1d-abc",
            "row_count": 100,
            "expected_rows": 100,
            "coverage_pct": 100.0,
            "quality_score": 95.0,
            "issues": [],
            "duplicate_timestamps": 0,
            "invalid_ohlc": 0,
            "non_positive_prices": 0,
            "cleaning_loss_rows": 0,
            "missing_bars": 0,
        }
        mock_manifest = DataManifest(
            data_version="test-version",
            source="sqlite",
            symbol="AAPL",
            interval="1d",
            coverage_pct=100.0,
            quality_score=95.0,
            row_count=100,
        )
        mock_build.return_value = mock_manifest

        mock_store = MagicMock()
        mock_store.list_manifests.return_value = []
        mock_store_cls.return_value = mock_store

        out, err, exc = self._run_main(["--all", "--source", "sqlite"])

        self.assertIsNone(exc)
        # 9 symbols x 3 intervals = 27 calls
        self.assertEqual(mock_inspect.call_count, 27)
        self.assertEqual(mock_build.call_count, 27)
        self.assertEqual(mock_store.write.call_count, 27)

    # ---- --all skips gracefully on error ----

    @patch("scripts.generate_data_manifest.get_git_commit", return_value="abc123")
    @patch("scripts.generate_data_manifest.build_manifest_from_quality")
    @patch("scripts.generate_data_manifest.DataManifestStore")
    def test_all_skips_on_inspect_failure(
        self,
        mock_store_cls: MagicMock,
        mock_build: MagicMock,
        mock_git: MagicMock,
    ) -> None:
        """When inspect raises in --all mode, main() prints SKIP and continues."""
        quality_ok = {
            "data_version": "v1",
            "row_count": 100,
            "expected_rows": 100,
            "coverage_pct": 100.0,
            "quality_score": 95.0,
            "issues": [],
            "duplicate_timestamps": 0,
            "invalid_ohlc": 0,
            "non_positive_prices": 0,
            "cleaning_loss_rows": 0,
            "missing_bars": 0,
        }
        # First call raises ValueError, remaining 26 succeed
        inspect_side_effects = [ValueError("no data")] + [quality_ok] * 26

        with patch(
            "scripts.generate_data_manifest.inspect_market_data_quality",
            side_effect=inspect_side_effects,
        ):
            mock_manifest = DataManifest(
                data_version="v1",
                source="sqlite",
                symbol="AAPL",
                interval="1d",
                coverage_pct=100.0,
                quality_score=95.0,
                row_count=100,
            )
            mock_build.return_value = mock_manifest

            mock_store = MagicMock()
            mock_store.list_manifests.return_value = []
            mock_store_cls.return_value = mock_store

            out, err, exc = self._run_main(["--all", "--source", "sqlite"])

        self.assertIsNone(exc)
        self.assertIn("SKIP", out)
        # 27 total calls attempted; 1 failed -> 26 succeeded
        self.assertEqual(mock_build.call_count, 26)

    # ---- single generation error propagates ----

    @patch("scripts.generate_data_manifest.DataManifestStore")
    def test_single_generate_raises_when_inspect_fails(
        self, mock_store_cls: MagicMock
    ) -> None:
        """When inspect raises (non --all), main() propagates the exception."""
        mock_store = MagicMock()
        mock_store_cls.return_value = mock_store

        with patch(
            "scripts.generate_data_manifest.inspect_market_data_quality",
            side_effect=ValueError("DB not found"),
        ):
            out, err, exc = self._run_main(
                [
                    "--source", "sqlite",
                    "--symbol", "AAPL",
                    "--interval", "1d",
                ]
            )

        self.assertIsNotNone(exc)
        self.assertIsInstance(exc, ValueError)
        self.assertIn("DB not found", str(exc))

    # ---- symbol uppercasing ----

    @patch("scripts.generate_data_manifest.get_git_commit", return_value="abc123")
    @patch("scripts.generate_data_manifest.build_manifest_from_quality")
    @patch("scripts.generate_data_manifest.inspect_market_data_quality")
    @patch("scripts.generate_data_manifest.DataManifestStore")
    def test_symbol_passed_lowercase_to_build(
        self,
        mock_store_cls: MagicMock,
        mock_inspect: MagicMock,
        mock_build: MagicMock,
        mock_git: MagicMock,
    ) -> None:
        """--symbol aapl is passed as-is to build_manifest_from_quality which uppercases."""
        mock_inspect.return_value = {
            "data_version": "v1",
            "row_count": 10,
            "expected_rows": 10,
            "coverage_pct": 100.0,
            "quality_score": 100.0,
            "issues": [],
            "duplicate_timestamps": 0,
            "invalid_ohlc": 0,
            "non_positive_prices": 0,
            "cleaning_loss_rows": 0,
            "missing_bars": 0,
        }
        mock_manifest = DataManifest(
            data_version="v1",
            source="sqlite",
            symbol="AAPL",
            interval="1d",
            coverage_pct=100.0,
            quality_score=100.0,
            row_count=10,
        )
        mock_build.return_value = mock_manifest

        mock_store = MagicMock()
        mock_store.list_manifests.return_value = []
        mock_store_cls.return_value = mock_store

        out, err, exc = self._run_main(
            [
                "--source", "sqlite",
                "--symbol", "aapl",  # deliberately lowercase
                "--interval", "1d",
            ]
        )

        self.assertIsNone(exc)

        # verify the symbol was passed as lowercase to build_manifest_from_quality
        # (build_manifest_from_quality internally calls symbol.upper())
        _, call_kwargs = mock_build.call_args
        self.assertEqual(call_kwargs["symbol"], "aapl")

        # Also verify inspect_market_data_quality got the lowercase symbol too
        mock_inspect.assert_called_once()
        _, inspect_kwargs = mock_inspect.call_args
        self.assertEqual(inspect_kwargs["symbol"], "aapl")

    @patch("scripts.generate_data_manifest.get_git_commit", return_value="abc123")
    @patch("scripts.generate_data_manifest.build_manifest_from_quality")
    @patch("scripts.generate_data_manifest.inspect_market_data_quality")
    @patch("scripts.generate_data_manifest.DataManifestStore")
    def test_universe_and_adjustment_args_are_forwarded(
        self,
        mock_store_cls: MagicMock,
        mock_inspect: MagicMock,
        mock_build: MagicMock,
        mock_git: MagicMock,
    ) -> None:
        mock_inspect.return_value = {
            "data_version": "v2",
            "row_count": 10,
            "expected_rows": 10,
            "coverage_pct": 100.0,
            "quality_score": 100.0,
            "issues": [],
            "duplicate_timestamps": 0,
            "invalid_ohlc": 0,
            "non_positive_prices": 0,
            "cleaning_loss_rows": 0,
            "missing_bars": 0,
        }
        mock_manifest = DataManifest(
            data_version="v2",
            source="sqlite",
            symbol="AAPL",
            interval="1d",
            coverage_pct=100.0,
            quality_score=100.0,
            row_count=10,
            universe_id="us-core-v2",
            universe_source="universe_builder:v2",
            survivorship_bias_risk="clean",
            adjustment_policy="split_adjusted",
            corporate_action_adjustment="split_adjusted",
        )
        mock_build.return_value = mock_manifest

        mock_store = MagicMock()
        mock_store.list_manifests.return_value = []
        mock_store_cls.return_value = mock_store

        out, err, exc = self._run_main(
            [
                "--source", "sqlite",
                "--symbol", "AAPL",
                "--interval", "1d",
                "--universe-id", "us-core-v2",
                "--universe-source", "universe_builder:v2",
                "--survivorship-bias-risk", "clean",
                "--adjustment-policy", "split_adjusted",
            ]
        )

        self.assertIsNone(exc)
        _, build_kwargs = mock_build.call_args
        self.assertEqual(build_kwargs["universe_id"], "us-core-v2")
        self.assertEqual(build_kwargs["universe_source"], "universe_builder:v2")
        self.assertEqual(build_kwargs["survivorship_bias_risk"], "clean")
        self.assertEqual(build_kwargs["adjustment_policy"], "split_adjusted")
        self.assertIn("adjustment_policy: split_adjusted", out)

    @patch("scripts.generate_data_manifest.get_git_commit", return_value="abc123")
    @patch("scripts.generate_data_manifest.inspect_market_data_quality")
    @patch("scripts.generate_data_manifest.DataManifestStore")
    def test_validate_mode_passes_with_auto_inferred_lineage(
        self,
        mock_store_cls: MagicMock,
        mock_inspect: MagicMock,
        mock_git: MagicMock,
    ) -> None:
        mock_inspect.return_value = {
            "data_version": "qs-sqlite-AAPL-1d-auto",
            "actual_source": "sqlite",
            "first_timestamp": "2024-01-02T00:00:00+00:00",
            "last_timestamp": "2024-12-31T00:00:00+00:00",
            "row_count": 252,
            "expected_rows": 252,
            "coverage_pct": 100.0,
            "fingerprint": "a" * 64,
            "quality_score": 99.0,
            "issues": [],
            "duplicate_timestamps": 0,
            "invalid_ohlc": 0,
            "non_positive_prices": 0,
            "cleaning_loss_rows": 0,
            "missing_bars": 0,
        }
        mock_store = MagicMock()
        mock_store.list_manifests.return_value = []
        mock_store_cls.return_value = mock_store

        out, err, exc = self._run_main(
            [
                "--source", "sqlite",
                "--symbol", "AAPL",
                "--interval", "1d",
                "--start", "2024-01-02",
                "--end", "2024-12-31",
                "--validate",
            ]
        )

        self.assertIsNone(exc)
        mock_store.write.assert_called_once()
        written_manifest = mock_store.write.call_args.args[0]
        self.assertEqual(written_manifest.survivorship_bias_risk, "clean")
        self.assertTrue(written_manifest.universe_id.startswith("single-symbol-AAPL-1d-"))
        self.assertIn("promotion validation: PASS", out)

    @patch("scripts.generate_data_manifest.get_git_commit", return_value="abc123")
    @patch("scripts.generate_data_manifest.inspect_market_data_quality")
    @patch("scripts.generate_data_manifest.DataManifestStore")
    def test_validate_mode_blocks_when_auto_lineage_cannot_be_inferred(
        self,
        mock_store_cls: MagicMock,
        mock_inspect: MagicMock,
        mock_git: MagicMock,
    ) -> None:
        mock_inspect.return_value = {
            "data_version": "qs-sqlite-AAPL,MSFT-1d-multi-symbol",
            "actual_source": "sqlite",
            "first_timestamp": "2024-01-02T00:00:00+00:00",
            "last_timestamp": "2024-12-31T00:00:00+00:00",
            "row_count": 252,
            "expected_rows": 252,
            "coverage_pct": 100.0,
            "fingerprint": "b" * 64,
            "quality_score": 99.0,
            "issues": [],
            "duplicate_timestamps": 0,
            "invalid_ohlc": 0,
            "non_positive_prices": 0,
            "cleaning_loss_rows": 0,
            "missing_bars": 0,
        }
        mock_store = MagicMock()
        mock_store.list_manifests.return_value = []
        mock_store_cls.return_value = mock_store

        out, err, exc = self._run_main(
            [
                "--source", "sqlite",
                "--symbol", "AAPL,MSFT",
                "--interval", "1d",
                "--validate",
            ]
        )

        self.assertIsInstance(exc, ValueError)
        mock_store.write.assert_not_called()
        self.assertIn("promotion validation: BLOCK", out)
        self.assertIn("universe_id_missing", out)

    @patch("scripts.generate_data_manifest.get_git_commit", return_value="abc123")
    @patch(
        "scripts.generate_data_manifest.validate_manifest_for_promotion",
        return_value=DataManifestValidation(
            ok=False,
            reasons=["missing_bars:2", "zero_volume_bars:1"],
            warnings=[],
        ),
    )
    @patch("scripts.generate_data_manifest.build_manifest_from_quality")
    @patch("scripts.generate_data_manifest.inspect_market_data_quality")
    @patch("scripts.generate_data_manifest.DataManifestStore")
    def test_validate_mode_blocks_write_for_bad_manifest(
        self,
        mock_store_cls: MagicMock,
        mock_inspect: MagicMock,
        mock_build: MagicMock,
        mock_validate: MagicMock,
        mock_git: MagicMock,
    ) -> None:
        mock_inspect.return_value = {
            "data_version": "v3",
            "row_count": 10,
            "expected_rows": 12,
            "coverage_pct": 83.3,
            "quality_score": 81.0,
            "issues": [],
            "duplicate_timestamps": 0,
            "invalid_ohlc": 0,
            "non_positive_prices": 0,
            "cleaning_loss_rows": 0,
            "missing_bars": 2,
        }
        mock_manifest = DataManifest(
            data_version="v3",
            source="sqlite",
            symbol="AAPL",
            interval="1d",
            coverage_pct=83.3,
            quality_score=81.0,
            row_count=10,
            quality_summary={
                "missing_bars": 2,
                "duplicate_bars": 0,
                "price_jump_bars": 0,
                "zero_volume_bars": 1,
                "corporate_action_flags": 0,
                "invalid_ohlc_rows": 0,
                "non_positive_price_rows": 0,
                "duplicate_timestamps_removed": 0,
                "cleaning_loss_rows": 0,
                "total_issue_count": 3,
            },
        )
        mock_build.return_value = mock_manifest

        mock_store = MagicMock()
        mock_store.list_manifests.return_value = []
        mock_store_cls.return_value = mock_store

        out, err, exc = self._run_main(
            [
                "--source", "sqlite",
                "--symbol", "AAPL",
                "--interval", "1d",
                "--validate",
            ]
        )

        self.assertIsNotNone(exc)
        self.assertIsInstance(exc, ValueError)
        mock_validate.assert_called_once_with(mock_manifest, strict=True)
        mock_store.write.assert_not_called()
        self.assertIn("promotion validation: BLOCK", out)
        self.assertIn("quality_summary:", out)
        self.assertIn("missing_bars=2", out)

    @patch("scripts.generate_data_manifest.get_git_commit", return_value="abc123")
    @patch(
        "scripts.generate_data_manifest.validate_manifest_for_promotion",
        return_value=DataManifestValidation(ok=True, reasons=[], warnings=[]),
    )
    @patch("scripts.generate_data_manifest.build_manifest_from_quality")
    @patch("scripts.generate_data_manifest.inspect_market_data_quality")
    @patch("scripts.generate_data_manifest.DataManifestStore")
    def test_validate_mode_writes_good_manifest_and_prints_quality_summary(
        self,
        mock_store_cls: MagicMock,
        mock_inspect: MagicMock,
        mock_build: MagicMock,
        mock_validate: MagicMock,
        mock_git: MagicMock,
    ) -> None:
        mock_inspect.return_value = {
            "data_version": "v4",
            "row_count": 10,
            "expected_rows": 10,
            "coverage_pct": 100.0,
            "quality_score": 99.0,
            "issues": [],
            "duplicate_timestamps": 0,
            "invalid_ohlc": 0,
            "non_positive_prices": 0,
            "cleaning_loss_rows": 0,
            "missing_bars": 0,
        }
        mock_manifest = DataManifest(
            data_version="v4",
            source="sqlite",
            symbol="AAPL",
            interval="1d",
            coverage_pct=100.0,
            quality_score=99.0,
            row_count=10,
            quality_summary={
                "missing_bars": 0,
                "duplicate_bars": 0,
                "price_jump_bars": 0,
                "zero_volume_bars": 0,
                "corporate_action_flags": 0,
                "invalid_ohlc_rows": 0,
                "non_positive_price_rows": 0,
                "duplicate_timestamps_removed": 0,
                "cleaning_loss_rows": 0,
                "total_issue_count": 0,
            },
        )
        mock_build.return_value = mock_manifest

        mock_store = MagicMock()
        mock_store.list_manifests.return_value = []
        mock_store_cls.return_value = mock_store

        out, err, exc = self._run_main(
            [
                "--source", "sqlite",
                "--symbol", "AAPL",
                "--interval", "1d",
                "--validate",
            ]
        )

        self.assertIsNone(exc)
        mock_validate.assert_called_once_with(mock_manifest, strict=True)
        mock_store.write.assert_called_once_with(mock_manifest)
        self.assertIn("promotion validation: PASS", out)
        self.assertIn("quality_summary:", out)
        self.assertIn("total_issue_count=0", out)


if __name__ == "__main__":
    unittest.main()
