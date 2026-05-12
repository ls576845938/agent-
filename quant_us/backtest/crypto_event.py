from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from math import sqrt
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd

from quant_us.backtest.data_bridge import SignalReplayStrategy
from quant_us.backtest.engine import BacktestBroker
from quant_us.backtest.ledger_pnl import ledger_states_at_times
from quant_us.backtest.unified_runner import UnifiedBacktestConfig, UnifiedBacktestResult, UnifiedBacktestRunner
from quant_us.core.events import MarketEvent
from quant_us.data.storage.data_manifest import DataManifestStore
from quant_us.portfolio.allocation import AllocationConfig
from quant_us.portfolio.position_sizer import PositionSizerConfig
from quant_us.portfolio.rebalance import RebalanceConfig
from quant_us.risk.pre_trade import PreTradeRiskConfig


MarketFrameLoader = Callable[..., pd.DataFrame]
SignalProvider = Callable[[pd.DataFrame, str, dict[str, Any]], pd.Series]

CRYPTO_VALIDATION_INTERVALS = ("5m", "15m", "1h", "4h", "1d")
CRYPTO_LONG_SAMPLE_MIN_BARS = {
    "5m": 30 * 24 * 12,
    "15m": 60 * 24 * 4,
    "1h": 180 * 24,
    "4h": 365 * 6,
    "1d": 730,
}
CRYPTO_COST_STRESS_SCENARIOS = (
    {
        "name": "base",
        "label": "Current costs",
        "commission_multiplier": 1.0,
        "slippage_multiplier": 1.0,
    },
    {
        "name": "fees_2x",
        "label": "Fees 2x",
        "commission_multiplier": 2.0,
        "slippage_multiplier": 1.0,
    },
    {
        "name": "slippage_2x",
        "label": "Slippage 2x",
        "commission_multiplier": 1.0,
        "slippage_multiplier": 2.0,
    },
    {
        "name": "costs_2x",
        "label": "Fees and slippage 2x",
        "commission_multiplier": 2.0,
        "slippage_multiplier": 2.0,
    },
    {
        "name": "fees_3x_slippage_5x",
        "label": "Fees 3x and slippage 5x",
        "commission_multiplier": 3.0,
        "slippage_multiplier": 5.0,
    },
    {
        "name": "slippage_5x",
        "label": "Slippage 5x",
        "commission_multiplier": 1.0,
        "slippage_multiplier": 5.0,
    },
    {
        "name": "costs_5x",
        "label": "Fees and slippage 5x",
        "commission_multiplier": 5.0,
        "slippage_multiplier": 5.0,
    },
    {
        "name": "tail_10x",
        "label": "Tail cost shock 10x",
        "commission_multiplier": 10.0,
        "slippage_multiplier": 10.0,
    },
)


@dataclass(frozen=True)
class CryptoCandidateGateThresholds:
    min_validation_sharpe: float = 1.0
    min_profit_factor: float = 1.15
    min_trade_count: int = 10
    min_total_return_pct: float = 0.0
    max_drawdown_pct_floor: float = -15.0
    min_cost_survival_rate_pct: float = 100.0
    min_ledger_consistency_pct: float = 100.0
    min_walk_forward_pass_rate_pct: float = 80.0
    min_regime_pass_rate_pct: float = 75.0


@dataclass
class CryptoEventBacktestArtifacts:
    mode: str
    summary: dict[str, float | int]
    chart: dict[str, list[dict[str, float | int | str]]]
    strategy_details: list[dict[str, Any]]
    latest_weights: list[dict[str, float | str]]
    diagnostics: dict[str, Any]
    unified: UnifiedBacktestResult


