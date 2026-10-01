from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from quant_us.core.enums import OrderSide, OrderStatus, OrderType, TimeInForce
from quant_us.core.types import Order
from quant_us.execution.ibkr_paper_execution_adapter import (
    IBKRAdapterError,
    IBKRPaperAdapterMode,
    IBKRPaperExecutionAdapter,
    IBKRPaperExecutionConfig,
    account_id_hash,
)


class FakeIBKRExecutionClient:
    def __init__(self, *, account_id: str = "DU-PAPER-001") -> None:
        self.account_id = account_id
        self.connected = False
        self.connect_calls: list[dict[str, object]] = []
        self.disconnect_calls = 0
        self.place_order_calls: list[tuple[object, object]] = []
        self.cancel_order_calls: list[object] = []
        self.open_orders: list[SimpleNamespace] = []
        self.fill_rows: list[SimpleNamespace] = []
        self.account_rows = [
            SimpleNamespace(account=account_id, tag="TotalCashValue", value="10000.25"),
            SimpleNamespace(account=account_id, tag="NetLiquidation", value="12500.50"),
            SimpleNamespace(account=account_id, tag="BuyingPower", value="25000.00"),
        ]
        self.position_rows = [
            SimpleNamespace(
                contract=SimpleNamespace(symbol="AAPL"),
                position=5,
                avgCost=190.0,
                marketPrice=191.0,
                unrealizedPNL=5.0,
            )
        ]
        self.next_order_id = 100
        self.next_fill_id = 1
        self.next_submit_status = "Submitted"
        self.next_reject: tuple[str, str] | None = None
        self.connect_failures = 0
        self.duplicate_client_id = False

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
        if self.duplicate_client_id:
            error = RuntimeError("Error 326: client ID already in use")
            error.errorCode = 326
            raise error
        if self.connect_failures:
            self.connect_failures -= 1
            return False
        self.connected = True
        return True

    def disconnect(self) -> None:
        self.disconnect_calls += 1
        self.connected = False

    def isConnected(self) -> bool:
        return self.connected

    def accountSummary(self) -> list[SimpleNamespace]:
        return list(self.account_rows)

    def positions(self) -> list[SimpleNamespace]:
        return list(self.position_rows)

    def openTrades(self) -> list[SimpleNamespace]:
        return list(self.open_orders)

    def fills(self) -> list[SimpleNamespace]:
        return list(self.fill_rows)

    def placeOrder(self, contract: object, payload: object) -> SimpleNamespace:
        self.place_order_calls.append((contract, payload))
        broker_order_id = self.next_order_id
        self.next_order_id += 1
        status = self.next_submit_status
        if self.next_reject is not None:
            status = "Inactive"
            reject_code, reject_reason = self.next_reject
        else:
            reject_code, reject_reason = "", ""
        response_order = SimpleNamespace(
            orderId=broker_order_id,
            action=getattr(payload, "action"),
            totalQuantity=getattr(payload, "totalQuantity"),
            orderType=getattr(payload, "orderType"),
            tif=getattr(payload, "tif"),
            lmtPrice=getattr(payload, "lmtPrice"),
            orderRef=getattr(payload, "orderRef"),
        )
        response_status = SimpleNamespace(
            status=status,
            filled=0,
            remaining=getattr(payload, "totalQuantity"),
            errorCode=reject_code,
            reason=reject_reason,
        )
        response = SimpleNamespace(
            contract=contract,
            order=response_order,
            orderStatus=response_status,
        )
        if status not in {"Inactive", "Rejected"}:
            self.open_orders.append(response)
        return response

    def cancelOrder(self, payload: object) -> SimpleNamespace:
        self.cancel_order_calls.append(payload)
        broker_order_id = str(getattr(payload, "orderId", getattr(payload, "order_id", "")))
        for trade in self.open_orders:
            trade_id = str(getattr(trade.order, "orderId", ""))
            if trade_id == broker_order_id:
                trade.orderStatus.status = "Cancelled"
        return SimpleNamespace(orderStatus=SimpleNamespace(status="Cancelled"))


def _adapter(
    client: FakeIBKRExecutionClient,
    *,
    mode: IBKRPaperAdapterMode = IBKRPaperAdapterMode.READONLY,
    port: int = 7497,
) -> IBKRPaperExecutionAdapter:
    return IBKRPaperExecutionAdapter(
        IBKRPaperExecutionConfig(
            mode=mode,
            port=port,
            client_id=71,
            account_hash_allowlist=(account_id_hash(client.account_id),),
            reconnect_attempts=3,
        ),
        client=client,
    )


