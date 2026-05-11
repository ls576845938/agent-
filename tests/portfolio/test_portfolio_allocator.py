from __future__ import annotations

from datetime import datetime, timezone

import pytest

from quant_us.core.enums import OrderSide
from quant_us.core.types import AccountState, OrderIntent, Position, TargetPosition
from quant_us.portfolio.allocation import AllocationConfig, PortfolioAllocator
from quant_us.risk.pre_trade import PortfolioRiskPolicy


def _ts() -> datetime:
    return datetime(2026, 1, 5, 14, 30, tzinfo=timezone.utc)


def test_allocate_targets_applies_strategy_weights_and_caps_with_reasons() -> None:
    allocator = PortfolioAllocator(
        config=AllocationConfig(
            strategy_weights={"alpha": 0.5, "beta": 0.25},
            max_symbol_weight=0.20,
            cash_reserve_weight=0.10,
        ),
        risk_policy=PortfolioRiskPolicy(
            cash_reserve_weight=0.10,
            max_symbol_weight=0.20,
            max_gross_exposure=0.60,
            max_daily_turnover=1.0,
        ),
    )

    result = allocator.allocate_targets(
        [
            TargetPosition(timestamp_utc=_ts(), strategy_id="alpha", symbol="AAPL", target_weight=0.40),
            TargetPosition(timestamp_utc=_ts(), strategy_id="beta", symbol="AAPL", target_weight=0.40),
            TargetPosition(timestamp_utc=_ts(), strategy_id="alpha", symbol="MSFT", target_weight=0.50),
            TargetPosition(timestamp_utc=_ts(), strategy_id="alpha", symbol="TSLA", target_weight=0.50),
        ]
    )

    weights = {target.symbol: target.target_weight for target in result.targets}
    assert weights["AAPL"] == pytest.approx(0.20)
    assert weights["MSFT"] == pytest.approx(0.20)
    assert weights["TSLA"] == pytest.approx(0.20)

    aapl_decision = next(item for item in result.target_decisions if item.symbol == "AAPL")
    msft_decision = next(item for item in result.target_decisions if item.symbol == "MSFT")
    assert {"strategy_weight", "max_symbol_weight"}.issubset({reason.rule_name for reason in aapl_decision.reasons})
    assert "max_symbol_weight" in {reason.rule_name for reason in msft_decision.reasons}


def test_allocate_targets_scales_to_turnover_cap_before_rebalance() -> None:
    allocator = PortfolioAllocator(
        config=AllocationConfig(max_symbol_weight=0.60, cash_reserve_weight=0.05),
        risk_policy=PortfolioRiskPolicy(
            cash_reserve_weight=0.05,
            max_symbol_weight=0.60,
            max_gross_exposure=0.95,
            max_daily_turnover=0.20,
        ),
    )
    account = AccountState(
        timestamp_utc=_ts(),
        account_id="acct",
        cash=50_000.0,
        equity=100_000.0,
        buying_power=100_000.0,
        positions={"AAPL": Position(symbol="AAPL", quantity=100.0, market_price=100.0)},
    )

    result = allocator.allocate_targets(
        [TargetPosition(timestamp_utc=_ts(), strategy_id="alpha", symbol="AAPL", target_weight=0.50)],
        account=account,
        prices={"AAPL": 100.0},
        run_id="run_1",
    )

    assert len(result.targets) == 1
    assert result.targets[0].target_weight == pytest.approx(0.30)
    assert len(result.intents) == 1
    assert result.intents[0].side == OrderSide.BUY
    assert result.intents[0].quantity == pytest.approx(200.0)
    assert "max_daily_turnover" in {reason.rule_name for reason in result.target_decisions[0].reasons}


def test_merge_order_intents_converts_to_final_portfolio_intent() -> None:
    allocator = PortfolioAllocator(
        config=AllocationConfig(
            strategy_weights={"alpha": 0.5, "beta": 0.5},
            max_symbol_weight=0.30,
            cash_reserve_weight=0.10,
        ),
        risk_policy=PortfolioRiskPolicy(
            cash_reserve_weight=0.10,
            max_symbol_weight=0.30,
            max_gross_exposure=0.90,
            max_daily_turnover=0.50,
        ),
    )
    account = AccountState(
        timestamp_utc=_ts(),
        account_id="acct",
        cash=100_000.0,
        equity=100_000.0,
        buying_power=100_000.0,
        positions={},
    )

    result = allocator.merge_order_intents(
        [
            OrderIntent(timestamp_utc=_ts(), strategy_id="alpha", symbol="NVDA", side=OrderSide.BUY, quantity=100.0),
            OrderIntent(timestamp_utc=_ts(), strategy_id="beta", symbol="NVDA", side=OrderSide.BUY, quantity=60.0),
        ],
        account=account,
        prices={"NVDA": 100.0},
        run_id="run_2",
    )

    assert len(result.intents) == 1
    final_intent = result.intents[0]
    assert final_intent.symbol == "NVDA"
    assert final_intent.side == OrderSide.BUY
    assert final_intent.quantity == 80.0
    assert result.targets[0].target_weight == pytest.approx(0.08)
