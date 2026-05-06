"""Tests for quant_us/reports/live_readiness.py — LiveReadinessGate.

Covers:
  - All checks pass on a correctly configured system (real modules)
  - Individual check failures via patching
  - is_ready() returns False when any check fails
  - to_dict() output format
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
# Report / Check unit tests
# ---------------------------------------------------------------------------


class LiveReadinessReportTests(unittest.TestCase):
    """LiveReadinessReport aggregation logic."""

    def test_all_passed_empty_is_true(self) -> None:
        report = LiveReadinessReport()
        self.assertTrue(report.all_passed)
        self.assertTrue(report.is_ready())

    def test_all_passed_one_fail_is_false(self) -> None:
        report = LiveReadinessReport(
            checks=[
                ReadinessCheck(name="a", passed=True),
                ReadinessCheck(name="b", passed=False),
            ],
        )
        self.assertFalse(report.all_passed)
        self.assertFalse(report.is_ready())

    def test_to_dict_format(self) -> None:
        report = LiveReadinessReport(
            checks=[
                ReadinessCheck(name="c1", passed=True, detail="ok"),
                ReadinessCheck(name="c2", passed=False, detail="fail"),
            ],
        )
        d = report.to_dict()
        self.assertFalse(d["ready"])
        self.assertEqual(len(d["checks"]), 2)
        self.assertEqual(d["checks"][0]["name"], "c1")
        self.assertTrue(d["checks"][0]["passed"])
        self.assertEqual(d["checks"][1]["name"], "c2")
        self.assertFalse(d["checks"][1]["passed"])


# ---------------------------------------------------------------------------
# LiveReadinessGate — individual check tests
# ---------------------------------------------------------------------------


class LiveReadinessGateCheckAllTests(unittest.TestCase):
    """check_all() with all real modules should pass all checks."""

    def test_all_checks_pass_with_real_modules(self) -> None:
        """On a correctly configured system all 8 checks should pass."""
        gate = LiveReadinessGate()
        report = gate.check_all()
        passed = [c for c in report.checks if c.passed]
        failed = [c for c in report.checks if not c.passed]

        # paper_30_day_clean will fail (no validation-state path), but all
        # other checks should pass.
        for check in report.checks:
            if check.name == "paper_30_day_clean":
                self.assertFalse(
                    check.passed,
                    f"paper_30_day_clean should fail without validation_state_path: {check.detail}",
                )
            else:
                self.assertTrue(
                    check.passed,
                    f"{check.name} should pass with real modules: {check.detail}",
                )


class LiveReadinessGatePaper30DayCleanTests(unittest.TestCase):
    """paper_30_day_clean check."""

    def test_fails_without_path(self) -> None:
        check = LiveReadinessGate._check_paper_30_day_clean(None)
        self.assertFalse(check.passed)
        self.assertIn("No validation_state_path", check.detail)

    def test_fails_when_file_missing(self) -> None:
        check = LiveReadinessGate._check_paper_30_day_clean("/nonexistent/state.json")
        self.assertFalse(check.passed)
        self.assertIn("not found", check.detail)

    def test_fails_when_not_enough_days(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({
                "consecutive_clean_days": 15,
                "days_completed": 15,
                "days_required": 30,
                "daily_results": [],
            }, f)
            path = f.name
        try:
            check = LiveReadinessGate._check_paper_30_day_clean(path)
            self.assertFalse(check.passed)
            self.assertIn("15/30 consecutive clean", check.detail)
        finally:
            os.unlink(path)

    def test_passes_when_enough_days(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({
                "consecutive_clean_days": 30,
                "days_completed": 30,
                "days_required": 30,
                "daily_results": [
                    {"date": "2025-01-01", "errors": [], "recon": "PASS"},
                    {"date": "2025-01-02", "errors": [], "recon": "PASS"},
                ],
            }, f)
            path = f.name
        try:
            check = LiveReadinessGate._check_paper_30_day_clean(path)
            self.assertTrue(check.passed)
            self.assertIn("30/30 consecutive clean", check.detail)
        finally:
            os.unlink(path)

    def test_fails_when_reconciliation_errors_exist(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({
                "consecutive_clean_days": 30,
                "days_completed": 30,
                "days_required": 30,
                "daily_results": [
                    {"date": "2025-01-01", "errors": [], "recon": "FAIL"},
                ],
            }, f)
            path = f.name
        try:
            check = LiveReadinessGate._check_paper_30_day_clean(path)
            self.assertFalse(check.passed)
            self.assertIn("recon_fail", check.detail)
        finally:
            os.unlink(path)

    def test_fails_when_daily_errors_exist(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({
                "consecutive_clean_days": 30,
                "days_completed": 30,
                "days_required": 30,
                "daily_results": [
                    {"date": "2025-01-01", "errors": ["data_error"], "recon": "PASS"},
                ],
            }, f)
            path = f.name
        try:
            check = LiveReadinessGate._check_paper_30_day_clean(path)
            self.assertFalse(check.passed)
            self.assertIn("Problem days", check.detail)
        finally:
            os.unlink(path)


class LiveReadinessGateOmsIdempotencyTests(unittest.TestCase):
    """oms_idempotency check."""

    def test_passes(self) -> None:
        check = LiveReadinessGate._check_oms_idempotency()
        self.assertTrue(check.passed)

    @patch("quant_us.reports.live_readiness.inspect.signature")
    def test_fails_when_param_missing(self, mock_sig: MagicMock) -> None:
        from inspect import Signature, Parameter

        mock_sig.return_value = Signature(
            [Parameter("self", Parameter.POSITIONAL_OR_KEYWORD)]
        )
        check = LiveReadinessGate._check_oms_idempotency()
        self.assertFalse(check.passed)
        self.assertIn("missing", check.detail.lower())


class LiveReadinessGateKillSwitchCoverageTests(unittest.TestCase):
    """kill_switch_coverage check."""

    def test_passes(self) -> None:
        check = LiveReadinessGate._check_kill_switch_coverage()
        self.assertTrue(check.passed)
        self.assertIn("kill-switch thresholds configured", check.detail)

    @patch("quant_us.risk.kill_switch.KillSwitchConfig")
    def test_fails_when_missing_thresholds(self, mock_cls: MagicMock) -> None:
        # Mock a dataclass field that only has 2 fields
        from dataclasses import dataclass

        @dataclass
        class MockKillSwitchConfig:
            max_daily_loss_pct: float = 0.03
            max_drawdown_pct: float = 0.12

        mock_cls.__dataclass_fields__ = MockKillSwitchConfig.__dataclass_fields__
        check = LiveReadinessGate._check_kill_switch_coverage()
        self.assertFalse(check.passed)
        self.assertIn("Missing", check.detail)


class LiveReadinessGateReconHardGateTests(unittest.TestCase):
    """recon_hard_gate check."""

    def test_passes(self) -> None:
        check = LiveReadinessGate._check_recon_hard_gate()
        self.assertTrue(check.passed)
        self.assertIn("reconcile_all", check.detail)

    def test_fails_when_missing_reconcile_all(self) -> None:
        class FakeReconService:
            pass  # no reconcile_all attribute

        with patch("quant_us.live.reconciliation_service.ReconciliationService", FakeReconService):
            check = LiveReadinessGate._check_recon_hard_gate()
            self.assertFalse(check.passed)


class LiveReadinessGateFillTraceabilityTests(unittest.TestCase):
    """fill_traceability check."""

    def test_passes(self) -> None:
        check = LiveReadinessGate._check_fill_traceability()
        self.assertTrue(check.passed)
        self.assertIn("traceability chain verified", check.detail)


class LiveReadinessGateOrderRecoveryTests(unittest.TestCase):
    """order_recovery check."""

    def test_passes(self) -> None:
        check = LiveReadinessGate._check_order_recovery()
        self.assertTrue(check.passed)
        self.assertIn("recover_from_ledger", check.detail)

    def test_fails_when_missing(self) -> None:
        class FakeOMS:
            pass  # no recover_from_ledger attribute

        with patch("quant_us.execution.oms.OrderManagementSystem", FakeOMS):
            check = LiveReadinessGate._check_order_recovery()
            self.assertFalse(check.passed)


class LiveReadinessGateDailyReportTests(unittest.TestCase):
    """daily_report check."""

    def test_passes(self) -> None:
        check = LiveReadinessGate._check_daily_report()
        self.assertTrue(check.passed)
        self.assertIn("daily_report", check.detail)

    def test_passes_with_mock(self) -> None:
        """Sanity: using a callable mock should pass."""
        mock_fn = MagicMock()
        with patch("quant_us.monitoring.report.daily_report", mock_fn):
            check = LiveReadinessGate._check_daily_report()
            self.assertTrue(check.passed)


class LiveReadinessGateMonitoringTests(unittest.TestCase):
    """monitoring check."""

    def test_passes(self) -> None:
        check = LiveReadinessGate._check_monitoring()
        self.assertTrue(check.passed)
        self.assertIn("MetricsCollector", check.detail)

    def test_fails_when_missing_methods(self) -> None:
        """A class without snapshot or to_prometheus_text should fail."""
        class FakeCollector:
            pass

        with patch("quant_us.monitoring.metrics.MetricsCollector", FakeCollector):
            check = LiveReadinessGate._check_monitoring()
            self.assertFalse(check.passed)


# ---------------------------------------------------------------------------
# Integration: is_ready()
# ---------------------------------------------------------------------------


class LiveReadinessGateIsReadyTests(unittest.TestCase):
    """is_ready() must be True only when ALL checks pass."""

    def test_is_ready_false_if_any_check_fails(self) -> None:
        gate = LiveReadinessGate()
        with patch.object(gate, "_check_paper_30_day_clean") as mock_check:
            mock_check.return_value = ReadinessCheck(name="x", passed=False)
            report = gate.check_all()
            self.assertFalse(report.is_ready())

    def test_is_ready_true_when_all_pass(self) -> None:
        gate = LiveReadinessGate()
        with (
            patch.object(gate, "_check_paper_30_day_clean") as m1,
            patch.object(gate, "_check_oms_idempotency") as m2,
            patch.object(gate, "_check_kill_switch_coverage") as m3,
            patch.object(gate, "_check_recon_hard_gate") as m4,
            patch.object(gate, "_check_fill_traceability") as m5,
            patch.object(gate, "_check_order_recovery") as m6,
            patch.object(gate, "_check_daily_report") as m7,
            patch.object(gate, "_check_monitoring") as m8,
        ):
            # Return passing check for every one
            passed = ReadinessCheck(name="mock", passed=True)
            m1.return_value = passed
            m2.return_value = passed
            m3.return_value = passed
            m4.return_value = passed
            m5.return_value = passed
            m6.return_value = passed
            m7.return_value = passed
            m8.return_value = passed
            report = gate.check_all()
            self.assertTrue(report.is_ready())
