#!/usr/bin/env python3
"""Clear the BTC manual metadata import marker after blocked evidence is published."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import yaml


DEFAULT_BUNDLE_DIR = Path(
    "data/external/btc_perpetual/binance_usdm/bundles/btc_usdm_binance_btcusdt_20240101_20260512_v1"
)
DEFAULT_IMPORT_REPORT = Path("artifacts/btc_data_status/latest/btc_manual_metadata_import_report.json")
DEFAULT_PROVIDER_REPORT = Path("artifacts/btc_data_status/latest/btc_perpetual_provider_verification_report.json")
DEFAULT_READINESS_REPORT = Path("artifacts/btc_paper_readiness/latest/btc_paper_readiness_report.json")
DEFAULT_CONFIG = Path("configs/data/btc_perpetual_sources.yaml")
MANUAL_METADATA_IMPORT_IN_PROGRESS_MARKER = ".btc_manual_metadata_import_in_progress.json"
UTC_SECOND_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def clear_btc_manual_metadata_import_marker(
    *,
    repo_root: Path | None = None,
    bundle_dir: Path | None = None,
    import_report: Path | None = None,
    provider_report: Path | None = None,
    readiness_report: Path | None = None,
    selected_bundle_config: Path | None = None,
    dry_run: bool = False,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    config_path = _resolve(root, selected_bundle_config or DEFAULT_CONFIG)
    bundle = (
        _resolve(root, bundle_dir)
        if bundle_dir is not None
        else _selected_bundle_dir(root=root, config=config_path) or _resolve(root, DEFAULT_BUNDLE_DIR)
    )
    report_path = _resolve(root, import_report or DEFAULT_IMPORT_REPORT)
    provider_path = _resolve(root, provider_report or DEFAULT_PROVIDER_REPORT)
    readiness_path = _resolve(root, readiness_report or DEFAULT_READINESS_REPORT)
    marker = bundle / MANUAL_METADATA_IMPORT_IN_PROGRESS_MARKER
    report = _read_json(report_path)
    provider = _read_json(provider_path)
    readiness = _read_json(readiness_path)
    blockers = _dedupe(
        [
            *_marker_blockers(marker),
            *_report_blockers(report, root=root, bundle_dir=bundle),
            *_selected_bundle_blockers(bundle_dir=bundle, config=config_path),
            *_blocked_rebuild_blockers(provider=provider, readiness=readiness),
        ]
    )
    if not blockers and not dry_run:
        marker.unlink()
    return {
        "schema_version": "btc_manual_metadata_import_marker_clear_v1",
        "generated_at": generated_at or _utc_z_now(),
        "status": "cleared" if not blockers else "rejected",
        "dry_run": bool(dry_run),
        "marker_path": _relpath(marker, root),
        "marker_exists_before": marker.exists() or (not blockers and not dry_run),
        "marker_exists_after": marker.exists(),
        "bundle_dir": _relpath(bundle, root),
        "import_report": _relpath(report_path, root),
        "provider_report": _relpath(provider_path, root),
        "readiness_report": _relpath(readiness_path, root),
        "blockers": blockers,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--bundle-dir", default="")
    parser.add_argument("--import-report", default=str(DEFAULT_IMPORT_REPORT))
    parser.add_argument("--provider-report", default=str(DEFAULT_PROVIDER_REPORT))
    parser.add_argument("--readiness-report", default=str(DEFAULT_READINESS_REPORT))
    parser.add_argument("--selected-bundle-config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    result = clear_btc_manual_metadata_import_marker(
        repo_root=Path(args.repo_root),
        bundle_dir=Path(args.bundle_dir) if args.bundle_dir else None,
        import_report=Path(args.import_report),
        provider_report=Path(args.provider_report),
        readiness_report=Path(args.readiness_report),
        selected_bundle_config=Path(args.selected_bundle_config),
        dry_run=bool(args.dry_run),
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    if result.get("status") != "cleared":
        raise SystemExit(1)


def _marker_blockers(marker: Path) -> list[str]:
    return [] if marker.exists() else ["btc_manual_metadata_import_in_progress_marker_missing"]


def _report_blockers(payload: Mapping[str, Any], *, root: Path, bundle_dir: Path) -> list[str]:
    blockers: list[str] = []
    if payload.get("schema_version") != "btc_manual_metadata_import_report_v1":
        blockers.append("btc_manual_metadata_import_schema_version_missing_or_invalid")
    if payload.get("status") != "verified":
        blockers.append("btc_manual_metadata_import_not_verified")
    if payload.get("dry_run") is not False:
        blockers.append("btc_manual_metadata_import_is_dry_run")
    if payload.get("writes_performed") is not True:
        blockers.append("btc_manual_metadata_import_write_not_performed")
    if payload.get("exchange_info_verified") is not True:
        blockers.append("btc_manual_metadata_import_exchange_info_not_verified")
    if payload.get("funding_info_verified") is not True:
        blockers.append("btc_manual_metadata_import_funding_info_not_verified")
    if not isinstance(payload.get("captured_at"), str) or not UTC_SECOND_TIMESTAMP_RE.fullmatch(str(payload.get("captured_at"))):
        blockers.append("btc_manual_metadata_import_captured_at_missing")
    if payload.get("post_import_validation_command") != "make validate-btc-public-data-bundle":
        blockers.append("btc_manual_metadata_import_validation_command_missing")
    reported_bundle = _resolve_report_path(payload.get("bundle_dir"), root)
    if reported_bundle is None or not _same_resolved_path(reported_bundle, bundle_dir):
        blockers.append("btc_manual_metadata_import_bundle_dir_not_selected_bundle")
    blockers.extend(
        _output_hash_blockers(
            payload,
            root=root,
            bundle_dir=bundle_dir,
            prefix="exchange_info",
            filename="exchange_info.json",
        )
    )
    blockers.extend(
        _output_hash_blockers(
            payload,
            root=root,
            bundle_dir=bundle_dir,
            prefix="funding_info",
            filename="funding_info.json",
        )
    )
    return blockers


def _output_hash_blockers(
    payload: Mapping[str, Any],
    *,
    root: Path,
    bundle_dir: Path,
    prefix: str,
    filename: str,
) -> list[str]:
    expected_path = bundle_dir / filename
    reported_path = _resolve_report_path(payload.get(f"{prefix}_output_path"), root)
    reported_hash = payload.get(f"{prefix}_output_sha256")
    blockers: list[str] = []
    if reported_path is None:
        blockers.append(f"btc_manual_metadata_import_{prefix}_output_path_missing")
    elif not _same_resolved_path(reported_path, expected_path):
        blockers.append(f"btc_manual_metadata_import_{prefix}_output_path_not_selected_bundle")
    if not expected_path.exists():
        blockers.append(f"btc_manual_metadata_import_{prefix}_output_file_missing")
    if not isinstance(reported_hash, str) or not SHA256_RE.fullmatch(reported_hash):
        blockers.append(f"btc_manual_metadata_import_{prefix}_output_sha256_missing")
    elif expected_path.exists() and _sha256(expected_path) != reported_hash:
        blockers.append(f"btc_manual_metadata_import_{prefix}_output_hash_mismatch")
    return blockers


def _selected_bundle_blockers(*, bundle_dir: Path, config: Path) -> list[str]:
    selected = _selected_bundle_dir(root=config.resolve().parents[2], config=config)
    if selected is None:
        return ["btc_manual_metadata_import_selected_bundle_config_missing"]
    return [] if _same_resolved_path(bundle_dir, selected) else ["btc_manual_metadata_import_bundle_dir_not_selected_bundle"]


def _selected_bundle_dir(*, root: Path, config: Path) -> Path | None:
    if not config.exists():
        return None
    payload = yaml.safe_load(config.read_text(encoding="utf-8")) or {}
    providers = _mapping(payload.get("providers"))
    selected_provider = str(payload.get("selected_provider") or "").strip()
    if not selected_provider:
        enabled = [
            name
            for name, provider_payload in providers.items()
            if isinstance(name, str) and _mapping(provider_payload).get("enabled") is True
        ]
        selected_provider = enabled[0] if len(enabled) == 1 else "binance_usdm"
    provider = _mapping(providers.get(selected_provider))
    root_value = provider.get("root")
    bundle_id = provider.get("selected_bundle_id")
    if not isinstance(root_value, str) or not root_value.strip() or not isinstance(bundle_id, str) or not bundle_id.strip():
        return None
    return root / root_value.strip() / "bundles" / bundle_id.strip()


def _blocked_rebuild_blockers(*, provider: Mapping[str, Any], readiness: Mapping[str, Any]) -> list[str]:
    blockers: list[str] = []
    if "btc_manual_metadata_import_in_progress" not in _list_of_strings(provider.get("blockers")):
        blockers.append("btc_manual_metadata_import_provider_marker_blocker_missing")
    if "btc_paper_readiness_manual_metadata_import_in_progress" not in _list_of_strings(readiness.get("blockers")):
        blockers.append("btc_manual_metadata_import_readiness_marker_blocker_missing")
    return blockers


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return dict(payload) if isinstance(payload, Mapping) else {}


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _resolve_report_path(value: object, root: Path) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    path = Path(value)
    return path if path.is_absolute() else root / path


def _same_resolved_path(left: Path, right: Path) -> bool:
    try:
        return left.resolve() == right.resolve()
    except OSError:
        return False


def _relpath(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _list_of_strings(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item)]


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


def _utc_z_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    main()
