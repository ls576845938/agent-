from __future__ import annotations

import random as _random
from dataclasses import dataclass, field
from datetime import date
from itertools import groupby
from types import SimpleNamespace
from typing import Iterable, Protocol

import numpy as np

from quant_us.backtest.broker_simulator import SimulatedBroker
from quant_us.backtest.commission import PercentCommission
from quant_us.backtest.gap_session import GapConfig, SessionConfig, gap_adjusted_fill_price, is_bar_tradable
from quant_us.backtest.liquidity_slippage import LiquiditySlippage
from quant_us.backtest.performance import compute_performance
from quant_us.backtest.slippage import BpsSlippage
from quant_us.core.calendar import USEquityCalendar
from quant_us.core.events import Event, MarketEvent, OrderIntentEvent, SignalEvent, TargetPositionEvent
from quant_us.core.types import AccountState, Bar, Fill, Order, PortfolioSnapshot, new_id
from quant_us.execution.oms import OMSResult, OrderManagementSystem
from quant_us.portfolio.allocation import AllocationCombiner, AllocationConfig
from quant_us.portfolio.position_sizer import PercentOfEquitySizer, PositionSizerConfig
from quant_us.portfolio.rebalance import RebalanceConfig, RebalancePlanner
from quant_us.risk.pre_trade import PreTradeRiskConfig, PreTradeRiskEngine
from quant_us.strategies.base import Strategy, StrategyContext


FeatureMap = dict[date, dict[str, dict[str, float]]]


class BacktestBroker(Protocol):
    """Backtest broker surface required by the event-driven engine.

    This deliberately stays separate from execution.BrokerBase because the
    backtest engine needs simulated-market methods such as update_market and
    snapshot that real broker adapters should not be forced to expose.
    """

    market_prices: dict[str, float]

    def update_market(self, bar: Bar) -> None:
        ...

    def get_account(self) -> AccountState:
        ...

    def get_fills(self, order_id: str | None = None) -> list[Fill]:
        ...

    def get_orders(self) -> list[Order]:
        ...

    def submit_order(self, order: Order) -> Order:
        ...

    def cancel_order(self, order_id: str) -> Order:
        ...

    def snapshot(self, timestamp_utc) -> PortfolioSnapshot:
        ...


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


@dataclass
class _BacktestRunState:
    events: list[Event] = field(default_factory=list)
    oms_results: list[OMSResult] = field(default_factory=list)
    snapshots: list[PortfolioSnapshot] = field(default_factory=list)


