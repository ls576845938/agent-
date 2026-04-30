from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from quant_us.core.clock import utc_now
from quant_us.core.types import new_id


@dataclass(frozen=True)
class DatasetSpec:
    dataset_name: str = "bar_factor_forward_return"
    feature_names: tuple[str, ...] = ("momentum_score", "realized_vol_20", "average_dollar_volume_20")
    feature_version: str = "v1"
    universe: str = "default"
    label_horizon_bars: int = 5
    train_end: date | None = None
    validation_end: date | None = None
    drop_missing_features: bool = True


@dataclass(frozen=True)
class DatasetBuildResult:
    run_id: str
    status: str
    rows_written: int
    columns: list[str]
    dataset_path: str
    manifest_path: str
    created_at: datetime
    error: str | None = None


class MLFeatureDatasetBuilder:
    def __init__(self, output_root: str | Path = "data/ml_datasets") -> None:
        self.output_root = Path(output_root)

    def build_from_bars_and_factors(
        self,
        bars: pd.DataFrame,
        factor_values: pd.DataFrame,
        spec: DatasetSpec | None = None,
    ) -> DatasetBuildResult:
        run_id = new_id("ds")
        created_at = utc_now()
        dataset_spec = spec or DatasetSpec()
        try:
            dataset = self._build_dataset_frame(bars, factor_values, dataset_spec)
            if dataset.empty:
                return DatasetBuildResult(run_id, "completed", 0, [], "", "", created_at)

            base = self.output_root / f"dataset={dataset_spec.dataset_name}" / f"version={dataset_spec.feature_version}" / f"run_id={run_id}"
            base.mkdir(parents=True, exist_ok=True)
            dataset_path = base / "dataset.parquet"
            manifest_path = base / "manifest.json"
            dataset.to_parquet(dataset_path, index=False)
            manifest_path.write_text(
                json.dumps(self._manifest(run_id, created_at, dataset, dataset_spec), indent=2, sort_keys=True),
                encoding="utf-8",
            )
            return DatasetBuildResult(
                run_id=run_id,
                status="completed",
                rows_written=len(dataset),
                columns=list(dataset.columns),
                dataset_path=str(dataset_path),
                manifest_path=str(manifest_path),
                created_at=created_at,
            )
        except Exception as exc:
            return DatasetBuildResult(run_id, "failed", 0, [], "", "", created_at, error=str(exc))

    def _build_dataset_frame(self, bars: pd.DataFrame, factor_values: pd.DataFrame, spec: DatasetSpec) -> pd.DataFrame:
        if bars.empty or factor_values.empty:
            return pd.DataFrame()
        if spec.label_horizon_bars <= 0:
            raise ValueError("label_horizon_bars must be positive")

        bar_frame = bars.copy()
        bar_frame["timestamp_utc"] = pd.to_datetime(bar_frame["timestamp_utc"], utc=True)
        bar_frame["symbol"] = bar_frame["symbol"].astype(str).str.upper()
        bar_frame["date"] = bar_frame["timestamp_utc"].dt.date
        bar_frame = bar_frame.sort_values(["symbol", "timestamp_utc"])
        label_column = f"forward_return_{spec.label_horizon_bars}b"
        bar_frame[label_column] = (
            bar_frame.groupby("symbol")["close"].shift(-spec.label_horizon_bars).astype(float) / bar_frame["close"].astype(float) - 1.0
        )
        labels = bar_frame[["date", "timestamp_utc", "symbol", "close", label_column]]

        factor_frame = factor_values.copy()
        factor_frame["symbol"] = factor_frame["symbol"].astype(str).str.upper()
        factor_frame["date"] = pd.to_datetime(factor_frame["date"]).dt.date
        if "version" in factor_frame.columns:
            factor_frame = factor_frame[factor_frame["version"] == spec.feature_version]
        if "universe" in factor_frame.columns:
            factor_frame = factor_frame[factor_frame["universe"] == spec.universe]
        factor_frame = factor_frame[factor_frame["factor_name"].isin(spec.feature_names)]
        if factor_frame.empty:
            return pd.DataFrame()

        features = (
            factor_frame.pivot_table(index=["date", "symbol"], columns="factor_name", values="factor_value", aggfunc="last")
            .reset_index()
            .rename_axis(None, axis=1)
        )
        feature_columns = [name for name in spec.feature_names if name in features.columns]
        if not feature_columns:
            return pd.DataFrame()

        dataset = labels.merge(features, on=["date", "symbol"], how="inner")
        dataset = dataset.dropna(subset=[label_column])
        if spec.drop_missing_features:
            dataset = dataset.dropna(subset=feature_columns)
        dataset = dataset.sort_values(["date", "symbol"]).reset_index(drop=True)
        if dataset.empty:
            return dataset

        dataset["split"] = self._assign_splits(dataset["date"], spec)
        dataset["feature_version"] = spec.feature_version
        dataset["universe"] = spec.universe
        dataset["label_horizon_bars"] = spec.label_horizon_bars
        return dataset

    def _assign_splits(self, dates: pd.Series, spec: DatasetSpec) -> list[str]:
        unique_dates = sorted(pd.Series(dates).dropna().unique())
        if not unique_dates:
            return []
        train_end = spec.train_end
        validation_end = spec.validation_end
        if train_end is None or validation_end is None:
            train_idx = max(0, int(len(unique_dates) * 0.6) - 1)
            validation_idx = max(train_idx, int(len(unique_dates) * 0.8) - 1)
            train_end = train_end or unique_dates[train_idx]
            validation_end = validation_end or unique_dates[validation_idx]
        if validation_end < train_end:
            raise ValueError("validation_end must be on or after train_end")
        return ["train" if item <= train_end else "validation" if item <= validation_end else "test" for item in dates]

    def _manifest(self, run_id: str, created_at: datetime, dataset: pd.DataFrame, spec: DatasetSpec) -> dict[str, object]:
        split_counts = {str(key): int(value) for key, value in dataset["split"].value_counts().sort_index().items()}
        spec_payload = asdict(spec)
        spec_payload["feature_names"] = list(spec.feature_names)
        spec_payload["train_end"] = None if spec.train_end is None else spec.train_end.isoformat()
        spec_payload["validation_end"] = None if spec.validation_end is None else spec.validation_end.isoformat()
        return {
            "run_id": run_id,
            "created_at": created_at.isoformat(),
            "spec": spec_payload,
            "rows": int(len(dataset)),
            "columns": list(dataset.columns),
            "symbols": sorted(str(symbol) for symbol in dataset["symbol"].unique()),
            "date_start": str(dataset["date"].min()),
            "date_end": str(dataset["date"].max()),
            "split_counts": split_counts,
        }
