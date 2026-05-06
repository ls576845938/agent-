"""Unified backtest runner — event-driven engine as canonical path.

This module enforces that all promotion-gate-level backtests go through the
full order lifecycle: Signal → TargetPosition → OrderIntent → Risk Check →
Broker Order → Fill → Ledger → PnL.

The vectorized _simulate() path is explicitly marked as APPROXIMATE and should
only be used for fast research scanning, not for promotion decisions.
"""

from __future__ import annotations

import random as _random
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd

from quant_us.backtest.corporate_actions_ledger import LedgerAdjustmentLog
from quant_us.backtest.data_bridge import EventDrivenBacktestRunner, bars_from_dataframe
from quant_us.backtest.engine import BacktestConfig, BacktestResult, EventDrivenBacktestEngine
from quant_us.backtest.gap_session import GapConfig, SessionConfig, classify_session, is_bar_tradable
from quant_us.backtest.ledger_pnl import LedgerEquityCurve, derive_equity_from_fills, verify_equity_consistency
from quant_us.backtest.turnover import TurnoverReport, compute_turnover
from quant_us.core.calendar import USEquityCalendar
from quant_us.core.types import new_id
from quant_us.data.storage.data_manifest import DataManifestStore
from quant_us.strategies.base import Strategy


@dataclass
class UnifiedBacktestResult:
    """Canonical backtest result with both event-driven and ledger-verified data."""

    run_id: str
    event_driven: BacktestResult
    ledger_curve: LedgerEquityCurve
    equity_consistent: bool
    equity_consistency_msg: str
    data_version: str = ""
    strategy_version: str = ""
    manifest_id: str = ""
    turnover_report: TurnoverReport | None = None
    gap_skipped_bars: list[dict] = field(default_factory=list)
    determinism_verified: bool = False
    determinism_details: dict | None = None

    @property
    def summary(self) -> dict[str, float | int]:
        return self.event_driven.summary

    @property
    def fills(self) -> list:
        return self.event_driven.fills

    @property
    def orders(self) -> list:
        return self.event_driven.orders

    @property
    def snapshots(self) -> list:
        return self.event_driven.snapshots

    @property
    def is_trustworthy(self) -> bool:
        """Backtest is trustworthy if equity is consistent and turnover is not excessive."""
        if not self.equity_consistent:
            return False
        if self.turnover_report is not None and self.turnover_report.excessive_turnover_days > 0:
            return False
        return True


@dataclass
class UnifiedBacktestConfig:
    initial_cash: float = 100_000.0
    commission_rate: float = 0.0001
    slippage_bps: float = 1.0
    fill_ratio: float = 1.0
    volume_participation_cap_pct: float = 5.0
    max_daily_turnover_pct: float = 200.0
    gap_config: GapConfig | None = None
    session_config: SessionConfig | None = None
    save_replay_path: str | None = None
    verify_determinism: bool = False
    adjustment_log: LedgerAdjustmentLog | None = None
    run_id: str = field(default_factory=lambda: new_id("ubt"))


