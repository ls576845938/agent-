"""Adapter for legacy definitions/template generation/GA AST crossover.

No legacy miner, SQLite, latest artifact, cross-sectional preprocessor or proxy
backtest is called. Market-independent contracts never import a domain miner.
"""
from __future__ import annotations

from dataclasses import asdict

import numpy as np
import pandas as pd

from quant_shared.alpha_factory.contracts import FactorSpec
from quant_shared.alpha_factory.evaluation import rolling_z


def crossover(left: dict, right: dict, rng) -> dict:
    from quant_crypto.research.ga_factor_mining import FactorExpression, _crossover
    return _crossover(FactorExpression.from_mapping(left), FactorExpression.from_mapping(right), rng).to_dict()


def build_primitives(panel: pd.DataFrame, *, bar_size: str, annualization: float):
    from quant_us.factors.definition import FactorLibrary
    from quant_us.factors.pipeline import _compute_factor_series
    library = FactorLibrary()
    columns, metadata = {}, []
    for definition in library.list_all():
        pieces = []
        for _, frame in panel.groupby(level="instrument"):
            value = _compute_factor_series(definition.factor_id, frame.close, frame.volume)
            # Legacy realized_volatility uses sqrt(252); explicitly remap before
            # rolling normalization, preserving actual bar rather than day units.
            if definition.category == "volatility": value = value * np.sqrt(annualization / 252)
            pieces.append(value)
        raw = pd.concat(pieces).reindex(panel.index).astype(float)
        columns[definition.factor_id] = rolling_z(raw, 60)
        metadata.append({"primitive": definition.factor_id, "source": "FactorLibrary",
            "source_definition": {k:v for k,v in asdict(definition).items() if k != "created_at"}, "effective_lookback_unit": "bars",
            "effective_bar_size": bar_size, "normalization": "causal_per_instrument_rolling_60",
            "sector_neutralization_applied": False})
    for field in ("funding_rate", "open_interest", "liquidation"):
        if field in panel:
            columns[field] = rolling_z(panel[field], 60)
            metadata.append({"primitive": field, "source": "available_time_aligned_market_field",
                "normalization": "causal_per_instrument_rolling_60"})
    return pd.DataFrame(columns, index=panel.index), metadata


def seed_factors(primitives: list[str], *, template_budget=24):
    from quant_us.factors.formula import generate_candidate_formula_specs
    specs = [FactorSpec({"op": "primitive", "primitive": name}, "registered", name,
        {"registry": "FactorLibrary_or_market_capability"}) for name in primitives]
    generated = generate_candidate_formula_specs(seed_factor_ids=primitives, max_specs=template_budget)
    leaf = lambda name: {"op": "primitive", "primitive": name}
    const = lambda value: {"op": "const", "value": value}
    binary = lambda op, a, b: {"op": op, "args": [a, b]}
    for item in generated:
        args = [leaf(name) for name in item.components]
        if any(name not in primitives for name in item.components): continue
        if item.formula_type == "signed_power":
            node = {"op": "signed_power", "args": [args[0]]}
        elif item.formula_type == "linear_combo" and len(args) == 2:
            node = binary("add", binary("mul", args[0], const(item.weights[0])),
                binary("mul", args[1], const(item.weights[1])))
        elif item.formula_type == "interaction": node = binary("mul", args[0], args[1])
        else:
            # Unsupported template semantics are not approximated silently.
            continue
        specs.append(FactorSpec(node, "template", item.factor_id,
            {"generator": "generate_candidate_formula_specs", "legacy_spec": {k:v for k,v in asdict(item).items() if k != "created_at"},
             "normalization_override": "causal_per_instrument_rolling_not_cross_sectional"}))
    return specs
