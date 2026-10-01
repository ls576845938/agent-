from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from quant_shared.core import ensure_utc, utc_now

UTC = timezone.utc
ET = ZoneInfo("America/New_York")


def to_et(value: datetime) -> datetime:
    return ensure_utc(value).astimezone(ET)


def to_utc(value: datetime) -> datetime:
    return ensure_utc(value)


def trading_date_et(value: datetime) -> date:
    return to_et(value).date()
