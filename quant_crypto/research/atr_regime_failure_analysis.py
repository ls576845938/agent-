from __future__ import annotations

import csv
import json
import math
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd

from quant_crypto.research.simple_trend_rule_lab import (
    BASE_COST_BPS,
    BASE_INTERVAL,
    DEFAULT_DERIVATIVES_ROWS,
    DEFAULT_MARKET_DB,
    EXCHANGE,
    INITIAL_CAPITAL,
    SYMBOL,
    aggregate_ohlcv,
    align_derivatives_to_index,
    evaluate_rule,
    load_market_1h,
    performance_metrics,
    simple_trend_rule_specs,
)


SCHEMA_VERSION = "btc_atr_regime_failure_analysis_v1"
DEFAULT_OUTPUT_DIR = Path("artifacts/btc_atr_regime_failure_analysis/latest")
DEFAULT_REPORT_PATH = DEFAULT_OUTPUT_DIR / "btc_atr_regime_failure_analysis_report.json"
DEFAULT_MATRIX_PATH = DEFAULT_OUTPUT_DIR / "btc_atr_regime_failure_matrix.csv"
DEFAULT_MARKDOWN_PATH = DEFAULT_OUTPUT_DIR / "btc_atr_regime_failure_analysis_summary_cn.md"

SEGMENT_DEFINITIONS = (
    ("2024_trend_segment", "2024-01-01", "2025-01-01", "2024 趋势段"),
    ("2025_drawdown_segment", "2025-01-01", "2026-01-01", "2025 回撤段"),
    ("2026_recent_segment", "2026-01-01", None, "2026 最近段"),
)


def build_btc_atr_regime_failure_analysis(
    *,
    market_db_path: Path = DEFAULT_MARKET_DB,
    derivatives_rows_path: Path = DEFAULT_DERIVATIVES_ROWS,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    generated_at_utc: datetime | None = None,
    initial_capital: float = INITIAL_CAPITAL,
    base_cost_bps: float = BASE_COST_BPS,
) -> dict[str, Any]:
    generated = generated_at_utc or datetime.now(timezone.utc)
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / DEFAULT_REPORT_PATH.name
    matrix_path = output_dir / DEFAULT_MATRIX_PATH.name
    markdown_path = output_dir / DEFAULT_MARKDOWN_PATH.name

    bars_1h = load_market_1h(market_db_path)
    bars_4h = aggregate_ohlcv(bars_1h, interval_hours=4)
    bars_1d = aggregate_ohlcv(bars_1h, interval_hours=24)
    derivatives_4h = align_derivatives_to_index(derivatives_rows_path, bars_4h.index)
    atr_item = _select_strongest_atr_baseline(
        bars_4h=bars_4h,
        bars_1d=bars_1d,
        derivatives_4h=derivatives_4h,
        initial_capital=initial_capital,
        cost_bps=base_cost_bps,
    )
    regime_frame = build_market_regime_frame(bars_4h)
    calendar_segments = _calendar_segment_review(
        atr_item,
        bars_4h=bars_4h,
        regime_frame=regime_frame,
        initial_capital=initial_capital,
    )
    regime_review = _regime_review(
        atr_item,
        bars_4h=bars_4h,
        regime_frame=regime_frame,
        initial_capital=initial_capital,
    )
    matrix = _segment_regime_matrix(
        atr_item,
        bars_4h=bars_4h,
        regime_frame=regime_frame,
        initial_capital=initial_capital,
    )
    drawdown = _drawdown_regime_attribution(
        atr_item,
        regime_frame=regime_frame,
        initial_capital=initial_capital,
    )
    failure_summary = _failure_summary(calendar_segments, regime_review, matrix)
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated.isoformat(),
        "status": "complete_research_only",
        "decision": "btc_atr_regime_failure_analysis_research_only_no_paper_no_live",
        "scope": "diagnose_when_handwritten_atr_channel_works_or_should_be_flat",
        "code_commit": _git_commit(),
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
            "bar_4h_start": _ts(bars_4h.index.min()) if len(bars_4h) else None,
            "bar_4h_end": _ts(bars_4h.index.max()) if len(bars_4h) else None,
            "completed_bar_rule": "1h completed bars only; 4h/1d derived from completed 1h chunks",
        },
        "atr_baseline": {
            "candidate_id": atr_item.spec.candidate_id,
            "variant_id": atr_item.spec.variant_id,
            "label": atr_item.spec.label,
            "params": atr_item.spec.params,
            "full_metrics": atr_item.metrics,
        },
        "regime_definition": {
            "point_in_time_rule": "regime labels use only completed 4h bars and rolling windows with shifted volatility cap",
            "labels": {
                "bull_trend": "EMA50 > EMA200, close > EMA200, EMA200 24-bar slope positive",
                "bear_or_drawdown": "EMA50 < EMA200 and close < EMA200",
                "high_volatility_risk": "24h realized volatility above trailing shifted 85% cap",
                "sideways_chop": "all other states",
            },
        },
        "calendar_segment_review": calendar_segments,
        "regime_review": regime_review,
        "segment_regime_matrix": matrix,
        "max_drawdown_regime_attribution": drawdown,
        "failure_summary": failure_summary,
        "guardrails": _guardrails(),
        "gate": {
            "paper_queue_write_allowed": False,
            "paper_candidate_created": False,
            "live_unlock_allowed": False,
            "live_order_allowed": False,
            "oms_access_allowed": False,
            "broker_access_allowed": False,
            "strategy_skeleton_generated": False,
            "reason": "regime failure analysis is diagnostic only; it does not create a tradable strategy",
        },
        "blockers": [],
        "warnings": _warnings(failure_summary),
        "outputs": {
            "json": _portable_path(report_path),
            "matrix_csv": _portable_path(matrix_path),
            "summary_cn": _portable_path(markdown_path),
        },
    }
    _write_json(report_path, report)
    _write_csv(matrix_path, _matrix_fieldnames(), matrix)
    _write_text(markdown_path, render_btc_atr_regime_failure_analysis_markdown(report))
    return report


