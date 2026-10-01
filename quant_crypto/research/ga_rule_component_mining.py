from __future__ import annotations

import csv
import hashlib
import json
import math
import random
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd

from quant_crypto.research.multi_timeframe_rule_lab import (
    BASE_COST_BPS,
    INITIAL_CAPITAL,
    MultiTimeframeRuleSpec,
    aggregate_ohlcv,
    align_derivatives_to_index,
    evaluate_mtf_rule,
    load_market_1h,
    multi_timeframe_rule_specs,
)
from quant_crypto.research.simple_trend_rule_lab import (
    DEFAULT_DERIVATIVES_ROWS,
    DEFAULT_MARKET_DB,
    EXCHANGE,
    SYMBOL,
    evaluate_rule as evaluate_simple_rule,
    simple_trend_rule_specs,
)


SCHEMA_VERSION = "btc_ga_rule_component_mining_v2"
DEFAULT_OUTPUT_DIR = Path("artifacts/btc_ga_rule_component_mining/latest")
DEFAULT_REPORT_PATH = DEFAULT_OUTPUT_DIR / "ga_rule_component_mining_report.json"
DEFAULT_CANDIDATES_PATH = DEFAULT_OUTPUT_DIR / "candidate_rule_genomes.json"
DEFAULT_GRID_PATH = DEFAULT_OUTPUT_DIR / "ga_rule_component_mining_grid.csv"
DEFAULT_MARKDOWN_PATH = DEFAULT_OUTPUT_DIR / "ga_rule_component_mining_summary_cn.md"

SOURCE_INTERVAL = "1h"
BASE_INTERVAL = "4h"
GA_RUN_PROFILES = {
    "smoke": {"population_size": 64, "generations": 20},
    "formal": {"population_size": 128, "generations": 60},
    "extended": {"population_size": 256, "generations": 100},
}
COOLDOWN_BAR_GRID = (0, 6, 12)
MAX_ENTRY_CONDITIONS = 6
REQUIRED_RULE_SOURCE_FAMILIES = {
    "donchian_turtle",
    "atr_channel",
    "supertrend",
    "squeeze_breakout",
    "ma_ribbon",
    "oi_confirmed_atr_breakout",
    "multi_tf_trend_confirm",
    "multi_tf_turtle",
    "trend_pullback_reentry",
    "multi_tf_squeeze_breakout",
    "regime_router",
    "derivatives_risk_filtered_trend",
    "short_research_branch",
    "vote_ensemble",
}


def _resolve_ga_profile(
    run_profile: str,
    *,
    population_size: int | None,
    generations: int | None,
) -> dict[str, int]:
    if run_profile not in GA_RUN_PROFILES:
        allowed = ",".join(sorted(GA_RUN_PROFILES))
        raise ValueError(f"ga_run_profile_not_allowed:{run_profile};allowed={allowed}")
    resolved = dict(GA_RUN_PROFILES[run_profile])
    if population_size is not None:
        resolved["population_size"] = int(population_size)
    if generations is not None:
        resolved["generations"] = int(generations)
    if resolved["population_size"] <= 0 or resolved["generations"] <= 0:
        raise ValueError("ga_population_and_generations_must_be_positive")
    return resolved


@dataclass(frozen=True)
class RulePrimitiveSpec:
    primitive_id: str
    kind: str
    value_type: str
    source_rules: tuple[str, ...]
    description_zh: str
    comparator: str = "gt"
    threshold_grid: tuple[float, ...] = (0.5,)


@dataclass(frozen=True)
class RuleCondition:
    primitive_id: str
    comparator: str
    threshold: float

    def to_dict(self) -> dict[str, Any]:
        return {"primitive_id": self.primitive_id, "comparator": self.comparator, "threshold": _round(self.threshold)}


@dataclass(frozen=True)
class RuleGenome:
    entry_conditions: tuple[RuleCondition, ...]
    vote_threshold: int
    exit_conditions: tuple[RuleCondition, ...]
    exit_vote_threshold: int
    genome_type: str = "vote_rule"
    regime_rules: tuple[tuple[str, "RuleGenome"], ...] = ()
    cooldown_bars: int = 0
    sizing_mode: str = "binary"

    @property
    def genome_hash(self) -> str:
        return hashlib.sha1(json.dumps(self.to_dict(), sort_keys=True).encode("utf-8")).hexdigest()[:12]

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "entry_conditions": [item.to_dict() for item in self.entry_conditions],
            "vote_threshold": int(self.vote_threshold),
            "exit_conditions": [item.to_dict() for item in self.exit_conditions],
            "exit_vote_threshold": int(self.exit_vote_threshold),
            "genome_type": self.genome_type,
            "cooldown_bars": int(self.cooldown_bars),
            "sizing_mode": self.sizing_mode,
        }
        if self.regime_rules:
            payload["regime_rules"] = [{"regime": regime, "genome": genome.to_dict()} for regime, genome in self.regime_rules]
        return payload


@dataclass
class EvaluatedGenome:
    genome: RuleGenome
    raw_signal: pd.Series
    exposure: pd.Series
    returns: pd.Series
    turnover: pd.Series
    cost: pd.Series
    equity: pd.Series
    metrics: dict[str, Any]


def build_btc_ga_rule_component_mining(
    *,
    market_db_path: Path = DEFAULT_MARKET_DB,
    derivatives_rows_path: Path = DEFAULT_DERIVATIVES_ROWS,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    generated_at_utc: datetime | None = None,
    seed: int = 20260629,
    run_profile: str = "smoke",
    population_size: int | None = None,
    generations: int | None = None,
    selected_candidate_count: int = 12,
    initial_capital: float = INITIAL_CAPITAL,
    base_cost_bps: float = BASE_COST_BPS,
) -> dict[str, Any]:
    generated = generated_at_utc or datetime.now(timezone.utc)
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / DEFAULT_REPORT_PATH.name
    candidates_path = output_dir / DEFAULT_CANDIDATES_PATH.name
    grid_path = output_dir / DEFAULT_GRID_PATH.name
    markdown_path = output_dir / DEFAULT_MARKDOWN_PATH.name

    source_1h = load_market_1h(market_db_path)
    bars_4h = aggregate_ohlcv(source_1h, interval_hours=4)
    bars_1d = aggregate_ohlcv(source_1h, interval_hours=24)
    derivatives_4h = align_derivatives_to_index(derivatives_rows_path, bars_4h.index)
    primitive_frame, primitive_catalog = build_rule_primitive_frame(source_1h, bars_4h, bars_1d, derivatives_4h)
    profile_config = _resolve_ga_profile(run_profile, population_size=population_size, generations=generations)
    resolved_population_size = int(profile_config["population_size"])
    resolved_generations = int(profile_config["generations"])

    missing_sources = sorted(REQUIRED_RULE_SOURCE_FAMILIES - set().union(*(item.source_rules for item in primitive_catalog)))
    blockers = [f"primitive_source_family_missing:{name}" for name in missing_sources]
    train_end = max(1, int(len(bars_4h) * 0.70))
    train_index = bars_4h.index[:train_end]
    validation_index = bars_4h.index[train_end:]
    rng = random.Random(seed)
    run = _run_ga(
        primitive_frame=primitive_frame,
        bars_4h=bars_4h,
        rng=rng,
        population_size=resolved_population_size,
        generations=resolved_generations,
        initial_capital=initial_capital,
        cost_bps=base_cost_bps,
        train_index=train_index,
    )
    candidates = _select_candidates(
        run["candidate_pool"],
        primitive_frame=primitive_frame,
        bars_4h=bars_4h,
        validation_index=validation_index,
        selected_candidate_count=selected_candidate_count,
        initial_capital=initial_capital,
        cost_bps=base_cost_bps,
    )
    sizing_diagnostics = _position_sizing_diagnostics(
        candidates,
        primitive_frame=primitive_frame,
        bars_4h=bars_4h,
        initial_capital=initial_capital,
        cost_bps=base_cost_bps,
    )
    handwritten = _handwritten_baseline_comparison(
        bars_1h=source_1h,
        bars_4h=bars_4h,
        bars_1d=bars_1d,
        derivatives_4h=derivatives_4h,
        validation_index=validation_index,
        initial_capital=initial_capital,
        cost_bps=base_cost_bps,
    )
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated.isoformat(),
        "status": "blocked" if blockers else "complete_research_only",
        "decision": "btc_ga_rule_component_mining_research_only_no_paper_no_live",
        "scope": "btc_ga_rule_component_combination_and_threshold_search",
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
            "bar_4h_start": _ts(bars_4h.index.min()) if len(bars_4h) else None,
            "bar_4h_end": _ts(bars_4h.index.max()) if len(bars_4h) else None,
            "derivatives_visible_rows": int(derivatives_4h["open_interest_usd"].notna().sum())
            if "open_interest_usd" in derivatives_4h
            else 0,
            "completed_bar_rule": "1h completed bars only; 4h/1d derived from completed 1h chunks",
            "derivatives_available_time_rule": "available_time <= 4h decision_time",
        },
        "ga_config": {
            "seed": int(seed),
            "run_profile": str(run_profile),
            "profile_defaults": GA_RUN_PROFILES,
            "population_size": resolved_population_size,
            "generations": resolved_generations,
            "trial_count": int(run["trial_count"]),
            "rejected_count": int(run["rejected_count"]),
            "seeded_genome_count": int(run["seeded_genome_count"]),
            "max_entry_conditions": MAX_ENTRY_CONDITIONS,
            "candidate_pool_count": int(len(run["candidate_pool"])),
            "selected_candidate_count": int(len(candidates)),
            "train_fraction": 0.70,
            "train_start": _ts(train_index.min()) if len(train_index) else None,
            "train_end": _ts(train_index.max()) if len(train_index) else None,
            "validation_start": _ts(validation_index.min()) if len(validation_index) else None,
            "validation_end": _ts(validation_index.max()) if len(validation_index) else None,
            "selection_policy": "handwritten seeds plus random genomes evolve only on train segment; validation, walk-forward, costs and baseline comparison are evaluation only",
        },
        "primitive_catalog": [primitive_to_dict(item) for item in primitive_catalog],
        "primitive_source_coverage": _primitive_source_coverage(primitive_catalog),
        "guardrails": _guardrails(),
        "gate": {
            "paper_queue_write_allowed": False,
            "paper_candidate_created": False,
            "live_unlock_allowed": False,
            "live_order_allowed": False,
            "oms_access_allowed": False,
            "broker_access_allowed": False,
            "strategy_skeleton_generated": False,
            "reason": "GA rule component mining is research-only; selected genomes require separate manual review",
        },
        "handwritten_rule_baseline_comparison": handwritten,
        "candidate_rule_genomes": candidates,
        "position_sizing_diagnostics": sizing_diagnostics,
        "blockers": blockers,
        "warnings": _warnings(candidates),
        "outputs": {
            "json": _portable_path(report_path),
            "candidate_rule_genomes": _portable_path(candidates_path),
            "grid_csv": _portable_path(grid_path),
            "summary_cn": _portable_path(markdown_path),
        },
    }
    _write_json(report_path, report)
    _write_json(
        candidates_path,
        {
            "schema_version": "btc_ga_rule_component_candidates_v2",
            "scope": "research_only_rule_genomes",
            "candidate_count": len(candidates),
            "candidates": candidates,
            "paper_candidate_generated": False,
            "paper_queue_write_allowed": False,
            "live_enabled": False,
        },
    )
    _write_csv(grid_path, _grid_fieldnames(), candidates)
    _write_text(markdown_path, render_ga_rule_component_mining_markdown(report))
    return report


