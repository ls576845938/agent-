"""Tests for YAML-based market session configuration."""

from __future__ import annotations

from datetime import date, datetime, time, timezone

import pytest
import yaml

from quant_us.core.calendar import (
    USEquityCalendar,
    SessionConfig,
    SessionName,
    SessionRule,
    load_sessions_from_yaml,
)
from quant_us.core.clock import to_et

YAML_PATH = "config/market_sessions.yaml"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _et_dt(y: int, m: int, d: int, h: int, mi: int = 0) -> datetime:
    """Build an ET-aware datetime for the given wall-clock time.

    The returned datetime carries ``America/New_York`` tzinfo so that
    ``SessionRule.contains()`` (which calls ``.time()`` directly) sees
    the correct wall-clock time.
    """
    from zoneinfo import ZoneInfo
    et = ZoneInfo("America/New_York")
    return datetime(y, m, d, h, mi, tzinfo=et)


# ---------------------------------------------------------------------------
# Tests: load_sessions_from_yaml
# ---------------------------------------------------------------------------

class TestLoadSessionsFromYaml:
    """Verify the YAML parser produces correct SessionConfig + SessionRules."""

    def test_returns_correct_types(self):
        config, rules, early_close_time = load_sessions_from_yaml(YAML_PATH)
        assert isinstance(config, SessionConfig)
        assert isinstance(rules, list)
        assert len(rules) == 4
        assert isinstance(early_close_time, time)

    def test_session_order_preserved(self):
        _, rules, _ = load_sessions_from_yaml(YAML_PATH)
        names = [r.name for r in rules]
        assert names == [
            SessionName.PRE_MARKET,
            SessionName.REGULAR,
            SessionName.AFTER_HOURS,
            SessionName.OVERNIGHT,
        ]

    def test_regular_session_allows_trading(self):
        _, rules, _ = load_sessions_from_yaml(YAML_PATH)
        regular = next(r for r in rules if r.name == SessionName.REGULAR)
        assert regular.enabled is True

    def test_non_regular_sessions_disallow_trading(self):
        _, rules, _ = load_sessions_from_yaml(YAML_PATH)
        for r in rules:
            if r.name != SessionName.REGULAR:
                assert r.enabled is False, f"{r.name} should have allow_trading=False"

    def test_early_close_time_is_configurable(self):
        _, _, early_close_time = load_sessions_from_yaml(YAML_PATH)
        assert early_close_time == time(13, 0)

    def test_all_times_parsed_correctly(self):
        _, rules, _ = load_sessions_from_yaml(YAML_PATH)
        expected = {
            SessionName.PRE_MARKET: (time(4, 0), time(9, 30)),
            SessionName.REGULAR: (time(9, 30), time(16, 0)),
            SessionName.AFTER_HOURS: (time(16, 0), time(20, 0)),
            SessionName.OVERNIGHT: (time(21, 0), time(4, 0)),
        }
        for rule in rules:
            exp_start, exp_end = expected[rule.name]
            assert rule.start_et == exp_start, f"{rule.name} start mismatch"
            assert rule.end_et == exp_end, f"{rule.name} end mismatch"

    def test_invalid_yaml_path_raises(self):
        with pytest.raises(FileNotFoundError):
            load_sessions_from_yaml("/nonexistent/path.yaml")


# ---------------------------------------------------------------------------
# Tests: USEquityCalendar.from_yaml
# ---------------------------------------------------------------------------

class TestFromYaml:
    """Verify the from_yaml classmethod builds a working calendar."""

    def test_from_yaml_creates_calendar(self):
        cal = USEquityCalendar.from_yaml(YAML_PATH)
        assert isinstance(cal, USEquityCalendar)
        assert len(cal.rules) == 4

    def test_from_yaml_sessions_no_holidays(self):
        cal = USEquityCalendar.from_yaml(YAML_PATH)
        # No holiday data loaded by from_yaml
        assert len(cal.holidays) == 0
        assert len(cal.early_closes) == 0

    def test_regular_session_returns_regular(self):
        cal = USEquityCalendar.from_yaml(YAML_PATH)
        # 2026-05-04 is a Monday, 10:30 ET is regular hours
        ts = _et_dt(2026, 5, 4, 10, 30)
        assert cal.session_for(ts) == SessionName.REGULAR

    def test_pre_market_returns_closed_when_disabled(self):
        cal = USEquityCalendar.from_yaml(YAML_PATH)
        ts = _et_dt(2026, 5, 4, 6, 0)
        # pre_market has allow_trading=False, so it should be CLOSED
        assert cal.session_for(ts) == SessionName.CLOSED


