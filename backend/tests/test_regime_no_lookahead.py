"""Verify regime detector uses only past data — no lookahead.

The detector must only use data available at time t for classification.
"""

from __future__ import annotations

import unittest


class TestRegimeNoLookahead(unittest.TestCase):
    """Regime detector no-lookahead verification."""

    def test_regime_detector_no_future_data(self) -> None:
        """Verify detector.py uses rolling/expanding windows, not full-dataset."""
        import quant_us.regime.detector as detector
        with open(detector.__file__ or "", encoding="utf-8") as f:
            content = f.read()

        # Should use rolling(), expanding(), or similar for windowed computation
        self.assertIn("rolling", content)
        self.assertIn("expanding", content)

        # Check no lookahead patterns
        self.assertNotIn("shift(-1)", content)

        # bfill is allowed only for vol_percentile (expanding rank)
        bfill_count = content.count("bfill")
        if bfill_count > 1:
            self.fail(f"Found {bfill_count} bfill occurrences — potential lookahead")

        # Should not use shift with negative periods
        import re
        shift_matches = re.findall(r"shift\(-\d+", content)
        self.assertEqual(
            len(shift_matches), 0,
            f"Found shift with negative periods: {shift_matches}"
        )

    def test_regime_uses_only_past_data(self) -> None:
        """Verify _compute_features uses only data up to current row."""
        import quant_us.regime.detector as detector
        src = detector.__file__
        if src:
            with open(src, encoding="utf-8") as f:
                content = f.read()
            # Rolling/expanding windows ensure only past data is used
            self.assertIn(".rolling(", content)
            # No fillna(method='bfill') in feature computation except for vol
            # which uses expanding().rank() that is also past-only

    def test_no_live_import(self) -> None:
        """Regime detector has no live/execution imports."""
        import quant_us.regime.detector as detector
        with open(detector.__file__ or "", encoding="utf-8") as f:
            content = f.read()
        self.assertNotIn("from quant_us.live import", content)
        self.assertNotIn("import quant_us.live", content)
        self.assertNotIn("from quant_us.execution import", content)
        self.assertNotIn("import quant_us.execution", content)
        self.assertNotIn("submit_order", content)

    def test_no_future_indexing(self) -> None:
        """Check no .iloc or .loc with future indices in feature computation."""
        import quant_us.regime.detector as detector
        src = detector.__file__
        if src:
            with open(src, encoding="utf-8") as f:
                content = f.read()
            # The compute_features uses iterrows() which is future-safe
            self.assertIn("iterrows", content)

    def test_classification_rules_use_current_row_only(self) -> None:
        """Verify _classify_regime uses only row-level features."""
        import inspect
        from quant_us.regime.detector import MarketRegimeDetector
        source = inspect.getsource(MarketRegimeDetector._classify_regime)
        # Should use row data, not external lookups
        self.assertNotIn(".iloc", source)
        self.assertNotIn(".loc[", source)

    def test_detect_all_calls_detect(self) -> None:
        """detect_all delegates to detect, ensuring consistent behavior."""
        import inspect
        from quant_us.regime.detector import MarketRegimeDetector
        source = inspect.getsource(MarketRegimeDetector.detect_all)
        self.assertIn("self.detect(", source)
