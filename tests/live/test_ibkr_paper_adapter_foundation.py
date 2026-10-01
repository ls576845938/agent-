from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from quant_us.core.enums import OrderSide, OrderStatus, OrderType, TimeInForce
from quant_us.core.types import Order
from quant_us.execution.ibkr_broker import IBKRBroker, IBKRBrokerConfig
from quant_us.execution.ibkr_paper_execution_adapter import (
    IBKRPaperAdapterMode,
    IBKRPaperExecutionAdapter,
    IBKRPaperExecutionConfig,
    account_id_hash,
)
from quant_us.live.paper_adapter_contract import evaluate_paper_adapter_contract
from quant_us.live.paper_runtime import PaperRuntime, PaperRuntimeConfig


class FakeIBKRClient:
    def __init__(self) -> None:
        self.connected = False
        self.connect_calls: list[dict[str, object]] = []
        self.disconnect_calls = 0
        self.place_order_calls = 0
        self.cancel_order_calls = 0

    def connect(
        self,
        host: str,
        port: int,
        *,
        clientId: int,
        readonly: bool,
        timeout: float,
    ) -> bool:
        self.connect_calls.append(
            {
                "host": host,
                "port": port,
                "clientId": clientId,
                "readonly": readonly,
                "timeout": timeout,
            }
        )
        self.connected = True
        return True

    def disconnect(self) -> None:
        self.disconnect_calls += 1
        self.connected = False

    def isConnected(self) -> bool:
        return self.connected

    def accountSummary(self) -> list[SimpleNamespace]:
        return [
            SimpleNamespace(account="DU12345", tag="TotalCashValue", value="10000.25"),
            SimpleNamespace(account="DU12345", tag="NetLiquidation", value="12500.50"),
            SimpleNamespace(account="DU12345", tag="BuyingPower", value="25000.00"),
        ]

    def positions(self) -> list[SimpleNamespace]:
        return [
            SimpleNamespace(
                account="DU12345",
                contract=SimpleNamespace(symbol="AAPL"),
                position=5,
                avgCost=190.0,
            )
        ]

    def openTrades(self) -> list[SimpleNamespace]:
        return [
            SimpleNamespace(
                contract=SimpleNamespace(symbol="MSFT"),
                order=SimpleNamespace(
                    orderId=42,
                    permId=420,
                    action="BUY",
                    totalQuantity=3,
                    orderType="LMT",
                    tif="DAY",
                    lmtPrice=410.5,
                    orderRef="client-42",
                ),
                orderStatus=SimpleNamespace(status="Submitted"),
            )
        ]

    def fills(self) -> list[SimpleNamespace]:
        return [
            SimpleNamespace(
                contract=SimpleNamespace(symbol="QQQ"),
                execution=SimpleNamespace(
                    execId="fill-7",
                    orderId=7,
                    side="BOT",
                    shares=2,
                    price=500.25,
                    time=datetime(2026, 8, 6, 1, 2, tzinfo=timezone.utc),
                ),
                commissionReport=SimpleNamespace(commission=0.35),
            )
        ]

    def placeOrder(self, *_args: object, **_kwargs: object) -> None:
        self.place_order_calls += 1

    def cancelOrder(self, *_args: object, **_kwargs: object) -> None:
        self.cancel_order_calls += 1


def _order() -> Order:
    return Order(
        timestamp_utc=datetime(2026, 8, 6, tzinfo=timezone.utc),
        strategy_id="test",
        symbol="SPY",
        side=OrderSide.BUY,
        quantity=1,
        order_type=OrderType.MARKET,
        time_in_force=TimeInForce.DAY,
        client_order_id="client-test",
        status=OrderStatus.RISK_CHECKED,
    )


@pytest.mark.parametrize("port", [4002, 7497])
def test_ibkr_broker_allows_only_documented_paper_ports_without_auto_connect(port: int) -> None:
    client = FakeIBKRClient()
    broker = IBKRBroker(IBKRBrokerConfig(port=port), client=client)

    assert client.connect_calls == []
    assert broker.health_check() == {
        "ok": False,
        "broker": "ibkr",
        "connected": False,
        "endpoint_kind": "paper",
        "host": "127.0.0.1",
        "port": port,
        "readonly": True,
        "submit_capable": False,
        "cancel_capable": False,
    }


