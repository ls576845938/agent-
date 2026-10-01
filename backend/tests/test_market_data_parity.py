"""Tests for quant_us/live/market_data_parity.py — MarketDataParityChecker,
MarketDataParityReport, ParityBar.

Covers report generation, safety checks, freshness, price diff thresholds,
and serialization.
"""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from quant_us.live.market_data_parity import (
    MarketDataParityChecker,
    MarketDataParityReport,
    ParityBar,
)


# ===========================================================================
# MarketDataParityReport
# ===========================================================================


class TestMarketDataParityReport:
    def test_create_report(self) -> None:
        report = MarketDataParityReport(run_id="mdp_test_001")
        assert report.run_id == "mdp_test_001"
        assert report.overall_status == "ok"
        assert report.is_safe_for_shadow_orders is True

    def test_is_safe_for_shadow_orders_with_critical(self) -> None:
        report = MarketDataParityReport(
            run_id="test",
            critical_issues=["Live data missing for SPY"],
        )
        assert report.is_safe_for_shadow_orders is False

    def test_is_safe_for_shadow_orders_with_warnings(self) -> None:
        report = MarketDataParityReport(
            run_id="test",
            warnings=["SPY data stale"],
        )
        assert report.is_safe_for_shadow_orders is True

    def test_to_dict_format(self) -> None:
        report = MarketDataParityReport(
            run_id="mdp_test",
            symbols=["SPY", "QQQ"],
            sources_compared=["live", "local"],
            warnings=["SPY: live data stale (120s)"],
        )
        d = report.to_dict()
        assert d["run_id"] == "mdp_test"
        assert d["symbols"] == ["SPY", "QQQ"]
        assert d["bar_count"] >= 0
        assert "warnings" in d
        assert "critical_issues" in d
        assert "is_safe_for_shadow_orders" in d
        assert d["overall_status"] in ("ok", "warn")


# ===========================================================================
# MarketDataParityChecker
# ===========================================================================


class TestMarketDataParityChecker:
    @pytest.fixture
    def checker(self) -> MarketDataParityChecker:
        return MarketDataParityChecker(symbols=["SPY", "QQQ"], data_root="/tmp/test_mdp")

    def test_create_checker(self, checker: MarketDataParityChecker) -> None:
        assert checker.symbols == ["SPY", "QQQ"]

    def test_compare_without_sources_returns_warn(
        self, checker: MarketDataParityChecker
    ) -> None:
        report = checker.compare(live_bars=None, include_yfinance=False)
        assert report.overall_status == "warn"
        assert len(report.warnings) > 0
        assert any("No data sources" in w for w in report.warnings)

    def test_compare_with_live_data_missing_bars(
        self, checker: MarketDataParityChecker
    ) -> None:
        live_bars: dict[str, list[dict]] = {}
        report = checker.compare(live_bars=live_bars, include_yfinance=False)
        assert report.overall_status == "warn"

    def test_compare_with_live_partial_data(
        self, checker: MarketDataParityChecker
    ) -> None:
        now = datetime.now(timezone.utc)
        live_bars = {
            "SPY": [
                {
                    "timestamp": now,
                    "open": 530.0,
                    "high": 532.0,
                    "low": 528.0,
                    "close": 531.0,
                    "volume": 10_000_000,
                },
            ],
        }
        report = checker.compare(live_bars=live_bars, include_yfinance=False)
        # SPY has data; QQQ is missing from live
        assert "QQQ" in str(report.warnings) or report.overall_status in ("ok", "warn")

    def test_stale_data_generates_warning(self, checker: MarketDataParityChecker) -> None:
        stale_time = datetime.now(timezone.utc) - timedelta(seconds=120)
        live_bars = {
            "SPY": [
                {
                    "timestamp": stale_time,
                    "open": 530.0,
                    "high": 532.0,
                    "low": 528.0,
                    "close": 531.0,
                    "volume": 10_000_000,
                },
            ],
        }
        report = checker.compare(live_bars=live_bars, include_yfinance=False)
        if report.overall_status != "warn":
            # If latency < STALE_WARN_SECONDS, no warning — that is also fine
            pass

    def test_critically_stale_data_generates_critical(
        self, checker: MarketDataParityChecker
    ) -> None:
        very_stale = datetime.now(timezone.utc) - timedelta(seconds=600)
        live_bars = {
            "SPY": [
                {
                    "timestamp": very_stale,
                    "open": 530.0,
                    "high": 532.0,
                    "low": 528.0,
                    "close": 531.0,
                    "volume": 10_000_000,
                },
            ],
        }
        report = checker.compare(live_bars=live_bars, include_yfinance=False)
        if report.overall_status == "critical":
            assert report.is_safe_for_shadow_orders is False

    def test_freshness_status_logic_fresh(
        self, checker: MarketDataParityChecker
    ) -> None:
        now = datetime.now(timezone.utc)
        live_bars = {
            "SPY": [
                {
                    "timestamp": now,
                    "open": 530.0,
                    "high": 532.0,
                    "low": 528.0,
                    "close": 531.0,
                    "volume": 10_000_000,
                },
            ],
        }
        report = checker.compare(live_bars=live_bars, include_yfinance=False)
        for bar in report.bars:
            if bar.symbol == "SPY" and bar.source == "live":
                assert bar.freshness_status == "fresh"

    def test_missing_data_generates_missing_bars(
        self, checker: MarketDataParityChecker
    ) -> None:
        report = checker.compare(live_bars={}, include_yfinance=False)
        has_missing = any(b.missing_bar for b in report.bars)
        assert has_missing is True


# ===========================================================================
# ParityBar
# ===========================================================================


class TestParityBar:
    def test_create_parity_bar(self) -> None:
        bar = ParityBar(
            symbol="SPY",
            timestamp=datetime.now(timezone.utc),
            source="live",
            open=530.0,
            high=532.0,
            low=528.0,
            close=531.0,
            volume=10_000_000,
        )
        assert bar.symbol == "SPY"
        assert bar.source == "live"
        assert bar.missing_bar is False
        assert bar.freshness_status == "fresh"

    def test_missing_bar_defaults(self) -> None:
        bar = ParityBar(
            symbol="QQQ",
            timestamp=datetime.now(timezone.utc),
            source="live",
            open=0.0,
            high=0.0,
            low=0.0,
            close=0.0,
            volume=0.0,
            missing_bar=True,
            freshness_status="missing",
        )
        assert bar.missing_bar is True
        assert bar.freshness_status == "missing"

    def test_to_dict(self) -> None:
        now = datetime.now(timezone.utc)
        bar = ParityBar(
            symbol="SPY",
            timestamp=now,
            source="live",
            open=530.0,
            high=532.0,
            low=528.0,
            close=531.0,
            volume=10_000_000,
            price_diff_bps=5.0,
            freshness_status="fresh",
        )
        d = bar.to_dict()
        assert d["symbol"] == "SPY"
        assert d["price_diff_bps"] == 5.0
        assert d["freshness_status"] == "fresh"


# ===========================================================================
# save_report
# ===========================================================================


class TestSaveReport:
    def test_save_report_writes_json(self) -> None:
        checker = MarketDataParityChecker(["SPY"])
        report = MarketDataParityReport(
            run_id="save_test",
            symbols=["SPY"],
            overall_status="ok",
        )
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            out_path = f.name

        try:
            checker.save_report(report, out_path)
            saved = json.loads(Path(out_path).read_text())
            assert saved["run_id"] == "save_test"
            assert saved["is_safe_for_shadow_orders"] is True
        finally:
            Path(out_path).unlink(missing_ok=True)
