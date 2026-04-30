from __future__ import annotations

from dataclasses import dataclass

from quant_us.execution.paper_broker import PaperBroker


@dataclass
class IBKRBrokerConfig:
    host: str = "127.0.0.1"
    port: int = 7497
    client_id: int = 1


class IBKRBroker(PaperBroker):
    broker_name = "ibkr"

    def __init__(self, config: IBKRBrokerConfig) -> None:
        super().__init__(broker_name="ibkr")
        self.config = config

    def submit_order(self, order):
        raise NotImplementedError("IBKR adapter boundary is present; gateway wiring is a later phase")
