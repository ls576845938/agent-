"""Alert sink contracts for the runtime incident lifecycle.

The incident service owns durable state.  Sinks are deliberately injected so
that an operator console or an external notifier can subscribe without making
the incident store depend on a network client or credentials.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Iterable, Protocol, TYPE_CHECKING, runtime_checkable

from quant_shared.core.time import ensure_utc, isoformat_utc

if TYPE_CHECKING:  # pragma: no cover - imports are only for type checkers.
    from quant_us.monitoring.runtime_incidents import Incident


@dataclass(frozen=True)
class AlertNotification:
    """Notification emitted after a durable incident state change.

    ``incident`` is intentionally typed as ``Any`` here to keep this module
    independent from the incident model and avoid an import cycle.  The
    forwarding properties make the notification convenient for small sinks
    while retaining the complete incident object for richer integrations.
    """

    incident: Any
    event: str
    occurred_at_utc: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "event", str(self.event).strip().lower())
        if not self.event:
            raise ValueError("alert event is required")
        object.__setattr__(self, "occurred_at_utc", ensure_utc(self.occurred_at_utc))

    @property
    def incident_id(self) -> str:
        return str(self.incident.incident_id)

    @property
    def type(self) -> str:
        return str(self.incident.type)

    @property
    def severity(self) -> str:
        value = getattr(self.incident, "severity", "")
        return str(getattr(value, "value", value))

    @property
    def status(self) -> str:
        value = getattr(self.incident, "status", "")
        return str(getattr(value, "value", value))

    @property
    def message(self) -> str:
        return str(getattr(self.incident, "message", ""))

    @property
    def context(self) -> Any:
        return getattr(self.incident, "context", {})

    def to_dict(self) -> dict[str, Any]:
        incident = self.incident
        if hasattr(incident, "to_dict"):
            incident_payload = incident.to_dict()
        else:  # pragma: no cover - defensive for a third-party sink adapter.
            incident_payload = {"incident_id": self.incident_id}
        return {
            "event": self.event,
            "occurred_at_utc": isoformat_utc(self.occurred_at_utc),
            "incident": incident_payload,
        }


@runtime_checkable
class AlertSink(Protocol):
    """Minimal injected sink contract.

    Implementations must not be assumed to be network-backed.  The runtime
    service calls ``send`` only after the append-only store has durably written
    the state transition.  A sink may therefore be a UI bridge, test fake, or
    an adapter for a future Telegram/Email/Webhook integration.
    """

    def send(self, alert: AlertNotification) -> None:
        ...


@runtime_checkable
class IncidentAlertEmitter(Protocol):
    """Optional richer sink shape supporting the lifecycle event name."""

    def emit(self, incident: "Incident", *, event: str) -> None:
        ...


@runtime_checkable
class TelegramAlertSink(Protocol):
    """Future Telegram adapter contract; no token or transport is read here."""

    def send(self, alert: AlertNotification) -> None:
        ...


@runtime_checkable
class EmailAlertSink(Protocol):
    """Future Email adapter contract; credentials stay outside this module."""

    def send(self, alert: AlertNotification) -> None:
        ...


@runtime_checkable
class WebhookAlertSink(Protocol):
    """Future Webhook adapter contract; URL/auth belong to the integration."""

    def send(self, alert: AlertNotification) -> None:
        ...


class NullAlertSink:
    """Explicit no-op sink for deployments that only need durable storage."""

    def send(self, alert: AlertNotification) -> None:
        return None


class CallbackAlertSink:
    """Adapt a callback into an :class:`AlertSink` without network behavior."""

    def __init__(self, callback: Callable[[AlertNotification], None]) -> None:
        if not callable(callback):
            raise TypeError("callback must be callable")
        self._callback = callback

    def send(self, alert: AlertNotification) -> None:
        self._callback(alert)


class FanoutAlertSink:
    """Send a notification to multiple sinks.

    A failing external adapter does not undo the already durable incident or
    prevent another sink from receiving it.  Errors are retained for operator
    diagnostics and can be inspected through ``errors``.
    """

    def __init__(self, sinks: Iterable[AlertSink | IncidentAlertEmitter]) -> None:
        self._sinks = tuple(sinks)
        self.errors: list[str] = []

    @property
    def sinks(self) -> tuple[AlertSink | IncidentAlertEmitter, ...]:
        return self._sinks

    def send(self, alert: AlertNotification) -> None:
        self.errors.clear()
        for sink in self._sinks:
            try:
                _deliver(sink, alert)
            except Exception as exc:  # noqa: BLE001 - one sink cannot erase state.
                # Keep diagnostics free of exception text because third-party
                # clients occasionally echo credentials in their errors.
                self.errors.append(type(exc).__name__)


def _deliver(sink: AlertSink | IncidentAlertEmitter, alert: AlertNotification) -> None:
    """Deliver to either the richer ``emit`` shape or the minimal ``send``."""

    emitter = getattr(sink, "emit", None)
    if callable(emitter):
        emitter(alert.incident, event=alert.event)
        return
    notifier = getattr(sink, "notify", None)
    if callable(notifier):
        try:
            notifier(alert.incident, event=alert.event)
        except TypeError:
            notifier(alert)
        return
    sender = getattr(sink, "send", None)
    if not callable(sender):
        raise TypeError("alert sink must provide send() or emit()")
    sender(alert)


# ``CompositeAlertSink`` is a descriptive alias used by integrations.
CompositeAlertSink = FanoutAlertSink


__all__ = [
    "AlertNotification",
    "AlertSink",
    "CallbackAlertSink",
    "CompositeAlertSink",
    "EmailAlertSink",
    "FanoutAlertSink",
    "IncidentAlertEmitter",
    "NullAlertSink",
    "TelegramAlertSink",
    "WebhookAlertSink",
    "_deliver",
]