class EventDrivenBacktestEngine:
    def __init__(
        self,
        strategies: list[Strategy],
        config: BacktestConfig | None = None,
        calendar: USEquityCalendar | None = None,
        features_by_date: FeatureMap | None = None,
        gap_config: GapConfig | None = None,
        session_config: SessionConfig | None = None,
        liquidity_slippage_model: LiquiditySlippage | None = None,
        broker: BacktestBroker | None = None,
    ) -> None:
        self.strategies = strategies
        self.config = config or BacktestConfig()
        self.calendar = calendar or USEquityCalendar()
        self.features_by_date = features_by_date or {}
        self.gap_config = gap_config
        self.session_config = session_config
        self.broker = broker or SimulatedBroker(
            initial_cash=self.config.initial_cash,
            commission_model=PercentCommission(rate=self.config.commission_rate),
            slippage_model=BpsSlippage(bps=self.config.slippage_bps),
            liquidity_slippage_model=liquidity_slippage_model,
        )
        self.sizer = PercentOfEquitySizer(self.config.sizing)
        self.allocator = AllocationCombiner(self.config.allocation)
        self.rebalance = RebalancePlanner(self.config.rebalance)
        self.risk_engine = PreTradeRiskEngine(self.config.risk, calendar=self.calendar)
        self.oms = OrderManagementSystem(self.broker, self.risk_engine, calendar=self.calendar)
        self._prev_close: dict[str, float] = {}
        self._gap_rejected_orders: list[dict] = []
        self._stream_events: list[MarketEvent] = []

    def run(self, bars: list[Bar]) -> BacktestResult:
        return self.run_slices(bars)

    def run_slices(self, bars: list[Bar]) -> BacktestResult:
        _random.seed(42)
        np.random.seed(42)

        self._prev_close = {}
        self._gap_rejected_orders = []
        state = _BacktestRunState()

        ordered = sorted(bars, key=lambda item: (item.timestamp_utc, item.symbol))
        for timestamp_utc, slice_iter in groupby(ordered, key=lambda item: item.timestamp_utc):
            self._process_slice(list(slice_iter), timestamp_utc, state)

        fills = self.broker.get_fills()
        orders = self.broker.get_orders()
        metadata: dict[str, object] = {}
        if self._gap_rejected_orders:
            metadata["gap_rejected_orders"] = list(self._gap_rejected_orders)
            metadata["gap_rejected_count"] = len(self._gap_rejected_orders)
        return BacktestResult(
            run_id=self.config.run_id,
            snapshots=state.snapshots,
            orders=orders,
            fills=fills,
            events=state.events,
            oms_results=state.oms_results,
            summary=compute_performance(state.snapshots, fills),
            metadata=metadata,
        )

    def run_streaming(self, events: Iterable[MarketEvent]) -> BacktestResult:
        """Run the same deterministic engine from a stream of MarketEvent objects."""
        for event in events:
            self.on_market_event(event)
        return self.flush_stream()

    def on_market_event(self, event: MarketEvent) -> None:
        """Accept one market event for later deterministic slice processing."""
        if event.bar is None:
            raise ValueError("MarketEvent.bar is required")
        self._stream_events.append(event)

    def flush_stream(self) -> BacktestResult:
        """Process buffered streaming market events and return a backtest result."""
        bars = [event.bar for event in self._stream_events]
        self._stream_events = []
        return self.run_slices(bars)

    def connection_health(self) -> dict[str, object]:
        """Return a local health snapshot without touching network resources."""
        return {
            "status": "ok",
            "broker": getattr(self.broker, "broker_name", self.broker.__class__.__name__),
            "market_prices": len(getattr(self.broker, "market_prices", {})),
        }

    def _process_slice(self, slice_bars: list[Bar], timestamp_utc, state: _BacktestRunState) -> None:
        # Build a per-symbol bar map for this timestamp
        bar_by_symbol: dict[str, Bar] = {}
        for bar in slice_bars:
            bar_by_symbol[bar.symbol] = bar
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
            state.events.append(market_event)
            for strategy in self.strategies:
                strategy_signals = list(strategy.on_market_event(market_event, context))
                signals.extend(strategy_signals)
                state.events.extend(SignalEvent.from_signal(signal) for signal in strategy_signals)

        targets = self.allocator.combine(self.sizer.size(signals))
        state.events.extend(TargetPositionEvent.from_target(target) for target in targets)
        account = self.broker.get_account()
        intents = self.rebalance.plan(targets, account, prices, self.config.run_id)
        state.events.extend(OrderIntentEvent.from_intent(intent) for intent in intents)

        # Apply gap overrides before processing orders
        if self.gap_config is not None and intents:
            gap_overrides: dict[str, float | None] = {}
            for intent in intents:
                bar = bar_by_symbol.get(intent.symbol)
                if bar is None:
                    continue
                prev_close = self._prev_close.get(intent.symbol)
                if prev_close is None or prev_close <= 0:
                    # No previous close — cannot detect gap, skip override
                    continue
                order_proxy = SimpleNamespace(side=intent.side)
                adj = gap_adjusted_fill_price(order_proxy, bar, prev_close, self.gap_config)
                if adj is None:
                    gap_overrides[intent.symbol] = None
                    self._gap_rejected_orders.append({
                        "timestamp": timestamp_utc,
                        "symbol": intent.symbol,
                        "side": intent.side.value,
                        "quantity": intent.quantity,
                        "reason": "extreme_gap",
                    })
                else:
                    gap_overrides[intent.symbol] = adj
            self._set_gap_overrides(gap_overrides)

        for intent in intents:
            account = self.broker.get_account()
            result = self.oms.handle_intent(intent, account, market_price=prices.get(intent.symbol, 0.0), timestamp=timestamp_utc)
            state.oms_results.append(result)
            state.events.extend(result.events)

        self._clear_gap_overrides()

        # Track previous closes for gap detection on next timestamp
        for bar in slice_bars:
            if bar.close > 0:
                self._prev_close[bar.symbol] = bar.close

        state.snapshots.append(self.broker.snapshot(timestamp_utc))

    def _set_gap_overrides(self, gap_overrides: dict[str, float | None]) -> None:
        setter = getattr(self.broker, "set_gap_overrides", None)
        if callable(setter):
            setter(gap_overrides)

    def _clear_gap_overrides(self) -> None:
        clearer = getattr(self.broker, "clear_gap_overrides", None)
        if callable(clearer):
            clearer()
