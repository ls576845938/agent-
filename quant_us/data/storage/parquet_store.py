from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd

from quant_us.core.clock import ensure_utc

_logger = logging.getLogger("parquet_store")


@dataclass(frozen=True)
class ParquetWriteResult:
    rows_written: int
    files_written: list[Path]


class ParquetBarStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def write_bars(
        self,
        frame: pd.DataFrame,
        vendor: str,
        asset_class: str,
        bar_size: str,
        symbol: str,
    ) -> ParquetWriteResult:
        if frame.empty:
            return ParquetWriteResult(0, [])

        working = frame.copy()
        working["timestamp_utc"] = pd.to_datetime(working["timestamp_utc"], utc=True)
        working["date"] = working["timestamp_utc"].dt.strftime("%Y-%m-%d")
        files_written: list[Path] = []
        rows_written = 0

        for date_value, group in working.groupby("date"):
            path = self._partition_path(vendor, asset_class, bar_size, symbol, str(date_value))
            path.parent.mkdir(parents=True, exist_ok=True)
            output = group.drop(columns=["date"]).copy()
            if path.exists():
                existing = pd.read_parquet(path)
                output = pd.concat([existing, output], ignore_index=True)
            output = output.drop_duplicates(subset=["timestamp_utc", "symbol"], keep="last").sort_values("timestamp_utc")
            output.to_parquet(path, index=False)
            rows_written += len(group)
            files_written.append(path)

        return ParquetWriteResult(rows_written=rows_written, files_written=files_written)

    def read_bars(
        self,
        vendor: str,
        asset_class: str,
        bar_size: str,
        symbol: str,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> pd.DataFrame:
        """Read bars from partitioned parquet files.

        When start/end filters are present, uses DuckDB for predicate pushdown
        to avoid loading all partitions into memory. Falls back to pandas
        eager-read when DuckDB is unavailable.
        """
        if start is not None or end is not None:
            try:
                return self._read_bars_lazy(
                    vendor=vendor,
                    asset_class=asset_class,
                    bar_size=bar_size,
                    symbol=symbol,
                    start=start,
                    end=end,
                )
            except Exception:
                _logger.debug("DuckDB lazy read failed, falling back to pandas eager path", exc_info=True)

        return self._read_bars_eager(
            vendor=vendor,
            asset_class=asset_class,
            bar_size=bar_size,
            symbol=symbol,
            start=start,
            end=end,
        )

    # ------------------------------------------------------------------
    # DuckDB lazy read with predicate pushdown
    # ------------------------------------------------------------------

    def _read_bars_lazy(
        self,
        vendor: str,
        asset_class: str,
        bar_size: str,
        symbol: str,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> pd.DataFrame:
        import duckdb

        base = self.root / f"vendor={vendor}" / f"asset_class={asset_class}" / f"bar_size={bar_size}" / f"symbol={symbol.upper()}"
        if not base.exists():
            return pd.DataFrame()

        glob_pattern = str(base / "date=*.parquet")
        where_clauses = []
        params: list = []

        if start is not None:
            where_clauses.append("timestamp_utc >= ?")
            params.append(ensure_utc(start).isoformat())
        if end is not None:
            where_clauses.append("timestamp_utc <= ?")
            params.append(ensure_utc(end).isoformat())

        where = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
        sql = f"SELECT * FROM read_parquet('{glob_pattern}') {where} ORDER BY timestamp_utc"
        return duckdb.execute(sql, params).df()

    # ------------------------------------------------------------------
    # Eager pandas path (legacy, full-partition scan)
    # ------------------------------------------------------------------

    def _read_bars_eager(
        self,
        vendor: str,
        asset_class: str,
        bar_size: str,
        symbol: str,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> pd.DataFrame:
        base = self.root / f"vendor={vendor}" / f"asset_class={asset_class}" / f"bar_size={bar_size}" / f"symbol={symbol.upper()}"
        if not base.exists():
            return pd.DataFrame()

        parts = [pd.read_parquet(path) for path in sorted(base.glob("date=*.parquet"))]
        if not parts:
            return pd.DataFrame()

        frame = pd.concat(parts, ignore_index=True)
        frame["timestamp_utc"] = pd.to_datetime(frame["timestamp_utc"], utc=True)
        if start is not None:
            frame = frame[frame["timestamp_utc"] >= ensure_utc(start)]
        if end is not None:
            frame = frame[frame["timestamp_utc"] <= ensure_utc(end)]
        return frame.sort_values("timestamp_utc").reset_index(drop=True)

    def _partition_path(self, vendor: str, asset_class: str, bar_size: str, symbol: str, date_value: str) -> Path:
        return (
            self.root
            / f"vendor={vendor}"
            / f"asset_class={asset_class}"
            / f"bar_size={bar_size}"
            / f"symbol={symbol.upper()}"
            / f"date={date_value}.parquet"
        )
