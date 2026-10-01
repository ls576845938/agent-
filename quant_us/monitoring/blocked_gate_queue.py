"""Operator queue helpers for blocked US equity monitoring gates."""

from __future__ import annotations

from typing import Any, Mapping


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

OWNER_BY_SOURCE = {
    "daily_production_line": "quant_architect",
    "strategy_production_line": "quant_architect",
    "forward_observation_daily_health": "daily_forward_observation_scheduler",
    "forward_observation_evaluation": "daily_forward_observation_scheduler",
    "paper_simulation_readiness": "execution_engineering",
    "paper_simulation_evaluation": "paper_simulation_scheduler",
    "execution_drill_evidence": "execution_engineering",
    "replay_readiness": "quant_architect",
    "monitoring_rules": "quant_architect",
    "next_action_queue": "quant_operator",
}

COMMAND_BY_SOURCE = {
    "daily_production_line": "python scripts/run_us_equity_daily_production_line.py",
    "strategy_production_line": "python scripts/build_us_equity_strategy_production_line_report.py",
    "forward_observation_daily_health": "python scripts/build_us_etf_forward_observation_daily_health_report.py",
    "forward_observation_evaluation": "python scripts/build_us_etf_forward_observation_evaluation_report.py",
    "paper_simulation_readiness": "python scripts/build_us_equity_paper_simulation_readiness_report.py",
    "paper_simulation_evaluation": "python scripts/build_us_equity_paper_simulation_evaluation_report.py",
    "execution_drill_evidence": "python scripts/build_us_equity_execution_drill_evidence_report.py",
    "replay_readiness": "python scripts/build_us_etf_forward_observation_replay_readiness_report.py",
    "monitoring_rules": "python scripts/build_us_equity_monitoring_rules_report.py",
    "next_action_queue": "python scripts/build_us_equity_next_action_queue_report.py",
}


def build_operator_queue(
    *,
    next_action_payload: Mapping[str, Any],
    sources: Mapping[str, Mapping[str, Any]],
    replay_diff: Mapping[str, Any],
) -> list[dict[str, Any]]:
    queue: list[dict[str, Any]] = []
    for item in _open_next_actions(next_action_payload):
        records = _records_for_next_action(item, fallback_evidence_path=str(sources["next_action_queue"]["path"]))
        first_record = records[0] if records else {}
        queue.append(
            {
                "item_id": str(item.get("action_id", "")),
                "owner": str(item.get("owner", "quant_operator")),
                "severity": _severity_for_next_action(item),
                "reason": str(first_record.get("reason") or item.get("first_blocker") or item.get("title") or ""),
                "next_action": str(item.get("instruction") or item.get("recommended_command") or ""),
                "recommended_command": str(item.get("recommended_command", "")),
                "evidence_path": str(first_record.get("evidence_path") or _first_source_report(item) or sources["next_action_queue"]["path"]),
                "source_report": "next_action_queue",
                "blocked_gate_record_count": len(records),
                "blocked_gate_records": records,
            }
        )

    for diff in _list(replay_diff.get("diffs")):
        if not isinstance(diff, Mapping):
            continue
        source_id = str(diff.get("source_id", ""))
        if not source_id:
            continue
        item_id = f"monitoring_replay_diff_{source_id}"
        if _has_item(queue, item_id):
            continue
        queue.append(_source_operator_item(source_id=source_id, reason=str(diff.get("reason", "")), source=sources.get(source_id, {}), item_id=item_id))

    for source_id, source in sources.items():
        if not _source_requires_operator_item(source):
            continue
        if _source_is_covered(source_id, source, queue):
            continue
        reason = _source_reason(source)
        item_id = f"monitoring_blocked_gate_{source_id}"
        queue.append(_source_operator_item(source_id=source_id, reason=reason, source=source, item_id=item_id))

    return queue


