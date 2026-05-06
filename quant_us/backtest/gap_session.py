"""Gap, halt, and session-aware order execution for backtest integrity.

Handles:
- Opening gaps (close[t-1] vs open[t])
- Trading halts and circuit breakers
- Zero-volume bars (no execution possible)
- Pre-market / regular / after-hours session enforcement
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import time

from quant_us.core.enums import OrderSide, OrderStatus, SessionName
from quant_us.core.types import Bar, Order


@dataclass
class GapConfig:
    max_gap_pct: float = 20.0
    reject_on_extreme_gap: bool = True
    limit_fill_on_gap: bool = True
    gap_fill_ratio: float = 0.5


@dataclass
class SessionConfig:
    regular_open: time = time(9, 30)
    regular_close: time = time(16, 0)
    allow_pre_market: bool = False
    allow_after_hours: bool = False
    only_regular_session: bool = True


@dataclass
class OrderDelayConfig:
    delay_bars: int = 0
    delay_seconds: float = 0.0


def classify_session(bar: Bar, config: SessionConfig | None = None) -> SessionName:
    """Classify which trading session a bar belongs to."""
    cfg = config or SessionConfig()
    t = bar.timestamp_utc.time() if bar.timestamp_utc.tzinfo else bar.timestamp_utc.time()
    if t < cfg.regular_open:
        return SessionName.PRE_MARKET
    if t > cfg.regular_close:
        return SessionName.AFTER_HOURS
    return SessionName.REGULAR


def detect_gap(prev_close: float, bar: Bar, config: GapConfig | None = None) -> float:
    """Detect the opening gap from previous close to current bar open.

    Returns the gap in percentage. Positive = gap up, negative = gap down.
    """
    if prev_close <= 0 or bar.open <= 0:
        return 0.0
    return (bar.open / prev_close - 1.0) * 100.0


def is_extreme_gap(gap_pct: float, config: GapConfig | None = None) -> bool:
    cfg = config or GapConfig()
    return abs(gap_pct) > cfg.max_gap_pct


def gap_adjusted_fill_price(
    order: Order,
    bar: Bar,
    prev_close: float,
    config: GapConfig | None = None,
) -> float | None:
    """Return the gap-adjusted fill price, or None if the order should be rejected.

    On extreme gaps, orders may be rejected or filled at a worse price.
    """
    cfg = config or GapConfig()
    gap = detect_gap(prev_close, bar, cfg)

    if cfg.reject_on_extreme_gap and is_extreme_gap(gap, cfg):
        return None

    if cfg.limit_fill_on_gap and abs(gap) > cfg.max_gap_pct * 0.5:
        base = bar.open
        if order.side == OrderSide.BUY:
            return base * (1.0 + abs(gap) / 100.0 * cfg.gap_fill_ratio)
        else:
            return base * (1.0 - abs(gap) / 100.0 * cfg.gap_fill_ratio)

    return bar.open if bar.open > 0 else bar.close


def is_bar_tradable(bar: Bar) -> tuple[bool, str]:
    """Check if a bar represents a tradable period.

    Returns (tradable, reason) where reason explains why not.
    """
    if bar.volume <= 0:
        return False, "zero_volume"
    if bar.high <= 0 or bar.low <= 0 or bar.close <= 0:
        return False, "non_positive_price"
    if bar.high == bar.low:
        return False, "no_price_movement"
    return True, "tradable"


def apply_order_delay(
    order: Order,
    bar_index: int,
    config: OrderDelayConfig | None = None,
) -> Order | None:
    """Apply order delay. Returns None if order should be skipped at this bar."""
    cfg = config or OrderDelayConfig()
    if cfg.delay_bars > bar_index % (cfg.delay_bars + 1):
        return None
    return order