# ---------------------------------------------------------------------------
# Tests: with_holidays backward compatibility
# ---------------------------------------------------------------------------

class TestWithHolidaysBackwardCompat:
    """Ensure the existing with_holidays() API still works identically."""

    def test_default_no_yaml_still_works(self):
        cal = USEquityCalendar.with_holidays()
        assert len(cal.rules) == 4
        assert cal.early_close_time == time(13, 0)
        # Should have holidays loaded
        assert len(cal.holidays) > 0

    def test_default_rules_are_same(self):
        cal = USEquityCalendar.with_holidays()
        rules = cal.rules
        over = next(r for r in rules if r.name == SessionName.OVERNIGHT)
        pre = next(r for r in rules if r.name == SessionName.PRE_MARKET)
        reg = next(r for r in rules if r.name == SessionName.REGULAR)
        ah = next(r for r in rules if r.name == SessionName.AFTER_HOURS)
        assert over.enabled is False  # default SessionConfig has overnight=False
        assert pre.enabled is True
        assert reg.enabled is True
        assert ah.enabled is True

    def test_with_holidays_accepts_yaml_path(self):
        cal = USEquityCalendar.with_holidays(yaml_path=YAML_PATH)
        assert len(cal.rules) == 4
        assert len(cal.holidays) > 0  # Still has holidays
        # YAML has pre_market.allow_trading=False
        pre = next(r for r in cal.rules if r.name == SessionName.PRE_MARKET)
        assert pre.enabled is False

    def test_known_holiday_still_recognized_with_yaml(self):
        cal = USEquityCalendar.with_holidays(yaml_path=YAML_PATH)
        # 2026-01-01 is New Year's Day
        assert not cal.is_trading_day(date(2026, 1, 1))

    def test_early_close_still_works_with_yaml(self):
        cal = USEquityCalendar.with_holidays(yaml_path=YAML_PATH)
        # 2026-11-27 is Black Friday (early close at 13:00 ET)
        ts = _et_dt(2026, 11, 27, 14, 0)
        if cal.is_early_close(date(2026, 11, 27)):
            assert cal.session_for(ts) == SessionName.CLOSED

    def test_custom_early_close_time_from_yaml(self):
        cal = USEquityCalendar.with_holidays(yaml_path=YAML_PATH)
        assert cal.early_close_time == time(13, 0)


# ---------------------------------------------------------------------------
# Tests: SessionRule.contains with YAML rules
# ---------------------------------------------------------------------------

class TestYamlSessionContains:
    """SessionRule.contains should work correctly with YAML-loaded times."""

    def test_regular_hours_contained(self):
        _, rules, _ = load_sessions_from_yaml(YAML_PATH)
        regular = next(r for r in rules if r.name == SessionName.REGULAR)
        ts = _et_dt(2026, 5, 4, 11, 0)
        assert regular.contains(ts)

    def test_regular_before_open_not_contained(self):
        _, rules, _ = load_sessions_from_yaml(YAML_PATH)
        regular = next(r for r in rules if r.name == SessionName.REGULAR)
        ts = _et_dt(2026, 5, 4, 9, 0)
        assert not regular.contains(ts)

    def test_regular_after_close_not_contained(self):
        _, rules, _ = load_sessions_from_yaml(YAML_PATH)
        regular = next(r for r in rules if r.name == SessionName.REGULAR)
        ts = _et_dt(2026, 5, 4, 16, 30)
        assert not regular.contains(ts)

    def test_overnight_crosses_midnight(self):
        _, rules, _ = load_sessions_from_yaml(YAML_PATH)
        overnight = next(r for r in rules if r.name == SessionName.OVERNIGHT)
        # 22:00 ET should be in overnight
        ts = _et_dt(2026, 5, 4, 22, 0)
        assert overnight.contains(ts)
        # 03:00 ET should be in overnight
        ts = _et_dt(2026, 5, 5, 3, 0)
        assert overnight.contains(ts)

    def test_overnight_after_end_not_contained(self):
        _, rules, _ = load_sessions_from_yaml(YAML_PATH)
        overnight = next(r for r in rules if r.name == SessionName.OVERNIGHT)
        ts = _et_dt(2026, 5, 5, 5, 0)
        assert not overnight.contains(ts)


