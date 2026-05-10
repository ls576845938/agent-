"""Shared micro-live review-only design freeze metadata."""

from __future__ import annotations

import hashlib
import json
from typing import Any


DESIGN_FREEZE_VERSION = "micro-live-review-only-v1"
DESIGN_FREEZE_SCOPE = "review_only"
DESIGN_FREEZE_MAX_SYMBOLS = 2
DESIGN_FREEZE_MAX_NOTIONAL = 100.0
DESIGN_FREEZE_MAX_ORDERS = 3


def _design_freeze_payload() -> dict[str, Any]:
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


def design_freeze_hash(metadata: dict[str, Any] | None = None) -> str:
    payload = metadata or _design_freeze_payload()
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def design_freeze_metadata() -> dict[str, Any]:
    payload = _design_freeze_payload()
    payload["hash"] = design_freeze_hash(payload)
    return payload
