"""Candidate-specific portfolio and promotion evidence for the frozen ETF26 run.

The service consumes only the immutable Goal 3 canonical artifacts and the
validated read-only ETF26 dataset.  It never calls a broker, creates a real
order, or upgrades research evidence to promotion credit.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import pandas as pd

from quant_us.data.shared_hf_etf26 import ResolvedHfEtf26Dataset


SCHEMA_VERSION = "us_etf_26_candidate_portfolio_report_v1"
MANIFEST_SCHEMA_VERSION = "us_etf_26_candidate_portfolio_manifest_v1"
ARTIFACT_FILES = (
    "portfolio_construction.json",
    "risk_decisions.jsonl",
    "portfolio_event_ledger.jsonl",
    "ledger_pnl.json",
    "reconciliation.json",
    "cost_stress.json",
    "sector_style_exposure.json",
    "liquidity_capacity.json",
    "walk_forward.json",
    "promotion_evidence.json",
    "report.json",
    "report.md",
)
FALSE_GUARDRAILS = (
    "promotion_credit_allowed",
    "promotion_unlock_allowed",
    "paper_or_live_unlock_allowed",
    "paper_order_allowed",
    "live_order_allowed",
    "paper_queue_write_allowed",
    "private_endpoint_used",
    "order_endpoint_used",
    "broker_endpoint_used",
    "network_used",
    "secret_read",
    "real_order_submitted",
    "source_data_modified",
)


@dataclass(frozen=True)
class CandidatePortfolioRunResult:
    run_id: str
    run_dir: Path
    latest_pointer: Path
    report: dict[str, Any]
    manifest: dict[str, Any]
    manifest_sha256: str


def build_us_etf_26_candidate_portfolio(
    *,
    repo_root: Path,
    config_path: Path,
    resolved_dataset: ResolvedHfEtf26Dataset,
    code_commit: str,
    code_tree_hash: str,
    generated_at: str,
    artifact_root_override: Path | None = None,
) -> CandidatePortfolioRunResult:
    """Build immutable Goal 4 evidence without mutating the Goal 3 run."""

    root = repo_root.resolve()
    config_abs = _resolve_repo_path(root, config_path)
    config = _read_json(config_abs)
    candidate_path = _resolve_repo_path(root, Path(str(config["candidate_config"])))
    goal2_path = _resolve_repo_path(root, Path(str(config["goal2_intake_report"])))
    candidate = _read_json(candidate_path)
    goal2 = _read_json(goal2_path)
    canonical = _load_and_validate_canonical(root=root, config=config)
    _validate_inputs(
        config=config,
        candidate=candidate,
        goal2=goal2,
        canonical=canonical,
        resolved_dataset=resolved_dataset,
    )

    universe = [str(symbol).upper() for symbol in candidate["universe"]]
    research_window = canonical["report"]["candidate"]["research_window"]
    daily_close, daily_dollar_volume, universe_data = _load_universe_daily(
        resolved_dataset=resolved_dataset,
        universe=universe,
        start=date.fromisoformat(str(research_window["requested_start"])),
        end=date.fromisoformat(str(research_window["requested_end"])),
    )
    analysis = analyze_candidate_portfolio(
        config=config,
        candidate=candidate,
        goal2=goal2,
        canonical=canonical,
        daily_close=daily_close,
        daily_dollar_volume=daily_dollar_volume,
        universe_data=universe_data,
        code_commit=code_commit,
        code_tree_hash=code_tree_hash,
        generated_at=generated_at,
        config_sha256=_sha256_file(config_abs),
        candidate_sha256=_sha256_file(candidate_path),
        goal2_sha256=_sha256_file(goal2_path),
        data_manifest_sha256=resolved_dataset.manifest_sha256,
    )
    artifact_root = (
        artifact_root_override.resolve()
        if artifact_root_override is not None
        else _resolve_repo_path(root, Path(str(config["artifact_root"])))
    )
    return _write_immutable_run(
        root=root,
        artifact_root=artifact_root,
        generated_at=generated_at,
        analysis=analysis,
    )


def analyze_candidate_portfolio(
    *,
    config: Mapping[str, Any],
    candidate: Mapping[str, Any],
    goal2: Mapping[str, Any],
    canonical: Mapping[str, Any],
    daily_close: pd.DataFrame,
    daily_dollar_volume: pd.DataFrame,
    universe_data: Mapping[str, Any],
    code_commit: str,
    code_tree_hash: str,
    generated_at: str,
    config_sha256: str,
    candidate_sha256: str,
    goal2_sha256: str,
    data_manifest_sha256: str,
) -> dict[str, Any]:
    """Pure analysis entry point used by tests and the artifact builder."""

    report = canonical["report"]
    fills = canonical["fills"]
    positions = canonical["positions"]
    cash = canonical["cash"]
    corporate_actions = canonical["corporate_actions"]
    exposure = canonical["exposure"]
    events = canonical["events"]
    constraints = _mapping(config["constraints"])
    risk_estimation = _mapping(config["risk_estimation"])

    risk_model = _risk_model(
        daily_close=daily_close,
        universe=[str(item) for item in candidate["universe"]],
        benchmark_symbol=str(config["benchmark_symbol"]),
        risk_estimation=risk_estimation,
    )
    pnl = _ledger_pnl(
        fills=fills,
        positions=positions,
        cash=cash,
        corporate_actions=corporate_actions,
        initial_cash=float(report["performance"]["initial_cash"]),
    )
    reconciliation = _portfolio_reconciliation(
        report=report,
        fills=fills,
        positions=positions,
        cash=cash,
        corporate_actions=corporate_actions,
    )
    decisions = _risk_decisions(
        events=events,
        exposure=exposure,
        config=config,
        risk_model=risk_model,
    )
    event_ledger = _portfolio_event_ledger(
        report=report,
        decisions=decisions,
        fills=fills,
        positions=positions,
        cash=cash,
        corporate_actions=corporate_actions,
    )
    replay_event_ledger = _portfolio_event_ledger(
        report=report,
        decisions=decisions,
        fills=fills,
        positions=positions,
        cash=cash,
        corporate_actions=corporate_actions,
    )
    reconciliation["portfolio_event_ledger_hash"] = _stable_hash(event_ledger)
    reconciliation["deterministic_replay_hash_match"] = (
        _stable_hash(event_ledger) == _stable_hash(replay_event_ledger)
    )
    reconciliation["portfolio_event_id_unique"] = len(
        {str(item["portfolio_event_id"]) for item in event_ledger}
    ) == len(event_ledger)
    reconciliation["passed"] = bool(
        reconciliation["canonical_reconciliation_passed"]
        and reconciliation["ledger_inputs_reconciled"]
        and abs(float(reconciliation["cash_delta"])) <= 1e-6
        and abs(float(reconciliation["quantity_delta"])) <= 1e-6
        and abs(float(reconciliation["equity_delta"])) <= 1e-6
        and reconciliation["duplicate_fill_id_count"] == 0
        and reconciliation["orphan_fill_count"] == 0
        and reconciliation["deterministic_replay_hash_match"]
        and reconciliation["portfolio_event_id_unique"]
    )
    reconciliation["status"] = "pass" if reconciliation["passed"] else "blocked"

    active_risk = _benchmark_active_risk(
        pnl_records=pnl["records"],
        daily_close=daily_close,
        benchmark_symbol=str(config["benchmark_symbol"]),
    )
    exposure_report = _sector_style_exposure(
        exposure=exposure,
        constraints=constraints,
        candidate_symbol=str(candidate["selection"]["symbol"]),
    )
    liquidity = _liquidity_capacity(
        fills=fills,
        daily_dollar_volume=daily_dollar_volume,
        symbol=str(candidate["selection"]["symbol"]),
        target_weight=float(candidate["selection"]["exposure_multiplier"]),
        constraints=constraints,
    )
    cost_stress = _portfolio_cost_stress(
        canonical_cost_stress=_mapping(report["cost_stress"]),
        fills=fills,
        target_weight=float(candidate["selection"]["exposure_multiplier"]),
    )
    construction = _portfolio_construction(
        config=config,
        candidate=candidate,
        report=report,
        decisions=decisions,
        risk_model=risk_model,
        active_risk=active_risk,
        exposure_report=exposure_report,
        liquidity=liquidity,
    )
    walk_forward = _walk_forward_layer(report)
    blockers = _promotion_blockers(
        report=report,
        goal2=goal2,
        construction=construction,
        exposure_report=exposure_report,
        liquidity=liquidity,
        pnl=pnl,
        reconciliation=reconciliation,
    )
    layers = _evidence_layers(
        report=report,
        construction=construction,
        cost_stress=cost_stress,
        exposure_report=exposure_report,
        walk_forward=walk_forward,
        reconciliation=reconciliation,
        event_ledger=event_ledger,
        pnl=pnl,
        blockers=blockers,
    )
    promotion_evidence = {
        "status": "blocked",
        "decision": "promotion_evidence_blocked_fail_closed",
        "promotion_credit_allowed": False,
        "required_layers": list(layers),
        "layers": layers,
        "engineering_layer_pass_count": sum(
            1 for layer in layers.values() if layer["engineering_passed"] is True
        ),
        "promotion_layer_pass_count": sum(
            1 for layer in layers.values() if layer["promotion_passed"] is True
        ),
        "blockers": blockers,
    }
    guardrails = {key: False for key in FALSE_GUARDRAILS}
    guardrails.update(
        {
            "research_only": True,
            "fail_closed": True,
            "source_canonical_run_modified": False,
            "price_series_nav_substitution_used": False,
            "strategy_parameters_mutated": False,
        }
    )
    run_inputs = {
        "candidate_id": candidate["candidate_id"],
        "canonical_run_id": report["run_id"],
        "canonical_manifest_sha256": canonical["manifest_sha256"],
        "canonical_report_sha256": canonical["report_sha256"],
        "candidate_config_sha256": candidate_sha256,
        "goal2_report_sha256": goal2_sha256,
        "goal4_config_sha256": config_sha256,
        "data_version": config["dataset_version"],
        "data_aggregate_sha256": config["aggregate_sha256"],
        "data_manifest_sha256": data_manifest_sha256,
        "params_hash": report["candidate"]["params_hash"],
        "cost_model_hash": report["cost_model"]["canonical_cost_model_hash"],
        "code_commit": code_commit,
        "code_tree_hash": code_tree_hash,
        "generated_at": generated_at,
    }
    run_inputs_hash = _stable_hash(run_inputs)
    run_id = f"us-etf26-portfolio-{run_inputs_hash[:16]}"
    portfolio_report = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "generated_at": generated_at,
        "status": "engineering_evidence_complete_promotion_blocked",
        "decision": "portfolio_engineering_layers_complete_promotion_evidence_blocked",
        "code_commit": code_commit,
        "code_tree_hash": code_tree_hash,
        "candidate": {
            "candidate_id": candidate["candidate_id"],
            "strategy_version": candidate["strategy_version"],
            "symbol": candidate["selection"]["symbol"],
            "timeframe": candidate["selection"]["timeframe"],
            "frozen_exposure_multiplier": candidate["selection"]["exposure_multiplier"],
            "params_hash": report["candidate"]["params_hash"],
            "parameter_tuning_performed": False,
            "symbol_or_timeframe_reselection_performed": False,
            "sample_role": "exploratory_selection_sample_not_clean_holdout",
            "universe": list(candidate["universe"]),
        },
        "canonical_dependency": {
            "run_id": report["run_id"],
            "code_commit": report["code_commit"],
            "manifest_sha256": canonical["manifest_sha256"],
            "report_sha256": canonical["report_sha256"],
            "fill_count": len(fills),
            "promotion_credit_allowed": False,
            "reconciliation_passed": report["ledger_reconciliation"]["passed"],
        },
        "data": {
            "dataset_id": config["dataset_id"],
            "data_version": config["dataset_version"],
            "readiness_class": "research_ready",
            "aggregate_sha256": config["aggregate_sha256"],
            "manifest_sha256": data_manifest_sha256,
            "consumer_read_only": True,
            "universe_data": dict(universe_data),
        },
        "forecast_to_portfolio": construction,
        "risk_adjusted_contribution": active_risk,
        "ledger_pnl": {key: value for key, value in pnl.items() if key != "records"},
        "ledger_reconciliation": reconciliation,
        "cost_stress": cost_stress,
        "sector_style_exposure": exposure_report,
        "liquidity_capacity": liquidity,
        "walk_forward": walk_forward,
        "promotion_evidence": promotion_evidence,
        "counts": {
            "canonical_order_count": int(report["event_chain"]["order_count"]),
            "canonical_fill_count": len(fills),
            "canonical_position_ledger_count": len(positions),
            "canonical_cash_ledger_count": len(cash),
            "canonical_corporate_action_ledger_count": len(corporate_actions),
            "risk_decision_count": len(decisions),
            "portfolio_event_ledger_count": len(event_ledger),
            "ledger_pnl_session_count": len(pnl["records"]),
        },
        "hashes": {
            **run_inputs,
            "run_inputs_hash": run_inputs_hash,
            "portfolio_event_ledger_content_hash": _stable_hash(event_ledger),
            "risk_decisions_content_hash": _stable_hash(decisions),
            "ledger_pnl_content_hash": _stable_hash(pnl),
        },
        "blockers": blockers,
        "guardrails": guardrails,
    }
    return {
        "run_id": run_id,
        "run_inputs": run_inputs,
        "report": portfolio_report,
        "portfolio_construction": construction,
        "risk_decisions": decisions,
        "portfolio_event_ledger": event_ledger,
        "ledger_pnl": pnl,
        "reconciliation": reconciliation,
        "cost_stress": cost_stress,
        "sector_style_exposure": exposure_report,
        "liquidity_capacity": liquidity,
        "walk_forward": walk_forward,
        "promotion_evidence": promotion_evidence,
    }


def _load_and_validate_canonical(*, root: Path, config: Mapping[str, Any]) -> dict[str, Any]:
    pointer_path = _resolve_repo_path(root, Path(str(config["canonical_latest_pointer"])))
    pointer = _read_json(pointer_path)
    expected = {
        "run_id": config["expected_canonical_run_id"],
        "code_commit": config["expected_canonical_code_commit"],
        "manifest_sha256": config["expected_canonical_manifest_sha256"],
        "report_sha256": config["expected_canonical_report_sha256"],
        "promotion_credit_allowed": False,
        "paper_or_live_unlock_allowed": False,
    }
    for key, value in expected.items():
        if pointer.get(key) != value:
            raise ValueError(f"goal3_pointer_{key}_mismatch")
    manifest_path = _resolve_repo_path(root, Path(str(pointer["manifest"])))
    report_path = _resolve_repo_path(root, Path(str(pointer["report"])))
    if _sha256_file(manifest_path) != pointer["manifest_sha256"]:
        raise ValueError("goal3_manifest_hash_mismatch")
    if _sha256_file(report_path) != pointer["report_sha256"]:
        raise ValueError("goal3_report_hash_mismatch")
    manifest = _read_json(manifest_path)
    report = _read_json(report_path)
    run_dir = manifest_path.parent
    if manifest.get("run_id") != pointer["run_id"] or report.get("run_id") != pointer["run_id"]:
        raise ValueError("goal3_run_id_mismatch")
    for name, metadata in _mapping(manifest.get("files")).items():
        path = (run_dir / name).resolve()
        _require_within(run_dir, path, "goal3_artifact_path_escape")
        if not path.is_file() or _sha256_file(path) != _mapping(metadata).get("sha256"):
            raise ValueError(f"goal3_artifact_hash_mismatch:{name}")
    return {
        "pointer": pointer,
        "manifest": manifest,
        "report": report,
        "manifest_sha256": pointer["manifest_sha256"],
        "report_sha256": pointer["report_sha256"],
        "run_dir": run_dir,
        "events": _read_jsonl(run_dir / "event_log.jsonl"),
        "fills": _read_jsonl(run_dir / "fills.jsonl"),
        "positions": _read_jsonl(run_dir / "position_ledger.jsonl"),
        "cash": _read_jsonl(run_dir / "cash_ledger.jsonl"),
        "corporate_actions": _read_jsonl(run_dir / "corporate_action_ledger.jsonl"),
        "exposure": _read_jsonl(run_dir / "exposure_timeline.jsonl"),
    }


def _validate_inputs(
    *,
    config: Mapping[str, Any],
    candidate: Mapping[str, Any],
    goal2: Mapping[str, Any],
    canonical: Mapping[str, Any],
    resolved_dataset: ResolvedHfEtf26Dataset,
) -> None:
    if config.get("schema_version") != "us_etf_26_candidate_portfolio_config_v1":
        raise ValueError("goal4_config_schema_mismatch")
    report = _mapping(canonical["report"])
    checks = {
        "candidate_id": candidate.get("candidate_id"),
        "strategy_version": candidate.get("strategy_version"),
        "data_version": config.get("dataset_version"),
    }
    if _mapping(report.get("candidate")).get("candidate_id") != checks["candidate_id"]:
        raise ValueError("goal4_candidate_id_mismatch")
    if _mapping(report.get("candidate")).get("strategy_version") != checks["strategy_version"]:
        raise ValueError("goal4_strategy_version_mismatch")
    if _mapping(report.get("data")).get("data_version") != checks["data_version"]:
        raise ValueError("goal4_data_version_mismatch")
    if report.get("status") != "complete_research_only_blocked":
        raise ValueError("goal3_status_not_research_only_blocked")
    if _mapping(report.get("guardrails")).get("promotion_credit_allowed") is not False:
        raise ValueError("goal3_promotion_credit_not_false")
    if _mapping(report.get("ledger_reconciliation")).get("passed") is not True:
        raise ValueError("goal3_reconciliation_not_passed")
    if goal2.get("status") != "blocked_external_data":
        raise ValueError("goal2_status_not_blocked_external_data")
    if resolved_dataset.manifest.get("dataset_version") != config.get("dataset_version"):
        raise ValueError("goal4_resolved_data_version_mismatch")
    if resolved_dataset.manifest.get("aggregate_sha256") != config.get("aggregate_sha256"):
        raise ValueError("goal4_resolved_aggregate_hash_mismatch")
    if resolved_dataset.manifest.get("readiness_class") != "research_ready":
        raise ValueError("goal4_resolved_data_not_research_ready")
    if float(_mapping(candidate.get("selection")).get("exposure_multiplier", 0.0)) != 3.0:
        raise ValueError("goal4_frozen_exposure_multiplier_mismatch")


def _load_universe_daily(
    *,
    resolved_dataset: ResolvedHfEtf26Dataset,
    universe: Sequence[str],
    start: date,
    end: date,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    entries = {
        str(item.get("path", "")).split("/")[0].removeprefix("symbol=").upper(): item
        for item in resolved_dataset.manifest.get("files", [])
        if isinstance(item, dict)
    }
    close_series: dict[str, pd.Series] = {}
    dollar_volume_series: dict[str, pd.Series] = {}
    row_counts: dict[str, int] = {}
    session_counts: dict[str, int] = {}
    start_ts = pd.Timestamp(start)
    end_exclusive = pd.Timestamp(end) + pd.Timedelta(days=1)
    for symbol in universe:
        entry = entries.get(symbol)
        if not isinstance(entry, dict):
            raise ValueError(f"goal4_universe_manifest_entry_missing:{symbol}")
        path = (resolved_dataset.root / str(entry["path"])).resolve()
        _require_within(resolved_dataset.root, path, "goal4_universe_path_escape")
        if not path.is_file():
            raise ValueError(f"goal4_universe_file_missing:{symbol}")
        frame = pd.read_parquet(
            path,
            columns=["datetime", "Close", "Volume"],
            filters=[("datetime", ">=", start_ts), ("datetime", "<", end_exclusive)],
        )
        if frame.empty:
            raise ValueError(f"goal4_universe_research_window_empty:{symbol}")
        frame = frame.sort_values("datetime", kind="stable")
        frame["session"] = pd.to_datetime(frame["datetime"]).dt.strftime("%Y-%m-%d")
        frame["dollar_volume"] = frame["Close"].astype(float) * frame["Volume"].astype(float)
        grouped = frame.groupby("session", sort=True)
        close_series[symbol] = grouped["Close"].last().astype(float)
        dollar_volume_series[symbol] = grouped["dollar_volume"].sum().astype(float)
        row_counts[symbol] = int(len(frame))
        session_counts[symbol] = int(grouped.ngroups)
    daily_close = pd.DataFrame(close_series).sort_index()
    daily_dollar_volume = pd.DataFrame(dollar_volume_series).sort_index()
    return daily_close, daily_dollar_volume, {
        "universe_count": len(universe),
        "loaded_symbol_count": len(close_series),
        "unavailable_symbols": [],
        "row_counts": row_counts,
        "session_counts": session_counts,
        "research_start": start.isoformat(),
        "research_end": end.isoformat(),
        "price_adjustment_available_time_present": False,
        "point_in_time_holdings_present": False,
        "correlation_inputs_promotion_clean": False,
    }


def _risk_model(
    *,
    daily_close: pd.DataFrame,
    universe: Sequence[str],
    benchmark_symbol: str,
    risk_estimation: Mapping[str, Any],
) -> dict[str, Any]:
    returns = daily_close.loc[:, list(universe)].pct_change(fill_method=None)
    lookback = int(risk_estimation["lookback_sessions"])
    minimum_symbol = int(risk_estimation["minimum_symbol_sessions"])
    minimum_pairwise = int(risk_estimation["minimum_pairwise_sessions"])
    annualization = int(risk_estimation["annualization_sessions"])
    sample = returns.tail(lookback)
    observations = {symbol: int(sample[symbol].notna().sum()) for symbol in universe}
    volatility: dict[str, float | None] = {}
    for symbol in universe:
        values = sample[symbol].dropna()
        volatility[symbol] = (
            _round(values.std(ddof=1) * math.sqrt(annualization), 8)
            if len(values) >= minimum_symbol
            else None
        )
    correlation: dict[str, dict[str, float | None]] = {}
    pairwise_unavailable: list[str] = []
    for left in universe:
        row: dict[str, float | None] = {}
        for right in universe:
            pair = sample[[left, right]].dropna()
            key = f"{left}:{right}"
            if len(pair) < minimum_pairwise:
                row[right] = None
                pairwise_unavailable.append(key)
            elif left == right:
                row[right] = 1.0
            else:
                row[right] = _round(pair[left].corr(pair[right]), 8)
        correlation[left] = row
    qqq_vol = volatility.get("QQQ")
    target_vol = float(risk_estimation["target_annual_volatility"])
    volatility_scaled_weight = (
        min(1.0, target_vol / float(qqq_vol)) if qqq_vol and qqq_vol > 0 else None
    )
    return {
        "status": "estimated_research_only",
        "method": "pairwise_daily_close_returns_trailing_visible_sessions",
        "lookback_sessions": lookback,
        "minimum_symbol_sessions": minimum_symbol,
        "minimum_pairwise_sessions": minimum_pairwise,
        "annualization_sessions": annualization,
        "as_of_session": str(daily_close.index.max()),
        "universe_count": len(universe),
        "estimated_symbol_count": sum(value is not None for value in volatility.values()),
        "observations": observations,
        "annualized_volatility": volatility,
        "correlation": correlation,
        "pairwise_unavailable": _dedupe(pairwise_unavailable),
        "qqq_spy_correlation": correlation.get("QQQ", {}).get(benchmark_symbol),
        "target_annual_volatility": target_vol,
        "qqq_one_x_volatility_scaled_weight": _round(volatility_scaled_weight, 8),
        "diversification_used_for_candidate": False,
        "effective_candidate_asset_count": 1,
        "estimation_boundaries": [
            "price_return_correlation_only_not_constituent_or_factor_correlation",
            "research_ready_adjusted_prices_without_adjustment_available_time_replay",
            "pairwise_missing_values_not_imputed",
            "full_26_etf_estimates_do_not_create_candidate_diversification",
        ],
        "promotion_credit_allowed": False,
    }


def _ledger_pnl(
    *,
    fills: Sequence[Mapping[str, Any]],
    positions: Sequence[Mapping[str, Any]],
    cash: Sequence[Mapping[str, Any]],
    corporate_actions: Sequence[Mapping[str, Any]],
    initial_cash: float,
) -> dict[str, Any]:
    """Replay periodic equity strictly from canonical ledgers.

    Position ``mark`` rows supply the periodic quantity and market price. Cash
    and corporate-action rows are accumulated only when their recorded event
    time is visible. The canonical exposure timeline is deliberately absent
    from this function and cannot influence PnL.
    """

    marks = sorted(
        (
            dict(row)
            for row in positions
            if row.get("market_price") is not None
            and str(row.get("entry_type") or "mark") == "mark"
        ),
        key=lambda row: _ledger_timestamp(row),
    )
    cash_events = sorted((dict(row) for row in cash), key=lambda row: _ledger_timestamp(row))
    timed_actions: list[tuple[datetime, float]] = []
    unallocated_corporate_action_count = 0
    for row in corporate_actions:
        amount = _corporate_action_amount(row)
        timestamp = _optional_ledger_timestamp(row)
        if timestamp is None:
            if abs(amount) > 1e-12:
                unallocated_corporate_action_count += 1
            continue
        timed_actions.append((timestamp, amount))
    timed_actions.sort(key=lambda item: item[0])

    records: list[dict[str, Any]] = []
    previous_equity: float | None = None
    peak = initial_cash
    cash_index = 0
    action_index = 0
    cash_balance = 0.0
    corporate_action_balance = 0.0
    for row in marks:
        timestamp = _ledger_timestamp(row)
        while cash_index < len(cash_events) and _ledger_timestamp(cash_events[cash_index]) <= timestamp:
            cash_balance += float(cash_events[cash_index].get("amount", 0.0) or 0.0)
            cash_index += 1
        while action_index < len(timed_actions) and timed_actions[action_index][0] <= timestamp:
            corporate_action_balance += timed_actions[action_index][1]
            action_index += 1
        quantity = float(row.get("quantity_after", 0.0) or 0.0)
        market_price = float(row["market_price"])
        position_value = quantity * market_price
        equity = cash_balance + position_value + corporate_action_balance
        daily_pnl = 0.0 if previous_equity is None else equity - previous_equity
        daily_return = 0.0 if previous_equity in (None, 0.0) else daily_pnl / float(previous_equity)
        peak = max(peak, equity)
        records.append(
            {
                "session": timestamp.date().isoformat(),
                "timestamp_utc": str(row["timestamp_utc"]),
                "cash": _round(cash_balance),
                "quantity": _round(quantity, 8),
                "market_price": _round(market_price),
                "position_value": _round(position_value),
                "corporate_action_balance": _round(corporate_action_balance),
                "equity": _round(equity),
                "daily_pnl": _round(daily_pnl),
                "daily_return": _round(daily_return, 10),
                "cumulative_pnl": _round(equity - initial_cash),
                "drawdown": _round(equity / peak - 1.0, 10),
                "source": "canonical_fill_cash_position_corporate_action_ledgers",
            }
        )
        previous_equity = equity
    final_equity = float(records[-1]["equity"]) if records else initial_cash
    returns = pd.Series([float(item["daily_return"]) for item in records], dtype=float)
    return {
        "status": "pass" if records and unallocated_corporate_action_count == 0 else "blocked",
        "pnl_source": "fills_plus_positions_plus_cash_plus_corporate_action_ledger",
        "price_series_nav_substitution_used": False,
        "exposure_timeline_used": False,
        "replay_method": "periodic_position_marks_plus_asof_cash_and_corporate_action_ledgers",
        "input_hashes": {
            "fills": _stable_hash(fills),
            "positions": _stable_hash(positions),
            "cash": _stable_hash(cash),
            "corporate_actions": _stable_hash(corporate_actions),
        },
        "fill_count": len(fills),
        "position_ledger_count": len(positions),
        "cash_ledger_count": len(cash),
        "corporate_action_ledger_count": len(corporate_actions),
        "unallocated_corporate_action_count": unallocated_corporate_action_count,
        "initial_cash": _round(initial_cash),
        "final_equity": _round(final_equity),
        "total_pnl": _round(final_equity - initial_cash),
        "total_return_pct": _round((final_equity / initial_cash - 1.0) * 100.0),
        "worst_daily_return_pct": _round(returns.min() * 100.0),
        "session_count": len(records),
        "records": records,
    }


def _portfolio_reconciliation(
    *,
    report: Mapping[str, Any],
    fills: Sequence[Mapping[str, Any]],
    positions: Sequence[Mapping[str, Any]],
    cash: Sequence[Mapping[str, Any]],
    corporate_actions: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    replay_cash = sum(float(row["amount"]) for row in cash)
    replay_quantity = sum(
        float(row["quantity"]) if row["side"] == "buy" else -float(row["quantity"])
        for row in fills
    )
    corporate_action_pnl = sum(_corporate_action_amount(row) for row in corporate_actions)
    canonical_recon = _mapping(report["ledger_reconciliation"])
    final_price = float(canonical_recon["final_market_price"])
    replay_equity = replay_cash + replay_quantity * final_price + corporate_action_pnl
    reported_cash = float(canonical_recon["reported_final_cash"])
    reported_quantity = float(canonical_recon["reported_final_quantity"])
    reported_equity = float(canonical_recon["reported_final_equity"])
    fill_ids = [str(row["fill_id"]) for row in fills]
    order_ids = {str(row["order_id"]) for row in fills}
    cash_fill_ids = {str(row["fill_id"]) for row in cash if row.get("fill_id")}
    position_fill_rows = [row for row in positions if row.get("fill_id")]
    position_fill_ids = {str(row["fill_id"]) for row in position_fill_rows}
    position_fill_quantity = sum(
        float(row.get("quantity_after", 0.0) or 0.0)
        - float(row.get("quantity_before", 0.0) or 0.0)
        for row in position_fill_rows
    )
    position_marks = sorted(
        (row for row in positions if row.get("market_price") is not None),
        key=lambda item: _ledger_timestamp(item),
    )
    final_position_quantity = float(
        (position_marks[-1] if position_marks else positions[-1]).get("quantity_after", 0.0)
        if positions
        else 0.0
    )
    running_cash = 0.0
    cash_balance_chain_max_delta = 0.0
    for row in sorted(cash, key=lambda item: _ledger_timestamp(item)):
        running_cash += float(row.get("amount", 0.0) or 0.0)
        recorded_balance = row.get("balance_after", row.get("balance"))
        if recorded_balance is not None:
            cash_balance_chain_max_delta = max(
                cash_balance_chain_max_delta,
                abs(running_cash - float(recorded_balance)),
            )
    settlement_by_fill: dict[str, float] = {}
    for row in cash:
        if row.get("fill_id") and str(row.get("entry_type")) in {"fill_settlement", "fill_and_commission"}:
            fill_id = str(row["fill_id"])
            settlement_by_fill[fill_id] = settlement_by_fill.get(fill_id, 0.0) + float(
                row.get("amount", 0.0) or 0.0
            )
    fill_settlement_max_delta = 0.0
    for row in fills:
        fill_id = str(row["fill_id"])
        side = str(row["side"]).lower()
        price = float(row.get("fill_price", row.get("price", 0.0)) or 0.0)
        expected_settlement = float(row["quantity"]) * price * (-1.0 if side == "buy" else 1.0)
        settlement_type = next(
            (
                str(item.get("entry_type"))
                for item in cash
                if str(item.get("fill_id")) == fill_id
                and str(item.get("entry_type")) in {"fill_settlement", "fill_and_commission"}
            ),
            "",
        )
        if settlement_type == "fill_and_commission":
            expected_settlement -= float(row.get("commission", 0.0) or 0.0)
        fill_settlement_max_delta = max(
            fill_settlement_max_delta,
            abs(settlement_by_fill.get(fill_id, 0.0) - expected_settlement),
        )
    position_fill_quantity_delta = position_fill_quantity - replay_quantity
    final_position_quantity_delta = final_position_quantity - replay_quantity
    ledger_inputs_reconciled = bool(
        abs(replay_cash - reported_cash) <= 1e-6
        and abs(replay_quantity - reported_quantity) <= 1e-6
        and abs(replay_equity - reported_equity) <= 1e-6
        and abs(position_fill_quantity_delta) <= 1e-6
        and abs(final_position_quantity_delta) <= 1e-6
        and cash_balance_chain_max_delta <= 1e-6
        and fill_settlement_max_delta <= 1e-6
        and len(fill_ids) == len(set(fill_ids))
        and all(fill_id in cash_fill_ids for fill_id in fill_ids)
        and all(fill_id in position_fill_ids for fill_id in fill_ids)
    )
    return {
        "status": "pending",
        "passed": False,
        "canonical_reconciliation_passed": canonical_recon.get("passed") is True,
        "pnl_source": "fills_plus_positions_plus_cash_plus_corporate_action_ledger",
        "price_series_nav_substitution_used": False,
        "exposure_timeline_used": False,
        "ledger_inputs_reconciled": ledger_inputs_reconciled,
        "fill_count": len(fills),
        "position_ledger_count": len(positions),
        "cash_ledger_count": len(cash),
        "corporate_action_ledger_count": len(corporate_actions),
        "reported_final_cash": _round(reported_cash),
        "replayed_final_cash": _round(replay_cash),
        "cash_delta": _round(replay_cash - reported_cash, 10),
        "reported_final_quantity": _round(reported_quantity, 8),
        "replayed_final_quantity": _round(replay_quantity, 8),
        "quantity_delta": _round(replay_quantity - reported_quantity, 10),
        "reported_final_equity": _round(reported_equity),
        "replayed_final_equity": _round(replay_equity),
        "equity_delta": _round(replay_equity - reported_equity, 10),
        "corporate_action_pnl": _round(corporate_action_pnl),
        "position_fill_quantity_delta": _round(position_fill_quantity_delta, 10),
        "final_position_quantity_delta": _round(final_position_quantity_delta, 10),
        "cash_balance_chain_max_delta": _round(cash_balance_chain_max_delta, 10),
        "fill_settlement_max_delta": _round(fill_settlement_max_delta, 10),
        "duplicate_fill_id_count": len(fill_ids) - len(set(fill_ids)),
        "orphan_fill_count": sum(1 for fill_id in fill_ids if fill_id not in cash_fill_ids),
        "orphan_position_fill_count": sum(1 for fill_id in fill_ids if fill_id not in position_fill_ids),
        "fill_order_id_count": len(order_ids),
    }


def _optional_ledger_timestamp(row: Mapping[str, Any]) -> datetime | None:
    value = next(
        (
            row.get(key)
            for key in ("timestamp_utc", "available_time", "event_time", "as_of_utc")
            if row.get(key)
        ),
        None,
    )
    if value is None:
        return None
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("goal4_ledger_timestamp_timezone_missing")
    return parsed


def _ledger_timestamp(row: Mapping[str, Any]) -> datetime:
    parsed = _optional_ledger_timestamp(row)
    if parsed is None:
        raise ValueError("goal4_ledger_timestamp_missing")
    return parsed


def _corporate_action_amount(row: Mapping[str, Any]) -> float:
    if row.get("amount") is not None:
        return float(row.get("amount") or 0.0)
    return float(row.get("pnl_adjustment", 0.0) or 0.0)


def _risk_decisions(
    *,
    events: Sequence[Mapping[str, Any]],
    exposure: Sequence[Mapping[str, Any]],
    config: Mapping[str, Any],
    risk_model: Mapping[str, Any],
) -> list[dict[str, Any]]:
    constraints = _mapping(config["constraints"])
    forecast_conversion = _mapping(config["forecast_conversion"])
    exposure_by_session = {str(item["session"]): item for item in exposure}
    daily_return_by_session: dict[str, float] = {}
    previous_equity: float | None = None
    for item in exposure:
        equity = float(item.get("equity", 0.0) or 0.0)
        daily_return_by_session[str(item["session"])] = (
            0.0 if previous_equity in (None, 0.0) else equity / float(previous_equity) - 1.0
        )
        previous_equity = equity
    risk_by_target: dict[str, Mapping[str, Any]] = {}
    for event in events:
        if event.get("event_type") != "RiskDecision":
            continue
        target = _mapping(event.get("target_position"))
        target_id = str(target.get("target_position_id") or "")
        if target_id:
            risk_by_target[target_id] = _mapping(event.get("risk_decision"))
    results: list[dict[str, Any]] = []
    for event in events:
        if event.get("event_type") != "TargetPosition":
            continue
        signal = _mapping(event.get("signal"))
        forecast = _mapping(event.get("forecast"))
        target = _mapping(event.get("target_position"))
        target_weight = float(target.get("target_weight", 0.0))
        alpha_score = float(signal.get("strength", 0.0)) * float(forecast.get("confidence", 0.0))
        session = str(event.get("decision_time") or event.get("timestamp_utc"))[:10]
        state = _mapping(exposure_by_session.get(session))
        equity = float(state.get("equity", 0.0) or 0.0)
        cash_weight = float(state.get("cash", 0.0) or 0.0) / equity if equity else 1.0
        leverage = float(state.get("leverage", 0.0) or 0.0)
        drawdown = abs(min(float(state.get("drawdown", 0.0) or 0.0), 0.0))
        daily_return = float(daily_return_by_session.get(session, 0.0))
        stale_trading_sessions = 0 if state else int(constraints["max_stale_trading_sessions"]) + 1
        breaches: list[str] = []
        if target_weight > float(constraints["max_single_asset_weight"]):
            breaches.append("max_single_asset_weight")
        if target_weight > float(constraints["max_gross_exposure"]):
            breaches.append("max_gross_exposure")
        if target_weight > float(constraints["max_net_exposure"]):
            breaches.append("max_net_exposure")
        if max(target_weight, leverage) > float(constraints["max_leverage"]):
            breaches.append("max_leverage")
        if cash_weight < float(constraints["minimum_cash_weight"]):
            breaches.append("minimum_cash_weight")
        if drawdown > float(constraints["max_drawdown"]):
            breaches.append("max_drawdown")
        if daily_return < -float(constraints["max_daily_loss"]):
            breaches.append("max_daily_loss")
        if stale_trading_sessions > int(constraints["max_stale_trading_sessions"]):
            breaches.append("stale_data")
        if target_weight > 0:
            breaches.extend(["sector_exposure_unavailable", "style_exposure_unavailable"])
        target_id = str(target.get("target_position_id") or "")
        canonical_risk = _mapping(risk_by_target.get(target_id))
        risk_id = _stable_id("portfolio_risk", event.get("run_id"), target_id)
        results.append(
            {
                "run_id": event.get("run_id"),
                "strategy_id": event.get("strategy_id"),
                "data_version": event.get("data_version"),
                "decision_time": event.get("decision_time"),
                "signal": signal,
                "forecast": forecast,
                "alpha": {
                    "score": _round(alpha_score, 8),
                    "score_rule": forecast_conversion["alpha_score_rule"],
                    "expected_active_return": None,
                    "expected_return_calibration_available": False,
                    "error_code": forecast_conversion["expected_return_blocker"],
                },
                "target_position": target,
                "risk_decision": {
                    "risk_decision_id": risk_id,
                    "canonical_risk_check_id": canonical_risk.get("risk_check_id"),
                    "canonical_research_replay_approved": canonical_risk.get("approved") is True,
                    "approved_for_research_replay": canonical_risk.get("approved") is True,
                    "approved_for_promotion": False,
                    "decision": "block_promotion_fail_closed",
                    "breaches": _dedupe(breaches),
                    "current_leverage": _round(leverage, 8),
                    "current_cash_weight": _round(cash_weight, 8),
                    "current_drawdown": _round(drawdown, 8),
                    "current_daily_return": _round(daily_return, 8),
                    "stale_data_trading_sessions": stale_trading_sessions,
                    "max_stale_trading_sessions": int(constraints["max_stale_trading_sessions"]),
                    "stale_data_check_passed": stale_trading_sessions <= int(constraints["max_stale_trading_sessions"]),
                    "qqq_annualized_volatility": _mapping(risk_model["annualized_volatility"]).get("QQQ"),
                },
                "order_id": None,
                "fill_id": None,
                "error_code": "promotion_credit_disallowed",
            }
        )
    return results


def _portfolio_event_ledger(
    *,
    report: Mapping[str, Any],
    decisions: Sequence[Mapping[str, Any]],
    fills: Sequence[Mapping[str, Any]],
    positions: Sequence[Mapping[str, Any]],
    cash: Sequence[Mapping[str, Any]],
    corporate_actions: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    run_id = str(report["run_id"])
    strategy_id = str(_mapping(report["candidate"])["strategy_id"])
    data_version = str(_mapping(report["data"])["data_version"])
    rows: list[dict[str, Any]] = []

    def append(event_type: str, source_id: str, timestamp: str | None, payload: Mapping[str, Any]) -> None:
        rows.append(
            {
                "portfolio_event_id": _stable_id("portfolio_event", run_id, event_type, source_id),
                "sequence": len(rows) + 1,
                "event_type": event_type,
                "source_id": source_id,
                "timestamp_utc": timestamp,
                "run_id": run_id,
                "strategy_id": strategy_id,
                "data_version": data_version,
                "decision_time": payload.get("decision_time"),
                "signal": payload.get("signal"),
                "forecast": payload.get("forecast"),
                "alpha": payload.get("alpha"),
                "target_position": payload.get("target_position"),
                "risk_decision": payload.get("risk_decision"),
                "order_id": payload.get("order_id"),
                "fill_id": payload.get("fill_id"),
                "error_code": payload.get("error_code"),
                "payload": dict(payload.get("payload") or {}),
            }
        )

    for item in decisions:
        risk = _mapping(item["risk_decision"])
        append(
            "PortfolioRiskDecision",
            str(risk["risk_decision_id"]),
            str(item["decision_time"]),
            item,
        )
    for item in fills:
        append(
            "PortfolioFill",
            str(item["fill_id"]),
            str(item["filled_at"]),
            {
                "decision_time": item.get("decision_time"),
                "signal": {"signal_id": item.get("signal_id")},
                "forecast": {"forecast_id": item.get("forecast_id")},
                "target_position": {"target_position_id": item.get("target_position_id")},
                "risk_decision": {"risk_check_id": item.get("risk_check_id")},
                "order_id": item.get("order_id"),
                "fill_id": item.get("fill_id"),
                "error_code": item.get("error_code"),
                "payload": {
                    "symbol": item.get("symbol"),
                    "side": item.get("side"),
                    "quantity": item.get("quantity"),
                    "fill_price": item.get("fill_price"),
                    "commission": item.get("commission"),
                    "spread_cost": item.get("spread_cost"),
                    "slippage_cost": item.get("slippage_cost"),
                    "impact_cost": item.get("impact_cost"),
                },
            },
        )
    for item in positions:
        append(
            "PortfolioPositionLedger",
            str(item["entry_id"]),
            str(item["timestamp_utc"]),
            {
                "fill_id": item.get("fill_id"),
                "error_code": item.get("error_code"),
                "payload": dict(item),
            },
        )
    for item in cash:
        append(
            "PortfolioCashLedger",
            str(item["entry_id"]),
            str(item["timestamp_utc"]),
            {
                "order_id": item.get("order_id"),
                "fill_id": item.get("fill_id"),
                "error_code": item.get("error_code"),
                "payload": dict(item),
            },
        )
    for index, item in enumerate(corporate_actions):
        source_id = str(item.get("event_id") or item.get("entry_id") or f"coverage_{index}")
        append(
            "PortfolioCorporateActionLedger",
            source_id,
            str(item.get("timestamp_utc") or item.get("as_of_utc") or ""),
            {"error_code": item.get("error_code"), "payload": dict(item)},
        )
    return rows


def _benchmark_active_risk(
    *,
    pnl_records: Sequence[Mapping[str, Any]],
    daily_close: pd.DataFrame,
    benchmark_symbol: str,
) -> dict[str, Any]:
    portfolio = pd.Series(
        {str(item["session"]): float(item["daily_return"]) for item in pnl_records},
        name="portfolio",
        dtype=float,
    )
    benchmark = daily_close[benchmark_symbol].pct_change(fill_method=None).rename("benchmark")
    benchmark.index = benchmark.index.astype(str)
    aligned = pd.concat([portfolio, benchmark], axis=1).dropna()
    if aligned.empty:
        return {
            "status": "blocked",
            "blockers": ["benchmark_active_risk_overlap_missing"],
            "promotion_credit_allowed": False,
        }
    active = aligned["portfolio"] - aligned["benchmark"]
    annualized_active_return = float(active.mean() * 252.0)
    active_risk = float(active.std(ddof=1) * math.sqrt(252.0))
    information_ratio = annualized_active_return / active_risk if active_risk > 0 else None
    benchmark_variance = float(aligned["benchmark"].var(ddof=1))
    beta = (
        float(aligned["portfolio"].cov(aligned["benchmark"]) / benchmark_variance)
        if benchmark_variance > 0
        else None
    )
    residual = (
        aligned["portfolio"] - float(beta) * aligned["benchmark"]
        if beta is not None
        else aligned["portfolio"]
    )
    residual_risk = float(residual.std(ddof=1) * math.sqrt(252.0))
    return {
        "status": "estimated_research_only",
        "benchmark": benchmark_symbol,
        "aligned_session_count": int(len(aligned)),
        "benchmark_total_return_pct": _round(
            ((1.0 + aligned["benchmark"]).prod() - 1.0) * 100.0
        ),
        "annualized_active_return_pct": _round(annualized_active_return * 100.0),
        "active_risk_pct": _round(active_risk * 100.0),
        "information_ratio": _round(information_ratio, 8),
        "benchmark_beta": _round(beta, 8),
        "residual_risk_pct": _round(residual_risk * 100.0),
        "candidate_marginal_risk_contribution_pct": 100.0,
        "candidate_risk_adjusted_contribution_note": (
            "sole QQQ candidate contributes all modeled portfolio active risk; "
            "this is concentration, not diversification"
        ),
        "pnl_source": "ledger_derived_portfolio_returns",
        "price_series_nav_substitution_used": False,
        "promotion_credit_allowed": False,
    }


def _sector_style_exposure(
    *,
    exposure: Sequence[Mapping[str, Any]],
    constraints: Mapping[str, Any],
    candidate_symbol: str,
) -> dict[str, Any]:
    gross_weights: list[float] = []
    cash_weights: list[float] = []
    for row in exposure:
        equity = float(row.get("equity", 0.0) or 0.0)
        if equity == 0:
            continue
        gross_weights.append(float(row.get("gross_exposure", 0.0) or 0.0) / equity)
        cash_weights.append(float(row.get("cash", 0.0) or 0.0) / equity)
    max_gross = max(gross_weights, default=0.0)
    max_single = max_gross
    max_net = max_gross
    min_cash = min(cash_weights, default=1.0)
    checks = {
        "single_asset": max_single <= float(constraints["max_single_asset_weight"]),
        "gross_exposure": max_gross <= float(constraints["max_gross_exposure"]),
        "net_exposure": max_net <= float(constraints["max_net_exposure"]),
        "cash": min_cash >= float(constraints["minimum_cash_weight"]),
        "sector": False,
        "style": False,
    }
    return {
        "status": "blocked_for_promotion",
        "candidate_symbol": candidate_symbol,
        "instrument_exposure": {
            "effective_asset_count": 1,
            "max_single_asset_weight": _round(max_single, 8),
            "max_gross_exposure": _round(max_gross, 8),
            "max_net_exposure": _round(max_net, 8),
            "minimum_cash_weight": _round(min_cash, 8),
            "short_exposure": 0.0,
            "long_only": True,
        },
        "sector_exposure": {
            "status": "unavailable",
            "point_in_time_holdings_available": False,
            "unknown_exposure_max": _round(max_gross, 8),
            "limit": constraints["max_sector_weight"],
            "blocker": "sector_exposure_unavailable_without_point_in_time_holdings",
        },
        "style_exposure": {
            "status": "unavailable",
            "point_in_time_holdings_available": False,
            "unknown_exposure_max": _round(max_gross, 8),
            "limit": constraints["max_style_weight"],
            "blocker": "style_exposure_unavailable_without_point_in_time_holdings",
        },
        "constraint_checks": checks,
        "all_constraints_passed": all(checks.values()),
        "diversification_claimed": False,
        "promotion_credit_allowed": False,
    }


def _liquidity_capacity(
    *,
    fills: Sequence[Mapping[str, Any]],
    daily_dollar_volume: pd.DataFrame,
    symbol: str,
    target_weight: float,
    constraints: Mapping[str, Any],
) -> dict[str, Any]:
    notionals = [abs(float(row["quantity"]) * float(row["arrival_price"])) for row in fills]
    participations = [float(row["volume_participation_pct"]) for row in fills]
    minimum_order = float(constraints["minimum_order_notional"])
    max_participation = float(constraints["max_volume_participation_pct"])
    adv20 = daily_dollar_volume[symbol].rolling(20, min_periods=20).mean().dropna()
    latest_adv20 = float(adv20.iloc[-1]) if not adv20.empty else 0.0
    median_adv20 = float(adv20.median()) if not adv20.empty else 0.0
    latest_trade_capacity = latest_adv20 * max_participation / 100.0
    median_account_capacity = (
        median_adv20 * max_participation / 100.0 / abs(target_weight)
        if target_weight
        else None
    )
    below_minimum = sum(value < minimum_order for value in notionals)
    actual_max_participation = max(participations, default=0.0)
    return {
        "status": "engineering_complete_candidate_blocked",
        "symbol": symbol,
        "fill_count": len(fills),
        "minimum_order_notional": minimum_order,
        "minimum_fill_notional": _round(min(notionals, default=0.0)),
        "median_fill_notional": _round(pd.Series(notionals).median() if notionals else 0.0),
        "maximum_fill_notional": _round(max(notionals, default=0.0)),
        "fills_below_minimum_order_notional": below_minimum,
        "max_volume_participation_pct_limit": max_participation,
        "actual_max_volume_participation_pct": _round(actual_max_participation, 8),
        "volume_participation_passed": actual_max_participation <= max_participation,
        "minimum_order_notional_passed": below_minimum == 0,
        "latest_20_session_adv_dollars": _round(latest_adv20),
        "median_20_session_adv_dollars": _round(median_adv20),
        "latest_trade_capacity_at_limit_dollars": _round(latest_trade_capacity),
        "median_account_capacity_at_frozen_3x_dollars": _round(median_account_capacity),
        "capacity_method": "20_session_mean_dollar_volume_x_participation_limit_divided_by_target_weight",
        "capacity_is_research_proxy": True,
        "quotes_or_depth_available": False,
        "promotion_credit_allowed": False,
    }


def _portfolio_cost_stress(
    *,
    canonical_cost_stress: Mapping[str, Any],
    fills: Sequence[Mapping[str, Any]],
    target_weight: float,
) -> dict[str, Any]:
    rows = [dict(item) for item in canonical_cost_stress.get("rows", [])]
    final_equities = [float(item["final_equity"]) for item in rows]
    monotonic = all(left >= right for left, right in zip(final_equities, final_equities[1:]))
    total_fill_notional = sum(abs(float(row["quantity"]) * float(row["arrival_price"])) for row in fills)
    return {
        "status": "pass_engineering_research_only" if rows and monotonic else "blocked",
        "rows": rows,
        "cost_monotonic_nonincreasing_final_equity": monotonic,
        "canonical_fill_notional": _round(total_fill_notional),
        "frozen_target_weight": target_weight,
        "weight_cost_linkage": (
            "fill notional and turnover scale with the frozen target weight; each stress row "
            "is replayed through fills, cash and positions"
        ),
        "cost_components": [
            "commission",
            "spread",
            "slippage",
            "impact",
            "margin_interest",
        ],
        "borrow": "not_applicable_long_only",
        "promotion_credit_allowed": False,
    }


def _portfolio_construction(
    *,
    config: Mapping[str, Any],
    candidate: Mapping[str, Any],
    report: Mapping[str, Any],
    decisions: Sequence[Mapping[str, Any]],
    risk_model: Mapping[str, Any],
    active_risk: Mapping[str, Any],
    exposure_report: Mapping[str, Any],
    liquidity: Mapping[str, Any],
) -> dict[str, Any]:
    constraints = _mapping(config["constraints"])
    instrument_models = _mapping(config["instrument_models"])
    qqq_vol = _mapping(risk_model["annualized_volatility"]).get("QQQ")
    frozen_weight = float(_mapping(candidate["selection"])["exposure_multiplier"])
    expected_vol = float(qqq_vol) * frozen_weight if qqq_vol is not None else None
    risk_budget_weight = risk_model.get("qqq_one_x_volatility_scaled_weight")
    max_leverage = float(_mapping(_mapping(exposure_report)["instrument_exposure"])["max_gross_exposure"])
    risk_breaches = sorted(
        {
            breach
            for item in decisions
            for breach in _mapping(item["risk_decision"]).get("breaches", [])
        }
    )
    return {
        "status": "engineering_complete_promotion_blocked",
        "source_type": "candidate_specific_canonical_research_evidence",
        "signal_to_forecast_alpha": {
            "signal_object": "canonical Signal with binary strength in {0,1}",
            "forecast_object": "canonical Forecast with next_session_open_to_open horizon",
            "forecast_unit": config["forecast_conversion"]["forecast_unit"],
            "alpha_score_rule": config["forecast_conversion"]["alpha_score_rule"],
            "expected_return_calibration_available": False,
            "expected_return_calibration_blocker": config["forecast_conversion"]["expected_return_blocker"],
            "decision_count": len(decisions),
        },
        "forecast_to_target_position": {
            "canonical_rule": config["forecast_conversion"]["canonical_target_rule"],
            "cash_target_weight": 0.0,
            "long_target_weight": frozen_weight,
            "frozen_parameters_unchanged": True,
            "risk_budget_one_x_weight": risk_budget_weight,
            "risk_budget_one_x_weight_applied_to_canonical_fills": False,
            "reason_not_applied": "Goal 4 audits the immutable frozen Goal 3 fills and does not retune or replace them",
        },
        "risk_budget": {
            "target_annual_volatility": config["risk_estimation"]["target_annual_volatility"],
            "qqq_one_x_annualized_volatility": qqq_vol,
            "canonical_synthetic_three_x_expected_volatility": _round(expected_vol, 8),
            "correlation_model": risk_model,
            "single_candidate_marginal_risk_contribution_pct": 100.0,
            "diversification_used": False,
            "effective_asset_count": 1,
        },
        "constraints": {
            "configured": dict(constraints),
            "observed_max_leverage": _round(max_leverage, 8),
            "breaches": risk_breaches,
            "all_candidate_constraints_passed": _mapping(exposure_report).get("all_constraints_passed") is True,
        },
        "data_freshness_risk": {
            "latest_complete_session": risk_model["as_of_session"],
            "latest_complete_data_stale_trading_sessions": 0,
            "max_stale_trading_sessions": constraints["max_stale_trading_sessions"],
            "stale_data_check_passed": True,
            "available_time_field_present": False,
            "available_time_blocker": "hf_minute_available_time_not_provided_assumed_session_close",
        },
        "turnover_cost_liquidity": {
            "canonical_turnover_notional": report["performance"]["turnover_notional"],
            "canonical_turnover_ratio": report["performance"]["turnover_ratio"],
            "total_cost_paid": report["performance"]["costs"]["total"],
            "minimum_order_notional_passed": liquidity["minimum_order_notional_passed"],
            "volume_participation_passed": liquidity["volume_participation_passed"],
        },
        "benchmark_active_risk": dict(active_risk),
        "instrument_models": {
            "qqq_one_x": {
                **dict(_mapping(instrument_models["qqq_one_x"])),
                "economic_exposure": "unlevered QQQ share ownership",
                "promotion_status": "blocked_by_pit_and_confirmation",
            },
            "qqq_synthetic_three_x": {
                **dict(_mapping(instrument_models["qqq_synthetic_three_x"])),
                "economic_exposure": "three times QQQ notional financed with external margin debt",
                "path_risks": ["margin_interest", "margin_call", "gap_loss", "financing_availability"],
                "promotion_status": "prohibited_research_danger_reference",
            },
            "tqqq_intrinsic_leverage": {
                **dict(_mapping(instrument_models["tqqq_intrinsic_leverage"])),
                "economic_exposure": "daily reset leveraged ETF with embedded derivatives and financing",
                "path_risks": ["daily_reset", "volatility_drag", "fund_expenses", "derivative_counterparty"],
                "promotion_status": "not_evaluated_no_canonical_fills",
            },
        },
        "equivalence": {
            "qqq_one_x_equals_qqq_synthetic_three_x": False,
            "qqq_synthetic_three_x_equals_tqqq_intrinsic_leverage": False,
            "qqq_one_x_equals_tqqq_intrinsic_leverage": False,
            "statement": (
                "QQQ 1x, externally financed synthetic QQQ 3x and TQQQ intrinsic daily-reset leverage "
                "have different financing, path dependency, liquidation and cost semantics"
            ),
        },
        "promotion_credit_allowed": False,
    }


def _walk_forward_layer(report: Mapping[str, Any]) -> dict[str, Any]:
    walk = _mapping(report["walk_forward"])
    confirmation = _mapping(report["independent_confirmation"])
    return {
        "status": "engineering_pass_confirmation_blocked",
        "method": walk.get("method"),
        "fold_count": walk.get("fold_count"),
        "positive_fold_count": walk.get("positive_fold_count"),
        "parameters_frozen": all(
            _mapping(item).get("parameters_frozen") is True for item in walk.get("folds", [])
        ),
        "parameter_selection_performed": walk.get("parameter_selection_performed"),
        "purged_and_embargoed": all(
            int(_mapping(item).get("purge_sessions", 0)) > 0
            and int(_mapping(item).get("embargo_sessions", 0)) > 0
            for item in walk.get("folds", [])
        ),
        "independent_confirmation": dict(confirmation),
        "engineering_passed": int(walk.get("fold_count", 0)) > 0,
        "promotion_passed": False,
        "promotion_credit_allowed": False,
    }


def _promotion_blockers(
    *,
    report: Mapping[str, Any],
    goal2: Mapping[str, Any],
    construction: Mapping[str, Any],
    exposure_report: Mapping[str, Any],
    liquidity: Mapping[str, Any],
    pnl: Mapping[str, Any],
    reconciliation: Mapping[str, Any],
) -> list[str]:
    blockers = list(report.get("blockers", []))
    if goal2.get("status") == "blocked_external_data":
        blockers.append("production_pit_intake_blocked_external_data")
    blockers.extend(
        [
            "forecast_alpha_calibration_unavailable_without_clean_oos_ic",
            "portfolio_diversification_not_available_single_candidate_qqq",
            "sector_exposure_unavailable_without_point_in_time_holdings",
            "style_exposure_unavailable_without_point_in_time_holdings",
            "synthetic_three_x_margin_candidate_not_broker_executable",
            "tqqq_intrinsic_leverage_not_modeled_or_equivalent",
        ]
    )
    observed = _mapping(_mapping(construction["constraints"])).get("observed_max_leverage")
    max_leverage = float(_mapping(_mapping(construction["constraints"])["configured"])["max_leverage"])
    if observed is not None and float(observed) > max_leverage:
        blockers.append(f"canonical_synthetic_leverage_exceeds_executable_limit:{observed}_gt_{max_leverage}")
    instrument = _mapping(exposure_report["instrument_exposure"])
    max_single = float(instrument["max_single_asset_weight"])
    single_limit = float(_mapping(_mapping(construction["constraints"])["configured"])["max_single_asset_weight"])
    if max_single > single_limit:
        blockers.append(f"canonical_single_asset_concentration_exceeds_limit:{max_single}_gt_{single_limit}")
    min_cash = float(instrument["minimum_cash_weight"])
    min_cash_limit = float(_mapping(_mapping(construction["constraints"])["configured"])["minimum_cash_weight"])
    if min_cash < min_cash_limit:
        blockers.append(f"canonical_cash_constraint_breached:{min_cash}_lt_{min_cash_limit}")
    max_drawdown = float(report["performance"]["max_drawdown_abs_pct"]) / 100.0
    drawdown_limit = float(_mapping(_mapping(construction["constraints"])["configured"])["max_drawdown"])
    if max_drawdown > drawdown_limit:
        blockers.append(f"canonical_max_drawdown_exceeds_limit:{_round(max_drawdown, 8)}_gt_{drawdown_limit}")
    daily_loss = abs(min(float(pnl["worst_daily_return_pct"]) / 100.0, 0.0))
    daily_loss_limit = float(_mapping(_mapping(construction["constraints"])["configured"])["max_daily_loss"])
    if daily_loss > daily_loss_limit:
        blockers.append(f"canonical_daily_loss_exceeds_limit:{_round(daily_loss, 8)}_gt_{daily_loss_limit}")
    below = int(liquidity["fills_below_minimum_order_notional"])
    if below:
        blockers.append(f"canonical_fills_below_minimum_order_notional:{below}")
    if reconciliation.get("passed") is not True:
        blockers.append("goal4_portfolio_reconciliation_failed")
    return _dedupe(str(item) for item in blockers)


def _evidence_layers(
    *,
    report: Mapping[str, Any],
    construction: Mapping[str, Any],
    cost_stress: Mapping[str, Any],
    exposure_report: Mapping[str, Any],
    walk_forward: Mapping[str, Any],
    reconciliation: Mapping[str, Any],
    event_ledger: Sequence[Mapping[str, Any]],
    pnl: Mapping[str, Any],
    blockers: Sequence[str],
) -> dict[str, dict[str, Any]]:
    candidate_validation = bool(
        report.get("status") == "complete_research_only_blocked"
        and _mapping(report["candidate"]).get("parameter_tuning_performed") is False
    )
    event_pass = bool(event_ledger)
    recon_pass = reconciliation.get("passed") is True
    construction_pass = construction.get("status") == "engineering_complete_promotion_blocked"
    cost_pass = cost_stress.get("cost_monotonic_nonincreasing_final_equity") is True
    exposure_engineering = bool(_mapping(exposure_report).get("constraint_checks"))
    walk_engineering = walk_forward.get("engineering_passed") is True
    layers = {
        "candidate_validation": _layer(candidate_validation, False, [] if candidate_validation else ["candidate_validation_failed"]),
        "event_ledger": _layer(event_pass, False, [] if event_pass else ["portfolio_event_ledger_missing"]),
        "reconciliation": _layer(recon_pass, False, [] if recon_pass else ["goal4_portfolio_reconciliation_failed"]),
        "construction": _layer(construction_pass, False, [] if construction_pass else ["portfolio_construction_missing"]),
        "cost_stress": _layer(cost_pass, False, [] if cost_pass else ["portfolio_cost_stress_failed"]),
        "exposure_constraints": _layer(
            exposure_engineering,
            exposure_report.get("all_constraints_passed") is True,
            [
                item
                for item in blockers
                if "exposure" in item or "concentration" in item or "cash_constraint" in item
            ],
        ),
        "walk_forward": _layer(
            walk_engineering,
            False,
            [
                str(item)
                for item in blockers
                if "confirmation" in str(item) or "clean_holdout" in str(item)
            ],
        ),
    }
    layers["ledger_pnl"] = _layer(
        pnl.get("status") == "pass" and pnl.get("price_series_nav_substitution_used") is False,
        False,
        [] if pnl.get("status") == "pass" else ["ledger_pnl_missing"],
    )
    return layers


def _layer(engineering: bool, promotion: bool, blockers: Sequence[str]) -> dict[str, Any]:
    return {
        "engineering_status": "pass" if engineering else "blocked",
        "engineering_passed": bool(engineering),
        "promotion_status": "pass" if promotion else "blocked",
        "promotion_passed": bool(promotion),
        "promotion_credit_allowed": False,
        "blockers": _dedupe(str(item) for item in blockers),
    }


def _write_immutable_run(
    *,
    root: Path,
    artifact_root: Path,
    generated_at: str,
    analysis: Mapping[str, Any],
) -> CandidatePortfolioRunResult:
    run_id = str(analysis["run_id"])
    run_dir = artifact_root / "runs" / run_id
    latest_pointer = artifact_root / "latest_pointer.json"
    report = dict(_mapping(analysis["report"]))
    report["artifacts"] = {
        "run_dir": _relpath(run_dir, root),
        "latest_pointer": _relpath(latest_pointer, root),
        "immutable": True,
        "files": list(ARTIFACT_FILES),
    }
    payloads: dict[str, bytes] = {
        "portfolio_construction.json": _json_bytes(analysis["portfolio_construction"]),
        "risk_decisions.jsonl": _jsonl_bytes(analysis["risk_decisions"]),
        "portfolio_event_ledger.jsonl": _jsonl_bytes(analysis["portfolio_event_ledger"]),
        "ledger_pnl.json": _json_bytes(analysis["ledger_pnl"]),
        "reconciliation.json": _json_bytes(analysis["reconciliation"]),
        "cost_stress.json": _json_bytes(analysis["cost_stress"]),
        "sector_style_exposure.json": _json_bytes(analysis["sector_style_exposure"]),
        "liquidity_capacity.json": _json_bytes(analysis["liquidity_capacity"]),
        "walk_forward.json": _json_bytes(analysis["walk_forward"]),
        "promotion_evidence.json": _json_bytes(analysis["promotion_evidence"]),
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
        "canonical_run_id": report["canonical_dependency"]["run_id"],
        "data_version": report["data"]["data_version"],
        "params_hash": report["candidate"]["params_hash"],
        "cost_model_hash": report["hashes"]["cost_model_hash"],
        "inputs": dict(analysis["run_inputs"]),
        "files": file_hashes,
        "guardrails": dict(report["guardrails"]),
    }
    manifest_bytes = _json_bytes(manifest)
    all_payloads = {**payloads, "manifest.json": manifest_bytes}
    if run_dir.exists():
        for name, expected in all_payloads.items():
            path = run_dir / name
            if not path.is_file() or path.read_bytes() != expected:
                raise ValueError(f"goal4_immutable_run_conflict:{name}")
    else:
        run_dir.mkdir(parents=True, exist_ok=False)
        for name, content in all_payloads.items():
            (run_dir / name).write_bytes(content)
    manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
    pointer = {
        "schema_version": "us_etf_26_candidate_portfolio_latest_pointer_v1",
        "run_id": run_id,
        "run_dir": _relpath(run_dir, root),
        "manifest": _relpath(run_dir / "manifest.json", root),
        "manifest_sha256": manifest_sha256,
        "report": _relpath(run_dir / "report.json", root),
        "report_sha256": file_hashes["report.json"]["sha256"],
        "code_commit": report["code_commit"],
        "status": report["status"],
        "promotion_credit_allowed": False,
        "promotion_unlock_allowed": False,
        "paper_or_live_unlock_allowed": False,
    }
    artifact_root.mkdir(parents=True, exist_ok=True)
    _atomic_write(latest_pointer, _json_bytes(pointer))
    return CandidatePortfolioRunResult(
        run_id=run_id,
        run_dir=run_dir,
        latest_pointer=latest_pointer,
        report=report,
        manifest=manifest,
        manifest_sha256=manifest_sha256,
    )


def _markdown(report: Mapping[str, Any]) -> str:
    recon = _mapping(report["ledger_reconciliation"])
    liquidity = _mapping(report["liquidity_capacity"])
    lines = [
        "# US ETF26 Candidate Portfolio and Promotion Evidence",
        "",
        f"- Run: `{report['run_id']}`",
        f"- Candidate: `{report['candidate']['candidate_id']}`",
        f"- Canonical run: `{report['canonical_dependency']['run_id']}`",
        f"- Status: `{report['status']}`",
        f"- Decision: `{report['decision']}`",
        f"- Code commit: `{report['code_commit']}`",
        f"- Data version: `{report['data']['data_version']}`",
        f"- Portfolio event ledger rows: `{report['counts']['portfolio_event_ledger_count']}`",
        f"- Ledger cash delta: `{recon['cash_delta']}`",
        f"- Ledger quantity delta: `{recon['quantity_delta']}`",
        f"- Ledger equity delta: `{recon['equity_delta']}`",
        f"- Fills below minimum notional: `{liquidity['fills_below_minimum_order_notional']}`",
        "- Promotion credit allowed: `false`",
        "- Paper/live unlock allowed: `false`",
        "",
        "## Blockers",
        "",
    ]
    lines.extend(f"- `{blocker}`" for blocker in report["blockers"])
    return "\n".join(lines) + "\n"


def _resolve_repo_path(root: Path, path: Path) -> Path:
    resolved = path.resolve() if path.is_absolute() else (root / path).resolve()
    _require_within(root, resolved, "goal4_repo_path_escape")
    return resolved


def _require_within(root: Path, path: Path, error_code: str) -> None:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(error_code) from exc


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"goal4_json_not_object:{path.name}")
    return payload


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"goal4_jsonl_not_object:{path.name}:{number}")
        rows.append(value)
    return rows


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, default=_json_default) + "\n"
    ).encode("utf-8")


def _jsonl_bytes(rows: Iterable[Mapping[str, Any]]) -> bytes:
    return b"".join(
        (
            json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=_json_default)
            + "\n"
        ).encode("utf-8")
        for row in rows
    )


def _json_default(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if hasattr(value, "item"):
        return value.item()
    raise TypeError(f"not JSON serializable: {type(value).__name__}")


def _stable_hash(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=_json_default,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _stable_id(prefix: str, *parts: object) -> str:
    payload = "|".join(str(part) for part in parts).encode("utf-8")
    return f"{prefix}_{hashlib.sha256(payload).hexdigest()[:20]}"


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
