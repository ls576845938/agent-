#!/usr/bin/env python3
"""Build an onboarding audit for US equity production lineage bundles."""

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


SCHEMA_VERSION = "us_equity_production_bundle_onboarding_report_v1"
DEFAULT_SCAFFOLD_REPORT = Path("artifacts/us_equity_data_lineage/latest/us_equity_production_bundle_scaffold_report.json")
DEFAULT_PREFLIGHT_REPORT = Path("artifacts/us_equity_data_lineage/latest/production_bundle_preflight_report.json")
DEFAULT_PROVIDER_REPORT = Path("artifacts/us_equity_data_lineage/latest/provider_verification_report.json")
DEFAULT_DATA_STATUS_REPORT = Path("artifacts/us_equity_data_status/latest/data_status_report.json")
DEFAULT_REMEDIATION_REPORT = Path("artifacts/us_equity_data_lineage/latest/us_equity_data_lineage_remediation_report.json")
DEFAULT_ACQUISITION_PLAN = Path("artifacts/us_equity_data_lineage/latest/us_equity_production_data_acquisition_plan.json")
DEFAULT_MANUAL_VENDOR_DROP_PACKAGE = Path("artifacts/us_equity_data_lineage/latest/us_equity_manual_vendor_drop_package_report.json")
DEFAULT_OUTPUT = Path("artifacts/us_equity_data_lineage/latest/us_equity_production_bundle_onboarding_report.json")
DEFAULT_MARKDOWN_OUTPUT = Path("../学习资料/量化交易业务闭环/系统评估/US Equity 生产数据包接入审计.md")


def build_us_equity_production_bundle_onboarding_report(
    *,
    repo_root: Path | None = None,
    scaffold_report_path: Path = DEFAULT_SCAFFOLD_REPORT,
    preflight_report_path: Path = DEFAULT_PREFLIGHT_REPORT,
    provider_report_path: Path = DEFAULT_PROVIDER_REPORT,
    data_status_report_path: Path = DEFAULT_DATA_STATUS_REPORT,
    remediation_report_path: Path = DEFAULT_REMEDIATION_REPORT,
    acquisition_plan_path: Path = DEFAULT_ACQUISITION_PLAN,
    manual_vendor_drop_package_path: Path = DEFAULT_MANUAL_VENDOR_DROP_PACKAGE,
    output: Path = DEFAULT_OUTPUT,
    markdown_output: Path = DEFAULT_MARKDOWN_OUTPUT,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at or _utc_z_now()
    scaffold = _read_json(_resolve(root, scaffold_report_path))
    preflight = _read_json(_resolve(root, preflight_report_path))
    provider = _read_json(_resolve(root, provider_report_path))
    data_status = _read_json(_resolve(root, data_status_report_path))
    remediation = _read_json(_resolve(root, remediation_report_path))
    acquisition_plan = _read_json(_resolve(root, acquisition_plan_path))
    manual_vendor_drop_package = _read_json(_resolve(root, manual_vendor_drop_package_path))

    stages = [
        _stage_scaffold(scaffold),
        _stage_manual_vendor_drop_package(manual_vendor_drop_package),
        _stage_bundle_discovery(preflight),
        _stage_explicit_selection(preflight),
        _stage_provider_verification(provider),
        _stage_data_status(data_status),
        _stage_remediation(remediation),
    ]
    blockers: list[str] = []
    for stage in stages:
        blockers.extend(_list_of_str(stage.get("blockers")))
    status = "production_bundle_onboarding_ready_for_data_drop" if stages[0]["status"] == "pass" else "blocked"
    if any(stage["status"] == "blocked" for stage in stages[1:]):
        status = "production_bundle_onboarding_blocked"
    if not scaffold:
        status = "production_bundle_onboarding_missing_scaffold"

    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated,
        "status": status,
        "asset": "us_equity",
        "reports": {
            "scaffold": _relpath(_resolve(root, scaffold_report_path), root),
            "preflight": _relpath(_resolve(root, preflight_report_path), root),
            "provider_verification": _relpath(_resolve(root, provider_report_path), root),
            "data_status": _relpath(_resolve(root, data_status_report_path), root),
            "remediation": _relpath(_resolve(root, remediation_report_path), root),
            "acquisition_plan": _relpath(_resolve(root, acquisition_plan_path), root),
            "manual_vendor_drop_package": _relpath(_resolve(root, manual_vendor_drop_package_path), root),
        },
        "stages": stages,
        "selected_bundle": {
            "selected_bundle_id": preflight.get("selected_bundle_id") or provider.get("selected_bundle_id"),
            "selected_bundle_source_type": preflight.get("selected_bundle_source_type") or provider.get("selected_bundle_source_type"),
            "selected_bundle_manifest_path": preflight.get("selected_bundle_manifest_path") or provider.get("selected_bundle_manifest_path"),
            "production_bundle_preflight_pass": bool(preflight.get("production_bundle_preflight_pass", False)),
            "provider_promotion_clean": bool(provider.get("promotion_clean", False)),
            "data_promotion_clean": bool(data_status.get("promotion_clean", False)),
        },
        "activation_checklist": _activation_checklist(stages),
        "acquisition_plan": {
            "status": acquisition_plan.get("status"),
            "acceptable_provider_ids": acquisition_plan.get("acceptable_provider_ids", []),
            "missing_contract_groups": acquisition_plan.get("missing_contract_groups", []),
            "available": bool(acquisition_plan),
        },
        "manual_vendor_drop_package": {
            "status": manual_vendor_drop_package.get("status"),
            "incoming_drop_dir": manual_vendor_drop_package.get("incoming_drop_dir"),
            "template_root": manual_vendor_drop_package.get("template_root"),
            "field_dictionary": manual_vendor_drop_package.get("field_dictionary"),
            "handoff_doc": manual_vendor_drop_package.get("handoff_doc"),
            "template_file_count": len(_list(manual_vendor_drop_package.get("template_files"))),
            "field_count": manual_vendor_drop_package.get("field_count"),
            "available": bool(manual_vendor_drop_package),
        },
        "blockers": _dedupe(blockers),
        "guardrails": {
            "onboarding_report_is_not_provider_evidence": True,
            "configuration_mutated_by_this_report": False,
            "promotion_clean_granted_by_this_report": False,
            "paper_simulation_allowed": False,
            "live_order_allowed": False,
            "private_endpoint_allowed": False,
            "order_endpoint_allowed": False,
        },
        "outputs": {
            "json": _relpath(_resolve(root, output), root),
            "markdown": _relpath(_resolve(root, markdown_output), root),
        },
    }
    _write_json(_resolve(root, output), payload)
    _write_text(_resolve(root, markdown_output), _markdown(payload))
    return payload