# ---------------------------------------------------------------------------
# Tests: default (no YAML) still works
# ---------------------------------------------------------------------------

class TestDefaultCalendar:
    """Ensure the original default calendar still works unchanged."""

    def test_default_calendar_has_same_sessions(self):
        cal = USEquityCalendar()
        assert len(cal.rules) == 4
        names = {r.name for r in cal.rules}
        assert names == {
            SessionName.OVERNIGHT,
            SessionName.PRE_MARKET,
            SessionName.REGULAR,
            SessionName.AFTER_HOURS,
        }

    def test_default_calendar_regular_session_works(self):
        cal = USEquityCalendar()
        ts = _et_dt(2026, 5, 4, 10, 30)
        assert cal.session_for(ts) == SessionName.REGULAR

    def test_default_calendar_pre_market_works(self):
        cal = USEquityCalendar()
        ts = _et_dt(2026, 5, 4, 6, 0)
        # Default SessionConfig has pre_market=True
        assert cal.session_for(ts) == SessionName.PRE_MARKET

    def test_default_calendar_overnight_disabled(self):
        cal = USEquityCalendar()
        ts = _et_dt(2026, 5, 4, 22, 0)
        # Default SessionConfig has overnight=False so this falls through to CLOSED
        assert cal.session_for(ts) == SessionName.CLOSED


# ---------------------------------------------------------------------------
# Tests: early close time configurability
# ---------------------------------------------------------------------------

class TestEarlyCloseConfig:
    """Verify early_close_time is configurable and used in session_for."""

    def test_early_close_time_default(self):
        cal = USEquityCalendar()
        assert cal.early_close_time == time(13, 0)

    def test_early_close_time_custom(self):
        cal = USEquityCalendar(early_close_time=time(14, 0))
        assert cal.early_close_time == time(14, 0)

    def test_early_close_uses_configured_time(self):
        """On an early close day, trading stops at early_close_time."""
        cal = USEquityCalendar(early_close_time=time(12, 0))
        # Mock early close for a day
        cal.early_closes = {date(2026, 5, 4): "test"}
        ts_1130 = _et_dt(2026, 5, 4, 11, 30)
        ts_1230 = _et_dt(2026, 5, 4, 12, 30)
        # Before early close -> REGULAR
        assert cal.session_for(ts_1130) == SessionName.REGULAR
        # After early close -> CLOSED
        assert cal.session_for(ts_1230) == SessionName.CLOSED

    def test_early_close_yaml_custom_value(self):
        """Create a temp YAML with non-standard early close and verify."""
        import tempfile
        custom = {
            "market": {
                "timezone": "America/New_York",
                "sessions": {
                    "pre_market": {"start": "04:00", "end": "09:30", "allow_trading": False},
                    "regular": {"start": "09:30", "end": "16:00", "allow_trading": True},
                    "after_hours": {"start": "16:00", "end": "20:00", "allow_trading": False},
                    "overnight": {"start": "21:00", "end": "04:00", "allow_trading": False},
                },
                "early_close": {"time": "14:00"},
            }
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(custom, f)
            tmp_path = f.name
        try:
            cal = USEquityCalendar.from_yaml(tmp_path)
            assert cal.early_close_time == time(14, 0)
            # On an early close day, after 14:00 should be CLOSED
            cal.early_closes = {date(2026, 5, 4): "test"}
            ts_1330 = _et_dt(2026, 5, 4, 13, 30)
            ts_1430 = _et_dt(2026, 5, 4, 14, 30)
            assert cal.session_for(ts_1330) == SessionName.REGULAR
            assert cal.session_for(ts_1430) == SessionName.CLOSED
        finally:
            import os
            os.unlink(tmp_path)