def build_market_regime_frame(bars_4h: pd.DataFrame) -> pd.DataFrame:
    close = bars_4h["close"].astype(float)
    returns = close.pct_change().fillna(0.0)
    ema50 = close.ewm(span=50, adjust=False).mean()
    ema200 = close.ewm(span=200, adjust=False).mean()
    ema200_slope_24 = ema200.pct_change(24)
    realized_vol_24h = returns.rolling(6).std(ddof=0)
    vol_cap = realized_vol_24h.rolling(180, min_periods=60).quantile(0.85).shift(1)
    labels = pd.Series("sideways_chop", index=close.index, dtype=object)
    bull = (ema50 > ema200) & (close > ema200) & (ema200_slope_24 > 0.0)
    bear = (ema50 < ema200) & (close < ema200)
    high_vol = (realized_vol_24h > vol_cap) & vol_cap.notna()
    labels.loc[bull] = "bull_trend"
    labels.loc[bear] = "bear_or_drawdown"
    labels.loc[high_vol] = "high_volatility_risk"
    return pd.DataFrame(
        {
            "regime_label": labels,
            "close": close,
            "bar_return": returns,
            "ema50": ema50,
            "ema200": ema200,
            "ema200_slope_24": ema200_slope_24,
            "realized_vol_24h": realized_vol_24h,
            "vol_cap_85_shifted": vol_cap,
        },
        index=close.index,
    )


def _select_strongest_atr_baseline(
    *,
    bars_4h: pd.DataFrame,
    bars_1d: pd.DataFrame,
    derivatives_4h: pd.DataFrame,
    initial_capital: float,
    cost_bps: float,
) -> Any:
    rows = []
    for spec in simple_trend_rule_specs():
        if spec.family_id != "atr_channel":
            continue
        item = evaluate_rule(
            spec,
            bars_4h=bars_4h,
            bars_1d=bars_1d,
            derivatives_4h=derivatives_4h,
            initial_capital=initial_capital,
            cost_bps=cost_bps,
        )
        score = float(item.metrics["total_return_pct"]) + 10.0 * float(item.metrics["profit_factor"]) - float(item.metrics["max_drawdown_abs_pct"])
        rows.append((score, item))
    if not rows:
        raise ValueError("atr_channel_baseline_not_found")
    return sorted(rows, key=lambda row: (-row[0], row[1].spec.candidate_id))[0][1]


