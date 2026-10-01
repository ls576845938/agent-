#!/usr/bin/env python3
"""Run the fail-closed US equity PIT vendor-drop pipeline."""

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
from scripts.build_us_equity_pit_operator_handoff_summary import (  # noqa: E402
    build_us_equity_pit_operator_handoff_summary,
)
from scripts.build_us_equity_vendor_drop_operator_progress_report import (  # noqa: E402
    build_us_equity_vendor_drop_operator_progress_report,
)
from scripts.build_us_equity_vendor_drop_preflight_report import (  # noqa: E402
    build_us_equity_vendor_drop_preflight_report,
)
from scripts.import_us_equity_local_csv_production_bundle import (  # noqa: E402
    DEFAULT_BUNDLE_ID,
    DEFAULT_LICENSE_NOTE,
    DEFAULT_SAMPLE_END,
    DEFAULT_SAMPLE_START,
    DEFAULT_SOURCE_DIR,
    import_us_equity_local_csv_production_bundle,
)
from scripts.run_us_equity_pit_bundle_acceptance import run_us_equity_pit_bundle_acceptance  # noqa: E402


SCHEMA_VERSION = "us_equity_vendor_drop_pipeline_run_v1"
DEFAULT_OUTPUT = Path("artifacts/us_equity_data_lineage/latest/us_equity_vendor_drop_pipeline_run_report.json")
DEFAULT_MARKDOWN_OUTPUT = Path("../学习资料/量化交易业务闭环/系统评估/US Equity PIT 数据交付Pipeline运行报告.md")
ALLOWED_STATUSES = {"vendor_drop_pipeline_blocked", "vendor_drop_pipeline_ready_for_manual_config_review"}

StepFn = Callable[..., Mapping[str, Any]]


