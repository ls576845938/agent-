from pathlib import Path

import pandas as pd


RUN_DIR = Path("artifacts/btc_canonical/20260516T061000Z_attribution")


def test_trade_attribution_is_derived_from_ledger_fills() -> None:
    attribution = pd.read_csv(RUN_DIR / "trade_attribution.csv")
    ledger = pd.read_csv(RUN_DIR / "trade_ledger.csv")

    assert not attribution.empty
    assert set(attribution["attribution_source"]) == {"ledger_fills"}
    assert set(ledger["attribution_source"]) == {"ledger_fills"}
    assert set(attribution["trade_id"]).issubset(set(ledger["trade_id"]))
    assert "net_pnl" in attribution.columns
    assert "entry_signal_components" in attribution.columns
