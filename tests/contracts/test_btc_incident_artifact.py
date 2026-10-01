from __future__ import annotations

from datetime import datetime, timezone

import pytest

from quant_crypto.monitoring.incident import (
    BTC_INCIDENT_ARTIFACT_VERSION,
    BTCIncidentTrigger,
    build_btc_incident_artifact,
)


TS = datetime(2026, 6, 26, 8, 0, tzinfo=timezone.utc)
HASH = "a" * 64
REPLAY_HASH = "b" * 64


def _template(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "timeline": [{"at": TS.isoformat(), "event": "detected"}],
        "impact_scope": "paper BTC only",
        "direct_cause": "fixture direct cause",
        "root_cause": "fixture root cause",
        "failed_gate": "fixture gate",
        "remediation_actions": ["repair fixture"],
        "regression_test": "tests/contracts/test_btc_incident_artifact.py",
        "strategy_pause_required": True,
    }
    values.update(overrides)
    return values


def _incident(trigger: BTCIncidentTrigger, **overrides: object) -> dict[str, object]:
    source_refs = {
        BTCIncidentTrigger.OKX_API_ERROR: {"api_response": "artifacts/errors/okx.json"},
        BTCIncidentTrigger.BINANCE_API_ERROR: {"api_response": "artifacts/errors/binance.json"},
        BTCIncidentTrigger.FUNDING_GAP: {"funding_gap_report": "artifacts/btc_cost_model/latest/funding_gap.json"},
    }.get(trigger, {})
    kwargs: dict[str, object] = {
        "incident_id": f"incident_{trigger.value}",
        "trigger": trigger,
        "detected_at_utc": TS,
        "run_id": "btc_incident_run_001",
        "strategy_id": "btc_intraday_short_cycle",
        "severity": "high",
        "template": _template(),
        "source_refs": source_refs,
        "audit_dag_hash": HASH,
        "replay_artifact_hash": REPLAY_HASH,
    }
    kwargs.update(overrides)
    return build_btc_incident_artifact(**kwargs)


@pytest.mark.parametrize("trigger", list(BTCIncidentTrigger))
def test_btc_incident_artifact_supports_required_trigger_types(trigger: BTCIncidentTrigger) -> None:
    payload = _incident(trigger)

    assert payload["incident_artifact_version"] == BTC_INCIDENT_ARTIFACT_VERSION
    assert payload["status"] == "open"
    assert payload["trigger"] == trigger.value
    assert payload["blockers"] == []
    assert len(payload["artifact_hash"]) == 64
    assert payload["input_hashes"]["template"]
    assert payload["input_hashes"]["source_refs"]


def test_btc_incident_blocks_missing_template_fields() -> None:
    template = _template()
    template.pop("root_cause")

    payload = _incident(BTCIncidentTrigger.DATA_INTERRUPTION, template=template)

    assert payload["status"] == "blocked"
    assert "btc_incident_template_field_missing:root_cause" in payload["blockers"]


def test_btc_incident_requires_regression_test_or_rule_update() -> None:
    template = _template(regression_test="")

    payload = _incident(BTCIncidentTrigger.DATA_INTERRUPTION, template=template)

    assert payload["status"] == "blocked"
    assert "btc_incident_template_field_empty:regression_test" in payload["blockers"]
    assert "btc_incident_requires_regression_test_or_rule_update" in payload["blockers"]

    payload_with_rule = _incident(
        BTCIncidentTrigger.DATA_INTERRUPTION,
        template=_template(regression_test="", rule_update="docs/knowledge/05_monitoring_replay/incident_review.md"),
    )
    assert "btc_incident_requires_regression_test_or_rule_update" not in payload_with_rule["blockers"]


@pytest.mark.parametrize(
    "trigger",
    [
        BTCIncidentTrigger.LEDGER_MISMATCH,
        BTCIncidentTrigger.GATE_STATE_CONFLICT,
        BTCIncidentTrigger.DUPLICATE_ORDER,
        BTCIncidentTrigger.DRAWDOWN_BREACH,
    ],
)
def test_btc_incident_requires_audit_dag_for_trade_path_incidents(trigger: BTCIncidentTrigger) -> None:
    payload = _incident(trigger, audit_dag_hash="")

    assert payload["status"] == "blocked"
    assert "btc_incident_audit_dag_hash_missing" in payload["blockers"]


@pytest.mark.parametrize(
    "trigger",
    [BTCIncidentTrigger.LEDGER_MISMATCH, BTCIncidentTrigger.GATE_STATE_CONFLICT],
)
def test_btc_incident_requires_replay_artifact_for_replay_relevant_incidents(trigger: BTCIncidentTrigger) -> None:
    payload = _incident(trigger, replay_artifact_hash="")

    assert payload["status"] == "blocked"
    assert "btc_incident_replay_artifact_hash_missing" in payload["blockers"]


@pytest.mark.parametrize(
    "trigger",
    [BTCIncidentTrigger.OKX_API_ERROR, BTCIncidentTrigger.BINANCE_API_ERROR],
)
def test_btc_incident_requires_api_response_ref_for_exchange_api_errors(trigger: BTCIncidentTrigger) -> None:
    payload = _incident(trigger, source_refs={})

    assert payload["status"] == "blocked"
    assert "btc_incident_api_response_ref_missing" in payload["blockers"]


def test_btc_incident_requires_funding_gap_source_ref() -> None:
    payload = _incident(BTCIncidentTrigger.FUNDING_GAP, source_refs={})

    assert payload["status"] == "blocked"
    assert "btc_incident_funding_gap_report_ref_missing" in payload["blockers"]


def test_btc_incident_rejects_invalid_severity() -> None:
    with pytest.raises(ValueError, match="severity"):
        _incident(BTCIncidentTrigger.DATA_INTERRUPTION, severity="urgent")
