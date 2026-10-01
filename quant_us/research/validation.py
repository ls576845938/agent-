"""Research validation statistics for promotion and review evidence.

This module summarizes cross-validation structure, multiple-testing burden,
Deflated Sharpe Ratio (DSR), Probability of Backtest Overfitting (PBO),
net-return distribution, and cost before/after effects from persisted
candidate evidence.
"""

from __future__ import annotations

from collections import defaultdict
import math
from statistics import NormalDist
from typing import Any, Mapping, Sequence


_NORMAL = NormalDist()
_EULER_MASCHERONI = 0.5772156649015329


def summarize_candidate_validation(
    *,
    candidate_id: str,
    metrics: Mapping[str, Any] | None,
    walk_forward_artifact: Mapping[str, Any] | None = None,
    cost_stress_artifact: Mapping[str, Any] | None = None,
    experiment_data: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a compact validation summary for promotion evidence."""
    metrics = metrics or {}
    walk_forward_artifact = walk_forward_artifact or {}
    cost_stress_artifact = cost_stress_artifact or {}
    experiment_data = experiment_data or {}

    cv_summary = _summarize_cv(metrics, walk_forward_artifact)
    lookahead_controls = _summarize_lookahead_controls(
        metrics=metrics,
        walk_forward_artifact=walk_forward_artifact,
        experiment_data=experiment_data,
    )
    trial_sharpes = _collect_trial_sharpes(metrics, walk_forward_artifact, cost_stress_artifact)
    pbo_trials = _collect_pbo_trials(metrics, walk_forward_artifact)
    cost_levels = _collect_cost_levels(metrics, cost_stress_artifact)
    trial_counting = _summarize_trial_counting(
        metrics=metrics,
        experiment_data=experiment_data,
        cv_summary=cv_summary,
        trial_sharpes=trial_sharpes,
        pbo_trials=pbo_trials,
        cost_levels=cost_levels,
    )
    return_series = _collect_return_series(metrics, walk_forward_artifact, cost_stress_artifact)
    return_distribution = _summarize_return_distribution(return_series)
    cost_before_after = _summarize_cost_before_after(
        metrics=metrics,
        cost_levels=cost_levels,
    )
    dsr_summary = _summarize_deflated_sharpe_ratio(
        metrics=metrics,
        return_series=return_series,
        trial_sharpes=trial_sharpes,
        trial_count=trial_counting["effective_trial_count"],
    )
    pbo_summary = _summarize_pbo(pbo_trials)
    multiple_testing = _summarize_multiple_testing(
        dsr_summary=dsr_summary,
        trial_counting=trial_counting,
    )
    promotion_gate_contract = _build_promotion_gate_contract(
        cv_summary=cv_summary,
        lookahead_controls=lookahead_controls,
        trial_counting=trial_counting,
        dsr_summary=dsr_summary,
        pbo_summary=pbo_summary,
        multiple_testing=multiple_testing,
    )

    available_components = {
        "cv_summary": cv_summary["fold_count"] > 0 or cv_summary["path_count"] > 0,
        "trial_counting": trial_counting["effective_trial_count"] > 0,
        "deflated_sharpe_ratio": dsr_summary["dsr"] is not None,
        "pbo": pbo_summary["pbo"] is not None,
        "multiple_testing": multiple_testing["mode"] != "unavailable",
        "lookahead_controls": lookahead_controls["recorded"] and lookahead_controls["passed"],
        "net_return_distribution": return_distribution["count"] > 0,
        "cost_before_after": cost_before_after["mode"] != "unavailable",
    }
    complete = all(available_components.values())

    return {
        "candidate_id": candidate_id,
        "status": "complete" if complete else "partial",
        "available_components": available_components,
        "cv_summary": cv_summary,
        "lookahead_controls": lookahead_controls,
        "trial_counting": trial_counting,
        "deflated_sharpe_ratio": dsr_summary,
        "pbo": pbo_summary,
        "multiple_testing": multiple_testing,
        "net_return_distribution": return_distribution,
        "cost_before_after": cost_before_after,
        "promotion_gate_contract": promotion_gate_contract,
    }


def _summarize_cv(
    metrics: Mapping[str, Any],
    walk_forward_artifact: Mapping[str, Any],
) -> dict[str, Any]:
    method = _infer_cv_method(metrics, walk_forward_artifact)
    folds = _extract_fold_records(metrics, walk_forward_artifact)
    oos_sharpes = [
        _first_float(record, ("oos_sharpe", "test_sharpe", "validation_sharpe", "sharpe_ratio"))
        for record in folds
    ]
    oos_sharpes = [value for value in oos_sharpes if value is not None]
    passed = [_coerce_bool(record.get("passed")) for record in folds if "passed" in record]
    pass_rate = _first_float(
        walk_forward_artifact,
        ("walk_forward_pass_rate", "pass_rate"),
    )
    if pass_rate is None:
        pass_rate = _first_float(metrics, ("walk_forward_pass_rate",))
    if pass_rate is None and passed:
        pass_rate = sum(1 for item in passed if item) / len(passed)

    raw_n_splits = _first_int(walk_forward_artifact, ("n_splits", "fold_count", "n_folds"))
    raw_test_splits = _first_int(
        walk_forward_artifact,
        ("test_splits", "n_test_splits", "test_window_count"),
    )
    path_count = _first_int(
        walk_forward_artifact,
        ("combination_count", "path_count", "cpcv_path_count"),
    )
    if path_count is None and method == "cpcv" and raw_n_splits and raw_test_splits:
        try:
            path_count = math.comb(raw_n_splits, raw_test_splits)
        except ValueError:
            path_count = None

    purge_steps = _first_int(
        walk_forward_artifact,
        ("purge_bars", "purge_steps", "purge_periods"),
    )
    if purge_steps is None:
        purge_steps = _first_int(metrics, ("purge_bars", "purge_steps", "purge_periods"))
    embargo_steps = _first_int(
        walk_forward_artifact,
        ("embargo_bars", "embargo_steps", "embargo_periods"),
    )
    if embargo_steps is None:
        embargo_steps = _first_int(metrics, ("embargo_bars", "embargo_steps", "embargo_periods"))
    purged = _first_bool(walk_forward_artifact, ("purged", "is_purged"))
    if purged is None:
        purged = _first_bool(metrics, ("purged", "is_purged"))
    embargoed = _first_bool(walk_forward_artifact, ("embargoed", "is_embargoed"))
    if embargoed is None:
        embargoed = _first_bool(metrics, ("embargoed", "is_embargoed"))
    if embargoed is None and embargo_steps is not None:
        embargoed = embargo_steps > 0
    purge_recorded = purged is not None or purge_steps is not None
    embargo_recorded = embargoed is not None or embargo_steps is not None

    return {
        "method": method,
        "purged": bool(purged) if purged is not None else False,
        "purge_steps": purge_steps or 0,
        "purge_recorded": purge_recorded,
        "embargoed": bool(embargoed) if embargoed is not None else False,
        "embargo_steps": embargo_steps or 0,
        "embargo_recorded": embargo_recorded,
        "fold_count": len(folds),
        "path_count": path_count or 0,
        "train_window_count": raw_n_splits or 0,
        "test_window_count": raw_test_splits or 0,
        "pass_rate": round(float(pass_rate), 6) if pass_rate is not None else None,
        "mean_oos_sharpe": round(_mean(oos_sharpes), 6) if oos_sharpes else None,
        "median_oos_sharpe": round(_median(oos_sharpes), 6) if oos_sharpes else None,
    }


def _summarize_lookahead_controls(
    *,
    metrics: Mapping[str, Any],
    walk_forward_artifact: Mapping[str, Any],
    experiment_data: Mapping[str, Any],
) -> dict[str, Any]:
    params = experiment_data.get("params", {})
    if not isinstance(params, Mapping):
        params = {}

    guard = _first_string(
        walk_forward_artifact,
        ("lookahead_guard", "lookahead_policy", "feature_timing_guard"),
    )
    if guard is None:
        guard = _first_string(metrics, ("lookahead_guard", "lookahead_policy", "feature_timing_guard"))
    if guard is None:
        guard = _first_string(experiment_data, ("lookahead_guard", "lookahead_policy", "feature_timing_guard"))
    if guard is None:
        guard = _first_string(params, ("lookahead_guard", "lookahead_policy", "feature_timing_guard"))

    violations: list[str] = []
    for key in ("bfill_features", "shift_minus_one", "uses_future_returns", "same_bar_label"):
        value = _first_bool(params, (key,))
        if value is True:
            violations.append(key)
    for key in ("lookahead_detected", "has_lookahead", "future_leak_detected"):
        value = _first_bool(metrics, (key,))
        if value is True:
            violations.append(key)
        value = _first_bool(walk_forward_artifact, (key,))
        if value is True:
            violations.append(key)

    recorded = guard is not None
    passed = recorded and not violations
    return {
        "recorded": recorded,
        "guard": guard,
        "violations": violations,
        "passed": passed,
    }


def _summarize_trial_counting(
    *,
    metrics: Mapping[str, Any],
    experiment_data: Mapping[str, Any],
    cv_summary: Mapping[str, Any],
    trial_sharpes: list[float],
    pbo_trials: list[dict[str, Any]],
    cost_levels: list[dict[str, Any]],
) -> dict[str, Any]:
    declared = _first_int(
        metrics,
        (
            "trial_count",
            "n_trials",
            "num_trials",
            "candidate_trial_count",
            "effective_trial_count",
        ),
    )
    param_grid_trials = _param_grid_trials(experiment_data.get("param_grid", {}))
    pbo_split_count = len({str(item.get("split_id", "")) for item in pbo_trials if item.get("split_id")})
    unique_configs = len(
        {
            str(item.get("config_id", ""))
            for item in pbo_trials
            if str(item.get("config_id", ""))
        }
    )
    components = [
        declared or 0,
        param_grid_trials,
        len(trial_sharpes),
        len(cost_levels),
        unique_configs,
    ]
    effective = max([value for value in components if value > 0], default=0)
    independent = _first_int(metrics, ("independent_trial_count", "effective_independent_trials"))
    if independent is None:
        independent = max(
            [value for value in (unique_configs, pbo_split_count, len(trial_sharpes), effective) if value > 0],
            default=0,
        )
    independent = min(independent, effective) if effective > 0 else independent

    return {
        "declared_trial_count": declared or 0,
        "param_grid_trial_count": param_grid_trials,
        "cv_path_count": int(cv_summary.get("path_count", 0) or 0),
        "cv_fold_count": int(cv_summary.get("fold_count", 0) or 0),
        "cost_level_count": len(cost_levels),
        "trial_sharpe_count": len(trial_sharpes),
        "pbo_split_count": pbo_split_count,
        "independent_trial_count": independent or 0,
        "effective_trial_count": effective,
    }


def _summarize_deflated_sharpe_ratio(
    *,
    metrics: Mapping[str, Any],
    return_series: list[float],
    trial_sharpes: list[float],
    trial_count: int,
) -> dict[str, Any]:
    observed_sharpe = _first_float(metrics, ("sharpe_ratio", "sharpe", "net_sharpe_ratio"))
    if observed_sharpe is None and len(return_series) >= 2:
        observed_sharpe = _sharpe_from_returns(return_series)

    sample_size = _first_int(
        metrics,
        (
            "return_observation_count",
            "n_observations",
            "n_periods",
            "bar_count",
            "sample_count",
        ),
    )
    if sample_size is None:
        sample_size = len(return_series)
    if sample_size <= 1 or observed_sharpe is None:
        return {
            "observed_sharpe": observed_sharpe,
            "benchmark_sharpe": None,
            "trial_count": trial_count,
            "returns_count": len(return_series),
            "skew": None,
            "excess_kurtosis": None,
            "psr": None,
            "dsr": None,
            "passed": None,
        }

    skew = _skewness(return_series)
    excess_kurtosis = _excess_kurtosis(return_series)
    trial_count = max(int(trial_count or 0), len(trial_sharpes), 1)

    if trial_sharpes:
        trial_mean = _mean(trial_sharpes)
        trial_std = _sample_std(trial_sharpes)
    else:
        trial_mean = 0.0
        trial_std = 1.0 / math.sqrt(max(sample_size - 1, 1))

    benchmark = _expected_max_sharpe(trial_mean, trial_std, trial_count)
    psr = _probabilistic_sharpe_ratio(
        observed_sharpe=observed_sharpe,
        benchmark_sharpe=0.0,
        sample_size=sample_size,
        skew=skew,
        excess_kurtosis=excess_kurtosis,
    )
    dsr = _probabilistic_sharpe_ratio(
        observed_sharpe=observed_sharpe,
        benchmark_sharpe=benchmark,
        sample_size=sample_size,
        skew=skew,
        excess_kurtosis=excess_kurtosis,
    )
    return {
        "observed_sharpe": round(observed_sharpe, 6),
        "benchmark_sharpe": round(benchmark, 6),
        "trial_count": trial_count,
        "returns_count": len(return_series),
        "skew": round(skew, 6),
        "excess_kurtosis": round(excess_kurtosis, 6),
        "psr": round(psr, 6) if psr is not None else None,
        "dsr": round(dsr, 6) if dsr is not None else None,
        "passed": dsr is not None and dsr >= 0.10,
    }


def _summarize_pbo(pbo_trials: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in pbo_trials:
        split_id = str(item.get("split_id", "") or "")
        if not split_id:
            continue
        train_score = _first_float(item, ("train_sharpe", "train_score", "in_sample_sharpe"))
        test_score = _first_float(item, ("test_sharpe", "test_score", "oos_sharpe", "out_of_sample_sharpe"))
        if train_score is None or test_score is None:
            continue
        grouped[split_id].append(
            {
                "config_id": str(item.get("config_id", "")),
                "train_score": train_score,
                "test_score": test_score,
            }
        )

    valid_groups = [group for group in grouped.values() if len(group) >= 2]
    if not valid_groups:
        return {
            "mode": "unavailable",
            "group_count": 0,
            "overfit_group_count": 0,
            "pbo": None,
            "logit_mean": None,
            "logit_median": None,
            "passed": None,
        }

    logits: list[float] = []
    overfit = 0
    for group in valid_groups:
        selected = max(group, key=lambda item: item["train_score"])
        ranked = sorted(
            (item["test_score"] for item in group),
            reverse=True,
        )
        rank_index = ranked.index(selected["test_score"])
        percentile = 1.0 - (rank_index / max(len(ranked) - 1, 1))
        clip = 1.0 / (2.0 * len(ranked))
        percentile = min(max(percentile, clip), 1.0 - clip)
        logit = math.log(percentile / (1.0 - percentile))
        logits.append(logit)
        if logit <= 0.0:
            overfit += 1

    pbo = overfit / len(logits)
    return {
        "mode": "grouped_trials",
        "group_count": len(logits),
        "overfit_group_count": overfit,
        "pbo": round(pbo, 6),
        "logit_mean": round(_mean(logits), 6),
        "logit_median": round(_median(logits), 6),
        "passed": pbo <= 0.20,
    }


def _summarize_multiple_testing(
    *,
    dsr_summary: Mapping[str, Any],
    trial_counting: Mapping[str, Any],
) -> dict[str, Any]:
    psr = _first_float(dsr_summary, ("psr",))
    dsr = _first_float(dsr_summary, ("dsr",))
    effective_trials = max(int(trial_counting.get("effective_trial_count", 0) or 0), 0)
    independent_trials = max(int(trial_counting.get("independent_trial_count", 0) or 0), 0)
    if independent_trials <= 0:
        independent_trials = effective_trials
    if psr is None or independent_trials <= 0:
        return {
            "mode": "unavailable",
            "familywise_alpha": 0.05,
            "effective_trial_count": effective_trials,
            "independent_trial_count": independent_trials,
            "raw_p_value": None,
            "bonferroni_alpha": None,
            "sidak_alpha": None,
            "dsr_p_value": None,
            "passed": None,
        }

    familywise_alpha = 0.05
    bonferroni_alpha = familywise_alpha / independent_trials
    sidak_alpha = 1.0 - ((1.0 - familywise_alpha) ** (1.0 / independent_trials))
    raw_p_value = max(0.0, min(1.0, 1.0 - psr))
    dsr_p_value = max(0.0, min(1.0, 1.0 - dsr)) if dsr is not None else None
    passed = raw_p_value <= bonferroni_alpha and (dsr is None or dsr >= 0.10)
    return {
        "mode": "familywise_error_control",
        "familywise_alpha": familywise_alpha,
        "effective_trial_count": effective_trials,
        "independent_trial_count": independent_trials,
        "raw_p_value": round(raw_p_value, 6),
        "bonferroni_alpha": round(bonferroni_alpha, 6),
        "sidak_alpha": round(sidak_alpha, 6),
        "dsr_p_value": round(dsr_p_value, 6) if dsr_p_value is not None else None,
        "passed": passed,
    }


def _build_promotion_gate_contract(
    *,
    cv_summary: Mapping[str, Any],
    lookahead_controls: Mapping[str, Any],
    trial_counting: Mapping[str, Any],
    dsr_summary: Mapping[str, Any],
    pbo_summary: Mapping[str, Any],
    multiple_testing: Mapping[str, Any],
) -> dict[str, Any]:
    method = str(cv_summary.get("method", "unknown") or "unknown")
    validation_paths = max(
        int(cv_summary.get("path_count", 0) or 0),
        int(cv_summary.get("fold_count", 0) or 0),
    )
    effective_trials = int(trial_counting.get("effective_trial_count", 0) or 0)
    independent_trials = int(trial_counting.get("independent_trial_count", 0) or 0)
    dsr = _first_float(dsr_summary, ("dsr",))
    pbo = _first_float(pbo_summary, ("pbo",))
    checks = {
        "cv_method_allowed": method in {"cpcv", "purged_kfold", "embargoed_walk_forward"},
        "cpcv_available": method == "cpcv" and validation_paths >= 2,
        "purged_or_embargoed": bool(cv_summary.get("purged")) or bool(cv_summary.get("embargoed")),
        "purge_embargo_recorded": bool(cv_summary.get("purge_recorded")) and bool(cv_summary.get("embargo_recorded")),
        "multi_path_validation": validation_paths >= 2,
        "trial_count_sufficient": effective_trials >= 2 and independent_trials >= 2,
        "dsr_available": dsr is not None,
        "dsr_passed": dsr is not None and dsr >= 0.10,
        "pbo_available": pbo is not None,
        "pbo_passed": pbo is not None and pbo <= 0.50,
        "multiple_testing_complete": multiple_testing.get("passed") is not None,
        "multiple_testing_passed": multiple_testing.get("passed") is True,
        "lookahead_guard_recorded": bool(lookahead_controls.get("recorded")),
        "lookahead_guard_passed": lookahead_controls.get("passed") is True,
    }
    blocking_checks = (
        "cv_method_allowed",
        "cpcv_available",
        "purged_or_embargoed",
        "purge_embargo_recorded",
        "multi_path_validation",
        "trial_count_sufficient",
        "dsr_available",
        "dsr_passed",
        "pbo_available",
        "pbo_passed",
        "multiple_testing_complete",
        "multiple_testing_passed",
        "lookahead_guard_recorded",
        "lookahead_guard_passed",
    )
    status = "passed" if all(checks[name] for name in blocking_checks) else "blocked"
    return {
        "status": status,
        "required": {
            "allowed_cv_methods": ["cpcv", "purged_kfold", "embargoed_walk_forward"],
            "required_cv_method": "cpcv",
            "min_validation_paths": 2,
            "min_effective_trial_count": 2,
            "min_independent_trial_count": 2,
            "min_dsr": 0.10,
            "max_pbo": 0.50,
            "familywise_alpha": 0.05,
            "lookahead_guard_recorded": True,
        },
        "observed": {
            "cv_method": method,
            "validation_paths": validation_paths,
            "purged": bool(cv_summary.get("purged")),
            "purge_recorded": bool(cv_summary.get("purge_recorded")),
            "embargoed": bool(cv_summary.get("embargoed")),
            "embargo_recorded": bool(cv_summary.get("embargo_recorded")),
            "effective_trial_count": effective_trials,
            "independent_trial_count": independent_trials,
            "dsr": dsr,
            "pbo": pbo,
            "multiple_testing_mode": str(multiple_testing.get("mode", "unavailable")),
            "lookahead_guard_recorded": bool(lookahead_controls.get("recorded")),
            "lookahead_violations": list(lookahead_controls.get("violations", []) or []),
        },
        "checks": checks,
    }


def _summarize_return_distribution(return_series: list[float]) -> dict[str, Any]:
    if not return_series:
        return {
            "count": 0,
            "mean": None,
            "std": None,
            "median": None,
            "min": None,
            "max": None,
            "p05": None,
            "p25": None,
            "p75": None,
            "p95": None,
            "negative_share": None,
        }

    negatives = sum(1 for item in return_series if item < 0.0)
    return {
        "count": len(return_series),
        "mean": round(_mean(return_series), 6),
        "std": round(_sample_std(return_series), 6),
        "median": round(_median(return_series), 6),
        "min": round(min(return_series), 6),
        "max": round(max(return_series), 6),
        "p05": round(_percentile(return_series, 0.05), 6),
        "p25": round(_percentile(return_series, 0.25), 6),
        "p75": round(_percentile(return_series, 0.75), 6),
        "p95": round(_percentile(return_series, 0.95), 6),
        "negative_share": round(negatives / len(return_series), 6),
    }


def _summarize_cost_before_after(
    *,
    metrics: Mapping[str, Any],
    cost_levels: list[dict[str, Any]],
) -> dict[str, Any]:
    gross_return = _first_float(metrics, ("gross_total_return_pct", "gross_return_pct", "gross_cagr"))
    net_return = _first_float(metrics, ("total_return_pct", "net_total_return_pct", "cagr"))
    gross_sharpe = _first_float(metrics, ("gross_sharpe_ratio", "gross_sharpe"))
    net_sharpe = _first_float(metrics, ("sharpe_ratio", "net_sharpe_ratio"))

    baseline = None
    worst = None
    if cost_levels:
        ranked = sorted(
            cost_levels,
            key=lambda item: (_cost_multiplier(item), item.get("_position", 0)),
        )
        baseline = min(ranked, key=lambda item: abs(_cost_multiplier(item) - 1.0))
        worst = max(ranked, key=_cost_multiplier)
        if net_return is None:
            net_return = _first_float(baseline, ("total_return_pct", "net_return_pct", "return_pct"))
        if net_sharpe is None:
            net_sharpe = _first_float(baseline, ("sharpe_ratio", "net_sharpe_ratio", "sharpe"))

    mode = "unavailable"
    if gross_return is not None and net_return is not None:
        mode = "gross_vs_net"
    elif baseline is not None and worst is not None:
        mode = "stress_curve"

    if mode == "gross_vs_net" and baseline is not None and worst is not None:
        mode = "gross_vs_net_plus_stress"

    worst_return = (
        _first_float(worst, ("total_return_pct", "net_return_pct", "return_pct"))
        if worst is not None
        else None
    )
    worst_sharpe = (
        _first_float(worst, ("sharpe_ratio", "net_sharpe_ratio", "sharpe"))
        if worst is not None
        else None
    )
    surviving_levels = 0
    for level in cost_levels:
        level_return = _first_float(level, ("total_return_pct", "net_return_pct", "return_pct"))
        level_sharpe = _first_float(level, ("sharpe_ratio", "net_sharpe_ratio", "sharpe"))
        if level_return is not None and level_sharpe is not None and level_return > 0.0 and level_sharpe >= 0.0:
            surviving_levels += 1

    return {
        "mode": mode,
        "gross_return": gross_return,
        "net_return": net_return,
        "gross_sharpe": gross_sharpe,
        "net_sharpe": net_sharpe,
        "cost_drag_return": round(gross_return - net_return, 6)
        if gross_return is not None and net_return is not None
        else None,
        "cost_drag_sharpe": round(gross_sharpe - net_sharpe, 6)
        if gross_sharpe is not None and net_sharpe is not None
        else None,
        "baseline_multiplier": _cost_multiplier(baseline) if baseline is not None else None,
        "worst_multiplier": _cost_multiplier(worst) if worst is not None else None,
        "worst_return": worst_return,
        "worst_sharpe": worst_sharpe,
        "stress_return_delta": round(net_return - worst_return, 6)
        if net_return is not None and worst_return is not None
        else None,
        "surviving_levels": surviving_levels,
        "level_count": len(cost_levels),
    }


def _infer_cv_method(
    metrics: Mapping[str, Any],
    walk_forward_artifact: Mapping[str, Any],
) -> str:
    raw_method = str(
        walk_forward_artifact.get("validation_method")
        or walk_forward_artifact.get("cv_method")
        or metrics.get("validation_method")
        or metrics.get("cv_method")
        or ""
    ).strip().lower()
    if "cpcv" in raw_method or "combinatorial" in raw_method:
        return "cpcv"
    if "purged" in raw_method:
        return "purged_kfold"
    if "embargo" in raw_method:
        return "embargoed_walk_forward"
    if raw_method:
        return raw_method
    if walk_forward_artifact.get("combination_count") or walk_forward_artifact.get("test_splits"):
        return "cpcv"
    if _first_int(walk_forward_artifact, ("embargo_bars", "embargo_steps", "embargo_periods")):
        return "embargoed_walk_forward"
    if _coerce_bool(walk_forward_artifact.get("purged")):
        return "purged_kfold"
    return "unknown"


def _extract_fold_records(
    metrics: Mapping[str, Any],
    walk_forward_artifact: Mapping[str, Any],
) -> list[dict[str, Any]]:
    for source in (
        walk_forward_artifact.get("folds"),
        walk_forward_artifact.get("paths"),
        walk_forward_artifact.get("fold_results"),
        walk_forward_artifact.get("splits"),
        metrics.get("wf_fold_results"),
    ):
        if isinstance(source, list):
            return [dict(item) for item in source if isinstance(item, Mapping)]

    sharpes = _coerce_numeric_list(
        walk_forward_artifact.get("fold_sharpes")
        or metrics.get("wf_fold_sharpes")
        or []
    )
    drawdowns = _coerce_numeric_list(
        walk_forward_artifact.get("fold_drawdowns")
        or metrics.get("wf_fold_drawdowns")
        or []
    )
    results: list[dict[str, Any]] = []
    for index, sharpe in enumerate(sharpes):
        results.append(
            {
                "oos_sharpe": sharpe,
                "max_drawdown_pct": drawdowns[index] if index < len(drawdowns) else None,
            }
        )
    return results


def _collect_trial_sharpes(
    metrics: Mapping[str, Any],
    walk_forward_artifact: Mapping[str, Any],
    cost_stress_artifact: Mapping[str, Any],
) -> list[float]:
    values: list[float] = []
    for item in (
        metrics.get("trial_sharpes"),
        metrics.get("candidate_trial_sharpes"),
        metrics.get("wf_fold_sharpes"),
        walk_forward_artifact.get("fold_sharpes"),
    ):
        values.extend(_coerce_numeric_list(item))

    for record in _extract_fold_records(metrics, walk_forward_artifact):
        sharpe = _first_float(record, ("oos_sharpe", "test_sharpe", "validation_sharpe", "sharpe_ratio"))
        if sharpe is not None:
            values.append(sharpe)

    for level in _collect_cost_levels(metrics, cost_stress_artifact):
        sharpe = _first_float(level, ("sharpe_ratio", "net_sharpe_ratio", "sharpe"))
        if sharpe is not None:
            values.append(sharpe)

    seen: set[float] = set()
    deduped: list[float] = []
    for value in values:
        marker = round(value, 12)
        if marker in seen:
            continue
        seen.add(marker)
        deduped.append(float(value))
    return deduped


def _collect_pbo_trials(
    metrics: Mapping[str, Any],
    walk_forward_artifact: Mapping[str, Any],
) -> list[dict[str, Any]]:
    raw_trials = walk_forward_artifact.get("pbo_trials") or metrics.get("pbo_trials") or []
    if not isinstance(raw_trials, list):
        return []
    trials: list[dict[str, Any]] = []
    for item in raw_trials:
        if isinstance(item, Mapping):
            trials.append(dict(item))
    return trials


def _collect_cost_levels(
    metrics: Mapping[str, Any],
    cost_stress_artifact: Mapping[str, Any],
) -> list[dict[str, Any]]:
    raw_levels = cost_stress_artifact.get("levels") or metrics.get("cost_stress_levels") or []
    if not isinstance(raw_levels, list):
        return []
    levels: list[dict[str, Any]] = []
    for index, item in enumerate(raw_levels):
        if not isinstance(item, Mapping):
            continue
        payload = dict(item)
        payload["_position"] = index
        levels.append(payload)
    return levels


def _collect_return_series(
    metrics: Mapping[str, Any],
    walk_forward_artifact: Mapping[str, Any],
    cost_stress_artifact: Mapping[str, Any],
) -> list[float]:
    for key in (
        "net_returns",
        "return_series",
        "daily_returns",
        "net_return_series",
        "returns",
    ):
        values = _coerce_numeric_list(metrics.get(key))
        if values:
            return values

    for key in ("fold_returns",):
        values = _coerce_numeric_list(walk_forward_artifact.get(key))
        if values:
            return values

    cost_returns = [
        value
        for value in (
            _first_float(level, ("total_return_pct", "net_return_pct", "return_pct"))
            for level in _collect_cost_levels(metrics, cost_stress_artifact)
        )
        if value is not None
    ]
    return cost_returns


def _param_grid_trials(raw_grid: Any) -> int:
    if not isinstance(raw_grid, Mapping) or not raw_grid:
        return 0
    total = 1
    found = False
    for value in raw_grid.values():
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            total *= max(len(value), 1)
            found = True
        else:
            total *= 1
    return total if found else 0


def _expected_max_sharpe(mean_value: float, std_value: float, trial_count: int) -> float:
    if trial_count <= 1 or std_value <= 0.0:
        return mean_value
    z_left = _NORMAL.inv_cdf(1.0 - (1.0 / trial_count))
    z_right = _NORMAL.inv_cdf(1.0 - (1.0 / (trial_count * math.e)))
    return mean_value + std_value * (
        (1.0 - _EULER_MASCHERONI) * z_left
        + _EULER_MASCHERONI * z_right
    )


def _probabilistic_sharpe_ratio(
    *,
    observed_sharpe: float,
    benchmark_sharpe: float,
    sample_size: int,
    skew: float,
    excess_kurtosis: float,
) -> float | None:
    if sample_size <= 1:
        return None
    denominator = 1.0 - skew * observed_sharpe + ((excess_kurtosis + 2.0) / 4.0) * (observed_sharpe ** 2)
    denominator = max(denominator, 1e-12)
    z_score = (observed_sharpe - benchmark_sharpe) * math.sqrt(sample_size - 1.0) / math.sqrt(denominator)
    return _NORMAL.cdf(z_score)


def _sharpe_from_returns(return_series: list[float]) -> float | None:
    std_value = _sample_std(return_series)
    if std_value <= 0.0:
        return None
    return _mean(return_series) / std_value * math.sqrt(252.0)


def _skewness(values: list[float]) -> float:
    if len(values) < 3:
        return 0.0
    mean_value = _mean(values)
    std_value = _sample_std(values)
    if std_value <= 0.0:
        return 0.0
    n = len(values)
    moment3 = sum(((value - mean_value) / std_value) ** 3 for value in values)
    return (n / ((n - 1) * (n - 2))) * moment3


def _excess_kurtosis(values: list[float]) -> float:
    if len(values) < 4:
        return 0.0
    mean_value = _mean(values)
    std_value = _sample_std(values)
    if std_value <= 0.0:
        return 0.0
    n = len(values)
    moment4 = sum(((value - mean_value) / std_value) ** 4 for value in values)
    term1 = (n * (n + 1) * moment4) / ((n - 1) * (n - 2) * (n - 3))
    term2 = (3 * ((n - 1) ** 2)) / ((n - 2) * (n - 3))
    return term1 - term2


def _percentile(values: list[float], level: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    if len(ordered) == 1:
        return ordered[0]
    position = min(max(level, 0.0), 1.0) * (len(ordered) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _cost_multiplier(level: Mapping[str, Any] | None) -> float:
    if not isinstance(level, Mapping):
        return 0.0
    value = _first_float(level, ("cost_multiplier", "multiplier", "cost_multiple", "stress_multiplier"))
    if value is None:
        return float(level.get("_position", 0))
    return value


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _median(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def _sample_std(values: Sequence[float]) -> float:
    if len(values) <= 1:
        return 0.0
    mean_value = _mean(values)
    variance = sum((value - mean_value) ** 2 for value in values) / (len(values) - 1)
    return math.sqrt(max(variance, 0.0))


def _coerce_numeric_list(value: Any) -> list[float]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return []
    values: list[float] = []
    for item in value:
        try:
            values.append(float(item))
        except (TypeError, ValueError):
            continue
    return values


def _first_float(payload: Mapping[str, Any], keys: Sequence[str]) -> float | None:
    for key in keys:
        if key not in payload or payload.get(key) is None:
            continue
        try:
            return float(payload[key])
        except (TypeError, ValueError):
            continue
    return None


def _first_string(payload: Mapping[str, Any], keys: Sequence[str]) -> str | None:
    for key in keys:
        if key not in payload or payload.get(key) in (None, ""):
            continue
        return str(payload[key])
    return None


def _first_int(payload: Mapping[str, Any], keys: Sequence[str]) -> int | None:
    for key in keys:
        if key not in payload or payload.get(key) is None:
            continue
        try:
            return int(payload[key])
        except (TypeError, ValueError):
            continue
    return None


def _first_bool(payload: Mapping[str, Any], keys: Sequence[str]) -> bool | None:
    for key in keys:
        if key not in payload or payload.get(key) is None:
            continue
        value = _coerce_bool(payload[key])
        if value is not None:
            return value
    return None


def _coerce_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "y", "pass", "passed"}:
            return True
        if normalized in {"0", "false", "no", "n", "fail", "failed"}:
            return False
    return None
