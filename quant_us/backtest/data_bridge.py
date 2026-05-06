from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from quant_us.backtest.engine import BacktestConfig, BacktestResult, EventDrivenBacktestEngine
from quant_us.core.calendar import USEquityCalendar
from quant_us.core.types import Bar
from quant_us.data.storage.data_manifest import DataManifest, DataManifestStore
from quant_us.strategies.base import Strategy


def bars_from_dataframe(
    frame: pd.DataFrame,
    source: str = "",
    session: str = "regular",
) -> list[Bar]:
    """Convert a cleaned DataFrame to Bar objects for the event-driven engine."""
    data = frame.copy()
    if data.index.name in (None, ""):
        ts_col = "timestamp_utc" if "timestamp_utc" in data.columns else "timestamp"
        data[ts_col] = pd.to_datetime(data[ts_col], utc=True)
        data = data.set_index(ts_col)

    bars: list[Bar] = []
    for idx, row in data.iterrows():
        ts = idx.to_pydatetime()
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        bars.append(
            Bar(
                timestamp_utc=ts,
                symbol=str(row.get("symbol", "")),
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row.get("volume", 0)),
                vwap=float(row["vwap"]) if "vwap" in row and not pd.isna(row["vwap"]) else None,
                trade_count=int(row["trade_count"]) if "trade_count" in row and not pd.isna(row.get("trade_count")) else None,
                source=source,
                session=session,
                adjusted=bool(row.get("adjusted_flag", False)),
            )
        )
    return bars


def feature_map_from_frame(
    frame: pd.DataFrame,
) -> dict[datetime, dict[str, dict[str, float]]]:
    """Build feature map from factor values DataFrame for event-driven engine.

    Expects columns: date, symbol, factor_name, factor_value
    """
    from quant_us.backtest.features import feature_map_from_frame as _ff

    raw = _ff(frame)
    return {datetime.combine(d, datetime.min.time()): v for d, v in raw.items()}


@dataclass
class EventDrivenBacktestRunner:
    strategies: list[Strategy]
    config: BacktestConfig = field(default_factory=BacktestConfig)
    calendar: USEquityCalendar = field(default_factory=USEquityCalendar)
    manifest_store: DataManifestStore | None = None

    def run_from_dataframe(
        self,
        frame: pd.DataFrame,
        features_frame: pd.DataFrame | None = None,
        source: str = "",
        session: str = "regular",
    ) -> BacktestResult:
        bars = bars_from_dataframe(frame, source=source, session=session)

        features_by_date = {}
        if features_frame is not None and not features_frame.empty:
            features_by_date = feature_map_from_frame(features_frame)

        engine = EventDrivenBacktestEngine(
            strategies=self.strategies,
            config=self.config,
            calendar=self.calendar,
            features_by_date=features_by_date,
        )
        result = engine.run(bars)

        if self.manifest_store is not None:
            self._attach_manifest(result)

        return result

    def run_from_dataframe_multi_symbol(
        self,
        frame: pd.DataFrame,
        features_frame: pd.DataFrame | None = None,
        source: str = "",
        session: str = "regular",
    ) -> BacktestResult:
        bars = bars_from_dataframe(frame, source=source, session=session)

        features_by_date = {}
        if features_frame is not None and not features_frame.empty:
            features_by_date = feature_map_from_frame(features_frame)

        engine = EventDrivenBacktestEngine(
            strategies=self.strategies,
            config=self.config,
            calendar=self.calendar,
            features_by_date=features_by_date,
        )
        return engine.run(bars)

    def _attach_manifest(self, result: BacktestResult) -> None:
        store = self.manifest_store or DataManifestStore()
        manifests = store.list_manifests()
        if manifests:
            latest = manifests[-1]
            result.metadata["data_version"] = latest.data_version
            result.metadata["data_fingerprint"] = latest.fingerprint
            result.metadata["data_manifest_id"] = latest.manifest_id
