from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from quant_us.live.execution_drill_evidence import (
    evaluate_execution_drill_evidence,
    oms_exception_blockers,
    oms_exception_drill_proven,
    oms_exception_scenarios,
    validate_oms_exception_scenario,
)
from scripts.build_us_equity_execution_drill_evidence_report import (
    build_us_equity_execution_drill_evidence_report,
)


SCHEMA = Path("schemas/us_equity_execution_drill_evidence_report.schema.json")


def test_oms_exception_service_fails_closed_on_unsafe_scenario() -> None:
    unsafe = validate_oms_exception_scenario(
        {
            "scenario_id": "broker_outage_no_duplicate_retry",
            "broker_submit_attempted": True,
            "order_created": True,
            "simulated_fill_created": True,
            "idempotency_key_required": False,
            "blockers": [],
        }
    )
    assert unsafe["passed"] is False
    assert "oms_exception_broker_submit_attempted" in unsafe["blockers"]
    assert "oms_exception_order_created" in unsafe["blockers"]
    assert "oms_exception_fill_created" in unsafe["blockers"]
    assert "oms_exception_idempotency_key_missing" in unsafe["blockers"]
    assert oms_exception_drill_proven([unsafe]) is False
    assert "oms_exception_broker_submit_attempted" in oms_exception_blockers([unsafe])

    scenarios = oms_exception_scenarios()
    assert oms_exception_drill_proven(scenarios) is True
    assert {item["scenario_id"] for item in scenarios} == {
        "broker_reject_structured_error",
        "cancel_pending_not_assumed_cancelled",
        "duplicate_submit_idempotency",
        "market_closed_reject",
        "broker_outage_no_duplicate_retry",
        "partial_fill_remaining_qty_recomputed",
        "reconciliation_break_halts_new_orders",
    }


def test_oms_exception_service_fails_closed_on_incomplete_lifecycle_evidence() -> None:
    cancel = validate_oms_exception_scenario(
        {
            "scenario_id": "cancel_pending_not_assumed_cancelled",
            "broker_submit_attempted": False,
            "order_created": False,
            "simulated_fill_created": False,
            "cancel_request_recorded": False,
            "cancel_confirmation_required": False,
            "cancelled_assumed_without_confirmation": True,
            "blockers": [],
        }
    )
    partial = validate_oms_exception_scenario(
        {
            "scenario_id": "partial_fill_remaining_qty_recomputed",
            "broker_submit_attempted": False,
            "order_created": False,
            "simulated_fill_created": False,
            "partial_fill_recorded": True,
            "remaining_quantity_recomputed": False,
            "cash_position_reconciliation_required": False,
            "blockers": [],
        }
    )
    reconciliation = validate_oms_exception_scenario(
        {
            "scenario_id": "reconciliation_break_halts_new_orders",
            "broker_submit_attempted": False,
            "order_created": False,
            "simulated_fill_created": False,
            "reconciliation_break_detected": True,
            "new_orders_blocked": False,
            "incident_review_required": False,
            "blockers": [],
        }
    )

    assert cancel["passed"] is False
    assert "oms_exception_cancel_request_missing" in cancel["blockers"]
    assert "oms_exception_cancel_assumed_without_confirmation" in cancel["blockers"]
    assert partial["passed"] is False
    assert "oms_exception_remaining_quantity_not_recomputed" in partial["blockers"]
    assert reconciliation["passed"] is False
    assert "oms_exception_new_orders_not_blocked_on_reconciliation_break" in reconciliation["blockers"]


