import json
from pathlib import Path

import pandas as pd


RUN = Path("artifacts/btc_canonical/20260516T100000Z_eventreturn_alpha")


def test_event_return_attribution_schema_is_complete() -> None:
    report = json.loads((RUN / "event_return_attribution.json").read_text(encoding="utf-8"))

    assert report["schema_version"] == "btc_event_return_attribution_v1"
    for field in [
        "run_id",
        "source_run_id",
        "strategy_id",
        "event_PF",
        "source_event_PF",
        "event_pf_definition_summary",
        "overall_distribution",
        "by_fold",
        "by_regime",
        "by_side",
        "by_holding_age_bucket",
        "top_50_negative_events",
        "event_return_root_cause_summary",
    ]:
        assert field in report
    assert report["event_pf_definition_summary"]["gate_metric"] == "event_PF"


def test_event_return_table_contains_required_columns() -> None:
    table = pd.read_csv(RUN / "event_return_table.csv")

    for column in [
        "fold_id",
        "regime",
        "position_side",
        "event_return",
        "signed_event_pnl",
        "holding_age_bars",
        "exposure_bucket",
    ]:
        assert column in table.columns
    assert len(table) > 20_000
