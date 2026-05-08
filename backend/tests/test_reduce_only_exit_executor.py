"""Tests for G6 ReduceOnlyExitExecutor.

Uses FakeLiveBroker instead of real AlpacaBroker. All tests use tmp_path
for data isolation. No real broker calls.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from quant_us.live.g6_exit_plan import LivePositionExitPlanBuilder
from quant_us.live.g6_reduce_only_executor import (
    ReduceOnlyExitExecutor,
    ReduceOnlyExitResult,
)


# ---------------------------------------------------------------------------
# FakeLiveBroker for testing
# ---------------------------------------------------------------------------


class FakeLiveBroker:
    """Fake broker for testing — records orders, never hits real API."""

    def __init__(self) -> None:
        self.submitted_orders: list[dict] = []
        self.submit_count: int = 0

    def submit_reduce_only(
        self,
        symbol: str,
        side: str,
        qty: float,
        order_type: str = "limit",
        limit_price: float = 0.0,
    ) -> dict:
        self.submitted_orders.append({
            "symbol": symbol,
            "side": side,
            "qty": qty,
            "order_type": order_type,
            "limit_price": limit_price,
        })
        self.submit_count += 1
        return {
            "broker_order_id": f"fake_broker_{self.submit_count}",
            "symbol": symbol,
            "side": side,
            "qty": qty,
            "status": "submitted",
        }

    def submit_order(
        self,
        symbol: str,
        side: str,
        qty: float,
    ) -> dict:
        return self.submit_reduce_only(symbol, side, qty)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_approved_plan(
    builder: LivePositionExitPlanBuilder,
    episode_id: str = "ep_1",
    ticket_id: str = "ticket_1",
    symbol: str = "SPY",
    current_qty: float = 100.0,
) -> str:
    """Create an exit plan, mark ready, approve, return exit_plan_id."""
    plan = builder.build(
        episode_id=episode_id,
        ticket_id=ticket_id,
        symbol=symbol,
        current_qty=current_qty,
        entry_price=500.0,
    )
    builder.mark_ready(plan)
    builder.approve(plan, approved_by="test_reviewer")
    return plan.exit_plan_id


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestReduceOnlyExitExecutor:
    """Tests for ReduceOnlyExitExecutor safety invariants."""

    def test_default_dry_run_no_submit(self, tmp_path: Path) -> None:
        """Default dry_run=True → submitted=False, no broker call."""
        builder = LivePositionExitPlanBuilder(data_root=str(tmp_path))
        plan_id = _create_approved_plan(builder)

        executor = ReduceOnlyExitExecutor(data_root=str(tmp_path), dry_run=True)
        result = executor.execute(
            exit_plan_id=plan_id,
            manual_approval=True,
        )
        assert result.dry_run is True
        assert result.submitted is False
        assert result.reduce_only_verified is True
        assert result.position_check_passed is True
        assert len(result.errors) == 0

    def test_reduce_only_verified(self, tmp_path: Path) -> None:
        """Valid exit plan → reduce_only_verified=True."""
        builder = LivePositionExitPlanBuilder(data_root=str(tmp_path))
        plan_id = _create_approved_plan(builder)

        executor = ReduceOnlyExitExecutor(data_root=str(tmp_path), dry_run=True)
        result = executor.execute(
            exit_plan_id=plan_id,
            manual_approval=True,
        )
        assert result.reduce_only_verified is True

    def test_increase_position_rejected(self, tmp_path: Path) -> None:
        """Exit plan with suggested_qty > abs(current_qty) → rejected."""
        builder = LivePositionExitPlanBuilder(data_root=str(tmp_path))
        plan = builder.build(
            episode_id="ep_1", ticket_id="t_1",
            symbol="SPY", current_qty=100.0, entry_price=500.0,
        )
        # Tamper with suggested_qty to simulate increase
        plan.suggested_qty = 200.0  # > abs(100.0) = increase position
        builder.mark_ready(plan)
        builder.approve(plan, approved_by="test")

        executor = ReduceOnlyExitExecutor(data_root=str(tmp_path), dry_run=True)
        result = executor.execute(
            exit_plan_id=plan.exit_plan_id,
            manual_approval=True,
        )
        assert result.reduce_only_verified is False  # verification fails
        assert any("increase position" in e for e in result.errors)

    def test_reverse_position_rejected(self, tmp_path: Path) -> None:
        """Long position but suggested_side='buy' → rejected."""
        builder = LivePositionExitPlanBuilder(data_root=str(tmp_path))
        plan = builder.build(
            episode_id="ep_1", ticket_id="t_1",
            symbol="SPY", current_qty=100.0, entry_price=500.0,
        )
        # Tamper with suggested_side to simulate reverse
        plan.suggested_side = "buy"  # LONG should exit with sell
        builder.mark_ready(plan)
        builder.approve(plan, approved_by="test")

        executor = ReduceOnlyExitExecutor(data_root=str(tmp_path), dry_run=True)
        result = executor.execute(
            exit_plan_id=plan.exit_plan_id,
            manual_approval=True,
        )
        assert result.reduce_only_verified is False
        assert any("expected 'sell'" in e for e in result.errors)

    def test_no_manual_approval_no_submit_even_fake(self, tmp_path: Path) -> None:
        """Without manual_approval=True → blocked even with fake broker."""
        builder = LivePositionExitPlanBuilder(data_root=str(tmp_path))
        plan_id = _create_approved_plan(builder)

        fake = FakeLiveBroker()
        executor = ReduceOnlyExitExecutor(data_root=str(tmp_path), dry_run=False)
        result = executor.execute(
            exit_plan_id=plan_id,
            manual_approval=False,
            env_enabled=True,
            fake_broker=fake,
        )
        assert result.submitted is False
        assert fake.submit_count == 0
        assert any("Manual approval flag" in e for e in result.errors)

    def test_fake_broker_submits_only_with_approval(self, tmp_path: Path) -> None:
        """Full path: dry_run=False + manual_approval=True + env_enabled + fake → submit."""
        builder = LivePositionExitPlanBuilder(data_root=str(tmp_path))
        plan_id = _create_approved_plan(builder)

        fake = FakeLiveBroker()
        executor = ReduceOnlyExitExecutor(data_root=str(tmp_path), dry_run=False)
        result = executor.execute(
            exit_plan_id=plan_id,
            manual_approval=True,
            env_enabled=True,
            fake_broker=fake,
        )
        assert result.submitted is True
        assert fake.submit_count == 1
        assert fake.submitted_orders[0]["symbol"] == "SPY"
        assert fake.submitted_orders[0]["side"] == "sell"

    def test_audit_written_on_submit(self, tmp_path: Path) -> None:
        """Audit trail is written when executor is called."""
        builder = LivePositionExitPlanBuilder(data_root=str(tmp_path))
        plan_id = _create_approved_plan(builder)

        executor = ReduceOnlyExitExecutor(data_root=str(tmp_path), dry_run=True)
        executor.execute(
            exit_plan_id=plan_id,
            manual_approval=True,
        )

        # Check audit file exists
        audit_dir = tmp_path / "live_pilot" / "exit_plans"
        audit_path = audit_dir / "reduce_only_executor_audit.jsonl"
        assert audit_path.exists()

        lines = audit_path.read_text().strip().split("\n")
        assert len(lines) >= 1
        import json
        entry = json.loads(lines[0])
        assert entry["action"] == "DRY_RUN"
        assert entry["exit_plan_id"] == plan_id

    def test_never_reaches_real_broker(self, tmp_path: Path) -> None:
        """Executor has no AlpacaBroker import or real broker attribute."""
        executor = ReduceOnlyExitExecutor(data_root=str(tmp_path), dry_run=True)
        assert not hasattr(executor, "_broker")
        assert not hasattr(executor, "alpaca_broker")
        # The only broker parameter is 'fake_broker' in execute()
        import inspect
        sig = inspect.signature(executor.execute)
        assert "fake_broker" in sig.parameters

    def test_nonexistent_plan_returns_error(self, tmp_path: Path) -> None:
        """Executor returns error for nonexistent exit plan."""
        executor = ReduceOnlyExitExecutor(data_root=str(tmp_path), dry_run=True)
        result = executor.execute(
            exit_plan_id="nonexistent_plan",
            manual_approval=True,
        )
        assert result.submitted is False
        assert any("not found" in e for e in result.errors)

    def test_not_approved_plan_blocked(self, tmp_path: Path) -> None:
        """Exit plan that is not APPROVED → blocked."""
        builder = LivePositionExitPlanBuilder(data_root=str(tmp_path))
        plan = builder.build(
            episode_id="ep_1", ticket_id="t_1",
            symbol="SPY", current_qty=100.0, entry_price=500.0,
        )
        # Only mark ready, don't approve
        builder.mark_ready(plan)

        executor = ReduceOnlyExitExecutor(data_root=str(tmp_path), dry_run=True)
        result = executor.execute(
            exit_plan_id=plan.exit_plan_id,
            manual_approval=True,
        )
        assert result.submitted is False
        assert any("APPROVED" in e for e in result.errors)
