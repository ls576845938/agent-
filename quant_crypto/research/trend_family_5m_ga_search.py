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
from quant_crypto.research.intraday_ga_strategy_mining import FoldSpec, build_walk_forward_folds
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


SCHEMA_VERSION = "btc_5m_trend_family_ga_search_v1"
LOCK_SCHEMA_VERSION = "btc_5m_trend_family_candidate_lock_v1"
PREFIX_SCHEMA_VERSION = "shared_dataset_manifest_v1"
PREFIX_DATASET_ID = "btc-5m-qcv2r1-selection-prefix"
PREFIX_ATTESTATION_SCHEMA = "btc_5m_selection_prefix_attestation_v1"
PREFIX_PAYLOAD_RELATIVE_PATH = (
    "exchange=binance_spot/symbol=BTCUSDT/interval=5m/part-00000.jsonl"
)
DEFAULT_EXPERIMENT_ID = "btc-5m-trend-family-ga-search-02"
DEFAULT_SEED = 20260827
EXPECTED_SELECTION_ROWS = 248_270
EXPECTED_SELECTION_START = "2024-01-01T00:00:00+00:00"
EXPECTED_SELECTION_END = "2026-05-12T01:05:00+00:00"
PRIOR_UNIQUE_EVALUATIONS = 1_587
MAX_NEW_UNIQUE_EVALUATIONS = 300
FAMILIES = (
    "breakout_retest_continuation",
    "directional_efficiency_continuation",
)


class TrendFamilySearchError(ValueError):
    pass


class SelectionPrefixError(TrendFamilySearchError):
    pass


BREAKOUT_OPTIONS: dict[str, tuple[Any, ...]] = {
    "channel_bars": (12, 24, 48, 96),
    "retest_bars": (2, 3, 6),
    "exit_bars": (6, 12, 24, 48),
    "atr_window_bars": (14, 24, 48),
    "entry_buffer_atr": (0.0, 0.10, 0.25),
    "retest_tolerance_atr": (0.10, 0.25, 0.50),
    "htf_pair": ((12, 48), (24, 96), (48, 192)),
    "quality_threshold_atr": (0.5, 1.0, 1.5),
    "max_holding_bars": (12, 24, 48, 96),
    "cooldown_bars": (3, 6, 12),
}
EFFICIENCY_OPTIONS: dict[str, tuple[Any, ...]] = {
    "efficiency_window_bars": (24, 48, 96),
    "efficiency_threshold": (0.25, 0.35, 0.45, 0.55),
    "ema_pair": ((12, 48), (24, 96), (48, 192)),
    "slope_lookback_bars": (3, 6, 12),
    "continuation_window_bars": (6, 12, 24, 48),
    "exit_bars": (6, 12, 24, 48),
    "atr_window_bars": (14, 24, 48),
    "entry_buffer_atr": (0.0, 0.10, 0.25),
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
        payload = {"family": self.family, "active_genes": self.active_genes}
        return hashlib.sha256(_stable_json(payload).encode("utf-8")).hexdigest()

    @property
    def candidate_id(self) -> str:
        return f"btc_5m_trend_{self.genome_hash[:12]}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "family": self.family,
            "active_genes": self.active_genes,
            "genome_hash": self.genome_hash,
            "candidate_id": self.candidate_id,
            "family_inactive_genes_hashed": False,
        }


@dataclass(frozen=True)
class TradingRangeBreakoutGenome(_GenomeMixin):
    channel_bars: int
    retest_bars: int
    exit_bars: int
    atr_window_bars: int
    entry_buffer_atr: float
    retest_tolerance_atr: float
    htf_fast_bars: int
    htf_slow_bars: int
    quality_threshold_atr: float
    max_holding_bars: int
    cooldown_bars: int

    def __post_init__(self) -> None:
        values = asdict(self)
        pair = (values.pop("htf_fast_bars"), values.pop("htf_slow_bars"))
        invalid = [name for name, value in values.items() if value not in BREAKOUT_OPTIONS[name]]
        if pair not in BREAKOUT_OPTIONS["htf_pair"]:
            invalid.append("htf_pair")
        if invalid:
            raise TrendFamilySearchError("breakout_genome_invalid:" + ",".join(invalid))

    @property
    def family(self) -> str:
        return FAMILIES[0]

    @property
    def maximum_lookback_bars(self) -> int:
        return max(self.channel_bars + self.retest_bars, self.exit_bars, self.atr_window_bars, self.htf_slow_bars)


@dataclass(frozen=True)
class DirectionalEfficiencyGenome(_GenomeMixin):
    efficiency_window_bars: int
    efficiency_threshold: float
    ema_fast_bars: int
    ema_slow_bars: int
    slope_lookback_bars: int
    continuation_window_bars: int
    exit_bars: int
    atr_window_bars: int
    entry_buffer_atr: float
    max_holding_bars: int
    cooldown_bars: int

    def __post_init__(self) -> None:
        values = asdict(self)
        pair = (values.pop("ema_fast_bars"), values.pop("ema_slow_bars"))
        invalid = [name for name, value in values.items() if value not in EFFICIENCY_OPTIONS[name]]
        if pair not in EFFICIENCY_OPTIONS["ema_pair"]:
            invalid.append("ema_pair")
        if invalid:
            raise TrendFamilySearchError("efficiency_genome_invalid:" + ",".join(invalid))

    @property
    def family(self) -> str:
        return FAMILIES[1]

    @property
    def maximum_lookback_bars(self) -> int:
        return max(
            self.efficiency_window_bars,
            self.ema_slow_bars + self.slope_lookback_bars,
            self.continuation_window_bars,
            self.exit_bars,
            self.atr_window_bars,
        )


