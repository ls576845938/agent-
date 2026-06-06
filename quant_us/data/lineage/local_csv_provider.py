"""Local CSV provider validation for US equity lineage bundles."""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Any, Mapping

try:
    import yaml
except Exception:  # pragma: no cover - PyYAML is expected in this repo env.
    yaml = None  # type: ignore[assignment]

from .provider_contracts import ProviderVerificationReport, evaluate_provider_verification


SOURCE_TYPES = {"fixture", "sample", "production"}
MEMBERSHIP_EVENT_TYPES = {"add", "remove", "list", "delist", "symbol_change", "exchange_change"}
CORPORATE_ACTION_EVENT_TYPES = {"split", "dividend", "merger", "spin_off", "symbol_change", "delisting", "other"}
ADJUSTMENT_REPLAY_TOLERANCE = 1e-6

UNIVERSE_MEMBERSHIP_FIELDS = [
    "security_id",
    "ticker",
    "universe_name",
    "event_type",
    "effective_date",
    "end_date",
    "source_record_id",
]
DELISTED_SYMBOL_FIELDS = [
    "security_id",
    "ticker",
    "delisting_date",
    "delisting_reason",
    "last_trade_date",
    "delisting_return",
    "source_record_id",
]
CORPORATE_ACTION_FIELDS = [
    "security_id",
    "ticker",
    "event_type",
    "ex_date",
    "effective_date",
    "ratio",
    "cash_amount",
    "old_symbol",
    "new_symbol",
    "source_record_id",
]
SYMBOL_MAPPING_FIELDS = [
    "security_id",
    "ticker",
    "start_date",
    "end_date",
    "figi",
    "cik",
    "cusip",
    "permno",
    "exchange",
    "source_record_id",
]
ADJUSTMENT_REPLAY_FIELDS = [
    "security_id",
    "ticker",
    "date",
    "raw_close",
    "adjusted_close",
    "split_factor",
    "dividend_adjustment",
    "total_adjustment_factor",
    "replay_adjusted_close",
    "replay_error",
    "source_record_id",
]

REQUIRED_LOCAL_CSV_FILES = {
    "universe_membership_events": UNIVERSE_MEMBERSHIP_FIELDS,
    "delisted_symbols": DELISTED_SYMBOL_FIELDS,
    "corporate_actions": CORPORATE_ACTION_FIELDS,
    "symbol_mapping": SYMBOL_MAPPING_FIELDS,
    "adjustment_replay": ADJUSTMENT_REPLAY_FIELDS,
}

DATE_FIELDS_BY_FILE = {
    "universe_membership_events": ["effective_date", "end_date"],
    "delisted_symbols": ["delisting_date", "last_trade_date"],
    "corporate_actions": ["ex_date", "effective_date"],
    "symbol_mapping": ["start_date", "end_date"],
    "adjustment_replay": ["date"],
}
CRITICAL_DATE_FIELDS = {
    "universe_membership_events": ["effective_date"],
    "delisted_symbols": ["delisting_date", "last_trade_date"],
    "corporate_actions": ["ex_date"],
    "symbol_mapping": ["start_date"],
    "adjustment_replay": ["date"],
}
EVENT_TYPE_FIELDS = {
    "universe_membership_events": ("event_type", MEMBERSHIP_EVENT_TYPES),
    "corporate_actions": ("event_type", CORPORATE_ACTION_EVENT_TYPES),
}


def load_provider_sources_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"providers": {}}
    if yaml is None:
        raise RuntimeError("PyYAML is required to read us_equity_provider_sources.yaml")
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return dict(payload) if isinstance(payload, Mapping) else {"providers": {}}


def local_csv_config(config: Mapping[str, Any]) -> dict[str, Any]:
    providers = config.get("providers", {})
    if not isinstance(providers, Mapping):
        return {}
    provider = providers.get("local_csv", {})
    return dict(provider) if isinstance(provider, Mapping) else {}


