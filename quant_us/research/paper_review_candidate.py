"""Read-only paper-review candidate evidence packaging.

This module assembles persisted paper-trading evidence into a single
paper-review candidate payload. It never imports runtime or execution loops.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from quant_us.core.clock import utc_now
from quant_us.reports.paper_validation import inspect_paper_validation_evidence
from quant_us.reports.portfolio_observability import inspect_portfolio_observability


_PASS_STATES = {"PASS", "OK", "CLEAN", "COMPLETE", "COMPLETED", "READY"}
_ATTRIBUTION_CANDIDATES = (
    "paper_ledger/daily_reports/strategy_attribution_*.json",
    "reports/paper_production/strategy_attribution_*.json",
)


@dataclass(frozen=True)
class PaperReviewCandidateEvidence:
    candidate_id: str
    data_root: str
    generated_at: str
    schema_version: str = "paper_review_candidate_evidence_v1"
    review_candidate_status: str = "BLOCKED"
    overall_status: str = "BLOCKED"
    blocking_reasons: list[str] = field(default_factory=list)
    sections: dict[str, Any] = field(default_factory=dict)
    portfolio_observability: dict[str, Any] = field(default_factory=dict)
    paper_validation: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "candidate_id": self.candidate_id,
            "data_root": self.data_root,
            "generated_at": self.generated_at,
            "review_candidate_status": self.review_candidate_status,
            "overall_status": self.overall_status,
            "blocking_reasons": list(self.blocking_reasons),
            "sections": dict(self.sections),
            "portfolio_observability": dict(self.portfolio_observability),
            "paper_validation": dict(self.paper_validation),
        }


def inspect_paper_review_candidate_evidence(
    candidate_id: str,
    data_root: str | Path = "data",
    *,
    ledger_root: str | Path | None = None,
    validation_state_path: str | Path | None = None,
    strategy: str = "portfolio",
) -> PaperReviewCandidateEvidence:
    root = Path(data_root)
    paper_validation = inspect_paper_validation_evidence(
        root,
        ledger_root=ledger_root,
        validation_state_path=validation_state_path,
    ).to_dict()
    observability = inspect_portfolio_observability(root, strategy=strategy).to_dict()
    attribution_path, attribution_payload = _latest_attribution_payload(root)

    sections = {
        "multi_strategy": _multi_strategy_section(observability),
        "multi_timeframe": _multi_timeframe_section(observability),
        "paper_validation": _paper_validation_section(paper_validation),
        "ledger_reconciliation": _ledger_reconciliation_section(paper_validation),
        "strategy_attribution": _strategy_attribution_section(
            observability,
            attribution_path,
            attribution_payload,
        ),
    }
    blocking_reasons: list[str] = []
    for name, section in sections.items():
        if str(section.get("status", "BLOCKED")).upper() != "PASS":
            detail = str(section.get("blocking_reason", "") or f"{name}_not_ready")
            if detail not in blocking_reasons:
                blocking_reasons.append(detail)

    overall_status = "PASS" if not blocking_reasons else "BLOCKED"
    review_status = "READY_FOR_REVIEW" if overall_status == "PASS" else "BLOCKED"
    return PaperReviewCandidateEvidence(
        candidate_id=candidate_id,
        data_root=str(root),
        generated_at=utc_now().isoformat(),
        review_candidate_status=review_status,
        overall_status=overall_status,
        blocking_reasons=blocking_reasons,
        sections=sections,
        portfolio_observability=observability,
        paper_validation=paper_validation,
    )


def _multi_strategy_section(observability: dict[str, Any]) -> dict[str, Any]:
    payload = dict(observability.get("multi_strategy", {}))
    count = int(payload.get("strategy_count", 0) or 0)
    status = "PASS" if _is_pass(payload.get("status")) and count > 1 else "BLOCKED"
    reason = "" if status == "PASS" else "multi_strategy_evidence_not_ready"
    if count <= 1:
        reason = "multi_strategy_count_below_two"
    return {
        "status": status,
        "strategy_count": count,
        "detail": str(payload.get("detail", "")),
        "evidence_path": str(payload.get("evidence_path", "")),
        "blocking_reason": reason,
    }


def _multi_timeframe_section(observability: dict[str, Any]) -> dict[str, Any]:
    payload = dict(observability.get("multi_timeframe", {}))
    count = int(payload.get("timeframe_count", 0) or 0)
    status = "PASS" if _is_pass(payload.get("status")) and count > 1 else "BLOCKED"
    reason = "" if status == "PASS" else "multi_timeframe_evidence_not_ready"
    if count <= 1:
        reason = "multi_timeframe_count_below_two"
    return {
        "status": status,
        "timeframe_count": count,
        "detail": str(payload.get("detail", "")),
        "evidence_path": str(payload.get("evidence_path", "")),
        "blocking_reason": reason,
    }


def _paper_validation_section(validation: dict[str, Any]) -> dict[str, Any]:
    gaps = list(validation.get("gaps", []))
    readiness = str(validation.get("readiness_state", "BLOCKED"))
    audit = str(validation.get("audit_blocker_status", "BLOCKED"))
    status = "PASS" if _is_pass(readiness) and _is_pass(audit) and not gaps else "BLOCKED"
    reason = "" if status == "PASS" else gaps[0] if gaps else "paper_validation_not_ready"
    return {
        "status": status,
        "readiness_state": readiness,
        "audit_blocker_status": audit,
        "days_completed": int(validation.get("days_completed", 0) or 0),
        "days_required": int(validation.get("days_required", 0) or 0),
        "gaps": gaps,
        "blocking_reason": reason,
    }


def _ledger_reconciliation_section(validation: dict[str, Any]) -> dict[str, Any]:
    recon = dict(validation.get("ledger_reconciliation_summary", {}))
    diff = dict(validation.get("broker_local_diff_summary", {}))
    status_text = str(recon.get("status", "missing"))
    halt = bool(recon.get("halt_new_orders", False))
    total_diff = int(diff.get("total_diff_count", 0) or 0)
    status = (
        "PASS"
        if _is_pass(status_text) and not halt and total_diff == 0 and recon.get("artifact_hash")
        else "BLOCKED"
    )
    reason = ""
    if status != "PASS":
        if not recon.get("artifact_hash"):
            reason = "ledger_reconciliation_artifact_missing"
        elif halt:
            reason = "ledger_reconciliation_halt_new_orders"
        elif total_diff != 0:
            reason = "broker_local_diff_detected"
        else:
            reason = "ledger_reconciliation_not_clean"
    return {
        "status": status,
        "reconciliation_status": status_text,
        "halt_new_orders": halt,
        "artifact_hash": str(recon.get("artifact_hash", "")),
        "cash_diff": float(diff.get("cash_diff", 0.0) or 0.0),
        "position_diff_count": int(diff.get("position_diff_count", 0) or 0),
        "order_diff_count": int(diff.get("order_diff_count", 0) or 0),
        "fill_diff_count": int(diff.get("fill_diff_count", 0) or 0),
        "total_diff_count": total_diff,
        "blocking_reason": reason,
    }


def _strategy_attribution_section(
    observability: dict[str, Any],
    attribution_path: Path | None,
    attribution_payload: dict[str, Any],
) -> dict[str, Any]:
    pnl_payload = dict(observability.get("pnl_attribution", {}))
    by_strategy = attribution_payload.get("by_strategy", {})
    rows = by_strategy if isinstance(by_strategy, dict) else {}
    row_count = len(rows)
    totals = attribution_payload.get("totals", {})
    total_fills = float(totals.get("fills", 0.0) or 0.0)
    if total_fills <= 0:
        total_fills = sum(float(row.get("fills", 0.0) or 0.0) for row in rows.values())
    total_notional = sum(
        float(row.get("filled_notional", 0.0) or 0.0) for row in rows.values()
    )
    status = "PASS"
    reason = ""
    if attribution_path is None:
        status = "BLOCKED"
        reason = "strategy_attribution_report_missing"
    elif row_count <= 0:
        status = "BLOCKED"
        reason = "strategy_attribution_rows_missing"
    elif total_fills <= 0:
        status = "BLOCKED"
        reason = "strategy_attribution_missing_fills"
    elif total_notional <= 0:
        status = "BLOCKED"
        reason = "strategy_attribution_missing_filled_notional"
    elif not _is_pass(pnl_payload.get("status")):
        status = "BLOCKED"
        reason = "portfolio_pnl_attribution_not_ready"
    return {
        "status": status,
        "row_count": row_count,
        "total_fills": total_fills,
        "total_orders": float(totals.get("orders", 0.0) or 0.0),
        "total_filled_notional": total_notional,
        "strategies": sorted(rows),
        "evidence_path": str(attribution_path or ""),
        "observability_state": str(pnl_payload.get("status", "")),
        "observability_evidence_path": str(pnl_payload.get("evidence_path", "")),
        "blocking_reason": reason,
    }


def _latest_attribution_payload(root: Path) -> tuple[Path | None, dict[str, Any]]:
    paths: list[Path] = []
    for pattern in _ATTRIBUTION_CANDIDATES:
        paths.extend(root.glob(pattern))
    for path in sorted(paths, key=lambda item: (item.stat().st_mtime_ns, item.name), reverse=True):
        payload = _read_json_object(path)
        if payload:
            return path, payload
    return None, {}


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _is_pass(value: Any) -> bool:
    return str(value or "").strip().upper() in _PASS_STATES
