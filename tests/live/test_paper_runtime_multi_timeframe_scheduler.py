from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pandas as pd

from quant_us.core.enums import SignalDirection
from quant_us.core.events import MarketEvent
from quant_us.core.types import Bar, Signal
from quant_us.live.market_data_loop import MarketDataStatus
from quant_us.live.multi_timeframe_scheduler import MultiTimeframeDataStatus
from quant_us.live.paper_runtime import PaperRuntime, PaperRuntimeConfig, PaperSessionMetrics
from quant_us.strategies.base import Strategy, StrategyContext
from quant_us.strategies.composite import CompositeStrategy, StrategySpec


UTC = timezone.utc


@dataclass
class TrackingStrategy(Strategy):
    strategy_id: str
    calls: list[dict[str, Any]] = field(default_factory=list)

    def on_bar(self, event: MarketEvent, context: StrategyContext):
        self.calls.append(
            {
                "bar_size": event.bar.bar_size,
                "timestamp": event.timestamp_utc,
                "market_price": context.market_prices.get(event.bar.symbol),
                "strategy_timeframe": context.parameters.get("strategy_timeframe"),
            }
        )
        return [
            Signal(
                timestamp_utc=event.timestamp_utc,
                strategy_id=self.strategy_id,
                symbol=event.bar.symbol,
                direction=SignalDirection.LONG,
                strength=1.0,
                horizon=event.bar.bar_size,
            )
        ]


def _runtime(tmp_path: Path, strategy: Strategy) -> PaperRuntime:
    runtime = PaperRuntime(
        PaperRuntimeConfig(
            symbols=["SPY"],
            strategy_id="portfolio",
            ledger_root=str(tmp_path / "ledger"),
            reconcile_on_start=False,
            reconcile_on_close=False,
            submit_orders=False,
            poll_interval_seconds=0.01,
            strategy_weights=getattr(strategy, "strategy_weights", {}),
        )
    )
    runtime.bootstrap(strategy=strategy)
    runtime.data_freshness.evaluate_bar = lambda bar, now=None: type(  # type: ignore[method-assign]
        "Freshness",
        (),
        {"fresh": True, "delay_seconds": 0.0, "stale_seconds": 0.0, "reason": "fresh"},
    )()
    return runtime


def _bar(timestamp: datetime, close: float, bar_size: str) -> Bar:
    return Bar(
        timestamp_utc=timestamp,
        symbol="SPY",
        open=close,
        high=close,
        low=close,
        close=close,
        volume=100_000.0,
        source="test",
        bar_size=bar_size,
    )


def _frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "timestamp_utc": datetime(2026, 5, 11, 14, 35, tzinfo=UTC),
                "symbol": "SPY",
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.5,
                "volume": 100_000.0,
                "bar_size": "1m",
            },
            {
                "timestamp_utc": datetime(2026, 5, 11, 14, 35, tzinfo=UTC),
                "symbol": "SPY",
                "open": 101.0,
                "high": 102.0,
                "low": 100.0,
                "close": 101.5,
                "volume": 100_000.0,
                "bar_size": "5m",
            },
        ]
    )


class FakeDataLoop:
    def __init__(self, frame: pd.DataFrame, status: MultiTimeframeDataStatus) -> None:
        self._frame = frame
        self._last_status = status

    def fetch_latest_bars(self) -> pd.DataFrame:
        return self._frame

    @property
    def last_status(self) -> MultiTimeframeDataStatus:
        return self._last_status


def _status(*, stale_15m: bool = False) -> MultiTimeframeDataStatus:
    statuses = {
        "1m": MarketDataStatus(
            fresh=True,
            stale_seconds=0.0,
            latest_timestamp=datetime(2026, 5, 11, 14, 35, tzinfo=UTC),
            symbols_updated=["SPY"],
        ),
        "5m": MarketDataStatus(
            fresh=True,
            stale_seconds=0.0,
            latest_timestamp=datetime(2026, 5, 11, 14, 35, tzinfo=UTC),
            symbols_updated=["SPY"],
        ),
        "15m": MarketDataStatus(
            fresh=not stale_15m,
            stale_seconds=900.0 if stale_15m else 0.0,
            latest_timestamp=datetime(2026, 5, 11, 14, 30, tzinfo=UTC),
            symbols_updated=["SPY"],
            error="stale" if stale_15m else None,
        ),
    }
    return MultiTimeframeDataStatus(
        fresh=True,
        stale_seconds=900.0 if stale_15m else 0.0,
        latest_timestamp=datetime(2026, 5, 11, 14, 35, tzinfo=UTC),
        symbols_updated=["SPY"],
        timeframe_statuses=statuses,
    )


