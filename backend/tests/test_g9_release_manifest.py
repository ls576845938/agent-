"""Tests for G9 ReleaseManifestManager.

All tests use tmp_path for data isolation. No real broker calls.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from quant_us.live.g9_release_manifest import ReleaseManifestManager, ReleaseManifest


class TestReleaseManifest:
    """Tests for ReleaseManifest lifecycle and safety invariants."""

    def test_release_created_with_config_hash(self, tmp_path: Path) -> None:
        """Release manifest is created with a config_hash."""
        mgr = ReleaseManifestManager(data_root=str(tmp_path))
        manifest = mgr.create()
        assert manifest.release_id is not None
        assert manifest.config_hash != ""
        assert manifest.status == "DRAFT"

    def test_release_approve_requires_human(self, tmp_path: Path) -> None:
        """Approve requires non-empty approved_by."""
        mgr = ReleaseManifestManager(data_root=str(tmp_path))
        manifest = mgr.create()
        with pytest.raises(ValueError, match="approver"):
            mgr.approve(manifest.release_id, approved_by="")

    def test_approve_changes_status_and_records(self, tmp_path: Path) -> None:
        """Approve records approver name and timestamp."""
        mgr = ReleaseManifestManager(data_root=str(tmp_path))
        manifest = mgr.create()
        approved = mgr.approve(manifest.release_id, approved_by="alice")
        assert approved.status == "APPROVED"
        assert approved.approved_by == "alice"
        assert approved.approved_at != ""

    def test_release_never_auto_deploys(self, tmp_path: Path) -> None:
        """Approval does not trigger deployment."""
        mgr = ReleaseManifestManager(data_root=str(tmp_path))
        manifest = mgr.create()
        approved = mgr.approve(manifest.release_id, approved_by="bob")
        assert approved.status == "APPROVED"
        # Verify approve does not trigger deployment
        assert not hasattr(mgr, "deploy")

    def test_rollback_changes_status(self, tmp_path: Path) -> None:
        """Rollback changes status to ROLLED_BACK."""
        mgr = ReleaseManifestManager(data_root=str(tmp_path))
        manifest = mgr.create()
        rolled_back = mgr.rollback(manifest.release_id, reason="Bug found")
        assert rolled_back.status == "ROLLED_BACK"
        # Verify rollback is persisted
        loaded = mgr.load(manifest.release_id)
        assert loaded is not None
        assert loaded.status == "ROLLED_BACK"

    def test_double_rollback_raises(self, tmp_path: Path) -> None:
        """Double rollback raises ValueError."""
        mgr = ReleaseManifestManager(data_root=str(tmp_path))
        manifest = mgr.create()
        mgr.rollback(manifest.release_id, reason="First rollback")
        with pytest.raises(ValueError, match="ROLLED_BACK"):
            mgr.rollback(manifest.release_id, reason="Second rollback")

    def test_reject_changes_status(self, tmp_path: Path) -> None:
        """Reject changes status to REJECTED."""
        mgr = ReleaseManifestManager(data_root=str(tmp_path))
        manifest = mgr.create()
        rejected = mgr.reject(manifest.release_id, reason="Not ready")
        assert rejected.status == "REJECTED"

    def test_never_calls_submit_order(self, tmp_path: Path) -> None:
        """Safety invariant: ReleaseManifestManager has no submit_order."""
        import inspect
        import quant_us.live.g9_release_manifest as mod
        source = inspect.getsource(mod)
        assert "submit_order" not in source
        assert "AlpacaBroker" not in source
