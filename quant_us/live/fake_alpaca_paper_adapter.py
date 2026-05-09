from __future__ import annotations

from dataclasses import dataclass, field

from quant_us.backtest.broker_simulator import SimulatedBroker
from quant_us.core.types import AccountState, Fill, Order, Position
from quant_us.live.paper_adapter_contract import (
    REQUIRED_PAPER_ADAPTER_CAPABILITIES,
    normalize_paper_adapter_capabilities,
)


@dataclass
class FakeAlpacaPaperBrokerAdapter(SimulatedBroker):
    """Local-only fake Alpaca paper adapter used for contract tests.

    This never connects to Alpaca. It extends the simulated broker with the
    sync/poll surface required by the paper adapter contract.
    """

    broker_name: str = "alpaca_paper_fake"
    fail_on_call: str | None = None
    sync_call_log: list[str] = field(default_factory=list)
    submit_call_count: int = 0

    @classmethod
    def contract_capabilities(cls) -> dict[str, bool]:
        return normalize_paper_adapter_capabilities(
            {name: True for name in REQUIRED_PAPER_ADAPTER_CAPABILITIES}
        )

    def _record_sync_call(self, name: str) -> None:
        self.sync_call_log.append(name)
        if self.fail_on_call == name:
            raise RuntimeError(f"{name}_failed")

    def submit_order(self, order: Order) -> Order:
        self.submit_call_count += 1
        return super().submit_order(order)

    def poll_orders(self) -> list[Order]:
        self._record_sync_call("poll_orders")
        return self.get_orders()

    def sync_fills(self, order_id: str | None = None) -> list[Fill]:
        self._record_sync_call("sync_fills")
        return self.get_fills(order_id=order_id)

    def sync_account(self) -> AccountState:
        self._record_sync_call("sync_account")
        return self.get_account()

    def sync_positions(self) -> dict[str, Position]:
        self._record_sync_call("sync_positions")
        return self.get_positions()

    def readiness_report(self) -> dict[str, object]:
        return {
            "adapter": self.broker_name,
            "network": "disabled",
            "paper_only": True,
            "submit_surface": True,
            "fake_adapter": True,
        }
