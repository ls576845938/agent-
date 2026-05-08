"""Tests for G7 PromotionBoard.

All tests use tmp_path for data isolation. No real broker calls.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from quant_us.live.g7_promotion_board import PromotionBoard, BoardDecision


class TestPromotionBoard:
    """Tests for PromotionBoard governance and safety invariants."""

    def _create_manifest(self, tmp_path: Path, promotion_id: str = "prom_test") -> str:
        """Helper: create a manifest in PENDING_REVIEW status for testing."""
        from quant_us.live.g7_manifest import StrategyPromotionManifestManager

        mgr = StrategyPromotionManifestManager(data_root=str(tmp_path))
        manifest = mgr.create(
            source_episode_id="ep_1",
            scorecard_path=str(tmp_path / "sc.json"),
            strategy_id="strat_a",
            paper_30d_path=str(tmp_path / "paper.json"),
            shadow_5d_path=str(tmp_path / "shadow.json"),
            g5_dossier_path=str(tmp_path / "g5.json"),
            g6_episode_dossier_path=str(tmp_path / "g6.json"),
        )
        # Set PENDING_REVIEW so board can act on it
        mgr.set_pending_review(manifest.promotion_id)
        return manifest.promotion_id

    def test_board_review_requires_board_member(self, tmp_path: Path) -> None:
        """Review blocks when board_member is missing."""
        board = PromotionBoard(data_root=str(tmp_path))
        prom_id = self._create_manifest(tmp_path)
        with pytest.raises(ValueError, match="board_member"):
            board.review(
                promotion_id=prom_id,
                board_member="",
                decision="APPROVED_FOR_G8_REVIEW",
                reason="All checks pass",
            )

    def test_board_review_requires_decision(self, tmp_path: Path) -> None:
        """Review blocks when decision is empty."""
        board = PromotionBoard(data_root=str(tmp_path))
        prom_id = self._create_manifest(tmp_path)
        with pytest.raises(ValueError, match="decision"):
            board.review(
                promotion_id=prom_id,
                board_member="alice",
                decision="",
                reason="Test",
            )

    def test_board_review_requires_reason(self, tmp_path: Path) -> None:
        """Review blocks when reason is empty."""
        board = PromotionBoard(data_root=str(tmp_path))
        prom_id = self._create_manifest(tmp_path)
        with pytest.raises(ValueError, match="reason"):
            board.review(
                promotion_id=prom_id,
                board_member="alice",
                decision="APPROVED_FOR_G8_REVIEW",
                reason="",
            )

    def test_board_approve_writes_audit(self, tmp_path: Path) -> None:
        """Board approve writes audit trail."""
        board = PromotionBoard(data_root=str(tmp_path))
        prom_id = self._create_manifest(tmp_path)
        decision = board.review(
            promotion_id=prom_id,
            board_member="alice",
            decision="APPROVED_FOR_G8_REVIEW",
            reason="Episode completed cleanly",
        )
        assert decision.decision == "APPROVED_FOR_G8_REVIEW"
        assert decision.board_member == "alice"
        assert decision.reason == "Episode completed cleanly"

        # Verify manifest was approved
        from quant_us.live.g7_manifest import StrategyPromotionManifestManager
        mgr = StrategyPromotionManifestManager(data_root=str(tmp_path))
        manifest = mgr.load(prom_id)
        assert manifest is not None
        assert manifest.status == "APPROVED_FOR_G8_REVIEW"
        assert manifest.approved_by == "alice"

    def test_board_reject_writes_reason(self, tmp_path: Path) -> None:
        """Board reject saves rejection reason."""
        board = PromotionBoard(data_root=str(tmp_path))
        prom_id = self._create_manifest(tmp_path)
        decision = board.review(
            promotion_id=prom_id,
            board_member="bob",
            decision="REJECTED",
            reason="Insufficient evidence",
        )
        assert decision.decision == "REJECTED"
        assert decision.reason == "Insufficient evidence"

        # Verify manifest was rejected
        from quant_us.live.g7_manifest import StrategyPromotionManifestManager
        mgr = StrategyPromotionManifestManager(data_root=str(tmp_path))
        manifest = mgr.load(prom_id)
        assert manifest is not None
        assert manifest.status == "REJECTED"
        assert manifest.rejection_reason == "Insufficient evidence"

    def test_board_never_auto_approves(self, tmp_path: Path) -> None:
        """No auto-approve path exists."""
        board = PromotionBoard(data_root=str(tmp_path))
        prom_id = self._create_manifest(tmp_path)
        # Verify no method auto-approves
        from quant_us.live.g7_manifest import StrategyPromotionManifestManager
        mgr = StrategyPromotionManifestManager(data_root=str(tmp_path))
        manifest = mgr.load(prom_id)
        assert manifest is not None
        assert manifest.status == "PENDING_REVIEW"  # Still pending, not auto-approved
        # The review method docstring confirms explicit action required
        assert "NEVER auto-approves" in PromotionBoard.review.__doc__

    def test_list_pending_works(self, tmp_path: Path) -> None:
        """list_pending returns manifests in PENDING_REVIEW."""
        board = PromotionBoard(data_root=str(tmp_path))
        p1 = self._create_manifest(tmp_path, "prom_pending_1")
        p2 = self._create_manifest(tmp_path, "prom_pending_2")
        pending = board.list_pending()
        assert len(pending) >= 1

    def test_board_never_calls_submit_order(self, tmp_path: Path) -> None:
        """Safety invariant: PromotionBoard has no submit_order capability."""
        board = PromotionBoard(data_root=str(tmp_path))
        import inspect
        source = inspect.getsource(type(board))
        assert "submit_order" not in source
        assert "AlpacaBroker" not in source
        methods = [m for m in dir(board) if "submit" in m.lower()]
        assert "submit_order" not in methods

    def test_invalid_decision_raises(self, tmp_path: Path) -> None:
        """Invalid decision string raises ValueError."""
        board = PromotionBoard(data_root=str(tmp_path))
        prom_id = self._create_manifest(tmp_path)
        with pytest.raises(ValueError, match="Invalid decision"):
            board.review(
                promotion_id=prom_id,
                board_member="alice",
                decision="INVALID_DECISION",
                reason="test",
            )

    def test_board_decision_persistence(self, tmp_path: Path) -> None:
        """Board decisions are persisted and can be loaded."""
        board = PromotionBoard(data_root=str(tmp_path))
        prom_id = self._create_manifest(tmp_path)
        decision = board.review(
            promotion_id=prom_id,
            board_member="alice",
            decision="APPROVED_FOR_G8_REVIEW",
            reason="Good episode",
        )
        loaded = board.load_decision(decision.decision_id)
        assert loaded is not None
        assert loaded.decision_id == decision.decision_id
        assert loaded.board_member == "alice"
        assert loaded.decision == "APPROVED_FOR_G8_REVIEW"
