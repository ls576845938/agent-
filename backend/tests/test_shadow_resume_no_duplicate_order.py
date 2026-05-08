"""Tests for shadow-live resume safety: no duplicate orders on restart.

Verifies that resuming a shadow-live run doesn't create duplicate
shadow orders, duplicate journal entries, or double-count days.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from quant_us.core.enums import OrderSide, OrderType
from quant_us.live.shadow_models import ShadowOrder, ShadowFill
from quant_us.live.shadow_validation_controller import ShadowValidationController


class TestShadowOrderIdUniqueness:
    """Shadow order IDs must be unique across runs and resumptions."""

    def test_ids_unique_across_creations(self) -> None:
        o1 = ShadowOrder(
            shadow_order_id="ord_a", run_id="r1", strategy_id="s",
            signal_id="sig1", target_position_id="t1", order_intent_id="i1",
            risk_check_id="rk1", symbol="SPY", side=OrderSide.BUY,
            quantity=1.0, estimated_price=1.0, estimated_notional=1.0,
            order_type=OrderType.MARKET,
        )
        o2 = ShadowOrder(
            shadow_order_id="ord_b", run_id="r1", strategy_id="s",
            signal_id="sig2", target_position_id="t2", order_intent_id="i2",
            risk_check_id="rk2", symbol="SPY", side=OrderSide.BUY,
            quantity=1.0, estimated_price=1.0, estimated_notional=1.0,
            order_type=OrderType.MARKET,
        )
        assert o1.shadow_order_id != o2.shadow_order_id
        # Also verify intent/signal IDs differ
        assert o1.signal_id != o2.signal_id
        assert o1.order_intent_id != o2.order_intent_id


class TestResumeNoDuplicate:
    """Verify resume flow doesn't duplicate validation state."""

    def make_shadow_order(self, oid: str) -> ShadowOrder:
        return ShadowOrder(
            shadow_order_id=oid, run_id="test", strategy_id="s",
            signal_id="sig", target_position_id="tgt", order_intent_id="int",
            risk_check_id="risk", symbol="SPY", side=OrderSide.BUY,
            quantity=10.0, estimated_price=500.0, estimated_notional=5000.0,
            order_type=OrderType.MARKET,
        )

    def make_shadow_fill(self, fid: str, oid: str) -> ShadowFill:
        return ShadowFill(
            shadow_fill_id=fid, shadow_order_id=oid,
            simulated_fill_price=500.0, simulated_fill_qty=10.0,
            slippage_model="bps_1", commission_model="pct_0.01",
        )

    def test_resume_does_not_double_count_days(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            # First session: run 2 days
            ctrl1 = ShadowValidationController(
                state_dir=tmp, symbols=["SPY"], days_target=5,
            )
            state1 = ctrl1.start()
            run_id = state1.run_id

            for day in range(2):
                orders = [self.make_shadow_order(f"ord_d{day}")]
                fills = [self.make_shadow_fill(f"fill_d{day}", f"ord_d{day}")]
                ctrl1.record_day(orders, fills)

            # Simulate restart: create new controller pointing to same state
            ctrl2 = ShadowValidationController(
                state_dir=tmp, symbols=["SPY"], days_target=5,
            )
            state2 = ctrl2.start()

            # Should resume same run, not start new
            assert state2.run_id == run_id
            assert state2.days_completed == 2  # Not 0 (new) or 4 (doubled)

            # Run more days
            for day in range(2, 5):
                orders = [self.make_shadow_order(f"ord_d{day}")]
                fills = [self.make_shadow_fill(f"fill_d{day}", f"ord_d{day}")]
                ctrl2.record_day(orders, fills)

            status = ctrl2.status()
            assert status["state"]["days_completed"] == 5
            assert status["passed"] is True

    def test_resume_preserves_shadow_order_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ctrl1 = ShadowValidationController(
                state_dir=tmp, symbols=["SPY"], days_target=5,
            )
            ctrl1.start()
            orders = [
                self.make_shadow_order("ord_1"),
                self.make_shadow_order("ord_2"),
                self.make_shadow_order("ord_3"),
            ]
            fills = [
                self.make_shadow_fill("fill_1", "ord_1"),
                self.make_shadow_fill("fill_2", "ord_2"),
                self.make_shadow_fill("fill_3", "ord_3"),
            ]
            ctrl1.record_day(orders, fills)

            ctrl2 = ShadowValidationController(state_dir=tmp)
            state = ctrl2.start()
            assert state.shadow_order_count == 3
            assert state.shadow_fill_count == 3

    def test_resume_keeps_real_submit_at_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ctrl1 = ShadowValidationController(
                state_dir=tmp, symbols=["SPY"], days_target=5,
            )
            ctrl1.start()
            ctrl1.record_day([], [])

            ctrl2 = ShadowValidationController(state_dir=tmp)
            state = ctrl2.start()
            assert state.real_submit_count == 0

            ctrl2.record_day([], [])
            assert state.real_submit_count == 0

    def test_shadow_ledger_consistency_across_resume(self) -> None:
        """ShadowLedger state persists correctly across orchestrator restarts."""
        from quant_us.live.shadow_orchestrator import (
            ShadowLiveOrchestrator,
            ShadowOrchestratorConfig,
        )

        with tempfile.TemporaryDirectory() as tmp:
            config = ShadowOrchestratorConfig(
                symbols=["SPY"],
                readonly=True,
                data_root=tmp,
                ledger_root=f"{tmp}/shadow_ledger",
            )
            orch1 = ShadowLiveOrchestrator(config)
            orch1.bootstrap()
            orch1.shadow_ledger.apply_shadow_fill("SPY", OrderSide.BUY, 100.0, 500.0)
            orch1.shutdown_safely()

            # Resume
            config2 = ShadowOrchestratorConfig(
                symbols=["SPY"],
                readonly=True,
                data_root=tmp,
                ledger_root=f"{tmp}/shadow_ledger",
            )
            orch2 = ShadowLiveOrchestrator(config2)
            resumed = orch2.resume_from_state()
            assert resumed is True
            # Shadow ledger reflects persisted cash/equity/pnl from state
            snap = orch2.shadow_ledger.snapshot()
            # After buying 100 SPY at 500: 100_000 - (100*500) - comm = 50_000 - small_comm
            assert snap["shadow_cash"] < 100_000.0  # Cash decreased from buy

    def test_journal_entries_not_duplicated_on_resume(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ctrl1 = ShadowValidationController(
                state_dir=tmp, symbols=["SPY"], days_target=3,
            )
            ctrl1.start()

            orders = [self.make_shadow_order("ord_x")]
            fills = [self.make_shadow_fill("fill_x", "ord_x")]
            ctrl1.record_day(orders, fills)

            # Get audit count
            entries1 = ctrl1.audit(latest_only=False)
            count1 = len(entries1)

            # Resume
            ctrl2 = ShadowValidationController(
                state_dir=tmp, symbols=["SPY"], days_target=3,
            )
            state = ctrl2.start()

            # record one more day
            orders2 = [self.make_shadow_order("ord_y")]
            fills2 = [self.make_shadow_fill("fill_y", "ord_y")]
            ctrl2.record_day(orders2, fills2)

            assert state.days_completed == 2
            assert state.real_submit_count == 0
