"""Diagnostics for BTC compression-expansion event-ledger candidate evidence.

The helpers here are research-only. They read persisted artifacts, produce
attribution diagnostics, and never touch paper/live/broker execution paths.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd

from backend.app.services.data_management import (
    DEFAULT_EXCHANGE,
    MarketDataRepository,
    from_milliseconds,
    interval_to_milliseconds,
)
from quant_us.research.btc_alpha_hardening import classify_btc_regimes
from quant_us.research.btc_canonical import git_commit_hash, stable_hash, write_json
from quant_us.research.btc_compression_expansion_validation import (
    BTC_COMPRESSION_EXPANSION_VALIDATION_RUN_ID,
    BTC_COMPRESSION_EXPANSION_VALIDATION_ROOT,
    SOURCE_HYPOTHESIS_RUN_DIR,
)
from quant_us.research.btc_eventpf_wf import load_btc_1h_frame


DEFAULT_VALIDATION_RUN_DIR = BTC_COMPRESSION_EXPANSION_VALIDATION_ROOT / BTC_COMPRESSION_EXPANSION_VALIDATION_RUN_ID
BTC_INTERVALS = ("5m", "15m", "1h", "4h", "1d")


def analyze_failure_modes(*, run_dir: Path = DEFAULT_VALIDATION_RUN_DIR) -> dict[str, Any]:
    report = _read_json(run_dir / "canonical_backtest_report.json")
    validation = _read_json(run_dir / "candidate_validation_result.json")
    safety = _read_json(run_dir / "paper_live_safety_status.json")
    event_report = _read_json(run_dir / "event_ledger_attribution_report.json")
    table = _read_event_table(run_dir)
    trades = pd.read_csv(run_dir / "trade_ledger.csv")
    active = table.loc[table["active_exposure"].astype(bool)].copy()
    inactive = table.loc[~table["active_exposure"].astype(bool)].copy()
    failed_folds = [str(row["fold_id"]) for row in event_report.get("failed_fold_autopsy", [])]
    payload = {
        "schema_version": "btc_compression_expansion_failure_mode_report_v1",
        "run_id": report["run_id"],
        "strategy_id": report["strategy_id"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "code_commit": git_commit_hash(),
        "candidate_metrics": {
            "ordinary_pf": report["metrics"]["profit_factor"],
            "event_pf": report["metrics"]["event_profit_factor"],
            "sharpe": report["metrics"]["sharpe"],
            "max_drawdown": report["metrics"]["max_drawdown"],
            "annual_turnover": report["metrics"]["annual_turnover"],
            "walk_forward_pass_rate": report["metrics"]["walk_forward_pass_rate"],
            "regime_pass_rate": report["metrics"]["regime_pass_rate"],
        },
        "gate_status": validation["status"],
        "gate_fail_reasons": validation["gate_fail_reasons"],
        "paper_queue": safety["paper_queue"],
        "live": safety["live"],
        "hypothesis_vs_event_ledger": {
            "hypothesis_layer_decision": _hypothesis_decision(),
            "event_ledger_candidate_status": validation["status"],
            "ordinary_pf_passes": float(report["metrics"]["profit_factor"]) >= 1.15,
            "event_pf_passes": float(report["metrics"]["event_profit_factor"]) >= 1.15,
            "primary_gap": "hypothesis event-return labels do not survive full event-ledger execution evidence",
        },
        "full_vs_active_exposure": {
            "full_ledger": _event_stats(table),
            "active_exposure": _event_stats(active),
            "inactive_or_unmapped": _event_stats(inactive),
            "active_event_pf_gate_passes": _event_pf(active) >= 1.15,
            "full_event_pf_gate_passes": float(report["metrics"]["event_profit_factor"]) >= 1.15,
            "diagnostic_note": (
                "Active exposure event_PF is diagnostic only. Promotion uses full ledger event_PF from "
                "canonical event-ledger evidence, including all persisted equity events."
            ),
        },
        "failed_fold_autopsy": _failed_fold_autopsy(table, failed_folds),
        "regime_drag": _regime_drag(table, event_report),
        "entry_exit_timing": _entry_exit_timing(trades),
        "repairability_assessment": _repairability_assessment(table, failed_folds, report),
        "decision": {
            "compression_expansion_status": "needs_event_ledger_surgery_before_any_paper_review",
            "paper_review_pending_created": False,
            "live_changed": False,
            "next_research_route_if_unfixed": "liquidation_shock_recovery_continuation_hypothesis_lab",
        },
    }
    write_json(run_dir / "compression_expansion_failure_mode_report.json", payload)
    return payload


def audit_fold_regime_contracts(
    *,
    run_dir: Path = DEFAULT_VALIDATION_RUN_DIR,
    hypothesis_run_dir: Path = SOURCE_HYPOTHESIS_RUN_DIR,
) -> dict[str, Any]:
    event_table = _read_event_table(run_dir)
    hypothesis_table = pd.read_csv(hypothesis_run_dir / "event_table.csv")
    walk_forward = _read_json(run_dir / "walk_forward_report.json")
    regime = _read_json(run_dir / "regime_report.json")
    validation = _read_json(run_dir / "candidate_validation_result.json")
    label_trimmed_rows = int(len(event_table) - len(hypothesis_table))
    payload = {
        "schema_version": "btc_fold_regime_contract_audit_v1",
        "run_id": run_dir.name,
        "strategy_id": validation["strategy_id"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "fold_contract": {
            "gate_source": "walk_forward_report.json",
            "method": walk_forward.get("method"),
            "fold_count": walk_forward.get("fold_count"),
            "folds": [
                {
                    "fold_id": str(row.get("fold")),
                    "validation_start": row.get("validation_start"),
                    "validation_end": row.get("validation_end"),
                    "validation_rows": row.get("validation_rows"),
                    "passed": bool(row.get("passed", False)),
                }
                for row in walk_forward.get("windows", [])
            ],
            "event_table_fold_counts": _value_counts(event_table["fold_id"]),
            "hypothesis_label_fold_counts": _value_counts(hypothesis_table["fold_id"]),
            "label_trimmed_rows_due_to_forward_horizon": label_trimmed_rows,
            "status": "pass" if label_trimmed_rows >= 0 else "fail",
        },
        "regime_contract": {
            "classifier": "quant_us.research.btc_alpha_hardening.classify_btc_regimes",
            "gate_source": "entry_regime_from_ledger_segments",
            "diagnostic_source": "bar_level_event_ledger_attribution",
            "gate_eligible_regimes": [row["regime"] for row in regime.get("regimes", [])],
            "diagnostic_regimes": sorted(set(event_table["regime"].astype(str))),
            "dragging_regimes": regime.get("dragging_regimes", []),
            "pass_rate": regime.get("pass_rate"),
            "status": "fail" if float(regime.get("pass_rate", 0.0)) < 0.75 else "pass",
        },
        "promotion_contract": {
            "event_pf_required": 1.15,
            "walk_forward_pass_required": 0.80,
            "regime_pass_required": 0.75,
            "paper_review_pending_requires_all_three": True,
            "paper_ready_allowed": False,
            "live_ready_allowed": False,
            "live_enabled_allowed": False,
        },
        "cleanup_required": [
            "Keep hypothesis fold labels as label-generation diagnostics; gate folds come from walk_forward_report.json.",
            "Record forward-horizon label trimming explicitly when comparing hypothesis and ledger event tables.",
            "Use entry-regime trade report for regime gate and bar-level regimes for failure diagnostics.",
        ],
    }
    write_json(run_dir / "fold_regime_contract_audit.json", payload)
    return payload


def build_data_fold_regime_status_report(
    *,
    run_dir: Path = DEFAULT_VALIDATION_RUN_DIR,
    db_path: str = "data/market_data.sqlite",
    manifest_root: Path = Path("data/manifests"),
) -> dict[str, Any]:
    repository = MarketDataRepository(db_path)
    intervals = [_interval_status(repository, interval, manifest_root) for interval in BTC_INTERVALS]
    frame = load_btc_1h_frame()
    regimes = classify_btc_regimes(frame)
    fold_audit = _read_optional(run_dir / "fold_regime_contract_audit.json")
    payload = {
        "schema_version": "btc_data_fold_regime_status_report_v1",
        "run_id": run_dir.name,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "code_commit": git_commit_hash(),
        "sqlite": {
            "db_path": db_path,
            "exchange": DEFAULT_EXCHANGE,
            "symbol": "BTCUSDT",
            "status": "pass" if all(row["status"] == "pass" for row in intervals) else "fail",
        },
        "intervals": intervals,
        "manifest_lineage": {
            "status": "pass" if all(row["manifest_status"] == "pass" for row in intervals) else "fail",
            "latest_manifests": [
                {
                    "interval": row["interval"],
                    "manifest_path": row["latest_manifest_path"],
                    "data_version": row["data_version"],
                    "coverage_pct": row["manifest_coverage_pct"],
                    "quality_score": row["manifest_quality_score"],
                }
                for row in intervals
            ],
        },
        "fold_status": fold_audit.get("fold_contract", {}),
        "regime_status": {
            "classifier": "classify_btc_regimes",
            "bar_counts": _value_counts(regimes.astype(str)),
            "gate_pass_rate": fold_audit.get("regime_contract", {}).get("pass_rate"),
            "dragging_regimes": fold_audit.get("regime_contract", {}).get("dragging_regimes", []),
            "status": fold_audit.get("regime_contract", {}).get("status", "unknown"),
        },
    }
    write_json(run_dir / "btc_data_fold_regime_status_report.json", payload)
    return payload


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_optional(path: Path) -> dict[str, Any]:
    return _read_json(path) if path.exists() else {}


def _read_event_table(run_dir: Path) -> pd.DataFrame:
    table = pd.read_csv(run_dir / "event_ledger_attribution_table.csv")
    table["timestamp"] = pd.to_datetime(table["timestamp"], utc=True)
    return table


def _event_pf(frame: pd.DataFrame) -> float:
    if frame.empty:
        return 0.0
    returns = pd.to_numeric(frame["event_return"], errors="coerce").fillna(0.0)
    positive = float(returns[returns > 0.0].sum())
    negative = abs(float(returns[returns < 0.0].sum()))
    if negative == 0.0:
        return 999.0 if positive > 0.0 else 0.0
    return positive / negative


def _event_stats(frame: pd.DataFrame) -> dict[str, Any]:
    if frame.empty:
        return {
            "event_count": 0,
            "event_pf": 0.0,
            "positive_sum": 0.0,
            "negative_sum": 0.0,
            "positive_event_rate": 0.0,
            "mean_return": 0.0,
            "median_return": 0.0,
            "downside_tail_5pct": 0.0,
        }
    returns = pd.to_numeric(frame["event_return"], errors="coerce").fillna(0.0)
    positive = returns[returns > 0.0]
    negative = returns[returns < 0.0]
    return {
        "event_count": int(len(frame)),
        "event_pf": round(_event_pf(frame), 6),
        "positive_sum": round(float(positive.sum()), 10),
        "negative_sum": round(float(negative.sum()), 10),
        "positive_event_rate": round(float((returns > 0.0).mean()), 6),
        "mean_return": round(float(returns.mean()), 10),
        "median_return": round(float(returns.median()), 10),
        "downside_tail_5pct": round(float(returns.quantile(0.05)), 10),
    }


def _group_stats(frame: pd.DataFrame, group_cols: Sequence[str], *, limit: int | None = None) -> list[dict[str, Any]]:
    if frame.empty:
        return []
    rows: list[dict[str, Any]] = []
    for keys, subset in frame.groupby(list(group_cols), dropna=False):
        if not isinstance(keys, tuple):
            keys = (keys,)
        row = _event_stats(subset)
        for column, key in zip(group_cols, keys):
            row[column] = str(key)
        rows.append(row)
    rows.sort(key=lambda item: (float(item["event_pf"]), -int(item["event_count"])))
    return rows if limit is None else rows[:limit]


def _failed_fold_autopsy(table: pd.DataFrame, failed_folds: Sequence[str]) -> list[dict[str, Any]]:
    rows = []
    for fold_id in failed_folds:
        fold = table.loc[table["fold_id"].astype(str) == str(fold_id)]
        active = fold.loc[fold["active_exposure"].astype(bool)]
        rows.append(
            {
                "fold_id": str(fold_id),
                "full_fold_distribution": _event_stats(fold),
                "active_exposure_distribution": _event_stats(active),
                "inactive_or_unmapped_distribution": _event_stats(fold.loc[~fold["active_exposure"].astype(bool)]),
                "worst_regimes": _group_stats(active, ["regime"], limit=6),
                "worst_age_buckets": _group_stats(active, ["segment_age_bucket"], limit=6),
                "worst_trend_buckets": _group_stats(active, ["trend_strength_bucket"], limit=6),
                "worst_regime_age_pairs": _group_stats(active, ["regime", "segment_age_bucket"], limit=8),
                "largest_negative_events": active.sort_values("event_return", ascending=True)
                .head(12)[
                    [
                        "timestamp",
                        "event_return",
                        "signed_event_pnl",
                        "regime",
                        "segment_id",
                        "segment_age_bucket",
                        "trend_strength_bucket",
                    ]
                ]
                .to_dict(orient="records"),
            }
        )
    return rows


def _regime_drag(table: pd.DataFrame, event_report: Mapping[str, Any]) -> dict[str, Any]:
    active = table.loc[table["active_exposure"].astype(bool)]
    dragging = list(event_report.get("trade_segment_attribution", {}).get("regime_report", {}).get("dragging_regimes", []))
    return {
        "gate_dragging_regimes": dragging,
        "active_bar_level_regime_stats": _group_stats(active, ["regime"]),
        "worst_regime_fold_pairs": _group_stats(active, ["fold_id", "regime"], limit=12),
        "contract_note": "Regime gate is entry-regime trade level; this section is bar-level diagnostic attribution.",
    }


def _entry_exit_timing(trades: pd.DataFrame) -> dict[str, Any]:
    if trades.empty:
        return {"trade_count": 0, "by_entry_hour": [], "by_exit_hour": [], "by_holding_bars": []}
    local = trades.copy()
    local["entry_time_ts"] = pd.to_datetime(local["entry_time"], utc=True)
    local["exit_time_ts"] = pd.to_datetime(local["exit_time"], utc=True)
    local["entry_hour_utc"] = local["entry_time_ts"].dt.hour
    local["exit_hour_utc"] = local["exit_time_ts"].dt.hour
    return {
        "trade_count": int(len(local)),
        "by_entry_hour": _trade_group_stats(local, "entry_hour_utc"),
        "by_exit_hour": _trade_group_stats(local, "exit_hour_utc"),
        "by_holding_bars": _trade_group_stats(local, "holding_bars"),
        "timing_note": "Entry/exit hour is diagnostic only; no time-of-day rule is accepted without cross-fold evidence.",
    }


def _trade_group_stats(frame: pd.DataFrame, column: str) -> list[dict[str, Any]]:
    rows = []
    for key, subset in frame.groupby(column, dropna=False):
        pnl = pd.to_numeric(subset["net_pnl"], errors="coerce").fillna(0.0)
        wins = pnl[pnl > 0.0]
        losses = -pnl[pnl < 0.0]
        pf = float(wins.sum() / losses.sum()) if float(losses.sum()) > 0.0 else (999.0 if float(wins.sum()) > 0.0 else 0.0)
        rows.append(
            {
                column: str(key),
                "trade_count": int(len(subset)),
                "net_pnl": round(float(pnl.sum()), 6),
                "profit_factor": round(pf, 6),
                "win_rate": round(float((pnl > 0.0).mean()), 6),
            }
        )
    return sorted(rows, key=lambda row: (float(row["profit_factor"]), -int(row["trade_count"])))


def _repairability_assessment(table: pd.DataFrame, failed_folds: Sequence[str], report: Mapping[str, Any]) -> dict[str, Any]:
    failed_rows = _failed_fold_autopsy(table, failed_folds)
    worst_sets = []
    for row in failed_rows:
        meaningful = {
            item["regime"]
            for item in row["worst_regimes"]
            if int(item.get("event_count", 0)) >= 10 and float(item.get("event_pf", 999.0)) < 1.05
        }
        worst_sets.append(meaningful)
    shared_worst = sorted(set.intersection(*worst_sets)) if len(worst_sets) >= 2 and all(worst_sets) else []
    event_pf = float(report["metrics"]["event_profit_factor"])
    wf = float(report["metrics"]["walk_forward_pass_rate"])
    regime_pass = float(report["metrics"]["regime_pass_rate"])
    if event_pf < 1.15 and wf < 0.80 and regime_pass < 0.75 and not shared_worst:
        conclusion = "not_yet_fixable_without_more_evidence"
    elif event_pf < 1.15 or wf < 0.80 or regime_pass < 0.75:
        conclusion = "potentially_fixable_but_requires_rule_ablation"
    else:
        conclusion = "gate_ready"
    return {
        "conclusion": conclusion,
        "shared_worst_regimes_across_failed_folds": shared_worst,
        "fold_3_4_have_single_shared_failure_pattern": bool(shared_worst),
        "do_not_parameter_tune_to_pass": True,
        "recommended_next_step": (
            "Run rule ablations only if they target shared failed-fold/regime evidence; otherwise archive the skeleton "
            "and move to liquidation-shock recovery."
        ),
    }


def _hypothesis_decision() -> str:
    path = SOURCE_HYPOTHESIS_RUN_DIR / "compression_expansion_hypothesis_decision.json"
    if not path.exists():
        return "unknown"
    return str(_read_json(path).get("decision", "unknown"))


def _value_counts(series: pd.Series) -> dict[str, int]:
    return {str(key): int(value) for key, value in series.astype(str).value_counts().sort_index().items()}


def _interval_status(repository: MarketDataRepository, interval: str, manifest_root: Path) -> dict[str, Any]:
    bounds = repository.interval_bounds(DEFAULT_EXCHANGE, "BTCUSDT", interval)
    if bounds is None:
        return {
            "interval": interval,
            "status": "missing",
            "row_count": 0,
            "expected_rows": 0,
            "missing_rows": 0,
            "latest_manifest_path": "",
            "manifest_status": "missing",
        }
    step = interval_to_milliseconds(interval)
    expected_rows = ((bounds["end_ms"] - bounds["start_ms"]) // step) + 1
    latest_manifest = _latest_manifest(manifest_root, interval)
    manifest = _read_json(latest_manifest) if latest_manifest is not None else {}
    manifest_matches = (
        bool(manifest)
        and int(manifest.get("row_count", -1)) == int(bounds["row_count"])
        and str(manifest.get("end")) == from_milliseconds(bounds["end_ms"]).isoformat()
        and float(manifest.get("coverage_pct", 0.0)) >= 100.0
    )
    return {
        "interval": interval,
        "status": "pass" if bounds["row_count"] == expected_rows else "fail",
        "start": from_milliseconds(bounds["start_ms"]).isoformat(),
        "end": from_milliseconds(bounds["end_ms"]).isoformat(),
        "row_count": int(bounds["row_count"]),
        "expected_rows": int(expected_rows),
        "missing_rows": int(expected_rows - bounds["row_count"]),
        "latest_manifest_path": str(latest_manifest or ""),
        "manifest_status": "pass" if manifest_matches else "fail",
        "data_version": manifest.get("data_version", ""),
        "manifest_coverage_pct": manifest.get("coverage_pct", 0.0),
        "manifest_quality_score": manifest.get("quality_score", 0.0),
    }


def _latest_manifest(root: Path, interval: str) -> Path | None:
    files = list(root.glob(f"qs-sqlite-BTCUSDT-{interval}-*.json"))
    return max(files, key=lambda path: path.stat().st_mtime) if files else None


def artifact_hashes(run_dir: Path, files: Sequence[str]) -> dict[str, str]:
    rows = {}
    for name in files:
        path = run_dir / name
        if path.exists():
            rows[name] = stable_hash({"path": str(path), "content": path.read_text(encoding="utf-8")})
    return rows
