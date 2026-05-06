from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from quant_us.backtest.commission import PercentCommission
from quant_us.backtest.liquidity_slippage import LiquiditySlippage
from quant_us.backtest.slippage import BpsSlippage
from quant_us.core.clock import utc_now
from quant_us.core.enums import OrderSide, OrderStatus
from quant_us.core.types import AccountState, Bar, Fill, Order, PortfolioSnapshot, Position, new_id
from quant_us.execution.broker_base import BrokerBase
from quant_us.risk.exposure import gross_exposure, net_exposure


def _deterministic_random(seed: str, low: float = 0.0, high: float = 1.0) -> float:
    digest = hashlib.sha256(seed.encode()).hexdigest()[:8]
    return low + (int(digest, 16) / 0xFFFFFFFF) * (high - low)


@dataclass
class SimulatedBroker(BrokerBase):
    initial_cash: float = 100_000.0
    commission_model: PercentCommission = field(default_factory=PercentCommission)
    slippage_model: BpsSlippage = field(default_factory=BpsSlippage)
    liquidity_slippage_model: LiquiditySlippage | None = None
    broker_name: str = "sim"
    fill_ratio: float = 1.0
    volume_participation_cap_pct: float = 5.0
    bar_volumes: dict[str, float] = field(default_factory=dict)
    cash: float = field(init=False)
    positions: dict[str, Position] = field(default_factory=dict)
    orders: list[Order] = field(default_factory=list)
    fills: list[Fill] = field(default_factory=list)
    market_prices: dict[str, float] = field(default_factory=dict)
    start_equity: float = field(init=False)
    high_water_equity: float = field(init=False)
    gap_overrides: dict[str, float | None] = field(default_factory=dict)
    _order_counter: int = field(init=False, default=0)

    def set_gap_overrides(self, overrides: dict[str, float | None]) -> None:
        self.gap_overrides.clear()
        self.gap_overrides.update(overrides)

    def clear_gap_overrides(self) -> None:
        self.gap_overrides.clear()

    def __post_init__(self) -> None:
        self.cash = self.initial_cash
        self.start_equity = self.initial_cash
        self.high_water_equity = self.initial_cash

    def update_market(self, bar: Bar) -> None:
        self.market_prices[bar.symbol] = float(bar.close)
        self.bar_volumes[bar.symbol] = float(bar.volume) if bar.volume else 0.0
        if bar.symbol in self.positions:
            position = self.positions[bar.symbol]
            position.market_price = float(bar.close)
            position.unrealized_pnl = (position.market_price - position.avg_price) * position.quantity

    def get_account(self) -> AccountState:
        equity = self.cash + sum(position.market_value for position in self.positions.values())
        return AccountState(
            timestamp_utc=utc_now(),
            account_id=self.broker_name,
            cash=self.cash,
            equity=equity,
            buying_power=self.cash,
            positions={symbol: Position(**position.__dict__) for symbol, position in self.positions.items()},
        )

    def get_positions(self) -> dict[str, Position]:
        return {symbol: Position(**position.__dict__) for symbol, position in self.positions.items()}

    def get_orders(self) -> list[Order]:
        return list(self.orders)

    def submit_order(self, order: Order) -> Order:
        # Check gap overrides first — if set, override market price or reject
        if order.symbol in self.gap_overrides:
            override = self.gap_overrides[order.symbol]
            if override is None:
                order.status = OrderStatus.REJECTED
                order.broker_order_id = new_id("sim")
                order.updated_at = utc_now()
                self.orders.append(order)
                return order
            price = override
        else:
            price = self.market_prices.get(order.symbol)

        if price is None or price <= 0:
            order.status = OrderStatus.REJECTED
            order.updated_at = utc_now()
            self.orders.append(order)
            return order

        order.status = OrderStatus.ACCEPTED
        order.broker_order_id = new_id("sim")
        order.updated_at = utc_now()

        self._order_counter += 1
        fillable_quantity = self._compute_fillable_quantity(order, price)

        if fillable_quantity <= 0:
            order.status = OrderStatus.REJECTED
            order.updated_at = utc_now()
            self.orders.append(order)
            return order

        if fillable_quantity < order.quantity:
            filled_qty = fillable_quantity
            if self.liquidity_slippage_model is not None:
                fill_price = self.liquidity_slippage_model.apply(order.side, price, filled_qty, self.bar_volumes.get(order.symbol, 0.0))
            else:
                fill_price = self.slippage_model.apply(order.side, price)
            notional = filled_qty * fill_price
            commission = self.commission_model.calculate(notional)
            fill = Fill(
                order_id=order.order_id,
                symbol=order.symbol,
                side=order.side,
                quantity=filled_qty,
                price=fill_price,
                commission=commission,
                filled_at=order.timestamp_utc,
                broker=self.broker_name,
                broker_order_id=order.broker_order_id,
            )
            self._apply_fill(fill)
            self.fills.append(fill)
            order.status = OrderStatus.PARTIALLY_FILLED
        else:
            filled_qty = order.quantity
            if self.liquidity_slippage_model is not None:
                fill_price = self.liquidity_slippage_model.apply(order.side, price, filled_qty, self.bar_volumes.get(order.symbol, 0.0))
            else:
                fill_price = self.slippage_model.apply(order.side, price)
            notional = filled_qty * fill_price
            commission = self.commission_model.calculate(notional)
            fill = Fill(
                order_id=order.order_id,
                symbol=order.symbol,
                side=order.side,
                quantity=filled_qty,
                price=fill_price,
                commission=commission,
                filled_at=order.timestamp_utc,
                broker=self.broker_name,
                broker_order_id=order.broker_order_id,
            )
            self._apply_fill(fill)
            self.fills.append(fill)
            order.status = OrderStatus.FILLED

        order.updated_at = utc_now()
        self.orders.append(order)
        return order

    def _compute_fillable_quantity(self, order: Order, price: float) -> float:
        requested = abs(order.quantity)

        if self.fill_ratio < 1.0:
            seed = f"{order.order_id}:{self._order_counter}:fill"
            roll = _deterministic_random(seed)
            if roll > self.fill_ratio:
                requested *= self.fill_ratio

        bar_volume = self.bar_volumes.get(order.symbol, 0.0)
        if bar_volume > 0 and self.volume_participation_cap_pct > 0:
            max_by_volume = bar_volume * self.volume_participation_cap_pct / 100.0
            requested_notional = requested * price
            max_notional = max_by_volume * price
            if requested_notional > max_notional:
                requested = max_by_volume

        return round(requested, 8)

    def cancel_order(self, order_id: str) -> Order:
        for order in self.orders:
            if order.order_id == order_id:
                order.status = OrderStatus.CANCELLED
                order.updated_at = utc_now()
                return order
        raise KeyError(order_id)

    def get_fills(self, order_id: str | None = None) -> list[Fill]:
        if order_id is None:
            return list(self.fills)
        return [fill for fill in self.fills if fill.order_id == order_id]

    def snapshot(self, timestamp_utc) -> PortfolioSnapshot:
        account = self.get_account()
        self.high_water_equity = max(self.high_water_equity, account.equity)
        gross = gross_exposure(account.positions)
        net = net_exposure(account.positions)
        drawdown = 0.0
        if self.high_water_equity > 0:
            drawdown = account.equity / self.high_water_equity - 1.0
        return PortfolioSnapshot(
            timestamp_utc=timestamp_utc,
            equity=account.equity,
            cash=account.cash,
            gross_exposure=gross,
            net_exposure=net,
            daily_pnl=account.equity - self.start_equity,
            drawdown=drawdown,
        )

    def _apply_fill(self, fill: Fill) -> None:
        signed_quantity = fill.quantity if fill.side == OrderSide.BUY else -fill.quantity
        cash_delta = -fill.quantity * fill.price - fill.commission if fill.side == OrderSide.BUY else fill.quantity * fill.price - fill.commission
        self.cash += cash_delta
        position = self.positions.get(fill.symbol, Position(symbol=fill.symbol, market_price=fill.price))
        old_quantity = position.quantity
        new_quantity = old_quantity + signed_quantity
        if new_quantity == 0:
            position.quantity = 0.0
            position.avg_price = 0.0
        elif old_quantity >= 0 and signed_quantity > 0:
            position.avg_price = ((old_quantity * position.avg_price) + (fill.quantity * fill.price)) / new_quantity
            position.quantity = new_quantity
        else:
            position.quantity = new_quantity
            if position.avg_price == 0:
                position.avg_price = fill.price
        position.market_price = self.market_prices.get(fill.symbol, fill.price)
        position.unrealized_pnl = (position.market_price - position.avg_price) * position.quantity
        self.positions[fill.symbol] = position
