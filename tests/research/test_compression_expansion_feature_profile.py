import json
from pathlib import Path

import pandas as pd


RUN = Path("artifacts/btc_hypothesis/20260516T122000Z_compression_expansion")


def test_compression_expansion_feature_profile_schema() -> None:
    profile = json.loads((RUN / "feature_profile.json").read_text(encoding="utf-8"))

    assert profile["schema_version"] == "btc_hypothesis_lab_feature_profile_v1"
    assert profile["hypothesis_id"] == "compression_expansion_breakout_v0"
    assert profile["no_lookahead"]["status"] == "pass"
    assert profile["feature_definitions"]["orderflow_entry_trigger"] is False
    assert profile["active_event_count"] >= 200
    assert profile["upside_event_count"] > 0
    assert profile["downside_event_count"] > 0


def test_compression_expansion_event_table_fields() -> None:
    table = pd.read_csv(RUN / "event_table.csv")
    required = [
        "timestamp",
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
        "close",
        "event_return_forward_1h",
        "event_return_forward_4h",
        "event_return_forward_12h",
        "event_return_forward_24h",
        "event_return_forward_48h",
        "future_return_used_only_for_label",
    ]
    for column in required:
        assert column in table.columns
    assert table["future_return_used_only_for_label"].all()
