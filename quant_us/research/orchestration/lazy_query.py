"""Lazy dataset backed by DuckDB scanning parquet files.

Only reads necessary columns and applies predicate pushdown on date/symbol
to minimise I/O.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class LazyStats:
    """Summary statistics for a lazy dataset."""

    row_count: int = 0
    columns: list[str] = field(default_factory=list)
    date_min: str = ""
    date_max: str = ""
    symbol_count: int = 0


class LazyDataset:
    """Lazy dataset backed by DuckDB scanning parquet files.

    Only reads necessary columns and applies predicate pushdown on date/symbol.
    """

    def __init__(self, parquet_path: str) -> None:
        self._parquet_path = parquet_path
        self._columns: list[str] | None = None
        self._date_start: str | None = None
        self._date_end: str | None = None
        self._symbols: list[str] | None = None

    def select(self, columns: list[str]) -> LazyDataset:
        """Restrict to given columns (projection pushdown).

        Args:
            columns: Column names to include.

        Returns:
            Self for method chaining.
        """
        self._columns = columns
        return self

    def filter_date(self, start: str, end: str) -> LazyDataset:
        """Filter rows to a date range.

        Predicate is pushed down to DuckDB so only matching rows are scanned.

        Args:
            start: Start date (inclusive), YYYY-MM-DD.
            end: End date (inclusive), YYYY-MM-DD.

        Returns:
            Self for method chaining.
        """
        self._date_start = start
        self._date_end = end
        return self

    def filter_symbols(self, symbols: list[str]) -> LazyDataset:
        """Filter rows to given symbols.

        Predicate is pushed down to DuckDB.

        Args:
            symbols: List of symbol strings.

        Returns:
            Self for method chaining.
        """
        self._symbols = symbols
        return self

    def _build_query(self) -> str:
        """Build a DuckDB SQL query from the configured filters."""
        cols = "*" if self._columns is None else ", ".join(self._columns)
        query = f"SELECT {cols} FROM read_parquet('{self._parquet_path}/*.parquet')"

        filters: list[str] = []
        if self._date_start is not None and self._date_end is not None:
            filters.append(
                f"date BETWEEN '{self._date_start}' AND '{self._date_end}'"
            )
        if self._symbols:
            quoted = ", ".join(f"'{s}'" for s in self._symbols)
            filters.append(f"symbol IN ({quoted})")

        if filters:
            query += " WHERE " + " AND ".join(filters)

        return query

    def collect(self) -> "pd.DataFrame":
        """Materialise the dataset into a pandas DataFrame.

        Returns:
            DataFrame with the selected columns and filtered rows.
        """
        import pandas as pd

        try:
            import duckdb
        except ImportError:
            # Fallback: glob and concatenate manually (no predicate pushdown)
            return self._fallback_collect()

        conn = duckdb.connect()
        try:
            query = self._build_query()
            return conn.execute(query).fetchdf()
        finally:
            conn.close()

    def _fallback_collect(self) -> "pd.DataFrame":
        """Fallback when DuckDB is not installed -- glob + pandas concat."""
        import pandas as pd

        frames: list[pd.DataFrame] = []
        path = Path(self._parquet_path)
        for p in sorted(path.rglob("*.parquet")):
            df = pd.read_parquet(p)
            if self._columns:
                existing = [c for c in self._columns if c in df.columns]
                if existing:
                    df = df[existing]
                else:
                    continue
            frames.append(df)

        if not frames:
            return pd.DataFrame()

        combined = pd.concat(frames, ignore_index=True)

        if self._date_start is not None and self._date_end is not None:
            combined = combined[
                (combined["date"] >= self._date_start)
                & (combined["date"] <= self._date_end)
            ]
        if self._symbols:
            combined = combined[combined["symbol"].isin(self._symbols)]

        return combined

    def stats(self) -> dict[str, Any]:
        """Return summary statistics about the dataset.

        Returns:
            Dict with row_count, columns, date range, symbol_count.
        """
        try:
            import duckdb

            conn = duckdb.connect()
            try:
                base = f"read_parquet('{self._parquet_path}/*.parquet')"
                row_count = conn.execute(
                    f"SELECT count(*) FROM {base}"
                ).fetchone()[0]
                cols = [
                    r[0]
                    for r in conn.execute(
                        f"SELECT column_name FROM (DESCRIBE SELECT * FROM {base})"
                    ).fetchall()
                ]
                date_min = conn.execute(
                    f"SELECT min(date) FROM {base}"
                ).fetchone()[0]
                date_max = conn.execute(
                    f"SELECT max(date) FROM {base}"
                ).fetchone()[0]
                sym_count = conn.execute(
                    f"SELECT count(DISTINCT symbol) FROM {base}"
                ).fetchone()[0]
                return {
                    "row_count": row_count,
                    "columns": cols,
                    "date_min": str(date_min) if date_min else "",
                    "date_max": str(date_max) if date_max else "",
                    "symbol_count": sym_count,
                }
            finally:
                conn.close()
        except ImportError:
            # Fallback: scan files manually
            import pandas as pd

            frames: list[pd.DataFrame] = []
            for p in Path(self._parquet_path).rglob("*.parquet"):
                frames.append(pd.read_parquet(p, columns=["date", "symbol"]))
            if not frames:
                return {}
            combined = pd.concat(frames, ignore_index=True)
            return {
                "row_count": len(combined),
                "columns": sorted(combined.columns.tolist()),
                "date_min": str(combined["date"].min()),
                "date_max": str(combined["date"].max()),
                "symbol_count": combined["symbol"].nunique(),
            }
        except Exception:
            return {}
