import pandas as pd

from quant_us.research.btc_range_reclaim_lifecycle import build_event_table, load_config


def test_range_reclaim_prior_range_excludes_current_bar() -> None:
    index = pd.date_range("2024-01-01", periods=80, freq="h", tz="UTC")
    frame = pd.DataFrame(
        {
            "open": range(100, 180),
            "high": range(101, 181),
            "low": range(99, 179),
            "close": range(100, 180),
            "volume": [1.0] * 80,
        },
        index=index,
    )
    config = load_config("configs/btc/hypotheses/range_reclaim_momentum_v0.yaml")
    config = dict(config)
    config["feature_config"] = {**config["feature_config"], "range_window": 12, "fast_ma": 12, "slow_ma": 24, "slope_window": 6}

    table = build_event_table(frame, config, drop_incomplete_labels=False)
    row = table.iloc[30]

    assert row["prior_range_high"] == frame["high"].iloc[18:30].max()
    assert row["prior_range_high"] < frame["high"].iloc[30]
    assert bool(row["future_return_used_only_for_label"]) is True
