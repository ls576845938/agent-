import json
from pathlib import Path

import pandas as pd


RUN = Path("artifacts/btc_canonical/20260516T080000Z_eventpf_wf")


def test_v4_trade_attribution_entry_features_are_past_or_current() -> None:
    attribution = pd.read_csv(RUN / "btc_perp_dual_trend_v4_eventpf_wf" / "trade_attribution.csv")

    assert not attribution.empty
    entry_time = pd.to_datetime(attribution["entry_time"], utc=True)
    feature_time = pd.to_datetime(attribution["entry_feature_time"], utc=True)
    assert (feature_time <= entry_time).all()


def test_side_regime_ablation_records_no_lookahead_basis() -> None:
    report = json.loads((RUN / "side_regime_ablation_report.json").read_text(encoding="utf-8"))

    assert report["schema_version"] == "btc_side_regime_ablation_v1"
    assert any("No future returns are used" in note for note in report["notes"])
    assert "orderflow_short_trigger" in report["rejected_rules"]
