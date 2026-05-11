"""Unified backtest runner — event-driven engine as canonical path.

This module enforces that all promotion-gate-level backtests go through the
full order lifecycle: Signal → TargetPosition → OrderIntent → Risk Check →
Broker Order → Fill → Ledger → PnL.

The vectorized _simulate() path is explicitly marked as APPROXIMATE and should
only be used for fast research scanning, not for promotion decisions.
"""

from __future__ import annotations

import random as _random
import json
import subprocess as _subprocess
from dataclasses import asdict, dataclass, field, fields, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable

import numpy as np
import pandas as pd

from quant_us.backtest.corporate_actions_ledger import LedgerAdjustmentLog
from quant_us.backtest.data_bridge import EventDrivenBacktestRunner, bars_from_dataframe
from quant_us.backtest.engine import BacktestBroker, BacktestConfig, BacktestResult, EventDrivenBacktestEngine
from quant_us.backtest.gap_session import GapConfig, SessionConfig, classify_session, is_bar_tradable
from quant_us.backtest.ledger_pnl import (
    LedgerEquityCurve,
    LedgerReconciliationArtifact,
    LedgerReconciliationReport,
    build_ledger_reconciliation_artifact_from_records,
    build_reconciliation_report,
    derive_equity_from_fills,
    ledger_state_at_time,
)
from quant_us.backtest.broker_simulator import SimulatedBroker
from quant_us.backtest.commission import PercentCommission
from quant_us.backtest.slippage import BpsSlippage
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
    evidence: dict[str, Any] = field(default_factory=dict)
    manifest_path: str = ""

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
        broker_factory: Callable[[UnifiedBacktestConfig], BacktestBroker] | None = None,
    ) -> None:
        self.config = config or UnifiedBacktestConfig()
        self.calendar = calendar or USEquityCalendar.with_holidays()
        self.manifest_store = DataManifestStore()
        self.broker_factory = broker_factory

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
        broker = self._build_broker()
        engine = EventDrivenBacktestEngine(
            strategies=strategies,
            config=engine_config,
            calendar=self.calendar,
            features_by_date=features_by_date,
            gap_config=self.config.gap_config,
            session_config=self.config.session_config,
            broker=broker,
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

        ledger_curve = derive_equity_from_fills(
            fills=event_result.fills,
            initial_cash=self.config.initial_cash,
            market_prices_by_time=all_bar_prices,
            adjustments=self.config.adjustment_log,
        )
        reconciliation_report = build_reconciliation_report(
            event_result.snapshots,
            ledger_curve,
            fills=event_result.fills,
            market_prices_by_time=all_bar_prices,
            adjustments=self.config.adjustment_log,
        )
        ledger_artifact = build_ledger_reconciliation_artifact_from_records(
            order_records=event_result.orders,
            fills=event_result.fills,
            initial_cash=self.config.initial_cash,
            market_prices_by_time=all_bar_prices,
            snapshots=event_result.snapshots,
            adjustments=self.config.adjustment_log,
        )
        is_consistent, msg = reconciliation_report.passed, reconciliation_report.message

        commit_hash = _git_commit_hash()
        evidence = _build_promotion_evidence(
            run_id=self.config.run_id,
            event_result=event_result,
            ledger_curve=ledger_curve,
            reconciliation_report=reconciliation_report,
            equity_consistent=is_consistent,
            equity_consistency_msg=msg,
            initial_cash=self.config.initial_cash,
            all_bar_prices=all_bar_prices,
            strategies=strategies,
            data_version=data_version,
            strategy_version=strategy_version,
            config=self.config,
            ledger_artifact=ledger_artifact,
            commit_hash=commit_hash,
            manifest_store=self.manifest_store,
        )
        ledger_artifact_path = _write_ledger_reconciliation_artifact(
            self.manifest_store.root,
            ledger_artifact,
        )
        evidence["ledger_artifact_path"] = str(ledger_artifact_path)
        evidence["completeness"]["ledger_artifact_file_written"] = True

        start_time = start_dt.isoformat()
        end_time = datetime.now(timezone.utc).isoformat()
        run_manifest: dict[str, Any] = {
            "manifest_schema_version": "backtest_run_v2",
            "engine": "event_driven",
            "canonical_for_promotion": True,
            "execution_semantics": event_result.metadata.get(
                "execution_semantics",
                engine_config.execution_semantics,
            ),
            "run_id": self.config.run_id,
            "generated_at": evidence["generated_at"],
            "data_version": data_version,
            "strategy_version": evidence["strategy"]["strategy_version"],
            "strategy_params": evidence["strategy"]["strategies"],
            "commit_hash": commit_hash,
            "start_time": start_time,
            "end_time": end_time,
            "ledger_artifact_hash": evidence["ledger_artifact_hash"],
            "ledger_artifact_path": evidence["ledger_artifact_path"],
            "ledger_hash": evidence["ledger_hash"],
            "fills_hash": evidence["fills_hash"],
            "config": {
                "initial_cash": self.config.initial_cash,
                "commission_rate": self.config.commission_rate,
                "slippage_bps": self.config.slippage_bps,
                "max_daily_turnover_pct": self.config.max_daily_turnover_pct,
                "gap_config": str(self.config.gap_config) if self.config.gap_config else None,
            },
            "cost_model": evidence["costs"],
            "commission_model": evidence["commission"],
            "slippage_model": evidence["slippage"],
            "data_manifest_exists": evidence["data_manifest_exists"],
            "missing_data_manifest": evidence["missing_data_manifest"],
            "data_manifest": evidence["data_manifest"],
            "reconciliation": evidence["reconciliation"]["summary"],
            "ledger_artifact": evidence["ledger_artifact"],
            "corporate_actions": evidence["corporate_actions"]["digest"],
            "evidence": evidence,
        }
        manifest_id = self.config.run_id
        manifest_path = _write_run_manifest(self.manifest_store.root, manifest_id, run_manifest)

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
            evidence=evidence,
            manifest_path=str(manifest_path),
        )

    def _build_broker(self) -> BacktestBroker:
        if self.broker_factory is not None:
            return self.broker_factory(self.config)
        return SimulatedBroker(
            initial_cash=self.config.initial_cash,
            commission_model=PercentCommission(rate=self.config.commission_rate),
            slippage_model=BpsSlippage(bps=self.config.slippage_bps),
            fill_ratio=self.config.fill_ratio,
            volume_participation_cap_pct=self.config.volume_participation_cap_pct,
            adjustment_log=self.config.adjustment_log,
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


def _git_commit_hash() -> str:
    proc = _subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        stderr = proc.stderr.strip() or proc.stdout.strip() or "unknown git error"
        raise RuntimeError(f"Unable to resolve git commit hash for backtest manifest: {stderr}")
    commit_hash = proc.stdout.strip()
    if not commit_hash:
        raise RuntimeError("Unable to resolve git commit hash for backtest manifest: empty output")
    return commit_hash


def _write_run_manifest(root, manifest_id: str, manifest: dict[str, Any]):
    path = root / f"run_{manifest_id}.json"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(manifest, indent=2, sort_keys=True, default=str), encoding="utf-8")
    except Exception as exc:
        raise RuntimeError(f"Unable to write backtest run manifest at {path}: {exc}") from exc
    return path


