"""Live runner boundaries."""
from __future__ import annotations

# These modules have a circular dependency (shadow_live imports from
# live_state_store), so __init__ uses lazy imports via __getattr__.
# Import directly from submodules in your code:
#   from quant_us.live.live_state_store import LiveStateStore
#   from quant_us.live.shadow_live import ShadowLiveRunner


def __getattr__(name: str):
    _exports = {
        "DayResult": "quant_us.live.live_state_store",
        "LiveSessionRunner": "quant_us.live.live_state_store",
        "LiveSessionState": "quant_us.live.live_state_store",
        "LiveStateStore": "quant_us.live.live_state_store",
        "ShadowLiveConfig": "quant_us.live.shadow_live",
        "ShadowLiveGate": "quant_us.live.shadow_live",
        "ShadowLiveGateReport": "quant_us.live.shadow_live",
        "ShadowLiveRunner": "quant_us.live.shadow_live",
    }
    if name in _exports:
        import importlib
        mod = importlib.import_module(_exports[name])
        return getattr(mod, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "DayResult",
    "LiveSessionRunner",
    "LiveSessionState",
    "LiveStateStore",
    "ShadowLiveConfig",
    "ShadowLiveGate",
    "ShadowLiveGateReport",
    "ShadowLiveRunner",
]