def run_crypto_event_backtest(
    *,
    source: str,
    symbol: str,
    interval: str,
    start: datetime,
    end: datetime,
    strategy_id: str,
    params: dict[str, Any] | None = None,
    capital: float = 100_000.0,
    cost: float | None = None,
    commission_rate: float | None = None,
    slippage: float | None = None,
    slippage_bps: float | None = None,
    sqlite_path: str = "",
    db_path: str = "",
    data_version: str = "",
    strategy_version: str = "",
    manifest_root: str | Path | None = None,
    signal_provider: SignalProvider | None = None,
    market_loader: MarketFrameLoader | None = None,
    market_events: list[MarketEvent] | None = None,
    target_weight: float = 0.90,
    min_cash_buffer_pct: float | None = None,
    min_trade_notional: float = 25.0,
    rebalance_buffer_pct: float = 0.05,
    long_only: bool = True,
    broker_factory: Callable[[UnifiedBacktestConfig], BacktestBroker] | None = None,
    run_id: str = "",
) -> CryptoEventBacktestArtifacts:
    """Run a single-symbol crypto backtest through the event-driven ledger path.

    The default loader/provider are lazy imports of the backend service and
    registry so the existing API can add a thin wrapper without duplicating
    execution semantics. Tests and batch jobs can inject either dependency.
    """

    requested_params = dict(params or {})
    loader = market_loader or _default_market_loader
    if market_events is None:
        frame = loader(
            source=source,
            symbol=symbol,
            interval=interval,
            start=start,
            end=end,
            db_path=db_path or sqlite_path,
        )
    else:
        frame = _frame_from_market_events(market_events)

    frame = _normalize_market_frame(frame, symbol=symbol)
    provider = signal_provider or _default_registry_signal_provider
    signal = provider(frame, strategy_id, requested_params).reindex(frame.index).fillna(0.0).clip(-1.0, 1.0)

    initial_cash = float(capital)
    commission = float(commission_rate if commission_rate is not None else (cost if cost is not None else 0.0001))
    slip_bps = float(slippage_bps if slippage_bps is not None else (slippage if slippage is not None else 1.0))
    execution_settings = _crypto_execution_settings(
        target_weight=target_weight,
        min_cash_buffer_pct=min_cash_buffer_pct,
        min_trade_notional=min_trade_notional,
        rebalance_buffer_pct=rebalance_buffer_pct,
        long_only=long_only,
    )

    config = UnifiedBacktestConfig(
        initial_cash=initial_cash,
        commission_rate=commission,
        slippage_bps=slip_bps,
        run_id=run_id or f"crypto_ed_{strategy_id}_{symbol.upper()}",
    )
    config = _with_crypto_execution_config(
        config,
        execution_settings=execution_settings,
    )
    runner = UnifiedBacktestRunner(config=config, broker_factory=broker_factory)
    if manifest_root is not None:
        runner.manifest_store = DataManifestStore(manifest_root)

    effective_data_version = data_version or _data_version(source, symbol, interval, start, end)
    effective_strategy_version = strategy_version or f"{strategy_id}:signal_replay_v1"
    strategy = SignalReplayStrategy(
        strategy_id=strategy_id,
        signal=signal,
        horizon="crypto_event_replay",
        params=requested_params,
        emit_on_change_only=True,
    )

    if market_events is None:
        unified = runner.run(
            strategies=[strategy],
            frame=frame,
            data_version=effective_data_version,
            strategy_version=effective_strategy_version,
        )
    else:
        unified = runner.run(
            strategies=[strategy],
            market_events_override=market_events,
            data_version=effective_data_version,
            strategy_version=effective_strategy_version,
        )

    ledger_rows = _ledger_timeline(unified, frame=frame, initial_cash=initial_cash)
    summary = _ledger_summary(
        ledger_rows["equity"],
        periods_per_year=_crypto_periods_per_year(interval),
        trade_count=len(unified.fills),
    )
    chart = _chart_payload(frame=frame, unified=unified, ledger_rows=ledger_rows)
    final_equity = float(ledger_rows["equity"].iloc[-1]) if not ledger_rows["equity"].empty else initial_cash
    final_position_value = float(ledger_rows["exposure"].iloc[-1]) if not ledger_rows["exposure"].empty else 0.0
    latest_weight = final_position_value / max(final_equity, 1.0)

    diagnostics: dict[str, Any] = {
        "engine": "event_driven",
        "asset_class": "crypto",
        "source": source,
        "symbol": symbol.upper(),
        "interval": interval,
        "sample": _crypto_sample_summary(frame, interval=interval),
        "strategy_id": strategy_id,
        "strategy_params": requested_params,
        "data_version": effective_data_version,
        "strategy_version": effective_strategy_version,
        "manifest_id": unified.manifest_id,
        "manifest_path": unified.manifest_path,
        "pnl_source": "ledger_fills",
        "execution_semantics": unified.event_driven.metadata.get("execution_semantics"),
        "connection_health": runner.connection_health(),
        "orders": len(unified.orders),
        "fills": len(unified.fills),
        "ledger_equity_consistent": unified.equity_consistent,
        "ledger_consistency_msg": unified.equity_consistency_msg,
        "ledger_final_equity": round(final_equity, 6),
        "ledger_total_fees": round(float(unified.ledger_curve.total_fees), 6),
        "ledger_curve_points": len(ledger_rows["equity"]),
        "run_id": unified.run_id,
        "execution_config": execution_settings,
        "event_counts": unified.evidence.get("events", {}),
        "regime_split": _crypto_regime_split_summary(
            frame=frame,
            equity=ledger_rows["equity"],
            fills=unified.fills,
            periods_per_year=_crypto_periods_per_year(interval),
        ),
        "risk": unified.evidence.get("risk", {}),
        "reconciliation": unified.evidence.get("reconciliation", {}).get("summary", {}),
        "ledger_artifact_path": unified.evidence.get("ledger_artifact_path", ""),
        "ledger_hash": unified.evidence.get("ledger_hash", ""),
        "fills_hash": unified.evidence.get("fills_hash", ""),
        "data_manifest": unified.evidence.get("data_manifest", {}),
        "missing_data_manifest": bool(unified.evidence.get("missing_data_manifest", False)),
        "determinism_verified": bool(unified.determinism_verified),
    }

    return CryptoEventBacktestArtifacts(
        mode="crypto_event",
        summary=summary,
        chart=chart,
        strategy_details=[
            {
                "strategy_id": strategy_id,
                "version": effective_strategy_version,
                "params": requested_params,
                "signal_points": int(len(signal)),
            }
        ],
        latest_weights=[
            {
                "strategy_id": strategy_id,
                "display_name": strategy_id,
                "weight": round(float(latest_weight), 6),
            }
        ],
        diagnostics=diagnostics,
        unified=unified,
    )


