from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from quant_crypto.monitoring.artifact_schema import validate_btc_artifact_schema
from quant_crypto.monitoring.paper_validation import (
    build_btc_paper_validation_evaluation_artifact,
    build_btc_paper_validation_runtime_artifact,
    build_btc_paper_validation_start_artifact,
)
from scripts.build_btc_paper_validation_artifacts import build_btc_paper_validation_artifacts


TS = datetime(2026, 6, 26, 8, 0, tzinfo=timezone.utc)
HASH = "a" * 64


def test_btc_paper_validation_start_artifact_binds_ledger_and_blocks_live() -> None:
    payload = build_btc_paper_validation_start_artifact(
        source_start_report={
            "status": "ready_to_start_paper_validation",
            "paper_start_allowed": True,
            "live_status": "frozen",
            "paper_review_id": "review_1",
            "approved_paper_review": {"strategy_manifest_id": "btc_strategy_v1"},
            "ledger_session": {"ledger_root": "data/paper_ledger/btc", "latest_reconciliation_artifact_hash": HASH},
        },
        generated_at_utc=TS,
    )

    assert payload["status"] == "complete"
    assert payload["decision"] == "paper_validation_start_ready"
    assert payload["allows_live_orders"] is False
    assert payload["real_order_submitted"] is False
    assert payload["private_endpoint_used"] is False
    assert payload["order_endpoint_used"] is False
    assert validate_btc_artifact_schema(payload) == []


def test_btc_paper_validation_runtime_requires_ledger_oms_audit_dag_and_replay_hashes() -> None:
    payload = build_btc_paper_validation_runtime_artifact(run_id="run_1", generated_at_utc=TS)

    assert payload["status"] == "blocked"
    assert "btc_paper_validation_runtime_ledger_hash_missing" in payload["blockers"]
    assert "btc_paper_validation_runtime_paper_oms_lifecycle_hash_missing" in payload["blockers"]
    assert "btc_paper_validation_runtime_audit_dag_hash_missing" in payload["blockers"]
    assert "btc_paper_validation_runtime_replay_hash_missing" in payload["blockers"]


def test_btc_paper_validation_runtime_blocks_private_or_order_endpoint_claims() -> None:
    payload = build_btc_paper_validation_runtime_artifact(
        run_id="run_1",
        generated_at_utc=TS,
        ledger_hash=HASH,
        paper_oms_lifecycle_hash=HASH,
        audit_dag_hash=HASH,
        replay_hash=HASH,
        runtime_report={
            "real_order_submitted": True,
            "order_endpoint_used": True,
            "private_endpoint_used": True,
        },
    )

    assert payload["status"] == "blocked"
    assert "btc_paper_validation_runtime_real_order_submitted" in payload["blockers"]
    assert "btc_paper_validation_runtime_order_endpoint_used" in payload["blockers"]
    assert "btc_paper_validation_runtime_private_endpoint_used" in payload["blockers"]


def test_btc_paper_validation_evaluation_requires_runtime_hash() -> None:
    payload = build_btc_paper_validation_evaluation_artifact(
        source_evaluation_report={
            "asset": "btc",
            "metrics": {"system_passed": True, "days_completed": 30, "total_orders": 4, "total_fills": 4},
            "conclusion": {"system": "PASS"},
        },
        generated_at_utc=TS,
        runtime_artifact_hash="",
    )

    assert payload["status"] == "blocked"
    assert "btc_paper_validation_evaluation_runtime_hash_missing" in payload["blockers"]


