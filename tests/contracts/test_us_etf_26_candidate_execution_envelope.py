from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import jsonschema

from quant_us.live.us_etf_26_candidate_execution_envelope import (
    FALSE_GUARDRAILS,
    _reconcile,
    _run_local_fake_oms_behavior_drill,
    analyze_candidate_execution_envelope,
)


ROOT = Path(__file__).resolve().parents[2]
SCHEMA = ROOT / "schemas/us_etf_26_candidate_execution_envelope_report.schema.json"


def test_local_scenario_matrix_reconciliation_and_uow() -> None:
    evidence = _analysis()
    report = evidence["report"]
    scenarios = {row["scenario_id"]: row for row in report["execution_drill"]["scenarios"]}
    assert len(scenarios) == 20
    assert all(row["status"] == "pass_local_fixture" for row in scenarios.values())
    assert report["execution_drill"]["behavior_source"] == "local_fixture_oms_observed_state_transitions"
    for required in ("partial_fill", "reject", "cancel", "timeout_unknown_outcome", "duplicate_callback", "duplicate_submit", "restart_recovery", "local_fixture_state_reconciliation", "market_calendar_session_boundary", "market_closed", "stale_data", "broker_outage", "kill_switch", "cancel_only", "reduce_only", "no_new_risk", "paper_ledger_uow_atomic_rollback"):
        assert required in scenarios
        assert scenarios[required]["behavior_assertion_passed"] is True
        assert scenarios[required]["observations"]
    assert report["reconciliation"]["passed"] is True
    assert report["reconciliation"]["local_fixture_state_reconciliation"] == "passed"
    assert report["reconciliation"]["broker_state_reconciliation"] == "unproven"
    assert report["reconciliation"]["paper_state_reconciliation"] == "blocked_unproven"
    assert report["reconciliation"]["order_fill_quantity_delta"] == 0.0
    assert report["reconciliation"]["fill_position_quantity_delta"] == 0.0
    assert abs(report["reconciliation"]["fill_cash_balance_delta"]) <= 1e-8
    assert report["paper_ledger_uow"]["commit_operation_count"] == 7
    assert report["paper_ledger_uow"]["rollback_succeeded"] is True


def test_reconciliation_fails_on_duplicate_fill_and_ledger_tamper() -> None:
    evidence = _analysis()
    report = evidence["report"]
    duplicate_fills = [dict(row) for row in evidence["fills"]] + [dict(evidence["fills"][0])]
    duplicate = _reconcile(
        evidence["orders"],
        duplicate_fills,
        evidence["positions"],
        evidence["cash"],
        100000.0,
        evidence["lifecycle"],
    )
    assert duplicate["passed"] is False
    assert duplicate["duplicate_fill_id_count"] == 1

    tampered_positions = [dict(row) for row in evidence["positions"]]
    tampered_positions[0]["quantity"] += 1.0
    position_result = _reconcile(
        evidence["orders"], evidence["fills"], tampered_positions, evidence["cash"], 100000.0, evidence["lifecycle"]
    )
    assert position_result["passed"] is False
    assert position_result["position_chain_max_delta"] == 1.0

    tampered_cash = [dict(row) for row in evidence["cash"]]
    tampered_cash[1]["balance"] += 1.0
    cash_result = _reconcile(
        evidence["orders"], evidence["fills"], evidence["positions"], tampered_cash, 100000.0, evidence["lifecycle"]
    )
    assert cash_result["passed"] is False
    assert cash_result["cash_chain_max_delta"] == 1.0


def test_lifecycle_tamper_blocks_behavior_replay_and_restart_is_observed() -> None:
    evidence = _analysis()
    tampered = [dict(row) for row in evidence["lifecycle"]]
    tampered[1]["event_type"] = "filled"
    behavior = _run_local_fake_oms_behavior_drill(
        evidence["orders"],
        evidence["fills"],
        tampered,
        evidence["reconciliation"],
        evidence["paper_ledger_uow"],
        _config(),
    )
    scenarios = {row["scenario_id"]: row for row in behavior["scenarios"]}
    assert scenarios["append_only_order_lifecycle"]["status"] == "blocked"
    assert scenarios["restart_recovery"]["observations"]["state_hash_match"] is True