def _order(
    *,
    client_order_id: str = "client-test-1",
    order_type: OrderType = OrderType.MARKET,
    limit_price: float | None = None,
    quantity: float = 3,
) -> Order:
    return Order(
        timestamp_utc=datetime(2026, 8, 6, tzinfo=timezone.utc),
        strategy_id="test-strategy",
        symbol="SPY",
        side=OrderSide.BUY,
        quantity=quantity,
        order_type=order_type,
        time_in_force=TimeInForce.DAY,
        client_order_id=client_order_id,
        limit_price=limit_price,
        status=OrderStatus.RISK_CHECKED,
    )


def test_import_and_constructor_are_local_only_and_default_disabled() -> None:
    client = FakeIBKRExecutionClient()
    adapter = IBKRPaperExecutionAdapter(
        IBKRPaperExecutionConfig(account_hash_allowlist=()),
        client=client,
    )

    assert client.connect_calls == []
    report = adapter.readiness_report()
    assert report["state"] == "disabled"
    assert report["disabled"] is True
    assert report["readonly"] is False
    assert report["paper_submit"] is False
    assert report["fail_closed"] is True

    with pytest.raises(IBKRAdapterError, match="adapter_disabled"):
        adapter.connect()
    assert client.connect_calls == []


@pytest.mark.parametrize("port", [4001, 7496])
def test_live_ports_are_hard_rejected_before_client_access(port: int) -> None:
    client = FakeIBKRExecutionClient()
    with pytest.raises(IBKRAdapterError) as exc_info:
        _adapter(client, port=port)
    assert exc_info.value.code == "ibkr_live_endpoint_forbidden"
    assert client.connect_calls == []


@pytest.mark.parametrize("port", [4002, 7497])
def test_readonly_connect_verifies_hash_and_never_writes(port: int) -> None:
    client = FakeIBKRExecutionClient()
    adapter = _adapter(client, port=port)

    report = adapter.connect()
    assert report["state"] == "readonly"
    assert report["readonly"] is True
    assert report["paper_submit"] is False
    assert client.connect_calls[0]["port"] == port
    assert client.connect_calls[0]["readonly"] is True
    assert len(adapter.replay_open_orders()) == 0

    with pytest.raises(IBKRAdapterError) as submit_error:
        adapter.submit_order(_order())
    assert submit_error.value.code == "paper_submit_disabled_fail_closed"
    with pytest.raises(IBKRAdapterError) as cancel_error:
        adapter.cancel_order("missing")
    assert cancel_error.value.code == "paper_submit_disabled_fail_closed"
    assert client.place_order_calls == []
    assert client.cancel_order_calls == []


def test_account_hash_mismatch_fails_closed_without_exposing_account_id() -> None:
    client = FakeIBKRExecutionClient()
    adapter = IBKRPaperExecutionAdapter(
        IBKRPaperExecutionConfig(
            mode=IBKRPaperAdapterMode.READONLY,
            account_hash_allowlist=(account_id_hash("different-account"),),
        ),
        client=client,
    )

    with pytest.raises(IBKRAdapterError) as exc_info:
        adapter.connect()
    assert exc_info.value.code == "account_not_allowlisted"
    assert client.connected is False
    assert client.account_id not in str(exc_info.value)
    assert "account_hash" in exc_info.value.to_dict()["details"]


def test_paper_submit_supports_market_limit_day_and_client_order_ref_idempotency() -> None:
    client = FakeIBKRExecutionClient()
    adapter = _adapter(client, mode=IBKRPaperAdapterMode.PAPER_SUBMIT)
    adapter.connect()

    market = adapter.submit_order(_order(client_order_id="market-1"))
    assert market.status is OrderStatus.SUBMITTED
    assert market.broker_order_id == "100"
    assert client.place_order_calls[0][1].orderType == "MKT"
    assert client.place_order_calls[0][1].tif == "DAY"
    assert client.place_order_calls[0][1].orderRef == "market-1"

    duplicate = adapter.submit_order(_order(client_order_id="market-1"))
    assert duplicate is market
    assert len(client.place_order_calls) == 1

    limit = adapter.submit_order(
        _order(client_order_id="limit-1", order_type=OrderType.LIMIT, limit_price=500.25)
    )
    assert limit.status is OrderStatus.SUBMITTED
    assert client.place_order_calls[1][1].orderType == "LMT"
    assert client.place_order_calls[1][1].lmtPrice == 500.25


