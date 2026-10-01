#!/usr/bin/env python3
"""Build a categorized blocker taxonomy for the US equity production line."""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


SCHEMA_VERSION = "us_equity_blocker_taxonomy_report_v1"
DEFAULT_OUTPUT = Path("artifacts/us_equity_strategy_production_line/latest/us_equity_blocker_taxonomy_report.json")
DEFAULT_MARKDOWN_OUTPUT = Path("../学习资料/量化交易业务闭环/系统评估/US Equity 阻断项分层报告.md")
DEFAULT_DEVELOPMENT_AUDIT = Path("artifacts/us_equity_strategy_production_line/latest/us_equity_development_plan_audit_report.json")
DEFAULT_LIVE_READINESS = Path("artifacts/us_equity_etf_macro_rotation/latest/us_equity_live_readiness_report.json")
DEFAULT_FORWARD_EVALUATION = Path("artifacts/us_equity_etf_macro_rotation/latest/us_etf_forward_observation_evaluation_report.json")
DEFAULT_PIT_HANDOFF = Path("artifacts/us_equity_data_lineage/latest/us_equity_pit_operator_handoff_summary.json")
DEFAULT_BROKER_HANDOFF = Path("artifacts/us_equity_etf_macro_rotation/latest/us_equity_broker_credentials_operator_handoff.json")
DEFAULT_EXECUTION_EVIDENCE = Path("artifacts/us_equity_etf_macro_rotation/latest/us_equity_execution_drill_evidence_report.json")
DEFAULT_DAILY_LINE = Path("artifacts/us_equity_strategy_production_line/latest/us_equity_daily_production_line_run_report.json")

CATEGORIES = {
    "external_data": {
        "label": "External production PIT data",
        "keywords": (
            "production_bundle",
            "provider_required",
            "provider_",
            "point_in_time",
            "membership",
            "delisting",
            "corporate_action",
            "adjustment_reproducibility",
            "adjustment_replay",
            "identifier_mapping",
            "survivorship",
            "split",
            "dividend",
            "symbol_change",
            "macro_release",
            "pit_intake",
            "pit_bundle",
            "pit_acceptance",
            "production_pit",
            "source_dir",
            "source_delisted",
            "source_symbol_mapping",
            "source_type",
            "source_provider",
            "sample_start",
            "sample_end",
            "adjustment_mode",
            "universe_snapshot",
            "vendor_drop",
            "bundle",
            "local_csv",
            "license",
            "promotion_clean",
            "remediation_required",
        ),
    },
    "natural_time": {
        "label": "Forward observation time",
        "keywords": ("forward_observation_less_than_30_days", "forward_observation_not_complete", "observation"),
    },
    "manual_review": {
        "label": "Manual review and sign-off",
        "keywords": ("manual_review", "manual_reviewer", "manual_approval", "reviewer", "signoff"),
    },
    "execution_infra": {
        "label": "Execution infrastructure evidence",
        "keywords": ("broker_credentials", "order_reconciliation", "kill_switch", "monitoring_and_alerting"),
    },
    "research_data_quality": {
        "label": "Research validation data quality",
        "keywords": ("strategy_validation", "data_quality", "data_not_promotion_clean", "data_lineage_not_promotion_clean"),
    },
    "remediation_governance": {
        "label": "Open remediation-ticket governance",
        "keywords": (
            "remediation_tickets_open",
            "daily_production_line_not_pass",
            "daily_step_not_safe",
            "schema_audit_action_required",
            "schema_audit_not_pass",
            "standard_schema",
            "production_control_health",
        ),
    },
    "unsafe_flags": {
        "label": "Unsafe endpoint/live flags",
        "keywords": ("unsafe_flag", "live_order_allowed=true", "order_endpoint", "private_endpoint"),
    },
}


