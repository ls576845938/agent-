from __future__ import annotations

import csv
import hashlib
import json
import math
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd

from quant_crypto.research.multi_timeframe_rule_lab import (
    BASE_COST_BPS,
    INITIAL_CAPITAL,
    aggregate_ohlcv_calendar,
    performance_metrics,
)
from quant_crypto.research.simple_trend_rule_lab import (
    DEFAULT_DERIVATIVES_ROWS,
    DEFAULT_MARKET_DB,
    EXCHANGE,
    SYMBOL,
    aggregate_ohlcv,
    align_derivatives_to_index,
    load_market_1h,
)


SCHEMA_VERSION = "btc_long_short_trend_following_lab_v1"
SOURCE_INTERVAL = "1h"
BASE_INTERVAL = "4h"
DEFAULT_OUTPUT_DIR = Path("artifacts/btc_long_short_trend_following_lab/latest")
DEFAULT_REPORT_PATH = DEFAULT_OUTPUT_DIR / "btc_long_short_trend_following_lab_report.json"
DEFAULT_GRID_PATH = DEFAULT_OUTPUT_DIR / "btc_long_short_trend_following_lab_grid.csv"
DEFAULT_MARKDOWN_PATH = DEFAULT_OUTPUT_DIR / "btc_long_short_trend_following_lab_summary_cn.md"

MIN_4H_BARS = 900
MIN_1D_BARS = 180
BAR_HOURS = 4.0
FUNDING_INTERVAL_HOURS = 8.0
DERIVED_TIMEFRAMES = ["4h", "1d", "1w", "1mo"]
DEFAULT_RUN_PROFILE = "formal_narrow"
RUN_PROFILES = {"smoke", "formal_narrow"}
FORMAL_DONCHIAN_WINDOWS = [72, 96, 120, 180, 240]
FORMAL_DAILY_TRENDS = [(20, 80), (34, 144), (50, 200)]
FORMAL_ATR_MULTS = [2.0, 2.5, 3.0, 3.5]
FORMAL_COOLDOWN_BARS = [0, 6, 12]
FORMAL_FAILURE_EXIT = [False, True]
FORMAL_RISK_FILTER_MODES = ["none", "funding", "funding_oi", "funding_oi_long_short"]


@dataclass(frozen=True)
class LongShortTrendSpec:
    family_id: str
    variant_id: str
    label: str
    params: dict[str, Any]
    direction_policy: str
    instrument_assumption: str
    optimization_stage: str
    optimization_components: list[str]
    notes: list[str]

    @property
    def branch(self) -> str:
        if self.direction_policy == "long_short":
            return "long_short_research"
        return "same_window_reference"

    @property
    def candidate_id(self) -> str:
        raw = {
            "family_id": self.family_id,
            "variant_id": self.variant_id,
            "params": self.params,
            "direction_policy": self.direction_policy,
            "instrument_assumption": self.instrument_assumption,
            "optimization_stage": self.optimization_stage,
        }
        digest = hashlib.sha1(json.dumps(raw, sort_keys=True).encode("utf-8")).hexdigest()[:10]
        return f"btc_ls_tf_{self.variant_id}_{digest}"


@dataclass
class EvaluatedLongShortTrendRule:
    spec: LongShortTrendSpec
    raw_signal: pd.Series
    exposure: pd.Series
    returns: pd.Series
    turnover: pd.Series
    trading_cost: pd.Series
    funding_pnl: pd.Series
    equity: pd.Series
    metrics: dict[str, Any]


def build_btc_long_short_trend_following_lab(
    *,
    market_db_path: Path = DEFAULT_MARKET_DB,
    derivatives_rows_path: Path = DEFAULT_DERIVATIVES_ROWS,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    generated_at_utc: datetime | None = None,
    initial_capital: float = INITIAL_CAPITAL,
    base_cost_bps: float = BASE_COST_BPS,
    run_profile: str = DEFAULT_RUN_PROFILE,
) -> dict[str, Any]:
    if run_profile not in RUN_PROFILES:
        raise ValueError(f"unsupported run_profile: {run_profile}")
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

    blockers: list[str] = []
    if len(bars_4h) < MIN_4H_BARS:
        blockers.append("btc_long_short_trend_following_lab_insufficient_4h_bars")
    if len(bars_1d) < MIN_1D_BARS:
        blockers.append("btc_long_short_trend_following_lab_insufficient_1d_bars")

    specs = long_short_trend_following_specs(run_profile=run_profile)
    evaluated = [
        evaluate_long_short_trend_rule(
            spec,
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
            bars_4h=bars_4h,
            bars_1d=bars_1d,
            initial_capital=initial_capital,
            base_cost_bps=base_cost_bps,
        )
        for item in evaluated
    ]
    baselines = _baselines(bars_4h=bars_4h, initial_capital=initial_capital, cost_bps=base_cost_bps)
    reference_comparison = _reference_comparison(rows)
    ranked = _rank_with_reference_context(rows, reference_comparison=reference_comparison)
    long_short_rows = [row for row in ranked if row["branch"] == "long_short_research"]
    reference_rows = [row for row in ranked if row["branch"] == "same_window_reference"]
    watchlist = _long_short_research_watchlist(long_short_rows)

    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated.isoformat(),
        "status": "blocked" if blockers else "complete_research_only",
        "decision": "btc_long_short_trend_following_lab_research_only_no_paper_no_live",
        "scope": "btc_long_short_symmetric_trend_following_research_lab",
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
            "derived_timeframes_from_1h": DERIVED_TIMEFRAMES,
            "market_completed_bar_rule": "1h completed bars are the only market source; 4h/1d/1w/1mo are derived from complete 1h chunks",
            "derivatives_available_time_rule": "derivatives rows are aligned by available_time <= 4h decision_time",
            "derivatives_visible_rows": int(derivatives_4h["open_interest_usd"].notna().sum())
            if "open_interest_usd" in derivatives_4h
            else 0,
        },
        "validation_design": {
            "run_profile": run_profile,
            "formal_grid": _formal_grid_summary(),
            "candidate_count": len(specs),
            "long_short_candidate_count": len([spec for spec in specs if spec.direction_policy == "long_short"]),
            "same_window_reference_count": len([spec for spec in specs if spec.direction_policy != "long_short"]),
            "purpose": "test symmetric BTC trend following: confirmed uptrend may go long, confirmed downtrend may go short, sideways stays cash",
            "execution_rule": "signals are computed at completed 4h decision closes; exposure starts on the next 4h bar",
            "sideways_cash_rule": "if daily trend is neither bull nor bear, new entries are forbidden and existing trend positions exit",
            "primary_signal_sources": ["price_trend", "donchian_breakout_breakdown", "ema_ribbon", "atr_trailing_stop"],
            "derivatives_usage": "funding/OI/long-short ratio are risk filters only; they are never standalone entry signals",
            "comparison_policy": "long_short candidates are compared to same-window long_flat and short_flat references under the same 4h cost model",
            "cost_model": {
                "base_cost_bps": float(base_cost_bps),
                "stress_cost_bps": _cost_stress_bps(base_cost_bps),
                "includes_taker_fee_and_slippage": True,
            },
            "funding_model": {
                "enabled_for_perpetual_research_rows": True,
                "formula": "funding_pnl = -exposure * funding_rate * (4h / 8h)",
                "research_approximation": True,
                "not_sufficient_for_paper_or_live": True,
            },
            "no_lookahead_policy": [
                "all price features use completed 1h bars",
                "4h/1d/1w/1mo bars are derived from completed 1h rows",
                "derivatives features require available_time <= decision_time",
                "rolling quantiles, z-scores, Donchian channels and volatility caps use shifted history",
                "raw signals are shifted by one 4h bar before return calculation",
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
            "reason": "long/short trend following remains research-only; it needs perpetual funding, liquidation, borrow/exchange and paper gate evidence before promotion",
        },
        "baselines": baselines,
        "reference_comparison": reference_comparison,
        "comparison_rows": ranked,
        "long_short_research_rows": long_short_rows,
        "same_window_reference_rows": reference_rows,
        "long_short_research_watchlist": watchlist,
        "blockers": blockers,
        "warnings": _warnings(ranked),
        "outputs": {
            "json": _portable_path(report_path),
            "grid_csv": _portable_path(grid_path),
            "summary_cn": _portable_path(markdown_path),
        },
    }
    _write_csv(grid_path, _grid_fieldnames(), ranked)
    _write_json(report_path, report)
    _write_text(markdown_path, render_long_short_trend_following_markdown(report))
    return report


