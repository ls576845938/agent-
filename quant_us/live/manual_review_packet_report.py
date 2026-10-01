#!/usr/bin/env python3
"""Service layer for the US equity manual-review packet report.

The service reads existing evidence and assembles a fail-closed packet for a
human reviewer. It never records approval or unlocks paper/live trading.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from quant_us.live.manual_review_packet import STRATEGY_ID, evaluate_manual_review_packet


SCHEMA_VERSION = "us_equity_manual_review_packet_v1"
DEFAULT_OUTPUT = Path("artifacts/us_equity_etf_macro_rotation/latest/us_equity_manual_review_packet.json")
DEFAULT_MARKDOWN_OUTPUT = Path("../学习资料/量化交易业务闭环/系统评估/US Equity 人工审阅包.md")
DEFAULT_STRATEGY_GATE = Path("artifacts/us_equity_etf_macro_rotation/latest/us_etf_strategy_validation_gate_report.json")
DEFAULT_STRATEGY_EVIDENCE_AUDIT = Path(
    "artifacts/us_equity_etf_macro_rotation/latest/us_etf_strategy_validation_evidence_audit.json"
)
DEFAULT_FORWARD_EVALUATION = Path(
    "artifacts/us_equity_etf_macro_rotation/latest/us_etf_forward_observation_evaluation_report.json"
)
DEFAULT_DATA_FRESHNESS = Path("artifacts/us_equity_data_status/latest/us_equity_data_freshness_daily_report.json")
DEFAULT_SMALL_ACCOUNT = Path(
    "artifacts/us_equity_etf_macro_rotation/latest/us_etf_small_account_execution_preflight_report.json"
)
DEFAULT_LIVE_READINESS = Path(
    "artifacts/us_equity_etf_macro_rotation/latest/us_equity_live_readiness_risk_constitution_report.json"
)
DEFAULT_MANUAL_DECISION_RECORD = Path(
    "artifacts/us_equity_etf_macro_rotation/latest/us_equity_manual_decision_record_report.json"
)
DEFAULT_PRODUCTION_PIT_INTAKE_STATUS = Path(
    "artifacts/us_equity_data_lineage/latest/us_equity_pit_data_intake_status_report.json"
)
DEFAULT_PIT_BUNDLE_ACCEPTANCE = Path(
    "artifacts/us_equity_data_lineage/latest/us_equity_pit_bundle_acceptance_run_report.json"
)
DEFAULT_BLOCKER_TAXONOMY = Path(
    "artifacts/us_equity_strategy_production_line/latest/us_equity_blocker_taxonomy_report.json"
)


def build_us_equity_manual_review_packet(
    *,
    repo_root: Path | None = None,
    output: Path = DEFAULT_OUTPUT,
    markdown_output: Path = DEFAULT_MARKDOWN_OUTPUT,
    strategy_gate: Path = DEFAULT_STRATEGY_GATE,
    strategy_evidence_audit: Path = DEFAULT_STRATEGY_EVIDENCE_AUDIT,
    forward_evaluation: Path = DEFAULT_FORWARD_EVALUATION,
    data_freshness: Path = DEFAULT_DATA_FRESHNESS,
    small_account_preflight: Path = DEFAULT_SMALL_ACCOUNT,
    live_readiness: Path = DEFAULT_LIVE_READINESS,
    manual_decision_record: Path = DEFAULT_MANUAL_DECISION_RECORD,
    production_pit_intake_status: Path = DEFAULT_PRODUCTION_PIT_INTAKE_STATUS,
    pit_bundle_acceptance: Path = DEFAULT_PIT_BUNDLE_ACCEPTANCE,
    blocker_taxonomy: Path = DEFAULT_BLOCKER_TAXONOMY,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at or _utc_z_now()
    paths = {
        "strategy_gate": _resolve(root, strategy_gate),
        "strategy_evidence_audit": _resolve(root, strategy_evidence_audit),
        "forward_evaluation": _resolve(root, forward_evaluation),
        "data_freshness": _resolve(root, data_freshness),
        "small_account_preflight": _resolve(root, small_account_preflight),
        "live_readiness": _resolve(root, live_readiness),
        "manual_decision_record": _resolve(root, manual_decision_record),
        "production_pit_intake_status": _resolve(root, production_pit_intake_status),
        "pit_bundle_acceptance": _resolve(root, pit_bundle_acceptance),
        "blocker_taxonomy": _resolve(root, blocker_taxonomy),
    }
    reports = {name: _read_json(path) for name, path in paths.items()}
    evaluation = evaluate_manual_review_packet(reports)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated,
        "status": evaluation.status,
        "asset": "us_equity",
        "strategy_id": STRATEGY_ID,
        "decision": evaluation.decision,
        "review_items": evaluation.review_items,
        "remediation_tickets": evaluation.remediation_tickets,
        "forward_review_progress": evaluation.forward_review_progress,
        "review_milestones": evaluation.review_milestones,
        "evidence_checklist": evaluation.evidence_checklist,
        "signoff_requirements": evaluation.signoff_requirements,
        "paper_or_live_unlock_decision": evaluation.paper_or_live_unlock_decision,
        "blockers": evaluation.blockers,
        "unsafe_flags": evaluation.unsafe_flags,
        "guardrails": evaluation.guardrails,
        "source_reports": {name: _relpath(path, root) for name, path in paths.items()},
        "outputs": {
            "json": _relpath(_resolve(root, output), root),
            "markdown": _relpath(_resolve(root, markdown_output), root),
        },
    }
    _write_json(_resolve(root, output), payload)
    _write_text(_resolve(root, markdown_output), _markdown(payload))
    return payload


def _markdown(payload: Mapping[str, Any]) -> str:
    remediation = _mapping(payload.get("remediation_tickets"))
    progress = _mapping(payload.get("forward_review_progress"))
    lines = [
        "# US Equity 人工审阅包",
        "",
        f"生成时间：`{payload.get('generated_at', '')}`",
        f"- 状态：`{payload.get('status', '')}`",
        f"- 决策：`{payload.get('decision', '')}`",
        f"- remediation tickets：`{remediation.get('ticket_count')}`",
        "",
        "该审阅包只汇总证据，不解锁纸面模拟或实盘。",
        "",
        "## Forward Review Progress",
        "",
        f"- observation days：`{progress.get('observation_days')}` / `{progress.get('minimum_complete_days')}`",
        f"- next milestone：`{progress.get('next_milestone')}`",
        f"- days until minimum：`{progress.get('days_until_minimum')}`",
        f"- manual review required：`{progress.get('manual_review_required')}`",
        f"- paper/live unlock allowed：`{progress.get('paper_or_live_unlock_allowed')}`",
        "",
        "## Review Items",
        "",
    ]
    for name, item in _mapping(payload.get("review_items")).items():
        review_item = _mapping(item)
        lines.append(
            f"- `{name}`：status=`{review_item.get('status', '')}`；action={review_item.get('required_action', '')}"
        )
    lines += ["", "## Evidence Checklist", ""]
    for item in _list(payload.get("evidence_checklist")):
        check = _mapping(item)
        lines.append(f"- `{check.get('check_id')}`：passed=`{check.get('passed')}`")
    lines += ["", "## Signoff Requirements", ""]
    for item in _list(payload.get("signoff_requirements")):
        requirement = _mapping(item)
        lines.append(
            f"- `{requirement.get('signoff_id')}`：required=`{requirement.get('required')}`，"
            f"recorded=`{requirement.get('recorded')}`"
        )
    lines += ["", "## Remediation Tickets", ""]
    tickets = [item for item in _list(remediation.get("tickets")) if isinstance(item, Mapping)]
    if tickets:
        for ticket in tickets:
            lines.append(
                f"- `{ticket.get('ticket_id')}`：`{ticket.get('status')}`，owner=`{ticket.get('owner')}`，"
                f"dependency=`{ticket.get('dependency_type')}`"
            )
    else:
        lines.append("- None")
    lines += ["", "## Blockers", ""]
    blockers = _list(payload.get("blockers"))
    lines.extend((f"- `{blocker}`" for blocker in blockers) if blockers else ["- 无"])
    return "\n".join(lines)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return {"schema_version": "unreadable", "read_error": type(exc).__name__}
    return dict(payload) if isinstance(payload, Mapping) else {"schema_version": "unreadable"}


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(
            json.dumps(dict(payload), indent=2, sort_keys=True, ensure_ascii=False, default=str) + "\n",
            encoding="utf-8",
        )
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


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _relpath(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _utc_z_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
