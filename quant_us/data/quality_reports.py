"""Six-category daily quality report generator for US equity bar data.

Each report is a frozen dataclass with:
  - report_type (str)
  - symbol     (str)
  - date       (date)           -- generation date
  - issues_found (int)
  - details    (list[dict])     -- per-issue detail rows

All six reports are bundled into a ``DataQualityReportSet`` that provides a
convenience method ``to_issues_list()`` suitable for appending to the
``DataManifest.issues`` field.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd

from quant_us.core.nyse_holidays import is_nyse_trading_day

# ---------------------------------------------------------------------------
# Individual report dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MissingBarsReport:
    """Trading days without a bar vs. the expected NYSE-trading-day calendar."""

    report_type: str = "missing_bars"
    symbol: str = ""
    date: date = date.today()
    issues_found: int = 0
    details: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class DuplicateBarsReport:
    """Timestamps that appear more than once in the data."""

    report_type: str = "duplicate_bars"
    symbol: str = ""
    date: date = date.today()
    issues_found: int = 0
    details: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class PriceJumpReport:
    """Bars whose open price differs >10 % from the previous bar's close."""

    report_type: str = "price_jump"
    symbol: str = ""
    date: date = date.today()
    issues_found: int = 0
    details: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class ZeroVolumeReport:
    """Bars where volume is zero or null."""

    report_type: str = "zero_volume"
    symbol: str = ""
    date: date = date.today()
    issues_found: int = 0
    details: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class SessionCoverageReport:
    """Count of bars broken down by session type (regular / pre_market /
    after_hours / closed)."""

    report_type: str = "session_coverage"
    symbol: str = ""
    date: date = date.today()
    issues_found: int = 0
    details: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class CorporateActionReport:
    """Suspected splits or reverse splits where day-over-day close ratio
    is >1.5 or <0.67."""

    report_type: str = "corporate_action"
    symbol: str = ""
    date: date = date.today()
    issues_found: int = 0
    details: list[dict[str, Any]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Aggregated report set
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DataQualityReportSet:
    """All six quality reports for a single symbol / date-range pair."""

    missing_bars: MissingBarsReport
    duplicate_bars: DuplicateBarsReport
    price_jump: PriceJumpReport
    zero_volume: ZeroVolumeReport
    session_coverage: SessionCoverageReport
    corporate_action: CorporateActionReport

    @property
    def total_issues(self) -> int:
        return sum(
            [
                self.missing_bars.issues_found,
                self.duplicate_bars.issues_found,
                self.price_jump.issues_found,
                self.zero_volume.issues_found,
                self.corporate_action.issues_found,
            ]
        )

    def to_issues_list(self) -> list[dict[str, Any]]:
        """Flatten all reports with issues into a list suitable for
        ``DataManifest.issues``."""
        issues: list[dict[str, Any]] = []
        for report in (
            self.missing_bars,
            self.duplicate_bars,
            self.price_jump,
            self.zero_volume,
            self.session_coverage,
            self.corporate_action,
        ):
            entry: dict[str, Any] = {
                "report_type": report.report_type,
                "symbol": report.symbol,
                "issues_found": report.issues_found,
            }
            if report.details:
                # Include first 10 details for context, but no more.
                entry["details"] = report.details[:10]
            issues.append(entry)
        return issues

    @property
    def has_issues(self) -> bool:
        return self.total_issues > 0


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _expected_trading_days(start: date, end: date) -> list[date]:
    """Return all NYSE trading days in *[start, end]* inclusive."""
    days: list[date] = []
    current = start
    while current <= end:
        if is_nyse_trading_day(current):
            days.append(current)
        current += timedelta(days=1)
    return days


def _ts_col(df: pd.DataFrame) -> str:
    return "timestamp_utc" if "timestamp_utc" in df.columns else "timestamp"


# ---------------------------------------------------------------------------
# Individual check functions
# ---------------------------------------------------------------------------


def _check_missing_bars(
    df: pd.DataFrame, symbol: str, report_date: date, date_range: tuple[date, date]
) -> MissingBarsReport:
    ts_col = _ts_col(df)
    if df.empty:
        all_expected = _expected_trading_days(date_range[0], date_range[1])
        return MissingBarsReport(
            symbol=symbol,
            date=report_date,
            issues_found=len(all_expected),
            details=[{"date": d.isoformat()} for d in all_expected],
        )

    timestamps = pd.to_datetime(df[ts_col], utc=True)
    actual_dates: set[date] = set(timestamps.dt.date.unique())

    expected = _expected_trading_days(date_range[0], date_range[1])
    missing = sorted([d for d in expected if d not in actual_dates])

    details = [{"date": d.isoformat()} for d in missing]
    return MissingBarsReport(
        symbol=symbol,
        date=report_date,
        issues_found=len(missing),
        details=details,
    )


def _check_duplicate_bars(
    df: pd.DataFrame, symbol: str, report_date: date
) -> DuplicateBarsReport:
    if df.empty:
        return DuplicateBarsReport(symbol=symbol, date=report_date)

    ts_col = _ts_col(df)
    timestamps = pd.to_datetime(df[ts_col], utc=True)
    dup_mask = timestamps.duplicated(keep=False)
    if not dup_mask.any():
        return DuplicateBarsReport(symbol=symbol, date=report_date)

    dup_timestamps = timestamps[dup_mask].unique()
    details: list[dict[str, Any]] = []
    for ts in dup_timestamps:
        count = int((timestamps == ts).sum())
        details.append(
            {"timestamp": ts.isoformat(), "count": count}
        )

    return DuplicateBarsReport(
        symbol=symbol,
        date=report_date,
        issues_found=len(dup_timestamps),
        details=details,
    )


def _check_price_jumps(
    df: pd.DataFrame, symbol: str, report_date: date
) -> PriceJumpReport:
    if df.empty or len(df) < 2:
        return PriceJumpReport(symbol=symbol, date=report_date)

    ts_col = _ts_col(df)
    sorted_df = df.sort_values(ts_col).reset_index(drop=True)
    prev_close = sorted_df["close"].shift(1)
    gap = (sorted_df["open"] - prev_close).abs() / prev_close
    jump_mask = gap > 0.10

    details: list[dict[str, Any]] = []
    for idx in sorted_df[jump_mask].index:
        ts_val = (
            sorted_df.loc[idx, ts_col].isoformat()
            if isinstance(sorted_df.loc[idx, ts_col], datetime)
            else str(sorted_df.loc[idx, ts_col])
        )
        prev_val = (
            float(prev_close.loc[idx])
            if pd.notna(prev_close.loc[idx])
            else None
        )
        details.append(
            {
                "timestamp": ts_val,
                "open": float(sorted_df.loc[idx, "open"]),
                "prev_close": prev_val,
                "gap_pct": round(float(gap.loc[idx] * 100), 2),
            }
        )

    return PriceJumpReport(
        symbol=symbol,
        date=report_date,
        issues_found=len(details),
        details=details,
    )


def _check_zero_volume(
    df: pd.DataFrame, symbol: str, report_date: date
) -> ZeroVolumeReport:
    if df.empty or "volume" not in df.columns:
        return ZeroVolumeReport(symbol=symbol, date=report_date)

    ts_col = _ts_col(df)
    zero_mask = df["volume"].fillna(0) == 0
    if not zero_mask.any():
        return ZeroVolumeReport(symbol=symbol, date=report_date)

    details: list[dict[str, Any]] = []
    for idx in df[zero_mask].index:
        ts_val = (
            df.loc[idx, ts_col].isoformat()
            if isinstance(df.loc[idx, ts_col], datetime)
            else str(df.loc[idx, ts_col])
        )
        vol_val = (
            float(df.loc[idx, "volume"])
            if pd.notna(df.loc[idx, "volume"])
            else None
        )
        details.append({"timestamp": ts_val, "volume": vol_val})

    return ZeroVolumeReport(
        symbol=symbol,
        date=report_date,
        issues_found=len(details),
        details=details,
    )


def _check_session_coverage(
    df: pd.DataFrame, symbol: str, report_date: date
) -> SessionCoverageReport:
    if df.empty or "session" not in df.columns:
        # If no session column yet, produce a single "untagged" detail.
        return SessionCoverageReport(
            symbol=symbol,
            date=report_date,
            issues_found=0,
            details=[{"session": "untagged", "count": len(df)}] if not df.empty else [],
        )

    counts = df["session"].value_counts().to_dict()
    details = [
        {"session": str(sess), "count": int(cnt)}
        for sess, cnt in counts.items()
    ]
    return SessionCoverageReport(
        symbol=symbol,
        date=report_date,
        issues_found=0,  # purely informational
        details=details,
    )


def _check_corporate_actions(
    df: pd.DataFrame, symbol: str, report_date: date
) -> CorporateActionReport:
    if df.empty or len(df) < 2:
        return CorporateActionReport(symbol=symbol, date=report_date)

    ts_col = _ts_col(df)
    sorted_df = df.sort_values(ts_col).reset_index(drop=True)
    ratio = sorted_df["close"] / sorted_df["close"].shift(1)
    action_mask = (ratio > 1.5) | (ratio < 0.67)

    details: list[dict[str, Any]] = []
    for idx in sorted_df[action_mask].index:
        if idx == 0:
            continue
        r = float(ratio.loc[idx])
        if r < 0.67:
            suspected = "split"
        elif r > 1.5:
            suspected = "reverse_split"
        else:
            suspected = "other"

        ts_val = (
            sorted_df.loc[idx, ts_col].isoformat()
            if isinstance(sorted_df.loc[idx, ts_col], datetime)
            else str(sorted_df.loc[idx, ts_col])
        )
        details.append(
            {
                "timestamp": ts_val,
                "close": float(sorted_df.loc[idx, "close"]),
                "prev_close": float(sorted_df.loc[idx - 1, "close"]),
                "ratio": round(r, 4),
                "suspected_action": suspected,
            }
        )

    return CorporateActionReport(
        symbol=symbol,
        date=report_date,
        issues_found=len(details),
        details=details,
    )


# ---------------------------------------------------------------------------
# Public entry-point
# ---------------------------------------------------------------------------


def generate_daily_quality_report(
    df: pd.DataFrame,
    symbol: str,
    date_range: tuple[date, date],
) -> DataQualityReportSet:
    """Run all six quality checks on *df* and return a ``DataQualityReportSet``.

    Parameters
    ----------
    df:
        OHLCV DataFrame.  Must contain at least a timestamp column
        (``timestamp_utc`` or ``timestamp``) plus ``open``, ``high``,
        ``low``, ``close``, and optionally ``volume`` / ``session``.
    symbol:
        Ticker symbol (for provenance).
    date_range:
        Inclusive ``(start, end)`` date range used to determine expected
        trading days for the *missing bars* report.
    """
    report_date = date.today()

    missing = _check_missing_bars(df, symbol, report_date, date_range)
    duplicates = _check_duplicate_bars(df, symbol, report_date)
    jumps = _check_price_jumps(df, symbol, report_date)
    zero_vol = _check_zero_volume(df, symbol, report_date)
    sessions = _check_session_coverage(df, symbol, report_date)
    corp = _check_corporate_actions(df, symbol, report_date)

    return DataQualityReportSet(
        missing_bars=missing,
        duplicate_bars=duplicates,
        price_jump=jumps,
        zero_volume=zero_vol,
        session_coverage=sessions,
        corporate_action=corp,
    )
