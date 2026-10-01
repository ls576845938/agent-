"""Tests for G6 LivePositionExitPlanBuilder.

All tests use tmp_path for data isolation. No real broker calls.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from quant_us.live.g6_exit_plan import (
    LivePositionExitPlan,
    LivePositionExitPlanBuilder,
)


class TestLivePositionExitPlan:
    """Tests for LivePositionExitPlan invariants."""

    def test_default_reduce_only_is_true(self) -> None:
        plan = LivePositionExitPlan(
            exit_plan_id="exit_1",
            symbol="SPY",
            current_qty=100.0,
        )
        assert plan.reduce_only is True

    def test_default_status_is_draft(self) -> None:
        plan = LivePositionExitPlan(
            exit_plan_id="exit_1",
            symbol="SPY",
            current_qty=100.0,
        )
        assert plan.status == "DRAFT"

    def test_default_manual_approval_required_is_true(self) -> None:
        plan = LivePositionExitPlan(
            exit_plan_id="exit_1",
            symbol="SPY",
            current_qty=100.0,
        )
        assert plan.manual_approval_required is True

    def test_to_dict_round_trip(self) -> None:
        plan = LivePositionExitPlan(
            exit_plan_id="exit_1",
            episode_id="ep_1",
            symbol="SPY",
            current_qty=100.0,
            suggested_qty=100.0,
            suggested_side="sell",
        )
        data = plan.to_dict()
        assert data["exit_plan_id"] == "exit_1"
        assert data["episode_id"] == "ep_1"
        assert data["symbol"] == "SPY"
        assert data["reduce_only"] is True
        assert data["suggested_side"] == "sell"

    def test_is_reduce_only_true_when_suggested_lte_abs_qty(self) -> None:
        plan = LivePositionExitPlan(
            exit_plan_id="exit_1",
            current_qty=100.0,
            suggested_qty=80.0,
            reduce_only=True,
        )
        assert plan.is_reduce_only is True

    def test_is_reduce_only_false_when_suggested_exceeds_abs_qty(self) -> None:
        plan = LivePositionExitPlan(
            exit_plan_id="exit_1",
            current_qty=100.0,
            suggested_qty=150.0,
            reduce_only=True,
        )
        assert plan.is_reduce_only is False


class TestLivePositionExitPlanBuilder:
    """Tests for exit plan builder logic and safety invariants."""

    def test_exit_plan_created_for_long_position(self, tmp_path: Path) -> None:
        builder = LivePositionExitPlanBuilder(data_root=str(tmp_path))
        plan = builder.build(
            episode_id="ep_1",
            ticket_id="ticket_1",
            symbol="SPY",
            current_qty=100.0,
            entry_price=500.0,
            current_market_price=505.0,
        )
        assert plan.exit_plan_id.startswith("exit_")
        assert plan.symbol == "SPY"
        assert plan.current_qty == 100.0
        assert plan.current_market_price == 505.0

    def test_exit_plan_created_for_short_position(self, tmp_path: Path) -> None:
        builder = LivePositionExitPlanBuilder(data_root=str(tmp_path))
        plan = builder.build(
            episode_id="ep_1",
            ticket_id="ticket_2",
            symbol="QQQ",
            current_qty=-50.0,
            entry_price=400.0,
            current_market_price=395.0,
        )
        assert plan.symbol == "QQQ"
        assert plan.current_qty == -50.0
        assert plan.suggested_side == "buy"  # short -> buy to cover

    def test_reduce_only_always_true(self, tmp_path: Path) -> None:
        """All generated exit plans have reduce_only=True (no option to set False)."""
        builder = LivePositionExitPlanBuilder(data_root=str(tmp_path))
        plan = builder.build(
            episode_id="ep_1",
            ticket_id="ticket_1",
            symbol="SPY",
            current_qty=100.0,
            entry_price=500.0,
        )
        assert plan.reduce_only is True

    def test_suggested_qty_equals_abs_current_qty(self, tmp_path: Path) -> None:
        """Suggested qty always equals abs(current_qty) to zero out position."""
        builder = LivePositionExitPlanBuilder(data_root=str(tmp_path))
        plan = builder.build(
            episode_id="ep_1",
            ticket_id="ticket_1",
            symbol="SPY",
            current_qty=100.0,
            entry_price=500.0,
        )
        assert plan.suggested_qty == 100.0
        assert plan.suggested_qty == abs(plan.current_qty)

    def test_long_position_exit_is_sell(self, tmp_path: Path) -> None:
        """Long position (qty > 0) → suggested_side = 'sell'."""
        builder = LivePositionExitPlanBuilder(data_root=str(tmp_path))
        plan = builder.build(
            episode_id="ep_1", ticket_id="t_1",
            symbol="SPY", current_qty=100.0, entry_price=500.0,
        )
        assert plan.suggested_side == "sell"

    def test_short_position_exit_is_buy(self, tmp_path: Path) -> None:
        """Short position (qty < 0) → suggested_side = 'buy'."""
        builder = LivePositionExitPlanBuilder(data_root=str(tmp_path))
        plan = builder.build(
            episode_id="ep_1", ticket_id="t_2",
            symbol="QQQ", current_qty=-50.0, entry_price=400.0,
        )
        assert plan.suggested_side == "buy"

    def test_suggested_qty_never_exceeds_current_qty(self, tmp_path: Path) -> None:
        """Suggested qty can NEVER exceed abs(current_qty)."""
        builder = LivePositionExitPlanBuilder(data_root=str(tmp_path))
        plan = builder.build(
            episode_id="ep_1", ticket_id="t_1",
            symbol="SPY", current_qty=100.0, entry_price=500.0,
        )
        assert plan.suggested_qty <= abs(plan.current_qty)

    def test_save_and_load(self, tmp_path: Path) -> None:
        builder = LivePositionExitPlanBuilder(data_root=str(tmp_path))
        plan = builder.build(
            episode_id="ep_1", ticket_id="t_1",
            symbol="SPY", current_qty=100.0, entry_price=500.0,
        )
        path = builder.save(plan)
        assert Path(path).exists()

        loaded = builder.load(plan.exit_plan_id)
        assert loaded is not None
        assert loaded.exit_plan_id == plan.exit_plan_id
        assert loaded.symbol == "SPY"
        assert loaded.current_qty == 100.0
        assert loaded.suggested_side == "sell"

    def test_approve_requires_ready_for_review(self, tmp_path: Path) -> None:
        builder = LivePositionExitPlanBuilder(data_root=str(tmp_path))
        plan = builder.build(
            episode_id="ep_1", ticket_id="t_1",
            symbol="SPY", current_qty=100.0, entry_price=500.0,
        )
        with pytest.raises(ValueError, match="Must be READY_FOR_REVIEW"):
            builder.approve(plan)

    def test_mark_ready_then_approve(self, tmp_path: Path) -> None:
        builder = LivePositionExitPlanBuilder(data_root=str(tmp_path))
        plan = builder.build(
            episode_id="ep_1", ticket_id="t_1",
            symbol="SPY", current_qty=100.0, entry_price=500.0,
        )
        builder.mark_ready(plan)
        assert plan.status == "READY_FOR_REVIEW"

        builder.approve(plan, approved_by="reviewer_1")
        assert plan.status == "APPROVED"

    def test_invalid_exit_reason_raises(self, tmp_path: Path) -> None:
        builder = LivePositionExitPlanBuilder(data_root=str(tmp_path))
        with pytest.raises(ValueError, match="Invalid exit_reason"):
            builder.build(
                episode_id="ep_1", ticket_id="t_1",
                symbol="SPY", current_qty=100.0, entry_price=500.0,
                exit_reason="invalid_reason",
            )

    def test_cancel_plan(self, tmp_path: Path) -> None:
        builder = LivePositionExitPlanBuilder(data_root=str(tmp_path))
        plan = builder.build(
            episode_id="ep_1", ticket_id="t_1",
            symbol="SPY", current_qty=100.0, entry_price=500.0,
        )
        builder.cancel(plan, reason="strategy_changed")
        assert plan.status == "CANCELED"

    def test_list_plans_by_episode(self, tmp_path: Path) -> None:
        builder = LivePositionExitPlanBuilder(data_root=str(tmp_path))
        # Build plans with explicit time to avoid same-second IDs
        p1 = builder.build(episode_id="ep_1", ticket_id="t_1", symbol="SPY",
                           current_qty=100.0, entry_price=500.0)
        # Manually set unique IDs to avoid time collisions
        p1.exit_plan_id = "exit_plan_001"
        builder.save(p1)

        p2 = builder.build(episode_id="ep_1", ticket_id="t_2", symbol="QQQ",
                           current_qty=-50.0, entry_price=400.0)
        p2.exit_plan_id = "exit_plan_002"
        builder.save(p2)

        plans = builder.list_plans(episode_id="ep_1")
        assert len(plans) == 2
        plan_ids = [p.exit_plan_id for p in plans]
        assert "exit_plan_001" in plan_ids
        assert "exit_plan_002" in plan_ids

    def test_unrealized_pnl_calculation_long(self, tmp_path: Path) -> None:
        """Long position: (current - entry) * qty."""
        builder = LivePositionExitPlanBuilder(data_root=str(tmp_path))
        plan = builder.build(
            episode_id="ep_1", ticket_id="t_1",
            symbol="SPY", current_qty=100.0, entry_price=500.0,
            current_market_price=510.0,
        )
        assert plan.unrealized_pnl == 1000.0  # (510 - 500) * 100

    def test_unrealized_pnl_calculation_short(self, tmp_path: Path) -> None:
        """Short position: -(current - entry) * abs(qty)."""
        builder = LivePositionExitPlanBuilder(data_root=str(tmp_path))
        plan = builder.build(
            episode_id="ep_1", ticket_id="t_2",
            symbol="QQQ", current_qty=-50.0, entry_price=400.0,
            current_market_price=390.0,
        )
        assert plan.unrealized_pnl == 500.0  # -(390 - 400) * 50
