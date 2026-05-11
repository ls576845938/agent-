from __future__ import annotations

from datetime import datetime, timedelta, timezone

from quant_us.backtest.engine import BacktestConfig, EventDrivenBacktestEngine
from quant_us.core.events import OrderIntentEvent, RiskEvent, TargetPositionEvent
from quant_us.core.types import Bar, TargetPosition
from quant_us.risk.pre_trade import PreTradeRiskConfig


UTC = timezone.utc


def _bar(ts: datetime, *, open_: float, close: float) -> Bar:
    return Bar(
        timestamp_utc=ts,
        symbol="AAPL",
        open=open_,
        high=max(open_, close) + 1.0,
        low=min(open_, close) - 1.0,
        close=close,
        volume=100_000.0,
        source="test",
        bar_size="1m",
    )


def _btc_bar(ts: datetime, *, open_: float = 50_000.0, close: float = 50_000.0) -> Bar:
    return Bar(
        timestamp_utc=ts,
        symbol="BTCUSD",
        open=open_,
        high=max(open_, close) + 100.0,
        low=min(open_, close) - 100.0,
        close=close,
        volume=100.0,
        source="sqlite",
        bar_size="1m",
    )


def _pypfopt_target(ts: datetime, weight: float = 0.55) -> TargetPosition:
    return TargetPosition(
        timestamp_utc=ts,
        strategy_id="pypfopt_portfolio",
        symbol="AAPL",
        target_weight=weight,
        metadata={
            "portfolio_run_id": "pf_test",
            "optimizer": "max_sharpe",
            "source": "pypfopt_target_weights",
        },
    )


def _btc_target(ts: datetime, weight: float = 0.55) -> TargetPosition:
    return TargetPosition(
        timestamp_utc=ts,
        strategy_id="btc_research_candidate",
        symbol="BTCUSD",
        target_weight=weight,
        metadata={"source": "crypto_research_target"},
    )


def test_external_target_weights_stop_at_order_intent_until_next_bar_risk_gate() -> None:
    start = datetime(2026, 5, 11, 14, 30, tzinfo=UTC)
    engine = EventDrivenBacktestEngine(
        strategies=[],
        config=BacktestConfig(
            commission_rate=0.0,
            slippage_bps=0.0,
            target_positions=(_pypfopt_target(start),),
        ),
    )

    result = engine.run([_bar(start, open_=100.0, close=100.0)])

    target_events = [event for event in result.events if isinstance(event, TargetPositionEvent)]
    intent_events = [event for event in result.events if isinstance(event, OrderIntentEvent)]
    assert len(target_events) == 1
    assert len(intent_events) == 1
    assert result.oms_results == []
    assert result.orders == []
    assert result.fills == []
    assert result.metadata["pending_intent_count"] == 1
    assert result.metadata["external_target_positions_consumed"] == 1

    target = target_events[0].target
    intent = intent_events[0].intent
    assert target.target_weight == 0.1
    assert target.metadata["source"] == "pypfopt_target_weights"
    assert target.metadata["boundary"] == "target_weight_to_target_position"
    assert intent.target_position_id == target.target_position_id
    assert intent.metadata["order_intent_boundary"] == "rebalance_planner"
    assert intent.metadata["risk_gate"] == "oms_pre_trade_risk"


def test_external_target_weights_execute_next_bar_only_after_risk_approval() -> None:
    start = datetime(2026, 5, 11, 14, 30, tzinfo=UTC)
    bars = [
        _bar(start, open_=100.0, close=100.0),
        _bar(start + timedelta(minutes=1), open_=99.0, close=101.0),
    ]
    engine = EventDrivenBacktestEngine(
        strategies=[],
        config=BacktestConfig(
            commission_rate=0.0,
            slippage_bps=0.0,
            risk=PreTradeRiskConfig(max_order_notional_pct=0.20),
            target_positions=(_pypfopt_target(start),),
        ),
    )

    result = engine.run(bars)

    risk_events = [event for event in result.events if isinstance(event, RiskEvent)]
    assert len(risk_events) == 1
    assert risk_events[0].decision.approved is True
    assert len(result.orders) == 1
    assert result.orders[0].risk_check_id == risk_events[0].decision.risk_check_id
    assert result.orders[0].timestamp_utc == bars[1].timestamp_utc
    assert result.orders[0].metadata["source"] == "pypfopt_target_weights"
    assert result.fills[0].filled_at == bars[1].timestamp_utc
    assert result.fills[0].price == 99.0
    assert result.summary["trade_count"] == 1


def test_external_target_weights_rejected_by_risk_gate_never_create_orders_or_fills() -> None:
    start = datetime(2026, 5, 11, 14, 30, tzinfo=UTC)
    bars = [
        _bar(start, open_=100.0, close=100.0),
        _bar(start + timedelta(minutes=1), open_=99.0, close=101.0),
    ]
    engine = EventDrivenBacktestEngine(
        strategies=[],
        config=BacktestConfig(
            commission_rate=0.0,
            slippage_bps=0.0,
            risk=PreTradeRiskConfig(max_order_notional_pct=0.05),
            target_positions=(_pypfopt_target(start, weight=0.55),),
        ),
    )

    result = engine.run(bars)

    risk_events = [event for event in result.events if isinstance(event, RiskEvent)]
    intent_events = [event for event in result.events if isinstance(event, OrderIntentEvent)]
    assert len(intent_events) == 1
    assert len(risk_events) == 1
    assert risk_events[0].decision.approved is False
    assert risk_events[0].decision.reason == "order_notional_limit"
    assert result.oms_results[0].risk_decision.reason == "order_notional_limit"
    assert result.orders == []
    assert result.fills == []
    assert result.metadata["external_target_position_semantics"] == (
        "target_weights_imported_as_target_positions_rebalanced_before_risk_gate"
    )


def test_crypto_target_positions_do_not_bypass_backtest_risk_gate() -> None:
    start = datetime(2026, 5, 11, 12, 0, tzinfo=UTC)
    bars = [
        _btc_bar(start),
        _btc_bar(start + timedelta(minutes=1), open_=50_100.0, close=50_200.0),
    ]
    engine = EventDrivenBacktestEngine(
        strategies=[],
        config=BacktestConfig(
            commission_rate=0.0,
            slippage_bps=0.0,
            risk=PreTradeRiskConfig(
                skip_session_check=True,
                max_symbol_weight=1.0,
                max_order_notional_pct=0.05,
            ),
            target_positions=(_btc_target(start),),
        ),
    )

    result = engine.run(bars)

    risk_events = [event for event in result.events if isinstance(event, RiskEvent)]
    assert len(risk_events) == 1
    assert risk_events[0].decision.approved is False
    assert risk_events[0].decision.reason == "order_notional_limit"
    assert result.orders == []
    assert result.fills == []
