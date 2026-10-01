from __future__ import annotations

import hashlib
import json
import math
import random
import subprocess
from dataclasses import asdict, dataclass, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence, TypeAlias

import numpy as np
import pandas as pd

from quant_crypto.research.high_yield_5m_ga_mining import COST_SCENARIOS
from quant_crypto.research.intraday_ga_strategy_mining import FoldSpec
from quant_crypto.research.regime_conditional_5m_alpha_search import (
    FixedRiskConstitution,
    FixedSizingPolicy,
    apply_cost_aware_sizing,
    build_position_path_from_events,
    simulate_regime_conditional_next_open,
)
from tools.agent_governance.shared_data import (
    default_shared_data_root,
    resolve_manifest_file,
    validate_manifest,
)


SCHEMA_VERSION = "btc_multiscale_trend_15m_1h_search_v1"
AGGREGATION_VERSION = "utc_epoch_complete_5m_groups_available_time_v1"
DEFAULT_EXPERIMENT_ID = "btc-15m-1h-trend-family-search-01"
DEFAULT_SEED = 20260827
TIMEFRAMES_MINUTES = (15, 30, 60)
FAMILIES = (
    "dynamic_momentum_cycle_continuation",
    "volatility_conditioned_channel_breakout",
    "htf_pullback_reacceleration",
)
SELECTION_MANIFEST_RELATIVE_PATH = (
    ".agent/data_manifests/btc-5m-qcv2r1-selection-prefix/"
    "btc-5m-qcv2r1-selection-prefix-248270-qc2r1.json"
)
EXPECTED_MANIFEST_GIT_BLOB_SHA = "7e083664a9bf0509695a3eb62c78c0d15d9dd752"
EXPECTED_DATASET_ID = "btc-5m-qcv2r1-selection-prefix"
EXPECTED_DATASET_VERSION = (
    "btc-5m-qcv2r1-selection-prefix-248270-parent76e8654c-mainbcc31f0b-corr01"
)
EXPECTED_PAYLOAD_RELATIVE_PATH = (
    "exchange=binance_spot/symbol=BTCUSDT/interval=5m/part-00000.jsonl"
)
EXPECTED_PAYLOAD_SHA256 = "b00557b75b3b4049bde1c09bfa69d31a8856993bb9f4fbdc71cfb49078b8f9b5"
EXPECTED_SELECTION_ROWS = 248_270
EXPECTED_SELECTION_START = "2024-01-01T00:00:00+00:00"
EXPECTED_SELECTION_END = "2026-05-12T01:05:00+00:00"
EXPECTED_DERIVED_ROWS = {15: 82_756, 30: 41_378, 60: 20_689}
EXPECTED_DERIVED_LAST_AVAILABLE = "2026-05-12T00:59:59.999000+00:00"
PRIOR_UNIQUE_EVALUATIONS = 1_840
MAX_NEW_UNIQUE_EVALUATIONS = 450
LEGACY_HOLDOUT_STATUS = "legacy_qcv2r1_holdout_retired_without_metric_reveal"


class SearchContractError(ValueError):
    pass


class SelectionPrefixBindingError(SearchContractError):
    pass


class AggregationError(SearchContractError):
    pass


MOMENTUM_OPTIONS: dict[str, tuple[Any, ...]] = {
    "momentum_window_bars": (6, 12, 24, 48),
    "turning_lookback_bars": (2, 3, 6, 12),
    "exit_window_bars": (3, 6, 12, 24),
    "atr_window_bars": (12, 14, 24, 48),
    "max_holding_bars": (12, 24, 48, 96),
    "cooldown_bars": (3, 6, 12),
}
CHANNEL_OPTIONS: dict[str, tuple[Any, ...]] = {
    "channel_bars": (12, 24, 48, 96),
    "atr_window_bars": (12, 14, 24, 48),
    "entry_buffer_atr": (0.0, 0.1, 0.25, 0.5),
    "exit_window_bars": (6, 12, 24, 48),
    "max_holding_bars": (12, 24, 48, 96),
    "cooldown_bars": (3, 6, 12),
}
PULLBACK_OPTIONS: dict[str, tuple[Any, ...]] = {
    "ema_pair": ((6, 24), (12, 48), (24, 96)),
    "pullback_tolerance_atr": (0.25, 0.5, 0.75, 1.0),
    "reacceleration_window_bars": (3, 6, 12, 24),
    "exit_window_bars": (6, 12, 24, 48),
    "max_holding_bars": (12, 24, 48, 96),
    "cooldown_bars": (3, 6, 12),
}


class _GenomeMixin:
    @property
    def family(self) -> str:
        raise NotImplementedError

    @property
    def active_genes(self) -> dict[str, Any]:
        return asdict(self)  # type: ignore[arg-type]

    @property
    def genome_hash(self) -> str:
        return hashlib.sha256(
            _stable_json({"family": self.family, "active_genes": self.active_genes}).encode("utf-8")
        ).hexdigest()

    @property
    def maximum_lookback_bars(self) -> int:
        raise NotImplementedError

    def to_dict(self) -> dict[str, Any]:
        return {
            "family": self.family,
            "active_genes": self.active_genes,
            "genome_hash": self.genome_hash,
            "family_inactive_genes_hashed": False,
        }


@dataclass(frozen=True)
class DynamicMomentumCycleGenome(_GenomeMixin):
    momentum_window_bars: int
    turning_lookback_bars: int
    exit_window_bars: int
    atr_window_bars: int
    max_holding_bars: int
    cooldown_bars: int

    def __post_init__(self) -> None:
        _validate_fields(self, MOMENTUM_OPTIONS)

    @property
    def family(self) -> str:
        return FAMILIES[0]

    @property
    def maximum_lookback_bars(self) -> int:
        return max(self.momentum_window_bars, self.turning_lookback_bars, self.exit_window_bars, self.atr_window_bars)


@dataclass(frozen=True)
class VolatilityChannelGenome(_GenomeMixin):
    channel_bars: int
    atr_window_bars: int
    entry_buffer_atr: float
    exit_window_bars: int
    max_holding_bars: int
    cooldown_bars: int

    def __post_init__(self) -> None:
        _validate_fields(self, CHANNEL_OPTIONS)

    @property
    def family(self) -> str:
        return FAMILIES[1]

    @property
    def maximum_lookback_bars(self) -> int:
        return max(self.channel_bars, self.atr_window_bars * 4, self.exit_window_bars)


