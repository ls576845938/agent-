"""Regression tests: env vars do NOT bypass safety gates.

Even when QUANT_LIVE_SUBMISSION_ENABLED=true, allow_live_orders=true,
or confirm_live=true, the approval gate, risk envelope, and dry-run
invariants must hold. Safety is never skippable via env configuration.
"""

from __future__ import annotations

import os
import tempfile

import pytest

from quant_us.live.live_pilot_approval import HumanApprovalGate


# ---------------------------------------------------------------------------
# QUANT_LIVE_SUBMISSION_ENABLED=true does not bypass approval gate
# ---------------------------------------------------------------------------


class TestEnvVarDoesNotBypassApprovalGate:
    def test_approval_gate_still_blocks_without_approval(self, monkeypatch) -> None:
        """Setting QUANT_LIVE_SUBMISSION_ENABLED=true does not bypass approval."""
        monkeypatch.setenv("QUANT_LIVE_SUBMISSION_ENABLED", "true")
        with tempfile.TemporaryDirectory() as td:
            gate = HumanApprovalGate(store_path=td)
            result = gate.check(approval_id="")
            assert not result.passed
            assert "No approval_id" in result.reason

    def test_approval_gate_still_blocks_nonexistent(self, monkeypatch) -> None:
        """QUANT_LIVE_SUBMISSION_ENABLED=true does not bypass missing approval."""
        monkeypatch.setenv("QUANT_LIVE_SUBMISSION_ENABLED", "true")
        with tempfile.TemporaryDirectory() as td:
            gate = HumanApprovalGate(store_path=td)
            result = gate.check(approval_id="nonexistent")
            assert not result.passed
            assert "not found" in result.reason

    def test_approval_gate_still_blocks_draft(self, monkeypatch) -> None:
        """QUANT_LIVE_SUBMISSION_ENABLED=true does not bypass DRAFT status."""
        monkeypatch.setenv("QUANT_LIVE_SUBMISSION_ENABLED", "true")
        with tempfile.TemporaryDirectory() as td:
            gate = HumanApprovalGate(store_path=td)
            gate.create(approval_id="draft_test")
            result = gate.check(approval_id="draft_test")
            assert not result.passed
            assert "DRAFT" in result.reason

    def test_approval_gate_still_blocks_expired(self, monkeypatch) -> None:
        """QUANT_LIVE_SUBMISSION_ENABLED=true does not bypass expiry."""
        from datetime import datetime, timedelta, timezone

        monkeypatch.setenv("QUANT_LIVE_SUBMISSION_ENABLED", "true")
        with tempfile.TemporaryDirectory() as td:
            gate = HumanApprovalGate(store_path=td)
            gate.create(approval_id="exp_test")
            past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
            approval = gate.inspect("exp_test")
            assert approval is not None
            approval.status = "APPROVED"
            approval.expires_at = past
            gate._save_approval(approval)
            result = gate.check(approval_id="exp_test")
            assert not result.passed
            assert "expired" in result.reason


# ---------------------------------------------------------------------------
# Env vars do not bypass risk envelope
# ---------------------------------------------------------------------------


class TestEnvVarDoesNotBypassRiskEnvelope:
    def test_risk_envelope_still_validates_with_env_true(self, monkeypatch) -> None:
        """Risk envelope validation still runs even with env set."""
        from quant_us.core.enums import OrderSide, OrderType
        from quant_us.live.live_pilot_risk_envelope import (
            LivePilotRiskEnvelope,
            RiskEnvelopeManager,
        )

        monkeypatch.setenv("QUANT_LIVE_SUBMISSION_ENABLED", "true")
        with tempfile.TemporaryDirectory() as td:
            mgr = RiskEnvelopeManager(store_path=td)
            env = LivePilotRiskEnvelope(
                envelope_id="env_test",
                max_order_notional=100.0,
            )
            mgr.create(env)
            result = mgr.validate(
                envelope_id="env_test",
                order_notional=500.0,
            )
            assert result["passed"] is False
            assert "exceeds" in result.get("reason", "")

    def test_risk_envelope_reduce_only_with_env_true(self, monkeypatch) -> None:
        """Reduce-only on recon_fail still works with env set."""
        from quant_us.live.live_pilot_risk_envelope import (
            LivePilotRiskEnvelope,
            RiskEnvelopeManager,
        )

        monkeypatch.setenv("QUANT_LIVE_SUBMISSION_ENABLED", "true")
        with tempfile.TemporaryDirectory() as td:
            mgr = RiskEnvelopeManager(store_path=td)
            env = LivePilotRiskEnvelope(
                envelope_id="env_ro",
                force_stop_on_recon_fail=True,
            )
            mgr.create(env)
            result = mgr.validate(
                envelope_id="env_ro",
                recon_fail=True,
            )
            assert result["reduce_only"] is True

    def test_risk_envelope_strict_regardless_of_env(self, monkeypatch) -> None:
        """Market orders are still blocked by OrderTypeValidator regardless of env."""
        from quant_us.core.enums import OrderSide, OrderType
        from quant_us.live.live_pilot_risk_envelope import (
            LivePilotRiskEnvelope,
            OrderTypeValidator,
        )

        monkeypatch.setenv("QUANT_LIVE_SUBMISSION_ENABLED", "true")
        validator = OrderTypeValidator()
        env = LivePilotRiskEnvelope.default_conservative("test")
        result = validator.check(env, OrderType.MARKET, OrderSide.BUY)
        assert result.passed is False


# ---------------------------------------------------------------------------
# allow_live_orders / confirm_live vars do NOT bypass approval
# ---------------------------------------------------------------------------


