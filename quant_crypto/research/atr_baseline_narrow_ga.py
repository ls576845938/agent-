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

from quant_crypto.research.simple_trend_rule_lab import (
    BASE_COST_BPS,
    BASE_INTERVAL,
    DEFAULT_DERIVATIVES_ROWS,
    DEFAULT_MARKET_DB,
    EXCHANGE,
    INITIAL_CAPITAL,
    SYMBOL,
    TrendRuleSpec,
    aggregate_ohlcv,
    align_derivatives_to_index,
    evaluate_rule,
    load_market_1h,
    performance_metrics,
    simple_trend_rule_specs,
)


SCHEMA_VERSION = "btc_atr_baseline_narrow_ga_v1"
DEFAULT_OUTPUT_DIR = Path("artifacts/btc_atr_baseline_narrow_ga/latest")
DEFAULT_REPORT_PATH = DEFAULT_OUTPUT_DIR / "btc_atr_baseline_narrow_ga_report.json"
DEFAULT_GRID_PATH = DEFAULT_OUTPUT_DIR / "btc_atr_baseline_narrow_ga_grid.csv"
DEFAULT_MARKDOWN_PATH = DEFAULT_OUTPUT_DIR / "btc_atr_baseline_narrow_ga_summary_cn.md"

GA_RUN_PROFILES = {
    "smoke": {"population_size": 64, "generations": 20},
    "formal": {"population_size": 128, "generations": 60},
    "extended": {"population_size": 256, "generations": 100},
}
EMA_MIDLINE_GRID = (72, 96, 120, 144)
ATR_MULTIPLIER_GRID = (1.0, 1.2, 1.5, 2.0, 2.5)
EXIT_TYPE_GRID = ("atr_channel", "ema_mid", "donchian_low", "atr_trail", "failed_breakout")
DONCHIAN_EXIT_WINDOWS = (24, 48, 60, 90, 120)
FAILED_BREAKOUT_WINDOWS = (6, 12, 24)
COOLDOWN_BAR_GRID = (0, 6, 12)
FILTER_MODE_GRID = ("none", "daily_ema50_200", "vol_not_extreme")
MAX_CONDITION_COUNT = 4
DEFAULT_SELECTED_CANDIDATE_COUNT = 12


@dataclass(frozen=True)
class AtrNarrowGenome:
    ma_window: int
    entry_k: float
    exit_type: str
    exit_k: float
    donchian_exit_window: int
    failed_breakout_window: int
    cooldown_bars: int
    filter_mode: str = "none"
    atr_window: int = 20

    @property
    def condition_count(self) -> int:
        # Entry ATR breakout + optional filter + one exit rule + optional cooldown gate.
        return 1 + (0 if self.filter_mode == "none" else 1) + 1 + (1 if self.cooldown_bars > 0 else 0)

    @property
    def genome_hash(self) -> str:
        return hashlib.sha1(json.dumps(self.to_dict(), sort_keys=True).encode("utf-8")).hexdigest()[:12]

    def to_dict(self) -> dict[str, Any]:
        return {
            "ma_window": int(self.ma_window),
            "atr_window": int(self.atr_window),
            "entry_k": _round(self.entry_k),
            "exit_type": self.exit_type,
            "exit_k": _round(self.exit_k),
            "donchian_exit_window": int(self.donchian_exit_window),
            "failed_breakout_window": int(self.failed_breakout_window),
            "cooldown_bars": int(self.cooldown_bars),
            "filter_mode": self.filter_mode,
            "condition_count": int(self.condition_count),
        }


@dataclass
class EvaluatedAtrGenome:
    genome: AtrNarrowGenome
    raw_signal: pd.Series
    exposure: pd.Series
    returns: pd.Series
    turnover: pd.Series
    cost: pd.Series
    equity: pd.Series
    metrics: dict[str, Any]


