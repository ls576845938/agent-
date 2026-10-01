from __future__ import annotations

import csv
import json
import math
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd

from quant_crypto.research.atr_regime_failure_analysis import build_market_regime_frame
from quant_crypto.research.long_short_trend_following_lab import (
    DEFAULT_DERIVATIVES_ROWS,
    DEFAULT_MARKET_DB,
    BASE_INTERVAL,
    EXCHANGE,
    SYMBOL,
    LongShortTrendSpec,
    aggregate_ohlcv,
    aggregate_ohlcv_calendar,
    align_derivatives_to_index,
    evaluate_long_short_trend_rule,
    load_market_1h,
    long_short_trend_following_specs,
)
from quant_crypto.research.multi_timeframe_rule_lab import BASE_COST_BPS, INITIAL_CAPITAL, performance_metrics


SCHEMA_VERSION = "btc_long_short_top5_review_v1"
DEFAULT_SOURCE_REPORT_PATH = Path("artifacts/btc_long_short_trend_following_lab/latest/btc_long_short_trend_following_lab_report.json")
DEFAULT_OUTPUT_DIR = Path("artifacts/btc_long_short_top5_review/latest")
DEFAULT_REPORT_PATH = DEFAULT_OUTPUT_DIR / "btc_long_short_top5_review_report.json"
DEFAULT_CSV_PATH = DEFAULT_OUTPUT_DIR / "btc_long_short_top5_review_candidates.csv"
DEFAULT_MARKDOWN_PATH = DEFAULT_OUTPUT_DIR / "btc_long_short_top5_review_summary_cn.md"


@dataclass
class ReviewedCandidate:
    spec: LongShortTrendSpec
    source_row: Mapping[str, Any]
    item: Any
    holdout: dict[str, Any]
    in_sample: dict[str, Any]
    annual: dict[str, Any]
    regime: dict[str, Any]
    concentration: dict[str, Any]
    drawdown: dict[str, Any]
    trend_profile: dict[str, Any]
    forward_observation: dict[str, Any]
    failures: dict[str, Any]


