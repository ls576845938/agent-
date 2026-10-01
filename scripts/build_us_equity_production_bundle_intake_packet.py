#!/usr/bin/env python3
"""Build the operator intake packet for a US equity production PIT bundle.

The packet is an instruction and acceptance contract only. It does not inspect
private data values, mutate provider config, grant promotion-clean status, or
unlock paper/live trading.
"""

from __future__ import annotations

import argparse
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

from quant_us.data.lineage.local_csv_provider import REQUIRED_LOCAL_CSV_FILES  # noqa: E402
from scripts.build_us_equity_local_csv_bundle_manifest import DEFAULT_FILENAMES  # noqa: E402
from scripts.import_us_equity_local_csv_production_bundle import (  # noqa: E402
    DEFAULT_BUNDLE_ID as DEFAULT_IMPORT_BUNDLE_ID,
)
from scripts.import_us_equity_local_csv_production_bundle import (  # noqa: E402
    DEFAULT_SAMPLE_END as DEFAULT_IMPORT_SAMPLE_END,
)
from scripts.import_us_equity_local_csv_production_bundle import (  # noqa: E402
    DEFAULT_SAMPLE_START as DEFAULT_IMPORT_SAMPLE_START,
)
from scripts.import_us_equity_local_csv_production_bundle import DEFAULT_SOURCE_DIR  # noqa: E402


SCHEMA_VERSION = "us_equity_production_bundle_intake_packet_v1"
DEFAULT_SCAFFOLD_REPORT = Path("artifacts/us_equity_data_lineage/latest/us_equity_production_bundle_scaffold_report.json")
DEFAULT_PREFLIGHT_REPORT = Path("artifacts/us_equity_data_lineage/latest/production_bundle_preflight_report.json")
DEFAULT_PROVIDER_REPORT = Path("artifacts/us_equity_data_lineage/latest/provider_verification_report.json")
DEFAULT_ACQUISITION_PLAN = Path("artifacts/us_equity_data_lineage/latest/us_equity_production_data_acquisition_plan.json")
DEFAULT_OUTPUT = Path("artifacts/us_equity_data_lineage/latest/us_equity_production_bundle_intake_packet.json")
DEFAULT_MARKDOWN_OUTPUT = Path("../学习资料/量化交易业务闭环/系统评估/US Equity 生产数据包导入验收包.md")
DEFAULT_BUNDLE_ROOT = "data/external/us_equity_lineage/bundles/<bundle_id>"
DEFAULT_INCOMING_DROP_DIR = DEFAULT_SOURCE_DIR.as_posix()


