from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd

from quant_us.research.btc_liquidation_shock_recovery import DEFAULT_CONFIG_PATH, build_event_table, load_config


def _frame(rows: int = 320) -> pd.DataFrame:
    timestamps = [datetime(2024, 1, 1, tzinfo=timezone.utc) + timedelta(hours=i) for i in range(rows)]
    close = [100.0 + i * 0.02 for i in range(rows)]
    close[100] = close[99] * 0.96
    close[101] = close[100] * 1.01
    volume = [1000.0] * rows
    volume[100] = 2500.0
    data = {
        "open": close,
        "high": [value * 1.01 for value in close],
        "low": [value * 0.99 for value in close],
        "close": close,
        "volume": volume,
        "quote_volume": [value * 100.0 for value in volume],
        "trade_count": [100] * rows,
        "taker_buy_base_volume": [value * 0.5 for value in volume],
        "taker_buy_quote_volume": [value * 50.0 for value in volume],
    }
    return pd.DataFrame(data, index=pd.DatetimeIndex(timestamps))


def test_liquidation_shock_features_do_not_change_when_future_bars_change() -> None:
    config = load_config(DEFAULT_CONFIG_PATH)
    base = _frame()
    changed = base.copy()
    changed.iloc[180:, changed.columns.get_loc("close")] = changed.iloc[180:]["close"] * 1.5
    changed.iloc[180:, changed.columns.get_loc("high")] = changed.iloc[180:]["high"] * 1.5
    changed.iloc[180:, changed.columns.get_loc("low")] = changed.iloc[180:]["low"] * 1.5

    base_table = build_event_table(base, config, drop_incomplete_labels=False)
    changed_table = build_event_table(changed, config, drop_incomplete_labels=False)
    feature_cols = [
        "liquidation_shock",
        "recent_liquidation_shock",
        "recovery_confirmed",
        "is_hypothesis_active",
        "volume_ratio",
        "wick_recovery_score",
        "regime",
    ]

    pd.testing.assert_frame_equal(
        base_table.loc[:160, feature_cols].reset_index(drop=True),
        changed_table.loc[:160, feature_cols].reset_index(drop=True),
    )
