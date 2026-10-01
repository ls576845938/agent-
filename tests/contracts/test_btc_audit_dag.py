from __future__ import annotations

from datetime import datetime, timezone

import pytest

from quant_crypto.monitoring.audit_dag import (
    BTC_AUDIT_DAG_VERSION,
    BTC_AUDIT_NODE_ORDER,
    BTCAuditArtifactRef,
    BTCAuditDAG,
    BTCAuditNode,
    BTCAuditNodeType,
    artifact_ref_from_payload,
    build_btc_audit_dag,
    stable_payload_hash,
)


TS = datetime(2026, 6, 26, 8, 0, tzinfo=timezone.utc)


def _artifact(node_type: BTCAuditNodeType) -> BTCAuditArtifactRef:
    payload = {"node_type": node_type.value, "value": 1}
    return artifact_ref_from_payload(
        path=f"artifacts/btc_audit_fixture/{node_type.value}.json",
        payload=payload,
        code_version="test-code-version",
        input_hashes={"source": stable_payload_hash({"source": node_type.value})},
    )


def _artifacts() -> dict[BTCAuditNodeType, BTCAuditArtifactRef]:
    return {node_type: _artifact(node_type) for node_type in BTC_AUDIT_NODE_ORDER}


def _log_context(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "run_id": "btc_audit_run_001",
        "strategy_id": "btc_intraday_short_cycle",
        "data_version": "btc_data_v1",
        "decision_time_utc": TS.isoformat(),
        "signal_id": "sig_001",
        "forecast_id": "fcst_001",
        "target_id": "tgt_001",
        "risk_decision_id": "risk_001",
        "order_id": "btc_order_001",
        "fill_id": "fill_001",
        "error_code": "",
    }
    values.update(overrides)
    return values


def test_btc_audit_dag_requires_complete_ordered_artifact_chain_and_log_context() -> None:
    dag = build_btc_audit_dag(
        run_id="btc_audit_run_001",
        strategy_id="btc_intraday_short_cycle",
        data_version="btc_data_v1",
        decision_time_utc=TS,
        artifacts=_artifacts(),
        log_context=_log_context(),
    )
    payload = dag.to_dict()

    assert payload["dag_version"] == BTC_AUDIT_DAG_VERSION
    assert payload["status"] == "complete"
    assert payload["blockers"] == []
    assert payload["node_order"] == [node_type.value for node_type in BTC_AUDIT_NODE_ORDER]
    assert [node["node_type"] for node in payload["nodes"]] == payload["node_order"]
    assert payload["nodes"][0]["depends_on"] == []
    assert payload["nodes"][1]["depends_on"] == ["btc_data_snapshot"]
    assert payload["nodes"][-1]["depends_on"] == ["btc_pnl"]
    assert len(payload["artifact_hash"]) == 64
    assert set(payload["input_hashes"]) == {f"btc_{node_type.value}" for node_type in BTC_AUDIT_NODE_ORDER}
    for node in payload["nodes"]:
        assert node["artifact"]["path"].endswith(f"{node['node_type']}.json")
        assert len(node["artifact"]["artifact_hash"]) == 64
        assert node["artifact"]["code_version"] == "test-code-version"
        assert node["artifact"]["input_hashes"]["source"]


def test_btc_audit_dag_rejects_missing_node_artifact() -> None:
    artifacts = _artifacts()
    artifacts.pop(BTCAuditNodeType.FILL)

    with pytest.raises(ValueError, match="fill"):
        build_btc_audit_dag(
            run_id="btc_audit_run_001",
            strategy_id="btc_intraday_short_cycle",
            data_version="btc_data_v1",
            decision_time_utc=TS,
            artifacts=artifacts,
            log_context=_log_context(),
        )


def test_btc_audit_dag_blocks_missing_structured_log_fields() -> None:
    log_context = _log_context()
    log_context.pop("risk_decision_id")

    dag = build_btc_audit_dag(
        run_id="btc_audit_run_001",
        strategy_id="btc_intraday_short_cycle",
        data_version="btc_data_v1",
        decision_time_utc=TS,
        artifacts=_artifacts(),
        log_context=log_context,
    )

    assert "btc_structured_log_field_missing:risk_decision_id" in dag.validate()
    assert dag.to_dict()["status"] == "blocked"


def test_btc_audit_dag_blocks_wrong_order_and_dependency_gap() -> None:
    nodes = [
        BTCAuditNode(node_type=BTCAuditNodeType.DATA_SNAPSHOT, artifact=_artifact(BTCAuditNodeType.DATA_SNAPSHOT)),
        BTCAuditNode(node_type=BTCAuditNodeType.SIGNAL, artifact=_artifact(BTCAuditNodeType.SIGNAL), depends_on=[]),
    ]
    dag = BTCAuditDAG(
        run_id="btc_audit_run_001",
        strategy_id="btc_intraday_short_cycle",
        data_version="btc_data_v1",
        decision_time_utc=TS,
        nodes=nodes,
        log_context=_log_context(),
    )

    blockers = dag.validate()
    assert "btc_audit_dag_node_order_incomplete_or_invalid" in blockers
    assert "btc_audit_dag_missing_dependency:btc_signal->btc_data_snapshot" in blockers


def test_btc_audit_artifact_ref_requires_hash_code_version_and_valid_input_hashes() -> None:
    with pytest.raises(ValueError, match="artifact_hash"):
        BTCAuditArtifactRef(path="artifact.json", artifact_hash="not-a-hash", code_version="code")

    with pytest.raises(ValueError, match="code_version"):
        BTCAuditArtifactRef(path="artifact.json", artifact_hash="a" * 64, code_version="")

    with pytest.raises(ValueError, match="input_hashes"):
        BTCAuditArtifactRef(
            path="artifact.json",
            artifact_hash="a" * 64,
            code_version="code",
            input_hashes={"bad": "not-a-hash"},
        )
