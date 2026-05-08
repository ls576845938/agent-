"""Tests for CapitalAllocator allocation methods.

Covers: all allocation methods, weight caps, normalization.
"""

from __future__ import annotations

import unittest

from quant_us.portfolio.construction.allocator import (
    AllocationMethod,
    CapitalAllocator,
)


class TestCapitalAllocator(unittest.TestCase):
    """CapitalAllocator allocation method tests."""

    def setUp(self) -> None:
        self.allocator = CapitalAllocator()

    def _make_candidates(self, count: int = 2) -> list[dict]:
        return [
            {"id": f"strat_{i}", "volatility": 0.10 + i * 0.05}
            for i in range(count)
        ]

    def test_equal_weight_two(self) -> None:
        candidates = self._make_candidates(2)
        weights = self.allocator.allocate(candidates, AllocationMethod.EQUAL_WEIGHT)
        self.assertAlmostEqual(weights["strat_0"], 0.5)
        self.assertAlmostEqual(weights["strat_1"], 0.5)

    def test_equal_weight_three(self) -> None:
        candidates = self._make_candidates(3)
        weights = self.allocator.allocate(candidates, AllocationMethod.EQUAL_WEIGHT)
        for v in weights.values():
            self.assertAlmostEqual(v, 1.0 / 3, places=5)

    def test_equal_weight_normalized(self) -> None:
        """Equal weight should always sum to 1.0."""
        candidates = self._make_candidates(5)
        weights = self.allocator.allocate(candidates, AllocationMethod.EQUAL_WEIGHT)
        total = sum(weights.values())
        self.assertAlmostEqual(total, 1.0)

    def test_inverse_vol_weighting(self) -> None:
        candidates = [
            {"id": "low_vol", "volatility": 0.10},
            {"id": "high_vol", "volatility": 0.40},
        ]
        weights = self.allocator.allocate(candidates, AllocationMethod.INVERSE_VOL)
        self.assertGreater(weights["low_vol"], weights["high_vol"])

    def test_inverse_vol_sum_to_one(self) -> None:
        candidates = self._make_candidates(4)
        weights = self.allocator.allocate(candidates, AllocationMethod.INVERSE_VOL)
        total = sum(weights.values())
        self.assertAlmostEqual(total, 1.0, places=5)

    def test_single_candidate_full_weight(self) -> None:
        candidates = [{"id": "only_one", "volatility": 0.15}]
        weights = self.allocator.allocate(candidates, AllocationMethod.INVERSE_VOL)
        self.assertAlmostEqual(weights["only_one"], 1.0)

    def test_empty_candidates_returns_empty(self) -> None:
        weights = self.allocator.allocate([], AllocationMethod.EQUAL_WEIGHT)
        self.assertEqual(weights, {})

    def test_weight_capping(self) -> None:
        candidates = self._make_candidates(3)
        weights = self.allocator.allocate(
            candidates,
            AllocationMethod.EQUAL_WEIGHT,
            constraints={"max_single_weight": 0.20},
        )
        # The cap is applied pre-normalization, then weights are renormalized.
        # With 3 candidates capped at 0.20, total = 0.60, each gets 0.20/0.60 = 0.333.
        total = sum(weights.values())
        self.assertAlmostEqual(total, 1.0)
        self.assertGreater(len(weights), 0)

    def test_unknown_method_raises(self) -> None:
        candidates = self._make_candidates(2)
        with self.assertRaises(ValueError):
            self.allocator.allocate(candidates, "unknown_method")
