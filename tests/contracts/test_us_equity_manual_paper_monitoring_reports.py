from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from quant_us.live.paper_simulation_readiness import evaluate_paper_simulation_readiness
from scripts.build_us_equity_manual_review_packet import build_us_equity_manual_review_packet
from scripts.build_us_equity_monitoring_rules_report import build_us_equity_monitoring_rules_report
from scripts.build_us_equity_paper_simulation_readiness_report import (
    build_us_equity_paper_simulation_readiness_report,
)


PAPER_READINESS_SCHEMA = Path("schemas/us_equity_paper_simulation_readiness_report.schema.json")


def test_paper_simulation_readiness_report_rules_live_in_live_service() -> None:
    assert (
        build_us_equity_paper_simulation_readiness_report.__module__
        == "quant_us.live.paper_simulation_readiness_report"
    )


def test_manual_review_packet_stays_pending_until_upstream_complete(tmp_path: Path) -> None:
    paths = _write_upstream(tmp_path)

    payload = build_us_equity_manual_review_packet(
        repo_root=tmp_path,
        output=tmp_path / "manual.json",
        markdown_output=tmp_path / "manual.md",
        **paths,
        generated_at="2026-06-25T00:00:00Z",
    )

    assert payload["status"] == "manual_review_pending"
    assert payload["decision"] == "human_review_required"
    assert "us_equity_manual_review_strategy_validation_not_passed" in payload["blockers"]
    assert "us_equity_manual_review_forward_observation_not_complete" in payload["blockers"]
    assert "us_equity_manual_review_production_pit_intake_not_ready" in payload["blockers"]
    assert "us_equity_manual_review_pit_bundle_acceptance_not_ready" in payload["blockers"]
    assert payload["review_items"]["production_pit_data"]["intake_status"] == "production_pit_data_intake_blocked"
    assert payload["review_items"]["production_pit_data"]["acceptance_status"] == "acceptance_blocked"
    assert payload["guardrails"]["paper_simulation_allowed"] is False
    assert payload["guardrails"]["live_order_allowed"] is False
    assert (tmp_path / "manual.md").exists()


def test_paper_simulation_readiness_blocks_without_manual_approval(tmp_path: Path) -> None:
    paths = _write_upstream(tmp_path)
    manual = tmp_path / "manual.json"
    manual.write_text(
        json.dumps(
            {
                "status": "manual_review_ready",
                "checklist": [{"check_id": "forward_observation_continuity_passed", "passed": True}],
                "review_items": {"forward_observation": {"data_gate_blocked_count": 0, "continuity_passed": True}},
                "guardrails": {
                    "manual_approval_recorded": False,
                    "live_order_allowed": False,
                    "private_endpoint_allowed": False,
                    "order_endpoint_allowed": False,
                },
            }
        ),
        encoding="utf-8",
    )

    payload = build_us_equity_paper_simulation_readiness_report(
        repo_root=tmp_path,
        output=tmp_path / "paper.json",
        markdown_output=tmp_path / "paper.md",
        manual_review=manual,
        strategy_gate=paths["strategy_gate"],
        forward_evaluation=paths["forward_evaluation"],
        small_account_preflight=paths["small_account_preflight"],
        generated_at="2026-06-25T00:00:00Z",
    )

    assert payload["status"] == "paper_simulation_blocked"
    _validate_paper_schema(payload)
    assert payload["paper_runner_allowed"] is False
    assert "us_equity_paper_readiness_manual_approval_not_recorded" in payload["blockers"]
    gates = {item["gate_id"]: item for item in payload["paper_start_gate_matrix"]}
    assert gates["manual_review_ready"]["passed"] is True
    assert gates["manual_approval_recorded"]["passed"] is False
    assert gates["manual_approval_recorded"]["blocker"] == "us_equity_paper_readiness_manual_approval_not_recorded"
    assert gates["manual_decision_record_valid"]["passed"] is True
    assert gates["manual_decision_is_paper_candidate"]["passed"] is True
    assert gates["strategy_validation_passed"]["passed"] is False
    assert gates["forward_evaluation_complete"]["passed"] is False
    assert gates["small_account_preflight_pass"]["passed"] is True
    assert gates["unsafe_flags_absent"]["passed"] is True
    assert payload["required_runner_contract"]["must_not_reuse_forward_observation_ledger"] is True
    ledger_contract = payload["required_ledger_evidence_contract"]
    assert ledger_contract["ledger_root"] == "data/paper_ledger/us_equity_etf_rotation_v1"
    assert ledger_contract["forward_observation_source_only"] is True
    assert set(ledger_contract["required_files"]) == {
        "target_positions.jsonl",
        "fills.jsonl",
        "positions.jsonl",
        "cash_ledger.jsonl",
        "portfolio_snapshots.jsonl",
        "validation_state.json",
    }
    assert {"trade_reconciliation", "position_cash_consistency"} <= set(
        ledger_contract["required_reconciliation_checks"]
    )
    assert {"broker_order_id", "exchange_order_id", "simulated_only"} <= set(ledger_contract["required_fill_fields"])
    assert ledger_contract["simulated_fills_only"] is True
    assert ledger_contract["live_ready_claim_allowed"] is False
    assert payload["guardrails"]["order_endpoint_allowed"] is False


