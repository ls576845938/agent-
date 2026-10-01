#!/usr/bin/env python3
"""Build a BTC-only trend exposure-management v0 report.

This is not a CTA multi-asset model. It evaluates whether a single-asset BTC
trend exposure process is ready to study, and keeps short-history proxy results
separate from the intended 120/200 day and 12-month rules.
"""

from __future__ import annotations

import argparse
import json
import math
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


SCHEMA_VERSION = "btc_only_trend_v0_report_v1"
SYMBOL = "BTCUSDT"
DEFAULT_CONFIG = Path("configs/data/btc_perpetual_sources.yaml")
DEFAULT_OUTPUT = Path("artifacts/btc_trend_v0/latest/btc_only_trend_v0_report.json")
DEFAULT_MARKDOWN_OUTPUT = Path("../学习资料/量化交易业务闭环/系统评估/BTC-only 趋势暴露管理 v0.md")


def build_btc_only_trend_v0_report(
    *,
    repo_root: Path | None = None,
    config_path: Path = DEFAULT_CONFIG,
    bundle_dir: Path | None = None,
    output: Path = DEFAULT_OUTPUT,
    markdown_output: Path = DEFAULT_MARKDOWN_OUTPUT,
    initial_capital: float = 25_000.0,
    target_volatility: float = 0.25,
    max_exposure: float = 1.0,
    cost_bps_per_turnover: float = 5.0,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at or _utc_z_now()
    config_abs = _resolve(root, config_path)
    selected_bundle = _resolve(root, bundle_dir) if bundle_dir else _selected_bundle_dir(root, config_abs)
    output_path = _resolve(root, output)
    markdown_path = _resolve(root, markdown_output)
    daily = _load_daily_bars(selected_bundle)
    strategies = _strategy_rows(
        daily,
        target_volatility=float(target_volatility),
        max_exposure=float(max_exposure),
        cost_bps_per_turnover=float(cost_bps_per_turnover),
        initial_capital=float(initial_capital),
    )
    requirements = _data_requirements(daily)
    comparison = _benchmark_comparison(strategies)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated,
        "asset": "btc",
        "symbol": SYMBOL,
        "bundle_dir": _relpath(selected_bundle, root),
        "status": _status(requirements),
        "decision": (
            "use_current_90d_as_framework_smoke_only"
            if not requirements["full_trend_rules_ready"]
            else "full_trend_v0_ready_for_research_evaluation"
        ),
        "objective": "BTC-only trend exposure management; reduce drawdown versus passive BTC exposure.",
        "not_multi_asset_cta": True,
        "data": {
            "daily_rows": int(len(daily)),
            "start": _timestamp_text(daily.index.min()) if len(daily) else "",
            "end": _timestamp_text(daily.index.max()) if len(daily) else "",
            "source": "OKX public local bundle",
        },
        "parameters": {
            "initial_capital": float(initial_capital),
            "target_volatility": float(target_volatility),
            "max_exposure": float(max_exposure),
            "cost_bps_per_turnover": float(cost_bps_per_turnover),
            "volatility_window_days": 20,
            "proxy_trend_fast_window_days": 20,
            "proxy_trend_slow_window_days": 60,
            "intended_ma_windows_days": [120, 200],
            "intended_momentum_window_months": 12,
        },
        "data_requirements": requirements,
        "strategies": strategies,
        "benchmark_comparison": comparison,
        "guardrails": {
            "research_only": True,
            "spot_or_low_leverage_first": True,
            "high_leverage_perpetual_not_allowed_for_v0": True,
            "broker_calls_allowed": False,
            "private_endpoint_used": False,
            "order_endpoint_used": False,
            "do_not_treat_multiple_btc_timeframes_as_diversification": True,
        },
        "interpretation": _interpretation(requirements=requirements, strategies=strategies, comparison=comparison),
    }
    _write_json(output_path, payload)
    _write_text(markdown_path, _markdown(payload))
    return payload


