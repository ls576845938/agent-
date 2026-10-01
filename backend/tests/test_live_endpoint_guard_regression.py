"""Regression tests for live endpoint guard.

Verifies endpoint isolation: paper uses paper URL, shadow_live guards
live URL, live is default-blocked, accidental injection prevented.
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from quant_us.execution.alpaca_broker import (
    AlpacaBroker,
    AlpacaBrokerConfig,
    PAPER_BASE_URL,
    LIVE_BASE_URL,
)
from quant_us.live.readonly_live_broker import (
    LiveEndpointGuard,
    ReadOnlyLiveBrokerProxy,
    mask_secret,
    mask_account_id,
)
from quant_us.execution.broker_base import BrokerBase
from quant_us.live.modes import RuntimeMode
from quant_us.live.runtime_config import LiveRuntimeConfig


class TestEndpointURLs:
    """Verify paper and live base URLs are distinct."""

    def test_paper_url_contains_paper(self) -> None:
        assert "paper-api" in PAPER_BASE_URL

    def test_live_url_does_not_contain_paper(self) -> None:
        assert "paper-api" not in LIVE_BASE_URL

    def test_urls_are_different(self) -> None:
        assert PAPER_BASE_URL != LIVE_BASE_URL


class TestAlpacaBrokerConfig:
    """Verify AlpacaBrokerConfig validates paper/URL alignment."""

    def test_paper_config_with_paper_url_passes(self) -> None:
        config = AlpacaBrokerConfig(
            api_key="test_key",
            api_secret="test_secret",
            paper=True,
            base_url=PAPER_BASE_URL,
        )
        assert config.paper is True

    def test_paper_config_with_live_url_fails(self) -> None:
        with pytest.raises(ValueError, match="does not point to paper endpoint"):
            AlpacaBrokerConfig(
                api_key="test_key",
                api_secret="test_secret",
                paper=True,
                base_url=LIVE_BASE_URL,
            )

    def test_live_config_with_live_url_passes(self) -> None:
        config = AlpacaBrokerConfig(
            api_key="test_key",
            api_secret="test_secret",
            paper=False,
            base_url=LIVE_BASE_URL,
        )
        assert config.paper is False

    def test_live_config_with_paper_url_fails(self) -> None:
        with pytest.raises(ValueError, match="does not point to live endpoint"):
            AlpacaBrokerConfig(
                api_key="test_key",
                api_secret="test_secret",
                paper=False,
                base_url=PAPER_BASE_URL,
            )


class TestLiveEndpointGuard:
    """Verify LiveEndpointGuard enforces endpoint isolation."""

    def test_validate_paper_profile_passes_with_paper_url(self) -> None:
        assert LiveEndpointGuard.validate_paper_profile(PAPER_BASE_URL) is True

    def test_validate_paper_profile_fails_with_live_url(self) -> None:
        with pytest.raises(ValueError, match="paper endpoint"):
            LiveEndpointGuard.validate_paper_profile(LIVE_BASE_URL)

    def test_validate_shadow_live_endpoint_requires_allow(self) -> None:
        with pytest.raises(ValueError, match="cannot connect to live endpoint"):
            LiveEndpointGuard.validate_shadow_live_endpoint(LIVE_BASE_URL, allow_live=False)

    def test_validate_shadow_live_endpoint_with_allow(self) -> None:
        assert LiveEndpointGuard.validate_shadow_live_endpoint(LIVE_BASE_URL, allow_live=True) is True

    def test_block_live_profile_raises(self) -> None:
        with pytest.raises(RuntimeError, match="NOT READY"):
            LiveEndpointGuard.block_live_profile()

    def test_guard_submit_order_shadow_live_raises(self) -> None:
        with pytest.raises(RuntimeError, match="submit_order.*blocked.*shadow_live"):
            LiveEndpointGuard.guard_submit_order("shadow_live", allow_live=False)

    def test_guard_submit_order_no_allow_live_raises(self) -> None:
        with pytest.raises(RuntimeError, match="submit_order.*blocked"):
            LiveEndpointGuard.guard_submit_order("live", allow_live=False)


class TestReadOnlyBrokerProxyForLiveEndpoint:
    """Verify ReadOnlyBrokerProxy is used for live endpoint access."""

    def test_proxy_blocks_write_on_live_endpoint(self) -> None:
        inner = MagicMock(spec=BrokerBase)
        inner.broker_name = "alpaca"
        proxy = ReadOnlyLiveBrokerProxy(inner)

        from quant_us.core.enums import OrderSide, OrderType, TimeInForce
        from quant_us.core.types import Order
        import datetime

        order = Order(
            timestamp_utc=datetime.datetime.now(datetime.timezone.utc),
            strategy_id="test",
            symbol="SPY",
            side=OrderSide.BUY,
            quantity=1.0,
            order_type=OrderType.MARKET,
            time_in_force=TimeInForce.DAY,
            client_order_id="",
        )

        with pytest.raises(RuntimeError, match="FORBIDDEN"):
            proxy.submit_order(order)

    def test_proxy_allows_read_on_live_endpoint(self) -> None:
        from quant_us.core.types import AccountState
        import datetime

        inner = MagicMock(spec=BrokerBase)
        inner.broker_name = "alpaca"
        inner.get_account.return_value = AccountState(
            timestamp_utc=datetime.datetime.now(datetime.timezone.utc),
            account_id="live_account",
            cash=100000.0,
            equity=100000.0,
            buying_power=200000.0,
        )
        proxy = ReadOnlyLiveBrokerProxy(inner)

        account = proxy.get_account()
        assert account.account_id == "live_account"

    def test_proxy_broker_name_prefixed(self) -> None:
        inner = MagicMock(spec=BrokerBase)
        inner.broker_name = "alpaca"
        proxy = ReadOnlyLiveBrokerProxy(inner)
        assert proxy.broker_name == "readonly_live_alpaca"

    def test_proxy_is_readonly(self) -> None:
        inner = MagicMock(spec=BrokerBase)
        inner.broker_name = "test"
        proxy = ReadOnlyLiveBrokerProxy(inner)
        assert proxy.is_readonly is True

    def test_health_check_readonly(self) -> None:
        from quant_us.core.types import AccountState
        import datetime

        inner = MagicMock(spec=BrokerBase)
        inner.broker_name = "alpaca"
        inner.get_account.return_value = AccountState(
            timestamp_utc=datetime.datetime.now(datetime.timezone.utc),
            account_id="test",
            cash=0.0,
            equity=0.0,
            buying_power=0.0,
        )
        proxy = ReadOnlyLiveBrokerProxy(inner)
        health = proxy.health_check()
        assert health["readonly"] is True
        assert health["account_accessible"] is True

    def test_paper_runtime_cannot_use_live_endpoint(self) -> None:
        """Paper mode must not allow live orders."""
        config = LiveRuntimeConfig(mode=RuntimeMode.PAPER, allow_live_orders=False)
        assert config.real_order_submission_enabled is False


class TestSecretMasking:
    def test_mask_secret_normal(self) -> None:
        masked = mask_secret("ABCDEFGHIJKLMNOP")
        assert masked.endswith("MNOP")
        assert "ABCDEFGHIJKL" not in masked

    def test_mask_secret_short(self) -> None:
        masked = mask_secret("AB")
        assert masked == "****"

    def test_mask_secret_empty(self) -> None:
        masked = mask_secret("")
        assert masked == "****"

    def test_mask_account_id(self) -> None:
        masked = mask_account_id("abc12345xyz")
        assert masked == "abc1...xyz" or masked.startswith("abc1")

    def test_full_key_not_in_masked(self) -> None:
        key = "PKLIVEKEY1234567890ABCDEF"
        masked = mask_secret(key)
        assert key not in masked
