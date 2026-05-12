from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd

from backend.app.domain.strategy_registry import (
    BTC_DOWNTREND_LOW_VOL_FILTER_DEFAULTS,
    _btc_downtrend_low_volatility_filter,
    _confirmed_stateful_long_signal,
    strategy_registry,
)


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
        **BTC_DOWNTREND_LOW_VOL_FILTER_DEFAULTS,
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


def test_btc_downtrend_low_volatility_filter_forces_flat_state() -> None:
    closes = [120.0 - 0.08 * idx for idx in range(48)]
    frame = _frame_from_closes(closes)
    risk_off, diagnostics = _btc_downtrend_low_volatility_filter(
        frame,
        {
            "regime_filter_enabled": 1.0,
            "regime_filter_window": 4,
            "regime_filter_vol_window": 4,
            "regime_filter_low_vol_quantile": 1.0,
            "regime_filter_downtrend_threshold": -0.001,
        },
    )

    signal = _confirmed_stateful_long_signal(
        frame.index,
        entry_ready=(~risk_off),
        exit_ready=risk_off,
        entry_confirm_bars=1,
        exit_confirm_bars=1,
        min_hold_bars=1,
        cooldown_bars=0,
    )

    assert risk_off.tail(12).all()
    assert diagnostics["downtrend_low_vol_risk_off"].iloc[-1] == 1.0
    assert signal.max() == 1.0
    assert signal.iloc[-1] == 0.0


def test_btc_downtrend_low_volatility_filter_uses_only_past_data() -> None:
    frame = _frame_from_closes([100.0 + 0.02 * idx for idx in range(36)])
    mutated = frame.copy()
    mutated.loc[mutated.index[24]:, "close"] = [150.0 - 2.0 * idx for idx in range(12)]
    mutated.loc[:, "open"] = mutated["close"]
    mutated.loc[:, "high"] = mutated["close"] * 1.01
    mutated.loc[:, "low"] = mutated["close"] * 0.99

    config = {
        "regime_filter_enabled": 1.0,
        "regime_filter_window": 4,
        "regime_filter_vol_window": 4,
        "regime_filter_low_vol_quantile": 0.5,
        "regime_filter_downtrend_threshold": 0.0,
    }
    base_risk_off, base_diagnostics = _btc_downtrend_low_volatility_filter(frame, config)
    mutated_risk_off, mutated_diagnostics = _btc_downtrend_low_volatility_filter(mutated, config)

    cutoff = frame.index[23]
    pd.testing.assert_series_equal(base_risk_off.loc[:cutoff], mutated_risk_off.loc[:cutoff])
    pd.testing.assert_series_equal(
        base_diagnostics["regime_low_vol_threshold"].loc[:cutoff],
        mutated_diagnostics["regime_low_vol_threshold"].loc[:cutoff],
    )


def test_btc_downtrend_low_volatility_filter_requires_recovery_before_reentry() -> None:
    closes = [
        100.0,
        99.9,
        99.8,
        99.7,
        99.6,
        99.5,
        99.4,
        99.3,
        99.2,
        99.1,
        99.25,
        99.35,
        99.45,
        102.0,
        102.5,
        103.0,
    ]
    frame = _frame_from_closes(closes)
    risk_off, diagnostics = _btc_downtrend_low_volatility_filter(
        frame,
        {
            "regime_filter_enabled": 1.0,
            "regime_filter_window": 3,
            "regime_filter_vol_window": 3,
            "regime_filter_low_vol_quantile": 1.0,
            "regime_filter_downtrend_threshold": 0.0,
            "regime_filter_reentry_return_threshold": 0.02,
        },
    )

    first_trigger_idx = diagnostics["downtrend_low_vol_trigger"].loc[
        diagnostics["downtrend_low_vol_trigger"] > 0
    ].index[0]

    assert risk_off.loc[first_trigger_idx]
    assert risk_off.iloc[-4]
    assert diagnostics["regime_reentry_state"].iloc[-1] == 1.0
    assert not risk_off.iloc[-1]


def test_confirmed_stateful_long_signal_enforces_max_hold_timeout() -> None:
    frame = _frame_from_closes([100.0 + idx for idx in range(12)])
    signal = _confirmed_stateful_long_signal(
        frame.index,
        entry_ready=pd.Series(True, index=frame.index),
        exit_ready=pd.Series(False, index=frame.index),
        entry_confirm_bars=1,
        exit_confirm_bars=1,
        min_hold_bars=1,
        cooldown_bars=99,
        max_hold_bars=3,
    )

    assert signal.iloc[:3].tolist() == [1.0, 1.0, 1.0]
    assert signal.iloc[3:].sum() == 0.0


