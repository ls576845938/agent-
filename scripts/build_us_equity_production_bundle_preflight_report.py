#!/usr/bin/env python3
"""Build a fail-closed preflight report for US equity production PIT bundles."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from quant_us.data.lineage.local_csv_provider import (  # noqa: E402
    REQUIRED_LOCAL_CSV_FILES,
    file_sha256,
    load_provider_sources_config,
    local_csv_config,
)


DEFAULT_CONFIG = Path("configs/data/us_equity_provider_sources.yaml")
DEFAULT_OUTPUT = Path("artifacts/us_equity_data_lineage/latest/production_bundle_preflight_report.json")
DEFAULT_BUNDLE_ROOT = Path("data/external/us_equity_lineage/bundles")
MANIFEST_NAME = "provider_bundle_manifest.json"


def build_production_bundle_preflight_report(
    *,
    repo_root: Path | None = None,
    generated_at: str | None = None,
    config_path: Path = DEFAULT_CONFIG,
    bundle_root: Path | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at or datetime.now(timezone.utc).isoformat()
    config_ref = config_path if config_path.is_absolute() else root / config_path
    config = load_provider_sources_config(config_ref)
    local_csv = local_csv_config(config)
    configured_root = _provider_root(root, local_csv)
    scan_root = bundle_root if bundle_root is not None else configured_root / "bundles"
    scan_root = scan_root if scan_root.is_absolute() else root / scan_root

    local_csv_enabled = _is_true(local_csv.get("enabled", False))
    require_explicit = local_csv.get("require_explicit_bundle_selection", True) is True
    selected_bundle_id = _optional_string(local_csv.get("selected_bundle_id"))
    promotion_clean_allowed_by_config = local_csv.get("promotion_clean_allowed", False) is True

    manifests = _scan_manifests(scan_root)
    production = [item for item in manifests if item["source_type"] == "production"]
    sample = [item for item in manifests if item["source_type"] == "sample"]
    fixture = [item for item in manifests if item["source_type"] == "fixture"]
    candidate_bundle_ids = sorted(str(item["bundle_id"]) for item in production if item.get("bundle_id"))

    selected_manifest_path: Path | None = None
    selected_manifest: dict[str, Any] = {}
    selected_bundle_source_type: str | None = None
    if selected_bundle_id:
        selected_manifest_path = scan_root / selected_bundle_id / MANIFEST_NAME
        selected_manifest = _read_json(selected_manifest_path)
        selected_bundle_source_type = _optional_string(selected_manifest.get("source_type"))

    selected_bundle_manifest_path = _relpath(selected_manifest_path, root) if selected_manifest_path and selected_manifest_path.exists() else None
    promotion_clean_allowed_by_manifest = selected_manifest.get("promotion_clean_allowed", False) is True
    combined_promotion_clean_allowed = bool(promotion_clean_allowed_by_config and promotion_clean_allowed_by_manifest)
    selected_file_status = _selected_file_status(
        selected_manifest_path=selected_manifest_path,
        selected_manifest=selected_manifest,
        repo_root=root,
    )
    gitignore_confirmed = _gitignore_protection_confirmed(root, scan_root)
    vendor_risk = _vendor_data_committed_risk(root, scan_root)

    blockers: list[str] = []
    if not local_csv_enabled:
        blockers.append("local_csv_provider_disabled")
    if not manifests:
        blockers.append("production_bundle_root_empty")
    if not production:
        blockers.append("production_bundle_missing")
    if require_explicit and not selected_bundle_id:
        blockers.append("explicit_bundle_selection_missing")
    if selected_bundle_id and not selected_manifest:
        blockers.append("selected_bundle_manifest_missing")
    if selected_bundle_id and selected_manifest and selected_bundle_source_type != "production":
        blockers.append("selected_bundle_not_production")
    if not gitignore_confirmed:
        blockers.append("gitignore_protection_missing")
    if vendor_risk:
        blockers.append("vendor_data_committed_risk")
    if selected_manifest and not selected_file_status["required_files_present"]:
        blockers.append("production_bundle_required_files_missing")
    if selected_manifest and not selected_file_status["manifest_sha256_present"]:
        blockers.append("production_bundle_manifest_sha256_missing")
    if selected_manifest and not selected_file_status["manifest_record_counts_present"]:
        blockers.append("production_bundle_manifest_record_count_missing")
    if selected_manifest and not _optional_string(selected_manifest.get("license_note")):
        blockers.append("production_bundle_license_note_missing")
    if selected_manifest and not combined_promotion_clean_allowed:
        if not promotion_clean_allowed_by_config:
            blockers.append("config_promotion_clean_not_allowed")
        if not promotion_clean_allowed_by_manifest:
            blockers.append("bundle_promotion_clean_not_allowed")
        blockers.append("promotion_clean_not_allowed")
    blockers.extend(selected_file_status["blockers"])

    selected_preflight_pass = bool(
        local_csv_enabled
        and production
        and selected_bundle_id
        and selected_manifest
        and selected_bundle_source_type == "production"
        and gitignore_confirmed
        and not vendor_risk
        and selected_file_status["required_files_present"]
        and selected_file_status["manifest_sha256_present"]
        and selected_file_status["manifest_record_counts_present"]
        and _optional_string(selected_manifest.get("license_note"))
        and combined_promotion_clean_allowed
        and not _dedupe(blockers)
    )

    return {
        "schema_version": "us_equity_production_bundle_preflight_report_v1",
        "generated_at": generated,
        "commit": _git(["rev-parse", "--short", "HEAD"], cwd=root),
        "branch": _git(["branch", "--show-current"], cwd=root),
        "bundle_root": _relpath(scan_root, root),
        "provider_config_path": _relpath(config_ref, root),
        "local_csv_enabled": local_csv_enabled,
        "require_explicit_bundle_selection": require_explicit,
        "production_bundles_found": len(production),
        "sample_bundles_found": len(sample),
        "fixture_bundles_found": len(fixture),
        "candidate_bundle_ids": candidate_bundle_ids,
        "selected_bundle_id": selected_bundle_id,
        "selected_bundle_source_type": selected_bundle_source_type,
        "selected_bundle_manifest_path": selected_bundle_manifest_path,
        "selected_bundle_preflight_pass": selected_preflight_pass,
        "production_bundle_preflight_pass": selected_preflight_pass,
        "gitignore_protection_confirmed": gitignore_confirmed,
        "vendor_data_committed_risk": vendor_risk,
        "required_files_present": bool(selected_file_status["required_files_present"]),
        "manifest_sha256_present": bool(selected_file_status["manifest_sha256_present"]),
        "manifest_record_counts_present": bool(selected_file_status["manifest_record_counts_present"]),
        "license_note_present": bool(_optional_string(selected_manifest.get("license_note"))),
        "promotion_clean_allowed": combined_promotion_clean_allowed,
        "promotion_clean_allowed_by_config": promotion_clean_allowed_by_config,
        "promotion_clean_allowed_by_manifest": promotion_clean_allowed_by_manifest,
        "files": selected_file_status["files"],
        "blockers": _dedupe(blockers),
    }


def write_production_bundle_preflight_report(payload: Mapping[str, Any], output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(dict(payload), indent=2, sort_keys=True), encoding="utf-8")
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--config-path", default=str(DEFAULT_CONFIG))
    parser.add_argument("--bundle-root", default="")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--generated-at", default="")
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()
    payload = build_production_bundle_preflight_report(
        repo_root=Path(args.repo_root),
        config_path=Path(args.config_path),
        bundle_root=Path(args.bundle_root) if args.bundle_root else None,
        generated_at=args.generated_at or None,
    )
    print(write_production_bundle_preflight_report(payload, Path(args.output)))
    if args.strict and not bool(payload.get("production_bundle_preflight_pass", False)):
        raise SystemExit(1)


def _scan_manifests(bundle_root: Path) -> list[dict[str, Any]]:
    if not bundle_root.exists():
        return []
    result: list[dict[str, Any]] = []
    for path in sorted(bundle_root.glob(f"*/{MANIFEST_NAME}")):
        manifest = _read_json(path)
        if not manifest:
            continue
        result.append(
            {
                "path": path,
                "bundle_id": _optional_string(manifest.get("bundle_id")) or path.parent.name,
                "source_type": _optional_string(manifest.get("source_type")) or "unknown",
                "manifest": manifest,
            }
        )
    return result


def _selected_file_status(
    *,
    selected_manifest_path: Path | None,
    selected_manifest: Mapping[str, Any],
    repo_root: Path,
) -> dict[str, Any]:
    if selected_manifest_path is None or not selected_manifest:
        return {
            "required_files_present": False,
            "manifest_sha256_present": False,
            "manifest_record_counts_present": False,
            "files": {},
            "blockers": [],
        }
    files_payload = selected_manifest.get("files", {})
    files_payload = dict(files_payload) if isinstance(files_payload, Mapping) else {}
    bundle_dir = selected_manifest_path.parent
    files: dict[str, Any] = {}
    blockers: list[str] = []
    all_present = True
    all_sha = True
    all_counts = True
    for key in REQUIRED_LOCAL_CSV_FILES:
        spec = files_payload.get(key, {})
        spec = dict(spec) if isinstance(spec, Mapping) else {}
        rel_path = _optional_string(spec.get("path"))
        sha256 = _optional_string(spec.get("sha256"))
        record_count_present = "record_count" in spec
        path = _safe_join(bundle_dir, rel_path) if rel_path else None
        present = bool(path and path.exists())
        if not rel_path:
            blockers.append(f"production_bundle_{key}_path_missing")
        if rel_path and path is None:
            blockers.append(f"production_bundle_{key}_path_outside_bundle")
        if not present:
            blockers.append(f"production_bundle_{key}_file_missing")
        if not sha256:
            blockers.append(f"production_bundle_{key}_sha256_missing")
        if not record_count_present:
            blockers.append(f"production_bundle_{key}_record_count_missing")
        all_present = all_present and present
        all_sha = all_sha and bool(sha256)
        all_counts = all_counts and record_count_present
        files[key] = {
            "path": _relpath(path, repo_root) if path else None,
            "present": present,
            "sha256_present": bool(sha256),
            "record_count_present": record_count_present,
            "record_count": spec.get("record_count") if record_count_present else None,
            "actual_sha256": file_sha256(path) if present else None,
        }
    return {
        "required_files_present": all_present,
        "manifest_sha256_present": all_sha,
        "manifest_record_counts_present": all_counts,
        "files": files,
        "blockers": _dedupe(blockers),
    }


def _provider_root(repo_root: Path, provider: Mapping[str, Any]) -> Path:
    raw_root = Path(str(provider.get("root") or "data/external/us_equity_lineage"))
    return raw_root if raw_root.is_absolute() else repo_root / raw_root


def _safe_join(root: Path, rel_path: str | None) -> Path | None:
    if not rel_path:
        return None
    candidate = (root / rel_path).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        return None
    return candidate


def _gitignore_protection_confirmed(repo_root: Path, bundle_root: Path) -> bool:
    probe = bundle_root / "__probe__" / "vendor.csv"
    try:
        probe_ref = str(probe.resolve().relative_to(repo_root.resolve()))
        completed = subprocess.run(
            ["git", "check-ignore", "--quiet", probe_ref],
            cwd=repo_root,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if completed.returncode == 0:
            return True
    except Exception:
        pass
    gitignore = repo_root / ".gitignore"
    if not gitignore.exists():
        return False
    text = gitignore.read_text(encoding="utf-8")
    return "data/external/us_equity_lineage/bundles/*" in text or "bundles/*" in text


def _vendor_data_committed_risk(repo_root: Path, bundle_root: Path) -> bool:
    try:
        path_ref = str(bundle_root.resolve().relative_to(repo_root.resolve()))
        completed = subprocess.run(
            ["git", "ls-files", "--", path_ref],
            cwd=repo_root,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        return bool(completed.stdout.strip())
    except Exception:
        return False


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _is_true(value: object) -> bool:
    return value is True


def _optional_string(value: object) -> str | None:
    text = str(value or "")
    return text or None


def _relpath(path: Path | None, root: Path) -> str | None:
    if path is None:
        return None
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


def _git(args: list[str], *, cwd: Path) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=cwd, stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:
        return "unknown"


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


if __name__ == "__main__":
    main()
