"""Shadow Order, Shadow Fill, and Shadow Ledger models for G2 shadow-live validation.

All models are immutable (frozen dataclasses). They capture what the system
*would* have done without submitting any real orders.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from quant_us.core.enums import OrderSide, OrderType
from quant_us.core.types import new_id


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class ShadowOrder:
    """An order the system would have submitted to a live broker.

    Captures the full signal → target → risk → order_intent chain.
    ``would_submit`` is always True; ``real_submit`` is always False.
    """

    shadow_order_id: str
    run_id: str
    strategy_id: str
    signal_id: str
    target_position_id: str
    order_intent_id: str
    risk_check_id: str
    symbol: str
    side: OrderSide
    quantity: float
    estimated_price: float
    estimated_notional: float
    order_type: OrderType
    would_submit: bool = True
    real_submit: bool = False
    block_reason: str = "shadow_live_readonly"
    created_at: datetime = field(default_factory=_utc_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "shadow_order_id": self.shadow_order_id,
            "run_id": self.run_id,
            "strategy_id": self.strategy_id,
            "signal_id": self.signal_id,
            "target_position_id": self.target_position_id,
            "order_intent_id": self.order_intent_id,
            "risk_check_id": self.risk_check_id,
            "symbol": self.symbol,
            "side": self.side.value,
            "quantity": self.quantity,
            "estimated_price": self.estimated_price,
            "estimated_notional": self.estimated_notional,
            "order_type": self.order_type.value,
            "would_submit": self.would_submit,
            "real_submit": self.real_submit,
            "block_reason": self.block_reason,
            "created_at": self.created_at.isoformat(),
        }


@dataclass(frozen=True)
class ShadowFill:
    """Simulated fill for a shadow order — never a real fill."""

    shadow_fill_id: str
    shadow_order_id: str
    simulated_fill_price: float
    simulated_fill_qty: float
    slippage_model: str
    commission_model: str
    created_at: datetime = field(default_factory=_utc_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "shadow_fill_id": self.shadow_fill_id,
            "shadow_order_id": self.shadow_order_id,
            "simulated_fill_price": self.simulated_fill_price,
            "simulated_fill_qty": self.simulated_fill_qty,
            "slippage_model": self.slippage_model,
            "commission_model": self.commission_model,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class ShadowLedger:
    """Tracks what the shadow portfolio *would* look like.

    Mutated in-place during a shadow-live run. Does NOT affect any real account.
    """

    shadow_cash: float = 100_000.0
    shadow_positions: dict[str, float] = field(default_factory=dict)
    shadow_equity: float = 100_000.0
    shadow_pnl: float = 0.0
    shadow_exposure: float = 0.0
    shadow_drawdown: float = 0.0
    peak_equity: float = 100_000.0

    def apply_shadow_fill(
        self,
        symbol: str,
        side: OrderSide,
        qty: float,
        price: float,
        commission: float = 0.0,
    ) -> None:
        signed_qty = qty if side == OrderSide.BUY else -qty
        cost = abs(qty) * price + commission

        prev = self.shadow_positions.get(symbol, 0.0)
        self.shadow_positions[symbol] = prev + signed_qty
        if side == OrderSide.BUY:
            self.shadow_cash -= cost
        else:
            self.shadow_cash += abs(qty) * price - commission

        long_value = sum(
            q * self._last_price(s) for s, q in self.shadow_positions.items()
        )
        self.shadow_equity = self.shadow_cash + long_value
        self.shadow_pnl = self.shadow_equity - 100_000.0
        self.shadow_exposure = long_value

        if self.shadow_equity > self.peak_equity:
            self.peak_equity = self.shadow_equity
        if self.peak_equity > 0:
            self.shadow_drawdown = (self.peak_equity - self.shadow_equity) / self.peak_equity

    def _last_price(self, symbol: str) -> float:
        return 0.0

    def snapshot(self) -> dict[str, Any]:
        return {
            "shadow_cash": self.shadow_cash,
            "shadow_positions": dict(self.shadow_positions),
            "shadow_equity": self.shadow_equity,
            "shadow_pnl": self.shadow_pnl,
            "shadow_exposure": self.shadow_exposure,
            "shadow_drawdown": self.shadow_drawdown,
        }


@dataclass
class StateDiff:
    """Difference report between paper / shadow / live-readonly states."""

    run_id: str
    created_at: datetime = field(default_factory=_utc_now)
    paper_positions: dict[str, float] = field(default_factory=dict)
    shadow_positions: dict[str, float] = field(default_factory=dict)
    live_positions: dict[str, float] = field(default_factory=dict)
    diff_paper_shadow: dict[str, float] = field(default_factory=dict)
    diff_shadow_live: dict[str, float] = field(default_factory=dict)
    diff_paper_live: dict[str, float] = field(default_factory=dict)
    paper_equity: float = 0.0
    shadow_equity: float = 0.0
    live_equity: float = 0.0

    def has_critical_diff(self) -> bool:
        return any(abs(v) > 0.01 for v in self.diff_shadow_live.values())

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "created_at": self.created_at.isoformat(),
            "paper_positions": self.paper_positions,
            "shadow_positions": self.shadow_positions,
            "live_positions": self.live_positions,
            "diff_paper_shadow": self.diff_paper_shadow,
            "diff_shadow_live": self.diff_shadow_live,
            "diff_paper_live": self.diff_paper_live,
            "paper_equity": self.paper_equity,
            "shadow_equity": self.shadow_equity,
            "live_equity": self.live_equity,
            "has_critical_diff": self.has_critical_diff(),
        }
