from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from quant_us.core.calendar import USEquityCalendar
from quant_us.core.enums import OrderSide, SessionName
from quant_us.core.types import AccountState, OrderIntent, RiskDecision
from quant_us.risk.exposure import gross_exposure


@dataclass(frozen=True)
class PortfolioRiskPolicy:
    cash_reserve_weight: float = 0.05
    max_symbol_weight: float = 0.10
    max_gross_exposure: float = 0.95
    max_daily_turnover: float = 1.0

    def gross_cap(self) -> float:
        cash_limited_cap = max(0.0, 1.0 - self.cash_reserve_weight)
        return max(0.0, min(self.max_gross_exposure, cash_limited_cap))

    def clamp_symbol_weight(self, weight: float) -> float:
        return max(-self.max_symbol_weight, min(self.max_symbol_weight, weight))

    def scale_target_weights_for_turnover(
        self,
        current_weights: dict[str, float],
        target_weights: dict[str, float],
    ) -> tuple[dict[str, float], float]:
        symbols = set(current_weights) | set(target_weights)
        turnover = sum(abs(target_weights.get(symbol, 0.0) - current_weights.get(symbol, 0.0)) for symbol in symbols)
        if turnover <= self.max_daily_turnover or turnover <= 0:
            return dict(target_weights), 1.0

        scale = self.max_daily_turnover / turnover
        scaled = {
            symbol: current_weights.get(symbol, 0.0) + (target_weights.get(symbol, 0.0) - current_weights.get(symbol, 0.0)) * scale
            for symbol in symbols
        }
        return scaled, scale


@dataclass(frozen=True)
class PreTradeRiskConfig:
    max_symbol_weight: float = 0.10
    max_gross_exposure: float = 1.0
    max_leverage: float = 1.0
    max_order_notional_pct: float = 0.10
    max_daily_turnover_pct: float = 1.0
    max_orders_per_minute: int = 60
    max_data_staleness_seconds: float = 300.0
    max_gap_pct: float = 20.0
    min_cash_buffer_pct: float = 0.02
    long_only: bool = True
    allowed_sessions: set[SessionName] = field(default_factory=lambda: {SessionName.REGULAR, SessionName.AFTER_HOURS})
    skip_session_check: bool = False
    blacklisted_symbols: set[str] = field(default_factory=set)
    risk_version: str = "risk_v0.1.0"


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
        metadata = dict(intent.metadata or {})
        if symbol in self.config.blacklisted_symbols:
            return self._reject(intent, "symbol_blacklisted")
        if self._metadata_bool(metadata, "market_data_stale"):
            return self._reject(intent, "market_data_stale", self.config.max_data_staleness_seconds)
        stale_seconds = self._metadata_float(metadata, "data_stale_seconds")
        if stale_seconds is not None and stale_seconds > self.config.max_data_staleness_seconds:
            return self._reject(intent, "market_data_stale", self.config.max_data_staleness_seconds)
        if self._metadata_bool(metadata, "market_data_gap") or self._metadata_bool(metadata, "data_gap_blocker"):
            return self._reject(intent, "market_data_gap", self.config.max_gap_pct)
        gap_pct = self._metadata_float(metadata, "gap_pct")
        if gap_pct is not None and abs(gap_pct) > self.config.max_gap_pct:
            return self._reject(intent, "market_data_gap", self.config.max_gap_pct)
        orders_last_minute = self._metadata_float(metadata, "orders_last_minute")
        if orders_last_minute is not None and orders_last_minute >= self.config.max_orders_per_minute:
            return self._reject(intent, "order_frequency_limit", float(self.config.max_orders_per_minute))
        if intent.quantity <= 0:
            return self._reject(intent, "non_positive_quantity")
        if market_price <= 0:
            return self._reject(intent, "missing_market_price")
        if not self.config.skip_session_check and not self.calendar.is_open(timestamp, self.config.allowed_sessions):
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
            return self._reject(intent, "order_notional_limit", self.config.max_order_notional_pct)
        daily_turnover_notional = self._metadata_float(metadata, "daily_turnover_notional")
        if daily_turnover_notional is None:
            daily_turnover_pct = self._metadata_float(metadata, "daily_turnover_pct")
            daily_turnover_notional = 0.0 if daily_turnover_pct is None else daily_turnover_pct * equity
        projected_turnover_pct = (max(0.0, daily_turnover_notional) + order_notional) / equity
        if projected_turnover_pct > self.config.max_daily_turnover_pct + 1e-9:
            return self._reject(intent, "turnover_limit", self.config.max_daily_turnover_pct)

        projected_symbol_weight = abs(projected_quantity * market_price) / equity
        if projected_symbol_weight > self.config.max_symbol_weight + 1e-9:
            return self._reject(intent, "symbol_weight_limit", self.config.max_symbol_weight)

        if intent.side == OrderSide.BUY:
            required_cash = order_notional
            cash_buffer = equity * self.config.min_cash_buffer_pct
            if account.cash - required_cash < cash_buffer:
                return self._reject(intent, "cash_buffer_limit", self.config.min_cash_buffer_pct)

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
        projected_gross_pct = gross_exposure(projected_positions) / equity
        if projected_gross_pct > self.config.max_gross_exposure + 1e-9:
            return self._reject(intent, "gross_exposure_limit", self.config.max_gross_exposure)
        if projected_gross_pct > self.config.max_leverage + 1e-9:
            return self._reject(intent, "leverage_limit", self.config.max_leverage)

        return RiskDecision(
            approved=True,
            reason="approved",
            order_intent_id=intent.order_intent_id,
            risk_version=self.config.risk_version,
            rule_name="",
            threshold=0.0,
        )

    def _reject(self, intent: OrderIntent, rule_name: str, threshold: float = 0.0) -> RiskDecision:
        return RiskDecision(
            approved=False,
            reason=rule_name,
            order_intent_id=intent.order_intent_id,
            risk_version=self.config.risk_version,
            rule_name=rule_name,
            threshold=threshold,
        )

    @staticmethod
    def _metadata_float(metadata: dict[str, object], key: str) -> float | None:
        if key not in metadata or metadata[key] is None:
            return None
        try:
            return float(metadata[key])
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _metadata_bool(metadata: dict[str, object], key: str) -> bool:
        value = metadata.get(key)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "y"}
        return bool(value)
