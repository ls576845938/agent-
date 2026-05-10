"""Read-only paper validation evidence inspection.

This module summarizes persisted artifacts for the 30 trading day paper
validation review.  It deliberately does not import runtime, broker, or live
execution modules; all fields are derived from JSON/JSONL evidence already on
disk.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class EvidencePointer:
    name: str
    path: str
    state: str
    detail: str = ""


@dataclass(frozen=True)
class PaperValidationEvidence:
    data_root: str
    ledger_root: str
    validation_state_path: str
    days_required: int
    days_completed: int
    consecutive_clean_days: int
    paper_submit_orders: str
    readiness_state: str
    gaps: list[str] = field(default_factory=list)
    evidence: list[EvidencePointer] = field(default_factory=list)
    daily_report_summary: dict[str, Any] = field(default_factory=dict)
    ledger_reconciliation_summary: dict[str, Any] = field(default_factory=dict)
    broker_local_diff_summary: dict[str, Any] = field(default_factory=dict)
    recovery_summary: dict[str, Any] = field(default_factory=dict)
    session_summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "data_root": self.data_root,
            "ledger_root": self.ledger_root,
            "validation_state_path": self.validation_state_path,
            "days_required": self.days_required,
            "days_completed": self.days_completed,
            "consecutive_clean_days": self.consecutive_clean_days,
            "paper_submit_orders": self.paper_submit_orders,
            "readiness_state": self.readiness_state,
            "gaps": list(self.gaps),
            "evidence": [pointer.__dict__ for pointer in self.evidence],
            "daily_report_summary": dict(self.daily_report_summary),
            "ledger_reconciliation_summary": dict(self.ledger_reconciliation_summary),
            "broker_local_diff_summary": dict(self.broker_local_diff_summary),
            "recovery_summary": dict(self.recovery_summary),
            "session_summary": dict(self.session_summary),
        }


def inspect_paper_validation_evidence(
    data_root: str | Path = "data",
    *,
    ledger_root: str | Path | None = None,
    validation_state_path: str | Path | None = None,
) -> PaperValidationEvidence:
    root = Path(data_root)
    ledger = Path(ledger_root) if ledger_root else root / "paper_ledger"
    state_path = _resolve_validation_state(root, ledger, validation_state_path)
    state = _read_json_object(state_path)

    required = int(state.get("days_required", 30) or 30) if state else 30
    completed = int(state.get("days_completed", 0) or 0) if state else 0
    clean = int(state.get("consecutive_clean_days", 0) or 0) if state else 0

    session_path = ledger / "audit" / "paper_session_manifest.json"
    session = _read_json_object(session_path)
    startup_path = ledger / "audit" / "paper_broker_adapter_startup_sync.json"
    startup = _read_json_object(startup_path)
    recovery_path = _resolve_broker_state_recovery_path(state, ledger)
    daily_path = _latest_file(ledger / "daily_reports", "daily_report_*.json")
    daily = _read_json_object(daily_path)
    recon_path = _latest_file(ledger / "reconciliation", "recon_*.json")
    recon = _read_json_object(recon_path)
    artifact_path = _latest_file(ledger / "reconciliation", "ledger_recon_artifact_*.json")
    artifact = _read_json_object(artifact_path)
    journal_path = ledger / "run_journal.jsonl"
    run_state_path = ledger / "run_state.json"
    run_state = _read_json_object(run_state_path)
    validation_report_path = _first_existing(
        root / "reports" / "paper_production" / "validation_report.json",
        ledger / "validation_report.json",
    )

    pointers = [
        _pointer("validation_state", state_path),
        _pointer("validation_report", validation_report_path),
        _pointer("daily_report", daily_path),
        _pointer("paper_session_manifest", session_path),
        _pointer("startup_sync", startup_path),
        _pointer("broker_state_recovery", recovery_path),
        _pointer("ledger_reconciliation", recon_path),
        _pointer("ledger_reconciliation_artifact", artifact_path),
        _pointer("run_journal", journal_path),
    ]

    submit_state, submit_gaps = _paper_submit_state(session)
    daily_summary, daily_gaps = _daily_report_summary(daily, daily_path)
    recon_summary, diff_summary, recon_gaps = _reconciliation_summaries(recon, artifact)
    recovery_summary = _recovery_summary(
        state,
        recovery_path,
        journal_path,
        run_state,
    )
    session_summary, session_gaps = _session_summary(session, startup)

    gaps: list[str] = []
    if not state_path or not state_path.exists():
        gaps.append("validation_state_missing")
    if completed < required:
        gaps.append(f"days_completed_below_required:{completed}/{required}")
    if clean < required:
        gaps.append(f"consecutive_clean_days_below_required:{clean}/{required}")
    gaps.extend(submit_gaps)
    gaps.extend(daily_gaps)
    gaps.extend(recon_gaps)
    gaps.extend(session_gaps)
    recovery_path_value = str(recovery_summary.get("artifact_path", "") or "")
    if not recovery_path_value:
        gaps.append("broker_state_recovery_missing")
    elif not bool(recovery_summary.get("operationally_complete", False)):
        status = str(recovery_summary.get("status", "missing") or "missing")
        gaps.append(f"broker_state_recovery_incomplete:{status}")

    readiness = "PASS" if not gaps else "BLOCKED"
    return PaperValidationEvidence(
        data_root=str(root),
        ledger_root=str(ledger),
        validation_state_path=str(state_path) if state_path else "",
        days_required=required,
        days_completed=completed,
        consecutive_clean_days=clean,
        paper_submit_orders=submit_state,
        readiness_state=readiness,
        gaps=gaps,
        evidence=pointers,
        daily_report_summary=daily_summary,
        ledger_reconciliation_summary=recon_summary,
        broker_local_diff_summary=diff_summary,
        recovery_summary=recovery_summary,
        session_summary=session_summary,
    )


def _resolve_validation_state(
    data_root: Path,
    ledger_root: Path,
    explicit: str | Path | None,
) -> Path:
    if explicit:
        return Path(explicit)
    candidates = [
        data_root / "reports" / "paper_production" / "validation_state.json",
        ledger_root / "validation_state.json",
    ]
    return _first_existing(*candidates) or candidates[0]


def _first_existing(*paths: Path) -> Path | None:
    for path in paths:
        if path.exists():
            return path
    return None


def _latest_file(directory: Path, pattern: str) -> Path | None:
    if not directory.exists():
        return None
    files = list(directory.glob(pattern))
    if not files:
        return None
    return max(files, key=lambda path: (path.stat().st_mtime_ns, path.name))


def _read_json_object(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _first_present(*values: Any) -> Any:
    for value in values:
        if value is not None and value != "":
            return value
    return None


def _pointer(name: str, path: Path | None) -> EvidencePointer:
    if path is None:
        return EvidencePointer(name=name, path="", state="MISSING")
    return EvidencePointer(
        name=name,
        path=str(path),
        state="PASS" if path.exists() else "MISSING",
    )


def _resolve_broker_state_recovery_path(state: dict[str, Any], ledger_root: Path) -> Path | None:
    evidence = state.get("evidence", {})
    if isinstance(evidence, dict):
        raw_path = str(evidence.get("broker_state_recovery_path", "") or "")
        if raw_path:
            return Path(raw_path)
    return ledger_root / "audit" / "paper_broker_state_recovery.json"


def _paper_submit_state(session: dict[str, Any]) -> tuple[str, list[str]]:
    if not session:
        return "UNKNOWN", ["paper_session_manifest_missing"]
    submit = bool(session.get("submit_orders", False))
    proof = session.get("no_real_order_submission_proof", {})
    proof_status = str(proof.get("status", "") if isinstance(proof, dict) else "")
    if submit:
        return "ENABLED", ["paper_submit_orders_enabled"]
    if proof_status:
        return "DISABLED", []
    return "DISABLED", ["paper_no_submit_proof_missing"]


def _daily_report_summary(payload: dict[str, Any], path: Path | None) -> tuple[dict[str, Any], list[str]]:
    if not payload:
        return {"path": str(path) if path else "", "state": "MISSING"}, ["daily_report_missing"]
    errors = payload.get("errors", [])
    gaps = ["daily_report_errors_present"] if errors else []
    return (
        {
            "path": str(path) if path else "",
            "report_date": payload.get("report_date") or payload.get("date", ""),
            "orders_submitted": int(payload.get("orders_submitted", 0) or 0),
            "orders_filled": int(payload.get("orders_filled", 0) or 0),
            "reconciliation_status": payload.get("reconciliation_status", "unknown"),
            "errors_count": len(errors) if isinstance(errors, list) else 1,
        },
        gaps,
    )


def _reconciliation_summaries(
    recon: dict[str, Any],
    artifact: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    gaps: list[str] = []
    status = str(recon.get("status", "unknown") if recon else "unknown")
    position_diffs = recon.get("position_diffs", {}) if isinstance(recon.get("position_diffs", {}), dict) else {}
    order_diffs = recon.get("order_diffs", {}) if isinstance(recon.get("order_diffs", {}), dict) else {}
    fill_diffs = recon.get("fill_diffs", {}) if isinstance(recon.get("fill_diffs", {}), dict) else {}
    cash_diff = float(recon.get("cash_diff", 0.0) or 0.0) if recon else 0.0
    diff_count = len(position_diffs) + len(order_diffs) + len(fill_diffs) + (1 if abs(cash_diff) > 1e-6 else 0)
    if not recon:
        gaps.append("ledger_reconciliation_missing")
    elif status not in {"clean", "PASS", "pass"} or diff_count:
        gaps.append("broker_local_diff_not_clean")
    if not artifact:
        gaps.append("ledger_reconciliation_artifact_missing")

    fills = artifact.get("fills", {}) if isinstance(artifact.get("fills", {}), dict) else {}
    hashes = artifact.get("hashes", {}) if isinstance(artifact.get("hashes", {}), dict) else {}
    pnl = artifact.get("pnl", {}) if isinstance(artifact.get("pnl", {}), dict) else {}
    return (
        {
            "status": status,
            "halt_new_orders": bool(recon.get("halt_new_orders", False)) if recon else False,
            "artifact_hash": artifact.get("artifact_hash", ""),
            "fills_hash": hashes.get("fills_hash", ""),
            "duplicate_fill_count": int(fills.get("duplicate_fill_count", 0) or 0),
            "conflict_fill_count": int(fills.get("conflict_fill_count", 0) or 0),
            "ledger_pnl": float(pnl.get("net_pnl", 0.0) or 0.0),
        },
        {
            "cash_diff": cash_diff,
            "position_diff_count": len(position_diffs),
            "order_diff_count": len(order_diffs),
            "fill_diff_count": len(fill_diffs),
            "total_diff_count": diff_count,
        },
        gaps,
    )


def _recovery_summary(
    state: dict[str, Any],
    recovery_path: Path | None,
    journal_path: Path,
    run_state: dict[str, Any],
) -> dict[str, Any]:
    event_counts: dict[str, int] = {}
    latest_event = ""
    if journal_path.exists():
        try:
            for line in journal_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                payload = json.loads(line)
                if not isinstance(payload, dict):
                    continue
                event = str(payload.get("entry_type") or payload.get("event") or "")
                if any(token in event for token in ("recover", "resume", "incident", "error", "fail")):
                    event_counts[event] = event_counts.get(event, 0) + 1
                    latest_event = event
        except (OSError, json.JSONDecodeError):
            event_counts["journal_unreadable"] = 1
    state_recovery = state.get("recovery_summary", {})
    if not isinstance(state_recovery, dict):
        state_recovery = {}
    artifact = _read_json_object(recovery_path)
    artifact_path = str(recovery_path) if recovery_path and recovery_path.exists() else ""
    resume_detected = _first_present(
        artifact.get("resume_detected"),
        state_recovery.get("required"),
        run_state.get("recovery_required"),
        False,
    )
    status = str(
        _first_present(
            artifact.get("status"),
            state_recovery.get("status"),
            "missing" if not artifact_path else "unknown",
        )
    )
    operationally_complete = bool(
        _first_present(
            artifact.get("operationally_complete"),
            state_recovery.get("operationally_complete"),
            False,
        )
    )
    return {
        "recovery_required": bool(resume_detected),
        "artifact_path": artifact_path,
        "artifact_state": "PASS" if artifact_path else "MISSING",
        "status": status,
        "operationally_complete": operationally_complete,
        "resume_detected": bool(resume_detected),
        "broker_state_restored": bool(
            _first_present(
                artifact.get("broker_state_restored"),
                state_recovery.get("resume_restores_broker_state"),
                False,
            )
        ),
        "broker_state_verified": bool(
            _first_present(
                artifact.get("broker_state_verified"),
                state_recovery.get("broker_state_verified"),
                False,
            )
        ),
        "reason": str(
            _first_present(
                artifact.get("error"),
                state_recovery.get("reason"),
                "",
            )
        ),
        "last_step": str(run_state.get("last_step", "")),
        "event_counts": event_counts,
        "latest_event": latest_event,
    }


def _session_summary(
    session: dict[str, Any],
    startup: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    gaps: list[str] = []
    if not session:
        gaps.append("paper_session_manifest_missing")
    if not startup:
        gaps.append("startup_sync_missing")
    elif str(startup.get("status", "")).lower() not in {"", "pass", "ok", "clean", "complete"}:
        gaps.append("startup_sync_not_clean")
    return (
        {
            "session_id": session.get("session_id", ""),
            "mode": session.get("mode", ""),
            "paper_broker": session.get("paper_broker", ""),
            "broker_backend": session.get("broker_backend", ""),
            "history_artifact_path": session.get("history_artifact_path", ""),
            "startup_sync_status": startup.get("status", ""),
        },
        gaps,
    )
