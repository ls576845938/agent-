from __future__ import annotations

from dataclasses import dataclass

from backend.app.core.exceptions import DependencyUnavailableError


@dataclass(frozen=True)
class LiveTradingConfig:
    gateway_name: str = "BINANCE_USDT"
    symbol: str = "BTCUSDT"
    exchange_suffix: str = "GLOBAL"
    total_leverage: float = 1.0
    max_exposure_ratio: float = 0.8
    order_timeout_seconds: int = 10


def detect_live_dependencies() -> dict[str, bool]:
    import importlib.util

    packages = {
        "vnpy": "vnpy",
        "vnpy_ctastrategy": "vnpy_ctastrategy",
        "vnpy_binance": "vnpy_binance",
    }
    return {name: bool(importlib.util.find_spec(module_name)) for name, module_name in packages.items()}


class OptionalVnpyAdapter:
    """
    Thin compatibility wrapper for the future live trading phase.

    The research system stays fully functional without vn.py. When the live
    dependencies are installed, this adapter can become the migration point for
    the old daemon/bootstrap logic and the net-position executor.
    """

    def __init__(self, config: LiveTradingConfig | None = None) -> None:
        self.config = config or LiveTradingConfig()
        self.dependencies = detect_live_dependencies()

    @property
    def available(self) -> bool:
        return all(self.dependencies.values())

    def bootstrap(self) -> None:
        if not self.available:
            missing = [name for name, available in self.dependencies.items() if not available]
            raise DependencyUnavailableError(
                "Live trading dependencies are unavailable. Missing packages: "
                + ", ".join(missing)
            )

    def describe(self) -> dict[str, object]:
        return {
            "available": self.available,
            "dependencies": self.dependencies,
            "config": self.config.__dict__,
        }
