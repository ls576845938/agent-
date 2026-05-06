"""Tests for quant_us/risk/exposure.py and quant_us/risk/liquidity.py."""

from __future__ import annotations

from datetime import datetime

import pytest

from quant_us.core.enums import OrderSide, OrderType, TimeInForce
from quant_us.core.types import OrderIntent, Position
from quant_us.risk.exposure import gross_exposure, net_exposure
from quant_us.risk.liquidity import LiquidityGuard, LiquidityRule

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BUY = OrderSide.BUY
_SELL = OrderSide.SELL
_MARKET = OrderType.MARKET
_DAY = TimeInForce.DAY


def _pos(symbol: str, quantity: float, market_price: float) -> Position:
    return Position(symbol=symbol, quantity=quantity, market_price=market_price)


def _intent(quantity: float, symbol: str = "TEST") -> OrderIntent:
    return OrderIntent(
        timestamp_utc=datetime(2026, 1, 1),
        strategy_id="s1",
        symbol=symbol,
        side=_BUY,
        quantity=quantity,
        order_type=_MARKET,
        time_in_force=_DAY,
    )


# ===================================================================
# Exposure tests
# ===================================================================


class TestGrossExposure:
    def test_empty(self) -> None:
        assert gross_exposure({}) == 0.0

    def test_long_only(self) -> None:
        positions = {"A": _pos("A", 100, 50.0), "B": _pos("B", 200, 25.0)}
        # 100*50 + 200*25 = 5000 + 5000 = 10000
        assert gross_exposure(positions) == 10000.0

    def test_short_only(self) -> None:
        positions = {"A": _pos("A", -100, 50.0), "B": _pos("B", -200, 25.0)}
        # |-5000| + |-5000| = 10000
        assert gross_exposure(positions) == 10000.0

    def test_mixed(self) -> None:
        positions = {"A": _pos("A", 100, 50.0), "B": _pos("B", -50, 20.0)}
        # |5000| + |-1000| = 6000
        assert gross_exposure(positions) == 6000.0

    def test_zero_market_value(self) -> None:
        positions = {"A": _pos("A", 0, 100.0)}
        assert gross_exposure(positions) == 0.0

    def test_single_negative_market_price(self) -> None:
        positions = {"A": _pos("A", 100, -5.0)}
        assert gross_exposure(positions) == 500.0


class TestNetExposure:
    def test_empty(self) -> None:
        assert net_exposure({}) == 0.0

    def test_long_only(self) -> None:
        positions = {"A": _pos("A", 100, 50.0), "B": _pos("B", 200, 25.0)}
        # 5000 + 5000 = 10000
        assert net_exposure(positions) == 10000.0

    def test_short_only(self) -> None:
        positions = {"A": _pos("A", -100, 50.0), "B": _pos("B", -200, 25.0)}
        # -5000 + -5000 = -10000
        assert net_exposure(positions) == -10000.0

    def test_mixed(self) -> None:
        positions = {"A": _pos("A", 100, 50.0), "B": _pos("B", -50, 20.0)}
        # 5000 + -1000 = 4000
        assert net_exposure(positions) == 4000.0

    def test_zero_market_value(self) -> None:
        positions = {"A": _pos("A", 0, 100.0)}
        assert net_exposure(positions) == 0.0

    def test_single_negative_market_price(self) -> None:
        positions = {"A": _pos("A", 100, -5.0)}
        assert net_exposure(positions) == -500.0


class TestGrossVsNet:
    """Invariant: |net_exposure| <= gross_exposure for any portfolio."""

    def test_all_long(self) -> None:
        positions = {"A": _pos("A", 100, 50.0), "B": _pos("B", 200, 25.0)}
        g = gross_exposure(positions)
        n = net_exposure(positions)
        assert abs(n) <= g

    def test_all_short(self) -> None:
        positions = {"A": _pos("A", -100, 50.0), "B": _pos("B", -200, 25.0)}
        g = gross_exposure(positions)
        n = net_exposure(positions)
        assert abs(n) <= g

    def test_mixed(self) -> None:
        positions = {"A": _pos("A", 100, 50.0), "B": _pos("B", -50, 20.0)}
        g = gross_exposure(positions)
        n = net_exposure(positions)
        assert abs(n) <= g

    def test_equal_when_same_direction(self) -> None:
        positions = {"A": _pos("A", 100, 50.0)}
        assert gross_exposure(positions) == abs(net_exposure(positions))


