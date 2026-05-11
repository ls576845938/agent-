from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from quant_us.core.calendar import USEquityCalendar
from quant_us.core.clock import ET, UTC, ensure_utc, to_et, utc_now

SUPPORTED_MINUTE_BAR_SIZES: tuple[str, ...] = ("1m", "5m", "15m")
SUPPORTED_ROOT_SUBDIRS: tuple[str, ...] = ("raw", "cleaned")
_STATUS_RANK = {"PASS": 0, "WARN": 1, "FAIL": 2, "MISSING": 3}
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
    min_coverage_pct: float = 99.0
    session_coverage: list[dict[str, Any]] = field(default_factory=list)
    latest_timestamp_utc: str = ""
    expected_latest_timestamp_utc: str = ""
    freshness_lag_minutes: float = 0.0
    missing_bar_samples_utc: list[str] = field(default_factory=list)
    evidence_paths: list[str] = field(default_factory=list)
    duplicate_timestamp_count: int = 0
    conflicting_duplicate_count: int = 0
    invalid_ohlc_count: int = 0
    non_positive_price_count: int = 0
    zero_volume_count: int = 0
    negative_volume_count: int = 0
    timezone_naive_count: int = 0
    timezone_non_utc_count: int = 0
    outside_session_count: int = 0
    malformed_file_count: int = 0
    file_errors: list[str] = field(default_factory=list)
    outside_session_samples_utc: list[str] = field(default_factory=list)
    gate_reasons: list[str] = field(default_factory=list)

    @property
    def duplicate_count(self) -> int:
        return self.duplicate_timestamp_count

    @property
    def conflict_count(self) -> int:
        return self.conflicting_duplicate_count

    @property
    def invalid_ohlc(self) -> int:
        return self.invalid_ohlc_count

    @property
    def non_positive_count(self) -> int:
        return self.non_positive_price_count + self.negative_volume_count

    @property
    def zero_volume(self) -> int:
        return self.zero_volume_count

    @property
    def missing_bars(self) -> int:
        return self.missing_bar_count

    @property
    def quality_dimensions(self) -> dict[str, Any]:
        return {
            "coverage": {
                "status": _coverage_dimension_status(self),
                "coverage_pct": self.coverage_pct,
                "expected_bars": self.expected_bars,
                "observed_bars": self.observed_bars,
                "missing_bar_count": self.missing_bar_count,
                "missing_file_dates": list(self.missing_file_dates),
                "missing_bar_samples_utc": list(self.missing_bar_samples_utc),
            },
            "duplicates": {
                "status": _duplicate_dimension_status(self),
                "duplicate_timestamp_count": self.duplicate_timestamp_count,
                "conflicting_duplicate_count": self.conflicting_duplicate_count,
            },
            "ohlc": {
                "status": _ohlc_dimension_status(self),
                "invalid_ohlc_count": self.invalid_ohlc_count,
                "non_positive_price_count": self.non_positive_price_count,
                "negative_volume_count": self.negative_volume_count,
            },
            "volume": {
                "status": _volume_dimension_status(self),
                "zero_volume_count": self.zero_volume_count,
                "negative_volume_count": self.negative_volume_count,
            },
            "timezone_session": {
                "status": _timezone_session_dimension_status(self),
                "timezone_naive_count": self.timezone_naive_count,
                "timezone_non_utc_count": self.timezone_non_utc_count,
                "outside_session_count": self.outside_session_count,
                "outside_session_samples_utc": list(self.outside_session_samples_utc),
                "session_coverage": [dict(item) for item in self.session_coverage],
            },
            "files": {
                "status": _file_dimension_status(self),
                "malformed_file_count": self.malformed_file_count,
                "file_errors": list(self.file_errors),
                "evidence_paths": list(self.evidence_paths),
            },
        }

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
            "missing_bars": self.missing_bars,
            "coverage_pct": self.coverage_pct,
            "min_coverage_pct": self.min_coverage_pct,
            "session_coverage": [dict(item) for item in self.session_coverage],
            "latest_timestamp_utc": self.latest_timestamp_utc,
            "expected_latest_timestamp_utc": self.expected_latest_timestamp_utc,
            "freshness_lag_minutes": self.freshness_lag_minutes,
            "missing_bar_samples_utc": list(self.missing_bar_samples_utc),
            "evidence_paths": list(self.evidence_paths),
            "duplicate_timestamp_count": self.duplicate_timestamp_count,
            "duplicate": self.duplicate_count,
            "conflicting_duplicate_count": self.conflicting_duplicate_count,
            "conflict": self.conflict_count,
            "invalid_ohlc_count": self.invalid_ohlc_count,
            "invalid_ohlc": self.invalid_ohlc,
            "non_positive_price_count": self.non_positive_price_count,
            "negative_volume_count": self.negative_volume_count,
            "non_positive": self.non_positive_count,
            "zero_volume_count": self.zero_volume_count,
            "zero_volume": self.zero_volume,
            "timezone_naive_count": self.timezone_naive_count,
            "timezone_non_utc_count": self.timezone_non_utc_count,
            "outside_session_count": self.outside_session_count,
            "malformed_file_count": self.malformed_file_count,
            "file_errors": list(self.file_errors),
            "outside_session_samples_utc": list(self.outside_session_samples_utc),
            "gate_reasons": list(self.gate_reasons),
            "quality_dimensions": self.quality_dimensions,
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
    root_subdir: str
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
            "root_subdir": self.root_subdir,
            "vendor": self.vendor,
            "asset_class": self.asset_class,
            "lookback_trading_days": self.lookback_trading_days,
            "bar_sizes": list(self.bar_sizes),
            "evaluated_symbols": list(self.evaluated_symbols),
            "symbols": [symbol.to_dict() for symbol in self.symbols],
            "evidence_summary": self.evidence_summary,
            "remediation_summary": self.remediation_summary,
        }

    @property
    def issue_count(self) -> int:
        return sum(
            1
            for symbol in self.symbols
            for interval in symbol.intervals
            if interval.status != "PASS"
        )

    @property
    def evidence_summary(self) -> dict[str, Any]:
        return _build_evidence_summary(_interval_records_for_dataset(self))

    @property
    def remediation_summary(self) -> dict[str, Any]:
        return _build_remediation_summary(
            _interval_records_for_dataset(self),
            data_root=self.data_root,
        )


