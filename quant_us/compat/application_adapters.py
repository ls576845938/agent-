"""Adapters from US application ports to current legacy implementations."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from quant_us.application.service import USApplicationService
from quant_us.core.calendar import USEquityCalendar
from quant_us.core.clock import utc_now


CALENDAR_UPSERT_SQL = """
    INSERT INTO quant.trading_calendar
        (date, is_trading_day, session_hours, early_close_time, holiday_name, notes)
    VALUES
        (%(date)s, %(is_trading_day)s, %(session_hours)s, %(early_close_time)s, %(holiday_name)s, %(notes)s)
    ON CONFLICT (date) DO UPDATE SET
        is_trading_day = EXCLUDED.is_trading_day,
        session_hours = EXCLUDED.session_hours,
        early_close_time = EXCLUDED.early_close_time,
        holiday_name = EXCLUDED.holiday_name,
        notes = EXCLUDED.notes
"""


class DatabaseTradingCalendarRepository:
    def __init__(self, connection: Any | None, *, mark_dirty) -> None:
        self._connection = connection
        self._mark_dirty = mark_dirty

    def upsert(self, rows: Sequence[Mapping[str, Any]]) -> None:
        if self._connection is None:
            raise RuntimeError(
                "Database connection required. Provide db_connection to USQuantService."
            )
        self._mark_dirty()
        with self._connection.cursor() as cursor:
            cursor.executemany(CALENDAR_UPSERT_SQL, list(rows))


class LegacyMinuteQualityRepository:
    def __init__(self, data_root: str | Path) -> None:
        self._data_root = Path(data_root)

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
    ) -> Mapping[str, Any]:
        from quant_us.data.minute_quality_gate import (
            inspect_minute_data_quality_overview,
        )

        report = inspect_minute_data_quality_overview(
            data_root=self._data_root,
            symbols=list(symbols) if symbols is not None else None,
            vendor=vendor,
            asset_class=asset_class,
            bar_sizes=list(bar_sizes),
            lookback_trading_days=lookback_trading_days,
            as_of=as_of,
            root_subdirs=list(root_subdirs),
        )
        return report.to_dict()


class LegacyPromotionGateRepository:
    def __init__(self, data_root: str | Path) -> None:
        self._data_root = str(data_root)

    def evaluate(self, candidate_id: str) -> Any:
        from quant_us.research.automation.promotion_gate import (
            ResearchPromotionGate,
        )

        return ResearchPromotionGate(data_root=self._data_root).evaluate(candidate_id)


class LegacyUSApplicationUnitOfWork:
    def __init__(
        self,
        *,
        data_root: str | Path,
        db_connection: Any | None,
    ) -> None:
        self._db_connection = db_connection
        self._dirty = False
        self.calendar = DatabaseTradingCalendarRepository(
            db_connection,
            mark_dirty=self._mark_dirty,
        )
        self.minute_quality = LegacyMinuteQualityRepository(data_root)
        self.promotion_gate = LegacyPromotionGateRepository(data_root)

    def _mark_dirty(self) -> None:
        self._dirty = True

    def commit(self) -> None:
        if self._dirty and self._db_connection is not None:
            self._db_connection.commit()

    def rollback(self) -> None:
        rollback = (
            getattr(self._db_connection, "rollback", None)
            if self._dirty and self._db_connection is not None
            else None
        )
        if callable(rollback):
            rollback()


def build_us_application_service(
    *,
    data_root: str | Path = "data",
    db_connection: Any | None = None,
    clock=utc_now,
) -> USApplicationService:
    return USApplicationService(
        uow_factory=lambda: LegacyUSApplicationUnitOfWork(
            data_root=data_root,
            db_connection=db_connection,
        ),
        calendar_factory=lambda years: USEquityCalendar.with_holidays(years=years),
        clock=clock,
    )
