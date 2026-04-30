from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from quant_us.core.calendar import USEquityCalendar
from quant_us.core.enums import OrderSide, SessionName
from quant_us.core.types import AccountState, OrderIntent, RiskDecision
from quant_us.risk.exposure import gross_exposure


@dataclass(frozen=True)
class PreTradeRiskConfig:
    max_symbol_weight: float = 0.10
    max_gross_exposure: float = 1.0
    max_order_notional_pct: float = 0.10
    min_cash_buffer_pct: float = 0.02
    long_only: bool = True
    allowed_sessions: set[SessionName] = field(default_factory=lambda: {SessionName.REGULAR})
    blacklisted_symbols: set[str] = field(default_factory=set)


class PreTradeRiskEngine:
    def __init__(self, config: PreTradeRiskConfig | None = None, calendar: USEquityCalendar | None = None) -> None:
        self.config = config or PreTradeRiskConfig()
        self.calendar = calendar or USEquityCalendar()

    def evaluate(
        self,
        intent: OrderIntent,
        account: AccountState,
        market_price: float,
        timestamp: datetime,
    ) -> RiskDecision:
        symbol = intent.symbol.upper()
        if symbol in self.config.blacklisted_symbols:
            return self._reject(intent, "symbol_blacklisted")
        if intent.quantity <= 0:
            return self._reject(intent, "non_positive_quantity")
        if market_price <= 0:
            return self._reject(intent, "missing_market_price")
        if not self.calendar.is_open(timestamp, self.config.allowed_sessions):
            return self._reject(intent, "session_not_allowed")

        position = account.positions.get(symbol)
        current_quantity = position.quantity if position else 0.0
        delta = intent.quantity if intent.side == OrderSide.BUY else -intent.quantity
        projected_quantity = current_quantity + delta
        if self.config.long_only and projected_quantity < -1e-9:
            return self._reject(intent, "long_only_short_sale")

        equity = max(account.equity, 1.0)
        order_notional = abs(intent.quantity * market_price)
        if order_notional / equity > self.config.max_order_notional_pct:
            return self._reject(intent, "order_notional_limit")

        projected_symbol_weight = abs(projected_quantity * market_price) / equity
        if projected_symbol_weight > self.config.max_symbol_weight + 1e-9:
            return self._reject(intent, "symbol_weight_limit")

        if intent.side == OrderSide.BUY:
            required_cash = order_notional
            cash_buffer = equity * self.config.min_cash_buffer_pct
            if account.cash - required_cash < cash_buffer:
                return self._reject(intent, "cash_buffer_limit")

        projected_positions = dict(account.positions)
        if position:
            projected_positions[symbol] = type(position)(
                symbol=symbol,
                quantity=projected_quantity,
                avg_price=position.avg_price,
                market_price=market_price,
            )
        else:
            from quant_us.core.types import Position

            projected_positions[symbol] = Position(symbol=symbol, quantity=projected_quantity, market_price=market_price)
        if gross_exposure(projected_positions) / equity > self.config.max_gross_exposure + 1e-9:
            return self._reject(intent, "gross_exposure_limit")

        return RiskDecision(approved=True, reason="approved", order_intent_id=intent.order_intent_id)

    @staticmethod
    def _reject(intent: OrderIntent, reason: str) -> RiskDecision:
        return RiskDecision(approved=False, reason=reason, order_intent_id=intent.order_intent_id)