def test_execution_drill_service_completes_without_unlocking_paper_or_live() -> None:
    reports = _service_reports(
        broker_review_status="broker_credentials_review_proven",
        small_account_pass=True,
        monitoring_pass=True,
        order_reconciliation_status="order_reconciliation_drill_proven",
        kill_switch_status="kill_switch_drill_proven",
    )

    evaluation = evaluate_execution_drill_evidence(reports)

    assert evaluation.status == "execution_drill_evidence_complete"
    assert evaluation.drill_count == 5
    assert evaluation.proven_count == 5
    assert evaluation.blocked_count == 0
    assert evaluation.blockers == []
    assert evaluation.broker_credentials_evidence["broker_credentials_proven"] is True
    assert evaluation.broker_credentials_evidence["credential_review_can_unlock_paper_or_live"] is False
    assert evaluation.broker_credentials_evidence["credential_review_contains_secret_values"] is False
    assert evaluation.broker_credentials_evidence["live_order_allowed"] is False
    for scenario in evaluation.oms_exception_scenarios:
        assert scenario["broker_submit_attempted"] is False
        assert scenario["order_created"] is False
        assert scenario["simulated_fill_created"] is False
    coverage = {item["scenario_id"]: item for item in evaluation.oms_exception_coverage_matrix}
    assert set(coverage) == {
        "broker_reject_structured_error",
        "cancel_pending_not_assumed_cancelled",
        "duplicate_submit_idempotency",
        "market_closed_reject",
        "broker_outage_no_duplicate_retry",
        "partial_fill_remaining_qty_recomputed",
        "reconciliation_break_halts_new_orders",
    }
    assert {item["coverage_status"] for item in coverage.values()} == {"complete"}
    assert all(item["broker_submit_attempted"] is False for item in coverage.values())


def test_execution_drill_service_blocks_unsafe_broker_review_flags() -> None:
    reports = _service_reports(
        broker_review_status="broker_credentials_review_proven",
        small_account_pass=True,
        monitoring_pass=True,
        order_reconciliation_status="order_reconciliation_drill_proven",
        kill_switch_status="kill_switch_drill_proven",
    )
    reports["broker_credentials_review"]["guardrails"]["live_order_allowed"] = True

    evaluation = evaluate_execution_drill_evidence(reports)

    assert evaluation.status == "execution_drill_evidence_partial"
    assert evaluation.proven_count == 5
    assert "broker_credentials_review_live_order_allowed_true" in evaluation.blockers
    drills = {item["drill_id"]: item for item in evaluation.drills}
    assert "broker_credentials_review" not in drills


def test_execution_drill_service_blocks_proven_broker_review_with_invalid_account_hash() -> None:
    reports = _service_reports(
        broker_review_status="broker_credentials_review_proven",
        small_account_pass=True,
        monitoring_pass=True,
        order_reconciliation_status="order_reconciliation_drill_proven",
        kill_switch_status="kill_switch_drill_proven",
    )
    reports["broker_credentials_review"]["review_summary"]["account_id_hash_format_ok"] = False
    reports["broker_credentials_review"]["review_summary"]["raw_account_id_pattern_detected"] = True

    evaluation = evaluate_execution_drill_evidence(reports)

    assert evaluation.status == "execution_drill_evidence_partial"
    assert "broker_credentials_review_account_id_hash_format_not_ok" in evaluation.blockers
    assert "broker_credentials_review_raw_account_id_pattern_detected" in evaluation.blockers
    assert evaluation.broker_credentials_evidence["account_id_hash_format_ok"] is False
    assert evaluation.broker_credentials_evidence["raw_account_id_pattern_detected"] is True


