"""BTC alpha hardening helpers.

The helpers in this module are research-only. They deliberately avoid broker,
paper, and live runtime imports so BTC alpha candidates can be hardened without
changing execution readiness.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from math import erf, sqrt
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd


BTC_HARDENING_GATE_THRESHOLDS: dict[str, float] = {
    "profit_factor": 1.15,
    "event_profit_factor": 1.15,
    "walk_forward_pass_rate": 0.80,
    "regime_pass_rate": 0.75,
    "annual_turnover": 15.0,
    "max_drawdown_pct_floor": -15.0,
    "dsr": 0.10,
    "pbo": 0.50,
}

BTC_HARDENING_ALLOWED_STATES = {
    "research_failed",
    "research_candidate",
    "candidate_gate_failed",
    "candidate_passed_internal_gate",
    "paper_review_pending",
}
BTC_HARDENING_FORBIDDEN_STATES = {"paper_ready", "live_ready", "live_enabled"}


@dataclass(frozen=True)
class BtcHardeningGateResult:
    strategy_id: str
    status: str
    passed: bool
    fail_reasons: list[str]
    checks: dict[str, bool]
    thresholds: dict[str, float]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def classify_btc_regimes(
    frame: pd.DataFrame,
    *,
    trend_window: int = 168,
    volatility_window: int = 168,
    compression_window: int = 336,
) -> pd.Series:
    """Classify BTC bars using only current and historical OHLCV data."""

    if frame.empty:
        return pd.Series(dtype="object", name="regime")

    close = pd.to_numeric(frame["close"], errors="coerce").astype(float)
    high = pd.to_numeric(frame.get("high", close), errors="coerce").astype(float)
    low = pd.to_numeric(frame.get("low", close), errors="coerce").astype(float)
    volume = pd.to_numeric(frame.get("volume", pd.Series(0.0, index=frame.index)), errors="coerce").astype(float)
    returns = close.pct_change().fillna(0.0)

    tw = max(2, int(trend_window))
    vw = max(2, int(volatility_window))
    cw = max(vw, int(compression_window))
    trend = close.pct_change(tw).fillna(0.0)
    realized_vol = returns.rolling(vw, min_periods=max(2, vw // 3)).std(ddof=0).fillna(0.0)
    trend_threshold = trend.abs().rolling(cw, min_periods=max(10, cw // 3)).median().fillna(0.0)
    trend_threshold = trend_threshold.clip(lower=0.005)
    high_vol_threshold = realized_vol.expanding(min_periods=max(10, vw // 2)).quantile(0.70).fillna(realized_vol)
    low_vol_threshold = realized_vol.expanding(min_periods=max(10, vw // 2)).quantile(0.35).fillna(realized_vol)
    range_pct = ((high - low).abs() / close.shift(1).replace(0, pd.NA)).fillna(0.0)
    range_low_threshold = range_pct.expanding(min_periods=max(10, vw // 2)).quantile(0.35).fillna(range_pct)
    volume_baseline = volume.rolling(vw, min_periods=max(2, vw // 3)).median().replace(0, pd.NA)
    volume_ratio = (volume / volume_baseline).replace([np.inf, -np.inf], np.nan).fillna(1.0)
    shock_threshold = realized_vol.rolling(vw, min_periods=max(2, vw // 3)).median().fillna(realized_vol) * 4.0

    regimes = pd.Series("mean_reverting_chop", index=frame.index, dtype="object", name="regime")
    low_vol_chop = (realized_vol <= low_vol_threshold) & (trend.abs() <= trend_threshold)
    compression = low_vol_chop & (range_pct <= range_low_threshold)
    expansion = (realized_vol >= high_vol_threshold) & (volume_ratio >= 1.10)
    high_vol_trend = expansion & (trend.abs() > trend_threshold)
    trending_up = trend > trend_threshold
    trending_down = trend < -trend_threshold
    liquidation_shock = (returns < -shock_threshold.abs()) | ((returns < -0.035) & (volume_ratio >= 1.25))

    regimes.loc[low_vol_chop] = "low_vol_chop"
    regimes.loc[compression] = "compression"
    regimes.loc[expansion] = "expansion"
    regimes.loc[trending_up] = "trending_up"
    regimes.loc[trending_down] = "trending_down"
    regimes.loc[high_vol_trend] = "high_vol_trend"
    regimes.loc[liquidation_shock] = "liquidation_shock"
    return regimes


def filter_signal_by_regime(
    signal: pd.Series,
    regimes: pd.Series,
    *,
    allowed_regimes: Iterable[str] | None = None,
    blocked_regimes: Iterable[str] | None = None,
) -> pd.Series:
    filtered = signal.copy().astype(float)
    aligned_regimes = regimes.reindex(filtered.index).fillna("unknown").astype(str)
    if allowed_regimes:
        allowed = {str(item) for item in allowed_regimes}
        filtered.loc[~aligned_regimes.isin(allowed)] = 0.0
    if blocked_regimes:
        blocked = {str(item) for item in blocked_regimes}
        filtered.loc[aligned_regimes.isin(blocked)] = 0.0
    return filtered.fillna(0.0).clip(-1.0, 1.0)


def apply_directional_state_machine(
    target_signal: pd.Series,
    *,
    min_holding_bars: int,
    cooldown_bars: int,
    exit_hysteresis_bars: int = 1,
    max_holding_bars: int = 0,
) -> pd.Series:
    """Convert a target direction into executable research exposure."""

    index = target_signal.index
    normalized = target_signal.reindex(index).fillna(0.0).clip(-1.0, 1.0)
    signal = pd.Series(0.0, index=index, dtype=float)
    position = 0.0
    bars_held = 0
    cooldown_remaining = 0
    flat_streak = 0
    min_hold = max(0, int(min_holding_bars))
    cooldown = max(0, int(cooldown_bars))
    hysteresis = max(1, int(exit_hysteresis_bars))
    max_hold = max(0, int(max_holding_bars))

    for timestamp in index:
        if cooldown_remaining > 0:
            cooldown_remaining -= 1
        raw_target = float(normalized.loc[timestamp])
        target = 1.0 if raw_target > 0 else -1.0 if raw_target < 0 else 0.0
        if target == 0.0 or (position != 0.0 and target != position):
            flat_streak += 1
        else:
            flat_streak = 0

        can_exit = bars_held >= min_hold
        force_exit = position != 0.0 and max_hold > 0 and bars_held >= max_hold
        if position == 0.0:
            if cooldown_remaining == 0 and target != 0.0:
                position = target
                bars_held = 0
                flat_streak = 0
        elif force_exit or (can_exit and flat_streak >= hysteresis):
            old_position = position
            position = 0.0
            bars_held = 0
            cooldown_remaining = cooldown
            flat_streak = 0
            if target != 0.0 and target != old_position and cooldown_remaining == 0:
                position = target
        if position != 0.0:
            bars_held += 1
        signal.loc[timestamp] = position
    return signal


def _ma(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(max(1, int(window)), min_periods=max(1, int(window))).mean()


def _orderflow_components(frame: pd.DataFrame, config: Mapping[str, Any]) -> dict[str, pd.Series]:
    close = frame["close"].astype(float)
    volume = frame["volume"].astype(float)
    quote_volume = pd.to_numeric(frame.get("quote_volume", close * volume), errors="coerce").astype(float)
    trade_count = pd.to_numeric(frame.get("trade_count", pd.Series(1.0, index=frame.index)), errors="coerce").astype(float)
    taker_buy = pd.to_numeric(
        frame.get("taker_buy_base_volume", volume * 0.5),
        errors="coerce",
    ).astype(float)
    buy_ratio = (taker_buy / volume.replace(0, pd.NA)).clip(0.0, 1.0).fillna(0.5)
    pressure_window = max(2, int(config.get("orderflow_window", config.get("pressure_window", 144))))
    buy_pressure = (buy_ratio - buy_ratio.rolling(pressure_window, min_periods=pressure_window).mean()).fillna(0.0)
    activity_window = max(2, int(config.get("activity_window", pressure_window)))
    quote_intensity = (
        quote_volume / quote_volume.rolling(activity_window, min_periods=activity_window).mean().replace(0, pd.NA)
    ).replace([np.inf, -np.inf], np.nan).fillna(1.0)
    trade_intensity = (
        trade_count / trade_count.rolling(activity_window, min_periods=activity_window).mean().replace(0, pd.NA)
    ).replace([np.inf, -np.inf], np.nan).fillna(1.0)
    return {
        "buy_ratio": buy_ratio,
        "buy_pressure": buy_pressure,
        "quote_intensity": quote_intensity,
        "trade_intensity": trade_intensity,
    }


def btc_orderflow_confirmed_trend_signal(
    frame: pd.DataFrame,
    config: Mapping[str, Any] | None = None,
) -> tuple[pd.Series, dict[str, pd.Series]]:
    """Build a trend signal where order-flow is confirmation only."""

    cfg = dict(config or {})
    close = frame["close"].astype(float)
    fast_ma = _ma(close, int(cfg.get("fast_ma", 96)))
    slow_ma = _ma(close, int(cfg.get("slow_ma", 336)))
    regime_ma = _ma(close, int(cfg.get("regime_ma", 720)))
    momentum = close.pct_change(int(cfg.get("momentum_window", 168))).fillna(0.0)
    realized_vol = close.pct_change().rolling(
        int(cfg.get("vol_window", 168)),
        min_periods=max(2, int(cfg.get("vol_window", 168)) // 2),
    ).std(ddof=0).fillna(0.0)
    max_vol = float(cfg.get("max_volatility", 0.055))
    trend_long = (
        (fast_ma > slow_ma)
        & (slow_ma > regime_ma)
        & (momentum >= float(cfg.get("momentum_threshold", 0.02)))
        & (realized_vol <= max_vol)
    ).fillna(False)
    trend_short = (
        (fast_ma < slow_ma)
        & (slow_ma < regime_ma)
        & (momentum <= -float(cfg.get("momentum_threshold", 0.02)))
        & (realized_vol <= max_vol)
        & (float(cfg.get("short_enabled", 1.0)) > 0.0)
    ).fillna(False)

    flow = _orderflow_components(frame, cfg)
    activity_ready = (
        (flow["quote_intensity"] >= float(cfg.get("min_quote_intensity", 0.75)))
        & (flow["trade_intensity"] >= float(cfg.get("min_trade_intensity", 0.70)))
    ).fillna(False)
    long_confirm = (
        (flow["buy_ratio"] >= float(cfg.get("buy_ratio_threshold", 0.535)))
        & (flow["buy_pressure"] >= float(cfg.get("pressure_threshold", 0.005)))
        & activity_ready
    ).fillna(False)
    short_confirm = (
        (flow["buy_ratio"] <= float(cfg.get("sell_ratio_threshold", 0.465)))
        & (flow["buy_pressure"] <= -float(cfg.get("pressure_threshold", 0.005)))
        & activity_ready
    ).fillna(False)

    persistence = max(1, int(cfg.get("signal_persistence_bars", 3)))
    trend_long_persistent = trend_long.rolling(persistence, min_periods=persistence).sum().fillna(0) >= persistence
    trend_short_persistent = trend_short.rolling(persistence, min_periods=persistence).sum().fillna(0) >= persistence
    flow_long_persistent = long_confirm.rolling(persistence, min_periods=persistence).sum().fillna(0) >= persistence
    flow_short_persistent = short_confirm.rolling(persistence, min_periods=persistence).sum().fillna(0) >= persistence

    target = pd.Series(0.0, index=frame.index, dtype=float)
    target.loc[trend_long_persistent & flow_long_persistent] = 1.0
    target.loc[trend_short_persistent & flow_short_persistent] = -1.0
    conflict = (trend_long_persistent & flow_short_persistent) | (trend_short_persistent & flow_long_persistent)
    target.loc[conflict] = 0.0
    regimes = classify_btc_regimes(
        frame,
        trend_window=int(cfg.get("regime_trend_window", 168)),
        volatility_window=int(cfg.get("regime_vol_window", 168)),
    )
    target = filter_signal_by_regime(
        target,
        regimes,
        allowed_regimes=cfg.get("allowed_regimes"),
        blocked_regimes=cfg.get("blocked_regimes", ("low_vol_chop", "mean_reverting_chop", "liquidation_shock")),
    )
    signal = apply_directional_state_machine(
        target,
        min_holding_bars=int(cfg.get("min_hold_bars", 96)),
        cooldown_bars=int(cfg.get("cooldown_bars", 48)),
        exit_hysteresis_bars=int(cfg.get("exit_hysteresis_bars", 3)),
        max_holding_bars=int(cfg.get("max_hold_bars", 720)),
    )
    scale = min(1.0, max(0.0, float(cfg.get("signal_scale", 0.20))))
    diagnostics = {
        "fast_ma": fast_ma,
        "slow_ma": slow_ma,
        "regime_ma": regime_ma,
        "momentum": momentum,
        "volatility": realized_vol,
        "trend_long": trend_long.astype(float),
        "trend_short": trend_short.astype(float),
        "orderflow_long_confirm": long_confirm.astype(float),
        "orderflow_short_confirm": short_confirm.astype(float),
        "orderflow_conflict": conflict.astype(float),
        "target_signal": target,
        "regime": regimes,
    }
    diagnostics.update(flow)
    return (signal * scale).clip(-1.0, 1.0), diagnostics


def btc_dual_trend_v2_signal(
    frame: pd.DataFrame,
    config: Mapping[str, Any] | None = None,
) -> tuple[pd.Series, dict[str, pd.Series]]:
    """Build a harder dual-trend variant with regime and volatility controls."""

    cfg = {
        "fast_ma": 96,
        "slow_ma": 336,
        "regime_ma": 720,
        "momentum_window": 168,
        "momentum_threshold": 0.025,
        "vol_window": 168,
        "max_volatility": 0.05,
        "min_hold_bars": 120,
        "cooldown_bars": 72,
        "exit_hysteresis_bars": 4,
        "signal_persistence_bars": 3,
        "signal_scale": 0.20,
        "blocked_regimes": ("low_vol_chop", "mean_reverting_chop", "liquidation_shock"),
    }
    cfg.update(dict(config or {}))
    return btc_orderflow_confirmed_trend_signal(frame, cfg)


def annual_turnover_from_signal(signal: pd.Series, *, periods_per_year: float) -> float:
    if signal.empty:
        return 0.0
    total_turnover = float(signal.diff().abs().fillna(signal.abs()).sum())
    years = len(signal) / max(float(periods_per_year), 1.0)
    return total_turnover / max(years, 1e-12)


def hardening_objective_score(metrics: Mapping[str, Any]) -> float:
    pf = min(max(float(metrics.get("profit_factor", 0.0)) / 1.50, 0.0), 1.5)
    wf = min(max(float(metrics.get("walk_forward_pass_rate", 0.0)), 0.0), 1.0)
    regime = min(max(float(metrics.get("regime_pass_rate", 0.0)), 0.0), 1.0)
    cost_return = min(max(float(metrics.get("cost_adjusted_return_pct", 0.0)) / 20.0, -1.0), 1.0)
    turnover = max(float(metrics.get("annual_turnover", 0.0)), 0.0)
    turnover_penalty = min(turnover / BTC_HARDENING_GATE_THRESHOLDS["annual_turnover"], 2.0)
    return round(0.30 * pf + 0.25 * wf + 0.20 * regime + 0.15 * cost_return - 0.10 * turnover_penalty, 6)


def simplified_dsr(sharpe: float, trial_count: int, observation_count: int) -> float:
    if observation_count <= 1:
        return 0.0
    benchmark = sqrt(max(1.0, float(trial_count))) / sqrt(max(2.0, float(observation_count)))
    z_score = (float(sharpe) - benchmark) * sqrt(max(1.0, float(observation_count - 1)))
    return round(max(0.0, min(1.0, 0.5 * (1.0 + erf(z_score / sqrt(2.0))))), 6)


def simplified_pbo(pbo_trials: Sequence[Mapping[str, Any]]) -> float:
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for trial in pbo_trials:
        grouped.setdefault(str(trial.get("split_id", "default")), []).append(trial)
    if not grouped:
        return 1.0
    overfit = 0
    for rows in grouped.values():
        ranked_train = sorted(rows, key=lambda row: float(row.get("train_sharpe", 0.0)), reverse=True)
        selected = ranked_train[0]
        ranked_test = sorted(rows, key=lambda row: float(row.get("test_sharpe", 0.0)), reverse=True)
        test_rank = ranked_test.index(selected) + 1
        if test_rank > (len(ranked_test) + 1) / 2:
            overfit += 1
    return round(overfit / max(1, len(grouped)), 6)


def evaluate_internal_gate(
    strategy_id: str,
    metrics: Mapping[str, Any],
    *,
    thresholds: Mapping[str, float] | None = None,
) -> BtcHardeningGateResult:
    limits = {**BTC_HARDENING_GATE_THRESHOLDS, **dict(thresholds or {})}
    checks = {
        "profit_factor": float(metrics.get("profit_factor", 0.0)) >= limits["profit_factor"],
        "event_profit_factor": float(metrics.get("event_profit_factor", 0.0)) >= limits["event_profit_factor"],
        "walk_forward_pass_rate": float(metrics.get("walk_forward_pass_rate", 0.0)) >= limits["walk_forward_pass_rate"],
        "regime_pass_rate": float(metrics.get("regime_pass_rate", 0.0)) >= limits["regime_pass_rate"],
        "annual_turnover": float(metrics.get("annual_turnover", float("inf"))) <= limits["annual_turnover"],
        "max_drawdown": float(metrics.get("max_drawdown_pct", -100.0)) >= limits["max_drawdown_pct_floor"],
        "cost_stress_base": bool(metrics.get("cost_stress_base_pass", False)),
        "cost_stress_harsh": bool(metrics.get("cost_stress_harsh_survives", False)),
        "no_lookahead": bool(metrics.get("no_lookahead_pass", False)),
        "event_ledger": bool(metrics.get("event_ledger_pass", False)),
        "dsr": float(metrics.get("dsr", 0.0)) >= limits["dsr"],
        "pbo": float(metrics.get("pbo", 1.0)) <= limits["pbo"],
    }
    fail_reasons = [name for name, passed in checks.items() if not passed]
    passed = not fail_reasons
    return BtcHardeningGateResult(
        strategy_id=strategy_id,
        status="candidate_passed_internal_gate" if passed else "candidate_gate_failed",
        passed=passed,
        fail_reasons=fail_reasons,
        checks=checks,
        thresholds=limits,
    )


def decide_paper_review_queue(candidate_gate_results: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    passed = [
        str(row.get("strategy_id", ""))
        for row in candidate_gate_results
        if bool(row.get("passed", False)) and str(row.get("status", "")) == "candidate_passed_internal_gate"
    ]
    queue = passed[:3]
    return {
        "paper_review_queue_locked": not (1 <= len(queue) <= 3),
        "paper_review_pending": queue if 1 <= len(queue) <= 3 else [],
        "reason": "requires_1_to_3_internal_gate_passes" if not (1 <= len(queue) <= 3) else "manual_review_required",
        "forbidden_states": sorted(BTC_HARDENING_FORBIDDEN_STATES),
        "max_state": "paper_review_pending" if queue else "candidate_gate_failed",
        "live_frozen": True,
        "paper_auto_start": False,
    }


def regime_pass_rate(regime_rows: Sequence[Mapping[str, Any]]) -> float:
    if not regime_rows:
        return 0.0
    return round(sum(1 for row in regime_rows if bool(row.get("passed", False))) / len(regime_rows), 6)
