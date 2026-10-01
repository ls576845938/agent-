"""Tests for OverfitDetector.

Covers: all overfit checks, OOS degradation, param sensitivity, cost failure.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from quant_us.research.automation.overfit import OverfitDetector, OverfitReport


class TestOverfitReport(unittest.TestCase):
    """OverfitReport dataclass."""

    def test_defaults(self) -> None:
        report = OverfitReport(candidate_id="cand_001")
        self.assertEqual(report.candidate_id, "cand_001")
        self.assertFalse(report.is_overfit)
        self.assertEqual(report.reasons, [])

    def test_full_construction(self) -> None:
        report = OverfitReport(
            candidate_id="cand_002",
            is_overfit=True,
            reasons=["OOS degradation too high"],
            degradation_pct=0.5,
            param_sensitivity=0.8,
            trade_count=5,
        )
        self.assertTrue(report.is_overfit)
        self.assertEqual(len(report.reasons), 1)


class TestOverfitDetector(unittest.TestCase):
    """Overfit detection logic."""

    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        self.detector = OverfitDetector(data_root=self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _write_candidate(self, cid: str, metrics: dict | None = None) -> None:
        if metrics is None:
            metrics = {
                "sharpe_ratio": 1.5,
                "in_sample_sharpe": 1.8,
                "out_of_sample_sharpe": 1.2,
                "param_sensitivity": 0.2,
                "trade_count": 50,
                "single_year_concentration": 0.3,
                "single_symbol_concentration": 0.4,
                "cost_sensitivity": 0.1,
            }
        cand_dir = Path(self.tmp.name) / "research" / "candidates" / cid
        cand_dir.mkdir(parents=True, exist_ok=True)
        (cand_dir / "candidate.json").write_text(
            json.dumps({"candidate_id": cid, "metrics": metrics}, indent=2),
            encoding="utf-8",
        )

    def test_clean_candidate_not_overfit(self) -> None:
        self._write_candidate("cand_clean")
        report = self.detector.check("cand_clean")
        self.assertFalse(report.is_overfit)

    def test_oos_degradation_over_40_percent(self) -> None:
        self._write_candidate("cand_oos", {
            "in_sample_sharpe": 2.0,
            "out_of_sample_sharpe": 1.0,
            "trade_count": 50,
        })
        report = self.detector.check("cand_oos")
        self.assertAlmostEqual(report.degradation_pct, 0.5)
        self.assertTrue(report.is_overfit)

    def test_high_param_sensitivity(self) -> None:
        self._write_candidate("cand_param", {
            "param_sensitivity": 0.8,
            "trade_count": 50,
        })
        report = self.detector.check("cand_param")
        self.assertTrue(report.is_overfit)

    def test_too_few_trades(self) -> None:
        self._write_candidate("cand_few", {
            "trade_count": 3,
        })
        report = self.detector.check("cand_few")
        self.assertTrue(report.is_overfit)

    def test_high_single_year_concentration(self) -> None:
        self._write_candidate("cand_year", {
            "single_year_concentration": 0.6,
            "trade_count": 50,
        })
        report = self.detector.check("cand_year")
        self.assertTrue(report.is_overfit)

    def test_high_single_symbol_concentration(self) -> None:
        self._write_candidate("cand_sym", {
            "single_symbol_concentration": 0.7,
            "trade_count": 50,
        })
        report = self.detector.check("cand_sym")
        self.assertTrue(report.is_overfit)

    def test_cost_stress_failure(self) -> None:
        self._write_candidate("cand_cost", {
            "cost_sensitivity": 0.8,
            "trade_count": 50,
        })
        report = self.detector.check("cand_cost")
        self.assertTrue(report.is_overfit)

    def test_multiple_reasons(self) -> None:
        self._write_candidate("cand_multi", {
            "param_sensitivity": 0.8,
            "trade_count": 3,
            "single_year_concentration": 0.7,
            "single_symbol_concentration": 0.8,
        })
        report = self.detector.check("cand_multi")
        self.assertTrue(report.is_overfit)
        self.assertGreaterEqual(len(report.reasons), 3)

    def test_missing_candidate_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.detector.check("cand_nonexistent")

    def test_degradation_calculation(self) -> None:
        """Test static method _compute_degradation."""
        d = OverfitDetector._compute_degradation(2.0, 1.0)
        self.assertAlmostEqual(d, 0.5)

        d = OverfitDetector._compute_degradation(1.0, 1.5)
        self.assertEqual(d, 0.0)  # OOS better than IS, no degradation

        d = OverfitDetector._compute_degradation(0.0, 0.0)
        self.assertEqual(d, 0.0)
