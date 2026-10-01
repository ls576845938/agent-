#!/usr/bin/env python3
"""Build a BTC 5m paper-validation evaluation report."""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import pandas as pd
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from quant_us.research.btc_intraday_short_cycle_event_ledger import (
    DEFAULT_PARAMS,
    DRIFT_GUARDED_ENTRY_FILTER,
    DRIFT_GUARDED_VARIANT_ID,
    FAMILY_ID,
    apply_repaired_entry_filter,
    pullback_reclaim_intraday_signal,
)
from scripts.run_btc_paper_validation import _load_bundle_frame


SCHEMA_VERSION = "btc_paper_validation_evaluation_v1"
SYMBOL = "BTCUSDT"
DEFAULT_CONFIG = Path("configs/data/btc_perpetual_sources.yaml")
DEFAULT_LEDGER_ROOT = Path("data/paper_ledger/btc_5m")
DEFAULT_BACKFILL_REPORT = Path("artifacts/btc_paper_readiness/latest/btc_paper_validation_backfill_report.json")
DEFAULT_OUTPUT = Path("artifacts/btc_paper_readiness/latest/btc_paper_validation_evaluation_report.json")
DEFAULT_MARKDOWN_OUTPUT = Path("../学习资料/量化交易业务闭环/系统评估/BTC 5m纸盘验证评估报告.md")


def build_btc_paper_validation_evaluation_report(
    *,
    repo_root: Path | None = None,
    ledger_root: Path = DEFAULT_LEDGER_ROOT,
    config_path: Path = DEFAULT_CONFIG,
    bundle_dir: Path | None = None,
    backfill_report: Path = DEFAULT_BACKFILL_REPORT,
    output: Path = DEFAULT_OUTPUT,
    markdown_output: Path = DEFAULT_MARKDOWN_OUTPUT,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at or _utc_z_now()
    ledger = _resolve(root, ledger_root)
    config = _resolve(root, config_path)
    selected_bundle = _resolve(root, bundle_dir) if bundle_dir else _selected_bundle_dir(root, config)
    backfill_path = _resolve(root, backfill_report)
    output_path = _resolve(root, output)
    markdown_path = _resolve(root, markdown_output)

    state = _read_json(ledger / "validation_state.json")
    backfill = _read_json(backfill_path)
    daily = [_mapping(row) for row in state.get("daily_results", []) if isinstance(row, Mapping)]
    fills = [_mapping(row) for row in _read_jsonl(ledger / "fills.jsonl")]
    snapshots = [_mapping(row) for row in _read_jsonl(ledger / "portfolio_snapshots.jsonl")]
    frame = _load_bundle_frame(selected_bundle, interval="5m")
    try:
        context = _load_bundle_frame(selected_bundle, interval="15m")
    except Exception:
        context = None

    metrics = _paper_metrics(state=state, backfill=backfill, daily=daily, fills=fills, snapshots=snapshots)
    strategy = _strategy_diagnostics(
        frame=frame,
        context=context,
        evaluation_start=str(daily[0].get("start", "")) if daily else "",
        evaluation_end=str(daily[-1].get("end", "")) if daily else "",
        evaluation_windows=[(str(row.get("start", "")), str(row.get("end", ""))) for row in daily],
    )
    trade_ledger = _trade_ledger(fills)
    conclusion = _conclusion(metrics=metrics, strategy=strategy)
    high_frequency_fit = _high_frequency_fit(metrics=metrics, strategy=strategy)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated,
        "asset": "btc",
        "symbol": SYMBOL,
        "interval": "5m",
        "ledger_root": _relpath(ledger, root),
        "bundle_dir": _relpath(selected_bundle, root),
        "backfill_report": _relpath(backfill_path, root),
        "status": _report_status(metrics=metrics, high_frequency_fit=high_frequency_fit),
        "metrics": metrics,
        "strategy_diagnostics": strategy,
        "high_frequency_fit": high_frequency_fit,
        "trade_ledger": trade_ledger,
        "conclusion": conclusion,
    }
    _write_json(output_path, payload)
    _write_text(markdown_path, _markdown(payload))
    return payload


