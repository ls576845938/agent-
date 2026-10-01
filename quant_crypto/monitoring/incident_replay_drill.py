from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from quant_shared.core.time import ensure_utc

from .artifact_schema import apply_btc_artifact_schema, stable_payload_hash
from .incident import BTCIncidentTrigger, build_btc_incident_artifact


BTC_INCIDENT_REPLAY_DRILL_VERSION = "btc_incident_replay_drill_v1"


@dataclass(frozen=True)
class BTCIncidentReplayDrillScenario:
    name: str
    trigger: BTCIncidentTrigger
    regression_test: str
    replay_artifact_hash: str
    audit_dag_hash: str
    source_refs: dict[str, str]
    detected_at_utc: datetime
    run_id: str
    strategy_id: str
    severity: str = "medium"

    def __post_init__(self) -> None:
        if not isinstance(self.trigger, BTCIncidentTrigger):
            object.__setattr__(self, "trigger", BTCIncidentTrigger(str(self.trigger)))
        object.__setattr__(self, "detected_at_utc", ensure_utc(self.detected_at_utc))


def build_btc_incident_replay_drill(
    *,
    scenarios: list[BTCIncidentReplayDrillScenario],
    generated_at_utc: datetime,
) -> dict[str, Any]:
    blockers: list[str] = []
    scenario_payloads: list[dict[str, Any]] = []
    required = {"data_outage", "funding_gap", "order_reject", "ledger_mismatch"}
    present = {scenario.name for scenario in scenarios}
    for missing in sorted(required - present):
        blockers.append(f"btc_incident_replay_drill_scenario_missing:{missing}")
    for scenario in scenarios:
        template = {
            "timeline": [f"{scenario.name}_detected"],
            "impact_scope": "paper observation",
            "direct_cause": scenario.name,
            "root_cause": "drill",
            "failed_gate": scenario.name,
            "remediation_actions": ["fail closed", "review replay diff"],
            "regression_test": scenario.regression_test,
            "strategy_pause_required": True,
        }
        incident = build_btc_incident_artifact(
            incident_id=f"drill_{scenario.name}",
            trigger=scenario.trigger,
            detected_at_utc=scenario.detected_at_utc,
            run_id=scenario.run_id,
            strategy_id=scenario.strategy_id,
            severity=scenario.severity,
            template=template,
            source_refs=scenario.source_refs,
            audit_dag_hash=scenario.audit_dag_hash,
            replay_artifact_hash=scenario.replay_artifact_hash,
        )
        if incident["status"] == "blocked":
            blockers.append(f"btc_incident_replay_drill_incident_blocked:{scenario.name}")
        if not scenario.replay_artifact_hash:
            blockers.append(f"btc_incident_replay_drill_replay_hash_missing:{scenario.name}")
        if not scenario.regression_test:
            blockers.append(f"btc_incident_replay_drill_regression_test_missing:{scenario.name}")
        scenario_payloads.append(
            {
                "name": scenario.name,
                "trigger": scenario.trigger.value,
                "incident": incident,
                "replay_artifact_hash": scenario.replay_artifact_hash,
                "audit_dag_hash": scenario.audit_dag_hash,
                "regression_test": scenario.regression_test,
            }
        )
    payload = {
        "incident_replay_drill_version": BTC_INCIDENT_REPLAY_DRILL_VERSION,
        "status": "complete" if not blockers else "blocked",
        "scenario_count": len(scenario_payloads),
        "required_scenarios": sorted(required),
        "scenarios": scenario_payloads,
        "allows_live_orders": False,
        "real_order_submitted": False,
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "blockers": _dedupe(blockers),
    }
    return apply_btc_artifact_schema(
        payload,
        decision="incident_replay_drill_complete" if not blockers else "incident_replay_drill_blocked",
        generated_at_utc=generated_at_utc,
        as_of_utc=generated_at_utc,
        blockers=_dedupe(blockers),
        warnings=[],
        input_hashes={"scenarios": stable_payload_hash([scenario.__dict__ for scenario in scenarios])},
    )


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result
