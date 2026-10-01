from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from quant_shared.forecasting.contracts import ForecastUsage, TimeSeriesForecastRequest
from quant_shared.forecasting.timesfm_adapter import (
    TIMESFM_DEFAULT_CHECKPOINT,
    TimesFMForecastAdapter,
    inspect_timesfm_environment,
)
from scripts.research.run_btc_timesfm_smoke_forecast import ceil_to_patch_multiple, parse_utc


SCHEMA_VERSION = "btc_timesfm_vs_trend_baseline_oos_v1"
DEFAULT_DB_PATH = Path("data/market_data.sqlite")
DEFAULT_OUTPUT_DIR = Path("artifacts/shared_forecasting/timesfm/btc_vs_trend_baseline_latest")


@dataclass(frozen=True)
class DecisionPoint:
    row_index: int
    decision_time_utc: datetime
    future_time_utc: datetime
    close: float
    future_close: float
    future_return: float


def load_market_rows(*, db_path: Path, exchange: str, symbol: str, interval: str) -> list[dict[str, Any]]:
    if not db_path.exists():
        raise FileNotFoundError(f"market data sqlite not found: {db_path}")
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            """
            select open_time, close_time, open, high, low, close, volume
            from market_klines
            where exchange = ?
              and upper(symbol) = ?
              and interval = ?
            order by open_time_ms
            """,
            [exchange, symbol.upper(), interval],
        ).fetchall()
    finally:
        conn.close()
    if not rows:
        raise ValueError(f"no rows found for {exchange}:{symbol}:{interval}")
    market_rows: list[dict[str, Any]] = []
    closes: list[float] = []
    for row in rows:
        try:
            close = float(row[5])
            market_rows.append(
                {
                    "open_time_utc": parse_utc(str(row[0])),
                    "close_time_utc": parse_utc(str(row[1])),
                    "open": float(row[2]),
                    "high": float(row[3]),
                    "low": float(row[4]),
                    "close": close,
                    "volume": float(row[6]),
                }
            )
            closes.append(close)
        except (TypeError, ValueError):
            continue
    momentum_24h: list[float | None] = []
    for index, close in enumerate(closes):
        if index < 24:
            momentum_24h.append(None)
        else:
            previous = closes[index - 24]
            momentum_24h.append(close / previous - 1.0 if previous != 0.0 else None)
    z24 = rolling_zscore(momentum_24h, 24)
    z48 = rolling_zscore(momentum_24h, 48)
    for row, momentum, value_z24, value_z48 in zip(market_rows, momentum_24h, z24, z48):
        row["momentum_24h"] = momentum
        row["momentum_24h_z24"] = value_z24
        row["momentum_24h_z48"] = value_z48
    return market_rows


def rolling_zscore(values: Sequence[float | None], window: int) -> list[float | None]:
    output: list[float | None] = []
    for index in range(len(values)):
        if index + 1 < window:
            output.append(None)
            continue
        window_values = values[index - window + 1 : index + 1]
        if any(value is None or not math.isfinite(float(value)) for value in window_values):
            output.append(None)
            continue
        numbers = [float(value) for value in window_values if value is not None]
        mean = sum(numbers) / len(numbers)
        variance = sum((value - mean) ** 2 for value in numbers) / len(numbers)
        std = math.sqrt(variance)
        output.append((numbers[-1] - mean) / std if std > 0.0 else None)
    return output


def select_decision_points(
    frame: Sequence[dict[str, Any]],
    *,
    lookback_hours: int,
    horizon_hours: int,
    holdout_days: int,
    stride_hours: int,
    max_decisions: int,
) -> list[DecisionPoint]:
    if lookback_hours < 64:
        raise ValueError("lookback_hours must be >= 64 for TimesFM context and trend zscore features.")
    if horizon_hours <= 0:
        raise ValueError("horizon_hours must be positive.")
    if stride_hours <= 0:
        raise ValueError("stride_hours must be positive.")
    if max_decisions <= 1:
        raise ValueError("max_decisions must be > 1.")
    max_future_index = len(frame) - 1
    if max_future_index <= lookback_hours + horizon_hours:
        raise ValueError("insufficient rows for lookback and future horizon.")

    max_decision_time = frame[max_future_index - horizon_hours]["close_time_utc"]
    holdout_start = max_decision_time - timedelta(days=int(holdout_days))
    candidates: list[DecisionPoint] = []
    for idx in range(lookback_hours - 1, max_future_index - horizon_hours + 1, stride_hours):
        decision_time = frame[idx]["close_time_utc"]
        if decision_time < holdout_start:
            continue
        close = float(frame[idx]["close"])
        future_close = float(frame[idx + horizon_hours]["close"])
        candidates.append(
            DecisionPoint(
                row_index=idx,
                decision_time_utc=decision_time,
                future_time_utc=frame[idx + horizon_hours]["close_time_utc"],
                close=close,
                future_close=future_close,
                future_return=future_close / close - 1.0,
            )
        )
    if len(candidates) < 4:
        raise ValueError(f"insufficient OOS decision points: got {len(candidates)}.")
    if len(candidates) <= max_decisions:
        return candidates
    positions = sorted({round(item) for item in _linspace(0, len(candidates) - 1, max_decisions)})
    return [candidates[position] for position in positions]


