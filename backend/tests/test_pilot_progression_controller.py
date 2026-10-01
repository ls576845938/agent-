"""Tests for G6 PilotProgressionController.

All tests use tmp_path for data isolation. No real broker calls.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from quant_us.live.g6_episode import MicroPilotEpisodeManager
from quant_us.live.g6_progression import PilotProgressionController


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _setup_episode_with_order(
    tmp_path: Path,
    episode_id: str = "ep_1",
    ticket_id: str = "ticket_1",
) -> None:
    """Create an episode with one completed order and fake dossier."""
    mgr = MicroPilotEpisodeManager(data_root=str(tmp_path))
    mgr.create(
        strategy_id="strat_a",
        symbols=["SPY"],
        episode_id=episode_id,
        max_order_count=3,
        max_cumulative_notional=300.0,
    )
    mgr.add_ticket(episode_id, ticket_id, notional=100.0)

    live_pilot = tmp_path / "live_pilot"

    # Create audit directory (needed for traceable orders check)
    audit_dir = live_pilot / "audit"
    audit_dir.mkdir(parents=True, exist_ok=True)

    # Create a dossier to simulate G5 review
    dossier_path = live_pilot / f"post_trade_dossier_{ticket_id}.json"
    dossier_path.write_text(json.dumps({
        "ticket_id": ticket_id,
        "decision": "STOP_AND_REVIEW",
        "pre_trade_evidence": {"approved": True},
        "order_evidence": {"broker_order_id": "broker_123"},
        "execution_evidence": {"execution_status": "filled", "fill_price": 501.0},
        "safety_evidence": {"submit_once_active": True, "freeze_active": True},
    }))


def _setup_second_review(
    tmp_path: Path,
    ticket_id: str = "ticket_1",
    decision: str = "APPROVED_FOR_SECOND_ONE_SHOT_REVIEW",
) -> None:
    """Create a second review file to simulate manual review approval."""
    live_pilot = tmp_path / "live_pilot"
    review_path = live_pilot / f"second_review_{ticket_id}.json"
    review_path.write_text(json.dumps({
        "decision": decision,
        "block_reasons": [],
        "passed_checks": ["manual_review_approved"],
    }))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestPilotProgressionController:
    """Tests for PilotProgressionController safety invariants."""

    def test_no_g5_review_blocks_progression(self, tmp_path: Path) -> None:
        """Episode with no tickets → blocked."""
        mgr = MicroPilotEpisodeManager(data_root=str(tmp_path))
        mgr.create(
            strategy_id="strat_a",
            symbols=["SPY"],
            episode_id="ep_no_review",
        )

        controller = PilotProgressionController(data_root=str(tmp_path))
        result = controller.evaluate(episode_id="ep_no_review")
        assert result["progression_status"] != "READY_FOR_G7_REVIEW"
        assert "no_completed_orders" in result["blocked_reasons"]

    def test_unresolved_incident_blocks_progression(self, tmp_path: Path) -> None:
        """Emergency stop triggered → blocked with unresolved_incidents."""
        _setup_episode_with_order(tmp_path, episode_id="ep_incident")
        _setup_second_review(tmp_path)

        from quant_us.live.emergency_stop import EmergencyStopController
        ctrl = EmergencyStopController(state_dir=str(tmp_path / "live_pilot"))
        ctrl.trigger("recon_fail", triggered_by="test")

        controller = PilotProgressionController(data_root=str(tmp_path))
        result = controller.evaluate(episode_id="ep_incident")
        assert "unresolved_incidents" in result["blocked_reasons"]

    def test_recon_fail_blocks_progression(self, tmp_path: Path) -> None:
        """Freeze state non-FROZEN → blocked with recon_failures."""
        _setup_episode_with_order(tmp_path, episode_id="ep_recon")
        _setup_second_review(tmp_path)

        # Write non-clean freeze state
        live_pilot = tmp_path / "live_pilot"
        freeze_path = live_pilot / "freeze_state.json"
        freeze_path.write_text(json.dumps({"state": "UNKNOWN"}))

        controller = PilotProgressionController(data_root=str(tmp_path))
        result = controller.evaluate(episode_id="ep_recon")
        assert "recon_failures" in result["blocked_reasons"]

    def test_all_pass_returns_ready_for_review_not_auto_execute(self, tmp_path: Path) -> None:
        """All conditions met → READY_FOR_G7_REVIEW recommendation, not auto-advance."""
        _setup_episode_with_order(tmp_path, episode_id="ep_ready")
        _setup_second_review(tmp_path)

        controller = PilotProgressionController(data_root=str(tmp_path))
        result = controller.evaluate(episode_id="ep_ready")
        assert result["progression_status"] == "READY_FOR_G7_REVIEW"
        assert not result["blocked_reasons"]
        # Verify it's a recommendation, not an auto-advance
        assert "evaluated_at" in result

    def test_never_auto_advances(self, tmp_path: Path) -> None:
        """Controller has no method to change episode status."""
        controller = PilotProgressionController(data_root=str(tmp_path))
        assert not hasattr(controller, "advance")
        assert not hasattr(controller, "auto_advance")
        assert not hasattr(controller, "proceed")

    def test_never_calls_submit_order(self, tmp_path: Path) -> None:
        """Controller has no submit_order capability."""
        controller = PilotProgressionController(data_root=str(tmp_path))
        assert not hasattr(controller, "submit_order")
        assert not hasattr(controller, "_broker")
        assert not hasattr(controller, "broker")

    def test_episode_not_found_returns_blocked(self, tmp_path: Path) -> None:
        """Nonexistent episode → blocked."""
        controller = PilotProgressionController(data_root=str(tmp_path))
        result = controller.evaluate(episode_id="nonexistent")
        assert "no_completed_orders" in result["blocked_reasons"]

    def test_manual_review_not_approved_blocks(self, tmp_path: Path) -> None:
        """Episode with orders but no manual review → blocked."""
        _setup_episode_with_order(tmp_path, episode_id="ep_no_review_2")
        # Don't create second review

        controller = PilotProgressionController(data_root=str(tmp_path))
        result = controller.evaluate(episode_id="ep_no_review_2")
        assert "manual_review_not_approved" in result["blocked_reasons"]

    def test_status_returns_saved_state(self, tmp_path: Path) -> None:
        """status() returns the last evaluated state."""
        _setup_episode_with_order(tmp_path, episode_id="ep_status")
        _setup_second_review(tmp_path)

        controller = PilotProgressionController(data_root=str(tmp_path))
        controller.evaluate(episode_id="ep_status")

        state = controller.status()
        assert state["episode_id"] == "ep_status"
        assert state["progression_status"] == "READY_FOR_G7_REVIEW"

    def test_status_before_evaluate(self, tmp_path: Path) -> None:
        """status() before any evaluate() call returns NOT_EVALUATED."""
        controller = PilotProgressionController(data_root=str(tmp_path))
        state = controller.status()
        assert state["progression_status"] == "NOT_EVALUATED"

    def test_conditions_returned_in_result(self, tmp_path: Path) -> None:
        """Evaluate result includes detailed condition checks."""
        _setup_episode_with_order(tmp_path, episode_id="ep_conds")
        _setup_second_review(tmp_path)

        controller = PilotProgressionController(data_root=str(tmp_path))
        result = controller.evaluate(episode_id="ep_conds")
        conditions = result["conditions"]
        assert "at_least_one_order_completed" in conditions
        assert "all_orders_traceable" in conditions
        assert "no_duplicate_orders" in conditions
        assert "no_unresolved_incidents" in conditions
        assert "manual_review_approved" in conditions
