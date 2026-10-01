from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from quant_us.application.service import MinuteQualityRequest
from quant_us.compat.application_adapters import build_us_application_service


class USApplicationFacade:
    """US-only HTTP/service facade; app_factory wiring remains integrator-owned."""

    def __init__(self, *, db_connection: Any | None = None) -> None:
        self._db_connection = db_connection

    def populate_trading_calendar(self, start_year: int, end_year: int) -> int:
        service = build_us_application_service(
            db_connection=self._db_connection,
        )
        return service.populate_trading_calendar(start_year, end_year)

    def data_quality_report(self, request: Mapping[str, Any]) -> dict[str, Any]:
        raw_bar_sizes = request.get("bar_sizes")
        if raw_bar_sizes is None:
            raw_bar_sizes = request.get("bar_size")
        service = build_us_application_service(
            data_root=str(request.get("data_root", "data")),
            db_connection=self._db_connection,
        )
        return service.inspect_minute_quality(
            MinuteQualityRequest(
                symbols=_optional_symbols(request),
                vendor=str(request.get("vendor", "yfinance")),
                asset_class=str(request.get("asset_class", "equity")),
                bar_sizes=_string_list(
                    raw_bar_sizes,
                    default=("1m", "5m", "15m", "30m"),
                ),
                lookback_trading_days=int(
                    request.get("lookback_trading_days", 5)
                ),
                as_of=_optional_as_of(request.get("as_of")),
                root_subdirs=_string_list(
                    request.get("root_subdirs"),
                    default=("raw", "cleaned"),
                ),
            )
        )


def _optional_symbols(request: Mapping[str, Any]) -> Sequence[str] | None:
    raw = request.get("symbols")
    if raw is None and request.get("symbol"):
        raw = [request["symbol"]]
    if raw is None:
        return None
    if isinstance(raw, str):
        return tuple(item.strip() for item in raw.split(","))
    return tuple(str(item) for item in raw)


def _string_list(value: Any, *, default: Sequence[str]) -> tuple[str, ...]:
    if value is None:
        return tuple(default)
    if isinstance(value, str):
        return tuple(item.strip() for item in value.split(","))
    return tuple(str(item) for item in value)


def _optional_as_of(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    parsed = (
        value
        if isinstance(value, datetime)
        else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    )
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