def verify_local_csv_provider(
    *,
    repo_root: Path,
    config: Mapping[str, Any],
) -> ProviderVerificationReport:
    """Verify a local CSV lineage bundle without inventing missing evidence."""

    provider = local_csv_config(config)
    if not _strict_bool(provider.get("enabled", False)):
        return evaluate_provider_verification(
            provider_id="local_csv",
            source_type="none",
            promotion_clean_allowed=False,
            local_data_available=False,
            required_tables_available=False,
            required_fields_available=False,
            record_count=0,
            sample_validation_pass=False,
            identifier_mapping_available=False,
            point_in_time_universe_confirmed=False,
            delisting_coverage_confirmed=False,
            corporate_action_event_source_available=False,
            adjustment_reproducibility_confirmed=False,
            survivorship_clean=False,
            extra_blockers=["local_csv_provider_disabled"],
        )

    root = _provider_root(repo_root, provider)
    manifest_path = _bundle_manifest_path(repo_root=repo_root, provider=provider, root=root)
    validation = validate_local_csv_bundle(
        repo_root=repo_root,
        provider_config=provider,
        root=root,
        manifest_path=manifest_path,
    )
    bundle_validation = validation["bundle_validation"]
    structural_validation = validation["structural_validation"]
    pit_validation = validation["pit_validation"]
    survivorship_validation = validation["survivorship_validation"]
    corporate_action_validation = validation["corporate_action_validation"]
    adjustment_replay_validation = validation["adjustment_replay_validation"]
    source_type = str(bundle_validation.get("source_type") or "none")
    promotion_clean_allowed = _strict_bool(bundle_validation.get("promotion_clean_allowed", False))
    blockers = _dedupe(
        _list_of_strings(bundle_validation.get("blockers"))
        + _list_of_strings(structural_validation.get("blockers"))
        + _list_of_strings(pit_validation.get("blockers"))
        + _list_of_strings(survivorship_validation.get("blockers"))
        + _list_of_strings(corporate_action_validation.get("blockers"))
        + _list_of_strings(adjustment_replay_validation.get("blockers"))
    )
    record_counts = dict(bundle_validation.get("record_counts", {}))
    date_ranges = dict(validation.get("date_ranges", {}))
    verified_artifacts = list(bundle_validation.get("verified_artifacts", []))
    required_tables_available = bool(structural_validation.get("required_tables_available", False))
    required_fields_available = bool(structural_validation.get("required_fields_available", False))
    date_validation_pass = bool(structural_validation.get("date_validation_pass", False))
    event_type_validation_pass = bool(structural_validation.get("event_type_validation_pass", False))
    duplicate_validation_pass = bool(structural_validation.get("duplicate_source_record_id_validation_pass", False))
    symbol_mapping_validation_pass = bool(structural_validation.get("symbol_mapping_validation_pass", False))
    sample_validation_pass = bool(
        date_validation_pass
        and event_type_validation_pass
        and duplicate_validation_pass
        and symbol_mapping_validation_pass
        and not structural_validation.get("blockers")
    )
    local_data_available = bool(required_tables_available and sum(record_counts.values()) > 0)
    corporate_action_source_available = bool(
        corporate_action_validation.get("corporate_action_event_source_available", False)
    )
    adjustment_confirmed = bool(
        adjustment_replay_validation.get("adjustment_reproducibility_confirmed", False)
    )
    survivorship_clean = bool(survivorship_validation.get("survivorship_clean", False))

    return evaluate_provider_verification(
        provider_id="local_csv",
        source_type=source_type,
        promotion_clean_allowed=promotion_clean_allowed,
        local_data_available=local_data_available,
        required_tables_available=required_tables_available,
        required_fields_available=required_fields_available,
        record_count=sum(record_counts.values()),
        date_range=_combined_date_range(date_ranges),
        sample_validation_pass=sample_validation_pass,
        identifier_mapping_available=bool(structural_validation.get("identifier_mapping_available", False)),
        point_in_time_universe_confirmed=bool(pit_validation.get("point_in_time_universe_confirmed", False)),
        delisting_coverage_confirmed=bool(survivorship_validation.get("delisting_coverage_confirmed", False)),
        corporate_action_event_source_available=corporate_action_source_available,
        adjustment_reproducibility_confirmed=adjustment_confirmed,
        survivorship_clean=survivorship_clean,
        bundle_id=_optional_string(bundle_validation.get("bundle_id")),
        bundle_manifest_path=_optional_string(bundle_validation.get("bundle_manifest_path")),
        bundle_hash=_optional_string(bundle_validation.get("bundle_hash")),
        source_provider=_optional_string(bundle_validation.get("source_provider")),
        license_note=_optional_string(bundle_validation.get("license_note")),
        selected_bundle_id=_optional_string(bundle_validation.get("selected_bundle_id")),
        selected_bundle_source_type=_optional_string(bundle_validation.get("source_type")),
        selected_bundle_manifest_path=_optional_string(bundle_validation.get("bundle_manifest_path")),
        explicit_bundle_selection_confirmed=_strict_bool(
            bundle_validation.get("explicit_bundle_selection_confirmed", False)
        ),
        promotion_clean_allowed_by_config=_strict_bool(
            bundle_validation.get("config_promotion_clean_allowed", False)
        ),
        promotion_clean_allowed_by_manifest=_strict_bool(
            bundle_validation.get("bundle_promotion_clean_allowed", False)
        ),
        active_bundle_validation_status=(
            "pass"
            if not blockers
            and required_tables_available
            and required_fields_available
            and sample_validation_pass
            else "fail"
        ),
        verified_artifacts=verified_artifacts,
        bundle_record_count_by_table={key: int(value) for key, value in record_counts.items()},
        bundle_date_range_by_table={key: dict(value) for key, value in date_ranges.items()},
        bundle_validation=bundle_validation,
        structural_validation=structural_validation,
        pit_validation=pit_validation,
        survivorship_validation=survivorship_validation,
        corporate_action_validation=corporate_action_validation,
        adjustment_replay_validation=adjustment_replay_validation,
        extra_blockers=blockers,
    )


