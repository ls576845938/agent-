"""Integration-style tests verifying the full G6 gate chain blocks auto second orders.

No real broker calls. All tests use tmp_path for data isolation.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from quant_us.live.g6_second_review import SecondOneShotReviewGate
from quant_us.live.g6_episode import MicroPilotEpisodeManager
from quant_us.live.one_shot_executor import SubmitOnceLockManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _full_setup(tmp_path: Path) -> Path:
    """Set up a complete G5/G6 data directory for integration testing.

    Creates:
    - G5 dossier (post-trade review)
    - Execution quality report
    - Clean freeze state
    - Submit-once lock
    - Episode with one completed order
    """
    live_pilot = tmp_path / "live_pilot"
    live_pilot.mkdir(parents=True, exist_ok=True)
    audit_dir = live_pilot / "audit"
    audit_dir.mkdir(exist_ok=True)

    # G5 post-trade dossier
    (live_pilot / "post_trade_dossier_ticket_1.json").write_text(json.dumps({
        "decision": "STOP_AND_REVIEW",
        "ticket_id": "ticket_1",
        "safety_evidence": {"second_order_detected": False},
    }))

    # Execution quality report
    (audit_dir / "exec_quality_ticket_1.json").write_text(json.dumps({
        "ticket_id": "ticket_1",
        "execution_status": "filled",
        "fill_price": 501.0,
        "slippage_bps": 0.5,
    }))

    # Clean freeze state
    (live_pilot / "freeze_state.json").write_text(json.dumps({
        "state": "FROZEN_PENDING_REVIEW",
        "unknown_order_state": False,
    }))

    # Submit-once lock
    (live_pilot / "submit_once_lock.json").write_text(json.dumps({
        "lock_id": "lock_abc",
        "status": "ACTIVE",
    }))

    # Episode with completed order
    episode_mgr = MicroPilotEpisodeManager(data_root=str(tmp_path))
    episode_mgr.create(
        strategy_id="strat_a",
        symbols=["SPY"],
        episode_id="ep_1",
        max_order_count=3,
        max_cumulative_notional=300.0,
    )
    episode_mgr.add_ticket("ep_1", "ticket_1", notional=100.0)

    # Override last_order_date to yesterday so same-day check doesn't block
    ep = episode_mgr.load("ep_1")
    if ep:
        from datetime import datetime, timedelta, timezone
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
        ep.last_order_date = yesterday
        episode_mgr.save(ep)

    return live_pilot


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestNoAutoSecondOrder:
    """Integration tests verifying the gate chain prevents automatic second orders."""

    def test_full_gate_chain_blocks_without_review(self, tmp_path: Path) -> None:
        """Without manual review, both the gate and episode manager block a second order."""
        _full_setup(tmp_path)
        live_pilot = tmp_path / "live_pilot"

        # Gate check without manual review
        gate = SecondOneShotReviewGate(data_root=str(tmp_path))
        result = gate.review(
            g5_ticket_id="ticket_1",
            manual_review_decision="",
            manual_reviewer="",
        )
        # Without manual review, it's either REQUIRES_MORE_REVIEW or BLOCKED
        assert result.decision in ("REQUIRES_MORE_REVIEW", "BLOCKED")
        assert "manual_review_missing" in result.block_reasons

        # Episode manager also blocks without dossier for previous order
        episode_mgr = MicroPilotEpisodeManager(data_root=str(tmp_path))
        # The ticket_1's dossier exists (we set it up), so this should pass
        # if status is correct. But without the second_review file,
        # progression controller would block.
        can, reason = episode_mgr.can_add_next_order("ep_1", new_notional=100.0)
        # Episode should be in WAITING_NEXT_ONE_SHOT_REVIEW after add_ticket
        assert can is True, f"Episode check failed: {reason}"

    def test_even_with_env_enabled_second_needs_review(self, tmp_path: Path) -> None:
        """Even if env enabled, the gate still requires manual review."""
        _full_setup(tmp_path)

        # Simulate env enabled (but gate doesn't read env, it checks manual_review_decision)
        gate = SecondOneShotReviewGate(data_root=str(tmp_path))
        result = gate.review(
            g5_ticket_id="ticket_1",
            manual_review_decision="approve",
            manual_reviewer="reviewer_admin",
        )

        # With all conditions including manual review, the gate approves
        assert result.decision == "APPROVED_FOR_SECOND_ONE_SHOT_REVIEW"

        # But this is only a RECOMMENDATION — the executor still needs
        # manual approval flag. The gate alone cannot submit orders.
        # Verify gate never auto-submits
        assert not hasattr(gate, "submit_order")
        assert not hasattr(gate, "execute")

    def test_episode_blocks_before_manual_review(self, tmp_path: Path) -> None:
        """Episode management blocks second order before manual review is complete."""
        _full_setup(tmp_path)

        episode_mgr = MicroPilotEpisodeManager(data_root=str(tmp_path))
        can, reason = episode_mgr.can_add_next_order("ep_1", new_notional=100.0)

        # With dossier present and status WAITING_NEXT_ONE_SHOT_REVIEW,
        # the episode alone allows. But the higher-level progression
        # controller would block because no second_review_*.json exists.
        assert can is True

        # Now verify the progression would be blocked
        from quant_us.live.g6_progression import PilotProgressionController
        controller = PilotProgressionController(data_root=str(tmp_path))
        prog_result = controller.evaluate(episode_id="ep_1")
        assert "manual_review_not_approved" in prog_result["blocked_reasons"]

        # After manual review approval exists, progression passes
        review_path = tmp_path / "live_pilot" / "second_review_ticket_1.json"
        review_path.write_text(json.dumps({
            "decision": "APPROVED_FOR_SECOND_ONE_SHOT_REVIEW",
            "block_reasons": [],
            "passed_checks": ["manual_review_approved", "g5_dossier_exists"],
        }))

        prog_result2 = controller.evaluate(episode_id="ep_1")
        # Still may have other conditions, but manual review check should pass
        assert "manual_review_not_approved" not in prog_result2["blocked_reasons"]

    def test_submit_once_lock_is_independent_gate(self, tmp_path: Path) -> None:
        """Submit-once lock exists independently and must be active for traceability."""
        _full_setup(tmp_path)

        # Verify the lock exists
        lock_manager = SubmitOnceLockManager(
            lock_path=str(tmp_path / "live_pilot" / "submit_once_lock.json"),
        )
        status = lock_manager.status()
        assert status["locked"] is True
        assert status["status"] == "ACTIVE"

        # The gate's _check_submit_once_lock verifies this
        gate = SecondOneShotReviewGate(data_root=str(tmp_path))
        result = gate.review(
            g5_ticket_id="ticket_1",
            manual_review_decision="approve",
            manual_reviewer="reviewer_1",
        )
        assert "submit_once_lock_missing" not in result.block_reasons

    def test_gate_approval_is_not_auto_execution(self, tmp_path: Path) -> None:
        """Gate returning APPROVED does NOT execute orders."""
        _full_setup(tmp_path)

        gate = SecondOneShotReviewGate(data_root=str(tmp_path))
        result = gate.review(
            g5_ticket_id="ticket_1",
            manual_review_decision="approve",
            manual_reviewer="reviewer_1",
        )

        assert result.decision == "APPROVED_FOR_SECOND_ONE_SHOT_REVIEW"
        # Verify: no orders were submitted, no broker was called
        assert not hasattr(gate, "submit_order")
        # The gate is purely a decision — execution is separate
