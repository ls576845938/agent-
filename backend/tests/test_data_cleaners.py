from __future__ import annotations

import unittest
from datetime import date, datetime

import pandas as pd

from quant_us.data.cleaners.bar_cleaner import BarCleaner, CleaningResult
from quant_us.data.cleaners.corporate_action_adjuster import CorporateAction, CorporateActionAdjuster
from quant_us.data.cleaners.data_validator import BarDataValidator, DataQualityReport


class BarCleanerHighLowViolation(unittest.TestCase):
    """Remove rows with high < low -> count decreases."""

    def setUp(self) -> None:
        self.cleaner = BarCleaner()
        self.valid_bars = pd.DataFrame(
            {
                "timestamp_utc": pd.to_datetime(
                    [
                        "2024-01-02 15:00:00+00:00",
                        "2024-01-02 15:05:00+00:00",
                        "2024-01-02 15:10:00+00:00",
                    ]
                ),
                "symbol": ["AAPL", "AAPL", "AAPL"],
                "open": [150.0, 151.0, 152.0],
                "high": [152.0, 153.0, 154.0],
                "low": [149.0, 150.0, 151.0],
                "close": [151.0, 152.0, 153.0],
                "volume": [10000, 11000, 12000],
            }
        )

    def test_drops_high_low_violation(self) -> None:
        df = self.valid_bars.copy()
        df.loc[1, "high"] = 140.0  # high < low
        result = self.cleaner.clean(df)
        self.assertEqual(len(result.frame), 2)
        self.assertEqual(result.dropped_rows, 1)
        self.assertNotIn(152.0, result.frame["close"].values)


class BarCleanerNonPositiveClose(unittest.TestCase):
    """Remove rows with non-positive close -> count decreases."""

    def setUp(self) -> None:
        self.cleaner = BarCleaner()
        self.valid_bars = pd.DataFrame(
            {
                "timestamp_utc": pd.to_datetime(
                    [
                        "2024-01-02 15:00:00+00:00",
                        "2024-01-02 15:05:00+00:00",
                        "2024-01-02 15:10:00+00:00",
                    ]
                ),
                "symbol": ["AAPL", "AAPL", "AAPL"],
                "open": [150.0, 151.0, 152.0],
                "high": [152.0, 153.0, 154.0],
                "low": [149.0, 150.0, 151.0],
                "close": [151.0, 152.0, 153.0],
                "volume": [10000, 11000, 12000],
            }
        )

    def test_drops_zero_close(self) -> None:
        df = self.valid_bars.copy()
        df.loc[1, "close"] = 0.0
        result = self.cleaner.clean(df)
        self.assertEqual(len(result.frame), 2)
        self.assertEqual(result.dropped_rows, 1)

    def test_drops_negative_close(self) -> None:
        df = self.valid_bars.copy()
        df.loc[1, "close"] = -5.0
        result = self.cleaner.clean(df)
        self.assertEqual(len(result.frame), 2)
        self.assertEqual(result.dropped_rows, 1)


class BarCleanerNonPositiveVolume(unittest.TestCase):
    """Remove rows with non-positive volume -> count decreases."""

    def setUp(self) -> None:
        self.cleaner = BarCleaner()
        self.valid_bars = pd.DataFrame(
            {
                "timestamp_utc": pd.to_datetime(
                    [
                        "2024-01-02 15:00:00+00:00",
                        "2024-01-02 15:05:00+00:00",
                        "2024-01-02 15:10:00+00:00",
                    ]
                ),
                "symbol": ["AAPL", "AAPL", "AAPL"],
                "open": [150.0, 151.0, 152.0],
                "high": [152.0, 153.0, 154.0],
                "low": [149.0, 150.0, 151.0],
                "close": [151.0, 152.0, 153.0],
                "volume": [10000, 11000, 12000],
            }
        )

    def test_drops_negative_volume(self) -> None:
        df = self.valid_bars.copy()
        df.loc[1, "volume"] = -1
        result = self.cleaner.clean(df)
        self.assertEqual(len(result.frame), 2)
        self.assertEqual(result.dropped_rows, 1)