def validate_local_csv_bundle(
    *,
    repo_root: Path,
    provider_config: Mapping[str, Any],
    root: Path,
    manifest_path: Path | None,
) -> dict[str, Any]:
    bundle_validation = _validate_bundle_manifest(
        repo_root=repo_root,
        provider_config=provider_config,
        root=root,
        manifest_path=manifest_path,
    )
    files = _bundle_file_paths(
        root=root,
        provider_config=provider_config,
        manifest_path=manifest_path,
    )
    structural_validation, rows_by_table, date_ranges = _validate_csv_structure(files)
    pit_validation = _validate_pit(rows_by_table, bundle_validation)
    survivorship_validation = _validate_survivorship(rows_by_table, pit_validation)
    corporate_action_validation = _validate_corporate_actions(rows_by_table)
    adjustment_replay_validation = _validate_adjustment_replay(
        rows_by_table.get("adjustment_replay", []),
        tolerance=float(provider_config.get("adjustment_replay_tolerance", ADJUSTMENT_REPLAY_TOLERANCE) or ADJUSTMENT_REPLAY_TOLERANCE),
    )
    return {
        "bundle_validation": bundle_validation,
        "structural_validation": structural_validation,
        "pit_validation": pit_validation,
        "survivorship_validation": survivorship_validation,
        "corporate_action_validation": corporate_action_validation,
        "adjustment_replay_validation": adjustment_replay_validation,
        "date_ranges": date_ranges,
        "rows_by_table": rows_by_table,
    }


