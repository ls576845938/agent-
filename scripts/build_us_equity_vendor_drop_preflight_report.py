#!/usr/bin/env python3
"""Preflight the manual US equity PIT vendor-drop workspace."""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from quant_us.data.lineage.local_csv_provider import REQUIRED_LOCAL_CSV_FILES
from scripts.build_us_equity_local_csv_bundle_manifest import DEFAULT_FILENAMES


SCHEMA_VERSION = "us_equity_vendor_drop_preflight_report_v1"
DEFAULT_PACKAGE_REPORT = Path("artifacts/us_equity_data_lineage/latest/us_equity_manual_vendor_drop_package_report.json")
DEFAULT_SOURCE_DIR = Path("data/external/us_equity_lineage/incoming/manual_vendor_drop")
DEFAULT_OUTPUT = Path("artifacts/us_equity_data_lineage/latest/us_equity_vendor_drop_preflight_report.json")
DEFAULT_MARKDOWN_OUTPUT = Path("../学习资料/量化交易业务闭环/系统评估/US Equity Vendor Drop Preflight.md")


def build_us_equity_vendor_drop_preflight_report(
    *,
    repo_root: Path | None = None,
    package_report: Path = DEFAULT_PACKAGE_REPORT,
    source_dir: Path = DEFAULT_SOURCE_DIR,
    output: Path = DEFAULT_OUTPUT,
    markdown_output: Path = DEFAULT_MARKDOWN_OUTPUT,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at or _utc_z_now()
    package_path = _resolve(root, package_report)
    source = _resolve(root, source_dir)
    package = _read_json(package_path)
    package_checks = _package_checks(root, package_path, package)
    csv_checks = _csv_checks(source)
    required_files = _required_files(root, source)
    missing_required_files = [item for item in required_files if not item["ready"]]
    ready_required_files = [item for item in required_files if item["ready"]]
    file_copy_plan = _file_copy_plan(root, source, package, required_files)
    blockers = _dedupe(
        [item["blocker"] for item in package_checks if not item["passed"]]
        + [item["blocker"] for item in csv_checks if not item["passed"]]
    )
    package_ready = all(item["passed"] for item in package_checks)
    csv_ready = all(item["passed"] for item in csv_checks)
    if not package_ready:
        status = "vendor_drop_preflight_blocked"
    elif not csv_ready:
        status = "vendor_drop_preflight_waiting_for_vendor_files"
    else:
        status = "vendor_drop_preflight_ready_for_readiness_check"
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated,
        "commit": _git(["rev-parse", "--short", "HEAD"], cwd=root),
        "branch": _git(["branch", "--show-current"], cwd=root),
        "asset": "us_equity",
        "status": status,
        "allowed_statuses": [
            "vendor_drop_preflight_blocked",
            "vendor_drop_preflight_waiting_for_vendor_files",
            "vendor_drop_preflight_ready_for_readiness_check",
        ],
        "source_dir": _relpath(source, root),
        "package_report": _relpath(package_path, root),
        "required_file_count": len(REQUIRED_LOCAL_CSV_FILES),
        "ready_file_count": len(ready_required_files),
        "missing_file_count": len(missing_required_files),
        "required_files": required_files,
        "missing_required_files": missing_required_files,
        "ready_required_files": ready_required_files,
        "file_copy_plan": file_copy_plan,
        "import_metadata_requirements": _import_metadata_requirements(source_dir=_relpath(source, root)),
        "package_checks": package_checks,
        "csv_checks": csv_checks,
        "blockers": blockers,
        "operator_next_actions": _operator_next_actions(status, source_dir=_relpath(source, root)),
        "guardrails": {
            "preflight_only": True,
            "templates_only": False,
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


def _package_checks(root: Path, package_path: Path, package: Mapping[str, Any]) -> list[dict[str, Any]]:
    template_files = _list(package.get("template_files"))
    template_paths = [root / str(item.get("path", "")) for item in template_files if isinstance(item, Mapping)]
    field_dictionary = root / str(package.get("field_dictionary", ""))
    handoff_doc = root / str(package.get("handoff_doc", ""))
    return [
        _check("package_report_exists", package_path.exists(), "manual_vendor_drop_package_report_missing", _relpath(package_path, root)),
        _check(
            "package_report_ready",
            package.get("status") == "manual_vendor_drop_package_ready",
            "manual_vendor_drop_package_not_ready",
            str(package.get("status", "")),
        ),
        _check(
            "template_count",
            len(template_files) == len(REQUIRED_LOCAL_CSV_FILES),
            "manual_vendor_drop_template_count_mismatch",
            str(len(template_files)),
        ),
        _check(
            "template_files_exist",
            bool(template_paths) and all(path.exists() for path in template_paths),
            "manual_vendor_drop_template_files_missing",
            ",".join(_relpath(path, root) for path in template_paths if not path.exists()),
        ),
        _check(
            "field_dictionary_exists",
            field_dictionary.exists(),
            "manual_vendor_drop_field_dictionary_missing",
            _relpath(field_dictionary, root),
        ),
        _check("handoff_doc_exists", handoff_doc.exists(), "manual_vendor_drop_handoff_doc_missing", _relpath(handoff_doc, root)),
    ]


def _csv_checks(source: Path) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    source_exists = source.exists() and source.is_dir()
    checks.append(_check("source_dir_exists", source_exists, "source_dir_missing", str(source)))
    for table, fields in REQUIRED_LOCAL_CSV_FILES.items():
        filename = DEFAULT_FILENAMES[table]
        path = source / filename
        if not source_exists:
            checks.append(_check(f"{table}_csv_ready", False, f"{table}_csv_missing", str(path)))
            continue
        if not path.exists():
            checks.append(_check(f"{table}_csv_ready", False, f"{table}_csv_missing", str(path)))
            continue
        try:
            with path.open("r", encoding="utf-8", newline="") as handle:
                rows = list(csv.reader(handle))
        except Exception as exc:  # noqa: BLE001 - report as data preflight failure
            checks.append(_check(f"{table}_csv_ready", False, f"{table}_csv_unreadable:{type(exc).__name__}", str(path)))
            continue
        header = rows[0] if rows else []
        data_rows = rows[1:]
        header_ok = header == fields
        non_empty = len(data_rows) > 0
        passed = header_ok and non_empty
        blocker = ""
        if not header_ok:
            blocker = f"{table}_csv_header_mismatch"
        elif not non_empty:
            blocker = f"{table}_csv_header_only"
        checks.append(_check(f"{table}_csv_ready", passed, blocker, str(path)))
    return checks


def _required_files(root: Path, source: Path) -> list[dict[str, Any]]:
    files = []
    for table, fields in REQUIRED_LOCAL_CSV_FILES.items():
        filename = DEFAULT_FILENAMES[table]
        path = source / filename
        exists = path.exists()
        header: list[str] = []
        row_count = 0
        unreadable = ""
        if exists:
            try:
                with path.open("r", encoding="utf-8", newline="") as handle:
                    rows = list(csv.reader(handle))
                header = rows[0] if rows else []
                row_count = max(0, len(rows) - 1)
            except Exception as exc:  # noqa: BLE001 - report only
                unreadable = type(exc).__name__
        header_matches = exists and not unreadable and header == fields
        ready = exists and header_matches and row_count > 0
        blocker = ""
        if unreadable:
            blocker = f"{table}_csv_unreadable:{unreadable}"
        elif not exists:
            blocker = f"{table}_csv_missing"
        elif not header_matches:
            blocker = f"{table}_csv_header_mismatch"
        elif row_count <= 0:
            blocker = f"{table}_csv_header_only"
        files.append(
            {
                "table": table,
                "filename": filename,
                "path": _relpath(path, root),
                "required_fields": fields,
                "exists": exists,
                "header_matches": bool(header_matches),
                "data_row_count": row_count,
                "ready": bool(ready),
                "blocker": blocker,
            }
        )
    return files


def _file_copy_plan(
    root: Path,
    source: Path,
    package: Mapping[str, Any],
    required_files: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    template_by_table = {
        str(item.get("table")): str(item.get("path"))
        for item in _list(package.get("template_files"))
        if isinstance(item, Mapping)
    }
    plan: list[dict[str, Any]] = []
    for item in required_files:
        table = str(item["table"])
        filename = str(item["filename"])
        target = source / filename
        template_path = template_by_table.get(table, f"docs/us_equity_manual_vendor_drop_templates/{filename}")
        current_state = "ready"
        operator_action = "no_action_required"
        if not item["exists"]:
            current_state = "missing"
            operator_action = "copy_licensed_csv_with_exact_header_to_target_path"
        elif not item["header_matches"]:
            current_state = "header_mismatch"
            operator_action = "replace_file_or_reexport_with_exact_template_header"
        elif int(item["data_row_count"]) <= 0:
            current_state = "header_only"
            operator_action = "replace_template_with_licensed_vendor_rows"
        plan.append(
            {
                "table": table,
                "filename": filename,
                "template_path": template_path,
                "target_path": _relpath(target, root),
                "required_fields": list(item["required_fields"]),
                "current_state": current_state,
                "current_blocker": str(item["blocker"]),
                "operator_action": operator_action,
                "ready_after_action_requires_rerun": current_state != "ready",
            }
        )
    return plan


def _import_metadata_requirements(*, source_dir: str) -> dict[str, Any]:
    return {
        "bundle_id": "manual_vendor_bundle_v1",
        "source_provider_allowed_values": ["local_csv", "crsp", "sharadar", "polygon", "norgate", "other"],
        "source_type_required": "production",
        "required_cli_args": [
            "--source-dir",
            "--bundle-id",
            "--source-provider",
            "--source-type",
            "--sample-start",
            "--sample-end",
            "--license-note",
            "--promotion-clean-allowed",
        ],
        "optional_cli_args": [
            "--as-of-date",
            "--universe-name",
            "--price-data-reference",
        ],
        "preferred_import_command_template": (
            "python scripts/import_us_equity_local_csv_production_bundle.py "
            f"--source-dir {source_dir} --bundle-id manual_vendor_bundle_v1 "
            "--source-provider <provider> --source-type production "
            "--sample-start <YYYY-MM-DD> --sample-end <YYYY-MM-DD> "
            "--license-note \"<licensed provider scope>\" --promotion-clean-allowed"
        ),
        "notes": [
            "Do not put API keys, account numbers, or raw vendor credentials in command args or committed files.",
            "sample-start/sample-end must describe the actual licensed PIT bundle coverage.",
            "promotion-clean-allowed is only a data-lineage assertion for this import; it does not unlock paper/live trading.",
        ],
    }


def _check(check_id: str, passed: bool, blocker: str, evidence: str) -> dict[str, Any]:
    return {
        "check_id": check_id,
        "passed": bool(passed),
        "blocker": "" if passed else blocker,
        "evidence": evidence,
    }


def _operator_next_actions(status: str, *, source_dir: str) -> list[str]:
    if status == "vendor_drop_preflight_blocked":
        return [
            "Run: python scripts/build_us_equity_manual_vendor_drop_package.py",
            "Then rerun: python scripts/build_us_equity_vendor_drop_preflight_report.py",
        ]
    if status == "vendor_drop_preflight_waiting_for_vendor_files":
        return [
            f"Create directory if missing: {source_dir}",
            "Copy the licensed CSV files into the incoming drop directory using docs/us_equity_manual_vendor_drop_templates headers.",
            "Do not use header-only templates, parquet, xlsx, screenshots, or unlicensed exports as production evidence.",
            "Rerun: python scripts/build_us_equity_vendor_drop_preflight_report.py",
        ]
    return [
        f"Run readiness: python scripts/build_us_equity_incoming_drop_readiness_report.py --source-dir {source_dir} --bundle-id manual_vendor_bundle_v1",
        f"If readiness is clean, run import: python scripts/import_us_equity_local_csv_production_bundle.py --source-dir {source_dir} --bundle-id manual_vendor_bundle_v1 --promotion-clean-allowed",
    ]


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


def _dedupe(items: list[str]) -> list[str]:
    out = []
    seen = set()
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _git(args: list[str], *, cwd: Path) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=cwd, stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:
        return "unknown"


def _utc_z_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _markdown(payload: Mapping[str, Any]) -> str:
    lines = [
        "# US Equity Vendor Drop Preflight",
        "",
        f"生成时间：`{payload.get('generated_at', '')}`",
        f"状态：`{payload.get('status', '')}`",
        f"source：`{payload.get('source_dir', '')}`",
        f"ready files：`{payload.get('ready_file_count')}` / `{payload.get('required_file_count')}`",
        f"missing files：`{payload.get('missing_file_count')}`",
        "",
        "## Required Files",
        "",
        "| table | filename | ready | rows | blocker |",
        "| --- | --- | --- | ---: | --- |",
    ]
    for item in payload.get("required_files", []):
        if not isinstance(item, Mapping):
            continue
        lines.append(
            f"| `{item.get('table')}` | `{item.get('filename')}` | `{item.get('ready')}` | `{item.get('data_row_count')}` | `{item.get('blocker')}` |"
        )
    lines.extend(["", "## File Copy Plan", ""])
    lines.extend(["| table | target | template | state | action |", "| --- | --- | --- | --- | --- |"])
    for item in payload.get("file_copy_plan", []):
        if not isinstance(item, Mapping):
            continue
        lines.append(
            f"| `{item.get('table')}` | `{item.get('target_path')}` | `{item.get('template_path')}` | `{item.get('current_state')}` | `{item.get('operator_action')}` |"
        )
    metadata = payload.get("import_metadata_requirements", {})
    if isinstance(metadata, Mapping):
        lines.extend(
            [
                "",
                "## Import Metadata Requirements",
                "",
                f"- bundle_id：`{metadata.get('bundle_id')}`",
                f"- source_type_required：`{metadata.get('source_type_required')}`",
                f"- preferred command：`{metadata.get('preferred_import_command_template')}`",
                "",
                "Required args:",
            ]
        )
        lines.extend(f"- `{item}`" for item in metadata.get("required_cli_args", []))
    lines.extend(
        [
            "",
        "## Checks",
        "",
        "| check | passed | blocker | evidence |",
        "| --- | --- | --- | --- |",
        ]
    )
    for item in [*payload.get("package_checks", []), *payload.get("csv_checks", [])]:
        if not isinstance(item, Mapping):
            continue
        lines.append(
            f"| `{item.get('check_id')}` | `{item.get('passed')}` | `{item.get('blocker')}` | `{item.get('evidence')}` |"
        )
    lines.extend(["", "## Operator Next Actions", ""])
    lines.extend(f"- {item}" for item in payload.get("operator_next_actions", []))
    lines.extend(["", "## Guardrails", "", "- preflight only", "- source_vendor_data_modified=false", "- live_order_allowed=false"])
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--package-report", type=Path, default=DEFAULT_PACKAGE_REPORT)
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN_OUTPUT)
    parser.add_argument("--generated-at", default="")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    payload = build_us_equity_vendor_drop_preflight_report(
        repo_root=args.repo_root,
        package_report=args.package_report,
        source_dir=args.source_dir,
        output=args.output,
        markdown_output=args.markdown_output,
        generated_at=args.generated_at or None,
    )
    print(json.dumps({"status": payload["status"], "output": payload["outputs"]["json"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
