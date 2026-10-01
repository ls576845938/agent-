from __future__ import annotations

import hashlib
import json
import math
import os
import random
import subprocess
import uuid
from dataclasses import asdict, dataclass, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from quant_crypto.research.high_yield_5m_ga_mining import (
    COST_SCENARIOS,
    CostScenario,
    load_committed_5m_market_frame,
)
from quant_crypto.research.intraday_ga_strategy_mining import (
    FoldSpec,
    build_walk_forward_folds,
)


SCHEMA_VERSION = "btc_5m_regime_conditional_alpha_search_v1"
CANDIDATE_LOCK_SCHEMA_VERSION = "btc_5m_regime_conditional_candidate_lock_v1"
DEFAULT_EXPERIMENT_ID = "btc-5m-regime-conditional-alpha-search-01"
DEFAULT_SEED = 20260827
DEFAULT_OUTPUT_ROOT = Path("artifacts/btc_5m_regime_conditional_alpha_search/latest")
ANNUAL_5M_BARS = 365.0 * 24.0 * 12.0
MIN_UNSEEN_HOLDOUT_ROWS = 1_000

HYPOTHESIS_FAMILIES = (
    "compression_breakout_continuation",
    "trend_pullback_reclaim",
    "range_failed_breakout_reversal",
)
STATE_PAIRS = ((12, 48), (24, 96), (48, 192))
STATE_STRENGTH_ATR = (0.5, 1.0, 1.5)
ENTRY_WINDOWS = (12, 24, 48, 96)
EXIT_WINDOWS = (6, 12, 24, 48)
ATR_WINDOWS = (14, 24, 48)
ENTRY_BUFFERS_ATR = (0.0, 0.10, 0.25)
INVALIDATION_ATR = (1.5, 2.0, 3.0)
MAX_HOLDING_BARS = (3, 6, 12, 24, 48, 96)
COOLDOWN_BARS = (3, 6, 12)
COMPRESSION_RATIOS = (0.70, 0.85, 1.00)

DEFAULT_MIN_REGIME_ROWS = 288
DEFAULT_MIN_INDEPENDENT_BETS = 8
DEFAULT_MIN_POOLED_EFFECTIVE_BETS = 30.0


class RegimeConditionalSearchError(ValueError):
    pass


@dataclass(frozen=True)
class AlphaGenome:
    """Searchable economic hypothesis, state, entry and semantic-exit contract.

    Position scaling, leverage, loss limits and pause thresholds are deliberately
    absent.  They belong to fixed policies below and cannot be optimized for
    historical return.
    """

    hypothesis_family: str
    state_fast_bars: int
    state_slow_bars: int
    state_strength_atr: float
    entry_window_bars: int
    exit_window_bars: int
    atr_window_bars: int
    entry_buffer_atr: float
    invalidation_atr: float
    max_holding_bars: int
    cooldown_bars: int
    compression_ratio: float

    def __post_init__(self) -> None:
        allowed = {
            "hypothesis_family": self.hypothesis_family in HYPOTHESIS_FAMILIES,
            "state_pair": (self.state_fast_bars, self.state_slow_bars) in STATE_PAIRS,
            "state_strength_atr": self.state_strength_atr in STATE_STRENGTH_ATR,
            "entry_window_bars": self.entry_window_bars in ENTRY_WINDOWS,
            "exit_window_bars": self.exit_window_bars in EXIT_WINDOWS,
            "atr_window_bars": self.atr_window_bars in ATR_WINDOWS,
            "entry_buffer_atr": self.entry_buffer_atr in ENTRY_BUFFERS_ATR,
            "invalidation_atr": self.invalidation_atr in INVALIDATION_ATR,
            "max_holding_bars": self.max_holding_bars in MAX_HOLDING_BARS,
            "cooldown_bars": self.cooldown_bars in COOLDOWN_BARS,
            "compression_ratio": self.compression_ratio in COMPRESSION_RATIOS,
        }
        invalid = [name for name, valid in allowed.items() if not valid]
        if invalid:
            raise RegimeConditionalSearchError(
                "alpha_genome_values_invalid:" + ",".join(invalid)
            )

    @property
    def genome_hash(self) -> str:
        return hashlib.sha256(_stable_json(asdict(self)).encode("utf-8")).hexdigest()

    @property
    def candidate_id(self) -> str:
        return f"btc_5m_regime_alpha_{self.genome_hash[:12]}"

    @property
    def maximum_lookback_bars(self) -> int:
        return max(
            self.state_slow_bars,
            self.entry_window_bars,
            self.exit_window_bars,
            self.atr_window_bars * 4,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "candidate_id": self.candidate_id,
            "maximum_lookback_bars": self.maximum_lookback_bars,
            "decision_interval": "5m_completed_bar",
            "market_state_horizons": {
                "fast_5m_bars": self.state_fast_bars,
                "slow_5m_bars": self.state_slow_bars,
                "fast_hours": _round(self.state_fast_bars / 12.0, 4),
                "slow_hours": _round(self.state_slow_bars / 12.0, 4),
            },
        }


@dataclass(frozen=True)
class FixedSizingPolicy:
    max_abs_position: float = 1.0
    rebalance_interval_bars: int = 12
    no_trade_band: float = 0.15
    minimum_position_delta: float = 0.15

    def __post_init__(self) -> None:
        if (
            self.max_abs_position != 1.0
            or self.rebalance_interval_bars < 1
            or not 0.0 <= self.no_trade_band <= 1.0
            or not 0.0 <= self.minimum_position_delta <= 1.0
        ):
            raise RegimeConditionalSearchError("fixed_sizing_policy_invalid")

    @property
    def policy_digest(self) -> str:
        return hashlib.sha256(_stable_json(asdict(self)).encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "policy_digest": self.policy_digest,
            "optimized_by_search": False,
            "standardized_alpha_selection_scale": "fixed_1x_cap",
        }


@dataclass(frozen=True)
class FixedRiskConstitution:
    max_abs_position: float = 1.0
    bar_hard_stop_atr_multiple: float = 3.0
    structure_shock_atr_multiple: float = 4.0
    structure_pause_bars: int = 12
    daily_loss_limit_pct: float = 0.04
    daily_pause_bars: int = 288
    max_strategy_loss_pct: float = 0.15
    venue_hosted_stop_proven: bool = False

    def __post_init__(self) -> None:
        if (
            self.max_abs_position != 1.0
            or self.bar_hard_stop_atr_multiple <= 0.0
            or self.structure_shock_atr_multiple <= 0.0
            or self.structure_pause_bars < 1
            or not 0.0 < self.daily_loss_limit_pct < 1.0
            or self.daily_pause_bars < 1
            or not 0.0 < self.max_strategy_loss_pct < 1.0
            or self.venue_hosted_stop_proven
        ):
            raise RegimeConditionalSearchError("fixed_risk_constitution_invalid")

    @property
    def policy_digest(self) -> str:
        return hashlib.sha256(_stable_json(asdict(self)).encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "policy_digest": self.policy_digest,
            "optimized_by_search": False,
            "hard_stop_evidence_class": "completed_bar_proxy_next_open_not_venue_hosted",
            "max_strategy_loss_behavior": "sticky_for_evaluation_fold",
            "daily_loss_resume_protocol": "fixed_bars_then_fresh_target_required",
        }


def build_alpha_events(frame: pd.DataFrame, genome: AlphaGenome) -> pd.DataFrame:
    """Build causal completed-bar economic events for one hypothesis family."""

    _require_ohlcv(frame)
    close = frame["close"].astype(float)
    high = frame["high"].astype(float)
    low = frame["low"].astype(float)
    atr = _atr(frame, genome.atr_window_bars)
    fast = close.ewm(
        span=genome.state_fast_bars,
        adjust=False,
        min_periods=genome.state_fast_bars,
    ).mean()
    slow = close.ewm(
        span=genome.state_slow_bars,
        adjust=False,
        min_periods=genome.state_slow_bars,
    ).mean()
    strength = (fast - slow).abs() / atr.replace(0.0, np.nan)
    bull = (fast > slow) & (close > slow) & (strength >= genome.state_strength_atr)
    bear = (fast < slow) & (close < slow) & (strength >= genome.state_strength_atr)
    range_state = strength <= genome.state_strength_atr

    upper = high.shift(1).rolling(
        genome.entry_window_bars,
        min_periods=genome.entry_window_bars,
    ).max()
    lower = low.shift(1).rolling(
        genome.entry_window_bars,
        min_periods=genome.entry_window_bars,
    ).min()
    exit_high = high.shift(1).rolling(
        genome.exit_window_bars,
        min_periods=genome.exit_window_bars,
    ).max()
    exit_low = low.shift(1).rolling(
        genome.exit_window_bars,
        min_periods=genome.exit_window_bars,
    ).min()
    atr_baseline = atr.rolling(
        genome.state_slow_bars,
        min_periods=genome.state_slow_bars,
    ).median()
    compressed_prior = (
        (atr / atr_baseline.replace(0.0, np.nan)) <= genome.compression_ratio
    ).shift(1).fillna(False)

    if genome.hypothesis_family == "compression_breakout_continuation":
        regime_eligible = (bull | bear) & compressed_prior
        long_entry = bull & compressed_prior & (
            close > upper + genome.entry_buffer_atr * atr
        )
        short_entry = bear & compressed_prior & (
            close < lower - genome.entry_buffer_atr * atr
        )
        long_invalidation = (~bull) | (close < exit_low) | (
            close < upper - genome.invalidation_atr * atr
        )
        short_invalidation = (~bear) | (close > exit_high) | (
            close > lower + genome.invalidation_atr * atr
        )
    elif genome.hypothesis_family == "trend_pullback_reclaim":
        pullback_window = max(3, genome.exit_window_bars)
        prior_pullback_long = (
            low.shift(1).rolling(pullback_window, min_periods=pullback_window).min()
            <= fast.shift(1)
        )
        prior_pullback_short = (
            high.shift(1).rolling(pullback_window, min_periods=pullback_window).max()
            >= fast.shift(1)
        )
        regime_eligible = bull | bear
        long_entry = (
            bull
            & prior_pullback_long
            & (close > fast)
            & (close > high.shift(1) + genome.entry_buffer_atr * atr)
        )
        short_entry = (
            bear
            & prior_pullback_short
            & (close < fast)
            & (close < low.shift(1) - genome.entry_buffer_atr * atr)
        )
        long_invalidation = (~bull) | (close < slow) | (close < exit_low)
        short_invalidation = (~bear) | (close > slow) | (close > exit_high)
    else:
        prior_failed_low = low.shift(1) < lower.shift(1)
        prior_failed_high = high.shift(1) > upper.shift(1)
        regime_eligible = range_state
        long_entry = range_state & prior_failed_low & (
            close > lower + genome.entry_buffer_atr * atr
        )
        short_entry = range_state & prior_failed_high & (
            close < upper - genome.entry_buffer_atr * atr
        )
        long_invalidation = (close < lower - genome.invalidation_atr * atr) | (
            close >= slow
        )
        short_invalidation = (close > upper + genome.invalidation_atr * atr) | (
            close <= slow
        )

    displacement = (close - slow).abs() / atr.replace(0.0, np.nan)
    confidence = (displacement / max(genome.state_strength_atr, 0.5)).clip(0.25, 1.0)
    ready = atr.notna() & fast.notna() & slow.notna() & upper.notna() & lower.notna()
    events = pd.DataFrame(
        {
            "regime_eligible": (regime_eligible & ready).fillna(False).astype(bool),
            "long_entry": (long_entry & ready).fillna(False).astype(bool),
            "short_entry": (short_entry & ready).fillna(False).astype(bool),
            "long_invalidation": long_invalidation.fillna(True).astype(bool),
            "short_invalidation": short_invalidation.fillna(True).astype(bool),
            "confidence": confidence.fillna(0.0).astype(float),
            "hypothesis_family": genome.hypothesis_family,
        },
        index=frame.index,
    )
    return events