def _stage_scaffold(scaffold: Mapping[str, Any]) -> dict[str, Any]:
    blockers = []
    if not scaffold:
        blockers.append("production_bundle_scaffold_report_missing")
    elif scaffold.get("status") != "template_ready_not_provider_evidence":
        blockers.append("production_bundle_scaffold_unexpected_status")
    return {
        "stage_id": "scaffold_ready",
        "status": "pass" if not blockers else "blocked",
        "evidence": {
            "scaffold_status": scaffold.get("status"),
            "scaffold_dir": scaffold.get("scaffold_dir"),
            "required_table_count": len(_list(scaffold.get("required_tables"))),
        },
        "blockers": blockers,
    }


def _stage_manual_vendor_drop_package(package: Mapping[str, Any]) -> dict[str, Any]:
    blockers = []
    if not package:
        blockers.append("manual_vendor_drop_package_report_missing")
    elif package.get("status") != "manual_vendor_drop_package_ready":
        blockers.append("manual_vendor_drop_package_not_ready")
    elif int(package.get("required_table_count", 0) or 0) < 6:
        blockers.append("manual_vendor_drop_package_required_tables_incomplete")
    elif int(package.get("field_count", 0) or 0) <= 0:
        blockers.append("manual_vendor_drop_package_field_dictionary_empty")
    return {
        "stage_id": "manual_vendor_drop_package",
        "status": "pass" if not blockers else "blocked",
        "evidence": {
            "package_status": package.get("status"),
            "incoming_drop_dir": package.get("incoming_drop_dir"),
            "template_root": package.get("template_root"),
            "field_dictionary": package.get("field_dictionary"),
            "handoff_doc": package.get("handoff_doc"),
            "required_table_count": package.get("required_table_count"),
            "field_count": package.get("field_count"),
        },
        "blockers": blockers,
    }