def _linspace(start: int, stop: int, count: int) -> list[float]:
    if count == 1:
        return [float(start)]
    step = (stop - start) / float(count - 1)
    return [start + index * step for index in range(count)]


def build_oos_rows(
    *,
    frame: Sequence[dict[str, Any]],
    decisions: Sequence[DecisionPoint],
    adapter: TimesFMForecastAdapter,
    symbol: str,
    interval: str,
    lookback_hours: int,
    horizon_hours: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for decision in decisions:
        start = decision.row_index - lookback_hours + 1
        context = frame[start : decision.row_index + 1]
        request = TimeSeriesForecastRequest(
            asset_namespace="btc",
            instrument_id=symbol,
            series_name="close",
            frequency=interval,
            decision_time_utc=decision.decision_time_utc,
            history_timestamps_utc=[row["close_time_utc"] for row in context],
            history_values=[row["close"] for row in context],
            horizon_steps=int(horizon_hours),
            allowed_usage=ForecastUsage.RESEARCH_ONLY,
            metadata={
                "source_table": "market_klines",
                "completed_bar_policy": "context close_time <= decision_time",
            },
        )
        result = adapter.forecast(request)
        forecast_close = float(result.point_forecast[-1])
        rows.append(
            {
                "decision_time_utc": decision.decision_time_utc.isoformat(),
                "future_time_utc": decision.future_time_utc.isoformat(),
                "close": decision.close,
                "future_close": decision.future_close,
                "future_return": decision.future_return,
                "timesfm_forecast_close_h24": forecast_close,
                "timesfm_score_return_h24": forecast_close / decision.close - 1.0,
                "btc_trend_baseline_momentum_24h_z24": frame[decision.row_index]["momentum_24h_z24"],
                "btc_trend_baseline_momentum_24h_z48": frame[decision.row_index]["momentum_24h_z48"],
            }
        )
    return rows


def split_calibration_evaluation(rows: Sequence[dict[str, Any]], calibration_fraction: float) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not 0.1 <= calibration_fraction <= 0.8:
        raise ValueError("calibration_fraction must be in [0.1, 0.8].")
    split = max(2, min(len(rows) - 2, int(round(len(rows) * calibration_fraction))))
    return list(rows[:split]), list(rows[split:])


def evaluate_score(
    *,
    model_id: str,
    score_field: str,
    calibration_rows: Sequence[dict[str, Any]],
    evaluation_rows: Sequence[dict[str, Any]],
    fee_bps: float,
    slippage_bps: float,
) -> dict[str, Any]:
    calibration_pair = [
        row
        for row in calibration_rows
        if is_finite(row.get(score_field)) and is_finite(row.get("future_return"))
    ]
    evaluation_pair = [
        row
        for row in evaluation_rows
        if is_finite(row.get(score_field)) and is_finite(row.get("future_return"))
    ]
    if len(calibration_pair) < 2 or len(evaluation_pair) < 2:
        return {
            "model_id": model_id,
            "score_field": score_field,
            "status": "blocked",
            "reason": "insufficient_calibration_or_evaluation_rows",
        }
    calibration_scores = [float(row[score_field]) for row in calibration_pair]
    calibration_returns = [float(row["future_return"]) for row in calibration_pair]
    evaluation_scores = [float(row[score_field]) for row in evaluation_pair]
    evaluation_returns = [float(row["future_return"]) for row in evaluation_pair]
    calibration_ic = rank_ic(calibration_scores, calibration_returns)
    direction = 1 if calibration_ic >= 0.0 else -1
    adjusted_calibration_score = [value * direction for value in calibration_scores]
    threshold = quantile(adjusted_calibration_score, 0.70)
    adjusted_eval_score = [value * direction for value in evaluation_scores]
    signal = [1.0 if value > threshold else 0.0 for value in adjusted_eval_score]
    base_metrics = strategy_metrics(
        signal=signal,
        forward_returns=evaluation_returns,
        fee_bps=fee_bps,
        slippage_bps=slippage_bps,
    )
    raw_direction_accuracy = directional_accuracy(evaluation_scores, evaluation_returns)
    return {
        "model_id": model_id,
        "score_field": score_field,
        "status": "complete",
        "calibration": {
            "rows": int(len(calibration_pair)),
            "rank_ic": round(calibration_ic, 6),
            "direction": direction,
            "threshold_q70_after_direction": round(threshold, 10),
        },
        "evaluation": {
            "rows": int(len(evaluation_pair)),
            "rank_ic": round(rank_ic(evaluation_scores, evaluation_returns), 6),
            "raw_direction_accuracy": round(raw_direction_accuracy, 6),
            **base_metrics,
        },
        "cost_stress": {
            "base": base_metrics,
            "fees_2x": strategy_metrics(signal=signal, forward_returns=evaluation_returns, fee_bps=fee_bps * 2.0, slippage_bps=slippage_bps),
            "slippage_2x": strategy_metrics(signal=signal, forward_returns=evaluation_returns, fee_bps=fee_bps, slippage_bps=slippage_bps * 2.0),
            "costs_2x": strategy_metrics(signal=signal, forward_returns=evaluation_returns, fee_bps=fee_bps * 2.0, slippage_bps=slippage_bps * 2.0),
        },
    }


def is_finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def rank_ic(score: Sequence[float], label: Sequence[float]) -> float:
    pairs = [(float(s), float(y)) for s, y in zip(score, label) if is_finite(s) and is_finite(y)]
    if len(pairs) < 3 or len({item[0] for item in pairs}) < 2 or len({item[1] for item in pairs}) < 2:
        return 0.0
    score_ranks = ranks([item[0] for item in pairs])
    label_ranks = ranks([item[1] for item in pairs])
    value = correlation(score_ranks, label_ranks)
    if value != value:
        return 0.0
    return float(value)


def ranks(values: Sequence[float]) -> list[float]:
    sorted_pairs = sorted((float(value), index) for index, value in enumerate(values))
    result = [0.0] * len(values)
    pos = 0
    while pos < len(sorted_pairs):
        end = pos + 1
        while end < len(sorted_pairs) and sorted_pairs[end][0] == sorted_pairs[pos][0]:
            end += 1
        average_rank = (pos + 1 + end) / 2.0
        for _, original_index in sorted_pairs[pos:end]:
            result[original_index] = average_rank
        pos = end
    return result


def correlation(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right) or len(left) < 2:
        return 0.0
    left_mean = sum(left) / len(left)
    right_mean = sum(right) / len(right)
    numerator = sum((x - left_mean) * (y - right_mean) for x, y in zip(left, right))
    left_var = sum((x - left_mean) ** 2 for x in left)
    right_var = sum((y - right_mean) ** 2 for y in right)
    denominator = math.sqrt(left_var * right_var)
    return numerator / denominator if denominator > 0.0 else 0.0


def directional_accuracy(score: Sequence[float], label: Sequence[float]) -> float:
    pairs = [(float(s), float(y)) for s, y in zip(score, label) if is_finite(s) and is_finite(y)]
    if not pairs:
        return 0.0
    return sum(1 for s, y in pairs if (s > 0.0) == (y > 0.0)) / len(pairs)


def strategy_metrics(*, signal: Sequence[float], forward_returns: Sequence[float], fee_bps: float, slippage_bps: float) -> dict[str, Any]:
    signal_values = [float(value) if is_finite(value) else 0.0 for value in signal]
    return_values = [float(value) if is_finite(value) else 0.0 for value in forward_returns]
    turnover: list[float] = []
    previous = 0.0
    for value in signal_values:
        turnover.append(abs(value - previous))
        previous = value
    cost_bps = float(fee_bps) + float(slippage_bps)
    returns = [s * r - t * (cost_bps / 10_000.0) for s, r, t in zip(signal_values, return_values, turnover)]
    return {
        "profit_factor": profit_factor(returns),
        "total_return": round(compound_return(returns), 6),
        "max_drawdown": round(max_drawdown(returns), 6),
        "hit_rate": round(sum(1 for value in returns if value > 0.0) / len(returns), 6) if returns else 0.0,
        "exposure": round(sum(signal_values) / len(signal_values), 6) if signal_values else 0.0,
        "turnover": round(sum(turnover) / len(turnover), 6) if turnover else 0.0,
        "cost_bps": round(cost_bps, 6),
    }


def quantile(values: Sequence[float], q: float) -> float:
    if not values:
        return 0.0
    sorted_values = sorted(float(value) for value in values)
    position = (len(sorted_values) - 1) * q
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return sorted_values[lower]
    weight = position - lower
    return sorted_values[lower] * (1.0 - weight) + sorted_values[upper] * weight


def compound_return(returns: Sequence[float]) -> float:
    equity = 1.0
    for value in returns:
        equity *= 1.0 + float(value)
    return equity - 1.0


def profit_factor(returns: Sequence[float]) -> float:
    values = [float(value) if is_finite(value) else 0.0 for value in returns]
    gains = sum(value for value in values if value > 0.0)
    losses = abs(sum(value for value in values if value < 0.0))
    if losses <= 1e-12:
        return 999.0 if gains > 0.0 else 0.0
    return round(gains / losses, 6)


def max_drawdown(returns: Sequence[float]) -> float:
    peak = 1.0
    equity = 1.0
    worst = 0.0
    for value in returns:
        equity *= 1.0 + (float(value) if is_finite(value) else 0.0)
        peak = max(peak, equity)
        worst = min(worst, equity / peak - 1.0 if peak > 0.0 else 0.0)
    return worst


def rows_digest(rows: Sequence[dict[str, Any]]) -> str:
    payload = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def write_rows_csv(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    fieldnames = [
        "decision_time_utc",
        "future_time_utc",
        "close",
        "future_close",
        "future_return",
        "timesfm_forecast_close_h24",
        "timesfm_score_return_h24",
        "btc_trend_baseline_momentum_24h_z24",
        "btc_trend_baseline_momentum_24h_z48",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key) for key in fieldnames})