def build_btc_long_short_top5_review(
    *,
    source_report_path: Path = DEFAULT_SOURCE_REPORT_PATH,
    market_db_path: Path = DEFAULT_MARKET_DB,
    derivatives_rows_path: Path = DEFAULT_DERIVATIVES_ROWS,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    generated_at_utc: datetime | None = None,
    top_n: int = 5,
    holdout_days: int = 180,
    holdout_fraction: float = 0.20,
    initial_capital: float = INITIAL_CAPITAL,
    base_cost_bps: float = BASE_COST_BPS,
) -> dict[str, Any]:
    generated = generated_at_utc or datetime.now(timezone.utc)
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / DEFAULT_REPORT_PATH.name
    csv_path = output_dir / DEFAULT_CSV_PATH.name
    markdown_path = output_dir / DEFAULT_MARKDOWN_PATH.name

    source_report = _read_json(source_report_path)
    source_rows = _top_source_rows(source_report, top_n=top_n)
    bars_1h = load_market_1h(market_db_path)
    bars_4h = aggregate_ohlcv(bars_1h, interval_hours=4)
    bars_1d = aggregate_ohlcv(bars_1h, interval_hours=24)
    bars_1w = aggregate_ohlcv_calendar(bars_1h, timeframe="1w")
    bars_1mo = aggregate_ohlcv_calendar(bars_1h, timeframe="1mo")
    derivatives_4h = align_derivatives_to_index(derivatives_rows_path, bars_4h.index)
    regime_frame = build_market_regime_frame(bars_4h)
    spec_by_id = {spec.candidate_id: spec for spec in long_short_trend_following_specs(run_profile="formal_narrow")}

    blockers: list[str] = []
    reviewed: list[ReviewedCandidate] = []
    if not source_rows:
        blockers.append("btc_long_short_top5_review_missing_source_watchlist")
    for row in source_rows:
        candidate_id = str(row.get("candidate_id", ""))
        spec = spec_by_id.get(candidate_id)
        if spec is None:
            blockers.append(f"btc_long_short_top5_review_missing_spec:{candidate_id}")
            continue
        item = evaluate_long_short_trend_rule(
            spec,
            bars_4h=bars_4h,
            bars_1d=bars_1d,
            bars_1w=bars_1w,
            bars_1mo=bars_1mo,
            derivatives_4h=derivatives_4h,
            initial_capital=initial_capital,
            cost_bps=base_cost_bps,
        )
        holdout_index, in_sample_index, holdout_meta = _holdout_split(
            item.returns.index,
            holdout_days=holdout_days,
            holdout_fraction=holdout_fraction,
        )
        holdout = {
            **holdout_meta,
            "metrics": _slice_metrics(item, holdout_index, initial_capital=initial_capital),
            "passed": False,
        }
        holdout["passed"] = _segment_passed(holdout["metrics"], max_drawdown_abs_pct=25.0)
        in_sample = {
            "row_count": int(len(in_sample_index)),
            "start": _ts(in_sample_index.min()) if len(in_sample_index) else None,
            "end": _ts(in_sample_index.max()) if len(in_sample_index) else None,
            "metrics": _slice_metrics(item, in_sample_index, initial_capital=initial_capital),
        }
        annual = _annual_attribution(item, initial_capital=initial_capital)
        regime = _regime_attribution(item, regime_frame=regime_frame, initial_capital=initial_capital)
        trades = _trade_ledger(item)
        concentration = _concentration_review(item, trades=trades)
        drawdown = _drawdown_review(item, regime_frame=regime_frame, initial_capital=initial_capital)
        trend_profile = _trend_following_profile_review(
            item,
            trades=trades,
            regime_frame=regime_frame,
            annual=annual,
            initial_capital=initial_capital,
        )
        forward_observation = _forward_observation_plan(
            item,
            regime_frame=regime_frame,
            initial_capital=initial_capital,
        )
        failures = _failure_review(
            item,
            holdout=holdout,
            annual=annual,
            regime=regime,
            concentration=concentration,
            drawdown=drawdown,
            trend_profile=trend_profile,
            trades=trades,
        )
        reviewed.append(
            ReviewedCandidate(
                spec=spec,
                source_row=row,
                item=item,
                holdout=holdout,
                in_sample=in_sample,
                annual=annual,
                regime=regime,
                concentration=concentration,
                drawdown=drawdown,
                trend_profile=trend_profile,
                forward_observation=forward_observation,
                failures=failures,
            )
        )

    rows = [_candidate_row(candidate, rank=rank) for rank, candidate in enumerate(reviewed, 1)]
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated.isoformat(),
        "status": "blocked" if blockers else "complete_research_only",
        "decision": "btc_long_short_top5_review_research_only_no_paper_no_live",
        "scope": "confirmatory_holdout_regime_concentration_failure_review_for_btc_long_short_top5",
        "code_commit": _git_commit(),
        "source": {
            "source_report_path": _portable_path(source_report_path),
            "source_schema_version": source_report.get("schema_version"),
            "source_code_commit": source_report.get("code_commit"),
            "source_candidate_count": source_report.get("validation_design", {}).get("candidate_count"),
            "source_run_profile": source_report.get("validation_design", {}).get("run_profile"),
            "top_n_requested": int(top_n),
            "top_n_reviewed": len(reviewed),
            "selection_note": "Top 5 are taken from the latest long_short_research_watchlist order, not re-selected in this review.",
        },
        "input": {
            "market_db_path": _portable_path(market_db_path),
            "derivatives_rows_path": _portable_path(derivatives_rows_path),
            "symbol": SYMBOL,
            "exchange": EXCHANGE,
            "source_interval": "1h",
            "decision_interval": BASE_INTERVAL,
            "market_1h_rows": int(len(bars_1h)),
            "bar_4h_rows": int(len(bars_4h)),
            "bar_1d_rows": int(len(bars_1d)),
            "bar_1w_rows": int(len(bars_1w)),
            "bar_1mo_rows": int(len(bars_1mo)),
            "bar_4h_start": _ts(bars_4h.index.min()) if len(bars_4h) else None,
            "bar_4h_end": _ts(bars_4h.index.max()) if len(bars_4h) else None,
            "completed_bar_rule": "1h completed bars only; 4h/1d/1w/1mo derived from completed 1h chunks",
            "derivatives_available_time_rule": "derivatives rows aligned by available_time <= decision_time",
        },
        "review_design": {
            "confirmation_holdout_rule": f"latest max({holdout_days} days, {holdout_fraction:.0%} of 4h rows)",
            "holdout_locked_for_this_review": True,
            "clean_pre_selection_holdout": False,
            "clean_pre_selection_holdout_note": "The formal shortlist was already selected from the full historical report. This review is a post-selection confirmation stress, not fresh unseen market data.",
            "checks": [
                "confirmatory holdout metrics",
                "calendar-year segment attribution",
                "market-regime attribution",
                "trade and year return concentration",
                "trend-following-specific profile checks",
                "future 30d/60d forward-observation criteria",
                "max drawdown regime attribution",
                "worst trade and failure flags",
            ],
        },
        "guardrails": _guardrails(),
        "gate": {
            "paper_queue_write_allowed": False,
            "paper_candidate_created": False,
            "live_unlock_allowed": False,
            "live_order_allowed": False,
            "oms_access_allowed": False,
            "broker_access_allowed": False,
            "strategy_skeleton_generated": False,
            "reason": "Top 5 review is diagnostic only; it cannot promote candidates without future-data validation and manual paper gate review.",
        },
        "candidate_rows": rows,
        "candidate_reviews": [_candidate_detail(candidate) for candidate in reviewed],
        "review_summary": _review_summary(rows),
        "blockers": blockers,
        "warnings": _warnings(rows),
        "outputs": {
            "json": _portable_path(report_path),
            "candidate_csv": _portable_path(csv_path),
            "summary_cn": _portable_path(markdown_path),
        },
    }
    _write_json(report_path, report)
    _write_csv(csv_path, _csv_fieldnames(), rows)
    _write_text(markdown_path, render_btc_long_short_top5_review_markdown(report))
    return report