def build_btc_atr_baseline_narrow_ga(
    *,
    market_db_path: Path = DEFAULT_MARKET_DB,
    derivatives_rows_path: Path = DEFAULT_DERIVATIVES_ROWS,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    generated_at_utc: datetime | None = None,
    seed: int = 20260629,
    run_profile: str = "formal",
    population_size: int | None = None,
    generations: int | None = None,
    selected_candidate_count: int = DEFAULT_SELECTED_CANDIDATE_COUNT,
    initial_capital: float = INITIAL_CAPITAL,
    base_cost_bps: float = BASE_COST_BPS,
    validation_fraction: float = 0.20,
    holdout_fraction: float = 0.15,
    embargo_bars: int = 4,
) -> dict[str, Any]:
    generated = generated_at_utc or datetime.now(timezone.utc)
    profile = _resolve_ga_profile(run_profile, population_size=population_size, generations=generations)
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / DEFAULT_REPORT_PATH.name
    grid_path = output_dir / DEFAULT_GRID_PATH.name
    markdown_path = output_dir / DEFAULT_MARKDOWN_PATH.name

    bars_1h = load_market_1h(market_db_path)
    bars_4h = aggregate_ohlcv(bars_1h, interval_hours=4)
    bars_1d = aggregate_ohlcv(bars_1h, interval_hours=24)
    derivatives_4h = align_derivatives_to_index(derivatives_rows_path, bars_4h.index)
    splits = _locked_splits(bars_4h.index, validation_fraction=validation_fraction, holdout_fraction=holdout_fraction, embargo_bars=embargo_bars)
    blockers = _split_blockers(splits)

    baseline_review = _review_atr_handwritten_baselines(
        bars_4h=bars_4h,
        bars_1d=bars_1d,
        derivatives_4h=derivatives_4h,
        splits=splits,
        initial_capital=initial_capital,
        cost_bps=base_cost_bps,
    )
    rng = random.Random(seed)
    run = _run_narrow_ga(
        bars_4h=bars_4h,
        bars_1d=bars_1d,
        rng=rng,
        population_size=int(profile["population_size"]),
        generations=int(profile["generations"]),
        train_index=splits["train_index"],
        initial_capital=initial_capital,
        cost_bps=base_cost_bps,
    )
    candidates = _select_candidates(
        run["candidate_pool"],
        bars_4h=bars_4h,
        bars_1d=bars_1d,
        splits=splits,
        selected_candidate_count=selected_candidate_count,
        initial_capital=initial_capital,
        cost_bps=base_cost_bps,
    )
    shortlist = _research_shortlist(candidates)
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated.isoformat(),
        "status": "blocked" if blockers else "complete_research_only",
        "decision": "btc_atr_baseline_narrow_ga_research_only_no_paper_no_live",
        "scope": "atr_channel_baseline_attribution_and_narrow_formal_ga_search",
        "code_commit": _git_commit(),
        "input": {
            "market_db_path": _portable_path(market_db_path),
            "derivatives_rows_path": _portable_path(derivatives_rows_path),
            "symbol": SYMBOL,
            "exchange": EXCHANGE,
            "source_interval": "1h",
            "decision_interval": BASE_INTERVAL,
            "market_1h_rows": int(len(bars_1h)),
            "bar_4h_rows": int(len(bars_4h)),
            "bar_1d_rows": int(len(bars_1d)),
            "bar_4h_start": _ts(bars_4h.index.min()) if len(bars_4h) else None,
            "bar_4h_end": _ts(bars_4h.index.max()) if len(bars_4h) else None,
            "completed_bar_rule": "1h completed bars only; 4h/1d derived from completed 1h chunks",
        },
        "step_results": {
            "step_1_atr_baseline_review": "completed",
            "step_2_narrow_formal_search_space": "completed",
            "step_3_confirmatory_holdout_locked": "completed",
            "step_4_formal_narrow_ga_run": "completed" if not blockers else "blocked",
        },
        "search_space": _search_space(),
        "holdout_lock": _holdout_lock_payload(splits, validation_fraction=validation_fraction, holdout_fraction=holdout_fraction, embargo_bars=embargo_bars),
        "ga_config": {
            "seed": int(seed),
            "run_profile": run_profile,
            "profile_defaults": GA_RUN_PROFILES,
            "population_size": int(profile["population_size"]),
            "generations": int(profile["generations"]),
            "trial_count": int(run["trial_count"]),
            "rejected_count": int(run["rejected_count"]),
            "seeded_genome_count": int(run["seeded_genome_count"]),
            "candidate_pool_count": int(len(run["candidate_pool"])),
            "selected_candidate_count": int(len(candidates)),
            "selection_policy": "GA evolves on train only; validation ranks candidates; locked holdout is evaluated once after selection",
        },
        "atr_handwritten_baseline_review": baseline_review,
        "candidate_rule_genomes": candidates,
        "extended_research_shortlist": shortlist,
        "guardrails": _guardrails(),
        "gate": {
            "paper_queue_write_allowed": False,
            "paper_candidate_created": False,
            "live_unlock_allowed": False,
            "live_order_allowed": False,
            "oms_access_allowed": False,
            "broker_access_allowed": False,
            "strategy_skeleton_generated": False,
            "reason": "ATR narrow GA is research-only; holdout passing candidates still require separate manual review",
        },
        "blockers": blockers,
        "warnings": _warnings(candidates, baseline_review),
        "outputs": {
            "json": _portable_path(report_path),
            "grid_csv": _portable_path(grid_path),
            "summary_cn": _portable_path(markdown_path),
        },
    }
    _write_json(report_path, report)
    _write_csv(grid_path, _grid_fieldnames(), candidates)
    _write_text(markdown_path, render_btc_atr_baseline_narrow_ga_markdown(report))
    return report


def evaluate_atr_genome(
    genome: AtrNarrowGenome,
    *,
    bars_4h: pd.DataFrame,
    bars_1d: pd.DataFrame,
    initial_capital: float,
    cost_bps: float,
    index: pd.DatetimeIndex | None = None,
) -> EvaluatedAtrGenome:
    _validate_genome(genome)
    close = bars_4h["close"].astype(float)
    raw = _atr_narrow_signal(genome, bars_4h=bars_4h, bars_1d=bars_1d).reindex(close.index).fillna(0.0).clip(0.0, 1.0)
    exposure = raw.shift(1).fillna(0.0).clip(0.0, 1.0)
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
    metrics = performance_metrics(
        strategy_returns=returns,
        equity=equity,
        exposure=exposure,
        turnover=turnover,
        cost=cost,
        interval=BASE_INTERVAL,
        initial_capital=initial_capital,
    )
    return EvaluatedAtrGenome(genome, raw, exposure, returns, turnover, cost, equity, metrics)