def _paper_metrics(
    *,
    state: Mapping[str, Any],
    backfill: Mapping[str, Any],
    daily: list[Mapping[str, Any]],
    fills: list[Mapping[str, Any]],
    snapshots: list[Mapping[str, Any]],
) -> dict[str, Any]:
    initial = _float_or(state.get("initial_capital"), 0.0)
    final = _float_or(daily[-1].get("final_equity") if daily else None, initial)
    returns = ((final / initial) - 1.0) * 100.0 if initial > 0 else 0.0
    equity = [_float_or(row.get("equity"), 0.0) for row in snapshots if _float_or(row.get("equity"), 0.0) > 0]
    max_dd = _max_drawdown_pct(equity)
    trade_days = [row for row in daily if int(row.get("fills", 0) or 0) > 0]
    order_days = [row for row in daily if int(row.get("orders", 0) or 0) > 0]
    signal_days = [row for row in daily if int(row.get("signals", 0) or 0) > 0]
    no_trade_days = [row for row in daily if int(row.get("fills", 0) or 0) == 0]
    no_signal_days = [row for row in daily if int(row.get("signals", 0) or 0) == 0]
    monitoring_summary = _mapping(backfill.get("monitoring_summary"))
    return {
        "system_passed": (
            str(backfill.get("status", "")) == "PASS"
            and bool(monitoring_summary.get("all_equity_consistent", False))
            and bool(monitoring_summary.get("all_reconciliation_passed", False))
            and int(monitoring_summary.get("total_rejected", 0) or 0) == 0
        ),
        "days_completed": int(state.get("days_completed", len(daily)) or 0),
        "consecutive_clean_days": int(state.get("consecutive_clean_days", 0) or 0),
        "initial_capital": round(initial, 6),
        "final_equity": round(final, 6),
        "total_return_pct": round(returns, 6),
        "max_drawdown_pct": round(max_dd, 6),
        "signal_days": len(signal_days),
        "order_days": len(order_days),
        "trade_days": len(trade_days),
        "no_signal_days": len(no_signal_days),
        "no_trade_days": len(no_trade_days),
        "max_consecutive_no_trade_days": _max_consecutive_days(daily, lambda row: int(row.get("fills", 0) or 0) == 0),
        "total_signals": sum(int(row.get("signals", 0) or 0) for row in daily),
        "total_orders": sum(int(row.get("orders", 0) or 0) for row in daily),
        "total_fills": sum(int(row.get("fills", 0) or 0) for row in daily),
        "total_rejected": sum(int(row.get("rejected", 0) or 0) for row in daily),
        "total_fees": round(sum(float(row.get("fees", 0.0) or 0.0) for row in daily), 6),
        "ledger_fill_rows": len(fills),
        "snapshot_count": len(snapshots),
        "trade_days_detail": [
            {
                "start": str(row.get("start", "")),
                "end": str(row.get("end", "")),
                "signals": int(row.get("signals", 0) or 0),
                "orders": int(row.get("orders", 0) or 0),
                "fills": int(row.get("fills", 0) or 0),
                "fees": round(float(row.get("fees", 0.0) or 0.0), 6),
                "final_equity": round(float(row.get("final_equity", 0.0) or 0.0), 6),
            }
            for row in trade_days
        ],
    }


