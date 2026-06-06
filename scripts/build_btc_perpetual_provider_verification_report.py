#!/usr/bin/env python3
"""Verify the explicitly selected BTC USD-M perpetual local data bundle."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
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
    from quant_crypto.data.binance_usdm_metadata import evaluate_exchange_info, evaluate_funding_info
    from quant_crypto.data.funding_rate_coverage import funding_rate_coverage_status
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from quant_crypto.data.btc_perpetual_provider_config import (
        default_provider_root,
        selected_btc_perpetual_provider,
    )
    from quant_crypto.data.binance_usdm_metadata import evaluate_exchange_info, evaluate_funding_info
    from quant_crypto.data.funding_rate_coverage import funding_rate_coverage_status

try:
    from scripts.build_btc_perpetual_data_bundle_manifest import REQUIRED_FILES, validate_btc_perpetual_data_bundle_manifest
    from scripts.build_btc_perpetual_bundle_preflight_report import build_btc_perpetual_bundle_preflight_report
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    from build_btc_perpetual_data_bundle_manifest import REQUIRED_FILES, validate_btc_perpetual_data_bundle_manifest
    from build_btc_perpetual_bundle_preflight_report import build_btc_perpetual_bundle_preflight_report


DEFAULT_CONFIG = Path("configs/data/btc_perpetual_sources.yaml")
DEFAULT_OUTPUT_ROOT = Path("artifacts/btc_data_status/latest")
DEFAULT_PREFLIGHT_REPORT = Path("artifacts/btc_data_status/latest/btc_perpetual_bundle_preflight_report.json")
DEFAULT_MANUAL_METADATA_IMPORT_REPORT = Path("artifacts/btc_data_status/latest/btc_manual_metadata_import_report.json")
MANUAL_METADATA_IMPORT_IN_PROGRESS_MARKER = ".btc_manual_metadata_import_in_progress.json"
UTC_CAPTURE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
DIAGNOSTIC_ONLY_WARNINGS = {
    "btc_open_interest_history_not_verified_diagnostic_partial",
    "btc_liquidation_snapshot_missing_diagnostic_only",
    "btc_liquidation_snapshots_missing_diagnostic_only",
    "diagnostic_only_not_gate_evidence",
}


def build_btc_perpetual_provider_verification_report(
    *,
    repo_root: Path | None = None,
    config_path: Path | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    config_rel = config_path or DEFAULT_CONFIG
    config_abs = config_rel if config_rel.is_absolute() else root / config_rel
    generated = generated_at or datetime.now(timezone.utc).isoformat()
    selected_provider, provider = selected_btc_perpetual_provider(config_abs)
    preflight = build_btc_perpetual_bundle_preflight_report(repo_root=root, config_path=config_rel, generated_at=generated)
    selected_bundle_id = provider.get("selected_bundle_id")
    enabled = _strict_bool(provider.get("enabled", False))
    root_path = root / str(provider.get("root", default_provider_root(selected_provider)))
    bundle_dir = root_path / "bundles" / str(selected_bundle_id) if selected_bundle_id else None
    manifest_path = bundle_dir / "btc_perpetual_bundle_manifest.json" if bundle_dir else None
    manifest = _read_json(manifest_path) if manifest_path else {}
    local_bundle_available = bool(bundle_dir and bundle_dir.exists() and manifest_path and manifest_path.exists())
    explicit_selection = bool(enabled and selected_bundle_id)
    source_type = str(manifest.get("source_type")) if manifest else None
    blockers: list[str] = []
    if not enabled:
        blockers.append("btc_perpetual_provider_disabled")
    if not selected_bundle_id:
        blockers.append("btc_perpetual_selected_bundle_missing")
    if not explicit_selection:
        blockers.append("btc_perpetual_explicit_bundle_selection_missing")
    if not local_bundle_available:
        blockers.append("btc_perpetual_local_bundle_missing")
    if _strict_bool(provider.get("allow_private_endpoints", False)):
        blockers.append("btc_perpetual_private_endpoints_not_allowed")
    if _strict_bool(provider.get("allow_order_endpoints", False)):
        blockers.append("btc_perpetual_order_endpoints_not_allowed")
    if _strict_bool(provider.get("allow_network", False)):
        blockers.append("btc_perpetual_allow_network_must_be_disabled_for_verification")
    if _strict_bool(provider.get("allow_public_rest_fetch", False)):
        blockers.append("btc_perpetual_public_rest_fetch_must_be_disabled_for_verification")
    if not preflight.get("preflight_pass", False):
        blockers.append("btc_perpetual_bundle_preflight_not_pass")
    if not local_bundle_available:
        blockers.append("btc_public_api_capability_not_local_verification")
    manifest_validation = {"valid": False, "blockers": []}
    if local_bundle_available and manifest_path and bundle_dir:
        manifest_validation = validate_btc_perpetual_data_bundle_manifest(bundle_dir, manifest)
        blockers.extend(manifest_validation["blockers"])
    roles = _roles(manifest)
    quality = _quality_checks(bundle_dir, manifest) if local_bundle_available and bundle_dir else _empty_quality()
    role_validation = _role_validation(manifest, manifest_validation)
    role_quality = _mapping(quality.get("role_quality_pass"))
    klines_verified = all(
        bool(role_validation.get(role)) and bool(role_quality.get(role, True))
        for role in {"klines_1h", "klines_4h", "klines_1d"}
    )
    mark_verified = bool(role_validation.get("mark_price_klines_1h")) and bool(
        role_quality.get("mark_price_klines_1h", True)
    )
    premium_verified = bool(role_validation.get("premium_index_klines_1h")) and bool(
        role_quality.get("premium_index_klines_1h", True)
    )
    funding_rate_verified = bool(role_validation.get("funding_rate")) and bool(role_quality.get("funding_rate", True))
    funding_info_status = evaluate_funding_info(bundle_dir, manifest) if bundle_dir else {}
    exchange_info_status = evaluate_exchange_info(bundle_dir / "exchange_info.json" if bundle_dir else None)
    manual_import = _manual_metadata_import_status(root=root, bundle_dir=bundle_dir)
    funding_info_verified = bool(role_validation.get("funding_info")) and bool(funding_info_status.get("funding_info_verified"))
    exchange_info_verified = bool(role_validation.get("exchange_info")) and bool(exchange_info_status.get("exchange_info_verified"))
    coverage_type = _open_interest_coverage_type(manifest, roles)
    open_interest_verified = coverage_type == "full_local_archive"
    liquidation_available = "liquidation_snapshots" in roles
    diagnostic_warnings: list[str] = []
    if not klines_verified:
        blockers.append("btc_perpetual_klines_not_verified")
    if not mark_verified:
        blockers.append("btc_perpetual_mark_price_klines_not_verified")
    if not premium_verified:
        blockers.append("btc_perpetual_premium_index_klines_not_verified")
    if not funding_rate_verified:
        blockers.append("btc_perpetual_funding_rate_not_verified")
    if not funding_info_verified:
        blockers.append("btc_perpetual_funding_info_not_verified")
    if not exchange_info_verified:
        blockers.append("btc_perpetual_exchange_info_not_verified")
    if not open_interest_verified:
        diagnostic_warnings.append("btc_open_interest_history_not_verified_diagnostic_partial")
    if source_type in {"fixture", "sample"}:
        blockers.append(f"btc_perpetual_source_type_{source_type}_not_candidate_eligible")
    config_promotion = _strict_bool(provider.get("promotion_clean_allowed", False))
    manifest_promotion = _strict_bool(manifest.get("promotion_clean_allowed", False))
    if not config_promotion:
        blockers.append("btc_perpetual_promotion_clean_not_allowed_by_config")
    if local_bundle_available and not manifest_promotion:
        blockers.append("btc_perpetual_promotion_clean_not_allowed_by_manifest")
    required_ready = [
        enabled,
        explicit_selection,
        local_bundle_available,
        source_type == "production",
        bool(preflight.get("preflight_pass", False)),
        config_promotion,
        manifest_promotion,
        klines_verified,
        mark_verified,
        premium_verified,
        funding_rate_verified,
        funding_info_verified,
        exchange_info_verified,
        quality["interval_grid_pass"],
        quality["utc_alignment_pass"],
        quality["monotonic_time_pass"],
        quality["duplicate_time_check_pass"],
        quality["symbol_consistency_pass"],
        quality["sample_range_alignment_pass"],
        funding_info_verified,
        exchange_info_verified,
        bool(manual_import["verified"]),
    ]
    blockers.extend(funding_info_status.get("blockers", []))
    blockers.extend(exchange_info_status.get("blockers", []))
    blockers.extend(manual_import["blockers"])
    blockers.extend(quality["blockers"])
    diagnostic_warnings.extend(_diagnostic_only_items(blockers))
    blockers = _hard_blockers(blockers)
    perpetual_ready = all(required_ready) and not blockers
    return {
        "schema_version": "btc_perpetual_provider_verification_report_v1",
        "generated_at": generated,
        "commit": _git(["rev-parse", "--short", "HEAD"], cwd=root),
        "branch": _git(["branch", "--show-current"], cwd=root),
        "selected_provider": selected_provider,
        "selected_bundle_id": str(selected_bundle_id) if selected_bundle_id else None,
        "source_type": source_type,
        "provider_config_path": _relpath(config_abs, root),
        "bundle_preflight_report_path": _relpath(root / DEFAULT_PREFLIGHT_REPORT, root)
        if (root / DEFAULT_PREFLIGHT_REPORT).exists()
        else str(DEFAULT_PREFLIGHT_REPORT),
        "preflight_pass": bool(preflight.get("preflight_pass", False)),
        "local_bundle_available": local_bundle_available,
        "explicit_bundle_selection_confirmed": explicit_selection,
        "promotion_clean_allowed_by_config": bool(config_promotion),
        "promotion_clean_allowed_by_manifest": bool(manifest_promotion),
        "klines_verified": bool(klines_verified),
        "mark_price_klines_verified": bool(mark_verified),
        "premium_index_klines_verified": bool(premium_verified),
        "funding_rate_verified": bool(funding_rate_verified),
        "funding_info_verified": bool(funding_info_verified),
        "manual_metadata_import_report_path": manual_import["report_path"],
        "manual_metadata_import_verified": bool(manual_import["verified"]),
        "manual_metadata_import_captured_at": manual_import["captured_at"],
        "manual_metadata_import_exchange_info_output_hash_verified": bool(
            manual_import["exchange_info_output_hash_verified"]
        ),
        "manual_metadata_import_funding_info_output_hash_verified": bool(
            manual_import["funding_info_output_hash_verified"]
        ),
        "funding_info_source_method": funding_info_status.get("source_method"),
        "funding_info_endpoint_response_available": bool(
            funding_info_status.get("endpoint_response_available", False)
        ),
        "funding_info_symbol_adjustment_record_present": bool(
            funding_info_status.get("symbol_adjustment_record_present", False)
        ),
        "funding_interval_hours": funding_info_status.get("funding_interval_hours"),
        "funding_interval_source": funding_info_status.get("funding_interval_source"),
        "funding_interval_inference_confidence": funding_info_status.get("inference_confidence"),
        "exchange_info_verified": bool(exchange_info_verified),
        "exchange_info_source_method": exchange_info_status.get("source_method"),
        "exchange_info_captured_at": exchange_info_status.get("captured_at"),
        "exchange_info_historical_rule_lineage_available": bool(
            exchange_info_status.get("historical_rule_lineage_available", False)
        ),
        "open_interest_verified": bool(open_interest_verified),
        "open_interest_coverage_type": coverage_type,
        "open_interest_gate_eligible": False,
        "liquidation_snapshot_available": bool(liquidation_available),
        "liquidation_snapshot_gate_eligible": False,
        "interval_grid_pass": bool(quality["interval_grid_pass"]),
        "utc_alignment_pass": bool(quality["utc_alignment_pass"]),
        "monotonic_time_pass": bool(quality["monotonic_time_pass"]),
        "duplicate_time_check_pass": bool(quality["duplicate_time_check_pass"]),
        "symbol_consistency_pass": bool(quality["symbol_consistency_pass"]),
        "sample_range_alignment_pass": bool(quality["sample_range_alignment_pass"]),
        "data_lineage_grade_candidate": _grade(source_type, perpetual_ready),
        "perpetual_evidence_ready": bool(perpetual_ready),
        "diagnostic_warnings": _dedupe(diagnostic_warnings),
        "blockers": blockers,
    }


def write_btc_perpetual_provider_verification_report(payload: Mapping[str, Any], output_root: Path) -> str:
    output_root.mkdir(parents=True, exist_ok=True)
    output = output_root / "btc_perpetual_provider_verification_report.json"
    output.write_text(json.dumps(dict(payload), indent=2, sort_keys=True), encoding="utf-8")
    return str(output)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--config-path", default=str(DEFAULT_CONFIG))
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--generated-at", default="")
    args = parser.parse_args()
    payload = build_btc_perpetual_provider_verification_report(
        repo_root=Path(args.repo_root),
        config_path=Path(args.config_path),
        generated_at=args.generated_at or None,
    )
    print(write_btc_perpetual_provider_verification_report(payload, Path(args.output_root)))


def _provider_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    selected_provider = str(payload.get("selected_provider") or payload.get("active_provider") or "").strip()
    return dict(_mapping(_mapping(payload.get("providers")).get(selected_provider or "binance_usdm")))


def _roles(manifest: Mapping[str, Any]) -> set[str]:
    return {str(item.get("role")) for item in manifest.get("files", []) if isinstance(item, Mapping)}


def _role_validation(manifest: Mapping[str, Any], manifest_validation: Mapping[str, Any]) -> dict[str, bool]:
    files = [item for item in manifest.get("files", []) if isinstance(item, Mapping)]
    by_role = {str(item.get("role")): str(item.get("path")) for item in files}
    blockers = [str(item) for item in manifest_validation.get("blockers", [])]
    result: dict[str, bool] = {}
    for filename, role in REQUIRED_FILES.items():
        path = by_role.get(role)
        if not path:
            result[role] = False
            continue
        result[role] = not any(filename in blocker for blocker in blockers)
    return result


def _quality_checks(bundle_dir: Path | None, manifest: Mapping[str, Any]) -> dict[str, Any]:
    files = [item for item in manifest.get("files", []) if isinstance(item, Mapping)]
    by_role = {str(item.get("role")): item for item in files}
    required_roles = {
        "klines_1h",
        "klines_4h",
        "klines_1d",
        "mark_price_klines_1h",
        "premium_index_klines_1h",
        "funding_rate",
    }
    interval_ms = {
        "klines_1h": 3_600_000,
        "klines_4h": 14_400_000,
        "klines_1d": 86_400_000,
        "mark_price_klines_1h": 3_600_000,
        "premium_index_klines_1h": 3_600_000,
    }
    blockers: list[str] = []
    interval_grid_pass = True
    utc_alignment_pass = True
    monotonic_time_pass = True
    duplicate_time_check_pass = True
    sample_range_alignment_pass = bool(manifest.get("sample_start") and manifest.get("sample_end"))
    symbol_consistency_pass = str(manifest.get("symbol")) == "BTCUSDT"
    exchange_info_content_pass = _json_role_has_symbol(bundle_dir, by_role.get("exchange_info"), "BTCUSDT")
    funding_info_content_pass = _json_role_is_valid(bundle_dir, by_role.get("funding_info"))
    role_quality_pass = {role: True for role in required_roles}
    manifest_start = _parse_time_value(manifest.get("sample_start"))
    manifest_end = _parse_time_value(manifest.get("sample_end"))
    for item in files:
        role = str(item.get("role"))
        if role not in required_roles:
            continue
        start = item.get("sample_start")
        end = item.get("sample_end")
        count = int(item.get("record_count", 0) or 0)
        if not start or not end or str(start) >= str(end) or count < 2:
            sample_range_alignment_pass = False
            role_quality_pass[role] = False
            blockers.append(f"btc_perpetual_{role}_sample_range_not_verified")
        if item.get("interval") is None and role.endswith(("1h", "4h", "1d")):
            interval_grid_pass = False
            role_quality_pass[role] = False
            blockers.append(f"btc_perpetual_{role}_interval_missing")
        path = bundle_dir / str(item.get("path", "")) if bundle_dir else None
        if path and path.suffix.lower() == ".csv" and path.exists():
            parsed = _csv_datetimes(path)
            if not parsed:
                sample_range_alignment_pass = False
                role_quality_pass[role] = False
                blockers.append(f"btc_perpetual_{role}_timestamps_missing")
                continue
            times = [value for value, _has_utc in parsed]
            if any(not has_utc for _value, has_utc in parsed):
                utc_alignment_pass = False
                role_quality_pass[role] = False
                blockers.append(f"btc_perpetual_{role}_utc_alignment_not_verified")
            if times != sorted(times):
                monotonic_time_pass = False
                role_quality_pass[role] = False
                blockers.append(f"btc_perpetual_{role}_monotonic_time_failed")
            if len(times) != len(set(times)):
                duplicate_time_check_pass = False
                role_quality_pass[role] = False
                blockers.append(f"btc_perpetual_{role}_duplicate_time_found")
            expected_step = interval_ms.get(role)
            if expected_step:
                for earlier, later in zip(times, times[1:]):
                    delta_ms = int((later - earlier).total_seconds() * 1000)
                    if delta_ms != expected_step:
                        interval_grid_pass = False
                        role_quality_pass[role] = False
                        blockers.append(f"btc_perpetual_{role}_interval_grid_gap")
                        break
            if manifest_start and manifest_end and role == "funding_rate":
                coverage = funding_rate_coverage_status(path, sample_start=manifest_start, sample_end=manifest_end)
                if not coverage.get("coverage_complete", False):
                    sample_range_alignment_pass = False
                    role_quality_pass[role] = False
                    blockers.append(f"btc_perpetual_{role}_sample_range_not_aligned")
                    blockers.extend(str(item) for item in coverage.get("blockers", []))
            elif manifest_start and manifest_end:
                tolerance_ms = interval_ms.get(role, 0)
                if times[0] > manifest_start or times[-1].timestamp() * 1000 + tolerance_ms < manifest_end.timestamp() * 1000:
                    sample_range_alignment_pass = False
                    role_quality_pass[role] = False
                    blockers.append(f"btc_perpetual_{role}_sample_range_not_aligned")
    if not symbol_consistency_pass:
        blockers.append("btc_perpetual_symbol_consistency_failed")
    if not exchange_info_content_pass:
        blockers.append("btc_perpetual_exchange_info_content_not_verified")
    if not funding_info_content_pass:
        blockers.append("btc_perpetual_funding_info_content_not_verified")
    return {
        "interval_grid_pass": interval_grid_pass,
        "utc_alignment_pass": utc_alignment_pass,
        "monotonic_time_pass": monotonic_time_pass,
        "duplicate_time_check_pass": duplicate_time_check_pass,
        "symbol_consistency_pass": symbol_consistency_pass,
        "sample_range_alignment_pass": sample_range_alignment_pass,
        "exchange_info_content_pass": exchange_info_content_pass,
        "funding_info_content_pass": funding_info_content_pass,
        "role_quality_pass": role_quality_pass,
        "blockers": _dedupe(blockers),
    }


def _empty_quality() -> dict[str, Any]:
    return {
        "interval_grid_pass": False,
        "utc_alignment_pass": False,
        "monotonic_time_pass": False,
        "duplicate_time_check_pass": False,
        "symbol_consistency_pass": False,
        "sample_range_alignment_pass": False,
        "exchange_info_content_pass": False,
        "funding_info_content_pass": False,
        "role_quality_pass": {},
        "blockers": [],
    }


def _csv_datetimes(path: Path) -> list[tuple[datetime, bool]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        values = []
        for row in reader:
            for key in ("timestamp", "open_time", "openTime", "fundingTime", "funding_time", "time", "date"):
                value = row.get(key)
                if value:
                    parsed = _parse_time_with_utc(value)
                    if parsed:
                        values.append(parsed)
                    break
        return values


def _parse_time_with_utc(value: object) -> tuple[datetime, bool] | None:
    if value in {None, ""}:
        return None
    text = str(value).strip()
    if text.isdigit():
        number = int(text)
        if number > 10_000_000_000:
            number = number / 1000
        return datetime.fromtimestamp(float(number), tz=timezone.utc), True
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    has_utc = parsed.tzinfo is not None and parsed.astimezone(timezone.utc).utcoffset().total_seconds() == 0
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc), has_utc


def _parse_time_value(value: object) -> datetime | None:
    parsed = _parse_time_with_utc(value)
    return parsed[0] if parsed else None


def _json_role_has_symbol(bundle_dir: Path | None, entry: Mapping[str, Any] | None, symbol: str) -> bool:
    payload = _json_role_payload(bundle_dir, entry)
    if not payload:
        return False
    raw = json.dumps(payload)
    return symbol in raw


def _json_role_is_valid(bundle_dir: Path | None, entry: Mapping[str, Any] | None) -> bool:
    payload = _json_role_payload(bundle_dir, entry)
    return payload is not None


def _json_role_payload(bundle_dir: Path | None, entry: Mapping[str, Any] | None) -> Any:
    if not bundle_dir or not isinstance(entry, Mapping):
        return None
    path = bundle_dir / str(entry.get("path", ""))
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _open_interest_coverage_type(manifest: Mapping[str, Any], roles: set[str]) -> str:
    if "open_interest_hist_1h" in roles:
        files = [item for item in manifest.get("files", []) if isinstance(item, Mapping)]
        hist = next((item for item in files if str(item.get("role")) == "open_interest_hist_1h"), None)
        manifest_start = _parse_time_value(manifest.get("sample_start"))
        manifest_end = _parse_time_value(manifest.get("sample_end"))
        hist_start = _parse_time_value(hist.get("sample_start")) if hist else None
        hist_end = _parse_time_value(hist.get("sample_end")) if hist else None
        if manifest_start and manifest_end and hist_start and hist_end:
            if hist_start <= manifest_start and hist_end >= manifest_end:
                return "full_local_archive"
            days = max((hist_end - hist_start).total_seconds() / 86_400, 0)
            if days <= 35:
                return "latest_month_only"
        return "partial_local_archive"
    if "open_interest_current" in roles:
        return "current_only"
    return "missing"


def _manual_metadata_import_status(*, root: Path, bundle_dir: Path | None) -> dict[str, Any]:
    path = root / DEFAULT_MANUAL_METADATA_IMPORT_REPORT
    marker_blockers = _manual_metadata_import_marker_blockers(bundle_dir)
    if not path.exists():
        return {
            "report_path": None,
            "verified": False,
            "captured_at": None,
            "exchange_info_output_hash_verified": False,
            "funding_info_output_hash_verified": False,
            "blockers": _dedupe([*marker_blockers, "btc_manual_metadata_import_report_missing"]),
        }
    payload = _read_json(path)
    exchange_output = _manual_output_hash_status(
        payload,
        root=root,
        bundle_dir=bundle_dir,
        prefix="exchange_info",
        filename="exchange_info.json",
    )
    funding_output = _manual_output_hash_status(
        payload,
        root=root,
        bundle_dir=bundle_dir,
        prefix="funding_info",
        filename="funding_info.json",
    )
    blockers: list[str] = [*marker_blockers]
    blockers.extend(_list_of_strings(payload.get("blockers")))
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
    if not _utc_capture_timestamp(payload.get("captured_at")):
        blockers.append("btc_manual_metadata_import_captured_at_missing")
    if payload.get("post_import_validation_command") != "make validate-btc-public-data-bundle":
        blockers.append("btc_manual_metadata_import_validation_command_missing")
    if not _manual_import_bundle_matches(payload, root=root, bundle_dir=bundle_dir):
        blockers.append("btc_manual_metadata_import_bundle_dir_not_selected_bundle")
    blockers.extend(_manual_raw_input_blockers(payload, root=root))
    blockers.extend(exchange_output["blockers"])
    blockers.extend(funding_output["blockers"])
    blockers = _dedupe(blockers)
    return {
        "report_path": _relpath(path, root),
        "verified": not blockers,
        "captured_at": payload.get("captured_at"),
        "exchange_info_output_hash_verified": bool(exchange_output["verified"]),
        "funding_info_output_hash_verified": bool(funding_output["verified"]),
        "blockers": blockers,
    }


def _manual_raw_input_blockers(payload: Mapping[str, Any], *, root: Path) -> list[str]:
    raw_inputs = _mapping(payload.get("raw_input_files"))
    return [
        *_manual_raw_file_blockers(
            _mapping(raw_inputs.get("exchange_info_raw")),
            root=root,
            prefix="exchange_info",
        ),
        *_manual_raw_file_blockers(
            _mapping(raw_inputs.get("funding_info_raw")),
            root=root,
            prefix="funding_info",
        ),
    ]


def _manual_raw_file_blockers(raw: Mapping[str, Any], *, root: Path, prefix: str) -> list[str]:
    blockers: list[str] = []
    path = _resolve_path(raw.get("path"), root)
    reported_size = raw.get("size_bytes")
    reported_hash = raw.get("sha256")
    status_path = _resolve_path(raw.get("http_status_file"), root)
    provenance_ok = (
        raw.get("exists") is True
        and path is not None
        and isinstance(reported_size, int)
        and reported_size > 0
        and isinstance(reported_hash, str)
        and SHA256_RE.fullmatch(reported_hash)
    )
    if not provenance_ok:
        blockers.append(f"btc_{prefix}_raw_import_provenance_missing")
    if not _manual_raw_current_file_verified(path, reported_size, reported_hash):
        blockers.append(f"btc_{prefix}_raw_import_current_file_mismatch")
    if not (
        status_path is not None
        and status_path.exists()
        and _read_int_file(status_path) == 200
        and raw.get("http_status") == 200
        and raw.get("http_status_verified") is True
    ):
        blockers.append(f"btc_{prefix}_raw_http_status_not_200")
    return blockers


def _manual_raw_current_file_verified(path: Path | None, reported_size: object, reported_hash: object) -> bool:
    if path is None or not path.exists() or not isinstance(reported_size, int) or not isinstance(reported_hash, str):
        return False
    return path.stat().st_size == reported_size and _sha256(path) == reported_hash


def _manual_metadata_import_marker_blockers(bundle_dir: Path | None) -> list[str]:
    if bundle_dir is None:
        return []
    marker = bundle_dir / MANUAL_METADATA_IMPORT_IN_PROGRESS_MARKER
    return ["btc_manual_metadata_import_in_progress"] if marker.exists() else []


def _manual_output_hash_status(
    payload: Mapping[str, Any],
    *,
    root: Path,
    bundle_dir: Path | None,
    prefix: str,
    filename: str,
) -> dict[str, Any]:
    expected_path = bundle_dir / filename if bundle_dir else None
    reported_path = _resolve_path(payload.get(f"{prefix}_output_path"), root)
    reported_hash = payload.get(f"{prefix}_output_sha256")
    blockers: list[str] = []
    if reported_path is None:
        blockers.append(f"btc_manual_metadata_import_{prefix}_output_path_missing")
    if not isinstance(reported_hash, str) or not SHA256_RE.fullmatch(reported_hash):
        blockers.append(f"btc_manual_metadata_import_{prefix}_output_sha256_missing")
    if expected_path is None or not expected_path.exists():
        blockers.append(f"btc_manual_metadata_import_{prefix}_output_file_missing")
    elif reported_path is not None and not _same_resolved_path(reported_path, expected_path):
        blockers.append(f"btc_manual_metadata_import_{prefix}_output_path_not_selected_bundle")
    elif isinstance(reported_hash, str) and SHA256_RE.fullmatch(reported_hash) and _sha256(expected_path) != reported_hash:
        blockers.append(f"btc_manual_metadata_import_{prefix}_output_hash_mismatch")
    return {"verified": not blockers, "blockers": blockers}


def _manual_import_bundle_matches(payload: Mapping[str, Any], *, root: Path, bundle_dir: Path | None) -> bool:
    reported = _resolve_path(payload.get("bundle_dir"), root)
    return bool(reported and bundle_dir and _same_resolved_path(reported, bundle_dir))


def _resolve_path(value: object, root: Path) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    path = Path(value)
    return path if path.is_absolute() else root / path


def _same_resolved_path(left: Path, right: Path) -> bool:
    try:
        return left.resolve() == right.resolve()
    except OSError:
        return False


def _list_of_strings(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item)]


def _utc_capture_timestamp(value: object) -> bool:
    return isinstance(value, str) and bool(UTC_CAPTURE_RE.fullmatch(value))


def _grade(source_type: str | None, ready: bool) -> str:
    if ready:
        return "L4_perpetual_evidence_ready"
    if source_type == "fixture":
        return "L0_fixture"
    if source_type == "sample":
        return "L1_sample_perpetual_bundle"
    if source_type == "production":
        return "L2_production_bundle_not_verified"
    return "L1_spot_proxy_research_input"


def _read_json(path: Path | None) -> dict[str, Any]:
    if not path or not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _read_int_file(path: Path) -> int | None:
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _strict_bool(value: object) -> bool:
    return value is True


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


def _dedupe(values: list[str]) -> list[str]:
    result = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


def _diagnostic_only_items(values: list[str]) -> list[str]:
    return [value for value in _list_of_strings(values) if value in DIAGNOSTIC_ONLY_WARNINGS]


def _hard_blockers(values: list[str]) -> list[str]:
    return _dedupe([value for value in _list_of_strings(values) if value not in DIAGNOSTIC_ONLY_WARNINGS])


def _git(args: list[str], *, cwd: Path) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=cwd, stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:
        return "unknown"


if __name__ == "__main__":
    main()
