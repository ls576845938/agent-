"""Tests for G7 StrategyPromotionManifestManager.

All tests use tmp_path for data isolation. No real broker calls.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from quant_us.live.g7_manifest import (
    StrategyPromotionManifestManager,
    StrategyPromotionManifest,
)


class TestStrategyPromotionManifest:
    """Tests for StrategyPromotionManifest lifecycle and safety."""

    def _create_evidence_files(self, tmp_path: Path) -> dict[str, str]:
        """Create evidence files on disk and return paths."""
        files = {
            "paper_30d": tmp_path / "paper_30d.json",
            "shadow_5d": tmp_path / "shadow_5d.json",
            "g5_dossier": tmp_path / "g5_dossier.json",
            "g6_dossier": tmp_path / "g6_dossier.json",
            "scorecard": tmp_path / "scorecard.json",
        }
        for f in files.values():
            f.write_text("{}")
        return {k: str(v) for k, v in files.items()}

    def test_create_manifest_from_episode(self, tmp_path: Path) -> None:
        """Create manifest with evidence references."""
        paths = self._create_evidence_files(tmp_path)
        mgr = StrategyPromotionManifestManager(data_root=str(tmp_path))
        manifest = mgr.create(
            source_episode_id="ep_1",
            scorecard_path=paths["scorecard"],
            strategy_id="strat_a",
            strategy_version="1.0.0",
            paper_30d_path=paths["paper_30d"],
            shadow_5d_path=paths["shadow_5d"],
            g5_dossier_path=paths["g5_dossier"],
            g6_episode_dossier_path=paths["g6_dossier"],
        )
        assert manifest.promotion_id is not None
        assert manifest.strategy_id == "strat_a"
        assert manifest.strategy_version == "1.0.0"
        assert manifest.source_episode_id == "ep_1"
        assert manifest.status == "DRAFT"

    def test_missing_evidence_blocks_creation(self, tmp_path: Path) -> None:
        """is_valid_for_g8 returns False when evidence paths are missing."""
        mgr = StrategyPromotionManifestManager(data_root=str(tmp_path))
        manifest = mgr.create(
            source_episode_id="ep_no_evidence",
            scorecard_path="",
            strategy_id="strat_b",
        )
        # Approve it first
        mgr.approve(manifest.promotion_id, approved_by="alice")
        # Now check validity — should fail because evidence paths are empty
        valid, reason = mgr.is_valid_for_g8(manifest.promotion_id)
        assert not valid
        assert "evidence" in reason.lower() or "Missing" in reason

    def test_manifest_approve_requires_human(self, tmp_path: Path) -> None:
        """Approve requires non-empty approved_by."""
        mgr = StrategyPromotionManifestManager(data_root=str(tmp_path))
        manifest = mgr.create(
            source_episode_id="ep_2",
            scorecard_path=str(tmp_path / "sc.json"),
        )
        with pytest.raises(ValueError, match="approved_by"):
            mgr.approve(manifest.promotion_id, approved_by="")

    def test_approve_changes_status(self, tmp_path: Path) -> None:
        """Approve changes status and records approver."""
        paths = self._create_evidence_files(tmp_path)
        mgr = StrategyPromotionManifestManager(data_root=str(tmp_path))
        manifest = mgr.create(
            source_episode_id="ep_3",
            scorecard_path=paths["scorecard"],
            paper_30d_path=paths["paper_30d"],
            shadow_5d_path=paths["shadow_5d"],
            g5_dossier_path=paths["g5_dossier"],
            g6_episode_dossier_path=paths["g6_dossier"],
        )
        approved = mgr.approve(manifest.promotion_id, approved_by="alice")
        assert approved.status == "APPROVED_FOR_G8_REVIEW"
        assert approved.approved_by == "alice"

    def test_is_valid_for_g8_checks_all(self, tmp_path: Path) -> None:
        """is_valid_for_g8 returns True when all conditions met."""
        paths = self._create_evidence_files(tmp_path)
        mgr = StrategyPromotionManifestManager(data_root=str(tmp_path))
        manifest = mgr.create(
            source_episode_id="ep_4",
            scorecard_path=paths["scorecard"],
            paper_30d_path=paths["paper_30d"],
            shadow_5d_path=paths["shadow_5d"],
            g5_dossier_path=paths["g5_dossier"],
            g6_episode_dossier_path=paths["g6_dossier"],
        )
        mgr.approve(manifest.promotion_id, approved_by="bob")
        valid, reason = mgr.is_valid_for_g8(manifest.promotion_id)
        assert valid

    def test_is_valid_for_g8_fails_without_approval(self, tmp_path: Path) -> None:
        """is_valid_for_g8 fails when status is not APPROVED_FOR_G8_REVIEW."""
        paths = self._create_evidence_files(tmp_path)
        mgr = StrategyPromotionManifestManager(data_root=str(tmp_path))
        manifest = mgr.create(
            source_episode_id="ep_5",
            scorecard_path=paths["scorecard"],
            paper_30d_path=paths["paper_30d"],
            shadow_5d_path=paths["shadow_5d"],
            g5_dossier_path=paths["g5_dossier"],
            g6_episode_dossier_path=paths["g6_dossier"],
        )
        valid, reason = mgr.is_valid_for_g8(manifest.promotion_id)
        assert not valid
        assert "DRAFT" in reason

    def test_manifest_expiry(self, tmp_path: Path) -> None:
        """Manifest becomes invalid after expiry."""
        paths = self._create_evidence_files(tmp_path)
        mgr = StrategyPromotionManifestManager(data_root=str(tmp_path))
        manifest = mgr.create(
            source_episode_id="ep_exp",
            scorecard_path=paths["scorecard"],
            paper_30d_path=paths["paper_30d"],
            shadow_5d_path=paths["shadow_5d"],
            g5_dossier_path=paths["g5_dossier"],
            g6_episode_dossier_path=paths["g6_dossier"],
        )
        mgr.approve(manifest.promotion_id, approved_by="alice")

        # Set expires_at in the past
        from datetime import datetime, timezone, timedelta
        manifest.expires_at = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        mgr.save(manifest)

        valid, reason = mgr.is_valid_for_g8(manifest.promotion_id)
        assert not valid
        assert "expired" in reason.lower() or "valid" in reason.lower() or "draft" in reason.lower()

    def test_set_pending_review(self, tmp_path: Path) -> None:
        """set_pending_review transitions from DRAFT to PENDING_REVIEW."""
        mgr = StrategyPromotionManifestManager(data_root=str(tmp_path))
        manifest = mgr.create(source_episode_id="ep_pr", scorecard_path=str(tmp_path / "sc.json"))
        assert manifest.status == "DRAFT"
        pending = mgr.set_pending_review(manifest.promotion_id)
        assert pending.status == "PENDING_REVIEW"

    def test_set_pending_review_from_wrong_state(self, tmp_path: Path) -> None:
        """set_pending_review fails when not DRAFT."""
        mgr = StrategyPromotionManifestManager(data_root=str(tmp_path))
        manifest = mgr.create(source_episode_id="ep_wrong", scorecard_path=str(tmp_path / "sc.json"))
        mgr.set_pending_review(manifest.promotion_id)
        with pytest.raises(ValueError, match="pending review"):
            mgr.set_pending_review(manifest.promotion_id)

    def test_manifest_never_triggers_orders(self, tmp_path: Path) -> None:
        """Safety invariant: manifest manager has no submit_order capability."""
        mgr = StrategyPromotionManifestManager(data_root=str(tmp_path))
        import inspect
        source = inspect.getsource(type(mgr))
        assert "submit_order" not in source
        assert "AlpacaBroker" not in source
