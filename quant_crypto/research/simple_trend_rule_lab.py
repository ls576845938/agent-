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
import numpy as np


SCHEMA_VERSION = "btc_simple_trend_rule_lab_v1"
SYMBOL = "BTCUSDT"
EXCHANGE = "binance_spot"
BASE_INTERVAL = "4h"
SOURCE_INTERVAL = "1h"
DEFAULT_MARKET_DB = Path("data/market_data.sqlite")
DEFAULT_DERIVATIVES_ROWS = Path(
    "data/external/btc_derivatives_sentiment/free_sources/free_public_btcusdt_1h_latest/"
    "derivatives_sentiment_1h.json"
)
DEFAULT_OUTPUT_DIR = Path("artifacts/btc_simple_trend_rule_lab/latest")
DEFAULT_REPORT_PATH = DEFAULT_OUTPUT_DIR / "btc_simple_trend_rule_lab_report.json"
DEFAULT_GRID_PATH = DEFAULT_OUTPUT_DIR / "btc_simple_trend_rule_lab_grid.csv"
DEFAULT_MARKDOWN_PATH = DEFAULT_OUTPUT_DIR / "btc_simple_trend_rule_lab_summary_cn.md"

INITIAL_CAPITAL = 25_000.0
BASE_COST_BPS = 10.0
COST_STRESS_BPS = [5.0, 10.0, 25.0, 50.0, 100.0]
BARS_PER_YEAR = {"4h": 6 * 365, "1d": 365}
MIN_4H_BARS = 900


@dataclass(frozen=True)
class TrendRuleSpec:
    family_id: str
    variant_id: str
    label: str
    params: dict[str, Any]
    optimized: bool
    optimization_stage: str
    optimization_components: list[str]
    optimization_notes: list[str]

    @property
    def candidate_id(self) -> str:
        raw = {
            "family_id": self.family_id,
            "variant_id": self.variant_id,
            "params": self.params,
            "optimized": self.optimized,
            "optimization_stage": self.optimization_stage,
            "optimization_components": self.optimization_components,
        }
        digest = hashlib.sha1(json.dumps(raw, sort_keys=True).encode("utf-8")).hexdigest()[:10]
        return f"btc_{BASE_INTERVAL}_{self.variant_id}_{digest}"


@dataclass
class EvaluatedRule:
    spec: TrendRuleSpec
    raw_signal: pd.Series
    exposure: pd.Series
    returns: pd.Series
    turnover: pd.Series
    cost: pd.Series
    equity: pd.Series
    metrics: dict[str, Any]


