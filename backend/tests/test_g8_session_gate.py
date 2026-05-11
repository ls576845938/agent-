"""Tests for G8 SessionGate.

All tests use tmp_path for data isolation. No real broker calls.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from quant_us.live.g8_session_gate import SessionGate, SessionGateDecision
from quant_us.live.g8_session_state import SessionRuntimeStateManager


class TestSessionGate:
    """Tests for SessionGate check logic and safety invariants."""

    def _create_approved_promotion(self, tmp_path: Path, promo_id: str = "promo_test") -> str:
        """Helper: create an approved promotion manifest using G8 gate."""
        gate = SessionGate(data_root=str(tmp_path))
        gate.create_promotion(promo_id)
        gate.approve_promotion(promo_id)
        return promo_id

    def _setup_armed_session(self, tmp_path: Path) -> tuple[SessionGate, str, str]:
        """Helper: create a session with approved promotion in ARMED state."""
        gate = SessionGate(data_root=str(tmp_path))
        state_mgr = SessionRuntimeStateManager(data_root=str(tmp_path))
        promo_id = self._create_approved_promotion(tmp_path)

        # Create and arm session
        session = state_mgr.create(promotion_id=promo_id)
        state_mgr.arm(session.session_id)

        return gate, session.session_id, promo_id

    def test_gate_blocks_dry_run(self, tmp_path: Path) -> None:
        """dry_run -> BLOCKED."""
        gate, session_id, promo_id = self._setup_armed_session(tmp_path)
        decision = gate.check(
            session_id=session_id,
            promotion_id=promo_id,
            ticket_id="ticket_1",
            manual_confirm=True,
            dry_run=True,
        )
        assert decision.decision == "BLOCKED"
        assert "dry_run_mode" in decision.block_reasons

    def test_gate_blocks_missing_confirm(self, tmp_path: Path) -> None:
        """manual_confirm=False -> BLOCKED."""
        gate, session_id, promo_id = self._setup_armed_session(tmp_path)
        decision = gate.check(
            session_id=session_id,
            promotion_id=promo_id,
            ticket_id="ticket_1",
            manual_confirm=False,
            dry_run=False,
        )
        assert decision.decision == "BLOCKED"
        assert "missing_manual_confirm" in decision.block_reasons

    def test_gate_blocks_promotion_not_approved(self, tmp_path: Path) -> None:
        """Promotion not yet approved -> BLOCKED."""
        gate = SessionGate(data_root=str(tmp_path))
        state_mgr = SessionRuntimeStateManager(data_root=str(tmp_path))

        # Create promotion but don't approve (stays DRAFT)
        gate.create_promotion("promo_draft")

        session = state_mgr.create(promotion_id="promo_draft")
        state_mgr.arm(session.session_id)

        decision = gate.check(
            session_id=session.session_id,
            promotion_id="promo_draft",
            ticket_id="ticket_1",
            manual_confirm=True,
            dry_run=False,
        )
        # Promotion is DRAFT, not APPROVED_FOR_G8_REVIEW
        assert decision.decision == "BLOCKED"

    def test_gate_blocks_session_not_armed(self, tmp_path: Path) -> None:
        """Session in DRAFT (not armed) -> BLOCKED."""
        gate = SessionGate(data_root=str(tmp_path))
        state_mgr = SessionRuntimeStateManager(data_root=str(tmp_path))
        promo_id = self._create_approved_promotion(tmp_path)
        session = state_mgr.create(promotion_id=promo_id)
        # Don't arm it

        decision = gate.check(
            session_id=session.session_id,
            promotion_id=promo_id,
            ticket_id="ticket_1",
            manual_confirm=True,
            dry_run=False,
        )
        assert decision.decision == "BLOCKED"
        assert "session_not_armed" in decision.block_reasons

    def test_gate_blocks_frozen_session(self, tmp_path: Path) -> None:
        """FROZEN session -> BLOCKED."""
        gate, session_id, promo_id = self._setup_armed_session(tmp_path)
        state_mgr = SessionRuntimeStateManager(data_root=str(tmp_path))
        state_mgr.activate(session_id)
        state_mgr.freeze(session_id, reason="ORDER_SUBMITTED")

        decision = gate.check(
            session_id=session_id,
            promotion_id=promo_id,
            ticket_id="ticket_1",
            manual_confirm=True,
            dry_run=False,
        )
        assert decision.decision == "BLOCKED"
        assert "session_frozen" in decision.block_reasons

    def test_gate_blocks_daily_order_exceeded(self, tmp_path: Path) -> None:
        """Daily order limit exceeded -> BLOCKED."""
        gate, session_id, promo_id = self._setup_armed_session(tmp_path)
        from datetime import date
        today = date.today().isoformat()

        # Record enough orders to exceed daily cap
        cap_mgr = gate.cap_mgr
        cap_mgr.get_or_create(session_id, today)
        cap = cap_mgr.load(session_id, today)
        assert cap is not None
        # Manually set orders_submitted_today to max
        cap.orders_submitted_today = cap.max_orders_today
        cap_mgr._save(cap)

        decision = gate.check(
            session_id=session_id,
            promotion_id=promo_id,
            ticket_id="ticket_1",
            manual_confirm=True,
            dry_run=False,
        )
        assert decision.decision == "BLOCKED"
        assert any("max_orders_per_day" in r for r in decision.block_reasons)

    def test_gate_blocks_emergency_stop(self, tmp_path: Path) -> None:
        """Session with emergency stop -> BLOCKED."""
        gate, session_id, promo_id = self._setup_armed_session(tmp_path)
        state_mgr = SessionRuntimeStateManager(data_root=str(tmp_path))
        state = state_mgr.load(session_id)
        assert state is not None
        state.emergency_stop_count = 1
        state_mgr._save(state)

        decision = gate.check(
            session_id=session_id,
            promotion_id=promo_id,
            ticket_id="ticket_1",
            manual_confirm=True,
            dry_run=False,
        )
        assert decision.decision == "BLOCKED"
        assert "emergency_stop_triggered" in decision.block_reasons

    def test_gate_blocks_reconciliation_dirty(self, tmp_path: Path) -> None:
        """Reconciliation failures -> BLOCKED."""
        gate, session_id, promo_id = self._setup_armed_session(tmp_path)
        state_mgr = SessionRuntimeStateManager(data_root=str(tmp_path))
        state = state_mgr.load(session_id)
        assert state is not None
        state.recon_fail_count = 1
        state_mgr._save(state)

        decision = gate.check(
            session_id=session_id,
            promotion_id=promo_id,
            ticket_id="ticket_1",
            manual_confirm=True,
            dry_run=False,
        )
        assert decision.decision == "BLOCKED"
        assert "reconciliation_dirty" in decision.block_reasons

    def test_gate_blocks_missing_ticket(self, tmp_path: Path) -> None:
        """Missing ticket_id -> BLOCKED."""
        gate, session_id, promo_id = self._setup_armed_session(tmp_path)
        decision = gate.check(
            session_id=session_id,
            promotion_id=promo_id,
            ticket_id="",
            manual_confirm=True,
            dry_run=False,
        )
        assert decision.decision == "BLOCKED"
        assert "missing_ticket" in decision.block_reasons

    def test_gate_passes_when_all_clean(self, tmp_path: Path) -> None:
        """All checks pass -> APPROVED_FOR_SESSION_ONE_SHOT."""
        gate, session_id, promo_id = self._setup_armed_session(tmp_path)

        # Must activate to ACTIVE_MANUAL_SUPERVISION to pass session state check
        # ARMED status alone won't pass (check expects ARMED or ACTIVE_MANUAL_SUPERVISION)
        # Actually ARMED should pass too per the check logic
        decision = gate.check(
            session_id=session_id,
            promotion_id=promo_id,
            ticket_id="ticket_1",
            manual_confirm=True,
            dry_run=False,
        )
        assert decision.decision == "APPROVED_FOR_SESSION_ONE_SHOT"
        assert decision.block_reasons == []

    def test_gate_never_calls_submit_order(self, tmp_path: Path) -> None:
        """Safety invariant: SessionGate has no submit_order."""
        import inspect
        import quant_us.live.g8_session_gate as mod
        source = inspect.getsource(mod)
        assert "submit_order" not in source
        assert "broker.submit" not in source
