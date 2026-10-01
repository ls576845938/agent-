import numpy as np
import pandas as pd

from quant_us.research.btc_alpha_hardening import btc_orderflow_confirmed_trend_signal


def test_orderflow_cannot_open_without_trend() -> None:
    index = pd.date_range("2024-01-01", periods=40, freq="h", tz="UTC")
    close = pd.Series(np.full(len(index), 100.0), index=index)
    volume = pd.Series(np.full(len(index), 100.0), index=index)
    taker_buy = volume * 0.5
    taker_buy.iloc[10:] = volume.iloc[10:] * 0.9
    frame = pd.DataFrame(
        {
            "open": close,
            "high": close * 1.001,
            "low": close * 0.999,
            "close": close,
            "volume": volume,
            "quote_volume": volume * close,
            "trade_count": 100.0,
            "taker_buy_base_volume": taker_buy,
        },
        index=index,
    )

    signal, diagnostics = btc_orderflow_confirmed_trend_signal(
        frame,
        {
            "fast_ma": 2,
            "slow_ma": 4,
            "regime_ma": 6,
            "momentum_window": 2,
            "momentum_threshold": 0.001,
            "orderflow_window": 3,
            "activity_window": 3,
            "buy_ratio_threshold": 0.6,
            "pressure_threshold": 0.0,
            "signal_persistence_bars": 2,
            "min_hold_bars": 1,
            "cooldown_bars": 1,
            "blocked_regimes": [],
        },
    )

    assert diagnostics["orderflow_long_confirm"].sum() > 0
    assert diagnostics["trend_long"].sum() == 0
    assert diagnostics["target_signal"].abs().sum() == 0
    assert signal.abs().sum() == 0