def _with_crypto_execution_config(
    config: UnifiedBacktestConfig,
    *,
    execution_settings: dict[str, float | bool],
) -> UnifiedBacktestConfig:
    target_weight = float(execution_settings["target_weight"])
    risk_limit = float(execution_settings["risk_limit"])
    cash_reserve = float(execution_settings["cash_reserve_weight"])
    min_trade_notional = float(execution_settings["min_trade_notional"])
    rebalance_buffer_pct = float(execution_settings["rebalance_buffer_pct"])
    long_only = bool(execution_settings["long_only"])
    config.sizing = PositionSizerConfig(
        default_strategy_weight=target_weight,
        max_symbol_weight=risk_limit,
        long_only=long_only,
    )
    config.allocation = AllocationConfig(
        max_symbol_weight=risk_limit,
        cash_reserve_weight=cash_reserve,
        max_gross_exposure=risk_limit,
    )
    config.rebalance = RebalanceConfig(min_trade_notional=min_trade_notional, min_weight_change=rebalance_buffer_pct)
    config.risk = PreTradeRiskConfig(
        max_symbol_weight=risk_limit,
        max_gross_exposure=risk_limit,
        max_order_notional_pct=min(1.0, risk_limit + 0.10),
        min_cash_buffer_pct=cash_reserve,
        long_only=long_only,
        skip_session_check=True,
    )
    return config


def _crypto_execution_settings(
    *,
    target_weight: float,
    min_cash_buffer_pct: float | None,
    min_trade_notional: float,
    rebalance_buffer_pct: float,
    long_only: bool,
) -> dict[str, float | bool]:
    effective_target_weight = max(0.0, min(float(target_weight), 0.98))
    implied_cash_buffer = max(0.02, 1.0 - effective_target_weight)
    requested_cash_buffer = 0.0 if min_cash_buffer_pct is None else float(min_cash_buffer_pct)
    cash_reserve = max(implied_cash_buffer, requested_cash_buffer)
    return {
        "target_weight": effective_target_weight,
        "risk_limit": min(1.0, max(effective_target_weight + 0.10, 0.10)),
        "cash_reserve_weight": cash_reserve,
        "min_cash_buffer_pct": cash_reserve,
        "min_trade_notional": max(0.0, float(min_trade_notional)),
        "rebalance_buffer_pct": max(0.0, float(rebalance_buffer_pct)),
        "long_only": bool(long_only),
    }


def default_crypto_cost_stress_scenarios(max_scenarios: int | None = None) -> list[dict[str, Any]]:
    """Return the standard BTC closure stress grid without mutating shared state."""

    scenarios = [dict(row) for row in CRYPTO_COST_STRESS_SCENARIOS]
    if max_scenarios is None:
        return scenarios
    return scenarios[: max(1, min(int(max_scenarios), len(scenarios)))]


