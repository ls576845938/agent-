import json
from pathlib import Path

import pandas as pd

from quant_us.research.btc_eventreturn_alpha import profit_factor


RUN = Path("artifacts/btc_canonical/20260516T100000Z_eventreturn_alpha")


def test_event_pf_recomputes_from_event_returns() -> None:
    report = json.loads((RUN / "event_return_attribution.json").read_text(encoding="utf-8"))
    table = pd.read_csv(RUN / "event_return_table.csv")

    recomputed = profit_factor(table["event_return"])

    assert abs(recomputed - report["event_PF"]) < 1e-9
    assert abs(report["event_PF"] - report["source_event_PF"]) <= 0.001


def test_event_pf_remains_gate_metric_not_closed_trade_pf() -> None:
    report = json.loads((RUN / "event_return_attribution.json").read_text(encoding="utf-8"))

    assert report["event_pf_definition_summary"]["definition"].startswith("sum positive hourly event returns")
    assert report["event_pf_definition_summary"]["ordinary_PF_status"] == "diagnostic_only"