@dataclass(frozen=True)
class PullbackReaccelerationGenome(_GenomeMixin):
    ema_fast_bars: int
    ema_slow_bars: int
    pullback_tolerance_atr: float
    reacceleration_window_bars: int
    exit_window_bars: int
    max_holding_bars: int
    cooldown_bars: int

    def __post_init__(self) -> None:
        values = asdict(self)
        pair = (values.pop("ema_fast_bars"), values.pop("ema_slow_bars"))
        invalid = [name for name, value in values.items() if value not in PULLBACK_OPTIONS[name]]
        if pair not in PULLBACK_OPTIONS["ema_pair"]:
            invalid.append("ema_pair")
        if invalid:
            raise SearchContractError("pullback_genome_invalid:" + ",".join(invalid))

    @property
    def family(self) -> str:
        return FAMILIES[2]

    @property
    def atr_window_bars(self) -> int:
        return 24

    @property
    def maximum_lookback_bars(self) -> int:
        return max(self.ema_slow_bars, self.reacceleration_window_bars, self.exit_window_bars, self.atr_window_bars)


TrendGenome: TypeAlias = DynamicMomentumCycleGenome | VolatilityChannelGenome | PullbackReaccelerationGenome


def load_committed_selection_prefix(repo_root: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    root = repo_root.resolve()
    manifest_path = root / SELECTION_MANIFEST_RELATIVE_PATH
    if not manifest_path.is_file():
        raise SelectionPrefixBindingError("fixed_manifest_path_required")
    blob = _git_text(root, ["rev-parse", f"HEAD:{SELECTION_MANIFEST_RELATIVE_PATH}"])
    if blob != EXPECTED_MANIFEST_GIT_BLOB_SHA:
        raise SelectionPrefixBindingError("current_head_manifest_blob_mismatch")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (
        manifest.get("dataset_id") != EXPECTED_DATASET_ID
        or manifest.get("dataset_version") != EXPECTED_DATASET_VERSION
        or validate_manifest(manifest)
    ):
        raise SelectionPrefixBindingError("selection_prefix_manifest_contract_invalid")
    files = manifest.get("files")
    if not isinstance(files, list):
        raise SelectionPrefixBindingError("selection_prefix_files_invalid")
    entry = next((row for row in files if isinstance(row, Mapping) and row.get("path") == EXPECTED_PAYLOAD_RELATIVE_PATH), None)
    if not isinstance(entry, Mapping) or entry.get("sha256") != EXPECTED_PAYLOAD_SHA256:
        raise SelectionPrefixBindingError("selection_prefix_payload_binding_invalid")
    shared_root = resolve_manifest_file(
        manifest_path,
        shared_root=default_shared_data_root(root),
        verify_files=True,
    )
    payload_path = shared_root / EXPECTED_PAYLOAD_RELATIVE_PATH
    if _sha256_file(payload_path) != EXPECTED_PAYLOAD_SHA256:
        raise SelectionPrefixBindingError("selection_prefix_payload_sha256_mismatch")
    frame = _open_prefix_payload(payload_path)
    _require_source_frame(frame)
    if (
        len(frame) != EXPECTED_SELECTION_ROWS
        or frame.index[0].isoformat() != EXPECTED_SELECTION_START
        or frame.index[-1].isoformat() != EXPECTED_SELECTION_END
    ):
        raise SelectionPrefixBindingError("selection_prefix_decoded_boundary_invalid")
    return frame, {
        "dataset_id": EXPECTED_DATASET_ID,
        "dataset_version": EXPECTED_DATASET_VERSION,
        "manifest_relative_path": SELECTION_MANIFEST_RELATIVE_PATH,
        "manifest_git_blob_sha": blob,
        "manifest_file_sha256": _sha256_file(manifest_path),
        "payload_relative_path": EXPECTED_PAYLOAD_RELATIVE_PATH,
        "payload_sha256": EXPECTED_PAYLOAD_SHA256,
        "selection_rows_decoded": len(frame),
        "selection_boundary": {"start": EXPECTED_SELECTION_START, "end": EXPECTED_SELECTION_END},
        "unseen_bytes_read": 0,
        "unseen_rows_decoded": 0,
        "unseen_strategy_metrics_read": False,
        "legacy_holdout_status": LEGACY_HOLDOUT_STATUS,
    }


def _open_prefix_payload(path: Path) -> pd.DataFrame:
    raw = pd.read_json(path, lines=True)
    required = {"event_time", "available_time", "is_finalized", "open", "high", "low", "close", "volume"}
    if not required.issubset(raw.columns):
        raise SelectionPrefixBindingError("selection_prefix_fields_missing")
    if not raw["is_finalized"].astype(bool).all():
        raise SelectionPrefixBindingError("selection_prefix_contains_unfinalized_bar")
    event_time = pd.to_datetime(raw.pop("event_time"), utc=True)
    raw["available_time"] = pd.to_datetime(raw["available_time"], utc=True)
    raw.index = pd.DatetimeIndex(event_time.dt.floor("5min"), name="open_time")
    return raw


def aggregate_completed_bars(source: pd.DataFrame, *, minutes: int) -> tuple[pd.DataFrame, dict[str, Any]]:
    _require_source_frame(source)
    if minutes not in TIMEFRAMES_MINUTES:
        raise AggregationError("target_timeframe_not_allowed")
    expected_delta = pd.Timedelta(minutes=5)
    if len(source) > 1 and not (source.index.to_series().diff().iloc[1:] == expected_delta).all():
        raise AggregationError("source_5m_sequence_not_contiguous")
    group_size = minutes // 5
    bucket = source.index.floor(f"{minutes}min")
    grouped = source.groupby(bucket, sort=True)
    frame = grouped.agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
        available_time=("available_time", "last"),
        source_bar_count=("close", "size"),
    )
    frame = frame.loc[frame["source_bar_count"] == group_size].copy()
    frame.index = pd.DatetimeIndex(frame.index, name="open_time")
    _require_ohlcv(frame)
    if not (frame["source_bar_count"] == group_size).all():
        raise AggregationError("incomplete_target_bucket_retained")
    frame_hash = _derived_frame_hash(frame)
    provenance = {
        "aggregation_version": AGGREGATION_VERSION,
        "timeframe_minutes": minutes,
        "source_bars_per_target_bar": group_size,
        "complete_unique_consecutive_source_bars_required": True,
        "target_bucket_rule": "UTC epoch aligned left_closed_right_open",
        "decision_visibility_rule": "completed target close; available_time equals last source available_time",
        "execution_rule": "next target bar open which is next source 5m open",
        "derived_rows": len(frame),
        "boundary": {
            "first_open_time": frame.index[0].isoformat(),
            "last_open_time": frame.index[-1].isoformat(),
            "last_available_time": pd.Timestamp(frame["available_time"].iloc[-1]).isoformat(),
        },
        "derived_frame_sha256": frame_hash,
    }
    return frame, provenance


