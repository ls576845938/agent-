import json
from pathlib import Path


RUN = Path("artifacts/btc_candidate_validation/20260516T133000Z_compression_expansion_eventledger")


def test_failure_mode_report_preserves_event_ledger_gate_failure() -> None:
    report = json.loads((RUN / "compression_expansion_failure_mode_report.json").read_text(encoding="utf-8"))

    assert report["schema_version"] == "btc_compression_expansion_failure_mode_report_v1"
    assert report["gate_status"] == "candidate_gate_failed"
    assert "event_profit_factor" in report["gate_fail_reasons"]
    assert report["paper_queue"] == "LOCKED"
    assert report["live"] == "FROZEN"
    assert report["candidate_metrics"]["ordinary_pf"] >= 1.15
    assert report["candidate_metrics"]["event_pf"] < 1.15


def test_failure_mode_report_separates_full_and_active_exposure_pf() -> None:
    report = json.loads((RUN / "compression_expansion_failure_mode_report.json").read_text(encoding="utf-8"))
    split = report["full_vs_active_exposure"]

    assert split["active_exposure"]["event_pf"] >= 1.15
    assert split["full_ledger"]["event_pf"] < 1.15
    assert split["full_event_pf_gate_passes"] is False
    assert split["active_event_pf_gate_passes"] is True
    assert "diagnostic only" in split["diagnostic_note"]


def test_failure_mode_report_identifies_failed_folds_without_paper_promotion() -> None:
    report = json.loads((RUN / "compression_expansion_failure_mode_report.json").read_text(encoding="utf-8"))

    assert [row["fold_id"] for row in report["failed_fold_autopsy"]] == ["3", "4"]
    assert report["repairability_assessment"]["conclusion"] == "not_yet_fixable_without_more_evidence"
    assert report["decision"]["paper_review_pending_created"] is False
    assert report["decision"]["live_changed"] is False
