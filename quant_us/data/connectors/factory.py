"""Vendor registry and connector factory.

Usage
-----
>>> from quant_us.data.connectors.factory import get_connector, available_vendors
>>> conn = get_connector("yfinance")
>>> print(conn.vendor)
'yfinance'

>>> get_connector("unknown")
ValueError: Unknown data vendor: 'unknown'. Available: ['alpaca', 'yfinance']
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from quant_us.data.connectors.base import MarketDataConnector

# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------
DATA_VENDOR_REGISTRY: dict[str, type[MarketDataConnector]] = {}


def register(vendor: str) -> type[MarketDataConnector]:
    """Decorator to register a connector class under *vendor* name."""

    def _wrap(cls: type[MarketDataConnector]) -> type[MarketDataConnector]:
        DATA_VENDOR_REGISTRY[vendor] = cls
        return cls

    return _wrap


def get_connector(vendor: str, **kwargs) -> MarketDataConnector:
    """Return an instantiated connector for the given vendor.

    Parameters
    ----------
    vendor : str
        One of the keys in :data:`DATA_VENDOR_REGISTRY`.
    **kwargs
        Forwarded to the connector constructor.

    Returns
    -------
    MarketDataConnector
    """
    cls = DATA_VENDOR_REGISTRY.get(vendor)
    if cls is None:
        raise ValueError(
            f"Unknown data vendor: {vendor!r}. "
            f"Available: {sorted(DATA_VENDOR_REGISTRY)}"
        )
    return cls(**kwargs)


def available_vendors() -> list[str]:
    """Return sorted list of registered vendor names."""
    return sorted(DATA_VENDOR_REGISTRY)


# ---------------------------------------------------------------------------
# Auto-register connectors shipped with the codebase
# ---------------------------------------------------------------------------
# Lazy imports to avoid hard dependencies at import time.
from quant_us.data.connectors.yfinance_data import YFinanceDataConnector  # noqa: E402
from quant_us.data.connectors.alpaca_data import AlpacaDataConnector  # noqa: E402

DATA_VENDOR_REGISTRY["yfinance"] = YFinanceDataConnector
DATA_VENDOR_REGISTRY["alpaca"] = AlpacaDataConnector