@dataclass(frozen=True)
class MinuteDataQualityOverviewReport:
    status: str
    as_of_utc: str
    data_root: str
    vendor: str
    asset_class: str
    lookback_trading_days: int
    bar_sizes: list[str]
    evaluated_symbols: list[str]
    datasets: list[MinuteDataQualityReport]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "as_of_utc": self.as_of_utc,
            "data_root": self.data_root,
            "vendor": self.vendor,
            "asset_class": self.asset_class,
            "lookback_trading_days": self.lookback_trading_days,
            "bar_sizes": list(self.bar_sizes),
            "evaluated_symbols": list(self.evaluated_symbols),
            "datasets": [dataset.to_dict() for dataset in self.datasets],
            "dataset_statuses": {
                dataset.root_subdir: {
                    "status": dataset.status,
                    "dataset_root": dataset.dataset_root,
                    "issue_count": dataset.issue_count,
                    "evaluated_symbols": list(dataset.evaluated_symbols),
                }
                for dataset in self.datasets
            },
            "evidence_summary": self.evidence_summary,
            "remediation_summary": self.remediation_summary,
        }

    @property
    def issue_count(self) -> int:
        return sum(dataset.issue_count for dataset in self.datasets)

    @property
    def evidence_summary(self) -> dict[str, Any]:
        return _build_evidence_summary(_interval_records_for_overview(self))

    @property
    def remediation_summary(self) -> dict[str, Any]:
        return _build_remediation_summary(
            _interval_records_for_overview(self),
            data_root=self.data_root,
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
    normalized_root_subdir = _normalize_root_subdir(root_subdir)
    as_of_utc = ensure_utc(as_of or utc_now())
    calendar = USEquityCalendar.with_holidays()
    dataset_root = root / normalized_root_subdir / f"vendor={vendor}" / f"asset_class={asset_class}"
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
        root_subdir=normalized_root_subdir,
        vendor=vendor,
        asset_class=asset_class,
        lookback_trading_days=lookback_trading_days,
        bar_sizes=list(normalized_bar_sizes),
        evaluated_symbols=list(resolved_symbols),
        symbols=symbol_summaries,
    )


