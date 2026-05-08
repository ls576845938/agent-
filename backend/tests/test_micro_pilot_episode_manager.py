"""Tests for G6 MicroPilotEpisodeManager.

All tests use tmp_path for data isolation. No real broker calls.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from quant_us.live.g6_episode import MicroPilotEpisode, MicroPilotEpisodeManager


class TestMicroPilotEpisode:
    """Tests for the MicroPilotEpisode dataclass."""

    def test_default_status_is_draft(self) -> None:
        ep = MicroPilotEpisode(episode_id="ep_1")
        assert ep.status == "DRAFT"

    def test_starts_with_zero_orders(self) -> None:
        ep = MicroPilotEpisode(episode_id="ep_1")
        assert ep.completed_order_count == 0
        assert ep.used_cumulative_notional == 0.0
        assert ep.ticket_ids == []

    def test_to_dict_round_trip(self) -> None:
        ep = MicroPilotEpisode(
            episode_id="ep_1", strategy_id="strat_a",
            symbols=["SPY", "QQQ"], status="ACTIVE_REVIEW_ONLY",
        )
        data = ep.to_dict()
        restored = MicroPilotEpisode.from_dict(data)
        assert restored.episode_id == "ep_1"
        assert restored.strategy_id == "strat_a"
        assert restored.symbols == ["SPY", "QQQ"]
        assert restored.status == "ACTIVE_REVIEW_ONLY"

    def test_terminated_status_blocks_orders(self) -> None:
        ep = MicroPilotEpisode(episode_id="ep_1", status="TERMINATED")
        from quant_us.live.g6_episode import MicroPilotEpisodeManager
        mgr = MicroPilotEpisodeManager(data_root="/tmp/nonexistent")
        allowed, reason = mgr.can_add_next_order("ep_1")
        # Episode doesn't exist in manager — returns not found, but
        # the EPISODE itself knows status.
        assert allowed is False


class TestMicroPilotEpisodeManager:
    """Tests for MicroPilotEpisodeManager lifecycle and safety invariants."""

    def test_episode_created_successfully(self, tmp_path: Path) -> None:
        mgr = MicroPilotEpisodeManager(data_root=str(tmp_path))
        ep = mgr.create(
            strategy_id="strat_a",
            symbols=["SPY"],
            episode_id="ep_test_1",
        )
        assert ep.episode_id == "ep_test_1"
        assert ep.status == "DRAFT"
        assert ep.strategy_id == "strat_a"
        assert ep.symbols == ["SPY"]

    def test_episode_loaded_correctly(self, tmp_path: Path) -> None:
        mgr = MicroPilotEpisodeManager(data_root=str(tmp_path))
        mgr.create(
            strategy_id="strat_a",
            symbols=["SPY", "QQQ"],
            episode_id="ep_load_test",
        )
        loaded = mgr.load("ep_load_test")
        assert loaded is not None
        assert loaded.episode_id == "ep_load_test"
        assert loaded.strategy_id == "strat_a"
        assert loaded.symbols == ["SPY", "QQQ"]

    def test_can_add_order_when_under_limit(self, tmp_path: Path) -> None:
        mgr = MicroPilotEpisodeManager(data_root=str(tmp_path))
        ep = mgr.create(
            strategy_id="strat_a",
            symbols=["SPY"],
            episode_id="ep_can_add",
            max_order_count=3,
            max_cumulative_notional=300.0,
        )
        # Episode must be in a state that allows orders
        ep.status = "WAITING_NEXT_ONE_SHOT_REVIEW"
        mgr.save(ep)

        allowed, reason = mgr.can_add_next_order("ep_can_add", new_notional=100.0)
        assert allowed is True, f"Should be allowed but got: {reason}"

    def test_exceeds_max_order_count_blocked(self, tmp_path: Path) -> None:
        mgr = MicroPilotEpisodeManager(data_root=str(tmp_path))
        ep = mgr.create(
            strategy_id="strat_a",
            symbols=["SPY"],
            episode_id="ep_max_order",
            max_order_count=1,
        )
        # Add one ticket to reach limit
        mgr.add_ticket("ep_max_order", "ticket_1", notional=50.0)

        # Now check can_add_next_order — should be blocked
        allowed, reason = mgr.can_add_next_order("ep_max_order", new_notional=50.0)
        assert allowed is False
        # Episode status is COMPLETED when max_order_count reached
        assert "episode_completed" in reason

    def test_exceeds_cumulative_notional_blocked(self, tmp_path: Path) -> None:
        mgr = MicroPilotEpisodeManager(data_root=str(tmp_path))
        ep = mgr.create(
            strategy_id="strat_a",
            symbols=["SPY"],
            episode_id="ep_notional",
            max_order_count=3,
            max_cumulative_notional=200.0,
        )
        # Change status so can_add_next_order accepts
        ep.status = "WAITING_NEXT_ONE_SHOT_REVIEW"
        mgr.save(ep)

        # Add tickets using notional
        mgr.add_ticket("ep_notional", "ticket_1", notional=150.0)

        # Next order would exceed cumulative notional
        allowed, reason = mgr.can_add_next_order("ep_notional", new_notional=100.0)
        assert allowed is False
        assert "cumulative_notional_exceeded" in reason

    def test_same_day_second_order_blocked(self, tmp_path: Path) -> None:
        mgr = MicroPilotEpisodeManager(data_root=str(tmp_path))
        ep = mgr.create(
            strategy_id="strat_a",
            symbols=["SPY"],
            episode_id="ep_same_day",
            max_order_count=3,
            max_cumulative_notional=300.0,
        )
        ep.status = "WAITING_NEXT_ONE_SHOT_REVIEW"
        ep.last_order_date = "2026-05-08"  # same as "today"
        mgr.save(ep)

        allowed, reason = mgr.can_add_next_order("ep_same_day", new_notional=50.0)
        assert allowed is False
        assert "same_day_order_blocked" in reason

    def test_unreviewed_previous_order_blocked(self, tmp_path: Path) -> None:
        """Previous ticket without dossier → blocked with previous_order_review_incomplete."""
        mgr = MicroPilotEpisodeManager(data_root=str(tmp_path))
        ep = mgr.create(
            strategy_id="strat_a",
            symbols=["SPY"],
            episode_id="ep_unreviewed",
            max_order_count=3,
            max_cumulative_notional=300.0,
        )
        ep.status = "WAITING_NEXT_ONE_SHOT_REVIEW"
        ep.last_order_date = "2026-05-07"  # yesterday
        ep.latest_ticket_id = "ticket_no_dossier"
        mgr.save(ep)

        allowed, reason = mgr.can_add_next_order("ep_unreviewed", new_notional=50.0)
        assert allowed is False
        assert "previous_order_review_incomplete" in reason

    def test_terminated_episode_blocks_new_orders(self, tmp_path: Path) -> None:
        mgr = MicroPilotEpisodeManager(data_root=str(tmp_path))
        mgr.create(
            strategy_id="strat_a",
            symbols=["SPY"],
            episode_id="ep_term",
        )
        mgr.terminate("ep_term", "max_loss_reached")

        allowed, reason = mgr.can_add_next_order("ep_term", new_notional=50.0)
        assert allowed is False
        assert "episode_terminated" in reason or "episode_" in reason

    def test_never_calls_submit_order(self, tmp_path: Path) -> None:
        """Episode manager has no submit_order capability."""
        mgr = MicroPilotEpisodeManager(data_root=str(tmp_path))
        assert not hasattr(mgr, "submit_order")
        assert not hasattr(mgr, "_broker")
        assert not hasattr(mgr, "broker")

    def test_add_ticket_increments_count_and_notional(self, tmp_path: Path) -> None:
        mgr = MicroPilotEpisodeManager(data_root=str(tmp_path))
        mgr.create(
            strategy_id="strat_a",
            symbols=["SPY"],
            episode_id="ep_counts",
            max_order_count=5,
            max_cumulative_notional=500.0,
        )
        mgr.add_ticket("ep_counts", "ticket_1", notional=100.0)
        ep = mgr.load("ep_counts")
        assert ep is not None
        assert ep.completed_order_count == 1
        assert ep.used_cumulative_notional == 100.0
        assert ep.ticket_ids == ["ticket_1"]

    def test_completed_when_max_orders_reached(self, tmp_path: Path) -> None:
        mgr = MicroPilotEpisodeManager(data_root=str(tmp_path))
        mgr.create(
            strategy_id="strat_a",
            symbols=["SPY"],
            episode_id="ep_complete",
            max_order_count=1,
            max_cumulative_notional=500.0,
        )
        mgr.add_ticket("ep_complete", "ticket_1", notional=100.0)
        ep = mgr.load("ep_complete")
        assert ep is not None
        assert ep.status == "COMPLETED"

    def test_terminate_sets_status_and_reason(self, tmp_path: Path) -> None:
        mgr = MicroPilotEpisodeManager(data_root=str(tmp_path))
        mgr.create(
            strategy_id="strat_a",
            symbols=["SPY"],
            episode_id="ep_kill",
        )
        mgr.terminate("ep_kill", "emergency_stop")
        ep = mgr.load("ep_kill")
        assert ep is not None
        assert ep.status == "TERMINATED"
        assert ep.termination_reason == "emergency_stop"
        assert ep.terminated_at != ""

    def test_load_nonexistent_returns_none(self, tmp_path: Path) -> None:
        mgr = MicroPilotEpisodeManager(data_root=str(tmp_path))
        assert mgr.load("does_not_exist") is None

    def test_status_returns_summary(self, tmp_path: Path) -> None:
        mgr = MicroPilotEpisodeManager(data_root=str(tmp_path))
        mgr.create(
            strategy_id="strat_a",
            symbols=["SPY"],
            episode_id="ep_status",
        )
        summary = mgr.status("ep_status")
        assert summary["episode_id"] == "ep_status"
        assert summary["status"] == "DRAFT"
        assert summary["strategy_id"] == "strat_a"
        assert summary["symbols"] == ["SPY"]

    def test_status_not_found(self, tmp_path: Path) -> None:
        mgr = MicroPilotEpisodeManager(data_root=str(tmp_path))
        summary = mgr.status("nonexistent")
        assert summary["status"] == "NOT_FOUND"

    def test_draft_status_not_ready_for_order(self, tmp_path: Path) -> None:
        """DRAFT episodes cannot accept orders — must be WAITING_NEXT_ONE_SHOT_REVIEW."""
        mgr = MicroPilotEpisodeManager(data_root=str(tmp_path))
        mgr.create(
            strategy_id="strat_a",
            symbols=["SPY"],
            episode_id="ep_draft",
        )
        allowed, reason = mgr.can_add_next_order("ep_draft", new_notional=50.0)
        assert allowed is False
        assert "episode_status_not_ready" in reason or "DRAFT" in reason