def _validate_bundle_manifest(
    *,
    repo_root: Path,
    provider_config: Mapping[str, Any],
    root: Path,
    manifest_path: Path | None,
) -> dict[str, Any]:
    blockers: list[str] = []
    manifest: dict[str, Any] = {}
    if manifest_path is None:
        blockers.append("local_csv_bundle_manifest_missing")
    elif not manifest_path.exists():
        blockers.append("local_csv_bundle_manifest_missing")
    else:
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            blockers.append("local_csv_bundle_manifest_invalid_json")

    bundle_id = str(manifest.get("bundle_id", "") or "")
    source_provider = str(manifest.get("source_provider", "") or "")
    source_type = str(manifest.get("source_type", "") or "")
    license_note = str(manifest.get("license_note", "") or "")
    selected_bundle_id = _optional_string(provider_config.get("selected_bundle_id"))
    require_explicit_selection = provider_config.get("require_explicit_bundle_selection", True) is True
    explicit_bundle_selection_confirmed = bool(selected_bundle_id and (not bundle_id or selected_bundle_id == bundle_id))
    bundle_promotion_clean_allowed = _strict_bool(manifest.get("promotion_clean_allowed", False))
    config_promotion_clean_allowed = _strict_bool(provider_config.get("promotion_clean_allowed", False))
    promotion_clean_allowed = bool(bundle_promotion_clean_allowed and config_promotion_clean_allowed)
    sample_start = str(manifest.get("sample_start", "") or "")
    sample_end = str(manifest.get("sample_end", "") or "")
    files_payload = manifest.get("files", {})
    files = dict(files_payload) if isinstance(files_payload, Mapping) else {}

    if not bundle_id:
        blockers.append("bundle_id_missing")
    if not source_provider:
        blockers.append("source_provider_missing")
    if require_explicit_selection and not explicit_bundle_selection_confirmed:
        blockers.append("explicit_bundle_selection_missing")
    if selected_bundle_id and bundle_id and selected_bundle_id != bundle_id:
        blockers.append("selected_bundle_id_mismatch")
    if "promotion_clean_allowed" in manifest and not isinstance(manifest.get("promotion_clean_allowed"), bool):
        blockers.append("bundle_promotion_clean_allowed_not_boolean")
    if "promotion_clean_allowed" in provider_config and not isinstance(provider_config.get("promotion_clean_allowed"), bool):
        blockers.append("config_promotion_clean_allowed_not_boolean")
    if source_type not in SOURCE_TYPES:
        blockers.append("source_type_missing_or_invalid")
    if source_type == "fixture":
        blockers.append("fixture_source_not_promotion_ready")
    elif source_type == "sample":
        blockers.append("sample_source_not_promotion_ready")
    elif source_type == "production" and not promotion_clean_allowed:
        if not bundle_promotion_clean_allowed:
            blockers.append("bundle_promotion_clean_not_allowed")
        if not config_promotion_clean_allowed:
            blockers.append("config_promotion_clean_not_allowed")
        blockers.append("promotion_clean_not_allowed")
    if not sample_start:
        blockers.append("sample_start_missing")
    if not sample_end:
        blockers.append("sample_end_missing")
    if not license_note:
        blockers.append("license_note_missing")
    if not files:
        blockers.append("bundle_files_missing")

    record_counts: dict[str, int] = {}
    files_present: dict[str, bool] = {}
    sha256_validation: dict[str, bool] = {}
    verified_artifacts: list[dict[str, Any]] = []
    for key in REQUIRED_LOCAL_CSV_FILES:
        spec = files.get(key, {}) if isinstance(files.get(key), Mapping) else {}
        rel_path = str(spec.get("path", "") or "")
        expected_sha = str(spec.get("sha256", "") or "")
        expected_count = _int(spec.get("record_count"))
        if not rel_path:
            blockers.append(f"local_csv_{key}_path_missing")
            record_counts[key] = 0
            files_present[key] = False
            sha256_validation[key] = False
            continue
        path = _safe_bundle_file_path(manifest_path.parent if manifest_path else root, rel_path)
        if path is None:
            blockers.append(f"local_csv_{key}_path_outside_bundle")
            record_counts[key] = 0
            files_present[key] = False
            sha256_validation[key] = False
            continue
        files_present[key] = path.exists()
        if not path.exists():
            blockers.append(f"local_csv_{key}_file_missing")
            record_counts[key] = 0
            sha256_validation[key] = False
            continue
        actual_sha = file_sha256(path)
        actual_count = count_csv_records(path)
        record_counts[key] = actual_count
        sha256_validation[key] = bool(expected_sha and expected_sha == actual_sha)
        if not expected_sha:
            blockers.append(f"local_csv_{key}_sha256_missing")
        elif expected_sha != actual_sha:
            blockers.append(f"local_csv_{key}_sha256_mismatch")
        if expected_count != actual_count:
            blockers.append(f"local_csv_{key}_record_count_mismatch")
        verified_artifacts.append(
            {
                "table": key,
                "path": _relpath(path, repo_root),
                "sha256": actual_sha,
                "record_count": actual_count,
            }
        )
    if any(count <= 0 for count in record_counts.values()):
        blockers.append("bundle_required_record_count_zero")

    bundle_hash_payload = {
        "bundle_id": bundle_id,
        "source_provider": source_provider,
        "source_type": source_type,
        "sample_start": sample_start,
        "sample_end": sample_end,
        "files": verified_artifacts,
    }
    return {
        "bundle_id": bundle_id or None,
        "selected_bundle_id": selected_bundle_id,
        "explicit_bundle_selection_confirmed": explicit_bundle_selection_confirmed,
        "bundle_manifest_path": _relpath(manifest_path, repo_root) if manifest_path and manifest_path.exists() else None,
        "bundle_root": _relpath((manifest_path.parent if manifest_path else root), repo_root),
        "source_provider": source_provider or None,
        "source_type": source_type or None,
        "promotion_clean_allowed": promotion_clean_allowed,
        "bundle_promotion_clean_allowed": bundle_promotion_clean_allowed,
        "config_promotion_clean_allowed": config_promotion_clean_allowed,
        "sample_start": sample_start or None,
        "sample_end": sample_end or None,
        "license_note": license_note or None,
        "files_present": files_present,
        "sha256_validation": sha256_validation,
        "record_counts": record_counts,
        "verified_artifacts": verified_artifacts,
        "bundle_hash": _hash_payload(bundle_hash_payload) if verified_artifacts else None,
        "blockers": _dedupe(blockers),
    }


