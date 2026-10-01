from __future__ import annotations

import csv
import hashlib
import json
import math
import sqlite3
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd

from quant_crypto.research.multi_timeframe_rule_lab import aggregate_ohlcv_calendar
from quant_crypto.research.simple_trend_rule_lab import (
    BASE_COST_BPS,
    DEFAULT_DERIVATIVES_ROWS,
    DEFAULT_MARKET_DB,
    EXCHANGE,
    INITIAL_CAPITAL,
    SYMBOL,
    aggregate_ohlcv,
    align_derivatives_to_index,
    load_market_1h,
)


SCHEMA_VERSION = "btc_multi_timeframe_ma_ladder_v2_lab_v1"
DEFAULT_OUTPUT_DIR = Path("artifacts/btc_multi_timeframe_ma_ladder_v2_lab/latest")
DEFAULT_REPORT_PATH = DEFAULT_OUTPUT_DIR / "btc_multi_timeframe_ma_ladder_v2_lab_report.json"
DEFAULT_GRID_PATH = DEFAULT_OUTPUT_DIR / "btc_multi_timeframe_ma_ladder_v2_lab_grid.csv"
DEFAULT_EVENTS_PATH = DEFAULT_OUTPUT_DIR / "btc_multi_timeframe_ma_ladder_v2_lab_events.csv"
DEFAULT_MARKDOWN_PATH = DEFAULT_OUTPUT_DIR / "btc_multi_timeframe_ma_ladder_v2_lab_summary_cn.md"
DEFAULT_SAFETY_PATH = DEFAULT_OUTPUT_DIR / "paper_live_safety_status.json"

SOURCE_INTERVAL = "15m"
BASE_INTERVAL = "15m"
BASE_BARS_PER_YEAR = 365.0 * 24.0 * 4.0
MIN_15M_BARS = 20_000
MIN_1H_BARS = 5_000
BASE_INTERVAL_HOURS = 0.25
FUNDING_INTERVAL_HOURS = 8.0
MAX_RESEARCH_LEVERAGE = 5.0
DEFAULT_RUN_PROFILE = "smoke"
RUN_PROFILES = {"smoke", "best_neighbor", "formal"}
RUN_PROFILE_SPEC_LIMITS = {"smoke": 24, "best_neighbor": None, "formal": None}

DAILY_TRENDS = ((20, 80), (34, 144), (50, 200))
HOURLY_TRENDS = ((24, 96), (48, 192))
FOUR_HOUR_TRENDS = ((18, 72), (30, 120))
TREND_EFFICIENCY_THRESHOLDS = (0.18, 0.24)
LEVERAGE_GRID = (1.0, 2.0, 3.0)
TAKE_PROFIT_GRID = (0.06, 0.10, 0.14)
STOP_LOSS_GRID = (0.025, 0.035)
TREND_FAIL_BARS_GRID = (4, 8)
ENTRY_COOLDOWN_GRID = (16, 32)
LEVEL_SETS: dict[str, tuple[tuple[str, int, float], ...]] = {
    "short_ma_pullback": (("15m", 20, 0.45), ("30m", 20, 0.35), ("1h", 20, 0.20)),
    "balanced_ma_pullback": (("15m", 50, 0.35), ("30m", 50, 0.35), ("1h", 50, 0.30)),
}


@dataclass(frozen=True)
class MaLadderV2Spec:
    variant_id: str
    label: str
    params: dict[str, Any]
    optimization_stage: str
    optimization_components: list[str]
    notes: list[str]

    @property
    def candidate_id(self) -> str:
        raw = {
            "variant_id": self.variant_id,
            "params": self.params,
            "optimization_stage": self.optimization_stage,
            "optimization_components": self.optimization_components,
        }
        digest = hashlib.sha1(json.dumps(raw, sort_keys=True).encode("utf-8")).hexdigest()[:10]
        return f"btc_mtf_ma_ladder_v2_{self.variant_id}_{digest}"


@dataclass
class EvaluatedMaLadderV2:
    spec: MaLadderV2Spec
    direction: pd.Series
    exposure: pd.Series
    returns: pd.Series
    turnover: pd.Series
    cost: pd.Series
    funding_pnl: pd.Series
    equity: pd.Series
    entry_fill: pd.Series
    metrics: dict[str, Any]
    events: tuple[dict[str, Any], ...]


