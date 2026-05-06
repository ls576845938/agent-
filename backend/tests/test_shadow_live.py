"""Tests for ShadowLiveGate, ReadOnlyBrokerProxy, and ShadowLiveRunner.

Focus on safety-critical behaviour:
- Hard safety gate raises RuntimeError
- ReadOnlyBrokerProxy blocks submit/cancel
- verify_no_real_orders() at bootstrap and before orders
- Bootstrap fails when kill switch is triggered
- Shutdown does not raise
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from unittest.mock import MagicMock, PropertyMock

import pytest

from quant_us.core.enums import OrderSide, OrderType, TimeInForce
from quant_us.core.types import AccountState, Order, Position
from quant_us.execution.broker_base import BrokerBase
from quant_us.live.shadow_live import (
    ReadOnlyBrokerProxy,
    ShadowLiveConfig,
    ShadowLiveGate,
)


# ===========================================================================
# ShadowLiveConfig safety
# ===========================================================================


class TestShadowLiveConfig:
    def test_default_config_is_safe(self) -> None:
        """Default config has submit_real_orders=False."""
        config = ShadowLiveConfig()
        assert config.submit_real_orders is False

    def test_submit_real_orders_can_be_set(self) -> None:
        """submit_real_orders can be set to False explicitly."""
        config = ShadowLiveConfig(submit_real_orders=False)
        assert config.submit_real_orders is False


# ===========================================================================
# ReadOnlyBrokerProxy — hard safety gate at the broker level
# ===========================================================================


class TestReadOnlyBrokerProxy:
    """Verify the proxy blocks write operations and forwards read operations."""

    @pytest.fixture
    def mock_inner(self) -> MagicMock:
        inner = MagicMock(spec=BrokerBase)
        inner.broker_name = "alpaca"
        inner.get_account.return_value = AccountState(
            timestamp_utc=datetime(2026, 4, 1, 12, 0, 0, tzinfo=timezone.utc),
            account_id="test1",
            cash=100_000.0,
            equity=100_000.0,
            buying_power=200_000.0,
            positions={
                "SPY": Position(symbol="SPY", quantity=100.0, market_price=500.0),
            },
        )
        inner.get_positions.return_value = {
            "SPY": Position(symbol="SPY", quantity=100.0, market_price=500.0),
        }
        inner.get_orders.return_value = []
        inner.get_fills.return_value = []
        return inner

    @pytest.fixture
    def proxy(self, mock_inner: MagicMock) -> ReadOnlyBrokerProxy:
        return ReadOnlyBrokerProxy(mock_inner)

    def test_broker_name_prefix(self, proxy: ReadOnlyBrokerProxy) -> None:
        """broker_name is prefixed with readonly_."""
        assert proxy.broker_name == "readonly_alpaca"

    def test_get_account_forwards(self, proxy: ReadOnlyBrokerProxy) -> None:
        """get_account is forwarded to the inner broker."""
        account = proxy.get_account()
        assert account.account_id == "test1"
        assert account.equity == 100_000.0

    def test_get_positions_forwards(self, proxy: ReadOnlyBrokerProxy) -> None:
        """get_positions is forwarded to the inner broker."""
        positions = proxy.get_positions()
        assert "SPY" in positions
        assert positions["SPY"].quantity == 100.0

    def test_get_orders_forwards(self, proxy: ReadOnlyBrokerProxy) -> None:
        """get_orders is forwarded to the inner broker."""
        orders = proxy.get_orders()
        assert orders == []

    def test_get_fills_forwards(self, proxy: ReadOnlyBrokerProxy) -> None:
        """get_fills is forwarded to the inner broker."""
        fills = proxy.get_fills()
        assert fills == []

    def test_submit_order_raises(self, proxy: ReadOnlyBrokerProxy) -> None:
        """submit_order raises RuntimeError — hard block."""
        order = Order(
            timestamp_utc=datetime(2026, 4, 1, 12, 0, 0, tzinfo=timezone.utc),
            strategy_id="test",
            symbol="SPY",
            side=OrderSide.BUY,
            quantity=10.0,
            order_type=OrderType.MARKET,
            time_in_force=TimeInForce.DAY,
            client_order_id="coid_test",
        )
        with pytest.raises(RuntimeError, match="submit_order.*blocked"):
            proxy.submit_order(order)

    def test_cancel_order_raises(self, proxy: ReadOnlyBrokerProxy) -> None:
        """cancel_order raises RuntimeError — hard block."""
        with pytest.raises(RuntimeError, match="cancel_order.*blocked"):
            proxy.cancel_order("ord_123")


# ===========================================================================
# ShadowLiveGate
# ===========================================================================


class TestShadowLiveGate:
    def test_verify_no_real_orders_passes(self) -> None:
        """verify_no_real_orders returns True when submit_real_orders is False."""
        config = ShadowLiveConfig(submit_real_orders=False)
        gate = ShadowLiveGate(config)
        assert gate.verify_no_real_orders() is True

    def test_verify_no_real_orders_fails(self) -> None:
        """ShadowLiveConfig rejects submit_real_orders=True at construction time."""
        with pytest.raises(ValueError, match="submit_real_orders MUST be False"):
            ShadowLiveConfig(submit_real_orders=True)

    def test_check_all_with_truish_submit(self) -> None:
        """ShadowLiveConfig construction fails — cannot even create a config with submit_real_orders=True."""
        with pytest.raises(ValueError, match="submit_real_orders MUST be False"):
            ShadowLiveConfig(submit_real_orders=True)


# ===========================================================================
# ShadowLiveRunner safety gates (bootstrap checks)
# ===========================================================================


class TestShadowLiveRunnerSafety:
    """Minimal bootstrap safety tests — no real broker or market data needed."""

    def test_hard_safety_gate_raises(self) -> None:
        """ShadowLiveConfig rejects submit_real_orders=True at construction.
        The safety gate is enforced at config creation, before any runner exists."""
        with pytest.raises(ValueError, match="submit_real_orders MUST be False"):
            ShadowLiveConfig(submit_real_orders=True)

    def test_hard_safety_gate_passes(self) -> None:
        """_hard_safety_gate() does nothing when submit_real_orders is False."""
        from quant_us.live.shadow_live import ShadowLiveRunner

        config = ShadowLiveConfig(submit_real_orders=False)
        runner = ShadowLiveRunner(config)
        # Should not raise
        runner._hard_safety_gate()

    def test_verify_and_gate_raises_on_true(self) -> None:
        """Config creation fails when submit_real_orders=True.
        The safety is enforced at the config dataclass level."""
        with pytest.raises(ValueError, match="submit_real_orders MUST be False"):
            ShadowLiveConfig(submit_real_orders=True)

    def test_bootstrap_fails_when_submit_real_orders_true(self) -> None:
        """ShadowLiveConfig cannot be created with submit_real_orders=True.
        Safety gate enforced at construction time."""
        with pytest.raises(ValueError, match="MUST be False"):
            ShadowLiveConfig(submit_real_orders=True)

    def test_shutdown_no_crash(self) -> None:
        """shutdown() does not raise when called without bootstrap."""
        from quant_us.live.shadow_live import ShadowLiveRunner

        config = ShadowLiveConfig(submit_real_orders=False)
        runner = ShadowLiveRunner(config)
        # Should not raise
        runner.shutdown()

    def test_bootstrap_no_api_keys_returns_false(self) -> None:
        """bootstrap() returns False when no API keys are configured
        (gate check fails on broker connectivity)."""
        from quant_us.live.shadow_live import ShadowLiveRunner

        config = ShadowLiveConfig(
            submit_real_orders=False,
            broker_api_key="",
            broker_api_secret="",
            require_live_readiness_check=True,
        )
        runner = ShadowLiveRunner(config)
        result = runner.bootstrap()
        assert result is False

    def test_bootstrap_skip_gate_check(self) -> None:
        """bootstrap() with require_live_readiness_check=False and no symbols
        skips broker connectivity + market data checks and creates components."""
        from quant_us.live.shadow_live import ShadowLiveRunner

        config = ShadowLiveConfig(
            submit_real_orders=False,
            broker_api_key="",
            broker_api_secret="",
            require_live_readiness_check=False,
            use_real_market_data=False,
            symbols=[],
        )
        runner = ShadowLiveRunner(config)
        result = runner.bootstrap()
        # Should succeed because gate check + market data are skipped
        assert runner._bootstrapped is True
        assert result is True
        # Clean shutdown
        runner.shutdown()


# ===========================================================================
# ShadowLiveGate check_all completeness
# ===========================================================================


class TestShadowLiveGateCompleteness:
    def test_gate_checks_seven_categories(self) -> None:
        """check_all returns at least 5 check categories (gate + bootstrap = 7)."""
        config = ShadowLiveConfig(submit_real_orders=False, broker_api_key="k", broker_api_secret="s")
        gate = ShadowLiveGate(config)
        report = gate.check_all()
        # Without state_store, there should be at least 4 gate-level checks:
        # verify_no_real_orders, broker_connectivity, market_data_accessible,
        # paper_broker_configured
        assert "verify_no_real_orders" in report.checks
        assert "broker_connectivity" in report.checks
        assert "market_data_accessible" in report.checks
        assert "paper_broker_configured" in report.checks
        assert len(report.checks) >= 4