def build_family_events(frame: pd.DataFrame, genome: TrendGenome) -> pd.DataFrame:
    _require_ohlcv(frame)
    close = frame["close"].astype(float)
    high = frame["high"].astype(float)
    low = frame["low"].astype(float)
    atr = _atr(frame, genome.atr_window_bars)
    exit_high = high.shift(1).rolling(genome.exit_window_bars, min_periods=genome.exit_window_bars).max()
    exit_low = low.shift(1).rolling(genome.exit_window_bars, min_periods=genome.exit_window_bars).min()
    if isinstance(genome, DynamicMomentumCycleGenome):
        momentum = close / close.shift(genome.momentum_window_bars) - 1.0
        turn_high = high.shift(1).rolling(genome.turning_lookback_bars, min_periods=genome.turning_lookback_bars).max()
        turn_low = low.shift(1).rolling(genome.turning_lookback_bars, min_periods=genome.turning_lookback_bars).min()
        scale = atr / close.replace(0.0, np.nan)
        bull = momentum > scale
        bear = momentum < -scale
        long_entry = bull & (close > turn_high)
        short_entry = bear & (close < turn_low)
        long_exit = (momentum <= 0.0) | (close < exit_low)
        short_exit = (momentum >= 0.0) | (close > exit_high)
        confidence = (momentum.abs() / scale.replace(0.0, np.nan)).clip(0.0, 1.0)
        ready = momentum.notna() & atr.notna() & turn_high.notna() & turn_low.notna()
    elif isinstance(genome, VolatilityChannelGenome):
        upper = high.shift(1).rolling(genome.channel_bars, min_periods=genome.channel_bars).max()
        lower = low.shift(1).rolling(genome.channel_bars, min_periods=genome.channel_bars).min()
        normalized_atr = atr / close.replace(0.0, np.nan)
        volatility_floor = normalized_atr.shift(1).rolling(genome.atr_window_bars * 4, min_periods=genome.atr_window_bars * 2).median()
        eligible = normalized_atr >= volatility_floor
        long_entry = eligible & (close > upper + genome.entry_buffer_atr * atr)
        short_entry = eligible & (close < lower - genome.entry_buffer_atr * atr)
        long_exit = (~eligible) | (close < exit_low)
        short_exit = (~eligible) | (close > exit_high)
        confidence = (normalized_atr / volatility_floor.replace(0.0, np.nan) - 1.0).clip(0.0, 1.0)
        ready = atr.notna() & upper.notna() & lower.notna() & volatility_floor.notna()
        bull = eligible
        bear = eligible
    elif isinstance(genome, PullbackReaccelerationGenome):
        fast = close.ewm(span=genome.ema_fast_bars, adjust=False, min_periods=genome.ema_fast_bars).mean()
        slow = close.ewm(span=genome.ema_slow_bars, adjust=False, min_periods=genome.ema_slow_bars).mean()
        prior_high = high.shift(1).rolling(genome.reacceleration_window_bars, min_periods=genome.reacceleration_window_bars).max()
        prior_low = low.shift(1).rolling(genome.reacceleration_window_bars, min_periods=genome.reacceleration_window_bars).min()
        bull = (fast > slow) & (slow > slow.shift(genome.reacceleration_window_bars))
        bear = (fast < slow) & (slow < slow.shift(genome.reacceleration_window_bars))
        touched_long = (low <= fast + genome.pullback_tolerance_atr * atr).shift(1).rolling(genome.reacceleration_window_bars, min_periods=1).max().fillna(0).astype(bool)
        touched_short = (high >= fast - genome.pullback_tolerance_atr * atr).shift(1).rolling(genome.reacceleration_window_bars, min_periods=1).max().fillna(0).astype(bool)
        long_entry = bull & touched_long & (close > prior_high)
        short_entry = bear & touched_short & (close < prior_low)
        long_exit = (~bull) | (close < slow) | (close < exit_low)
        short_exit = (~bear) | (close > slow) | (close > exit_high)
        confidence = ((fast - slow).abs() / atr.replace(0.0, np.nan)).clip(0.0, 1.0)
        ready = atr.notna() & slow.notna() & prior_high.notna() & prior_low.notna()
    else:
        raise SearchContractError("genome_type_invalid")
    eligible = (bull | bear) & ready
    return pd.DataFrame(
        {
            "regime_eligible": eligible.fillna(False).astype(bool),
            "long_entry": (long_entry & ready).fillna(False).astype(bool),
            "short_entry": (short_entry & ready).fillna(False).astype(bool),
            "long_invalidation": long_exit.fillna(True).astype(bool),
            "short_invalidation": short_exit.fillna(True).astype(bool),
            "confidence": confidence.fillna(0.0).astype(float),
            "hypothesis_family": genome.family,
        },
        index=frame.index,
    )


def crossover_within_stratum(left: TrendGenome, right: TrendGenome, rng: random.Random) -> TrendGenome:
    if type(left) is not type(right):
        raise SearchContractError("cross_family_crossover_forbidden")
    left_values, right_values = asdict(left), asdict(right)
    values: dict[str, Any] = {}
    if isinstance(left, PullbackReaccelerationGenome):
        source = left_values if rng.random() < 0.5 else right_values
        values["ema_fast_bars"], values["ema_slow_bars"] = source["ema_fast_bars"], source["ema_slow_bars"]
    for name in left_values:
        if name not in values:
            values[name] = left_values[name] if rng.random() < 0.5 else right_values[name]
    return type(left)(**values)


