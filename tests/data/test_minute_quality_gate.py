from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from quant_us.core.clock import UTC
from quant_us.core.calendar import USEquityCalendar
from quant_us.data.minute_quality_gate import (
    _expected_regular_timestamps,
    inspect_minute_data_quality,
    inspect_minute_data_quality_overview,
)


def _write_minute_partition(
    data_root: Path,
    *,
    root_subdir: str = "raw",
    symbol: str,
    bar_size: str,
    trading_day: str,
    timestamps: list[datetime],
    open_values: list[float] | None = None,
    high_values: list[float] | None = None,
    low_values: list[float] | None = None,
    close_values: list[float] | None = None,
    volume_values: list[float] | None = None,
) -> None:
    path = (
        data_root
        / root_subdir
        / "vendor=yfinance"
        / "asset_class=equity"
        / f"bar_size={bar_size}"
        / f"symbol={symbol}"
        / f"date={trading_day}.parquet"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(
        {
            "timestamp_utc": timestamps,
            "symbol": [symbol] * len(timestamps),
            "open": open_values or [100.0] * len(timestamps),
            "high": high_values or [101.0] * len(timestamps),
            "low": low_values or [99.0] * len(timestamps),
            "close": close_values or [100.5] * len(timestamps),
            "volume": volume_values or [1_000] * len(timestamps),
        }
    )
    frame.to_parquet(path, index=False)


def test_minute_quality_passes_for_complete_1m_5m_15m_data(tmp_path: Path) -> None:
    calendar = USEquityCalendar.with_holidays()
    trading_day = datetime(2026, 5, 8, tzinfo=UTC).date()
    for bar_size in ("1m", "5m", "15m"):
        interval = int(bar_size.removesuffix("m"))
        timestamps = _expected_regular_timestamps(trading_day, interval, calendar)
        _write_minute_partition(
            tmp_path,
            symbol="AAPL",
            bar_size=bar_size,
            trading_day=trading_day.isoformat(),
            timestamps=timestamps,
        )

    report = inspect_minute_data_quality(
        tmp_path,
        symbols=["AAPL"],
        lookback_trading_days=1,
        as_of=datetime(2026, 5, 8, 21, 0, tzinfo=UTC),
    )

    assert report.status == "PASS"
    assert report.issue_count == 0
    intervals = {interval.bar_size: interval for interval in report.symbols[0].intervals}
    assert intervals["1m"].observed_bars == 390
    assert intervals["5m"].observed_bars == 78
    assert intervals["15m"].observed_bars == 26
    assert all(interval.status == "PASS" for interval in intervals.values())
    assert all(interval.coverage_pct == 100.0 for interval in intervals.values())
    assert all(interval.session_coverage[0]["coverage_pct"] == 100.0 for interval in intervals.values())


def test_minute_quality_flags_missing_files_and_missing_bars(tmp_path: Path) -> None:
    calendar = USEquityCalendar.with_holidays()
    day_one = datetime(2026, 5, 7, tzinfo=UTC).date()
    day_two = datetime(2026, 5, 8, tzinfo=UTC).date()

    partial_1m = _expected_regular_timestamps(day_two, 1, calendar)[5:]
    full_15m = _expected_regular_timestamps(day_two, 15, calendar)
    _write_minute_partition(
        tmp_path,
        symbol="MSFT",
        bar_size="1m",
        trading_day=day_two.isoformat(),
        timestamps=partial_1m,
    )
    _write_minute_partition(
        tmp_path,
        symbol="MSFT",
        bar_size="15m",
        trading_day=day_two.isoformat(),
        timestamps=full_15m,
    )

    report = inspect_minute_data_quality(
        tmp_path,
        symbols=["MSFT"],
        lookback_trading_days=2,
        as_of=datetime(2026, 5, 8, 21, 0, tzinfo=UTC),
    )

    assert report.status == "MISSING"
    symbol = report.symbols[0]
    intervals = {interval.bar_size: interval for interval in symbol.intervals}

    one_minute = intervals["1m"]
    assert one_minute.status == "FAIL"
    assert day_one.isoformat() in one_minute.missing_file_dates
    assert one_minute.missing_bar_count > 0
    assert one_minute.coverage_pct < 100.0

    five_minute = intervals["5m"]
    assert five_minute.status == "MISSING"
    assert five_minute.observed_bars == 0
    assert set(five_minute.missing_file_dates) == {day_one.isoformat(), day_two.isoformat()}

    fifteen_minute = intervals["15m"]
    assert fifteen_minute.status == "FAIL"
    assert fifteen_minute.missing_file_dates == [day_one.isoformat()]


def test_minute_quality_allows_same_timestamp_across_different_symbols(tmp_path: Path) -> None:
    calendar = USEquityCalendar.with_holidays()
    trading_day = datetime(2026, 5, 8, tzinfo=UTC).date()
    timestamps = _expected_regular_timestamps(trading_day, 1, calendar)
    for symbol in ("AAPL", "MSFT"):
        _write_minute_partition(
            tmp_path,
            symbol=symbol,
            bar_size="1m",
            trading_day=trading_day.isoformat(),
            timestamps=timestamps,
        )

    report = inspect_minute_data_quality(
        tmp_path,
        symbols=["AAPL", "MSFT"],
        bar_sizes=["1m"],
        lookback_trading_days=1,
        as_of=datetime(2026, 5, 8, 21, 0, tzinfo=UTC),
    )

    assert report.status == "PASS"
    assert [symbol.status for symbol in report.symbols] == ["PASS", "PASS"]
    assert all(
        interval.duplicate_timestamp_count == 0
        for symbol in report.symbols
        for interval in symbol.intervals
    )


def test_minute_quality_blocks_conflicting_duplicates_and_invalid_ohlc(tmp_path: Path) -> None:
    calendar = USEquityCalendar.with_holidays()
    trading_day = datetime(2026, 5, 8, tzinfo=UTC).date()
    timestamps = _expected_regular_timestamps(trading_day, 1, calendar)
    first = timestamps[0]
    corrupt_timestamps = [first, first, timestamps[1], timestamps[2]]
    _write_minute_partition(
        tmp_path,
        symbol="AAPL",
        bar_size="1m",
        trading_day=trading_day.isoformat(),
        timestamps=corrupt_timestamps,
        open_values=[100.0, 100.0, 0.0, 100.0],
        high_values=[101.0, 102.0, 101.0, 99.0],
        low_values=[99.0, 99.0, 99.0, 100.0],
        close_values=[100.5, 101.5, 100.5, 100.5],
        volume_values=[1_000, 1_000, 1_000, -1],
    )

    report = inspect_minute_data_quality(
        tmp_path,
        symbols=["AAPL"],
        bar_sizes=["1m"],
        lookback_trading_days=1,
        as_of=datetime(2026, 5, 8, 21, 0, tzinfo=UTC),
    )

    interval = report.symbols[0].intervals[0]
    assert report.status == "FAIL"
    assert interval.status == "FAIL"
    assert interval.duplicate_timestamp_count == 2
    assert interval.conflicting_duplicate_count == 1
    assert interval.non_positive_price_count == 1
    assert interval.non_positive_count == 2
    assert interval.invalid_ohlc_count == 1
    assert interval.negative_volume_count == 1
    assert interval.zero_volume_count == 0


def test_minute_quality_warns_for_small_regular_session_gap_and_zero_volume(tmp_path: Path) -> None:
    calendar = USEquityCalendar.with_holidays()
    trading_day = datetime(2026, 5, 8, tzinfo=UTC).date()
    timestamps = _expected_regular_timestamps(trading_day, 1, calendar)
    _write_minute_partition(
        tmp_path,
        symbol="AAPL",
        bar_size="1m",
        trading_day=trading_day.isoformat(),
        timestamps=timestamps[1:],
        volume_values=[0] + [1_000] * (len(timestamps) - 2),
    )

    report = inspect_minute_data_quality(
        tmp_path,
        symbols=["AAPL"],
        bar_sizes=["1m"],
        lookback_trading_days=1,
        as_of=datetime(2026, 5, 8, 21, 0, tzinfo=UTC),
    )

    interval = report.symbols[0].intervals[0]
    assert report.status == "WARN"
    assert interval.status == "WARN"
    assert interval.coverage_pct > 99.0
    assert interval.missing_bars == 1
    assert interval.zero_volume == 1
    assert "missing_bars:1" in interval.gate_reasons
    assert "zero_volume:1" in interval.gate_reasons


def test_minute_quality_overview_audits_raw_and_cleaned_roots(tmp_path: Path) -> None:
    calendar = USEquityCalendar.with_holidays()
    trading_day = datetime(2026, 5, 8, tzinfo=UTC).date()
    raw_timestamps = _expected_regular_timestamps(trading_day, 1, calendar)[1:]
    clean_timestamps = _expected_regular_timestamps(trading_day, 1, calendar)
    _write_minute_partition(
        tmp_path,
        root_subdir="raw",
        symbol="AAPL",
        bar_size="1m",
        trading_day=trading_day.isoformat(),
        timestamps=raw_timestamps,
    )
    _write_minute_partition(
        tmp_path,
        root_subdir="cleaned",
        symbol="AAPL",
        bar_size="1m",
        trading_day=trading_day.isoformat(),
        timestamps=clean_timestamps,
    )

    report = inspect_minute_data_quality_overview(
        tmp_path,
        symbols=["AAPL"],
        bar_sizes=["1m"],
        lookback_trading_days=1,
        as_of=datetime(2026, 5, 8, 21, 0, tzinfo=UTC),
    )

    assert report.status == "WARN"
    assert report.evaluated_symbols == ["AAPL"]
    dataset_statuses = {dataset.root_subdir: dataset.status for dataset in report.datasets}
    assert dataset_statuses == {"raw": "WARN", "cleaned": "PASS"}
    assert report.evidence_summary["bar_size_summary"]["1m"]["status"] == "WARN"
    assert report.remediation_summary["download_performed"] is False
    assert report.remediation_summary["actions"][0]["category"] == "coverage"


def test_minute_quality_overview_reports_placeholder_layout_without_silent_pass(tmp_path: Path) -> None:
    dataset_root = tmp_path / "raw" / "vendor=yfinance" / "asset_class=equity"
    for bar_size in ("1m", "5m", "15m"):
        (dataset_root / f"bar_size={bar_size}").mkdir(parents=True, exist_ok=True)

    report = inspect_minute_data_quality_overview(
        tmp_path,
        bar_sizes=["1m", "5m", "15m"],
        lookback_trading_days=1,
        as_of=datetime(2026, 5, 8, 21, 0, tzinfo=UTC),
    )

    assert report.status == "MISSING"
    assert report.audit_scope["data_source"] == "yfinance"
    assert report.audit_scope["calendar_name"] == "NYSE"
    assert report.audit_scope["storage_timezone"] == "UTC"
    raw_layout = next(item for item in report.dataset_discovery if item["root_subdir"] == "raw")
    assert raw_layout["placeholder_structure_detected"] is True
    assert raw_layout["present_bar_sizes"] == ["1m", "5m", "15m"]
    assert raw_layout["discovered_symbol_count"] == 0
    assert raw_layout["partition_file_count"] == 0
    assert report.remediation_summary["action_count"] >= 1
    coverage_actions = [
        action for action in report.remediation_summary["actions"] if action["category"] == "coverage"
    ]
    assert coverage_actions
    assert coverage_actions[0]["recommended_commands"]
    assert "ingest_intraday.py" in coverage_actions[0]["recommended_commands"][0]
    assert "quant-us report minute-quality" in coverage_actions[0]["recommended_commands"][-1]
    assert "--symbol SPY" in coverage_actions[0]["recommended_commands"][0]
    assert "--end 2026-05-12T00:00:00Z" in coverage_actions[0]["recommended_commands"][0]


def test_minute_quality_overview_resolves_project_root_to_nested_data_directory(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    calendar = USEquityCalendar.with_holidays()
    trading_day = datetime(2026, 5, 8, tzinfo=UTC).date()
    for bar_size in ("1m", "5m", "15m"):
        interval = int(bar_size.removesuffix("m"))
        timestamps = _expected_regular_timestamps(trading_day, interval, calendar)
        for root_subdir in ("raw", "cleaned"):
            _write_minute_partition(
                data_root,
                root_subdir=root_subdir,
                symbol="SPY",
                bar_size=bar_size,
                trading_day=trading_day.isoformat(),
                timestamps=timestamps,
            )

    report = inspect_minute_data_quality_overview(
        tmp_path,
        symbols=["SPY"],
        lookback_trading_days=1,
        as_of=datetime(2026, 5, 8, 21, 0, tzinfo=UTC),
    )

    assert report.status == "PASS"
    assert report.data_root == str(data_root)
    assert report.requested_data_root == str(tmp_path)
    assert report.resolved_data_root == str(data_root)
    assert report.data_root_resolution["resolution_mode"] == "project_root_data_subdir"
    assert report.data_root_resolution["nested_data_subdir_used"] is True


def test_minute_quality_remediation_uses_affected_symbol_and_inclusive_missing_day_window(tmp_path: Path) -> None:
    calendar = USEquityCalendar.with_holidays()
    trading_day = datetime(2026, 5, 8, tzinfo=UTC).date()
    for bar_size in ("1m", "5m", "15m"):
        interval = int(bar_size.removesuffix("m"))
        timestamps = _expected_regular_timestamps(trading_day, interval, calendar)
        _write_minute_partition(
            tmp_path,
            symbol="SPY",
            bar_size=bar_size,
            trading_day=trading_day.isoformat(),
            timestamps=timestamps,
        )

    report = inspect_minute_data_quality(
        tmp_path,
        symbols=["SPY"],
        lookback_trading_days=2,
        as_of=datetime(2026, 5, 11, 22, 0, tzinfo=UTC),
    )

    coverage_actions = [
        action for action in report.remediation_summary["actions"] if action["category"] == "coverage"
    ]
    assert coverage_actions
    commands = coverage_actions[0]["recommended_commands"]
    assert any("--symbol SPY --bar-size 1m" in command for command in commands)
    assert any("--symbol SPY --bar-size 5m" in command for command in commands)
    assert any("--symbol SPY --bar-size 15m" in command for command in commands)
    assert any("--start 2026-05-11T00:00:00Z --end 2026-05-12T00:00:00Z" in command for command in commands)


def test_minute_quality_classifies_timezone_session_and_early_close(tmp_path: Path) -> None:
    calendar = USEquityCalendar.with_holidays()
    trading_day = datetime(2026, 11, 27, tzinfo=UTC).date()
    assert calendar.is_early_close(trading_day)

    one_minute = _expected_regular_timestamps(trading_day, 1, calendar)
    one_minute_naive = [timestamp.replace(tzinfo=None) for timestamp in one_minute]
    one_minute_naive.append((one_minute[-1] + timedelta(minutes=2)).replace(tzinfo=None))
    five_minute = [
        timestamp.astimezone(timezone(timedelta(hours=-5)))
        for timestamp in _expected_regular_timestamps(trading_day, 5, calendar)
    ]
    fifteen_minute = _expected_regular_timestamps(trading_day, 15, calendar)

    _write_minute_partition(
        tmp_path,
        symbol="AAPL",
        bar_size="1m",
        trading_day=trading_day.isoformat(),
        timestamps=one_minute_naive,
    )
    _write_minute_partition(
        tmp_path,
        symbol="AAPL",
        bar_size="5m",
        trading_day=trading_day.isoformat(),
        timestamps=five_minute,
    )
    _write_minute_partition(
        tmp_path,
        symbol="AAPL",
        bar_size="15m",
        trading_day=trading_day.isoformat(),
        timestamps=fifteen_minute,
    )

    report = inspect_minute_data_quality(
        tmp_path,
        symbols=["AAPL"],
        lookback_trading_days=1,
        as_of=datetime(2026, 11, 27, 19, 0, tzinfo=UTC),
    )

    intervals = {interval.bar_size: interval for interval in report.symbols[0].intervals}
    one_minute_interval = intervals["1m"]
    five_minute_interval = intervals["5m"]
    fifteen_minute_interval = intervals["15m"]

    assert report.status == "FAIL"
    assert one_minute_interval.quality_dimensions["timezone_session"]["status"] == "FAIL"
    assert one_minute_interval.timezone_naive_count == len(one_minute_naive)
    assert one_minute_interval.outside_session_count == 0
    assert one_minute_interval.extended_session_count == 1
    assert one_minute_interval.session_coverage[0]["session_type"] == "early_close"
    assert one_minute_interval.session_coverage[0]["is_early_close"] is True
    assert one_minute_interval.session_coverage[0]["expected_bars"] == 210
    assert one_minute_interval.coverage_pct == 100.0

    assert five_minute_interval.quality_dimensions["timezone_session"]["status"] == "FAIL"
    assert five_minute_interval.timezone_non_utc_count == len(five_minute)
    assert five_minute_interval.outside_session_count == 0

    assert fifteen_minute_interval.status == "PASS"
    assert report.evidence_summary["bar_size_summary"]["1m"]["status"] == "FAIL"
    assert report.evidence_summary["bar_size_summary"]["5m"]["status"] == "FAIL"
    assert report.evidence_summary["bar_size_summary"]["15m"]["status"] == "PASS"
    assert report.evidence_summary["session_totals"]["early_close_days"] == 3
    assert any(
        action["category"] == "timezone_session"
        for action in report.remediation_summary["actions"]
    )


def test_minute_quality_warns_for_valid_extended_session_rows(tmp_path: Path) -> None:
    calendar = USEquityCalendar.with_holidays()
    trading_day = datetime(2026, 5, 8, tzinfo=UTC).date()
    timestamps = _expected_regular_timestamps(trading_day, 1, calendar)
    extended = [
        datetime(2026, 5, 8, 8, 0, tzinfo=UTC),
        datetime(2026, 5, 8, 23, 59, tzinfo=UTC),
    ]
    _write_minute_partition(
        tmp_path,
        symbol="AAPL",
        bar_size="1m",
        trading_day=trading_day.isoformat(),
        timestamps=[*extended, *timestamps],
    )

    report = inspect_minute_data_quality(
        tmp_path,
        symbols=["AAPL"],
        bar_sizes=["1m"],
        lookback_trading_days=1,
        as_of=datetime(2026, 5, 8, 21, 0, tzinfo=UTC),
    )

    interval = report.symbols[0].intervals[0]
    assert report.status == "WARN"
    assert interval.status == "WARN"
    assert interval.coverage_pct == 100.0
    assert interval.outside_session_count == 0
    assert interval.extended_session_count == 2
    assert interval.quality_dimensions["timezone_session"]["status"] == "WARN"
    assert "extended_session:2" in interval.gate_reasons
    assert report.evidence_summary["category_totals"]["extended_session_rows"] == 2


def test_minute_quality_fails_for_true_outside_extended_session_rows(tmp_path: Path) -> None:
    calendar = USEquityCalendar.with_holidays()
    trading_day = datetime(2026, 5, 8, tzinfo=UTC).date()
    timestamps = _expected_regular_timestamps(trading_day, 1, calendar)
    _write_minute_partition(
        tmp_path,
        symbol="AAPL",
        bar_size="1m",
        trading_day=trading_day.isoformat(),
        timestamps=[*timestamps, datetime(2026, 5, 9, 0, 30, tzinfo=UTC)],
    )

    report = inspect_minute_data_quality(
        tmp_path,
        symbols=["AAPL"],
        bar_sizes=["1m"],
        lookback_trading_days=1,
        as_of=datetime(2026, 5, 8, 21, 0, tzinfo=UTC),
    )

    interval = report.symbols[0].intervals[0]
    assert report.status == "FAIL"
    assert interval.status == "FAIL"
    assert interval.coverage_pct == 100.0
    assert interval.outside_session_count == 1
    assert interval.extended_session_count == 0
    assert interval.quality_dimensions["timezone_session"]["status"] == "FAIL"


def test_minute_quality_rejects_invalid_inputs_instead_of_silent_fallback(tmp_path: Path) -> None:
    as_of = datetime(2026, 5, 8, 21, 0, tzinfo=UTC)

    try:
        inspect_minute_data_quality(
            tmp_path,
            symbols=["AAPL"],
            bar_sizes=["2m"],
            lookback_trading_days=1,
            as_of=as_of,
        )
    except ValueError as exc:
        assert "Unsupported minute bar sizes" in str(exc)
    else:
        raise AssertionError("expected invalid bar_sizes to raise ValueError")

    try:
        inspect_minute_data_quality_overview(
            tmp_path,
            symbols=["AAPL"],
            bar_sizes=["1m"],
            lookback_trading_days=1,
            as_of=as_of,
            root_subdirs=["archive"],
        )
    except ValueError as exc:
        assert "Unsupported root_subdir" in str(exc)
    else:
        raise AssertionError("expected invalid root_subdirs to raise ValueError")