def build_us_equity_blocker_taxonomy_report(
    *,
    repo_root: Path | None = None,
    output: Path = DEFAULT_OUTPUT,
    markdown_output: Path = DEFAULT_MARKDOWN_OUTPUT,
    development_audit: Path = DEFAULT_DEVELOPMENT_AUDIT,
    live_readiness: Path = DEFAULT_LIVE_READINESS,
    forward_evaluation: Path = DEFAULT_FORWARD_EVALUATION,
    pit_handoff: Path = DEFAULT_PIT_HANDOFF,
    broker_handoff: Path = DEFAULT_BROKER_HANDOFF,
    execution_evidence: Path = DEFAULT_EXECUTION_EVIDENCE,
    daily_line: Path = DEFAULT_DAILY_LINE,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at or _utc_z_now()
    paths = {
        "development_audit": _resolve(root, development_audit),
        "live_readiness": _resolve(root, live_readiness),
        "forward_evaluation": _resolve(root, forward_evaluation),
        "pit_handoff": _resolve(root, pit_handoff),
        "broker_handoff": _resolve(root, broker_handoff),
        "execution_evidence": _resolve(root, execution_evidence),
        "daily_line": _resolve(root, daily_line),
    }
    reports = {name: _read_json(path) for name, path in paths.items()}

    blocker_sources = _collect_blockers(reports)
    categories = _categorize(blocker_sources)
    uncategorized = [
        item for item in blocker_sources if item["category"] == "other"
    ]
    actionable_now = [
        row
        for row in categories
        if row["category"] in {"manual_review", "execution_infra", "research_data_quality", "remediation_governance", "unsafe_flags"}
        and row["blocker_count"] > 0
    ]
    waiting_on = [
        row
        for row in categories
        if row["category"] in {"external_data", "natural_time"} and row["blocker_count"] > 0
    ]

    status = "blocked_external_and_time_dependencies" if waiting_on else "actionable_engineering_review"
    if not blocker_sources:
        status = "no_blockers_detected"
    remediation_tickets = _remediation_tickets(categories, reports)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated,
        "commit": _git(["rev-parse", "--short", "HEAD"], cwd=root),
        "branch": _git(["branch", "--show-current"], cwd=root),
        "asset": "us_equity",
        "status": status,
        "decision": "continue_fail_closed_development_do_not_unlock_paper_or_live",
        "summary": {
            "total_blockers": len(blocker_sources),
            "categorized_blockers": len(blocker_sources) - len(uncategorized),
            "uncategorized_blockers": len(uncategorized),
            "waiting_category_count": len(waiting_on),
            "actionable_category_count": len(actionable_now),
            "remediation_ticket_count": len(remediation_tickets),
        },
        "categories": categories,
        "waiting_on": waiting_on,
        "actionable_now": actionable_now,
        "uncategorized": uncategorized,
        "remediation_tickets": remediation_tickets,
        "operator_next_actions": _operator_next_actions(reports),
        "source_reports": {name: _relpath(path, root) for name, path in paths.items()},
        "guardrails": {
            "taxonomy_only": True,
            "strategy_parameters_mutated": False,
            "paper_or_live_unlock_allowed": False,
            "paper_simulation_allowed": False,
            "live_order_allowed": False,
            "private_endpoint_allowed": False,
            "order_endpoint_allowed": False,
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


def _collect_blockers(reports: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for report_name, report in reports.items():
        for blocker in _list_of_str(report.get("blockers")):
            rows.append(
                {
                    "source_report": report_name,
                    "source_path": "blockers",
                    "blocker": blocker,
                    "category": _category_for(blocker),
                }
            )
    return _dedupe_rows(rows)


def _categorize(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    by_category: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_category.setdefault(str(row["category"]), []).append(row)
    ordered = list(CATEGORIES) + ["other"]
    for category in ordered:
        items = by_category.get(category, [])
        out.append(
            {
                "category": category,
                "label": CATEGORIES.get(category, {"label": "Other"})["label"],
                "blocker_count": len(items),
                "blockers": [item["blocker"] for item in items],
                "blocker_details": items,
                "source_reports": sorted(
                    {
                        report
                        for item in items
                        for report in item.get("source_reports", [])
                    }
                ),
                "next_action": _next_action(category),
            }
        )
    return out


def _category_for(blocker: str) -> str:
    lowered = blocker.lower()
    for category, spec in CATEGORIES.items():
        if any(keyword in lowered for keyword in spec["keywords"]):
            return category
    return "other"


def _next_action(category: str) -> str:
    return {
        "external_data": "Place the six licensed production PIT CSV files into the manual vendor drop directory, confirm license review, then run the fail-closed vendor-drop pipeline.",
        "natural_time": "Keep forward observation running until the minimum observation window is complete; do not reset strategy parameters.",
        "manual_review": "Record explicit manual reviewer/sign-off only after strategy, data, forward observation, and risk evidence are ready.",
        "execution_infra": "Complete the broker credential local review via the broker handoff, then rerun execution evidence; order reconciliation, kill switch, and monitoring drills must remain proven.",
        "research_data_quality": "Resolve production PIT/data-lineage blockers before treating strategy validation as passed.",
        "remediation_governance": "Rerun blocker taxonomy, remediation ticket closure, manual review, paper readiness, and live readiness after upstream evidence changes; close this ticket only when remediation_tickets_open blockers are absent and uncategorized_blockers == 0.",
        "unsafe_flags": "Repair any unsafe live/private/order flags immediately; no paper/live unlock is allowed.",
        "other": "Inspect these blockers manually and either map them into a category or create a dedicated remediation ticket.",
    }.get(category, "Inspect manually.")


def _remediation_tickets(categories: list[dict[str, Any]], reports: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "ticket_id": f"us_equity_remediate_{row['category']}",
            "category": row["category"],
            "owner": _owner_for(str(row["category"])),
            "dependency_type": _dependency_type_for(str(row["category"])),
            "status": _ticket_status_for(str(row["category"]), reports),
            "blocker_count": row["blocker_count"],
            "source_reports": _ticket_source_reports(str(row["category"]), _list_of_str(row.get("source_reports")), reports),
            "next_action": row["next_action"],
            "acceptance_evidence": _acceptance_evidence_for(str(row["category"])),
        }
        for row in categories
        if int(row.get("blocker_count", 0) or 0) > 0
    ]


def _owner_for(category: str) -> str:
    return {
        "external_data": "operator_data_vendor",
        "natural_time": "daily_forward_observation_scheduler",
        "manual_review": "human_reviewer",
        "execution_infra": "execution_engineering",
        "research_data_quality": "research_data_engineering",
        "remediation_governance": "quant_architect",
        "unsafe_flags": "safety_engineering",
        "other": "quant_architect",
    }.get(category, "quant_architect")


def _dependency_type_for(category: str) -> str:
    return {
        "external_data": "external_user_action",
        "natural_time": "natural_time",
        "manual_review": "manual_review",
        "execution_infra": "engineering",
        "research_data_quality": "engineering_after_data",
        "remediation_governance": "governance_dependency",
        "unsafe_flags": "safety_repair",
        "other": "manual_triage",
    }.get(category, "manual_triage")


def _ticket_status_for(category: str, reports: Mapping[str, Mapping[str, Any]] | None = None) -> str:
    reports = reports or {}
    if category == "execution_infra":
        execution_evidence = reports.get("execution_evidence", {})
        broker_handoff = reports.get("broker_handoff", {})
        if execution_evidence.get("status") == "execution_drill_evidence_partial" and int(
            execution_evidence.get("proven_count", 0) or 0
        ) > 0:
            return "waiting_broker_local_review"
        if any("broker_credentials" in item for item in _list_of_str(broker_handoff.get("blockers"))):
            return "waiting_broker_local_review"
        return "not_started"
    return {
        "external_data": "waiting_external_input",
        "natural_time": "waiting_observation_window",
        "manual_review": "blocked_until_upstream_ready",
        "research_data_quality": "blocked_by_data_quality",
        "remediation_governance": "waiting_upstream_ticket_closure",
        "unsafe_flags": "requires_immediate_repair",
        "other": "needs_triage",
    }.get(category, "needs_triage")


def _ticket_source_reports(category: str, source_reports: list[str], reports: Mapping[str, Mapping[str, Any]]) -> list[str]:
    out = list(source_reports)
    if category == "execution_infra" and reports.get("execution_evidence", {}).get("status"):
        out.append("execution_evidence")
    return sorted(set(out))


def _acceptance_evidence_for(category: str) -> list[str]:
    return {
        "external_data": [
            "us_equity_vendor_drop_pipeline_run_report.status == vendor_drop_pipeline_ready_for_manual_config_review",
            "us_equity_pit_data_intake_status_report.status == production_pit_data_intake_ready",
            "us_equity_pit_bundle_acceptance_run_report.status == acceptance_ready_for_manual_config_apply",
        ],
        "natural_time": [
            "us_etf_forward_observation_evaluation_report.status == forward_complete_for_manual_review",
            "observation_continuity.passed == true",
        ],
        "manual_review": [
            "us_equity_manual_review_packet.status == manual_review_ready",
            "manual reviewer records explicit sign-off outside automated gates",
        ],
        "execution_infra": [
            "us_equity_broker_credentials_operator_handoff.status == broker_credentials_handoff_ready_for_manual_review",
            "us_equity_broker_credentials_review_report.status == broker_credentials_review_proven",
            "order reconciliation, kill switch, and monitoring drills proven before live gate",
        ],
        "research_data_quality": [
            "us_etf_strategy_validation_gate_report.status == validation_passed_for_forward_observation",
            "production PIT/data-lineage blockers cleared",
        ],
        "remediation_governance": [
            "manual review, paper readiness, and live readiness no longer report remediation_tickets_open blockers",
            "blocker taxonomy has no uncategorized blockers",
        ],
        "unsafe_flags": [
            "all private/order/live flags remain false",
            "no real orders submitted",
        ],
        "other": ["category mapping or dedicated remediation ticket added"],
    }.get(category, ["manual triage completed"])


def _operator_next_actions(reports: Mapping[str, Mapping[str, Any]]) -> list[str]:
    actions = _list_of_str(reports.get("pit_handoff", {}).get("operator_next_actions"))
    actions.extend(_list_of_str(reports.get("broker_handoff", {}).get("operator_next_actions")))
    if actions:
        return _dedupe(actions)
    return [
        "Continue daily production-line runs while preserving fail-closed paper/live gates.",
        "Do not treat forward observation or live readiness reports as alpha validation.",
    ]


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


def _dedupe_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        blocker = str(row["blocker"])
        category = str(row["category"])
        key = (category, blocker)
        if key not in grouped:
            grouped[key] = {
                "blocker": blocker,
                "category": category,
                "source_reports": set(),
                "source_paths": set(),
            }
        grouped[key]["source_reports"].add(str(row["source_report"]))
        grouped[key]["source_paths"].add(f"{row['source_report']}:{row['source_path']}")
    return [
        {
            "blocker": item["blocker"],
            "category": item["category"],
            "source_reports": sorted(item["source_reports"]),
            "source_paths": sorted(item["source_paths"]),
        }
        for item in sorted(grouped.values(), key=lambda x: (str(x["category"]), str(x["blocker"])))
    ]


def _list_of_str(value: Any) -> list[str]:
    return [str(item) for item in value] if isinstance(value, list) else []


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(item for item in values if item))


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


def _git(args: list[str], *, cwd: Path) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=cwd, stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:
        return "unknown"


def _utc_z_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _markdown(payload: Mapping[str, Any]) -> str:
    lines = [
        "# US Equity 阻断项分层报告",
        "",
        f"生成时间：`{payload.get('generated_at', '')}`",
        f"状态：`{payload.get('status', '')}`",
        f"决策：`{payload.get('decision', '')}`",
        "",
        "| 分类 | 数量 | 下一步 |",
        "| --- | ---: | --- |",
    ]
    for row in payload.get("categories", []):
        if not isinstance(row, Mapping) or int(row.get("blocker_count", 0) or 0) == 0:
            continue
        lines.append(f"| `{row.get('category')}` | `{row.get('blocker_count')}` | {row.get('next_action')} |")
    lines.extend(["", "## Operator Next Actions", ""])
    actions = _list_of_str(payload.get("operator_next_actions"))
    lines.extend(f"- {item}" for item in actions) if actions else lines.append("- None")
    lines.extend(["", "## Remediation Tickets", ""])
    tickets = [item for item in payload.get("remediation_tickets", []) if isinstance(item, Mapping)]
    if tickets:
        lines.extend(
            f"- `{item.get('ticket_id')}`：`{item.get('status')}`，owner=`{item.get('owner')}`，next={item.get('next_action')}"
            for item in tickets
        )
    else:
        lines.append("- None")
    lines.extend(["", "## Guardrails", "", "- taxonomy only", "- live_order_allowed=false", "- paper_or_live_unlock_allowed=false"])
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
    payload = build_us_equity_blocker_taxonomy_report(
        repo_root=args.repo_root,
        output=args.output,
        markdown_output=args.markdown_output,
        generated_at=args.generated_at or None,
    )
    print(json.dumps({"status": payload["status"], "output": payload["outputs"]["json"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