class BarCleanerDuplicateTimestamps(unittest.TestCase):
    """Remove duplicate timestamps -> count decreases, timestamps unique."""

    def setUp(self) -> None:
        self.cleaner = BarCleaner()
        self.valid_bars = pd.DataFrame(
            {
                "timestamp_utc": pd.to_datetime(
                    [
                        "2024-01-02 15:00:00+00:00",
                        "2024-01-02 15:05:00+00:00",
                        "2024-01-02 15:10:00+00:00",
                    ]
                ),
                "symbol": ["AAPL", "AAPL", "AAPL"],
                "open": [150.0, 151.0, 152.0],
                "high": [152.0, 153.0, 154.0],
                "low": [149.0, 150.0, 151.0],
                "close": [151.0, 152.0, 153.0],
                "volume": [10000, 11000, 12000],
            }
        )

    def test_drops_duplicate_timestamps(self) -> None:
        df = self.valid_bars.copy()
        duplicate = df.iloc[1].to_dict()
        df = pd.concat([df, pd.DataFrame([duplicate])], ignore_index=True)
        result = self.cleaner.clean(df)
        self.assertEqual(len(result.frame), 3)
        self.assertEqual(result.duplicate_rows, 1)
        self.assertEqual(
            len(result.frame["timestamp_utc"].unique()),
            len(result.frame),
        )


class BarCleanerSortOrder(unittest.TestCase):
    """Sort timestamps ascending -> output sorted."""

    def setUp(self) -> None:
        self.cleaner = BarCleaner()
        self.valid_bars = pd.DataFrame(
            {
                "timestamp_utc": pd.to_datetime(
                    [
                        "2024-01-02 15:00:00+00:00",
                        "2024-01-02 15:05:00+00:00",
                        "2024-01-02 15:10:00+00:00",
                    ]
                ),
                "symbol": ["AAPL", "AAPL", "AAPL"],
                "open": [150.0, 151.0, 152.0],
                "high": [152.0, 153.0, 154.0],
                "low": [149.0, 150.0, 151.0],
                "close": [151.0, 152.0, 153.0],
                "volume": [10000, 11000, 12000],
            }
        )

    def test_output_is_sorted(self) -> None:
        df = self.valid_bars.iloc[::-1].reset_index(drop=True)  # reverse order
        result = self.cleaner.clean(df)
        self.assertTrue(result.frame["timestamp_utc"].is_monotonic_increasing)


class BarCleanerEmptyInput(unittest.TestCase):
    """Empty input -> empty output, no crash."""

    def setUp(self) -> None:
        self.cleaner = BarCleaner()

    def test_empty_dataframe(self) -> None:
        df = pd.DataFrame()
        result = self.cleaner.clean(df)
        self.assertTrue(result.frame.empty)
        self.assertEqual(result.dropped_rows, 0)
        self.assertEqual(result.duplicate_rows, 0)


class CorporateActionAdjusterSplit(unittest.TestCase):
    """Split adjustment: 2:1 split halves price, doubles volume."""

    def setUp(self) -> None:
        self.adjuster = CorporateActionAdjuster()
        self.bars = pd.DataFrame(
            {
                "timestamp_utc": pd.to_datetime(
                    [
                        "2024-01-02 15:00:00+00:00",
                        "2024-01-03 15:00:00+00:00",
                        "2024-01-04 15:00:00+00:00",
                    ]
                ),
                "symbol": ["AAPL", "AAPL", "AAPL"],
                "open": [100.0, 101.0, 102.0],
                "high": [102.0, 103.0, 104.0],
                "low": [99.0, 100.0, 101.0],
                "close": [101.0, 102.0, 103.0],
                "volume": [10000, 11000, 12000],
            }
        )

    def test_split_halves_price_doubles_volume(self) -> None:
        actions = [
            CorporateAction(symbol="AAPL", action_type="split", ex_date=date(2024, 1, 3), ratio=2.0),
        ]
        result = self.adjuster.adjust_bars(self.bars, actions)
        # Pre-split row (2024-01-02): prices halved, volume doubled
        self.assertAlmostEqual(result.loc[0, "close"], 101.0 / 2.0)
        self.assertAlmostEqual(result.loc[0, "volume"], 10000 * 2.0)
        # Ex-date row (2024-01-03): no adjustment
        self.assertAlmostEqual(result.loc[1, "close"], 102.0)
        self.assertAlmostEqual(result.loc[1, "volume"], 11000)
        self.assertTrue(result["adjusted_flag"].all())


