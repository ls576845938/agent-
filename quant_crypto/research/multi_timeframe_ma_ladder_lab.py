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
    align_derivatives_to_index,
)


SCHEMA_VERSION = "btc_multi_timeframe_ma_ladder_lab_v1"
DEFAULT_OUTPUT_DIR = Path("artifacts/btc_multi_timeframe_ma_ladder_lab/latest")
DEFAULT_REPORT_PATH = DEFAULT_OUTPUT_DIR / "btc_multi_timeframe_ma_ladder_lab_report.json"
DEFAULT_GRID_PATH = DEFAULT_OUTPUT_DIR / "btc_multi_timeframe_ma_ladder_lab_grid.csv"
DEFAULT_EVENTS_PATH = DEFAULT_OUTPUT_DIR / "btc_multi_timeframe_ma_ladder_lab_events.csv"
DEFAULT_MARKDOWN_PATH = DEFAULT_OUTPUT_DIR / "btc_multi_timeframe_ma_ladder_lab_summary_cn.md"
DEFAULT_SAFETY_PATH = DEFAULT_OUTPUT_DIR / "paper_live_safety_status.json"

SOURCE_INTERVAL = "1m"
BASE_INTERVAL = "15m"
BASE_BARS_PER_YEAR = 365.0 * 24.0 * 4.0
MIN_15M_BARS = 20_000
FUNDING_INTERVAL_HOURS = 8.0
BASE_INTERVAL_HOURS = 0.25
MAX_RESEARCH_LEVERAGE = 5.0
DEFAULT_RUN_PROFILE = "smoke"
RUN_PROFILES = {"smoke", "formal"}
RUN_PROFILE_SPEC_LIMITS = {"smoke": 20, "formal": None}

DAILY_TRENDS = ((20, 80), (34, 144), (50, 200))
HOURLY_TRENDS = ((12, 48), (24, 96))
FOUR_HOUR_TRENDS = ((12, 48), (18, 72))
TREND_EFFICIENCY_THRESHOLDS = (0.12, 0.18, 0.24)
MAX_LEVERAGE_GRID = (1.0, 2.0, 3.0, 5.0)
TAKE_PROFIT_GRID = (0.08, 0.12, 0.16, None)
STOP_LOSS_GRID = (0.03,)
LEVEL_SETS: dict[str, tuple[tuple[str, int, float], ...]] = {
    "fast_5_15_30": (("5m", 20, 0.40), ("15m", 20, 0.35), ("30m", 20, 0.25)),
    "mid_5_15_30": (("5m", 20, 0.30), ("15m", 50, 0.35), ("30m", 50, 0.35)),
}


@dataclass(frozen=True)
class MaLadderSpec:
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
        return f"btc_mtf_ma_ladder_{self.variant_id}_{digest}"


@dataclass
class EvaluatedMaLadder:
    spec: MaLadderSpec
    raw_side: pd.Series
    exposure: pd.Series
    returns: pd.Series
    turnover: pd.Series
    cost: pd.Series
    funding_pnl: pd.Series
    equity: pd.Series
    fill_fraction: pd.Series
    metrics: dict[str, Any]
    events: tuple[dict[str, Any], ...]


