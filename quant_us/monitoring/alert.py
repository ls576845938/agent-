from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Alert:
    severity: str
    message: str
    context: dict[str, object]


class AlertSink:
    def send(self, alert: Alert) -> None:
        raise NotImplementedError("Wire Telegram/email/Slack sinks after live mode is ready")
