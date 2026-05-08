"""G9 Deployment Readiness Check for Production Ops Hardening.

Final checklist before any deployment can be considered ready.
All checks must pass for READY status.

NEVER triggers deployment. NEVER calls submit_order.
Returns a readiness report only.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from quant_us.live.g9_release_manifest import ReleaseManifestManager
from quant_us.live.g9_config_check import ConfigIntegrityChecker

_logger = logging.getLogger("g9_readiness")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Readiness status constants
# ---------------------------------------------------------------------------


class ReadinessStatus:
    READY = "READY"
    BLOCKED = "BLOCKED"
    PENDING = "PENDING"


# ---------------------------------------------------------------------------
# DeploymentReadinessCheck
# ---------------------------------------------------------------------------


@dataclass
class DeploymentReadinessCheck:
    check_id: str
    status: str = ReadinessStatus.PENDING
    release_exists: bool = False
    release_approved: bool = False
    config_integrity_passed: bool = False
    config_drift_detected: bool = False
    release_manifest_consistent: bool = False
    backup_available: bool = False
    audit_archive_exists: bool = False
    block_reasons: list[str] = field(default_factory=list)
    checked_at: str = ""

    def __post_init__(self) -> None:
        if not self.checked_at:
            self.checked_at = _utc_now().isoformat()

    @property
    def is_ready(self) -> bool:
        return self.status == ReadinessStatus.READY

    def to_dict(self) -> dict[str, Any]:
        return {
            "check_id": self.check_id,
            "status": self.status,
            "release_exists": self.release_exists,
            "release_approved": self.release_approved,
            "config_integrity_passed": self.config_integrity_passed,
            "config_drift_detected": self.config_drift_detected,
            "release_manifest_consistent": self.release_manifest_consistent,
            "backup_available": self.backup_available,
            "audit_archive_exists": self.audit_archive_exists,
            "block_reasons": self.block_reasons,
            "checked_at": self.checked_at,
        }


# ---------------------------------------------------------------------------
# ReadinessChecker
# ---------------------------------------------------------------------------


class ReadinessChecker:
    """Runs deployment readiness checks.

    NEVER triggers deployment. NEVER calls submit_order.
    All checks are read-only.
    """

    def __init__(self, data_root: str = "data") -> None:
        self.data_root = Path(data_root)
        self.release_mgr = ReleaseManifestManager(data_root=data_root)
        self.config_checker = ConfigIntegrityChecker(data_root=data_root)
        self.check_dir = self.data_root / "live_pilot" / "readiness"
        self.check_dir.mkdir(parents=True, exist_ok=True)

    def check(self) -> DeploymentReadinessCheck:
        """Run all deployment readiness checks.

        Returns a DeploymentReadinessCheck with all results.
        NEVER triggers any deployment action.
        """
        from quant_us.core.types import new_id

        readiness = DeploymentReadinessCheck(
            check_id=new_id("readiness"),
        )

        block_reasons: list[str] = []

        # Check 1: Release exists
        releases = self.release_mgr.list_releases()
        if not releases:
            block_reasons.append("no_release_found")
        else:
            readiness.release_exists = True
            latest = releases[-1]

            # Check 2: Release is APPROVED
            if latest.status == "APPROVED":
                readiness.release_approved = True
            else:
                block_reasons.append(f"release_not_approved:{latest.status}")

            # Check 3: Release manifest consistency
            release_consistent = (
                bool(latest.config_hash)
                and bool(latest.approved_by)
            )
            readiness.release_manifest_consistent = release_consistent
            if not release_consistent:
                block_reasons.append("release_manifest_incomplete")

        # Check 4: Config integrity
        config_result = self.config_checker.check()
        readiness.config_integrity_passed = config_result.passed

        # Check 5: Config drift
        if config_result.drift_detected:
            readiness.config_drift_detected = True
            block_reasons.append(f"config_drift:{config_result.drift_detected[0]}")

        # Check 6: Backup available
        backup_dir = self.data_root / "live_pilot" / "backups"
        readiness.backup_available = backup_dir.exists() and any(
            backup_dir.glob("backup_record_*.json")
        )
        if not readiness.backup_available:
            block_reasons.append("no_backup_available")

        # Check 7: Audit archive exists
        archive_dir = self.data_root / "live_pilot" / "audit_archives"
        readiness.audit_archive_exists = archive_dir.exists() and any(
            archive_dir.glob("audit_archive_record_*.json")
        )
        if not readiness.audit_archive_exists:
            block_reasons.append("no_audit_archive")

        # Determine final status
        if block_reasons:
            readiness.status = ReadinessStatus.BLOCKED
            readiness.block_reasons = block_reasons
        else:
            readiness.status = ReadinessStatus.READY

        self._save(readiness)
        _logger.info(
            "Deployment readiness check: %s status=%s",
            readiness.check_id, readiness.status,
        )
        return readiness

    def load(self, check_id: str) -> DeploymentReadinessCheck | None:
        """Load a previous readiness check."""
        path = self._check_path(check_id)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text())
            return DeploymentReadinessCheck(**data)
        except (json.JSONDecodeError, OSError):
            return None

    def _check_path(self, check_id: str) -> Path:
        return self.check_dir / f"{check_id}.json"

    def _save(self, readiness: DeploymentReadinessCheck) -> None:
        path = self._check_path(readiness.check_id)
        path.write_text(json.dumps(readiness.to_dict(), indent=2, default=str))