def summarize_crypto_interval_validation(
    *,
    target_intervals: list[str] | tuple[str, ...] = CRYPTO_VALIDATION_INTERVALS,
    quality_results: list[dict[str, Any]] | None = None,
    resample_results: list[dict[str, Any]] | None = None,
    coverage_floor_pct: float = 99.0,
    quality_score_floor: float = 95.0,
    min_bars_by_interval: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Summarize multi-timeframe BTC data checks for closure gating."""

    min_bars = {**CRYPTO_LONG_SAMPLE_MIN_BARS, **(min_bars_by_interval or {})}
    quality_by_interval = {
        str(row.get("interval") or row.get("target_interval")): row for row in quality_results or []
    }
    resample_by_interval = {
        str(row.get("target_interval") or row.get("interval")): row for row in resample_results or []
    }
    rows: list[dict[str, Any]] = []
    blockers: list[str] = []

    for interval in target_intervals:
        interval_text = str(interval)
        quality = quality_by_interval.get(interval_text, {})
        resample = resample_by_interval.get(interval_text, {})
        row_count = int(quality.get("row_count") or resample.get("rows_written") or 0)
        coverage = float(quality.get("coverage_pct", resample.get("coverage_pct", 0.0)) or 0.0)
        quality_score = float(quality.get("quality_score", resample.get("quality_score", 0.0)) or 0.0)
        required_bars = int(min_bars.get(interval_text, 0))
        row_blockers: list[str] = []

        if not quality:
            row_blockers.append("missing quality result")
        if not resample:
            row_blockers.append("missing resample result")
        if quality and not bool(quality.get("is_usable", False)):
            row_blockers.append("quality result is not usable")
        if coverage < coverage_floor_pct:
            row_blockers.append(f"coverage {coverage}% < {coverage_floor_pct}%")
        if quality_score < quality_score_floor:
            row_blockers.append(f"quality_score {quality_score} < {quality_score_floor}")
        if required_bars and row_count < required_bars:
            row_blockers.append(f"row_count {row_count} < long_sample_min_bars {required_bars}")

        rows.append(
            {
                "interval": interval_text,
                "status": "pass" if not row_blockers else "fail",
                "row_count": row_count,
                "min_required_bars": required_bars,
                "coverage_pct": round(coverage, 4),
                "quality_score": round(quality_score, 4),
                "blockers": row_blockers,
                "data_version": quality.get("data_version") or resample.get("data_version", ""),
                "fingerprint": quality.get("fingerprint") or resample.get("fingerprint", ""),
            }
        )
        blockers.extend(f"{interval_text}: {blocker}" for blocker in row_blockers)

    return {
        "status": "pass" if not blockers else "fail",
        "target_intervals": [str(item) for item in target_intervals],
        "coverage_floor_pct": coverage_floor_pct,
        "quality_score_floor": quality_score_floor,
        "intervals": rows,
        "blockers": blockers,
    }


def qualify_crypto_candidates(
    candidates: list[dict[str, Any]],
    *,
    cost_stress_by_candidate: dict[str, dict[str, Any]] | None = None,
    walk_forward_by_candidate: dict[str, dict[str, Any]] | None = None,
    event_backtest_by_candidate: dict[str, dict[str, Any]] | None = None,
    max_selected: int = 2,
    thresholds: CryptoCandidateGateThresholds | None = None,
) -> dict[str, Any]:
    """Mark only candidates passing durable event/cost/WF/regime gates as selected."""

    limits = thresholds or CryptoCandidateGateThresholds()
    cost_map = cost_stress_by_candidate or {}
    walk_map = walk_forward_by_candidate or {}
    event_map = event_backtest_by_candidate or {}
    rows: list[dict[str, Any]] = []

    for candidate in candidates:
        key = _crypto_candidate_key(candidate)
        strategy_id = str(candidate.get("strategy_id", ""))
        cost = cost_map.get(key) or cost_map.get(strategy_id) or {}
        walk_forward = walk_map.get(key) or walk_map.get(strategy_id) or {}
        event_backtest = event_map.get(key) or event_map.get(strategy_id) or {}
        screening_metrics = _crypto_candidate_screening_metrics(
            candidate,
            cost_stress=cost,
            walk_forward=walk_forward,
        )
        blockers = _crypto_candidate_blockers(
            candidate,
            cost_stress=cost,
            walk_forward=walk_forward,
            event_backtest=event_backtest,
            thresholds=limits,
        )
        row = dict(candidate)
        row["candidate_key"] = key
        row["qualified"] = not blockers
        row["selected"] = False
        row["screening_metrics"] = screening_metrics
        row["qualification_blockers"] = blockers
        rows.append(row)

    rows.sort(key=_crypto_candidate_selection_sort_key)

    selected_remaining = max(0, int(max_selected))
    for row in rows:
        if selected_remaining <= 0:
            break
        if bool(row["qualified"]):
            row["selected"] = True
            selected_remaining -= 1

    return {
        "status": "completed",
        "thresholds": asdict(limits),
        "candidate_count": len(rows),
        "qualified_count": sum(1 for row in rows if row["qualified"]),
        "selected_count": sum(1 for row in rows if row["selected"]),
        "candidates": rows,
        "selected_candidates": [row for row in rows if row["selected"]],
        "blockers": [
            f"{row['candidate_key']}: {blocker}"
            for row in rows
            for blocker in row["qualification_blockers"]
        ],
    }


def _crypto_candidate_key(candidate: dict[str, Any]) -> str:
    strategy_id = str(candidate.get("strategy_id", "unknown"))
    params = candidate.get("parameters") or candidate.get("params") or {}
    if not isinstance(params, dict) or not params:
        return strategy_id
    parts = ",".join(f"{key}={params[key]}" for key in sorted(params))
    return f"{strategy_id}|{parts}"


def _crypto_candidate_selection_sort_key(candidate: dict[str, Any]) -> tuple[Any, ...]:
    rank = candidate.get("rank")
    validation = candidate.get("validation") or {}
    screening_metrics = candidate.get("screening_metrics") or {}
    has_rank = isinstance(rank, (int, float))
    cost_sensitivity = _finite_sort_value(screening_metrics.get("cost_sensitivity"))
    annual_turnover_pct = _finite_sort_value(screening_metrics.get("annual_turnover_pct"))
    avg_holding_bars = _finite_desc_sort_value(screening_metrics.get("avg_holding_bars"))
    return (
        0 if has_rank else 1,
        float(rank) if has_rank else 0.0,
        cost_sensitivity,
        annual_turnover_pct,
        avg_holding_bars,
        -float(candidate.get("score", 0.0)),
        -float(validation.get("sharpe_ratio", 0.0)),
        -float(validation.get("total_return_pct", 0.0)),
        abs(float(validation.get("max_drawdown_pct", 0.0))),
        str(candidate.get("candidate_key", "")),
    )


def _crypto_candidate_blockers(
    candidate: dict[str, Any],
    *,
    cost_stress: dict[str, Any],
    walk_forward: dict[str, Any],
    event_backtest: dict[str, Any],
    thresholds: CryptoCandidateGateThresholds,
) -> list[str]:
    validation = candidate.get("validation") or {}
    blockers: list[str] = []

    if float(validation.get("total_return_pct", 0.0)) <= thresholds.min_total_return_pct:
        blockers.append("validation total_return is not positive")
    if float(validation.get("sharpe_ratio", 0.0)) < thresholds.min_validation_sharpe:
        blockers.append(f"validation sharpe < {thresholds.min_validation_sharpe}")
    if float(validation.get("profit_factor", 0.0)) < thresholds.min_profit_factor:
        blockers.append(f"validation profit_factor < {thresholds.min_profit_factor}")
    if float(validation.get("max_drawdown_pct", -100.0)) < thresholds.max_drawdown_pct_floor:
        blockers.append(f"validation max_drawdown < {thresholds.max_drawdown_pct_floor}%")
    if int(validation.get("trade_count", 0)) < thresholds.min_trade_count:
        blockers.append(f"validation trade_count < {thresholds.min_trade_count}")

    event_diagnostics = event_backtest.get("diagnostics", event_backtest)
    if not event_diagnostics:
        blockers.append("missing event backtest diagnostics")
    else:
        if str(event_diagnostics.get("engine", "")) != "event_driven":
            blockers.append("event backtest is not event_driven")
        if str(event_diagnostics.get("pnl_source", "")) != "ledger_fills":
            blockers.append("event backtest PnL is not ledger_fills")
        if event_diagnostics.get("ledger_equity_consistent") is not True:
            blockers.append("event backtest ledger consistency was not proven")

    if not cost_stress:
        blockers.append("missing cost stress result")
    else:
        if str(cost_stress.get("engine", "")) != "event_driven":
            blockers.append("cost stress is not event_driven")
        if float(cost_stress.get("survival_rate_pct", 0.0)) < thresholds.min_cost_survival_rate_pct:
            blockers.append(f"cost survival_rate < {thresholds.min_cost_survival_rate_pct}%")
        if float(cost_stress.get("ledger_consistency_pct", 0.0)) < thresholds.min_ledger_consistency_pct:
            blockers.append(f"cost ledger_consistency < {thresholds.min_ledger_consistency_pct}%")

    stability = walk_forward.get("stability", {}) if walk_forward else {}
    if not walk_forward:
        blockers.append("missing walk-forward result")
    else:
        pass_rate = float(stability.get("fold_pass_rate_pct") or stability.get("pass_rate_pct", 0.0))
        if pass_rate < thresholds.min_walk_forward_pass_rate_pct:
            blockers.append(f"walk_forward pass_rate < {thresholds.min_walk_forward_pass_rate_pct}%")
        if float(stability.get("ledger_consistency_pct", 0.0)) < thresholds.min_ledger_consistency_pct:
            blockers.append(f"walk_forward ledger_consistency < {thresholds.min_ledger_consistency_pct}%")
        regime_pass_rate = float(
            stability.get("regime_pass_rate_pct", walk_forward.get("regime_pass_rate_pct", 0.0))
        )
        if regime_pass_rate < thresholds.min_regime_pass_rate_pct:
            blockers.append(f"regime pass_rate < {thresholds.min_regime_pass_rate_pct}%")

    runtime_hints = _crypto_candidate_runtime_hints(candidate)
    max_annual_turnover_pct = _float_or_none(runtime_hints.get("max_annual_turnover_pct"))
    annual_turnover_pct = _crypto_candidate_annual_turnover_pct(candidate, walk_forward)
    if (
        max_annual_turnover_pct is not None
        and annual_turnover_pct is not None
        and annual_turnover_pct > max_annual_turnover_pct
    ):
        blockers.append(f"annual turnover > {max_annual_turnover_pct}%")

    min_holding_bars = _float_or_none(runtime_hints.get("min_holding_bars"))
    avg_holding_bars = _crypto_candidate_avg_holding_bars(candidate, walk_forward)
    if min_holding_bars is not None and avg_holding_bars is not None and avg_holding_bars < min_holding_bars:
        blockers.append(f"avg holding bars < {min_holding_bars}")

    if runtime_hints.get("cost_aware_filter"):
        cost_sensitivity = _crypto_candidate_cost_sensitivity(candidate, cost_stress)
        if cost_sensitivity is not None and cost_sensitivity > 0.5:
            blockers.append("cost sensitivity > 0.5")

    return blockers


def _crypto_candidate_screening_metrics(
    candidate: dict[str, Any],
    *,
    cost_stress: dict[str, Any],
    walk_forward: dict[str, Any],
) -> dict[str, float]:
    metrics: dict[str, float] = {}
    annual_turnover_pct = _crypto_candidate_annual_turnover_pct(candidate, walk_forward)
    if annual_turnover_pct is not None:
        metrics["annual_turnover_pct"] = round(annual_turnover_pct, 4)
    avg_holding_bars = _crypto_candidate_avg_holding_bars(candidate, walk_forward)
    if avg_holding_bars is not None:
        metrics["avg_holding_bars"] = round(avg_holding_bars, 4)
    cost_sensitivity = _crypto_candidate_cost_sensitivity(candidate, cost_stress)
    if cost_sensitivity is not None:
        metrics["cost_sensitivity"] = round(cost_sensitivity, 6)
    return metrics


def _crypto_candidate_runtime_hints(candidate: dict[str, Any]) -> dict[str, Any]:
    research_metadata = candidate.get("research_metadata")
    if not isinstance(research_metadata, dict):
        return {}
    runtime_hints = research_metadata.get("runtime_hints")
    return runtime_hints if isinstance(runtime_hints, dict) else {}


def _crypto_candidate_annual_turnover_pct(
    candidate: dict[str, Any],
    walk_forward: dict[str, Any],
) -> float | None:
    stability = walk_forward.get("stability", {}) if isinstance(walk_forward, dict) else {}
    for payload, key in (
        (stability, "oos_avg_turnover_pct"),
        (candidate.get("turnover"), "annual_turnover_pct"),
        (candidate.get("metrics"), "annual_turnover_pct"),
        (candidate.get("validation"), "annual_turnover_pct"),
    ):
        if isinstance(payload, dict):
            value = _float_or_none(payload.get(key))
            if value is not None:
                return value
    return None


def _crypto_candidate_avg_holding_bars(
    candidate: dict[str, Any],
    walk_forward: dict[str, Any],
) -> float | None:
    stability = walk_forward.get("stability", {}) if isinstance(walk_forward, dict) else {}
    for payload, key in (
        (stability, "oos_avg_holding_bars"),
        (candidate.get("holding_period"), "avg_holding_bars"),
        (candidate.get("metrics"), "avg_holding_bars"),
        (candidate.get("validation"), "avg_holding_bars"),
    ):
        if isinstance(payload, dict):
            value = _float_or_none(payload.get(key))
            if value is not None:
                return value
    return None


def _crypto_candidate_cost_sensitivity(
    candidate: dict[str, Any],
    cost_stress: dict[str, Any],
) -> float | None:
    for payload, key in (
        (cost_stress, "cost_sensitivity"),
        (candidate.get("metrics"), "cost_sensitivity"),
        (candidate.get("validation"), "cost_sensitivity"),
    ):
        if isinstance(payload, dict):
            value = _float_or_none(payload.get(key))
            if value is not None:
                return value
    return None


def _float_or_none(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _finite_sort_value(value: Any) -> float:
    parsed = _float_or_none(value)
    return parsed if parsed is not None else float("inf")


def _finite_desc_sort_value(value: Any) -> float:
    parsed = _float_or_none(value)
    return -parsed if parsed is not None else float("inf")


def _crypto_sample_summary(frame: pd.DataFrame, *, interval: str) -> dict[str, Any]:
    if frame.empty:
        return {
            "bar_count": 0,
            "start": "",
            "end": "",
            "duration_days": 0.0,
            "min_required_bars": CRYPTO_LONG_SAMPLE_MIN_BARS.get(interval, 0),
            "long_sample_pass": False,
        }
    start = pd.Timestamp(frame.index.min())
    end = pd.Timestamp(frame.index.max())
    if start.tzinfo is None:
        start = start.tz_localize("UTC")
    else:
        start = start.tz_convert("UTC")
    if end.tzinfo is None:
        end = end.tz_localize("UTC")
    else:
        end = end.tz_convert("UTC")
    required_bars = int(CRYPTO_LONG_SAMPLE_MIN_BARS.get(interval, 0))
    bar_count = int(len(frame))
    duration_days = max(0.0, float((end - start).total_seconds()) / 86_400.0)
    return {
        "bar_count": bar_count,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "duration_days": round(duration_days, 4),
        "min_required_bars": required_bars,
        "long_sample_pass": bool(required_bars and bar_count >= required_bars),
    }


def _default_market_loader(**kwargs: Any) -> pd.DataFrame:
    from backend.app.services.market_data import load_market_frame

    return load_market_frame(**kwargs)


def _default_registry_signal_provider(
    frame: pd.DataFrame,
    strategy_id: str,
    params: dict[str, Any],
) -> pd.Series:
    from backend.app.domain.strategy_registry import strategy_registry

    pack = strategy_registry.get(strategy_id).generate(frame, params=params)
    return pack.signal


def _normalize_market_frame(frame: pd.DataFrame, *, symbol: str) -> pd.DataFrame:
    data = frame.copy()
    if not isinstance(data.index, pd.DatetimeIndex):
        ts_col = "timestamp_utc" if "timestamp_utc" in data.columns else "timestamp"
        data[ts_col] = pd.to_datetime(data[ts_col], utc=True)
        data = data.set_index(ts_col)
    data.index = pd.to_datetime(data.index, utc=True)
    data = data.sort_index()
    if "symbol" not in data.columns:
        data["symbol"] = symbol.upper()
    else:
        data["symbol"] = data["symbol"].fillna(symbol).astype(str).str.upper()
    return data


def _frame_from_market_events(events: list[MarketEvent]) -> pd.DataFrame:
    rows = []
    for event in events:
        if event.bar is None:
            raise ValueError("MarketEvent.bar is required")
        bar = event.bar
        rows.append(
            {
                "timestamp": bar.timestamp_utc,
                "symbol": bar.symbol,
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "volume": bar.volume,
                "vwap": bar.vwap,
                "trade_count": bar.trade_count,
            }
        )
    return pd.DataFrame(rows)


def _ledger_timeline(
    unified: UnifiedBacktestResult,
    *,
    frame: pd.DataFrame,
    initial_cash: float,
) -> dict[str, pd.Series]:
    equity: dict[pd.Timestamp, float] = {}
    exposure: dict[pd.Timestamp, float] = {}
    net_units: dict[pd.Timestamp, float] = {}
    timestamps: list[datetime] = []
    market_prices_by_time: dict[datetime, dict[str, float]] = {}

    for timestamp, row in frame.iterrows():
        ts = pd.Timestamp(timestamp).tz_convert("UTC").to_pydatetime()
        symbol = str(row.get("symbol", "")).upper()
        close = float(row["close"])
        timestamps.append(ts)
        market_prices_by_time[ts] = {symbol: close}

    ledger_states = ledger_states_at_times(
        unified.fills,
        timestamps,
        initial_cash,
        market_prices_by_time=market_prices_by_time,
    )

    for timestamp, row in frame.iterrows():
        ts = pd.Timestamp(timestamp).tz_convert("UTC").to_pydatetime()
        symbol = str(row.get("symbol", "")).upper()
        positions, _cash, position_value, ledger_equity = ledger_states[ts]
        idx = pd.Timestamp(ts)
        equity[idx] = float(ledger_equity)
        exposure[idx] = abs(float(position_value))
        net_units[idx] = float(positions.get(symbol, 0.0))

    return {
        "equity": pd.Series(equity).sort_index(),
        "exposure": pd.Series(exposure).sort_index(),
        "net_units": pd.Series(net_units).sort_index(),
    }


def _ledger_summary(
    equity: pd.Series,
    *,
    periods_per_year: float,
    trade_count: int,
) -> dict[str, float | int]:
    if equity.empty:
        return {
            "total_return_pct": 0.0,
            "annual_return_pct": 0.0,
            "annual_volatility_pct": 0.0,
            "sharpe_ratio": 0.0,
            "sortino_ratio": 0.0,
            "max_drawdown_pct": 0.0,
            "calmar_ratio": 0.0,
            "win_rate_pct": 0.0,
            "profit_factor": 0.0,
            "trade_count": trade_count,
        }

    returns = equity.pct_change().fillna(0.0)
    total_return = float(equity.iloc[-1] / equity.iloc[0] - 1.0) if equity.iloc[0] else 0.0
    annual_return = (
        float(equity.iloc[-1] / equity.iloc[0]) ** (periods_per_year / max(1, len(equity))) - 1.0
        if equity.iloc[0] > 0
        else 0.0
    )
    std = float(returns.std(ddof=0))
    annual_volatility = std * sqrt(periods_per_year)
    downside = returns[returns < 0]
    downside_std = float(downside.std(ddof=0))
    sharpe = float(returns.mean() / std * sqrt(periods_per_year)) if std > 0 else 0.0
    sortino = float(returns.mean() / downside_std * sqrt(periods_per_year)) if downside_std > 0 else 0.0
    drawdown = equity / equity.cummax() - 1.0
    max_drawdown = float(drawdown.min()) if not drawdown.empty else 0.0
    calmar = float(annual_return / abs(max_drawdown)) if max_drawdown < 0 else 0.0
    active = returns[returns != 0.0]
    win_rate = float((active > 0).mean()) if not active.empty else 0.0
    gains = float(returns[returns > 0].sum())
    losses = abs(float(returns[returns < 0].sum()))
    profit_factor = gains / losses if losses > 0 else (999.0 if gains > 0 else 0.0)
    return {
        "total_return_pct": round(total_return * 100.0, 4),
        "annual_return_pct": round(annual_return * 100.0, 4),
        "annual_volatility_pct": round(annual_volatility * 100.0, 4),
        "sharpe_ratio": round(sharpe, 4),
        "sortino_ratio": round(sortino, 4),
        "max_drawdown_pct": round(max_drawdown * 100.0, 4),
        "calmar_ratio": round(calmar, 4),
        "win_rate_pct": round(win_rate * 100.0, 4),
        "profit_factor": round(profit_factor, 4) if np.isfinite(profit_factor) else 0.0,
        "trade_count": trade_count,
    }


def _crypto_regime_split_summary(
    *,
    frame: pd.DataFrame,
    equity: pd.Series,
    fills: list[Any],
    periods_per_year: float,
) -> dict[str, Any]:
    if frame.empty or equity.empty:
        return {"status": "empty", "pass_rate_pct": 0.0, "regimes": [], "blockers": ["empty frame or equity"]}

    aligned_equity = equity.reindex(pd.to_datetime(frame.index, utc=True)).dropna()
    min_rows = max(5, int(len(frame) * 0.05))
    regimes: list[dict[str, Any]] = []
    blockers: list[str] = []
    for name, label, mask in _crypto_regime_masks(frame):
        mask = mask.reindex(frame.index).fillna(False)
        regime_frame = frame.loc[mask]
        if len(regime_frame) < min_rows:
            blockers.append(f"{name} bar_count {len(regime_frame)} < {min_rows}")
            continue
        regime_index = pd.to_datetime(regime_frame.index, utc=True)
        regime_equity = aligned_equity.reindex(regime_index).dropna()
        if regime_equity.empty:
            blockers.append(f"{name} has no aligned ledger equity")
            continue
        fill_count = _fill_count_for_index(fills, regime_index)
        summary = _ledger_summary(
            regime_equity,
            periods_per_year=periods_per_year,
            trade_count=fill_count,
        )
        survives = _crypto_regime_survives(summary)
        regimes.append(
            {
                "name": name,
                "label": label,
                "bar_count": int(len(regime_frame)),
                "coverage_pct": round(len(regime_frame) / max(1, len(frame)) * 100.0, 4),
                "survives": survives,
                "summary": summary,
            }
        )

    pass_rate = sum(1 for row in regimes if row["survives"]) / max(1, len(regimes)) * 100.0
    return {
        "status": "pass" if regimes and pass_rate >= 75.0 else "fail",
        "pass_rate_pct": round(pass_rate, 4),
        "min_rows": min_rows,
        "regimes": regimes,
        "blockers": blockers,
    }


def _crypto_regime_masks(frame: pd.DataFrame) -> list[tuple[str, str, pd.Series]]:
    close = frame["close"].astype(float)
    returns = close.pct_change().fillna(0.0)
    window = max(5, min(96, len(frame) // 8))
    trend = close.pct_change(window).fillna(0.0)
    volatility = returns.rolling(window=window, min_periods=max(3, window // 3)).std(ddof=0)
    fallback_volatility = float(returns.std(ddof=0)) if len(returns) > 1 else 0.0
    volatility = volatility.fillna(fallback_volatility)
    volatility_median = float(volatility.median()) if not volatility.empty else 0.0
    return [
        ("uptrend", "Uptrend", trend > 0.0),
        ("downtrend", "Downtrend", trend <= 0.0),
        ("high_volatility", "High volatility", volatility >= volatility_median),
        ("low_volatility", "Low volatility", volatility < volatility_median),
    ]


def _crypto_regime_survives(summary: dict[str, float | int]) -> bool:
    return (
        float(summary["total_return_pct"]) > -5.0
        and float(summary["profit_factor"]) >= 0.9
        and float(summary["max_drawdown_pct"]) > -20.0
    )


def _fill_count_for_index(fills: list[Any], index: pd.DatetimeIndex) -> int:
    if index.empty:
        return 0
    timestamps = set(pd.to_datetime(index, utc=True))
    count = 0
    for fill in fills:
        filled_at = pd.Timestamp(getattr(fill, "filled_at", None))
        if filled_at.tzinfo is None:
            filled_at = filled_at.tz_localize("UTC")
        else:
            filled_at = filled_at.tz_convert("UTC")
        if filled_at in timestamps:
            count += 1
    return count


def _chart_payload(
    *,
    frame: pd.DataFrame,
    unified: UnifiedBacktestResult,
    ledger_rows: dict[str, pd.Series],
) -> dict[str, list[dict[str, float | int | str]]]:
    equity = ledger_rows["equity"]
    drawdown = (equity / equity.cummax() - 1.0).fillna(0.0) * 100.0 if not equity.empty else equity
    return {
        "candles": [
            {
                "time": _to_epoch(timestamp),
                "open": round(float(row["open"]), 6),
                "high": round(float(row["high"]), 6),
                "low": round(float(row["low"]), 6),
                "close": round(float(row["close"]), 6),
            }
            for timestamp, row in frame.iterrows()
        ],
        "markers": [
            {
                "time": _to_epoch(fill.filled_at),
                "position": "belowBar" if fill.side.value == "buy" else "aboveBar",
                "color": "#00C853" if fill.side.value == "buy" else "#D50000",
                "shape": "arrowUp" if fill.side.value == "buy" else "arrowDown",
                "text": f"{fill.side.value.upper()} {fill.quantity:.8f} @ {fill.price:.2f}",
            }
            for fill in unified.fills
        ],
        "equity": _series_payload(equity),
        "drawdown": _series_payload(drawdown),
        "exposure": _series_payload(ledger_rows["exposure"]),
        "net_units": _series_payload(ledger_rows["net_units"]),
    }


def _series_payload(series: pd.Series) -> list[dict[str, float | int]]:
    return [
        {"time": _to_epoch(timestamp), "value": round(float(value), 6)}
        for timestamp, value in series.items()
    ]


def _to_epoch(timestamp: datetime | pd.Timestamp) -> int:
    ts = pd.Timestamp(timestamp)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    return int(ts.timestamp())


def _data_version(source: str, symbol: str, interval: str, start: datetime, end: datetime) -> str:
    start_s = pd.Timestamp(start).tz_convert("UTC").isoformat() if pd.Timestamp(start).tzinfo else pd.Timestamp(start).tz_localize("UTC").isoformat()
    end_s = pd.Timestamp(end).tz_convert("UTC").isoformat() if pd.Timestamp(end).tzinfo else pd.Timestamp(end).tz_localize("UTC").isoformat()
    return f"crypto:{source}:{symbol.upper()}:{interval}:{start_s}:{end_s}"


def _crypto_periods_per_year(interval: str) -> float:
    normalized = interval.strip().lower()
    if normalized.endswith("min"):
        minutes = float(normalized[:-3] or 1)
        return 365.0 * 24.0 * 60.0 / minutes
    unit = normalized[-1:]
    amount_text = normalized[:-1] or "1"
    try:
        amount = float(amount_text)
    except ValueError:
        amount = 1.0
    if unit == "m":
        return 365.0 * 24.0 * 60.0 / amount
    if unit == "h":
        return 365.0 * 24.0 / amount
    if unit == "d":
        return 365.0 / amount
    return 365.0