def long_short_trend_following_specs(*, run_profile: str = DEFAULT_RUN_PROFILE) -> list[LongShortTrendSpec]:
    if run_profile not in RUN_PROFILES:
        raise ValueError(f"unsupported run_profile: {run_profile}")

    def spec(
        family_id: str,
        variant_id: str,
        label: str,
        params: dict[str, Any],
        *,
        direction_policy: str,
        instrument: str,
        stage: str,
        components: list[str],
        notes: list[str],
    ) -> LongShortTrendSpec:
        params = {
            "primary_signal_source": "price_trend",
            "derivatives_usage": "risk_filter_only",
            **params,
        }
        return LongShortTrendSpec(
            family_id=family_id,
            variant_id=variant_id,
            label=label,
            params=params,
            direction_policy=direction_policy,
            instrument_assumption=instrument,
            optimization_stage=stage,
            optimization_components=components,
            notes=notes,
        )

    perp = "simulated_usdt_perpetual_research_only"
    spot = "spot_research_reference_only"
    specs = [
        spec(
            "symmetric_donchian",
            "ls_donchian_original",
            "Symmetric Donchian breakout/breakdown with ATR trail",
            {
                "signal_type": "symmetric_donchian",
                "daily_fast": 50,
                "daily_slow": 200,
                "entry_window": 120,
                "exit_window": 60,
                "atr_window": 20,
                "atr_mult": 3.0,
                "use_derivatives_risk_filter": False,
                "use_risk_exit": False,
            },
            direction_policy="long_short",
            instrument=perp,
            stage="original",
            components=[],
            notes=["Donchian upper break goes long; lower break goes short; neutral daily regime stays cash"],
        ),
        spec(
            "symmetric_donchian",
            "ls_donchian_risk_filter",
            "Symmetric Donchian with funding/OI/long-short risk filter",
            {
                "signal_type": "symmetric_donchian",
                "daily_fast": 50,
                "daily_slow": 200,
                "entry_window": 120,
                "exit_window": 60,
                "atr_window": 20,
                "atr_mult": 3.0,
                "use_derivatives_risk_filter": True,
                "use_risk_exit": True,
            },
            direction_policy="long_short",
            instrument=perp,
            stage="single_derivatives_risk_filter",
            components=["funding_oi_long_short_filter"],
            notes=["Derivatives data only blocks crowded entries or forces risk exits; it never creates an entry"],
        ),
        spec(
            "symmetric_donchian",
            "ls_donchian_fast_regime",
            "Faster daily regime Donchian with ATR trail",
            {
                "signal_type": "symmetric_donchian",
                "daily_fast": 20,
                "daily_slow": 80,
                "entry_window": 72,
                "exit_window": 36,
                "atr_window": 20,
                "atr_mult": 2.5,
                "use_derivatives_risk_filter": False,
                "use_risk_exit": False,
            },
            direction_policy="long_short",
            instrument=perp,
            stage="single_faster_regime_and_channel",
            components=["faster_daily_regime", "shorter_donchian_window", "tighter_atr_trail"],
            notes=["Narrow variant to test whether downtrend confirmation is too slow on BTC"],
        ),
        spec(
            "symmetric_ema_ribbon",
            "ls_ema_ribbon_original",
            "Symmetric EMA ribbon long/short with ATR trail",
            {
                "signal_type": "symmetric_ema_ribbon",
                "daily_fast": 50,
                "daily_slow": 200,
                "atr_window": 20,
                "atr_mult": 3.0,
                "use_derivatives_risk_filter": False,
                "use_risk_exit": False,
            },
            direction_policy="long_short",
            instrument=perp,
            stage="original",
            components=[],
            notes=["EMA ribbon bull alignment goes long; bear alignment goes short"],
        ),
        spec(
            "symmetric_ema_ribbon",
            "ls_ema_ribbon_risk_filter",
            "Symmetric EMA ribbon with derivatives risk filter",
            {
                "signal_type": "symmetric_ema_ribbon",
                "daily_fast": 50,
                "daily_slow": 200,
                "atr_window": 20,
                "atr_mult": 3.0,
                "use_derivatives_risk_filter": True,
                "use_risk_exit": True,
            },
            direction_policy="long_short",
            instrument=perp,
            stage="single_derivatives_risk_filter",
            components=["funding_oi_long_short_filter"],
            notes=["Risk filter is symmetric: avoid crowded longs and crowded shorts"],
        ),
        spec(
            "hybrid_donchian_ema_atr",
            "ls_hybrid_donchian_ema_atr",
            "Donchian entry with EMA ribbon confirmation and ATR trail",
            {
                "signal_type": "hybrid_donchian_ema_atr",
                "daily_fast": 34,
                "daily_slow": 144,
                "entry_window": 72,
                "exit_window": 36,
                "atr_window": 20,
                "atr_mult": 2.5,
                "use_derivatives_risk_filter": False,
                "use_risk_exit": False,
            },
            direction_policy="long_short",
            instrument=perp,
            stage="combo_donchian_ema_atr",
            components=["donchian_breakout", "ema_ribbon_confirmation", "atr_trailing_exit"],
            notes=["Only trade when price breakout and EMA trend agree"],
        ),
        spec(
            "hybrid_donchian_ema_atr",
            "ls_hybrid_risk_filter",
            "Hybrid Donchian/EMA/ATR with derivatives risk filter",
            {
                "signal_type": "hybrid_donchian_ema_atr",
                "daily_fast": 34,
                "daily_slow": 144,
                "entry_window": 72,
                "exit_window": 36,
                "atr_window": 20,
                "atr_mult": 2.5,
                "use_derivatives_risk_filter": True,
                "use_risk_exit": True,
            },
            direction_policy="long_short",
            instrument=perp,
            stage="combo_hybrid_plus_risk_filter",
            components=["donchian_breakout", "ema_ribbon_confirmation", "atr_trailing_exit", "funding_oi_long_short_filter"],
            notes=["Same trend logic as hybrid, with derivatives only as a risk veto"],
        ),
        spec(
            "symmetric_atr_channel",
            "ls_atr_channel_original",
            "Symmetric ATR channel trend follower with ATR trail",
            {
                "signal_type": "symmetric_atr_channel",
                "daily_fast": 34,
                "daily_slow": 144,
                "ma_window": 96,
                "atr_window": 20,
                "entry_k": 1.2,
                "exit_k": 0.4,
                "atr_mult": 2.5,
                "use_derivatives_risk_filter": False,
                "use_risk_exit": False,
            },
            direction_policy="long_short",
            instrument=perp,
            stage="atr_channel_baseline_neighbor",
            components=["atr_channel", "atr_trailing_exit"],
            notes=["Long above upper ATR channel and short below lower ATR channel, only when daily trend confirms"],
        ),
        spec(
            "symmetric_donchian",
            "ref_donchian_long_flat",
            "Same-window Donchian long/flat reference",
            {
                "signal_type": "symmetric_donchian",
                "daily_fast": 50,
                "daily_slow": 200,
                "entry_window": 120,
                "exit_window": 60,
                "atr_window": 20,
                "atr_mult": 3.0,
                "use_derivatives_risk_filter": False,
                "use_risk_exit": False,
            },
            direction_policy="long_flat_reference",
            instrument=spot,
            stage="same_window_reference",
            components=["long_flat_reference"],
            notes=["Reference row to compare the symmetric rule against long/flat under the same market window"],
        ),
        spec(
            "symmetric_donchian",
            "ref_donchian_short_flat",
            "Same-window Donchian short/flat reference",
            {
                "signal_type": "symmetric_donchian",
                "daily_fast": 50,
                "daily_slow": 200,
                "entry_window": 120,
                "exit_window": 60,
                "atr_window": 20,
                "atr_mult": 3.0,
                "use_derivatives_risk_filter": False,
                "use_risk_exit": False,
            },
            direction_policy="short_flat_reference",
            instrument=perp,
            stage="same_window_reference",
            components=["short_flat_reference"],
            notes=["Reference row to compare the symmetric rule against short/flat under the same market window"],
        ),
        spec(
            "symmetric_ema_ribbon",
            "ref_ema_ribbon_long_flat",
            "Same-window EMA ribbon long/flat reference",
            {
                "signal_type": "symmetric_ema_ribbon",
                "daily_fast": 50,
                "daily_slow": 200,
                "atr_window": 20,
                "atr_mult": 3.0,
                "use_derivatives_risk_filter": False,
                "use_risk_exit": False,
            },
            direction_policy="long_flat_reference",
            instrument=spot,
            stage="same_window_reference",
            components=["long_flat_reference"],
            notes=["Reference row for the existing long/flat research line"],
        ),
        spec(
            "symmetric_ema_ribbon",
            "ref_ema_ribbon_short_flat",
            "Same-window EMA ribbon short/flat reference",
            {
                "signal_type": "symmetric_ema_ribbon",
                "daily_fast": 50,
                "daily_slow": 200,
                "atr_window": 20,
                "atr_mult": 3.0,
                "use_derivatives_risk_filter": False,
                "use_risk_exit": False,
            },
            direction_policy="short_flat_reference",
            instrument=perp,
            stage="same_window_reference",
            components=["short_flat_reference"],
            notes=["Reference row for the existing short/flat research line"],
        ),
    ]
    if run_profile == "smoke":
        return specs

    for window in FORMAL_DONCHIAN_WINDOWS:
        for daily_fast, daily_slow in FORMAL_DAILY_TRENDS:
            for atr_mult in FORMAL_ATR_MULTS:
                for cooldown in FORMAL_COOLDOWN_BARS:
                    for use_failure_exit in FORMAL_FAILURE_EXIT:
                        for risk_mode in FORMAL_RISK_FILTER_MODES:
                            risk_components = _risk_filter_components(risk_mode)
                            components = [
                                "formal_donchian_window",
                                "formal_daily_trend",
                                "formal_atr_trail",
                                "formal_cooldown",
                            ]
                            if use_failure_exit:
                                components.append("failed_breakout_exit")
                            components.extend(risk_components)
                            variant_id = (
                                f"formal_donchian_w{window}_d{daily_fast}_{daily_slow}_"
                                f"atr{int(atr_mult * 10):02d}_cd{cooldown}_"
                                f"fail{int(use_failure_exit)}_risk{risk_mode}"
                            )
                            specs.append(
                                spec(
                                    "symmetric_donchian_formal_narrow",
                                    variant_id,
                                    "Formal narrow symmetric Donchian long/short trend follower",
                                    {
                                        "signal_type": "symmetric_donchian",
                                        "daily_fast": daily_fast,
                                        "daily_slow": daily_slow,
                                        "entry_window": window,
                                        "exit_window": max(24, window // 2),
                                        "atr_window": 20,
                                        "atr_mult": atr_mult,
                                        "cooldown_bars": cooldown,
                                        "use_failed_breakout_exit": use_failure_exit,
                                        "failure_exit_window": 6,
                                        "risk_filter_mode": risk_mode,
                                        "use_derivatives_risk_filter": risk_mode != "none",
                                        "use_risk_exit": risk_mode != "none",
                                    },
                                    direction_policy="long_short",
                                    instrument=perp,
                                    stage="formal_narrow_grid",
                                    components=components,
                                    notes=[
                                        "pre-declared narrow formal grid around Donchian long/short trend following",
                                        "derivatives filter mode is a risk veto only",
                                    ],
                                )
                            )
    return specs


def evaluate_long_short_trend_rule(
    spec: LongShortTrendSpec,
    *,
    bars_4h: pd.DataFrame,
    bars_1d: pd.DataFrame,
    bars_1w: pd.DataFrame,
    bars_1mo: pd.DataFrame,
    derivatives_4h: pd.DataFrame,
    initial_capital: float,
    cost_bps: float,
) -> EvaluatedLongShortTrendRule:
    close = bars_4h["close"].astype(float)
    raw = raw_long_short_trend_signal(
        spec,
        bars_4h=bars_4h,
        bars_1d=bars_1d,
        bars_1w=bars_1w,
        bars_1mo=bars_1mo,
        derivatives_4h=derivatives_4h,
    )
    raw = _apply_direction_policy(raw.reindex(close.index).fillna(0.0).clip(-1.0, 1.0), spec.direction_policy)
    exposure = raw.shift(1).fillna(0.0).clip(-1.0, 1.0)
    turnover = exposure.diff().abs().fillna(exposure.abs())
    trading_cost = turnover * (float(cost_bps) / 10_000.0)
    funding_pnl = _funding_pnl(exposure, derivatives_4h) if "perpetual" in spec.instrument_assumption else pd.Series(0.0, index=close.index)
    returns = (exposure * close.pct_change().fillna(0.0) - trading_cost + funding_pnl).fillna(0.0)
    equity = float(initial_capital) * (1.0 + returns).cumprod()
    metrics = performance_metrics(
        strategy_returns=returns,
        equity=equity,
        exposure=exposure,
        turnover=turnover,
        cost=trading_cost,
        interval=BASE_INTERVAL,
        initial_capital=initial_capital,
    )
    metrics["funding_return_pct"] = _round(float(funding_pnl.sum()) * 100.0)
    metrics["trading_cost_return_pct"] = _round(float(trading_cost.sum()) * -100.0)
    metrics["long_bar_count"] = int((exposure > 0.0).sum())
    metrics["short_bar_count"] = int((exposure < 0.0).sum())
    return EvaluatedLongShortTrendRule(spec, raw, exposure, returns, turnover, trading_cost, funding_pnl, equity, metrics)


def _formal_grid_summary() -> dict[str, Any]:
    return {
        "profile": "formal_narrow",
        "enabled_by_default": DEFAULT_RUN_PROFILE == "formal_narrow",
        "base_smoke_candidate_count": len(long_short_trend_following_specs(run_profile="smoke")),
        "donchian_windows": FORMAL_DONCHIAN_WINDOWS,
        "daily_trend_ema_pairs": [[fast, slow] for fast, slow in FORMAL_DAILY_TRENDS],
        "atr_multipliers": FORMAL_ATR_MULTS,
        "cooldown_bars_4h": FORMAL_COOLDOWN_BARS,
        "failed_breakout_exit": FORMAL_FAILURE_EXIT,
        "risk_filter_modes": FORMAL_RISK_FILTER_MODES,
        "formal_donchian_grid_count": (
            len(FORMAL_DONCHIAN_WINDOWS)
            * len(FORMAL_DAILY_TRENDS)
            * len(FORMAL_ATR_MULTS)
            * len(FORMAL_COOLDOWN_BARS)
            * len(FORMAL_FAILURE_EXIT)
            * len(FORMAL_RISK_FILTER_MODES)
        ),
        "exit_window_rule": "exit_window=max(24, donchian_window/2)",
        "risk_filter_policy": "none/funding/funding+OI/funding+OI+long-short ratio; all are risk vetoes only",
    }


def _risk_filter_components(risk_mode: str) -> list[str]:
    if risk_mode == "none":
        return []
    if risk_mode == "funding":
        return ["funding_filter"]
    if risk_mode == "funding_oi":
        return ["funding_filter", "open_interest_filter"]
    if risk_mode == "funding_oi_long_short":
        return ["funding_filter", "open_interest_filter", "long_short_ratio_filter"]
    raise ValueError(f"unsupported risk_filter_mode: {risk_mode}")


def raw_long_short_trend_signal(
    spec: LongShortTrendSpec,
    *,
    bars_4h: pd.DataFrame,
    bars_1d: pd.DataFrame,
    bars_1w: pd.DataFrame,
    bars_1mo: pd.DataFrame,
    derivatives_4h: pd.DataFrame,
) -> pd.Series:
    signal_type = str(spec.params["signal_type"])
    if signal_type == "symmetric_donchian":
        return _signal_symmetric_donchian(bars_4h=bars_4h, bars_1d=bars_1d, derivatives_4h=derivatives_4h, params=spec.params)
    if signal_type == "symmetric_ema_ribbon":
        return _signal_symmetric_ema_ribbon(bars_4h=bars_4h, bars_1d=bars_1d, derivatives_4h=derivatives_4h, params=spec.params)
    if signal_type == "hybrid_donchian_ema_atr":
        return _signal_hybrid_donchian_ema_atr(bars_4h=bars_4h, bars_1d=bars_1d, derivatives_4h=derivatives_4h, params=spec.params)
    if signal_type == "symmetric_atr_channel":
        return _signal_symmetric_atr_channel(bars_4h=bars_4h, bars_1d=bars_1d, derivatives_4h=derivatives_4h, params=spec.params)
    raise ValueError(f"unsupported signal_type: {signal_type}")


def _signal_symmetric_donchian(
    *,
    bars_4h: pd.DataFrame,
    bars_1d: pd.DataFrame,
    derivatives_4h: pd.DataFrame,
    params: Mapping[str, Any],
) -> pd.Series:
    close = bars_4h["close"].astype(float)
    high = bars_4h["high"].astype(float)
    low = bars_4h["low"].astype(float)
    daily_bull, daily_bear = _daily_trend_states(bars_1d, close.index, params=params)
    long_breakout_line = high.shift(1).rolling(int(params["entry_window"])).max()
    short_breakdown_line = low.shift(1).rolling(int(params["entry_window"])).min()
    long_entry = daily_bull & (close > long_breakout_line)
    short_entry = daily_bear & (close < short_breakdown_line)
    long_exit = (~daily_bull) | (close < low.shift(1).rolling(int(params["exit_window"])).min())
    short_exit = (~daily_bear) | (close > high.shift(1).rolling(int(params["exit_window"])).max())
    long_entry, long_exit, short_entry, short_exit = _apply_derivatives_risk_filters(
        long_entry,
        long_exit,
        short_entry,
        short_exit,
        derivatives_4h=derivatives_4h,
        index=close.index,
        params=params,
    )
    atr = _atr(bars_4h, int(params.get("atr_window", 20)))
    return _stateful_long_short_with_atr_trail(
        long_entry,
        long_exit,
        short_entry,
        short_exit,
        close=close,
        atr=atr,
        atr_mult=float(params.get("atr_mult", 3.0)),
        cooldown_bars=int(params.get("cooldown_bars", 0)),
        use_failed_breakout_exit=bool(params.get("use_failed_breakout_exit", False)),
        failure_exit_window=int(params.get("failure_exit_window", 6)),
        long_failure_line=long_breakout_line,
        short_failure_line=short_breakdown_line,
    )


def _signal_symmetric_ema_ribbon(
    *,
    bars_4h: pd.DataFrame,
    bars_1d: pd.DataFrame,
    derivatives_4h: pd.DataFrame,
    params: Mapping[str, Any],
) -> pd.Series:
    close = bars_4h["close"].astype(float)
    daily_bull, daily_bear = _daily_trend_states(bars_1d, close.index, params=params)
    long_entry = daily_bull & _ema_ribbon_long(close)
    short_entry = daily_bear & _ema_ribbon_bear(close)
    long_exit = (~daily_bull) | (close < _ema(close, 100))
    short_exit = (~daily_bear) | (close > _ema(close, 100))
    long_entry, long_exit, short_entry, short_exit = _apply_derivatives_risk_filters(
        long_entry,
        long_exit,
        short_entry,
        short_exit,
        derivatives_4h=derivatives_4h,
        index=close.index,
        params=params,
    )
    atr = _atr(bars_4h, int(params.get("atr_window", 20)))
    return _stateful_long_short_with_atr_trail(
        long_entry,
        long_exit,
        short_entry,
        short_exit,
        close=close,
        atr=atr,
        atr_mult=float(params.get("atr_mult", 3.0)),
        cooldown_bars=int(params.get("cooldown_bars", 0)),
    )


def _signal_hybrid_donchian_ema_atr(
    *,
    bars_4h: pd.DataFrame,
    bars_1d: pd.DataFrame,
    derivatives_4h: pd.DataFrame,
    params: Mapping[str, Any],
) -> pd.Series:
    close = bars_4h["close"].astype(float)
    high = bars_4h["high"].astype(float)
    low = bars_4h["low"].astype(float)
    daily_bull, daily_bear = _daily_trend_states(bars_1d, close.index, params=params)
    long_break = close > high.shift(1).rolling(int(params["entry_window"])).max()
    short_break = close < low.shift(1).rolling(int(params["entry_window"])).min()
    long_entry = daily_bull & long_break & _ema_ribbon_long(close)
    short_entry = daily_bear & short_break & _ema_ribbon_bear(close)
    long_exit = (~daily_bull) | (close < low.shift(1).rolling(int(params["exit_window"])).min()) | (close < _ema(close, 100))
    short_exit = (~daily_bear) | (close > high.shift(1).rolling(int(params["exit_window"])).max()) | (close > _ema(close, 100))
    long_entry, long_exit, short_entry, short_exit = _apply_derivatives_risk_filters(
        long_entry,
        long_exit,
        short_entry,
        short_exit,
        derivatives_4h=derivatives_4h,
        index=close.index,
        params=params,
    )
    atr = _atr(bars_4h, int(params.get("atr_window", 20)))
    return _stateful_long_short_with_atr_trail(
        long_entry,
        long_exit,
        short_entry,
        short_exit,
        close=close,
        atr=atr,
        atr_mult=float(params.get("atr_mult", 2.5)),
        cooldown_bars=int(params.get("cooldown_bars", 0)),
    )


def _signal_symmetric_atr_channel(
    *,
    bars_4h: pd.DataFrame,
    bars_1d: pd.DataFrame,
    derivatives_4h: pd.DataFrame,
    params: Mapping[str, Any],
) -> pd.Series:
    close = bars_4h["close"].astype(float)
    atr = _atr(bars_4h, int(params.get("atr_window", 20)))
    mid = _ema(close, int(params.get("ma_window", 96)))
    daily_bull, daily_bear = _daily_trend_states(bars_1d, close.index, params=params)
    long_entry = daily_bull & (close > mid + float(params.get("entry_k", 1.2)) * atr)
    short_entry = daily_bear & (close < mid - float(params.get("entry_k", 1.2)) * atr)
    long_exit = (~daily_bull) | (close < mid - float(params.get("exit_k", 0.4)) * atr)
    short_exit = (~daily_bear) | (close > mid + float(params.get("exit_k", 0.4)) * atr)
    long_entry, long_exit, short_entry, short_exit = _apply_derivatives_risk_filters(
        long_entry,
        long_exit,
        short_entry,
        short_exit,
        derivatives_4h=derivatives_4h,
        index=close.index,
        params=params,
    )
    return _stateful_long_short_with_atr_trail(
        long_entry,
        long_exit,
        short_entry,
        short_exit,
        close=close,
        atr=atr,
        atr_mult=float(params.get("atr_mult", 2.5)),
        cooldown_bars=int(params.get("cooldown_bars", 0)),
    )


def _grid_row(
    item: EvaluatedLongShortTrendRule,
    *,
    bars_4h: pd.DataFrame,
    bars_1d: pd.DataFrame,
    initial_capital: float,
    base_cost_bps: float,
) -> dict[str, Any]:
    walk_forward = walk_forward_summary(item, initial_capital=initial_capital)
    annual = annual_summary(item, initial_capital=initial_capital)
    recent = recent_segment_summary(item, initial_capital=initial_capital)
    regime = market_regime_summary(item, bars_4h=bars_4h, bars_1d=bars_1d, initial_capital=initial_capital)
    cost_stress = cost_stress_summary(
        item,
        bars_4h=bars_4h,
        initial_capital=initial_capital,
        base_cost_bps=base_cost_bps,
    )
    adverse = adverse_move_diagnostics(item, bars_4h=bars_4h)
    decision = _retention_decision(
        item,
        walk_forward=walk_forward,
        annual=annual,
        recent=recent,
        regime=regime,
        cost_stress=cost_stress,
        adverse=adverse,
    )
    score = _score(item.metrics, walk_forward=walk_forward, annual=annual, recent=recent, regime=regime, cost_stress=cost_stress, adverse=adverse)
    return {
        "candidate_id": item.spec.candidate_id,
        "family_id": item.spec.family_id,
        "variant_id": item.spec.variant_id,
        "branch": item.spec.branch,
        "direction_policy": item.spec.direction_policy,
        "instrument_assumption": item.spec.instrument_assumption,
        "optimization_stage": item.spec.optimization_stage,
        "optimization_components": item.spec.optimization_components,
        "notes": item.spec.notes,
        "params": item.spec.params,
        "params_hash": hashlib.sha1(json.dumps(item.spec.params, sort_keys=True).encode("utf-8")).hexdigest()[:12],
        "label": item.spec.label,
        "total_return_pct": item.metrics["total_return_pct"],
        "annual_return_pct": item.metrics["annual_return_pct"],
        "max_drawdown_pct": item.metrics["max_drawdown_pct"],
        "max_drawdown_abs_pct": item.metrics["max_drawdown_abs_pct"],
        "profit_factor": item.metrics["profit_factor"],
        "sharpe_ratio": item.metrics["sharpe_ratio"],
        "average_exposure": item.metrics["average_exposure"],
        "average_net_exposure": item.metrics["average_net_exposure"],
        "long_bar_count": item.metrics["long_bar_count"],
        "short_bar_count": item.metrics["short_bar_count"],
        "bars_with_exposure": item.metrics["bars_with_exposure"],
        "turnover": item.metrics["turnover"],
        "fee_return_pct": item.metrics["fee_return_pct"],
        "funding_return_pct": item.metrics["funding_return_pct"],
        "trading_cost_return_pct": item.metrics["trading_cost_return_pct"],
        "walk_forward_pass_rate": walk_forward["pass_rate"],
        "annual_pass_rate": annual["pass_rate"],
        "best_positive_year_share": annual["best_positive_year_share"],
        "recent_segment_passed": recent["passed"],
        "recent_segment_total_return_pct": recent["metrics"]["total_return_pct"],
        "market_regime_pass_rate": regime["pass_rate"],
        "sideways_exposure_bar_count": regime["sideways_exposure_bar_count"],
        "cost_survival_rate": cost_stress["survival_rate"],
        "score": _round(score),
        "retention_decision": decision,
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
        "walk_forward": walk_forward,
        "annual": annual,
        "recent_segment": recent,
        "market_regime": regime,
        "cost_stress": cost_stress,
        "adverse_move_diagnostics": adverse,
    }


def cost_stress_summary(
    item: EvaluatedLongShortTrendRule,
    *,
    bars_4h: pd.DataFrame,
    initial_capital: float,
    base_cost_bps: float,
) -> dict[str, Any]:
    close = bars_4h["close"].astype(float)
    bar_returns = close.pct_change().fillna(0.0)
    scenarios = []
    for cost_bps in _cost_stress_bps(base_cost_bps):
        cost = item.turnover * (float(cost_bps) / 10_000.0)
        returns = (item.exposure * bar_returns - cost + item.funding_pnl).fillna(0.0)
        equity = float(initial_capital) * (1.0 + returns).cumprod()
        metrics = performance_metrics(
            strategy_returns=returns,
            equity=equity,
            exposure=item.exposure,
            turnover=item.turnover,
            cost=cost,
            interval=BASE_INTERVAL,
            initial_capital=initial_capital,
        )
        metrics["funding_return_pct"] = _round(float(item.funding_pnl.sum()) * 100.0)
        metrics["trading_cost_return_pct"] = _round(float(cost.sum()) * -100.0)
        survives = float(metrics["total_return_pct"]) > 0.0 and float(metrics["profit_factor"]) >= 1.0
        scenarios.append({"cost_bps": _round(cost_bps), "survives": bool(survives), "metrics": metrics})
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


def walk_forward_summary(item: EvaluatedLongShortTrendRule, *, initial_capital: float, fold_count: int = 4) -> dict[str, Any]:
    chunks = _sequential_chunks(item.returns.index, fold_count)
    rows = []
    for idx, chunk in enumerate(chunks, 1):
        if len(chunk) < 20:
            continue
        metrics = _slice_metrics(item, chunk, initial_capital=initial_capital)
        rows.append({"fold": idx, "row_count": int(len(chunk)), "passed": _segment_passed(metrics), "metrics": metrics})
    pass_rate = sum(1 for row in rows if row["passed"]) / len(rows) if rows else 0.0
    return {"fold_count": len(rows), "pass_rate": _round(pass_rate), "minimum_pass_rate": 0.5, "passed": pass_rate >= 0.5 if rows else False, "folds": rows}


def annual_summary(item: EvaluatedLongShortTrendRule, *, initial_capital: float) -> dict[str, Any]:
    rows = []
    for year, index in item.returns.groupby(item.returns.index.year).groups.items():
        idx = pd.DatetimeIndex(index)
        if len(idx) < 20:
            continue
        metrics = _slice_metrics(item, idx, initial_capital=initial_capital)
        rows.append({"year": int(year), "row_count": int(len(idx)), "passed": _segment_passed(metrics), "metrics": metrics})
    pass_rate = sum(1 for row in rows if row["passed"]) / len(rows) if rows else 0.0
    positive = [max(0.0, float(row["metrics"]["total_return_pct"])) for row in rows]
    best_share = max(positive) / sum(positive) if sum(positive) > 0.0 else 0.0
    latest = rows[-1] if rows else None
    return {
        "segment_type": "calendar_year",
        "segment_count": len(rows),
        "pass_rate": _round(pass_rate),
        "best_positive_year_share": _round(best_share),
        "latest_segment_passed": bool(latest["passed"]) if latest else False,
        "latest_segment_total_return_pct": latest["metrics"]["total_return_pct"] if latest else 0.0,
        "segments": rows,
    }


def recent_segment_summary(item: EvaluatedLongShortTrendRule, *, initial_capital: float, days: int = 180) -> dict[str, Any]:
    if item.returns.empty:
        return {"segment": f"latest_{days}d", "row_count": 0, "passed": False, "metrics": _empty_metrics(initial_capital)}
    start = item.returns.index.max() - pd.Timedelta(days=days)
    idx = item.returns.index[item.returns.index >= start]
    metrics = _slice_metrics(item, idx, initial_capital=initial_capital)
    return {"segment": f"latest_{days}d", "row_count": int(len(idx)), "passed": _segment_passed(metrics), "metrics": metrics}


def market_regime_summary(
    item: EvaluatedLongShortTrendRule,
    *,
    bars_4h: pd.DataFrame,
    bars_1d: pd.DataFrame,
    initial_capital: float,
) -> dict[str, Any]:
    labels = _market_regime_labels(bars_4h, bars_1d=bars_1d)
    rows = []
    for label in ["bull_trend", "bear_trend", "sideways_cash", "high_volatility_risk"]:
        idx = item.returns.index[labels.reindex(item.returns.index).fillna("sideways_cash") == label]
        if len(idx) < 20:
            continue
        metrics = _slice_metrics(item, pd.DatetimeIndex(idx), initial_capital=initial_capital)
        rows.append({"segment": label, "row_count": int(len(idx)), "passed": _segment_passed(metrics), "metrics": metrics})
    pass_rate = sum(1 for row in rows if row["passed"]) / len(rows) if rows else 0.0
    sideways_idx = item.exposure.index[labels.reindex(item.exposure.index).fillna("sideways_cash") == "sideways_cash"]
    sideways_exposure = int((item.exposure.loc[sideways_idx].abs() > 0.0).sum()) if len(sideways_idx) else 0
    return {
        "segment_type": "market_regime",
        "segment_count": len(rows),
        "pass_rate": _round(pass_rate),
        "sideways_exposure_bar_count": sideways_exposure,
        "sideways_exposure_policy": "should be near zero because neutral daily trend exits positions; residual bars can occur from next-bar execution shift",
        "segments": rows,
    }


def adverse_move_diagnostics(item: EvaluatedLongShortTrendRule, *, bars_4h: pd.DataFrame) -> dict[str, Any]:
    close = bars_4h["close"].astype(float)
    high = bars_4h["high"].astype(float)
    low = bars_4h["low"].astype(float)
    prev = close.shift(1).replace(0.0, math.nan)
    short_idx = item.exposure < 0.0
    long_idx = item.exposure > 0.0
    short_adverse = ((high / prev) - 1.0).where(short_idx).dropna()
    long_adverse = ((prev / low) - 1.0).where(long_idx).dropna()
    return {
        "long_exposure_bars": int(long_idx.sum()),
        "short_exposure_bars": int(short_idx.sum()),
        "max_long_intrabar_adverse_pct": _round((float(long_adverse.max()) if len(long_adverse) else 0.0) * 100.0),
        "max_short_intrabar_adverse_pct": _round((float(short_adverse.max()) if len(short_adverse) else 0.0) * 100.0),
        "short_squeeze_bar_count_10pct": int((short_adverse >= 0.10).sum()),
        "long_flush_bar_count_10pct": int((long_adverse >= 0.10).sum()),
        "hypothetical_liquidation_checks": [
            {
                "leverage": lev,
                "adverse_move_threshold_pct": _round((0.80 / lev) * 100.0),
                "breach_count": int((short_adverse >= 0.80 / lev).sum() + (long_adverse >= 0.80 / lev).sum()),
            }
            for lev in [1.0, 2.0, 3.0]
        ],
        "research_approximation": True,
    }


def render_long_short_trend_following_markdown(report: Mapping[str, Any]) -> str:
    gate = _mapping(report.get("gate"))
    validation = _mapping(report.get("validation_design"))
    input_info = _mapping(report.get("input"))
    refs = _mapping(report.get("reference_comparison"))
    formal_grid = _mapping(validation.get("formal_grid"))
    lines = [
        "# BTC Long/Short 趋势跟踪实验室",
        "",
        f"- 状态：`{report.get('status')}`",
        f"- 决策边界：`{report.get('decision')}`",
        f"- 运行档位：`{validation.get('run_profile')}`",
        f"- formal Donchian 网格数：`{formal_grid.get('formal_donchian_grid_count')}`",
        f"- 1H 样本行数：`{input_info.get('market_1h_rows')}`",
        f"- 4H 决策行数：`{input_info.get('bar_4h_rows')}`",
        f"- 候选总数：`{validation.get('candidate_count')}`",
        f"- long/short 候选数：`{validation.get('long_short_candidate_count')}`",
        f"- 同窗口参考数：`{validation.get('same_window_reference_count')}`",
        f"- 写入 paper 队列：`{gate.get('paper_queue_write_allowed')}`",
        f"- 解锁 live：`{gate.get('live_unlock_allowed')}`",
        "",
        "## 同窗口参考",
        "",
        f"- 最强 long/flat 参考：`{refs.get('best_long_flat_reference_id')}`，收益 `{refs.get('best_long_flat_total_return_pct')}%`。",
        f"- 最强 short/flat 参考：`{refs.get('best_short_flat_reference_id')}`，收益 `{refs.get('best_short_flat_total_return_pct')}%`。",
        f"- 最强 long/short 候选：`{refs.get('best_long_short_candidate_id')}`，收益 `{refs.get('best_long_short_total_return_pct')}%`。",
        "",
        "## Long/Short 研究观察名单",
        "",
    ]
    watchlist = list(report.get("long_short_research_watchlist", []))
    if not watchlist:
        lines.append("- 当前没有候选通过严格观察名单门槛；这不影响 research-only 对比继续使用。")
    for row in watchlist:
        lines.append(
            f"- `{row['candidate_id']}`：{row['label']}；收益 `{row['total_return_pct']}%`，"
            f"回撤 `{row['max_drawdown_pct']}%`，PF `{row['profit_factor']}`，"
            f"WF `{row['walk_forward_pass_rate']}`，结论 `{row['retention_decision']}`。"
        )
    lines.extend(["", "## 排名 Top 12", ""])
    lines.append("| 排名 | 候选 | 方向 | 收益 | 回撤 | PF | long bars | short bars | 成本存活 | 结论 |")
    lines.append("|---:|---|---|---:|---:|---:|---:|---:|---:|---|")
    for idx, row in enumerate(list(report.get("comparison_rows", []))[:12], 1):
        lines.append(
            f"| {idx} | `{row['variant_id']}` | `{row['direction_policy']}` | {row['total_return_pct']} | "
            f"{row['max_drawdown_pct']} | {row['profit_factor']} | {row['long_bar_count']} | {row['short_bar_count']} | "
            f"{row['cost_survival_rate']} | `{row['retention_decision']}` |"
        )
    lines.extend(
        [
            "",
            "## 复核边界",
            "",
            "- 本实验室只研究双向趋势跟踪表达，不生成策略骨架，不写 paper 队列，不解锁 live。",
            "- 做空不是因为行情差就做空；只有日线下跌趋势和 4H 价格趋势同时确认时才允许做空。",
            "- funding、OI、多空比只作为风险过滤和诊断，不作为独立开仓信号。",
            "- 所有候选进入任何门禁前，还需要单独补 liquidation buffer、funding 账本、交易所深度和 paper 验证证据。",
        ]
    )
    return "\n".join(lines) + "\n"


def _daily_trend_states(frame: pd.DataFrame, index: pd.DatetimeIndex, *, params: Mapping[str, Any]) -> tuple[pd.Series, pd.Series]:
    fast = int(params.get("daily_fast", 50))
    slow = int(params.get("daily_slow", 200))
    bull = _timeframe_bull(frame, index, fast=fast, slow=slow)
    bear = _timeframe_bear(frame, index, fast=fast, slow=slow)
    return bull, bear


def _apply_derivatives_risk_filters(
    long_entry: pd.Series,
    long_exit: pd.Series,
    short_entry: pd.Series,
    short_exit: pd.Series,
    *,
    derivatives_4h: pd.DataFrame,
    index: pd.DatetimeIndex,
    params: Mapping[str, Any],
) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series]:
    risk_mode = str(params.get("risk_filter_mode", "funding_oi_long_short" if params.get("use_derivatives_risk_filter", False) else "none"))
    if risk_mode == "none" or not bool(params.get("use_derivatives_risk_filter", False)):
        return long_entry, long_exit, short_entry, short_exit
    use_funding = risk_mode in {"funding", "funding_oi", "funding_oi_long_short"}
    use_oi = risk_mode in {"funding_oi", "funding_oi_long_short"}
    use_long_short = risk_mode == "funding_oi_long_short"
    long_ok = _long_derivatives_risk_ok(derivatives_4h, index, use_funding=use_funding, use_oi=use_oi, use_long_short=use_long_short)
    short_ok = _short_derivatives_risk_ok(derivatives_4h, index, use_funding=use_funding, use_oi=use_oi, use_long_short=use_long_short)
    long_entry = long_entry & long_ok
    short_entry = short_entry & short_ok
    if bool(params.get("use_risk_exit", False)):
        long_exit = long_exit | (~long_ok)
        short_exit = short_exit | (~short_ok)
    return long_entry, long_exit, short_entry, short_exit


