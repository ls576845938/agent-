"""Durable runtime incident lifecycle for fail-closed operations.

The store is an append-only JSONL event stream.  Each lifecycle event carries
the complete incident snapshot, so a process restart reconstructs the latest
state without a mutable runtime database.  Stable identity is derived from
``type``, ``source`` and an optional caller-supplied ``identity_key``; repeated
observations coalesce into one incident and increment ``occurrence_count``.

This module is intentionally standalone.  Runtime, backend, and frontend
wiring belongs to the integration owner and can inject the store path and an
``AlertSink`` when those boundaries are ready.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import Enum
import json
import os
from pathlib import Path
import re
import threading
from typing import Any, Callable, Iterable, Mapping, Protocol, Sequence

from quant_shared.core.serialization import canonical_json_dumps, sha256_hex
from quant_shared.core.time import ensure_utc, isoformat_utc, utc_now

from quant_us.monitoring.alert_sinks import AlertNotification, AlertSink, _deliver


INCIDENT_EVENT_SCHEMA_VERSION = "quant_us_runtime_incident_event_v1"
INCIDENT_SCHEMA_VERSION = "quant_us_runtime_incident_v1"
DEFAULT_INCIDENT_FILENAME = "runtime_incidents.jsonl"


class IncidentStatus(str, Enum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RESOLVED = "RESOLVED"


class IncidentSeverity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class IncidentType(str, Enum):
    IBKR_DISCONNECTED = "IBKR_DISCONNECTED"
    IBKR_RECONNECT_FAILED = "IBKR_RECONNECT_FAILED"
    IBKR_RECONNECTED = "IBKR_RECONNECTED"
    BROKER_TRUTH_STALE = "BROKER_TRUTH_STALE"
    MARKET_DATA_STALE = "MARKET_DATA_STALE"
    RECONCILIATION_FAILED = "RECONCILIATION_FAILED"
    UNKNOWN_BROKER_ORDER = "UNKNOWN_BROKER_ORDER"
    UNKNOWN_EXECUTION = "UNKNOWN_EXECUTION"
    POSITION_MISMATCH = "POSITION_MISMATCH"
    CASH_MISMATCH = "CASH_MISMATCH"
    ACCOUNT_MISMATCH = "ACCOUNT_MISMATCH"
    KILL_SWITCH_TRIPPED = "KILL_SWITCH_TRIPPED"
    RUNTIME_HALTED = "RUNTIME_HALTED"
    RECOVERY_PENDING = "RECOVERY_PENDING"


CRITICAL_INCIDENT_TYPES = frozenset(
    {
        IncidentType.UNKNOWN_BROKER_ORDER.value,
        IncidentType.UNKNOWN_EXECUTION.value,
        IncidentType.RECONCILIATION_FAILED.value,
        IncidentType.ACCOUNT_MISMATCH.value,
        IncidentType.RUNTIME_HALTED.value,
        IncidentType.KILL_SWITCH_TRIPPED.value,
    }
)

_SEVERITY_RANK = {
    IncidentSeverity.INFO: 0,
    IncidentSeverity.WARNING: 1,
    IncidentSeverity.CRITICAL: 2,
}
_SENSITIVE_KEY = re.compile(
    r"(?:api[_-]?key|authorization|cookie|credential|passphrase|password|private[_-]?key|secret|token)",
    re.IGNORECASE,
)
_SENSITIVE_TEXT = re.compile(
    r"(?i)\b(api[_-]?key|authorization|cookie|credential|passphrase|password|private[_-]?key|secret|token)\b"
    r"\s*[:=]\s*(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)"
)
_BEARER_TEXT = re.compile(r"(?i)\bBearer\s+[^\s,;]+")


class IncidentStoreError(RuntimeError):
    """Base class for durable incident store failures."""


class IncidentStoreCorruptionError(IncidentStoreError):
    """Raised when an append-only record cannot be safely replayed."""


class IncidentIdentityConflictError(IncidentStoreError):
    """Raised when one stable ID is used for incompatible incident metadata."""


class IncidentStateError(IncidentStoreError):
    """Raised when a lifecycle transition is invalid."""


def _normalise_type(value: IncidentType | str) -> str:
    if isinstance(value, IncidentType):
        return value.value
    normalised = str(value).strip().upper()
    if not normalised:
        raise ValueError("incident type is required")
    return normalised


def _normalise_severity(value: IncidentSeverity | str | None, *, incident_type: str) -> IncidentSeverity:
    if value is None:
        return IncidentSeverity.CRITICAL if incident_type in CRITICAL_INCIDENT_TYPES else IncidentSeverity.WARNING
    if isinstance(value, IncidentSeverity):
        return value
    normalised = str(value).strip().upper()
    aliases = {
        "LOW": IncidentSeverity.INFO,
        "MEDIUM": IncidentSeverity.WARNING,
        "HIGH": IncidentSeverity.CRITICAL,
        "ERROR": IncidentSeverity.CRITICAL,
    }
    if normalised in aliases:
        return aliases[normalised]
    try:
        return IncidentSeverity(normalised)
    except ValueError as exc:
        raise ValueError(f"unsupported incident severity: {value}") from exc


def _normalise_status(value: IncidentStatus | str) -> IncidentStatus:
    if isinstance(value, IncidentStatus):
        return value
    try:
        return IncidentStatus(str(value).strip().upper())
    except ValueError as exc:
        raise ValueError(f"unsupported incident status: {value}") from exc


def _enum_value(value: Any) -> str:
    return str(value.value) if isinstance(value, Enum) else str(value)


def _redact_text(value: Any) -> str:
    text = str(value)
    text = _SENSITIVE_TEXT.sub(lambda match: f"{match.group(1)}=[REDACTED]", text)
    return _BEARER_TEXT.sub("Bearer [REDACTED]", text)


def _json_safe(value: Any, *, key: str = "") -> Any:
    if key and _SENSITIVE_KEY.search(key):
        return "[REDACTED]"
    if value is None or isinstance(value, (str, bool, int, float)):
        if isinstance(value, str):
            return _redact_text(value)
        return value
    if isinstance(value, datetime):
        return isoformat_utc(value)
    if isinstance(value, Enum):
        return _json_safe(value.value, key=key)
    if isinstance(value, Mapping):
        return {str(item_key): _json_safe(item, key=str(item_key)) for item_key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_safe(item) for item in value]
    if isinstance(value, Path):
        return value.as_posix()
    # Do not serialize arbitrary object reprs; a repr can contain credentials.
    return _redact_text(type(value).__name__)


def _normalise_context(value: Mapping[str, Any] | None) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise TypeError("incident context must be a mapping")
    return dict(_json_safe(value))


def _normalise_links(
    audit_link: str | None = None,
    audit_links: Iterable[str] | None = None,
    audit_id: str | None = None,
    audit_ref: str | None = None,
) -> tuple[str, ...]:
    values: list[str] = []
    if audit_links is not None:
        if isinstance(audit_links, str):
            values.append(audit_links)
        else:
            values.extend(str(value) for value in audit_links)
    for value in (audit_link, audit_id, audit_ref):
        if value is not None:
            values.append(str(value))
    result: list[str] = []
    for value in values:
        cleaned = _redact_text(value).strip()
        if cleaned and cleaned not in result:
            result.append(cleaned)
    return tuple(result)


def _merge_links(*groups: Iterable[str]) -> tuple[str, ...]:
    result: list[str] = []
    for group in groups:
        for value in group:
            cleaned = _redact_text(value).strip()
            if cleaned and cleaned not in result:
                result.append(cleaned)
    return tuple(result)


def incident_identity_key(
    incident_type: IncidentType | str,
    source: str,
    identity_key: str | None = None,
) -> str:
    """Return canonical identity material used for stable incident IDs."""

    normalised_type = _normalise_type(incident_type)
    normalised_source = _redact_text(source).strip()
    if not normalised_source:
        raise ValueError("incident source is required")
    normalised_key = _redact_text(identity_key).strip() if identity_key is not None else ""
    return canonical_json_dumps(
        {
            "identity_key": normalised_key,
            "source": normalised_source,
            "type": normalised_type,
        }
    )


def stable_incident_id(
    incident_type: IncidentType | str,
    source: str,
    identity_key: str | None = None,
) -> str:
    """Derive a deterministic ID independent of process or restart state."""

    return f"incident-{sha256_hex(incident_identity_key(incident_type, source, identity_key))}"


# Descriptive aliases used by integration code.
incident_id_for = stable_incident_id
build_incident_id = stable_incident_id


@dataclass(frozen=True)
class Incident:
    """Immutable latest-state view of one runtime incident."""

    incident_id: str
    type: IncidentType | str
    severity: IncidentSeverity | str
    source: str
    opened_at: datetime
    last_seen_at: datetime
    resolved_at: datetime | None = None
    acknowledged_at: datetime | None = None
    acknowledged_by: str | None = None
    status: IncidentStatus | str = IncidentStatus.OPEN
    message: str = ""
    context: Mapping[str, Any] = field(default_factory=dict)
    occurrence_count: int = 1
    audit_links: Sequence[str] = field(default_factory=tuple)
    schema_version: str = INCIDENT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "incident_id", str(self.incident_id).strip())
        if not self.incident_id:
            raise ValueError("incident_id is required")
        object.__setattr__(self, "type", _normalise_type(self.type))
        object.__setattr__(self, "severity", _normalise_severity(self.severity, incident_type=str(self.type)))
        source = _redact_text(self.source).strip()
        if not source:
            raise ValueError("incident source is required")
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "opened_at", ensure_utc(self.opened_at))
        object.__setattr__(self, "last_seen_at", ensure_utc(self.last_seen_at))
        if self.resolved_at is not None:
            object.__setattr__(self, "resolved_at", ensure_utc(self.resolved_at))
        if self.acknowledged_at is not None:
            object.__setattr__(self, "acknowledged_at", ensure_utc(self.acknowledged_at))
        if self.acknowledged_by is not None:
            acknowledged_by = _redact_text(self.acknowledged_by).strip()
            object.__setattr__(self, "acknowledged_by", acknowledged_by or None)
        object.__setattr__(self, "status", _normalise_status(self.status))
        object.__setattr__(self, "message", _redact_text(self.message))
        object.__setattr__(self, "context", _normalise_context(self.context))
        count = int(self.occurrence_count)
        if count < 1:
            raise ValueError("occurrence_count must be positive")
        object.__setattr__(self, "occurrence_count", count)
        links = (self.audit_links,) if isinstance(self.audit_links, str) else self.audit_links
        object.__setattr__(self, "audit_links", _merge_links(links))
        if str(self.schema_version).strip() != INCIDENT_SCHEMA_VERSION:
            raise ValueError(f"unsupported incident schema_version: {self.schema_version}")

    @property
    def audit_link(self) -> str | None:
        """Compatibility accessor for callers that have one audit reference."""

        return self.audit_links[0] if self.audit_links else None

    @property
    def audit_id(self) -> str | None:
        return self.audit_link

    @property
    def audit_linkage(self) -> tuple[str, ...]:
        return tuple(self.audit_links)

    @property
    def is_active(self) -> bool:
        return self.status is not IncidentStatus.RESOLVED

    def to_dict(self) -> dict[str, Any]:
        return {
            "incident_id": self.incident_id,
            "type": _enum_value(self.type),
            "severity": _enum_value(self.severity),
            "source": self.source,
            "opened_at": isoformat_utc(self.opened_at),
            "last_seen_at": isoformat_utc(self.last_seen_at),
            "resolved_at": isoformat_utc(self.resolved_at) if self.resolved_at else None,
            "acknowledged_at": isoformat_utc(self.acknowledged_at) if self.acknowledged_at else None,
            "acknowledged_by": self.acknowledged_by,
            "status": _enum_value(self.status),
            "message": self.message,
            "context": _normalise_context(self.context),
            "occurrence_count": self.occurrence_count,
            "audit_links": list(self.audit_links),
            "audit_linkage": list(self.audit_links),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "Incident":
        if not isinstance(payload, Mapping):
            raise IncidentStoreCorruptionError("incident snapshot must be an object")

        def _timestamp(name: str, *, required: bool) -> datetime | None:
            value = payload.get(name)
            if value is None and not required:
                return None
            if value is None:
                raise IncidentStoreCorruptionError(f"incident field missing: {name}")
            try:
                return ensure_utc(datetime.fromisoformat(str(value).replace("Z", "+00:00")))
            except (TypeError, ValueError) as exc:
                raise IncidentStoreCorruptionError(f"invalid incident timestamp: {name}") from exc

        try:
            audit_payload = payload.get("audit")
            nested_audit_links = audit_payload.get("links", ()) if isinstance(audit_payload, Mapping) else ()
            return cls(
                incident_id=str(payload["incident_id"]),
                type=str(payload["type"]),
                severity=str(payload.get("severity", "WARNING")),
                source=str(payload["source"]),
                opened_at=_timestamp("opened_at", required=True),  # type: ignore[arg-type]
                last_seen_at=_timestamp("last_seen_at", required=True),  # type: ignore[arg-type]
                resolved_at=_timestamp("resolved_at", required=False),
                acknowledged_at=_timestamp("acknowledged_at", required=False),
                acknowledged_by=payload.get("acknowledged_by"),
                status=str(payload.get("status", "OPEN")),
                message=str(payload.get("message", "")),
                context=payload.get("context") if isinstance(payload.get("context"), Mapping) else {},
                occurrence_count=int(payload.get("occurrence_count", 1)),
                audit_links=payload.get("audit_links", payload.get("audit_linkage", nested_audit_links)),
                schema_version=str(payload.get("schema_version", INCIDENT_SCHEMA_VERSION)),
            )
        except IncidentStoreCorruptionError:
            raise
        except (KeyError, TypeError, ValueError) as exc:
            raise IncidentStoreCorruptionError("invalid incident snapshot") from exc


class IncidentStore(Protocol):
    """Storage contract consumed by :class:`RuntimeIncidentManager`."""

    def upsert(self, incident: Incident) -> Incident:
        ...

    def acknowledge(
        self,
        incident_id: str,
        *,
        acknowledged_by: str,
        acknowledged_at: datetime,
        audit_links: Iterable[str] = (),
    ) -> Incident:
        ...

    def resolve(
        self,
        incident_id: str,
        *,
        resolved_at: datetime,
        message: str | None = None,
        audit_links: Iterable[str] = (),
    ) -> Incident:
        ...

    def get(self, incident_id: str) -> Incident | None:
        ...

    def list(self, *, include_resolved: bool = True) -> list[Incident]:
        ...


_STORE_LOCKS_GUARD = threading.Lock()
_STORE_LOCKS: dict[Path, threading.RLock] = {}


def _store_lock(path: Path) -> threading.RLock:
    resolved = path.resolve()
    with _STORE_LOCKS_GUARD:
        lock = _STORE_LOCKS.get(resolved)
        if lock is None:
            lock = threading.RLock()
            _STORE_LOCKS[resolved] = lock
        return lock


class JsonlIncidentStore:
    """Append-only JSONL incident store with restart-safe state replay."""

    def __init__(self, path_or_root: str | Path) -> None:
        candidate = Path(path_or_root)
        if candidate.suffix.lower() == ".jsonl" or candidate.exists() and candidate.is_file():
            self.path = candidate
        else:
            self.path = candidate / DEFAULT_INCIDENT_FILENAME
        self.path = self.path.expanduser().resolve()
        self._lock = _store_lock(self.path)

    def upsert(self, incident: Incident) -> Incident:
        """Create or coalesce one observation and append its resulting state."""

        with self._lock:
            states = self._read_states_unlocked()
            existing = states.get(incident.incident_id)
            if existing is None:
                result = incident
                event = "opened"
            else:
                if existing.type != incident.type or existing.source != incident.source:
                    raise IncidentIdentityConflictError(
                        f"incident identity conflict for {incident.incident_id}"
                    )
                result = self._coalesce(existing, incident)
                event = "reopened" if existing.status is IncidentStatus.RESOLVED else "coalesced"
            self._append_event_unlocked(event, result)
            return result

    def open(self, incident: Incident) -> Incident:
        return self.upsert(incident)

    def open_incident(self, incident: Incident) -> Incident:
        return self.upsert(incident)

    def acknowledge(
        self,
        incident_id: str,
        *,
        acknowledged_by: str,
        acknowledged_at: datetime,
        audit_links: Iterable[str] = (),
    ) -> Incident:
        with self._lock:
            existing = self._require_unlocked(incident_id)
            if existing.status is IncidentStatus.RESOLVED:
                raise IncidentStateError("resolved incident cannot be acknowledged")
            links = _merge_links(existing.audit_links, audit_links)
            actor = _redact_text(acknowledged_by).strip()
            if not actor:
                raise ValueError("acknowledged_by is required")
            timestamp = ensure_utc(acknowledged_at)
            if existing.status is IncidentStatus.ACKNOWLEDGED and tuple(existing.audit_links) == links:
                return existing
            result = replace(
                existing,
                status=IncidentStatus.ACKNOWLEDGED,
                acknowledged_at=timestamp,
                acknowledged_by=actor,
                audit_links=links,
            )
            self._append_event_unlocked("acknowledged", result, audit_links=links, occurred_at=timestamp)
            return result

    def acknowledge_incident(
        self,
        incident_id: str,
        acknowledged_by: str,
        *,
        acknowledged_at: datetime | None = None,
        audit_link: str | None = None,
        audit_links: Iterable[str] = (),
    ) -> Incident:
        return self.acknowledge(
            incident_id,
            acknowledged_by=acknowledged_by,
            acknowledged_at=ensure_utc(acknowledged_at or utc_now()),
            audit_links=_normalise_links(audit_link, audit_links),
        )

    def resolve(
        self,
        incident_id: str,
        *,
        resolved_at: datetime,
        message: str | None = None,
        audit_links: Iterable[str] = (),
    ) -> Incident:
        with self._lock:
            existing = self._require_unlocked(incident_id)
            timestamp = ensure_utc(resolved_at)
            links = _merge_links(existing.audit_links, audit_links)
            if (
                existing.status is IncidentStatus.RESOLVED
                and tuple(existing.audit_links) == links
                and (message is None or _redact_text(message) == existing.message)
            ):
                return existing
            result = replace(
                existing,
                status=IncidentStatus.RESOLVED,
                resolved_at=timestamp,
                message=_redact_text(message) if message is not None else existing.message,
                audit_links=links,
            )
            self._append_event_unlocked("resolved", result, audit_links=links, occurred_at=timestamp)
            return result

    def resolve_incident(
        self,
        incident_id: str,
        *,
        resolved_at: datetime | None = None,
        message: str | None = None,
        audit_link: str | None = None,
        audit_links: Iterable[str] = (),
    ) -> Incident:
        return self.resolve(
            incident_id,
            resolved_at=ensure_utc(resolved_at or utc_now()),
            message=message,
            audit_links=_normalise_links(audit_link, audit_links),
        )

    def get(self, incident_id: str) -> Incident | None:
        with self._lock:
            return self._read_states_unlocked().get(str(incident_id))

    def get_incident(self, incident_id: str) -> Incident | None:
        return self.get(incident_id)

    def list(self, *, include_resolved: bool = True) -> list[Incident]:
        with self._lock:
            incidents = list(self._read_states_unlocked().values())
        if not include_resolved:
            incidents = [incident for incident in incidents if incident.is_active]
        return sorted(incidents, key=lambda incident: (incident.opened_at, incident.incident_id))

    def list_incidents(self, *, include_resolved: bool = True) -> list[Incident]:
        return self.list(include_resolved=include_resolved)

    def list_active(self) -> list[Incident]:
        return self.list(include_resolved=False)

    def active_incidents(self) -> list[Incident]:
        return self.list_active()

    def read_events(self) -> list[dict[str, Any]]:
        with self._lock:
            return self._read_events_unlocked()

    def history(self, incident_id: str) -> list[dict[str, Any]]:
        target = str(incident_id)
        return [
            event
            for event in self.read_events()
            if isinstance(event.get("incident"), Mapping)
            and str(event["incident"].get("incident_id")) == target
        ]

    @staticmethod
    def _coalesce(existing: Incident, incoming: Incident) -> Incident:
        merged_context = dict(existing.context)
        merged_context.update(incoming.context)
        severity = max(
            (existing.severity, incoming.severity),
            key=lambda value: _SEVERITY_RANK[_normalise_severity(value, incident_type=existing.type)],
        )
        if existing.status is IncidentStatus.RESOLVED:
            return replace(
                existing,
                status=IncidentStatus.OPEN,
                resolved_at=None,
                acknowledged_at=None,
                acknowledged_by=None,
                last_seen_at=max(existing.last_seen_at, incoming.last_seen_at),
                severity=severity,
                message=incoming.message or existing.message,
                context=merged_context,
                occurrence_count=existing.occurrence_count + incoming.occurrence_count,
                audit_links=_merge_links(existing.audit_links, incoming.audit_links),
            )
        return replace(
            existing,
            last_seen_at=max(existing.last_seen_at, incoming.last_seen_at),
            severity=severity,
            message=incoming.message or existing.message,
            context=merged_context,
            occurrence_count=existing.occurrence_count + incoming.occurrence_count,
            audit_links=_merge_links(existing.audit_links, incoming.audit_links),
        )

    def _require_unlocked(self, incident_id: str) -> Incident:
        incident = self._read_states_unlocked().get(str(incident_id))
        if incident is None:
            raise KeyError(f"unknown incident: {incident_id}")
        return incident

    def _read_states_unlocked(self) -> dict[str, Incident]:
        states: dict[str, Incident] = {}
        for event in self._read_events_unlocked():
            snapshot = event.get("incident")
            if not isinstance(snapshot, Mapping):
                raise IncidentStoreCorruptionError("incident event missing snapshot")
            incident = Incident.from_dict(snapshot)
            states[incident.incident_id] = incident
        return states

    def _read_events_unlocked(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        events: list[dict[str, Any]] = []
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            raise IncidentStoreError(f"cannot read incident store: {self.path}") from exc
        for line_number, line in enumerate(lines, start=1):
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise IncidentStoreCorruptionError(f"invalid incident event at line {line_number}") from exc
            if not isinstance(event, dict) or event.get("schema_version") != INCIDENT_EVENT_SCHEMA_VERSION:
                raise IncidentStoreCorruptionError(f"unsupported incident event at line {line_number}")
            events.append(event)
        return events

    def _append_event_unlocked(
        self,
        event_name: str,
        incident: Incident,
        *,
        audit_links: Iterable[str] = (),
        occurred_at: datetime | None = None,
    ) -> None:
        links = _merge_links(incident.audit_links, audit_links)
        event = {
            "schema_version": INCIDENT_EVENT_SCHEMA_VERSION,
            "event": str(event_name).strip().lower(),
            "event_type": str(event_name).strip().lower(),
            "occurred_at_utc": isoformat_utc(occurred_at or incident.last_seen_at),
            "incident": incident.to_dict(),
            "audit_links": list(links),
            "audit_linkage": list(links),
            "audit": {"links": list(links)},
        }
        encoded = (canonical_json_dumps(event) + "\n").encode("utf-8")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("ab") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
        except OSError as exc:
            raise IncidentStoreError(f"cannot append incident event: {self.path}") from exc


# Explicit aliases make the persistence boundary discoverable to integrations.
PersistentIncidentStore = JsonlIncidentStore
FileIncidentStore = JsonlIncidentStore


class RuntimeIncidentManager:
    """Service facade combining identity, persistence, and alert dispatch."""

    def __init__(
        self,
        store: IncidentStore | str | Path,
        alert_sink: AlertSink | Any | None = None,
        *,
        clock: Callable[[], datetime] | Any | None = None,
    ) -> None:
        self.store: IncidentStore = JsonlIncidentStore(store) if isinstance(store, (str, Path)) else store
        self.alert_sink = alert_sink
        self.clock = clock or utc_now
        self.sink_errors: list[str] = []

    def open(
        self,
        incident_type: IncidentType | str | None = None,
        source: str = "",
        message: str = "",
        severity: IncidentSeverity | str | None = None,
        *,
        context: Mapping[str, Any] | None = None,
        identity_key: str | None = None,
        opened_at: datetime | None = None,
        last_seen_at: datetime | None = None,
        audit_link: str | None = None,
        audit_links: Iterable[str] | None = None,
        audit_id: str | None = None,
        audit_ref: str | None = None,
        type: IncidentType | str | None = None,
        event_type: IncidentType | str | None = None,
    ) -> Incident:
        selected_type = incident_type or type or event_type
        if selected_type is None:
            raise ValueError("incident type is required")
        now = ensure_utc(opened_at or self._now())
        seen = ensure_utc(last_seen_at or now)
        normalised_type = _normalise_type(selected_type)
        normalised_source = _redact_text(source).strip()
        links = _normalise_links(audit_link, audit_links, audit_id, audit_ref)
        incident = Incident(
            incident_id=stable_incident_id(normalised_type, normalised_source, identity_key),
            type=normalised_type,
            severity=_normalise_severity(severity, incident_type=normalised_type),
            source=normalised_source,
            opened_at=now,
            last_seen_at=seen,
            message=message,
            context=context or {},
            audit_links=links,
        )
        existing = self.store.get(incident.incident_id)
        result = self.store.upsert(incident)
        event = "opened" if existing is None else ("reopened" if existing.status is IncidentStatus.RESOLVED else "coalesced")
        if existing is None or existing.status is IncidentStatus.RESOLVED:
            self._dispatch(result, event=event)
        return result

    def open_incident(self, *args: Any, **kwargs: Any) -> Incident:
        return self.open(*args, **kwargs)

    def raise_incident(self, *args: Any, **kwargs: Any) -> Incident:
        return self.open(*args, **kwargs)

    def record(self, *args: Any, **kwargs: Any) -> Incident:
        return self.open(*args, **kwargs)

    def acknowledge(
        self,
        incident_id: str,
        acknowledged_by: str = "operator",
        *,
        acknowledged_at: datetime | None = None,
        audit_link: str | None = None,
        audit_links: Iterable[str] | None = None,
        audit_id: str | None = None,
        audit_ref: str | None = None,
        by: str | None = None,
    ) -> Incident:
        actor = by if by is not None else acknowledged_by
        links = _normalise_links(audit_link, audit_links, audit_id, audit_ref)
        previous = self.store.get(incident_id)
        ack_timestamp = ensure_utc(acknowledged_at or self._now())
        result = self.store.acknowledge(
            incident_id,
            acknowledged_by=actor,
            acknowledged_at=ack_timestamp,
            audit_links=links,
        )
        if previous != result:
            self._dispatch(result, event="acknowledged", occurred_at=ack_timestamp)
        return result

    def acknowledge_incident(self, *args: Any, **kwargs: Any) -> Incident:
        return self.acknowledge(*args, **kwargs)

    def resolve(
        self,
        incident_id: str,
        *,
        resolved_at: datetime | None = None,
        message: str | None = None,
        audit_link: str | None = None,
        audit_links: Iterable[str] | None = None,
        audit_id: str | None = None,
        audit_ref: str | None = None,
    ) -> Incident:
        links = _normalise_links(audit_link, audit_links, audit_id, audit_ref)
        previous = self.store.get(incident_id)
        resolve_timestamp = ensure_utc(resolved_at or self._now())
        result = self.store.resolve(
            incident_id,
            resolved_at=resolve_timestamp,
            message=message,
            audit_links=links,
        )
        if previous != result:
            self._dispatch(result, event="resolved", occurred_at=resolve_timestamp)
        return result

    def resolve_incident(self, *args: Any, **kwargs: Any) -> Incident:
        return self.resolve(*args, **kwargs)

    def get(self, incident_id: str) -> Incident | None:
        return self.store.get(incident_id)

    def list(self, *, include_resolved: bool = True) -> list[Incident]:
        return self.store.list(include_resolved=include_resolved)

    def list_active(self) -> list[Incident]:
        return self.store.list(include_resolved=False)

    def _now(self) -> datetime:
        candidate = self.clock() if callable(self.clock) else self.clock.now()
        return ensure_utc(candidate)

    def _dispatch(self, incident: Incident, *, event: str, occurred_at: datetime | None = None) -> None:
        if self.alert_sink is None:
            return
        notification = AlertNotification(
            incident=incident,
            event=event,
            occurred_at_utc=occurred_at or incident.last_seen_at,
        )
        try:
            _deliver(self.alert_sink, notification)
        except Exception as exc:  # noqa: BLE001 - persistence remains authoritative.
            # Do not retain third-party exception text: clients can echo auth
            # material in their error strings.
            self.sink_errors.append(type(exc).__name__)


# Short alias for callers that prefer the domain name.
IncidentManager = RuntimeIncidentManager


__all__ = [
    "CRITICAL_INCIDENT_TYPES",
    "DEFAULT_INCIDENT_FILENAME",
    "FileIncidentStore",
    "Incident",
    "IncidentIdentityConflictError",
    "IncidentManager",
    "IncidentSeverity",
    "IncidentStateError",
    "IncidentStatus",
    "IncidentStore",
    "IncidentStoreCorruptionError",
    "IncidentStoreError",
    "IncidentType",
    "INCIDENT_EVENT_SCHEMA_VERSION",
    "INCIDENT_SCHEMA_VERSION",
    "JsonlIncidentStore",
    "PersistentIncidentStore",
    "RuntimeIncidentManager",
    "build_incident_id",
    "incident_id_for",
    "incident_identity_key",
    "stable_incident_id",
]
