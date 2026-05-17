import json
from pathlib import Path

import pandas as pd


RUN = Path("artifacts/btc_candidate_attribution/20260517T010000Z_liquidation_shock_attribution")


def test_liquidation_shock_event_return_attribution_schema() -> None:
    report = json.loads((RUN / "liquidation_shock_event_return_attribution.json").read_text(encoding="utf-8"))
    table = pd.read_csv(RUN / "liquidation_shock_event_return_table.csv")

    assert report["schema_version"] == "btc_liquidation_shock_event_return_attribution_v1"
    assert report["event_PF"] == 0.998
    assert report["event_PF_recomputed"] < 1.15
    assert report["promotion_status"] == "candidate_gate_failed"
    assert report["paper_queue"] == "LOCKED"
    assert report["live"] == "FROZEN"
    assert report["event_return_root_cause_summary"]

    required_columns = {
        "fold_id",
        "regime",
        "event_return",
        "signed_event_pnl",
        "active_exposure",
        "recovery_age_bars",
        "time_since_shock_bars",
        "time_to_exit_bars",
        "mean_reverting_chop_flag",
        "confirmation_state",
    }
    assert required_columns.issubset(set(table.columns))
    assert table["active_exposure"].astype(bool).sum() > 0
    assert "3" in set(table["fold_id"].astype(str))
