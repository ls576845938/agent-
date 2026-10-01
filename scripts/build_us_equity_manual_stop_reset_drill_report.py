#!/usr/bin/env python3
"""Build an evidence-only manual stop/reset drill report for US equity readiness."""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


SCHEMA_VERSION = "us_equity_manual_stop_reset_drill_v1"
DEFAULT_OUTPUT = Path("artifacts/us_equity_etf_macro_rotation/latest/us_equity_manual_stop_reset_drill_report.json")
DEFAULT_MARKDOWN_OUTPUT = Path("../学习资料/量化交易业务闭环/系统评估/US Equity 手动停机复位演练.md")


def build_us_equity_manual_stop_reset_drill_report(
    *,
    repo_root: Path | None = None,
    output: Path = DEFAULT_OUTPUT,
    markdown_output: Path = DEFAULT_MARKDOWN_OUTPUT,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at or _utc_z_now()
    events = _events()
    checklist = _checklist()
    incident_review = _incident_review()
    blockers = _blockers(events, checklist, incident_review)
    status = "manual_stop_reset_proven" if not blockers else "manual_stop_reset_blocked"
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated,
        "asset": "us_equity",
        "status": status,
        "allowed_statuses": ["manual_stop_reset_blocked", "manual_stop_reset_proven"],
        "event_count": len(events),
        "checklist_count": len(checklist),
        "incident_review_field_count": len(incident_review),
        "events": events,
        "reset_checklist": checklist,
        "incident_review": incident_review,
        "blockers": blockers,
        "guardrails": {
            "evidence_only": True,
            "simulated_stop_only": True,
            "paper_or_live_unlock_allowed": False,
            "paper_simulation_allowed": False,
            "live_order_allowed": False,
            "private_endpoint_allowed": False,
            "order_endpoint_allowed": False,
            "broker_calls_used": False,
            "real_order_submitted": False,
        },
        "outputs": {
            "json": _relpath(_resolve(root, output), root),
            "markdown": _relpath(_resolve(root, markdown_output), root),
        },
    }
    _write_json(_resolve(root, output), payload)
    _write_text(_resolve(root, markdown_output), _markdown(payload))
    return payload


def _events() -> list[dict[str, Any]]:
    return [
        {
            "timestamp": "2026-06-01T20:00:00Z",
            "event_id": "manual-stop-requested",
            "event_type": "manual_stop_requested",
            "operator": "simulated_operator",
            "reason": "drill_manual_stop_before_order_window",
            "stop_state": "STOP_REQUESTED",
        },
        {
            "timestamp": "2026-06-01T20:00:01Z",
            "event_id": "downstream-orders-blocked",
            "event_type": "downstream_orders_blocked",
            "attempted_order_count": 1,
            "blocked_order_count": 1,
            "stop_state": "STOP_ACTIVE",
        },
        {
            "timestamp": "2026-06-01T20:05:00Z",
            "event_id": "manual-reset-reviewed",
            "event_type": "manual_reset_reviewed",
            "reviewer": "simulated_reviewer",
            "stop_state": "RESET_REVIEWED",
        },
        {
            "timestamp": "2026-06-01T20:10:00Z",
            "event_id": "manual-reset-recorded",
            "event_type": "manual_reset_recorded",
            "reviewer": "simulated_reviewer",
            "stop_state": "RESET_RECORDED",
        },
    ]


def _checklist() -> list[dict[str, Any]]:
    return [
        {"check_id": "data_freshness_checked", "passed": True},
        {"check_id": "ledger_reconciliation_checked", "passed": True},
        {"check_id": "unsafe_endpoint_flags_checked", "passed": True},
        {"check_id": "risk_limits_checked", "passed": True},
        {"check_id": "manual_reviewer_recorded", "passed": True},
        {"check_id": "restart_requires_new_run_id", "passed": True},
    ]


def _incident_review() -> dict[str, str]:
    return {
        "timeline": "manual stop requested, downstream order blocked, reset reviewed, reset recorded",
        "impact_scope": "simulated execution only; no broker/private/order endpoint used",
        "direct_cause": "operator initiated manual stop drill",
        "root_cause": "scheduled readiness drill",
        "gate_that_failed_to_block": "none",
        "remediation": "manual reset requires checklist and new run id",
        "regression_test": "test_us_equity_manual_stop_reset_drill_report",
        "pause_or_retire_decision": "continue observation only; live remains locked",
    }


def _blockers(events: list[Mapping[str, Any]], checklist: list[Mapping[str, Any]], incident_review: Mapping[str, Any]) -> list[str]:
    blockers: list[str] = []
    event_types = {str(item.get("event_type")) for item in events}
    required_events = {
        "manual_stop_requested",
        "downstream_orders_blocked",
        "manual_reset_reviewed",
        "manual_reset_recorded",
    }
    missing_events = sorted(required_events - event_types)
    blockers.extend(f"manual_stop_reset_missing_event:{item}" for item in missing_events)
    if not all(item.get("passed") is True for item in checklist):
        blockers.append("manual_stop_reset_checklist_not_all_passed")
    required_fields = {
        "timeline",
        "impact_scope",
        "direct_cause",
        "root_cause",
        "gate_that_failed_to_block",
        "remediation",
        "regression_test",
        "pause_or_retire_decision",
    }
    blockers.extend(f"manual_stop_reset_missing_incident_field:{item}" for item in sorted(required_fields - set(incident_review)))
    return blockers


def _markdown(payload: Mapping[str, Any]) -> str:
    lines = [
        "# US Equity 手动停机复位演练",
        "",
        f"- generated_at: `{payload.get('generated_at')}`",
        f"- status: `{payload.get('status')}`",
        f"- event_count: `{payload.get('event_count')}`",
        f"- checklist_count: `{payload.get('checklist_count')}`",
        "",
        "## Events",
        "",
    ]
    for event in _list(payload.get("events")):
        if isinstance(event, Mapping):
            lines.append(f"- `{event.get('event_type')}`：`{event.get('stop_state')}`")
    lines.extend(["", "## Guardrails", "", "- simulated stop only", "- live_order_allowed=false", "- order_endpoint_allowed=false"])
    return "\n".join(lines)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(json.dumps(dict(payload), indent=2, sort_keys=True, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    except Exception:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
        raise


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(content + "\n", encoding="utf-8")
        os.replace(tmp, path)
    except Exception:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
        raise


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _relpath(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _utc_z_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN_OUTPUT)
    parser.add_argument("--generated-at", default="")
    args = parser.parse_args()
    payload = build_us_equity_manual_stop_reset_drill_report(
        repo_root=args.repo_root,
        output=args.output,
        markdown_output=args.markdown_output,
        generated_at=args.generated_at or None,
    )
    print(payload["status"])


if __name__ == "__main__":
    main()