@pytest.mark.parametrize(
    ("port", "reason"),
    [
        (4001, "ibkr_live_endpoint_forbidden"),
        (7496, "ibkr_live_endpoint_forbidden"),
        (1234, "ibkr_paper_port_not_allowed"),
    ],
)
def test_ibkr_broker_rejects_live_and_unknown_ports_before_client_access(
    port: int,
    reason: str,
) -> None:
    client = FakeIBKRClient()

    with pytest.raises(ValueError, match=reason):
        IBKRBroker(IBKRBrokerConfig(port=port), client=client)

    assert client.connect_calls == []


def test_ibkr_broker_connect_disconnect_and_readonly_sync_aliases() -> None:
    client = FakeIBKRClient()
    broker = IBKRBroker(
        IBKRBrokerConfig(port=7497, client_id=71, connect_timeout_seconds=3.5),
        client=client,
    )

    broker.connect()

    assert client.connect_calls == [
        {
            "host": "127.0.0.1",
            "port": 7497,
            "clientId": 71,
            "readonly": True,
            "timeout": 3.5,
        }
    ]
    assert broker.health_check()["ok"] is True

    account = broker.sync_account()
    assert account.account_id == "DU12345"
    assert account.cash == 10000.25
    assert account.equity == 12500.50
    assert account.buying_power == 25000.00
    assert account.positions["AAPL"].quantity == 5
    account_alias = broker.get_account()
    assert account_alias.account_id == account.account_id
    assert account_alias.cash == account.cash
    assert account_alias.equity == account.equity
    assert account_alias.buying_power == account.buying_power
    assert account_alias.positions == account.positions

    positions = broker.sync_positions()
    assert positions["AAPL"].avg_price == 190.0
    assert broker.get_positions() == positions

    orders = broker.sync_open_orders()
    assert len(orders) == 1
    assert orders[0].symbol == "MSFT"
    assert orders[0].status is OrderStatus.SUBMITTED
    assert orders[0].broker_order_id == "42"
    assert broker.get_open_orders()[0].broker_order_id == "42"
    assert broker.get_orders()[0].broker_order_id == "42"
    assert broker.poll_orders()[0].broker_order_id == "42"

    fills = broker.sync_fills()
    assert len(fills) == 1
    assert fills[0].fill_id == "fill-7"
    assert fills[0].symbol == "QQQ"
    assert fills[0].side is OrderSide.BUY
    assert fills[0].commission == 0.35
    assert broker.get_fills(order_id="7") == fills

    broker.disconnect()
    assert client.disconnect_calls == 1
    assert broker.health_check()["connected"] is False


def test_ibkr_submit_and_cancel_are_hard_fail_closed_without_client_write_calls() -> None:
    client = FakeIBKRClient()
    broker = IBKRBroker(IBKRBrokerConfig(port=4002), client=client)
    broker.connect()

    with pytest.raises(RuntimeError, match="paper_submit_disabled_fail_closed"):
        broker.submit_order(_order())
    with pytest.raises(RuntimeError, match="ibkr_paper_cancel_disabled_fail_closed"):
        broker.cancel_order("42")

    assert client.place_order_calls == 0
    assert client.cancel_order_calls == 0
    assert broker.submit_call_count == 0
    assert broker.cancel_call_count == 0
    assert broker.submit_attempt_count == 1
    assert broker.cancel_attempt_count == 1


def test_ibkr_contract_requires_explicit_enable_and_keeps_writes_fail_closed() -> None:
    capabilities = IBKRBroker.contract_capabilities()

    disabled = evaluate_paper_adapter_contract(
        "ibkr_paper",
        adapter_enabled=True,
        adapter_factory_present=True,
        adapter_capabilities=capabilities,
        env_requested=False,
        ibkr_host="127.0.0.1",
        ibkr_port=7497,
    )
    assert disabled.effective_backend == "simulated"
    assert disabled.adapter_ready is False
    assert disabled.fail_closed is True
    assert disabled.reason == "ibkr_paper_adapter_not_explicitly_enabled"

    enabled = evaluate_paper_adapter_contract(
        "ibkr_paper",
        adapter_enabled=True,
        adapter_factory_present=True,
        adapter_capabilities=capabilities,
        env_requested=True,
        ibkr_host="127.0.0.1",
        ibkr_port=7497,
    )
    assert enabled.effective_backend == "ibkr_paper"
    assert enabled.adapter_ready is True
    assert enabled.read_only_sync_capable is True
    assert enabled.submit_capable is False
    assert enabled.fail_closed is True
    assert enabled.submit_blocked_reason == "ibkr_paper_submit_cancel_disabled_fail_closed"
    assert enabled.allowed_ports == [4002, 7497]
    assert enabled.readonly is True

    alias = evaluate_paper_adapter_contract(
        "ibkr",
        adapter_enabled=True,
        adapter_factory_present=True,
        adapter_capabilities=capabilities,
        env_requested=True,
        ibkr_host="127.0.0.1",
        ibkr_port=4002,
    )
    assert alias.requested_backend == "ibkr"
    assert alias.effective_backend == "ibkr_paper"
    assert alias.adapter_ready is True

    live = evaluate_paper_adapter_contract(
        "ibkr_paper",
        adapter_enabled=True,
        adapter_factory_present=True,
        adapter_capabilities=capabilities,
        env_requested=True,
        ibkr_host="127.0.0.1",
        ibkr_port=4001,
    )
    assert live.effective_backend == "simulated"
    assert live.adapter_ready is False
    assert live.reason == "ibkr_live_endpoint_forbidden"


