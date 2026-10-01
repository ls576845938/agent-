#!/usr/bin/env python3
"""Build operator progress for the US equity PIT vendor drop checklist."""

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

from scripts.import_us_equity_local_csv_production_bundle import DEFAULT_SOURCE_DIR  # noqa: E402


SCHEMA_VERSION = "us_equity_vendor_drop_operator_progress_report_v1"
DEFAULT_OUTPUT = Path("artifacts/us_equity_data_lineage/latest/us_equity_vendor_drop_operator_progress_report.json")
DEFAULT_MARKDOWN_OUTPUT = Path("../学习资料/量化交易业务闭环/系统评估/US Equity PIT 数据交付进度.md")
DEFAULT_REPORT_PATHS = {
    "manual_vendor_drop_package": Path("artifacts/us_equity_data_lineage/latest/us_equity_manual_vendor_drop_package_report.json"),
    "incoming_drop_readiness": Path("artifacts/us_equity_data_lineage/latest/us_equity_incoming_drop_readiness_report.json"),
    "local_csv_import": Path("artifacts/us_equity_data_lineage/latest/us_equity_local_csv_production_bundle_import_report.json"),
    "pit_bundle_acceptance": Path("artifacts/us_equity_data_lineage/latest/us_equity_pit_bundle_acceptance_run_report.json"),
    "daily_production_line": Path("artifacts/us_equity_strategy_production_line/latest/us_equity_daily_production_line_run_report.json"),
}


