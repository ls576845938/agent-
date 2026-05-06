from __future__ import annotations

from dataclasses import fields, is_dataclass
from typing import Any

from quant_us.strategies.base import Strategy
from quant_us.strategies.earnings_drift_strategy import EarningsDriftStrategy
from quant_us.strategies.etf_rotation_strategy import EtfMomentumRotationStrategy
from quant_us.strategies.factor_rank_strategy import FactorRankStrategy
from quant_us.strategies.mean_reversion_strategy import MeanReversionStrategy
from quant_us.strategies.momentum_strategy import MomentumStrategy


STRATEGY_REGISTRY: dict[str, type[Strategy]] = {
    "trend_momentum": MomentumStrategy,
    "short_reversion": MeanReversionStrategy,
    "factor_rank": FactorRankStrategy,
    "earnings_drift": EarningsDriftStrategy,
    "etf_rotation": EtfMomentumRotationStrategy,
}


def build_strategy(strategy_id: str, parameters: dict[str, Any] | None = None) -> Strategy:
    strategy_cls = STRATEGY_REGISTRY.get(strategy_id)
    if strategy_cls is None:
        raise ValueError(f"Unknown quant_us strategy_id: {strategy_id}")
    params = parameters or {}
    allowed = strategy_parameter_names(strategy_id)
    unknown = sorted(set(params) - allowed)
    if unknown:
        raise ValueError(f"Unknown parameters for {strategy_id}: {unknown}")
    return strategy_cls(**params)


def strategy_parameter_names(strategy_id: str) -> set[str]:
    strategy_cls = STRATEGY_REGISTRY.get(strategy_id)
    if strategy_cls is None:
        raise ValueError(f"Unknown quant_us strategy_id: {strategy_id}")
    if not is_dataclass(strategy_cls):
        return set()
    return {field.name for field in fields(strategy_cls) if field.init and not field.name.startswith("_")}


def available_strategies() -> list[str]:
    return sorted(STRATEGY_REGISTRY)
