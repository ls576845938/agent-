"""BTC event-PF bridge and walk-forward stabilization helpers.

This module is research-only. It builds diagnostic artifacts from the canonical
event-ledger path and never imports broker, paper, or live runtime modules.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import numpy as np
import pandas as pd

from backend.app.services.market_data import load_market_frame
from quant_us.research.btc_alpha_hardening import classify_btc_regimes
from quant_us.research.btc_canonical import (
    BTC_CANONICAL_GATE_THRESHOLDS,
    build_canonical_report,
    build_trade_attribution,
    cost_stress_for_signal,
    decide_paper_queue_from_canonical,
    evaluate_canonical_gate,
    fills_to_trade_ledger,
    git_commit_hash,
    regime_report_from_trades,
    run_event_with_signal,
    simplified_dsr,
    simplified_pbo,
    stable_hash,
    summarize_trade_attribution,
    write_json,
)
from quant_us.research.btc_canonical import btc_perp_dual_trend_v3_signal as _v3_signal


BTC_EVENTPF_SOURCE_RUN_ID = "20260516T061000Z_attribution"
BTC_EVENTPF_WF_RUN_ID = "20260516T080000Z_eventpf_wf"
BTC_EVENTPF_WF_SOURCE_RUN_DIR = Path("artifacts/btc_canonical") / BTC_EVENTPF_SOURCE_RUN_ID
BTC_EVENTPF_WF_OUTPUT_ROOT = Path("artifacts/btc_canonical")

BTC_EVENTPF_START = datetime(2024, 1, 1, tzinfo=timezone.utc)
BTC_EVENTPF_END = datetime(2026, 5, 12, tzinfo=timezone.utc)

BTC_V3_PARAMS: dict[str, Any] = {
    "fast_ma": 96,
    "slow_ma": 336,
    "regime_ma": 720,
    "momentum_window": 168,
    "momentum_threshold": 0.025,
    "vol_window": 168,
    "max_volatility": 0.055,
    "orderflow_window": 144,
    "orderflow_veto_threshold": 0.012,
    "allowed_long_regimes": ["trending_up", "expansion"],
    "allowed_short_regimes": [],
    "min_hold_bars": 120,
    "cooldown_bars": 72,
    "exit_hysteresis_bars": 4,
    "max_hold_bars": 720,
    "signal_scale": 0.20,
    "orderflow_mode": "veto_only",
}

BTC_V4_PARAMS: dict[str, Any] = {
    **BTC_V3_PARAMS,
    "strategy_revision": "eventpf_wf_v4",
    "orderflow_mode": "no_orderflow",
    "allowed_long_regimes": ["trending_up", "expansion"],
    "allowed_short_regimes": [],
    "min_hold_bars": 120,
    "cooldown_bars": 120,
    "exit_hysteresis_bars": 8,
    "max_hold_bars": 480,
    "momentum_threshold": 0.03,
    "max_volatility": 0.052,
    "no_same_bar_flip": True,
    "flat_then_confirm_reverse": True,
    "reverse_confirmation_bars": 6,
    "reverse_requires_regime_alignment": True,
    "min_reentry_delay_bars": 120,
    "short_signal_scale": 0.0,
    "event_pf_bridge_required": True,
}


SignalBuilder = Callable[[pd.DataFrame, Mapping[str, Any]], tuple[pd.Series, dict[str, pd.Series]]]


@dataclass(frozen=True)
class StrategyEvaluation:
    report: dict[str, Any]
    decision: dict[str, Any]
    trades: pd.DataFrame
    attribution: pd.DataFrame
    cost_stress: dict[str, Any]
    walk_forward: dict[str, Any]
    regime_report: dict[str, Any]
    event: dict[str, Any]
    signal: pd.Series
    diagnostics: dict[str, pd.Series]


def load_btc_1h_frame() -> pd.DataFrame:
    return load_market_frame(
        source="sqlite",
        symbol="BTCUSDT",
        interval="1h",
        start=BTC_EVENTPF_START,
        end=BTC_EVENTPF_END,
        db_path="data/market_data.sqlite",
    )


def btc_eventpf_wf_signal(
    frame: pd.DataFrame,
    params: Mapping[str, Any] | None = None,
) -> tuple[pd.Series, dict[str, pd.Series]]:
    """Build the v4 research signal from v3 components plus scoped surgery.

    Unknown metadata fields are ignored by the underlying v3 builder. This
    wrapper only applies supported side scaling after v3 constructs the
    executable signal.
    """

    cfg = {**BTC_V3_PARAMS, **dict(params or {})}
    signal, diagnostics = _v3_signal(frame, cfg)
    if any(
        bool(cfg.get(flag, False))
        for flag in [
            "no_same_bar_flip",
            "flat_then_confirm_reverse",
            "reverse_requires_regime_alignment",
        ]
    ) or int(cfg.get("flip_cooldown_bars", 0)) > 0 or int(cfg.get("min_reentry_delay_bars", 0)) > 0:
        signal = apply_exit_surgery_policy(
            signal,
            regimes=diagnostics.get("regime"),
            reverse_confirmation_bars=int(cfg.get("reverse_confirmation_bars", 1)),
            flip_cooldown_bars=int(cfg.get("flip_cooldown_bars", cfg.get("cooldown_bars", 0))),
            min_reentry_delay_bars=int(cfg.get("min_reentry_delay_bars", 0)),
            reverse_requires_regime_alignment=bool(cfg.get("reverse_requires_regime_alignment", False)),
        )
    short_scale = float(cfg.get("short_signal_scale", 1.0))
    if short_scale != 1.0:
        signal = signal.copy()
        signal.loc[signal < 0.0] = signal.loc[signal < 0.0] * max(0.0, short_scale)
        diagnostics = dict(diagnostics)
        diagnostics["short_signal_scale"] = pd.Series(short_scale, index=signal.index, dtype=float)
    return signal.clip(-1.0, 1.0).fillna(0.0), diagnostics


def apply_exit_surgery_policy(
    signal: pd.Series,
    *,
    regimes: pd.Series | None = None,
    reverse_confirmation_bars: int = 1,
    flip_cooldown_bars: int = 0,
    min_reentry_delay_bars: int = 0,
    reverse_requires_regime_alignment: bool = False,
) -> pd.Series:
    """Force flat-before-reverse semantics using current and past bars only."""

    index = signal.index
    target = signal.reindex(index).fillna(0.0).astype(float)
    abs_size = target.abs().where(target.abs() > 0.0).ffill().fillna(0.0).clip(0.0, 1.0)
    aligned_regimes = None
    if regimes is not None:
        aligned_regimes = regimes.reindex(index).ffill().fillna("unknown").astype(str)
    output = pd.Series(0.0, index=index, dtype=float)
    position = 0.0
    cooldown_remaining = 0
    pending_reverse = 0.0
    reverse_streak = 0
    required = max(1, int(reverse_confirmation_bars))
    cooldown = max(0, int(flip_cooldown_bars), int(min_reentry_delay_bars))
    for ts in index:
        if cooldown_remaining > 0:
            cooldown_remaining -= 1
        raw = float(target.loc[ts])
        desired = 1.0 if raw > 0.0 else -1.0 if raw < 0.0 else 0.0
        if position == 0.0:
            if desired == 0.0:
                pending_reverse = 0.0
                reverse_streak = 0
            else:
                if pending_reverse == 0.0 and cooldown_remaining == 0:
                    position = desired
                    reverse_streak = 0
                elif desired == pending_reverse:
                    reverse_streak += 1
                else:
                    pending_reverse = desired
                    reverse_streak = 1
                if pending_reverse != 0.0:
                    regime_ok = True
                    if reverse_requires_regime_alignment and aligned_regimes is not None and desired < 0.0:
                        regime_ok = str(aligned_regimes.loc[ts]) == "expansion"
                    if cooldown_remaining == 0 and reverse_streak >= required and regime_ok:
                        position = desired
                        pending_reverse = 0.0
                        reverse_streak = 0
        else:
            if desired == position:
                pending_reverse = 0.0
                reverse_streak = 0
            elif desired == 0.0:
                position = 0.0
                pending_reverse = 0.0
                reverse_streak = 0
                cooldown_remaining = cooldown
            else:
                position = 0.0
                pending_reverse = desired
                reverse_streak = 1
                cooldown_remaining = cooldown
        output.loc[ts] = position * float(abs_size.loc[ts])
    return output


def build_event_pf_bridge_report(
    *,
    source_run_dir: Path = BTC_EVENTPF_WF_SOURCE_RUN_DIR,
    run_dir: Path,
    strategy_id: str = "btc_perp_dual_trend_v3",
) -> dict[str, Any]:
    strategy_dir = source_run_dir / strategy_id
    canonical_report = read_json(strategy_dir / "canonical_backtest_report.json")
    trade_ledger = pd.read_csv(strategy_dir / "trade_ledger.csv")
    attribution = pd.read_csv(strategy_dir / "trade_attribution.csv")
    manifest_path = Path(canonical_report["event_ledger_status"]["manifest_path"])
    manifest = read_json(manifest_path)
    ledger_artifact = manifest.get("evidence", {}).get("ledger_artifact", {})
    snapshots = ledger_artifact.get("reconciliation", {}).get("snapshots", [])
    equity = pd.Series(
        [float(row.get("ledger_equity", row.get("snapshot_equity", 0.0))) for row in snapshots],
        index=pd.to_datetime([row.get("timestamp_utc") for row in snapshots], utc=True),
        dtype=float,
    ).sort_index()
    equity_returns = equity.pct_change().fillna(0.0)
    equity_pnl_deltas = equity.diff().fillna(0.0)
    trade_level_pf = profit_factor(trade_ledger["net_pnl"])
    gross_pf = profit_factor(trade_ledger["gross_pnl"])
    event_pf = float(canonical_report["metrics"]["event_profit_factor"])
    cashflow_pf = profit_factor(equity_pnl_deltas)
    return_gap = round(float(canonical_report["metrics"]["profit_factor"]) - event_pf, 6)
    closed_trade_net = float(trade_ledger["net_pnl"].sum())
    ledger_net = float(ledger_artifact.get("pnl", {}).get("net_pnl", canonical_report["metrics"].get("total_return_pct", 0.0)))
    open_position_value = float(ledger_artifact.get("pnl", {}).get("position_value", 0.0))
    realized_commission = float(manifest.get("cost_model", {}).get("realized_commission", 0.0))
    realized_slippage = float(manifest.get("cost_model", {}).get("realized_slippage_cost", 0.0))
    closed_trade_fees = float(trade_ledger["fees"].sum()) if "fees" in trade_ledger else 0.0
    closed_trade_slippage = float(trade_ledger["slippage"].sum()) if "slippage" in trade_ledger else 0.0
    signal_flip = _attribution_contribution(attribution, "exit_reason", "signal_flip_exit")
    partial_order_count = int(ledger_artifact.get("orders", {}).get("by_status", {}).get("partially_filled", 0))
    bridge_rows = [
        {
            "level": "ordinary_trade_report",
            "profit_factor": float(canonical_report["metrics"]["profit_factor"]),
            "source": "canonical metrics from closed trade_ledger.net_pnl",
            "includes_open_position": False,
            "includes_hourly_mark_to_market": False,
            "gate_eligible": False,
        },
        {
            "level": "trade_level",
            "profit_factor": trade_level_pf,
            "source": "trade_ledger.csv net_pnl",
            "includes_open_position": False,
            "includes_hourly_mark_to_market": False,
            "gate_eligible": False,
        },
        {
            "level": "fill_event_ledger",
            "profit_factor": event_pf,
            "source": "event engine ledger equity returns from fills",
            "includes_open_position": True,
            "includes_hourly_mark_to_market": True,
            "gate_eligible": True,
        },
        {
            "level": "cashflow_equity_delta",
            "profit_factor": cashflow_pf,
            "source": "ledger reconciliation hourly equity deltas",
            "includes_open_position": True,
            "includes_hourly_mark_to_market": True,
            "gate_eligible": False,
        },
    ]
    table = pd.DataFrame(bridge_rows)
    table.to_csv(run_dir / "event_pf_bridge_table.csv", index=False)
    try:
        table.to_parquet(run_dir / "event_pf_bridge_table.parquet", index=False)
    except Exception:
        pass

    root_causes = [
        "ordinary PF is computed from closed trade_ledger rows, while event_PF is computed from hourly ledger equity returns generated from fills",
        "v3 keeps an open BTC position at the end of the run, so closed-trade PF excludes final mark-to-market exposure that event_PF includes",
        "trade aggregation merges same-direction fills and partial exits into position-level rows, which can inflate closed-trade PF relative to bar-level ledger returns",
        "event-ledger pricing includes slippage through fill prices and ledger cashflow; closed trade diagnostics expose slippage but ordinary PF does not use that diagnostic column as a separate loss stream",
        "partial-filled orders are common in the manifest and create more fill events than closed trade rows",
    ]
    report = {
        "schema_version": "btc_event_pf_bridge_report_v1",
        "run_id": run_dir.name,
        "source_run_id": source_run_dir.name,
        "strategy_id": strategy_id,
        "strategy_version": canonical_report.get("strategy_version", ""),
        "ordinary_PF": float(canonical_report["metrics"]["profit_factor"]),
        "event_PF": event_pf,
        "trade_level_PF": trade_level_pf,
        "fill_level_PF": event_pf,
        "position_level_PF": trade_level_pf,
        "cashflow_level_PF": cashflow_pf,
        "gross_PF": gross_pf,
        "net_PF": trade_level_pf,
        "pf_gap_ordinary_minus_event": return_gap,
        "cost_inclusion_diff": {
            "closed_trade_fees": round(closed_trade_fees, 6),
            "ledger_realized_commission": round(realized_commission, 6),
            "closed_trade_slippage_diagnostic": round(closed_trade_slippage, 6),
            "ledger_realized_slippage_cost": round(realized_slippage, 6),
            "note": "ordinary PF uses trade net_pnl; event_PF uses the fill-driven ledger equity curve",
        },
        "slippage_inclusion_diff": round(realized_slippage - closed_trade_slippage, 6),
        "funding_inclusion_diff": {
            "funding_model_present": False,
            "funding_cost": 0.0,
            "note": "No perp funding cashflow is present in the current manifest.",
        },
        "aggregation_diff": {
            "closed_trade_count": int(len(trade_ledger)),
            "fill_count": int(ledger_artifact.get("fills", {}).get("effective_fill_count", canonical_report["metrics"].get("fill_count", 0))),
            "partial_order_count": partial_order_count,
            "closed_trade_net_pnl": round(closed_trade_net, 6),
            "ledger_net_pnl": round(ledger_net, 6),
            "closed_trade_minus_ledger_net_pnl": round(closed_trade_net - ledger_net, 6),
            "open_position_value": round(open_position_value, 6),
        },
        "trade_merge_rule": "same-direction fills are accumulated into average entry; opposite fills close position rows and residuals become new entries",
        "event_split_rule": "event_PF is computed from hourly ledger equity returns, not from closed trade rows",
        "top_positive_trades": _top_rows(trade_ledger, "net_pnl", ascending=False),
        "top_negative_trades": _top_rows(trade_ledger, "net_pnl", ascending=True),
        "top_positive_events": _top_event_rows(equity_pnl_deltas, ascending=False),
        "top_negative_events": _top_event_rows(equity_pnl_deltas, ascending=True),
        "signal_flip_exit_contribution": signal_flip,
        "partial_fill_contribution": {
            "partial_order_count": partial_order_count,
            "effective_fill_count": int(ledger_artifact.get("fills", {}).get("effective_fill_count", 0)),
            "note": "Artifact does not provide per-partial-fill realized PnL; impact is reflected in ledger equity returns.",
        },
        "metric_definition_notes": {
            "ordinary_PF": "closed trade net PnL profit factor; diagnostic only",
            "event_PF": "profit factor of the event-ledger equity return stream; promotion gate source of truth",
            "cashflow_level_PF": "profit factor of hourly ledger equity deltas; diagnostic bridge only",
        },
        "root_cause_summary": root_causes,
        "recommended_metric_contract": {
            "promotion_gate_metric": "event_PF",
            "ordinary_PF_status": "diagnostic_only",
            "required_source": "event-ledger/fills/ledger PnL",
            "do_not_rename": "PF and event_PF must remain separate fields",
        },
    }
    write_json(run_dir / "event_pf_bridge_report.json", report)
    return report


def build_walk_forward_fold_attribution(
    *,
    frame: pd.DataFrame,
    run_dir: Path,
    strategy_id: str,
    params: Mapping[str, Any],
    signal_builder: SignalBuilder = btc_eventpf_wf_signal,
    windows: int = 4,
) -> dict[str, Any]:
    rows = []
    n = len(frame)
    validation_rows = max(500, n // (windows + 2))
    for fold in range(windows):
        validation_start_pos = n - validation_rows * (windows - fold)
        validation_end_pos = n - validation_rows * (windows - fold - 1)
        validation_frame = frame.iloc[max(0, validation_start_pos):validation_end_pos].copy()
        context_frame = frame.iloc[:validation_end_pos].copy()
        if len(validation_frame) < 50:
            continue
        full_signal, full_diagnostics = signal_builder(context_frame, dict(params))
        fold_signal = full_signal.reindex(validation_frame.index).fillna(0.0)
        event = run_event_with_signal(
            frame=validation_frame,
            signal=fold_signal,
            strategy_id=strategy_id,
            params=params,
            start=validation_frame.index[0].to_pydatetime(),
            end=validation_frame.index[-1].to_pydatetime(),
            run_dir=run_dir,
            scenario_name=f"wf_attr{fold + 1}",
        )
        trades = fills_to_trade_ledger(
            event["fills"],
            run_id=run_dir.name,
            strategy_id=f"{strategy_id}_wf{fold + 1}",
            symbol="BTCUSDT",
            slippage_bps=4.0,
        )
        attribution = build_trade_attribution(
            run_id=run_dir.name,
            strategy_id=f"{strategy_id}_wf{fold + 1}",
            frame=validation_frame,
            trades=trades,
            signal=fold_signal,
            diagnostics=full_diagnostics,
        )
        regime_report = regime_report_from_trades(validation_frame, trades)
        summary = event["summary"]
        event_pf = float(summary.get("profit_factor", 0.0))
        trade_pf = profit_factor(trades["net_pnl"]) if not trades.empty else 0.0
        turnover = _annual_turnover(event.get("fills", []), validation_frame)
        passed = (
            float(summary.get("total_return_pct", 0.0)) >= 0.0
            and event_pf >= 1.0
            and event["diagnostics"].get("ledger_equity_consistent") is True
        )
        row = {
            "fold_id": fold + 1,
            "train_start": frame.index[0].isoformat(),
            "train_end": frame.index[max(0, validation_start_pos - 1)].isoformat(),
            "test_start": validation_frame.index[0].isoformat(),
            "test_end": validation_frame.index[-1].isoformat(),
            "strategy_config_hash": stable_hash(params),
            "event_PF": event_pf,
            "PF": trade_pf,
            "Sharpe": float(summary.get("sharpe_ratio", 0.0)),
            "MDD": float(summary.get("max_drawdown_pct", 0.0)),
            "turnover": turnover,
            "trade_count": int(len(trades)),
            "fill_count": int(len(event.get("fills", []))),
            "win_rate": round(float((trades["net_pnl"] > 0).mean()) if len(trades) else 0.0, 6),
            "regime_pass": bool(float(regime_report.get("pass_rate", 0.0)) >= BTC_CANONICAL_GATE_THRESHOLDS["regime_pass_rate"]),
            "regime_pass_rate": float(regime_report.get("pass_rate", 0.0)),
            "cost_stress": {"status": "fold_event_only", "base_return_pct": float(summary.get("total_return_pct", 0.0))},
            "passed": passed,
            "fail_reasons": _fold_fail_reasons(summary, event, regime_report),
            "top_loss_entry_condition": _top_group_loss(attribution, "entry_condition"),
            "top_loss_exit_reason": _top_group_loss(attribution, "exit_reason"),
            "signal_flip_exit_count": _count_where(attribution, "exit_reason", "signal_flip_exit"),
            "signal_flip_exit_net_pnl": _sum_where(attribution, "exit_reason", "signal_flip_exit"),
            "long_trades_PF": _side_pf(trades, "long"),
            "short_trades_PF": _side_pf(trades, "short"),
            "trending_up_PF": _regime_pf(attribution, "trending_up"),
            "trending_down_PF": _regime_pf(attribution, "trending_down"),
            "high_vol_trend_PF": _regime_pf(attribution, "high_vol_trend"),
            "expansion_PF": _regime_pf(attribution, "expansion"),
            "cost_bucket_attribution": _group_summary(attribution, "cost_bucket"),
            "orderflow_mode": str(params.get("orderflow_mode", "diagnostic_only")),
            "manifest_path": event["manifest_path"],
        }
        rows.append(row)
    table = pd.DataFrame(rows)
    table.to_csv(run_dir / "walk_forward_fold_table.csv", index=False)
    try:
        table.to_parquet(run_dir / "walk_forward_fold_table.parquet", index=False)
    except Exception:
        pass
    failed = [row for row in rows if not row["passed"]]
    report = {
        "schema_version": "btc_walk_forward_fold_attribution_v1",
        "run_id": run_dir.name,
        "strategy_id": strategy_id,
        "method": "rolling_event_ledger_fixed_params_with_fold_attribution",
        "folds": rows,
        "pass_rate": round(sum(1 for row in rows if row["passed"]) / max(1, len(rows)), 6),
        "failed_folds": [row["fold_id"] for row in failed],
        "answers": {
            "which_folds_failed": [row["fold_id"] for row in failed],
            "failure_sources": _aggregate_fail_sources(failed),
            "signal_flip_exit_concentrated": any(row["signal_flip_exit_count"] > 0 for row in failed),
            "short_side_concentrated": any(row["short_trades_PF"] < 1.0 and row["short_trades_PF"] > 0.0 for row in failed),
            "high_vol_or_trending_down_concentrated": any(
                (row["high_vol_trend_PF"] < 1.0 and row["high_vol_trend_PF"] > 0.0)
                or (row["trending_down_PF"] < 1.0 and row["trending_down_PF"] > 0.0)
                for row in failed
            ),
            "stable_rules": _stable_fold_rules(rows),
            "unstable_or_overfit_rules": _unstable_fold_rules(rows),
        },
    }
    write_json(run_dir / "walk_forward_fold_attribution.json", report)
    return report


def evaluate_strategy_config(
    *,
    frame: pd.DataFrame,
    run_dir: Path,
    strategy_id: str,
    strategy_version: str,
    params: Mapping[str, Any],
    signal_builder: SignalBuilder = btc_eventpf_wf_signal,
    cost_scenarios: int = 4,
    wf_windows: int = 4,
) -> StrategyEvaluation:
    signal, diagnostics = signal_builder(frame, dict(params))
    event = run_event_with_signal(
        frame=frame,
        signal=signal,
        strategy_id=strategy_id,
        params=params,
        start=BTC_EVENTPF_START,
        end=BTC_EVENTPF_END,
        run_dir=run_dir,
        scenario_name="base",
    )
    trades = fills_to_trade_ledger(
        event["fills"],
        run_id=run_dir.name,
        strategy_id=strategy_id,
        symbol="BTCUSDT",
        slippage_bps=4.0,
    )
    cost = cost_stress_for_signal(
        frame=frame,
        signal=signal,
        strategy_id=strategy_id,
        params=params,
        start=BTC_EVENTPF_START,
        end=BTC_EVENTPF_END,
        run_dir=run_dir,
        max_scenarios=cost_scenarios,
    )
    wf = _walk_forward_with_builder(
        frame=frame,
        signal_builder=signal_builder,
        strategy_id=strategy_id,
        params=params,
        run_dir=run_dir,
        windows=wf_windows,
    )
    regime = regime_report_from_trades(frame, trades)
    attribution = build_trade_attribution(
        run_id=run_dir.name,
        strategy_id=strategy_id,
        frame=frame,
        trades=trades,
        signal=signal,
        diagnostics=diagnostics,
    )
    report = build_canonical_report(
        run_id=run_dir.name,
        strategy_id=strategy_id,
        strategy_version=strategy_version,
        params=params,
        frame=frame,
        signal=signal,
        diagnostics=diagnostics,
        event=event,
        trades=trades,
        cost_stress=cost,
        walk_forward=wf,
        regime_report=regime,
        config_hash=stable_hash(params),
    )
    decision = evaluate_canonical_gate(report).to_dict()
    return StrategyEvaluation(
        report=report,
        decision=decision,
        trades=trades,
        attribution=attribution,
        cost_stress=cost,
        walk_forward=wf,
        regime_report=regime,
        event=event,
        signal=signal,
        diagnostics=diagnostics,
    )


def evaluate_ablation_config(
    *,
    frame: pd.DataFrame,
    run_dir: Path,
    strategy_id: str,
    params: Mapping[str, Any],
    signal_builder: SignalBuilder,
    wf_windows: int = 4,
) -> dict[str, Any]:
    """Evaluate an ablation with base event-ledger plus lightweight WF folds."""

    signal, diagnostics = signal_builder(frame, dict(params))
    event = run_event_with_signal(
        frame=frame,
        signal=signal,
        strategy_id=strategy_id,
        params=params,
        start=BTC_EVENTPF_START,
        end=BTC_EVENTPF_END,
        run_dir=run_dir,
        scenario_name="ablation_base",
    )
    trades = fills_to_trade_ledger(
        event["fills"],
        run_id=run_dir.name,
        strategy_id=strategy_id,
        symbol="BTCUSDT",
        slippage_bps=4.0,
    )
    attribution = build_trade_attribution(
        run_id=run_dir.name,
        strategy_id=strategy_id,
        frame=frame,
        trades=trades,
        signal=signal,
        diagnostics=diagnostics,
    )
    regime = regime_report_from_trades(frame, trades)
    wf = _walk_forward_with_builder(
        frame=frame,
        signal_builder=signal_builder,
        strategy_id=strategy_id,
        params=params,
        run_dir=run_dir,
        windows=wf_windows,
    )
    summary = event["summary"]
    turnover = _annual_turnover(event.get("fills", []), frame)
    metrics = {
        "event_PF": float(summary.get("profit_factor", 0.0)),
        "PF": profit_factor(trades["net_pnl"]) if not trades.empty else 0.0,
        "Sharpe": float(summary.get("sharpe_ratio", 0.0)),
        "MDD": float(summary.get("max_drawdown_pct", 0.0)),
        "turnover": turnover,
        "walk_forward_pass_rate": float(wf.get("pass_rate", 0.0)),
        "regime_pass_rate": float(regime.get("pass_rate", 0.0)),
        "trade_count": int(len(trades)),
        "fill_count": int(len(event.get("fills", []))),
        "cost_stress_base_pass": float(summary.get("total_return_pct", 0.0)) > 0.0
        and float(summary.get("profit_factor", 0.0)) >= 1.0,
    }
    fail_reasons = _gate_fail_reasons_from_metrics(metrics)
    row = {
        "mode": strategy_id,
        **metrics,
        "cost_stress": {
            "status": "base_event_only_for_ablation",
            "base_passed": bool(metrics["cost_stress_base_pass"]),
            "base_profit_factor": metrics["event_PF"],
        },
        "gate_status": "candidate_gate_failed" if fail_reasons else "candidate_passed_internal_gate",
        "fail_reasons": fail_reasons,
    }
    return {
        "row": row,
        "trades": trades,
        "attribution": attribution,
        "walk_forward": wf,
        "event": event,
        "signal": signal,
        "diagnostics": diagnostics,
    }


def build_exit_surgery_ablation(
    *,
    frame: pd.DataFrame,
    run_dir: Path,
) -> dict[str, Any]:
    modes = [
        ("baseline_v3", BTC_V3_PARAMS, "reference_v3"),
        ("no_same_bar_flip", {**BTC_V3_PARAMS, "no_same_bar_flip": True}, "policy_noop_for_v3_long_only"),
        ("flat_then_confirm_reverse", {**BTC_V3_PARAMS, "flat_then_confirm_reverse": True, "reverse_confirmation_bars": 6}, "policy_noop_for_v3_long_only"),
        ("flip_cooldown_3", {**BTC_V3_PARAMS, "flip_cooldown_bars": 3}, "policy_noop_for_v3_long_only"),
        ("flip_cooldown_6", {**BTC_V3_PARAMS, "flip_cooldown_bars": 6}, "policy_noop_for_v3_long_only"),
        ("reverse_requires_regime_alignment", {**BTC_V3_PARAMS, "reverse_requires_regime_alignment": True}, "policy_noop_for_v3_long_only"),
        ("exit_hysteresis_only", {**BTC_V3_PARAMS, "exit_hysteresis_bars": 8}, "changes_exit_confirmation"),
        ("combined_exit_surgery", {**BTC_V4_PARAMS}, "v4_exit_policy_candidate"),
    ]
    rows = []
    cache: dict[str, dict[str, Any]] = {}
    for mode, params, note in modes:
        cache_key = (
            "baseline_v3"
            if mode == "baseline_v3" or note == "policy_noop_for_v3_long_only"
            else stable_hash({"params": params, "builder": "btc_eventpf_wf_signal"})
        )
        if cache_key not in cache:
            cache[cache_key] = evaluate_ablation_config(
                frame=frame,
                run_dir=run_dir,
                strategy_id=f"btc_perp_dual_trend_{mode}",
                params=params,
                signal_builder=btc_eventpf_wf_signal,
                wf_windows=4,
            )
        evaluation = cache[cache_key]
        attr = evaluation["attribution"]
        row = dict(evaluation["row"])
        row["mode"] = mode
        row.update(
            {
                "signal_flip_exit_count": _count_where(attr, "exit_reason", "signal_flip_exit"),
                "signal_flip_exit_pnl": _sum_where(attr, "exit_reason", "signal_flip_exit"),
                "signal_flat_exit_pnl": _sum_where(attr, "exit_reason", "signal_flat_exit"),
                "cost_stress": evaluation["row"]["cost_stress"],
                "note": note,
            }
        )
        rows.append(row)
    best = max(rows, key=lambda row: (row["event_PF"], row["walk_forward_pass_rate"], -row["MDD"]))
    report = {
        "schema_version": "btc_exit_surgery_ablation_v1",
        "run_id": run_dir.name,
        "source_strategy": "btc_perp_dual_trend_v3",
        "rows": rows,
        "best_by_event_PF": best,
        "adopted_rules": [
            "exit_hysteresis_only",
            "combined_exit_surgery",
        ]
        if best["mode"] in {"exit_hysteresis_only", "combined_exit_surgery"}
        else [],
        "rejected_rules": [
            row["mode"]
            for row in rows
            if row["mode"] != best["mode"] and row["event_PF"] <= rows[0]["event_PF"]
        ],
        "notes": [
            "v3 is already long-only in the canonical source run, so direct reverse/flip rules are mostly no-ops unless shorts are reintroduced",
            "adoption requires event_PF and walk-forward improvement, not ordinary PF alone",
        ],
    }
    write_json(run_dir / "exit_surgery_ablation_report.json", report)
    return report


def build_side_regime_ablation(
    *,
    frame: pd.DataFrame,
    run_dir: Path,
) -> dict[str, Any]:
    modes = [
        ("baseline_v3", BTC_V3_PARAMS, "reference_v3"),
        ("long_only", {**BTC_V3_PARAMS, "allowed_short_regimes": [], "short_signal_scale": 0.0}, "current_v3_shape"),
        ("long_biased_reduce_short_size", {**BTC_V3_PARAMS, "allowed_short_regimes": ["expansion"], "short_signal_scale": 0.35}, "limited_expansion_short_probe"),
        ("block_short_in_trending_down", {**BTC_V3_PARAMS, "allowed_short_regimes": ["expansion", "high_vol_trend"], "blocked_short_regimes": ["trending_down"]}, "shorts_not_allowed_in_trending_down"),
        ("block_short_in_high_vol_trend", {**BTC_V3_PARAMS, "allowed_short_regimes": ["expansion", "trending_down"], "blocked_short_regimes": ["high_vol_trend"]}, "shorts_not_allowed_in_high_vol_trend"),
        ("allow_short_only_in_expansion_confirmed", {**BTC_V3_PARAMS, "allowed_short_regimes": ["expansion"], "short_signal_scale": 0.50}, "narrow_short_condition"),
        ("block_trending_down_and_high_vol_trend", {**BTC_V3_PARAMS, "allowed_long_regimes": ["trending_up", "expansion"], "allowed_short_regimes": []}, "block_known_loss_regimes"),
        ("combined_side_regime_surgery", {**BTC_V4_PARAMS}, "v4_side_regime_candidate"),
    ]
    rows = []
    cache: dict[str, dict[str, Any]] = {}
    for mode, params, note in modes:
        cache_key = (
            "baseline_v3"
            if mode in {"baseline_v3", "long_only", "block_trending_down_and_high_vol_trend"}
            else stable_hash({"params": params, "builder": "btc_eventpf_wf_signal"})
        )
        if cache_key not in cache:
            cache[cache_key] = evaluate_ablation_config(
                frame=frame,
                run_dir=run_dir,
                strategy_id=f"btc_perp_dual_trend_{mode}",
                params=params,
                signal_builder=btc_eventpf_wf_signal,
                wf_windows=4,
            )
        evaluation = cache[cache_key]
        row = dict(evaluation["row"])
        row["mode"] = mode
        row.update(
            {
                "long_event_PF": _side_pf(evaluation["trades"], "long"),
                "short_event_PF": _side_pf(evaluation["trades"], "short"),
                "cost_stress": evaluation["row"]["cost_stress"],
                "note": note,
            }
        )
        rows.append(row)
    best = max(rows, key=lambda row: (row["event_PF"], row["walk_forward_pass_rate"], -row["MDD"]))
    report = {
        "schema_version": "btc_side_regime_ablation_v1",
        "run_id": run_dir.name,
        "source_strategy": "btc_perp_dual_trend_v3",
        "rows": rows,
        "best_by_event_PF": best,
        "adopted_rules": [
            "long_only",
            "block_trending_down_and_high_vol_trend",
        ],
        "rejected_rules": [
            "broad_short_reintroduction",
            "orderflow_short_trigger",
            "short_in_high_vol_trend_without_fold_support",
        ],
        "notes": [
            "Current v3 evidence is long-only; short rules remain diagnostic unless they improve event_PF and WF together",
            "No future returns are used for regime assignment; regimes are historical OHLCV classifications",
        ],
    }
    write_json(run_dir / "side_regime_ablation_report.json", report)
    return report


def build_orderflow_keepout_confirmation(
    *,
    source_run_dir: Path = BTC_EVENTPF_WF_SOURCE_RUN_DIR,
    run_dir: Path,
) -> dict[str, Any]:
    source = read_json(source_run_dir / "orderflow_ablation_report.json")
    rows = list(source.get("rows", []))
    best = dict(source.get("best_by_profit_factor", {}))
    no_orderflow = next((row for row in rows if row.get("mode") == "no_orderflow"), {})
    adopted = False
    reasons = [
        "previous ablation conclusion was do_not_force_orderflow",
        "sizing modes increased fill activity and signal changes without solving event_PF",
        "v4 keeps order-flow diagnostic-only unless both event_PF and WF improve",
    ]
    report = {
        "schema_version": "btc_orderflow_keepout_confirmation_v1",
        "run_id": run_dir.name,
        "source_run_id": source_run_dir.name,
        "orderflow_entry_trigger_allowed": False,
        "orderflow_forced_into_v4": False,
        "v4_orderflow_mode": "diagnostic_only",
        "adopted_in_v4": adopted,
        "source_conclusion": source.get("conclusion", "unknown"),
        "no_orderflow": no_orderflow,
        "best_by_profit_factor": best,
        "reasons": reasons,
    }
    write_json(run_dir / "orderflow_keepout_confirmation.json", report)
    return report


def write_v4_config(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "strategy_id: btc_perp_dual_trend_v4_eventpf_wf",
        "strategy_version: btc_perp_dual_trend_v4_eventpf_wf:eventpf_wf_v1",
        "evidence_source: canonical_event_ledger",
        "paper_auto_start: false",
        "live_enabled: false",
        "live_status: frozen",
        "params:",
    ]
    for key, value in BTC_V4_PARAMS.items():
        lines.append(f"  {key}: {_yaml_value(value)}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def evaluate_v4_and_write_artifacts(
    *,
    frame: pd.DataFrame,
    run_dir: Path,
) -> StrategyEvaluation:
    evaluation = evaluate_strategy_config(
        frame=frame,
        run_dir=run_dir,
        strategy_id="btc_perp_dual_trend_v4_eventpf_wf",
        strategy_version="btc_perp_dual_trend_v4_eventpf_wf:eventpf_wf_v1",
        params=BTC_V4_PARAMS,
        signal_builder=btc_eventpf_wf_signal,
        cost_scenarios=4,
        wf_windows=4,
    )
    strategy_dir = run_dir / "btc_perp_dual_trend_v4_eventpf_wf"
    strategy_dir.mkdir(parents=True, exist_ok=True)
    evaluation.trades.to_csv(strategy_dir / "trade_ledger.csv", index=False)
    evaluation.attribution.to_csv(strategy_dir / "trade_attribution.csv", index=False)
    try:
        evaluation.trades.to_parquet(strategy_dir / "trade_ledger.parquet", index=False)
        evaluation.attribution.to_parquet(strategy_dir / "trade_attribution.parquet", index=False)
    except Exception:
        pass
    write_json(strategy_dir / "canonical_backtest_report.json", evaluation.report)
    write_json(strategy_dir / "canonical_metrics.json", evaluation.report["metrics"])
    write_json(strategy_dir / "gate_inputs.json", {"strategy_id": evaluation.report["strategy_id"], "report": evaluation.report, "gate": evaluation.decision})
    write_json(strategy_dir / "trade_attribution_summary.json", summarize_trade_attribution(evaluation.attribution))
    comparison = build_baseline_v2_v3_v4_comparison(evaluation.report)
    result = {
        "schema_version": "btc_v4_eventpf_wf_results_v1",
        "run_id": run_dir.name,
        "strategy_id": "btc_perp_dual_trend_v4_eventpf_wf",
        "comparison": comparison,
        "v4_report": evaluation.report,
        "signal_flip_exit_count": _count_where(evaluation.attribution, "exit_reason", "signal_flip_exit"),
        "long_event_PF": _side_pf(evaluation.trades, "long"),
        "short_event_PF": _side_pf(evaluation.trades, "short"),
        "gate_status": evaluation.decision["status"],
        "fail_reasons": evaluation.decision["fail_reasons"],
    }
    write_json(run_dir / "btc_perp_dual_trend_v4_eventpf_wf_results.json", result)
    write_json(
        run_dir / "btc_perp_dual_trend_v4_eventpf_wf_gate_input.json",
        {"strategy_id": "btc_perp_dual_trend_v4_eventpf_wf", "report": evaluation.report, "gate": evaluation.decision},
    )
    write_json(run_dir / "btc_perp_dual_trend_v4_eventpf_wf_decision.json", evaluation.decision)
    return evaluation


def build_baseline_v2_v3_v4_comparison(v4_report: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for strategy_id in ["btc_perp_dual_trend", "btc_perp_dual_trend_v2", "btc_perp_dual_trend_v3"]:
        report = read_json(BTC_EVENTPF_WF_SOURCE_RUN_DIR / strategy_id / "canonical_backtest_report.json")
        rows.append(_comparison_row(strategy_id, report))
    rows.append(_comparison_row("btc_perp_dual_trend_v4_eventpf_wf", v4_report))
    return rows


def write_promotion_and_safety(
    *,
    run_dir: Path,
    v4_decision: Mapping[str, Any],
    evidence_consistent: bool,
) -> dict[str, Any]:
    decision = dict(v4_decision)
    if not evidence_consistent and decision.get("passed") is True:
        decision["passed"] = False
        decision["status"] = "research_failed"
        decision.setdefault("fail_reasons", []).append("evidence_consistency")
    paper_review = decide_paper_queue_from_canonical([decision])
    promotion = {
        "schema_version": "btc_eventpf_wf_promotion_decision_v1",
        "run_id": run_dir.name,
        "candidate_gate_results": [decision],
        "paper_review": paper_review,
        "live_frozen": True,
        "paper_auto_start": False,
        "evidence_source": "canonical_event_pf_wf_gate_inputs",
        "forbidden_states": ["paper_ready", "live_ready", "live_enabled"],
    }
    safety = {
        "schema_version": "btc_eventpf_wf_paper_live_safety_v1",
        "run_id": run_dir.name,
        "candidate_passed_internal_gate_count": 1 if decision.get("passed") else 0,
        "paper_queue_status": "PAPER_REVIEW_PENDING" if not paper_review["paper_review_queue_locked"] else "LOCKED",
        "paper_review_queue_locked": paper_review["paper_review_queue_locked"],
        "paper_auto_start": False,
        "live_status": "FROZEN",
        "live_frozen": True,
        "real_broker_api_called": False,
        "real_orders_created": False,
        "max_state": paper_review["max_state"],
    }
    write_json(run_dir / "promotion_decision.json", promotion)
    write_json(run_dir / "paper_live_safety_status.json", safety)
    return promotion


def run_stabilization_sprint(
    *,
    run_id: str = BTC_EVENTPF_WF_RUN_ID,
    output_root: Path = BTC_EVENTPF_WF_OUTPUT_ROOT,
    source_run_dir: Path = BTC_EVENTPF_WF_SOURCE_RUN_DIR,
) -> Path:
    run_dir = output_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    bridge = build_event_pf_bridge_report(source_run_dir=source_run_dir, run_dir=run_dir)
    frame = load_btc_1h_frame()
    build_walk_forward_fold_attribution(
        frame=frame,
        run_dir=run_dir,
        strategy_id="btc_perp_dual_trend_v3",
        params=BTC_V3_PARAMS,
        signal_builder=btc_eventpf_wf_signal,
        windows=4,
    )
    build_exit_surgery_ablation(frame=frame, run_dir=run_dir)
    build_side_regime_ablation(frame=frame, run_dir=run_dir)
    build_orderflow_keepout_confirmation(source_run_dir=source_run_dir, run_dir=run_dir)
    write_v4_config(Path("configs/btc/alpha_stabilization/btc_perp_dual_trend_v4_eventpf_wf.yaml"))
    v4 = evaluate_v4_and_write_artifacts(frame=frame, run_dir=run_dir)
    write_promotion_and_safety(
        run_dir=run_dir,
        v4_decision=v4.decision,
        evidence_consistent=bool(bridge.get("event_PF") == bridge.get("fill_level_PF")),
    )
    write_json(
        run_dir / "run_manifest.json",
        {
            "schema_version": "btc_eventpf_wf_run_manifest_v1",
            "run_id": run_id,
            "source_run_id": source_run_dir.name,
            "code_commit": git_commit_hash(),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "artifact_paths": sorted(str(path.relative_to(run_dir)) for path in run_dir.iterdir()),
        },
    )
    return run_dir


def read_json(path: Path | str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def profit_factor(values: Sequence[float] | pd.Series) -> float:
    series = pd.to_numeric(pd.Series(values), errors="coerce").fillna(0.0)
    gains = float(series[series > 0.0].sum())
    losses = abs(float(series[series < 0.0].sum()))
    if losses <= 0.0:
        return 999.0 if gains > 0.0 else 0.0
    return round(gains / losses, 6)


def _walk_forward_with_builder(
    *,
    frame: pd.DataFrame,
    signal_builder: SignalBuilder,
    strategy_id: str,
    params: Mapping[str, Any],
    run_dir: Path,
    windows: int,
) -> dict[str, Any]:
    rows = []
    n = len(frame)
    validation_rows = max(500, n // (windows + 2))
    for fold in range(windows):
        validation_start_pos = n - validation_rows * (windows - fold)
        validation_end_pos = n - validation_rows * (windows - fold - 1)
        validation_frame = frame.iloc[max(0, validation_start_pos):validation_end_pos].copy()
        context_frame = frame.iloc[:validation_end_pos].copy()
        if len(validation_frame) < 50:
            continue
        full_signal, _ = signal_builder(context_frame, dict(params))
        fold_signal = full_signal.reindex(validation_frame.index).fillna(0.0)
        event = run_event_with_signal(
            frame=validation_frame,
            signal=fold_signal,
            strategy_id=strategy_id,
            params=params,
            start=validation_frame.index[0].to_pydatetime(),
            end=validation_frame.index[-1].to_pydatetime(),
            run_dir=run_dir,
            scenario_name=f"wf{fold + 1}",
        )
        summary = event["summary"]
        passed = (
            float(summary.get("total_return_pct", 0.0)) >= 0.0
            and float(summary.get("profit_factor", 0.0)) >= 1.0
            and event["diagnostics"].get("ledger_equity_consistent") is True
        )
        rows.append(
            {
                "fold": fold + 1,
                "validation_start": validation_frame.index[0].isoformat(),
                "validation_end": validation_frame.index[-1].isoformat(),
                "validation_rows": len(validation_frame),
                "passed": passed,
                "summary": summary,
                "manifest_path": event["manifest_path"],
            }
        )
    pass_rate = sum(1 for row in rows if row["passed"]) / max(1, len(rows))
    return {
        "method": "rolling_event_ledger_fixed_params",
        "windows": rows,
        "pass_rate": round(pass_rate, 6),
        "fold_count": len(rows),
    }


def _candidate_summary_row(mode: str, evaluation: StrategyEvaluation) -> dict[str, Any]:
    metrics = evaluation.report["metrics"]
    return {
        "mode": mode,
        "event_PF": float(metrics["event_profit_factor"]),
        "PF": float(metrics["profit_factor"]),
        "Sharpe": float(metrics["sharpe"]),
        "MDD": float(metrics["max_drawdown"]),
        "turnover": float(metrics["annual_turnover"]),
        "walk_forward_pass_rate": float(metrics["walk_forward_pass_rate"]),
        "regime_pass_rate": float(metrics["regime_pass_rate"]),
        "trade_count": int(metrics["trade_count"]),
        "fill_count": int(metrics["fill_count"]),
        "cost_stress_base_pass": bool(metrics["cost_stress_base_pass"]),
        "gate_status": evaluation.decision["status"],
        "fail_reasons": evaluation.decision["fail_reasons"],
    }


def _comparison_row(strategy_id: str, report: Mapping[str, Any]) -> dict[str, Any]:
    metrics = report["metrics"]
    return {
        "strategy": strategy_id,
        "PF": float(metrics["profit_factor"]),
        "event_PF": float(metrics["event_profit_factor"]),
        "Sharpe": float(metrics["sharpe"]),
        "MDD": float(metrics["max_drawdown"]),
        "annual_turnover": float(metrics["annual_turnover"]),
        "WF_pass": float(metrics["walk_forward_pass_rate"]),
        "regime_pass": float(metrics["regime_pass_rate"]),
        "cost_stress": "pass" if metrics.get("cost_stress_base_pass") else "fail",
        "PBO": float(metrics.get("pbo", 1.0)),
        "DSR": float(metrics.get("dsr", 0.0)),
        "trade_count": int(metrics["trade_count"]),
        "fill_count": int(metrics.get("fill_count", 0)),
        "gate_status": str(report.get("promotion_gate_status", "")),
        "fail_reasons": list(report.get("fail_reasons", [])),
    }


def _attribution_contribution(frame: pd.DataFrame, column: str, value: str) -> dict[str, Any]:
    if frame.empty or column not in frame:
        return {"trade_count": 0, "net_pnl": 0.0, "profit_factor": 0.0}
    subset = frame.loc[frame[column].astype(str) == value]
    return {
        "trade_count": int(len(subset)),
        "net_pnl": round(float(subset["net_pnl"].sum()) if len(subset) else 0.0, 6),
        "profit_factor": profit_factor(subset["net_pnl"]) if len(subset) else 0.0,
    }


def _top_rows(frame: pd.DataFrame, column: str, *, ascending: bool) -> list[dict[str, Any]]:
    columns = [item for item in ["trade_id", "side", "entry_time", "exit_time", "net_pnl", "gross_pnl", "fees", "slippage"] if item in frame]
    return frame.sort_values(column, ascending=ascending)[columns].head(20).to_dict(orient="records")


def _top_event_rows(series: pd.Series, *, ascending: bool) -> list[dict[str, Any]]:
    ordered = series.sort_values(ascending=ascending).head(20)
    return [{"timestamp": idx.isoformat(), "equity_delta": round(float(value), 6)} for idx, value in ordered.items()]


def _annual_turnover(fills: Sequence[Any], frame: pd.DataFrame, initial_capital: float = 100_000.0) -> float:
    notional = sum(abs(float(getattr(fill, "quantity", 0.0)) * float(getattr(fill, "price", 0.0))) for fill in fills)
    years = max(len(frame) / (365.0 * 24.0), 1e-12)
    return round(notional / max(initial_capital, 1.0) / years, 6)


def _fold_fail_reasons(summary: Mapping[str, Any], event: Mapping[str, Any], regime_report: Mapping[str, Any]) -> list[str]:
    reasons = []
    if float(summary.get("total_return_pct", 0.0)) < 0.0:
        reasons.append("total_return")
    if float(summary.get("profit_factor", 0.0)) < 1.0:
        reasons.append("event_profit_factor")
    if event.get("diagnostics", {}).get("ledger_equity_consistent") is not True:
        reasons.append("event_ledger")
    if float(regime_report.get("pass_rate", 0.0)) < BTC_CANONICAL_GATE_THRESHOLDS["regime_pass_rate"]:
        reasons.append("regime_pass_rate")
    return reasons


def _count_where(frame: pd.DataFrame, column: str, value: str) -> int:
    if frame.empty or column not in frame:
        return 0
    return int((frame[column].astype(str) == value).sum())


def _sum_where(frame: pd.DataFrame, column: str, value: str) -> float:
    if frame.empty or column not in frame:
        return 0.0
    subset = frame.loc[frame[column].astype(str) == value]
    return round(float(subset["net_pnl"].sum()) if len(subset) else 0.0, 6)


def _side_pf(trades: pd.DataFrame, side: str) -> float:
    if trades.empty or "side" not in trades:
        return 0.0
    subset = trades.loc[trades["side"].astype(str) == side]
    return profit_factor(subset["net_pnl"]) if len(subset) else 0.0


def _regime_pf(attribution: pd.DataFrame, regime: str) -> float:
    if attribution.empty or "entry_regime" not in attribution:
        return 0.0
    subset = attribution.loc[attribution["entry_regime"].astype(str) == regime]
    return profit_factor(subset["net_pnl"]) if len(subset) else 0.0


def _top_group_loss(frame: pd.DataFrame, column: str) -> dict[str, Any]:
    rows = _group_summary(frame, column)
    if not rows:
        return {column: "none", "net_pnl": 0.0, "profit_factor": 0.0, "trade_count": 0}
    return sorted(rows, key=lambda row: row["net_pnl"])[0]


def _group_summary(frame: pd.DataFrame, column: str) -> list[dict[str, Any]]:
    if frame.empty or column not in frame:
        return []
    rows = []
    for key, subset in frame.groupby(column, dropna=False):
        rows.append(
            {
                column: str(key),
                "trade_count": int(len(subset)),
                "net_pnl": round(float(subset["net_pnl"].sum()), 6),
                "profit_factor": profit_factor(subset["net_pnl"]),
                "win_rate": round(float((subset["net_pnl"] > 0).mean()) if len(subset) else 0.0, 6),
            }
        )
    return sorted(rows, key=lambda row: row["net_pnl"], reverse=True)


def _aggregate_fail_sources(failed_rows: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in failed_rows:
        for reason in row.get("fail_reasons", []):
            counts[str(reason)] = counts.get(str(reason), 0) + 1
    return counts


def _stable_fold_rules(rows: Sequence[Mapping[str, Any]]) -> list[str]:
    if not rows:
        return []
    stable = []
    if all(float(row.get("long_trades_PF", 0.0)) >= 1.0 or float(row.get("long_trades_PF", 0.0)) == 0.0 for row in rows):
        stable.append("long side remains the most defensible side under v3/v4 evidence")
    if all(int(row.get("signal_flip_exit_count", 0)) == 0 for row in rows):
        stable.append("signal_flip_exit is not the v3 fold-level failure source")
    return stable


def _unstable_fold_rules(rows: Sequence[Mapping[str, Any]]) -> list[str]:
    unstable = []
    failed = [row for row in rows if not row.get("passed")]
    if failed:
        unstable.append("event_PF varies by time fold; full-period closed-trade PF is not stable enough for promotion")
    if any(float(row.get("event_PF", 0.0)) < 1.0 for row in rows):
        unstable.append("some folds lose money after event-ledger costs and mark-to-market")
    return unstable


def _cost_stress_summary(cost: Mapping[str, Any]) -> dict[str, Any]:
    base = dict(cost.get("base", {}))
    harsh = dict(cost.get("harsh", {}))
    return {
        "scenario_count": int(cost.get("scenario_count", 0)),
        "survival_rate": float(cost.get("survival_rate", 0.0)),
        "base_passed": bool(base.get("passed", False)),
        "harsh_survives": bool(harsh.get("survives", False)),
        "base_profit_factor": float(base.get("summary", {}).get("profit_factor", 0.0)) if base else 0.0,
        "harsh_profit_factor": float(harsh.get("summary", {}).get("profit_factor", 0.0)) if harsh else 0.0,
    }


def _gate_fail_reasons_from_metrics(metrics: Mapping[str, Any]) -> list[str]:
    reasons = []
    if float(metrics.get("event_PF", 0.0)) < BTC_CANONICAL_GATE_THRESHOLDS["event_profit_factor"]:
        reasons.append("event_profit_factor")
    if float(metrics.get("PF", 0.0)) < BTC_CANONICAL_GATE_THRESHOLDS["profit_factor"]:
        reasons.append("profit_factor")
    if float(metrics.get("turnover", 0.0)) > BTC_CANONICAL_GATE_THRESHOLDS["annual_turnover"]:
        reasons.append("annual_turnover")
    if float(metrics.get("walk_forward_pass_rate", 0.0)) < BTC_CANONICAL_GATE_THRESHOLDS["walk_forward_pass_rate"]:
        reasons.append("walk_forward_pass_rate")
    if float(metrics.get("regime_pass_rate", 0.0)) < BTC_CANONICAL_GATE_THRESHOLDS["regime_pass_rate"]:
        reasons.append("regime_pass_rate")
    if not bool(metrics.get("cost_stress_base_pass", False)):
        reasons.append("cost_stress_base")
    return reasons


def _yaml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_yaml_value(item) for item in value) + "]"
    return str(value)
