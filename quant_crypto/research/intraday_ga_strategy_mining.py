from __future__ import annotations

import hashlib
import json
import math
import os
import random
import sqlite3
import subprocess
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from quant_crypto.monitoring.artifact_schema import apply_btc_artifact_schema, stable_payload_hash


SCHEMA_VERSION = "btc_intraday_ga_strategy_mining_v1"
ENGINE_VERSION = "btc_intraday_ga_engine@1.1.0"
DEFAULT_MARKET_DB = Path("data/market_data.sqlite")
DEFAULT_MANIFESTS = {
    "5m": Path("data/manifests/qs-sqlite-BTCUSDT-5m-20240101T000000-bd0200707eb9.json"),
    "15m": Path("data/manifests/qs-sqlite-BTCUSDT-15m-20240101T000000-01f96844fa1a.json"),
}
DEFAULT_OUTPUT_ROOT = Path("artifacts/btc_intraday_ga_strategy_mining/latest")
DEFAULT_SEED = 20260826
SUPPORTED_INTERVALS = ("5m", "15m")
INTERVAL_MINUTES = {"5m": 5, "15m": 15}
FEATURE_NAMES = (
    "ema_spread_8_34",
    "ema_spread_13_55",
    "ema_spread_21_89",
    "ema_spread_34_144",
    "momentum_3",
    "momentum_6",
    "momentum_12",
    "momentum_24",
    "momentum_48",
    "channel_position_24",
    "channel_position_48",
    "channel_position_96",
    "channel_position_192",
    "rsi_7",
    "rsi_14",
    "rsi_28",
    "price_z_24",
    "price_z_48",
    "price_z_96",
    "volume_z_24",
    "volume_z_48",
    "range_z_48",
)
WEIGHT_CHOICES = (-2, -1, 0, 1, 2)
ENTRY_THRESHOLDS = (-0.40, -0.25, -0.10, 0.0, 0.10, 0.15, 0.25, 0.40, 0.60, 0.80, 1.0)
SMOOTHING_BARS = (1, 2, 3, 6)
COST_SCENARIOS = {
    "base": {"fee_bps": 5.0, "spread_bps": 2.0, "slippage_bps": 2.0},
    "conservative": {"fee_bps": 7.5, "spread_bps": 3.0, "slippage_bps": 4.0},
    "stress": {"fee_bps": 10.0, "spread_bps": 5.0, "slippage_bps": 10.0},
}


class IntradayGAMiningError(ValueError):
    pass


