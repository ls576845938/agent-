import numpy as np
import pandas as pd

from quant_us.research.btc_alpha_hardening import classify_btc_regimes


def test_regime_classifier_does_not_change_past_when_future_changes() -> None:
    index = pd.date_range("2024-01-01", periods=120, freq="h", tz="UTC")
    close = pd.Series(np.linspace(100.0, 130.0, len(index)), index=index)
    frame = pd.DataFrame(
        {
            "open": close.shift(1).fillna(close.iloc[0]),
            "high": close * 1.002,
            "low": close * 0.998,
            "close": close,
            "volume": 100.0,
        },
        index=index,
    )
    mutated = frame.copy()
    mutated.loc[index[80]:, "close"] *= 2.5
    mutated.loc[index[80]:, "high"] *= 2.5
    mutated.loc[index[80]:, "low"] *= 2.5
    mutated.loc[index[80]:, "volume"] *= 15.0

    original_prefix = classify_btc_regimes(frame, trend_window=12, volatility_window=12, compression_window=36).iloc[:70]
    mutated_prefix = classify_btc_regimes(mutated, trend_window=12, volatility_window=12, compression_window=36).iloc[:70]

    pd.testing.assert_series_equal(original_prefix, mutated_prefix)
