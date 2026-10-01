from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from quant_us.monitoring.alert_sinks import AlertNotification
from quant_us.monitoring.runtime_incidents import (
    IncidentSeverity,
    IncidentStateError,
    IncidentStatus,
    IncidentType,
    JsonlIncidentStore,
    RuntimeIncidentManager,
    stable_incident_id,
)


UTC = timezone.utc


class RecordingSink:
    def __init__(self) -> None:
        self.notifications: list[AlertNotification] = []

    def send(self, alert: AlertNotification) -> None:
        self.notifications.append(alert)


def _clock() -> list[datetime]:
    return [
        datetime(2026, 8, 7, 1, 0, tzinfo=UTC),
        datetime(2026, 8, 7, 1, 0, 1, tzinfo=UTC),
        datetime(2026, 8, 7, 1, 0, 2, tzinfo=UTC),
        datetime(2026, 8, 7, 1, 0, 3, tzinfo=UTC),
    ]


def test_open_has_stable_identity_critical_default_and_audit_linkage(tmp_path: Path) -> None:
    moments = iter(_clock())
    sink = RecordingSink()
    manager = RuntimeIncidentManager(tmp_path / "incidents.jsonl", alert_sink=sink, clock=lambda: next(moments))

    incident = manager.open(
        IncidentType.UNKNOWN_BROKER_ORDER,
        "ibkr.paper",
        "unknown broker order",
        context={"order_id": "internal-1", "api_token": "do-not-persist"},
        identity_key="order:internal-1",
        audit_link="audit:runtime:1",
    )

    assert incident.incident_id == stable_incident_id("UNKNOWN_BROKER_ORDER", "ibkr.paper", "order:internal-1")
    assert incident.severity is IncidentSeverity.CRITICAL
    assert incident.status is IncidentStatus.OPEN
    assert incident.occurrence_count == 1
    assert incident.audit_links == ("audit:runtime:1",)
    assert incident.context["api_token"] == "[REDACTED]"
    assert "do-not-persist" not in (tmp_path / "incidents.jsonl").read_text(encoding="utf-8")
    assert len(sink.notifications) == 1
    assert sink.notifications[0].incident_id == incident.incident_id
    assert sink.notifications[0].event == "opened"


def test_duplicate_observations_coalesce_without_alert_storm(tmp_path: Path) -> None:
    moments = iter(_clock())
    sink = RecordingSink()
    manager = RuntimeIncidentManager(tmp_path / "incidents.jsonl", alert_sink=sink, clock=lambda: next(moments))

    first = manager.open("MARKET_DATA_STALE", "market:aapl", "stale tick", identity_key="AAPL")
    second = manager.open("MARKET_DATA_STALE", "market:aapl", "still stale", identity_key="AAPL")

    assert second.incident_id == first.incident_id
    assert second.occurrence_count == 2
    assert second.opened_at == first.opened_at
    assert second.last_seen_at > first.last_seen_at
    assert second.message == "still stale"
    assert len(sink.notifications) == 1
    assert len(JsonlIncidentStore(tmp_path / "incidents.jsonl").read_events()) == 2


def test_acknowledge_then_resolve_and_persist_across_restart(tmp_path: Path) -> None:
    path = tmp_path / "runtime_incidents.jsonl"
    moments = iter(_clock())
    manager = RuntimeIncidentManager(path, clock=lambda: next(moments))
    opened = manager.open(
        "RECONCILIATION_FAILED",
        "ibkr.paper",
        "reconciliation failed",
        identity_key="account",
        audit_id="audit:recon:1",
    )
    acknowledged = manager.acknowledge(opened.incident_id, "operator-1", audit_ref="audit:ack:1")
    resolved = manager.resolve(opened.incident_id, message="reconciled", audit_link="audit:resolve:1")

    assert acknowledged.status is IncidentStatus.ACKNOWLEDGED
    assert acknowledged.acknowledged_by == "operator-1"
    assert resolved.status is IncidentStatus.RESOLVED
    assert resolved.resolved_at is not None
    assert resolved.audit_links == ("audit:recon:1", "audit:ack:1", "audit:resolve:1")

    reopened_store = JsonlIncidentStore(path)
    restored = reopened_store.get(opened.incident_id)
    assert restored == resolved
    assert reopened_store.list(include_resolved=False) == []
    assert len(reopened_store.history(opened.incident_id)) == 3


def test_resolved_incident_reopens_with_same_identity_and_new_occurrence(tmp_path: Path) -> None:
    moments = iter(_clock())
    manager = RuntimeIncidentManager(tmp_path / "incidents.jsonl", clock=lambda: next(moments))
    first = manager.open("IBKR_DISCONNECTED", "ibkr.paper", "offline", identity_key="session")
    manager.resolve(first.incident_id)
    reopened = manager.open("IBKR_DISCONNECTED", "ibkr.paper", "offline again", identity_key="session")

    assert reopened.incident_id == first.incident_id
    assert reopened.status is IncidentStatus.OPEN
    assert reopened.occurrence_count == 2
    assert reopened.resolved_at is None
    assert reopened.acknowledged_at is None


def test_resolved_incident_cannot_be_acknowledged(tmp_path: Path) -> None:
    manager = RuntimeIncidentManager(tmp_path / "incidents.jsonl")
    opened = manager.open("RUNTIME_HALTED", "runtime", "halted")
    manager.resolve(opened.incident_id)

    with pytest.raises(IncidentStateError):
        manager.acknowledge(opened.incident_id, "operator")


def test_invalid_append_only_record_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "runtime_incidents.jsonl"
    path.write_text(json.dumps({"schema_version": "wrong"}) + "\n", encoding="utf-8")

    with pytest.raises(Exception):
        JsonlIncidentStore(path).list()
