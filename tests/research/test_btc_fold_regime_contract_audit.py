import json
from pathlib import Path


RUN = Path("artifacts/btc_candidate_validation/20260516T133000Z_compression_expansion_eventledger")


def test_fold_regime_contract_audit_schema_and_fold_contract() -> None:
    audit = json.loads((RUN / "fold_regime_contract_audit.json").read_text(encoding="utf-8"))

    assert audit["schema_version"] == "btc_fold_regime_contract_audit_v1"
    assert audit["fold_contract"]["status"] == "pass"
    assert audit["fold_contract"]["fold_count"] == 4
    assert audit["fold_contract"]["label_trimmed_rows_due_to_forward_horizon"] == 48
    assert [row["fold_id"] for row in audit["fold_contract"]["folds"]] == ["1", "2", "3", "4"]


def test_regime_contract_records_gate_failure_and_contract_boundary() -> None:
    audit = json.loads((RUN / "fold_regime_contract_audit.json").read_text(encoding="utf-8"))

    assert audit["regime_contract"]["status"] == "fail"
    assert audit["regime_contract"]["pass_rate"] < 0.75
    assert "trending_down" in audit["regime_contract"]["dragging_regimes"]
    assert audit["regime_contract"]["gate_source"] == "entry_regime_from_ledger_segments"
    assert audit["regime_contract"]["diagnostic_source"] == "bar_level_event_ledger_attribution"


def test_promotion_contract_requires_all_three_evidence_gates() -> None:
    audit = json.loads((RUN / "fold_regime_contract_audit.json").read_text(encoding="utf-8"))
    contract = audit["promotion_contract"]

    assert contract["paper_review_pending_requires_all_three"] is True
    assert contract["event_pf_required"] == 1.15
    assert contract["walk_forward_pass_required"] == 0.80
    assert contract["regime_pass_required"] == 0.75
    assert contract["paper_ready_allowed"] is False
    assert contract["live_ready_allowed"] is False