def _review_atr_handwritten_baselines(
    *,
    bars_4h: pd.DataFrame,
    bars_1d: pd.DataFrame,
    derivatives_4h: pd.DataFrame,
    splits: Mapping[str, pd.DatetimeIndex],
    initial_capital: float,
    cost_bps: float,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for spec in simple_trend_rule_specs():
        if spec.family_id != "atr_channel":
            continue
        item = evaluate_rule(spec, bars_4h=bars_4h, bars_1d=bars_1d, derivatives_4h=derivatives_4h, initial_capital=initial_capital, cost_bps=cost_bps)
        yearly = _period_summary(item.returns, item.exposure, item.turnover, item.cost, initial_capital=initial_capital, groups="year")
        recent = _slice_metrics(item.returns, item.exposure, item.turnover, item.cost, splits["holdout_index"], initial_capital=initial_capital)
        trades = _trade_concentration(item.returns, item.exposure)
        drawdown = _drawdown_attribution(item.equity, item.exposure)
        row = {
            "candidate_id": spec.candidate_id,
            "variant_id": spec.variant_id,
            "label": spec.label,
            "params": spec.params,
            "full_metrics": item.metrics,
            "train_metrics": _slice_metrics(item.returns, item.exposure, item.turnover, item.cost, splits["train_index"], initial_capital=initial_capital),
            "validation_metrics": _slice_metrics(item.returns, item.exposure, item.turnover, item.cost, splits["validation_index"], initial_capital=initial_capital),
            "holdout_metrics": recent,
            "yearly_return_attribution": yearly,
            "recent_segment_review": {"segment": "locked_holdout", "still_effective": _segment_passed(recent), "metrics": recent},
            "trade_return_concentration": trades,
            "max_drawdown_attribution": drawdown,
            "score": _round(_selection_score(item.metrics, annual=yearly, recent=recent, cost_stress=_cost_stress_proxy(item.metrics), genome_condition_count=2)),
            "same_window_as_ga": True,
            "paper_queue_write_allowed": False,
            "live_unlock_allowed": False,
        }
        rows.append(row)
    ranked = sorted(rows, key=lambda row: (-float(row["score"]), str(row["candidate_id"])))
    return {
        "review_question": "Why did the handwritten ATR channel family dominate the previous comparison?",
        "baseline_count": len(ranked),
        "ranked_baselines": ranked,
        "strongest_baseline": ranked[0] if ranked else None,
        "summary_zh": _atr_baseline_summary_zh(ranked),
    }


def _run_narrow_ga(
    *,
    bars_4h: pd.DataFrame,
    bars_1d: pd.DataFrame,
    rng: random.Random,
    population_size: int,
    generations: int,
    train_index: pd.DatetimeIndex,
    initial_capital: float,
    cost_bps: float,
) -> dict[str, Any]:
    seed_genomes = _seed_genomes()
    population = seed_genomes[:population_size]
    while len(population) < population_size:
        population.append(_random_genome(rng))
    pool: list[tuple[float, AtrNarrowGenome, dict[str, Any]]] = []
    trial_count = 0
    rejected_count = 0
    for _ in range(generations):
        scored: list[tuple[float, AtrNarrowGenome, dict[str, Any]]] = []
        for genome in population:
            trial_count += 1
            item = evaluate_atr_genome(genome, bars_4h=bars_4h, bars_1d=bars_1d, initial_capital=initial_capital, cost_bps=cost_bps, index=train_index)
            annual = _period_summary(item.returns, item.exposure, item.turnover, item.cost, initial_capital=initial_capital, groups="year")
            recent = _recent_metrics(item.returns, item.exposure, item.turnover, item.cost, initial_capital=initial_capital)
            fitness = _selection_score(item.metrics, annual=annual, recent=recent, cost_stress=_cost_stress_proxy(item.metrics), genome_condition_count=genome.condition_count)
            if fitness <= 0.0:
                rejected_count += 1
            scored.append((fitness, genome, item.metrics))
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
    unique: dict[str, tuple[float, AtrNarrowGenome, dict[str, Any]]] = {}
    for item in pool:
        unique.setdefault(item[1].genome_hash, item)
    return {
        "trial_count": trial_count,
        "rejected_count": rejected_count,
        "seeded_genome_count": min(len(seed_genomes), population_size),
        "candidate_pool": list(unique.values()),
    }


def _select_candidates(
    candidate_pool: Sequence[tuple[float, AtrNarrowGenome, dict[str, Any]]],
    *,
    bars_4h: pd.DataFrame,
    bars_1d: pd.DataFrame,
    splits: Mapping[str, pd.DatetimeIndex],
    selected_candidate_count: int,
    initial_capital: float,
    cost_bps: float,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    preselected = sorted(candidate_pool, key=lambda item: (-item[0], item[1].genome_hash))[: max(selected_candidate_count * 8, 64)]
    for train_fitness, genome, train_metrics in preselected:
        validation = evaluate_atr_genome(genome, bars_4h=bars_4h, bars_1d=bars_1d, initial_capital=initial_capital, cost_bps=cost_bps, index=splits["validation_index"])
        holdout = evaluate_atr_genome(genome, bars_4h=bars_4h, bars_1d=bars_1d, initial_capital=initial_capital, cost_bps=cost_bps, index=splits["holdout_index"])
        full = evaluate_atr_genome(genome, bars_4h=bars_4h, bars_1d=bars_1d, initial_capital=initial_capital, cost_bps=cost_bps)
        annual = _period_summary(full.returns, full.exposure, full.turnover, full.cost, initial_capital=initial_capital, groups="year")
        recent = _slice_metrics(full.returns, full.exposure, full.turnover, full.cost, splits["holdout_index"], initial_capital=initial_capital)
        cost_stress = _cost_stress_summary(genome, bars_4h=bars_4h, bars_1d=bars_1d, initial_capital=initial_capital)
        validation_score = _selection_score(validation.metrics, annual=annual, recent=recent, cost_stress=cost_stress, genome_condition_count=genome.condition_count)
        row = {
            "candidate_id": f"btc_atr_narrow_ga_{genome.genome_hash}",
            "genome_hash": genome.genome_hash,
            "genome": genome.to_dict(),
            "train_fitness": _round(train_fitness),
            "train_metrics": train_metrics,
            "validation_metrics": validation.metrics,
            "holdout_metrics": holdout.metrics,
            "full_metrics": full.metrics,
            "annual_return_attribution": annual,
            "recent_segment_review": {"segment": "locked_holdout", "still_effective": _segment_passed(holdout.metrics), "metrics": holdout.metrics},
            "trade_return_concentration": _trade_concentration(full.returns, full.exposure),
            "max_drawdown_attribution": _drawdown_attribution(full.equity, full.exposure),
            "cost_stress": cost_stress,
            "validation_score": _round(validation_score),
            "retention_decision": _retention_decision(validation.metrics, holdout.metrics, annual, cost_stress),
            "selected_by": "validation_score_after_train_only_evolution",
            "holdout_used_for_selection": False,
            "scope": "research_only_atr_narrow_ga_candidate",
            "paper_queue_write_allowed": False,
            "live_unlock_allowed": False,
        }
        rows.append(row)
    ranked = sorted(rows, key=lambda row: (-float(row["validation_score"]), str(row["candidate_id"])))
    return ranked[:selected_candidate_count]


def _atr_narrow_signal(genome: AtrNarrowGenome, *, bars_4h: pd.DataFrame, bars_1d: pd.DataFrame) -> pd.Series:
    close = bars_4h["close"].astype(float)
    high = bars_4h["high"].astype(float)
    low = bars_4h["low"].astype(float)
    atr = _atr(high=high, low=low, close=close, window=genome.atr_window)
    mid = _ema(close, genome.ma_window)
    entry = close > mid + float(genome.entry_k) * atr
    if genome.filter_mode == "daily_ema50_200":
        daily_fast = _ema(bars_1d["close"].astype(float), 50)
        daily_slow = _ema(bars_1d["close"].astype(float), 200)
        daily_ok = ((daily_fast > daily_slow) & (bars_1d["close"].astype(float) > daily_slow)).reindex(close.index, method="ffill").fillna(False)
        entry = entry & daily_ok.astype(bool)
    elif genome.filter_mode == "vol_not_extreme":
        vol = close.pct_change().rolling(60).std(ddof=0)
        cap = vol.rolling(240, min_periods=60).quantile(0.85).shift(1)
        entry = entry & ((vol <= cap) | cap.isna())
    if genome.exit_type == "atr_channel":
        exit_signal = close < mid - float(genome.exit_k) * atr
    elif genome.exit_type == "ema_mid":
        exit_signal = close < mid
    elif genome.exit_type == "donchian_low":
        exit_signal = close < low.shift(1).rolling(int(genome.donchian_exit_window)).min()
    elif genome.exit_type == "atr_trail":
        trail_high = close.shift(1).rolling(max(24, int(genome.ma_window // 2))).max()
        exit_signal = close < trail_high - float(genome.exit_k) * atr
    elif genome.exit_type == "failed_breakout":
        recent_breakout = entry.shift(1).rolling(int(genome.failed_breakout_window), min_periods=1).max().fillna(False).astype(bool)
        exit_signal = recent_breakout & (close < mid)
    else:
        raise ValueError(f"exit_type_not_allowed:{genome.exit_type}")
    return _stateful_long_flat(entry, exit_signal, cooldown_bars=genome.cooldown_bars).reindex(close.index).fillna(0.0)


def _locked_splits(index: pd.DatetimeIndex, *, validation_fraction: float, holdout_fraction: float, embargo_bars: int) -> dict[str, pd.DatetimeIndex]:
    n = len(index)
    holdout_start = int(n * (1.0 - holdout_fraction))
    validation_start = int(n * (1.0 - holdout_fraction - validation_fraction))
    train_end = max(0, validation_start - int(embargo_bars))
    validation_end = max(validation_start, holdout_start - int(embargo_bars))
    return {
        "train_index": index[:train_end],
        "validation_index": index[validation_start:validation_end],
        "holdout_index": index[holdout_start:],
    }


def _split_blockers(splits: Mapping[str, pd.DatetimeIndex]) -> list[str]:
    blockers = []
    for name in ["train_index", "validation_index", "holdout_index"]:
        if len(splits[name]) < 120:
            blockers.append(f"{name}_too_short:{len(splits[name])}")
    return blockers


def _holdout_lock_payload(splits: Mapping[str, pd.DatetimeIndex], *, validation_fraction: float, holdout_fraction: float, embargo_bars: int) -> dict[str, Any]:
    return {
        "locked_before_search": True,
        "holdout_used_for_ga_evolution": False,
        "holdout_used_for_candidate_ranking": False,
        "validation_fraction": float(validation_fraction),
        "holdout_fraction": float(holdout_fraction),
        "embargo_bars": int(embargo_bars),
        "train": _index_payload(splits["train_index"]),
        "validation": _index_payload(splits["validation_index"]),
        "confirmatory_holdout": _index_payload(splits["holdout_index"]),
    }


def _index_payload(index: pd.DatetimeIndex) -> dict[str, Any]:
    return {"row_count": int(len(index)), "start": _ts(index.min()) if len(index) else None, "end": _ts(index.max()) if len(index) else None}


def _seed_genomes() -> list[AtrNarrowGenome]:
    return [
        AtrNarrowGenome(96, 1.5, "atr_channel", 1.5, 60, 12, 0, "none"),
        AtrNarrowGenome(96, 1.5, "atr_channel", 1.0, 60, 12, 0, "none"),
        AtrNarrowGenome(96, 1.5, "ema_mid", 1.5, 60, 12, 0, "none"),
        AtrNarrowGenome(96, 1.5, "atr_trail", 2.0, 60, 12, 6, "none"),
        AtrNarrowGenome(96, 1.5, "donchian_low", 1.5, 60, 12, 0, "none"),
        AtrNarrowGenome(96, 1.5, "failed_breakout", 1.5, 60, 12, 6, "none"),
        AtrNarrowGenome(120, 1.2, "atr_channel", 1.5, 90, 12, 6, "none"),
        AtrNarrowGenome(72, 1.5, "ema_mid", 1.5, 48, 12, 0, "vol_not_extreme"),
        AtrNarrowGenome(144, 1.2, "atr_trail", 2.0, 90, 24, 12, "daily_ema50_200"),
    ]


def _random_genome(rng: random.Random) -> AtrNarrowGenome:
    return AtrNarrowGenome(
        ma_window=rng.choice(EMA_MIDLINE_GRID),
        entry_k=rng.choice(ATR_MULTIPLIER_GRID),
        exit_type=rng.choice(EXIT_TYPE_GRID),
        exit_k=rng.choice(ATR_MULTIPLIER_GRID),
        donchian_exit_window=rng.choice(DONCHIAN_EXIT_WINDOWS),
        failed_breakout_window=rng.choice(FAILED_BREAKOUT_WINDOWS),
        cooldown_bars=rng.choice(COOLDOWN_BAR_GRID),
        filter_mode=rng.choice(FILTER_MODE_GRID),
    )


def _crossover(parent_a: AtrNarrowGenome, parent_b: AtrNarrowGenome, rng: random.Random) -> AtrNarrowGenome:
    return AtrNarrowGenome(
        ma_window=rng.choice([parent_a.ma_window, parent_b.ma_window]),
        entry_k=rng.choice([parent_a.entry_k, parent_b.entry_k]),
        exit_type=rng.choice([parent_a.exit_type, parent_b.exit_type]),
        exit_k=rng.choice([parent_a.exit_k, parent_b.exit_k]),
        donchian_exit_window=rng.choice([parent_a.donchian_exit_window, parent_b.donchian_exit_window]),
        failed_breakout_window=rng.choice([parent_a.failed_breakout_window, parent_b.failed_breakout_window]),
        cooldown_bars=rng.choice([parent_a.cooldown_bars, parent_b.cooldown_bars]),
        filter_mode=rng.choice([parent_a.filter_mode, parent_b.filter_mode]),
    )


def _mutate(genome: AtrNarrowGenome, rng: random.Random) -> AtrNarrowGenome:
    payload = genome.to_dict()
    field = rng.choice(["ma_window", "entry_k", "exit_type", "exit_k", "donchian_exit_window", "failed_breakout_window", "cooldown_bars", "filter_mode"])
    if field == "ma_window":
        payload[field] = rng.choice(EMA_MIDLINE_GRID)
    elif field in {"entry_k", "exit_k"}:
        payload[field] = rng.choice(ATR_MULTIPLIER_GRID)
    elif field == "exit_type":
        payload[field] = rng.choice(EXIT_TYPE_GRID)
    elif field == "donchian_exit_window":
        payload[field] = rng.choice(DONCHIAN_EXIT_WINDOWS)
    elif field == "failed_breakout_window":
        payload[field] = rng.choice(FAILED_BREAKOUT_WINDOWS)
    elif field == "cooldown_bars":
        payload[field] = rng.choice(COOLDOWN_BAR_GRID)
    elif field == "filter_mode":
        payload[field] = rng.choice(FILTER_MODE_GRID)
    return _genome_from_mapping(payload)


def _genome_from_mapping(payload: Mapping[str, Any]) -> AtrNarrowGenome:
    return AtrNarrowGenome(
        ma_window=int(payload["ma_window"]),
        entry_k=float(payload["entry_k"]),
        exit_type=str(payload["exit_type"]),
        exit_k=float(payload["exit_k"]),
        donchian_exit_window=int(payload["donchian_exit_window"]),
        failed_breakout_window=int(payload["failed_breakout_window"]),
        cooldown_bars=int(payload["cooldown_bars"]),
        filter_mode=str(payload.get("filter_mode", "none")),
        atr_window=int(payload.get("atr_window", 20)),
    )


def _validate_genome(genome: AtrNarrowGenome) -> None:
    if genome.ma_window not in EMA_MIDLINE_GRID:
        raise ValueError(f"ma_window_not_allowed:{genome.ma_window}")
    if genome.entry_k not in ATR_MULTIPLIER_GRID or genome.exit_k not in ATR_MULTIPLIER_GRID:
        raise ValueError("atr_multiplier_not_allowed")
    if genome.exit_type not in EXIT_TYPE_GRID:
        raise ValueError(f"exit_type_not_allowed:{genome.exit_type}")
    if genome.donchian_exit_window not in DONCHIAN_EXIT_WINDOWS:
        raise ValueError(f"donchian_exit_window_not_allowed:{genome.donchian_exit_window}")
    if genome.failed_breakout_window not in FAILED_BREAKOUT_WINDOWS:
        raise ValueError(f"failed_breakout_window_not_allowed:{genome.failed_breakout_window}")
    if genome.cooldown_bars not in COOLDOWN_BAR_GRID:
        raise ValueError(f"cooldown_bars_not_allowed:{genome.cooldown_bars}")
    if genome.filter_mode not in FILTER_MODE_GRID:
        raise ValueError(f"filter_mode_not_allowed:{genome.filter_mode}")
    if genome.condition_count > MAX_CONDITION_COUNT:
        raise ValueError(f"condition_count_exceeds_limit:{genome.condition_count}")


def _tournament(scored: Sequence[tuple[float, AtrNarrowGenome, dict[str, Any]]], rng: random.Random) -> AtrNarrowGenome:
    picks = rng.sample(list(scored), min(4, len(scored)))
    return sorted(picks, key=lambda item: -item[0])[0][1]


def _period_summary(
    returns: pd.Series,
    exposure: pd.Series,
    turnover: pd.Series,
    cost: pd.Series,
    *,
    initial_capital: float,
    groups: str,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    group_values = returns.index.year if groups == "year" else returns.index.to_period("M").astype(str)
    for label, positions in returns.groupby(group_values).groups.items():
        idx = pd.DatetimeIndex(positions)
        if len(idx) < 20:
            continue
        metrics = _slice_metrics(returns, exposure, turnover, cost, idx, initial_capital=initial_capital)
        rows.append({"segment": str(label), "start": _ts(idx.min()), "end": _ts(idx.max()), "row_count": len(idx), "passed": _segment_passed(metrics), "metrics": metrics})
    positive_returns = [max(0.0, float(row["metrics"]["total_return_pct"])) for row in rows]
    total_positive = sum(positive_returns)
    best_share = max(positive_returns) / total_positive if total_positive else 0.0
    return {
        "segment_count": len(rows),
        "pass_rate": _round(sum(1 for row in rows if row["passed"]) / len(rows) if rows else 0.0),
        "best_positive_year_share": _round(best_share),
        "segments": rows,
    }


def _recent_metrics(returns: pd.Series, exposure: pd.Series, turnover: pd.Series, cost: pd.Series, *, initial_capital: float) -> dict[str, Any]:
    if returns.empty:
        return _slice_metrics(returns, exposure, turnover, cost, returns.index, initial_capital=initial_capital)
    length = max(20, len(returns) // 4)
    return _slice_metrics(returns, exposure, turnover, cost, returns.index[-min(length, len(returns)) :], initial_capital=initial_capital)


def _slice_metrics(
    returns: pd.Series,
    exposure: pd.Series,
    turnover: pd.Series,
    cost: pd.Series,
    index: pd.DatetimeIndex,
    *,
    initial_capital: float,
) -> dict[str, Any]:
    if len(index) == 0:
        equity = float(initial_capital) * (1.0 + returns.loc[index]).cumprod()
        return performance_metrics(strategy_returns=returns.loc[index], equity=equity, exposure=exposure.loc[index], turnover=turnover.loc[index], cost=cost.loc[index], interval=BASE_INTERVAL, initial_capital=initial_capital)
    sub_returns = returns.loc[index]
    equity = float(initial_capital) * (1.0 + sub_returns).cumprod()
    return performance_metrics(
        strategy_returns=sub_returns,
        equity=equity,
        exposure=exposure.loc[index],
        turnover=turnover.loc[index],
        cost=cost.loc[index],
        interval=BASE_INTERVAL,
        initial_capital=initial_capital,
    )


def _trade_concentration(returns: pd.Series, exposure: pd.Series) -> dict[str, Any]:
    trades: list[dict[str, Any]] = []
    in_trade = False
    start: Any = None
    current: list[float] = []
    for ts, exp in exposure.items():
        active = float(exp) > 0.0
        if active and not in_trade:
            in_trade = True
            start = ts
            current = []
        if in_trade:
            current.append(float(returns.loc[ts]))
        if in_trade and not active:
            trades.append(_trade_row(start, ts, current))
            in_trade = False
            current = []
    if in_trade and current:
        trades.append(_trade_row(start, exposure.index[-1], current))
    positive = [max(0.0, float(row["return_pct"])) for row in trades]
    total_positive = sum(positive)
    top_positive = max(positive) if positive else 0.0
    top_three = sum(sorted(positive, reverse=True)[:3])
    return {
        "trade_count": len(trades),
        "positive_trade_count": sum(1 for row in trades if float(row["return_pct"]) > 0.0),
        "top_trade_positive_return_share": _round(top_positive / total_positive if total_positive else 0.0),
        "top_3_trade_positive_return_share": _round(top_three / total_positive if total_positive else 0.0),
        "top_trades": sorted(trades, key=lambda row: -float(row["return_pct"]))[:5],
    }


def _trade_row(start: Any, end: Any, returns: Sequence[float]) -> dict[str, Any]:
    total = 1.0
    for value in returns:
        total *= 1.0 + float(value)
    return {"start": _ts(start), "end": _ts(end), "bar_count": len(returns), "return_pct": _round((total - 1.0) * 100.0)}


def _drawdown_attribution(equity: pd.Series, exposure: pd.Series) -> dict[str, Any]:
    if equity.empty:
        return {"max_drawdown_pct": 0.0, "peak_time": None, "trough_time": None, "recovery_time": None, "duration_bars": 0, "exposure_share_during_drawdown": 0.0}
    running_peak = equity.cummax()
    drawdown = equity / running_peak - 1.0
    trough_time = drawdown.idxmin()
    peak_time = equity.loc[:trough_time].idxmax()
    recovery = equity.loc[trough_time:][equity.loc[trough_time:] >= float(equity.loc[peak_time])]
    recovery_time = recovery.index[0] if len(recovery) else None
    dd_index = equity.loc[peak_time : (recovery_time or trough_time)].index
    return {
        "max_drawdown_pct": _round(float(drawdown.loc[trough_time]) * 100.0),
        "max_drawdown_abs_pct": _round(abs(float(drawdown.loc[trough_time])) * 100.0),
        "peak_time": _ts(peak_time),
        "trough_time": _ts(trough_time),
        "recovery_time": _ts(recovery_time) if recovery_time is not None else None,
        "duration_bars": int(len(dd_index)),
        "duration_days": _round((pd.Timestamp((recovery_time or trough_time)) - pd.Timestamp(peak_time)).total_seconds() / 86_400.0),
        "exposure_share_during_drawdown": _round(float((exposure.loc[dd_index] > 0.0).mean()) if len(dd_index) else 0.0),
    }


def _cost_stress_proxy(metrics: Mapping[str, Any]) -> dict[str, Any]:
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


def _cost_stress_summary(genome: AtrNarrowGenome, *, bars_4h: pd.DataFrame, bars_1d: pd.DataFrame, initial_capital: float) -> dict[str, Any]:
    scenarios = []
    for cost_bps in [BASE_COST_BPS, BASE_COST_BPS * 2.0, BASE_COST_BPS * 5.0]:
        item = evaluate_atr_genome(genome, bars_4h=bars_4h, bars_1d=bars_1d, initial_capital=initial_capital, cost_bps=cost_bps)
        survives = float(item.metrics["total_return_pct"]) > 0.0 and float(item.metrics["profit_factor"]) >= 1.0
        scenarios.append({"cost_bps": _round(cost_bps), "survives": bool(survives), "metrics": item.metrics})
    survival_count = sum(1 for row in scenarios if row["survives"])
    return {"scenario_count": len(scenarios), "survival_count": survival_count, "survival_rate": _round(survival_count / len(scenarios)), "scenarios": scenarios}


def _selection_score(
    metrics: Mapping[str, Any],
    *,
    annual: Mapping[str, Any],
    recent: Mapping[str, Any],
    cost_stress: Mapping[str, Any],
    genome_condition_count: int,
) -> float:
    score = float(metrics.get("total_return_pct", 0.0)) * 0.25
    score += min(float(metrics.get("profit_factor", 0.0)), 5.0) * 8.0
    score += float(metrics.get("sharpe_ratio", 0.0)) * 8.0
    score -= float(metrics.get("max_drawdown_abs_pct", 0.0)) * 0.75
    score += float(annual.get("pass_rate", 0.0)) * 12.0
    score += float(cost_stress.get("survival_rate", 0.0)) * 12.0
    score += 6.0 if _segment_passed(recent) else -6.0
    score -= max(0.0, float(annual.get("best_positive_year_share", 0.0)) - 0.70) * 50.0
    score -= max(0, int(genome_condition_count) - 3) * 2.0
    if float(metrics.get("average_exposure", 0.0)) < 0.03:
        score -= 20.0
    return _round(score)


def _retention_decision(validation: Mapping[str, Any], holdout: Mapping[str, Any], annual: Mapping[str, Any], cost_stress: Mapping[str, Any]) -> str:
    if float(validation.get("total_return_pct", 0.0)) <= 0.0:
        return "reject_non_positive_validation_return"
    if float(validation.get("profit_factor", 0.0)) < 1.05:
        return "defer_validation_profit_factor_too_thin"
    if float(holdout.get("total_return_pct", 0.0)) <= 0.0:
        return "reject_non_positive_confirmatory_holdout_return"
    if float(holdout.get("profit_factor", 0.0)) < 1.0:
        return "defer_holdout_profit_factor_below_1"
    if float(validation.get("max_drawdown_abs_pct", 0.0)) > 30.0 or float(holdout.get("max_drawdown_abs_pct", 0.0)) > 30.0:
        return "defer_drawdown_too_high"
    if float(annual.get("best_positive_year_share", 0.0)) > 0.75:
        return "defer_year_concentration_review"
    if float(cost_stress.get("survival_rate", 0.0)) < 0.67:
        return "defer_cost_stress_fragile"
    return "retain_extended_research_only"


def _research_shortlist(candidates: Sequence[Mapping[str, Any]], *, max_count: int = 4) -> list[dict[str, Any]]:
    retained = [dict(row) for row in candidates if row.get("retention_decision") == "retain_extended_research_only"]
    for row in retained:
        row["shortlist_status"] = "extended_research_manual_review_only"
        row["paper_queue_write_allowed"] = False
        row["live_unlock_allowed"] = False
    return retained[:max_count]


def _segment_passed(metrics: Mapping[str, Any]) -> bool:
    return float(metrics.get("total_return_pct", 0.0)) > 0.0 and float(metrics.get("profit_factor", 0.0)) >= 1.0


def _search_space() -> dict[str, Any]:
    return {
        "scope": "narrow_atr_channel_neighborhood_only",
        "ema_midline_grid": list(EMA_MIDLINE_GRID),
        "atr_multiplier_grid": list(ATR_MULTIPLIER_GRID),
        "exit_type_grid": list(EXIT_TYPE_GRID),
        "donchian_exit_windows": list(DONCHIAN_EXIT_WINDOWS),
        "failed_breakout_windows": list(FAILED_BREAKOUT_WINDOWS),
        "cooldown_bar_grid": list(COOLDOWN_BAR_GRID),
        "filter_mode_grid": list(FILTER_MODE_GRID),
        "max_condition_count": MAX_CONDITION_COUNT,
        "excluded": ["all_non_atr_primitives", "short_branch", "paper_queue", "live_unlock", "OMS", "broker"],
    }


def render_btc_atr_baseline_narrow_ga_markdown(report: Mapping[str, Any]) -> str:
    config = _mapping(report.get("ga_config"))
    holdout = _mapping(report.get("holdout_lock"))
    baseline = _mapping(report.get("atr_handwritten_baseline_review"))
    strongest = _mapping(baseline.get("strongest_baseline"))
    lines = [
        "# BTC ATR 基线复核与窄范围 GA formal",
        "",
        f"- 状态：`{report.get('status')}`",
        f"- 决策：`{report.get('decision')}`",
        f"- 运行档位：`{config.get('run_profile')}`",
        f"- 种群/代数：`{config.get('population_size')}` / `{config.get('generations')}`",
        f"- trial/rejected：`{config.get('trial_count')}` / `{config.get('rejected_count')}`",
        f"- paper 队列：`{_mapping(report.get('gate')).get('paper_queue_write_allowed')}`",
        f"- live 解锁：`{_mapping(report.get('gate')).get('live_unlock_allowed')}`",
        "",
        "## 1. 手写 ATR 基线为什么强",
        "",
        f"- 最强手写 ATR：`{strongest.get('candidate_id')}`，参数 `{strongest.get('params')}`。",
        f"- 全样本收益/PF/回撤：`{_mapping(strongest.get('full_metrics')).get('total_return_pct')}%` / `{_mapping(strongest.get('full_metrics')).get('profit_factor')}` / `{_mapping(strongest.get('full_metrics')).get('max_drawdown_abs_pct')}%`。",
        f"- 最近锁定 holdout 是否仍有效：`{_mapping(strongest.get('recent_segment_review')).get('still_effective')}`。",
        f"- 最大正收益年份占比：`{_mapping(strongest.get('yearly_return_attribution')).get('best_positive_year_share')}`。",
        f"- Top 3 交易正收益占比：`{_mapping(strongest.get('trade_return_concentration')).get('top_3_trade_positive_return_share')}`。",
        "",
        "## 2. 窄范围 formal 搜索",
        "",
        "- 只搜索 ATR channel 邻域：EMA 中线、ATR 倍数、退出类型、冷却期和少量过滤器。",
        "- 最多 4 个条件；不允许全 primitive 大乱斗；不含做空分支。",
        "",
        "## 3. 确认性 holdout",
        "",
        f"- holdout 已在搜索前锁定：`{holdout.get('locked_before_search')}`",
        f"- train：`{_mapping(holdout.get('train')).get('start')}` 到 `{_mapping(holdout.get('train')).get('end')}`，行数 `{_mapping(holdout.get('train')).get('row_count')}`",
        f"- validation：`{_mapping(holdout.get('validation')).get('start')}` 到 `{_mapping(holdout.get('validation')).get('end')}`，行数 `{_mapping(holdout.get('validation')).get('row_count')}`",
        f"- confirmatory holdout：`{_mapping(holdout.get('confirmatory_holdout')).get('start')}` 到 `{_mapping(holdout.get('confirmatory_holdout')).get('end')}`，行数 `{_mapping(holdout.get('confirmatory_holdout')).get('row_count')}`",
        "",
        "## 4. formal 结果 Top 候选",
        "",
    ]
    candidates = list(report.get("candidate_rule_genomes", []))
    if not candidates:
        lines.append("- 当前没有候选。")
    for idx, row in enumerate(candidates[:12], 1):
        val = _mapping(row.get("validation_metrics"))
        hold = _mapping(row.get("holdout_metrics"))
        lines.append(
            f"- {idx}. `{row.get('candidate_id')}`：validation `{val.get('total_return_pct')}%` / PF `{val.get('profit_factor')}`；"
            f"holdout `{hold.get('total_return_pct')}%` / PF `{hold.get('profit_factor')}`；"
            f"结论 `{row.get('retention_decision')}`；参数 `{row.get('genome')}`。"
        )
    lines.extend(
        [
            "",
            "## 边界",
            "",
            "- 本报告只输出 research-only 证据和扩展研究短名单。",
            "- 不写 paper 队列，不解锁 live，不接 broker/OMS。",
            "- holdout 只用于最终确认，不参与 GA 进化和 validation 排名。",
        ]
    )
    return "\n".join(lines) + "\n"


def _atr_baseline_summary_zh(rows: Sequence[Mapping[str, Any]]) -> str:
    if not rows:
        return "未找到 ATR channel 手写基线。"
    top = rows[0]
    full = _mapping(top.get("full_metrics"))
    recent = _mapping(top.get("recent_segment_review"))
    yearly = _mapping(top.get("yearly_return_attribution"))
    trades = _mapping(top.get("trade_return_concentration"))
    drawdown = _mapping(top.get("max_drawdown_attribution"))
    return (
        f"最强 ATR 手写基线为 {top.get('candidate_id')}，全样本收益 {full.get('total_return_pct')}%，"
        f"PF {full.get('profit_factor')}，最大回撤 {full.get('max_drawdown_abs_pct')}%。"
        f"最近 holdout 有效={recent.get('still_effective')}；"
        f"最大正收益年份占比 {yearly.get('best_positive_year_share')}；"
        f"Top3 交易正收益占比 {trades.get('top_3_trade_positive_return_share')}；"
        f"最大回撤区间 {drawdown.get('peak_time')} 到 {drawdown.get('trough_time')}。"
    )


def _resolve_ga_profile(run_profile: str, *, population_size: int | None, generations: int | None) -> dict[str, int]:
    if run_profile not in GA_RUN_PROFILES:
        raise ValueError(f"ga_run_profile_not_allowed:{run_profile}")
    resolved = dict(GA_RUN_PROFILES[run_profile])
    if population_size is not None:
        resolved["population_size"] = int(population_size)
    if generations is not None:
        resolved["generations"] = int(generations)
    if resolved["population_size"] <= 0 or resolved["generations"] <= 0:
        raise ValueError("ga_population_and_generations_must_be_positive")
    return resolved


def _stateful_long_flat(entry: pd.Series, exit_signal: pd.Series, *, cooldown_bars: int) -> pd.Series:
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


def _atr(*, high: pd.Series, low: pd.Series, close: pd.Series, window: int) -> pd.Series:
    previous_close = close.shift(1)
    tr = pd.concat([(high - low).abs(), (high - previous_close).abs(), (low - previous_close).abs()], axis=1).max(axis=1)
    return tr.rolling(window).mean()


def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.astype(float).ewm(span=span, adjust=False).mean()


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


def _warnings(candidates: Sequence[Mapping[str, Any]], baseline_review: Mapping[str, Any]) -> list[str]:
    warnings = ["btc_atr_baseline_narrow_ga_research_only_no_paper_no_live"]
    if not candidates:
        warnings.append("btc_atr_baseline_narrow_ga_no_candidates_selected")
    if any(row.get("retention_decision") != "retain_extended_research_only" for row in candidates):
        warnings.append("btc_atr_baseline_narrow_ga_candidates_require_manual_review")
    strongest = _mapping(baseline_review.get("strongest_baseline"))
    yearly = _mapping(strongest.get("yearly_return_attribution"))
    if float(yearly.get("best_positive_year_share", 0.0)) > 0.75:
        warnings.append("atr_handwritten_baseline_year_concentration_review_required")
    return warnings


def _grid_fieldnames() -> list[str]:
    return [
        "candidate_id",
        "genome_hash",
        "genome",
        "train_fitness",
        "validation_score",
        "retention_decision",
        "holdout_used_for_selection",
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
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False), encoding="utf-8")


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