def build_us_equity_production_bundle_intake_packet(
    *,
    repo_root: Path | None = None,
    scaffold_report_path: Path = DEFAULT_SCAFFOLD_REPORT,
    preflight_report_path: Path = DEFAULT_PREFLIGHT_REPORT,
    provider_report_path: Path = DEFAULT_PROVIDER_REPORT,
    acquisition_plan_path: Path = DEFAULT_ACQUISITION_PLAN,
    output: Path = DEFAULT_OUTPUT,
    markdown_output: Path = DEFAULT_MARKDOWN_OUTPUT,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at or _utc_z_now()
    scaffold = _read_json(_resolve(root, scaffold_report_path))
    preflight = _read_json(_resolve(root, preflight_report_path))
    provider = _read_json(_resolve(root, provider_report_path))
    acquisition = _read_json(_resolve(root, acquisition_plan_path))

    required_tables = _required_tables()
    current_blockers = _dedupe(
        _list_of_str(preflight.get("blockers"))
        + _list_of_str(provider.get("blockers"))
        + _list_of_str(acquisition.get("blockers"))
    )
    scaffold_ready = scaffold.get("status") == "template_ready_not_provider_evidence"
    status = "intake_packet_ready_for_data_vendor_drop" if scaffold_ready and required_tables else "intake_packet_action_required"
    blockers = [] if scaffold_ready else ["production_bundle_scaffold_report_missing_or_not_ready"]

    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated,
        "commit": _git(["rev-parse", "--short", "HEAD"], cwd=root),
        "branch": _git(["branch", "--show-current"], cwd=root),
        "asset": "us_equity",
        "status": status,
        "decision": "prepare_external_pit_bundle_drop_do_not_unlock_trading",
        "bundle_contract": {
            "incoming_drop_dir": DEFAULT_INCOMING_DROP_DIR,
            "default_import_bundle_id": DEFAULT_IMPORT_BUNDLE_ID,
            "target_bundle_root": DEFAULT_BUNDLE_ROOT,
            "manifest_name": "provider_bundle_manifest.json",
            "required_table_count": len(required_tables),
            "required_tables": required_tables,
            "accepted_source_providers": ["crsp", "sharadar", "norgate", "local_csv", "other"],
            "accepted_source_type": "production",
            "must_include_license_note": True,
            "must_include_sha256_and_record_count": True,
            "must_use_explicit_bundle_selection": True,
            "preferred_import_command": _preferred_import_command(),
        },
        "current_state": {
            "scaffold_status": scaffold.get("status"),
            "scaffold_dir": scaffold.get("scaffold_dir"),
            "preflight_pass": preflight.get("production_bundle_preflight_pass"),
            "selected_bundle_id": preflight.get("selected_bundle_id") or provider.get("selected_bundle_id"),
            "production_bundles_found": preflight.get("production_bundles_found"),
            "provider_promotion_clean": provider.get("promotion_clean"),
            "production_data_acquisition_status": acquisition.get("status"),
            "missing_contract_groups": acquisition.get("missing_contract_groups", []),
            "current_blockers": current_blockers,
        },
        "operator_steps": _operator_steps(),
        "validation_commands": _validation_commands(),
        "acceptance_criteria": _acceptance_criteria(),
        "blockers": blockers,
        "guardrails": {
            "intake_packet_only": True,
            "vendor_data_written_by_this_report": False,
            "configuration_mutated_by_this_report": False,
            "promotion_clean_granted_by_this_report": False,
            "paper_or_live_unlock_allowed": False,
            "paper_simulation_allowed": False,
            "live_order_allowed": False,
            "private_endpoint_allowed": False,
            "order_endpoint_allowed": False,
            "real_order_submitted": False,
        },
        "source_reports": {
            "scaffold": _relpath(_resolve(root, scaffold_report_path), root),
            "preflight": _relpath(_resolve(root, preflight_report_path), root),
            "provider_verification": _relpath(_resolve(root, provider_report_path), root),
            "acquisition_plan": _relpath(_resolve(root, acquisition_plan_path), root),
        },
        "outputs": {
            "json": _relpath(_resolve(root, output), root),
            "markdown": _relpath(_resolve(root, markdown_output), root),
        },
    }
    _write_json(_resolve(root, output), payload)
    _write_text(_resolve(root, markdown_output), _markdown(payload))
    return payload


def _required_tables() -> list[dict[str, Any]]:
    descriptions = {
        "universe_membership_events": "Point-in-time universe membership events; prevents future constituent and survivorship bias.",
        "delisted_symbols": "Delisting records and returns; prevents survivorship-clean universe from silently dropping failures.",
        "corporate_actions": "Split, dividend, symbol change, merger, spin-off, and delisting events for adjustment lineage.",
        "symbol_mapping": "Stable security_id to ticker and identifier mapping over time.",
        "adjustment_replay": "Raw-to-adjusted close replay evidence with replay_error for reproducibility checks.",
        "macro_release_calendar": "Macro release calendar with UTC available_time evidence for point-in-time macro features.",
    }
    rows = []
    for table, fields in REQUIRED_LOCAL_CSV_FILES.items():
        rows.append(
            {
                "table": table,
                "filename": DEFAULT_FILENAMES[table],
                "purpose": descriptions.get(table, ""),
                "required_fields": list(fields),
                "minimum_record_count": 1,
                "date_fields_must_be_iso_yyyy_mm_dd": True,
            }
        )
    return rows


