from __future__ import annotations

from dataclasses import dataclass

from quant_us.core.types import Position


@dataclass(frozen=True)
class ReconciliationBreak:
    symbol: str
    local_quantity: float
    broker_quantity: float
    local_market_value: float = 0.0
    broker_market_value: float = 0.0


@dataclass(frozen=True)
class ReconciliationReport:
    status: str
    break_count: int
    breaks: list[ReconciliationBreak]

    @property
    def is_clean(self) -> bool:
        return self.break_count == 0


class StateReconciler:
    def compare_positions(
        self,
        local_positions: dict[str, Position],
        broker_positions: dict[str, Position],
        tolerance: float = 1e-6,
    ) -> list[ReconciliationBreak]:
        symbols = set(local_positions) | set(broker_positions)
        breaks: list[ReconciliationBreak] = []
        for symbol in symbols:
            local_quantity = local_positions.get(symbol, Position(symbol)).quantity
            broker_quantity = broker_positions.get(symbol, Position(symbol)).quantity
            if abs(local_quantity - broker_quantity) > tolerance:
                local_position = local_positions.get(symbol, Position(symbol))
                broker_position = broker_positions.get(symbol, Position(symbol))
                breaks.append(
                    ReconciliationBreak(
                        symbol=symbol,
                        local_quantity=local_quantity,
                        broker_quantity=broker_quantity,
                        local_market_value=local_position.market_value,
                        broker_market_value=broker_position.market_value,
                    )
                )
        return breaks

    def report(
        self,
        local_positions: dict[str, Position],
        broker_positions: dict[str, Position],
        tolerance: float = 1e-6,
    ) -> ReconciliationReport:
        breaks = self.compare_positions(local_positions, broker_positions, tolerance=tolerance)
        return ReconciliationReport(status="clean" if not breaks else "breaks_detected", break_count=len(breaks), breaks=breaks)
