#!/usr/bin/env python3
"""Research-only TQQQ migration of the BTC 10x sleeve compounding danger reference."""

from __future__ import annotations

import argparse
import csv
import json
import math
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import pandas as pd


SCHEMA_VERSION = "us_tqqq_btc_10x_rollover_migration_report_v1"
DEFAULT_OUTPUT_ROOT = Path("artifacts/us_tqqq_btc_10x_rollover_migration/latest")
DEFAULT_MARKDOWN = Path("学习资料/量化交易业务闭环/系统评估/TQQQ BTC 10x 滚仓迁移研究.md")
DEFAULT_BTC_CEILING_REPORT = Path("artifacts/btc_bankroll_rollover_review/latest/btc_bankroll_rollover_review_report.json")
INITIAL_CAPITAL = 25_000.0
INITIAL_SLEEVE_COUNT = 10
MAX_SLEEVE_COUNT = 100
ROLL_MULTIPLE = 2.0
TQQQ_MULTIPLIERS = (1.0, 1.5, 2.0, 3.0)
ROLLOVER_POLICIES = ("no_rollover", "split_2_on_double", "extract_principal_roll_profit")
COST_BPS_LEVELS = (0.0, 5.0, 10.0, 25.0, 50.0)
BASE_COST_BPS = 10.0
MARGIN_INTEREST_ANNUAL = 0.06
MAINTENANCE_MARGIN_RATE = 0.25
FORMAL_DONCHIAN_WINDOWS = (120, 180, 240)
FORMAL_DAILY_TRENDS = ((50, 200),)
FORMAL_ATR_MULTS = (2.0, 2.5, 3.0)
FORMAL_COOLDOWN_BARS = (0, 6, 12)
FORMAL_FAILURE_EXIT = (False, True)
FORMAL_RISK_FILTER_MODES = ("none",)
FORMAL_GRID_COUNT = (
    len(FORMAL_DONCHIAN_WINDOWS)
    * len(FORMAL_DAILY_TRENDS)
    * len(FORMAL_ATR_MULTS)
    * len(FORMAL_COOLDOWN_BARS)
    * len(FORMAL_FAILURE_EXIT)
    * len(FORMAL_RISK_FILTER_MODES)
)
ATR_WINDOW = 20
FAILURE_EXIT_WINDOW = 6
ROLLING_START_STEP_DAYS = 126
MIN_ROLLING_START_DAYS = 252


@dataclass
class Sleeve:
    sleeve_id: int
    equity: float
    basis_equity: float
    status: str = "active"
    rollover_count: int = 0
    margin_call_count: int = 0
    wipeout_count: int = 0


@dataclass(frozen=True)
class Scenario:
    scenario_id: str
    rollover_policy: str
    tqqq_multiplier: float
    cost_bps: float = BASE_COST_BPS
    margin_interest_annual: float = MARGIN_INTEREST_ANNUAL


@dataclass
class ScenarioResult:
    scenario: Scenario
    equity: pd.Series
    daily_return: pd.Series
    metrics: dict[str, Any]
    ledger_rows: list[dict[str, Any]]
    event_rows: list[dict[str, Any]]


def build_us_tqqq_btc_10x_rollover_migration_report(
    *,
    repo_root: Path | None = None,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    markdown_path: Path = DEFAULT_MARKDOWN,
    btc_ceiling_report: Path = DEFAULT_BTC_CEILING_REPORT,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at or datetime.now(timezone.utc).isoformat()
    output_abs = _resolve(root, output_root)
    markdown_abs = _resolve(root, markdown_path)
    output_abs.mkdir(parents=True, exist_ok=True)

    tqqq_frame, tqqq_source = _load_symbol_frame(root, "TQQQ")
    qqq_frame, qqq_source = _load_symbol_frame(root, "QQQ")
    blockers: list[str] = []
    if tqqq_frame.empty:
        blockers.append("tqqq_adjusted_ohlcv_missing")
    if qqq_frame.empty:
        blockers.append("qqq_adjusted_ohlcv_missing")

    btc_ceiling = _btc_ceiling(root, btc_ceiling_report)
    scenario_rows: list[dict[str, Any]] = []
    direction_grid_rows: list[dict[str, Any]] = []
    ledger_rows: list[dict[str, Any]] = []
    event_rows: list[dict[str, Any]] = []
    selected_analysis: dict[str, Any] = {}
    selected_direction: dict[str, Any] = {}
    status = "blocked" if blockers else "complete_research_only"

    if not blockers:
        market = _prepare_market(tqqq_frame, qqq_frame)
        if len(market) < max(slow for _, slow in FORMAL_DAILY_TRENDS) + max(FORMAL_DONCHIAN_WINDOWS):
            blockers.append("tqqq_qqq_common_history_insufficient")
            status = "blocked"
        else:
            direction_grid_rows, selected_direction, signal = _run_formal_donchian_direction_grid(market)
            market = market.join(signal, how="inner")
            results: list[ScenarioResult] = []
            scenarios = _scenario_plan()
            for scenario in scenarios:
                result = _simulate_scenario(scenario, market)
                results.append(result)
                scenario_rows.append(_scenario_row(result))
                if scenario.cost_bps == BASE_COST_BPS:
                    ledger_rows.extend(result.ledger_rows)
                    event_rows.extend(result.event_rows)

            scenario_rows = sorted(
                scenario_rows,
                key=lambda row: (
                    -float(row.get("final_equity", 0.0)),
                    int(row.get("total_margin_call_count", 0)),
                    float(row.get("max_drawdown_abs_pct", 100.0)),
                    str(row.get("scenario_id", "")),
                ),
            )
            selected_analysis = _selected_analysis(results, market)

    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated,
        "code_commit": _git(["rev-parse", "--short", "HEAD"], cwd=root),
        "status": status,
        "decision": "tqqq_btc_10x_rollover_migration_danger_reference_research_only_no_paper_no_live",
        "strategy_id": "us_tqqq_btc_10x_rollover_migration_danger_reference",
        "research_question": "Can the BTC 10x isolated sleeve compounding danger reference be structurally migrated to TQQQ without pretending it is paper/live ready?",
        "economic_hypothesis": "The transferable part is trend direction plus high beta exposure plus sleeve-level bankroll rules; any explosive result should be attributed to leveraged Nasdaq trend beta and path-dependent compounding, not to a new alpha.",
        "btc_danger_ceiling_reference": btc_ceiling,
        "migration_boundary": {
            "migrated": [
                "trend_direction_signal",
                "high_beta_instrument",
                "isolated_sleeves",
                "no_rollover",
                "split_2_on_double",
                "extract_principal_roll_profit",
                "rolling_start_and_gap_stress_review",
            ],
            "not_migrated": [
                "btc_perpetual_funding_model",
                "btc_mark_index_liquidation_model",
                "24_7_crypto_calendar",
                "same_4h_high_low_execution_proxy",
                "long_short_symmetric_perp_direction",
            ],
        },
        "data": {
            "traded_symbol": "TQQQ",
            "signal_symbol": "QQQ",
            "tqqq_source": tqqq_source,
            "qqq_source": qqq_source,
            "common_start": _date_str(tqqq_frame["datetime"].min()) if not tqqq_frame.empty else None,
            "common_end": _date_str(tqqq_frame["datetime"].max()) if not tqqq_frame.empty else None,
            "tqqq_rows": int(len(tqqq_frame)),
            "qqq_rows": int(len(qqq_frame)),
            "bar_timeframe": _bar_timeframe(tqqq_source, qqq_source),
            "periods_per_year": _periods_per_year_from_sources(tqqq_source, qqq_source),
            "pre_2010_tqqq_unavailable_no_2008_test": True,
        },
        "signal_rule": {
            "rule_id": "qqq_formal_donchian_grid_selected_long_cash",
            "decision_time_rule": _decision_time_rule(tqqq_source, qqq_source),
            "execution_time_rule": _execution_time_rule(tqqq_source, qqq_source),
            "origin": "Mirrors the BTC long/short Donchian formal narrow-grid discovery path: higher-timeframe EMA trend, 4H-style Donchian breakout, ATR trailing exit, cooldown, and failed breakout option.",
            "source_btc_pattern": "daily trend filter + Donchian breakout entry + Donchian/ATR trailing exit + cooldown + failed breakout exit, then shift(1) execution.",
            "bar_timeframe": _bar_timeframe(tqqq_source, qqq_source),
            "trend_visibility_rule": _trend_visibility_rule(tqqq_source, qqq_source),
            "selected_direction": selected_direction,
            "formal_grid": {
                "donchian_entry_windows": list(FORMAL_DONCHIAN_WINDOWS),
                "daily_trends": [{"ema_fast": fast, "ema_slow": slow} for fast, slow in FORMAL_DAILY_TRENDS],
                "atr_window": ATR_WINDOW,
                "atr_multipliers": list(FORMAL_ATR_MULTS),
                "cooldown_bars": list(FORMAL_COOLDOWN_BARS),
                "failed_breakout_exit": list(FORMAL_FAILURE_EXIT),
                "risk_filter_modes": list(FORMAL_RISK_FILTER_MODES),
                "candidate_count": len(direction_grid_rows),
                "expected_candidate_count": FORMAL_GRID_COUNT,
                "exit_window_rule": "exit_window=max(20, entry_window/2)",
            },
            "long_entry": "Selected EMA trend must be bullish and QQQ close must break the prior selected Donchian high.",
            "long_exit": "Selected EMA trend fails, QQQ breaks the selected Donchian exit line, ATR trailing stop fires, or optional failed breakout exit fires.",
            "shorting": "disabled in TQQQ v1; short side would require SQQQ/short QQQ and a separate borrow/execution model.",
        },
        "experiment_design": {
            "initial_capital": INITIAL_CAPITAL,
            "initial_sleeve_count": INITIAL_SLEEVE_COUNT,
            "max_sleeve_count": MAX_SLEEVE_COUNT,
            "roll_multiple": ROLL_MULTIPLE,
            "rollover_policies": list(ROLLOVER_POLICIES),
            "tqqq_multipliers": list(TQQQ_MULTIPLIERS),
            "nasdaq_equivalent_exposure_note": "1x TQQQ is roughly 3x Nasdaq daily exposure; 3x margin on TQQQ is roughly 9x Nasdaq beta.",
            "cost_bps_levels": list(COST_BPS_LEVELS),
            "base_cost_bps": BASE_COST_BPS,
            "margin_interest_annual": MARGIN_INTEREST_ANNUAL,
            "maintenance_margin_rate": MAINTENANCE_MARGIN_RATE,
            "scenario_plan": "base cost for all rollover policies and multipliers; cost stress for no_rollover only",
            "candidate_count": len(scenario_rows),
            "direction_candidate_count": len(direction_grid_rows),
        },
        "direction_grid_rows": direction_grid_rows[:50],
        "candidate_rows": scenario_rows,
        "analysis": selected_analysis,
        "gate": _gate(),
        "guardrails": _guardrails(),
        "warnings": _warnings(scenario_rows, selected_analysis),
        "blockers": _dedupe(blockers),
        "outputs": {
            "json": _relpath(output_abs / "us_tqqq_btc_10x_rollover_migration_report.json", root),
            "grid_csv": _relpath(output_abs / "us_tqqq_btc_10x_rollover_migration_grid.csv", root),
            "direction_grid_csv": _relpath(output_abs / "us_tqqq_btc_10x_rollover_migration_direction_grid.csv", root),
            "ledger_csv": _relpath(output_abs / "us_tqqq_btc_10x_rollover_migration_ledger.csv", root),
            "events_csv": _relpath(output_abs / "us_tqqq_btc_10x_rollover_migration_events.csv", root),
            "summary_cn": _relpath(markdown_abs, root),
        },
    }
    _write_json(output_abs / "us_tqqq_btc_10x_rollover_migration_report.json", report)
    _write_csv(output_abs / "us_tqqq_btc_10x_rollover_migration_grid.csv", scenario_rows)
    _write_csv(output_abs / "us_tqqq_btc_10x_rollover_migration_direction_grid.csv", direction_grid_rows)
    _write_csv(output_abs / "us_tqqq_btc_10x_rollover_migration_ledger.csv", ledger_rows)
    _write_csv(output_abs / "us_tqqq_btc_10x_rollover_migration_events.csv", event_rows)
    markdown_abs.parent.mkdir(parents=True, exist_ok=True)
    markdown_abs.write_text(_markdown(report), encoding="utf-8")
    return report