def _operator_steps() -> list[dict[str, str]]:
    return [
        {
            "step_id": "prepare_incoming_drop",
            "command": f"Place the six licensed CSV files in {DEFAULT_INCOMING_DROP_DIR} using the exact filenames in this packet.",
            "expected_result": f"{DEFAULT_INCOMING_DROP_DIR} contains the licensed provider CSV drop and is not committed to git.",
        },
        {
            "step_id": "run_importer",
            "command": _preferred_import_command(),
            "expected_result": f"A private, gitignored bundle folder exists under data/external/us_equity_lineage/bundles/{DEFAULT_IMPORT_BUNDLE_ID}.",
        },
        {
            "step_id": "build_manifest",
            "command": "The importer builds provider_bundle_manifest.json automatically; rerun scripts/build_us_equity_local_csv_bundle_manifest.py manually only if metadata needs repair.",
            "expected_result": "provider_bundle_manifest.json contains sha256 and record_count for every required CSV.",
        },
        {
            "step_id": "select_bundle",
            "command": "Set providers.local_csv.enabled=true, selected_bundle_id=<bundle_id>, and promotion_clean_allowed=true only after license and evidence review.",
            "expected_result": "configs/data/us_equity_provider_sources.yaml explicitly selects one production bundle.",
        },
        {
            "step_id": "run_gates",
            "command": "Run the validation commands in order and keep paper/live locked until every report passes and manual review is complete.",
            "expected_result": "Preflight, provider verification, data status, strategy validation, and production line reports agree on the same selected bundle.",
        },
    ]


def _validation_commands() -> list[str]:
    return [
        _preferred_import_command(),
        "python scripts/build_us_equity_production_bundle_activation_report.py --bundle-id <bundle_id> --license-reviewed",
        "python scripts/build_us_equity_production_bundle_preflight_report.py --strict",
        "python scripts/build_us_equity_provider_capability_matrix.py",
        "python scripts/build_us_equity_provider_verification_report.py",
        "python scripts/build_us_equity_data_status_report.py",
        "python scripts/build_us_equity_data_lineage_remediation_report.py",
        "python scripts/build_us_etf_strategy_validation_gate_report.py",
        "python scripts/build_us_equity_strategy_production_line_report.py",
        "python scripts/build_us_equity_development_plan_audit.py",
    ]


def _preferred_import_command() -> str:
    return (
        "python scripts/import_us_equity_local_csv_production_bundle.py "
        f"--source-dir {DEFAULT_INCOMING_DROP_DIR} "
        f"--bundle-id {DEFAULT_IMPORT_BUNDLE_ID} "
        f"--sample-start {DEFAULT_IMPORT_SAMPLE_START} "
        f"--sample-end {DEFAULT_IMPORT_SAMPLE_END} "
        '--license-note "<license scope>" '
        "--promotion-clean-allowed"
    )


def _acceptance_criteria() -> list[dict[str, str]]:
    return [
        {"criterion": "production_bundle_preflight_pass", "required_value": "true"},
        {"criterion": "provider_verification.promotion_clean", "required_value": "true"},
        {"criterion": "data_status.promotion_clean", "required_value": "true"},
        {"criterion": "source_type", "required_value": "production"},
        {"criterion": "explicit_bundle_selection_confirmed", "required_value": "true"},
        {"criterion": "point_in_time_universe_confirmed", "required_value": "true"},
        {"criterion": "survivorship_clean", "required_value": "true"},
        {"criterion": "corporate_action_event_source_available", "required_value": "true"},
        {"criterion": "adjustment_reproducibility_confirmed", "required_value": "true"},
        {"criterion": "paper_or_live_unlock_allowed", "required_value": "false"},
        {"criterion": "live_order_allowed", "required_value": "false"},
    ]


