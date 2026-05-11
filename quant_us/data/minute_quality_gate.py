from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from quant_us.core.calendar import USEquityCalendar
from quant_us.core.clock import ET, UTC, ensure_utc, to_et, utc_now

SUPPORTED_MINUTE_BAR_SIZES: tuple[str, ...] = ("1m", "5m", "15m")
_STATUS_RANK = {"PASS": 0, "DEGRADED": 1, "STALE": 2, "MISSING": 3, "INVALID": 4}
_PRICE_COLUMNS = ("open", "high", "low", "close")


@dataclass(frozen=True)
class MinuteBarQualitySnapshot:
    symbol: str
    bar_size: str
    status: str
    expected_trading_days: list[str]
    observed_file_dates: list[str]
    missing_file_dates: list[str]
    expected_bars: int
    observed_bars: int
    missing_bar_count: int
    coverage_pct: float
    latest_timestamp_utc: str = ""
    expected_latest_timestamp_utc: str = ""
    freshness_lag_minutes: float = 0.0
    missing_bar_samples_utc: list[str] = field(default_factory=list)
    evidence_paths: list[str] = field(default_factory=list)
    duplicate_timestamp_count: int = 0
    conflicting_duplicate_count: int = 0
    invalid_ohlc_count: int = 0
    non_positive_price_count: int = 0
    negative_volume_count: int = 0
    malformed_file_count: int = 0
    file_errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "bar_size": self.bar_size,
            "status": self.status,
            "expected_trading_days": list(self.expected_trading_days),
            "observed_file_dates": list(self.observed_file_dates),
            "missing_file_dates": list(self.missing_file_dates),
            "expected_bars": self.expected_bars,
            "observed_bars": self.observed_bars,
            "missing_bar_count": self.missing_bar_count,
            "coverage_pct": self.coverage_pct,
            "latest_timestamp_utc": self.latest_timestamp_utc,
            "expected_latest_timestamp_utc": self.expected_latest_timestamp_utc,
            "freshness_lag_minutes": self.freshness_lag_minutes,
            "missing_bar_samples_utc": list(self.missing_bar_samples_utc),
            "evidence_paths": list(self.evidence_paths),
            "duplicate_timestamp_count": self.duplicate_timestamp_count,
            "conflicting_duplicate_count": self.conflicting_duplicate_count,
            "invalid_ohlc_count": self.invalid_ohlc_count,
            "non_positive_price_count": self.non_positive_price_count,
            "negative_volume_count": self.negative_volume_count,
            "malformed_file_count": self.malformed_file_count,
            "file_errors": list(self.file_errors),
        }


@dataclass(frozen=True)
class MinuteSymbolQualitySummary:
    symbol: str
    status: str
    intervals: list[MinuteBarQualitySnapshot]

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "status": self.status,
            "intervals": [interval.to_dict() for interval in self.intervals],
        }


@dataclass(frozen=True)
class MinuteDataQualityReport:
    status: str
    as_of_utc: str
    data_root: str
    dataset_root: str
    vendor: str
    asset_class: str
    lookback_trading_days: int
    bar_sizes: list[str]
    evaluated_symbols: list[str]
    symbols: list[MinuteSymbolQualitySummary]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "as_of_utc": self.as_of_utc,
            "data_root": self.data_root,
            "dataset_root": self.dataset_root,
            "vendor": self.vendor,
            "asset_class": self.asset_class,
            "lookback_trading_days": self.lookback_trading_days,
            "bar_sizes": list(self.bar_sizes),
            "evaluated_symbols": list(self.evaluated_symbols),
            "symbols": [symbol.to_dict() for symbol in self.symbols],
        }

    @property
    def issue_count(self) -> int:
        return sum(
            1
            for symbol in self.symbols
            for interval in symbol.intervals
            if interval.status != "PASS"
        )


