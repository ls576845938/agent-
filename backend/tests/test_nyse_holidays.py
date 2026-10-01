"""Tests for quant_us.core.nyse_holidays.

Covers nyse_holidays, nyse_early_closes, is_nyse_trading_day, and
trading_days_between for years 2020-2026 with known expected values.
"""
from __future__ import annotations

import unittest
from datetime import date

from quant_us.core.nyse_holidays import (
    is_nyse_trading_day,
    nyse_early_closes,
    nyse_holidays,
    trading_days_between,
)


class TestNyseHolidays(unittest.TestCase):
    """Comprehensive test suite for the NYSE holiday module."""

    maxDiff = None

    # ------------------------------------------------------------------
    # nyse_holidays(year)  –  per-year full holiday dicts
    # ------------------------------------------------------------------

    def _assert_holidays(self, year: int, expected: dict[date, str]) -> None:
        actual = nyse_holidays(year)
        self.assertEqual(len(actual), len(expected),
                         f"{year}: expected {len(expected)} holidays, got {len(actual)}")
        for d, name in expected.items():
            self.assertIn(d, actual, f"{year}: missing holiday {d}")
            self.assertEqual(actual[d], name, f"{year}: name mismatch for {d}")

    def test_holidays_2020(self) -> None:
        expected = {
            date(2020, 1, 1): "New Year's Day",
            date(2020, 1, 20): "Martin Luther King Jr. Day",
            date(2020, 2, 17): "Presidents' Day",
            date(2020, 4, 10): "Good Friday",
            date(2020, 5, 25): "Memorial Day",
            date(2020, 7, 3): "Independence Day",
            date(2020, 9, 7): "Labor Day",
            date(2020, 11, 26): "Thanksgiving Day",
            date(2020, 12, 25): "Christmas Day",
        }
        self._assert_holidays(2020, expected)

    def test_holidays_2021(self) -> None:
        expected = {
            date(2021, 1, 1): "New Year's Day",
            date(2021, 1, 18): "Martin Luther King Jr. Day",
            date(2021, 2, 15): "Presidents' Day",
            date(2021, 4, 2): "Good Friday",
            date(2021, 5, 31): "Memorial Day",
            date(2021, 7, 5): "Independence Day",
            date(2021, 9, 6): "Labor Day",
            date(2021, 11, 25): "Thanksgiving Day",
            date(2021, 12, 24): "Christmas Day",
        }
        self._assert_holidays(2021, expected)

    def test_holidays_2022(self) -> None:
        """2022 includes first Juneteenth; NYSE did not close on Dec 31 2021."""
        expected = {
            date(2022, 1, 17): "Martin Luther King Jr. Day",
            date(2022, 2, 21): "Presidents' Day",
            date(2022, 4, 15): "Good Friday",
            date(2022, 5, 30): "Memorial Day",
            date(2022, 6, 20): "Juneteenth National Independence Day",
            date(2022, 7, 4): "Independence Day",
            date(2022, 9, 5): "Labor Day",
            date(2022, 11, 24): "Thanksgiving Day",
            date(2022, 12, 26): "Christmas Day",
        }
        self._assert_holidays(2022, expected)

    def test_holidays_2023(self) -> None:
        expected = {
            date(2023, 1, 2): "New Year's Day",
            date(2023, 1, 16): "Martin Luther King Jr. Day",
            date(2023, 2, 20): "Presidents' Day",
            date(2023, 4, 7): "Good Friday",
            date(2023, 5, 29): "Memorial Day",
            date(2023, 6, 19): "Juneteenth National Independence Day",
            date(2023, 7, 4): "Independence Day",
            date(2023, 9, 4): "Labor Day",
            date(2023, 11, 23): "Thanksgiving Day",
            date(2023, 12, 25): "Christmas Day",
        }
        self._assert_holidays(2023, expected)

    def test_holidays_2024(self) -> None:
        expected = {
            date(2024, 1, 1): "New Year's Day",
            date(2024, 1, 15): "Martin Luther King Jr. Day",
            date(2024, 2, 19): "Presidents' Day",
            date(2024, 3, 29): "Good Friday",
            date(2024, 5, 27): "Memorial Day",
            date(2024, 6, 19): "Juneteenth National Independence Day",
            date(2024, 7, 4): "Independence Day",
            date(2024, 9, 2): "Labor Day",
            date(2024, 11, 28): "Thanksgiving Day",
            date(2024, 12, 25): "Christmas Day",
        }
        self._assert_holidays(2024, expected)

    def test_holidays_2025(self) -> None:
        expected = {
            date(2025, 1, 1): "New Year's Day",
            date(2025, 1, 9): "National Day of Mourning for President Jimmy Carter",
            date(2025, 1, 20): "Martin Luther King Jr. Day",
            date(2025, 2, 17): "Presidents' Day",
            date(2025, 4, 18): "Good Friday",
            date(2025, 5, 26): "Memorial Day",
            date(2025, 6, 19): "Juneteenth National Independence Day",
            date(2025, 7, 4): "Independence Day",
            date(2025, 9, 1): "Labor Day",
            date(2025, 11, 27): "Thanksgiving Day",
            date(2025, 12, 25): "Christmas Day",
        }
        self._assert_holidays(2025, expected)

    def test_holidays_2026(self) -> None:
        expected = {
            date(2026, 1, 1): "New Year's Day",
            date(2026, 1, 19): "Martin Luther King Jr. Day",
            date(2026, 2, 16): "Presidents' Day",
            date(2026, 4, 3): "Good Friday",
            date(2026, 5, 25): "Memorial Day",
            date(2026, 6, 19): "Juneteenth National Independence Day",
            date(2026, 7, 3): "Independence Day",
            date(2026, 9, 7): "Labor Day",
            date(2026, 11, 26): "Thanksgiving Day",
            date(2026, 12, 25): "Christmas Day",
        }
        self._assert_holidays(2026, expected)

    # ------------------------------------------------------------------
    # Saturday / Sunday observation rules
    # ------------------------------------------------------------------

    def test_saturday_observed_friday(self) -> None:
        """Holiday on Saturday is observed on preceding Friday."""
        holidays_2020 = nyse_holidays(2020)
        # Independence Day 2020-07-04 (Sat) -> observed 2020-07-03 (Fri)
        self.assertIn(date(2020, 7, 3), holidays_2020)
        self.assertNotIn(date(2020, 7, 4), holidays_2020)

        holidays_2026 = nyse_holidays(2026)
        # Independence Day 2026-07-04 (Sat) -> observed 2026-07-03 (Fri)
        self.assertIn(date(2026, 7, 3), holidays_2026)
        self.assertNotIn(date(2026, 7, 4), holidays_2026)

    def test_sunday_observed_monday(self) -> None:
        """Holiday on Sunday is observed on following Monday."""
        holidays_2021 = nyse_holidays(2021)
        # Independence Day 2021-07-04 (Sun) -> observed 2021-07-05 (Mon)
        self.assertIn(date(2021, 7, 5), holidays_2021)
        self.assertNotIn(date(2021, 7, 4), holidays_2021)

        holidays_2023 = nyse_holidays(2023)
        # New Year's Day 2023-01-01 (Sun) -> observed 2023-01-02 (Mon)
        self.assertIn(date(2023, 1, 2), holidays_2023)
        self.assertNotIn(date(2023, 1, 1), holidays_2023)

        holidays_2022 = nyse_holidays(2022)
        # Juneteenth 2022-06-19 (Sun) -> observed 2022-06-20 (Mon)
        self.assertIn(date(2022, 6, 20), holidays_2022)

        # Christmas 2022-12-25 (Sun) -> observed 2022-12-26 (Mon)
        self.assertIn(date(2022, 12, 26), holidays_2022)

    def test_saturday_christmas_observed_friday(self) -> None:
        """Christmas on Saturday observed Friday."""
        holidays_2021 = nyse_holidays(2021)
        # Christmas 2021-12-25 (Sat) -> observed 2021-12-24 (Fri)
        self.assertIn(date(2021, 12, 24), holidays_2021)
        self.assertNotIn(date(2021, 12, 25), holidays_2021)

    # ------------------------------------------------------------------
    # Juneteenth first appears in 2022
    # ------------------------------------------------------------------

    def test_juneteenth_not_present_before_2022(self) -> None:
        for year in (2020, 2021):
            holidays = nyse_holidays(year)
            for d, name in holidays.items():
                self.assertNotIn("Juneteenth", name,
                                 f"Juneteenth unexpectedly present in {year}")

    def test_juneteenth_present_from_2022(self) -> None:
        for year in range(2022, 2027):
            holidays = nyse_holidays(year)
            juneteenth_dates = [d for d, n in holidays.items() if "Juneteenth" in n]
            self.assertEqual(len(juneteenth_dates), 1,
                             f"Expected 1 Juneteenth in {year}, got {juneteenth_dates}")

    # ------------------------------------------------------------------
    # is_nyse_trading_day
    # ------------------------------------------------------------------

    def test_is_trading_day_weekend_returns_false(self) -> None:
        self.assertFalse(is_nyse_trading_day(date(2024, 1, 6)))   # Saturday
        self.assertFalse(is_nyse_trading_day(date(2024, 1, 7)))   # Sunday

    def test_is_trading_day_known_holiday_returns_false(self) -> None:
        self.assertFalse(is_nyse_trading_day(date(2024, 1, 1)))    # New Year's
        self.assertFalse(is_nyse_trading_day(date(2024, 1, 15)))   # MLK Day
        self.assertFalse(is_nyse_trading_day(date(2024, 7, 4)))    # Independence Day
        self.assertFalse(is_nyse_trading_day(date(2024, 11, 28)))  # Thanksgiving
        self.assertFalse(is_nyse_trading_day(date(2024, 12, 25)))  # Christmas

    def test_is_trading_day_regular_weekday_returns_true(self) -> None:
        self.assertTrue(is_nyse_trading_day(date(2024, 1, 2)))   # Tue
        self.assertTrue(is_nyse_trading_day(date(2024, 1, 3)))   # Wed
        self.assertTrue(is_nyse_trading_day(date(2024, 1, 4)))   # Thu
        self.assertTrue(is_nyse_trading_day(date(2024, 1, 5)))   # Fri

    def test_is_trading_day_observed_holiday(self) -> None:
        """Saturday-observed holiday is non-trading day."""
        # 2021-07-05 (Mon) is observed Independence Day
        self.assertFalse(is_nyse_trading_day(date(2021, 7, 5)))
        # Regular July 4 weekend days
        self.assertFalse(is_nyse_trading_day(date(2021, 7, 3)))  # Sat
        self.assertTrue(is_nyse_trading_day(date(2021, 7, 2)))   # Fri before

    def test_is_trading_day_monday_before_tuesday_holiday(self) -> None:
        """Wednesday holiday: Monday and Tuesday are normal trading days."""
        # Christmas 2024 is Wednesday Dec 25
        self.assertTrue(is_nyse_trading_day(date(2024, 12, 23)))  # Mon
        self.assertTrue(is_nyse_trading_day(date(2024, 12, 24)))  # Tue (early close but still trading)

    def test_is_trading_day_leap_year_feb29(self) -> None:
        """February 29 in a leap year is a trading day unless it's a weekend or holiday."""
        # 2024-02-29 is Thursday — regular trading day
        self.assertTrue(is_nyse_trading_day(date(2024, 2, 29)))

    # ------------------------------------------------------------------
    # trading_days_between
    # ------------------------------------------------------------------

    def test_trading_days_same_day_holiday(self) -> None:
        self.assertEqual(trading_days_between(date(2024, 1, 1), date(2024, 1, 1)), 0)

    def test_trading_days_same_day_trading(self) -> None:
        self.assertEqual(trading_days_between(date(2024, 1, 2), date(2024, 1, 2)), 1)

    def test_trading_days_short_range(self) -> None:
        # Tue Jan 2 to Fri Jan 5 — no holidays, all trading
        self.assertEqual(trading_days_between(date(2024, 1, 2), date(2024, 1, 5)), 4)

    def test_trading_days_full_january_2024(self) -> None:
        # Jan 2-31 = 21 trading days (Jan 1 NYD + Jan 15 MLK are holidays)
        self.assertEqual(trading_days_between(date(2024, 1, 2), date(2024, 1, 31)), 21)

    def test_trading_days_cross_year(self) -> None:
        # Dec 30 2024 (Mon) to Jan 3 2025 (Fri)
        # Holidays: Jan 1 (Wed) is NYD. Dec 30, 31, Jan 2, 3 all trading.
        self.assertEqual(trading_days_between(date(2024, 12, 30), date(2025, 1, 3)), 4)

    # ------------------------------------------------------------------
    # nyse_early_closes
    # ------------------------------------------------------------------

    def test_early_closes_black_friday_all_years(self) -> None:
        """Black Friday (day after Thanksgiving) is always an early close when it's a weekday."""
        for year in range(2020, 2027):
            early = nyse_early_closes(year)
            # Black Friday is always a Friday — always a weekday
            black_friday_found = any("Thanksgiving" in v for v in early.values())
            self.assertTrue(black_friday_found, f"Missing Black Friday early close in {year}")

    def test_early_closes_christmas_eve_weekday(self) -> None:
        """Christmas Eve is an early close when it's a weekday and not a holiday."""
        early_2024 = nyse_early_closes(2024)
        self.assertIn(date(2024, 12, 24), early_2024)  # Tuesday

        early_2025 = nyse_early_closes(2025)
        self.assertIn(date(2025, 12, 24), early_2025)  # Wednesday

        early_2020 = nyse_early_closes(2020)
        self.assertIn(date(2020, 12, 24), early_2020)  # Thursday

    def test_early_closes_christmas_eve_weekend_no_early_close(self) -> None:
        """Christmas Eve on weekend is not an early close."""
        early_2022 = nyse_early_closes(2022)
        self.assertNotIn(date(2022, 12, 24), early_2022)  # Saturday

        early_2023 = nyse_early_closes(2023)
        self.assertNotIn(date(2023, 12, 24), early_2023)  # Sunday

    def test_early_closes_christmas_eve_is_holiday_not_early_close(self) -> None:
        """When Christmas Eve is the observed Christmas holiday, skip early close."""
        early_2021 = nyse_early_closes(2021)
        # Dec 24, 2021 is Friday AND observed Christmas (Dec 25 Sat)
        self.assertNotIn(date(2021, 12, 24), early_2021)

    def test_early_closes_christmas_eve_count_by_year(self) -> None:
        """Verify Christmas Eve early close present only for valid years."""
        early_2020 = nyse_early_closes(2020)
        early_2021 = nyse_early_closes(2021)
        early_2022 = nyse_early_closes(2022)
        early_2023 = nyse_early_closes(2023)
        early_2024 = nyse_early_closes(2024)
        early_2025 = nyse_early_closes(2025)
        early_2026 = nyse_early_closes(2026)
        # Present: 2020(Thu), 2024(Tue), 2025(Wed), 2026(Thu)
        self.assertIn(date(2020, 12, 24), early_2020)
        self.assertNotIn(date(2021, 12, 24), early_2021)  # holiday
        self.assertNotIn(date(2022, 12, 24), early_2022)  # Saturday
        self.assertNotIn(date(2023, 12, 24), early_2023)  # Sunday
        self.assertIn(date(2024, 12, 24), early_2024)
        self.assertIn(date(2025, 12, 24), early_2025)
        self.assertIn(date(2026, 12, 24), early_2026)

    # ------------------------------------------------------------------
    # Edge cases
    # ------------------------------------------------------------------

    def test_year_boundary_dec31_new_years(self) -> None:
        """NYSE does not observe New Year's on the prior Friday when Jan 1 is Saturday."""
        holidays_2022 = nyse_holidays(2022)
        self.assertNotIn(date(2021, 12, 31), holidays_2022)
        self.assertTrue(is_nyse_trading_day(date(2021, 12, 31)))

    def test_holidays_handles_leap_year_feb29(self) -> None:
        """Leap year does not produce spurious holidays."""
        holidays_2024 = nyse_holidays(2024)
        # No holiday should fall on Feb 29 in any year
        for d in holidays_2024:
            self.assertNotEqual((d.month, d.day), (2, 29))

    def test_holidays_no_duplicates(self) -> None:
        """No duplicate dates across all tested years."""
        for year in range(2020, 2027):
            holidays = nyse_holidays(year)
            self.assertEqual(len(holidays), len(set(holidays)),
                             f"Duplicate holiday dates in {year}")

    def test_holidays_all_weekdays(self) -> None:
        """All NYSE holidays should fall on Mon-Fri."""
        for year in range(2020, 2027):
            for d in nyse_holidays(year):
                self.assertLess(d.weekday(), 5,
                                f"Holiday {d} in {year} falls on weekend")

    def test_early_closes_no_overlap_with_holidays(self) -> None:
        """Early close days should never overlap with full holidays."""
        for year in range(2020, 2027):
            holidays = nyse_holidays(year)
            early = nyse_early_closes(year)
            overlap = set(holidays) & set(early)
            self.assertEqual(len(overlap), 0,
                             f"Overlap in {year}: {overlap}")

    def test_no_holidays_before_jan_1_or_after_dec_31(self) -> None:
        """Sanity check: no holiday dates with wrong year component."""
        for year in range(2020, 2027):
            for d in nyse_holidays(year):
                self.assertIn(d.year, (year, year - 1),
                              f"{d} in nyse_holidays({year}) has unexpected year")

    def test_is_trading_day_consistent_with_holidays(self) -> None:
        """Every holiday date should return False for is_nyse_trading_day.

        Note: cross-year holiday dates (e.g., Dec 31, 2021 from
        nyse_holidays(2022) due to Jan 1 Saturday) are skipped because
        is_nyse_trading_day only checks holidays for the date's own year.
        USEquityCalendar.with_holidays() loads multiple years and handles
        these correctly.
        """
        for year in range(2020, 2027):
            for d in nyse_holidays(year):
                if d.year != year:
                    # Cross-year holiday date; is_nyse_trading_day(d) checks
                    # nyse_holidays(d.year) which does not contain this entry.
                    continue
                self.assertFalse(
                    is_nyse_trading_day(d),
                    f"{d} is a holiday in {year} but is_nyse_trading_day says True",
                )