def _markdown(payload: Mapping[str, Any]) -> str:
    contract = _mapping(payload.get("bundle_contract"))
    current = _mapping(payload.get("current_state"))
    lines = [
        "# US Equity 生产数据包导入验收包",
        "",
        f"生成时间：`{payload.get('generated_at', '')}`",
        "",
        f"- 状态：`{payload.get('status', '')}`",
        f"- incoming drop：`{contract.get('incoming_drop_dir', '')}`",
        f"- 默认导入 bundle：`{contract.get('default_import_bundle_id', '')}`",
        f"- 目标目录：`{contract.get('target_bundle_root', '')}`",
        f"- 当前选中 bundle：`{current.get('selected_bundle_id')}`",
        f"- production bundles found：`{current.get('production_bundles_found')}`",
        f"- preflight pass：`{current.get('preflight_pass')}`",
        "",
        "## Required Tables",
        "",
        "| table | filename | purpose | required fields |",
        "| --- | --- | --- | --- |",
    ]
    for row in _list(contract.get("required_tables")):
        if not isinstance(row, Mapping):
            continue
        fields = ", ".join(f"`{field}`" for field in _list_of_str(row.get("required_fields")))
        lines.append(f"| `{row.get('table')}` | `{row.get('filename')}` | {row.get('purpose')} | {fields} |")
    lines.extend(["", "## Operator Steps", ""])
    for step in _list(payload.get("operator_steps")):
        if not isinstance(step, Mapping):
            continue
        lines.append(f"- `{step.get('step_id')}`: {step.get('command')}")
    lines.extend(["", "## Validation Commands", ""])
    lines.extend(f"```powershell\n{cmd}\n```" for cmd in _list_of_str(payload.get("validation_commands")))
    lines.extend(["", "## Acceptance Criteria", ""])
    for item in _list(payload.get("acceptance_criteria")):
        if not isinstance(item, Mapping):
            continue
        lines.append(f"- `{item.get('criterion')}` must be `{item.get('required_value')}`")
    lines.extend(["", "## Current Blockers", ""])
    blockers = _list_of_str(current.get("current_blockers"))
    lines.extend([f"- `{item}`" for item in blockers] if blockers else ["- None"])
    lines.extend(
        [
            "",
            "## Guardrails",
            "",
            "- 本验收包不包含供应商数据，也不写入供应商数据。",
            "- 本验收包不修改 provider 配置。",
            "- 本验收包不能解锁 paper/live；通过后仍需要 strategy validation、forward observation 和人工审阅。",
            "",
        ]
    )
    return "\n".join(lines)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


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


def _git(args: list[str], *, cwd: Path) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=cwd, stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:
        return "unknown"


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _list_of_str(value: Any) -> list[str]:
    return [str(item) for item in value if str(item)] if isinstance(value, list) else []


def _dedupe(items: list[str]) -> list[str]:
    out = []
    seen = set()
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _utc_z_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build US equity production bundle intake packet.")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--scaffold-report-path", default=str(DEFAULT_SCAFFOLD_REPORT))
    parser.add_argument("--preflight-report-path", default=str(DEFAULT_PREFLIGHT_REPORT))
    parser.add_argument("--provider-report-path", default=str(DEFAULT_PROVIDER_REPORT))
    parser.add_argument("--acquisition-plan-path", default=str(DEFAULT_ACQUISITION_PLAN))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--markdown-output", default=str(DEFAULT_MARKDOWN_OUTPUT))
    parser.add_argument("--generated-at", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    payload = build_us_equity_production_bundle_intake_packet(
        repo_root=Path(args.repo_root),
        scaffold_report_path=Path(args.scaffold_report_path),
        preflight_report_path=Path(args.preflight_report_path),
        provider_report_path=Path(args.provider_report_path),
        acquisition_plan_path=Path(args.acquisition_plan_path),
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
