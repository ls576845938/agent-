from __future__ import annotations

import csv
import hashlib
import json
import math
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

import pandas as pd


SCHEMA_VERSION = "us_tqqq_multitimeframe_walk_forward_report_v1"
TIMEFRAME_MINUTES = {"5min": 5, "15min": 15, "30min": 30, "1H": 60, "4H": 240, "1D": 390}
DEFAULT_TIMEFRAMES = tuple(TIMEFRAME_MINUTES)
DEFAULT_COST_BPS = (5.0, 10.0, 25.0, 50.0)
BASE_COST_BPS = 10.0
INITIAL_CAPITAL = 25_000.0


def prepare_fixed_rule_market_from_pit(
    *,
    qqq_path: Path,
    tqqq_path: Path,
    timeframe: str,
) -> tuple[pd.DataFrame, dict[str, Any], dict[str, Any]]:
    if timeframe not in TIMEFRAME_MINUTES:
        raise ValueError(f"unsupported timeframe: {timeframe}")
    qqq_minute = _load_pit_frame(qqq_path, "QQQ")
    tqqq_minute = _load_pit_frame(tqqq_path, "TQQQ")
    complete_sessions = sorted(_complete_sessions(qqq_minute) & _complete_sessions(tqqq_minute))
    if not complete_sessions:
        raise ValueError("common_complete_rth_sessions_missing")
    qqq_minute = _filter_sessions(qqq_minute, complete_sessions)
    tqqq_minute = _filter_sessions(tqqq_minute, complete_sessions)
    minutes = TIMEFRAME_MINUTES[timeframe]
    qqq = _resample_rth(qqq_minute, minutes=minutes, symbol="QQQ")
    tqqq = _resample_rth(tqqq_minute, minutes=minutes, symbol="TQQQ")
    market = _prepare_market(tqqq, qqq)
    params = _fixed_params(minutes)
    market = market.join(_fixed_signal(market, params))
    return market, params, {
        "timeframe": timeframe,
        "complete_session_count": len(complete_sessions),
        "complete_session_start": complete_sessions[0],
        "complete_session_end": complete_sessions[-1],
    }


