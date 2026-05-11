"""Contracts for portfolio paper-review evidence.

This module defines the minimum persisted evidence required before a
portfolio simulation can enter the human paper-review queue.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


PORTFOLIO_PAPER_REVIEW_EVIDENCE_SCHEMA_VERSION = "portfolio_paper_review_evidence_v2"
PORTFOLIO_PAPER_REVIEW_EVIDENCE_ORIGIN = (
    "quant_us.research.evidence_pack:EvidencePackGenerator.save_portfolio_review_pack"
)
REQUIRED_STRATEGY_MANIFEST_FIELDS = (
    "data_version",
    "sample_window",
    "purge_embargo",
    "trial_id",
    "trial_count",
    "pbo",
    "dsr",
    "cost_model",
    "slippage_model",
    "capacity",
    "turnover",
    "holding_period",
    "exposure_limits",
    "failure_conditions",
    "delisting_conditions",
)


@dataclass(frozen=True)
class PortfolioPaperReviewEvidenceValidation:
    status: str
    blocking_reasons: list[str] = field(default_factory=list)
    strategy_manifest_ids: list[str] = field(default_factory=list)
    portfolio_sim_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "blocking_reasons": list(self.blocking_reasons),
            "strategy_manifest_ids": list(self.strategy_manifest_ids),
            "portfolio_sim_id": self.portfolio_sim_id,
        }


def summarize_strategy_manifest_contract(manifest: dict[str, Any]) -> dict[str, Any]:
    missing_fields: list[str] = []
    for field_name in REQUIRED_STRATEGY_MANIFEST_FIELDS:
        value = manifest.get(field_name)
        if value is None:
            missing_fields.append(field_name)
            continue
        if isinstance(value, str) and not value.strip():
            missing_fields.append(field_name)
        elif isinstance(value, dict) and not value:
            missing_fields.append(field_name)
        elif isinstance(value, list) and field_name != "failure_conditions" and not value:
            missing_fields.append(field_name)
        elif field_name == "trial_count" and int(value or 0) <= 0:
            missing_fields.append(field_name)
    return {
        "required_fields": list(REQUIRED_STRATEGY_MANIFEST_FIELDS),
        "missing_fields": missing_fields,
        "contract_complete": not missing_fields,
        "data_version": str(manifest.get("data_version", "") or ""),
        "trial_id": str(manifest.get("trial_id", "") or ""),
        "trial_count": int(manifest.get("trial_count", 0) or 0),
        "pbo": manifest.get("pbo"),
        "dsr": manifest.get("dsr"),
    }


def build_portfolio_paper_review_evidence_contract(
    *,
    portfolio_sim_id: str,
    strategy_manifest_ids: list[str],
    candidate_sections: list[dict[str, Any]],
) -> dict[str, Any]:
    manifest_statuses = [
        bool(section.get("strategy_manifest_contract_complete", False))
        for section in candidate_sections
    ]
    return {
        "schema_version": PORTFOLIO_PAPER_REVIEW_EVIDENCE_SCHEMA_VERSION,
        "origin": PORTFOLIO_PAPER_REVIEW_EVIDENCE_ORIGIN,
        "portfolio_sim_id": portfolio_sim_id,
        "strategy_manifest_ids": list(strategy_manifest_ids),
        "candidate_count": len(candidate_sections),
        "all_strategy_manifest_contracts_complete": all(manifest_statuses)
        if manifest_statuses
        else False,
        "paper_review_gate": "portfolio_evidence_pack_required",
    }


def validate_portfolio_paper_review_evidence(
    evidence: dict[str, Any],
    *,
    root: str | Path | None = None,
) -> PortfolioPaperReviewEvidenceValidation:
    sections = evidence.get("sections", {})
    contract = evidence.get("evidence_contract", {})
    blockers: list[str] = []

    if evidence.get("paper_review_scope") != "portfolio_sim":
        blockers.append("paper_review_scope_not_portfolio_sim")
    if contract.get("schema_version") != PORTFOLIO_PAPER_REVIEW_EVIDENCE_SCHEMA_VERSION:
        blockers.append("portfolio_evidence_contract_schema_missing")
    if contract.get("origin") != PORTFOLIO_PAPER_REVIEW_EVIDENCE_ORIGIN:
        blockers.append("portfolio_evidence_contract_origin_invalid")

    portfolio_sim = sections.get("portfolio_sim", {})
    portfolio_sim_id = str(
        portfolio_sim.get("portfolio_sim_id", evidence.get("portfolio_sim_id", "")) or ""
    )
    if not portfolio_sim_id:
        blockers.append("portfolio_sim_id_missing")

    strategy_manifest_ids = list(
        evidence.get("strategy_manifest_ids", [])
        or contract.get("strategy_manifest_ids", [])
        or portfolio_sim.get("strategy_manifest_ids", [])
    )
    if not strategy_manifest_ids:
        blockers.append("strategy_manifest_ids_missing")

    portfolio_candidates = sections.get("portfolio_candidates", [])
    if not isinstance(portfolio_candidates, list) or not portfolio_candidates:
        blockers.append("portfolio_candidates_missing")
        portfolio_candidates = []

    for row in portfolio_candidates:
        if not isinstance(row, dict):
            blockers.append("portfolio_candidate_row_invalid")
            continue
        if not row.get("strategy_manifest_id"):
            blockers.append("portfolio_candidate_manifest_id_missing")
        if not row.get("candidate_id"):
            blockers.append("portfolio_candidate_candidate_id_missing")
        if not row.get("evidence_pack_path"):
            blockers.append("candidate_evidence_pack_path_missing")
        contract_summary = row.get("strategy_manifest_contract", {})
        if not row.get("strategy_manifest_contract_complete", False):
            blockers.append(
                f"strategy_manifest_contract_incomplete:{row.get('strategy_manifest_id', '')}"
            )
        missing_fields = list(contract_summary.get("missing_fields", []))
        if missing_fields:
            blockers.append(
                f"strategy_manifest_contract_missing_fields:{row.get('strategy_manifest_id', '')}:{','.join(missing_fields)}"
            )
        manifest_path = str(row.get("strategy_manifest_path", "") or "")
        if root is not None and manifest_path:
            resolved = _resolve_path(Path(root), manifest_path)
            if not resolved.exists():
                blockers.append(
                    f"strategy_manifest_path_not_found:{row.get('strategy_manifest_id', '')}"
                )

    if not contract.get("all_strategy_manifest_contracts_complete", False):
        blockers.append("portfolio_evidence_contract_manifest_completeness_failed")

    blockers = list(dict.fromkeys(str(item) for item in blockers if str(item).strip()))
    return PortfolioPaperReviewEvidenceValidation(
        status="READY" if not blockers else "BLOCKED",
        blocking_reasons=blockers,
        strategy_manifest_ids=strategy_manifest_ids,
        portfolio_sim_id=portfolio_sim_id,
    )


def _resolve_path(root: Path, raw_path: str) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path
    if path.exists():
        return path
    return root / path
