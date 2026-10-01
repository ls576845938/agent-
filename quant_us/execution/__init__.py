"""OMS, broker adapters, and routing boundaries."""
from __future__ import annotations

# Module-level imports from brokers
from quant_us.execution.alpaca_broker import AlpacaBroker, AlpacaBrokerConfig
from quant_us.execution.broker_base import BrokerBase
from quant_us.execution.ibkr_broker import IBKRBroker
from quant_us.execution.ledger import JsonlLedgerStore
from quant_us.execution.oms import OrderManagementSystem
from quant_us.execution.order_lifecycle import OrderLifecycleAction, OrderLifecycleConfig, OrderLifecycleManager
from quant_us.execution.order_router import OrderRouter
from quant_us.execution.paper_broker import PaperBroker

# -- Optional modules (created by Phase F agents) ---------------------------
try:
    from quant_us.execution.order_polling import OrderPollResult, OrderPollingLoop  # noqa: F401
except ImportError:
    pass

try:
    from quant_us.execution.fill_sync import FillSync, FillSyncResult  # noqa: F401
except ImportError:
    pass

try:
    from quant_us.execution.broker_state_sync import BrokerStateSync, BrokerSyncReport  # noqa: F401
except ImportError:
    pass


__all__ = [
    "AlpacaBroker",
    "AlpacaBrokerConfig",
    "BrokerBase",
    "IBKRBroker",
    "JsonlLedgerStore",
    "OrderManagementSystem",
    "OrderLifecycleAction",
    "OrderLifecycleConfig",
    "OrderLifecycleManager",
    "OrderRouter",
    "PaperBroker",
]
