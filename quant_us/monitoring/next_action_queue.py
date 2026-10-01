"""Service rules for the US equity next-action queue report."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


SCHEMA_VERSION = "us_equity_next_action_queue_report_v1"
DEFAULT_COMPLETION_DEPENDENCY = Path(
    "artifacts/us_equity_strategy_production_line/latest/us_equity_completion_dependency_report.json"
)
DEFAULT_VENDOR_DROP_PREFLIGHT = Path("artifacts/us_equity_data_lineage/latest/us_equity_vendor_drop_preflight_report.json")
DEFAULT_PIT_FILE_DISCOVERY = Path("artifacts/us_equity_data_lineage/latest/us_equity_local_pit_file_discovery_report.json")
DEFAULT_OUTPUT = Path("artifacts/us_equity_strategy_production_line/latest/us_equity_next_action_queue_report.json")
DEFAULT_MARKDOWN_OUTPUT = Path("../学习资料/量化交易业务闭环/系统评估/US Equity 下一步执行队列.md")

MILESTONE_ORDER = {
    "production_pit_data": 10,
    "strategy_validation_gate": 20,
    "portfolio_promotion_evidence": 25,
    "forward_observation_30d": 30,
    "manual_review_signoff": 40,
    "paper_simulation_readiness": 50,
    "paper_simulation_evaluation": 55,
    "execution_infra_evidence": 60,
    "broker_credentials_review": 65,
    "live_readiness_risk_constitution": 80,
    "remediation_ticket_closure": 90,
}


def build_us_equity_next_action_queue_report(
    *,
    repo_root: Path | None = None,
    output: Path = DEFAULT_OUTPUT,
    markdown_output: Path = DEFAULT_MARKDOWN_OUTPUT,
    completion_dependency: Path = DEFAULT_COMPLETION_DEPENDENCY,
    vendor_drop_preflight: Path = DEFAULT_VENDOR_DROP_PREFLIGHT,
    pit_file_discovery: Path = DEFAULT_PIT_FILE_DISCOVERY,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at or _utc_z_now()
    completion_path = _resolve(root, completion_dependency)
    vendor_preflight_path = _resolve(root, vendor_drop_preflight)
    discovery_path = _resolve(root, pit_file_discovery)
    completion = _read_json(completion_path)
    vendor_preflight = _read_json(vendor_preflight_path)
    discovery = _read_json(discovery_path)
    actions = _build_actions(completion, vendor_preflight, discovery)
    open_actions = [item for item in actions if item["status"] == "open"]
    status = "next_actions_open" if open_actions else "next_actions_complete"
    parallel_tracks = _parallel_tracks(open_actions)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated,
        "commit": _git(["rev-parse", "--short", "HEAD"], cwd=root),
        "branch": _git(["branch", "--show-current"], cwd=root),
        "asset": "us_equity",
        "status": status,
        "allowed_statuses": ["next_actions_open", "next_actions_complete"],
        "decision": "execute_actions_in_order_keep_paper_live_locked",
        "summary": {
            "action_count": len(actions),
            "open_count": len(open_actions),
            "manual_required_count": sum(1 for item in open_actions if item["manual_required"]),
            "external_input_count": sum(1 for item in open_actions if item["dependency_type"] == "external_input"),
            "natural_time_count": sum(1 for item in open_actions if item["dependency_type"] == "natural_time"),
            "actionable_engineering_count": sum(1 for item in open_actions if item["actionability"] == "actionable"),
            "blocked_until_upstream_count": sum(
                1 for item in open_actions if str(item["actionability"]).startswith("blocked")
            ),
            "blocked_gate_record_count": sum(len(_list(item.get("blocked_gate_records"))) for item in open_actions),
            "paper_or_live_unlock_allowed": False,
            "live_order_allowed": False,
        },
        "next_action": open_actions[0] if open_actions else None,
        "parallel_tracks": parallel_tracks,
        "actions": actions,
        "source_reports": {
            "completion_dependency": _relpath(completion_path, root),
            "vendor_drop_preflight": _relpath(vendor_preflight_path, root),
            "pit_file_discovery": _relpath(discovery_path, root) if discovery_path.exists() else "",
        },
        "guardrails": {
            "queue_only": True,
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


def _build_actions(
    completion: Mapping[str, Any],
    vendor_preflight: Mapping[str, Any],
    discovery: Mapping[str, Any],
) -> list[dict[str, Any]]:
    milestones = [item for item in _list(completion.get("milestones")) if isinstance(item, Mapping)]
    source_report_paths = {
        str(key): str(value)
        for key, value in dict(completion.get("source_reports") or {}).items()
        if str(key) and str(value)
    }
    actions = [
        _action_for_milestone(item, vendor_preflight, discovery, source_report_paths)
        for item in milestones
        if item.get("passed") is not True
    ]
    return sorted(actions, key=lambda item: (item["priority"], item["action_id"]))


def _action_for_milestone(
    milestone: Mapping[str, Any],
    vendor_preflight: Mapping[str, Any],
    discovery: Mapping[str, Any],
    source_report_paths: Mapping[str, str],
) -> dict[str, Any]:
    milestone_id = str(milestone.get("milestone_id", "unknown"))
    spec = _spec_for(milestone_id)
    blockers = _list_of_str(milestone.get("blockers"))
    actionability = _actionability_for_action(milestone_id, milestone, spec, blockers)
    source_reports = _list_of_str(milestone.get("source_reports"))
    return {
        "action_id": f"us_equity_action_{milestone_id}",
        "priority": MILESTONE_ORDER.get(milestone_id, 999),
        "milestone_id": milestone_id,
        "title": spec["title"],
        "owner": spec["owner"],
        "dependency_type": spec["dependency_type"],
        "actionability": actionability,
        "status": "open",
        "manual_required": spec["manual_required"],
        "recommended_command": spec["recommended_command"],
        "instruction": spec["instruction"],
        "first_blocker": blockers[0] if blockers else "",
        "blockers": blockers,
        "blocked_gate_records": _blocked_gate_records(
            milestone=milestone,
            spec=spec,
            blockers=blockers,
            source_reports=source_reports,
            source_report_paths=source_report_paths,
        ),
        "evidence": _action_evidence(milestone, vendor_preflight, discovery),
        "unlocks": spec["unlocks"],
        "source_reports": source_reports,
    }


def _blocked_gate_records(
    *,
    milestone: Mapping[str, Any],
    spec: Mapping[str, Any],
    blockers: list[str],
    source_reports: list[str],
    source_report_paths: Mapping[str, str],
) -> list[dict[str, Any]]:
    milestone_id = str(milestone.get("milestone_id", "unknown"))
    next_action = str(milestone.get("next_action") or spec.get("instruction") or spec.get("recommended_command") or "")
    owner = str(spec.get("owner", "quant_architect"))
    source_report = source_reports[0] if source_reports else ""
    evidence_path = str(source_report_paths.get(source_report, source_report))
    return [
        {
            "record_id": f"{milestone_id}:{index + 1}",
            "milestone_id": milestone_id,
            "gate_id": milestone_id,
            "blocker": blocker,
            "owner": owner,
            "reason": f"Blocked by {blocker}",
            "next_action": next_action,
            "evidence_path": evidence_path,
            "source_report": source_report,
            "actionability": str(milestone.get("actionability") or spec.get("actionability", "")),
            "dependency_type": str(milestone.get("dependency_type") or spec.get("dependency_type", "")),
        }
        for index, blocker in enumerate(blockers)
    ]


def _actionability_for_action(
    milestone_id: str,
    milestone: Mapping[str, Any],
    spec: Mapping[str, Any],
    blockers: list[str],
) -> str:
    if milestone_id == "execution_infra_evidence" and any(item.startswith("broker_credentials_") for item in blockers):
        return "blocked_until_manual_input"
    return str(milestone.get("actionability") or spec["actionability"])


def _action_evidence(
    milestone: Mapping[str, Any],
    vendor_preflight: Mapping[str, Any],
    discovery: Mapping[str, Any],
) -> dict[str, Any]:
    milestone_id = str(milestone.get("milestone_id", "unknown"))
    blockers = _list_of_str(milestone.get("blockers"))
    evidence: dict[str, Any] = {
        "label": str(milestone.get("label", "")),
        "actionability": str(milestone.get("actionability", "")),
        "dependency_type": str(milestone.get("dependency_type", "")),
        "blocker_count": len(blockers),
        "first_blocker": blockers[0] if blockers else "",
        "blocker_sample": blockers[:5],
        "source_reports": _list_of_str(milestone.get("source_reports")),
        "milestone_next_action": str(milestone.get("next_action", "")),
    }
    if milestone_id != "production_pit_data":
        return evidence
    missing_files = [item for item in _list(vendor_preflight.get("missing_required_files")) if isinstance(item, Mapping)]
    ready_files = [item for item in _list(vendor_preflight.get("ready_required_files")) if isinstance(item, Mapping)]
    evidence.update(
        {
            "vendor_drop_preflight_status": vendor_preflight.get("status", ""),
            "required_file_count": vendor_preflight.get("required_file_count", 0),
            "missing_file_count": vendor_preflight.get("missing_file_count", len(missing_files)),
            "ready_file_count": vendor_preflight.get("ready_file_count", len(ready_files)),
            "missing_required_filenames": [str(item.get("filename")) for item in missing_files if item.get("filename")],
            "ready_required_filenames": [str(item.get("filename")) for item in ready_files if item.get("filename")],
            "required_operator_inputs": [_operator_input(item) for item in missing_files],
            "operator_command_sequence": _operator_command_sequence(bool(missing_files)),
            "local_pit_file_discovery": _discovery_evidence(discovery),
        }
    )
    return evidence


def _discovery_evidence(discovery: Mapping[str, Any]) -> dict[str, Any]:
    if not discovery:
        return {
            "status": "missing",
            "ready_for_copy_count": 0,
            "required_file_count": 0,
            "ready_filenames": [],
            "missing_filenames": [],
            "excluded_candidate_count": 0,
            "next_command": "python scripts/build_us_equity_local_pit_file_discovery_report.py",
        }
    files = [item for item in _list(discovery.get("files")) if isinstance(item, Mapping)]
    excluded_count = sum(int(item.get("excluded_candidate_count", 0) or 0) for item in files)
    ready = int(discovery.get("ready_for_copy_count", 0) or 0)
    required = int(discovery.get("required_file_count", 0) or 0)
    return {
        "status": str(discovery.get("status", "")),
        "ready_for_copy_count": ready,
        "required_file_count": required,
        "ready_filenames": _list_of_str(discovery.get("ready_filenames")),
        "missing_filenames": _list_of_str(discovery.get("missing_filenames")),
        "excluded_candidate_count": excluded_count,
        "next_command": (
            "copy manually license-reviewed ready candidates into data/external/us_equity_lineage/incoming/manual_vendor_drop"
            if ready and ready == required
            else "python scripts/build_us_equity_local_pit_file_discovery_report.py --search-root <licensed_vendor_folder>"
        ),
    }


def _operator_input(item: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "filename": str(item.get("filename", "")),
        "target_path": str(item.get("path", "")),
        "table": str(item.get("table", "")),
        "blocker": str(item.get("blocker", "")),
        "required_fields": _list_of_str(item.get("required_fields")),
    }


def _operator_command_sequence(has_missing_files: bool) -> list[str]:
    if has_missing_files:
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


def _spec_for(milestone_id: str) -> dict[str, Any]:
    specs: dict[str, dict[str, Any]] = {
        "production_pit_data": {
            "title": "Prepare and import production PIT vendor drop",
            "owner": "operator_data_vendor",
            "dependency_type": "external_input",
            "actionability": "waiting",
            "manual_required": True,
            "recommended_command": "python scripts/run_us_equity_vendor_drop_pipeline.py --license-reviewed",
            "instruction": "Place all licensed PIT CSV files required by the current provider contract in the incoming drop directory, manually confirm license review, then run the fail-closed vendor-drop pipeline.",
            "unlocks": ["strategy_validation_gate", "manual_review_signoff", "paper_simulation_readiness"],
        },
        "strategy_validation_gate": {
            "title": "Rerun strategy validation gate after PIT data is clean",
            "owner": "research_data_engineering",
            "dependency_type": "engineering_after_data",
            "actionability": "blocked_until_data",
            "manual_required": False,
            "recommended_command": "python scripts/build_us_etf_strategy_validation_gate_report.py",
            "instruction": "Do this only after production PIT/data-lineage blockers clear; validation does not imply live readiness.",
            "unlocks": ["forward_observation_30d", "manual_review_signoff"],
        },
        "forward_observation_30d": {
            "title": "Continue forward observation to 30 valid days",
            "owner": "daily_forward_observation_scheduler",
            "dependency_type": "natural_time",
            "actionability": "waiting",
            "manual_required": False,
            "recommended_command": "python scripts/run_us_equity_daily_production_line.py",
            "instruction": "Keep the daily line running; forward observation only verifies operational quality, not alpha.",
            "unlocks": ["manual_review_signoff"],
        },
        "manual_review_signoff": {
            "title": "Complete manual review packet",
            "owner": "human_reviewer",
            "dependency_type": "manual_review",
            "actionability": "manual",
            "manual_required": True,
            "recommended_command": "python scripts/build_us_equity_manual_review_packet.py",
            "instruction": "Review only after strategy validation, production PIT data, and forward observation are ready.",
            "unlocks": ["paper_simulation_readiness"],
        },
        "paper_simulation_readiness": {
            "title": "Prepare paper simulation readiness",
            "owner": "execution_engineering",
            "dependency_type": "engineering",
            "actionability": "blocked_until_review",
            "manual_required": False,
            "recommended_command": "python scripts/build_us_equity_paper_simulation_readiness_report.py",
            "instruction": "Keep paper blocked until manual review and remediation tickets are closed.",
            "unlocks": ["live_readiness_risk_constitution"],
        },
        "paper_simulation_evaluation": {
            "title": "Run paper simulation to manual-review window",
            "owner": "paper_simulation_scheduler",
            "dependency_type": "natural_time",
            "actionability": "waiting",
            "manual_required": False,
            "recommended_command": "python scripts/run_us_equity_daily_production_line.py",
            "instruction": "Start only after manual paper approval, then accumulate 30+ valid paper days; this remains simulation evidence and cannot unlock live by itself.",
            "unlocks": ["live_readiness_risk_constitution"],
        },
        "execution_infra_evidence": {
            "title": "Complete execution drill evidence",
            "owner": "execution_engineering",
            "dependency_type": "engineering",
            "actionability": "actionable",
            "manual_required": False,
            "recommended_command": "python scripts/build_us_equity_execution_drill_evidence_report.py",
            "instruction": "Broker credential review is the remaining execution evidence blocker; do not call broker/order endpoints.",
            "unlocks": ["live_readiness_risk_constitution"],
        },
        "broker_credentials_review": {
            "title": "Fill broker credential local review",
            "owner": "human_operator",
            "dependency_type": "manual_review",
            "actionability": "manual",
            "manual_required": True,
            "recommended_command": "python scripts/init_us_equity_broker_credentials_local_review.py",
            "instruction": "Initialize the ignored local review file, record read-only/live-disabled evidence manually, then rerun broker credential review; never commit secrets or account numbers.",
            "unlocks": ["execution_infra_evidence"],
        },
        "live_readiness_risk_constitution": {
            "title": "Rerun live readiness and risk constitution",
            "owner": "quant_architect",
            "dependency_type": "governance",
            "actionability": "blocked_until_upstream",
            "manual_required": True,
            "recommended_command": "python scripts/build_us_equity_live_readiness_risk_constitution.py",
            "instruction": "This can only reach manual-review readiness after data, validation, forward, paper, execution, and sign-off evidence are complete.",
            "unlocks": ["manual_live_review_only"],
        },
        "remediation_ticket_closure": {
            "title": "Close remediation tickets with evidence",
            "owner": "quant_architect",
            "dependency_type": "governance",
            "actionability": "blocked_until_upstream",
            "manual_required": False,
            "recommended_command": "python scripts/build_us_equity_remediation_ticket_closure_report.py",
            "instruction": "Close tickets only from source evidence; do not delete blockers to force closure.",
            "unlocks": ["completion_dependency_report"],
        },
        "portfolio_promotion_evidence": {
            "title": "Build portfolio promotion evidence",
            "owner": "portfolio_engineering",
            "dependency_type": "research_evidence",
            "actionability": "blocked_until_upstream",
            "manual_required": False,
            "recommended_command": "python scripts/build_us_equity_portfolio_promotion_evidence_report.py",
            "instruction": "Rebuild portfolio promotion evidence after strategy validation and ledger evidence are available.",
            "unlocks": ["completion_dependency_report"],
        },
    }
    return specs.get(
        milestone_id,
        {
            "title": f"Resolve {milestone_id}",
            "owner": "quant_architect",
            "dependency_type": "manual_triage",
            "actionability": "manual",
            "manual_required": True,
            "recommended_command": "",
            "instruction": "Inspect source reports and add a dedicated action spec if this milestone persists.",
            "unlocks": [],
        },
    )


def _parallel_tracks(open_actions: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    track_specs = [
        ("external_input_waiting", "External input waiting", lambda item: item.get("dependency_type") == "external_input"),
        ("natural_time_waiting", "Natural time waiting", lambda item: item.get("dependency_type") == "natural_time"),
        ("manual_required", "Manual required", lambda item: item.get("manual_required") is True),
        ("actionable_engineering", "Actionable engineering", lambda item: item.get("actionability") == "actionable"),
        (
            "blocked_until_upstream",
            "Blocked until upstream evidence",
            lambda item: str(item.get("actionability", "")).startswith("blocked"),
        ),
        (
            "blocked_until_manual_input",
            "Blocked until manual input",
            lambda item: item.get("actionability") == "blocked_until_manual_input",
        ),
    ]
    tracks: list[dict[str, Any]] = []
    for track_id, label, predicate in track_specs:
        actions = [item for item in open_actions if predicate(item)]
        tracks.append(
            {
                "track_id": track_id,
                "label": label,
                "action_count": len(actions),
                "action_ids": [str(item.get("action_id", "")) for item in actions],
                "owners": _dedupe(str(item.get("owner", "")) for item in actions if item.get("owner")),
                "recommended_commands": _dedupe(
                    str(item.get("recommended_command", "")) for item in actions if item.get("recommended_command")
                ),
            }
        )
    return tracks


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


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _list_of_str(value: Any) -> list[str]:
    return [str(item) for item in value if str(item)] if isinstance(value, list) else []


def _dedupe(values: Any) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        text = str(value)
        if not text or text in seen:
            continue
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


def markdown(payload: Mapping[str, Any]) -> str:
    lines = [
        "# US Equity 下一步执行队列",
        "",
        f"- generated_at: `{payload.get('generated_at', '')}`",
        f"- status: `{payload.get('status', '')}`",
        f"- decision: `{payload.get('decision', '')}`",
        "",
    ]
    next_action = payload.get("next_action")
    if isinstance(next_action, Mapping):
        lines.extend(
            [
                "## Next Action",
                "",
                f"- action_id: `{next_action.get('action_id')}`",
                f"- owner: `{next_action.get('owner')}`",
                f"- command: `{next_action.get('recommended_command')}`",
                f"- first_blocker: `{next_action.get('first_blocker')}`",
                f"- instruction: {next_action.get('instruction')}",
                "",
            ]
        )
        evidence = next_action.get("evidence")
        if isinstance(evidence, Mapping) and evidence:
            lines.extend(["### Evidence", ""])
            for key, value in evidence.items():
                lines.append(f"- `{key}`: `{value}`")
            lines.append("")
    tracks = [item for item in payload.get("parallel_tracks", []) if isinstance(item, Mapping)]
    if tracks:
        lines.extend(["## Parallel Tracks", "", "| Track | Count | Actions |", "| --- | ---: | --- |"])
        for track in tracks:
            lines.append(
                f"| `{track.get('track_id')}` | `{track.get('action_count')}` | `{', '.join(track.get('action_ids', []))}` |"
            )
        lines.append("")
    lines.extend(["## Queue", "", "| Priority | Action | Owner | Type | First blocker |", "| ---: | --- | --- | --- | --- |"])
    for item in payload.get("actions", []):
        if not isinstance(item, Mapping):
            continue
        lines.append(
            f"| `{item.get('priority')}` | `{item.get('action_id')}` | `{item.get('owner')}` | `{item.get('dependency_type')}` | `{item.get('first_blocker')}` |"
        )
    lines.extend(["", "## Guardrails", "", "- queue_only=true", "- paper_or_live_unlock_allowed=false", "- live_order_allowed=false"])
    return "\n".join(lines)
