from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any, Mapping, Sequence

from quant_us.application.ports import (
    CalendarFactory,
    Clock,
    USApplicationUnitOfWorkFactory,
)


SUPPORTED_MINUTE_BAR_SIZES = ("1m", "5m", "15m", "30m")
SUPPORTED_MINUTE_ROOT_SUBDIRS = ("raw", "cleaned")


@dataclass(frozen=True)
class MinuteQualityRequest:
    symbols: Sequence[str] | None = None
    vendor: str = "yfinance"
    asset_class: str = "equity"
    bar_sizes: Sequence[str] = SUPPORTED_MINUTE_BAR_SIZES
    lookback_trading_days: int = 5
    as_of: datetime | None = None
    root_subdirs: Sequence[str] = SUPPORTED_MINUTE_ROOT_SUBDIRS


class USApplicationService:
    """US use-case orchestration with no filesystem, HTTP, SDK, or env access."""

    def __init__(
        self,
        *,
        uow_factory: USApplicationUnitOfWorkFactory,
        calendar_factory: CalendarFactory,
        clock: Clock,
    ) -> None:
        self._uow_factory = uow_factory
        self._calendar_factory = calendar_factory
        self._clock = clock

    def populate_trading_calendar(self, start_year: int, end_year: int) -> int:
        if start_year > end_year:
            raise ValueError("start_year must be less than or equal to end_year")
        years = tuple(range(int(start_year), int(end_year) + 1))
        calendar = self._calendar_factory(years)
        rows = _calendar_rows(calendar, start_year=int(start_year), end_year=int(end_year))
        uow = self._uow_factory()
        try:
            uow.calendar.upsert(rows)
            uow.commit()
        except Exception:
            uow.rollback()
            raise
        return len(rows)

    def inspect_minute_quality(
        self,
        request: MinuteQualityRequest,
    ) -> dict[str, Any]:
        symbols = _normalize_symbols(request.symbols)
        bar_sizes = _normalize_bar_sizes(request.bar_sizes)
        root_subdirs = _normalize_root_subdirs(request.root_subdirs)
        lookback = max(1, int(request.lookback_trading_days))
        as_of = request.as_of or self._clock()
        uow = self._uow_factory()
        try:
            payload = uow.minute_quality.inspect(
                symbols=symbols,
                vendor=str(request.vendor),
                asset_class=str(request.asset_class),
                bar_sizes=bar_sizes,
                lookback_trading_days=lookback,
                as_of=as_of,
                root_subdirs=root_subdirs,
            )
            uow.commit()
        except Exception:
            uow.rollback()
            raise
        return dict(payload)

    def evaluate_promotion_gate(self, candidate_id: str) -> Any:
        normalized = str(candidate_id).strip()
        if not normalized:
            raise ValueError("candidate_id is required")
        uow = self._uow_factory()
        try:
            result = uow.promotion_gate.evaluate(normalized)
            uow.commit()
        except Exception:
            uow.rollback()
            raise
        return result


def _calendar_rows(
    calendar: Any,
    *,
    start_year: int,
    end_year: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    current = date(start_year, 1, 1)
    end = date(end_year, 12, 31)
    while current <= end:
        holiday_name = calendar.holidays.get(current)
        is_trading_day = calendar.is_trading_day(current)
        is_early_close = is_trading_day and calendar.is_early_close(current)
        if not is_trading_day:
            session_hours = "00:00-00:00"
            early_close_time = None
        elif is_early_close:
            session_hours = "09:30-13:00"
            early_close_time = time(13, 0)
        else:
            session_hours = "09:30-16:00"
            early_close_time = None
        notes = holiday_name if not is_trading_day and holiday_name else (
            "Early close" if is_early_close else ""
        )
        rows.append(
            {
                "date": current,
                "is_trading_day": is_trading_day,
                "session_hours": session_hours,
                "early_close_time": early_close_time,
                "holiday_name": holiday_name,
                "notes": notes,
            }
        )
        current += timedelta(days=1)
    return rows


def _normalize_symbols(values: Sequence[str] | None) -> list[str] | None:
    if values is None:
        return None
    symbols: list[str] = []
    seen: set[str] = set()
    for item in values:
        symbol = str(item).strip().upper()
        if symbol and symbol not in seen:
            symbols.append(symbol)
            seen.add(symbol)
    return symbols or None


def _normalize_bar_sizes(values: Sequence[str]) -> list[str]:
    bar_sizes: list[str] = []
    invalid: set[str] = set()
    for item in values:
        bar_size = str(item or "").strip().lower()
        if not bar_size:
            continue
        if bar_size not in SUPPORTED_MINUTE_BAR_SIZES:
            invalid.add(bar_size)
        elif bar_size not in bar_sizes:
            bar_sizes.append(bar_size)
    if invalid:
        raise ValueError(
            f"Unsupported minute bar sizes: {sorted(invalid)}. "
            f"Allowed values: {list(SUPPORTED_MINUTE_BAR_SIZES)}"
        )
    if not bar_sizes:
        raise ValueError(
            "At least one minute bar size is required. "
            f"Allowed values: {list(SUPPORTED_MINUTE_BAR_SIZES)}"
        )
    return bar_sizes


def _normalize_root_subdirs(values: Sequence[str]) -> list[str]:
    roots: list[str] = []
    invalid: set[str] = set()
    for item in values:
        root = str(item or "").strip().lower()
        if not root:
            continue
        if root not in SUPPORTED_MINUTE_ROOT_SUBDIRS:
            invalid.add(root)
        elif root not in roots:
            roots.append(root)
    if invalid:
        raise ValueError(
            f"Unsupported root_subdirs: {sorted(invalid)}. "
            f"Allowed values: {list(SUPPORTED_MINUTE_ROOT_SUBDIRS)}"
        )
    if not roots:
        raise ValueError(
            "At least one root_subdir is required. "
            f"Allowed values: {list(SUPPORTED_MINUTE_ROOT_SUBDIRS)}"
        )
    return roots
