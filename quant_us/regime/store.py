"""Persistent storage for regime-detection results.

Stores regime records as parquet with features serialised as JSON.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd


@dataclass
class RegimeRecord:
    """A single regime classification record ready for persistence."""

    date: str
    symbol: str
    regime: str
    confidence: float
    features: dict[str, float] = field(default_factory=dict)
    version: str = "1.0"


class RegimeFeatureStore:
    """Parquet-backed store for regime detection outputs.

    Data is written to ``{data_root}/regime/regime_records.parquet``.

    Because parquet does not natively support dict columns, features are
    serialised as a JSON string column (``features_json``) and deserialised
    on read.
    """

    def __init__(self, data_root: str = "data") -> None:
        self.root = Path(data_root) / "regime"

    def save(self, records: list[RegimeRecord]) -> str:
        """Persist a list of regime records to parquet.

        Returns
        -------
        str
            Absolute path of the written parquet file.
        """
        rows: list[dict[str, Any]] = []
        for r in records:
            row = asdict(r)
            features_json = json.dumps(row.pop("features"), sort_keys=True)
            row["features_json"] = features_json
            rows.append(row)

        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / "regime_records.parquet"

        df = pd.DataFrame(rows)
        df.to_parquet(path, index=False)
        return str(path.resolve())

    def load(
        self,
        symbol: str,
        start: str = "",
        end: str = "",
    ) -> pd.DataFrame:
        """Load regime records for a given symbol and date range.

        Parameters
        ----------
        symbol : str
            Ticker symbol.
        start : str, optional
            Inclusive start date (ISO format).
        end : str, optional
            Inclusive end date (ISO format).

        Returns
        -------
        pd.DataFrame
            Sorted by date. The ``features_json`` column is deserialised
            into a ``features`` dict column.
        """
        path = self.root / "regime_records.parquet"
        if not path.exists():
            return pd.DataFrame()

        df = pd.read_parquet(str(path))
        mask = df["symbol"] == symbol
        if start:
            mask &= df["date"] >= start
        if end:
            mask &= df["date"] <= end

        result = df[mask].sort_values("date").reset_index(drop=True)
        if not result.empty and "features_json" in result.columns:
            result["features"] = result["features_json"].apply(
                lambda x: json.loads(x) if isinstance(x, str) else {}
            )
            result = result.drop(columns=["features_json"])
        return result

    def get_regime_history(self, symbol: str) -> list[dict[str, Any]]:
        """Return the full regime history for *symbol* as a list of dicts.

        Each dict contains the columns from the parquet file with ``features``
        deserialised.
        """
        df = self.load(symbol)
        if df.empty:
            return []
        return df.to_dict(orient="records")