def render_btc_long_short_top5_review_markdown(report: Mapping[str, Any]) -> str:
    source = report.get("source", {})
    summary = report.get("review_summary", {})
    gate = report.get("gate", {})
    lines = [
        "# BTC Long/Short Top 5 复核包",
        "",
        f"- 状态：`{report.get('status')}`",
        f"- 决策边界：`{report.get('decision')}`",
        f"- 来源候选数：`{source.get('source_candidate_count')}`",
        f"- 复核 Top 数：`{source.get('top_n_reviewed')}`",
        f"- holdout 通过数：`{summary.get('holdout_pass_count')}`",
        f"- 趋势跟踪口径通过数：`{summary.get('trend_profile_pass_count')}`",
        f"- 高集中度候选数：`{summary.get('high_concentration_count')}`",
        f"- 写入 paper 队列：`{gate.get('paper_queue_write_allowed')}`",
        f"- 解锁 live：`{gate.get('live_unlock_allowed')}`",
        "",
        "## 趋势跟踪专用评价口径",
        "",
        "- 收益集中是趋势跟踪的常见特征，不再单独作为剔除理由。",
        "- 额外检查大盈利交易是否来自多根 K 线延续和明确趋势环境，而不是单根异常拉动。",
        "- 额外检查亏损交易是否保持小亏、震荡/无趋势阶段是否少亏或空仓、不同年份是否仍有趋势捕捉机会。",
        "- 未来 30/60 天观察重点不是必须赚钱，而是继续符合“少亏、等待大趋势”的形态。",
        "",
        "## Top 5 复核摘要",
        "",
        "| 排名 | 候选 | holdout收益 | holdout回撤 | holdout PF | 大盈利来自趋势 | 小亏可控 | 无趋势少亏/空仓 | 年度机会 | 30/60观察 | 结论 |",
        "|---:|---|---:|---:|---:|---|---|---|---|---|---|",
    ]
    for row in report.get("candidate_rows", []):
        lines.append(
            f"| {row['rank']} | `{row['variant_id']}` | {row['holdout_total_return_pct']} | "
            f"{row['holdout_max_drawdown_pct']} | {row['holdout_profit_factor']} | "
            f"{_yes_no(row.get('large_winner_trend_passed'))} | {_yes_no(row.get('loss_control_passed'))} | "
            f"{_yes_no(row.get('trendless_phase_passed'))} | {_yes_no(row.get('yearly_opportunity_passed'))} | "
            f"{row.get('forward_30d_status')}/{row.get('forward_60d_status')} | `{row['review_decision']}` |"
        )
    lines.extend(
        [
            "",
            "## 重要限制",
            "",
            "- 这不是干净的预选前 holdout：Top 5 已经来自完整历史 formal 报告，本复核只能作为 post-selection 压力确认。",
            "- 所有候选仍然只在扩展研究观察中，不写 paper 队列，不解锁 live。",
            "- 下一步需要等待新增真实行情，按 30 天/60 天观察规则复核，再讨论是否进入 paper candidate 人工门禁。",
        ]
    )
    return "\n".join(lines) + "\n"


def _top_source_rows(source_report: Mapping[str, Any], *, top_n: int) -> list[Mapping[str, Any]]:
    rows = source_report.get("long_short_research_watchlist") or []
    if not isinstance(rows, list):
        return []
    return [row for row in rows[:top_n] if isinstance(row, Mapping)]


def _holdout_split(index: pd.DatetimeIndex, *, holdout_days: int, holdout_fraction: float) -> tuple[pd.DatetimeIndex, pd.DatetimeIndex, dict[str, Any]]:
    if len(index) == 0:
        return pd.DatetimeIndex([]), pd.DatetimeIndex([]), {"row_count": 0, "start": None, "end": None}
    fraction_start = index[max(0, int(len(index) * (1.0 - holdout_fraction)))]
    day_start = index.max() - pd.Timedelta(days=holdout_days)
    holdout_start = min(pd.Timestamp(fraction_start), pd.Timestamp(day_start))
    holdout_index = pd.DatetimeIndex(index[index >= holdout_start])
    if len(holdout_index) < 20:
        holdout_index = pd.DatetimeIndex(index[-min(len(index), 20) :])
    in_sample_index = pd.DatetimeIndex(index[index < holdout_index.min()])
    meta = {
        "row_count": int(len(holdout_index)),
        "start": _ts(holdout_index.min()) if len(holdout_index) else None,
        "end": _ts(holdout_index.max()) if len(holdout_index) else None,
        "holdout_days_requested": int(holdout_days),
        "holdout_fraction_requested": _round(float(holdout_fraction)),
        "rule": "latest max(holdout_days, holdout_fraction of rows)",
    }
    return holdout_index, in_sample_index, meta


def _slice_metrics(item: Any, index: pd.DatetimeIndex, *, initial_capital: float) -> dict[str, Any]:
    if len(index) == 0:
        return _empty_metrics(initial_capital)
    returns = item.returns.loc[index]
    equity = float(initial_capital) * (1.0 + returns).cumprod()
    metrics = performance_metrics(
        strategy_returns=returns,
        equity=equity,
        exposure=item.exposure.loc[index],
        turnover=item.turnover.loc[index],
        cost=item.trading_cost.loc[index],
        interval=BASE_INTERVAL,
        initial_capital=initial_capital,
    )
    metrics["funding_return_pct"] = _round(float(item.funding_pnl.loc[index].sum()) * 100.0)
    metrics["long_bar_count"] = int((item.exposure.loc[index] > 0.0).sum())
    metrics["short_bar_count"] = int((item.exposure.loc[index] < 0.0).sum())
    return metrics


def _annual_attribution(item: Any, *, initial_capital: float) -> dict[str, Any]:
    rows = []
    for year, positions in item.returns.groupby(item.returns.index.year).groups.items():
        idx = pd.DatetimeIndex(positions)
        if len(idx) < 20:
            continue
        metrics = _slice_metrics(item, idx, initial_capital=initial_capital)
        rows.append({"year": int(year), "row_count": int(len(idx)), "passed": _segment_passed(metrics), "metrics": metrics})
    positive = [max(0.0, float(row["metrics"]["total_return_pct"])) for row in rows]
    best_share = max(positive) / sum(positive) if sum(positive) > 0.0 else 0.0
    return {
        "segment_count": len(rows),
        "pass_rate": _round(sum(1 for row in rows if row["passed"]) / len(rows) if rows else 0.0),
        "best_positive_year_share": _round(best_share),
        "segments": rows,
    }