def test_btc_new_strategy_families_are_registered_and_long_only() -> None:
    strategy_params = {
        "btc_trend_pullback": {
            "fast_ma": 4,
            "slow_ma": 8,
            "trend_ma": 12,
            "pullback_pct": 0.01,
            "pullback_lookback": 20,
            "pullback_rsi": 55,
            "rsi_window": 4,
            "trend_strength": 0.0,
            "exit_buffer": 0.02,
            "entry_confirm_bars": 1,
            "exit_confirm_bars": 1,
            "min_hold_bars": 1,
            "cooldown_bars": 0,
        },
        "btc_vol_breakout": {
            "breakout_window": 6,
            "vol_window": 4,
            "min_volatility": 0.0,
            "max_volatility": 0.20,
            "volume_window": 4,
            "volume_mult": 0.5,
            "exit_ma": 6,
            "stop_pct": 0.20,
            "entry_confirm_bars": 1,
            "exit_confirm_bars": 1,
            "min_hold_bars": 1,
            "cooldown_bars": 0,
        },
        "btc_regime_trend": {
            "fast_ma": 4,
            "slow_ma": 8,
            "regime_ma": 12,
            "momentum_window": 4,
            "momentum_threshold": 0.0,
            "vol_window": 4,
            "max_volatility": 0.20,
            "min_trend_strength": 0.0,
            "exit_buffer": 0.03,
            "entry_confirm_bars": 1,
            "exit_confirm_bars": 1,
            "min_hold_bars": 1,
            "cooldown_bars": 0,
        },
        "btc_low_turnover_breakout": {
            "entry_window": 8,
            "exit_window": 4,
            "trend_ma": 10,
            "vol_window": 4,
            "max_volatility": 0.20,
            "breakout_buffer": 0.0,
            "entry_confirm_bars": 1,
            "exit_confirm_bars": 1,
            "min_hold_bars": 1,
            "cooldown_bars": 0,
        },
    }
    closes = [
        100.0,
        101.0,
        102.0,
        103.0,
        101.0,
        104.0,
        106.0,
        108.0,
        107.0,
        110.0,
        113.0,
        116.0,
        119.0,
        123.0,
        126.0,
        130.0,
        135.0,
        141.0,
        148.0,
        156.0,
    ]
    frame = _frame_from_closes(closes)

    for strategy_id, params in strategy_params.items():
        strategy = strategy_registry.get(strategy_id)
        pack = strategy.generate(frame, params=params)

        assert set(pack.signal.unique()) <= {0.0, 1.0}
        assert pack.signal.max() == 1.0


def test_btc_new_strategy_families_do_not_use_future_data() -> None:
    params_by_strategy = {
        "btc_trend_pullback": {
            "fast_ma": 3,
            "slow_ma": 5,
            "trend_ma": 8,
            "pullback_pct": 0.01,
            "pullback_lookback": 4,
            "pullback_rsi": 60,
            "rsi_window": 3,
            "trend_strength": 0.0,
            "exit_buffer": 0.02,
            "entry_confirm_bars": 1,
            "exit_confirm_bars": 1,
            "min_hold_bars": 1,
            "cooldown_bars": 0,
        },
        "btc_vol_breakout": {
            "breakout_window": 5,
            "vol_window": 3,
            "min_volatility": 0.0,
            "max_volatility": 0.30,
            "volume_window": 3,
            "volume_mult": 0.5,
            "exit_ma": 5,
            "stop_pct": 0.25,
            "entry_confirm_bars": 1,
            "exit_confirm_bars": 1,
            "min_hold_bars": 1,
            "cooldown_bars": 0,
        },
        "btc_regime_trend": {
            "fast_ma": 3,
            "slow_ma": 5,
            "regime_ma": 8,
            "momentum_window": 3,
            "momentum_threshold": 0.0,
            "vol_window": 3,
            "max_volatility": 0.30,
            "min_trend_strength": 0.0,
            "exit_buffer": 0.02,
            "entry_confirm_bars": 1,
            "exit_confirm_bars": 1,
            "min_hold_bars": 1,
            "cooldown_bars": 0,
        },
        "btc_low_turnover_breakout": {
            "entry_window": 5,
            "exit_window": 3,
            "trend_ma": 8,
            "vol_window": 3,
            "max_volatility": 0.30,
            "breakout_buffer": 0.0,
            "entry_confirm_bars": 1,
            "exit_confirm_bars": 1,
            "min_hold_bars": 1,
            "cooldown_bars": 0,
        },
    }
    base = _frame_from_closes([100.0 + idx for idx in range(24)])
    mutated = base.copy()
    mutated.loc[mutated.index[16]:, "close"] = [500.0 - idx * 20.0 for idx in range(8)]
    mutated.loc[:, "open"] = mutated["close"]
    mutated.loc[:, "high"] = mutated["close"] * 1.01
    mutated.loc[:, "low"] = mutated["close"] * 0.99

    for strategy_id, params in params_by_strategy.items():
        strategy = strategy_registry.get(strategy_id)
        base_signal = strategy.generate(base, params=params).signal
        mutated_signal = strategy.generate(mutated, params=params).signal

        pd.testing.assert_series_equal(base_signal.iloc[:16], mutated_signal.iloc[:16])
