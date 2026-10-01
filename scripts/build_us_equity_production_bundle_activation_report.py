#!/usr/bin/env python3
"""Build a dry-run activation report for a US equity production data bundle."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.build_us_equity_production_bundle_preflight_report import (  # noqa: E402
    build_production_bundle_preflight_report,
)
from scripts.build_us_equity_provider_verification_report import build_provider_verification_report  # noqa: E402


SCHEMA_VERSION = "us_equity_production_bundle_activation_report_v1"
DEFAULT_OUTPUT = Path("artifacts/us_equity_data_lineage/latest/us_equity_production_bundle_activation_report.json")
DEFAULT_MARKDOWN_OUTPUT = Path("../学习资料/量化交易业务闭环/系统评估/US Equity 生产数据包激活预检.md")
DEFAULT_PROVIDER_ROOT = Path("data/external/us_equity_lineage")
DEFAULT_CANDIDATE_CONFIG_DIR = Path("artifacts/us_equity_data_lineage/latest/activation_candidates")


def build_us_equity_production_bundle_activation_report(
    *,
    repo_root: Path | None = None,
    bundle_id: str = "",
    provider_root: Path = DEFAULT_PROVIDER_ROOT,
    candidate_config_dir: Path = DEFAULT_CANDIDATE_CONFIG_DIR,
    output: Path = DEFAULT_OUTPUT,
    markdown_output: Path = DEFAULT_MARKDOWN_OUTPUT,
    generated_at: str | None = None,
    license_reviewed: bool = False,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at or _utc_z_now()
    clean_bundle_id = _safe_bundle_id(bundle_id)
    provider_root_abs = _resolve(root, provider_root)
    bundle_root = provider_root_abs / "bundles" / clean_bundle_id if clean_bundle_id else provider_root_abs / "bundles" / "__missing__"
    manifest_path = bundle_root / "provider_bundle_manifest.json"
    manifest = _read_json(manifest_path)

    candidate_config_path = _resolve(root, candidate_config_dir) / f"us_equity_provider_sources.{clean_bundle_id or 'missing'}.candidate.yaml"
    candidate_config_text = _candidate_config(
        provider_root=_relpath(provider_root_abs, root),
        bundle_id=clean_bundle_id,
        promotion_clean_allowed=bool(license_reviewed),
    )
    _write_text(candidate_config_path, candidate_config_text)

    preflight = build_production_bundle_preflight_report(
        repo_root=root,
        generated_at=generated,
        config_path=candidate_config_path,
    )
    provider = build_provider_verification_report(
        repo_root=root,
        generated_at=generated,
        config_path=candidate_config_path,
    )
    checks = _checks(
        bundle_id=clean_bundle_id,
        bundle_root=bundle_root,
        manifest=manifest,
        preflight=preflight,
        provider=provider,
        license_reviewed=license_reviewed,
    )
    blockers = _dedupe(
        [blocker for check in checks.values() for blocker in _list_of_str(check.get("blockers"))]
        + _list_of_str(preflight.get("blockers"))
        + _list_of_str(provider.get("blockers"))
    )
    activation_ready = bool(
        clean_bundle_id
        and license_reviewed
        and preflight.get("production_bundle_preflight_pass") is True
        and provider.get("promotion_clean") is True
        and not blockers
    )
    status = "activation_ready_for_manual_config_apply" if activation_ready else "activation_blocked"

    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated,
        "commit": _git(["rev-parse", "--short", "HEAD"], cwd=root),
        "branch": _git(["branch", "--show-current"], cwd=root),
        "status": status,
        "asset": "us_equity",
        "bundle_id": clean_bundle_id or None,
        "bundle_root": _relpath(bundle_root, root),
        "bundle_manifest_path": _relpath(manifest_path, root),
        "candidate_config_path": _relpath(candidate_config_path, root),
        "candidate_config_patch": candidate_config_text,
        "checks": checks,
        "preflight_summary": {
            "production_bundle_preflight_pass": bool(preflight.get("production_bundle_preflight_pass", False)),
            "selected_bundle_id": preflight.get("selected_bundle_id"),
            "selected_bundle_source_type": preflight.get("selected_bundle_source_type"),
            "blockers": _list_of_str(preflight.get("blockers")),
        },
        "provider_verification_summary": {
            "selected_provider": provider.get("selected_provider"),
            "source_type": provider.get("source_type"),
            "promotion_clean": bool(provider.get("promotion_clean", False)),
            "data_lineage_grade_candidate": provider.get("data_lineage_grade_candidate"),
            "blockers": _list_of_str(provider.get("blockers")),
        },
        "manual_apply_commands": _manual_apply_commands(clean_bundle_id),
        "validation_commands_after_apply": _validation_commands(),
        "blockers": blockers,
        "guardrails": {
            "activation_report_only": True,
            "configuration_mutated_by_this_report": False,
            "promotion_clean_granted_by_this_report": False,
            "paper_or_live_unlock_allowed": False,
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


def _checks(
    *,
    bundle_id: str,
    bundle_root: Path,
    manifest: Mapping[str, Any],
    preflight: Mapping[str, Any],
    provider: Mapping[str, Any],
    license_reviewed: bool,
) -> dict[str, Any]:
    checks: dict[str, Any] = {}
    checks["bundle_id"] = {
        "passed": bool(bundle_id),
        "blockers": [] if bundle_id else ["candidate_bundle_id_missing"],
    }
    checks["bundle_exists"] = {
        "passed": bundle_root.exists(),
        "blockers": [] if bundle_root.exists() else ["candidate_bundle_root_missing"],
    }
    checks["manifest"] = {
        "passed": bool(manifest),
        "source_type": manifest.get("source_type"),
        "promotion_clean_allowed": manifest.get("promotion_clean_allowed"),
        "license_note_present": bool(str(manifest.get("license_note", "") or "").strip()),
        "blockers": [] if manifest else ["candidate_bundle_manifest_missing"],
    }
    checks["manual_license_review"] = {
        "passed": bool(license_reviewed),
        "blockers": [] if license_reviewed else ["manual_license_review_required_before_activation"],
    }
    checks["preflight"] = {
        "passed": bool(preflight.get("production_bundle_preflight_pass", False)),
        "blockers": _list_of_str(preflight.get("blockers")) or (
            [] if preflight.get("production_bundle_preflight_pass") else ["production_bundle_preflight_failed"]
        ),
    }
    checks["provider_verification"] = {
        "passed": bool(provider.get("promotion_clean", False)),
        "blockers": _list_of_str(provider.get("blockers")) or (
            [] if provider.get("promotion_clean") else ["provider_not_verified_for_promotion"]
        ),
    }
    return checks


def _candidate_config(*, provider_root: str, bundle_id: str, promotion_clean_allowed: bool) -> str:
    selected = bundle_id or "null"
    return "\n".join(
        [
            "providers:",
            "  local_csv:",
            "    enabled: true",
            f"    root: {provider_root}",
            f"    selected_bundle_id: {selected}",
            "    require_explicit_bundle_selection: true",
            "    allow_sample_for_research: false",
            "    allow_fixture_for_tests_only: false",
            "    bundle_manifest: null",
            f"    promotion_clean_allowed: {str(promotion_clean_allowed).lower()}",
            "    files: {}",
            "",
        ]
    )


def _manual_apply_commands(bundle_id: str) -> list[str]:
    if not bundle_id:
        return []
    return [
        f"Review artifacts/us_equity_data_lineage/latest/activation_candidates/us_equity_provider_sources.{bundle_id}.candidate.yaml",
        "Manually apply the local_csv block to configs/data/us_equity_provider_sources.yaml only after license and evidence review.",
        "Do not enable paper/live from this activation report.",
    ]


def _validation_commands() -> list[str]:
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
        "# US Equity 生产数据包激活预检",
        "",
        f"生成时间：`{payload.get('generated_at', '')}`",
        "",
        f"- 状态：`{payload.get('status', '')}`",
        f"- Bundle：`{payload.get('bundle_id')}`",
        f"- 候选配置：`{payload.get('candidate_config_path', '')}`",
        "",
        "## 检查",
        "",
        "| check | passed | blockers |",
        "| --- | --- | --- |",
    ]
    for name, check in _mapping(payload.get("checks")).items():
        lines.append(f"| `{name}` | `{check.get('passed')}` | `{', '.join(_list_of_str(check.get('blockers')))}` |")
    lines.extend(["", "## Guardrails", ""])
    guardrails = _mapping(payload.get("guardrails"))
    lines.extend(f"- `{key}` = `{value}`" for key, value in guardrails.items())
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--bundle-id", default="")
    parser.add_argument("--provider-root", default=str(DEFAULT_PROVIDER_ROOT))
    parser.add_argument("--candidate-config-dir", default=str(DEFAULT_CANDIDATE_CONFIG_DIR))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--markdown-output", default=str(DEFAULT_MARKDOWN_OUTPUT))
    parser.add_argument("--generated-at", default="")
    parser.add_argument("--license-reviewed", action="store_true")
    args = parser.parse_args()
    payload = build_us_equity_production_bundle_activation_report(
        repo_root=Path(args.repo_root),
        bundle_id=args.bundle_id,
        provider_root=Path(args.provider_root),
        candidate_config_dir=Path(args.candidate_config_dir),
        output=Path(args.output),
        markdown_output=Path(args.markdown_output),
        generated_at=args.generated_at or None,
        license_reviewed=bool(args.license_reviewed),
    )
    print(payload["status"])


def _safe_bundle_id(value: str) -> str:
    text = str(value or "").strip()
    return text if re.fullmatch(r"[A-Za-z0-9_.-]+", text) else ""


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _relpath(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


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


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _list_of_str(value: Any) -> list[str]:
    return [str(item) for item in value if str(item)] if isinstance(value, list) else []


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


def _utc_z_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _git(args: list[str], *, cwd: Path) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=cwd, stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:
        return "unknown"


if __name__ == "__main__":
    main()