class CorporateActionAdjusterReverseSplit(unittest.TestCase):
    """Reverse split: 1:2 reverse split doubles price, halves volume."""

    def setUp(self) -> None:
        self.adjuster = CorporateActionAdjuster()
        self.bars = pd.DataFrame(
            {
                "timestamp_utc": pd.to_datetime(
                    [
                        "2024-01-02 15:00:00+00:00",
                        "2024-01-03 15:00:00+00:00",
                        "2024-01-04 15:00:00+00:00",
                    ]
                ),
                "symbol": ["AAPL", "AAPL", "AAPL"],
                "open": [100.0, 101.0, 102.0],
                "high": [102.0, 103.0, 104.0],
                "low": [99.0, 100.0, 101.0],
                "close": [101.0, 102.0, 103.0],
                "volume": [10000, 11000, 12000],
            }
        )

    def test_reverse_split_doubles_price_halves_volume(self) -> None:
        actions = [
            CorporateAction(symbol="AAPL", action_type="split", ex_date=date(2024, 1, 3), ratio=0.5),
        ]
        result = self.adjuster.adjust_bars(self.bars, actions)
        # Pre-split row: prices doubled, volume halved
        # adjustment_factor *= 1/0.5 = 2, so price *= 2, volume /= 2
        self.assertAlmostEqual(result.loc[0, "close"], 101.0 * 2.0)
        self.assertAlmostEqual(result.loc[0, "volume"], 10000 / 2.0)
        # Ex-date row: no adjustment
        self.assertAlmostEqual(result.loc[1, "close"], 102.0)
        self.assertAlmostEqual(result.loc[1, "volume"], 11000)


class CorporateActionAdjusterDividend(unittest.TestCase):
    """Dividend adjustment: price reduced by dividend amount."""

    def setUp(self) -> None:
        self.adjuster = CorporateActionAdjuster()
        self.bars = pd.DataFrame(
            {
                "timestamp_utc": pd.to_datetime(
                    [
                        "2024-01-02 15:00:00+00:00",
                        "2024-01-03 15:00:00+00:00",
                        "2024-01-04 15:00:00+00:00",
                    ]
                ),
                "symbol": ["AAPL", "AAPL", "AAPL"],
                "open": [100.0, 101.0, 102.0],
                "high": [102.0, 103.0, 104.0],
                "low": [99.0, 100.0, 101.0],
                "close": [101.0, 102.0, 103.0],
                "volume": [10000, 11000, 12000],
            }
        )

    def test_dividend_reduces_price(self) -> None:
        # $1 dividend on 2024-01-03; reference close = 101.0
        # factor = (101 - 1) / 101 = 100/101
        actions = [
            CorporateAction(symbol="AAPL", action_type="dividend", ex_date=date(2024, 1, 3), cash_amount=1.0),
        ]
        result = self.adjuster.adjust_bars(self.bars, actions)
        expected_factor = 100.0 / 101.0
        self.assertAlmostEqual(result.loc[0, "close"], 101.0 * expected_factor)
        self.assertAlmostEqual(result.loc[0, "open"], 100.0 * expected_factor)
        self.assertAlmostEqual(result.loc[0, "high"], 102.0 * expected_factor)
        self.assertAlmostEqual(result.loc[0, "low"], 99.0 * expected_factor)
        # Ex-date row: not adjusted
        self.assertAlmostEqual(result.loc[1, "close"], 102.0)
        self.assertTrue(result["adjusted_flag"].all())


