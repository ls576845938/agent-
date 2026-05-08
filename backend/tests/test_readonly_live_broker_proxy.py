"""Tests for quant_us/live/readonly_live_broker.py — ReadOnlyLiveBrokerProxy,
LiveEndpointGuard, mask_secret, mask_account_id.

Core invariant: ALL write operations raise RuntimeError.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from quant_us.core.enums import OrderSide, OrderType, TimeInForce
from quant_us.core.types import AccountState, Fill, Order, Position
from quant_us.execution.broker_base import BrokerBase
from quant_us.live.readonly_live_broker import (
    LiveEndpointGuard,
    ReadOnlyLiveBrokerProxy,
    mask_account_id,
    mask_secret,
)


# ===========================================================================
# mask_secret / mask_account_id
# ===========================================================================


class TestMaskFunctions:
    def test_mask_secret_shows_last_four(self) -> None:
        result = mask_secret("my-super-secret-key-1234")
        assert result.endswith("1234")
        assert result.startswith("*")
        assert "my-super-secret" not in result

    def test_mask_secret_short_string(self) -> None:
        result = mask_secret("ab")
        assert result == "****"

    def test_mask_secret_empty_string(self) -> None:
        result = mask_secret("")
        assert result == "****"

    def test_mask_account_id_normal(self) -> None:
        result = mask_account_id("ABCD1234EFGH5678")
        assert result.startswith("ABCD")
        assert result.endswith("5678")
        assert "1234EFGH" not in result

    def test_mask_account_id_short(self) -> None:
        result = mask_account_id("ABC12345")
        assert result == "ABC1****"

    def test_mask_account_id_exact_eight(self) -> None:
        result = mask_account_id("12345678")
        assert result == "1234****"


# ===========================================================================
# ReadOnlyLiveBrokerProxy — read operations forward, write operations block
# ===========================================================================


class TestReadOnlyLiveBrokerProxy:
    """Verify the proxy forwards reads and blocks ALL writes."""

    @pytest.fixture
    def mock_inner(self) -> MagicMock:
        inner = MagicMock(spec=BrokerBase)
        inner.broker_name = "alpaca"
        inner.get_account.return_value = AccountState(
            timestamp_utc=datetime(2026, 5, 1, 12, 0, 0, tzinfo=timezone.utc),
            account_id="live_acct_1",
            cash=250_000.0,
            equity=275_000.0,
            buying_power=500_000.0,
            positions={
                "SPY": Position(symbol="SPY", quantity=200.0, market_price=530.0),
                "QQQ": Position(symbol="QQQ", quantity=100.0, market_price=450.0),
            },
        )
        inner.get_positions.return_value = {
            "SPY": Position(symbol="SPY", quantity=200.0, market_price=530.0),
            "QQQ": Position(symbol="QQQ", quantity=100.0, market_price=450.0),
        }
        inner.get_orders.return_value = []
        inner.get_fills.return_value = [
            Fill(
                fill_id="fill_1",
                order_id="ord_1",
                symbol="SPY",
                side=OrderSide.BUY,
                quantity=100.0,
                price=530.0,
                commission=0.0,
                filled_at=datetime(2026, 5, 1, 12, 30, 0, tzinfo=timezone.utc),
            ),
        ]
        return inner

    @pytest.fixture
    def proxy(self, mock_inner: MagicMock) -> ReadOnlyLiveBrokerProxy:
        return ReadOnlyLiveBrokerProxy(mock_inner)

    # -- Identity --

    def test_broker_name_prefix(self, proxy: ReadOnlyLiveBrokerProxy) -> None:
        assert proxy.broker_name == "readonly_live_alpaca"

    def test_is_readonly(self, proxy: ReadOnlyLiveBrokerProxy) -> None:
        assert proxy.is_readonly is True

    def test_forbidden_call_count_starts_at_zero(
        self, proxy: ReadOnlyLiveBrokerProxy
    ) -> None:
        assert proxy.forbidden_call_count == 0

    # -- Read operations --

    def test_get_account_forwards(self, proxy: ReadOnlyLiveBrokerProxy) -> None:
        account = proxy.get_account()
        assert account.account_id == "live_acct_1"
        assert account.equity == 275_000.0
        assert account.cash == 250_000.0

    def test_get_positions_forwards(self, proxy: ReadOnlyLiveBrokerProxy) -> None:
        positions = proxy.get_positions()
        assert "SPY" in positions
        assert positions["SPY"].quantity == 200.0
        assert "QQQ" in positions

    def test_get_orders_forwards(self, proxy: ReadOnlyLiveBrokerProxy) -> None:
        orders = proxy.get_orders()
        assert orders == []

    def test_get_open_orders_empty(self, proxy: ReadOnlyLiveBrokerProxy) -> None:
        open_orders = proxy.get_open_orders()
        assert open_orders == []

    def test_get_fills_forwards(self, proxy: ReadOnlyLiveBrokerProxy) -> None:
        fills = proxy.get_fills()
        assert len(fills) == 1
        assert fills[0].fill_id == "fill_1"

    def test_get_fills_readonly_forwards(self, proxy: ReadOnlyLiveBrokerProxy) -> None:
        fills = proxy.get_fills_readonly()
        assert len(fills) == 1

    # -- Health check --

    def test_health_check_returns_ok(self, proxy: ReadOnlyLiveBrokerProxy) -> None:
        result = proxy.health_check()
        assert result["status"] == "ok"
        assert result["account_accessible"] is True
        assert result["readonly"] is True
        assert result["broker"] == "readonly_live_alpaca"
        assert result["equity"] == 275_000.0

    def test_health_check_on_error(self, mock_inner: MagicMock) -> None:
        mock_inner.get_account.side_effect = RuntimeError("connection failed")
        proxy = ReadOnlyLiveBrokerProxy(mock_inner)
        result = proxy.health_check()
        assert result["status"] == "error"
        assert result["account_accessible"] is False
        assert result["readonly"] is True

    # -- Forbidden operations --

    def test_submit_order_raises(self, proxy: ReadOnlyLiveBrokerProxy) -> None:
        order = Order(
            timestamp_utc=datetime(2026, 5, 1, 12, 0, 0, tzinfo=timezone.utc),
            strategy_id="test",
            symbol="SPY",
            side=OrderSide.BUY,
            quantity=10.0,
            order_type=OrderType.MARKET,
            time_in_force=TimeInForce.DAY,
            client_order_id="coid_test",
        )
        with pytest.raises(RuntimeError, match="submit_order"):
            proxy.submit_order(order)

    def test_cancel_order_raises(self, proxy: ReadOnlyLiveBrokerProxy) -> None:
        with pytest.raises(RuntimeError, match="cancel_order"):
            proxy.cancel_order("ord_123")

    def test_replace_order_raises(self, proxy: ReadOnlyLiveBrokerProxy) -> None:
        order = Order(
            timestamp_utc=datetime(2026, 5, 1, 12, 0, 0, tzinfo=timezone.utc),
            strategy_id="test",
            symbol="SPY",
            side=OrderSide.BUY,
            quantity=15.0,
            order_type=OrderType.MARKET,
            time_in_force=TimeInForce.DAY,
            client_order_id="coid_repl",
        )
        with pytest.raises(RuntimeError, match="replace_order"):
            proxy.replace_order("ord_123", order)

    def test_close_position_raises(self, proxy: ReadOnlyLiveBrokerProxy) -> None:
        with pytest.raises(RuntimeError, match="close_position"):
            proxy.close_position("SPY")

    def test_close_all_positions_raises(self, proxy: ReadOnlyLiveBrokerProxy) -> None:
        with pytest.raises(RuntimeError, match="close_all_positions"):
            proxy.close_all_positions()

    # -- forbidden_call_count increments --

    def test_forbidden_call_increments_on_submit(
        self, proxy: ReadOnlyLiveBrokerProxy
    ) -> None:
        order = Order(
            timestamp_utc=datetime(2026, 5, 1, 12, 0, 0, tzinfo=timezone.utc),
            strategy_id="test",
            symbol="SPY",
            side=OrderSide.BUY,
            quantity=10.0,
            order_type=OrderType.MARKET,
            time_in_force=TimeInForce.DAY,
            client_order_id="coid_test",
        )
        assert proxy.forbidden_call_count == 0
        with pytest.raises(RuntimeError):
            proxy.submit_order(order)
        assert proxy.forbidden_call_count == 1

    def test_forbidden_call_increments_on_cancel(
        self, proxy: ReadOnlyLiveBrokerProxy
    ) -> None:
        assert proxy.forbidden_call_count == 0
        with pytest.raises(RuntimeError):
            proxy.cancel_order("x")
        assert proxy.forbidden_call_count == 1

    def test_forbidden_call_increments_on_replace(
        self, proxy: ReadOnlyLiveBrokerProxy
    ) -> None:
        order = Order(
            timestamp_utc=datetime(2026, 5, 1, 12, 0, 0, tzinfo=timezone.utc),
            strategy_id="test",
            symbol="SPY",
            side=OrderSide.BUY,
            quantity=15.0,
            order_type=OrderType.MARKET,
            time_in_force=TimeInForce.DAY,
            client_order_id="coid_repl",
        )
        assert proxy.forbidden_call_count == 0
        with pytest.raises(RuntimeError):
            proxy.replace_order("x", order)
        assert proxy.forbidden_call_count == 1

    def test_forbidden_call_increments_on_close(
        self, proxy: ReadOnlyLiveBrokerProxy
    ) -> None:
        with pytest.raises(RuntimeError):
            proxy.close_position("SPY")
        assert proxy.forbidden_call_count == 1

    def test_forbidden_call_increments_on_close_all(
        self, proxy: ReadOnlyLiveBrokerProxy
    ) -> None:
        with pytest.raises(RuntimeError):
            proxy.close_all_positions()
        assert proxy.forbidden_call_count == 1

    # -- audit_no_real_submit --

    def test_audit_no_real_submit_proof(self, proxy: ReadOnlyLiveBrokerProxy) -> None:
        proof = proxy.audit_no_real_submit()
        assert proof["is_readonly"] is True
        assert proof["no_real_order_submitted"] is True
        assert proof["forbidden_call_count"] == 0
        assert "blocked with RuntimeError" in proof["proof"]

    def test_audit_no_real_submit_after_attempt(
        self, proxy: ReadOnlyLiveBrokerProxy
    ) -> None:
        with pytest.raises(RuntimeError):
            proxy.cancel_order("x")
        proof = proxy.audit_no_real_submit()
        assert proof["no_real_order_submitted"] is False
        assert proof["forbidden_call_count"] == 1


# ===========================================================================
# LiveEndpointGuard
# ===========================================================================


class TestLiveEndpointGuard:
    def test_validate_paper_profile_passes(self) -> None:
        result = LiveEndpointGuard.validate_paper_profile(
            "https://paper-api.alpaca.markets"
        )
        assert result is True

    def test_validate_paper_profile_raises_on_live_url(self) -> None:
        with pytest.raises(ValueError, match="Paper profile must use paper endpoint"):
            LiveEndpointGuard.validate_paper_profile("https://api.alpaca.markets")

    def test_validate_shadow_live_endpoint_raises_without_allow(
        self,
    ) -> None:
        with pytest.raises(
            ValueError, match="Shadow-live cannot connect to live endpoint"
        ):
            LiveEndpointGuard.validate_shadow_live_endpoint(
                "https://api.alpaca.markets", allow_live=False
            )

    def test_validate_shadow_live_endpoint_with_allow_passes(self) -> None:
        result = LiveEndpointGuard.validate_shadow_live_endpoint(
            "https://api.alpaca.markets", allow_live=True
        )
        assert result is True

    def test_validate_shadow_live_endpoint_wrong_url(self) -> None:
        with pytest.raises(ValueError, match="Shadow-live endpoint must be live"):
            LiveEndpointGuard.validate_shadow_live_endpoint(
                "https://paper-api.alpaca.markets", allow_live=True
            )

    def test_block_live_profile_raises(self) -> None:
        with pytest.raises(RuntimeError, match="Live profile is NOT READY"):
            LiveEndpointGuard.block_live_profile()

    def test_guard_submit_order_blocked_shadow_live(self) -> None:
        with pytest.raises(RuntimeError, match="shadow_live mode"):
            LiveEndpointGuard.guard_submit_order("shadow_live", allow_live=False)

    def test_guard_submit_order_blocked_no_allow(self) -> None:
        with pytest.raises(RuntimeError, match="allow_live_orders=False"):
            LiveEndpointGuard.guard_submit_order("live", allow_live=False)

    def test_guard_submit_order_passes_live_with_allow(self) -> None:
        # Does not raise when mode=live and allow_live=True
        LiveEndpointGuard.guard_submit_order("live", allow_live=True)
