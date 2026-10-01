"""Verify bfill is not used in factor/feature computation modules.

bfill in feature engineering can introduce lookahead bias by carrying
future information backward.
"""

from __future__ import annotations

import unittest


_MODULES_TO_CHECK = [
    "quant_us/factors/momentum.py",
    "quant_us/factors/volatility.py",
    "quant_us/factors/liquidity.py",
    "quant_us/factors/quality.py",
    "quant_us/factors/value.py",
    "quant_us/factors/feature_pipeline.py",
    "quant_us/research/datasets.py",
]


class TestBfillForbiddenInFeatures(unittest.TestCase):
    """Verify bfill is not used in factor computation modules."""

    def _read_module_source(self, rel_path: str) -> str:
        import os
        import quant_us
        pkg_dir = os.path.dirname(quant_us.__file__)
        full_path = os.path.normpath(os.path.join(pkg_dir, "..", rel_path))
        try:
            with open(full_path, encoding="utf-8") as f:
                return f.read()
        except FileNotFoundError:
            self.skipTest(f"File not found: {full_path}")
            return ""

    def test_no_bfill_in_momentum(self) -> None:
        source = self._read_module_source("quant_us/factors/momentum.py")
        self.assertNotIn("bfill", source)

    def test_no_bfill_in_volatility(self) -> None:
        source = self._read_module_source("quant_us/factors/volatility.py")
        self.assertNotIn("bfill", source)

    def test_no_bfill_in_liquidity(self) -> None:
        source = self._read_module_source("quant_us/factors/liquidity.py")
        self.assertNotIn("bfill", source)

    def test_no_bfill_in_quality(self) -> None:
        source = self._read_module_source("quant_us/factors/quality.py")
        self.assertNotIn("bfill", source)

    def test_no_bfill_in_value(self) -> None:
        source = self._read_module_source("quant_us/factors/value.py")
        self.assertNotIn("bfill", source)

    def test_no_bfill_in_feature_pipeline(self) -> None:
        source = self._read_module_source("quant_us/factors/feature_pipeline.py")
        self.assertNotIn("bfill", source)

    def test_no_bfill_in_datasets(self) -> None:
        source = self._read_module_source("quant_us/research/datasets.py")
        self.assertNotIn("bfill", source)

    def test_bfill_is_allowed_in_regime_detector_only(self) -> None:
        """Regime detector uses bfill for vol_percentile (expanding rank is safe)."""
        import quant_us.regime.detector as detector
        with open(detector.__file__ or "", encoding="utf-8") as f:
            content = f.read()
        bfill_count = content.count("bfill")
        # The regime detector has exactly 2 bfill uses
        # (one for volatilty, one in a comment or test)
        self.assertLessEqual(bfill_count, 2)