def _runtime_execution_adapter(client: FakeIBKRClient, port: int) -> IBKRPaperExecutionAdapter:
    return IBKRPaperExecutionAdapter(
        IBKRPaperExecutionConfig(
            mode=IBKRPaperAdapterMode.READONLY,
            port=port,
            account_hash_allowlist=(account_id_hash("DU12345"),),
        ),
        client=client,
    )


def _market_data_factory() -> SimpleNamespace:
    return SimpleNamespace(vendor="ibkr", bar_size="1d")


def test_ibkr_runtime_blocks_before_factory_without_explicit_enable(tmp_path) -> None:
    client = FakeIBKRClient()
    broker = _runtime_execution_adapter(client, 7497)
    runtime = PaperRuntime(
        PaperRuntimeConfig(
            paper_broker="ibkr_paper",
            ibkr_port=7497,
            ibkr_adapter_mode="readonly",
            ibkr_account_hash_allowlist=(account_id_hash("DU12345"),),
            data_vendor="ibkr",
            bar_size="1d",
            ledger_root=str(tmp_path / "ledger"),
            data_root=str(tmp_path / "data"),
        ),
        ibkr_paper_adapter_factory=lambda: broker,
        ibkr_market_data_adapter_factory=_market_data_factory,
    )

    with patch.dict("os.environ", {}, clear=True):
        gate = runtime._check_runtime_entry_gate()
        with pytest.raises(RuntimeError, match="ibkr_paper_adapter_not_explicitly_enabled"):
            runtime.bootstrap()

    assert gate["ok"] is False
    assert client.connect_calls == []


def test_ibkr_runtime_explicit_enable_builds_only_injected_readonly_adapter() -> None:
    client = FakeIBKRClient()
    injected = _runtime_execution_adapter(client, 4002)
    runtime = PaperRuntime(
        PaperRuntimeConfig(
            paper_broker="ibkr_paper",
            ibkr_port=4002,
            ibkr_client_id=9,
            ibkr_adapter_mode="readonly",
            ibkr_account_hash_allowlist=(account_id_hash("DU12345"),),
            data_vendor="ibkr",
            bar_size="1d",
        ),
        ibkr_paper_adapter_factory=lambda: injected,
        ibkr_market_data_adapter_factory=_market_data_factory,
    )

    with patch.dict(
        "os.environ",
        {"QUANT_ENABLE_IBKR_PAPER_ADAPTER": "true"},
        clear=True,
    ):
        contract = runtime._paper_adapter_contract()
        gate = runtime._check_runtime_entry_gate()
        built = runtime._build_paper_broker()

    assert contract["effective_backend"] == "ibkr_paper"
    assert contract["submit_capable"] is False
    assert gate["ok"] is True
    assert built is injected
    assert client.connect_calls == []

    built.connect()
    assert client.connect_calls[0]["readonly"] is True

    with pytest.raises(RuntimeError, match="paper_submit_disabled_fail_closed"):
        built.submit_order(_order())
    assert client.place_order_calls == 0
    built.disconnect()


def test_existing_simulated_contract_behavior_is_unchanged() -> None:
    contract = evaluate_paper_adapter_contract("simulated")

    assert contract.effective_backend == "simulated"
    assert contract.fail_closed is False
    assert contract.reason == "simulated_paper_backend"
