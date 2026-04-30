from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd

from quant_us.core.clock import utc_now
from quant_us.core.types import new_id
from quant_us.data.storage.feature_store import ParquetFeatureStore
from quant_us.factors.liquidity import average_dollar_volume
from quant_us.factors.momentum import rolling_momentum_score
from quant_us.factors.volatility import realized_volatility


@dataclass(frozen=True)
class FeatureBuildResult:
    run_id: str
    status: str
    rows_written: int
    files_written: list[str]
    version: str
    created_at: datetime
    error: str | None = None


class FeaturePipeline:
    def __init__(self, feature_root: str | Path = "data/features") -> None:
        self.store = ParquetFeatureStore(feature_root)

    def build_bar_factors(
        self,
        bars: pd.DataFrame,
        universe: str = "default",
        version: str = "v1",
    ) -> FeatureBuildResult:
        created_at = utc_now()
        try:
            values: list[dict[str, object]] = []
            if bars.empty:
                return FeatureBuildResult(new_id("feat"), "completed", 0, [], version, created_at)
            working = bars.copy()
            working["timestamp_utc"] = pd.to_datetime(working["timestamp_utc"], utc=True)
            for symbol, group in working.sort_values("timestamp_utc").groupby("symbol"):
                close = group["close"].astype(float)
                volume = group["volume"].astype(float)
                factors = {
                    "momentum_score": rolling_momentum_score(close, short_window=20, long_window=60),
                    "realized_vol_20": realized_volatility(close, window=20),
                    "average_dollar_volume_20": average_dollar_volume(close, volume, window=20),
                }
                dates = group["timestamp_utc"].dt.date
                for factor_name, series in factors.items():
                    for date_value, value in zip(dates, series):
                        if pd.isna(value):
                            continue
                        values.append(
                            {
                                "date": date_value,
                                "symbol": symbol,
                                "factor_name": factor_name,
                                "factor_value": float(value),
                                "universe": universe,
                                "version": version,
                                "created_at": created_at,
                            }
                        )
            frame = pd.DataFrame(values)
            write = self.store.write_factor_values(frame, version=version)
            return FeatureBuildResult(
                run_id=new_id("feat"),
                status="completed",
                rows_written=write.rows_written,
                files_written=[str(path) for path in write.files_written],
                version=version,
                created_at=created_at,
            )
        except Exception as exc:
            return FeatureBuildResult(new_id("feat"), "failed", 0, [], version, created_at, error=str(exc))
