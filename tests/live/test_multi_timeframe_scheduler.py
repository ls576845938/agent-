from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from quant_us.live.market_data_loop import MarketDataStatus
from quant_us.live.multi_timeframe_scheduler import MultiTimeframeMarketDataScheduler


UTC = timezone.utc


@patch("quant_us.live.multi_timeframe_scheduler.MarketDataLoop")
def test_multi_timeframe_scheduler_reports_fresh_and_stale_timeframes(mock_loop_cls: MagicMock) -> None:
    loops = {
        "1m": MagicMock(),
        "5m": MagicMock(),
        "15m": MagicMock(),
    }

    def loop_factory(*, bar_size: str, **kwargs):
        return loops[bar_size]

    mock_loop_cls.side_effect = loop_factory
    loops["1m"].run_once.return_value = MarketDataStatus(
        fresh=True,
        stale_seconds=0.0,
        latest_timestamp=datetime(2026, 5, 11, 14, 31, tzinfo=UTC),
        symbols_updated=["SPY"],
    )
    loops["5m"].run_once.return_value = MarketDataStatus(
        fresh=True,
        stale_seconds=0.0,
        latest_timestamp=datetime(2026, 5, 11, 14, 35, tzinfo=UTC),
        symbols_updated=["SPY"],
    )
    loops["15m"].run_once.return_value = MarketDataStatus(
        fresh=False,
        stale_seconds=900.0,
        latest_timestamp=datetime(2026, 5, 11, 14, 15, tzinfo=UTC),
        symbols_updated=["SPY"],
        error="stale",
    )

    scheduler = MultiTimeframeMarketDataScheduler(
        symbols=["SPY"],
        vendor="test",
        bar_sizes=["1m", "5m", "15m"],
        data_root="data",
    )
    status = scheduler.run_once()

    assert status.fresh is True
    assert status.all_fresh is False
    assert status.fresh_timeframes == ["1m", "5m"]
    assert status.stale_timeframes == ["15m"]
    assert status.symbols_updated == ["SPY"]