def build_position_path_from_events(
    frame: pd.DataFrame,
    events: pd.DataFrame,
    genome: AlphaGenome,
    risk_constitution: FixedRiskConstitution,
) -> tuple[pd.Series, dict[str, Any]]:
    """Convert economic events to a causal semantic position direction.

    The bar hard stop and structure-shock detector are conservative research
    proxies.  They are not evidence of a hosted protective order.
    """

    _require_ohlcv(frame)
    required = {
        "regime_eligible",
        "long_entry",
        "short_entry",
        "long_invalidation",
        "short_invalidation",
    }
    if not required.issubset(events.columns) or not events.index.equals(frame.index):
        raise RegimeConditionalSearchError("alpha_events_contract_invalid")
    close = frame["close"].astype(float).to_numpy()
    high = frame["high"].astype(float).to_numpy()
    low = frame["low"].astype(float).to_numpy()
    atr_series = _atr(frame, genome.atr_window_bars)
    shock_atr_series = _true_range(frame).rolling(
        genome.atr_window_bars,
        min_periods=1,
    ).mean()
    atr = atr_series.to_numpy(dtype=float)
    shock_atr = shock_atr_series.to_numpy(dtype=float)
    effective_atr = np.where(np.isfinite(atr), atr, shock_atr)
    eligible = events["regime_eligible"].astype(bool).to_numpy()
    long_entry = events["long_entry"].astype(bool).to_numpy()
    short_entry = events["short_entry"].astype(bool).to_numpy()
    long_exit = events["long_invalidation"].astype(bool).to_numpy()
    short_exit = events["short_invalidation"].astype(bool).to_numpy()

    direction = np.zeros(len(frame), dtype=float)
    side = 0.0
    held_bars = 0
    entry_price = 0.0
    entry_atr = 0.0
    cooldown_remaining = 0
    structure_pause_remaining = 0
    time_stop_count = 0
    hard_stop_count = 0
    semantic_exit_count = 0
    structure_shock_count = 0
    entry_count = 0

    for pos in range(len(frame)):
        prior_atr = shock_atr[pos - 1] if pos > 0 else math.nan
        true_range = max(
            high[pos] - low[pos],
            abs(high[pos] - close[pos - 1]) if pos > 0 else 0.0,
            abs(low[pos] - close[pos - 1]) if pos > 0 else 0.0,
        )
        shock = bool(
            math.isfinite(prior_atr)
            and prior_atr > 0.0
            and true_range
            >= risk_constitution.structure_shock_atr_multiple * prior_atr
        )
        if shock:
            structure_shock_count += 1
            side = 0.0
            held_bars = 0
            structure_pause_remaining = risk_constitution.structure_pause_bars
            direction[pos] = 0.0
            continue

        if structure_pause_remaining > 0:
            structure_pause_remaining -= 1
            side = 0.0
            held_bars = 0
            direction[pos] = 0.0
            continue

        exit_reason = ""
        if side != 0.0:
            if held_bars >= genome.max_holding_bars:
                exit_reason = "time_stop"
                time_stop_count += 1
            elif (
                side > 0.0
                and entry_atr > 0.0
                and close[pos]
                <= entry_price
                - risk_constitution.bar_hard_stop_atr_multiple * entry_atr
            ) or (
                side < 0.0
                and entry_atr > 0.0
                and close[pos]
                >= entry_price
                + risk_constitution.bar_hard_stop_atr_multiple * entry_atr
            ):
                exit_reason = "bar_hard_stop_proxy"
                hard_stop_count += 1
            elif (side > 0.0 and long_exit[pos]) or (side < 0.0 and short_exit[pos]):
                exit_reason = "semantic_invalidation"
                semantic_exit_count += 1
        if exit_reason:
            side = 0.0
            held_bars = 0
            cooldown_remaining = genome.cooldown_bars

        if cooldown_remaining > 0:
            cooldown_remaining -= 1
        elif (
            side == 0.0
            and eligible[pos]
            and math.isfinite(effective_atr[pos])
            and effective_atr[pos] > 0.0
        ):
            if long_entry[pos] and not short_entry[pos]:
                side = 1.0
            elif short_entry[pos] and not long_entry[pos]:
                side = -1.0
            if side != 0.0:
                held_bars = 1
                entry_price = close[pos]
                entry_atr = effective_atr[pos]
                entry_count += 1
        elif side != 0.0:
            held_bars += 1
        direction[pos] = side

    result = pd.Series(
        direction,
        index=frame.index,
        name="semantic_direction_at_completed_5m_close",
    )
    diagnostics = {
        "entry_count": entry_count,
        "time_stop_count": time_stop_count,
        "bar_hard_stop_proxy_count": hard_stop_count,
        "semantic_invalidation_count": semantic_exit_count,
        "structure_shock_count": structure_shock_count,
        "regime_eligible_rows": int(np.count_nonzero(eligible)),
        "risk_policy_digest": risk_constitution.policy_digest,
        "venue_hosted_stop_proven": False,
    }
    return result, diagnostics


def apply_cost_aware_sizing(
    raw_target: pd.Series,
    policy: FixedSizingPolicy,
) -> tuple[pd.Series, dict[str, Any]]:
    if raw_target.empty or not isinstance(raw_target.index, pd.DatetimeIndex):
        raise RegimeConditionalSearchError("raw_target_contract_invalid")
    values = raw_target.astype(float).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    clipped = values.clip(-policy.max_abs_position, policy.max_abs_position).to_numpy()
    applied = np.zeros(len(values), dtype=float)
    current = 0.0
    last_rebalance = -policy.rebalance_interval_bars
    raw_change_count = 0
    executed_change_count = 0
    suppressed_count = 0
    previous_raw = 0.0
    for pos, desired in enumerate(clipped):
        if abs(desired - previous_raw) > 1e-12:
            raw_change_count += 1
        previous_raw = desired
        force_flat = abs(desired) <= 1e-12 and abs(current) > 1e-12
        new_entry = abs(desired) > 1e-12 and abs(current) <= 1e-12
        reversal = desired * current < 0.0
        interval_ready = pos % policy.rebalance_interval_bars == 0
        delta = abs(desired - current)
        band_ready = delta >= max(policy.no_trade_band, policy.minimum_position_delta)
        if force_flat or new_entry or reversal or (interval_ready and band_ready):
            if delta > 1e-12:
                current = float(desired)
                last_rebalance = pos
                executed_change_count += 1
        elif delta > 1e-12:
            suppressed_count += 1
        applied[pos] = current
    target = pd.Series(
        applied,
        index=values.index,
        name="fixed_policy_target_at_completed_5m_close",
    )
    return target, {
        "raw_position_change_count": raw_change_count,
        "executed_position_change_count": executed_change_count,
        "suppressed_rebalance_count": suppressed_count,
        "sizing_policy_digest": policy.policy_digest,
        "per_bar_volatility_resizing": False,
    }


def build_regime_conditional_target(
    frame: pd.DataFrame,
    genome: AlphaGenome,
    *,
    sizing_policy: FixedSizingPolicy | None = None,
    risk_constitution: FixedRiskConstitution | None = None,
) -> tuple[pd.Series, dict[str, Any]]:
    sizing = sizing_policy or FixedSizingPolicy()
    risk = risk_constitution or FixedRiskConstitution()
    events = build_alpha_events(frame, genome)
    direction, state_diagnostics = build_position_path_from_events(
        frame,
        events,
        genome,
        risk,
    )
    # Alpha selection uses a standardized 1x direction.  Confidence is retained
    # as research evidence but does not cause five-minute volatility resizing.
    target, sizing_diagnostics = apply_cost_aware_sizing(direction, sizing)
    target.attrs["regime_eligible"] = events["regime_eligible"].copy()
    target.attrs["hypothesis_family"] = genome.hypothesis_family
    return target, {
        **state_diagnostics,
        **sizing_diagnostics,
        "alpha_genome_hash": genome.genome_hash,
        "hypothesis_family": genome.hypothesis_family,
        "confidence_used_for_position_scaling": False,
        "fixed_1x_alpha_selection": True,
    }


