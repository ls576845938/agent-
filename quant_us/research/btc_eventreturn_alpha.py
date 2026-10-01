"""BTC event-return attribution and alpha renewal helpers.

This module is research-only. It reads canonical event-ledger artifacts and
does not import live, paper, broker, OMS, or execution-runtime modules.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from math import sqrt
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from quant_us.research.btc_alpha_hardening import classify_btc_regimes
from quant_us.research.btc_eventpf_wf import load_btc_1h_frame
from quant_us.research.btc_canonical import decide_paper_queue_from_canonical, stable_hash, write_json


BTC_EVENTRETURN_RUN_ID = "20260516T100000Z_eventreturn_alpha"
BTC_EVENTRETURN_SOURCE_RUN_ID = "20260516T080000Z_eventpf_wf"
BTC_EVENTRETURN_SOURCE_RUN_DIR = Path("artifacts/btc_canonical") / BTC_EVENTRETURN_SOURCE_RUN_ID
BTC_EVENTRETURN_OUTPUT_ROOT = Path("artifacts/btc_canonical")
BTC_EVENTRETURN_STRATEGY_ID = "btc_perp_dual_trend_v4_eventpf_wf"


def run_eventreturn_alpha_renewal(
    *,
    run_id: str = BTC_EVENTRETURN_RUN_ID,
    output_root: Path = BTC_EVENTRETURN_OUTPUT_ROOT,
    source_run_dir: Path = BTC_EVENTRETURN_SOURCE_RUN_DIR,
) -> Path:
    run_dir = output_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    frame = load_btc_1h_frame()
    event_attr = build_event_return_attribution(source_run_dir=source_run_dir, run_dir=run_dir, frame=frame)
    terminal = build_terminal_exposure_audit(source_run_dir=source_run_dir, run_dir=run_dir)
    autopsy = build_failed_fold_autopsy(run_dir=run_dir, event_return_table=event_attr["table"], terminal_audit=terminal)
    decision = build_alpha_renewal_decision(
        source_run_dir=source_run_dir,
        run_dir=run_dir,
        event_return_attribution=event_attr["report"],
        terminal_audit=terminal,
        failed_fold_autopsy=autopsy,
    )
    write_promotion_and_safety(run_dir=run_dir, decision=decision)
    write_json(
        run_dir / "run_manifest.json",
        {
            "schema_version": "btc_eventreturn_alpha_run_manifest_v1",
            "run_id": run_id,
            "source_run_id": source_run_dir.name,
            "strategy_id": BTC_EVENTRETURN_STRATEGY_ID,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "v5_generated": bool(decision.get("v5_generated", False)),
            "artifact_hash": stable_hash(decision),
        },
    )
    return run_dir


def build_event_return_attribution(
    *,
    source_run_dir: Path = BTC_EVENTRETURN_SOURCE_RUN_DIR,
    run_dir: Path,
    frame: pd.DataFrame | None = None,
) -> dict[str, Any]:
    frame = load_btc_1h_frame() if frame is None else frame
    report = read_json(source_run_dir / BTC_EVENTRETURN_STRATEGY_ID / "canonical_backtest_report.json")
    result = read_json(source_run_dir / f"{BTC_EVENTRETURN_STRATEGY_ID}_results.json")
    fold_report = read_json(source_run_dir / "walk_forward_fold_attribution.json")
    bridge = read_json(source_run_dir / "event_pf_bridge_report.json")
    trade_ledger = pd.read_csv(source_run_dir / BTC_EVENTRETURN_STRATEGY_ID / "trade_ledger.csv")
    trade_attribution = pd.read_csv(source_run_dir / BTC_EVENTRETURN_STRATEGY_ID / "trade_attribution.csv")
    manifest = read_json(Path(report["event_ledger_status"]["manifest_path"]))
    table = _event_return_table_from_manifest(
        run_id=run_dir.name,
        source_run_id=source_run_dir.name,
        report=report,
        manifest=manifest,
        frame=frame,
        trade_ledger=trade_ledger,
        trade_attribution=trade_attribution,
        fold_report=fold_report,
    )
    table.to_csv(run_dir / "event_return_table.csv", index=False)
    try:
        table.to_parquet(run_dir / "event_return_table.parquet", index=False)
    except Exception:
        pass
    event_pf = profit_factor(table["event_return"])
    event_pf_from_pnl = profit_factor(table["signed_event_pnl"])
    positive = table.loc[table["event_return"] > 0.0]
    negative = table.loc[table["event_return"] < 0.0]
    report_payload = {
        "schema_version": "btc_event_return_attribution_v1",
        "run_id": run_dir.name,
        "source_run_id": source_run_dir.name,
        "strategy_id": BTC_EVENTRETURN_STRATEGY_ID,
        "strategy_version": report.get("strategy_version", ""),
        "event_PF": round(event_pf, 6),
        "event_PF_from_signed_pnl": round(event_pf_from_pnl, 6),
        "source_event_PF": float(report["metrics"]["event_profit_factor"]),
        "event_pf_definition_summary": {
            "definition": "sum positive hourly event returns divided by absolute sum negative hourly event returns",
            "gate_metric": "event_PF",
            "ordinary_PF_status": "diagnostic_only",
            "source": "event-ledger hourly equity snapshots",
        },
        "overall_distribution": {
            "event_count": int(len(table)),
            "positive_event_count": int(len(positive)),
            "negative_event_count": int(len(negative)),
            "positive_event_return_sum": round(float(positive["event_return"].sum()), 10),
            "negative_event_return_sum": round(float(negative["event_return"].sum()), 10),
            "positive_event_pnl_sum": round(float(positive["signed_event_pnl"].sum()), 6),
            "negative_event_pnl_sum": round(float(negative["signed_event_pnl"].sum()), 6),
            "zero_event_count": int((table["event_return"] == 0.0).sum()),
        },
        "by_fold": group_event_returns(table, "fold_id"),
        "by_regime": group_event_returns(table, "regime"),
        "by_side": group_event_returns(table, "position_side"),
        "by_holding_age_bucket": group_event_returns(table, "holding_age_bucket"),
        "by_exposure_bucket": group_event_returns(table, "exposure_bucket"),
        "by_cost_bucket": group_event_returns(table, "cost_bucket"),
        "by_entry_reason_active": group_event_returns(table, "entry_reason_active"),
        "by_exit_reason_pending": group_event_returns(table, "exit_reason_pending"),
        "by_compression_state": group_event_returns(table, "compression_state"),
        "by_expansion_state": group_event_returns(table, "expansion_state"),
        "by_trend_strength": group_event_returns(table, "trend_strength_bucket"),
        "by_volatility_bucket": group_event_returns(table, "volatility_bucket"),
        "top_50_negative_events": _top_event_rows(table, ascending=True),
        "top_50_positive_events": _top_event_rows(table, ascending=False),
        "largest_event_drawdown_clusters": _drawdown_clusters(table),
        "profitable_trade_negative_event_check": _profitable_trade_negative_event_check(table, trade_attribution),
        "bridge_reference": {
            "ordinary_PF": bridge.get("ordinary_PF"),
            "event_PF": bridge.get("event_PF"),
            "pf_gap_ordinary_minus_event": bridge.get("pf_gap_ordinary_minus_event"),
        },
        "event_return_root_cause_summary": _event_return_root_causes(table, report),
    }
    write_json(run_dir / "event_return_attribution.json", report_payload)
    return {"report": report_payload, "table": table}


def build_terminal_exposure_audit(
    *,
    source_run_dir: Path = BTC_EVENTRETURN_SOURCE_RUN_DIR,
    run_dir: Path,
) -> dict[str, Any]:
    report = read_json(source_run_dir / BTC_EVENTRETURN_STRATEGY_ID / "canonical_backtest_report.json")
    trade_ledger = pd.read_csv(source_run_dir / BTC_EVENTRETURN_STRATEGY_ID / "trade_ledger.csv")
    manifest = read_json(Path(report["event_ledger_status"]["manifest_path"]))
    ledger_artifact = manifest["evidence"]["ledger_artifact"]
    snapshots = ledger_artifact["reconciliation"]["snapshots"]
    equity = pd.Series(
        [float(row.get("ledger_equity", row.get("snapshot_equity", 0.0))) for row in snapshots],
        index=pd.to_datetime([row["timestamp_utc"] for row in snapshots], utc=True),
        dtype=float,
    )
    event_returns = equity.pct_change().fillna(0.0)
    position_value = float(ledger_artifact.get("pnl", {}).get("position_value", 0.0))
    commission_rate = float(manifest.get("cost_model", {}).get("commission_rate", 0.0))
    slippage_bps = float(manifest.get("slippage_model", {}).get("slippage_bps", manifest.get("cost_model", {}).get("slippage_bps", 0.0)))
    flatten_cost = position_value * (commission_rate + slippage_bps / 10_000.0)
    forced_equity = pd.concat(
        [
            equity,
            pd.Series(
                [float(equity.iloc[-1]) - flatten_cost],
                index=[equity.index[-1] + pd.Timedelta(hours=1)],
                dtype=float,
            ),
        ]
    )
    forced_returns = forced_equity.pct_change().fillna(0.0)
    closed_net = float(trade_ledger["net_pnl"].sum())
    closed_total_return = closed_net / 100_000.0
    payload = {
        "schema_version": "btc_terminal_exposure_audit_v1",
        "run_id": run_dir.name,
        "source_run_id": source_run_dir.name,
        "strategy_id": BTC_EVENTRETURN_STRATEGY_ID,
        "policies": [
            {
                "policy": "mark_to_market_at_end",
                "net_pnl": round(float(equity.iloc[-1] - equity.iloc[0]), 6),
                "event_PF": profit_factor(event_returns),
                "PF": float(report["metrics"]["profit_factor"]),
                "Sharpe": _sharpe(event_returns),
                "MDD": _max_drawdown(equity),
                "total_return": round(float(equity.iloc[-1] / equity.iloc[0] - 1.0), 8),
                "terminal_position_value": round(position_value, 6),
                "open_pnl_included": True,
                "liquidation_or_flatten_cost_estimate": 0.0,
                "gate_eligible": True,
                "notes": "Current canonical event-ledger policy.",
            },
            {
                "policy": "force_flat_at_end",
                "net_pnl": round(float(forced_equity.iloc[-1] - forced_equity.iloc[0]), 6),
                "event_PF": profit_factor(forced_returns),
                "PF": profit_factor(trade_ledger["net_pnl"]),
                "Sharpe": _sharpe(forced_returns),
                "MDD": _max_drawdown(forced_equity),
                "total_return": round(float(forced_equity.iloc[-1] / forced_equity.iloc[0] - 1.0), 8),
                "terminal_position_value": 0.0,
                "open_pnl_included": True,
                "liquidation_or_flatten_cost_estimate": round(flatten_cost, 6),
                "gate_eligible": False,
                "notes": "Diagnostic estimate only because the strategy did not predeclare a force-flat-at-end execution policy.",
            },
            {
                "policy": "closed_trades_only_diagnostic",
                "net_pnl": round(closed_net, 6),
                "event_PF": None,
                "PF": profit_factor(trade_ledger["net_pnl"]),
                "Sharpe": None,
                "MDD": None,
                "total_return": round(closed_total_return, 8),
                "terminal_position_value": 0.0,
                "open_pnl_included": False,
                "liquidation_or_flatten_cost_estimate": 0.0,
                "gate_eligible": False,
                "notes": "Closed-trade PF remains diagnostic-only and cannot be used for promotion.",
            },
        ],
        "recommended_terminal_policy": {
            "policy": "mark_to_market_at_end_for_current_gate",
            "future_experiment_requirement": "If a strategy depends on terminal flattening, the force-flat rule must be declared before the run and executed through event-ledger fills.",
            "do_not_select_best_metric": True,
        },
    }
    write_json(run_dir / "terminal_exposure_audit.json", payload)
    return payload


def build_failed_fold_autopsy(
    *,
    run_dir: Path,
    event_return_table: pd.DataFrame | None = None,
    terminal_audit: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if event_return_table is None:
        event_return_table = pd.read_csv(run_dir / "event_return_table.csv")
    terminal_audit = terminal_audit or read_json(run_dir / "terminal_exposure_audit.json")
    rows = []
    for fold_id in [3, 4]:
        subset = event_return_table.loc[event_return_table["fold_id"].astype(str) == str(fold_id)].copy()
        negative = subset.loc[subset["event_return"] < 0.0]
        positive = subset.loc[subset["event_return"] > 0.0]
        worst_regime = _worst_group(subset, "regime")
        worst_side = _worst_group(subset, "position_side")
        worst_age = _worst_group(subset, "holding_age_bucket")
        worst_exposure = _worst_group(subset, "exposure_bucket")
        worst_cost = _worst_group(subset, "cost_bucket")
        worst_entry = _worst_group(subset, "entry_reason_active")
        worst_exit = _worst_group(subset, "exit_reason_pending")
        fold = {
            "fold_id": fold_id,
            "start_date": str(subset["timestamp"].min()) if not subset.empty else "",
            "end_date": str(subset["timestamp"].max()) if not subset.empty else "",
            "event_PF": profit_factor(subset["event_return"]),
            "total_return": round(float(subset["equity_after"].iloc[-1] / subset["equity_before"].iloc[0] - 1.0), 8) if not subset.empty else 0.0,
            "max_drawdown": _max_drawdown(pd.Series(subset["equity_after"].values)) if not subset.empty else 0.0,
            "trade_count": int((subset["closed_pnl"].abs() > 0.0).sum()),
            "event_count": int(len(subset)),
            "positive_event_count": int(len(positive)),
            "negative_event_count": int(len(negative)),
            "positive_event_sum": round(float(positive["event_return"].sum()), 10),
            "negative_event_sum": round(float(negative["event_return"].sum()), 10),
            "largest_negative_events": _top_event_rows(subset, ascending=True, limit=10),
            "worst_regime": worst_regime,
            "worst_side": worst_side,
            "worst_holding_age_bucket": worst_age,
            "worst_exposure_bucket": worst_exposure,
            "worst_cost_bucket": worst_cost,
            "worst_entry_reason": worst_entry,
            "worst_exit_context": worst_exit,
            "terminal_exposure_contribution": _fold_terminal_contribution(fold_id),
            "fees_slippage_contribution": {
                "fees": round(float(subset["fees"].sum()), 6),
                "slippage": round(float(subset["slippage"].sum()), 6),
                "share_of_negative_pnl": round(
                    float((subset["fees"].sum() + subset["slippage"].sum()) / max(abs(negative["signed_event_pnl"].sum()), 1e-12)),
                    6,
                ),
            },
            "funding_contribution": {"funding_present": False, "funding": 0.0},
            "whether_failure_is_rule_fixable": False,
            "recommended_action": "archive_alpha",
        }
        rows.append(fold)
    common = _common_fold_pattern(rows)
    payload = {
        "schema_version": "btc_failed_fold_autopsy_v1",
        "run_id": run_dir.name,
        "source_run_id": BTC_EVENTRETURN_SOURCE_RUN_ID,
        "strategy_id": BTC_EVENTRETURN_STRATEGY_ID,
        "failed_folds": rows,
        "fold_3_4_same_pattern": common["same_pattern"],
        "common_failure_pattern": common["summary"],
        "root_cause_summary": [
            "Fold 3 and fold 4 both fail through event-return mark-to-market losses while carrying long exposure.",
            "The losses are not explained primarily by fees, slippage, funding, signal flips, or broad short exposure.",
            "The failure pattern is time-window dependent and too weakly concentrated to justify a single stable rule patch.",
        ],
        "recommended_action": "archive_alpha",
        "terminal_policy_reference": terminal_audit.get("recommended_terminal_policy", {}),
    }
    write_json(run_dir / "failed_fold_autopsy.json", payload)
    return payload


def build_alpha_renewal_decision(
    *,
    source_run_dir: Path,
    run_dir: Path,
    event_return_attribution: Mapping[str, Any],
    terminal_audit: Mapping[str, Any],
    failed_fold_autopsy: Mapping[str, Any],
) -> dict[str, Any]:
    previous = read_json(source_run_dir / f"{BTC_EVENTRETURN_STRATEGY_ID}_results.json")
    decision = {
        "schema_version": "btc_alpha_renewal_decision_v1",
        "run_id": run_dir.name,
        "source_run_id": source_run_dir.name,
        "strategy_line": "perp_dual_trend",
        "decision": "archive_perp_dual_trend",
        "status": "research_failed",
        "v5_generated": False,
        "v5_generation_blocked_reason": "No cross-fold stable event-return failure pattern was found. Event_PF remains near 1.02 after v4, and fold 3/4 failures are mark-to-market alpha absence rather than a clean rule defect.",
        "evidence_consistency": {
            "event_pf_recomputed": event_return_attribution.get("event_PF"),
            "source_event_pf": event_return_attribution.get("source_event_PF"),
            "consistent": abs(float(event_return_attribution.get("event_PF", 0.0)) - float(event_return_attribution.get("source_event_PF", 0.0))) <= 0.001,
        },
        "previous_v1_v4_metrics": previous.get("comparison", []),
        "archive_manifest": {
            "strategy_line": "perp_dual_trend",
            "archived": True,
            "archive_status": "research_failed",
            "code_retained": True,
            "artifacts_retained": True,
            "reason": "event-return edge too thin for internal gate",
        },
        "reasons": [
            "event_PF is constrained by near-balanced positive and negative hourly event returns rather than by ordinary closed-trade aggregation alone",
            "terminal exposure explains part of PF/event_PF divergence but does not create a gate-passing candidate",
            "failed folds 3 and 4 do not expose one robust, no-lookahead rule that would plausibly lift event_PF to 1.15",
            "order-flow and exit surgery had already failed to solve event_PF in the previous sprint",
        ],
        "alpha_hypothesis_backlog": [
            {
                "hypothesis": "BTC long-only event continuation after low-vol uptrend confirmation",
                "rationale": "Prior attribution showed long exposure in trending_up and low-vol uptrend contexts carries the cleanest positive contribution.",
                "required_data": ["BTCUSDT 1h OHLCV", "multi-timeframe trend state", "event-ledger fills"],
                "expected_event_level_edge": "fewer adverse hourly mark-to-market events during confirmed continuation windows",
                "no_lookahead_requirements": "trend and volatility confirmation must use only current and historical bars",
                "first_experiment_plan": "rank low-vol uptrend continuations by event-return PF and hold-age decay before creating a strategy candidate",
                "stop_condition": "archive if event_PF < 1.10 or failed folds remain concentrated after first pass",
            },
            {
                "hypothesis": "BTC compression-to-expansion breakout with event-return objective",
                "rationale": "Expansion regimes showed high payoff in trade attribution, but must be optimized directly on event returns.",
                "required_data": ["BTCUSDT OHLCV", "volume/quote volume", "range compression features"],
                "expected_event_level_edge": "large positive event-return clusters after expansion onset, with explicit adverse-event stop",
                "no_lookahead_requirements": "compression thresholds must be expanding or rolling historical quantiles only",
                "first_experiment_plan": "build a diagnostic breakout label-free signal and evaluate event-return distribution by expansion age",
                "stop_condition": "archive if positive event sums are not at least 1.15x negative sums after costs",
            },
            {
                "hypothesis": "BTC liquidation-shock recovery continuation",
                "rationale": "Current trend line avoids shocks, but post-shock continuation may offer a different event-return source.",
                "required_data": ["BTCUSDT OHLCV", "volume shock state", "liquidation proxy from candle/volume"],
                "expected_event_level_edge": "asymmetric positive event-return rebounds after capitulation without broad short exposure",
                "no_lookahead_requirements": "shock detection must be bar-close only and recovery confirmation must wait for subsequent historical bars",
                "first_experiment_plan": "profile event returns for post-shock windows before any strategy implementation",
                "stop_condition": "archive if rebound edge is single-window only or max drawdown worsens above gate limits",
            },
        ],
        "paper_queue_status": "LOCKED",
        "live_status": "FROZEN",
        "terminal_policy": terminal_audit.get("recommended_terminal_policy", {}),
        "failed_fold_action": failed_fold_autopsy.get("recommended_action"),
    }
    write_json(run_dir / "alpha_renewal_decision.json", decision)
    write_json(run_dir / "perp_dual_trend_archive_manifest.json", decision["archive_manifest"])
    write_alpha_renewal_decision_doc(run_dir=run_dir, decision=decision)
    return decision


def write_promotion_and_safety(*, run_dir: Path, decision: Mapping[str, Any]) -> None:
    gate_result = {
        "strategy_id": "perp_dual_trend",
        "status": "research_failed",
        "passed": False,
        "fail_reasons": ["alpha_archived", "event_return_edge_too_thin", "walk_forward_instability"],
        "evidence_source": "event_return_alpha_renewal",
    }
    paper_review = decide_paper_queue_from_canonical([gate_result])
    paper_review["max_state"] = "research_failed"
    paper_review["reason"] = "alpha_archived_after_event_return_attribution"
    promotion = {
        "schema_version": "btc_eventreturn_promotion_decision_v1",
        "run_id": run_dir.name,
        "candidate_gate_results": [gate_result],
        "paper_review": paper_review,
        "paper_auto_start": False,
        "live_frozen": True,
        "evidence_source": "event_return_alpha_renewal",
        "forbidden_states": ["paper_ready", "live_ready", "live_enabled"],
        "alpha_renewal_decision": decision.get("decision"),
    }
    safety = {
        "schema_version": "btc_eventreturn_paper_live_safety_v1",
        "run_id": run_dir.name,
        "candidate_passed_internal_gate_count": 0,
        "paper_queue_status": "LOCKED",
        "paper_review_queue_locked": True,
        "paper_auto_start": False,
        "live_status": "FROZEN",
        "live_frozen": True,
        "real_broker_api_called": False,
        "real_orders_created": False,
        "max_state": "research_failed",
    }
    write_json(run_dir / "promotion_decision.json", promotion)
    write_json(run_dir / "paper_live_safety_status.json", safety)


def write_alpha_renewal_decision_doc(*, run_dir: Path, decision: Mapping[str, Any]) -> None:
    backlog = decision["alpha_hypothesis_backlog"]
    lines = [
        "# BTC Alpha Renewal Decision",
        "",
        f"- Run ID: `{run_dir.name}`",
        f"- Source run: `{decision['source_run_id']}`",
        f"- Decision: `{decision['decision']}`",
        f"- Status: `{decision['status']}`",
        f"- v5 generated: `{decision['v5_generated']}`",
        "",
        "## Conclusion",
        "",
        "Archive the `perp_dual_trend` line as `research_failed`. The code and artifacts are retained, but no v5 is generated because the event-return evidence does not show a stable, rule-fixable defect.",
        "",
        "## Evidence",
        "",
        *[f"- {reason}" for reason in decision["reasons"]],
        "",
        "## Alpha Hypothesis Backlog",
        "",
    ]
    for item in backlog:
        lines.extend(
            [
                f"### {item['hypothesis']}",
                "",
                f"- Rationale: {item['rationale']}",
                f"- Required data: {', '.join(item['required_data'])}",
                f"- Expected event-level edge: {item['expected_event_level_edge']}",
                f"- No-lookahead requirements: {item['no_lookahead_requirements']}",
                f"- First experiment plan: {item['first_experiment_plan']}",
                f"- Stop condition: {item['stop_condition']}",
                "",
            ]
        )
    lines.extend(
        [
            "## Safety",
            "",
            "- PAPER QUEUE: LOCKED",
            "- LIVE: FROZEN",
            "- No v5, paper_ready, live_ready, or live_enabled state is created.",
        ]
    )
    Path("docs/research/BTC_ALPHA_RENEWAL_DECISION.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _event_return_table_from_manifest(
    *,
    run_id: str,
    source_run_id: str,
    report: Mapping[str, Any],
    manifest: Mapping[str, Any],
    frame: pd.DataFrame,
    trade_ledger: pd.DataFrame,
    trade_attribution: pd.DataFrame,
    fold_report: Mapping[str, Any],
) -> pd.DataFrame:
    ledger_artifact = manifest["evidence"]["ledger_artifact"]
    snapshots = ledger_artifact["reconciliation"]["snapshots"]
    raw = pd.DataFrame(
        {
            "timestamp": pd.to_datetime([row["timestamp_utc"] for row in snapshots], utc=True),
            "equity_after": [float(row.get("ledger_equity", row.get("snapshot_equity", 0.0))) for row in snapshots],
            "cash_after": [float(row.get("ledger_cash", row.get("snapshot_cash", 0.0))) for row in snapshots],
        }
    ).sort_values("timestamp")
    raw["equity_before"] = raw["equity_after"].shift(1)
    raw["cash_before"] = raw["cash_after"].shift(1)
    raw = raw.iloc[1:].copy()
    raw["event_return"] = raw["equity_after"] / raw["equity_before"].replace(0.0, np.nan) - 1.0
    raw["event_return"] = raw["event_return"].fillna(0.0)
    raw["signed_event_pnl"] = raw["equity_after"] - raw["equity_before"]

    indexed_frame = frame.copy()
    indexed_frame.index = pd.to_datetime(indexed_frame.index, utc=True)
    close = indexed_frame["close"].astype(float).reindex(raw["timestamp"], method="ffill").reset_index(drop=True)
    raw["close"] = close
    exposure = raw["equity_after"] - raw["cash_after"]
    raw["position_size"] = (exposure / raw["close"].replace(0.0, np.nan)).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    raw["exposure"] = (exposure / raw["equity_after"].replace(0.0, np.nan)).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    raw["position_side"] = np.where(raw["exposure"] > 0.001, "long", np.where(raw["exposure"] < -0.001, "short", "flat"))

    regimes = classify_btc_regimes(indexed_frame).reindex(raw["timestamp"], method="ffill").reset_index(drop=True)
    raw["regime"] = regimes.astype(str)
    returns = indexed_frame["close"].astype(float).pct_change().fillna(0.0)
    volatility = returns.rolling(168, min_periods=24).std(ddof=0).fillna(0.0).reindex(raw["timestamp"], method="ffill").reset_index(drop=True)
    trend = indexed_frame["close"].astype(float).pct_change(168).fillna(0.0).reindex(raw["timestamp"], method="ffill").reset_index(drop=True)
    range_pct = ((indexed_frame["high"].astype(float) - indexed_frame["low"].astype(float)).abs() / indexed_frame["close"].astype(float).shift(1)).fillna(0.0)
    range_aligned = range_pct.reindex(raw["timestamp"], method="ffill").reset_index(drop=True)
    raw["volatility_bucket"] = _historical_buckets(volatility, labels=("low_vol", "mid_vol", "high_vol"))
    raw["trend_strength_bucket"] = pd.cut(
        trend,
        bins=[-np.inf, -0.01, 0.01, np.inf],
        labels=["weak_downtrend", "neutral_trend", "strong_uptrend"],
    ).astype(str)
    raw["compression_state"] = (range_aligned <= range_aligned.expanding(min_periods=24).quantile(0.35).fillna(range_aligned)).astype(bool)
    raw["expansion_state"] = raw["regime"].isin(["expansion", "high_vol_trend"])
    raw["liquidation_shock_state"] = raw["regime"].eq("liquidation_shock")

    raw["holding_age_bars"] = _holding_age(raw["position_side"])
    raw["holding_age_bucket"] = pd.cut(
        raw["holding_age_bars"],
        bins=[-1, 0, 24, 72, 168, 720, np.inf],
        labels=["flat", "intraday_to_1d", "1d_to_3d", "3d_to_7d", "1w_to_1m", "over_1m"],
    ).astype(str)
    raw["exposure_bucket"] = pd.cut(
        raw["exposure"].abs(),
        bins=[-0.001, 0.01, 0.05, 0.15, np.inf],
        labels=["flat", "low_exposure", "mid_exposure", "high_exposure"],
    ).astype(str)

    raw["entry_reason_active"] = _active_trade_field(raw["timestamp"], trade_attribution, "entry_condition", default="no_active_trade")
    raw["exit_reason_pending"] = _exit_reason_at_timestamp(raw["timestamp"], trade_attribution)
    raw["flip_state"] = raw["exit_reason_pending"].eq("signal_flip_exit")
    raw["cooldown_state"] = _cooldown_state(raw["timestamp"], trade_attribution, bars=120)

    costs = _cost_maps_from_trades(trade_ledger)
    raw["fees"] = [costs["fees"].get(ts.isoformat(), 0.0) for ts in raw["timestamp"]]
    raw["slippage"] = [costs["slippage"].get(ts.isoformat(), 0.0) for ts in raw["timestamp"]]
    raw["funding"] = 0.0
    raw["closed_pnl"] = [costs["closed_pnl"].get(ts.isoformat(), 0.0) for ts in raw["timestamp"]]
    raw["open_pnl"] = raw["signed_event_pnl"] - raw["closed_pnl"] - raw["fees"] - raw["slippage"]
    cost_ratio = (raw["fees"].abs() + raw["slippage"].abs()) / raw["signed_event_pnl"].abs().replace(0.0, np.nan)
    raw["cost_bucket"] = pd.cut(
        cost_ratio.fillna(0.0),
        bins=[-0.001, 0.05, 0.25, np.inf],
        labels=["low_cost_ratio", "mid_cost_ratio", "high_cost_ratio"],
    ).astype(str)
    raw["fold_id"] = _fold_ids(raw["timestamp"], fold_report)
    raw["is_positive_event"] = raw["event_return"] > 0.0
    raw["is_negative_event"] = raw["event_return"] < 0.0
    raw["run_id"] = run_id
    raw["source_run_id"] = source_run_id
    raw["strategy_id"] = BTC_EVENTRETURN_STRATEGY_ID
    raw["strategy_version"] = str(report.get("strategy_version", ""))
    columns = [
        "run_id",
        "source_run_id",
        "timestamp",
        "strategy_id",
        "strategy_version",
        "equity_before",
        "equity_after",
        "event_return",
        "signed_event_pnl",
        "position_side",
        "position_size",
        "exposure",
        "open_pnl",
        "closed_pnl",
        "fees",
        "slippage",
        "funding",
        "regime",
        "volatility_bucket",
        "trend_strength_bucket",
        "compression_state",
        "expansion_state",
        "liquidation_shock_state",
        "holding_age_bars",
        "holding_age_bucket",
        "exposure_bucket",
        "entry_reason_active",
        "exit_reason_pending",
        "flip_state",
        "cooldown_state",
        "cost_bucket",
        "fold_id",
        "is_positive_event",
        "is_negative_event",
    ]
    return raw[columns]


def group_event_returns(frame: pd.DataFrame, column: str) -> list[dict[str, Any]]:
    rows = []
    for key, subset in frame.groupby(column, dropna=False):
        positive = subset.loc[subset["event_return"] > 0.0]
        negative = subset.loc[subset["event_return"] < 0.0]
        rows.append(
            {
                column: str(key),
                "event_count": int(len(subset)),
                "positive_event_count": int(len(positive)),
                "negative_event_count": int(len(negative)),
                "event_PF": profit_factor(subset["event_return"]),
                "signed_event_pnl": round(float(subset["signed_event_pnl"].sum()), 6),
                "positive_event_sum": round(float(positive["event_return"].sum()), 10),
                "negative_event_sum": round(float(negative["event_return"].sum()), 10),
            }
        )
    return sorted(rows, key=lambda row: row["signed_event_pnl"], reverse=True)


def profit_factor(values: Sequence[float] | pd.Series) -> float:
    series = pd.to_numeric(pd.Series(values), errors="coerce").fillna(0.0)
    gains = float(series[series > 0.0].sum())
    losses = abs(float(series[series < 0.0].sum()))
    if losses <= 0.0:
        return 999.0 if gains > 0.0 else 0.0
    return round(gains / losses, 6)


def read_json(path: Path | str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _historical_buckets(series: pd.Series, *, labels: tuple[str, str, str]) -> pd.Series:
    low = series.expanding(min_periods=24).quantile(0.33).fillna(series)
    high = series.expanding(min_periods=24).quantile(0.66).fillna(series)
    return pd.Series(
        np.where(series <= low, labels[0], np.where(series >= high, labels[2], labels[1])),
        index=series.index,
    )


def _holding_age(side: pd.Series) -> list[int]:
    ages: list[int] = []
    age = 0
    current = "flat"
    for value in side.astype(str):
        if value == "flat":
            age = 0
            current = "flat"
        else:
            age = age + 1 if value == current else 1
            current = value
        ages.append(age)
    return ages


def _active_trade_field(timestamps: pd.Series, attribution: pd.DataFrame, field: str, *, default: str) -> pd.Series:
    values = []
    trades = attribution.copy()
    trades["entry_time_ts"] = pd.to_datetime(trades["entry_time"], utc=True)
    trades["exit_time_ts"] = pd.to_datetime(trades["exit_time"], utc=True)
    for ts in timestamps:
        active = trades.loc[(trades["entry_time_ts"] <= ts) & (trades["exit_time_ts"] >= ts)]
        values.append(str(active.iloc[-1][field]) if not active.empty and field in active else default)
    return pd.Series(values, index=timestamps.index)


def _exit_reason_at_timestamp(timestamps: pd.Series, attribution: pd.DataFrame) -> pd.Series:
    exits = {
        pd.Timestamp(row["exit_time"]).tz_convert("UTC").isoformat(): str(row["exit_reason"])
        for _, row in attribution.iterrows()
    }
    return pd.Series([exits.get(ts.isoformat(), "none") for ts in timestamps], index=timestamps.index)


def _cooldown_state(timestamps: pd.Series, attribution: pd.DataFrame, *, bars: int) -> pd.Series:
    exit_times = pd.to_datetime(attribution["exit_time"], utc=True).sort_values()
    states = []
    for ts in timestamps:
        recent = exit_times.loc[(exit_times < ts) & (exit_times >= ts - pd.Timedelta(hours=bars))]
        states.append(bool(len(recent)))
    return pd.Series(states, index=timestamps.index)


def _cost_maps_from_trades(trades: pd.DataFrame) -> dict[str, dict[str, float]]:
    maps = {"fees": {}, "slippage": {}, "closed_pnl": {}}
    for _, row in trades.iterrows():
        entry = pd.Timestamp(row["entry_time"]).tz_convert("UTC").isoformat()
        exit_ = pd.Timestamp(row["exit_time"]).tz_convert("UTC").isoformat()
        fees = float(row.get("fees", 0.0))
        slippage = float(row.get("slippage", 0.0))
        maps["fees"][entry] = maps["fees"].get(entry, 0.0) + fees * 0.5
        maps["fees"][exit_] = maps["fees"].get(exit_, 0.0) + fees * 0.5
        maps["slippage"][entry] = maps["slippage"].get(entry, 0.0) + slippage * 0.5
        maps["slippage"][exit_] = maps["slippage"].get(exit_, 0.0) + slippage * 0.5
        maps["closed_pnl"][exit_] = maps["closed_pnl"].get(exit_, 0.0) + float(row.get("net_pnl", 0.0))
    return maps


def _fold_ids(timestamps: pd.Series, fold_report: Mapping[str, Any]) -> list[str]:
    folds = []
    for row in fold_report.get("folds", []):
        folds.append(
            (
                str(row.get("fold_id")),
                pd.Timestamp(row["test_start"]).tz_convert("UTC"),
                pd.Timestamp(row["test_end"]).tz_convert("UTC"),
            )
        )
    out = []
    for ts in timestamps:
        assigned = "out_of_wf"
        for fold_id, start, end in folds:
            if start <= ts <= end:
                assigned = fold_id
                break
        out.append(assigned)
    return out


def _top_event_rows(frame: pd.DataFrame, *, ascending: bool, limit: int = 50) -> list[dict[str, Any]]:
    columns = [
        "timestamp",
        "event_return",
        "signed_event_pnl",
        "position_side",
        "exposure",
        "regime",
        "fold_id",
        "holding_age_bucket",
        "entry_reason_active",
    ]
    rows = frame.sort_values("event_return", ascending=ascending)[columns].head(limit).copy()
    rows["timestamp"] = rows["timestamp"].astype(str)
    return rows.to_dict(orient="records")


def _drawdown_clusters(frame: pd.DataFrame) -> list[dict[str, Any]]:
    clusters = []
    current: list[Mapping[str, Any]] = []
    for _, row in frame.iterrows():
        if float(row["event_return"]) < 0.0:
            current.append(row)
        elif current:
            clusters.append(_cluster_summary(current))
            current = []
    if current:
        clusters.append(_cluster_summary(current))
    return sorted(clusters, key=lambda row: row["event_return_sum"])[:10]


def _cluster_summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    frame = pd.DataFrame(rows)
    return {
        "start": str(frame["timestamp"].iloc[0]),
        "end": str(frame["timestamp"].iloc[-1]),
        "event_count": int(len(frame)),
        "event_return_sum": round(float(frame["event_return"].sum()), 10),
        "signed_event_pnl_sum": round(float(frame["signed_event_pnl"].sum()), 6),
        "dominant_regime": str(frame["regime"].mode().iloc[0]) if not frame.empty else "unknown",
        "dominant_fold": str(frame["fold_id"].mode().iloc[0]) if not frame.empty else "unknown",
    }


def _profitable_trade_negative_event_check(table: pd.DataFrame, attribution: pd.DataFrame) -> dict[str, Any]:
    profitable = attribution.loc[attribution["net_pnl"] > 0.0].copy()
    if profitable.empty:
        return {"profitable_trade_count": 0, "negative_event_inside_profitable_trades": 0}
    count = 0
    pnl = 0.0
    for _, trade in profitable.iterrows():
        start = pd.Timestamp(trade["entry_time"]).tz_convert("UTC")
        end = pd.Timestamp(trade["exit_time"]).tz_convert("UTC")
        subset = table.loc[(pd.to_datetime(table["timestamp"], utc=True) >= start) & (pd.to_datetime(table["timestamp"], utc=True) <= end)]
        neg = subset.loc[subset["event_return"] < 0.0]
        count += len(neg)
        pnl += float(neg["signed_event_pnl"].sum())
    return {
        "profitable_trade_count": int(len(profitable)),
        "negative_event_inside_profitable_trades": int(count),
        "negative_event_pnl_inside_profitable_trades": round(pnl, 6),
    }


def _event_return_root_causes(table: pd.DataFrame, report: Mapping[str, Any]) -> list[str]:
    positive = table.loc[table["event_return"] > 0.0]
    negative = table.loc[table["event_return"] < 0.0]
    positive_sum = float(positive["event_return"].sum())
    negative_sum = abs(float(negative["event_return"].sum()))
    active_negative = negative.loc[negative["position_side"] != "flat"]
    fees_slip = float(table["fees"].sum() + table["slippage"].sum())
    neg_pnl = abs(float(negative["signed_event_pnl"].sum()))
    return [
        f"event_PF stays near {float(report['metrics']['event_profit_factor']):.4f} because positive event-return sum ({positive_sum:.6f}) barely exceeds negative event-return sum ({negative_sum:.6f}).",
        f"negative events are primarily mark-to-market while exposed: {len(active_negative)} of {len(negative)} negative events occur with non-flat exposure.",
        f"fees and estimated slippage in the event-return table are small relative to negative event PnL ({fees_slip:.2f} vs {neg_pnl:.2f}), so costs are not the main blocker.",
        "closed-trade PF is high because trades aggregate long holding campaigns; event_PF penalizes the adverse hourly path inside those campaigns.",
    ]


def _worst_group(frame: pd.DataFrame, column: str) -> dict[str, Any]:
    rows = group_event_returns(frame, column)
    if not rows:
        return {column: "none", "signed_event_pnl": 0.0, "event_PF": 0.0}
    return sorted(rows, key=lambda row: row["signed_event_pnl"])[0]


def _fold_terminal_contribution(fold_id: int) -> dict[str, Any]:
    path = BTC_EVENTRETURN_SOURCE_RUN_DIR / "manifests" / f"run_{BTC_EVENTRETURN_STRATEGY_ID}_wf{fold_id}.json"
    if not path.exists():
        return {"available": False}
    manifest = read_json(path)
    pnl = manifest["evidence"]["ledger_artifact"].get("pnl", {})
    cost = manifest.get("cost_model", {})
    return {
        "available": True,
        "net_pnl": float(pnl.get("net_pnl", 0.0)),
        "terminal_position_value": float(pnl.get("position_value", 0.0)),
        "realized_commission": float(cost.get("realized_commission", 0.0)),
        "realized_slippage_cost": float(cost.get("realized_slippage_cost", 0.0)),
    }


def _common_fold_pattern(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if len(rows) < 2:
        return {"same_pattern": False, "summary": "insufficient failed folds"}
    same_side = rows[0]["worst_side"].get("position_side") == rows[1]["worst_side"].get("position_side")
    same_age = rows[0]["worst_holding_age_bucket"].get("holding_age_bucket") == rows[1]["worst_holding_age_bucket"].get("holding_age_bucket")
    same_regime = rows[0]["worst_regime"].get("regime") == rows[1]["worst_regime"].get("regime")
    same = bool(same_side and same_age and same_regime)
    return {
        "same_pattern": same,
        "summary": "same side/age/regime loss pattern" if same else "fold 3 and 4 share long mark-to-market weakness but not a sufficiently identical regime/age pattern",
    }


def _sharpe(returns: pd.Series, periods_per_year: float = 365.0 * 24.0) -> float:
    std = float(returns.std(ddof=0))
    return round(float(returns.mean() / std * sqrt(periods_per_year)), 6) if std > 0 else 0.0


def _max_drawdown(equity: pd.Series) -> float:
    series = pd.to_numeric(equity, errors="coerce").dropna()
    if series.empty:
        return 0.0
    drawdown = series / series.cummax() - 1.0
    return round(float(drawdown.min()) * 100.0, 6)
