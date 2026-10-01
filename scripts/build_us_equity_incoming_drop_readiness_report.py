#!/usr/bin/env python3
"""Build a readiness report for the manual US equity production CSV drop."""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Mapping

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from quant_us.data.lineage.local_csv_provider import (  # noqa: E402
    CORPORATE_ACTION_EVENT_TYPES,
    DATE_FIELDS_BY_FILE,
    MEMBERSHIP_EVENT_TYPES,
    REQUIRED_LOCAL_CSV_FILES,
)
from scripts.import_us_equity_local_csv_production_bundle import (  # noqa: E402
    DEFAULT_BUNDLE_ID,
    DEFAULT_SOURCE_DIR,
    _post_import_commands,
)
from scripts.build_us_equity_local_csv_bundle_manifest import DEFAULT_FILENAMES  # noqa: E402


SCHEMA_VERSION = "us_equity_incoming_drop_readiness_report_v1"
DEFAULT_OUTPUT = Path("artifacts/us_equity_data_lineage/latest/us_equity_incoming_drop_readiness_report.json")
DEFAULT_MARKDOWN_OUTPUT = Path("../学习资料/量化交易业务闭环/系统评估/US Equity Incoming Drop Readiness.md")
ALLOWED_STATUSES = {"incoming_drop_ready_for_import", "incoming_drop_blocked"}
MAX_ROW_VALIDATION_ISSUES_PER_FILE = 25


