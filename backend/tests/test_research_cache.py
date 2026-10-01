"""Tests for ResearchCache.

Covers: feature cache, factor cache, avoid duplicate parquet reads.
"""

from __future__ import annotations

import unittest
from tempfile import TemporaryDirectory

import pandas as pd

from quant_us.research.cache import ResearchCache


class TestResearchCache(unittest.TestCase):
    """Cache storage and retrieval."""

    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        self.cache = ResearchCache(cache_root=self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_set_and_get_dataframe(self) -> None:
        df = pd.DataFrame({"a": [1, 2, 3], "b": [4, 5, 6]})
        self.cache.set("test_key", df)
        retrieved = self.cache.get("test_key")
        self.assertIsNotNone(retrieved)
        self.assertEqual(len(retrieved), 3)

    def test_get_nonexistent(self) -> None:
        result = self.cache.get("nonexistent")
        self.assertIsNone(result)

    def test_set_and_get_json(self) -> None:
        data = {"sharpe": 1.5, "cagr": 0.12}
        self.cache.set_json("metrics_key", data)
        retrieved = self.cache.get_json("metrics_key")
        self.assertEqual(retrieved["sharpe"], 1.5)

    def test_get_json_nonexistent(self) -> None:
        result = self.cache.get_json("nonexistent")
        self.assertIsNone(result)

    def test_has_key(self) -> None:
        self.cache.set_json("exists", {"val": 1})
        self.assertTrue(self.cache.has("exists"))
        self.assertFalse(self.cache.has("not_exists"))

    def test_invalidate_removes_key(self) -> None:
        self.cache.set_json("temp", {"val": 1})
        self.assertTrue(self.cache.has("temp"))
        self.cache.invalidate("temp")
        self.assertFalse(self.cache.has("temp"))

    def test_clear_removes_all(self) -> None:
        self.cache.set_json("k1", {"v": 1})
        self.cache.set_json("k2", {"v": 2})
        count = self.cache.clear()
        self.assertEqual(count, 2)
        self.assertFalse(self.cache.has("k1"))
        self.assertFalse(self.cache.has("k2"))

    def test_cache_key_hashing_is_consistent(self) -> None:
        key1_hash = self.cache._hash_key("same_key")
        key2_hash = self.cache._hash_key("same_key")
        self.assertEqual(key1_hash, key2_hash)

    def test_different_keys_different_hashes(self) -> None:
        h1 = self.cache._hash_key("key_a")
        h2 = self.cache._hash_key("key_b")
        self.assertNotEqual(h1, h2)

    def test_cache_different_dataframes(self) -> None:
        df1 = pd.DataFrame({"x": [1.0, 2.0, 3.0]})
        df2 = pd.DataFrame({"y": [10.0, 20.0]})
        self.cache.set("df1", df1)
        self.cache.set("df2", df2)
        r1 = self.cache.get("df1")
        r2 = self.cache.get("df2")
        self.assertEqual(len(r1), 3)
        self.assertEqual(len(r2), 2)
