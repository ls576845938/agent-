from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from itertools import groupby

from quant_us.backtest.broker_simulator import SimulatedBroker
from quant_us.backtest.commission import PercentCommission
from quant_us.backtest.performance import compute_performance
from quant_us.backtest.slippage import BpsSlippage
from quant_us.core.calendar import USEquityCalendar
from quant_us.core.events import Event, MarketEvent, OrderIntentEvent, SignalEvent, TargetPositionEvent
from quant_us.core.types import Bar, Fill, Order, PortfolioSnapshot, new_id
from quant_us.execution.oms import OMSResult, OrderManagementSystem
from quant_us.portfolio.allocation import AllocationCombiner, AllocationConfig
from quant_us.portfolio.position_sizer import PercentOfEquitySizer, PositionSizerConfig
from quant_us.portfolio.rebalance import RebalanceConfig, RebalancePlanner
from quant_us.risk.pre_trade import PreTradeRiskConfig, PreTradeRiskEngine
from quant_us.strategies.base import Strategy, StrategyContext


FeatureMap = dict[date, dict[str, dict[str, float]]]


@dataclass(frozen=True)
class BacktestConfig:
    initial_cash: float = 100_000.0
    commission_rate: float = 0.0001
    slippage_bps: float = 1.0
    run_id: str = field(default_factory=lambda: new_id("bt"))
    risk: PreTradeRiskConfig = field(default_factory=PreTradeRiskConfig)
    sizing: PositionSizerConfig = field(default_factory=PositionSizerConfig)
    allocation: AllocationConfig = field(default_factory=AllocationConfig)
    rebalance: RebalanceConfig = field(default_factory=RebalanceConfig)


@dataclass(frozen=True)
class BacktestResult:
    run_id: str
    snapshots: list[PortfolioSnapshot]
    orders: list[Order]
    fills: list[Fill]
    events: list[Event]
    oms_results: list[OMSResult]
    summary: dict[str, float | int]
    metadata: dict[str, object] = field(default_factory=dict)


class EventDrivenBacktestEngine:
    def __init__(
        self,
        strategies: list[Strategy],
        config: BacktestConfig | None = None,
        calendar: USEquityCalendar | None = None,
        features_by_date: FeatureMap | None = None,
    ) -> None:
        self.strategies = strategies
        self.config = config or BacktestConfig()
        self.calendar = calendar or USEquityCalendar()
        self.features_by_date = features_by_date or {}
        self.broker = SimulatedBroker(
            initial_cash=self.config.initial_cash,
            commission_model=PercentCommission(rate=self.config.commission_rate),
            slippage_model=BpsSlippage(bps=self.config.slippage_bps),
        )
        self.sizer = PercentOfEquitySizer(self.config.sizing)
        self.allocator = AllocationCombiner(self.config.allocation)
        self.rebalance = RebalancePlanner(self.config.rebalance)
        self.risk_engine = PreTradeRiskEngine(self.config.risk, calendar=self.calendar)
        self.oms = OrderManagementSystem(self.broker, self.risk_engine, calendar=self.calendar)

    def run(self, bars: list[Bar]) -> BacktestResult:
        return self.run_slices(bars)

    def run_slices(self, bars: list[Bar]) -> BacktestResult:
        events: list[Event] = []
        oms_results: list[OMSResult] = []
        snapshots: list[PortfolioSnapshot] = []

        ordered = sorted(bars, key=lambda item: (item.timestamp_utc, item.symbol))
        for timestamp_utc, slice_iter in groupby(ordered, key=lambda item: item.timestamp_utc):
            slice_bars = list(slice_iter)
            for bar in slice_bars:
                self.broker.update_market(bar)

            account = self.broker.get_account()
            prices = {symbol: float(price) for symbol, price in self.broker.market_prices.items()}
            context = StrategyContext(
                run_id=self.config.run_id,
                account=account,
                market_prices=prices,
                features=self.features_by_date.get(timestamp_utc.date(), {}),
                universe=sorted(prices),
            )

            signals = []
            for bar in slice_bars:
                market_event = MarketEvent.from_bar(bar)
                events.append(market_event)
                for strategy in self.strategies:
                    strategy_signals = list(strategy.on_bar(market_event, context))
                    signals.extend(strategy_signals)
                    events.extend(SignalEvent.from_signal(signal) for signal in strategy_signals)

            targets = self.allocator.combine(self.sizer.size(signals))
            events.extend(TargetPositionEvent.from_target(target) for target in targets)
            account = self.broker.get_account()
            intents = self.rebalance.plan(targets, account, prices, self.config.run_id)
            events.extend(OrderIntentEvent.from_intent(intent) for intent in intents)

            for intent in intents:
                account = self.broker.get_account()
                result = self.oms.handle_intent(intent, account, market_price=prices.get(intent.symbol, 0.0), timestamp=timestamp_utc)
                oms_results.append(result)
                events.extend(result.events)

            snapshots.append(self.broker.snapshot(timestamp_utc))

        fills = self.broker.get_fills()
        orders = self.broker.get_orders()
        return BacktestResult(
            run_id=self.config.run_id,
            snapshots=snapshots,
            orders=orders,
            fills=fills,
            events=events,
            oms_results=oms_results,
            summary=compute_performance(snapshots, fills),
        )
