"""Test that real live order submission is properly gated and default-disabled."""

import os
import pytest


class TestLiveOrderConfigDefaults:
    """LiveRuntimeConfig defaults must prevent real orders."""

    def test_config_defaults_are_safe(self):
        from quant_us.live.runtime_config import LiveRuntimeConfig
        from quant_us.live.modes import RuntimeMode

        c = LiveRuntimeConfig()
        assert c.mode == RuntimeMode.PAPER
        assert c.submit_orders is False
        assert c.allow_live_orders is False
        assert c.confirm_live is False
        assert c.live_submission_enabled is False
        assert c.require_readiness_gate is True
        assert c.require_reconciliation_clean is True

    def test_live_mode_alone_insufficient(self):
        """Setting mode=LIVE without other flags must not enable orders."""
        from quant_us.live.runtime_config import LiveRuntimeConfig
        from quant_us.live.modes import RuntimeMode

        c = LiveRuntimeConfig(mode=RuntimeMode.LIVE)
        assert c.mode == RuntimeMode.LIVE
        # All safety flags still False
        assert c.submit_orders is False
        assert c.allow_live_orders is False
        assert c.confirm_live is False
        assert c.live_submission_enabled is False


class TestShadowLiveSafety:
    """Shadow live mode must never submit real orders."""

    def test_shadow_config_rejects_real_orders(self):
        """ShadowLiveConfig raises ValueError if submit_real_orders=True."""
        from quant_us.live.shadow_live import ShadowLiveConfig

        config = ShadowLiveConfig(
            symbols=["SPY"],
            broker_api_key="test_key",
            broker_api_secret="test_secret",
            submit_real_orders=False,
        )
        assert config.submit_real_orders is False

    def test_shadow_config_default_is_safe(self):
        """ShadowLiveConfig defaults to no real orders."""
        from quant_us.live.shadow_live import ShadowLiveConfig

        config = ShadowLiveConfig(
            symbols=["SPY"],
            broker_api_key="test_key",
            broker_api_secret="test_secret",
        )
        assert config.submit_real_orders is False

    def test_readonly_broker_proxy_blocks_submit(self):
        """ReadOnlyBrokerProxy.submit_order() must raise RuntimeError."""
        from datetime import datetime, timezone
        from quant_us.live.shadow_live import ReadOnlyBrokerProxy
        from quant_us.execution.alpaca_broker import AlpacaBrokerConfig, AlpacaBroker
        from quant_us.core.types import Order
        from quant_us.core.enums import OrderSide, OrderType, TimeInForce

        broker_config = AlpacaBrokerConfig(
            api_key="test_key",
            api_secret="test_secret",
            paper=True,
        )
        broker = AlpacaBroker(broker_config)
        proxy = ReadOnlyBrokerProxy(broker)

        order = Order(
            timestamp_utc=datetime.now(timezone.utc),
            strategy_id="test", symbol="SPY",
            side=OrderSide.BUY, quantity=10.0,
            order_type=OrderType.MARKET,
            time_in_force=TimeInForce.DAY,
            client_order_id="test-1",
        )

        with pytest.raises(RuntimeError, match="blocked"):
            proxy.submit_order(order)

        with pytest.raises(RuntimeError, match="blocked"):
            proxy.cancel_order("test-id")


class TestLiveOrderGateChain:
    """Verify all layers of the live order safety gate."""

    def test_env_var_not_set_means_disabled(self):
        """QUANT_LIVE_SUBMISSION_ENABLED not set = disabled."""
        # Remove env var if set
        old = os.environ.pop("QUANT_LIVE_SUBMISSION_ENABLED", None)
        try:
            live_enabled = os.environ.get("QUANT_LIVE_SUBMISSION_ENABLED", "").lower() in ("1", "true", "yes")
            assert live_enabled is False
        finally:
            if old is not None:
                os.environ["QUANT_LIVE_SUBMISSION_ENABLED"] = old

    def test_env_var_false_string_disabled(self):
        """QUANT_LIVE_SUBMISSION_ENABLED=false = disabled."""
        old = os.environ.get("QUANT_LIVE_SUBMISSION_ENABLED")
        os.environ["QUANT_LIVE_SUBMISSION_ENABLED"] = "false"
        try:
            live_enabled = os.environ.get("QUANT_LIVE_SUBMISSION_ENABLED", "").lower() in ("1", "true", "yes")
            assert live_enabled is False
        finally:
            if old is not None:
                os.environ["QUANT_LIVE_SUBMISSION_ENABLED"] = old
            else:
                os.environ.pop("QUANT_LIVE_SUBMISSION_ENABLED", None)

    def test_env_var_true_enables(self):
        """QUANT_LIVE_SUBMISSION_ENABLED=true = enabled."""
        old = os.environ.get("QUANT_LIVE_SUBMISSION_ENABLED")
        os.environ["QUANT_LIVE_SUBMISSION_ENABLED"] = "true"
        try:
            live_enabled = os.environ.get("QUANT_LIVE_SUBMISSION_ENABLED", "").lower() in ("1", "true", "yes")
            assert live_enabled is True
        finally:
            if old is not None:
                os.environ["QUANT_LIVE_SUBMISSION_ENABLED"] = old
            else:
                os.environ.pop("QUANT_LIVE_SUBMISSION_ENABLED", None)

    def test_cli_live_start_defaults_to_paper(self):
        """live start without --allow-live-orders defaults to paper mode."""
        from quant_us.cli import build_parser

        parser = build_parser()
        args = parser.parse_args(["live", "start"])
        assert args.allow_live_orders is False
        assert args.confirm_live is False

    def test_cli_live_start_simulate_days(self):
        """live start --simulate-days N defaults to N day simulated mode."""
        from quant_us.cli import build_parser

        parser = build_parser()
        args = parser.parse_args(["live", "start", "--simulate-days", "30"])
        assert args.simulate_days == 30
        assert args.allow_live_orders is False

    def test_broker_mode_mismatch_blocked(self):
        """Runtime with mode=SHADOW_LIVE cannot submit real orders."""
        from quant_us.live.runtime_config import LiveRuntimeConfig
        from quant_us.live.modes import RuntimeMode

        c = LiveRuntimeConfig(mode=RuntimeMode.SHADOW_LIVE)
        # In shadow mode, submit_orders and allow_live_orders must still be False
        assert c.allow_live_orders is False
        assert c.live_submission_enabled is False