def _bundle_file_paths(
    *,
    root: Path,
    provider_config: Mapping[str, Any],
    manifest_path: Path | None,
) -> dict[str, Path | None]:
    bundle_root = manifest_path.parent if manifest_path and manifest_path.exists() else root
    config_files = provider_config.get("files", {})
    config_files = dict(config_files) if isinstance(config_files, Mapping) else {}
    result: dict[str, Path | None] = {}
    manifest_payload: dict[str, Any] = {}
    if manifest_path and manifest_path.exists():
        manifest_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_files = manifest_payload.get("files", {}) if isinstance(manifest_payload, Mapping) else {}
    manifest_files = dict(manifest_files) if isinstance(manifest_files, Mapping) else {}
    for key in REQUIRED_LOCAL_CSV_FILES:
        rel_path = ""
        spec = manifest_files.get(key)
        if isinstance(spec, Mapping):
            rel_path = str(spec.get("path", "") or "")
        if not rel_path and config_files.get(key):
            rel_path = str(config_files.get(key) or "")
        result[key] = _safe_bundle_file_path(bundle_root, rel_path) if rel_path else None
    return result


def _validate_csv_structure(files: Mapping[str, Path | None]) -> tuple[dict[str, Any], dict[str, list[dict[str, str]]], dict[str, dict[str, str | None]]]:
    blockers: list[str] = []
    rows_by_table: dict[str, list[dict[str, str]]] = {}
    date_ranges: dict[str, dict[str, str | None]] = {}
    required_tables_available = True
    required_fields_available = True
    date_validation_pass = True
    event_type_validation_pass = True
    duplicate_source_record_id_validation_pass = True
    symbol_mapping_validation_pass = True
    source_record_ids: set[str] = set()

    for key, fields in REQUIRED_LOCAL_CSV_FILES.items():
        path = files.get(key)
        if path is None or not path.exists():
            blockers.append(f"local_csv_{key}_file_missing")
            required_tables_available = False
            rows_by_table[key] = []
            date_ranges[key] = {"start": None, "end": None}
            continue
        rows, read_blockers = read_csv_rows(path, key, fields)
        rows_by_table[key] = rows
        if read_blockers:
            blockers.extend(read_blockers)
            required_fields_available = False
        if not rows:
            required_tables_available = False
        table_dates: list[str] = []
        for row in rows:
            security_id = str(row.get("security_id", "") or "")
            source_record_id = str(row.get("source_record_id", "") or "")
            if not security_id:
                blockers.append(f"local_csv_{key}_security_id_missing")
            if not source_record_id:
                blockers.append(f"local_csv_{key}_source_record_id_missing")
            elif source_record_id in source_record_ids:
                blockers.append("duplicate_source_record_id")
                duplicate_source_record_id_validation_pass = False
            else:
                source_record_ids.add(source_record_id)
            event_spec = EVENT_TYPE_FIELDS.get(key)
            if event_spec:
                field, allowed = event_spec
                event_type = str(row.get(field, "") or "")
                if event_type not in allowed:
                    blockers.append(f"local_csv_{key}_event_type_invalid")
                    event_type_validation_pass = False
            for field in DATE_FIELDS_BY_FILE[key]:
                value = str(row.get(field, "") or "")
                if not value:
                    if field in CRITICAL_DATE_FIELDS[key]:
                        blockers.append(f"local_csv_{key}_{field}_missing")
                        date_validation_pass = False
                    continue
                if not _is_iso_date(value):
                    blockers.append(f"local_csv_{key}_{field}_invalid_date")
                    date_validation_pass = False
                else:
                    table_dates.append(value[:10])
        date_ranges[key] = _date_range(table_dates)

    mapping_blockers = _validate_symbol_mapping(rows_by_table)
    if mapping_blockers:
        blockers.extend(mapping_blockers)
        symbol_mapping_validation_pass = False

    return (
        {
            "required_tables_available": required_tables_available,
            "required_fields_available": required_fields_available,
            "date_validation_pass": date_validation_pass,
            "event_type_validation_pass": event_type_validation_pass,
            "duplicate_source_record_id_validation_pass": duplicate_source_record_id_validation_pass,
            "symbol_mapping_validation_pass": symbol_mapping_validation_pass,
            "identifier_mapping_available": bool(rows_by_table.get("symbol_mapping")) and symbol_mapping_validation_pass,
            "blockers": _dedupe(blockers),
        },
        rows_by_table,
        date_ranges,
    )