def _calendar_segment_review(
    item: Any,
    *,
    bars_4h: pd.DataFrame,
    regime_frame: pd.DataFrame,
    initial_capital: float,
) -> list[dict[str, Any]]:
    rows = []
    for segment_id, start, end, label_zh in SEGMENT_DEFINITIONS:
        start_ts = pd.Timestamp(start, tz="UTC")
        end_ts = pd.Timestamp(end, tz="UTC") if end else bars_4h.index.max() + pd.Timedelta(milliseconds=1)
        idx = bars_4h.index[(bars_4h.index >= start_ts) & (bars_4h.index < end_ts)]
        if len(idx) == 0:
            continue
        metrics = _slice_strategy_metrics(item, idx, initial_capital=initial_capital)
        market = _slice_market_metrics(regime_frame, idx, initial_capital=initial_capital)
        regime_mix = _regime_mix(regime_frame.loc[idx, "regime_label"])
        row = {
            "segment_id": segment_id,
            "label_zh": label_zh,
            "start": _ts(idx.min()),
            "end": _ts(idx.max()),
            "row_count": int(len(idx)),
            "strategy_metrics": metrics,
            "market_metrics": market,
            "regime_mix": regime_mix,
            "recommendation": _recommendation(metrics, min_rows=len(idx)),
            "reason": _recommendation_reason(metrics, market),
        }
        rows.append(row)
    return rows


def _regime_review(
    item: Any,
    *,
    bars_4h: pd.DataFrame,
    regime_frame: pd.DataFrame,
    initial_capital: float,
) -> list[dict[str, Any]]:
    rows = []
    for regime, positions in regime_frame.groupby("regime_label").groups.items():
        idx = pd.DatetimeIndex(positions).intersection(bars_4h.index)
        if len(idx) == 0:
            continue
        metrics = _slice_strategy_metrics(item, idx, initial_capital=initial_capital)
        market = _slice_market_metrics(regime_frame, idx, initial_capital=initial_capital)
        rows.append(
            {
                "regime_label": str(regime),
                "row_count": int(len(idx)),
                "row_share": _round(len(idx) / len(bars_4h) if len(bars_4h) else 0.0),
                "strategy_metrics": metrics,
                "market_metrics": market,
                "recommendation": _recommendation(metrics, min_rows=len(idx)),
                "reason": _recommendation_reason(metrics, market),
            }
        )
    return sorted(rows, key=lambda row: str(row["regime_label"]))


def _segment_regime_matrix(
    item: Any,
    *,
    bars_4h: pd.DataFrame,
    regime_frame: pd.DataFrame,
    initial_capital: float,
) -> list[dict[str, Any]]:
    rows = []
    for segment_id, start, end, label_zh in SEGMENT_DEFINITIONS:
        start_ts = pd.Timestamp(start, tz="UTC")
        end_ts = pd.Timestamp(end, tz="UTC") if end else bars_4h.index.max() + pd.Timedelta(milliseconds=1)
        segment_idx = bars_4h.index[(bars_4h.index >= start_ts) & (bars_4h.index < end_ts)]
        for regime in sorted(regime_frame["regime_label"].dropna().unique()):
            idx = segment_idx[regime_frame.loc[segment_idx, "regime_label"] == regime]
            if len(idx) < 10:
                continue
            metrics = _slice_strategy_metrics(item, idx, initial_capital=initial_capital)
            market = _slice_market_metrics(regime_frame, idx, initial_capital=initial_capital)
            rows.append(
                {
                    "segment_id": segment_id,
                    "segment_label_zh": label_zh,
                    "regime_label": str(regime),
                    "row_count": int(len(idx)),
                    "start": _ts(idx.min()),
                    "end": _ts(idx.max()),
                    "strategy_total_return_pct": metrics["total_return_pct"],
                    "strategy_profit_factor": metrics["profit_factor"],
                    "strategy_max_drawdown_abs_pct": metrics["max_drawdown_abs_pct"],
                    "average_exposure": metrics["average_exposure"],
                    "market_total_return_pct": market["total_return_pct"],
                    "recommendation": _recommendation(metrics, min_rows=len(idx)),
                    "reason": _recommendation_reason(metrics, market),
                }
            )
    return rows


