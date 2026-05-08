"""Tests proving G8 session cannot loop-submit orders.

All tests use tmp_path for data isolation. No real broker calls.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from quant_us.live.g8_session_state import (
    SessionRuntimeStateManager,
    SessionStatus,
)
from quant_us.live.g8_daily_cap import DailyTradingCapManager
from quant_us.live.g8_session_gate import SessionGate
from quant_us.live.g7_manifest import StrategyPromotionManifestManager


class TestNoContinuousTrading:
    """Proves G8 session cannot loop-submit orders."""

    def _create_approved_promotion(self, tmp_path: Path, promo_id: str = "promo_nc") -> str:
        """Helper: create an approved promotion manifest."""
        mgr = StrategyPromotionManifestManager(data_root=str(tmp_path))
        base = tmp_path
        for sub in [
            f"data/paper/{promo_id}/30d.pdf",
            f"data/shadow/{promo_id}/5d.pdf",
            f"data/dossiers/g5_{promo_id}.json",
            f"data/dossiers/g6_{promo_id}.json",
            f"data/scorecards/sc_{promo_id}.json",
        ]:
            p = base / sub
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("{}")
        manifest = mgr.create(
            source_episode_id=f"ep_{promo_id}",
            scorecard_path=str(base / f"data/scorecards/sc_{promo_id}.json"),
            strategy_id="strat_a",
            paper_30d_path=str(base / f"data/paper/{promo_id}/30d.pdf"),
            shadow_5d_path=str(base / f"data/shadow/{promo_id}/5d.pdf"),
            g5_dossier_path=str(base / f"data/dossiers/g5_{promo_id}.json"),
            g6_episode_dossier_path=str(base / f"data/dossiers/g6_{promo_id}.json"),
        )
        mgr.set_pending_review(manifest.promotion_id)
        mgr.approve(manifest.promotion_id, approved_by="alice")
        return manifest.promotion_id

    def test_session_frozen_after_one_submit(self, tmp_path: Path) -> None:
        """After freeze, status is FROZEN and cannot submit."""
        mgr = SessionRuntimeStateManager(data_root=str(tmp_path))
        promo_id = self._create_approved_promotion(tmp_path)
        session = mgr.create(promotion_id=promo_id)
        mgr.arm(session.session_id)
        mgr.activate(session.session_id)
        mgr.freeze(session.session_id, reason="ORDER_SUBMITTED")

        state = mgr.load(session.session_id)
        assert state is not None
        assert state.status == SessionStatus.FROZEN
        # Cannot submit while frozen
        assert state.status not in (SessionStatus.ARMED, SessionStatus.ACTIVE_MANUAL_SUPERVISION)

    def test_daily_cap_prevents_second_order(self, tmp_path: Path) -> None:
        """Daily cap prevents a second order on the same day."""
        cap_mgr = DailyTradingCapManager(data_root=str(tmp_path))
        from datetime import date
        today = date.today().isoformat()

        # Record an order which creates the cap with max_orders_today=1 default
        cap_mgr.get_or_create("session_1", today)
        cap = cap_mgr.load("session_1", today)
        assert cap is not None
        cap.orders_submitted_today = cap.max_orders_today
        cap_mgr._save(cap)

        # Second order blocked
        allowed, reason = cap_mgr.check("session_1", today, proposed_notional=50.0)
        assert not allowed
        assert "max_orders_per_day" in reason

    def test_session_gate_blocks_without_manual_review(self, tmp_path: Path) -> None:
        """Gate blocks when manual_confirm is False."""
        gate = SessionGate(data_root=str(tmp_path))
        state_mgr = SessionRuntimeStateManager(data_root=str(tmp_path))
        promo_id = self._create_approved_promotion(tmp_path)
        session = state_mgr.create(promotion_id=promo_id)
        state_mgr.arm(session.session_id)

        decision = gate.check(
            session_id=session.session_id,
            promotion_id=promo_id,
            ticket_id="ticket_1",
            manual_confirm=False,
            dry_run=False,
        )
        assert decision.decision == "BLOCKED"
        assert "missing_manual_confirm" in decision.block_reasons

    def test_no_while_loop_submits_orders(self, tmp_path: Path) -> None:
        """Code analysis: verify no while-loop order submission in G8 code."""
        import quant_us.live.g8_session_state as ssm
        import quant_us.live.g8_session_gate as sgate
        import quant_us.live.g8_session_bridge as sbridge
        import quant_us.live.g8_daily_cap as scap

        for mod in [ssm, sgate, sbridge, scap]:
            import inspect
            content = inspect.getsource(mod)
            # No while-loop that could auto-submit
            assert "while True" not in content
            assert "while 1" not in content
            # No auto-continue
            assert "auto_continue" not in content.lower()

    def test_session_requires_resume_after_freeze(self, tmp_path: Path) -> None:
        """Session must be manually resumed after freeze before next order."""
        mgr = SessionRuntimeStateManager(data_root=str(tmp_path))
        promo_id = self._create_approved_promotion(tmp_path)
        session = mgr.create(promotion_id=promo_id)
        mgr.arm(session.session_id)
        mgr.activate(session.session_id)
        mgr.freeze(session.session_id, reason="ORDER_SUBMITTED")

        state = mgr.load(session.session_id)
        assert state is not None
        assert state.status == SessionStatus.FROZEN

        # Cannot go from FROZEN to ARMED directly
        with pytest.raises(ValueError):
            mgr.arm(session.session_id)

        # Must resume first
        resumed = mgr.resume(session.session_id)
        assert resumed.status == SessionStatus.ACTIVE_MANUAL_SUPERVISION

    def test_never_calls_submit_order(self, tmp_path: Path) -> None:
        """Safety invariant: no G8 module calls submit_order directly."""
        import inspect
        for mod_name in [
            "quant_us.live.g8_session_state",
            "quant_us.live.g8_session_gate",
            "quant_us.live.g8_session_bridge",
            "quant_us.live.g8_daily_cap",
        ]:
            import importlib
            mod = importlib.import_module(mod_name)
            source = inspect.getsource(mod)
            assert "submit_order" not in source, f"{mod_name} contains submit_order"
