"""Dedicated edge-case tests for LiquiditySlippage model.

Tests cover:
 - BUY / SELL direction (slippage always adds cost)
 - Volume participation cap behaviour (small, near-cap, at-cap)
 - Fallback when bar_volume is zero or quantity is zero
 - Default constructor values
 - Extreme parameter values
 - Equivalence with BpsSlippage when volume impact is disabled
"""
from __future__ import annotations

import unittest

from quant_us.backtest.liquidity_slippage import LiquiditySlippage
from quant_us.backtest.slippage import BpsSlippage
from quant_us.core.enums import OrderSide


class LiquiditySlippageApplyTests(unittest.TestCase):
    """Tests for LiquiditySlippage.apply()."""

    def setUp(self):
        self.slippage = LiquiditySlippage()

    # ------------------------------------------------------------------
    # Direction tests — slippage always moves price against the trader
    # ------------------------------------------------------------------

    def test_buy_fill_price_above_reference(self):
        """BUY: fill_price > reference price (slippage adds cost)."""
        fill_price = self.slippage.apply(OrderSide.BUY, price=100.0, quantity=100, bar_volume=1_000_000)
        self.assertGreater(fill_price, 100.0)

    def test_sell_fill_price_below_reference(self):
        """SELL: fill_price < reference price (slippage adds cost)."""
        fill_price = self.slippage.apply(OrderSide.SELL, price=100.0, quantity=100, bar_volume=1_000_000)
        self.assertLess(fill_price, 100.0)

    def test_buy_and_sell_produce_symmetric_slippage(self):
        """BUY/SELL with same params produce equal absolute deviation from reference."""
        ref = 100.0
        buy_price = self.slippage.apply(OrderSide.BUY, price=ref, quantity=100, bar_volume=1_000_000)
        sell_price = self.slippage.apply(OrderSide.SELL, price=ref, quantity=100, bar_volume=1_000_000)
        buy_bps = (buy_price / ref - 1.0) * 10_000
        sell_bps = (1.0 - sell_price / ref) * 10_000
        self.assertAlmostEqual(buy_bps, sell_bps, places=10)

    # ------------------------------------------------------------------
    # Volume participation cap
    # ------------------------------------------------------------------

    def test_small_order_minimal_additional_slippage(self):
        """Very small participation → total_bps close to base_bps."""
        # participation = abs(1 * 100) / 10_000_000 * 100 = 0.001%
        fill_price = self.slippage.apply(OrderSide.BUY, price=100.0, quantity=1, bar_volume=10_000_000)
        total_bps = (fill_price / 100.0 - 1.0) * 10_000
        # base_bps=0.5, additional ≈ 2.0 * 0.001 = 0.002
        self.assertAlmostEqual(total_bps, 0.502, places=3)

    def test_large_order_near_cap_maximum_slippage(self):
        """Large order → participation capped at volume_cap_pct."""
        # participation = 5000*100 / 100_000 * 100 = 5000% → capped at 5%
        fill_price = self.slippage.apply(OrderSide.BUY, price=100.0, quantity=5000, bar_volume=100_000)
        total_bps = (fill_price / 100.0 - 1.0) * 10_000
        # total_bps = 0.5 + 2.0 * 5.0 = 10.5
        self.assertAlmostEqual(total_bps, 10.5, places=6)

    def test_participation_exactly_at_cap_boundary(self):
        """Order sized so participation == volume_cap_pct."""
        # Want: quantity * price / bar_volume * 100 = 5.0
        # So: quantity = 5.0 * bar_volume / (100 * price)
        price = 100.0
        bar_volume = 100_000.0
        quantity = 5.0 * bar_volume / (100.0 * price)  # = 50
        fill_price = self.slippage.apply(OrderSide.BUY, price=price, quantity=quantity, bar_volume=bar_volume)
        total_bps = (fill_price / price - 1.0) * 10_000
        # capped = 5.0 (exactly), total_bps = 0.5 + 2.0 * 5.0 = 10.5
        self.assertAlmostEqual(total_bps, 10.5, places=6)

    # ------------------------------------------------------------------
    # Edge conditions: zero / missing arguments
    # ------------------------------------------------------------------

    def test_zero_bar_volume_falls_back(self):
        """Zero bar_volume uses fallback (quantity * 100) and still computes."""
        price = 100.0
        quantity = 100.0
        fill_price = self.slippage.apply(OrderSide.BUY, price=price, quantity=quantity, bar_volume=0.0)
        # Fallback: bar_volume = quantity * 100 = 10_000
        # participation = 100*100 / 10_000 * 100 = 100% → capped at 5%
        total_bps = (fill_price / price - 1.0) * 10_000
        self.assertAlmostEqual(total_bps, 10.5, places=6)

    def test_zero_bar_volume_default_argument(self):
        """bar_volume defaults to 0.0, triggering fallback."""
        fill_price = self.slippage.apply(OrderSide.BUY, price=100.0, quantity=100)
        self.assertGreater(fill_price, 100.0)

    def test_zero_quantity_only_base_bps(self):
        """Zero quantity → participation is 0, only base_bps applies."""
        fill_price = self.slippage.apply(OrderSide.BUY, price=100.0, quantity=0, bar_volume=1_000_000)
        total_bps = (fill_price / 100.0 - 1.0) * 10_000
        self.assertAlmostEqual(total_bps, 0.5, places=10)

    def test_zero_quantity_and_zero_bar_volume(self):
        """Both zero → participation stays 0, only base_bps applies."""
        fill_price = self.slippage.apply(OrderSide.BUY, price=100.0, quantity=0, bar_volume=0.0)
        total_bps = (fill_price / 100.0 - 1.0) * 10_000
        self.assertAlmostEqual(total_bps, 0.5, places=10)

    # ------------------------------------------------------------------
    # Default constructor values
    # ------------------------------------------------------------------

    def test_default_constructor_values(self):
        """Default constructor sets documented defaults."""
        s = LiquiditySlippage()
        self.assertEqual(s.base_bps, 0.5)
        self.assertEqual(s.participation_bps, 2.0)
        self.assertEqual(s.volume_impact_scale, 1.0)
        self.assertEqual(s.volume_cap_pct, 5.0)
        self.assertEqual(s.max_bps, 50.0)

    def test_frozen_dataclass(self):
        """LiquiditySlippage is frozen (immutable)."""
        s = LiquiditySlippage()
        with self.assertRaises(AttributeError):
            s.base_bps = 99.0  # type: ignore[misc]

    # ------------------------------------------------------------------
    # Extreme parameter values
    # ------------------------------------------------------------------

    def test_very_high_base_bps_clamped_by_max_bps(self):
        """When base_bps alone exceeds max_bps, result is clamped."""
        s = LiquiditySlippage(base_bps=2000.0, max_bps=50.0)
        # Even with tiny participation: total_bps = 2000 → clamped to 50
        fill_price = s.apply(OrderSide.BUY, price=100.0, quantity=1, bar_volume=10_000_000)
        total_bps = (fill_price / 100.0 - 1.0) * 10_000
        self.assertAlmostEqual(total_bps, 50.0, places=6)

    def test_very_low_volume_cap_pct(self):
        """Low volume_cap_pct aggressively caps participation regardless of order size."""
        s = LiquiditySlippage(volume_cap_pct=0.1, base_bps=0.0, participation_bps=10.0)
        price = 100.0
        # Massive order relative to bar
        fill_price = s.apply(OrderSide.BUY, price=price, quantity=1_000_000, bar_volume=100_000)
        total_bps = (fill_price / price - 1.0) * 10_000
        # participation capped at 0.1% → extra = 10.0 * 0.1 = 1.0 bps
        self.assertAlmostEqual(total_bps, 1.0, places=6)

    def test_max_bps_floor_never_exceeded(self):
        """No combination produces total_bps > max_bps."""
        s = LiquiditySlippage(max_bps=5.0)
        price = 100.0
        for side in (OrderSide.BUY, OrderSide.SELL):
            fill_price = s.apply(side, price=price, quantity=1_000_000, bar_volume=1.0)
            deviation_bps = abs(fill_price / price - 1.0) * 10_000
            self.assertLessEqual(deviation_bps, 5.0 + 1e-9)

    # ------------------------------------------------------------------
    # Equivalence with BpsSlippage
    # ------------------------------------------------------------------

    def test_zero_volume_impact_equals_bps_slippage(self):
        """LiquiditySlippage with zero volume_impact_scale matches BpsSlippage with same base_bps."""
        base = 5.0
        liq = LiquiditySlippage(base_bps=base, participation_bps=0, volume_impact_scale=0.0)
        bps = BpsSlippage(bps=base)
        price = 100.0
        for side in (OrderSide.BUY, OrderSide.SELL):
            expected = bps.apply(side, price)
            actual = liq.apply(side, price=price, quantity=999, bar_volume=1_000_000)
            self.assertEqual(actual, expected)

    def test_zero_volume_impact_ignores_order_size(self):
        """With zero impact scale, order size does not affect fill price."""
        liq = LiquiditySlippage(base_bps=0.5, volume_impact_scale=0.0)
        small = liq.apply(OrderSide.BUY, price=100.0, quantity=1, bar_volume=10_000_000)
        large = liq.apply(OrderSide.BUY, price=100.0, quantity=1_000_000, bar_volume=100_000)
        self.assertEqual(small, large)

    # ------------------------------------------------------------------
    # apply_notional convenience method
    # ------------------------------------------------------------------

    def test_apply_notional_matches_apply(self):
        """apply_notional(side, price, notional, bar_volume) == apply(side, price, notional/price, bar_volume)."""
        s = self.slippage
        price = 100.0
        notional = 5000.0
        bar_volume = 200_000.0
        expected = s.apply(OrderSide.BUY, price=price, quantity=notional / price, bar_volume=bar_volume)
        actual = s.apply_notional(OrderSide.BUY, price=price, notional=notional, bar_volume=bar_volume)
        self.assertAlmostEqual(actual, expected, places=10)


if __name__ == "__main__":
    unittest.main()
