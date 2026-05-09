from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from quant_us.research.evidence_registry import (
    inspect_evidence_registry,
    rebuild_evidence_registry,
)


@dataclass(frozen=True)
class PaperReviewStatus:
    """Read-only summary of research paper-review evidence."""

    status: str
    paper_review_entry_allowed: bool
    manual_review_pending: bool
    summary: str
    evidence_path: str
    review_path: str = ""
    manifest_path: str = ""
    evidence_pack_path: str = ""


def inspect_paper_review_status(
    data_root: str | Path = "data",
    *,
    use_index: bool = True,
) -> PaperReviewStatus:
    """Inspect persisted registry evidence and summarize paper-review state."""
    registry = inspect_evidence_registry(
        data_root,
        use_saved=use_index,
        rebuild_if_missing=True,
    )
    if registry.get("registry_status") in {"stale", "changed"}:
        registry = inspect_evidence_registry(
            data_root,
            use_saved=False,
            rebuild_if_missing=True,
        )
    reviews = list(registry.get("evidence", {}).get("paper_reviews", []))
    manifests = list(registry.get("evidence", {}).get("strategy_manifests", []))
    latest_review = reviews[0] if reviews else None
    latest_manifest = manifests[0] if manifests else None

    if latest_review is not None:
        integrity_status = str(latest_review.get("integrity_status", "PASS/STABLE"))
        if integrity_status == "CONFLICT":
            review_path = str(latest_review.get("path", ""))
            return PaperReviewStatus(
                status="CONFLICT",
                paper_review_entry_allowed=False,
                manual_review_pending=False,
                summary="Latest paper review evidence is conflicting; resolve duplicate or divergent review artifacts before promotion.",
                evidence_path=review_path,
                review_path=review_path,
                evidence_pack_path=str(latest_review.get("details", {}).get("evidence_pack_path", "") or ""),
            )
        status = str(latest_review.get("details", {}).get("status", latest_review.get("summary", "UNKNOWN")))
        evidence_pack_path = str(latest_review.get("details", {}).get("evidence_pack_path", "") or "")
        approval = latest_review.get("details", {}).get("approval", {})
        reviewer = str(latest_review.get("details", {}).get("reviewer", "") or "")
        reviewed_at = str(latest_review.get("details", {}).get("reviewed_at", "") or "")
        review_path = str(latest_review.get("path", ""))
        if status == "PENDING_HUMAN_REVIEW":
            return PaperReviewStatus(
                status=status,
                paper_review_entry_allowed=True,
                manual_review_pending=True,
                summary="Paper review is in the human queue; manual review is still pending.",
                evidence_path=review_path,
                review_path=review_path,
                evidence_pack_path=evidence_pack_path,
            )
        if status == "APPROVED_FOR_PAPER_ONLY":
            approval_tail = ""
            if isinstance(approval, dict) and approval:
                reviewer = str(approval.get("reviewer", reviewer) or reviewer)
                reviewed_at = str(approval.get("timestamp", reviewed_at) or reviewed_at)
            if reviewer:
                approval_tail = f" Reviewer={reviewer}."
            if reviewed_at:
                approval_tail = f"{approval_tail} Approved_at={reviewed_at}."
            return PaperReviewStatus(
                status=status,
                paper_review_entry_allowed=True,
                manual_review_pending=False,
                summary=(
                    "Human paper review is approved for paper-only consideration; "
                    f"no order path is enabled here.{approval_tail}"
                ).strip(),
                evidence_path=review_path,
                review_path=review_path,
                evidence_pack_path=evidence_pack_path,
            )
        return PaperReviewStatus(
            status=status,
            paper_review_entry_allowed=False,
            manual_review_pending=False,
            summary=f"Latest paper review is {status}; paper-review entry is not currently allowed from this evidence.",
            evidence_path=review_path,
            review_path=review_path,
            evidence_pack_path=evidence_pack_path,
        )

    if latest_manifest is not None:
        integrity_status = str(latest_manifest.get("integrity_status", "PASS/STABLE"))
        manifest_path = str(latest_manifest.get("path", ""))
        if integrity_status == "CONFLICT":
            return PaperReviewStatus(
                status="CONFLICT",
                paper_review_entry_allowed=False,
                manual_review_pending=False,
                summary="Latest strategy manifest evidence is conflicting; paper-review entry is blocked until manifest lineage is resolved.",
                evidence_path=manifest_path,
                manifest_path=manifest_path,
            )
        status = str(
            latest_manifest.get("details", {}).get(
                "promotion_status",
                latest_manifest.get("summary", "UNKNOWN"),
            )
        )
        if status in {"READY_FOR_PORTFOLIO_SIM", "PAPER_REVIEW_CANDIDATE"}:
            return PaperReviewStatus(
                status="ELIGIBLE_FOR_PAPER_REVIEW",
                paper_review_entry_allowed=True,
                manual_review_pending=False,
                summary="Research evidence allows entry into PAPER_REVIEW, but no human review record exists yet.",
                evidence_path=manifest_path,
                manifest_path=manifest_path,
            )
        return PaperReviewStatus(
            status=status,
            paper_review_entry_allowed=False,
            manual_review_pending=False,
            summary=f"Latest strategy manifest status is {status}; no paper-review approval evidence is present.",
            evidence_path=manifest_path,
            manifest_path=manifest_path,
        )

    return PaperReviewStatus(
        status="NO_PAPER_REVIEW_EVIDENCE",
        paper_review_entry_allowed=False,
        manual_review_pending=False,
        summary="No paper-review or manifest evidence was found under the research data root.",
        evidence_path="",
    )


def build_paper_review_evidence_index(
    data_root: str | Path = "data",
    *,
    write: bool = True,
) -> dict[str, Any]:
    """Rebuild the full evidence registry and return the legacy paper-review view."""
    registry = rebuild_evidence_registry(data_root, write=write)
    legacy_index_path = Path(data_root) / "research" / "paper_review_index.json"
    return {
        "schema_version": "paper_review_evidence_index_v2",
        "generated_at": str(registry.get("generated_at", "")),
        "latest_review_path": str(registry.get("latest", {}).get("paper_review_path", "")),
        "latest_manifest_path": str(registry.get("latest", {}).get("strategy_manifest_path", "")),
        "review_count": int(registry.get("counts", {}).get("paper_review_count", 0)),
        "manifest_count": int(registry.get("counts", {}).get("strategy_manifest_count", 0)),
        "registry_path": str(registry.get("registry_path", "")),
        "index_path": str(legacy_index_path),
        "reviews": [
            {
                "path": row.get("path", ""),
                "id": row.get("id", ""),
                "status": row.get("details", {}).get("status", row.get("summary", "")),
                "created_at": row.get("created_at", ""),
            }
            for row in registry.get("evidence", {}).get("paper_reviews", [])
        ],
        "manifests": [
            {
                "path": row.get("path", ""),
                "id": row.get("strategy_candidate_id", row.get("id", "")),
                "status": row.get("details", {}).get("promotion_status", row.get("summary", "")),
                "created_at": row.get("created_at", ""),
            }
            for row in registry.get("evidence", {}).get("strategy_manifests", [])
        ],
    }
