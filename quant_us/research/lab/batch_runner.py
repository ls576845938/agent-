"""Batch backtest runner for the Strategy Research Lab.

Runs multiple experiments in batch, parameter sweeps, and multi-symbol
variants. Uses the canonical UnifiedBacktestRunner under the hood.
"""

from __future__ import annotations

import json
from itertools import product
from pathlib import Path
from typing import Any

import pandas as pd

from quant_us.research.lab.manifest import ExperimentManager


class BatchBacktestRunner:
    """Run multiple experiments in batch.

    All backtests go through ExperimentManager.run(), which uses the
    canonical UnifiedBacktestRunner under the hood.
    """

    def __init__(self, data_root: str = "data") -> None:
        self.data_root = data_root
        self.exp_manager = ExperimentManager(data_root)

    def run_experiments(self, experiment_ids: list[str]) -> list[dict[str, Any]]:
        """Run multiple experiments sequentially.

        Args:
            experiment_ids: List of experiment IDs to run.

        Returns:
            List of result dicts with experiment_id, status, and metrics.
        """
        results: list[dict[str, Any]] = []
        for eid in experiment_ids:
            try:
                summary = self.exp_manager.run(eid)
                results.append(
                    {"experiment_id": eid, "status": "COMPLETED", "metrics": summary}
                )
            except Exception as exc:
                results.append(
                    {"experiment_id": eid, "status": "FAILED", "error": str(exc)}
                )
        return results

    def run_parameter_sweep(
        self, experiment_id: str, param_grid: dict[str, list[Any] | Any]
    ) -> list[dict[str, Any]]:
        """Run a parameter sweep from a base experiment.

        Creates a new experiment for each combination in the grid and runs them all.

        Args:
            experiment_id: Base experiment to derive the sweep from.
            param_grid: Dict of param_name -> list of values to sweep.

        Returns:
            List of result dicts with experiment_id, params, and metrics.
        """
        manifest = self.exp_manager.load(experiment_id)
        if manifest is None:
            raise ValueError(f"Experiment {experiment_id} not found")

        keys = list(param_grid)
        values = [v if isinstance(v, list) else [v] for v in param_grid.values()]

        results: list[dict[str, Any]] = []
        for combo in product(*values):
            params = dict(zip(keys, combo))
            merged: dict[str, Any] = {**manifest.params, **params}

            sweep_exp = self.exp_manager.create(
                strategy_id=manifest.strategy_id,
                symbols=list(manifest.symbols),
                params=merged,
                strategy_family=manifest.strategy_family,
                timeframe=manifest.timeframe,
                start_date=manifest.start_date,
                end_date=manifest.end_date,
                data_version=manifest.data_version,
                feature_version=manifest.feature_version,
            )

            try:
                summary = self.exp_manager.run(sweep_exp.experiment_id)
                results.append(
                    {
                        "experiment_id": sweep_exp.experiment_id,
                        "params": params,
                        "metrics": summary,
                    }
                )
            except Exception as exc:
                results.append(
                    {
                        "experiment_id": sweep_exp.experiment_id,
                        "params": params,
                        "status": "FAILED",
                        "error": str(exc),
                    }
                )

        return results

    def run_multi_symbol(
        self, experiment_id: str, symbols: list[str]
    ) -> list[dict[str, Any]]:
        """Run the same experiment across different symbols.

        Creates a separate experiment for each symbol.

        Args:
            experiment_id: Base experiment to derive variants from.
            symbols: List of symbols to run individually.

        Returns:
            List of result dicts with experiment_id, symbol, and metrics.
        """
        manifest = self.exp_manager.load(experiment_id)
        if manifest is None:
            raise ValueError(f"Experiment {experiment_id} not found")

        results: list[dict[str, Any]] = []
        for sym in symbols:
            sym_exp = self.exp_manager.create(
                strategy_id=manifest.strategy_id,
                symbols=[sym],
                params=dict(manifest.params),
                strategy_family=manifest.strategy_family,
                timeframe=manifest.timeframe,
                start_date=manifest.start_date,
                end_date=manifest.end_date,
                data_version=manifest.data_version,
                feature_version=manifest.feature_version,
            )

            try:
                summary = self.exp_manager.run(sym_exp.experiment_id)
                results.append(
                    {
                        "experiment_id": sym_exp.experiment_id,
                        "symbol": sym,
                        "metrics": summary,
                    }
                )
            except Exception as exc:
                results.append(
                    {
                        "experiment_id": sym_exp.experiment_id,
                        "symbol": sym,
                        "status": "FAILED",
                        "error": str(exc),
                    }
                )

        return results

    def cache_features(self, experiment_id: str) -> str:
        """Pre-compute and cache feature data for an experiment.

        Loads cleaned bars for the experiment's symbols and saves them
        as Parquet files under data/research/feature_cache/<experiment_id>/.

        Args:
            experiment_id: The experiment to cache features for.

        Returns:
            Path string to the cache directory.

        Raises:
            ValueError: If the experiment is not found.
        """
        manifest = self.exp_manager.load(experiment_id)
        if manifest is None:
            raise ValueError(f"Experiment {experiment_id} not found")

        from datetime import datetime

        from quant_us.data.lake.data_lake import DataLakeConfig, DataLakeService

        start = (
            datetime.fromisoformat(manifest.start_date)
            if manifest.start_date
            else datetime(2020, 1, 1)
        )
        end = datetime.fromisoformat(manifest.end_date) if manifest.end_date else datetime.now()

        lake = DataLakeService(DataLakeConfig(data_root=Path(self.data_root)))
        cache_dir = Path(self.data_root) / "research" / "feature_cache" / experiment_id
        cache_dir.mkdir(parents=True, exist_ok=True)

        for sym in manifest.symbols:
            df = lake.read_cleaned_bars(
                symbol=sym,
                start=start,
                end=end,
                bar_size=manifest.timeframe,
                vendor="yfinance",
                asset_class="equity",
            )
            if not df.empty:
                path = cache_dir / f"{sym}.parquet"
                df.to_parquet(path)

        return str(cache_dir)
