from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd

from quant_us.core.clock import ensure_utc


@dataclass(frozen=True)
class DuckDBQuery:
    vendor: str
    asset_class: str
    bar_size: str
    symbol: str
    start: datetime | None = None
    end: datetime | None = None


class DuckDBBarReader:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def query_bars(self, query: DuckDBQuery) -> pd.DataFrame:
        try:
            import duckdb
        except ImportError as exc:
            raise RuntimeError("duckdb is required for DuckDBBarReader") from exc

        glob_path = (
            self.root
            / f"vendor={query.vendor}"
            / f"asset_class={query.asset_class}"
            / f"bar_size={query.bar_size}"
            / f"symbol={query.symbol.upper()}"
            / "date=*.parquet"
        )
        sql = "select * from read_parquet(?)"
        params: list[object] = [str(glob_path)]
        predicates: list[str] = []
        if query.start is not None:
            predicates.append("timestamp_utc >= ?")
            params.append(ensure_utc(query.start))
        if query.end is not None:
            predicates.append("timestamp_utc <= ?")
            params.append(ensure_utc(query.end))
        if predicates:
            sql += " where " + " and ".join(predicates)
        sql += " order by timestamp_utc"
        return duckdb.execute(sql, params).df()