def test_btc_paper_validation_builder_binds_roll_chain_audit_dag_and_replay(tmp_path: Path) -> None:
    start_source = tmp_path / "start.json"
    evaluation_source = tmp_path / "evaluation.json"
    roll_source = tmp_path / "roll.json"
    chain_root = tmp_path / "chain"
    output_root = tmp_path / "latest"
    chain_root.mkdir()

    start_source.write_text(json.dumps({
        "status": "ready_to_start_paper_validation",
        "paper_start_allowed": True,
        "live_status": "frozen",
        "paper_review_id": "review_1",
        "approved_paper_review": {"strategy_manifest_id": "btc_strategy_v1"},
        "ledger_session": {"ledger_root": "ledger", "latest_reconciliation_artifact_hash": HASH},
    }), encoding="utf-8")
    evaluation_source.write_text(json.dumps({
        "asset": "btc",
        "metrics": {"system_passed": True, "days_completed": 30, "total_orders": 0, "total_fills": 0},
        "conclusion": {"system": "PASS"},
    }), encoding="utf-8")

    signal_path = chain_root / "signal.json"
    forecast_path = chain_root / "forecast.json"
    target_path = chain_root / "target.json"
    cost_gate_path = chain_root / "cost_gate.json"
    order_intent_path = chain_root / "order_intent.json"
    paper_oms_path = chain_root / "paper_oms.json"
    _write_json(signal_path, {"signal": {
        "signal_id": "sig_1",
        "strategy_id": "btc_strategy_v1",
        "timestamp_utc": TS.isoformat(),
        "direction": "flat",
    }})
    _write_json(forecast_path, {"forecast": {"forecast_id": "fcst_1", "forecast_expected_return_bps": 0.0}})
    _write_json(target_path, {"target": {
        "target_position_id": "tgt_1",
        "target_weight": 0.0,
        "metadata": {"risk_budget": 1.0},
    }})
    _write_json(cost_gate_path, {"approved": False, "blockers": ["delta_quantity_below_minimum"]})
    _write_json(order_intent_path, {
        "order_intent": None,
        "real_order_submitted": False,
        "private_endpoint_used": False,
        "order_endpoint_used": False,
    })
    _write_json(paper_oms_path, {
        "order_required": False,
        "real_order_submitted": False,
        "private_endpoint_used": False,
        "order_endpoint_used": False,
    })
    _write_json(roll_source, {
        "status": "PASS",
        "strategy_id": "btc_strategy_v1",
        "forecast_target_order_chain": {
            "signal_artifact": str(signal_path),
            "forecast_artifact": str(forecast_path),
            "target_artifact": str(target_path),
            "cost_gate_artifact": str(cost_gate_path),
            "order_intent_artifact": str(order_intent_path),
            "paper_oms_lifecycle_artifact": str(paper_oms_path),
            "order_required": False,
            "real_order_submitted": False,
            "private_endpoint_used": False,
            "order_endpoint_used": False,
        },
    })

    summary = build_btc_paper_validation_artifacts(
        start_source=start_source,
        evaluation_source=evaluation_source,
        roll_source=roll_source,
        output_root=output_root,
        generated_at_utc=TS,
    )
    runtime = json.loads((output_root / "btc_paper_validation_runtime_report.json").read_text(encoding="utf-8"))
    audit_dag = json.loads((output_root / "btc_paper_validation_audit_dag.json").read_text(encoding="utf-8"))
    replay = json.loads((output_root / "btc_paper_validation_replay_report.json").read_text(encoding="utf-8"))

    assert summary["statuses"] == {"start": "complete", "runtime": "complete", "evaluation": "complete"}
    assert runtime["paper_oms_lifecycle_hash"]
    assert runtime["audit_dag_hash"] == audit_dag["artifact_hash"]
    assert runtime["replay_hash"] == replay["artifact_hash"]
    assert audit_dag["status"] == "complete"
    assert replay["status"] == "replay_pass"
    assert replay["perpetual_risk_policy"]["perpetual_allowed"] is False
    assert replay["perpetual_risk_policy"]["status"] == "not_applicable_spot_or_unlevered_path"
    assert replay["perpetual_risk_policy"]["perp_risk_decision_status"] == "not_required_spot_or_unlevered_path"
    assert replay["metadata"]["perpetual_risk_policy"] == replay["perpetual_risk_policy"]
    assert runtime["real_order_submitted"] is False
    assert runtime["private_endpoint_used"] is False
    assert runtime["order_endpoint_used"] is False
    assert runtime["runtime_report"]["perpetual_risk_policy"] == replay["perpetual_risk_policy"]


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")
