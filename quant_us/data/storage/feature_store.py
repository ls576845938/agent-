from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

import pandas as pd


@dataclass(frozen=True)
class FeatureWriteResult:
    rows_written: int
    files_written: list[Path]


class ParquetFeatureStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def write_factor_values(self, frame: pd.DataFrame, version: str) -> FeatureWriteResult:
        if frame.empty:
            return FeatureWriteResult(0, [])
        working = frame.copy()
        working["date"] = pd.to_datetime(working["date"]).dt.strftime("%Y-%m-%d")
        files_written: list[Path] = []
        for (factor_name, date_value), group in working.groupby(["factor_name", "date"]):
            version_dir = self.root / f"factor_name={factor_name}" / f"version={version}"
            version_dir.mkdir(parents=True, exist_ok=True)
            path = version_dir / f"date={date_value}.parquet"
            output = group.copy()
            if path.exists():
                existing = pd.read_parquet(path)
                output = pd.concat([existing, output], ignore_index=True)
            output = output.drop_duplicates(subset=["symbol", "factor_name", "universe"], keep="last")
            output.to_parquet(path, index=False)
            files_written.append(path)
            # Write checksum alongside partition
            checksum_path = version_dir / f"date={date_value}.sha256"
            checksum_path.write_text(self._compute_checksum(output), encoding="utf-8")
        return FeatureWriteResult(rows_written=len(frame), files_written=files_written)

    @staticmethod
    def _compute_checksum(df: pd.DataFrame) -> str:
        """SHA-256 of sorted values for content integrity."""
        h = hashlib.sha256()
        for col in sorted(df.columns):
            h.update(col.encode())
            for v in sorted(df[col].astype(str)):
                h.update(v.encode())
        return h.hexdigest()[:16]

    def read_as_of(
        self,
        factor_name: str,
        version: str,
        as_of_date: str,
        symbols: list[str] | None = None,
    ) -> pd.DataFrame:
        """Return factor values as they existed on or before as_of_date.

        For each symbol, returns the most recent value before as_of_date.
        Uses DuckDB for efficient window-based query.
        """
        base = self.root / f"factor_name={factor_name}" / f"version={version}"
        if not base.exists():
            return pd.DataFrame()
        try:
            import duckdb

            glob = str(base / "date=*.parquet")
            sql = "SELECT * FROM ("
            sql += " SELECT *, ROW_NUMBER() OVER ("
            sql += "   PARTITION BY symbol ORDER BY date DESC"
            sql += " ) AS _rn"
            sql += f" FROM read_parquet('{glob}')"
            sql += " WHERE date <= ?"
            if symbols:
                placeholders = ", ".join("?" for _ in symbols)
                sql += f" AND symbol IN ({placeholders})"
            sql += ") WHERE _rn = 1"
            params: list[str | None] = [as_of_date]
            if symbols:
                params.extend(symbols)
            result = duckdb.execute(sql, params).df()
            result = result.drop(columns=["_rn"])
            return result
        except Exception:
            pass
        # Fallback: eager read with pandas
        parts = []
        for p in sorted(base.glob("date=*.parquet")):
            df_part = pd.read_parquet(p)
            df_part = df_part[df_part["date"] <= as_of_date]
            if symbols:
                df_part = df_part[df_part["symbol"].isin(symbols)]
            if not df_part.empty:
                parts.append(df_part)
        if not parts:
            return pd.DataFrame()
        frame = pd.concat(parts, ignore_index=True)
        frame = frame.sort_values("date").groupby("symbol").last().reset_index()
        return frame

    def read_factor_values(
        self,
        factor_name: str,
        version: str,
        columns: list[str] | None = None,
        start: str | None = None,
        end: str | None = None,
        use_duckdb: bool = True,
    ) -> pd.DataFrame:
        """Read factor values with optional DuckDB lazy scan.

        When *use_duckdb* is True and a date filter is present, DuckDB's
        ``read_parquet`` with predicate pushdown is used, avoiding a full
        eager scan of every partition file.
        """
        base = self.root / f"factor_name={factor_name}" / f"version={version}"
        if not base.exists():
            return pd.DataFrame()

        has_filter = start is not None or end is not None
        if use_duckdb and has_filter:
            try:
                return self._read_lazy(factor_name, version, columns, start, end)
            except Exception:
                pass  # fall back to eager

        return self._read_eager(base, columns, start, end)

    def _read_lazy(
        self,
        factor_name: str,
        version: str,
        columns: list[str] | None,
        start: str | None,
        end: str | None,
    ) -> pd.DataFrame:
        import duckdb

        base = self.root / f"factor_name={factor_name}" / f"version={version}"
        glob = str(base / "date=*.parquet")
        col_list = ", ".join(columns) if columns else "*"
        sql = f"SELECT {col_list} FROM read_parquet('{glob}') WHERE 1=1"
        params: list[str] = []
        if start:
            sql += " AND date >= ?"
            params.append(start)
        if end:
            sql += " AND date <= ?"
            params.append(end)
        return duckdb.execute(sql, params).df()

    @staticmethod
    def _read_eager(
        base: Path,
        columns: list[str] | None,
        start: str | None,
        end: str | None,
    ) -> pd.DataFrame:
        parts = [pd.read_parquet(path, columns=columns) for path in sorted(base.glob("date=*.parquet"))]
        if not parts:
            return pd.DataFrame()
        frame = pd.concat(parts, ignore_index=True)
        if start:
            frame = frame[frame["date"] >= start]
        if end:
            frame = frame[frame["date"] <= end]
        return frame


class FeatureCache:
    """In-memory cache for computed factor values.

    Avoids recomputing common factors across backtest runs.
    Thread-safe via simple dict; not distributed.
    """

    def __init__(self) -> None:
        self._cache: dict[str, pd.DataFrame] = {}

    def get(self, key: str) -> pd.DataFrame | None:
        return self._cache.get(key)

    def put(self, key: str, frame: pd.DataFrame) -> None:
        self._cache[key] = frame.copy()

    def invalidate(self, key: str | None = None) -> None:
        if key is None:
            self._cache.clear()
        else:
            self._cache.pop(key, None)

    def compute_or_get(
        self, key: str, factory: Callable[[], pd.DataFrame]
    ) -> pd.DataFrame:
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        frame = factory()
        self._cache[key] = frame.copy()
        return frame