def build_us_equity_incoming_drop_readiness_report(
    *,
    repo_root: Path | None = None,
    source_dir: Path = DEFAULT_SOURCE_DIR,
    bundle_id: str = DEFAULT_BUNDLE_ID,
    output: Path = DEFAULT_OUTPUT,
    markdown_output: Path = DEFAULT_MARKDOWN_OUTPUT,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at or _utc_z_now()
    source = _resolve(root, source_dir)
    blockers: list[str] = []
    files: list[dict[str, Any]] = []
    row_validation_summary: dict[str, Any] = {
        "checked_file_count": 0,
        "checked_row_count": 0,
        "issue_count": 0,
        "reported_issue_count": 0,
        "issue_truncation_applied": False,
    }
    drop_file_contract = _drop_file_contract(source, source.exists() and source.is_dir())

    if not source.exists():
        blockers.append("source_dir_missing")
    elif not source.is_dir():
        blockers.append("source_dir_not_directory")
    else:
        blockers.extend(_list_of_str(drop_file_contract.get("blockers")))
        source_record_ids: set[str] = set()
        for table, required_fields in REQUIRED_LOCAL_CSV_FILES.items():
            filename = DEFAULT_FILENAMES.get(table, f"{table}.csv")
            path = source / filename
            file_report = _file_readiness(table, filename, path, required_fields, source_record_ids)
            files.append(file_report)
            blockers.extend(_list_of_str(file_report.get("blockers")))
            _merge_row_validation(row_validation_summary, file_report.get("row_validation"))

    if not files:
        files = [
            {
                "table": table,
                "filename": DEFAULT_FILENAMES.get(table, f"{table}.csv"),
                "path": _relpath(source / DEFAULT_FILENAMES.get(table, f"{table}.csv"), root),
                "exists": False,
                "non_empty": False,
                "record_count": 0,
                "required_fields": list(fields),
                "missing_fields": list(fields),
                "extra_fields": [],
                "blockers": [f"source_{table}_file_missing"],
                "row_validation": _empty_row_validation(),
            }
            for table, fields in REQUIRED_LOCAL_CSV_FILES.items()
        ]

    status = "incoming_drop_ready_for_import" if not blockers else "incoming_drop_blocked"
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated,
        "commit": _git(["rev-parse", "--short", "HEAD"], cwd=root),
        "branch": _git(["branch", "--show-current"], cwd=root),
        "asset": "us_equity",
        "status": status,
        "allowed_statuses": sorted(ALLOWED_STATUSES),
        "source_dir": _relpath(source, root),
        "bundle_id": bundle_id,
        "required_file_count": len(REQUIRED_LOCAL_CSV_FILES),
        "ready_file_count": sum(1 for item in files if item.get("blockers") == []),
        "drop_file_contract": drop_file_contract,
        "files": files,
        "row_validation_summary": row_validation_summary,
        "blockers": _dedupe(blockers),
        "operator_next_actions": _operator_next_actions(
            source_exists=source.exists(),
            source_dir_display=_relpath(source, root),
            bundle_id=bundle_id,
        ),
        "preferred_import_command": (
            "python scripts/import_us_equity_local_csv_production_bundle.py "
            f"--source-dir {DEFAULT_SOURCE_DIR.as_posix()} --bundle-id {bundle_id} "
            "--promotion-clean-allowed"
        ),
        "post_import_commands": _post_import_commands(bundle_id),
        "guardrails": {
            "diagnostic_only": True,
            "source_vendor_data_modified": False,
            "missing_pit_evidence_synthesized": False,
            "configuration_mutated_by_this_report": False,
            "production_bundle_written": False,
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
    if payload["status"] not in ALLOWED_STATUSES:
        raise AssertionError(f"invalid incoming drop readiness status: {payload['status']}")
    _write_json(_resolve(root, output), payload)
    _write_text(_resolve(root, markdown_output), _markdown(payload))
    return payload


def _file_readiness(
    table: str,
    filename: str,
    path: Path,
    required_fields: list[str],
    source_record_ids: set[str],
) -> dict[str, Any]:
    blockers: list[str] = []
    exists = path.exists()
    non_empty = bool(exists and path.stat().st_size > 0)
    headers: list[str] = []
    record_count = 0
    missing_fields = list(required_fields)
    extra_fields: list[str] = []
    row_validation = _empty_row_validation()
    if not exists:
        blockers.append(f"source_{table}_file_missing")
    elif path.suffix.lower() != ".csv":
        blockers.append(f"source_{table}_file_not_csv")
    elif not non_empty:
        blockers.append(f"source_{table}_file_empty")
    else:
        try:
            with path.open("r", encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                headers = list(reader.fieldnames or [])
                rows = [dict(row) for row in reader]
                record_count = len(rows)
        except UnicodeDecodeError:
            blockers.append(f"source_{table}_file_not_utf8")
        except csv.Error:
            blockers.append(f"source_{table}_csv_parse_error")
        missing_fields = [field for field in required_fields if field not in headers]
        extra_fields = [field for field in headers if field not in required_fields]
        blockers.extend(f"source_{table}_{field}_missing" for field in missing_fields)
        if record_count <= 0:
            blockers.append(f"source_{table}_file_empty")
        if not missing_fields:
            row_validation = _validate_rows(table, rows, source_record_ids)
            blockers.extend(_list_of_str(row_validation.get("blockers")))
    return {
        "table": table,
        "filename": filename,
        "path": path.as_posix(),
        "exists": exists,
        "non_empty": non_empty and record_count > 0,
        "record_count": record_count,
        "required_fields": list(required_fields),
        "missing_fields": missing_fields,
        "extra_fields": extra_fields,
        "blockers": _dedupe(blockers),
        "row_validation": row_validation,
    }


def _validate_rows(table: str, rows: list[dict[str, str]], source_record_ids: set[str]) -> dict[str, Any]:
    blockers: list[str] = []
    issues: list[dict[str, Any]] = []
    issue_count = 0
    date_fields = set(DATE_FIELDS_BY_FILE.get(table, []))
    for row_number, row in enumerate(rows, start=2):
        source_record_id = str(row.get("source_record_id", "") or "").strip()
        if not source_record_id:
            issue_count = _add_row_issue(
                issues,
                issue_count,
                table=table,
                row_number=row_number,
                field="source_record_id",
                issue="missing",
                blocker=f"source_{table}_source_record_id_missing",
                value=source_record_id,
            )
        elif source_record_id in source_record_ids:
            issue_count = _add_row_issue(
                issues,
                issue_count,
                table=table,
                row_number=row_number,
                field="source_record_id",
                issue="duplicate",
                blocker="source_record_id_duplicate",
                value=source_record_id,
            )
        else:
            source_record_ids.add(source_record_id)
        for field in date_fields:
            value = str(row.get(field, "") or "").strip()
            if value and not _is_iso_date(value):
                issue_count = _add_row_issue(
                    issues,
                    issue_count,
                    table=table,
                    row_number=row_number,
                    field=field,
                    issue="invalid_date",
                    blocker=f"source_{table}_{field}_invalid_date",
                    value=value,
                )
        if table == "universe_membership_events":
            event_type = str(row.get("event_type", "") or "").strip()
            if event_type not in MEMBERSHIP_EVENT_TYPES:
                issue_count = _add_row_issue(
                    issues,
                    issue_count,
                    table=table,
                    row_number=row_number,
                    field="event_type",
                    issue="invalid_membership_event_type",
                    blocker="source_universe_membership_events_event_type_invalid",
                    value=event_type,
                )
        if table == "corporate_actions":
            event_type = str(row.get("event_type", "") or "").strip()
            if event_type not in CORPORATE_ACTION_EVENT_TYPES:
                issue_count = _add_row_issue(
                    issues,
                    issue_count,
                    table=table,
                    row_number=row_number,
                    field="event_type",
                    issue="invalid_corporate_action_event_type",
                    blocker="source_corporate_actions_event_type_invalid",
                    value=event_type,
                )
        if table == "macro_release_calendar":
            available_time = str(row.get("available_time_utc", "") or "").strip()
            if not available_time:
                issue_count = _add_row_issue(
                    issues,
                    issue_count,
                    table=table,
                    row_number=row_number,
                    field="available_time_utc",
                    issue="missing",
                    blocker="source_macro_release_calendar_available_time_utc_missing",
                    value=available_time,
                )
            elif not _is_iso_utc_datetime(available_time):
                issue_count = _add_row_issue(
                    issues,
                    issue_count,
                    table=table,
                    row_number=row_number,
                    field="available_time_utc",
                    issue="invalid_utc_datetime",
                    blocker="source_macro_release_calendar_available_time_utc_invalid",
                    value=available_time,
                )
    blockers = _dedupe([str(issue.get("blocker")) for issue in issues])
    return {
        "checked_rows": len(rows),
        "issue_count": issue_count,
        "reported_issue_count": len(issues),
        "issue_truncation_applied": issue_count > len(issues),
        "blockers": blockers,
        "issues": issues,
    }


def _add_row_issue(
    issues: list[dict[str, Any]],
    issue_count: int,
    *,
    table: str,
    row_number: int,
    field: str,
    issue: str,
    blocker: str,
    value: str,
) -> int:
    next_count = issue_count + 1
    if len(issues) < MAX_ROW_VALIDATION_ISSUES_PER_FILE:
        issues.append(
            {
                "table": table,
                "row_number": row_number,
                "field": field,
                "issue": issue,
                "blocker": blocker,
                "value": value,
            }
        )
    return next_count


def _empty_row_validation() -> dict[str, Any]:
    return {
        "checked_rows": 0,
        "issue_count": 0,
        "reported_issue_count": 0,
        "issue_truncation_applied": False,
        "blockers": [],
        "issues": [],
    }


def _merge_row_validation(summary: dict[str, Any], validation: object) -> None:
    if not isinstance(validation, Mapping):
        return
    checked_rows = int(validation.get("checked_rows", 0) or 0)
    issue_count = int(validation.get("issue_count", 0) or 0)
    reported_issue_count = int(validation.get("reported_issue_count", 0) or 0)
    if checked_rows > 0:
        summary["checked_file_count"] = int(summary["checked_file_count"]) + 1
    summary["checked_row_count"] = int(summary["checked_row_count"]) + checked_rows
    summary["issue_count"] = int(summary["issue_count"]) + issue_count
    summary["reported_issue_count"] = int(summary["reported_issue_count"]) + reported_issue_count
    summary["issue_truncation_applied"] = bool(summary["issue_truncation_applied"]) or bool(
        validation.get("issue_truncation_applied", False)
    )


def _drop_file_contract(source: Path, source_is_dir: bool) -> dict[str, Any]:
    expected_filenames = list(DEFAULT_FILENAMES.values())
    expected = set(expected_filenames)
    observed_files: list[str] = []
    unexpected_files: list[str] = []
    blockers: list[str] = []
    if source_is_dir:
        for path in sorted(source.iterdir(), key=lambda item: item.name.lower()):
            if path.is_dir():
                unexpected_files.append(path.name)
                blockers.append(f"unexpected_vendor_drop_directory:{path.name}")
                continue
            if not path.is_file():
                continue
            observed_files.append(path.name)
            if path.name not in expected:
                unexpected_files.append(path.name)
                if path.suffix.lower() == ".csv":
                    blockers.append(f"unexpected_vendor_drop_csv_file:{path.name}")
                elif path.suffix.lower() in {".parquet", ".xlsx", ".xls"}:
                    blockers.append(f"unsupported_vendor_drop_file:{path.name}")
                else:
                    blockers.append(f"unexpected_vendor_drop_file:{path.name}")
    return {
        "exact_required_file_count": len(expected_filenames),
        "expected_filenames": expected_filenames,
        "observed_file_count": len(observed_files),
        "observed_files": observed_files,
        "unexpected_file_count": len(unexpected_files),
        "unexpected_files": unexpected_files,
        "blockers": _dedupe(blockers),
        "exactly_six_csv_files_required": True,
        "empty_templates_are_not_valid_evidence": True,
    }


def _is_iso_date(value: str) -> bool:
    try:
        date.fromisoformat(value[:10])
        return len(value) >= 10
    except ValueError:
        return False


def _is_iso_utc_datetime(value: str) -> bool:
    if not value.endswith("Z") or "T" not in value:
        return False
    normalized = value[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return False
    return parsed.tzinfo is not None


def _markdown(payload: Mapping[str, Any]) -> str:
    lines = [
        "# US Equity Incoming Drop Readiness",
        "",
        f"生成时间：`{payload.get('generated_at')}`",
        "",
        f"- 状态：`{payload.get('status')}`",
        f"- source：`{payload.get('source_dir')}`",
        f"- ready files：`{payload.get('ready_file_count')}` / `{payload.get('required_file_count')}`",
        f"- import：`{payload.get('preferred_import_command')}`",
        "",
        "## Operator Next Actions",
        "",
    ]
    lines.extend(f"- `{item}`" for item in _list_of_str(payload.get("operator_next_actions")))
    lines.extend(
        [
            "",
            "## Drop File Contract",
            "",
        ]
    )
    contract = _mapping(payload.get("drop_file_contract"))
    lines.append(f"- exact_required_file_count: `{contract.get('exact_required_file_count')}`")
    lines.append(f"- observed_file_count: `{contract.get('observed_file_count')}`")
    lines.append(f"- unexpected_file_count: `{contract.get('unexpected_file_count')}`")
    lines.append("- expected_filenames:")
    lines.extend(f"  - `{item}`" for item in _list_of_str(contract.get("expected_filenames")))
    unexpected = _list_of_str(contract.get("unexpected_files"))
    if unexpected:
        lines.append("- unexpected_files:")
        lines.extend(f"  - `{item}`" for item in unexpected)
    lines.extend(
        [
            "",
            "## Required CSV",
            "",
            "| table | filename | records | missing fields | blockers |",
            "| --- | --- | ---: | --- | --- |",
        ]
    )
    for item in _list(payload.get("files")):
        if not isinstance(item, Mapping):
            continue
        missing = ", ".join(_list_of_str(item.get("missing_fields")))
        blockers = ", ".join(_list_of_str(item.get("blockers")))
        lines.append(
            f"| `{item.get('table')}` | `{item.get('filename')}` | `{item.get('record_count')}` | `{missing}` | `{blockers}` |"
        )
    lines.extend(["", "## Blockers", ""])
    blockers = _list_of_str(payload.get("blockers"))
    lines.extend([f"- `{item}`" for item in blockers] if blockers else ["- None"])
    lines.extend(["", "## Guardrails", ""])
    lines.extend(f"- `{key}` = `{value}`" for key, value in dict(payload.get("guardrails", {})).items())
    return "\n".join(lines)


def _operator_next_actions(*, source_exists: bool, source_dir_display: str, bundle_id: str) -> list[str]:
    actions = [
        "Run: python scripts/build_us_equity_manual_vendor_drop_package.py",
    ]
    if not source_exists:
        actions.append(f"Create directory: {source_dir_display}")
    actions.extend(
        [
            "Copy the six licensed CSV files into the incoming drop directory using docs/us_equity_manual_vendor_drop_templates headers.",
            "Do not use header-only templates, parquet, xlsx, or unlicensed exports as production evidence.",
            f"Run readiness: python scripts/build_us_equity_incoming_drop_readiness_report.py --source-dir {source_dir_display} --bundle-id {bundle_id}",
            f"Only after readiness is clean, run import: python scripts/import_us_equity_local_csv_production_bundle.py --source-dir {source_dir_display} --bundle-id {bundle_id} --promotion-clean-allowed",
        ]
    )
    return actions


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
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _list_of_str(value: Any) -> list[str]:
    return [str(item) for item in value if str(item)] if isinstance(value, list) else []


def _dedupe(values: list[str]) -> list[str]:
    out = []
    seen = set()
    for value in values:
        if value and value not in seen:
            seen.add(value)
            out.append(value)
    return out


def _utc_z_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _git(args: list[str], *, cwd: Path) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=cwd, stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:
        return "unknown"


def main() -> None:
    parser = argparse.ArgumentParser(description="Build US equity manual incoming drop readiness report.")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--source-dir", default=str(DEFAULT_SOURCE_DIR))
    parser.add_argument("--bundle-id", default=DEFAULT_BUNDLE_ID)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--markdown-output", default=str(DEFAULT_MARKDOWN_OUTPUT))
    parser.add_argument("--generated-at", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    payload = build_us_equity_incoming_drop_readiness_report(
        repo_root=Path(args.repo_root),
        source_dir=Path(args.source_dir),
        bundle_id=args.bundle_id,
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
