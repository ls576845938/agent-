from __future__ import annotations

import csv
import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd

from quant_crypto.research.simple_trend_rule_lab import (
    DEFAULT_DERIVATIVES_ROWS,
    DEFAULT_MARKET_DB,
    EXCHANGE,
    SYMBOL,
    aggregate_ohlcv,
    align_derivatives_to_index,
    load_market_1h,
)


SCHEMA_VERSION = "btc_multi_timeframe_rule_lab_v1"
SOURCE_INTERVAL = "1h"
BASE_INTERVAL = "4h"
DEFAULT_OUTPUT_DIR = Path("artifacts/btc_multi_timeframe_rule_lab/latest")
DEFAULT_REPORT_PATH = DEFAULT_OUTPUT_DIR / "btc_multi_timeframe_rule_lab_report.json"
DEFAULT_GRID_PATH = DEFAULT_OUTPUT_DIR / "btc_multi_timeframe_rule_lab_grid.csv"
DEFAULT_MARKDOWN_PATH = DEFAULT_OUTPUT_DIR / "btc_multi_timeframe_rule_lab_summary_cn.md"

INITIAL_CAPITAL = 25_000.0
BASE_COST_BPS = 10.0
MIN_4H_BARS = 900
MIN_1D_BARS = 180
BARS_PER_YEAR = {"4h": 6 * 365}
DERIVED_TIMEFRAMES = ["4h", "1d", "1w", "1mo"]


@dataclass(frozen=True)
class MultiTimeframeRuleSpec:
    family_id: str
    variant_id: str
    label: str
    params: dict[str, Any]
    direction_policy: str
    optimized: bool
    optimization_stage: str
    optimization_components: list[str]
    optimization_notes: list[str]

    @property
    def branch(self) -> str:
        return "short_research" if self.family_id == "short_research_branch" else "long_flat_research"

    @property
    def candidate_id(self) -> str:
        raw = {
            "family_id": self.family_id,
            "variant_id": self.variant_id,
            "params": self.params,
            "direction_policy": self.direction_policy,
            "optimization_stage": self.optimization_stage,
            "optimization_components": self.optimization_components,
        }
        digest = hashlib.sha1(json.dumps(raw, sort_keys=True).encode("utf-8")).hexdigest()[:10]
        return f"btc_mtf_{self.variant_id}_{digest}"


@dataclass
class EvaluatedMtfRule:
    spec: MultiTimeframeRuleSpec
    raw_signal: pd.Series
    exposure: pd.Series
    returns: pd.Series
    turnover: pd.Series
    cost: pd.Series
    equity: pd.Series
    metrics: dict[str, Any]


