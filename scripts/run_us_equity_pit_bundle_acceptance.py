#!/usr/bin/env python3
"""Run a fail-closed acceptance chain for a manual US equity PIT CSV drop."""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.build_us_equity_incoming_drop_readiness_report import (  # noqa: E402
    build_us_equity_incoming_drop_readiness_report,
)
from scripts.build_us_equity_manual_vendor_drop_package import (  # noqa: E402
    build_us_equity_manual_vendor_drop_package,
)
from scripts.build_us_equity_production_bundle_activation_report import (  # noqa: E402
    build_us_equity_production_bundle_activation_report,
)
from scripts.import_us_equity_local_csv_production_bundle import (  # noqa: E402
    DEFAULT_BUNDLE_ID,
    DEFAULT_LICENSE_NOTE,
    DEFAULT_SAMPLE_END,
    DEFAULT_SAMPLE_START,
    DEFAULT_SOURCE_DIR,
    import_us_equity_local_csv_production_bundle,
)


SCHEMA_VERSION = "us_equity_pit_bundle_acceptance_run_v1"
DEFAULT_OUTPUT = Path("artifacts/us_equity_data_lineage/latest/us_equity_pit_bundle_acceptance_run_report.json")
DEFAULT_MARKDOWN_OUTPUT = Path("../学习资料/量化交易业务闭环/系统评估/US Equity PIT 数据包验收运行报告.md")
ALLOWED_STATUSES = {"acceptance_ready_for_manual_config_apply", "acceptance_blocked"}

StepFn = Callable[..., Mapping[str, Any]]


