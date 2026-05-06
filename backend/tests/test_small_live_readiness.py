"""Tests for small-live readiness gate.

Covers:
  - paper_30_day_clean passes with valid state
  - paper_30_day_clean fails with <30 days
  - paper_30_day_clean fails with reconciliation errors
  - paper_30_day_clean fails with daily errors
  - Small-live readiness requires all 8 gates + paper 30 day
  - Go/no-go output via CLI
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from quant_us.reports.live_readiness import LiveReadinessGate, LiveReadinessReport, ReadinessCheck


# ---------------------------------------------------------------------------
# Helper: build a valid validation state dict
# ---------------------------------------------------------------------------

def _make_valid_state(
    consecutive_clean_days: int = 30,
    days_completed: int = 30,
    days_required: int = 30,
    daily_results: list[dict] | None = None,
) -> dict:
    if daily_results is None:
        daily_results = [
            {"date": f"2025-01-{d:02d}", "errors": [], "recon": "PASS"}
            for d in range(1, 31)
        ]
    return {
        "symbols": ["SPY", "QQQ"],
        "capital": 100_000.0,
        "days_required": days_required,
        "days_completed": days_completed,
        "consecutive_clean_days": consecutive_clean_days,
        "start_date": "2025-01-01",
        "last_date": "2025-01-30",
        "daily_results": daily_results,
    }


def _dump_temp_state(state: dict) -> str:
    """Write *state* to a temp JSON file and return its path."""
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
    json.dump(state, f)
    f.close()
    return f.name


# ---------------------------------------------------------------------------
# paper_30_day_clean unit tests
# ---------------------------------------------------------------------------


class Paper30DayCleanTests(unittest.TestCase):
    """paper_30_day_clean check with updated validation state schema."""

    def test_passes_with_valid_state(self) -> None:
        path = _dump_temp_state(_make_valid_state())
        try:
            check = LiveReadinessGate._check_paper_30_day_clean(path)
            self.assertTrue(check.passed, msg=check.detail)
            self.assertIn("30/30 consecutive clean", check.detail)
            self.assertIn("no errors", check.detail)
        finally:
            os.unlink(path)

    def test_fails_without_path(self) -> None:
        check = LiveReadinessGate._check_paper_30_day_clean(None)
        self.assertFalse(check.passed)
        self.assertIn("No validation_state_path", check.detail)

    def test_fails_when_file_missing(self) -> None:
        check = LiveReadinessGate._check_paper_30_day_clean("/nonexistent/path/state.json")
        self.assertFalse(check.passed)
        self.assertIn("not found", check.detail)

    def test_fails_when_not_enough_consecutive_days(self) -> None:
        state = _make_valid_state(consecutive_clean_days=15, days_completed=30)
        path = _dump_temp_state(state)
        try:
            check = LiveReadinessGate._check_paper_30_day_clean(path)
            self.assertFalse(check.passed)
            self.assertIn("15/30 consecutive clean", check.detail)
        finally:
            os.unlink(path)

    def test_fails_when_not_enough_days_completed(self) -> None:
        state = _make_valid_state(consecutive_clean_days=30, days_completed=20)
        path = _dump_temp_state(state)
        try:
            check = LiveReadinessGate._check_paper_30_day_clean(path)
            self.assertFalse(check.passed)
            self.assertIn("20/30 days completed", check.detail)
        finally:
            os.unlink(path)

    def test_fails_when_reconciliation_fails(self) -> None:
        daily_results = [
            {"date": "2025-01-01", "errors": [], "recon": "FAIL"},
        ]
        state = _make_valid_state(daily_results=daily_results)
        path = _dump_temp_state(state)
        try:
            check = LiveReadinessGate._check_paper_30_day_clean(path)
            self.assertFalse(check.passed)
            self.assertIn("recon_fail", check.detail)
        finally:
            os.unlink(path)

    def test_fails_when_daily_errors_exist(self) -> None:
        daily_results = [
            {"date": "2025-01-01", "errors": ["data_stale"], "recon": "PASS"},
        ]
        state = _make_valid_state(daily_results=daily_results)
        path = _dump_temp_state(state)
        try:
            check = LiveReadinessGate._check_paper_30_day_clean(path)
            self.assertFalse(check.passed)
            self.assertIn("Problem days", check.detail)
            self.assertIn("1 errors", check.detail)
        finally:
            os.unlink(path)

    def test_fails_when_both_errors_and_recon_fail(self) -> None:
        daily_results = [
            {"date": "2025-01-01", "errors": ["bad_data"], "recon": "FAIL"},
        ]
        state = _make_valid_state(daily_results=daily_results)
        path = _dump_temp_state(state)
        try:
            check = LiveReadinessGate._check_paper_30_day_clean(path)
            self.assertFalse(check.passed)
            self.assertIn("Problem days", check.detail)
            self.assertIn("1 errors", check.detail)
            self.assertIn("recon_fail", check.detail)
        finally:
            os.unlink(path)

    def test_fails_with_corrupt_json(self) -> None:
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        f.write("not valid json")
        f.close()
        try:
            check = LiveReadinessGate._check_paper_30_day_clean(f.name)
            self.assertFalse(check.passed)
            self.assertIn("Error reading", check.detail)
        finally:
            os.unlink(f.name)


# ---------------------------------------------------------------------------
# Small-live readiness: all 8 gates must pass
# ---------------------------------------------------------------------------


class SmallLiveReadinessGateTests(unittest.TestCase):
    """Small-live readiness requires all 8 gates + paper 30-day."""

    def test_reject_when_any_check_fails(self) -> None:
        """is_ready() must be False if any of the 8 checks fails."""
        gate = LiveReadinessGate()
        with patch.object(gate, "_check_paper_30_day_clean") as mock_check:
            mock_check.return_value = ReadinessCheck(name="paper_30_day_clean", passed=False)
            report = gate.check_all()
            self.assertFalse(report.is_ready())

    def test_gate_passes_with_all_mocks(self) -> None:
        """When all 8 checks return passed, the gate says ready."""
        gate = LiveReadinessGate()
        passed = ReadinessCheck(name="mock", passed=True)
        attrs = [
            "_check_paper_30_day_clean",
            "_check_oms_idempotency",
            "_check_kill_switch_coverage",
            "_check_recon_hard_gate",
            "_check_fill_traceability",
            "_check_order_recovery",
            "_check_daily_report",
            "_check_monitoring",
        ]
        with (
            patch.object(gate, attrs[0], return_value=passed),
            patch.object(gate, attrs[1], return_value=passed),
            patch.object(gate, attrs[2], return_value=passed),
            patch.object(gate, attrs[3], return_value=passed),
            patch.object(gate, attrs[4], return_value=passed),
            patch.object(gate, attrs[5], return_value=passed),
            patch.object(gate, attrs[6], return_value=passed),
            patch.object(gate, attrs[7], return_value=passed),
        ):
            report = gate.check_all(
                validation_state_path="/fake/path/validation_state.json"
            )
            self.assertTrue(report.is_ready())

    def test_gate_fails_without_validation_state(self) -> None:
        """Without validation-state path, paper_30_day_clean fails -> not ready."""
        gate = LiveReadinessGate()
        report = gate.check_all(validation_state_path=None)
        paper = next((c for c in report.checks if c.name == "paper_30_day_clean"), None)
        self.assertIsNotNone(paper)
        self.assertFalse(paper.passed)
        self.assertFalse(report.is_ready())


# ---------------------------------------------------------------------------
# Go/no-go output format
# ---------------------------------------------------------------------------


class SmallLiveGoNoGoOutputTests(unittest.TestCase):
    """Check that the go/no-go logic produces correct labels."""

    def test_go_when_all_pass(self) -> None:
        report = LiveReadinessReport(
            checks=[
                ReadinessCheck(name=n, passed=True)
                for n in [
                    "paper_30_day_clean", "oms_idempotency", "kill_switch_coverage",
                    "recon_hard_gate", "fill_traceability", "order_recovery",
                    "daily_report", "monitoring",
                ]
            ],
        )
        self.assertTrue(report.is_ready())
        # go/no-go label: ready means GO
        self.assertTrue(report.is_ready())

    def test_no_go_when_any_fails(self) -> None:
        report = LiveReadinessReport(
            checks=[
                ReadinessCheck(name="paper_30_day_clean", passed=True),
                ReadinessCheck(name="oms_idempotency", passed=True),
                ReadinessCheck(name="kill_switch_coverage", passed=False),  # fails
                ReadinessCheck(name="recon_hard_gate", passed=True),
                ReadinessCheck(name="fill_traceability", passed=True),
                ReadinessCheck(name="order_recovery", passed=True),
                ReadinessCheck(name="daily_report", passed=True),
                ReadinessCheck(name="monitoring", passed=True),
            ],
        )
        self.assertFalse(report.is_ready())

    def test_to_dict_includes_all_checks(self) -> None:
        checks = [
            ReadinessCheck(name="paper_30_day_clean", passed=True, detail="30/30"),
            ReadinessCheck(name="oms_idempotency", passed=False, detail="missing param"),
        ]
        report = LiveReadinessReport(checks=checks)
        d = report.to_dict()
        self.assertFalse(d["ready"])
        self.assertEqual(len(d["checks"]), 2)
        self.assertEqual(d["checks"][0]["name"], "paper_30_day_clean")
        self.assertEqual(d["checks"][0]["detail"], "30/30")


if __name__ == "__main__":
    unittest.main()
