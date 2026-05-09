"""Bridge between ExperimentManager (lab/manifest.py) and ExperimentRegistry (experiments.py).

Syncs experiments from the lab ExperimentManager into the ExperimentRegistry format
so that both systems can coexist and share data.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from quant_us.research.experiments import (
    ArtifactRef,
    ExperimentRecord,
    ExperimentRegistry,
    ExperimentSpec,
    _to_jsonable,
)
from quant_us.research.lab.manifest import ExperimentManager


class RegistryBridge:
    """Bridges ExperimentManager (lab) with ExperimentRegistry (experiments.py).

    Provides a single sync() call that reads all completed experiments from the
    ExperimentManager's persisted manifests and registers them as ExperimentRecords
    in the ExperimentRegistry.
    """

    def __init__(self, data_root: str = "data") -> None:
        self.manager = ExperimentManager(data_root)
        self.registry = ExperimentRegistry(root=str(Path(data_root) / "experiments"))

    def sync(self, experiment_id: str | None = None) -> list[dict[str, Any]]:
        """Sync experiments from the lab manager into the registry.

        Args:
            experiment_id: Optional single experiment to sync. If None, syncs all.

        Returns:
            List of synced record dicts.
        """
        if experiment_id:
            manifests = [self.manager.load(experiment_id)]
            manifests = [m for m in manifests if m is not None]
        else:
            manifests = self.manager.list_experiments()

        synced: list[dict[str, Any]] = []
        for manifest in manifests:
            if not self._should_sync(manifest):
                continue
            record = self._build_record(manifest)
            self.registry.register(record)
            synced.append(asdict(record))

        return synced

    def sync_candidate(
        self, candidate_id: str
    ) -> dict[str, Any] | None:
        """Sync a single candidate into the registry as an experiment record.

        Args:
            candidate_id: The candidate to sync.

        Returns:
            The synced record dict, or None if not found.
        """
        from quant_us.research.lab.manifest import StrategyCandidate

        candidate = self.manager._load_candidate(candidate_id)
        if candidate is None:
            return None

        spec = ExperimentSpec(
            experiment_name=f"candidate_{candidate.strategy_id}",
            run_type="candidate_sync",
            symbols=[],
            start=datetime.min,
            end=datetime.min,
            strategy_id=candidate.strategy_id,
            promotion_decision=candidate.promotion_status,
            promotion_stage="candidate",
            parameters=candidate.metrics,
            tags=["synced_from_candidate"],
        )
        record = self.registry.create_record(
            run_id=candidate.candidate_id,
            spec=spec,
            metrics=_extract_metrics(candidate.metrics),
            artifacts=[],
            status="completed",
        )
        self.registry.register(record)
        return asdict(record)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _should_sync(manifest: Any) -> bool:
        """Only sync experiments that are in a terminal or runnable state."""
        return manifest.status in {
            "COMPLETED",
            "FAILED",
            "PROMOTED_TO_CANDIDATE",
            "ARCHIVED",
        }

    @staticmethod
    def _build_record(manifest: Any) -> ExperimentRecord:
        """Build an ExperimentRecord from a ResearchExperimentManifest."""
        created = _parse_dt(manifest.created_at)
        spec = ExperimentSpec(
            experiment_name=manifest.strategy_id,
            run_type="backtest",
            symbols=list(manifest.symbols),
            start=_parse_dt(manifest.start_date) if manifest.start_date else datetime.min,
            end=_parse_dt(manifest.end_date) if manifest.end_date else datetime.min,
            strategy_id=manifest.strategy_id,
            strategy_version=manifest.strategy_version,
            data_version=manifest.data_version,
            feature_version=manifest.feature_version,
            parameters=dict(manifest.params),
            tags=[manifest.strategy_family] if manifest.strategy_family else [],
            notes=f"Synced from lab experiment {manifest.experiment_id}",
        )

        run_result_path = manifest.run_result_path or ""
        artifacts = (
            [
                ArtifactRef(
                    name="run_result",
                    path=run_result_path,
                    artifact_type="json",
                )
            ]
            if run_result_path
            else []
        )

        metrics_dict = _extract_metrics(manifest.metrics)

        return ExperimentRecord(
            experiment_id=manifest.experiment_id,
            run_id=manifest.experiment_id,
            status=manifest.status.lower() if manifest.status else "unknown",
            spec=spec,
            metrics=metrics_dict,
            artifacts=artifacts,
            created_at=created,
            completed_at=created,
            error=None,
        )


def _parse_dt(value: str) -> datetime:
    """Parse an ISO datetime string, with lenient fallback."""
    if not value:
        return datetime.min
    try:
        return datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return datetime.min


def _extract_metrics(metrics: Any) -> dict[str, float | int]:
    """Extract numeric metrics from a metrics dict, filtering out non-numeric."""
    result: dict[str, float | int] = {}
    if not isinstance(metrics, dict):
        return result
    for key, value in metrics.items():
        if isinstance(value, (float, int)):
            result[str(key)] = value
    return result