def run_us_equity_vendor_drop_pipeline(
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
    preflight_fn: StepFn = build_us_equity_vendor_drop_preflight_report,
    incoming_readiness_fn: StepFn = build_us_equity_incoming_drop_readiness_report,
    import_fn: StepFn = import_us_equity_local_csv_production_bundle,
    acceptance_fn: StepFn = run_us_equity_pit_bundle_acceptance,
    progress_fn: StepFn = build_us_equity_vendor_drop_operator_progress_report,
    handoff_fn: StepFn = build_us_equity_pit_operator_handoff_summary,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at or _utc_z_now()
    source = _resolve(root, source_dir)
    steps: list[dict[str, Any]] = []

    steps.append(_run_step("manual_vendor_drop_package", manual_package_fn, repo_root=root, generated_at=generated))
    steps.append(_run_step("vendor_drop_preflight", preflight_fn, repo_root=root, source_dir=source, generated_at=generated))
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
    preflight_step = steps[1]
    readiness_step = steps[2]
    if _step_passed(preflight_step) and _step_passed(readiness_step):
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
        blocking_step = preflight_step if not _step_passed(preflight_step) else readiness_step
        steps.append(_skipped_step("local_csv_production_bundle_import", blocking_step))
    if _step_passed(steps[-1]):
        steps.append(
            _run_step(
                "pit_bundle_acceptance",
                acceptance_fn,
                repo_root=root,
                source_dir=source,
                bundle_id=bundle_id,
                license_note=license_note,
                sample_start=sample_start,
                sample_end=sample_end,
                as_of_date=as_of_date,
                universe_name=universe_name,
                price_data_reference=price_data_reference,
                license_reviewed=license_reviewed,
                generated_at=generated,
            )
        )
    else:
        steps.append(_skipped_step("pit_bundle_acceptance", steps[-1]))

    steps.append(_run_step("vendor_drop_operator_progress", progress_fn, repo_root=root, generated_at=generated))
    steps.append(_run_step("pit_operator_handoff", handoff_fn, repo_root=root, generated_at=generated))

    blockers = _pipeline_blockers(steps)
    unsafe = _unsafe_flags(steps)
    blockers.extend(f"unsafe_flag:{item}" for item in unsafe)
    status = "vendor_drop_pipeline_ready_for_manual_config_review" if not blockers else "vendor_drop_pipeline_blocked"
    current_blocking_step = _current_blocking_step(steps)
    if current_blocking_step == "none" and unsafe:
        current_blocking_step = "unsafe_guardrail"
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated,
        "asset": "us_equity",
        "status": status,
        "allowed_statuses": sorted(ALLOWED_STATUSES),
        "decision": (
            "review_activation_candidate_manually_keep_paper_live_locked"
            if status == "vendor_drop_pipeline_ready_for_manual_config_review"
            else "repair_vendor_drop_before_import_or_activation"
        ),
        "source_dir": _relpath(source, root),
        "bundle_id": bundle_id,
        "sample_start": sample_start,
        "sample_end": sample_end,
        "license_reviewed": bool(license_reviewed),
        "current_blocking_step": current_blocking_step,
        "steps": steps,
        "blockers": _dedupe(blockers),
        "unsafe_flags": unsafe,
        "guardrails": {
            "vendor_drop_pipeline_only": True,
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


def _run_step(step_id: str, fn: StepFn, **kwargs: Any) -> dict[str, Any]:
    try:
        payload = dict(fn(**kwargs))
    except Exception as exc:  # noqa: BLE001
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
        "passed": _step_passed_payload(step_id, payload),
        "blockers": _list_of_str(payload.get("blockers")),
        "payload": payload,
    }


def _skipped_step(step_id: str, previous_step: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "step_id": step_id,
        "status": "SKIPPED",
        "passed": False,
        "blockers": [f"{step_id}_skipped_until_{previous_step.get('step_id')}_passes"],
        "skipped_due_to_step_id": str(previous_step.get("step_id", "")),
        "skipped_due_to_status": str(previous_step.get("status", "")),
        "payload": {"status": "SKIPPED"},
    }


def _step_passed(step: Mapping[str, Any]) -> bool:
    return step.get("passed") is True


def _step_passed_payload(step_id: str, payload: Mapping[str, Any]) -> bool:
    expected = {
        "manual_vendor_drop_package": {"manual_vendor_drop_package_ready"},
        "vendor_drop_preflight": {"vendor_drop_preflight_ready_for_readiness_check"},
        "incoming_drop_readiness": {"incoming_drop_ready_for_import"},
        "local_csv_production_bundle_import": {"production_bundle_imported"},
        "pit_bundle_acceptance": {"acceptance_ready_for_manual_config_apply"},
        "vendor_drop_operator_progress": {
            "operator_drop_blocked",
            "operator_drop_ready_for_import",
            "operator_drop_complete_for_manual_review",
        },
        "pit_operator_handoff": {"handoff_blocked", "handoff_ready_for_operator_drop"},
    }
    return str(payload.get("status", "")) in expected.get(step_id, set())


def _pipeline_blockers(steps: list[Mapping[str, Any]]) -> list[str]:
    blockers: list[str] = []
    for step in steps:
        step_id = str(step.get("step_id", ""))
        if step_id in {"vendor_drop_operator_progress", "pit_operator_handoff"}:
            continue
        if step.get("passed") is not True:
            blockers.append(f"vendor_drop_pipeline_step_not_passed:{step_id}:{step.get('status')}")
            blockers.extend(_list_of_str(step.get("blockers")))
            break
    return _dedupe(blockers)


def _current_blocking_step(steps: list[Mapping[str, Any]]) -> str:
    for step in steps:
        step_id = str(step.get("step_id", ""))
        if step_id in {"vendor_drop_operator_progress", "pit_operator_handoff"}:
            continue
        if step.get("passed") is not True:
            return step_id
    return "none"


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
        step_id = str(step.get("step_id", "unknown_step"))
        for path, value in _walk(step.get("payload")):
            key = path.split(".")[-1]
            if key in unsafe_keys and value is True:
                unsafe.append(f"{step_id}.{path}=true")
    return _dedupe(unsafe)


def _walk(value: Any, prefix: str = "") -> list[tuple[str, Any]]:
    out: list[tuple[str, Any]] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            out.extend(_walk(child, path))
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            out.extend(_walk(child, f"{prefix}[{idx}]"))
    else:
        out.append((prefix, value))
    return out


def _markdown(payload: Mapping[str, Any]) -> str:
    lines = [
        "# US Equity PIT 数据交付Pipeline运行报告",
        "",
        f"- generated_at: `{payload.get('generated_at')}`",
        f"- status: `{payload.get('status')}`",
        f"- decision: `{payload.get('decision')}`",
        f"- current_blocking_step: `{payload.get('current_blocking_step')}`",
        "",
        "| step | status | passed | first blocker | skipped due to |",
        "| --- | --- | --- | --- | --- |",
    ]
    for step in _list(payload.get("steps")):
        if not isinstance(step, Mapping):
            continue
        blockers = _list_of_str(step.get("blockers"))
        lines.append(
            f"| `{step.get('step_id')}` | `{step.get('status')}` | `{step.get('passed')}` | `{blockers[0] if blockers else ''}` | `{step.get('skipped_due_to_step_id', '')}` |"
        )
    lines.extend(["", "## Blockers", ""])
    blockers = _list_of_str(payload.get("blockers"))
    lines.extend([f"- `{item}`" for item in blockers] if blockers else ["- None"])
    lines.extend(["", "## Guardrails", "", "- vendor_drop_pipeline_only=true", "- live_order_allowed=false", "- paper_or_live_unlock_allowed=false"])
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
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _list_of_str(value: Any) -> list[str]:
    return [str(item) for item in value if str(item)] if isinstance(value, list) else []


def _dedupe(items: list[str]) -> list[str]:
    return list(dict.fromkeys(item for item in items if item))


def _utc_z_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the US equity PIT vendor-drop pipeline.")
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    parser.add_argument("--bundle-id", default=DEFAULT_BUNDLE_ID)
    parser.add_argument("--license-note", default=DEFAULT_LICENSE_NOTE)
    parser.add_argument("--sample-start", default=DEFAULT_SAMPLE_START)
    parser.add_argument("--sample-end", default=DEFAULT_SAMPLE_END)
    parser.add_argument("--license-reviewed", action="store_true")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN_OUTPUT)
    parser.add_argument("--generated-at", default="")
    args = parser.parse_args()
    payload = run_us_equity_vendor_drop_pipeline(
        repo_root=args.repo_root,
        source_dir=args.source_dir,
        bundle_id=args.bundle_id,
        license_note=args.license_note,
        sample_start=args.sample_start,
        sample_end=args.sample_end,
        license_reviewed=args.license_reviewed,
        output=args.output,
        markdown_output=args.markdown_output,
        generated_at=args.generated_at or None,
    )
    print(payload["status"])


if __name__ == "__main__":
    main()