def build_rule_primitive_frame(
    bars_1h: pd.DataFrame,
    bars_4h: pd.DataFrame,
    bars_1d: pd.DataFrame,
    derivatives_4h: pd.DataFrame,
) -> tuple[pd.DataFrame, list[RulePrimitiveSpec]]:
    close = bars_4h["close"].astype(float)
    high = bars_4h["high"].astype(float)
    low = bars_4h["low"].astype(float)
    volume = bars_4h["volume"].astype(float)
    close_1h = bars_1h["close"].astype(float)
    frame = pd.DataFrame(index=close.index)
    atr20 = _atr(bars_4h, 20)
    ema21 = _ema(close, 21)
    ema50 = _ema(close, 50)
    ema100 = _ema(close, 100)
    ema200 = _ema(close, 200)
    daily50 = _daily_ema(bars_1d, close.index, 50)
    daily200 = _daily_ema(bars_1d, close.index, 200)
    daily34 = _daily_ema(bars_1d, close.index, 34)
    daily144 = _daily_ema(bars_1d, close.index, 144)
    donchian20 = high.shift(1).rolling(120).max()
    donchian55 = high.shift(1).rolling(330).max()
    donchian10_low = low.shift(1).rolling(60).min()
    bb_mid = close.rolling(40).mean()
    bb_std = close.rolling(40).std(ddof=0)
    bb_upper = bb_mid + 2.0 * bb_std
    bb_lower = bb_mid - 2.0 * bb_std
    kc_mid = _ema(close, 40)
    kc_upper = kc_mid + 1.5 * atr20
    kc_lower = kc_mid - 1.5 * atr20
    squeeze_on = (bb_upper < kc_upper) & (bb_lower > kc_lower)
    recent_squeeze = squeeze_on.shift(1).rolling(18, min_periods=1).max().fillna(False).astype(bool)
    funding = _numeric_col(derivatives_4h, "funding_rate", close.index)
    oi = _numeric_col(derivatives_4h, "open_interest_usd", close.index)
    long_short = _numeric_col(derivatives_4h, "long_short_ratio", close.index)

    frame["daily_ema50_gt_200"] = (daily50 > daily200).astype(float)
    frame["daily_ema34_gt_144"] = (daily34 > daily144).astype(float)
    frame["daily_not_bear_50_200"] = (~((daily50 < daily200) & (close < daily200))).astype(float)
    frame["daily_bear_50_200"] = ((daily50 < daily200) & (close < daily200)).astype(float)
    frame["ema_ribbon_4h_long"] = ((ema21 > ema50) & (ema50 > ema100) & (ema100 > ema200) & (close > ema200)).astype(float)
    frame["ema_ribbon_4h_bear"] = ((ema21 < ema50) & (ema50 < ema100) & (ema100 < ema200) & (close < ema200)).astype(float)
    for fast, mid, slow in [(8, 21, 55), (13, 34, 89), (21, 50, 100), (34, 72, 144)]:
        frame[f"ema_ribbon_long_{fast}_{mid}_{slow}"] = ((_ema(close, fast) > _ema(close, mid)) & (_ema(close, mid) > _ema(close, slow)) & (close > _ema(close, slow))).astype(float)
    for fast, slow in [(34, 144), (50, 200), (55, 233)]:
        frame[f"daily_ema{fast}_gt_{slow}"] = (_daily_ema(bars_1d, close.index, fast) > _daily_ema(bars_1d, close.index, slow)).astype(float)
    frame["donchian_20d_breakout"] = (close > donchian20).astype(float)
    frame["donchian_55d_breakout"] = (close > donchian55).astype(float)
    frame["donchian_20d_margin"] = (close / donchian20.replace(0.0, math.nan) - 1.0).clip(-1.0, 1.0)
    for window in [48, 72, 96, 120, 180, 240, 330]:
        channel_high = high.shift(1).rolling(window).max()
        frame[f"donchian_breakout_w{window}"] = (close > channel_high).astype(float)
        frame[f"donchian_margin_w{window}"] = (close / channel_high.replace(0.0, math.nan) - 1.0).clip(-1.0, 1.0)
    frame["atr_channel_breakout"] = (close > _ema(close, 96) + 1.5 * atr20).astype(float)
    frame["atr_channel_distance"] = ((close - _ema(close, 96)) / atr20.replace(0.0, math.nan)).clip(-10.0, 10.0)
    for k in [1.0, 1.2, 1.5, 2.0]:
        key = str(k).replace(".", "p")
        frame[f"atr_channel_breakout_k{key}"] = (close > _ema(close, 96) + k * atr20).astype(float)
    frame["supertrend_4h_long"] = _supertrend_signal(bars_4h, window=10, multiplier=3.0).astype(float)
    frame["squeeze_recent"] = recent_squeeze.astype(float)
    frame["squeeze_breakout"] = (recent_squeeze & (close > high.shift(1).rolling(48).max())).astype(float)
    frame["pullback_ema50_reclaim"] = ((low <= ema50 * 1.012) & (close > ema50) & (close > close.shift(1))).astype(float)
    frame["pullback_ema100_reclaim"] = ((low <= ema100 * 1.018) & (close > ema100) & (close > close.shift(1))).astype(float)
    frame["one_hour_momentum_positive"] = _to_4h(((close_1h > _ema(close_1h, 24)) & (close_1h.pct_change(6) > 0.0)).astype(float), close.index)
    frame["vol_not_extreme_60"] = _high_vol_ok(close, window=60).astype(float)
    frame["funding_not_crowded"] = _cap_ok(funding, window=180, quantile=0.80).astype(float)
    frame["oi_not_extreme"] = ((_rolling_z(oi.diff(), window=72) <= 2.0) | _rolling_z(oi.diff(), window=72).isna()).astype(float)
    frame["long_short_not_crowded"] = _cap_ok(long_short, window=180, quantile=0.85).astype(float)
    frame["funding_z"] = _rolling_z(funding, window=72).clip(-10.0, 10.0)
    frame["oi_delta_z"] = _rolling_z(oi.diff(), window=72).clip(-10.0, 10.0)
    frame["long_short_z"] = _rolling_z(long_short, window=72).clip(-10.0, 10.0)
    frame["momentum_24h_z"] = _rolling_z(close.pct_change(6), window=72).clip(-10.0, 10.0)
    frame["realized_vol_24h_z"] = _rolling_z(close.pct_change().rolling(6).std(ddof=0), window=72).clip(-10.0, 10.0)
    frame["vote_count_core"] = (
        frame["ema_ribbon_4h_long"]
        + frame["donchian_20d_breakout"]
        + frame["atr_channel_breakout"]
        + frame["funding_not_crowded"]
        + frame["vol_not_extreme_60"]
    )
    frame["exit_close_below_ema50"] = (close < ema50).astype(float)
    frame["exit_close_below_ema100"] = (close < ema100).astype(float)
    frame["exit_1h_below_ema24"] = _to_4h((close_1h < _ema(close_1h, 24)).astype(float), close.index)
    frame["exit_donchian_10d_low"] = (close < donchian10_low).astype(float)
    frame["exit_atr_trail_3x"] = (close < close.shift(1).rolling(60).max() - 3.0 * atr20).astype(float)
    for window in [24, 48, 60, 90, 120]:
        frame[f"exit_donchian_low_w{window}"] = (close < low.shift(1).rolling(window).min()).astype(float)
    for mult in [1.5, 2.0, 2.5, 3.0, 4.0]:
        key = str(mult).replace(".", "p")
        frame[f"exit_atr_trail_{key}x"] = (close < close.shift(1).rolling(60).max() - mult * atr20).astype(float)
    frame["exit_failed_breakout_12"] = ((close < donchian20) & (frame["donchian_20d_breakout"].shift(1).rolling(12, min_periods=1).max() > 0.0)).astype(float)
    frame["exit_failed_breakout_24"] = ((close < donchian20) & (frame["donchian_20d_breakout"].shift(1).rolling(24, min_periods=1).max() > 0.0)).astype(float)
    frame["exit_daily_bear"] = frame["daily_bear_50_200"]
    frame = frame.replace([math.inf, -math.inf], math.nan).fillna(0.0)
    return frame, rule_primitive_catalog()