def _load_symbol_frame(root: Path, symbol: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    candidates = [
        (
            "yahoo_chart_intraday_1h_derived_4h",
            root / "data/external/us_equity_intraday/yahoo_chart/interval=4h/kline" / f"{symbol}.parquet",
        ),
        ("tiingo_eod", root / "data/external/us_equity_eod/tiingo/kline" / f"{symbol}.parquet"),
        ("yahoo_chart_adjusted", root / "data/external/us_equity_eod/yahoo_chart_adjusted/kline" / f"{symbol}.parquet"),
    ]
    attempted: list[dict[str, Any]] = []
    for source, path in candidates:
        if not path.exists():
            attempted.append({"source": source, "path": _relpath(path, root), "status": "missing"})
            continue
        frame = _normalize_price_frame(pd.read_parquet(path), symbol)
        quality = _quality(frame, symbol=symbol, root=root, path=path, source=source)
        attempted.append(quality)
        if quality["status"] == "available":
            return frame, {**quality, "attempted_sources": attempted}
    if attempted:
        best = attempted[-1]
        path = _resolve(root, Path(str(best.get("path", "")))) if best.get("path") else Path()
        if path.exists():
            return _normalize_price_frame(pd.read_parquet(path), symbol), {**best, "attempted_sources": attempted}
    return pd.DataFrame(), {"status": "missing", "attempted_sources": attempted}


def _normalize_price_frame(frame: pd.DataFrame, symbol: str) -> pd.DataFrame:
    working = frame.copy()
    rename = {
        "timestamp_utc": "datetime",
        "open": "Open",
        "high": "High",
        "low": "Low",
        "close": "Close",
        "volume": "Volume",
    }
    working = working.rename(columns={k: v for k, v in rename.items() if k in working.columns})
    required = ["datetime", "Open", "High", "Low", "Close", "Volume"]
    missing = [column for column in required if column not in working.columns]
    if missing:
        raise ValueError(f"{symbol} frame missing columns: {missing}")
    if "symbol" not in working.columns:
        working["symbol"] = symbol
    working["datetime"] = pd.to_datetime(working["datetime"], utc=True)
    for column in ("Open", "High", "Low", "Close", "Volume"):
        working[column] = pd.to_numeric(working[column], errors="coerce")
    return (
        working[["datetime", "symbol", "Open", "High", "Low", "Close", "Volume"]]
        .dropna(subset=["datetime", "Open", "High", "Low", "Close"])
        .sort_values("datetime")
        .drop_duplicates("datetime", keep="last")
        .reset_index(drop=True)
    )


def _quality(frame: pd.DataFrame, *, symbol: str, root: Path, path: Path, source: str) -> dict[str, Any]:
    blockers: list[str] = []
    if frame.empty:
        blockers.append(f"{symbol.lower()}_empty")
    ohlc = frame[["Open", "High", "Low", "Close"]].astype(float) if not frame.empty else pd.DataFrame()
    if not frame.empty:
        if int((ohlc <= 0).any(axis=1).sum()):
            blockers.append(f"{symbol.lower()}_non_positive_ohlc")
        invalid = int(((ohlc["High"] < ohlc[["Open", "Close", "Low"]].max(axis=1)) | (ohlc["Low"] > ohlc[["Open", "Close", "High"]].min(axis=1))).sum())
        if invalid:
            blockers.append(f"{symbol.lower()}_invalid_ohlc")
        if int(frame["datetime"].duplicated().sum()):
            blockers.append(f"{symbol.lower()}_duplicate_dates")
        max_abs_return = float(frame["Close"].pct_change(fill_method=None).abs().max())
        if max_abs_return > 0.45:
            blockers.append(f"{symbol.lower()}_extreme_daily_return_above_45pct")
    else:
        max_abs_return = 0.0
    return {
        "source": source,
        "path": _relpath(path, root),
        "bar_timeframe": _source_timeframe(source),
        "periods_per_year": _source_periods_per_year(source),
        "status": "available" if not blockers else "quality_concerns",
        "rows": int(len(frame)),
        "start": _date_str(frame["datetime"].min()) if not frame.empty else None,
        "end": _date_str(frame["datetime"].max()) if not frame.empty else None,
        "max_abs_bar_return": _round(max_abs_return),
        "blockers": blockers,
    }


def _prepare_market(tqqq: pd.DataFrame, qqq: pd.DataFrame) -> pd.DataFrame:
    left = tqqq.set_index("datetime")[["Open", "High", "Low", "Close", "Volume"]].rename(
        columns={column: f"tqqq_{column.lower()}" for column in ["Open", "High", "Low", "Close", "Volume"]}
    )
    right = qqq.set_index("datetime")[["Open", "High", "Low", "Close", "Volume"]].rename(
        columns={column: f"qqq_{column.lower()}" for column in ["Open", "High", "Low", "Close", "Volume"]}
    )
    market = left.join(right, how="inner").sort_index()
    market["tqqq_next_open"] = market["tqqq_open"].shift(-1)
    market["tqqq_open_to_next_open_return"] = market["tqqq_next_open"] / market["tqqq_open"] - 1.0
    market["tqqq_adverse_open_low_or_gap_return"] = pd.concat(
        [
            market["tqqq_low"] / market["tqqq_open"] - 1.0,
            market["tqqq_next_open"] / market["tqqq_open"] - 1.0,
        ],
        axis=1,
    ).min(axis=1)
    return market.dropna(subset=["tqqq_next_open", "tqqq_open_to_next_open_return"])


def _source_timeframe(source: str) -> str:
    if "intraday" in source or "derived_4h" in source:
        return "4H derived from Yahoo 1H research fallback"
    return "1D adjusted EOD"


def _source_periods_per_year(source: str) -> int:
    if "intraday" in source or "derived_4h" in source:
        return 504
    return 252


def _bar_timeframe(tqqq_source: Mapping[str, Any], qqq_source: Mapping[str, Any]) -> str:
    if tqqq_source.get("bar_timeframe") == qqq_source.get("bar_timeframe"):
        return str(tqqq_source.get("bar_timeframe"))
    return f"{tqqq_source.get('bar_timeframe')} / {qqq_source.get('bar_timeframe')}"


def _periods_per_year_from_sources(tqqq_source: Mapping[str, Any], qqq_source: Mapping[str, Any]) -> int:
    values = [int(source.get("periods_per_year", 252) or 252) for source in (tqqq_source, qqq_source)]
    return max(values)


def _decision_time_rule(tqqq_source: Mapping[str, Any], qqq_source: Mapping[str, Any]) -> str:
    timeframe = _bar_timeframe(tqqq_source, qqq_source)
    if timeframe.startswith("4H"):
        return "QQQ completed 4H bar computes raw signal only after bar_end_utc; daily EMA trend uses the prior completed session."
    return "QQQ completed daily close computes raw signal after market close."


def _execution_time_rule(tqqq_source: Mapping[str, Any], qqq_source: Mapping[str, Any]) -> str:
    timeframe = _bar_timeframe(tqqq_source, qqq_source)
    if timeframe.startswith("4H"):
        return "TQQQ target exposure is effective at the next completed 4H bar open; no same-bar execution."
    return "TQQQ target exposure is effective at the next trading day's open; no same-bar execution."


def _trend_visibility_rule(tqqq_source: Mapping[str, Any], qqq_source: Mapping[str, Any]) -> str:
    timeframe = _bar_timeframe(tqqq_source, qqq_source)
    if timeframe.startswith("4H"):
        return "Daily EMA trend is computed from QQQ session closes and shifted one session before being aligned to intraday bars."
    return "Daily EMA trend is computed from the completed daily close and shifted by the execution rule."


def _run_formal_donchian_direction_grid(market: pd.DataFrame) -> tuple[list[dict[str, Any]], dict[str, Any], pd.DataFrame]:
    rows: list[dict[str, Any]] = []
    signals: dict[str, pd.DataFrame] = {}
    for entry_window in FORMAL_DONCHIAN_WINDOWS:
        exit_window = max(20, int(entry_window / 2))
        for fast, slow in FORMAL_DAILY_TRENDS:
            for atr_mult in FORMAL_ATR_MULTS:
                for cooldown in FORMAL_COOLDOWN_BARS:
                    for failed_exit in FORMAL_FAILURE_EXIT:
                        for risk_mode in FORMAL_RISK_FILTER_MODES:
                            params = {
                                "entry_window": entry_window,
                                "exit_window": exit_window,
                                "ema_fast": fast,
                                "ema_slow": slow,
                                "atr_window": ATR_WINDOW,
                                "atr_mult": atr_mult,
                                "cooldown_bars": cooldown,
                                "use_failed_breakout_exit": failed_exit,
                                "failure_exit_window": FAILURE_EXIT_WINDOW,
                                "risk_filter_mode": risk_mode,
                            }
                            signal = _build_qqq_formal_donchian_signal(market, params)
                            metrics = _direction_metrics(market, signal)
                            candidate_id = (
                                f"formal_donchian_w{entry_window}_d{fast}_{slow}_"
                                f"atr{_num_id(atr_mult)}_cd{cooldown}_fail{int(failed_exit)}_risk{risk_mode}"
                            )
                            row = {
                                "candidate_id": candidate_id,
                                **params,
                                **metrics,
                                "selected_by": "cost_adjusted_tqqq_1x_direction_score",
                                "paper_queue_write_allowed": False,
                                "live_unlock_allowed": False,
                            }
                            rows.append(row)
                            signals[candidate_id] = signal
    ranked = sorted(
        rows,
        key=lambda row: (
            -float(row.get("score", -1e9)),
            float(row.get("max_drawdown_abs_pct", 100.0)),
            -float(row.get("total_return_pct", -100.0)),
            str(row.get("candidate_id")),
        ),
    )
    selected = dict(ranked[0]) if ranked else {}
    if not selected:
        empty = pd.DataFrame(index=market.index, data={"raw_signal": 0.0, "effective_signal": 0.0, "signal_reason": "blocked:no_direction_candidate"})
        return rows, selected, empty
    selected_signal = signals[str(selected["candidate_id"])].copy()
    selected_signal["selected_candidate_id"] = str(selected["candidate_id"])
    selected["rank"] = 1
    selected["top5"] = ranked[:5]
    return ranked, selected, selected_signal


def _build_qqq_formal_donchian_signal(market: pd.DataFrame, params: Mapping[str, Any]) -> pd.DataFrame:
    close = market["qqq_close"].astype(float)
    high = market["qqq_high"].astype(float)
    low = market["qqq_low"].astype(float)
    fast = int(params["ema_fast"])
    slow = int(params["ema_slow"])
    entry_window = int(params["entry_window"])
    exit_window = int(params["exit_window"])
    atr_mult = float(params["atr_mult"])
    cooldown_bars = int(params["cooldown_bars"])
    use_failed_breakout_exit = bool(params["use_failed_breakout_exit"])
    failure_exit_window = int(params["failure_exit_window"])
    if _is_intraday_index(market.index):
        ema_fast, ema_slow = _prior_session_daily_ema_aligned(close, fast=fast, slow=slow)
    else:
        ema_fast = close.ewm(span=fast, adjust=False).mean()
        ema_slow = close.ewm(span=slow, adjust=False).mean()
    prior_high = high.shift(1).rolling(entry_window, min_periods=entry_window).max()
    prior_low = low.shift(1).rolling(exit_window, min_periods=exit_window).min()
    trend_up = (ema_fast > ema_slow) & (close > ema_slow)
    entry = trend_up & (close > prior_high)
    exit_signal = (~trend_up) | (close < prior_low)
    atr = _atr_from_ohlc(market["qqq_high"], market["qqq_low"], market["qqq_close"], int(params["atr_window"]))
    close_arr = close.to_numpy(dtype=float)
    entry_arr = entry.fillna(False).to_numpy(dtype=bool)
    exit_arr = exit_signal.fillna(False).to_numpy(dtype=bool)
    atr_arr = atr.to_numpy(dtype=float)
    prior_high_arr = prior_high.to_numpy(dtype=float)
    raw: list[float] = []
    state = 0.0
    reasons: list[str] = []
    cooldown_remaining = 0
    atr_stop: float | None = None
    entry_pos: int | None = None
    entry_line: float | None = None
    for pos in range(len(market.index)):
        close_value = float(close_arr[pos])
        atr_value = float(atr_arr[pos])
        if cooldown_remaining > 0:
            cooldown_remaining -= 1
        if state > 0.0 and math.isfinite(atr_value):
            candidate_stop = close_value - atr_mult * atr_value
            atr_stop = max(atr_stop if atr_stop is not None else candidate_stop, candidate_stop)
        failed_breakout = (
            state > 0.0
            and use_failed_breakout_exit
            and entry_pos is not None
            and entry_line is not None
            and pos - entry_pos <= failure_exit_window
            and close_value < entry_line
        )
        atr_exit = state > 0.0 and atr_stop is not None and close_value < atr_stop
        if state <= 0.0 and cooldown_remaining <= 0 and bool(entry_arr[pos]):
            state = 1.0
            atr_stop = close_value - atr_mult * atr_value if math.isfinite(atr_value) else None
            entry_pos = pos
            prior_high_value = float(prior_high_arr[pos])
            entry_line = prior_high_value if math.isfinite(prior_high_value) else close_value
            reasons.append("entry:qqq_formal_donchian_breakout")
        elif state > 0.0 and (bool(exit_arr[pos]) or atr_exit or failed_breakout):
            state = 0.0
            cooldown_remaining = cooldown_bars
            atr_stop = None
            entry_pos = None
            entry_line = None
            if atr_exit:
                reasons.append("exit:atr_trailing_stop")
            elif failed_breakout:
                reasons.append("exit:failed_breakout")
            else:
                reasons.append("exit:qqq_trend_failed_or_donchian_breakdown")
        else:
            reasons.append("hold_long" if state > 0.0 else "hold_cash")
        raw.append(state)
    signal = pd.DataFrame(index=market.index)
    signal["raw_signal"] = raw
    signal["effective_signal"] = signal["raw_signal"].shift(1).fillna(0.0)
    signal["signal_timestamp"] = signal.index.astype(str)
    signal["effective_timestamp"] = signal.index.to_series().shift(-1).astype(str)
    signal["signal_reason"] = reasons
    return signal


def _is_intraday_index(index: pd.Index) -> bool:
    if len(index) < 3:
        return False
    deltas = pd.Series(pd.DatetimeIndex(index)).diff().dropna()
    if deltas.empty:
        return False
    return bool(deltas.median() < pd.Timedelta(hours=20))


def _prior_session_daily_ema_aligned(close: pd.Series, *, fast: int, slow: int) -> tuple[pd.Series, pd.Series]:
    index = pd.DatetimeIndex(close.index)
    local_dates = pd.Series(index.tz_convert("America/New_York").date.astype(str), index=index)
    daily_close = close.groupby(local_dates).last()
    daily_fast = daily_close.ewm(span=fast, adjust=False).mean().shift(1)
    daily_slow = daily_close.ewm(span=slow, adjust=False).mean().shift(1)
    fast_aligned = local_dates.map(daily_fast).astype(float)
    slow_aligned = local_dates.map(daily_slow).astype(float)
    fast_aligned.index = close.index
    slow_aligned.index = close.index
    return fast_aligned, slow_aligned


def _direction_metrics(market: pd.DataFrame, signal: pd.DataFrame) -> dict[str, Any]:
    periods_per_year = _periods_per_year(market)
    side = signal["effective_signal"].astype(float).reindex(market.index).fillna(0.0)
    tqqq_return = market["tqqq_open_to_next_open_return"].astype(float)
    turnover = side.diff().abs().fillna(abs(float(side.iloc[0]) if len(side) else 0.0))
    returns = side * tqqq_return - turnover * BASE_COST_BPS / 10_000.0
    equity = (1.0 + returns.fillna(0.0)).cumprod()
    total_return = float(equity.iloc[-1] - 1.0) if len(equity) else 0.0
    years = max(1.0 / periods_per_year, len(returns) / periods_per_year)
    annual_return = (1.0 + total_return) ** (1.0 / years) - 1.0 if total_return > -1.0 else -1.0
    vol = float(returns.std(ddof=0) * math.sqrt(periods_per_year)) if len(returns) else 0.0
    sharpe = annual_return / vol if vol > 1e-12 else 0.0
    dd = equity / equity.cummax() - 1.0 if len(equity) else pd.Series(dtype=float)
    max_dd = abs(float(dd.min())) if len(dd) else 0.0
    trade_count = int((turnover > 0).sum())
    exposure_ratio = float((side.abs() > 0).mean()) if len(side) else 0.0
    score = annual_return * 3.0 + sharpe * 0.25 - max_dd * 0.75
    if trade_count < 2 or exposure_ratio <= 0.01:
        score -= 10.0
    return {
        "total_return_pct": _round(total_return * 100.0),
        "annual_return_pct": _round(annual_return * 100.0),
        "annual_vol_pct": _round(vol * 100.0),
        "sharpe": _round(sharpe),
        "max_drawdown_abs_pct": _round(max_dd * 100.0),
        "turnover": _round(float(turnover.sum())),
        "trade_count": trade_count,
        "exposure_ratio": _round(exposure_ratio),
        "score": _round(score),
        "periods_per_year": int(periods_per_year),
    }


def _periods_per_year(market: pd.DataFrame | pd.Series) -> int:
    index = pd.DatetimeIndex(market.index)
    if len(index) < 3:
        return 252
    local_dates = pd.Series(index.tz_convert("America/New_York").date.astype(str))
    bars_per_day = max(1.0, float(local_dates.value_counts().median()))
    if bars_per_day > 1.0:
        return int(round(252.0 * bars_per_day))
    return 252


def _atr_from_ohlc(high: pd.Series, low: pd.Series, close: pd.Series, window: int) -> pd.Series:
    high = high.astype(float)
    low = low.astype(float)
    close = close.astype(float)
    prev_close = close.shift(1)
    tr = pd.concat([(high - low).abs(), (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    return tr.rolling(window, min_periods=window).mean()


def _simulate_scenario(scenario: Scenario, market: pd.DataFrame) -> ScenarioResult:
    periods_per_year = _periods_per_year(market)
    sleeve_initial = INITIAL_CAPITAL / INITIAL_SLEEVE_COUNT
    active_equity = INITIAL_CAPITAL
    active_sleeve_count = INITIAL_SLEEVE_COUNT
    basis_per_sleeve = sleeve_initial
    reserve_cash = 0.0
    previous_side = 0.0
    equity_values: list[float] = []
    dates: list[pd.Timestamp] = []
    ledger_rows: list[dict[str, Any]] = []
    event_rows: list[dict[str, Any]] = []
    total_fee = 0.0
    total_margin_interest = 0.0
    turnover_total = 0.0
    total_margin_call_count = 0
    total_wipeout_count = 0
    total_rolled_sleeve_count = 0
    max_sleeve_count = INITIAL_SLEEVE_COUNT
    margin_threshold = _margin_call_threshold(scenario.tqqq_multiplier)
    wipeout_threshold = -1.0 / scenario.tqqq_multiplier if scenario.tqqq_multiplier > 0 else -1.0

    for row in market.itertuples(index=True):
        ts = pd.Timestamp(row.Index)
        side = float(row.effective_signal)
        ret = float(row.tqqq_open_to_next_open_return)
        adverse = float(row.tqqq_adverse_open_low_or_gap_return)
        turnover = abs(side - previous_side) * float(scenario.tqqq_multiplier)
        turnover_total += turnover
        daily_fee = 0.0
        daily_interest = 0.0
        daily_margin_calls = 0
        daily_wipeouts = 0
        if turnover > 0.0 and active_sleeve_count > 0:
            daily_fee = active_equity * turnover * scenario.cost_bps / 10_000.0
            active_equity = max(0.0, active_equity - daily_fee)
        if side > 0.0 and active_sleeve_count > 0 and active_equity > 0.0:
            if scenario.tqqq_multiplier > 1.0 and adverse <= margin_threshold:
                daily_margin_calls = active_sleeve_count
                total_margin_call_count += active_sleeve_count
                event_rows.append(_aggregate_event(scenario, ts, "margin_call_forced_zero", active_equity, f"adverse_return={_round(adverse * 100)} pct <= threshold={_round(margin_threshold * 100)} pct; all active sleeves forced to zero"))
                active_equity = 0.0
                active_sleeve_count = 0
            elif ret <= wipeout_threshold:
                daily_wipeouts = active_sleeve_count
                total_wipeout_count += active_sleeve_count
                event_rows.append(_aggregate_event(scenario, ts, "open_to_open_wipeout", active_equity, f"return={_round(ret * 100)} pct <= wipeout_threshold={_round(wipeout_threshold * 100)} pct; all active sleeves forced to zero"))
                active_equity = 0.0
                active_sleeve_count = 0
            else:
                daily_interest = active_equity * max(0.0, scenario.tqqq_multiplier - 1.0) * scenario.margin_interest_annual / periods_per_year
                active_equity = max(0.0, active_equity * (1.0 + scenario.tqqq_multiplier * ret) - daily_interest)
                active_equity, active_sleeve_count, basis_per_sleeve, reserve_cash, rolled = _apply_aggregate_rollover(
                    active_equity=active_equity,
                    active_sleeve_count=active_sleeve_count,
                    basis_per_sleeve=basis_per_sleeve,
                    reserve_cash=reserve_cash,
                    scenario=scenario,
                    ts=ts,
                    event_rows=event_rows,
                )
                total_rolled_sleeve_count += rolled
                max_sleeve_count = max(max_sleeve_count, active_sleeve_count)
        total_fee += daily_fee
        total_margin_interest += daily_interest
        total_equity = reserve_cash + active_equity
        dates.append(pd.Timestamp(ts))
        equity_values.append(total_equity)
        ledger_rows.append(
            {
                "timestamp": pd.Timestamp(ts).isoformat(),
                "scenario_id": scenario.scenario_id,
                "rollover_policy": scenario.rollover_policy,
                "tqqq_multiplier": scenario.tqqq_multiplier,
                "nasdaq_equivalent_exposure": scenario.tqqq_multiplier * 3.0,
                "cost_bps": scenario.cost_bps,
                "qqq_close": _round(float(row.qqq_close)),
                "tqqq_open": _round(float(row.tqqq_open)),
                "tqqq_next_open": _round(float(row.tqqq_next_open)),
                "raw_signal": float(row.raw_signal),
                "effective_signal": side,
                "open_to_next_open_return": _round(ret),
                "adverse_open_low_or_gap_return": _round(adverse),
                "turnover": _round(turnover),
                "fee": _round(daily_fee),
                "margin_interest": _round(daily_interest),
                "daily_margin_calls": daily_margin_calls,
                "daily_wipeouts": daily_wipeouts,
                "active_sleeve_count": active_sleeve_count,
                "reserve_cash": _round(reserve_cash),
                "equity": _round(total_equity),
                "reason": row.signal_reason,
            }
        )
        previous_side = side

    equity = pd.Series(equity_values, index=pd.DatetimeIndex(dates), dtype=float)
    daily_return = equity.pct_change(fill_method=None).fillna(0.0)
    metrics = _aggregate_metrics(
        equity=equity,
        daily_return=daily_return,
        active_sleeve_count=active_sleeve_count,
        total_rolled_sleeve_count=total_rolled_sleeve_count,
        max_sleeve_count=max_sleeve_count,
        reserve_cash=reserve_cash,
        initial_capital=INITIAL_CAPITAL,
        total_fee=total_fee,
        total_margin_interest=total_margin_interest,
        turnover_total=turnover_total,
        total_margin_call_count=total_margin_call_count,
        total_wipeout_count=total_wipeout_count,
        scenario=scenario,
        periods_per_year=periods_per_year,
    )
    return ScenarioResult(scenario=scenario, equity=equity, daily_return=daily_return, metrics=metrics, ledger_rows=ledger_rows, event_rows=event_rows)


def _scenario_plan() -> list[Scenario]:
    scenarios: dict[str, Scenario] = {}
    for multiplier in TQQQ_MULTIPLIERS:
        for policy in ROLLOVER_POLICIES:
            scenario = Scenario(
                scenario_id=f"tqqq_{policy}_{_num_id(multiplier)}x_cost{_num_id(BASE_COST_BPS)}bps",
                rollover_policy=policy,
                tqqq_multiplier=multiplier,
                cost_bps=BASE_COST_BPS,
            )
            scenarios[scenario.scenario_id] = scenario
        for cost_bps in COST_BPS_LEVELS:
            scenario = Scenario(
                scenario_id=f"tqqq_no_rollover_{_num_id(multiplier)}x_cost{_num_id(cost_bps)}bps",
                rollover_policy="no_rollover",
                tqqq_multiplier=multiplier,
                cost_bps=cost_bps,
            )
            scenarios[scenario.scenario_id] = scenario
    return list(scenarios.values())


def _apply_aggregate_rollover(
    *,
    active_equity: float,
    active_sleeve_count: int,
    basis_per_sleeve: float,
    reserve_cash: float,
    scenario: Scenario,
    ts: pd.Timestamp,
    event_rows: list[dict[str, Any]],
) -> tuple[float, int, float, float, int]:
    if active_sleeve_count <= 0 or active_equity <= 0.0:
        return active_equity, active_sleeve_count, basis_per_sleeve, reserve_cash, 0
    rolled = 0
    average_sleeve_equity = active_equity / active_sleeve_count
    if average_sleeve_equity < basis_per_sleeve * ROLL_MULTIPLE:
        return active_equity, active_sleeve_count, basis_per_sleeve, reserve_cash, 0
    if scenario.rollover_policy == "no_rollover":
        return active_equity, active_sleeve_count, average_sleeve_equity, reserve_cash, 0
    if scenario.rollover_policy == "extract_principal_roll_profit":
        extract = min(active_equity, basis_per_sleeve * active_sleeve_count)
        active_equity = max(0.0, active_equity - extract)
        reserve_cash += extract
        basis_per_sleeve = active_equity / active_sleeve_count if active_sleeve_count and active_equity > 0.0 else 1e-9
        event_rows.append(_aggregate_event(scenario, ts, "extract_principal", extract, "aggregate principal moved to reserve cash"))
        return active_equity, active_sleeve_count, basis_per_sleeve, reserve_cash, 0
    while active_sleeve_count > 0 and active_sleeve_count * 2 <= MAX_SLEEVE_COUNT:
        average_sleeve_equity = active_equity / active_sleeve_count
        if average_sleeve_equity < basis_per_sleeve * ROLL_MULTIPLE:
            break
        old_count = active_sleeve_count
        active_sleeve_count *= 2
        basis_per_sleeve = active_equity / active_sleeve_count
        rolled += old_count
        event_rows.append(_aggregate_event(scenario, ts, "split_2_on_double", active_equity, f"aggregate active sleeve count doubled from {old_count} to {active_sleeve_count}"))
    return active_equity, active_sleeve_count, basis_per_sleeve, reserve_cash, rolled


def _aggregate_metrics(
    *,
    equity: pd.Series,
    daily_return: pd.Series,
    active_sleeve_count: int,
    total_rolled_sleeve_count: int,
    max_sleeve_count: int,
    reserve_cash: float,
    initial_capital: float,
    total_fee: float,
    total_margin_interest: float,
    turnover_total: float,
    total_margin_call_count: int,
    total_wipeout_count: int,
    scenario: Scenario,
    periods_per_year: int,
) -> dict[str, Any]:
    final_equity = float(equity.iloc[-1]) if len(equity) else 0.0
    total_return = final_equity / initial_capital - 1.0 if initial_capital else -1.0
    elapsed_years = max(1.0 / periods_per_year, len(equity) / periods_per_year)
    annual_return = (1.0 + total_return) ** (1.0 / elapsed_years) - 1.0 if total_return > -1.0 else -1.0
    vol = float(daily_return.std(ddof=0) * math.sqrt(periods_per_year)) if len(daily_return) else 0.0
    sharpe = annual_return / vol if vol > 1e-12 else 0.0
    drawdown = equity / equity.cummax() - 1.0 if len(equity) else pd.Series(dtype=float)
    max_dd = abs(float(drawdown.min())) if len(drawdown) else 0.0
    return {
        "final_equity": _round(final_equity),
        "total_return_pct": _round(total_return * 100.0),
        "annual_return_pct": _round(annual_return * 100.0),
        "annual_vol_pct": _round(vol * 100.0),
        "sharpe": _round(sharpe),
        "max_drawdown_abs_pct": _round(max_dd * 100.0),
        "calmar": _round(annual_return / max_dd if max_dd > 1e-12 else 0.0),
        "turnover": _round(turnover_total),
        "fee_paid": _round(total_fee),
        "margin_interest_paid": _round(total_margin_interest),
        "active_sleeve_count": int(active_sleeve_count),
        "rolled_sleeve_count": int(total_rolled_sleeve_count),
        "total_sleeve_count": int(active_sleeve_count + total_rolled_sleeve_count),
        "max_sleeves_observed": int(max_sleeve_count),
        "reserve_cash": _round(reserve_cash),
        "total_margin_call_count": int(total_margin_call_count),
        "total_wipeout_count": int(total_wipeout_count),
        "portfolio_zero": bool(final_equity <= 1e-9),
        "margin_call_threshold_pct": _round(_margin_call_threshold(scenario.tqqq_multiplier) * 100.0),
        "wipeout_threshold_pct": _round((-1.0 / scenario.tqqq_multiplier) * 100.0),
        "periods_per_year": int(periods_per_year),
    }


def _apply_rollover(
    sleeves: list[Sleeve],
    *,
    scenario: Scenario,
    ts: pd.Timestamp,
    event_rows: list[dict[str, Any]],
    next_sleeve_id: int,
    reserve_cash: float,
) -> tuple[int, float]:
    active = [sleeve for sleeve in sleeves if sleeve.status == "active" and sleeve.equity >= sleeve.basis_equity * ROLL_MULTIPLE]
    for sleeve in active:
        if scenario.rollover_policy == "no_rollover":
            sleeve.basis_equity = sleeve.equity
            continue
        if scenario.rollover_policy == "extract_principal_roll_profit":
            extract = min(sleeve.basis_equity, sleeve.equity)
            sleeve.equity -= extract
            reserve_cash += extract
            sleeve.basis_equity = max(sleeve.equity, 1e-9)
            sleeve.rollover_count += 1
            event_rows.append(_event(scenario, ts, sleeve, "extract_principal", extract, "principal moved to reserve cash"))
            continue
        active_count = len([item for item in sleeves if item.status == "active"])
        if active_count + 1 > MAX_SLEEVE_COUNT:
            sleeve.basis_equity = sleeve.equity
            event_rows.append(_event(scenario, ts, sleeve, "split_skipped_max_sleeves", 0.0, "max sleeve count reached"))
            continue
        parent_equity = sleeve.equity
        child_equity = parent_equity / 2.0
        sleeve.status = "rolled"
        sleeve.rollover_count += 1
        sleeve.equity = 0.0
        for _ in range(2):
            sleeves.append(Sleeve(sleeve_id=next_sleeve_id, equity=child_equity, basis_equity=child_equity))
            next_sleeve_id += 1
        event_rows.append(_event(scenario, ts, sleeve, "split_2_on_double", parent_equity, "equity split into child sleeves"))
    return next_sleeve_id, reserve_cash


def _metrics(
    *,
    equity: pd.Series,
    daily_return: pd.Series,
    sleeves: Sequence[Sleeve],
    reserve_cash: float,
    initial_capital: float,
    total_fee: float,
    total_margin_interest: float,
    turnover_total: float,
    scenario: Scenario,
) -> dict[str, Any]:
    final_equity = float(equity.iloc[-1]) if len(equity) else 0.0
    total_return = final_equity / initial_capital - 1.0 if initial_capital else -1.0
    elapsed_years = max(1.0 / 252.0, len(equity) / 252.0)
    annual_return = (1.0 + total_return) ** (1.0 / elapsed_years) - 1.0 if total_return > -1.0 else -1.0
    vol = float(daily_return.std(ddof=0) * math.sqrt(252.0)) if len(daily_return) else 0.0
    sharpe = annual_return / vol if vol > 1e-12 else 0.0
    drawdown = equity / equity.cummax() - 1.0 if len(equity) else pd.Series(dtype=float)
    max_dd = abs(float(drawdown.min())) if len(drawdown) else 0.0
    margin_calls = sum(sleeve.margin_call_count for sleeve in sleeves)
    wipeouts = sum(sleeve.wipeout_count for sleeve in sleeves)
    active_sleeves = [sleeve for sleeve in sleeves if sleeve.status == "active" and sleeve.equity > 0.0]
    rolled_sleeves = [sleeve for sleeve in sleeves if sleeve.status == "rolled"]
    return {
        "final_equity": _round(final_equity),
        "total_return_pct": _round(total_return * 100.0),
        "annual_return_pct": _round(annual_return * 100.0),
        "annual_vol_pct": _round(vol * 100.0),
        "sharpe": _round(sharpe),
        "max_drawdown_abs_pct": _round(max_dd * 100.0),
        "calmar": _round(annual_return / max_dd if max_dd > 1e-12 else 0.0),
        "turnover": _round(turnover_total),
        "fee_paid": _round(total_fee),
        "margin_interest_paid": _round(total_margin_interest),
        "active_sleeve_count": len(active_sleeves),
        "rolled_sleeve_count": len(rolled_sleeves),
        "total_sleeve_count": len(sleeves),
        "reserve_cash": _round(reserve_cash),
        "total_margin_call_count": int(margin_calls),
        "total_wipeout_count": int(wipeouts),
        "portfolio_zero": bool(final_equity <= 1e-9),
        "margin_call_threshold_pct": _round(_margin_call_threshold(scenario.tqqq_multiplier) * 100.0),
        "wipeout_threshold_pct": _round((-1.0 / scenario.tqqq_multiplier) * 100.0),
    }


def _selected_analysis(results: Sequence[ScenarioResult], market: pd.DataFrame) -> dict[str, Any]:
    by_id = {result.scenario.scenario_id: result for result in results}
    base_ids = {
        "one_x_no_rollover": "tqqq_no_rollover_1x_cost10bps",
        "three_x_no_rollover": "tqqq_no_rollover_3x_cost10bps",
        "three_x_split_2": "tqqq_split_2_on_double_3x_cost10bps",
        "three_x_extract": "tqqq_extract_principal_roll_profit_3x_cost10bps",
    }
    selected = {name: by_id.get(sid) for name, sid in base_ids.items()}
    analysis: dict[str, Any] = {
        "selected_scenarios": {name: sid for name, sid in base_ids.items()},
        "source_attribution": {},
        "rolling_start": {},
        "yearly_breakdown": {},
        "trend_segment_contribution": {},
        "cost_stress": {},
        "regime_notes": {
            "cannot_test_2008": "TQQQ inception is 2010-02-11 in available adjusted data.",
            "explicit_regimes": ["2020_covid_gap", "2022_rate_hike_bear", "2024_2026_ai_tech_beta"],
        },
    }
    one_x = selected["one_x_no_rollover"]
    three_x = selected["three_x_no_rollover"]
    split = selected["three_x_split_2"]
    extract = selected["three_x_extract"]
    if one_x and three_x and split and extract:
        analysis["source_attribution"] = {
            "one_x_tqqq_total_return_pct": one_x.metrics["total_return_pct"],
            "three_x_tqqq_margin_total_return_pct": three_x.metrics["total_return_pct"],
            "split_2_total_return_pct": split.metrics["total_return_pct"],
            "extract_principal_total_return_pct": extract.metrics["total_return_pct"],
            "split_incremental_final_equity_vs_no_rollover": _round(split.metrics["final_equity"] - three_x.metrics["final_equity"]),
            "main_driver": "tqqq_trend_beta_and_margin_compounding_not_split_2_rollover",
        }
    for name, result in selected.items():
        if result:
            if name in {"one_x_no_rollover", "three_x_no_rollover"}:
                analysis["rolling_start"][name] = _rolling_start(result.scenario, market)
            analysis["yearly_breakdown"][name] = _yearly_breakdown(result.equity)
            analysis["trend_segment_contribution"][name] = _trend_segments(result.equity, market)
    analysis["rolling_start_scope_note"] = "Rolling start is run on 1x and 3x no_rollover core compounding references; split_2 is compared in full-sample and attribution to avoid excessive research runtime."
    for multiplier in TQQQ_MULTIPLIERS:
        key = f"{_num_id(multiplier)}x_no_rollover"
        analysis["cost_stress"][key] = [
            _scenario_row(by_id[f"tqqq_no_rollover_{_num_id(multiplier)}x_cost{_num_id(cost)}bps"])
            for cost in COST_BPS_LEVELS
            if f"tqqq_no_rollover_{_num_id(multiplier)}x_cost{_num_id(cost)}bps" in by_id
        ]
    analysis["path_dependency"] = _path_dependency(analysis)
    return analysis


def _rolling_start(scenario: Scenario, market: pd.DataFrame) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    max_start = max(0, len(market) - MIN_ROLLING_START_DAYS)
    for start in range(0, max_start + 1, ROLLING_START_STEP_DAYS):
        sub = market.iloc[start:].copy()
        if len(sub) < MIN_ROLLING_START_DAYS:
            continue
        result = _simulate_scenario(scenario, sub)
        rows.append(
            {
                "start": pd.Timestamp(sub.index[0]).date().isoformat(),
                "end": pd.Timestamp(sub.index[-1]).date().isoformat(),
                "total_return_pct": result.metrics["total_return_pct"],
                "annual_return_pct": result.metrics["annual_return_pct"],
                "max_drawdown_abs_pct": result.metrics["max_drawdown_abs_pct"],
                "final_equity": result.metrics["final_equity"],
                "total_margin_call_count": result.metrics["total_margin_call_count"],
                "portfolio_zero": result.metrics["portfolio_zero"],
            }
        )
    returns = [float(row["total_return_pct"]) for row in rows]
    return {
        "row_count": len(rows),
        "worst_total_return_pct": _round(min(returns)) if returns else None,
        "median_total_return_pct": _round(float(pd.Series(returns).median())) if returns else None,
        "best_total_return_pct": _round(max(returns)) if returns else None,
        "portfolio_zero_count": sum(1 for row in rows if row["portfolio_zero"]),
        "margin_call_start_count": sum(1 for row in rows if int(row["total_margin_call_count"]) > 0),
        "rows": rows[:20],
    }


def _yearly_breakdown(equity: pd.Series) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if equity.empty:
        return rows
    returns = equity.pct_change(fill_method=None).fillna(0.0)
    total_positive_log = 0.0
    year_logs: dict[int, float] = {}
    for year, group in returns.groupby(returns.index.year):
        log_ret = float((1.0 + group).clip(lower=1e-9).apply(math.log).sum())
        year_logs[int(year)] = log_ret
        if log_ret > 0:
            total_positive_log += log_ret
    for year, group in returns.groupby(returns.index.year):
        eq = equity.loc[group.index]
        year_return = float(eq.iloc[-1] / eq.iloc[0] - 1.0) if len(eq) > 1 and eq.iloc[0] else 0.0
        drawdown = eq / eq.cummax() - 1.0
        rows.append(
            {
                "year": int(year),
                "return_pct": _round(year_return * 100.0),
                "max_drawdown_abs_pct": _round(abs(float(drawdown.min())) * 100.0),
                "log_contribution_share_of_positive_years": _round(year_logs[int(year)] / total_positive_log) if total_positive_log > 0 and year_logs[int(year)] > 0 else 0.0,
            }
        )
    return rows


def _trend_segments(equity: pd.Series, market: pd.DataFrame) -> dict[str, Any]:
    if equity.empty:
        return {"segment_count": 0, "rows": []}
    signal = market.reindex(equity.index)["effective_signal"].fillna(0.0)
    segment_id = ((signal != signal.shift(1)) & (signal > 0)).cumsum()
    rows: list[dict[str, Any]] = []
    for sid, idx in segment_id[signal > 0].groupby(segment_id[signal > 0]).groups.items():
        segment_equity = equity.loc[idx]
        if len(segment_equity) < 2:
            continue
        if float(segment_equity.iloc[0]) <= 1e-12:
            continue
        ret = float(segment_equity.iloc[-1] / segment_equity.iloc[0] - 1.0)
        if not math.isfinite(ret):
            continue
        rows.append(
            {
                "segment_id": int(sid),
                "start": pd.Timestamp(segment_equity.index[0]).date().isoformat(),
                "end": pd.Timestamp(segment_equity.index[-1]).date().isoformat(),
                "return_pct": _round(ret * 100.0),
                "days": int(len(segment_equity)),
            }
        )
    rows = sorted(rows, key=lambda row: float(row["return_pct"]), reverse=True)
    total_positive = sum(float(row["return_pct"]) for row in rows if float(row["return_pct"]) > 0.0)
    return {
        "segment_count": len(rows),
        "top_segment_positive_return_share": _round(float(rows[0]["return_pct"]) / total_positive) if rows and total_positive > 0 else None,
        "rows": rows[:20],
    }


def _path_dependency(analysis: Mapping[str, Any]) -> dict[str, Any]:
    flags: list[str] = []
    for name, rolling in analysis.get("rolling_start", {}).items():
        if rolling.get("portfolio_zero_count", 0) or rolling.get("margin_call_start_count", 0):
            flags.append(f"{name}:rolling_start_margin_or_zero")
        worst = rolling.get("worst_total_return_pct")
        median = rolling.get("median_total_return_pct")
        if worst is not None and median is not None and float(median) - float(worst) > 500.0:
            flags.append(f"{name}:wide_rolling_start_dispersion")
    for name, yearly in analysis.get("yearly_breakdown", {}).items():
        if any(float(row.get("log_contribution_share_of_positive_years", 0.0)) > 0.5 for row in yearly):
            flags.append(f"{name}:single_year_contribution_concentration")
    return {
        "status": "path_dependent" if flags else "no_path_dependency_flag_from_current_checks",
        "flags": flags,
    }


def _scenario_row(result: ScenarioResult) -> dict[str, Any]:
    return {
        "scenario_id": result.scenario.scenario_id,
        "rollover_policy": result.scenario.rollover_policy,
        "tqqq_multiplier": result.scenario.tqqq_multiplier,
        "nasdaq_equivalent_exposure": result.scenario.tqqq_multiplier * 3.0,
        "cost_bps": result.scenario.cost_bps,
        "margin_interest_annual": result.scenario.margin_interest_annual,
        **result.metrics,
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
        "research_decision": _research_decision(result),
    }


def _research_decision(result: ScenarioResult) -> str:
    if result.metrics.get("portfolio_zero"):
        return "reject_portfolio_zero_danger_reference_only"
    if int(result.metrics.get("total_margin_call_count", 0)) > 0:
        return "reject_margin_call_observed_danger_reference_only"
    if float(result.metrics.get("max_drawdown_abs_pct", 100.0)) > 70.0:
        return "reject_drawdown_above_70_danger_reference_only"
    return "retain_danger_reference_only_not_candidate"


def _btc_ceiling(root: Path, path: Path) -> dict[str, Any]:
    full = _resolve(root, path)
    if not full.exists():
        return {"status": "missing", "path": _relpath(full, root)}
    payload = json.loads(full.read_text(encoding="utf-8"))
    summary = payload.get("source_attribution", {}).get("summary", {})
    return {
        "status": payload.get("status"),
        "decision": payload.get("decision"),
        "path": _relpath(full, root),
        "no_rollover_total_return_pct": summary.get("leverage_compounding_proxy_10x_no_rollover_total_return_pct"),
        "split_2_total_return_pct": summary.get("split_2_total_return_pct"),
        "split_incremental_pct_of_no_rollover_equity": summary.get("split_incremental_pct_of_10x_no_rollover_equity"),
        "main_driver": summary.get("main_driver"),
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
    }


def _margin_call_threshold(multiplier: float) -> float:
    if multiplier <= 1.0:
        return -1.0
    return (MAINTENANCE_MARGIN_RATE * multiplier - 1.0) / (multiplier * (1.0 - MAINTENANCE_MARGIN_RATE))


def _event(scenario: Scenario, ts: pd.Timestamp, sleeve: Sleeve, event_type: str, amount: float, note: str) -> dict[str, Any]:
    return {
        "timestamp": pd.Timestamp(ts).isoformat(),
        "scenario_id": scenario.scenario_id,
        "sleeve_id": sleeve.sleeve_id,
        "event_type": event_type,
        "amount": _round(amount),
        "sleeve_equity_after": _round(sleeve.equity),
        "note": note,
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
    }


def _aggregate_event(scenario: Scenario, ts: pd.Timestamp, event_type: str, amount: float, note: str) -> dict[str, Any]:
    return {
        "timestamp": pd.Timestamp(ts).isoformat(),
        "scenario_id": scenario.scenario_id,
        "sleeve_id": "aggregate",
        "event_type": event_type,
        "amount": _round(amount),
        "sleeve_equity_after": None,
        "note": note,
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
    }


def _gate() -> dict[str, Any]:
    return {
        "status": "research_only_danger_reference",
        "paper_queue_write_allowed": False,
        "paper_candidate_created": False,
        "forward_observation_allowed": False,
        "live_unlock_allowed": False,
        "live_order_allowed": False,
        "broker_access_allowed": False,
        "order_endpoint_used": False,
        "reason": "Migration is a danger ceiling research reference, not a candidate strategy.",
    }


def _guardrails() -> dict[str, Any]:
    return {
        "research_only": True,
        "private_endpoint_used": False,
        "broker_endpoint_used": False,
        "order_endpoint_used": False,
        "real_order_submitted": False,
        "paper_queue_write_allowed": False,
        "live_order_allowed": False,
        "paper_or_live_unlock_allowed": False,
    }


def _warnings(rows: Sequence[Mapping[str, Any]], analysis: Mapping[str, Any]) -> list[str]:
    warnings = ["tqqq_btc_10x_rollover_migration_danger_reference_only"]
    if any(int(row.get("total_margin_call_count", 0)) > 0 for row in rows):
        warnings.append("tqqq_margin_call_observed")
    if any(bool(row.get("portfolio_zero")) for row in rows):
        warnings.append("tqqq_portfolio_zero_observed")
    if analysis.get("path_dependency", {}).get("status") == "path_dependent":
        warnings.append("tqqq_path_dependent")
    warnings.append("tqqq_not_paper_or_live_candidate")
    return warnings


def _markdown(report: Mapping[str, Any]) -> str:
    rows = report.get("candidate_rows", [])
    top = rows[0] if rows else {}
    signal_rule = report.get("signal_rule", {})
    selected_direction = signal_rule.get("selected_direction", {})
    source = report.get("analysis", {}).get("source_attribution", {})
    path_dep = report.get("analysis", {}).get("path_dependency", {})
    data = report.get("data", {})
    lines = [
        "# TQQQ 迁移 BTC 10x 滚仓爆炸版研究",
        "",
        "## 结论",
        "",
        f"- 状态：`{report.get('status')}`。",
        f"- 决策：`{report.get('decision')}`。",
        "- 这是 danger reference，不是 paper/live 候选。",
        f"- 最佳场景：`{top.get('scenario_id')}`，总收益 `{top.get('total_return_pct')}`%，最大回撤 `{top.get('max_drawdown_abs_pct')}`%，margin call `{top.get('total_margin_call_count')}`。",
        f"- 路径依赖：`{path_dep.get('status')}`。",
        f"- 方向层不是固定简化规则，而是 formal Donchian top-family grid，候选数 `{signal_rule.get('formal_grid', {}).get('candidate_count')}`。",
        f"- 选中方向：`{selected_direction.get('candidate_id')}`，方向层总收益 `{selected_direction.get('total_return_pct')}`%，回撤 `{selected_direction.get('max_drawdown_abs_pct')}`%。",
        "",
        "## 来源归因",
        "",
        f"- 1x TQQQ no_rollover 总收益：`{source.get('one_x_tqqq_total_return_pct')}`%。",
        f"- 3x TQQQ margin no_rollover 总收益：`{source.get('three_x_tqqq_margin_total_return_pct')}`%。",
        f"- 3x TQQQ split_2 总收益：`{source.get('split_2_total_return_pct')}`%。",
        f"- split_2 相比 no_rollover 最终权益增量：`{source.get('split_incremental_final_equity_vs_no_rollover')}`。",
        f"- 主驱动：`{source.get('main_driver')}`。",
        "",
        "## 数据与执行",
        "",
        f"- 交易标的：`{report.get('data', {}).get('traded_symbol')}`；信号标的：`{report.get('data', {}).get('signal_symbol')}`。",
        f"- TQQQ 数据源：`{data.get('tqqq_source', {}).get('source')}`，覆盖 `{data.get('tqqq_source', {}).get('start')}` 到 `{data.get('tqqq_source', {}).get('end')}`。",
        f"- bar 周期：`{data.get('bar_timeframe')}`，年化周期数 `{data.get('periods_per_year')}`。",
        f"- 决策时间：{signal_rule.get('decision_time_rule')}",
        f"- 执行时间：{signal_rule.get('execution_time_rule')}",
        "- 2008 无法测试，因为 TQQQ 可用数据从 2010 年开始。",
        "",
        "## 风险边界",
        "",
        "- 不迁移 BTC 永续 funding、mark/index、24/7 交易和强平模型。",
        "- 3x TQQQ margin 约等于 9x Nasdaq beta，只作为极端研究上限。",
        "- 若出现 margin call、组合归零或单一年份/单一趋势段贡献集中，必须保持 danger reference。",
    ]
    return "\n".join(lines) + "\n"


def _num_id(value: float) -> str:
    text = f"{value:g}".replace(".", "p")
    return text


def _round(value: float | int | None, digits: int = 6) -> float | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except TypeError:
        pass
    return round(float(value), digits)


def _date_str(value: Any) -> str | None:
    if value is None or pd.isna(value):
        return None
    return pd.Timestamp(value).date().isoformat()


def _dedupe(items: Iterable[str]) -> list[str]:
    result: list[str] = []
    for item in items:
        value = str(item)
        if value and value not in result:
            result.append(value)
    return result


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False), encoding="utf-8")


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(str(key))
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: _csv_value(row.get(field)) for field in fieldnames})


def _csv_value(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return value


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _relpath(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
    except ValueError:
        return str(path)


def _git(args: list[str], *, cwd: Path) -> str:
    try:
        completed = subprocess.run(["git", *args], cwd=cwd, check=False, capture_output=True, text=True)
    except OSError:
        return ""
    if completed.returncode != 0:
        return ""
    return completed.stdout.strip()


def main() -> None:
    parser = argparse.ArgumentParser(description="Build TQQQ research-only migration report for BTC 10x rollover danger reference.")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--markdown-path", default=str(DEFAULT_MARKDOWN))
    parser.add_argument("--btc-ceiling-report", default=str(DEFAULT_BTC_CEILING_REPORT))
    parser.add_argument("--generated-at", default="")
    args = parser.parse_args()
    root = Path(args.repo_root).resolve()
    report = build_us_tqqq_btc_10x_rollover_migration_report(
        repo_root=root,
        output_root=Path(args.output_root),
        markdown_path=Path(args.markdown_path),
        btc_ceiling_report=Path(args.btc_ceiling_report),
        generated_at=args.generated_at or None,
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "decision": report["decision"],
                "report": report["outputs"]["json"],
                "blockers": report.get("blockers", []),
            },
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