def _regime_attribution(item: Any, *, regime_frame: pd.DataFrame, initial_capital: float) -> dict[str, Any]:
    rows = []
    labels = regime_frame["regime_label"].reindex(item.returns.index).fillna("unknown")
    for label in sorted(labels.dropna().unique()):
        idx = pd.DatetimeIndex(labels.index[labels == label])
        if len(idx) < 20:
            continue
        metrics = _slice_metrics(item, idx, initial_capital=initial_capital)
        rows.append({"regime_label": str(label), "row_count": int(len(idx)), "passed": _segment_passed(metrics), "metrics": metrics})
    return {
        "segment_count": len(rows),
        "pass_rate": _round(sum(1 for row in rows if row["passed"]) / len(rows) if rows else 0.0),
        "segments": rows,
    }


def _trade_ledger(item: Any) -> list[dict[str, Any]]:
    trades: list[dict[str, Any]] = []
    current_side = 0.0
    start: pd.Timestamp | None = None
    for ts, exposure in item.exposure.items():
        side = float(math.copysign(1.0, exposure)) if abs(float(exposure)) > 1e-12 else 0.0
        if current_side != 0.0 and side != current_side:
            trades.append(_close_trade(item, start=start, end=pd.Timestamp(previous_ts), side=current_side))
            start = None
            current_side = 0.0
        if current_side == 0.0 and side != 0.0:
            start = pd.Timestamp(ts)
            current_side = side
        previous_ts = ts
    if current_side != 0.0 and start is not None:
        trades.append(_close_trade(item, start=start, end=pd.Timestamp(item.exposure.index[-1]), side=current_side))
    return [trade for trade in trades if trade["bar_count"] > 0]


def _close_trade(item: Any, *, start: pd.Timestamp | None, end: pd.Timestamp, side: float) -> dict[str, Any]:
    if start is None:
        return {"bar_count": 0}
    idx = item.returns.index[(item.returns.index >= start) & (item.returns.index <= end)]
    returns = item.returns.loc[idx]
    total_return = float((1.0 + returns).prod() - 1.0) if len(returns) else 0.0
    positive_returns = returns[returns > 0.0]
    positive_sum = float(positive_returns.sum()) if len(positive_returns) else 0.0
    max_single_bar = float(positive_returns.max()) if len(positive_returns) else 0.0
    return {
        "side": "long" if side > 0.0 else "short",
        "start": _ts(start),
        "end": _ts(end),
        "bar_count": int(len(idx)),
        "total_return_pct": _round(total_return * 100.0),
        "max_single_bar_net_return_pct": _round(max_single_bar * 100.0),
        "max_single_bar_share_of_positive_bars": _round(max_single_bar / positive_sum if positive_sum > 0.0 else 0.0),
        "trend_duration_passed": bool(len(idx) >= 6),
        "not_single_bar_dominated": bool(max_single_bar / positive_sum <= 0.75 if positive_sum > 0.0 else True),
        "cost_return_pct": _round(float(item.trading_cost.loc[idx].sum()) * -100.0) if len(idx) else 0.0,
        "funding_return_pct": _round(float(item.funding_pnl.loc[idx].sum()) * 100.0) if len(idx) else 0.0,
    }


