#!/usr/bin/env python3
"""Build a research-only BTC intraday event-definition repair report.

The report is a bounded diagnostic over the already generated event-ledger
trade attribution. It identifies a repair candidate for a later full
event-ledger retest; it is not promotion evidence and cannot unlock candidate,
paper, or live states.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import pandas as pd


DEFAULT_OUTPUT_ROOT = Path("artifacts/btc_candidate_gate/latest")
SOURCE_EVENT_LEDGER_REPORT = Path(
    "artifacts/btc_candidate_gate/latest/btc_intraday_short_cycle_event_ledger_report.json"
)
SOURCE_EVENT_LEDGER_RUN_DIR = Path(
    "artifacts/btc_intraday_event_ledger/20260620T000000Z_pullback_reclaim_intraday_eventledger"
)
MIN_REPAIR_TRADE_COUNT = 50
MIN_REPAIR_PROFIT_FACTOR = 1.15
MIN_REPAIR_MEDIAN_NET_PNL = 0.0
MIN_REPAIR_REGIME_PASS_RATE = 0.75
MAX_TOP5_POSITIVE_SHARE = 0.50
MAX_TOP_DECILE_POSITIVE_SHARE = 0.75


def build_btc_intraday_short_cycle_event_definition_repair_report(
    *,
    repo_root: Path | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    source_report = _read_json(root / SOURCE_EVENT_LEDGER_REPORT)
    attribution_path = root / SOURCE_EVENT_LEDGER_RUN_DIR / "trade_attribution.csv"
    attribution = pd.read_csv(attribution_path) if attribution_path.exists() else pd.DataFrame()
    variants = [_evaluate_variant(spec, attribution) for spec in _repair_specs()]
    best = _best_variant(variants)
    repair_found = bool(best and best.get("repair_screen_pass"))
    return {
        "schema_version": "btc_intraday_short_cycle_event_definition_repair_report_v1",
        "generated_at": generated_at or _utc_z_now(),
        "commit": _git(["rev-parse", "--short", "HEAD"], cwd=root),
        "branch": _git(["branch", "--show-current"], cwd=root),
        "asset": "btc",
        "symbol": "BTCUSDT",
        "scope": "research_only_event_definition_repair_no_candidate_no_paper_no_live",
        "status": "repair_candidate_identified_retest_required" if repair_found else "repair_scan_no_candidate",
        "decision": (
            "run_full_event_ledger_retest_for_repaired_definition"
            if repair_found
            else "return_to_event_definition"
        ),
        "next_required_action": (
            f"run_research_only_event_ledger_retest_for_{best['variant_id']}"
            if repair_found and best
            else "design_new_intraday_event_definition"
        ),
        "repair_scan_completed": attribution_path.exists() and not attribution.empty,
        "repair_screen_is_promotion_evidence": False,
        "full_event_ledger_retest_required": True,
        "candidate_generation_allowed": False,
        "strategy_skeleton_generation_allowed": False,
        "promotion_allowed": False,
        "paper_review_pending_allowed": False,
        "paper_or_live_unlock_allowed": False,
        "true_scalping_allowed": False,
        "source_event_ledger_report": _maybe_path(root, SOURCE_EVENT_LEDGER_REPORT),
        "source_trade_attribution": _maybe_path(root, SOURCE_EVENT_LEDGER_RUN_DIR / "trade_attribution.csv"),
        "source_trade_ledger": _maybe_path(root, SOURCE_EVENT_LEDGER_RUN_DIR / "trade_ledger.csv"),
        "base_failure_context": {
            "status": str(source_report.get("status", "missing") or "missing"),
            "decision": str(source_report.get("decision", "")),
            "failed_metrics": _list_of_strings(source_report.get("failed_metrics")),
            "blockers": _list_of_strings(source_report.get("blockers")),
            "regime_pass_rate": _float_or_none(_mapping(source_report.get("metrics")).get("regime_pass_rate")),
            "tail_dependency_status": str(_mapping(source_report.get("tail_dependency")).get("status", "")),
        },
        "repair_thresholds": {
            "min_trade_count": MIN_REPAIR_TRADE_COUNT,
            "min_profit_factor": MIN_REPAIR_PROFIT_FACTOR,
            "min_median_net_pnl": MIN_REPAIR_MEDIAN_NET_PNL,
            "min_regime_pass_rate": MIN_REPAIR_REGIME_PASS_RATE,
            "max_top5_positive_share": MAX_TOP5_POSITIVE_SHARE,
            "max_top_decile_positive_share": MAX_TOP_DECILE_POSITIVE_SHARE,
        },
        "variant_results": variants,
        "best_repair_variant": best,
        "guardrails": {
            "research_only": True,
            "broker_calls_allowed": False,
            "private_endpoints_allowed": False,
            "order_endpoints_allowed": False,
            "paper_or_live_unlock_allowed": False,
            "candidate_generation_allowed": False,
            "strategy_skeleton_generation_allowed": False,
            "true_scalping_allowed": False,
            "sub_minute_or_tick_scalping_allowed": False,
            "repair_screen_is_promotion_evidence": False,
            "full_event_ledger_retest_required": True,
        },
        "blockers": _blockers(
            source_report=source_report,
            attribution_ready=attribution_path.exists() and not attribution.empty,
            repair_found=repair_found,
        ),
    }


def write_btc_intraday_short_cycle_event_definition_repair_report(
    payload: Mapping[str, Any],
    output_root: Path,
) -> str:
    output_root.mkdir(parents=True, exist_ok=True)
    output = output_root / "btc_intraday_short_cycle_event_definition_repair_report.json"
    output.write_text(json.dumps(dict(payload), indent=2, sort_keys=True), encoding="utf-8")
    return str(output)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--generated-at", default="")
    args = parser.parse_args()
    payload = build_btc_intraday_short_cycle_event_definition_repair_report(
        repo_root=Path(args.repo_root),
        generated_at=args.generated_at or None,
    )
    print(write_btc_intraday_short_cycle_event_definition_repair_report(payload, Path(args.output_root)))


def _repair_specs() -> list[dict[str, Any]]:
    return [
        {
            "variant_id": "high_vol_non_expansion_repair_v1",
            "description": "Require high realized-volatility state and exclude expansion/trending_down entry regimes.",
            "volatility_states": ["high_vol"],
            "allowed_regimes": ["high_vol_trend", "mean_reverting_chop", "trending_up"],
        },
        {
            "variant_id": "high_vol_all_regimes_repair_v1",
            "description": "Require high realized-volatility state only.",
            "volatility_states": ["high_vol"],
            "allowed_regimes": [],
        },
        {
            "variant_id": "trending_up_only_repair_v1",
            "description": "Keep only trending_up regime entries.",
            "volatility_states": [],
            "allowed_regimes": ["trending_up"],
        },
        {
            "variant_id": "high_vol_trending_up_only_repair_v1",
            "description": "Require high realized-volatility state and trending_up entries.",
            "volatility_states": ["high_vol"],
            "allowed_regimes": ["trending_up"],
        },
        {
            "variant_id": "remove_expansion_down_repair_v1",
            "description": "Exclude expansion and trending_down regimes without volatility filtering.",
            "volatility_states": [],
            "allowed_regimes": ["high_vol_trend", "mean_reverting_chop", "trending_up"],
        },
    ]


def _evaluate_variant(spec: Mapping[str, Any], attribution: pd.DataFrame) -> dict[str, Any]:
    filtered = _apply_filters(spec, attribution)
    metrics = _metrics(filtered)
    blockers = _repair_blockers(metrics)
    return {
        "variant_id": str(spec["variant_id"]),
        "description": str(spec["description"]),
        "filters": {
            "volatility_states": _list_of_strings(spec.get("volatility_states")),
            "allowed_regimes": _list_of_strings(spec.get("allowed_regimes")),
        },
        "trade_count": metrics["trade_count"],
        "net_pnl": metrics["net_pnl"],
        "mean_net_pnl": metrics["mean_net_pnl"],
        "median_net_pnl": metrics["median_net_pnl"],
        "profit_factor": metrics["profit_factor"],
        "hit_rate": metrics["hit_rate"],
        "regime_pass_rate": metrics["regime_pass_rate"],
        "tail_dependency_pass": metrics["tail_dependency_pass"],
        "top5_positive_share": metrics["top5_positive_share"],
        "top_decile_positive_share": metrics["top_decile_positive_share"],
        "repair_screen_pass": not blockers,
        "repair_screen_is_promotion_evidence": False,
        "full_event_ledger_retest_required": True,
        "regime_breakdown": metrics["regime_breakdown"],
        "blockers": blockers,
    }


def _apply_filters(spec: Mapping[str, Any], attribution: pd.DataFrame) -> pd.DataFrame:
    if attribution.empty:
        return attribution
    frame = attribution.copy()
    volatility_states = set(_list_of_strings(spec.get("volatility_states")))
    if volatility_states:
        frame = frame[frame["volatility_state_at_entry"].astype(str).isin(volatility_states)]
    allowed_regimes = set(_list_of_strings(spec.get("allowed_regimes")))
    if allowed_regimes:
        frame = frame[frame["entry_regime"].astype(str).isin(allowed_regimes)]
    return frame


def _metrics(frame: pd.DataFrame) -> dict[str, Any]:
    if frame.empty:
        return {
            "trade_count": 0,
            "net_pnl": 0.0,
            "mean_net_pnl": 0.0,
            "median_net_pnl": 0.0,
            "profit_factor": 0.0,
            "hit_rate": 0.0,
            "regime_pass_rate": 0.0,
            "tail_dependency_pass": False,
            "top5_positive_share": None,
            "top_decile_positive_share": None,
            "regime_breakdown": [],
        }
    pnl = frame["net_pnl"].astype(float)
    wins = pnl[pnl > 0]
    losses = -pnl[pnl < 0]
    gross_profit = float(wins.sum())
    gross_loss = float(losses.sum())
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else (999.0 if gross_profit > 0 else 0.0)
    top = pnl.sort_values(ascending=False)
    top_decile_count = max(1, int(len(top) * 0.10))
    top5_share = float(top.head(5).sum() / gross_profit) if gross_profit > 0 else None
    top_decile_share = float(top.head(top_decile_count).sum() / gross_profit) if gross_profit > 0 else None
    mean = float(pnl.mean())
    median = float(pnl.median())
    regime_rows = _regime_breakdown(frame)
    regime_pass_rate = sum(1 for row in regime_rows if row["passed"]) / max(1, len(regime_rows))
    tail_pass = bool(
        top5_share is not None
        and top_decile_share is not None
        and top5_share <= MAX_TOP5_POSITIVE_SHARE
        and top_decile_share <= MAX_TOP_DECILE_POSITIVE_SHARE
        and not (mean > 0.0 and median < 0.0)
    )
    return {
        "trade_count": int(len(frame)),
        "net_pnl": round(float(pnl.sum()), 6),
        "mean_net_pnl": round(mean, 6),
        "median_net_pnl": round(median, 6),
        "profit_factor": round(float(profit_factor), 6),
        "hit_rate": round(float((pnl > 0).mean()), 6),
        "regime_pass_rate": round(float(regime_pass_rate), 6),
        "tail_dependency_pass": tail_pass,
        "top5_positive_share": round(top5_share, 6) if top5_share is not None else None,
        "top_decile_positive_share": round(top_decile_share, 6) if top_decile_share is not None else None,
        "regime_breakdown": regime_rows,
    }


def _regime_breakdown(frame: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for regime, subset in frame.groupby("entry_regime", dropna=False):
        pnl = subset["net_pnl"].astype(float)
        wins = pnl[pnl > 0]
        losses = -pnl[pnl < 0]
        gross_profit = float(wins.sum())
        gross_loss = float(losses.sum())
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else (999.0 if gross_profit > 0 else 0.0)
        passed = bool(float(pnl.sum()) >= 0.0 and profit_factor >= 1.0)
        rows.append(
            {
                "regime": str(regime),
                "trade_count": int(len(subset)),
                "net_pnl": round(float(pnl.sum()), 6),
                "median_net_pnl": round(float(pnl.median()), 6),
                "profit_factor": round(float(profit_factor), 6),
                "passed": passed,
            }
        )
    return sorted(rows, key=lambda row: row["net_pnl"])


def _repair_blockers(metrics: Mapping[str, Any]) -> list[str]:
    blockers: list[str] = []
    if int(metrics["trade_count"]) < MIN_REPAIR_TRADE_COUNT:
        blockers.append("repair_trade_count_below_threshold")
    if float(metrics["profit_factor"]) < MIN_REPAIR_PROFIT_FACTOR:
        blockers.append("repair_profit_factor_below_threshold")
    if float(metrics["median_net_pnl"]) < MIN_REPAIR_MEDIAN_NET_PNL:
        blockers.append("repair_median_net_pnl_below_threshold")
    if float(metrics["regime_pass_rate"]) < MIN_REPAIR_REGIME_PASS_RATE:
        blockers.append("repair_regime_pass_rate_below_threshold")
    if not bool(metrics["tail_dependency_pass"]):
        blockers.append("repair_tail_dependency_not_pass")
    return blockers


def _best_variant(variants: list[Mapping[str, Any]]) -> dict[str, Any] | None:
    if not variants:
        return None
    best = max(
        variants,
        key=lambda row: (
            bool(row.get("repair_screen_pass", False)),
            int(row.get("trade_count", 0) or 0) >= MIN_REPAIR_TRADE_COUNT,
            float(row.get("regime_pass_rate", 0.0) or 0.0),
            bool(row.get("tail_dependency_pass", False)),
            float(row.get("profit_factor", 0.0) or 0.0),
            float(row.get("median_net_pnl", 0.0) or 0.0),
            int(row.get("trade_count", 0) or 0),
        ),
    )
    return dict(best)


def _blockers(
    *,
    source_report: Mapping[str, Any],
    attribution_ready: bool,
    repair_found: bool,
) -> list[str]:
    blockers: list[str] = []
    if not attribution_ready:
        blockers.append("btc_intraday_repair_trade_attribution_missing")
    if not repair_found:
        blockers.append("btc_intraday_repair_no_variant_passed_screen")
    blockers.extend(_list_of_strings(source_report.get("blockers")))
    blockers.append("btc_intraday_repair_full_event_ledger_retest_required")
    blockers.append("btc_intraday_repair_candidate_generation_locked")
    blockers.append("btc_intraday_repair_paper_live_locked")
    blockers.append("btc_true_scalping_blocked_until_1m_tick_orderbook_spread_latency_queue_model")
    return _dedupe(blockers)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return dict(payload) if isinstance(payload, Mapping) else {}


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list_of_strings(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item)]


def _float_or_none(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _maybe_path(root: Path, path: Path) -> str | None:
    full = root / path
    return _relpath(full, root) if full.exists() else None


def _relpath(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value and value not in seen:
            out.append(value)
            seen.add(value)
    return out


def _git(args: list[str], *, cwd: Path) -> str:
    proc = subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=True, check=False)
    return proc.stdout.strip() if proc.returncode == 0 else "unknown"


def _utc_z_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    main()