def _drawdown_regime_attribution(item: Any, *, regime_frame: pd.DataFrame, initial_capital: float) -> dict[str, Any]:
    equity = item.equity
    if equity.empty:
        return {}
    running_peak = equity.cummax()
    drawdown = equity / running_peak - 1.0
    trough = drawdown.idxmin()
    peak = equity.loc[:trough].idxmax()
    recovery = equity.loc[trough:][equity.loc[trough:] >= float(equity.loc[peak])]
    recovery_time = recovery.index[0] if len(recovery) else None
    end = recovery_time or trough
    idx = item.returns.loc[peak:end].index
    regime_rows = []
    for regime, positions in regime_frame.loc[idx].groupby("regime_label").groups.items():
        sub_idx = pd.DatetimeIndex(positions)
        metrics = _slice_strategy_metrics(item, sub_idx, initial_capital=initial_capital)
        regime_rows.append(
            {
                "regime_label": str(regime),
                "row_count": int(len(sub_idx)),
                "row_share_in_drawdown": _round(len(sub_idx) / len(idx) if len(idx) else 0.0),
                "strategy_total_return_pct": metrics["total_return_pct"],
                "average_exposure": metrics["average_exposure"],
            }
        )
    return {
        "peak_time": _ts(peak),
        "trough_time": _ts(trough),
        "recovery_time": _ts(recovery_time) if recovery_time is not None else None,
        "duration_bars": int(len(idx)),
        "duration_days": _round((pd.Timestamp(end) - pd.Timestamp(peak)).total_seconds() / 86_400.0),
        "max_drawdown_pct": _round(float(drawdown.loc[trough]) * 100.0),
        "max_drawdown_abs_pct": _round(abs(float(drawdown.loc[trough])) * 100.0),
        "regime_contribution": sorted(regime_rows, key=lambda row: -float(row["row_share_in_drawdown"])),
    }


