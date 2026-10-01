from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from quant_shared.forecasting.baseline_adapter import DriftForecastAdapter  # noqa: E402
from quant_shared.forecasting.contracts import (  # noqa: E402
    FORECASTING_CONTRACT_VERSION,
    ForecastModelAdapter,
    ForecastUsage,
    TimeSeriesForecastRequest,
)
from quant_shared.forecasting.timesfm_adapter import (  # noqa: E402
    TIMESFM_DEFAULT_CHECKPOINT,
    TimesFMForecastAdapter,
    inspect_timesfm_environment,
    is_timesfm_available,
)
from quant_us.research.us_etf_macro_momentum_rotation import (  # noqa: E402
    UsEtfMacroMomentumRotationConfig,
    build_price_matrix_from_bars,
    run_us_etf_macro_momentum_rotation,
)
from scripts.build_us_etf_macro_rotation_research_report import (  # noqa: E402
    DEFAULT_EXTERNAL_DATA_LAKE,
    DEFAULT_TIINGO_EOD_LAKE,
    _load_eod_kline_lake_bars,
    _load_macro_data,
)


SCHEMA_VERSION = "us_equity_shared_forecast_vs_baseline_smoke_v1"
DEFAULT_OUTPUT_DIR = Path("artifacts/shared_forecasting/us_equity/latest")


@dataclass(frozen=True)
class DecisionPoint:
    decision_index: int
    future_index: int
    decision_time_utc: pd.Timestamp
    future_time_utc: pd.Timestamp


