#!/usr/bin/env python3
"""Build the US equity production PIT procurement readiness report.

This is an evidence and operator-readiness report only. It does not copy
vendor files, import bundles, mutate configuration, or unlock paper/live.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from quant_us.data.lineage.local_csv_provider import REQUIRED_LOCAL_CSV_FILES
from scripts.build_us_equity_local_csv_bundle_manifest import DEFAULT_FILENAMES


SCHEMA_VERSION = "us_equity_pit_procurement_readiness_report_v1"
DEFAULT_DISCOVERY = Path("artifacts/us_equity_data_lineage/latest/us_equity_local_pit_file_discovery_report.json")
DEFAULT_OUTPUT = Path("artifacts/us_equity_data_lineage/latest/us_equity_pit_procurement_readiness_report.json")
DEFAULT_MARKDOWN_OUTPUT = Path("../学习资料/量化交易业务闭环/系统评估/US Equity PIT采购交付就绪审计.md")

ALLOWED_STATUSES = {
    "pit_procurement_blocked",
    "pit_procurement_ready_for_vendor_order",
    "pit_procurement_ready_for_manual_license_review",
}

ACCEPTABLE_SOURCE_ROUTES = [
    {
        "route_id": "crsp",
        "label": "CRSP / WRDS or CRSP direct export",
        "mapping_doc": "docs/us_equity_provider_mappings/crsp_to_local_csv.md",
    },
    {
        "route_id": "sharadar_nasdaq_data_link",
        "label": "Sharadar / Nasdaq Data Link export",
        "mapping_doc": "docs/us_equity_provider_mappings/sharadar_to_local_csv.md",
    },
    {
        "route_id": "polygon_massive",
        "label": "Polygon / Massive reference and corporate action export",
        "mapping_doc": "docs/us_equity_provider_mappings/polygon_massive_to_local_csv.md",
    },
    {
        "route_id": "norgate",
        "label": "Norgate export",
        "mapping_doc": "docs/us_equity_provider_mappings/norgate_to_local_csv.md",
    },
    {
        "route_id": "curated_local_csv",
        "label": "Manually curated licensed local CSV bundle",
        "mapping_doc": "docs/us_equity_provider_mappings/generic_local_csv_to_local_csv.md",
    },
]

SUPPLEMENTAL_SOURCE_ROUTES = [
    {
        "route_id": "tiingo_eod",
        "label": "Tiingo EOD price and adjusted bar data",
        "usable_for": [
            "research price refresh",
            "secondary price cross-check",
            "candidate vendor exploration",
        ],
        "not_sufficient_for": [
            "point-in-time universe membership",
            "full delisted-security coverage",
            "effective-dated identifier mapping",
            "macro release calendar",
            "standalone L4 promotion-clean approval",
        ],
    },
    {
        "route_id": "ibkr_market_data",
        "label": "Interactive Brokers market data",
        "usable_for": [
            "execution-adjacent quote sanity checks",
            "current tradability checks",
            "paper/live price monitoring after separate approval",
        ],
        "not_sufficient_for": [
            "historical point-in-time index membership",
            "survivorship-bias-free research universe",
            "local adjustment replay proof",
            "standalone L4 promotion-clean approval",
        ],
    },
    {
        "route_id": "fred",
        "label": "FRED macro time series and release metadata",
        "usable_for": [
            "macro signal inputs",
            "macro release calendar construction when release timestamps are retained",
            "macro data freshness monitoring",
        ],
        "not_sufficient_for": [
            "equity universe membership",
            "delisted equity coverage",
            "corporate actions",
            "identifier mapping",
            "standalone L4 promotion-clean approval",
        ],
    },
]

UNACCEPTABLE_SOURCES = [
    "fixtures",
    "templates",
    "tests",
    ".tmp",
    "derived_non_pit_research_outputs",
    "yfinance_only_exports",
    "latest_membership_only_exports",
]


def build_us_equity_pit_procurement_readiness_report(
    *,
    repo_root: Path | None = None,
    discovery_report: Path = DEFAULT_DISCOVERY,
    output: Path = DEFAULT_OUTPUT,
    markdown_output: Path = DEFAULT_MARKDOWN_OUTPUT,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at or _utc_z_now()
    discovery_path = _resolve(root, discovery_report)
    discovery = _read_json(discovery_path)
    required_files = _required_files(discovery)
    missing_files = [item["filename"] for item in required_files if item["readiness_status"] != "ready_for_manual_license_review"]
    ready_files = [item["filename"] for item in required_files if item["readiness_status"] == "ready_for_manual_license_review"]
    discovery_status = str(discovery.get("status", "missing_discovery_report"))
    discovery_ready_count = _int(discovery.get("ready_for_copy_count"), 0)
    required_count = len(required_files)

    if not discovery:
        status = "pit_procurement_blocked"
        decision = "run_local_pit_file_discovery_before_procurement_review"
    elif discovery_ready_count == required_count and required_count > 0:
        status = "pit_procurement_ready_for_manual_license_review"
        decision = "review_ready_candidates_before_copy_or_import"
    else:
        status = "pit_procurement_ready_for_vendor_order"
        decision = "order_or_export_missing_licensed_production_pit_files"

    blockers = _blockers(status, missing_files, discovery_status)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated,
        "commit": _git(["rev-parse", "--short", "HEAD"], cwd=root),
        "branch": _git(["branch", "--show-current"], cwd=root),
        "asset": "us_equity",
        "status": status,
        "allowed_statuses": sorted(ALLOWED_STATUSES),
        "decision": decision,
        "summary": {
            "required_file_count": required_count,
            "ready_for_manual_license_review_count": len(ready_files),
            "missing_file_count": len(missing_files),
            "acceptable_source_route_count": len(ACCEPTABLE_SOURCE_ROUTES),
            "supplemental_source_route_count": len(SUPPLEMENTAL_SOURCE_ROUTES),
            "unacceptable_source_count": len(UNACCEPTABLE_SOURCES),
            "paper_or_live_unlock_allowed": False,
            "live_order_allowed": False,
        },
        "required_files": required_files,
        "missing_filenames": missing_files,
        "ready_filenames": ready_files,
        "acceptable_source_routes": ACCEPTABLE_SOURCE_ROUTES,
        "supplemental_source_routes": SUPPLEMENTAL_SOURCE_ROUTES,
        "unacceptable_sources": UNACCEPTABLE_SOURCES,
        "minimum_delivery_requirements": [
            "All six required CSVs must be licensed production PIT inputs.",
            "Ticker must be treated as an alias; security_id must be the stable identity.",
            "Vendor exports must be normalized into the local CSV contract before validation.",
            "SHA256 and record counts must be recorded in provider_bundle_manifest.json.",
            "L4 promotion-clean can only come from provider verification and data status reports.",
        ],
        "source_reports": {
            "local_pit_file_discovery": _relpath(discovery_path, root),
            "operator_guide": "docs/us_equity_production_pit_data_acquisition_operator_guide.md",
            "source_decision": "docs/us_equity_point_in_time_data_source_decision.md",
            "acquisition_checklist": "docs/us_equity_production_pit_data_acquisition_checklist.md",
            "supplemental_source_boundaries": "docs/us_equity_supplemental_data_source_boundaries.md",
        },
        "blockers": blockers,
        "operator_next_actions": _operator_next_actions(status, missing_files),
        "guardrails": {
            "procurement_readiness_only": True,
            "files_copied": False,
            "vendor_data_imported": False,
            "configuration_mutated_by_this_report": False,
            "license_reviewed_by_this_report": False,
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
        raise AssertionError(f"invalid status: {payload['status']}")
    _write_json(_resolve(root, output), payload)
    _write_text(_resolve(root, markdown_output), _markdown(payload))
    return payload


def _required_files(discovery: Mapping[str, Any]) -> list[dict[str, Any]]:
    by_filename = {}
    for item in _list(discovery.get("files")):
        if isinstance(item, Mapping):
            by_filename[str(item.get("filename", ""))] = item

    rows: list[dict[str, Any]] = []
    for table, fields in REQUIRED_LOCAL_CSV_FILES.items():
        filename = DEFAULT_FILENAMES[table]
        discovered = by_filename.get(filename, {})
        ready = bool(discovered.get("ready_for_copy"))
        ready_candidates = _list(discovered.get("ready_candidates"))
        rows.append(
            {
                "table": table,
                "filename": filename,
                "required_fields": list(fields),
                "target_path": f"data/external/us_equity_lineage/incoming/manual_vendor_drop/{filename}",
                "readiness_status": "ready_for_manual_license_review" if ready else "missing_vendor_export",
                "ready_candidate_count": len(ready_candidates),
                "excluded_candidate_count": _int(discovered.get("excluded_candidate_count"), 0),
                "first_ready_candidate_path": _first_candidate_path(ready_candidates),
            }
        )
    return rows


def _first_candidate_path(candidates: list[Any]) -> str | None:
    for item in candidates:
        if isinstance(item, Mapping) and item.get("path"):
            return str(item["path"])
    return None


def _blockers(status: str, missing_files: list[str], discovery_status: str) -> list[str]:
    if status == "pit_procurement_ready_for_manual_license_review":
        return []
    if status == "pit_procurement_blocked":
        return ["local_pit_file_discovery_report_missing_or_unreadable"]
    return [f"pit_procurement_missing:{filename}" for filename in missing_files] or [f"pit_discovery_status:{discovery_status}"]


def _operator_next_actions(status: str, missing_files: list[str]) -> list[str]:
    if status == "pit_procurement_ready_for_manual_license_review":
        return [
            "Manually review license scope and provenance for each ready candidate.",
            "Copy only reviewed production CSV files into data/external/us_equity_lineage/incoming/manual_vendor_drop.",
            "Run python scripts/run_us_equity_vendor_drop_pipeline.py --license-reviewed.",
        ]
    if status == "pit_procurement_blocked":
        return ["Run python scripts/build_us_equity_local_pit_file_discovery_report.py before procurement readiness review."]
    return [
        "Choose CRSP, Sharadar/Nasdaq Data Link, Polygon/Massive, Norgate, or a licensed curated CSV route.",
        f"Acquire or export missing files: {', '.join(missing_files)}.",
        "Use Tiingo, IBKR, and FRED only as supplemental inputs unless they are normalized into the required PIT CSV contract and pass local verification.",
        "Do not use fixtures, templates, tests, yfinance-only, or latest-membership-only files.",
    ]


def _markdown(payload: Mapping[str, Any]) -> str:
    summary = _mapping(payload.get("summary"))
    lines = [
        "# US Equity PIT 采购交付就绪审计",
        "",
        f"- status: `{payload.get('status')}`",
        f"- decision: `{payload.get('decision')}`",
        f"- ready: `{summary.get('ready_for_manual_license_review_count')}` / `{summary.get('required_file_count')}`",
        f"- missing: `{', '.join(_list_of_str(payload.get('missing_filenames')))}`",
        "",
        "## 必需文件",
        "",
        "| file | status | target |",
        "| --- | --- | --- |",
    ]
    for item in _list(payload.get("required_files")):
        if isinstance(item, Mapping):
            lines.append(f"| `{item.get('filename')}` | `{item.get('readiness_status')}` | `{item.get('target_path')}` |")
    lines.extend(
        [
            "",
            "## 可接受来源",
            "",
            *[f"- `{item.get('route_id')}`: {item.get('label')}" for item in _list(payload.get("acceptable_source_routes")) if isinstance(item, Mapping)],
            "",
            "## 补充来源边界",
            "",
            *[
                f"- `{item.get('route_id')}`: {item.get('label')}；不能单独证明 `{', '.join(_list_of_str(item.get('not_sufficient_for'))[:2])}`"
                for item in _list(payload.get("supplemental_source_routes"))
                if isinstance(item, Mapping)
            ],
            "",
            "## 不可接受来源",
            "",
            *[f"- `{item}`" for item in _list_of_str(payload.get("unacceptable_sources"))],
            "",
            "## 下一步",
            "",
            *[f"- {item}" for item in _list_of_str(payload.get("operator_next_actions"))],
            "",
            "## Guardrails",
            "",
            "- files_copied=false",
            "- vendor_data_imported=false",
            "- paper_or_live_unlock_allowed=false",
            "- live_order_allowed=false",
        ]
    )
    return "\n".join(lines)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return {"status": "unreadable_report", "blockers": [type(exc).__name__]}


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


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


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _list_of_str(value: Any) -> list[str]:
    return [str(item) for item in _list(value)]


def _int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _git(args: list[str], *, cwd: Path) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=cwd, text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:  # noqa: BLE001
        return ""


def _utc_z_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--discovery-report", type=Path, default=DEFAULT_DISCOVERY)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN_OUTPUT)
    args = parser.parse_args()
    payload = build_us_equity_pit_procurement_readiness_report(
        repo_root=args.repo_root,
        discovery_report=args.discovery_report,
        output=args.output,
        markdown_output=args.markdown_output,
    )
    print(json.dumps({"status": payload["status"], "output": payload["outputs"]["json"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
