#!/usr/bin/env python3
"""Build US equity provider verification report from local evidence only."""

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
    load_provider_sources_config,
    verify_local_csv_provider,
)
from quant_us.data.lineage.provider_contracts import evaluate_provider_verification  # noqa: E402
from scripts.build_us_equity_production_bundle_preflight_report import (  # noqa: E402
    DEFAULT_OUTPUT as DEFAULT_PREFLIGHT_OUTPUT,
    build_production_bundle_preflight_report,
)


DEFAULT_OUTPUT = Path("artifacts/us_equity_data_lineage/latest/provider_verification_report.json")
DEFAULT_CONFIG = Path("configs/data/us_equity_provider_sources.yaml")


def build_provider_verification_report(
    *,
    repo_root: Path | None = None,
    generated_at: str | None = None,
    config_path: Path = DEFAULT_CONFIG,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at or datetime.now(timezone.utc).isoformat()
    config_ref = config_path if config_path.is_absolute() else root / config_path
    config = load_provider_sources_config(config_ref)
    providers = _mapping(config.get("providers"))
    preflight_report = build_production_bundle_preflight_report(
        repo_root=root,
        generated_at=generated,
        config_path=config_path,
    )
    selected_provider = _selected_provider(providers, root)
    if selected_provider == "local_csv":
        report = verify_local_csv_provider(repo_root=root, config=config)
        verified_artifacts = report.verified_artifacts
    elif selected_provider == "yfinance":
        manifests = _load_yfinance_manifests(root)
        report = evaluate_provider_verification(
            provider_id="yfinance",
            source_type="research_price_bars",
            promotion_clean_allowed=False,
            local_data_available=bool(manifests),
            required_tables_available=False,
            required_fields_available=False,
            record_count=len(manifests),
            date_range=_manifest_date_range(manifests),
            sample_validation_pass=bool(manifests),
            identifier_mapping_available=False,
            point_in_time_universe_confirmed=False,
            delisting_coverage_confirmed=False,
            corporate_action_event_source_available=False,
            adjustment_reproducibility_confirmed=False,
            survivorship_clean=False,
            extra_blockers=[
                "selected_provider_not_promotion_clean_capable",
                "provider_capability_not_verification",
            ],
        )
        verified_artifacts = [{"path": "data/manifests", "record_count": len(manifests)}] if manifests else []
    else:
        report = evaluate_provider_verification(
            provider_id="none",
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
            extra_blockers=["selected_provider_missing"],
        )
        verified_artifacts = []

    preflight_fields = _preflight_fields(preflight_report, root)
    effective_blockers = list(report.blockers)
    effective_blockers.extend(_list_of_strings(preflight_report.get("blockers")))
    if not bool(preflight_fields["production_bundle_preflight_pass"]):
        effective_blockers.append("production_bundle_preflight_failed")
    if selected_provider == "local_csv" and not bool(preflight_fields["explicit_bundle_selection_confirmed"]):
        effective_blockers.append("explicit_bundle_selection_missing")
    if selected_provider == "local_csv" and not bool(preflight_fields["promotion_clean_allowed_by_config"]):
        effective_blockers.append("config_promotion_clean_not_allowed")
    if selected_provider == "local_csv" and not bool(preflight_fields["promotion_clean_allowed_by_manifest"]):
        effective_blockers.append("bundle_promotion_clean_not_allowed")
    if selected_provider == "local_csv" and preflight_fields["active_bundle_validation_status"] != "pass":
        effective_blockers.append("active_bundle_validation_failed")
    effective_blockers = _dedupe(effective_blockers)
    effective_promotion_clean = bool(report.promotion_clean and not effective_blockers)
    grade_candidate = "L4_promotion_clean" if report.promotion_clean else (
        "L0_fixture"
        if report.source_type == "fixture"
        else (
            "L2_static_snapshot"
            if report.source_type == "sample"
            else ("L3_point_in_time_universe" if report.point_in_time_universe_confirmed else "L1_sample_non_pit")
        )
    )
    if not effective_promotion_clean and grade_candidate == "L4_promotion_clean":
        grade_candidate = "L3_point_in_time_universe" if report.point_in_time_universe_confirmed else "L1_sample_non_pit"
    payload = {
        "schema_version": "us_equity_provider_verification_report_v1",
        "generated_at": generated,
        "commit": _git(["rev-parse", "--short", "HEAD"], cwd=root),
        "branch": _git(["branch", "--show-current"], cwd=root),
        "selected_provider": selected_provider,
        "provider_id": report.provider_id,
        "source_type": report.source_type,
        "source_provider": report.source_provider or report.provider_id,
        "bundle_id": report.bundle_id,
        "bundle_manifest_path": report.bundle_manifest_path,
        "bundle_hash": report.bundle_hash,
        "license_note": report.license_note,
        "promotion_clean_allowed": report.promotion_clean_allowed,
        **preflight_fields,
        "provider_config_path": _relpath(config_ref, root),
        "local_data_available": report.local_data_available,
        "required_tables_available": report.required_tables_available,
        "required_fields_available": report.required_fields_available,
        "record_count": report.record_count,
        "date_range": report.date_range,
        "sample_validation_pass": report.sample_validation_pass,
        "point_in_time_universe_confirmed": report.point_in_time_universe_confirmed,
        "delisting_coverage_confirmed": report.delisting_coverage_confirmed,
        "corporate_action_event_source_available": report.corporate_action_event_source_available,
        "identifier_mapping_available": report.identifier_mapping_available,
        "adjustment_reproducibility_confirmed": report.adjustment_reproducibility_confirmed,
        "survivorship_clean": report.survivorship_clean,
        "promotion_clean": effective_promotion_clean,
        "data_lineage_grade_candidate": grade_candidate,
        "bundle_record_count_by_table": report.bundle_record_count_by_table,
        "bundle_date_range_by_table": report.bundle_date_range_by_table,
        "verified_artifacts": verified_artifacts,
        "bundle_validation": report.bundle_validation,
        "structural_validation": report.structural_validation,
        "pit_validation": report.pit_validation,
        "survivorship_validation": report.survivorship_validation,
        "corporate_action_validation": report.corporate_action_validation,
        "adjustment_replay_validation": report.adjustment_replay_validation,
        "blockers": effective_blockers,
    }
    return payload


def write_provider_verification_report(payload: Mapping[str, Any], output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(dict(payload), indent=2, sort_keys=True), encoding="utf-8")
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--config-path", default=str(DEFAULT_CONFIG))
    parser.add_argument("--generated-at", default="")
    args = parser.parse_args()
    payload = build_provider_verification_report(
        repo_root=Path(args.repo_root),
        generated_at=args.generated_at or None,
        config_path=Path(args.config_path),
    )
    print(write_provider_verification_report(payload, Path(args.output)))


def _selected_provider(providers: Mapping[str, Any], root: Path) -> str:
    local_csv = _mapping(providers.get("local_csv"))
    if local_csv.get("enabled", False) is True:
        return "local_csv"
    yfinance = _mapping(providers.get("yfinance"))
    if yfinance.get("enabled", True) is True and _load_yfinance_manifests(root):
        return "yfinance"
    return "none"


def _preflight_fields(preflight_report: Mapping[str, Any], root: Path) -> dict[str, Any]:
    report_path = root / DEFAULT_PREFLIGHT_OUTPUT
    selected_bundle_id = preflight_report.get("selected_bundle_id")
    return {
        "production_bundle_preflight_report_path": _relpath(report_path, root),
        "production_bundle_preflight_pass": bool(preflight_report.get("production_bundle_preflight_pass", False)),
        "selected_bundle_id": selected_bundle_id,
        "selected_bundle_source_type": preflight_report.get("selected_bundle_source_type"),
        "selected_bundle_manifest_path": preflight_report.get("selected_bundle_manifest_path"),
        "explicit_bundle_selection_confirmed": bool(selected_bundle_id),
        "promotion_clean_allowed_by_config": bool(preflight_report.get("promotion_clean_allowed_by_config", False)),
        "promotion_clean_allowed_by_manifest": bool(preflight_report.get("promotion_clean_allowed_by_manifest", False)),
        "active_bundle_validation_status": (
            "pass" if bool(preflight_report.get("production_bundle_preflight_pass", False)) else "fail"
        ),
    }


def _load_yfinance_manifests(root: Path) -> list[dict[str, Any]]:
    result = []
    for path in sorted((root / "data" / "manifests").glob("*.json")):
        if path.stem.startswith("run_"):
            continue
        payload = _read_json(path)
        if (
            all(payload.get(key) for key in ("data_version", "source", "symbol", "interval"))
            and str(payload.get("source", "")).lower() == "yfinance"
            and str(payload.get("asset_class", "equity")).lower() == "equity"
        ):
            result.append(payload)
    return result


def _manifest_date_range(manifests: list[Mapping[str, Any]]) -> dict[str, str | None]:
    starts = sorted(str(item.get("start") or item.get("requested_start") or "")[:10] for item in manifests if item.get("start") or item.get("requested_start"))
    ends = sorted(str(item.get("end") or item.get("requested_end") or "")[:10] for item in manifests if item.get("end") or item.get("requested_end"))
    return {"start": starts[0] if starts else None, "end": ends[-1] if ends else None}


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _relpath(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


def _list_of_strings(value: object) -> list[str]:
    return [str(item) for item in value if str(item)] if isinstance(value, list) else []


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