def mutate_within_stratum(genome: TrendGenome, rng: random.Random) -> TrendGenome:
    values = asdict(genome)
    options = _options_for_genome(genome)
    selectable = list(options)
    for name in rng.sample(selectable, k=rng.choice((1, 1, 2))):
        replacement = rng.choice(options[name])
        if name == "ema_pair":
            values["ema_fast_bars"], values["ema_slow_bars"] = replacement
        else:
            values[name] = replacement
    return type(genome)(**values)


def embargo_target_bars(minutes: int) -> int:
    if minutes not in TIMEFRAMES_MINUTES:
        raise SearchContractError("target_timeframe_not_allowed")
    return (5_760 * 5) // minutes


def build_purged_selection_folds(row_count: int, *, minutes: int, fold_count: int) -> list[FoldSpec]:
    embargo = embargo_target_bars(minutes)
    initial_train = int(row_count * 0.40)
    available = row_count - initial_train - fold_count * embargo
    validation_rows = available // fold_count
    if initial_train < 500 or validation_rows < 50:
        return []
    folds: list[FoldSpec] = []
    cursor = initial_train
    for fold_id in range(1, fold_count + 1):
        start = cursor + embargo
        end = row_count if fold_id == fold_count else start + validation_rows
        if end - start < 50:
            return []
        folds.append(FoldSpec(fold_id, 0, cursor, start, end, embargo))
        cursor = end
    return folds


def candidate_sort_key(row: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        0 if bool(row.get("feasible")) else 1,
        int(row.get("pareto_rank", 999)),
        -int(row.get("passed_fold_count", 0)),
        -float(row.get("objectives", {}).get("worst_conservative_return", -999.0)),
        str(row.get("genome_hash", "")),
    )