def rule_primitive_catalog() -> list[RulePrimitiveSpec]:
    catalog = [
        RulePrimitiveSpec("daily_ema50_gt_200", "entry_filter", "bool", ("multi_tf_trend_confirm", "multi_tf_turtle", "trend_pullback_reentry"), "日线 EMA50 大于 EMA200"),
        RulePrimitiveSpec("daily_ema34_gt_144", "entry_filter", "bool", ("regime_router",), "较快日线多头状态"),
        RulePrimitiveSpec("daily_not_bear_50_200", "entry_filter", "bool", ("multi_tf_squeeze_breakout",), "日线不是熊市"),
        RulePrimitiveSpec("daily_bear_50_200", "short_entry", "bool", ("short_research_branch",), "日线熊市状态"),
        RulePrimitiveSpec("ema_ribbon_4h_long", "entry_signal", "bool", ("ma_ribbon", "multi_tf_trend_confirm", "derivatives_risk_filtered_trend", "vote_ensemble"), "4H EMA 多头排列"),
        RulePrimitiveSpec("ema_ribbon_4h_bear", "short_entry", "bool", ("short_research_branch",), "4H EMA 空头排列"),
        RulePrimitiveSpec("donchian_20d_breakout", "entry_signal", "bool", ("donchian_turtle", "multi_tf_turtle", "vote_ensemble"), "4H 20 日 Donchian 突破"),
        RulePrimitiveSpec("donchian_55d_breakout", "entry_signal", "bool", ("donchian_turtle",), "4H 55 日 Donchian 突破"),
        RulePrimitiveSpec("donchian_20d_margin", "entry_numeric", "numeric", ("donchian_turtle",), "4H Donchian 突破幅度", "gt", (0.0, 0.002, 0.005, 0.01)),
        RulePrimitiveSpec("atr_channel_breakout", "entry_signal", "bool", ("atr_channel", "vote_ensemble"), "4H ATR 通道突破"),
        RulePrimitiveSpec("atr_channel_distance", "entry_numeric", "numeric", ("atr_channel",), "价格相对 ATR 通道中线距离", "gt", (0.8, 1.0, 1.2, 1.5)),
        RulePrimitiveSpec("supertrend_4h_long", "entry_signal", "bool", ("supertrend",), "4H SuperTrend 多头状态"),
        RulePrimitiveSpec("squeeze_recent", "entry_filter", "bool", ("squeeze_breakout", "multi_tf_squeeze_breakout"), "近期波动压缩"),
        RulePrimitiveSpec("squeeze_breakout", "entry_signal", "bool", ("squeeze_breakout", "multi_tf_squeeze_breakout"), "压缩后向上突破"),
        RulePrimitiveSpec("pullback_ema50_reclaim", "entry_signal", "bool", ("trend_pullback_reentry",), "回撤到 EMA50 附近后重新站上"),
        RulePrimitiveSpec("pullback_ema100_reclaim", "entry_signal", "bool", ("trend_pullback_reentry",), "回撤到 EMA100 附近后重新站上"),
        RulePrimitiveSpec("one_hour_momentum_positive", "entry_filter", "bool", ("multi_tf_trend_confirm", "trend_pullback_reentry"), "1H 动量转正"),
        RulePrimitiveSpec("vol_not_extreme_60", "risk_filter", "bool", ("ma_ribbon", "multi_tf_turtle", "regime_router", "vote_ensemble"), "60 根 4H 波动不过热"),
        RulePrimitiveSpec("funding_not_crowded", "risk_filter", "bool", ("oi_confirmed_atr_breakout", "multi_tf_turtle", "derivatives_risk_filtered_trend", "vote_ensemble"), "资金费率不拥挤"),
        RulePrimitiveSpec("oi_not_extreme", "risk_filter", "bool", ("oi_confirmed_atr_breakout", "derivatives_risk_filtered_trend", "vote_ensemble"), "OI 加速不过热"),
        RulePrimitiveSpec("long_short_not_crowded", "risk_filter", "bool", ("oi_confirmed_atr_breakout", "derivatives_risk_filtered_trend"), "多空比不拥挤"),
        RulePrimitiveSpec("funding_z", "entry_numeric", "numeric", ("derivatives_risk_filtered_trend",), "资金费率 rolling zscore", "lt", (-1.0, 0.0, 1.0, 2.0)),
        RulePrimitiveSpec("oi_delta_z", "entry_numeric", "numeric", ("derivatives_risk_filtered_trend",), "OI 变化 rolling zscore", "lt", (0.0, 1.0, 2.0, 3.0)),
        RulePrimitiveSpec("long_short_z", "entry_numeric", "numeric", ("derivatives_risk_filtered_trend",), "多空比 rolling zscore", "lt", (0.0, 1.0, 2.0)),
        RulePrimitiveSpec("momentum_24h_z", "entry_numeric", "numeric", ("multi_tf_trend_confirm",), "24H 动量 rolling zscore", "gt", (-0.5, 0.0, 0.5, 1.0)),
        RulePrimitiveSpec("realized_vol_24h_z", "entry_numeric", "numeric", ("regime_router",), "24H 波动 rolling zscore", "lt", (0.0, 1.0, 2.0)),
        RulePrimitiveSpec("vote_count_core", "entry_numeric", "numeric", ("vote_ensemble",), "核心规则投票数量", "gt", (2.5, 3.5, 4.5)),
        RulePrimitiveSpec("exit_close_below_ema50", "exit_signal", "bool", ("multi_tf_trend_confirm", "regime_router"), "4H 跌破 EMA50 退出"),
        RulePrimitiveSpec("exit_close_below_ema100", "exit_signal", "bool", ("ma_ribbon", "trend_pullback_reentry"), "4H 跌破 EMA100 退出"),
        RulePrimitiveSpec("exit_1h_below_ema24", "exit_signal", "bool", ("multi_tf_trend_confirm", "trend_pullback_reentry"), "1H 跌破 EMA24 退出"),
        RulePrimitiveSpec("exit_donchian_10d_low", "exit_signal", "bool", ("donchian_turtle", "multi_tf_turtle"), "4H 跌破 10 日 Donchian 低点退出"),
        RulePrimitiveSpec("exit_atr_trail_3x", "exit_signal", "bool", ("atr_channel", "multi_tf_turtle", "trend_pullback_reentry"), "3 倍 ATR 移动退出"),
        RulePrimitiveSpec("exit_daily_bear", "exit_signal", "bool", ("regime_router", "short_research_branch"), "日线熊市退出多头"),
    ]
    for fast, mid, slow in [(8, 21, 55), (13, 34, 89), (21, 50, 100), (34, 72, 144)]:
        catalog.append(RulePrimitiveSpec(f"ema_ribbon_long_{fast}_{mid}_{slow}", "entry_signal", "bool", ("ma_ribbon", "multi_tf_trend_confirm"), f"4H EMA 多头排列 {fast}/{mid}/{slow}"))
    for fast, slow in [(34, 144), (50, 200), (55, 233)]:
        catalog.append(RulePrimitiveSpec(f"daily_ema{fast}_gt_{slow}", "entry_filter", "bool", ("multi_tf_trend_confirm", "multi_tf_turtle", "regime_router"), f"日线 EMA{fast} 大于 EMA{slow}"))
    for window in [48, 72, 96, 120, 180, 240, 330]:
        catalog.append(RulePrimitiveSpec(f"donchian_breakout_w{window}", "entry_signal", "bool", ("donchian_turtle", "multi_tf_turtle"), f"4H Donchian {window} 根突破"))
        catalog.append(RulePrimitiveSpec(f"donchian_margin_w{window}", "entry_numeric", "numeric", ("donchian_turtle", "multi_tf_turtle"), f"4H Donchian {window} 根突破幅度", "gt", (0.0, 0.002, 0.005, 0.01)))
    for k in [1.0, 1.2, 1.5, 2.0]:
        key = str(k).replace(".", "p")
        catalog.append(RulePrimitiveSpec(f"atr_channel_breakout_k{key}", "entry_signal", "bool", ("atr_channel",), f"4H ATR 通道突破 k={k}"))
    for window in [24, 48, 60, 90, 120]:
        catalog.append(RulePrimitiveSpec(f"exit_donchian_low_w{window}", "exit_signal", "bool", ("donchian_turtle", "multi_tf_turtle"), f"跌破 Donchian {window} 根低点退出"))
    for mult in [1.5, 2.0, 2.5, 3.0, 4.0]:
        key = str(mult).replace(".", "p")
        catalog.append(RulePrimitiveSpec(f"exit_atr_trail_{key}x", "exit_signal", "bool", ("atr_channel", "multi_tf_turtle", "trend_pullback_reentry"), f"{mult} 倍 ATR 移动退出"))
    catalog.extend(
        [
            RulePrimitiveSpec("exit_failed_breakout_12", "exit_signal", "bool", ("donchian_turtle", "multi_tf_squeeze_breakout"), "突破后 12 根 4H 内失败退出"),
            RulePrimitiveSpec("exit_failed_breakout_24", "exit_signal", "bool", ("donchian_turtle", "multi_tf_squeeze_breakout"), "突破后 24 根 4H 内失败退出"),
        ]
    )
    return catalog