def _apply_direction_policy(raw: pd.Series, direction_policy: str) -> pd.Series:
    if direction_policy == "long_short":
        return raw.clip(-1.0, 1.0)
    if direction_policy == "long_flat_reference":
        return raw.where(raw > 0.0, 0.0).clip(0.0, 1.0)
    if direction_policy == "short_flat_reference":
        return raw.where(raw < 0.0, 0.0).clip(-1.0, 0.0)
    raise ValueError(f"unsupported direction_policy: {direction_policy}")


def _reference_comparison(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    long_refs = [row for row in rows if row.get("direction_policy") == "long_flat_reference"]
    short_refs = [row for row in rows if row.get("direction_policy") == "short_flat_reference"]
    long_short = [row for row in rows if row.get("direction_policy") == "long_short"]
    best_long_ref = _best_by_score(long_refs)
    best_short_ref = _best_by_score(short_refs)
    best_long_short = _best_by_score(long_short)
    return {
        "best_long_flat_reference_id": best_long_ref.get("candidate_id"),
        "best_long_flat_total_return_pct": best_long_ref.get("total_return_pct", 0.0),
        "best_short_flat_reference_id": best_short_ref.get("candidate_id"),
        "best_short_flat_total_return_pct": best_short_ref.get("total_return_pct", 0.0),
        "best_long_short_candidate_id": best_long_short.get("candidate_id"),
        "best_long_short_total_return_pct": best_long_short.get("total_return_pct", 0.0),
        "best_long_short_minus_best_long_flat_pct": _round(float(best_long_short.get("total_return_pct", 0.0)) - float(best_long_ref.get("total_return_pct", 0.0))),
        "best_long_short_minus_best_short_flat_pct": _round(float(best_long_short.get("total_return_pct", 0.0)) - float(best_short_ref.get("total_return_pct", 0.0))),
        "interpretation": "same-window references are diagnostics only and do not authorize paper/live promotion",
    }


def _rank_with_reference_context(rows: Sequence[Mapping[str, Any]], *, reference_comparison: Mapping[str, Any]) -> list[dict[str, Any]]:
    enriched = []
    best_long = float(reference_comparison.get("best_long_flat_total_return_pct", 0.0) or 0.0)
    best_short = float(reference_comparison.get("best_short_flat_total_return_pct", 0.0) or 0.0)
    for row in rows:
        item = dict(row)
        item["return_diff_vs_best_long_flat_reference_pct"] = _round(float(item["total_return_pct"]) - best_long)
        item["return_diff_vs_best_short_flat_reference_pct"] = _round(float(item["total_return_pct"]) - best_short)
        enriched.append(item)
    return sorted(enriched, key=lambda row: (-float(row["score"]), str(row["candidate_id"])))


def _best_by_score(rows: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
    if not rows:
        return {}
    return sorted(rows, key=lambda row: (-float(row.get("score", 0.0)), str(row.get("candidate_id", ""))))[0]


def _retention_decision(
    item: EvaluatedLongShortTrendRule,
    *,
    walk_forward: Mapping[str, Any],
    annual: Mapping[str, Any],
    recent: Mapping[str, Any],
    regime: Mapping[str, Any],
    cost_stress: Mapping[str, Any],
    adverse: Mapping[str, Any],
) -> str:
    metrics = item.metrics
    if item.spec.branch == "same_window_reference":
        return "same_window_reference_only_no_paper_no_live"
    if float(metrics.get("total_return_pct", 0.0)) <= 0.0:
        return "reject_non_positive_total_return"
    if float(metrics.get("profit_factor", 0.0)) < 1.05:
        return "defer_profit_factor_too_thin"
    if float(metrics.get("max_drawdown_abs_pct", 0.0)) > 35.0:
        return "defer_drawdown_too_high"
    if int(metrics.get("long_bar_count", 0)) <= 0 or int(metrics.get("short_bar_count", 0)) <= 0:
        return "defer_not_truly_long_short"
    if float(walk_forward.get("pass_rate", 0.0)) < 0.5:
        return "defer_walk_forward_unstable"
    if float(annual.get("pass_rate", 0.0)) < 0.5:
        return "defer_annual_unstable"
    if not bool(recent.get("passed", False)):
        return "defer_recent_segment_failed"
    if float(annual.get("best_positive_year_share", 0.0)) > 0.70:
        return "defer_year_concentration_review"
    if float(cost_stress.get("survival_rate", 0.0)) < 0.67:
        return "defer_cost_stress_fragile"
    if float(adverse.get("max_short_intrabar_adverse_pct", 0.0)) > 15.0:
        return "defer_short_squeeze_risk_review"
    if float(regime.get("sideways_exposure_bar_count", 0.0)) > 6.0:
        return "defer_sideways_exposure_review"
    return "retain_long_short_research_watchlist_only"


def _score(
    metrics: Mapping[str, Any],
    *,
    walk_forward: Mapping[str, Any],
    annual: Mapping[str, Any],
    recent: Mapping[str, Any],
    regime: Mapping[str, Any],
    cost_stress: Mapping[str, Any],
    adverse: Mapping[str, Any],
) -> float:
    score = float(metrics.get("total_return_pct", 0.0))
    score += 8.0 * float(metrics.get("profit_factor", 0.0))
    score += 12.0 * float(walk_forward.get("pass_rate", 0.0))
    score += 8.0 * float(annual.get("pass_rate", 0.0))
    score += 6.0 * float(regime.get("pass_rate", 0.0))
    score += 10.0 if bool(recent.get("passed", False)) else -10.0
    score += 8.0 * float(cost_stress.get("survival_rate", 0.0))
    score -= max(0.0, float(metrics.get("max_drawdown_abs_pct", 0.0)) - 25.0) * 1.2
    score -= max(0.0, float(annual.get("best_positive_year_share", 0.0)) - 0.60) * 25.0
    score -= max(0.0, float(metrics.get("turnover", 0.0)) - 200.0) * 0.04
    score -= max(0.0, float(adverse.get("max_short_intrabar_adverse_pct", 0.0)) - 10.0) * 1.5
    score -= min(20.0, float(regime.get("sideways_exposure_bar_count", 0.0)) * 0.5)
    if int(metrics.get("long_bar_count", 0)) <= 0 or int(metrics.get("short_bar_count", 0)) <= 0:
        score -= 15.0
    return score


def _long_short_research_watchlist(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [dict(row) for row in rows if row.get("retention_decision") == "retain_long_short_research_watchlist_only"][:5]


def _baselines(*, bars_4h: pd.DataFrame, initial_capital: float, cost_bps: float) -> dict[str, Any]:
    close = bars_4h["close"].astype(float)
    raw_buy_hold = pd.Series(1.0, index=close.index)
    raw_cash = pd.Series(0.0, index=close.index)
    return {
        "buy_hold_spot": _baseline_metrics(raw_buy_hold, close=close, initial_capital=initial_capital, cost_bps=cost_bps),
        "cash": _baseline_metrics(raw_cash, close=close, initial_capital=initial_capital, cost_bps=cost_bps),
    }


def _baseline_metrics(raw: pd.Series, *, close: pd.Series, initial_capital: float, cost_bps: float) -> dict[str, Any]:
    exposure = raw.shift(1).fillna(0.0)
    turnover = exposure.diff().abs().fillna(exposure.abs())
    cost = turnover * (float(cost_bps) / 10_000.0)
    returns = (exposure * close.pct_change().fillna(0.0) - cost).fillna(0.0)
    equity = float(initial_capital) * (1.0 + returns).cumprod()
    return performance_metrics(strategy_returns=returns, equity=equity, exposure=exposure, turnover=turnover, cost=cost, interval=BASE_INTERVAL, initial_capital=initial_capital)


def _slice_metrics(item: EvaluatedLongShortTrendRule, index: pd.DatetimeIndex, *, initial_capital: float) -> dict[str, Any]:
    returns = item.returns.loc[index]
    equity = float(initial_capital) * (1.0 + returns).cumprod()
    metrics = performance_metrics(
        strategy_returns=returns,
        equity=equity,
        exposure=item.exposure.loc[index],
        turnover=item.turnover.loc[index],
        cost=item.trading_cost.loc[index],
        interval=BASE_INTERVAL,
        initial_capital=initial_capital,
    )
    metrics["funding_return_pct"] = _round(float(item.funding_pnl.loc[index].sum()) * 100.0) if len(index) else 0.0
    metrics["long_bar_count"] = int((item.exposure.loc[index] > 0.0).sum()) if len(index) else 0
    metrics["short_bar_count"] = int((item.exposure.loc[index] < 0.0).sum()) if len(index) else 0
    return metrics


def _segment_passed(metrics: Mapping[str, Any]) -> bool:
    return (
        float(metrics.get("total_return_pct", 0.0)) > 0.0
        and float(metrics.get("profit_factor", 0.0)) >= 1.0
        and float(metrics.get("max_drawdown_abs_pct", 0.0)) <= 35.0
    )


def _sequential_chunks(index: pd.DatetimeIndex, count: int) -> list[pd.DatetimeIndex]:
    if len(index) == 0 or count <= 0:
        return []
    size = max(1, len(index) // count)
    chunks = []
    for start in range(0, len(index), size):
        chunk = pd.DatetimeIndex(index[start : start + size])
        if len(chunk):
            chunks.append(chunk)
        if len(chunks) == count:
            break
    return chunks


def _market_regime_labels(bars_4h: pd.DataFrame, *, bars_1d: pd.DataFrame) -> pd.Series:
    close = bars_4h["close"].astype(float)
    daily_bull = _timeframe_bull(bars_1d, close.index, fast=50, slow=200)
    daily_bear = _timeframe_bear(bars_1d, close.index, fast=50, slow=200)
    vol_ok = _high_vol_ok(close, window=60)
    labels = pd.Series("sideways_cash", index=close.index)
    labels[daily_bull] = "bull_trend"
    labels[daily_bear] = "bear_trend"
    labels[~vol_ok] = "high_volatility_risk"
    return labels


def _stateful_long_short_with_atr_trail(
    long_entry: pd.Series,
    long_exit: pd.Series,
    short_entry: pd.Series,
    short_exit: pd.Series,
    *,
    close: pd.Series,
    atr: pd.Series,
    atr_mult: float,
    cooldown_bars: int = 0,
    use_failed_breakout_exit: bool = False,
    failure_exit_window: int = 6,
    long_failure_line: pd.Series | None = None,
    short_failure_line: pd.Series | None = None,
) -> pd.Series:
    out: list[float] = []
    position = 0.0
    high_since_entry = math.nan
    low_since_entry = math.nan
    entry_age = 0
    cooldown_remaining = 0
    aligned_numeric = (close.index.is_unique and atr.index.equals(close.index)
                       and pd.api.types.is_float_dtype(close.dtype)
                       and pd.api.types.is_float_dtype(atr.dtype))
    prices = close.to_numpy() if aligned_numeric else None
    atr_values = atr.to_numpy() if aligned_numeric else None
    for ordinal, (ts, le, lx, se, sx) in enumerate(zip(
        close.index,
        long_entry.reindex(close.index).fillna(False).astype(bool),
        long_exit.reindex(close.index).fillna(False).astype(bool),
        short_entry.reindex(close.index).fillna(False).astype(bool),
        short_exit.reindex(close.index).fillna(False).astype(bool),
    )):
        if aligned_numeric:
            price = float(prices[ordinal])
            value = float(atr_values[ordinal])
            current_atr = value if math.isfinite(value) else math.nan
        else:
            price = float(close.loc[ts])
            current_atr = _finite_at(atr, ts)
        if position > 0.0:
            entry_age += 1
            high_since_entry = max(high_since_entry, price) if math.isfinite(high_since_entry) else price
            if math.isfinite(current_atr) and price < high_since_entry - atr_mult * current_atr:
                lx = True
            if use_failed_breakout_exit and entry_age <= failure_exit_window and long_failure_line is not None:
                failure_line = _finite_at(long_failure_line, ts)
                if math.isfinite(failure_line) and price < failure_line:
                    lx = True
        elif position < 0.0:
            entry_age += 1
            low_since_entry = min(low_since_entry, price) if math.isfinite(low_since_entry) else price
            if math.isfinite(current_atr) and price > low_since_entry + atr_mult * current_atr:
                sx = True
            if use_failed_breakout_exit and entry_age <= failure_exit_window and short_failure_line is not None:
                failure_line = _finite_at(short_failure_line, ts)
                if math.isfinite(failure_line) and price > failure_line:
                    sx = True

        exited = False
        if position > 0.0 and (lx or se):
            position = 0.0
            high_since_entry = math.nan
            entry_age = 0
            exited = True
        if position < 0.0 and (sx or le):
            position = 0.0
            low_since_entry = math.nan
            entry_age = 0
            exited = True
        if exited:
            cooldown_remaining = max(0, int(cooldown_bars))

        if position == 0.0 and not exited and cooldown_remaining <= 0:
            if le and not se:
                position = 1.0
                high_since_entry = price
                entry_age = 0
            elif se and not le:
                position = -1.0
                low_since_entry = price
                entry_age = 0
        out.append(position)
        if position == 0.0 and cooldown_remaining > 0:
            cooldown_remaining -= 1
    return pd.Series(out, index=close.index)


def _finite_at(series: pd.Series, ts: pd.Timestamp) -> float:
    try:
        value = float(series.loc[ts])
    except Exception:
        return math.nan
    return value if math.isfinite(value) else math.nan


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


def _short_derivatives_risk_ok(
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
        floor = funding.rolling(180, min_periods=24).quantile(0.20).shift(1)
        ok = ok & ((funding >= floor) | floor.isna() | funding.isna())
    if use_oi:
        oi = _numeric_col(derivatives, "open_interest_usd", index)
        oi_z = _rolling_z(oi.diff(), window=72)
        ok = ok & ((oi_z <= 2.0) | oi_z.isna())
    if use_long_short:
        long_short = _numeric_col(derivatives, "long_short_ratio", index)
        floor = long_short.rolling(180, min_periods=24).quantile(0.20).shift(1)
        ok = ok & ((long_short >= floor) | floor.isna() | long_short.isna())
    return ok.fillna(True).astype(bool)


def _funding_pnl(exposure: pd.Series, derivatives_4h: pd.DataFrame) -> pd.Series:
    funding = _numeric_col(derivatives_4h, "funding_rate", exposure.index).fillna(0.0)
    return (-exposure * funding * (BAR_HOURS / FUNDING_INTERVAL_HOURS)).fillna(0.0)


def _timeframe_bull(frame: pd.DataFrame, index: pd.DatetimeIndex, *, fast: int, slow: int) -> pd.Series:
    if frame.empty or "close" not in frame:
        return pd.Series(False, index=index)
    close = frame["close"].astype(float)
    fast_ema = _ema(close, fast)
    slow_ema = _ema(close, slow)
    return ((fast_ema > slow_ema) & (close > slow_ema)).reindex(index, method="ffill").fillna(False).astype(bool)


def _timeframe_bear(frame: pd.DataFrame, index: pd.DatetimeIndex, *, fast: int, slow: int) -> pd.Series:
    if frame.empty or "close" not in frame:
        return pd.Series(False, index=index)
    close = frame["close"].astype(float)
    fast_ema = _ema(close, fast)
    slow_ema = _ema(close, slow)
    return ((fast_ema < slow_ema) & (close < slow_ema)).reindex(index, method="ffill").fillna(False).astype(bool)


def _ema_ribbon_long(close: pd.Series) -> pd.Series:
    return (_ema(close, 21) > _ema(close, 50)) & (_ema(close, 50) > _ema(close, 100)) & (_ema(close, 100) > _ema(close, 200)) & (close > _ema(close, 200))


def _ema_ribbon_bear(close: pd.Series) -> pd.Series:
    return (_ema(close, 21) < _ema(close, 50)) & (_ema(close, 50) < _ema(close, 100)) & (_ema(close, 100) < _ema(close, 200)) & (close < _ema(close, 200))


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


def _numeric_col(frame: pd.DataFrame, column: str, index: pd.DatetimeIndex) -> pd.Series:
    if column not in frame:
        return pd.Series(math.nan, index=index)
    return pd.to_numeric(frame[column], errors="coerce").reindex(index)


def _rolling_z(values: pd.Series, *, window: int) -> pd.Series:
    mean = values.rolling(window).mean()
    std = values.rolling(window).std(ddof=0)
    return (values - mean) / std.replace(0.0, math.nan)


def _empty_metrics(initial_capital: float) -> dict[str, Any]:
    return performance_metrics(
        strategy_returns=pd.Series(dtype=float),
        equity=pd.Series(dtype=float),
        exposure=pd.Series(dtype=float),
        turnover=pd.Series(dtype=float),
        cost=pd.Series(dtype=float),
        interval=BASE_INTERVAL,
        initial_capital=initial_capital,
    )


def _cost_stress_bps(base_cost_bps: float) -> list[float]:
    return [float(base_cost_bps), float(base_cost_bps) * 2.0, float(base_cost_bps) * 5.0]


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
    warnings = ["btc_long_short_trend_following_lab_research_only_no_paper_no_live"]
    if any(float(row.get("cost_survival_rate", 0.0)) < 0.67 for row in rows):
        warnings.append("some_candidates_cost_stress_fragile")
    if any(float(row.get("best_positive_year_share", 0.0)) > 0.70 for row in rows):
        warnings.append("some_candidates_year_concentrated")
    if any(float(row.get("adverse_move_diagnostics", {}).get("max_short_intrabar_adverse_pct", 0.0)) > 10.0 for row in rows):
        warnings.append("short_squeeze_adverse_move_review_required")
    warnings.append("derivatives_sentiment_is_risk_filter_only")
    return warnings


def _grid_fieldnames() -> list[str]:
    return [
        "candidate_id",
        "family_id",
        "variant_id",
        "branch",
        "direction_policy",
        "instrument_assumption",
        "optimization_stage",
        "label",
        "total_return_pct",
        "annual_return_pct",
        "max_drawdown_pct",
        "max_drawdown_abs_pct",
        "profit_factor",
        "sharpe_ratio",
        "average_exposure",
        "average_net_exposure",
        "long_bar_count",
        "short_bar_count",
        "bars_with_exposure",
        "turnover",
        "fee_return_pct",
        "funding_return_pct",
        "walk_forward_pass_rate",
        "annual_pass_rate",
        "best_positive_year_share",
        "recent_segment_passed",
        "recent_segment_total_return_pct",
        "market_regime_pass_rate",
        "sideways_exposure_bar_count",
        "cost_survival_rate",
        "return_diff_vs_best_long_flat_reference_pct",
        "return_diff_vs_best_short_flat_reference_pct",
        "score",
        "retention_decision",
        "paper_queue_write_allowed",
        "live_unlock_allowed",
    ]


def _write_csv(path: Path, fieldnames: Sequence[str], rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fieldnames), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _portable_path(path: Path) -> str:
    try:
        return str(path.relative_to(Path.cwd())).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def _git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=Path.cwd(), text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return "unknown"


def _ts(value: Any) -> str:
    return pd.Timestamp(value).isoformat()


def _round(value: float, digits: int = 6) -> float:
    if value is None or not math.isfinite(float(value)):
        return 0.0
    return round(float(value), digits)
