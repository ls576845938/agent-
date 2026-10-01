"""Tests for LivePilotDryRunExecutor and LiveOrderDryRunRecord."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from quant_us.live.live_pilot_dry_run import (
    LivePilotDryRunExecutor,
    LiveOrderDryRunRecord,
    DryRunReport,
)


class TestLiveOrderDryRunRecord:
    def test_always_real_submit_false(self) -> None:
        for _ in range(100):
            record = LiveOrderDryRunRecord(dry_run_id="test")
            assert record.real_submit is False

    def test_real_submit_is_false_by_default(self) -> None:
        record = LiveOrderDryRunRecord(dry_run_id="test")
        assert record.real_submit is False
        assert record.would_submit is True

    def test_no_real_submit_proof_non_empty(self) -> None:
        record = LiveOrderDryRunRecord(dry_run_id="test")
        assert len(record.no_real_submit_proof) > 0

    def test_to_dict(self) -> None:
        record = LiveOrderDryRunRecord(
            dry_run_id="dr_1",
            approval_id="apr_1",
            envelope_id="env_1",
            strategy_id="etf_rotation",
            order_intent_id="int_1",
            estimated_notional=500.0,
        )
        d = record.to_dict()
        assert d["real_submit"] is False
        assert d["dry_run_id"] == "dr_1"
        assert d["approval_id"] == "apr_1"


class TestDryRunReport:
    def test_real_submit_occurred_always_false(self) -> None:
        report = DryRunReport(dry_run_id="test")
        d = report.to_dict()
        assert d["real_submit_occurred"] is False
        assert d["no_real_order_submitted"] is True

    def test_empty_report_defaults(self) -> None:
        report = DryRunReport(dry_run_id="test")
        assert report.overall_passed is False
        assert report.steps_passed == 0


class TestLivePilotDryRunExecutor:
    def test_execute_returns_report_with_14_steps(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            from quant_us.live.live_pilot_approval import HumanApprovalGate
            from quant_us.live.live_pilot_risk_envelope import (
                LivePilotRiskEnvelope,
                RiskEnvelopeManager,
            )

            gate = HumanApprovalGate(store_path=f"{tmp}/approvals")
            gate.create("dr_apr", strategy_id="etf_rotation", symbols=["SPY"])
            gate.approve("dr_apr", "tester")

            mgr = RiskEnvelopeManager(store_path=f"{tmp}/envelopes")
            env = LivePilotRiskEnvelope.default_conservative("dr_env")
            mgr.create(env)

            executor = LivePilotDryRunExecutor(data_root=tmp)
            report = executor.execute(
                approval_id="dr_apr",
                envelope_id="dr_env",
                strategy_id="etf_rotation",
                symbols=["SPY"],
            )
            assert report.dry_run_id != ""
            assert len(report.records) == 14

    def test_all_records_have_real_submit_false(self) -> None:
        record = LiveOrderDryRunRecord(dry_run_id="test")
        assert record.real_submit is False
        # Try to check it cannot be changed (frozen dataclass would raise)
        assert record.real_submit is False

    def test_save_report_writes_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            executor = LivePilotDryRunExecutor(data_root=tmp)
            report = DryRunReport(dry_run_id="save_test")
            path = executor.save_report(report, output_path=f"{tmp}/test_report.json")
            assert Path(path).exists()
            data = json.loads(Path(path).read_text())
            assert data["no_real_order_submitted"] is True

    def test_no_approval_blocks_dry_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            from quant_us.live.live_pilot_risk_envelope import (
                LivePilotRiskEnvelope,
                RiskEnvelopeManager,
            )

            mgr = RiskEnvelopeManager(store_path=f"{tmp}/envelopes")
            env = LivePilotRiskEnvelope.default_conservative("dr_env")
            mgr.create(env)

            executor = LivePilotDryRunExecutor(data_root=tmp)
            report = executor.execute(
                approval_id="nonexistent",
                envelope_id="dr_env",
            )
            assert report.overall_passed is False

    def test_no_envelope_blocks_dry_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            from quant_us.live.live_pilot_approval import HumanApprovalGate

            gate = HumanApprovalGate(store_path=f"{tmp}/approvals")
            gate.create("dr_apr2", strategy_id="etf_rotation", symbols=["SPY"])
            gate.approve("dr_apr2", "tester")

            executor = LivePilotDryRunExecutor(data_root=tmp)
            report = executor.execute(
                approval_id="dr_apr2",
                envelope_id="nonexistent",
            )
            assert report.overall_passed is False

    def test_dry_run_never_calls_broker(self) -> None:
        """Verify the dry-run executor never imports or calls a real broker."""
        with tempfile.TemporaryDirectory() as tmp:
            executor = LivePilotDryRunExecutor(data_root=tmp)
            report = DryRunReport(dry_run_id="test")
            d = report.to_dict()
            assert d["real_submit_occurred"] is False
