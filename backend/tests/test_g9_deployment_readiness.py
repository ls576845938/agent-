"""Tests for G9 DeploymentReadinessCheck (ReadinessChecker).

All tests use tmp_path for data isolation. No real broker calls.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

from quant_us.live.g9_readiness import ReadinessChecker, DeploymentReadinessCheck, ReadinessStatus


class TestDeploymentReadiness:
    """Tests for ReadinessChecker safety and logic."""

    def _setup_all_requirements(self, tmp_path: Path) -> None:
        """Helper: create all required artifacts for readiness."""
        live_pilot = tmp_path / "live_pilot"

        releases_dir = live_pilot / "releases"
        releases_dir.mkdir(parents=True, exist_ok=True)
        (releases_dir / "rel_test.json").write_text(json.dumps({
            "release_id": "rel_test",
            "status": "APPROVED",
            "config_hash": "abc123",
            "approved_by": "alice",
            "approved_at": datetime.now(timezone.utc).isoformat(),
            "promotion_manifest_ids": [],
            "session_report_ids": [],
            "created_at": datetime.now(timezone.utc).isoformat(),
        }))

        (live_pilot / "runtime_config.json").write_text(json.dumps({
            "mode": "PAPER",
            "base_url": "https://paper-api.alpaca.markets",
        }))

        env_dir = live_pilot / "envelopes"
        env_dir.mkdir(parents=True, exist_ok=True)
        (env_dir / "default.json").write_text(json.dumps({
            "envelope_id": "env_default",
            "max_order_notional": 100.0,
        }))

        backup_dir = live_pilot / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        (backup_dir / "backup_record_bu_test.json").write_text(json.dumps({
            "backup_id": "bu_test",
            "archive_name": "test.tar.gz",
            "dry_run": False,
            "file_count": 0,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }))

        archive_dir = live_pilot / "audit_archives"
        archive_dir.mkdir(parents=True, exist_ok=True)
        (archive_dir / "audit_archive_record_arc_test.json").write_text(json.dumps({
            "archive_id": "arc_test",
            "archive_name": "test_archive.tar.gz",
            "audit_file_count": 0,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }))

    def test_missing_release_returns_blocked(self, tmp_path: Path) -> None:
        """No release manifest -> BLOCKED."""
        checker = ReadinessChecker(data_root=str(tmp_path))
        readiness = checker.check()
        assert readiness.status == ReadinessStatus.BLOCKED
        assert any("release" in r for r in readiness.block_reasons)

    def test_config_drift_returns_blocked(self, tmp_path: Path) -> None:
        """Config issues -> BLOCKED."""
        self._setup_all_requirements(tmp_path)
        (tmp_path / "live_pilot" / "runtime_config.json").unlink()
        checker = ReadinessChecker(data_root=str(tmp_path))
        readiness = checker.check()
        assert readiness.status == ReadinessStatus.BLOCKED

    def test_readiness_never_triggers_deployment(self, tmp_path: Path) -> None:
        """Safety: ReadinessChecker has no deploy method."""
        checker = ReadinessChecker(data_root=str(tmp_path))
        methods = [m for m in dir(checker) if "deploy" in m.lower()]
        assert all("deploy" not in m.lower() for m in methods)

    def test_readiness_never_calls_submit_order(self, tmp_path: Path) -> None:
        """Safety: ReadinessChecker has no submit_order capability."""
        checker = ReadinessChecker(data_root=str(tmp_path))
        methods = [m for m in dir(checker) if "order" in m.lower()]
        assert not methods, f"Found order-related methods: {methods}"

    def test_load_previous_check(self, tmp_path: Path) -> None:
        """Can load a previously saved readiness check."""
        checker = ReadinessChecker(data_root=str(tmp_path))
        readiness = checker.check()
        loaded = checker.load(readiness.check_id)
        assert loaded is not None
        assert loaded.check_id == readiness.check_id
        assert loaded.status == readiness.status