def test_paper_readiness_complete_manual_record_cannot_bypass_blocked_upstream(tmp_path: Path) -> None:
    paths = _write_upstream(tmp_path)
    manual = tmp_path / "manual-ready.json"
    manual.write_text(
        json.dumps(
            {
                "status": "manual_review_ready",
                "evidence_checklist": [
                    {"check_id": "forward_data_gate_no_blocked_runs", "passed": True},
                    {"check_id": "forward_observation_continuity_passed", "passed": True},
                ],
                "review_items": {
                    "forward_observation": {"data_gate_blocked_count": 0, "continuity_passed": True}
                },
                "guardrails": {
                    "manual_approval_recorded": True,
                    "live_order_allowed": False,
                    "private_endpoint_allowed": False,
                    "order_endpoint_allowed": False,
                },
            }
        ),
        encoding="utf-8",
    )

    payload = build_us_equity_paper_simulation_readiness_report(
        repo_root=tmp_path,
        output=tmp_path / "paper.json",
        markdown_output=tmp_path / "paper.md",
        manual_review=manual,
        manual_decision_record=paths["manual_decision_record"],
        strategy_gate=paths["strategy_gate"],
        forward_evaluation=paths["forward_evaluation"],
        small_account_preflight=paths["small_account_preflight"],
        production_pit_intake_status=paths["production_pit_intake_status"],
        pit_bundle_acceptance=paths["pit_bundle_acceptance"],
        blocker_taxonomy=tmp_path
        / "artifacts/us_equity_strategy_production_line/latest/us_equity_blocker_taxonomy_report.json",
        generated_at="2026-06-25T00:00:00Z",
    )

    _validate_paper_schema(payload)
    assert payload["status"] == "paper_simulation_blocked"
    assert payload["paper_runner_allowed"] is False
    assert "us_equity_paper_readiness_strategy_validation_not_passed" in payload["blockers"]
    assert "us_equity_paper_readiness_forward_evaluation_not_complete" in payload["blockers"]
    assert "us_equity_paper_readiness_production_pit_intake_not_ready" in payload["blockers"]
    assert payload["guardrails"]["live_order_allowed"] is False


def test_paper_simulation_readiness_malformed_source_fails_closed(tmp_path: Path) -> None:
    paths = _write_upstream(tmp_path)
    paths["strategy_gate"].write_text("{not-json", encoding="utf-8")

    payload = build_us_equity_paper_simulation_readiness_report(
        repo_root=tmp_path,
        output=tmp_path / "paper.json",
        markdown_output=tmp_path / "paper.md",
        manual_decision_record=paths["manual_decision_record"],
        strategy_gate=paths["strategy_gate"],
        forward_evaluation=paths["forward_evaluation"],
        small_account_preflight=paths["small_account_preflight"],
        production_pit_intake_status=paths["production_pit_intake_status"],
        pit_bundle_acceptance=paths["pit_bundle_acceptance"],
        generated_at="2026-06-25T00:00:00Z",
    )

    _validate_paper_schema(payload)
    assert payload["status"] == "paper_simulation_blocked"
    assert "us_equity_paper_readiness_strategy_validation_not_passed" in payload["blockers"]
    assert payload["paper_runner_allowed"] is False
    assert payload["guardrails"]["live_order_allowed"] is False


