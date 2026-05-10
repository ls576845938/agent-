from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

import pytest

from quant_us.core.enums import OrderSide, OrderStatus, OrderType, TimeInForce
from quant_us.core.types import AccountState, Fill, Order, OrderIntent, RiskDecision
from quant_us.execution.alpaca_broker import AlpacaBroker, AlpacaBrokerConfig
from quant_us.execution.broker_state_sync import BrokerStateSync
from quant_us.execution.ledger import JsonlLedgerStore
from quant_us.execution.oms import OrderManagementSystem
from quant_us.execution.order_polling import OrderPollingLoop
from quant_us.execution.paper_broker import PaperBroker
from quant_us.risk.kill_switch import KillSwitch, KillSwitchConfig


TS = datetime(2026, 5, 10, 14, 30, tzinfo=timezone.utc)


def make_order(
    *,
    client_order_id: str = "coid_1",
    order_id: str = "ord_1",
    status: OrderStatus = OrderStatus.SUBMITTED,
    side: OrderSide = OrderSide.BUY,
    quantity: float = 10.0,
) -> Order:
    return Order(
        timestamp_utc=TS,
        strategy_id="test",
        symbol="AAPL",
        side=side,
        quantity=quantity,
        order_type=OrderType.MARKET,
        time_in_force=TimeInForce.DAY,
        client_order_id=client_order_id,
        order_id=order_id,
        broker_order_id=f"broker_{order_id}",
        status=status,
    )


def make_fill(*, order_id: str = "ord_1", fill_id: str = "fill_1", quantity: float = 5.0) -> Fill:
    return Fill(
        order_id=order_id,
        symbol="AAPL",
        side=OrderSide.BUY,
        quantity=quantity,
        price=150.0,
        commission=0.0,
        filled_at=TS,
        broker="paper",
        broker_order_id=f"broker_{order_id}",
        fill_id=fill_id,
    )


class RecordingRiskLog:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def record(self, event_type: str, details: dict[str, Any]) -> None:
        self.events.append((event_type, details))


class DownOnGetOrdersBroker(PaperBroker):
    def get_orders(self) -> list[Order]:
        raise ConnectionError("broker down")


class ApprovingRiskEngine:
    def evaluate(
        self,
        intent: OrderIntent,
        account: AccountState,
        market_price: float,
        timestamp: datetime,
    ) -> RiskDecision:
        return RiskDecision(True, "approved", intent.order_intent_id)


class SubmitTimeoutBroker(PaperBroker):
    def __init__(self) -> None:
        super().__init__()
        self.submit_calls = 0

    def submit_order(self, order: Order) -> Order:
        self.submit_calls += 1
        raise TimeoutError("submit timeout")


@dataclass
class RegisteringOMS:
    reduce_only: bool = False
    client_order_ids: set[str] = field(default_factory=set)

    def register_client_order_id(self, client_order_id: str) -> None:
        self.client_order_ids.add(client_order_id)


def make_account() -> AccountState:
    return AccountState(
        timestamp_utc=TS,
        account_id="acct",
        cash=100_000.0,
        equity=100_000.0,
        buying_power=100_000.0,
    )


def test_poll_get_orders_failure_fail_closed_without_marking_orders_unknown(tmp_path) -> None:
    ledger = JsonlLedgerStore(tmp_path)
    local_order = make_order(client_order_id="coid_active", status=OrderStatus.SUBMITTED)
    ledger.append_order(local_order)
    oms = SimpleNamespace(reduce_only=False)
    kill_switch = KillSwitch(KillSwitchConfig(max_consecutive_order_failures=1))
    risk_log = RecordingRiskLog()

    loop = OrderPollingLoop(
        DownOnGetOrdersBroker(),
        ledger,
        oms,  # type: ignore[arg-type]
        kill_switch,
        risk_log,  # type: ignore[arg-type]
    )

    result = loop.poll()

    assert result.broker_unavailable is True
    assert result.unknown == []
    assert result.errors == ["broker_get_orders_failed"]
    assert oms.reduce_only is True
    assert kill_switch.triggered is True
    assert risk_log.events == [("broker_poll_failure", {"error": "broker down"})]
    order_records = ledger.read_records("orders.jsonl")
    assert len(order_records) == 1
    assert order_records[0]["status"] == "submitted"


