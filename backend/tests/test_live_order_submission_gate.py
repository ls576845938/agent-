"""Test LiveOrderSubmissionGate and SubmissionGateDecision for G4.

Every block reason is verified independently. The "all gates pass" test
mocks HumanApprovalGate and RiskEnvelopeManager so that approval_id and
envelope_id are validated successfully.
ALL tests use tempfile for audit storage.
"""

from __future__ import annotations

import tempfile
from unittest.mock import MagicMock, patch

import pytest

from quant_us.live.live_order_submission_gate import (
    LiveOrderSubmissionGate,
    SubmissionGateDecision,
)


# ---------------------------------------------------------------------------
# Gate decision model
# ---------------------------------------------------------------------------


class TestSubmissionGateDecision:
    def test_approved_property(self) -> None:
        d = SubmissionGateDecision(decision="APPROVED_FOR_SUBMIT")
        assert d.approved is True
        assert d.blocked is False

    def test_blocked_property(self) -> None:
        d = SubmissionGateDecision(decision="BLOCKED", block_reasons=["dry_run_mode"])
        assert d.approved is False
        assert d.blocked is True

    def test_to_dict_includes_fields(self) -> None:
        d = SubmissionGateDecision(
            decision="BLOCKED",
            block_reasons=["r1", "r2"],
            warnings=["w1"],
        )
        dd = d.to_dict()
        assert dd["decision"] == "BLOCKED"
        assert "r1" in dd["block_reasons"]
        assert "w1" in dd["warnings"]
        assert "gate_version" in dd
        assert "checked_at" in dd


# ---------------------------------------------------------------------------
# Submission gate check
# ---------------------------------------------------------------------------


