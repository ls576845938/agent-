from __future__ import annotations

import inspect

import numpy as np
import pandas as pd

from quant_us.execution import us_etf_rotation_execution
from quant_us.execution.us_etf_rotation_execution import simulate_us_etf_rotation_backtest_execution
from quant_us.portfolio import us_etf_rotation_portfolio
from quant_us.portfolio.us_etf_rotation_portfolio import construct_us_etf_rotation_portfolio
from quant_us.research.us_etf_macro_momentum_rotation import (
    UsEtfMacroMomentumRotationConfig,
    build_price_matrix_from_bars,
    run_us_etf_macro_momentum_rotation,
)
from quant_us.signals import us_etf_rotation_alpha
from quant_us.signals.us_etf_rotation_alpha import generate_us_etf_rotation_alpha_signals


def test_us_etf_rotation_has_explicit_signal_portfolio_execution_layers() -> None:
    cfg = UsEtfMacroMomentumRotationConfig(min_rows=300)
    prices = build_price_matrix_from_bars(_synthetic_bars(cfg.required_symbols(), periods=460), cfg.required_symbols())

    signals = generate_us_etf_rotation_alpha_signals(prices, pd.DataFrame(), cfg)
    portfolio = construct_us_etf_rotation_portfolio(prices, signals, cfg)
    execution = simulate_us_etf_rotation_backtest_execution(portfolio, signals.asset_returns, cfg)
    integrated = run_us_etf_macro_momentum_rotation(prices, pd.DataFrame(), cfg)

    assert signals.diagnostics["layer"] == "alpha_signal"
    assert set(signals.diagnostics["outputs"]) >= {
        "cross_sectional_momentum",
        "absolute_trend",
        "macro_regime",
    }
    assert portfolio.diagnostics["layer"] == "portfolio_construction"
    assert portfolio.diagnostics["t_plus_1_execution"] is True
    assert execution.diagnostics["layer"] == "execution_simulation"
    pd.testing.assert_series_equal(execution.strategy_returns, integrated.strategy_returns)
    assert integrated.diagnostics["architecture_layers"] == [
        "alpha_signal",
        "portfolio_construction",
        "execution_simulation",
    ]


def test_us_etf_core_layers_do_not_import_data_download_or_broker_code() -> None:
    forbidden = [
        "import requests",
        "from requests",
        "import urllib",
        "from urllib",
        "private_endpoint",
        "order_endpoint_used",
        "live_order_allowed",
        "tiingo",
        "api_key",
    ]
    for module in [us_etf_rotation_alpha, us_etf_rotation_portfolio, us_etf_rotation_execution]:
        source = inspect.getsource(module).lower()
        assert not any(token in source for token in forbidden), module.__name__


def _synthetic_bars(symbols: list[str] | tuple[str, ...], *, periods: int) -> pd.DataFrame:
    dates = pd.bdate_range("2020-01-01", periods=periods, tz="UTC")
    rows = []
    x = np.arange(periods, dtype=float)
    for index, symbol in enumerate(symbols):
        drift = 0.02 + index * 0.002
        seasonal = np.sin(x / (18.0 + index)) * (0.4 + index * 0.03)
        close = 50.0 + index * 3.0 + x * drift + seasonal
        close = np.maximum(close, 3.0)
        rows.append(
            pd.DataFrame(
                {
                    "timestamp_utc": dates,
                    "symbol": symbol,
                    "open": close * 0.99,
                    "high": close * 1.01,
                    "low": close * 0.98,
                    "close": close,
                    "volume": 1_000_000 + index,
                }
            )
        )
    return pd.concat(rows, ignore_index=True)