# ===================================================================
# Liquidity tests
# ===================================================================


class TestLiquidityGuard:
    def test_approves_small_order(self) -> None:
        guard = LiquidityGuard()
        intent = _intent(quantity=100.0)
        adv = 1_000_000.0  # 100 / 1_000_000 = 0.0001 < 0.01
        decision = guard.evaluate(intent, adv)
        assert decision.approved is True
        assert decision.reason == "approved"
        assert decision.order_intent_id == intent.order_intent_id

    def test_rejects_large_order(self) -> None:
        guard = LiquidityGuard()
        intent = _intent(quantity=200_000.0)
        adv = 1_000_000.0  # 200_000 / 1_000_000 = 0.2 > 0.01
        decision = guard.evaluate(intent, adv)
        assert decision.approved is False
        assert decision.reason == "adv_participation_limit"
        assert decision.order_intent_id == intent.order_intent_id

    def test_zero_adv(self) -> None:
        guard = LiquidityGuard()
        intent = _intent(quantity=100.0)
        decision = guard.evaluate(intent, 0.0)
        assert decision.approved is False
        assert decision.reason == "missing_liquidity"
        assert decision.order_intent_id == intent.order_intent_id

    def test_negative_adv(self) -> None:
        guard = LiquidityGuard()
        intent = _intent(quantity=100.0)
        decision = guard.evaluate(intent, -5000.0)
        assert decision.approved is False
        assert decision.reason == "missing_liquidity"
        assert decision.order_intent_id == intent.order_intent_id

    def test_exact_boundary_approved(self) -> None:
        """quantity / adv == max_adv_participation exactly. The guard uses >, so exactly-on passes."""
        guard = LiquidityGuard()
        adv = 1_000_000.0
        intent = _intent(quantity=10_000.0)  # 10_000 / 1_000_000 = 0.01 exactly
        decision = guard.evaluate(intent, adv)
        assert decision.approved is True
        assert decision.reason == "approved"

    def test_just_over_boundary_rejected(self) -> None:
        """quantity / adv just exceeds max_adv_participation."""
        guard = LiquidityGuard()
        adv = 1_000_000.0
        intent = _intent(quantity=10_001.0)  # 10_001 / 1_000_000 > 0.01
        decision = guard.evaluate(intent, adv)
        assert decision.approved is False
        assert decision.reason == "adv_participation_limit"

    def test_custom_rule(self) -> None:
        """Custom max_adv_participation of 0.05."""
        rule = LiquidityRule(max_adv_participation=0.05)
        guard = LiquidityGuard(rule)
        adv = 1_000_000.0
        intent = _intent(quantity=50_000.0)  # 50_000 / 1_000_000 = 0.05 == boundary → approved
        decision = guard.evaluate(intent, adv)
        assert decision.approved is True
        assert decision.reason == "approved"

    def test_custom_rule_rejected(self) -> None:
        rule = LiquidityRule(max_adv_participation=0.05)
        guard = LiquidityGuard(rule)
        adv = 1_000_000.0
        intent = _intent(quantity=60_000.0)  # 60_000 / 1_000_000 = 0.06 > 0.05
        decision = guard.evaluate(intent, adv)
        assert decision.approved is False
        assert decision.reason == "adv_participation_limit"


class TestLiquidityRuleDefault:
    def test_default_max_adv_participation(self) -> None:
        rule = LiquidityRule()
        assert rule.max_adv_participation == 0.01

    def test_default_rejects_above_one_percent(self) -> None:
        rule = LiquidityRule()
        guard = LiquidityGuard(rule)
        adv = 100_000.0
        intent = _intent(quantity=2_000.0)  # 2_000 / 100_000 = 0.02 > 0.01
        decision = guard.evaluate(intent, adv)
        assert decision.approved is False
        assert decision.reason == "adv_participation_limit"
