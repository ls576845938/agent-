"""Tests for the six-category daily quality report system.

Every test uses fully synthetic bar data and asserts the expected
``issues_found`` count and details structure.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import pandas as pd
import pytest

from quant_us.data.quality_reports import (
    CorporateActionReport,
    DataQualityReportSet,
    DuplicateBarsReport,
    MissingBarsReport,
    PriceJumpReport,
    SessionCoverageReport,
    ZeroVolumeReport,
    generate_daily_quality_report,
)


def _make_bars(
    timestamps: list[datetime],
    opens: list[float] | None = None,
    highs: list[float] | None = None,
    lows: list[float] | None = None,
    closes: list[float] | None = None,
    volumes: list[float] | None = None,
    sessions: list[str] | None = None,
) -> pd.DataFrame:
    """Build a synthetic OHLCV DataFrame."""
    n = len(timestamps)
    data: dict = {
        "timestamp_utc": timestamps,
        "open": opens or [100.0] * n,
        "high": highs or [101.0] * n,
        "low": lows or [99.0] * n,
        "close": closes or [100.5] * n,
        "volume": volumes or [1_000_000] * n,
    }
    if sessions is not None:
        data["session"] = sessions
    return pd.DataFrame(data)


# ---------------------------------------------------------------------------
# 1. Missing bars
# ---------------------------------------------------------------------------


def test_missing_bars_report() -> None:
    """5 consecutive trading days (Mon-Fri) but only 3 bars -> 2 missing."""
    # 2024-01-02 (Tue) through 2024-01-08 (Mon) spans 5 trading days.
    #   Tue 02, Wed 03, Thu 04, Fri 05, Mon 08  (weekend 06-07 skipped)
    timestamps = [
        datetime(2024, 1, 2, 14, 30, tzinfo=timezone.utc),  # Tue
        datetime(2024, 1, 3, 14, 30, tzinfo=timezone.utc),  # Wed
        datetime(2024, 1, 8, 14, 30, tzinfo=timezone.utc),  # Mon
    ]
    df = _make_bars(timestamps)
    report_set = generate_daily_quality_report(
        df, "SPY", (date(2024, 1, 2), date(2024, 1, 8))
    )

    report = report_set.missing_bars
    assert isinstance(report, MissingBarsReport)
    assert report.report_type == "missing_bars"
    assert report.symbol == "SPY"
    assert report.issues_found == 2, f"Expected 2 missing, got {report.issues_found}"
    assert len(report.details) == 2
    missing_dates = {d["date"] for d in report.details}
    assert "2024-01-04" in missing_dates  # Thu
    assert "2024-01-05" in missing_dates  # Fri


# ---------------------------------------------------------------------------
# 2. Duplicate bars
# ---------------------------------------------------------------------------


def test_duplicate_bars_report() -> None:
    """2 bars with the same timestamp -> 1 duplicate timestamp found."""
    ts = datetime(2024, 1, 3, 14, 30, tzinfo=timezone.utc)
    timestamps = [ts, ts, datetime(2024, 1, 4, 14, 30, tzinfo=timezone.utc)]
    df = _make_bars(timestamps)
    report_set = generate_daily_quality_report(
        df, "QQQ", (date(2024, 1, 3), date(2024, 1, 4))
    )

    report = report_set.duplicate_bars
    assert isinstance(report, DuplicateBarsReport)
    assert report.report_type == "duplicate_bars"
    assert report.symbol == "QQQ"
    assert report.issues_found == 1, f"Expected 1 duplicate, got {report.issues_found}"
    assert len(report.details) == 1
    assert report.details[0]["count"] == 2


# ---------------------------------------------------------------------------
# 3. Price jump
# ---------------------------------------------------------------------------


def test_price_jump_report_detected() -> None:
    """Bar with a >10 % open gap from previous close -> detected."""
    timestamps = [
        datetime(2024, 1, 3, 14, 30, tzinfo=timezone.utc),
        datetime(2024, 1, 4, 14, 30, tzinfo=timezone.utc),
    ]
    # Prev close = 100.5, next open = 120.0  -> gap ~19.4 %
    df = _make_bars(
        timestamps,
        opens=[100.0, 120.0],
        closes=[100.5, 119.0],
    )
    report_set = generate_daily_quality_report(
        df, "AAPL", (date(2024, 1, 3), date(2024, 1, 4))
    )

    report = report_set.price_jump
    assert isinstance(report, PriceJumpReport)
    assert report.report_type == "price_jump"
    assert report.symbol == "AAPL"
    assert report.issues_found == 1, f"Expected 1 jump, got {report.issues_found}"
    assert len(report.details) == 1
    assert report.details[0]["gap_pct"] > 10.0


def test_price_jump_report_clean() -> None:
    """No bars with >10 % gap -> zero issues."""
    timestamps = [
        datetime(2024, 1, 3, 14, 30, tzinfo=timezone.utc),
        datetime(2024, 1, 4, 14, 30, tzinfo=timezone.utc),
    ]
    df = _make_bars(timestamps, closes=[100.0, 101.0], opens=[99.5, 100.5])
    report_set = generate_daily_quality_report(
        df, "AAPL", (date(2024, 1, 3), date(2024, 1, 4))
    )
    assert report_set.price_jump.issues_found == 0


# ---------------------------------------------------------------------------
# 4. Zero volume
# ---------------------------------------------------------------------------


def test_zero_volume_report() -> None:
    """Bar with volume=0 -> detected."""
    timestamps = [
        datetime(2024, 1, 3, 14, 30, tzinfo=timezone.utc),
        datetime(2024, 1, 4, 14, 30, tzinfo=timezone.utc),
    ]
    df = _make_bars(timestamps, volumes=[1_000_000, 0])
    report_set = generate_daily_quality_report(
        df, "MSFT", (date(2024, 1, 3), date(2024, 1, 4))
    )

    report = report_set.zero_volume
    assert isinstance(report, ZeroVolumeReport)
    assert report.report_type == "zero_volume"
    assert report.symbol == "MSFT"
    assert report.issues_found == 1, f"Expected 1 zero-vol bar, got {report.issues_found}"
    assert len(report.details) == 1
    assert report.details[0]["volume"] == 0.0


def test_zero_volume_report_clean() -> None:
    """All bars have positive volume -> zero issues."""
    timestamps = [
        datetime(2024, 1, 3, 14, 30, tzinfo=timezone.utc),
        datetime(2024, 1, 4, 14, 30, tzinfo=timezone.utc),
    ]
    df = _make_bars(timestamps, volumes=[500_000, 1_200_000])
    report_set = generate_daily_quality_report(
        df, "MSFT", (date(2024, 1, 3), date(2024, 1, 4))
    )
    assert report_set.zero_volume.issues_found == 0


# ---------------------------------------------------------------------------
# 5. Session coverage
# ---------------------------------------------------------------------------


def test_session_coverage_report() -> None:
    """Bars tagged with session labels -> counts per session."""
    timestamps = [
        datetime(2024, 1, 3, 8, 0, tzinfo=timezone.utc),    # pre_market ET
        datetime(2024, 1, 3, 14, 30, tzinfo=timezone.utc),  # regular ET
        datetime(2024, 1, 3, 14, 31, tzinfo=timezone.utc),  # regular ET
        datetime(2024, 1, 3, 21, 0, tzinfo=timezone.utc),   # after_hours ET
    ]
    df = _make_bars(
        timestamps,
        sessions=["pre_market", "regular", "regular", "after_hours"],
    )
    report_set = generate_daily_quality_report(
        df, "IWM", (date(2024, 1, 3), date(2024, 1, 3))
    )

    report = report_set.session_coverage
    assert isinstance(report, SessionCoverageReport)
    assert report.report_type == "session_coverage"
    assert report.symbol == "IWM"
    # sessions field is informational, issues_found stays 0
    assert report.issues_found == 0

    counts = {d["session"]: d["count"] for d in report.details}
    assert counts.get("regular") == 2, f"expected 2 regular bars: {counts}"
    assert counts.get("pre_market") == 1, f"expected 1 pre_market bar: {counts}"
    assert counts.get("after_hours") == 1, f"expected 1 after_hours bar: {counts}"


def test_session_coverage_untagged() -> None:
    """DataFrame without session column -> 'untagged' detail."""
    timestamps = [datetime(2024, 1, 3, 14, 30, tzinfo=timezone.utc)]
    df = _make_bars(timestamps)  # no session column
    report_set = generate_daily_quality_report(
        df, "IWM", (date(2024, 1, 3), date(2024, 1, 3))
    )
    assert report_set.session_coverage.issues_found == 0
    assert len(report_set.session_coverage.details) == 1
    assert report_set.session_coverage.details[0]["session"] == "untagged"


# ---------------------------------------------------------------------------
# 6. Corporate action (simulated split)
# ---------------------------------------------------------------------------


def test_corporate_action_split() -> None:
    """Simulated 2:1 split where close halves -> detected."""
    timestamps = [
        datetime(2024, 1, 3, 14, 30, tzinfo=timezone.utc),
        datetime(2024, 1, 4, 14, 30, tzinfo=timezone.utc),  # split day
    ]
    # Prev close = 200, next close = 100  -> ratio = 0.5 (< 0.67)
    df = _make_bars(timestamps, closes=[200.0, 100.0])
    report_set = generate_daily_quality_report(
        df, "NVDA", (date(2024, 1, 3), date(2024, 1, 4))
    )

    report = report_set.corporate_action
    assert isinstance(report, CorporateActionReport)
    assert report.report_type == "corporate_action"
    assert report.symbol == "NVDA"
    assert report.issues_found == 1, f"Expected 1 corp action, got {report.issues_found}"
    assert len(report.details) == 1
    assert report.details[0]["suspected_action"] == "split"
    assert report.details[0]["ratio"] == 0.5


def test_corporate_action_reverse_split() -> None:
    """Simulated reverse split (close jumps >1.5x) -> detected."""
    timestamps = [
        datetime(2024, 1, 3, 14, 30, tzinfo=timezone.utc),
        datetime(2024, 1, 4, 14, 30, tzinfo=timezone.utc),
    ]
    df = _make_bars(timestamps, closes=[50.0, 150.0])  # ratio = 3.0 > 1.5
    report_set = generate_daily_quality_report(
        df, "NVDA", (date(2024, 1, 3), date(2024, 1, 4))
    )
    assert report_set.corporate_action.issues_found == 1
    assert report_set.corporate_action.details[0]["suspected_action"] == "reverse_split"


def test_corporate_action_no_event() -> None:
    """Normal price movement -> no detection."""
    timestamps = [
        datetime(2024, 1, 3, 14, 30, tzinfo=timezone.utc),
        datetime(2024, 1, 4, 14, 30, tzinfo=timezone.utc),
    ]
    df = _make_bars(timestamps, closes=[100.0, 102.0])
    report_set = generate_daily_quality_report(
        df, "NVDA", (date(2024, 1, 3), date(2024, 1, 4))
    )
    assert report_set.corporate_action.issues_found == 0


# ---------------------------------------------------------------------------
# Aggregated set behaviour
# ---------------------------------------------------------------------------


def test_quality_report_set_aggregation() -> None:
    """DataQualityReportSet wraps all 6 reports correctly."""
    ts = datetime(2024, 1, 3, 14, 30, tzinfo=timezone.utc)
    df = _make_bars([ts])
    report_set = generate_daily_quality_report(
        df, "TEST", (date(2024, 1, 3), date(2024, 1, 3))
    )

    assert isinstance(report_set, DataQualityReportSet)
    assert isinstance(report_set.missing_bars, MissingBarsReport)
    assert isinstance(report_set.duplicate_bars, DuplicateBarsReport)
    assert isinstance(report_set.price_jump, PriceJumpReport)
    assert isinstance(report_set.zero_volume, ZeroVolumeReport)
    assert isinstance(report_set.session_coverage, SessionCoverageReport)
    assert isinstance(report_set.corporate_action, CorporateActionReport)
    # total_issues should be >= 0
    assert report_set.total_issues >= 0


def test_to_issues_list_flat() -> None:
    """to_issues_list() returns exactly 6 entries with expected keys."""
    ts = datetime(2024, 1, 3, 14, 30, tzinfo=timezone.utc)
    df = _make_bars([ts])
    report_set = generate_daily_quality_report(
        df, "TEST", (date(2024, 1, 3), date(2024, 1, 3))
    )

    issues = report_set.to_issues_list()
    assert len(issues) == 6
    types_found = {e["report_type"] for e in issues}
    assert types_found == {
        "missing_bars",
        "duplicate_bars",
        "price_jump",
        "zero_volume",
        "session_coverage",
        "corporate_action",
    }


def test_has_issues_property() -> None:
    """has_issues True when any report has issues_found > 0."""
    # Deliberately create data with a zero-volume bar.
    timestamps = [
        datetime(2024, 1, 3, 14, 30, tzinfo=timezone.utc),
        datetime(2024, 1, 4, 14, 30, tzinfo=timezone.utc),
    ]
    df = _make_bars(timestamps, volumes=[0, 0])
    report_set = generate_daily_quality_report(
        df, "TEST", (date(2024, 1, 3), date(2024, 1, 4))
    )
    assert report_set.has_issues is True


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_empty_dataframe() -> None:
    """Empty DataFrame produces zero-issue reports (except missing bars)."""
    df = pd.DataFrame()
    report_set = generate_daily_quality_report(
        df, "EMPTY", (date(2024, 1, 2), date(2024, 1, 5))
    )
    assert report_set.duplicate_bars.issues_found == 0
    assert report_set.price_jump.issues_found == 0
    assert report_set.zero_volume.issues_found == 0
    assert report_set.session_coverage.issues_found == 0
    assert report_set.session_coverage.details == []
    assert report_set.corporate_action.issues_found == 0
    # missing bars should still report the expected trading days
    assert report_set.missing_bars.issues_found > 0


def test_single_bar() -> None:
    """Single bar cannot produce price-jump or corp-action issues."""
    ts = datetime(2024, 1, 3, 14, 30, tzinfo=timezone.utc)
    df = _make_bars([ts])
    report_set = generate_daily_quality_report(
        df, "SINGLE", (date(2024, 1, 3), date(2024, 1, 3))
    )
    assert report_set.price_jump.issues_found == 0
    assert report_set.corporate_action.issues_found == 0
