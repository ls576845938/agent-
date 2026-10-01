"""Tests for G8 SessionExecutionBridge.

All tests use tmp_path for data isolation. No real broker calls.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from quant_us.live.g8_session_bridge import SessionExecutionBridge
from quant_us.live.g8_session_state import SessionRuntimeStateManager
from quant_us.live.g7_manifest import StrategyPromotionManifestManager


class TestSessionExecutionBridge:
    """Tests for SessionExecutionBridge lifecycle and safety."""

    def _create_approved_promotion(self, tmp_path: Path, promo_id: str = "promo_bridge") -> str:
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

    def _setup_armed_session(self, tmp_path: Path) -> tuple[SessionExecutionBridge, str, str]:
        """Helper: create bridge with armed session and approved promotion."""
        bridge = SessionExecutionBridge(data_root=str(tmp_path))
        promo_id = self._create_approved_promotion(tmp_path)
        session = bridge.state_mgr.create(promotion_id=promo_id)
        bridge.state_mgr.arm(session.session_id)
        return bridge, session.session_id, promo_id

    def test_can_submit_allows_when_armed(self, tmp_path: Path) -> None:
        """ARMED -> can_submit=True."""
        bridge, session_id, promo_id = self._setup_armed_session(tmp_path)
        allowed, reason = bridge.can_submit(session_id)
        assert allowed
        assert reason == "ok"

    def test_can_submit_blocks_when_frozen(self, tmp_path: Path) -> None:
        """FROZEN -> can_submit=False."""
        bridge, session_id, promo_id = self._setup_armed_session(tmp_path)
        bridge.state_mgr.activate(session_id)
        bridge.state_mgr.freeze(session_id, reason="ORDER_SUBMITTED")
        allowed, reason = bridge.can_submit(session_id)
        assert not allowed
        assert "FROZEN" in reason

    def test_can_submit_blocks_when_terminated(self, tmp_path: Path) -> None:
        """TERMINATED -> can_submit=False."""
        bridge, session_id, promo_id = self._setup_armed_session(tmp_path)
        bridge.state_mgr.terminate(session_id, reason="MAX_LOSS")
        allowed, reason = bridge.can_submit(session_id)
        assert not allowed
        assert "TERMINATED" in reason

    def test_can_submit_blocks_when_completed(self, tmp_path: Path) -> None:
        """COMPLETED -> can_submit=False."""
        bridge, session_id, promo_id = self._setup_armed_session(tmp_path)
        bridge.state_mgr.activate(session_id)
        bridge.state_mgr.freeze(session_id, reason="ORDER_SUBMITTED")
        bridge.state_mgr.complete(session_id)
        allowed, reason = bridge.can_submit(session_id)
        assert not allowed
        assert "COMPLETED" in reason

    def test_execute_blocks_terminated_session(self, tmp_path: Path) -> None:
        """execute_one_shot blocks when session is terminated."""
        bridge, session_id, promo_id = self._setup_armed_session(tmp_path)
        bridge.state_mgr.terminate(session_id, reason="USER_REQUEST")
        result = bridge.execute_one_shot(
            session_id=session_id,
            ticket_id="ticket_1",
        )
        assert "session_terminated" in result.get("errors", [])
        assert result["status"] == "TERMINATED"

    def test_execute_blocks_completed_session(self, tmp_path: Path) -> None:
        """execute_one_shot blocks when session is completed."""
        bridge, session_id, promo_id = self._setup_armed_session(tmp_path)
        bridge.state_mgr.activate(session_id)
        bridge.state_mgr.freeze(session_id, reason="ORDER_SUBMITTED")
        bridge.state_mgr.complete(session_id)
        result = bridge.execute_one_shot(
            session_id=session_id,
            ticket_id="ticket_1",
        )
        assert "session_completed" in result.get("errors", [])
        assert result["status"] == "COMPLETED"

    def test_dry_run_defaults_true(self, tmp_path: Path) -> None:
        """Default dry_run is True in execute_one_shot signature."""
        bridge = SessionExecutionBridge(data_root=str(tmp_path))
        import inspect
        sig = inspect.signature(bridge.execute_one_shot)
        assert sig.parameters["dry_run"].default is True

    def test_bridge_never_calls_submit_order(self, tmp_path: Path) -> None:
        """Safety: bridge never references real broker submit_order."""
        import inspect
        import quant_us.live.g8_session_bridge as mod
        source = inspect.getsource(mod)
        assert "AlpacaBroker" not in source
        assert "submit_order" not in source
        assert "broker.submit" not in source