class TestLiveOrderSubmissionGateCheck:
    def _gate(self, td: str) -> LiveOrderSubmissionGate:
        return LiveOrderSubmissionGate(audit_dir=td)

    def test_dry_run_blocked(self) -> None:
        """is_dry_run=True immediately returns BLOCKED with dry_run_mode."""
        with tempfile.TemporaryDirectory() as td:
            g = self._gate(td)
            d = g.check(is_dry_run=True)
            assert d.blocked
            assert "dry_run_mode" in d.block_reasons

    def test_execute_live_pilot_false_blocked(self) -> None:
        """execute_live_pilot=False returns BLOCKED with execute_live_pilot_not_set."""
        with tempfile.TemporaryDirectory() as td:
            g = self._gate(td)
            d = g.check(is_dry_run=False, execute_live_pilot=False)
            assert d.blocked
            assert "execute_live_pilot_not_set" in d.block_reasons

    def test_missing_approval_blocked(self) -> None:
        """Empty approval_id adds missing_approval to block reasons."""
        with tempfile.TemporaryDirectory() as td:
            g = self._gate(td)
            d = g.check(
                is_dry_run=False,
                execute_live_pilot=True,
                approval_id="",
            )
            assert "missing_approval" in d.block_reasons

    def test_missing_envelope_blocked(self) -> None:
        """Empty envelope_id adds missing_envelope to block reasons."""
        with tempfile.TemporaryDirectory() as td:
            g = self._gate(td)
            d = g.check(
                is_dry_run=False,
                execute_live_pilot=True,
                envelope_id="",
            )
            assert "missing_envelope" in d.block_reasons

    def test_env_disabled_blocked(self) -> None:
        """env_enabled=False adds env_gate_disabled to block reasons."""
        with tempfile.TemporaryDirectory() as td:
            g = self._gate(td)
            d = g.check(
                is_dry_run=False,
                execute_live_pilot=True,
                env_enabled=False,
                approval_id="",
                envelope_id="",
            )
            assert "env_gate_disabled" in d.block_reasons

    def test_missing_confirm_live_blocked(self) -> None:
        """confirm_live=False adds missing_confirm_live to block reasons."""
        with tempfile.TemporaryDirectory() as td:
            g = self._gate(td)
            d = g.check(
                is_dry_run=False,
                execute_live_pilot=True,
                confirm_live=False,
                approval_id="",
                envelope_id="",
            )
            assert "missing_confirm_live" in d.block_reasons

    def test_allow_live_false_blocked(self) -> None:
        """allow_live=False adds allow_live_orders_false to block reasons."""
        with tempfile.TemporaryDirectory() as td:
            g = self._gate(td)
            d = g.check(
                is_dry_run=False,
                execute_live_pilot=True,
                allow_live=False,
                approval_id="",
                envelope_id="",
            )
            assert "allow_live_orders_false" in d.block_reasons

    def test_order_type_not_allowed_blocked(self) -> None:
        """Unsupported order type adds order_type_not_allowed."""
        with tempfile.TemporaryDirectory() as td:
            g = self._gate(td)
            d = g.check(
                is_dry_run=False,
                execute_live_pilot=True,
                order_type="market",
                allowed_order_types=["limit"],
                approval_id="",
                envelope_id="",
            )
            assert "order_type_not_allowed" in d.block_reasons

    def test_notional_exceeded_blocked(self) -> None:
        """order_notional > max_order_notional adds notional_exceeded."""
        with tempfile.TemporaryDirectory() as td:
            g = self._gate(td)
            d = g.check(
                is_dry_run=False,
                execute_live_pilot=True,
                order_notional=500.0,
                max_order_notional=100.0,
                approval_id="",
                envelope_id="",
            )
            assert "notional_exceeded" in d.block_reasons

    def test_kill_switch_active_blocked(self) -> None:
        """kill_switch_active=True adds kill_switch_active to block reasons."""
        with tempfile.TemporaryDirectory() as td:
            g = self._gate(td)
            d = g.check(
                is_dry_run=False,
                execute_live_pilot=True,
                kill_switch_active=True,
                approval_id="",
                envelope_id="",
            )
            assert "kill_switch_active" in d.block_reasons

    def test_emergency_stop_triggered_blocked(self) -> None:
        """emergency_stop_triggered=True adds emergency_stop_triggered."""
        with tempfile.TemporaryDirectory() as td:
            g = self._gate(td)
            d = g.check(
                is_dry_run=False,
                execute_live_pilot=True,
                emergency_stop_triggered=True,
                approval_id="",
                envelope_id="",
            )
            assert "emergency_stop_triggered" in d.block_reasons

    def test_all_gates_pass_still_requires_manual_review(self) -> None:
        """When all gate conditions pass, decision remains REQUIRES_MANUAL_REVIEW."""
        with tempfile.TemporaryDirectory() as td:
            with patch(
                "quant_us.live.live_pilot_approval.HumanApprovalGate"
            ) as mock_hag_cls:
                mock_hag = MagicMock()
                mock_hag.check.return_value = MagicMock(
                    passed=True,
                    reason="ok",
                    checks={"status_approved": True, "not_expired": True},
                )
                mock_hag_cls.return_value = mock_hag

                with patch(
                    "quant_us.live.live_pilot_risk_envelope.RiskEnvelopeManager"
                ) as mock_rem_cls:
                    mock_rem = MagicMock()
                    mock_env = MagicMock()
                    mock_env.max_order_notional = 10000.0
                    mock_env.max_daily_notional = 50000.0
                    mock_env.max_daily_order_count = 3
                    mock_env.allow_market_order = False
                    mock_env.reduce_only_on_warning = True
                    mock_env.symbols = ["SPY", "QQQ"]
                    mock_rem.load.return_value = mock_env
                    mock_rem_cls.return_value = mock_rem

                    g = self._gate(td)
                    d = g.check(
                        approval_id="test_approval",
                        envelope_id="test_env",
                        dossier_decision="GO_FOR_SMALL_LIVE_REVIEW",
                        env_enabled=True,
                        confirm_live=True,
                        allow_live=True,
                        execute_live_pilot=True,
                        is_dry_run=False,
                        live_endpoint_ok=True,
                        reconciliation_clean=True,
                        emergency_stop_armed=True,
                        emergency_stop_triggered=False,
                        in_regular_session=True,
                        order_type="limit",
                        allowed_order_types=["limit"],
                        order_notional=50.0,
                        max_order_notional=100.0,
                        oms_idempotency_ok=True,
                        kill_switch_active=False,
                        strategy_version="1.0.0",
                        approved_version="1.0.0",
                        symbol="SPY",
                        allowed_symbols=["SPY", "QQQ"],
                        current_daily_order_count=0,
                        max_daily_order_count=3,
                        reduce_only_exit_ready=True,
                        endpoint_guard_active=True,
                        read_only_acknowledged=True,
                    )
                    assert d.decision == "REQUIRES_MANUAL_REVIEW"
                    assert d.approved is False
                    assert "review_only_surface_no_automatic_submission" in d.warnings

    def test_symbol_allowlist_violation_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            with patch(
                "quant_us.live.live_pilot_approval.HumanApprovalGate"
            ) as mock_hag_cls:
                mock_hag = MagicMock()
                mock_hag.check.return_value = MagicMock(
                    passed=True,
                    reason="ok",
                    checks={"status_approved": True, "not_expired": True},
                )
                mock_hag_cls.return_value = mock_hag

                with patch(
                    "quant_us.live.live_pilot_risk_envelope.RiskEnvelopeManager"
                ) as mock_rem_cls:
                    mock_rem = MagicMock()
                    mock_env = MagicMock()
                    mock_env.max_order_notional = 10000.0
                    mock_env.max_daily_notional = 50000.0
                    mock_env.max_daily_order_count = 3
                    mock_env.allow_market_order = False
                    mock_env.reduce_only_on_warning = True
                    mock_env.symbols = ["SPY"]
                    mock_rem.load.return_value = mock_env
                    mock_rem_cls.return_value = mock_rem

                    g = self._gate(td)
                    d = g.check(
                        approval_id="test_approval",
                        envelope_id="test_env",
                        dossier_decision="READY_FOR_HUMAN_REVIEW",
                        env_enabled=True,
                        confirm_live=True,
                        allow_live=True,
                        execute_live_pilot=True,
                        is_dry_run=False,
                        live_endpoint_ok=True,
                        reconciliation_clean=True,
                        emergency_stop_armed=True,
                        emergency_stop_triggered=False,
                        in_regular_session=True,
                        order_type="limit",
                        allowed_order_types=["limit"],
                        order_notional=50.0,
                        max_order_notional=100.0,
                        oms_idempotency_ok=True,
                        kill_switch_active=False,
                        symbol="QQQ",
                        allowed_symbols=["SPY"],
                        current_daily_order_count=0,
                        max_daily_order_count=3,
                        reduce_only_exit_ready=True,
                        endpoint_guard_active=True,
                        read_only_acknowledged=True,
                    )
                    assert d.blocked
                    assert "symbol_not_allowed" in d.block_reasons

    def test_missing_reduce_only_exit_plan_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            g = self._gate(td)
            d = g.check(
                is_dry_run=False,
                execute_live_pilot=True,
                approval_id="",
                envelope_id="",
                reduce_only_exit_ready=False,
            )
            assert d.blocked
            assert "reduce_only_exit_plan_missing" in d.block_reasons


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------


class TestLiveOrderSubmissionGateAudit:
    def test_audit_written_for_every_check(self) -> None:
        """Every gate.check call writes an audit entry."""
        with tempfile.TemporaryDirectory() as td:
            g = LiveOrderSubmissionGate(audit_dir=td)
            g.check(is_dry_run=True)
            g.check(is_dry_run=False, execute_live_pilot=False)
            entries = g.read_audit()
            assert len(entries) == 2
            assert all(e["decision"] == "BLOCKED" for e in entries)

    def test_read_audit_returns_entries(self) -> None:
        """read_audit returns list of dict entries, newest entries last."""
        with tempfile.TemporaryDirectory() as td:
            g = LiveOrderSubmissionGate(audit_dir=td)
            assert g.read_audit() == []  # initially empty
            g.check(is_dry_run=True)
            entries = g.read_audit()
            assert len(entries) == 1
            entry = entries[0]
            assert entry["gate_version"] == "g4_v1.0.0"
            assert "timestamp" in entry
            assert entry["decision"] == "BLOCKED"
            assert "dry_run_mode" in entry["reasons"]
