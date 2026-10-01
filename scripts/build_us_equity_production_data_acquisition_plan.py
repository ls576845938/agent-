#!/usr/bin/env python3
"""Build the US equity production data acquisition plan.

This report turns the current PIT/data-lineage blockers into a concrete
provider-data acceptance contract. It does not fetch vendor data, mutate
provider config, or grant promotion-clean status.
"""

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
    DEFAULT_BUNDLE_ID as DEFAULT_IMPORT_BUNDLE_ID,
)
from scripts.import_us_equity_local_csv_production_bundle import (  # noqa: E402
    DEFAULT_SAMPLE_END as DEFAULT_IMPORT_SAMPLE_END,
)
from scripts.import_us_equity_local_csv_production_bundle import (  # noqa: E402
    DEFAULT_SAMPLE_START as DEFAULT_IMPORT_SAMPLE_START,
)
from scripts.import_us_equity_local_csv_production_bundle import DEFAULT_SOURCE_DIR  # noqa: E402


SCHEMA_VERSION = "us_equity_production_data_acquisition_plan_v1"
DEFAULT_PROVIDER_MATRIX = Path("artifacts/us_equity_data_lineage/latest/provider_capability_matrix.json")
DEFAULT_ONBOARDING = Path("artifacts/us_equity_data_lineage/latest/us_equity_production_bundle_onboarding_report.json")
DEFAULT_REMEDIATION = Path("artifacts/us_equity_data_lineage/latest/us_equity_data_lineage_remediation_report.json")
DEFAULT_INCOMING_READINESS = Path("artifacts/us_equity_data_lineage/latest/us_equity_incoming_drop_readiness_report.json")
DEFAULT_OUTPUT = Path("artifacts/us_equity_data_lineage/latest/us_equity_production_data_acquisition_plan.json")
DEFAULT_MARKDOWN_OUTPUT = Path("../学习资料/量化交易业务闭环/系统评估/US Equity 生产数据获取计划.md")