def test_paper_simulation_readiness_service_requires_manual_record_and_clean_upstream() -> None:
    reports = {
        "manual_review": {
            "status": "manual_review_ready",
            "evidence_checklist": [
                {"check_id": "forward_data_gate_no_blocked_runs", "passed": True},
                {"check_id": "forward_observation_continuity_passed", "passed": True},
            ],
            "guardrails": {"manual_approval_recorded": True},
        },
        "manual_decision_record": {
            "status": "manual_decision_record_valid",
            "record_summary": {
                "decision": "paper_simulation_review_candidate",
                "reviewer_recorded": True,
                "evidence_path_count": 2,
            },
            "evidence_path_details": [
                {"traceable_report_artifact": True},
                {"traceable_report_artifact": True},
            ],
        },
        "strategy_gate": {"status": "validation_passed_for_forward_observation"},
        "forward_evaluation": {"status": "forward_complete_for_manual_review", "metrics": {"observation_days": 30}},
        "small_account_preflight": {"status": "pass_observation_only"},
        "production_pit_intake_status": {"status": "production_pit_data_intake_ready"},
        "pit_bundle_acceptance": {"status": "acceptance_ready_for_manual_config_apply"},
        "blocker_taxonomy": {"status": "no_open_tickets", "remediation_tickets": []},
    }

    evaluation = evaluate_paper_simulation_readiness(reports)

    assert evaluation.status == "paper_simulation_ready_for_manual_start"
    assert evaluation.decision == "manual_start_required"
    assert evaluation.blockers == []
    assert evaluation.manual_review_evidence["manual_decision_traceable_evidence_path_count"] == 2
    assert evaluation.required_runner_contract["independent_ledger_root"] == "data/paper_ledger/us_equity_etf_rotation_v1"
    assert evaluation.required_ledger_evidence_contract["ledger_root"] == "data/paper_ledger/us_equity_etf_rotation_v1"
    assert "fills.jsonl" in evaluation.required_ledger_evidence_contract["required_files"]
    assert "snapshot_reconciliation" in evaluation.required_ledger_evidence_contract["required_reconciliation_checks"]
    assert evaluation.required_ledger_evidence_contract["broker_order_ids_must_be_absent"] is True
    assert evaluation.required_ledger_evidence_contract["live_ready_claim_allowed"] is False
    assert evaluation.guardrails["paper_simulation_allowed"] is False
    assert evaluation.guardrails["live_order_allowed"] is False

    unsafe_reports = dict(reports)
    unsafe_reports["strategy_gate"] = {"status": "validation_passed_for_forward_observation", "live_order_allowed": True}
    unsafe = evaluate_paper_simulation_readiness(unsafe_reports)
    assert unsafe.status == "paper_simulation_blocked"
    assert "us_equity_paper_readiness_unsafe_flag:strategy_gate.live_order_allowed=true" in unsafe.blockers

    untraceable_reports = dict(reports)
    untraceable_reports["manual_decision_record"] = {
        **reports["manual_decision_record"],
        "evidence_path_details": [{"traceable_report_artifact": False}],
    }
    untraceable = evaluate_paper_simulation_readiness(untraceable_reports)
    assert untraceable.status == "paper_simulation_blocked"
    assert "us_equity_paper_readiness_manual_decision_evidence_not_traceable" in untraceable.blockers


def test_paper_simulation_readiness_counts_manual_evidence_checklist(tmp_path: Path) -> None:
    paths = _write_upstream(tmp_path)
    manual = tmp_path / "manual.json"
    manual.write_text(
        json.dumps(
            {
                "status": "manual_review_ready",
                "evidence_checklist": [
                    {"check_id": "strategy_validation_gate_passed", "passed": False},
                    {"check_id": "forward_data_gate_no_blocked_runs", "passed": True},
                    {"check_id": "forward_observation_continuity_passed", "passed": True},
                ],
                "review_items": {"forward_observation": {"data_gate_blocked_count": 0, "continuity_passed": True}},
                "guardrails": {
                    "manual_approval_recorded": False,
                    "live_order_allowed": False,
                    "private_endpoint_allowed": False,
                    "order_endpoint_allowed": False,
                },
            }
        ),
        encoding="utf-8",
    )

    payload = build_us_equity_paper_simulation_readiness_report(
        repo_root=tmp_path,
        output=tmp_path / "paper.json",
        markdown_output=tmp_path / "paper.md",
        manual_review=manual,
        strategy_gate=paths["strategy_gate"],
        forward_evaluation=paths["forward_evaluation"],
        small_account_preflight=paths["small_account_preflight"],
        generated_at="2026-06-25T00:00:00Z",
    )

    _validate_paper_schema(payload)
    assert payload["manual_review_evidence"]["checklist_total"] == 3
    assert payload["manual_review_evidence"]["checklist_passed_count"] == 2
    assert payload["manual_review_evidence"]["manual_decision_record_status"] == "manual_decision_record_valid"
    assert payload["manual_review_evidence"]["manual_decision"] == "paper_simulation_review_candidate"
    assert payload["manual_review_evidence"]["manual_decision_traceable_evidence_path_count"] == 1
    assert payload["manual_review_evidence"]["forward_data_gate_no_blocked_runs"] is True
    assert payload["manual_review_evidence"]["forward_observation_continuity_passed"] is True


