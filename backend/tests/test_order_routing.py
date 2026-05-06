from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from quant_us.core.clock import utc_now
from quant_us.core.enums import OrderSide, OrderStatus, OrderType, TimeInForce
from quant_us.core.types import AccountState, Fill, Order, Position
from quant_us.execution.alpaca_broker import AlpacaBroker, AlpacaBrokerConfig
from quant_us.execution.broker_base import BrokerBase
from quant_us.execution.ibkr_broker import IBKRBroker, IBKRBrokerConfig
from quant_us.execution.order_router import OrderRouter
from quant_us.execution.paper_broker import PaperBroker


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_order(symbol: str = "AAPL", side: OrderSide = OrderSide.BUY, quantity: float = 100.0) -> Order:
    return Order(
        timestamp_utc=utc_now(),
        strategy_id="test_strat",
        symbol=symbol,
        side=side,
        quantity=quantity,
        order_type=OrderType.MARKET,
        time_in_force=TimeInForce.DAY,
        client_order_id="coid_test",
    )


def _make_fill(order_id: str, symbol: str = "AAPL") -> Fill:
    return Fill(
        order_id=order_id,
        symbol=symbol,
        side=OrderSide.BUY,
        quantity=100.0,
        price=150.0,
        commission=1.0,
        filled_at=utc_now(),
        broker="paper",
    )


# ---------------------------------------------------------------------------
# BrokerBase (ABC)
# ---------------------------------------------------------------------------

class TestBrokerBase:
    def test_cannot_instantiate_directly(self):
        with pytest.raises(TypeError):
            BrokerBase()  # type: ignore[abstract]


# ---------------------------------------------------------------------------
# OrderRouter
# ---------------------------------------------------------------------------

class TestOrderRouter:
    def test_route_delegates_to_broker_submit_order(self):
        mock_broker = MagicMock(spec=BrokerBase)
        mock_broker.submit_order.return_value = _make_order()
        router = OrderRouter(broker=mock_broker)

        order = _make_order()
        result = router.route(order)

        mock_broker.submit_order.assert_called_once_with(order)
        assert result is mock_broker.submit_order.return_value


# ---------------------------------------------------------------------------
# PaperBroker
# ---------------------------------------------------------------------------

class TestPaperBroker:
    def test_submit_order_changes_status_to_accepted(self):
        broker = PaperBroker(initial_cash=100_000.0)
        order = _make_order()

        result = broker.submit_order(order)

        assert result.status == OrderStatus.ACCEPTED
        assert result in broker.orders
        assert result.updated_at is not None

    def test_get_filters_by_order_id(self):
        broker = PaperBroker(initial_cash=100_000.0)
        fill_a = _make_fill(order_id="ord_a", symbol="AAPL")
        fill_b = _make_fill(order_id="ord_b", symbol="MSFT")
        broker.fills.extend([fill_a, fill_b])

        result = broker.get_fills(order_id="ord_a")

        assert len(result) == 1
        assert result[0].order_id == "ord_a"

    def test_get_fills_returns_all_when_no_order_id(self):
        broker = PaperBroker(initial_cash=100_000.0)
        fill = _make_fill(order_id="ord_a")
        broker.fills.append(fill)

        result = broker.get_fills(order_id=None)

        assert result == [fill]

    def test_get_fills_returns_empty_list_when_none_exist(self):
        broker = PaperBroker(initial_cash=100_000.0)

        result = broker.get_fills(order_id="ord_nonexistent")

        assert result == []

    def test_cancel_order_changes_status_to_cancelled(self):
        broker = PaperBroker(initial_cash=100_000.0)
        order = _make_order()
        broker.submit_order(order)

        cancelled = broker.cancel_order(order.order_id)

        assert cancelled.status == OrderStatus.CANCELLED
        assert cancelled.updated_at is not None

    def test_cancel_order_raises_key_error_for_unknown_id(self):
        broker = PaperBroker(initial_cash=100_000.0)

        with pytest.raises(KeyError):
            broker.cancel_order("nonexistent")

    def test_get_account_returns_state_with_correct_initial_cash(self):
        broker = PaperBroker(initial_cash=200_000.0)

        state = broker.get_account()

        assert isinstance(state, AccountState)
        assert state.cash == 200_000.0
        assert state.account_id == "paper"

    def test_get_account_equity_includes_positions(self):
        broker = PaperBroker(initial_cash=100_000.0)
        broker.positions["AAPL"] = Position(
            symbol="AAPL",
            quantity=10.0,
            market_price=150.0,
        )

        state = broker.get_account()

        expected_equity = 100_000.0 + 10.0 * 150.0
        assert state.equity == pytest.approx(expected_equity)
        assert "AAPL" in state.positions

    def test_get_positions_returns_dict_keyed_by_symbol(self):
        broker = PaperBroker(initial_cash=100_000.0)
        broker.positions["AAPL"] = Position(symbol="AAPL", quantity=10.0, market_price=150.0)
        broker.positions["MSFT"] = Position(symbol="MSFT", quantity=5.0, market_price=300.0)

        result = broker.get_positions()

        assert "AAPL" in result
        assert "MSFT" in result
        assert result["AAPL"].quantity == 10.0

    def test_get_orders_returns_all_submitted_orders(self):
        broker = PaperBroker(initial_cash=100_000.0)
        o1 = _make_order(symbol="AAPL")
        o2 = _make_order(symbol="MSFT")
        broker.submit_order(o1)
        broker.submit_order(o2)

        result = broker.get_orders()

        assert len(result) == 2
        assert o1 in result
        assert o2 in result

    def test_get_orders_returns_empty_list_when_no_orders(self):
        broker = PaperBroker(initial_cash=100_000.0)

        result = broker.get_orders()

        assert result == []


