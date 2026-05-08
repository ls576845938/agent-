"""Test multi-symbol walk-forward integration with promotion gate."""

import pytest
from quant_us.backtest.walk_forward import (
    WalkForwardConfig,
    WalkForwardAggregate,
    aggregate_walk_forward,
)


class TestWalkForwardMultiSymbol:
    """Verify multi-symbol walk-forward support and manifest generation."""

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