def inspect_minute_data_quality(
    data_root: str | Path = "data",
    *,
    symbols: list[str] | None = None,
    vendor: str = "yfinance",
    asset_class: str = "equity",
    bar_sizes: list[str] | tuple[str, ...] = SUPPORTED_MINUTE_BAR_SIZES,
    lookback_trading_days: int = 5,
    as_of: datetime | None = None,
    root_subdir: str = "raw",
    min_coverage_pct: float = 99.0,
    max_missing_samples: int = 8,
) -> MinuteDataQualityReport:
    root = Path(data_root)
    normalized_bar_sizes = _normalize_bar_sizes(bar_sizes)
    as_of_utc = ensure_utc(as_of or utc_now())
    calendar = USEquityCalendar.with_holidays()
    dataset_root = root / root_subdir / f"vendor={vendor}" / f"asset_class={asset_class}"
    resolved_symbols = _resolve_symbols(dataset_root, normalized_bar_sizes, symbols)

    symbol_summaries: list[MinuteSymbolQualitySummary] = []
    overall_status = "PASS"
    for symbol in resolved_symbols:
        intervals = [
            _inspect_symbol_interval(
                dataset_root=dataset_root,
                symbol=symbol,
                bar_size=bar_size,
                as_of_utc=as_of_utc,
                lookback_trading_days=lookback_trading_days,
                calendar=calendar,
                min_coverage_pct=min_coverage_pct,
                max_missing_samples=max_missing_samples,
            )
            for bar_size in normalized_bar_sizes
        ]
        symbol_status = _worst_status(interval.status for interval in intervals)
        overall_status = _worst_status((overall_status, symbol_status))
        symbol_summaries.append(
            MinuteSymbolQualitySummary(
                symbol=symbol,
                status=symbol_status,
                intervals=intervals,
            )
        )

    return MinuteDataQualityReport(
        status=overall_status if symbol_summaries else "MISSING",
        as_of_utc=as_of_utc.isoformat(),
        data_root=str(root),
        dataset_root=str(dataset_root),
        vendor=vendor,
        asset_class=asset_class,
        lookback_trading_days=lookback_trading_days,
        bar_sizes=list(normalized_bar_sizes),
        evaluated_symbols=list(resolved_symbols),
        symbols=symbol_summaries,
    )