def build_btc_multi_timeframe_ma_ladder_v2_lab(
    *,
    market_db_path: Path = DEFAULT_MARKET_DB,
    derivatives_rows_path: Path = DEFAULT_DERIVATIVES_ROWS,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    generated_at_utc: datetime | None = None,
    initial_capital: float = INITIAL_CAPITAL,
    base_cost_bps: float = BASE_COST_BPS,
    run_profile: str = DEFAULT_RUN_PROFILE,
    max_specs: int | None = None,
) -> dict[str, Any]:
    if run_profile not in RUN_PROFILES:
        raise ValueError(f"unsupported run_profile: {run_profile}")
    generated = generated_at_utc or datetime.now(timezone.utc)
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / DEFAULT_REPORT_PATH.name
    grid_path = output_dir / DEFAULT_GRID_PATH.name
    events_path = output_dir / DEFAULT_EVENTS_PATH.name
    markdown_path = output_dir / DEFAULT_MARKDOWN_PATH.name
    safety_path = output_dir / DEFAULT_SAFETY_PATH.name

    frames = _load_fast_timeframes(market_db_path)
    base = frames[BASE_INTERVAL]
    derivatives_15m = align_derivatives_to_index(derivatives_rows_path, base.index)
    blockers: list[str] = []
    if len(base) < MIN_15M_BARS:
        blockers.append("btc_multi_timeframe_ma_ladder_v2_insufficient_15m_bars")
    if len(frames["1h"]) < MIN_1H_BARS:
        blockers.append("btc_multi_timeframe_ma_ladder_v2_insufficient_1h_bars")

    all_specs = ma_ladder_v2_specs(run_profile=run_profile)
    profile_limit = RUN_PROFILE_SPEC_LIMITS[run_profile]
    effective_limit = int(max_specs) if max_specs is not None else profile_limit
    specs = all_specs[: int(effective_limit)] if effective_limit is not None else all_specs
    precomputed = _precompute_features(frames)

    evaluated = [
        evaluate_ma_ladder_v2(
            spec,
            frames=frames,
            precomputed=precomputed,
            derivatives_15m=derivatives_15m,
            initial_capital=initial_capital,
            cost_bps=base_cost_bps,
            collect_events=idx < 5,
        )
        for idx, spec in enumerate(specs)
    ]
    rows = [
        _grid_row(
            item,
            frames=frames,
            derivatives_15m=derivatives_15m,
            initial_capital=initial_capital,
            base_cost_bps=base_cost_bps,
        )
        for item in evaluated
    ]
    ranked = sorted(rows, key=_rank_key)
    watchlist = [dict(row) for row in ranked if row["retention_decision"] == "retain_ma_ladder_v2_research_watchlist_only"][:20]
    event_rows = [event for item in evaluated[:5] for event in item.events]
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated.astimezone(timezone.utc).isoformat(),
        "status": "blocked" if blockers else "complete_research_only",
        "decision": "btc_multi_timeframe_ma_ladder_v2_lab_research_only_no_paper_no_live",
        "scope": "btc_strong_trend_short_cycle_ma_pullback_ladder_v2_research",
        "code_commit": _git_commit(),
        "input": {
            "market_db_path": _portable_path(market_db_path),
            "derivatives_rows_path": _portable_path(derivatives_rows_path),
            "symbol": SYMBOL,
            "exchange": EXCHANGE,
            "source_intervals": ["15m", "1h"],
            "base_execution_interval": BASE_INTERVAL,
            "bar_15m_rows": int(len(base)),
            "bar_1h_rows": int(len(frames["1h"])),
            "bar_4h_rows": int(len(frames["4h"])),
            "bar_1d_rows": int(len(frames["1d"])),
            "bar_15m_start": _ts(base.index.min()) if len(base) else None,
            "bar_15m_end": _ts(base.index.max()) if len(base) else None,
            "fast_timeframe_policy": "read existing 15m/1h rows; derive 4h/1d/1w/1mo from complete 1h rows to avoid v1 full 1m resampling",
            "derivatives_visible_rows": int(derivatives_15m["funding_rate"].notna().sum()) if "funding_rate" in derivatives_15m else 0,
            "derivatives_available_time_rule": "derivatives rows are aligned by available_time <= 15m decision_time",
        },
        "research_design": {
            "economic_hypothesis": "强趋势短线里，均线回撤挂价比追价更容易控制盈亏比；震荡不做，进场后只因止盈、止损或趋势失败退出。",
            "run_profile": run_profile,
            "candidate_count": len(specs),
            "formal_candidate_count": len(all_specs),
            "trial_count": len(specs),
            "selected_by": "annual return, total return, PF, drawdown, cost stress, low-turnover campaign behavior and liquidation diagnostics",
            "v2_changes_vs_v1": [
                "只读已有 15m/1h 数据，避免每次全量 1m 重采样",
                "强趋势过滤更严格：日线许可，4H/1H 同向确认，趋势效率必须通过",
                "挂价入场后不频繁调仓，一个趋势战役只持有到止盈、止损或趋势失败",
                "明确止盈，不再靠频繁换仓累积收益",
                "趋势失败才清仓，不做每日清仓",
            ],
            "entry_rule": "completed 15m decision bar computes trend and MA ladder; next completed 15m high/low confirms resting limit fill",
            "pnl_rule": "filled campaign exposure earns return only from the following 15m close-to-close bar",
            "exit_rule": "fixed take profit, fixed stop loss, or N completed 15m bars of trend failure",
            "level_sets": LEVEL_SETS,
            "daily_trends": [list(item) for item in DAILY_TRENDS],
            "hourly_trends": [list(item) for item in HOURLY_TRENDS],
            "four_hour_trends": [list(item) for item in FOUR_HOUR_TRENDS],
            "trend_efficiency_thresholds": list(TREND_EFFICIENCY_THRESHOLDS),
            "leverage_grid": list(LEVERAGE_GRID),
            "take_profit_grid": list(TAKE_PROFIT_GRID),
            "stop_loss_grid": list(STOP_LOSS_GRID),
            "trend_fail_bars_grid": list(TREND_FAIL_BARS_GRID),
            "entry_cooldown_grid": list(ENTRY_COOLDOWN_GRID),
            "max_research_leverage": MAX_RESEARCH_LEVERAGE,
            "cost_model": {"base_cost_bps": float(base_cost_bps), "stress_multipliers": [1, 2, 5]},
            "funding_model": {
                "enabled": True,
                "formula": "funding_pnl = -exposure.shift(1) * funding_rate * (15m / 8h)",
                "research_approximation": True,
            },
            "no_lookahead_policy": [
                "15m and 1h rows are completed market bars from the sqlite store",
                "4h/1d/1w/1mo bars are derived from completed 1h rows",
                "trend, stop and target decisions use completed decision bars",
                "limit fill is checked only on the next completed 15m bar",
                "filled exposure is effective after fill bar close via exposure.shift(1)",
                "derivatives require available_time <= decision_time",
            ],
        },
        "guardrails": _guardrails(),
        "gate": _gate(),
        "summary": _summary(ranked, watchlist=watchlist, blockers=blockers),
        "comparison_rows": ranked,
        "ma_ladder_v2_research_watchlist": watchlist,
        "event_rows_sample": event_rows[:500],
        "blockers": blockers,
        "warnings": _warnings(ranked, blockers=blockers),
        "outputs": {
            "json": _portable_path(report_path),
            "grid_csv": _portable_path(grid_path),
            "events_csv": _portable_path(events_path),
            "summary_cn": _portable_path(markdown_path),
            "paper_live_safety_status": _portable_path(safety_path),
        },
    }
    _write_json(report_path, report)
    _write_csv(grid_path, _grid_fieldnames(), ranked)
    _write_csv(events_path, _event_fieldnames(), event_rows[:2000])
    _write_text(markdown_path, render_btc_multi_timeframe_ma_ladder_v2_lab_markdown(report))
    _write_json(safety_path, _safety_status(report))
    return report


def _load_fast_timeframes(market_db_path: Path) -> dict[str, pd.DataFrame]:
    bars_15m = load_market_interval(market_db_path, "15m")
    bars_1h = load_market_1h(market_db_path)
    bars_4h = aggregate_ohlcv(bars_1h, interval_hours=4)
    bars_1d = aggregate_ohlcv(bars_1h, interval_hours=24)
    bars_1w = aggregate_ohlcv_calendar(bars_1h, timeframe="1w")
    bars_1mo = aggregate_ohlcv_calendar(bars_1h, timeframe="1mo")
    bars_30m = aggregate_ohlcv_from_interval(bars_15m, minutes=30, source_minutes=15)
    return {
        "15m": bars_15m,
        "30m": bars_30m,
        "1h": bars_1h,
        "4h": bars_4h,
        "1d": bars_1d,
        "1w": bars_1w,
        "1mo": bars_1mo,
    }


def load_market_interval(path: Path, interval: str) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"market data sqlite not found: {path}")
    conn = sqlite3.connect(path)
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
            [EXCHANGE, SYMBOL, interval],
        ).fetchall()
    finally:
        conn.close()
    if not rows:
        raise ValueError(f"no {SYMBOL} {interval} rows in {path}")
    frame = pd.DataFrame(rows, columns=["open_time", "close_time", "open", "high", "low", "close", "volume"])
    frame["open_time"] = pd.to_datetime(frame["open_time"], utc=True)
    frame["close_time"] = pd.to_datetime(frame["close_time"], utc=True)
    for col in ["open", "high", "low", "close", "volume"]:
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    frame = frame.dropna(subset=["open", "high", "low", "close", "volume"]).sort_values("close_time")
    frame = frame.set_index("close_time")
    return frame[["open_time", "open", "high", "low", "close", "volume"]]