def build_us_equity_production_data_acquisition_plan(
    *,
    repo_root: Path | None = None,
    provider_matrix_path: Path = DEFAULT_PROVIDER_MATRIX,
    onboarding_path: Path = DEFAULT_ONBOARDING,
    remediation_path: Path = DEFAULT_REMEDIATION,
    incoming_readiness_path: Path = DEFAULT_INCOMING_READINESS,
    output: Path = DEFAULT_OUTPUT,
    markdown_output: Path = DEFAULT_MARKDOWN_OUTPUT,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at or _utc_z_now()
    provider_matrix = _read_json(_resolve(root, provider_matrix_path))
    onboarding = _read_json(_resolve(root, onboarding_path))
    remediation = _read_json(_resolve(root, remediation_path))
    incoming_readiness = _read_json(_resolve(root, incoming_readiness_path))
    blockers = _dedupe(
        _list_of_str(onboarding.get("blockers"))
        + _list_of_str(remediation.get("blockers"))
        + _list_of_str(provider_matrix.get("blockers"))
    )
    required_tables = _required_tables()
    provider_rows = _provider_rows(provider_matrix)
    acceptable_provider_ids = [
        row["provider_id"]
        for row in provider_rows
        if row["role"] in {"production_vendor", "local_csv_ingestion_contract"}
    ]
    missing_contract_groups = _missing_contract_groups(blockers)

    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated,
        "status": "production_data_acquisition_required" if blockers else "production_data_acquisition_ready_for_preflight",
        "asset": "us_equity",
        "reports": {
            "provider_matrix": _relpath(_resolve(root, provider_matrix_path), root),
            "onboarding": _relpath(_resolve(root, onboarding_path), root),
            "remediation": _relpath(_resolve(root, remediation_path), root),
            "incoming_drop_readiness": _relpath(_resolve(root, incoming_readiness_path), root),
        },
        "acceptable_provider_ids": acceptable_provider_ids,
        "non_substitutes": [
            {
                "provider_id": "tiingo",
                "reason": "Research EOD OHLCV is useful but does not provide PIT universe, delistings, corporate action event replay, or identifier mapping.",
            },
            {
                "provider_id": "ibkr",
                "reason": "Broker/recent market data cannot replace licensed historical PIT research data lineage.",
            },
            {
                "provider_id": "yfinance",
                "reason": "Free adjusted prices are not sufficient for promotion-clean survivorship and adjustment reproducibility.",
            },
        ],
        "required_tables": required_tables,
        "local_csv_drop_contract": {
            "incoming_drop_dir": DEFAULT_SOURCE_DIR.as_posix(),
            "default_bundle_id": DEFAULT_IMPORT_BUNDLE_ID,
            "required_filenames": [DEFAULT_FILENAMES[table] for table in REQUIRED_LOCAL_CSV_FILES],
            "preferred_import_command": _preferred_import_command(),
        },
        "current_drop_readiness": _current_drop_readiness(incoming_readiness),
        "contract_status_by_table": _contract_status_by_table(incoming_readiness),
        "missing_contract_groups": missing_contract_groups,
        "acceptance_commands": [
            _preferred_import_command(),
            f"python scripts/build_us_equity_production_bundle_activation_report.py --bundle-id {DEFAULT_IMPORT_BUNDLE_ID} --license-reviewed",
            "python scripts/build_us_equity_production_bundle_preflight_report.py",
            "python scripts/build_us_equity_provider_verification_report.py",
            "python scripts/build_us_equity_data_status_report.py",
            "python scripts/build_us_equity_data_lineage_remediation_report.py",
            "python scripts/build_us_etf_strategy_validation_gate_report.py",
            "python scripts/build_us_equity_strategy_production_line_report.py",
        ],
        "promotion_acceptance_criteria": {
            "production_bundle_preflight_pass": True,
            "provider_promotion_clean": True,
            "data_status_promotion_clean": True,
            "strategy_validation_gate_status": "validation_passed_for_forward_observation",
            "paper_or_live_unlock_allowed_by_this_plan": False,
        },
        "blockers": blockers,
        "guardrails": {
            "data_acquisition_plan_is_not_provider_evidence": True,
            "configuration_mutated_by_this_report": False,
            "promotion_clean_granted_by_this_report": False,
            "paper_simulation_allowed": False,
            "live_order_allowed": False,
            "private_endpoint_allowed": False,
            "order_endpoint_allowed": False,
            "real_order_submitted": False,
        },
        "outputs": {
            "json": _relpath(_resolve(root, output), root),
            "markdown": _relpath(_resolve(root, markdown_output), root),
        },
    }
    _write_json(_resolve(root, output), payload)
    _write_text(_resolve(root, markdown_output), _markdown(payload))
    return payload


def _preferred_import_command() -> str:
    return (
        "python scripts/import_us_equity_local_csv_production_bundle.py "
        f"--source-dir {DEFAULT_SOURCE_DIR.as_posix()} "
        f"--bundle-id {DEFAULT_IMPORT_BUNDLE_ID} "
        f"--sample-start {DEFAULT_IMPORT_SAMPLE_START} "
        f"--sample-end {DEFAULT_IMPORT_SAMPLE_END} "
        '--license-note "<license scope>" '
        "--promotion-clean-allowed"
    )


def _required_tables() -> list[dict[str, Any]]:
    return [
        {
            "table": table,
            "filename": DEFAULT_FILENAMES[table],
            "required_fields": list(fields),
            "purpose": _table_purpose(table),
        }
        for table, fields in REQUIRED_LOCAL_CSV_FILES.items()
    ]


def _table_purpose(table: str) -> str:
    return {
        "universe_membership_events": "Point-in-time universe membership, additions, removals, listing and delisting events.",
        "delisted_symbols": "Survivorship-bias control and delisting-return evidence.",
        "corporate_actions": "Split, dividend, merger, spin-off, symbol-change and delisting action events.",
        "symbol_mapping": "Stable identifier mapping across tickers, symbols, and provider identifiers.",
        "adjustment_replay": "Raw-to-adjusted price replay evidence for adjustment reproducibility.",
        "macro_release_calendar": "Macro release calendar with available_time_utc for point-in-time macro gating.",
    }[table]


