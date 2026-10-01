import json
from pathlib import Path

from scripts.run_btc_canonical_attribution import STRATEGIES


def test_canonical_sprint_does_not_run_orderflow_as_standalone_entry_strategy() -> None:
    strategy_ids = set(STRATEGIES)

    assert "btc_orderflow_pressure" not in strategy_ids
    assert "btc_orderflow_confirmed_trend_v1" not in strategy_ids


def test_orderflow_ablation_keeps_orderflow_out_of_entry_trigger() -> None:
    report = json.loads(
        Path("artifacts/btc_canonical/20260516T061000Z_attribution/orderflow_ablation_report.json").read_text(
            encoding="utf-8"
        )
    )

    assert report["orderflow_entry_trigger_allowed"] is False
    assert {row["mode"] for row in report["rows"]} == {
        "no_orderflow",
        "veto_only",
        "sizing_only",
        "veto_plus_sizing",
    }
    assert all(row["orderflow_entry_trigger_allowed"] is False for row in report["rows"])