class UnifiedBacktestRunner:
    """Run backtests through the canonical event-driven + ledger path.

    This is the ONLY runner that should be used for promotion gate decisions.
    """

    def __init__(
        self,
        config: UnifiedBacktestConfig | None = None,
        calendar: USEquityCalendar | None = None,
    ) -> None:
        self.config = config or UnifiedBacktestConfig()
        self.calendar = calendar or USEquityCalendar.with_holidays()
        self.manifest_store = DataManifestStore()

    def run(
        self,
        strategies: list[Strategy],
        frame: pd.DataFrame | None = None,
        features_frame: pd.DataFrame | None = None,
        data_version: str = "",
        strategy_version: str = "",
        bars_override: list | None = None,
    ) -> UnifiedBacktestResult:
        _random.seed(42)
        np.random.seed(42)

        import subprocess as _subprocess
        start_dt = datetime.now(timezone.utc)

        if bars_override is not None:
            bars = list(bars_override)
        elif frame is not None:
            bars = bars_from_dataframe(frame)
        else:
            raise ValueError("Either frame or bars_override must be provided")

        # Pre-process bars when gap or session config is set
        gap_skipped_bars: list[dict] = []
        if self.config.gap_config is not None or self.config.session_config is not None:
            filtered: list[Bar] = []
            for b in bars:
                # Classify session (logging only — filtering per session not enforced here)
                if self.config.session_config:
                    _session = classify_session(b, self.config.session_config)

                # Skip untradeable bars
                if self.config.gap_config is not None:
                    tradable, reason = is_bar_tradable(b)
                    if not tradable:
                        gap_skipped_bars.append({
                            "timestamp": b.timestamp_utc,
                            "symbol": b.symbol,
                            "reason": reason,
                        })
                        continue

                filtered.append(b)
            bars = filtered

        features_by_date = {}
        if features_frame is not None and not features_frame.empty:
            from quant_us.backtest.data_bridge import feature_map_from_frame
            features_by_date = feature_map_from_frame(features_frame)

        engine_config = BacktestConfig(
            initial_cash=self.config.initial_cash,
            commission_rate=self.config.commission_rate,
            slippage_bps=self.config.slippage_bps,
            run_id=self.config.run_id,
        )
        engine = EventDrivenBacktestEngine(
            strategies=strategies,
            config=engine_config,
            calendar=self.calendar,
            features_by_date=features_by_date,
            gap_config=self.config.gap_config,
            session_config=self.config.session_config,
        )

        event_result = engine.run(bars)

        # --- Replay save / determinism verification ---
        determinism_verified = False
        determinism_details: dict | None = None
        if self.config.save_replay_path is not None or self.config.verify_determinism:
            from quant_us.backtest.replay import BacktestReplay

            replay = BacktestReplay.from_result(event_result, bars, engine_config)

            if self.config.save_replay_path is not None:
                replay.save(self.config.save_replay_path)

            if self.config.verify_determinism:
                det_result = replay.verify_determinism(strategies, bars, engine_config)
                determinism_verified = det_result.get("deterministic", False)
                determinism_details = det_result

        # --- End replay / determinism ---

        bar_ref_prices: dict[datetime, dict[str, float]] = {}
        for b in bars:
            ref = b.vwap if b.vwap is not None and b.vwap > 0 else b.close
            bar_ref_prices.setdefault(b.timestamp_utc, {})[b.symbol] = ref

        # Build market_prices keyed by ALL bar timestamps for consistency verification.
        # This ensures each snapshot timestamp has matching market prices for ledger equity
        # recomputation — avoiding timestamp-mismatch false positives.
        running_ref: dict[str, float] = {}
        all_bar_prices: dict[datetime, dict[str, float]] = {}
        bar_timestamps = sorted({b.timestamp_utc for b in bars})
        for ts in bar_timestamps:
            refs = bar_ref_prices.get(ts, {})
            running_ref.update(refs)
            all_bar_prices[ts] = dict(running_ref)

        # Fill-level market prices for derive_equity_from_fills
        fill_market_prices: dict[datetime, dict[str, float]] = {}
        sorted_fills = sorted(event_result.fills, key=lambda f: f.filled_at)
        for fill in sorted_fills:
            if fill.filled_at in all_bar_prices:
                fill_market_prices[fill.filled_at] = all_bar_prices[fill.filled_at]
            elif fill.symbol not in running_ref:
                running_ref[fill.symbol] = fill.price
                fill_market_prices[fill.filled_at] = dict(running_ref)

        ledger_curve = derive_equity_from_fills(
            fills=event_result.fills,
            initial_cash=self.config.initial_cash,
            market_prices_by_time=fill_market_prices,
            adjustments=self.config.adjustment_log,
        )
        is_consistent, msg = verify_equity_consistency(
            event_result.snapshots,
            ledger_curve,
            fills=event_result.fills,
            market_prices_by_time=all_bar_prices,
        )

        # --- Generate per-run manifest ---
        commit_hash = ""
        try:
            commit_hash = _subprocess.check_output(
                ["git", "rev-parse", "--short", "HEAD"], text=True
            ).strip()
        except Exception:
            pass

        start_time = start_dt.isoformat()
        end_time = datetime.now(timezone.utc).isoformat()
        run_manifest = {
            "run_id": self.config.run_id,
            "data_version": data_version,
            "strategy_version": strategy_version,
            "commit_hash": commit_hash,
            "start_time": start_time,
            "end_time": end_time,
            "config": {
                "initial_cash": self.config.initial_cash,
                "commission_rate": self.config.commission_rate,
                "slippage_bps": self.config.slippage_bps,
                "max_daily_turnover_pct": self.config.max_daily_turnover_pct,
                "gap_config": str(self.config.gap_config) if self.config.gap_config else None,
            },
        }
        manifest_id = self.config.run_id
        # Write run manifest alongside data manifests
        manifest_path = self.manifest_store.root / f"run_{manifest_id}.json"
        try:
            import json as _json
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            manifest_path.write_text(_json.dumps(run_manifest, indent=2, default=str), encoding="utf-8")
        except Exception:
            pass

        # Compute turnover from fills and equity curve
        turnover_report = compute_turnover(
            fills=event_result.fills,
            equity_curve=ledger_curve.equity_series,
            max_daily_turnover_pct=self.config.max_daily_turnover_pct,
        )

        return UnifiedBacktestResult(
            run_id=self.config.run_id,
            event_driven=event_result,
            ledger_curve=ledger_curve,
            equity_consistent=is_consistent,
            equity_consistency_msg=msg,
            data_version=data_version,
            strategy_version=strategy_version,
            manifest_id=manifest_id,
            turnover_report=turnover_report,
            gap_skipped_bars=gap_skipped_bars,
            determinism_verified=determinism_verified,
            determinism_details=determinism_details,
        )


def compare_vectorized_vs_event_driven(
    vectorized_summary: dict[str, float | int],
    unified_result: UnifiedBacktestResult,
) -> dict[str, Any]:
    """Compare vectorized (approximate) vs event-driven (canonical) results.

    Returns differences in key metrics. Large discrepancies indicate the
    vectorized path is making unrealistic assumptions.
    """
    ed = unified_result.summary
    diffs: dict[str, Any] = {}
    for key in ["total_return_pct", "sharpe_ratio", "max_drawdown_pct", "profit_factor", "trade_count"]:
        v_val = float(vectorized_summary.get(key, 0))
        e_val = float(ed.get(key, 0))
        diff = round(v_val - e_val, 4)
        diffs[key] = {
            "vectorized": v_val,
            "event_driven": e_val,
            "delta": diff,
        }
    diffs["equity_consistent"] = unified_result.equity_consistent
    diffs["equity_consistency_msg"] = unified_result.equity_consistency_msg
    diffs["is_trustworthy"] = unified_result.is_trustworthy
    return diffs