def _failure_summary(
    calendar_segments: Sequence[Mapping[str, Any]],
    regime_review: Sequence[Mapping[str, Any]],
    matrix: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    effective = [row for row in regime_review if row.get("recommendation") == "allow_atr_long"]
    conditional = [row for row in regime_review if row.get("recommendation") == "conditional_or_reduce_size"]
    flat = [row for row in regime_review if row.get("recommendation") == "prefer_flat"]
    bad_segments = [row for row in calendar_segments if row.get("recommendation") == "prefer_flat"]
    bad_matrix = [row for row in matrix if row.get("recommendation") == "prefer_flat"]
    return {
        "effective_regimes": [row["regime_label"] for row in effective],
        "conditional_regimes": [row["regime_label"] for row in conditional],
        "should_be_flat_regimes": [row["regime_label"] for row in flat],
        "should_be_flat_calendar_segments": [row["segment_id"] for row in bad_segments],
        "worst_segment_regime_cells": sorted(
            bad_matrix,
            key=lambda row: float(row["strategy_total_return_pct"]),
        )[:8],
        "operator_summary_zh": _operator_summary_zh(calendar_segments, regime_review, bad_matrix),
    }


def _slice_strategy_metrics(item: Any, index: pd.DatetimeIndex, *, initial_capital: float) -> dict[str, Any]:
    sub_returns = item.returns.loc[index]
    equity = float(initial_capital) * (1.0 + sub_returns).cumprod()
    return performance_metrics(
        strategy_returns=sub_returns,
        equity=equity,
        exposure=item.exposure.loc[index],
        turnover=item.turnover.loc[index],
        cost=item.cost.loc[index],
        interval=BASE_INTERVAL,
        initial_capital=initial_capital,
    )


def _slice_market_metrics(regime_frame: pd.DataFrame, index: pd.DatetimeIndex, *, initial_capital: float) -> dict[str, Any]:
    returns = regime_frame.loc[index, "bar_return"].fillna(0.0)
    equity = float(initial_capital) * (1.0 + returns).cumprod()
    exposure = pd.Series(1.0, index=index)
    zero = pd.Series(0.0, index=index)
    return performance_metrics(
        strategy_returns=returns,
        equity=equity,
        exposure=exposure,
        turnover=zero,
        cost=zero,
        interval=BASE_INTERVAL,
        initial_capital=initial_capital,
    )


def _regime_mix(labels: pd.Series) -> dict[str, float]:
    if labels.empty:
        return {}
    counts = labels.value_counts(normalize=True)
    return {str(key): _round(float(value)) for key, value in counts.sort_index().items()}


def _recommendation(metrics: Mapping[str, Any], *, min_rows: int) -> str:
    if min_rows < 30:
        return "insufficient_rows"
    total = float(metrics.get("total_return_pct", 0.0))
    pf = float(metrics.get("profit_factor", 0.0))
    drawdown = float(metrics.get("max_drawdown_abs_pct", 0.0))
    exposure = float(metrics.get("average_exposure", 0.0))
    if total > 0.0 and pf >= 1.05 and drawdown <= 20.0 and exposure >= 0.03:
        return "allow_atr_long"
    if total > 0.0 and pf >= 1.0 and drawdown <= 30.0:
        return "conditional_or_reduce_size"
    return "prefer_flat"


def _recommendation_reason(metrics: Mapping[str, Any], market: Mapping[str, Any]) -> str:
    total = float(metrics.get("total_return_pct", 0.0))
    pf = float(metrics.get("profit_factor", 0.0))
    drawdown = float(metrics.get("max_drawdown_abs_pct", 0.0))
    exposure = float(metrics.get("average_exposure", 0.0))
    market_return = float(market.get("total_return_pct", 0.0))
    if total <= 0.0:
        return f"ATR segment return non-positive ({_round(total)}%) while market return was {_round(market_return)}%"
    if pf < 1.0:
        return f"profit factor below 1 ({_round(pf)})"
    if drawdown > 30.0:
        return f"drawdown too high ({_round(drawdown)}%)"
    if exposure < 0.03:
        return "signal almost never participates"
    if pf < 1.05:
        return f"thin edge PF={_round(pf)}"
    return "positive return, acceptable PF and controlled drawdown"


def render_btc_atr_regime_failure_analysis_markdown(report: Mapping[str, Any]) -> str:
    gate = _mapping(report.get("gate"))
    baseline = _mapping(report.get("atr_baseline"))
    failure = _mapping(report.get("failure_summary"))
    drawdown = _mapping(report.get("max_drawdown_regime_attribution"))
    lines = [
        "# BTC ATR 行情分段失效分析",
        "",
        f"- 状态：`{report.get('status')}`",
        f"- 决策：`{report.get('decision')}`",
        f"- ATR 基线：`{baseline.get('candidate_id')}`",
        f"- paper 队列：`{gate.get('paper_queue_write_allowed')}`",
        f"- live 解锁：`{gate.get('live_unlock_allowed')}`",
        "",
        "## 结论",
        "",
        f"- {failure.get('operator_summary_zh')}",
        f"- 应该空仓的年度段：`{', '.join(failure.get('should_be_flat_calendar_segments', []))}`",
        f"- 应该空仓的行情 regime：`{', '.join(failure.get('should_be_flat_regimes', []))}`",
        f"- 可考虑允许 ATR 做多的 regime：`{', '.join(failure.get('effective_regimes', []))}`",
        "",
        "## 年份段",
        "",
    ]
    for row in report.get("calendar_segment_review", []):
        metrics = _mapping(row.get("strategy_metrics"))
        market = _mapping(row.get("market_metrics"))
        lines.append(
            f"- `{row.get('segment_id')}`：ATR `{metrics.get('total_return_pct')}%` / PF `{metrics.get('profit_factor')}` / 回撤 `{metrics.get('max_drawdown_abs_pct')}%`；"
            f"市场 `{market.get('total_return_pct')}%`；建议 `{row.get('recommendation')}`；原因：{row.get('reason')}。"
        )
    lines.extend(["", "## 行情 Regime", ""])
    for row in report.get("regime_review", []):
        metrics = _mapping(row.get("strategy_metrics"))
        market = _mapping(row.get("market_metrics"))
        lines.append(
            f"- `{row.get('regime_label')}`：ATR `{metrics.get('total_return_pct')}%` / PF `{metrics.get('profit_factor')}` / "
            f"回撤 `{metrics.get('max_drawdown_abs_pct')}%`；市场 `{market.get('total_return_pct')}%`；建议 `{row.get('recommendation')}`。"
        )
    lines.extend(
        [
            "",
            "## 最大回撤",
            "",
            f"- 峰值：`{drawdown.get('peak_time')}`",
            f"- 谷底：`{drawdown.get('trough_time')}`",
            f"- 最大回撤：`{drawdown.get('max_drawdown_abs_pct')}%`",
            f"- 持续天数：`{drawdown.get('duration_days')}`",
            "",
            "## 边界",
            "",
            "- 本报告只做失效诊断，不生成策略骨架。",
            "- 不写 paper 队列，不解锁 live，不接 broker/OMS。",
            "- 如果后续加 regime filter，必须重新做 walk-forward、holdout、成本压力和人工复核。",
        ]
    )
    return "\n".join(lines) + "\n"


def _operator_summary_zh(
    calendar_segments: Sequence[Mapping[str, Any]],
    regime_review: Sequence[Mapping[str, Any]],
    bad_matrix: Sequence[Mapping[str, Any]],
) -> str:
    bad_segments = [str(row.get("segment_id")) for row in calendar_segments if row.get("recommendation") == "prefer_flat"]
    bad_regimes = [str(row.get("regime_label")) for row in regime_review if row.get("recommendation") == "prefer_flat"]
    good_regimes = [str(row.get("regime_label")) for row in regime_review if row.get("recommendation") == "allow_atr_long"]
    worst = bad_matrix[0] if bad_matrix else {}
    return (
        "ATR 更像只适合部分趋势段的工具；"
        f"空仓优先段={bad_segments or ['none']}；"
        f"空仓优先 regime={bad_regimes or ['none']}；"
        f"允许做多 regime={good_regimes or ['none']}；"
        f"最差组合={worst.get('segment_id')}/{worst.get('regime_label')}。"
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


def _warnings(failure_summary: Mapping[str, Any]) -> list[str]:
    warnings = ["btc_atr_regime_failure_analysis_research_only_no_paper_no_live"]
    if failure_summary.get("should_be_flat_regimes"):
        warnings.append("atr_has_regime_failure_conditions")
    if failure_summary.get("should_be_flat_calendar_segments"):
        warnings.append("atr_has_calendar_segment_failure_conditions")
    return warnings


def _matrix_fieldnames() -> list[str]:
    return [
        "segment_id",
        "segment_label_zh",
        "regime_label",
        "row_count",
        "start",
        "end",
        "strategy_total_return_pct",
        "strategy_profit_factor",
        "strategy_max_drawdown_abs_pct",
        "average_exposure",
        "market_total_return_pct",
        "recommendation",
        "reason",
    ]


def _write_csv(path: Path, fieldnames: Sequence[str], rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fieldnames), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False), encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _round(value: float, digits: int = 6) -> float:
    if value is None or not math.isfinite(float(value)):
        return 0.0
    return round(float(value), digits)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _portable_path(path: Path) -> str:
    return str(path).replace("\\", "/")


def _ts(value: Any) -> str:
    return pd.Timestamp(value).isoformat()


def _git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return "unknown"