def build_btc_multi_timeframe_ma_ladder_lab(
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

    source_1m = load_market_interval(market_db_path, SOURCE_INTERVAL)
    frames = _build_timeframes(source_1m)
    base = frames[BASE_INTERVAL]
    derivatives_15m = align_derivatives_to_index(derivatives_rows_path, base.index)

    blockers: list[str] = []
    if len(base) < MIN_15M_BARS:
        blockers.append("btc_multi_timeframe_ma_ladder_lab_insufficient_15m_bars")
    if len(frames["1d"]) < 220:
        blockers.append("btc_multi_timeframe_ma_ladder_lab_short_daily_history_for_50_200")
    if len(frames["1mo"]) < 8:
        blockers.append("btc_multi_timeframe_ma_ladder_lab_monthly_risk_switch_insufficient_history")

    all_specs = ma_ladder_specs()
    profile_limit = RUN_PROFILE_SPEC_LIMITS[run_profile]
    effective_limit = int(max_specs) if max_specs is not None else profile_limit
    specs = all_specs[: int(effective_limit)] if effective_limit is not None else all_specs

    evaluated = [
        evaluate_ma_ladder(
            spec,
            frames=frames,
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
    watchlist = [dict(row) for row in ranked if row["retention_decision"] == "retain_ma_ladder_research_watchlist_only"][:20]
    event_rows = [event for item in evaluated[:5] for event in item.events]

    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated.astimezone(timezone.utc).isoformat(),
        "status": "blocked" if blockers else "complete_research_only",
        "decision": "btc_multi_timeframe_ma_ladder_lab_research_only_no_paper_no_live",
        "scope": "btc_multi_timeframe_ma_pullback_limit_ladder_research",
        "code_commit": _git_commit(),
        "input": {
            "market_db_path": _portable_path(market_db_path),
            "derivatives_rows_path": _portable_path(derivatives_rows_path),
            "symbol": SYMBOL,
            "exchange": EXCHANGE,
            "source_interval": SOURCE_INTERVAL,
            "base_execution_interval": BASE_INTERVAL,
            "source_1m_rows": int(len(source_1m)),
            "base_15m_rows": int(len(base)),
            "bar_start": _ts(base.index.min()) if len(base) else None,
            "bar_end": _ts(base.index.max()) if len(base) else None,
            "derived_timeframes_from_complete_1m": {key: int(len(value)) for key, value in frames.items()},
            "derivatives_visible_rows": int(derivatives_15m["funding_rate"].notna().sum()) if "funding_rate" in derivatives_15m else 0,
            "derivatives_available_time_rule": "derivatives rows are aligned by available_time <= 15m decision_time",
        },
        "research_design": {
            "economic_hypothesis": "强趋势里，回撤到多周期均线附近是更容易被市场理解和承接的挂价区域；震荡区间应减少或停止交易。",
            "run_profile": run_profile,
            "candidate_count": len(specs),
            "formal_candidate_count": len(all_specs),
            "trial_count": len(specs),
            "selected_by": "ranked by annual return, total return, PF, drawdown, cost stress, trend-regime behavior and liquidation diagnostics",
            "direction_rule": "1D decides long/short permission, 4H and 1H confirm trend, 1W changes size, 1M is a coarse risk switch when enough history exists",
            "ladder_rule": "after a completed 15m decision bar, next completed 15m high/low confirms whether resting MA ladder prices were touched",
            "execution_rule": "filled ladder exposure only earns returns from the following 15m close-to-close bar; same-bar fill-to-close alpha is not credited",
            "level_sets": LEVEL_SETS,
            "daily_trends": [list(item) for item in DAILY_TRENDS],
            "hourly_trends": [list(item) for item in HOURLY_TRENDS],
            "four_hour_trends": [list(item) for item in FOUR_HOUR_TRENDS],
            "trend_efficiency_thresholds": list(TREND_EFFICIENCY_THRESHOLDS),
            "max_leverage_grid": list(MAX_LEVERAGE_GRID),
            "take_profit_grid": [value if value is not None else "none" for value in TAKE_PROFIT_GRID],
            "stop_loss_grid": list(STOP_LOSS_GRID),
            "max_research_leverage": MAX_RESEARCH_LEVERAGE,
            "cost_model": {"base_cost_bps": float(base_cost_bps), "stress_multipliers": [1, 2, 5]},
            "funding_model": {
                "enabled": True,
                "formula": "funding_pnl = -exposure * funding_rate * (15m / 8h)",
                "research_approximation": True,
            },
            "no_lookahead_policy": [
                "all timeframes are aggregated from complete 1m bars",
                "trend and ladder levels are read at the completed decision bar",
                "order fill is checked on the next completed 15m bar",
                "exposure is effective only after the fill bar close",
                "derivatives require available_time <= decision_time",
            ],
        },
        "guardrails": _guardrails(),
        "gate": _gate(),
        "summary": _summary(ranked, watchlist=watchlist, blockers=blockers),
        "comparison_rows": ranked,
        "ma_ladder_research_watchlist": watchlist,
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
    _write_text(markdown_path, render_btc_multi_timeframe_ma_ladder_lab_markdown(report))
    _write_json(safety_path, _safety_status(report))
    return report


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


def _build_timeframes(source_1m: pd.DataFrame) -> dict[str, pd.DataFrame]:
    bars_5m = aggregate_ohlcv_minutes(source_1m, minutes=5)
    bars_15m = aggregate_ohlcv_minutes(source_1m, minutes=15)
    bars_30m = aggregate_ohlcv_minutes(source_1m, minutes=30)
    bars_1h = aggregate_ohlcv_minutes(source_1m, minutes=60)
    bars_4h = aggregate_ohlcv_minutes(source_1m, minutes=240)
    bars_1d = aggregate_ohlcv_minutes(source_1m, minutes=1440)
    bars_1w = aggregate_ohlcv_calendar(bars_1h, timeframe="1w")
    bars_1mo = aggregate_ohlcv_calendar(bars_1h, timeframe="1mo")
    return {
        "1m": source_1m,
        "5m": bars_5m,
        "15m": bars_15m,
        "30m": bars_30m,
        "1h": bars_1h,
        "4h": bars_4h,
        "1d": bars_1d,
        "1w": bars_1w,
        "1mo": bars_1mo,
    }


def aggregate_ohlcv_minutes(frame_1m: pd.DataFrame, *, minutes: int) -> pd.DataFrame:
    if minutes == 1:
        return frame_1m.copy()
    source = frame_1m.copy().sort_values("open_time")
    source = source.set_index("open_time")
    grouper = source.resample(f"{minutes}min", label="left", closed="left")
    counts = grouper["close"].count()
    aggregated = grouper.agg(
        {
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        }
    )
    aggregated["close_time"] = pd.to_datetime(
        aggregated.index + pd.Timedelta(minutes=minutes) - pd.Timedelta(milliseconds=1),
        utc=True,
    )
    aggregated = aggregated[counts == minutes].dropna(subset=["open", "high", "low", "close", "close_time"])
    aggregated["open_time"] = aggregated.index
    aggregated = aggregated.set_index("close_time")
    return aggregated[["open_time", "open", "high", "low", "close", "volume"]].sort_index()


def ma_ladder_specs() -> list[MaLadderSpec]:
    specs = [
        MaLadderSpec(
            variant_id="original_d50_200_h24_96_f18_72_lev1_fast",
            label="原始版：日线50/200 + 1H/4H确认 + 5/15/30均线挂价",
            params=_params(
                daily=(50, 200),
                hourly=(24, 96),
                four_hour=(18, 72),
                trend_efficiency=0.12,
                max_leverage=1.0,
                take_profit=None,
                level_set="fast_5_15_30",
            ),
            optimization_stage="original",
            optimization_components=[],
            notes=["closest to simple MA pullback-ladder idea with low leverage"],
        )
    ]
    for daily_fast, daily_slow in DAILY_TRENDS:
        for hourly_fast, hourly_slow in HOURLY_TRENDS:
            for four_fast, four_slow in FOUR_HOUR_TRENDS:
                for trend_eff in TREND_EFFICIENCY_THRESHOLDS:
                    for max_leverage in MAX_LEVERAGE_GRID:
                        for take_profit in TAKE_PROFIT_GRID:
                            for level_set_id in LEVEL_SETS:
                                variant = (
                                    f"formal_d{daily_fast}_{daily_slow}_h{hourly_fast}_{hourly_slow}"
                                    f"_f{four_fast}_{four_slow}_te{_num_slug(trend_eff)}"
                                    f"_lev{_num_slug(max_leverage)}_tp{_tp_slug(take_profit)}_{level_set_id}"
                                )
                                components = [
                                    "daily_trend_permission",
                                    "hourly_four_hour_trend_confirm",
                                    "ma_ladder_limit_pullback",
                                    "trend_efficiency_filter",
                                    "weekly_size_monthly_risk",
                                ]
                                if max_leverage > 1.0:
                                    components.append("research_leverage")
                                if take_profit is not None:
                                    components.append("fixed_price_move_take_profit")
                                specs.append(
                                    MaLadderSpec(
                                        variant_id=variant,
                                        label="Formal narrow MA pullback ladder long/short research",
                                        params=_params(
                                            daily=(daily_fast, daily_slow),
                                            hourly=(hourly_fast, hourly_slow),
                                            four_hour=(four_fast, four_slow),
                                            trend_efficiency=trend_eff,
                                            max_leverage=max_leverage,
                                            take_profit=take_profit,
                                            level_set=level_set_id,
                                        ),
                                        optimization_stage="formal_narrow_ma_ladder_grid",
                                        optimization_components=components,
                                        notes=[
                                            "predeclared narrow grid around simple MA pullback ladder",
                                            "derivatives are funding/cost diagnostics only",
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
    max_leverage: float,
    take_profit: float | None,
    level_set: str,
) -> dict[str, Any]:
    return {
        "daily_fast": daily[0],
        "daily_slow": daily[1],
        "hourly_fast": hourly[0],
        "hourly_slow": hourly[1],
        "four_hour_fast": four_hour[0],
        "four_hour_slow": four_hour[1],
        "monthly_fast": 3,
        "monthly_slow": 8,
        "weekly_fast": 8,
        "weekly_slow": 21,
        "trend_efficiency_window": 96,
        "trend_efficiency_threshold": trend_efficiency,
        "max_leverage": max_leverage,
        "level_set": level_set,
        "max_pullback_pct": 0.035,
        "take_profit_pct": take_profit,
        "stop_loss_pct": STOP_LOSS_GRID[0],
        "cooldown_bars_after_stop": 8,
        "allow_additive_ladder": True,
        "primary_signal_source": "multi_timeframe_price_trend",
        "derivatives_usage": "funding_cost_diagnostic_only",
    }


def evaluate_ma_ladder(
    spec: MaLadderSpec,
    *,
    frames: Mapping[str, pd.DataFrame],
    derivatives_15m: pd.DataFrame,
    initial_capital: float,
    cost_bps: float,
    collect_events: bool = False,
) -> EvaluatedMaLadder:
    base = frames[BASE_INTERVAL]
    close = base["close"].astype(float)
    high = base["high"].astype(float)
    low = base["low"].astype(float)
    raw_side, weekly_size, levels = _ma_ladder_decision_frame(spec, frames=frames)
    raw_side = raw_side.reindex(close.index).fillna(0.0).clip(-1.0, 1.0)
    weekly_size = weekly_size.reindex(close.index).fillna(0.0).clip(0.0, 1.0)
    levels = levels.reindex(close.index).ffill()

    exposure, fill_fraction, event_rows = _simulate_ladder_exposure(
        spec,
        close=close,
        high=high,
        low=low,
        raw_side=raw_side,
        weekly_size=weekly_size,
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
    metrics.update(_ladder_diagnostics(exposure=exposure, fill_fraction=fill_fraction, close=close, high=high, low=low))
    return EvaluatedMaLadder(
        spec=spec,
        raw_side=raw_side,
        exposure=exposure,
        returns=strategy_returns,
        turnover=turnover,
        cost=cost,
        funding_pnl=funding_pnl,
        equity=equity,
        fill_fraction=fill_fraction,
        metrics=metrics,
        events=tuple(event_rows),
    )


def _ma_ladder_decision_frame(
    spec: MaLadderSpec,
    *,
    frames: Mapping[str, pd.DataFrame],
) -> tuple[pd.Series, pd.Series, pd.DataFrame]:
    params = spec.params
    base = frames[BASE_INTERVAL]
    index = base.index
    close = base["close"].astype(float)

    daily_side = _timeframe_side(frames["1d"], index, fast=int(params["daily_fast"]), slow=int(params["daily_slow"]))
    hourly_side = _timeframe_side(frames["1h"], index, fast=int(params["hourly_fast"]), slow=int(params["hourly_slow"]))
    four_hour_side = _timeframe_side(frames["4h"], index, fast=int(params["four_hour_fast"]), slow=int(params["four_hour_slow"]))
    monthly_side = _timeframe_side(frames["1mo"], index, fast=int(params["monthly_fast"]), slow=int(params["monthly_slow"]))
    weekly_side = _timeframe_side(frames["1w"], index, fast=int(params["weekly_fast"]), slow=int(params["weekly_slow"]))
    efficiency = _trend_efficiency(close, window=int(params["trend_efficiency_window"]))
    efficiency_ok = efficiency >= float(params["trend_efficiency_threshold"])

    side = pd.Series(0.0, index=index)
    long_ok = (daily_side > 0.0) & (hourly_side > 0.0) & (four_hour_side > 0.0) & (monthly_side >= 0.0) & efficiency_ok
    short_ok = (daily_side < 0.0) & (hourly_side < 0.0) & (four_hour_side < 0.0) & (monthly_side <= 0.0) & efficiency_ok
    side[long_ok] = 1.0
    side[short_ok] = -1.0

    weekly_size = pd.Series(0.5, index=index)
    weekly_size[(side > 0.0) & (weekly_side > 0.0)] = 1.0
    weekly_size[(side < 0.0) & (weekly_side < 0.0)] = 1.0
    weekly_size[(side != 0.0) & (weekly_side == 0.0)] = 0.5
    weekly_size[(side > 0.0) & (weekly_side < 0.0)] = 0.25
    weekly_size[(side < 0.0) & (weekly_side > 0.0)] = 0.25
    weekly_size[side == 0.0] = 0.0

    level_columns: dict[str, pd.Series] = {}
    for pos, (timeframe, span, weight) in enumerate(LEVEL_SETS[str(params["level_set"])]):
        series = _ema(frames[timeframe]["close"].astype(float), span=int(span)).reindex(index, method="ffill")
        level_columns[f"level_{pos}_{timeframe}_ema{span}_w{_num_slug(weight)}"] = series
    levels = pd.DataFrame(level_columns, index=index)
    return side, weekly_size, levels


def _simulate_ladder_exposure(
    spec: MaLadderSpec,
    *,
    close: pd.Series,
    high: pd.Series,
    low: pd.Series,
    raw_side: pd.Series,
    weekly_size: pd.Series,
    levels: pd.DataFrame,
    collect_events: bool,
) -> tuple[pd.Series, pd.Series, list[dict[str, Any]]]:
    params = spec.params
    max_leverage = float(params["max_leverage"])
    max_pullback_pct = float(params["max_pullback_pct"])
    stop_loss_pct = float(params["stop_loss_pct"])
    take_profit_pct = params.get("take_profit_pct")
    cooldown_after_stop = int(params["cooldown_bars_after_stop"])
    allow_additive = bool(params.get("allow_additive_ladder", True))

    exposure_values = [0.0 for _ in close.index]
    fill_values = [0.0 for _ in close.index]
    event_rows: list[dict[str, Any]] = []
    current_exposure = 0.0
    current_side = 0.0
    entry_price = math.nan
    cooldown = 0

    for i in range(1, len(close)):
        decision_i = i - 1
        decision_time = close.index[decision_i]
        fill_time = close.index[i]
        decision_close = float(close.iloc[decision_i])
        side = float(raw_side.iloc[decision_i])
        if cooldown > 0:
            side = 0.0
            cooldown -= 1

        if current_side != 0.0:
            pnl_since_entry = current_side * (decision_close / entry_price - 1.0) if math.isfinite(entry_price) and entry_price > 0.0 else 0.0
            stop_hit = pnl_since_entry <= -stop_loss_pct
            target_hit = bool(take_profit_pct is not None and pnl_since_entry >= float(take_profit_pct))
            trend_exit = side == 0.0 or side != current_side
            if stop_hit or target_hit or trend_exit:
                if collect_events:
                    event_rows.append(
                        _event_row(
                            spec=spec,
                            timestamp=fill_time,
                            event_type="exit",
                            side=current_side,
                            exposure_before=current_exposure,
                            exposure_after=0.0,
                            fill_fraction=0.0,
                            note=_exit_note(stop_hit=stop_hit, target_hit=target_hit, trend_exit=trend_exit),
                        )
                    )
                if stop_hit:
                    cooldown = cooldown_after_stop
                current_exposure = 0.0
                current_side = 0.0
                entry_price = math.nan

        filled_fraction = 0.0
        if side != 0.0 and (current_side == 0.0 or (allow_additive and current_side == side and abs(current_exposure) < max_leverage)):
            valid_weights = []
            filled_weights = []
            for column in levels.columns:
                level = float(levels[column].iloc[decision_i])
                if not math.isfinite(level) or level <= 0.0:
                    continue
                weight = _weight_from_level_column(column)
                if side > 0.0:
                    distance = (decision_close - level) / decision_close
                    valid = 0.0 < distance <= max_pullback_pct
                    filled = valid and float(low.iloc[i]) <= level
                else:
                    distance = (level - decision_close) / decision_close
                    valid = 0.0 < distance <= max_pullback_pct
                    filled = valid and float(high.iloc[i]) >= level
                if valid:
                    valid_weights.append(weight)
                if filled:
                    filled_weights.append(weight)
            denominator = sum(valid_weights) if valid_weights else 0.0
            filled_fraction = min(1.0, sum(filled_weights) / denominator) if denominator > 0.0 else 0.0
            if filled_fraction > 0.0:
                target = side * max_leverage * float(weekly_size.iloc[decision_i]) * filled_fraction
                if current_side == side:
                    if abs(target) > abs(current_exposure):
                        current_exposure = target
                else:
                    current_exposure = target
                    current_side = side
                    entry_price = decision_close
                if collect_events:
                    event_rows.append(
                        _event_row(
                            spec=spec,
                            timestamp=fill_time,
                            event_type="ma_ladder_fill",
                            side=side,
                            exposure_before=exposure_values[i - 1],
                            exposure_after=current_exposure,
                            fill_fraction=filled_fraction,
                            note=f"decision_time={_ts(decision_time)}",
                        )
                    )
        exposure_values[i] = current_exposure
        fill_values[i] = filled_fraction

    return pd.Series(exposure_values, index=close.index), pd.Series(fill_values, index=close.index), event_rows


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
    item: EvaluatedMaLadder,
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
        "max_leverage": item.spec.params["max_leverage"],
        "level_set": item.spec.params["level_set"],
        "total_return_pct": item.metrics["total_return_pct"],
        "annual_return_pct": item.metrics["annual_return_pct"],
        "max_drawdown_abs_pct": item.metrics["max_drawdown_abs_pct"],
        "profit_factor": item.metrics["profit_factor"],
        "calmar_ratio": item.metrics["calmar_ratio"],
        "sharpe_ratio": item.metrics["sharpe_ratio"],
        "average_exposure": item.metrics["average_exposure"],
        "average_fill_fraction": item.metrics["average_fill_fraction"],
        "fill_bar_count": item.metrics["fill_bar_count"],
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
    item: EvaluatedMaLadder,
    *,
    frames: Mapping[str, pd.DataFrame],
    derivatives_15m: pd.DataFrame,
    initial_capital: float,
    base_cost_bps: float,
) -> dict[str, Any]:
    close = frames[BASE_INTERVAL]["close"].astype(float)
    bar_returns = close.pct_change().fillna(0.0)
    funding_rate = pd.to_numeric(derivatives_15m.get("funding_rate", pd.Series(0.0, index=close.index)), errors="coerce").reindex(close.index).fillna(0.0)
    effective_exposure = item.exposure.shift(1).fillna(0.0)
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


def annual_summary(item: EvaluatedMaLadder, *, initial_capital: float) -> dict[str, Any]:
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
    return {
        "segment_type": "calendar_year",
        "segment_count": len(rows),
        "pass_rate": _round(pass_rate),
        "best_positive_year_share": _round(best_share),
        "segments": rows,
    }


def recent_segment_summary(item: EvaluatedMaLadder, *, initial_capital: float, days: int = 180) -> dict[str, Any]:
    if item.returns.empty:
        return {"segment": f"latest_{days}d", "row_count": 0, "passed": False, "metrics": _empty_metrics(initial_capital)}
    start = item.returns.index.max() - pd.Timedelta(days=days)
    idx = item.returns.index[item.returns.index >= start]
    metrics = _slice_metrics(item, pd.DatetimeIndex(idx), initial_capital=initial_capital)
    return {"segment": f"latest_{days}d", "row_count": int(len(idx)), "passed": _segment_passed(metrics), "metrics": metrics}


def regime_summary(item: EvaluatedMaLadder, *, frames: Mapping[str, pd.DataFrame], initial_capital: float) -> dict[str, Any]:
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


def _slice_metrics(item: EvaluatedMaLadder, idx: pd.DatetimeIndex, *, initial_capital: float) -> dict[str, Any]:
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
    score += float(metrics.get("annual_return_pct", 0.0)) * 0.45
    score += float(metrics.get("total_return_pct", 0.0)) * 0.08
    score += min(float(metrics.get("profit_factor", 0.0)), 4.0) * 8.0
    score += float(metrics.get("calmar_ratio", 0.0)) * 6.0
    score += float(cost_stress.get("survival_rate", 0.0)) * 18.0
    score += float(annual.get("pass_rate", 0.0)) * 10.0
    score += 5.0 if bool(recent.get("passed", False)) else -8.0
    score += float(regime.get("pass_rate", 0.0)) * 8.0
    score -= max(0.0, float(metrics.get("max_drawdown_abs_pct", 0.0)) - 50.0) * 1.2
    score -= float(metrics.get("liquidation_proxy_breach_count", 0)) * 4.0
    score -= max(0.0, float(annual.get("best_positive_year_share", 0.0)) - 0.75) * 40.0
    score -= min(20.0, float(regime.get("sideways_exposure_bar_count", 0)) * 0.02)
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
    if float(annual.get("best_positive_year_share", 0.0)) > 0.85:
        return "defer_year_concentration_review"
    if not bool(recent.get("passed", False)):
        return "defer_recent_segment_failed"
    return "retain_ma_ladder_research_watchlist_only"


def _rank_key(row: Mapping[str, Any]) -> tuple[Any, ...]:
    retained = str(row.get("retention_decision")) == "retain_ma_ladder_research_watchlist_only"
    return (
        0 if retained else 1,
        -float(row.get("score", 0.0)),
        -float(row.get("annual_return_pct", 0.0)),
        -float(row.get("total_return_pct", 0.0)),
        float(row.get("max_drawdown_abs_pct", 0.0)),
        str(row.get("candidate_id")),
    )


def _timeframe_side(frame: pd.DataFrame, index: pd.DatetimeIndex, *, fast: int, slow: int) -> pd.Series:
    if frame.empty:
        return pd.Series(0.0, index=index)
    close = frame["close"].astype(float)
    fast_ema = _ema(close, span=fast)
    slow_ema = _ema(close, span=slow)
    side = pd.Series(0.0, index=close.index)
    side[(fast_ema > slow_ema) & (close > slow_ema)] = 1.0
    side[(fast_ema < slow_ema) & (close < slow_ema)] = -1.0
    return side.reindex(index, method="ffill").fillna(0.0)


def _trend_efficiency(close: pd.Series, *, window: int) -> pd.Series:
    net = (close / close.shift(window) - 1.0).abs()
    path = close.pct_change().abs().rolling(window).sum()
    return (net / path.replace(0.0, math.nan)).fillna(0.0)


def _regime_labels(frames: Mapping[str, pd.DataFrame]) -> pd.Series:
    base = frames[BASE_INTERVAL]
    index = base.index
    daily = _timeframe_side(frames["1d"], index, fast=50, slow=200)
    efficiency = _trend_efficiency(base["close"].astype(float), window=96)
    labels = pd.Series("sideways_or_transition", index=index)
    labels[(daily > 0.0) & (efficiency >= 0.12)] = "bull_trend"
    labels[(daily < 0.0) & (efficiency >= 0.12)] = "bear_trend"
    return labels


def _ema(series: pd.Series, *, span: int) -> pd.Series:
    return series.ewm(span=int(span), adjust=False).mean()


def _ladder_diagnostics(*, exposure: pd.Series, fill_fraction: pd.Series, close: pd.Series, high: pd.Series, low: pd.Series) -> dict[str, Any]:
    prev_close = close.shift(1).replace(0.0, math.nan)
    active = exposure.shift(1).fillna(0.0)
    lev = active.abs().replace(0.0, math.nan)
    long_adverse = ((prev_close - low) / prev_close).where(active > 0.0)
    short_adverse = ((high - prev_close) / prev_close).where(active < 0.0)
    adverse = pd.concat([long_adverse, short_adverse], axis=1).max(axis=1)
    threshold = 0.80 / lev
    breaches = ((adverse >= threshold) & threshold.notna()).fillna(False)
    return {
        "average_fill_fraction": _round(float(fill_fraction[fill_fraction > 0.0].mean()) if (fill_fraction > 0.0).any() else 0.0),
        "fill_bar_count": int((fill_fraction > 0.0).sum()),
        "liquidation_proxy_breach_count": int(breaches.sum()),
        "max_intrabar_adverse_pct": _round(float(adverse.max()) * 100.0 if adverse.notna().any() else 0.0),
        "liquidation_proxy_model": "diagnostic_only_not_applied_to_equity",
    }


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
        reasons.append("trend_exit")
    return ",".join(reasons) if reasons else "unknown_exit"


def _event_row(
    *,
    spec: MaLadderSpec,
    timestamp: pd.Timestamp,
    event_type: str,
    side: float,
    exposure_before: float,
    exposure_after: float,
    fill_fraction: float,
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
        "fill_fraction": _round(fill_fraction),
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
        "best_liquidation_proxy_breach_count": best.get("liquidation_proxy_breach_count", 0),
        "blocked": bool(blockers),
    }


def render_btc_multi_timeframe_ma_ladder_lab_markdown(report: Mapping[str, Any]) -> str:
    summary = _mapping(report.get("summary"))
    top_rows = report.get("comparison_rows", [])[:10]
    lines = [
        "# BTC 多周期均线挂价实验室 v1",
        "",
        f"- 状态：`{report.get('status')}`",
        f"- 结论边界：`{report.get('decision')}`",
        f"- 候选数：`{summary.get('candidate_count', 0)}`",
        f"- watchlist 数：`{summary.get('watchlist_count', 0)}`",
        f"- 当前最佳：`{summary.get('best_variant_id')}`",
        f"- 最佳年化：`{summary.get('best_annual_return_pct')}%`",
        f"- 最佳总收益：`{summary.get('best_total_return_pct')}%`",
        f"- 最佳最大回撤：`{summary.get('best_max_drawdown_abs_pct')}%`",
        "",
        "## 策略原理",
        "",
        "日线决定能不能做多/做空，4H 和 1H 确认趋势，周线只调仓位大小，月线只做粗风险开关。方向确认后，不追突破，而是在 5m/15m/30m EMA 附近挂价等回撤；震荡或趋势效率不足时空仓。",
        "",
        "## 关键边界",
        "",
        "- 只用已完成 1m 聚合出的 5m/15m/30m/1H/4H/1D/1W/1M。",
        "- 15m 收盘后生成挂价，下一根 15m K 线确认是否触及挂价。",
        "- 成交后的收益从再下一段 close-to-close 开始算，不吃同根 K 线的事后利润。",
        "- funding、强平和滑点仍是研究近似，不是 paper/live 证据。",
        "- 不写 paper 队列，不解锁 live，不接 broker/OMS/order。",
        "",
        "## Top 10",
        "",
        "| 排名 | variant | 年化% | 总收益% | 回撤% | PF | 均暴露 | 决策 |",
        "|---:|---|---:|---:|---:|---:|---:|---|",
    ]
    for idx, row in enumerate(top_rows, 1):
        lines.append(
            f"| {idx} | `{row.get('variant_id')}` | {row.get('annual_return_pct')} | {row.get('total_return_pct')} | "
            f"{row.get('max_drawdown_abs_pct')} | {row.get('profit_factor')} | {row.get('average_exposure')} | `{row.get('retention_decision')}` |"
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
        "reason": "MA ladder lab is research-only and uses synthetic limit-fill and liquidation diagnostics; it needs event-ledger, depth-aware fill and forward observation before promotion.",
    }


def _warnings(rows: Sequence[Mapping[str, Any]], *, blockers: Sequence[str]) -> list[str]:
    warnings = ["btc_multi_timeframe_ma_ladder_research_only_no_paper_no_live"]
    if blockers:
        warnings.append("btc_multi_timeframe_ma_ladder_has_data_history_blockers")
    if any(int(row.get("liquidation_proxy_breach_count", 0)) > 0 for row in rows):
        warnings.append("some_ma_ladder_candidates_have_liquidation_proxy_breaches")
    if any(str(row.get("retention_decision")) == "retain_ma_ladder_research_watchlist_only" for row in rows):
        warnings.append("ma_ladder_watchlist_is_research_only_and_requires_forward_observation")
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
        "max_leverage",
        "level_set",
        "total_return_pct",
        "annual_return_pct",
        "max_drawdown_abs_pct",
        "profit_factor",
        "calmar_ratio",
        "sharpe_ratio",
        "average_exposure",
        "average_fill_fraction",
        "fill_bar_count",
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
    return ["timestamp", "candidate_id", "variant_id", "event_type", "side", "exposure_before", "exposure_after", "fill_fraction", "note"]


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


def _tp_slug(value: float | None) -> str:
    return "none" if value is None else _num_slug(value)


def _git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return "unknown"
