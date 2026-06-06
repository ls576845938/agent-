#!/usr/bin/env python3
"""Run a data-dependent US equity baseline factor evidence pack.

This script reads existing cleaned US equity bars and existing built-in factor
definitions. It does not run portfolio, paper, live, broker, or order paths.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from quant_us.factors.definition import FactorDefinition, FactorLibrary
from quant_us.factors.pipeline import _compute_factor_series, _load_bars
from scripts.build_us_equity_factor_evidence_pack import (
    evaluate_us_equity_factor_evidence_row,
)


DATA_STATUS_REPORT = Path("artifacts/us_equity_data_status/latest/data_status_report.json")
UNIVERSE_MANIFEST = Path("artifacts/us_equity_data_status/latest/universe_manifest.json")
UNIVERSE_SNAPSHOT_MANIFEST = Path("artifacts/us_equity_data_lineage/latest/universe_snapshot_manifest.json")
CORPORATE_ACTION_STATUS_REPORT = Path("artifacts/us_equity_data_lineage/latest/corporate_action_status_report.json")
SURVIVORSHIP_AUDIT_REPORT = Path("artifacts/us_equity_data_lineage/latest/survivorship_audit_report.json")
PROVIDER_VERIFICATION_REPORT = Path("artifacts/us_equity_data_lineage/latest/provider_verification_report.json")
DEFAULT_LATEST_ROOT = Path("artifacts/us_equity_factor_evidence/latest")
DEFAULT_HISTORY_ROOT = Path("artifacts/us_equity_factor_evidence")
DEFAULT_FACTORS = [
    "momentum_20d",
    "reversal_1d",
    "volatility_20d",
]
BAR_SIZE = "1d"
VENDOR = "yfinance"
ASSET_CLASS = "equity"
FORWARD_PERIOD = 5
COST_PER_TURNOVER = 0.001
MIN_CROSS_SECTION = 10
MIN_OBSERVATIONS = 500
MIN_DATES = 60
MIN_ABS_IC = 0.01
MIN_ABS_RANK_IC = 0.01
MAX_AVG_TURNOVER = 1.0
MIN_WALK_FORWARD_PASS_RATE = 2.0 / 3.0


def build_real_us_equity_factor_evidence_pack(
    *,
    repo_root: Path | None = None,
    generated_at: str | None = None,
    factor_ids: list[str] | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at or datetime.now(timezone.utc).isoformat()
    data_status_path = root / DATA_STATUS_REPORT
    universe_manifest_path = root / UNIVERSE_MANIFEST
    universe_snapshot_manifest_path = root / UNIVERSE_SNAPSHOT_MANIFEST
    corporate_action_status_report_path = root / CORPORATE_ACTION_STATUS_REPORT
    survivorship_audit_report_path = root / SURVIVORSHIP_AUDIT_REPORT
    provider_verification_report_path = root / PROVIDER_VERIFICATION_REPORT
    data_status = _read_json(data_status_path)
    universe_manifest = _read_json(universe_manifest_path)
    universe_snapshot_manifest = _read_json(universe_snapshot_manifest_path)
    corporate_action_status_report = _read_json(corporate_action_status_report_path)
    survivorship_audit_report = _read_json(survivorship_audit_report_path)
    provider_verification_report = _read_json(provider_verification_report_path)
    factor_ids = factor_ids or DEFAULT_FACTORS

    symbols = _select_symbols(root, data_status)
    data_versions = _one_day_data_versions(data_status)
    data_version = _combined_data_version(data_versions)
    universe_version = str(universe_manifest.get("universe_id", "") or "")
    universe_name = universe_version or "us_equity_manifest_universe"
    manifest_payloads = _manifest_payloads(root, data_versions)
    manifest_hash = _manifest_hash(manifest_payloads)
    data_lineage_grade = _mapping(data_status.get("data_lineage_grade")) or {
        "value": "L0_fixture",
        "reason": "data lineage grade missing",
    }
    promotion_clean = bool(data_status.get("promotion_clean", False))
    inherited_data_blockers = _inherited_data_blockers(
        data_status,
        universe_snapshot_manifest,
        corporate_action_status_report,
        survivorship_audit_report,
        provider_verification_report,
        promotion_clean=promotion_clean,
    )
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
    adjustment_mode = _daily_adjustment_mode(manifest_payloads)
    survivorship_status = str(
        survivorship_audit_report.get("survivorship_status")
        or data_status.get("survivorship_status", "unknown")
        or "unknown"
    )
    calendar = str(data_status.get("calendar_id", "XNYS") or "XNYS")

    bars, bars_error = _load_source_bars(root, symbols)
    rows: list[dict[str, Any]] = []
    factor_lib = FactorLibrary()

    if not bars.empty:
        bars = bars.copy()
        bars["timestamp_utc"] = pd.to_datetime(bars["timestamp_utc"], utc=True)
        bars["date"] = bars["timestamp_utc"].dt.date.astype(str)
        bars = bars.sort_values(["symbol", "timestamp_utc"]).reset_index(drop=True)
        sample_start = str(bars["date"].min())
        sample_end = str(bars["date"].max())
        forward_returns = _build_forward_returns(bars, FORWARD_PERIOD)
        for factor_id in factor_ids:
            definition = factor_lib.get(factor_id)
            factor_frame = _compute_factor_frame(bars, definition)
            row = _build_factor_row(
                definition=definition,
                factor_frame=factor_frame,
                forward_returns=forward_returns,
                source_bars=bars,
                data_version=data_version,
                data_versions=data_versions,
                universe_version=universe_version,
                manifest_hash=manifest_hash,
                universe_name=universe_name,
                sample_start=sample_start,
                sample_end=sample_end,
                symbol_count=len(symbols),
                calendar=calendar,
                adjustment_mode=adjustment_mode,
                survivorship_status=survivorship_status,
                data_blockers=inherited_data_blockers,
                data_lineage_paths=data_lineage_paths,
                data_lineage_grade=data_lineage_grade,
                promotion_clean=promotion_clean,
                provider_verification_report=provider_verification_report,
                inherited_provider_blockers=inherited_provider_blockers,
            )
            rows.append(row)
    else:
        sample_start = ""
        sample_end = ""

    pack_blockers = _dedupe(inherited_data_blockers)
    if bars_error:
        pack_blockers.append(bars_error)
    if not data_status_path.exists():
        pack_blockers.append("us_equity_data_status_report_required")
    if not universe_manifest_path.exists():
        pack_blockers.append("us_equity_universe_manifest_required")
    if not data_version:
        pack_blockers.append("data_version_missing")
    if not universe_version:
        pack_blockers.append("universe_version_missing")
    if not manifest_hash:
        pack_blockers.append("manifest_hash_missing")
    if not rows:
        pack_blockers.append("us_equity_factor_rows_missing")

    factor_pass_count = sum(
        1 for row in rows if _mapping(row.get("gates")).get("overall_status") == "pass"
    )
    factor_fail_count = len(rows) - factor_pass_count
    factor_metric_blockers: list[str] = []
    for row in rows:
        pack_blockers.extend(_list_of_strings(row.get("blocker_reasons")))
        factor_metric_blockers.extend(
            blocker
            for blocker in _list_of_strings(row.get("blocker_reasons"))
            if blocker not in inherited_data_blockers
        )
    if rows and factor_pass_count == 0:
        pack_blockers.append("us_equity_no_factor_passed_factor_evidence_gate")
    pack_blockers = _dedupe(pack_blockers)
    factor_metric_blockers = _dedupe(factor_metric_blockers)

    current_factor_candidates = [
        str(row["factor_name"])
        for row in rows
        if row.get("allowed_next_action") == "portfolio_candidate_review"
    ]
    if not promotion_clean:
        current_factor_candidates = []
    allowed_next_action = (
        "portfolio_candidate_review"
        if current_factor_candidates
        else ("rerun_required" if not rows else "research_only")
    )
    status = "missing" if not rows else ("complete" if factor_pass_count == len(rows) and not pack_blockers else "partial")

    return {
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
        "factor_name": "us_equity_baseline_factor_evidence_pack",
        "factor_version": "v1",
        "factor_family": "baseline_cross_sectional",
        "evidence_source": "real_us_equity_factor_run_v1",
        "is_placeholder": False if rows else True,
        "is_data_dependent": bool(rows and data_version and manifest_hash),
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
            "inherited_provider_blockers": inherited_provider_blockers,
            "inherited_data_blockers": inherited_data_blockers,
            "factor_metric_blockers": factor_metric_blockers,
        },
        "inherited_data_blockers": inherited_data_blockers,
        "inherited_provider_blockers": inherited_provider_blockers,
        "factor_metric_blockers": factor_metric_blockers,
        "metrics": {
            "factor_count": len(rows),
            "factor_pass_count": factor_pass_count,
            "factor_fail_count": factor_fail_count,
        },
        "gates": {
            "data_lineage_pass": bool(
                data_version and universe_version and manifest_hash and promotion_clean and not inherited_data_blockers
            ),
            "required_evidence_present": bool(rows),
            "overall_status": "pass" if factor_pass_count > 0 else "fail",
        },
        "blocker_reasons": pack_blockers,
        "allowed_next_action": allowed_next_action,
        "data_status_report": _relpath(data_status_path, root) if data_status_path.exists() else None,
        "data_versions": data_versions[:200],
        "symbols": symbols[:500],
        "latest_factor_mining_report": None,
        "factor_mining_run_count": 0,
        "generated_factors_path": None,
        "generated_factor_count": 0,
        "generated_strategy_count": 0,
        "candidate_count": len(current_factor_candidates),
        "selected_factor_count": len(current_factor_candidates),
        "selected_factor_ids": current_factor_candidates,
        "compiled_strategy_count": 0,
        "latest_correlation_report": None,
        "evidence_coverage": {
            "style_exposure": {"status": "not_available_for_factor_level_run"},
            "capacity": {"status": "not_available_for_factor_level_run"},
            "turnover": {"status": "measured"},
            "bar_samples_available": {BAR_SIZE: bool(not bars.empty)},
            "lookahead_guard": "factor[t] paired with forward returns only; no broker or order path invoked",
        },
        "quality_filter": {
            "min_observations": MIN_OBSERVATIONS,
            "min_dates": MIN_DATES,
            "min_abs_ic": MIN_ABS_IC,
            "min_abs_rank_ic": MIN_ABS_RANK_IC,
            "max_avg_turnover": MAX_AVG_TURNOVER,
            "min_walk_forward_pass_rate": MIN_WALK_FORWARD_PASS_RATE,
            "cost_per_turnover": COST_PER_TURNOVER,
        },
        "factor_rows": rows,
        "factor_evidence_rows": rows,
        "factor_count": len(rows),
        "factor_pass_count": factor_pass_count,
        "factor_fail_count": factor_fail_count,
        "current_factor_candidates": current_factor_candidates,
        "required_evidence": [
            "data_version",
            "universe_version",
            "manifest_hash",
            "IC_mean",
            "Rank_IC_mean",
            "IC_decay",
            "turnover",
            "cost_adjusted_spread",
            "walk_forward_stability",
        ],
        "blockers": pack_blockers,
        "promotion_ready": False,
        "paper_queue_status": "locked",
        "live_status": "frozen",
    }


def write_factor_evidence_outputs(
    payload: Mapping[str, Any],
    *,
    latest_root: Path,
    history_root: Path,
    generated_at: str,
) -> tuple[Path, Path]:
    run_id = _run_id(generated_at)
    history_output_root = history_root / run_id
    latest_root.mkdir(parents=True, exist_ok=True)
    history_output_root.mkdir(parents=True, exist_ok=True)
    latest_path = latest_root / "factor_evidence_pack.json"
    history_path = history_output_root / "factor_evidence_pack.json"
    encoded = json.dumps(dict(payload), indent=2, sort_keys=True)
    latest_path.write_text(encoded, encoding="utf-8")
    history_path.write_text(encoded, encoding="utf-8")
    return latest_path, history_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--latest-root", default=str(DEFAULT_LATEST_ROOT))
    parser.add_argument("--history-root", default=str(DEFAULT_HISTORY_ROOT))
    parser.add_argument("--generated-at", default="")
    parser.add_argument("--factors", nargs="*", default=DEFAULT_FACTORS)
    args = parser.parse_args()

    generated_at = args.generated_at or datetime.now(timezone.utc).isoformat()
    payload = build_real_us_equity_factor_evidence_pack(
        repo_root=Path(args.repo_root),
        generated_at=generated_at,
        factor_ids=[str(item) for item in args.factors if str(item)],
    )
    latest, history = write_factor_evidence_outputs(
        payload,
        latest_root=Path(args.latest_root),
        history_root=Path(args.history_root),
        generated_at=generated_at,
    )
    print(str(latest))
    print(str(history))


def _load_source_bars(root: Path, symbols: list[str]) -> tuple[pd.DataFrame, str]:
    if not symbols:
        return pd.DataFrame(), "us_equity_symbol_universe_empty"
    base = root / "data" / "cleaned" / f"vendor={VENDOR}" / f"asset_class={ASSET_CLASS}" / f"bar_size={BAR_SIZE}"
    try:
        import duckdb

        pattern = str(base / "symbol=*" / "date=*.parquet")
        placeholders = ", ".join(["?"] * len(symbols))
        sql = (
            "SELECT timestamp_utc, symbol, open, high, low, close, volume "
            f"FROM read_parquet('{pattern}') "
            f"WHERE symbol IN ({placeholders}) "
            "AND timestamp_utc >= ? AND timestamp_utc <= ? "
            "ORDER BY symbol, timestamp_utc"
        )
        params = [
            *symbols,
            "2020-01-01T00:00:00+00:00",
            "2025-12-31T23:59:59+00:00",
        ]
        frame = duckdb.execute(sql, params).df()
        if not frame.empty:
            return frame, ""
    except Exception:
        pass
    try:
        bars = _load_bars(
            str(root / "data"),
            symbols,
            "2020-01-01",
            "2025-12-31",
            bar_size=BAR_SIZE,
            vendor=VENDOR,
            asset_class=ASSET_CLASS,
        )
        return bars, ""
    except Exception as exc:
        return pd.DataFrame(), f"us_equity_cleaned_bar_load_failed:{type(exc).__name__}"


def _build_factor_row(
    *,
    definition: FactorDefinition,
    factor_frame: pd.DataFrame,
    forward_returns: pd.DataFrame,
    source_bars: pd.DataFrame,
    data_version: str,
    data_versions: list[str],
    universe_version: str,
    manifest_hash: str,
    universe_name: str,
    sample_start: str,
    sample_end: str,
    symbol_count: int,
    calendar: str,
    adjustment_mode: str,
    survivorship_status: str,
    data_blockers: list[str],
    data_lineage_paths: Mapping[str, Any],
    data_lineage_grade: Mapping[str, Any],
    promotion_clean: bool,
    provider_verification_report: Mapping[str, Any],
    inherited_provider_blockers: list[str],
) -> dict[str, Any]:
    merged = factor_frame.merge(
        forward_returns[["timestamp_utc", "date", "symbol", "fwd_return"]],
        on=["timestamp_utc", "date", "symbol"],
        how="inner",
    )
    daily_stats = _daily_factor_stats(merged)
    ic_values = [item["ic"] for item in daily_stats if not math.isnan(item["ic"])]
    rank_ic_values = [item["rank_ic"] for item in daily_stats if not math.isnan(item["rank_ic"])]
    spread_values = [item["long_short_spread"] for item in daily_stats if not math.isnan(item["long_short_spread"])]
    turnover = _average_turnover(merged)
    ic_decay = _ic_decay(factor_frame, source_bars)
    walk_forward = _walk_forward_stability(daily_stats)
    factor_sample_start = str(merged["date"].min()) if not merged.empty else ""
    factor_sample_end = str(merged["date"].max()) if not merged.empty else ""
    expected_grid = max(1, symbol_count * max(1, int(factor_frame["date"].nunique()) if not factor_frame.empty else 0))
    coverage = min(1.0, len(factor_frame.dropna(subset=["factor_value"])) / expected_grid)
    long_short_spread = _mean(spread_values)
    cost_adjusted_spread = long_short_spread - turnover * COST_PER_TURNOVER

    metrics = {
        "IC_mean": _mean(ic_values),
        "IC_std": _std(ic_values),
        "Rank_IC_mean": _mean(rank_ic_values),
        "Rank_IC_std": _std(rank_ic_values),
        "IC_hit_rate": _hit_rate(ic_values),
        "IC_decay": ic_decay,
        "long_short_spread": long_short_spread,
        "cost_adjusted_spread": cost_adjusted_spread,
        "turnover": turnover,
        "coverage": coverage,
        "missing_rate": max(0.0, 1.0 - coverage),
        "n_observations": int(len(merged)),
        "n_dates": int(len(daily_stats)),
    }
    gates = {
        "data_lineage_pass": bool(
            data_version and universe_version and manifest_hash and promotion_clean and not data_blockers
        ),
        "IC_pass": bool(len(ic_values) >= MIN_DATES and abs(metrics["IC_mean"]) >= MIN_ABS_IC),
        "rank_IC_pass": bool(len(rank_ic_values) >= MIN_DATES and abs(metrics["Rank_IC_mean"]) >= MIN_ABS_RANK_IC),
        "turnover_pass": bool(0.0 < turnover <= MAX_AVG_TURNOVER),
        "cost_adjusted_pass": bool(cost_adjusted_spread > 0.0),
        "walk_forward_pass": bool(walk_forward["walk_forward_pass_rate"] >= MIN_WALK_FORWARD_PASS_RATE),
    }
    row_blockers = _gate_blockers(metrics=metrics, gates=gates, data_blockers=data_blockers)
    row = {
        "factor_id": definition.factor_id,
        "bar_size": BAR_SIZE,
        "candidate_rank": 0,
        "selected": False,
        "rank_ic_mean": metrics["Rank_IC_mean"],
        "ic_mean": metrics["IC_mean"],
        "hit_rate": metrics["IC_hit_rate"],
        "turnover": metrics["turnover"],
        "quality_score": 0.0,
        "stability_score": walk_forward["walk_forward_pass_rate"],
        "reject_reason": ";".join(row_blockers),
        "factor_name": definition.factor_id,
        "factor_version": definition.version,
        "factor_family": definition.category,
        "evidence_source": "real_us_equity_factor_run_v1",
        "is_placeholder": False,
        "is_data_dependent": bool(metrics["n_observations"] > 0 and data_version),
        "data_version": data_version,
        "universe_version": universe_version,
        "manifest_hash": manifest_hash,
        "universe_name": universe_name,
        "sample_start": factor_sample_start or sample_start,
        "sample_end": factor_sample_end or sample_end,
        "factor_identity": {
            "factor_name": definition.factor_id,
            "factor_family": definition.category,
            "factor_version": definition.version,
            "input_columns": definition.required_fields,
            "calculation_window": f"{definition.lookback}d",
            "rebalance_frequency": BAR_SIZE,
        },
        "data_lineage": {
            "data_version": data_version,
            "data_versions": data_versions[:200],
            "universe_version": universe_version,
            "manifest_hash": manifest_hash,
            "universe_name": universe_name,
            "sample_start": factor_sample_start or sample_start,
            "sample_end": factor_sample_end or sample_end,
            "symbol_count": symbol_count,
            "calendar": calendar,
            "adjustment_mode": adjustment_mode,
            "survivorship_status": survivorship_status,
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
            "inherited_data_blockers": data_blockers,
        },
        "metrics": metrics,
        "stability": walk_forward,
        "gates": gates,
        "blocker_reasons": row_blockers,
        "allowed_next_action": "research_only",
        "overall_status": "fail",
    }
    verdict = evaluate_us_equity_factor_evidence_row(row)
    row["blocker_reasons"] = verdict["blocker_reasons"]
    row["allowed_next_action"] = verdict["allowed_next_action"]
    row["overall_status"] = verdict["overall_status"]
    row["gates"]["overall_status"] = verdict["overall_status"]
    if verdict["overall_status"] == "pass":
        row["selected"] = True
        row["candidate_rank"] = 1
        row["quality_score"] = 1.0
        row["reject_reason"] = ""
    else:
        row["reject_reason"] = ";".join(verdict["blocker_reasons"])
    return row


def _compute_factor_frame(bars: pd.DataFrame, definition: FactorDefinition) -> pd.DataFrame:
    records: list[pd.DataFrame] = []
    for symbol, group in bars.groupby("symbol", sort=False):
        ordered = group.sort_values("timestamp_utc").reset_index(drop=True)
        close = ordered["close"].astype(float) if "close" in ordered.columns else None
        volume = ordered["volume"].astype(float) if "volume" in ordered.columns else None
        values = _compute_factor_series(definition.factor_id, close, volume)
        frame = ordered[["timestamp_utc", "date", "symbol"]].copy()
        frame["factor_value"] = pd.to_numeric(values, errors="coerce")
        records.append(frame.dropna(subset=["factor_value"]))
    if not records:
        return pd.DataFrame(columns=["timestamp_utc", "date", "symbol", "factor_value"])
    result = pd.concat(records, ignore_index=True)
    return _post_process_cross_section(result, definition)


def _post_process_cross_section(frame: pd.DataFrame, definition: FactorDefinition) -> pd.DataFrame:
    result = frame.copy()
    key = "timestamp_utc"
    if definition.winsorize_pct > 0:
        result["factor_value"] = result.groupby(key, group_keys=False)["factor_value"].transform(
            lambda group: _winsorize(group, definition.winsorize_pct)
        )
    if definition.zscore:
        result["factor_value"] = result.groupby(key, group_keys=False)["factor_value"].transform(_zscore)
    if definition.rank_method == "percentile":
        result["factor_value"] = result.groupby(key, group_keys=False)["factor_value"].transform(
            lambda group: group.rank(pct=True)
        )
    return result.dropna(subset=["factor_value"]).reset_index(drop=True)


def _build_forward_returns(bars: pd.DataFrame, period: int) -> pd.DataFrame:
    working = bars.copy()
    working = working.sort_values(["symbol", "timestamp_utc"]).reset_index(drop=True)
    working["close_fwd"] = working.groupby("symbol")["close"].transform(lambda series: series.shift(-period))
    working["fwd_return"] = working["close_fwd"] / working["close"] - 1.0
    return working.dropna(subset=["fwd_return"])[["timestamp_utc", "date", "symbol", "fwd_return"]]


def _daily_factor_stats(merged: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if merged.empty:
        return rows
    for date_value, group in merged.groupby("date", sort=True):
        clean = group[["factor_value", "fwd_return"]].dropna()
        if len(clean) < MIN_CROSS_SECTION:
            continue
        factor = clean["factor_value"].astype(float)
        returns = clean["fwd_return"].astype(float)
        ic = factor.corr(returns)
        rank_ic = factor.corr(returns, method="spearman")
        spread = _long_short_spread(factor, returns)
        rows.append(
            {
                "date": str(date_value),
                "ic": float(ic) if not pd.isna(ic) else float("nan"),
                "rank_ic": float(rank_ic) if not pd.isna(rank_ic) else float("nan"),
                "long_short_spread": spread,
            }
        )
    return rows


def _long_short_spread(factor: pd.Series, returns: pd.Series) -> float:
    if len(factor) < MIN_CROSS_SECTION:
        return float("nan")
    low_cut = factor.quantile(0.2)
    high_cut = factor.quantile(0.8)
    high = returns[factor >= high_cut]
    low = returns[factor <= low_cut]
    if high.empty or low.empty:
        return float("nan")
    return float(high.mean() - low.mean())


def _average_turnover(merged: pd.DataFrame) -> float:
    if merged.empty:
        return 0.0
    previous: dict[str, float] = {}
    turnover_values: list[float] = []
    for _, group in merged.groupby("date", sort=True):
        clean = group[["symbol", "factor_value"]].dropna()
        if len(clean) < MIN_CROSS_SECTION:
            continue
        low_cut = clean["factor_value"].quantile(0.2)
        high_cut = clean["factor_value"].quantile(0.8)
        long_symbols = sorted(str(item) for item in clean.loc[clean["factor_value"] >= high_cut, "symbol"])
        short_symbols = sorted(str(item) for item in clean.loc[clean["factor_value"] <= low_cut, "symbol"])
        current: dict[str, float] = {}
        if long_symbols:
            long_weight = 0.5 / len(long_symbols)
            current.update({symbol: long_weight for symbol in long_symbols})
        if short_symbols:
            short_weight = -0.5 / len(short_symbols)
            current.update({symbol: short_weight for symbol in short_symbols})
        if previous:
            names = set(previous) | set(current)
            turnover_values.append(sum(abs(current.get(name, 0.0) - previous.get(name, 0.0)) for name in names))
        previous = current
    return _mean(turnover_values)


def _ic_decay(factor_frame: pd.DataFrame, source_bars: pd.DataFrame) -> dict[str, float]:
    if factor_frame.empty:
        return {}
    result: dict[str, float] = {}
    for horizon in (1, 5, 10, 20):
        horizon_forward = _build_forward_returns(source_bars, horizon)
        merged = factor_frame.merge(
            horizon_forward,
            on=["timestamp_utc", "date", "symbol"],
            how="inner",
        )
        stats = _daily_factor_stats(merged)
        values = [item["rank_ic"] for item in stats if not math.isnan(item["rank_ic"])]
        result[f"{horizon}d"] = _mean(values)
    return result


def _walk_forward_stability(daily_stats: list[dict[str, Any]]) -> dict[str, Any]:
    if not daily_stats:
        return {
            "walk_forward_fold_count": 0,
            "walk_forward_pass_count": 0,
            "walk_forward_pass_rate": 0.0,
            "worst_fold_metric": 0.0,
            "regime_breakdown": "not_available",
        }
    folds = [fold for fold in np.array_split(daily_stats, 3) if len(fold) > 0]
    fold_metrics: list[float] = []
    pass_count = 0
    for fold in folds:
        rank_values = [
            float(item["rank_ic"])
            for item in fold.tolist()
            if not math.isnan(float(item["rank_ic"]))
        ]
        spread_values = [
            float(item["long_short_spread"])
            for item in fold.tolist()
            if not math.isnan(float(item["long_short_spread"]))
        ]
        rank_mean = _mean(rank_values)
        spread_mean = _mean(spread_values)
        fold_metrics.append(rank_mean)
        if abs(rank_mean) >= MIN_ABS_RANK_IC and spread_mean > 0.0:
            pass_count += 1
    fold_count = len(folds)
    return {
        "walk_forward_fold_count": fold_count,
        "walk_forward_pass_count": pass_count,
        "walk_forward_pass_rate": pass_count / fold_count if fold_count else 0.0,
        "worst_fold_metric": min(fold_metrics, key=lambda value: abs(value)) if fold_metrics else 0.0,
        "regime_breakdown": "not_available",
    }


def _gate_blockers(*, metrics: Mapping[str, Any], gates: Mapping[str, Any], data_blockers: list[str]) -> list[str]:
    blockers = list(data_blockers)
    if int(metrics.get("n_observations", 0) or 0) < MIN_OBSERVATIONS:
        blockers.append("factor_observation_count_below_threshold")
    if int(metrics.get("n_dates", 0) or 0) < MIN_DATES:
        blockers.append("factor_date_count_below_threshold")
    for gate_name, blocker in (
        ("data_lineage_pass", "data_lineage_gate_failed"),
        ("IC_pass", "IC_gate_failed"),
        ("rank_IC_pass", "rank_IC_gate_failed"),
        ("turnover_pass", "turnover_gate_failed"),
        ("cost_adjusted_pass", "cost_adjusted_spread_gate_failed"),
        ("walk_forward_pass", "walk_forward_stability_gate_failed"),
    ):
        if gates.get(gate_name) is not True:
            blockers.append(blocker)
    return _dedupe(blockers)


def _select_symbols(root: Path, data_status: Mapping[str, Any]) -> list[str]:
    symbols = [str(item).upper() for item in data_status.get("symbols", []) if str(item)]
    if not symbols:
        base = root / "data" / "cleaned" / f"vendor={VENDOR}" / f"asset_class={ASSET_CLASS}" / f"bar_size={BAR_SIZE}"
        symbols = [path.name.split("=", 1)[1].upper() for path in sorted(base.glob("symbol=*"))]
    result = []
    for symbol in symbols:
        path = (
            root
            / "data"
            / "cleaned"
            / f"vendor={VENDOR}"
            / f"asset_class={ASSET_CLASS}"
            / f"bar_size={BAR_SIZE}"
            / f"symbol={symbol}"
        )
        if path.exists():
            result.append(symbol)
    return _dedupe(result)


def _one_day_data_versions(data_status: Mapping[str, Any]) -> list[str]:
    return [
        str(item)
        for item in data_status.get("data_versions", [])
        if str(item) and f"-{BAR_SIZE}-" in str(item)
    ]


def _inherited_data_blockers(
    data_status: Mapping[str, Any],
    universe_snapshot_manifest: Mapping[str, Any],
    corporate_action_status_report: Mapping[str, Any],
    survivorship_audit_report: Mapping[str, Any],
    provider_verification_report: Mapping[str, Any],
    *,
    promotion_clean: bool,
) -> list[str]:
    blockers = []
    blockers.extend(_list_of_strings(data_status.get("blockers")))
    blockers.extend(_list_of_strings(universe_snapshot_manifest.get("blockers")))
    blockers.extend(_list_of_strings(corporate_action_status_report.get("blockers")))
    blockers.extend(_list_of_strings(survivorship_audit_report.get("blockers")))
    blockers.extend(_provider_blockers(provider_verification_report))
    required = [
        "point_in_time_universe_not_confirmed",
        "corporate_action_event_source_missing",
        "survivorship_status_not_clean",
        "delisting_coverage_missing",
        "universe_snapshot_manifest_derived_only",
    ]
    for blocker in required:
        if blocker in blockers:
            continue
        if blocker == "point_in_time_universe_not_confirmed" and not bool(
            universe_snapshot_manifest.get("point_in_time_confirmed", False)
        ):
            blockers.append(blocker)
        if blocker == "corporate_action_event_source_missing" and not bool(
            corporate_action_status_report.get("corporate_action_event_source_available", False)
        ):
            blockers.append(blocker)
        if blocker == "survivorship_status_not_clean" and str(
            survivorship_audit_report.get("survivorship_status", "")
        ) != "clean":
            blockers.append(blocker)
        if blocker == "delisting_coverage_missing" and not bool(
            survivorship_audit_report.get("delisted_symbols_included", False)
        ):
            blockers.append(blocker)
        if blocker == "universe_snapshot_manifest_derived_only" and str(
            universe_snapshot_manifest.get("source_type", "")
        ) == "derived_from_bars":
            blockers.append(blocker)
    if not promotion_clean:
        blockers.append("data_lineage_not_promotion_clean")
    return _dedupe(blockers)


def _provider_blockers(provider_verification_report: Mapping[str, Any]) -> list[str]:
    blockers = _list_of_strings(provider_verification_report.get("blockers"))
    if provider_verification_report and not bool(provider_verification_report.get("promotion_clean", False)):
        blockers.append("provider_not_verified_for_promotion")
    if provider_verification_report and not bool(provider_verification_report.get("identifier_mapping_available", False)):
        blockers.append("identifier_mapping_missing")
    if not provider_verification_report:
        blockers.append("provider_verification_report_missing")
    return _dedupe(blockers)


def _daily_adjustment_mode(manifest_payloads: list[Mapping[str, Any]]) -> str:
    policies = {
        str(
            item.get("adjustment_policy")
            or item.get("corporate_action_adjustment")
            or item.get("adjustment")
            or "unknown"
        )
        for item in manifest_payloads
        if str(item.get("interval", "")) == BAR_SIZE
    }
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


def _combined_data_version(data_versions: list[str]) -> str:
    if not data_versions:
        return ""
    digest = hashlib.sha256(
        json.dumps(sorted(data_versions), separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]
    return f"us_equity_1d_data_versions_sha256:{digest}"


def _manifest_payloads(root: Path, data_versions: list[str]) -> list[dict[str, Any]]:
    payloads = []
    for data_version in data_versions:
        path = root / "data" / "manifests" / f"{data_version}.json"
        payload = _read_json(path)
        if payload:
            payloads.append(payload)
    return payloads


def _manifest_hash(payloads: list[Mapping[str, Any]]) -> str:
    if not payloads:
        return ""
    encoded = json.dumps(payloads, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _winsorize(series: pd.Series, pct: float) -> pd.Series:
    if series.empty or pct <= 0:
        return series
    lower = series.quantile(pct)
    upper = series.quantile(1.0 - pct)
    return series.clip(lower, upper)


def _zscore(series: pd.Series) -> pd.Series:
    std = series.std(ddof=0)
    if std == 0 or pd.isna(std):
        return series * 0.0
    return (series - series.mean()) / std


def _mean(values: list[float]) -> float:
    clean = [float(value) for value in values if not math.isnan(float(value))]
    return float(np.mean(clean)) if clean else 0.0


def _std(values: list[float]) -> float:
    clean = [float(value) for value in values if not math.isnan(float(value))]
    return float(np.std(clean, ddof=1)) if len(clean) > 1 else 0.0


def _hit_rate(values: list[float]) -> float:
    clean = [float(value) for value in values if not math.isnan(float(value))]
    return float(np.mean([value > 0.0 for value in clean])) if clean else 0.0


def _run_id(generated_at: str) -> str:
    return (
        generated_at.replace("+00:00", "Z")
        .replace(":", "")
        .replace("-", "")
        .replace(".", "")
    )


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _list_of_strings(value: object) -> list[str]:
    return [str(item) for item in value if str(item)] if isinstance(value, list) else []


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


def _relpath(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


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
