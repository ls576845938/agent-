"""Tests for G9 BackupRestoreController.

All tests use tmp_path for data isolation. No real broker calls.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from quant_us.live.g9_backup import BackupRestoreController


class TestBackup:
    """Tests for BackupRestoreController safety and functionality."""

    def _setup_data(self, tmp_path: Path) -> None:
        """Helper: create test data files."""
        live_pilot = tmp_path / "live_pilot"
        live_pilot.mkdir(parents=True, exist_ok=True)
        (live_pilot / "runtime_config.json").write_text('{"mode": "PAPER"}')
        (live_pilot / "readme.txt").write_text("test data")

    def _setup_data_with_secrets(self, tmp_path: Path) -> None:
        """Helper: create test data including secret files."""
        self._setup_data(tmp_path)
        live_pilot = tmp_path / "live_pilot"
        (live_pilot / ".env").write_text("API_KEY=secret_123")
        (live_pilot / "api_key.txt").write_text("sk_test_key")
        (live_pilot / "credentials.json").write_text('{"secret": "value"}')

    def test_backup_creates_archive(self, tmp_path: Path) -> None:
        """Backup creates a tar.gz archive."""
        self._setup_data(tmp_path)
        ctrl = BackupRestoreController(data_root=str(tmp_path))
        record = ctrl.create_backup(dry_run=False)
        assert record.backup_id is not None
        assert record.file_count > 0
        assert record.dry_run is False
        assert (ctrl.backup_dir / record.archive_name).exists()

    def test_backup_excludes_secret_files(self, tmp_path: Path) -> None:
        """Backup excludes .env and key files."""
        self._setup_data_with_secrets(tmp_path)
        ctrl = BackupRestoreController(data_root=str(tmp_path))
        record = ctrl.create_backup(dry_run=False)
        assert record.file_count > 0
        assert record.excluded_count > 0

        import tarfile
        archive_path = ctrl.backup_dir / record.archive_name
        with tarfile.open(archive_path, "r:gz") as tar:
            names = [m.name for m in tar.getmembers()]
        assert not any(".env" in n for n in names)
        assert not any("api_key" in n for n in names)
        assert not any("credential" in n for n in names)

    def test_restore_defaults_dry_run(self, tmp_path: Path) -> None:
        """Restore defaults to dry_run=True (no actual extraction)."""
        self._setup_data(tmp_path)
        ctrl = BackupRestoreController(data_root=str(tmp_path))
        record = ctrl.create_backup(dry_run=False)
        (tmp_path / "live_pilot" / "runtime_config.json").unlink()
        result = ctrl.restore(record.backup_id, dry_run=True)
        assert result["status"] == "DRY_RUN"
        assert not (tmp_path / "live_pilot" / "runtime_config.json").exists()

    def test_backup_checksum_verified(self, tmp_path: Path) -> None:
        """Backup checksum can be verified."""
        self._setup_data(tmp_path)
        ctrl = BackupRestoreController(data_root=str(tmp_path))
        record = ctrl.create_backup(dry_run=False)
        assert ctrl.verify_checksum(record.backup_id)

    def test_list_backups(self, tmp_path: Path) -> None:
        """list_backups returns backup records."""
        self._setup_data(tmp_path)
        ctrl = BackupRestoreController(data_root=str(tmp_path))
        ctrl.create_backup(dry_run=True)
        ctrl.create_backup(dry_run=True)
        records = ctrl.list_backups()
        assert len(records) == 2

    def test_restore_nonexistent_returns_error(self, tmp_path: Path) -> None:
        """Restoring nonexistent backup returns error."""
        ctrl = BackupRestoreController(data_root=str(tmp_path))
        result = ctrl.restore("nonexistent_backup")
        assert result["status"] == "ERROR"

    def test_never_calls_submit_order(self, tmp_path: Path) -> None:
        """Safety: backup module has no submit_order."""
        import inspect
        import quant_us.live.g9_backup as mod
        source = inspect.getsource(mod)
        assert "submit_order" not in source
        assert "AlpacaBroker" not in source