def _stage_bundle_discovery(preflight: Mapping[str, Any]) -> dict[str, Any]:
    blockers = []
    if not preflight:
        blockers.append("production_bundle_preflight_report_missing")
    elif int(preflight.get("production_bundles_found", 0) or 0) <= 0:
        blockers.append("production_bundle_missing")
    return {
        "stage_id": "production_bundle_discovery",
        "status": "pass" if not blockers else "blocked",
        "evidence": {
            "bundle_root": preflight.get("bundle_root"),
            "production_bundles_found": preflight.get("production_bundles_found"),
            "candidate_bundle_ids": preflight.get("candidate_bundle_ids", []),
            "local_csv_enabled": preflight.get("local_csv_enabled"),
        },
        "blockers": blockers,
    }


def _stage_explicit_selection(preflight: Mapping[str, Any]) -> dict[str, Any]:
    blockers = []
    if not preflight:
        blockers.append("production_bundle_preflight_report_missing")
    elif not preflight.get("selected_bundle_id"):
        blockers.append("explicit_bundle_selection_missing")
    elif not bool(preflight.get("production_bundle_preflight_pass", False)):
        blockers.extend(_list_of_str(preflight.get("blockers")) or ["production_bundle_preflight_failed"])
    return {
        "stage_id": "explicit_bundle_selection",
        "status": "pass" if not blockers else "blocked",
        "evidence": {
            "selected_bundle_id": preflight.get("selected_bundle_id"),
            "selected_bundle_manifest_path": preflight.get("selected_bundle_manifest_path"),
            "production_bundle_preflight_pass": preflight.get("production_bundle_preflight_pass"),
            "promotion_clean_allowed": preflight.get("promotion_clean_allowed"),
        },
        "blockers": _dedupe(blockers),
    }


def _stage_provider_verification(provider: Mapping[str, Any]) -> dict[str, Any]:
    blockers = []
    if not provider:
        blockers.append("provider_verification_report_missing")
    elif not bool(provider.get("promotion_clean", False)):
        blockers.extend(_list_of_str(provider.get("blockers")) or ["provider_not_verified_for_promotion"])
    return {
        "stage_id": "provider_verification",
        "status": "pass" if not blockers else "blocked",
        "evidence": {
            "selected_provider": provider.get("selected_provider"),
            "source_type": provider.get("source_type"),
            "promotion_clean": provider.get("promotion_clean"),
            "data_lineage_grade_candidate": provider.get("data_lineage_grade_candidate"),
        },
        "blockers": _dedupe(blockers),
    }


def _stage_data_status(data_status: Mapping[str, Any]) -> dict[str, Any]:
    blockers = []
    if not data_status:
        blockers.append("data_status_report_missing")
    elif not bool(data_status.get("promotion_clean", False)):
        blockers.extend(_list_of_str(data_status.get("blockers")) or ["data_lineage_not_promotion_clean"])
    return {
        "stage_id": "data_status_promotion_clean",
        "status": "pass" if not blockers else "blocked",
        "evidence": {
            "data_status": data_status.get("status"),
            "source_type": data_status.get("source_type"),
            "promotion_clean": data_status.get("promotion_clean"),
            "data_lineage_grade": data_status.get("data_lineage_grade"),
        },
        "blockers": _dedupe(blockers),
    }


def _stage_remediation(remediation: Mapping[str, Any]) -> dict[str, Any]:
    blockers = []
    groups = []
    if not remediation:
        blockers.append("data_lineage_remediation_report_missing")
    else:
        groups = [
            str(group.get("group_id"))
            for group in _list(remediation.get("remediation_groups"))
            if isinstance(group, Mapping) and group.get("group_id")
        ]
        if remediation.get("status") == "remediation_required":
            blockers.extend(f"remediation_required:{group_id}" for group_id in groups)
    return {
        "stage_id": "remaining_remediation",
        "status": "pass" if not blockers else "blocked",
        "evidence": {
            "remediation_status": remediation.get("status"),
            "remediation_groups": groups,
        },
        "blockers": _dedupe(blockers),
    }


