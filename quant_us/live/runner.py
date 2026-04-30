from __future__ import annotations

from dataclasses import dataclass, field

from quant_us.execution.oms import OrderManagementSystem
from quant_us.live.heartbeat import Heartbeat
from quant_us.live.reconciliation_service import ReconciliationService
from quant_us.risk.kill_switch import KillSwitch


@dataclass
class LiveReadinessReport:
    status: str
    checks: dict[str, bool]
    errors: list[str] = field(default_factory=list)

    @property
    def ready(self) -> bool:
        return self.status == "ready"


@dataclass
class LiveRunnerConfig:
    require_reconciliation_clean: bool = True
    allow_live_orders: bool = False


@dataclass
class LiveRunner:
    oms: OrderManagementSystem
    heartbeat: Heartbeat
    reconciliation: ReconciliationService | None = None
    kill_switch: KillSwitch | None = None
    config: LiveRunnerConfig = field(default_factory=LiveRunnerConfig)

    def check_readiness(self) -> LiveReadinessReport:
        checks = {
            "heartbeat": True,
            "kill_switch_clear": not (self.kill_switch and self.kill_switch.triggered),
            "reconciliation": True,
            "live_orders_enabled": self.config.allow_live_orders,
        }
        errors: list[str] = []
        if not checks["kill_switch_clear"]:
            errors.append(f"kill_switch_triggered:{self.kill_switch.reason if self.kill_switch else ''}")
        if self.config.require_reconciliation_clean and self.reconciliation is not None:
            report = self.reconciliation.reconcile_positions()
            checks["reconciliation"] = report["status"] == "clean"
            if not checks["reconciliation"]:
                errors.append("reconciliation_breaks_detected")
        if not checks["live_orders_enabled"]:
            errors.append("live_orders_disabled")
        status = "ready" if not errors else "blocked"
        return LiveReadinessReport(status=status, checks=checks, errors=errors)

    def start(self, dry_run: bool = True) -> LiveReadinessReport:
        self.heartbeat.beat()
        report = self.check_readiness()
        if not report.ready:
            return report
        if dry_run:
            return report
        raise NotImplementedError("Live market-data loop is deferred until the broker paper run is validated")