def validate_genome(genome: RuleGenome, primitive_catalog: Sequence[RulePrimitiveSpec] | None = None) -> None:
    known = {item.primitive_id: item for item in (primitive_catalog or rule_primitive_catalog())}
    if genome.genome_type == "regime_router":
        if not genome.regime_rules:
            raise ValueError("regime_genome_requires_regime_rules")
        for regime, child in genome.regime_rules:
            if regime not in {"bull_trend", "sideways", "high_volatility", "bear_risk"}:
                raise ValueError(f"regime_not_allowed:{regime}")
            validate_genome(child, primitive_catalog=primitive_catalog)
        return
    if genome.genome_type != "vote_rule":
        raise ValueError(f"genome_type_not_allowed:{genome.genome_type}")
    if not genome.entry_conditions:
        raise ValueError("genome_requires_entry_conditions")
    if not genome.exit_conditions:
        raise ValueError("genome_requires_exit_conditions")
    if genome.vote_threshold < 1 or genome.vote_threshold > len(genome.entry_conditions):
        raise ValueError("entry_vote_threshold_invalid")
    for condition in (*genome.entry_conditions, *genome.exit_conditions):
        if condition.primitive_id not in known:
            raise ValueError(f"primitive_not_allowed:{condition.primitive_id}")
        if condition.comparator not in {"gt", "lt"}:
            raise ValueError(f"comparator_not_allowed:{condition.comparator}")


def evaluate_genome(
    genome: RuleGenome,
    *,
    primitive_frame: pd.DataFrame,
    bars_4h: pd.DataFrame,
    initial_capital: float,
    cost_bps: float,
    index: pd.DatetimeIndex | None = None,
) -> EvaluatedGenome:
    validate_genome(genome)
    close = bars_4h["close"].astype(float)
    frame = primitive_frame.reindex(close.index).fillna(0.0)
    raw = _raw_signal_from_genome(genome, frame=frame, bars_4h=bars_4h).reindex(close.index).fillna(0.0)
    exposure = raw.shift(1).fillna(0.0)
    if genome.sizing_mode == "vol_scaled":
        exposure = _apply_volatility_sizing(exposure, close)
    bar_returns = close.pct_change().fillna(0.0)
    turnover = exposure.diff().abs().fillna(exposure.abs())
    cost = turnover * (float(cost_bps) / 10_000.0)
    returns = (exposure * bar_returns - cost).fillna(0.0)
    if index is not None:
        returns = returns.loc[index]
        exposure = exposure.loc[index]
        turnover = turnover.loc[index]
        cost = cost.loc[index]
    equity = float(initial_capital) * (1.0 + returns).cumprod()
    metrics = _performance_metrics(strategy_returns=returns, equity=equity, exposure=exposure, turnover=turnover, cost=cost, initial_capital=initial_capital)
    return EvaluatedGenome(genome, raw, exposure, returns, turnover, cost, equity, metrics)


def _raw_signal_from_genome(genome: RuleGenome, *, frame: pd.DataFrame, bars_4h: pd.DataFrame) -> pd.Series:
    if genome.genome_type == "regime_router":
        labels = _market_regime_labels(bars_4h)
        raw = pd.Series(0.0, index=frame.index)
        for regime, child in genome.regime_rules:
            child_raw = _raw_signal_from_genome(child, frame=frame, bars_4h=bars_4h)
            raw.loc[labels == regime] = child_raw.loc[labels == regime]
        return raw.fillna(0.0).clip(0.0, 1.0)
    entry_votes = _condition_votes(frame, genome.entry_conditions)
    exit_votes = _condition_votes(frame, genome.exit_conditions)
    entry = entry_votes >= int(genome.vote_threshold)
    exit_signal = exit_votes >= int(genome.exit_vote_threshold)
    return _stateful_long_flat(entry, exit_signal, cooldown_bars=int(genome.cooldown_bars)).reindex(frame.index).fillna(0.0)


def _apply_volatility_sizing(exposure: pd.Series, close: pd.Series) -> pd.Series:
    vol = close.pct_change().rolling(60).std(ddof=0)
    cap = vol.rolling(240, min_periods=60).quantile(0.75).shift(1)
    scaled = exposure.copy()
    scaled.loc[(vol > cap) & cap.notna()] = scaled.loc[(vol > cap) & cap.notna()] * 0.5
    return scaled.fillna(0.0).clip(0.0, 1.0)