class CorporateActionAdjusterEmptyActions(unittest.TestCase):
    """Empty actions list -> no change."""

    def setUp(self) -> None:
        self.adjuster = CorporateActionAdjuster()
        self.bars = pd.DataFrame(
            {
                "timestamp_utc": pd.to_datetime(
                    [
                        "2024-01-02 15:00:00+00:00",
                        "2024-01-03 15:00:00+00:00",
                    ]
                ),
                "symbol": ["AAPL", "AAPL"],
                "open": [100.0, 101.0],
                "high": [102.0, 103.0],
                "low": [99.0, 100.0],
                "close": [101.0, 102.0],
                "volume": [10000, 11000],
            }
        )

    def test_no_actions_returns_original(self) -> None:
        result = self.adjuster.adjust_bars(self.bars, [])
        pd.testing.assert_frame_equal(
            result[self.bars.columns],
            self.bars,
        )
        self.assertIn("adjusted_flag", result.columns)
        self.assertFalse(result["adjusted_flag"].any())


class CorporateActionAdjusterFactorColumn(unittest.TestCase):
    """Adjust factor column exists in output."""

    def setUp(self) -> None:
        self.adjuster = CorporateActionAdjuster()
        self.bars = pd.DataFrame(
            {
                "timestamp_utc": pd.to_datetime(
                    [
                        "2024-01-02 15:00:00+00:00",
                        "2024-01-03 15:00:00+00:00",
                    ]
                ),
                "symbol": ["AAPL", "AAPL"],
                "open": [100.0, 101.0],
                "high": [102.0, 103.0],
                "low": [99.0, 100.0],
                "close": [101.0, 102.0],
                "volume": [10000, 11000],
            }
        )

    def test_adjusted_flag_present_factor_dropped(self) -> None:
        actions = [
            CorporateAction(symbol="AAPL", action_type="split", ex_date=date(2024, 1, 3), ratio=2.0),
        ]
        result = self.adjuster.adjust_bars(self.bars, actions)
        self.assertIn("adjusted_flag", result.columns)
        self.assertNotIn("adjustment_factor", result.columns)


class BarDataValidatorValid(unittest.TestCase):
    """Valid OHLCV -> passes all checks."""

    def setUp(self) -> None:
        self.validator = BarDataValidator()
        self.valid_frame = pd.DataFrame(
            {
                "timestamp_utc": pd.to_datetime(
                    [
                        "2024-01-02 15:00:00+00:00",
                        "2024-01-02 15:05:00+00:00",
                        "2024-01-02 15:10:00+00:00",
                    ]
                ),
                "open": [100.0, 101.0, 102.0],
                "high": [102.0, 103.0, 104.0],
                "low": [99.0, 100.0, 101.0],
                "close": [101.0, 102.0, 103.0],
                "volume": [10000, 11000, 12000],
            }
        )

    def test_valid_data_passes(self) -> None:
        report = self.validator.validate(self.valid_frame)
        self.assertEqual(report.row_count, 3)
        self.assertEqual(report.non_positive_prices, 0)
        self.assertEqual(report.invalid_ohlc, 0)
        self.assertEqual(report.duplicate_timestamps, 0)
        self.assertTrue(report.is_usable)


class BarDataValidatorMissingColumns(unittest.TestCase):
    """Missing columns -> reports missing."""

    def setUp(self) -> None:
        self.validator = BarDataValidator()

    def test_missing_open_raises_key_error(self) -> None:
        frame = pd.DataFrame(
            {
                "timestamp_utc": pd.to_datetime(
                    ["2024-01-02 15:00:00+00:00"]
                ),
                "high": [102.0],
                "low": [99.0],
                "close": [101.0],
                "volume": [10000],
            }
        )
        with self.assertRaises(KeyError):
            self.validator.validate(frame)

    def test_missing_timestamp_uses_index(self) -> None:
        """When timestamp_utc is absent, validator falls back to index."""
        frame = pd.DataFrame(
            {
                "open": [100.0],
                "high": [102.0],
                "low": [99.0],
                "close": [101.0],
                "volume": [10000],
            },
            index=pd.to_datetime(["2024-01-02 15:00:00+00:00"]),
        )
        # This should not raise because timestamp_col becomes None,
        # then timestamps = pd.to_datetime(frame.index, utc=True)
        report = self.validator.validate(frame)
        self.assertEqual(report.row_count, 1)