def aggregate_ohlcv_from_interval(frame: pd.DataFrame, *, minutes: int, source_minutes: int) -> pd.DataFrame:
    needed = int(minutes // source_minutes)
    rows: list[dict[str, Any]] = []
    for start, chunk in frame.groupby(pd.Grouper(key="open_time", freq=f"{minutes}min")):
        if len(chunk) != needed:
            continue
        rows.append(
            {
                "open_time": start,
                "close_time": chunk.index.max(),
                "open": float(chunk["open"].iloc[0]),
                "high": float(chunk["high"].max()),
                "low": float(chunk["low"].min()),
                "close": float(chunk["close"].iloc[-1]),
                "volume": float(chunk["volume"].sum()),
            }
        )
    output = pd.DataFrame(rows)
    if output.empty:
        return pd.DataFrame(columns=["open_time", "open", "high", "low", "close", "volume"])
    output = output.set_index(pd.to_datetime(output["close_time"], utc=True))
    return output[["open_time", "open", "high", "low", "close", "volume"]].sort_index()


def ma_ladder_v2_specs(*, run_profile: str = "formal") -> list[MaLadderV2Spec]:
    if run_profile == "best_neighbor":
        return ma_ladder_v2_best_neighbor_specs()
    specs = [
        MaLadderV2Spec(
            variant_id="original_d50_200_h24_96_f18_72_lev1_tp10_sl35_tf4_cd16_balanced",
            label="v2 原始版：强趋势 + 均线挂价 + 10%止盈 + 趋势失败退出",
            params=_params(
                daily=(50, 200),
                hourly=(24, 96),
                four_hour=(18, 72),
                trend_efficiency=0.18,
                leverage=1.0,
                take_profit=0.10,
                stop_loss=0.035,
                trend_fail_bars=4,
                cooldown=16,
                max_pullback=0.035,
                level_set="balanced_ma_pullback",
            ),
            optimization_stage="original",
            optimization_components=[],
            notes=["closer to manual strong-trend MA pullback: wait for MA price, hold campaign until target/stop/trend fail"],
        )
    ]
    for daily_fast, daily_slow in DAILY_TRENDS:
        for hourly_fast, hourly_slow in HOURLY_TRENDS:
            for four_fast, four_slow in FOUR_HOUR_TRENDS:
                for trend_eff in TREND_EFFICIENCY_THRESHOLDS:
                    for leverage in LEVERAGE_GRID:
                        for take_profit in TAKE_PROFIT_GRID:
                            for stop_loss in STOP_LOSS_GRID:
                                for trend_fail_bars in TREND_FAIL_BARS_GRID:
                                    for cooldown in ENTRY_COOLDOWN_GRID:
                                        for level_set in LEVEL_SETS:
                                            variant_id = (
                                                f"formal_d{daily_fast}_{daily_slow}_h{hourly_fast}_{hourly_slow}"
                                                f"_f{four_fast}_{four_slow}_te{_num_slug(trend_eff)}"
                                                f"_lev{_num_slug(leverage)}_tp{_num_slug(take_profit)}"
                                                f"_sl{_num_slug(stop_loss)}_tf{trend_fail_bars}_cd{cooldown}_{level_set}"
                                            )
                                            components = [
                                                "strong_trend_filter",
                                                "ma_pullback_limit_entry",
                                                "single_campaign_hold",
                                                "fixed_take_profit",
                                                "fixed_stop_loss",
                                                "trend_failure_exit",
                                                "entry_cooldown",
                                            ]
                                            if leverage > 1.0:
                                                components.append("research_leverage")
                                            specs.append(
                                                MaLadderV2Spec(
                                                    variant_id=variant_id,
                                                    label="v2 formal strong-trend MA pullback campaign",
                                                    params=_params(
                                                        daily=(daily_fast, daily_slow),
                                                        hourly=(hourly_fast, hourly_slow),
                                                        four_hour=(four_fast, four_slow),
                                                        trend_efficiency=trend_eff,
                                                        leverage=leverage,
                                                        take_profit=take_profit,
                                                        stop_loss=stop_loss,
                                                        trend_fail_bars=trend_fail_bars,
                                                        cooldown=cooldown,
                                                        max_pullback=0.035,
                                                        level_set=level_set,
                                                    ),
                                                    optimization_stage="formal_narrow_v2_grid",
                                                    optimization_components=components,
                                                    notes=[
                                                        "predeclared narrow v2 grid",
                                                        "entry is pullback limit only; derivatives are funding/cost diagnostics only",
                                                    ],
                                                )
                                            )
    return specs


def ma_ladder_v2_best_neighbor_specs() -> list[MaLadderV2Spec]:
    specs: list[MaLadderV2Spec] = []
    for leverage in (1.0, 2.0, 3.0):
        for take_profit in (0.06, 0.08):
            for trend_fail_bars in (8, 12):
                for cooldown in (16, 32):
                    for max_pullback in (0.025, 0.035):
                        variant_id = (
                            "neighbor_best"
                            f"_d20_80_h24_96_f18_72_te0p18"
                            f"_lev{_num_slug(leverage)}_tp{_num_slug(take_profit)}"
                            f"_sl0p025_tf{trend_fail_bars}_cd{cooldown}"
                            f"_pb{_num_slug(max_pullback)}_short_ma_pullback"
                        )
                        specs.append(
                            MaLadderV2Spec(
                                variant_id=variant_id,
                                label="v2 best-neighbor strong-trend MA pullback campaign",
                                params=_params(
                                    daily=(20, 80),
                                    hourly=(24, 96),
                                    four_hour=(18, 72),
                                    trend_efficiency=0.18,
                                    leverage=leverage,
                                    take_profit=take_profit,
                                    stop_loss=0.025,
                                    trend_fail_bars=trend_fail_bars,
                                    cooldown=cooldown,
                                    max_pullback=max_pullback,
                                    level_set="short_ma_pullback",
                                ),
                                optimization_stage="best_neighbor_narrow_grid",
                                optimization_components=[
                                    "current_best_neighborhood",
                                    "research_leverage_1x_2x_3x",
                                    "lower_turnover_cooldown",
                                    "trend_failure_hold",
                                    "manual_style_take_profit",
                                    "ma_pullback_limit_entry",
                                ],
                                notes=[
                                    "fixed around current best: d20/80 h24/96 f18/72 te0.18 short_ma_pullback",
                                    "tests 2x/3x and lower-turnover campaign controls without expanding full parameter space",
                                ],
                            )
                        )
    return specs


def _params(
    *,
    daily: tuple[int, int],
    hourly: tuple[int, int],
    four_hour: tuple[int, int],
    trend_efficiency: float,
    leverage: float,
    take_profit: float,
    stop_loss: float,
    trend_fail_bars: int,
    cooldown: int,
    max_pullback: float,
    level_set: str,
) -> dict[str, Any]:
    return {
        "daily_fast": daily[0],
        "daily_slow": daily[1],
        "hourly_fast": hourly[0],
        "hourly_slow": hourly[1],
        "four_hour_fast": four_hour[0],
        "four_hour_slow": four_hour[1],
        "weekly_fast": 8,
        "weekly_slow": 21,
        "monthly_fast": 3,
        "monthly_slow": 8,
        "trend_efficiency_window_1h": 96,
        "trend_efficiency_threshold": trend_efficiency,
        "leverage": leverage,
        "take_profit_pct": take_profit,
        "stop_loss_pct": stop_loss,
        "trend_fail_bars": trend_fail_bars,
        "entry_cooldown_bars": cooldown,
        "max_pullback_pct": max_pullback,
        "level_set": level_set,
        "primary_signal_source": "strong_trend_ma_pullback_ladder",
        "derivatives_usage": "funding_cost_diagnostic_only",
    }


def evaluate_ma_ladder_v2(
    spec: MaLadderV2Spec,
    *,
    frames: Mapping[str, pd.DataFrame],
    precomputed: Mapping[str, pd.Series],
    derivatives_15m: pd.DataFrame,
    initial_capital: float,
    cost_bps: float,
    collect_events: bool = False,
) -> EvaluatedMaLadderV2:
    base = frames[BASE_INTERVAL]
    close = base["close"].astype(float)
    high = base["high"].astype(float)
    low = base["low"].astype(float)
    direction, levels = _decision_inputs(spec, frames=frames, precomputed=precomputed)
    direction = direction.reindex(close.index).fillna(0.0).clip(-1.0, 1.0)
    levels = levels.reindex(close.index).ffill()
    exposure, entry_fill, event_rows = _simulate_campaign_exposure(
        spec,
        close=close,
        high=high,
        low=low,
        direction=direction,
        levels=levels,
        collect_events=collect_events,
    )
    bar_returns = close.pct_change().fillna(0.0)
    effective_exposure = exposure.shift(1).fillna(0.0)
    turnover = exposure.diff().abs().fillna(exposure.abs())
    cost = turnover * (float(cost_bps) / 10_000.0)
    funding_rate = pd.to_numeric(derivatives_15m.get("funding_rate", pd.Series(0.0, index=close.index)), errors="coerce").reindex(close.index).fillna(0.0)
    funding_pnl = (-effective_exposure * funding_rate * (BASE_INTERVAL_HOURS / FUNDING_INTERVAL_HOURS)).fillna(0.0)
    strategy_returns = (effective_exposure * bar_returns + funding_pnl - cost).fillna(0.0).clip(lower=-0.95)
    equity = float(initial_capital) * (1.0 + strategy_returns).cumprod()
    metrics = performance_metrics(
        strategy_returns=strategy_returns,
        equity=equity,
        exposure=exposure,
        turnover=turnover,
        cost=cost,
        funding_pnl=funding_pnl,
        initial_capital=initial_capital,
    )
    metrics.update(_campaign_diagnostics(exposure=exposure, entry_fill=entry_fill, close=close, high=high, low=low))
    return EvaluatedMaLadderV2(
        spec=spec,
        direction=direction,
        exposure=exposure,
        returns=strategy_returns,
        turnover=turnover,
        cost=cost,
        funding_pnl=funding_pnl,
        equity=equity,
        entry_fill=entry_fill,
        metrics=metrics,
        events=tuple(event_rows),
    )


def _precompute_features(frames: Mapping[str, pd.DataFrame]) -> dict[str, pd.Series]:
    index = frames[BASE_INTERVAL].index
    output: dict[str, pd.Series] = {}
    for timeframe in ["15m", "30m", "1h", "4h", "1d", "1w", "1mo"]:
        close = frames[timeframe]["close"].astype(float)
        for span in sorted({2, 3, 8, 18, 20, 21, 24, 30, 34, 48, 50, 72, 80, 96, 120, 144, 192, 200}):
            output[f"{timeframe}_ema_{span}"] = _ema(close, span=span).reindex(index, method="ffill")
    one_hour_close = frames["1h"]["close"].astype(float)
    output["trend_efficiency_1h_96"] = _trend_efficiency(one_hour_close, window=96).reindex(index, method="ffill").fillna(0.0)
    return output


def _decision_inputs(
    spec: MaLadderV2Spec,
    *,
    frames: Mapping[str, pd.DataFrame],
    precomputed: Mapping[str, pd.Series],
) -> tuple[pd.Series, pd.DataFrame]:
    params = spec.params
    index = frames[BASE_INTERVAL].index
    daily_side = _side_from_precomputed(
        precomputed=precomputed,
        timeframe="1d",
        index=index,
        fast=int(params["daily_fast"]),
        slow=int(params["daily_slow"]),
        close=frames["1d"]["close"].astype(float).reindex(index, method="ffill"),
    )
    hourly_side = _side_from_precomputed(
        precomputed=precomputed,
        timeframe="1h",
        index=index,
        fast=int(params["hourly_fast"]),
        slow=int(params["hourly_slow"]),
        close=frames["1h"]["close"].astype(float).reindex(index, method="ffill"),
    )
    four_hour_side = _side_from_precomputed(
        precomputed=precomputed,
        timeframe="4h",
        index=index,
        fast=int(params["four_hour_fast"]),
        slow=int(params["four_hour_slow"]),
        close=frames["4h"]["close"].astype(float).reindex(index, method="ffill"),
    )
    monthly_side = _side_from_precomputed(
        precomputed=precomputed,
        timeframe="1mo",
        index=index,
        fast=int(params["monthly_fast"]),
        slow=int(params["monthly_slow"]),
        close=frames["1mo"]["close"].astype(float).reindex(index, method="ffill"),
    )
    efficiency_ok = precomputed["trend_efficiency_1h_96"].reindex(index).fillna(0.0) >= float(params["trend_efficiency_threshold"])
    direction = pd.Series(0.0, index=index)
    direction[(daily_side > 0.0) & (hourly_side > 0.0) & (four_hour_side > 0.0) & (monthly_side >= 0.0) & efficiency_ok] = 1.0
    direction[(daily_side < 0.0) & (hourly_side < 0.0) & (four_hour_side < 0.0) & (monthly_side <= 0.0) & efficiency_ok] = -1.0

    levels: dict[str, pd.Series] = {}
    for pos, (timeframe, span, weight) in enumerate(LEVEL_SETS[str(params["level_set"])]):
        levels[f"level_{pos}_{timeframe}_ema{span}_w{_num_slug(weight)}"] = precomputed[f"{timeframe}_ema_{span}"].reindex(index).ffill()
    return direction, pd.DataFrame(levels, index=index)


def _side_from_precomputed(
    *,
    precomputed: Mapping[str, pd.Series],
    timeframe: str,
    index: pd.DatetimeIndex,
    fast: int,
    slow: int,
    close: pd.Series,
) -> pd.Series:
    fast_ema = precomputed[f"{timeframe}_ema_{fast}"].reindex(index)
    slow_ema = precomputed[f"{timeframe}_ema_{slow}"].reindex(index)
    side = pd.Series(0.0, index=index)
    side[(fast_ema > slow_ema) & (close > slow_ema)] = 1.0
    side[(fast_ema < slow_ema) & (close < slow_ema)] = -1.0
    return side.fillna(0.0)


def _simulate_campaign_exposure(
    spec: MaLadderV2Spec,
    *,
    close: pd.Series,
    high: pd.Series,
    low: pd.Series,
    direction: pd.Series,
    levels: pd.DataFrame,
    collect_events: bool,
) -> tuple[pd.Series, pd.Series, list[dict[str, Any]]]:
    params = spec.params
    leverage = float(params["leverage"])
    take_profit = float(params["take_profit_pct"])
    stop_loss = float(params["stop_loss_pct"])
    max_pullback = float(params["max_pullback_pct"])
    trend_fail_bars = int(params["trend_fail_bars"])
    entry_cooldown_bars = int(params["entry_cooldown_bars"])

    exposure = [0.0 for _ in close.index]
    entry_fill = [0.0 for _ in close.index]
    events: list[dict[str, Any]] = []
    position_side = 0.0
    entry_price = math.nan
    trend_fail_count = 0
    cooldown = 0

    for i in range(1, len(close)):
        decision_i = i - 1
        decision_time = close.index[decision_i]
        fill_time = close.index[i]
        decision_close = float(close.iloc[decision_i])
        desired_side = float(direction.iloc[decision_i])
        if cooldown > 0:
            desired_side = 0.0
            cooldown -= 1

        if position_side != 0.0:
            move = position_side * (decision_close / entry_price - 1.0) if math.isfinite(entry_price) and entry_price > 0.0 else 0.0
            trend_failed_now = desired_side != position_side
            trend_fail_count = trend_fail_count + 1 if trend_failed_now else 0
            stop_hit = move <= -stop_loss
            target_hit = move >= take_profit
            trend_exit = trend_fail_count >= trend_fail_bars
            if stop_hit or target_hit or trend_exit:
                if collect_events:
                    events.append(
                        _event_row(
                            spec=spec,
                            timestamp=fill_time,
                            event_type="campaign_exit",
                            side=position_side,
                            exposure_before=position_side * leverage,
                            exposure_after=0.0,
                            fill_price=decision_close,
                            note=_exit_note(stop_hit=stop_hit, target_hit=target_hit, trend_exit=trend_exit),
                        )
                    )
                position_side = 0.0
                entry_price = math.nan
                trend_fail_count = 0
                cooldown = entry_cooldown_bars if stop_hit or trend_exit else max(1, entry_cooldown_bars // 2)

        if position_side == 0.0 and desired_side != 0.0 and cooldown <= 0:
            fill_price = _next_bar_ladder_fill_price(
                side=desired_side,
                decision_close=decision_close,
                next_high=float(high.iloc[i]),
                next_low=float(low.iloc[i]),
                level_row=levels.iloc[decision_i],
                max_pullback=max_pullback,
            )
            if math.isfinite(fill_price):
                position_side = desired_side
                entry_price = fill_price
                entry_fill[i] = 1.0
                if collect_events:
                    events.append(
                        _event_row(
                            spec=spec,
                            timestamp=fill_time,
                            event_type="ma_ladder_campaign_entry",
                            side=position_side,
                            exposure_before=0.0,
                            exposure_after=position_side * leverage,
                            fill_price=fill_price,
                            note=f"decision_time={_ts(decision_time)}",
                        )
                    )
        exposure[i] = position_side * leverage
    return pd.Series(exposure, index=close.index), pd.Series(entry_fill, index=close.index), events


def _next_bar_ladder_fill_price(
    *,
    side: float,
    decision_close: float,
    next_high: float,
    next_low: float,
    level_row: pd.Series,
    max_pullback: float,
) -> float:
    filled: list[tuple[float, float]] = []
    for column, raw_level in level_row.items():
        level = float(raw_level)
        if not math.isfinite(level) or level <= 0.0:
            continue
        weight = _weight_from_level_column(str(column))
        if side > 0.0:
            distance = (decision_close - level) / decision_close
            if 0.0 < distance <= max_pullback and next_low <= level:
                filled.append((level, weight))
        else:
            distance = (level - decision_close) / decision_close
            if 0.0 < distance <= max_pullback and next_high >= level:
                filled.append((level, weight))
    if not filled:
        return math.nan
    total_weight = sum(weight for _level, weight in filled)
    return sum(level * weight for level, weight in filled) / total_weight if total_weight > 0.0 else math.nan


def performance_metrics(
    *,
    strategy_returns: pd.Series,
    equity: pd.Series,
    exposure: pd.Series,
    turnover: pd.Series,
    cost: pd.Series,
    funding_pnl: pd.Series,
    initial_capital: float,
) -> dict[str, Any]:
    if strategy_returns.empty:
        return _empty_metrics(initial_capital)
    total_return = float(equity.iloc[-1] / float(initial_capital) - 1.0)
    elapsed_days = max(1.0, float((strategy_returns.index.max() - strategy_returns.index.min()).total_seconds()) / 86_400.0)
    annual_return = (1.0 + total_return) ** (365.0 / elapsed_days) - 1.0 if total_return > -1.0 else -1.0
    std = float(strategy_returns.std(ddof=0))
    downside = strategy_returns[strategy_returns < 0.0]
    downside_std = float(downside.std(ddof=0)) if len(downside) else 0.0
    sharpe = float(strategy_returns.mean() / std * math.sqrt(BASE_BARS_PER_YEAR)) if std > 0.0 else 0.0
    sortino = float(strategy_returns.mean() / downside_std * math.sqrt(BASE_BARS_PER_YEAR)) if downside_std > 0.0 else 0.0
    drawdown = equity / equity.cummax() - 1.0
    max_drawdown = float(drawdown.min()) if len(drawdown) else 0.0
    positive = strategy_returns[strategy_returns > 0.0].sum()
    negative = strategy_returns[strategy_returns < 0.0].sum()
    profit_factor = float(positive / abs(negative)) if negative < 0.0 else (999.0 if positive > 0.0 else 0.0)
    exposed_returns = strategy_returns[exposure.shift(1).fillna(0.0).abs() > 0.0]
    return {
        "total_return_pct": _round(total_return * 100.0),
        "annual_return_pct": _round(annual_return * 100.0),
        "annual_volatility_pct": _round(std * math.sqrt(BASE_BARS_PER_YEAR) * 100.0),
        "downside_volatility_pct": _round(downside_std * math.sqrt(BASE_BARS_PER_YEAR) * 100.0),
        "sharpe_ratio": _round(sharpe),
        "sortino_ratio": _round(sortino),
        "calmar_ratio": _round(float(annual_return / abs(max_drawdown)) if max_drawdown < 0.0 else 0.0),
        "profit_factor": _round(profit_factor),
        "max_drawdown_pct": _round(max_drawdown * 100.0),
        "max_drawdown_abs_pct": _round(abs(max_drawdown) * 100.0),
        "final_equity": _round(float(equity.iloc[-1])),
        "average_exposure": _round(float(exposure.abs().mean())),
        "average_net_exposure": _round(float(exposure.mean())),
        "bars_with_exposure": int((exposure.abs() > 0.0).sum()),
        "long_bar_count": int((exposure > 0.0).sum()),
        "short_bar_count": int((exposure < 0.0).sum()),
        "turnover": _round(float(turnover.sum())),
        "exposure_change_count": int((turnover > 1e-12).sum()),
        "fee_return_pct": _round(float(cost.sum()) * -100.0),
        "funding_return_pct": _round(float(funding_pnl.sum()) * 100.0),
        "winning_exposed_bar_pct": _round(float((exposed_returns > 0.0).mean()) * 100.0) if len(exposed_returns) else 0.0,
    }


def _grid_row(
    item: EvaluatedMaLadderV2,
    *,
    frames: Mapping[str, pd.DataFrame],
    derivatives_15m: pd.DataFrame,
    initial_capital: float,
    base_cost_bps: float,
) -> dict[str, Any]:
    cost_stress = cost_stress_summary(
        item,
        frames=frames,
        derivatives_15m=derivatives_15m,
        initial_capital=initial_capital,
        base_cost_bps=base_cost_bps,
    )
    annual = annual_summary(item, initial_capital=initial_capital)
    recent = recent_segment_summary(item, initial_capital=initial_capital)
    regime = regime_summary(item, frames=frames, initial_capital=initial_capital)
    score = _score(item.metrics, cost_stress=cost_stress, annual=annual, recent=recent, regime=regime)
    decision = _retention_decision(item.metrics, cost_stress=cost_stress, annual=annual, recent=recent)
    return {
        "candidate_id": item.spec.candidate_id,
        "variant_id": item.spec.variant_id,
        "label": item.spec.label,
        "optimization_stage": item.spec.optimization_stage,
        "optimization_components": item.spec.optimization_components,
        "params_hash": hashlib.sha1(json.dumps(item.spec.params, sort_keys=True).encode("utf-8")).hexdigest()[:12],
        "params": item.spec.params,
        "leverage": item.spec.params["leverage"],
        "take_profit_pct": item.spec.params["take_profit_pct"],
        "stop_loss_pct": item.spec.params["stop_loss_pct"],
        "level_set": item.spec.params["level_set"],
        "total_return_pct": item.metrics["total_return_pct"],
        "annual_return_pct": item.metrics["annual_return_pct"],
        "max_drawdown_abs_pct": item.metrics["max_drawdown_abs_pct"],
        "profit_factor": item.metrics["profit_factor"],
        "calmar_ratio": item.metrics["calmar_ratio"],
        "sharpe_ratio": item.metrics["sharpe_ratio"],
        "average_exposure": item.metrics["average_exposure"],
        "campaign_entry_count": item.metrics["campaign_entry_count"],
        "exposure_change_count": item.metrics["exposure_change_count"],
        "turnover": item.metrics["turnover"],
        "long_bar_count": item.metrics["long_bar_count"],
        "short_bar_count": item.metrics["short_bar_count"],
        "liquidation_proxy_breach_count": item.metrics["liquidation_proxy_breach_count"],
        "cost_2x_survives": cost_stress["cost_2x_survives"],
        "cost_5x_survives": cost_stress["cost_5x_survives"],
        "cost_survival_rate": cost_stress["survival_rate"],
        "best_positive_year_share": annual["best_positive_year_share"],
        "latest_180d_total_return_pct": recent["metrics"]["total_return_pct"],
        "latest_180d_passed": recent["passed"],
        "regime_pass_rate": regime["pass_rate"],
        "sideways_exposure_bar_count": regime["sideways_exposure_bar_count"],
        "score": score,
        "retention_decision": decision,
        "cost_stress": cost_stress,
        "annual_summary": annual,
        "recent_segment": recent,
        "regime_summary": regime,
        "research_only": True,
        "paper_queue_write_allowed": False,
        "paper_candidate_created": False,
        "live_unlock_allowed": False,
    }


def cost_stress_summary(
    item: EvaluatedMaLadderV2,
    *,
    frames: Mapping[str, pd.DataFrame],
    derivatives_15m: pd.DataFrame,
    initial_capital: float,
    base_cost_bps: float,
) -> dict[str, Any]:
    close = frames[BASE_INTERVAL]["close"].astype(float)
    bar_returns = close.pct_change().fillna(0.0)
    effective_exposure = item.exposure.shift(1).fillna(0.0)
    funding_rate = pd.to_numeric(derivatives_15m.get("funding_rate", pd.Series(0.0, index=close.index)), errors="coerce").reindex(close.index).fillna(0.0)
    scenarios = []
    for multiplier in [1.0, 2.0, 5.0]:
        cost = item.turnover * (float(base_cost_bps) * multiplier / 10_000.0)
        funding = -effective_exposure * funding_rate * (BASE_INTERVAL_HOURS / FUNDING_INTERVAL_HOURS)
        returns = (effective_exposure * bar_returns + funding - cost).fillna(0.0).clip(lower=-0.95)
        equity = float(initial_capital) * (1.0 + returns).cumprod()
        metrics = performance_metrics(
            strategy_returns=returns,
            equity=equity,
            exposure=item.exposure,
            turnover=item.turnover,
            cost=cost,
            funding_pnl=funding,
            initial_capital=initial_capital,
        )
        survives = float(metrics["total_return_pct"]) > 0.0 and float(metrics["profit_factor"]) >= 1.0
        scenarios.append({"cost_multiplier": multiplier, "survives": survives, "metrics": metrics})
    survival_count = sum(1 for row in scenarios if row["survives"])
    return {
        "scenario_count": len(scenarios),
        "survival_count": survival_count,
        "survival_rate": _round(survival_count / len(scenarios) if scenarios else 0.0),
        "base_survives": bool(scenarios[0]["survives"]) if scenarios else False,
        "cost_2x_survives": bool(scenarios[1]["survives"]) if len(scenarios) > 1 else False,
        "cost_5x_survives": bool(scenarios[2]["survives"]) if len(scenarios) > 2 else False,
        "scenarios": scenarios,
    }


def annual_summary(item: EvaluatedMaLadderV2, *, initial_capital: float) -> dict[str, Any]:
    rows = []
    for year, index in item.returns.groupby(item.returns.index.year).groups.items():
        idx = pd.DatetimeIndex(index)
        if len(idx) < 100:
            continue
        metrics = _slice_metrics(item, idx, initial_capital=initial_capital)
        rows.append({"year": int(year), "row_count": int(len(idx)), "passed": _segment_passed(metrics), "metrics": metrics})
    positive = [max(0.0, float(row["metrics"]["total_return_pct"])) for row in rows]
    best_share = max(positive) / sum(positive) if sum(positive) > 0.0 else 0.0
    pass_rate = sum(1 for row in rows if row["passed"]) / len(rows) if rows else 0.0
    return {"segment_type": "calendar_year", "segment_count": len(rows), "pass_rate": _round(pass_rate), "best_positive_year_share": _round(best_share), "segments": rows}


def recent_segment_summary(item: EvaluatedMaLadderV2, *, initial_capital: float, days: int = 180) -> dict[str, Any]:
    if item.returns.empty:
        return {"segment": f"latest_{days}d", "row_count": 0, "passed": False, "metrics": _empty_metrics(initial_capital)}
    start = item.returns.index.max() - pd.Timedelta(days=days)
    idx = item.returns.index[item.returns.index >= start]
    metrics = _slice_metrics(item, pd.DatetimeIndex(idx), initial_capital=initial_capital)
    return {"segment": f"latest_{days}d", "row_count": int(len(idx)), "passed": _segment_passed(metrics), "metrics": metrics}


def regime_summary(item: EvaluatedMaLadderV2, *, frames: Mapping[str, pd.DataFrame], initial_capital: float) -> dict[str, Any]:
    labels = _regime_labels(frames)
    rows = []
    for label in ["bull_trend", "bear_trend", "sideways_or_transition"]:
        idx = item.returns.index[labels.reindex(item.returns.index).fillna("sideways_or_transition") == label]
        if len(idx) < 100:
            continue
        metrics = _slice_metrics(item, pd.DatetimeIndex(idx), initial_capital=initial_capital)
        rows.append({"segment": label, "row_count": int(len(idx)), "passed": _segment_passed(metrics), "metrics": metrics})
    sideways_idx = item.exposure.index[labels.reindex(item.exposure.index).fillna("sideways_or_transition") == "sideways_or_transition"]
    sideways_exposure = int((item.exposure.loc[sideways_idx].abs() > 0.0).sum()) if len(sideways_idx) else 0
    pass_rate = sum(1 for row in rows if row["passed"]) / len(rows) if rows else 0.0
    return {
        "segment_type": "market_regime",
        "segment_count": len(rows),
        "pass_rate": _round(pass_rate),
        "sideways_exposure_bar_count": sideways_exposure,
        "segments": rows,
    }


def _slice_metrics(item: EvaluatedMaLadderV2, idx: pd.DatetimeIndex, *, initial_capital: float) -> dict[str, Any]:
    returns = item.returns.reindex(idx).fillna(0.0)
    if returns.empty:
        return _empty_metrics(initial_capital)
    equity = float(initial_capital) * (1.0 + returns).cumprod()
    return performance_metrics(
        strategy_returns=returns,
        equity=equity,
        exposure=item.exposure.reindex(idx).fillna(0.0),
        turnover=item.turnover.reindex(idx).fillna(0.0),
        cost=item.cost.reindex(idx).fillna(0.0),
        funding_pnl=item.funding_pnl.reindex(idx).fillna(0.0),
        initial_capital=initial_capital,
    )


def _segment_passed(metrics: Mapping[str, Any]) -> bool:
    return float(metrics.get("total_return_pct", 0.0)) > 0.0 and float(metrics.get("profit_factor", 0.0)) >= 1.0


def _score(
    metrics: Mapping[str, Any],
    *,
    cost_stress: Mapping[str, Any],
    annual: Mapping[str, Any],
    recent: Mapping[str, Any],
    regime: Mapping[str, Any],
) -> float:
    score = 0.0
    score += float(metrics.get("annual_return_pct", 0.0)) * 0.5
    score += float(metrics.get("total_return_pct", 0.0)) * 0.10
    score += min(float(metrics.get("profit_factor", 0.0)), 4.0) * 9.0
    score += float(metrics.get("calmar_ratio", 0.0)) * 7.0
    score += float(cost_stress.get("survival_rate", 0.0)) * 16.0
    score += float(annual.get("pass_rate", 0.0)) * 8.0
    score += 6.0 if bool(recent.get("passed", False)) else -7.0
    score += float(regime.get("pass_rate", 0.0)) * 8.0
    score -= max(0.0, float(metrics.get("max_drawdown_abs_pct", 0.0)) - 50.0) * 1.1
    score -= float(metrics.get("liquidation_proxy_breach_count", 0)) * 5.0
    score -= max(0.0, float(annual.get("best_positive_year_share", 0.0)) - 0.85) * 30.0
    score -= min(15.0, float(regime.get("sideways_exposure_bar_count", 0)) * 0.01)
    return _round(score)


def _retention_decision(
    metrics: Mapping[str, Any],
    *,
    cost_stress: Mapping[str, Any],
    annual: Mapping[str, Any],
    recent: Mapping[str, Any],
) -> str:
    if float(metrics.get("annual_return_pct", 0.0)) < 60.0:
        return "defer_annual_return_below_high_yield_line"
    if float(metrics.get("profit_factor", 0.0)) < 1.10:
        return "defer_profit_factor_below_1p10"
    if float(metrics.get("max_drawdown_abs_pct", 0.0)) > 70.0:
        return "reject_drawdown_above_attack_limit"
    if int(metrics.get("liquidation_proxy_breach_count", 0)) > 0:
        return "defer_liquidation_proxy_breach_review"
    if not bool(cost_stress.get("cost_2x_survives", False)):
        return "defer_cost_2x_not_survive"
    if float(annual.get("best_positive_year_share", 0.0)) > 0.90:
        return "defer_year_concentration_review"
    if not bool(recent.get("passed", False)):
        return "defer_recent_segment_failed"
    return "retain_ma_ladder_v2_research_watchlist_only"


def _rank_key(row: Mapping[str, Any]) -> tuple[Any, ...]:
    retained = str(row.get("retention_decision")) == "retain_ma_ladder_v2_research_watchlist_only"
    return (
        0 if retained else 1,
        -float(row.get("score", 0.0)),
        -float(row.get("annual_return_pct", 0.0)),
        -float(row.get("total_return_pct", 0.0)),
        float(row.get("max_drawdown_abs_pct", 0.0)),
        str(row.get("candidate_id")),
    )


def _regime_labels(frames: Mapping[str, pd.DataFrame]) -> pd.Series:
    index = frames[BASE_INTERVAL].index
    daily_close = frames["1d"]["close"].astype(float)
    fast = _ema(daily_close, span=50).reindex(index, method="ffill")
    slow = _ema(daily_close, span=200).reindex(index, method="ffill")
    close = daily_close.reindex(index, method="ffill")
    efficiency = _trend_efficiency(frames["1h"]["close"].astype(float), window=96).reindex(index, method="ffill").fillna(0.0)
    labels = pd.Series("sideways_or_transition", index=index)
    labels[(fast > slow) & (close > slow) & (efficiency >= 0.18)] = "bull_trend"
    labels[(fast < slow) & (close < slow) & (efficiency >= 0.18)] = "bear_trend"
    return labels


def _campaign_diagnostics(*, exposure: pd.Series, entry_fill: pd.Series, close: pd.Series, high: pd.Series, low: pd.Series) -> dict[str, Any]:
    prev_close = close.shift(1).replace(0.0, math.nan)
    active = exposure.shift(1).fillna(0.0)
    lev = active.abs().replace(0.0, math.nan)
    long_adverse = ((prev_close - low) / prev_close).where(active > 0.0)
    short_adverse = ((high - prev_close) / prev_close).where(active < 0.0)
    adverse = pd.concat([long_adverse, short_adverse], axis=1).max(axis=1)
    threshold = 0.80 / lev
    breaches = ((adverse >= threshold) & threshold.notna()).fillna(False)
    return {
        "campaign_entry_count": int((entry_fill > 0.0).sum()),
        "liquidation_proxy_breach_count": int(breaches.sum()),
        "max_intrabar_adverse_pct": _round(float(adverse.max()) * 100.0 if adverse.notna().any() else 0.0),
        "liquidation_proxy_model": "diagnostic_only_not_applied_to_equity",
    }


def _trend_efficiency(close: pd.Series, *, window: int) -> pd.Series:
    net = (close / close.shift(window) - 1.0).abs()
    path = close.pct_change().abs().rolling(window).sum()
    return (net / path.replace(0.0, math.nan)).fillna(0.0)


def _ema(series: pd.Series, *, span: int) -> pd.Series:
    return series.ewm(span=int(span), adjust=False).mean()


def _weight_from_level_column(column: str) -> float:
    marker = "_w"
    if marker not in column:
        return 1.0
    return float(column.rsplit(marker, 1)[1].replace("p", "."))


def _exit_note(*, stop_hit: bool, target_hit: bool, trend_exit: bool) -> str:
    reasons = []
    if stop_hit:
        reasons.append("stop_loss")
    if target_hit:
        reasons.append("take_profit")
    if trend_exit:
        reasons.append("trend_failure")
    return ",".join(reasons) if reasons else "unknown_exit"


def _event_row(
    *,
    spec: MaLadderV2Spec,
    timestamp: pd.Timestamp,
    event_type: str,
    side: float,
    exposure_before: float,
    exposure_after: float,
    fill_price: float,
    note: str,
) -> dict[str, Any]:
    return {
        "timestamp": _ts(timestamp),
        "candidate_id": spec.candidate_id,
        "variant_id": spec.variant_id,
        "event_type": event_type,
        "side": _round(side),
        "exposure_before": _round(exposure_before),
        "exposure_after": _round(exposure_after),
        "fill_price": _round(fill_price),
        "note": note,
    }


def _summary(rows: Sequence[Mapping[str, Any]], *, watchlist: Sequence[Mapping[str, Any]], blockers: Sequence[str]) -> dict[str, Any]:
    best = rows[0] if rows else {}
    return {
        "candidate_count": len(rows),
        "watchlist_count": len(watchlist),
        "best_candidate_id": best.get("candidate_id"),
        "best_variant_id": best.get("variant_id"),
        "best_retention_decision": best.get("retention_decision"),
        "best_annual_return_pct": best.get("annual_return_pct", 0.0),
        "best_total_return_pct": best.get("total_return_pct", 0.0),
        "best_max_drawdown_abs_pct": best.get("max_drawdown_abs_pct", 0.0),
        "best_profit_factor": best.get("profit_factor", 0.0),
        "best_average_exposure": best.get("average_exposure", 0.0),
        "best_campaign_entry_count": best.get("campaign_entry_count", 0),
        "best_turnover": best.get("turnover", 0.0),
        "best_liquidation_proxy_breach_count": best.get("liquidation_proxy_breach_count", 0),
        "blocked": bool(blockers),
    }


def render_btc_multi_timeframe_ma_ladder_v2_lab_markdown(report: Mapping[str, Any]) -> str:
    summary = _mapping(report.get("summary"))
    top_rows = report.get("comparison_rows", [])[:10]
    lines = [
        "# BTC 多周期均线挂价 v2 实验室",
        "",
        f"- 状态：`{report.get('status')}`",
        f"- 结论边界：`{report.get('decision')}`",
        f"- 候选数：`{summary.get('candidate_count', 0)}`",
        f"- watchlist 数：`{summary.get('watchlist_count', 0)}`",
        f"- 当前最佳：`{summary.get('best_variant_id')}`",
        f"- 最佳年化：`{summary.get('best_annual_return_pct')}%`",
        f"- 最佳总收益：`{summary.get('best_total_return_pct')}%`",
        f"- 最佳最大回撤：`{summary.get('best_max_drawdown_abs_pct')}%`",
        f"- 最佳战役入场次数：`{summary.get('best_campaign_entry_count')}`",
        "",
        "## 策略原理",
        "",
        "v2 更接近人工短线做法：只在强趋势里等均线回撤挂价；进场后不反复换仓；到明确利润目标止盈，打到固定止损退出，或者趋势连续失败后退出。震荡和趋势效率不足时不主动开仓。",
        "",
        "## 和 v1 的区别",
        "",
        "- v1 容易频繁换仓，成本拖累很重；v2 是一次趋势战役。",
        "- v1 从 1m 全量重采样很慢；v2 直接用已有 15m/1h，4H/1D 从 1H 派生。",
        "- v1 没有足够像人工“到目标就走”；v2 固定止盈、固定止损、趋势失败退出。",
        "",
        "## 边界",
        "",
        "- 只输出 research-only 报告，不写 paper，不解锁 live，不接 broker/OMS/order。",
        "- limit fill 和 funding/强平仍是研究近似，不是实盘证据。",
        "",
        "## Top 10",
        "",
        "| 排名 | variant | 年化% | 总收益% | 回撤% | PF | 入场数 | 换手 | 决策 |",
        "|---:|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for idx, row in enumerate(top_rows, 1):
        lines.append(
            f"| {idx} | `{row.get('variant_id')}` | {row.get('annual_return_pct')} | {row.get('total_return_pct')} | "
            f"{row.get('max_drawdown_abs_pct')} | {row.get('profit_factor')} | {row.get('campaign_entry_count')} | "
            f"{row.get('turnover')} | `{row.get('retention_decision')}` |"
        )
    return "\n".join(lines) + "\n"


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


def _gate() -> dict[str, Any]:
    return {
        "paper_queue_write_allowed": False,
        "paper_candidate_created": False,
        "paper_allowed": False,
        "live_unlock_allowed": False,
        "live_order_allowed": False,
        "oms_access_allowed": False,
        "broker_access_allowed": False,
        "strategy_skeleton_generated": False,
        "reason": "MA ladder v2 is research-only and uses synthetic limit-fill/funding/liquidation diagnostics; it needs event-ledger and forward observation before promotion.",
    }


def _warnings(rows: Sequence[Mapping[str, Any]], *, blockers: Sequence[str]) -> list[str]:
    warnings = ["btc_multi_timeframe_ma_ladder_v2_research_only_no_paper_no_live"]
    if blockers:
        warnings.append("btc_multi_timeframe_ma_ladder_v2_has_data_history_blockers")
    if any(int(row.get("liquidation_proxy_breach_count", 0)) > 0 for row in rows):
        warnings.append("some_ma_ladder_v2_candidates_have_liquidation_proxy_breaches")
    if any(str(row.get("retention_decision")) == "retain_ma_ladder_v2_research_watchlist_only" for row in rows):
        warnings.append("ma_ladder_v2_watchlist_is_research_only_and_requires_forward_observation")
    return warnings


def _safety_status(report: Mapping[str, Any]) -> dict[str, Any]:
    gate = _mapping(report.get("gate"))
    return {
        "status": "research_only",
        "decision": report.get("decision"),
        "paper_queue_write_allowed": bool(gate.get("paper_queue_write_allowed", False)),
        "paper_candidate_created": bool(gate.get("paper_candidate_created", False)),
        "paper_allowed": bool(gate.get("paper_allowed", False)),
        "live_unlock_allowed": bool(gate.get("live_unlock_allowed", False)),
        "live_order_allowed": bool(gate.get("live_order_allowed", False)),
        "oms_access_allowed": bool(gate.get("oms_access_allowed", False)),
        "broker_access_allowed": bool(gate.get("broker_access_allowed", False)),
        "real_order_submitted": False,
        "blockers": list(report.get("blockers", [])),
    }


def _empty_metrics(initial_capital: float) -> dict[str, Any]:
    return {
        "total_return_pct": 0.0,
        "annual_return_pct": 0.0,
        "annual_volatility_pct": 0.0,
        "downside_volatility_pct": 0.0,
        "sharpe_ratio": 0.0,
        "sortino_ratio": 0.0,
        "calmar_ratio": 0.0,
        "profit_factor": 0.0,
        "max_drawdown_pct": 0.0,
        "max_drawdown_abs_pct": 0.0,
        "final_equity": initial_capital,
        "average_exposure": 0.0,
        "average_net_exposure": 0.0,
        "bars_with_exposure": 0,
        "long_bar_count": 0,
        "short_bar_count": 0,
        "turnover": 0.0,
        "exposure_change_count": 0,
        "fee_return_pct": 0.0,
        "funding_return_pct": 0.0,
        "winning_exposed_bar_pct": 0.0,
    }


def _grid_fieldnames() -> list[str]:
    return [
        "candidate_id",
        "variant_id",
        "label",
        "optimization_stage",
        "optimization_components",
        "params_hash",
        "leverage",
        "take_profit_pct",
        "stop_loss_pct",
        "level_set",
        "total_return_pct",
        "annual_return_pct",
        "max_drawdown_abs_pct",
        "profit_factor",
        "calmar_ratio",
        "sharpe_ratio",
        "average_exposure",
        "campaign_entry_count",
        "exposure_change_count",
        "turnover",
        "long_bar_count",
        "short_bar_count",
        "liquidation_proxy_breach_count",
        "cost_2x_survives",
        "cost_5x_survives",
        "cost_survival_rate",
        "best_positive_year_share",
        "latest_180d_total_return_pct",
        "latest_180d_passed",
        "regime_pass_rate",
        "sideways_exposure_bar_count",
        "score",
        "retention_decision",
        "research_only",
        "paper_queue_write_allowed",
        "paper_candidate_created",
        "live_unlock_allowed",
    ]


def _event_fieldnames() -> list[str]:
    return ["timestamp", "candidate_id", "variant_id", "event_type", "side", "exposure_before", "exposure_after", "fill_price", "note"]


def _write_csv(path: Path, fieldnames: Sequence[str], rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fieldnames), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _round(value: Any, digits: int = 6) -> float:
    try:
        number = float(value)
    except Exception:
        return 0.0
    if not math.isfinite(number):
        return 0.0
    return round(number, digits)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _portable_path(path: Path) -> str:
    return str(path).replace("\\", "/")


def _ts(value: Any) -> str:
    return pd.Timestamp(value).isoformat()


def _num_slug(value: float) -> str:
    text = f"{float(value):g}"
    return text.replace(".", "p").replace("-", "m")


def _git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return "unknown"