def test_paper_simulation_readiness_requires_clean_forward_data_gate_evidence(tmp_path: Path) -> None:
    paths = _write_upstream(tmp_path)
    paths["strategy_gate"].write_text(
        json.dumps({"status": "validation_passed_for_forward_observation", "guardrails": {"live_order_allowed": False}}),
        encoding="utf-8",
    )
    paths["forward_evaluation"].write_text(
        json.dumps({"status": "forward_complete_for_manual_review", "guardrails": {"live_order_allowed": False}}),
        encoding="utf-8",
    )
    manual = tmp_path / "manual.json"
    manual.write_text(
        json.dumps(
            {
                "status": "manual_review_ready",
                "checklist": [
                    {"check_id": "strategy_validation_passed", "passed": True},
                    {"check_id": "forward_observation_complete", "passed": True},
                    {"check_id": "forward_data_gate_no_blocked_runs", "passed": False},
                    {"check_id": "forward_observation_continuity_passed", "passed": True},
                ],
                "review_items": {"forward_observation": {"data_gate_blocked_count": 1, "continuity_passed": True}},
                "guardrails": {
                    "manual_approval_recorded": True,
                    "live_order_allowed": False,
                    "private_endpoint_allowed": False,
                    "order_endpoint_allowed": False,
                },
            }
        ),
        encoding="utf-8",
    )

    payload = build_us_equity_paper_simulation_readiness_report(
        repo_root=tmp_path,
        output=tmp_path / "paper.json",
        markdown_output=tmp_path / "paper.md",
        manual_review=manual,
        strategy_gate=paths["strategy_gate"],
        forward_evaluation=paths["forward_evaluation"],
        small_account_preflight=paths["small_account_preflight"],
        generated_at="2026-06-25T00:00:00Z",
    )

    assert payload["status"] == "paper_simulation_blocked"
    _validate_paper_schema(payload)
    assert payload["paper_runner_allowed"] is False
    assert "us_equity_paper_readiness_forward_data_gate_not_clean" in payload["blockers"]
    gates = {item["gate_id"]: item for item in payload["paper_start_gate_matrix"]}
    assert gates["forward_data_gate_clean"]["passed"] is False
    assert gates["forward_data_gate_clean"]["evidence"]["forward_data_gate_blocked_count"] == 1
    assert payload["manual_review_evidence"]["forward_data_gate_no_blocked_runs"] is False
    assert payload["manual_review_evidence"]["forward_data_gate_blocked_count"] == 1