@patch("quant_us.live.market_data_loop.get_connector")
def test_paper_runtime_routes_bars_by_strategy_timeframe(_mock_connector: object, tmp_path: Path) -> None:
    s1 = TrackingStrategy("s_1m")
    s5 = TrackingStrategy("s_5m")
    s15 = TrackingStrategy("s_15m")
    strategy = CompositeStrategy(
        strategies=[s1, s5, s15],
        specs=[
            StrategySpec("s_1m", weight=0.4, timeframe="1m"),
            StrategySpec("s_5m", weight=0.3, timeframe="5m"),
            StrategySpec("s_15m", weight=0.3, timeframe="15m"),
        ],
    )
    runtime = _runtime(tmp_path, strategy)
    manifest = json.loads(
        (tmp_path / "ledger" / "audit" / "paper_session_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["market_data_symbols_evidence"]["timeframes"] == ["1m", "5m", "15m"]
    assert manifest["bar_sizes"] == ["1m", "5m", "15m"]

    metrics = PaperSessionMetrics()
    runtime._process_bars(
        [
            _bar(datetime(2026, 5, 11, 14, 31, tzinfo=UTC), 101.0, "1m"),
            _bar(datetime(2026, 5, 11, 14, 35, tzinfo=UTC), 105.0, "5m"),
            _bar(datetime(2026, 5, 11, 14, 45, tzinfo=UTC), 115.0, "15m"),
        ],
        metrics,
    )

    assert [call["bar_size"] for call in s1.calls] == ["1m"]
    assert [call["bar_size"] for call in s5.calls] == ["5m"]
    assert [call["bar_size"] for call in s15.calls] == ["15m"]


@patch("quant_us.live.market_data_loop.get_connector")
def test_paper_runtime_processes_bars_asof_without_lookahead(
    _mock_connector: object,
    tmp_path: Path,
) -> None:
    s1 = TrackingStrategy("s_1m")
    s5 = TrackingStrategy("s_5m")
    strategy = CompositeStrategy(
        strategies=[s1, s5],
        specs=[
            StrategySpec("s_1m", weight=0.5, timeframe="1m"),
            StrategySpec("s_5m", weight=0.5, timeframe="5m"),
        ],
    )
    runtime = _runtime(tmp_path, strategy)

    metrics = PaperSessionMetrics()
    runtime._process_bars(
        [
            _bar(datetime(2026, 5, 11, 14, 31, tzinfo=UTC), 101.0, "1m"),
            _bar(datetime(2026, 5, 11, 14, 35, tzinfo=UTC), 105.0, "5m"),
        ],
        metrics,
    )

    assert s1.calls[0]["market_price"] == 101.0
    assert s5.calls[0]["market_price"] == 105.0


@patch("quant_us.live.market_data_loop.get_connector")
def test_paper_runtime_filters_stale_timeframe_bars_before_processing(
    _mock_connector: object,
    tmp_path: Path,
) -> None:
    strategy = CompositeStrategy(
        strategies=[TrackingStrategy("s_1m"), TrackingStrategy("s_15m")],
        specs=[
            StrategySpec("s_1m", weight=0.5, timeframe="1m"),
            StrategySpec("s_15m", weight=0.5, timeframe="15m"),
        ],
    )
    runtime = _runtime(tmp_path, strategy)
    frame = pd.DataFrame(
        [
            {**row, "bar_size": "15m"} if index == 1 else row
            for index, row in enumerate(_frame().to_dict("records"))
        ]
    )
    runtime.data_loop = FakeDataLoop(frame, _status(stale_15m=True))  # type: ignore[assignment]

    bars = runtime._new_bars_from_cache()

    assert [bar.bar_size for bar in bars] == ["1m"]


@patch("quant_us.live.market_data_loop.get_connector")
def test_paper_runtime_persists_timeframe_watermarks_across_restart(
    _mock_connector: object,
    tmp_path: Path,
) -> None:
    strategy = CompositeStrategy(
        strategies=[TrackingStrategy("s_1m"), TrackingStrategy("s_5m")],
        specs=[
            StrategySpec("s_1m", weight=0.5, timeframe="1m"),
            StrategySpec("s_5m", weight=0.5, timeframe="5m"),
        ],
    )
    runtime = _runtime(tmp_path, strategy)
    runtime.data_loop = FakeDataLoop(_frame(), _status())  # type: ignore[assignment]
    bars = runtime._new_bars_from_cache()
    assert [bar.bar_size for bar in bars] == ["1m", "5m"]
    runtime._process_bars(bars, PaperSessionMetrics())

    restarted = _runtime(tmp_path, strategy)
    restarted.data_loop = FakeDataLoop(_frame(), _status())  # type: ignore[assignment]

    assert restarted._new_bars_from_cache() == []
