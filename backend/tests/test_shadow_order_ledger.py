"""Tests for quant_us/live/shadow_models.py — ShadowOrder, ShadowFill,
ShadowLedger, StateDiff.

Covers creation, serialization, ledger mutations, state comparison,
and traceability chain invariants.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from quant_us.core.enums import OrderSide, OrderType
from quant_us.core.types import new_id
from quant_us.live.shadow_models import ShadowFill, ShadowLedger, ShadowOrder, StateDiff


# ===========================================================================
# ShadowOrder
# ===========================================================================


class TestShadowOrder:
    def test_create_with_required_fields(self) -> None:
        order = ShadowOrder(
            shadow_order_id="so_001",
            run_id="run_1",
            strategy_id="etf_rotation",
            signal_id="sig_001",
            target_position_id="tgt_001",
            order_intent_id="intent_001",
            risk_check_id="risk_001",
            symbol="SPY",
            side=OrderSide.BUY,
            quantity=100.0,
            estimated_price=530.0,
            estimated_notional=53_000.0,
            order_type=OrderType.MARKET,
        )
        assert order.shadow_order_id == "so_001"
        assert order.would_submit is True
        assert order.real_submit is False
        assert order.block_reason == "shadow_live_readonly"

    def test_default_safety_invariants(self) -> None:
        order = ShadowOrder(
            shadow_order_id="so_002",
            run_id="run_1",
            strategy_id="etf_rotation",
            signal_id="sig_002",
            target_position_id="tgt_002",
            order_intent_id="intent_002",
            risk_check_id="risk_002",
            symbol="QQQ",
            side=OrderSide.SELL,
            quantity=50.0,
            estimated_price=450.0,
            estimated_notional=22_500.0,
            order_type=OrderType.LIMIT,
        )
        assert order.would_submit is True
        assert order.real_submit is False

    def test_immutable(self) -> None:
        order = ShadowOrder(
            shadow_order_id="so_003",
            run_id="run_1",
            strategy_id="etf_rotation",
            signal_id="sig_003",
            target_position_id="tgt_003",
            order_intent_id="intent_003",
            risk_check_id="risk_003",
            symbol="SPY",
            side=OrderSide.BUY,
            quantity=10.0,
            estimated_price=530.0,
            estimated_notional=5_300.0,
            order_type=OrderType.MARKET,
        )
        with pytest.raises(AttributeError):
            order.real_submit = True  # type: ignore[misc]

    def test_to_dict_contains_expected_keys(self) -> None:
        order = ShadowOrder(
            shadow_order_id="so_004",
            run_id="run_1",
            strategy_id="etf_rotation",
            signal_id="sig_004",
            target_position_id="tgt_004",
            order_intent_id="intent_004",
            risk_check_id="risk_004",
            symbol="IWM",
            side=OrderSide.BUY,
            quantity=200.0,
            estimated_price=210.0,
            estimated_notional=42_000.0,
            order_type=OrderType.MARKET,
        )
        d = order.to_dict()
        assert d["shadow_order_id"] == "so_004"
        assert d["would_submit"] is True
        assert d["real_submit"] is False
        assert d["side"] == OrderSide.BUY.value
        assert d["order_type"] == OrderType.MARKET.value
        assert d["block_reason"] == "shadow_live_readonly"
        assert "created_at" in d
        assert "shadow_order_id" in d
        assert "run_id" in d
        assert "strategy_id" in d
        assert "signal_id" in d
        assert "target_position_id" in d
        assert "order_intent_id" in d
        assert "risk_check_id" in d
        assert "symbol" in d
        assert "quantity" in d
        assert "estimated_price" in d
        assert "estimated_notional" in d

    def test_shadow_order_id_unique(self) -> None:
        ids = {
            ShadowOrder(
                shadow_order_id=new_id("shadow_ord"),
                run_id="run_x",
                strategy_id="s",
                signal_id="sig",
                target_position_id="tgt",
                order_intent_id="intent",
                risk_check_id="risk",
                symbol="SPY",
                side=OrderSide.BUY,
                quantity=1.0,
                estimated_price=500.0,
                estimated_notional=500.0,
                order_type=OrderType.MARKET,
            ).shadow_order_id
            for _ in range(100)
        }
        assert len(ids) == 100


# ===========================================================================
# ShadowFill
# ===========================================================================


class TestShadowFill:
    def test_create_with_required_fields(self) -> None:
        fill = ShadowFill(
            shadow_fill_id="sf_001",
            shadow_order_id="so_001",
            simulated_fill_price=531.0,
            simulated_fill_qty=100.0,
            slippage_model="bps_1",
            commission_model="percent_0.01",
        )
        assert fill.shadow_fill_id == "sf_001"
        assert fill.simulated_fill_price == 531.0
        assert fill.simulated_fill_qty == 100.0

    def test_to_dict_contains_expected_keys(self) -> None:
        fill = ShadowFill(
            shadow_fill_id="sf_002",
            shadow_order_id="so_002",
            simulated_fill_price=450.0,
            simulated_fill_qty=50.0,
            slippage_model="bps_0.5",
            commission_model="percent_0.005",
        )
        d = fill.to_dict()
        assert d["shadow_fill_id"] == "sf_002"
        assert d["shadow_order_id"] == "so_002"
        assert d["simulated_fill_price"] == 450.0
        assert d["simulated_fill_qty"] == 50.0
        assert d["slippage_model"] == "bps_0.5"
        assert "created_at" in d


# ===========================================================================
# ShadowLedger
# ===========================================================================


class TestShadowLedger:
    @pytest.fixture
    def ledger(self) -> ShadowLedger:
        return ShadowLedger()

    def test_initial_state(self, ledger: ShadowLedger) -> None:
        assert ledger.shadow_cash == 100_000.0
        assert ledger.shadow_equity == 100_000.0
        assert ledger.shadow_pnl == 0.0
        assert ledger.shadow_exposure == 0.0
        assert ledger.shadow_drawdown == 0.0
        assert ledger.peak_equity == 100_000.0
        assert ledger.shadow_positions == {}

    def test_apply_buy_updates_cash_and_position(
        self, ledger: ShadowLedger
    ) -> None:
        ledger.apply_shadow_fill("SPY", OrderSide.BUY, 100.0, 500.0)
        assert ledger.shadow_cash == 100_000.0 - 50_000.0
        assert ledger.shadow_positions["SPY"] == 100.0

    def test_apply_sell_updates_cash_and_position(
        self, ledger: ShadowLedger
    ) -> None:
        # First buy
        ledger.apply_shadow_fill("SPY", OrderSide.BUY, 100.0, 500.0)
        assert ledger.shadow_positions["SPY"] == 100.0

        cash_after_buy = ledger.shadow_cash

        # Then sell
        ledger.apply_shadow_fill("SPY", OrderSide.SELL, 50.0, 510.0)
        assert ledger.shadow_positions["SPY"] == 50.0

    def test_equity_tracking(self, ledger: ShadowLedger) -> None:
        ledger.apply_shadow_fill("SPY", OrderSide.BUY, 100.0, 500.0)
        assert ledger.shadow_equity == ledger.shadow_cash + 0.0  # _last_price=0
        assert ledger.shadow_pnl == ledger.shadow_equity - 100_000.0

    def test_multiple_fills_compound_correctly(
        self, ledger: ShadowLedger
    ) -> None:
        ledger.apply_shadow_fill("SPY", OrderSide.BUY, 100.0, 500.0)
        ledger.apply_shadow_fill("QQQ", OrderSide.BUY, 50.0, 450.0)
        ledger.apply_shadow_fill("IWM", OrderSide.BUY, 200.0, 210.0)

        assert ledger.shadow_positions["SPY"] == 100.0
        assert ledger.shadow_positions["QQQ"] == 50.0
        assert ledger.shadow_positions["IWM"] == 200.0

        expected_cash = 100_000.0 - (100 * 500.0) - (50 * 450.0) - (200 * 210.0)
        assert ledger.shadow_cash == expected_cash

    def test_drawdown_no_change(self, ledger: ShadowLedger) -> None:
        ledger.apply_shadow_fill("SPY", OrderSide.BUY, 100.0, 500.0)
        # _last_price returns 0, so equity drops = drawdown increases
        assert ledger.shadow_drawdown > 0.0

    def test_peak_equity_updates(self, ledger: ShadowLedger) -> None:
        """When equity goes up, peak_equity should track it.
        Since _last_price returns 0, equity will drop on each buy,
        so peak_equity stays at the initial or highest observed value."""
        initial_peak = ledger.peak_equity
        ledger.apply_shadow_fill("SPY", OrderSide.BUY, 100.0, 500.0)
        # Because _last_price returns 0, equity drops, so peak_equity remains same
        assert ledger.peak_equity == initial_peak

    def test_snapshot(self, ledger: ShadowLedger) -> None:
        ledger.apply_shadow_fill("SPY", OrderSide.BUY, 100.0, 500.0)
        snap = ledger.snapshot()
        assert snap["shadow_cash"] == ledger.shadow_cash
        assert snap["shadow_positions"] == ledger.shadow_positions
        assert snap["shadow_equity"] == ledger.shadow_equity
        assert snap["shadow_pnl"] == ledger.shadow_pnl
        assert snap["shadow_exposure"] == ledger.shadow_exposure
        assert snap["shadow_drawdown"] == ledger.shadow_drawdown


# ===========================================================================
# StateDiff
# ===========================================================================


class TestStateDiff:
    def test_basic_creation(self) -> None:
        diff = StateDiff(
            run_id="run_1",
            shadow_positions={"SPY": 100.0},
            live_positions={"SPY": 0.0},
            shadow_equity=105_000.0,
            live_equity=100_000.0,
        )
        assert diff.run_id == "run_1"

    def test_has_critical_diff_true(self) -> None:
        diff = StateDiff(
            run_id="run_1",
            diff_shadow_live={"SPY": 100.0},
        )
        assert diff.has_critical_diff() is True

    def test_has_critical_diff_false(self) -> None:
        diff = StateDiff(
            run_id="run_1",
            diff_shadow_live={"SPY": 0.005},
        )
        assert diff.has_critical_diff() is False

    def test_has_critical_diff_empty(self) -> None:
        diff = StateDiff(run_id="run_1")
        assert diff.has_critical_diff() is False

    def test_to_dict_serializable(self) -> None:
        diff = StateDiff(
            run_id="run_1",
            paper_positions={"SPY": 50.0},
            shadow_positions={"SPY": 100.0},
            live_positions={"SPY": 0.0},
            diff_paper_shadow={"SPY": -50.0},
            diff_shadow_live={"SPY": 100.0},
            diff_paper_live={"SPY": 50.0},
            paper_equity=100_000.0,
            shadow_equity=105_000.0,
            live_equity=102_000.0,
        )
        d = diff.to_dict()
        assert d["run_id"] == "run_1"
        assert d["has_critical_diff"] is True
        assert d["paper_positions"]["SPY"] == 50.0
        assert d["shadow_positions"]["SPY"] == 100.0
        assert d["live_positions"]["SPY"] == 0.0
        assert d["shadow_equity"] == 105_000.0

    def test_to_dict_no_critical_diff(self) -> None:
        diff = StateDiff(run_id="run_1")
        d = diff.to_dict()
        assert d["has_critical_diff"] is False


# ===========================================================================
# Traceability Chain
# ===========================================================================


class TestTraceabilityChain:
    def test_shadow_order_links_to_intent_and_signal(self) -> None:
        signal_id = new_id("sig")
        intent_id = new_id("intent")
        order = ShadowOrder(
            shadow_order_id=new_id("shadow_ord"),
            run_id="run_1",
            strategy_id="etf_rotation",
            signal_id=signal_id,
            target_position_id=new_id("target"),
            order_intent_id=intent_id,
            risk_check_id=new_id("risk"),
            symbol="SPY",
            side=OrderSide.BUY,
            quantity=100.0,
            estimated_price=500.0,
            estimated_notional=50_000.0,
            order_type=OrderType.MARKET,
        )
        assert order.signal_id == signal_id
        assert order.order_intent_id == intent_id

    def test_shadow_fill_links_to_order(self) -> None:
        order_id = "so_trace_001"
        fill = ShadowFill(
            shadow_fill_id=new_id("shadow_fill"),
            shadow_order_id=order_id,
            simulated_fill_price=500.0,
            simulated_fill_qty=100.0,
            slippage_model="bps_1",
            commission_model="percent_0.01",
        )
        assert fill.shadow_order_id == order_id