def test_paper_simulation_readiness_requires_production_pit_intake_ready(tmp_path: Path) -> None:
    paths = _write_upstream(tmp_path)
    paths["strategy_gate"].write_text(
        json.dumps({"status": "validation_passed_for_forward_observation", "guardrails": {"live_order_allowed": False}}),
        encoding="utf-8",
    )
    paths["forward_evaluation"].write_text(
        json.dumps({"status": "forward_complete_for_manual_review", "guardrails": {"live_order_allowed": False}}),
        encoding="utf-8",
    )
    manual = tmp_path / "manual.json"
    manual.write_text(
        json.dumps(
            {
                "status": "manual_review_ready",
                "checklist": [
                    {"check_id": "forward_data_gate_no_blocked_runs", "passed": True},
                    {"check_id": "forward_observation_continuity_passed", "passed": True},
                ],
                "review_items": {"forward_observation": {"data_gate_blocked_count": 0, "continuity_passed": True}},
                "guardrails": {
                    "manual_approval_recorded": True,
                    "live_order_allowed": False,
                    "private_endpoint_allowed": False,
                    "order_endpoint_allowed": False,
                },
            }
        ),
        encoding="utf-8",
    )
    pit_status = tmp_path / "pit_status.json"
    pit_status.write_text(
        json.dumps({"status": "production_pit_data_intake_blocked", "blockers": ["source_dir_missing"], "guardrails": {"live_order_allowed": False}}),
        encoding="utf-8",
    )
    pit_acceptance = tmp_path / "pit_acceptance.json"
    pit_acceptance.write_text(
        json.dumps({"status": "acceptance_blocked", "blockers": ["source_dir_missing"], "guardrails": {"live_order_allowed": False}}),
        encoding="utf-8",
    )

    payload = build_us_equity_paper_simulation_readiness_report(
        repo_root=tmp_path,
        output=tmp_path / "paper.json",
        markdown_output=tmp_path / "paper.md",
        manual_review=manual,
        strategy_gate=paths["strategy_gate"],
        forward_evaluation=paths["forward_evaluation"],
        small_account_preflight=paths["small_account_preflight"],
        production_pit_intake_status=pit_status,
        pit_bundle_acceptance=pit_acceptance,
        generated_at="2026-06-25T00:00:00Z",
    )

    assert payload["status"] == "paper_simulation_blocked"
    _validate_paper_schema(payload)
    assert "us_equity_paper_readiness_production_pit_intake_not_ready" in payload["blockers"]
    assert "us_equity_paper_readiness_pit_bundle_acceptance_not_ready" in payload["blockers"]
    gates = {item["gate_id"]: item for item in payload["paper_start_gate_matrix"]}
    assert gates["production_pit_intake_ready"]["passed"] is False
    assert gates["pit_bundle_acceptance_ready"]["passed"] is False
    assert "production_pit_intake_status" in payload["source_reports"]
    assert "pit_bundle_acceptance" in payload["source_reports"]


def test_paper_simulation_readiness_requires_forward_continuity(tmp_path: Path) -> None:
    paths = _write_upstream(tmp_path)
    paths["strategy_gate"].write_text(
        json.dumps({"status": "validation_passed_for_forward_observation", "guardrails": {"live_order_allowed": False}}),
        encoding="utf-8",
    )
    paths["forward_evaluation"].write_text(
        json.dumps({"status": "forward_complete_for_manual_review", "guardrails": {"live_order_allowed": False}}),
        encoding="utf-8",
    )
    manual = tmp_path / "manual.json"
    manual.write_text(
        json.dumps(
            {
                "status": "manual_review_ready",
                "checklist": [
                    {"check_id": "forward_data_gate_no_blocked_runs", "passed": True},
                    {"check_id": "forward_observation_continuity_passed", "passed": False},
                ],
                "review_items": {"forward_observation": {"data_gate_blocked_count": 0, "continuity_passed": False}},
                "guardrails": {
                    "manual_approval_recorded": True,
                    "live_order_allowed": False,
                    "private_endpoint_allowed": False,
                    "order_endpoint_allowed": False,
                },
            }
        ),
        encoding="utf-8",
    )

    payload = build_us_equity_paper_simulation_readiness_report(
        repo_root=tmp_path,
        output=tmp_path / "paper.json",
        markdown_output=tmp_path / "paper.md",
        manual_review=manual,
        strategy_gate=paths["strategy_gate"],
        forward_evaluation=paths["forward_evaluation"],
        small_account_preflight=paths["small_account_preflight"],
        generated_at="2026-06-25T00:00:00Z",
    )

    assert payload["status"] == "paper_simulation_blocked"
    _validate_paper_schema(payload)
    assert "us_equity_paper_readiness_forward_observation_continuity_not_passed" in payload["blockers"]
    assert payload["manual_review_evidence"]["forward_observation_continuity_passed"] is False