def _load_daily_bars(bundle_dir: Path) -> pd.DataFrame:
    daily_path = bundle_dir / "klines_1d.csv"
    if daily_path.exists():
        frame = pd.read_csv(daily_path)
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
        frame = frame.set_index("timestamp").sort_index()
    else:
        intraday_path = bundle_dir / "klines_5m.csv"
        frame = pd.read_csv(intraday_path)
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
        frame = frame.set_index("timestamp").sort_index()
        frame = frame.resample("1D").agg(
            {
                "open": "first",
                "high": "max",
                "low": "min",
                "close": "last",
                "volume_base": "sum" if "volume_base" in frame.columns else "count",
            }
        )
    for column in ("open", "high", "low", "close"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.dropna(subset=["close"])
    return frame


def _strategy_rows(
    daily: pd.DataFrame,
    *,
    target_volatility: float,
    max_exposure: float,
    cost_bps_per_turnover: float,
    initial_capital: float,
) -> list[dict[str, Any]]:
    close = daily["close"].astype(float)
    returns = close.pct_change().fillna(0.0)
    rows = [
        _evaluate_strategy(
            "buy_hold_btc",
            "Buy and hold BTC",
            returns=returns,
            exposure=pd.Series(1.0, index=returns.index),
            cost_bps_per_turnover=0.0,
            initial_capital=initial_capital,
        ),
        _evaluate_strategy(
            "fixed_50pct_btc",
            "Fixed 50% BTC exposure",
            returns=returns,
            exposure=pd.Series(0.5, index=returns.index),
            cost_bps_per_turnover=0.0,
            initial_capital=initial_capital,
        ),
    ]
    proxy_trend = ((close.rolling(20).mean() > close.rolling(60).mean()) & (close > close.rolling(60).mean())).astype(float)
    proxy_exposure = proxy_trend.shift(1).fillna(0.0).clip(0.0, max_exposure)
    rows.append(
        _evaluate_strategy(
            "ma20_60_timing_proxy",
            "Short-history proxy: MA20/60 timing",
            returns=returns,
            exposure=proxy_exposure,
            cost_bps_per_turnover=cost_bps_per_turnover,
            initial_capital=initial_capital,
        )
    )
    realized_vol = returns.rolling(20).std(ddof=0) * math.sqrt(365.0)
    vol_scalar = (target_volatility / realized_vol).replace([math.inf, -math.inf], 0.0).fillna(0.0)
    vol_target_exposure = (proxy_trend.shift(1).fillna(0.0) * vol_scalar).clip(0.0, max_exposure)
    rows.append(
        _evaluate_strategy(
            "btc_trend_v0_proxy_vol_target",
            "Short-history proxy: MA20/60 trend with volatility-targeted exposure",
            returns=returns,
            exposure=vol_target_exposure,
            cost_bps_per_turnover=cost_bps_per_turnover,
            initial_capital=initial_capital,
        )
    )
    ma120_200_ready = len(daily) >= 220
    ma120_200_trend = (
        (close.rolling(120).mean() > close.rolling(200).mean()) & (close > close.rolling(200).mean())
    ).astype(float)
    full_exposure = ma120_200_trend.shift(1).fillna(0.0)
    full_row = _evaluate_strategy(
        "ma120_200_trend_intended",
        "Intended v0: MA120/200 daily trend timing",
        returns=returns,
        exposure=full_exposure,
        cost_bps_per_turnover=cost_bps_per_turnover,
        initial_capital=initial_capital,
    )
    full_row["status"] = "ready" if ma120_200_ready else "insufficient_history"
    rows.append(full_row)
    ma120_200_vol_target_exposure = (ma120_200_trend.shift(1).fillna(0.0) * vol_scalar).clip(0.0, max_exposure)
    full_vol_row = _evaluate_strategy(
        "ma120_200_trend_vol_target_intended",
        "Intended v0: MA120/200 trend + volatility-targeted exposure",
        returns=returns,
        exposure=ma120_200_vol_target_exposure,
        cost_bps_per_turnover=cost_bps_per_turnover,
        initial_capital=initial_capital,
    )
    full_vol_row["status"] = "ready" if ma120_200_ready else "insufficient_history"
    rows.append(full_vol_row)
    momentum_ready = len(daily) >= 365
    momentum_exposure = (close.pct_change(365) > 0.0).astype(float).shift(1).fillna(0.0)
    momentum_row = _evaluate_strategy(
        "twelve_month_momentum_intended",
        "Intended v0: 12-month BTC momentum timing",
        returns=returns,
        exposure=momentum_exposure,
        cost_bps_per_turnover=cost_bps_per_turnover,
        initial_capital=initial_capital,
    )
    momentum_row["status"] = "ready" if momentum_ready else "insufficient_history"
    rows.append(momentum_row)
    return rows


def _evaluate_strategy(
    strategy_id: str,
    label: str,
    *,
    returns: pd.Series,
    exposure: pd.Series,
    cost_bps_per_turnover: float,
    initial_capital: float,
) -> dict[str, Any]:
    exposure = exposure.reindex(returns.index).fillna(0.0).clip(0.0, 1.0)
    turnover = exposure.diff().abs().fillna(exposure.abs())
    cost = turnover * (float(cost_bps_per_turnover) / 10_000.0)
    strategy_returns = (exposure * returns - cost).fillna(0.0)
    equity = float(initial_capital) * (1.0 + strategy_returns).cumprod()
    metrics = _performance(strategy_returns, equity)
    return {
        "strategy_id": strategy_id,
        "label": label,
        "status": "ready",
        "metrics": metrics,
        "exposure": {
            "average_exposure": round(float(exposure.mean()), 6) if len(exposure) else 0.0,
            "max_exposure": round(float(exposure.max()), 6) if len(exposure) else 0.0,
            "days_with_exposure": int((exposure > 0.0).sum()),
            "turnover": round(float(turnover.sum()), 6),
        },
    }


def _performance(returns: pd.Series, equity: pd.Series) -> dict[str, Any]:
    if returns.empty or equity.empty:
        return {
            "total_return_pct": 0.0,
            "annual_return_pct": 0.0,
            "annual_volatility_pct": 0.0,
            "sharpe_ratio": 0.0,
            "max_drawdown_pct": 0.0,
            "max_drawdown_abs_pct": 0.0,
            "final_equity": 0.0,
        }
    total_return = float(equity.iloc[-1] / equity.iloc[0] - 1.0) if float(equity.iloc[0]) else 0.0
    days = max(1, int((equity.index.max() - equity.index.min()).days))
    annual_return = (1.0 + total_return) ** (365.0 / days) - 1.0 if total_return > -1.0 else -1.0
    std = float(returns.std(ddof=0))
    annual_vol = std * math.sqrt(365.0)
    sharpe = float(returns.mean() / std * math.sqrt(365.0)) if std > 0 else 0.0
    drawdown = equity / equity.cummax() - 1.0
    max_drawdown = float(drawdown.min()) if len(drawdown) else 0.0
    return {
        "total_return_pct": round(total_return * 100.0, 6),
        "annual_return_pct": round(annual_return * 100.0, 6),
        "annual_volatility_pct": round(annual_vol * 100.0, 6),
        "sharpe_ratio": round(sharpe, 6),
        "max_drawdown_pct": round(max_drawdown * 100.0, 6),
        "max_drawdown_abs_pct": round(abs(max_drawdown) * 100.0, 6),
        "final_equity": round(float(equity.iloc[-1]), 6),
    }


def _data_requirements(daily: pd.DataFrame) -> dict[str, Any]:
    rows = int(len(daily))
    return {
        "available_daily_rows": rows,
        "ma120_200_required_rows": 220,
        "twelve_month_momentum_required_rows": 365,
        "ma120_200_ready": rows >= 220,
        "twelve_month_momentum_ready": rows >= 365,
        "full_trend_rules_ready": rows >= 365,
        "blocking_reason": "" if rows >= 365 else "btc_only_trend_full_rules_need_longer_daily_history",
    }


def _benchmark_comparison(strategies: list[Mapping[str, Any]]) -> dict[str, Any]:
    by_id = {str(row.get("strategy_id", "")): _mapping(row) for row in strategies}
    buy_hold = _mapping(_mapping(by_id.get("buy_hold_btc")).get("metrics"))
    comparisons: dict[str, Any] = {}
    for strategy_id, row in by_id.items():
        metrics = _mapping(row.get("metrics"))
        if str(row.get("status", "")) != "ready":
            comparisons[strategy_id] = {
                "valid": False,
                "reason": "insufficient_history",
                "return_diff_vs_buy_hold_pct": None,
                "drawdown_reduction_vs_buy_hold_pct": None,
                "volatility_reduction_vs_buy_hold_pct": None,
            }
            continue
        comparisons[strategy_id] = {
            "valid": True,
            "reason": "",
            "return_diff_vs_buy_hold_pct": round(
                float(metrics.get("total_return_pct", 0.0) or 0.0)
                - float(buy_hold.get("total_return_pct", 0.0) or 0.0),
                6,
            ),
            "drawdown_reduction_vs_buy_hold_pct": round(
                float(buy_hold.get("max_drawdown_abs_pct", 0.0) or 0.0)
                - float(metrics.get("max_drawdown_abs_pct", 0.0) or 0.0),
                6,
            ),
            "volatility_reduction_vs_buy_hold_pct": round(
                float(buy_hold.get("annual_volatility_pct", 0.0) or 0.0)
                - float(metrics.get("annual_volatility_pct", 0.0) or 0.0),
                6,
            ),
        }
    return comparisons


def _status(requirements: Mapping[str, Any]) -> str:
    return (
        "research_ready"
        if bool(requirements.get("full_trend_rules_ready", False))
        else "research_proxy_only_insufficient_history_for_full_trend_v0"
    )


def _interpretation(
    *,
    requirements: Mapping[str, Any],
    strategies: list[Mapping[str, Any]],
    comparison: Mapping[str, Any],
) -> list[str]:
    notes = [
        "BTC-only 趋势是单资产暴露管理问题，不是多品种 CTA 组合。",
        "目标是降低回撤、让 BTC 暴露更可承受，不是追求每天盈利。",
    ]
    if not bool(requirements.get("full_trend_rules_ready", False)):
        notes.append("当前本地日线历史不足以验证 MA120/200 和 12 个月动量；短窗结果只能作为框架 smoke test。")
    else:
        notes.append("当前日线历史已足够做正式 v0 对比：买入持有、固定 50%、MA120/200、12 个月动量、MA 趋势 + 波动率仓位。")
    proxy = _mapping(next((row for row in strategies if row.get("strategy_id") == "btc_trend_v0_proxy_vol_target"), {}))
    proxy_cmp = _mapping(comparison.get("btc_trend_v0_proxy_vol_target"))
    if proxy:
        notes.append(
            "波动率目标趋势 proxy 应先看相对买入持有是否降低回撤和波动，再看收益。"
        )
        if float(proxy_cmp.get("drawdown_reduction_vs_buy_hold_pct", 0.0) or 0.0) <= 0.0:
            notes.append("当前短样本内，趋势 proxy 没有证明能比买入持有降低回撤。")
    return notes


def _markdown(payload: Mapping[str, Any]) -> str:
    data = _mapping(payload.get("data"))
    requirements = _mapping(payload.get("data_requirements"))
    strategies = [_mapping(row) for row in payload.get("strategies", []) if isinstance(row, Mapping)]
    comparison = _mapping(payload.get("benchmark_comparison"))
    full_ready = bool(requirements.get("full_trend_rules_ready", False))
    lines = [
        "# BTC-only 趋势暴露管理 v0",
        "",
        f"生成时间：{payload.get('generated_at', '')}",
        "",
        "## 结论",
        "",
        f"状态：`{payload.get('status', '')}`",
        "",
        "这个方向不是多品种 CTA，而是单资产 BTC 暴露管理。目标不是每天赚钱，而是判断什么时候持有 BTC、什么时候空仓或低仓位，并且必须和买入持有比较。",
        "",
        (
            "当前日线历史已足够验证正式 v0：买入持有、固定 50%、MA120/200、12 个月动量、MA 趋势 + 波动率仓位。"
            if full_ready
            else "当前本地数据只有短样本，不能严肃验证 120/200 日均线或 12 个月动量；下面的 20/60 均线和波动率目标只是框架 smoke test。"
        ),
        "",
        "## 数据",
        "",
        "| 项目 | 数值 |",
        "| --- | ---: |",
        f"| 日线行数 | {data.get('daily_rows', 0)} |",
        f"| 开始 | {data.get('start', '')} |",
        f"| 结束 | {data.get('end', '')} |",
        f"| 120/200 日均线可验证 | {requirements.get('ma120_200_ready', False)} |",
        f"| 12 个月动量可验证 | {requirements.get('twelve_month_momentum_ready', False)} |",
        "",
        "## 策略与基准",
        "",
        "| 策略 | 状态 | 总收益 | 年化波动 | 最大回撤 | Sharpe | 平均仓位 | 相对买入持有回撤改善 |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in strategies:
        metrics = _mapping(row.get("metrics"))
        exposure = _mapping(row.get("exposure"))
        cmp_row = _mapping(comparison.get(str(row.get("strategy_id", ""))))
        dd_improvement = cmp_row.get("drawdown_reduction_vs_buy_hold_pct")
        lines.append(
            f"| {row.get('label', '')} | {row.get('status', '')} | "
            f"{metrics.get('total_return_pct', 0)}% | {metrics.get('annual_volatility_pct', 0)}% | "
            f"{metrics.get('max_drawdown_abs_pct', 0)}% | {metrics.get('sharpe_ratio', 0)} | "
            f"{exposure.get('average_exposure', 0)} | {_format_optional_pct(dd_improvement)} |"
        )
    lines += [
        "",
        "## 解释",
        "",
    ]
    for note in payload.get("interpretation", []):
        lines.append(f"- {note}")
    lines += [
        "",
        "## 下一步",
        "",
        (
            "1. 基于正式长样本结果决定是否保留 MA120/200 趋势 + 波动率仓位作为 v0 主线。"
            if full_ready
            else "1. 保留 BTC-only 方向，但先补足更长日线历史后再评估 120/200 日均线和 12 个月动量。"
        ),
        "2. v0 只允许现货或极低杠杆暴露管理，不进入高杠杆永续。",
        "3. 每个候选必须同时比较买入持有、固定比例持有、简单均线择时和波动率仓位版本。",
        "4. 多周期 BTC 信号只能平滑择时，不能当作跨资产分散。",
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


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _relpath(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _timestamp_text(value: object) -> str:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    else:
        timestamp = timestamp.tz_convert("UTC")
    return timestamp.isoformat().replace("+00:00", "Z")


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _format_optional_pct(value: object) -> str:
    return "n/a" if value is None else f"{value}%"


def _utc_z_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build BTC-only trend exposure-management v0 report.")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--config-path", default=str(DEFAULT_CONFIG))
    parser.add_argument("--bundle-dir", default="")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--markdown-output", default=str(DEFAULT_MARKDOWN_OUTPUT))
    parser.add_argument("--initial-capital", type=float, default=25_000.0)
    parser.add_argument("--target-volatility", type=float, default=0.25)
    parser.add_argument("--max-exposure", type=float, default=1.0)
    parser.add_argument("--cost-bps-per-turnover", type=float, default=5.0)
    parser.add_argument("--generated-at", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    payload = build_btc_only_trend_v0_report(
        repo_root=Path(args.repo_root),
        config_path=Path(args.config_path),
        bundle_dir=Path(args.bundle_dir) if args.bundle_dir else None,
        output=Path(args.output),
        markdown_output=Path(args.markdown_output),
        initial_capital=args.initial_capital,
        target_volatility=args.target_volatility,
        max_exposure=args.max_exposure,
        cost_bps_per_turnover=args.cost_bps_per_turnover,
        generated_at=args.generated_at or None,
    )
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    else:
        print(payload["status"])


if __name__ == "__main__":
    main()
