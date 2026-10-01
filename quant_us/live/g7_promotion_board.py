"""G7 Promotion Board for human governance review.

Human governance board that reviews scorecards and makes promotion decisions.
NEVER auto-approves. All decisions require explicit board member name.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_logger = logging.getLogger("g7_promotion_board")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


# Valid board decision strings
BOARD_DECISIONS = frozenset({
    "APPROVED_FOR_G8_REVIEW",
    "REJECTED",
    "MORE_EVIDENCE_REQUIRED",
})


# ---------------------------------------------------------------------------
# Board Decision
# ---------------------------------------------------------------------------


@dataclass
class BoardDecision:
    decision_id: str
    promotion_id: str
    episode_id: str
    board_member: str
    decision: str  # APPROVED_FOR_G8_REVIEW|REJECTED|MORE_EVIDENCE_REQUIRED
    reason: str
    conditions: list[str] = field(default_factory=list)
    decided_at: str = ""

    def __post_init__(self) -> None:
        if not self.decided_at:
            self.decided_at = _utc_now().isoformat()
        if not self.decision_id:
            self.decision_id = (
                f"bd_{_utc_now().strftime('%Y%m%d_%H%M%S')}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "promotion_id": self.promotion_id,
            "episode_id": self.episode_id,
            "board_member": self.board_member,
            "decision": self.decision,
            "reason": self.reason,
            "conditions": self.conditions,
            "decided_at": self.decided_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BoardDecision:
        return cls(
            decision_id=data.get("decision_id", ""),
            promotion_id=data.get("promotion_id", ""),
            episode_id=data.get("episode_id", ""),
            board_member=data.get("board_member", ""),
            decision=data.get("decision", ""),
            reason=data.get("reason", ""),
            conditions=data.get("conditions", []),
            decided_at=data.get("decided_at", ""),
        )


# ---------------------------------------------------------------------------
# Promotion Board
# ---------------------------------------------------------------------------


class PromotionBoard:
    """Human governance board for promotion review.

    Requires:
    - board_member (name)
    - explicit decision string
    - reason

    NEVER auto-approves. Writes audit trail.
    """

    VALID_DECISIONS = BOARD_DECISIONS

    def __init__(self, data_root: str = "data") -> None:
        self.data_root = Path(data_root)
        self.promotions_dir = self.data_root / "live_pilot" / "promotions"
        self.board_dir = self.promotions_dir / "board_decisions"
        self.board_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Review
    # ------------------------------------------------------------------

    def review(
        self,
        promotion_id: str,
        board_member: str,
        decision: str,
        reason: str,
        conditions: list[str] | None = None,
    ) -> BoardDecision:
        """Human board member reviews a promotion.

        Requires explicit board member name, decision, and reason.
        NEVER auto-approves.
        Writes audit trail.

        The manifest status is updated automatically:
        - APPROVED_FOR_G8_REVIEW -> manifest.approve()
        - REJECTED -> manifest.reject()
        - MORE_EVIDENCE_REQUIRED -> manifest remains PENDING_REVIEW
        """
        # Input validation
        if not board_member or not board_member.strip():
            raise ValueError("board_member is required for review")
        if not decision:
            raise ValueError("decision is required for review")
        if decision not in BOARD_DECISIONS:
            raise ValueError(
                f"Invalid decision: {decision}. "
                f"Must be one of {sorted(BOARD_DECISIONS)}"
            )
        if not reason or not reason.strip():
            raise ValueError("reason is required for review")

        board_member = board_member.strip()

        # Load manifest to get episode_id
        from quant_us.live.g7_manifest import (
            StrategyPromotionManifestManager,
        )

        mgr = StrategyPromotionManifestManager(
            data_root=str(self.data_root)
        )
        manifest = mgr.load(promotion_id)
        if manifest is None:
            raise ValueError(
                f"Promotion manifest not found: {promotion_id}"
            )

        # Create board decision record
        board_decision = BoardDecision(
            decision_id="",
            promotion_id=promotion_id,
            episode_id=manifest.source_episode_id,
            board_member=board_member,
            decision=decision,
            reason=reason,
            conditions=conditions or [],
        )

        # Save decision
        self._save_decision(board_decision)

        # Update manifest status based on decision
        if decision == "APPROVED_FOR_G8_REVIEW":
            mgr.approve(promotion_id, approved_by=board_member)
        elif decision == "REJECTED":
            mgr.reject(promotion_id, reason=reason)
        elif decision == "MORE_EVIDENCE_REQUIRED":
            # Keep manifest in PENDING_REVIEW
            if manifest.status == "PENDING_REVIEW":
                self._audit("MORE_EVIDENCE_REQUIRED", board_decision)

        # Audit
        self._audit("REVIEW", board_decision)

        _logger.info(
            "Board review: promotion=%s member=%s decision=%s",
            promotion_id,
            board_member,
            decision,
        )
        return board_decision

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def list_pending(self) -> list[dict[str, Any]]:
        """List all manifests in PENDING_REVIEW status."""
        from quant_us.live.g7_manifest import (
            StrategyPromotionManifestManager,
        )

        mgr = StrategyPromotionManifestManager(
            data_root=str(self.data_root)
        )

        pending: list[dict[str, Any]] = []
        for path in sorted(self.promotions_dir.glob("prom_*.json")):
            try:
                manifest = mgr.load(path.stem)
                if manifest and manifest.status == "PENDING_REVIEW":
                    pending.append(manifest.to_dict())
            except Exception:
                continue

        return pending

    def inspect(self, promotion_id: str) -> dict[str, Any]:
        """Full inspection of promotion evidence.

        Returns manifest details, evidence file status, and board decisions.
        """
        from quant_us.live.g7_manifest import (
            StrategyPromotionManifestManager,
        )

        mgr = StrategyPromotionManifestManager(
            data_root=str(self.data_root)
        )
        manifest = mgr.load(promotion_id)
        if manifest is None:
            return {
                "error": (
                    f"Promotion manifest not found: {promotion_id}"
                )
            }

        result: dict[str, Any] = {
            "manifest": manifest.to_dict(),
            "evidence_files": {},
            "board_decisions": [],
        }

        # Check each evidence file
        evidence_fields = {
            "paper_30d": manifest.paper_30d_path,
            "shadow_5d": manifest.shadow_5d_path,
            "g5_dossier": manifest.g5_dossier_path,
            "g6_dossier": manifest.g6_episode_dossier_path,
            "scorecard": manifest.scorecard_path,
        }
        for label, path_str in evidence_fields.items():
            result["evidence_files"][label] = {
                "path": path_str,
                "exists": Path(path_str).exists() if path_str else False,
            }

        # Load board decisions for this promotion
        for path in sorted(self.board_dir.glob("*.json")):
            try:
                data = json.loads(path.read_text())
                if data.get("promotion_id") == promotion_id:
                    result["board_decisions"].append(data)
            except Exception:
                continue

        return result

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _save_decision(self, decision: BoardDecision) -> None:
        """Save board decision to JSON."""
        path = self.board_dir / f"{decision.decision_id}.json"
        path.write_text(
            json.dumps(decision.to_dict(), indent=2, default=str)
        )

    def load_decision(self, decision_id: str) -> BoardDecision | None:
        """Load a board decision by ID."""
        path = self.board_dir / f"{decision_id}.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text())
            return BoardDecision.from_dict(data)
        except (json.JSONDecodeError, OSError):
            return None

    def _audit(self, action: str, decision: BoardDecision) -> None:
        """Write to promotion audit trail."""
        audit_path = self.promotions_dir / "promotion_audit.jsonl"
        entry: dict[str, Any] = {
            "timestamp": _utc_now().isoformat(),
            "action": action,
            "promotion_id": decision.promotion_id,
            "decision_id": decision.decision_id,
            "board_member": decision.board_member,
            "decision": decision.decision,
            "reason": decision.reason,
        }
        with open(audit_path, "a") as f:
            f.write(json.dumps(entry, default=str) + "\n")
