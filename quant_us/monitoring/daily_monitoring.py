"""Service rules for the US equity daily monitoring report.

The CLI entrypoint should only parse arguments and write the report.  Gate
classification, replay diff construction, incident template assembly, and
operator queue coverage live here so they can be tested without invoking a
script.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from quant_us.monitoring.blocked_gate_queue import (
    build_blocked_gate_coverage,
    build_operator_queue,
    coverage_blockers,
)


SCHEMA_VERSION = "us_equity_daily_monitoring_report_v1"
DEFAULT_MONITORING_RULES = Path("artifacts/us_equity_etf_macro_rotation/latest/us_equity_monitoring_rules_report.json")
DEFAULT_DAILY_PRODUCTION_LINE = Path(
    "artifacts/us_equity_strategy_production_line/latest/us_equity_daily_production_line_run_report.json"
)
DEFAULT_STRATEGY_PRODUCTION_LINE = Path(
    "artifacts/us_equity_strategy_production_line/latest/us_equity_strategy_production_line_report.json"
)
DEFAULT_NEXT_ACTION_QUEUE = Path(
    "artifacts/us_equity_strategy_production_line/latest/us_equity_next_action_queue_report.json"
)
DEFAULT_FORWARD_HEALTH = Path(
    "artifacts/us_equity_etf_macro_rotation/latest/us_etf_forward_observation_daily_health_report.json"
)
DEFAULT_FORWARD_EVALUATION = Path(
    "artifacts/us_equity_etf_macro_rotation/latest/us_etf_forward_observation_evaluation_report.json"
)
DEFAULT_PAPER_READINESS = Path(
    "artifacts/us_equity_etf_macro_rotation/latest/us_equity_paper_simulation_readiness_report.json"
)
DEFAULT_PAPER_EVALUATION = Path(
    "artifacts/us_equity_etf_macro_rotation/latest/us_equity_paper_simulation_evaluation_report.json"
)
DEFAULT_EXECUTION_DRILL = Path(
    "artifacts/us_equity_etf_macro_rotation/latest/us_equity_execution_drill_evidence_report.json"
)
DEFAULT_REPLAY_READINESS = Path(
    "artifacts/us_equity_etf_macro_rotation/latest/us_etf_forward_observation_replay_readiness_report.json"
)
DEFAULT_OUTPUT = Path("artifacts/us_equity_etf_macro_rotation/latest/us_equity_daily_monitoring_report.json")
DEFAULT_MARKDOWN_OUTPUT = Path(
    "../学习资料/量化交易业务闭环/系统评估/US Equity Daily Monitoring.md"
)

DEFAULT_INCIDENT_REVIEW_TEMPLATE_PATH = (
    "artifacts/us_equity_etf_macro_rotation/incidents/us_equity_daily_monitoring_incident_review_template.json"
)
DEFAULT_REPLAY_DIFF_PATH = (
    "artifacts/us_equity_etf_macro_rotation/replay/us_equity_daily_monitoring_replay_diff.json"
)
DEFAULT_OPERATOR_QUEUE_SNAPSHOT_PATH = (
    "artifacts/us_equity_etf_macro_rotation/operator/us_equity_daily_monitoring_operator_queue.json"
)

EXPECTED_STATUSES: dict[str, set[str]] = {
    "monitoring_rules": {"monitoring_rules_defined"},
    "daily_production_line": {"PASS"},
    "strategy_production_line": {
        "production_line_blocked_before_paper_or_live",
        "production_line_observing_manual_review_required",
        "production_line_registry_missing",
    },
    "forward_observation_daily_health": {"daily_health_pass", "daily_health_observing_stale"},
    "forward_observation_evaluation": {"forward_observing", "forward_complete_for_manual_review"},
    "paper_simulation_readiness": {"paper_simulation_blocked", "paper_simulation_ready_for_manual_start"},
    "paper_simulation_evaluation": {
        "paper_simulation_not_started",
        "paper_simulation_observing",
        "paper_simulation_complete_for_manual_review",
        "paper_simulation_blocked",
    },
    "execution_drill_evidence": {
        "execution_drill_evidence_blocked",
        "execution_drill_evidence_partial",
        "execution_drill_evidence_complete",
    },
    "replay_readiness": {"replay_readiness_pass"},
    "next_action_queue": {"next_actions_open", "next_actions_complete"},
}

BLOCKING_STATUSES = {
    "BLOCKED",
    "blocked",
    "blocked_data_quality",
    "paper_simulation_blocked",
    "paper_simulation_not_started",
    "execution_drill_evidence_blocked",
    "execution_drill_evidence_partial",
    "live_readiness_blocked",
    "completion_dependencies_blocked",
    "production_line_blocked_before_paper_or_live",
    "production_line_registry_missing",
    "next_actions_open",
}


def build_us_equity_daily_monitoring_report(
    *,
    repo_root: Path | None = None,
    output: Path = DEFAULT_OUTPUT,
    markdown_output: Path = DEFAULT_MARKDOWN_OUTPUT,
    monitoring_rules: Path = DEFAULT_MONITORING_RULES,
    daily_production_line: Path = DEFAULT_DAILY_PRODUCTION_LINE,
    strategy_production_line: Path = DEFAULT_STRATEGY_PRODUCTION_LINE,
    next_action_queue: Path = DEFAULT_NEXT_ACTION_QUEUE,
    forward_health: Path = DEFAULT_FORWARD_HEALTH,
    forward_evaluation: Path = DEFAULT_FORWARD_EVALUATION,
    paper_readiness: Path = DEFAULT_PAPER_READINESS,
    paper_evaluation: Path = DEFAULT_PAPER_EVALUATION,
    execution_drill: Path = DEFAULT_EXECUTION_DRILL,
    replay_readiness: Path = DEFAULT_REPLAY_READINESS,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at or _utc_z_now()
    sources = {
        "monitoring_rules": _source(root, monitoring_rules),
        "daily_production_line": _source(root, daily_production_line),
        "strategy_production_line": _source(root, strategy_production_line),
        "forward_observation_daily_health": _source(root, forward_health),
        "forward_observation_evaluation": _source(root, forward_evaluation),
        "paper_simulation_readiness": _source(root, paper_readiness),
        "paper_simulation_evaluation": _source(root, paper_evaluation),
        "execution_drill_evidence": _source(root, execution_drill),
        "replay_readiness": _source(root, replay_readiness),
        "next_action_queue": _source(root, next_action_queue),
    }
    source_payloads = {key: dict(value.get("payload") or {}) for key, value in sources.items()}
    replay_diff = build_replay_diff(sources)
    operator_queue = build_operator_queue(
        next_action_payload=source_payloads.get("next_action_queue", {}),
        sources=sources,
        replay_diff=replay_diff,
    )
    blocked_gate_coverage = build_blocked_gate_coverage(sources=sources, operator_queue=operator_queue)
    blockers = build_daily_monitoring_blockers(sources, replay_diff, operator_queue, blocked_gate_coverage)
    status = daily_monitoring_status(blockers, operator_queue)
    monitoring_rules_payload = source_payloads.get("monitoring_rules", {})
    incident_template = build_incident_template(monitoring_rules_payload, replay_diff, operator_queue)
    incident_action_item_count = int(incident_template.get("incident_action_item_count", 0) or 0)
    retained_artifacts = write_retained_monitoring_artifacts(
        root=root,
        generated_at=generated,
        replay_diff=replay_diff,
        incident_template=incident_template,
        operator_queue=operator_queue,
    )
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated,
        "commit": _git(["rev-parse", "--short", "HEAD"], cwd=root),
        "branch": _git(["branch", "--show-current"], cwd=root),
        "asset": "us_equity",
        "status": status,
        "allowed_statuses": [
            "daily_monitoring_blocked",
            "daily_monitoring_observing",
            "daily_monitoring_clear",
        ],
        "decision": "operate_queue_keep_paper_live_locked",
        "summary": {
            "source_count": len(sources),
            "missing_source_count": sum(1 for item in sources.values() if not item["exists"]),
            "status_diff_count": len(replay_diff["diffs"]),
            "operator_action_count": len(operator_queue),
            "blocker_count": len(blockers),
            "blocked_gate_count": int(blocked_gate_coverage["gate_count"]),
            "covered_blocked_gate_count": int(blocked_gate_coverage["covered_gate_count"]),
            "uncovered_blocked_gate_count": int(blocked_gate_coverage["uncovered_gate_count"]),
            "blocked_gate_record_count": sum(
                int(item.get("blocked_gate_record_count", 0) or 0)
                for item in operator_queue
            ),
            "incident_template_ready": bool(incident_template["template_fields"]),
            "incident_action_item_count": incident_action_item_count,
            "paper_or_live_unlock_allowed": False,
            "live_order_allowed": False,
        },
        "monitoring_rules_applied": {
            "rules_status": _payload_status(monitoring_rules_payload),
            "monitor_count": int(monitoring_rules_payload.get("monitor_count") or 0),
            "rules_source": sources["monitoring_rules"]["path"],
        },
        "source_reports": {
            key: {
                "path": value["path"],
                "exists": value["exists"],
                "status": value["status"],
                "blockers": value["blockers"],
            }
            for key, value in sources.items()
        },
        "replay_diff": replay_diff,
        "blocked_gate_coverage": blocked_gate_coverage,
        "incident_review_template": incident_template,
        "operator_queue": operator_queue,
        "retained_artifacts": retained_artifacts,
        "blockers": blockers,
        "guardrails": {
            "monitoring_only": True,
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


def write_retained_monitoring_artifacts(
    *,
    root: Path,
    generated_at: str,
    replay_diff: Mapping[str, Any],
    incident_template: Mapping[str, Any],
    operator_queue: list[Mapping[str, Any]],
) -> dict[str, Any]:
    """Persist monitoring artifacts that operators can open directly."""
    replay_path = _resolve(root, Path(DEFAULT_REPLAY_DIFF_PATH))
    incident_path = _resolve(root, Path(DEFAULT_INCIDENT_REVIEW_TEMPLATE_PATH))
    operator_path = _resolve(root, Path(DEFAULT_OPERATOR_QUEUE_SNAPSHOT_PATH))
    _write_json(
        replay_path,
        {
            "schema_version": "us_equity_daily_monitoring_replay_diff_v1",
            "generated_at": generated_at,
            "artifact_id": "replay_diff",
            "replay_diff": dict(replay_diff),
            "guardrails": retained_artifact_guardrails(),
        },
    )
    _write_json(
        incident_path,
        {
            "schema_version": "us_equity_daily_monitoring_incident_review_template_v1",
            "generated_at": generated_at,
            "artifact_id": "incident_review_template",
            "incident_review_template": dict(incident_template),
            "guardrails": retained_artifact_guardrails(),
        },
    )
    _write_json(
        operator_path,
        {
            "schema_version": "us_equity_daily_monitoring_operator_queue_snapshot_v1",
            "generated_at": generated_at,
            "artifact_id": "operator_queue_snapshot",
            "item_count": len(operator_queue),
            "operator_queue": list(operator_queue),
            "guardrails": retained_artifact_guardrails(),
        },
    )
    return {
        "replay_diff": _retained_artifact("replay_diff", replay_path, root),
        "incident_review_template": _retained_artifact("incident_review_template", incident_path, root),
        "operator_queue_snapshot": _retained_artifact("operator_queue_snapshot", operator_path, root),
    }


def retained_artifact_guardrails() -> dict[str, bool]:
    return {
        "monitoring_only": True,
        "paper_or_live_unlock_allowed": False,
        "paper_simulation_allowed": False,
        "live_order_allowed": False,
        "private_endpoint_allowed": False,
        "order_endpoint_allowed": False,
        "broker_calls_used": False,
        "real_order_submitted": False,
    }


def _retained_artifact(artifact_id: str, path: Path, root: Path) -> dict[str, Any]:
    return {
        "artifact_id": artifact_id,
        "path": _relpath(path, root),
        "written": path.exists(),
    }


def build_replay_diff(sources: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    diffs: list[dict[str, Any]] = []
    for source_id, source in sources.items():
        expected = sorted(EXPECTED_STATUSES[source_id])
        actual = str(source.get("status", ""))
        exists = bool(source.get("exists"))
        passed = exists and actual in EXPECTED_STATUSES[source_id]
        row = {
            "source_id": source_id,
            "path": str(source.get("path", "")),
            "exists": exists,
            "expected_statuses": expected,
            "actual_status": actual,
            "passed": passed,
            "blockers": _list_of_str(source.get("blockers")),
        }
        rows.append(row)
        if not passed:
            diffs.append(
                {
                    "source_id": source_id,
                    "reason": "missing_source" if not exists else "unexpected_status",
                    "expected_statuses": expected,
                    "actual_status": actual,
                    "evidence_path": str(source.get("path", "")),
                }
            )
    return {
        "mode": "fixed_clock_no_realtime_access",
        "diff_count": len(diffs),
        "source_statuses": rows,
        "diffs": diffs,
    }


def build_daily_monitoring_blockers(
    sources: Mapping[str, Mapping[str, Any]],
    replay_diff: Mapping[str, Any],
    operator_queue: list[Mapping[str, Any]],
    blocked_gate_coverage: Mapping[str, Any],
) -> list[str]:
    blockers: list[str] = []
    for source_id, source in sources.items():
        if not source.get("exists"):
            blockers.append(f"us_equity_daily_monitoring_source_missing:{source_id}")
            continue
        status = str(source.get("status", ""))
        if status in BLOCKING_STATUSES or status.endswith("_blocked"):
            blockers.append(f"us_equity_daily_monitoring_source_blocked:{source_id}:{status}")
        blockers.extend(str(item) for item in source.get("blockers", []) if str(item))
    blockers.extend(
        f"us_equity_daily_monitoring_replay_diff:{item.get('source_id')}"
        for item in _list(replay_diff.get("diffs"))
        if isinstance(item, Mapping)
    )
    blockers.extend(coverage_blockers(blocked_gate_coverage))
    if operator_queue:
        blockers.append("us_equity_daily_monitoring_operator_queue_open")
    return _dedupe(blockers)


def daily_monitoring_status(blockers: list[str], operator_queue: list[Mapping[str, Any]]) -> str:
    if blockers:
        return "daily_monitoring_blocked"
    if operator_queue:
        return "daily_monitoring_observing"
    return "daily_monitoring_clear"


def build_incident_template(
    monitoring_rules: Mapping[str, Any],
    replay_diff: Mapping[str, Any],
    operator_queue: list[Mapping[str, Any]],
) -> dict[str, Any]:
    contract = monitoring_rules.get("incident_review") if isinstance(monitoring_rules.get("incident_review"), Mapping) else {}
    template_fields = _list_of_str(contract.get("required_template_fields"))
    must_create_update = bool(contract.get("incident_review_must_create_test_or_rule_update", False))
    incident_action_items = build_incident_action_items(
        operator_queue=operator_queue,
        regression_required=must_create_update,
    )
    source_evidence_paths = _dedupe(
        [
            str(item.get("evidence_path", ""))
            for item in _list(replay_diff.get("diffs"))
            if isinstance(item, Mapping) and item.get("evidence_path")
        ]
        + [
            str(item.get("evidence_path", ""))
            for item in operator_queue
            if item.get("evidence_path")
        ]
    )
    return {
        "template_id": "us_equity_daily_monitoring_incident_review_v1",
        "trigger_candidates": _incident_triggers(replay_diff, operator_queue, contract),
        "template_fields": {field: "" for field in template_fields},
        "required_template_fields": template_fields,
        "retention_path": DEFAULT_INCIDENT_REVIEW_TEMPLATE_PATH,
        "source_evidence_paths": source_evidence_paths,
        "incident_action_items": incident_action_items,
        "incident_action_item_count": len(incident_action_items),
        "operator_queue_item_count": len(operator_queue),
        "replay_diff_count": int(replay_diff.get("diff_count", 0) or 0),
        "incident_review_must_create_test_or_rule_update": must_create_update,
    }


def build_incident_action_items(
    *,
    operator_queue: list[Mapping[str, Any]],
    regression_required: bool,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in operator_queue:
        records = [record for record in _list(item.get("blocked_gate_records")) if isinstance(record, Mapping)]
        if not records:
            records = [
                {
                    "record_id": str(item.get("item_id", "")),
                    "gate_id": str(item.get("source_report", "")),
                    "blocker": str(item.get("reason", "")),
                    "owner": str(item.get("owner", "")),
                    "reason": str(item.get("reason", "")),
                    "next_action": str(item.get("next_action", "")),
                    "evidence_path": str(item.get("evidence_path", "")),
                    "source_report": str(item.get("source_report", "")),
                }
            ]
        for index, record in enumerate(records, start=1):
            row_id = str(record.get("record_id") or f"{item.get('item_id', 'operator_item')}:{index}")
            rows.append(
                {
                    "action_item_id": f"incident_action:{row_id}",
                    "operator_item_id": str(item.get("item_id", "")),
                    "record_id": row_id,
                    "gate_id": str(record.get("gate_id", "")),
                    "blocker": str(record.get("blocker") or item.get("reason", "")),
                    "owner": str(record.get("owner") or item.get("owner", "")),
                    "reason": str(record.get("reason") or item.get("reason", "")),
                    "next_action": str(record.get("next_action") or item.get("next_action", "")),
                    "recommended_command": str(item.get("recommended_command", "")),
                    "evidence_path": str(record.get("evidence_path") or item.get("evidence_path", "")),
                    "source_report": str(record.get("source_report") or item.get("source_report", "")),
                    "regression_test_or_rule_update_required": regression_required,
                }
            )
    return rows


def markdown(payload: Mapping[str, Any]) -> str:
    lines = [
        "# US Equity Daily Monitoring",
        "",
        f"- Status: `{payload.get('status', '')}`",
        f"- Decision: `{payload.get('decision', '')}`",
        f"- Operator actions: `{payload.get('summary', {}).get('operator_action_count')}`",
        f"- Replay diffs: `{payload.get('summary', {}).get('status_diff_count')}`",
        "",
        "## Operator Queue",
        "",
    ]
    for item in _list(payload.get("operator_queue")):
        if not isinstance(item, Mapping):
            continue
        lines.append(
            f"- `{item.get('item_id')}` owner=`{item.get('owner')}` reason=`{item.get('reason')}` evidence=`{item.get('evidence_path')}`"
        )
    lines.extend(["", "## Incident Action Items", ""])
    incident_template = payload.get("incident_review_template", {})
    action_items = _list(incident_template.get("incident_action_items") if isinstance(incident_template, Mapping) else [])
    for item in action_items[:20]:
        if not isinstance(item, Mapping):
            continue
        lines.append(
            f"- `{item.get('action_item_id')}` owner=`{item.get('owner')}` next=`{item.get('next_action')}` evidence=`{item.get('evidence_path')}`"
        )
    lines.extend(
        [
            "",
        "## Guardrails",
            "",
            "- monitoring_only=true",
            "- paper_or_live_unlock_allowed=false",
            "- live_order_allowed=false",
        ]
    )
    return "\n".join(lines)


def _source(root: Path, path: Path) -> dict[str, Any]:
    resolved = _resolve(root, path)
    exists = resolved.exists()
    payload: dict[str, Any] = {}
    if exists:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    return {
        "path": _relpath(resolved, root),
        "exists": exists,
        "status": _payload_status(payload),
        "blockers": _list_of_str(payload.get("blockers")),
        "payload": payload,
    }


def _incident_triggers(
    replay_diff: Mapping[str, Any],
    operator_queue: list[Mapping[str, Any]],
    contract: Mapping[str, Any],
) -> list[str]:
    candidates: list[str] = []
    for diff in _list(replay_diff.get("diffs")):
        if isinstance(diff, Mapping):
            candidates.append(f"replay_diff:{diff.get('source_id')}")
    for item in operator_queue:
        candidates.append(f"operator_queue:{item.get('item_id')}")
    if not candidates:
        candidates.extend(_list_of_str(contract.get("triggers"))[:1])
    return _dedupe(candidates)


def _payload_status(payload: Mapping[str, Any]) -> str:
    return str(payload.get("status") or payload.get("health_status") or "")


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


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def _git(args: list[str], *, cwd: Path) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=cwd, stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:
        return "unknown"


def _utc_z_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
