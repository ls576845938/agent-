#!/usr/bin/env python3
"""Build read-only US equity data status artifacts from existing manifests."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.build_us_equity_provider_capability_matrix import (
    build_provider_capability_matrix,
)
from scripts.build_us_equity_production_bundle_preflight_report import (
    build_production_bundle_preflight_report,
)
from scripts.build_us_equity_provider_verification_report import (
    build_provider_verification_report,
)

DEFAULT_OUTPUT_ROOT = Path("artifacts/us_equity_data_status/latest")
LINEAGE_OUTPUT_ROOT = Path("artifacts/us_equity_data_lineage/latest")
DATA_MANIFEST_ROOT = Path("data/manifests")
PROVIDER_CAPABILITY_MATRIX = LINEAGE_OUTPUT_ROOT / "provider_capability_matrix.json"
PRODUCTION_BUNDLE_PREFLIGHT_REPORT = LINEAGE_OUTPUT_ROOT / "production_bundle_preflight_report.json"
PROVIDER_VERIFICATION_REPORT = LINEAGE_OUTPUT_ROOT / "provider_verification_report.json"


def build_us_equity_data_status(
    *,
    repo_root: Path | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at or datetime.now(timezone.utc).isoformat()
    manifest_items = _load_us_equity_manifests(root)
    manifests = [payload for _, payload in manifest_items]
    data_versions = [str(item.get("data_version", "")) for item in manifests if item.get("data_version")]
    symbols = sorted({str(item.get("symbol", "")).upper() for item in manifests if item.get("symbol")})
    latest_manifest = _latest_existing_path([path for path, _ in manifest_items])
    sample_start = _sample_start(manifests)
    sample_end = _sample_end(manifests)
    adjustment_mode = _adjustment_mode(manifests)
    survivorship_status = _survivorship_status(manifests)
    provider_capability_matrix = build_provider_capability_matrix(
        repo_root=root,
        generated_at=generated,
    )
    production_bundle_preflight_report = build_production_bundle_preflight_report(
        repo_root=root,
        generated_at=generated,
    )
    provider_verification_report = build_provider_verification_report(
        repo_root=root,
        generated_at=generated,
    )
    universe_source_type = (
        "point_in_time_membership"
        if bool(provider_verification_report.get("point_in_time_universe_confirmed", False))
        else ("derived_from_bars" if manifests else "unknown")
    )
    lineage_maturity = _build_data_lineage_maturity(
        manifests=manifests,
        universe_source_type=universe_source_type,
        survivorship_status=survivorship_status,
        provider_verification_report=provider_verification_report,
    )
    lineage_grade = evaluate_data_lineage_grade(
        lineage_maturity,
        universe_source_type=universe_source_type,
    )

    universe_manifest = _build_universe_manifest(
        manifests=manifests,
        data_versions=data_versions,
        symbols=symbols,
        latest_manifest=_relpath(latest_manifest, root) if latest_manifest else None,
        generated_at=generated,
    )
    universe_snapshot_manifest = _build_universe_snapshot_manifest(
        manifests=manifests,
        data_versions=data_versions,
        symbols=symbols,
        sample_start=sample_start,
        sample_end=sample_end,
        generated_at=generated,
        cwd=root,
        provider_verification_report=provider_verification_report,
    )
    corporate_action_report = _build_corporate_action_report(
        manifests=manifests,
        symbols=symbols,
        generated_at=generated,
    )
    corporate_action_status_report = _build_corporate_action_status_report(
        manifests=manifests,
        data_versions=data_versions,
        symbols=symbols,
        adjustment_mode=adjustment_mode,
        generated_at=generated,
        cwd=root,
        provider_verification_report=provider_verification_report,
    )
    survivorship_audit_report = _build_survivorship_audit_report(
        manifests=manifests,
        symbols=symbols,
        sample_start=sample_start,
        sample_end=sample_end,
        universe_version=str(universe_manifest.get("universe_id", "us_equity_manifest_universe_v1")),
        generated_at=generated,
        cwd=root,
        provider_verification_report=provider_verification_report,
    )
    blockers = _build_data_status_blockers(
        manifests,
        universe_manifest,
        corporate_action_report,
        universe_snapshot_manifest,
        corporate_action_status_report,
        survivorship_audit_report,
        lineage_maturity,
        provider_verification_report,
    )
    quality_summary = _aggregate_quality_summary(manifests)
    data_status = {
        "schema_version": "us_equity_data_status_report_v1",
        "generated_at": generated,
        "commit": _git(["rev-parse", "--short", "HEAD"], cwd=root),
        "branch": _git(["branch", "--show-current"], cwd=root),
        "asset": "us_equity",
        "status": "missing" if not manifests else ("complete" if not blockers else "partial"),
        "manifest_count": len(manifests),
        "latest_data_manifest": _relpath(latest_manifest, root) if latest_manifest else None,
        "data_versions": data_versions[:200],
        "symbols": symbols,
        "sources": sorted({str(item.get("source", "")) for item in manifests if item.get("source")}),
        "intervals": sorted({str(item.get("interval", "")) for item in manifests if item.get("interval")}),
        "calendar_id": "XNYS",
        "timezone": "UTC",
        "timezone_status": _timezone_status(manifests),
        "adjustment_policies": _adjustment_policies(manifests),
        "adjustment_mode": adjustment_mode,
        "survivorship_status": survivorship_status,
        "data_lineage_grade": lineage_grade,
        "data_lineage_maturity": lineage_maturity,
        "promotion_clean": bool(lineage_maturity["promotion_clean"]),
        "quality_summary": quality_summary,
        "universe_manifest_path": str(DEFAULT_OUTPUT_ROOT / "universe_manifest.json"),
        "corporate_action_report_path": str(DEFAULT_OUTPUT_ROOT / "corporate_action_report.json"),
        "universe_snapshot_manifest_path": str(LINEAGE_OUTPUT_ROOT / "universe_snapshot_manifest.json"),
        "corporate_action_status_report_path": str(LINEAGE_OUTPUT_ROOT / "corporate_action_status_report.json"),
        "survivorship_audit_report_path": str(LINEAGE_OUTPUT_ROOT / "survivorship_audit_report.json"),
        "provider_capability_matrix_path": str(PROVIDER_CAPABILITY_MATRIX),
        "production_bundle_preflight_report_path": str(PRODUCTION_BUNDLE_PREFLIGHT_REPORT),
        "provider_verification_report_path": str(PROVIDER_VERIFICATION_REPORT),
        "selected_provider": str(provider_verification_report.get("selected_provider", "none") or "none"),
        "source_type": str(provider_verification_report.get("source_type", "none") or "none"),
        "bundle_id": provider_verification_report.get("bundle_id"),
        "production_bundle_preflight_pass": bool(
            provider_verification_report.get("production_bundle_preflight_pass", False)
        ),
        "explicit_bundle_selection_confirmed": bool(
            provider_verification_report.get("explicit_bundle_selection_confirmed", False)
        ),
        "provider_verified_for_promotion": bool(provider_verification_report.get("promotion_clean", False)),
        "blockers": blockers,
        "promotion_ready": False,
        "paper_queue_status": "locked",
        "live_status": "frozen",
    }
    return {
        "data_status_report": data_status,
        "universe_manifest": universe_manifest,
        "corporate_action_report": corporate_action_report,
        "universe_snapshot_manifest": universe_snapshot_manifest,
        "corporate_action_status_report": corporate_action_status_report,
        "survivorship_audit_report": survivorship_audit_report,
        "provider_capability_matrix": provider_capability_matrix,
        "production_bundle_preflight_report": production_bundle_preflight_report,
        "provider_verification_report": provider_verification_report,
    }


def write_us_equity_data_status(payload: Mapping[str, Any], output_root: Path) -> dict[str, str]:
    output_root.mkdir(parents=True, exist_ok=True)
    lineage_root = output_root.parent.parent / "us_equity_data_lineage" / output_root.name
    lineage_root.mkdir(parents=True, exist_ok=True)
    paths = {
        "data_status_report": output_root / "data_status_report.json",
        "universe_manifest": output_root / "universe_manifest.json",
        "corporate_action_report": output_root / "corporate_action_report.json",
        "universe_snapshot_manifest": lineage_root / "universe_snapshot_manifest.json",
        "corporate_action_status_report": lineage_root / "corporate_action_status_report.json",
        "survivorship_audit_report": lineage_root / "survivorship_audit_report.json",
        "provider_capability_matrix": lineage_root / "provider_capability_matrix.json",
        "production_bundle_preflight_report": lineage_root / "production_bundle_preflight_report.json",
        "provider_verification_report": lineage_root / "provider_verification_report.json",
    }
    payload_to_write = {key: dict(payload[key]) for key in paths}
    payload_to_write["data_status_report"]["universe_manifest_path"] = str(paths["universe_manifest"])
    payload_to_write["data_status_report"]["corporate_action_report_path"] = str(paths["corporate_action_report"])
    payload_to_write["data_status_report"]["universe_snapshot_manifest_path"] = str(paths["universe_snapshot_manifest"])
    payload_to_write["data_status_report"]["corporate_action_status_report_path"] = str(paths["corporate_action_status_report"])
    payload_to_write["data_status_report"]["survivorship_audit_report_path"] = str(paths["survivorship_audit_report"])
    payload_to_write["data_status_report"]["provider_capability_matrix_path"] = str(paths["provider_capability_matrix"])
    payload_to_write["data_status_report"]["production_bundle_preflight_report_path"] = str(
        paths["production_bundle_preflight_report"]
    )
    payload_to_write["data_status_report"]["provider_verification_report_path"] = str(paths["provider_verification_report"])
    for key, path in paths.items():
        path.write_text(json.dumps(payload_to_write[key], indent=2, sort_keys=True), encoding="utf-8")
    return {key: str(path) for key, path in paths.items()}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--generated-at", default="")
    args = parser.parse_args()

    payload = build_us_equity_data_status(
        repo_root=Path(args.repo_root),
        generated_at=args.generated_at or None,
    )
    paths = write_us_equity_data_status(payload, Path(args.output_root))
    print(json.dumps(paths, indent=2, sort_keys=True))


def _load_us_equity_manifests(root: Path) -> list[tuple[Path, dict[str, Any]]]:
    result: list[tuple[Path, dict[str, Any]]] = []
    for path in sorted((root / DATA_MANIFEST_ROOT).glob("*.json")):
        if path.stem.startswith("run_"):
            continue
        payload = _read_json(path)
        if _looks_like_us_equity_manifest(payload):
            result.append((path, payload))
    return result


def _build_universe_manifest(
    *,
    manifests: list[Mapping[str, Any]],
    data_versions: list[str],
    symbols: list[str],
    latest_manifest: str | None,
    generated_at: str,
) -> dict[str, Any]:
    ends = sorted(str(item.get("end", "")) for item in manifests if item.get("end"))
    return {
        "schema_version": "us_equity_universe_manifest_v1",
        "generated_at": generated_at,
        "status": "partial" if manifests else "missing",
        "universe_id": "us_equity_manifest_universe_v1",
        "universe_source": "data_manifests",
        "asset": "us_equity",
        "calendar_id": "XNYS",
        "as_of": ends[-1] if ends else "",
        "latest_data_manifest": latest_manifest,
        "manifest_count": len(manifests),
        "symbol_count": len(symbols),
        "symbols": symbols,
        "data_versions": data_versions[:200],
        "adjustment_policies": _adjustment_policies(manifests),
        "selection_rule": "symbols observed in US equity data manifests",
        "survivorship_bias_risk": _survivorship_status(manifests),
        "point_in_time": False,
        "promotion_ready": False,
        "blockers": [
            "universe_snapshot_manifest_derived_only",
            "point_in_time_universe_not_confirmed",
        ],
        "repo_root_independent": True,
        "source_manifest_root": str(DATA_MANIFEST_ROOT),
    }


def _build_corporate_action_report(
    *,
    manifests: list[Mapping[str, Any]],
    symbols: list[str],
    generated_at: str,
) -> dict[str, Any]:
    return {
        "schema_version": "us_equity_corporate_action_report_v1",
        "generated_at": generated_at,
        "asset": "us_equity",
        "status": "manifest_derived_only" if manifests else "missing",
        "symbol_count": len(symbols),
        "symbols": symbols,
        "adjustment_policies": _adjustment_policies(manifests),
        "promotion_ready": False,
        "blockers": ["corporate_action_event_source_missing"],
    }


def _build_universe_snapshot_manifest(
    *,
    manifests: list[Mapping[str, Any]],
    data_versions: list[str],
    symbols: list[str],
    sample_start: str,
    sample_end: str,
    generated_at: str,
    cwd: Path,
    provider_verification_report: Mapping[str, Any],
) -> dict[str, Any]:
    provider_pit_confirmed = bool(provider_verification_report.get("point_in_time_universe_confirmed", False))
    source_type = "point_in_time_membership" if provider_pit_confirmed else ("derived_from_bars" if manifests else "unknown")
    blockers: list[str] = []
    if source_type == "derived_from_bars":
        blockers.extend(
            [
                "universe_snapshot_manifest_derived_only",
                "point_in_time_universe_not_confirmed",
            ]
        )
    pit_validation = _mapping(provider_verification_report.get("pit_validation"))
    survivorship_validation = _mapping(provider_verification_report.get("survivorship_validation"))
    membership_events_available = bool(pit_validation.get("membership_events_available", False))
    delisted_symbols_included = bool(survivorship_validation.get("delisted_symbols_available", False))
    if not membership_events_available:
        blockers.append("membership_events_missing")
    if not bool(provider_verification_report.get("delisting_coverage_confirmed", False)):
        blockers.append("delisting_coverage_missing")
    if not bool(provider_verification_report.get("survivorship_clean", False)):
        blockers.append("survivorship_status_not_clean")
    blockers.extend(_provider_blockers(provider_verification_report))
    bundle_start = str(_mapping(provider_verification_report.get("date_range")).get("start") or "")
    bundle_end = str(_mapping(provider_verification_report.get("date_range")).get("end") or "")
    return {
        "schema_version": "us_equity_universe_snapshot_manifest_v1",
        "generated_at": generated_at,
        "commit": _git(["rev-parse", "--short", "HEAD"], cwd=cwd),
        "branch": _git(["branch", "--show-current"], cwd=cwd),
        "universe_version": "us_equity_manifest_universe_v1",
        "universe_name": "US equity manifest-derived research universe",
        "source_type": source_type,
        "as_of_date": sample_end or bundle_end,
        "sample_start": sample_start or bundle_start,
        "sample_end": sample_end or bundle_end,
        "symbol_count": len(symbols),
        "symbols_hash": _hash_list(symbols),
        "membership_events_available": membership_events_available,
        "membership_events_source": provider_verification_report.get("bundle_manifest_path"),
        "point_in_time_confirmed": provider_pit_confirmed,
        "delisted_symbols_included": delisted_symbols_included,
        "delisting_source": provider_verification_report.get("bundle_manifest_path") if delisted_symbols_included else None,
        "survivorship_risk": "clean" if provider_verification_report.get("survivorship_clean") else ("likely" if manifests else "unknown"),
        "data_versions": data_versions[:200],
        "selected_provider": str(provider_verification_report.get("selected_provider", "none") or "none"),
        "provider_verification_report_path": str(PROVIDER_VERIFICATION_REPORT),
        "provider_verified_for_promotion": bool(provider_verification_report.get("promotion_clean", False)),
        "identifier_mapping_available": bool(provider_verification_report.get("identifier_mapping_available", False)),
        "blockers": _dedupe(blockers),
    }


def _build_corporate_action_status_report(
    *,
    manifests: list[Mapping[str, Any]],
    data_versions: list[str],
    symbols: list[str],
    adjustment_mode: str,
    generated_at: str,
    cwd: Path,
    provider_verification_report: Mapping[str, Any],
) -> dict[str, Any]:
    corporate_validation = _mapping(provider_verification_report.get("corporate_action_validation"))
    replay_validation = _mapping(provider_verification_report.get("adjustment_replay_validation"))
    split_events_available = bool(corporate_validation.get("split_events_available", False))
    dividend_events_available = bool(corporate_validation.get("dividend_events_available", False))
    symbol_change_events_available = bool(corporate_validation.get("symbol_change_events_available", False))
    corporate_source_available = bool(provider_verification_report.get("corporate_action_event_source_available", False))
    adjustment_reproducible = bool(provider_verification_report.get("adjustment_reproducibility_confirmed", False))
    blockers: list[str] = []
    if not corporate_source_available:
        blockers.append("corporate_action_event_source_missing")
    if not split_events_available:
        blockers.append("split_events_source_missing")
    if not dividend_events_available:
        blockers.append("dividend_events_source_missing")
    if not symbol_change_events_available:
        blockers.append("symbol_change_events_source_missing")
    if not adjustment_reproducible:
        blockers.append("price_adjustment_reproducibility_missing")
    if adjustment_mode == "unknown":
        blockers.append("adjustment_mode_unknown")
    blockers.extend(_provider_blockers(provider_verification_report))
    return {
        "schema_version": "us_equity_corporate_action_status_report_v1",
        "generated_at": generated_at,
        "commit": _git(["rev-parse", "--short", "HEAD"], cwd=cwd),
        "branch": _git(["branch", "--show-current"], cwd=cwd),
        "data_version": _combined_data_version(data_versions),
        "price_source": str(provider_verification_report.get("selected_provider") or ("yfinance" if manifests else "unknown")),
        "adjustment_mode": adjustment_mode,
        "split_events_available": split_events_available,
        "split_events_source": provider_verification_report.get("bundle_manifest_path") if split_events_available else None,
        "dividend_events_available": dividend_events_available,
        "dividend_events_source": provider_verification_report.get("bundle_manifest_path") if dividend_events_available else None,
        "merger_events_available": False,
        "merger_events_source": None,
        "delisting_events_available": bool(provider_verification_report.get("delisting_coverage_confirmed", False)),
        "delisting_events_source": provider_verification_report.get("bundle_manifest_path") if provider_verification_report.get("delisting_coverage_confirmed") else None,
        "corporate_action_event_source_available": corporate_source_available,
        "adjustment_reproducible": adjustment_reproducible,
        "promotion_clean": bool(provider_verification_report.get("promotion_clean", False)),
        "symbol_count": len(symbols),
        "symbols_hash": _hash_list(symbols),
        "selected_provider": str(provider_verification_report.get("selected_provider", "none") or "none"),
        "provider_verification_report_path": str(PROVIDER_VERIFICATION_REPORT),
        "provider_verified_for_promotion": bool(provider_verification_report.get("promotion_clean", False)),
        "identifier_mapping_available": bool(provider_verification_report.get("identifier_mapping_available", False)),
        "blockers": _dedupe(blockers),
    }


def _build_survivorship_audit_report(
    *,
    manifests: list[Mapping[str, Any]],
    symbols: list[str],
    sample_start: str,
    sample_end: str,
    universe_version: str,
    generated_at: str,
    cwd: Path,
    provider_verification_report: Mapping[str, Any],
) -> dict[str, Any]:
    pit_validation = _mapping(provider_verification_report.get("pit_validation"))
    survivorship_validation = _mapping(provider_verification_report.get("survivorship_validation"))
    historical_membership_available = bool(pit_validation.get("point_in_time_universe_confirmed", False))
    delisted_symbols_included = bool(survivorship_validation.get("delisted_symbols_available", False))
    membership_event_count = int(pit_validation.get("membership_event_count", 0) or 0)
    delisting_event_count = int(survivorship_validation.get("delisted_symbol_count", 0) or 0)
    survivorship_clean = bool(provider_verification_report.get("survivorship_clean", False))
    blockers: list[str] = []
    if not historical_membership_available:
        blockers.append("historical_membership_missing")
    if not bool(provider_verification_report.get("delisting_coverage_confirmed", False)):
        blockers.append("delisting_coverage_missing")
    if not survivorship_clean:
        blockers.append("survivorship_status_not_clean")
    blockers.extend(_provider_blockers(provider_verification_report))
    return {
        "schema_version": "us_equity_survivorship_audit_report_v1",
        "generated_at": generated_at,
        "commit": _git(["rev-parse", "--short", "HEAD"], cwd=cwd),
        "branch": _git(["branch", "--show-current"], cwd=cwd),
        "universe_version": universe_version,
        "sample_start": sample_start,
        "sample_end": sample_end,
        "symbol_count": len(symbols),
        "delisted_symbols_included": delisted_symbols_included,
        "historical_membership_available": historical_membership_available,
        "membership_event_count": membership_event_count,
        "delisting_event_count": delisting_event_count,
        "survivorship_status": "clean" if survivorship_clean else ("not_clean" if manifests else "unknown"),
        "survivorship_risk": "low" if survivorship_clean else ("likely" if manifests else "unknown"),
        "promotion_clean": bool(provider_verification_report.get("promotion_clean", False)),
        "selected_provider": str(provider_verification_report.get("selected_provider", "none") or "none"),
        "provider_verification_report_path": str(PROVIDER_VERIFICATION_REPORT),
        "provider_verified_for_promotion": bool(provider_verification_report.get("promotion_clean", False)),
        "identifier_mapping_available": bool(provider_verification_report.get("identifier_mapping_available", False)),
        "blockers": _dedupe(blockers),
    }


def _build_data_lineage_maturity(
    *,
    manifests: list[Mapping[str, Any]],
    universe_source_type: str,
    survivorship_status: str,
    provider_verification_report: Mapping[str, Any],
) -> dict[str, bool]:
    price_data_available = bool(manifests)
    universe_snapshot_available = price_data_available and universe_source_type in {
        "derived_from_bars",
        "static_symbol_list",
        "provider_snapshot",
        "point_in_time_membership",
    }
    point_in_time_universe_confirmed = bool(
        universe_source_type == "point_in_time_membership"
        and provider_verification_report.get("point_in_time_universe_confirmed", False)
    )
    corporate_action_event_source_available = bool(
        provider_verification_report.get("corporate_action_event_source_available", False)
    )
    split_adjustment_confirmed = bool(
        corporate_action_event_source_available
        and provider_verification_report.get("adjustment_reproducibility_confirmed", False)
    )
    dividend_adjustment_confirmed = bool(
        corporate_action_event_source_available
        and provider_verification_report.get("adjustment_reproducibility_confirmed", False)
    )
    delisting_coverage_confirmed = bool(
        provider_verification_report.get("delisting_coverage_confirmed", False)
    )
    identifier_mapping_available = bool(
        provider_verification_report.get("identifier_mapping_available", False)
    )
    adjustment_reproducibility_confirmed = bool(
        provider_verification_report.get("adjustment_reproducibility_confirmed", False)
    )
    survivorship_clean = bool(
        point_in_time_universe_confirmed
        and delisting_coverage_confirmed
        and identifier_mapping_available
        and provider_verification_report.get("survivorship_clean", False)
    )
    promotion_clean = bool(
        price_data_available
        and point_in_time_universe_confirmed
        and corporate_action_event_source_available
        and split_adjustment_confirmed
        and dividend_adjustment_confirmed
        and delisting_coverage_confirmed
        and identifier_mapping_available
        and adjustment_reproducibility_confirmed
        and survivorship_clean
        and provider_verification_report.get("promotion_clean", False)
    )
    return {
        "price_data_available": price_data_available,
        "universe_snapshot_available": universe_snapshot_available,
        "point_in_time_universe_confirmed": point_in_time_universe_confirmed,
        "corporate_action_event_source_available": corporate_action_event_source_available,
        "split_adjustment_confirmed": split_adjustment_confirmed,
        "dividend_adjustment_confirmed": dividend_adjustment_confirmed,
        "delisting_coverage_confirmed": delisting_coverage_confirmed,
        "identifier_mapping_available": identifier_mapping_available,
        "adjustment_reproducibility_confirmed": adjustment_reproducibility_confirmed,
        "survivorship_clean": survivorship_clean,
        "promotion_clean": promotion_clean,
    }


def evaluate_data_lineage_grade(
    maturity: Mapping[str, Any],
    *,
    universe_source_type: str,
) -> dict[str, str]:
    """Assign a fail-closed maturity grade from explicit lineage facts."""

    promotion_clean = bool(maturity.get("promotion_clean"))
    point_in_time = bool(maturity.get("point_in_time_universe_confirmed"))
    universe_snapshot = bool(maturity.get("universe_snapshot_available"))
    price_data = bool(maturity.get("price_data_available"))
    required_for_l4 = all(
        bool(maturity.get(key))
        for key in (
            "price_data_available",
            "point_in_time_universe_confirmed",
            "corporate_action_event_source_available",
            "split_adjustment_confirmed",
            "dividend_adjustment_confirmed",
            "delisting_coverage_confirmed",
            "identifier_mapping_available",
            "adjustment_reproducibility_confirmed",
            "survivorship_clean",
            "promotion_clean",
        )
    )

    if required_for_l4 and universe_source_type == "point_in_time_membership":
        return {
            "value": "L4_promotion_clean",
            "reason": "PIT universe, corporate actions, delistings, and survivorship controls are all confirmed.",
        }
    if promotion_clean:
        return {
            "value": "L3_point_in_time_universe",
            "reason": "promotion_clean requested but L4 prerequisites are incomplete; fail closed.",
        }
    if point_in_time:
        return {
            "value": "L3_point_in_time_universe",
            "reason": "Point-in-time universe is confirmed, but promotion-clean corporate action or survivorship controls are incomplete.",
        }
    if universe_snapshot and universe_source_type in {"static_symbol_list", "provider_snapshot"}:
        return {
            "value": "L2_static_snapshot",
            "reason": "Universe is an explicit static/provider snapshot, not historical point-in-time membership.",
        }
    if price_data:
        return {
            "value": "L1_sample_non_pit",
            "reason": "Price data exists, but universe is not point-in-time and cannot be promotion-clean.",
        }
    return {
        "value": "L0_fixture",
        "reason": "No production price data lineage is available.",
    }


def _build_data_status_blockers(
    manifests: list[Mapping[str, Any]],
    universe_manifest: Mapping[str, Any],
    corporate_action_report: Mapping[str, Any],
    universe_snapshot_manifest: Mapping[str, Any],
    corporate_action_status_report: Mapping[str, Any],
    survivorship_audit_report: Mapping[str, Any],
    data_lineage_maturity: Mapping[str, Any],
    provider_verification_report: Mapping[str, Any],
) -> list[str]:
    blockers: list[str] = []
    if not manifests:
        blockers.append("us_equity_data_manifest_missing")
    if universe_manifest.get("blockers"):
        blockers.extend(str(item) for item in universe_manifest["blockers"])
    if corporate_action_report.get("blockers"):
        blockers.extend(str(item) for item in corporate_action_report["blockers"])
    if universe_snapshot_manifest.get("blockers"):
        blockers.extend(str(item) for item in universe_snapshot_manifest["blockers"])
    if corporate_action_status_report.get("blockers"):
        blockers.extend(str(item) for item in corporate_action_status_report["blockers"])
    if survivorship_audit_report.get("blockers"):
        blockers.extend(str(item) for item in survivorship_audit_report["blockers"])
    blockers.extend(_provider_blockers(provider_verification_report))
    if _survivorship_status(manifests) in {"unknown", "mixed"}:
        blockers.append("survivorship_status_not_clean")
    if not bool(data_lineage_maturity.get("identifier_mapping_available", False)):
        blockers.append("identifier_mapping_missing")
    if not bool(data_lineage_maturity.get("adjustment_reproducibility_confirmed", False)):
        blockers.append("adjustment_reproducibility_missing")
    if not bool(data_lineage_maturity.get("promotion_clean")):
        blockers.append("data_lineage_not_promotion_clean")
    return _dedupe(blockers)


def _provider_blockers(provider_verification_report: Mapping[str, Any]) -> list[str]:
    blockers = _list_of_strings(provider_verification_report.get("blockers"))
    if not bool(provider_verification_report.get("promotion_clean", False)):
        blockers.append("provider_not_verified_for_promotion")
    if not bool(provider_verification_report.get("identifier_mapping_available", False)):
        blockers.append("identifier_mapping_missing")
    return _dedupe(blockers)


def _aggregate_quality_summary(manifests: list[Mapping[str, Any]]) -> dict[str, Any]:
    coverages = [_float(item.get("coverage_pct")) for item in manifests if item.get("coverage_pct") is not None]
    quality_scores = [_float(item.get("quality_score")) for item in manifests if item.get("quality_score") is not None]
    issue_keys = [
        "missing_bars",
        "duplicate_bars",
        "invalid_ohlc_rows",
        "non_positive_price_rows",
        "zero_volume_bars",
        "total_issue_count",
    ]
    issue_totals = {key: 0 for key in issue_keys}
    for item in manifests:
        summary = item.get("quality_summary", {})
        if not isinstance(summary, Mapping):
            continue
        for key in issue_keys:
            issue_totals[key] += int(summary.get(key, 0) or 0)
    return {
        "min_coverage_pct": min(coverages) if coverages else 0.0,
        "avg_coverage_pct": (sum(coverages) / len(coverages)) if coverages else 0.0,
        "min_quality_score": min(quality_scores) if quality_scores else 0.0,
        "avg_quality_score": (sum(quality_scores) / len(quality_scores)) if quality_scores else 0.0,
        **issue_totals,
    }


def _timezone_status(manifests: list[Mapping[str, Any]]) -> str:
    values = {str(item.get("timezone", "") or "").upper() for item in manifests}
    values.discard("")
    if not manifests:
        return "missing"
    return "utc" if values == {"UTC"} else "mixed_or_non_utc"


def _adjustment_policies(manifests: list[Mapping[str, Any]]) -> list[str]:
    return sorted(
        {
            str(
                item.get("adjustment_policy")
                or item.get("corporate_action_adjustment")
                or item.get("adjustment")
                or "unknown"
            )
            for item in manifests
        }
    )


def _adjustment_mode(manifests: list[Mapping[str, Any]]) -> str:
    policies = set(_adjustment_policies(manifests))
    policies.discard("")
    if not policies:
        return "unknown"
    if policies == {"raw"}:
        return "raw"
    if policies == {"adj_close"}:
        return "adj_close"
    if policies == {"auto_adjust"}:
        return "auto_adjust"
    if policies == {"back_adjust"}:
        return "back_adjust"
    return "unknown"


def _survivorship_status(manifests: list[Mapping[str, Any]]) -> str:
    values = {
        str(item.get("survivorship_bias_risk", "unknown") or "unknown").lower()
        for item in manifests
    }
    if not values:
        return "unknown"
    if len(values) == 1:
        return next(iter(values))
    return "mixed"


def _sample_start(manifests: list[Mapping[str, Any]]) -> str:
    starts = sorted(
        str(item.get("start") or item.get("requested_start") or "")
        for item in manifests
        if item.get("start") or item.get("requested_start")
    )
    return starts[0][:10] if starts else ""


def _sample_end(manifests: list[Mapping[str, Any]]) -> str:
    ends = sorted(
        str(item.get("end") or item.get("requested_end") or "")
        for item in manifests
        if item.get("end") or item.get("requested_end")
    )
    return ends[-1][:10] if ends else ""


def _combined_data_version(data_versions: list[str]) -> str:
    if not data_versions:
        return ""
    digest = hashlib.sha256(
        json.dumps(sorted(data_versions), separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]
    return f"us_equity_data_versions_sha256:{digest}"


def _hash_list(values: list[str]) -> str:
    encoded = json.dumps(sorted(values), separators=(",", ":"), sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _looks_like_us_equity_manifest(data: Mapping[str, Any]) -> bool:
    source = str(data.get("source", "")).lower()
    asset_class = str(data.get("asset_class", "equity")).lower()
    return (
        all(data.get(key) for key in ("data_version", "source", "symbol", "interval"))
        and source in {"yfinance", "alpaca"}
        and asset_class == "equity"
    )


def _latest_existing_path(paths: list[Path]) -> Path | None:
    existing = [path for path in paths if path.exists()]
    if not existing:
        return None
    return max(existing, key=lambda path: path.stat().st_mtime)


def _relpath(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _list_of_strings(value: object) -> list[str]:
    return [str(item) for item in value if str(item)] if isinstance(value, list) else []


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


def _git(args: list[str], *, cwd: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", *args],
            cwd=cwd,
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except Exception:
        return "unknown"


if __name__ == "__main__":
    main()
