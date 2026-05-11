from __future__ import annotations

from datetime import datetime, timezone

from quant_us.core.enums import OrderSide
from quant_us.core.types import AccountState, OrderIntent, Position
from quant_us.risk.pre_trade import PreTradeRiskConfig, PreTradeRiskEngine


UTC = timezone.utc


def _account(*, cash: float = 10_000.0, equity: float = 10_000.0, btc_quantity: float = 0.0) -> AccountState:
    positions = {}
    if btc_quantity:
        positions["BTCUSD"] = Position(
            symbol="BTCUSD",
            quantity=btc_quantity,
            avg_price=50_000.0,
            market_price=50_000.0,
        )
    return AccountState(
        timestamp_utc=datetime(2026, 5, 11, 12, 0, tzinfo=UTC),
        account_id="paper_spot",
        cash=cash,
        equity=equity,
        buying_power=cash,
        positions=positions,
    )


def _intent(quantity: float, *, metadata: dict[str, object] | None = None) -> OrderIntent:
    return OrderIntent(
        timestamp_utc=datetime(2026, 5, 11, 12, 0, tzinfo=UTC),
        strategy_id="btc_spot_test",
        symbol="BTCUSD",
        side=OrderSide.BUY,
        quantity=quantity,
        metadata=metadata or {},
    )


def _engine(**overrides) -> PreTradeRiskEngine:
    config = PreTradeRiskConfig(
        skip_session_check=True,
        max_symbol_weight=10.0,
        max_order_notional_pct=10.0,
        min_cash_buffer_pct=0.0,
        **overrides,
    )
    return PreTradeRiskEngine(config)


def test_spot_risk_blocks_max_gross_exposure() -> None:
    decision = _engine(max_gross_exposure=0.75, max_leverage=10.0).evaluate(
        _intent(0.20),
        _account(),
        market_price=50_000.0,
        timestamp=datetime(2026, 5, 11, 12, 0, tzinfo=UTC),
    )

    assert decision.approved is False
    assert decision.reason == "gross_exposure_limit"


def test_spot_risk_blocks_max_leverage_separately_from_gross_cap() -> None:
    decision = _engine(max_gross_exposure=10.0, max_leverage=1.0).evaluate(
        _intent(0.05),
        _account(cash=10_000.0, equity=10_000.0, btc_quantity=0.20),
        market_price=50_000.0,
        timestamp=datetime(2026, 5, 11, 12, 0, tzinfo=UTC),
    )

    assert decision.approved is False
    assert decision.reason == "leverage_limit"


def test_spot_risk_blocks_turnover_and_order_frequency() -> None:
    turnover_decision = _engine(max_daily_turnover_pct=0.25).evaluate(
        _intent(0.02, metadata={"daily_turnover_notional": 2_000.0}),
        _account(),
        market_price=50_000.0,
        timestamp=datetime(2026, 5, 11, 12, 0, tzinfo=UTC),
    )
    frequency_decision = _engine(max_orders_per_minute=2).evaluate(
        _intent(0.01, metadata={"orders_last_minute": 2}),
        _account(),
        market_price=50_000.0,
        timestamp=datetime(2026, 5, 11, 12, 0, tzinfo=UTC),
    )

    assert turnover_decision.approved is False
    assert turnover_decision.reason == "turnover_limit"
    assert frequency_decision.approved is False
    assert frequency_decision.reason == "order_frequency_limit"


def test_spot_risk_blocks_stale_data_and_data_gaps() -> None:
    stale_decision = _engine(max_data_staleness_seconds=60.0).evaluate(
        _intent(0.01, metadata={"data_stale_seconds": 90.0}),
        _account(),
        market_price=50_000.0,
        timestamp=datetime(2026, 5, 11, 12, 0, tzinfo=UTC),
    )
    gap_decision = _engine(max_gap_pct=5.0).evaluate(
        _intent(0.01, metadata={"gap_pct": 7.5}),
        _account(),
        market_price=50_000.0,
        timestamp=datetime(2026, 5, 11, 12, 0, tzinfo=UTC),
    )

    assert stale_decision.approved is False
    assert stale_decision.reason == "market_data_stale"
    assert gap_decision.approved is False
    assert gap_decision.reason == "market_data_gap"
