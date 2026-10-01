"""Budgeted genetic search over a supplied train-only frame and seed catalog."""
from __future__ import annotations

import copy
import random

from .contracts import BINARY, UNARY, FactorSpec, FactoryError, validate_expression
from .evaluation import evaluate_expression, signal_metrics, select_decorrelated


def random_expression(rng, primitives, depth=1):
    if depth >= 3 or rng.random() < .4:
        return {"op": "primitive", "primitive": rng.choice(primitives)}
    op = rng.choice(UNARY + BINARY)
    result = {"op": op, "args": [random_expression(rng, primitives, depth + 1)
        for _ in range(1 if op in UNARY else 2)]}
    if op == "rolling_z": result["window"] = rng.choice([12, 24, 60])
    return result


def mutate(node, rng, primitives, depth=1):
    if depth >= 3 or not node.get("args") or rng.random() < .3:
        return random_expression(rng, primitives, depth)
    result = copy.deepcopy(node)
    index = rng.randrange(len(result["args"]))
    result["args"][index] = mutate(result["args"][index], rng, primitives, depth + 1)
    return result


def search_factors(primitives, labels, seed_specs, request, *, mode, crossover, on_trial=lambda row: None):
    rng = random.Random(request["seed"])
    trial_log, scored, values, unique = [], [], {}, {}

    def score(spec, generation, parents=()):
        row = {**spec.to_dict(), "trial_number": len(trial_log) + 1, "generation": generation,
            "parents": list(parents), "status": "evaluated", "fitness": 0.0,
            "evaluation_segment": "train", "holdout_accessed": False}
        try:
            complexity = validate_expression(spec.expression, set(primitives))
            if spec.factor_id in unique:
                raise FactoryError("duplicate_expression")
            unique[spec.factor_id] = spec
            value = evaluate_expression(spec.expression, primitives)
            metrics = signal_metrics(value, labels, mode)
            row.update(metrics=metrics, complexity=complexity)
            if metrics["rank_ic"] is None or metrics["block_count"] < 3 or metrics["coverage"] < .80:
                raise FactoryError("insufficient_train_coverage_or_ic")
            # The GA fitness is explicitly exploratory; no pseudo-PnL objective.
            fitness = max(0, abs(metrics["rank_ic"]) - .001 * complexity)
            row["fitness"] = fitness
            values[spec.factor_id] = value
            scored.append(row)
        except (FactoryError, KeyError, ValueError) as exc:
            row.update(status="rejected", reason=str(exc))
        trial_log.append(row)
        on_trial(row)

    for spec in seed_specs:
        if spec.origin in request["generators"]:
            score(spec, 0)
    if "genetic" in request["generators"]:
        for generation in range(1, request["generations"] + 1):
            # Freeze parent pool per generation, not per evaluation order.
            pool = sorted(scored, key=lambda x: (-x["fitness"], x["factor_id"]))[:max(2, request["population"] // 2)]
            for attempt in range(request["population"]):
                parents = []
                if len(pool) >= 2 and rng.random() < .75:
                    left, right = rng.sample(pool, 2)
                    node = crossover(left["expression"], right["expression"], rng)
                    node = mutate(node, rng, list(primitives))
                    parents = [left["factor_id"], right["factor_id"]]
                else:
                    node = random_expression(rng, list(primitives))
                score(FactorSpec(node, "genetic", f"generation_{generation}_{attempt}",
                    {"search_algorithm": "budgeted_tournament_crossover_mutation_v1"}), generation, parents)
    selected, rejections = select_decorrelated(scored, values, maximum=request["max_features"])
    return {"trials": trial_log, "selected": selected, "selection_rejections": rejections,
        "specs": [unique[row["factor_id"]] for row in selected],
        "trial_count": len(trial_log), "unique_expression_count": len(unique),
        "search_data_scope": "train_only", "max_abs_train_correlation": .90}
