from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

UTC = timezone.utc
ET = ZoneInfo("America/New_York")


def utc_now() -> datetime:
    return datetime.now(tz=UTC)


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def to_et(value: datetime) -> datetime:
    return ensure_utc(value).astimezone(ET)


def to_utc(value: datetime) -> datetime:
    return ensure_utc(value)


def trading_date_et(value: datetime) -> date:
    return to_et(value).date()
