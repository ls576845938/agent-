import pandas as pd

from quant_us.research.btc_low_vol_uptrend import DEFAULT_PARAMS, _feature_event_table, load_btc_1h_frame


def test_low_vol_uptrend_features_ignore_future_bars() -> None:
    frame = load_btc_1h_frame().tail(2500)
    mutated = frame.copy()
    cutoff = len(mutated) // 2
    future_index = mutated.index[cutoff:]
    mutated.loc[future_index, ["open", "high", "low", "close"]] *= 1.25
    if "volume" in mutated:
        mutated.loc[future_index, "volume"] *= 2.0

    baseline = _feature_event_table(frame, DEFAULT_PARAMS)
    changed = _feature_event_table(mutated, DEFAULT_PARAMS)
    cutoff_ts = frame.index[cutoff - 60]
    before_cutoff = pd.to_datetime(baseline["timestamp"], utc=True) <= cutoff_ts

    feature_columns = [
        "realized_vol",
        "vol_bucket",
        "trend_strength",
        "trend_bucket",
        "pullback_depth",
        "continuation_score",
        "regime",
        "excluded_regime_flags",
        "is_hypothesis_active",
        "low_vol",
        "uptrend_confirmation",
        "continuation_state",
        "recent_liquidation_shock",
    ]
    pd.testing.assert_frame_equal(
        baseline.loc[before_cutoff, feature_columns].reset_index(drop=True),
        changed.loc[before_cutoff, feature_columns].reset_index(drop=True),
        check_dtype=False,
    )


def test_low_vol_uptrend_forward_returns_are_labels_only() -> None:
    table = _feature_event_table(load_btc_1h_frame().tail(1200), DEFAULT_PARAMS)

    assert table["future_return_used_only_for_label"].all()
    for column in ["event_return_forward_1h", "event_return_forward_4h", "event_return_forward_12h"]:
        assert column in table.columns
