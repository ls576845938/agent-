"""Tests for FactorDefinition and FactorLibrary.

Covers: factor registration, categories, library list.
"""

from __future__ import annotations

import unittest

from quant_us.factors.definition import (
    FACTOR_CATEGORIES,
    FactorDefinition,
    FactorLibrary,
)


class TestFactorDefinition(unittest.TestCase):
    """FactorDefinition dataclass validation."""

    def test_valid_factor(self) -> None:
        factor = FactorDefinition(
            factor_id="test_momentum",
            name="Test Momentum",
            category="momentum",
            lookback=20,
        )
        self.assertEqual(factor.factor_id, "test_momentum")
        self.assertEqual(factor.category, "momentum")

    def test_invalid_category_raises(self) -> None:
        with self.assertRaises(ValueError):
            FactorDefinition(
                factor_id="bad",
                name="Bad",
                category="nonexistent",
            )

    def test_invalid_neutralization_raises(self) -> None:
        with self.assertRaises(ValueError):
            FactorDefinition(
                factor_id="bad",
                name="Bad",
                category="momentum",
                neutralization="invalid",
            )

    def test_invalid_rank_method_raises(self) -> None:
        with self.assertRaises(ValueError):
            FactorDefinition(
                factor_id="bad",
                name="Bad",
                category="momentum",
                rank_method="invalid",
            )

    def test_default_winsorize_pct(self) -> None:
        factor = FactorDefinition(factor_id="test", name="Test", category="momentum")
        self.assertEqual(factor.winsorize_pct, 0.01)

    def test_default_required_fields(self) -> None:
        factor = FactorDefinition(factor_id="test", name="Test", category="momentum")
        self.assertEqual(factor.required_fields, ["close"])


class TestFactorLibrary(unittest.TestCase):
    """FactorLibrary registry tests."""

    def setUp(self) -> None:
        self.lib = FactorLibrary()

    def test_has_builtin_factors(self) -> None:
        all_factors = self.lib.list_all()
        self.assertGreater(len(all_factors), 0)

    def test_get_builtin_factor(self) -> None:
        factor = self.lib.get("momentum_60d")
        self.assertEqual(factor.factor_id, "momentum_60d")
        self.assertEqual(factor.category, "momentum")

    def test_get_unknown_raises(self) -> None:
        with self.assertRaises(KeyError):
            self.lib.get("nonexistent_factor")

    def test_list_by_category(self) -> None:
        momentum_factors = self.lib.list_by_category("momentum")
        for f in momentum_factors:
            self.assertEqual(f.category, "momentum")

    def test_list_by_category_empty(self) -> None:
        factors = self.lib.list_by_category("macro")
        # macro is a valid category but may have no registered factors
        self.assertIsInstance(factors, list)

    def test_factor_ids(self) -> None:
        ids = self.lib.factor_ids()
        self.assertIn("momentum_60d", ids)
        self.assertIn("volatility_20d", ids)
        self.assertIn("liquidity_20d", ids)

    def test_register_custom_factor(self) -> None:
        custom = FactorDefinition(
            factor_id="custom_factor",
            name="Custom",
            category="quality",
        )
        self.lib.register(custom)
        retrieved = self.lib.get("custom_factor")
        self.assertEqual(retrieved.factor_id, "custom_factor")

    def test_register_overwrites(self) -> None:
        orig = FactorDefinition(
            factor_id="dup", name="Original", category="momentum"
        )
        self.lib.register(orig)
        updated = FactorDefinition(
            factor_id="dup", name="Updated", category="volatility"
        )
        self.lib.register(updated)
        retrieved = self.lib.get("dup")
        self.assertEqual(retrieved.name, "Updated")

    def test_factors_have_required_fields(self) -> None:
        for factor in self.lib.list_all():
            self.assertIsInstance(factor.factor_id, str)
            self.assertIn(factor.category, FACTOR_CATEGORIES)
