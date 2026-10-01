"""Contracts for portfolio paper-review evidence.

This module defines the minimum persisted evidence required before a
portfolio simulation can enter the human paper-review queue.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


PORTFOLIO_PAPER_REVIEW_EVIDENCE_SCHEMA_VERSION = "portfolio_paper_review_evidence_v3"
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
    "cpcv",
    "cost_model",
    "slippage_model",
    "cost_stress",
    "style_exposure",
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
    missing_reasons = dict(manifest.get("contract_missing_reasons", {}) or {})
    missing_fields: list[str] = []
    documented_missing_fields: list[str] = []
    undocumented_missing_fields: list[str] = []
    field_status: dict[str, dict[str, Any]] = {}
    for field_name in REQUIRED_STRATEGY_MANIFEST_FIELDS:
        present = _field_value_present(field_name, manifest.get(field_name))
        status = {"present": present}
        if not present:
            missing_fields.append(field_name)
            reason = str(missing_reasons.get(field_name, "") or "").strip()
            if not reason:
                reason = _default_missing_reason(field_name, manifest.get(field_name))
            status["missing_reason"] = reason
            if reason:
                documented_missing_fields.append(field_name)
            else:
                undocumented_missing_fields.append(field_name)
        field_status[field_name] = status
    return {
        "required_fields": list(REQUIRED_STRATEGY_MANIFEST_FIELDS),
        "missing_fields": missing_fields,
        "documented_missing_fields": documented_missing_fields,
        "undocumented_missing_fields": undocumented_missing_fields,
        "missing_field_reasons": {
            field_name: field_status[field_name]["missing_reason"]
            for field_name in missing_fields
            if field_status[field_name].get("missing_reason")
        },
        "field_status": field_status,
        "contract_documented": not undocumented_missing_fields,
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
    manifest_statuses = []
    manifest_documentation = []
    for section in candidate_sections:
        manifest_statuses.append(
            bool(section.get("strategy_manifest_contract_complete", False))
        )
        contract_summary = dict(section.get("strategy_manifest_contract", {}) or {})
        manifest_documentation.append(
            bool(
                contract_summary.get(
                    "contract_documented",
                    not contract_summary.get("missing_fields", []),
                )
            )
        )
    return {
        "schema_version": PORTFOLIO_PAPER_REVIEW_EVIDENCE_SCHEMA_VERSION,
        "origin": PORTFOLIO_PAPER_REVIEW_EVIDENCE_ORIGIN,
        "portfolio_sim_id": portfolio_sim_id,
        "strategy_manifest_ids": list(strategy_manifest_ids),
        "candidate_count": len(candidate_sections),
        "all_strategy_manifest_contracts_complete": all(manifest_statuses)
        if manifest_statuses
        else False,
        "all_strategy_manifest_contracts_documented": all(manifest_documentation)
        if manifest_documentation
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
        undocumented_missing_fields = list(
            contract_summary.get("undocumented_missing_fields", [])
        )
        if undocumented_missing_fields:
            blockers.append(
                "strategy_manifest_contract_missing_reasons:"
                f"{row.get('strategy_manifest_id', '')}:{','.join(undocumented_missing_fields)}"
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
    documented_contracts = contract.get("all_strategy_manifest_contracts_documented")
    if documented_contracts is None:
        documented_contracts = not any(
            list(dict(row).get("strategy_manifest_contract", {}).get("undocumented_missing_fields", []))
            for row in portfolio_candidates
            if isinstance(row, dict)
        )
    if not documented_contracts:
        blockers.append("portfolio_evidence_contract_manifest_documentation_failed")

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


def _field_value_present(field_name: str, value: Any) -> bool:
    if field_name == "trial_count":
        return int(value or 0) > 0
    if field_name in {"pbo", "dsr"}:
        return value is not None
    if field_name == "cpcv":
        return (
            isinstance(value, dict)
            and str(value.get("method", "")).lower() == "cpcv"
            and (
                int(value.get("path_count", 0) or 0) > 0
                or int(value.get("fold_count", 0) or 0) > 0
            )
        )
    if field_name == "cost_stress":
        return isinstance(value, dict) and (
            value.get("stress_survival_rate") is not None
            or value.get("cost_sensitivity") is not None
            or int(value.get("level_count", 0) or 0) > 0
        )
    if field_name == "style_exposure":
        return isinstance(value, dict) and (
            bool(value.get("betas")) or bool(value.get("benchmark_columns"))
        )
    if field_name == "capacity":
        return isinstance(value, dict) and any(
            value.get(key) is not None
            for key in ("estimated_capacity_usd", "fragility_score")
        )
    if field_name == "turnover":
        return isinstance(value, dict) and any(
            value.get(key) is not None
            for key in ("turnover", "annual_turnover_pct", "trade_count")
        )
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, dict):
        return bool(value)
    if isinstance(value, list):
        return field_name == "failure_conditions" or bool(value)
    return True


def _default_missing_reason(field_name: str, value: Any) -> str:
    if field_name == "cpcv" and isinstance(value, dict):
        return str(value.get("missing_reason", "") or "")
    if field_name == "cost_stress" and isinstance(value, dict):
        return str(value.get("missing_reason", "") or "")
    if field_name == "style_exposure" and isinstance(value, dict):
        return str(value.get("missing_reason", "") or "")
    return f"{field_name}_missing"
