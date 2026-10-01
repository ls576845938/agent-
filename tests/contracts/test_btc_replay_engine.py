from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

from quant_crypto.monitoring.audit_dag import (
    BTC_AUDIT_NODE_ORDER,
    BTCAuditArtifactRef,
    artifact_ref_from_payload,
    build_btc_audit_dag,
)
from quant_crypto.monitoring.replay_engine import (
    BTC_REPLAY_ENGINE_VERSION,
    BTCReplayContext,
    diff_replay_outputs,
    run_btc_replay,
)


TS = datetime(2026, 6, 26, 8, 0, tzinfo=timezone.utc)


def _artifact(node_type) -> BTCAuditArtifactRef:
    return artifact_ref_from_payload(
        path=f"artifacts/btc_replay_fixture/{node_type.value}.json",
        payload={"node_type": node_type.value},
        code_version="test-code-version",
    )


def _audit_dag_payload() -> dict[str, Any]:
    artifacts = {node_type: _artifact(node_type) for node_type in BTC_AUDIT_NODE_ORDER}
    dag = build_btc_audit_dag(
        run_id="btc_replay_run_001",
        strategy_id="btc_intraday_short_cycle",
        data_version="btc_data_v1",
        decision_time_utc=TS,
        artifacts=artifacts,
        log_context={
            "run_id": "btc_replay_run_001",
            "strategy_id": "btc_intraday_short_cycle",
            "data_version": "btc_data_v1",
            "decision_time_utc": TS.isoformat(),
            "signal_id": "sig_001",
            "forecast_id": "fcst_001",
            "target_id": "tgt_001",
            "risk_decision_id": "risk_001",
            "order_id": "order_001",
            "fill_id": "fill_001",
            "error_code": "",
        },
    )
    return dag.to_dict()


def _context(**overrides: object) -> BTCReplayContext:
    values: dict[str, object] = {
        "fixed_clock_utc": TS,
        "random_seed": 7,
        "strategy_version": "strategy_v1",
        "params": {"lookback": 12},
        "data_snapshot": {"bars": [{"ts": TS.isoformat(), "close": 50_000.0}]},
        "risk_config": {"max_btc_exposure": 0.25},
        "current_position": {"quantity": 0.0},
        "historical_orders": [{"client_order_id": "coid_001"}],
        "historical_fills": [{"fill_id": "fill_001"}],
        "live_data_accessed": False,
    }
    values.update(overrides)
    return BTCReplayContext(**values)


def _outputs() -> dict[str, object]:
    return {
        "signal": {"signal_id": "sig_001", "direction": "long", "strength": 1.0},
        "forecast": {"forecast_id": "fcst_001", "expected_return_bps": 80.0},
        "target": {"target_id": "tgt_001", "target_weight": 0.25},
        "risk_decision": {"risk_decision_id": "risk_001", "approved": True},
    }


def test_btc_replay_passes_with_fixed_clock_seed_and_matching_outputs() -> None:
    original = _outputs()

    result = run_btc_replay(
        audit_dag_payload=_audit_dag_payload(),
        context=_context(),
        replay_fn=lambda context: original,
        original_outputs=original,
    )
    payload = result.to_dict()

    assert payload["replay_engine_version"] == BTC_REPLAY_ENGINE_VERSION
    assert payload["status"] == "replay_pass"
    assert payload["blockers"] == []
    assert payload["metadata"]["fixed_clock_utc"] == TS.isoformat()
    assert payload["metadata"]["fixed_random_seed"] == 7
    assert payload["metadata"]["current_realtime_data_accessed"] is False
    assert payload["metadata"]["required_outputs"] == ["signal", "forecast", "target", "risk_decision"]
    assert all(not item["changed"] for item in payload["diffs"].values())
    assert len(payload["artifact_hash"]) == 64
    assert set(payload["input_hashes"]) == {"replayed_outputs", "diffs", "metadata"}


def test_btc_replay_blocks_live_data_access() -> None:
    result = run_btc_replay(
        audit_dag_payload=_audit_dag_payload(),
        context=_context(live_data_accessed=True),
        replay_fn=lambda context: _outputs(),
        original_outputs=_outputs(),
    )

    assert result.status == "replay_blocked"
    assert "btc_replay_live_data_accessed" in result.blockers


def test_btc_replay_blocks_incomplete_audit_dag() -> None:
    dag = _audit_dag_payload()
    dag["status"] = "blocked"

    result = run_btc_replay(
        audit_dag_payload=dag,
        context=_context(),
        replay_fn=lambda context: _outputs(),
        original_outputs=_outputs(),
    )

    assert "btc_replay_audit_dag_not_complete" in result.blockers


def test_btc_replay_blocks_missing_required_outputs() -> None:
    replayed = _outputs()
    replayed.pop("risk_decision")

    result = run_btc_replay(
        audit_dag_payload=_audit_dag_payload(),
        context=_context(),
        replay_fn=lambda context: replayed,
        original_outputs=_outputs(),
    )

    assert result.status == "replay_blocked"
    assert "btc_replay_output_missing:risk_decision" in result.blockers
    assert "btc_replay_diff_detected" in result.blockers


def test_btc_replay_blocks_diff_vs_original_artifact() -> None:
    replayed = _outputs()
    replayed["target"] = {"target_id": "tgt_001", "target_weight": 0.10}

    result = run_btc_replay(
        audit_dag_payload=_audit_dag_payload(),
        context=_context(),
        replay_fn=lambda context: replayed,
        original_outputs=_outputs(),
    )

    assert result.status == "replay_blocked"
    assert "btc_replay_diff_detected" in result.blockers
    assert result.diffs["target"]["changed"] is True


def test_btc_replay_context_requires_seed_and_strategy_version() -> None:
    with pytest.raises(ValueError, match="random_seed"):
        _context(random_seed=None)
    with pytest.raises(ValueError, match="strategy_version"):
        _context(strategy_version="")


def test_btc_replay_diff_reports_stable_hashes() -> None:
    diff = diff_replay_outputs(
        {"signal": {"value": 1}},
        {"signal": {"value": 1}},
        keys=("signal",),
    )

    assert diff["signal"]["changed"] is False
    assert len(diff["signal"]["original_hash"]) == 64
    assert len(diff["signal"]["replayed_hash"]) == 64
