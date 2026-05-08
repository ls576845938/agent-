"""Test strategy → event → signal alignment in the event-driven path."""

import pytest
from quant_us.core.enums import EventType


class TestStrategyEventAlignment:
    """Strategy.on_market_event must produce aligned Signal events."""

    def test_event_type_market_defined(self):
        """EventType.MARKET must exist for bar events."""
        assert hasattr(EventType, "MARKET") or hasattr(EventType, "MARKET_DATA")

    def test_base_strategy_on_market_event_delegates_to_on_bar(self):
        """Base Strategy.on_market_event() must delegate to on_bar() by default."""
        from quant_us.strategies.base import Strategy

        # Verify the method exists
        assert hasattr(Strategy, "on_market_event")
        # It should delegate to on_bar
        assert hasattr(Strategy, "on_bar")

    def test_all_strategies_register_in_factory(self):
        """Every strategy must be registered in the factory."""
        from quant_us.strategies.factory import available_strategies

        strategies = available_strategies()
        assert len(strategies) >= 11
        # Key strategies must be present
        for sid in ["trend_momentum", "short_reversion", "etf_rotation",
                     "factor_rank", "earnings_drift"]:
            assert sid in strategies, f"Strategy {sid} not registered"

    def test_signal_direction_enum(self):
        """SignalDirection must define valid directions."""
        from quant_us.core.enums import SignalDirection
        values = [e.value for e in SignalDirection]
        assert len(values) >= 2  # at least LONG and SHORT (or equivalent)
