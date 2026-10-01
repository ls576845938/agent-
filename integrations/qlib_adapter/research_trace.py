"""Market-neutral trace envelope with existing domain pure functions for sizing/risk.

This is an offline research replay, never the runtime OMS or authoritative ledger.
"""
from __future__ import annotations

from datetime import timedelta
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from .candidate_policy import (
    CandidateExitObservation,
    CandidateExitPolicy,
    CandidateExitState,
    CandidatePolicyFacts,
    CandidatePolicyVersions,
    POLICY_VERSION,
    evaluate_candidate_policy,
    policy_binding_digest,
)
from .schemas import QlibAdapterError, build_run_paths, load_yaml_file, read_json, to_jsonable, utc_now_iso, write_json

LAYERS = ("alpha", "regime", "risk", "allocation", "position", "exit", "execution")
TRUTH_KINDS = {"alpha":"research_derived", "regime":"research_derived_diagnostic",
    **{name:"research_simulated" for name in LAYERS[2:]}}


def digest(value) -> str:
    return hashlib.sha256(json.dumps(to_jsonable(value), sort_keys=True, allow_nan=False).encode()).hexdigest()


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("x", encoding="utf-8") as target:
        for row in rows:
            target.write(json.dumps(to_jsonable(row), sort_keys=True, allow_nan=False) + "\n")


def _preserve_safe_pending_exit(pending, current_quantity, target_quantity, reason):
    """Keep an earlier equally strong reduction; repeated exits cannot reset its deadline."""
    for timestamp, orders in list(pending.items()):
        retained = []
        for order in orders:
            previous_target = order["target_quantity"]
            if (order["position_before"] == current_quantity and current_quantity != 0
                    and current_quantity * previous_target >= 0
                    and abs(previous_target) <= abs(target_quantity) < abs(current_quantity)):
                retained.append(order)
            else:
                order["record"]["layers"]["execution"].update({"status":"blocked","blockers":[reason]})
        if retained:
            pending[timestamp] = retained
        else:
            del pending[timestamp]


def reconcile_research_ledger(rows: list[dict], initial_equity: float) -> dict:
    """Independent replay from signed fills and funding; not from reported return."""
    cash, quantity, average = float(initial_equity), 0.0, 0.0
    maximum_error = 0.0
    for row in rows:
        if row["kind"] == "funding":
            expected = -quantity * row["valuation_mark"] * row["rate"]
            maximum_error = max(maximum_error, abs(expected - row["cash_delta"]))
            cash += expected
        elif row["kind"] == "fill":
            delta, price = row["quantity_delta"], row["price"]
            before = quantity
            if before * delta < 0:
                closed = min(abs(before), abs(delta))
                cash += closed * (price - average) * np.sign(before)
            quantity += delta
            if abs(quantity) < 1e-12:
                quantity, average = 0.0, 0.0
            elif before == 0 or before * quantity < 0:
                average = price
            elif before * delta > 0:
                average = (abs(before) * average + abs(delta) * price) / abs(quantity)
            cash -= abs(delta) * price * row["fee_rate"]
        equity = cash + quantity * (row["mark"] - average)
        maximum_error = max(maximum_error, abs(cash - row["cash_after"]),
            abs(quantity - row["position_after"]), abs(equity - row["equity_after"]))
    return {"status": "passed" if maximum_error < 1e-7 else "blocked", "maximum_absolute_error": float(maximum_error),
        "cash": float(cash), "position": float(quantity), "events_checked": len(rows)}


