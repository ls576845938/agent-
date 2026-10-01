#!/usr/bin/env python3
"""Generate the operator handoff package for a manual US equity PIT CSV drop."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone
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
from scripts.build_us_equity_local_csv_bundle_manifest import DEFAULT_FILENAMES  # noqa: E402
from scripts.build_us_equity_pit_procurement_readiness_report import (  # noqa: E402
    ACCEPTABLE_SOURCE_ROUTES,
    SUPPLEMENTAL_SOURCE_ROUTES,
    UNACCEPTABLE_SOURCES,
)
from scripts.import_us_equity_local_csv_production_bundle import (  # noqa: E402
    DEFAULT_BUNDLE_ID,
    DEFAULT_SAMPLE_END,
    DEFAULT_SAMPLE_START,
    DEFAULT_SOURCE_DIR,
)


SCHEMA_VERSION = "us_equity_manual_vendor_drop_package_report_v1"
DEFAULT_TEMPLATE_ROOT = Path("docs/us_equity_manual_vendor_drop_templates")
DEFAULT_FIELD_DICTIONARY = Path("docs/us_equity_manual_vendor_drop_field_dictionary.md")
DEFAULT_HANDOFF_DOC = Path("docs/us_equity_manual_vendor_drop_handoff.md")
DEFAULT_OUTPUT = Path("artifacts/us_equity_data_lineage/latest/us_equity_manual_vendor_drop_package_report.json")
DEFAULT_MARKDOWN_OUTPUT = Path("../学习资料/量化交易业务闭环/系统评估/US Equity 生产PIT数据人工交付包.md")


def build_us_equity_manual_vendor_drop_package(
    *,
    repo_root: Path | None = None,
    template_root: Path = DEFAULT_TEMPLATE_ROOT,
    field_dictionary: Path = DEFAULT_FIELD_DICTIONARY,
    handoff_doc: Path = DEFAULT_HANDOFF_DOC,
    output: Path = DEFAULT_OUTPUT,
    markdown_output: Path = DEFAULT_MARKDOWN_OUTPUT,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at or _utc_z_now()
    templates = _write_templates(_resolve(root, template_root))
    dictionary_rows = _field_dictionary_rows()
    handoff = _handoff_markdown(dictionary_rows)
    dictionary = _field_dictionary_markdown(dictionary_rows)

    _write_text(_resolve(root, field_dictionary), dictionary)
    _write_text(_resolve(root, handoff_doc), handoff)

    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated,
        "commit": _git(["rev-parse", "--short", "HEAD"], cwd=root),
        "branch": _git(["branch", "--show-current"], cwd=root),
        "asset": "us_equity",
        "status": "manual_vendor_drop_package_ready",
        "incoming_drop_dir": DEFAULT_SOURCE_DIR.as_posix(),
        "default_bundle_id": DEFAULT_BUNDLE_ID,
        "template_root": _relpath(_resolve(root, template_root), root),
        "template_files": [
            {
                "table": table,
                "filename": DEFAULT_FILENAMES[table],
                "path": _relpath(path, root),
                "required_fields": list(REQUIRED_LOCAL_CSV_FILES[table]),
                "header_sha256": _sha256_text(",".join(REQUIRED_LOCAL_CSV_FILES[table])),
                "template_file_sha256": _sha256_file(path),
            }
            for table, path in templates.items()
        ],
        "field_dictionary": _relpath(_resolve(root, field_dictionary), root),
        "handoff_doc": _relpath(_resolve(root, handoff_doc), root),
        "field_count": len(dictionary_rows),
        "required_table_count": len(REQUIRED_LOCAL_CSV_FILES),
        "required_tables": _required_tables(),
        "source_boundary_rules": _source_boundary_rules(),
        "operator_checklist": _operator_checklist(),
        "operator_commands": _operator_commands(),
        "copy_readiness_checks": _copy_readiness_checks(),
        "acceptance_rules": _acceptance_rules(),
        "guardrails": {
            "templates_only": True,
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
    _write_text(_resolve(root, markdown_output), _summary_markdown(payload))
    return payload


def _write_templates(template_root: Path) -> dict[str, Path]:
    template_root.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}
    for table, fields in REQUIRED_LOCAL_CSV_FILES.items():
        path = template_root / DEFAULT_FILENAMES[table]
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(fields)
        paths[table] = path
    return paths


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


def _field_dictionary_rows() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for table, fields in REQUIRED_LOCAL_CSV_FILES.items():
        date_fields = set(DATE_FIELDS_BY_FILE.get(table, []))
        for field in fields:
            rows.append(
                {
                    "table": table,
                    "filename": DEFAULT_FILENAMES[table],
                    "field": field,
                    "type_hint": _type_hint(table, field, date_fields),
                    "required": "yes",
                    "description": _field_description(table, field),
                    "validation": _field_validation(table, field, date_fields),
                }
            )
    return rows


def _type_hint(table: str, field: str, date_fields: set[str]) -> str:
    if field in date_fields:
        return "date:YYYY-MM-DD"
    if field == "available_time_utc":
        return "datetime:UTC-Z"
    if field in {"ratio", "cash_amount", "delisting_return", "raw_close", "adjusted_close", "split_factor", "dividend_adjustment", "total_adjustment_factor", "replay_adjusted_close", "replay_error"}:
        return "decimal"
    if field == "event_type":
        return "enum"
    if field in {"source_record_id", "security_id", "series_id"}:
        return "stable_id"
    return "string"


def _field_validation(table: str, field: str, date_fields: set[str]) -> str:
    if field in date_fields:
        return "ISO date; no future-as-of leakage."
    if table == "macro_release_calendar" and field == "available_time_utc":
        return "UTC timestamp ending with Z; must be the earliest usable release time."
    if table == "universe_membership_events" and field == "event_type":
        return "One of: " + ", ".join(sorted(MEMBERSHIP_EVENT_TYPES))
    if table == "corporate_actions" and field == "event_type":
        return "One of: " + ", ".join(sorted(CORPORATE_ACTION_EVENT_TYPES))
    if field == "source_record_id":
        return "Globally unique across all six CSV files."
    if field == "security_id":
        return "Stable issuer/security identifier and must resolve in symbol_mapping."
    if field == "replay_error":
        return "Absolute value must be within adjustment replay tolerance."
    return "Non-empty unless explicitly inapplicable; keep provider source semantics."


def _field_description(table: str, field: str) -> str:
    descriptions = {
        "security_id": "Stable security identifier used across all equity lineage files.",
        "ticker": "Displayed ticker at the row's effective time, not a backfilled current ticker.",
        "source_record_id": "Unique provider/source row identifier for audit and duplicate detection.",
        "universe_name": "Name of the PIT universe, such as SP500, ETF_POOL, or US_CORE.",
        "event_type": "Provider event classification for membership or corporate action lineage.",
        "effective_date": "Date on which the event becomes effective for PIT research.",
        "end_date": "Optional end date for a membership or mapping interval.",
        "delisting_date": "Date when the security leaves trading/listing coverage.",
        "delisting_reason": "Provider reason for delisting, merger, liquidation, acquisition, or other removal.",
        "last_trade_date": "Last known trading date before delisting or removal.",
        "delisting_return": "Return impact associated with delisting if supplied by the provider.",
        "ex_date": "Corporate action ex-date.",
        "ratio": "Split or event ratio when applicable.",
        "cash_amount": "Cash dividend or cash component when applicable.",
        "old_symbol": "Previous ticker or symbol in a symbol-change event.",
        "new_symbol": "New ticker or symbol in a symbol-change event.",
        "start_date": "Start of symbol or identifier mapping interval.",
        "figi": "FIGI identifier when available.",
        "cik": "SEC CIK when available.",
        "cusip": "CUSIP when license permits storage.",
        "permno": "CRSP PERMNO when available and licensed.",
        "exchange": "Exchange or venue identifier at the mapping interval.",
        "date": "Market date for adjustment replay row.",
        "raw_close": "Unadjusted close used as replay input.",
        "adjusted_close": "Provider adjusted close used as target value.",
        "split_factor": "Split adjustment factor.",
        "dividend_adjustment": "Dividend adjustment component.",
        "total_adjustment_factor": "Total raw-to-adjusted factor.",
        "replay_adjusted_close": "Adjusted close recomputed by the system or provider replay.",
        "replay_error": "Difference between adjusted_close and replay_adjusted_close.",
        "series_id": "Macro series identifier.",
        "observation_period_start": "Macro observation period start date.",
        "observation_period_end": "Macro observation period end date.",
        "release_date": "Official macro release date.",
        "available_time_utc": "Earliest UTC timestamp when the macro observation is usable by a strategy.",
    }
    return descriptions.get(field, f"{table}.{field}")


def _operator_commands() -> list[str]:
    return [
        "python scripts/build_us_equity_manual_vendor_drop_package.py",
        "python scripts/build_us_equity_incoming_drop_readiness_report.py",
        (
            "python scripts/import_us_equity_local_csv_production_bundle.py "
            f"--source-dir {DEFAULT_SOURCE_DIR.as_posix()} "
            f"--bundle-id {DEFAULT_BUNDLE_ID} "
            f"--sample-start {DEFAULT_SAMPLE_START} "
            f"--sample-end {DEFAULT_SAMPLE_END} "
            '--license-note "<license scope>" '
            "--promotion-clean-allowed"
        ),
        "python scripts/build_us_equity_production_bundle_activation_report.py --bundle-id manual_vendor_bundle_v1 --license-reviewed",
        "python scripts/run_us_equity_daily_production_line.py",
    ]


def _operator_checklist() -> list[dict[str, Any]]:
    return [
        {
            "step_id": "build_handoff_package",
            "label": "Build the handoff package and templates",
            "command": "python scripts/build_us_equity_manual_vendor_drop_package.py",
            "expected_evidence": "us_equity_manual_vendor_drop_package_report.status == manual_vendor_drop_package_ready",
            "unlocks": "operator_drop_preparation_only",
        },
        {
            "step_id": "create_incoming_drop_dir",
            "label": "Create the incoming vendor drop directory",
            "command": f"New-Item -ItemType Directory -Force -Path {DEFAULT_SOURCE_DIR.as_posix()}",
            "expected_evidence": f"{DEFAULT_SOURCE_DIR.as_posix()} exists and is a directory",
            "unlocks": "csv_copy_step_only",
        },
        {
            "step_id": "copy_six_licensed_csv_files",
            "label": "Copy exactly six licensed CSV files into the incoming drop",
            "command": "manual_file_copy",
            "expected_evidence": "incoming drop contains the six required CSV filenames and no parquet/xlsx substitutes",
            "unlocks": "incoming_drop_readiness_check",
        },
        {
            "step_id": "run_incoming_drop_readiness",
            "label": "Run incoming drop readiness",
            "command": "python scripts/build_us_equity_incoming_drop_readiness_report.py",
            "expected_evidence": "us_equity_incoming_drop_readiness_report.status == incoming_drop_ready_for_import",
            "unlocks": "local_csv_import_only",
        },
        {
            "step_id": "import_local_csv_bundle",
            "label": "Import the local CSV production bundle",
            "command": _operator_commands()[2],
            "expected_evidence": "us_equity_local_csv_production_bundle_import_report.status == production_bundle_imported",
            "unlocks": "activation_preflight_only",
        },
        {
            "step_id": "run_acceptance_and_activation",
            "label": "Run PIT bundle acceptance and activation preflight",
            "command": "python scripts/run_us_equity_pit_bundle_acceptance.py",
            "expected_evidence": "pit acceptance ready and activation candidate emitted for manual config apply",
            "unlocks": "manual_config_apply_review_only",
        },
        {
            "step_id": "rerun_daily_production_line",
            "label": "Rerun the daily production line after data evidence changes",
            "command": "python scripts/run_us_equity_daily_production_line.py",
            "expected_evidence": "daily report updates production_pit_drop and remediation closure state",
            "unlocks": "status_refresh_only_no_execution_permission",
        },
    ]


def _copy_readiness_checks() -> list[dict[str, Any]]:
    required_names = [DEFAULT_FILENAMES[table] for table in REQUIRED_LOCAL_CSV_FILES]
    names_literal = "@(" + ", ".join(f"'{name}'" for name in required_names) + ")"
    source_dir = DEFAULT_SOURCE_DIR.as_posix()
    return [
        {
            "check_id": "incoming_dir_exists",
            "command": f"Test-Path '{source_dir}' -PathType Container",
            "expected_result": "True",
            "failure_means": "Incoming drop directory has not been created.",
            "blocks_import": True,
        },
        {
            "check_id": "all_required_filenames_present",
            "command": f"$required={names_literal}; $required | Where-Object {{ -not (Test-Path (Join-Path '{source_dir}' $_) -PathType Leaf) }}",
            "expected_result": "No output",
            "failure_means": "At least one licensed PIT CSV file is missing or named incorrectly.",
            "blocks_import": True,
        },
        {
            "check_id": "no_header_only_templates",
            "command": f"$required={names_literal}; $required | ForEach-Object {{ $p=Join-Path '{source_dir}' $_; if ((Import-Csv $p).Count -lt 1) {{ $_ }} }}",
            "expected_result": "No output",
            "failure_means": "A copied CSV is empty/header-only; templates are not valid vendor data.",
            "blocks_import": True,
        },
        {
            "check_id": "run_contract_preflight",
            "command": "python scripts/build_us_equity_vendor_drop_preflight_report.py",
            "expected_result": "us_equity_vendor_drop_preflight_report.status != vendor_drop_preflight_waiting_for_vendor_files",
            "failure_means": "The operator copy contract is not yet satisfied.",
            "blocks_import": True,
        },
    ]


def _acceptance_rules() -> list[str]:
    return [
        "Use the exact six CSV filenames; do not substitute parquet/xlsx files in the incoming drop.",
        "Every CSV must include the exact header order from docs/us_equity_manual_vendor_drop_templates.",
        "Templates are header-only and are not valid vendor data.",
        "Tiingo, IBKR, FRED, yfinance, fixtures, templates, and latest-only exports are not standalone production PIT evidence.",
        "All date fields use YYYY-MM-DD; macro available_time_utc uses UTC timestamp ending with Z.",
        "source_record_id must be globally unique across all six CSVs.",
        "security_id must be stable and effective-dated through symbol_mapping.",
        "The package does not grant promotion-clean status and cannot unlock paper/live trading.",
    ]


def _source_boundary_rules() -> dict[str, Any]:
    return {
        "acceptable_routes": [
            {
                "route_id": str(item.get("route_id", "")),
                "label": str(item.get("label", "")),
                "mapping_doc": str(item.get("mapping_doc", "")),
                "must_normalize_to_local_csv_contract": True,
            }
            for item in ACCEPTABLE_SOURCE_ROUTES
        ],
        "supplemental_only_routes": [
            {
                "route_id": str(item.get("route_id", "")),
                "label": str(item.get("label", "")),
                "usable_for": list(item.get("usable_for", [])),
                "not_sufficient_for": list(item.get("not_sufficient_for", [])),
            }
            for item in SUPPLEMENTAL_SOURCE_ROUTES
        ],
        "rejected_routes": list(UNACCEPTABLE_SOURCES),
        "promotion_clean_rule": (
            "No source is promotion-clean until the copied CSVs pass local schema, hash, record-count, PIT, "
            "survivorship, corporate-action, identifier, macro-release, and adjustment-replay verification."
        ),
    }


def _handoff_markdown(dictionary_rows: list[Mapping[str, str]]) -> str:
    lines = [
        "# US Equity Manual Vendor Drop Handoff",
        "",
        "This package is the operator-facing contract for a licensed production PIT data drop.",
        "",
        f"- Incoming drop dir: `{DEFAULT_SOURCE_DIR.as_posix()}`",
        f"- Default bundle id: `{DEFAULT_BUNDLE_ID}`",
        f"- Template root: `{DEFAULT_TEMPLATE_ROOT.as_posix()}`",
        f"- Field dictionary: `{DEFAULT_FIELD_DICTIONARY.as_posix()}`",
        "",
        "## Required Files",
        "",
    ]
    for table, fields in REQUIRED_LOCAL_CSV_FILES.items():
        lines.append(f"- `{DEFAULT_FILENAMES[table]}`: {len(fields)} required fields for `{table}`")
    lines.extend(["", "## Commands", ""])
    lines.extend(f"```powershell\n{command}\n```" for command in _operator_commands())
    lines.extend(["", "## Operator Checklist", ""])
    for item in _operator_checklist():
        lines.append(f"- `{item['step_id']}`: {item['label']} -> {item['expected_evidence']}")
    lines.extend(["", "## Acceptance Rules", ""])
    lines.extend(f"- {rule}" for rule in _acceptance_rules())
    lines.extend(["", "## Source Boundary Rules", ""])
    boundaries = _source_boundary_rules()
    lines.extend(["### Acceptable only after normalization", ""])
    lines.extend(f"- `{item['route_id']}`: {item['label']}" for item in boundaries["acceptable_routes"])
    lines.extend(["", "### Supplemental only", ""])
    lines.extend(
        f"- `{item['route_id']}`: not sufficient for `{', '.join(item['not_sufficient_for'][:2])}`"
        for item in boundaries["supplemental_only_routes"]
    )
    lines.extend(["", "## Guardrails", ""])
    lines.extend(
        [
            "- This handoff contains no vendor data.",
            "- Do not commit licensed CSV drops.",
            "- Do not treat readiness/import success as strategy validation or live readiness.",
        ]
    )
    return "\n".join(lines)


def _field_dictionary_markdown(rows: list[Mapping[str, str]]) -> str:
    lines = [
        "# US Equity Manual Vendor Drop Field Dictionary",
        "",
        "| table | filename | field | type | required | validation | description |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(
            f"| `{row['table']}` | `{row['filename']}` | `{row['field']}` | `{row['type_hint']}` | `{row['required']}` | {row['validation']} | {row['description']} |"
        )
    return "\n".join(lines)


def _summary_markdown(payload: Mapping[str, Any]) -> str:
    lines = [
        "# US Equity 生产PIT数据人工交付包",
        "",
        f"生成时间：`{payload.get('generated_at')}`",
        "",
        f"- 状态：`{payload.get('status')}`",
        f"- incoming drop：`{payload.get('incoming_drop_dir')}`",
        f"- 模板目录：`{payload.get('template_root')}`",
        f"- 字段字典：`{payload.get('field_dictionary')}`",
        f"- 交付说明：`{payload.get('handoff_doc')}`",
        f"- 字段数：`{payload.get('field_count')}`",
        "",
        "## Required Files",
        "",
        "| table | filename | fields |",
        "| --- | --- | ---: |",
    ]
    for item in _list(payload.get("template_files")):
        if isinstance(item, Mapping):
            lines.append(f"| `{item.get('table')}` | `{item.get('filename')}` | `{len(_list(item.get('required_fields')))}` |")
    lines.extend(["", "## Commands", ""])
    lines.extend(f"```powershell\n{command}\n```" for command in _list_of_str(payload.get("operator_commands")))
    lines.extend(["", "## Operator Checklist", ""])
    for item in _list(payload.get("operator_checklist")):
        if isinstance(item, Mapping):
            lines.append(
                f"- `{item.get('step_id')}`：{item.get('label')}；evidence=`{item.get('expected_evidence')}`；unlocks=`{item.get('unlocks')}`"
            )
    lines.extend(["", "## Copy Readiness Checks", ""])
    for item in _list(payload.get("copy_readiness_checks")):
        if isinstance(item, Mapping):
            lines.append(f"- `{item.get('check_id')}`：expected=`{item.get('expected_result')}`；blocks_import=`{item.get('blocks_import')}`")
            lines.append(f"```powershell\n{item.get('command')}\n```")
    boundaries = _mapping(payload.get("source_boundary_rules"))
    lines.extend(["", "## Source Boundary Rules", ""])
    lines.append(f"- promotion_clean_rule: `{boundaries.get('promotion_clean_rule')}`")
    for item in _list(boundaries.get("supplemental_only_routes")):
        if isinstance(item, Mapping):
            lines.append(f"- supplemental_only `{item.get('route_id')}`: not sufficient for `{', '.join(_list_of_str(item.get('not_sufficient_for'))[:2])}`")
    lines.extend(["", "## Guardrails", ""])
    lines.extend(f"- `{key}` = `{value}`" for key, value in dict(payload.get("guardrails", {})).items())
    return "\n".join(lines)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list_of_str(value: Any) -> list[str]:
    return [str(item) for item in value if str(item)] if isinstance(value, list) else []


def _utc_z_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _git(args: list[str], *, cwd: Path) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=cwd, stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:
        return "unknown"


def main() -> None:
    parser = argparse.ArgumentParser(description="Build US equity manual vendor drop package.")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--template-root", default=str(DEFAULT_TEMPLATE_ROOT))
    parser.add_argument("--field-dictionary", default=str(DEFAULT_FIELD_DICTIONARY))
    parser.add_argument("--handoff-doc", default=str(DEFAULT_HANDOFF_DOC))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--markdown-output", default=str(DEFAULT_MARKDOWN_OUTPUT))
    parser.add_argument("--generated-at", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    payload = build_us_equity_manual_vendor_drop_package(
        repo_root=Path(args.repo_root),
        template_root=Path(args.template_root),
        field_dictionary=Path(args.field_dictionary),
        handoff_doc=Path(args.handoff_doc),
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
