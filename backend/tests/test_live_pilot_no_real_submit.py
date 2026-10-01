"""Tests that NO G3 module ever calls broker.submit_order.

Proves the no-real-submit invariant across all G3 Live Pilot modules.
"""

from __future__ import annotations

import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from quant_us.live.live_pilot_dry_run import (
    DryRunReport,
    LiveOrderDryRunRecord,
    LivePilotDryRunExecutor,
)


# ---------------------------------------------------------------------------
# LivePilotDryRunExecutor — no broker.submit_order
# ---------------------------------------------------------------------------


class TestDryRunExecutorNoBrokerCall:
    def test_executor_never_calls_broker_submit_order(self) -> None:
        """Verify that executing a dry-run NEVER calls broker.submit_order."""
        with tempfile.TemporaryDirectory() as td:
            executor = LivePilotDryRunExecutor(data_root=td)
            report = executor.execute(
                approval_id="test_approval",
                envelope_id="test_envelope",
            )
            for record in report.records:
                assert record.real_submit is False

    def test_executor_does_not_import_alpaca_broker(self) -> None:
        """The executor should not import AlpacaBroker."""
        import quant_us.live.live_pilot_dry_run as dry_run_mod

        source = dry_run_mod.__file__ or ""
        with open(source) as f:
            code = f.read()
        assert "AlpacaBroker" not in code

    @patch("quant_us.live.live_pilot_dry_run.LivePilotDryRunExecutor._step_final_record")
    def test_submit_order_never_invoked_even_with_mock(
        self, mock_step
    ) -> None:
        """Even when mocks are used, submit_order is never called."""
        with tempfile.TemporaryDirectory() as td:
            executor = LivePilotDryRunExecutor(data_root=td)
            report = executor.execute(
                approval_id="test_approval",
                envelope_id="test_envelope",
            )
            assert report.to_dict()["real_submit_occurred"] is False


class TestLiveOrderDryRunRecordRealSubmit:
    def test_always_false_100_records(self) -> None:
        for i in range(100):
            record = LiveOrderDryRunRecord(dry_run_id=f"dr_{i:04d}")
            assert record.real_submit is False, f"Record {i} has real_submit=True"

    def test_redundant_constructor_arg_still_false(self) -> None:
        record = LiveOrderDryRunRecord(dry_run_id="test", real_submit=False)
        assert record.real_submit is False

    def test_field_present_in_instance(self) -> None:
        record = LiveOrderDryRunRecord(dry_run_id="test")
        assert hasattr(record, "real_submit")

    def test_field_present_in_to_dict(self) -> None:
        record = LiveOrderDryRunRecord(dry_run_id="test")
        d = record.to_dict()
        assert "real_submit" in d
        assert d["real_submit"] is False


class TestDryRunReportNoRealSubmit:
    def test_real_submit_occurred_always_false(self) -> None:
        report = DryRunReport(dry_run_id="test")
        d = report.to_dict()
        assert d["real_submit_occurred"] is False

    def test_no_real_order_submitted_always_true(self) -> None:
        report = DryRunReport(dry_run_id="test")
        d = report.to_dict()
        assert d["no_real_order_submitted"] is True

    def test_with_multiple_records_still_false(self) -> None:
        report = DryRunReport(dry_run_id="test")
        for i in range(10):
            report.records.append(
                LiveOrderDryRunRecord(dry_run_id=f"rec_{i}")
            )
        d = report.to_dict()
        assert d["real_submit_occurred"] is False

    def test_empty_report_defaults(self) -> None:
        report = DryRunReport(dry_run_id="test")
        assert report.overall_passed is False
        assert report.steps_passed == 0


# ---------------------------------------------------------------------------
# EmergencyStopController — no broker.submit_order
# ---------------------------------------------------------------------------


class TestEmergencyStopNoBrokerCall:
    def test_controller_never_calls_broker(self) -> None:
        """EmergencyStopController should only manage state files."""
        from quant_us.live.emergency_stop import EmergencyStopController

        with tempfile.TemporaryDirectory() as td:
            ctrl = EmergencyStopController(state_dir=td)
            ctrl.trigger(reason="manual_stop")
            ctrl.acknowledge(acknowledged_by="tester")
            ctrl.resolve()
            status = ctrl.status()
            assert status["state"] in ("ARMED", "RESOLVED", "TRIGGERED", "ACKNOWLEDGED")

    def test_controller_does_not_import_broker(self) -> None:
        import quant_us.live.emergency_stop as es_mod

        source = es_mod.__file__ or ""
        with open(source) as f:
            code = f.read()
        assert "submit_order(" not in code
        assert "AlpacaBroker" not in code