def inspect_minute_data_quality_overview(
    data_root: str | Path = "data",
    *,
    symbols: list[str] | None = None,
    vendor: str = "yfinance",
    asset_class: str = "equity",
    bar_sizes: list[str] | tuple[str, ...] = SUPPORTED_MINUTE_BAR_SIZES,
    lookback_trading_days: int = 5,
    as_of: datetime | None = None,
    root_subdirs: Iterable[str] = SUPPORTED_ROOT_SUBDIRS,
    min_coverage_pct: float = 99.0,
    max_missing_samples: int = 8,
) -> MinuteDataQualityOverviewReport:
    root = Path(data_root)
    normalized_bar_sizes = _normalize_bar_sizes(bar_sizes)
    normalized_root_subdirs = _normalize_root_subdirs(root_subdirs)
    as_of_utc = ensure_utc(as_of or utc_now())
    resolved_symbols = _resolve_symbols_across_roots(
        data_root=root,
        vendor=vendor,
        asset_class=asset_class,
        bar_sizes=normalized_bar_sizes,
        root_subdirs=normalized_root_subdirs,
        symbols=symbols,
    )

    datasets = [
        inspect_minute_data_quality(
            data_root=root,
            symbols=list(resolved_symbols),
            vendor=vendor,
            asset_class=asset_class,
            bar_sizes=normalized_bar_sizes,
            lookback_trading_days=lookback_trading_days,
            as_of=as_of_utc,
            root_subdir=root_subdir,
            min_coverage_pct=min_coverage_pct,
            max_missing_samples=max_missing_samples,
        )
        for root_subdir in normalized_root_subdirs
    ]
    overall_status = _worst_status(dataset.status for dataset in datasets) if datasets else "MISSING"
    merged_symbols = sorted({symbol for dataset in datasets for symbol in dataset.evaluated_symbols})

    return MinuteDataQualityOverviewReport(
        status=overall_status,
        as_of_utc=as_of_utc.isoformat(),
        data_root=str(root),
        vendor=vendor,
        asset_class=asset_class,
        lookback_trading_days=lookback_trading_days,
        bar_sizes=list(normalized_bar_sizes),
        evaluated_symbols=merged_symbols or list(resolved_symbols),
        datasets=datasets,
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
    session_metadata_by_day = {
        day.isoformat(): _session_metadata(day, interval_minutes, calendar)
        for day in expected_days
    }
    expected_ts_by_day = {
        day.isoformat(): _expected_regular_timestamps(day, interval_minutes, calendar)
        for day in expected_days
    }
    expected_ts = {
        timestamp
        for timestamps in expected_ts_by_day.values()
        for timestamp in timestamps
    }
    expected_latest = _expected_latest_timestamp(as_of_utc, interval_minutes, calendar)

    if not base.exists():
        missing_bars = len(expected_ts)
        return MinuteBarQualitySnapshot(
            symbol=symbol.upper(),
            bar_size=bar_size,
            status="MISSING",
            expected_trading_days=expected_dates,
            observed_file_dates=[],
            missing_file_dates=expected_dates,
            expected_bars=missing_bars,
            observed_bars=0,
            missing_bar_count=missing_bars,
            coverage_pct=0.0,
            min_coverage_pct=min_coverage_pct,
            session_coverage=_missing_session_coverage(expected_ts_by_day, session_metadata_by_day),
            expected_latest_timestamp_utc=expected_latest.isoformat() if expected_latest else "",
            freshness_lag_minutes=0.0,
            gate_reasons=["dataset_partition_missing"],
        )

    observed_ts: set[datetime] = set()
    observed_ts_by_day: dict[str, set[datetime]] = {key: set() for key in expected_ts_by_day}
    evidence_paths: list[str] = []
    observed_dates: list[str] = []
    missing_file_dates: list[str] = []
    duplicate_timestamp_count = 0
    conflicting_duplicate_count = 0
    invalid_ohlc_count = 0
    non_positive_price_count = 0
    zero_volume_count = 0
    negative_volume_count = 0
    timezone_naive_count = 0
    timezone_non_utc_count = 0
    outside_session_count = 0
    malformed_file_count = 0
    file_errors: list[str] = []
    outside_session_samples: list[str] = []

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
        zero_volume_count += quality["zero_volume_count"]
        negative_volume_count += quality["negative_volume_count"]
        timezone_naive_count += quality["timezone_naive_count"]
        timezone_non_utc_count += quality["timezone_non_utc_count"]
        outside_session_count += quality["outside_session_count"]
        malformed_file_count += quality["malformed_file_count"]
        file_errors.extend(quality["file_errors"])
        outside_session_samples.extend(quality["outside_session_samples_utc"])
        for timestamp in quality["timestamps"]:
            observed_ts.add(timestamp)
            observed_ts_by_day.setdefault(date_str, set()).add(timestamp)

    missing_timestamps = sorted(expected_ts - observed_ts)
    latest_observed = max(observed_ts) if observed_ts else None
    freshness_lag = _freshness_lag_minutes(expected_latest, latest_observed)
    coverage_pct = round((len(observed_ts) / max(1, len(expected_ts))) * 100.0, 4)
    session_coverage = _build_session_coverage(
        expected_ts_by_day,
        observed_ts_by_day,
        session_metadata_by_day,
    )
    gate_reasons = _gate_reasons(
        coverage_pct=coverage_pct,
        min_coverage_pct=min_coverage_pct,
        missing_file_dates=missing_file_dates,
        missing_bar_count=len(missing_timestamps),
        duplicate_timestamp_count=duplicate_timestamp_count,
        conflicting_duplicate_count=conflicting_duplicate_count,
        invalid_ohlc_count=invalid_ohlc_count,
        non_positive_count=non_positive_price_count + negative_volume_count,
        zero_volume_count=zero_volume_count,
        timezone_naive_count=timezone_naive_count,
        timezone_non_utc_count=timezone_non_utc_count,
        outside_session_count=outside_session_count,
        malformed_file_count=malformed_file_count,
        observed_bars=len(observed_ts),
    )
    status = _classify_status(
        coverage_pct=coverage_pct,
        min_coverage_pct=min_coverage_pct,
        missing_bar_count=len(missing_timestamps),
        duplicate_timestamp_count=duplicate_timestamp_count,
        conflicting_duplicate_count=conflicting_duplicate_count,
        invalid_ohlc_count=invalid_ohlc_count,
        non_positive_count=non_positive_price_count + negative_volume_count,
        zero_volume_count=zero_volume_count,
        timezone_naive_count=timezone_naive_count,
        timezone_non_utc_count=timezone_non_utc_count,
        outside_session_count=outside_session_count,
        malformed_file_count=malformed_file_count,
        observed_bars=len(observed_ts),
    )

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
        min_coverage_pct=min_coverage_pct,
        session_coverage=session_coverage,
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
        zero_volume_count=zero_volume_count,
        negative_volume_count=negative_volume_count,
        timezone_naive_count=timezone_naive_count,
        timezone_non_utc_count=timezone_non_utc_count,
        outside_session_count=outside_session_count,
        malformed_file_count=malformed_file_count,
        file_errors=file_errors[:max_missing_samples],
        outside_session_samples_utc=outside_session_samples[:max_missing_samples],
        gate_reasons=gate_reasons,
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
        "zero_volume_count": 0,
        "negative_volume_count": 0,
        "timezone_naive_count": 0,
        "timezone_non_utc_count": 0,
        "outside_session_count": 0,
        "malformed_file_count": 0,
        "file_errors": [],
        "outside_session_samples_utc": [],
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

    expected_set = set(expected_timestamps)
    (
        normalized,
        timezone_naive_count,
        timezone_non_utc_count,
        invalid_timestamp_count,
    ) = _normalize_timestamps(frame[ts_col])
    if invalid_timestamp_count:
        return {
            **empty,
            "malformed_file_count": 1,
            "file_errors": [f"{path}:invalid_timestamps:{invalid_timestamp_count}"],
        }
    regular = frame.copy()
    regular["_timestamp_utc_norm"] = normalized
    unexpected = regular[regular["_timestamp_utc_norm"].notna() & ~regular["_timestamp_utc_norm"].isin(expected_set)].copy()
    regular = regular[regular["_timestamp_utc_norm"].isin(expected_set)].copy()
    if regular.empty:
        return {
            **empty,
            "timezone_naive_count": timezone_naive_count,
            "timezone_non_utc_count": timezone_non_utc_count,
            "outside_session_count": int(len(unexpected)),
            "outside_session_samples_utc": [
                timestamp.isoformat()
                for timestamp in unexpected["_timestamp_utc_norm"].dropna().drop_duplicates().tolist()[:8]
            ],
        }

    duplicate_mask = regular.duplicated("_timestamp_utc_norm", keep=False)
    duplicate_timestamp_count = int(duplicate_mask.sum())
    conflicting_duplicate_count = 0
    if duplicate_timestamp_count:
        compare_columns = [*list(_PRICE_COLUMNS), *([ "volume"] if "volume" in regular.columns else [])]
        for _, group in regular[duplicate_mask].groupby("_timestamp_utc_norm", dropna=True):
            if len(group[compare_columns].drop_duplicates()) > 1:
                conflicting_duplicate_count += 1

    price_frame = regular.loc[:, _PRICE_COLUMNS].apply(pd.to_numeric, errors="coerce")
    positive_price_mask = price_frame.gt(0).all(axis=1) & price_frame.notna().all(axis=1)
    structural_invalid_mask = positive_price_mask & (
        (price_frame["high"] < price_frame["low"])
        | (price_frame["high"] < price_frame[["open", "close"]].max(axis=1))
        | (price_frame["low"] > price_frame[["open", "close"]].min(axis=1))
    )
    non_positive_price_mask = ~positive_price_mask

    zero_volume_count = 0
    negative_volume_count = 0
    if "volume" in regular.columns:
        volume = pd.to_numeric(regular["volume"], errors="coerce")
        zero_volume_count = int((volume.eq(0) | volume.isna()).sum())
        negative_volume_count = int(volume.lt(0).sum())

    return {
        "timestamps": set(regular["_timestamp_utc_norm"].dropna().drop_duplicates()),
        "duplicate_timestamp_count": duplicate_timestamp_count,
        "conflicting_duplicate_count": conflicting_duplicate_count,
        "invalid_ohlc_count": int(structural_invalid_mask.sum()),
        "non_positive_price_count": int(non_positive_price_mask.sum()),
        "zero_volume_count": zero_volume_count,
        "negative_volume_count": negative_volume_count,
        "timezone_naive_count": timezone_naive_count,
        "timezone_non_utc_count": timezone_non_utc_count,
        "outside_session_count": int(len(unexpected)),
        "malformed_file_count": 0,
        "file_errors": [],
        "outside_session_samples_utc": [
            timestamp.isoformat()
            for timestamp in unexpected["_timestamp_utc_norm"].dropna().drop_duplicates().tolist()[:8]
        ],
    }


def _missing_session_coverage(
    expected_ts_by_day: dict[str, list[datetime]],
    session_metadata_by_day: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        {
            "date": trading_day,
            **dict(session_metadata_by_day.get(trading_day, {})),
            "expected_bars": len(expected),
            "observed_bars": 0,
            "missing_bars": len(expected),
            "coverage_pct": 0.0,
        }
        for trading_day, expected in expected_ts_by_day.items()
    ]


def _build_session_coverage(
    expected_ts_by_day: dict[str, list[datetime]],
    observed_ts_by_day: dict[str, set[datetime]],
    session_metadata_by_day: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    coverage: list[dict[str, Any]] = []
    for trading_day, expected in expected_ts_by_day.items():
        observed = len(observed_ts_by_day.get(trading_day, set()))
        expected_count = len(expected)
        coverage.append(
            {
                "date": trading_day,
                **dict(session_metadata_by_day.get(trading_day, {})),
                "expected_bars": expected_count,
                "observed_bars": observed,
                "missing_bars": max(0, expected_count - observed),
                "coverage_pct": round((observed / max(1, expected_count)) * 100.0, 4),
            }
        )
    return coverage


def _gate_reasons(
    *,
    coverage_pct: float,
    min_coverage_pct: float,
    missing_file_dates: list[str],
    missing_bar_count: int,
    duplicate_timestamp_count: int,
    conflicting_duplicate_count: int,
    invalid_ohlc_count: int,
    non_positive_count: int,
    zero_volume_count: int,
    timezone_naive_count: int,
    timezone_non_utc_count: int,
    outside_session_count: int,
    malformed_file_count: int,
    observed_bars: int,
) -> list[str]:
    reasons: list[str] = []
    if observed_bars == 0:
        reasons.append("regular_session_bars_missing")
    if malformed_file_count > 0:
        reasons.append(f"malformed_files:{malformed_file_count}")
    if conflicting_duplicate_count > 0:
        reasons.append(f"conflicting_duplicates:{conflicting_duplicate_count}")
    if invalid_ohlc_count > 0:
        reasons.append(f"invalid_ohlc:{invalid_ohlc_count}")
    if non_positive_count > 0:
        reasons.append(f"non_positive:{non_positive_count}")
    if timezone_naive_count > 0:
        reasons.append(f"timezone_naive:{timezone_naive_count}")
    if timezone_non_utc_count > 0:
        reasons.append(f"timezone_non_utc:{timezone_non_utc_count}")
    if outside_session_count > 0:
        reasons.append(f"outside_session:{outside_session_count}")
    if coverage_pct < min_coverage_pct:
        reasons.append(f"coverage_below_threshold:{coverage_pct:.4f}")
    elif missing_bar_count > 0:
        reasons.append(f"missing_bars:{missing_bar_count}")
    if missing_file_dates:
        reasons.append(f"missing_files:{len(missing_file_dates)}")
    if duplicate_timestamp_count > 0:
        reasons.append(f"duplicate_rows:{duplicate_timestamp_count}")
    if zero_volume_count > 0:
        reasons.append(f"zero_volume:{zero_volume_count}")
    return reasons


def _classify_status(
    *,
    coverage_pct: float,
    min_coverage_pct: float,
    missing_bar_count: int,
    duplicate_timestamp_count: int,
    conflicting_duplicate_count: int,
    invalid_ohlc_count: int,
    non_positive_count: int,
    zero_volume_count: int,
    timezone_naive_count: int,
    timezone_non_utc_count: int,
    outside_session_count: int,
    malformed_file_count: int,
    observed_bars: int,
) -> str:
    if observed_bars == 0:
        return "MISSING"
    if (
        malformed_file_count > 0
        or conflicting_duplicate_count > 0
        or invalid_ohlc_count > 0
        or non_positive_count > 0
        or timezone_naive_count > 0
        or timezone_non_utc_count > 0
        or outside_session_count > 0
        or coverage_pct < min_coverage_pct
    ):
        return "FAIL"
    if missing_bar_count > 0 or duplicate_timestamp_count > 0 or zero_volume_count > 0:
        return "WARN"
    return "PASS"


def _normalize_timestamps(
    values: pd.Series,
) -> tuple[pd.Series, int, int, int]:
    normalized: list[datetime | None] = []
    timezone_naive_count = 0
    timezone_non_utc_count = 0
    invalid_timestamp_count = 0
    for raw_value in values.tolist():
        if pd.isna(raw_value):
            normalized.append(None)
            invalid_timestamp_count += 1
            continue
        try:
            timestamp = pd.Timestamp(raw_value)
        except (TypeError, ValueError):
            normalized.append(None)
            invalid_timestamp_count += 1
            continue
        if timestamp.tzinfo is None:
            timezone_naive_count += 1
            normalized.append(timestamp.tz_localize(UTC).to_pydatetime())
            continue
        if getattr(timestamp.tzinfo, "key", None) != "UTC" and str(timestamp.tzinfo) != "UTC":
            timezone_non_utc_count += 1
        normalized.append(timestamp.tz_convert(UTC).to_pydatetime())
    return pd.Series(normalized, index=values.index), timezone_naive_count, timezone_non_utc_count, invalid_timestamp_count


def _session_metadata(
    trading_day: date,
    interval_minutes: int,
    calendar: USEquityCalendar,
) -> dict[str, Any]:
    expected = _expected_regular_timestamps(trading_day, interval_minutes, calendar)
    open_utc = expected[0].isoformat() if expected else ""
    close_utc = ""
    if expected:
        close_utc = (expected[-1] + timedelta(minutes=interval_minutes)).isoformat()
    is_early_close = bool(calendar.is_early_close(trading_day))
    return {
        "session_type": "early_close" if is_early_close else "regular",
        "is_early_close": is_early_close,
        "expected_session_open_utc": open_utc,
        "expected_session_close_utc": close_utc,
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
        return _normalize_symbols(symbols)

    discovered: set[str] = set()
    for bar_size in bar_sizes:
        base = dataset_root / f"bar_size={bar_size}"
        if not base.exists():
            continue
        for path in base.glob("symbol=*"):
            if path.is_dir():
                discovered.add(path.name.split("=", 1)[-1].upper())
    return sorted(discovered)


def _resolve_symbols_across_roots(
    *,
    data_root: Path,
    vendor: str,
    asset_class: str,
    bar_sizes: list[str],
    root_subdirs: list[str],
    symbols: list[str] | None,
) -> list[str]:
    if symbols:
        return _normalize_symbols(symbols)
    discovered: set[str] = set()
    for root_subdir in root_subdirs:
        dataset_root = data_root / root_subdir / f"vendor={vendor}" / f"asset_class={asset_class}"
        discovered.update(_resolve_symbols(dataset_root, bar_sizes, None))
    return sorted(discovered)


def _coverage_dimension_status(snapshot: MinuteBarQualitySnapshot) -> str:
    if snapshot.observed_bars == 0:
        return "MISSING"
    if snapshot.coverage_pct < snapshot.min_coverage_pct:
        return "FAIL"
    if snapshot.missing_bar_count > 0 or snapshot.missing_file_dates:
        return "WARN"
    return "PASS"


def _duplicate_dimension_status(snapshot: MinuteBarQualitySnapshot) -> str:
    if snapshot.observed_bars == 0:
        return "MISSING"
    if snapshot.conflicting_duplicate_count > 0:
        return "FAIL"
    if snapshot.duplicate_timestamp_count > 0:
        return "WARN"
    return "PASS"


def _ohlc_dimension_status(snapshot: MinuteBarQualitySnapshot) -> str:
    if snapshot.observed_bars == 0:
        return "MISSING"
    if snapshot.invalid_ohlc_count > 0 or snapshot.non_positive_count > 0:
        return "FAIL"
    return "PASS"


def _volume_dimension_status(snapshot: MinuteBarQualitySnapshot) -> str:
    if snapshot.observed_bars == 0:
        return "MISSING"
    if snapshot.negative_volume_count > 0:
        return "FAIL"
    if snapshot.zero_volume_count > 0:
        return "WARN"
    return "PASS"


def _timezone_session_dimension_status(snapshot: MinuteBarQualitySnapshot) -> str:
    if snapshot.observed_bars == 0:
        return "MISSING"
    if (
        snapshot.timezone_naive_count > 0
        or snapshot.timezone_non_utc_count > 0
        or snapshot.outside_session_count > 0
    ):
        return "FAIL"
    return "PASS"


def _file_dimension_status(snapshot: MinuteBarQualitySnapshot) -> str:
    if snapshot.observed_bars == 0 and not snapshot.evidence_paths:
        return "MISSING"
    if snapshot.malformed_file_count > 0:
        return "FAIL"
    if snapshot.missing_file_dates:
        return "WARN"
    return "PASS"


def _interval_records_for_dataset(report: MinuteDataQualityReport) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for symbol_summary in report.symbols:
        for interval in symbol_summary.intervals:
            records.append(
                {
                    "root_subdir": report.root_subdir,
                    "dataset_root": report.dataset_root,
                    "symbol": symbol_summary.symbol,
                    "interval": interval,
                }
            )
    return records


def _interval_records_for_overview(report: MinuteDataQualityOverviewReport) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for dataset in report.datasets:
        records.extend(_interval_records_for_dataset(dataset))
    return records


def _status_counts() -> dict[str, int]:
    return {"PASS": 0, "WARN": 0, "FAIL": 0, "MISSING": 0}


def _build_evidence_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    status_counts = _status_counts()
    bar_size_summary: dict[str, dict[str, Any]] = {}
    affected_symbols: set[str] = set()
    evidence_paths: set[str] = set()
    category_totals = {
        "missing_files": 0,
        "missing_bars": 0,
        "duplicate_rows": 0,
        "conflicting_duplicates": 0,
        "invalid_ohlc": 0,
        "non_positive_prices": 0,
        "negative_volume": 0,
        "zero_volume": 0,
        "timezone_naive_rows": 0,
        "timezone_non_utc_rows": 0,
        "outside_session_rows": 0,
        "malformed_files": 0,
    }
    session_totals = {"regular_days": 0, "early_close_days": 0}
    for record in records:
        interval = record["interval"]
        status_counts[interval.status] = status_counts.get(interval.status, 0) + 1
        if interval.status != "PASS":
            affected_symbols.add(str(record["symbol"]))
        evidence_paths.update(interval.evidence_paths)
        category_totals["missing_files"] += len(interval.missing_file_dates)
        category_totals["missing_bars"] += int(interval.missing_bar_count)
        category_totals["duplicate_rows"] += int(interval.duplicate_timestamp_count)
        category_totals["conflicting_duplicates"] += int(interval.conflicting_duplicate_count)
        category_totals["invalid_ohlc"] += int(interval.invalid_ohlc_count)
        category_totals["non_positive_prices"] += int(interval.non_positive_price_count)
        category_totals["negative_volume"] += int(interval.negative_volume_count)
        category_totals["zero_volume"] += int(interval.zero_volume_count)
        category_totals["timezone_naive_rows"] += int(interval.timezone_naive_count)
        category_totals["timezone_non_utc_rows"] += int(interval.timezone_non_utc_count)
        category_totals["outside_session_rows"] += int(interval.outside_session_count)
        category_totals["malformed_files"] += int(interval.malformed_file_count)
        for session_row in interval.session_coverage:
            if bool(session_row.get("is_early_close", False)):
                session_totals["early_close_days"] += 1
            else:
                session_totals["regular_days"] += 1
        bar_size_bucket = bar_size_summary.setdefault(
            interval.bar_size,
            {
                "status": "PASS",
                "status_counts": _status_counts(),
                "affected_symbols": set(),
                "intervals_evaluated": 0,
            },
        )
        bar_size_bucket["status"] = _worst_status((bar_size_bucket["status"], interval.status))
        bar_size_bucket["status_counts"][interval.status] = bar_size_bucket["status_counts"].get(interval.status, 0) + 1
        bar_size_bucket["intervals_evaluated"] += 1
        if interval.status != "PASS":
            bar_size_bucket["affected_symbols"].add(str(record["symbol"]))

    normalized_bar_size_summary: dict[str, dict[str, Any]] = {}
    for bar_size in sorted(bar_size_summary, key=lambda value: SUPPORTED_MINUTE_BAR_SIZES.index(value)):
        payload = bar_size_summary[bar_size]
        normalized_bar_size_summary[bar_size] = {
            "status": payload["status"],
            "status_counts": dict(payload["status_counts"]),
            "affected_symbols": sorted(payload["affected_symbols"]),
            "intervals_evaluated": int(payload["intervals_evaluated"]),
        }

    return {
        "strict_gate": True,
        "read_only": True,
        "download_performed": False,
        "intervals_evaluated": len(records),
        "interval_status_counts": status_counts,
        "affected_symbols": sorted(affected_symbols),
        "bar_size_summary": normalized_bar_size_summary,
        "category_totals": category_totals,
        "session_totals": session_totals,
        "evidence_path_count": len(evidence_paths),
        "evidence_paths_sample": sorted(evidence_paths)[:12],
    }


def _build_remediation_summary(
    records: list[dict[str, Any]],
    *,
    data_root: str,
) -> dict[str, Any]:
    grouped: dict[str, dict[str, Any]] = {}
    categories = (
        ("coverage", "high", "Explicitly backfill only the listed missing partitions/bars, then re-run the read-only gate."),
        ("duplicates", "high", "Deduplicate vendor partitions upstream and preserve one canonical bar per timestamp before promoting data."),
        ("ohlc", "high", "Repair corrupted OHLC/price rows upstream; do not let invalid prices into cleaned research inputs."),
        ("volume", "medium", "Audit zero/negative volume rows against vendor raw evidence and either correct or quarantine the affected bars."),
        ("timezone_session", "high", "Normalize timestamps to UTC before writing parquet and keep rows inside the expected US regular session window."),
        ("files", "high", "Repair unreadable parquet partitions or regenerate them explicitly; this gate did not fetch or download anything."),
    )
    for category, priority, instruction in categories:
        grouped[category] = {
            "priority": priority,
            "category": category,
            "instruction": instruction,
            "root_subdirs": set(),
            "symbols": set(),
            "bar_sizes": set(),
            "details": [],
            "evidence_paths": set(),
            "affected_interval_keys": set(),
        }

    for record in records:
        interval = record["interval"]
        root_subdir = str(record["root_subdir"])
        scope = f"{root_subdir}/{record['symbol']}/{interval.bar_size}"
        dimensions = interval.quality_dimensions
        for category, payload in dimensions.items():
            if str(payload.get("status", "PASS")) == "PASS":
                continue
            bucket = grouped[category]
            bucket["root_subdirs"].add(root_subdir)
            bucket["symbols"].add(str(record["symbol"]))
            bucket["bar_sizes"].add(interval.bar_size)
            bucket["evidence_paths"].update(interval.evidence_paths)
            bucket["affected_interval_keys"].add(scope)
            if category == "coverage":
                bucket["details"].append(
                    f"{scope} coverage={interval.coverage_pct:.2f}% missing_files={len(interval.missing_file_dates)} missing_bars={interval.missing_bar_count}"
                )
            elif category == "duplicates":
                bucket["details"].append(
                    f"{scope} duplicate_rows={interval.duplicate_timestamp_count} conflicting_duplicates={interval.conflicting_duplicate_count}"
                )
            elif category == "ohlc":
                bucket["details"].append(
                    f"{scope} invalid_ohlc={interval.invalid_ohlc_count} non_positive={interval.non_positive_count}"
                )
            elif category == "volume":
                bucket["details"].append(
                    f"{scope} zero_volume={interval.zero_volume_count} negative_volume={interval.negative_volume_count}"
                )
            elif category == "timezone_session":
                bucket["details"].append(
                    f"{scope} timezone_naive={interval.timezone_naive_count} timezone_non_utc={interval.timezone_non_utc_count} outside_session={interval.outside_session_count}"
                )
            elif category == "files":
                bucket["details"].append(
                    f"{scope} malformed_files={interval.malformed_file_count} file_errors={len(interval.file_errors)}"
                )

    actions: list[dict[str, Any]] = []
    for category in ("coverage", "duplicates", "ohlc", "volume", "timezone_session", "files"):
        bucket = grouped[category]
        if not bucket["affected_interval_keys"]:
            continue
        actions.append(
            {
                "priority": bucket["priority"],
                "category": category,
                "summary": f"{category} issues detected in {len(bucket['affected_interval_keys'])} interval checks.",
                "instruction": bucket["instruction"],
                "root_subdirs": sorted(bucket["root_subdirs"]),
                "symbols": sorted(bucket["symbols"]),
                "bar_sizes": sorted(bucket["bar_sizes"], key=lambda value: SUPPORTED_MINUTE_BAR_SIZES.index(value)),
                "affected_interval_count": len(bucket["affected_interval_keys"]),
                "details": bucket["details"][:10],
                "evidence_paths": sorted(bucket["evidence_paths"])[:12],
            }
        )

    return {
        "strict_gate": True,
        "read_only": True,
        "download_performed": False,
        "action_count": len(actions),
        "rerun_hint": f"quant-us report minute-quality --data-root {data_root}",
        "actions": actions,
    }


def _normalize_symbols(values: Iterable[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        symbol = str(value or "").strip().upper()
        if symbol and symbol not in seen:
            seen.add(symbol)
            normalized.append(symbol)
    return normalized


def _normalize_bar_sizes(values: list[str] | tuple[str, ...]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    invalid: list[str] = []
    for value in values:
        bar_size = str(value or "").strip().lower()
        if not bar_size:
            continue
        if bar_size not in SUPPORTED_MINUTE_BAR_SIZES:
            invalid.append(bar_size)
            continue
        if bar_size in seen:
            continue
        seen.add(bar_size)
        normalized.append(bar_size)
    if invalid:
        raise ValueError(
            f"Unsupported minute bar sizes: {sorted(set(invalid))}. "
            f"Allowed values: {list(SUPPORTED_MINUTE_BAR_SIZES)}"
        )
    if not normalized:
        raise ValueError(
            f"At least one minute bar size is required. Allowed values: {list(SUPPORTED_MINUTE_BAR_SIZES)}"
        )
    return normalized


def _normalize_root_subdir(root_subdir: str) -> str:
    normalized = str(root_subdir or "").strip().lower()
    if normalized not in SUPPORTED_ROOT_SUBDIRS:
        raise ValueError(
            f"Unsupported root_subdir={root_subdir!r}. Allowed values: {list(SUPPORTED_ROOT_SUBDIRS)}"
        )
    return normalized


def _normalize_root_subdirs(root_subdirs: Iterable[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for root_subdir in root_subdirs:
        resolved = _normalize_root_subdir(root_subdir)
        if resolved not in seen:
            seen.add(resolved)
            normalized.append(resolved)
    if not normalized:
        raise ValueError(
            f"At least one root_subdir is required. Allowed values: {list(SUPPORTED_ROOT_SUBDIRS)}"
        )
    return normalized


def _worst_status(statuses: Iterable[str]) -> str:
    resolved = [str(status) for status in statuses]
    if not resolved:
        return "MISSING"
    return max(resolved, key=lambda value: _STATUS_RANK.get(value, 0))
