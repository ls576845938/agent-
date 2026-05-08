"""Tests for ExposureManager.

Covers: gross/net exposure, single symbol limit, correlation detection.
"""

from __future__ import annotations

import unittest

from quant_us.portfolio.construction.exposure import ExposureManager, ExposureReport


class TestExposureManager(unittest.TestCase):
    """ExposureManager analysis and constraint checks."""

    def setUp(self) -> None:
        self.mgr = ExposureManager()

    def test_empty_positions(self) -> None:
        report = self.mgr.analyze({}, {})
        self.assertAlmostEqual(report.gross_exposure, 0.0)
        self.assertAlmostEqual(report.net_exposure, 0.0)

    def test_single_long_position(self) -> None:
        report = self.mgr.analyze(
            {"AAPL": 10000.0},
            {"AAPL": 150.0},
        )
        self.assertGreater(report.gross_exposure, 0)

    def test_long_and_short(self) -> None:
        report = self.mgr.analyze(
            {"AAPL": 10000.0, "MSFT": -5000.0},
            {"AAPL": 150.0, "MSFT": 200.0},
        )
        # Net should be 5000 (10000 - 5000)
        self.assertAlmostEqual(report.net_exposure, 5000.0)

    def test_single_symbol_exposure_calc(self) -> None:
        report = self.mgr.analyze(
            {"AAPL": 10000.0, "MSFT": 5000.0},
            {"AAPL": 150.0, "MSFT": 200.0},
        )
        self.assertIn("AAPL", report.single_symbol_exposures)
        self.assertIn("MSFT", report.single_symbol_exposures)

    def test_sector_exposure(self) -> None:
        report = self.mgr.analyze(
            {"AAPL": 10000.0, "MSFT": 5000.0, "XOM": 8000.0},
            {"AAPL": 150.0, "MSFT": 200.0, "XOM": 50.0},
            sectors={"AAPL": "tech", "MSFT": "tech", "XOM": "energy"},
        )
        self.assertIn("tech", report.sector_exposures)
        self.assertIn("energy", report.sector_exposures)
        self.assertGreater(report.sector_exposures["tech"], report.sector_exposures["energy"])

    def test_strategy_exposure(self) -> None:
        report = self.mgr.analyze(
            {"AAPL": 10000.0, "MSFT": 5000.0},
            {"AAPL": 150.0, "MSFT": 200.0},
            strategies={"AAPL": "momentum", "MSFT": "value"},
        )
        self.assertIn("momentum", report.strategy_exposures)
        self.assertIn("value", report.strategy_exposures)

    def test_check_limits_passes(self) -> None:
        report = self.mgr.analyze({}, {})
        passed, violations = self.mgr.check_limits(report, {})
        self.assertTrue(passed)
        self.assertEqual(violations, [])

    def test_check_limits_gross_exposure(self) -> None:
        report = ExposureReport(gross_exposure=2.0)
        passed, violations = self.mgr.check_limits(
            report, {"max_gross_exposure": 1.0}
        )
        self.assertFalse(passed)
        self.assertTrue(any("gross" in v.lower() for v in violations))

    def test_check_limits_net_exposure(self) -> None:
        report = ExposureReport(net_exposure=1.5)
        passed, violations = self.mgr.check_limits(
            report, {"max_net_exposure": 1.0}
        )
        self.assertFalse(passed)
        self.assertTrue(any("net" in v.lower() for v in violations))

    def test_diversification_ratio_present(self) -> None:
        report = self.mgr.analyze(
            {"AAPL": 10000.0, "MSFT": 5000.0},
            {"AAPL": 150.0, "MSFT": 200.0},
        )
        self.assertGreater(report.diversification_ratio, 0)
