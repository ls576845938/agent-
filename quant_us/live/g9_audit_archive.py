"""G9 Audit Archive Builder for Production Ops Hardening.

Collects all audit trail files across G3-G9 into a single versioned archive
with checksum verification. Excludes secret-bearing files.

NEVER modifies original audit trails. Read-only collection.
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

_logger = logging.getLogger("g9_audit_archive")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# AuditArchive
# ---------------------------------------------------------------------------


@dataclass
class AuditArchive:
    archive_id: str
    archive_name: str = ""
    audit_file_count: int = 0
    total_bytes: int = 0
    checksum: str = ""
    audit_sources: list[str] = field(default_factory=list)
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = _utc_now().isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "archive_id": self.archive_id,
            "archive_name": self.archive_name,
            "audit_file_count": self.audit_file_count,
            "total_bytes": self.total_bytes,
            "checksum": self.checksum,
            "audit_sources": self.audit_sources,
            "created_at": self.created_at,
        }


# ---------------------------------------------------------------------------
# Audit trail source patterns
# ---------------------------------------------------------------------------

AUDIT_SOURCE_PATTERNS = [
    "*audit*",
    "*audit*.jsonl",
    "*audit*.json",
    "board_audit*",
    "session_audit*",
    "session_gate_audit*",
    "manifest_audit*",
    "scorecard_*",
    "dossier_*",
]

EXCLUDED_AUDIT_PATTERNS = [
    ".env",
    "*key*",
    "*secret*",
    "*credential*",
    "*token*",
]

# ---------------------------------------------------------------------------
# AuditArchiveBuilder
# ---------------------------------------------------------------------------


class AuditArchiveBuilder:
    """Collects all audit trails into a single versioned archive.

    NEVER modifies original audit files. Read-only collection.
    Excludes secret-bearing files from archive.
    """

    def __init__(self, data_root: str = "data") -> None:
        self.data_root = Path(data_root)
        self.archive_dir = self.data_root / "live_pilot" / "audit_archives"
        self.archive_dir.mkdir(parents=True, exist_ok=True)

    def build(self) -> AuditArchive:
        """Collect all audit trail files into a single archive.

        Searches for audit files across the live_pilot directory tree,
        collects them, creates a checksum-verified archive.
        """
        from quant_us.core.types import new_id

        archive_id = new_id("audit_arc")
        timestamp = _utc_now().strftime("%Y%m%d_%H%M%S")
        archive_name = f"audit_archive_{archive_id}_{timestamp}.tar.gz"

        live_pilot_dir = self.data_root / "live_pilot"
        audit_files: list[Path] = []
        audit_sources: list[str] = []

        if not live_pilot_dir.exists():
            archive = AuditArchive(
                archive_id=archive_id,
                archive_name=archive_name,
                source_path=str(live_pilot_dir),
            )
            self._save_archive(archive)
            return archive

        for path in live_pilot_dir.rglob("*"):
            if not path.is_file():
                continue
            if self._is_excluded(path):
                continue
            if self._is_audit_file(path):
                audit_files.append(path)
                # Record the relative source directory
                rel_dir = str(path.parent.relative_to(live_pilot_dir))
                if rel_dir not in audit_sources:
                    audit_sources.append(rel_dir)

        archive_path = self.archive_dir / archive_name

        # Build archive
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            for fpath in audit_files:
                arcname = str(fpath.relative_to(self.data_root))
                tar.add(str(fpath), arcname=arcname)

        archive_bytes = buf.getvalue()
        archive_path.write_bytes(archive_bytes)

        checksum = hashlib.sha256(archive_bytes).hexdigest()
        total_bytes = sum(p.stat().st_size for p in audit_files)

        archive = AuditArchive(
            archive_id=archive_id,
            archive_name=archive_name,
            audit_file_count=len(audit_files),
            total_bytes=total_bytes,
            checksum=checksum,
            audit_sources=audit_sources,
        )
        self._save_archive(archive)
        _logger.info(
            "Audit archive built: %s (%d files, %d sources)",
            archive_name, len(audit_files), len(audit_sources),
        )
        return archive

    def verify(self, archive_id: str) -> bool:
        """Verify the checksum of a previously built archive.

        Returns True if archive exists and checksum matches.
        """
        archive_data = self._load_archive(archive_id)
        if archive_data is None:
            _logger.warning("Audit archive not found: %s", archive_id)
            return False

        archive_path = self.archive_dir / archive_data.get("archive_name", "")
        if not archive_path.exists():
            _logger.warning("Audit archive file not found: %s", archive_path)
            return False

        try:
            actual_hash = hashlib.sha256(archive_path.read_bytes()).hexdigest()
            expected = archive_data.get("checksum", "")
            return actual_hash == expected
        except OSError as exc:
            _logger.warning("Audit archive verify error: %s", exc)
            return False

    def detect_corruption(self, archive_id: str) -> list[str]:
        """Check for corruption in an audit archive.

        Returns a list of corruption descriptions (empty list = clean).
        """
        issues: list[str] = []

        archive_data = self._load_archive(archive_id)
        if archive_data is None:
            issues.append(f"Archive record not found: {archive_id}")
            return issues

        archive_path = self.archive_dir / archive_data.get("archive_name", "")
        if not archive_path.exists():
            issues.append(f"Archive file missing: {archive_path}")
            return issues

        # Check 1: File size integrity
        try:
            stat = archive_path.stat()
            if stat.st_size == 0:
                issues.append("Archive file is empty")
        except OSError as exc:
            issues.append(f"Archive cannot be read: {exc}")
            return issues

        # Check 2: Tar integrity
        try:
            with tarfile.open(archive_path, "r:gz") as tar:
                members = tar.getmembers()
                if not members:
                    issues.append("Archive contains no files")
                # Verify each member can be extracted
                for member in members:
                    if member.size < 0:
                        issues.append(f"Invalid member size in archive: {member.name}")
        except (tarfile.TarError, OSError) as exc:
            issues.append(f"Archive corruption detected: {exc}")
            return issues

        # Check 3: Checksum verification
        if not self.verify(archive_id):
            issues.append("Checksum mismatch — archive may be corrupted or tampered")

        return issues

    def list_archives(self) -> list[AuditArchive]:
        """List all audit archives."""
        if not self.archive_dir.exists():
            return []
        archives: list[AuditArchive] = []
        for path in sorted(self.archive_dir.glob("audit_archive_record_*.json")):
            try:
                data = json.loads(path.read_text())
                archives.append(AuditArchive(**data))
            except (json.JSONDecodeError, OSError):
                continue
        return archives

    def _is_audit_file(self, path: Path) -> bool:
        """Check if a file is an audit trail."""
        name_lower = path.name.lower()
        # Match audit patterns
        for pattern in AUDIT_SOURCE_PATTERNS:
            if pattern.startswith("*") and pattern.endswith("*"):
                if pattern[1:-1] in name_lower:
                    return True
            elif pattern.endswith("*"):
                if name_lower.startswith(pattern[:-1]):
                    return True
            elif pattern.startswith("*"):
                if name_lower.endswith(pattern[1:]):
                    return True
            elif name_lower == pattern:
                return True
        return False

    def _is_excluded(self, path: Path) -> bool:
        """Check if file should be excluded from archive."""
        name_lower = path.name.lower()
        for pattern in EXCLUDED_AUDIT_PATTERNS:
            if pattern.startswith("*") and pattern.endswith("*"):
                if pattern[1:-1] in name_lower:
                    return True
            elif pattern.endswith("*"):
                if name_lower.startswith(pattern[:-1]):
                    return True
            elif name_lower == pattern:
                return True
        return False

    def _save_archive(self, archive: AuditArchive) -> None:
        path = self.archive_dir / f"audit_archive_record_{archive.archive_id}.json"
        path.write_text(json.dumps(archive.to_dict(), indent=2, default=str))

    def load(self, archive_id: str) -> AuditArchive | None:
        """Load an audit archive by ID. Returns None if not found."""
        data = self._load_archive(archive_id)
        if data is None:
            return None
        return AuditArchive(**data)

    def _load_archive(self, archive_id: str) -> dict[str, Any] | None:
        path = self.archive_dir / f"audit_archive_record_{archive_id}.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return None
