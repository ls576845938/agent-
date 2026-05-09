"""Tests proving shadow_live NEVER submits real orders, even when
QUANT_LIVE_SUBMISSION_ENABLED=true in the environment.

This is the most critical safety test suite — it verifies that no
environment variable or configuration can create a live order path
through shadow_live mode.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock

import pytest

from quant_us.core.enums import OrderSide, OrderType, TimeInForce
from quant_us.core.types import Order
from quant_us.live.modes import RuntimeMode
from quant_us.live.runtime_config import LiveRuntimeConfig
from quant_us.live.shadow_live import ShadowLiveConfig, ShadowLiveRunner


class TestShadowLiveNoRealSubmitEnvTrue:
    """Verify shadow_live never submits real orders regardless of env."""

    def test_runtime_mode_shadow_cannot_submit(self) -> None:
        """RuntimeMode.SHADOW_LIVE.can_submit_real_orders is always False."""
        assert RuntimeMode.SHADOW_LIVE.can_submit_real_orders is False

    def test_runtime_config_rejects_shadow_with_live_orders(self) -> None:
        """LiveRuntimeConfig rejects shadow_live + allow_live_orders."""
        with pytest.raises(ValueError, match="shadow_live cannot allow live orders"):
            LiveRuntimeConfig(mode=RuntimeMode.SHADOW_LIVE, allow_live_orders=True)

    def test_readonly_broker_blocks_submit_order(self) -> None:
        """ReadOnlyBrokerProxy blocks submit_order with RuntimeError."""
        from quant_us.live.readonly_live_broker import ReadOnlyLiveBrokerProxy
        from quant_us.execution.broker_base import BrokerBase

        inner = MagicMock(spec=BrokerBase)
        inner.broker_name = "alpaca"
        proxy = ReadOnlyLiveBrokerProxy(inner)

        order = Order(
            timestamp_utc=__import__('datetime').datetime.now(__import__('datetime').timezone.utc),
            strategy_id="test",
            symbol="SPY",
            side=OrderSide.BUY,
            quantity=10.0,
            order_type=OrderType.MARKET,
            time_in_force=TimeInForce.DAY,
            client_order_id="",
        )
        with pytest.raises(RuntimeError, match="FORBIDDEN"):
            proxy.submit_order(order)

    def test_readonly_broker_blocks_cancel_order(self) -> None:
        """ReadOnlyBrokerProxy blocks cancel_order with RuntimeError."""
        from quant_us.live.readonly_live_broker import ReadOnlyLiveBrokerProxy
        from quant_us.execution.broker_base import BrokerBase

        inner = MagicMock(spec=BrokerBase)
        inner.broker_name = "alpaca"
        proxy = ReadOnlyLiveBrokerProxy(inner)

        with pytest.raises(RuntimeError, match="FORBIDDEN"):
            proxy.cancel_order("test_ord_id")

    def test_readonly_broker_blocks_replace_order(self) -> None:
        """ReadOnlyBrokerProxy blocks replace_order."""
        from quant_us.live.readonly_live_broker import ReadOnlyLiveBrokerProxy
        from quant_us.execution.broker_base import BrokerBase

        inner = MagicMock(spec=BrokerBase)
        inner.broker_name = "alpaca"
        proxy = ReadOnlyLiveBrokerProxy(inner)

        order = Order(
            timestamp_utc=__import__('datetime').datetime.now(__import__('datetime').timezone.utc),
            strategy_id="test",
            symbol="SPY",
            side=OrderSide.BUY,
            quantity=1.0,
            order_type=OrderType.MARKET,
            time_in_force=TimeInForce.DAY,
            client_order_id="",
        )
        with pytest.raises(RuntimeError, match="FORBIDDEN"):
            proxy.replace_order("test_id", order)

    def test_readonly_broker_blocks_close_position(self) -> None:
        """ReadOnlyBrokerProxy blocks close_position."""
        from quant_us.live.readonly_live_broker import ReadOnlyLiveBrokerProxy
        from quant_us.execution.broker_base import BrokerBase

        inner = MagicMock(spec=BrokerBase)
        inner.broker_name = "alpaca"
        proxy = ReadOnlyLiveBrokerProxy(inner)

        with pytest.raises(RuntimeError, match="FORBIDDEN"):
            proxy.close_position("SPY")

    def test_readonly_broker_blocks_close_all_positions(self) -> None:
        """ReadOnlyBrokerProxy blocks close_all_positions."""
        from quant_us.live.readonly_live_broker import ReadOnlyLiveBrokerProxy
        from quant_us.execution.broker_base import BrokerBase

        inner = MagicMock(spec=BrokerBase)
        inner.broker_name = "alpaca"
        proxy = ReadOnlyLiveBrokerProxy(inner)

        with pytest.raises(RuntimeError, match="FORBIDDEN"):
            proxy.close_all_positions()

    def test_shadow_config_rejects_submit_real_orders(self) -> None:
        """ShadowLiveConfig rejects submit_real_orders=True."""
        with pytest.raises(ValueError, match="submit_real_orders MUST be False"):
            ShadowLiveConfig(submit_real_orders=True)

    def test_shadow_config_accepts_submit_real_orders_false(self) -> None:
        """ShadowLiveConfig accepts submit_real_orders=False."""
        config = ShadowLiveConfig(submit_real_orders=False)
        assert config.submit_real_orders is False

    def test_real_order_submission_disabled_for_shadow(self, monkeypatch) -> None:
        """Even with QUANT_LIVE_SUBMISSION_ENABLED=true,
        shadow_live mode does NOT enable real order submission."""
        monkeypatch.setenv("QUANT_LIVE_SUBMISSION_ENABLED", "true")

        config = LiveRuntimeConfig(
            mode=RuntimeMode.SHADOW_LIVE,
            allow_live_orders=False,
        )
        # real_order_submission_enabled requires mode=LIVE
        assert config.real_order_submission_enabled is False

    def test_forbidden_call_count_tracks_attempts(self) -> None:
        """ReadOnlyBrokerProxy.forbidden_call_count increments on blocked calls."""
        from quant_us.live.readonly_live_broker import ReadOnlyLiveBrokerProxy
        from quant_us.execution.broker_base import BrokerBase

        inner = MagicMock(spec=BrokerBase)
        inner.broker_name = "alpaca"
        proxy = ReadOnlyLiveBrokerProxy(inner)
        assert proxy.forbidden_call_count == 0

        order = Order(
            timestamp_utc=__import__('datetime').datetime.now(__import__('datetime').timezone.utc),
            strategy_id="test",
            symbol="SPY",
            side=OrderSide.BUY,
            quantity=1.0,
            order_type=OrderType.MARKET,
            time_in_force=TimeInForce.DAY,
            client_order_id="",
        )
        try:
            proxy.submit_order(order)
        except RuntimeError:
            pass
        assert proxy.forbidden_call_count == 1

    def test_audit_proof_no_real_submit(self) -> None:
        """audit_no_real_submit provides proof of read-only operation."""
        from quant_us.live.readonly_live_broker import ReadOnlyLiveBrokerProxy
        from quant_us.execution.broker_base import BrokerBase

        inner = MagicMock(spec=BrokerBase)
        inner.broker_name = "alpaca"
        proxy = ReadOnlyLiveBrokerProxy(inner)

        proof = proxy.audit_no_real_submit()
        assert proof["is_readonly"] is True
        assert proof["no_real_order_submitted"] is True

    def test_shadow_readonly_audit_is_explicit_about_endpoint_and_credentials(self) -> None:
        """shadow_live readonly proof includes masked credential and endpoint audit."""
        from quant_us.execution.broker_base import BrokerBase
        from quant_us.live.shadow_live import ReadOnlyBrokerProxy

        inner = MagicMock(spec=BrokerBase)
        inner.broker_name = "alpaca"
        proxy = ReadOnlyBrokerProxy(
            inner,
            audit_context={
                "api_key": "PKLIVE12345678",
                "api_secret": "secret987654321",
                "base_url": "https://api.alpaca.markets",
                "endpoint_kind": "live",
                "readonly_expected": True,
            },
        )

        proof = proxy.audit_no_real_submit()
        assert proof["credential_audit"]["api_key_present"] is True
        assert proof["credential_audit"]["api_secret_present"] is True
        assert proof["credential_audit"]["endpoint_kind"] == "live"
        assert proof["credential_audit"]["api_key_masked"].endswith("5678")
        assert proof["credential_audit"]["api_secret_masked"].endswith("4321")

    def test_shadow_orchestrator_config_requires_readonly(self) -> None:
        """ShadowOrchestratorConfig requires readonly=True."""
        from quant_us.live.shadow_orchestrator import ShadowOrchestratorConfig

        with pytest.raises(ValueError, match="readonly MUST be True"):
            ShadowOrchestratorConfig(readonly=False)

    def test_shadow_runner_readonly_audit_stays_fail_closed_even_when_env_true(
        self, monkeypatch, tmp_path
    ) -> None:
        """ShadowLiveRunner exposes explicit readonly proof even when env is true."""
        from quant_us.execution.broker_base import BrokerBase
        from quant_us.live.shadow_live import ReadOnlyBrokerProxy

        monkeypatch.setenv("QUANT_LIVE_SUBMISSION_ENABLED", "true")
        config = ShadowLiveConfig(
            broker_api_key="PKLIVE12345678",
            broker_api_secret="secret987654321",
            require_live_readiness_check=False,
            use_real_market_data=False,
            symbols=[],
            ledger_root=str(tmp_path / "shadow_ledger"),
        )
        runner = ShadowLiveRunner(config)
        inner = MagicMock(spec=BrokerBase)
        inner.broker_name = "alpaca"
        runner.real_broker = ReadOnlyBrokerProxy(
            inner,
            audit_context=runner._readonly_broker_audit_context(),
            audit_log_path=str(tmp_path / "shadow_ledger" / "readonly_audit.jsonl"),
        )

        proof = runner.readonly_broker_audit()
        assert proof["configured"] is True
        assert proof["runtime_mode"] == "shadow_live"
        assert proof["real_submit_capability"] is False
        assert proof["credential_audit"]["endpoint_kind"] == "live"
        assert proof["credential_audit"]["api_key_masked"].endswith("5678")
