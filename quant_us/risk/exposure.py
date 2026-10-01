from __future__ import annotations

from quant_us.core.types import Position


def gross_exposure(positions: dict[str, Position]) -> float:
    return sum(abs(position.market_value) for position in positions.values())


def net_exposure(positions: dict[str, Position]) -> float:
    return sum(position.market_value for position in positions.values())
