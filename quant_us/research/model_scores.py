from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from quant_us.core.clock import utc_now
from quant_us.core.types import new_id
from quant_us.data.storage.feature_store import ParquetFeatureStore
from quant_us.research.experiments import ExperimentRegistry, ModelArtifact


@dataclass(frozen=True)
class LinearModelSpec:
    model_id: str
    feature_names: list[str]
    weights: dict[str, float]
    intercept: float = 0.0
    score_name: str = "model_score"
    score_version: str = ""
    feature_version: str = ""
    dataset_run_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ModelScoreResult:
    run_id: str
    status: str
    model_id: str
    score_name: str
    score_version: str
    rows_written: int
    files_written: list[str]
    model_path: str
    model_manifest_path: str
    created_at: datetime
    error: str | None = None


class LinearModelScoreBuilder:
    def __init__(
        self,
        feature_root: str | Path = "data/features",
        model_root: str | Path = "data/models",
        registry: ExperimentRegistry | None = None,
    ) -> None:
        self.feature_store = ParquetFeatureStore(feature_root)
        self.model_root = Path(model_root)
        self.registry = registry

    def score_dataset(
        self,
        dataset_path: str | Path,
        spec: LinearModelSpec,
        universe: str = "default",
        split: str = "",
    ) -> ModelScoreResult:
        run_id = new_id("score")
        created_at = utc_now()
        score_version = spec.score_version or spec.model_id
        try:
            dataset = pd.read_parquet(dataset_path)
            scored = self._score_frame(dataset, spec, universe=universe, split=split, created_at=created_at)
            write = self.feature_store.write_factor_values(scored, version=score_version)
            model_path = self._write_model_spec(spec)
            manifest_path = ""
            if self.registry is not None:
                manifest_path = str(
                    self.registry.register_model(
                        ModelArtifact(
                            model_id=spec.model_id,
                            model_type="linear",
                            path=str(model_path),
                            feature_names=spec.feature_names,
                            feature_version=spec.feature_version,
                            dataset_run_id=spec.dataset_run_id,
                            metadata={
                                **spec.metadata,
                                "score_name": spec.score_name,
                                "score_version": score_version,
                                "intercept": spec.intercept,
                            },
                        )
                    )
                )
            return ModelScoreResult(
                run_id=run_id,
                status="completed",
                model_id=spec.model_id,
                score_name=spec.score_name,
                score_version=score_version,
                rows_written=write.rows_written,
                files_written=[str(path) for path in write.files_written],
                model_path=str(model_path),
                model_manifest_path=manifest_path,
                created_at=created_at,
            )
        except Exception as exc:
            return ModelScoreResult(
                run_id=run_id,
                status="failed",
                model_id=spec.model_id,
                score_name=spec.score_name,
                score_version=score_version,
                rows_written=0,
                files_written=[],
                model_path="",
                model_manifest_path="",
                created_at=created_at,
                error=str(exc),
            )

    def _score_frame(self, dataset: pd.DataFrame, spec: LinearModelSpec, universe: str, split: str, created_at: datetime) -> pd.DataFrame:
        if dataset.empty:
            return pd.DataFrame()
        missing = [name for name in spec.feature_names if name not in dataset.columns]
        if missing:
            raise ValueError(f"Missing model feature columns: {missing}")
        if split:
            if "split" not in dataset.columns:
                raise ValueError("Dataset does not contain split column")
            dataset = dataset[dataset["split"] == split]
        if dataset.empty:
            return pd.DataFrame()

        working = dataset.copy()
        score = pd.Series(spec.intercept, index=working.index, dtype="float64")
        for name in spec.feature_names:
            score += pd.to_numeric(working[name], errors="coerce").fillna(0.0) * float(spec.weights.get(name, 0.0))
        output = pd.DataFrame(
            {
                "date": pd.to_datetime(working["date"]).dt.date,
                "symbol": working["symbol"].astype(str).str.upper(),
                "factor_name": spec.score_name,
                "factor_value": score.astype(float),
                "universe": universe,
                "version": spec.score_version or spec.model_id,
                "created_at": created_at,
            }
        )
        return output.dropna(subset=["factor_value"])

    def _write_model_spec(self, spec: LinearModelSpec) -> Path:
        path = self.model_root / f"model_id={spec.model_id}" / "linear_model.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(spec), indent=2, sort_keys=True), encoding="utf-8")
        return path
