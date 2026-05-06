"""Polling-based market data loop for paper trading.

Continuously fetches the latest bars from a data vendor, validates freshness,
and caches them for downstream consumption.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from threading import Event
from typing import Any

import pandas as pd

from quant_us.core.clock import ensure_utc, utc_now
from quant_us.data.connectors.factory import get_connector
from quant_us.data.storage.parquet_store import ParquetBarStore


@dataclass
class MarketDataStatus:
    """Result of a single market data poll cycle."""

    fresh: bool
    stale_seconds: float
    latest_timestamp: datetime | None
    symbols_updated: list[str]
    error: str | None = None


_BAR_SIZE_MINUTES: dict[str, int] = {
    "1m": 1,
    "2m": 2,
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "60m": 60,
    "1h": 60,
    "1d": 1440,
    "1wk": 10080,
}


class MarketDataLoop:
    """Continuously polls market data and caches it.

    Parameters
    ----------
    symbols : list[str]
        List of ticker symbols to track.
    vendor : str
        Data vendor name (e.g., ``"yfinance"``, ``"alpaca"``).
    bar_size : str
        Bar interval string (e.g., ``"1m"``, ``"5m"``, ``"1d"``).
    poll_interval_seconds : float
        Seconds between poll cycles.
    data_root : str | Path
        Root path for cached data. Bars are written under
        ``<data_root>/latest/``.
    connector_kwargs : dict | None
        Extra keyword arguments forwarded to the connector constructor.
    """

    def __init__(
        self,
        symbols: list[str],
        vendor: str,
        bar_size: str,
        poll_interval_seconds: float = 60.0,
        data_root: str | Path = "data",
        connector_kwargs: dict[str, Any] | None = None,
    ) -> None:
        self.symbols = [s.upper() for s in symbols]
        self.vendor = vendor
        self.bar_size = bar_size
        self.poll_interval_seconds = poll_interval_seconds
        self.data_root = Path(data_root)
        self._logger = logging.getLogger("market_data_loop")

        self._connector = get_connector(vendor, **(connector_kwargs or {}))
        self._store = ParquetBarStore(str(self.data_root / "latest"))
        self._stop_event = Event()
        self._last_status: MarketDataStatus | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fetch_latest_bars(self) -> pd.DataFrame:
        """Fetch the most recent bars for all tracked symbols.

        Returns a concatenated DataFrame with connector-native columns.
        Returns an empty DataFrame on complete failure.
        """
        lookback = self._compute_lookback()
        end = utc_now()
        start = end - lookback

        parts: list[pd.DataFrame] = []
        for symbol in self.symbols:
            try:
                frame = self._connector.fetch_bars(symbol, start, end, self.bar_size)
                if not frame.empty:
                    parts.append(frame)
            except Exception:
                self._logger.exception("Failed to fetch bars for %s", symbol)

        if not parts:
            return pd.DataFrame()
        return pd.concat(parts, ignore_index=True)

    def validate_freshness(self, bars: pd.DataFrame) -> MarketDataStatus:
        """Check bar timestamps against current time.

        Parameters
        ----------
        bars : pd.DataFrame
            Bars DataFrame with ``timestamp_utc`` and ``symbol`` columns.

        Returns
        -------
        MarketDataStatus
        """
        if bars.empty:
            return MarketDataStatus(
                fresh=False,
                stale_seconds=float("inf"),
                latest_timestamp=None,
                symbols_updated=[],
                error="no_data",
            )

        now = utc_now()
        symbols_updated = sorted(bars["symbol"].unique().tolist())
        latest_ts = pd.to_datetime(bars["timestamp_utc"].max()).to_pydatetime()
        latest_ts = ensure_utc(latest_ts)

        delay = max(0.0, (now - latest_ts).total_seconds())
        max_acceptable = self._compute_max_delay()
        fresh = delay <= max_acceptable

        return MarketDataStatus(
            fresh=fresh,
            stale_seconds=delay if not fresh else 0.0,
            latest_timestamp=latest_ts,
            symbols_updated=symbols_updated,
        )

    def write_to_cache(self, bars: pd.DataFrame) -> None:
        """Write bars to the latest-data parquet cache.

        Parameters
        ----------
        bars : pd.DataFrame
            Bars DataFrame with the columns expected by
            :class:`~quant_us.data.storage.parquet_store.ParquetBarStore`.
        """
        if bars.empty:
            return

        for symbol in bars["symbol"].unique():
            subset = bars[bars["symbol"] == symbol]
            self._store.write_bars(
                frame=subset,
                vendor=self.vendor,
                asset_class="equity",
                bar_size=self.bar_size,
                symbol=symbol,
            )

    def run_once(self) -> MarketDataStatus:
        """Execute a single poll-fetch -> validate -> write cycle.

        Returns
        -------
        MarketDataStatus
        """
        try:
            bars = self.fetch_latest_bars()
        except Exception as exc:
            status = MarketDataStatus(
                fresh=False,
                stale_seconds=float("inf"),
                latest_timestamp=None,
                symbols_updated=[],
                error=str(exc),
            )
            self._last_status = status
            return status

        status = self.validate_freshness(bars)
        if status.fresh:
            self.write_to_cache(bars)

        self._last_status = status
        return status

    def start(self) -> None:
        """Run the poll loop indefinitely (blocking).

        Call :meth:`stop` from another thread to terminate gracefully.
        """
        self._logger.info(
            "MarketDataLoop started: symbols=%s vendor=%s bar_size=%s interval=%.0fs",
            self.symbols,
            self.vendor,
            self.bar_size,
            self.poll_interval_seconds,
        )
        self._stop_event.clear()

        while not self._stop_event.is_set():
            status = self.run_once()
            if not status.fresh and status.error:
                self._logger.warning(
                    "Market data poll: fresh=%s stale_seconds=%.0f error=%s",
                    status.fresh,
                    status.stale_seconds,
                    status.error,
                )
            elif not status.fresh:
                self._logger.info(
                    "Market data stale: %.0fs behind latest bar",
                    status.stale_seconds,
                )
            self._stop_event.wait(self.poll_interval_seconds)

        self._logger.info("MarketDataLoop stopped.")

    def stop(self) -> None:
        """Signal the poll loop to stop gracefully."""
        self._stop_event.set()

    @property
    def last_status(self) -> MarketDataStatus | None:
        """Return the status from the most recent poll cycle."""
        return self._last_status

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _compute_lookback(self) -> timedelta:
        """Compute a lookback duration that covers at least two poll cycles."""
        minutes = self._parse_bar_size_minutes()
        if minutes >= 1440:
            return timedelta(days=7)
        bar_seconds = minutes * 60
        return timedelta(seconds=max(bar_seconds * 3, int(self.poll_interval_seconds * 3)))

    def _compute_max_delay(self) -> float:
        """Return the maximum acceptable delay in seconds for a bar.

        Uses twice the poll interval as the primary bound, with a floor
        of twice the bar duration.
        """
        minutes = self._parse_bar_size_minutes()
        return max(self.poll_interval_seconds * 2, minutes * 60 * 2)

    def _parse_bar_size_minutes(self) -> int:
        return _BAR_SIZE_MINUTES.get(self.bar_size, 60)
