"""G9 Release Manifest for Production Ops Hardening.

Captures a point-in-time snapshot of all configuration, strategy versions,
and approval artifacts that comprise a deployable release.

NEVER auto-approves. NEVER triggers deployment.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_logger = logging.getLogger("g9_release_manifest")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Release status constants
# ---------------------------------------------------------------------------

VALID_RELEASE_STATUSES = frozenset({
    "DRAFT",
    "CANDIDATE",
    "APPROVED",
    "REJECTED",
    "ROLLED_BACK",
})


# ---------------------------------------------------------------------------
# ReleaseManifest
# ---------------------------------------------------------------------------


@dataclass
class ReleaseManifest:
    release_id: str
    git_commit: str = ""
    strategy_versions: dict[str, str] = field(default_factory=dict)
    config_hash: str = ""
    risk_envelope_hash: str = ""
    promotion_manifest_ids: list[str] = field(default_factory=list)
    session_report_ids: list[str] = field(default_factory=list)
    test_result_path: str = ""
    docs_version: str = ""
    created_at: str = ""
    approved_by: str = ""
    approved_at: str = ""
    status: str = "DRAFT"

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = _utc_now().isoformat()
        if self.status not in VALID_RELEASE_STATUSES:
            self.status = "DRAFT"

    def to_dict(self) -> dict[str, Any]:
        return {
            "release_id": self.release_id,
            "git_commit": self.git_commit,
            "strategy_versions": self.strategy_versions,
            "config_hash": self.config_hash,
            "risk_envelope_hash": self.risk_envelope_hash,
            "promotion_manifest_ids": self.promotion_manifest_ids,
            "session_report_ids": self.session_report_ids,
            "test_result_path": self.test_result_path,
            "docs_version": self.docs_version,
            "created_at": self.created_at,
            "approved_by": self.approved_by,
            "approved_at": self.approved_at,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ReleaseManifest":
        return cls(
            release_id=data.get("release_id", ""),
            git_commit=data.get("git_commit", ""),
            strategy_versions=data.get("strategy_versions", {}),
            config_hash=data.get("config_hash", ""),
            risk_envelope_hash=data.get("risk_envelope_hash", ""),
            promotion_manifest_ids=data.get("promotion_manifest_ids", []),
            session_report_ids=data.get("session_report_ids", []),
            test_result_path=data.get("test_result_path", ""),
            docs_version=data.get("docs_version", ""),
            created_at=data.get("created_at", ""),
            approved_by=data.get("approved_by", ""),
            approved_at=data.get("approved_at", ""),
            status=data.get("status", "DRAFT"),
        )


# ---------------------------------------------------------------------------
# ReleaseManifestManager
# ---------------------------------------------------------------------------


class ReleaseManifestManager:
    """Manages release manifest lifecycle.

    Storage: data/live_pilot/releases/{release_id}.json
    """

    def __init__(self, data_root: str = "data") -> None:
        self.release_dir = Path(data_root) / "live_pilot" / "releases"
        self.release_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    def create(
        self,
        promotion_ids: list[str] | None = None,
        session_report_ids: list[str] | None = None,
    ) -> ReleaseManifest:
        """Create a new release manifest.

        Computes config_hash and risk_envelope_hash automatically.
        Does NOT auto-approve. Status is always DRAFT on creation.
        """
        from quant_us.core.types import new_id

        release_id = new_id("rel")

        manifest = ReleaseManifest(
            release_id=release_id,
            promotion_manifest_ids=promotion_ids or [],
            session_report_ids=session_report_ids or [],
        )

        # Compute config hash from current runtime config
        manifest.config_hash = self.compute_config_hash()

        # Compute risk envelope hash
        manifest.risk_envelope_hash = self._compute_risk_envelope_hash()

        # Try to read git commit
        manifest.git_commit = self._get_git_commit()

        self._save(manifest)
        _logger.info("Release manifest created: %s (DRAFT)", release_id)
        return manifest

    # ------------------------------------------------------------------
    # Approve / Reject / Rollback
    # ------------------------------------------------------------------

    def approve(self, release_id: str, approved_by: str) -> ReleaseManifest:
        """Human approval of a release manifest.

        NEVER auto-approves. NEVER triggers deployment.
        """
        manifest = self._require_load(release_id)
        if manifest.status not in ("DRAFT", "CANDIDATE"):
            raise ValueError(
                f"Cannot approve release {release_id}: current status is {manifest.status}"
            )
        if not approved_by:
            raise ValueError("approve() requires a non-empty approver name")

        manifest.status = "APPROVED"
        manifest.approved_by = approved_by
        manifest.approved_at = _utc_now().isoformat()
        self._save(manifest)
        _logger.info(
            "Release APPROVED: %s by %s (still no deployment triggered)",
            release_id, approved_by,
        )
        return manifest

    def reject(self, release_id: str, reason: str) -> ReleaseManifest:
        """Reject a release manifest."""
        manifest = self._require_load(release_id)
        if manifest.status == "ROLLED_BACK":
            raise ValueError(
                f"Cannot reject release {release_id}: already ROLLED_BACK"
            )
        manifest.status = "REJECTED"
        self._save(manifest)
        _logger.info("Release REJECTED: %s reason=%s", release_id, reason)
        return manifest

    def rollback(self, release_id: str, reason: str) -> ReleaseManifest:
        """Mark release as ROLLED_BACK.

        Does NOT execute any code changes. Only records the decision.
        """
        manifest = self._require_load(release_id)
        if manifest.status == "ROLLED_BACK":
            raise ValueError(f"Release {release_id} is already ROLLED_BACK")
        manifest.status = "ROLLED_BACK"
        self._save(manifest)
        _logger.info("Release ROLLED_BACK: %s reason=%s", release_id, reason)
        return manifest

    # ------------------------------------------------------------------
    # Hashing
    # ------------------------------------------------------------------

    def compute_config_hash(self) -> str:
        """Hash current config files (risk envelope, strategy versions, runtime config).

        Explicitly excludes any secret-bearing files.
        """
        hasher = hashlib.sha256()
        config_files: list[str] = []

        # Runtime config
        runtime_cfg = self.release_dir.parent / "runtime_config.json"
        if runtime_cfg.exists():
            config_files.append(str(runtime_cfg))

        # Strategy config
        strategy_cfg = self.release_dir.parent / "strategy_config.json"
        if strategy_cfg.exists():
            config_files.append(str(strategy_cfg))

        # Risk envelope files
        envelope_dir = self.release_dir.parent / "envelopes"
        if envelope_dir.exists():
            config_files.extend(str(p) for p in sorted(envelope_dir.glob("*.json")))

        # Promotion manifests
        promotions_dir = self.release_dir.parent / "promotions"
        if promotions_dir.exists():
            config_files.extend(str(p) for p in sorted(promotions_dir.glob("*.json")))

        for path in sorted(config_files):
            try:
                content = Path(path).read_bytes()
                hasher.update(content)
            except OSError:
                continue

        return hasher.hexdigest()

    def _compute_risk_envelope_hash(self) -> str:
        """Compute hash of all risk envelope files."""
        hasher = hashlib.sha256()
        envelope_dir = self.release_dir.parent / "envelopes"
        if envelope_dir.exists():
            for path in sorted(envelope_dir.glob("*.json")):
                try:
                    hasher.update(path.read_bytes())
                except OSError:
                    continue
        return hasher.hexdigest()

    def _get_git_commit(self) -> str:
        """Try to read current git commit hash."""
        try:
            import subprocess
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception:
            pass
        return ""

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def load(self, release_id: str) -> ReleaseManifest | None:
        path = self._release_path(release_id)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text())
            return ReleaseManifest.from_dict(data)
        except (json.JSONDecodeError, OSError) as exc:
            _logger.warning("Failed to load release %s: %s", release_id, exc)
            return None

    def list_releases(self) -> list[ReleaseManifest]:
        manifests: list[ReleaseManifest] = []
        for path in sorted(self.release_dir.glob("*.json"), reverse=True):
            try:
                data = json.loads(path.read_text())
                manifests.append(ReleaseManifest.from_dict(data))
            except (json.JSONDecodeError, OSError):
                continue
        return manifests

    def _require_load(self, release_id: str) -> ReleaseManifest:
        manifest = self.load(release_id)
        if manifest is None:
            raise ValueError(f"Release manifest not found: {release_id}")
        return manifest

    def _release_path(self, release_id: str) -> Path:
        return self.release_dir / f"{release_id}.json"

    def _save(self, manifest: ReleaseManifest) -> None:
        path = self._release_path(manifest.release_id)
        path.write_text(json.dumps(manifest.to_dict(), indent=2, default=str))

    # ------------------------------------------------------------------
    # Output
    # ------------------------------------------------------------------

    def to_markdown(self, release: ReleaseManifest) -> str:
        d = release.to_dict()
        lines = [
            "# Release Manifest",
            "",
            f"**Release ID**: `{d['release_id']}`",
            f"**Status**: {d['status']}",
            f"**Created**: {d['created_at'][:19] if d['created_at'] else 'N/A'}",
            "",
            "---",
            "## Configuration",
            f"| Field | Value |",
            f"|-------|-------|",
            f"| Git Commit | `{d['git_commit'][:12] if d['git_commit'] else 'N/A'}` |",
            f"| Config Hash | `{d['config_hash'][:16] if d['config_hash'] else 'N/A'}...` |",
            f"| Risk Envelope Hash | `{d['risk_envelope_hash'][:16] if d['risk_envelope_hash'] else 'N/A'}...` |",
            f"| Test Result Path | {d['test_result_path'] or 'N/A'} |",
            f"| Docs Version | {d['docs_version'] or 'N/A'} |",
            "",
            "## Strategy Versions",
        ]
        if d["strategy_versions"]:
            for sid, ver in d["strategy_versions"].items():
                lines.append(f"- `{sid}`: **{ver}**")
        else:
            lines.append("*No strategy versions recorded.*")

        lines.extend([
            "",
            "## Promotion Manifests",
        ])
        if d["promotion_manifest_ids"]:
            for pid in d["promotion_manifest_ids"]:
                lines.append(f"- `{pid}`")
        else:
            lines.append("*None*")

        lines.extend([
            "",
            "## Session Reports",
        ])
        if d["session_report_ids"]:
            for sid in d["session_report_ids"]:
                lines.append(f"- `{sid}`")
        else:
            lines.append("*None*")

        lines.extend([
            "",
            "---",
        ])
        if d["status"] == "APPROVED":
            lines.extend([
                "## Approval",
                f"- **Approved By**: {d['approved_by']}",
                f"- **Approved At**: {d['approved_at'][:19] if d['approved_at'] else 'N/A'}",
            ])
        elif d["status"] == "REJECTED":
            lines.append("## Rejected")
        elif d["status"] == "ROLLED_BACK":
            lines.append("## Rolled Back")

        lines.append("")
        lines.append("> **Note**: This manifest is a point-in-time record.")
        lines.append("> It does NOT represent a live deployment.")

        return "\n".join(lines)