def run_us_equity_pit_bundle_acceptance(
    *,
    repo_root: Path | None = None,
    source_dir: Path = DEFAULT_SOURCE_DIR,
    bundle_id: str = DEFAULT_BUNDLE_ID,
    license_note: str = DEFAULT_LICENSE_NOTE,
    sample_start: str = DEFAULT_SAMPLE_START,
    sample_end: str = DEFAULT_SAMPLE_END,
    as_of_date: str = "",
    universe_name: str = "",
    price_data_reference: str = "",
    license_reviewed: bool = False,
    output: Path = DEFAULT_OUTPUT,
    markdown_output: Path = DEFAULT_MARKDOWN_OUTPUT,
    generated_at: str | None = None,
    manual_package_fn: StepFn = build_us_equity_manual_vendor_drop_package,
    incoming_readiness_fn: StepFn = build_us_equity_incoming_drop_readiness_report,
    import_fn: StepFn = import_us_equity_local_csv_production_bundle,
    activation_fn: StepFn = build_us_equity_production_bundle_activation_report,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at or _utc_z_now()
    source = _resolve(root, source_dir)
    steps: list[dict[str, Any]] = []

    steps.append(_run_step("manual_vendor_drop_package", manual_package_fn, repo_root=root, generated_at=generated))
    steps.append(
        _run_step(
            "incoming_drop_readiness",
            incoming_readiness_fn,
            repo_root=root,
            source_dir=source,
            bundle_id=bundle_id,
            generated_at=generated,
        )
    )
    if _last_step_passed(steps):
        steps.append(
            _run_step(
                "local_csv_production_bundle_import",
                import_fn,
                repo_root=root,
                source_dir=source,
                bundle_id=bundle_id,
                license_note=license_note,
                sample_start=sample_start,
                sample_end=sample_end,
                as_of_date=as_of_date,
                universe_name=universe_name,
                price_data_reference=price_data_reference,
                promotion_clean_allowed=True,
                generated_at=generated,
            )
        )
    else:
        steps.append(_skipped_step("local_csv_production_bundle_import", steps[-1]))
    if _last_step_passed(steps):
        steps.append(
            _run_step(
                "production_bundle_activation",
                activation_fn,
                repo_root=root,
                bundle_id=bundle_id,
                license_reviewed=license_reviewed,
                generated_at=generated,
            )
        )
    else:
        steps.append(_skipped_step("production_bundle_activation", steps[-1]))

    blockers = _acceptance_blockers(steps)
    unsafe = _unsafe_flags(steps)
    blockers.extend(f"unsafe_flag:{item}" for item in unsafe)
    status = "acceptance_ready_for_manual_config_apply" if not blockers else "acceptance_blocked"
    current_blocking_step = _current_blocking_step(steps)
    activation = _payload_for_step(steps, "production_bundle_activation")
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated,
        "asset": "us_equity",
        "status": status,
        "allowed_statuses": sorted(ALLOWED_STATUSES),
        "decision": (
            "review_activation_candidate_then_apply_manually"
            if status == "acceptance_ready_for_manual_config_apply"
            else "repair_pit_bundle_drop_before_activation"
        ),
        "source_dir": _relpath(source, root),
        "bundle_id": bundle_id,
        "sample_start": sample_start,
        "sample_end": sample_end,
        "as_of_date": as_of_date,
        "universe_name": universe_name,
        "price_data_reference": price_data_reference,
        "license_reviewed": bool(license_reviewed),
        "current_blocking_step": current_blocking_step,
        "activation_candidate_config_path": activation.get("candidate_config_path"),
        "steps": steps,
        "blockers": _dedupe(blockers),
        "unsafe_flags": unsafe,
        "post_acceptance_manual_commands": _post_acceptance_manual_commands(bundle_id),
        "guardrails": {
            "acceptance_orchestration_only": True,
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
    if payload["status"] not in ALLOWED_STATUSES:
        raise AssertionError(f"invalid acceptance status: {payload['status']}")
    _write_json(_resolve(root, output), payload)
    _write_text(_resolve(root, markdown_output), _markdown(payload))
    return payload


def _run_step(step_id: str, fn: StepFn, **kwargs: Any) -> dict[str, Any]:
    try:
        payload = dict(fn(**kwargs))
    except Exception as exc:  # noqa: BLE001 - fail closed with audit trail.
        return {
            "step_id": step_id,
            "status": "EXCEPTION",
            "passed": False,
            "blockers": [f"{step_id}_exception:{type(exc).__name__}"],
            "payload": {"error": str(exc)},
        }
    return {
        "step_id": step_id,
        "status": str(payload.get("status", "")),
        "passed": _step_passed(step_id, payload),
        "blockers": _list_of_str(payload.get("blockers")),
        "payload": payload,
    }


def _last_step_passed(steps: list[Mapping[str, Any]]) -> bool:
    return bool(steps) and steps[-1].get("passed") is True


def _skipped_step(step_id: str, previous_step: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "step_id": step_id,
        "status": "SKIPPED",
        "passed": False,
        "blockers": [f"{step_id}_skipped_until_{previous_step.get('step_id')}_passes"],
        "skipped_due_to_step_id": str(previous_step.get("step_id", "")),
        "skipped_due_to_status": str(previous_step.get("status", "")),
        "payload": {
            "status": "SKIPPED",
            "guardrails": {
                "skipped_fail_closed": True,
                "source_vendor_data_modified": False,
                "configuration_mutated_by_this_report": False,
                "paper_or_live_unlock_allowed": False,
                "live_order_allowed": False,
                "order_endpoint_allowed": False,
                "real_order_submitted": False,
            },
        },
    }


def _step_passed(step_id: str, payload: Mapping[str, Any]) -> bool:
    expected = {
        "manual_vendor_drop_package": {"manual_vendor_drop_package_ready"},
        "incoming_drop_readiness": {"incoming_drop_ready_for_import"},
        "local_csv_production_bundle_import": {"production_bundle_imported"},
        "production_bundle_activation": {"activation_ready_for_manual_config_apply"},
    }
    return str(payload.get("status", "")) in expected.get(step_id, set())


def _acceptance_blockers(steps: list[Mapping[str, Any]]) -> list[str]:
    blockers: list[str] = []
    for step in steps:
        if step.get("passed") is not True:
            blockers.append(f"us_equity_pit_acceptance_step_not_passed:{step.get('step_id')}:{step.get('status')}")
            blockers.extend(_list_of_str(step.get("blockers")))
            break
    return _dedupe(blockers)


def _current_blocking_step(steps: list[Mapping[str, Any]]) -> str:
    for step in steps:
        if step.get("passed") is not True:
            return str(step.get("step_id", "unknown"))
    return "none"


def _payload_for_step(steps: list[Mapping[str, Any]], step_id: str) -> Mapping[str, Any]:
    for step in steps:
        if step.get("step_id") == step_id:
            return _mapping(step.get("payload"))
    return {}


def _unsafe_flags(steps: list[Mapping[str, Any]]) -> list[str]:
    unsafe = []
    unsafe_keys = {
        "paper_or_live_unlock_allowed",
        "paper_simulation_allowed",
        "live_order_allowed",
        "private_endpoint_allowed",
        "order_endpoint_allowed",
        "real_order_submitted",
        "broker_calls_used",
    }
    for step in steps:
        for path, value in _walk(step.get("payload")):
            if path.split(".")[-1] in unsafe_keys and value is True:
                unsafe.append(f"{step.get('step_id')}.{path}=true")
    return _dedupe(unsafe)


def _post_acceptance_manual_commands(bundle_id: str) -> list[str]:
    return [
        f"Review artifacts/us_equity_data_lineage/latest/activation_candidates/us_equity_provider_sources.{bundle_id}.candidate.yaml",
        "python scripts/apply_us_equity_production_bundle_activation.py --confirm-apply",
        "python scripts/build_us_equity_production_bundle_preflight_report.py --strict",
        "python scripts/build_us_equity_provider_verification_report.py",
        "python scripts/build_us_equity_data_status_report.py",
        "python scripts/build_us_equity_data_lineage_remediation_report.py",
        "python scripts/run_us_equity_daily_production_line.py",
    ]


def _markdown(payload: Mapping[str, Any]) -> str:
    lines = [
        "# US Equity PIT 数据包验收运行报告",
        "",
        f"生成时间：`{payload.get('generated_at', '')}`",
        "",
        f"- 状态：`{payload.get('status', '')}`",
        f"- source：`{payload.get('source_dir', '')}`",
        f"- bundle：`{payload.get('bundle_id', '')}`",
        f"- 当前阻断步骤：`{payload.get('current_blocking_step', '')}`",
        f"- activation candidate：`{payload.get('activation_candidate_config_path')}`",
        "",
        "## Steps",
        "",
        "| step | status | passed | first blocker |",
        "| --- | --- | --- | --- |",
    ]
    for step in _list(payload.get("steps")):
        if not isinstance(step, Mapping):
            continue
        blockers = _list_of_str(step.get("blockers"))
        lines.append(f"| `{step.get('step_id')}` | `{step.get('status')}` | `{step.get('passed')}` | `{blockers[0] if blockers else ''}` |")
    lines.extend(["", "## Blockers", ""])
    blockers = _list_of_str(payload.get("blockers"))
    lines.extend([f"- `{item}`" for item in blockers] if blockers else ["- None"])
    lines.extend(["", "## Guardrails", ""])
    lines.extend(f"- `{key}` = `{value}`" for key, value in _mapping(payload.get("guardrails")).items())
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
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


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


def main() -> None:
    parser = argparse.ArgumentParser(description="Run US equity PIT bundle acceptance.")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--source-dir", default=str(DEFAULT_SOURCE_DIR))
    parser.add_argument("--bundle-id", default=DEFAULT_BUNDLE_ID)
    parser.add_argument("--license-note", default=DEFAULT_LICENSE_NOTE)
    parser.add_argument("--sample-start", default=DEFAULT_SAMPLE_START)
    parser.add_argument("--sample-end", default=DEFAULT_SAMPLE_END)
    parser.add_argument("--as-of-date", default="")
    parser.add_argument("--universe-name", default="")
    parser.add_argument("--price-data-reference", default="")
    parser.add_argument("--license-reviewed", action="store_true")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--markdown-output", default=str(DEFAULT_MARKDOWN_OUTPUT))
    parser.add_argument("--generated-at", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    payload = run_us_equity_pit_bundle_acceptance(
        repo_root=Path(args.repo_root),
        source_dir=Path(args.source_dir),
        bundle_id=args.bundle_id,
        license_note=args.license_note,
        sample_start=args.sample_start,
        sample_end=args.sample_end,
        as_of_date=args.as_of_date,
        universe_name=args.universe_name,
        price_data_reference=args.price_data_reference,
        license_reviewed=bool(args.license_reviewed),
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
