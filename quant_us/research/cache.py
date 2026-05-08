"""Research cache for feature and factor computations.

Avoids redundant parquet reads and factor computations by caching
results using content-addressable keys.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd


class ResearchCache:
    """Cache for research computations (features, factors, datasets).

    Uses SHA-256 content hashing on cache keys to avoid collisions.
    Cached values are stored as parquet files for features/factors
    or JSON for scalar values.
    """

    def __init__(self, cache_root: str = "data/cache") -> None:
        self.cache_root = Path(cache_root)
        self.cache_root.mkdir(parents=True, exist_ok=True)

    def get(self, key: str) -> pd.DataFrame | None:
        """Retrieve a cached DataFrame by key.

        Args:
            key: Cache key string.

        Returns:
            Cached DataFrame if found, None otherwise.
        """
        path = self._path(key)
        if not path.exists():
            return None
        try:
            return pd.read_parquet(str(path))
        except Exception:
            return None

    def set(self, key: str, value: pd.DataFrame) -> None:
        """Cache a DataFrame under the given key.

        Args:
            key: Cache key string.
            value: DataFrame to cache.
        """
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        value.to_parquet(str(path), index=False)

    def get_json(self, key: str) -> Any | None:
        """Retrieve a cached JSON-serializable value by key.

        Args:
            key: Cache key string.

        Returns:
            Cached value if found, None otherwise.
        """
        path = self._json_path(key)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    def set_json(self, key: str, value: Any) -> None:
        """Cache a JSON-serializable value under the given key.

        Args:
            key: Cache key string.
            value: Value to cache (must be JSON-serializable).
        """
        path = self._json_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, default=str), encoding="utf-8")

    def has(self, key: str) -> bool:
        """Check if a key exists in the cache.

        Args:
            key: Cache key string.

        Returns:
            True if the key exists.
        """
        return self._path(key).exists() or self._json_path(key).exists()

    def invalidate(self, key: str) -> bool:
        """Remove a key from the cache.

        Args:
            key: Cache key string.

        Returns:
            True if a value was removed.
        """
        removed = False
        path = self._path(key)
        if path.exists():
            path.unlink()
            removed = True
        json_path = self._json_path(key)
        if json_path.exists():
            json_path.unlink()
            removed = True
        return removed

    def clear(self) -> int:
        """Clear all cached values.

        Returns:
            Number of files removed.
        """
        count = 0
        if self.cache_root.exists():
            for path in self.cache_root.rglob("*"):
                if path.is_file():
                    path.unlink()
                    count += 1
        return count

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _hash_key(self, key: str) -> str:
        return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]

    def _path(self, key: str) -> Path:
        return self.cache_root / "parquet" / f"{self._hash_key(key)}.parquet"

    def _json_path(self, key: str) -> Path:
        return self.cache_root / "json" / f"{self._hash_key(key)}.json"
