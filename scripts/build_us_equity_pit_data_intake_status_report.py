#!/usr/bin/env python3
"""Build a one-page status report for US equity production PIT data intake."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


SCHEMA_VERSION = "us_equity_pit_data_intake_status_report_v1"
DEFAULT_OUTPUT = Path("artifacts/us_equity_data_lineage/latest/us_equity_pit_data_intake_status_report.json")
DEFAULT_MARKDOWN_OUTPUT = Path("../学习资料/量化交易业务闭环/系统评估/US Equity PIT 数据接入状态面板.md")

REPORTS = {
    "manual_vendor_drop_package": Path("artifacts/us_equity_data_lineage/latest/us_equity_manual_vendor_drop_package_report.json"),
    "incoming_drop_readiness": Path("artifacts/us_equity_data_lineage/latest/us_equity_incoming_drop_readiness_report.json"),
    "local_csv_import": Path("artifacts/us_equity_data_lineage/latest/us_equity_local_csv_production_bundle_import_report.json"),
    "intake_packet": Path("artifacts/us_equity_data_lineage/latest/us_equity_production_bundle_intake_packet.json"),
    "activation": Path("artifacts/us_equity_data_lineage/latest/us_equity_production_bundle_activation_report.json"),
    "pit_bundle_acceptance": Path("artifacts/us_equity_data_lineage/latest/us_equity_pit_bundle_acceptance_run_report.json"),
    "onboarding": Path("artifacts/us_equity_data_lineage/latest/us_equity_production_bundle_onboarding_report.json"),
    "development_plan_audit": Path("artifacts/us_equity_strategy_production_line/latest/us_equity_development_plan_audit_report.json"),
}

STAGE_ORDER = [
    "manual_vendor_drop_package",
    "incoming_drop_readiness",
    "local_csv_import",
    "intake_packet",
    "activation",
    "pit_bundle_acceptance",
    "onboarding",
    "development_plan_audit",
]


def build_us_equity_pit_data_intake_status_report(
    *,
    repo_root: Path | None = None,
    output: Path = DEFAULT_OUTPUT,
    markdown_output: Path = DEFAULT_MARKDOWN_OUTPUT,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at or _utc_z_now()
    paths = {name: _resolve(root, path) for name, path in REPORTS.items()}
    reports = {name: _read_json(path) for name, path in paths.items()}
    stages = [_stage(name, reports[name], paths[name], root) for name in STAGE_ORDER]
    blockers = _dedupe([blocker for stage in stages for blocker in _list_of_str(stage.get("blockers"))])
    unsafe = _unsafe_flags(reports)
    blockers.extend(f"unsafe_flag:{item}" for item in unsafe)
    next_action = _next_action(stages)
    status = "production_pit_data_intake_ready" if all(stage["status"] == "pass" for stage in stages) and not blockers else "production_pit_data_intake_blocked"

    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated,
        "commit": _git(["rev-parse", "--short", "HEAD"], cwd=root),
        "branch": _git(["branch", "--show-current"], cwd=root),
        "asset": "us_equity",
        "status": status,
        "decision": "continue_data_intake_do_not_unlock_paper_or_live",
        "current_blocking_stage": next_action.get("stage_id"),
        "next_action": next_action,
        "operator_next_actions": _operator_next_actions(next_action, reports),
        "stages": stages,
        "blockers": _dedupe(blockers),
        "unsafe_flags": unsafe,
        "source_reports": {name: _relpath(path, root) for name, path in paths.items()},
        "guardrails": {
            "status_panel_only": True,
            "source_vendor_data_modified": False,
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


def _stage(stage_id: str, report: Mapping[str, Any], path: Path, root: Path) -> dict[str, Any]:
    missing = not bool(report)
    raw_status = str(report.get("status", "")) if report else "missing"
    blockers = [] if not missing else [f"{stage_id}_report_missing"]
    stage_status = "pass"
    if missing:
        stage_status = "blocked"
    elif stage_id == "manual_vendor_drop_package":
        stage_status = "pass" if raw_status == "manual_vendor_drop_package_ready" else "blocked"
    elif stage_id == "incoming_drop_readiness":
        if raw_status == "incoming_drop_ready_for_import":
            stage_status = "pass"
        else:
            stage_status = "blocked"
            blockers.extend(_list_of_str(report.get("blockers")) or ["incoming_drop_not_ready"])
    elif stage_id == "local_csv_import":
        if raw_status == "production_bundle_imported":
            stage_status = "pass"
        else:
            stage_status = "blocked"
            blockers.extend(_list_of_str(report.get("blockers")) or ["production_bundle_not_imported"])
    elif stage_id == "intake_packet":
        stage_status = "pass" if raw_status == "intake_packet_ready_for_data_vendor_drop" else "blocked"
        blockers.extend([] if stage_status == "pass" else _list_of_str(report.get("blockers")))
    elif stage_id == "activation":
        if raw_status == "activation_ready_for_manual_config_apply":
            stage_status = "pass"
        else:
            stage_status = "blocked"
            blockers.extend(_list_of_str(report.get("blockers")) or ["activation_not_ready"])
    elif stage_id == "pit_bundle_acceptance":
        if raw_status == "acceptance_ready_for_manual_config_apply":
            stage_status = "pass"
        else:
            stage_status = "blocked"
            blockers.extend(_list_of_str(report.get("blockers")) or ["pit_bundle_acceptance_not_ready"])
    elif stage_id == "onboarding":
        if raw_status in {"production_bundle_onboarding_ready_for_data_drop", "production_bundle_onboarding_ready"}:
            stage_status = "pass"
        else:
            stage_status = "blocked"
            blockers.extend(_list_of_str(report.get("blockers")) or ["production_bundle_onboarding_not_ready"])
    elif stage_id == "development_plan_audit":
        if raw_status in {"development_plan_complete", "development_plan_blocked_by_production_pit_data"}:
            stage_status = "pass"
        else:
            stage_status = "blocked"
            blockers.extend(_list_of_str(report.get("blockers")) or ["development_plan_not_complete"])
    return {
        "stage_id": stage_id,
        "status": stage_status,
        "report_status": raw_status,
        "report_path": _relpath(path, root),
        "summary": _summary(stage_id, report),
        "blockers": _dedupe(blockers),
    }


def _summary(stage_id: str, report: Mapping[str, Any]) -> dict[str, Any]:
    if stage_id == "manual_vendor_drop_package":
        return {
            "template_files": len(_list(report.get("template_files"))),
            "field_count": report.get("field_count"),
            "incoming_drop_dir": report.get("incoming_drop_dir"),
        }
    if stage_id == "incoming_drop_readiness":
        return {
            "ready_file_count": report.get("ready_file_count"),
            "required_file_count": report.get("required_file_count"),
            "source_dir": report.get("source_dir"),
        }
    if stage_id == "local_csv_import":
        return {
            "bundle_id": report.get("bundle_id"),
            "source_dir": report.get("source_dir"),
            "target_bundle_root": report.get("target_bundle_root"),
        }
    if stage_id == "activation":
        return {
            "bundle_id": report.get("bundle_id"),
            "candidate_config_path": report.get("candidate_config_path"),
            "preflight_pass": _nested(report, "preflight_summary.production_bundle_preflight_pass"),
            "provider_promotion_clean": _nested(report, "provider_verification_summary.promotion_clean"),
        }
    if stage_id == "pit_bundle_acceptance":
        return {
            "bundle_id": report.get("bundle_id"),
            "source_dir": report.get("source_dir"),
            "current_blocking_step": report.get("current_blocking_step"),
            "license_reviewed": report.get("license_reviewed"),
        }
    if stage_id == "onboarding":
        return {
            "manual_vendor_drop_package_status": _nested(report, "manual_vendor_drop_package.status"),
            "selected_bundle_id": _nested(report, "selected_bundle.selected_bundle_id"),
            "provider_promotion_clean": _nested(report, "selected_bundle.provider_promotion_clean"),
        }
    if stage_id == "development_plan_audit":
        return {
            "complete_count": _nested(report, "summary.complete_count"),
            "blocked_count": _nested(report, "summary.blocked_count"),
            "phase_count": _nested(report, "summary.phase_count"),
        }
    return {}


def _next_action(stages: list[Mapping[str, Any]]) -> dict[str, str]:
    descriptions = {
        "manual_vendor_drop_package": "Run python scripts/build_us_equity_manual_vendor_drop_package.py.",
        "incoming_drop_readiness": "Place the six licensed CSV files under data/external/us_equity_lineage/incoming/manual_vendor_drop, then run readiness again.",
        "local_csv_import": "Run python scripts/import_us_equity_local_csv_production_bundle.py after readiness passes.",
        "intake_packet": "Regenerate the intake packet and compare the operator contract.",
        "activation": "Run activation preflight with the imported bundle id and manual license review flag.",
        "pit_bundle_acceptance": "Run python scripts/run_us_equity_pit_bundle_acceptance.py after the licensed CSV drop is complete.",
        "onboarding": "Clear provider verification, data status, and remediation blockers.",
        "development_plan_audit": "Continue the development plan after production PIT data is promotion clean.",
    }
    for stage in stages:
        if stage.get("status") != "pass":
            stage_id = str(stage.get("stage_id"))
            blockers = _list_of_str(stage.get("blockers"))
            return {
                "stage_id": stage_id,
                "description": descriptions.get(stage_id, "Review the blocked stage."),
                "first_blocker": blockers[0] if blockers else "",
            }
    return {"stage_id": "none", "description": "All PIT intake stages passed; continue downstream manual review.", "first_blocker": ""}


def _operator_next_actions(next_action: Mapping[str, Any], reports: Mapping[str, Mapping[str, Any]]) -> list[str]:
    stage_id = str(next_action.get("stage_id", ""))
    if stage_id == "incoming_drop_readiness":
        actions = _list_of_str(reports.get("incoming_drop_readiness", {}).get("operator_next_actions"))
        if actions:
            return actions
    if stage_id == "none":
        return ["Continue downstream manual review; this status panel does not unlock paper or live trading."]
    description = str(next_action.get("description", "")).strip()
    return [description] if description else ["Review the current blocking stage and repair its first blocker."]


def _unsafe_flags(reports: Mapping[str, Mapping[str, Any]]) -> list[str]:
    out = []
    unsafe_keys = {
        "live_order_allowed",
        "paper_or_live_unlock_allowed",
        "paper_simulation_allowed",
        "private_endpoint_allowed",
        "order_endpoint_allowed",
        "real_order_submitted",
        "broker_calls_used",
    }
    for report_id, report in reports.items():
        for path, value in _walk(report):
            if path.split(".")[-1] in unsafe_keys and value is True:
                out.append(f"{report_id}.{path}=true")
    return _dedupe(out)


def _markdown(payload: Mapping[str, Any]) -> str:
    next_action = _mapping(payload.get("next_action"))
    lines = [
        "# US Equity PIT 数据接入状态面板",
        "",
        f"生成时间：`{payload.get('generated_at')}`",
        "",
        f"- 状态：`{payload.get('status')}`",
        f"- 当前阻断阶段：`{payload.get('current_blocking_stage')}`",
        f"- 下一步：{next_action.get('description', '')}",
        f"- 首个 blocker：`{next_action.get('first_blocker', '')}`",
        "",
        "## Operator Next Actions",
        "",
    ]
    lines.extend(f"- `{item}`" for item in _list_of_str(payload.get("operator_next_actions")))
    lines.extend(
        [
            "",
            "## Pipeline",
            "",
            "| stage | status | report status | first blocker |",
            "| --- | --- | --- | --- |",
        ]
    )
    for stage in _list(payload.get("stages")):
        if not isinstance(stage, Mapping):
            continue
        blockers = _list_of_str(stage.get("blockers"))
        lines.append(
            f"| `{stage.get('stage_id')}` | `{stage.get('status')}` | `{stage.get('report_status')}` | `{blockers[0] if blockers else ''}` |"
        )
    lines.extend(["", "## Blockers", ""])
    blockers = _list_of_str(payload.get("blockers"))
    lines.extend([f"- `{item}`" for item in blockers] if blockers else ["- None"])
    lines.extend(["", "## Guardrails", ""])
    lines.extend(f"- `{key}` = `{value}`" for key, value in dict(payload.get("guardrails", {})).items())
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
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _nested(value: Any, dotted: str, default: Any = None) -> Any:
    current = value
    for key in dotted.split("."):
        if not isinstance(current, Mapping):
            return default
        current = current.get(key)
    return current if current is not None else default


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


def _walk(value: Any, prefix: str = "") -> list[tuple[str, Any]]:
    if isinstance(value, Mapping):
        out = []
        for key, child in value.items():
            out.extend(_walk(child, f"{prefix}.{key}" if prefix else str(key)))
        return out
    if isinstance(value, list):
        out = []
        for index, child in enumerate(value):
            out.extend(_walk(child, f"{prefix}.{index}"))
        return out
    return [(prefix, value)]


def _utc_z_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _git(args: list[str], *, cwd: Path) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=cwd, stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:
        return "unknown"


def main() -> None:
    parser = argparse.ArgumentParser(description="Build US equity PIT data intake status report.")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--markdown-output", default=str(DEFAULT_MARKDOWN_OUTPUT))
    parser.add_argument("--generated-at", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    payload = build_us_equity_pit_data_intake_status_report(
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
