from __future__ import annotations

from pathlib import Path
from typing import Any


PAPER_REVIEW_ELIGIBLE_PROMOTION_STATUSES = {
    "READY_FOR_PORTFOLIO_SIM",
    "PAPER_REVIEW_CANDIDATE",
}


def _row_details(row: dict[str, Any]) -> dict[str, Any]:
    details = row.get("details", {})
    return details if isinstance(details, dict) else {}


def _as_str(value: Any) -> str:
    return str(value or "").strip()


def _build_entry_command(data_root: Path, manifest_id: str, candidate_id: str) -> str:
    payload = []
    if manifest_id:
        payload.append(f'"strategy_manifest_id": "{manifest_id}"')
    if candidate_id:
        payload.append(f'"candidate_id": "{candidate_id}"')
    if not payload:
        return ""
    body = ", ".join(payload)
    return f"POST /api/research/paper-review/create {{ {body}, \"data_root\": \"{data_root}\" }}"


def summarize_paper_review_entry(
    *,
    data_root: str | Path,
    registry: dict[str, Any],
    paper_review: dict[str, Any],
    paper_validation_state: str,
    credentials_present: bool,
    base_url_valid: bool,
) -> dict[str, Any]:
    root = Path(data_root)
    evidence = registry.get("evidence", {})
    if not isinstance(evidence, dict):
        evidence = {}

    manifest_rows = [row for row in evidence.get("strategy_manifests", []) if isinstance(row, dict)]
    review_rows = [row for row in evidence.get("paper_reviews", []) if isinstance(row, dict)]

    eligible_manifest_rows: list[dict[str, Any]] = []
    for row in manifest_rows:
        details = _row_details(row)
        manifest_id = _as_str(details.get("strategy_manifest_id") or row.get("strategy_manifest_id") or row.get("evidence_id"))
        candidate_id = _as_str(details.get("source_candidate_id") or row.get("candidate_id"))
        promotion_status = _as_str(details.get("promotion_status") or row.get("summary") or row.get("status"))
        paper_review_candidate_status = _as_str(details.get("paper_review_candidate_status"))
        if promotion_status in PAPER_REVIEW_ELIGIBLE_PROMOTION_STATUSES:
            eligible_manifest_rows.append(
                {
                    "strategy_manifest_id": manifest_id,
                    "source_candidate_id": candidate_id,
                    "promotion_status": promotion_status,
                    "paper_review_candidate_status": paper_review_candidate_status,
                    "paper_review_evidence_pack_path": _as_str(details.get("paper_review_evidence_pack_path")),
                    "paper_review_id": _as_str(details.get("paper_review_id")),
                }
            )

    eligible_manifest_rows = eligible_manifest_rows[:10]
    eligible_manifest_ids = [row["strategy_manifest_id"] for row in eligible_manifest_rows if row["strategy_manifest_id"]]
    eligible_candidate_ids = [row["source_candidate_id"] for row in eligible_manifest_rows if row["source_candidate_id"]]
    preferred_manifest_id = eligible_manifest_ids[0] if eligible_manifest_ids else ""
    preferred_candidate_id = eligible_candidate_ids[0] if eligible_candidate_ids else ""

    why_blocked: list[str] = []
    creation_allowed = True

    registry_state = _as_str(registry.get("registry_status", "missing"))
    registry_integrity = _as_str(registry.get("registry_integrity_status", "MISSING"))
    if registry_state != "present" or registry_integrity != "PASS/STABLE":
        why_blocked.append(f"registry_not_ready:{registry_state}:{registry_integrity}")
        creation_allowed = False

    if paper_validation_state != "PASS":
        why_blocked.append(f"paper_validation_not_ready:{paper_validation_state}")
        creation_allowed = False

    if not eligible_manifest_rows:
        why_blocked.append(
            "no_eligible_manifest: run promotion gate until a manifest reaches READY_FOR_PORTFOLIO_SIM or PAPER_REVIEW_CANDIDATE"
        )
        creation_allowed = False

    latest_review = review_rows[0] if review_rows else None
    if latest_review is not None:
        details = _row_details(latest_review)
        review_status = _as_str(details.get("status") or latest_review.get("summary") or latest_review.get("status"))
        if review_status and review_status not in {"PENDING_HUMAN_REVIEW", "APPROVED_FOR_PAPER_ONLY"}:
            why_blocked.append(f"latest_review_status:{review_status}")

    current_review_status = _as_str(paper_review.get("status", ""))
    if current_review_status and current_review_status not in {"PENDING_HUMAN_REVIEW", "APPROVED_FOR_PAPER_ONLY"}:
        why_blocked.append(f"paper_review_status:{current_review_status}")

    if creation_allowed:
        next_command = _build_entry_command(root, preferred_manifest_id, preferred_candidate_id)
        creation_message = "Eligible manifest found; create paper-review evidence from the canonical promotion result."
    else:
        if registry_state != "present" or registry_integrity != "PASS/STABLE":
            next_command = "Run: quant-us research evidence-registry-rebuild --data-root <data_root>"
        elif paper_validation_state != "PASS":
            next_command = "Complete paper validation evidence before any paper submission gate."
        else:
            next_command = "Run promotion gate until a manifest reaches READY_FOR_PORTFOLIO_SIM, then create paper-review evidence from that manifest."
        creation_message = "Paper-review evidence creation is blocked until an eligible manifest exists and the registry / validation gates are clean."

    return {
        "creation_allowed": creation_allowed,
        "why_blocked": why_blocked,
        "next_command": next_command,
        "eligible_manifest_ids": eligible_manifest_ids,
        "eligible_candidate_ids": eligible_candidate_ids,
        "preferred_manifest_id": preferred_manifest_id,
        "preferred_candidate_id": preferred_candidate_id,
        "create_from_manifest_command": _build_entry_command(root, preferred_manifest_id, ""),
        "create_from_candidate_command": _build_entry_command(root, "", preferred_candidate_id),
        "eligible_manifest_count": len(eligible_manifest_ids),
        "eligible_candidate_count": len(eligible_candidate_ids),
        "summary": creation_message,
        "eligible_manifest_rows": eligible_manifest_rows,
    }