def _inspect_symbol_interval(
    *,
    dataset_root: Path,
    symbol: str,
    bar_size: str,
    as_of_utc: datetime,
    lookback_trading_days: int,
    calendar: USEquityCalendar,
    min_coverage_pct: float,
    max_missing_samples: int,
) -> MinuteBarQualitySnapshot:
    interval_minutes = int(bar_size.removesuffix("m"))
    base = dataset_root / f"bar_size={bar_size}" / f"symbol={symbol.upper()}"
    coverage_end = _latest_completed_trading_day(as_of_utc, calendar)
    expected_days = _recent_trading_days(coverage_end, lookback_trading_days, calendar)
    expected_dates = [day.isoformat() for day in expected_days]

    if not base.exists():
        expected_latest = _expected_latest_timestamp(as_of_utc, interval_minutes, calendar)
        return MinuteBarQualitySnapshot(
            symbol=symbol.upper(),
            bar_size=bar_size,
            status="MISSING",
            expected_trading_days=expected_dates,
            observed_file_dates=[],
            missing_file_dates=expected_dates,
            expected_bars=sum(len(_expected_regular_timestamps(day, interval_minutes, calendar)) for day in expected_days),
            observed_bars=0,
            missing_bar_count=sum(len(_expected_regular_timestamps(day, interval_minutes, calendar)) for day in expected_days),
            coverage_pct=0.0,
            expected_latest_timestamp_utc=expected_latest.isoformat() if expected_latest else "",
            freshness_lag_minutes=0.0,
        )

    expected_ts_by_day = {
        day.isoformat(): _expected_regular_timestamps(day, interval_minutes, calendar)
        for day in expected_days
    }
    expected_ts = {
        timestamp
        for timestamps in expected_ts_by_day.values()
        for timestamp in timestamps
    }
    observed_ts: set[datetime] = set()
    evidence_paths: list[str] = []
    observed_dates: list[str] = []
    missing_file_dates: list[str] = []
    duplicate_timestamp_count = 0
    conflicting_duplicate_count = 0
    invalid_ohlc_count = 0
    non_positive_price_count = 0
    negative_volume_count = 0
    malformed_file_count = 0
    file_errors: list[str] = []

    for day in expected_days:
        date_str = day.isoformat()
        path = base / f"date={date_str}.parquet"
        if not path.exists():
            missing_file_dates.append(date_str)
            continue
        evidence_paths.append(str(path))
        observed_dates.append(date_str)
        try:
            frame = pd.read_parquet(path)
        except Exception as exc:
            malformed_file_count += 1
            file_errors.append(f"{path}:read_failed:{exc}")
            continue
        quality = _regular_frame_quality(frame, expected_ts_by_day[date_str], path)
        duplicate_timestamp_count += quality["duplicate_timestamp_count"]
        conflicting_duplicate_count += quality["conflicting_duplicate_count"]
        invalid_ohlc_count += quality["invalid_ohlc_count"]
        non_positive_price_count += quality["non_positive_price_count"]
        negative_volume_count += quality["negative_volume_count"]
        malformed_file_count += quality["malformed_file_count"]
        file_errors.extend(quality["file_errors"])
        for timestamp in quality["timestamps"]:
            observed_ts.add(timestamp)

    missing_timestamps = sorted(expected_ts - observed_ts)
    expected_latest = _expected_latest_timestamp(as_of_utc, interval_minutes, calendar)
    latest_observed = max(observed_ts) if observed_ts else None
    freshness_lag = _freshness_lag_minutes(expected_latest, latest_observed)
    coverage_pct = round((len(observed_ts) / max(1, len(expected_ts))) * 100.0, 4)

    status = "PASS"
    has_invalid_rows = (
        malformed_file_count > 0
        or conflicting_duplicate_count > 0
        or invalid_ohlc_count > 0
        or non_positive_price_count > 0
        or negative_volume_count > 0
    )
    if has_invalid_rows:
        status = "INVALID"
    elif not observed_ts:
        status = "MISSING"
    elif freshness_lag > float(interval_minutes):
        status = "STALE"
    elif (
        coverage_pct < min_coverage_pct
        or missing_file_dates
        or missing_timestamps
        or duplicate_timestamp_count > 0
    ):
        status = "DEGRADED"

    return MinuteBarQualitySnapshot(
        symbol=symbol.upper(),
        bar_size=bar_size,
        status=status,
        expected_trading_days=expected_dates,
        observed_file_dates=observed_dates,
        missing_file_dates=missing_file_dates,
        expected_bars=len(expected_ts),
        observed_bars=len(observed_ts),
        missing_bar_count=len(missing_timestamps),
        coverage_pct=coverage_pct,
        latest_timestamp_utc=latest_observed.isoformat() if latest_observed else "",
        expected_latest_timestamp_utc=expected_latest.isoformat() if expected_latest else "",
        freshness_lag_minutes=freshness_lag,
        missing_bar_samples_utc=[
            timestamp.isoformat() for timestamp in missing_timestamps[:max_missing_samples]
        ],
        evidence_paths=evidence_paths,
        duplicate_timestamp_count=duplicate_timestamp_count,
        conflicting_duplicate_count=conflicting_duplicate_count,
        invalid_ohlc_count=invalid_ohlc_count,
        non_positive_price_count=non_positive_price_count,
        negative_volume_count=negative_volume_count,
        malformed_file_count=malformed_file_count,
        file_errors=file_errors[:max_missing_samples],
    )


def _regular_timestamps_from_frame(
    frame: pd.DataFrame,
    expected_timestamps: list[datetime],
) -> set[datetime]:
    return set(_regular_frame_quality(frame, expected_timestamps, Path(""))["timestamps"])