def build_us_equity_vendor_drop_operator_progress_report(
    *,
    repo_root: Path | None = None,
    output: Path = DEFAULT_OUTPUT,
    markdown_output: Path = DEFAULT_MARKDOWN_OUTPUT,
    generated_at: str | None = None,
    report_paths: Mapping[str, Path] | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at or _utc_z_now()
    paths = dict(DEFAULT_REPORT_PATHS)
    if report_paths:
        paths.update(report_paths)
    reports = {name: _read_report(_resolve(root, path), root) for name, path in paths.items()}
    manual = _payload(reports, "manual_vendor_drop_package")
    incoming = _payload(reports, "incoming_drop_readiness")
    local_import = _payload(reports, "local_csv_import")
    acceptance = _payload(reports, "pit_bundle_acceptance")
    daily = _payload(reports, "daily_production_line")

    checklist = _checklist(manual)
    progress = [_step_progress(item, root, incoming, local_import, acceptance, daily) for item in checklist]
    required_file_progress = _required_file_progress(incoming)
    completed_count = sum(1 for item in progress if item["status"] == "completed")
    blocked_count = sum(1 for item in progress if item["status"] == "blocked")
    pending_count = sum(1 for item in progress if item["status"] == "pending")
    next_step = next((item for item in progress if item["status"] != "completed"), None)
    status = "operator_drop_ready_for_import" if all(item["status"] == "completed" for item in progress[:4]) else "operator_drop_blocked"
    if completed_count == len(progress):
        status = "operator_drop_complete_for_manual_review"

    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated,
        "asset": "us_equity",
        "status": status,
        "allowed_statuses": [
            "operator_drop_blocked",
            "operator_drop_ready_for_import",
            "operator_drop_complete_for_manual_review",
        ],
        "incoming_drop_dir": DEFAULT_SOURCE_DIR.as_posix(),
        "completed_count": completed_count,
        "blocked_count": blocked_count,
        "pending_count": pending_count,
        "step_count": len(progress),
        "next_step_id": str(next_step.get("step_id")) if next_step else "",
        "next_action": str(next_step.get("action")) if next_step else "manual review current production PIT evidence",
        "operator_copy_contract": _operator_copy_contract(manual),
        "copy_readiness_checks": _copy_readiness_checks(manual),
        "required_file_progress": required_file_progress["summary"],
        "missing_required_files": required_file_progress["missing_required_files"],
        "ready_required_files": required_file_progress["ready_required_files"],
        "steps": progress,
        "source_reports": {
            name: {"path": report["path"], "exists": report["exists"], "status": _string(_payload(reports, name).get("status"))}
            for name, report in reports.items()
        },
        "blockers": _dedupe(
            [f"operator_drop_step_blocked:{item['step_id']}:{item['first_blocker']}" for item in progress if item["status"] == "blocked"]
        ),
        "guardrails": {
            "operator_progress_only": True,
            "contains_vendor_data": False,
            "source_vendor_data_modified": False,
            "production_bundle_written": False,
            "configuration_mutated_by_this_report": False,
            "promotion_clean_granted_by_this_report": False,
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
    _write_json(_resolve(root, output), payload)
    _write_text(_resolve(root, markdown_output), _markdown(payload))
    return payload


def _operator_copy_contract(manual: Mapping[str, Any]) -> dict[str, Any]:
    required_tables = [item for item in _list(manual.get("required_tables")) if isinstance(item, Mapping)]
    required_files = []
    for item in required_tables:
        required_files.append(
            {
                "table": _string(item.get("table")),
                "filename": _string(item.get("filename")),
                "minimum_record_count": int(item.get("minimum_record_count", 1) or 1),
                "required_fields": _list_of_str(item.get("required_fields")),
                "empty_template_is_not_valid_drop": bool(item.get("empty_template_is_not_valid_drop", True)),
            }
        )
    if not required_files:
        for table in (
            "universe_membership_events",
            "delisted_symbols",
            "corporate_actions",
            "symbol_mapping",
            "adjustment_replay",
            "macro_release_calendar",
        ):
            required_files.append(
                {
                    "table": table,
                    "filename": f"{table}.csv",
                    "minimum_record_count": 1,
                    "required_fields": [],
                    "empty_template_is_not_valid_drop": True,
                }
            )
    return {
        "incoming_drop_dir": DEFAULT_SOURCE_DIR.as_posix(),
        "required_file_count": len(required_files),
        "required_files": required_files,
        "required_filenames": [item["filename"] for item in required_files],
        "forbidden_substitutes": [
            "header_only_template_csv",
            "empty_csv",
            "parquet",
            "xlsx",
            "screenshots",
            "unlicensed_exports",
        ],
        "post_copy_commands": [
            "python scripts/build_us_equity_incoming_drop_readiness_report.py",
            "python scripts/import_us_equity_local_csv_production_bundle.py --source-dir data/external/us_equity_lineage/incoming/manual_vendor_drop --bundle-id manual_vendor_bundle_v1 --sample-start 2000-01-01 --sample-end 2026-06-24 --license-note \"<license scope>\" --promotion-clean-allowed",
            "python scripts/run_us_equity_pit_bundle_acceptance.py",
            "python scripts/run_us_equity_daily_production_line.py",
        ],
        "guardrails": {
            "contract_only": True,
            "contains_vendor_data": False,
            "empty_templates_are_not_valid_evidence": True,
            "copy_contract_does_not_unlock_paper_or_live": True,
        },
    }


def _copy_readiness_checks(manual: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = [item for item in _list(manual.get("copy_readiness_checks")) if isinstance(item, Mapping)]
    if rows:
        return [
            {
                "check_id": _string(item.get("check_id")),
                "command": _string(item.get("command")),
                "expected_result": _string(item.get("expected_result")),
                "failure_means": _string(item.get("failure_means")),
                "blocks_import": bool(item.get("blocks_import", True)),
            }
            for item in rows
        ]
    return [
        {
            "check_id": "run_contract_preflight",
            "command": "python scripts/build_us_equity_vendor_drop_preflight_report.py",
            "expected_result": "vendor drop preflight no longer waits for vendor files",
            "failure_means": "The operator copy contract is not yet satisfied.",
            "blocks_import": True,
        }
    ]


def _step_progress(
    checklist_item: Mapping[str, Any],
    root: Path,
    incoming: Mapping[str, Any],
    local_import: Mapping[str, Any],
    acceptance: Mapping[str, Any],
    daily: Mapping[str, Any],
) -> dict[str, Any]:
    step_id = _string(checklist_item.get("step_id"))
    command = _string(checklist_item.get("command"))
    evidence = _string(checklist_item.get("expected_evidence"))
    status = "pending"
    first_blocker = ""
    if step_id == "build_handoff_package":
        status = "completed"
    elif step_id == "create_incoming_drop_dir":
        status = "completed" if _resolve(root, DEFAULT_SOURCE_DIR).is_dir() else "blocked"
        first_blocker = "" if status == "completed" else "source_dir_missing"
    elif step_id == "copy_six_licensed_csv_files":
        ready_count = int(incoming.get("ready_file_count", 0) or 0)
        required_count = int(incoming.get("required_file_count", 6) or 6)
        status = "completed" if ready_count >= required_count and _string(incoming.get("status")) == "incoming_drop_ready_for_import" else "blocked"
        first_blocker = "" if status == "completed" else (_list_of_str(incoming.get("blockers")) or ["required_csv_files_not_ready"])[0]
    elif step_id == "run_incoming_drop_readiness":
        status = "completed" if _string(incoming.get("status")) == "incoming_drop_ready_for_import" else "blocked"
        first_blocker = "" if status == "completed" else (_list_of_str(incoming.get("blockers")) or ["incoming_drop_not_ready"])[0]
    elif step_id == "import_local_csv_bundle":
        if _string(incoming.get("status")) != "incoming_drop_ready_for_import":
            status = "pending"
            first_blocker = "waiting_for_incoming_drop_readiness"
        else:
            status = "completed" if _string(local_import.get("status")) == "production_bundle_imported" else "blocked"
            first_blocker = "" if status == "completed" else (_list_of_str(local_import.get("blockers")) or ["local_csv_import_not_complete"])[0]
    elif step_id == "run_acceptance_and_activation":
        if _string(local_import.get("status")) != "production_bundle_imported":
            status = "pending"
            first_blocker = "waiting_for_local_csv_import"
        else:
            status = "completed" if _string(acceptance.get("status")) == "acceptance_ready_for_manual_config_apply" else "blocked"
            first_blocker = "" if status == "completed" else (_list_of_str(acceptance.get("blockers")) or ["pit_acceptance_not_ready"])[0]
    elif step_id == "rerun_daily_production_line":
        drop_status = _nested(daily, "production_pit_drop.status")
        status = "completed" if drop_status else "pending"
        first_blocker = "" if status == "completed" else "daily_production_line_not_refreshed"
    return {
        "step_id": step_id,
        "label": _string(checklist_item.get("label")),
        "status": status,
        "first_blocker": first_blocker,
        "command": command,
        "expected_evidence": evidence,
        "action": command if status != "completed" else "none",
    }


def _required_file_progress(incoming: Mapping[str, Any]) -> dict[str, Any]:
    files = [item for item in _list(incoming.get("files")) if isinstance(item, Mapping)]
    missing_required_files: list[dict[str, Any]] = []
    ready_required_files: list[dict[str, Any]] = []
    blocked_count = 0
    for item in files:
        blockers = _list_of_str(item.get("blockers"))
        row = {
            "table": _string(item.get("table")),
            "filename": _string(item.get("filename")),
            "exists": bool(item.get("exists", False)),
            "record_count": int(item.get("record_count", 0) or 0),
            "first_blocker": blockers[0] if blockers else "",
        }
        if blockers:
            blocked_count += 1
        if row["exists"] and not blockers:
            ready_required_files.append(row)
        elif not row["exists"] or blockers:
            missing_required_files.append(row)
    required_count = int(incoming.get("required_file_count", 0) or len(files))
    ready_count = int(incoming.get("ready_file_count", 0) or len(ready_required_files))
    return {
        "summary": {
            "required_file_count": required_count,
            "ready_file_count": ready_count,
            "missing_file_count": len([item for item in missing_required_files if not item["exists"]]),
            "blocked_file_count": blocked_count,
        },
        "missing_required_files": missing_required_files,
        "ready_required_files": ready_required_files,
    }


def _checklist(manual: Mapping[str, Any]) -> list[dict[str, Any]]:
    items = [dict(item) for item in _list(manual.get("operator_checklist")) if isinstance(item, Mapping)]
    if items:
        return items
    return [
        {"step_id": "build_handoff_package", "label": "Build package", "command": "python scripts/build_us_equity_manual_vendor_drop_package.py", "expected_evidence": "package ready"},
        {"step_id": "create_incoming_drop_dir", "label": "Create drop dir", "command": f"New-Item -ItemType Directory -Force -Path {DEFAULT_SOURCE_DIR.as_posix()}", "expected_evidence": "drop dir exists"},
        {"step_id": "copy_six_licensed_csv_files", "label": "Copy CSV files", "command": "manual_file_copy", "expected_evidence": "six CSV files present"},
        {"step_id": "run_incoming_drop_readiness", "label": "Run readiness", "command": "python scripts/build_us_equity_incoming_drop_readiness_report.py", "expected_evidence": "readiness ready"},
        {"step_id": "import_local_csv_bundle", "label": "Import bundle", "command": "python scripts/import_us_equity_local_csv_production_bundle.py", "expected_evidence": "bundle imported"},
        {"step_id": "run_acceptance_and_activation", "label": "Run acceptance", "command": "python scripts/run_us_equity_pit_bundle_acceptance.py", "expected_evidence": "acceptance ready"},
        {"step_id": "rerun_daily_production_line", "label": "Rerun daily", "command": "python scripts/run_us_equity_daily_production_line.py", "expected_evidence": "daily refreshed"},
    ]


def _read_report(path: Path, root: Path) -> dict[str, Any]:
    if not path.exists():
        return {"path": _relpath(path, root), "exists": False, "payload": {}}
    try:
        return {"path": _relpath(path, root), "exists": True, "payload": json.loads(path.read_text(encoding="utf-8"))}
    except Exception as exc:  # noqa: BLE001
        return {"path": _relpath(path, root), "exists": True, "payload": {"status": "unreadable_report", "blockers": [f"unreadable_report:{type(exc).__name__}"]}}


def _payload(reports: Mapping[str, Mapping[str, Any]], name: str) -> Mapping[str, Any]:
    return _mapping(_mapping(reports.get(name)).get("payload"))


def _markdown(payload: Mapping[str, Any]) -> str:
    lines = [
        "# US Equity PIT 数据交付进度",
        "",
        f"- generated_at: `{payload.get('generated_at')}`",
        f"- status: `{payload.get('status')}`",
        f"- progress: `{payload.get('completed_count')}` / `{payload.get('step_count')}`",
        f"- next_step_id: `{payload.get('next_step_id')}`",
        f"- next_action: `{payload.get('next_action')}`",
        "",
        "| step | status | first blocker | command |",
        "| --- | --- | --- | --- |",
    ]
    for item in _list(payload.get("steps")):
        if isinstance(item, Mapping):
            lines.append(f"| `{item.get('step_id')}` | `{item.get('status')}` | `{item.get('first_blocker')}` | `{item.get('command')}` |")
    copy_contract = _mapping(payload.get("operator_copy_contract"))
    lines.extend(["", "## Copy Contract", ""])
    lines.append(f"- incoming_drop_dir: `{copy_contract.get('incoming_drop_dir', '')}`")
    lines.append(f"- required_file_count: `{copy_contract.get('required_file_count', 0)}`")
    lines.append("- required_filenames:")
    lines.extend(f"  - `{filename}`" for filename in _list_of_str(copy_contract.get("required_filenames")))
    lines.append("- forbidden_substitutes:")
    lines.extend(f"  - `{item}`" for item in _list_of_str(copy_contract.get("forbidden_substitutes")))
    lines.extend(["", "## Copy Readiness Checks", ""])
    for item in _list(payload.get("copy_readiness_checks")):
        if isinstance(item, Mapping):
            lines.append(f"- `{item.get('check_id')}`: expected=`{item.get('expected_result')}`, blocks_import=`{item.get('blocks_import')}`")
            lines.append(f"```powershell\n{item.get('command')}\n```")
    lines.extend(["", "## Guardrails", "", "- operator progress only", "- live_order_allowed=false", "- paper_or_live_unlock_allowed=false"])
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


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _list_of_str(value: Any) -> list[str]:
    return [str(item) for item in value if str(item)] if isinstance(value, list) else []


def _string(value: Any) -> str:
    return str(value) if value not in (None, "") else ""


def _nested(payload: Any, dotted: str, default: Any = None) -> Any:
    current = payload
    for key in dotted.split("."):
        if not isinstance(current, Mapping):
            return default
        current = current.get(key)
    return current if current is not None else default


def _dedupe(items: list[str]) -> list[str]:
    return list(dict.fromkeys(item for item in items if item))


def _utc_z_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN_OUTPUT)
    parser.add_argument("--generated-at", default="")
    args = parser.parse_args()
    payload = build_us_equity_vendor_drop_operator_progress_report(
        repo_root=args.repo_root,
        output=args.output,
        markdown_output=args.markdown_output,
        generated_at=args.generated_at or None,
    )
    print(payload["status"])


if __name__ == "__main__":
    main()
