from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from quant_us.execution.broker_base import BrokerBase
from quant_us.execution.ledger import JsonlLedgerStore
from quant_us.live.state_reconciler import StateReconciler


class ReconciliationService:
    def __init__(self, ledger_dir: str | Path, broker: BrokerBase) -> None:
        self.ledger = JsonlLedgerStore(ledger_dir)
        self.broker = broker
        self.reconciler = StateReconciler()

    def reconcile_positions(self, tolerance: float = 1e-6) -> dict[str, object]:
        local_positions = self.ledger.latest_positions_from_fills()
        broker_positions = self.broker.get_positions()
        report = self.reconciler.report(local_positions, broker_positions, tolerance=tolerance)
        return asdict(report)