def _run_ga(
    *,
    primitive_frame: pd.DataFrame,
    bars_4h: pd.DataFrame,
    rng: random.Random,
    population_size: int,
    generations: int,
    initial_capital: float,
    cost_bps: float,
    train_index: pd.DatetimeIndex,
) -> dict[str, Any]:
    seed_genomes = _handwritten_seed_genomes()
    population = seed_genomes[:population_size]
    while len(population) < population_size:
        population.append(_random_genome(rng))
    pool: list[tuple[float, RuleGenome, dict[str, Any]]] = []
    trial_count = 0
    rejected_count = 0
    for _ in range(generations):
        scored: list[tuple[float, RuleGenome, dict[str, Any]]] = []
        for genome in population:
            trial_count += 1
            evaluation = evaluate_genome(
                genome,
                primitive_frame=primitive_frame,
                bars_4h=bars_4h,
                initial_capital=initial_capital,
                cost_bps=cost_bps,
                index=train_index,
            )
            annual = _annual_summary(evaluation, initial_capital=initial_capital)
            recent = _recent_segment_summary(evaluation, initial_capital=initial_capital)
            cost_stress = _cost_stress_proxy_from_metrics(evaluation.metrics)
            fitness = _fitness(evaluation.metrics, genome=genome, annual=annual, recent=recent, cost_stress=cost_stress)
            if fitness <= 0.0:
                rejected_count += 1
            scored.append((fitness, genome, evaluation.metrics))
        scored = sorted(scored, key=lambda item: (-item[0], item[1].genome_hash))
        pool.extend(scored[: max(8, population_size // 4)])
        elites = [item[1] for item in scored[: max(4, population_size // 8)]]
        next_population = elites[:]
        while len(next_population) < population_size:
            parent_a = _tournament(scored, rng)
            parent_b = _tournament(scored, rng)
            child = _crossover(parent_a, parent_b, rng) if rng.random() < 0.65 else parent_a
            if rng.random() < 0.35:
                child = _mutate(child, rng)
            next_population.append(child)
        population = next_population
    unique: dict[str, tuple[float, RuleGenome, dict[str, Any]]] = {}
    for item in pool:
        unique.setdefault(item[1].genome_hash, item)
    return {
        "trial_count": trial_count,
        "rejected_count": rejected_count,
        "seeded_genome_count": min(len(seed_genomes), population_size),
        "candidate_pool": list(unique.values()),
    }


def _select_candidates(
    candidate_pool: Sequence[tuple[float, RuleGenome, dict[str, Any]]],
    *,
    primitive_frame: pd.DataFrame,
    bars_4h: pd.DataFrame,
    validation_index: pd.DatetimeIndex,
    selected_candidate_count: int,
    initial_capital: float,
    cost_bps: float,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    preselected = sorted(candidate_pool, key=lambda item: (-item[0], item[1].genome_hash))[: max(selected_candidate_count * 8, 48)]
    for train_fitness, genome, train_metrics in preselected:
        validation = evaluate_genome(
            genome,
            primitive_frame=primitive_frame,
            bars_4h=bars_4h,
            initial_capital=initial_capital,
            cost_bps=cost_bps,
            index=validation_index,
        )
        full = evaluate_genome(genome, primitive_frame=primitive_frame, bars_4h=bars_4h, initial_capital=initial_capital, cost_bps=cost_bps)
        walk_forward = _walk_forward_summary(genome, primitive_frame=primitive_frame, bars_4h=bars_4h, initial_capital=initial_capital, cost_bps=cost_bps)
        annual = _annual_summary(full, initial_capital=initial_capital)
        recent = _recent_segment_summary(full, initial_capital=initial_capital)
        cost_stress = _cost_stress_summary(genome, primitive_frame=primitive_frame, bars_4h=bars_4h, initial_capital=initial_capital, base_cost_bps=cost_bps)
        row = {
            "candidate_id": f"btc_ga_rule_{genome.genome_hash}",
            "genome_hash": genome.genome_hash,
            "genome_type": genome.genome_type,
            "cooldown_bars": int(genome.cooldown_bars),
            "sizing_mode": genome.sizing_mode,
            "condition_count": _genome_condition_count(genome),
            "genome": genome.to_dict(),
            "entry_primitive_ids": [item.primitive_id for item in genome.entry_conditions],
            "exit_primitive_ids": [item.primitive_id for item in genome.exit_conditions],
            "train_fitness": _round(train_fitness),
            "train_metrics": train_metrics,
            "validation_metrics": validation.metrics,
            "full_metrics": full.metrics,
            "walk_forward": walk_forward,
            "annual_regime": annual,
            "recent_segment": recent,
            "cost_stress": cost_stress,
            "validation_score": _round(_fitness(validation.metrics, genome=genome, annual=annual, recent=recent, cost_stress=cost_stress)),
            "retention_decision": _ga_retention_decision(validation.metrics, walk_forward, annual, cost_stress),
            "scope": "research_only_rule_genome",
            "paper_candidate_generated": False,
            "paper_queue_write_allowed": False,
            "live_unlock_allowed": False,
        }
        rows.append(row)
    ranked = sorted(rows, key=lambda row: (-float(row["validation_score"]), str(row["candidate_id"])))
    return ranked[:selected_candidate_count]


def _handwritten_baseline_comparison(
    *,
    bars_1h: pd.DataFrame,
    bars_4h: pd.DataFrame,
    bars_1d: pd.DataFrame,
    derivatives_4h: pd.DataFrame,
    validation_index: pd.DatetimeIndex,
    initial_capital: float,
    cost_bps: float,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for spec in simple_trend_rule_specs():
        item = evaluate_simple_rule(spec, bars_4h=bars_4h, bars_1d=bars_1d, derivatives_4h=derivatives_4h, initial_capital=initial_capital, cost_bps=cost_bps)
        rows.append(_baseline_row("simple_trend_rule_lab", spec.family_id, spec.variant_id, spec.candidate_id, item, validation_index=validation_index, initial_capital=initial_capital))
    for spec in multi_timeframe_rule_specs():
        item = evaluate_mtf_rule(spec, bars_1h=bars_1h, bars_4h=bars_4h, bars_1d=bars_1d, derivatives_4h=derivatives_4h, initial_capital=initial_capital, cost_bps=cost_bps)
        rows.append(_baseline_row("multi_timeframe_rule_lab", spec.family_id, spec.variant_id, spec.candidate_id, item, validation_index=validation_index, initial_capital=initial_capital))
    ranked = sorted(rows, key=lambda row: (-float(row["score"]), str(row["candidate_id"])))
    return {
        "baseline_count": len(rows),
        "top_handwritten_baselines": ranked[:12],
        "comparison_policy": "GA candidates and handwritten baselines are compared on the same validation window and cost model before any future review",
        "validation_start": _ts(validation_index.min()) if len(validation_index) else None,
        "validation_end": _ts(validation_index.max()) if len(validation_index) else None,
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
    }


def _baseline_row(source_lab: str, family_id: str, variant_id: str, candidate_id: str, item: Any, *, validation_index: pd.DatetimeIndex, initial_capital: float) -> dict[str, Any]:
    metrics = item.metrics
    validation_returns = item.returns.loc[validation_index]
    validation_equity = float(initial_capital) * (1.0 + validation_returns).cumprod()
    validation_metrics = _performance_metrics(
        strategy_returns=validation_returns,
        equity=validation_equity,
        exposure=item.exposure.loc[validation_index],
        turnover=item.turnover.loc[validation_index],
        cost=item.cost.loc[validation_index],
        initial_capital=initial_capital,
    )
    score = float(metrics.get("total_return_pct", 0.0)) + 10.0 * float(metrics.get("profit_factor", 0.0)) - float(metrics.get("max_drawdown_abs_pct", 0.0))
    return {
        "source_lab": source_lab,
        "family_id": family_id,
        "variant_id": variant_id,
        "candidate_id": candidate_id,
        "total_return_pct": metrics.get("total_return_pct", 0.0),
        "max_drawdown_abs_pct": metrics.get("max_drawdown_abs_pct", 0.0),
        "profit_factor": metrics.get("profit_factor", 0.0),
        "average_exposure": metrics.get("average_exposure", 0.0),
        "validation_metrics": validation_metrics,
        "same_validation_window": True,
        "score": _round(score),
    }


def _position_sizing_diagnostics(
    candidates: Sequence[Mapping[str, Any]],
    *,
    primitive_frame: pd.DataFrame,
    bars_4h: pd.DataFrame,
    initial_capital: float,
    cost_bps: float,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for row in list(candidates)[:5]:
        genome = _genome_from_dict(_mapping(row.get("genome")))
        diagnostic = RuleGenome(
            genome.entry_conditions,
            genome.vote_threshold,
            genome.exit_conditions,
            genome.exit_vote_threshold,
            genome_type=genome.genome_type,
            regime_rules=genome.regime_rules,
            cooldown_bars=genome.cooldown_bars,
            sizing_mode="vol_scaled",
        )
        evaluated = evaluate_genome(diagnostic, primitive_frame=primitive_frame, bars_4h=bars_4h, initial_capital=initial_capital, cost_bps=cost_bps)
        rows.append(
            {
                "source_candidate_id": row.get("candidate_id"),
                "diagnostic_candidate_id": f"{row.get('candidate_id')}_vol_scaled",
                "sizing_mode": "vol_scaled",
                "metrics": evaluated.metrics,
                "included_in_main_shortlist": False,
                "paper_queue_write_allowed": False,
                "live_unlock_allowed": False,
            }
        )
    return {
        "scope": "diagnostic_only_not_used_for_main_shortlist",
        "row_count": len(rows),
        "rows": rows,
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
    }


def _genome_from_dict(payload: Mapping[str, Any]) -> RuleGenome:
    def condition(item: Mapping[str, Any]) -> RuleCondition:
        return RuleCondition(str(item["primitive_id"]), str(item["comparator"]), float(item["threshold"]))

    regime_rules = tuple(
        (str(item["regime"]), _genome_from_dict(_mapping(item.get("genome"))))
        for item in payload.get("regime_rules", [])
        if isinstance(item, Mapping)
    )
    return RuleGenome(
        tuple(condition(_mapping(item)) for item in payload.get("entry_conditions", [])),
        int(payload.get("vote_threshold", 0)),
        tuple(condition(_mapping(item)) for item in payload.get("exit_conditions", [])),
        int(payload.get("exit_vote_threshold", 0)),
        genome_type=str(payload.get("genome_type") or "vote_rule"),
        regime_rules=regime_rules,
        cooldown_bars=int(payload.get("cooldown_bars", 0)),
        sizing_mode=str(payload.get("sizing_mode") or "binary"),
    )


def _render_ga_rule_component_mining_markdown_legacy(report: Mapping[str, Any]) -> str:
    gate = _mapping(report.get("gate"))
    config = _mapping(report.get("ga_config"))
    input_info = _mapping(report.get("input"))
    lines = [
        "# BTC GA 规则组件挖掘实验室",
        "",
        f"- 状态：`{report.get('status')}`",
        f"- 决策：`{report.get('decision')}`",
        f"- 写 paper 队列：`{gate.get('paper_queue_write_allowed')}`",
        f"- 解锁 live：`{gate.get('live_unlock_allowed')}`",
        f"- 1H 样本行数：`{input_info.get('market_1h_rows')}`",
        f"- 4H 决策行数：`{input_info.get('bar_4h_rows')}`",
        f"- primitive 数量：`{len(report.get('primitive_catalog', []))}`",
        f"- GA 试验次数：`{config.get('trial_count')}`",
        f"- 候选 genome 数量：`{config.get('selected_candidate_count')}`",
        "",
        "## GA 候选规则",
        "",
    ]
    candidates = list(report.get("candidate_rule_genomes", []))
    if not candidates:
        lines.append("- 当前没有 GA 规则候选。")
    for idx, row in enumerate(candidates[:12], 1):
        validation = _mapping(row.get("validation_metrics"))
        lines.append(
            f"- {idx}. `{row['candidate_id']}`：验证收益 `{validation.get('total_return_pct')}%`，"
            f"回撤 `{validation.get('max_drawdown_pct')}%`，PF `{validation.get('profit_factor')}`，"
            f"结论 `{row.get('retention_decision')}`。"
        )
        lines.append(f"  - 入场 primitive：`{', '.join(row.get('entry_primitive_ids', []))}`")
        lines.append(f"  - 退出 primitive：`{', '.join(row.get('exit_primitive_ids', []))}`")
    lines.extend(["", "## 手写规则基线 Top 8", ""])
    handwritten = _mapping(report.get("handwritten_rule_baseline_comparison"))
    for idx, row in enumerate(list(handwritten.get("top_handwritten_baselines", []))[:8], 1):
        lines.append(
            f"- {idx}. `{row['candidate_id']}`：{row['source_lab']} / {row['family_id']} / {row['variant_id']}，"
            f"收益 `{row['total_return_pct']}%`，回撤 `{row['max_drawdown_abs_pct']}%`，PF `{row['profit_factor']}`。"
        )
    lines.extend(
        [
            "",
            "## 复核重点",
            "",
            "- GA 只组合已登记 primitive 和阈值，不直接发明完整策略骨架。",
            "- 输出只用于 research-only 复核，不写 paper 队列，不解锁 live。",
            "- 任何候选都必须继续和手写规则基线、行情分段、成本压力、回撤归因比较。",
        ]
    )
    return "\n".join(lines) + "\n"


def primitive_to_dict(item: RulePrimitiveSpec) -> dict[str, Any]:
    return {
        "primitive_id": item.primitive_id,
        "kind": item.kind,
        "value_type": item.value_type,
        "source_rules": list(item.source_rules),
        "description_zh": item.description_zh,
        "comparator": item.comparator,
        "threshold_grid": list(item.threshold_grid),
    }


def _primitive_source_coverage(catalog: Sequence[RulePrimitiveSpec]) -> dict[str, Any]:
    covered = sorted(set().union(*(item.source_rules for item in catalog)))
    return {"required_source_family_count": len(REQUIRED_RULE_SOURCE_FAMILIES), "covered_source_families": covered, "missing_source_families": sorted(REQUIRED_RULE_SOURCE_FAMILIES - set(covered))}


def _condition_votes(frame: pd.DataFrame, conditions: Sequence[RuleCondition]) -> pd.Series:
    votes = pd.Series(0, index=frame.index, dtype=int)
    for condition in conditions:
        values = pd.to_numeric(frame[condition.primitive_id], errors="coerce").fillna(0.0)
        if condition.comparator == "gt":
            votes += (values > float(condition.threshold)).astype(int)
        elif condition.comparator == "lt":
            votes += (values < float(condition.threshold)).astype(int)
        else:
            raise ValueError(f"comparator_not_allowed:{condition.comparator}")
    return votes


def _random_genome(rng: random.Random) -> RuleGenome:
    if rng.random() < 0.15:
        return _random_regime_genome(rng)
    catalog = rule_primitive_catalog()
    entry_pool = [item for item in catalog if item.kind in {"entry_filter", "entry_signal", "entry_numeric", "risk_filter"}]
    exit_pool = [item for item in catalog if item.kind == "exit_signal"]
    entry_count = rng.randint(3, MAX_ENTRY_CONDITIONS)
    exit_count = rng.randint(1, 3)
    entries = tuple(_condition_from_primitive(item, rng) for item in rng.sample(entry_pool, entry_count))
    exits = tuple(_condition_from_primitive(item, rng) for item in rng.sample(exit_pool, exit_count))
    vote_threshold = rng.randint(max(1, math.ceil(entry_count * 0.55)), entry_count)
    return RuleGenome(entries, vote_threshold, exits, 1, cooldown_bars=rng.choice(COOLDOWN_BAR_GRID))


def _random_regime_genome(rng: random.Random) -> RuleGenome:
    seeds = [genome for genome in _handwritten_seed_genomes() if genome.genome_type == "vote_rule"]
    regimes = []
    for regime in ["bull_trend", "sideways", "high_volatility", "bear_risk"]:
        child = rng.choice(seeds)
        if regime in {"high_volatility", "bear_risk"} and rng.random() < 0.55:
            child = _cash_like_genome()
        regimes.append((regime, child))
    return RuleGenome((), 0, (), 0, genome_type="regime_router", regime_rules=tuple(regimes), cooldown_bars=0)


def _handwritten_seed_genomes() -> list[RuleGenome]:
    def c(name: str, comparator: str = "gt", threshold: float = 0.5) -> RuleCondition:
        return RuleCondition(name, comparator, threshold)

    seeds = [
        RuleGenome((c("ema_ribbon_4h_long"), c("vol_not_extreme_60")), 2, (c("exit_close_below_ema100"),), 1, cooldown_bars=6),
        RuleGenome((c("daily_ema50_gt_200"), c("donchian_breakout_w120")), 2, (c("exit_donchian_low_w60"), c("exit_failed_breakout_12")), 1, cooldown_bars=6),
        RuleGenome((c("daily_ema50_gt_200"), c("donchian_breakout_w180"), c("vol_not_extreme_60")), 2, (c("exit_atr_trail_3p0x"), c("exit_failed_breakout_24")), 1, cooldown_bars=12),
        RuleGenome((c("daily_not_bear_50_200"), c("squeeze_recent"), c("squeeze_breakout")), 2, (c("exit_close_below_ema50"), c("exit_failed_breakout_12")), 1, cooldown_bars=6),
        RuleGenome((c("daily_ema50_gt_200"), c("pullback_ema50_reclaim"), c("one_hour_momentum_positive")), 2, (c("exit_close_below_ema100"), c("exit_atr_trail_2p5x")), 1, cooldown_bars=6),
        RuleGenome((c("ema_ribbon_4h_long"), c("funding_not_crowded"), c("oi_not_extreme")), 2, (c("exit_close_below_ema100"), c("exit_daily_bear")), 1, cooldown_bars=6),
        RuleGenome((c("vote_count_core", "gt", 2.5),), 1, (c("exit_close_below_ema50"),), 1, cooldown_bars=6),
        RuleGenome((c("daily_ema34_gt_144"), c("ema_ribbon_long_13_34_89"), c("realized_vol_24h_z", "lt", 1.0)), 2, (c("exit_close_below_ema50"),), 1, cooldown_bars=6),
        RuleGenome((c("daily_ema55_gt_233"), c("donchian_breakout_w240")), 2, (c("exit_donchian_low_w90"), c("exit_failed_breakout_24")), 1, cooldown_bars=12),
        RuleGenome((c("atr_channel_breakout_k1p2"), c("funding_not_crowded"), c("vol_not_extreme_60")), 2, (c("exit_atr_trail_2p0x"),), 1, cooldown_bars=6),
    ]
    seeds.append(
        RuleGenome(
            (),
            0,
            (),
            0,
            genome_type="regime_router",
            regime_rules=(
                ("bull_trend", seeds[1]),
                ("sideways", seeds[4]),
                ("high_volatility", _cash_like_genome()),
                ("bear_risk", _cash_like_genome()),
            ),
        )
    )
    return seeds


def _cash_like_genome() -> RuleGenome:
    return RuleGenome((RuleCondition("daily_ema50_gt_200", "gt", 2.0),), 1, (RuleCondition("exit_daily_bear", "gt", 0.5),), 1)


def _condition_from_primitive(item: RulePrimitiveSpec, rng: random.Random) -> RuleCondition:
    threshold = rng.choice(item.threshold_grid)
    return RuleCondition(item.primitive_id, item.comparator, float(threshold))


def _tournament(scored: Sequence[tuple[float, RuleGenome, dict[str, Any]]], rng: random.Random) -> RuleGenome:
    picks = rng.sample(list(scored), min(4, len(scored)))
    return sorted(picks, key=lambda item: -item[0])[0][1]


def _crossover(parent_a: RuleGenome, parent_b: RuleGenome, rng: random.Random) -> RuleGenome:
    if parent_a.genome_type == "regime_router" or parent_b.genome_type == "regime_router":
        return rng.choice([parent_a, parent_b, _random_regime_genome(rng)])
    entries = tuple(_dedupe_conditions((*parent_a.entry_conditions[: max(1, len(parent_a.entry_conditions) // 2)], *parent_b.entry_conditions[max(1, len(parent_b.entry_conditions) // 2) :])))[:MAX_ENTRY_CONDITIONS]
    exits = tuple(_dedupe_conditions((*parent_a.exit_conditions[:1], *parent_b.exit_conditions[1:])))[:3] or parent_a.exit_conditions
    vote_threshold = max(1, min(len(entries), rng.choice([parent_a.vote_threshold, parent_b.vote_threshold])))
    return RuleGenome(entries, vote_threshold, exits, 1, cooldown_bars=rng.choice([parent_a.cooldown_bars, parent_b.cooldown_bars]))


def _mutate(genome: RuleGenome, rng: random.Random) -> RuleGenome:
    if genome.genome_type == "regime_router":
        regimes = list(genome.regime_rules)
        vote_rule_seeds = [item for item in _handwritten_seed_genomes() if item.genome_type == "vote_rule"]
        if regimes:
            idx = rng.randrange(len(regimes))
            regime, child = regimes[idx]
            regimes[idx] = (regime, _mutate(child, rng) if rng.random() < 0.6 else rng.choice(vote_rule_seeds))
        return RuleGenome((), 0, (), 0, genome_type="regime_router", regime_rules=tuple(regimes), cooldown_bars=0)
    catalog = {item.primitive_id: item for item in rule_primitive_catalog()}
    entry_pool = [item for item in catalog.values() if item.kind in {"entry_filter", "entry_signal", "entry_numeric", "risk_filter"}]
    exit_pool = [item for item in catalog.values() if item.kind == "exit_signal"]
    entries = list(genome.entry_conditions)
    exits = list(genome.exit_conditions)
    roll = rng.random()
    if roll < 0.35 and entries:
        idx = rng.randrange(len(entries))
        entries[idx] = _condition_from_primitive(rng.choice(entry_pool), rng)
    elif roll < 0.55 and len(entries) < MAX_ENTRY_CONDITIONS:
        entries.append(_condition_from_primitive(rng.choice(entry_pool), rng))
    elif roll < 0.75 and len(entries) > 3:
        entries.pop(rng.randrange(len(entries)))
    elif roll < 0.90 and exits:
        exits[rng.randrange(len(exits))] = _condition_from_primitive(rng.choice(exit_pool), rng)
    else:
        idx = rng.randrange(len(entries))
        primitive = catalog[entries[idx].primitive_id]
        entries[idx] = _condition_from_primitive(primitive, rng)
    entries = _dedupe_conditions(entries)[:MAX_ENTRY_CONDITIONS]
    exits = _dedupe_conditions(exits)[:3] or [_condition_from_primitive(rng.choice(exit_pool), rng)]
    vote_threshold = min(len(entries), max(1, genome.vote_threshold + rng.choice([-1, 0, 1])))
    cooldown_bars = rng.choice(COOLDOWN_BAR_GRID) if rng.random() < 0.25 else genome.cooldown_bars
    return RuleGenome(tuple(entries), vote_threshold, tuple(exits), 1, cooldown_bars=cooldown_bars)


def _dedupe_conditions(conditions: Sequence[RuleCondition]) -> list[RuleCondition]:
    output: list[RuleCondition] = []
    seen: set[str] = set()
    for condition in conditions:
        if condition.primitive_id in seen:
            continue
        output.append(condition)
        seen.add(condition.primitive_id)
    return output


def _fitness(
    metrics: Mapping[str, Any],
    *,
    genome: RuleGenome,
    annual: Mapping[str, Any] | None = None,
    recent: Mapping[str, Any] | None = None,
    cost_stress: Mapping[str, Any] | None = None,
) -> float:
    annual = annual or {}
    recent = recent or {}
    cost_stress = cost_stress or {}
    score = float(metrics.get("total_return_pct", 0.0))
    score += 12.0 * float(metrics.get("profit_factor", 0.0))
    score -= 1.2 * float(metrics.get("max_drawdown_abs_pct", 0.0))
    score -= 0.03 * float(metrics.get("turnover", 0.0))
    condition_count = _genome_condition_count(genome)
    score -= 1.5 * max(0, condition_count - 4)
    score += 8.0 * float(annual.get("pass_rate", 0.0))
    score += 8.0 * float(cost_stress.get("survival_rate", 0.0))
    score += 6.0 if bool(recent.get("passed", False)) else -6.0
    score -= max(0.0, float(annual.get("best_positive_year_share", 0.0)) - 0.70) * 30.0
    if float(metrics.get("average_exposure", 0.0)) < 0.03:
        score -= 20.0
    if genome.genome_type == "regime_router":
        score += 2.0
    return score


def _genome_condition_count(genome: RuleGenome) -> int:
    if genome.genome_type == "regime_router":
        return sum(_genome_condition_count(child) for _, child in genome.regime_rules)
    return len(genome.entry_conditions) + len(genome.exit_conditions)


def _ga_retention_decision(metrics: Mapping[str, Any], walk_forward: Mapping[str, Any], annual: Mapping[str, Any], cost_stress: Mapping[str, Any]) -> str:
    if float(metrics.get("total_return_pct", 0.0)) <= 0.0:
        return "reject_non_positive_validation_return"
    if float(metrics.get("profit_factor", 0.0)) < 1.05:
        return "defer_validation_profit_factor_too_thin"
    if float(metrics.get("max_drawdown_abs_pct", 0.0)) > 30.0:
        return "defer_validation_drawdown_too_high"
    if float(walk_forward.get("pass_rate", 0.0)) < 0.5:
        return "defer_walk_forward_unstable"
    if float(annual.get("best_positive_year_share", 0.0)) > 0.70:
        return "defer_year_concentration_review"
    if float(cost_stress.get("survival_rate", 0.0)) < 0.67:
        return "defer_cost_stress_fragile"
    return "retain_extended_research_only"


def _walk_forward_summary(
    genome: RuleGenome,
    *,
    primitive_frame: pd.DataFrame,
    bars_4h: pd.DataFrame,
    initial_capital: float,
    cost_bps: float,
    fold_count: int = 4,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    index = bars_4h.index
    fold_size = max(1, len(index) // fold_count)
    for fold in range(fold_count):
        start = fold * fold_size
        end = len(index) if fold == fold_count - 1 else (fold + 1) * fold_size
        idx = index[start:end]
        if len(idx) < 20:
            continue
        metrics = evaluate_genome(genome, primitive_frame=primitive_frame, bars_4h=bars_4h, initial_capital=initial_capital, cost_bps=cost_bps, index=idx).metrics
        passed = float(metrics["total_return_pct"]) > 0.0 and float(metrics["profit_factor"]) >= 1.0 and float(metrics["max_drawdown_abs_pct"]) <= 35.0
        rows.append({"fold": fold + 1, "start": _ts(idx.min()), "end": _ts(idx.max()), "row_count": len(idx), "passed": passed, "metrics": metrics})
    pass_rate = sum(1 for row in rows if row["passed"]) / len(rows) if rows else 0.0
    return {"fold_count": len(rows), "pass_rate": _round(pass_rate), "minimum_pass_rate": 0.5, "passed": pass_rate >= 0.5 if rows else False, "folds": rows}


def _annual_summary(item: EvaluatedGenome, *, initial_capital: float) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for year, positions in item.returns.groupby(item.returns.index.year).groups.items():
        idx = pd.DatetimeIndex(positions)
        returns = item.returns.loc[idx]
        equity = float(initial_capital) * (1.0 + returns).cumprod()
        metrics = _performance_metrics(strategy_returns=returns, equity=equity, exposure=item.exposure.loc[idx], turnover=item.turnover.loc[idx], cost=item.cost.loc[idx], initial_capital=initial_capital)
        rows.append({"segment": str(year), "row_count": len(idx), "passed": float(metrics["total_return_pct"]) > 0.0 and float(metrics["profit_factor"]) >= 1.0, "metrics": metrics})
    positives = [max(0.0, float(row["metrics"]["total_return_pct"])) for row in rows]
    total_positive = sum(positives)
    best_share = max(positives) / total_positive if total_positive > 0.0 else 0.0
    return {"segment_count": len(rows), "pass_rate": _round(sum(1 for row in rows if row["passed"]) / len(rows) if rows else 0.0), "best_positive_year_share": _round(best_share), "segments": rows}


def _recent_segment_summary(item: EvaluatedGenome, *, initial_capital: float) -> dict[str, Any]:
    if item.returns.empty:
        return {"row_count": 0, "passed": False, "metrics": _performance_metrics(strategy_returns=item.returns, equity=item.equity, exposure=item.exposure, turnover=item.turnover, cost=item.cost, initial_capital=initial_capital)}
    length = max(20, len(item.returns) // 4)
    idx = item.returns.index[-min(length, len(item.returns)) :]
    returns = item.returns.loc[idx]
    equity = float(initial_capital) * (1.0 + returns).cumprod()
    metrics = _performance_metrics(
        strategy_returns=returns,
        equity=equity,
        exposure=item.exposure.loc[idx],
        turnover=item.turnover.loc[idx],
        cost=item.cost.loc[idx],
        initial_capital=initial_capital,
    )
    passed = float(metrics["total_return_pct"]) > 0.0 and float(metrics["profit_factor"]) >= 1.0 and float(metrics["max_drawdown_abs_pct"]) <= 35.0
    return {"row_count": len(idx), "start": _ts(idx.min()), "end": _ts(idx.max()), "passed": passed, "metrics": metrics}


def _cost_stress_proxy_from_metrics(metrics: Mapping[str, Any]) -> dict[str, Any]:
    base_return = float(metrics.get("total_return_pct", 0.0))
    base_fee = max(0.0, float(metrics.get("fee_return_pct", 0.0)))
    profit_factor = float(metrics.get("profit_factor", 0.0))
    scenarios = []
    for multiplier in [1.0, 2.0, 5.0]:
        adjusted_return = base_return - base_fee * (multiplier - 1.0)
        survives = adjusted_return > 0.0 and profit_factor >= 1.0
        scenarios.append({"cost_multiplier": _round(multiplier), "estimated_total_return_pct": _round(adjusted_return), "survives": survives})
    survival_count = sum(1 for row in scenarios if row["survives"])
    return {"scenario_count": len(scenarios), "survival_count": survival_count, "survival_rate": _round(survival_count / len(scenarios)), "proxy": True, "scenarios": scenarios}


def _cost_stress_summary(
    genome: RuleGenome,
    *,
    primitive_frame: pd.DataFrame,
    bars_4h: pd.DataFrame,
    initial_capital: float,
    base_cost_bps: float,
    index: pd.DatetimeIndex | None = None,
) -> dict[str, Any]:
    scenarios: list[dict[str, Any]] = []
    for cost_bps in [base_cost_bps, base_cost_bps * 2.0, base_cost_bps * 5.0]:
        metrics = evaluate_genome(genome, primitive_frame=primitive_frame, bars_4h=bars_4h, initial_capital=initial_capital, cost_bps=cost_bps, index=index).metrics
        survives = float(metrics["total_return_pct"]) > 0.0 and float(metrics["profit_factor"]) >= 1.0
        scenarios.append({"cost_bps": _round(cost_bps), "survives": survives, "metrics": metrics})
    survival_count = sum(1 for row in scenarios if row["survives"])
    return {"scenario_count": len(scenarios), "survival_count": survival_count, "survival_rate": _round(survival_count / len(scenarios)), "scenarios": scenarios}


def _performance_metrics(
    *,
    strategy_returns: pd.Series,
    equity: pd.Series,
    exposure: pd.Series,
    turnover: pd.Series,
    cost: pd.Series,
    initial_capital: float,
) -> dict[str, Any]:
    if strategy_returns.empty:
        return {"total_return_pct": 0.0, "profit_factor": 0.0, "max_drawdown_pct": 0.0, "max_drawdown_abs_pct": 0.0, "average_exposure": 0.0, "turnover": 0.0, "fee_return_pct": 0.0}
    total_return = float(equity.iloc[-1] / float(initial_capital) - 1.0)
    drawdown = equity / equity.cummax() - 1.0
    positive = strategy_returns[strategy_returns > 0.0].sum()
    negative = strategy_returns[strategy_returns < 0.0].sum()
    profit_factor = float(positive / abs(negative)) if negative < 0.0 else (999.0 if positive > 0.0 else 0.0)
    return {
        "total_return_pct": _round(total_return * 100.0),
        "profit_factor": _round(profit_factor),
        "max_drawdown_pct": _round(float(drawdown.min()) * 100.0),
        "max_drawdown_abs_pct": _round(abs(float(drawdown.min())) * 100.0),
        "average_exposure": _round(float(exposure.abs().mean())),
        "turnover": _round(float(turnover.sum())),
        "fee_return_pct": _round(float(cost.sum()) * 100.0),
        "final_equity": _round(float(equity.iloc[-1])),
    }


def _supertrend_signal(bars: pd.DataFrame, *, window: int, multiplier: float) -> pd.Series:
    close = bars["close"].astype(float)
    high = bars["high"].astype(float)
    low = bars["low"].astype(float)
    atr = _atr(bars, window)
    upper = (high + low) / 2.0 + multiplier * atr
    lower = (high + low) / 2.0 - multiplier * atr
    trend: list[float] = []
    final_upper: list[float] = []
    final_lower: list[float] = []
    for i in range(len(close)):
        cu = float(upper.iloc[i])
        cl = float(lower.iloc[i])
        if not math.isfinite(cu) or not math.isfinite(cl):
            final_upper.append(math.nan)
            final_lower.append(math.nan)
            trend.append(0.0)
            continue
        if not final_upper or not math.isfinite(final_upper[-1]) or not math.isfinite(final_lower[-1]):
            final_upper.append(cu)
            final_lower.append(cl)
            trend.append(1.0 if float(close.iloc[i]) > cl else 0.0)
            continue
        pu = final_upper[-1]
        pl = final_lower[-1]
        prev_close = float(close.iloc[i - 1])
        fu = cu if cu < pu or prev_close > pu else pu
        fl = cl if cl > pl or prev_close < pl else pl
        final_upper.append(fu)
        final_lower.append(fl)
        previous = trend[-1]
        current_close = float(close.iloc[i])
        if previous <= 0.0 and current_close > fu:
            trend.append(1.0)
        elif previous >= 1.0 and current_close < fl:
            trend.append(0.0)
        else:
            trend.append(previous)
    return pd.Series(trend, index=close.index)


def _stateful_long_flat(entry: pd.Series, exit_signal: pd.Series, *, cooldown_bars: int = 0) -> pd.Series:
    out: list[float] = []
    in_position = False
    cooldown_remaining = 0
    for ent, ex in zip(entry.fillna(False).astype(bool), exit_signal.fillna(False).astype(bool)):
        if in_position and ex:
            in_position = False
            cooldown_remaining = max(0, int(cooldown_bars))
        if cooldown_remaining > 0:
            cooldown_remaining -= 1
        if not in_position and cooldown_remaining <= 0 and ent:
            in_position = True
        out.append(1.0 if in_position else 0.0)
    return pd.Series(out, index=entry.index)


def _atr(bars: pd.DataFrame, window: int) -> pd.Series:
    high = bars["high"].astype(float)
    low = bars["low"].astype(float)
    close = bars["close"].astype(float)
    previous_close = close.shift(1)
    tr = pd.concat([(high - low).abs(), (high - previous_close).abs(), (low - previous_close).abs()], axis=1).max(axis=1)
    return tr.rolling(window).mean()


def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.astype(float).ewm(span=span, adjust=False).mean()


def _daily_ema(bars_1d: pd.DataFrame, index: pd.DatetimeIndex, span: int) -> pd.Series:
    return _ema(bars_1d["close"].astype(float), span).reindex(index, method="ffill").fillna(0.0)


def _to_4h(series: pd.Series, index: pd.DatetimeIndex) -> pd.Series:
    return series.sort_index().reindex(index, method="ffill").fillna(0.0)


def _high_vol_ok(close: pd.Series, *, window: int) -> pd.Series:
    vol = close.pct_change().rolling(window).std(ddof=0)
    cap = vol.rolling(window * 4, min_periods=window).quantile(0.85).shift(1)
    return ((vol <= cap) | cap.isna()).fillna(True).astype(bool)


def _market_regime_labels(bars_4h: pd.DataFrame) -> pd.Series:
    close = bars_4h["close"].astype(float)
    fast = _ema(close, 50)
    slow = _ema(close, 200)
    vol = close.pct_change().rolling(60).std(ddof=0)
    vol_cap = vol.rolling(240, min_periods=60).quantile(0.85).shift(1)
    labels = pd.Series("sideways", index=close.index, dtype=object)
    labels.loc[(fast > slow) & (close > slow)] = "bull_trend"
    labels.loc[(fast < slow) & (close < slow)] = "bear_risk"
    labels.loc[(vol > vol_cap) & vol_cap.notna()] = "high_volatility"
    return labels


def _cap_ok(series: pd.Series, *, window: int, quantile: float) -> pd.Series:
    cap = series.rolling(window, min_periods=24).quantile(quantile).shift(1)
    return ((series <= cap) | cap.isna() | series.isna()).fillna(True).astype(bool)


def _numeric_col(frame: pd.DataFrame, column: str, index: pd.DatetimeIndex) -> pd.Series:
    if column not in frame:
        return pd.Series(math.nan, index=index)
    return pd.to_numeric(frame[column], errors="coerce").reindex(index)


def _rolling_z(values: pd.Series, *, window: int) -> pd.Series:
    mean = values.rolling(window).mean()
    std = values.rolling(window).std(ddof=0)
    return (values - mean) / std.replace(0.0, math.nan)


def _warnings(candidates: Sequence[Mapping[str, Any]]) -> list[str]:
    warnings = ["btc_ga_rule_component_mining_research_only_no_paper_no_live"]
    if not candidates:
        warnings.append("btc_ga_rule_component_mining_no_candidates_selected")
    if any(row.get("retention_decision") != "retain_extended_research_only" for row in candidates):
        warnings.append("btc_ga_rule_component_mining_candidates_require_manual_review")
    return warnings


def render_ga_rule_component_mining_markdown(report: Mapping[str, Any]) -> str:
    gate = _mapping(report.get("gate"))
    config = _mapping(report.get("ga_config"))
    input_info = _mapping(report.get("input"))
    lines = [
        "# BTC GA 规则组件挖掘实验室",
        "",
        f"- 状态：`{report.get('status')}`",
        f"- 决策：`{report.get('decision')}`",
        f"- 写入 paper 队列：`{gate.get('paper_queue_write_allowed')}`",
        f"- 解锁 live：`{gate.get('live_unlock_allowed')}`",
        f"- 运行档位：`{config.get('run_profile')}`",
        f"- 种群/代数：`{config.get('population_size')}` / `{config.get('generations')}`",
        f"- 试验次数：`{config.get('trial_count')}`",
        f"- 拒绝次数：`{config.get('rejected_count')}`",
        f"- 手写规则种子数量：`{config.get('seeded_genome_count')}`",
        f"- 1H 样本行数：`{input_info.get('market_1h_rows')}`",
        f"- 4H 决策行数：`{input_info.get('bar_4h_rows')}`",
        f"- primitive 数量：`{len(report.get('primitive_catalog', []))}`",
        f"- 候选 genome 数量：`{config.get('selected_candidate_count')}`",
        "",
        "## GA 候选规则",
        "",
    ]
    candidates = list(report.get("candidate_rule_genomes", []))
    if not candidates:
        lines.append("- 当前没有 GA 规则候选。")
    for idx, row in enumerate(candidates[:12], 1):
        validation = _mapping(row.get("validation_metrics"))
        lines.append(
            f"- {idx}. `{row['candidate_id']}`：验证收益 `{validation.get('total_return_pct')}%`，"
            f"回撤 `{validation.get('max_drawdown_abs_pct')}%`，PF `{validation.get('profit_factor')}`，"
            f"类型 `{row.get('genome_type')}`，条件数 `{row.get('condition_count')}`，"
            f"冷却 `{row.get('cooldown_bars')}` 根 4H，结论 `{row.get('retention_decision')}`。"
        )
        lines.append(f"  - 入场 primitive：`{', '.join(row.get('entry_primitive_ids', []))}`")
        lines.append(f"  - 退出 primitive：`{', '.join(row.get('exit_primitive_ids', []))}`")
    lines.extend(["", "## 手写规则基线 Top 8", ""])
    handwritten = _mapping(report.get("handwritten_rule_baseline_comparison"))
    for idx, row in enumerate(list(handwritten.get("top_handwritten_baselines", []))[:8], 1):
        lines.append(
            f"- {idx}. `{row['candidate_id']}`：{row['source_lab']} / {row['family_id']} / {row['variant_id']}，"
            f"收益 `{row['total_return_pct']}%`，回撤 `{row['max_drawdown_abs_pct']}%`，PF `{row['profit_factor']}`。"
        )
    sizing = _mapping(report.get("position_sizing_diagnostics"))
    lines.extend(
        [
            "",
            "## 仓位缩放诊断",
            "",
            f"- 诊断范围：`{sizing.get('scope')}`",
            f"- 诊断行数：`{sizing.get('row_count')}`",
            "- 仓位缩放只用于观察风险形态，不进入主短名单，不写 paper 队列，不解锁 live。",
            "",
            "## 复核重点",
            "",
            "- GA 只组合已登记 primitive 和阈值，不直接生成完整交易系统。",
            "- 输出只用于 research-only 复核，不写 paper 队列，不解锁 live。",
            "- 任何候选都必须继续和手写规则基线、行情分段、成本压力、回撤归因比较。",
            "- formal/extended 档位会显著增加数据挖掘风险，报告必须保留 trial_count 和 rejected_count。",
        ]
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


def _grid_fieldnames() -> list[str]:
    return [
        "candidate_id",
        "genome_hash",
        "genome_type",
        "condition_count",
        "cooldown_bars",
        "sizing_mode",
        "entry_primitive_ids",
        "exit_primitive_ids",
        "train_fitness",
        "validation_score",
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


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _portable_path(path: Path) -> str:
    return str(path).replace("\\", "/")


def _ts(value: Any) -> str:
    return pd.Timestamp(value).isoformat()


def _git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return "unknown"