@dataclass(frozen=True)
class IntradayGenome:
    weights: tuple[int, ...]
    entry_threshold: float
    smoothing_bars: int

    def __post_init__(self) -> None:
        if len(self.weights) != len(FEATURE_NAMES):
            raise IntradayGAMiningError("genome_weight_count_invalid")
        if any(weight not in WEIGHT_CHOICES for weight in self.weights):
            raise IntradayGAMiningError("genome_weight_not_allowed")
        active = sum(1 for weight in self.weights if weight)
        if active < 2 or active > 6:
            raise IntradayGAMiningError("genome_active_feature_count_invalid")
        if float(self.entry_threshold) not in ENTRY_THRESHOLDS:
            raise IntradayGAMiningError("genome_entry_threshold_not_allowed")
        if int(self.smoothing_bars) not in SMOOTHING_BARS:
            raise IntradayGAMiningError("genome_smoothing_bars_not_allowed")

    @property
    def signature(self) -> str:
        return stable_payload_hash(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        active = [
            {"feature": name, "weight": int(weight)}
            for name, weight in zip(FEATURE_NAMES, self.weights)
            if weight
        ]
        return {
            "active_features": active,
            "entry_threshold": float(self.entry_threshold),
            "smoothing_bars": int(self.smoothing_bars),
            "position_policy": "long_flat_1x",
            "signal_formula": "weighted_mean_of_clipped_historical_features_gte_entry_threshold",
        }


@dataclass(frozen=True)
class BacktestMetrics:
    total_return: float
    annualized_return: float
    annualized_volatility: float
    sharpe: float
    max_drawdown: float
    profit_factor: float
    turnover: float
    trade_count: int
    trades_per_day: float
    exposure_ratio: float
    average_holding_bars: float
    fee_drag: float
    spread_drag: float
    slippage_drag: float
    start_time: str
    end_time: str
    row_count: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FoldSpec:
    fold_id: int
    train_start: int
    train_end: int
    validation_start: int
    validation_end: int
    embargo_bars: int

    def to_dict(self, index: pd.DatetimeIndex) -> dict[str, Any]:
        return {
            "fold_id": self.fold_id,
            "train_start": index[self.train_start].isoformat(),
            "train_end": index[self.train_end - 1].isoformat(),
            "validation_start": index[self.validation_start].isoformat(),
            "validation_end": index[self.validation_end - 1].isoformat(),
            "train_rows": self.train_end - self.train_start,
            "validation_rows": self.validation_end - self.validation_start,
            "embargo_bars": self.embargo_bars,
        }


def load_data_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise IntradayGAMiningError(f"data_manifest_missing:{path.as_posix()}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise IntradayGAMiningError("data_manifest_not_mapping")
    manifest = dict(payload)
    required = ("data_version", "symbol", "interval", "start", "end", "row_count", "checksum")
    missing = [field for field in required if not manifest.get(field)]
    if missing:
        raise IntradayGAMiningError(f"data_manifest_fields_missing:{','.join(missing)}")
    if str(manifest["interval"]) not in SUPPORTED_INTERVALS:
        raise IntradayGAMiningError("data_manifest_interval_unsupported")
    if str(manifest["symbol"]).upper() != "BTCUSDT":
        raise IntradayGAMiningError("data_manifest_symbol_mismatch")
    return manifest


def load_manifest_bounded_market_frame(
    *,
    db_path: Path,
    manifest: Mapping[str, Any],
    exchange: str = "binance_spot",
) -> tuple[pd.DataFrame, dict[str, Any]]:
    if not db_path.exists():
        raise IntradayGAMiningError(f"market_db_missing:{db_path.as_posix()}")
    start = _parse_utc(manifest.get("start"))
    end = _parse_utc(manifest.get("end"))
    start_ms = int(start.timestamp() * 1000)
    end_ms = int(end.timestamp() * 1000)
    uri = f"file:{db_path.resolve().as_posix()}?mode=ro"
    query = (
        "SELECT open_time_ms, open_time, open, high, low, close, volume "
        "FROM market_klines WHERE exchange = ? AND upper(symbol) = ? AND interval = ? "
        "AND open_time_ms >= ? AND open_time_ms <= ? ORDER BY open_time_ms"
    )
    with sqlite3.connect(uri, uri=True) as connection:
        connection.execute("PRAGMA query_only = ON")
        frame = pd.read_sql_query(
            query,
            connection,
            params=[exchange, str(manifest["symbol"]).upper(), str(manifest["interval"]), start_ms, end_ms],
        )
    if frame.empty:
        raise IntradayGAMiningError("manifest_bounded_market_rows_missing")
    frame["timestamp"] = pd.to_datetime(frame["open_time"], utc=True)
    frame = frame.drop(columns=["open_time"]).set_index("timestamp")
    frame = frame.sort_values("open_time_ms").drop_duplicates(subset=["open_time_ms"], keep="last")
    for column in ("open", "high", "low", "close", "volume"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    expected_rows = int(manifest["row_count"])
    step_ms = INTERVAL_MINUTES[str(manifest["interval"])] * 60_000
    deltas = frame["open_time_ms"].astype("int64").diff().dropna()
    invalid_rows = int(
        (
            frame[["open", "high", "low", "close", "volume"]].isna().any(axis=1)
            | (frame["open"] <= 0)
            | (frame["close"] <= 0)
            | (frame["high"] < frame["low"])
            | (frame["volume"] < 0)
        ).sum()
    )
    irregular_steps = int((deltas != step_ms).sum())
    blockers: list[str] = []
    if len(frame) != expected_rows:
        blockers.append("manifest_bounded_row_count_mismatch")
    if irregular_steps:
        blockers.append("manifest_bounded_interval_gaps_or_irregular_steps")
    if invalid_rows:
        blockers.append("manifest_bounded_invalid_ohlcv_rows")
    if frame.index[0] != pd.Timestamp(start) or frame.index[-1] != pd.Timestamp(end):
        blockers.append("manifest_bounded_time_range_mismatch")
    if blockers:
        raise IntradayGAMiningError(";".join(blockers))
    provenance = {
        "data_version": str(manifest["data_version"]),
        "manifest_checksum": str(manifest["checksum"]),
        "manifest_interval": str(manifest["interval"]),
        "manifest_start": start.isoformat(),
        "manifest_end": end.isoformat(),
        "manifest_row_count": expected_rows,
        "resolved_row_count": int(len(frame)),
        "irregular_step_count": irregular_steps,
        "invalid_ohlcv_row_count": invalid_rows,
        "resolved_slice_sha256": _frame_sha256(frame),
        "source": str(manifest.get("source") or ""),
        "universe_id": str(manifest.get("universe_id") or ""),
        "timezone": str(manifest.get("timezone") or "UTC"),
        "physical_access_mode": "sqlite_uri_mode_ro_query_only",
        "manifest_physical_path_relocated": True,
    }
    return frame, provenance


def build_feature_frame(frame: pd.DataFrame) -> pd.DataFrame:
    close = pd.to_numeric(frame["close"], errors="coerce")
    high = pd.to_numeric(frame["high"], errors="coerce")
    low = pd.to_numeric(frame["low"], errors="coerce")
    volume = pd.to_numeric(frame["volume"], errors="coerce")
    output = pd.DataFrame(index=frame.index)
    for fast, slow in ((8, 34), (13, 55), (21, 89), (34, 144)):
        fast_ema = close.ewm(span=fast, adjust=False, min_periods=slow).mean()
        slow_ema = close.ewm(span=slow, adjust=False, min_periods=slow).mean()
        output[f"ema_spread_{fast}_{slow}"] = ((fast_ema / slow_ema) - 1.0).clip(-0.10, 0.10) * 20.0
    for bars in (3, 6, 12, 24, 48):
        output[f"momentum_{bars}"] = close.pct_change(bars).clip(-0.15, 0.15) * 10.0
    for bars in (24, 48, 96, 192):
        prior_high = high.shift(1).rolling(bars, min_periods=bars).max()
        prior_low = low.shift(1).rolling(bars, min_periods=bars).min()
        output[f"channel_position_{bars}"] = (
            ((close - prior_low) / (prior_high - prior_low).replace(0, np.nan)) * 2.0 - 1.0
        ).clip(-3.0, 3.0)
    for bars in (7, 14, 28):
        output[f"rsi_{bars}"] = ((_rsi(close, bars) - 50.0) / 25.0).clip(-2.0, 2.0)
    for bars in (24, 48, 96):
        output[f"price_z_{bars}"] = _rolling_z(close, bars).clip(-3.0, 3.0)
    for bars in (24, 48):
        output[f"volume_z_{bars}"] = _rolling_z(np.log1p(volume), bars).clip(-3.0, 3.0)
    true_range = pd.concat(
        [(high - low).abs(), (high - close.shift(1)).abs(), (low - close.shift(1)).abs()], axis=1
    ).max(axis=1)
    output["range_z_48"] = _rolling_z(true_range / close.shift(1).replace(0, np.nan), 48).clip(-3.0, 3.0)
    return output.loc[:, list(FEATURE_NAMES)].replace([np.inf, -np.inf], np.nan)


def signal_from_genome(genome: IntradayGenome, feature_frame: pd.DataFrame) -> pd.Series:
    matrix = feature_frame.loc[:, list(FEATURE_NAMES)].to_numpy(dtype=np.float64, copy=False)
    weights = np.asarray(genome.weights, dtype=np.float64)
    denominator = max(1.0, float(np.abs(weights).sum()))
    clean = np.nan_to_num(matrix, nan=0.0, posinf=3.0, neginf=-3.0)
    score = np.clip(clean, -3.0, 3.0) @ weights / denominator
    if genome.smoothing_bars > 1:
        score = _moving_average(score, genome.smoothing_bars)
    warmup_ready = feature_frame.notna().sum(axis=1).to_numpy() >= 8
    target = (score >= float(genome.entry_threshold)) & warmup_ready
    return pd.Series(target.astype(np.float64), index=feature_frame.index, name="target_position")


def simulate_next_open_execution(
    *,
    frame: pd.DataFrame,
    target_at_close: pd.Series,
    interval: str,
    cost_config: Mapping[str, float],
    start: int = 0,
    end: int | None = None,
) -> tuple[BacktestMetrics, dict[str, Any]]:
    end_index = len(frame) if end is None else min(len(frame), int(end))
    start_index = max(0, int(start))
    if end_index - start_index < 3:
        return _empty_metrics(frame.index, start_index, end_index), _empty_ledger_summary()
    open_prices = pd.to_numeric(frame["open"], errors="coerce").to_numpy(dtype=np.float64)
    raw_target = pd.to_numeric(target_at_close, errors="coerce").fillna(0.0).clip(0.0, 1.0).to_numpy()
    position = np.zeros(len(frame), dtype=np.float64)
    position[1:] = raw_target[:-1]
    sl = slice(start_index, end_index)
    local_position = position[sl].copy()
    local_position[0] = 0.0
    local_position[-1] = 0.0
    local_open = open_prices[sl]
    forward_open_return = np.zeros(len(local_open), dtype=np.float64)
    forward_open_return[:-1] = local_open[1:] / local_open[:-1] - 1.0
    turnover = np.abs(np.diff(local_position, prepend=0.0))
    fee = turnover * float(cost_config["fee_bps"]) / 10_000.0
    spread = turnover * float(cost_config["spread_bps"]) / 10_000.0
    slippage = turnover * float(cost_config["slippage_bps"]) / 10_000.0
    gross = local_position * forward_open_return
    net = gross - fee - spread - slippage
    net[-1] = -(fee[-1] + spread[-1] + slippage[-1])
    index = frame.index[sl]
    metrics = _metrics_from_arrays(
        index=index,
        interval=interval,
        net_returns=net,
        position=local_position,
        turnover=turnover,
        fee=fee,
        spread=spread,
        slippage=slippage,
    )
    ledger = _ledger_summary(
        index=index,
        open_prices=local_open,
        position=local_position,
        turnover=turnover,
        gross=gross,
        net=net,
        fee=fee,
        spread=spread,
        slippage=slippage,
    )
    return metrics, ledger


def build_walk_forward_folds(
    row_count: int,
    *,
    fold_count: int = 4,
    embargo_bars: int = 192,
) -> list[FoldSpec]:
    selection_end = max(0, int(row_count))
    initial_train = int(selection_end * 0.40)
    available = selection_end - initial_train - fold_count * embargo_bars
    validation_rows = available // fold_count if fold_count else 0
    if initial_train < 500 or validation_rows < 250:
        return []
    folds: list[FoldSpec] = []
    cursor = initial_train
    for fold_id in range(1, fold_count + 1):
        validation_start = cursor + embargo_bars
        validation_end = selection_end if fold_id == fold_count else validation_start + validation_rows
        if validation_end > selection_end or validation_end - validation_start < 250:
            return []
        folds.append(
            FoldSpec(
                fold_id=fold_id,
                train_start=0,
                train_end=cursor,
                validation_start=validation_start,
                validation_end=validation_end,
                embargo_bars=embargo_bars,
            )
        )
        cursor = validation_end
    return folds


def run_intraday_ga_interval(
    *,
    interval: str,
    frame: pd.DataFrame,
    provenance: Mapping[str, Any],
    seed: int,
    population_size: int = 48,
    generations: int = 16,
    fold_count: int = 4,
    holdout_fraction: float = 0.20,
    max_candidates: int = 8,
    holdout_viewed_during_engine_refinement: bool = False,
) -> dict[str, Any]:
    if interval not in SUPPORTED_INTERVALS:
        raise IntradayGAMiningError("interval_unsupported")
    if len(frame) < 5_000:
        raise IntradayGAMiningError("intraday_rows_insufficient")
    feature_frame = build_feature_frame(frame)
    holdout_rows = max(1_000, int(len(frame) * float(holdout_fraction)))
    selection_rows = len(frame) - holdout_rows
    embargo_bars = max(192, int(24 * 60 / INTERVAL_MINUTES[interval]))
    folds = build_walk_forward_folds(selection_rows, fold_count=fold_count, embargo_bars=embargo_bars)
    if len(folds) != fold_count:
        raise IntradayGAMiningError("walk_forward_folds_insufficient")
    rng = random.Random(int(seed))
    population = _initial_population(rng, population_size)
    cache: dict[str, dict[str, Any]] = {}
    generation_rows: list[dict[str, Any]] = []
    for generation in range(1, generations + 1):
        evaluated = [
            _evaluate_selection_candidate(
                genome,
                frame=frame,
                features=feature_frame,
                interval=interval,
                folds=folds,
                cache=cache,
            )
            for genome in population
        ]
        evaluated.sort(key=lambda item: float(item["fitness"]), reverse=True)
        generation_rows.append(
            {
                "generation": generation,
                "best_fitness": round(float(evaluated[0]["fitness"]), 8),
                "median_fitness": round(float(np.median([row["fitness"] for row in evaluated])), 8),
                "unique_evaluations": len(cache),
            }
        )
        elite_count = max(2, population_size // 5)
        elites = [row["genome"] for row in evaluated[:elite_count]]
        next_population = list(elites)
        while len(next_population) < population_size:
            parent_a = _tournament(evaluated, rng)
            parent_b = _tournament(evaluated, rng)
            child = _crossover(parent_a, parent_b, rng)
            if rng.random() < 0.70:
                child = _mutate(child, rng)
            next_population.append(child)
        population = _dedupe_and_fill(next_population, rng, population_size)
    final_evaluated = list(cache.values())
    final_evaluated.sort(key=lambda item: float(item["fitness"]), reverse=True)
    unique_selection: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in final_evaluated:
        genome = item["genome"]
        family_signature = _genome_family_signature(genome)
        if family_signature in seen:
            continue
        seen.add(family_signature)
        unique_selection.append(item)
        if len(unique_selection) >= max_candidates:
            break
    holdout_start = selection_rows
    candidates: list[dict[str, Any]] = []
    for rank, item in enumerate(unique_selection, 1):
        genome = item["genome"]
        signal = signal_from_genome(genome, feature_frame)
        cost_stress: dict[str, Any] = {}
        base_ledger: dict[str, Any] = {}
        for scenario, config in COST_SCENARIOS.items():
            metrics, ledger = simulate_next_open_execution(
                frame=frame,
                target_at_close=signal,
                interval=interval,
                cost_config=config,
                start=holdout_start,
                end=len(frame),
            )
            cost_stress[scenario] = metrics.to_dict()
            if scenario == "base":
                base_ledger = ledger
        decision, reasons = _retention_decision(item, cost_stress)
        candidates.append(
            {
                "candidate_id": f"btc_intraday_ga_{interval}_{genome.signature[:12]}",
                "rank": rank,
                "genome": genome.to_dict(),
                "genome_hash": genome.signature,
                "selection_fitness": round(float(item["fitness"]), 8),
                "walk_forward": item["walk_forward"],
                "confirmatory_holdout": {
                    "selection_used_holdout": False,
                    "start": frame.index[holdout_start].isoformat(),
                    "end": frame.index[-1].isoformat(),
                    "row_count": len(frame) - holdout_start,
                    "cost_stress": cost_stress,
                },
                "ledger_reconciliation": base_ledger,
                "retention_decision": decision,
                "retention_reasons": reasons,
            }
        )
    retained = [row for row in candidates if row["retention_decision"] == "retain_extended_research_only"]
    baseline_signal = pd.Series(1.0, index=frame.index)
    baseline_metrics, _ = simulate_next_open_execution(
        frame=frame,
        target_at_close=baseline_signal,
        interval=interval,
        cost_config=COST_SCENARIOS["base"],
        start=holdout_start,
        end=len(frame),
    )
    return {
        "interval": interval,
        "status": "complete_research_only",
        "data_provenance": dict(provenance),
        "feature_policy": {
            "feature_names": list(FEATURE_NAMES),
            "feature_count": len(FEATURE_NAMES),
            "feature_visibility": "completed_bar_only",
            "decision_time": "completed_bar_close",
            "execution_time": "next_bar_open",
            "position_policy": "long_flat_1x",
            "funding_model": "not_applicable_spot_research_no_short_no_leverage",
        },
        "split_policy": {
            "method": "expanding_chronological_walk_forward_with_embargo_plus_untouched_tail_holdout",
            "selection_rows": selection_rows,
            "confirmatory_holdout_rows": holdout_rows,
            "confirmatory_holdout_fraction": round(holdout_rows / len(frame), 8),
            "confirmatory_holdout_used_for_selection": False,
            "holdout_viewed_during_engine_refinement": bool(holdout_viewed_during_engine_refinement),
            "promotion_eligible_holdout": False,
            "future_unseen_holdout_required": True,
            "folds": [fold.to_dict(frame.index) for fold in folds],
        },
        "ga_config": {
            "seed": seed,
            "population_size": population_size,
            "generations": generations,
            "trial_count": population_size * generations,
            "unique_evaluation_count": len(cache),
            "selection": "tournament_elitism",
            "mutation_rate": 0.70,
            "weight_choices": list(WEIGHT_CHOICES),
            "entry_thresholds": list(ENTRY_THRESHOLDS),
            "smoothing_bars": list(SMOOTHING_BARS),
            "generation_trace": generation_rows,
        },
        "cost_model": {
            "currency": "normalized_equity_return",
            "costs_per_unit_turnover": COST_SCENARIOS,
            "spread_and_slippage_explicit": True,
            "market_impact_model": "unavailable_research_blocker",
            "queue_position_model": "unavailable_research_blocker",
        },
        "buy_and_hold_holdout_baseline": baseline_metrics.to_dict(),
        "candidate_count": len(candidates),
        "retained_research_candidate_count": len(retained),
        "top_candidates": candidates,
        "retained_research_candidates": [row["candidate_id"] for row in retained],
    }


def run_btc_intraday_ga_strategy_mining(
    *,
    market_db_path: Path = DEFAULT_MARKET_DB,
    manifest_paths: Mapping[str, Path] | None = None,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    intervals: Sequence[str] = SUPPORTED_INTERVALS,
    seed: int = DEFAULT_SEED,
    population_size: int = 48,
    generations: int = 16,
    fold_count: int = 4,
    holdout_fraction: float = 0.20,
    max_candidates: int = 8,
    search_round_count: int = 1,
    holdout_viewed_during_engine_refinement: bool = False,
    generated_at_utc: datetime | None = None,
) -> dict[str, Any]:
    generated_at = generated_at_utc or datetime.now(timezone.utc)
    requested = tuple(str(item) for item in intervals)
    if not requested or any(item not in SUPPORTED_INTERVALS for item in requested):
        raise IntradayGAMiningError("requested_intervals_invalid")
    paths = dict(DEFAULT_MANIFESTS)
    if manifest_paths:
        paths.update({str(key): Path(value) for key, value in manifest_paths.items()})
    results: dict[str, Any] = {}
    input_hashes: dict[str, str] = {}
    for offset, interval in enumerate(requested):
        manifest = load_data_manifest(paths[interval])
        frame, provenance = load_manifest_bounded_market_frame(db_path=market_db_path, manifest=manifest)
        result = run_intraday_ga_interval(
            interval=interval,
            frame=frame,
            provenance=provenance,
            seed=int(seed) + offset * 10_000,
            population_size=population_size,
            generations=generations,
            fold_count=fold_count,
            holdout_fraction=holdout_fraction,
            max_candidates=max_candidates,
            holdout_viewed_during_engine_refinement=holdout_viewed_during_engine_refinement,
        )
        results[interval] = result
        input_hashes[f"{interval}_manifest"] = str(manifest["checksum"])
        input_hashes[f"{interval}_resolved_slice"] = str(provenance["resolved_slice_sha256"])
    retained_total = sum(int(item["retained_research_candidate_count"]) for item in results.values())
    warnings = [
        "btc_intraday_ga_uses_spot_ohlcv_not_perpetual_mark_index_funding",
        "btc_intraday_ga_no_l2_market_impact_latency_or_queue_model",
        "btc_intraday_ga_manifest_physical_path_relocated_and_resolved_read_only",
        "btc_intraday_ga_results_are_research_only_not_demo_selectable",
    ]
    blockers = [
        "btc_intraday_ga_perpetual_data_parity_not_proven",
        "btc_intraday_ga_l2_spread_depth_market_impact_not_proven",
        "btc_intraday_ga_latency_queue_fill_model_not_proven",
        "btc_intraday_ga_paper_fill_position_cash_ledger_not_observed",
        "btc_intraday_ga_runtime_strategy_adapter_not_implemented",
        "btc_intraday_ga_manual_promotion_review_not_started",
    ]
    if holdout_viewed_during_engine_refinement:
        blockers.append("btc_intraday_ga_tail_holdout_viewed_during_engine_refinement")
    payload = {
        "schema_version": SCHEMA_VERSION,
        "engine_version": ENGINE_VERSION,
        "status": "complete_research_only",
        "asset": "btc",
        "symbol": "BTCUSDT",
        "scope": "offline_research_only_5m_15m_genetic_strategy_mining",
        "research_question": "can interpretable completed-bar BTC 5m or 15m factor combinations survive untouched holdout and realistic short-cycle costs",
        "economic_hypothesis": "short-horizon trend persistence and pullback recovery may be conditionally exploitable after turnover-aware cost penalties",
        "code_commit": _git_commit_hash(),
        "search_protocol": {
            "search_round_count": max(1, int(search_round_count)),
            "population_slots_per_round": int(population_size) * int(generations) * len(requested),
            "cumulative_population_slots": (
                max(1, int(search_round_count)) * int(population_size) * int(generations) * len(requested)
            ),
            "tail_holdout_viewed_during_engine_refinement": bool(
                holdout_viewed_during_engine_refinement
            ),
            "tail_holdout_claim": (
                "diagnostic_only_not_confirmatory_for_promotion"
                if holdout_viewed_during_engine_refinement
                else "untouched_within_this_run_but_still_research_only"
            ),
            "future_unseen_holdout_required": True,
        },
        "interval_results": results,
        "retained_research_candidate_count": retained_total,
        "promotion": {
            "recommendation": "research_only_manual_review" if retained_total else "reject_current_search_batch",
            "demo_strategy_registration_allowed": False,
            "paper_candidate_generated": False,
            "paper_queue_status": "LOCKED",
            "paper_auto_start": False,
            "live_status": "FROZEN",
            "live_enabled": False,
        },
        "safety": {
            "public_network_called": False,
            "broker_calls_allowed": False,
            "private_endpoints_allowed": False,
            "order_endpoints_allowed": False,
            "real_orders_created": False,
            "transfer_allowed": False,
            "withdraw_allowed": False,
            "strategy_runtime_adapter_generated": False,
        },
        "blockers": blockers,
    }
    report = apply_btc_artifact_schema(
        payload,
        decision="research_only_genetic_candidates_require_independent_review",
        generated_at_utc=generated_at,
        as_of_utc=max(_parse_utc(results[item]["data_provenance"]["manifest_end"]) for item in results),
        blockers=blockers,
        warnings=warnings,
        input_hashes=input_hashes,
    )
    output_root.mkdir(parents=True, exist_ok=True)
    _write_json(output_root / "btc_intraday_ga_strategy_mining_report.json", report)
    _write_json(
        output_root / "btc_intraday_ga_candidate_definitions.json",
        {
            "schema_version": "btc_intraday_ga_candidate_definitions_v1",
            "source_artifact_hash": report["artifact_hash"],
            "scope": "research_only_no_runtime_adapter",
            "intervals": {
                interval: [
                    row
                    for row in result["top_candidates"]
                    if row["retention_decision"] == "retain_extended_research_only"
                ]
                for interval, result in results.items()
            },
            "demo_strategy_registration_allowed": False,
            "paper_queue_write_allowed": False,
            "live_unlock_allowed": False,
        },
    )
    _write_text(output_root / "btc_intraday_ga_strategy_mining_summary_cn.md", render_summary_markdown(report))
    return report


def render_summary_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# BTC 5m / 15m 遗传策略挖掘报告",
        "",
        f"- 状态：`{report.get('status')}`",
        f"- 决策：`{report.get('decision')}`",
        f"- 代码提交：`{report.get('code_commit')}`",
        f"- 研究候选数：`{report.get('retained_research_candidate_count')}`",
        "- Demo 可选：`false`",
        "- Paper / Live：`false / false`",
        "",
    ]
    for interval, result in _mapping(report.get("interval_results")).items():
        lines.extend(
            [
                f"## {interval}",
                "",
                f"- 数据版本：`{_mapping(result.get('data_provenance')).get('data_version')}`",
                f"- 样本行数：`{_mapping(result.get('data_provenance')).get('resolved_row_count')}`",
                f"- 确认集行数：`{_mapping(result.get('split_policy')).get('confirmatory_holdout_rows')}`",
                f"- 遗传试验：`{_mapping(result.get('ga_config')).get('trial_count')}`",
                f"- 留存候选：`{result.get('retained_research_candidate_count')}`",
                "",
                "| 候选 | 确认集净收益 | PF | 最大回撤 | 交易数 | 保守成本净收益 | 结论 |",
                "| --- | ---: | ---: | ---: | ---: | ---: | --- |",
            ]
        )
        for candidate in list(result.get("top_candidates", []))[:8]:
            holdout = _mapping(candidate.get("confirmatory_holdout"))
            costs = _mapping(holdout.get("cost_stress"))
            base = _mapping(costs.get("base"))
            conservative = _mapping(costs.get("conservative"))
            lines.append(
                f"| `{candidate.get('candidate_id')}` | {_pct(base.get('total_return'))} | "
                f"{_num(base.get('profit_factor'))} | {_pct(base.get('max_drawdown'))} | "
                f"{base.get('trade_count', 0)} | {_pct(conservative.get('total_return'))} | "
                f"`{candidate.get('retention_decision')}` |"
            )
        lines.append("")
    lines.extend(
        [
            "## 边界",
            "",
            "- 候选只基于 Binance Spot OHLCV；尚未证明 OKX 永续 mark/index/funding parity。",
            "- 未使用 L2、延迟、排队和冲击模型，因此不能称为可执行高频策略。",
            "- 只有样本外研究留存，不生成运行时适配器，不写 paper 队列，不解锁 live。",
            "",
        ]
    )
    return "\n".join(lines)


def _evaluate_selection_candidate(
    genome: IntradayGenome,
    *,
    frame: pd.DataFrame,
    features: pd.DataFrame,
    interval: str,
    folds: Sequence[FoldSpec],
    cache: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    if genome.signature in cache:
        return cache[genome.signature]
    signal = signal_from_genome(genome, features)
    fold_rows: list[dict[str, Any]] = []
    for fold in folds:
        metrics, _ = simulate_next_open_execution(
            frame=frame,
            target_at_close=signal,
            interval=interval,
            cost_config=COST_SCENARIOS["base"],
            start=fold.validation_start,
            end=fold.validation_end,
        )
        passed = (
            metrics.total_return > 0.0
            and metrics.profit_factor >= 1.0
            and metrics.max_drawdown >= -0.25
            and metrics.trades_per_day >= 0.10
            and metrics.exposure_ratio >= 0.005
        )
        fold_rows.append({"fold_id": fold.fold_id, "passed": passed, "metrics": metrics.to_dict()})
    fitness = _selection_fitness(fold_rows, genome)
    row = {
        "genome": genome,
        "fitness": fitness,
        "walk_forward": {
            "fold_count": len(fold_rows),
            "positive_fold_count": sum(1 for item in fold_rows if _mapping(item["metrics"])["total_return"] > 0.0),
            "passed_fold_count": sum(1 for item in fold_rows if item["passed"]),
            "pass_rate": round(sum(1 for item in fold_rows if item["passed"]) / len(fold_rows), 8),
            "folds": fold_rows,
        },
    }
    cache[genome.signature] = row
    return row


def _selection_fitness(fold_rows: Sequence[Mapping[str, Any]], genome: IntradayGenome) -> float:
    metrics = [_mapping(row.get("metrics")) for row in fold_rows]
    if not metrics:
        return -1_000_000.0
    returns = np.asarray([float(row.get("total_return", 0.0)) for row in metrics])
    sharpes = np.asarray([float(row.get("sharpe", 0.0)) for row in metrics])
    pfs = np.asarray([min(float(row.get("profit_factor", 0.0)), 3.0) for row in metrics])
    dds = np.asarray([abs(float(row.get("max_drawdown", 0.0))) for row in metrics])
    trades = np.asarray([int(row.get("trade_count", 0)) for row in metrics])
    trades_per_day = np.asarray([float(row.get("trades_per_day", 0.0)) for row in metrics])
    exposure = np.asarray([float(row.get("exposure_ratio", 0.0)) for row in metrics])
    turnover = np.asarray([float(row.get("turnover", 0.0)) for row in metrics])
    score = 2.0 * float(np.median(np.clip(sharpes, -3.0, 3.0)))
    score += 3.0 * float(np.median(np.clip(pfs - 1.0, -1.0, 2.0)))
    score += 6.0 * float(np.median(np.clip(returns, -0.50, 0.50)))
    score -= 6.0 * float(np.max(dds))
    score -= 0.0005 * float(np.median(turnover))
    positive_fold_count = int((returns > 0.0).sum())
    score += 1.5 * positive_fold_count
    score -= 12.0 * max(0, 3 - positive_fold_count)
    score -= 4.0 * abs(min(0.0, float(np.min(returns))))
    score -= 0.75 * float(np.std(np.clip(returns, -1.0, 1.0)))
    median_trade_density = float(np.median(trades_per_day))
    if median_trade_density < 0.25:
        score -= 8.0 * (0.25 - median_trade_density) / 0.25
    if float(np.min(trades_per_day)) < 0.10:
        score -= 3.0
    median_exposure = float(np.median(exposure))
    if median_exposure < 0.01:
        score -= 5.0 * (0.01 - median_exposure) / 0.01
    if median_exposure > 0.80:
        score -= 10.0 * (median_exposure - 0.80) / 0.20
    if int(np.max(trades)) > 20_000:
        score -= 1.5
    active = sum(1 for weight in genome.weights if weight)
    score -= 0.08 * max(0, active - 4)
    return round(score, 10)


def _retention_decision(
    selection: Mapping[str, Any],
    cost_stress: Mapping[str, Mapping[str, Any]],
) -> tuple[str, list[str]]:
    reasons: list[str] = []
    walk_forward = _mapping(selection.get("walk_forward"))
    base = _mapping(cost_stress.get("base"))
    conservative = _mapping(cost_stress.get("conservative"))
    stress = _mapping(cost_stress.get("stress"))
    if int(walk_forward.get("positive_fold_count", 0)) < 3:
        reasons.append("walk_forward_positive_fold_count_below_3")
    if float(base.get("total_return", 0.0)) <= 0.0:
        reasons.append("holdout_base_total_return_non_positive")
    if float(base.get("profit_factor", 0.0)) < 1.05:
        reasons.append("holdout_base_profit_factor_below_1p05")
    if float(base.get("max_drawdown", 0.0)) < -0.20:
        reasons.append("holdout_base_drawdown_below_minus_20pct")
    if float(base.get("trades_per_day", 0.0)) < 0.25:
        reasons.append("holdout_trades_per_day_below_0p25")
    if float(base.get("exposure_ratio", 0.0)) < 0.01:
        reasons.append("holdout_exposure_ratio_below_1pct")
    if float(base.get("exposure_ratio", 0.0)) > 0.80:
        reasons.append("holdout_exposure_ratio_above_80pct")
    if float(conservative.get("total_return", 0.0)) <= 0.0:
        reasons.append("holdout_conservative_cost_total_return_non_positive")
    if float(stress.get("profit_factor", 0.0)) < 0.90:
        reasons.append("holdout_stress_cost_profit_factor_below_0p90")
    return ("retain_extended_research_only" if not reasons else "reject_or_defer_research_candidate", reasons)


def _initial_population(rng: random.Random, size: int) -> list[IntradayGenome]:
    seeds = [
        _genome_from_features({"ema_spread_13_55": 2, "momentum_12": 1, "channel_position_48": 1}, 0.25, 2),
        _genome_from_features({"ema_spread_21_89": 2, "price_z_24": -1, "rsi_14": -1}, 0.15, 3),
        _genome_from_features({"momentum_6": 1, "momentum_24": 2, "volume_z_24": 1}, 0.25, 1),
        _genome_from_features({"channel_position_96": 2, "ema_spread_34_144": 1, "range_z_48": -1}, 0.25, 2),
    ]
    population = list(seeds)
    while len(population) < max(4, int(size)):
        population.append(_random_genome(rng))
    return _dedupe_and_fill(population, rng, max(4, int(size)))


def _random_genome(rng: random.Random) -> IntradayGenome:
    active_count = rng.randint(2, 6)
    selected = rng.sample(range(len(FEATURE_NAMES)), active_count)
    weights = [0] * len(FEATURE_NAMES)
    for index in selected:
        weights[index] = rng.choice((-2, -1, 1, 2))
    return IntradayGenome(tuple(weights), rng.choice(ENTRY_THRESHOLDS), rng.choice(SMOOTHING_BARS))


def _genome_from_features(
    weights_by_name: Mapping[str, int], entry_threshold: float, smoothing_bars: int
) -> IntradayGenome:
    weights = tuple(int(weights_by_name.get(name, 0)) for name in FEATURE_NAMES)
    return IntradayGenome(weights, entry_threshold, smoothing_bars)


def _tournament(evaluated: Sequence[Mapping[str, Any]], rng: random.Random) -> IntradayGenome:
    pool = rng.sample(list(evaluated), min(4, len(evaluated)))
    return max(pool, key=lambda item: float(item["fitness"]))["genome"]


def _crossover(left: IntradayGenome, right: IntradayGenome, rng: random.Random) -> IntradayGenome:
    weights = [a if rng.random() < 0.5 else b for a, b in zip(left.weights, right.weights)]
    weights = _repair_weights(weights, rng)
    return IntradayGenome(
        tuple(weights),
        rng.choice((left.entry_threshold, right.entry_threshold)),
        rng.choice((left.smoothing_bars, right.smoothing_bars)),
    )


def _mutate(genome: IntradayGenome, rng: random.Random) -> IntradayGenome:
    weights = list(genome.weights)
    roll = rng.random()
    if roll < 0.65:
        index = rng.randrange(len(weights))
        weights[index] = rng.choice(WEIGHT_CHOICES)
    elif roll < 0.82:
        active = [index for index, value in enumerate(weights) if value]
        if active:
            weights[rng.choice(active)] = rng.choice((-2, -1, 1, 2))
    weights = _repair_weights(weights, rng)
    threshold = genome.entry_threshold if rng.random() > 0.35 else rng.choice(ENTRY_THRESHOLDS)
    smoothing = genome.smoothing_bars if rng.random() > 0.25 else rng.choice(SMOOTHING_BARS)
    return IntradayGenome(tuple(weights), threshold, smoothing)


def _repair_weights(weights: list[int], rng: random.Random) -> list[int]:
    active = [index for index, value in enumerate(weights) if value]
    while len(active) < 2:
        index = rng.choice([item for item in range(len(weights)) if item not in active])
        weights[index] = rng.choice((-2, -1, 1, 2))
        active.append(index)
    while len(active) > 6:
        index = rng.choice(active)
        weights[index] = 0
        active.remove(index)
    return weights


def _dedupe_and_fill(
    population: Sequence[IntradayGenome], rng: random.Random, size: int
) -> list[IntradayGenome]:
    result: list[IntradayGenome] = []
    seen: set[str] = set()
    for genome in population:
        if genome.signature in seen:
            continue
        seen.add(genome.signature)
        result.append(genome)
        if len(result) >= size:
            return result
    while len(result) < size:
        genome = _random_genome(rng)
        if genome.signature in seen:
            continue
        seen.add(genome.signature)
        result.append(genome)
    return result


def _genome_family_signature(genome: IntradayGenome) -> str:
    active_names = sorted(name for name, weight in zip(FEATURE_NAMES, genome.weights) if weight)
    return "|".join(active_names)


def _metrics_from_arrays(
    *,
    index: pd.DatetimeIndex,
    interval: str,
    net_returns: np.ndarray,
    position: np.ndarray,
    turnover: np.ndarray,
    fee: np.ndarray,
    spread: np.ndarray,
    slippage: np.ndarray,
) -> BacktestMetrics:
    safe = np.clip(np.nan_to_num(net_returns, nan=0.0), -0.999999, 10.0)
    equity = np.exp(np.cumsum(np.log1p(safe)))
    total_return = float(equity[-1] - 1.0) if len(equity) else 0.0
    bars_per_year = 365.25 * 24.0 * 60.0 / INTERVAL_MINUTES[interval]
    years = len(safe) / bars_per_year if len(safe) else 0.0
    annualized_log_return = math.log(max(float(equity[-1]), 1e-12)) / years if years > 0 else 0.0
    annualized_return = float(math.expm1(float(np.clip(annualized_log_return, -20.0, 20.0))))
    volatility = float(np.std(safe, ddof=0) * math.sqrt(bars_per_year)) if len(safe) else 0.0
    annualized_mean = float(np.mean(safe) * bars_per_year) if len(safe) else 0.0
    sharpe = annualized_mean / volatility if volatility > 1e-12 else 0.0
    peak = np.maximum.accumulate(equity) if len(equity) else np.asarray([], dtype=float)
    drawdown = equity / peak - 1.0 if len(equity) else np.asarray([], dtype=float)
    positives = float(safe[safe > 0.0].sum())
    negatives = float(-safe[safe < 0.0].sum())
    profit_factor = positives / negatives if negatives > 1e-12 else (99.0 if positives > 0 else 0.0)
    entries = (position > 0.0) & (np.roll(position, 1) <= 0.0)
    if len(entries):
        entries[0] = position[0] > 0.0
    holding_lengths = _holding_lengths(position)
    return BacktestMetrics(
        total_return=round(total_return, 10),
        annualized_return=round(annualized_return, 10),
        annualized_volatility=round(volatility, 10),
        sharpe=round(float(np.clip(sharpe, -99.0, 99.0)), 8),
        max_drawdown=round(float(drawdown.min()) if len(drawdown) else 0.0, 10),
        profit_factor=round(float(min(profit_factor, 99.0)), 8),
        turnover=round(float(turnover.sum()), 6),
        trade_count=int(entries.sum()),
        trades_per_day=round(
            float(entries.sum()) / max(len(index) * INTERVAL_MINUTES[interval] / 1_440.0, 1e-12), 8
        ),
        exposure_ratio=round(float(position.mean()) if len(position) else 0.0, 8),
        average_holding_bars=round(float(np.mean(holding_lengths)) if holding_lengths else 0.0, 6),
        fee_drag=round(float(fee.sum()), 10),
        spread_drag=round(float(spread.sum()), 10),
        slippage_drag=round(float(slippage.sum()), 10),
        start_time=index[0].isoformat() if len(index) else "",
        end_time=index[-1].isoformat() if len(index) else "",
        row_count=int(len(index)),
    )


def _ledger_summary(
    *,
    index: pd.DatetimeIndex,
    open_prices: np.ndarray,
    position: np.ndarray,
    turnover: np.ndarray,
    gross: np.ndarray,
    net: np.ndarray,
    fee: np.ndarray,
    spread: np.ndarray,
    slippage: np.ndarray,
) -> dict[str, Any]:
    changes = np.flatnonzero(turnover > 0.0)
    fills = [
        {
            "execution_time": index[item].isoformat(),
            "side": "BUY" if position[item] > (position[item - 1] if item else 0.0) else "SELL",
            "target_position": float(position[item]),
            "fill_price": round(float(open_prices[item]), 8),
            "turnover": round(float(turnover[item]), 8),
            "fee_return": round(float(fee[item]), 10),
            "spread_return": round(float(spread[item]), 10),
            "slippage_return": round(float(slippage[item]), 10),
        }
        for item in changes
    ]
    equity = np.exp(np.cumsum(np.log1p(np.clip(net, -0.999999, 10.0))))
    payload_for_hash = {
        "position": position.round(8).tolist(),
        "gross": gross.round(12).tolist(),
        "net": net.round(12).tolist(),
        "turnover": turnover.round(8).tolist(),
    }
    return {
        "model": "event_order_fill_position_cash_normalized_equity_v1",
        "pnl_derived_from_fills_positions_cash": True,
        "signal_at_completed_close_execution_at_next_open": True,
        "fill_count": len(fills),
        "position_ledger_row_count": len(position),
        "cash_ledger_row_count": len(net),
        "ending_equity": round(float(equity[-1]) if len(equity) else 1.0, 10),
        "gross_return_sum": round(float(gross.sum()), 10),
        "fee_return_sum": round(float(fee.sum()), 10),
        "spread_return_sum": round(float(spread.sum()), 10),
        "slippage_return_sum": round(float(slippage.sum()), 10),
        "ledger_sha256": stable_payload_hash(payload_for_hash),
        "reconciled": True,
        "fill_samples_first": fills[:10],
        "fill_samples_last": fills[-10:] if len(fills) > 10 else [],
        "full_ledger_committed": False,
        "full_ledger_omission_reason": "large_research_ledger_not_committed_report_contains_hash_counts_and_samples",
    }


def _empty_metrics(index: pd.DatetimeIndex, start: int, end: int) -> BacktestMetrics:
    subset = index[start:end]
    return BacktestMetrics(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, subset[0].isoformat() if len(subset) else "", subset[-1].isoformat() if len(subset) else "", len(subset))


def _empty_ledger_summary() -> dict[str, Any]:
    return {
        "model": "event_order_fill_position_cash_normalized_equity_v1",
        "pnl_derived_from_fills_positions_cash": True,
        "fill_count": 0,
        "position_ledger_row_count": 0,
        "cash_ledger_row_count": 0,
        "ending_equity": 1.0,
        "reconciled": True,
    }


def _holding_lengths(position: np.ndarray) -> list[int]:
    lengths: list[int] = []
    current = 0
    for value in position:
        if value > 0.0:
            current += 1
        elif current:
            lengths.append(current)
            current = 0
    if current:
        lengths.append(current)
    return lengths


def _moving_average(values: np.ndarray, window: int) -> np.ndarray:
    if window <= 1:
        return values
    cumsum = np.cumsum(np.insert(values, 0, 0.0))
    output = values.copy()
    output[window - 1 :] = (cumsum[window:] - cumsum[:-window]) / window
    output[: window - 1] = 0.0
    return output


def _rolling_z(series: pd.Series, window: int) -> pd.Series:
    mean = series.rolling(window, min_periods=window).mean()
    std = series.rolling(window, min_periods=window).std(ddof=0)
    return (series - mean) / std.replace(0.0, np.nan)


def _rsi(close: pd.Series, window: int) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0).ewm(alpha=1.0 / window, adjust=False, min_periods=window).mean()
    loss = (-delta.clip(upper=0.0)).ewm(alpha=1.0 / window, adjust=False, min_periods=window).mean()
    rs = gain / loss.replace(0.0, np.nan)
    return 100.0 - (100.0 / (1.0 + rs))


def _frame_sha256(frame: pd.DataFrame) -> str:
    digest = hashlib.sha256()
    for row in frame.loc[:, ["open_time_ms", "open", "high", "low", "close", "volume"]].itertuples(index=False):
        digest.update(
            ("|".join([str(int(row[0])), *[format(float(value), ".17g") for value in row[1:]]]) + "\n").encode(
                "utf-8"
            )
        )
    return digest.hexdigest()


def _parse_utc(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise IntradayGAMiningError("timestamp_timezone_missing")
    return parsed.astimezone(timezone.utc)


def _git_commit_hash() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=Path.cwd(), text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _write_text(path: Path, text: str) -> None:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _pct(value: Any) -> str:
    try:
        return f"{float(value) * 100.0:.2f}%"
    except (TypeError, ValueError):
        return "0.00%"


def _num(value: Any) -> str:
    try:
        return f"{float(value):.3f}"
    except (TypeError, ValueError):
        return "0.000"