def _write_ledger_reconciliation_artifact(
    root,
    artifact: LedgerReconciliationArtifact,
):
    payload = artifact.to_dict()
    artifact_hash = str(payload.get("artifact_hash", ""))
    path = root / "reconciliation" / f"ledger_recon_artifact_{artifact_hash[:16]}.json"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
            encoding="utf-8",
        )
    except Exception as exc:
        raise RuntimeError(
            f"Unable to write ledger reconciliation artifact at {path}: {exc}"
        ) from exc
    return path


def _jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value) and not isinstance(value, type):
        return {k: _jsonable(v) for k, v in asdict(value).items()}
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items() if not str(k).startswith("_")}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _resolve_data_manifest_binding(store: DataManifestStore, data_version: str) -> dict[str, Any]:
    manifest_path = str(store.root / f"{data_version}.json") if data_version else ""
    manifest = store.read(data_version) if data_version else None
    if manifest is None:
        return {
            "exists": False,
            "missing_data_manifest": True,
            "requested_data_version": data_version,
            "data_version": "",
            "data_version_matches_requested": False,
            "data_manifest_id": "",
            "path": manifest_path,
            "checksum": "",
            "fingerprint": "",
            "source": "",
            "asset_class": "",
            "symbol": "",
            "interval": "",
            "coverage": {},
            "quality": {},
        }

    return {
        "exists": True,
        "missing_data_manifest": False,
        "requested_data_version": data_version,
        "data_version": manifest.data_version,
        "data_version_matches_requested": manifest.data_version == data_version,
        "data_manifest_id": manifest.manifest_id,
        "path": manifest_path,
        "checksum": manifest.effective_checksum,
        "fingerprint": manifest.fingerprint,
        "source": manifest.source,
        "asset_class": manifest.asset_class,
        "symbol": manifest.symbol,
        "interval": manifest.interval,
        "coverage": {
            "start": manifest.start,
            "end": manifest.end,
            "row_count": manifest.row_count,
            "expected_rows": manifest.expected_rows,
            "coverage_pct": manifest.coverage_pct,
            "timezone": manifest.timezone,
            "adjustment": manifest.adjustment,
        },
        "quality": {
            "quality_score": manifest.quality_score,
            "issue_count": len(manifest.issues),
            "is_usable": manifest.is_usable,
        },
    }


