"""Research experiment manifest and candidate management.

This module defines the core dataclasses and manager for the Strategy Research Lab.
Experiments are created, run, and optionally promoted to StrategyCandidates.
All data is persisted as JSON under data/research/experiments/ and data/research/candidates/.

Research code MUST NOT import from quant_us.live or quant_us.execution.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields, field
from datetime import datetime
import hashlib
import json
from pathlib import Path
from typing import Any

from quant_us.core.clock import utc_now
from quant_us.core.types import new_id


def _commission_rate_for_cost_model(cost_model: str) -> float:
    model = str(cost_model or "default").strip().lower()
    if model == "high":
        return 0.0005
    if model == "low":
        return 0.0
    return 0.0001


def _slippage_bps_for_model(slippage_model: str) -> float:
    model = str(slippage_model or "default").strip().lower()
    if model == "high":
        return 5.0
    if model == "low":
        return 0.0
    return 1.0


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
    backtest_manifest_path: str = ""
    ledger_artifact_path: str = ""
    ledger_artifact_hash: str = ""
    data_manifest_path: str = ""
    metrics: dict = field(default_factory=dict)


@dataclass
class StrategyCandidate:
    """A research finding that has been promoted from an experiment for further review."""

    candidate_id: str
    experiment_id: str
    strategy_id: str
    symbols: list[str] = field(default_factory=list)
    timeframe: str = "1d"
    data_source: str = "yfinance"
    asset_class: str = "equity"
    params_hash: str = ""
    data_version: str = ""
    backtest_result_path: str = ""
    backtest_manifest_path: str = ""
    ledger_artifact_path: str = ""
    ledger_artifact_hash: str = ""
    data_manifest_path: str = ""
    scorecard_path: str = ""
    walk_forward_result_path: str = ""
    cost_stress_result_path: str = ""
    robustness_score: float = 0.0
    overfit_score: float = 0.0
    alpha_score: float = 0.0
    risk_score: float = 0.0
    turnover_score: float = 0.0
    promotion_status: str = "RESEARCH_ONLY"  # RESEARCH_ONLY|CANDIDATE|PAPER_ELIGIBLE|REJECTED
    parent_candidate_id: str = ""  # for lineage tracking
    candidate_hash: str = ""  # SHA256 of (strategy_id + json.dumps(params, sort_keys=True))
    reject_reason: str = ""  # populated when REJECTED
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

            from quant_us.backtest.unified_runner import UnifiedBacktestConfig, UnifiedBacktestRunner
            from quant_us.data.pipeline import DataLakeConfig, DataLakeService
            from quant_us.data.storage.data_manifest import DataManifestStore
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
            features_frame: pd.DataFrame | None = None
            if manifest.strategy_id == "factor_rank":
                factor_name = str(
                    manifest.params.get("factor_name")
                    or manifest.params.get("factor_id")
                    or ""
                ).strip()
                if not factor_name:
                    raise ValueError(
                        "factor_rank experiment requires params.factor_name"
                    )
                from quant_us.factors.pipeline import FactorPipeline

                features_frame = FactorPipeline(
                    data_root=str(self.data_root)
                ).compute(
                    factor_ids=[factor_name],
                    symbols=manifest.symbols,
                    start=start.isoformat(),
                    end=end.isoformat(),
                    bar_size=manifest.timeframe,
                    timeframe=manifest.timeframe,
                )

            runner = UnifiedBacktestRunner(
                UnifiedBacktestConfig(
                    commission_rate=_commission_rate_for_cost_model(manifest.cost_model),
                    slippage_bps=_slippage_bps_for_model(manifest.slippage_model),
                )
            )
            runner.manifest_store = DataManifestStore(self.data_root / "manifests")
            result = runner.run(
                strategies=[strategy],
                frame=frame,
                features_frame=features_frame,
                data_version=manifest.data_version,
                strategy_version=manifest.strategy_version,
            )

            summary = dict(result.summary)
            evidence = dict(result.evidence)
            data_manifest = evidence.get("data_manifest", {})
            if not isinstance(data_manifest, dict):
                data_manifest = {}
            ledger_artifact_path = str(evidence.get("ledger_artifact_path", ""))
            ledger_artifact_hash = str(evidence.get("ledger_artifact_hash", ""))
            data_manifest_path = str(data_manifest.get("path", ""))
            summary.update(
                {
                    "engine": "event_driven",
                    "canonical_for_promotion": True,
                    "backtest_manifest_path": result.manifest_path,
                    "backtest_manifest_id": result.manifest_id,
                    "ledger_artifact_path": ledger_artifact_path,
                    "ledger_artifact_hash": ledger_artifact_hash,
                    "ledger_hash": str(evidence.get("ledger_hash", "")),
                    "fills_hash": str(evidence.get("fills_hash", "")),
                    "orders_hash": str(evidence.get("orders_hash", "")),
                    "data_manifest_path": data_manifest_path,
                    "data_manifest_exists": bool(evidence.get("data_manifest_exists", False)),
                    "missing_data_manifest": bool(evidence.get("missing_data_manifest", True)),
                    "data_version": manifest.data_version,
                    "cost_model": manifest.cost_model,
                    "slippage_model": manifest.slippage_model,
                    "ledger_consistency_pct": 100.0 if result.equity_consistent else 0.0,
                    "total_order_count": len(result.orders),
                    "total_fill_count": len(result.fills),
                    "baseline_order_count": len(result.orders),
                    "baseline_fill_count": len(result.fills),
                }
            )

            # Persist run result
            result_path = self.experiments_dir / experiment_id / "run_result.json"
            result_path.parent.mkdir(parents=True, exist_ok=True)
            result_path.write_text(
                json.dumps(summary, indent=2, default=str), encoding="utf-8"
            )

            # Update manifest
            manifest.status = "COMPLETED"
            manifest.run_result_path = str(result_path)
            manifest.backtest_manifest_path = result.manifest_path
            manifest.ledger_artifact_path = ledger_artifact_path
            manifest.ledger_artifact_hash = ledger_artifact_hash
            manifest.data_manifest_path = data_manifest_path
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
            symbols=list(manifest.symbols),
            timeframe=manifest.timeframe,
            data_source="yfinance",
            asset_class="equity",
            candidate_hash=self.compute_candidate_hash(
                manifest.strategy_id, manifest.params
            ),
            data_version=manifest.data_version,
            backtest_result_path=manifest.run_result_path,
            backtest_manifest_path="",
            ledger_artifact_path=manifest.ledger_artifact_path,
            ledger_artifact_hash=manifest.ledger_artifact_hash,
            data_manifest_path=manifest.data_manifest_path,
            scorecard_path=str(
                self.data_root
                / "research"
                / "scorecards"
                / f"{candidate_id}.json"
            ),
            walk_forward_result_path=str(
                self.data_root
                / "research"
                / "walk_forward"
                / candidate_id
                / "result.json"
            ),
            cost_stress_result_path=str(
                self.data_root
                / "research"
                / "cost_stress"
                / candidate_id
                / "result.json"
            ),
            metrics=manifest.metrics,
            created_at=utc_now().isoformat(),
        )
        if manifest.backtest_manifest_path:
            candidate.backtest_manifest_path = self._materialize_candidate_backtest_manifest(
                candidate=candidate,
                manifest=manifest,
            )
        candidate.metrics = {
            **dict(candidate.metrics),
            "backtest_manifest_path": candidate.backtest_manifest_path,
            "ledger_artifact_path": candidate.ledger_artifact_path,
            "ledger_artifact_hash": candidate.ledger_artifact_hash,
            "data_manifest_path": candidate.data_manifest_path,
            "scorecard_path": candidate.scorecard_path,
            "walk_forward_result_path": candidate.walk_forward_result_path,
            "cost_stress_result_path": candidate.cost_stress_result_path,
            "symbols": candidate.symbols,
            "timeframe": candidate.timeframe,
            "data_source": candidate.data_source,
            "asset_class": candidate.asset_class,
        }

        self._save_candidate(candidate)

        manifest.status = "PROMOTED_TO_CANDIDATE"
        self._save_manifest(manifest)

        return candidate

    def register_manifest(
        self,
        experiment_id: str,
        git_commit: str = "",
        data_version: str = "",
        config_hash: str = "",
        created_by: str = "",
    ) -> dict:
        """Generate a full experiment manifest with reproducibility metadata.

        Tries to get git_commit from subprocess, falls back to 'unknown'.
        Computes config_hash if not provided by hashing the experiment's config.
        Stores manifest alongside experiment data.

        Args:
            experiment_id: The experiment to register.
            git_commit: Git commit hash (auto-detected if empty).
            data_version: Data version string.
            config_hash: Config hash (auto-computed if empty).
            created_by: Who created the experiment.

        Returns:
            Dict containing the full manifest with reproducibility metadata.
        """
        manifest = self.load(experiment_id)
        if manifest is None:
            raise ValueError(f"Experiment {experiment_id} not found")

        if not git_commit:
            git_commit = self._detect_git_commit()

        if not config_hash:
            config_hash = hashlib.sha256(
                json.dumps(manifest.params, sort_keys=True).encode("utf-8")
            ).hexdigest()[:16]

        if manifest.data_version and not data_version:
            data_version = manifest.data_version

        full_manifest = {
            "experiment_id": manifest.experiment_id,
            "strategy_id": manifest.strategy_id,
            "strategy_version": manifest.strategy_version,
            "strategy_family": manifest.strategy_family,
            "symbols": manifest.symbols,
            "params": manifest.params,
            "param_grid": manifest.param_grid,
            "data_version": data_version,
            "feature_version": manifest.feature_version,
            "git_commit": git_commit,
            "config_hash": config_hash,
            "created_by": created_by,
            "created_at": manifest.created_at,
            "status": manifest.status,
            "metrics": manifest.metrics,
            "registered_at": utc_now().isoformat(),
        }

        # Persist alongside experiment data
        reg_path = self.experiments_dir / experiment_id / "manifest_registry.json"
        reg_path.parent.mkdir(parents=True, exist_ok=True)
        reg_path.write_text(
            json.dumps(full_manifest, indent=2, default=str), encoding="utf-8"
        )

        return full_manifest

    def archive_experiment(self, experiment_id: str) -> None:
        """Mark experiment as ARCHIVED. Does NOT delete data.

        Args:
            experiment_id: The experiment to archive.

        Raises:
            ValueError: If the experiment is not found.
        """
        manifest = self.load(experiment_id)
        if manifest is None:
            raise ValueError(f"Experiment {experiment_id} not found")
        manifest.status = "ARCHIVED"
        self._save_manifest(manifest)

    def get_manifest(self, experiment_id: str) -> dict | None:
        """Get experiment manifest with reproducibility metadata.

        Args:
            experiment_id: The experiment to inspect.

        Returns:
            Dict manifest if found, None otherwise.
        """
        manifest = self.load(experiment_id)
        if manifest is None:
            return None
        return asdict(manifest)

    def compare_experiments(
        self, experiment_ids: list[str], metric: str = "score"
    ) -> list[dict]:
        """Compare multiple experiments by a metric. Returns sorted list.

        Args:
            experiment_ids: List of experiment IDs to compare.
            metric: Metric key to sort by (default: 'score').

        Returns:
            List of dicts sorted by metric descending.
        """
        results: list[dict] = []
        for eid in experiment_ids:
            manifest = self.load(eid)
            if manifest is None:
                continue
            entry = {
                "experiment_id": manifest.experiment_id,
                "strategy_id": manifest.strategy_id,
                "status": manifest.status,
                "created_at": manifest.created_at,
            }
            if isinstance(manifest.metrics, dict):
                entry["metrics"] = manifest.metrics
                entry[metric] = manifest.metrics.get(metric, 0.0)
            else:
                entry["metrics"] = {}
                entry[metric] = 0.0
            results.append(entry)

        results.sort(key=lambda r: float(r.get(metric, 0.0) or 0.0), reverse=True)
        return results

    def get_lineage(self, candidate_id: str) -> dict:
        """Get the full lineage chain for a candidate.

        Traces parent chain upward and finds all children.

        Args:
            candidate_id: The candidate to trace.

        Returns:
            Dict with candidate_id, parent_candidate_id, children,
            experiment_id, generation_method, params.

        Raises:
            ValueError: If the candidate is not found.
        """
        candidate = self._load_candidate(candidate_id)
        if candidate is None:
            raise ValueError(f"Candidate {candidate_id} not found")

        children = self._find_children(candidate_id)

        return {
            "candidate_id": candidate.candidate_id,
            "parent_candidate_id": candidate.parent_candidate_id,
            "children": children,
            "experiment_id": candidate.experiment_id,
            "generation_method": candidate.promotion_status,
            "params": candidate.metrics,
        }

    def set_parent(self, child_id: str, parent_id: str) -> None:
        """Set parent-child relationship between candidates.

        Args:
            child_id: The child candidate ID.
            parent_id: The parent candidate ID.

        Raises:
            ValueError: If either candidate is not found.
        """
        child = self._load_candidate(child_id)
        if child is None:
            raise ValueError(f"Candidate {child_id} not found")
        parent = self._load_candidate(parent_id)
        if parent is None:
            raise ValueError(f"Parent candidate {parent_id} not found")

        child.parent_candidate_id = parent_id
        self._save_candidate(child)

    def deduplicate_candidates(self, experiment_id: str) -> dict:
        """Find and mark duplicate candidates.

        Two candidates are duplicates if they have the same candidate_hash
        (strategy_id + sorted params).

        Args:
            experiment_id: The experiment to check candidates for.

        Returns:
            Dict with total, duplicates_found, duplicates_marked, unique_remaining.
        """
        candidates = self.list_candidates()
        exp_candidates = [c for c in candidates if c.experiment_id == experiment_id]

        total = len(exp_candidates)
        seen_hashes: dict[str, list[StrategyCandidate]] = {}

        for c in exp_candidates:
            h = c.candidate_hash or self.compute_candidate_hash(c.strategy_id, c.metrics)
            if h not in seen_hashes:
                seen_hashes[h] = []
            seen_hashes[h].append(c)

        duplicates_found = 0
        duplicates_marked = 0

        for h, group in seen_hashes.items():
            if len(group) > 1:
                duplicates_found += len(group) - 1
                # Keep the first one, mark the rest
                for dup in group[1:]:
                    if dup.promotion_status != "REJECTED":
                        dup.promotion_status = "REJECTED"
                        dup.reject_reason = f"DUPLICATE of {group[0].candidate_id}"
                        self._save_candidate(dup)
                        duplicates_marked += 1

        unique_remaining = total - duplicates_marked
        return {
            "total": total,
            "duplicates_found": duplicates_found,
            "duplicates_marked": duplicates_marked,
            "unique_remaining": unique_remaining,
        }

    def compute_candidate_hash(self, strategy_id: str, params: dict) -> str:
        """SHA256 of strategy_id + sorted params JSON. Deterministic.

        Args:
            strategy_id: The strategy ID.
            params: Strategy parameters dict.

        Returns:
            Hex digest string (16 chars).
        """
        raw = strategy_id + json.dumps(params, sort_keys=True)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

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
                self._candidate_from_payload(
                    json.loads(cand_path.read_text(encoding="utf-8"))
                )
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

    def _materialize_candidate_backtest_manifest(
        self,
        *,
        candidate: StrategyCandidate,
        manifest: ResearchExperimentManifest,
    ) -> str:
        """Copy the run manifest to the promotion-gate canonical candidate path."""
        if not manifest.backtest_manifest_path:
            raise ValueError(
                "Cannot promote experiment without backtest_manifest_path evidence"
            )

        source_path = Path(manifest.backtest_manifest_path)
        if not source_path.exists():
            raise ValueError(
                f"Cannot promote experiment because backtest manifest is missing: {source_path}"
            )

        payload = json.loads(source_path.read_text(encoding="utf-8"))
        payload.update(
            {
                "candidate_id": candidate.candidate_id,
                "experiment_id": manifest.experiment_id,
                "strategy_id": manifest.strategy_id,
                "source_run_manifest_path": str(source_path),
                "canonical_backtest_manifest_path": str(
                    self._candidate_backtest_manifest_path(candidate.candidate_id)
                ),
                "cost_model_name": manifest.cost_model,
                "slippage_model_name": manifest.slippage_model,
            }
        )
        payload.setdefault("canonical_for_promotion", True)

        target_path = self._candidate_backtest_manifest_path(candidate.candidate_id)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True, default=str),
            encoding="utf-8",
        )
        return str(target_path)

    def _candidate_backtest_manifest_path(self, candidate_id: str) -> Path:
        return self.data_root / "research" / "backtests" / candidate_id / "run_manifest.json"

    def _load_candidate(self, candidate_id: str) -> StrategyCandidate | None:
        """Load a candidate from disk by ID."""
        path = self.candidates_dir / candidate_id / "candidate.json"
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return self._candidate_from_payload(data)

    def _find_children(self, candidate_id: str) -> list[str]:
        """Find all candidates that have the given candidate_id as parent."""
        children: list[str] = []
        for c in self.list_candidates():
            if c.parent_candidate_id == candidate_id:
                children.append(c.candidate_id)
        return children

    @staticmethod
    def _candidate_from_payload(data: dict[str, Any]) -> StrategyCandidate:
        """Load current and legacy candidate JSON without failing on extra keys."""
        allowed = {f.name for f in fields(StrategyCandidate)}
        return StrategyCandidate(
            **{key: value for key, value in data.items() if key in allowed}
        )

    @staticmethod
    def _detect_git_commit() -> str:
        """Detect current git commit hash. Returns 'unknown' on failure."""
        try:
            import subprocess
            result = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception:
            pass
        return "unknown"