def test_duplicate_client_order_ref_with_changed_fingerprint_is_rejected() -> None:
    client = FakeIBKRExecutionClient()
    adapter = _adapter(client, mode=IBKRPaperAdapterMode.PAPER_SUBMIT)
    adapter.connect()
    adapter.submit_order(_order(client_order_id="same-ref", quantity=1))

    with pytest.raises(IBKRAdapterError) as exc_info:
        adapter.submit_order(_order(client_order_id="same-ref", quantity=2))
    assert exc_info.value.code == "duplicate_client_order_ref"
    assert len(client.place_order_calls) == 1


def test_partial_fill_commission_reject_and_cancel_are_structured() -> None:
    client = FakeIBKRExecutionClient()
    adapter = _adapter(client, mode=IBKRPaperAdapterMode.PAPER_SUBMIT)
    adapter.connect()
    order = adapter.submit_order(_order(client_order_id="partial-1", quantity=3))

    trade = client.open_orders[0]
    trade.orderStatus.status = "PartiallyFilled"
    trade.orderStatus.filled = 1
    trade.orderStatus.remaining = 2
    adapter.replay_open_orders()
    assert order.status is OrderStatus.PARTIALLY_FILLED
    assert order.metadata["filled_quantity"] == 1

    client.fill_rows.append(
        SimpleNamespace(
            contract=SimpleNamespace(symbol="SPY"),
            execution=SimpleNamespace(
                execId="exec-1",
                orderId=100,
                side="BOT",
                shares=1,
                price=500.0,
                time=datetime(2026, 8, 6, 1, 2, tzinfo=timezone.utc),
            ),
            commissionReport=SimpleNamespace(commission=0.35),
        )
    )
    fills = adapter.sync_fills(order.broker_order_id)
    assert len(fills) == 1
    assert fills[0].commission == 0.35
    assert order.metadata["commission"] == 0.35
    assert order.status is OrderStatus.PARTIALLY_FILLED
    repeated_fills = adapter.sync_fills(order.broker_order_id)
    assert len(repeated_fills) == 1
    assert order.metadata["filled_quantity"] == 1
    assert order.metadata["commission"] == 0.35

    client.fill_rows[0].commissionReport.commission = 9.99
    with pytest.raises(IBKRAdapterError) as duplicate_exc:
        adapter.sync_fills(order.broker_order_id)
    assert duplicate_exc.value.code == "duplicate_fill_conflict"
    client.fill_rows[0].commissionReport.commission = 0.35

    cancelled = adapter.cancel_order(order.order_id)
    assert cancelled.status is OrderStatus.CANCELLED
    assert len(client.cancel_order_calls) == 1
    assert str(client.cancel_order_calls[0].orderId) == "100"

    client.next_reject = (201, "insufficient buying power")
    rejected = adapter.submit_order(_order(client_order_id="reject-1"))
    assert rejected.status is OrderStatus.REJECTED
    assert rejected.metadata["reject"]["reject_code"] == "201"
    assert rejected.metadata["reject"]["reject_reason"] == "insufficient buying power"


def test_duplicate_client_id_is_not_retried_and_reconnect_is_bounded() -> None:
    client = FakeIBKRExecutionClient()
    client.duplicate_client_id = True
    adapter = _adapter(client)

    with pytest.raises(IBKRAdapterError) as exc_info:
        adapter.reconnect(max_attempts=3)
    assert exc_info.value.code == "duplicate_client_id"
    assert len(client.connect_calls) == 1

    client.duplicate_client_id = False
    client.connect_failures = 2
    report = adapter.reconnect(max_attempts=3)
    assert report["connected"] is True
    assert len(client.connect_calls) == 4


def test_open_order_replay_reuses_existing_order_ref_without_new_submit() -> None:
    client = FakeIBKRExecutionClient()
    client.open_orders.append(
        SimpleNamespace(
            contract=SimpleNamespace(symbol="SPY"),
            order=SimpleNamespace(
                orderId=77,
                action="BUY",
                totalQuantity=2,
                orderType="MKT",
                tif="DAY",
                orderRef="replayed-ref",
            ),
            orderStatus=SimpleNamespace(status="Submitted", filled=0, remaining=2),
        )
    )
    adapter = _adapter(client, mode=IBKRPaperAdapterMode.PAPER_SUBMIT)
    adapter.connect()
    order = adapter.submit_order(_order(client_order_id="replayed-ref", quantity=2))

    assert order.broker_order_id == "77"
    assert len(client.place_order_calls) == 0


def test_no_gateway_or_socket_is_used_by_import_constructor_or_fake_tests() -> None:
    client = FakeIBKRExecutionClient()
    adapter = _adapter(client)
    assert adapter.readiness_report()["no_auto_connect"] is True
    assert client.connect_calls == []
