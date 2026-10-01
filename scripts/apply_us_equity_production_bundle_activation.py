#!/usr/bin/env python3
"""Apply a reviewed US equity production-bundle activation candidate.

This is the only scripted path that may mutate the US equity provider config,
and it is fail-closed: the activation report must already be ready and the
operator must pass --confirm-apply.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


SCHEMA_VERSION = "us_equity_production_bundle_activation_apply_report_v1"
DEFAULT_ACTIVATION_REPORT = Path("artifacts/us_equity_data_lineage/latest/us_equity_production_bundle_activation_report.json")
DEFAULT_TARGET_CONFIG = Path("configs/data/us_equity_provider_sources.yaml")
DEFAULT_OUTPUT = Path("artifacts/us_equity_data_lineage/latest/us_equity_production_bundle_activation_apply_report.json")
DEFAULT_MARKDOWN_OUTPUT = Path("../学习资料/量化交易业务闭环/系统评估/US Equity 生产数据包激活应用报告.md")


def apply_us_equity_production_bundle_activation(
    *,
    repo_root: Path | None = None,
    activation_report: Path = DEFAULT_ACTIVATION_REPORT,
    target_config: Path = DEFAULT_TARGET_CONFIG,
    output: Path = DEFAULT_OUTPUT,
    markdown_output: Path = DEFAULT_MARKDOWN_OUTPUT,
    generated_at: str | None = None,
    confirm_apply: bool = False,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at or _utc_z_now()
    activation_path = _resolve(root, activation_report)
    target_path = _resolve(root, target_config)
    activation = _read_json(activation_path)
    candidate_path = _candidate_config_path(root, activation)
    blockers = _blockers(
        root=root,
        activation=activation,
        activation_path=activation_path,
        candidate_path=candidate_path,
        confirm_apply=confirm_apply,
    )
    config_before = target_path.read_text(encoding="utf-8") if target_path.exists() else ""
    candidate_text = candidate_path.read_text(encoding="utf-8") if candidate_path and candidate_path.exists() else ""
    applied = False
    backup_path: Path | None = None
    if not blockers:
        backup_path = target_path.with_name(f"{target_path.name}.{generated.replace(':', '').replace('-', '').replace('Z', 'Z')}.bak")
        if target_path.exists():
            backup_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target_path, backup_path)
        _write_text(target_path, candidate_text)
        applied = True
    config_after = target_path.read_text(encoding="utf-8") if target_path.exists() else config_before
    status = "activation_applied" if applied else "activation_apply_blocked"
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated,
        "commit": _git(["rev-parse", "--short", "HEAD"], cwd=root),
        "branch": _git(["branch", "--show-current"], cwd=root),
        "asset": "us_equity",
        "status": status,
        "activation_report_path": _relpath(activation_path, root),
        "activation_status": activation.get("status"),
        "bundle_id": activation.get("bundle_id"),
        "candidate_config_path": _relpath(candidate_path, root) if candidate_path else None,
        "target_config_path": _relpath(target_path, root),
        "backup_config_path": _relpath(backup_path, root) if backup_path else None,
        "configuration_mutated": applied,
        "config_changed": config_before != config_after,
        "pre_apply_audit": _pre_apply_audit(
            root=root,
            activation=activation,
            activation_path=activation_path,
            candidate_path=candidate_path,
            target_path=target_path,
            config_before=config_before,
            candidate_text=candidate_text,
            confirm_apply=confirm_apply,
        ),
        "blockers": blockers,
        "post_apply_validation_commands": _post_apply_validation_commands(),
        "guardrails": {
            "activation_apply_only": True,
            "requires_ready_activation_report": True,
            "requires_confirm_apply": True,
            "configuration_mutated_by_this_report": applied,
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


def _pre_apply_audit(
    *,
    root: Path,
    activation: Mapping[str, Any],
    activation_path: Path,
    candidate_path: Path | None,
    target_path: Path,
    config_before: str,
    candidate_text: str,
    confirm_apply: bool,
) -> dict[str, Any]:
    guardrails = activation.get("guardrails", {})
    unsafe_guardrail_keys = []
    if isinstance(guardrails, Mapping):
        unsafe_guardrail_keys = [
            key
            for key in (
                "paper_or_live_unlock_allowed",
                "paper_simulation_allowed",
                "live_order_allowed",
                "private_endpoint_allowed",
                "order_endpoint_allowed",
                "real_order_submitted",
            )
            if guardrails.get(key) is True
        ]
    candidate_allowed_dir = root / "artifacts/us_equity_data_lineage/latest/activation_candidates"
    candidate_exists = bool(candidate_path and candidate_path.exists())
    candidate_inside_allowed_dir = bool(candidate_path and _is_inside(candidate_path, candidate_allowed_dir))
    return {
        "activation_report_exists": activation_path.exists(),
        "activation_report_ready": activation.get("status") == "activation_ready_for_manual_config_apply",
        "bundle_id": activation.get("bundle_id"),
        "manual_confirm_apply_present": bool(confirm_apply),
        "candidate_config_exists": candidate_exists,
        "candidate_config_inside_allowed_dir": candidate_inside_allowed_dir,
        "target_config_exists_before": target_path.exists(),
        "target_config_would_change": bool(candidate_text and candidate_text != config_before),
        "backup_required_before_overwrite": target_path.exists(),
        "backup_will_be_written_on_apply": bool(target_path.exists() and confirm_apply and activation.get("status") == "activation_ready_for_manual_config_apply" and candidate_exists and candidate_inside_allowed_dir),
        "unsafe_activation_guardrail_keys": unsafe_guardrail_keys,
        "paper_or_live_unlock_allowed": False,
        "live_order_allowed": False,
    }


def _blockers(
    *,
    root: Path,
    activation: Mapping[str, Any],
    activation_path: Path,
    candidate_path: Path | None,
    confirm_apply: bool,
) -> list[str]:
    blockers: list[str] = []
    if not activation_path.exists():
        blockers.append("activation_report_missing")
    if activation.get("status") != "activation_ready_for_manual_config_apply":
        blockers.append("activation_report_not_ready")
    if not activation.get("bundle_id"):
        blockers.append("bundle_id_missing")
    if not confirm_apply:
        blockers.append("manual_confirm_apply_missing")
    guardrails = activation.get("guardrails", {})
    if isinstance(guardrails, Mapping):
        unsafe = [
            key
            for key in (
                "paper_or_live_unlock_allowed",
                "paper_simulation_allowed",
                "live_order_allowed",
                "private_endpoint_allowed",
                "order_endpoint_allowed",
                "real_order_submitted",
            )
            if guardrails.get(key) is True
        ]
        blockers.extend(f"unsafe_activation_guardrail:{key}=true" for key in unsafe)
    if candidate_path is None:
        blockers.append("candidate_config_path_missing")
    elif not candidate_path.exists():
        blockers.append("candidate_config_missing")
    elif not _is_inside(candidate_path, root / "artifacts/us_equity_data_lineage/latest/activation_candidates"):
        blockers.append("candidate_config_outside_activation_candidates")
    return _dedupe(blockers)


def _candidate_config_path(root: Path, activation: Mapping[str, Any]) -> Path | None:
    raw = str(activation.get("candidate_config_path") or "")
    if not raw:
        return None
    path = Path(raw)
    return path if path.is_absolute() else root / path


def _post_apply_validation_commands() -> list[str]:
    return [
        "python scripts/build_us_equity_production_bundle_preflight_report.py --strict",
        "python scripts/build_us_equity_provider_verification_report.py",
        "python scripts/build_us_equity_data_status_report.py",
        "python scripts/build_us_equity_data_lineage_remediation_report.py",
        "python scripts/build_us_etf_strategy_validation_gate_report.py",
        "python scripts/run_us_equity_daily_production_line.py",
        "python scripts/build_us_equity_development_plan_audit.py",
    ]


def _markdown(payload: Mapping[str, Any]) -> str:
    lines = [
        "# US Equity 生产数据包激活应用报告",
        "",
        f"生成时间：`{payload.get('generated_at')}`",
        "",
        f"- 状态：`{payload.get('status')}`",
        f"- Bundle：`{payload.get('bundle_id')}`",
        f"- configuration mutated：`{payload.get('configuration_mutated')}`",
        f"- target config：`{payload.get('target_config_path')}`",
        f"- backup config：`{payload.get('backup_config_path')}`",
        "",
        "## Pre-Apply Audit",
        "",
    ]
    audit = dict(payload.get("pre_apply_audit", {}))
    lines.extend(f"- `{key}` = `{value}`" for key, value in audit.items())
    lines.extend(["", "## Blockers", ""])
    blockers = [str(item) for item in payload.get("blockers", [])]
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


def _relpath(path: Path | None, root: Path) -> str | None:
    if path is None:
        return None
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _is_inside(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _dedupe(values: list[str]) -> list[str]:
    result = []
    seen = set()
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _utc_z_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _git(args: list[str], *, cwd: Path) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=cwd, stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:
        return "unknown"


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply a reviewed US equity production bundle activation.")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--activation-report", default=str(DEFAULT_ACTIVATION_REPORT))
    parser.add_argument("--target-config", default=str(DEFAULT_TARGET_CONFIG))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--markdown-output", default=str(DEFAULT_MARKDOWN_OUTPUT))
    parser.add_argument("--generated-at", default="")
    parser.add_argument("--confirm-apply", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    payload = apply_us_equity_production_bundle_activation(
        repo_root=Path(args.repo_root),
        activation_report=Path(args.activation_report),
        target_config=Path(args.target_config),
        output=Path(args.output),
        markdown_output=Path(args.markdown_output),
        generated_at=args.generated_at or None,
        confirm_apply=bool(args.confirm_apply),
    )
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False))
    else:
        print(payload["status"])


if __name__ == "__main__":
    main()