def test_execution_metrics_and_audit_fields() -> None:
    evidence = _analysis()
    quality = evidence["report"]["execution_quality"]
    assert quality["fill_rate"] == round(16.0 / 27.0, 8)
    assert quality["implementation_shortfall_usd"] == 1.83
    assert quality["commission_usd"] == 0.17
    assert len(evidence["orders"]) == 4
    assert len(evidence["fills"]) == 3
    assert len(evidence["positions"]) == 3
    assert len(evidence["cash"]) == 4
    required = {"run_id", "strategy_id", "candidate_id", "data_version", "decision_time", "signal", "forecast", "target_position", "risk_decision", "order_id", "fill_id", "error_code"}
    assert all(required <= set(row) for row in evidence["lifecycle"])


def test_credential_contract_and_paper_envelope_fail_closed() -> None:
    report = _analysis()["report"]
    contract = report["broker_credential_metadata_contract"]
    readiness = report["paper_simulation_readiness"]
    assert contract["status"] == "blocked_missing_human_review"
    assert set(contract["allowed_metadata_fields"]) == {"broker_name", "account_hash", "reviewer", "review_time", "approval_ticket", "funding_source_external_confirmation", "permission_conclusion"}
    assert all(value is None for value in contract["metadata"].values())
    assert contract["secret_value_present"] is False
    assert contract["secret_path_present"] is False
    assert readiness["status"] == "paper_simulation_blocked_fail_closed"
    assert "manual_broker_credential_review_missing" in readiness["blockers"]
    assert "production_pit_intake_blocked_external_data" in readiness["blockers"]
    assert "portfolio_promotion_evidence_blocked" in readiness["blockers"]
    assert "broker_state_reconciliation_unproven" in readiness["blockers"]
    assert "paper_state_reconciliation_blocked_unproven" in readiness["blockers"]
    assert all(report["guardrails"][name] is False for name in FALSE_GUARDRAILS)


def test_current_main_candidate_execution_fixture_contract() -> None:
    evidence = _analysis()
    report = evidence["report"]
    jsonschema.validate(report, json.loads(SCHEMA.read_text(encoding="utf-8")))
    assert report["code_commit"] == "a" * 40
    assert report["portfolio_dependency"]["run_id"] == "us-etf26-portfolio-84555a2ad906db2d"
    assert report["portfolio_dependency"]["manifest_sha256"] == "c" * 64
    assert report["portfolio_dependency"]["report_sha256"] == "d" * 64
    assert report["execution_drill"]["passed_count"] == 20
    assert report["paper_simulation_readiness"]["status"] == "paper_simulation_blocked_fail_closed"
    assert all(report["guardrails"][name] is False for name in FALSE_GUARDRAILS)


def test_schema_rejects_paper_order_unlock() -> None:
    report = _analysis()["report"]
    report["guardrails"]["paper_order_allowed"] = True
    try:
        jsonschema.validate(report, json.loads(SCHEMA.read_text(encoding="utf-8")))
    except jsonschema.ValidationError:
        return
    raise AssertionError("schema accepted paper_order_allowed=true")


def test_builder_help_imports_service() -> None:
    completed = subprocess.run([sys.executable, "scripts/build_us_etf_26_candidate_execution_envelope.py", "--help"], cwd=ROOT, check=False, capture_output=True, text=True, encoding="utf-8")
    assert completed.returncode == 0, completed.stderr
    assert "local-only ETF26 candidate execution" in completed.stdout


def _analysis() -> dict[str, object]:
    return analyze_candidate_execution_envelope(
        config=_config(),
        portfolio_pointer={
            "run_id": "us-etf26-portfolio-84555a2ad906db2d",
            "code_commit": "b" * 40,
            "manifest_sha256": "c" * 64,
            "report_sha256": "d" * 64,
            "status": "engineering_evidence_complete_promotion_blocked",
        },
        portfolio_report={
            "data": {"data_version": "fixture-data-v1"},
            "blockers": ["production_pit_bundle_missing:corporate_actions"],
        },
        code_commit="a" * 40,
        code_tree_hash="e" * 40,
        generated_at="2026-07-13T00:00:00+00:00",
        config_sha256="f" * 64,
        portfolio_pointer_sha256="1" * 64,
    )


def _config() -> dict[str, object]:
    return {
        "candidate_id": "us-etf26-complete-return-qqq-1d-v1",
        "strategy_id": "us-etf26-complete-return-qqq-1d-v1",
        "initial_cash": 100000.0,
        "fixture_market_calendar": {"weekend_closed": True},
    }
