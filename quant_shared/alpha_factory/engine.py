"""Shared campaign use case. Persistence, market access and trainers are injected."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .contracts import (FactoryError, SAFETY, digest, REAL_ACCEPTANCE_PROFILE,
    REAL_ACCEPTANCE_PRIMITIVES)
from .evaluation import (split_plan, segment, forward_labels, evaluate_expression, signal_metrics,
    nomination_gate, purged_selection_folds, hac_p_value, by_fdr, effective_temporal_samples)
from .search import search_factors


def run_campaign(*, panel, profile, request, primitives, primitive_catalog, seed_specs, crossover,
    model_catalog, trainer, emit):
    acceptance = request.get("acceptance_profile") == REAL_ACCEPTANCE_PROFILE
    cost_scenarios = {"base": 24, "conservative": 36, "stress": 48} if acceptance else profile["cost_scenarios_bps"]
    if acceptance:
        missing = [name for name in REAL_ACCEPTANCE_PRIMITIVES if name not in primitives]
        if missing:
            raise FactoryError("acceptance_primitive_missing:" + ",".join(missing))
        primitives = primitives.loc[:, list(REAL_ACCEPTANCE_PRIMITIVES)]
        seed_specs = [spec for spec in seed_specs if spec.name in REAL_ACCEPTANCE_PRIMITIVES]
        model_catalog = tuple(model for model in model_catalog if model.get("model_id") == "lgbm_small")
        if len(model_catalog) != 1:
            raise FactoryError("acceptance_model_catalog_invalid")
    plan = split_plan(panel.index, horizon=profile["label_horizon"], delay=profile["entry_delay"])
    if acceptance:
        _validate_real_acceptance_offline_window(panel.index, plan)
    labels = forward_labels(panel, plan)
    train_primitives = segment(primitives, plan, "train")
    unavailable = {name: "insufficient_train_availability" for name in train_primitives
        if train_primitives[name].notna().mean() < .80}
    available = [name for name in primitives if name not in unavailable]
    if not available: raise FactoryError("no_available_train_primitives")
    primitives = primitives[available]
    seed_specs = [spec for spec in seed_specs if all(name not in unavailable for name in _primitives(spec.expression))]
    emit("generate", "running", {"split_plan": plan, "primitive_catalog": primitive_catalog,
        "unavailable_primitives": unavailable, "profile_hash": profile["profile_hash"]})
    search = search_factors(segment(primitives, plan, "train"), segment(labels, plan, "train"),
        seed_specs, request, mode=profile["metric_mode"], crossover=crossover,
        on_trial=lambda row: emit("generate", "trial", row))
    selected_specs = search.pop("specs")
    emit("generate", "completed", search)
    emit("evaluate", "completed", {"selected_factor_ids": [s.factor_id for s in selected_specs],
        "selection_rejections": search["selection_rejections"], "correlation_fit_scope": "train_only"})
    base = {"schema_version": "alpha_factory_result_v1", "profile": profile, "request": request,
        "split_plan": plan, "factor_search": search, "primitive_catalog": primitive_catalog,
        "unavailable_primitives": unavailable, "factor_specs": [spec.to_dict() for spec in selected_specs],
        "model_trials": [], "candidates": [], "status": "completed", **SAFETY}
    if not selected_specs:
        return {**base, "decision": "blocked", "blockers": ["no_selected_factors"]}
    features = pd.DataFrame({spec.factor_id: evaluate_expression(spec.expression, primitives) for spec in selected_specs})
    features = features.replace([np.inf, -np.inf], np.nan)
    # A real truncation-invariance check on this exact frame, not just a test flag.
    cutoff = pd.Timestamp(plan["segments"]["selection"][1])
    prefix = primitives.loc[primitives.index.get_level_values("datetime") <= cutoff]
    for spec in selected_specs:
        expected = evaluate_expression(spec.expression, prefix)
        pd.testing.assert_series_equal(features.loc[expected.index, spec.factor_id], expected, check_names=False)
    emit("train", "running", {"feature_ids": list(features), "feature_spec_hash": digest(base["factor_specs"]),
        "truncation_invariance": "passed", "model_trials_requested": request["model_trials"]})
    folds = purged_selection_folds(panel.index, plan)
    if acceptance and len(folds) != 4:
        raise FactoryError("acceptance_selection_fold_count_invalid")
    predictions = {}
    for number, model in enumerate(model_catalog[:request["model_trials"]], 1):
        row = {"trial_number": number, "model_id": model["model_id"], "model_spec": model,
            "status": "running", "folds": [], "fit_used_audit": False, "qlib_runs": []}
        emit("train", "trial_started", row)
        pieces = []
        try:
            for fold_id, windows in enumerate(folds, 1):
                pred, reference = trainer(features=features, labels=labels, segments=windows, plan=plan,
                    model_spec=model, trial_number=number, phase=f"fold{fold_id}")
                metric = signal_metrics(pred, labels.reindex(pred.index), profile["metric_mode"])
                row["folds"].append({"fold_id": fold_id, "segments": windows, "metrics": metric})
                row["qlib_runs"].append(reference); pieces.append(pred)
                emit("train", "fold_completed", {"trial_number": number, "fold_id": fold_id, "reference": reference})
            prediction = pd.concat(pieces).sort_index()
            metrics = signal_metrics(prediction, labels.reindex(prediction.index), profile["metric_mode"])
            row.update(status="completed", selection_metrics=metrics, p_value=hac_p_value(metrics))
            row["consistent_folds"] = sum((fold["metrics"].get("rank_ic") or 0) > 0 for fold in row["folds"])
            row["effective_samples"] = effective_temporal_samples(prediction.index, plan)
            row["effective_sample_semantics"] = "distinct_decision_times_divided_by_horizon_plus_delay_conservative_proxy"
            row["cost_diagnostics"] = {scenario: {"mean_abs_forecast_bps": float(prediction.abs().mean() * 10000),
                "assumed_round_trip_bps": cost, "forecast_net_edge_bps": float(prediction.abs().mean() * 10000 - cost),
                "semantics": "forecast_edge_proxy_not_fill_pnl"} for scenario, cost in cost_scenarios.items()}
            predictions[number] = prediction
        except Exception as exc:
            row.update(status="failed", error=str(exc), p_value=None)
        base["model_trials"].append(row)
        emit("train", "trial_completed", row)
    emit("train", "completed", {"model_trials": base["model_trials"]})
    adjusted = by_fdr([row.get("p_value") for row in base["model_trials"]])
    for row, qvalue in zip(base["model_trials"], adjusted):
        row["fdr_adjusted_p"] = qvalue
        row["screen_blockers"] = []
        if row["status"] != "completed": row["screen_blockers"].append("training_failed")
        if qvalue is None or qvalue > .10: row["screen_blockers"].append("BY_FDR_not_passed")
        if row.get("consistent_folds", 0) < 3: row["screen_blockers"].append("fewer_than_three_consistent_folds")
        if row.get("effective_samples", 0) < 30: row["screen_blockers"].append("insufficient_effective_samples")
        for scenario in ("base", "conservative"):
            if row.get("cost_diagnostics", {}).get(scenario, {}).get("forecast_net_edge_bps", -1) <= 0:
                row["screen_blockers"].append(scenario + ":forecast_does_not_cover_assumed_cost")
    eligible = [row for row in base["model_trials"] if not row["screen_blockers"]]
    base.update(statistical_trial_count=search["unique_expression_count"] + len(base["model_trials"]),
        qlib_fit_count=sum(len(row["qlib_runs"]) for row in base["model_trials"]),
        dsr=None, pbo=None, returns_evidence="not_run_signal_factory_not_trading_backtest")
    if not eligible:
        # A rejected search must not consume the final audit window, including
        # when a future independent authority binds an unseen confirmation set.
        detail = {"decision": "rejected", "audit_status": "not_run_selection_failed",
            "blockers": ["no_model_passed_selection_gate", "audit_not_opened_no_eligible_model"]}
        emit("screen", "completed", {**detail, "model_trials": base["model_trials"]})
        emit("nominate", "completed", detail)
        return {**base, **detail}
    # Freeze a single champion BEFORE touching audit; no selecting a replacement
    # after observing its test result.
    completed = [row for row in base["model_trials"] if row["status"] == "completed"]
    ranked = sorted(eligible, key=lambda row: (-(row["selection_metrics"].get("rank_ic") or -1), row["trial_number"]))
    champion = ranked[0]
    for row in completed:
        if row["trial_number"] != champion["trial_number"]:
            correlation = predictions[row["trial_number"]].corr(predictions[champion["trial_number"]])
            row["prediction_correlation_to_champion"] = float(correlation) if np.isfinite(correlation) else None
            row["selection_decision"] = "correlated_redundant" if np.isfinite(correlation) and abs(correlation) >= .90 else "not_champion"
    frozen = {"trial_number": champion["trial_number"], "model_spec": champion["model_spec"],
        "feature_spec_hash": digest(base["factor_specs"]), "selected_by": "model_selection_only",
        "audit_used_for_selection": False, "screen_passed": not champion["screen_blockers"]}
    emit("screen", "completed", {"frozen_champion": frozen, "model_trials": base["model_trials"]})
    audit_windows = {"train": [plan["segments"]["train"][0], plan["segments"]["valid"][1]],
        "valid": plan["segments"]["selection"], "test": plan["segments"]["audit"]}
    emit("screen", "running", {"phase": "frozen_champion_audit", "frozen_champion": frozen})
    candidate_id = "alpha_" + digest({"frozen": frozen, "run_id": request["run_id"]})[:24]
    pred, audit_reference = trainer(features=features, labels=labels, segments=audit_windows, plan=plan,
        model_spec=champion["model_spec"], trial_number=champion["trial_number"], phase="final" if acceptance else "audit",
        candidate_id=candidate_id)
    audit = signal_metrics(pred, labels.reindex(pred.index), profile["metric_mode"])
    emit("screen", "completed", {"frozen_champion": frozen, "audit_metrics": audit, "audit_reference": audit_reference})
    gate = nomination_gate(champion["selection_metrics"], audit, observed_audit=profile["previously_observed_audit"])
    gate["blockers"] += champion["screen_blockers"]
    if gate["blockers"]: gate["status"] = "rejected"
    candidate = {"candidate_id": candidate_id,
        "factory_run_id": request["run_id"], "model_trial": champion["trial_number"],
        "qlib_run_id": audit_reference["qlib_run_id"], "data_version": profile["data_version"],
        "profile_id": profile["profile_id"], "feature_specs": base["factor_specs"],
        "status": gate["status"], "gate": gate, "audit_metrics": audit, "frozen_champion": frozen,
        "audit_qlib_reference": audit_reference, "strategy_config": {"strategy_id": "qlib_forecast",
            "market": profile["market"], "bar_size": profile["bar_size"], "forecast_source": audit_reference["qlib_run_id"],
            "mode": "research_only", "automatic_execution_handoff": False}, **SAFETY}
    if acceptance:
        delivery_evidence = audit_reference.get("acceptance_delivery_evidence")
        if not isinstance(delivery_evidence, dict):
            raise FactoryError("acceptance_delivery_evidence_missing")
        delivery_evidence["frozen_policy"]["feature_specs_sha256"] = digest(base["factor_specs"])
        candidate["delivery_evidence"] = delivery_evidence
    base.update(candidates=[candidate], decision=gate["status"], blockers=gate["blockers"],
        audit_provenance="historical_observed_not_confirmatory" if profile["previously_observed_audit"] else "precommitted_unseen",
        statistical_trial_count=search["unique_expression_count"] + len(base["model_trials"]),
        qlib_fit_count=sum(len(row["qlib_runs"]) for row in base["model_trials"]) + 1,
        dsr=None, pbo=None, returns_evidence="not_run_signal_factory_not_trading_backtest")
    emit("nominate", "completed", {"candidate": candidate, "decision": gate["status"]})
    return base


def _primitives(node):
    if node["op"] == "primitive": return [node["primitive"]]
    return [name for child in node.get("args", []) for name in _primitives(child)]


def _validate_real_acceptance_offline_window(index, plan):
    calendar = index.get_level_values("datetime").unique().sort_values()
    offline_start = pd.Timestamp("2026-06-16T01:00:00Z")
    offline_end = pd.Timestamp("2026-06-18T00:00:00Z")
    positions = {value: calendar.get_loc(value) if value in calendar else None for value in (offline_start, offline_end)}
    if any(value is None for value in positions.values()) or positions[offline_end] - positions[offline_start] + 1 != 48:
        raise FactoryError("acceptance_fixed_48_decision_window_missing")
    audit_start, audit_end = map(pd.Timestamp, plan["segments"]["audit"])
    if audit_start != offline_start or audit_end < offline_end:
        raise FactoryError("acceptance_offline_window_not_covered_by_audit")