def _validate_symbol_mapping(rows_by_table: Mapping[str, list[dict[str, str]]]) -> list[str]:
    blockers: list[str] = []
    mapping = rows_by_table.get("symbol_mapping", [])
    if not mapping:
        return ["identifier_mapping_missing"]
    mapped_ids = {str(row.get("security_id", "") or "") for row in mapping if row.get("security_id")}
    for table in ("universe_membership_events", "delisted_symbols", "corporate_actions", "adjustment_replay"):
        for row in rows_by_table.get(table, []):
            security_id = str(row.get("security_id", "") or "")
            if security_id and security_id not in mapped_ids:
                blockers.append(f"local_csv_{table}_security_id_not_in_symbol_mapping")
    by_ticker: dict[str, list[tuple[str, str, str]]] = {}
    for row in mapping:
        ticker = str(row.get("ticker", "") or "")
        security_id = str(row.get("security_id", "") or "")
        start = str(row.get("start_date", "") or "")
        end = str(row.get("end_date", "") or "9999-12-31")
        if ticker and security_id and start:
            by_ticker.setdefault(ticker, []).append((security_id, start[:10], end[:10]))
    for ticker, ranges in by_ticker.items():
        ordered = sorted(ranges, key=lambda item: item[1])
        for idx, current in enumerate(ordered):
            for other in ordered[idx + 1 :]:
                if _ranges_overlap(current[1], current[2], other[1], other[2]):
                    blockers.append(f"local_csv_symbol_mapping_overlap:{ticker}")
    return _dedupe(blockers)


