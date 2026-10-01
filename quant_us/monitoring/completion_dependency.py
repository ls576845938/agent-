#!/usr/bin/env python3
"""Service rules for the US equity production-line dependency dashboard.

The CLI entrypoint should only parse arguments and call this module. Milestone
classification, blocker extraction, dependency grouping, and fail-closed
guardrails live here so the daily production line and tests share one rule set.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


SCHEMA_VERSION = "us_equity_completion_dependency_report_v1"
DEFAULT_OUTPUT = Path("artifacts/us_equity_strategy_production_line/latest/us_equity_completion_dependency_report.json")
DEFAULT_MARKDOWN_OUTPUT = Path("../学习资料/量化交易业务闭环/系统评估/US Equity 剩余依赖总控.md")
DEFAULT_PIT_PROCUREMENT_READINESS = Path("artifacts/us_equity_data_lineage/latest/us_equity_pit_procurement_readiness_report.json")
DEFAULT_PIT_STATUS = Path("artifacts/us_equity_data_lineage/latest/us_equity_pit_data_intake_status_report.json")
DEFAULT_PIT_ACCEPTANCE = Path("artifacts/us_equity_data_lineage/latest/us_equity_pit_bundle_acceptance_run_report.json")
DEFAULT_STRATEGY_VALIDATION = Path("artifacts/us_equity_etf_macro_rotation/latest/us_etf_strategy_validation_gate_report.json")
DEFAULT_STRATEGY_VALIDATION_EVIDENCE_AUDIT = Path("artifacts/us_equity_etf_macro_rotation/latest/us_etf_strategy_validation_evidence_audit.json")
DEFAULT_PORTFOLIO_PROMOTION = Path("artifacts/us_equity_portfolio/latest/portfolio_promotion_evidence_report.json")
DEFAULT_FORWARD_EVALUATION = Path("artifacts/us_equity_etf_macro_rotation/latest/us_etf_forward_observation_evaluation_report.json")
DEFAULT_MANUAL_REVIEW = Path("artifacts/us_equity_etf_macro_rotation/latest/us_equity_manual_review_packet.json")
DEFAULT_PAPER_READINESS = Path("artifacts/us_equity_etf_macro_rotation/latest/us_equity_paper_simulation_readiness_report.json")
DEFAULT_PAPER_EVALUATION = Path("artifacts/us_equity_etf_macro_rotation/latest/us_equity_paper_simulation_evaluation_report.json")
DEFAULT_EXECUTION_EVIDENCE = Path("artifacts/us_equity_etf_macro_rotation/latest/us_equity_execution_drill_evidence_report.json")
DEFAULT_BROKER_HANDOFF = Path("artifacts/us_equity_etf_macro_rotation/latest/us_equity_broker_credentials_operator_handoff.json")
DEFAULT_BROKER_REVIEW = Path("artifacts/us_equity_etf_macro_rotation/latest/us_equity_broker_credentials_review_report.json")
DEFAULT_LIVE_READINESS = Path("artifacts/us_equity_etf_macro_rotation/latest/us_equity_live_readiness_report.json")
DEFAULT_BLOCKER_TAXONOMY = Path("artifacts/us_equity_strategy_production_line/latest/us_equity_blocker_taxonomy_report.json")
DEFAULT_REMEDIATION_CLOSURE = Path("artifacts/us_equity_strategy_production_line/latest/us_equity_remediation_ticket_closure_report.json")
DEFAULT_VENDOR_DROP_PREFLIGHT = Path("artifacts/us_equity_data_lineage/latest/us_equity_vendor_drop_preflight_report.json")


def build_us_equity_completion_dependency_report(
    *,
    repo_root: Path | None = None,
    output: Path = DEFAULT_OUTPUT,
    markdown_output: Path = DEFAULT_MARKDOWN_OUTPUT,
    pit_procurement_readiness: Path = DEFAULT_PIT_PROCUREMENT_READINESS,
    pit_status: Path = DEFAULT_PIT_STATUS,
    pit_acceptance: Path = DEFAULT_PIT_ACCEPTANCE,
    strategy_validation: Path = DEFAULT_STRATEGY_VALIDATION,
    strategy_validation_evidence_audit: Path = DEFAULT_STRATEGY_VALIDATION_EVIDENCE_AUDIT,
    portfolio_promotion: Path = DEFAULT_PORTFOLIO_PROMOTION,
    forward_evaluation: Path = DEFAULT_FORWARD_EVALUATION,
    manual_review: Path = DEFAULT_MANUAL_REVIEW,
    paper_readiness: Path = DEFAULT_PAPER_READINESS,
    paper_evaluation: Path = DEFAULT_PAPER_EVALUATION,
    execution_evidence: Path = DEFAULT_EXECUTION_EVIDENCE,
    broker_handoff: Path = DEFAULT_BROKER_HANDOFF,
    broker_review: Path = DEFAULT_BROKER_REVIEW,
    live_readiness: Path = DEFAULT_LIVE_READINESS,
    blocker_taxonomy: Path = DEFAULT_BLOCKER_TAXONOMY,
    remediation_closure: Path = DEFAULT_REMEDIATION_CLOSURE,
    vendor_drop_preflight: Path = DEFAULT_VENDOR_DROP_PREFLIGHT,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at or _utc_z_now()
    paths = {
        "pit_procurement_readiness": _resolve(root, pit_procurement_readiness),
        "pit_status": _resolve(root, pit_status),
        "pit_acceptance": _resolve(root, pit_acceptance),
        "strategy_validation": _resolve(root, strategy_validation),
        "strategy_validation_evidence_audit": _resolve(root, strategy_validation_evidence_audit),
        "portfolio_promotion": _resolve(root, portfolio_promotion),
        "forward_evaluation": _resolve(root, forward_evaluation),
        "manual_review": _resolve(root, manual_review),
        "paper_readiness": _resolve(root, paper_readiness),
        "paper_evaluation": _resolve(root, paper_evaluation),
        "execution_evidence": _resolve(root, execution_evidence),
        "broker_handoff": _resolve(root, broker_handoff),
        "broker_review": _resolve(root, broker_review),
        "live_readiness": _resolve(root, live_readiness),
        "blocker_taxonomy": _resolve(root, blocker_taxonomy),
        "remediation_closure": _resolve(root, remediation_closure),
        "vendor_drop_preflight": _resolve(root, vendor_drop_preflight),
    }
    reports = {name: _read_json(path) for name, path in paths.items()}
    milestones = _milestones(reports)
    blockers = _dedupe(
        blocker
        for milestone in milestones
        if not milestone["passed"]
        for blocker in milestone["blockers"]
    )
    status = "completion_dependencies_blocked" if blockers else "completion_dependencies_satisfied"
    dependency_groups = _dependency_groups(milestones)
    primary_next_action = _primary_next_action(milestones)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated,
        "commit": _git(["rev-parse", "--short", "HEAD"], cwd=root),
        "branch": _git(["branch", "--show-current"], cwd=root),
        "asset": "us_equity",
        "status": status,
        "allowed_statuses": ["completion_dependencies_blocked", "completion_dependencies_satisfied"],
        "decision": "continue_fail_closed_until_all_dependencies_satisfied",
        "summary": {
            "milestone_count": len(milestones),
            "passed_count": sum(1 for item in milestones if item["passed"]),
            "blocked_count": sum(1 for item in milestones if not item["passed"]),
            "paper_or_live_unlock_allowed": False,
            "live_order_allowed": False,
        },
        "external_input_summary": _external_input_summary(reports),
        "dependency_groups": dependency_groups,
        "primary_next_action": primary_next_action,
        "milestones": milestones,
        "blockers": blockers,
        "operator_next_actions": _operator_next_actions(milestones, reports),
        "source_reports": {name: _relpath(path, root) for name, path in paths.items()},
        "guardrails": {
            "dependency_dashboard_only": True,
            "strategy_parameters_mutated": False,
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


def _milestones(reports: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    pit_procurement = reports.get("pit_procurement_readiness", {})
    pit_status = reports.get("pit_status", {})
    pit_acceptance = reports.get("pit_acceptance", {})
    strategy_validation = reports.get("strategy_validation", {})
    strategy_validation_evidence_audit = reports.get("strategy_validation_evidence_audit", {})
    portfolio_promotion = reports.get("portfolio_promotion", {})
    forward_evaluation = reports.get("forward_evaluation", {})
    manual_review = reports.get("manual_review", {})
    paper_readiness = reports.get("paper_readiness", {})
    paper_evaluation = reports.get("paper_evaluation", {})
    execution_evidence = reports.get("execution_evidence", {})
    broker_handoff = reports.get("broker_handoff", {})
    broker_review = reports.get("broker_review", {})
    live_readiness = reports.get("live_readiness", {})
    remediation_closure = reports.get("remediation_closure", {})
    return [
        _milestone(
            "production_pit_data",
            "Production PIT data intake and acceptance",
            pit_procurement.get("status") == "pit_procurement_ready_for_manual_license_review"
            and pit_status.get("status") == "production_pit_data_intake_ready"
            and pit_acceptance.get("status") == "acceptance_ready_for_manual_config_apply",
            [
                *(_list_of_str(pit_procurement.get("blockers"))),
                *(_list_of_str(pit_status.get("blockers"))),
                *(_list_of_str(pit_acceptance.get("blockers"))),
            ]
            or ["production_pit_data_not_ready"],
            ["pit_procurement_readiness", "pit_status", "pit_acceptance"],
            "Place licensed production PIT files, confirm license review, and run the fail-closed vendor-drop pipeline.",
        ),
        _milestone(
            "strategy_validation_gate",
            "Strategy validation gate",
            strategy_validation.get("status") == "validation_passed_for_forward_observation"
            and strategy_validation_evidence_audit.get("status") == "validation_evidence_audit_ready_for_forward_observation",
            [
                *(_list_of_str(strategy_validation.get("blockers"))),
                *(_list_of_str(strategy_validation_evidence_audit.get("blockers"))),
                *[
                    f"strategy_validation_requirement_incomplete:{item}"
                    for item in _list_of_str(strategy_validation_evidence_audit.get("incomplete_requirements"))
                ],
            ]
            or ["strategy_validation_not_passed"],
            ["strategy_validation", "strategy_validation_evidence_audit"],
            "Clear production PIT/data-lineage blockers and rerun the strategy validation gate.",
        ),
        _milestone(
            "portfolio_promotion_evidence",
            "Portfolio promotion evidence",
            portfolio_promotion.get("status") == "promotion_evidence_ready"
            and portfolio_promotion.get("promotion_ready") is True,
            _list_of_str(portfolio_promotion.get("blockers")) or ["portfolio_promotion_evidence_not_ready"],
            ["portfolio_promotion"],
            "Produce production portfolio promotion evidence: event ledger, event-driven flow, ledger PnL, construction controls, cost stress, walk-forward, and exposure checks.",
        ),
        _milestone(
            "forward_observation_30d",
            "Forward observation minimum window",
            forward_evaluation.get("status") == "forward_complete_for_manual_review",
            _list_of_str(forward_evaluation.get("blockers")) or ["forward_observation_less_than_30_days"],
            ["forward_evaluation"],
            "Keep the forward observation runner active until 30+ valid observation days are complete.",
        ),
        _milestone(
            "manual_review_signoff",
            "Manual review and sign-off",
            manual_review.get("status") == "manual_review_ready"
            and _nested(manual_review, "guardrails.manual_approval_recorded", False) is True
            and _nested(manual_review, "paper_or_live_unlock_decision.manual_review_can_unlock_live_by_itself", True) is False,
            _list_of_str(manual_review.get("blockers")) or ["manual_review_not_ready"],
            ["manual_review"],
            "Perform manual review only after upstream data, validation, and forward observation gates are ready.",
        ),
        _milestone(
            "paper_simulation_readiness",
            "Paper simulation readiness",
            paper_readiness.get("status") == "paper_simulation_ready_for_manual_start",
            _list_of_str(paper_readiness.get("blockers")) or ["paper_simulation_not_ready"],
            ["paper_readiness"],
            "Keep paper simulation blocked until remediation tickets close and manual review is ready.",
        ),
        _milestone(
            "paper_simulation_evaluation",
            "Paper simulation minimum window and ledger evaluation",
            paper_evaluation.get("status") == "paper_simulation_complete_for_manual_review",
            _list_of_str(paper_evaluation.get("blockers")) or ["paper_simulation_less_than_30_days_or_not_started"],
            ["paper_evaluation"],
            "After manual start, keep paper simulation running until 30+ valid paper days and ledger reconciliation are complete.",
        ),
        _milestone(
            "execution_infra_evidence",
            "Execution infrastructure evidence",
            execution_evidence.get("status") == "execution_drill_evidence_complete",
            _list_of_str(execution_evidence.get("blockers")) or ["execution_drill_evidence_not_complete"],
            ["execution_evidence"],
            "Complete broker credential review; order reconciliation, kill switch, and monitoring evidence must remain proven.",
        ),
        _milestone(
            "broker_credentials_review",
            "Broker credential local review",
            broker_handoff.get("status") == "broker_credentials_handoff_ready_for_manual_review"
            and broker_review.get("status") == "broker_credentials_review_proven",
            [*(_list_of_str(broker_handoff.get("blockers"))), *(_list_of_str(broker_review.get("blockers")))]
            or ["broker_credentials_review_not_proven"],
            ["broker_handoff", "broker_review"],
            "Fill the local broker review file without secrets and prove read-only/live-disabled order permissions.",
        ),
        _milestone(
            "live_readiness_risk_constitution",
            "Live readiness and risk constitution",
            live_readiness.get("status") == "live_readiness_ready_for_manual_review",
            _list_of_str(live_readiness.get("blockers")) or ["live_readiness_not_ready"],
            ["live_readiness"],
            "Keep live locked until risk limits, execution evidence, paper evidence, and manual sign-off are complete.",
        ),
        _milestone(
            "remediation_ticket_closure",
            "Remediation ticket closure",
            remediation_closure.get("status") == "remediation_tickets_closed",
            _list_of_str(remediation_closure.get("blockers")) or ["remediation_tickets_open"],
            ["blocker_taxonomy", "remediation_closure"],
            "Close every remediation ticket with source evidence; do not close by deleting blockers.",
        ),
    ]


def _external_input_summary(reports: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    vendor_preflight = reports.get("vendor_drop_preflight", {})
    missing_files = [item for item in _list(vendor_preflight.get("missing_required_files")) if isinstance(item, Mapping)]
    ready_files = [item for item in _list(vendor_preflight.get("ready_required_files")) if isinstance(item, Mapping)]
    operator_action = (
        "place_licensed_pit_csv_files_and_rerun_readiness"
        if missing_files or int(vendor_preflight.get("missing_file_count", 0) or 0) > 0
        else "rerun_incoming_drop_readiness"
    )
    return {
        "vendor_drop_preflight_status": vendor_preflight.get("status", ""),
        "required_file_count": vendor_preflight.get("required_file_count", 0),
        "missing_file_count": vendor_preflight.get("missing_file_count", len(missing_files)),
        "ready_file_count": vendor_preflight.get("ready_file_count", len(ready_files)),
        "missing_required_filenames": [str(item.get("filename")) for item in missing_files if item.get("filename")],
        "ready_required_filenames": [str(item.get("filename")) for item in ready_files if item.get("filename")],
        "required_operator_inputs": [_operator_input(item) for item in missing_files],
        "operator_command_sequence": _operator_command_sequence(operator_action),
        "operator_action": operator_action,
    }


def _operator_input(item: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "filename": str(item.get("filename", "")),
        "target_path": str(item.get("path", "")),
        "table": str(item.get("table", "")),
        "blocker": str(item.get("blocker", "")),
        "required_fields": _list_of_str(item.get("required_fields")),
    }


def _operator_command_sequence(operator_action: str) -> list[str]:
    if operator_action == "place_licensed_pit_csv_files_and_rerun_readiness":
        return [
            "python scripts/build_us_equity_manual_vendor_drop_package.py",
            "copy licensed PIT CSV files into data/external/us_equity_lineage/incoming/manual_vendor_drop",
            "manually confirm license review for the copied PIT CSV files",
            "python scripts/run_us_equity_vendor_drop_pipeline.py --license-reviewed",
        ]
    return [
        "manually confirm license review for the copied PIT CSV files",
        "python scripts/run_us_equity_vendor_drop_pipeline.py --license-reviewed",
    ]


def _milestone(
    milestone_id: str,
    label: str,
    passed: bool,
    blockers: list[str],
    source_reports: list[str],
    next_action: str,
) -> dict[str, Any]:
    dependency_type = _dependency_type_for(milestone_id)
    return {
        "milestone_id": milestone_id,
        "label": label,
        "dependency_type": dependency_type,
        "actionability": _actionability_for(dependency_type),
        "passed": bool(passed),
        "blockers": [] if passed else _dedupe(blockers),
        "source_reports": source_reports,
        "next_action": next_action,
    }


def _dependency_type_for(milestone_id: str) -> str:
    return {
        "production_pit_data": "external_input",
        "strategy_validation_gate": "engineering_after_data",
        "portfolio_promotion_evidence": "engineering_after_data",
        "forward_observation_30d": "natural_time",
        "manual_review_signoff": "manual_review",
        "paper_simulation_readiness": "engineering_after_review",
        "paper_simulation_evaluation": "natural_time",
        "execution_infra_evidence": "engineering",
        "broker_credentials_review": "manual_review",
        "live_readiness_risk_constitution": "governance",
        "remediation_ticket_closure": "governance",
    }.get(milestone_id, "governance")


def _actionability_for(dependency_type: str) -> str:
    return {
        "external_input": "waiting",
        "natural_time": "waiting",
        "manual_review": "manual",
        "engineering_after_data": "blocked_until_data",
        "engineering_after_review": "blocked_until_review",
        "engineering": "actionable",
        "governance": "blocked_until_upstream",
    }.get(dependency_type, "blocked_until_upstream")


def _dependency_groups(milestones: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    order = [
        "external_input",
        "natural_time",
        "manual_review",
        "engineering",
        "engineering_after_data",
        "engineering_after_review",
        "governance",
    ]
    rows = []
    for dependency_type in order:
        group = [item for item in milestones if item.get("dependency_type") == dependency_type]
        if not group:
            continue
        blocked = [item for item in group if item.get("passed") is not True]
        first_blockers = []
        for item in blocked:
            blockers = _list_of_str(item.get("blockers"))
            if blockers:
                first_blockers.append(blockers[0])
        rows.append(
            {
                "dependency_type": dependency_type,
                "actionability": _actionability_for(dependency_type),
                "milestone_count": len(group),
                "blocked_count": len(blocked),
                "passed_count": len(group) - len(blocked),
                "milestone_ids": [str(item.get("milestone_id")) for item in group],
                "first_blockers": _dedupe(first_blockers),
                "next_actions": _dedupe([str(item.get("next_action")) for item in blocked if item.get("next_action")]),
            }
        )
    return rows


def _primary_next_action(milestones: list[Mapping[str, Any]]) -> dict[str, Any] | None:
    for item in milestones:
        if item.get("passed") is True:
            continue
        blockers = _list_of_str(item.get("blockers"))
        return {
            "milestone_id": str(item.get("milestone_id", "")),
            "dependency_type": str(item.get("dependency_type", "")),
            "actionability": str(item.get("actionability", "")),
            "first_blocker": blockers[0] if blockers else "",
            "next_action": str(item.get("next_action", "")),
            "source_reports": _list_of_str(item.get("source_reports")),
        }
    return None


def _operator_next_actions(milestones: list[Mapping[str, Any]], reports: Mapping[str, Mapping[str, Any]]) -> list[str]:
    actions: list[str] = []
    actions.extend(str(item["next_action"]) for item in milestones if item.get("passed") is not True)
    for key in ("broker_handoff", "pit_status"):
        actions.extend(_list_of_str(reports.get(key, {}).get("operator_next_actions")))
    return _dedupe(actions)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(payload), indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content + "\n", encoding="utf-8")


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _relpath(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _list_of_str(value: Any) -> list[str]:
    return [str(item) for item in value if str(item)] if isinstance(value, list) else []


def _nested(value: Any, dotted: str, default: Any = "") -> Any:
    current = value
    for part in dotted.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return default
        current = current[part]
    return current


def _dedupe(items: Any) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = str(item)
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    return out


def _git(args: list[str], *, cwd: Path) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=cwd, stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:
        return "unknown"


def _utc_z_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _markdown(payload: Mapping[str, Any]) -> str:
    lines = [
        "# US Equity 剩余依赖总控",
        "",
        f"生成时间：`{payload.get('generated_at', '')}`",
        f"状态：`{payload.get('status', '')}`",
        f"决策：`{payload.get('decision', '')}`",
        "",
        "## External Input Summary",
        "",
    ]
    external = payload.get("external_input_summary")
    primary = payload.get("primary_next_action")
    if isinstance(primary, Mapping):
        lines.extend(
            [
                "## Primary Next Action",
                "",
                f"- milestone_id：`{primary.get('milestone_id')}`",
                f"- dependency_type：`{primary.get('dependency_type')}`",
                f"- actionability：`{primary.get('actionability')}`",
                f"- first_blocker：`{primary.get('first_blocker')}`",
                f"- next_action：{primary.get('next_action')}",
                "",
            ]
        )
    if isinstance(external, Mapping):
        lines.extend(
            [
                f"- vendor_drop_preflight_status：`{external.get('vendor_drop_preflight_status')}`",
                f"- required_file_count：`{external.get('required_file_count')}`",
                f"- missing_file_count：`{external.get('missing_file_count')}`",
                f"- missing_required_filenames：`{external.get('missing_required_filenames')}`",
                "",
            ]
        )
    lines.extend(
        [
        "| Milestone | Passed | First blocker | Next action |",
        "| --- | --- | --- | --- |",
        ]
    )
    for item in payload.get("milestones", []):
        if not isinstance(item, Mapping):
            continue
        blockers = _list_of_str(item.get("blockers"))
        lines.append(
            f"| `{item.get('milestone_id')}` | `{item.get('passed')}` | `{blockers[0] if blockers else ''}` | {item.get('next_action')} |"
        )
    lines.extend(["", "## Operator Next Actions", ""])
    actions = _list_of_str(payload.get("operator_next_actions"))
    lines.extend([f"- {item}" for item in actions] if actions else ["- None"])
    lines.extend(["", "## Guardrails", "", "- dashboard only", "- paper_or_live_unlock_allowed=false", "- live_order_allowed=false"])
    return "\n".join(lines)
