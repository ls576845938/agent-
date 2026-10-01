#!/usr/bin/env python3
"""Build a fail-closed preflight report for the selected BTC USD-M bundle."""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import yaml

try:
    from quant_crypto.data.btc_perpetual_provider_config import (
        default_provider_root,
        selected_btc_perpetual_provider,
    )
    from scripts.build_btc_perpetual_data_bundle_manifest import (
        REQUIRED_FILES,
        TIME_SERIES_ROLES,
        validate_btc_perpetual_data_bundle_manifest,
    )
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from quant_crypto.data.btc_perpetual_provider_config import (
        default_provider_root,
        selected_btc_perpetual_provider,
    )
    from build_btc_perpetual_data_bundle_manifest import (
        REQUIRED_FILES,
        TIME_SERIES_ROLES,
        validate_btc_perpetual_data_bundle_manifest,
    )


DEFAULT_CONFIG = Path("configs/data/btc_perpetual_sources.yaml")
DEFAULT_OUTPUT_ROOT = Path("artifacts/btc_data_status/latest")


def build_btc_perpetual_bundle_preflight_report(
    *,
    repo_root: Path | None = None,
    config_path: Path | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    config_rel = config_path or DEFAULT_CONFIG
    config_abs = config_rel if config_rel.is_absolute() else root / config_rel
    selected_provider, provider = selected_btc_perpetual_provider(config_abs)
    generated = generated_at or datetime.now(timezone.utc).isoformat()
    bundle_root = root / str(provider.get("root", default_provider_root(selected_provider))) / "bundles"
    selected_bundle_id = provider.get("selected_bundle_id")
    explicit_selection = _strict_bool(provider.get("enabled")) and bool(selected_bundle_id)
    selected_bundle_dir = bundle_root / str(selected_bundle_id) if selected_bundle_id else None
    manifest_path = selected_bundle_dir / "btc_perpetual_bundle_manifest.json" if selected_bundle_dir else None
    manifest = _read_json(manifest_path)
    source_type = manifest.get("source_type") if manifest else None
    files = _manifest_files(manifest)
    required_file_checks = _required_file_checks(selected_bundle_dir, files, manifest)
    missing_required_files = [
        item["path"] for item in required_file_checks if not item["disk_file_exists"] or not item["manifest_entry_present"]
    ]
    sha256_missing_files = [item["path"] for item in required_file_checks if not item["sha256_present"]]
    record_count_missing_files = [item["path"] for item in required_file_checks if not item["record_count_present"]]
    sample_range_missing_files = [item["path"] for item in required_file_checks if not item["sample_range_present"]]
    source_missing_files = [item["path"] for item in required_file_checks if not item["source_present"]]
    required_files_present = bool(manifest) and all(
        (selected_bundle_dir / filename).exists() and filename in files for filename in REQUIRED_FILES
    )
    sha256_present = bool(manifest) and all(bool(files.get(filename, {}).get("sha256")) for filename in REQUIRED_FILES)
    record_counts_present = bool(manifest) and all(
        files.get(filename, {}).get("record_count") is not None for filename in REQUIRED_FILES
    )
    sample_range_present = _sample_range_present(manifest, files)
    license_note_present = bool(manifest.get("license_note"))
    config_promotion = _strict_bool(provider.get("promotion_clean_allowed"))
    manifest_promotion = _strict_bool(manifest.get("promotion_clean_allowed"))
    blockers: list[str] = []
    if not _strict_bool(provider.get("enabled")):
        blockers.append("btc_perpetual_provider_disabled")
    if _strict_bool(provider.get("allow_network")):
        blockers.append("btc_perpetual_allow_network_must_be_disabled_for_verification")
    if _strict_bool(provider.get("allow_public_rest_fetch")):
        blockers.append("btc_perpetual_public_rest_fetch_must_be_disabled_for_verification")
    if _strict_bool(provider.get("allow_private_endpoints")):
        blockers.append("btc_perpetual_private_endpoints_not_allowed")
    if _strict_bool(provider.get("allow_order_endpoints")):
        blockers.append("btc_perpetual_order_endpoints_not_allowed")
    if not selected_bundle_id:
        blockers.append("btc_perpetual_selected_bundle_missing")
    if not explicit_selection:
        blockers.append("btc_perpetual_explicit_bundle_selection_missing")
    if not selected_bundle_dir or not selected_bundle_dir.exists():
        blockers.append("btc_perpetual_bundle_missing")
    if not manifest_path or not manifest_path.exists():
        blockers.append("btc_perpetual_bundle_manifest_missing")
    if source_type != "production":
        blockers.append("btc_perpetual_bundle_source_type_not_production")
    if not required_files_present:
        blockers.append("btc_perpetual_bundle_required_files_missing")
    if not sha256_present:
        blockers.append("btc_perpetual_bundle_sha256_missing")
    if not record_counts_present:
        blockers.append("btc_perpetual_bundle_record_counts_missing")
    if not sample_range_present:
        blockers.append("btc_perpetual_bundle_sample_range_missing")
    if not license_note_present:
        blockers.append("btc_perpetual_bundle_license_note_missing")
    if manifest and selected_bundle_dir:
        validation = validate_btc_perpetual_data_bundle_manifest(selected_bundle_dir, manifest)
        blockers.extend(validation.get("blockers", []))
    blockers = _dedupe(blockers)
    return {
        "schema_version": "btc_perpetual_bundle_preflight_report_v1",
        "generated_at": generated,
        "commit": _git(["rev-parse", "--short", "HEAD"], cwd=root),
        "branch": _git(["branch", "--show-current"], cwd=root),
        "bundle_root": _relpath(bundle_root, root),
        "selected_bundle_id": str(selected_bundle_id) if selected_bundle_id else None,
        "selected_bundle_dir": _relpath(selected_bundle_dir, root) if selected_bundle_dir and selected_bundle_dir.exists() else None,
        "selected_bundle_manifest_path": _relpath(manifest_path, root) if manifest_path and manifest_path.exists() else None,
        "explicit_bundle_selection_confirmed": bool(explicit_selection),
        "source_type": str(source_type) if source_type else None,
        "required_files": required_file_checks,
        "missing_required_files": missing_required_files,
        "manifest_missing_file_entries": [
            item["path"] for item in required_file_checks if not item["manifest_entry_present"]
        ],
        "disk_missing_required_files": [item["path"] for item in required_file_checks if not item["disk_file_exists"]],
        "sha256_missing_files": sha256_missing_files,
        "record_count_missing_files": record_count_missing_files,
        "sample_range_missing_files": sample_range_missing_files,
        "source_missing_files": source_missing_files,
        "required_files_present": bool(required_files_present),
        "sha256_present": bool(sha256_present),
        "record_counts_present": bool(record_counts_present),
        "sample_range_present": bool(sample_range_present),
        "license_note_present": bool(license_note_present),
        "promotion_clean_allowed_by_config": bool(config_promotion),
        "promotion_clean_allowed_by_manifest": bool(manifest_promotion),
        "preflight_pass": bool(
            explicit_selection
            and source_type == "production"
            and required_files_present
            and sha256_present
            and record_counts_present
            and sample_range_present
            and license_note_present
            and not [item for item in blockers if not item.endswith("_not_allowed_by_config")]
        ),
        "blockers": blockers,
        "next_required_action": _next_required_action(blockers, missing_required_files),
    }


def write_btc_perpetual_bundle_preflight_report(payload: Mapping[str, Any], output_root: Path) -> str:
    output_root.mkdir(parents=True, exist_ok=True)
    output = output_root / "btc_perpetual_bundle_preflight_report.json"
    output.write_text(json.dumps(dict(payload), indent=2, sort_keys=True), encoding="utf-8")
    return str(output)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--config-path", default=str(DEFAULT_CONFIG))
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--generated-at", default="")
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()
    payload = build_btc_perpetual_bundle_preflight_report(
        repo_root=Path(args.repo_root),
        config_path=Path(args.config_path),
        generated_at=args.generated_at or None,
    )
    output = write_btc_perpetual_bundle_preflight_report(payload, Path(args.output_root))
    print(output)
    if args.strict and not payload["preflight_pass"]:
        raise SystemExit(2)


def _provider_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    providers = payload.get("providers", {})
    if not isinstance(providers, Mapping):
        return {}
    selected_provider = str(payload.get("selected_provider") or payload.get("active_provider") or "").strip()
    provider = providers.get(selected_provider or "binance_usdm", {})
    return dict(provider) if isinstance(provider, Mapping) else {}


def _manifest_files(manifest: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    files = manifest.get("files", [])
    if not isinstance(files, list):
        return {}
    return {str(item.get("path")): item for item in files if isinstance(item, Mapping)}


def _sample_range_present(manifest: Mapping[str, Any], files: Mapping[str, Mapping[str, Any]]) -> bool:
    if not manifest.get("sample_start") or not manifest.get("sample_end"):
        return False
    for filename, role in REQUIRED_FILES.items():
        if role in TIME_SERIES_ROLES:
            entry = files.get(filename, {})
            if not entry.get("sample_start") or not entry.get("sample_end"):
                return False
    return True


def _required_file_checks(
    selected_bundle_dir: Path | None,
    files: Mapping[str, Mapping[str, Any]],
    manifest: Mapping[str, Any],
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    manifest_exists = bool(manifest)
    for filename, role in REQUIRED_FILES.items():
        entry = files.get(filename, {})
        path = selected_bundle_dir / filename if selected_bundle_dir else None
        disk_file_exists = bool(path and path.exists())
        manifest_entry_present = manifest_exists and filename in files
        checks.append(
            {
                "path": filename,
                "role": role,
                "disk_file_exists": disk_file_exists,
                "manifest_entry_present": manifest_entry_present,
                "sha256_present": bool(entry.get("sha256")) if manifest_entry_present else False,
                "record_count_present": entry.get("record_count") is not None if manifest_entry_present else False,
                "sample_range_present": _file_sample_range_present(role, entry) if manifest_entry_present else False,
                "source_present": bool(entry.get("source_endpoint_or_archive")) if manifest_entry_present else False,
            }
        )
    return checks


def _file_sample_range_present(role: str, entry: Mapping[str, Any]) -> bool:
    if role not in TIME_SERIES_ROLES:
        return True
    return bool(entry.get("sample_start") and entry.get("sample_end"))


def _next_required_action(blockers: list[str], missing_required_files: list[str]) -> str:
    if "exchange_info.json" in missing_required_files or "funding_info.json" in missing_required_files:
        return "manual_capture_metadata_from_allowed_network"
    if blockers:
        return "repair_btc_perpetual_bundle_manifest"
    return "none"


def _read_json(path: Path | None) -> dict[str, Any]:
    if not path or not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _strict_bool(value: object) -> bool:
    return value is True


def _relpath(path: Path | None, root: Path) -> str | None:
    if path is None:
        return None
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


def _git(args: list[str], *, cwd: Path) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=cwd, stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:
        return "unknown"


if __name__ == "__main__":
    main()