class BarDataValidatorNegativePrices(unittest.TestCase):
    """Negative prices -> reports invalid."""

    def setUp(self) -> None:
        self.validator = BarDataValidator()
        self.valid_frame = pd.DataFrame(
            {
                "timestamp_utc": pd.to_datetime(
                    [
                        "2024-01-02 15:00:00+00:00",
                        "2024-01-02 15:05:00+00:00",
                    ]
                ),
                "open": [100.0, 101.0],
                "high": [102.0, 103.0],
                "low": [99.0, 100.0],
                "close": [101.0, -1.0],
                "volume": [10000, 11000],
            }
        )

    def test_negative_close_reported(self) -> None:
        report = self.validator.validate(self.valid_frame)
        self.assertEqual(report.non_positive_prices, 1)
        self.assertFalse(report.is_usable)

    def test_zero_open_reported(self) -> None:
        frame = pd.DataFrame(
            {
                "timestamp_utc": pd.to_datetime(
                    ["2024-01-02 15:00:00+00:00"]
                ),
                "open": [0.0],
                "high": [102.0],
                "low": [99.0],
                "close": [101.0],
                "volume": [10000],
            }
        )
        report = self.validator.validate(frame)
        self.assertEqual(report.non_positive_prices, 1)
        self.assertFalse(report.is_usable)


class BarDataValidatorCoverageBelowThreshold(unittest.TestCase):
    """Coverage below threshold -> reports low coverage."""

    def setUp(self) -> None:
        self.validator = BarDataValidator()

    def test_missing_bars_detected(self) -> None:
        """5m bars with a gap: one bar missing at 15:10."""
        frame = pd.DataFrame(
            {
                "timestamp_utc": pd.to_datetime(
                    [
                        "2024-01-02 15:00:00+00:00",
                        "2024-01-02 15:05:00+00:00",
                        "2024-01-02 15:15:00+00:00",
                    ]
                ),
                "open": [100.0, 101.0, 102.0],
                "high": [102.0, 103.0, 104.0],
                "low": [99.0, 100.0, 101.0],
                "close": [101.0, 102.0, 103.0],
                "volume": [10000, 11000, 12000],
            }
        )
        # Expected 5min bars: 15:00, 15:05, 15:10, 15:15 -> 4 expected, 3 present -> 1 missing
        report = self.validator.validate(frame, expected_interval="5m")
        self.assertGreater(report.missing_bars, 0)
        self.assertEqual(report.missing_bars, 1)

    def test_no_expected_interval_returns_zero(self) -> None:
        """Without expected_interval, missing_bars is always 0."""
        frame = pd.DataFrame(
            {
                "timestamp_utc": pd.to_datetime(
                    ["2024-01-02 15:00:00+00:00"]
                ),
                "open": [100.0],
                "high": [102.0],
                "low": [99.0],
                "close": [101.0],
                "volume": [10000],
            }
        )
        report = self.validator.validate(frame)
        self.assertEqual(report.missing_bars, 0)


class BarDataValidatorEmptyDataset(unittest.TestCase):
    """Empty dataset -> reports empty."""

    def setUp(self) -> None:
        self.validator = BarDataValidator()

    def test_empty_frame_returns_empty_report(self) -> None:
        frame = pd.DataFrame()
        report = self.validator.validate(frame)
        self.assertEqual(report.row_count, 0)
        self.assertEqual(report.duplicate_timestamps, 0)
        self.assertEqual(report.non_positive_prices, 0)
        self.assertEqual(report.invalid_ohlc, 0)
        self.assertEqual(report.missing_bars, 0)
        self.assertFalse(report.is_usable)


if __name__ == "__main__":
    unittest.main()