def _regular_frame_quality(
    frame: pd.DataFrame,
    expected_timestamps: list[datetime],
    path: Path,
) -> dict[str, Any]:
    empty = {
        "timestamps": set(),
        "duplicate_timestamp_count": 0,
        "conflicting_duplicate_count": 0,
        "invalid_ohlc_count": 0,
        "non_positive_price_count": 0,
        "negative_volume_count": 0,
        "malformed_file_count": 0,
        "file_errors": [],
    }
    if frame.empty:
        return empty
    ts_col = "timestamp_utc" if "timestamp_utc" in frame.columns else "timestamp"
    if ts_col not in frame.columns:
        return {
            **empty,
            "malformed_file_count": 1,
            "file_errors": [f"{path}:missing_timestamp_column"],
        }
    missing_prices = [column for column in _PRICE_COLUMNS if column not in frame.columns]
    if missing_prices:
        return {
            **empty,
            "malformed_file_count": 1,
            "file_errors": [f"{path}:missing_price_columns:{','.join(missing_prices)}"],
        }

    timestamps = pd.to_datetime(frame[ts_col], utc=True, errors="coerce")
    expected_set = set(expected_timestamps)
    normalized = timestamps.map(
        lambda ts: ts.to_pydatetime().astimezone(UTC) if pd.notna(ts) else None
    )
    regular = frame.copy()
    regular["_timestamp_utc_norm"] = normalized
    regular = regular[regular["_timestamp_utc_norm"].isin(expected_set)].copy()
    if regular.empty:
        return empty

    duplicate_mask = regular.duplicated("_timestamp_utc_norm", keep=False)
    duplicate_timestamp_count = int(duplicate_mask.sum())
    conflicting_duplicate_count = 0
    if duplicate_timestamp_count:
        for _, group in regular[duplicate_mask].groupby("_timestamp_utc_norm", dropna=True):
            if len(group[list(_PRICE_COLUMNS)].drop_duplicates()) > 1:
                conflicting_duplicate_count += 1

    price_frame = regular.loc[:, _PRICE_COLUMNS].apply(pd.to_numeric, errors="coerce")
    non_positive_mask = price_frame.le(0).any(axis=1) | price_frame.isna().any(axis=1)
    invalid_ohlc_mask = (
        non_positive_mask
        | (price_frame["high"] < price_frame["low"])
        | (price_frame["high"] < price_frame[["open", "close"]].max(axis=1))
        | (price_frame["low"] > price_frame[["open", "close"]].min(axis=1))
    )
    negative_volume_count = 0
    if "volume" in regular.columns:
        volume = pd.to_numeric(regular["volume"], errors="coerce")
        negative_volume_count = int(volume.lt(0).sum())

    return {
        "timestamps": set(regular["_timestamp_utc_norm"].dropna().drop_duplicates()),
        "duplicate_timestamp_count": duplicate_timestamp_count,
        "conflicting_duplicate_count": conflicting_duplicate_count,
        "invalid_ohlc_count": int(invalid_ohlc_mask.sum()),
        "non_positive_price_count": int(non_positive_mask.sum()),
        "negative_volume_count": negative_volume_count,
        "malformed_file_count": 0,
        "file_errors": [],
    }


def _expected_regular_timestamps(
    trading_day: date,
    interval_minutes: int,
    calendar: USEquityCalendar,
) -> list[datetime]:
    open_et = datetime.combine(trading_day, time(9, 30), tzinfo=ET)
    close_time = calendar.early_close_time if calendar.is_early_close(trading_day) else time(16, 0)
    close_et = datetime.combine(trading_day, close_time, tzinfo=ET)
    timestamps: list[datetime] = []
    current = open_et
    interval = timedelta(minutes=interval_minutes)
    while current < close_et:
        timestamps.append(current.astimezone(UTC))
        current += interval
    return timestamps


