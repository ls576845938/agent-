#!/usr/bin/env python3
"""Build a one-page operator handoff summary for US equity PIT data intake."""

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

from quant_us.data.lineage.local_csv_provider import REQUIRED_LOCAL_CSV_FILES  # noqa: E402
from scripts.build_us_equity_local_csv_bundle_manifest import DEFAULT_FILENAMES  # noqa: E402
from scripts.import_us_equity_local_csv_production_bundle import (  # noqa: E402
    DEFAULT_BUNDLE_ID,
    DEFAULT_SOURCE_DIR,
)


SCHEMA_VERSION = "us_equity_pit_operator_handoff_summary_v1"
DEFAULT_OUTPUT = Path("artifacts/us_equity_data_lineage/latest/us_equity_pit_operator_handoff_summary.json")
DEFAULT_MARKDOWN_OUTPUT = Path("../学习资料/量化交易业务闭环/系统评估/US Equity PIT 数据交付一页纸.md")
DEFAULT_REPORT_PATHS = {
    "manual_vendor_drop_package": Path("artifacts/us_equity_data_lineage/latest/us_equity_manual_vendor_drop_package_report.json"),
    "incoming_drop_readiness": Path("artifacts/us_equity_data_lineage/latest/us_equity_incoming_drop_readiness_report.json"),
    "pit_bundle_acceptance": Path("artifacts/us_equity_data_lineage/latest/us_equity_pit_bundle_acceptance_run_report.json"),
    "pit_data_intake_status": Path("artifacts/us_equity_data_lineage/latest/us_equity_pit_data_intake_status_report.json"),
    "development_plan_audit": Path("artifacts/us_equity_strategy_production_line/latest/us_equity_development_plan_audit_report.json"),
    "vendor_drop_operator_progress": Path("artifacts/us_equity_data_lineage/latest/us_equity_vendor_drop_operator_progress_report.json"),
}


