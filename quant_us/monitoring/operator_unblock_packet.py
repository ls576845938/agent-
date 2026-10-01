"""Service rules for the US equity operator unblock packet."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


SCHEMA_VERSION = "us_equity_operator_unblock_packet_v1"
DEFAULT_NEXT_ACTION_QUEUE = Path("artifacts/us_equity_strategy_production_line/latest/us_equity_next_action_queue_report.json")
DEFAULT_PIT_DISCOVERY = Path("artifacts/us_equity_data_lineage/latest/us_equity_local_pit_file_discovery_report.json")
DEFAULT_PIT_PROCUREMENT = Path("artifacts/us_equity_data_lineage/latest/us_equity_pit_procurement_readiness_report.json")
DEFAULT_BROKER_HANDOFF = Path("artifacts/us_equity_etf_macro_rotation/latest/us_equity_broker_credentials_operator_handoff.json")
DEFAULT_BROKER_REVIEW = Path("artifacts/us_equity_etf_macro_rotation/latest/us_equity_broker_credentials_review_report.json")
DEFAULT_MANUAL_DECISION = Path("artifacts/us_equity_etf_macro_rotation/latest/us_equity_manual_decision_record_report.json")
DEFAULT_OUTPUT = Path("artifacts/us_equity_strategy_production_line/latest/us_equity_operator_unblock_packet.json")
DEFAULT_MARKDOWN_OUTPUT = Path("../学习资料/量化交易业务闭环/系统评估/US Equity 操作解锁包.md")


def build_us_equity_operator_unblock_packet(
    *,
    repo_root: Path | None = None,
    next_action_queue: Path = DEFAULT_NEXT_ACTION_QUEUE,
    pit_discovery: Path = DEFAULT_PIT_DISCOVERY,
    pit_procurement: Path = DEFAULT_PIT_PROCUREMENT,
    broker_handoff: Path = DEFAULT_BROKER_HANDOFF,
    broker_review: Path = DEFAULT_BROKER_REVIEW,
    manual_decision: Path = DEFAULT_MANUAL_DECISION,
    output: Path = DEFAULT_OUTPUT,
    markdown_output: Path = DEFAULT_MARKDOWN_OUTPUT,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at or _utc_z_now()
    paths = {
        "next_action_queue": _resolve(root, next_action_queue),
        "pit_discovery": _resolve(root, pit_discovery),
        "pit_procurement": _resolve(root, pit_procurement),
        "broker_handoff": _resolve(root, broker_handoff),
        "broker_review": _resolve(root, broker_review),
        "manual_decision": _resolve(root, manual_decision),
    }
    reports = {name: _read_json(path) for name, path in paths.items()}
    source_report_paths = {name: _relpath(path, root) for name, path in paths.items()}
    actions = [item for item in _list(reports["next_action_queue"].get("actions")) if isinstance(item, Mapping)]
    external = _external_inputs(reports["pit_discovery"], reports["pit_procurement"], actions, source_report_paths)
    manual = _manual_inputs(
        reports["broker_handoff"],
        reports["broker_review"],
        reports["manual_decision"],
        actions,
        source_report_paths,
    )
    natural_time = _natural_time_inputs(actions, source_report_paths)
    all_items = [*external, *manual, *natural_time]
    open_count = sum(1 for item in all_items if item["status"] == "open")
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated,
        "commit": _git(["rev-parse", "--short", "HEAD"], cwd=root),
        "branch": _git(["branch", "--show-current"], cwd=root),
        "asset": "us_equity",
        "status": "operator_unblock_open" if open_count else "operator_unblock_complete",
        "allowed_statuses": ["operator_unblock_open", "operator_unblock_complete"],
        "decision": "operator_inputs_required_keep_paper_live_locked" if open_count else "no_operator_inputs_pending",
        "summary": {
            "open_count": open_count,
            "external_input_count": len(external),
            "manual_input_count": len(manual),
            "natural_time_count": len(natural_time),
            "paper_or_live_unlock_allowed": False,
            "live_order_allowed": False,
        },
        "next_operator_action": all_items[0] if all_items else None,
        "external_inputs": external,
        "manual_inputs": manual,
        "natural_time_inputs": natural_time,
        "source_reports": {name: _relpath(path, root) for name, path in paths.items()},
        "guardrails": {
            "operator_packet_only": True,
            "files_copied": False,
            "local_review_mutated": False,
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
    _write_text(_resolve(root, markdown_output), markdown(payload))
    return payload


def _external_inputs(
    discovery: Mapping[str, Any],
    procurement: Mapping[str, Any],
    actions: list[Mapping[str, Any]],
    source_report_paths: Mapping[str, str],
) -> list[dict[str, Any]]:
    pit_action = _action_by_milestone(actions, "production_pit_data")
    missing = _list_of_str(discovery.get("missing_filenames"))
    ready = _list_of_str(discovery.get("ready_filenames"))
    blockers = _list_of_str(pit_action.get("blockers")) or missing
    if not blockers and not missing:
        return []
    acceptable_routes = [
        {"route_id": str(item.get("route_id", "")), "label": str(item.get("label", ""))}
        for item in _list(procurement.get("acceptable_source_routes"))
        if isinstance(item, Mapping)
    ]
    supplemental_boundaries = [
        {
            "route_id": str(item.get("route_id", "")),
            "label": str(item.get("label", "")),
            "not_sufficient_for": _list_of_str(item.get("not_sufficient_for")),
        }
        for item in _list(procurement.get("supplemental_source_routes"))
        if isinstance(item, Mapping)
    ]
    return [
        {
            "item_id": "production_pit_csv_drop",
            "category": "external_input",
            "status": "open",
            "owner": "operator_data_vendor",
            "title": "Place licensed production PIT CSV files",
            "reason": _first_blocker(blockers, "production_pit_data_missing"),
            "next_action": "Place licensed PIT CSV files, manually confirm license review, then rerun the vendor-drop pipeline.",
            "evidence_path": _action_evidence_path(pit_action, source_report_paths.get("pit_discovery", "")),
            "source_report": _action_source_report(pit_action, "pit_discovery"),
            "required_files": missing,
            "ready_files": ready,
            "acceptable_source_routes": acceptable_routes,
            "supplemental_source_boundaries": supplemental_boundaries,
            "blockers": blockers,
            "commands": [
                "python scripts/build_us_equity_local_pit_file_discovery_report.py --search-root <licensed_vendor_folder>",
                "python scripts/run_us_equity_vendor_drop_pipeline.py --license-reviewed",
            ],
        }
    ]


def _manual_inputs(
    broker_handoff: Mapping[str, Any],
    broker_review: Mapping[str, Any],
    manual_decision: Mapping[str, Any],
    actions: list[Mapping[str, Any]],
    source_report_paths: Mapping[str, str],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    broker_blockers = _dedupe([*_list_of_str(broker_handoff.get("blockers")), *_list_of_str(broker_review.get("blockers"))])
    if broker_blockers:
        broker_connectivity = _mapping(broker_handoff.get("broker_connectivity_evidence"))
        rows.append(
            {
                "item_id": "broker_credentials_local_review",
                "category": "manual_input",
                "status": "open",
                "owner": "human_operator",
                "title": "Complete broker credential local review without secrets",
                "reason": _first_blocker(broker_blockers, "broker_credentials_local_review_missing"),
                "next_action": "Record metadata-only broker review evidence in the ignored local review file and rerun the credential review report.",
                "evidence_path": source_report_paths.get("broker_review", ""),
                "source_report": "broker_review",
                "local_file": "configs/execution/us_equity_broker_credentials_review.local.json",
                "connectivity_evidence": broker_connectivity,
                "blockers": broker_blockers,
                "commands": [
                    "python scripts/init_us_equity_broker_credentials_local_review.py",
                    "python scripts/build_us_equity_broker_credentials_review_report.py",
                    "python scripts/run_us_equity_daily_production_line.py",
                ],
            }
        )
    manual_blockers = _list_of_str(manual_decision.get("blockers"))
    manual_action = _action_by_milestone(actions, "manual_review_signoff")
    if manual_blockers or manual_action:
        rows.append(
            {
                "item_id": "manual_strategy_decision_record",
                "category": "manual_input",
                "status": "open",
                "owner": "human_reviewer",
                "title": "Fill manual strategy decision record after evidence is ready",
                "reason": _first_blocker(
                    _dedupe([*manual_blockers, *_list_of_str(manual_action.get("blockers"))]),
                    "manual_strategy_decision_record_missing",
                ),
                "next_action": "After upstream evidence is ready, record the manual strategy decision locally and rebuild the review packet.",
                "evidence_path": _action_evidence_path(manual_action, source_report_paths.get("manual_decision", "")),
                "source_report": _action_source_report(manual_action, "manual_decision"),
                "local_file": "configs/reviews/us_equity_manual_decision_record.local.json",
                "blockers": _dedupe([*manual_blockers, *_list_of_str(manual_action.get("blockers"))]),
                "commands": [
                    "python scripts/init_us_equity_manual_decision_record_local.py",
                    "python scripts/build_us_equity_manual_decision_record_report.py",
                    "python scripts/build_us_equity_manual_review_packet.py",
                ],
            }
        )
    return rows


def _natural_time_inputs(actions: list[Mapping[str, Any]], source_report_paths: Mapping[str, str]) -> list[dict[str, Any]]:
    rows = []
    for milestone_id, title in (
        ("forward_observation_30d", "Continue forward observation to 30 valid days"),
        ("paper_simulation_evaluation", "Continue paper simulation after manual approval"),
    ):
        action = _action_by_milestone(actions, milestone_id)
        if not action:
            continue
        rows.append(
            {
                "item_id": milestone_id,
                "category": "natural_time",
                "status": "open",
                "owner": str(action.get("owner", "")),
                "title": title,
                "reason": _first_blocker(_list_of_str(action.get("blockers")), f"{milestone_id}_not_complete"),
                "next_action": str(action.get("instruction") or action.get("recommended_command") or title),
                "evidence_path": _action_evidence_path(action, source_report_paths.get("next_action_queue", "")),
                "source_report": _action_source_report(action, "next_action_queue"),
                "blockers": _list_of_str(action.get("blockers")),
                "commands": [str(action.get("recommended_command", ""))] if action.get("recommended_command") else [],
            }
        )
    return rows


def _action_by_milestone(actions: list[Mapping[str, Any]], milestone_id: str) -> Mapping[str, Any]:
    for action in actions:
        if action.get("milestone_id") == milestone_id:
            return action
    return {}


def _action_evidence_path(action: Mapping[str, Any], fallback: str) -> str:
    for record in _list(action.get("blocked_gate_records")):
        if isinstance(record, Mapping) and record.get("evidence_path"):
            return str(record.get("evidence_path"))
    return fallback


def _action_source_report(action: Mapping[str, Any], fallback: str) -> str:
    for record in _list(action.get("blocked_gate_records")):
        if isinstance(record, Mapping) and record.get("source_report"):
            return str(record.get("source_report"))
    return fallback


def _first_blocker(blockers: list[str], fallback: str) -> str:
    return blockers[0] if blockers else fallback


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return {"status": "unreadable_report", "blockers": [type(exc).__name__]}


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(payload), indent=2, sort_keys=True, ensure_ascii=False, default=str) + "\n", encoding="utf-8")


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content + "\n", encoding="utf-8")


def markdown(payload: Mapping[str, Any]) -> str:
    lines = [
        "# US Equity 操作解锁包",
        "",
        f"- generated_at: `{payload.get('generated_at')}`",
        f"- status: `{payload.get('status')}`",
        f"- open_count: `{_nested(payload, 'summary.open_count', 0)}`",
        "",
        "本报告只汇总人工、外部、自然时间输入，不解锁 paper/live。",
        "",
        "| category | item | owner | first blocker |",
        "| --- | --- | --- | --- |",
    ]
    for section in ("external_inputs", "manual_inputs", "natural_time_inputs"):
        for item in _list(payload.get(section)):
            if not isinstance(item, Mapping):
                continue
            blockers = _list_of_str(item.get("blockers"))
            lines.append(
                f"| `{item.get('category')}` | `{item.get('item_id')}` | `{item.get('owner')}` | `{blockers[0] if blockers else ''}` |"
            )
    for item in _list(payload.get("external_inputs")):
        if not isinstance(item, Mapping) or item.get("item_id") != "production_pit_csv_drop":
            continue
        lines.extend(["", "## Production PIT Source Boundaries", ""])
        routes = [route for route in _list(item.get("acceptable_source_routes")) if isinstance(route, Mapping)]
        if routes:
            lines.extend(["### Acceptable routes", ""])
            lines.extend([f"- `{route.get('route_id')}`: {route.get('label')}" for route in routes])
        boundaries = [route for route in _list(item.get("supplemental_source_boundaries")) if isinstance(route, Mapping)]
        if boundaries:
            lines.extend(["", "### Supplemental only", ""])
            for route in boundaries:
                lines.append(
                    f"- `{route.get('route_id')}`: not sufficient for `{', '.join(_list_of_str(route.get('not_sufficient_for'))[:2])}`"
                )
    lines.extend(["", "## Guardrails", "", "- files_copied=false", "- local_review_mutated=false", "- live_order_allowed=false"])
    return "\n".join(lines)


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _relpath(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list_of_str(value: Any) -> list[str]:
    return [str(item) for item in value if str(item)] if isinstance(value, list) else []


def _dedupe(items: list[str]) -> list[str]:
    return list(dict.fromkeys(item for item in items if item))


def _nested(value: Any, dotted: str, default: Any = "") -> Any:
    current = value
    for part in dotted.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return default
        current = current[part]
    return current


def _git(args: list[str], *, cwd: Path) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=cwd, stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:
        return "unknown"


def _utc_z_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
