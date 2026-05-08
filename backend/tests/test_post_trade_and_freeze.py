"""Tests for PostTradeReconciliation, LivePilotFreezeState, and G5 Dossier."""

from __future__ import annotations

import tempfile

import pytest

from quant_us.live.g5_post_trade import (
    PostTradeReconciler,
    PostTradeReconciliationResult,
    LivePilotFreezeState,
    generate_execution_quality,
    G5PostTradeDossier,
)


class TestPostTradeReconciler:
    def test_filled_clean(self) -> None:
        r = PostTradeReconciler()
        result = r.reconcile("T1", broker_order_status="filled", fill_qty=1.0, submitted_qty=1.0)
        assert result.status == "CLEAN_FILLED"
        assert not result.requires_manual_review

    def test_partial_fill_manual_review(self) -> None:
        r = PostTradeReconciler()
        result = r.reconcile("T1", broker_order_status="filled", fill_qty=0.5, submitted_qty=1.0)
        assert result.status == "PARTIAL_FILL"
        assert result.requires_manual_review

    def test_rejected_manual_review(self) -> None:
        r = PostTradeReconciler()
        result = r.reconcile("T1", broker_order_status="rejected")
        assert result.status == "REJECTED"
        assert result.requires_manual_review

    def test_pending_manual_review(self) -> None:
        r = PostTradeReconciler()
        result = r.reconcile("T1", broker_order_status="pending")
        assert result.status == "CLEAN_PENDING"
        assert result.requires_manual_review

    def test_timeout_manual_review(self) -> None:
        r = PostTradeReconciler()
        result = r.reconcile("T1", broker_order_status="timeout")
        assert result.status == "BROKER_TIMEOUT"
        assert result.requires_manual_review
        assert result.unknown_order_state


class TestLivePilotFreezeState:
    def test_freeze_creates_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            freeze = LivePilotFreezeState(state_dir=f"{tmp}/live_pilot")
            freeze.freeze("T1", state="FROZEN_CLEAN")
            assert freeze.is_frozen() is True

    def test_not_frozen_initially(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            freeze = LivePilotFreezeState(state_dir=f"{tmp}/live_pilot")
            assert freeze.is_frozen() is False

    def test_release_changes_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            freeze = LivePilotFreezeState(state_dir=f"{tmp}/live_pilot")
            freeze.freeze("T1")
            freeze.release("admin", "review_complete")
            assert freeze.is_frozen() is False

    def test_invalid_freeze_state_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            freeze = LivePilotFreezeState(state_dir=f"{tmp}/live_pilot")
            with pytest.raises(ValueError):
                freeze.freeze("T1", state="INVALID")

    def test_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            freeze = LivePilotFreezeState(state_dir=f"{tmp}/live_pilot")
            s = freeze.status()
            assert s["frozen"] is False
            freeze.freeze("T1", state="FROZEN_PENDING_REVIEW")
            s = freeze.status()
            assert s["frozen"] is True


class TestExecutionQuality:
    def test_filled_generates_stop(self) -> None:
        r = generate_execution_quality("T1", execution_status="filled", fill_price=500.0, limit_price=500.0)
        assert r.next_action == "STOP"

    def test_partial_generates_review(self) -> None:
        r = generate_execution_quality("T1", execution_status="filled", partial_fill=True)
        assert r.next_action == "REVIEW"

    def test_rejected_generates_stop(self) -> None:
        r = generate_execution_quality("T1", execution_status="rejected", reject_reason="price_outside_band")
        assert r.next_action == "STOP"

    def test_timeout_generates_stop(self) -> None:
        r = generate_execution_quality("T1", execution_status="timeout")
        assert r.next_action == "STOP"


class TestG5PostTradeDossier:
    def test_not_ready_no_ticket(self) -> None:
        d = G5PostTradeDossier()
        assert d.determine_decision() == "NOT_READY"

    def test_blocked_no_submit_lock(self) -> None:
        d = G5PostTradeDossier(ticket_id="T1", order_evidence={"status": "filled"},
                               execution_evidence={"execution_status": "filled"},
                               safety_evidence={"submit_once_active": False})
        assert d.determine_decision() == "BLOCKED"

    def test_stop_and_review_when_all_clean(self) -> None:
        d = G5PostTradeDossier(
            ticket_id="T1",
            order_evidence={"status": "filled"},
            execution_evidence={"execution_status": "filled"},
            safety_evidence={
                "submit_once_active": True,
                "second_order_detected": False,
                "freeze_active": True,
            },
        )
        assert d.determine_decision() == "STOP_AND_REVIEW"

    def test_to_dict(self) -> None:
        d = G5PostTradeDossier(ticket_id="T1")
        dd = d.to_dict()
        assert dd["ticket_id"] == "T1"

    def test_to_markdown(self) -> None:
        d = G5PostTradeDossier(ticket_id="T1")
        d.determine_decision()
        md = d.to_markdown()
        assert "G5 Post-Trade Dossier" in md
