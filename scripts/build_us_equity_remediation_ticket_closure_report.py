#!/usr/bin/env python3
"""Build the US equity remediation-ticket closure report.

The blocker taxonomy creates tickets; this report checks whether each ticket's
acceptance evidence is satisfied by current machine-readable reports. It is a
governance artifact only and never unlocks paper/live execution.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


SCHEMA_VERSION = "us_equity_remediation_ticket_closure_report_v1"
DEFAULT_OUTPUT = Path("artifacts/us_equity_strategy_production_line/latest/us_equity_remediation_ticket_closure_report.json")
DEFAULT_MARKDOWN_OUTPUT = Path("../学习资料/量化交易业务闭环/系统评估/US Equity Remediation Ticket Closure.md")
DEFAULT_TAXONOMY = Path("artifacts/us_equity_strategy_production_line/latest/us_equity_blocker_taxonomy_report.json")
DEFAULT_MANUAL_REVIEW = Path("artifacts/us_equity_etf_macro_rotation/latest/us_equity_manual_review_packet.json")
DEFAULT_PAPER_READINESS = Path("artifacts/us_equity_etf_macro_rotation/latest/us_equity_paper_simulation_readiness_report.json")
DEFAULT_LIVE_READINESS = Path("artifacts/us_equity_etf_macro_rotation/latest/us_equity_live_readiness_report.json")
DEFAULT_PIT_INTAKE = Path("artifacts/us_equity_data_lineage/latest/us_equity_pit_data_intake_status_report.json")
DEFAULT_PIT_ACCEPTANCE = Path("artifacts/us_equity_data_lineage/latest/us_equity_pit_bundle_acceptance_run_report.json")
DEFAULT_VENDOR_DROP_PIPELINE = Path("artifacts/us_equity_data_lineage/latest/us_equity_vendor_drop_pipeline_run_report.json")
DEFAULT_FORWARD_EVALUATION = Path("artifacts/us_equity_etf_macro_rotation/latest/us_etf_forward_observation_evaluation_report.json")
DEFAULT_STRATEGY_VALIDATION = Path("artifacts/us_equity_etf_macro_rotation/latest/us_etf_strategy_validation_gate_report.json")
DEFAULT_BROKER_HANDOFF = Path("artifacts/us_equity_etf_macro_rotation/latest/us_equity_broker_credentials_operator_handoff.json")
DEFAULT_BROKER_REVIEW = Path("artifacts/us_equity_etf_macro_rotation/latest/us_equity_broker_credentials_review_report.json")

ALLOWED_STATUSES = {
    "remediation_tickets_open",
    "remediation_tickets_closed",
    "remediation_ticket_closure_source_missing",
}


def build_us_equity_remediation_ticket_closure_report(
    *,
    repo_root: Path | None = None,
    output: Path = DEFAULT_OUTPUT,
    markdown_output: Path = DEFAULT_MARKDOWN_OUTPUT,
    taxonomy: Path = DEFAULT_TAXONOMY,
    manual_review: Path = DEFAULT_MANUAL_REVIEW,
    paper_readiness: Path = DEFAULT_PAPER_READINESS,
    live_readiness: Path = DEFAULT_LIVE_READINESS,
    pit_intake: Path = DEFAULT_PIT_INTAKE,
    pit_acceptance: Path = DEFAULT_PIT_ACCEPTANCE,
    vendor_drop_pipeline: Path = DEFAULT_VENDOR_DROP_PIPELINE,
    forward_evaluation: Path = DEFAULT_FORWARD_EVALUATION,
    strategy_validation: Path = DEFAULT_STRATEGY_VALIDATION,
    broker_handoff: Path = DEFAULT_BROKER_HANDOFF,
    broker_review: Path = DEFAULT_BROKER_REVIEW,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at or _utc_z_now()
    paths = {
        "taxonomy": _resolve(root, taxonomy),
        "manual_review": _resolve(root, manual_review),
        "paper_readiness": _resolve(root, paper_readiness),
        "live_readiness": _resolve(root, live_readiness),
        "pit_intake": _resolve(root, pit_intake),
        "pit_acceptance": _resolve(root, pit_acceptance),
        "vendor_drop_pipeline": _resolve(root, vendor_drop_pipeline),
        "forward_evaluation": _resolve(root, forward_evaluation),
        "strategy_validation": _resolve(root, strategy_validation),
        "broker_handoff": _resolve(root, broker_handoff),
        "broker_review": _resolve(root, broker_review),
    }
    reports = {name: _read_json(path) for name, path in paths.items()}
    missing_sources = [name for name, path in paths.items() if not path.exists()]
    tickets = [dict(item) for item in _list(reports["taxonomy"].get("remediation_tickets")) if isinstance(item, Mapping)]

    closure_checks = [_closure_check(ticket, reports) for ticket in tickets]
    closed_count = sum(1 for item in closure_checks if item["closed"])
    open_count = len(closure_checks) - closed_count
    closure_progress = _closure_progress(closure_checks)
    unsafe = _unsafe_flags(reports)
    summary = _summary(
        tickets=tickets,
        closure_checks=closure_checks,
        missing_sources=missing_sources,
        unsafe_flags=unsafe,
    )

    if missing_sources:
        status = "remediation_ticket_closure_source_missing"
    elif open_count:
        status = "remediation_tickets_open"
    else:
        status = "remediation_tickets_closed"
    blockers: list[str] = []
    if missing_sources:
        blockers.extend(f"us_equity_remediation_ticket_closure_source_missing:{name}" for name in missing_sources)
    blockers.extend(
        f"us_equity_remediation_ticket_open:{item['ticket_id']}"
        for item in closure_checks
        if item["closed"] is not True
    )
    blockers.extend(f"unsafe_flag:{item}" for item in unsafe)

    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated,
        "commit": _git(["rev-parse", "--short", "HEAD"], cwd=root),
        "branch": _git(["branch", "--show-current"], cwd=root),
        "asset": "us_equity",
        "status": status,
        "allowed_statuses": sorted(ALLOWED_STATUSES),
        "decision": "keep_paper_live_locked_until_all_remediation_tickets_close",
        "summary": summary,
        "ticket_count": len(tickets),
        "closed_count": closed_count,
        "open_count": open_count,
        "closure_progress": closure_progress,
        "missing_sources": missing_sources,
        "closure_checks": closure_checks,
        "blockers": _dedupe(blockers),
        "unsafe_flags": unsafe,
        "source_reports": {name: _relpath(path, root) for name, path in paths.items()},
        "guardrails": {
            "closure_report_only": True,
            "strategy_parameters_mutated": False,
            "paper_or_live_unlock_allowed": False,
            "paper_simulation_allowed": False,
            "live_order_allowed": False,
            "private_endpoint_allowed": False,
            "order_endpoint_allowed": False,
            "real_order_submitted": False,
            "broker_calls_used": False,
        },
        "outputs": {
            "json": _relpath(_resolve(root, output), root),
            "markdown": _relpath(_resolve(root, markdown_output), root),
        },
    }
    if payload["status"] not in ALLOWED_STATUSES:
        raise AssertionError(f"invalid remediation closure status: {payload['status']}")
    _write_json(_resolve(root, output), payload)
    _write_text(_resolve(root, markdown_output), _markdown(payload))
    return payload


def _summary(
    *,
    tickets: list[Mapping[str, Any]],
    closure_checks: list[Mapping[str, Any]],
    missing_sources: list[str],
    unsafe_flags: list[str],
) -> dict[str, Any]:
    by_dependency = _dependency_counts(tickets)
    by_category = _category_open_counts(closure_checks)
    open_checks = [item for item in closure_checks if item.get("closed") is not True]
    return {
        "ticket_count": len(closure_checks),
        "open_count": len(open_checks),
        "closed_count": len(closure_checks) - len(open_checks),
        "missing_source_count": len(missing_sources),
        "unsafe_flag_count": len(unsafe_flags),
        "external_or_time_dependency_count": by_dependency["external_or_time_dependency_count"],
        "manual_dependency_count": by_dependency["manual_dependency_count"],
        "engineering_dependency_count": by_dependency["engineering_dependency_count"],
        "governance_dependency_count": by_dependency["governance_dependency_count"],
        "other_dependency_count": by_dependency["other_dependency_count"],
        "open_by_category": by_category,
        "first_open_ticket_id": str(open_checks[0].get("ticket_id", "")) if open_checks else "",
        "first_open_blocking_evidence": _list_of_str(open_checks[0].get("blocking_evidence"))[0] if open_checks and _list_of_str(open_checks[0].get("blocking_evidence")) else "",
        "paper_or_live_unlock_allowed": False,
        "live_order_allowed": False,
    }


def _dependency_counts(tickets: list[Mapping[str, Any]]) -> dict[str, int]:
    counts = {
        "external_or_time_dependency_count": 0,
        "manual_dependency_count": 0,
        "engineering_dependency_count": 0,
        "governance_dependency_count": 0,
        "other_dependency_count": 0,
    }
    for ticket in tickets:
        dependency = str(ticket.get("dependency_type", ""))
        if dependency in {"external_user_action", "natural_time"}:
            counts["external_or_time_dependency_count"] += 1
        elif dependency == "manual_review":
            counts["manual_dependency_count"] += 1
        elif dependency.startswith("engineering"):
            counts["engineering_dependency_count"] += 1
        elif dependency == "governance_dependency":
            counts["governance_dependency_count"] += 1
        else:
            counts["other_dependency_count"] += 1
    return counts


def _category_open_counts(closure_checks: list[Mapping[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in closure_checks:
        if item.get("closed") is True:
            continue
        category = str(item.get("category", "unknown"))
        counts[category] = counts.get(category, 0) + 1
    return dict(sorted(counts.items()))


def _closure_check(ticket: Mapping[str, Any], reports: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    category = str(ticket.get("category", "other"))
    checks = _category_checks(category, reports)
    closed = bool(checks) and all(item["passed"] for item in checks)
    return {
        "ticket_id": str(ticket.get("ticket_id", "")),
        "category": category,
        "source_ticket_status": str(ticket.get("status", "")),
        "closed": closed,
        "status": "closed" if closed else "open",
        "blocking_evidence": [item["evidence"] for item in checks if item["passed"] is not True],
        "acceptance_evidence": [item["evidence"] for item in checks],
        "source_reports": sorted({report for item in checks for report in item["source_reports"]}),
    }


def _closure_progress(closure_checks: list[Mapping[str, Any]]) -> dict[str, Any]:
    by_category: dict[str, dict[str, int]] = {}
    by_source_report: dict[str, int] = {}
    for item in closure_checks:
        category = str(item.get("category", "unknown"))
        bucket = by_category.setdefault(category, {"ticket_count": 0, "open_count": 0, "closed_count": 0})
        bucket["ticket_count"] += 1
        if item.get("closed") is True:
            bucket["closed_count"] += 1
        else:
            bucket["open_count"] += 1
        for report in _list_of_str(item.get("source_reports")):
            by_source_report[report] = by_source_report.get(report, 0) + 1
    open_tickets = [str(item.get("ticket_id", "")) for item in closure_checks if item.get("closed") is not True]
    closed_tickets = [str(item.get("ticket_id", "")) for item in closure_checks if item.get("closed") is True]
    return {
        "ticket_count": len(closure_checks),
        "open_count": len(open_tickets),
        "closed_count": len(closed_tickets),
        "open_ticket_ids": open_tickets,
        "closed_ticket_ids": closed_tickets,
        "by_category": dict(sorted(by_category.items())),
        "by_source_report": dict(sorted(by_source_report.items())),
        "all_tickets_closed": not open_tickets,
        "paper_or_live_unlock_allowed": False,
    }


def _category_checks(category: str, reports: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    if category == "external_data":
        return [
            _check(
                _status(reports["vendor_drop_pipeline"]) == "vendor_drop_pipeline_ready_for_manual_config_review",
                "us_equity_vendor_drop_pipeline_run_report.status == vendor_drop_pipeline_ready_for_manual_config_review",
                ["vendor_drop_pipeline"],
            ),
            _check(
                _status(reports["pit_intake"]) == "production_pit_data_intake_ready",
                "us_equity_pit_data_intake_status_report.status == production_pit_data_intake_ready",
                ["pit_intake"],
            ),
            _check(
                _status(reports["pit_acceptance"]) == "acceptance_ready_for_manual_config_apply",
                "us_equity_pit_bundle_acceptance_run_report.status == acceptance_ready_for_manual_config_apply",
                ["pit_acceptance"],
            ),
        ]
    if category == "natural_time":
        continuity_passed = _nested(reports["forward_evaluation"], "observation_continuity.passed")
        if continuity_passed is None:
            continuity_passed = _nested(reports["forward_evaluation"], "checks.ledger_consistency.passed")
        return [
            _check(
                _status(reports["forward_evaluation"]) == "forward_complete_for_manual_review",
                "us_etf_forward_observation_evaluation_report.status == forward_complete_for_manual_review",
                ["forward_evaluation"],
            ),
            _check(
                continuity_passed is True,
                "forward observation continuity or ledger consistency passed",
                ["forward_evaluation"],
            ),
        ]
    if category == "manual_review":
        blockers = _list_of_str(reports["manual_review"].get("blockers"))
        manual_blockers = [item for item in blockers if "manual" in item.lower() or "review" in item.lower()]
        return [
            _check(_status(reports["manual_review"]) == "manual_review_ready", "us_equity_manual_review_packet.status == manual_review_ready", ["manual_review"]),
            _check(not manual_blockers, "manual review blockers cleared", ["manual_review"]),
        ]
    if category == "execution_infra":
        gate_checks = _mapping(reports["live_readiness"].get("gate_checks"))
        return [
            _check(_status(reports["broker_handoff"]) == "broker_credentials_handoff_ready_for_manual_review", "us_equity_broker_credentials_operator_handoff.status == broker_credentials_handoff_ready_for_manual_review", ["broker_handoff"]),
            _check(_status(reports["broker_review"]) == "broker_credentials_review_proven", "us_equity_broker_credentials_review_report.status == broker_credentials_review_proven", ["broker_review"]),
            _check(gate_checks.get("broker_credentials_review_complete") is True, "broker_credentials_review_complete == true", ["live_readiness"]),
            _check(gate_checks.get("order_reconciliation_proven") is True, "order_reconciliation_proven == true", ["live_readiness"]),
            _check(gate_checks.get("kill_switch_drill_complete") is True, "kill_switch_drill_complete == true", ["live_readiness"]),
            _check(gate_checks.get("monitoring_and_alerting_proven") is True, "monitoring_and_alerting_proven == true", ["live_readiness"]),
        ]
    if category == "research_data_quality":
        return [
            _check(
                _status(reports["strategy_validation"]) == "validation_passed_for_forward_observation",
                "us_etf_strategy_validation_gate_report.status == validation_passed_for_forward_observation",
                ["strategy_validation"],
            )
        ]
    if category == "remediation_governance":
        blockers = (
            _list_of_str(reports["manual_review"].get("blockers"))
            + _list_of_str(reports["paper_readiness"].get("blockers"))
            + _list_of_str(reports["live_readiness"].get("blockers"))
        )
        remediation_blockers = [item for item in blockers if "remediation_tickets_open" in item]
        uncategorized = int(_nested(reports["taxonomy"], "summary.uncategorized_blockers", default=0) or 0)
        return [
            _check(not remediation_blockers, "manual/paper/live no longer report remediation_tickets_open blockers", ["manual_review", "paper_readiness", "live_readiness"]),
            _check(uncategorized == 0, "blocker taxonomy summary.uncategorized_blockers == 0", ["taxonomy"]),
        ]
    if category == "unsafe_flags":
        return [_check(not _unsafe_flags(reports), "all private/order/live flags remain false", list(reports))]
    uncategorized = int(_nested(reports["taxonomy"], "summary.uncategorized_blockers", default=0) or 0)
    return [_check(uncategorized == 0, "uncategorized blockers cleared or mapped", ["taxonomy"])]


def _check(passed: bool, evidence: str, source_reports: list[str]) -> dict[str, Any]:
    return {"passed": bool(passed), "evidence": evidence, "source_reports": source_reports}


def _unsafe_flags(reports: Mapping[str, Mapping[str, Any]]) -> list[str]:
    unsafe = []
    for report_name, report in reports.items():
        for path, value in _walk(report):
            key = path.split(".")[-1]
            if key in {
                "live_order_allowed",
                "paper_or_live_unlock_allowed",
                "paper_simulation_allowed",
                "private_endpoint_allowed",
                "private_endpoint_used",
                "order_endpoint_allowed",
                "order_endpoint_used",
                "real_order_submitted",
                "broker_calls_used",
            } and value is True:
                unsafe.append(f"{report_name}.{path}=true")
    return _dedupe(unsafe)


def _walk(value: Any, prefix: str = "") -> list[tuple[str, Any]]:
    if isinstance(value, Mapping):
        out: list[tuple[str, Any]] = []
        for key, item in value.items():
            out.extend(_walk(item, f"{prefix}.{key}" if prefix else str(key)))
        return out
    if isinstance(value, list):
        out = []
        for index, item in enumerate(value):
            out.extend(_walk(item, f"{prefix}.{index}"))
        return out
    return [(prefix, value)]


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


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


def _status(report: Mapping[str, Any]) -> str:
    return str(report.get("status", ""))


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _list_of_str(value: Any) -> list[str]:
    return [str(item) for item in value] if isinstance(value, list) else []


def _nested(payload: Mapping[str, Any], dotted: str, default: Any = None) -> Any:
    value: Any = payload
    for part in dotted.split("."):
        if not isinstance(value, Mapping) or part not in value:
            return default
        value = value[part]
    return value


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _git(args: list[str], *, cwd: Path) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=cwd, stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:
        return "unknown"


def _utc_z_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _markdown(payload: Mapping[str, Any]) -> str:
    progress = _mapping(payload.get("closure_progress"))
    summary = _mapping(payload.get("summary"))
    lines = [
        "# US Equity Remediation Ticket Closure",
        "",
        f"生成时间：`{payload.get('generated_at', '')}`",
        f"状态：`{payload.get('status', '')}`",
        f"票据：`{payload.get('closed_count')}` closed / `{payload.get('open_count')}` open",
        f"paper/live unlock allowed：`{progress.get('paper_or_live_unlock_allowed')}`",
        "",
        "## Summary",
        "",
        f"- missing sources：`{summary.get('missing_source_count')}`",
        f"- unsafe flags：`{summary.get('unsafe_flag_count')}`",
        f"- external/time dependencies：`{summary.get('external_or_time_dependency_count')}`",
        f"- manual dependencies：`{summary.get('manual_dependency_count')}`",
        f"- engineering dependencies：`{summary.get('engineering_dependency_count')}`",
        f"- governance dependencies：`{summary.get('governance_dependency_count')}`",
        f"- first open ticket：`{summary.get('first_open_ticket_id')}`",
        f"- first blocking evidence：`{summary.get('first_open_blocking_evidence')}`",
        "",
        "| ticket | category | status | blocking evidence |",
        "| --- | --- | --- | --- |",
    ]
    for item in _list(payload.get("closure_checks")):
        if not isinstance(item, Mapping):
            continue
        blockers = "; ".join(str(x) for x in _list(item.get("blocking_evidence"))) or ""
        lines.append(f"| `{item.get('ticket_id')}` | `{item.get('category')}` | `{item.get('status')}` | {blockers} |")
    lines.extend(
        [
            "",
            "## Guardrails",
            "",
            "- closure report only",
            "- paper_or_live_unlock_allowed=false",
            "- live_order_allowed=false",
            "- private_endpoint_allowed=false",
            "",
        ]
    )
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN_OUTPUT)
    parser.add_argument("--generated-at", default="")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    payload = build_us_equity_remediation_ticket_closure_report(
        repo_root=args.repo_root,
        output=args.output,
        markdown_output=args.markdown_output,
        generated_at=args.generated_at or None,
    )
    print(json.dumps({"status": payload["status"], "output": payload["outputs"]["json"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