def _concentration_review(item: Any, *, trades: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    positive = sorted([float(trade["total_return_pct"]) for trade in trades if float(trade.get("total_return_pct", 0.0)) > 0.0], reverse=True)
    positive_sum = sum(positive)
    annual_positive = []
    for _, positions in item.returns.groupby(item.returns.index.year).groups.items():
        idx = pd.DatetimeIndex(positions)
        returns = item.returns.loc[idx]
        total = float((1.0 + returns).prod() - 1.0) * 100.0 if len(returns) else 0.0
        annual_positive.append(max(0.0, total))
    annual_sum = sum(annual_positive)
    return {
        "trade_count": len(trades),
        "positive_trade_count": len(positive),
        "top_1_positive_trade_share": _round(sum(positive[:1]) / positive_sum if positive_sum > 0.0 else 0.0),
        "top_3_positive_trade_share": _round(sum(positive[:3]) / positive_sum if positive_sum > 0.0 else 0.0),
        "top_5_positive_trade_share": _round(sum(positive[:5]) / positive_sum if positive_sum > 0.0 else 0.0),
        "best_positive_year_share": _round(max(annual_positive) / annual_sum if annual_sum > 0.0 else 0.0),
        "worst_trades": sorted(trades, key=lambda trade: float(trade.get("total_return_pct", 0.0)))[:5],
        "best_trades": sorted(trades, key=lambda trade: -float(trade.get("total_return_pct", 0.0)))[:5],
    }


def _drawdown_review(item: Any, *, regime_frame: pd.DataFrame, initial_capital: float) -> dict[str, Any]:
    equity = item.equity
    if equity.empty:
        return {}
    drawdown = equity / equity.cummax() - 1.0
    trough = pd.Timestamp(drawdown.idxmin())
    peak = pd.Timestamp(equity.loc[:trough].idxmax())
    idx = pd.DatetimeIndex(item.returns.index[(item.returns.index >= peak) & (item.returns.index <= trough)])
    labels = regime_frame["regime_label"].reindex(idx).fillna("unknown")
    exposure = item.exposure.loc[idx] if len(idx) else pd.Series(dtype=float)
    return {
        "peak_time": _ts(peak),
        "trough_time": _ts(trough),
        "bar_count": int(len(idx)),
        "max_drawdown_pct": _round(float(drawdown.loc[trough]) * 100.0),
        "metrics_during_drawdown": _slice_metrics(item, idx, initial_capital=initial_capital),
        "regime_mix": _value_share(labels),
        "long_bar_count": int((exposure > 0.0).sum()) if len(exposure) else 0,
        "short_bar_count": int((exposure < 0.0).sum()) if len(exposure) else 0,
    }


def _trend_following_profile_review(
    item: Any,
    *,
    trades: Sequence[Mapping[str, Any]],
    regime_frame: pd.DataFrame,
    annual: Mapping[str, Any],
    initial_capital: float,
) -> dict[str, Any]:
    large_winner = _large_winner_trend_review(item, trades=trades, regime_frame=regime_frame)
    loss_control = _loss_control_review(trades)
    trendless = _trendless_phase_review(item, regime_frame=regime_frame, initial_capital=initial_capital)
    yearly = _yearly_opportunity_review(annual)
    checks = {
        "large_winner_trend_passed": bool(large_winner["passed"]),
        "loss_control_passed": bool(loss_control["passed"]),
        "trendless_phase_passed": bool(trendless["passed"]),
        "yearly_opportunity_passed": bool(yearly["passed"]),
    }
    return {
        "profile_name": "trend_following_specific_review",
        "profile_passed": all(checks.values()),
        "checks": checks,
        "large_winner_trend_review": large_winner,
        "loss_control_review": loss_control,
        "trendless_phase_review": trendless,
        "yearly_opportunity_review": yearly,
        "interpretation": (
            "High return concentration is acceptable for trend following only when large winners are multi-bar trend moves, "
            "losses stay small, trendless phases are controlled, and multiple years still provide trend opportunities."
        ),
    }


def _large_winner_trend_review(item: Any, *, trades: Sequence[Mapping[str, Any]], regime_frame: pd.DataFrame) -> dict[str, Any]:
    positive = sorted(
        [trade for trade in trades if float(trade.get("total_return_pct", 0.0)) > 0.0],
        key=lambda trade: -float(trade.get("total_return_pct", 0.0)),
    )
    reviewed = []
    for trade in positive[:5]:
        idx = _trade_index(item, trade)
        labels = regime_frame["regime_label"].reindex(idx).fillna("unknown") if len(idx) else pd.Series(dtype=object)
        side = str(trade.get("side", ""))
        expected_label = "bull_trend" if side == "long" else "bear_or_drawdown"
        trend_share = float((labels == expected_label).sum()) / len(labels) if len(labels) else 0.0
        high_vol_share = float((labels == "high_volatility_risk").sum()) / len(labels) if len(labels) else 0.0
        row = dict(trade)
        row.update(
            {
                "expected_trend_regime": expected_label,
                "expected_trend_regime_share": _round(trend_share),
                "high_volatility_regime_share": _round(high_vol_share),
                "large_winner_trend_like": bool(
                    trade.get("trend_duration_passed")
                    and trade.get("not_single_bar_dominated")
                    and (trend_share >= 0.25 or high_vol_share >= 0.25)
                ),
            }
        )
        reviewed.append(row)
    top_to_check = reviewed[: min(3, len(reviewed))]
    passed = bool(top_to_check) and all(bool(row["large_winner_trend_like"]) for row in top_to_check)
    return {
        "passed": passed,
        "reviewed_positive_trade_count": len(reviewed),
        "top_checked_count": len(top_to_check),
        "min_required_bars": 6,
        "max_single_bar_share_threshold": 0.75,
        "min_expected_or_high_vol_regime_share": 0.25,
        "top_positive_trades": reviewed,
        "failure_reason": None if passed else "top_winners_not_confirmed_as_multi_bar_trend_moves",
    }


def _loss_control_review(trades: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    losses = sorted([float(trade.get("total_return_pct", 0.0)) for trade in trades if float(trade.get("total_return_pct", 0.0)) < 0.0])
    if not losses:
        return {
            "passed": True,
            "loss_trade_count": 0,
            "average_loss_pct": 0.0,
            "median_loss_pct": 0.0,
            "worst_loss_pct": 0.0,
            "rule": "no losing closed trades in reviewed sample",
        }
    average_loss = sum(losses) / len(losses)
    median_loss = losses[len(losses) // 2] if len(losses) % 2 else (losses[len(losses) // 2 - 1] + losses[len(losses) // 2]) / 2.0
    worst_loss = min(losses)
    passed = worst_loss >= -8.0 and average_loss >= -3.0
    return {
        "passed": passed,
        "loss_trade_count": len(losses),
        "average_loss_pct": _round(average_loss),
        "median_loss_pct": _round(median_loss),
        "worst_loss_pct": _round(worst_loss),
        "max_allowed_single_loss_pct": -8.0,
        "min_allowed_average_loss_pct": -3.0,
        "failure_reason": None if passed else "losses_too_large_for_trend_following_small_loss_profile",
    }


def _trendless_phase_review(item: Any, *, regime_frame: pd.DataFrame, initial_capital: float) -> dict[str, Any]:
    labels = regime_frame["regime_label"].reindex(item.returns.index).fillna("unknown")
    idx = pd.DatetimeIndex(labels.index[labels == "sideways_chop"])
    metrics = _slice_metrics(item, idx, initial_capital=initial_capital)
    total_return = float(metrics.get("total_return_pct", 0.0))
    drawdown_abs = float(metrics.get("max_drawdown_abs_pct", 0.0))
    average_exposure = float(metrics.get("average_exposure", 0.0))
    passed = total_return >= -3.0 and drawdown_abs <= 8.0 and (average_exposure <= 0.25 or total_return >= 0.0)
    return {
        "passed": passed,
        "regime_label": "sideways_chop",
        "row_count": int(len(idx)),
        "metrics": metrics,
        "max_allowed_loss_pct": -3.0,
        "max_allowed_drawdown_abs_pct": 8.0,
        "max_expected_average_exposure_when_losing": 0.25,
        "failure_reason": None if passed else "trendless_phase_did_not_stay_low_loss_or_low_exposure",
    }


def _yearly_opportunity_review(annual: Mapping[str, Any]) -> dict[str, Any]:
    segments = list(annual.get("segments", []))
    positive_years = [
        row
        for row in segments
        if float(row.get("metrics", {}).get("total_return_pct", 0.0)) > 0.0
    ]
    worst_year_return = min((float(row.get("metrics", {}).get("total_return_pct", 0.0)) for row in segments), default=0.0)
    required_positive_years = 2 if len(segments) >= 2 else min(1, len(segments))
    passed = len(positive_years) >= required_positive_years and worst_year_return >= -12.0
    return {
        "passed": passed,
        "calendar_year_count": len(segments),
        "positive_year_count": len(positive_years),
        "required_positive_year_count": required_positive_years,
        "best_positive_year_share": annual.get("best_positive_year_share", 0.0),
        "worst_year_total_return_pct": _round(worst_year_return),
        "failure_reason": None if passed else "too_few_years_captured_trend_or_one_year_loss_too_large",
    }


def _forward_observation_plan(item: Any, *, regime_frame: pd.DataFrame, initial_capital: float) -> dict[str, Any]:
    latest_ts = pd.Timestamp(item.returns.index.max()) if len(item.returns.index) else None
    windows = {}
    for days in (30, 60):
        key = f"{days}d"
        windows[key] = {
            "status": "pending_future_data",
            "start_after": _ts(latest_ts) if latest_ts is not None else None,
            "planned_end": _ts(latest_ts + pd.Timedelta(days=days)) if latest_ts is not None else None,
            "pass_shape": {
                "no_trend_or_no_breakout": "net_return_pct >= -3 for 30d / >= -6 for 60d and average_exposure <= 0.20",
                "trend_breakout_occurs": "loss trades remain small; no single losing trade worse than -8%; winners are not single-bar dominated",
                "promotion_effect": "observation can only support later manual paper review; it cannot unlock paper/live by itself",
            },
            "latest_history_proxy": _recent_window_diagnostic(
                item,
                regime_frame=regime_frame,
                days=days,
                initial_capital=initial_capital,
            ),
        }
    return {
        "policy": "future_30d_60d_observe_only_no_paper_no_live",
        "observation_windows": windows,
        "expected_shape": "small losses or cash while no trend is present; wait for large directional trend opportunities",
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
    }


def _recent_window_diagnostic(item: Any, *, regime_frame: pd.DataFrame, days: int, initial_capital: float) -> dict[str, Any]:
    if len(item.returns.index) == 0:
        return {"row_count": 0, "status": "empty"}
    end = pd.Timestamp(item.returns.index.max())
    start = end - pd.Timedelta(days=days)
    idx = pd.DatetimeIndex(item.returns.index[item.returns.index > start])
    metrics = _slice_metrics(item, idx, initial_capital=initial_capital)
    labels = regime_frame["regime_label"].reindex(idx).fillna("unknown") if len(idx) else pd.Series(dtype=object)
    total_return = float(metrics.get("total_return_pct", 0.0))
    average_exposure = float(metrics.get("average_exposure", 0.0))
    max_waiting_loss = -3.0 if days <= 30 else -6.0
    status = "matches_waiting_shape" if total_return >= max_waiting_loss or average_exposure <= 0.20 else "needs_manual_review"
    return {
        "status": status,
        "row_count": int(len(idx)),
        "start": _ts(idx.min()) if len(idx) else None,
        "end": _ts(idx.max()) if len(idx) else None,
        "metrics": metrics,
        "regime_mix": _value_share(labels),
        "max_waiting_loss_pct": max_waiting_loss,
        "trade_count": _trade_count_in_index(_trade_ledger(item), idx),
    }


def _trade_count_in_index(trades: Sequence[Mapping[str, Any]], index: pd.DatetimeIndex) -> int:
    if len(index) == 0:
        return 0
    start = pd.Timestamp(index.min())
    end = pd.Timestamp(index.max())
    count = 0
    for trade in trades:
        trade_start = pd.Timestamp(trade["start"])
        trade_end = pd.Timestamp(trade["end"])
        if trade_start <= end and trade_end >= start:
            count += 1
    return count


def _trade_index(item: Any, trade: Mapping[str, Any]) -> pd.DatetimeIndex:
    start = pd.Timestamp(trade["start"])
    end = pd.Timestamp(trade["end"])
    return pd.DatetimeIndex(item.returns.index[(item.returns.index >= start) & (item.returns.index <= end)])


def _failure_review(
    item: Any,
    *,
    holdout: Mapping[str, Any],
    annual: Mapping[str, Any],
    regime: Mapping[str, Any],
    concentration: Mapping[str, Any],
    drawdown: Mapping[str, Any],
    trend_profile: Mapping[str, Any],
    trades: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    flags: list[str] = []
    holdout_metrics = holdout.get("metrics", {})
    if not bool(holdout.get("passed", False)):
        flags.append("holdout_failed")
    if float(holdout_metrics.get("profit_factor", 0.0)) < 1.0:
        flags.append("holdout_profit_factor_below_1")
    if float(holdout_metrics.get("total_return_pct", 0.0)) <= 0.0:
        flags.append("holdout_non_positive_return")
    if float(annual.get("best_positive_year_share", 0.0)) > 0.70:
        flags.append("year_return_concentration_expected_for_trend_following")
    if float(concentration.get("top_3_positive_trade_share", 0.0)) > 0.65:
        flags.append("top_trade_return_concentration_expected_for_trend_following")
    if float(drawdown.get("max_drawdown_pct", 0.0)) < -20.0:
        flags.append("large_drawdown_review")
    if int(item.metrics.get("long_bar_count", 0)) <= 0 or int(item.metrics.get("short_bar_count", 0)) <= 0:
        flags.append("not_truly_long_short")
    worst_trade = min((float(trade.get("total_return_pct", 0.0)) for trade in trades), default=0.0)
    if worst_trade < -10.0:
        flags.append("large_single_trade_loss")
    failed_trend_checks = [
        name
        for name, passed in trend_profile.get("checks", {}).items()
        if not bool(passed)
    ]
    for name in failed_trend_checks:
        flags.append(f"trend_profile_failed:{name}")
    regime_failures = [
        row["regime_label"]
        for row in regime.get("segments", [])
        if float(row["metrics"].get("total_return_pct", 0.0)) <= 0.0 or float(row["metrics"].get("profit_factor", 0.0)) < 1.0
    ]
    if regime_failures:
        flags.append("regime_failure_present")
    decision = "extended_research_only_holdout_passed"
    if "holdout_failed" in flags:
        decision = "defer_holdout_failed"
    elif failed_trend_checks:
        decision = "defer_trend_following_profile_failed"
    elif "regime_failure_present" in flags:
        decision = "defer_regime_failure_review"
    elif "large_drawdown_review" in flags or "large_single_trade_loss" in flags:
        decision = "defer_loss_or_drawdown_review"
    elif (
        "top_trade_return_concentration_expected_for_trend_following" in flags
        or "year_return_concentration_expected_for_trend_following" in flags
    ):
        decision = "trend_following_concentration_expected_requires_forward_confirmation"
    else:
        decision = "extended_research_only_requires_forward_confirmation"
    return {
        "flags": flags,
        "flag_count": len(flags),
        "regime_failures": regime_failures,
        "failed_trend_profile_checks": failed_trend_checks,
        "trend_profile_passed": bool(trend_profile.get("profile_passed", False)),
        "worst_trade_total_return_pct": _round(worst_trade),
        "review_decision": decision,
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
    }


def _candidate_row(candidate: ReviewedCandidate, *, rank: int) -> dict[str, Any]:
    item = candidate.item
    holdout_metrics = candidate.holdout["metrics"]
    trend_checks = candidate.trend_profile.get("checks", {})
    forward_windows = candidate.forward_observation.get("observation_windows", {})
    return {
        "rank": rank,
        "candidate_id": candidate.spec.candidate_id,
        "variant_id": candidate.spec.variant_id,
        "params_hash": candidate.source_row.get("params_hash"),
        "entry_window": candidate.spec.params.get("entry_window"),
        "daily_fast": candidate.spec.params.get("daily_fast"),
        "daily_slow": candidate.spec.params.get("daily_slow"),
        "atr_mult": candidate.spec.params.get("atr_mult"),
        "cooldown_bars": candidate.spec.params.get("cooldown_bars"),
        "risk_filter_mode": candidate.spec.params.get("risk_filter_mode"),
        "full_total_return_pct": item.metrics["total_return_pct"],
        "full_max_drawdown_pct": item.metrics["max_drawdown_pct"],
        "full_profit_factor": item.metrics["profit_factor"],
        "holdout_total_return_pct": holdout_metrics["total_return_pct"],
        "holdout_max_drawdown_pct": holdout_metrics["max_drawdown_pct"],
        "holdout_profit_factor": holdout_metrics["profit_factor"],
        "holdout_passed": candidate.holdout["passed"],
        "annual_pass_rate": candidate.annual["pass_rate"],
        "best_positive_year_share": candidate.annual["best_positive_year_share"],
        "regime_pass_rate": candidate.regime["pass_rate"],
        "trade_count": candidate.concentration["trade_count"],
        "top_3_positive_trade_share": candidate.concentration["top_3_positive_trade_share"],
        "trend_profile_passed": candidate.trend_profile["profile_passed"],
        "large_winner_trend_passed": bool(trend_checks.get("large_winner_trend_passed", False)),
        "loss_control_passed": bool(trend_checks.get("loss_control_passed", False)),
        "trendless_phase_passed": bool(trend_checks.get("trendless_phase_passed", False)),
        "yearly_opportunity_passed": bool(trend_checks.get("yearly_opportunity_passed", False)),
        "worst_loss_pct": candidate.trend_profile["loss_control_review"].get("worst_loss_pct"),
        "trendless_total_return_pct": candidate.trend_profile["trendless_phase_review"].get("metrics", {}).get("total_return_pct"),
        "forward_30d_status": forward_windows.get("30d", {}).get("status"),
        "forward_60d_status": forward_windows.get("60d", {}).get("status"),
        "max_drawdown_regime_mix": candidate.drawdown.get("regime_mix", {}),
        "failure_flags": candidate.failures["flags"],
        "review_decision": candidate.failures["review_decision"],
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
    }


def _candidate_detail(candidate: ReviewedCandidate) -> dict[str, Any]:
    return {
        "candidate_id": candidate.spec.candidate_id,
        "variant_id": candidate.spec.variant_id,
        "label": candidate.spec.label,
        "params": candidate.spec.params,
        "source_row": dict(candidate.source_row),
        "full_metrics": candidate.item.metrics,
        "in_sample": candidate.in_sample,
        "confirmation_holdout": candidate.holdout,
        "annual_attribution": candidate.annual,
        "market_regime_attribution": candidate.regime,
        "return_concentration": candidate.concentration,
        "max_drawdown_attribution": candidate.drawdown,
        "trend_following_profile": candidate.trend_profile,
        "forward_observation": candidate.forward_observation,
        "failure_review": candidate.failures,
    }


def _review_summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "candidate_count": len(rows),
        "holdout_pass_count": sum(1 for row in rows if row.get("holdout_passed")),
        "high_concentration_count": sum(1 for row in rows if float(row.get("top_3_positive_trade_share", 0.0)) > 0.65),
        "regime_failure_count": sum(1 for row in rows if "regime_failure_present" in row.get("failure_flags", [])),
        "trend_profile_pass_count": sum(1 for row in rows if row.get("trend_profile_passed")),
        "large_winner_trend_pass_count": sum(1 for row in rows if row.get("large_winner_trend_passed")),
        "loss_control_pass_count": sum(1 for row in rows if row.get("loss_control_passed")),
        "trendless_phase_pass_count": sum(1 for row in rows if row.get("trendless_phase_passed")),
        "yearly_opportunity_pass_count": sum(1 for row in rows if row.get("yearly_opportunity_passed")),
        "forward_observation_pending_count": sum(
            1
            for row in rows
            if row.get("forward_30d_status") == "pending_future_data" and row.get("forward_60d_status") == "pending_future_data"
        ),
        "expected_concentration_count": sum(
            1
            for row in rows
            if "top_trade_return_concentration_expected_for_trend_following" in row.get("failure_flags", [])
            or "year_return_concentration_expected_for_trend_following" in row.get("failure_flags", [])
        ),
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
    }


def _segment_passed(metrics: Mapping[str, Any], *, max_drawdown_abs_pct: float = 35.0) -> bool:
    return (
        float(metrics.get("total_return_pct", 0.0)) > 0.0
        and float(metrics.get("profit_factor", 0.0)) >= 1.0
        and float(metrics.get("max_drawdown_abs_pct", 0.0)) <= max_drawdown_abs_pct
        and float(metrics.get("average_exposure", 0.0)) >= 0.03
    )


def _value_share(values: pd.Series) -> dict[str, float]:
    if len(values) == 0:
        return {}
    counts = values.value_counts(dropna=False)
    return {str(key): _round(float(value) / len(values)) for key, value in counts.items()}


def _empty_metrics(initial_capital: float) -> dict[str, Any]:
    return performance_metrics(
        strategy_returns=pd.Series(dtype=float),
        equity=pd.Series(dtype=float),
        exposure=pd.Series(dtype=float),
        turnover=pd.Series(dtype=float),
        cost=pd.Series(dtype=float),
        interval=BASE_INTERVAL,
        initial_capital=initial_capital,
    )


def _guardrails() -> dict[str, bool]:
    return {
        "research_only": True,
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "broker_access_allowed": False,
        "oms_access_allowed": False,
        "paper_queue_write_allowed": False,
        "paper_candidate_created": False,
        "live_unlock_allowed": False,
        "live_order_allowed": False,
        "real_order_submitted": False,
    }


def _warnings(rows: Sequence[Mapping[str, Any]]) -> list[str]:
    warnings = ["btc_long_short_top5_review_research_only_no_paper_no_live"]
    if any(
        "year_return_concentration_expected_for_trend_following" in row.get("failure_flags", [])
        or "top_trade_return_concentration_expected_for_trend_following" in row.get("failure_flags", [])
        for row in rows
    ):
        warnings.append("trend_following_return_concentration_expected_requires_forward_observation")
    if any(not row.get("trend_profile_passed", False) for row in rows):
        warnings.append("trend_following_profile_failure_present")
    if any("holdout_failed" in row.get("failure_flags", []) for row in rows):
        warnings.append("holdout_failure_present")
    warnings.append("clean_pre_selection_holdout_false_requires_future_data")
    return warnings


def _csv_fieldnames() -> list[str]:
    return [
        "rank",
        "candidate_id",
        "variant_id",
        "entry_window",
        "daily_fast",
        "daily_slow",
        "atr_mult",
        "cooldown_bars",
        "risk_filter_mode",
        "full_total_return_pct",
        "full_max_drawdown_pct",
        "full_profit_factor",
        "holdout_total_return_pct",
        "holdout_max_drawdown_pct",
        "holdout_profit_factor",
        "holdout_passed",
        "annual_pass_rate",
        "best_positive_year_share",
        "regime_pass_rate",
        "trade_count",
        "top_3_positive_trade_share",
        "trend_profile_passed",
        "large_winner_trend_passed",
        "loss_control_passed",
        "trendless_phase_passed",
        "yearly_opportunity_passed",
        "worst_loss_pct",
        "trendless_total_return_pct",
        "forward_30d_status",
        "forward_60d_status",
        "review_decision",
        "paper_queue_write_allowed",
        "live_unlock_allowed",
    ]


def _read_json(path: Path) -> Mapping[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"source report not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError(f"source report must be a JSON object: {path}")
    return payload


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_csv(path: Path, fieldnames: Sequence[str], rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fieldnames), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _portable_path(path: Path) -> str:
    try:
        return str(path.relative_to(Path.cwd())).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def _git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=Path.cwd(), text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return "unknown"


def _ts(value: Any) -> str:
    return pd.Timestamp(value).isoformat()


def _round(value: float, digits: int = 6) -> float:
    if value is None or not math.isfinite(float(value)):
        return 0.0
    return round(float(value), digits)


def _yes_no(value: Any) -> str:
    return "是" if bool(value) else "否"
