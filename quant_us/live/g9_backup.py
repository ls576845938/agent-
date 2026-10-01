"""G9 Backup and Restore Controller for Production Ops Hardening.

Creates versioned archives of operational data for disaster recovery.
Explicitly excludes secret-bearing files (API keys, credentials, .env).

Restore defaults to dry_run=True — NEVER auto-restores.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import tarfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_logger = logging.getLogger("g9_backup")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Secret/exclusion patterns
# ---------------------------------------------------------------------------

EXCLUDED_PATTERNS = [
    ".env",
    ".env.*",
    "*key*",
    "*secret*",
    "*credential*",
    "*token*",
    "api_key*",
    "api_secret*",
    "*password*",
    "__pycache__",
    "*.pyc",
    ".git",
]

EXCLUDED_SUFFIXES = {".pyc", ".pyo", ".log"}
EXCLUDED_NAMES = {".env", ".git", "__pycache__", "node_modules"}


# ---------------------------------------------------------------------------
# BackupRecord
# ---------------------------------------------------------------------------


@dataclass
class BackupRecord:
    backup_id: str
    archive_name: str = ""
    file_count: int = 0
    total_bytes: int = 0
    checksum: str = ""
    excluded_count: int = 0
    created_at: str = ""
    source_path: str = ""
    dry_run: bool = False

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = _utc_now().isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "backup_id": self.backup_id,
            "archive_name": self.archive_name,
            "file_count": self.file_count,
            "total_bytes": self.total_bytes,
            "checksum": self.checksum,
            "excluded_count": self.excluded_count,
            "created_at": self.created_at,
            "source_path": self.source_path,
            "dry_run": self.dry_run,
        }


# ---------------------------------------------------------------------------
# BackupRestoreController
# ---------------------------------------------------------------------------


class BackupRestoreController:
    """Creates and manages backup archives of operational data.

    NEVER includes secret files. NEVER auto-restores.
    Restore defaults to dry_run=True.
    """

    def __init__(self, data_root: str = "data") -> None:
        self.data_root = Path(data_root)
        self.backup_dir = self.data_root / "live_pilot" / "backups"
        self.backup_dir.mkdir(parents=True, exist_ok=True)

    def create_backup(self, dry_run: bool = False) -> BackupRecord:
        """Create a backup archive of the live_pilot data directory.

        Excludes:
        - .env and .env.* files
        - *key*, *secret*, *credential*, *token* patterns
        - __pycache__ and .pyc files
        - .git directory

        When dry_run=True, counts files but does NOT create an archive.
        """
        from quant_us.core.types import new_id

        backup_id = new_id("backup")
        timestamp = _utc_now().strftime("%Y%m%d_%H%M%S")
        archive_name = f"backup_{backup_id}_{timestamp}.tar.gz"

        included_files: list[Path] = []
        excluded_count = 0

        live_pilot_dir = self.data_root / "live_pilot"
        if not live_pilot_dir.exists():
            record = BackupRecord(
                backup_id=backup_id,
                archive_name=archive_name,
                source_path=str(live_pilot_dir),
                dry_run=dry_run,
            )
            self._save_record(record)
            _logger.warning("Backup: live_pilot directory not found at %s", live_pilot_dir)
            return record

        for path in live_pilot_dir.rglob("*"):
            if not path.is_file():
                continue

            if self._is_excluded(path):
                excluded_count += 1
                continue

            included_files.append(path)

        if dry_run:
            record = BackupRecord(
                backup_id=backup_id,
                archive_name=archive_name,
                file_count=len(included_files),
                total_bytes=sum(p.stat().st_size for p in included_files),
                excluded_count=excluded_count,
                source_path=str(live_pilot_dir),
                dry_run=True,
            )
            self._save_record(record)
            _logger.info(
                "Backup dry-run: %d files to include, %d excluded",
                len(included_files), excluded_count,
            )
            return record

        archive_path = self.backup_dir / archive_name
        checksum = self._build_archive(archive_path, included_files)

        total_bytes = sum(p.stat().st_size for p in included_files)

        record = BackupRecord(
            backup_id=backup_id,
            archive_name=archive_name,
            file_count=len(included_files),
            total_bytes=total_bytes,
            checksum=checksum,
            excluded_count=excluded_count,
            source_path=str(live_pilot_dir),
            dry_run=False,
        )
        self._save_record(record)
        _logger.info(
            "Backup created: %s (%d files, %d bytes, %d excluded)",
            archive_name, len(included_files), total_bytes, excluded_count,
        )
        return record

    def restore(self, backup_id: str, dry_run: bool = True) -> dict[str, Any]:
        """Restore from a backup archive.

        Default dry_run=True. NEVER auto-restores without explicit override.
        """
        record = self._load_record(backup_id)
        if record is None:
            return {"status": "ERROR", "error": f"Backup record not found: {backup_id}"}

        archive_path = self.backup_dir / record.archive_name
        if not archive_path.exists():
            return {
                "status": "ERROR",
                "error": f"Archive file not found: {archive_path}",
                "backup_id": backup_id,
            }

        if dry_run:
            # Verify archive integrity without extracting
            try:
                with tarfile.open(archive_path, "r:gz") as tar:
                    member_count = len(tar.getmembers())
                return {
                    "status": "DRY_RUN",
                    "backup_id": backup_id,
                    "archive": record.archive_name,
                    "member_count": member_count,
                    "checksum": record.checksum,
                    "note": "Dry-run restore — no files extracted",
                }
            except (tarfile.TarError, OSError) as exc:
                return {
                    "status": "ERROR",
                    "error": f"Archive verification failed: {exc}",
                    "backup_id": backup_id,
                }

        # Actual restore (only with explicit dry_run=False)
        try:
            with tarfile.open(archive_path, "r:gz") as tar:
                tar.extractall(path=self.data_root)
            _logger.warning(
                "Backup RESTORED: %s to %s", record.archive_name, self.data_root,
            )
            return {
                "status": "RESTORED",
                "backup_id": backup_id,
                "archive": record.archive_name,
                "destination": str(self.data_root),
            }
        except (tarfile.TarError, OSError) as exc:
            return {
                "status": "ERROR",
                "error": f"Restore failed: {exc}",
                "backup_id": backup_id,
            }

    def verify_checksum(self, backup_id: str) -> bool:
        """Verify backup archive checksum."""
        record = self._load_record(backup_id)
        if record is None or not record.checksum:
            return False

        archive_path = self.backup_dir / record.archive_name
        if not archive_path.exists():
            return False

        try:
            actual_hash = hashlib.sha256(archive_path.read_bytes()).hexdigest()
            return actual_hash == record.checksum
        except OSError:
            return False

    def list_backups(self) -> list[BackupRecord]:
        """List all backup records."""
        if not self.backup_dir.exists():
            return []
        records: list[BackupRecord] = []
        for path in sorted(self.backup_dir.glob("backup_record_*.json")):
            try:
                data = json.loads(path.read_text())
                records.append(BackupRecord(**data))
            except (json.JSONDecodeError, OSError):
                continue
        return records

    def _is_excluded(self, path: Path) -> bool:
        """Check if a file should be excluded from backup."""
        # Check suffix
        if path.suffix in EXCLUDED_SUFFIXES:
            return True

        # Check if any parent directory is excluded
        for parent in path.parents:
            if parent.name in EXCLUDED_NAMES:
                return True

        # Check name against exclusion patterns
        name_lower = path.name.lower()
        for pattern in EXCLUDED_PATTERNS:
            if pattern.startswith("*") and pattern.endswith("*"):
                mid = pattern[1:-1]
                if mid in name_lower:
                    return True
            elif pattern.endswith("*"):
                prefix = pattern[:-1]
                if name_lower.startswith(prefix):
                    return True
            elif pattern.startswith("*"):
                suffix = pattern[1:]
                if name_lower.endswith(suffix):
                    return True
            elif name_lower == pattern:
                return True

        return False

    def _build_archive(self, archive_path: Path, files: list[Path]) -> str:
        """Build a tar.gz archive and return its SHA256 checksum."""
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            for fpath in files:
                arcname = str(fpath.relative_to(self.data_root))
                tar.add(str(fpath), arcname=arcname)

        archive_bytes = buf.getvalue()
        archive_path.write_bytes(archive_bytes)

        checksum = hashlib.sha256(archive_bytes).hexdigest()
        return checksum

    def _save_record(self, record: BackupRecord) -> None:
        path = self.backup_dir / f"backup_record_{record.backup_id}.json"
        path.write_text(json.dumps(record.to_dict(), indent=2, default=str))

    def _load_record(self, backup_id: str) -> BackupRecord | None:
        path = self.backup_dir / f"backup_record_{backup_id}.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text())
            return BackupRecord(**data)
        except (json.JSONDecodeError, OSError):
            return None

    def load(self, backup_id: str) -> BackupRecord | None:
        """Load a backup record by ID. Alias for CLI convenience."""
        return self._load_record(backup_id)