def simulate_regime_conditional_next_open(
    frame: pd.DataFrame,
    target_at_close: pd.Series,
    *,
    start: int = 0,
    end: int | None = None,
    cost_bps: float = 10.0,
    risk_constitution: FixedRiskConstitution | None = None,
    regime_eligible_at_close: pd.Series | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Event-driven next-open simulation with a fill/position/cash ledger.

    The fixed loss constitution is evaluated from normalized cash/equity.  It
    may flatten or pause the path, but it is never a searchable gene.
    """

    _require_ohlcv(frame)
    risk = risk_constitution or FixedRiskConstitution()
    if not math.isfinite(float(cost_bps)) or cost_bps < 0.0:
        raise RegimeConditionalSearchError("cost_bps_invalid")
    end = len(frame) if end is None else int(end)
    start = int(start)
    if start < 0 or end > len(frame) or end <= start:
        raise RegimeConditionalSearchError("simulation_slice_invalid")

    index = frame.index
    opens = frame["open"].astype(float).to_numpy()
    closes = frame["close"].astype(float).to_numpy()
    target = target_at_close.reindex(index).fillna(0.0).astype(float).to_numpy()
    eligible_source = regime_eligible_at_close
    if eligible_source is None:
        candidate = target_at_close.attrs.get("regime_eligible")
        if isinstance(candidate, pd.Series):
            eligible_source = candidate
    if eligible_source is None:
        eligible = np.abs(target) > 1e-12
    else:
        eligible = (
            eligible_source.reindex(index).fillna(False).astype(bool).to_numpy()
        )

    rows = end - start
    positions = np.zeros(rows, dtype=float)
    gross = np.zeros(rows, dtype=float)
    costs = np.zeros(rows, dtype=float)
    net = np.zeros(rows, dtype=float)
    turnover_values = np.zeros(rows, dtype=float)
    equity_curve = np.ones(rows, dtype=float)
    cash_curve = np.ones(rows, dtype=float)

    previous_position = 0.0
    equity = 1.0
    cash = 1.0
    peak = 1.0
    current_day: object | None = None
    day_start_equity = 1.0
    daily_pause_remaining = 0
    strategy_loss_locked = False
    strategy_loss_lock_count = 0
    daily_pause_count = 0
    risk_forced_flatten_count = 0
    fill_count = 0
    bankruptcy = False
    fill_samples: list[dict[str, Any]] = []
    bet_returns: list[float] = []
    bet_equity = 1.0
    bet_open = False

    for local, pos in enumerate(range(start, end)):
        timestamp = index[pos]
        day = timestamp.date()
        if current_day != day:
            current_day = day
            day_start_equity = equity

        desired = float(target[pos - 1]) if pos > 0 else 0.0
        desired = float(np.clip(desired, -risk.max_abs_position, risk.max_abs_position))
        if strategy_loss_locked or daily_pause_remaining > 0:
            if abs(previous_position) > 1e-12 and abs(desired) > 1e-12:
                risk_forced_flatten_count += 1
            desired = 0.0
        if daily_pause_remaining > 0:
            daily_pause_remaining -= 1

        turnover = abs(desired - previous_position)
        turnover_values[local] = turnover
        side_changed = desired * previous_position < 0.0
        closing_bet = bet_open and (abs(desired) <= 1e-12 or side_changed)
        if closing_bet:
            bet_returns.append(bet_equity - 1.0)
            bet_equity = 1.0
            bet_open = False
        if turnover > 1e-12:
            fill_count += 1
            if len(fill_samples) < 5:
                fill_samples.append(
                    {
                        "execution_time": timestamp.isoformat(),
                        "decision_time": index[pos - 1].isoformat() if pos > 0 else None,
                        "execution_price": _round(opens[pos]),
                        "from_position": _round(previous_position),
                        "to_position": _round(desired),
                    }
                )
        if abs(desired) > 1e-12 and not bet_open:
            bet_open = True
            bet_equity = 1.0

        positions[local] = desired
        costs[local] = turnover * float(cost_bps) / 10_000.0
        if pos < end - 1:
            price_return = opens[pos + 1] / opens[pos] - 1.0
        else:
            price_return = closes[pos] / opens[pos] - 1.0
        gross[local] = desired * price_return
        net[local] = gross[local] - costs[local]

        if local == rows - 1 and abs(desired) > 1e-12:
            terminal_turnover = abs(desired)
            turnover_values[local] += terminal_turnover
            terminal_cost = terminal_turnover * float(cost_bps) / 10_000.0
            costs[local] += terminal_cost
            net[local] -= terminal_cost
            fill_count += 1

        if bet_open:
            bet_equity *= max(0.0, 1.0 + net[local])
        if net[local] <= -0.999999:
            equity = 0.0
            bankruptcy = True
        else:
            equity *= 1.0 + net[local]
        cash *= 1.0 - costs[local]
        equity_curve[local] = equity
        cash_curve[local] = cash
        peak = max(peak, equity)

        if (
            not strategy_loss_locked
            and equity <= 1.0 - risk.max_strategy_loss_pct
        ):
            strategy_loss_locked = True
            strategy_loss_lock_count += 1
        if (
            daily_pause_remaining == 0
            and day_start_equity > 0.0
            and equity / day_start_equity - 1.0 <= -risk.daily_loss_limit_pct
        ):
            daily_pause_remaining = risk.daily_pause_bars
            daily_pause_count += 1
        previous_position = desired

    if bet_open:
        bet_returns.append(bet_equity - 1.0)

    slice_index = index[start:end]
    metrics = _metrics_from_ledger(
        index=slice_index,
        positions=positions,
        gross=gross,
        net=net,
        equity=equity_curve,
        turnover=turnover_values,
        costs=costs,
        bet_returns=bet_returns,
        fill_count=fill_count,
        eligible_rows=int(np.count_nonzero(eligible[start:end])),
        strategy_loss_lock_count=strategy_loss_lock_count,
        daily_pause_count=daily_pause_count,
        risk_forced_flatten_count=risk_forced_flatten_count,
        bankruptcy=bankruptcy,
    )
    ledger = _ledger_summary(
        index=slice_index,
        positions=positions,
        gross=gross,
        net=net,
        equity=equity_curve,
        cash=cash_curve,
        costs=costs,
        fill_count=fill_count,
        fill_samples=fill_samples,
        risk_policy_digest=risk.policy_digest,
    )
    return metrics, ledger


def classify_fold_evidence(
    metrics: Mapping[str, Any],
    *,
    min_regime_rows: int = DEFAULT_MIN_REGIME_ROWS,
    min_independent_bets: int = DEFAULT_MIN_INDEPENDENT_BETS,
) -> dict[str, Any]:
    eligible_rows = int(metrics.get("regime_eligible_rows", 0))
    independent_bets = int(metrics.get("independent_bet_count", 0))
    effective_bets = float(metrics.get("effective_bet_count", 0.0))
    if eligible_rows < min_regime_rows or independent_bets < min_independent_bets:
        reasons: list[str] = []
        if eligible_rows < min_regime_rows:
            reasons.append("regime_evidence_rows_below_preregistered_minimum")
        if independent_bets < min_independent_bets:
            reasons.append("independent_bets_below_preregistered_minimum")
        return {
            "status": "not_applicable_insufficient_regime_evidence",
            "performance_gate_applied": False,
            "passed": None,
            "reasons": reasons,
        }

    reasons = []
    if float(metrics.get("total_return", 0.0)) <= 0.0:
        reasons.append("total_return_non_positive")
    if float(metrics.get("profit_factor", 0.0)) < 1.05:
        reasons.append("profit_factor_below_1p05")
    if float(metrics.get("max_drawdown", -1.0)) < -0.20:
        reasons.append("max_drawdown_below_minus_20pct")
    if effective_bets < max(1.0, min_independent_bets * 0.60):
        reasons.append("effective_bets_below_preregistered_minimum")
    if bool(metrics.get("bankruptcy")):
        reasons.append("bankruptcy")
    return {
        "status": "pass" if not reasons else "fail",
        "performance_gate_applied": True,
        "passed": not reasons,
        "reasons": reasons,
    }


def _metrics_from_ledger(
    *,
    index: pd.DatetimeIndex,
    positions: np.ndarray,
    gross: np.ndarray,
    net: np.ndarray,
    equity: np.ndarray,
    turnover: np.ndarray,
    costs: np.ndarray,
    bet_returns: Sequence[float],
    fill_count: int,
    eligible_rows: int,
    strategy_loss_lock_count: int,
    daily_pause_count: int,
    risk_forced_flatten_count: int,
    bankruptcy: bool,
) -> dict[str, Any]:
    total_return = float(equity[-1] - 1.0) if len(equity) else 0.0
    periods = max(len(index), 1)
    annualized_log_return = (
        math.log(max(float(equity[-1]), 1e-12)) * ANNUAL_5M_BARS / periods
        if len(equity)
        else 0.0
    )
    annualized_return = math.expm1(float(np.clip(annualized_log_return, -50.0, 50.0)))
    annualized_volatility = (
        float(np.std(net, ddof=0) * math.sqrt(ANNUAL_5M_BARS)) if len(net) else 0.0
    )
    sharpe = (
        float(np.mean(net) / np.std(net, ddof=0) * math.sqrt(ANNUAL_5M_BARS))
        if len(net) and np.std(net, ddof=0) > 0.0
        else 0.0
    )
    equity_with_start = np.concatenate(([1.0], equity))
    peaks = np.maximum.accumulate(equity_with_start)
    max_drawdown = float(np.min(equity_with_start / peaks - 1.0))
    positive = float(net[net > 0.0].sum())
    negative = float(-net[net < 0.0].sum())
    profit_factor = positive / negative if negative > 0.0 else (999.0 if positive > 0.0 else 0.0)
    bets = np.asarray(list(bet_returns), dtype=float)
    independent_bet_count = int(len(bets))
    effective_bets = _effective_sample_size(bets)
    mean_bet = float(np.mean(bets)) if len(bets) else 0.0
    bet_std = float(np.std(bets, ddof=1)) if len(bets) > 1 else 0.0
    standard_error = bet_std / math.sqrt(max(effective_bets, 1.0)) if bet_std > 0.0 else 0.0
    lower_95 = mean_bet - 1.645 * standard_error
    active = np.abs(positions) > 1e-12
    return {
        "start": index[0].isoformat() if len(index) else None,
        "end": index[-1].isoformat() if len(index) else None,
        "row_count": len(index),
        "total_return": _round(total_return),
        "annualized_return": _round(annualized_return),
        "annualized_volatility": _round(annualized_volatility),
        "sharpe": _round(sharpe),
        "profit_factor": _round(profit_factor),
        "max_drawdown": _round(max_drawdown),
        "turnover": _round(float(turnover.sum())),
        "cost_drag": _round(float(costs.sum())),
        "fill_count": int(fill_count),
        "independent_bet_count": independent_bet_count,
        "effective_bet_count": _round(effective_bets),
        "mean_bet_return": _round(mean_bet),
        "bet_return_std": _round(bet_std),
        "bet_return_lower_95": _round(lower_95),
        "turnover_per_independent_bet": _round(
            float(turnover.sum()) / max(independent_bet_count, 1)
        ),
        "cost_drag_per_independent_bet": _round(
            float(costs.sum()) / max(independent_bet_count, 1)
        ),
        "regime_eligible_rows": int(eligible_rows),
        "regime_coverage_ratio": _round(eligible_rows / max(len(index), 1)),
        "exposure_ratio": _round(float(active.mean()) if len(active) else 0.0),
        "long_exposure_ratio": _round(float((positions > 1e-12).mean()) if len(positions) else 0.0),
        "short_exposure_ratio": _round(float((positions < -1e-12).mean()) if len(positions) else 0.0),
        "max_absolute_position": _round(float(np.max(np.abs(positions))) if len(positions) else 0.0),
        "strategy_loss_lock_count": int(strategy_loss_lock_count),
        "daily_pause_count": int(daily_pause_count),
        "risk_forced_flatten_count": int(risk_forced_flatten_count),
        "bankruptcy": bool(bankruptcy),
    }


def _ledger_summary(
    *,
    index: pd.DatetimeIndex,
    positions: np.ndarray,
    gross: np.ndarray,
    net: np.ndarray,
    equity: np.ndarray,
    cash: np.ndarray,
    costs: np.ndarray,
    fill_count: int,
    fill_samples: Sequence[Mapping[str, Any]],
    risk_policy_digest: str,
) -> dict[str, Any]:
    digest_payload = {
        "start": index[0].isoformat() if len(index) else None,
        "end": index[-1].isoformat() if len(index) else None,
        "rows": len(index),
        "position_sha256": hashlib.sha256(np.asarray(positions, dtype="<f8").tobytes()).hexdigest(),
        "net_sha256": hashlib.sha256(np.asarray(net, dtype="<f8").tobytes()).hexdigest(),
        "equity_sha256": hashlib.sha256(np.asarray(equity, dtype="<f8").tobytes()).hexdigest(),
        "cash_sha256": hashlib.sha256(np.asarray(cash, dtype="<f8").tobytes()).hexdigest(),
        "fill_count": int(fill_count),
        "risk_policy_digest": risk_policy_digest,
    }
    return {
        "model": "event_fill_position_cash_normalized_equity_next_open_v2",
        "pnl_derived_from_fills_positions_cash": True,
        "signal_at_completed_close_execution_at_next_open": True,
        "reconciled": bool(
            len(positions) == len(net) == len(equity) == len(cash) == len(index)
            and np.isfinite(net).all()
            and np.isfinite(equity).all()
            and np.isfinite(cash).all()
        ),
        "position_ledger_row_count": len(positions),
        "cash_ledger_row_count": len(cash),
        "fill_count": int(fill_count),
        "ending_equity": _round(float(equity[-1]) if len(equity) else 1.0),
        "ending_cost_cash": _round(float(cash[-1]) if len(cash) else 1.0),
        "gross_return_sum": _round(float(gross.sum())),
        "cost_return_sum": _round(float(costs.sum())),
        "fill_samples_first": [dict(row) for row in fill_samples],
        "full_ledger_committed": False,
        "full_ledger_omission_reason": "large_research_ledger_not_committed_hash_counts_and_samples_only",
        "ledger_sha256": hashlib.sha256(_stable_json(digest_payload).encode("utf-8")).hexdigest(),
        "risk_policy_digest": risk_policy_digest,
    }


def run_regime_conditional_search_on_frame(
    *,
    frame: pd.DataFrame,
    data_provenance: Mapping[str, Any],
    output_root: Path,
    seed: int = DEFAULT_SEED,
    population_size: int = 48,
    generations: int = 12,
    fold_count: int = 4,
    holdout_fraction: float = 0.20,
    max_candidates: int = 3,
    prior_shared_tail_exposure: bool = True,
    search_round_count: int = 1,
    prior_search_unique_evaluations: int = 0,
    frozen_unseen_holdout_start_utc: datetime | None = None,
    prior_research_cutoff_utc: datetime | None = None,
    experiment_id: str = DEFAULT_EXPERIMENT_ID,
    generated_at_utc: datetime | None = None,
    sizing_policy: FixedSizingPolicy | None = None,
    risk_constitution: FixedRiskConstitution | None = None,
) -> dict[str, Any]:
    _require_ohlcv(frame)
    if len(frame) < 8_000:
        raise RegimeConditionalSearchError("five_minute_rows_insufficient")
    if population_size < 8 or generations < 1 or fold_count < 2:
        raise RegimeConditionalSearchError("search_configuration_too_small")
    if max_candidates < 1 or search_round_count < 1 or prior_search_unique_evaluations < 0:
        raise RegimeConditionalSearchError("search_history_or_candidate_count_invalid")
    if not experiment_id or any(
        character not in "abcdefghijklmnopqrstuvwxyz0123456789-"
        for character in experiment_id
    ):
        raise RegimeConditionalSearchError("experiment_id_invalid")

    sizing = sizing_policy or FixedSizingPolicy()
    risk = risk_constitution or FixedRiskConstitution()
    generated = (generated_at_utc or datetime.now(timezone.utc)).astimezone(timezone.utc)
    frozen_mode = (
        frozen_unseen_holdout_start_utc is not None
        or prior_research_cutoff_utc is not None
    )
    if frozen_mode and (
        frozen_unseen_holdout_start_utc is None
        or prior_research_cutoff_utc is None
    ):
        raise RegimeConditionalSearchError("frozen_unseen_boundary_pair_required")

    lock_path: Path | None = None
    prior_cutoff: pd.Timestamp | None = None
    holdout_start: pd.Timestamp | None = None
    if frozen_mode:
        if prior_shared_tail_exposure:
            raise RegimeConditionalSearchError("frozen_unseen_prior_exposure_must_be_false")
        if max_candidates != 1:
            raise RegimeConditionalSearchError("frozen_unseen_requires_single_candidate")
        prior_cutoff = _as_utc_timestamp(prior_research_cutoff_utc, "prior_research_cutoff")
        holdout_start = _as_utc_timestamp(
            frozen_unseen_holdout_start_utc,
            "frozen_unseen_holdout_start",
        )
        if holdout_start - prior_cutoff != pd.Timedelta(minutes=5):
            raise RegimeConditionalSearchError("frozen_unseen_boundary_not_contiguous")
        cutoff_hits = np.flatnonzero(frame.index == prior_cutoff)
        holdout_hits = np.flatnonzero(frame.index == holdout_start)
        if len(cutoff_hits) != 1 or len(holdout_hits) != 1:
            raise RegimeConditionalSearchError("frozen_unseen_boundary_missing")
        if int(holdout_hits[0]) != int(cutoff_hits[0]) + 1:
            raise RegimeConditionalSearchError("frozen_unseen_boundary_not_adjacent")
        selection_end = int(holdout_hits[0])
        if len(frame) - selection_end < MIN_UNSEEN_HOLDOUT_ROWS:
            raise RegimeConditionalSearchError("frozen_unseen_rows_insufficient")
        try:
            output_root.mkdir(parents=True, exist_ok=False)
        except FileExistsError as exc:
            raise RegimeConditionalSearchError(
                "frozen_unseen_output_root_must_be_new"
            ) from exc
        lock_path = output_root / "btc_5m_regime_conditional_candidate_lock.json"
    else:
        if not 0.10 <= holdout_fraction <= 0.35:
            raise RegimeConditionalSearchError("holdout_fraction_invalid")
        selection_end = int(len(frame) * (1.0 - holdout_fraction))
        output_root.mkdir(parents=True, exist_ok=True)

    selection_frame = frame.iloc[:selection_end]
    maximum_lookback = max(
        max(pair[1] for pair in STATE_PAIRS),
        max(ENTRY_WINDOWS),
        max(ATR_WINDOWS) * 4,
    )
    folds = build_walk_forward_folds(
        selection_end,
        fold_count=fold_count,
        embargo_bars=maximum_lookback,
    )
    if len(folds) != fold_count:
        raise RegimeConditionalSearchError("walk_forward_fold_construction_failed")

    rng = random.Random(int(seed))
    cache: dict[str, dict[str, Any]] = {}
    population = _initial_population(rng, population_size)
    generation_trace: list[dict[str, Any]] = []
    for generation in range(1, generations + 1):
        evaluated = [
            _evaluate_candidate(
                frame=selection_frame,
                genome=genome,
                folds=folds,
                cache=cache,
                sizing_policy=sizing,
                risk_constitution=risk,
            )
            for genome in population
        ]
        cumulative_trials = prior_search_unique_evaluations + len(cache)
        _assign_pareto_ranks(evaluated, cumulative_trials=cumulative_trials)
        evaluated.sort(key=_selection_sort_key)
        generation_trace.append(
            {
                "generation": generation,
                "pareto_front_size": sum(
                    int(int(row.get("pareto_rank", 999)) == 0) for row in evaluated
                ),
                "best_candidate_id": evaluated[0]["genome"].candidate_id,
                "best_deflated_mean_bet_return": _mapping(
                    evaluated[0].get("multiple_testing")
                ).get("deflated_mean_bet_return", 0.0),
                "unique_evaluations": len(cache),
            }
        )
        elite_count = max(2, population_size // 8)
        next_population = [row["genome"] for row in evaluated[:elite_count]]
        while len(next_population) < population_size:
            left = _tournament(evaluated, rng)
            right = _tournament(evaluated, rng)
            next_population.append(_mutate(_crossover(left, right, rng), rng))
        population = _dedupe_and_fill(next_population, rng, population_size)

    evaluated_all = list(cache.values())
    _assign_pareto_ranks(
        evaluated_all,
        cumulative_trials=prior_search_unique_evaluations + len(cache),
    )
    evaluated_all.sort(key=_selection_sort_key)

    # Parameter-platform evidence is evaluated outside the genome fitness.  A
    # small deterministic local neighborhood is tested for the provisional
    # leaders, then every row is re-ranked with the expanded trial count.
    provisional = evaluated_all[:max_candidates]
    for row in provisional:
        row["parameter_neighborhood_stability"] = evaluate_parameter_neighborhood_stability(
            frame=selection_frame,
            selection=row,
            folds=folds,
            cache=cache,
            sizing_policy=sizing,
            risk_constitution=risk,
        )
    evaluated_all = list(cache.values())
    _assign_pareto_ranks(
        evaluated_all,
        cumulative_trials=prior_search_unique_evaluations + len(cache),
    )
    evaluated_all.sort(key=_selection_sort_key)
    top_selection = evaluated_all[:max_candidates]
    for row in top_selection:
        if _mapping(row.get("parameter_neighborhood_stability")).get(
            "status"
        ) == "not_yet_evaluated":
            row["parameter_neighborhood_stability"] = evaluate_parameter_neighborhood_stability(
                frame=selection_frame,
                selection=row,
                folds=folds,
                cache=cache,
                sizing_policy=sizing,
                risk_constitution=risk,
            )
    final_trials = prior_search_unique_evaluations + len(cache)
    _assign_pareto_ranks(list(cache.values()), cumulative_trials=final_trials)
    top_selection.sort(key=_selection_sort_key)

    candidate_rows: list[dict[str, Any]] = []
    holdout_revealed = False
    candidate_lock: dict[str, Any] | None = None
    lock_file_sha256: str | None = None
    if frozen_mode:
        selection = top_selection[0]
        selection_reasons = _selection_gate_reasons(
            selection=selection,
            fold_count=fold_count,
        )
        candidate_lock = _build_candidate_lock(
            experiment_id=experiment_id,
            generated=generated,
            data_provenance=data_provenance,
            selection_frame=selection_frame,
            selection_end=selection_end,
            prior_cutoff=prior_cutoff,
            holdout_start=holdout_start,
            selection=selection,
            folds=folds,
            seed=seed,
            population_size=population_size,
            generations=generations,
            search_round_count=search_round_count,
            prior_search_unique_evaluations=prior_search_unique_evaluations,
            final_unique_evaluations=len(cache),
            sizing_policy=sizing,
            risk_constitution=risk,
            selection_reasons=selection_reasons,
        )
        assert lock_path is not None
        _write_json(lock_path, candidate_lock)
        lock_file_sha256 = _sha256_file(lock_path)

        holdout_costs: dict[str, Any] = {}
        holdout_ledger: dict[str, Any] = {}
        holdout_reasons: list[str]
        if not selection_reasons:
            target, target_diagnostics = build_regime_conditional_target(
                frame,
                selection["genome"],
                sizing_policy=sizing,
                risk_constitution=risk,
            )
            eligible_series = target.attrs.get("regime_eligible")
            for scenario in COST_SCENARIOS:
                metrics, ledger = simulate_regime_conditional_next_open(
                    frame,
                    target,
                    start=selection_end,
                    end=len(frame),
                    cost_bps=scenario.total_bps,
                    risk_constitution=risk,
                    regime_eligible_at_close=(
                        eligible_series if isinstance(eligible_series, pd.Series) else None
                    ),
                )
                holdout_costs[scenario.name] = metrics
                if scenario.name == "base":
                    holdout_ledger = ledger
            holdout_revealed = True
            holdout_reasons = _holdout_gate_reasons(holdout_costs)
        else:
            target_diagnostics = {}
            holdout_reasons = ["unseen_holdout_not_revealed_selection_gate_failed"]
        candidate_rows.append(
            _public_candidate(
                selection,
                rank=1,
                holdout_key="frozen_unseen_holdout",
                holdout={
                    "status": "consumed_once" if holdout_revealed else "preserved_unseen",
                    "start": frame.index[selection_end].isoformat(),
                    "end": frame.index[-1].isoformat(),
                    "row_count": len(frame) - selection_end,
                    "candidate_count_revealed": 1 if holdout_revealed else 0,
                    "cost_scenarios": holdout_costs if holdout_revealed else None,
                    "base_ledger": holdout_ledger if holdout_revealed else None,
                    "target_diagnostics": target_diagnostics if holdout_revealed else None,
                    "reasons": holdout_reasons,
                },
            )
        )
        all_reasons = [*selection_reasons, *holdout_reasons]
        if selection_reasons:
            decision = "reject_selection_batch_holdout_not_revealed"
        elif holdout_reasons:
            decision = "reject_locked_candidate_after_single_unseen_holdout"
        else:
            decision = "retain_research_hypothesis_execution_evidence_still_required"
        retained_count = int(not all_reasons)
    else:
        for rank, selection in enumerate(top_selection, start=1):
            target, target_diagnostics = build_regime_conditional_target(
                frame,
                selection["genome"],
                sizing_policy=sizing,
                risk_constitution=risk,
            )
            eligible_series = target.attrs.get("regime_eligible")
            holdout_costs = {}
            holdout_ledger = {}
            for scenario in COST_SCENARIOS:
                metrics, ledger = simulate_regime_conditional_next_open(
                    frame,
                    target,
                    start=selection_end,
                    end=len(frame),
                    cost_bps=scenario.total_bps,
                    risk_constitution=risk,
                    regime_eligible_at_close=(
                        eligible_series if isinstance(eligible_series, pd.Series) else None
                    ),
                )
                holdout_costs[scenario.name] = metrics
                if scenario.name == "base":
                    holdout_ledger = ledger
            reasons = [
                *_selection_gate_reasons(selection=selection, fold_count=fold_count),
                "diagnostic_tail_previously_available_not_confirmatory",
                *_holdout_gate_reasons(holdout_costs),
            ]
            candidate_rows.append(
                _public_candidate(
                    selection,
                    rank=rank,
                    holdout_key="diagnostic_holdout",
                    holdout={
                        "status": "diagnostic_previously_available",
                        "start": frame.index[selection_end].isoformat(),
                        "end": frame.index[-1].isoformat(),
                        "row_count": len(frame) - selection_end,
                        "candidate_count_revealed": len(top_selection),
                        "cost_scenarios": holdout_costs,
                        "base_ledger": holdout_ledger,
                        "target_diagnostics": target_diagnostics,
                        "reasons": reasons,
                    },
                )
            )
        decision = "diagnostic_research_only_existing_tail_not_confirmatory"
        retained_count = 0

    validation_design = {
        "completed_bar_decisions": True,
        "next_open_execution": True,
        "walk_forward_fold_count": fold_count,
        "walk_forward_folds": [fold.to_dict(selection_frame.index) for fold in folds],
        "embargo_bars": maximum_lookback,
        "embargo_equals_or_exceeds_maximum_lookback": True,
        "selection_start": selection_frame.index[0].isoformat(),
        "selection_end": selection_frame.index[-1].isoformat(),
        "selection_rows": selection_end,
        "holdout_start": frame.index[selection_end].isoformat(),
        "holdout_end": frame.index[-1].isoformat(),
        "holdout_rows": len(frame) - selection_end,
        "holdout_used_for_selection": False,
        "holdout_revealed": holdout_revealed if frozen_mode else True,
        "holdout_candidate_count_revealed": (
            1 if frozen_mode and holdout_revealed else (0 if frozen_mode else len(top_selection))
        ),
        "holdout_exposure_after_run": (
            "consumed_once"
            if frozen_mode and holdout_revealed
            else "preserved_unseen"
            if frozen_mode
            else "diagnostic_previously_available"
        ),
        "holdout_reuse_for_tuning_allowed": False,
        "single_candidate_lock_required_before_unseen_reveal": True,
    }
    search_protocol = {
        "selection_method": "deterministic_pareto_genetic_search",
        "fitness_is_single_weighted_scalar": False,
        "seed": int(seed),
        "population_size": population_size,
        "generations": generations,
        "selection": "four_way_tournament_by_pareto_rank_then_preregistered_tiebreak",
        "elite_fraction": "1/8",
        "gene_crossover": "fieldwise_with_state_pair_atomic",
        "mutation": "one_or_two_alpha_fields_only",
        "hypothesis_families": list(HYPOTHESIS_FAMILIES),
        "safety_parameters_in_genome": False,
        "sizing_parameters_in_genome": False,
        "cost_scenarios_used_in_selection": [scenario.to_dict() for scenario in COST_SCENARIOS],
        "fold_gate_uses_trades_per_day": False,
        "fold_gate_uses_independent_bets_and_effective_sample": True,
        "parameter_neighborhood_required": True,
        "multiple_testing_adjustment": "expected_maximum_normal_haircut_by_cumulative_unique_trials",
        "run_unique_evaluations": len(cache),
        "prior_unique_evaluations": prior_search_unique_evaluations,
        "cumulative_unique_evaluations": final_trials,
        "search_round_count": search_round_count,
        "generation_trace": generation_trace,
        "gene_space": _gene_space(),
    }
    candidate_lock_public = {
        "path": lock_path.name if lock_path is not None else None,
        "semantic_sha256": (
            candidate_lock.get("semantic_sha256") if candidate_lock is not None else None
        ),
        "file_sha256": lock_file_sha256,
        "reveal_authorized": bool(
            candidate_lock.get("reveal_authorized") if candidate_lock else False
        ),
        "written_before_reveal": bool(candidate_lock is not None),
    }
    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "experiment_id": experiment_id,
        "generated_at": generated.isoformat(),
        "status": "complete_research_only",
        "decision": decision,
        "code_commit": _git_commit_hash(),
        "data_provenance": dict(data_provenance),
        "data_consumption": {
            "selection_rows_used_for_search": selection_end,
            "unseen_rows_used_for_search": 0,
            "unseen_strategy_metrics_read": bool(frozen_mode and holdout_revealed),
            "immutable_payload_may_be_streamed_for_integrity_before_gate": True,
            "public_network_called": False,
            "mutable_sqlite_consumed": False,
        },
        "architecture": {
            "alpha_state_entry_exit_separated_from_sizing_and_risk": True,
            "alpha_contract": "hypothesis_to_regime_to_entry_to_semantic_invalidation",
            "sizing_contract": sizing.to_dict(),
            "risk_constitution": risk.to_dict(),
            "oms_or_strategy_registry_modified": False,
        },
        "search_protocol": search_protocol,
        "validation_design": validation_design,
        "candidate_lock": candidate_lock_public,
        "top_candidates": candidate_rows,
        "retained_research_candidate_count": retained_count,
        "promotion": {
            "research_only": True,
            "demo_strategy_registration_allowed": False,
            "paper_auto_start": False,
            "promotion_ready": False,
            "live_enabled": False,
        },
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
            "research_only_no_runtime_or_oms_adapter",
            "fixed_bps_costs_do_not_prove_l2_queue_latency_funding_or_liquidation",
            "completed_bar_hard_stop_proxy_is_not_venue_hosted_protection",
            "promotion_paper_live_require_separate_current_head_evidence_and_human_gate",
        ],
    }
    report["artifact_hash"] = hashlib.sha256(
        _stable_json(report).encode("utf-8")
    ).hexdigest()
    definitions = {
        "schema_version": "btc_5m_regime_conditional_candidate_definitions_v1",
        "experiment_id": experiment_id,
        "code_commit": report["code_commit"],
        "artifact_hash": report["artifact_hash"],
        "candidates": [
            {
                "rank": row["rank"],
                "candidate_id": row["candidate_id"],
                "alpha_genome": row["alpha_genome"],
                "research_only": True,
            }
            for row in candidate_rows
        ],
        "demo_strategy_registration_allowed": False,
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
        "private_endpoints_allowed": False,
        "order_endpoints_allowed": False,
    }
    _write_json(output_root / "btc_5m_regime_conditional_alpha_search_report.json", report)
    _write_json(
        output_root / "btc_5m_regime_conditional_candidate_definitions.json",
        definitions,
    )
    _write_text(
        output_root / "btc_5m_regime_conditional_alpha_search_summary_cn.md",
        render_regime_conditional_summary(report),
    )
    return report


def run_btc_regime_conditional_5m_alpha_search(
    *,
    repo_root: Path | None = None,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    seed: int = DEFAULT_SEED,
    population_size: int = 48,
    generations: int = 12,
    fold_count: int = 4,
    holdout_fraction: float = 0.20,
    max_candidates: int = 3,
    prior_shared_tail_exposure: bool = True,
    search_round_count: int = 1,
    prior_search_unique_evaluations: int = 0,
    frozen_unseen_holdout_start_utc: datetime | None = None,
    prior_research_cutoff_utc: datetime | None = None,
    experiment_id: str = DEFAULT_EXPERIMENT_ID,
    generated_at_utc: datetime | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    try:
        frame, provenance = load_committed_5m_market_frame(repo_root=root)
    except Exception as exc:
        if isinstance(exc, RegimeConditionalSearchError):
            raise
        raise RegimeConditionalSearchError(
            f"immutable_5m_dataset_unavailable:{type(exc).__name__}:{exc}"
        ) from exc
    return run_regime_conditional_search_on_frame(
        frame=frame,
        data_provenance=provenance,
        output_root=output_root,
        seed=seed,
        population_size=population_size,
        generations=generations,
        fold_count=fold_count,
        holdout_fraction=holdout_fraction,
        max_candidates=max_candidates,
        prior_shared_tail_exposure=prior_shared_tail_exposure,
        search_round_count=search_round_count,
        prior_search_unique_evaluations=prior_search_unique_evaluations,
        frozen_unseen_holdout_start_utc=frozen_unseen_holdout_start_utc,
        prior_research_cutoff_utc=prior_research_cutoff_utc,
        experiment_id=experiment_id,
        generated_at_utc=generated_at_utc,
    )


def run_regime_conditional_neighborhood_correction_on_frame(
    *,
    frame: pd.DataFrame,
    data_provenance: Mapping[str, Any],
    source_report: Mapping[str, Any],
    source_lock: Mapping[str, Any],
    source_report_file_sha256: str,
    source_lock_file_sha256: str,
    output_root: Path,
    generated_at_utc: datetime | None = None,
) -> dict[str, Any]:
    """Complete the missing selection-only neighborhood evidence.

    This correction can never reveal or evaluate the unseen holdout.  Even if
    the corrected selection gate were to pass, a separate pre-authorized run
    would be required to consume the tail.
    """

    _require_ohlcv(frame)
    if source_report.get("schema_version") != SCHEMA_VERSION:
        raise RegimeConditionalSearchError("correction_source_report_schema_invalid")
    if source_lock.get("schema_version") != CANDIDATE_LOCK_SCHEMA_VERSION:
        raise RegimeConditionalSearchError("correction_source_lock_schema_invalid")
    source_report_semantic = dict(source_report)
    source_report_artifact_hash = source_report_semantic.pop("artifact_hash", None)
    if (
        not _is_sha256(source_report_artifact_hash)
        or hashlib.sha256(
            _stable_json(source_report_semantic).encode("utf-8")
        ).hexdigest()
        != source_report_artifact_hash
    ):
        raise RegimeConditionalSearchError("correction_source_report_semantic_hash_mismatch")
    source_lock_semantic = dict(source_lock)
    source_lock_semantic_hash = source_lock_semantic.pop("semantic_sha256", None)
    if (
        not _is_sha256(source_lock_semantic_hash)
        or hashlib.sha256(_stable_json(source_lock_semantic).encode("utf-8")).hexdigest()
        != source_lock_semantic_hash
    ):
        raise RegimeConditionalSearchError("correction_source_lock_semantic_hash_mismatch")
    validation = _mapping(source_report.get("validation_design"))
    source_lock_summary = _mapping(source_report.get("candidate_lock"))
    if (
        validation.get("holdout_exposure_after_run") != "preserved_unseen"
        or bool(validation.get("holdout_revealed"))
        or int(validation.get("holdout_candidate_count_revealed", 0)) != 0
        or bool(source_lock_summary.get("reveal_authorized"))
        or bool(source_lock.get("reveal_authorized"))
    ):
        raise RegimeConditionalSearchError("correction_requires_preserved_unseen_source")
    if (
        source_lock_summary.get("semantic_sha256") != source_lock.get("semantic_sha256")
        or source_lock_summary.get("file_sha256") != source_lock_file_sha256
    ):
        raise RegimeConditionalSearchError("correction_source_lock_hash_mismatch")
    if not _is_sha256(source_report_file_sha256) or not _is_sha256(
        source_lock_file_sha256
    ):
        raise RegimeConditionalSearchError("correction_source_file_hash_invalid")
    source_data = _mapping(source_report.get("data_provenance"))
    binding_fields = (
        "dataset_version",
        "selector_sha256",
        "manifest_git_sha256",
        "physical_manifest_sha256",
        "aggregate_sha256",
        "five_minute_file_sha256",
        "source_sha256",
        "resolved_row_count",
    )
    mismatches = [
        key
        for key in binding_fields
        if source_data.get(key) != data_provenance.get(key)
    ]
    if mismatches:
        raise RegimeConditionalSearchError(
            "correction_immutable_data_binding_mismatch:" + ",".join(mismatches)
        )
    candidates = source_report.get("top_candidates")
    if not isinstance(candidates, list) or len(candidates) != 1:
        raise RegimeConditionalSearchError("correction_requires_one_locked_candidate")
    candidate = _mapping(candidates[0])
    genome_payload = _mapping(candidate.get("alpha_genome"))
    genome_fields = {item.name for item in fields(AlphaGenome)}
    genome = AlphaGenome(
        **{name: genome_payload[name] for name in genome_fields}
    )
    if (
        genome.genome_hash != candidate.get("genome_hash")
        or genome.candidate_id != candidate.get("candidate_id")
        or genome.genome_hash
        != _mapping(source_lock.get("locked_candidate")).get("genome_hash")
    ):
        raise RegimeConditionalSearchError("correction_locked_candidate_identity_mismatch")

    selection_end = int(validation.get("selection_rows", 0))
    if selection_end <= 0 or selection_end >= len(frame):
        raise RegimeConditionalSearchError("correction_selection_boundary_invalid")
    if frame.index[selection_end - 1].isoformat() != validation.get("selection_end"):
        raise RegimeConditionalSearchError("correction_selection_end_mismatch")
    if frame.index[selection_end].isoformat() != validation.get("holdout_start"):
        raise RegimeConditionalSearchError("correction_holdout_start_mismatch")
    selection_frame = frame.iloc[:selection_end]
    fold_count = int(validation.get("walk_forward_fold_count", 0))
    embargo_bars = int(validation.get("embargo_bars", 0))
    folds = build_walk_forward_folds(
        selection_end,
        fold_count=fold_count,
        embargo_bars=embargo_bars,
    )
    expected_folds = validation.get("walk_forward_folds")
    actual_folds = [fold.to_dict(selection_frame.index) for fold in folds]
    if actual_folds != expected_folds:
        raise RegimeConditionalSearchError("correction_walk_forward_identity_mismatch")
    source_folds = candidate.get("walk_forward")
    if not isinstance(source_folds, list) or len(source_folds) != fold_count:
        raise RegimeConditionalSearchError("correction_source_fold_evidence_invalid")

    sizing = FixedSizingPolicy()
    risk = FixedRiskConstitution()
    selection: dict[str, Any] = {
        "genome": genome,
        "genome_hash": genome.genome_hash,
        "folds": [dict(row) for row in source_folds],
        "target_diagnostics": dict(_mapping(candidate.get("target_diagnostics"))),
        "parameter_neighborhood_stability": {
            "status": "not_yet_evaluated",
            "passed": False,
            "neighbor_count": 0,
        },
    }
    cache = {genome.genome_hash: selection}
    stability = evaluate_parameter_neighborhood_stability(
        frame=selection_frame,
        selection=selection,
        folds=folds,
        cache=cache,
        sizing_policy=sizing,
        risk_constitution=risk,
    )
    selection["parameter_neighborhood_stability"] = stability
    source_cumulative = int(
        _mapping(source_report.get("search_protocol")).get(
            "cumulative_unique_evaluations", 0
        )
    )
    correction_unique = len(cache) - 1
    corrected_cumulative = source_cumulative + correction_unique
    _assign_pareto_ranks([selection], cumulative_trials=corrected_cumulative)
    reasons = _selection_gate_reasons(selection=selection, fold_count=fold_count)
    generated = (generated_at_utc or datetime.now(timezone.utc)).astimezone(timezone.utc)
    try:
        output_root.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise RegimeConditionalSearchError(
            "correction_output_root_must_be_new"
        ) from exc

    correction_lock: dict[str, Any] = {
        "schema_version": "btc_5m_regime_conditional_neighborhood_correction_lock_v1",
        "generated_at": generated.isoformat(),
        "source_artifact": {
            "report_file_sha256": source_report_file_sha256,
            "report_artifact_hash": source_report.get("artifact_hash"),
            "report_code_commit": source_report.get("code_commit"),
            "candidate_lock_file_sha256": source_lock_file_sha256,
            "candidate_lock_semantic_sha256": source_lock.get("semantic_sha256"),
        },
        "locked_candidate": {
            "candidate_id": genome.candidate_id,
            "genome_hash": genome.genome_hash,
        },
        "parameter_neighborhood_stability": stability,
        "corrected_multiple_testing": dict(
            _mapping(selection.get("multiple_testing"))
        ),
        "selection_gate_reasons": reasons,
        "selection_only_correction": True,
        "unseen_holdout_strategy_metrics_read": False,
        "unseen_holdout_exposure_after_correction": "preserved_unseen",
        "reveal_authorized": False,
        "new_authorized_holdout_run_required_even_if_selection_passed": True,
        "research_only": True,
        "promotion_allowed": False,
        "paper_allowed": False,
        "live_allowed": False,
        "private_allowed": False,
        "order_allowed": False,
    }
    correction_lock["semantic_sha256"] = hashlib.sha256(
        _stable_json(correction_lock).encode("utf-8")
    ).hexdigest()
    correction_lock_path = (
        output_root / "btc_5m_regime_conditional_neighborhood_correction_lock.json"
    )
    _write_json(correction_lock_path, correction_lock)
    correction_lock_file_sha256 = _sha256_file(correction_lock_path)

    report: dict[str, Any] = {
        "schema_version": "btc_5m_regime_conditional_neighborhood_correction_v1",
        "generated_at": generated.isoformat(),
        "status": "complete_research_only",
        "decision": (
            "reject_selection_batch_holdout_not_revealed"
            if reasons
            else "selection_gate_passed_holdout_preserved_new_authorized_run_required"
        ),
        "code_commit": _git_commit_hash(),
        "source_artifact": correction_lock["source_artifact"],
        "data_provenance": dict(data_provenance),
        "selection_rows": selection_end,
        "holdout_rows": len(frame) - selection_end,
        "holdout_exposure_after_run": "preserved_unseen",
        "holdout_revealed": False,
        "holdout_candidate_count_revealed": 0,
        "holdout_strategy_metrics_read": False,
        "correction_unique_evaluations": correction_unique,
        "source_cumulative_unique_evaluations": source_cumulative,
        "corrected_cumulative_unique_evaluations": corrected_cumulative,
        "candidate": {
            "candidate_id": genome.candidate_id,
            "genome_hash": genome.genome_hash,
            "alpha_genome": genome.to_dict(),
            "parameter_neighborhood_stability": stability,
            "multiple_testing": dict(_mapping(selection.get("multiple_testing"))),
            "eligible_fold_count": int(selection.get("eligible_fold_count", 0)),
            "passed_eligible_fold_count": int(
                selection.get("passed_eligible_fold_count", 0)
            ),
            "positive_eligible_fold_count": int(
                selection.get("positive_eligible_fold_count", 0)
            ),
            "selection_reasons": reasons,
        },
        "correction_lock": {
            "path": correction_lock_path.name,
            "semantic_sha256": correction_lock["semantic_sha256"],
            "file_sha256": correction_lock_file_sha256,
            "written_before_report": True,
            "reveal_authorized": False,
        },
        "safety": {
            "public_network_called": False,
            "private_endpoints_allowed": False,
            "order_endpoints_allowed": False,
            "real_orders_created": False,
            "paper_queue_write_allowed": False,
            "transfer_allowed": False,
            "withdraw_allowed": False,
        },
        "promotion": {
            "research_only": True,
            "demo_strategy_registration_allowed": False,
            "promotion_ready": False,
            "paper_auto_start": False,
            "live_enabled": False,
        },
    }
    report["artifact_hash"] = hashlib.sha256(
        _stable_json(report).encode("utf-8")
    ).hexdigest()
    _write_json(
        output_root / "btc_5m_regime_conditional_neighborhood_correction_report.json",
        report,
    )
    return report


def run_btc_regime_conditional_neighborhood_correction(
    *,
    source_report_path: Path,
    source_lock_path: Path,
    output_root: Path,
    repo_root: Path | None = None,
    generated_at_utc: datetime | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    try:
        source_report = json.loads(source_report_path.read_text(encoding="utf-8"))
        source_lock = json.loads(source_lock_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RegimeConditionalSearchError("correction_source_artifact_unreadable") from exc
    if not isinstance(source_report, Mapping) or not isinstance(source_lock, Mapping):
        raise RegimeConditionalSearchError("correction_source_artifact_not_mapping")
    try:
        frame, provenance = load_committed_5m_market_frame(repo_root=root)
    except Exception as exc:
        raise RegimeConditionalSearchError(
            f"immutable_5m_dataset_unavailable:{type(exc).__name__}:{exc}"
        ) from exc
    return run_regime_conditional_neighborhood_correction_on_frame(
        frame=frame,
        data_provenance=provenance,
        source_report=source_report,
        source_lock=source_lock,
        source_report_file_sha256=_sha256_file(source_report_path),
        source_lock_file_sha256=_sha256_file(source_lock_path),
        output_root=output_root,
        generated_at_utc=generated_at_utc,
    )


def render_regime_conditional_summary(report: Mapping[str, Any]) -> str:
    validation = _mapping(report.get("validation_design"))
    search = _mapping(report.get("search_protocol"))
    lines = [
        "# BTC 5m 市场状态条件 Alpha 搜索",
        "",
        f"- 决策：`{report.get('decision')}`",
        f"- 代码提交：`{report.get('code_commit')}`",
        f"- 选择样本：`{validation.get('selection_rows')}` 根 5m K 线",
        f"- 未见集状态：`{validation.get('holdout_exposure_after_run')}`",
        f"- 本轮/累计唯一评估：`{search.get('run_unique_evaluations')}` / `{search.get('cumulative_unique_evaluations')}`",
        "- 搜索对象仅含经济假设、状态、入场和语义退出；仓位与风险宪法为固定外部合同。",
        "- 结果仅为 research_only，不注册 Demo，不解锁 paper/live/private/order。",
        "",
    ]
    for row in report.get("top_candidates", []):
        candidate = _mapping(row)
        lines.extend(
            [
                f"## #{candidate.get('rank')} {candidate.get('candidate_id')}",
                "",
                f"- 假设家族：`{_mapping(candidate.get('alpha_genome')).get('hypothesis_family')}`",
                f"- Pareto 层：`{candidate.get('pareto_rank')}`",
                f"- 通过/适用 folds：`{candidate.get('passed_eligible_fold_count')}` / `{candidate.get('eligible_fold_count')}`",
                f"- 选择阻塞：`{candidate.get('selection_reasons')}`",
                "",
            ]
        )
    return "\n".join(lines)


def _evaluate_candidate(
    *,
    frame: pd.DataFrame,
    genome: AlphaGenome,
    folds: Sequence[FoldSpec],
    cache: dict[str, dict[str, Any]],
    sizing_policy: FixedSizingPolicy,
    risk_constitution: FixedRiskConstitution,
) -> dict[str, Any]:
    cached = cache.get(genome.genome_hash)
    if cached is not None:
        return cached
    target, target_diagnostics = build_regime_conditional_target(
        frame,
        genome,
        sizing_policy=sizing_policy,
        risk_constitution=risk_constitution,
    )
    eligible_series = target.attrs.get("regime_eligible")
    fold_rows: list[dict[str, Any]] = []
    for fold in folds:
        cost_metrics: dict[str, dict[str, Any]] = {}
        for scenario in COST_SCENARIOS:
            metrics, _ = simulate_regime_conditional_next_open(
                frame,
                target,
                start=fold.validation_start,
                end=fold.validation_end,
                cost_bps=scenario.total_bps,
                risk_constitution=risk_constitution,
                regime_eligible_at_close=(
                    eligible_series if isinstance(eligible_series, pd.Series) else None
                ),
            )
            cost_metrics[scenario.name] = metrics
        base = cost_metrics["base"]
        evidence = classify_fold_evidence(base)
        reasons = list(evidence["reasons"])
        if evidence["performance_gate_applied"]:
            conservative = cost_metrics["conservative"]
            stress = cost_metrics["stress"]
            if float(conservative.get("total_return", 0.0)) <= 0.0:
                reasons.append("conservative_cost_total_return_non_positive")
            if float(stress.get("total_return", 0.0)) <= 0.0:
                reasons.append("stress_cost_total_return_non_positive")
            if float(stress.get("profit_factor", 0.0)) < 1.0:
                reasons.append("stress_cost_profit_factor_below_1p0")
            status = "pass" if not reasons else "fail"
            passed: bool | None = not reasons
        else:
            status = str(evidence["status"])
            passed = None
        fold_rows.append(
            {
                "fold_id": fold.fold_id,
                "status": status,
                "performance_gate_applied": bool(evidence["performance_gate_applied"]),
                "passed": passed,
                "reasons": reasons,
                "cost_scenarios": cost_metrics,
            }
        )
    row: dict[str, Any] = {
        "genome": genome,
        "genome_hash": genome.genome_hash,
        "folds": fold_rows,
        "target_diagnostics": target_diagnostics,
        "parameter_neighborhood_stability": {
            "status": "not_yet_evaluated",
            "passed": False,
            "neighbor_count": 0,
        },
    }
    _refresh_candidate_statistics(row, cumulative_trials=max(1, len(cache) + 1))
    cache[genome.genome_hash] = row
    return row


def _refresh_candidate_statistics(
    row: dict[str, Any],
    *,
    cumulative_trials: int,
) -> None:
    folds = [dict(value) for value in row.get("folds", []) if isinstance(value, Mapping)]
    eligible = [fold for fold in folds if bool(fold.get("performance_gate_applied"))]
    source = eligible or folds
    base_metrics = [
        _mapping(_mapping(fold.get("cost_scenarios")).get("base")) for fold in source
    ]
    stress_metrics = [
        _mapping(_mapping(fold.get("cost_scenarios")).get("stress")) for fold in source
    ]
    means = [float(metrics.get("mean_bet_return", 0.0)) for metrics in base_metrics]
    deviations = [float(metrics.get("bet_return_std", 0.0)) for metrics in base_metrics]
    effective_bets = sum(
        float(metrics.get("effective_bet_count", 0.0)) for metrics in base_metrics
    )
    median_mean = float(np.median(means)) if means else 0.0
    median_std = float(np.median(deviations)) if deviations else 0.0
    standard_error = median_std / math.sqrt(max(effective_bets, 1.0))
    expected_maximum_z = math.sqrt(2.0 * math.log(max(int(cumulative_trials), 2)))
    haircut = expected_maximum_z * standard_error
    deflated = median_mean - haircut
    row["multiple_testing"] = {
        "method": "expected_maximum_normal_haircut",
        "cumulative_unique_trials": int(cumulative_trials),
        "pooled_effective_bets": _round(effective_bets),
        "median_mean_bet_return": _round(median_mean),
        "median_bet_return_std": _round(median_std),
        "expected_maximum_z": _round(expected_maximum_z),
        "haircut": _round(haircut),
        "deflated_mean_bet_return": _round(deflated),
    }
    row["eligible_fold_count"] = len(eligible)
    row["passed_eligible_fold_count"] = sum(
        int(fold.get("passed") is True) for fold in eligible
    )
    row["positive_eligible_fold_count"] = sum(
        int(
            float(
                _mapping(_mapping(fold.get("cost_scenarios")).get("base")).get(
                    "total_return", 0.0
                )
            )
            > 0.0
        )
        for fold in eligible
    )
    base_returns = [float(metrics.get("total_return", -1.0)) for metrics in base_metrics]
    stress_returns = [float(metrics.get("total_return", -1.0)) for metrics in stress_metrics]
    drawdowns = [float(metrics.get("max_drawdown", -1.0)) for metrics in base_metrics]
    profit_factors = [
        min(10.0, float(metrics.get("profit_factor", 0.0))) for metrics in base_metrics
    ]
    turnover_per_bet = [
        float(metrics.get("turnover_per_independent_bet", 999.0))
        for metrics in base_metrics
    ]
    row["objectives"] = {
        "passed_eligible_folds": float(row["passed_eligible_fold_count"]),
        "worst_stress_fold_return": min(stress_returns) if stress_returns else -1.0,
        "median_base_fold_return": float(np.median(base_returns)) if base_returns else -1.0,
        "deflated_mean_bet_return": deflated,
        "pooled_effective_bets": effective_bets,
        "worst_max_drawdown": min(drawdowns) if drawdowns else -1.0,
        "median_profit_factor": float(np.median(profit_factors)) if profit_factors else 0.0,
        "negative_median_turnover_per_bet": (
            -float(np.median(turnover_per_bet)) if turnover_per_bet else -999.0
        ),
    }


def _assign_pareto_ranks(
    rows: Sequence[dict[str, Any]],
    *,
    cumulative_trials: int,
) -> None:
    candidates = list(rows)
    for row in candidates:
        _refresh_candidate_statistics(row, cumulative_trials=cumulative_trials)
    remaining = set(range(len(candidates)))
    rank = 0
    while remaining:
        front: list[int] = []
        for index in sorted(remaining):
            if not any(
                _dominates(candidates[other], candidates[index])
                for other in remaining
                if other != index
            ):
                front.append(index)
        if not front:
            front = [min(remaining)]
        for index in front:
            candidates[index]["pareto_rank"] = rank
            remaining.remove(index)
        rank += 1


def _dominates(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    left_objectives = _mapping(left.get("objectives"))
    right_objectives = _mapping(right.get("objectives"))
    keys = tuple(left_objectives)
    if not keys or set(keys) != set(right_objectives):
        return False
    left_values = [float(left_objectives[key]) for key in keys]
    right_values = [float(right_objectives[key]) for key in keys]
    return all(a >= b for a, b in zip(left_values, right_values)) and any(
        a > b for a, b in zip(left_values, right_values)
    )


def _selection_sort_key(row: Mapping[str, Any]) -> tuple[Any, ...]:
    multiple = _mapping(row.get("multiple_testing"))
    objectives = _mapping(row.get("objectives"))
    return (
        int(row.get("pareto_rank", 999)),
        -int(row.get("passed_eligible_fold_count", 0)),
        -int(row.get("eligible_fold_count", 0)),
        -float(multiple.get("deflated_mean_bet_return", -1.0)),
        -float(objectives.get("worst_stress_fold_return", -1.0)),
        str(row.get("genome_hash", "")),
    )


def evaluate_parameter_neighborhood_stability(
    *,
    frame: pd.DataFrame,
    selection: Mapping[str, Any],
    folds: Sequence[FoldSpec],
    cache: dict[str, dict[str, Any]],
    sizing_policy: FixedSizingPolicy,
    risk_constitution: FixedRiskConstitution,
) -> dict[str, Any]:
    genome = selection.get("genome")
    if not isinstance(genome, AlphaGenome):
        raise RegimeConditionalSearchError("neighborhood_selection_genome_invalid")
    baseline = _median_eligible_base_return(selection)
    neighbors = _neighbor_genomes(genome)
    rows = [
        _evaluate_candidate(
            frame=frame,
            genome=neighbor,
            folds=folds,
            cache=cache,
            sizing_policy=sizing_policy,
            risk_constitution=risk_constitution,
        )
        for neighbor in neighbors
    ]
    neighbor_returns = [_median_eligible_base_return(row) for row in rows]
    threshold = max(0.0, baseline * 0.50)
    stable_count = sum(int(value >= threshold) for value in neighbor_returns)
    required = max(2, math.ceil(len(neighbor_returns) * 0.50))
    passed = bool(baseline > 0.0 and stable_count >= required)
    return {
        "status": "pass" if passed else "fail",
        "passed": passed,
        "baseline_median_eligible_base_return": _round(baseline),
        "retention_threshold": _round(threshold),
        "neighbor_count": len(neighbor_returns),
        "stable_neighbor_count": stable_count,
        "required_stable_neighbor_count": required,
        "neighbor_median_returns": [_round(value) for value in neighbor_returns],
        "neighbor_genome_hashes": [neighbor.genome_hash for neighbor in neighbors],
        "family_switch_count": 0,
    }


def _median_eligible_base_return(selection: Mapping[str, Any]) -> float:
    values: list[float] = []
    for fold in selection.get("folds", []):
        if not isinstance(fold, Mapping) or not fold.get("performance_gate_applied"):
            continue
        metrics = _mapping(_mapping(fold.get("cost_scenarios")).get("base"))
        values.append(float(metrics.get("total_return", 0.0)))
    return float(np.median(values)) if values else -1.0


def _selection_gate_reasons(
    *,
    selection: Mapping[str, Any],
    fold_count: int,
) -> list[str]:
    reasons: list[str] = []
    required_eligible = max(1, fold_count - 1)
    eligible = int(selection.get("eligible_fold_count", 0))
    passed = int(selection.get("passed_eligible_fold_count", 0))
    positive = int(selection.get("positive_eligible_fold_count", 0))
    required_passed = max(1, eligible - 1)
    if eligible < required_eligible:
        reasons.append(
            f"eligible_walk_forward_folds_below_{required_eligible}_of_{fold_count}"
        )
    if passed < required_passed:
        reasons.append(
            f"passed_eligible_folds_below_{required_passed}_of_{max(eligible, 1)}"
        )
    if positive < required_passed:
        reasons.append(
            f"positive_eligible_folds_below_{required_passed}_of_{max(eligible, 1)}"
        )
    multiple = _mapping(selection.get("multiple_testing"))
    if float(multiple.get("pooled_effective_bets", 0.0)) < DEFAULT_MIN_POOLED_EFFECTIVE_BETS:
        reasons.append("pooled_effective_bets_below_30")
    if float(multiple.get("deflated_mean_bet_return", 0.0)) <= 0.0:
        reasons.append("multiple_testing_deflated_mean_bet_return_non_positive")
    neighborhood = _mapping(selection.get("parameter_neighborhood_stability"))
    if not bool(neighborhood.get("passed")):
        reasons.append("parameter_neighborhood_stability_failed")
    if any(
        bool(
            _mapping(
                _mapping(_mapping(fold).get("cost_scenarios")).get("base")
            ).get("bankruptcy")
        )
        for fold in selection.get("folds", [])
        if isinstance(fold, Mapping)
    ):
        reasons.append("walk_forward_bankruptcy")
    return reasons


def _holdout_gate_reasons(cost_scenarios: Mapping[str, Mapping[str, Any]]) -> list[str]:
    reasons: list[str] = []
    base = _mapping(cost_scenarios.get("base"))
    conservative = _mapping(cost_scenarios.get("conservative"))
    stress = _mapping(cost_scenarios.get("stress"))
    if int(base.get("independent_bet_count", 0)) < DEFAULT_MIN_INDEPENDENT_BETS:
        reasons.append("holdout_independent_bets_below_preregistered_minimum")
    if float(base.get("total_return", 0.0)) <= 0.0:
        reasons.append("holdout_base_total_return_non_positive")
    if float(base.get("profit_factor", 0.0)) < 1.05:
        reasons.append("holdout_base_profit_factor_below_1p05")
    if float(base.get("max_drawdown", -1.0)) < -0.20:
        reasons.append("holdout_base_max_drawdown_below_minus_20pct")
    if float(conservative.get("total_return", 0.0)) <= 0.0:
        reasons.append("holdout_conservative_cost_total_return_non_positive")
    if float(stress.get("total_return", 0.0)) <= 0.0:
        reasons.append("holdout_stress_cost_total_return_non_positive")
    if float(stress.get("profit_factor", 0.0)) < 1.0:
        reasons.append("holdout_stress_cost_profit_factor_below_1p0")
    if bool(base.get("bankruptcy")):
        reasons.append("holdout_bankruptcy")
    return reasons


def _build_candidate_lock(
    *,
    experiment_id: str,
    generated: datetime,
    data_provenance: Mapping[str, Any],
    selection_frame: pd.DataFrame,
    selection_end: int,
    prior_cutoff: pd.Timestamp | None,
    holdout_start: pd.Timestamp | None,
    selection: Mapping[str, Any],
    folds: Sequence[FoldSpec],
    seed: int,
    population_size: int,
    generations: int,
    search_round_count: int,
    prior_search_unique_evaluations: int,
    final_unique_evaluations: int,
    sizing_policy: FixedSizingPolicy,
    risk_constitution: FixedRiskConstitution,
    selection_reasons: Sequence[str],
) -> dict[str, Any]:
    if prior_cutoff is None or holdout_start is None:
        raise RegimeConditionalSearchError("candidate_lock_boundary_missing")
    genome = selection.get("genome")
    if not isinstance(genome, AlphaGenome):
        raise RegimeConditionalSearchError("candidate_lock_genome_invalid")
    provenance_keys = (
        "dataset_id",
        "dataset_version",
        "manifest_git_sha256",
        "manifest_sha256",
        "physical_manifest_sha256",
        "aggregate_sha256",
        "five_minute_file_sha256",
        "resolved_slice_sha256",
        "source_sha256",
        "selector_commit",
        "selector_sha256",
    )
    payload: dict[str, Any] = {
        "schema_version": CANDIDATE_LOCK_SCHEMA_VERSION,
        "experiment_id": experiment_id,
        "generated_at": generated.isoformat(),
        "data_binding": {
            key: data_provenance.get(key)
            for key in provenance_keys
            if data_provenance.get(key) is not None
        },
        "selection_window": {
            "start": selection_frame.index[0].isoformat(),
            "end": prior_cutoff.isoformat(),
            "row_count": selection_end,
            "ohlcv_index_sha256": _frame_sha256(selection_frame),
        },
        "unseen_holdout_window": {
            "start": holdout_start.isoformat(),
            "boundary_contiguous_5m": True,
            "candidate_count_if_revealed": 1,
            "reuse_for_tuning_allowed": False,
        },
        "locked_candidate": {
            "candidate_id": genome.candidate_id,
            "genome_hash": genome.genome_hash,
            "alpha_genome": genome.to_dict(),
            "pareto_rank": int(selection.get("pareto_rank", 999)),
            "eligible_fold_count": int(selection.get("eligible_fold_count", 0)),
            "passed_eligible_fold_count": int(
                selection.get("passed_eligible_fold_count", 0)
            ),
            "multiple_testing": dict(_mapping(selection.get("multiple_testing"))),
            "parameter_neighborhood_stability": dict(
                _mapping(selection.get("parameter_neighborhood_stability"))
            ),
        },
        "fixed_policies": {
            "sizing": sizing_policy.to_dict(),
            "risk_constitution": risk_constitution.to_dict(),
        },
        "search_identity": {
            "seed": int(seed),
            "population_size": population_size,
            "generations": generations,
            "search_round_count": search_round_count,
            "prior_unique_evaluations": prior_search_unique_evaluations,
            "run_unique_evaluations": final_unique_evaluations,
            "cumulative_unique_evaluations": (
                prior_search_unique_evaluations + final_unique_evaluations
            ),
            "folds": [fold.to_dict(selection_frame.index) for fold in folds],
            "selection_method": "deterministic_pareto_genetic_search",
        },
        "selection_gate_reasons": list(selection_reasons),
        "reveal_authorized": not selection_reasons,
        "research_only": True,
        "promotion_allowed": False,
        "paper_allowed": False,
        "live_allowed": False,
        "private_allowed": False,
        "order_allowed": False,
    }
    payload["semantic_sha256"] = hashlib.sha256(
        _stable_json(payload).encode("utf-8")
    ).hexdigest()
    return payload


def _public_candidate(
    selection: Mapping[str, Any],
    *,
    rank: int,
    holdout_key: str,
    holdout: Mapping[str, Any],
) -> dict[str, Any]:
    genome = selection.get("genome")
    if not isinstance(genome, AlphaGenome):
        raise RegimeConditionalSearchError("public_candidate_genome_invalid")
    selection_reasons = _selection_gate_reasons(
        selection=selection,
        fold_count=len(selection.get("folds", [])) or 4,
    )
    return {
        "rank": rank,
        "candidate_id": genome.candidate_id,
        "genome_hash": genome.genome_hash,
        "alpha_genome": genome.to_dict(),
        "pareto_rank": int(selection.get("pareto_rank", 999)),
        "objectives": dict(_mapping(selection.get("objectives"))),
        "multiple_testing": dict(_mapping(selection.get("multiple_testing"))),
        "parameter_neighborhood_stability": dict(
            _mapping(selection.get("parameter_neighborhood_stability"))
        ),
        "eligible_fold_count": int(selection.get("eligible_fold_count", 0)),
        "passed_eligible_fold_count": int(
            selection.get("passed_eligible_fold_count", 0)
        ),
        "positive_eligible_fold_count": int(
            selection.get("positive_eligible_fold_count", 0)
        ),
        "selection_reasons": selection_reasons,
        "walk_forward": [dict(row) for row in selection.get("folds", [])],
        "target_diagnostics": dict(_mapping(selection.get("target_diagnostics"))),
        holdout_key: dict(holdout),
        "research_only": True,
        "demo_strategy_registration_allowed": False,
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
    }


def _initial_population(rng: random.Random, size: int) -> list[AlphaGenome]:
    seeded = [
        AlphaGenome(
            family,
            12,
            48,
            1.0,
            24,
            12,
            14,
            0.10,
            2.0,
            24,
            6,
            0.85,
        )
        for family in HYPOTHESIS_FAMILIES
    ]
    while len(seeded) < size:
        seeded.append(_random_genome(rng))
    return _dedupe_and_fill(seeded, rng, size)


def _random_genome(rng: random.Random) -> AlphaGenome:
    state_fast, state_slow = rng.choice(STATE_PAIRS)
    return AlphaGenome(
        hypothesis_family=rng.choice(HYPOTHESIS_FAMILIES),
        state_fast_bars=state_fast,
        state_slow_bars=state_slow,
        state_strength_atr=rng.choice(STATE_STRENGTH_ATR),
        entry_window_bars=rng.choice(ENTRY_WINDOWS),
        exit_window_bars=rng.choice(EXIT_WINDOWS),
        atr_window_bars=rng.choice(ATR_WINDOWS),
        entry_buffer_atr=rng.choice(ENTRY_BUFFERS_ATR),
        invalidation_atr=rng.choice(INVALIDATION_ATR),
        max_holding_bars=rng.choice(MAX_HOLDING_BARS),
        cooldown_bars=rng.choice(COOLDOWN_BARS),
        compression_ratio=rng.choice(COMPRESSION_RATIOS),
    )


def _tournament(evaluated: Sequence[Mapping[str, Any]], rng: random.Random) -> AlphaGenome:
    sample = rng.sample(list(evaluated), k=min(4, len(evaluated)))
    winner = sorted(sample, key=_selection_sort_key)[0]
    genome = winner.get("genome")
    if not isinstance(genome, AlphaGenome):
        raise RegimeConditionalSearchError("tournament_genome_invalid")
    return genome


def _crossover(
    left: AlphaGenome,
    right: AlphaGenome,
    rng: random.Random,
) -> AlphaGenome:
    left_values = asdict(left)
    right_values = asdict(right)
    values: dict[str, Any] = {}
    for field in left_values:
        if field in {"state_fast_bars", "state_slow_bars"}:
            continue
        values[field] = left_values[field] if rng.random() < 0.5 else right_values[field]
    pair = (
        (left.state_fast_bars, left.state_slow_bars)
        if rng.random() < 0.5
        else (right.state_fast_bars, right.state_slow_bars)
    )
    values["state_fast_bars"], values["state_slow_bars"] = pair
    return AlphaGenome(**values)


def _mutate(genome: AlphaGenome, rng: random.Random) -> AlphaGenome:
    values = asdict(genome)
    fields = [
        "hypothesis_family",
        "state_pair",
        "state_strength_atr",
        "entry_window_bars",
        "exit_window_bars",
        "atr_window_bars",
        "entry_buffer_atr",
        "invalidation_atr",
        "max_holding_bars",
        "cooldown_bars",
        "compression_ratio",
    ]
    for field in rng.sample(fields, k=rng.choice((1, 1, 2))):
        if field == "hypothesis_family":
            values[field] = rng.choice(HYPOTHESIS_FAMILIES)
        elif field == "state_pair":
            values["state_fast_bars"], values["state_slow_bars"] = rng.choice(STATE_PAIRS)
        elif field == "state_strength_atr":
            values[field] = rng.choice(STATE_STRENGTH_ATR)
        elif field == "entry_window_bars":
            values[field] = rng.choice(ENTRY_WINDOWS)
        elif field == "exit_window_bars":
            values[field] = rng.choice(EXIT_WINDOWS)
        elif field == "atr_window_bars":
            values[field] = rng.choice(ATR_WINDOWS)
        elif field == "entry_buffer_atr":
            values[field] = rng.choice(ENTRY_BUFFERS_ATR)
        elif field == "invalidation_atr":
            values[field] = rng.choice(INVALIDATION_ATR)
        elif field == "max_holding_bars":
            values[field] = rng.choice(MAX_HOLDING_BARS)
        elif field == "cooldown_bars":
            values[field] = rng.choice(COOLDOWN_BARS)
        elif field == "compression_ratio":
            values[field] = rng.choice(COMPRESSION_RATIOS)
    values.pop("state_pair", None)
    return AlphaGenome(**values)


def _dedupe_and_fill(
    genomes: Sequence[AlphaGenome],
    rng: random.Random,
    size: int,
) -> list[AlphaGenome]:
    unique = {genome.genome_hash: genome for genome in genomes}
    attempts = 0
    while len(unique) < size and attempts < size * 100:
        genome = _random_genome(rng)
        unique.setdefault(genome.genome_hash, genome)
        attempts += 1
    if len(unique) < size:
        raise RegimeConditionalSearchError("gene_space_deduplication_exhausted")
    return list(unique.values())[:size]


def _neighbor_genomes(genome: AlphaGenome) -> list[AlphaGenome]:
    values = asdict(genome)
    specifications: list[tuple[str, Sequence[Any], Any]] = [
        ("state_pair", STATE_PAIRS, (genome.state_fast_bars, genome.state_slow_bars)),
        ("entry_window_bars", ENTRY_WINDOWS, genome.entry_window_bars),
        ("exit_window_bars", EXIT_WINDOWS, genome.exit_window_bars),
        ("entry_buffer_atr", ENTRY_BUFFERS_ATR, genome.entry_buffer_atr),
        ("max_holding_bars", MAX_HOLDING_BARS, genome.max_holding_bars),
        ("compression_ratio", COMPRESSION_RATIOS, genome.compression_ratio),
    ]
    neighbors: list[AlphaGenome] = []
    for field, options, current in specifications:
        replacement = _adjacent_value(options, current)
        candidate = dict(values)
        if field == "state_pair":
            candidate["state_fast_bars"], candidate["state_slow_bars"] = replacement
        else:
            candidate[field] = replacement
        neighbor = AlphaGenome(**candidate)
        if neighbor.genome_hash != genome.genome_hash:
            neighbors.append(neighbor)
    return neighbors


def _adjacent_value(options: Sequence[Any], current: Any) -> Any:
    values = list(options)
    index = values.index(current)
    if index + 1 < len(values):
        return values[index + 1]
    return values[index - 1] if index > 0 else values[index]


def _gene_space() -> dict[str, Any]:
    counts = [
        len(HYPOTHESIS_FAMILIES),
        len(STATE_PAIRS),
        len(STATE_STRENGTH_ATR),
        len(ENTRY_WINDOWS),
        len(EXIT_WINDOWS),
        len(ATR_WINDOWS),
        len(ENTRY_BUFFERS_ATR),
        len(INVALIDATION_ATR),
        len(MAX_HOLDING_BARS),
        len(COOLDOWN_BARS),
        len(COMPRESSION_RATIOS),
    ]
    total = math.prod(counts)
    return {
        "hypothesis_families": list(HYPOTHESIS_FAMILIES),
        "state_pairs_5m_bars": [list(pair) for pair in STATE_PAIRS],
        "state_strength_atr": list(STATE_STRENGTH_ATR),
        "entry_windows_5m_bars": list(ENTRY_WINDOWS),
        "exit_windows_5m_bars": list(EXIT_WINDOWS),
        "atr_windows_5m_bars": list(ATR_WINDOWS),
        "entry_buffers_atr": list(ENTRY_BUFFERS_ATR),
        "semantic_invalidation_atr": list(INVALIDATION_ATR),
        "maximum_holding_bars": list(MAX_HOLDING_BARS),
        "cooldown_bars": list(COOLDOWN_BARS),
        "compression_ratios": list(COMPRESSION_RATIOS),
        "discrete_combination_count": total,
        "optimized_sizing_or_safety_parameters": [],
    }


def _atr(frame: pd.DataFrame, window: int) -> pd.Series:
    return _true_range(frame).rolling(window, min_periods=window).mean()


def _true_range(frame: pd.DataFrame) -> pd.Series:
    high = frame["high"].astype(float)
    low = frame["low"].astype(float)
    close = frame["close"].astype(float)
    previous_close = close.shift(1)
    return pd.concat(
        [
            high - low,
            (high - previous_close).abs(),
            (low - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)


def _effective_sample_size(values: np.ndarray) -> float:
    count = len(values)
    if count <= 1:
        return float(count)
    left = values[:-1]
    right = values[1:]
    if np.std(left, ddof=0) <= 0.0 or np.std(right, ddof=0) <= 0.0:
        return float(count)
    correlation = float(np.corrcoef(left, right)[0, 1])
    if not math.isfinite(correlation):
        return float(count)
    correlation = float(np.clip(correlation, -0.95, 0.95))
    estimate = count * (1.0 - correlation) / (1.0 + correlation)
    return float(np.clip(estimate, 1.0, float(count)))


def _require_ohlcv(frame: pd.DataFrame) -> None:
    required = {"open", "high", "low", "close", "volume"}
    if not isinstance(frame, pd.DataFrame) or not required.issubset(frame.columns):
        raise RegimeConditionalSearchError("ohlcv_fields_missing")
    if not isinstance(frame.index, pd.DatetimeIndex) or frame.index.tz is None:
        raise RegimeConditionalSearchError("ohlcv_index_must_be_timezone_aware")
    if frame.empty or not frame.index.is_monotonic_increasing or frame.index.has_duplicates:
        raise RegimeConditionalSearchError("ohlcv_index_invalid")
    values = frame[["open", "high", "low", "close", "volume"]].astype(float)
    if not np.isfinite(values.to_numpy()).all():
        raise RegimeConditionalSearchError("ohlcv_values_nonfinite")
    if (
        (values[["open", "high", "low", "close"]] <= 0.0).any().any()
        or (values["volume"] < 0.0).any()
        or (values["high"] < values[["open", "close", "low"]].max(axis=1)).any()
        or (values["low"] > values[["open", "close", "high"]].min(axis=1)).any()
    ):
        raise RegimeConditionalSearchError("ohlcv_values_invalid")


def _frame_sha256(frame: pd.DataFrame) -> str:
    values = frame[["open", "high", "low", "close", "volume"]].to_numpy(
        dtype="<f8",
        copy=True,
    )
    index_values = frame.index.view("int64").astype("<i8", copy=False)
    digest = hashlib.sha256()
    digest.update(index_values.tobytes())
    digest.update(values.tobytes())
    return digest.hexdigest()


def _as_utc_timestamp(value: datetime | None, label: str) -> pd.Timestamp:
    if value is None:
        raise RegimeConditionalSearchError(f"{label}_missing")
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        raise RegimeConditionalSearchError(f"{label}_timezone_missing")
    return timestamp.tz_convert("UTC")


def _git_commit_hash(repo_root: Path | None = None) -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root or Path.cwd(),
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(value, encoding="utf-8")
    os.replace(temporary, path)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_sha256(value: object) -> bool:
    text = str(value)
    return len(text) == 64 and all(character in "0123456789abcdef" for character in text)


def _stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _round(value: Any, digits: int = 8) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(parsed):
        return 0.0
    return round(parsed, digits)