def test_execution_drill_evidence_partially_proves_simulated_preflight_and_monitoring(tmp_path: Path) -> None:
    _write_sources(
        tmp_path,
        broker_review_status="missing",
        small_account_pass=True,
        monitoring_pass=True,
        order_reconciliation_status="order_reconciliation_drill_proven",
        kill_switch_status="kill_switch_drill_partial",
    )

    payload = build_us_equity_execution_drill_evidence_report(
        repo_root=tmp_path,
        output=Path("out/execution_drills.json"),
        markdown_output=Path("out/execution_drills.md"),
        generated_at="2026-06-27T00:00:00Z",
    )

    _validate_schema(payload)
    assert payload["status"] == "execution_drill_evidence_partial"
    assert payload["drill_count"] == 5
    assert payload["proven_count"] == 4
    assert payload["blocked_count"] == 1
    drills = {item["drill_id"]: item for item in payload["drills"]}
    assert drills["margin_financing_share_rounding_preflight"]["status"] == "proven"
    assert drills["monitoring_alerting_drill"]["status"] == "proven"
    assert drills["oms_exception_drill"]["status"] == "proven"
    assert "broker_credentials_review" not in drills
    assert drills["order_reconciliation_drill"]["status"] == "proven"
    assert drills["kill_switch_drill"]["status"] == "blocked"
    assert "manual_stop_reset_drill_not_proven" in drills["kill_switch_drill"]["blockers"]
    assert payload["broker_credentials_evidence"]["status"] == ""
    assert payload["broker_credentials_evidence"]["broker_credentials_proven"] is False
    assert payload["broker_credentials_evidence"]["template_safe_defaults_present"] is False
    _assert_oms_exception_scenarios(payload)
    assert payload["guardrails"]["live_order_allowed"] is False
    assert payload["guardrails"]["order_endpoint_allowed"] is False
    assert payload["guardrails"]["broker_calls_used"] is False
    assert (tmp_path / "out/execution_drills.json").exists()
    assert (tmp_path / "out/execution_drills.md").exists()


def test_execution_drill_evidence_blocks_when_simulated_inputs_missing(tmp_path: Path) -> None:
    _write_sources(
        tmp_path,
        broker_review_status="missing",
        small_account_pass=False,
        monitoring_pass=False,
        order_reconciliation_status="missing",
        kill_switch_status="missing",
    )

    payload = build_us_equity_execution_drill_evidence_report(
        repo_root=tmp_path,
        output=Path("out/execution_drills.json"),
        markdown_output=Path("out/execution_drills.md"),
        generated_at="2026-06-27T00:00:00Z",
    )

    _validate_schema(payload)
    assert payload["status"] == "execution_drill_evidence_partial"
    assert payload["proven_count"] == 1
    assert payload["blocked_count"] == 4
    assert "small_account_execution_preflight_not_proven" in payload["blockers"]
    assert "monitoring_alerting_drill_not_proven" in payload["blockers"]
    assert "order_reconciliation_drill_not_proven" in payload["blockers"]
    coverage = {item["scenario_id"]: item for item in payload["oms_exception_coverage_matrix"]}
    assert {item["coverage_status"] for item in coverage.values()} == {"policy_only"}
    assert all(item["order_reconciliation_matrix_present"] is False for item in coverage.values())
    assert "order_reconciliation_matrix_scenario_missing:broker_reject_structured_error" in coverage[
        "broker_reject_structured_error"
    ]["blockers"]


def test_execution_drill_evidence_blocks_order_reconciliation_when_recompute_missing(tmp_path: Path) -> None:
    _write_sources(
        tmp_path,
        broker_review_status="missing",
        small_account_pass=True,
        monitoring_pass=True,
        order_reconciliation_status="order_reconciliation_drill_blocked",
        kill_switch_status="kill_switch_drill_partial",
    )

    payload = build_us_equity_execution_drill_evidence_report(
        repo_root=tmp_path,
        output=Path("out/execution_drills.json"),
        markdown_output=Path("out/execution_drills.md"),
        generated_at="2026-06-27T00:00:00Z",
    )

    _validate_schema(payload)
    drills = {item["drill_id"]: item for item in payload["drills"]}
    assert drills["order_reconciliation_drill"]["status"] == "blocked"
    assert "order_reconciliation_recompute_failed" in payload["blockers"]