# ---------------------------------------------------------------------------
# AlpacaBroker
# ---------------------------------------------------------------------------

class TestAlpacaBroker:
    def test_constructor_accepts_valid_config(self):
        """Config with api_key/api_secret should instantiate successfully."""
        config = AlpacaBrokerConfig(api_key="test_key", api_secret="test_secret")
        broker = AlpacaBroker(config=config, session=MagicMock())
        assert broker.broker_name == "alpaca"
        assert broker.config.api_key == "test_key"
        assert broker.config.api_secret == "test_secret"

    def test_submit_order_with_mocked_request_returns_mapped_order(self):
        config = AlpacaBrokerConfig(api_key="k", api_secret="s")
        broker = AlpacaBroker(config=config, session=MagicMock())

        now_iso = "2026-05-03T12:00:00+00:00"
        mock_payload = {
            "id": "alpaca-ord-999",
            "client_order_id": "coid_test",
            "symbol": "AAPL",
            "qty": "100",
            "side": "buy",
            "type": "market",
            "time_in_force": "day",
            "status": "accepted",
            "created_at": now_iso,
            "updated_at": now_iso,
        }

        with patch.object(broker, "_request", return_value=mock_payload) as mock_req:
            order = _make_order()
            result = broker.submit_order(order)

        mock_req.assert_called_once()
        # _request called with POST, /v2/orders
        args, _ = mock_req.call_args
        assert args[0] == "POST"
        assert args[1] == "/v2/orders"

        assert result.status == OrderStatus.ACCEPTED
        assert result.broker_order_id == "alpaca-ord-999"

    def test_get_account_with_mocked_request_returns_account_state(self):
        config = AlpacaBrokerConfig(api_key="k", api_secret="s")
        broker = AlpacaBroker(config=config, session=MagicMock())

        mock_account_payload = {
            "id": "acc-001",
            "account_number": "ACC001",
            "cash": "50000.00",
            "equity": "75000.00",
            "buying_power": "100000.00",
        }
        mock_positions_payload: list[dict] = []

        def fake_request(method: str, path: str, **kwargs):
            if path == "/v2/account":
                return mock_account_payload
            if path == "/v2/positions":
                return mock_positions_payload
            return {}

        with patch.object(broker, "_request", side_effect=fake_request):
            state = broker.get_account()

        assert isinstance(state, AccountState)
        assert state.account_id == "acc-001"
        assert state.cash == 50000.0
        assert state.equity == 75000.0
        assert state.buying_power == 100000.0


# ---------------------------------------------------------------------------
# IBKRBroker
# ---------------------------------------------------------------------------

class TestIBKRBroker:
    def test_constructor_sets_broker_name(self):
        config = IBKRBrokerConfig()
        broker = IBKRBroker(config=config)
        assert broker.broker_name == "ibkr"

    def test_submit_order_raises_not_implemented(self):
        config = IBKRBrokerConfig()
        broker = IBKRBroker(config=config)
        with pytest.raises(NotImplementedError, match="IBKR adapter boundary"):
            broker.submit_order(_make_order())

    def test_paper_broker_methods_still_work(self):
        """IBKRBroker extends PaperBroker; non-overridden inherited methods should work."""
        config = IBKRBrokerConfig()
        broker = IBKRBroker(config=config)
        assert broker.get_account().cash == 100_000.0
        assert broker.get_positions() == {}
        assert broker.get_orders() == []
