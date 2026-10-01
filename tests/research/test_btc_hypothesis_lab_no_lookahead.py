import pandas as pd

from quant_us.research.btc_hypothesis_lab import DEFAULT_CONFIG_PATH, build_event_table, load_hypothesis_config, load_btc_1h_frame


def test_compression_expansion_features_ignore_future_bars() -> None:
    config = load_hypothesis_config(DEFAULT_CONFIG_PATH)
    frame = load_btc_1h_frame().tail(2600)
    mutated = frame.copy()
    cutoff = len(mutated) // 2
    future_index = mutated.index[cutoff:]
    mutated.loc[future_index, ["open", "high", "low", "close"]] *= 1.35
    if "volume" in mutated:
        mutated.loc[future_index, "volume"] *= 2.0

    baseline = build_event_table(frame, config)
    changed = build_event_table(mutated, config)
    cutoff_ts = frame.index[cutoff - 80]
    before_cutoff = pd.to_datetime(baseline["timestamp"], utc=True) <= cutoff_ts
    feature_columns = [
        "fold_id",
        "regime",
        "volatility_bucket",
        "trend_strength_bucket",
        "compression_active",
        "compression_score",
        "expansion_active",
        "expansion_score",
        "breakout_direction",
        "upside_breakout",
        "downside_breakout",
        "range_expansion",
        "volatility_expansion",
        "box_high_prior",
        "box_low_prior",
        "range_compression",
        "atr_compression",
        "band_width_compression",
    ]

    pd.testing.assert_frame_equal(
        baseline.loc[before_cutoff, feature_columns].reset_index(drop=True),
        changed.loc[before_cutoff, feature_columns].reset_index(drop=True),
        check_dtype=False,
    )


def test_forward_returns_are_labels_only() -> None:
    config = load_hypothesis_config(DEFAULT_CONFIG_PATH)
    table = build_event_table(load_btc_1h_frame().tail(1200), config)

    assert table["future_return_used_only_for_label"].all()
    assert "event_return_forward_48h" in table.columns