def build_research_trace(*, run_id: str, artifacts_root: str | Path) -> dict:
    from quant_crypto.portfolio.forecast import (BTCForecast, BTCForecastQuality, BTCRiskBudget,
        BTCRiskState)
    from quant_crypto.portfolio.order_intent import BTCExecutionCostEstimate
    from quant_crypto.risk import RiskConstitution, evaluate_combined_loss
    from quant_crypto.risk.liquidation import BTCReferencePriceState
    from quant_crypto.trading_contracts import SignalDirection

    paths = build_run_paths(run_id, artifacts_root)
    root = paths.run_root
    config = load_yaml_file(root / "qlib_workflow_config.yaml")
    simulation = config["research_simulation"]
    if simulation["engine"] != "btc_risk_budget":
        raise QlibAdapterError("No domain research sizing engine registered for this profile.")
    meta = read_json(root / "qlib_run_metadata.json")
    candidate = read_json(root / "qlib_strategy_manifest.json")
    if not (candidate.get("run_id") == run_id
            and candidate.get("candidate_id") == candidate.get("manifest_id") and candidate.get("candidate_id")
            and candidate.get("strategy_id") == candidate.get("strategy_version") == config["model"]["strategy_version"]
            and candidate.get("model_id") == config["model"]["name"]):
        raise QlibAdapterError("Research candidate identity mismatch.")
    manifest = read_json(paths.qlib_input_dir / "dataset_manifest.json")
    evaluation = read_json(root / "signal_evaluation.json")
    evaluation_hash = hashlib.sha256((root / "signal_evaluation.json").read_bytes()).hexdigest()
    calibration = evaluation["calibration"]
    for key, sha in manifest["file_hashes"].items():
        path = Path(manifest["files"][key]).resolve()
        if not path.is_relative_to(paths.qlib_input_dir.resolve()) or hashlib.sha256(path.read_bytes()).hexdigest() != sha:
            raise QlibAdapterError("Research input hash mismatch.")
    bars = pd.read_parquet(manifest["files"]["daily_bars_parquet"]).set_index("event_time")
    mark = pd.read_parquet(manifest["files"]["mark"]).set_index("event_time")
    premium = pd.read_parquet(manifest["files"]["premium"]).set_index("event_time")
    funding = pd.read_parquet(manifest["files"]["funding"]).set_index("event_time")
    scores = pd.read_parquet(root / "research_model_scores.parquet").set_index("datetime")
    if not scores.run_id.eq(run_id).all() or scores.index.duplicated().any():
        raise QlibAdapterError("Score identity mismatch.")
    first, last = scores.index.min(), scores.index.max()
    delay = int(config["evaluation"]["entry_delay_bars"])
    end = last + pd.Timedelta(hours=delay)
    if first < funding.index.min() or end > funding.index.max() + pd.Timedelta(hours=8):
        raise QlibAdapterError("OOS cost window exceeds verified funding coverage; missing funding is unknown.")
    if pd.Timestamp(calibration["fit_end"], tz="UTC") + pd.Timedelta(hours=14) >= first:
        raise QlibAdapterError("Calibration is not strictly prior to the test decisions.")
    initial = float(simulation["initial_equity"])
    cash, quantity, average, peak_equity = initial, 0.0, 0.0, initial
    realized, funding_total, fees_total = 0.0, 0.0, 0.0
    fee_rate = float(simulation["fee_bps"]) / 10000
    spread_bps, impact_bps = float(simulation["spread_bps"]), float(simulation["impact_bps"])
    friction = (float(simulation["slippage_bps"]) + spread_bps / 2 + impact_bps) / 10000
    ledger, decisions, pending, equity_curve = [], [], {}, []
    holding_bars, favorable = 0, None
    current_day, day_start_equity = None, initial
    symbol = manifest["symbols_exported"][0]
    calibration_hash = digest(calibration)
    identity = {"qlib_run_id": run_id, "profile_id": config["profile"], "experiment_id": run_id,
        "recorder_id": read_json(root / "recorder_metrics.json").get("id"), "model_id": config["model"]["name"],
        "strategy_id": candidate["strategy_id"], "candidate_id": candidate["candidate_id"],
        "manifest_id": candidate["manifest_id"], "strategy_version": candidate["strategy_version"], "params_sha256": digest(config),
        "asset_class": "crypto", "venue": "okx", "instrument": symbol, "bar_size": "1h",
        "data_version": manifest["input_contract"]["data_version_request"],
        "aggregate_sha256": manifest["input_contract"].get("aggregate_sha256"),
        "dataset_manifest_sha256": hashlib.sha256((paths.qlib_input_dir / "dataset_manifest.json").read_bytes()).hexdigest(),
        "config_sha256": meta["config_sha256"], "source_head": meta["code_version"], "code_version": meta["code_version"]}
    policy_bindings = {
        "position": {
            "engine": simulation["engine"],
            "risk_budget_fraction": simulation["risk_budget_fraction"],
            "max_weight": simulation["max_weight"],
            "volatility_target_annual_configured": simulation["volatility_target_annual"],
            "volatility_target_applied": False,
        },
        "exit": {
            "hard_stop_fraction": simulation["hard_stop_fraction"],
            "trailing_stop_fraction": simulation["trailing_stop_fraction"],
            "maximum_holding_bars": simulation["maximum_holding_bars"],
        },
        "cost": {
            "fee_bps_per_side": candidate["cost_model"]["fee_bps_per_side"],
            "funding": candidate["cost_model"]["funding"],
            "slippage_bps_per_side": candidate["slippage_model"]["bps_per_side"],
            "spread_bps_per_side": simulation["spread_bps"],
            "impact_bps_per_side": simulation["impact_bps"],
            "fill": candidate["slippage_model"]["fill"],
            "execution_delay_bars": candidate["slippage_model"]["execution_delay_bars"],
        },
    }
    policy_versions = CandidatePolicyVersions(
        policy_version=POLICY_VERSION,
        position_policy_sha256=policy_binding_digest(policy_bindings["position"]),
        exit_policy_sha256=policy_binding_digest(policy_bindings["exit"]),
        cost_policy_sha256=policy_binding_digest(policy_bindings["cost"]),
    )
    def book(kind, timestamp, valuation, **details):
        ledger.append({"ledger_id": digest([run_id, len(ledger)]), "kind": kind, "timestamp": timestamp.isoformat(),
            "truth_kind": "research_simulated", "cash_after": cash, "position_after": quantity,
            "mark": valuation, "equity_after": cash + quantity * (valuation - average), **details})
    def protection(q, price):
        return None if abs(q) < 1e-12 else {"present": True, "quantity": abs(q), "side": "sell" if q > 0 else "buy",
            "trigger_price": price * (1 - np.sign(q) * float(simulation["hard_stop_fraction"]))}
    for timestamp, bar in bars.loc[first:end].iterrows():
        if current_day != timestamp.date():
            current_day = timestamp.date()
            prior = float(mark.loc[timestamp-pd.Timedelta(hours=1), "close"])
            day_start_equity = cash + quantity * (prior-average)
        # Funding settles on the position held BEFORE a same-timestamp simulated fill.
        if timestamp in funding.index:
            prior_mark = float(mark.loc[timestamp - pd.Timedelta(hours=1), "close"])
            rate = float(funding.loc[timestamp, "fundingRate"])
            cash_delta = -quantity * prior_mark * rate
            cash += cash_delta
            funding_total += cash_delta
            book("funding", timestamp, prior_mark, rate=rate, valuation_mark=prior_mark,
                cash_delta=cash_delta, valuation_source="prior_available_mark_proxy_not_exchange_fee_receipt")
        for order in pending.pop(timestamp, []):
            if abs(quantity-order["position_before"]) > 1e-10:
                order["record"]["layers"]["execution"].update({"status":"blocked","blockers":["position_changed_before_simulated_fill"]})
                continue
            delta = order["target_quantity"] - quantity
            if abs(delta) < 1e-10:
                continue
            price = float(bar.open) * (1 + np.sign(delta) * friction)
            before = quantity
            closed = min(abs(before), abs(delta)) if before * delta < 0 else 0.0
            gain = closed * (price - average) * np.sign(before)
            realized += gain
            cash += gain
            quantity += delta
            if abs(quantity) < 1e-12:
                quantity, average, favorable, holding_bars = 0.0, 0.0, None, 0
            elif before == 0:
                average, favorable, holding_bars = price, price, 0
            elif before * delta > 0:
                average = (abs(before) * average + abs(delta) * price) / abs(quantity)
            fee = abs(delta) * price * fee_rate
            cash -= fee
            fees_total += fee
            fill_id = digest([order["decision_id"], "fill"])
            # Mark at execution OPEN is the prior completed mark, not this hour's future close.
            valuation = float(mark.loc[timestamp - pd.Timedelta(hours=1), "close"])
            book("fill", timestamp, valuation, fill_id=fill_id, decision_id=order["decision_id"],
                quantity_delta=delta, price=price, fee_rate=fee_rate, fee=fee, realized_pnl=gain)
            order["record"]["layers"]["execution"].update({"status": "passed", "fill_id": fill_id,
                "fill_time": timestamp.isoformat(), "fill_price": price, "quantity_delta": delta,
                "ledger_id": ledger[-1]["ledger_id"], "fee": fee})
        current_mark = float(mark.loc[timestamp, "close"])
        equity = cash + quantity * (current_mark - average)
        peak_equity = max(peak_equity, equity)
        drawdown = 1 - equity / peak_equity
        equity_curve.append({"time": (timestamp + pd.Timedelta(hours=1)).isoformat(), "equity": equity, "weight": quantity * current_mark / equity})
        if timestamp not in scores.index:
            continue
        decision_time = timestamp + pd.Timedelta(hours=1)
        decision_id = digest([run_id, symbol, decision_time.isoformat()])
        raw_score = float(scores.loc[timestamp, "score"])
        calibrated = float(np.clip(calibration["intercept"] + calibration["slope"] * raw_score, -0.05, 0.05))
        history = bars.loc[:timestamp, "close"]
        momentum = float(history.iloc[-1] / history.iloc[-25] - 1)
        volatility = float(history.pct_change().tail(72).std() * np.sqrt(8760))
        regime = "uptrend" if momentum > 0.005 else "downtrend" if momentum < -0.005 else "range"
        funding_known = funding[funding.available_time <= decision_time]
        known_rate = float(funding_known.iloc[-1].fundingRate) if not funding_known.empty else None
        blockers = [] if calibration["quality_passed"] else ["validation_calibration_quality_failed"]
        expected_bps = calibrated * 10000
        direction = SignalDirection.LONG if calibrated > 0 else SignalDirection.SHORT
        quality = calibration["quality"]
        forecast = BTCForecast(timestamp_utc=decision_time.to_pydatetime(), strategy_id=identity["strategy_id"],
            symbol=symbol, direction=direction, score=min(1.0, abs(calibrated) / 0.01), horizon="12h", unit="bps",
            expected_return_bps=expected_bps, confidence=max(0.0, min(1.0, float(quality["direction_hit_rate"]))),
            expiry_utc=(decision_time + timedelta(hours=12)).to_pydatetime(), source_signal_id=decision_id + ":signal",
            quality=BTCForecastQuality(ic=quality["time_series_ic"], hit_rate=quality["direction_hit_rate"],
                sample_size=quality["sample_size"], evidence_path="signal_evaluation.json", evidence_hash=evaluation_hash),
            forecast_id=decision_id + ":forecast", metadata={"qlib_run_id": run_id, "research_only": True})
        constitution = RiskConstitution(max_abs_position=initial/current_mark, max_quantity=initial/current_mark,
            max_notional=initial * float(simulation["max_weight"]), max_leverage=1.0,
            min_liquidation_buffer_bps=1000, max_daily_loss=initial*0.03, max_drawdown=0.12,
            max_combined_loss=initial*0.12, protection_required=True)
        loss = evaluate_combined_loss(realized, quantity*(current_mark-average), funding_total, fees_total, 0, 0,
            account_equity=equity, constitution=constitution, daily_loss=max(0,day_start_equity-equity), drawdown=drawdown)
        cost = BTCExecutionCostEstimate(fee_bps=2*simulation["fee_bps"], spread_bps=spread_bps,
            slippage_bps=2*simulation["slippage_bps"], impact_bps=2*impact_bps,
            funding_bps=None if known_rate is None else abs(known_rate)*10000*2, source="frozen_research_cost_assumption")
        policy = evaluate_candidate_policy(CandidatePolicyFacts(
            decision_id=decision_id, forecast=forecast,
            expected_source_signal_id=decision_id + ":signal",
            risk_budget=BTCRiskBudget(max_btc_exposure=float(simulation["max_weight"]),
                strategy_risk_budget=float(simulation["max_weight"]), target_volatility=float(simulation["volatility_target_annual"]),
                current_weight=quantity * current_mark / equity, min_cash_fraction=0.75, max_turnover=0.25,
                max_daily_loss_pct=0.03, max_drawdown_pct=0.12,
                max_abs_funding_rate=0.001 if simulation["funding_filter_enabled"] else 1.0,
                require_funding_rate=True),
            risk_state=BTCRiskState(cash_fraction=1 - abs(quantity * current_mark / equity), daily_loss_pct=max(0, 1-equity/day_start_equity),
                current_drawdown_pct=drawdown, funding_rate=known_rate, data_anomaly=bool(blockers)),
            account_equity=equity, mark_price=current_mark, current_quantity=quantity,
            reference_prices=lambda proposed: BTCReferencePriceState(
                observed_at_utc=decision_time.to_pydatetime(), signal_price=float(bar.close),
                execution_price=float(bar.close) * (1 + np.sign(float(proposed.target_quantity or 0.0) - quantity) * friction),
                mark_price=current_mark, index_price=float(premium.loc[timestamp, "index_close"]), current_mark_price=current_mark,
                primary_mid=float(bar.close), spread_bps=spread_bps, data_age_ms=0,
                source="okx_historical_mark_index_plus_research_cost_assumption"),
            constitution=constitution, combined_loss=loss,
            protection_before=protection(quantity,current_mark),
            protection_after=lambda proposed: protection(proposed,current_mark),
            cost_estimate=cost, min_quantity=0.00001, blockers=tuple(blockers),
            exit_state=CandidateExitState(quantity=quantity, average_price=average,
                favorable_price=favorable, holding_bars=holding_bars),
            exit_observation=CandidateExitObservation(close_price=float(bar.close),
                calibrated_prediction=calibrated, has_score=True,
                end_of_window=timestamp == last),
            exit_policy=CandidateExitPolicy(
                hard_stop_fraction=float(simulation["hard_stop_fraction"]),
                trailing_stop_fraction=float(simulation["trailing_stop_fraction"]),
                maximum_holding_bars=int(simulation["maximum_holding_bars"])),
            versions=policy_versions))
        holding_bars = policy.exit_state.holding_bars
        favorable = policy.exit_state.favorable_price
        target, assessment, portfolio = policy.target, policy.assessment, policy.portfolio
        prices = policy.reference_prices
        reduction, cost_decision = policy.reduction_plan, policy.cost_decision
        reduce_only, approved, reasons = reduction is not None, policy.approved, list(policy.reasons)
        exit_reasons = list(policy.exit_reasons)
        if policy.exit_reasons:
            _preserve_safe_pending_exit(pending, quantity, 0.0, "research_exit_superseded_pending_intent")
        if reduce_only:
            exit_reasons.append("research_reduce_only_plan")
            _preserve_safe_pending_exit(pending, quantity, target.target_quantity, "research_reduction_superseded_pending_intent")
        carried_pending_decision_id = None
        if pending:
            approved = False
            reasons.append("research_order_pending")
            carried_pending_decision_id = next(iter(pending.values()))[0]["decision_id"]
        record = {"decision_id": decision_id, "decision_time": decision_time.isoformat(), **identity,
            "runtime_run_id": None, "execution_binding_status": "not_bound_research_only",
            "execution_permission": False, "runtime_observed": False,
            "layers": {name: {"status": "passed", "truth_kind": TRUTH_KINDS[name],
                "record_id": decision_id + ":" + name,
                "evidence_refs": ["research_decisions.jsonl"], "identity_match": True} for name in LAYERS}}
        for index, name in enumerate(LAYERS):
            record["layers"][name]["parent_record_id"] = None if index == 0 else decision_id + ":" + LAYERS[index-1]
        record["layers"]["alpha"].update({"raw_score": raw_score, "expected_return_bps": expected_bps,
            "signal_id": forecast.source_signal_id,
            "forecast_id": forecast.forecast_id, "calibration_hash": calibration_hash,
            "quality_evidence_path": "signal_evaluation.json", "quality_evidence_sha256": evaluation_hash,
            "status": "blocked" if blockers else "passed", "blockers": blockers})
        record["layers"]["regime"].update({"regime": regime, "momentum_24h": momentum, "volatility_annual": volatility,
            "regime_usage": "diagnostic_only_not_position_filter",
            "funding_filter": "not_configured", "oi_filter": "not_configured", "oi_observation": "unknown"})
        record["layers"]["risk"].update({"status": "passed" if assessment.approved and not blockers else "blocked",
            "assessment": assessment.to_dict(), "blockers": blockers + list(assessment.blockers),
            "research_reduction_plan": reduction.to_dict() if reduce_only else None,
            "risk_truth_kind": "research_assumption_simulated_reference_prices",
            "actual_margin": None, "actual_liquidation_price": None, "actual_account_state": None,
            "reference_prices": prices.to_dict(), "protection_truth_kind": "configured_research_close_stop_not_exchange_order"})
        record["layers"]["allocation"].update({"method": "confidence_weighted_single_asset_risk_budget",
            "sizing_scope": "unlevered_exposure_proposal", "production_perpetual_sizing_ready": False,
            "target_weight": target.target_weight, "target_quantity": target.target_quantity,
            "target_position_id": target.target_position_id, "volatility_target_applied": False,
            "status": "passed" if approved else "blocked", "blockers": [] if approved else reasons,
            "reason_codes": list(portfolio.reason_codes)})
        record["layers"]["position"].update({"quantity_before": quantity, "average_entry": average,
            "mark_price": current_mark, "cash": cash, "equity": equity, "drawdown": drawdown})
        record["layers"]["exit"].update({"triggered": bool(exit_reasons), "reasons": exit_reasons,
            "holding_bars": holding_bars, "fill_policy": "delayed_open_not_intrabar_guaranteed_stop"})
        record["layers"]["execution"].update({"status": "not_run", "scope": "research_simulation",
            "carried_pending_decision_id": carried_pending_decision_id,
            "research_reduce_only": reduce_only,
            "simulated_order_id": decision_id + ":intent" if approved else None,
            "cost_gate": cost_decision.metadata, "blockers": [] if approved else reasons,
            "runtime_status": "unknown", "real_order_id": None, "real_fill_id": None, "real_ledger_hash": None})
        if approved:
            execution_time = timestamp + pd.Timedelta(hours=delay)
            pending.setdefault(execution_time, []).append({"target_quantity": target.target_quantity,
                "position_before": quantity, "decision_id": decision_id, "record": record})
        decisions.append(record)
    reconciliation = reconcile_research_ledger(ledger, initial)
    if reconciliation["status"] != "passed":
        raise QlibAdapterError(f"Research ledger reconciliation failed: {reconciliation}")
    _write_jsonl(root / "research_decisions.jsonl", decisions)
    _write_jsonl(root / "research_ledger.jsonl", ledger)
    fills = sum(row["kind"] == "fill" for row in ledger)
    completion_blockers = ([] if calibration["quality_passed"] else ["validation_calibration_quality_failed"])
    completion_blockers += [] if fills else ["no_simulated_fills"]
    completion_blockers += [] if abs(quantity) < 1e-12 else ["final_research_position_not_flat"]
    completion_blockers += [] if not pending else ["pending_research_intents_at_end"]
    if decisions and decisions[-1]["layers"]["position"]["quantity_before"] != 0:
        terminal = decisions[-1]["layers"]["execution"]
        carried = next((row["layers"]["execution"] for row in decisions
            if row["decision_id"] == terminal.get("carried_pending_decision_id")), {})
        if terminal["status"] != "passed" and carried.get("status") != "passed":
            completion_blockers.append("terminal_research_exit_unfilled")
    summary = {"schema_version": "qlib_research_trace_v1", "identity": identity, "created_at": utc_now_iso(),
        "as_of": (end+pd.Timedelta(hours=1)).isoformat(), "status": "research_flow_blocked" if completion_blockers else "research_flow_completed",
        "blockers": completion_blockers, "final_position": quantity, "pending_intent_count": sum(map(len,pending.values())),
        "decision_count": len(decisions), "simulated_fill_count": fills, "reconciliation": reconciliation,
        "research_metrics": {"initial_equity": initial, "final_equity": equity_curve[-1]["equity"],
            "net_return": equity_curve[-1]["equity"]/initial-1, "realized_pnl": realized,
            "funding_cashflow": funding_total, "fees": fees_total},
        "equity_curve": equity_curve[::12] + equity_curve[-1:], "calibration": calibration,
        "configured_research_risk": simulation, "runtime_run_id": None,
        "execution_binding_status": "not_bound_research_only", "execution_permission": False, "runtime_observed": False,
        "limitations": ["historical_research_not_live", "spread_impact_slippage_are_assumptions",
            "funding_valuation_uses_prior_available_mark_proxy", "close_based_delayed_exit_not_exchange_stop",
            "historical_arrival_times_reconstructed", "no_oi_or_depth_evidence", "no_volatility_targeting",
            "single_holdout_not_walk_forward_or_promotion_evidence"]}
    write_json(root / "research_trace.json", summary)
    return summary
