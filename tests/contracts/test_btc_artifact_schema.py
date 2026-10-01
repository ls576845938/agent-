from __future__ import annotations

from datetime import datetime, timezone

from quant_crypto.monitoring.artifact_schema import (
    apply_btc_artifact_schema,
    validate_btc_artifact_schema,
)
from quant_crypto.monitoring.audit_dag import (
    BTC_AUDIT_NODE_ORDER,
    BTCAuditArtifactRef,
    build_btc_audit_dag,
)
from quant_crypto.monitoring.incident import BTCIncidentTrigger, build_btc_incident_artifact
from quant_crypto.monitoring.order_surface_audit import audit_btc_direct_order_call_surface
from quant_crypto.monitoring.replay_engine import BTCReplayContext, run_btc_replay


TS = datetime(2026, 6, 26, 8, 0, tzinfo=timezone.utc)
HASH = "a" * 64


def test_btc_artifact_schema_adds_required_report_fields_and_hashes() -> None:
    payload = apply_btc_artifact_schema(
        {"status": "complete", "blockers": []},
        decision="schema_contract_pass",
        generated_at_utc=TS,
        as_of_utc=TS,
        input_hashes={"source": HASH},
    )

    assert validate_btc_artifact_schema(payload) == []
    assert payload["decision"] == "schema_contract_pass"
    assert payload["warnings"] == []
    assert payload["generated_at"] == TS.isoformat()
    assert payload["as_of_utc"] == TS.isoformat()
    assert len(payload["artifact_hash"]) == 64


def test_btc_artifact_schema_blocks_missing_required_fields() -> None:
    blockers = validate_btc_artifact_schema({"status": "complete"})

    assert "btc_artifact_schema_field_missing:decision" in blockers
    assert "btc_artifact_schema_field_missing:blockers" in blockers
    assert "btc_artifact_schema_field_missing:warnings" in blockers
    assert "btc_artifact_schema_field_missing:generated_at" in blockers
    assert "btc_artifact_schema_field_missing:as_of_utc" in blockers
    assert "btc_artifact_schema_field_missing:artifact_hash" in blockers
    assert "btc_artifact_schema_field_missing:input_hashes" in blockers


def test_btc_monitoring_artifacts_conform_to_unified_schema() -> None:
    artifacts = [
        _audit_dag_payload(),
        _replay_payload(),
        _incident_payload(),
        audit_btc_direct_order_call_surface(
            {"quant_crypto/portfolio/order_intent.py": "intent = {'source_boundary': 'no_broker_submit'}"},
            generated_at_utc=TS,
        ),
    ]

    for artifact in artifacts:
        assert validate_btc_artifact_schema(artifact) == []


def _audit_dag_payload() -> dict[str, object]:
    artifacts = {
        node_type: BTCAuditArtifactRef(
            path=f"artifacts/btc/{node_type.value}.json",
            artifact_hash=HASH,
            code_version="test",
            input_hashes={"source": HASH},
        )
        for node_type in BTC_AUDIT_NODE_ORDER
    }
    log_context = {
        "run_id": "run_1",
        "strategy_id": "btc_strategy",
        "data_version": "data_v1",
        "decision_time_utc": TS.isoformat(),
        "signal_id": "signal_1",
        "forecast_id": "forecast_1",
        "target_id": "target_1",
        "risk_decision_id": "risk_1",
        "order_id": "order_1",
        "fill_id": "fill_1",
        "error_code": "",
    }
    return build_btc_audit_dag(
        run_id="run_1",
        strategy_id="btc_strategy",
        data_version="data_v1",
        decision_time_utc=TS,
        artifacts=artifacts,
        log_context=log_context,
    ).to_dict()


def _replay_payload() -> dict[str, object]:
    context = BTCReplayContext(
        fixed_clock_utc=TS,
        random_seed=7,
        strategy_version="test",
        params={"lookback": 3},
        data_snapshot={"bars": [1, 2, 3]},
        risk_config={"max_weight": 0.2},
        current_position={"btc": 0.0},
    )
    original = {
        "signal": {"side": "buy"},
        "forecast": {"expected_return": 0.01},
        "target": {"weight": 0.1},
        "risk_decision": {"approved": True},
    }
    return run_btc_replay(
        audit_dag_payload={"status": "complete", "artifact_hash": HASH},
        context=context,
        replay_fn=lambda _: original,
        original_outputs=original,
    ).to_dict()


def _incident_payload() -> dict[str, object]:
    return build_btc_incident_artifact(
        incident_id="incident_1",
        trigger=BTCIncidentTrigger.DATA_INTERRUPTION,
        detected_at_utc=TS,
        run_id="run_1",
        strategy_id="btc_strategy",
        severity="medium",
        template={
            "timeline": ["detected"],
            "impact_scope": "paper observation",
            "direct_cause": "source interruption",
            "root_cause": "provider unavailable",
            "failed_gate": "data freshness",
            "remediation_actions": ["retry later"],
            "regression_test": "tests/contracts/test_btc_incident_artifact.py",
            "strategy_pause_required": True,
        },
        source_refs={"data_status": "artifacts/btc/data_status.json"},
        audit_dag_hash=HASH,
        replay_artifact_hash=HASH,
    )
