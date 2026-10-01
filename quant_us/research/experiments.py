from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime
import json
from pathlib import Path
from typing import Any

from quant_us.core.clock import utc_now
from quant_us.core.types import new_id


@dataclass(frozen=True)
class ArtifactRef:
    name: str
    path: str
    artifact_type: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExperimentSpec:
    experiment_name: str
    run_type: str
    symbols: list[str]
    start: datetime
    end: datetime
    strategy_id: str = ""
    strategy_version: str = ""
    data_vendor: str = "yfinance"
    asset_class: str = "equity"
    bar_size: str = "1d"
    feature_version: str = ""
    data_version: str = ""
    dataset_run_id: str = ""
    model_id: str = ""
    promotion_decision: str = ""
    promotion_stage: str = ""
    promotion_manifest_id: str = ""
    parameters: dict[str, Any] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    notes: str = ""


@dataclass(frozen=True)
class ExperimentRecord:
    experiment_id: str
    run_id: str
    status: str
    spec: ExperimentSpec
    metrics: dict[str, float | int]
    artifacts: list[ArtifactRef]
    created_at: datetime
    completed_at: datetime | None = None
    error: str | None = None


@dataclass(frozen=True)
class ModelArtifact:
    model_id: str
    model_type: str
    path: str
    feature_names: list[str]
    feature_version: str
    dataset_run_id: str
    metrics: dict[str, float | int] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utc_now)
    metadata: dict[str, Any] = field(default_factory=dict)


class ExperimentRegistry:
    def __init__(self, root: str | Path = "data/experiments") -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.index_path = self.root / "index.jsonl"

    def create_record(
        self,
        run_id: str,
        spec: ExperimentSpec,
        metrics: dict[str, float | int],
        artifacts: list[ArtifactRef],
        status: str = "completed",
        error: str | None = None,
    ) -> ExperimentRecord:
        now = utc_now()
        return ExperimentRecord(
            experiment_id=new_id("exp"),
            run_id=run_id,
            status=status,
            spec=spec,
            metrics=metrics,
            artifacts=artifacts,
            created_at=now,
            completed_at=now if status in {"completed", "failed"} else None,
            error=error,
        )

    def register(self, record: ExperimentRecord) -> Path:
        record_dir = self.root / f"experiment={record.spec.experiment_name}" / f"run_id={record.run_id}"
        record_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = record_dir / "manifest.json"
        payload = _to_jsonable(record)
        manifest_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        with self.index_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True) + "\n")
        return manifest_path

    def register_model(self, artifact: ModelArtifact) -> Path:
        model_dir = self.root / "models" / f"model_id={artifact.model_id}"
        model_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = model_dir / "model.json"
        manifest_path.write_text(json.dumps(_to_jsonable(artifact), indent=2, sort_keys=True), encoding="utf-8")
        return manifest_path

    def load_records(self, experiment_name: str | None = None) -> list[dict[str, Any]]:
        if not self.index_path.exists():
            return []
        records = [json.loads(line) for line in self.index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if experiment_name:
            records = [record for record in records if record.get("spec", {}).get("experiment_name") == experiment_name]
        return records

    def compare(
        self,
        metric: str = "sharpe_ratio",
        experiment_name: str | None = None,
        descending: bool = True,
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for record in self.load_records(experiment_name):
            metrics = record.get("metrics", {})
            if metric not in metrics:
                continue
            spec = record.get("spec", {})
            rows.append(
                {
                    "experiment_id": record.get("experiment_id", ""),
                    "run_id": record.get("run_id", ""),
                    "experiment_name": spec.get("experiment_name", ""),
                    "run_type": spec.get("run_type", ""),
                    "strategy_id": spec.get("strategy_id", ""),
                    "strategy_version": spec.get("strategy_version", ""),
                    "symbols": spec.get("symbols", []),
                    "status": record.get("status", ""),
                    "data_version": spec.get("data_version", ""),
                    "promotion_decision": spec.get("promotion_decision", ""),
                    "promotion_stage": spec.get("promotion_stage", ""),
                    "promotion_manifest_id": spec.get("promotion_manifest_id", ""),
                    metric: metrics.get(metric),
                    "total_return_pct": metrics.get("total_return_pct"),
                    "max_drawdown_pct": metrics.get("max_drawdown_pct"),
                    "created_at": record.get("created_at", ""),
                }
            )
        return sorted(rows, key=lambda row: float(row.get(metric) or 0.0), reverse=descending)


def _to_jsonable(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return _to_jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(key): _to_jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple | set):
        return [_to_jsonable(item) for item in value]
    if isinstance(value, datetime | date):
        return value.isoformat()
    return value
