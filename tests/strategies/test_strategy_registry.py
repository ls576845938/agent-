from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd

from backend.app.domain.strategy_registry import strategy_registry


UTC = timezone.utc


def _frame_from_closes(closes: list[float]) -> pd.DataFrame:
    start = datetime(2025, 1, 1, 0, 0, tzinfo=UTC)
    rows = []
    for offset, close in enumerate(closes):
        rows.append(
            {
                "timestamp": start + timedelta(hours=offset),
                "open": close,
                "high": close * 1.01,
                "low": close * 0.99,
                "close": close,
                "volume": 1_000_000.0,
            }
        )
    return pd.DataFrame(rows).set_index("timestamp")


def _turnover(signal: pd.Series) -> float:
    return signal.diff().abs().fillna(signal.abs()).sum()


def test_btc_low_turnover_trend_is_registered_and_exits_to_flat() -> None:
    strategy = strategy_registry.get("btc_low_turnover_trend")

    assert strategy.descriptor.default_params == {
        "fast_ma": 48,
        "slow_ma": 168,
        "trend_ma": 336,
        "vol_window": 72,
        "min_volatility": 0.003,
        "max_volatility": 0.06,
        "trend_strength": 0.04,
        "exit_buffer": 0.02,
        "entry_confirm_bars": 3,
        "exit_confirm_bars": 6,
        "min_hold_bars": 72,
        "cooldown_bars": 24,
    }

    frame = _frame_from_closes(
        [100.0 + 1.1 * idx for idx in range(14)]
        + [112.0, 108.0, 104.0, 101.0]
    )
    pack = strategy.generate(
        frame,
        params={
            "fast_ma": 3,
            "slow_ma": 5,
            "trend_ma": 8,
            "vol_window": 3,
            "min_volatility": 0.0,
            "max_volatility": 0.10,
            "trend_strength": 0.01,
            "exit_buffer": 0.01,
            "entry_confirm_bars": 1,
            "exit_confirm_bars": 1,
            "min_hold_bars": 1,
            "cooldown_bars": 0,
        },
    )

    assert set(pack.signal.unique()) <= {0.0, 1.0}
    assert pack.signal.iloc[7] == 1.0
    assert pack.signal.iloc[-1] == 0.0


def test_btc_low_turnover_trend_does_not_use_future_data() -> None:
    strategy = strategy_registry.get("btc_low_turnover_trend")
    base = _frame_from_closes([100.0 + idx for idx in range(24)])
    mutated = base.copy()
    mutated.loc[mutated.index[16]:, "close"] = [
        600.0,
        580.0,
        560.0,
        540.0,
        520.0,
        500.0,
        480.0,
        460.0,
    ]
    mutated.loc[:, "open"] = mutated["close"]
    mutated.loc[:, "high"] = mutated["close"] * 1.01
    mutated.loc[:, "low"] = mutated["close"] * 0.99

    params = {
        "fast_ma": 3,
        "slow_ma": 5,
        "trend_ma": 8,
        "vol_window": 3,
        "min_volatility": 0.0,
        "max_volatility": 0.30,
        "trend_strength": 0.01,
        "exit_buffer": 0.02,
        "entry_confirm_bars": 1,
        "exit_confirm_bars": 1,
        "min_hold_bars": 1,
        "cooldown_bars": 0,
    }
    base_signal = strategy.generate(base, params=params).signal
    mutated_signal = strategy.generate(mutated, params=params).signal

    pd.testing.assert_series_equal(base_signal.iloc[:16], mutated_signal.iloc[:16])


def test_btc_low_turnover_trend_has_lower_turnover_than_fast_trend_momentum() -> None:
    btc_strategy = strategy_registry.get("btc_low_turnover_trend")
    fast_strategy = strategy_registry.get("trend_momentum")
    closes = [
        100.0,
        101.0,
        102.0,
        103.0,
        104.0,
        105.0,
        104.0,
        105.0,
        104.0,
        105.0,
        104.0,
        105.0,
        104.0,
        106.0,
        104.0,
        106.0,
        104.0,
        107.0,
        103.0,
        107.0,
    ]
    frame = _frame_from_closes(closes)

    btc_signal = btc_strategy.generate(
        frame,
        params={
            "fast_ma": 3,
            "slow_ma": 6,
            "trend_ma": 10,
            "vol_window": 3,
            "min_volatility": 0.0,
            "max_volatility": 0.08,
            "trend_strength": 0.01,
            "exit_buffer": 0.03,
            "entry_confirm_bars": 2,
            "exit_confirm_bars": 2,
            "min_hold_bars": 4,
            "cooldown_bars": 2,
        },
    ).signal
    fast_signal = fast_strategy.generate(frame, params={"lookback_bars": 1, "entry_threshold": 0.0}).signal

    assert _turnover(btc_signal) < _turnover(fast_signal)
