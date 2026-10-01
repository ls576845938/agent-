from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from datetime import date, datetime
from enum import Enum
import json
from pathlib import Path
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class BacktestPersistResult:
    run_id: str
    root_path: str
    summary_path: str
    metadata_path: str
    orders_path: str
    fills_path: str
    snapshots_path: str


class BacktestResultStore:
    def __init__(self, root: str | Path = "data/backtest_results") -> None:
        self.root = Path(root)

    def write(self, result: Any) -> BacktestPersistResult:
        base = self.root / f"run_id={result.run_id}"
        base.mkdir(parents=True, exist_ok=True)
        summary_path = base / "summary.json"
        metadata_path = base / "metadata.json"
        orders_path = base / "orders.parquet"
        fills_path = base / "fills.parquet"
        snapshots_path = base / "portfolio_snapshots.parquet"

        summary_path.write_text(json.dumps(_to_jsonable(result.summary), indent=2, sort_keys=True), encoding="utf-8")
        metadata_path.write_text(json.dumps(_to_jsonable(result.metadata), indent=2, sort_keys=True), encoding="utf-8")
        _records_to_frame(result.orders).to_parquet(orders_path, index=False)
        _records_to_frame(result.fills).to_parquet(fills_path, index=False)
        _records_to_frame(result.snapshots).to_parquet(snapshots_path, index=False)

        return BacktestPersistResult(
            run_id=result.run_id,
            root_path=str(base),
            summary_path=str(summary_path),
            metadata_path=str(metadata_path),
            orders_path=str(orders_path),
            fills_path=str(fills_path),
            snapshots_path=str(snapshots_path),
        )


def _records_to_frame(records: list[Any]) -> pd.DataFrame:
    if not records:
        return pd.DataFrame()
    return pd.DataFrame([_to_jsonable(record) for record in records])


def _to_jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return _to_jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(key): _to_jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple | set):
        return [_to_jsonable(item) for item in value]
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    return value
