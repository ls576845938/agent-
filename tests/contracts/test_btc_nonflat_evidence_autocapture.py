from __future__ import annotations

from copy import deepcopy

import pytest

from quant_crypto.research.btc_nonflat_evidence_autocapture import (
    REQUIRED_NODE_TYPES,
    build_btc_nonflat_evidence_autocapture,
    replay_btc_nonflat_evidence,
)


BINDING = {
    "run_id": "natural-run-001",
    "strategy_version": "trend-v7",
    "data_version": "immutable-btc-v3",
    "source_head": "a" * 40,
}


def _session(status: str = "complete") -> dict:
    return {
        "order_records": [{"client_order_id": "c-1", "status": "filled"}],
        "fill_records": [{"fill_id": "f-1", "quantity_btc": 0.01}],
        "reconciliation_report": {"status": status, "blockers": [] if status == "complete" else ["position_mismatch"]},
    }


def _row(**overrides) -> dict:
    row = {
        "signal": {"direction": "long", "observed_at": "2026-07-24T08:00:00Z"},
        "forecast": {"return": "0.002", "horizon": "1h"},
        "target_exposure": 0.1,
        "side": "long",
        "candidate_id": "btc-natural-1",
        "decision_time": "2026-07-24T08:00:00Z",
        "risk_decision": "approved",
        "risk_approved": True,
        "risk_blockers": [],
        "fee_amount_usdt": 0.05,
        "modeled_slippage_bps": 2.0,
        "order_intent": "market_rebalance",
        "quantity_btc": 0.01,
        "filled_quantity_btc": 0.01,
        "notional_usdt": 600.0,
        "venue": "OKX",
        "simulated_fill_created": True,
        "fill_state": "filled",
        "position_ledger": {"quantity_btc": 0.01},
        "cash_ledger": {"cash_usdt": 9400.0},
        "funding_rate": 0.0,
        "funding_amount_usdt": 0.0,
        "mark_price": 60000.0,
        "index_price": 59990.0,
        "liquidation_price": 54000.0,
        "liquidation_buffer_bps": 1000.0,
        "depth_fill_mapping": {"snapshot_sequence": 42, "mapped_fill_id": "f-1"},
        "paper_runtime_gate_eligible": True,
    }
    row.update(overrides)
    return row


def _build(rows, *, session=None, **kwargs):
    return build_btc_nonflat_evidence_autocapture(
        replay_rows=rows,
        oms_session=session or _session(),
        **BINDING,
        **kwargs,
    )


def test_flat_heartbeat_waits_without_false_order_or_fill_evidence() -> None:
    report = _build([{"target_exposure": 0.0}], private_ws_observed=False, funding_cashflow_observed=False)
    assert report["status"] == "waiting_for_natural_non_flat_sample"
    assert report["nodes"] == []
    assert report["promotion_evidence_ready"] is False


def test_natural_nonflat_builds_ordered_hash_bound_audit_dag() -> None:
    report = _build([_row()], private_ws_observed=True, funding_cashflow_observed=True)
    assert report["status"] == "promotion_evidence_chain_complete"
    assert report["promotion_evidence_ready"] is True
    assert report["audit_dag"]["valid"] is True
    assert tuple(report["audit_dag"]["node_types"]) == REQUIRED_NODE_TYPES
    assert all(node["binding"] == BINDING for node in report["nodes"])
    assert replay_btc_nonflat_evidence(report)["valid"] is True


def test_risk_rejected_stops_before_order_intent() -> None:
    report = _build([_row(risk_approved=False, risk_decision="rejected", risk_blockers=["risk_budget"])])
    assert report["status"] == "risk_rejected_fail_closed"
    assert [node["node_type"] for node in report["nodes"]] == [
        "signal_forecast",
        "target_position",
        "cost_risk_decision",
    ]
    assert report["promotion_evidence_ready"] is False


def test_partial_fill_is_captured_but_remains_incomplete() -> None:
    report = _build(
        [_row(fill_state="partial", filled_quantity_btc=0.004)],
        private_ws_observed=False,
        funding_cashflow_observed=True,
    )
    assert report["status"] == "partial_fill_evidence_incomplete"
    assert "btc_nonflat_private_ws_observation_not_authorized_or_missing" in report["blockers"]


@pytest.mark.parametrize("funding_amount", [0.0, 1.25])
def test_zero_and_nonzero_funding_are_explicit_ledger_values(funding_amount) -> None:
    report = _build(
        [_row(funding_amount_usdt=funding_amount)],
        private_ws_observed=True,
        funding_cashflow_observed=True,
    )
    ledger = next(node for node in report["nodes"] if node["node_type"] == "position_cash_funding_ledger")
    assert ledger["payload"]["funding_ledger"]["funding_amount_usdt"] == funding_amount


def test_reconciliation_failure_blocks_promotion() -> None:
    report = _build(
        [_row()],
        session=_session("failed"),
        private_ws_observed=True,
        funding_cashflow_observed=True,
    )
    assert "btc_nonflat_reconciliation_failed" in report["blockers"]
    assert report["promotion_evidence_ready"] is False


def test_fixture_or_historical_sample_never_becomes_promotion_evidence() -> None:
    report = _build(
        [_row()],
        sample_origin="historical_fixture_diagnostic",
        private_ws_observed=True,
        funding_cashflow_observed=True,
    )
    assert report["diagnostic_or_fixture_only"] is True
    assert report["promotion_evidence_ready"] is False
    assert "btc_nonflat_sample_not_current_natural_observation" in report["blockers"]


def test_dag_validates_dependency_order_not_only_file_hash() -> None:
    report = _build([_row()], private_ws_observed=True, funding_cashflow_observed=True)
    mutated = deepcopy(report)
    mutated["nodes"][4]["dependencies"] = []
    replay = replay_btc_nonflat_evidence(mutated)
    assert replay["valid"] is False
    assert any("dependency_invalid" in item for item in replay["blockers"])


@pytest.mark.parametrize(
    "path",
    [
        "artifacts/x/latest/report.json",
        "runtime/current/state.json",
        "exchange/live/orders.json",
    ],
)
def test_replay_rejects_latest_current_and_live_pointers(path) -> None:
    report = _build([_row()], private_ws_observed=True, funding_cashflow_observed=True)
    report["inputs"] = {"source_paths": [path]}
    replay = replay_btc_nonflat_evidence(report)
    assert replay["valid"] is False
    assert replay["blockers"] == ["btc_nonflat_replay_forbidden_runtime_pointer"]
