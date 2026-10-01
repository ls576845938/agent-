from pathlib import Path

import pandas as pd


def test_trade_attribution_entry_features_do_not_use_future_bars() -> None:
    attribution = pd.read_csv("artifacts/btc_canonical/20260516T061000Z_attribution/trade_attribution.csv")

    entry_feature_time = pd.to_datetime(attribution["entry_feature_time"], utc=True)
    entry_time = pd.to_datetime(attribution["entry_time"], utc=True)

    assert not attribution.empty
    assert (entry_feature_time <= entry_time).all()
    assert attribution["entry_regime"].notna().all()
    assert Path("docs/research/BTC_REGIME_FILTER_DESIGN.md").exists()
