import pandas as pd

from quant_us.research.btc_alpha_hardening import apply_directional_state_machine


def test_min_holding_and_cooldown_delay_exits_and_reentries() -> None:
    index = pd.date_range("2024-01-01", periods=10, freq="h", tz="UTC")
    target = pd.Series([1, 0, 0, 0, 1, 1, 1, 0, 1, 1], index=index, dtype=float)

    signal = apply_directional_state_machine(
        target,
        min_holding_bars=3,
        cooldown_bars=2,
        exit_hysteresis_bars=1,
    )

    assert signal.iloc[0] == 1.0
    assert signal.iloc[1] == 1.0
    assert signal.iloc[2] == 1.0
    assert signal.iloc[3] == 0.0
    assert signal.iloc[4] == 0.0
    assert signal.iloc[5] == 1.0