def _validate_pit(rows_by_table: Mapping[str, list[dict[str, str]]], bundle_validation: Mapping[str, Any]) -> dict[str, Any]:
    rows = rows_by_table.get("universe_membership_events", [])
    blockers: list[str] = []
    event_types = {str(row.get("event_type", "") or "") for row in rows}
    dates = [str(row.get("effective_date", "") or "")[:10] for row in rows if _is_iso_date(str(row.get("effective_date", "") or ""))]
    sample_start = str(bundle_validation.get("sample_start") or "")
    sample_end = str(bundle_validation.get("sample_end") or "")
    if not rows:
        blockers.append("membership_events_missing")
    if not (event_types & {"add", "list", "remove", "delist"}):
        blockers.append("membership_event_types_missing")
    if dates and sample_start and min(dates) > sample_start:
        blockers.append("membership_event_range_does_not_cover_sample")
    if dates and sample_end and max(dates) < sample_end:
        blockers.append("membership_event_range_does_not_cover_sample")
    point_in_time = bool(rows and not blockers)
    return {
        "membership_events_available": bool(rows),
        "membership_event_count": len(rows),
        "point_in_time_universe_confirmed": point_in_time,
        "universe_names": sorted({str(row.get("universe_name", "") or "") for row in rows if row.get("universe_name")}),
        "sample_start": min(dates) if dates else None,
        "sample_end": max(dates) if dates else None,
        "blockers": _dedupe(blockers),
    }


def _validate_survivorship(rows_by_table: Mapping[str, list[dict[str, str]]], pit_validation: Mapping[str, Any]) -> dict[str, Any]:
    delisted = rows_by_table.get("delisted_symbols", [])
    membership = rows_by_table.get("universe_membership_events", [])
    blockers: list[str] = []
    if not delisted:
        blockers.append("delisting_coverage_missing")
    delisted_ids = {str(row.get("security_id", "") or "") for row in delisted if row.get("security_id")}
    membership_delist_ids = {
        str(row.get("security_id", "") or "")
        for row in membership
        if str(row.get("event_type", "") or "") == "delist"
    }
    membership_remove_or_delist_ids = {
        str(row.get("security_id", "") or "")
        for row in membership
        if str(row.get("event_type", "") or "") in {"remove", "delist"}
    }
    missing_delisted_records = sorted(membership_delist_ids - delisted_ids)
    if missing_delisted_records:
        blockers.append("membership_delist_without_delisted_symbol_record")
    missing_membership_removals = sorted(delisted_ids - membership_remove_or_delist_ids)
    if missing_membership_removals:
        blockers.append("delisted_symbol_without_membership_remove_or_delist")
    historical_membership_available = bool(pit_validation.get("point_in_time_universe_confirmed", False))
    delisting_coverage_confirmed = bool(delisted and not blockers)
    survivorship_clean = bool(historical_membership_available and delisting_coverage_confirmed)
    if not historical_membership_available:
        blockers.append("historical_membership_missing")
    if not survivorship_clean:
        blockers.append("survivorship_status_not_clean")
    return {
        "delisted_symbols_available": bool(delisted),
        "delisted_symbol_count": len(delisted),
        "historical_membership_available": historical_membership_available,
        "delisting_coverage_confirmed": delisting_coverage_confirmed,
        "survivorship_clean": survivorship_clean,
        "blockers": _dedupe(blockers),
    }


def _validate_corporate_actions(rows_by_table: Mapping[str, list[dict[str, str]]]) -> dict[str, Any]:
    rows = rows_by_table.get("corporate_actions", [])
    event_types = {str(row.get("event_type", "") or "") for row in rows}
    split = "split" in event_types
    dividend = "dividend" in event_types
    symbol_change = "symbol_change" in event_types
    blockers: list[str] = []
    if not rows:
        blockers.append("corporate_action_event_source_missing")
    if not any([split, dividend, symbol_change]):
        blockers.append("split_dividend_symbol_change_events_missing")
    available = bool(rows and any([split, dividend, symbol_change]) and not blockers)
    return {
        "corporate_action_events_available": bool(rows),
        "corporate_action_event_count": len(rows),
        "split_events_available": split,
        "dividend_events_available": dividend,
        "symbol_change_events_available": symbol_change,
        "corporate_action_event_source_available": available,
        "blockers": _dedupe(blockers),
    }


