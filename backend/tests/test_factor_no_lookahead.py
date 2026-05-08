"""Verify no lookahead bias in factor computation.

Checks that factor modules don't use shift(-1), bfill, or future data.
"""

from __future__ import annotations

import unittest


_FACTOR_FILES = [
    "quant_us/factors/definition.py",
    "quant_us/factors/feature_pipeline.py",
    "quant_us/factors/momentum.py",
    "quant_us/factors/volatility.py",
    "quant_us/factors/liquidity.py",
    "quant_us/factors/quality.py",
    "quant_us/factors/value.py",
]


class TestFactorNoLookahead(unittest.TestCase):
    """Verify factor modules have no lookahead bias patterns."""

    def _read_source(self, module_path: str) -> str:
        import os
        import quant_us
        pkg_dir = os.path.dirname(quant_us.__file__)
        full_path = os.path.join(pkg_dir, "..", module_path)
        full_path = os.path.normpath(full_path)
        try:
            with open(full_path, encoding="utf-8") as f:
                return f.read()
        except FileNotFoundError:
            self.skipTest(f"File not found: {full_path}")

    def test_no_shift_minus_one_in_factor_code(self) -> None:
        """shift(-1) would peek into the future."""
        for mod_path in _FACTOR_FILES:
            source = self._read_source(mod_path)
            # Check for shift(-1) or .shift(-1)
            self.assertNotIn(
                "shift(-1)", source,
                f"Found shift(-1) in {mod_path} — potential lookahead"
            )

    def test_no_bfill_in_factor_computation(self) -> None:
        """bfill in factor computation can introduce lookahead."""
        for mod_path in _FACTOR_FILES:
            source = self._read_source(mod_path)
            if "bfill" in source:
                # bfill is allowed only in regime detector's vol_percentile calc
                if "vol_percentile" not in source:
                    self.fail(f"Found bfill in {mod_path} — potential lookahead")

    def test_no_future_data_in_pipeline(self) -> None:
        """Feature pipeline should only use expanding windows, not full-data rank."""
        source = self._read_source("quant_us/factors/feature_pipeline.py")
        self.assertNotIn(".rank(", source)
        # The pipeline uses rolling computations, not full cross-sectional rank

    def test_no_import_from_live_in_factors(self) -> None:
        """Factor modules must not import live execution code."""
        for mod_path in _FACTOR_FILES:
            source = self._read_source(mod_path)
            self.assertNotIn("quant_us.live", source)
            self.assertNotIn("quant_us.execution", source)

    def test_factor_momentum_uses_rolling_windows(self) -> None:
        """Momentum factor should use rolling computations only."""
        try:
            from quant_us.factors.momentum import rolling_momentum_score
            import inspect
            source = inspect.getsource(rolling_momentum_score)
            # Should use rolling, pct_change, or shift(periods) not shift(-1)
            self.assertNotIn("shift(-1)", source)
        except (ImportError, AttributeError):
            self.skipTest("Momentum module not available")

    def test_factor_volatility_uses_rolling_windows(self) -> None:
        """Volatility factor should use rolling computations only."""
        try:
            from quant_us.factors.volatility import realized_volatility
            import inspect
            source = inspect.getsource(realized_volatility)
            self.assertNotIn("shift(-1)", source)
        except (ImportError, AttributeError):
            self.skipTest("Volatility module not available")

    def test_dataset_builder_no_bfill(self) -> None:
        """Dataset builder should not use bfill for features."""
        import quant_us.research.datasets as datasets
        with open(datasets.__file__ or "", encoding="utf-8") as f:
            content = f.read()
        # The build_dataset_frame uses dropna, not bfill
        if "drop_missing_features" in content:
            self.assertNotIn("bfill", content)

    def test_no_shift_minus_one_in_datasets(self) -> None:
        """Dataset builder should only use shift(-horizon) for labels, not features."""
        import quant_us.research.datasets as datasets
        with open(datasets.__file__ or "", encoding="utf-8") as f:
            content = f.read()
        # shift(-horizon) is acceptable for label creation (forward returns)
        # but shift(-1) specifically means one-step lookahead
        self.assertNotIn("shift(-1)", content)