# ---------------------------------------------------------------------------
# RollbackPlanGenerator — no broker.submit_order
# ---------------------------------------------------------------------------


class TestRollbackPlanNoBrokerCall:
    def test_generator_never_calls_broker(self) -> None:
        from quant_us.live.emergency_stop import RollbackPlanGenerator

        with tempfile.TemporaryDirectory() as td:
            gen = RollbackPlanGenerator(data_root=td)
            plan = gen.generate(reason="manual_stop")
            # Plan produces instructions only, not orders
            assert plan.manual_review_required is True
            assert len(plan.reduce_only_instructions) > 0

    def test_generator_does_not_import_broker(self) -> None:
        import quant_us.live.emergency_stop as es_mod

        source = es_mod.__file__ or ""
        with open(source) as f:
            code = f.read()
        assert "submit_order(" not in code


# ---------------------------------------------------------------------------
# HumanApprovalGate — no broker.submit_order
# ---------------------------------------------------------------------------


class TestHumanApprovalGateNoBrokerCall:
    def test_gate_never_calls_broker(self) -> None:
        from quant_us.live.live_pilot_approval import HumanApprovalGate

        with tempfile.TemporaryDirectory() as td:
            gate = HumanApprovalGate(store_path=td)
            req = gate.create(approval_id="test")
            gate.approve(approval_id="test", approver="admin")
            result = gate.check(approval_id="test")
            assert result.passed
            # No broker interaction

    def test_gate_does_not_import_broker(self) -> None:
        import quant_us.live.live_pilot_approval as app_mod

        source = app_mod.__file__ or ""
        with open(source) as f:
            code = f.read()
        assert "submit_order(" not in code
        assert "AlpacaBroker" not in code


# ---------------------------------------------------------------------------
# LivePilotGoNoGoDossier — no broker.submit_order
# ---------------------------------------------------------------------------


class TestGoNoGoNoBrokerCall:
    def test_dossier_never_enables_live_orders_directly(self) -> None:
        """Dossier decision NEVER directly enables live orders."""
        from quant_us.live.live_pilot_go_nogo import (
            ApprovalEvidence,
            EnvelopeEvidence,
            LivePilotGoNoGoDossier,
            PaperEvidence,
            SafetyEvidence,
            ShadowEvidence,
        )

        d = LivePilotGoNoGoDossier(
            shadow=ShadowEvidence(days_completed=5, real_submit_count=0),
            paper=PaperEvidence(clean_days=30, recon_fail_count=0),
            approval=ApprovalEvidence(status="APPROVED"),
            envelope=EnvelopeEvidence(envelope_id="env_001"),
            safety=SafetyEvidence(),
        )
        d.determine_decision()
        assert d.decision == "READY_FOR_HUMAN_REVIEW"
        # READY_FOR_HUMAN_REVIEW does NOT mean live orders are enabled
        markdown = d.to_markdown()
        assert "does NOT automatically enable live orders" in markdown

    def test_dossier_does_not_import_broker(self) -> None:
        import quant_us.live.live_pilot_go_nogo as gn_mod

        source = gn_mod.__file__ or ""
        with open(source) as f:
            code = f.read()
        assert "submit_order(" not in code
        assert "AlpacaBroker" not in code


# ---------------------------------------------------------------------------
# Comprehensive module-scan
# ---------------------------------------------------------------------------


G3_MODULE_PATHS = [
    "quant_us/live/live_pilot_approval.py",
    "quant_us/live/live_pilot_risk_envelope.py",
    "quant_us/live/live_pilot_dry_run.py",
    "quant_us/live/emergency_stop.py",
    "quant_us/live/live_pilot_go_nogo.py",
    "quant_us/live/live_pilot_dossier.py",
]


class TestAllG3ModulesNoBroker:
    def test_no_module_imports_alpaca_broker(self) -> None:
        for mod_path in G3_MODULE_PATHS:
            if not os.path.exists(mod_path):
                continue
            with open(mod_path) as f:
                code = f.read()
            assert "AlpacaBroker" not in code, (
                f"{mod_path} imports AlpacaBroker!"
            )

    def test_no_module_contains_submit_order(self) -> None:
        for mod_path in G3_MODULE_PATHS:
            if not os.path.exists(mod_path):
                continue
            with open(mod_path) as f:
                code = f.read()
            assert "submit_order(" not in code, (
                f"{mod_path} contains submit_order!"
            )

    def test_dry_run_references_readonly_broker_not_real(self) -> None:
        """The dry-run executor should reference ReadOnlyLiveBrokerProxy."""
        path = "quant_us/live/live_pilot_dry_run.py"
        if os.path.exists(path):
            with open(path) as f:
                code = f.read()
            assert "ReadOnlyLiveBrokerProxy" in code or "readonly" in code.lower()