def _activation_checklist(stages: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    descriptions = {
        "scaffold_ready": "Generate and review the local CSV production bundle scaffold.",
        "manual_vendor_drop_package": "Generate the exact six-CSV drop templates, field dictionary, and operator handoff.",
        "production_bundle_discovery": "Place a real licensed production bundle under data/external/us_equity_lineage/bundles/<bundle_id>.",
        "explicit_bundle_selection": "Enable local_csv and explicitly select the bundle id in configs/data/us_equity_provider_sources.yaml.",
        "provider_verification": "Run provider verification until PIT, delisting, corporate actions, identifier mapping, and adjustment replay pass.",
        "data_status_promotion_clean": "Rebuild data status and require promotion_clean=true.",
        "remaining_remediation": "Clear all data lineage remediation groups before strategy promotion.",
    }
    return [
        {
            "stage_id": str(stage.get("stage_id")),
            "done": stage.get("status") == "pass",
            "description": descriptions.get(str(stage.get("stage_id")), ""),
            "blockers": _list_of_str(stage.get("blockers")),
        }
        for stage in stages
    ]


def _markdown(payload: Mapping[str, Any]) -> str:
    lines = [
        "# US Equity 生产数据包接入审计",
        "",
        f"生成时间：`{payload.get('generated_at', '')}`",
        "",
        f"- 状态：`{payload.get('status', '')}`",
        f"- 选中 bundle：`{_nested(payload, 'selected_bundle.selected_bundle_id')}`",
        f"- provider promotion clean：`{_nested(payload, 'selected_bundle.provider_promotion_clean')}`",
        f"- data promotion clean：`{_nested(payload, 'selected_bundle.data_promotion_clean')}`",
        "",
        "## Stages",
        "",
        "| stage | status | first blocker |",
        "| --- | --- | --- |",
    ]
    for stage in _list(payload.get("stages")):
        if not isinstance(stage, Mapping):
            continue
        blockers = _list_of_str(stage.get("blockers"))
        lines.append(f"| `{stage.get('stage_id')}` | `{stage.get('status')}` | `{blockers[0] if blockers else ''}` |")
    lines.extend(["", "## Activation Checklist", ""])
    for row in _list(payload.get("activation_checklist")):
        if not isinstance(row, Mapping):
            continue
        marker = "DONE" if row.get("done") else "TODO"
        lines.append(f"- `{marker}` `{row.get('stage_id')}`: {row.get('description')}")
    lines.extend(["", "## Guardrails", ""])
    lines.extend(
        [
            "- 本报告不修改 provider 配置。",
            "- 本报告不是 provider evidence。",
            "- 本报告不能解锁 paper/live。",
        ]
    )
    return "\n".join(lines)


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


def _nested(payload: Mapping[str, Any], dotted: str, default: Any = None) -> Any:
    current: Any = payload
    for key in dotted.split("."):
        if not isinstance(current, Mapping):
            return default
        current = current.get(key)
    return current if current is not None else default


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _list_of_str(value: Any) -> list[str]:
    return [str(item) for item in value] if isinstance(value, list) else []


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
    parser = argparse.ArgumentParser(description="Build US equity production bundle onboarding report.")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--scaffold-report-path", default=str(DEFAULT_SCAFFOLD_REPORT))
    parser.add_argument("--preflight-report-path", default=str(DEFAULT_PREFLIGHT_REPORT))
    parser.add_argument("--provider-report-path", default=str(DEFAULT_PROVIDER_REPORT))
    parser.add_argument("--data-status-report-path", default=str(DEFAULT_DATA_STATUS_REPORT))
    parser.add_argument("--remediation-report-path", default=str(DEFAULT_REMEDIATION_REPORT))
    parser.add_argument("--acquisition-plan-path", default=str(DEFAULT_ACQUISITION_PLAN))
    parser.add_argument("--manual-vendor-drop-package-path", default=str(DEFAULT_MANUAL_VENDOR_DROP_PACKAGE))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--markdown-output", default=str(DEFAULT_MARKDOWN_OUTPUT))
    parser.add_argument("--generated-at", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    payload = build_us_equity_production_bundle_onboarding_report(
        repo_root=Path(args.repo_root),
        scaffold_report_path=Path(args.scaffold_report_path),
        preflight_report_path=Path(args.preflight_report_path),
        provider_report_path=Path(args.provider_report_path),
        data_status_report_path=Path(args.data_status_report_path),
        remediation_report_path=Path(args.remediation_report_path),
        acquisition_plan_path=Path(args.acquisition_plan_path),
        manual_vendor_drop_package_path=Path(args.manual_vendor_drop_package_path),
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