def test_execution_drill_evidence_marks_kill_switch_proven_only_when_fully_proven(tmp_path: Path) -> None:
    _write_sources(
        tmp_path,
        broker_review_status="missing",
        small_account_pass=True,
        monitoring_pass=True,
        order_reconciliation_status="order_reconciliation_drill_proven",
        kill_switch_status="kill_switch_drill_proven",
    )

    payload = build_us_equity_execution_drill_evidence_report(
        repo_root=tmp_path,
        output=Path("out/execution_drills.json"),
        markdown_output=Path("out/execution_drills.md"),
        generated_at="2026-06-27T00:00:00Z",
    )

    _validate_schema(payload)
    drills = {item["drill_id"]: item for item in payload["drills"]}
    assert drills["kill_switch_drill"]["status"] == "proven"
    assert drills["order_reconciliation_drill"]["status"] == "proven"
    assert payload["status"] == "execution_drill_evidence_complete"
    assert payload["proven_count"] == 5
    assert payload["blocked_count"] == 0


def test_execution_drill_evidence_complete_when_broker_review_proven(tmp_path: Path) -> None:
    _write_sources(
        tmp_path,
        broker_review_status="broker_credentials_review_proven",
        small_account_pass=True,
        monitoring_pass=True,
        order_reconciliation_status="order_reconciliation_drill_proven",
        kill_switch_status="kill_switch_drill_proven",
    )

    payload = build_us_equity_execution_drill_evidence_report(
        repo_root=tmp_path,
        output=Path("out/execution_drills.json"),
        markdown_output=Path("out/execution_drills.md"),
        generated_at="2026-06-27T00:00:00Z",
    )

    _validate_schema(payload)
    assert payload["status"] == "execution_drill_evidence_complete"
    assert payload["proven_count"] == 5
    assert payload["blocked_count"] == 0
    assert payload["blockers"] == []
    assert payload["broker_credentials_evidence"]["read_only_or_live_disabled"] is True
    assert payload["broker_credentials_evidence"]["broker_credentials_proven"] is True
    assert payload["broker_credentials_evidence"]["order_permission_enabled"] is False
    assert payload["broker_credentials_evidence"]["template_safe_defaults_present"] is True
    assert payload["broker_credentials_evidence"]["review_evidence_classification"] == "manual_review_metadata_only"
    assert payload["broker_credentials_evidence"]["credential_review_can_unlock_paper_or_live"] is False
    assert payload["broker_credentials_evidence"]["credential_review_contains_secret_values"] is False
    _assert_oms_exception_scenarios(payload)


def test_execution_drill_evidence_schema_rejects_live_order_allowed(tmp_path: Path) -> None:
    _write_sources(
        tmp_path,
        broker_review_status="missing",
        small_account_pass=True,
        monitoring_pass=True,
        order_reconciliation_status="order_reconciliation_drill_proven",
        kill_switch_status="kill_switch_drill_partial",
    )
    payload = build_us_equity_execution_drill_evidence_report(
        repo_root=tmp_path,
        output=Path("out/execution_drills.json"),
        markdown_output=Path("out/execution_drills.md"),
        generated_at="2026-06-27T00:00:00Z",
    )
    payload["guardrails"]["live_order_allowed"] = True

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError:
        return
    raise AssertionError("schema accepted live_order_allowed=true")


def test_execution_drill_evidence_schema_rejects_credential_review_unlock(tmp_path: Path) -> None:
    _write_sources(
        tmp_path,
        broker_review_status="broker_credentials_review_proven",
        small_account_pass=True,
        monitoring_pass=True,
        order_reconciliation_status="order_reconciliation_drill_proven",
        kill_switch_status="kill_switch_drill_proven",
    )
    payload = build_us_equity_execution_drill_evidence_report(
        repo_root=tmp_path,
        output=Path("out/execution_drills.json"),
        markdown_output=Path("out/execution_drills.md"),
        generated_at="2026-06-27T00:00:00Z",
    )
    payload["broker_credentials_evidence"]["credential_review_can_unlock_paper_or_live"] = True

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError:
        return
    raise AssertionError("schema accepted credential_review_can_unlock_paper_or_live=true")


