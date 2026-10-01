from __future__ import annotations

from datetime import datetime, timezone

from quant_crypto.monitoring.artifact_schema import validate_btc_artifact_schema
from quant_crypto.monitoring.incident import BTCIncidentTrigger
from quant_crypto.monitoring.incident_replay_drill import (
    BTCIncidentReplayDrillScenario,
    build_btc_incident_replay_drill,
)


TS = datetime(2026, 6, 26, 8, 0, tzinfo=timezone.utc)
HASH = "a" * 64
REPLAY = "b" * 64


def _scenario(name: str, trigger: BTCIncidentTrigger) -> BTCIncidentReplayDrillScenario:
    refs = {"data_status": "artifacts/btc/data_status.json"}
    if trigger == BTCIncidentTrigger.FUNDING_GAP:
        refs["funding_gap_report"] = "artifacts/btc/funding_gap.json"
    return BTCIncidentReplayDrillScenario(
        name=name,
        trigger=trigger,
        regression_test=f"tests/contracts/test_{name}.py",
        replay_artifact_hash=REPLAY,
        audit_dag_hash=HASH,
        source_refs=refs,
        detected_at_utc=TS,
        run_id="run_1",
        strategy_id="btc_strategy",
    )


def test_btc_incident_replay_drill_requires_all_core_paper_scenarios() -> None:
    payload = build_btc_incident_replay_drill(
        scenarios=[
            _scenario("data_outage", BTCIncidentTrigger.DATA_INTERRUPTION),
            _scenario("funding_gap", BTCIncidentTrigger.FUNDING_GAP),
            _scenario("order_reject", BTCIncidentTrigger.ORDER_REJECT),
            _scenario("ledger_mismatch", BTCIncidentTrigger.LEDGER_MISMATCH),
        ],
        generated_at_utc=TS,
    )

    assert payload["status"] == "complete"
    assert payload["decision"] == "incident_replay_drill_complete"
    assert payload["scenario_count"] == 4
    assert payload["allows_live_orders"] is False
    assert payload["real_order_submitted"] is False
    assert validate_btc_artifact_schema(payload) == []


def test_btc_incident_replay_drill_blocks_missing_scenario_and_replay_hash() -> None:
    broken = _scenario("data_outage", BTCIncidentTrigger.DATA_INTERRUPTION)
    broken = BTCIncidentReplayDrillScenario(
        name=broken.name,
        trigger=broken.trigger,
        regression_test="",
        replay_artifact_hash="",
        audit_dag_hash=HASH,
        source_refs=broken.source_refs,
        detected_at_utc=TS,
        run_id="run_1",
        strategy_id="btc_strategy",
    )

    payload = build_btc_incident_replay_drill(scenarios=[broken], generated_at_utc=TS)

    assert payload["status"] == "blocked"
    assert "btc_incident_replay_drill_scenario_missing:funding_gap" in payload["blockers"]
    assert "btc_incident_replay_drill_scenario_missing:ledger_mismatch" in payload["blockers"]
    assert "btc_incident_replay_drill_scenario_missing:order_reject" in payload["blockers"]
    assert "btc_incident_replay_drill_replay_hash_missing:data_outage" in payload["blockers"]
    assert "btc_incident_replay_drill_regression_test_missing:data_outage" in payload["blockers"]