def _strategy_diagnostics(
    frame: pd.DataFrame,
    context: pd.DataFrame | None,
    *,
    evaluation_start: str,
    evaluation_end: str,
    evaluation_windows: list[tuple[str, str]] | None = None,
) -> dict[str, Any]:
    params = {**DEFAULT_PARAMS, "variant_id": DRIFT_GUARDED_VARIANT_ID, "family_id": FAMILY_ID}
    windows = evaluation_windows or [(evaluation_start, evaluation_end)]
    counts = {
        "evaluation_bar_count": 0,
        "base_entry_bars": 0,
        "rejected_by_regime_bars": 0,
        "rejected_by_volatility_after_regime_bars": 0,
        "rejected_by_trend_guard_after_regime_vol_bars": 0,
        "accepted_entry_bars": 0,
        "final_signal_bars": 0,
        "final_entry_segments": 0,
    }
    for start_raw, end_raw in windows:
        if not start_raw or not end_raw:
            continue
        start_ts = pd.Timestamp(start_raw)
        end_ts = pd.Timestamp(end_raw)
        window_frame = frame[(frame.index >= start_ts) & (frame.index <= end_ts)].copy()
        if window_frame.empty:
            continue
        window_counts = _strategy_counts_for_frame(window_frame, params=params)
        for key, value in window_counts.items():
            counts[key] += int(value)
    return {
        "source_frame_start": _timestamp_text(frame.index.min()),
        "source_frame_end": _timestamp_text(frame.index.max()),
        "evaluation_start": evaluation_start,
        "evaluation_end": evaluation_end,
        "bar_count": int(len(frame)),
        "evaluation_bar_count": counts["evaluation_bar_count"],
        "signal_generation_scope": "per_daily_cycle_window_matching_paper_runner",
        "params": {
            "lookback": int(params["lookback"]),
            "prior_high_window": int(params["prior_high_window"]),
            "pullback_depth_min": float(params["pullback_depth_min"]),
            "volume_multiple": float(params["volume_multiple"]),
            "trend_min": float(params["trend_min"]),
            "time_exit_bars": int(params["time_exit_bars"]),
            "cooldown_bars": int(params["cooldown_bars"]),
            "signal_scale": float(params["signal_scale"]),
            "entry_filter": dict(DRIFT_GUARDED_ENTRY_FILTER),
        },
        "base_entry_bars": counts["base_entry_bars"],
        "rejected_by_regime_bars": counts["rejected_by_regime_bars"],
        "rejected_by_volatility_after_regime_bars": counts["rejected_by_volatility_after_regime_bars"],
        "rejected_by_trend_guard_after_regime_vol_bars": counts["rejected_by_trend_guard_after_regime_vol_bars"],
        "accepted_entry_bars": counts["accepted_entry_bars"],
        "final_signal_bars": counts["final_signal_bars"],
        "final_entry_segments": counts["final_entry_segments"],
        "interpretation": {
            "signal_bars_vs_entries": "final_signal_bars counts held 5m bars; final_entry_segments is the closer proxy for entry opportunities.",
            "main_reason": _main_reason(
                counts["base_entry_bars"],
                counts["accepted_entry_bars"],
                counts["rejected_by_regime_bars"],
                counts["rejected_by_volatility_after_regime_bars"],
                counts["rejected_by_trend_guard_after_regime_vol_bars"],
            ),
        },
    }


def _strategy_counts_for_frame(frame: pd.DataFrame, *, params: Mapping[str, Any]) -> dict[str, int]:
    base_signal, diagnostics = pullback_reclaim_intraday_signal(frame.copy(), None, params)
    guarded_signal, guarded_diagnostics = apply_repaired_entry_filter(
        frame=frame.copy(),
        signal=base_signal,
        diagnostics=diagnostics,
        params=params,
        entry_filter=DRIFT_GUARDED_ENTRY_FILTER,
    )
    index = frame.index
    base_entries = _series_bool(diagnostics.get("pullback_reclaim_entry"), index)
    regime_allowed = _series_bool(guarded_diagnostics.get("entry_regime_allowed"), index)
    vol_allowed = _series_bool(guarded_diagnostics.get("volatility_state_allowed"), index)
    trend_allowed = _series_bool(guarded_diagnostics.get("regime_trend_guard_allowed"), index)
    final_entries = _series_bool(guarded_diagnostics.get("pullback_reclaim_entry"), index)
    signal_active = guarded_signal.reindex(index).fillna(0.0).astype(float) > 0.0
    return {
        "evaluation_bar_count": int(len(frame)),
        "base_entry_bars": int(base_entries.sum()),
        "rejected_by_regime_bars": int((base_entries & ~regime_allowed).sum()),
        "rejected_by_volatility_after_regime_bars": int((base_entries & regime_allowed & ~vol_allowed).sum()),
        "rejected_by_trend_guard_after_regime_vol_bars": int(
            (base_entries & regime_allowed & vol_allowed & ~trend_allowed).sum()
        ),
        "accepted_entry_bars": int(final_entries.sum()),
        "final_signal_bars": int(signal_active.sum()),
        "final_entry_segments": int((signal_active & ~signal_active.shift(1, fill_value=False)).sum()),
    }