def build_chinese_markdown(report: dict[str, Any]) -> str:
    ranking = report["comparison"]["ranking_by_profit_factor_then_ic"]
    top = ranking[0] if ranking else {}
    decision = report["research_decision"]
    lines = [
        "# BTC TimesFM vs 趋势基线样本外诊断",
        "",
        f"- 状态：`{report['status']}`",
        f"- 决策点：`{report['input']['decision_count']}`，校准：`{report['validation_design']['calibration_rows']}`，评估：`{report['validation_design']['evaluation_rows']}`",
        f"- 窗口：`{report['input']['first_decision_time_utc']}` 到 `{report['input']['last_decision_time_utc']}`",
        f"- 诊断排序第一：`{top.get('model_id', 'n/a')}`，PF：`{top.get('profit_factor', 'n/a')}`，IC：`{top.get('rank_ic', 'n/a')}`",
        f"- 研究结论：`{decision['status']}`",
        f"- 中文解释：{decision['summary_cn']}",
        "",
        "## 结论边界",
        "",
        "- 这是 P1 研究诊断，不是策略晋级。",
        "- 结果不写 paper 队列，不解锁 live，不触达 OMS/broker。",
        "- 样本点少，只能决定下一步是否值得扩大验证。",
        "",
    ]
    return "\n".join(lines)