def _expected_latest_timestamp(
    as_of_utc: datetime,
    interval_minutes: int,
    calendar: USEquityCalendar,
) -> datetime | None:
    as_of_et = to_et(as_of_utc)
    trading_day = as_of_et.date()
    open_et = datetime.combine(trading_day, time(9, 30), tzinfo=ET)
    close_time = calendar.early_close_time if calendar.is_early_close(trading_day) else time(16, 0)
    close_et = datetime.combine(trading_day, close_time, tzinfo=ET)
    interval_seconds = interval_minutes * 60

    if not calendar.is_trading_day(trading_day) or as_of_et <= open_et:
        previous_day = calendar.previous_trading_day(trading_day)
        expected = _expected_regular_timestamps(previous_day, interval_minutes, calendar)
        return expected[-1] if expected else None

    if as_of_et >= close_et:
        expected = _expected_regular_timestamps(trading_day, interval_minutes, calendar)
        return expected[-1] if expected else None

    elapsed_seconds = int((as_of_et - open_et).total_seconds())
    slots_completed = (elapsed_seconds // interval_seconds) - 1 if elapsed_seconds >= interval_seconds else -1
    if slots_completed < 0:
        previous_day = calendar.previous_trading_day(trading_day)
        expected = _expected_regular_timestamps(previous_day, interval_minutes, calendar)
        return expected[-1] if expected else None
    latest_et = open_et + timedelta(seconds=slots_completed * interval_seconds)
    return latest_et.astimezone(UTC)


def _freshness_lag_minutes(expected_latest: datetime | None, latest_observed: datetime | None) -> float:
    if expected_latest is None or latest_observed is None:
        return 0.0
    lag_seconds = max(0.0, (expected_latest - latest_observed).total_seconds())
    return round(lag_seconds / 60.0, 4)


def _latest_completed_trading_day(as_of_utc: datetime, calendar: USEquityCalendar) -> date:
    as_of_et = to_et(as_of_utc)
    trading_day = as_of_et.date()
    close_time = calendar.early_close_time if calendar.is_early_close(trading_day) else time(16, 0)
    close_et = datetime.combine(trading_day, close_time, tzinfo=ET)
    if calendar.is_trading_day(trading_day) and as_of_et >= close_et:
        return trading_day
    return calendar.previous_trading_day(trading_day)


def _recent_trading_days(end_day: date, count: int, calendar: USEquityCalendar) -> list[date]:
    days: list[date] = []
    current = end_day
    while len(days) < max(1, count):
        if calendar.is_trading_day(current):
            days.append(current)
        current = calendar.previous_trading_day(current)
    return sorted(days)


def _resolve_symbols(
    dataset_root: Path,
    bar_sizes: list[str],
    symbols: list[str] | None,
) -> list[str]:
    if symbols:
        seen: set[str] = set()
        resolved: list[str] = []
        for symbol in symbols:
            normalized = str(symbol or "").strip().upper()
            if normalized and normalized not in seen:
                seen.add(normalized)
                resolved.append(normalized)
        return resolved

    discovered: set[str] = set()
    for bar_size in bar_sizes:
        base = dataset_root / f"bar_size={bar_size}"
        if not base.exists():
            continue
        for path in base.glob("symbol=*"):
            if path.is_dir():
                discovered.add(path.name.split("=", 1)[-1].upper())
    return sorted(discovered)


def _normalize_bar_sizes(values: list[str] | tuple[str, ...]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        bar_size = str(value or "").strip().lower()
        if not bar_size or bar_size in seen or bar_size not in SUPPORTED_MINUTE_BAR_SIZES:
            continue
        seen.add(bar_size)
        normalized.append(bar_size)
    return normalized or list(SUPPORTED_MINUTE_BAR_SIZES)


def _worst_status(statuses: Any) -> str:
    resolved = list(statuses)
    if not resolved:
        return "MISSING"
    return max(resolved, key=lambda value: _STATUS_RANK.get(str(value), 0))
