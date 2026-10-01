from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from scripts.build_us_equity_order_reconciliation_drill_report import (
    build_us_equity_order_reconciliation_drill_report,
)


SCHEMA = Path("schemas/us_equity_order_reconciliation_drill_report.schema.json")
REQUIRED_OMS_EXCEPTION_SCENARIOS = {
    "broker_reject_structured_error",
    "cancel_pending_not_assumed_cancelled",
    "duplicate_submit_idempotency",
    "market_closed_reject",
    "broker_outage_no_duplicate_retry",
    "partial_fill_remaining_qty_recomputed",
    "reconciliation_break_halts_new_orders",
}


def test_order_reconciliation_drill_proves_simulated_ledger_recalculation(tmp_path: Path) -> None:
    payload = build_us_equity_order_reconciliation_drill_report(
        repo_root=tmp_path,
        output=Path("out/order_reconciliation.json"),
        markdown_output=Path("out/order_reconciliation.md"),
        generated_at="2026-06-27T00:00:00Z",
    )

    _validate_schema(payload)
    assert payload["status"] == "order_reconciliation_drill_proven"
    assert payload["order_count"] == 5
    assert payload["fill_count"] == 3
    assert payload["snapshot_count"] == 5
    assert payload["scenario_count"] == 13
    assert payload["proven_count"] == 13
    assert payload["blocked_count"] == 0
    assert payload["blockers"] == []
    assert payload["oms_exception_matrix_complete"] is True
    assert payload["reconciliation"]["cash_recomputable"] is True
    assert payload["reconciliation"]["positions_recomputable"] is True
    assert payload["reconciliation"]["fees_recomputable"] is True
    assert payload["reconciliation"]["total_fees"] == 0.862
    scenario_status = {item["scenario_id"]: item["status"] for item in payload["scenario_results"]}
    assert scenario_status == {
        "filled_order_reconciles_cash_position_fee": "proven",
        "partial_fill_state_reconciles": "proven",
        "reject_order_creates_no_fill": "proven",
        "cancelled_order_creates_no_fill": "proven",
        "portfolio_snapshot_recomputes_from_fills": "proven",
        "fees_recompute_from_notional": "proven",
        "broker_reject_structured_error": "proven",
        "cancel_pending_not_assumed_cancelled": "proven",
        "duplicate_submit_idempotency": "proven",
        "market_closed_reject": "proven",
        "broker_outage_no_duplicate_retry": "proven",
        "partial_fill_remaining_qty_recomputed": "proven",
        "reconciliation_break_halts_new_orders": "proven",
    }
    assert payload["guardrails"]["live_order_allowed"] is False
    assert payload["guardrails"]["order_endpoint_allowed"] is False
    assert payload["guardrails"]["broker_calls_used"] is False
    assert (tmp_path / "out/order_reconciliation.json").exists()
    assert (tmp_path / "out/order_reconciliation.md").exists()


def test_order_reconciliation_drill_reject_cancel_have_no_fills(tmp_path: Path) -> None:
    payload = build_us_equity_order_reconciliation_drill_report(
        repo_root=tmp_path,
        output=Path("out/order_reconciliation.json"),
        markdown_output=Path("out/order_reconciliation.md"),
        generated_at="2026-06-27T00:00:00Z",
    )

    fill_order_ids = {fill["order_id"] for fill in payload["fills"]}
    assert "sim-reject-dbmf-001" not in fill_order_ids
    assert "sim-cancel-soxx-001" not in fill_order_ids
    orders = {order["order_id"]: order for order in payload["orders"]}
    assert "rejected" in orders["sim-reject-dbmf-001"]["lifecycle_events"]
    assert "cancel_requested" in orders["sim-cancel-soxx-001"]["lifecycle_events"]
    assert "cancelled" in orders["sim-cancel-soxx-001"]["lifecycle_events"]
    final_snapshot = payload["portfolio_snapshots"][-1]
    assert round(final_snapshot["cash"] + final_snapshot["market_value"], 8) == final_snapshot["equity"]


def test_order_reconciliation_drill_has_required_oms_exception_matrix(tmp_path: Path) -> None:
    payload = build_us_equity_order_reconciliation_drill_report(
        repo_root=tmp_path,
        output=Path("out/order_reconciliation.json"),
        markdown_output=Path("out/order_reconciliation.md"),
        generated_at="2026-06-27T00:00:00Z",
    )

    matrix = {item["scenario_id"]: item for item in payload["oms_exception_matrix"]}
    scenario_results = {item["scenario_id"]: item for item in payload["scenario_results"]}
    assert set(matrix) == REQUIRED_OMS_EXCEPTION_SCENARIOS
    assert set(payload["required_oms_exception_scenarios"]) == REQUIRED_OMS_EXCEPTION_SCENARIOS
    for scenario_id in REQUIRED_OMS_EXCEPTION_SCENARIOS:
        row = matrix[scenario_id]
        assert row["passed"] is True
        assert row["blockers"] == []
        assert row["broker_submit_attempted"] is False
        assert row["order_created"] is False
        assert row["simulated_fill_created"] is False
        assert scenario_results[scenario_id]["category"] == "oms_exception"
        assert scenario_results[scenario_id]["status"] == "proven"

    assert matrix["broker_outage_no_duplicate_retry"]["idempotency_key_required"] is True
    assert matrix["market_closed_reject"]["retry_allowed"] is True
    assert matrix["reconciliation_break_halts_new_orders"]["new_orders_blocked"] is True
    assert matrix["reconciliation_break_halts_new_orders"]["incident_review_required"] is True


def test_order_reconciliation_schema_rejects_live_order_allowed(tmp_path: Path) -> None:
    payload = build_us_equity_order_reconciliation_drill_report(
        repo_root=tmp_path,
        output=Path("out/order_reconciliation.json"),
        markdown_output=Path("out/order_reconciliation.md"),
        generated_at="2026-06-27T00:00:00Z",
    )
    payload["guardrails"]["live_order_allowed"] = True

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError:
        return
    raise AssertionError("schema accepted live_order_allowed=true")


def test_order_reconciliation_schema_rejects_incomplete_oms_exception_matrix(tmp_path: Path) -> None:
    payload = build_us_equity_order_reconciliation_drill_report(
        repo_root=tmp_path,
        output=Path("out/order_reconciliation.json"),
        markdown_output=Path("out/order_reconciliation.md"),
        generated_at="2026-06-27T00:00:00Z",
    )
    payload["oms_exception_matrix_complete"] = False

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError:
        return
    raise AssertionError("schema accepted incomplete oms_exception_matrix")


def _validate_schema(payload: dict[str, object]) -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    jsonschema.validate(payload, schema)
