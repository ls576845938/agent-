"""Shared micro-live review-only design freeze metadata."""

from __future__ import annotations

from typing import Any


DESIGN_FREEZE_VERSION = "micro-live-review-only-v1"
DESIGN_FREEZE_SCOPE = "review_only"
DESIGN_FREEZE_MAX_SYMBOLS = 2
DESIGN_FREEZE_MAX_NOTIONAL = 100.0
DESIGN_FREEZE_MAX_ORDERS = 3


def design_freeze_metadata() -> dict[str, Any]:
    return {
        "version": DESIGN_FREEZE_VERSION,
        "frozen": True,
        "scope": DESIGN_FREEZE_SCOPE,
        "no_continuous_loop": True,
        "manual_approval_required": True,
        "max_symbols": DESIGN_FREEZE_MAX_SYMBOLS,
        "max_notional": DESIGN_FREEZE_MAX_NOTIONAL,
        "max_orders": DESIGN_FREEZE_MAX_ORDERS,
    }
