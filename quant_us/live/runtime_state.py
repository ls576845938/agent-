from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from quant_us.core.clock import utc_now
from quant_us.live.modes import RuntimeMode


class RuntimeLifecycleState(str, Enum):
    CREATED = "created"
    BOOTSTRAPPED = "bootstrapped"
    READY = "ready"
    RUNNING = "running"
    RECONCILING = "reconciling"
    SHUTTING_DOWN = "shutting_down"
    STOPPED = "stopped"
    BLOCKED = "blocked"
    ERROR = "error"


@dataclass
class RuntimeHealth:
    status: str = "unknown"
    checks: dict[str, bool] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status in {"ready", "running"}


@dataclass
class LiveRuntimeState:
    mode: RuntimeMode
    lifecycle: RuntimeLifecycleState = RuntimeLifecycleState.CREATED
    started_at: datetime | None = None
    updated_at: datetime = field(default_factory=utc_now)
    health: RuntimeHealth = field(default_factory=RuntimeHealth)
    cycles: int = 0
    submitted_orders: int = 0

    def transition(self, lifecycle: RuntimeLifecycleState) -> None:
        self.lifecycle = lifecycle
        self.updated_at = utc_now()
