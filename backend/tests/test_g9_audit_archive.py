"""Tests for G9 AuditArchiveBuilder.

All tests use tmp_path for data isolation. No real broker calls.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from quant_us.live.g9_audit_archive import AuditArchiveBuilder, AuditArchive


class TestAuditArchive:
    """Tests for AuditArchiveBuilder collection and verification."""

    def _setup_audit_data(self, tmp_path: Path) -> None:
        """Helper: create test audit trail files."""
        live_pilot = tmp_path / "live_pilot"
        live_pilot.mkdir(parents=True, exist_ok=True)
        board_dir = live_pilot / "board"
        board_dir.mkdir(parents=True, exist_ok=True)
        (board_dir / "board_audit.jsonl").write_text(
            '{"action": "APPROVE", "timestamp": "2026-01-01"}\n'
        )
        session_dir = live_pilot / "session"
        session_dir.mkdir(parents=True, exist_ok=True)
        (session_dir / "session_audit.jsonl").write_text(
            '{"action": "ARM", "timestamp": "2026-01-01"}\n'
        )
        (session_dir / "session_gate_audit.jsonl").write_text(
            '{"action": "CHECK", "timestamp": "2026-01-01"}\n'
        )

    def test_archive_collects_all_audit_trails(self, tmp_path: Path) -> None:
        """Archive collects audit files from all sources."""
        self._setup_audit_data(tmp_path)
        builder = AuditArchiveBuilder(data_root=str(tmp_path))
        archive = builder.build()
        assert archive.archive_id is not None
        assert archive.audit_file_count >= 3
        assert len(archive.audit_sources) >= 1

    def test_archive_checksum_verified(self, tmp_path: Path) -> None:
        """Archive checksum can be verified."""
        self._setup_audit_data(tmp_path)
        builder = AuditArchiveBuilder(data_root=str(tmp_path))
        archive = builder.build()
        assert builder.verify(archive.archive_id)

    def test_verify_nonexistent_archive(self, tmp_path: Path) -> None:
        """Verify returns False for nonexistent archive."""
        builder = AuditArchiveBuilder(data_root=str(tmp_path))
        assert not builder.verify("nonexistent_archive")

    def test_build_empty_directory(self, tmp_path: Path) -> None:
        """Build with no audit data creates archive with zero files."""
        live_pilot = tmp_path / "live_pilot"
        live_pilot.mkdir(parents=True, exist_ok=True)
        builder = AuditArchiveBuilder(data_root=str(tmp_path))
        archive = builder.build()
        assert archive.audit_file_count == 0

    def test_never_calls_submit_order(self, tmp_path: Path) -> None:
        """Safety invariant: AuditArchiveBuilder has no submit_order."""
        import inspect
        import quant_us.live.g9_audit_archive as mod
        source = inspect.getsource(mod)
        assert "submit_order" not in source
        assert "AlpacaBroker" not in source
