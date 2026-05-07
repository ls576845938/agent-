from __future__ import annotations

from enum import Enum

from quant_us.core.enums import TradingMode


class RuntimeMode(str, Enum):
    """Explicit runtime modes for paper, shadow-live, and guarded live."""

    PAPER = "paper"
    SHADOW_LIVE = "shadow_live"
    LIVE = "live"

    @classmethod
    def from_trading_mode(cls, mode: TradingMode) -> "RuntimeMode":
        if mode == TradingMode.LIVE:
            return cls.LIVE
        if mode == TradingMode.PAPER:
            return cls.PAPER
        raise ValueError(f"TradingMode {mode.value!r} is not a live runtime mode")

    @property
    def can_submit_real_orders(self) -> bool:
        return self == RuntimeMode.LIVE

    @property
    def is_shadow(self) -> bool:
        return self == RuntimeMode.SHADOW_LIVE