def _provider_rows(provider_matrix: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for provider in _list(provider_matrix.get("providers")):
        if not isinstance(provider, Mapping):
            continue
        provider_id = str(provider.get("provider_id", ""))
        if provider_id in {"crsp", "sharadar", "norgate"}:
            role = "production_vendor"
        elif provider_id == "local_csv":
            role = "local_csv_ingestion_contract"
        else:
            role = "non_substitute"
        rows.append(
            {
                "provider_id": provider_id,
                "provider_name": provider.get("provider_name"),
                "role": role,
                "configured": bool(provider.get("configured", False)),
                "promotion_clean_capable": bool(provider.get("promotion_clean_capable", False)),
                "verified_for_promotion": bool(provider.get("verified_for_promotion", False)),
                "supports_point_in_time_universe": provider.get("supports_point_in_time_universe"),
                "supports_delisted_symbols": provider.get("supports_delisted_symbols"),
                "supports_adjustment_reproducibility": provider.get("supports_adjustment_reproducibility"),
            }
        )
    return rows


def _missing_contract_groups(blockers: list[str]) -> list[str]:
    groups = []
    mapping = {
        "pit_universe": {"point_in_time_universe_not_confirmed", "membership_events_missing", "historical_membership_missing"},
        "survivorship": {"delisting_coverage_missing", "survivorship_status_not_clean"},
        "corporate_actions": {"corporate_action_event_source_missing", "split_events_source_missing", "dividend_events_source_missing", "symbol_change_events_source_missing"},
        "identifier_mapping": {"identifier_mapping_missing", "provider_required_fields_missing"},
        "adjustment_replay": {"adjustment_reproducibility_missing", "price_adjustment_reproducibility_missing", "adjustment_mode_unknown"},
        "macro_release_calendar": {"fred_release_calendar_missing", "macro_release_lag_not_production_pit"},
        "bundle_activation": {"production_bundle_missing", "explicit_bundle_selection_missing", "local_csv_provider_disabled", "production_bundle_preflight_failed"},
    }
    blocker_set = set(blockers)
    for group, markers in mapping.items():
        if blocker_set & markers:
            groups.append(group)
    return groups


def _markdown(payload: Mapping[str, Any]) -> str:
    lines = [
        "# US Equity 生产数据获取计划",
        "",
        f"生成时间：`{payload.get('generated_at', '')}`",
        "",
        f"- 状态：`{payload.get('status', '')}`",
        f"- 可接受 provider：`{', '.join(_list_of_str(payload.get('acceptable_provider_ids')))}`",
        f"- 缺口组：`{', '.join(_list_of_str(payload.get('missing_contract_groups')))}`",
        f"- incoming drop：`{_mapping(payload.get('local_csv_drop_contract')).get('incoming_drop_dir', '')}`",
        f"- 默认导入 bundle：`{_mapping(payload.get('local_csv_drop_contract')).get('default_bundle_id', '')}`",
        f"- 当前 drop readiness：`{_mapping(payload.get('current_drop_readiness')).get('status')}`，ready=`{_mapping(payload.get('current_drop_readiness')).get('ready_file_count')}`/`{_mapping(payload.get('current_drop_readiness')).get('required_file_count')}`",
        "",
        "## 必需数据表",
        "",
        "| table | filename | purpose |",
        "| --- | --- | --- |",
    ]
    for row in _list(payload.get("required_tables")):
        if isinstance(row, Mapping):
            lines.append(f"| `{row.get('table')}` | `{row.get('filename')}` | {row.get('purpose')} |")
    lines.extend(["", "## 当前 Drop 合同状态", "", "| table | file | status | records | blockers |", "| --- | --- | --- | ---: | --- |"])
    for row in _list(payload.get("contract_status_by_table")):
        if isinstance(row, Mapping):
            lines.append(
                f"| `{row.get('table')}` | `{row.get('filename')}` | `{row.get('status')}` | `{row.get('record_count')}` | `{', '.join(_list_of_str(row.get('blockers')))}` |"
            )
    lines.extend(["", "## 验收命令", ""])
    lines.extend(f"- `{command}`" for command in _list_of_str(payload.get("acceptance_commands")))
    lines.extend(["", "## Guardrails", ""])
    lines.extend(
        [
            "- 该计划不是 provider evidence。",
            "- 该计划不修改配置。",
            "- 该计划不能解锁 paper/live。",
        ]
    )
    return "\n".join(lines)


def _current_drop_readiness(report: Mapping[str, Any]) -> dict[str, Any]:
    if not report:
        return {
            "status": "missing",
            "source_dir": DEFAULT_SOURCE_DIR.as_posix(),
            "bundle_id": DEFAULT_IMPORT_BUNDLE_ID,
            "ready_file_count": 0,
            "required_file_count": len(REQUIRED_LOCAL_CSV_FILES),
            "blocker_count": 1,
            "first_blocker": "incoming_drop_readiness_report_missing",
        }
    blockers = _list_of_str(report.get("blockers"))
    return {
        "status": str(report.get("status", "")),
        "source_dir": str(report.get("source_dir", DEFAULT_SOURCE_DIR.as_posix())),
        "bundle_id": str(report.get("bundle_id", DEFAULT_IMPORT_BUNDLE_ID)),
        "ready_file_count": int(report.get("ready_file_count", 0) or 0),
        "required_file_count": int(report.get("required_file_count", len(REQUIRED_LOCAL_CSV_FILES)) or len(REQUIRED_LOCAL_CSV_FILES)),
        "blocker_count": len(blockers),
        "first_blocker": blockers[0] if blockers else "",
    }


def _contract_status_by_table(report: Mapping[str, Any]) -> list[dict[str, Any]]:
    files = {
        str(item.get("table", "")): item
        for item in _list(report.get("files"))
        if isinstance(item, Mapping)
    }
    rows: list[dict[str, Any]] = []
    for table, required_fields in REQUIRED_LOCAL_CSV_FILES.items():
        file_report = _mapping(files.get(table))
        blockers = _list_of_str(file_report.get("blockers"))
        filename = str(file_report.get("filename") or DEFAULT_FILENAMES.get(table, f"{table}.csv"))
        exists = bool(file_report.get("exists", False))
        non_empty = bool(file_report.get("non_empty", False))
        missing_fields = _list_of_str(file_report.get("missing_fields", list(required_fields)))
        status = "ready" if exists and non_empty and not missing_fields and not blockers else "blocked"
        rows.append(
            {
                "table": table,
                "filename": filename,
                "status": status,
                "exists": exists,
                "non_empty": non_empty,
                "record_count": int(file_report.get("record_count", 0) or 0),
                "missing_fields": missing_fields,
                "blockers": blockers or ([f"source_{table}_file_missing"] if not exists else []),
            }
        )
    return rows


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


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


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _list_of_str(value: Any) -> list[str]:
    return [str(item) for item in value] if isinstance(value, list) else []


def _dedupe(items: list[str]) -> list[str]:
    out = []
    for item in items:
        if item and item not in out:
            out.append(item)
    return out


def _utc_z_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build US equity production data acquisition plan.")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--provider-matrix-path", default=str(DEFAULT_PROVIDER_MATRIX))
    parser.add_argument("--onboarding-path", default=str(DEFAULT_ONBOARDING))
    parser.add_argument("--remediation-path", default=str(DEFAULT_REMEDIATION))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--markdown-output", default=str(DEFAULT_MARKDOWN_OUTPUT))
    parser.add_argument("--generated-at", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    payload = build_us_equity_production_data_acquisition_plan(
        repo_root=Path(args.repo_root),
        provider_matrix_path=Path(args.provider_matrix_path),
        onboarding_path=Path(args.onboarding_path),
        remediation_path=Path(args.remediation_path),
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
