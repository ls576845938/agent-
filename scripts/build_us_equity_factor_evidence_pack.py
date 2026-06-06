#!/usr/bin/env python3
"""Build a read-only US equity factor evidence pack from existing artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


DEFAULT_OUTPUT_ROOT = Path("artifacts/us_equity_factor_evidence/latest")
DATA_STATUS_REPORT = Path("artifacts/us_equity_data_status/latest/data_status_report.json")
UNIVERSE_MANIFEST = Path("artifacts/us_equity_data_status/latest/universe_manifest.json")
UNIVERSE_SNAPSHOT_MANIFEST = Path("artifacts/us_equity_data_lineage/latest/universe_snapshot_manifest.json")
CORPORATE_ACTION_STATUS_REPORT = Path("artifacts/us_equity_data_lineage/latest/corporate_action_status_report.json")
SURVIVORSHIP_AUDIT_REPORT = Path("artifacts/us_equity_data_lineage/latest/survivorship_audit_report.json")
PROVIDER_VERIFICATION_REPORT = Path("artifacts/us_equity_data_lineage/latest/provider_verification_report.json")
FACTOR_MINING_ROOT = Path("data/research/factor_mining")
GENERATED_FACTORS_PATH = Path("data/research/generated_factors/factors.json")
GENERATED_STRATEGIES_ROOT = Path("data/research/generated_strategies")

ALLOWED_NEXT_ACTIONS = {
    "research_only",
    "rerun_required",
    "portfolio_candidate_review",
}
REQUIRED_PROVENANCE_FIELDS = ("data_version", "universe_version", "manifest_hash")
REQUIRED_METRIC_FIELDS = (
    "IC_mean",
    "Rank_IC_mean",
    "IC_decay",
    "turnover",
    "cost_adjusted_spread",
)
REQUIRED_STABILITY_FIELDS = ("walk_forward_pass_rate",)
REQUIRED_GATE_FIELDS = (
    "data_lineage_pass",
    "IC_pass",
    "rank_IC_pass",
    "turnover_pass",
    "cost_adjusted_pass",
    "walk_forward_pass",
)


def build_us_equity_factor_evidence_pack(
    *,
    repo_root: Path | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at or datetime.now(timezone.utc).isoformat()
    factor_mining_paths = _factor_mining_report_paths(root)
    latest_factor_mining = _latest_existing_path(factor_mining_paths)
    latest_factor_mining_payload = _read_json(latest_factor_mining) if latest_factor_mining else {}
    generated_factors = _read_json(root / GENERATED_FACTORS_PATH)
    generated_strategy_paths = sorted((root / GENERATED_STRATEGIES_ROOT).glob("*.json"))
    data_status_path = root / DATA_STATUS_REPORT
    data_status = _read_json(data_status_path)
    universe_manifest_path = root / UNIVERSE_MANIFEST
    universe_manifest = _read_json(universe_manifest_path)
    universe_snapshot_manifest_path = root / UNIVERSE_SNAPSHOT_MANIFEST
    corporate_action_status_report_path = root / CORPORATE_ACTION_STATUS_REPORT
    survivorship_audit_report_path = root / SURVIVORSHIP_AUDIT_REPORT
    provider_verification_report_path = root / PROVIDER_VERIFICATION_REPORT
    universe_snapshot_manifest = _read_json(universe_snapshot_manifest_path)
    corporate_action_status_report = _read_json(corporate_action_status_report_path)
    survivorship_audit_report = _read_json(survivorship_audit_report_path)
    provider_verification_report = _read_json(provider_verification_report_path)

    manifest_evidence = _mapping(latest_factor_mining_payload.get("manifest_evidence"))
    factor_scores = _list_of_mappings(latest_factor_mining_payload.get("factor_scores"))
    selected_factors = _list_of_mappings(latest_factor_mining_payload.get("selected_factors"))
    candidate_ranking = _list_of_mappings(latest_factor_mining_payload.get("candidate_ranking"))
    strategy_configs = _list_of_mappings(latest_factor_mining_payload.get("strategy_configs"))
    selected_factor_ids = _selected_factor_ids(
        selected_factors=selected_factors,
        manifest_evidence=manifest_evidence,
    )
    latest_correlation_report = _latest_correlation_path(
        root=root,
        latest_factor_mining_payload=latest_factor_mining_payload,
    )
    coverage = _build_evidence_coverage(manifest_evidence)
    blockers = _build_blockers(
        data_status_path_exists=data_status_path.exists(),
        factor_mining_exists=latest_factor_mining is not None,
        generated_factors_exists=(root / GENERATED_FACTORS_PATH).exists(),
        latest_correlation_report=latest_correlation_report,
        manifest_evidence=manifest_evidence,
        selected_factor_ids=selected_factor_ids,
        strategy_config_count=len(strategy_configs),
    )
    data_version = _data_version(data_status)
    universe_version = str(universe_manifest.get("universe_id", "") or "")
    manifest_hash = _artifact_hash(
        {
            "data_versions": data_status.get("data_versions", []),
            "latest_data_manifest": data_status.get("latest_data_manifest"),
            "universe_id": universe_version,
            "latest_factor_mining_report": _relpath(latest_factor_mining, root)
            if latest_factor_mining
            else None,
        }
    )
    universe_name = str(universe_manifest.get("universe_id", "us_equity_manifest_universe") or "")
    sample_start = _sample_bound(data_status, "sample_start", "start", "requested_start")
    sample_end = _sample_bound(data_status, "sample_end", "end", "requested_end")
    data_lineage_grade = _mapping(data_status.get("data_lineage_grade")) or {
        "value": "L0_fixture",
        "reason": "data lineage grade missing",
    }
    promotion_clean = bool(data_status.get("promotion_clean", False))
    data_lineage_paths = {
        "universe_snapshot_manifest_path": _relpath(universe_snapshot_manifest_path, root)
        if universe_snapshot_manifest_path.exists()
        else None,
        "corporate_action_status_report_path": _relpath(corporate_action_status_report_path, root)
        if corporate_action_status_report_path.exists()
        else None,
        "survivorship_audit_report_path": _relpath(survivorship_audit_report_path, root)
        if survivorship_audit_report_path.exists()
        else None,
        "provider_verification_report_path": _relpath(provider_verification_report_path, root)
        if provider_verification_report_path.exists()
        else None,
    }
    inherited_provider_blockers = _provider_blockers(provider_verification_report)
    inherited_data_blockers = _dedupe(
        _list_of_strings(data_status.get("blockers"))
        + _list_of_strings(universe_snapshot_manifest.get("blockers"))
        + _list_of_strings(corporate_action_status_report.get("blockers"))
        + _list_of_strings(survivorship_audit_report.get("blockers"))
        + inherited_provider_blockers
        + ([] if promotion_clean else ["data_lineage_not_promotion_clean"])
    )
    factor_rows = _factor_rows(
        factor_scores,
        candidate_ranking,
        data_version=data_version,
        universe_version=universe_version,
        manifest_hash=manifest_hash,
        universe_name=universe_name,
        sample_start=sample_start,
        sample_end=sample_end,
        data_lineage_paths=data_lineage_paths,
        data_lineage_grade=data_lineage_grade,
        promotion_clean=promotion_clean,
        provider_verification_report=provider_verification_report,
        inherited_provider_blockers=inherited_provider_blockers,
        inherited_data_blockers=inherited_data_blockers,
    )
    factor_pass_count = sum(
        1 for row in factor_rows if _mapping(row.get("gates")).get("overall_status") == "pass"
    )
    factor_fail_count = len(factor_rows) - factor_pass_count
    blockers = _dedupe(
        blockers
        + inherited_data_blockers
        + [
            blocker
            for row in factor_rows
            for blocker in _list_of_strings(row.get("blocker_reasons"))
        ]
    )
    if factor_rows and factor_pass_count == 0:
        blockers.append("us_equity_no_factor_passed_factor_evidence_gate")
    blockers = _dedupe(blockers)
    factor_metric_blockers = _dedupe(
        [
            blocker
            for row in factor_rows
            for blocker in _list_of_strings(row.get("blocker_reasons"))
            if blocker not in inherited_data_blockers
        ]
    )
    is_placeholder = latest_factor_mining is None and not factor_rows
    is_data_dependent = bool(factor_rows and data_version and manifest_hash)
    allowed_next_action = (
        "portfolio_candidate_review"
        if factor_pass_count > 0
        else ("rerun_required" if is_placeholder else "research_only")
    )
    status = "missing" if is_placeholder else ("complete" if factor_pass_count == len(factor_rows) and factor_rows else "partial")
    payload = {
        "schema_version": "us_equity_factor_evidence_pack_v1",
        "generated_at": generated,
        "commit": _git(["rev-parse", "--short", "HEAD"], cwd=root),
        "branch": _git(["branch", "--show-current"], cwd=root),
        "asset": "us_equity",
        "status": status,
        "data_version": data_version,
        "universe_version": universe_version,
        "manifest_hash": manifest_hash,
        "universe_name": universe_name,
        "sample_start": sample_start,
        "sample_end": sample_end,
        "factor_name": "us_equity_factor_evidence_pack",
        "factor_version": "v1",
        "factor_family": "baseline_factor_pack",
        "evidence_source": "factor_mining_artifact_summary"
        if latest_factor_mining
        else "artifact_summary_placeholder",
        "is_placeholder": is_placeholder,
        "is_data_dependent": is_data_dependent,
        "data_lineage": {
            "data_version": data_version,
            "universe_version": universe_version,
            "manifest_hash": manifest_hash,
            **data_lineage_paths,
            "data_lineage_grade": data_lineage_grade,
            "promotion_clean": promotion_clean,
            "selected_provider": str(provider_verification_report.get("selected_provider", "none") or "none"),
            "source_type": str(provider_verification_report.get("source_type", "none") or "none"),
            "bundle_id": provider_verification_report.get("bundle_id"),
            "provider_verified_for_promotion": bool(provider_verification_report.get("promotion_clean", False)),
            "inherited_data_blockers": inherited_data_blockers,
            "inherited_provider_blockers": inherited_provider_blockers,
            "factor_metric_blockers": factor_metric_blockers,
        },
        "inherited_data_blockers": inherited_data_blockers,
        "inherited_provider_blockers": inherited_provider_blockers,
        "factor_metric_blockers": factor_metric_blockers,
        "metrics": {
            "factor_count": len(factor_rows),
            "factor_pass_count": factor_pass_count,
            "factor_fail_count": factor_fail_count,
        },
        "gates": {
            "data_lineage_pass": bool(data_version and universe_version and manifest_hash and promotion_clean and not inherited_data_blockers),
            "required_evidence_present": factor_pass_count > 0,
            "overall_status": "pass" if factor_pass_count > 0 else "fail",
        },
        "blocker_reasons": blockers,
        "allowed_next_action": allowed_next_action,
        "data_status_report": _relpath(data_status_path, root) if data_status_path.exists() else None,
        "data_versions": [str(item) for item in data_status.get("data_versions", [])][:200],
        "symbols": [str(item) for item in data_status.get("symbols", [])][:500],
        "latest_factor_mining_report": _relpath(latest_factor_mining, root) if latest_factor_mining else None,
        "factor_mining_run_count": len(factor_mining_paths),
        "generated_factors_path": str(GENERATED_FACTORS_PATH) if (root / GENERATED_FACTORS_PATH).exists() else None,
        "generated_factor_count": _generated_factor_count(generated_factors),
        "generated_strategy_count": len(generated_strategy_paths),
        "candidate_count": int(manifest_evidence.get("candidate_count") or len(factor_scores)),
        "selected_factor_count": len(selected_factor_ids),
        "selected_factor_ids": selected_factor_ids,
        "compiled_strategy_count": int(manifest_evidence.get("compiled_strategy_count") or len(strategy_configs)),
        "latest_correlation_report": _relpath(latest_correlation_report, root) if latest_correlation_report else None,
        "evidence_coverage": coverage,
        "quality_filter": _mapping(manifest_evidence.get("quality_filter")),
        "factor_rows": factor_rows,
        "factor_evidence_rows": factor_rows,
        "factor_count": len(factor_rows),
        "factor_pass_count": factor_pass_count,
        "factor_fail_count": factor_fail_count,
        "current_factor_candidates": [
            str(row.get("factor_name", ""))
            for row in factor_rows
            if row.get("allowed_next_action") == "portfolio_candidate_review"
        ],
        "required_evidence": [
            "rank_ic",
            "ic",
            "hit_rate",
            "turnover",
            "style_exposure",
            "capacity_proxy",
            "correlation_report",
            "cost_adjusted_spread",
            "walk_forward_stability",
        ],
        "blockers": blockers,
        "promotion_ready": False,
        "paper_queue_status": "locked",
        "live_status": "frozen",
    }
    return payload


def write_us_equity_factor_evidence_pack(payload: Mapping[str, Any], output_root: Path) -> str:
    output_root.mkdir(parents=True, exist_ok=True)
    output = output_root / "factor_evidence_pack.json"
    output.write_text(json.dumps(dict(payload), indent=2, sort_keys=True), encoding="utf-8")
    return str(output)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--generated-at", default="")
    args = parser.parse_args()

    payload = build_us_equity_factor_evidence_pack(
        repo_root=Path(args.repo_root),
        generated_at=args.generated_at or None,
    )
    output = write_us_equity_factor_evidence_pack(payload, Path(args.output_root))
    print(output)


def _factor_mining_report_paths(root: Path) -> list[Path]:
    return [
        path
        for path in sorted((root / FACTOR_MINING_ROOT).glob("*.json"))
        if not path.name.endswith("_correlation.json")
    ]


def _build_evidence_coverage(manifest_evidence: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "style_exposure": _mapping(manifest_evidence.get("style_exposure_coverage")),
        "capacity": _mapping(manifest_evidence.get("capacity_coverage")),
        "turnover": _mapping(manifest_evidence.get("turnover_coverage")),
        "bar_samples_available": _mapping(manifest_evidence.get("bar_samples_available")),
        "lookahead_guard": str(manifest_evidence.get("lookahead_guard", "")),
    }


def _build_blockers(
    *,
    data_status_path_exists: bool,
    factor_mining_exists: bool,
    generated_factors_exists: bool,
    latest_correlation_report: Path | None,
    manifest_evidence: Mapping[str, Any],
    selected_factor_ids: list[str],
    strategy_config_count: int,
) -> list[str]:
    blockers: list[str] = []
    if not data_status_path_exists:
        blockers.append("us_equity_data_status_report_required")
    if not factor_mining_exists:
        blockers.append("us_equity_factor_mining_report_missing")
    if not generated_factors_exists:
        blockers.append("us_equity_generated_factor_registry_missing")
    if factor_mining_exists and not selected_factor_ids:
        blockers.append("us_equity_selected_factor_missing")
    if factor_mining_exists and strategy_config_count <= 0:
        blockers.append("us_equity_factor_strategy_config_missing")
    if factor_mining_exists and latest_correlation_report is None:
        blockers.append("us_equity_factor_correlation_report_missing")
    if _missing_count(manifest_evidence, "style_exposure_coverage") > 0:
        blockers.append("us_equity_style_exposure_coverage_incomplete")
    if _missing_count(manifest_evidence, "capacity_coverage") > 0:
        blockers.append("us_equity_capacity_coverage_incomplete")
    if _missing_count(manifest_evidence, "turnover_coverage") > 0:
        blockers.append("us_equity_turnover_coverage_incomplete")
    blockers.append("us_equity_factor_walk_forward_stability_required")
    blockers.append("us_equity_factor_cost_adjusted_spread_required")
    blockers.append("us_equity_portfolio_layer_required_before_promotion")
    return _dedupe(blockers)


def _missing_count(manifest_evidence: Mapping[str, Any], key: str) -> int:
    coverage = _mapping(manifest_evidence.get(key))
    try:
        return int(coverage.get("missing_candidates", 0) or 0)
    except (TypeError, ValueError):
        return 0


def _factor_rows(
    factor_scores: list[Mapping[str, Any]],
    candidate_ranking: list[Mapping[str, Any]],
    *,
    data_version: str,
    universe_version: str,
    manifest_hash: str,
    universe_name: str,
    sample_start: str,
    sample_end: str,
    data_lineage_paths: Mapping[str, Any],
    data_lineage_grade: Mapping[str, Any],
    promotion_clean: bool,
    provider_verification_report: Mapping[str, Any],
    inherited_provider_blockers: list[str],
    inherited_data_blockers: list[str],
) -> list[dict[str, Any]]:
    ranking_by_key = {
        (str(item.get("factor_id", "")), str(item.get("bar_size", ""))): item
        for item in candidate_ranking
    }
    rows: list[dict[str, Any]] = []
    for item in factor_scores[:100]:
        factor_id = str(item.get("factor_id", ""))
        bar_size = str(item.get("bar_size", ""))
        rank_row = ranking_by_key.get((factor_id, bar_size), {})
        row = {
            "factor_id": factor_id,
            "bar_size": bar_size,
            "candidate_rank": _int(rank_row.get("candidate_rank") or item.get("candidate_rank")),
            "selected": bool(item.get("selected", False)),
            "rank_ic_mean": _float(item.get("rank_ic_mean")),
            "ic_mean": _float(item.get("ic_mean")),
            "hit_rate": _float(item.get("hit_rate")),
            "turnover": _float(item.get("turnover")),
            "quality_score": _float(item.get("quality_score")),
            "stability_score": _float(item.get("stability_score")),
            "reject_reason": str(item.get("reject_reason", "")),
            "factor_name": factor_id,
            "factor_version": "unknown",
            "factor_family": "unknown",
            "evidence_source": "factor_mining_artifact_summary",
            "is_placeholder": False,
            "is_data_dependent": bool(data_version and factor_id),
            "data_version": data_version,
            "universe_version": universe_version,
            "manifest_hash": manifest_hash,
            "universe_name": universe_name,
            "sample_start": sample_start,
            "sample_end": sample_end,
            "factor_identity": {
                "factor_name": factor_id,
                "factor_family": "unknown",
                "factor_version": "unknown",
                "input_columns": [],
                "calculation_window": "",
                "rebalance_frequency": bar_size or "unknown",
            },
            "data_lineage": {
                "data_version": data_version,
                "universe_version": universe_version,
                "manifest_hash": manifest_hash,
                "sample_start": sample_start,
                "sample_end": sample_end,
                "symbol_count": 0,
                "calendar": "XNYS",
                "adjustment_mode": "unknown",
                "survivorship_status": "unknown",
                "universe_snapshot_manifest_path": data_lineage_paths.get("universe_snapshot_manifest_path"),
                "corporate_action_status_report_path": data_lineage_paths.get("corporate_action_status_report_path"),
                "survivorship_audit_report_path": data_lineage_paths.get("survivorship_audit_report_path"),
                "provider_verification_report_path": data_lineage_paths.get("provider_verification_report_path"),
                "data_lineage_grade": dict(data_lineage_grade),
                "promotion_clean": promotion_clean,
                "selected_provider": str(provider_verification_report.get("selected_provider", "none") or "none"),
                "source_type": str(provider_verification_report.get("source_type", "none") or "none"),
                "bundle_id": provider_verification_report.get("bundle_id"),
                "provider_verified_for_promotion": bool(provider_verification_report.get("promotion_clean", False)),
                "inherited_provider_blockers": inherited_provider_blockers,
                "inherited_data_blockers": inherited_data_blockers,
            },
            "metrics": {
                "IC_mean": _float(item.get("ic_mean")),
                "IC_std": 0.0,
                "Rank_IC_mean": _float(item.get("rank_ic_mean")),
                "Rank_IC_std": 0.0,
                "IC_hit_rate": _float(item.get("hit_rate")),
                "IC_decay": None,
                "long_short_spread": 0.0,
                "cost_adjusted_spread": None,
                "turnover": _float(item.get("turnover")),
                "coverage": None,
                "missing_rate": None,
            },
            "stability": {
                "walk_forward_fold_count": 0,
                "walk_forward_pass_count": 0,
                "walk_forward_pass_rate": None,
                "worst_fold_metric": None,
                "regime_breakdown": "not_available",
            },
            "gates": {
                "data_lineage_pass": bool(data_version and universe_version and manifest_hash and promotion_clean and not inherited_data_blockers),
                "IC_pass": bool(abs(_float(item.get("ic_mean"))) > 0.0),
                "rank_IC_pass": bool(abs(_float(item.get("rank_ic_mean"))) > 0.0),
                "turnover_pass": bool(_float(item.get("turnover")) > 0.0),
                "cost_adjusted_pass": False,
                "walk_forward_pass": False,
            },
            "blocker_reasons": inherited_data_blockers,
            "allowed_next_action": "research_only",
            "overall_status": "fail",
        }
        verdict = evaluate_us_equity_factor_evidence_row(row)
        row["blocker_reasons"] = verdict["blocker_reasons"]
        row["allowed_next_action"] = verdict["allowed_next_action"]
        row["overall_status"] = verdict["overall_status"]
        row["gates"]["overall_status"] = verdict["overall_status"]
        rows.append(row)
    return rows


def evaluate_us_equity_factor_evidence_row(row: Mapping[str, Any]) -> dict[str, Any]:
    """Fail-closed factor-level evidence gate for US equity factors."""

    blockers: list[str] = []
    data_lineage = _mapping(row.get("data_lineage"))
    metrics = _mapping(row.get("metrics"))
    stability = _mapping(row.get("stability"))
    gates = _mapping(row.get("gates"))
    allowed_next_action = str(row.get("allowed_next_action", "") or "")

    if bool(row.get("is_placeholder", True)):
        blockers.append("factor_evidence_placeholder")
    if not bool(row.get("is_data_dependent", False)):
        blockers.append("factor_evidence_not_data_dependent")

    for field in REQUIRED_PROVENANCE_FIELDS:
        value = row.get(field) or data_lineage.get(field)
        if value in (None, "", [], {}):
            blockers.append(f"{field}_missing")

    for field in REQUIRED_METRIC_FIELDS:
        value = metrics.get(field)
        if value in (None, "", [], {}):
            blockers.append(f"{field}_missing")

    for field in REQUIRED_STABILITY_FIELDS:
        value = stability.get(field)
        if value in (None, "", [], {}):
            blockers.append(f"{field}_missing")

    for field in REQUIRED_GATE_FIELDS:
        if gates.get(field) is not True:
            blockers.append(f"{field}_failed")

    if allowed_next_action not in ALLOWED_NEXT_ACTIONS:
        blockers.append("allowed_next_action_invalid")
        allowed_next_action = "rerun_required"

    blockers.extend(_list_of_strings(row.get("blocker_reasons")))
    blockers = _dedupe(blockers)
    overall_status = "pass" if not blockers else "fail"
    if overall_status == "pass":
        allowed_next_action = "portfolio_candidate_review"
    elif allowed_next_action == "portfolio_candidate_review":
        allowed_next_action = "research_only"

    return {
        "overall_status": overall_status,
        "allowed_next_action": allowed_next_action,
        "blocker_reasons": blockers,
    }


def _selected_factor_ids(
    *,
    selected_factors: list[Mapping[str, Any]],
    manifest_evidence: Mapping[str, Any],
) -> list[str]:
    ids = [str(item.get("factor_id", "")) for item in selected_factors if item.get("factor_id")]
    if ids:
        return _dedupe(ids)
    return _dedupe([str(item) for item in manifest_evidence.get("selected_factor_ids", [])])


def _latest_correlation_path(
    *,
    root: Path,
    latest_factor_mining_payload: Mapping[str, Any],
) -> Path | None:
    raw_path = str(latest_factor_mining_payload.get("correlation_report_path", "") or "")
    candidates: list[Path] = []
    if raw_path:
        path = Path(raw_path)
        candidates.append(path if path.is_absolute() else root / path)
    candidates.extend(sorted((root / FACTOR_MINING_ROOT).glob("*_correlation.json")))
    return _latest_existing_path(candidates)


def _generated_factor_count(payload: Mapping[str, Any]) -> int:
    for key in ("factors", "items", "generated_factors"):
        values = payload.get(key)
        if isinstance(values, list):
            return len(values)
        if isinstance(values, dict):
            return len(values)
    return 0


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _list_of_mappings(value: object) -> list[Mapping[str, Any]]:
    return [item for item in value if isinstance(item, Mapping)] if isinstance(value, list) else []


def _list_of_strings(value: object) -> list[str]:
    return [str(item) for item in value if str(item)] if isinstance(value, list) else []


def _provider_blockers(provider_verification_report: Mapping[str, Any]) -> list[str]:
    blockers = _list_of_strings(provider_verification_report.get("blockers"))
    if provider_verification_report and not bool(provider_verification_report.get("promotion_clean", False)):
        blockers.append("provider_not_verified_for_promotion")
    if provider_verification_report and not bool(provider_verification_report.get("identifier_mapping_available", False)):
        blockers.append("identifier_mapping_missing")
    if not provider_verification_report:
        blockers.append("provider_verification_report_missing")
    return _dedupe(blockers)


def _read_json(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


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


def _data_version(data_status: Mapping[str, Any]) -> str:
    versions = [str(item) for item in data_status.get("data_versions", []) if str(item)]
    if not versions:
        return ""
    digest = hashlib.sha256(
        json.dumps(sorted(versions), separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]
    return f"us_equity_data_versions_sha256:{digest}"


def _artifact_hash(payload: Mapping[str, Any]) -> str:
    has_payload = any(value not in (None, "", [], {}) for value in payload.values())
    if not has_payload:
        return ""
    encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _sample_bound(data_status: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        value = data_status.get(key)
        if value:
            return str(value)[:10]
    return ""


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


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