def _trade_ledger(fills: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows = sorted(fills, key=lambda row: str(row.get("filled_at", "")))
    trades: list[dict[str, Any]] = []
    pending_buy: Mapping[str, Any] | None = None
    for row in rows:
        side = str(row.get("side", "")).lower()
        if side == "buy":
            pending_buy = row
            continue
        if side != "sell" or pending_buy is None:
            continue
        buy_qty = _float_or(pending_buy.get("quantity"), 0.0)
        sell_qty = _float_or(row.get("quantity"), 0.0)
        qty = min(buy_qty, sell_qty)
        buy_notional = qty * _float_or(pending_buy.get("price"), 0.0)
        sell_notional = qty * _float_or(row.get("price"), 0.0)
        fees = _float_or(pending_buy.get("commission"), 0.0) + _float_or(row.get("commission"), 0.0)
        pnl = sell_notional - buy_notional - fees
        entry_at = str(pending_buy.get("filled_at", ""))
        exit_at = str(row.get("filled_at", ""))
        trades.append(
            {
                "entry_at": entry_at,
                "exit_at": exit_at,
                "quantity": round(qty, 10),
                "entry_price": round(_float_or(pending_buy.get("price"), 0.0), 6),
                "exit_price": round(_float_or(row.get("price"), 0.0), 6),
                "gross_pnl": round(sell_notional - buy_notional, 6),
                "fees": round(fees, 6),
                "net_pnl": round(pnl, 6),
                "return_on_notional_pct": round((pnl / buy_notional) * 100.0, 6) if buy_notional > 0 else 0.0,
            }
        )
        pending_buy = None
    return trades


def _conclusion(*, metrics: Mapping[str, Any], strategy: Mapping[str, Any]) -> dict[str, Any]:
    days = int(metrics.get("days_completed", 0) or 0)
    trade_days = int(metrics.get("trade_days", 0) or 0)
    total_fills = int(metrics.get("total_fills", 0) or 0)
    total_return = float(metrics.get("total_return_pct", 0.0) or 0.0)
    final_segments = int(strategy.get("final_entry_segments", 0) or 0)
    entry_per_day = final_segments / days if days > 0 else 0.0
    return {
        "system": (
            "PASS: 5m paper infrastructure, risk gate, ledger snapshots, monitoring, and reconciliation are functioning."
            if bool(metrics.get("system_passed", False))
            else "BLOCKED: system evidence is not clean."
        ),
        "strategy_sample": (
            f"INSUFFICIENT: only {trade_days} trade days, {total_fills} fills, and {final_segments} entry segments in the sample."
        ),
        "high_frequency_fit": (
            f"FAIL_AS_HIGH_FREQUENCY: {days} days produced only {final_segments} entry segments "
            f"({entry_per_day:.4f}/day). This is a sparse event filter, not a high-frequency strategy."
        ),
        "profitability": (
            f"NEGATIVE_EDGE_IN_SAMPLE: total_return_pct={total_return:.4f}; do not treat this as live-ready."
            if total_return < 0
            else f"NON_NEGATIVE_BUT_UNPROVEN: total_return_pct={total_return:.4f}; sample remains too small."
        ),
        "tuning_or_expansion": (
            "DO_NOT_PATCH_TUNE_AS_HFT: use 180/365 day expansion to confirm the failure mode, but redesign the high-frequency candidate instead of only relaxing filters."
        ),
    }


def _high_frequency_fit(*, metrics: Mapping[str, Any], strategy: Mapping[str, Any]) -> dict[str, Any]:
    days = int(metrics.get("days_completed", 0) or 0)
    final_segments = int(strategy.get("final_entry_segments", 0) or 0)
    trade_days = int(metrics.get("trade_days", 0) or 0)
    total_fills = int(metrics.get("total_fills", 0) or 0)
    total_signals = int(metrics.get("total_signals", 0) or 0)
    bars = int(strategy.get("evaluation_bar_count", 0) or metrics.get("snapshot_count", 0) or 0)
    segments_per_day = final_segments / days if days > 0 else 0.0
    trade_day_ratio = trade_days / days if days > 0 else 0.0
    bars_per_segment = bars / final_segments if final_segments > 0 else None
    failed = days >= 30 and (segments_per_day < 1.0 or trade_day_ratio < 0.25 or total_fills < days)
    return {
        "declared_style": "high_frequency",
        "status": "FAIL" if failed else "UNPROVEN",
        "entry_segments": final_segments,
        "entry_segments_per_day": round(segments_per_day, 6),
        "trade_days": trade_days,
        "trade_day_ratio": round(trade_day_ratio, 6),
        "fills": total_fills,
        "signal_bars": total_signals,
        "evaluation_bars": bars,
        "bars_per_entry_segment": round(bars_per_segment, 3) if bars_per_segment is not None else None,
        "reason": (
            "Observed entry frequency is orders of magnitude below a high-frequency strategy; current rules behave as a sparse event filter."
            if failed
            else "Entry frequency is not proven sufficient for a high-frequency strategy."
        ),
    }


def _report_status(*, metrics: Mapping[str, Any], high_frequency_fit: Mapping[str, Any]) -> str:
    if not bool(metrics.get("system_passed", False)):
        return "blocked"
    if str(high_frequency_fit.get("status", "")) == "FAIL":
        return "pass_with_strategy_rejected_as_high_frequency"
    return "pass_with_strategy_sample_warning"


def _markdown(payload: Mapping[str, Any]) -> str:
    metrics = _mapping(payload.get("metrics"))
    strategy = _mapping(payload.get("strategy_diagnostics"))
    high_frequency_fit = _mapping(payload.get("high_frequency_fit"))
    conclusion = _mapping(payload.get("conclusion"))
    trades = [_mapping(row) for row in payload.get("trade_ledger", []) if isinstance(row, Mapping)]
    days = int(metrics.get("days_completed", 0) or 0)
    trade_days = int(metrics.get("trade_days", 0) or 0)
    fills = int(metrics.get("total_fills", 0) or 0)
    final_segments = int(strategy.get("final_entry_segments", 0) or 0)
    lines = [
        "# BTC 5m 纸盘验证评估报告",
        "",
        f"生成时间：{payload.get('generated_at', '')}",
        "",
        "## 一句话结论",
        "",
        (
            f"系统链路通过，但当前策略作为高频策略不通过。{days} 日只有 {trade_days} 个交易日、"
            f"{fills} 笔成交、{final_segments} 个入场段，实际表现是低频事件过滤器，不是高频交易策略。"
        ),
        "",
        f"## {days} 日汇总",
        "",
        "| 指标 | 数值 |",
        "| --- | ---: |",
        f"| 完成周期 | {metrics.get('days_completed', 0)} |",
        f"| 连续干净周期 | {metrics.get('consecutive_clean_days', 0)} |",
        f"| 初始资金 | {metrics.get('initial_capital', 0)} |",
        f"| 最新权益 | {metrics.get('final_equity', 0)} |",
        f"| 总收益率 | {metrics.get('total_return_pct', 0)}% |",
        f"| 最大回撤 | {metrics.get('max_drawdown_pct', 0)}% |",
        f"| 信号 bar 数 | {metrics.get('total_signals', 0)} |",
        f"| 订单数 | {metrics.get('total_orders', 0)} |",
        f"| 成交数 | {metrics.get('total_fills', 0)} |",
        f"| 拒单数 | {metrics.get('total_rejected', 0)} |",
        f"| 手续费 | {metrics.get('total_fees', 0)} |",
        f"| 有信号天数 | {metrics.get('signal_days', 0)} |",
        f"| 有成交天数 | {metrics.get('trade_days', 0)} |",
        f"| 无成交天数 | {metrics.get('no_trade_days', 0)} |",
        f"| 最长连续无成交天数 | {metrics.get('max_consecutive_no_trade_days', 0)} |",
        "",
        "## 高频适配度",
        "",
        "| 指标 | 数值 |",
        "| --- | ---: |",
        f"| 高频适配状态 | {high_frequency_fit.get('status', '')} |",
        f"| 入场段/日 | {high_frequency_fit.get('entry_segments_per_day', 0)} |",
        f"| 交易日占比 | {high_frequency_fit.get('trade_day_ratio', 0)} |",
        f"| 每个入场段平均间隔 bar | {high_frequency_fit.get('bars_per_entry_segment', '')} |",
        "",
        f"判断：{high_frequency_fit.get('reason', '')}",
        "",
        f"## 为什么只有 {trade_days} 个交易日、{fills} 笔成交",
        "",
        f"这不是执行系统没下单，而是策略过滤后实际入场机会很少。`{metrics.get('total_signals', 0)} signals` 不是 {metrics.get('total_signals', 0)} 次入场，而是持仓信号持续的 5m bar；当前参数每次入场后 `time_exit_bars=12`，所以真实机会应看最终入场段数。",
        "",
        "| 筛选层 | bar 数 |",
        "| --- | ---: |",
        f"| 原始 pullback reclaim entry | {strategy.get('base_entry_bars', 0)} |",
        f"| 被 regime 过滤剔除 | {strategy.get('rejected_by_regime_bars', 0)} |",
        f"| regime 后被 high-vol 过滤剔除 | {strategy.get('rejected_by_volatility_after_regime_bars', 0)} |",
        f"| regime/high-vol 后被 trend guard 剔除 | {strategy.get('rejected_by_trend_guard_after_regime_vol_bars', 0)} |",
        f"| 最终接受 entry bar | {strategy.get('accepted_entry_bars', 0)} |",
        f"| 最终持仓 signal bar | {strategy.get('final_signal_bars', 0)} |",
        f"| 最终入场段数 | {strategy.get('final_entry_segments', 0)} |",
        "",
        f"主因判断：{_mapping(strategy.get('interpretation')).get('main_reason', '')}",
        "",
        "## 交易明细",
        "",
        "| 入场 | 出场 | 入场价 | 出场价 | 净盈亏 | 手续费 | 名义收益率 |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    if trades:
        for row in trades:
            lines.append(
                f"| {row.get('entry_at', '')} | {row.get('exit_at', '')} | {row.get('entry_price', 0)} | "
                f"{row.get('exit_price', 0)} | {row.get('net_pnl', 0)} | {row.get('fees', 0)} | "
                f"{row.get('return_on_notional_pct', 0)}% |"
            )
    else:
        lines.append("| 无 | 无 | 0 | 0 | 0 | 0 | 0% |")
    lines += [
        "",
        "## 分层结论",
        "",
        f"- 系统通过：{conclusion.get('system', '')}",
        f"- 策略样本不足：{conclusion.get('strategy_sample', '')}",
        f"- 高频策略适配：{conclusion.get('high_frequency_fit', '')}",
        f"- 收益边际：{conclusion.get('profitability', '')}",
        f"- 是否调参：{conclusion.get('tuning_or_expansion', '')}",
        "",
        "## 下一步",
        "",
        "1. 保留当前纸盘系统继续滚动验证，但不要把这个策略当高频候选推进。",
        "2. 180/365 日扩样本只用于确认失效形态和系统稳定性，不用于给当前策略找借口。",
        "3. 重新设计高频候选：需要更高触发密度、更短持仓周期，并引入盘口/价差/成交质量特征。",
        "4. 每日滚动纸盘继续执行：每日更新 OKX 5m/15m，跑最新周期并写 monitoring，异常直接阻断。",
        "",
    ]
    return "\n".join(lines)


def _selected_bundle_dir(root: Path, config_path: Path) -> Path:
    config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    providers = _mapping(config.get("providers"))
    selected = str(config.get("selected_provider", "okx_swap") or "okx_swap")
    provider = _mapping(providers.get(selected))
    bundle_id = str(provider.get("selected_bundle_id", "") or "")
    provider_root = Path(str(provider.get("root", "data/external/btc_perpetual/okx_swap/") or ""))
    return _resolve(root, provider_root / "bundles" / bundle_id)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return dict(payload) if isinstance(payload, Mapping) else {}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        if isinstance(payload, Mapping):
            rows.append(dict(payload))
    return rows


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(json.dumps(dict(payload), indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    except Exception:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
        raise


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
    except Exception:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
        raise


def _series_bool(value: object, index: pd.Index) -> pd.Series:
    if isinstance(value, pd.Series):
        return value.reindex(index).fillna(0.0).astype(float) > 0.0
    return pd.Series(False, index=index)


def _main_reason(base: int, accepted: int, regime_rejected: int, vol_rejected: int, trend_rejected: int) -> str:
    if base <= 0:
        return "原始 pullback reclaim 条件在样本内几乎没有触发。"
    if accepted <= 0:
        return "原始机会存在，但修复后的 regime / high-vol / trend guard 过滤后没有入场。"
    rejects = {
        "regime filter": regime_rejected,
        "high-vol filter": vol_rejected,
        "trend guard": trend_rejected,
    }
    main = max(rejects, key=rejects.get)
    return f"原始机会经过过滤后只剩 {accepted}/{base} 个 entry bar；最大剔除项是 {main}。"


def _max_drawdown_pct(equity: list[float]) -> float:
    peak = 0.0
    max_dd = 0.0
    for value in equity:
        peak = max(peak, value)
        if peak > 0:
            max_dd = min(max_dd, value / peak - 1.0)
    return abs(max_dd) * 100.0


def _max_consecutive_days(rows: list[Mapping[str, Any]], predicate: Any) -> int:
    best = 0
    current = 0
    for row in rows:
        if predicate(row):
            current += 1
            best = max(best, current)
        else:
            current = 0
    return best


def _timestamp_text(value: object) -> str:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    return ts.isoformat().replace("+00:00", "Z")


def _float_or(value: object, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return default if number != number else number


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _relpath(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _utc_z_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build BTC 5m paper-validation evaluation report.")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--ledger-root", default=str(DEFAULT_LEDGER_ROOT))
    parser.add_argument("--config-path", default=str(DEFAULT_CONFIG))
    parser.add_argument("--bundle-dir", default="")
    parser.add_argument("--backfill-report", default=str(DEFAULT_BACKFILL_REPORT))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--markdown-output", default=str(DEFAULT_MARKDOWN_OUTPUT))
    parser.add_argument("--generated-at", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    payload = build_btc_paper_validation_evaluation_report(
        repo_root=Path(args.repo_root),
        ledger_root=Path(args.ledger_root),
        config_path=Path(args.config_path),
        bundle_dir=Path(args.bundle_dir) if args.bundle_dir else None,
        backfill_report=Path(args.backfill_report),
        output=Path(args.output),
        markdown_output=Path(args.markdown_output),
        generated_at=args.generated_at or None,
    )
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    else:
        print(payload["status"])


if __name__ == "__main__":
    main()