def build_btc_multi_timeframe_rule_lab(
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
    grid_path = output_dir / DEFAULT_GRID_PATH.name
    markdown_path = output_dir / DEFAULT_MARKDOWN_PATH.name

    source_1h = load_market_1h(market_db_path)
    bars_4h = aggregate_ohlcv(source_1h, interval_hours=4)
    bars_1d = aggregate_ohlcv(source_1h, interval_hours=24)
    bars_1w = aggregate_ohlcv_calendar(source_1h, timeframe="1w")
    bars_1mo = aggregate_ohlcv_calendar(source_1h, timeframe="1mo")
    derivatives_4h = align_derivatives_to_index(derivatives_rows_path, bars_4h.index)

    specs = multi_timeframe_rule_specs()
    blockers: list[str] = []
    if len(bars_4h) < MIN_4H_BARS:
        blockers.append("btc_multi_timeframe_rule_lab_insufficient_4h_bars")
    if len(bars_1d) < MIN_1D_BARS:
        blockers.append("btc_multi_timeframe_rule_lab_insufficient_1d_bars")

    buy_hold = _evaluate_buy_hold(bars_4h, initial_capital=initial_capital, cost_bps=base_cost_bps)
    evaluated = [
        evaluate_mtf_rule(
            spec,
            bars_1h=source_1h,
            bars_4h=bars_4h,
            bars_1d=bars_1d,
            bars_1w=bars_1w,
            bars_1mo=bars_1mo,
            derivatives_4h=derivatives_4h,
            initial_capital=initial_capital,
            cost_bps=base_cost_bps,
        )
        for spec in specs
    ]
    rows = [
        _grid_row(
            item,
            buy_hold_metrics=buy_hold.metrics,
            walk_forward=walk_forward_summary(item, initial_capital=initial_capital),
            annual_regime=annual_regime_summary(item, initial_capital=initial_capital),
            market_regime=market_regime_summary(item, bars_4h=bars_4h, initial_capital=initial_capital),
            cost_stress=cost_stress_summary(
                item.spec,
                bars_1h=source_1h,
                bars_4h=bars_4h,
                bars_1d=bars_1d,
                bars_1w=bars_1w,
                bars_1mo=bars_1mo,
                derivatives_4h=derivatives_4h,
                initial_capital=initial_capital,
                base_cost_bps=base_cost_bps,
            ),
        )
        for item in evaluated
    ]
    ranked = sorted(rows, key=lambda row: (-float(row["score"]), str(row["candidate_id"])))
    long_flat_rows = [row for row in ranked if row["branch"] == "long_flat_research" and row["direction_policy"] == "long_flat"]
    short_rows = [row for row in ranked if row["branch"] == "short_research"]
    long_flat_shortlist = _extended_research_shortlist(long_flat_rows)
    short_watchlist = _short_research_watchlist(short_rows)
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated.isoformat(),
        "status": "blocked" if blockers else "complete_research_only",
        "decision": "btc_multi_timeframe_rule_lab_research_only_no_paper_no_live",
        "scope": "btc_multi_timeframe_simple_rule_research_lab",
        "code_commit": _git_commit(),
        "input": {
            "market_db_path": _portable_path(market_db_path),
            "derivatives_rows_path": _portable_path(derivatives_rows_path),
            "symbol": SYMBOL,
            "exchange": EXCHANGE,
            "source_interval": SOURCE_INTERVAL,
            "base_decision_interval": BASE_INTERVAL,
            "market_1h_rows": int(len(source_1h)),
            "bar_4h_rows": int(len(bars_4h)),
            "bar_1d_rows": int(len(bars_1d)),
            "bar_1w_rows": int(len(bars_1w)),
            "bar_1mo_rows": int(len(bars_1mo)),
            "bar_4h_start": _ts(bars_4h.index.min()) if len(bars_4h) else None,
            "bar_4h_end": _ts(bars_4h.index.max()) if len(bars_4h) else None,
            "bar_1d_start": _ts(bars_1d.index.min()) if len(bars_1d) else None,
            "bar_1d_end": _ts(bars_1d.index.max()) if len(bars_1d) else None,
            "bar_1w_start": _ts(bars_1w.index.min()) if len(bars_1w) else None,
            "bar_1w_end": _ts(bars_1w.index.max()) if len(bars_1w) else None,
            "bar_1mo_start": _ts(bars_1mo.index.min()) if len(bars_1mo) else None,
            "bar_1mo_end": _ts(bars_1mo.index.max()) if len(bars_1mo) else None,
            "derived_timeframes_from_1h": DERIVED_TIMEFRAMES,
            "market_completed_bar_rule": "1h completed bars are the only market source; 4h/1d/1w/1mo are aggregated from complete 1h chunks",
            "derivatives_available_time_rule": "derivatives features aligned by available_time <= 4h decision_time",
            "derivatives_visible_rows": int(derivatives_4h["open_interest_usd"].notna().sum())
            if "open_interest_usd" in derivatives_4h
            else 0,
        },
        "validation_design": {
            "candidate_family_count": 8,
            "candidate_count": len(specs),
            "variant_policy": "each family has original, single-component optimizations, and pre-declared combination optimizations",
            "execution_rule": "signals are computed at 4h decision closes; exposure is shifted to the next 4h bar",
            "one_hour_exit_policy": "1h features may update a 4h decision signal only after the 4h decision close, then exposure starts next 4h bar",
            "cost_model": {
                "base_cost_bps": float(base_cost_bps),
                "stress_cost_bps": _cost_stress_bps(base_cost_bps),
            },
            "short_policy": "short and long_short variants are research-only and can only enter short_research_watchlist",
            "no_lookahead_policy": [
                "all price features use completed 1h bars",
                "4h/1d/1w/1mo bars are derived from complete 1h chunks; incomplete current week/month groups are dropped",
                "derivatives features require available_time <= decision_time",
                "exposure uses raw_signal.shift(1) at the 4h decision grid",
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
            "reason": "multi-timeframe rule lab is research-only; no candidate may be promoted without separate manual review",
        },
        "buy_hold_baseline": _round_mapping(buy_hold.metrics),
        "higher_timeframe_context": higher_timeframe_context_summary(
            bars_4h=bars_4h,
            bars_1d=bars_1d,
            bars_1w=bars_1w,
            bars_1mo=bars_1mo,
        ),
        "families": _family_context(),
        "family_stepwise_comparison": _family_stepwise_comparison(rows),
        "comparison_rows": ranked,
        "long_flat_research_rows": long_flat_rows,
        "short_research_rows": short_rows,
        "extended_research_shortlist": long_flat_shortlist,
        "short_research_watchlist": short_watchlist,
        "blockers": blockers,
        "warnings": _warnings(rows),
        "outputs": {
            "json": _portable_path(report_path),
            "grid_csv": _portable_path(grid_path),
            "summary_cn": _portable_path(markdown_path),
        },
    }
    _write_csv(grid_path, _grid_fieldnames(), ranked)
    _write_json(report_path, report)
    _write_text(markdown_path, render_multi_timeframe_rule_lab_markdown(report))
    return report


def aggregate_ohlcv_calendar(frame_1h: pd.DataFrame, *, timeframe: str) -> pd.DataFrame:
    if timeframe not in {"1w", "1mo"}:
        raise ValueError(f"unsupported calendar timeframe: {timeframe}")
    if frame_1h.empty:
        return pd.DataFrame(columns=["open_time", "open", "high", "low", "close", "volume"])

    source = frame_1h.sort_values("open_time").copy()
    regular_utc = isinstance(source["open_time"].dtype, pd.DatetimeTZDtype) and str(source["open_time"].dt.tz) == "UTC"
    if timeframe == "1w":
        if regular_utc:
            source["_period_start"] = (source["open_time"] - pd.to_timedelta(source["open_time"].dt.weekday, unit="D")).dt.normalize()
        else:
            source["_period_start"] = source["open_time"].map(lambda value: (value - pd.Timedelta(days=value.weekday())).normalize())
    else:
        # Keep the scalar route outside UTC: calendar/DST arithmetic must not
        # acquire different semantics merely to speed the UTC offline replay.
        if regular_utc:
            source["_period_start"] = (source["open_time"] - pd.to_timedelta(source["open_time"].dt.day - 1, unit="D")).dt.normalize()
        else:
            source["_period_start"] = source["open_time"].map(lambda value: pd.Timestamp(year=value.year, month=value.month, day=1, tz=value.tz))

    rows: list[dict[str, Any]] = []
    for start, chunk in source.groupby("_period_start", sort=True):
        period_start = pd.Timestamp(start)
        next_start = period_start + (pd.Timedelta(days=7) if timeframe == "1w" else pd.DateOffset(months=1))
        expected_hours = int((next_start - period_start).total_seconds() // 3600)
        chunk = chunk.sort_values("open_time")
        if len(chunk) != expected_hours:
            continue
        if chunk["open_time"].iloc[0] != period_start:
            continue
        if chunk["open_time"].iloc[-1] != next_start - pd.Timedelta(hours=1):
            continue
        rows.append(
            {
                "open_time": period_start,
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


def multi_timeframe_rule_specs() -> list[MultiTimeframeRuleSpec]:
    def spec(
        family_id: str,
        variant_id: str,
        label: str,
        params: dict[str, Any],
        *,
        stage: str,
        components: list[str],
        notes: list[str],
        direction_policy: str = "long_flat",
    ) -> MultiTimeframeRuleSpec:
        return MultiTimeframeRuleSpec(
            family_id=family_id,
            variant_id=variant_id,
            label=label,
            params=params,
            direction_policy=direction_policy,
            optimized=stage != "original",
            optimization_stage=stage,
            optimization_components=components,
            optimization_notes=notes,
        )

    return [
        spec(
            "multi_tf_trend_confirm",
            "mtf_trend_original",
            "1D EMA trend plus 4H EMA trend confirmation",
            {"signal_type": "multi_tf_trend_confirm", "daily_fast": 50, "daily_slow": 200, "ema_fast": 21, "ema_mid": 50, "ema_slow": 100, "exit_1h_ema": 24, "use_1h_exit": False, "use_atr_trail": False},
            stage="original",
            components=[],
            notes=["daily EMA50/200 defines direction; 4h trend confirms entry"],
        ),
        spec(
            "multi_tf_trend_confirm",
            "mtf_trend_1h_exit",
            "1D/4H trend with 1H EMA exit",
            {"signal_type": "multi_tf_trend_confirm", "daily_fast": 50, "daily_slow": 200, "ema_fast": 21, "ema_mid": 50, "ema_slow": 100, "exit_1h_ema": 24, "use_1h_exit": True, "use_atr_trail": False},
            stage="single_1h_exit",
            components=["one_hour_exit_denoise"],
            notes=["single optimization: use 1h EMA break as next-4h exit input"],
        ),
        spec(
            "multi_tf_trend_confirm",
            "mtf_trend_atr_trail",
            "1D/4H trend with ATR trailing stop",
            {"signal_type": "multi_tf_trend_confirm", "daily_fast": 50, "daily_slow": 200, "ema_fast": 21, "ema_mid": 50, "ema_slow": 100, "exit_1h_ema": 24, "use_1h_exit": False, "use_atr_trail": True, "atr_window": 20, "atr_mult": 3.0},
            stage="single_atr_trailing_exit",
            components=["atr_trailing_exit"],
            notes=["single optimization: 4h ATR trailing exit"],
        ),
        spec(
            "multi_tf_trend_confirm",
            "mtf_trend_1h_atr_combo",
            "1D/4H trend with 1H exit and ATR trailing stop",
            {"signal_type": "multi_tf_trend_confirm", "daily_fast": 50, "daily_slow": 200, "ema_fast": 21, "ema_mid": 50, "ema_slow": 100, "exit_1h_ema": 24, "use_1h_exit": True, "use_atr_trail": True, "atr_window": 20, "atr_mult": 3.0},
            stage="combo_1h_exit_plus_atr_trail",
            components=["one_hour_exit_denoise", "atr_trailing_exit"],
            notes=["combination: 1h exit and ATR trail"],
        ),
        spec(
            "multi_tf_trend_confirm",
            "mtf_trend_weekly_monthly_confirm",
            "1D/1W/1M trend with 4H EMA trend confirmation",
            {"signal_type": "multi_tf_trend_confirm", "daily_fast": 50, "daily_slow": 200, "weekly_fast": 10, "weekly_slow": 30, "monthly_fast": 3, "monthly_slow": 10, "use_weekly_confirm": True, "use_monthly_confirm": True, "ema_fast": 21, "ema_mid": 50, "ema_slow": 100, "exit_1h_ema": 24, "use_1h_exit": False, "use_atr_trail": False},
            stage="single_higher_timeframe_confirm",
            components=["weekly_trend_confirmation", "monthly_trend_confirmation"],
            notes=["single optimization: require weekly and monthly trend context in addition to daily trend"],
        ),
        spec(
            "multi_tf_trend_confirm",
            "mtf_trend_tiered_htf_control",
            "1D permission, 1W position sizing, 1M risk switch trend confirmation",
            {"signal_type": "multi_tf_trend_confirm", "daily_fast": 50, "daily_slow": 200, "weekly_fast": 10, "weekly_slow": 30, "monthly_fast": 3, "monthly_slow": 10, "use_tiered_higher_timeframe_control": True, "use_weekly_position_scaling": True, "use_monthly_risk_switch": True, "weekly_bull_scale": 1.0, "weekly_neutral_scale": 0.5, "weekly_bear_scale": 0.25, "monthly_bear_scale": 0.0, "ema_fast": 21, "ema_mid": 50, "ema_slow": 100, "exit_1h_ema": 24, "use_1h_exit": False, "use_atr_trail": False},
            stage="combo_tiered_higher_timeframe_control",
            components=["daily_trade_permission", "weekly_position_sizing", "monthly_risk_switch"],
            notes=["combination: daily permits trading, weekly controls exposure size, monthly bear state cuts risk"],
        ),
        spec(
            "multi_tf_trend_confirm",
            "mtf_trend_tiered_weekly_60_20",
            "Tiered trend with 1W sizing 1.0/0.6/0.2 and 1M risk switch",
            {"signal_type": "multi_tf_trend_confirm", "daily_fast": 50, "daily_slow": 200, "weekly_fast": 10, "weekly_slow": 30, "monthly_fast": 3, "monthly_slow": 10, "use_tiered_higher_timeframe_control": True, "use_weekly_position_scaling": True, "use_monthly_risk_switch": True, "weekly_bull_scale": 1.0, "weekly_neutral_scale": 0.6, "weekly_bear_scale": 0.2, "monthly_bear_scale": 0.0, "ema_fast": 21, "ema_mid": 50, "ema_slow": 100, "exit_1h_ema": 24, "use_1h_exit": False, "use_atr_trail": False},
            stage="single_tiered_weekly_scale_60_20",
            components=["weekly_position_sizing"],
            notes=["single narrow search: weekly neutral scale 0.6 and weekly bear scale 0.2"],
        ),
        spec(
            "multi_tf_trend_confirm",
            "mtf_trend_tiered_weekly_strict_cash",
            "Tiered trend with 1W sizing 1.0/0.5/0.0 and 1M risk switch",
            {"signal_type": "multi_tf_trend_confirm", "daily_fast": 50, "daily_slow": 200, "weekly_fast": 10, "weekly_slow": 30, "monthly_fast": 3, "monthly_slow": 10, "use_tiered_higher_timeframe_control": True, "use_weekly_position_scaling": True, "use_monthly_risk_switch": True, "weekly_bull_scale": 1.0, "weekly_neutral_scale": 0.5, "weekly_bear_scale": 0.0, "monthly_bear_scale": 0.0, "ema_fast": 21, "ema_mid": 50, "ema_slow": 100, "exit_1h_ema": 24, "use_1h_exit": False, "use_atr_trail": False},
            stage="single_tiered_weekly_bear_cash",
            components=["weekly_position_sizing"],
            notes=["single narrow search: weekly bear state is cash instead of 0.25 exposure"],
        ),
        spec(
            "multi_tf_trend_confirm",
            "mtf_trend_tiered_weekly_loose",
            "Tiered trend with 1W sizing 1.0/0.75/0.5 and 1M risk switch",
            {"signal_type": "multi_tf_trend_confirm", "daily_fast": 50, "daily_slow": 200, "weekly_fast": 10, "weekly_slow": 30, "monthly_fast": 3, "monthly_slow": 10, "use_tiered_higher_timeframe_control": True, "use_weekly_position_scaling": True, "use_monthly_risk_switch": True, "weekly_bull_scale": 1.0, "weekly_neutral_scale": 0.75, "weekly_bear_scale": 0.5, "monthly_bear_scale": 0.0, "ema_fast": 21, "ema_mid": 50, "ema_slow": 100, "exit_1h_ema": 24, "use_1h_exit": False, "use_atr_trail": False},
            stage="single_tiered_weekly_loose_scale",
            components=["weekly_position_sizing"],
            notes=["single narrow search: keep more exposure when weekly context is neutral or bearish"],
        ),
        spec(
            "multi_tf_trend_confirm",
            "mtf_trend_tiered_monthly_fast_switch",
            "Tiered trend with faster 1M risk switch",
            {"signal_type": "multi_tf_trend_confirm", "daily_fast": 50, "daily_slow": 200, "weekly_fast": 10, "weekly_slow": 30, "monthly_fast": 2, "monthly_slow": 6, "use_tiered_higher_timeframe_control": True, "use_weekly_position_scaling": True, "use_monthly_risk_switch": True, "weekly_bull_scale": 1.0, "weekly_neutral_scale": 0.5, "weekly_bear_scale": 0.25, "monthly_bear_scale": 0.0, "ema_fast": 21, "ema_mid": 50, "ema_slow": 100, "exit_1h_ema": 24, "use_1h_exit": False, "use_atr_trail": False},
            stage="single_tiered_fast_monthly_switch",
            components=["monthly_risk_switch"],
            notes=["single narrow search: monthly risk switch uses EMA2/6 instead of EMA3/10"],
        ),
        spec(
            "multi_tf_trend_confirm",
            "mtf_trend_tiered_monthly_slow_switch",
            "Tiered trend with slower 1M risk switch",
            {"signal_type": "multi_tf_trend_confirm", "daily_fast": 50, "daily_slow": 200, "weekly_fast": 10, "weekly_slow": 30, "monthly_fast": 4, "monthly_slow": 12, "use_tiered_higher_timeframe_control": True, "use_weekly_position_scaling": True, "use_monthly_risk_switch": True, "weekly_bull_scale": 1.0, "weekly_neutral_scale": 0.5, "weekly_bear_scale": 0.25, "monthly_bear_scale": 0.0, "ema_fast": 21, "ema_mid": 50, "ema_slow": 100, "exit_1h_ema": 24, "use_1h_exit": False, "use_atr_trail": False},
            stage="single_tiered_slow_monthly_switch",
            components=["monthly_risk_switch"],
            notes=["single narrow search: monthly risk switch uses EMA4/12 instead of EMA3/10"],
        ),
        spec(
            "multi_tf_trend_confirm",
            "mtf_trend_tiered_weekly_60_fast_monthly",
            "Tiered trend with 1W sizing 1.0/0.6/0.2 and faster 1M risk switch",
            {"signal_type": "multi_tf_trend_confirm", "daily_fast": 50, "daily_slow": 200, "weekly_fast": 10, "weekly_slow": 30, "monthly_fast": 2, "monthly_slow": 6, "use_tiered_higher_timeframe_control": True, "use_weekly_position_scaling": True, "use_monthly_risk_switch": True, "weekly_bull_scale": 1.0, "weekly_neutral_scale": 0.6, "weekly_bear_scale": 0.2, "monthly_bear_scale": 0.0, "ema_fast": 21, "ema_mid": 50, "ema_slow": 100, "exit_1h_ema": 24, "use_1h_exit": False, "use_atr_trail": False},
            stage="combo_tiered_weekly_60_fast_monthly",
            components=["weekly_position_sizing", "monthly_risk_switch"],
            notes=["combination narrow search: weekly 1.0/0.6/0.2 plus monthly EMA2/6 risk switch"],
        ),
        spec(
            "multi_tf_turtle",
            "mtf_turtle_original",
            "1D trend-filtered 4H Donchian turtle",
            {"signal_type": "multi_tf_turtle", "daily_fast": 50, "daily_slow": 200, "entry_window": 120, "exit_window": 60, "use_atr_stop": False, "use_vol_filter": False, "use_derivatives_filter": False},
            stage="original",
            components=[],
            notes=["daily trend filter plus 4h Donchian entry/exit"],
        ),
        spec(
            "multi_tf_turtle",
            "mtf_turtle_slow_channel",
            "1D trend-filtered slower Donchian turtle",
            {"signal_type": "multi_tf_turtle", "daily_fast": 50, "daily_slow": 200, "entry_window": 180, "exit_window": 90, "use_atr_stop": False, "use_vol_filter": False, "use_derivatives_filter": False},
            stage="single_slow_channel",
            components=["slower_donchian_window"],
            notes=["single optimization: slower channel"],
        ),
        spec(
            "multi_tf_turtle",
            "mtf_turtle_atr_stop",
            "1D trend-filtered Donchian turtle with ATR stop",
            {"signal_type": "multi_tf_turtle", "daily_fast": 50, "daily_slow": 200, "entry_window": 120, "exit_window": 60, "use_atr_stop": True, "atr_window": 20, "atr_mult": 3.0, "use_vol_filter": False, "use_derivatives_filter": False},
            stage="single_atr_stop",
            components=["atr_trailing_exit"],
            notes=["single optimization: ATR trailing stop"],
        ),
        spec(
            "multi_tf_turtle",
            "mtf_turtle_derisk_filter",
            "1D trend-filtered Donchian turtle with volatility and funding filters",
            {"signal_type": "multi_tf_turtle", "daily_fast": 50, "daily_slow": 200, "entry_window": 120, "exit_window": 60, "use_atr_stop": False, "use_vol_filter": True, "use_derivatives_filter": True},
            stage="single_vol_funding_filter",
            components=["high_volatility_filter", "funding_crowding_filter"],
            notes=["single optimization bundle: avoid high volatility and crowded funding"],
        ),
        spec(
            "multi_tf_turtle",
            "mtf_turtle_full_combo",
            "1D trend-filtered Donchian turtle with ATR stop and crowding filters",
            {"signal_type": "multi_tf_turtle", "daily_fast": 50, "daily_slow": 200, "entry_window": 180, "exit_window": 90, "use_atr_stop": True, "atr_window": 20, "atr_mult": 3.0, "use_vol_filter": True, "use_derivatives_filter": True},
            stage="combo_slow_atr_vol_funding",
            components=["slower_donchian_window", "atr_trailing_exit", "high_volatility_filter", "funding_crowding_filter"],
            notes=["combination: slower channel plus ATR and risk filters"],
        ),
        spec(
            "multi_tf_turtle",
            "mtf_turtle_weekly_monthly_combo",
            "1D/1W/1M trend-filtered Donchian turtle with ATR and crowding filters",
            {"signal_type": "multi_tf_turtle", "daily_fast": 50, "daily_slow": 200, "weekly_fast": 10, "weekly_slow": 30, "monthly_fast": 3, "monthly_slow": 10, "use_weekly_confirm": True, "use_monthly_confirm": True, "entry_window": 180, "exit_window": 90, "use_atr_stop": True, "atr_window": 20, "atr_mult": 3.0, "use_vol_filter": True, "use_derivatives_filter": True},
            stage="combo_higher_timeframe_atr_risk",
            components=["weekly_trend_confirmation", "monthly_trend_confirmation", "slower_donchian_window", "atr_trailing_exit", "high_volatility_filter", "funding_crowding_filter"],
            notes=["combination: weekly/monthly trend filter plus turtle risk controls"],
        ),
        spec(
            "multi_tf_turtle",
            "mtf_turtle_tiered_htf_control",
            "1D permission Donchian turtle with 1W sizing and 1M risk switch",
            {"signal_type": "multi_tf_turtle", "daily_fast": 50, "daily_slow": 200, "weekly_fast": 10, "weekly_slow": 30, "monthly_fast": 3, "monthly_slow": 10, "use_tiered_higher_timeframe_control": True, "use_weekly_position_scaling": True, "use_monthly_risk_switch": True, "weekly_bull_scale": 1.0, "weekly_neutral_scale": 0.5, "weekly_bear_scale": 0.25, "monthly_bear_scale": 0.0, "entry_window": 120, "exit_window": 60, "use_atr_stop": True, "atr_window": 20, "atr_mult": 3.0, "use_vol_filter": False, "use_derivatives_filter": False},
            stage="combo_tiered_higher_timeframe_control",
            components=["daily_trade_permission", "weekly_position_sizing", "monthly_risk_switch", "atr_trailing_exit"],
            notes=["combination: preserve daily turtle permission while sizing with weekly context and cutting monthly bear risk"],
        ),
        spec(
            "trend_pullback_reentry",
            "pullback_reentry_original",
            "1D uptrend and 4H EMA50 pullback reentry",
            {"signal_type": "trend_pullback_reentry", "daily_fast": 50, "daily_slow": 200, "pullback_ema": 50, "pullback_band": 0.012, "use_1h_momentum": False, "use_atr_exit": False},
            stage="original",
            components=[],
            notes=["buy pullbacks in daily uptrend after 4h reclaim"],
        ),
        spec(
            "trend_pullback_reentry",
            "pullback_reentry_deeper",
            "1D uptrend and deeper 4H EMA100 pullback reentry",
            {"signal_type": "trend_pullback_reentry", "daily_fast": 50, "daily_slow": 200, "pullback_ema": 100, "pullback_band": 0.018, "use_1h_momentum": False, "use_atr_exit": False},
            stage="single_deeper_pullback",
            components=["deeper_pullback_anchor"],
            notes=["single optimization: wait for deeper pullback"],
        ),
        spec(
            "trend_pullback_reentry",
            "pullback_reentry_1h_momentum",
            "1D uptrend pullback with 1H momentum reclaim",
            {"signal_type": "trend_pullback_reentry", "daily_fast": 50, "daily_slow": 200, "pullback_ema": 50, "pullback_band": 0.012, "use_1h_momentum": True, "use_atr_exit": False},
            stage="single_1h_momentum_reclaim",
            components=["one_hour_momentum_reclaim"],
            notes=["single optimization: 1h momentum must turn positive"],
        ),
        spec(
            "trend_pullback_reentry",
            "pullback_reentry_atr_exit",
            "1D uptrend pullback with ATR exit",
            {"signal_type": "trend_pullback_reentry", "daily_fast": 50, "daily_slow": 200, "pullback_ema": 50, "pullback_band": 0.012, "use_1h_momentum": False, "use_atr_exit": True, "atr_window": 20, "atr_mult": 2.5},
            stage="single_atr_exit",
            components=["atr_trailing_exit"],
            notes=["single optimization: ATR exit for failed pullbacks"],
        ),
        spec(
            "trend_pullback_reentry",
            "pullback_reentry_full_combo",
            "1D uptrend deeper pullback with 1H momentum and ATR exit",
            {"signal_type": "trend_pullback_reentry", "daily_fast": 50, "daily_slow": 200, "pullback_ema": 100, "pullback_band": 0.018, "use_1h_momentum": True, "use_atr_exit": True, "atr_window": 20, "atr_mult": 2.5},
            stage="combo_deeper_1h_momentum_atr",
            components=["deeper_pullback_anchor", "one_hour_momentum_reclaim", "atr_trailing_exit"],
            notes=["combination: deeper pullback, 1h reclaim, ATR exit"],
        ),
        spec(
            "multi_tf_squeeze_breakout",
            "mtf_squeeze_original",
            "1D non-bear 4H squeeze breakout",
            {"signal_type": "multi_tf_squeeze_breakout", "daily_fast": 50, "daily_slow": 200, "bb_window": 40, "bb_k": 2.0, "kc_window": 40, "kc_k": 1.5, "breakout_window": 48, "exit_ema": 30, "use_volume_confirm": False, "use_atr_expand": False, "use_fast_fail_exit": False},
            stage="original",
            components=[],
            notes=["trade breakout only after volatility compression"],
        ),
        spec(
            "multi_tf_squeeze_breakout",
            "mtf_squeeze_volume_confirm",
            "1D non-bear 4H squeeze breakout with volume confirmation",
            {"signal_type": "multi_tf_squeeze_breakout", "daily_fast": 50, "daily_slow": 200, "bb_window": 40, "bb_k": 2.0, "kc_window": 40, "kc_k": 1.5, "breakout_window": 48, "exit_ema": 30, "use_volume_confirm": True, "volume_window": 60, "min_volume_ratio": 1.15, "use_atr_expand": False, "use_fast_fail_exit": False},
            stage="single_volume_confirm",
            components=["volume_breakout_confirmation"],
            notes=["single optimization: volume must confirm breakout"],
        ),
        spec(
            "multi_tf_squeeze_breakout",
            "mtf_squeeze_atr_expand",
            "1D non-bear 4H squeeze breakout with ATR expansion",
            {"signal_type": "multi_tf_squeeze_breakout", "daily_fast": 50, "daily_slow": 200, "bb_window": 40, "bb_k": 2.0, "kc_window": 40, "kc_k": 1.5, "breakout_window": 48, "exit_ema": 30, "use_volume_confirm": False, "use_atr_expand": True, "atr_expand_ratio": 1.05, "use_fast_fail_exit": False},
            stage="single_atr_expansion_confirm",
            components=["atr_expansion_confirmation"],
            notes=["single optimization: ATR expands on breakout"],
        ),
        spec(
            "multi_tf_squeeze_breakout",
            "mtf_squeeze_fast_fail_exit",
            "1D non-bear 4H squeeze breakout with faster failure exit",
            {"signal_type": "multi_tf_squeeze_breakout", "daily_fast": 50, "daily_slow": 200, "bb_window": 40, "bb_k": 2.0, "kc_window": 40, "kc_k": 1.5, "breakout_window": 48, "exit_ema": 18, "use_volume_confirm": False, "use_atr_expand": False, "use_fast_fail_exit": True},
            stage="single_fast_failure_exit",
            components=["fast_failure_exit"],
            notes=["single optimization: exit failed breakout faster"],
        ),
        spec(
            "multi_tf_squeeze_breakout",
            "mtf_squeeze_full_combo",
            "1D non-bear 4H squeeze breakout with volume, ATR and fast failure exit",
            {"signal_type": "multi_tf_squeeze_breakout", "daily_fast": 50, "daily_slow": 200, "bb_window": 40, "bb_k": 2.0, "kc_window": 40, "kc_k": 1.5, "breakout_window": 48, "exit_ema": 18, "use_volume_confirm": True, "volume_window": 60, "min_volume_ratio": 1.15, "use_atr_expand": True, "atr_expand_ratio": 1.05, "use_fast_fail_exit": True},
            stage="combo_volume_atr_fast_exit",
            components=["volume_breakout_confirmation", "atr_expansion_confirmation", "fast_failure_exit"],
            notes=["combination: volume, ATR expansion and fast failure exit"],
        ),
        spec(
            "regime_router",
            "regime_router_original",
            "Regime router: trend regime uses EMA ribbon, other regimes stay cash",
            {"signal_type": "regime_router", "daily_fast": 50, "daily_slow": 200, "use_sideways_pullback": False, "use_high_vol_risk_off": False, "use_bear_cash": True},
            stage="original",
            components=[],
            notes=["route trend regime to EMA ribbon, otherwise cash"],
        ),
        spec(
            "regime_router",
            "regime_router_sideways_pullback",
            "Regime router with sideways pullback entries",
            {"signal_type": "regime_router", "daily_fast": 50, "daily_slow": 200, "use_sideways_pullback": True, "use_high_vol_risk_off": False, "use_bear_cash": True},
            stage="single_sideways_pullback",
            components=["sideways_pullback_mode"],
            notes=["single optimization: allow pullback entries in sideways regime"],
        ),
        spec(
            "regime_router",
            "regime_router_high_vol_off",
            "Regime router with high-volatility risk-off",
            {"signal_type": "regime_router", "daily_fast": 50, "daily_slow": 200, "use_sideways_pullback": False, "use_high_vol_risk_off": True, "use_bear_cash": True},
            stage="single_high_volatility_risk_off",
            components=["high_volatility_risk_off"],
            notes=["single optimization: cash in high-volatility regimes"],
        ),
        spec(
            "regime_router",
            "regime_router_bear_cash",
            "Regime router with explicit bear cash state",
            {"signal_type": "regime_router", "daily_fast": 34, "daily_slow": 144, "use_sideways_pullback": False, "use_high_vol_risk_off": False, "use_bear_cash": True},
            stage="single_bear_cash_threshold",
            components=["faster_bear_cash_threshold"],
            notes=["single optimization: faster bear-state cash rule"],
        ),
        spec(
            "regime_router",
            "regime_router_full_combo",
            "Regime router with pullback mode, high-vol risk-off and faster bear cash",
            {"signal_type": "regime_router", "daily_fast": 34, "daily_slow": 144, "use_sideways_pullback": True, "use_high_vol_risk_off": True, "use_bear_cash": True},
            stage="combo_router_full",
            components=["sideways_pullback_mode", "high_volatility_risk_off", "faster_bear_cash_threshold"],
            notes=["combination: full simple regime router"],
        ),
        spec(
            "regime_router",
            "regime_router_weekly_monthly_combo",
            "Regime router with 1W/1M trend context and high-vol risk-off",
            {"signal_type": "regime_router", "daily_fast": 34, "daily_slow": 144, "weekly_fast": 10, "weekly_slow": 30, "monthly_fast": 3, "monthly_slow": 10, "use_weekly_confirm": True, "use_monthly_confirm": True, "use_sideways_pullback": True, "use_high_vol_risk_off": True, "use_bear_cash": True},
            stage="combo_higher_timeframe_router",
            components=["weekly_trend_confirmation", "monthly_trend_confirmation", "sideways_pullback_mode", "high_volatility_risk_off", "faster_bear_cash_threshold"],
            notes=["combination: route only when daily trend agrees with weekly and monthly context"],
        ),
        spec(
            "regime_router",
            "regime_router_tiered_htf_control",
            "Regime router with 1D permission, 1W sizing and 1M risk switch",
            {"signal_type": "regime_router", "daily_fast": 34, "daily_slow": 144, "weekly_fast": 10, "weekly_slow": 30, "monthly_fast": 3, "monthly_slow": 10, "use_tiered_higher_timeframe_control": True, "use_weekly_position_scaling": True, "use_monthly_risk_switch": True, "weekly_bull_scale": 1.0, "weekly_neutral_scale": 0.5, "weekly_bear_scale": 0.25, "monthly_bear_scale": 0.0, "use_sideways_pullback": True, "use_high_vol_risk_off": True, "use_bear_cash": True},
            stage="combo_tiered_higher_timeframe_control",
            components=["daily_trade_permission", "weekly_position_sizing", "monthly_risk_switch", "sideways_pullback_mode", "high_volatility_risk_off"],
            notes=["combination: regime router keeps daily trade permission while weekly and monthly context control risk size"],
        ),
        spec(
            "derivatives_risk_filtered_trend",
            "deriv_risk_trend_original",
            "EMA ribbon trend without derivatives filter",
            {"signal_type": "derivatives_risk_filtered_trend", "use_funding_filter": False, "use_oi_filter": False, "use_long_short_filter": False, "risk_exit": False},
            stage="original",
            components=[],
            notes=["base trend signal before derivatives risk filters"],
        ),
        spec(
            "derivatives_risk_filtered_trend",
            "deriv_risk_trend_funding",
            "EMA ribbon trend with funding crowding filter",
            {"signal_type": "derivatives_risk_filtered_trend", "use_funding_filter": True, "use_oi_filter": False, "use_long_short_filter": False, "risk_exit": False},
            stage="single_funding_filter",
            components=["funding_crowding_filter"],
            notes=["single optimization: do not chase crowded funding"],
        ),
        spec(
            "derivatives_risk_filtered_trend",
            "deriv_risk_trend_oi",
            "EMA ribbon trend with OI acceleration filter",
            {"signal_type": "derivatives_risk_filtered_trend", "use_funding_filter": False, "use_oi_filter": True, "use_long_short_filter": False, "risk_exit": False},
            stage="single_oi_filter",
            components=["open_interest_acceleration_filter"],
            notes=["single optimization: avoid extreme OI acceleration"],
        ),
        spec(
            "derivatives_risk_filtered_trend",
            "deriv_risk_trend_longs",
            "EMA ribbon trend with long-short crowding filter",
            {"signal_type": "derivatives_risk_filtered_trend", "use_funding_filter": False, "use_oi_filter": False, "use_long_short_filter": True, "risk_exit": False},
            stage="single_long_short_filter",
            components=["long_short_crowding_filter"],
            notes=["single optimization: avoid long-side crowding"],
        ),
        spec(
            "derivatives_risk_filtered_trend",
            "deriv_risk_trend_full_combo",
            "EMA ribbon trend with funding, OI and long-short filters",
            {"signal_type": "derivatives_risk_filtered_trend", "use_funding_filter": True, "use_oi_filter": True, "use_long_short_filter": True, "risk_exit": True},
            stage="combo_all_derivatives_filters",
            components=["funding_crowding_filter", "open_interest_acceleration_filter", "long_short_crowding_filter", "risk_filter_exit"],
            notes=["combination: all derivatives filters also force risk exit"],
        ),
        spec(
            "short_research_branch",
            "short_branch_short_flat_original",
            "Short/flat bearish EMA ribbon research branch",
            {"signal_type": "short_research_branch", "mode": "short_flat", "use_funding_guard": False, "use_squeeze_guard": False},
            direction_policy="short_flat",
            stage="original",
            components=[],
            notes=["research-only short branch; never enters normal shortlist"],
        ),
        spec(
            "short_research_branch",
            "short_branch_funding_guard",
            "Short/flat bearish EMA ribbon with funding guard",
            {"signal_type": "short_research_branch", "mode": "short_flat", "use_funding_guard": True, "use_squeeze_guard": False},
            direction_policy="short_flat",
            stage="single_funding_guard",
            components=["short_funding_squeeze_guard"],
            notes=["single optimization: avoid shorting when funding is too negative"],
        ),
        spec(
            "short_research_branch",
            "short_branch_squeeze_guard",
            "Short/flat bearish EMA ribbon with squeeze guard",
            {"signal_type": "short_research_branch", "mode": "short_flat", "use_funding_guard": False, "use_squeeze_guard": True},
            direction_policy="short_flat",
            stage="single_short_squeeze_guard",
            components=["short_squeeze_risk_guard"],
            notes=["single optimization: avoid crowded short squeeze risk"],
        ),
        spec(
            "short_research_branch",
            "short_branch_short_guard_combo",
            "Short/flat bearish EMA ribbon with funding and squeeze guards",
            {"signal_type": "short_research_branch", "mode": "short_flat", "use_funding_guard": True, "use_squeeze_guard": True},
            direction_policy="short_flat",
            stage="combo_short_guards",
            components=["short_funding_squeeze_guard", "short_squeeze_risk_guard"],
            notes=["combination: funding and squeeze guards"],
        ),
        spec(
            "short_research_branch",
            "short_branch_long_short_guard_combo",
            "Long/short EMA ribbon with funding and squeeze guards",
            {"signal_type": "short_research_branch", "mode": "long_short", "use_funding_guard": True, "use_squeeze_guard": True},
            direction_policy="long_short",
            stage="combo_long_short_guards",
            components=["long_short_switching", "short_funding_squeeze_guard", "short_squeeze_risk_guard"],
            notes=["combination: long-short switching remains research-only"],
        ),
        spec(
            "vote_ensemble",
            "vote_ensemble_threshold3",
            "3-of-5 simple rule voting ensemble",
            {"signal_type": "vote_ensemble", "entry_threshold": 3, "exit_threshold": 2, "use_derivatives_vote": True, "require_vol_vote": False},
            stage="original",
            components=[],
            notes=["EMA, Donchian, ATR channel, derivatives risk and volatility votes"],
        ),
        spec(
            "vote_ensemble",
            "vote_ensemble_threshold4",
            "4-of-5 simple rule voting ensemble",
            {"signal_type": "vote_ensemble", "entry_threshold": 4, "exit_threshold": 3, "use_derivatives_vote": True, "require_vol_vote": False},
            stage="single_stricter_vote_threshold",
            components=["stricter_vote_threshold"],
            notes=["single optimization: require 4 votes"],
        ),
        spec(
            "vote_ensemble",
            "vote_ensemble_derivatives_vote",
            "3-of-5 voting ensemble with derivatives vote required",
            {"signal_type": "vote_ensemble", "entry_threshold": 3, "exit_threshold": 2, "use_derivatives_vote": True, "require_derivatives_vote": True, "require_vol_vote": False},
            stage="single_derivatives_vote_required",
            components=["derivatives_vote_required"],
            notes=["single optimization: derivatives risk vote must pass"],
        ),
        spec(
            "vote_ensemble",
            "vote_ensemble_vol_required",
            "3-of-5 voting ensemble with volatility vote required",
            {"signal_type": "vote_ensemble", "entry_threshold": 3, "exit_threshold": 2, "use_derivatives_vote": True, "require_vol_vote": True},
            stage="single_volatility_vote_required",
            components=["volatility_vote_required"],
            notes=["single optimization: volatility vote must pass"],
        ),
        spec(
            "vote_ensemble",
            "vote_ensemble_full_combo",
            "4-of-5 voting ensemble with derivatives and volatility votes required",
            {"signal_type": "vote_ensemble", "entry_threshold": 4, "exit_threshold": 3, "use_derivatives_vote": True, "require_derivatives_vote": True, "require_vol_vote": True},
            stage="combo_threshold4_derivatives_volatility",
            components=["stricter_vote_threshold", "derivatives_vote_required", "volatility_vote_required"],
            notes=["combination: strict vote plus required risk votes"],
        ),
        spec(
            "vote_ensemble",
            "vote_ensemble_weekly_monthly_combo",
            "4-of-5 voting ensemble with 1W/1M trend context",
            {"signal_type": "vote_ensemble", "entry_threshold": 4, "exit_threshold": 3, "use_derivatives_vote": True, "require_derivatives_vote": True, "require_vol_vote": True, "weekly_fast": 10, "weekly_slow": 30, "monthly_fast": 3, "monthly_slow": 10, "use_weekly_confirm": True, "use_monthly_confirm": True},
            stage="combo_higher_timeframe_vote",
            components=["weekly_trend_confirmation", "monthly_trend_confirmation", "stricter_vote_threshold", "derivatives_vote_required", "volatility_vote_required"],
            notes=["combination: vote signal must agree with higher-timeframe trend context"],
        ),
        spec(
            "vote_ensemble",
            "vote_ensemble_tiered_htf_control",
            "3-of-5 voting ensemble with 1D permission, 1W sizing and 1M risk switch",
            {"signal_type": "vote_ensemble", "entry_threshold": 3, "exit_threshold": 2, "use_derivatives_vote": True, "require_derivatives_vote": False, "require_vol_vote": False, "use_daily_trade_permission": True, "weekly_fast": 10, "weekly_slow": 30, "monthly_fast": 3, "monthly_slow": 10, "use_tiered_higher_timeframe_control": True, "use_weekly_position_scaling": True, "use_monthly_risk_switch": True, "weekly_bull_scale": 1.0, "weekly_neutral_scale": 0.5, "weekly_bear_scale": 0.25, "monthly_bear_scale": 0.0},
            stage="combo_tiered_higher_timeframe_control",
            components=["daily_trade_permission", "weekly_position_sizing", "monthly_risk_switch", "simple_vote_ensemble"],
            notes=["combination: daily trend must permit the vote, weekly sizes exposure, monthly bear state cuts risk"],
        ),
    ]


def evaluate_mtf_rule(
    spec: MultiTimeframeRuleSpec,
    *,
    bars_1h: pd.DataFrame,
    bars_4h: pd.DataFrame,
    bars_1d: pd.DataFrame,
    bars_1w: pd.DataFrame | None = None,
    bars_1mo: pd.DataFrame | None = None,
    derivatives_4h: pd.DataFrame,
    initial_capital: float,
    cost_bps: float,
) -> EvaluatedMtfRule:
    close = bars_4h["close"].astype(float)
    bar_returns = close.pct_change().fillna(0.0)
    if _needs_weekly_context(spec.params) and bars_1w is None:
        bars_1w = aggregate_ohlcv_calendar(bars_1h, timeframe="1w")
    if _needs_monthly_context(spec.params) and bars_1mo is None:
        bars_1mo = aggregate_ohlcv_calendar(bars_1h, timeframe="1mo")
    raw = raw_mtf_signal(
        spec,
        bars_1h=bars_1h,
        bars_4h=bars_4h,
        bars_1d=bars_1d,
        bars_1w=bars_1w,
        bars_1mo=bars_1mo,
        derivatives_4h=derivatives_4h,
    )
    raw = raw.reindex(close.index).fillna(0.0).clip(-1.0, 1.0)
    exposure = raw.shift(1).fillna(0.0).clip(-1.0, 1.0)
    turnover = exposure.diff().abs().fillna(exposure.abs())
    cost = turnover * (float(cost_bps) / 10_000.0)
    returns = (exposure * bar_returns - cost).fillna(0.0)
    equity = float(initial_capital) * (1.0 + returns).cumprod()
    metrics = performance_metrics(
        strategy_returns=returns,
        equity=equity,
        exposure=exposure,
        turnover=turnover,
        cost=cost,
        interval=BASE_INTERVAL,
        initial_capital=initial_capital,
    )
    return EvaluatedMtfRule(spec, raw, exposure, returns, turnover, cost, equity, metrics)


def raw_mtf_signal(
    spec: MultiTimeframeRuleSpec,
    *,
    bars_1h: pd.DataFrame,
    bars_4h: pd.DataFrame,
    bars_1d: pd.DataFrame,
    bars_1w: pd.DataFrame | None = None,
    bars_1mo: pd.DataFrame | None = None,
    derivatives_4h: pd.DataFrame,
) -> pd.Series:
    if _needs_weekly_context(spec.params) and bars_1w is None:
        bars_1w = aggregate_ohlcv_calendar(bars_1h, timeframe="1w")
    if _needs_monthly_context(spec.params) and bars_1mo is None:
        bars_1mo = aggregate_ohlcv_calendar(bars_1h, timeframe="1mo")
    signal_type = str(spec.params["signal_type"])
    if signal_type == "multi_tf_trend_confirm":
        return _signal_multi_tf_trend_confirm(bars_1h=bars_1h, bars_4h=bars_4h, bars_1d=bars_1d, bars_1w=bars_1w, bars_1mo=bars_1mo, params=spec.params)
    if signal_type == "multi_tf_turtle":
        return _signal_multi_tf_turtle(bars_4h=bars_4h, bars_1d=bars_1d, bars_1w=bars_1w, bars_1mo=bars_1mo, derivatives_4h=derivatives_4h, params=spec.params)
    if signal_type == "trend_pullback_reentry":
        return _signal_trend_pullback_reentry(bars_1h=bars_1h, bars_4h=bars_4h, bars_1d=bars_1d, bars_1w=bars_1w, bars_1mo=bars_1mo, params=spec.params)
    if signal_type == "multi_tf_squeeze_breakout":
        return _signal_multi_tf_squeeze_breakout(bars_4h=bars_4h, bars_1d=bars_1d, bars_1w=bars_1w, bars_1mo=bars_1mo, params=spec.params)
    if signal_type == "regime_router":
        return _signal_regime_router(bars_4h=bars_4h, bars_1d=bars_1d, bars_1w=bars_1w, bars_1mo=bars_1mo, params=spec.params)
    if signal_type == "derivatives_risk_filtered_trend":
        return _signal_derivatives_risk_filtered_trend(bars_4h=bars_4h, derivatives_4h=derivatives_4h, params=spec.params)
    if signal_type == "short_research_branch":
        return _signal_short_research_branch(bars_1h=bars_1h, bars_4h=bars_4h, bars_1d=bars_1d, derivatives_4h=derivatives_4h, params=spec.params)
    if signal_type == "vote_ensemble":
        return _signal_vote_ensemble(bars_4h=bars_4h, bars_1d=bars_1d, bars_1w=bars_1w, bars_1mo=bars_1mo, derivatives_4h=derivatives_4h, params=spec.params)
    raise ValueError(f"unsupported signal_type: {signal_type}")


def performance_metrics(
    *,
    strategy_returns: pd.Series,
    equity: pd.Series,
    exposure: pd.Series,
    turnover: pd.Series,
    cost: pd.Series,
    interval: str,
    initial_capital: float,
) -> dict[str, Any]:
    if strategy_returns.empty:
        return _empty_metrics(initial_capital)
    total_return = float(equity.iloc[-1] / float(initial_capital) - 1.0)
    elapsed_days = max(1.0, float((strategy_returns.index.max() - strategy_returns.index.min()).total_seconds()) / 86_400.0)
    annual_return = (1.0 + total_return) ** (365.0 / elapsed_days) - 1.0 if total_return > -1.0 else -1.0
    bars_per_year = float(BARS_PER_YEAR.get(interval, 365.0))
    std = float(strategy_returns.std(ddof=0))
    downside = strategy_returns[strategy_returns < 0.0]
    downside_std = float(downside.std(ddof=0)) if len(downside) else 0.0
    sharpe = float(strategy_returns.mean() / std * math.sqrt(bars_per_year)) if std > 0.0 else 0.0
    sortino = float(strategy_returns.mean() / downside_std * math.sqrt(bars_per_year)) if downside_std > 0.0 else 0.0
    drawdown = equity / equity.cummax() - 1.0
    max_drawdown = float(drawdown.min()) if len(drawdown) else 0.0
    positive = strategy_returns[strategy_returns > 0.0].sum()
    negative = strategy_returns[strategy_returns < 0.0].sum()
    profit_factor = float(positive / abs(negative)) if negative < 0.0 else (999.0 if positive > 0.0 else 0.0)
    exposed_returns = strategy_returns[exposure.abs() > 0.0]
    return {
        "total_return_pct": _round(total_return * 100.0),
        "annual_return_pct": _round(annual_return * 100.0),
        "annual_volatility_pct": _round(std * math.sqrt(bars_per_year) * 100.0),
        "downside_volatility_pct": _round(downside_std * math.sqrt(bars_per_year) * 100.0),
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
        "fee_return_pct": _round(float(cost.sum()) * 100.0),
        "winning_exposed_bar_pct": _round(float((exposed_returns > 0.0).mean()) * 100.0) if len(exposed_returns) else 0.0,
    }


def walk_forward_summary(item: EvaluatedMtfRule, *, initial_capital: float, fold_count: int = 4) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    n = len(item.returns)
    fold_size = max(1, n // fold_count)
    for fold in range(fold_count):
        start = fold * fold_size
        end = n if fold == fold_count - 1 else (fold + 1) * fold_size
        idx = item.returns.index[start:end]
        if len(idx) < 20:
            continue
        sub_returns = item.returns.loc[idx]
        equity = float(initial_capital) * (1.0 + sub_returns).cumprod()
        metrics = performance_metrics(
            strategy_returns=sub_returns,
            equity=equity,
            exposure=item.exposure.loc[idx],
            turnover=item.turnover.loc[idx],
            cost=item.cost.loc[idx],
            interval=BASE_INTERVAL,
            initial_capital=initial_capital,
        )
        passed = (
            float(metrics["total_return_pct"]) > 0.0
            and float(metrics["profit_factor"]) >= 1.0
            and float(metrics["max_drawdown_abs_pct"]) <= 35.0
            and float(metrics["average_exposure"]) >= 0.03
        )
        rows.append({"fold": fold + 1, "start": _ts(idx.min()), "end": _ts(idx.max()), "row_count": int(len(idx)), "passed": bool(passed), "metrics": metrics})
    pass_rate = sum(1 for row in rows if row["passed"]) / len(rows) if rows else 0.0
    return {"fold_count": len(rows), "pass_rate": _round(pass_rate), "minimum_pass_rate": 0.5, "passed": pass_rate >= 0.5 if rows else False, "folds": rows}


def annual_regime_summary(item: EvaluatedMtfRule, *, initial_capital: float) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for year, index in item.returns.groupby(item.returns.index.year).groups.items():
        idx = pd.DatetimeIndex(index)
        if len(idx) < 20:
            continue
        sub_returns = item.returns.loc[idx]
        equity = float(initial_capital) * (1.0 + sub_returns).cumprod()
        metrics = performance_metrics(
            strategy_returns=sub_returns,
            equity=equity,
            exposure=item.exposure.loc[idx],
            turnover=item.turnover.loc[idx],
            cost=item.cost.loc[idx],
            interval=BASE_INTERVAL,
            initial_capital=initial_capital,
        )
        rows.append({"segment": str(year), "start": _ts(idx.min()), "end": _ts(idx.max()), "row_count": int(len(idx)), "passed": float(metrics["total_return_pct"]) > 0.0 and float(metrics["profit_factor"]) >= 1.0, "metrics": metrics})
    positive_returns = [max(0.0, float(row["metrics"]["total_return_pct"])) for row in rows]
    total_positive = sum(positive_returns)
    best_share = max(positive_returns) / total_positive if total_positive > 0.0 else 0.0
    pass_rate = sum(1 for row in rows if row["passed"]) / len(rows) if rows else 0.0
    latest = rows[-1] if rows else None
    return {
        "segment_type": "annual",
        "segment_count": len(rows),
        "pass_rate": _round(pass_rate),
        "positive_segment_count": sum(1 for row in rows if row["passed"]),
        "best_positive_year_share": _round(best_share),
        "latest_segment_passed": bool(latest["passed"]) if latest else False,
        "latest_segment_total_return_pct": latest["metrics"]["total_return_pct"] if latest else 0.0,
        "segments": rows,
    }


def market_regime_summary(item: EvaluatedMtfRule, *, bars_4h: pd.DataFrame, initial_capital: float) -> dict[str, Any]:
    labels = _market_regime_labels(bars_4h)
    rows: list[dict[str, Any]] = []
    for label in ["bull_trend", "sideways", "high_volatility", "bear_risk"]:
        idx = item.returns.index[labels.reindex(item.returns.index).fillna("sideways") == label]
        if len(idx) < 20:
            continue
        sub_returns = item.returns.loc[idx]
        equity = float(initial_capital) * (1.0 + sub_returns).cumprod()
        metrics = performance_metrics(
            strategy_returns=sub_returns,
            equity=equity,
            exposure=item.exposure.loc[idx],
            turnover=item.turnover.loc[idx],
            cost=item.cost.loc[idx],
            interval=BASE_INTERVAL,
            initial_capital=initial_capital,
        )
        rows.append({"segment": label, "row_count": int(len(idx)), "passed": float(metrics["total_return_pct"]) > 0.0 and float(metrics["profit_factor"]) >= 1.0, "metrics": metrics})
    pass_rate = sum(1 for row in rows if row["passed"]) / len(rows) if rows else 0.0
    return {"segment_type": "market_regime", "segment_count": len(rows), "pass_rate": _round(pass_rate), "segments": rows}


def cost_stress_summary(
    spec: MultiTimeframeRuleSpec,
    *,
    bars_1h: pd.DataFrame,
    bars_4h: pd.DataFrame,
    bars_1d: pd.DataFrame,
    bars_1w: pd.DataFrame | None = None,
    bars_1mo: pd.DataFrame | None = None,
    derivatives_4h: pd.DataFrame,
    initial_capital: float,
    base_cost_bps: float,
) -> dict[str, Any]:
    scenarios: list[dict[str, Any]] = []
    for cost_bps in _cost_stress_bps(base_cost_bps):
        item = evaluate_mtf_rule(
            spec,
            bars_1h=bars_1h,
            bars_4h=bars_4h,
            bars_1d=bars_1d,
            bars_1w=bars_1w,
            bars_1mo=bars_1mo,
            derivatives_4h=derivatives_4h,
            initial_capital=initial_capital,
            cost_bps=cost_bps,
        )
        survives = float(item.metrics["total_return_pct"]) > 0.0 and float(item.metrics["profit_factor"]) >= 1.0
        scenarios.append({"cost_bps": _round(cost_bps), "survives": bool(survives), "metrics": item.metrics})
    survival_count = sum(1 for row in scenarios if row["survives"])
    return {
        "scenario_count": len(scenarios),
        "scenarios": scenarios,
        "survival_count": survival_count,
        "survival_rate": _round(survival_count / len(scenarios) if scenarios else 0.0),
        "base_survives": bool(scenarios[0]["survives"]) if scenarios else False,
        "cost_2x_survives": bool(scenarios[1]["survives"]) if len(scenarios) > 1 else False,
        "cost_5x_survives": bool(scenarios[2]["survives"]) if len(scenarios) > 2 else False,
    }


def higher_timeframe_context_summary(
    *,
    bars_4h: pd.DataFrame,
    bars_1d: pd.DataFrame,
    bars_1w: pd.DataFrame,
    bars_1mo: pd.DataFrame,
) -> dict[str, Any]:
    index = bars_4h.index
    if len(index) == 0:
        return {
            "row_count_4h": 0,
            "bar_1d_rows": int(len(bars_1d)),
            "bar_1w_rows": int(len(bars_1w)),
            "bar_1mo_rows": int(len(bars_1mo)),
            "daily_bull_coverage_pct": 0.0,
            "weekly_bull_coverage_pct": 0.0,
            "monthly_bull_coverage_pct": 0.0,
            "daily_weekly_monthly_bull_alignment_pct": 0.0,
        }
    daily = _timeframe_bull(bars_1d, index, fast=50, slow=200)
    weekly = _timeframe_bull(bars_1w, index, fast=10, slow=30)
    monthly = _timeframe_bull(bars_1mo, index, fast=3, slow=10)
    aligned = daily & weekly & monthly
    return {
        "row_count_4h": int(len(index)),
        "bar_1d_rows": int(len(bars_1d)),
        "bar_1w_rows": int(len(bars_1w)),
        "bar_1mo_rows": int(len(bars_1mo)),
        "daily_fast_slow": [50, 200],
        "weekly_fast_slow": [10, 30],
        "monthly_fast_slow": [3, 10],
        "daily_bull_coverage_pct": _round(float(daily.mean()) * 100.0),
        "weekly_bull_coverage_pct": _round(float(weekly.mean()) * 100.0),
        "monthly_bull_coverage_pct": _round(float(monthly.mean()) * 100.0),
        "daily_weekly_monthly_bull_alignment_pct": _round(float(aligned.mean()) * 100.0),
        "interpretation": "higher-timeframe context is diagnostic and research-only; it is not a paper/live gate",
    }


def render_multi_timeframe_rule_lab_markdown(report: Mapping[str, Any]) -> str:
    gate = _mapping(report.get("gate"))
    validation = _mapping(report.get("validation_design"))
    input_info = _mapping(report.get("input"))
    htf = _mapping(report.get("higher_timeframe_context"))
    lines = [
        "# BTC 多周期简单规则策略实验室",
        "",
        f"- 状态：`{report.get('status')}`",
        f"- 决策：`{report.get('decision')}`",
        f"- 写 paper 队列：`{gate.get('paper_queue_write_allowed')}`",
        f"- 解锁 live：`{gate.get('live_unlock_allowed')}`",
        f"- 1H 样本行数：`{input_info.get('market_1h_rows')}`",
        f"- 4H 决策行数：`{input_info.get('bar_4h_rows')}`",
        f"- 1D 派生行数：`{input_info.get('bar_1d_rows')}`",
        f"- 1W 派生行数：`{input_info.get('bar_1w_rows')}`",
        f"- 1M 派生行数：`{input_info.get('bar_1mo_rows')}`",
        f"- 日线/周线/月线同时看多覆盖：`{htf.get('daily_weekly_monthly_bull_alignment_pct')}%`",
        f"- 候选数：`{validation.get('candidate_count')}`",
        "",
        "## 普通扩展研究短名单",
        "",
    ]
    shortlist = list(report.get("extended_research_shortlist", []))
    if not shortlist:
        lines.append("- 当前没有 long/flat 候选通过更严格短名单门槛。")
    for row in shortlist:
        lines.append(
            f"- `{row['candidate_id']}`：{row['label']}；阶段 `{row['optimization_stage']}`；"
            f"收益 `{row['total_return_pct']}%`，回撤 `{row['max_drawdown_pct']}%`，PF `{row['profit_factor']}`，"
            f"WF `{row['walk_forward_pass_rate']}`，保留状态 `{row['retention_decision']}`。"
        )
    lines.extend(["", "## 做空研究观察名单", ""])
    watchlist = list(report.get("short_research_watchlist", []))
    if not watchlist:
        lines.append("- 当前没有 short/long-short 候选进入做空研究观察名单。")
    for row in watchlist:
        lines.append(
            f"- `{row['candidate_id']}`：{row['label']}；方向 `{row['direction_policy']}`；阶段 `{row['optimization_stage']}`；"
            f"收益 `{row['total_return_pct']}%`，回撤 `{row['max_drawdown_pct']}%`，PF `{row['profit_factor']}`。"
        )
    lines.extend(["", "## 候选对比 Top 20", ""])
    lines.append("| 排名 | 候选 | 家族 | 方向 | 优化阶段 | 收益 | 回撤 | PF | WF | 年份集中 | 成本存活 | 决策 |")
    lines.append("|---:|---|---|---|---|---:|---:|---:|---:|---:|---:|---|")
    for idx, row in enumerate(list(report.get("comparison_rows", []))[:20], 1):
        lines.append(
            f"| {idx} | `{row['candidate_id']}` | `{row['family_id']}` | `{row['direction_policy']}` | `{row['optimization_stage']}` | "
            f"{row['total_return_pct']} | {row['max_drawdown_pct']} | {row['profit_factor']} | {row['walk_forward_pass_rate']} | "
            f"{row['best_positive_year_share']} | {row['cost_survival_rate']} | `{row['retention_decision']}` |"
        )
    lines.extend(["", "## 逐步优化对比", ""])
    for family in report.get("family_stepwise_comparison", []):
        lines.append(
            f"- `{family['family_id']}`：最佳阶段 `{family['best_optimization_stage']}`；"
            f"最佳候选 `{family['best_candidate_id']}`；保留状态 `{family['best_retention_decision']}`。"
        )
    lines.extend(
        [
            "",
            "## 复核重点",
            "",
            "- 本报告只做多周期简单规则研究筛选，不写 paper 队列，不解锁 live。",
            "- 做空和 long/short 候选只进入做空研究观察名单，不能进入普通扩展研究短名单。",
            "- derivatives sentiment 只做过滤和诊断，不能作为独立开仓信号。",
            "- 任何候选进入 paper 之前，必须另做 event-ledger、回撤归因、行情分段、成本压力和人工复核。",
        ]
    )
    return "\n".join(lines) + "\n"


def _signal_multi_tf_trend_confirm(
    *,
    bars_1h: pd.DataFrame,
    bars_4h: pd.DataFrame,
    bars_1d: pd.DataFrame,
    bars_1w: pd.DataFrame | None = None,
    bars_1mo: pd.DataFrame | None = None,
    params: Mapping[str, Any],
) -> pd.Series:
    close = bars_4h["close"].astype(float)
    trend_context = _trend_context_bull(bars_1d, close.index, params=params, bars_1w=bars_1w, bars_1mo=bars_1mo)
    fast = _ema(close, int(params["ema_fast"]))
    mid = _ema(close, int(params["ema_mid"]))
    slow = _ema(close, int(params["ema_slow"]))
    entry = trend_context & (fast > mid) & (mid > slow) & (close > slow)
    exit_signal = (~trend_context) | (close < mid)
    if bool(params.get("use_1h_exit", False)):
        close_1h = bars_1h["close"].astype(float)
        one_h_exit = close_1h < _ema(close_1h, int(params["exit_1h_ema"]))
        exit_signal = exit_signal | _to_4h(one_h_exit.astype(float), close.index).astype(bool)
    if bool(params.get("use_atr_trail", False)):
        atr = _atr(bars_4h, int(params.get("atr_window", 20)))
        signal = _stateful_long_flat_with_trailing(entry, exit_signal, close=close, atr=atr, atr_mult=float(params.get("atr_mult", 3.0)))
    else:
        signal = _stateful_long_flat(entry, exit_signal)
    return _apply_tiered_higher_timeframe_control(signal, bars_1w=bars_1w, bars_1mo=bars_1mo, params=params)


def _signal_multi_tf_turtle(
    *,
    bars_4h: pd.DataFrame,
    bars_1d: pd.DataFrame,
    bars_1w: pd.DataFrame | None = None,
    bars_1mo: pd.DataFrame | None = None,
    derivatives_4h: pd.DataFrame,
    params: Mapping[str, Any],
) -> pd.Series:
    close = bars_4h["close"].astype(float)
    high = bars_4h["high"].astype(float)
    low = bars_4h["low"].astype(float)
    trend_context = _trend_context_bull(bars_1d, close.index, params=params, bars_1w=bars_1w, bars_1mo=bars_1mo)
    entry = trend_context & (close > high.shift(1).rolling(int(params["entry_window"])).max())
    exit_signal = (~trend_context) | (close < low.shift(1).rolling(int(params["exit_window"])).min())
    if bool(params.get("use_vol_filter", False)):
        entry = entry & _high_vol_ok(close, window=60)
    if bool(params.get("use_derivatives_filter", False)):
        entry = entry & _long_derivatives_risk_ok(derivatives_4h, close.index, use_funding=True, use_oi=False, use_long_short=False)
    if bool(params.get("use_atr_stop", False)):
        atr = _atr(bars_4h, int(params.get("atr_window", 20)))
        signal = _stateful_long_flat_with_trailing(entry, exit_signal, close=close, atr=atr, atr_mult=float(params.get("atr_mult", 3.0)))
    else:
        signal = _stateful_long_flat(entry, exit_signal)
    return _apply_tiered_higher_timeframe_control(signal, bars_1w=bars_1w, bars_1mo=bars_1mo, params=params)


def _signal_trend_pullback_reentry(
    *,
    bars_1h: pd.DataFrame,
    bars_4h: pd.DataFrame,
    bars_1d: pd.DataFrame,
    bars_1w: pd.DataFrame | None = None,
    bars_1mo: pd.DataFrame | None = None,
    params: Mapping[str, Any],
) -> pd.Series:
    close = bars_4h["close"].astype(float)
    low = bars_4h["low"].astype(float)
    trend_context = _trend_context_bull(bars_1d, close.index, params=params, bars_1w=bars_1w, bars_1mo=bars_1mo)
    anchor = _ema(close, int(params["pullback_ema"]))
    near_pullback = (low <= anchor * (1.0 + float(params["pullback_band"]))) & (close > anchor)
    momentum = close > close.shift(1)
    if bool(params.get("use_1h_momentum", False)):
        close_1h = bars_1h["close"].astype(float)
        mom_1h = (close_1h > _ema(close_1h, 24)) & (close_1h.pct_change(6) > 0.0)
        momentum = _to_4h(mom_1h.astype(float), close.index).astype(bool)
    entry = trend_context & near_pullback & momentum
    exit_signal = (~trend_context) | (close < _ema(close, 100))
    if bool(params.get("use_atr_exit", False)):
        atr = _atr(bars_4h, int(params.get("atr_window", 20)))
        signal = _stateful_long_flat_with_trailing(entry, exit_signal, close=close, atr=atr, atr_mult=float(params.get("atr_mult", 2.5)))
    else:
        signal = _stateful_long_flat(entry, exit_signal)
    return _apply_tiered_higher_timeframe_control(signal, bars_1w=bars_1w, bars_1mo=bars_1mo, params=params)


def _signal_multi_tf_squeeze_breakout(
    *,
    bars_4h: pd.DataFrame,
    bars_1d: pd.DataFrame,
    bars_1w: pd.DataFrame | None = None,
    bars_1mo: pd.DataFrame | None = None,
    params: Mapping[str, Any],
) -> pd.Series:
    close = bars_4h["close"].astype(float)
    high = bars_4h["high"].astype(float)
    volume = bars_4h["volume"].astype(float)
    higher_ok = _trend_context_not_bear(bars_1d, close.index, params=params, bars_1w=bars_1w, bars_1mo=bars_1mo)
    bb_mid = close.rolling(int(params["bb_window"])).mean()
    bb_std = close.rolling(int(params["bb_window"])).std(ddof=0)
    bb_upper = bb_mid + float(params["bb_k"]) * bb_std
    bb_lower = bb_mid - float(params["bb_k"]) * bb_std
    atr = _atr(bars_4h, int(params["kc_window"]))
    kc_mid = _ema(close, int(params["kc_window"]))
    kc_upper = kc_mid + float(params["kc_k"]) * atr
    kc_lower = kc_mid - float(params["kc_k"]) * atr
    squeeze_on = (bb_upper < kc_upper) & (bb_lower > kc_lower)
    recent_squeeze = squeeze_on.shift(1).rolling(18, min_periods=1).max().fillna(False).astype(bool)
    breakout = close > high.shift(1).rolling(int(params["breakout_window"])).max()
    if bool(params.get("use_volume_confirm", False)):
        volume_ratio = volume / volume.rolling(int(params.get("volume_window", 60))).median().replace(0.0, math.nan)
        breakout = breakout & (volume_ratio >= float(params.get("min_volume_ratio", 1.15)))
    if bool(params.get("use_atr_expand", False)):
        atr_ratio = atr / atr.rolling(int(params.get("volume_window", 60))).median().replace(0.0, math.nan)
        breakout = breakout & (atr_ratio >= float(params.get("atr_expand_ratio", 1.05)))
    exit_ema = int(params["exit_ema"])
    exit_signal = close < _ema(close, exit_ema)
    if bool(params.get("use_fast_fail_exit", False)):
        exit_signal = exit_signal | (close < close.shift(1).rolling(12).min())
    signal = _stateful_long_flat(higher_ok & recent_squeeze & breakout, exit_signal)
    return _apply_tiered_higher_timeframe_control(signal, bars_1w=bars_1w, bars_1mo=bars_1mo, params=params)


def _signal_regime_router(
    *,
    bars_4h: pd.DataFrame,
    bars_1d: pd.DataFrame,
    bars_1w: pd.DataFrame | None = None,
    bars_1mo: pd.DataFrame | None = None,
    params: Mapping[str, Any],
) -> pd.Series:
    close = bars_4h["close"].astype(float)
    trend_bull = _trend_context_bull(bars_1d, close.index, params=params, bars_1w=bars_1w, bars_1mo=bars_1mo)
    trend_bear = _trend_context_bear(bars_1d, close.index, params=params, bars_1w=bars_1w, bars_1mo=bars_1mo)
    high_vol = ~_high_vol_ok(close, window=60)
    ribbon = _ema_ribbon_long(close)
    donchian = close > bars_4h["high"].astype(float).shift(1).rolling(72).max()
    pullback = (bars_4h["low"].astype(float) <= _ema(close, 50) * 1.012) & (close > _ema(close, 50))
    entry = trend_bull & (ribbon | donchian)
    if bool(params.get("use_sideways_pullback", False)):
        sideways = (~trend_bull) & (~trend_bear)
        entry = entry | (sideways & pullback)
    exit_signal = close < _ema(close, 100)
    if bool(params.get("use_bear_cash", True)):
        exit_signal = exit_signal | trend_bear
        entry = entry & (~trend_bear)
    if bool(params.get("use_high_vol_risk_off", False)):
        exit_signal = exit_signal | high_vol
        entry = entry & (~high_vol)
    signal = _stateful_long_flat(entry, exit_signal)
    return _apply_tiered_higher_timeframe_control(signal, bars_1w=bars_1w, bars_1mo=bars_1mo, params=params)


def _signal_derivatives_risk_filtered_trend(*, bars_4h: pd.DataFrame, derivatives_4h: pd.DataFrame, params: Mapping[str, Any]) -> pd.Series:
    close = bars_4h["close"].astype(float)
    base_entry = _ema_ribbon_long(close)
    base_exit = close < _ema(close, 100)
    risk_ok = _long_derivatives_risk_ok(
        derivatives_4h,
        close.index,
        use_funding=bool(params.get("use_funding_filter", False)),
        use_oi=bool(params.get("use_oi_filter", False)),
        use_long_short=bool(params.get("use_long_short_filter", False)),
    )
    entry = base_entry & risk_ok
    exit_signal = base_exit | ((~risk_ok) if bool(params.get("risk_exit", False)) else False)
    return _stateful_long_flat(entry, exit_signal)


def _signal_short_research_branch(*, bars_1h: pd.DataFrame, bars_4h: pd.DataFrame, bars_1d: pd.DataFrame, derivatives_4h: pd.DataFrame, params: Mapping[str, Any]) -> pd.Series:
    close = bars_4h["close"].astype(float)
    daily_bull = _daily_bull(bars_1d, close.index, fast=50, slow=200)
    daily_bear = _daily_bear(bars_1d, close.index, fast=50, slow=200)
    long_entry = daily_bull & _ema_ribbon_long(close)
    short_entry = daily_bear & _ema_ribbon_bear(close)
    close_1h = bars_1h["close"].astype(float)
    one_h_short_exit = _to_4h((close_1h > _ema(close_1h, 24)).astype(float), close.index).astype(bool)
    short_exit = (~daily_bear) | (close > _ema(close, 50)) | one_h_short_exit
    long_exit = (~daily_bull) | (close < _ema(close, 100))
    short_ok = _short_derivatives_risk_ok(
        derivatives_4h,
        close.index,
        use_funding=bool(params.get("use_funding_guard", False)),
        use_squeeze=bool(params.get("use_squeeze_guard", False)),
    )
    short_entry = short_entry & short_ok
    short_exit = short_exit | (~short_ok)
    if str(params.get("mode")) == "long_short":
        long_ok = _long_derivatives_risk_ok(derivatives_4h, close.index, use_funding=True, use_oi=False, use_long_short=True)
        return _stateful_long_short(long_entry & long_ok, long_exit, short_entry, short_exit)
    return _stateful_short_flat(short_entry, short_exit)


def _signal_vote_ensemble(
    *,
    bars_4h: pd.DataFrame,
    bars_1d: pd.DataFrame,
    bars_1w: pd.DataFrame | None = None,
    bars_1mo: pd.DataFrame | None = None,
    derivatives_4h: pd.DataFrame,
    params: Mapping[str, Any],
) -> pd.Series:
    close = bars_4h["close"].astype(float)
    trend_context = _trend_context_bull(bars_1d, close.index, params=params, bars_1w=bars_1w, bars_1mo=bars_1mo)
    ema_vote = trend_context & _ema_ribbon_long(close)
    donchian_vote = close > bars_4h["high"].astype(float).shift(1).rolling(96).max()
    atr = _atr(bars_4h, 20)
    atr_channel_vote = close > _ema(close, 96) + 1.2 * atr
    deriv_vote = _long_derivatives_risk_ok(derivatives_4h, close.index, use_funding=True, use_oi=True, use_long_short=True)
    vol_vote = _high_vol_ok(close, window=60)
    votes = ema_vote.astype(int) + donchian_vote.astype(int) + atr_channel_vote.astype(int) + deriv_vote.astype(int) + vol_vote.astype(int)
    entry = votes >= int(params["entry_threshold"])
    exit_signal = votes < int(params["exit_threshold"])
    if bool(params.get("require_derivatives_vote", False)):
        entry = entry & deriv_vote
        exit_signal = exit_signal | (~deriv_vote)
    if bool(params.get("require_vol_vote", False)):
        entry = entry & vol_vote
        exit_signal = exit_signal | (~vol_vote)
    if bool(params.get("use_daily_trade_permission", False)):
        entry = entry & trend_context
        exit_signal = exit_signal | (~trend_context)
    signal = _stateful_long_flat(entry, exit_signal)
    return _apply_tiered_higher_timeframe_control(signal, bars_1w=bars_1w, bars_1mo=bars_1mo, params=params)


def _evaluate_buy_hold(bars_4h: pd.DataFrame, *, initial_capital: float, cost_bps: float) -> EvaluatedMtfRule:
    spec = MultiTimeframeRuleSpec("baseline", "buy_hold", "Buy and hold BTC", {"signal_type": "baseline"}, "long_flat", False, "baseline", [], [])
    close = bars_4h["close"].astype(float)
    bar_returns = close.pct_change().fillna(0.0)
    raw = pd.Series(1.0, index=close.index)
    exposure = raw.shift(1).fillna(0.0)
    turnover = exposure.diff().abs().fillna(exposure.abs())
    cost = turnover * (float(cost_bps) / 10_000.0)
    returns = (exposure * bar_returns - cost).fillna(0.0)
    equity = float(initial_capital) * (1.0 + returns).cumprod()
    metrics = performance_metrics(strategy_returns=returns, equity=equity, exposure=exposure, turnover=turnover, cost=cost, interval=BASE_INTERVAL, initial_capital=initial_capital)
    return EvaluatedMtfRule(spec, raw, exposure, returns, turnover, cost, equity, metrics)


def _grid_row(
    item: EvaluatedMtfRule,
    *,
    buy_hold_metrics: Mapping[str, Any],
    walk_forward: Mapping[str, Any],
    annual_regime: Mapping[str, Any],
    market_regime: Mapping[str, Any],
    cost_stress: Mapping[str, Any],
) -> dict[str, Any]:
    metrics = item.metrics
    score = _score(metrics, buy_hold_metrics=buy_hold_metrics, walk_forward=walk_forward, annual_regime=annual_regime, market_regime=market_regime, cost_stress=cost_stress)
    decision = _retention_decision(item.spec, metrics, walk_forward=walk_forward, annual_regime=annual_regime, market_regime=market_regime, cost_stress=cost_stress)
    row = {
        "candidate_id": item.spec.candidate_id,
        "family_id": item.spec.family_id,
        "variant_id": item.spec.variant_id,
        "branch": item.spec.branch,
        "direction_policy": item.spec.direction_policy,
        "variant_kind": "optimized" if item.spec.optimized else "original",
        "optimization_stage": item.spec.optimization_stage,
        "optimization_components": item.spec.optimization_components,
        "optimization_notes": item.spec.optimization_notes,
        "params": item.spec.params,
        "params_hash": hashlib.sha1(json.dumps(item.spec.params, sort_keys=True).encode("utf-8")).hexdigest()[:12],
        "label": item.spec.label,
        "total_return_pct": metrics["total_return_pct"],
        "annual_return_pct": metrics["annual_return_pct"],
        "max_drawdown_pct": metrics["max_drawdown_pct"],
        "max_drawdown_abs_pct": metrics["max_drawdown_abs_pct"],
        "profit_factor": metrics["profit_factor"],
        "sharpe_ratio": metrics["sharpe_ratio"],
        "average_exposure": metrics["average_exposure"],
        "average_net_exposure": metrics["average_net_exposure"],
        "turnover": metrics["turnover"],
        "fee_return_pct": metrics["fee_return_pct"],
        "return_diff_vs_buy_hold_pct": _round(float(metrics["total_return_pct"]) - float(buy_hold_metrics.get("total_return_pct", 0.0))),
        "drawdown_reduction_vs_buy_hold_pct": _round(float(buy_hold_metrics.get("max_drawdown_abs_pct", 0.0)) - float(metrics["max_drawdown_abs_pct"])),
        "walk_forward_pass_rate": walk_forward.get("pass_rate", 0.0),
        "annual_regime_pass_rate": annual_regime.get("pass_rate", 0.0),
        "market_regime_pass_rate": market_regime.get("pass_rate", 0.0),
        "best_positive_year_share": annual_regime.get("best_positive_year_share", 0.0),
        "latest_segment_passed": annual_regime.get("latest_segment_passed", False),
        "latest_segment_total_return_pct": annual_regime.get("latest_segment_total_return_pct", 0.0),
        "cost_survival_rate": cost_stress.get("survival_rate", 0.0),
        "score": _round(score),
        "retention_decision": decision,
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
        "walk_forward": walk_forward,
        "annual_regime": annual_regime,
        "market_regime": market_regime,
        "cost_stress": cost_stress,
    }
    return row


def _score(
    metrics: Mapping[str, Any],
    *,
    buy_hold_metrics: Mapping[str, Any],
    walk_forward: Mapping[str, Any],
    annual_regime: Mapping[str, Any],
    market_regime: Mapping[str, Any],
    cost_stress: Mapping[str, Any],
) -> float:
    score = float(metrics.get("total_return_pct", 0.0))
    score += 10.0 * float(metrics.get("profit_factor", 0.0))
    score += 12.0 * float(walk_forward.get("pass_rate", 0.0))
    score += 8.0 * float(annual_regime.get("pass_rate", 0.0))
    score += 5.0 * float(market_regime.get("pass_rate", 0.0))
    score += 10.0 * float(cost_stress.get("survival_rate", 0.0))
    score += max(0.0, float(buy_hold_metrics.get("max_drawdown_abs_pct", 0.0)) - float(metrics.get("max_drawdown_abs_pct", 0.0))) * 0.5
    score -= max(0.0, float(metrics.get("max_drawdown_abs_pct", 0.0)) - 25.0) * 1.5
    score -= max(0.0, float(annual_regime.get("best_positive_year_share", 0.0)) - 0.60) * 35.0
    score -= max(0.0, float(metrics.get("turnover", 0.0)) - 160.0) * 0.05
    if not annual_regime.get("latest_segment_passed", False):
        score -= 12.0
    return score


def _retention_decision(
    spec: MultiTimeframeRuleSpec,
    metrics: Mapping[str, Any],
    *,
    walk_forward: Mapping[str, Any],
    annual_regime: Mapping[str, Any],
    market_regime: Mapping[str, Any],
    cost_stress: Mapping[str, Any],
) -> str:
    if float(metrics.get("total_return_pct", 0.0)) <= 0.0:
        return "reject_non_positive_total_return"
    if float(metrics.get("profit_factor", 0.0)) < 1.05:
        return "defer_profit_factor_too_thin"
    if float(metrics.get("max_drawdown_abs_pct", 0.0)) > 30.0:
        return "defer_drawdown_too_high"
    if float(walk_forward.get("pass_rate", 0.0)) < 0.5:
        return "defer_walk_forward_unstable"
    if float(annual_regime.get("pass_rate", 0.0)) < 0.5:
        return "defer_annual_regime_unstable"
    if float(market_regime.get("pass_rate", 0.0)) < 0.5:
        return "defer_market_regime_unstable"
    if float(cost_stress.get("survival_rate", 0.0)) < 0.67:
        return "defer_cost_stress_fragile"
    if float(annual_regime.get("best_positive_year_share", 0.0)) > 0.70:
        return "defer_year_concentration_review"
    if not annual_regime.get("latest_segment_passed", False):
        return "defer_latest_segment_failed"
    if spec.branch == "short_research":
        return "retain_short_research_watchlist_only"
    return "retain_extended_research_only"


def _extended_research_shortlist(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    used_families: set[str] = set()
    for row in rows:
        if row.get("retention_decision") != "retain_extended_research_only":
            continue
        family = str(row.get("family_id"))
        if family in used_families:
            continue
        selected.append(dict(row))
        used_families.add(family)
        if len(selected) >= 6:
            break
    return selected


def _short_research_watchlist(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for row in rows:
        if row.get("retention_decision") == "retain_short_research_watchlist_only":
            selected.append(dict(row))
        if len(selected) >= 4:
            break
    return selected


def _family_stepwise_comparison(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for family in sorted({str(row["family_id"]) for row in rows}):
        family_rows = [row for row in rows if row["family_id"] == family]
        original = next((row for row in family_rows if row["optimization_stage"] == "original"), family_rows[0])
        best = sorted(family_rows, key=lambda row: (-float(row["score"]), str(row["candidate_id"])))[0]
        variants = []
        for row in sorted(family_rows, key=lambda item: (_stage_rank(str(item["optimization_stage"])), str(item["candidate_id"]))):
            variants.append(
                {
                    "candidate_id": row["candidate_id"],
                    "direction_policy": row["direction_policy"],
                    "optimization_stage": row["optimization_stage"],
                    "optimization_components": row["optimization_components"],
                    "total_return_pct": row["total_return_pct"],
                    "delta_total_return_vs_original_pct": _round(float(row["total_return_pct"]) - float(original["total_return_pct"])),
                    "max_drawdown_abs_pct": row["max_drawdown_abs_pct"],
                    "delta_drawdown_abs_vs_original_pct": _round(float(row["max_drawdown_abs_pct"]) - float(original["max_drawdown_abs_pct"])),
                    "profit_factor": row["profit_factor"],
                    "score": row["score"],
                    "delta_score_vs_original": _round(float(row["score"]) - float(original["score"])),
                    "retention_decision": row["retention_decision"],
                }
            )
        output.append(
            {
                "family_id": family,
                "original_candidate_id": original["candidate_id"],
                "best_candidate_id": best["candidate_id"],
                "best_optimization_stage": best["optimization_stage"],
                "best_retention_decision": best["retention_decision"],
                "variants": variants,
            }
        )
    return output


def _stage_rank(stage: str) -> int:
    if stage == "original":
        return 0
    if stage.startswith("single_"):
        return 1
    if stage.startswith("combo_"):
        return 2
    return 3


def _needs_weekly_context(params: Mapping[str, Any]) -> bool:
    return bool(params.get("use_weekly_confirm", False) or params.get("use_weekly_position_scaling", False))


def _needs_monthly_context(params: Mapping[str, Any]) -> bool:
    return bool(params.get("use_monthly_confirm", False) or params.get("use_monthly_risk_switch", False))


def _apply_tiered_higher_timeframe_control(
    signal: pd.Series,
    *,
    bars_1w: pd.DataFrame | None,
    bars_1mo: pd.DataFrame | None,
    params: Mapping[str, Any],
) -> pd.Series:
    signal = signal.astype(float)
    if not bool(params.get("use_tiered_higher_timeframe_control", False)):
        return signal

    index = signal.index
    scale = pd.Series(1.0, index=index)
    if bool(params.get("use_weekly_position_scaling", False)):
        weekly_bull = _timeframe_bull(bars_1w, index, fast=int(params.get("weekly_fast", 10)), slow=int(params.get("weekly_slow", 30)))
        weekly_bear = _timeframe_bear(bars_1w, index, fast=int(params.get("weekly_fast", 10)), slow=int(params.get("weekly_slow", 30)))
        weekly_neutral = (~weekly_bull) & (~weekly_bear)
        weekly_scale = pd.Series(float(params.get("weekly_neutral_scale", 0.5)), index=index)
        weekly_scale.loc[weekly_bull] = float(params.get("weekly_bull_scale", 1.0))
        weekly_scale.loc[weekly_bear] = float(params.get("weekly_bear_scale", 0.25))
        weekly_scale.loc[weekly_neutral] = float(params.get("weekly_neutral_scale", 0.5))
        scale = scale * weekly_scale.clip(lower=0.0, upper=1.0)

    if bool(params.get("use_monthly_risk_switch", False)):
        monthly_bear = _timeframe_bear(bars_1mo, index, fast=int(params.get("monthly_fast", 3)), slow=int(params.get("monthly_slow", 10)))
        scale.loc[monthly_bear] = float(params.get("monthly_bear_scale", 0.0))

    return (signal * scale).clip(lower=-1.0, upper=1.0)


def _trend_context_bull(
    bars_1d: pd.DataFrame,
    index: pd.DatetimeIndex,
    *,
    params: Mapping[str, Any],
    bars_1w: pd.DataFrame | None = None,
    bars_1mo: pd.DataFrame | None = None,
) -> pd.Series:
    bull = _timeframe_bull(bars_1d, index, fast=int(params.get("daily_fast", 50)), slow=int(params.get("daily_slow", 200)))
    if bool(params.get("use_weekly_confirm", False)):
        bull = bull & _timeframe_bull(bars_1w, index, fast=int(params.get("weekly_fast", 10)), slow=int(params.get("weekly_slow", 30)))
    if bool(params.get("use_monthly_confirm", False)):
        bull = bull & _timeframe_bull(bars_1mo, index, fast=int(params.get("monthly_fast", 3)), slow=int(params.get("monthly_slow", 10)))
    return bull.astype(bool)


def _trend_context_bear(
    bars_1d: pd.DataFrame,
    index: pd.DatetimeIndex,
    *,
    params: Mapping[str, Any],
    bars_1w: pd.DataFrame | None = None,
    bars_1mo: pd.DataFrame | None = None,
) -> pd.Series:
    bear = _timeframe_bear(bars_1d, index, fast=int(params.get("daily_fast", 50)), slow=int(params.get("daily_slow", 200)))
    if bool(params.get("use_weekly_confirm", False)):
        bear = bear & _timeframe_bear(bars_1w, index, fast=int(params.get("weekly_fast", 10)), slow=int(params.get("weekly_slow", 30)))
    if bool(params.get("use_monthly_confirm", False)):
        bear = bear & _timeframe_bear(bars_1mo, index, fast=int(params.get("monthly_fast", 3)), slow=int(params.get("monthly_slow", 10)))
    return bear.astype(bool)


def _trend_context_not_bear(
    bars_1d: pd.DataFrame,
    index: pd.DatetimeIndex,
    *,
    params: Mapping[str, Any],
    bars_1w: pd.DataFrame | None = None,
    bars_1mo: pd.DataFrame | None = None,
) -> pd.Series:
    not_bear = _timeframe_not_bear(bars_1d, index, fast=int(params.get("daily_fast", 50)), slow=int(params.get("daily_slow", 200)))
    if bool(params.get("use_weekly_confirm", False)):
        not_bear = not_bear & _timeframe_not_bear(bars_1w, index, fast=int(params.get("weekly_fast", 10)), slow=int(params.get("weekly_slow", 30)))
    if bool(params.get("use_monthly_confirm", False)):
        not_bear = not_bear & _timeframe_not_bear(bars_1mo, index, fast=int(params.get("monthly_fast", 3)), slow=int(params.get("monthly_slow", 10)))
    return not_bear.astype(bool)


def _timeframe_bull(frame: pd.DataFrame | None, index: pd.DatetimeIndex, *, fast: int, slow: int) -> pd.Series:
    if frame is None or frame.empty or "close" not in frame:
        return pd.Series(False, index=index)
    close = frame["close"].astype(float)
    fast_ema = _ema(close, fast)
    slow_ema = _ema(close, slow)
    return ((fast_ema > slow_ema) & (close > slow_ema)).reindex(index, method="ffill").fillna(False).astype(bool)


def _timeframe_bear(frame: pd.DataFrame | None, index: pd.DatetimeIndex, *, fast: int, slow: int) -> pd.Series:
    if frame is None or frame.empty or "close" not in frame:
        return pd.Series(False, index=index)
    close = frame["close"].astype(float)
    fast_ema = _ema(close, fast)
    slow_ema = _ema(close, slow)
    return ((fast_ema < slow_ema) & (close < slow_ema)).reindex(index, method="ffill").fillna(False).astype(bool)


def _timeframe_not_bear(frame: pd.DataFrame | None, index: pd.DatetimeIndex, *, fast: int, slow: int) -> pd.Series:
    if frame is None or frame.empty or "close" not in frame:
        return pd.Series(False, index=index)
    return (~_timeframe_bear(frame, index, fast=fast, slow=slow)).astype(bool)


def _daily_bull(bars_1d: pd.DataFrame, index: pd.DatetimeIndex, *, fast: int, slow: int) -> pd.Series:
    return _timeframe_bull(bars_1d, index, fast=fast, slow=slow)


def _daily_bear(bars_1d: pd.DataFrame, index: pd.DatetimeIndex, *, fast: int, slow: int) -> pd.Series:
    return _timeframe_bear(bars_1d, index, fast=fast, slow=slow)


def _daily_not_bear(bars_1d: pd.DataFrame, index: pd.DatetimeIndex, *, fast: int, slow: int) -> pd.Series:
    return _timeframe_not_bear(bars_1d, index, fast=fast, slow=slow)


def _market_regime_labels(bars_4h: pd.DataFrame) -> pd.Series:
    close = bars_4h["close"].astype(float)
    fast = _ema(close, 50)
    slow = _ema(close, 200)
    vol_ok = _high_vol_ok(close, window=60)
    labels = pd.Series("sideways", index=close.index)
    labels[(fast > slow) & (close > slow)] = "bull_trend"
    labels[(fast < slow) & (close < slow)] = "bear_risk"
    labels[~vol_ok] = "high_volatility"
    return labels


def _ema_ribbon_long(close: pd.Series) -> pd.Series:
    return (_ema(close, 21) > _ema(close, 50)) & (_ema(close, 50) > _ema(close, 100)) & (_ema(close, 100) > _ema(close, 200)) & (close > _ema(close, 200))


def _ema_ribbon_bear(close: pd.Series) -> pd.Series:
    return (_ema(close, 21) < _ema(close, 50)) & (_ema(close, 50) < _ema(close, 100)) & (_ema(close, 100) < _ema(close, 200)) & (close < _ema(close, 200))


def _long_derivatives_risk_ok(
    derivatives: pd.DataFrame,
    index: pd.DatetimeIndex,
    *,
    use_funding: bool,
    use_oi: bool,
    use_long_short: bool,
) -> pd.Series:
    ok = pd.Series(True, index=index)
    if use_funding:
        funding = _numeric_col(derivatives, "funding_rate", index)
        cap = funding.rolling(180, min_periods=24).quantile(0.80).shift(1)
        ok = ok & ((funding <= cap) | cap.isna() | funding.isna())
    if use_oi:
        oi = _numeric_col(derivatives, "open_interest_usd", index)
        oi_z = _rolling_z(oi.diff(), window=72)
        ok = ok & ((oi_z <= 2.0) | oi_z.isna())
    if use_long_short:
        long_short = _numeric_col(derivatives, "long_short_ratio", index)
        cap = long_short.rolling(180, min_periods=24).quantile(0.85).shift(1)
        ok = ok & ((long_short <= cap) | cap.isna() | long_short.isna())
    return ok.fillna(True).astype(bool)


def _short_derivatives_risk_ok(derivatives: pd.DataFrame, index: pd.DatetimeIndex, *, use_funding: bool, use_squeeze: bool) -> pd.Series:
    ok = pd.Series(True, index=index)
    if use_funding:
        funding = _numeric_col(derivatives, "funding_rate", index)
        floor = funding.rolling(180, min_periods=24).quantile(0.20).shift(1)
        ok = ok & ((funding >= floor) | floor.isna() | funding.isna())
    if use_squeeze:
        long_short = _numeric_col(derivatives, "long_short_ratio", index)
        floor = long_short.rolling(180, min_periods=24).quantile(0.20).shift(1)
        ok = ok & ((long_short >= floor) | floor.isna() | long_short.isna())
    return ok.fillna(True).astype(bool)


def _numeric_col(frame: pd.DataFrame, column: str, index: pd.DatetimeIndex) -> pd.Series:
    if column not in frame:
        return pd.Series(math.nan, index=index)
    return pd.to_numeric(frame[column], errors="coerce").reindex(index)


def _to_4h(series: pd.Series, index: pd.DatetimeIndex) -> pd.Series:
    return series.sort_index().reindex(index, method="ffill").fillna(0.0)


def _high_vol_ok(close: pd.Series, *, window: int) -> pd.Series:
    vol = close.pct_change().rolling(window).std(ddof=0)
    cap = vol.rolling(window * 4, min_periods=window).quantile(0.85).shift(1)
    return ((vol <= cap) | cap.isna()).fillna(True).astype(bool)


def _atr(bars: pd.DataFrame, window: int) -> pd.Series:
    high = bars["high"].astype(float)
    low = bars["low"].astype(float)
    close = bars["close"].astype(float)
    previous_close = close.shift(1)
    tr = pd.concat([(high - low).abs(), (high - previous_close).abs(), (low - previous_close).abs()], axis=1).max(axis=1)
    return tr.rolling(window).mean()


def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.astype(float).ewm(span=span, adjust=False).mean()


def _rolling_z(values: pd.Series, *, window: int) -> pd.Series:
    mean = values.rolling(window).mean()
    std = values.rolling(window).std(ddof=0)
    return (values - mean) / std.replace(0.0, math.nan)


def _stateful_long_flat(entry: pd.Series, exit_signal: pd.Series) -> pd.Series:
    out: list[float] = []
    in_position = False
    for ent, ex in zip(entry.fillna(False).astype(bool), exit_signal.fillna(False).astype(bool)):
        if in_position and ex:
            in_position = False
        if not in_position and ent:
            in_position = True
        out.append(1.0 if in_position else 0.0)
    return pd.Series(out, index=entry.index)


def _stateful_short_flat(entry: pd.Series, exit_signal: pd.Series) -> pd.Series:
    long_like = _stateful_long_flat(entry, exit_signal)
    return -1.0 * long_like


def _stateful_long_short(long_entry: pd.Series, long_exit: pd.Series, short_entry: pd.Series, short_exit: pd.Series) -> pd.Series:
    out: list[float] = []
    position = 0.0
    for le, lx, se, sx in zip(
        long_entry.fillna(False).astype(bool),
        long_exit.fillna(False).astype(bool),
        short_entry.fillna(False).astype(bool),
        short_exit.fillna(False).astype(bool),
    ):
        if position > 0.0 and (lx or se):
            position = 0.0
        if position < 0.0 and (sx or le):
            position = 0.0
        if position == 0.0:
            if le and not se:
                position = 1.0
            elif se and not le:
                position = -1.0
        out.append(position)
    return pd.Series(out, index=long_entry.index)


def _stateful_long_flat_with_trailing(entry: pd.Series, exit_signal: pd.Series, *, close: pd.Series, atr: pd.Series, atr_mult: float) -> pd.Series:
    out: list[float] = []
    in_position = False
    high_since_entry = math.nan
    for ts, ent, ex in zip(close.index, entry.fillna(False).astype(bool), exit_signal.fillna(False).astype(bool)):
        price = float(close.loc[ts])
        current_atr = float(atr.loc[ts]) if ts in atr.index and math.isfinite(float(atr.loc[ts])) else math.nan
        if in_position:
            high_since_entry = max(high_since_entry, price) if math.isfinite(high_since_entry) else price
            if math.isfinite(current_atr) and price < high_since_entry - atr_mult * current_atr:
                ex = True
        if in_position and ex:
            in_position = False
            high_since_entry = math.nan
        if not in_position and ent:
            in_position = True
            high_since_entry = price
        out.append(1.0 if in_position else 0.0)
    return pd.Series(out, index=close.index)


def _cost_stress_bps(base_cost_bps: float) -> list[float]:
    return [float(base_cost_bps), float(base_cost_bps) * 2.0, float(base_cost_bps) * 5.0]


def _family_context() -> list[dict[str, str]]:
    return [
        {"family_id": "multi_tf_trend_confirm", "idea": "daily direction, 4h entry, 1h denoise exit"},
        {"family_id": "multi_tf_turtle", "idea": "daily-filtered Donchian breakout with ATR and crowding filters"},
        {"family_id": "trend_pullback_reentry", "idea": "buy pullbacks inside a higher-timeframe uptrend"},
        {"family_id": "multi_tf_squeeze_breakout", "idea": "trade breakouts after volatility compression"},
        {"family_id": "regime_router", "idea": "route simple rules by trend, sideways, high-vol and bear states"},
        {"family_id": "derivatives_risk_filtered_trend", "idea": "trend signal with funding, OI and long-short risk filters"},
        {"family_id": "short_research_branch", "idea": "research-only short and long-short variants, excluded from normal shortlist"},
        {"family_id": "vote_ensemble", "idea": "simple explainable 3-of-5 or 4-of-5 rule vote"},
    ]


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
    warnings = ["btc_multi_timeframe_rule_lab_research_only_no_paper_no_live"]
    if any(str(row.get("branch")) == "short_research" for row in rows):
        warnings.append("btc_multi_timeframe_rule_lab_short_branch_watchlist_only")
    if any(float(row.get("best_positive_year_share", 0.0)) > 0.70 for row in rows):
        warnings.append("btc_multi_timeframe_rule_lab_some_candidates_year_concentrated")
    if any(str(row.get("family_id")) == "derivatives_risk_filtered_trend" for row in rows):
        warnings.append("btc_multi_timeframe_rule_lab_derivatives_filters_require_timestamp_review")
    return warnings


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
        "final_equity": float(initial_capital),
        "average_exposure": 0.0,
        "average_net_exposure": 0.0,
        "bars_with_exposure": 0,
        "long_bar_count": 0,
        "short_bar_count": 0,
        "turnover": 0.0,
        "exposure_change_count": 0,
        "fee_return_pct": 0.0,
        "winning_exposed_bar_pct": 0.0,
    }


def _grid_fieldnames() -> list[str]:
    return [
        "candidate_id",
        "family_id",
        "variant_id",
        "branch",
        "direction_policy",
        "variant_kind",
        "optimization_stage",
        "optimization_components",
        "label",
        "total_return_pct",
        "annual_return_pct",
        "max_drawdown_pct",
        "max_drawdown_abs_pct",
        "profit_factor",
        "sharpe_ratio",
        "average_exposure",
        "average_net_exposure",
        "turnover",
        "fee_return_pct",
        "walk_forward_pass_rate",
        "annual_regime_pass_rate",
        "market_regime_pass_rate",
        "best_positive_year_share",
        "latest_segment_passed",
        "cost_survival_rate",
        "score",
        "retention_decision",
        "paper_queue_write_allowed",
        "live_unlock_allowed",
    ]


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


def _round(value: float, digits: int = 6) -> float:
    if value is None or not math.isfinite(float(value)):
        return 0.0
    return round(float(value), digits)


def _round_mapping(metrics: Mapping[str, Any]) -> dict[str, Any]:
    return {str(key): (_round(value) if isinstance(value, float) else value) for key, value in metrics.items()}


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _portable_path(path: Path) -> str:
    return str(path).replace("\\", "/")


def _ts(value: Any) -> str:
    return pd.Timestamp(value).isoformat()


def _git_commit() -> str:
    import subprocess

    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return "unknown"
