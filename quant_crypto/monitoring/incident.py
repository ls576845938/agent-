from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from quant_shared.core.time import ensure_utc

from .artifact_schema import apply_btc_artifact_schema
from .audit_dag import stable_payload_hash


BTC_INCIDENT_ARTIFACT_VERSION = "btc_incident_artifact_v1"


class BTCIncidentTrigger(str, Enum):
    DATA_INTERRUPTION = "data_interruption"
    OKX_API_ERROR = "okx_api_error"
    BINANCE_API_ERROR = "binance_api_error"
    FUNDING_GAP = "funding_gap"
    LEDGER_MISMATCH = "ledger_mismatch"
    GATE_STATE_CONFLICT = "gate_state_conflict"
    DUPLICATE_ORDER = "duplicate_order"
    ORDER_REJECT = "order_reject"
    DRAWDOWN_BREACH = "drawdown_breach"


REQUIRED_TEMPLATE_FIELDS: tuple[str, ...] = (
    "timeline",
    "impact_scope",
    "direct_cause",
    "root_cause",
    "failed_gate",
    "remediation_actions",
    "regression_test",
    "strategy_pause_required",
)


@dataclass(frozen=True)
class BTCIncidentArtifact:
    incident_id: str
    trigger: BTCIncidentTrigger
    detected_at_utc: datetime
    run_id: str
    strategy_id: str
    severity: str
    template: dict[str, Any]
    source_refs: dict[str, str] = field(default_factory=dict)
    audit_dag_hash: str = ""
    replay_artifact_hash: str = ""
    status: str = "open"

    def __post_init__(self) -> None:
        if not self.incident_id:
            raise ValueError("BTC incident_id is required.")
        if not isinstance(self.trigger, BTCIncidentTrigger):
            object.__setattr__(self, "trigger", _trigger_from_value(self.trigger))
        object.__setattr__(self, "detected_at_utc", ensure_utc(self.detected_at_utc))
        if not self.run_id:
            raise ValueError("BTC incident run_id is required.")
        if not self.strategy_id:
            raise ValueError("BTC incident strategy_id is required.")
        if self.severity not in {"low", "medium", "high", "critical"}:
            raise ValueError("BTC incident severity must be low/medium/high/critical.")

    def validate(self) -> list[str]:
        blockers: list[str] = []
        for field_name in REQUIRED_TEMPLATE_FIELDS:
            if field_name not in self.template:
                blockers.append(f"btc_incident_template_field_missing:{field_name}")
            elif _is_empty_template_value(self.template[field_name]):
                blockers.append(f"btc_incident_template_field_empty:{field_name}")
        if not self.template.get("regression_test") and not self.template.get("rule_update"):
            blockers.append("btc_incident_requires_regression_test_or_rule_update")
        if self.trigger in {
            BTCIncidentTrigger.LEDGER_MISMATCH,
            BTCIncidentTrigger.GATE_STATE_CONFLICT,
            BTCIncidentTrigger.DUPLICATE_ORDER,
            BTCIncidentTrigger.ORDER_REJECT,
            BTCIncidentTrigger.DRAWDOWN_BREACH,
        } and not self.audit_dag_hash:
            blockers.append("btc_incident_audit_dag_hash_missing")
        if self.trigger in {BTCIncidentTrigger.LEDGER_MISMATCH, BTCIncidentTrigger.GATE_STATE_CONFLICT} and not self.replay_artifact_hash:
            blockers.append("btc_incident_replay_artifact_hash_missing")
        if self.trigger in {BTCIncidentTrigger.OKX_API_ERROR, BTCIncidentTrigger.BINANCE_API_ERROR}:
            if "api_response" not in self.source_refs:
                blockers.append("btc_incident_api_response_ref_missing")
        if self.trigger == BTCIncidentTrigger.FUNDING_GAP and "funding_gap_report" not in self.source_refs:
            blockers.append("btc_incident_funding_gap_report_ref_missing")
        return _dedupe(blockers)

    def to_dict(self) -> dict[str, Any]:
        blockers = self.validate()
        payload = {
            "incident_artifact_version": BTC_INCIDENT_ARTIFACT_VERSION,
            "status": "blocked" if blockers else self.status,
            "incident_id": self.incident_id,
            "trigger": self.trigger.value,
            "detected_at_utc": self.detected_at_utc.isoformat(),
            "run_id": self.run_id,
            "strategy_id": self.strategy_id,
            "severity": self.severity,
            "template": dict(self.template),
            "source_refs": dict(self.source_refs),
            "audit_dag_hash": self.audit_dag_hash,
            "replay_artifact_hash": self.replay_artifact_hash,
            "blockers": blockers,
        }
        return apply_btc_artifact_schema(
            payload,
            decision="incident_open" if not blockers else "incident_blocked_pending_required_evidence",
            generated_at_utc=self.detected_at_utc,
            as_of_utc=self.detected_at_utc,
            blockers=blockers,
            warnings=[],
            input_hashes={
                "template": stable_payload_hash(payload["template"]),
                "source_refs": stable_payload_hash(payload["source_refs"]),
                "audit_dag": self.audit_dag_hash,
                "replay": self.replay_artifact_hash,
            },
        )


def build_btc_incident_artifact(
    *,
    incident_id: str,
    trigger: BTCIncidentTrigger | str,
    detected_at_utc: datetime,
    run_id: str,
    strategy_id: str,
    severity: str,
    template: dict[str, Any],
    source_refs: dict[str, str] | None = None,
    audit_dag_hash: str = "",
    replay_artifact_hash: str = "",
    status: str = "open",
) -> dict[str, Any]:
    return BTCIncidentArtifact(
        incident_id=incident_id,
        trigger=_trigger_from_value(trigger),
        detected_at_utc=detected_at_utc,
        run_id=run_id,
        strategy_id=strategy_id,
        severity=severity,
        template=template,
        source_refs=dict(source_refs or {}),
        audit_dag_hash=audit_dag_hash,
        replay_artifact_hash=replay_artifact_hash,
        status=status,
    ).to_dict()


def _trigger_from_value(value: BTCIncidentTrigger | str) -> BTCIncidentTrigger:
    if isinstance(value, BTCIncidentTrigger):
        return value
    return BTCIncidentTrigger(str(value))


def _is_empty_template_value(value: Any) -> bool:
    if value is None or value == "":
        return True
    if isinstance(value, (list, dict, tuple, set)) and not value:
        return True
    return False


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
