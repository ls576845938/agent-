import json
from pathlib import Path

import pandas as pd


RUN = Path("artifacts/btc_candidate_validation/20260516T133000Z_compression_expansion_eventledger")


def test_event_ledger_attribution_report_schema_and_root_cause() -> None:
    report = json.loads((RUN / "event_ledger_attribution_report.json").read_text(encoding="utf-8"))

    assert report["schema_version"] == "btc_compression_expansion_event_ledger_attribution_v1"
    assert report["source"] == "event_ledger_equity_snapshots"
    assert report["gate_status"] == "candidate_gate_failed"
    assert report["paper_queue"] == "LOCKED"
    assert report["live"] == "FROZEN"
    assert report["ordinary_pf"] >= 1.15
    assert report["event_pf"] < 1.15
    assert "event_profit_factor" in report["gate_fail_reasons"]
    assert any("ordinary PF" in line for line in report["root_cause_summary"])
    assert any("walk-forward pass rate" in line for line in report["root_cause_summary"])


def test_event_ledger_attribution_table_schema() -> None:
    table = pd.read_csv(RUN / "event_ledger_attribution_table.csv")

    for column in [
        "timestamp",
        "equity_before",
        "equity_after",
        "event_return",
        "signed_event_pnl",
        "active_exposure",
        "fold_id",
        "regime",
        "segment_age_bucket",
    ]:
        assert column in table.columns
    assert len(table) > 20_000


def test_fold_regime_cleanup_blocks_paper_until_all_gates_pass() -> None:
    cleanup = json.loads((RUN / "fold_regime_diagnostics_cleanup.json").read_text(encoding="utf-8"))

    assert cleanup["schema_version"] == "btc_fold_regime_diagnostics_cleanup_v1"
    assert cleanup["failed_folds"] == ["3", "4"]
    assert "trending_down" in cleanup["dragging_regimes"]
    assert any("Require fold/regime gates before paper_review_pending" in item for item in cleanup["cleanup_actions"])