TrendGenome: TypeAlias = TradingRangeBreakoutGenome | DirectionalEfficiencyGenome


def load_immutable_selection_prefix(manifest_path: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    manifest_file = manifest_path.resolve()
    payload = json.loads(manifest_file.read_text(encoding="utf-8"))
    if payload.get("schema_version") != PREFIX_SCHEMA_VERSION:
        raise SelectionPrefixError("selection_prefix_schema_invalid")
    if payload.get("dataset_id") != PREFIX_DATASET_ID:
        raise SelectionPrefixError("selection_prefix_role_required")
    if validate_manifest(payload):
        raise SelectionPrefixError("selection_prefix_shared_manifest_invalid")
    coverage = payload.get("coverage")
    if not isinstance(coverage, Mapping):
        raise SelectionPrefixError("selection_prefix_coverage_missing")
    if _utc_text(coverage.get("start")) != EXPECTED_SELECTION_START:
        raise SelectionPrefixError("selection_prefix_start_invalid")
    if _utc_text(coverage.get("end")) != EXPECTED_SELECTION_END:
        raise SelectionPrefixError("selection_prefix_end_invalid")
    files = payload.get("files")
    if not isinstance(files, list):
        raise SelectionPrefixError("selection_prefix_files_invalid")
    file_entry = next(
        (
            item
            for item in files
            if isinstance(item, Mapping)
            and item.get("path") == PREFIX_PAYLOAD_RELATIVE_PATH
        ),
        None,
    )
    if not isinstance(file_entry, Mapping):
        raise SelectionPrefixError("selection_prefix_payload_entry_missing")
    repo_root = manifest_file.parents[3]
    resolved_root = resolve_manifest_file(
        manifest_file,
        shared_root=default_shared_data_root(repo_root),
        verify_files=True,
    )
    attestation_path = resolved_root / "selection_prefix_attestation.json"
    attestation = json.loads(attestation_path.read_text(encoding="utf-8"))
    selection = attestation.get("selection_prefix")
    transform = attestation.get("transform")
    if (
        attestation.get("schema_version") != PREFIX_ATTESTATION_SCHEMA
        or not isinstance(selection, Mapping)
        or not isinstance(transform, Mapping)
        or int(selection.get("row_count", -1)) != EXPECTED_SELECTION_ROWS
        or _utc_text(selection.get("end_open_time")) != EXPECTED_SELECTION_END
        or int(selection.get("application_bytes_after_boundary", -1)) != 0
        or transform.get("holdout_row_decoded") is not False
        or transform.get("strategy_metrics_read") is not False
        or transform.get("full_parent_partition_rehashed") is not False
    ):
        raise SelectionPrefixError("selection_prefix_attestation_invalid")
    payload_path = resolved_root / PREFIX_PAYLOAD_RELATIVE_PATH
    expected_sha = str(file_entry.get("sha256", ""))
    actual_sha = _sha256_file(payload_path)
    if len(expected_sha) != 64 or actual_sha != expected_sha:
        raise SelectionPrefixError("selection_prefix_sha256_mismatch")
    frame = _decode_selection_prefix(payload_path)
    _require_ohlcv(frame)
    if len(frame) != EXPECTED_SELECTION_ROWS:
        raise SelectionPrefixError("selection_prefix_decoded_rows_invalid")
    if frame.index[0].isoformat() != EXPECTED_SELECTION_START or frame.index[-1].isoformat() != EXPECTED_SELECTION_END:
        raise SelectionPrefixError("selection_prefix_decoded_boundary_invalid")
    provenance = {
        "dataset_id": payload.get("dataset_id"),
        "dataset_version": payload.get("dataset_version"),
        "aggregate_sha256": payload.get("aggregate_sha256"),
        "readiness_class": payload.get("readiness_class"),
        "manifest_path": manifest_file.as_posix(),
        "manifest_file_sha256": _sha256_file(manifest_file),
        "payload_path": payload_path.as_posix(),
        "payload_sha256": actual_sha,
        "decoded_rows": len(frame),
        "unseen_bytes_read": 0,
        "unseen_rows_decoded": 0,
        "unseen_strategy_metrics_read": False,
    }
    return frame, provenance


def _decode_selection_prefix(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".parquet":
        raw = pd.read_parquet(path)
    elif path.suffix.lower() in {".jsonl", ".ndjson"}:
        raw = pd.read_json(path, lines=True)
    else:
        raw = pd.read_csv(path)
    if "open_time" in raw.columns:
        index = pd.to_datetime(raw.pop("open_time"), utc=True)
    elif "open_time_ms" in raw.columns:
        index = pd.to_datetime(raw["open_time_ms"], unit="ms", utc=True)
    elif "event_time" in raw.columns:
        index = pd.to_datetime(raw["event_time"], utc=True).dt.floor("5min")
    else:
        raise SelectionPrefixError("selection_prefix_timestamp_missing")
    raw.index = pd.DatetimeIndex(index)
    return raw


def build_trend_events(frame: pd.DataFrame, genome: TrendGenome) -> pd.DataFrame:
    _require_ohlcv(frame)
    close, high, low = (frame[name].astype(float) for name in ("close", "high", "low"))
    atr = _atr(frame, genome.atr_window_bars)
    exit_high = high.shift(1).rolling(genome.exit_bars, min_periods=genome.exit_bars).max()
    exit_low = low.shift(1).rolling(genome.exit_bars, min_periods=genome.exit_bars).min()
    if isinstance(genome, TradingRangeBreakoutGenome):
        fast = close.ewm(span=genome.htf_fast_bars, adjust=False, min_periods=genome.htf_fast_bars).mean()
        slow = close.ewm(span=genome.htf_slow_bars, adjust=False, min_periods=genome.htf_slow_bars).mean()
        quality = (fast - slow).abs() / atr.replace(0.0, np.nan)
        bull = (fast > slow) & (close > slow) & (quality >= genome.quality_threshold_atr)
        bear = (fast < slow) & (close < slow) & (quality >= genome.quality_threshold_atr)
        upper = high.shift(1).rolling(genome.channel_bars, min_periods=genome.channel_bars).max()
        lower = low.shift(1).rolling(genome.channel_bars, min_periods=genome.channel_bars).min()
        broke_up = close > upper + genome.entry_buffer_atr * atr
        broke_down = close < lower - genome.entry_buffer_atr * atr
        prior_up = broke_up.shift(1).rolling(genome.retest_bars, min_periods=1).max().fillna(0).astype(bool)
        prior_down = broke_down.shift(1).rolling(genome.retest_bars, min_periods=1).max().fillna(0).astype(bool)
        long_entry = bull & prior_up & (low <= upper + genome.retest_tolerance_atr * atr) & (close > upper)
        short_entry = bear & prior_down & (high >= lower - genome.retest_tolerance_atr * atr) & (close < lower)
        eligible = bull | bear
        long_exit = (~bull) | (close < exit_low)
        short_exit = (~bear) | (close > exit_high)
        confidence = (quality / max(genome.quality_threshold_atr, 0.5)).clip(0.25, 1.0)
        ready = atr.notna() & slow.notna() & upper.notna() & lower.notna()
    elif isinstance(genome, DirectionalEfficiencyGenome):
        fast = close.ewm(span=genome.ema_fast_bars, adjust=False, min_periods=genome.ema_fast_bars).mean()
        slow = close.ewm(span=genome.ema_slow_bars, adjust=False, min_periods=genome.ema_slow_bars).mean()
        movement = close.diff().abs().rolling(genome.efficiency_window_bars, min_periods=genome.efficiency_window_bars).sum()
        efficiency = (close - close.shift(genome.efficiency_window_bars)).abs() / movement.replace(0.0, np.nan)
        slope = slow - slow.shift(genome.slope_lookback_bars)
        bull = (efficiency >= genome.efficiency_threshold) & (fast > slow) & (slope > 0.0)
        bear = (efficiency >= genome.efficiency_threshold) & (fast < slow) & (slope < 0.0)
        upper = high.shift(1).rolling(genome.continuation_window_bars, min_periods=genome.continuation_window_bars).max()
        lower = low.shift(1).rolling(genome.continuation_window_bars, min_periods=genome.continuation_window_bars).min()
        long_entry = bull & (close > upper + genome.entry_buffer_atr * atr)
        short_entry = bear & (close < lower - genome.entry_buffer_atr * atr)
        eligible = bull | bear
        long_exit = (~bull) | (close < fast) | (close < exit_low)
        short_exit = (~bear) | (close > fast) | (close > exit_high)
        confidence = efficiency.clip(0.25, 1.0)
        ready = atr.notna() & slow.notna() & efficiency.notna() & upper.notna() & lower.notna()
    else:
        raise TrendFamilySearchError("genome_type_invalid")
    return pd.DataFrame(
        {
            "regime_eligible": (eligible & ready).fillna(False).astype(bool),
            "long_entry": (long_entry & ready).fillna(False).astype(bool),
            "short_entry": (short_entry & ready).fillna(False).astype(bool),
            "long_invalidation": long_exit.fillna(True).astype(bool),
            "short_invalidation": short_exit.fillna(True).astype(bool),
            "confidence": confidence.fillna(0.0).astype(float),
            "hypothesis_family": genome.family,
        },
        index=frame.index,
    )


def crossover_within_family(left: TrendGenome, right: TrendGenome, rng: random.Random) -> TrendGenome:
    if type(left) is not type(right):
        raise TrendFamilySearchError("cross_family_crossover_forbidden")
    values = {}
    left_values, right_values = asdict(left), asdict(right)
    pair_names = {TradingRangeBreakoutGenome: ("htf_fast_bars", "htf_slow_bars"), DirectionalEfficiencyGenome: ("ema_fast_bars", "ema_slow_bars")}
    pair = pair_names[type(left)]
    for name in left_values:
        if name not in pair:
            values[name] = left_values[name] if rng.random() < 0.5 else right_values[name]
    source = left_values if rng.random() < 0.5 else right_values
    values[pair[0]], values[pair[1]] = source[pair[0]], source[pair[1]]
    return type(left)(**values)


def mutate_within_family(genome: TrendGenome, rng: random.Random) -> TrendGenome:
    values = asdict(genome)
    options = BREAKOUT_OPTIONS if isinstance(genome, TradingRangeBreakoutGenome) else EFFICIENCY_OPTIONS
    pair_key = "htf_pair" if isinstance(genome, TradingRangeBreakoutGenome) else "ema_pair"
    pair_names = ("htf_fast_bars", "htf_slow_bars") if isinstance(genome, TradingRangeBreakoutGenome) else ("ema_fast_bars", "ema_slow_bars")
    selectable = [name for name in options]
    for name in rng.sample(selectable, k=rng.choice((1, 1, 2))):
        replacement = rng.choice(options[name])
        if name == pair_key:
            values[pair_names[0]], values[pair_names[1]] = replacement
        else:
            values[name] = replacement
    return type(genome)(**values)


def run_trend_family_search_on_selection_frame(
    *,
    frame: pd.DataFrame,
    data_provenance: Mapping[str, Any],
    output_root: Path | None,
    seed: int = DEFAULT_SEED,
    population_per_family: int = 24,
    generations: int = 6,
    fold_count: int = 4,
    prior_unique_evaluations: int = PRIOR_UNIQUE_EVALUATIONS,
    generated_at_utc: datetime | None = None,
) -> dict[str, Any]:
    _require_ohlcv(frame)
    if population_per_family < 8 or generations < 1 or fold_count < 2:
        raise TrendFamilySearchError("search_configuration_too_small")
    planned_slots = len(FAMILIES) * population_per_family * generations
    if planned_slots != 288 and (population_per_family, generations) == (24, 6):
        raise TrendFamilySearchError("official_budget_invalid")
    if planned_slots > 288 or prior_unique_evaluations != PRIOR_UNIQUE_EVALUATIONS:
        raise TrendFamilySearchError("trial_budget_or_prior_count_invalid")
    sizing, risk = FixedSizingPolicy(), FixedRiskConstitution()
    maximum_lookback = max(192, 96 + 12)
    event_memory = max(96 + 12, risk.daily_pause_bars, risk.structure_pause_bars)
    embargo = maximum_lookback + event_memory
    folds = build_walk_forward_folds(len(frame), fold_count=fold_count, embargo_bars=embargo)
    if len(folds) != fold_count:
        raise TrendFamilySearchError("walk_forward_fold_construction_failed")
    rng = random.Random(int(seed))
    cache: dict[str, dict[str, Any]] = {}
    populations = {
        FAMILIES[0]: _initial_population(FAMILIES[0], population_per_family, rng),
        FAMILIES[1]: _initial_population(FAMILIES[1], population_per_family, rng),
    }
    trace: list[dict[str, Any]] = []
    for generation in range(1, generations + 1):
        evaluated_by_family: dict[str, list[dict[str, Any]]] = {}
        for family, population in populations.items():
            evaluated_by_family[family] = [
                _evaluate_candidate(frame, genome, folds, cache, sizing, risk) for genome in population
            ]
        combined = [row for rows in evaluated_by_family.values() for row in rows]
        _assign_pareto(combined, prior_unique_evaluations + len(cache))
        trace.append({"generation": generation, "unique_evaluations": len(cache), "family_best": {family: sorted(rows, key=_sort_key)[0]["candidate_id"] for family, rows in evaluated_by_family.items()}})
        next_populations: dict[str, list[TrendGenome]] = {}
        for family, rows in evaluated_by_family.items():
            rows.sort(key=_sort_key)
            elite_count = max(2, population_per_family // 8)
            next_population = [row["genome"] for row in rows[:elite_count]]
            while len(next_population) < population_per_family:
                left = _tournament(rows, rng)
                right = _tournament(rows, rng)
                next_population.append(mutate_within_family(crossover_within_family(left, right, rng), rng))
            next_populations[family] = _dedupe_fill(next_population, family, population_per_family, rng)
        populations = next_populations
    rows = list(cache.values())
    _assign_pareto(rows, prior_unique_evaluations + len(cache))
    rows.sort(key=_sort_key)
    champion = rows[0]
    neighbors = _neighbors(champion["genome"], limit=max(0, MAX_NEW_UNIQUE_EVALUATIONS - len(cache)))
    neighbor_rows = [_evaluate_candidate(frame, genome, folds, cache, sizing, risk) for genome in neighbors]
    baseline = _median_base_return(champion)
    neighbor_returns = [_median_base_return(row) for row in neighbor_rows]
    threshold = max(0.0, baseline * 0.5)
    stable = sum(int(value >= threshold) for value in neighbor_returns)
    required = max(2, math.ceil(len(neighbor_returns) / 2)) if neighbor_returns else 2
    champion["parameter_neighborhood_stability"] = {
        "status": "pass" if baseline > 0 and stable >= required else "fail",
        "passed": bool(baseline > 0 and stable >= required),
        "neighbor_count": len(neighbor_rows),
        "stable_neighbor_count": stable,
        "required_stable_neighbor_count": required,
        "neighbor_median_returns": [_round(value) for value in neighbor_returns],
        "family_switch_count": 0,
    }
    _assign_pareto(list(cache.values()), prior_unique_evaluations + len(cache))
    reasons = _selection_gate_reasons(champion, fold_count)
    generated = (generated_at_utc or datetime.now(timezone.utc)).astimezone(timezone.utc)
    lock = {
        "schema_version": LOCK_SCHEMA_VERSION,
        "generated_at": generated.isoformat(),
        "locked_candidate": _public_candidate(champion),
        "selection_gate_reasons": reasons,
        "selection_only": True,
        "reveal_authorized": False,
        "separate_preregistered_reveal_ticket_required": True,
        "holdout_bytes_read": 0,
        "holdout_rows_decoded": 0,
        "holdout_strategy_metrics_read": False,
        "promotion_allowed": False,
        "paper_allowed": False,
        "live_allowed": False,
    }
    lock["semantic_sha256"] = hashlib.sha256(_stable_json(lock).encode("utf-8")).hexdigest()
    negative_control = _evaluate_negative_control(frame, folds, sizing, risk)
    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "experiment_id": DEFAULT_EXPERIMENT_ID,
        "generated_at": generated.isoformat(),
        "code_commit": _git_commit_hash(),
        "status": "complete_research_only",
        "decision": "selection_gate_passed_candidate_locked_holdout_not_authorized" if not reasons else "reject_selection_batch_holdout_not_read",
        "data_provenance": dict(data_provenance),
        "economic_sources": [
            {"doi": "10.1016/j.frl.2019.08.011", "use": "trading_range_breakout_hypothesis_only"},
            {"doi": "10.3390/risks8020044", "use": "five_minute_ma_negative_control"},
            {"url": "https://ssrn.com/abstract=4080253", "use": "intraday_regime_jump_liquidity_caution"},
            {"url": "https://ssrn.com/abstract=3416106", "use": "five_minute_realized_volatility_measurement_context"},
            {"url": "https://arxiv.org/abs/2009.12155", "use": "crypto_walk_forward_trend_background"},
        ],
        "architecture": {
            "typed_hierarchical_ga": True,
            "within_family_crossover_mutation_only": True,
            "cross_family_only_unified_pareto": True,
            "family_inactive_genes_hashed_or_counted": False,
            "fixed_sizing_policy": sizing.to_dict(),
            "fixed_risk_constitution": risk.to_dict(),
            "pnl_derived_from_fills_positions_cash": True,
        },
        "search_protocol": {
            "families": list(FAMILIES),
            "population_per_family": population_per_family,
            "generations": generations,
            "planned_slots": planned_slots,
            "neighbor_limit": 12,
            "run_unique_evaluations": len(cache),
            "prior_unique_evaluations": prior_unique_evaluations,
            "cumulative_unique_evaluations": prior_unique_evaluations + len(cache),
            "multiple_testing_adjustment": "expected_maximum_normal_haircut",
            "three_cost_scenarios_in_pareto_and_fold_gate": True,
            "generation_trace": trace,
        },
        "validation_design": {
            "selection_only": True,
            "completed_5m_close_decision": True,
            "next_open_execution": True,
            "flat_at_fold_start": True,
            "validation_entries_only": True,
            "fold_count": fold_count,
            "folds": [fold.to_dict(frame.index) for fold in folds],
            "maximum_lookback_bars": maximum_lookback,
            "event_memory_bars": event_memory,
            "embargo_bars": embargo,
            "embargo_at_least_lookback_plus_event_memory": embargo >= maximum_lookback + event_memory,
            "holdout_bytes_read": 0,
            "holdout_rows_decoded": 0,
            "holdout_strategy_metrics_read": False,
            "reveal_code_path_present": False,
        },
        "negative_control": negative_control,
        "top_candidates": [_public_candidate(row) for row in rows[: min(4, len(rows))]],
        "candidate_lock": {"semantic_sha256": lock["semantic_sha256"], "reveal_authorized": False},
        "selection_gate_reasons": reasons,
        "retained_locked_candidate_count": 1 if not reasons else 0,
        "promotion": {"research_only": True, "promotion_ready": False, "paper_auto_start": False, "live_enabled": False},
        "safety": {
            "public_network_called": False,
            "private_endpoints_allowed": False,
            "order_endpoints_allowed": False,
            "real_orders_created": False,
            "paper_queue_write_allowed": False,
            "transfer_allowed": False,
            "withdraw_allowed": False,
        },
        "blockers": [
            "selection_only_no_holdout_reveal_authorized",
            "fixed_bps_costs_do_not_prove_l2_queue_latency_funding_or_liquidation",
            "completed_bar_hard_stop_proxy_is_not_venue_hosted_protection",
            "promotion_paper_live_require_separate_current_head_evidence_and_human_gate",
        ],
    }
    report["artifact_hash"] = hashlib.sha256(_stable_json(report).encode("utf-8")).hexdigest()
    if output_root is not None:
        try:
            output_root.mkdir(parents=True, exist_ok=False)
        except FileExistsError as exc:
            raise TrendFamilySearchError("output_root_must_be_new") from exc
        _write_json(output_root / "btc_5m_trend_family_ga_search_report.json", report)
        _write_json(output_root / "btc_5m_trend_family_candidate_lock.json", lock)
        _write_json(output_root / "btc_5m_trend_family_candidate_definitions.json", {"schema_version": "btc_5m_trend_family_candidate_definitions_v1", "locked_candidates": [] if reasons else [_public_candidate(champion)], "negative_control_included": False, "demo_strategy_registration_allowed": False, "paper_queue_write_allowed": False, "live_unlock_allowed": False})
    return report


def run_btc_trend_family_5m_ga_search(*, selection_prefix_manifest: Path, output_root: Path, seed: int = DEFAULT_SEED, population_per_family: int = 24, generations: int = 6, fold_count: int = 4, generated_at_utc: datetime | None = None) -> dict[str, Any]:
    frame, provenance = load_immutable_selection_prefix(selection_prefix_manifest)
    return run_trend_family_search_on_selection_frame(frame=frame, data_provenance=provenance, output_root=output_root, seed=seed, population_per_family=population_per_family, generations=generations, fold_count=fold_count, prior_unique_evaluations=PRIOR_UNIQUE_EVALUATIONS, generated_at_utc=generated_at_utc)


def _evaluate_candidate(frame: pd.DataFrame, genome: TrendGenome, folds: Sequence[FoldSpec], cache: dict[str, dict[str, Any]], sizing: FixedSizingPolicy, risk: FixedRiskConstitution) -> dict[str, Any]:
    if genome.genome_hash in cache:
        return cache[genome.genome_hash]
    fold_rows = []
    for fold in folds:
        context_start = max(0, fold.validation_start - genome.maximum_lookback_bars)
        context = frame.iloc[context_start:fold.validation_end]
        validation = frame.iloc[fold.validation_start:fold.validation_end]
        events = build_trend_events(context, genome).loc[validation.index]
        direction, diagnostics = build_position_path_from_events(validation, events, genome, risk)  # type: ignore[arg-type]
        target, sizing_diagnostics = apply_cost_aware_sizing(direction, sizing)
        eligible = events["regime_eligible"]
        costs = {}
        for scenario in COST_SCENARIOS:
            metrics, ledger = simulate_regime_conditional_next_open(validation, target, cost_bps=scenario.total_bps, risk_constitution=risk, regime_eligible_at_close=eligible)
            costs[scenario.name] = metrics
            if scenario.name == "base":
                base_ledger = ledger
        reasons = _fold_gate_reasons(costs)
        fold_rows.append({
            "fold_id": fold.fold_id,
            "flat_at_fold_start": True,
            "entries_counted_before_validation": 0,
            "validation_entry_count": diagnostics["entry_count"],
            "performance_gate_applied": int(costs["base"]["regime_eligible_rows"]) >= 288 and int(costs["base"]["independent_bet_count"]) >= 8,
            "passed": not reasons,
            "reasons": reasons,
            "cost_scenarios": costs,
            "base_ledger": base_ledger,
            "target_diagnostics": {**diagnostics, **sizing_diagnostics},
        })
    row: dict[str, Any] = {"genome": genome, "genome_hash": genome.genome_hash, "candidate_id": genome.candidate_id, "family": genome.family, "walk_forward": fold_rows, "parameter_neighborhood_stability": {"status": "not_evaluated", "passed": False, "neighbor_count": 0}}
    cache[genome.genome_hash] = row
    _refresh(row, max(1, len(cache)))
    return row


def _fold_gate_reasons(costs: Mapping[str, Mapping[str, Any]]) -> list[str]:
    reasons = []
    base, conservative, stress = (costs[name] for name in ("base", "conservative", "stress"))
    if int(base.get("regime_eligible_rows", 0)) < 288:
        reasons.append("regime_rows_below_288")
    if int(base.get("independent_bet_count", 0)) < 8:
        reasons.append("independent_bets_below_8")
    if float(base.get("effective_bet_count", 0)) < 4.8:
        reasons.append("effective_bets_below_4p8")
    for name, metrics, pf in (("base", base, 1.05), ("conservative", conservative, 1.02), ("stress", stress, 1.0)):
        if float(metrics.get("total_return", 0)) <= 0:
            reasons.append(f"{name}_return_non_positive")
        if float(metrics.get("profit_factor", 0)) < pf:
            reasons.append(f"{name}_profit_factor_below_{str(pf).replace('.', 'p')}")
        if float(metrics.get("max_drawdown", -1)) < -0.20:
            reasons.append(f"{name}_drawdown_below_minus_20pct")
        if bool(metrics.get("bankruptcy")):
            reasons.append(f"{name}_bankruptcy")
    return reasons


def _refresh(row: dict[str, Any], cumulative: int) -> None:
    folds = row["walk_forward"]
    objectives = {}
    for cost in ("base", "conservative", "stress"):
        returns = [float(fold["cost_scenarios"][cost]["total_return"]) for fold in folds]
        pfs = [min(10.0, float(fold["cost_scenarios"][cost]["profit_factor"])) for fold in folds]
        objectives[f"worst_{cost}_return"] = min(returns)
        objectives[f"median_{cost}_return"] = float(np.median(returns))
        objectives[f"median_{cost}_profit_factor"] = float(np.median(pfs))
    means = [float(fold["cost_scenarios"]["base"]["mean_bet_return"]) for fold in folds]
    stds = [float(fold["cost_scenarios"]["base"]["bet_return_std"]) for fold in folds]
    effective = sum(float(fold["cost_scenarios"]["base"]["effective_bet_count"]) for fold in folds)
    median_mean, median_std = float(np.median(means)), float(np.median(stds))
    haircut = math.sqrt(2 * math.log(max(cumulative, 2))) * median_std / math.sqrt(max(effective, 1))
    row["multiple_testing"] = {"cumulative_unique_trials": cumulative, "pooled_effective_bets": _round(effective), "median_mean_bet_return": _round(median_mean), "haircut": _round(haircut), "deflated_mean_bet_return": _round(median_mean - haircut)}
    objectives["deflated_mean_bet_return"] = median_mean - haircut
    objectives["passed_fold_count"] = sum(int(fold["passed"]) for fold in folds)
    row["objectives"] = objectives
    row["passed_fold_count"] = int(objectives["passed_fold_count"])


def _assign_pareto(rows: Sequence[dict[str, Any]], cumulative: int) -> None:
    for row in rows:
        _refresh(row, cumulative)
    remaining = set(range(len(rows)))
    rank = 0
    while remaining:
        front = [i for i in remaining if not any(_dominates(rows[j], rows[i]) for j in remaining if j != i)]
        if not front:
            front = [min(remaining)]
        for i in front:
            rows[i]["pareto_rank"] = rank
            remaining.remove(i)
        rank += 1


def _dominates(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    a, b = left["objectives"], right["objectives"]
    return all(float(a[k]) >= float(b[k]) for k in a) and any(float(a[k]) > float(b[k]) for k in a)


def _sort_key(row: Mapping[str, Any]) -> tuple[Any, ...]:
    return (int(row.get("pareto_rank", 999)), -int(row.get("passed_fold_count", 0)), -float(row["multiple_testing"]["deflated_mean_bet_return"]), str(row["genome_hash"]))


def _selection_gate_reasons(row: Mapping[str, Any], fold_count: int) -> list[str]:
    reasons = []
    required = max(1, fold_count - 1)
    if int(row.get("passed_fold_count", 0)) < required:
        reasons.append(f"passed_folds_below_{required}_of_{fold_count}")
    if float(row["multiple_testing"].get("pooled_effective_bets", 0)) < 30:
        reasons.append("pooled_effective_bets_below_30")
    if float(row["multiple_testing"].get("deflated_mean_bet_return", 0)) <= 0:
        reasons.append("multiple_testing_deflated_mean_bet_return_non_positive")
    if not bool(row.get("parameter_neighborhood_stability", {}).get("passed")):
        reasons.append("parameter_neighborhood_stability_failed")
    return reasons


def _evaluate_negative_control(frame: pd.DataFrame, folds: Sequence[FoldSpec], sizing: FixedSizingPolicy, risk: FixedRiskConstitution) -> dict[str, Any]:
    results = []
    for fold in folds:
        validation = frame.iloc[fold.validation_start:fold.validation_end]
        close = validation["close"].astype(float)
        fast = close.ewm(span=12, adjust=False, min_periods=12).mean()
        slow = close.ewm(span=48, adjust=False, min_periods=48).mean()
        raw = pd.Series(np.where(fast > slow, 1.0, np.where(fast < slow, -1.0, 0.0)), index=validation.index)
        raw.iloc[0] = 0.0
        target, _ = apply_cost_aware_sizing(raw.fillna(0), sizing)
        metrics = {}
        for scenario in COST_SCENARIOS:
            metrics[scenario.name], _ = simulate_regime_conditional_next_open(validation, target, cost_bps=scenario.total_bps, risk_constitution=risk)
        results.append({"fold_id": fold.fold_id, "cost_scenarios": metrics, "flat_at_fold_start": True})
    return {"strategy": "fixed_ema_12_48_crossover", "purpose": "negative_control_only", "eligible_for_selection": False, "included_in_genetic_trials": False, "walk_forward": results}


def _random_genome(family: str, rng: random.Random) -> TrendGenome:
    if family == FAMILIES[0]:
        fast, slow = rng.choice(BREAKOUT_OPTIONS["htf_pair"])
        return TradingRangeBreakoutGenome(channel_bars=rng.choice(BREAKOUT_OPTIONS["channel_bars"]), retest_bars=rng.choice(BREAKOUT_OPTIONS["retest_bars"]), exit_bars=rng.choice(BREAKOUT_OPTIONS["exit_bars"]), atr_window_bars=rng.choice(BREAKOUT_OPTIONS["atr_window_bars"]), entry_buffer_atr=rng.choice(BREAKOUT_OPTIONS["entry_buffer_atr"]), retest_tolerance_atr=rng.choice(BREAKOUT_OPTIONS["retest_tolerance_atr"]), htf_fast_bars=fast, htf_slow_bars=slow, quality_threshold_atr=rng.choice(BREAKOUT_OPTIONS["quality_threshold_atr"]), max_holding_bars=rng.choice(BREAKOUT_OPTIONS["max_holding_bars"]), cooldown_bars=rng.choice(BREAKOUT_OPTIONS["cooldown_bars"]))
    if family == FAMILIES[1]:
        fast, slow = rng.choice(EFFICIENCY_OPTIONS["ema_pair"])
        return DirectionalEfficiencyGenome(efficiency_window_bars=rng.choice(EFFICIENCY_OPTIONS["efficiency_window_bars"]), efficiency_threshold=rng.choice(EFFICIENCY_OPTIONS["efficiency_threshold"]), ema_fast_bars=fast, ema_slow_bars=slow, slope_lookback_bars=rng.choice(EFFICIENCY_OPTIONS["slope_lookback_bars"]), continuation_window_bars=rng.choice(EFFICIENCY_OPTIONS["continuation_window_bars"]), exit_bars=rng.choice(EFFICIENCY_OPTIONS["exit_bars"]), atr_window_bars=rng.choice(EFFICIENCY_OPTIONS["atr_window_bars"]), entry_buffer_atr=rng.choice(EFFICIENCY_OPTIONS["entry_buffer_atr"]), max_holding_bars=rng.choice(EFFICIENCY_OPTIONS["max_holding_bars"]), cooldown_bars=rng.choice(EFFICIENCY_OPTIONS["cooldown_bars"]))
    raise TrendFamilySearchError("family_invalid")


def _initial_population(family: str, size: int, rng: random.Random) -> list[TrendGenome]:
    return _dedupe_fill([], family, size, rng)


def _dedupe_fill(genomes: Sequence[TrendGenome], family: str, size: int, rng: random.Random) -> list[TrendGenome]:
    unique = {genome.genome_hash: genome for genome in genomes}
    attempts = 0
    while len(unique) < size and attempts < size * 200:
        genome = _random_genome(family, rng)
        unique.setdefault(genome.genome_hash, genome)
        attempts += 1
    if len(unique) < size:
        raise TrendFamilySearchError("family_gene_space_exhausted")
    return list(unique.values())[:size]


def _tournament(rows: Sequence[Mapping[str, Any]], rng: random.Random) -> TrendGenome:
    winner = sorted(rng.sample(list(rows), min(4, len(rows))), key=_sort_key)[0]
    return winner["genome"]


def _neighbors(genome: TrendGenome, limit: int) -> list[TrendGenome]:
    if limit <= 0:
        return []
    values = asdict(genome)
    options = BREAKOUT_OPTIONS if isinstance(genome, TradingRangeBreakoutGenome) else EFFICIENCY_OPTIONS
    pair_key = "htf_pair" if isinstance(genome, TradingRangeBreakoutGenome) else "ema_pair"
    pair_names = ("htf_fast_bars", "htf_slow_bars") if isinstance(genome, TradingRangeBreakoutGenome) else ("ema_fast_bars", "ema_slow_bars")
    current_pair = (values[pair_names[0]], values[pair_names[1]])
    neighbors = []
    for name, choices in options.items():
        current = current_pair if name == pair_key else values[name]
        index = list(choices).index(current)
        replacement = choices[index + 1] if index + 1 < len(choices) else choices[index - 1]
        candidate = dict(values)
        if name == pair_key:
            candidate[pair_names[0]], candidate[pair_names[1]] = replacement
        else:
            candidate[name] = replacement
        neighbor = type(genome)(**candidate)
        if neighbor.genome_hash != genome.genome_hash:
            neighbors.append(neighbor)
        if len(neighbors) >= min(12, limit):
            break
    return neighbors


def _median_base_return(row: Mapping[str, Any]) -> float:
    return float(np.median([float(fold["cost_scenarios"]["base"]["total_return"]) for fold in row["walk_forward"]]))


def _public_candidate(row: Mapping[str, Any]) -> dict[str, Any]:
    genome: TrendGenome = row["genome"]
    return {"candidate_id": row["candidate_id"], "genome_hash": row["genome_hash"], "family": row["family"], "typed_genome": genome.to_dict(), "pareto_rank": row.get("pareto_rank"), "passed_fold_count": row["passed_fold_count"], "multiple_testing": row["multiple_testing"], "parameter_neighborhood_stability": row["parameter_neighborhood_stability"], "walk_forward": row["walk_forward"], "research_only": True}


def _atr(frame: pd.DataFrame, window: int) -> pd.Series:
    high, low, close = (frame[name].astype(float) for name in ("high", "low", "close"))
    previous = close.shift(1)
    tr = pd.concat([high - low, (high - previous).abs(), (low - previous).abs()], axis=1).max(axis=1)
    return tr.rolling(window, min_periods=window).mean()


def _require_ohlcv(frame: pd.DataFrame) -> None:
    required = {"open", "high", "low", "close", "volume"}
    if not isinstance(frame, pd.DataFrame) or not required.issubset(frame.columns):
        raise TrendFamilySearchError("ohlcv_fields_missing")
    if not isinstance(frame.index, pd.DatetimeIndex) or frame.index.tz is None or frame.empty or not frame.index.is_monotonic_increasing or frame.index.has_duplicates:
        raise TrendFamilySearchError("ohlcv_index_invalid")
    values = frame[list(required)].astype(float)
    if not np.isfinite(values.to_numpy()).all():
        raise TrendFamilySearchError("ohlcv_values_nonfinite")


def _utc_text(value: Any) -> str:
    return pd.Timestamp(value).tz_convert("UTC").isoformat() if pd.Timestamp(value).tzinfo else pd.Timestamp(value).tz_localize("UTC").isoformat()


def _stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _round(value: float) -> float:
    return round(float(value), 12)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _git_commit_hash() -> str:
    result = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=False)
    value = result.stdout.strip()
    return value if result.returncode == 0 and len(value) == 40 else "unknown"


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