def build_tqqq_multitimeframe_walk_forward_report(
    *,
    repo_root: Path,
    qqq_path: Path,
    tqqq_path: Path,
    pit_report_path: Path,
    output_root: Path,
    timeframes: Iterable[str] = DEFAULT_TIMEFRAMES,
    cost_bps_levels: Iterable[float] = DEFAULT_COST_BPS,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = repo_root.resolve()
    generated = generated_at or datetime.now(timezone.utc).isoformat()
    qqq_abs = _resolve(root, qqq_path)
    tqqq_abs = _resolve(root, tqqq_path)
    pit_report_abs = _resolve(root, pit_report_path)
    output_abs = _resolve(root, output_root)
    output_abs.mkdir(parents=True, exist_ok=True)
    ledger_root = output_abs / "ledger"
    ledger_root.mkdir(parents=True, exist_ok=True)

    selected_timeframes = tuple(_unique_timeframes(timeframes))
    selected_costs = tuple(sorted({float(value) for value in cost_bps_levels}))
    blockers: list[str] = []
    pit_report = _read_json(pit_report_abs)
    if pit_report.get("status") != "pass":
        blockers.append("ibkr_minute_pit_replay_not_passed")
    for symbol in ("QQQ", "TQQQ"):
        symbol_report = pit_report.get("symbol_reports", {}).get(symbol, {})
        if int(symbol_report.get("no_lookahead_violations", 1) or 0) != 0:
            blockers.append(f"{symbol.lower()}_pit_no_lookahead_not_clean")
    if not qqq_abs.exists():
        blockers.append("qqq_pit_adjusted_minute_missing")
    if not tqqq_abs.exists():
        blockers.append("tqqq_pit_adjusted_minute_missing")

    matrix_rows: list[dict[str, Any]] = []
    cost_rows: list[dict[str, Any]] = []
    fold_rows: list[dict[str, Any]] = []
    timeframe_reports: dict[str, Any] = {}
    if not blockers:
        qqq_minute = _load_pit_frame(qqq_abs, "QQQ")
        tqqq_minute = _load_pit_frame(tqqq_abs, "TQQQ")
        complete_sessions = sorted(_complete_sessions(qqq_minute) & _complete_sessions(tqqq_minute))
        if not complete_sessions:
            blockers.append("common_complete_rth_sessions_missing")
        qqq_minute = _filter_sessions(qqq_minute, complete_sessions)
        tqqq_minute = _filter_sessions(tqqq_minute, complete_sessions)
        for timeframe in selected_timeframes:
            minutes = TIMEFRAME_MINUTES[timeframe]
            qqq = _resample_rth(qqq_minute, minutes=minutes, symbol="QQQ")
            tqqq = _resample_rth(tqqq_minute, minutes=minutes, symbol="TQQQ")
            market = _prepare_market(tqqq, qqq)
            params = _fixed_params(minutes)
            signal = _fixed_signal(market, params)
            joined = market.join(signal)
            report, ledger, timeframe_cost_rows, timeframe_fold_rows = _evaluate_timeframe(
                timeframe=timeframe,
                market=joined,
                params=params,
                cost_bps_levels=selected_costs,
            )
            timeframe_reports[timeframe] = report
            cost_rows.extend(timeframe_cost_rows)
            fold_rows.extend(timeframe_fold_rows)
            if report["status"] != "pass":
                blockers.extend(report["blockers"])
                continue
            matrix_rows.append({"timeframe": timeframe, **report["base_cost_metrics"]})
            ledger.to_parquet(ledger_root / f"{timeframe}.parquet", index=False)

    status = "complete_research_only" if not blockers and len(matrix_rows) == len(selected_timeframes) else "blocked"
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated,
        "status": status,
        "decision": "research_only_multitimeframe_comparison_no_paper_no_live" if status == "complete_research_only" else "blocked_before_multitimeframe_comparison",
        "strategy_id": "us_tqqq_btc_10x_rollover_migration_fixed_rule_multitimeframe",
        "research_question": "How does one frozen QQQ trend-breakout rule perform on TQQQ across bar periods after PIT replay and explicit costs?",
        "economic_hypothesis": "If the effect is robust, cost-adjusted walk-forward performance should persist across adjacent bar periods without timeframe-specific parameter selection.",
        "code_commit": _git(["rev-parse", "--short", "HEAD"], cwd=root),
        "branch": _git(["branch", "--show-current"], cwd=root),
        "data": {
            "provider": "ibkr",
            "pit_report": _relpath(pit_report_abs, root),
            "pit_report_status": pit_report.get("status"),
            "qqq_path": _relpath(qqq_abs, root),
            "tqqq_path": _relpath(tqqq_abs, root),
            "qqq_sha256": _sha256(qqq_abs) if qqq_abs.exists() else None,
            "tqqq_sha256": _sha256(tqqq_abs) if tqqq_abs.exists() else None,
            "common_complete_session_count": len(complete_sessions) if not blockers else 0,
            "common_complete_session_start": complete_sessions[0] if not blockers and complete_sessions else None,
            "common_complete_session_end": complete_sessions[-1] if not blockers and complete_sessions else None,
            "raw_minute_overwritten": False,
            "future_factor_backfill_allowed": False,
        },
        "fixed_rule": {
            "selection_per_timeframe_allowed": False,
            "selection_per_fold_allowed": False,
            "reference_timeframe": "4H",
            "reference_params": {"entry_window": 240, "exit_window": 120, "atr_window": 20, "cooldown_bars": 12, "failure_exit_window": 6, "ema_fast_days": 50, "ema_slow_days": 200, "atr_mult": 3.0},
            "scaling_rule": "bar windows scale by bars_per_session / 2 so every timeframe preserves the 4H economic horizon",
            "decision_time_rule": "signals use only completed QQQ bars and prior-session daily EMA values",
            "execution_time_rule": "TQQQ exposure changes at the next bar open; no same-bar execution",
        },
        "cost_model": {"base_cost_bps": BASE_COST_BPS, "stress_levels_bps": list(selected_costs), "components": ["commission", "spread", "slippage", "market_impact_proxy"]},
        "walk_forward_contract": {"first_test_year": 2020, "test_window": "calendar_year", "training_selection": "none_fixed_parameters", "warmup_history_allowed": True, "fold_failure_hidden_by_average_allowed": False},
        "timeframes": list(selected_timeframes),
        "timeframe_reports": timeframe_reports,
        "matrix_rows": matrix_rows,
        "cost_stress_rows": cost_rows,
        "walk_forward_rows": fold_rows,
        "summary": _summary(matrix_rows, fold_rows),
        "outputs": {
            "json": _relpath(output_abs / "us_tqqq_multitimeframe_walk_forward_report.json", root),
            "matrix_csv": _relpath(output_abs / "us_tqqq_multitimeframe_matrix.csv", root),
            "cost_stress_csv": _relpath(output_abs / "us_tqqq_multitimeframe_cost_stress.csv", root),
            "walk_forward_csv": _relpath(output_abs / "us_tqqq_multitimeframe_walk_forward_folds.csv", root),
            "ledger_root": _relpath(ledger_root, root),
        },
        "guardrails": {
            "research_only": True,
            "private_endpoint_used": False,
            "order_endpoint_used": False,
            "broker_order_endpoint_used": False,
            "real_order_submitted": False,
            "paper_or_live_unlock_allowed": False,
            "live_order_allowed": False,
        },
        "blockers": _dedupe(blockers),
    }
    _write_json(output_abs / "us_tqqq_multitimeframe_walk_forward_report.json", report)
    _write_csv(output_abs / "us_tqqq_multitimeframe_matrix.csv", matrix_rows)
    _write_csv(output_abs / "us_tqqq_multitimeframe_cost_stress.csv", cost_rows)
    _write_csv(output_abs / "us_tqqq_multitimeframe_walk_forward_folds.csv", fold_rows)
    (output_abs / "us_tqqq_multitimeframe_walk_forward_report.md").write_text(_markdown(report), encoding="utf-8")
    return report


