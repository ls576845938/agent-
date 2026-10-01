from __future__ import annotations

from datetime import date, datetime
from typing import Any, Callable, Mapping, Protocol, Sequence


CalendarRow = Mapping[str, Any]
Clock = Callable[[], datetime]


class TradingCalendarRepository(Protocol):
    def upsert(self, rows: Sequence[CalendarRow]) -> None: ...


class MinuteQualityRepository(Protocol):
    def inspect(
        self,
        *,
        symbols: Sequence[str] | None,
        vendor: str,
        asset_class: str,
        bar_sizes: Sequence[str],
        lookback_trading_days: int,
        as_of: datetime,
        root_subdirs: Sequence[str],
    ) -> Mapping[str, Any]: ...


class PromotionGateRepository(Protocol):
    def evaluate(self, candidate_id: str) -> Any: ...


class USApplicationUnitOfWork(Protocol):
    calendar: TradingCalendarRepository
    minute_quality: MinuteQualityRepository
    promotion_gate: PromotionGateRepository

    def commit(self) -> None: ...

    def rollback(self) -> None: ...


USApplicationUnitOfWorkFactory = Callable[[], USApplicationUnitOfWork]
CalendarFactory = Callable[[tuple[int, ...]], Any]
