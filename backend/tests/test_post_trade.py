"""Tests for PostTradeRiskEngine — slippage alerting."""

from __future__ import annotations

from datetime import datetime

import pytest

from quant_us.core.enums import OrderSide
from quant_us.core.types import Fill, new_id
from quant_us.risk.post_trade import PostTradeAlert, PostTradeRiskEngine


def _make_fill(
    price: float,
    side: OrderSide = OrderSide.BUY,
    symbol: str = "AAPL",
) -> Fill:
    return Fill(
        order_id="ord_test",
        symbol=symbol,
        side=side,
        quantity=100.0,
        price=price,
        commission=1.0,
        filled_at=datetime(2026, 5, 3, 12, 0, 0),
        fill_id=new_id("fill"),
    )


class TestPostTradeRiskEngine:
    """Tests for PostTradeRiskEngine.check_slippage."""

    def test_slippage_within_limit(self) -> None:
        """Fill price within 50 bps of expected — no alerts."""
        engine = PostTradeRiskEngine()
        fill = _make_fill(price=100.5)  # 50 bps, but boundary is > not >=
        alerts = engine.check_slippage(fill, expected_price=100.0)
        assert alerts == []

    def test_slippage_exceeds_limit_buy(self) -> None:
        """BUY fill 100 bps above expected — alert."""
        engine = PostTradeRiskEngine()
        fill = _make_fill(price=101.0, side=OrderSide.BUY)
        alerts = engine.check_slippage(fill, expected_price=100.0)
        assert len(alerts) == 1
        assert alerts[0].reason == "slippage_limit"
        assert alerts[0].observed_value == pytest.approx(100.0)

    def test_slippage_exceeds_limit_sell(self) -> None:
        """SELL fill 100 bps below expected — alert."""
        engine = PostTradeRiskEngine()
        fill = _make_fill(price=99.0, side=OrderSide.SELL)
        alerts = engine.check_slippage(fill, expected_price=100.0)
        assert len(alerts) == 1
        assert alerts[0].reason == "slippage_limit"
        assert alerts[0].observed_value == pytest.approx(100.0)

    def test_slippage_at_exact_boundary(self) -> None:
        """Exactly 50 bps — boundary is > not >=, so no alert."""
        engine = PostTradeRiskEngine()
        fill = _make_fill(price=100.5)
        alerts = engine.check_slippage(fill, expected_price=100.0)
        assert alerts == []

    def test_slippage_zero_expected_price(self) -> None:
        """expected_price == 0 triggers missing_expected_price."""
        engine = PostTradeRiskEngine()
        fill = _make_fill(price=100.0)
        alerts = engine.check_slippage(fill, expected_price=0.0)
        assert len(alerts) == 1
        assert alerts[0].reason == "missing_expected_price"
        assert alerts[0].observed_value == 0.0

    def test_slippage_negative_expected_price(self) -> None:
        """expected_price < 0 triggers missing_expected_price."""
        engine = PostTradeRiskEngine()
        fill = _make_fill(price=100.0)
        alerts = engine.check_slippage(fill, expected_price=-10.0)
        assert len(alerts) == 1
        assert alerts[0].reason == "missing_expected_price"
        assert alerts[0].observed_value == 0.0

    def test_custom_threshold(self) -> None:
        """Custom 10 bps threshold with 20 bps slippage — alert."""
        engine = PostTradeRiskEngine(max_slippage_bps=10.0)
        fill = _make_fill(price=100.2)  # 20 bps
        alerts = engine.check_slippage(fill, expected_price=100.0)
        assert len(alerts) == 1
        assert alerts[0].reason == "slippage_limit"
        assert alerts[0].observed_value == pytest.approx(20.0)

    def test_alert_fields_match(self) -> None:
        """Verify fill_id, reason, observed_value in the alert."""
        engine = PostTradeRiskEngine()
        fill = _make_fill(price=110.0)  # 1000 bps
        alerts = engine.check_slippage(fill, expected_price=100.0)
        assert len(alerts) == 1
        alert = alerts[0]
        assert isinstance(alert, PostTradeAlert)
        assert alert.fill_id == fill.fill_id
        assert alert.reason == "slippage_limit"
        assert alert.observed_value == pytest.approx(1000.0)