def _strategy_params(strategy: Strategy) -> dict[str, Any]:
    if is_dataclass(strategy):
        params: dict[str, Any] = {}
        for item in fields(strategy):
            if item.name.startswith("_") or not item.init:
                continue
            params[item.name] = _jsonable(getattr(strategy, item.name))
        return params
    params = {}
    for key, value in vars(strategy).items():
        if not key.startswith("_"):
            params[key] = _jsonable(value)
    return params


def _strategy_evidence(strategies: list[Strategy], strategy_version: str) -> dict[str, Any]:
    strategy_rows = [
        {
            "strategy_id": getattr(strategy, "strategy_id", strategy.__class__.__name__),
            "version": getattr(strategy, "version", ""),
            "params": _strategy_params(strategy),
        }
        for strategy in strategies
    ]
    effective_version = strategy_version or ",".join(
        f"{row['strategy_id']}@{row['version'] or 'unknown'}" for row in strategy_rows
    )
    return {
        "strategy_version": effective_version,
        "strategies": strategy_rows,
    }


def _event_counts(event_result: BacktestResult) -> dict[str, int]:
    counts = {
        "market": 0,
        "signal": 0,
        "target_position": 0,
        "order_intent": 0,
        "risk": 0,
        "broker_order": 0,
        "fill": 0,
        "account_update": 0,
        "total": len(event_result.events),
    }
    for event in event_result.events:
        key = getattr(getattr(event, "event_type", ""), "value", str(getattr(event, "event_type", ""))).lower()
        if key in counts:
            counts[key] += 1
    return counts


def _order_status_counts(event_result: BacktestResult) -> dict[str, int]:
    counts: dict[str, int] = {}
    for order in event_result.orders:
        status = getattr(order.status, "value", str(order.status))
        counts[status] = counts.get(status, 0) + 1
    return counts


def _risk_counts(event_result: BacktestResult) -> dict[str, Any]:
    approved = sum(1 for result in event_result.oms_results if result.risk_decision.approved)
    rejected = len(event_result.oms_results) - approved
    rejection_reasons: dict[str, int] = {}
    for result in event_result.oms_results:
        if result.risk_decision.approved:
            continue
        reason = result.risk_decision.reason
        rejection_reasons[reason] = rejection_reasons.get(reason, 0) + 1
    return {
        "risk_check_count": len(event_result.oms_results),
        "approved": approved,
        "rejected": rejected,
        "rejection_reasons": rejection_reasons,
    }