def test_partial_fill_syncs_new_fills_without_duplicate_accounting(tmp_path) -> None:
    ledger = JsonlLedgerStore(tmp_path)
    ledger.append_order(make_order(status=OrderStatus.SUBMITTED))
    broker = PaperBroker()
    broker_order = make_order(status=OrderStatus.PARTIALLY_FILLED)
    broker.orders.append(broker_order)
    broker.fills.append(make_fill(fill_id="fill_1", quantity=4.0))
    loop = OrderPollingLoop(
        broker,
        ledger,
        SimpleNamespace(reduce_only=False),  # type: ignore[arg-type]
        KillSwitch(),
    )

    first = loop.poll()
    broker.fills.append(make_fill(fill_id="fill_2", quantity=3.0))
    second = loop.poll()
    third = loop.poll()

    assert first.synced == 1
    assert second.synced == 1
    assert third.synced == 1
    fill_records = ledger.read_records("fills.jsonl")
    assert [row["fill_id"] for row in fill_records] == ["fill_1", "fill_2"]
    assert sum(row["quantity"] for row in fill_records) == 7.0


def test_final_fill_after_partial_is_processed_on_later_poll(tmp_path) -> None:
    ledger = JsonlLedgerStore(tmp_path)
    ledger.append_order(make_order(status=OrderStatus.SUBMITTED))
    broker = PaperBroker()
    broker_order = make_order(status=OrderStatus.PARTIALLY_FILLED)
    broker.orders.append(broker_order)
    broker.fills.append(make_fill(fill_id="fill_1", quantity=4.0))
    loop = OrderPollingLoop(
        broker,
        ledger,
        SimpleNamespace(reduce_only=False),  # type: ignore[arg-type]
        KillSwitch(),
    )

    loop.poll()
    broker_order.status = OrderStatus.FILLED
    broker.fills.append(make_fill(fill_id="fill_2", quantity=6.0))
    second = loop.poll()

    assert second.filled == 1
    assert [row["fill_id"] for row in ledger.read_records("fills.jsonl")] == ["fill_1", "fill_2"]
    assert ledger.read_records("orders.jsonl")[-1]["status"] == "filled"


def test_oms_reserves_client_order_id_before_unknown_submit_outcome(tmp_path) -> None:
    broker = SubmitTimeoutBroker()
    risk_log = RecordingRiskLog()
    idempotency_path = tmp_path / "ids.json"
    oms = OrderManagementSystem(
        broker=broker,
        risk_engine=ApprovingRiskEngine(),  # type: ignore[arg-type]
        kill_switch=KillSwitch(),
        idempotency_path=idempotency_path,
        risk_event_log=risk_log,  # type: ignore[arg-type]
    )
    intent = OrderIntent(
        timestamp_utc=TS,
        strategy_id="test",
        symbol="AAPL",
        side=OrderSide.BUY,
        quantity=10.0,
        client_order_id="coid_timeout",
    )

    with pytest.raises(TimeoutError):
        oms.handle_intent(intent, make_account(), 150.0)

    assert "coid_timeout" in oms._client_order_ids
    assert oms.reduce_only is True
    assert idempotency_path.read_text() == '["coid_timeout"]'
    assert [event for event, _details in risk_log.events] == ["broker_timeout", "order_submit_unknown"]

    restarted = OrderManagementSystem(
        broker=broker,
        risk_engine=ApprovingRiskEngine(),  # type: ignore[arg-type]
        idempotency_path=idempotency_path,
    )
    restarted.load_idempotency()
    duplicate = restarted.handle_intent(intent, make_account(), 150.0)

    assert duplicate.risk_decision.approved is False
    assert duplicate.risk_decision.reason == "duplicate_client_order_id"
    assert broker.submit_calls == 1


def test_broker_state_sync_marks_active_local_missing_broker_unknown_and_reduce_only(tmp_path) -> None:
    ledger = JsonlLedgerStore(tmp_path)
    ledger.append_order(make_order(client_order_id="coid_missing", status=OrderStatus.ACCEPTED))
    oms = RegisteringOMS()

    report = BrokerStateSync(PaperBroker(), ledger, oms).full_sync()  # type: ignore[arg-type]

    assert report.reduce_only_engaged is True
    assert oms.reduce_only is True
    assert report.orders_missing_broker[0].client_order_id == "coid_missing"
    assert ledger.read_records("orders.jsonl")[-1]["status"] == "unknown"


