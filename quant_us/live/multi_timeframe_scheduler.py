"""Multi-timeframe market data scheduler for paper runtime."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from quant_us.live.market_data_loop import MarketDataLoop, MarketDataStatus

_logger = logging.getLogger("multi_timeframe_scheduler")


@dataclass(frozen=True)
class MultiTimeframeDataStatus:
    """Aggregated result of polling multiple bar sizes."""

    fresh: bool
    stale_seconds: float
    latest_timestamp: datetime | None
    symbols_updated: list[str]
    timeframe_statuses: dict[str, MarketDataStatus] = field(default_factory=dict)
    error: str | None = None

    @property
    def fresh_timeframes(self) -> list[str]:
        return sorted(
            timeframe
            for timeframe, status in self.timeframe_statuses.items()
            if status.fresh
        )

    @property
    def stale_timeframes(self) -> list[str]:
        return sorted(
            timeframe
            for timeframe, status in self.timeframe_statuses.items()
            if not status.fresh
        )

    @property
    def all_fresh(self) -> bool:
        return bool(self.timeframe_statuses) and not self.stale_timeframes


class MultiTimeframeMarketDataScheduler:
    """Run one ``MarketDataLoop`` per timeframe and aggregate statuses.

    The scheduler is paper-runtime only. It does not submit orders and only
    coordinates market-data polling across bar sizes.
    """

    def __init__(
        self,
        symbols: list[str],
        vendor: str,
        bar_sizes: list[str],
        poll_interval_seconds: float = 60.0,
        data_root: str | Path = "data",
        connector_kwargs: dict[str, Any] | None = None,
    ) -> None:
        normalized = _normalize_bar_sizes(bar_sizes)
        if not normalized:
            raise ValueError("At least one bar size is required")
        self.symbols = [symbol.upper() for symbol in symbols]
        self.vendor = vendor
        self.bar_sizes = normalized
        self.poll_interval_seconds = poll_interval_seconds
        self.data_root = Path(data_root)
        self.loops: dict[str, MarketDataLoop] = {
            bar_size: MarketDataLoop(
                symbols=self.symbols,
                vendor=self.vendor,
                bar_size=bar_size,
                poll_interval_seconds=self.poll_interval_seconds,
                data_root=self.data_root,
                connector_kwargs=connector_kwargs,
            )
            for bar_size in self.bar_sizes
        }
        self._last_status: MultiTimeframeDataStatus | None = None

    def run_once(self) -> MultiTimeframeDataStatus:
        """Poll every timeframe concurrently and return aggregate status."""
        statuses: dict[str, MarketDataStatus] = {}
        max_workers = max(1, len(self.loops))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(loop.run_once): bar_size
                for bar_size, loop in self.loops.items()
            }
            for future in as_completed(futures):
                bar_size = futures[future]
                try:
                    statuses[bar_size] = future.result()
                except Exception as exc:
                    _logger.exception("Multi-timeframe poll failed for %s", bar_size)
                    statuses[bar_size] = MarketDataStatus(
                        fresh=False,
                        stale_seconds=float("inf"),
                        latest_timestamp=None,
                        symbols_updated=[],
                        error=str(exc),
                    )

        status = _aggregate_status(statuses)
        self._last_status = status
        return status

    def fetch_latest_bars(self) -> pd.DataFrame:
        """Fetch latest bars for all timeframes and tag each row."""
        parts: list[pd.DataFrame] = []
        for bar_size, loop in self.loops.items():
            frame = loop.fetch_latest_bars()
            if frame.empty:
                continue
            frame = frame.copy()
            frame["bar_size"] = bar_size
            parts.append(frame)
        if not parts:
            return pd.DataFrame()
        return pd.concat(parts, ignore_index=True)

    @property
    def last_status(self) -> MultiTimeframeDataStatus | None:
        return self._last_status


def _aggregate_status(statuses: dict[str, MarketDataStatus]) -> MultiTimeframeDataStatus:
    fresh_statuses = [status for status in statuses.values() if status.fresh]
    stale_statuses = [status for status in statuses.values() if not status.fresh]
    latest_values = [status.latest_timestamp for status in statuses.values() if status.latest_timestamp is not None]
    symbols = sorted(
        {
            symbol
            for status in statuses.values()
            for symbol in status.symbols_updated
        }
    )
    error = "; ".join(
        f"{bar_size}:{status.error}"
        for bar_size, status in sorted(statuses.items())
        if status.error
    ) or None
    stale_seconds = max(
        [float(status.stale_seconds) for status in stale_statuses],
        default=0.0,
    )
    return MultiTimeframeDataStatus(
        fresh=bool(fresh_statuses),
        stale_seconds=stale_seconds,
        latest_timestamp=max(latest_values) if latest_values else None,
        symbols_updated=symbols,
        timeframe_statuses=dict(sorted(statuses.items())),
        error=error,
    )


def _normalize_bar_sizes(bar_sizes: list[str]) -> list[str]:
    seen: set[str] = set()
    normalized: list[str] = []
    for raw in bar_sizes:
        bar_size = str(raw or "").strip().lower()
        if not bar_size or bar_size in seen:
            continue
        seen.add(bar_size)
        normalized.append(bar_size)
    return normalized
