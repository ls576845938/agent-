"""G7 Strategy Promotion Manifest.

Pinned manifest required before a strategy can enter G8.
Requires explicit human approval. NEVER auto-approves.
Default status is DRAFT.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

_logger = logging.getLogger("g7_manifest")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Strategy Promotion Manifest
# ---------------------------------------------------------------------------


@dataclass
class StrategyPromotionManifest:
    promotion_id: str
    strategy_id: str
    strategy_version: str
    source_episode_id: str
    paper_30d_path: str = ""
    shadow_5d_path: str = ""
    g5_dossier_path: str = ""
    g6_episode_dossier_path: str = ""
    scorecard_path: str = ""
    approved_symbols: list[str] = field(default_factory=list)
    approved_capital_limit: float = 1000.0
    approved_order_limit: int = 3
    approved_session_limit: int = 1
    approved_risk_envelope_id: str = ""
    status: str = "DRAFT"  # DRAFT|PENDING_REVIEW|APPROVED_FOR_G8_REVIEW|REJECTED|EXPIRED
    created_at: str = ""
    approved_at: str = ""
    approved_by: str = ""
    rejection_reason: str = ""
    expires_at: str = ""  # 7 days from approval

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = _utc_now().isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "promotion_id": self.promotion_id,
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "source_episode_id": self.source_episode_id,
            "paper_30d_path": self.paper_30d_path,
            "shadow_5d_path": self.shadow_5d_path,
            "g5_dossier_path": self.g5_dossier_path,
            "g6_episode_dossier_path": self.g6_episode_dossier_path,
            "scorecard_path": self.scorecard_path,
            "approved_symbols": self.approved_symbols,
            "approved_capital_limit": self.approved_capital_limit,
            "approved_order_limit": self.approved_order_limit,
            "approved_session_limit": self.approved_session_limit,
            "approved_risk_envelope_id": self.approved_risk_envelope_id,
            "status": self.status,
            "created_at": self.created_at,
            "approved_at": self.approved_at,
            "approved_by": self.approved_by,
            "rejection_reason": self.rejection_reason,
            "expires_at": self.expires_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StrategyPromotionManifest:
        return cls(
            promotion_id=data.get("promotion_id", ""),
            strategy_id=data.get("strategy_id", ""),
            strategy_version=data.get("strategy_version", ""),
            source_episode_id=data.get("source_episode_id", ""),
            paper_30d_path=data.get("paper_30d_path", ""),
            shadow_5d_path=data.get("shadow_5d_path", ""),
            g5_dossier_path=data.get("g5_dossier_path", ""),
            g6_episode_dossier_path=data.get("g6_episode_dossier_path", ""),
            scorecard_path=data.get("scorecard_path", ""),
            approved_symbols=data.get("approved_symbols", []),
            approved_capital_limit=data.get("approved_capital_limit", 1000.0),
            approved_order_limit=data.get("approved_order_limit", 3),
            approved_session_limit=data.get("approved_session_limit", 1),
            approved_risk_envelope_id=data.get("approved_risk_envelope_id", ""),
            status=data.get("status", "DRAFT"),
            created_at=data.get("created_at", ""),
            approved_at=data.get("approved_at", ""),
            approved_by=data.get("approved_by", ""),
            rejection_reason=data.get("rejection_reason", ""),
            expires_at=data.get("expires_at", ""),
        )


# ---------------------------------------------------------------------------
# Strategy Promotion Manifest Manager
# ---------------------------------------------------------------------------


class StrategyPromotionManifestManager:
    """Manages strategy promotion manifest lifecycle.

    Requires explicit human approval. NEVER auto-approves.
    Default status is DRAFT.
    """

    def __init__(self, data_root: str = "data") -> None:
        self.data_root = Path(data_root)
        self.promotions_dir = self.data_root / "live_pilot" / "promotions"
        self.promotions_dir.mkdir(parents=True, exist_ok=True)

    def create(
        self,
        source_episode_id: str,
        scorecard_path: str,
        strategy_id: str = "",
        strategy_version: str = "1.0.0",
        paper_30d_path: str = "",
        shadow_5d_path: str = "",
        g5_dossier_path: str = "",
        g6_episode_dossier_path: str = "",
        approved_symbols: list[str] | None = None,
        approved_capital_limit: float = 1000.0,
        approved_order_limit: int = 3,
        approved_session_limit: int = 1,
        approved_risk_envelope_id: str = "",
    ) -> StrategyPromotionManifest:
        """Create a new promotion manifest in DRAFT status.

        NEVER auto-approves. Status remains DRAFT until board review.
        """
        promotion_id = f"prom_{_utc_now().strftime('%Y%m%d_%H%M%S')}"

        manifest = StrategyPromotionManifest(
            promotion_id=promotion_id,
            strategy_id=strategy_id,
            strategy_version=strategy_version,
            source_episode_id=source_episode_id,
            paper_30d_path=paper_30d_path,
            shadow_5d_path=shadow_5d_path,
            g5_dossier_path=g5_dossier_path,
            g6_episode_dossier_path=g6_episode_dossier_path,
            scorecard_path=scorecard_path,
            approved_symbols=approved_symbols or [],
            approved_capital_limit=approved_capital_limit,
            approved_order_limit=approved_order_limit,
            approved_session_limit=approved_session_limit,
            approved_risk_envelope_id=approved_risk_envelope_id,
            status="DRAFT",
        )

        self.save(manifest)
        self._audit("CREATE", manifest)
        _logger.info(
            "Promotion manifest created: %s strategy=%s episode=%s",
            promotion_id,
            strategy_id,
            source_episode_id,
        )
        return manifest

    def approve(self, promotion_id: str, approved_by: str) -> StrategyPromotionManifest:
        """Approve manifest for G8 review.

        Requires explicit human name (approved_by). NEVER auto-approves.
        Sets 7-day expiry from approval time.
        """
        if not approved_by:
            raise ValueError("approved_by is required for approval")

        manifest = self.load(promotion_id)
        if manifest is None:
            raise ValueError(f"Promotion manifest not found: {promotion_id}")

        if manifest.status == "EXPIRED":
            raise ValueError(f"Cannot approve expired manifest: {promotion_id}")

        if manifest.status == "REJECTED":
            raise ValueError(
                f"Cannot approve rejected manifest: {promotion_id}"
            )

        manifest.status = "APPROVED_FOR_G8_REVIEW"
        manifest.approved_by = approved_by
        manifest.approved_at = _utc_now().isoformat()
        manifest.expires_at = (_utc_now() + timedelta(days=7)).isoformat()

        self.save(manifest)
        self._audit(
            "APPROVE",
            manifest,
            extra={
                "approved_by": approved_by,
                "approved_at": manifest.approved_at,
            },
        )
        _logger.info(
            "Promotion manifest APPROVED: %s by %s (expires %s)",
            promotion_id,
            approved_by,
            manifest.expires_at,
        )
        return manifest

    def reject(self, promotion_id: str, reason: str) -> StrategyPromotionManifest:
        """Reject manifest with a reason."""
        if not reason:
            raise ValueError("rejection reason is required")

        manifest = self.load(promotion_id)
        if manifest is None:
            raise ValueError(f"Promotion manifest not found: {promotion_id}")

        manifest.status = "REJECTED"
        manifest.rejection_reason = reason

        self.save(manifest)
        self._audit("REJECT", manifest, extra={"reason": reason})
        _logger.warning(
            "Promotion manifest REJECTED: %s reason=%s",
            promotion_id,
            reason,
        )
        return manifest

    def is_valid_for_g8(self, promotion_id: str) -> tuple[bool, str]:
        """Check if manifest is valid for G8 entry.

        Checks:
        - manifest exists and status is APPROVED_FOR_G8_REVIEW
        - not expired (7 day TTL)
        - all evidence paths exist (paper_30d, shadow_5d, g5_dossier,
          g6_dossier, scorecard)
        - approved risk envelope exists (if specified)
        """
        manifest = self.load(promotion_id)
        if manifest is None:
            return False, f"Manifest not found: {promotion_id}"

        if manifest.status != "APPROVED_FOR_G8_REVIEW":
            return (
                False,
                f"Manifest status is {manifest.status}, "
                f"expected APPROVED_FOR_G8_REVIEW",
            )

        # Check expiry
        if manifest.expires_at:
            try:
                expires = datetime.fromisoformat(manifest.expires_at)
                if _utc_now() > expires:
                    return False, (
                        f"Manifest expired at {manifest.expires_at[:19]}"
                    )
            except (ValueError, TypeError):
                return False, f"Invalid expires_at: {manifest.expires_at}"

        # Check evidence paths
        evidence_paths = {
            "paper_30d": manifest.paper_30d_path,
            "shadow_5d": manifest.shadow_5d_path,
            "g5_dossier": manifest.g5_dossier_path,
            "g6_dossier": manifest.g6_episode_dossier_path,
            "scorecard": manifest.scorecard_path,
        }
        for label, path_str in evidence_paths.items():
            if not path_str:
                return False, f"Missing {label} evidence path"
            if not Path(path_str).exists():
                return False, f"{label} path does not exist: {path_str}"

        # Check risk envelope (optional - only check if specified)
        if manifest.approved_risk_envelope_id:
            env_path = (
                self.data_root
                / "live_pilot"
                / "envelopes"
                / f"{manifest.approved_risk_envelope_id}.json"
            )
            if not env_path.exists():
                return (
                    False,
                    f"Approved risk envelope not found: "
                    f"{manifest.approved_risk_envelope_id}",
                )

        return True, "Valid for G8"

    def load(self, promotion_id: str) -> StrategyPromotionManifest | None:
        """Load a promotion manifest by ID."""
        path = self._path(promotion_id)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text())
            return StrategyPromotionManifest.from_dict(data)
        except (json.JSONDecodeError, OSError):
            return None

    def save(self, manifest: StrategyPromotionManifest) -> str:
        """Save manifest to promotions directory."""
        path = self._path(manifest.promotion_id)
        path.write_text(
            json.dumps(manifest.to_dict(), indent=2, default=str)
        )
        _logger.info(
            "Manifest saved: %s status=%s",
            manifest.promotion_id,
            manifest.status,
        )
        return str(path)

    def set_pending_review(self, promotion_id: str) -> StrategyPromotionManifest:
        """Move manifest from DRAFT to PENDING_REVIEW status."""
        manifest = self.load(promotion_id)
        if manifest is None:
            raise ValueError(f"Promotion manifest not found: {promotion_id}")
        if manifest.status != "DRAFT":
            raise ValueError(
                f"Cannot set pending review: manifest status is {manifest.status}"
            )
        manifest.status = "PENDING_REVIEW"
        self.save(manifest)
        self._audit("SET_PENDING_REVIEW", manifest)
        _logger.info("Manifest set to PENDING_REVIEW: %s", promotion_id)
        return manifest

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _path(self, promotion_id: str) -> Path:
        return self.promotions_dir / f"{promotion_id}.json"

    def _audit(
        self,
        action: str,
        manifest: StrategyPromotionManifest,
        extra: dict[str, Any] | None = None,
    ) -> None:
        """Write to promotion audit trail."""
        audit_path = self.promotions_dir / "promotion_audit.jsonl"
        entry: dict[str, Any] = {
            "timestamp": _utc_now().isoformat(),
            "action": action,
            "promotion_id": manifest.promotion_id,
            "status": manifest.status,
        }
        if extra:
            entry.update(extra)
        with open(audit_path, "a") as f:
            f.write(json.dumps(entry, default=str) + "\n")