def test_broker_state_sync_get_orders_failure_enters_reduce_only_without_unknown(tmp_path) -> None:
    ledger = JsonlLedgerStore(tmp_path)
    ledger.append_order(make_order(client_order_id="coid_active", status=OrderStatus.ACCEPTED))
    oms = RegisteringOMS()

    report = BrokerStateSync(DownOnGetOrdersBroker(), ledger, oms).full_sync()  # type: ignore[arg-type]

    assert report.reduce_only_engaged is True
    assert oms.reduce_only is True
    assert report.orders_missing_broker == []
    assert report.errors == ["get_orders: broker down"]
    assert ledger.read_records("orders.jsonl")[-1]["status"] == "accepted"


def test_restart_sync_registers_local_ids_even_when_broker_unavailable(tmp_path) -> None:
    ledger = JsonlLedgerStore(tmp_path)
    ledger.append_order(make_order(client_order_id="coid_local", status=OrderStatus.ACCEPTED))
    oms = RegisteringOMS()

    report = BrokerStateSync(DownOnGetOrdersBroker(), ledger, oms).sync_after_restart()  # type: ignore[arg-type]

    assert report.reduce_only_engaged is True
    assert "coid_local" in oms.client_order_ids
    assert ledger.read_records("orders.jsonl")[-1]["status"] == "accepted"


def test_restart_sync_registers_restored_client_order_id(tmp_path) -> None:
    ledger = JsonlLedgerStore(tmp_path)
    broker = PaperBroker()
    broker.orders.append(make_order(client_order_id="coid_restored", status=OrderStatus.ACCEPTED))
    oms = RegisteringOMS()

    report = BrokerStateSync(broker, ledger, oms).sync_after_restart()  # type: ignore[arg-type]

    assert report.orders_missing_local[0].client_order_id == "coid_restored"
    assert "coid_restored" in oms.client_order_ids
    assert ledger.read_records("orders.jsonl")[0]["client_order_id"] == "coid_restored"


def test_paper_broker_duplicate_client_order_id_returns_existing_order() -> None:
    broker = PaperBroker()
    first = broker.submit_order(make_order(client_order_id="coid_dup", order_id="ord_first"))
    duplicate = broker.submit_order(make_order(client_order_id="coid_dup", order_id="ord_second"))

    assert duplicate is first
    assert duplicate.order_id == "ord_first"
    assert len(broker.get_orders()) == 1


class FakeResponse:
    def __init__(self, payload: Any, status_code: int = 200, text: str | None = None) -> None:
        self.payload = payload
        self.status_code = status_code
        self.text = text if text is not None else str(payload)

    def json(self) -> Any:
        return self.payload


class DuplicateSubmitSession:
    def request(self, method: str, url: str, **kwargs: Any) -> FakeResponse:
        if method == "POST" and url.endswith("/v2/orders"):
            return FakeResponse({}, 422, "client_order_id already exists")
        if method == "GET" and url.endswith("/v2/orders"):
            return FakeResponse(
                [
                    {
                        "id": "broker_existing",
                        "client_order_id": "coid_dup",
                        "symbol": "AAPL",
                        "qty": "10",
                        "side": "buy",
                        "type": "market",
                        "time_in_force": "day",
                        "status": "accepted",
                        "created_at": "2026-05-10T14:30:00Z",
                        "updated_at": "2026-05-10T14:31:00Z",
                    }
                ]
            )
        raise AssertionError(f"unexpected request {method} {url}")


def test_alpaca_duplicate_client_order_id_recovers_existing_order() -> None:
    broker = AlpacaBroker(
        AlpacaBrokerConfig(api_key="key", api_secret="secret"),
        session=DuplicateSubmitSession(),
    )
    order = make_order(client_order_id="coid_dup", order_id="local_order")

    submitted = broker.submit_order(order)

    assert submitted is order
    assert submitted.broker_order_id == "broker_existing"
    assert submitted.order_id == "coid_dup"
    assert submitted.status == OrderStatus.ACCEPTED