def _write_sources(
    tmp_path: Path,
    *,
    broker_review_status: str,
    small_account_pass: bool,
    monitoring_pass: bool,
    order_reconciliation_status: str,
    kill_switch_status: str,
) -> None:
    if broker_review_status != "missing":
        _write_json(
            tmp_path / "artifacts/us_equity_etf_macro_rotation/latest/us_equity_broker_credentials_review_report.json",
            _broker_review_payload(broker_review_status),
        )
    _write_json(
        tmp_path / "artifacts/us_equity_etf_macro_rotation/latest/us_etf_small_account_execution_preflight_report.json",
        _small_account_payload(small_account_pass),
    )
    _write_json(
        tmp_path / "artifacts/us_equity_etf_macro_rotation/latest/us_equity_monitoring_rules_report.json",
        _monitoring_payload(monitoring_pass),
    )
    if kill_switch_status != "missing":
        _write_json(
            tmp_path / "artifacts/us_equity_etf_macro_rotation/latest/us_equity_kill_switch_drill_report.json",
            _kill_switch_payload(kill_switch_status),
        )
    if order_reconciliation_status != "missing":
        _write_json(
            tmp_path / "artifacts/us_equity_etf_macro_rotation/latest/us_equity_order_reconciliation_drill_report.json",
            _order_reconciliation_payload(order_reconciliation_status),
        )
    _write_json(
        tmp_path / "artifacts/us_equity_etf_macro_rotation/latest/us_equity_paper_simulation_readiness_report.json",
        {"status": "paper_simulation_blocked", "guardrails": {"live_order_allowed": False}},
    )
    _write_json(
        tmp_path / "artifacts/us_equity_etf_macro_rotation/latest/us_etf_forward_observation_evaluation_report.json",
        {"status": "forward_observing", "guardrails": {"live_order_allowed": False}},
    )
    _write_json(
        tmp_path / "artifacts/us_equity_etf_macro_rotation/latest/us_equity_live_readiness_report.json",
        {"status": "live_readiness_blocked", "guardrails": {"live_order_allowed": False}},
    )


def _service_reports(
    *,
    broker_review_status: str,
    small_account_pass: bool,
    monitoring_pass: bool,
    order_reconciliation_status: str,
    kill_switch_status: str,
) -> dict[str, dict[str, object]]:
    return {
        "broker_credentials_review": _broker_review_payload(broker_review_status),
        "small_account_preflight": _small_account_payload(small_account_pass),
        "monitoring_rules": _monitoring_payload(monitoring_pass),
        "order_reconciliation_drill": _order_reconciliation_payload(order_reconciliation_status),
        "kill_switch_drill": _kill_switch_payload(kill_switch_status),
        "paper_simulation_readiness": {"status": "paper_simulation_blocked", "guardrails": {"live_order_allowed": False}},
        "forward_evaluation": {"status": "forward_observing", "guardrails": {"live_order_allowed": False}},
        "live_readiness": {"status": "live_readiness_blocked", "guardrails": {"live_order_allowed": False}},
    }


def _small_account_payload(passed: bool) -> dict[str, object]:
    model = {
        "borrow_notional": 0.0,
        "estimated_financing_daily": 0.0,
        "initial_margin_required": 5000.0,
        "initial_margin_surplus": 5000.0,
        "maintenance_margin_required": 2500.0,
        "maintenance_margin_surplus": 7500.0,
    }
    return {
        "status": "pass_observation_only" if passed else "blocked",
        "guardrails": {"live_order_allowed": False},
        "scenarios": [
            {
                "scenario_id": "one_x_cash_only",
                "fractional_share_allowed_model": dict(model),
                "whole_share_model": dict(model),
            }
        ]
        if passed
        else [],
    }


def _monitoring_payload(passed: bool) -> dict[str, object]:
    return {
        "status": "monitoring_rules_defined" if passed else "monitoring_rules_missing",
        "required_before_paper_or_live": passed,
        "rules": {
            "data_monitors": {"x": {}},
            "position_and_execution_monitors": {"x": {}},
            "attribution": {"x": {}},
            "retirement_rules": {"x": {}},
        }
        if passed
        else {},
        "incident_review": {"required_template_fields": ["timeline"]} if passed else {},
        "replay_requirements": {"inputs": ["data_snapshot"]} if passed else {},
        "guardrails": {"live_order_allowed": False},
    }