class TestOtherEnvVarsDoNotBypass:
    def test_allow_live_orders_does_not_bypass_approval(self, monkeypatch) -> None:
        """allow_live_orders=true does not bypass approval gate."""
        monkeypatch.setenv("allow_live_orders", "true")
        with tempfile.TemporaryDirectory() as td:
            gate = HumanApprovalGate(store_path=td)
            result = gate.check(approval_id="")
            assert not result.passed

    def test_confirm_live_does_not_bypass_approval(self, monkeypatch) -> None:
        """confirm_live=true does not bypass approval gate."""
        monkeypatch.setenv("confirm_live", "true")
        with tempfile.TemporaryDirectory() as td:
            gate = HumanApprovalGate(store_path=td)
            result = gate.check(approval_id="")
            assert not result.passed

    def test_multiple_env_vars_do_not_bypass(self, monkeypatch) -> None:
        """All env vars set simultaneously still do not bypass approval."""
        monkeypatch.setenv("QUANT_LIVE_SUBMISSION_ENABLED", "true")
        monkeypatch.setenv("allow_live_orders", "true")
        monkeypatch.setenv("confirm_live", "true")
        with tempfile.TemporaryDirectory() as td:
            gate = HumanApprovalGate(store_path=td)
            result = gate.check(approval_id="")
            assert not result.passed


# ---------------------------------------------------------------------------
# Dry-run still real_submit=False regardless of env
# ---------------------------------------------------------------------------


class TestDryRunStillDryWithEnv:
    def test_dry_run_real_submit_false_even_with_env_true(self, monkeypatch) -> None:
        """Dry-run executor always produces real_submit=False regardless of env."""
        from quant_us.live.live_pilot_dry_run import LiveOrderDryRunRecord

        monkeypatch.setenv("QUANT_LIVE_SUBMISSION_ENABLED", "true")
        record = LiveOrderDryRunRecord(dry_run_id="test")
        assert record.real_submit is False

    def test_100_records_all_false_with_env(self, monkeypatch) -> None:
        """Even with env set, 100 records all have real_submit=False."""
        from quant_us.live.live_pilot_dry_run import LiveOrderDryRunRecord

        monkeypatch.setenv("QUANT_LIVE_SUBMISSION_ENABLED", "true")
        for i in range(100):
            record = LiveOrderDryRunRecord(dry_run_id=f"dr_{i}")
            assert record.real_submit is False

    def test_dry_run_report_still_no_real_orders(self, monkeypatch) -> None:
        """DryRunReport.to_dict() still has real_submit_occurred=False with env."""
        from quant_us.live.live_pilot_dry_run import DryRunReport

        monkeypatch.setenv("QUANT_LIVE_SUBMISSION_ENABLED", "true")
        report = DryRunReport(dry_run_id="test")
        d = report.to_dict()
        assert d["real_submit_occurred"] is False
        assert d["no_real_order_submitted"] is True


# ---------------------------------------------------------------------------
# HumanApprovalGate.check still requires valid approval regardless of env
# ---------------------------------------------------------------------------


class TestApprovalGateAlwaysRequired:
    def test_still_needs_approval_with_all_env(self, monkeypatch) -> None:
        """Gate.check returns passed=False when no valid approval exists, even with env."""
        monkeypatch.setenv("QUANT_LIVE_SUBMISSION_ENABLED", "true")
        monkeypatch.setenv("allow_live_orders", "true")
        monkeypatch.setenv("confirm_live", "true")
        with tempfile.TemporaryDirectory() as td:
            gate = HumanApprovalGate(store_path=td)
            gate.create(approval_id="req_test")
            result = gate.check(approval_id="req_test")
            assert not result.passed
            assert "DRAFT" in result.reason

    def test_valid_approval_still_passes_with_env(self, monkeypatch) -> None:
        """A valid approved approval still passes even with env set."""
        monkeypatch.setenv("QUANT_LIVE_SUBMISSION_ENABLED", "true")
        with tempfile.TemporaryDirectory() as td:
            gate = HumanApprovalGate(store_path=td)
            gate.create(approval_id="valid_test")
            gate.approve(approval_id="valid_test", approver="admin")
            result = gate.check(approval_id="valid_test")
            assert result.passed


# ---------------------------------------------------------------------------
# ReadOnlyLiveBrokerProxy blocks even with env
# ---------------------------------------------------------------------------


class TestReadOnlyLiveBrokerBlocksWithEnv:
    def test_readonly_broker_blocks_even_with_env(self, monkeypatch) -> None:
        """ReadOnlyLiveBrokerProxy.submit_order raises even with env set."""
        from datetime import datetime, timezone
        from unittest.mock import MagicMock

        from quant_us.core.enums import OrderSide as OS, OrderType as OT, TimeInForce as TIF
        from quant_us.core.types import Order
        from quant_us.execution.broker_base import BrokerBase
        from quant_us.live.readonly_live_broker import ReadOnlyLiveBrokerProxy

        monkeypatch.setenv("QUANT_LIVE_SUBMISSION_ENABLED", "true")

        inner = MagicMock()
        inner.broker_name = "alpaca"
        proxy = ReadOnlyLiveBrokerProxy(inner)

        order = Order(
            timestamp_utc=datetime.now(timezone.utc),
            strategy_id="test",
            symbol="SPY",
            side=OS.BUY,
            quantity=1.0,
            order_type=OT.LIMIT,
            time_in_force=TIF.DAY,
            client_order_id="test",
        )
        with pytest.raises(RuntimeError, match="FORBIDDEN|blocked|read.only|read-only"):
            proxy.submit_order(order)