def test_paper_simulation_readiness_requires_valid_manual_decision_record(tmp_path: Path) -> None:
    paths = _write_upstream(tmp_path, manual_decision_status="manual_decision_record_missing_or_invalid")
    paths["strategy_gate"].write_text(
        json.dumps({"status": "validation_passed_for_forward_observation", "guardrails": {"live_order_allowed": False}}),
        encoding="utf-8",
    )
    paths["forward_evaluation"].write_text(
        json.dumps({"status": "forward_complete_for_manual_review", "guardrails": {"live_order_allowed": False}}),
        encoding="utf-8",
    )
    manual = tmp_path / "manual.json"
    manual.write_text(
        json.dumps(
            {
                "status": "manual_review_ready",
                "checklist": [
                    {"check_id": "forward_data_gate_no_blocked_runs", "passed": True},
                    {"check_id": "forward_observation_continuity_passed", "passed": True},
                ],
                "review_items": {"forward_observation": {"data_gate_blocked_count": 0, "continuity_passed": True}},
                "guardrails": {
                    "manual_approval_recorded": True,
                    "live_order_allowed": False,
                    "private_endpoint_allowed": False,
                    "order_endpoint_allowed": False,
                },
            }
        ),
        encoding="utf-8",
    )

    payload = build_us_equity_paper_simulation_readiness_report(
        repo_root=tmp_path,
        output=tmp_path / "paper.json",
        markdown_output=tmp_path / "paper.md",
        manual_review=manual,
        manual_decision_record=paths["manual_decision_record"],
        strategy_gate=paths["strategy_gate"],
        forward_evaluation=paths["forward_evaluation"],
        small_account_preflight=paths["small_account_preflight"],
        generated_at="2026-06-25T00:00:00Z",
    )

    assert payload["status"] == "paper_simulation_blocked"
    _validate_paper_schema(payload)
    assert "us_equity_paper_readiness_manual_decision_record_not_valid" in payload["blockers"]
    gates = {item["gate_id"]: item for item in payload["paper_start_gate_matrix"]}
    assert gates["manual_approval_recorded"]["passed"] is True
    assert gates["manual_decision_record_valid"]["passed"] is False
    assert payload["manual_review_evidence"]["manual_decision_record_status"] == "manual_decision_record_missing_or_invalid"


def test_paper_simulation_readiness_requires_manual_decision_paper_candidate(tmp_path: Path) -> None:
    paths = _write_upstream(tmp_path, manual_decision="continue_observation")
    paths["strategy_gate"].write_text(
        json.dumps({"status": "validation_passed_for_forward_observation", "guardrails": {"live_order_allowed": False}}),
        encoding="utf-8",
    )
    paths["forward_evaluation"].write_text(
        json.dumps({"status": "forward_complete_for_manual_review", "guardrails": {"live_order_allowed": False}}),
        encoding="utf-8",
    )
    manual = tmp_path / "manual.json"
    manual.write_text(
        json.dumps(
            {
                "status": "manual_review_ready",
                "checklist": [
                    {"check_id": "forward_data_gate_no_blocked_runs", "passed": True},
                    {"check_id": "forward_observation_continuity_passed", "passed": True},
                ],
                "review_items": {"forward_observation": {"data_gate_blocked_count": 0, "continuity_passed": True}},
                "guardrails": {
                    "manual_approval_recorded": True,
                    "live_order_allowed": False,
                    "private_endpoint_allowed": False,
                    "order_endpoint_allowed": False,
                },
            }
        ),
        encoding="utf-8",
    )

    payload = build_us_equity_paper_simulation_readiness_report(
        repo_root=tmp_path,
        output=tmp_path / "paper.json",
        markdown_output=tmp_path / "paper.md",
        manual_review=manual,
        manual_decision_record=paths["manual_decision_record"],
        strategy_gate=paths["strategy_gate"],
        forward_evaluation=paths["forward_evaluation"],
        small_account_preflight=paths["small_account_preflight"],
        generated_at="2026-06-25T00:00:00Z",
    )

    assert payload["status"] == "paper_simulation_blocked"
    _validate_paper_schema(payload)
    assert "us_equity_paper_readiness_manual_decision_not_paper_candidate" in payload["blockers"]
    gates = {item["gate_id"]: item for item in payload["paper_start_gate_matrix"]}
    assert gates["manual_decision_record_valid"]["passed"] is True
    assert gates["manual_decision_is_paper_candidate"]["passed"] is False
    assert payload["manual_review_evidence"]["manual_decision"] == "continue_observation"