def _validate_adjustment_replay(rows: list[Mapping[str, str]], *, tolerance: float) -> dict[str, Any]:
    blockers: list[str] = []
    errors: list[float] = []
    if not rows:
        blockers.append("adjustment_replay_missing")
    for row in rows:
        raw = str(row.get("replay_error", "") or "")
        if raw == "":
            blockers.append("adjustment_replay_error_missing")
            continue
        try:
            errors.append(abs(float(raw)))
        except ValueError:
            blockers.append("adjustment_replay_error_invalid")
    max_error = max(errors) if errors else None
    mean_error = sum(errors) / len(errors) if errors else None
    if max_error is not None and max_error > tolerance:
        blockers.append("adjustment_replay_error_above_tolerance")
    confirmed = bool(rows and errors and not blockers)
    return {
        "adjustment_replay_available": bool(rows),
        "adjustment_replay_row_count": len(rows),
        "adjustment_reproducibility_confirmed": confirmed,
        "max_replay_error": max_error,
        "mean_replay_error": mean_error,
        "tolerance": tolerance,
        "blockers": _dedupe(blockers),
    }


def _provider_root(repo_root: Path, provider: Mapping[str, Any]) -> Path:
    raw_root = Path(str(provider.get("root") or "data/external/us_equity_lineage"))
    return raw_root if raw_root.is_absolute() else repo_root / raw_root


def _bundle_manifest_path(*, repo_root: Path, provider: Mapping[str, Any], root: Path) -> Path | None:
    selected_bundle_id = str(provider.get("selected_bundle_id") or "")
    if selected_bundle_id:
        selected = root / "bundles" / selected_bundle_id / "provider_bundle_manifest.json"
        if selected.exists() or not provider.get("bundle_manifest"):
            return selected
    raw = str(provider.get("bundle_manifest") or provider.get("bundle_manifest_path") or "")
    if not raw:
        return None
    path = Path(raw)
    return path if path.is_absolute() else (repo_root / path if raw.startswith("data/") else root / path)


def _safe_bundle_file_path(root: Path, rel_path: str) -> Path | None:
    candidate = (root / rel_path).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        return None
    return candidate


def read_csv_rows(path: Path, key: str, expected_fields: list[str]) -> tuple[list[dict[str, str]], list[str]]:
    blockers: list[str] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        headers = list(reader.fieldnames or [])
        missing = [field for field in expected_fields if field not in headers]
        if missing:
            blockers.extend(f"local_csv_{key}_{field}_missing" for field in missing)
        rows = [dict(row) for row in reader]
    if not rows:
        blockers.append(f"local_csv_{key}_empty")
    return rows, blockers


def count_csv_records(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        rows = list(reader)
    return max(0, len(rows) - 1)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_iso_date(value: str) -> bool:
    try:
        date.fromisoformat(value[:10])
        return True
    except ValueError:
        return False


def _date_range(values: list[str]) -> dict[str, str | None]:
    clean = sorted(value[:10] for value in values if value)
    return {"start": clean[0], "end": clean[-1]} if clean else {"start": None, "end": None}


def _combined_date_range(ranges: Mapping[str, Mapping[str, str | None]]) -> dict[str, str | None]:
    starts = sorted(str(value.get("start")) for value in ranges.values() if value.get("start"))
    ends = sorted(str(value.get("end")) for value in ranges.values() if value.get("end"))
    return {"start": starts[0] if starts else None, "end": ends[-1] if ends else None}


def _ranges_overlap(start_a: str, end_a: str, start_b: str, end_b: str) -> bool:
    return start_a <= end_b and start_b <= end_a


def _hash_payload(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _relpath(path: Path | None, root: Path) -> str | None:
    if path is None:
        return None
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


def _int(value: object) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _strict_bool(value: object) -> bool:
    return value is True


def _optional_string(value: object) -> str | None:
    text = str(value or "")
    return text or None


def _list_of_strings(value: object) -> list[str]:
    return [str(item) for item in value if str(item)] if isinstance(value, list) else []


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


def report_to_json(report: ProviderVerificationReport) -> str:
    return json.dumps(report.to_json_dict(), indent=2, sort_keys=True)