def build_research_decision(metrics: Sequence[dict[str, Any]]) -> dict[str, Any]:
    complete = [row for row in metrics if row.get("status") == "complete"]
    qualified = [
        row
        for row in complete
        if float(row.get("evaluation", {}).get("profit_factor", 0.0)) >= 1.0
        and float(row.get("evaluation", {}).get("total_return", 0.0)) > 0.0
        and float(row.get("evaluation", {}).get("exposure", 0.0)) > 0.0
    ]
    timesfm = next((row for row in complete if row.get("model_id") == "timesfm_zero_shot_h24"), {})
    timesfm_eval = timesfm.get("evaluation", {}) if isinstance(timesfm, dict) else {}
    if qualified:
        return {
            "status": "HAS_DIAGNOSTIC_WINNER_REQUIRES_EXPANDED_RESEARCH",
            "paper_candidate_allowed": False,
            "best_model_id": qualified[0]["model_id"],
            "summary_cn": "有模型在小样本诊断里通过 PF/收益粗筛，但仍必须扩大样本、做 walk-forward、行情分段和回撤归因。",
        }
    if float(timesfm_eval.get("exposure", 0.0)) == 0.0:
        return {
            "status": "NO_MODEL_QUALIFIES_TIMESFM_NO_THRESHOLD_TRADES",
            "paper_candidate_allowed": False,
            "best_model_id": "",
            "summary_cn": "TimesFM 有预测排序信息，但按校准阈值没有触发交易；趋势基线有交易但样本外净表现为负，不能进入 paper 复核。",
        }
    return {
        "status": "NO_MODEL_QUALIFIES_FOR_PAPER_REVIEW",
        "paper_candidate_allowed": False,
        "best_model_id": "",
        "summary_cn": "本批次没有模型同时满足正收益、PF>=1 和非零暴露，不能进入 paper 复核。",
    }


