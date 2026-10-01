"""Canonical event-driven research evidence for the frozen ETF26 candidate."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable, Mapping

import pandas as pd

from quant_us.core.calendar import USEquityCalendar
from quant_us.data.shared_hf_etf26 import ResolvedHfEtf26Dataset
from quant_us.strategies.us_etf_26_complete_return import (
    Forecast,
    FrozenEtf26CompleteReturnStrategy,
    FrozenStrategyDecision,
)


SCHEMA_VERSION = "us_etf_26_canonical_backtest_report_v1"
MANIFEST_SCHEMA_VERSION = "us_etf_26_canonical_run_manifest_v1"
ARTIFACT_FILES = (
    "event_log.jsonl",
    "orders.jsonl",
    "fills.jsonl",
    "position_ledger.jsonl",
    "cash_ledger.jsonl",
    "corporate_action_ledger.jsonl",
    "reconciliation.json",
    "exposure_timeline.jsonl",
    "cost_stress.json",
    "walk_forward.json",
    "report.json",
    "report.md",
)


@dataclass(frozen=True)
class CanonicalRunResult:
    run_id: str
    run_dir: Path
    latest_pointer: Path
    report: dict[str, Any]
    manifest: dict[str, Any]
    manifest_sha256: str


@dataclass(frozen=True)
class _SimulationResult:
    events: list[dict[str, Any]]
    orders: list[dict[str, Any]]
    fills: list[dict[str, Any]]
    positions: list[dict[str, Any]]
    cash: list[dict[str, Any]]
    exposure: list[dict[str, Any]]
    reconciliation: dict[str, Any]
    metrics: dict[str, Any]
    lifecycle: dict[str, Any]


def build_us_etf_26_canonical_run(
    *,
    repo_root: Path,
    config_path: Path,
    resolved_dataset: ResolvedHfEtf26Dataset,
    code_commit: str,
    code_tree_hash: str,
    generated_at: str,
    artifact_root_override: Path | None = None,
) -> CanonicalRunResult:
    root = repo_root.resolve()
    config_abs = (root / config_path).resolve() if not config_path.is_absolute() else config_path.resolve()
    config = _read_json(config_abs)
    candidate_path = (root / str(config["candidate_config"])).resolve()
    goal2_path = (root / str(config["goal2_intake_report"])).resolve()
    candidate = _read_json(candidate_path)
    goal2 = _read_json(goal2_path)
    _validate_inputs(config, candidate, goal2, resolved_dataset)

    daily, data_quality = _load_complete_daily_sessions(
        resolved_dataset.qqq_path,
        start=date.fromisoformat(config["research_window"]["start"]),
        end=date.fromisoformat(config["research_window"]["end"]),
    )
    strategy = FrozenEtf26CompleteReturnStrategy(
        candidate_id=candidate["candidate_id"],
        strategy_version=candidate["strategy_version"],
        symbol=candidate["selection"]["symbol"],
        exposure_multiplier=candidate["selection"]["exposure_multiplier"],
        params=candidate["parameters"],
    )
    decisions = strategy.generate(daily)
    params_hash = _stable_hash(candidate["parameters"])
    candidate_config_hash = _sha256_file(candidate_path)
    strategy_source_hash = _sha256_file(root / "quant_us/strategies/us_etf_26_complete_return.py")
    goal2_hash = _sha256_file(goal2_path)
    canonical_cost_hash = _stable_hash(config["cost_model"])
    run_inputs = {
        "candidate_id": candidate["candidate_id"],
        "strategy_version": candidate["strategy_version"],
        "candidate_config_sha256": candidate_config_hash,
        "params_hash": params_hash,
        "canonical_cost_model_hash": canonical_cost_hash,
        "data_version": config["dataset_version"],
        "data_aggregate_sha256": config["aggregate_sha256"],
        "qqq_sha256": resolved_dataset.qqq_sha256,
        "code_commit": code_commit,
        "code_tree_hash": code_tree_hash,
        "research_window": dict(config["research_window"]),
    }
    run_id = f"us-etf26-canonical-{_stable_hash(run_inputs)[:16]}"
    run_hash = _stable_hash(run_inputs)
    base_cost = _cost_components(config["cost_model"], float(config["cost_model"]["base_total_bps"]))
    base = _simulate(
        daily=daily,
        decisions=decisions,
        run_id=run_id,
        strategy_id=strategy.strategy_id,
        data_version=config["dataset_version"],
        initial_cash=float(config["initial_cash"]),
        risk=config["risk"],
        execution=config["execution"],
        costs=base_cost,
    )
    replay = _simulate(
        daily=daily,
        decisions=decisions,
        run_id=run_id,
        strategy_id=strategy.strategy_id,
        data_version=config["dataset_version"],
        initial_cash=float(config["initial_cash"]),
        risk=config["risk"],
        execution=config["execution"],
        costs=base_cost,
    )
    replay_hashes = {
        "event_log": _stable_hash(base.events),
        "orders": _stable_hash(base.orders),
        "fills": _stable_hash(base.fills),
        "position_ledger": _stable_hash(base.positions),
        "cash_ledger": _stable_hash(base.cash),
        "exposure_timeline": _stable_hash(base.exposure),
    }
    deterministic_replay_hash_match = replay_hashes == {
        "event_log": _stable_hash(replay.events),
        "orders": _stable_hash(replay.orders),
        "fills": _stable_hash(replay.fills),
        "position_ledger": _stable_hash(replay.positions),
        "cash_ledger": _stable_hash(replay.cash),
        "exposure_timeline": _stable_hash(replay.exposure),
    }
    no_lookahead = _no_lookahead_check(strategy, daily, decisions, base.fills)
    cost_stress = _cost_stress(
        config=config,
        daily=daily,
        decisions=decisions,
        run_id=run_id,
        strategy_id=strategy.strategy_id,
    )
    walk_forward = _walk_forward(base.exposure, config["validation"])
    confirmation = _confirmation_status(candidate, daily)
    blockers = _blockers(
        data_quality=data_quality,
        goal2=goal2,
        confirmation=confirmation,
        no_lookahead=no_lookahead,
        reconciliation=base.reconciliation,
        deterministic_replay_hash_match=deterministic_replay_hash_match,
        cost_stress=cost_stress,
    )

    corporate_actions = [
        {
            "run_id": run_id,
            "strategy_id": strategy.strategy_id,
            "data_version": config["dataset_version"],
            "event_type": "coverage_status",
            "adjustment_type": "none_recorded",
            "amount": 0.0,
            "event_time": None,
            "available_time": None,
            "error_code": "corporate_action_available_time_replay_missing",
            "status": "blocked_external_data",
        }
    ]
    report = {
        "schema_version": SCHEMA_VERSION,
        "status": "complete_research_only_blocked",
        "decision": "canonical_research_evidence_complete_promotion_credit_disallowed_confirmation_incomplete",
        "generated_at": generated_at,
        "code_commit": code_commit,
        "code_tree_hash": code_tree_hash,
        "run_id": run_id,
        "candidate": {
            "candidate_id": candidate["candidate_id"],
            "strategy_id": strategy.strategy_id,
            "strategy_version": candidate["strategy_version"],
            "candidate_status": candidate["status"],
            "candidate_config": _relpath(candidate_path, root),
            "candidate_config_sha256": candidate_config_hash,
            "params": candidate["parameters"],
            "params_hash": params_hash,
            "symbol": candidate["selection"]["symbol"],
            "timeframe": candidate["selection"]["timeframe"],
            "target_exposure_multiplier": candidate["selection"]["exposure_multiplier"],
            "universe": candidate["universe"],
            "research_window": candidate["research_window"],
            "candidate_count": len(candidate["universe"]) * len(candidate["timeframes"]),
            "trial_count": len(candidate["universe"]) * len(candidate["timeframes"]),
            "selected_by": "Goal 1 exploratory 26 ETF x 7 timeframe screen; no selection in Goal 3",
            "parameter_tuning_performed": False,
            "symbol_or_timeframe_reselection_performed": False,
        },
        "data": {
            "dataset_id": config["dataset_id"],
            "data_version": config["dataset_version"],
            "readiness_class": resolved_dataset.manifest["readiness_class"],
            "manifest_git_spec": resolved_dataset.manifest_git_spec,
            "manifest_sha256": resolved_dataset.manifest_sha256,
            "aggregate_sha256": resolved_dataset.manifest["aggregate_sha256"],
            "qqq_relative_path": config["symbol_file"],
            "qqq_sha256": resolved_dataset.qqq_sha256,
            "consumer_read_only": True,
            "quality": data_quality,
        },
        "event_chain": {
            "sequence": [
                "MarketData",
                "Signal",
                "Forecast",
                "TargetPosition",
                "RiskDecision",
                "OrderIntent",
                "SimulatedFill",
                "PositionCashLedger",
                "Report",
            ],
            "strategy_has_io_dependency": False,
            "strategy_has_broker_dependency": False,
            "strategy_has_database_dependency": False,
            "event_count": len(base.events),
            "order_count": len(base.orders),
            "fill_count": len(base.fills),
            "position_ledger_count": len(base.positions),
            "cash_ledger_count": len(base.cash),
            "audit_required_fields_present": _audit_fields_present(base.events),
            "deterministic_replay_hash_match": deterministic_replay_hash_match,
            "hashes": replay_hashes,
        },
        "execution": {
            "decision_time_rule": "completed XNYS session close in UTC",
            "execution_time_rule": "next complete eligible XNYS session open in UTC",
            "same_bar_fill_count": no_lookahead["same_bar_fill_count"],
            "calendar": data_quality["calendar"],
            "session_policy": {
                "regular_session": "09:30 to 16:00 America/New_York",
                "early_close": "09:30 to 13:00 America/New_York",
                "gap": "fill at observed next-session open; gap recorded against prior close",
                "missing_scheduled_open": "use first observed RTH bar as research proxy and emit exact blocker",
                "suspension_or_zero_volume": "reject with no simulated fill",
                "partial_fill": "cap at configured daily volume participation",
                "reject": "invalid/missing open or zero volume fails closed",
                "cancel": "unfilled remainder cancelled at session close",
            },
            "lifecycle": base.lifecycle,
            "scenario_contract": {
                "next_open_gap_supported": True,
                "early_close_supported": True,
                "zero_volume_or_missing_open_reject_supported": True,
                "volume_cap_partial_fill_supported": True,
                "unfilled_remainder_cancel_supported": True,
                "actual_reject_count": base.lifecycle["rejected"],
                "actual_partial_fill_count": base.lifecycle["partially_filled"],
                "actual_cancel_count": base.lifecycle["cancelled"],
                "actual_gap_execution_count": base.lifecycle["gap_execution_count"],
            },
        },
        "cost_model": {
            **config["cost_model"],
            "canonical_cost_model_hash": canonical_cost_hash,
            "base_components_bps": base_cost,
            "base_realized": base.metrics["costs"],
            "borrow_applicability": "not_applicable_long_only",
        },
        "performance": base.metrics,
        "research_contract": {
            "research_question": "Can the sole frozen QQQ 1D exploratory candidate be replayed through a canonical fill and ledger chain without changing parameters?",
            "economic_hypothesis": "Long-only breakout/trend exposure seeks persistent QQQ trends while exits and cooldown limit failed breakouts; evidence remains synthetic-margin research only.",
            "sample_role": "exploratory_selection_sample_not_clean_holdout",
            "parameter_stability": "frozen_single_parameter_set_no_neighborhood_retuning",
            "signal_quality_position_quality_execution_quality_separated": True,
        },
        "ledger_reconciliation": base.reconciliation,
        "no_lookahead": no_lookahead,
        "walk_forward": walk_forward,
        "cost_stress": cost_stress,
        "independent_confirmation": confirmation,
        "corporate_actions": {
            "ledger_event_count": 0,
            "coverage_record_count": 1,
            "status": "blocked_external_data",
            "adjustment_available_time_replay": False,
            "pnl_adjustment_total": 0.0,
        },
        "dependencies": {
            "goal2_status": goal2["status"],
            "goal2_code_commit": goal2["code_commit"],
            "goal2_report_sha256": goal2_hash,
            "goal2_blockers": goal2["blockers"],
        },
        "hashes": {
            "data_aggregate_sha256": resolved_dataset.manifest["aggregate_sha256"],
            "data_manifest_sha256": resolved_dataset.manifest_sha256,
            "qqq_file_sha256": resolved_dataset.qqq_sha256,
            "strategy_config_sha256": candidate_config_hash,
            "strategy_source_sha256": strategy_source_hash,
            "params_hash": params_hash,
            "cost_model_hash": canonical_cost_hash,
            "slippage_model_hash": _stable_hash({key: config["cost_model"][key] for key in ("spread_bps", "slippage_bps", "impact_bps", "spread_model", "impact_model")}),
            "run_inputs_hash": run_hash,
            "code_tree_hash": code_tree_hash,
        },
        "blockers": blockers,
        "guardrails": {
            "research_only": True,
            "promotion_credit_allowed": False,
            "promotion_unlock_allowed": False,
            "paper_or_live_unlock_allowed": False,
            "paper_order_allowed": False,
            "live_order_allowed": False,
            "paper_queue_write_allowed": False,
            "private_endpoint_used": False,
            "order_endpoint_used": False,
            "broker_endpoint_used": False,
            "network_used": False,
            "secret_read": False,
            "real_order_submitted": False,
            "source_data_modified": False,
        },
    }
    return _write_immutable_run(
        root=root,
        artifact_root=(artifact_root_override or (root / str(config["artifact_root"]))).resolve(),
        run_id=run_id,
        generated_at=generated_at,
        report=report,
        simulation=base,
        corporate_actions=corporate_actions,
        cost_stress=cost_stress,
        walk_forward=walk_forward,
        run_inputs=run_inputs,
    )


def _validate_inputs(
    config: Mapping[str, Any],
    candidate: Mapping[str, Any],
    goal2: Mapping[str, Any],
    dataset: ResolvedHfEtf26Dataset,
) -> None:
    if candidate.get("candidate_id") != "us-etf26-complete-return-qqq-1d-v1":
        raise ValueError("canonical_candidate_id_mismatch")
    if candidate.get("status") != "frozen_exploratory_research_only":
        raise ValueError("canonical_candidate_not_frozen_research_only")
    if candidate.get("selection", {}).get("symbol") != "QQQ" or candidate.get("selection", {}).get("timeframe") != "1D":
        raise ValueError("canonical_candidate_selection_mismatch")
    if goal2.get("status") != "blocked_external_data":
        raise ValueError("canonical_goal2_expected_blocked_external_data")
    if dataset.manifest.get("dataset_id") != config.get("dataset_id"):
        raise ValueError("canonical_dataset_id_mismatch")
    if dataset.manifest.get("dataset_version") != config.get("dataset_version"):
        raise ValueError("canonical_dataset_version_mismatch")
    cost = config["cost_model"]
    parts = sum(float(cost[key]) for key in ("commission_bps", "spread_bps", "slippage_bps", "impact_bps"))
    if abs(parts - float(cost["base_total_bps"])) > 1e-12:
        raise ValueError("canonical_cost_components_do_not_sum_to_base")
    frozen_cost = candidate["cost_model"]
    if float(frozen_cost["base_cost_bps_per_unit_turnover"]) != float(cost["base_total_bps"]):
        raise ValueError("canonical_base_cost_differs_from_frozen_candidate")
    if list(frozen_cost["stress_cost_bps_per_unit_turnover"]) != list(cost["stress_total_bps"]):
        raise ValueError("canonical_cost_stress_grid_differs_from_frozen_candidate")
    if float(frozen_cost["margin_interest_annual"]) != float(cost["margin_interest_annual"]):
        raise ValueError("canonical_margin_interest_differs_from_frozen_candidate")


def _load_complete_daily_sessions(
    path: Path,
    *,
    start: date,
    end: date,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    frame = pd.read_parquet(
        path,
        columns=["datetime", "Open", "High", "Low", "Close", "Volume", "source"],
        filters=[
            ("datetime", ">=", pd.Timestamp(start)),
            ("datetime", "<", pd.Timestamp(end + timedelta(days=1))),
        ],
    )
    timestamp = pd.to_datetime(frame["datetime"], errors="coerce")
    if timestamp.dt.tz is None:
        local = timestamp.dt.tz_localize("America/New_York", ambiguous="raise", nonexistent="raise")
    else:
        local = timestamp.dt.tz_convert("America/New_York")
    frame = frame.assign(local_time=local, session=local.dt.date)
    duplicate_count = int(frame["local_time"].duplicated().sum())
    null_count = int(frame[["datetime", "Open", "High", "Low", "Close", "Volume"]].isna().any(axis=1).sum())
    nonpositive_price_count = int((frame[["Open", "High", "Low", "Close"]] <= 0).any(axis=1).sum())
    invalid_ohlc_count = int(
        (
            (frame["High"] < frame[["Open", "Close", "Low"]].max(axis=1))
            | (frame["Low"] > frame[["Open", "Close", "High"]].min(axis=1))
        ).sum()
    )
    years = tuple(range(start.year, end.year + 1))
    calendar = USEquityCalendar.with_exchange_calendars(years=years)
    grouped = {session: group.sort_values("local_time") for session, group in frame.groupby("session", sort=True)}
    observed_rth_counts = []
    for session_frame in grouped.values():
        local_minutes = session_frame["local_time"].dt.hour * 60 + session_frame["local_time"].dt.minute
        observed_rth_counts.append(int(((local_minutes >= 570) & (local_minutes < 960)).sum()))
    research_usable_threshold = max(1, int(math.floor(float(pd.Series(observed_rth_counts).median()) * 0.5)))
    complete_rows: list[dict[str, Any]] = []
    missing_sessions: list[str] = []
    incomplete_sessions: list[dict[str, Any]] = []
    early_close_count = 0
    source_splice_sessions = 0
    exact_complete_session_count = 0
    missing_scheduled_open_bar_count = 0
    missing_scheduled_close_bar_count = 0
    source_counts = {str(key): int(value) for key, value in frame["source"].value_counts(dropna=False).items()}
    for session in calendar.trading_days_between(start, end):
        session_frame = grouped.get(session)
        close_local_time = calendar.early_close_time if calendar.is_early_close(session) else time(16, 0)
        if calendar.is_early_close(session):
            early_close_count += 1
        open_local = pd.Timestamp(datetime.combine(session, time(9, 30)), tz="America/New_York")
        close_local = pd.Timestamp(datetime.combine(session, close_local_time), tz="America/New_York")
        expected = pd.date_range(open_local, close_local - pd.Timedelta(minutes=1), freq="min")
        if session_frame is None:
            missing_sessions.append(session.isoformat())
            continue
        rth = session_frame.loc[
            (session_frame["local_time"] >= open_local)
            & (session_frame["local_time"] < close_local)
        ].copy()
        actual = pd.DatetimeIndex(rth["local_time"])
        if len(actual) and actual[0] != expected[0]:
            missing_scheduled_open_bar_count += 1
        if len(actual) and actual[-1] != expected[-1]:
            missing_scheduled_close_bar_count += 1
        exact_complete = len(actual) == len(expected) and actual.equals(expected)
        if exact_complete:
            exact_complete_session_count += 1
        else:
            incomplete_sessions.append(
                {
                    "session": session.isoformat(),
                    "expected_minutes": len(expected),
                    "actual_minutes": len(actual),
                }
            )
        if len(actual) < research_usable_threshold:
            continue
        if rth["source"].nunique(dropna=False) > 1:
            source_splice_sessions += 1
        complete_rows.append(
            {
                "session": session.isoformat(),
                "open_time_utc": actual[0].tz_convert("UTC"),
                "decision_time_utc": close_local.tz_convert("UTC"),
                "Open": float(rth["Open"].iloc[0]),
                "High": float(rth["High"].max()),
                "Low": float(rth["Low"].min()),
                "Close": float(rth["Close"].iloc[-1]),
                "Volume": float(rth["Volume"].sum()),
                "minute_count": len(rth),
                "expected_minute_count": len(expected),
                "exact_complete": exact_complete,
                "first_observed_minute": actual[0].isoformat(),
                "last_observed_minute": actual[-1].isoformat(),
                "early_close": calendar.is_early_close(session),
                "sources": sorted(str(value) for value in rth["source"].drop_duplicates().tolist()),
            }
        )
    daily = pd.DataFrame(complete_rows)
    if daily.empty:
        raise ValueError("canonical_complete_daily_sessions_missing")
    quality = {
        "status": "research_ready_with_blockers",
        "requested_start": start.isoformat(),
        "requested_end": end.isoformat(),
        "minute_row_count": int(len(frame)),
        "exact_complete_session_count": exact_complete_session_count,
        "research_usable_session_count": int(len(daily)),
        "research_usable_minute_threshold": research_usable_threshold,
        "missing_scheduled_open_bar_count": missing_scheduled_open_bar_count,
        "missing_scheduled_close_bar_count": missing_scheduled_close_bar_count,
        "missing_session_count": len(missing_sessions),
        "missing_session_sample": missing_sessions[:20],
        "incomplete_session_count": len(incomplete_sessions),
        "incomplete_session_sample": incomplete_sessions[:20],
        "duplicate_timestamp_count": duplicate_count,
        "null_required_row_count": null_count,
        "nonpositive_price_row_count": nonpositive_price_count,
        "invalid_ohlc_row_count": invalid_ohlc_count,
        "source_counts": source_counts,
        "source_splice_session_count": source_splice_sessions,
        "available_time_field_present": False,
        "adjustment_available_time_field_present": False,
        "halt_indicator_present": False,
        "calendar": {
            "name": calendar.calendar_name,
            "provider": calendar.calendar_provider,
            "provider_diagnostics": calendar.provider_diagnostics,
            "timezone": "America/New_York",
            "early_close_session_count": early_close_count,
            "exact_complete_session_rule": "exact expected XNYS minute grid",
            "research_usable_session_rule": "at least half the median observed RTH minute count, matching frozen Goal 1 research semantics",
        },
    }
    return daily, quality


def _simulate(
    *,
    daily: pd.DataFrame,
    decisions: list[FrozenStrategyDecision],
    run_id: str,
    strategy_id: str,
    data_version: str,
    initial_cash: float,
    risk: Mapping[str, Any],
    execution: Mapping[str, Any],
    costs: Mapping[str, float],
) -> _SimulationResult:
    events: list[dict[str, Any]] = []
    orders: list[dict[str, Any]] = []
    fills: list[dict[str, Any]] = []
    positions: list[dict[str, Any]] = []
    cash_ledger: list[dict[str, Any]] = [
        {
            "entry_id": _stable_id("cash", run_id, "initial"),
            "run_id": run_id,
            "timestamp_utc": pd.Timestamp(daily.iloc[0]["open_time_utc"]).isoformat(),
            "entry_type": "initial_cash",
            "amount": _round(initial_cash),
            "balance_after": _round(initial_cash),
            "order_id": None,
            "fill_id": None,
            "error_code": None,
        }
    ]
    exposure: list[dict[str, Any]] = []
    cash = float(initial_cash)
    quantity = 0.0
    average_price = 0.0
    pending: dict[str, Any] | None = None
    previous_close: float | None = None
    previous_session: date | None = None
    high_water = float(initial_cash)
    turnover_notional = 0.0
    costs_paid = {"commission": 0.0, "spread": 0.0, "slippage": 0.0, "impact": 0.0, "margin_interest": 0.0}
    status_counts: dict[str, int] = {}
    margin_call_count = 0
    sequence = 0

    for index, row in daily.iterrows():
        open_time = pd.Timestamp(row["open_time_utc"]).to_pydatetime()
        decision_time = pd.Timestamp(row["decision_time_utc"]).to_pydatetime()
        session = date.fromisoformat(str(row["session"]))
        open_price = float(row["Open"])
        close_price = float(row["Close"])
        volume = float(row["Volume"])
        sequence = _append_event(
            events,
            sequence=sequence,
            event_type="MarketDataOpen",
            timestamp=open_time,
            run_id=run_id,
            strategy_id=strategy_id,
            data_version=data_version,
            decision_time=pending["decision"].signal.timestamp_utc if pending else None,
            payload={"session": row["session"], "open": open_price, "volume": volume},
        )

        if pending is not None:
            pending_decision = pending["decision"]
            open_equity = cash + quantity * open_price
            target_weight = float(pending_decision.target.target_weight)
            risk_approved = bool(pending["risk_approved"]) and open_equity > 0.0
            risk_reason = str(
                pending["risk_reason"]
                if not bool(pending["risk_approved"]) or risk_approved
                else "rejected_nonpositive_open_equity"
            )
            risk_id = str(pending["risk_id"])
            intent_id = str(pending["intent_id"])
            desired_qty = target_weight * max(open_equity, 0.0) / open_price if risk_approved and open_price > 0 else quantity
            delta = round(desired_qty - quantity, int(execution["fractional_quantity_precision"]))
            if risk_approved and abs(delta) > 1e-8:
                side = "buy" if delta > 0 else "sell"
                requested_qty = abs(delta)
                order_id = _stable_id("order", intent_id, side, requested_qty)
                fillable = min(requested_qty, max(0.0, volume * float(risk["max_volume_participation_pct"]) / 100.0))
                if open_price <= 0 or volume <= 0 or fillable <= 0:
                    status = "rejected"
                    error_code = "market_open_or_volume_unavailable"
                    filled_qty = 0.0
                else:
                    filled_qty = round(fillable, int(execution["fractional_quantity_precision"]))
                    status = "filled" if filled_qty >= requested_qty - 1e-8 else "partially_filled"
                    error_code = None
                order = {
                    "run_id": run_id,
                    "strategy_id": strategy_id,
                    "data_version": data_version,
                    "order_id": order_id,
                    "order_intent_id": intent_id,
                    "risk_check_id": risk_id,
                    "signal_id": pending_decision.signal.signal_id,
                    "forecast_id": pending_decision.forecast.forecast_id,
                    "target_position_id": pending_decision.target.target_position_id,
                    "decision_time": pending_decision.signal.timestamp_utc.isoformat(),
                    "created_at": pending_decision.signal.timestamp_utc.isoformat(),
                    "submitted_at": open_time.isoformat(),
                    "symbol": "QQQ",
                    "side": side,
                    "order_type": execution["order_type"],
                    "time_in_force": execution["time_in_force"],
                    "target_weight": target_weight,
                    "requested_quantity": _round(requested_qty, 8),
                    "filled_quantity": _round(filled_qty, 8),
                    "remaining_quantity": _round(max(0.0, requested_qty - filled_qty), 8),
                    "status": status,
                    "error_code": error_code,
                }
                orders.append(order)
                status_counts[status] = status_counts.get(status, 0) + 1
                if filled_qty > 0:
                    fill_id = _stable_id("fill", order_id, open_time.isoformat(), filled_qty)
                    direction = 1.0 if side == "buy" else -1.0
                    spread_cost = filled_qty * open_price * float(costs["spread_bps"]) / 10_000.0
                    slippage_cost = filled_qty * open_price * float(costs["slippage_bps"]) / 10_000.0
                    impact_cost = filled_qty * open_price * float(costs["impact_bps"]) / 10_000.0
                    execution_bps = float(costs["spread_bps"] + costs["slippage_bps"] + costs["impact_bps"])
                    fill_price = open_price * (1.0 + direction * execution_bps / 10_000.0)
                    notional = filled_qty * fill_price
                    commission = filled_qty * open_price * float(costs["commission_bps"]) / 10_000.0
                    settlement = -notional if side == "buy" else notional
                    cash += settlement
                    cash_ledger.append(_cash_entry(run_id, open_time, "fill_settlement", settlement, cash, order_id, fill_id))
                    cash -= commission
                    cash_ledger.append(_cash_entry(run_id, open_time, "commission", -commission, cash, order_id, fill_id))
                    old_qty = quantity
                    if side == "buy":
                        new_qty = quantity + filled_qty
                        average_price = ((quantity * average_price) + (filled_qty * fill_price)) / new_qty if new_qty else 0.0
                        quantity = new_qty
                    else:
                        quantity -= filled_qty
                        if abs(quantity) <= 1e-8:
                            quantity = 0.0
                            average_price = 0.0
                    turnover_notional += filled_qty * open_price
                    costs_paid["commission"] += commission
                    costs_paid["spread"] += spread_cost
                    costs_paid["slippage"] += slippage_cost
                    costs_paid["impact"] += impact_cost
                    fill = {
                        "run_id": run_id,
                        "strategy_id": strategy_id,
                        "data_version": data_version,
                        "fill_id": fill_id,
                        "order_id": order_id,
                        "order_intent_id": intent_id,
                        "risk_check_id": risk_id,
                        "signal_id": pending_decision.signal.signal_id,
                        "forecast_id": pending_decision.forecast.forecast_id,
                        "target_position_id": pending_decision.target.target_position_id,
                        "decision_time": pending_decision.signal.timestamp_utc.isoformat(),
                        "filled_at": open_time.isoformat(),
                        "symbol": "QQQ",
                        "side": side,
                        "quantity": _round(filled_qty, 8),
                        "arrival_price": _round(open_price, 8),
                        "fill_price": _round(fill_price, 8),
                        "gap_return": _round(open_price / previous_close - 1.0) if previous_close else None,
                        "volume_participation_pct": _round(filled_qty / volume * 100.0) if volume > 0 else None,
                        "commission": _round(commission),
                        "spread_cost": _round(spread_cost),
                        "slippage_cost": _round(slippage_cost),
                        "impact_cost": _round(impact_cost),
                        "error_code": None,
                    }
                    fills.append(fill)
                    positions.append(_position_entry(run_id, open_time, "fill", old_qty, quantity, average_price, fill_id))
                    sequence = _append_event(
                        events,
                        sequence=sequence,
                        event_type="SimulatedFill",
                        timestamp=open_time,
                        run_id=run_id,
                        strategy_id=strategy_id,
                        data_version=data_version,
                        decision_time=pending_decision.signal.timestamp_utc,
                        signal=_signal_record(pending_decision),
                        forecast=_forecast_record(pending_decision.forecast),
                        target_position=_target_record(pending_decision),
                        risk_decision={"risk_check_id": risk_id, "approved": risk_approved, "reason": risk_reason},
                        order_id=order_id,
                        fill_id=fill_id,
                        payload=fill,
                    )
                if status == "partially_filled" and bool(execution["cancel_unfilled_at_session_close"]):
                    order["status"] = "cancelled_after_partial_fill"
                    status_counts["cancelled"] = status_counts.get("cancelled", 0) + 1
                    sequence = _append_event(
                        events,
                        sequence=sequence,
                        event_type="Cancel",
                        timestamp=decision_time,
                        run_id=run_id,
                        strategy_id=strategy_id,
                        data_version=data_version,
                        decision_time=pending_decision.signal.timestamp_utc,
                        order_id=order_id,
                        error_code="unfilled_remainder_cancelled_at_session_close",
                    )

        elapsed_days = max(1, (session - previous_session).days) if previous_session else 1
        if cash < 0:
            interest = abs(cash) * float(costs["margin_interest_annual"]) * elapsed_days / 365.0
            cash -= interest
            costs_paid["margin_interest"] += interest
            cash_ledger.append(_cash_entry(run_id, decision_time, "margin_interest", -interest, cash, None, None))
        close_equity = cash + quantity * close_price
        high_water = max(high_water, close_equity)
        gross = abs(quantity * close_price)
        leverage = gross / close_equity if close_equity > 0 else math.inf
        margin_ratio = close_equity / gross if gross > 0 else 1.0
        margin_call = gross > 0 and margin_ratio < float(risk["maintenance_margin_rate"])
        if margin_call:
            margin_call_count += 1
        positions.append(_position_entry(run_id, decision_time, "mark", quantity, quantity, average_price, None, close_price))
        exposure.append(
            {
                "run_id": run_id,
                "strategy_id": strategy_id,
                "data_version": data_version,
                "session": row["session"],
                "timestamp_utc": decision_time.isoformat(),
                "quantity": _round(quantity, 8),
                "market_price": _round(close_price, 8),
                "position_value": _round(quantity * close_price),
                "cash": _round(cash),
                "equity": _round(close_equity),
                "gross_exposure": _round(gross),
                "net_exposure": _round(quantity * close_price),
                "leverage": None if not math.isfinite(leverage) else _round(leverage),
                "drawdown": _round(close_equity / high_water - 1.0) if high_water > 0 else None,
                "margin_ratio": _round(margin_ratio),
                "margin_call": margin_call,
            }
        )

        decision = decisions[index]
        sequence = _append_event(events, sequence=sequence, event_type="MarketDataClose", timestamp=decision_time, run_id=run_id, strategy_id=strategy_id, data_version=data_version, decision_time=decision_time, payload={"session": row["session"], "close": close_price, "early_close": bool(row["early_close"])})
        sequence = _append_event(events, sequence=sequence, event_type="Signal", timestamp=decision_time, run_id=run_id, strategy_id=strategy_id, data_version=data_version, decision_time=decision_time, signal=_signal_record(decision))
        sequence = _append_event(events, sequence=sequence, event_type="Forecast", timestamp=decision_time, run_id=run_id, strategy_id=strategy_id, data_version=data_version, decision_time=decision_time, signal=_signal_record(decision), forecast=_forecast_record(decision.forecast))
        target_record = _target_record(decision)
        if margin_call and bool(risk["terminal_on_margin_call"]):
            target_record["target_weight"] = 0.0
            decision = _replace_target_weight(decision, 0.0)
        sequence = _append_event(events, sequence=sequence, event_type="TargetPosition", timestamp=decision_time, run_id=run_id, strategy_id=strategy_id, data_version=data_version, decision_time=decision_time, signal=_signal_record(decision), forecast=_forecast_record(decision.forecast), target_position=target_record, error_code="maintenance_margin_call_forced_exit" if margin_call else None)
        if index < len(daily) - 1:
            target_weight = float(decision.target.target_weight)
            risk_approved = (
                0.0 <= target_weight <= float(risk["max_target_weight"])
                and (not bool(risk["long_only"]) or target_weight >= 0.0)
                and close_equity > 0.0
            )
            risk_reason = "approved_frozen_target_within_limits" if risk_approved else "rejected_target_or_equity_limit"
            risk_id = _stable_id("risk", decision.target.target_position_id)
            intent_id = _stable_id("intent", decision.target.target_position_id)
            risk_record = {"risk_check_id": risk_id, "approved": risk_approved, "reason": risk_reason}
            sequence = _append_event(
                events,
                sequence=sequence,
                event_type="RiskDecision",
                timestamp=decision_time,
                run_id=run_id,
                strategy_id=strategy_id,
                data_version=data_version,
                decision_time=decision_time,
                signal=_signal_record(decision),
                forecast=_forecast_record(decision.forecast),
                target_position=_target_record(decision),
                risk_decision=risk_record,
                error_code=None if risk_approved else "risk_target_rejected",
            )
            sequence = _append_event(
                events,
                sequence=sequence,
                event_type="OrderIntent",
                timestamp=decision_time,
                run_id=run_id,
                strategy_id=strategy_id,
                data_version=data_version,
                decision_time=decision_time,
                signal=_signal_record(decision),
                forecast=_forecast_record(decision.forecast),
                target_position=_target_record(decision),
                risk_decision=risk_record,
                payload={"order_intent_id": intent_id, "quantity_rule": "target_weight_at_next_session_open"},
                error_code=None if risk_approved else "risk_target_rejected",
            )
            pending = {
                "decision": decision,
                "risk_approved": risk_approved,
                "risk_reason": risk_reason,
                "risk_id": risk_id,
                "intent_id": intent_id,
            }
        else:
            pending = None
        previous_close = close_price
        previous_session = session

    reconciliation = _reconcile(
        initial_cash=initial_cash,
        cash_entries=cash_ledger,
        fills=fills,
        final_quantity=quantity,
        final_cash=cash,
        final_equity=cash + quantity * float(daily.iloc[-1]["Close"]),
        final_price=float(daily.iloc[-1]["Close"]),
        orders=orders,
    )
    metrics = _metrics(exposure, fills, initial_cash, turnover_notional, costs_paid)
    lifecycle = {
        "created": len(orders),
        "risk_checked": max(0, len(daily) - 1),
        "accepted": sum(1 for order in orders if order["status"] not in {"rejected"}),
        "filled": sum(1 for order in orders if order["status"] == "filled"),
        "partially_filled": status_counts.get("partially_filled", 0),
        "rejected": status_counts.get("rejected", 0),
        "cancelled": status_counts.get("cancelled", 0),
        "expired": 0,
        "no_trade_decision_count": max(0, len(daily) - 1 - len(orders)),
        "gap_execution_count": sum(1 for fill in fills if fill.get("gap_return") not in {None, 0.0}),
        "margin_call_count": margin_call_count,
    }
    return _SimulationResult(events, orders, fills, positions, cash_ledger, exposure, reconciliation, metrics, lifecycle)


def _append_event(
    events: list[dict[str, Any]],
    *,
    sequence: int,
    event_type: str,
    timestamp: datetime,
    run_id: str,
    strategy_id: str,
    data_version: str,
    decision_time: datetime | None,
    signal: dict[str, Any] | None = None,
    forecast: dict[str, Any] | None = None,
    target_position: dict[str, Any] | None = None,
    risk_decision: dict[str, Any] | None = None,
    order_id: str | None = None,
    fill_id: str | None = None,
    error_code: str | None = None,
    payload: dict[str, Any] | None = None,
) -> int:
    next_sequence = sequence + 1
    event_id = _stable_id("event", run_id, next_sequence, event_type, timestamp.isoformat())
    events.append(
        {
            "sequence": next_sequence,
            "event_id": event_id,
            "event_type": event_type,
            "timestamp_utc": timestamp.astimezone(timezone.utc).isoformat(),
            "run_id": run_id,
            "strategy_id": strategy_id,
            "data_version": data_version,
            "decision_time": decision_time.astimezone(timezone.utc).isoformat() if decision_time else None,
            "signal": signal,
            "forecast": forecast,
            "target_position": target_position,
            "risk_decision": risk_decision,
            "order_id": order_id,
            "fill_id": fill_id,
            "error_code": error_code,
            "payload": payload or {},
        }
    )
    return next_sequence


def _signal_record(decision: FrozenStrategyDecision) -> dict[str, Any]:
    signal = decision.signal
    return {
        "signal_id": signal.signal_id,
        "direction": signal.direction.value,
        "strength": signal.strength,
        "horizon": signal.horizon,
        "reason": signal.reason,
    }


def _forecast_record(forecast: Forecast) -> dict[str, Any]:
    return {
        "forecast_id": forecast.forecast_id,
        "signal_id": forecast.signal_id,
        "value": forecast.value,
        "unit": forecast.unit,
        "confidence": forecast.confidence,
        "horizon": forecast.horizon,
        "reason": forecast.reason,
    }


def _target_record(decision: FrozenStrategyDecision) -> dict[str, Any]:
    target = decision.target
    return {
        "target_position_id": target.target_position_id,
        "signal_id": target.signal_id,
        "target_weight": target.target_weight,
        "symbol": target.symbol,
    }


def _replace_target_weight(decision: FrozenStrategyDecision, target_weight: float) -> FrozenStrategyDecision:
    return replace(decision, target=replace(decision.target, target_weight=target_weight))


def _cash_entry(
    run_id: str,
    timestamp: datetime,
    entry_type: str,
    amount: float,
    balance: float,
    order_id: str | None,
    fill_id: str | None,
) -> dict[str, Any]:
    entry_id = _stable_id("cash", run_id, timestamp.isoformat(), entry_type, order_id, fill_id, amount)
    return {
        "entry_id": entry_id,
        "run_id": run_id,
        "timestamp_utc": timestamp.astimezone(timezone.utc).isoformat(),
        "entry_type": entry_type,
        "amount": _round(amount, 10),
        "balance_after": _round(balance, 10),
        "order_id": order_id,
        "fill_id": fill_id,
        "error_code": None,
    }


def _position_entry(
    run_id: str,
    timestamp: datetime,
    entry_type: str,
    quantity_before: float,
    quantity_after: float,
    average_price: float,
    fill_id: str | None,
    market_price: float | None = None,
) -> dict[str, Any]:
    return {
        "entry_id": _stable_id("position", run_id, timestamp.isoformat(), entry_type, fill_id, quantity_after),
        "run_id": run_id,
        "timestamp_utc": timestamp.astimezone(timezone.utc).isoformat(),
        "entry_type": entry_type,
        "symbol": "QQQ",
        "quantity_before": _round(quantity_before, 8),
        "quantity_after": _round(quantity_after, 8),
        "average_price": _round(average_price, 8),
        "market_price": _round(market_price, 8) if market_price is not None else None,
        "fill_id": fill_id,
        "error_code": None,
    }


def _reconcile(
    *,
    initial_cash: float,
    cash_entries: list[dict[str, Any]],
    fills: list[dict[str, Any]],
    final_quantity: float,
    final_cash: float,
    final_equity: float,
    final_price: float,
    orders: list[dict[str, Any]],
) -> dict[str, Any]:
    replay_cash = sum(float(entry["amount"]) for entry in cash_entries)
    replay_quantity = 0.0
    for fill in fills:
        signed = float(fill["quantity"]) if fill["side"] == "buy" else -float(fill["quantity"])
        replay_quantity += signed
    replay_equity = replay_cash + replay_quantity * final_price
    order_ids = {str(order["order_id"]) for order in orders}
    orphan_fill_count = sum(1 for fill in fills if str(fill["order_id"]) not in order_ids)
    fill_ids = [str(fill["fill_id"]) for fill in fills]
    order_id_list = [str(order["order_id"]) for order in orders]
    cash_delta = replay_cash - final_cash
    quantity_delta = replay_quantity - final_quantity
    equity_delta = replay_equity - final_equity
    passed = (
        abs(cash_delta) <= 1e-6
        and abs(quantity_delta) <= 1e-8
        and abs(equity_delta) <= 1e-6
        and orphan_fill_count == 0
        and len(fill_ids) == len(set(fill_ids))
        and len(order_id_list) == len(set(order_id_list))
    )
    return {
        "status": "pass" if passed else "failed",
        "passed": passed,
        "initial_cash": _round(initial_cash),
        "reported_final_cash": _round(final_cash),
        "replayed_final_cash": _round(replay_cash),
        "cash_delta": _round(cash_delta),
        "reported_final_quantity": _round(final_quantity, 8),
        "replayed_final_quantity": _round(replay_quantity, 8),
        "quantity_delta": _round(quantity_delta, 8),
        "final_market_price": _round(final_price, 8),
        "reported_final_equity": _round(final_equity),
        "replayed_final_equity": _round(replay_equity),
        "equity_delta": _round(equity_delta),
        "orphan_fill_count": orphan_fill_count,
        "duplicate_fill_id_count": len(fill_ids) - len(set(fill_ids)),
        "duplicate_order_id_count": len(order_id_list) - len(set(order_id_list)),
        "pnl_source": "fills_plus_cash_plus_positions_plus_corporate_action_ledger",
        "price_series_nav_substitution_used": False,
    }


def _metrics(
    exposure: list[dict[str, Any]],
    fills: list[dict[str, Any]],
    initial_cash: float,
    turnover_notional: float,
    costs_paid: Mapping[str, float],
) -> dict[str, Any]:
    frame = pd.DataFrame(exposure)
    equity = frame["equity"].astype(float)
    returns = equity.pct_change(fill_method=None).fillna(0.0)
    years = max(len(equity) / 252.0, 1.0 / 252.0)
    total_return = float(equity.iloc[-1] / initial_cash - 1.0)
    annual_return = (1.0 + total_return) ** (1.0 / years) - 1.0 if total_return > -1 else -1.0
    annual_vol = float(returns.std(ddof=0) * math.sqrt(252.0))
    drawdown = equity / equity.cummax() - 1.0
    exposed = frame["gross_exposure"].astype(float) > 0
    years_by_session = pd.to_datetime(frame["session"]).dt.year
    yearly_returns = {
        str(int(year)): _round((1.0 + returns.loc[years_by_session == year]).prod() - 1.0)
        for year in sorted(years_by_session.unique())
    }
    best_year = max(yearly_returns, key=lambda key: float(yearly_returns[key] or 0.0))
    worst_year = min(yearly_returns, key=lambda key: float(yearly_returns[key] or 0.0))
    positive_total = sum(max(0.0, float(value or 0.0)) for value in yearly_returns.values())
    cost_values = {key: _round(value) for key, value in costs_paid.items()}
    cost_values["total"] = _round(sum(float(value) for value in costs_paid.values()))
    return {
        "initial_cash": _round(initial_cash),
        "final_cash": _round(float(frame["cash"].iloc[-1])),
        "final_equity": _round(float(equity.iloc[-1])),
        "total_return_pct": _round(total_return * 100.0),
        "annualized_return_pct": _round(annual_return * 100.0),
        "annualized_volatility_pct": _round(annual_vol * 100.0),
        "sharpe": _round(annual_return / annual_vol if annual_vol > 1e-12 else 0.0),
        "max_drawdown_abs_pct": _round(abs(float(drawdown.min())) * 100.0),
        "turnover_notional": _round(turnover_notional),
        "turnover_ratio": _round(turnover_notional / initial_cash),
        "exposure_ratio": _round(float(exposed.mean())),
        "average_holding_sessions": _average_holding_sessions(exposed.tolist()),
        "number_of_bets": _bet_count(exposed.tolist()),
        "yearly_returns": yearly_returns,
        "best_year": best_year,
        "best_year_return_pct": _round(float(yearly_returns[best_year] or 0.0) * 100.0),
        "best_year_positive_contribution_share": _round(max(0.0, float(yearly_returns[best_year] or 0.0)) / positive_total) if positive_total > 0 else 0.0,
        "worst_year": worst_year,
        "worst_year_return_pct": _round(float(yearly_returns[worst_year] or 0.0) * 100.0),
        "fill_count": len(fills),
        "capacity_proxy_max_participation_pct": _round(
            max((float(fill.get("volume_participation_pct") or 0.0) for fill in fills), default=0.0)
        ),
        "costs": cost_values,
        "pnl_from_ledger_only": True,
    }


def _average_holding_sessions(exposed: list[bool]) -> float:
    lengths: list[int] = []
    current = 0
    for value in exposed:
        if value:
            current += 1
        elif current:
            lengths.append(current)
            current = 0
    if current:
        lengths.append(current)
    return _round(sum(lengths) / len(lengths)) if lengths else 0.0


def _bet_count(exposed: list[bool]) -> int:
    return sum(1 for index, value in enumerate(exposed) if value and (index == 0 or not exposed[index - 1]))


def _cost_components(cost_model: Mapping[str, Any], total_bps: float) -> dict[str, float]:
    base_total = float(cost_model["base_total_bps"])
    scale = total_bps / base_total if base_total else 0.0
    return {
        "commission_bps": float(cost_model["commission_bps"]) * scale,
        "spread_bps": float(cost_model["spread_bps"]) * scale,
        "slippage_bps": float(cost_model["slippage_bps"]) * scale,
        "impact_bps": float(cost_model["impact_bps"]) * scale,
        "margin_interest_annual": float(cost_model["margin_interest_annual"]),
    }


def _no_lookahead_check(
    strategy: FrozenEtf26CompleteReturnStrategy,
    daily: pd.DataFrame,
    decisions: list[FrozenStrategyDecision],
    fills: list[dict[str, Any]],
) -> dict[str, Any]:
    timestamp_order_passed = all(
        datetime.fromisoformat(str(fill["decision_time"]))
        < datetime.fromisoformat(str(fill["filled_at"]))
        for fill in fills
    )
    same_bar_fill_count = sum(
        datetime.fromisoformat(str(fill["decision_time"]))
        >= datetime.fromisoformat(str(fill["filled_at"]))
        for fill in fills
    )
    cutoff = max(1, int(len(daily) * 0.8))
    truncated = strategy.generate(daily.iloc[:cutoff].copy())
    full_prefix = [
        (
            item.signal.timestamp_utc.isoformat(),
            item.signal.direction.value,
            item.signal.reason,
            item.forecast.value,
            item.target.target_weight,
        )
        for item in decisions[:cutoff]
    ]
    truncated_records = [
        (
            item.signal.timestamp_utc.isoformat(),
            item.signal.direction.value,
            item.signal.reason,
            item.forecast.value,
            item.target.target_weight,
        )
        for item in truncated
    ]
    truncation_invariance_passed = full_prefix == truncated_records
    return {
        "status": "pass_with_data_visibility_blocker" if timestamp_order_passed and truncation_invariance_passed else "failed",
        "decision_before_fill_passed": timestamp_order_passed,
        "same_bar_fill_count": same_bar_fill_count,
        "truncation_invariance_passed": truncation_invariance_passed,
        "truncation_cutoff_session": str(daily.iloc[cutoff - 1]["session"]),
        "feature_visibility_rule": "completed session OHLC only; rolling/EMA state uses current and prior completed bars",
        "available_time_field_present": False,
        "label_pipeline_used": False,
        "full_sample_normalization_used": False,
    }


def _cost_stress(
    *,
    config: Mapping[str, Any],
    daily: pd.DataFrame,
    decisions: list[FrozenStrategyDecision],
    run_id: str,
    strategy_id: str,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for total_bps in config["cost_model"]["stress_total_bps"]:
        simulation = _simulate(
            daily=daily,
            decisions=decisions,
            run_id=f"{run_id}-cost-{float(total_bps):g}",
            strategy_id=strategy_id,
            data_version=config["dataset_version"],
            initial_cash=float(config["initial_cash"]),
            risk=config["risk"],
            execution=config["execution"],
            costs=_cost_components(config["cost_model"], float(total_bps)),
        )
        rows.append(
            {
                "total_cost_bps": float(total_bps),
                "final_equity": simulation.metrics["final_equity"],
                "total_return_pct": simulation.metrics["total_return_pct"],
                "turnover_notional": simulation.metrics["turnover_notional"],
                "total_cost_paid": simulation.metrics["costs"]["total"],
                "reconciliation_passed": simulation.reconciliation["passed"],
            }
        )
    monotonic = all(
        float(rows[index]["final_equity"]) <= float(rows[index - 1]["final_equity"]) + 1e-6
        for index in range(1, len(rows))
    )
    return {
        "status": "pass" if monotonic and all(row["reconciliation_passed"] for row in rows) else "failed",
        "rows": rows,
        "cost_monotonic_nonincreasing_final_equity": monotonic,
        "margin_interest_annual_held_constant": float(config["cost_model"]["margin_interest_annual"]),
    }


def _walk_forward(exposure: list[dict[str, Any]], validation: Mapping[str, Any]) -> dict[str, Any]:
    frame = pd.DataFrame(exposure)
    frame["session_date"] = pd.to_datetime(frame["session"])
    frame["return"] = frame["equity"].astype(float).pct_change(fill_method=None).fillna(0.0)
    purge = int(validation["purge_sessions"])
    embargo = int(validation["embargo_sessions"])
    folds: list[dict[str, Any]] = []
    for year in sorted(int(value) for value in frame["session_date"].dt.year.unique() if int(value) >= 2020):
        indices = frame.index[frame["session_date"].dt.year == year].tolist()
        eligible = indices[purge : len(indices) - embargo if embargo else None]
        if len(eligible) < 20:
            continue
        fold = frame.loc[eligible]
        returns = fold["return"].astype(float)
        equity = (1.0 + returns).cumprod()
        total = float(equity.iloc[-1] - 1.0)
        annual_vol = float(returns.std(ddof=0) * math.sqrt(252.0))
        annual_return = (1.0 + total) ** (252.0 / len(returns)) - 1.0 if total > -1 else -1.0
        drawdown = equity / equity.cummax() - 1.0
        folds.append(
            {
                "test_year": year,
                "test_start": str(fold["session"].iloc[0]),
                "test_end": str(fold["session"].iloc[-1]),
                "session_count": len(fold),
                "parameters_frozen": True,
                "training_selection_used": False,
                "purge_sessions": purge,
                "embargo_sessions": embargo,
                "total_return_pct": _round(total * 100.0),
                "annualized_return_pct": _round(annual_return * 100.0),
                "sharpe": _round(annual_return / annual_vol if annual_vol > 1e-12 else 0.0),
                "max_drawdown_abs_pct": _round(abs(float(drawdown.min())) * 100.0),
                "exposure_ratio": _round(float((fold["gross_exposure"].astype(float) > 0).mean())),
            }
        )
    return {
        "status": "complete_exploratory_frozen_parameters",
        "method": "calendar_year_walk_forward_with_boundary_purge_and_embargo",
        "parameter_selection_performed": False,
        "fold_count": len(folds),
        "positive_fold_count": sum(float(fold["total_return_pct"]) > 0 for fold in folds),
        "folds": folds,
    }


def _confirmation_status(candidate: Mapping[str, Any], daily: pd.DataFrame) -> dict[str, Any]:
    window = candidate["independent_confirmation_window"]
    start = date.fromisoformat(window["start"])
    end = date.fromisoformat(window["end"])
    sessions = [
        str(value)
        for value in daily["session"].tolist()
        if start <= date.fromisoformat(str(value)) <= end
    ]
    minimum = int(window["minimum_complete_sessions"])
    complete = len(sessions) >= minimum and date.fromisoformat(str(daily["session"].max())) >= end
    return {
        "status": "complete" if complete else "incomplete",
        "start": window["start"],
        "end": window["end"],
        "minimum_complete_sessions": minimum,
        "observed_complete_sessions": len(sessions),
        "latest_observed_session": str(daily["session"].max()),
        "evaluation_performed": False,
        "evaluation_allowed": complete,
        "parameters_changed": False,
        "selection_or_ranking_performed": False,
    }


def _blockers(
    *,
    data_quality: Mapping[str, Any],
    goal2: Mapping[str, Any],
    confirmation: Mapping[str, Any],
    no_lookahead: Mapping[str, Any],
    reconciliation: Mapping[str, Any],
    deterministic_replay_hash_match: bool,
    cost_stress: Mapping[str, Any],
) -> list[str]:
    blockers = [
        "production_pit_intake_blocked_external_data",
        "corporate_action_available_time_replay_missing",
        "hf_adjusted_prices_not_point_in_time_replayable",
        "hf_multi_provider_splice_equivalence_not_proven",
        "hf_minute_available_time_not_provided_assumed_session_close",
        "halt_vs_missing_data_semantics_unavailable",
        "spread_model_research_proxy_no_quotes",
        "impact_model_research_proxy_no_depth",
        "synthetic_three_x_margin_candidate_not_broker_executable",
        "canonical_target_weight_translation_rebalances_at_next_open",
        f"independent_confirmation_window_not_complete:{confirmation['observed_complete_sessions']}_of_{confirmation['minimum_complete_sessions']}",
        f"independent_confirmation_evaluation_prohibited_before:{confirmation['end']}",
    ]
    if data_quality["missing_session_count"]:
        blockers.append(f"canonical_market_calendar_sessions_missing:{data_quality['missing_session_count']}")
    if data_quality["incomplete_session_count"]:
        blockers.append(f"canonical_market_calendar_sessions_incomplete:{data_quality['incomplete_session_count']}")
    if data_quality["missing_scheduled_open_bar_count"]:
        blockers.append(f"canonical_next_session_open_bar_missing:{data_quality['missing_scheduled_open_bar_count']}")
    if data_quality["missing_scheduled_close_bar_count"]:
        blockers.append(f"canonical_session_close_bar_missing:{data_quality['missing_scheduled_close_bar_count']}")
    if data_quality["duplicate_timestamp_count"]:
        blockers.append(f"canonical_duplicate_timestamps:{data_quality['duplicate_timestamp_count']}")
    if data_quality["null_required_row_count"]:
        blockers.append(f"canonical_null_required_rows:{data_quality['null_required_row_count']}")
    if data_quality["nonpositive_price_row_count"] or data_quality["invalid_ohlc_row_count"]:
        blockers.append("canonical_invalid_ohlc_rows_present")
    if no_lookahead["status"] == "failed":
        blockers.append("canonical_no_lookahead_check_failed")
    if reconciliation.get("passed") is not True:
        blockers.append("canonical_ledger_reconciliation_failed")
    if not deterministic_replay_hash_match:
        blockers.append("canonical_deterministic_replay_hash_mismatch")
    if cost_stress.get("status") != "pass":
        blockers.append("canonical_cost_stress_failed")
    for blocker in goal2.get("blockers", []):
        if str(blocker).startswith("production_pit_bundle_missing:"):
            blockers.append(str(blocker))
    return _dedupe(blockers)


def _audit_fields_present(events: Iterable[Mapping[str, Any]]) -> bool:
    required = {
        "run_id",
        "strategy_id",
        "data_version",
        "decision_time",
        "signal",
        "forecast",
        "target_position",
        "risk_decision",
        "order_id",
        "fill_id",
        "error_code",
    }
    return all(required <= set(event) for event in events)


def _write_immutable_run(
    *,
    root: Path,
    artifact_root: Path,
    run_id: str,
    generated_at: str,
    report: dict[str, Any],
    simulation: _SimulationResult,
    corporate_actions: list[dict[str, Any]],
    cost_stress: dict[str, Any],
    walk_forward: dict[str, Any],
    run_inputs: dict[str, Any],
) -> CanonicalRunResult:
    run_dir = artifact_root / "runs" / run_id
    latest_pointer = artifact_root / "latest_pointer.json"
    report["artifacts"] = {
        "run_dir": _relpath(run_dir, root),
        "latest_pointer": _relpath(latest_pointer, root),
        "immutable": True,
        "files": list(ARTIFACT_FILES),
    }
    payloads: dict[str, bytes] = {
        "event_log.jsonl": _jsonl_bytes(simulation.events),
        "orders.jsonl": _jsonl_bytes(simulation.orders),
        "fills.jsonl": _jsonl_bytes(simulation.fills),
        "position_ledger.jsonl": _jsonl_bytes(simulation.positions),
        "cash_ledger.jsonl": _jsonl_bytes(simulation.cash),
        "corporate_action_ledger.jsonl": _jsonl_bytes(corporate_actions),
        "reconciliation.json": _json_bytes(simulation.reconciliation),
        "exposure_timeline.jsonl": _jsonl_bytes(simulation.exposure),
        "cost_stress.json": _json_bytes(cost_stress),
        "walk_forward.json": _json_bytes(walk_forward),
        "report.json": _json_bytes(report),
        "report.md": _markdown(report).encode("utf-8"),
    }
    file_hashes = {
        name: {
            "sha256": hashlib.sha256(content).hexdigest(),
            "bytes": len(content),
            "row_count": content.count(b"\n") if name.endswith(".jsonl") else None,
        }
        for name, content in payloads.items()
    }
    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "run_id": run_id,
        "generated_at": generated_at,
        "status": report["status"],
        "code_commit": report["code_commit"],
        "code_tree_hash": report["code_tree_hash"],
        "candidate_id": report["candidate"]["candidate_id"],
        "data_version": report["data"]["data_version"],
        "params_hash": report["candidate"]["params_hash"],
        "cost_model_hash": report["cost_model"]["canonical_cost_model_hash"],
        "inputs": run_inputs,
        "files": file_hashes,
        "guardrails": dict(report["guardrails"]),
    }
    manifest_bytes = _json_bytes(manifest)
    all_payloads = {**payloads, "manifest.json": manifest_bytes}
    if run_dir.exists():
        for name, expected in all_payloads.items():
            path = run_dir / name
            if not path.is_file() or path.read_bytes() != expected:
                raise ValueError(f"canonical_immutable_run_conflict:{name}")
    else:
        run_dir.mkdir(parents=True, exist_ok=False)
        for name, content in all_payloads.items():
            (run_dir / name).write_bytes(content)
    manifest_hash = hashlib.sha256(manifest_bytes).hexdigest()
    pointer = {
        "schema_version": "us_etf_26_canonical_latest_pointer_v1",
        "run_id": run_id,
        "run_dir": _relpath(run_dir, root),
        "manifest": _relpath(run_dir / "manifest.json", root),
        "manifest_sha256": manifest_hash,
        "report": _relpath(run_dir / "report.json", root),
        "report_sha256": file_hashes["report.json"]["sha256"],
        "code_commit": report["code_commit"],
        "status": report["status"],
        "promotion_credit_allowed": False,
        "paper_or_live_unlock_allowed": False,
    }
    artifact_root.mkdir(parents=True, exist_ok=True)
    _atomic_write(latest_pointer, _json_bytes(pointer))
    return CanonicalRunResult(
        run_id=run_id,
        run_dir=run_dir,
        latest_pointer=latest_pointer,
        report=report,
        manifest=manifest,
        manifest_sha256=manifest_hash,
    )


def _markdown(report: Mapping[str, Any]) -> str:
    recon = report["ledger_reconciliation"]
    confirmation = report["independent_confirmation"]
    performance = report["performance"]
    lines = [
        "# US ETF26 Canonical Event-Driven Backtest Evidence",
        "",
        f"- Run: `{report['run_id']}`",
        f"- Candidate: `{report['candidate']['candidate_id']}`",
        f"- Status: `{report['status']}`",
        f"- Decision: `{report['decision']}`",
        f"- Code commit: `{report['code_commit']}`",
        f"- Data version: `{report['data']['data_version']}`",
        f"- Final equity: `{performance['final_equity']}`",
        f"- Ledger cash delta: `{recon['cash_delta']}`",
        f"- Ledger quantity delta: `{recon['quantity_delta']}`",
        f"- Ledger equity delta: `{recon['equity_delta']}`",
        f"- Confirmation: `{confirmation['status']}` ({confirmation['observed_complete_sessions']}/{confirmation['minimum_complete_sessions']})",
        "- Promotion credit allowed: `false`",
        "- Paper/live unlock allowed: `false`",
        "",
        "## Blockers",
        "",
    ]
    lines.extend(f"- `{blocker}`" for blocker in report["blockers"])
    return "\n".join(lines) + "\n"


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"canonical_json_not_object:{path.name}")
    return payload


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, default=_json_default) + "\n").encode("utf-8")


def _jsonl_bytes(rows: Iterable[Mapping[str, Any]]) -> bytes:
    return b"".join(
        (json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=_json_default) + "\n").encode("utf-8")
        for row in rows
    )


def _json_default(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if hasattr(value, "item"):
        return value.item()
    raise TypeError(f"not JSON serializable: {type(value).__name__}")


def _stable_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=_json_default).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _stable_id(prefix: str, *parts: object) -> str:
    return f"{prefix}_{hashlib.sha256('|'.join(str(part) for part in parts).encode('utf-8')).hexdigest()[:20]}"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _round(value: float | int | None, digits: int = 6) -> float | None:
    if value is None or not math.isfinite(float(value)):
        return None
    return round(float(value), digits)


def _relpath(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _dedupe(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


def _atomic_write(path: Path, content: bytes) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(content)
    temporary.replace(path)