def _kill_switch_payload(status: str) -> dict[str, object]:
    blocked = 0 if status == "kill_switch_drill_proven" else 1
    return {
        "status": status,
        "blocked_count": blocked,
        "blockers": [] if blocked == 0 else ["manual_stop_reset_drill_not_proven"],
        "guardrails": {"live_order_allowed": False},
    }


def _order_reconciliation_payload(status: str) -> dict[str, object]:
    passed = status == "order_reconciliation_drill_proven"
    return {
        "status": status,
        "blocked_count": 0 if passed else 1,
        "blockers": [] if passed else ["order_reconciliation_recompute_failed"],
        "oms_exception_matrix_complete": passed,
        "oms_exception_matrix": oms_exception_scenarios() if passed else [],
        "reconciliation": {
            "cash_recomputable": passed,
            "positions_recomputable": passed,
            "fees_recomputable": passed,
        },
        "guardrails": {"live_order_allowed": False},
    }


def _broker_review_payload(status: str) -> dict[str, object]:
    passed = status == "broker_credentials_review_proven"
    return {
        "status": status,
        "broker_credentials_proven": passed,
        "blockers": [] if passed else ["broker_credentials_order_permission_enabled_not_false"],
        "review_summary": {
            "reviewer_recorded": passed,
            "reviewed_at_recorded": passed,
            "manual_approval_ticket_recorded": passed,
            "account_id_hash_format": "sha256_hex_64" if passed else "missing",
            "account_id_hash_format_ok": passed,
            "raw_account_id_pattern_detected": False,
            "read_only_or_live_disabled": passed,
            "order_permission_enabled": not passed,
            "api_key_present_in_repo": False,
        },
        "template_safety": {
            "safe_defaults_present": passed,
            "order_permission_enabled_default": False,
        },
        "evidence_classification": {
            "classification": "manual_review_metadata_only" if passed else "",
            "can_unlock_paper_or_live": False,
            "contains_secret_values": False,
        },
        "guardrails": {
            "live_order_allowed": False,
            "order_endpoint_allowed": False,
            "broker_calls_used": False,
        },
    }


def _assert_oms_exception_scenarios(payload: dict[str, object]) -> None:
    scenarios = {item["scenario_id"]: item for item in payload["oms_exception_scenarios"]}
    assert set(scenarios) == {
        "broker_reject_structured_error",
        "cancel_pending_not_assumed_cancelled",
        "duplicate_submit_idempotency",
        "market_closed_reject",
        "broker_outage_no_duplicate_retry",
        "partial_fill_remaining_qty_recomputed",
        "reconciliation_break_halts_new_orders",
    }
    for scenario in scenarios.values():
        assert scenario["broker_submit_attempted"] is False
        assert scenario["order_created"] is False
        assert scenario["simulated_fill_created"] is False
        assert scenario["passed"] is True
        assert scenario["blockers"] == []
    coverage = {item["scenario_id"]: item for item in payload["oms_exception_coverage_matrix"]}
    assert set(coverage) == set(scenarios)
    for scenario_id, row in coverage.items():
        assert row["required"] is True
        assert row["coverage_status"] == "complete"
        assert row["policy_scenario_passed"] is True
        assert row["order_reconciliation_matrix_present"] is True
        assert row["order_reconciliation_matrix_passed"] is True
        assert row["broker_submit_attempted"] is False
        assert row["order_created"] is False
        assert row["simulated_fill_created"] is False
        assert "generated_oms_exception_scenarios" in row["source_reports"]
        assert "order_reconciliation_drill" in row["source_reports"]
        assert row["blockers"] == [], scenario_id


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _validate_schema(payload: dict[str, object]) -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    jsonschema.validate(payload, schema)