def _ledger_state_at_final_snapshot(
    event_result: BacktestResult,
    initial_cash: float,
    all_bar_prices: dict[datetime, dict[str, float]],
    adjustments: LedgerAdjustmentLog | None = None,
) -> dict[str, Any]:
    if not event_result.snapshots:
        return {
            "final_timestamp_utc": "",
            "ledger_cash": initial_cash,
            "ledger_positions": {},
            "ledger_position_value": 0.0,
            "ledger_equity": initial_cash,
            "snapshot_cash": None,
            "snapshot_equity": None,
            "cash_consistent": True,
            "equity_consistent_at_final_snapshot": True,
        }

    final_snapshot = event_result.snapshots[-1]
    final_ts = final_snapshot.timestamp_utc.astimezone(timezone.utc)
    positions, cash, position_value, ledger_equity = ledger_state_at_time(
        event_result.fills,
        final_ts,
        initial_cash,
        market_prices=all_bar_prices.get(final_ts, {}),
        adjustments=adjustments,
    )
    return {
        "final_timestamp_utc": final_ts.isoformat(),
        "ledger_cash": round(cash, 6),
        "ledger_positions": {symbol: round(qty, 8) for symbol, qty in sorted(positions.items())},
        "ledger_position_value": round(position_value, 6),
        "ledger_equity": round(ledger_equity, 6),
        "snapshot_cash": round(final_snapshot.cash, 6),
        "snapshot_equity": round(final_snapshot.equity, 6),
        "cash_consistent": abs(final_snapshot.cash - cash) <= 1e-6,
        "equity_consistent_at_final_snapshot": abs(final_snapshot.equity - ledger_equity) <= 1e-6,
    }


def _adjustment_audit_entry(adjustment) -> dict[str, Any]:
    return {
        "timestamp_utc": adjustment.timestamp_utc.astimezone(timezone.utc).isoformat(),
        "symbol": adjustment.normalized_symbol(),
        "adjustment_type": adjustment.adjustment_type,
        "amount": round(float(adjustment.amount), 6),
        "quantity_multiplier": round(float(adjustment.quantity_multiplier), 8),
        "avg_price_multiplier": round(float(adjustment.effective_avg_price_multiplier()), 8),
        "description": adjustment.description,
        "has_position_impact": adjustment.has_position_impact(),
    }


def _corporate_actions_evidence(adjustments: LedgerAdjustmentLog | None) -> dict[str, Any]:
    if adjustments is None:
        summary = {
            "total_dividends": 0.0,
            "total_borrow_fees": 0.0,
            "total_corporate_adjustments": 0.0,
            "adjustment_count": 0,
            "split_event_count": 0,
        }
        return {
            "summary": summary,
            "digest": dict(summary),
            "adjustments": [],
        }

    summary = adjustments.to_dict()
    return {
        "summary": summary,
        "digest": dict(summary),
        "adjustments": [_adjustment_audit_entry(adjustment) for adjustment in adjustments.adjustments],
    }