def _load_pit_frame(path: Path, symbol: str) -> pd.DataFrame:
    frame = pd.read_parquet(path, columns=["datetime", "PitOpen", "PitHigh", "PitLow", "PitClose", "Volume"])
    frame = frame.rename(columns={"PitOpen": "Open", "PitHigh": "High", "PitLow": "Low", "PitClose": "Close"})
    frame["datetime"] = pd.to_datetime(frame["datetime"], utc=True)
    frame["symbol"] = symbol
    return frame.dropna(subset=["datetime", "Open", "High", "Low", "Close"]).sort_values("datetime").drop_duplicates("datetime", keep="last")


def _resample_rth(frame: pd.DataFrame, *, minutes: int, symbol: str) -> pd.DataFrame:
    working = frame.copy()
    local = working["datetime"].dt.tz_convert("America/New_York")
    minute_of_day = local.dt.hour * 60 + local.dt.minute
    mask = (minute_of_day >= 570) & (minute_of_day < 960) & (local.dt.dayofweek < 5)
    working = working.loc[mask].copy()
    local = local.loc[mask]
    minute_of_day = minute_of_day.loc[mask]
    working["session"] = local.dt.strftime("%Y-%m-%d")
    working["bucket"] = ((minute_of_day - 570) // int(minutes)).astype(int)
    grouped = working.groupby(["session", "bucket"], sort=True, observed=True)
    result = grouped.agg(Open=("Open", "first"), High=("High", "max"), Low=("Low", "min"), Close=("Close", "last"), Volume=("Volume", "sum")).reset_index()
    session_open = pd.to_datetime(result["session"] + " 09:30:00").dt.tz_localize("America/New_York")
    result["datetime"] = (session_open + pd.to_timedelta(result["bucket"] * int(minutes), unit="m")).dt.tz_convert("UTC")
    result["symbol"] = symbol
    return result[["datetime", "symbol", "Open", "High", "Low", "Close", "Volume"]]


def _complete_sessions(frame: pd.DataFrame) -> set[str]:
    local = frame["datetime"].dt.tz_convert("America/New_York")
    minute_of_day = local.dt.hour * 60 + local.dt.minute
    mask = (minute_of_day >= 570) & (minute_of_day < 960) & (local.dt.dayofweek < 5)
    sessions = local.loc[mask].dt.strftime("%Y-%m-%d")
    counts = sessions.value_counts()
    if counts.empty:
        return set()
    threshold = max(1, int(math.floor(float(counts.median()) * 0.5)))
    return {str(session) for session, count in counts.items() if int(count) >= threshold}


def _filter_sessions(frame: pd.DataFrame, sessions: Iterable[str]) -> pd.DataFrame:
    allowed = set(sessions)
    local_sessions = frame["datetime"].dt.tz_convert("America/New_York").dt.strftime("%Y-%m-%d")
    return frame.loc[local_sessions.isin(allowed)].copy()


def _prepare_market(tqqq: pd.DataFrame, qqq: pd.DataFrame) -> pd.DataFrame:
    left = tqqq.set_index("datetime")[["Open", "High", "Low", "Close", "Volume"]].rename(columns=lambda value: f"tqqq_{value.lower()}")
    right = qqq.set_index("datetime")[["Open", "High", "Low", "Close", "Volume"]].rename(columns=lambda value: f"qqq_{value.lower()}")
    market = left.join(right, how="inner").sort_index()
    market["tqqq_next_open"] = market["tqqq_open"].shift(-1)
    market["tqqq_open_to_next_open_return"] = market["tqqq_next_open"] / market["tqqq_open"] - 1.0
    market["tqqq_adverse_open_low_or_gap_return"] = pd.concat(
        [market["tqqq_low"] / market["tqqq_open"] - 1.0, market["tqqq_next_open"] / market["tqqq_open"] - 1.0],
        axis=1,
    ).min(axis=1)
    return market.dropna(subset=["tqqq_next_open"])


def _fixed_params(minutes: int) -> dict[str, Any]:
    bars_per_session = max(1, int(math.ceil(390 / int(minutes))))
    scale = bars_per_session / 2.0
    return {
        "bars_per_session": bars_per_session,
        "entry_window": max(2, int(round(240 * scale))),
        "exit_window": max(2, int(round(120 * scale))),
        "atr_window": max(2, int(round(20 * scale))),
        "cooldown_bars": max(0, int(round(12 * scale))),
        "failure_exit_window": max(1, int(round(6 * scale))),
        "ema_fast_days": 50,
        "ema_slow_days": 200,
        "atr_mult": 3.0,
    }


def _fixed_signal(market: pd.DataFrame, params: Mapping[str, Any]) -> pd.DataFrame:
    close = market["qqq_close"].astype(float)
    high = market["qqq_high"].astype(float)
    low = market["qqq_low"].astype(float)
    session = pd.Series(pd.DatetimeIndex(market.index).tz_convert("America/New_York").date.astype(str), index=market.index)
    daily_close = close.groupby(session).last()
    fast = daily_close.ewm(span=int(params["ema_fast_days"]), adjust=False).mean().shift(1)
    slow = daily_close.ewm(span=int(params["ema_slow_days"]), adjust=False).mean().shift(1)
    trend = (session.map(fast).astype(float) > session.map(slow).astype(float)) & (close > session.map(slow).astype(float))
    prior_high = high.shift(1).rolling(int(params["entry_window"]), min_periods=int(params["entry_window"])).max()
    prior_low = low.shift(1).rolling(int(params["exit_window"]), min_periods=int(params["exit_window"])).min()
    atr = _atr(high, low, close, int(params["atr_window"]))
    raw: list[float] = []
    reasons: list[str] = []
    state = 0.0
    cooldown = 0
    stop: float | None = None
    entry_pos: int | None = None
    entry_line: float | None = None
    for pos in range(len(market)):
        price = float(close.iloc[pos])
        atr_value = float(atr.iloc[pos])
        if cooldown > 0:
            cooldown -= 1
        if state > 0 and math.isfinite(atr_value):
            candidate = price - float(params["atr_mult"]) * atr_value
            stop = max(stop if stop is not None else candidate, candidate)
        failed = state > 0 and entry_pos is not None and entry_line is not None and pos - entry_pos <= int(params["failure_exit_window"]) and price < entry_line
        atr_exit = state > 0 and stop is not None and price < stop
        exit_rule = not bool(trend.iloc[pos]) or (pd.notna(prior_low.iloc[pos]) and price < float(prior_low.iloc[pos]))
        entry_rule = bool(trend.iloc[pos]) and pd.notna(prior_high.iloc[pos]) and price > float(prior_high.iloc[pos])
        if state <= 0 and cooldown <= 0 and entry_rule:
            state = 1.0
            stop = price - float(params["atr_mult"]) * atr_value if math.isfinite(atr_value) else None
            entry_pos = pos
            entry_line = float(prior_high.iloc[pos])
            reasons.append("entry:qqq_fixed_donchian")
        elif state > 0 and (exit_rule or atr_exit or failed):
            state = 0.0
            cooldown = int(params["cooldown_bars"])
            stop = None
            entry_pos = None
            entry_line = None
            reasons.append("exit:fixed_rule")
        else:
            reasons.append("hold_long" if state > 0 else "hold_cash")
        raw.append(state)
    signal = pd.DataFrame(index=market.index)
    signal["raw_signal"] = raw
    signal["effective_signal"] = signal["raw_signal"].shift(1).fillna(0.0)
    signal["signal_reason"] = reasons
    return signal


def _atr(high: pd.Series, low: pd.Series, close: pd.Series, window: int) -> pd.Series:
    previous = close.shift(1)
    true_range = pd.concat([(high - low).abs(), (high - previous).abs(), (low - previous).abs()], axis=1).max(axis=1)
    return true_range.rolling(window, min_periods=window).mean()


def _evaluate_timeframe(*, timeframe: str, market: pd.DataFrame, params: Mapping[str, Any], cost_bps_levels: Iterable[float]) -> tuple[dict[str, Any], pd.DataFrame, list[dict[str, Any]], list[dict[str, Any]]]:
    blockers: list[str] = []
    if len(market) < int(params["entry_window"]) + 50:
        blockers.append(f"{timeframe}_insufficient_bars")
    side = market["effective_signal"].astype(float)
    turnover = side.diff().abs().fillna(side.abs())
    gross = side * market["tqqq_open_to_next_open_return"].astype(float)
    periods_per_year = int(round(252 * float(params["bars_per_session"])))
    cost_rows: list[dict[str, Any]] = []
    fold_rows: list[dict[str, Any]] = []
    base_metrics: dict[str, Any] = {}
    base_ledger = pd.DataFrame()
    for cost_bps in cost_bps_levels:
        cost_return = turnover * float(cost_bps) / 10_000.0
        net = gross - cost_return
        metrics = _metrics(net, periods_per_year=periods_per_year, turnover=turnover, side=side, cost_return=cost_return)
        row = {"timeframe": timeframe, "cost_bps": float(cost_bps), **metrics}
        cost_rows.append(row)
        if abs(float(cost_bps) - BASE_COST_BPS) < 1e-9:
            base_metrics = metrics
            equity = INITIAL_CAPITAL * (1.0 + net.fillna(0.0)).cumprod()
            base_ledger = pd.DataFrame({
                "timestamp": market.index.astype(str),
                "timeframe": timeframe,
                "qqq_close": market["qqq_close"].to_numpy(),
                "tqqq_open": market["tqqq_open"].to_numpy(),
                "tqqq_next_open": market["tqqq_next_open"].to_numpy(),
                "raw_signal": market["raw_signal"].to_numpy(),
                "effective_signal": side.to_numpy(),
                "turnover": turnover.to_numpy(),
                "gross_return": gross.to_numpy(),
                "cost_return": cost_return.to_numpy(),
                "net_return": net.to_numpy(),
                "equity": equity.to_numpy(),
                "signal_reason": market["signal_reason"].to_numpy(),
            })
            fold_rows.extend(_walk_forward(timeframe=timeframe, net=net, periods_per_year=periods_per_year))
    if not base_metrics:
        blockers.append(f"{timeframe}_base_cost_missing")
    return {
        "status": "pass" if not blockers else "blocked",
        "blockers": blockers,
        "bar_count": int(len(market)),
        "start": _ts(market.index.min()) if len(market) else None,
        "end": _ts(market.index.max()) if len(market) else None,
        "params": dict(params),
        "base_cost_metrics": base_metrics,
        "walk_forward_summary": _fold_summary([row for row in fold_rows if row["timeframe"] == timeframe]),
    }, base_ledger, cost_rows, fold_rows


def _metrics(net: pd.Series, *, periods_per_year: int, turnover: pd.Series, side: pd.Series, cost_return: pd.Series) -> dict[str, Any]:
    net = net.fillna(0.0)
    equity = (1.0 + net).cumprod()
    total = float(equity.iloc[-1] - 1.0) if len(equity) else 0.0
    years = max(1.0 / periods_per_year, len(net) / periods_per_year)
    annual = (1.0 + total) ** (1.0 / years) - 1.0 if total > -1 else -1.0
    vol = float(net.std(ddof=0) * math.sqrt(periods_per_year)) if len(net) else 0.0
    drawdown = equity / equity.cummax() - 1.0 if len(equity) else pd.Series(dtype=float)
    return {
        "total_return_pct": _round(total * 100),
        "annual_return_pct": _round(annual * 100),
        "annual_vol_pct": _round(vol * 100),
        "sharpe": _round(annual / vol if vol > 1e-12 else 0.0),
        "max_drawdown_abs_pct": _round(abs(float(drawdown.min())) * 100 if len(drawdown) else 0.0),
        "turnover": _round(float(turnover.sum())),
        "trade_count": int((turnover > 0).sum()),
        "exposure_ratio": _round(float((side.abs() > 0).mean()) if len(side) else 0.0),
        "cost_drag_pct": _round(float(cost_return.sum()) * 100),
        "fee_paid_proxy": _round(float((INITIAL_CAPITAL * equity.shift(1).fillna(1.0) * cost_return).sum())),
    }


def _walk_forward(*, timeframe: str, net: pd.Series, periods_per_year: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    years = pd.DatetimeIndex(net.index).tz_convert("America/New_York").year
    for year in sorted({int(value) for value in years if int(value) >= 2020}):
        fold = net.loc[years == year]
        if len(fold) < 20:
            continue
        metrics = _metrics(fold, periods_per_year=periods_per_year, turnover=pd.Series(0.0, index=fold.index), side=pd.Series(0.0, index=fold.index), cost_return=pd.Series(0.0, index=fold.index))
        rows.append({"timeframe": timeframe, "fold_id": f"{timeframe}_{year}", "test_start": _ts(fold.index.min()), "test_end": _ts(fold.index.max()), "parameters_frozen": True, "training_selection_used": False, **metrics})
    return rows


def _fold_summary(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    returns = [float(row.get("total_return_pct", 0.0) or 0.0) for row in rows]
    return {"fold_count": len(rows), "positive_fold_count": sum(value > 0 for value in returns), "negative_fold_count": sum(value < 0 for value in returns), "worst_fold_return_pct": min(returns) if returns else None, "median_fold_return_pct": float(pd.Series(returns).median()) if returns else None}


def _summary(matrix_rows: list[Mapping[str, Any]], fold_rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    if not matrix_rows:
        return {"timeframe_count": 0, "best_timeframe_by_sharpe": None, "positive_base_cost_timeframe_count": 0}
    best = max(matrix_rows, key=lambda row: float(row.get("sharpe", -1e9) or -1e9))
    return {"timeframe_count": len(matrix_rows), "best_timeframe_by_sharpe": best.get("timeframe"), "positive_base_cost_timeframe_count": sum(float(row.get("total_return_pct", 0) or 0) > 0 for row in matrix_rows), "walk_forward_fold_count": len(fold_rows), "positive_walk_forward_fold_count": sum(float(row.get("total_return_pct", 0) or 0) > 0 for row in fold_rows)}


def _markdown(report: Mapping[str, Any]) -> str:
    lines = ["# TQQQ 固定规则多周期 Walk-Forward", "", f"- 状态：`{report.get('status')}`", f"- 决策：`{report.get('decision')}`", "", "| 周期 | 总收益 | 年化 | Sharpe | 最大回撤 |", "|---|---:|---:|---:|---:|"]
    for row in report.get("matrix_rows", []):
        lines.append(f"| {row.get('timeframe')} | {row.get('total_return_pct')}% | {row.get('annual_return_pct')}% | {row.get('sharpe')} | {row.get('max_drawdown_abs_pct')}% |")
    lines.extend(["", "本报告仅为 research-only，不允许自动进入 paper/live。", ""])
    return "\n".join(lines)


def _unique_timeframes(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        text = str(value).strip()
        if text not in TIMEFRAME_MINUTES:
            raise ValueError(f"unsupported timeframe: {text}")
        if text not in result:
            result.append(text)
    return result


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _write_csv(path: Path, rows: list[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git(args: list[str], *, cwd: Path) -> str:
    try:
        completed = subprocess.run(["git", *args], cwd=cwd, check=False, capture_output=True, text=True)
        return completed.stdout.strip() if completed.returncode == 0 else ""
    except OSError:
        return ""


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _relpath(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
    except ValueError:
        return str(path)


def _dedupe(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


def _round(value: float | int | None, digits: int = 6) -> float | None:
    return None if value is None or pd.isna(value) else round(float(value), digits)


def _ts(value: Any) -> str | None:
    return None if value is None or pd.isna(value) else pd.Timestamp(value).isoformat()
