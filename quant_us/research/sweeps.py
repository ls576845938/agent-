from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from itertools import product
from pathlib import Path
from typing import Any

from quant_us.backtest.configuration import build_backtest_config
from quant_us.backtest.result_store import BacktestResultStore
from quant_us.backtest.runner import run_event_backtest_from_lake
from quant_us.research.experiments import ArtifactRef, ExperimentRecord, ExperimentRegistry, ExperimentSpec


@dataclass(frozen=True)
class SweepConfig:
    experiment_name: str
    symbols: list[str]
    start: datetime
    end: datetime
    strategy_id: str = "trend_momentum"
    parameter_grid: dict[str, list[Any] | Any] = field(default_factory=dict)
    portfolio_grid: dict[str, list[Any] | Any] = field(default_factory=dict)
    data_root: str = "data"
    vendor: str = "yfinance"
    asset_class: str = "equity"
    bar_size: str = "1d"
    feature_version: str = ""
    feature_universe: str = "default"
    feature_names: list[str] = field(default_factory=list)
    capital: float = 100_000.0
    max_symbol_weight: float = 0.10
    max_order_notional_pct: float = 0.10
    cash_reserve_weight: float = 0.05
    default_strategy_weight: float = 0.10
    min_trade_notional: float = 25.0
    min_weight_change: float = 0.0
    tags: list[str] = field(default_factory=list)
    notes: str = ""


@dataclass(frozen=True)
class SweepResult:
    experiment_name: str
    records: list[ExperimentRecord]
    best: dict[str, Any] | None


def expand_parameter_grid(grid: dict[str, list[Any] | Any]) -> list[dict[str, Any]]:
    if not grid:
        return [{}]
    keys = list(grid)
    values = [value if isinstance(value, list) else [value] for value in grid.values()]
    combinations: list[dict[str, Any]] = []
    for items in product(*values):
        combinations.append(dict(zip(keys, items, strict=True)))
    return combinations


class ResearchSweepRunner:
    def __init__(
        self,
        result_store: BacktestResultStore | None = None,
        registry: ExperimentRegistry | None = None,
    ) -> None:
        self.result_store = result_store
        self.registry = registry

    def run(self, config: SweepConfig, compare_metric: str = "sharpe_ratio") -> SweepResult:
        registry = self.registry or ExperimentRegistry(Path(config.data_root) / "experiments")
        result_store = self.result_store or BacktestResultStore(Path(config.data_root) / "backtest_results")
        records: list[ExperimentRecord] = []
        combinations = [
            (strategy_params, portfolio_params)
            for strategy_params in expand_parameter_grid(config.parameter_grid)
            for portfolio_params in expand_parameter_grid(config.portfolio_grid)
        ]
        for index, (strategy_params, portfolio_params) in enumerate(combinations, start=1):
            backtest_params = {
                "capital": config.capital,
                "max_symbol_weight": config.max_symbol_weight,
                "max_order_notional_pct": config.max_order_notional_pct,
                "cash_reserve_weight": config.cash_reserve_weight,
                "default_strategy_weight": config.default_strategy_weight,
                "min_trade_notional": config.min_trade_notional,
                "min_weight_change": config.min_weight_change,
                **portfolio_params,
            }
            backtest_config = build_backtest_config(parameters=backtest_params)
            spec = ExperimentSpec(
                experiment_name=config.experiment_name,
                run_type="parameter_sweep",
                symbols=config.symbols,
                start=config.start,
                end=config.end,
                strategy_id=config.strategy_id,
                data_vendor=config.vendor,
                asset_class=config.asset_class,
                bar_size=config.bar_size,
                feature_version=config.feature_version,
                parameters={
                    "sweep_index": index,
                    "strategy_params": strategy_params,
                    "backtest_params": backtest_params,
                    "feature_names": config.feature_names,
                    "feature_universe": config.feature_universe,
                },
                tags=config.tags,
                notes=config.notes,
            )
            try:
                result = run_event_backtest_from_lake(
                    data_root=config.data_root,
                    symbol=config.symbols[0],
                    symbols=config.symbols,
                    start=config.start,
                    end=config.end,
                    bar_size=config.bar_size,
                    vendor=config.vendor,
                    asset_class=config.asset_class,
                    strategy_id=config.strategy_id,
                    strategy_params=strategy_params,
                    feature_names=config.feature_names,
                    feature_version=config.feature_version or "v1",
                    feature_universe=config.feature_universe,
                    config=backtest_config,
                )
                persisted = result_store.write(result)
                record = registry.create_record(
                    run_id=result.run_id,
                    spec=spec,
                    metrics=result.summary,
                    artifacts=[
                        ArtifactRef("summary", persisted.summary_path, "json"),
                        ArtifactRef("metadata", persisted.metadata_path, "json"),
                        ArtifactRef("orders", persisted.orders_path, "parquet"),
                        ArtifactRef("fills", persisted.fills_path, "parquet"),
                        ArtifactRef("portfolio_snapshots", persisted.snapshots_path, "parquet"),
                    ],
                )
            except Exception as exc:
                record = registry.create_record(
                    run_id=f"failed_{index}",
                    spec=spec,
                    metrics={},
                    artifacts=[],
                    status="failed",
                    error=str(exc),
                )
            registry.register(record)
            records.append(record)
        best_rows = registry.compare(metric=compare_metric, experiment_name=config.experiment_name)
        return SweepResult(experiment_name=config.experiment_name, records=records, best=best_rows[0] if best_rows else None)
