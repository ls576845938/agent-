from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence


DEFAULT_REPORT_PATH = Path("artifacts/btc_promotion_gate_control/latest/btc_promotion_gate_control_report.json")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check BTC promotion gate using root-cause task queue output for CI."
    )
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT_PATH)
    parser.add_argument(
        "--include-raw-blockers",
        action="store_true",
        help="Include raw blocker samples for drill-down. The default CI output stays root-cause-first.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = load_gate_report(args.report)
    payload = build_ci_payload(report, report_path=args.report, include_raw_blockers=args.include_raw_blockers)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return exit_code_for_payload(payload)


def load_gate_report(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "status": "missing",
            "decision": "btc_promotion_gate_control_report_missing",
            "blockers": [f"missing_report:{path.as_posix()}"],
            "root_cause_matrix": [],
            "root_cause_task_queue": {"schema_version": "btc_root_cause_task_queue_v1"},
            "outputs": {},
        }
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return payload if isinstance(payload, dict) else {}


def build_ci_payload(
    report: Mapping[str, Any],
    *,
    report_path: Path = DEFAULT_REPORT_PATH,
    include_raw_blockers: bool = False,
) -> dict[str, Any]:
    root_cause_matrix = _list_of_mappings(report.get("root_cause_matrix"))
    task_queue = _mapping(report.get("root_cause_task_queue"))
    raw_blockers = _list_of_strings(report.get("blockers"))
    status = str(report.get("status") or "missing")
    safety_violation_count = _int(report.get("safety_violation_count"))
    root_causes = [_root_cause_ci_row(row) for row in root_cause_matrix]
    payload = {
        "schema_version": "btc_promotion_gate_root_cause_ci_v1",
        "status": status,
        "decision": report.get("decision"),
        "report_path": _portable_path(report_path),
        "aggregation_batch_id": report.get("aggregation_batch_id", ""),
        "generated_at_utc": report.get("generated_at_utc", ""),
        "ci_passed": _ci_passed(report),
        "safety_violation_count": safety_violation_count,
        "root_cause_summary": report.get("root_cause_summary", {}),
        "root_cause_task_queue": {
            "schema_version": task_queue.get("schema_version", "btc_root_cause_task_queue_v1"),
            "dashboard_should_show_root_causes_only": task_queue.get(
                "dashboard_should_show_root_causes_only", True
            ),
            "data_wait_items": [_task_ci_row(row) for row in _list_of_mappings(task_queue.get("data_wait_items"))],
            "immediate_development_items": [
                _task_ci_row(row) for row in _list_of_mappings(task_queue.get("immediate_development_items"))
            ],
        },
        "root_causes": root_causes,
        "required_rebuild_reports": report.get("required_rebuild_reports", []),
        "artifact_freshness_status": _mapping(report.get("artifact_freshness")).get("status", ""),
        "raw_blocker_drilldown": {
            "raw_blocker_count": len(raw_blockers),
            "raw_blockers_hidden_by_default": not include_raw_blockers,
            "sample": raw_blockers[:10] if include_raw_blockers else raw_blockers[:3],
        },
        "outputs": report.get("outputs", {}),
        "gate": {
            "paper_queue_write_allowed": False,
            "live_unlock_allowed": False,
            "broker_or_order_allowed": False,
        },
    }
    return payload


def exit_code_for_payload(payload: Mapping[str, Any]) -> int:
    return 0 if payload.get("ci_passed") is True else 1


def _ci_passed(report: Mapping[str, Any]) -> bool:
    status = str(report.get("status") or "").lower()
    blockers = _list_of_strings(report.get("blockers"))
    safety_violation_count = _int(report.get("safety_violation_count"))
    if safety_violation_count:
        return False
    if blockers:
        return False
    return status in {"pass", "passed", "complete", "complete_research_only"}


def _root_cause_ci_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "root_cause_id": row.get("root_cause_id", ""),
        "label_cn": row.get("label_cn", ""),
        "raw_blocker_count": row.get("raw_blocker_count", 0),
        "unique_blocker_count": row.get("unique_blocker_count", 0),
        "affected_gates": row.get("affected_gates", []),
        "owner": row.get("owner", ""),
        "source_reports": row.get("source_reports", []),
        "next_command": row.get("next_command", ""),
        "acceptance_criteria": row.get("acceptance_criteria", []),
        "blocker_examples": _list_of_strings(row.get("blocker_examples"))[:3],
    }


def _task_ci_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "root_cause_id": row.get("root_cause_id", ""),
        "label_cn": row.get("label_cn", ""),
        "owner": row.get("owner", ""),
        "source_reports": row.get("source_reports", []),
        "next_command": row.get("next_command", ""),
        "raw_blocker_count": row.get("raw_blocker_count", 0),
        "affected_gates": row.get("affected_gates", []),
        "acceptance_criteria": row.get("acceptance_criteria", []),
    }


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list_of_mappings(value: Any) -> list[Mapping[str, Any]]:
    return [item for item in value if isinstance(item, Mapping)] if isinstance(value, list) else []


def _list_of_strings(value: Any) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [str(item) for item in value if str(item)]


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _portable_path(path: Path) -> str:
    return path.as_posix()


if __name__ == "__main__":
    raise SystemExit(main())
