import json
from pathlib import Path

import pandas as pd


RUN = Path("artifacts/btc_hypothesis/20260516T120000Z_lowvol_uptrend")


def test_low_vol_uptrend_feature_profile_schema() -> None:
    profile = json.loads((RUN / "low_vol_uptrend_feature_profile.json").read_text(encoding="utf-8"))

    assert profile["schema_version"] == "btc_low_vol_uptrend_feature_profile_v1"
    assert profile["no_lookahead"]["status"] == "pass"
    assert profile["no_lookahead"]["future_return_usage"] == "labels_only"
    assert profile["feature_definitions"]["side"] == "long_only"
    assert profile["feature_definitions"]["orderflow_entry_trigger"] is False
    assert profile["active_event_count"] >= 300


def test_low_vol_uptrend_event_table_labels_are_marked() -> None:
    table = pd.read_csv(RUN / "low_vol_uptrend_event_table.csv")

    for column in [
        "timestamp",
        "event_return_forward_1h",
        "event_return_forward_4h",
        "event_return_forward_12h",
        "event_return_forward_24h",
        "realized_vol",
        "vol_bucket",
        "trend_strength",
        "trend_bucket",
        "pullback_depth",
        "continuation_score",
        "regime",
        "excluded_regime_flags",
        "fold_id",
        "is_hypothesis_active",
        "future_return_used_only_for_label",
    ]:
        assert column in table.columns
    assert table["future_return_used_only_for_label"].all()