def test_paper_simulation_readiness_requires_closed_remediation_tickets(tmp_path: Path) -> None:
    paths = _write_upstream(tmp_path)
    paths["strategy_gate"].write_text(
        json.dumps({"status": "validation_passed_for_forward_observation", "guardrails": {"live_order_allowed": False}}),
        encoding="utf-8",
    )
    paths["forward_evaluation"].write_text(
        json.dumps({"status": "forward_complete_for_manual_review", "guardrails": {"live_order_allowed": False}}),
        encoding="utf-8",
    )
    blocker_taxonomy = tmp_path / "blocker_taxonomy.json"
    blocker_taxonomy.write_text(
        json.dumps(
            {
                "status": "blocked_external_and_time_dependencies",
                "remediation_tickets": [
                    {
                        "ticket_id": "us_equity_remediate_external_data",
                        "category": "external_data",
                        "owner": "operator_data_vendor",
                        "dependency_type": "external_user_action",
                        "status": "waiting_external_input",
                        "blocker_count": 3,
                        "source_reports": ["development_audit", "pit_handoff"],
                        "next_action": "Place production PIT files into the manual vendor drop.",
                        "acceptance_evidence": ["pit intake ready"],
                    }
                ],
                "guardrails": {"live_order_allowed": False},
            }
        ),
        encoding="utf-8",
    )
    manual = tmp_path / "manual.json"
    manual.write_text(
        json.dumps(
            {
                "status": "manual_review_ready",
                "checklist": [
                    {"check_id": "forward_data_gate_no_blocked_runs", "passed": True},
                    {"check_id": "forward_observation_continuity_passed", "passed": True},
                ],
                "review_items": {"forward_observation": {"data_gate_blocked_count": 0, "continuity_passed": True}},
                "guardrails": {
                    "manual_approval_recorded": True,
                    "live_order_allowed": False,
                    "private_endpoint_allowed": False,
                    "order_endpoint_allowed": False,
                },
            }
        ),
        encoding="utf-8",
    )

    payload = build_us_equity_paper_simulation_readiness_report(
        repo_root=tmp_path,
        output=tmp_path / "paper.json",
        markdown_output=tmp_path / "paper.md",
        manual_review=manual,
        strategy_gate=paths["strategy_gate"],
        forward_evaluation=paths["forward_evaluation"],
        small_account_preflight=paths["small_account_preflight"],
        blocker_taxonomy=blocker_taxonomy,
        generated_at="2026-06-25T00:00:00Z",
    )

    assert payload["status"] == "paper_simulation_blocked"
    _validate_paper_schema(payload)
    assert "us_equity_paper_readiness_remediation_tickets_open" in payload["blockers"]
    assert payload["remediation_tickets"]["ticket_count"] == 1
    assert payload["remediation_tickets"]["external_or_time_dependency_count"] == 1


def test_monitoring_rules_define_required_sections_without_unlocking_trading(tmp_path: Path) -> None:
    payload = build_us_equity_monitoring_rules_report(
        repo_root=tmp_path,
        output=tmp_path / "monitor.json",
        markdown_output=tmp_path / "monitor.md",
        generated_at="2026-06-25T00:00:00Z",
    )

    assert payload["status"] == "monitoring_rules_defined"
    assert payload["required_before_paper_or_live"] is True
    assert "data_monitors" in payload["rules"]
    assert "attribution" in payload["rules"]
    assert "retirement_rules" in payload["rules"]
    assert payload["guardrails"]["paper_simulation_allowed"] is False
    assert payload["guardrails"]["live_order_allowed"] is False
    assert (tmp_path / "monitor.md").exists()