def build_blocked_gate_coverage(
    *,
    sources: Mapping[str, Mapping[str, Any]],
    operator_queue: list[Mapping[str, Any]],
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for source_id, source in sources.items():
        if not _source_requires_operator_item(source):
            continue
        item = _covering_item(source_id, source, operator_queue)
        rows.append(
            {
                "source_id": source_id,
                "gate_id": f"us_equity_gate_{source_id}",
                "status": str(source.get("status", "")),
                "exists": bool(source.get("exists")),
                "reason": _source_reason(source),
                "owner": str(item.get("owner", "")) if item else _owner_for_source(source_id),
                "next_action": str(item.get("next_action", "")) if item else _next_action_for_source(source_id),
                "recommended_command": str(item.get("recommended_command", "")) if item else _recommended_command_for_source(source_id),
                "evidence_path": str(item.get("evidence_path", "")) if item else str(source.get("path", "")),
                "operator_item_id": str(item.get("item_id", "")) if item else "",
                "covered": item is not None,
            }
        )
    uncovered = [row for row in rows if not row["covered"]]
    return {
        "required": True,
        "gate_count": len(rows),
        "covered_gate_count": len(rows) - len(uncovered),
        "uncovered_gate_count": len(uncovered),
        "uncovered_sources": [str(row["source_id"]) for row in uncovered],
        "rows": rows,
    }


def coverage_blockers(coverage: Mapping[str, Any]) -> list[str]:
    return [f"us_equity_daily_monitoring_gate_uncovered:{source}" for source in _list(coverage.get("uncovered_sources"))]


def _source_operator_item(*, source_id: str, reason: str, source: Mapping[str, Any], item_id: str) -> dict[str, Any]:
    owner = _owner_for_source(source_id)
    next_action = _next_action_for_source(source_id)
    evidence_path = str(source.get("path", ""))
    record = _record(
        record_id=item_id,
        milestone_id=source_id,
        gate_id=f"us_equity_gate_{source_id}",
        blocker=reason,
        owner=owner,
        reason=reason,
        next_action=next_action,
        evidence_path=evidence_path,
        source_report=source_id,
        actionability="monitoring",
        dependency_type="monitoring",
    )
    return {
        "item_id": item_id,
        "owner": owner,
        "severity": "block",
        "reason": reason,
        "next_action": next_action,
        "recommended_command": _recommended_command_for_source(source_id),
        "evidence_path": evidence_path,
        "source_report": source_id,
        "blocked_gate_record_count": 1,
        "blocked_gate_records": [record],
    }


def _source_requires_operator_item(source: Mapping[str, Any]) -> bool:
    if not bool(source.get("exists")):
        return True
    status = str(source.get("status", ""))
    if status in BLOCKING_STATUSES or status.endswith("_blocked"):
        return True
    if _list(source.get("blockers")):
        return True
    return False


def _source_is_covered(source_id: str, source: Mapping[str, Any], queue: list[Mapping[str, Any]]) -> bool:
    return _covering_item(source_id, source, queue) is not None


def _covering_item(source_id: str, source: Mapping[str, Any], queue: list[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    source_path = str(source.get("path", ""))
    for item in queue:
        item_id = str(item.get("item_id", ""))
        source_report = str(item.get("source_report", ""))
        evidence_path = str(item.get("evidence_path", ""))
        if source_report == source_id:
            return item
        if source_id and source_id in item_id:
            return item
        if source_path and evidence_path == source_path:
            return item
    return None


def _source_reason(source: Mapping[str, Any]) -> str:
    blockers = _list_of_str(source.get("blockers"))
    if blockers:
        return blockers[0]
    if not bool(source.get("exists")):
        return "missing_source"
    return f"status:{source.get('status', '')}"


def _next_action_for_source(source_id: str) -> str:
    return f"Rebuild or inspect {source_id} before paper/live review."


def _owner_for_source(source_id: str) -> str:
    return OWNER_BY_SOURCE.get(source_id, "quant_operator")


def _recommended_command_for_source(source_id: str) -> str:
    return COMMAND_BY_SOURCE.get(source_id, "")


def _open_next_actions(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return [item for item in _list(payload.get("actions")) if isinstance(item, Mapping) and item.get("status") == "open"]


def _severity_for_next_action(action: Mapping[str, Any]) -> str:
    dependency = str(action.get("dependency_type", ""))
    if dependency in {"external_input", "manual_review", "governance"}:
        return "block"
    if dependency == "natural_time":
        return "observe"
    return "manual_review"


def _first_source_report(action: Mapping[str, Any]) -> str:
    reports = _list_of_str(action.get("source_reports"))
    return reports[0] if reports else ""


def _records_for_next_action(action: Mapping[str, Any], *, fallback_evidence_path: str) -> list[dict[str, Any]]:
    records = [
        _normalize_record(item)
        for item in _list(action.get("blocked_gate_records"))
        if isinstance(item, Mapping)
    ]
    records = [item for item in records if item]
    if records:
        return records

    action_id = str(action.get("action_id", "next_action"))
    blocker = str(action.get("first_blocker") or action.get("title") or action_id)
    owner = str(action.get("owner", "quant_operator"))
    next_action = str(action.get("instruction") or action.get("recommended_command") or "")
    source_report = _first_source_report(action) or "next_action_queue"
    return [
        _record(
            record_id=f"{action_id}:1",
            milestone_id=str(action.get("milestone_id") or action_id),
            gate_id=str(action.get("milestone_id") or action_id),
            blocker=blocker,
            owner=owner,
            reason=f"Blocked by {blocker}",
            next_action=next_action,
            evidence_path=fallback_evidence_path,
            source_report=source_report,
            actionability=str(action.get("actionability", "")),
            dependency_type=str(action.get("dependency_type", "")),
        )
    ]


def _normalize_record(item: Mapping[str, Any]) -> dict[str, Any]:
    return _record(
        record_id=str(item.get("record_id", "")),
        milestone_id=str(item.get("milestone_id", "")),
        gate_id=str(item.get("gate_id", "")),
        blocker=str(item.get("blocker", "")),
        owner=str(item.get("owner", "")),
        reason=str(item.get("reason", "")),
        next_action=str(item.get("next_action", "")),
        evidence_path=str(item.get("evidence_path", "")),
        source_report=str(item.get("source_report", "")),
        actionability=str(item.get("actionability", "")),
        dependency_type=str(item.get("dependency_type", "")),
    )


def _record(
    *,
    record_id: str,
    milestone_id: str,
    gate_id: str,
    blocker: str,
    owner: str,
    reason: str,
    next_action: str,
    evidence_path: str,
    source_report: str,
    actionability: str,
    dependency_type: str,
) -> dict[str, Any]:
    return {
        "record_id": record_id,
        "milestone_id": milestone_id,
        "gate_id": gate_id,
        "blocker": blocker,
        "owner": owner,
        "reason": reason,
        "next_action": next_action,
        "evidence_path": evidence_path,
        "source_report": source_report,
        "actionability": actionability,
        "dependency_type": dependency_type,
    }


def _has_item(queue: list[Mapping[str, Any]], item_id: str) -> bool:
    return any(str(item.get("item_id", "")) == item_id for item in queue)


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _list_of_str(value: Any) -> list[str]:
    return [str(item) for item in value if str(item)] if isinstance(value, list) else []