def _build_promotion_evidence(
    *,
    run_id: str,
    event_result: BacktestResult,
    ledger_curve: LedgerEquityCurve,
    reconciliation_report: LedgerReconciliationReport,
    equity_consistent: bool,
    equity_consistency_msg: str,
    initial_cash: float,
    all_bar_prices: dict[datetime, dict[str, float]],
    strategies: list[Strategy],
    data_version: str,
    strategy_version: str,
    config: UnifiedBacktestConfig,
    ledger_artifact: LedgerReconciliationArtifact,
    commit_hash: str,
    manifest_store: DataManifestStore,
) -> dict[str, Any]:
    final_ledger_state = _ledger_state_at_final_snapshot(
        event_result,
        initial_cash,
        all_bar_prices,
        adjustments=config.adjustment_log,
    )
    strategy_info = _strategy_evidence(strategies, strategy_version)
    data_manifest = _resolve_data_manifest_binding(manifest_store, data_version)
    corporate_actions = _corporate_actions_evidence(config.adjustment_log)
    risk = _risk_counts(event_result)
    order_count = len(event_result.orders)
    oms_order_count = sum(1 for result in event_result.oms_results if result.order is not None)
    order_ids = {order.order_id for order in event_result.orders}
    filled_order_ids = {fill.order_id for fill in event_result.fills}
    all_orders_have_risk = all(bool(order.risk_check_id) for order in event_result.orders)
    all_fills_have_orders = all(fill.order_id in order_ids for fill in event_result.fills)
    total_commission = round(sum(float(fill.commission) for fill in event_result.fills), 6)
    ledger_final_equity = float(final_ledger_state["ledger_equity"])
    final_pnl = round(ledger_final_equity - initial_cash, 6)
    ledger_artifact_data = ledger_artifact.to_dict()
    ledger_artifact_generated_at = str(ledger_artifact_data.get("generated_at") or "")
    ledger_artifact_hash = str(ledger_artifact_data.get("artifact_hash") or "")
    ledger_hash = str(ledger_artifact.hashes.get("ledger_hash", ""))
    fills_hash = str(ledger_artifact.hashes.get("fills_hash", ""))
    orders_hash = str(ledger_artifact.hashes.get("orders_hash", ""))
    snapshots_hash = str(ledger_artifact.hashes.get("portfolio_snapshots_hash", ""))
    effective_fills_hash = str(ledger_artifact.hashes.get("effective_fills_hash", ""))
    artifact_reconciliation = ledger_artifact.reconciliation
    artifact_summary = artifact_reconciliation.get("summary", {}) if isinstance(artifact_reconciliation, dict) else {}
    artifact_integrity = ledger_artifact.integrity if isinstance(ledger_artifact.integrity, dict) else {}
    artifact_fills = ledger_artifact.fills if isinstance(ledger_artifact.fills, dict) else {}
    artifact_orders = ledger_artifact.orders if isinstance(ledger_artifact.orders, dict) else {}
    artifact_pnl = ledger_artifact.pnl if isinstance(ledger_artifact.pnl, dict) else {}
    ledger_artifact_consistent = (
        bool(ledger_artifact_hash)
        and bool(ledger_artifact_generated_at)
        and bool(ledger_hash)
        and bool(fills_hash)
        and bool(orders_hash)
        and bool(snapshots_hash)
        and artifact_summary == reconciliation_report.to_dict().get("summary", {})
        and int(artifact_fills.get("effective_fill_count", -1)) == len(event_result.fills)
        and int(artifact_orders.get("total_orders", -1)) == order_count
        and str(artifact_pnl.get("source", "")) == "ledger_fills"
        and bool(artifact_integrity.get("passed", False))
    )

    required_fields = {
        "engine": "event_driven",
        "data_version": data_version,
        "strategy_version": strategy_info["strategy_version"],
        "commit_hash": commit_hash,
    }
    missing_required = [key for key, value in required_fields.items() if not value]
    fixture_like_data_version = "fixture" in data_version.lower()
    data_manifest_bound = data_manifest["exists"] and data_manifest["data_version_matches_requested"]
    ledger_evidence_complete = (
        not missing_required
        and reconciliation_report.passed
        and bool(commit_hash)
        and all_orders_have_risk
        and all_fills_have_orders
        and ledger_artifact_consistent
    )

    return {
        "run_id": run_id,
        "engine": "event_driven",
        "canonical_for_promotion": True,
        "approximate_scan_engine": False,
        "execution_semantics": event_result.metadata.get(
            "execution_semantics",
            "signal_at_bar_close_order_next_bar",
        ),
        "generated_at": ledger_artifact_generated_at,
        "as_of_utc": ledger_artifact_data.get("as_of_utc"),
        "data_version": data_version,
        "data_manifest_exists": data_manifest["exists"],
        "missing_data_manifest": data_manifest["missing_data_manifest"],
        "data_manifest": data_manifest,
        "data_scope": {
            "fixture_like_data_version": fixture_like_data_version,
            "promotion_scope_ok": not fixture_like_data_version,
            "scope_rejections": ["fixture_data_version"] if fixture_like_data_version else [],
        },
        "strategy": strategy_info,
        "commit_hash": commit_hash,
        "ledger_artifact_hash": ledger_artifact_hash,
        "ledger_hash": ledger_hash,
        "fills_hash": fills_hash,
        "orders_hash": orders_hash,
        "portfolio_snapshots_hash": snapshots_hash,
        "ledger_artifact": ledger_artifact_data,
        "costs": {
            "commission_rate": config.commission_rate,
            "slippage_bps": config.slippage_bps,
            "fill_ratio": config.fill_ratio,
            "volume_participation_cap_pct": config.volume_participation_cap_pct,
            "realized_commission": total_commission,
            "realized_slippage_cost": ledger_curve.points[-1].cumulative_slippage_cost if ledger_curve.points else 0.0,
            "total_fees": ledger_curve.total_fees,
        },
        "commission": {
            "model": "PercentCommission",
            "rate": config.commission_rate,
            "realized_total": total_commission,
        },
        "slippage": {
            "model": "BpsSlippage",
            "bps": config.slippage_bps,
            "realized_total": ledger_curve.points[-1].cumulative_slippage_cost if ledger_curve.points else 0.0,
        },
        "orders": {
            "count": order_count,
            "status_counts": _order_status_counts(event_result),
            "oms_order_count": oms_order_count,
            "all_orders_created_by_oms": order_count == oms_order_count,
            "all_orders_have_risk_check_id": all_orders_have_risk,
            "orders_hash": orders_hash,
        },
        "fills": {
            "count": len(event_result.fills),
            "filled_order_count": len(filled_order_ids),
            "all_fills_match_orders": all_fills_have_orders,
            "fills_hash": fills_hash,
            "effective_fills_hash": effective_fills_hash,
        },
        "risk": risk,
        "cash": {
            "initial_cash": initial_cash,
            "final_snapshot_cash": final_ledger_state["snapshot_cash"],
            "ledger_cash_at_final_snapshot": final_ledger_state["ledger_cash"],
            "cash_consistent": final_ledger_state["cash_consistent"],
        },
        "positions": {
            "final_positions": final_ledger_state["ledger_positions"],
            "final_position_value": final_ledger_state["ledger_position_value"],
            "position_count": len(final_ledger_state["ledger_positions"]),
        },
        "corporate_actions": corporate_actions,
        "fees": {
            "total_commission": total_commission,
            "ledger_total_fees": ledger_curve.total_fees,
            "fees_from_fills": True,
        },
        "pnl": {
            "source": "ledger_fills",
            "initial_cash": initial_cash,
            "final_equity": round(ledger_final_equity, 6),
            "final_pnl": final_pnl,
            "total_return_pct": round(final_pnl / initial_cash * 100.0, 6) if initial_cash else 0.0,
        },
        "equity": {
            "ledger_curve_points": len(ledger_curve.points),
            "ledger_final_equity": round(ledger_final_equity, 6),
            "snapshot_final_equity": final_ledger_state["snapshot_equity"],
            "consistent": equity_consistent,
            "consistent_at_final_snapshot": final_ledger_state["equity_consistent_at_final_snapshot"],
            "consistency_msg": equity_consistency_msg,
        },
        "reconciliation": reconciliation_report.to_dict(),
        "events": _event_counts(event_result),
        "completeness": {
            "missing_required_fields": missing_required,
            "ledger_evidence_complete": ledger_evidence_complete,
            "data_manifest_bound": data_manifest_bound,
            "ledger_artifact_present": bool(ledger_artifact_hash),
            "ledger_artifact_generated": bool(ledger_artifact_generated_at),
            "ledger_artifact_consistent": ledger_artifact_consistent,
            "promotion_evidence_complete": ledger_evidence_complete
            and not fixture_like_data_version
            and data_manifest_bound,
        },
    }