def test_paper_simulation_readiness_schema_rejects_runner_allowed(tmp_path: Path) -> None:
    paths = _write_upstream(tmp_path)
    manual = tmp_path / "manual.json"
    manual.write_text(
        json.dumps(
            {
                "status": "manual_review_ready",
                "checklist": [{"check_id": "forward_observation_continuity_passed", "passed": True}],
                "review_items": {"forward_observation": {"data_gate_blocked_count": 0, "continuity_passed": True}},
                "guardrails": {
                    "manual_approval_recorded": False,
                    "live_order_allowed": False,
                    "private_endpoint_allowed": False,
                    "order_endpoint_allowed": False,
                },
            }
        ),
        encoding="utf-8",
    )
    payload = build_us_equity_paper_simulation_readiness_report(
        repo_root=tmp_path,
        output=tmp_path / "paper.json",
        markdown_output=tmp_path / "paper.md",
        manual_review=manual,
        strategy_gate=paths["strategy_gate"],
        forward_evaluation=paths["forward_evaluation"],
        small_account_preflight=paths["small_account_preflight"],
        generated_at="2026-06-25T00:00:00Z",
    )
    payload["paper_runner_allowed"] = True

    schema = json.loads(PAPER_READINESS_SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError:
        return
    raise AssertionError("schema accepted paper_runner_allowed=true")


def _write_upstream(
    tmp_path: Path,
    *,
    manual_decision_status: str = "manual_decision_record_valid",
    manual_decision: str = "paper_simulation_review_candidate",
) -> dict[str, Path]:
    strategy_gate = tmp_path / "strategy_gate.json"
    forward_evaluation = tmp_path / "forward_eval.json"
    data_freshness = tmp_path / "freshness.json"
    small_account_preflight = tmp_path / "small_account.json"
    live_readiness = tmp_path / "live.json"
    manual_decision_record = tmp_path / "artifacts/us_equity_etf_macro_rotation/latest/us_equity_manual_decision_record_report.json"
    production_pit_intake_status = tmp_path / "pit_status.json"
    pit_bundle_acceptance = tmp_path / "pit_acceptance.json"
    blocker_taxonomy = tmp_path / "artifacts/us_equity_strategy_production_line/latest/us_equity_blocker_taxonomy_report.json"
    strategy_gate.write_text(
        json.dumps({"status": "blocked_data_quality", "live_order_allowed": False, "paper_simulation_allowed": False}),
        encoding="utf-8",
    )
    forward_evaluation.write_text(
        json.dumps({"status": "forward_observing", "metrics": {"observation_days": 1}, "guardrails": {"live_order_allowed": False}}),
        encoding="utf-8",
    )
    data_freshness.write_text(json.dumps({"status": "blocked", "guardrails": {"live_order_allowed": False}}), encoding="utf-8")
    small_account_preflight.write_text(json.dumps({"status": "pass_observation_only", "guardrails": {"live_order_allowed": False}}), encoding="utf-8")
    live_readiness.write_text(json.dumps({"status": "live_readiness_blocked", "guardrails": {"live_order_allowed": False}}), encoding="utf-8")
    manual_decision_record.parent.mkdir(parents=True, exist_ok=True)
    manual_decision_record.write_text(
        json.dumps(
            {
                "status": manual_decision_status,
                "record_summary": {
                    "decision": manual_decision,
                    "reviewer_recorded": manual_decision_status == "manual_decision_record_valid",
                    "evidence_path_count": 1 if manual_decision_status == "manual_decision_record_valid" else 0,
                },
                "evidence_path_details": (
                    [{"traceable_report_artifact": True}]
                    if manual_decision_status == "manual_decision_record_valid"
                    else []
                ),
                "guardrails": {
                    "paper_or_live_unlock_allowed": False,
                    "paper_simulation_allowed": False,
                    "live_order_allowed": False,
                },
            }
        ),
        encoding="utf-8",
    )
    production_pit_intake_status.write_text(
        json.dumps(
            {
                "status": "production_pit_data_intake_blocked",
                "current_blocking_stage": "incoming_drop_readiness",
                "blockers": ["source_dir_missing"],
                "guardrails": {"live_order_allowed": False},
            }
        ),
        encoding="utf-8",
    )
    pit_bundle_acceptance.write_text(
        json.dumps(
            {
                "status": "acceptance_blocked",
                "current_blocking_step": "incoming_drop_readiness",
                "blockers": ["source_dir_missing"],
                "guardrails": {"live_order_allowed": False},
            }
        ),
        encoding="utf-8",
    )
    blocker_taxonomy.parent.mkdir(parents=True, exist_ok=True)
    blocker_taxonomy.write_text(
        json.dumps({"status": "no_blockers_detected", "remediation_tickets": [], "guardrails": {"live_order_allowed": False}}),
        encoding="utf-8",
    )
    return {
        "strategy_gate": strategy_gate,
        "forward_evaluation": forward_evaluation,
        "data_freshness": data_freshness,
        "small_account_preflight": small_account_preflight,
        "live_readiness": live_readiness,
        "manual_decision_record": manual_decision_record,
        "production_pit_intake_status": production_pit_intake_status,
        "pit_bundle_acceptance": pit_bundle_acceptance,
    }


def _validate_paper_schema(payload: dict[str, object]) -> None:
    schema = json.loads(PAPER_READINESS_SCHEMA.read_text(encoding="utf-8"))
    jsonschema.validate(payload, schema)