def build_btc_simple_trend_rule_lab(
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
    derivatives_4h = align_derivatives_to_index(derivatives_rows_path, bars_4h.index)
    specs = simple_trend_rule_specs()
    blockers: list[str] = []
    if len(bars_4h) < MIN_4H_BARS:
        blockers.append("btc_simple_trend_rule_lab_insufficient_4h_bars")

    buy_hold = _evaluate_buy_hold(bars_4h, initial_capital=initial_capital, cost_bps=base_cost_bps)
    evaluated = [
        evaluate_rule(
            spec,
            bars_4h=bars_4h,
            bars_1d=bars_1d,
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
            walk_forward=walk_forward_summary(item, bars_4h=bars_4h, initial_capital=initial_capital, cost_bps=base_cost_bps),
            regime=regime_summary(item, bars_4h=bars_4h, initial_capital=initial_capital, cost_bps=base_cost_bps),
            cost_stress=cost_stress_summary(
                item.spec,
                bars_4h=bars_4h,
                bars_1d=bars_1d,
                derivatives_4h=derivatives_4h,
                initial_capital=initial_capital,
            ),
        )
        for item in evaluated
    ]
    ranked = sorted(rows, key=lambda row: (-float(row["score"]), str(row["candidate_id"])))
    stepwise = _family_stepwise_comparison(rows)
    shortlist = _extended_research_shortlist(ranked)
    rejected = [row for row in ranked if row["candidate_id"] not in {item["candidate_id"] for item in shortlist}]
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated.isoformat(),
        "status": "blocked" if blockers else "complete_research_only",
        "decision": "btc_simple_trend_rule_lab_research_only_shortlist_no_paper_no_live",
        "scope": "btc_simple_trend_rules_original_and_optimized_research_lab",
        "code_commit": _git_commit(),
        "input": {
            "market_db_path": _portable_path(market_db_path),
            "derivatives_rows_path": _portable_path(derivatives_rows_path),
            "source_interval": SOURCE_INTERVAL,
            "base_interval": BASE_INTERVAL,
            "symbol": SYMBOL,
            "exchange": EXCHANGE,
            "market_1h_rows": int(len(source_1h)),
            "bar_4h_rows": int(len(bars_4h)),
            "bar_1d_rows": int(len(bars_1d)),
            "bar_4h_start": _ts(bars_4h.index.min()) if len(bars_4h) else None,
            "bar_4h_end": _ts(bars_4h.index.max()) if len(bars_4h) else None,
            "derivatives_visible_rows": int(derivatives_4h["open_interest_usd"].notna().sum())
            if "open_interest_usd" in derivatives_4h
            else 0,
            "derivatives_available_time_rule": "derivatives features aligned by available_time <= 4h decision_time",
            "market_completed_bar_rule": "1h bars are complete; 4h/1d bars are aggregated from complete 1h bars",
        },
        "validation_design": {
            "candidate_family_count": 6,
            "candidate_count": len(specs),
            "variant_policy": "each family has an original version, single-component optimization variants, and pre-declared combination variants",
            "selected_by": "score with positive-return, drawdown, walk-forward, regime, cost-stress and concentration penalties",
            "execution_rule": "signal generated after 4h bar close; exposure effective from next 4h bar",
            "cost_model": {
                "base_cost_bps": float(base_cost_bps),
                "stress_cost_bps": COST_STRESS_BPS,
            },
            "no_lookahead_policy": [
                "price features use completed bars only",
                "derivatives features require available_time <= decision_time",
                "all exposures are shifted by one 4h bar after signal calculation",
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
            "reason": "simple trend rule lab is research-only; retained candidates require separate manual review",
        },
        "buy_hold_baseline": _round_mapping(buy_hold.metrics),
        "families": _family_context(),
        "family_stepwise_comparison": stepwise,
        "comparison_rows": ranked,
        "extended_research_shortlist": shortlist,
        "rejected_or_deferred": rejected,
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
    _write_text(markdown_path, render_simple_trend_rule_lab_markdown(report))
    return report


def load_market_1h(path: Path) -> pd.DataFrame:
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
            [EXCHANGE, SYMBOL, SOURCE_INTERVAL],
        ).fetchall()
    finally:
        conn.close()
    if not rows:
        raise ValueError(f"no {SYMBOL} {SOURCE_INTERVAL} rows in {path}")
    frame = pd.DataFrame(rows, columns=["open_time", "close_time", "open", "high", "low", "close", "volume"])
    frame["open_time"] = pd.to_datetime(frame["open_time"], utc=True)
    frame["close_time"] = pd.to_datetime(frame["close_time"], utc=True)
    for col in ["open", "high", "low", "close", "volume"]:
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    frame = frame.dropna(subset=["open", "high", "low", "close", "volume"]).sort_values("close_time")
    frame = frame.set_index("close_time")
    return frame[["open_time", "open", "high", "low", "close", "volume"]]


def aggregate_ohlcv(frame_1h: pd.DataFrame, *, interval_hours: int) -> pd.DataFrame:
    regular = _aggregate_regular_ohlcv(frame_1h, interval_hours=interval_hours)
    if regular is not None:
        return regular
    rows: list[dict[str, Any]] = []
    for start, chunk in frame_1h.groupby(pd.Grouper(key="open_time", freq=f"{interval_hours}h")):
        if len(chunk) != interval_hours:
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


def _aggregate_regular_ohlcv(frame: pd.DataFrame, *, interval_hours: int) -> pd.DataFrame | None:
    """Exact fast path for finite, contiguous UTC float64 hourly input.

    Unusual/irregular input keeps the established pandas implementation. There
    is no resampling, missing-bar fill, partial-period inclusion or summation
    policy change: each complete block uses the same NumPy reduction as Series.
    """
    columns = ["open", "high", "low", "close", "volume"]
    if (not isinstance(interval_hours, int) or interval_hours <= 0 or 24 % interval_hours
            or frame.empty or not set(["open_time", *columns]).issubset(frame.columns)
            or not isinstance(frame.index, pd.DatetimeIndex) or str(frame.index.tz) != "UTC"
            or not frame.index.is_monotonic_increasing or frame.index.has_duplicates
            or any(frame[name].dtype != np.dtype("float64") for name in columns)):
        return None
    opened = pd.DatetimeIndex(frame["open_time"])
    if (str(opened.tz) != "UTC" or opened.hasnans
            or not opened.equals(opened.floor("h"))
            or (len(opened) > 1 and not np.all(np.diff(opened.as_unit("ns").asi8) == 3_600_000_000_000))):
        return None
    values = {name: frame[name].to_numpy() for name in columns}
    if not all(np.isfinite(value).all() for value in values.values()):
        return None
    offset = (-opened[0].hour) % interval_hours
    count = max(0, (len(frame) - offset) // interval_hours)
    if not count:
        return pd.DataFrame(columns=["open_time", *columns])
    end = offset + count * interval_hours
    blocks = {name: values[name][offset:end].reshape(count, interval_hours) for name in columns}
    # Construct from Timestamp lists just as the old per-group rows do, so
    # pandas resolution, timezone and the close_time index name also match.
    output = pd.DataFrame({
        "open_time": list(opened[offset:end:interval_hours]),
        "close_time": list(frame.index[offset + interval_hours - 1:end:interval_hours]),
        "open": blocks["open"][:, 0], "high": blocks["high"].max(axis=1),
        "low": blocks["low"].min(axis=1), "close": blocks["close"][:, -1],
        "volume": blocks["volume"].sum(axis=1),
    })
    output = output.set_index(pd.to_datetime(output["close_time"], utc=True))
    return output[["open_time", *columns]].sort_index()


def align_derivatives_to_index(path: Path, index: pd.DatetimeIndex) -> pd.DataFrame:
    columns = [
        "open_interest_usd",
        "funding_rate",
        "long_short_ratio",
        "top_trader_long_short_ratio",
        "taker_buy_sell_ratio",
    ]
    empty = pd.DataFrame(index=index, columns=columns, dtype=float)
    if not path.exists() or len(index) == 0:
        return empty
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_rows = payload.get("rows", payload) if isinstance(payload, Mapping) else payload
    rows = [row for row in raw_rows if isinstance(row, Mapping)]
    if not rows:
        return empty
    frame = pd.DataFrame(rows)
    if "available_time" not in frame:
        return empty
    frame["available_time"] = pd.to_datetime(frame["available_time"], utc=True, errors="coerce")
    frame = frame.dropna(subset=["available_time"]).sort_values("available_time")
    for col in columns:
        frame[col] = pd.to_numeric(frame[col], errors="coerce") if col in frame else math.nan
    left = pd.DataFrame({"decision_time": index}).sort_values("decision_time")
    right = frame[["available_time", *columns]].sort_values("available_time")
    merged = pd.merge_asof(left, right, left_on="decision_time", right_on="available_time", direction="backward")
    merged = merged.set_index(pd.DatetimeIndex(index))
    return merged[columns]


def simple_trend_rule_specs() -> list[TrendRuleSpec]:
    def spec(
        family_id: str,
        variant_id: str,
        label: str,
        params: dict[str, Any],
        *,
        stage: str,
        components: list[str],
        notes: list[str],
    ) -> TrendRuleSpec:
        return TrendRuleSpec(
            family_id=family_id,
            variant_id=variant_id,
            label=label,
            params=params,
            optimized=stage != "original",
            optimization_stage=stage,
            optimization_components=components,
            optimization_notes=notes,
        )

    return [
        spec(
            "donchian_turtle",
            "donchian_turtle_original",
            "Donchian turtle 20d/10d breakout",
            {"signal_type": "donchian", "entry_window": 120, "exit_window": 60},
            stage="original",
            components=[],
            notes=["classic turtle-like 20 day breakout translated to 4h bars"],
        ),
        spec(
            "donchian_turtle",
            "donchian_turtle_slow_breakout",
            "Donchian turtle slower 55d/20d breakout",
            {"signal_type": "donchian", "entry_window": 330, "exit_window": 120},
            stage="single_slow_breakout",
            components=["slower_entry_exit_window"],
            notes=["single optimization: slower breakout/exit windows"],
        ),
        spec(
            "donchian_turtle",
            "donchian_turtle_daily_confirm",
            "Donchian turtle 20d/10d with 1D trend confirm",
            {"signal_type": "donchian_confirmed", "entry_window": 120, "exit_window": 60, "daily_ma": 100},
            stage="single_daily_confirm",
            components=["daily_trend_confirmation"],
            notes=["single optimization: daily trend confirmation"],
        ),
        spec(
            "donchian_turtle",
            "donchian_turtle_slow_daily_confirm",
            "Donchian turtle 55d/20d with 1D trend confirm",
            {"signal_type": "donchian_confirmed", "entry_window": 330, "exit_window": 120, "daily_ma": 100},
            stage="combo_slow_plus_daily_confirm",
            components=["slower_entry_exit_window", "daily_trend_confirmation"],
            notes=["combination: slower windows plus daily trend confirmation"],
        ),
        spec(
            "atr_channel",
            "atr_channel_original",
            "ATR channel breakout symmetric",
            {"signal_type": "atr_channel", "ma_window": 96, "atr_window": 20, "entry_k": 1.5, "exit_k": 1.5},
            stage="original",
            components=[],
            notes=["same logic family as current 4h ATR channel candidate"],
        ),
        spec(
            "atr_channel",
            "atr_channel_fast_exit",
            "ATR channel breakout with faster exit",
            {"signal_type": "atr_channel", "ma_window": 96, "atr_window": 20, "entry_k": 1.5, "exit_k": 0.75},
            stage="single_fast_exit",
            components=["faster_exit_band"],
            notes=["single optimization: faster exit after trend weakens"],
        ),
        spec(
            "atr_channel",
            "atr_channel_daily_confirm",
            "ATR channel breakout with 1D trend confirm",
            {"signal_type": "atr_channel_confirmed", "ma_window": 96, "atr_window": 20, "entry_k": 1.5, "exit_k": 1.5, "daily_ma": 100},
            stage="single_daily_confirm",
            components=["daily_trend_confirmation"],
            notes=["single optimization: daily trend confirmation"],
        ),
        spec(
            "atr_channel",
            "atr_channel_fast_exit_daily_confirm",
            "ATR channel breakout with faster exit and 1D trend confirm",
            {"signal_type": "atr_channel_confirmed", "ma_window": 96, "atr_window": 20, "entry_k": 1.5, "exit_k": 0.75, "daily_ma": 100},
            stage="combo_fast_exit_plus_daily_confirm",
            components=["faster_exit_band", "daily_trend_confirmation"],
            notes=["combination: asymmetric exit plus daily trend confirmation"],
        ),
        spec(
            "supertrend",
            "supertrend_original",
            "4h SuperTrend ATR 10 x 3",
            {"signal_type": "supertrend", "atr_window": 10, "multiplier": 3.0},
            stage="original",
            components=[],
            notes=["standard ATR trailing trend line"],
        ),
        spec(
            "supertrend",
            "supertrend_tighter",
            "4h SuperTrend tighter ATR 10 x 2",
            {"signal_type": "supertrend", "atr_window": 10, "multiplier": 2.0},
            stage="single_tighter_multiplier",
            components=["tighter_supertrend_multiplier"],
            notes=["single optimization: tighter trailing trend line"],
        ),
        spec(
            "supertrend",
            "supertrend_daily_confirm",
            "4h SuperTrend with 1D SuperTrend confirmation",
            {"signal_type": "supertrend_dual", "atr_window": 10, "multiplier": 3.0, "daily_atr_window": 10, "daily_multiplier": 3.0},
            stage="single_daily_supertrend_confirm",
            components=["daily_supertrend_confirmation"],
            notes=["single optimization: higher timeframe confirmation"],
        ),
        spec(
            "supertrend",
            "supertrend_tighter_daily_confirm",
            "4h tighter SuperTrend with 1D confirmation",
            {"signal_type": "supertrend_dual", "atr_window": 10, "multiplier": 2.0, "daily_atr_window": 10, "daily_multiplier": 3.0},
            stage="combo_tighter_plus_daily_confirm",
            components=["tighter_supertrend_multiplier", "daily_supertrend_confirmation"],
            notes=["combination: tighter 4h line plus 1d confirmation"],
        ),
        spec(
            "squeeze_breakout",
            "squeeze_breakout_original",
            "Bollinger/Keltner squeeze breakout",
            {"signal_type": "squeeze_breakout", "bb_window": 20, "bb_k": 2.0, "kc_window": 20, "kc_k": 1.5, "breakout_window": 60, "exit_ema": 40},
            stage="original",
            components=[],
            notes=["trade only after volatility compression releases upward"],
        ),
        spec(
            "squeeze_breakout",
            "squeeze_breakout_volume_confirm",
            "Squeeze breakout with volume confirmation",
            {
                "signal_type": "squeeze_breakout_confirmed",
                "bb_window": 20,
                "bb_k": 2.0,
                "kc_window": 20,
                "kc_k": 1.5,
                "breakout_window": 60,
                "exit_ema": 40,
                "volume_window": 60,
                "min_volume_ratio": 1.05,
                "min_atr_ratio": 0.0,
            },
            stage="single_volume_confirm",
            components=["volume_confirmation"],
            notes=["single optimization: breakout requires above-median volume"],
        ),
        spec(
            "squeeze_breakout",
            "squeeze_breakout_atr_expand",
            "Squeeze breakout with ATR expansion confirmation",
            {
                "signal_type": "squeeze_breakout_confirmed",
                "bb_window": 20,
                "bb_k": 2.0,
                "kc_window": 20,
                "kc_k": 1.5,
                "breakout_window": 60,
                "exit_ema": 40,
                "volume_window": 60,
                "min_volume_ratio": 0.0,
                "min_atr_ratio": 1.0,
            },
            stage="single_atr_expansion_confirm",
            components=["atr_expansion_confirmation"],
            notes=["single optimization: breakout requires ATR expansion"],
        ),
        spec(
            "squeeze_breakout",
            "squeeze_breakout_volume_atr_confirm",
            "Squeeze breakout with volume and ATR expansion confirmation",
            {
                "signal_type": "squeeze_breakout_confirmed",
                "bb_window": 20,
                "bb_k": 2.0,
                "kc_window": 20,
                "kc_k": 1.5,
                "breakout_window": 60,
                "exit_ema": 40,
                "volume_window": 60,
                "min_volume_ratio": 1.05,
                "min_atr_ratio": 1.0,
            },
            stage="combo_volume_plus_atr_expansion",
            components=["volume_confirmation", "atr_expansion_confirmation"],
            notes=["combination: volume plus ATR expansion confirmation"],
        ),
        spec(
            "ma_ribbon",
            "ma_ribbon_original",
            "EMA ribbon trend filter",
            {"signal_type": "ma_ribbon", "ema_fast": 21, "ema_mid": 50, "ema_slow": 100, "ema_floor": 200},
            stage="original",
            components=[],
            notes=["simple multi-EMA trend alignment"],
        ),
        spec(
            "ma_ribbon",
            "ma_ribbon_daily_confirm",
            "EMA ribbon with 1D trend confirmation",
            {"signal_type": "ma_ribbon_modular", "ema_fast": 21, "ema_mid": 50, "ema_slow": 100, "ema_floor": 200, "daily_fast": 50, "daily_slow": 200, "vol_window": 60, "use_daily_confirm": True, "use_vol_filter": False},
            stage="single_daily_confirm",
            components=["daily_trend_confirmation"],
            notes=["single optimization: daily EMA trend confirmation"],
        ),
        spec(
            "ma_ribbon",
            "ma_ribbon_vol_filter",
            "EMA ribbon with high-volatility chop filter",
            {"signal_type": "ma_ribbon_modular", "ema_fast": 21, "ema_mid": 50, "ema_slow": 100, "ema_floor": 200, "daily_fast": 50, "daily_slow": 200, "vol_window": 60, "use_daily_confirm": False, "use_vol_filter": True},
            stage="single_vol_filter",
            components=["high_volatility_chop_filter"],
            notes=["single optimization: avoid extreme high-volatility regimes"],
        ),
        spec(
            "ma_ribbon",
            "ma_ribbon_daily_vol_filter",
            "EMA ribbon with 1D trend and volatility filter",
            {"signal_type": "ma_ribbon_modular", "ema_fast": 21, "ema_mid": 50, "ema_slow": 100, "ema_floor": 200, "daily_fast": 50, "daily_slow": 200, "vol_window": 60, "use_daily_confirm": True, "use_vol_filter": True},
            stage="combo_daily_confirm_plus_vol_filter",
            components=["daily_trend_confirmation", "high_volatility_chop_filter"],
            notes=["combination: daily trend confirmation plus volatility filter"],
        ),
        spec(
            "oi_confirmed_atr_breakout",
            "oi_confirmed_atr_original",
            "ATR channel breakout confirmed by rising open interest",
            {"signal_type": "oi_atr_breakout", "ma_window": 96, "atr_window": 20, "entry_k": 1.5, "exit_k": 1.5, "oi_delta_bars": 6},
            stage="original",
            components=[],
            notes=["price breakout must be confirmed by 24h open-interest increase"],
        ),
        spec(
            "oi_confirmed_atr_breakout",
            "oi_confirmed_atr_fast_exit",
            "OI-confirmed ATR breakout with faster exit",
            {
                "signal_type": "oi_atr_breakout_modular",
                "ma_window": 96,
                "atr_window": 20,
                "entry_k": 1.5,
                "exit_k": 0.75,
                "oi_delta_bars": 6,
                "rolling_filter_window": 180,
                "use_funding_filter": False,
                "use_long_short_filter": False,
            },
            stage="single_fast_exit",
            components=["faster_exit_band"],
            notes=["single optimization: faster exit"],
        ),
        spec(
            "oi_confirmed_atr_breakout",
            "oi_confirmed_atr_funding_filter",
            "OI-confirmed ATR breakout with funding crowding filter",
            {
                "signal_type": "oi_atr_breakout_modular",
                "ma_window": 96,
                "atr_window": 20,
                "entry_k": 1.5,
                "exit_k": 1.5,
                "oi_delta_bars": 6,
                "rolling_filter_window": 180,
                "use_funding_filter": True,
                "use_long_short_filter": False,
            },
            stage="single_funding_filter",
            components=["funding_crowding_filter"],
            notes=["single optimization: avoid high funding crowded longs"],
        ),
        spec(
            "oi_confirmed_atr_breakout",
            "oi_confirmed_atr_longs_short_filter",
            "OI-confirmed ATR breakout with long-short crowding filter",
            {
                "signal_type": "oi_atr_breakout_modular",
                "ma_window": 96,
                "atr_window": 20,
                "entry_k": 1.5,
                "exit_k": 1.5,
                "oi_delta_bars": 6,
                "rolling_filter_window": 180,
                "use_funding_filter": False,
                "use_long_short_filter": True,
            },
            stage="single_long_short_filter",
            components=["long_short_crowding_filter"],
            notes=["single optimization: avoid extreme long-short crowding"],
        ),
        spec(
            "oi_confirmed_atr_breakout",
            "oi_confirmed_atr_all_filters",
            "OI-confirmed ATR breakout with fast exit, funding and crowding filters",
            {
                "signal_type": "oi_atr_breakout_modular",
                "ma_window": 96,
                "atr_window": 20,
                "entry_k": 1.5,
                "exit_k": 0.75,
                "oi_delta_bars": 6,
                "rolling_filter_window": 180,
                "use_funding_filter": True,
                "use_long_short_filter": True,
            },
            stage="combo_fast_exit_plus_funding_plus_long_short",
            components=["faster_exit_band", "funding_crowding_filter", "long_short_crowding_filter"],
            notes=["combination: faster exit plus funding and long-short crowding filters"],
        ),
    ]


def evaluate_rule(
    spec: TrendRuleSpec,
    *,
    bars_4h: pd.DataFrame,
    bars_1d: pd.DataFrame,
    derivatives_4h: pd.DataFrame,
    initial_capital: float,
    cost_bps: float,
) -> EvaluatedRule:
    close = bars_4h["close"].astype(float)
    returns = close.pct_change().fillna(0.0)
    raw = raw_signal(spec, bars_4h=bars_4h, bars_1d=bars_1d, derivatives_4h=derivatives_4h).reindex(close.index)
    raw = raw.fillna(0.0).clip(0.0, 1.0)
    exposure = raw.shift(1).fillna(0.0).clip(0.0, 1.0)
    turnover = exposure.diff().abs().fillna(exposure.abs())
    cost = turnover * (float(cost_bps) / 10_000.0)
    strategy_returns = (exposure * returns - cost).fillna(0.0)
    equity = float(initial_capital) * (1.0 + strategy_returns).cumprod()
    metrics = performance_metrics(
        strategy_returns=strategy_returns,
        equity=equity,
        exposure=exposure,
        turnover=turnover,
        cost=cost,
        interval=BASE_INTERVAL,
        initial_capital=initial_capital,
    )
    return EvaluatedRule(spec, raw, exposure, strategy_returns, turnover, cost, equity, metrics)


def raw_signal(
    spec: TrendRuleSpec,
    *,
    bars_4h: pd.DataFrame,
    bars_1d: pd.DataFrame,
    derivatives_4h: pd.DataFrame,
) -> pd.Series:
    close = bars_4h["close"].astype(float)
    high = bars_4h["high"].astype(float)
    low = bars_4h["low"].astype(float)
    volume = bars_4h["volume"].astype(float)
    params = spec.params
    signal_type = str(params["signal_type"])
    if signal_type == "donchian":
        return _donchian_signal(high=high, low=low, close=close, entry=int(params["entry_window"]), exit_window=int(params["exit_window"]))
    if signal_type == "donchian_confirmed":
        base = _donchian_signal(high=high, low=low, close=close, entry=int(params["entry_window"]), exit_window=int(params["exit_window"]))
        confirm = _daily_ma_confirm(bars_4h.index, bars_1d, ma_window=int(params["daily_ma"]))
        return (base * confirm).clip(0.0, 1.0)
    if signal_type == "atr_channel":
        return _atr_channel_signal(
            high=high,
            low=low,
            close=close,
            ma_window=int(params["ma_window"]),
            atr_window=int(params["atr_window"]),
            entry_k=float(params["entry_k"]),
            exit_k=float(params["exit_k"]),
        )
    if signal_type == "atr_channel_confirmed":
        base = _atr_channel_signal(
            high=high,
            low=low,
            close=close,
            ma_window=int(params["ma_window"]),
            atr_window=int(params["atr_window"]),
            entry_k=float(params["entry_k"]),
            exit_k=float(params["exit_k"]),
        )
        confirm = _daily_ma_confirm(bars_4h.index, bars_1d, ma_window=int(params["daily_ma"]))
        return (base * confirm).clip(0.0, 1.0)
    if signal_type == "supertrend":
        return _supertrend_signal(high=high, low=low, close=close, window=int(params["atr_window"]), multiplier=float(params["multiplier"]))
    if signal_type == "supertrend_dual":
        base = _supertrend_signal(high=high, low=low, close=close, window=int(params["atr_window"]), multiplier=float(params["multiplier"]))
        daily = _supertrend_signal(
            high=bars_1d["high"].astype(float),
            low=bars_1d["low"].astype(float),
            close=bars_1d["close"].astype(float),
            window=int(params["daily_atr_window"]),
            multiplier=float(params["daily_multiplier"]),
        )
        daily_on_4h = daily.reindex(bars_4h.index, method="ffill").fillna(0.0)
        return (base * daily_on_4h).clip(0.0, 1.0)
    if signal_type == "squeeze_breakout":
        return _squeeze_breakout_signal(high=high, low=low, close=close, volume=volume, params=params, confirmed=False)
    if signal_type == "squeeze_breakout_confirmed":
        return _squeeze_breakout_signal(high=high, low=low, close=close, volume=volume, params=params, confirmed=True)
    if signal_type == "ma_ribbon":
        return _ma_ribbon_signal(close=close, params=params)
    if signal_type in {"ma_ribbon_confirmed", "ma_ribbon_modular"}:
        return _ma_ribbon_modular_signal(close=close, bars_1d=bars_1d, params=params)
    if signal_type == "oi_atr_breakout":
        base = _atr_channel_signal(
            high=high,
            low=low,
            close=close,
            ma_window=int(params["ma_window"]),
            atr_window=int(params["atr_window"]),
            entry_k=float(params["entry_k"]),
            exit_k=float(params["exit_k"]),
        )
        oi = pd.to_numeric(derivatives_4h.get("open_interest_usd"), errors="coerce")
        oi_up = (oi.diff(int(params["oi_delta_bars"])) > 0.0).astype(float).reindex(close.index).fillna(0.0)
        return (base * oi_up).clip(0.0, 1.0)
    if signal_type in {"oi_atr_breakout_filtered", "oi_atr_breakout_modular"}:
        return _oi_atr_breakout_modular_signal(
            high=high,
            low=low,
            close=close,
            derivatives_4h=derivatives_4h,
            params=params,
        )
    raise ValueError(f"unsupported signal_type: {signal_type}")


def performance_metrics(
    *,
    strategy_returns: pd.Series,
    equity: pd.Series,
    exposure: pd.Series,
    turnover: pd.Series,
    cost: pd.Series,
    interval: str,
    initial_capital: float = INITIAL_CAPITAL,
) -> dict[str, Any]:
    if strategy_returns.empty:
        return _empty_metrics()
    initial = float(initial_capital)
    total_return = float(equity.iloc[-1] / initial - 1.0)
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
    nonzero = strategy_returns[exposure > 0.0]
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
        "average_exposure": _round(float(exposure.mean())),
        "bars_with_exposure": int((exposure > 0.0).sum()),
        "turnover": _round(float(turnover.sum())),
        "exposure_change_count": int((turnover > 1e-12).sum()),
        "fee_return_pct": _round(float(cost.sum()) * 100.0),
        "winning_exposed_bar_pct": _round(float((nonzero > 0.0).mean()) * 100.0) if len(nonzero) else 0.0,
    }


def walk_forward_summary(
    item: EvaluatedRule,
    *,
    bars_4h: pd.DataFrame,
    initial_capital: float,
    cost_bps: float,
    fold_count: int = 4,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    n = len(item.returns)
    fold_size = max(1, n // fold_count)
    for fold in range(fold_count):
        start = fold * fold_size
        end = n if fold == fold_count - 1 else (fold + 1) * fold_size
        index = item.returns.index[start:end]
        if len(index) < 20:
            continue
        sub_returns = item.returns.loc[index]
        sub_exposure = item.exposure.loc[index]
        sub_turnover = item.turnover.loc[index]
        sub_cost = item.cost.loc[index]
        equity = float(initial_capital) * (1.0 + sub_returns).cumprod()
        metrics = performance_metrics(
            strategy_returns=sub_returns,
            equity=equity,
            exposure=sub_exposure,
            turnover=sub_turnover,
            cost=sub_cost,
            interval=BASE_INTERVAL,
            initial_capital=initial_capital,
        )
        passed = (
            float(metrics["total_return_pct"]) > 0.0
            and float(metrics["profit_factor"]) >= 1.0
            and float(metrics["max_drawdown_abs_pct"]) <= 35.0
            and float(metrics["average_exposure"]) >= 0.05
        )
        rows.append(
            {
                "fold": fold + 1,
                "start": _ts(index.min()),
                "end": _ts(index.max()),
                "row_count": int(len(index)),
                "passed": bool(passed),
                "metrics": metrics,
            }
        )
    pass_rate = sum(1 for row in rows if row["passed"]) / len(rows) if rows else 0.0
    return {
        "fold_count": len(rows),
        "pass_rate": _round(pass_rate),
        "minimum_pass_rate": 0.5,
        "passed": pass_rate >= 0.5 if rows else False,
        "folds": rows,
    }


def regime_summary(
    item: EvaluatedRule,
    *,
    bars_4h: pd.DataFrame,
    initial_capital: float,
    cost_bps: float,
) -> dict[str, Any]:
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
        rows.append(
            {
                "segment": str(year),
                "start": _ts(idx.min()),
                "end": _ts(idx.max()),
                "row_count": int(len(idx)),
                "passed": float(metrics["total_return_pct"]) > 0.0 and float(metrics["profit_factor"]) >= 1.0,
                "metrics": metrics,
            }
        )
    positive = [row for row in rows if float(row["metrics"]["total_return_pct"]) > 0.0]
    pass_rate = sum(1 for row in rows if row["passed"]) / len(rows) if rows else 0.0
    total_positive = sum(max(0.0, float(row["metrics"]["total_return_pct"])) for row in rows)
    best_share = max((max(0.0, float(row["metrics"]["total_return_pct"])) for row in rows), default=0.0) / total_positive if total_positive else 0.0
    return {
        "segment_count": len(rows),
        "positive_segment_count": len(positive),
        "pass_rate": _round(pass_rate),
        "best_positive_year_share": _round(best_share),
        "passed": pass_rate >= 0.5 and best_share <= 0.75 if rows else False,
        "segments": rows,
    }


def cost_stress_summary(
    spec: TrendRuleSpec,
    *,
    bars_4h: pd.DataFrame,
    bars_1d: pd.DataFrame,
    derivatives_4h: pd.DataFrame,
    initial_capital: float,
) -> dict[str, Any]:
    scenarios = []
    for cost_bps in COST_STRESS_BPS:
        item = evaluate_rule(
            spec,
            bars_4h=bars_4h,
            bars_1d=bars_1d,
            derivatives_4h=derivatives_4h,
            initial_capital=initial_capital,
            cost_bps=cost_bps,
        )
        survives = float(item.metrics["total_return_pct"]) > 0.0 and float(item.metrics["profit_factor"]) >= 1.0
        scenarios.append(
            {
                "cost_bps": float(cost_bps),
                "survives": bool(survives),
                "metrics": item.metrics,
            }
        )
    return {
        "scenario_count": len(scenarios),
        "survival_count": sum(1 for row in scenarios if row["survives"]),
        "survival_rate": _round(sum(1 for row in scenarios if row["survives"]) / len(scenarios) if scenarios else 0.0),
        "base_survives": bool(next((row["survives"] for row in scenarios if row["cost_bps"] == BASE_COST_BPS), False)),
        "cost_25bps_survives": bool(next((row["survives"] for row in scenarios if row["cost_bps"] == 25.0), False)),
        "scenarios": scenarios,
    }


def render_simple_trend_rule_lab_markdown(report: Mapping[str, Any]) -> str:
    rows = [dict(row) for row in report.get("comparison_rows", [])]
    shortlist = [dict(row) for row in report.get("extended_research_shortlist", [])]
    lines = [
        "# BTC 简单趋势规则研究实验室",
        "",
        f"- 状态：`{report.get('status')}`",
        f"- 决策：`{report.get('decision')}`",
        f"- 写 paper 队列：`{_mapping(report.get('gate')).get('paper_queue_write_allowed')}`",
        f"- 解锁 live：`{_mapping(report.get('gate')).get('live_unlock_allowed')}`",
        f"- 4H 样本行数：`{_mapping(report.get('input')).get('bar_4h_rows')}`",
        f"- 候选数：`{_mapping(report.get('validation_design')).get('candidate_count')}`",
        "",
        "## 扩展研究短名单",
        "",
    ]
    if not shortlist:
        lines.append("- 当前没有候选进入扩展研究短名单。")
    for row in shortlist:
        lines.append(
            "- "
            f"`{row.get('candidate_id')}`：{row.get('label')}；"
            f"阶段 `{row.get('optimization_stage')}`；"
            f"收益 `{row.get('total_return_pct')}%`，"
            f"回撤 `{row.get('max_drawdown_pct')}%`，"
            f"PF `{row.get('profit_factor')}`，"
            f"walk-forward `{row.get('walk_forward_pass_rate')}`，"
            f"保留状态 `{row.get('retention_decision')}`。"
        )
    lines.extend(["", "## 候选对比", "", "| 排名 | 候选 | 类型 | 优化阶段 | 收益 | 回撤 | PF | WF | 年份集中 | 成本存活 | 决策 |", "|---:|---|---|---|---:|---:|---:|---:|---:|---:|---|"])
    for idx, row in enumerate(rows, start=1):
        lines.append(
            f"| {idx} | `{row.get('candidate_id')}` | `{row.get('variant_kind')}` | "
            f"`{row.get('optimization_stage')}` | "
            f"{row.get('total_return_pct')} | {row.get('max_drawdown_pct')} | {row.get('profit_factor')} | "
            f"{row.get('walk_forward_pass_rate')} | {row.get('best_positive_year_share')} | "
            f"{row.get('cost_survival_rate')} | `{row.get('retention_decision')}` |"
        )
    lines.extend(["", "## 逐步优化对比", ""])
    for family in report.get("family_stepwise_comparison", []):
        variants = [dict(row) for row in family.get("variants", [])]
        best = str(family.get("best_candidate_id"))
        original = variants[0] if variants else {}
        best_row = next((row for row in variants if str(row.get("candidate_id")) == best), {})
        lines.append(
            "- "
            f"`{family.get('family_id')}`：最佳阶段 `{family.get('best_optimization_stage')}`；"
            f"相对原始版收益变化 `{best_row.get('delta_total_return_vs_original_pct')}` pct，"
            f"回撤变化 `{best_row.get('delta_drawdown_abs_vs_original_pct')}` pct，"
            f"score 变化 `{best_row.get('delta_score_vs_original')}`；"
            f"原始版 `{original.get('candidate_id')}`。"
        )
    lines.extend(
        [
            "",
            "## 复核重点",
            "",
            "- 本报告只做简单规则研究筛选，不写 paper 队列，不解锁 live。",
            "- OI 确认类候选必须单独复核 derivatives 可见时间和覆盖窗口。",
            "- 任何候选进入 paper 之前，必须另做 event-ledger、回撤归因、行情分段、成本压力和人工复核。",
        ]
    )
    return "\n".join(lines) + "\n"


def _evaluate_buy_hold(bars_4h: pd.DataFrame, *, initial_capital: float, cost_bps: float) -> EvaluatedRule:
    spec = TrendRuleSpec(
        "baseline",
        "buy_hold",
        "Buy and hold BTC",
        {"signal_type": "baseline"},
        False,
        "baseline",
        [],
        [],
    )
    close = bars_4h["close"].astype(float)
    returns = close.pct_change().fillna(0.0)
    exposure = pd.Series(1.0, index=close.index)
    turnover = exposure.diff().abs().fillna(exposure.abs())
    cost = turnover * (float(cost_bps) / 10_000.0)
    strategy_returns = (exposure * returns - cost).fillna(0.0)
    equity = float(initial_capital) * (1.0 + strategy_returns).cumprod()
    metrics = performance_metrics(
        strategy_returns=strategy_returns,
        equity=equity,
        exposure=exposure,
        turnover=turnover,
        cost=cost,
        interval=BASE_INTERVAL,
        initial_capital=initial_capital,
    )
    return EvaluatedRule(spec, exposure, exposure, strategy_returns, turnover, cost, equity, metrics)


def _grid_row(
    item: EvaluatedRule,
    *,
    buy_hold_metrics: Mapping[str, Any],
    walk_forward: Mapping[str, Any],
    regime: Mapping[str, Any],
    cost_stress: Mapping[str, Any],
) -> dict[str, Any]:
    metrics = item.metrics
    score = _score(metrics, buy_hold_metrics=buy_hold_metrics, walk_forward=walk_forward, regime=regime, cost_stress=cost_stress)
    decision = _retention_decision(metrics, walk_forward=walk_forward, regime=regime, cost_stress=cost_stress)
    return {
        "candidate_id": item.spec.candidate_id,
        "family_id": item.spec.family_id,
        "variant_id": item.spec.variant_id,
        "variant_kind": "optimized" if item.spec.optimized else "original",
        "optimization_stage": item.spec.optimization_stage,
        "optimization_components": item.spec.optimization_components,
        "label": item.spec.label,
        "params": item.spec.params,
        "optimization_notes": item.spec.optimization_notes,
        "total_return_pct": metrics["total_return_pct"],
        "annual_return_pct": metrics["annual_return_pct"],
        "max_drawdown_pct": metrics["max_drawdown_pct"],
        "max_drawdown_abs_pct": metrics["max_drawdown_abs_pct"],
        "profit_factor": metrics["profit_factor"],
        "sharpe_ratio": metrics["sharpe_ratio"],
        "average_exposure": metrics["average_exposure"],
        "turnover": metrics["turnover"],
        "fee_return_pct": metrics["fee_return_pct"],
        "return_diff_vs_buy_hold_pct": _round(float(metrics["total_return_pct"]) - float(buy_hold_metrics.get("total_return_pct", 0.0))),
        "drawdown_reduction_vs_buy_hold_pct": _round(float(buy_hold_metrics.get("max_drawdown_abs_pct", 0.0)) - float(metrics["max_drawdown_abs_pct"])),
        "walk_forward_pass_rate": walk_forward["pass_rate"],
        "walk_forward": walk_forward,
        "regime_pass_rate": regime["pass_rate"],
        "best_positive_year_share": regime["best_positive_year_share"],
        "regime": regime,
        "cost_survival_rate": cost_stress["survival_rate"],
        "cost_stress": cost_stress,
        "score": score,
        "retention_decision": decision,
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
    }


def _score(metrics: Mapping[str, Any], *, buy_hold_metrics: Mapping[str, Any], walk_forward: Mapping[str, Any], regime: Mapping[str, Any], cost_stress: Mapping[str, Any]) -> float:
    total = float(metrics.get("total_return_pct", 0.0))
    sharpe = float(metrics.get("sharpe_ratio", 0.0))
    drawdown = float(metrics.get("max_drawdown_abs_pct", 0.0))
    profit_factor = min(float(metrics.get("profit_factor", 0.0)), 5.0)
    wf = float(walk_forward.get("pass_rate", 0.0))
    regime_pass = float(regime.get("pass_rate", 0.0))
    cost_survival = float(cost_stress.get("survival_rate", 0.0))
    best_year_share = float(regime.get("best_positive_year_share", 1.0))
    bh_drawdown = float(buy_hold_metrics.get("max_drawdown_abs_pct", 0.0))
    drawdown_reduction = bh_drawdown - drawdown
    return _round(total * 0.25 + sharpe * 10.0 + profit_factor * 8.0 + wf * 20.0 + regime_pass * 10.0 + cost_survival * 12.0 + drawdown_reduction * 0.35 - max(0.0, best_year_share - 0.70) * 50.0)


def _retention_decision(metrics: Mapping[str, Any], *, walk_forward: Mapping[str, Any], regime: Mapping[str, Any], cost_stress: Mapping[str, Any]) -> str:
    if float(metrics.get("total_return_pct", 0.0)) <= 0.0:
        return "reject_non_positive_total_return"
    if float(metrics.get("profit_factor", 0.0)) < 1.0:
        return "reject_profit_factor_below_1"
    if float(metrics.get("max_drawdown_abs_pct", 0.0)) > 40.0:
        return "defer_drawdown_too_high"
    if float(walk_forward.get("pass_rate", 0.0)) < 0.5:
        return "defer_walk_forward_unstable"
    if float(regime.get("best_positive_year_share", 1.0)) > 0.75:
        return "defer_year_concentration_review"
    if float(cost_stress.get("survival_rate", 0.0)) < 0.6:
        return "defer_cost_stress_review"
    return "retain_extended_research_only"


def _extended_research_shortlist(rows: Sequence[Mapping[str, Any]], *, max_count: int = 4) -> list[dict[str, Any]]:
    retained = [dict(row) for row in rows if row.get("retention_decision") == "retain_extended_research_only"]
    output = []
    seen_families: set[str] = set()
    for row in retained:
        family = str(row.get("family_id"))
        if family in seen_families:
            continue
        row["shortlist_status"] = "extended_research_manual_review_only"
        row["paper_queue_write_allowed"] = False
        row["live_unlock_allowed"] = False
        output.append(row)
        seen_families.add(family)
        if len(output) >= max_count:
            break
    return output


def _family_stepwise_comparison(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    stage_rank = {
        "original": 0,
        "single_slow_breakout": 1,
        "single_fast_exit": 1,
        "single_tighter_multiplier": 1,
        "single_volume_confirm": 1,
        "single_atr_expansion_confirm": 1,
        "single_daily_confirm": 2,
        "single_daily_supertrend_confirm": 2,
        "single_vol_filter": 2,
        "single_funding_filter": 2,
        "single_long_short_filter": 2,
    }
    output: list[dict[str, Any]] = []
    by_family: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        by_family.setdefault(str(row.get("family_id")), []).append(row)
    for family_id, family_rows in sorted(by_family.items()):
        ordered = sorted(
            family_rows,
            key=lambda row: (
                stage_rank.get(str(row.get("optimization_stage")), 9),
                len(row.get("optimization_components", []) or []),
                str(row.get("optimization_stage")),
                str(row.get("candidate_id")),
            ),
        )
        original = next((row for row in ordered if str(row.get("optimization_stage")) == "original"), ordered[0])
        variants = []
        for row in ordered:
            variants.append(
                {
                    "candidate_id": row.get("candidate_id"),
                    "optimization_stage": row.get("optimization_stage"),
                    "optimization_components": row.get("optimization_components", []),
                    "total_return_pct": row.get("total_return_pct"),
                    "max_drawdown_abs_pct": row.get("max_drawdown_abs_pct"),
                    "profit_factor": row.get("profit_factor"),
                    "score": row.get("score"),
                    "retention_decision": row.get("retention_decision"),
                    "delta_total_return_vs_original_pct": _round(
                        float(row.get("total_return_pct", 0.0)) - float(original.get("total_return_pct", 0.0))
                    ),
                    "delta_drawdown_abs_vs_original_pct": _round(
                        float(row.get("max_drawdown_abs_pct", 0.0)) - float(original.get("max_drawdown_abs_pct", 0.0))
                    ),
                    "delta_score_vs_original": _round(float(row.get("score", 0.0)) - float(original.get("score", 0.0))),
                }
            )
        best = max(ordered, key=lambda row: float(row.get("score", 0.0)))
        output.append(
            {
                "family_id": family_id,
                "original_candidate_id": original.get("candidate_id"),
                "best_candidate_id": best.get("candidate_id"),
                "best_optimization_stage": best.get("optimization_stage"),
                "best_retention_decision": best.get("retention_decision"),
                "variants": variants,
            }
        )
    return output


def _donchian_signal(*, high: pd.Series, low: pd.Series, close: pd.Series, entry: int, exit_window: int) -> pd.Series:
    entry_signal = close > high.shift(1).rolling(entry).max()
    exit_signal = close < low.shift(1).rolling(exit_window).min()
    return _stateful_long_flat(entry_signal, exit_signal)


def _atr_channel_signal(*, high: pd.Series, low: pd.Series, close: pd.Series, ma_window: int, atr_window: int, entry_k: float, exit_k: float) -> pd.Series:
    atr = _atr(high=high, low=low, close=close, window=atr_window)
    mid = close.rolling(ma_window).mean()
    entry = close > mid + entry_k * atr
    exit_signal = close < mid - exit_k * atr
    return _stateful_long_flat(entry, exit_signal)


def _supertrend_signal(*, high: pd.Series, low: pd.Series, close: pd.Series, window: int, multiplier: float) -> pd.Series:
    atr = _atr(high=high, low=low, close=close, window=window)
    hl2 = (high + low) / 2.0
    upper = hl2 + multiplier * atr
    lower = hl2 - multiplier * atr
    final_upper: list[float] = []
    final_lower: list[float] = []
    trend: list[float] = []
    for i in range(len(close)):
        current_upper = float(upper.iloc[i])
        current_lower = float(lower.iloc[i])
        if not math.isfinite(current_upper) or not math.isfinite(current_lower):
            final_upper.append(float(upper.iloc[i]) if math.isfinite(float(upper.iloc[i])) else math.nan)
            final_lower.append(float(lower.iloc[i]) if math.isfinite(float(lower.iloc[i])) else math.nan)
            trend.append(0.0)
            continue
        prev_upper = final_upper[-1]
        prev_lower = final_lower[-1]
        if not math.isfinite(prev_upper) or not math.isfinite(prev_lower):
            final_upper.append(current_upper)
            final_lower.append(current_lower)
            trend.append(1.0 if float(close.iloc[i]) > current_lower else 0.0)
            continue
        prev_close = float(close.iloc[i - 1])
        fu = current_upper if current_upper < prev_upper or prev_close > prev_upper else prev_upper
        fl = current_lower if current_lower > prev_lower or prev_close < prev_lower else prev_lower
        final_upper.append(fu)
        final_lower.append(fl)
        previous_trend = trend[-1]
        current_close = float(close.iloc[i])
        if previous_trend <= 0.0 and current_close > fu:
            trend.append(1.0)
        elif previous_trend >= 1.0 and current_close < fl:
            trend.append(0.0)
        else:
            trend.append(previous_trend)
    return pd.Series(trend, index=close.index).fillna(0.0)


def _squeeze_breakout_signal(*, high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series, params: Mapping[str, Any], confirmed: bool) -> pd.Series:
    bb_window = int(params["bb_window"])
    bb_mid = close.rolling(bb_window).mean()
    bb_std = close.rolling(bb_window).std(ddof=0)
    bb_upper = bb_mid + float(params["bb_k"]) * bb_std
    bb_lower = bb_mid - float(params["bb_k"]) * bb_std
    kc_window = int(params["kc_window"])
    atr = _atr(high=high, low=low, close=close, window=kc_window)
    kc_mid = close.ewm(span=kc_window, adjust=False).mean()
    kc_upper = kc_mid + float(params["kc_k"]) * atr
    kc_lower = kc_mid - float(params["kc_k"]) * atr
    squeeze_on = (bb_upper < kc_upper) & (bb_lower > kc_lower)
    recent_squeeze = squeeze_on.shift(1).rolling(18, min_periods=1).max().fillna(False).astype(bool)
    breakout = close > high.shift(1).rolling(int(params["breakout_window"])).max()
    exit_signal = close < close.ewm(span=int(params["exit_ema"]), adjust=False).mean()
    if confirmed:
        volume_ratio = volume / volume.rolling(int(params["volume_window"])).median().replace(0.0, math.nan)
        atr_ratio = atr / atr.rolling(int(params["volume_window"])).median().replace(0.0, math.nan)
        breakout = breakout & (volume_ratio >= float(params["min_volume_ratio"])) & (atr_ratio >= float(params["min_atr_ratio"]))
    return _stateful_long_flat(recent_squeeze & breakout, exit_signal)


def _ma_ribbon_signal(*, close: pd.Series, params: Mapping[str, Any]) -> pd.Series:
    fast = close.ewm(span=int(params["ema_fast"]), adjust=False).mean()
    mid = close.ewm(span=int(params["ema_mid"]), adjust=False).mean()
    slow = close.ewm(span=int(params["ema_slow"]), adjust=False).mean()
    floor = close.ewm(span=int(params["ema_floor"]), adjust=False).mean()
    return ((fast > mid) & (mid > slow) & (slow > floor) & (close > floor)).astype(float)


def _ma_ribbon_modular_signal(*, close: pd.Series, bars_1d: pd.DataFrame, params: Mapping[str, Any]) -> pd.Series:
    signal = _ma_ribbon_signal(close=close, params=params)
    if bool(params.get("use_daily_confirm", True)):
        daily_fast = bars_1d["close"].astype(float).ewm(span=int(params["daily_fast"]), adjust=False).mean()
        daily_slow = bars_1d["close"].astype(float).ewm(span=int(params["daily_slow"]), adjust=False).mean()
        daily_confirm = ((daily_fast > daily_slow) & (bars_1d["close"].astype(float) > daily_slow)).astype(float)
        signal = signal * daily_confirm.reindex(close.index, method="ffill").fillna(0.0)
    if bool(params.get("use_vol_filter", True)):
        window = int(params["vol_window"])
        vol = close.pct_change().rolling(window).std(ddof=0)
        vol_cap = vol.rolling(window * 4, min_periods=window).quantile(0.85).shift(1)
        vol_ok = ((vol <= vol_cap) | vol_cap.isna()).astype(float)
        signal = signal * vol_ok
    return signal.clip(0.0, 1.0)


def _oi_atr_breakout_modular_signal(
    *,
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    derivatives_4h: pd.DataFrame,
    params: Mapping[str, Any],
) -> pd.Series:
    base = _atr_channel_signal(
        high=high,
        low=low,
        close=close,
        ma_window=int(params["ma_window"]),
        atr_window=int(params["atr_window"]),
        entry_k=float(params["entry_k"]),
        exit_k=float(params["exit_k"]),
    )
    window = int(params["rolling_filter_window"])
    oi = pd.to_numeric(derivatives_4h.get("open_interest_usd"), errors="coerce")
    funding = pd.to_numeric(derivatives_4h.get("funding_rate"), errors="coerce")
    long_short = pd.to_numeric(derivatives_4h.get("long_short_ratio"), errors="coerce")
    oi_delta = oi.diff(int(params["oi_delta_bars"]))
    oi_z = rolling_z(oi_delta, window=max(18, int(params["oi_delta_bars"]) * 4))
    signal = base * (oi_z > 0.0).astype(float)
    if bool(params.get("use_funding_filter", True)):
        funding_cap = funding.rolling(window, min_periods=24).quantile(0.80).shift(1)
        funding_ok = ((funding <= funding_cap) | funding_cap.isna()).astype(float)
        signal = signal * funding_ok
    if bool(params.get("use_long_short_filter", True)):
        long_short_cap = long_short.rolling(window, min_periods=24).quantile(0.85).shift(1)
        long_short_ok = ((long_short <= long_short_cap) | long_short_cap.isna()).astype(float)
        signal = signal * long_short_ok
    return signal.reindex(close.index).fillna(0.0).clip(0.0, 1.0)


def _daily_ma_confirm(index: pd.DatetimeIndex, bars_1d: pd.DataFrame, *, ma_window: int) -> pd.Series:
    close = bars_1d["close"].astype(float)
    ma = close.rolling(ma_window).mean()
    raw = ((close > ma) & (ma > ma.shift(10))).astype(float)
    return raw.reindex(index, method="ffill").fillna(0.0)


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


def _atr(*, high: pd.Series, low: pd.Series, close: pd.Series, window: int) -> pd.Series:
    previous_close = close.shift(1)
    tr = pd.concat([(high - low).abs(), (high - previous_close).abs(), (low - previous_close).abs()], axis=1).max(axis=1)
    return tr.rolling(window).mean()


def rolling_z(values: pd.Series, window: int) -> pd.Series:
    mean = values.rolling(window).mean()
    std = values.rolling(window).std(ddof=0)
    return (values - mean) / std.replace(0.0, math.nan)


def _family_context() -> list[dict[str, Any]]:
    return [
        {"family_id": "donchian_turtle", "idea": "classic turtle-style high/low channel breakout"},
        {"family_id": "atr_channel", "idea": "moving average plus ATR channel trend following"},
        {"family_id": "supertrend", "idea": "ATR trailing trend-line regime switch"},
        {"family_id": "squeeze_breakout", "idea": "trade upside breakout only after volatility compression"},
        {"family_id": "ma_ribbon", "idea": "multi-EMA trend alignment and trend filter"},
        {"family_id": "oi_confirmed_atr_breakout", "idea": "price breakout confirmed by rising open interest and sentiment filters"},
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
    warnings: list[str] = ["btc_simple_trend_rule_lab_research_only_no_paper_no_live"]
    if any(str(row.get("family_id")) == "oi_confirmed_atr_breakout" for row in rows):
        warnings.append("btc_simple_trend_rule_lab_oi_candidates_require_derivatives_timestamp_review")
    if any(float(row.get("best_positive_year_share", 0.0)) > 0.75 for row in rows):
        warnings.append("btc_simple_trend_rule_lab_some_candidates_year_concentrated")
    return warnings


def _empty_metrics() -> dict[str, Any]:
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
        "final_equity": INITIAL_CAPITAL,
        "average_exposure": 0.0,
        "bars_with_exposure": 0,
        "turnover": 0.0,
        "exposure_change_count": 0,
        "fee_return_pct": 0.0,
        "winning_exposed_bar_pct": 0.0,
    }


def _round(value: float, digits: int = 6) -> float:
    if value is None or not math.isfinite(float(value)):
        return 0.0
    return round(float(value), digits)


def _round_mapping(metrics: Mapping[str, Any]) -> dict[str, Any]:
    return {str(key): (_round(value) if isinstance(value, float) else value) for key, value in metrics.items()}


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _grid_fieldnames() -> list[str]:
    return [
        "candidate_id",
        "family_id",
        "variant_id",
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
        "turnover",
        "fee_return_pct",
        "return_diff_vs_buy_hold_pct",
        "drawdown_reduction_vs_buy_hold_pct",
        "walk_forward_pass_rate",
        "regime_pass_rate",
        "best_positive_year_share",
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


def _portable_path(path: Path) -> str:
    return str(path).replace("\\", "/")


def _ts(value: Any) -> str:
    return pd.Timestamp(value).isoformat()


def _git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return "unknown"