def run_multiscale_search_on_frames(
    *,
    frames: Mapping[int, pd.DataFrame],
    data_provenance: Mapping[str, Any],
    output_root: Path | None,
    seed: int = DEFAULT_SEED,
    population_per_stratum: int = 12,
    generations: int = 4,
    fold_count: int = 4,
    prior_unique_evaluations: int = PRIOR_UNIQUE_EVALUATIONS,
    max_new_unique_evaluations: int = MAX_NEW_UNIQUE_EVALUATIONS,
    generated_at_utc: datetime | None = None,
) -> dict[str, Any]:
    if set(frames) != set(TIMEFRAMES_MINUTES):
        raise SearchContractError("all_fixed_timeframe_strata_required")
    if population_per_stratum < 4 or generations < 1 or fold_count < 2:
        raise SearchContractError("search_configuration_too_small")
    planned_slots = len(TIMEFRAMES_MINUTES) * len(FAMILIES) * population_per_stratum * generations
    if planned_slots > 432 or prior_unique_evaluations != PRIOR_UNIQUE_EVALUATIONS or max_new_unique_evaluations > MAX_NEW_UNIQUE_EVALUATIONS:
        raise SearchContractError("trial_budget_or_prior_count_invalid")
    for frame in frames.values():
        _require_ohlcv(frame)
    rng = random.Random(seed)
    sizing, risk = FixedSizingPolicy(), FixedRiskConstitution()
    caches: dict[tuple[int, str], dict[str, dict[str, Any]]] = {}
    populations: dict[tuple[int, str], list[TrendGenome]] = {}
    folds_by_timeframe: dict[int, list[FoldSpec]] = {}
    for minutes in TIMEFRAMES_MINUTES:
        folds = build_purged_selection_folds(len(frames[minutes]), minutes=minutes, fold_count=fold_count)
        if len(folds) != fold_count:
            raise SearchContractError(f"selection_fold_construction_failed_{minutes}m")
        folds_by_timeframe[minutes] = folds
        for family in FAMILIES:
            key = (minutes, family)
            caches[key] = {}
            populations[key] = _initial_population(family, population_per_stratum, rng)
    trace: list[dict[str, Any]] = []
    for generation in range(1, generations + 1):
        evaluated: dict[tuple[int, str], list[dict[str, Any]]] = {}
        for key, population in populations.items():
            minutes, _ = key
            evaluated[key] = [
                _evaluate_candidate(frames[minutes], minutes, genome, folds_by_timeframe[minutes], caches[key], sizing, risk)
                for genome in population
            ]
            _assign_pareto(evaluated[key], prior_unique_evaluations + sum(len(cache) for cache in caches.values()))
        trace.append({
            "generation": generation,
            "unique_evaluations": sum(len(cache) for cache in caches.values()),
            "stratum_best": {f"{m}m::{f}": sorted(rows, key=candidate_sort_key)[0]["candidate_id"] for (m, f), rows in evaluated.items()},
        })
        next_populations: dict[tuple[int, str], list[TrendGenome]] = {}
        for key, rows in evaluated.items():
            rows.sort(key=candidate_sort_key)
            next_population = [row["genome"] for row in rows[: max(1, population_per_stratum // 6)]]
            while len(next_population) < population_per_stratum:
                left = _tournament(rows, rng)
                right = _tournament(rows, rng)
                next_population.append(mutate_within_stratum(crossover_within_stratum(left, right, rng), rng))
            next_populations[key] = _dedupe_fill(next_population, key[1], population_per_stratum, rng)
        populations = next_populations
    selection_rows = [row for cache in caches.values() for row in cache.values()]
    cumulative_before_neighborhood = prior_unique_evaluations + len(selection_rows)
    _assign_pareto(selection_rows, cumulative_before_neighborhood)
    selection_rows.sort(key=candidate_sort_key)
    champion = selection_rows[0]
    selected_candidate_id = str(champion["candidate_id"])
    remaining = max_new_unique_evaluations - len(selection_rows)
    neighbor_rows: list[dict[str, Any]] = []
    if remaining > 0:
        key = (int(champion["timeframe_minutes"]), str(champion["family"]))
        for genome in _neighbors(champion["genome"], limit=remaining):
            before = len(caches[key])
            row = _evaluate_candidate(frames[key[0]], key[0], genome, folds_by_timeframe[key[0]], caches[key], sizing, risk)
            if len(caches[key]) > before:
                row["neighborhood_only"] = True
                row["eligible_for_selection"] = False
                neighbor_rows.append(row)
        _set_neighborhood(champion, neighbor_rows)
    else:
        _set_neighborhood(champion, [])
    run_unique_evaluations = sum(len(cache) for cache in caches.values())
    cumulative = prior_unique_evaluations + run_unique_evaluations
    for row in selection_rows:
        _refresh_candidate(row, cumulative)
    champion = next(row for row in selection_rows if row["candidate_id"] == selected_candidate_id)
    selection_reasons = _selection_gate_reasons(champion, fold_count)
    lock_status = "locked_selection_candidate_awaiting_new_future_unseen" if not selection_reasons else "reject_selection_batch"
    controls = [_evaluate_negative_control(frames[m], m, folds_by_timeframe[m], sizing, risk) for m in TIMEFRAMES_MINUTES]
    stratum_summaries = []
    for minutes in TIMEFRAMES_MINUTES:
        for family in FAMILIES:
            all_stratum_rows = list(caches[(minutes, family)].values())
            rows = [row for row in all_stratum_rows if not bool(row.get("neighborhood_only"))]
            rows.sort(key=candidate_sort_key)
            best = rows[0]
            conservative = [fold["cost_scenarios"]["conservative"] for fold in best["selection_folds"]]
            stratum_summaries.append({
                "timeframe_minutes": minutes,
                "family": family,
                "unique_trials": len(all_stratum_rows),
                "selection_pool_trials": len(rows),
                "neighborhood_only_trials": len(all_stratum_rows) - len(rows),
                "feasible_candidates": sum(int(row["feasible"]) for row in rows),
                "best_candidate_id": best["candidate_id"],
                "entries": sum(int(fold["target_diagnostics"]["entry_count"]) for fold in best["selection_folds"]),
                "independent_bets": sum(int(row["independent_bet_count"]) for row in conservative),
                "after_cost_return_sum": _round(sum(float(row["total_return"]) for row in conservative)),
                "median_profit_factor": _round(float(np.median([float(row["profit_factor"]) for row in conservative]))),
                "worst_drawdown": _round(min(float(row["max_drawdown"]) for row in conservative)),
                "cost_drag": _round(sum(float(row["cost_drag"]) for row in conservative)),
                "turnover": _round(sum(float(row["turnover"]) for row in conservative)),
                "applicable_folds": best["applicable_fold_count"],
                "worst_fold_return": best["objectives"]["worst_conservative_return"],
                "parameter_neighborhood_stability": best["parameter_neighborhood_stability"],
                "blockers": best["constraint_reasons"] + _selection_gate_reasons(best, fold_count),
            })
    generated = generated_at_utc or datetime.now(timezone.utc)
    public_champion = _public_candidate(champion)
    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "experiment_id": DEFAULT_EXPERIMENT_ID,
        "generated_at_utc": generated.astimezone(timezone.utc).isoformat(),
        "code_commit": _git_commit_hash(),
        "status": "complete_research_only",
        "decision": lock_status,
        "research_question": "Which preregistered trend hypothesis and completed 15m/30m/1h decision stratum has robust after-cost conditional evidence on the immutable selection prefix?",
        "data_provenance": dict(data_provenance),
        "validation_design": {
            "classification": "purged_chronological_selection_folds_not_oos_or_confirmatory",
            "fold_count": fold_count,
            "embargo_source_5m_bars": 5_760,
            "fold_start_flat": True,
            "entries_before_validation_counted": False,
            "holdout_bytes_read": 0,
            "holdout_rows_decoded": 0,
            "old_holdout_metrics_read": False,
            "old_holdout_status": LEGACY_HOLDOUT_STATUS,
            "new_future_unseen_required": True,
        },
        "search_protocol": {
            "algorithm": "deterministic_discrete_stratified_genetic_algorithm_constraint_domination_then_pareto",
            "seed": seed,
            "timeframes_minutes": list(TIMEFRAMES_MINUTES),
            "families": list(FAMILIES),
            "timeframe_is_genome_gene": False,
            "population_per_stratum": population_per_stratum,
            "generations": generations,
            "planned_slots": planned_slots,
            "prior_unique_evaluations": prior_unique_evaluations,
            "run_unique_evaluations": run_unique_evaluations,
            "cumulative_unique_evaluations": cumulative,
            "maximum_new_unique_evaluations": max_new_unique_evaluations,
            "trace": trace,
        },
        "cost_scenarios_bps": {scenario.name: scenario.total_bps for scenario in COST_SCENARIOS},
        "risk_and_sizing": {
            "fixed_1x": True,
            "sizing_policy": asdict(sizing),
            "risk_constitution": asdict(risk),
            "risk_and_safety_are_genome_fields": False,
            "completed_bar_hard_stop_is_proxy_only": True,
        },
        "stratum_summaries": stratum_summaries,
        "top_candidates": [_public_candidate(row) for row in selection_rows[:12]],
        "negative_controls": controls,
        "candidate_lock": {
            "status": lock_status,
            "maximum_locked_candidates": 1,
            "evaluated_candidate_id": selected_candidate_id,
            "locked_candidate": None if selection_reasons else public_champion,
            "selection_gate_reasons": selection_reasons,
            "old_holdout_reveal_authorized": False,
            "new_future_unseen_required": True,
        },
        "unproven_execution_evidence": [
            "venue_hosted_protective_orders",
            "mark_index_funding_and_liquidation",
            "l2_queue_partial_fill_market_impact",
            "runtime_fill_position_cash_ledger",
            "current_head_promotion_artifact",
        ],
        "safety": {name: False for name in ("promotion", "paper", "live", "private", "order", "real_order", "transfer", "withdraw")},
        "blockers": selection_reasons + [
            "research_only_no_clean_holdout_after_legacy_tail_retirement",
            "fixed_bps_cost_model_does_not_prove_execution_microstructure_or_perp_costs",
            "runtime_and_promotion_evidence_outside_ticket_scope",
        ],
    }
    report["semantic_hash"] = hashlib.sha256(_stable_json(report).encode("utf-8")).hexdigest()
    if output_root is not None:
        try:
            output_root.mkdir(parents=True, exist_ok=False)
        except FileExistsError as exc:
            raise SearchContractError("output_root_must_be_new") from exc
        report_path = output_root / "btc_multiscale_trend_search_report.json"
        lock_path = output_root / "btc_multiscale_trend_candidate_lock.json"
        _write_json(report_path, report)
        _write_json(lock_path, report["candidate_lock"])
        files = {path.name: _sha256_file(path) for path in (report_path, lock_path)}
        manifest = {
            "schema_version": "btc_multiscale_trend_search_artifact_manifest_v1",
            "experiment_id": DEFAULT_EXPERIMENT_ID,
            "semantic_hash": report["semantic_hash"],
            "files": files,
            "immutable_versioned_output": True,
            "latest_pointer_written": False,
        }
        _write_json(output_root / "artifact_manifest.json", manifest)
    return report


def run_btc_multiscale_trend_search(*, repo_root: Path, output_root: Path, **kwargs: Any) -> dict[str, Any]:
    source, provenance = load_committed_selection_prefix(repo_root)
    frames: dict[int, pd.DataFrame] = {}
    derived: dict[str, Any] = {}
    for minutes in TIMEFRAMES_MINUTES:
        frame, aggregation = aggregate_completed_bars(source, minutes=minutes)
        if (
            len(frame) != EXPECTED_DERIVED_ROWS[minutes]
            or aggregation["boundary"]["last_available_time"] != EXPECTED_DERIVED_LAST_AVAILABLE
        ):
            raise AggregationError(f"official_derived_boundary_invalid_{minutes}m")
        frames[minutes] = frame
        derived[f"{minutes}m"] = aggregation
    provenance = {**provenance, "derived_frames": derived}
    return run_multiscale_search_on_frames(frames=frames, data_provenance=provenance, output_root=output_root, **kwargs)


def _evaluate_candidate(
    frame: pd.DataFrame,
    minutes: int,
    genome: TrendGenome,
    folds: Sequence[FoldSpec],
    cache: dict[str, dict[str, Any]],
    sizing: FixedSizingPolicy,
    risk: FixedRiskConstitution,
) -> dict[str, Any]:
    key = hashlib.sha256(f"{minutes}:{genome.genome_hash}".encode("utf-8")).hexdigest()
    if key in cache:
        return cache[key]
    fold_rows = []
    for fold in folds:
        context_start = max(0, fold.validation_start - genome.maximum_lookback_bars)
        context = frame.iloc[context_start:fold.validation_end]
        validation = frame.iloc[fold.validation_start:fold.validation_end]
        events = build_family_events(context, genome).loc[validation.index]
        direction, diagnostics = build_position_path_from_events(validation, events, genome, risk)  # type: ignore[arg-type]
        target, sizing_diagnostics = apply_cost_aware_sizing(direction, sizing)
        costs: dict[str, Any] = {}
        ledgers: dict[str, Any] = {}
        for scenario in COST_SCENARIOS:
            metrics, ledger = simulate_regime_conditional_next_open(
                validation,
                target,
                cost_bps=scenario.total_bps,
                risk_constitution=risk,
                regime_eligible_at_close=events["regime_eligible"],
            )
            metrics = _correct_timeframe_annualization(metrics, minutes)
            costs[scenario.name] = metrics
            ledgers[scenario.name] = ledger
        reasons, applicable = _fold_gate_reasons(costs, minutes)
        fold_rows.append({
            "fold_id": fold.fold_id,
            "validation_start": validation.index[0].isoformat(),
            "validation_end": validation.index[-1].isoformat(),
            "embargo_target_bars": fold.embargo_bars,
            "embargo_source_5m_bars": 5_760,
            "flat_at_fold_start": True,
            "entries_counted_before_validation": 0,
            "applicable": applicable,
            "passed": applicable and not reasons,
            "reasons": reasons,
            "cost_scenarios": costs,
            "ledger_evidence": ledgers,
            "target_diagnostics": {**diagnostics, **sizing_diagnostics},
        })
    row: dict[str, Any] = {
        "genome": genome,
        "genome_hash": key,
        "candidate_id": f"btc_{minutes}m_{genome.family}_{key[:12]}",
        "timeframe_minutes": minutes,
        "family": genome.family,
        "selection_folds": fold_rows,
        "parameter_neighborhood_stability": {"status": "not_evaluated", "passed": False, "neighbor_count": 0},
    }
    cache[key] = row
    _refresh_candidate(row, PRIOR_UNIQUE_EVALUATIONS + len(cache))
    return row


def _fold_gate_reasons(costs: Mapping[str, Mapping[str, Any]], minutes: int) -> tuple[list[str], bool]:
    base, conservative, stress = (costs[name] for name in ("base", "conservative", "stress"))
    min_regime = {15: 96, 30: 48, 60: 24}[minutes]
    applicable = int(base["regime_eligible_rows"]) >= min_regime and int(base["independent_bet_count"]) >= 6
    reasons: list[str] = []
    if int(base["regime_eligible_rows"]) < min_regime:
        reasons.append(f"regime_rows_below_{min_regime}")
    if int(base["independent_bet_count"]) < 6:
        reasons.append("independent_bets_below_6")
    if applicable:
        if float(conservative["total_return"]) <= 0.0:
            reasons.append("conservative_return_non_positive")
        if float(conservative["profit_factor"]) < 1.02:
            reasons.append("conservative_profit_factor_below_1p02")
        if float(conservative["max_drawdown"]) < -0.20:
            reasons.append("conservative_drawdown_below_minus_20pct")
        if float(stress["total_return"]) < -0.02:
            reasons.append("stress_return_below_minus_2pct")
        if float(stress["profit_factor"]) < 0.98:
            reasons.append("stress_profit_factor_below_0p98")
        if bool(base["bankruptcy"]) or bool(conservative["bankruptcy"]) or bool(stress["bankruptcy"]):
            reasons.append("bankruptcy")
    return reasons, applicable


def _correct_timeframe_annualization(metrics: Mapping[str, Any], minutes: int) -> dict[str, Any]:
    corrected = dict(metrics)
    rows = max(int(corrected.get("row_count", 0)), 1)
    total_return = float(corrected.get("total_return", 0.0))
    periods_per_year = 365.0 * 24.0 * 60.0 / float(minutes)
    annualized_return = -1.0 if total_return <= -1.0 else math.expm1(
        float(np.clip(math.log1p(total_return) * periods_per_year / rows, -50.0, 50.0))
    )
    scale = math.sqrt(5.0 / float(minutes))
    corrected["annualized_return"] = _round(annualized_return)
    corrected["annualized_volatility"] = _round(float(corrected.get("annualized_volatility", 0.0)) * scale)
    corrected["sharpe"] = _round(float(corrected.get("sharpe", 0.0)) * scale)
    corrected["annualization_period_minutes"] = minutes
    corrected["annualization_corrected_from_reused_5m_primitive"] = True
    return corrected


def _refresh_candidate(row: dict[str, Any], cumulative: int) -> None:
    folds = row["selection_folds"]
    applicable = [fold for fold in folds if fold["applicable"]]
    passed = [fold for fold in folds if fold["passed"]]
    conservative = [fold["cost_scenarios"]["conservative"] for fold in folds]
    stress = [fold["cost_scenarios"]["stress"] for fold in folds]
    pooled_effective = sum(float(fold["cost_scenarios"]["base"]["effective_bet_count"]) for fold in folds)
    pooled_bets = sum(int(fold["cost_scenarios"]["base"]["independent_bet_count"]) for fold in folds)
    means = [float(fold["cost_scenarios"]["base"]["mean_bet_return"]) for fold in folds]
    stds = [float(fold["cost_scenarios"]["base"]["bet_return_std"]) for fold in folds]
    median_mean = float(np.median(means))
    median_std = float(np.median(stds))
    haircut = math.sqrt(2.0 * math.log(max(cumulative, 2))) * median_std / math.sqrt(max(pooled_effective, 1.0))
    row["applicable_fold_count"] = len(applicable)
    row["passed_fold_count"] = len(passed)
    row["pooled_independent_bets"] = pooled_bets
    row["pooled_effective_bets"] = _round(pooled_effective)
    row["multiple_testing"] = {
        "cumulative_unique_trials": cumulative,
        "haircut": _round(haircut),
        "deflated_mean_bet_return": _round(median_mean - haircut),
    }
    row["constraint_reasons"] = []
    if len(applicable) < max(1, len(folds) - 1):
        row["constraint_reasons"].append("applicable_folds_below_required")
    if pooled_bets < 24:
        row["constraint_reasons"].append("pooled_independent_bets_below_24")
    if pooled_effective < 14.4:
        row["constraint_reasons"].append("pooled_effective_bets_below_14p4")
    row["feasible"] = not row["constraint_reasons"]
    row["objectives"] = {
        "worst_conservative_return": min(float(item["total_return"]) for item in conservative),
        "median_conservative_return": float(np.median([float(item["total_return"]) for item in conservative])),
        "worst_stress_return": min(float(item["total_return"]) for item in stress),
        "median_conservative_profit_factor": float(np.median([min(10.0, float(item["profit_factor"])) for item in conservative])),
        "deflated_mean_bet_return": median_mean - haircut,
        "cost_efficiency": -sum(float(item["cost_drag"]) for item in conservative) / max(pooled_bets, 1),
        "tail_drawdown": min(float(item["max_drawdown"]) for item in stress),
    }


def _assign_pareto(rows: Sequence[dict[str, Any]], cumulative: int) -> None:
    for row in rows:
        _refresh_candidate(row, cumulative)
    feasible = [row for row in rows if row["feasible"]]
    infeasible = [row for row in rows if not row["feasible"]]
    _pareto_ranks(feasible, start_rank=0)
    _pareto_ranks(infeasible, start_rank=(max((int(row["pareto_rank"]) for row in feasible), default=-1) + 1))


def _pareto_ranks(rows: Sequence[dict[str, Any]], *, start_rank: int) -> None:
    remaining = set(range(len(rows)))
    rank = start_rank
    while remaining:
        front = [i for i in remaining if not any(_dominates(rows[j], rows[i]) for j in remaining if j != i)]
        for i in front or [min(remaining)]:
            rows[i]["pareto_rank"] = rank
            remaining.remove(i)
        rank += 1


def _dominates(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    a, b = left["objectives"], right["objectives"]
    return all(float(a[key]) >= float(b[key]) for key in a) and any(float(a[key]) > float(b[key]) for key in a)


def _selection_gate_reasons(row: Mapping[str, Any], fold_count: int) -> list[str]:
    reasons = list(row.get("constraint_reasons", []))
    if int(row.get("passed_fold_count", 0)) < max(1, fold_count - 1):
        reasons.append(f"passed_folds_below_{max(1, fold_count - 1)}_of_{fold_count}")
    if float(row.get("multiple_testing", {}).get("deflated_mean_bet_return", 0.0)) <= 0.0:
        reasons.append("multiple_testing_deflated_mean_bet_return_non_positive")
    if not bool(row.get("parameter_neighborhood_stability", {}).get("passed")):
        reasons.append("parameter_neighborhood_stability_failed")
    return list(dict.fromkeys(reasons))


def _set_neighborhood(champion: dict[str, Any], neighbors: Sequence[Mapping[str, Any]]) -> None:
    if not neighbors:
        champion["parameter_neighborhood_stability"] = {"status": "not_enough_budget", "passed": False, "neighbor_count": 0}
        return
    stable = sum(
        int(bool(row.get("feasible")) and int(row.get("passed_fold_count", 0)) >= max(1, len(row["selection_folds"]) - 1))
        for row in neighbors
    )
    required = math.ceil(len(neighbors) * 2 / 3)
    champion["parameter_neighborhood_stability"] = {
        "status": "pass" if stable >= required else "fail",
        "passed": stable >= required,
        "neighbor_count": len(neighbors),
        "stable_neighbor_count": stable,
        "required_stable_neighbors": required,
    }


def _evaluate_negative_control(frame: pd.DataFrame, minutes: int, folds: Sequence[FoldSpec], sizing: FixedSizingPolicy, risk: FixedRiskConstitution) -> dict[str, Any]:
    close = frame["close"].astype(float)
    fast = close.rolling(12, min_periods=12).mean()
    slow = close.rolling(48, min_periods=48).mean()
    direction = pd.Series(np.where(fast > slow, 1.0, np.where(fast < slow, -1.0, 0.0)), index=frame.index)
    rows = []
    for fold in folds:
        validation = frame.iloc[fold.validation_start:fold.validation_end]
        target, _ = apply_cost_aware_sizing(direction.loc[validation.index], sizing)
        costs = {}
        for scenario in COST_SCENARIOS:
            metrics, _ = simulate_regime_conditional_next_open(validation, target, cost_bps=scenario.total_bps, risk_constitution=risk)
            costs[scenario.name] = _correct_timeframe_annualization(metrics, minutes)
        rows.append(costs)
    return {
        "control_id": f"fixed_ma_12_48_{minutes}m",
        "timeframe_minutes": minutes,
        "role": "negative_control_reference",
        "eligible_for_selection": False,
        "cost_scenarios_by_fold": rows,
    }


def _public_candidate(row: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in row.items() if key != "genome"} | {"genome": row["genome"].to_dict()}


def _initial_population(family: str, size: int, rng: random.Random) -> list[TrendGenome]:
    return _dedupe_fill([], family, size, rng)


def _dedupe_fill(population: Sequence[TrendGenome], family: str, size: int, rng: random.Random) -> list[TrendGenome]:
    unique = {genome.genome_hash: genome for genome in population}
    attempts = 0
    while len(unique) < size and attempts < size * 100:
        genome = _random_genome(family, rng)
        unique.setdefault(genome.genome_hash, genome)
        attempts += 1
    if len(unique) < size:
        raise SearchContractError("genome_space_exhausted")
    return list(unique.values())[:size]


def _random_genome(family: str, rng: random.Random) -> TrendGenome:
    if family == FAMILIES[0]:
        return DynamicMomentumCycleGenome(**{name: rng.choice(values) for name, values in MOMENTUM_OPTIONS.items()})
    if family == FAMILIES[1]:
        return VolatilityChannelGenome(**{name: rng.choice(values) for name, values in CHANNEL_OPTIONS.items()})
    if family == FAMILIES[2]:
        values = {name: rng.choice(options) for name, options in PULLBACK_OPTIONS.items() if name != "ema_pair"}
        values["ema_fast_bars"], values["ema_slow_bars"] = rng.choice(PULLBACK_OPTIONS["ema_pair"])
        return PullbackReaccelerationGenome(**values)
    raise SearchContractError("family_not_allowed")


def _neighbors(genome: TrendGenome, *, limit: int) -> list[TrendGenome]:
    result: dict[str, TrendGenome] = {}
    values = asdict(genome)
    for name, options in _options_for_genome(genome).items():
        for option in options:
            candidate_values = dict(values)
            if name == "ema_pair":
                candidate_values["ema_fast_bars"], candidate_values["ema_slow_bars"] = option
            else:
                candidate_values[name] = option
            candidate = type(genome)(**candidate_values)
            if candidate.genome_hash != genome.genome_hash:
                result.setdefault(candidate.genome_hash, candidate)
            if len(result) >= limit:
                return list(result.values())
    return list(result.values())


def _tournament(rows: Sequence[Mapping[str, Any]], rng: random.Random) -> TrendGenome:
    sampled = rng.sample(list(rows), k=min(4, len(rows)))
    return min(sampled, key=candidate_sort_key)["genome"]  # type: ignore[return-value]


def _options_for_genome(genome: TrendGenome) -> dict[str, tuple[Any, ...]]:
    if isinstance(genome, DynamicMomentumCycleGenome):
        return MOMENTUM_OPTIONS
    if isinstance(genome, VolatilityChannelGenome):
        return CHANNEL_OPTIONS
    return PULLBACK_OPTIONS


def _validate_fields(genome: Any, options: Mapping[str, Sequence[Any]]) -> None:
    invalid = [item.name for item in fields(genome) if getattr(genome, item.name) not in options[item.name]]
    if invalid:
        raise SearchContractError("genome_invalid:" + ",".join(invalid))


def _atr(frame: pd.DataFrame, window: int) -> pd.Series:
    close, high, low = (frame[name].astype(float) for name in ("close", "high", "low"))
    prior = close.shift(1)
    true_range = pd.concat([(high - low).abs(), (high - prior).abs(), (low - prior).abs()], axis=1).max(axis=1)
    return true_range.rolling(window, min_periods=window).mean()


def _require_source_frame(frame: pd.DataFrame) -> None:
    _require_ohlcv(frame)
    if "available_time" not in frame.columns or "is_finalized" not in frame.columns:
        raise SelectionPrefixBindingError("source_visibility_fields_missing")
    available = pd.to_datetime(frame["available_time"], utc=True)
    expected = frame.index + pd.Timedelta(minutes=5) - pd.Timedelta(milliseconds=1)
    if not pd.DatetimeIndex(available).equals(pd.DatetimeIndex(expected)):
        raise SelectionPrefixBindingError("source_available_time_not_close_time")
    if not frame["is_finalized"].astype(bool).all():
        raise SelectionPrefixBindingError("source_unfinalized_bar")


def _require_ohlcv(frame: pd.DataFrame) -> None:
    required = {"open", "high", "low", "close", "volume"}
    if not isinstance(frame, pd.DataFrame) or frame.empty or not required.issubset(frame.columns):
        raise SearchContractError("ohlcv_fields_missing")
    if not isinstance(frame.index, pd.DatetimeIndex) or frame.index.tz is None or not frame.index.is_monotonic_increasing or frame.index.has_duplicates:
        raise SearchContractError("ohlcv_index_invalid")
    if not np.isfinite(frame[list(required)].astype(float).to_numpy()).all():
        raise SearchContractError("ohlcv_values_nonfinite")


def _derived_frame_hash(frame: pd.DataFrame) -> str:
    columns = ["open", "high", "low", "close", "volume", "available_time", "source_bar_count"]
    canonical = frame[columns].copy()
    canonical["available_time"] = pd.to_datetime(canonical["available_time"], utc=True).astype("int64")
    values_hash = pd.util.hash_pandas_object(canonical, index=True).to_numpy(dtype="<u8").tobytes()
    return hashlib.sha256(AGGREGATION_VERSION.encode("utf-8") + values_hash).hexdigest()


def _git_text(root: Path, args: Sequence[str]) -> str:
    result = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise SelectionPrefixBindingError("current_head_git_binding_unavailable")
    return result.stdout.strip()


def _git_commit_hash() -> str:
    result = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=False)
    value = result.stdout.strip()
    return value if result.returncode == 0 and len(value) == 40 else "unknown"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _round(value: float) -> float:
    return round(float(value), 12)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
