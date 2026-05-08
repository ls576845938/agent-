"""Tests for LookaheadBiasChecker.

Covers: high IC detection, bfill detection, shift(-1) detection.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from quant_us.research.automation.overfit import LookaheadBiasChecker


class TestLookaheadBiasChecker(unittest.TestCase):
    """Lookahead bias detection tests."""

    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        self.checker = LookaheadBiasChecker(data_root=self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _write_factor_metrics(self, factor_id: str, metrics: dict) -> None:
        factor_dir = Path(self.tmp.name) / "research" / "factors"
        factor_dir.mkdir(parents=True, exist_ok=True)
        (factor_dir / f"{factor_id}.json").write_text(
            json.dumps(metrics), encoding="utf-8"
        )

    def _write_experiment(self, eid: str, data: dict) -> None:
        exp_dir = Path(self.tmp.name) / "research" / "experiments" / eid
        exp_dir.mkdir(parents=True, exist_ok=True)
        (exp_dir / "manifest.json").write_text(
            json.dumps(data, indent=2), encoding="utf-8"
        )

    def test_check_missing_factor(self) -> None:
        has_bias, msg = self.checker.check("unknown_factor")
        self.assertFalse(has_bias)

    def test_high_ic_detected(self) -> None:
        self._write_factor_metrics("factor_high_ic", {"ic": 0.3, "ic_std": 0.05})
        has_bias, msg = self.checker.check("factor_high_ic")
        self.assertTrue(has_bias)
        self.assertIn("suspiciously high IC", msg)

    def test_low_ic_not_flagged(self) -> None:
        self._write_factor_metrics("factor_low_ic", {"ic": 0.05, "ic_std": 0.05})
        has_bias, msg = self.checker.check("factor_low_ic")
        self.assertFalse(has_bias)

    def test_constant_ic_detected(self) -> None:
        self._write_factor_metrics("factor_const", {"ic": 0.1, "ic_std": 0.0})
        has_bias, msg = self.checker.check("factor_const")
        self.assertTrue(has_bias)
        self.assertIn("constant across all periods", msg)

    def test_bfill_detected_in_experiment(self) -> None:
        self._write_experiment("exp_bfill", {
            "params": {"bfill_features": True},
            "metrics": {},
        })
        has_bias, msg = self.checker.check_experiment("exp_bfill")
        self.assertTrue(has_bias)
        self.assertIn("bfill", msg)

    def test_shift_minus_one_detected(self) -> None:
        self._write_experiment("exp_shift", {
            "params": {"shift_minus_one": True},
            "metrics": {},
        })
        has_bias, msg = self.checker.check_experiment("exp_shift")
        self.assertTrue(has_bias)
        self.assertIn("shift(-1)", msg)

    def test_high_sharpe_detected(self) -> None:
        self._write_experiment("exp_high_sharpe", {
            "params": {},
            "metrics": {"sharpe_ratio": 4.0},
        })
        has_bias, msg = self.checker.check_experiment("exp_high_sharpe")
        self.assertTrue(has_bias)

    def test_clean_experiment_passes(self) -> None:
        self._write_experiment("exp_clean", {
            "params": {},
            "metrics": {"sharpe_ratio": 1.5},
        })
        has_bias, msg = self.checker.check_experiment("exp_clean")
        self.assertFalse(has_bias)
        self.assertIn("passed", msg)
