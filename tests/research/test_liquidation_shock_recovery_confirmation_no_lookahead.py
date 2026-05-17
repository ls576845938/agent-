import pandas as pd

from quant_us.research.btc_eventpf_wf import load_btc_1h_frame
from quant_us.research.btc_liquidation_shock_attribution import liquidation_shock_signal_with_rules


def test_liquidation_shock_recovery_confirmation_no_lookahead() -> None:
    frame = load_btc_1h_frame().tail(2200)
    mutated = frame.copy()
    cutoff = len(mutated) // 2
    mutated.loc[mutated.index[cutoff:], ["open", "high", "low", "close", "volume"]] *= 1.35

    base_signal, _ = liquidation_shock_signal_with_rules(
        frame,
        {"second_confirmation": "combined_recovery_confirmation"},
    )
    mutated_signal, _ = liquidation_shock_signal_with_rules(
        mutated,
        {"second_confirmation": "combined_recovery_confirmation"},
    )
    cutoff_ts = frame.index[cutoff - 80]

    pd.testing.assert_series_equal(
        base_signal.loc[base_signal.index <= cutoff_ts],
        mutated_signal.loc[mutated_signal.index <= cutoff_ts],
        check_names=False,
    )