def run_us_equity_shared_forecast_smoke(
    *,
    repo_root: Path | None = None,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    prices: pd.DataFrame | None = None,
    macro_data: pd.DataFrame | None = None,
    adapter: ForecastModelAdapter | None = None,
    adapter_mode: str = "drift",
    checkpoint_repo_id: str = TIMESFM_DEFAULT_CHECKPOINT,
    config: UsEtfMacroMomentumRotationConfig | None = None,
    tiingo_data_lake: Path | None = DEFAULT_TIINGO_EOD_LAKE,
    external_data_lake: Path | None = DEFAULT_EXTERNAL_DATA_LAKE,
    lookback_days: int = 252,
    horizon_days: int = 21,
    holdout_days: int = 365,
    max_decisions: int = 12,
    top_n: int | None = None,
    cost_bps: float = 10.0,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    cfg = config or UsEtfMacroMomentumRotationConfig()
    generated_at = datetime.now(timezone.utc)
    price_matrix, price_source, price_coverage = _resolve_price_matrix(
        root=root,
        prices=prices,
        cfg=cfg,
        tiingo_data_lake=tiingo_data_lake,
        external_data_lake=external_data_lake,
    )
    if macro_data is None:
        macro_df, macro_status, macro_path = _load_macro_data(root, None, external_data_lake=external_data_lake)
    else:
        macro_df = macro_data
        macro_status = "provided"
        macro_path = None
    symbols = list(cfg.required_symbols())
    decisions = _select_month_end_decisions(
        price_matrix,
        lookback_days=lookback_days,
        horizon_days=horizon_days,
        holdout_days=holdout_days,
        max_decisions=max_decisions,
    )
    if len(decisions) < 2:
        return _blocked_report(
            root=root,
            output_dir=output_dir,
            generated_at=generated_at,
            cfg=cfg,
            price_source=price_source,
            price_coverage=price_coverage,
            blocker="insufficient_decision_points",
        )

    model = adapter or _build_adapter(
        adapter_mode=adapter_mode,
        lookback_days=lookback_days,
        horizon_days=horizon_days,
        checkpoint_repo_id=checkpoint_repo_id,
    )
    forecast_rows, request_audit = _build_forecast_score_rows(
        prices=price_matrix,
        decisions=decisions,
        symbols=symbols,
        adapter=model,
        lookback_days=lookback_days,
        horizon_days=horizon_days,
    )
    existing = run_us_etf_macro_momentum_rotation(price_matrix, macro_df, cfg)
    weights_by_strategy = _build_strategy_weights(
        prices=price_matrix,
        forecast_rows=forecast_rows,
        decisions=decisions,
        cfg=cfg,
        existing_daily_weights=existing.daily_weights,
        top_n=top_n or cfg.top_n,
    )
    metrics = [
        _evaluate_weight_path(
            strategy_id=strategy_id,
            weights_by_decision=weights,
            prices=price_matrix,
            decisions=decisions,
            cost_bps=cost_bps,
        )
        for strategy_id, weights in weights_by_strategy.items()
    ]
    ranking = sorted(
        metrics,
        key=lambda item: (
            float(item.get("total_return", -999.0)),
            float(item.get("sharpe_like", -999.0)),
            -float(item.get("max_drawdown_abs", 999.0)),
        ),
        reverse=True,
    )

    output_root = root / output_dir
    output_root.mkdir(parents=True, exist_ok=True)
    report_path = output_root / "us_equity_shared_forecast_vs_baseline_smoke_report.json"
    rows_path = output_root / "us_equity_shared_forecast_vs_baseline_smoke_rows.csv"
    markdown_path = output_root / "us_equity_shared_forecast_vs_baseline_smoke_summary.md"
    _write_forecast_rows(rows_path, forecast_rows)
    report = {
        "schema_version": SCHEMA_VERSION,
        "status": "COMPLETE_RESEARCH_ONLY_SMOKE",
        "generated_at_utc": generated_at.isoformat(),
        "asset": "us_equity",
        "scope": "us_equity_shared_forecasting_interface_smoke_vs_existing_baselines",
        "commit": _git(["rev-parse", "--short", "HEAD"], cwd=root),
        "contract": {
            "shared_package": "quant_shared.forecasting",
            "contract_version": FORECASTING_CONTRACT_VERSION,
            "request_type": "TimeSeriesForecastRequest",
            "result_type": "TimeSeriesForecastResult",
            "allowed_usage": "research_only",
        },
        "model": {
            "model_id": model.model_id,
            "model_version": model.model_version,
            "adapter_mode": adapter_mode,
            "timesfm_available": is_timesfm_available(),
            "timesfm_environment": inspect_timesfm_environment(),
        },
        "input": {
            "price_source": price_source,
            "macro_status": macro_status,
            "macro_path": str(macro_path) if macro_path else None,
            "symbols": symbols,
            "price_rows": int(len(price_matrix)),
            "price_start": _date_str(price_matrix.index[0]),
            "price_end": _date_str(price_matrix.index[-1]),
            "lookback_days": int(lookback_days),
            "horizon_days": int(horizon_days),
            "holdout_days": int(holdout_days),
            "decision_count": int(len(decisions)),
            "first_decision_time_utc": decisions[0].decision_time_utc.isoformat(),
            "last_decision_time_utc": decisions[-1].decision_time_utc.isoformat(),
            "forecast_row_count": int(len(forecast_rows)),
            "forecast_rows_sha256": _rows_digest(forecast_rows),
            "price_coverage": price_coverage,
        },
        "validation_design": {
            "decision_time_rule": "month-end completed daily close is the decision timestamp",
            "visible_history_rule": "each forecast request uses price history ending at or before decision_time_utc",
            "execution_time_rule": "diagnostic forward return uses next horizon close; no order or paper ledger is written",
            "baseline_comparison": [
                "shared_forecast_topn",
                "existing_us_etf_rotation",
                "spy_buy_hold",
                "qqq_buy_hold",
                "equal_weight_required_universe",
            ],
            "cost_model": {
                "turnover_cost_bps": float(cost_bps),
                "applied_to_weight_turnover": True,
            },
        },
        "forecast_request_audit": request_audit,
        "comparison": {
            "metrics": metrics,
            "ranking_by_return_then_sharpe": ranking,
        },
        "research_decision": {
            "status": "SMOKE_COMPLETE_NOT_A_STRATEGY_VALIDATION",
            "paper_candidate_allowed": False,
            "live_allowed": False,
            "summary_cn": "美股已接入 quant_shared.forecasting 统一接口并完成 smoke 对比；这只证明接口和诊断链路可跑，不证明 alpha 有效。",
        },
        "safety_flags": {
            "paper_queue_write_allowed": False,
            "paper_or_live_unlock_allowed": False,
            "live_unlock_allowed": False,
            "live_order_allowed": False,
            "oms_access_allowed": False,
            "broker_access_allowed": False,
            "order_intent_allowed": False,
            "private_endpoint_used": False,
            "order_endpoint_used": False,
        },
        "limitations": [
            "smoke comparison only; no full walk-forward, regime attribution, or parameter stability gate",
            "forecast strategy is a diagnostic top-n portfolio, not a promoted production strategy",
            "input data may still be non-PIT-clean until the US equity data lineage gate is resolved",
        ],
        "report_paths": {
            "json": str(report_path),
            "rows_csv": str(rows_path),
            "summary_md": str(markdown_path),
        },
    }
    markdown_path.write_text(_render_markdown(report), encoding="utf-8")
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def _resolve_price_matrix(
    *,
    root: Path,
    prices: pd.DataFrame | None,
    cfg: UsEtfMacroMomentumRotationConfig,
    tiingo_data_lake: Path | None,
    external_data_lake: Path | None,
) -> tuple[pd.DataFrame, str, dict[str, Any]]:
    if prices is not None:
        matrix = prices.copy()
        matrix.index = pd.to_datetime(matrix.index, utc=True)
        _validate_price_matrix(matrix, cfg.required_symbols())
        return matrix.sort_index(), "provided_price_matrix", _coverage_from_matrix(matrix, cfg.required_symbols())

    candidates: list[tuple[str, Path | None]] = [
        ("tiingo_eod", tiingo_data_lake),
        ("external_data_lake", external_data_lake),
    ]
    coverage_by_source: dict[str, Any] = {}
    for source_name, source_root in candidates:
        if source_root is None:
            continue
        resolved = source_root if source_root.is_absolute() else root / source_root
        bars, available, coverage = _load_eod_kline_lake_bars(resolved, cfg.required_symbols())
        coverage_by_source[source_name] = coverage
        if set(available) >= set(cfg.required_symbols()) and not bars.empty:
            matrix = build_price_matrix_from_bars(bars, cfg.required_symbols())
            _validate_price_matrix(matrix, cfg.required_symbols())
            return matrix, source_name, coverage
    raise ValueError(f"no complete US ETF price matrix found; coverage={coverage_by_source}")


def _build_adapter(
    *,
    adapter_mode: str,
    lookback_days: int,
    horizon_days: int,
    checkpoint_repo_id: str,
) -> ForecastModelAdapter:
    mode = adapter_mode.lower()
    if mode == "drift":
        return DriftForecastAdapter(lookback_steps=min(63, max(5, lookback_days // 4)))
    if mode == "timesfm":
        return TimesFMForecastAdapter(
            checkpoint_repo_id=checkpoint_repo_id,
            max_context=_ceil_to_multiple(max(32, lookback_days)),
            max_horizon=_ceil_to_multiple(max(1, horizon_days)),
            torch_compile=False,
        )
    raise ValueError("adapter_mode must be drift or timesfm.")


def _select_month_end_decisions(
    prices: pd.DataFrame,
    *,
    lookback_days: int,
    horizon_days: int,
    holdout_days: int,
    max_decisions: int,
) -> list[DecisionPoint]:
    if lookback_days < 2 or horizon_days < 1:
        raise ValueError("lookback_days and horizon_days must be positive.")
    index = pd.DatetimeIndex(prices.index).sort_values()
    latest_decision = index[-1] - pd.Timedelta(days=int(horizon_days * 2))
    holdout_start = latest_decision - pd.Timedelta(days=int(holdout_days))
    month_groups = pd.Series(index, index=index).groupby(index.tz_convert(None).to_period("M"))
    month_ends = [pd.Timestamp(group.iloc[-1]) for _, group in month_groups]
    decisions: list[DecisionPoint] = []
    for decision_time in month_ends:
        if decision_time < holdout_start or decision_time > latest_decision:
            continue
        decision_index = int(index.searchsorted(decision_time, side="right") - 1)
        future_index = decision_index + int(horizon_days)
        if decision_index < lookback_days - 1 or future_index >= len(index):
            continue
        decisions.append(
            DecisionPoint(
                decision_index=decision_index,
                future_index=future_index,
                decision_time_utc=pd.Timestamp(index[decision_index]),
                future_time_utc=pd.Timestamp(index[future_index]),
            )
        )
    if len(decisions) > max_decisions:
        positions = sorted({round(item) for item in _linspace(0, len(decisions) - 1, max_decisions)})
        decisions = [decisions[position] for position in positions]
    return decisions


def _build_forecast_score_rows(
    *,
    prices: pd.DataFrame,
    decisions: Sequence[DecisionPoint],
    symbols: Sequence[str],
    adapter: ForecastModelAdapter,
    lookback_days: int,
    horizon_days: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    violations: list[str] = []
    request_count = 0
    for decision in decisions:
        history_start = decision.decision_index - lookback_days + 1
        history = prices.iloc[history_start : decision.decision_index + 1]
        for symbol in symbols:
            series = history[symbol].dropna()
            if len(series) < 2:
                continue
            request = TimeSeriesForecastRequest(
                asset_namespace="us_equity",
                instrument_id=symbol,
                series_name="close",
                frequency="1d",
                decision_time_utc=decision.decision_time_utc.to_pydatetime(),
                history_timestamps_utc=[pd.Timestamp(item).to_pydatetime() for item in series.index],
                history_values=[float(item) for item in series.values],
                horizon_steps=int(horizon_days),
                allowed_usage=ForecastUsage.RESEARCH_ONLY,
                metadata={
                    "source": "us_equity_shared_forecasting_smoke",
                    "completed_bar_policy": "history timestamp <= decision_time_utc",
                },
            )
            if request.visible_history_end_time_utc > request.decision_time_utc:
                violations.append(f"{symbol}:{request.visible_history_end_time_utc.isoformat()}")
            result = adapter.forecast(request)
            current_close = float(series.iloc[-1])
            future_close = float(prices.iloc[decision.future_index][symbol])
            forecast_close = float(result.point_forecast[-1])
            rows.append(
                {
                    "decision_time_utc": decision.decision_time_utc.isoformat(),
                    "future_time_utc": decision.future_time_utc.isoformat(),
                    "symbol": symbol,
                    "current_close": current_close,
                    "future_close": future_close,
                    "future_return": future_close / current_close - 1.0 if current_close > 0.0 else 0.0,
                    "forecast_close": forecast_close,
                    "forecast_score_return": forecast_close / current_close - 1.0 if current_close > 0.0 else 0.0,
                    "model_id": result.model_id,
                    "model_version": result.model_version,
                    "visible_history_end_time_utc": result.request.visible_history_end_time_utc.isoformat(),
                    "allowed_usage": result.request.allowed_usage.value,
                }
            )
            request_count += 1
    return rows, {
        "request_count": int(request_count),
        "lookahead_violation_count": int(len(violations)),
        "lookahead_violation_sample": violations[:5],
        "all_requests_research_only": all(row["allowed_usage"] == "research_only" for row in rows),
        "asset_namespace": "us_equity",
    }


def _build_strategy_weights(
    *,
    prices: pd.DataFrame,
    forecast_rows: Sequence[dict[str, Any]],
    decisions: Sequence[DecisionPoint],
    cfg: UsEtfMacroMomentumRotationConfig,
    existing_daily_weights: pd.DataFrame,
    top_n: int,
) -> dict[str, list[dict[str, float]]]:
    rows_by_decision: dict[str, list[dict[str, Any]]] = {}
    for row in forecast_rows:
        rows_by_decision.setdefault(str(row["decision_time_utc"]), []).append(row)

    strategies: dict[str, list[dict[str, float]]] = {
        "shared_forecast_topn": [],
        "existing_us_etf_rotation": [],
        "spy_buy_hold": [],
        "qqq_buy_hold": [],
        "equal_weight_required_universe": [],
    }
    offensive = set(cfg.offensive_assets)
    required = list(cfg.required_symbols())
    for decision in decisions:
        key = decision.decision_time_utc.isoformat()
        decision_rows = rows_by_decision.get(key, [])
        eligible = [
            row
            for row in decision_rows
            if str(row["symbol"]) in offensive and _finite(row.get("forecast_score_return"))
        ]
        selected = sorted(eligible, key=lambda item: float(item["forecast_score_return"]), reverse=True)[:top_n]
        positive = [row for row in selected if float(row["forecast_score_return"]) > 0.0]
        if positive:
            weight = 1.0 / len(positive)
            strategies["shared_forecast_topn"].append({str(row["symbol"]): weight for row in positive})
        else:
            strategies["shared_forecast_topn"].append({"SHV": 1.0})

        if decision.decision_time_utc in existing_daily_weights.index:
            existing_row = existing_daily_weights.loc[decision.decision_time_utc].fillna(0.0)
        else:
            prior = existing_daily_weights.index[existing_daily_weights.index <= decision.decision_time_utc]
            existing_row = existing_daily_weights.loc[prior[-1]].fillna(0.0) if len(prior) else pd.Series(dtype=float)
        strategies["existing_us_etf_rotation"].append(
            {str(symbol): float(weight) for symbol, weight in existing_row.items() if abs(float(weight)) > 1e-12}
        )
        strategies["spy_buy_hold"].append({"SPY": 1.0})
        strategies["qqq_buy_hold"].append({"QQQ": 1.0})
        equal_weight = 1.0 / len(required)
        strategies["equal_weight_required_universe"].append({symbol: equal_weight for symbol in required})
    return strategies


def _evaluate_weight_path(
    *,
    strategy_id: str,
    weights_by_decision: Sequence[Mapping[str, float]],
    prices: pd.DataFrame,
    decisions: Sequence[DecisionPoint],
    cost_bps: float,
) -> dict[str, Any]:
    returns: list[float] = []
    turnover_values: list[float] = []
    prior: dict[str, float] = {}
    for weights, decision in zip(weights_by_decision, decisions):
        current = {symbol: float(weight) for symbol, weight in weights.items() if abs(float(weight)) > 1e-12}
        turnover = sum(abs(current.get(symbol, 0.0) - prior.get(symbol, 0.0)) for symbol in set(current) | set(prior))
        gross_return = 0.0
        for symbol, weight in current.items():
            start = float(prices.iloc[decision.decision_index][symbol])
            end = float(prices.iloc[decision.future_index][symbol])
            if start > 0.0:
                gross_return += weight * (end / start - 1.0)
        net_return = gross_return - turnover * float(cost_bps) / 10_000.0
        returns.append(net_return)
        turnover_values.append(turnover)
        prior = current
    total_return = _compound_return(returns)
    volatility = _std(returns)
    mean_return = sum(returns) / len(returns) if returns else 0.0
    return {
        "strategy_id": strategy_id,
        "decision_count": int(len(returns)),
        "total_return": round(total_return, 6),
        "mean_forward_return": round(mean_return, 6),
        "volatility_per_decision": round(volatility, 6),
        "sharpe_like": round(mean_return / volatility, 6) if volatility > 0.0 else 0.0,
        "max_drawdown": round(_max_drawdown(returns), 6),
        "max_drawdown_abs": round(abs(_max_drawdown(returns)), 6),
        "hit_rate": round(sum(1 for item in returns if item > 0.0) / len(returns), 6) if returns else 0.0,
        "average_turnover": round(sum(turnover_values) / len(turnover_values), 6) if turnover_values else 0.0,
        "cost_bps": float(cost_bps),
    }


def _blocked_report(
    *,
    root: Path,
    output_dir: Path,
    generated_at: datetime,
    cfg: UsEtfMacroMomentumRotationConfig,
    price_source: str,
    price_coverage: dict[str, Any],
    blocker: str,
) -> dict[str, Any]:
    output_root = root / output_dir
    output_root.mkdir(parents=True, exist_ok=True)
    report_path = output_root / "us_equity_shared_forecast_vs_baseline_smoke_report.json"
    report = {
        "schema_version": SCHEMA_VERSION,
        "status": "BLOCKED",
        "generated_at_utc": generated_at.isoformat(),
        "asset": "us_equity",
        "scope": "us_equity_shared_forecasting_interface_smoke_vs_existing_baselines",
        "contract": {
            "shared_package": "quant_shared.forecasting",
            "contract_version": FORECASTING_CONTRACT_VERSION,
            "allowed_usage": "research_only",
        },
        "input": {
            "price_source": price_source,
            "symbols": list(cfg.required_symbols()),
            "price_coverage": price_coverage,
        },
        "safety_flags": {
            "paper_queue_write_allowed": False,
            "paper_or_live_unlock_allowed": False,
            "live_unlock_allowed": False,
            "live_order_allowed": False,
            "oms_access_allowed": False,
            "broker_access_allowed": False,
            "order_intent_allowed": False,
            "private_endpoint_used": False,
            "order_endpoint_used": False,
        },
        "blockers": [blocker],
        "report_paths": {"json": str(report_path)},
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def _write_forecast_rows(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    fieldnames = [
        "decision_time_utc",
        "future_time_utc",
        "symbol",
        "current_close",
        "future_close",
        "future_return",
        "forecast_close",
        "forecast_score_return",
        "model_id",
        "model_version",
        "visible_history_end_time_utc",
        "allowed_usage",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key) for key in fieldnames})


def _render_markdown(report: Mapping[str, Any]) -> str:
    ranking = list(report.get("comparison", {}).get("ranking_by_return_then_sharpe", []))
    lines = [
        "# US Equity shared forecasting smoke",
        "",
        f"- status: `{report.get('status')}`",
        f"- model: `{report.get('model', {}).get('model_id')}`",
        f"- decision_count: `{report.get('input', {}).get('decision_count')}`",
        f"- forecast_row_count: `{report.get('input', {}).get('forecast_row_count')}`",
        f"- paper/live unlocked: `false`",
        "",
        "| rank | strategy | total_return | sharpe_like | max_drawdown | avg_turnover |",
        "|---:|---|---:|---:|---:|---:|",
    ]
    for idx, row in enumerate(ranking, start=1):
        lines.append(
            f"| {idx} | `{row['strategy_id']}` | {row['total_return']} | {row['sharpe_like']} | "
            f"{row['max_drawdown']} | {row['average_turnover']} |"
        )
    lines.extend(
        [
            "",
            "This is a research-only smoke artifact. It does not validate alpha and cannot unlock paper or live trading.",
            "",
        ]
    )
    return "\n".join(lines)


def _validate_price_matrix(matrix: pd.DataFrame, symbols: Sequence[str]) -> None:
    missing = [symbol for symbol in symbols if symbol not in matrix.columns]
    if missing:
        raise ValueError(f"price matrix missing symbols: {missing}")
    if matrix[list(symbols)].dropna(how="any").empty:
        raise ValueError("price matrix has no complete rows.")


def _coverage_from_matrix(matrix: pd.DataFrame, symbols: Sequence[str]) -> dict[str, Any]:
    coverage: dict[str, Any] = {}
    for symbol in symbols:
        series = matrix[symbol].dropna()
        coverage[symbol] = {
            "status": "available" if not series.empty else "missing",
            "rows": int(len(series)),
            "start": _date_str(series.index[0]) if not series.empty else "",
            "end": _date_str(series.index[-1]) if not series.empty else "",
        }
    return coverage


def _date_str(value: Any) -> str:
    return str(pd.Timestamp(value).date())


def _rows_digest(rows: Sequence[Mapping[str, Any]]) -> str:
    payload = json.dumps(list(rows), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _compound_return(returns: Sequence[float]) -> float:
    equity = 1.0
    for value in returns:
        equity *= 1.0 + float(value)
    return equity - 1.0


def _max_drawdown(returns: Sequence[float]) -> float:
    equity = 1.0
    peak = 1.0
    worst = 0.0
    for value in returns:
        equity *= 1.0 + float(value)
        peak = max(peak, equity)
        worst = min(worst, equity / peak - 1.0 if peak > 0.0 else 0.0)
    return worst


def _std(values: Sequence[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    return math.sqrt(sum((item - mean) ** 2 for item in values) / len(values))


def _linspace(start: int, stop: int, count: int) -> list[float]:
    if count <= 1:
        return [float(start)]
    step = (stop - start) / float(count - 1)
    return [start + index * step for index in range(count)]


def _ceil_to_multiple(value: int, patch: int = 32) -> int:
    return ((int(value) + patch - 1) // patch) * patch


def _finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _git(args: list[str], *, cwd: Path) -> str:
    try:
        completed = subprocess.run(["git", *args], cwd=cwd, check=False, capture_output=True, text=True)
    except OSError:
        return ""
    return completed.stdout.strip() if completed.returncode == 0 else ""


def main() -> int:
    parser = argparse.ArgumentParser(description="Run US equity shared forecasting smoke vs existing baselines.")
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--adapter-mode", choices=["drift", "timesfm"], default="drift")
    parser.add_argument("--checkpoint-repo-id", default=TIMESFM_DEFAULT_CHECKPOINT)
    parser.add_argument("--lookback-days", type=int, default=252)
    parser.add_argument("--horizon-days", type=int, default=21)
    parser.add_argument("--holdout-days", type=int, default=365)
    parser.add_argument("--max-decisions", type=int, default=12)
    parser.add_argument("--cost-bps", type=float, default=10.0)
    args = parser.parse_args()
    report = run_us_equity_shared_forecast_smoke(
        repo_root=args.repo_root,
        output_dir=args.output_dir,
        adapter_mode=args.adapter_mode,
        checkpoint_repo_id=args.checkpoint_repo_id,
        lookback_days=args.lookback_days,
        horizon_days=args.horizon_days,
        holdout_days=args.holdout_days,
        max_decisions=args.max_decisions,
        cost_bps=args.cost_bps,
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "ranking": report.get("comparison", {}).get("ranking_by_return_then_sharpe", []),
                "report_paths": report.get("report_paths", {}),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
