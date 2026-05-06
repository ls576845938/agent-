"""NYSE holiday database.

Covers known NYSE holidays. New Year's, MLK Day, Presidents' Day, Good Friday,
Memorial Day, Juneteenth, Independence Day, Labor Day, Thanksgiving, Christmas.
Includes early-close days (day after Thanksgiving, Christmas Eve when on weekday).
"""

from __future__ import annotations

from datetime import date, timedelta


def _new_years(year: int) -> date:
    d = date(year, 1, 1)
    return _nearest_weekday(d)


def _mlk_day(year: int) -> date:
    return _nth_weekday_of_month(year, 1, 0, 3)


def _presidents_day(year: int) -> date:
    return _nth_weekday_of_month(year, 2, 0, 3)


def _memorial_day(year: int) -> date:
    return _nth_weekday_of_month(year, 5, 0, -1)


def _juneteenth(year: int) -> date | None:
    if year < 2022:
        return None
    return _nearest_weekday(date(year, 6, 19))


def _independence_day(year: int) -> date:
    return _nearest_weekday(date(year, 7, 4))


def _labor_day(year: int) -> date:
    return _nth_weekday_of_month(year, 9, 0, 1)


def _thanksgiving(year: int) -> date:
    return _nth_weekday_of_month(year, 11, 3, 4)


def _christmas(year: int) -> date:
    return _nearest_weekday(date(year, 12, 25))


def _good_friday(year: int) -> date:
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    easter = date(year, month, day)
    return easter - timedelta(days=2)


def _nth_weekday_of_month(year: int, month: int, weekday: int, n: int) -> date:
    """nth occurrence of weekday in month. n=-1 means last."""
    first = date(year, month, 1)
    days_ahead = weekday - first.weekday()
    if days_ahead < 0:
        days_ahead += 7
    candidate = first + timedelta(days=days_ahead)
    if n > 0:
        candidate += timedelta(weeks=n - 1)
    else:
        while (candidate + timedelta(weeks=1)).month == month:
            candidate += timedelta(weeks=1)
    return candidate


def _nearest_weekday(d: date) -> date:
    if d.weekday() == 5:
        return d - timedelta(days=1)
    if d.weekday() == 6:
        return d + timedelta(days=1)
    return d


def nyse_holidays(year: int) -> dict[date, str]:
    """Return all NYSE holidays for a given year with names."""
    holidays: dict[date, str] = {}
    rules = [
        (_new_years, "New Year's Day"),
        (_mlk_day, "Martin Luther King Jr. Day"),
        (_presidents_day, "Presidents' Day"),
        (_good_friday, "Good Friday"),
        (_memorial_day, "Memorial Day"),
        (_juneteenth, "Juneteenth National Independence Day"),
        (_independence_day, "Independence Day"),
        (_labor_day, "Labor Day"),
        (_thanksgiving, "Thanksgiving Day"),
        (_christmas, "Christmas Day"),
    ]
    for rule_fn, name in rules:
        holiday_date = rule_fn(year)
        if holiday_date is not None and holiday_date not in holidays:
            holidays[holiday_date] = name
    return holidays


def nyse_early_closes(year: int) -> dict[date, str]:
    """Return NYSE early-close days (1:00 PM ET close)."""
    early: dict[date, str] = {}
    thanksgiving = _thanksgiving(year)
    black_friday = thanksgiving + timedelta(days=1)
    if black_friday.weekday() < 5:
        early[black_friday] = "Day after Thanksgiving (1:00 PM close)"

    christmas_eve = date(year, 12, 24)
    if christmas_eve.weekday() < 5:
        if christmas_eve not in nyse_holidays(year):
            early[christmas_eve] = "Christmas Eve (1:00 PM close)"

    return early


def is_nyse_trading_day(d: date) -> bool:
    if d.weekday() >= 5:
        return False
    holidays = nyse_holidays(d.year)
    return d not in holidays


def trading_days_between(start: date, end: date) -> int:
    current = start
    count = 0
    while current <= end:
        if is_nyse_trading_day(current):
            count += 1
        current += timedelta(days=1)
    return count
