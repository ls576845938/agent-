from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

import pandas as pd

from quant_us.backtest.engine import BacktestBroker, BacktestConfig, BacktestResult, EventDrivenBacktestEngine
from quant_us.core.calendar import USEquityCalendar
from quant_us.core.enums import SignalDirection
from quant_us.core.events import MarketEvent
from quant_us.core.types import Bar, Signal
from quant_us.data.storage.data_manifest import DataManifest, DataManifestStore
from quant_us.strategies.base import Strategy, StrategyContext


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


class SignalReplayStrategy(Strategy):
    """Replay precomputed target signals through the event-driven engine."""

    version = "signal_replay_v1"

    def __init__(
        self,
        strategy_id: str,
        signal: pd.Series,
        horizon: str = "replay",
        params: dict | None = None,
        emit_on_change_only: bool = False,
    ) -> None:
        self.strategy_id = strategy_id
        self.horizon = horizon
        self.params = dict(params or {})
        self.emit_on_change_only = bool(emit_on_change_only)
        self._last_emitted_signal: float | None = None
        normalized = signal.fillna(0.0).clip(-1.0, 1.0).copy()
        normalized.index = pd.to_datetime(normalized.index, utc=True)
        self._signals = {
            pd.Timestamp(timestamp).to_pydatetime(): float(value)
            for timestamp, value in normalized.items()
        }

    def on_bar(self, event: MarketEvent, context: StrategyContext):
        raw_signal = float(self._signals.get(pd.Timestamp(event.timestamp_utc).to_pydatetime(), 0.0))
        if self.emit_on_change_only and self._last_emitted_signal is not None and raw_signal == self._last_emitted_signal:
            return []
        self._last_emitted_signal = raw_signal
        if raw_signal > 0:
            direction = SignalDirection.LONG
            strength = min(1.0, abs(raw_signal))
        elif raw_signal < 0:
            direction = SignalDirection.SHORT
            strength = min(1.0, abs(raw_signal))
        else:
            direction = SignalDirection.FLAT
            strength = 1.0

        return [
            Signal(
                timestamp_utc=event.timestamp_utc,
                strategy_id=self.strategy_id,
                symbol=event.bar.symbol,
                direction=direction,
                strength=strength,
                horizon=self.horizon,
                reason="signal_replay",
                metadata={"raw_signal": raw_signal, "emit_on_change_only": self.emit_on_change_only},
            )
        ]


@dataclass
class EventDrivenBacktestRunner:
    strategies: list[Strategy]
    config: BacktestConfig = field(default_factory=BacktestConfig)
    calendar: USEquityCalendar = field(default_factory=USEquityCalendar)
    manifest_store: DataManifestStore | None = None
    broker_factory: Callable[[BacktestConfig], BacktestBroker] | None = None

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
            broker=self._build_broker(),
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
            broker=self._build_broker(),
        )
        return engine.run(bars)

    def connection_health(self) -> dict[str, object]:
        broker = self._build_broker()
        if broker is None:
            return {
                "status": "ok",
                "broker": "SimulatedBroker(default)",
                "market_prices": 0,
            }
        return {
            "status": "ok",
            "broker": getattr(broker, "broker_name", broker.__class__.__name__),
            "market_prices": len(getattr(broker, "market_prices", {})),
        }

    def _build_broker(self) -> BacktestBroker | None:
        if self.broker_factory is None:
            return None
        return self.broker_factory(self.config)

    def _attach_manifest(self, result: BacktestResult) -> None:
        store = self.manifest_store or DataManifestStore()
        manifests = store.list_manifests()
        if manifests:
            latest = manifests[-1]
            result.metadata["data_version"] = latest.data_version
            result.metadata["data_fingerprint"] = latest.fingerprint
            result.metadata["data_manifest_id"] = latest.manifest_id
