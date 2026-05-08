"""Research experiment manifest and candidate management.

This module defines the core dataclasses and manager for the Strategy Research Lab.
Experiments are created, run, and optionally promoted to StrategyCandidates.
All data is persisted as JSON under data/research/experiments/ and data/research/candidates/.

Research code MUST NOT import from quant_us.live or quant_us.execution.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
import json
from pathlib import Path
from typing import Any

from quant_us.core.clock import utc_now
from quant_us.core.types import new_id


@dataclass
class ResearchExperimentManifest:
    """Complete specification of a single research experiment, persisted as JSON."""

    experiment_id: str
    strategy_id: str
    strategy_version: str = ""
    strategy_family: str = ""  # e.g. momentum, mean_reversion, trend
    symbols: list[str] = field(default_factory=list)
    universe: str = "v1"
    timeframe: str = "1d"
    start_date: str = ""
    end_date: str = ""
    train_period: str = ""
    test_period: str = ""
    walk_forward_config: dict = field(default_factory=dict)
    params: dict = field(default_factory=dict)
    param_grid: dict = field(default_factory=dict)
    data_version: str = ""
    feature_version: str = ""
    cost_model: str = "default"
    slippage_model: str = "default"
    created_at: str = ""
    status: str = "DRAFT"  # DRAFT|RUNNING|COMPLETED|FAILED|PROMOTED_TO_CANDIDATE|REJECTED

    # Runtime fields populated after run()
    run_result_path: str = ""
    metrics: dict = field(default_factory=dict)


@dataclass
class StrategyCandidate:
    """A research finding that has been promoted from an experiment for further review."""

    candidate_id: str
    experiment_id: str
    strategy_id: str
    params_hash: str = ""
    data_version: str = ""
    backtest_result_path: str = ""
    walk_forward_result_path: str = ""
    robustness_score: float = 0.0
    overfit_score: float = 0.0
    alpha_score: float = 0.0
    risk_score: float = 0.0
    turnover_score: float = 0.0
    promotion_status: str = "RESEARCH_ONLY"  # RESEARCH_ONLY|CANDIDATE|PAPER_ELIGIBLE|REJECTED
    created_at: str = ""
    metrics: dict = field(default_factory=dict)


class ExperimentManager:
    """Orchestrates the experiment lifecycle: create, run, promote, load, list.

    All experiments are persisted as JSON manifests under:
        data/research/experiments/<experiment_id>/manifest.json

    Candidates are stored under:
        data/research/candidates/<candidate_id>/candidate.json

    This manager uses the canonical UnifiedBacktestRunner for backtesting
    and the strategy factory for building strategies.
    """

    def __init__(self, data_root: str = "data") -> None:
        self.data_root = Path(data_root)
        self.experiments_dir = self.data_root / "research" / "experiments"
        self.candidates_dir = self.data_root / "research" / "candidates"
        self.experiments_dir.mkdir(parents=True, exist_ok=True)
        self.candidates_dir.mkdir(parents=True, exist_ok=True)

    def create(
        self,
        strategy_id: str,
        symbols: list[str],
        params: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> ResearchExperimentManifest:
        """Create a new experiment in DRAFT status.

        Args:
            strategy_id: Registered strategy ID (e.g. 'trend_momentum').
            symbols: List of ticker symbols.
            params: Strategy parameters.
            **kwargs: Additional fields for ResearchExperimentManifest.

        Returns:
            The created manifest (persisted to disk).
        """
        experiment_id = new_id("exp")
        manifest = ResearchExperimentManifest(
            experiment_id=experiment_id,
            strategy_id=strategy_id,
            symbols=symbols,
            params=params or {},
            created_at=utc_now().isoformat(),
            **kwargs,
        )
        self._save_manifest(manifest)
        return manifest

    def run(self, experiment_id: str) -> dict[str, Any]:
        """Run a backtest for the given experiment.

        Loads market data from the data lake, builds the strategy,
        runs through UnifiedBacktestRunner, and saves results.

        Args:
            experiment_id: The experiment to run.

        Returns:
            Summary metrics dict from the backtest.

        Raises:
            ValueError: If the experiment is not found.
        """
        manifest = self.load(experiment_id)
        if manifest is None:
            raise ValueError(f"Experiment {experiment_id} not found")

        manifest.status = "RUNNING"
        self._save_manifest(manifest)

        try:
            import pandas as pd

            from quant_us.backtest.data_bridge import bars_from_dataframe
            from quant_us.backtest.unified_runner import UnifiedBacktestConfig, UnifiedBacktestRunner
            from quant_us.data.lake.data_lake import DataLakeConfig, DataLakeService
            from quant_us.strategies.factory import build_strategy

            # Parse dates
            start = (
                datetime.fromisoformat(manifest.start_date)
                if manifest.start_date
                else datetime(2020, 1, 1)
            )
            end = datetime.fromisoformat(manifest.end_date) if manifest.end_date else utc_now()

            # Load market data
            lake = DataLakeService(DataLakeConfig(data_root=self.data_root))
            frames: list[pd.DataFrame] = []
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
                    frames.append(df)

            if not frames:
                raise ValueError(f"No data loaded for experiment {experiment_id}")

            frame = pd.concat(frames, ignore_index=True)

            # Build strategy
            strategy = build_strategy(manifest.strategy_id, manifest.params)

            # Run canonical backtest
            runner = UnifiedBacktestRunner()
            result = runner.run(
                strategies=[strategy],
                frame=frame,
                data_version=manifest.data_version,
                strategy_version=manifest.strategy_version,
            )

            summary = result.summary

            # Persist run result
            result_path = self.experiments_dir / experiment_id / "run_result.json"
            result_path.parent.mkdir(parents=True, exist_ok=True)
            result_path.write_text(
                json.dumps(summary, indent=2, default=str), encoding="utf-8"
            )

            # Update manifest
            manifest.status = "COMPLETED"
            manifest.run_result_path = str(result_path)
            manifest.metrics = summary
            self._save_manifest(manifest)

            return summary

        except Exception:
            manifest.status = "FAILED"
            self._save_manifest(manifest)
            raise

    def promote_to_candidate(self, experiment_id: str) -> StrategyCandidate:
        """Promote a completed experiment to a StrategyCandidate (manual action only).

        This does NOT promote to paper or live — only to RESEARCH_ONLY/CANDIDATE status.
        The promotion_status remains RESEARCH_ONLY by default.

        Args:
            experiment_id: The completed experiment to promote.

        Returns:
            The created StrategyCandidate.

        Raises:
            ValueError: If the experiment is not found or not COMPLETED.
        """
        manifest = self.load(experiment_id)
        if manifest is None:
            raise ValueError(f"Experiment {experiment_id} not found")
        if manifest.status != "COMPLETED":
            raise ValueError(
                f"Cannot promote experiment with status {manifest.status} "
                "(must be COMPLETED)"
            )

        candidate_id = new_id("cand")
        candidate = StrategyCandidate(
            candidate_id=candidate_id,
            experiment_id=experiment_id,
            strategy_id=manifest.strategy_id,
            data_version=manifest.data_version,
            backtest_result_path=manifest.run_result_path,
            metrics=manifest.metrics,
            created_at=utc_now().isoformat(),
        )

        self._save_candidate(candidate)

        manifest.status = "PROMOTED_TO_CANDIDATE"
        self._save_manifest(manifest)

        return candidate

    def load(self, experiment_id: str) -> ResearchExperimentManifest | None:
        """Load an experiment manifest from disk.

        Returns None if the experiment does not exist.
        """
        path = self.experiments_dir / experiment_id / "manifest.json"
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return ResearchExperimentManifest(**data)

    def list_experiments(
        self, status: str | None = None
    ) -> list[ResearchExperimentManifest]:
        """List all experiments, optionally filtered by status.

        Results are sorted by created_at descending.
        """
        if not self.experiments_dir.exists():
            return []

        results: list[ResearchExperimentManifest] = []
        for d in sorted(self.experiments_dir.iterdir()):
            if not d.is_dir():
                continue
            manifest_path = d / "manifest.json"
            if not manifest_path.exists():
                continue
            manifest = ResearchExperimentManifest(
                **json.loads(manifest_path.read_text(encoding="utf-8"))
            )
            if status is None or manifest.status == status:
                results.append(manifest)

        results.sort(key=lambda m: m.created_at, reverse=True)
        return results

    def list_candidates(self) -> list[StrategyCandidate]:
        """List all candidates sorted by created_at descending."""
        if not self.candidates_dir.exists():
            return []

        results: list[StrategyCandidate] = []
        for d in sorted(self.candidates_dir.iterdir()):
            if not d.is_dir():
                continue
            cand_path = d / "candidate.json"
            if not cand_path.exists():
                continue
            results.append(
                StrategyCandidate(**json.loads(cand_path.read_text(encoding="utf-8")))
            )

        results.sort(key=lambda c: c.created_at, reverse=True)
        return results

    # ------------------------------------------------------------------
    # Internal persistence helpers
    # ------------------------------------------------------------------

    def _save_manifest(self, manifest: ResearchExperimentManifest) -> None:
        path = self.experiments_dir / manifest.experiment_id / "manifest.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(asdict(manifest), indent=2, default=str), encoding="utf-8"
        )

    def _save_candidate(self, candidate: StrategyCandidate) -> None:
        path = self.candidates_dir / candidate.candidate_id / "candidate.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(asdict(candidate), indent=2, default=str), encoding="utf-8"
        )