def build_us_equity_pit_operator_handoff_summary(
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
    acceptance = _payload(reports, "pit_bundle_acceptance")
    intake = _payload(reports, "pit_data_intake_status")
    audit = _payload(reports, "development_plan_audit")
    progress = _payload(reports, "vendor_drop_operator_progress")

    blockers = _handoff_blockers(reports, incoming, acceptance, intake)
    operator_next_actions = _dedupe(
        _list_of_str(intake.get("operator_next_actions"))
        + _list_of_str(_nested(audit, "phases[0].evidence.operator_next_actions"))
        + _list_of_str(_nested(acceptance, "operator_next_actions"))
        + _fallback_actions()
    )
    status = "handoff_blocked" if blockers else "handoff_ready_for_operator_drop"
    current_blocking_stage = (
        _string(intake.get("current_blocking_stage"))
        or _string(_nested(acceptance, "current_blocking_step"))
        or _string(_nested(incoming, "status"))
        or "none"
    )
    current_blocking_step = _string(_nested(acceptance, "current_blocking_step")) or current_blocking_stage

    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated,
        "asset": "us_equity",
        "status": status,
        "current_blocking_stage": current_blocking_stage,
        "current_blocking_step": current_blocking_step,
        "incoming_drop_dir": _string(manual.get("incoming_drop_dir")) or DEFAULT_SOURCE_DIR.as_posix(),
        "default_bundle_id": _string(manual.get("default_bundle_id")) or DEFAULT_BUNDLE_ID,
        "required_table_count": len(_required_tables()),
        "required_tables": _required_tables(),
        "operator_checklist": _operator_checklist(manual),
        "operator_progress": _operator_progress(progress),
        "copy_readiness_checks": _copy_readiness_checks(progress, manual),
        "acceptance_step_summary": _acceptance_step_summary(acceptance),
        "operator_next_actions": operator_next_actions,
        "acceptance_rules": _dedupe(_list_of_str(manual.get("acceptance_rules")) + _fallback_acceptance_rules()),
        "commands": {
            "build_package": "python scripts/build_us_equity_manual_vendor_drop_package.py",
            "readiness": (
                "python scripts/build_us_equity_incoming_drop_readiness_report.py "
                f"--source-dir {DEFAULT_SOURCE_DIR.as_posix()} --bundle-id {DEFAULT_BUNDLE_ID}"
            ),
            "preferred_import": _preferred_import_command(incoming, manual),
            "acceptance": "python scripts/run_us_equity_pit_bundle_acceptance.py",
            "daily_production_line": "python scripts/run_us_equity_daily_production_line.py",
        },
        "source_reports": {
            name: {
                "path": report["path"],
                "exists": report["exists"],
                "status": _string(_mapping(report.get("payload")).get("status")),
            }
            for name, report in reports.items()
        },
        "blockers": blockers,
        "guardrails": {
            "operator_handoff_only": True,
            "contains_vendor_data": False,
            "source_vendor_data_modified": False,
            "production_bundle_written": False,
            "configuration_mutated_by_this_report": False,
            "promotion_clean_granted_by_this_report": False,
            "paper_or_live_unlock_allowed": False,
            "paper_simulation_allowed": False,
            "live_order_allowed": False,
            "private_endpoint_allowed": False,
            "private_endpoint_used": False,
            "order_endpoint_allowed": False,
            "order_endpoint_used": False,
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


def _handoff_blockers(
    reports: Mapping[str, Mapping[str, Any]],
    incoming: Mapping[str, Any],
    acceptance: Mapping[str, Any],
    intake: Mapping[str, Any],
) -> list[str]:
    blockers = []
    for name, report in reports.items():
        if not report.get("exists"):
            blockers.append(f"missing_source_report:{name}")
    blockers.extend(_list_of_str(incoming.get("blockers")))
    blockers.extend(_list_of_str(acceptance.get("blockers")))
    blockers.extend(_list_of_str(intake.get("blockers")))
    if _string(intake.get("status")) != "production_pit_data_intake_ready":
        blockers.append("production_pit_data_intake_not_ready")
    if _string(acceptance.get("status")) != "acceptance_ready_for_manual_config_apply":
        blockers.append("pit_bundle_acceptance_not_ready")
    return _dedupe(blockers)


def _required_tables() -> list[dict[str, Any]]:
    return [
        {
            "table": table,
            "filename": DEFAULT_FILENAMES[table],
            "required_fields": list(fields),
            "minimum_record_count": 1,
            "empty_template_is_not_valid_drop": True,
        }
        for table, fields in REQUIRED_LOCAL_CSV_FILES.items()
    ]


def _preferred_import_command(incoming: Mapping[str, Any], manual: Mapping[str, Any]) -> str:
    command = _string(incoming.get("preferred_import_command"))
    if command:
        return command
    for item in _list_of_str(manual.get("operator_commands")):
        if "import_us_equity_local_csv_production_bundle.py" in item:
            return item
    return (
        "python scripts/import_us_equity_local_csv_production_bundle.py "
        f"--source-dir {DEFAULT_SOURCE_DIR.as_posix()} --bundle-id {DEFAULT_BUNDLE_ID} --promotion-clean-allowed"
    )


def _fallback_actions() -> list[str]:
    return [
        "Run: python scripts/build_us_equity_manual_vendor_drop_package.py",
        f"Create directory: {DEFAULT_SOURCE_DIR.as_posix()}",
        "Copy the six licensed CSV files into the incoming drop directory using docs/us_equity_manual_vendor_drop_templates headers.",
        "Do not use templates, parquet, xlsx, screenshots, or unlicensed exports as the production drop.",
        (
            "Run readiness: python scripts/build_us_equity_incoming_drop_readiness_report.py "
            f"--source-dir {DEFAULT_SOURCE_DIR.as_posix()} --bundle-id {DEFAULT_BUNDLE_ID}"
        ),
    ]


def _fallback_acceptance_rules() -> list[str]:
    return [
        "Use the exact six CSV filenames; do not substitute parquet/xlsx files in the incoming drop.",
        "Templates are header-only and are not valid vendor data.",
        "The package does not grant promotion-clean status and cannot unlock paper/live trading.",
    ]


def _read_report(path: Path, root: Path) -> dict[str, Any]:
    if not path.exists():
        return {"path": _relpath(path, root), "exists": False, "payload": {}}
    try:
        return {"path": _relpath(path, root), "exists": True, "payload": json.loads(path.read_text(encoding="utf-8"))}
    except Exception as exc:  # noqa: BLE001 - operator report should fail closed
        return {
            "path": _relpath(path, root),
            "exists": True,
            "payload": {"status": "unreadable_report", "blockers": [f"unreadable_report:{type(exc).__name__}"]},
        }


def _markdown(payload: Mapping[str, Any]) -> str:
    lines = [
        "# US Equity PIT 数据交付一页纸",
        "",
        f"- 生成时间：`{payload.get('generated_at')}`",
        f"- 状态：`{payload.get('status')}`",
        f"- 当前阻塞阶段：`{payload.get('current_blocking_stage')}`",
        f"- 当前阻塞步骤：`{payload.get('current_blocking_step')}`",
        f"- 数据投递目录：`{payload.get('incoming_drop_dir')}`",
        f"- 默认 bundle：`{payload.get('default_bundle_id')}`",
        "",
        "## 必需 CSV",
        "",
        "| table | filename | fields |",
        "| --- | --- | ---: |",
    ]
    for item in _list(payload.get("required_tables")):
        if isinstance(item, Mapping):
            lines.append(f"| `{item.get('table')}` | `{item.get('filename')}` | `{len(_list(item.get('required_fields')))}` |")
    lines.extend(["", "## Operator 下一步", ""])
    actions = _list_of_str(payload.get("operator_next_actions"))
    lines.extend([f"- {item}" for item in actions] if actions else ["- None"])
    progress = _mapping(payload.get("operator_progress"))
    lines.extend(
        [
            "",
            "## Operator 进度",
            "",
            f"- status: `{progress.get('status')}`",
            f"- completed: `{progress.get('completed_count')}` / `{progress.get('step_count')}`",
            f"- blocked: `{progress.get('blocked_count')}`",
            f"- pending: `{progress.get('pending_count')}`",
            f"- next_step_id: `{progress.get('next_step_id')}`",
            f"- next_action: `{progress.get('next_action')}`",
        ]
    )
    lines.extend(["", "## Operator Checklist", ""])
    checklist = [item for item in _list(payload.get("operator_checklist")) if isinstance(item, Mapping)]
    if checklist:
        for item in checklist:
            lines.append(
                f"- `{item.get('step_id')}`：{item.get('label')}；evidence=`{item.get('expected_evidence')}`；unlocks=`{item.get('unlocks')}`"
            )
    else:
        lines.append("- None")
    lines.extend(["", "## Copy Readiness Checks", ""])
    checks = [item for item in _list(payload.get("copy_readiness_checks")) if isinstance(item, Mapping)]
    if checks:
        for item in checks:
            lines.append(f"- `{item.get('check_id')}`：expected=`{item.get('expected_result')}`；blocks_import=`{item.get('blocks_import')}`")
            lines.append(f"```powershell\n{item.get('command')}\n```")
    else:
        lines.append("- None")
    lines.extend(
        [
            "",
            "## Acceptance Step Summary",
            "",
            "| step | status | passed | first blocker | skipped due to |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    for item in _list(payload.get("acceptance_step_summary")):
        if isinstance(item, Mapping):
            lines.append(
                f"| `{item.get('step_id')}` | `{item.get('status')}` | `{item.get('passed')}` | `{item.get('first_blocker')}` | `{item.get('skipped_due_to_step_id')}` |"
            )
    lines.extend(["", "## 验收命令", ""])
    for _, command in _mapping(payload.get("commands")).items():
        lines.append(f"```powershell\n{command}\n```")
    lines.extend(["", "## 当前 Blockers", ""])
    blockers = _list_of_str(payload.get("blockers"))
    lines.extend([f"- `{item}`" for item in blockers] if blockers else ["- None"])
    lines.extend(["", "## Guardrails", ""])
    guardrails = _mapping(payload.get("guardrails"))
    for key in [
        "operator_handoff_only",
        "contains_vendor_data",
        "production_bundle_written",
        "configuration_mutated_by_this_report",
        "paper_or_live_unlock_allowed",
        "paper_simulation_allowed",
        "live_order_allowed",
        "private_endpoint_allowed",
        "order_endpoint_allowed",
        "real_order_submitted",
        "broker_calls_used",
    ]:
        lines.append(f"- `{key}` = `{guardrails.get(key)}`")
    return "\n".join(lines)


def _operator_checklist(manual: Mapping[str, Any]) -> list[dict[str, str]]:
    checklist = []
    for item in _list(manual.get("operator_checklist")):
        if not isinstance(item, Mapping):
            continue
        checklist.append(
            {
                "step_id": _string(item.get("step_id")),
                "label": _string(item.get("label")),
                "command": _string(item.get("command")),
                "expected_evidence": _string(item.get("expected_evidence")),
                "unlocks": _string(item.get("unlocks")),
            }
        )
    if checklist:
        return checklist
    return [
        {
            "step_id": "build_handoff_package",
            "label": "Build the handoff package and templates",
            "command": "python scripts/build_us_equity_manual_vendor_drop_package.py",
            "expected_evidence": "us_equity_manual_vendor_drop_package_report.status == manual_vendor_drop_package_ready",
            "unlocks": "operator_drop_preparation_only",
        },
        {
            "step_id": "run_incoming_drop_readiness",
            "label": "Run incoming drop readiness",
            "command": "python scripts/build_us_equity_incoming_drop_readiness_report.py",
            "expected_evidence": "us_equity_incoming_drop_readiness_report.status == incoming_drop_ready_for_import",
            "unlocks": "local_csv_import_only",
        },
        {
            "step_id": "rerun_daily_production_line",
            "label": "Rerun the daily production line after data evidence changes",
            "command": "python scripts/run_us_equity_daily_production_line.py",
            "expected_evidence": "daily report updates production_pit_drop and remediation closure state",
            "unlocks": "status_refresh_only_no_execution_permission",
        },
    ]


def _operator_progress(progress: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "status": _string(progress.get("status")) or "operator_progress_report_missing",
        "completed_count": _int(progress.get("completed_count")),
        "blocked_count": _int(progress.get("blocked_count")),
        "pending_count": _int(progress.get("pending_count")),
        "step_count": _int(progress.get("step_count")),
        "next_step_id": _string(progress.get("next_step_id")),
        "next_action": _string(progress.get("next_action")) or "run vendor drop operator progress report",
    }


def _copy_readiness_checks(progress: Mapping[str, Any], manual: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = [item for item in _list(progress.get("copy_readiness_checks")) if isinstance(item, Mapping)]
    if not rows:
        rows = [item for item in _list(manual.get("copy_readiness_checks")) if isinstance(item, Mapping)]
    return [
        {
            "check_id": _string(item.get("check_id")),
            "command": _string(item.get("command")),
            "expected_result": _string(item.get("expected_result")),
            "failure_means": _string(item.get("failure_means")),
            "blocks_import": bool(item.get("blocks_import", True)),
        }
        for item in rows
        if _string(item.get("check_id"))
    ]


def _acceptance_step_summary(acceptance: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for item in _list(acceptance.get("steps")):
        if not isinstance(item, Mapping):
            continue
        rows.append(
            {
                "step_id": _string(item.get("step_id")),
                "status": _string(item.get("status")),
                "passed": bool(item.get("passed", False)),
                "first_blocker": (_list_of_str(item.get("blockers")) or [""])[0],
                "skipped_due_to_step_id": _string(item.get("skipped_due_to_step_id")),
            }
        )
    return rows


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


def _payload(reports: Mapping[str, Mapping[str, Any]], name: str) -> Mapping[str, Any]:
    return _mapping(_mapping(reports.get(name)).get("payload"))


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _list_of_str(value: Any) -> list[str]:
    return [str(item) for item in value if str(item)] if isinstance(value, list) else []


def _string(value: Any) -> str:
    return str(value) if value not in (None, "") else ""


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _dedupe(items: list[str]) -> list[str]:
    out = []
    seen = set()
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _nested(payload: Any, dotted: str, default: Any = None) -> Any:
    current = payload
    for raw_key in dotted.split("."):
        if "[" in raw_key and raw_key.endswith("]"):
            key, raw_index = raw_key[:-1].split("[", 1)
            if key:
                if not isinstance(current, Mapping):
                    return default
                current = current.get(key)
            if not isinstance(current, list):
                return default
            try:
                current = current[int(raw_index)]
            except (IndexError, ValueError):
                return default
            continue
        if not isinstance(current, Mapping):
            return default
        current = current.get(raw_key)
    return current if current is not None else default


def _utc_z_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build US equity PIT operator handoff summary.")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--markdown-output", default=str(DEFAULT_MARKDOWN_OUTPUT))
    parser.add_argument("--generated-at", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    payload = build_us_equity_pit_operator_handoff_summary(
        repo_root=Path(args.repo_root),
        output=Path(args.output),
        markdown_output=Path(args.markdown_output),
        generated_at=args.generated_at or None,
    )
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False, default=str))
    else:
        print(payload["status"])


if __name__ == "__main__":
    main()
