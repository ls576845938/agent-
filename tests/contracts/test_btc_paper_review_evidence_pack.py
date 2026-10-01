from __future__ import annotations

import hashlib
import json
from pathlib import Path

import jsonschema

from scripts.build_btc_paper_readiness_report import build_btc_paper_readiness_report
from scripts.build_btc_paper_review_evidence_pack import (
    build_btc_paper_review_evidence_pack_report,
    write_btc_paper_review_evidence_pack_artifacts,
)


SCHEMA = Path("schemas/btc_paper_review_evidence_pack_report.schema.json")


def test_btc_paper_review_evidence_pack_report_schema_valid() -> None:
    payload = build_btc_paper_review_evidence_pack_report(generated_at="2026-06-22T00:00:00Z")
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    jsonschema.validate(payload, schema)
    contract = payload["promotion_evidence_contract"]
    assert contract["schema_version"] == "btc_promotion_evidence_contract_v1"
    assert contract["status"] == "complete"
    assert contract["missing_fields"] == []
    assert contract["missing_minimum_metrics"] == []
    assert contract["blockers"] == []
    assert set(contract["required_fields"]) == {
        "strategy_id",
        "research_question",
        "economic_hypothesis",
        "data_source",
        "data_version",
        "start_time",
        "end_time",
        "decision_time_rule",
        "execution_time_rule",
        "cost_model",
        "slippage_model",
        "params",
        "params_hash",
        "candidate_count",
        "trial_count",
        "selected_by",
        "walk_forward_summary",
        "regime_summary",
        "parameter_stability_summary",
        "cost_stress_summary",
        "ledger_reconciliation",
        "promotion_decision",
    }
    assert all(item["present"] for item in contract["fields"].values())
    assert contract["fields"]["walk_forward_summary"]["value"]["pass_rate"] == 0.833333
    assert contract["fields"]["regime_summary"]["value"]["pass_rate"] == 0.8
    assert contract["fields"]["cost_stress_summary"]["value"]["scenario_count"] == 5
    assert contract["fields"]["ledger_reconciliation"]["value"]["ledger_equity_consistent"] is True
    assert contract["minimum_metrics"]["number_of_bets"] == 78
    assert contract["minimum_metrics"]["capacity_proxy"]["unit"] == "USDT_notional_at_recorded_trade_size"


def test_current_btc_paper_review_evidence_pack_blocks_after_review_already_approved(tmp_path: Path) -> None:
    payload = build_btc_paper_review_evidence_pack_report(
        data_root=tmp_path / "data",
        generated_at="2026-06-22T00:00:00Z",
    )
    output = write_btc_paper_review_evidence_pack_artifacts(
        payload,
        output_root=tmp_path / "artifacts/btc_paper_readiness/latest",
    )
    evidence_path = Path(payload["evidence_pack_path"])
    template_path = Path(payload["review_template_path"])
    final_review_path = Path(payload["final_review_path"])
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    template = json.loads(template_path.read_text(encoding="utf-8"))

    assert Path(output).exists()
    assert payload["status"] == "blocked"
    assert payload["decision"] == "repair_evidence_before_review"
    assert payload["next_required_action"] == "repair_paper_review_evidence_pack"
    assert payload["paper_start_allowed"] is False
    assert payload["paper_execution_authorized"] is False
    assert payload["guardrails"]["broker_calls_allowed"] is False
    assert payload["guardrails"]["order_endpoints_allowed"] is False
    assert "btc_promotion_evidence_missing_strategy_id" not in payload["blockers"]
    assert payload["blockers"] == [
        "btc_paper_review_current_status_not_ready",
        "btc_paper_review_readiness_not_waiting_for_manual_review",
        "btc_paper_review_readiness_already_allows_start",
        "btc_paper_review_execution_already_authorized",
        "btc_paper_review_start_report_not_blocked",
    ]
    assert evidence["schema_version"] == "btc_paper_review_evidence_pack_v1"
    assert evidence["status"] == "blocked"
    assert evidence["promotion_evidence_contract"]["status"] == "complete"
    assert evidence["promotion_evidence_contract"]["missing_fields"] == []
    assert evidence["readiness"]["status"] == "ready_for_paper_start"
    assert evidence["readiness"]["paper_start_allowed"] is True
    assert template["schema_version"] == "paper_review_candidate_template_v1"
    assert template["status"] == "PENDING_HUMAN_REVIEW"
    assert template["approval"]["valid"] is False
    assert template["approval"]["source"] == payload["evidence_pack_path"]
    assert template["approval"]["source_sha256"] == _sha256(evidence_path)
    assert template["approval"]["gate_snapshot"]["paper_execution_authorized"] is False
    assert template["approval"]["gate_snapshot"]["authorization_scope"] == "human_review_only"
    assert template["instructions"]["required_final_status"] == "APPROVED_FOR_PAPER_ONLY"
    assert not final_review_path.exists()

    readiness = build_btc_paper_readiness_report(
        data_root=tmp_path / "data",
        generated_at="2026-06-22T00:00:00Z",
    )
    assert readiness["status"] == "ready_for_manual_paper_review"
    assert readiness["paper_start_allowed"] is False
    assert readiness["approved_paper_review"]["approved"] is False


def test_btc_paper_review_evidence_pack_blocks_without_candidate_gate(tmp_path: Path) -> None:
    payload = build_btc_paper_review_evidence_pack_report(
        repo_root=tmp_path,
        data_root=tmp_path / "data",
        generated_at="2026-06-22T00:00:00Z",
    )
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    jsonschema.validate(payload, schema)
    assert payload["status"] == "blocked"
    assert payload["paper_start_allowed"] is False
    assert payload["paper_execution_authorized"] is False
    assert payload["promotion_evidence_contract"]["status"] == "blocked"
    assert "btc_paper_review_candidate_gate_missing" in payload["blockers"]
    assert "btc_paper_review_readiness_missing" in payload["blockers"]
    assert "btc_promotion_evidence_missing_strategy_id" in payload["blockers"]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
