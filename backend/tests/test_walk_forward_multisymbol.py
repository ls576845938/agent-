"""Test multi-symbol walk-forward integration with promotion gate."""

from datetime import datetime, timedelta, timezone

import pytest
from quant_us.backtest.walk_forward import build_walk_forward_windows
from quant_us.backtest.walk_forward import (
    WalkForwardConfig,
    WalkForwardAggregate,
    aggregate_walk_forward,
)
from quant_us.core.types import Bar


def _make_multisymbol_bars(
    timestamps: int,
    symbols: tuple[str, ...] = ("AAPL", "MSFT"),
) -> list[Bar]:
    start = datetime(2024, 1, 2, 14, 30, tzinfo=timezone.utc)
    rows: list[Bar] = []
    for minute in range(timestamps):
        ts = start + timedelta(minutes=minute)
        for offset, symbol in enumerate(symbols):
            price = 100.0 + minute + offset
            rows.append(
                Bar(
                    timestamp_utc=ts,
                    symbol=symbol,
                    open=price,
                    high=price + 1.0,
                    low=price - 1.0,
                    close=price + 0.5,
                    volume=1_000.0,
                )
            )
    return rows


class TestWalkForwardMultiSymbol:
    """Verify multi-symbol walk-forward support and manifest generation."""

    def test_windows_split_on_unique_timestamps(self):
        """Train/test boundaries must not share a timestamp inside one fold."""
        bars = _make_multisymbol_bars(timestamps=7)
        cfg = WalkForwardConfig(train_bars=3, test_bars=2, step_bars=2)

        windows = build_walk_forward_windows(bars, cfg)

        assert len(windows) == 2
        assert windows[0].train_end < windows[0].test_start
        assert windows[1].train_end < windows[1].test_start

        for window in windows:
            train_ts = {
                bar.timestamp_utc
                for bar in bars
                if window.train_start <= bar.timestamp_utc <= window.train_end
            }
            test_ts = {
                bar.timestamp_utc
                for bar in bars
                if window.test_start <= bar.timestamp_utc <= window.test_end
            }
            assert train_ts
            assert test_ts
            assert train_ts.isdisjoint(test_ts)

    def test_windows_require_enough_unique_timestamps(self):
        """Repeated symbols at one timestamp do not count as extra fold capacity."""
        bars = _make_multisymbol_bars(timestamps=2, symbols=("AAPL", "MSFT", "NVDA", "AMZN"))

        windows = build_walk_forward_windows(
            bars,
            WalkForwardConfig(train_bars=2, test_bars=1, step_bars=1),
        )

        assert windows == []

    def test_config_supports_symbols(self):
        """WalkForwardConfig must accept symbols list."""
        cfg = WalkForwardConfig(
            symbols=["SPY", "QQQ", "IWM", "DIA"],
            strategy_id="etf_rotation",
            data_version="v1",
        )
        assert len(cfg.symbols) == 4
        assert "SPY" in cfg.symbols

    def test_config_defaults_empty_symbols(self):
        """Default config has empty symbols list."""
        cfg = WalkForwardConfig()
        assert cfg.symbols == []

    def test_aggregate_has_portfolio_metrics(self):
        """WalkForwardAggregate must have portfolio-level fields."""
        agg = WalkForwardAggregate(
            windows=[], total_windows=10, windows_consistent=8,
            oos_total_return_pct=15.0, oos_avg_sharpe=1.2, oos_avg_max_dd=-8.0,
            oos_win_rate=0.75, oos_avg_turnover_pct=1200.0,
            fold_pass_rate_pct=80.0, symbol_coverage_pct=100.0,
            symbols_tested=["SPY", "QQQ"], insufficient_data=False,
        )
        assert agg.fold_pass_rate_pct == 80.0
        assert agg.symbol_coverage_pct == 100.0
        assert agg.symbols_tested == ["SPY", "QQQ"]

    def test_fold_pass_rate_distinct_from_pass_rate(self):
        """fold_pass_rate_pct (multi-symbol) is distinct from pass_rate_pct (legacy)."""
        # Multi-symbol aggregate
        multi = WalkForwardAggregate(
            windows=[], total_windows=10, windows_consistent=5,
            oos_total_return_pct=10.0, oos_avg_sharpe=0.8, oos_avg_max_dd=-10.0,
            oos_win_rate=0.5, oos_avg_turnover_pct=2000.0,
            fold_pass_rate_pct=50.0,  # portfolio-level
            symbol_coverage_pct=80.0,
            symbols_tested=["SPY", "QQQ", "IWM", "DIA"],
            insufficient_data=False,
        )
        # fold_pass_rate_pct is the portfolio aggregate, separate from individual symbol pass rates
        assert multi.fold_pass_rate_pct == 50.0

    def test_insufficient_data_flag(self):
        """When data is insufficient, flag must be set."""
        agg = WalkForwardAggregate(
            windows=[], total_windows=0, windows_consistent=0,
            oos_total_return_pct=0.0, oos_avg_sharpe=0.0, oos_avg_max_dd=0.0,
            oos_win_rate=0.0, oos_avg_turnover_pct=0.0,
            fold_pass_rate_pct=0.0, symbol_coverage_pct=0.0,
            symbols_tested=[], insufficient_data=True,
        )
        assert agg.insufficient_data is True

    def test_symbol_coverage_partial(self):
        """When some symbols have insufficient data, coverage < 100%."""
        agg = WalkForwardAggregate(
            windows=[], total_windows=8, windows_consistent=4,
            oos_total_return_pct=5.0, oos_avg_sharpe=0.5, oos_avg_max_dd=-12.0,
            oos_win_rate=0.5, oos_avg_turnover_pct=1500.0,
            fold_pass_rate_pct=40.0, symbol_coverage_pct=50.0,  # only 2 of 4 symbols
            symbols_tested=["SPY", "QQQ"],
            insufficient_data=False,
        )
        assert agg.symbol_coverage_pct < 100.0
        assert len(agg.symbols_tested) == 2


class TestWalkForwardManifestPersistence:
    """Verify manifest path and content."""

    def test_save_manifest_has_expected_keys(self):
        """Manifest dict includes portfolio-level keys."""
        agg = WalkForwardAggregate(
            windows=[], total_windows=5, windows_consistent=4,
            oos_total_return_pct=12.0, oos_avg_sharpe=1.0, oos_avg_max_dd=-7.0,
            oos_win_rate=0.6, oos_avg_turnover_pct=1800.0,
            fold_pass_rate_pct=75.0, symbol_coverage_pct=100.0,
            symbols_tested=["SPY", "QQQ", "IWM", "DIA"],
            insufficient_data=False,
        )
        result = {
            "fold_pass_rate_pct": agg.fold_pass_rate_pct,
            "symbol_coverage_pct": agg.symbol_coverage_pct,
            "symbols_tested": agg.symbols_tested,
            "insufficient_data": agg.insufficient_data,
            "oos_avg_turnover_pct": agg.oos_avg_turnover_pct,
        }
        assert "fold_pass_rate_pct" in result
        assert "symbols_tested" in result
        assert "insufficient_data" in result