def run_comparison(
    *,
    db_path: Path = DEFAULT_DB_PATH,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    exchange: str = "binance_spot",
    symbol: str = "BTCUSDT",
    interval: str = "1h",
    lookback_hours: int = 720,
    horizon_hours: int = 24,
    holdout_days: int = 90,
    stride_hours: int = 24,
    max_decisions: int = 12,
    calibration_fraction: float = 0.34,
    fee_bps: float = 5.0,
    slippage_bps: float = 4.0,
    checkpoint_repo_id: str = TIMESFM_DEFAULT_CHECKPOINT,
) -> dict[str, Any]:
    generated_at = datetime.now(timezone.utc)
    frame = load_market_rows(db_path=db_path, exchange=exchange, symbol=symbol, interval=interval)
    decisions = select_decision_points(
        frame,
        lookback_hours=lookback_hours,
        horizon_hours=horizon_hours,
        holdout_days=holdout_days,
        stride_hours=stride_hours,
        max_decisions=max_decisions,
    )
    adapter = TimesFMForecastAdapter(
        checkpoint_repo_id=checkpoint_repo_id,
        max_context=ceil_to_patch_multiple(lookback_hours),
        max_horizon=ceil_to_patch_multiple(horizon_hours),
        torch_compile=False,
    )
    rows = build_oos_rows(
        frame=frame,
        decisions=decisions,
        adapter=adapter,
        symbol=symbol,
        interval=interval,
        lookback_hours=lookback_hours,
        horizon_hours=horizon_hours,
    )
    calibration_rows, evaluation_rows = split_calibration_evaluation(rows, calibration_fraction)
    score_specs = [
        ("timesfm_zero_shot_h24", "timesfm_score_return_h24"),
        ("btc_trend_baseline_momentum_24h_z24", "btc_trend_baseline_momentum_24h_z24"),
        ("btc_trend_baseline_momentum_24h_z48", "btc_trend_baseline_momentum_24h_z48"),
    ]
    metrics = [
        evaluate_score(
            model_id=model_id,
            score_field=score_field,
            calibration_rows=calibration_rows,
            evaluation_rows=evaluation_rows,
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
        )
        for model_id, score_field in score_specs
    ]
    ranking = sorted(
        [
            {
                "model_id": row["model_id"],
                "profit_factor": row.get("evaluation", {}).get("profit_factor", -1.0),
                "rank_ic": row.get("evaluation", {}).get("rank_ic", -1.0),
                "total_return": row.get("evaluation", {}).get("total_return", 0.0),
                "max_drawdown": row.get("evaluation", {}).get("max_drawdown", 0.0),
            }
            for row in metrics
            if row.get("status") == "complete"
        ],
        key=lambda item: (float(item["profit_factor"]), float(item["rank_ic"])),
        reverse=True,
    )
    research_decision = build_research_decision(metrics)
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "btc_timesfm_vs_trend_baseline_oos_report.json"
    rows_path = output_dir / "btc_timesfm_vs_trend_baseline_oos_rows.csv"
    markdown_path = output_dir / "btc_timesfm_vs_trend_baseline_oos_summary_cn.md"
    report = {
        "schema_version": SCHEMA_VERSION,
        "status": "COMPLETE_RESEARCH_ONLY_DIAGNOSTIC",
        "generated_at_utc": generated_at.isoformat(),
        "scope": "btc_timesfm_vs_existing_trend_baseline_oos_comparison",
        "input": {
            "db_path": str(db_path),
            "exchange": exchange,
            "symbol": symbol,
            "interval": interval,
            "market_row_count": int(len(frame)),
            "market_start_time_utc": frame[0]["close_time_utc"].isoformat(),
            "market_end_time_utc": frame[-1]["close_time_utc"].isoformat(),
            "lookback_hours": lookback_hours,
            "horizon_hours": horizon_hours,
            "holdout_days": holdout_days,
            "stride_hours": stride_hours,
            "max_decisions": max_decisions,
            "decision_count": len(rows),
            "first_decision_time_utc": rows[0]["decision_time_utc"],
            "last_decision_time_utc": rows[-1]["decision_time_utc"],
            "row_digest_sha256": rows_digest(rows),
        },
        "validation_design": {
            "oos_policy": "each decision uses only completed bars with close_time <= decision_time",
            "label": "future 24h close-to-close return",
            "calibration_policy": "threshold and factor direction calibrated only on earliest sampled OOS decisions",
            "calibration_fraction": calibration_fraction,
            "calibration_rows": len(calibration_rows),
            "evaluation_rows": len(evaluation_rows),
            "trading_diagnostic": "daily non-overlapping long/flat threshold strategy, diagnostic only",
            "cost_model": {
                "fee_bps": fee_bps,
                "slippage_bps": slippage_bps,
                "base_cost_bps": fee_bps + slippage_bps,
            },
        },
        "model": {
            "timesfm": {
                "checkpoint_repo_id": checkpoint_repo_id,
                "environment": inspect_timesfm_environment(),
                "usage": "zero_shot_research_only",
            },
            "trend_baselines": [
                {
                    "baseline_id": "btc_trend_baseline_momentum_24h_z24",
                    "definition": "rolling_z(momentum_24h, window=24), using data visible at decision_time",
                },
                {
                    "baseline_id": "btc_trend_baseline_momentum_24h_z48",
                    "definition": "rolling_z(momentum_24h, window=48), using data visible at decision_time",
                },
            ],
        },
        "comparison": {
            "metrics": metrics,
            "ranking_by_profit_factor_then_ic": ranking,
        },
        "research_decision": research_decision,
        "safety_flags": {
            "paper_queue_write_allowed": False,
            "live_unlock_allowed": False,
            "oms_access_allowed": False,
            "broker_access_allowed": False,
            "order_intent_allowed": False,
        },
        "gate": {
            "paper_candidate_allowed": bool(research_decision["paper_candidate_allowed"]),
            "live_allowed": False,
            "reason": "diagnostic comparison only; sample is small and no full walk-forward/regime attribution has passed",
        },
        "limitations": [
            "small sampled OOS decision count; expand before any paper review",
            "TimesFM is used zero-shot without BTC-specific calibration",
            "only BTC spot 1H OHLCV close series is used; derivatives sentiment is not included in this comparison",
            "diagnostic long/flat returns are not a ledger backtest",
        ],
        "report_paths": {
            "json": str(report_path),
            "rows_csv": str(rows_path),
            "summary_cn": str(markdown_path),
        },
    }
    write_rows_csv(rows_path, rows)
    markdown_path.write_text(build_chinese_markdown(report), encoding="utf-8")
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare BTC TimesFM zero-shot forecasts against BTC trend baselines.")
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--exchange", default="binance_spot")
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--interval", default="1h")
    parser.add_argument("--lookback-hours", type=int, default=720)
    parser.add_argument("--horizon-hours", type=int, default=24)
    parser.add_argument("--holdout-days", type=int, default=90)
    parser.add_argument("--stride-hours", type=int, default=24)
    parser.add_argument("--max-decisions", type=int, default=12)
    parser.add_argument("--calibration-fraction", type=float, default=0.34)
    parser.add_argument("--fee-bps", type=float, default=5.0)
    parser.add_argument("--slippage-bps", type=float, default=4.0)
    parser.add_argument("--checkpoint-repo-id", default=TIMESFM_DEFAULT_CHECKPOINT)
    args = parser.parse_args()
    report = run_comparison(
        db_path=args.db_path,
        output_dir=args.output_dir,
        exchange=args.exchange,
        symbol=args.symbol,
        interval=args.interval,
        lookback_hours=args.lookback_hours,
        horizon_hours=args.horizon_hours,
        holdout_days=args.holdout_days,
        stride_hours=args.stride_hours,
        max_decisions=args.max_decisions,
        calibration_fraction=args.calibration_fraction,
        fee_bps=args.fee_bps,
        slippage_bps=args.slippage_bps,
        checkpoint_repo_id=args.checkpoint_repo_id,
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "ranking": report["comparison"]["ranking_by_profit_factor_then_ic"],
                "report_paths": report["report_paths"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
