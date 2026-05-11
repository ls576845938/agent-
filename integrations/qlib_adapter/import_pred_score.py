from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path

import pandas as pd

from .schemas import (
    PredScoreImportResult,
    QlibAdapterError,
    build_run_paths,
    read_json,
    resolve_run_id,
    utc_now_iso,
    write_json,
)


def import_pred_score(
    *,
    run_id: str,
    artifacts_root: str | Path = "artifacts/qlib_runs",
    pred_score_path: str | Path | None = None,
) -> PredScoreImportResult:
    created_at = utc_now_iso()
    resolved_run_id = resolve_run_id(run_id, artifacts_root)
    run_paths = build_run_paths(resolved_run_id, artifacts_root, create=False)
    dataset_manifest = read_json(run_paths.qlib_input_dir / "dataset_manifest.json")
    source_path = Path(pred_score_path) if pred_score_path else run_paths.run_root / "pred_score.parquet"
    output_path = run_paths.run_root / "research_model_scores.parquet"
    result_path = run_paths.run_root / "pred_score_import_result.json"

    try:
        if not source_path.exists():
            raise QlibAdapterError(f"Prediction score file not found: {source_path}")
        frame = pd.read_parquet(source_path)
        normalized = _normalize_pred_score_frame(frame=frame, dataset_manifest=dataset_manifest, run_id=resolved_run_id, created_at=created_at)
        if int(normalized.duplicated(subset=["datetime", "symbol"]).sum()) > 0:
            raise QlibAdapterError("Prediction scores contain duplicate datetime-symbol rows.")
        normalized["rank"] = (
            normalized.groupby("datetime")["score"]
            .rank(method="first", ascending=False)
            .astype("int64")
        )
        normalized = normalized.sort_values(["datetime", "rank", "symbol"]).reset_index(drop=True)
        normalized.to_parquet(output_path, index=False)
        result = PredScoreImportResult(
            run_id=resolved_run_id,
            status="completed",
            research_model_scores_path=str(output_path),
            rows_written=int(len(normalized)),
            created_at=created_at,
        )
        write_json(
            result_path,
            {
                **asdict(result),
                "pred_score_path": str(source_path),
            },
        )
        return result
    except Exception as exc:
        result = PredScoreImportResult(
            run_id=resolved_run_id,
            status="failed",
            research_model_scores_path=str(output_path),
            rows_written=0,
            created_at=created_at,
            error=str(exc),
        )
        write_json(result_path, asdict(result))
        return result


def _normalize_pred_score_frame(
    *,
    frame: pd.DataFrame,
    dataset_manifest: dict,
    run_id: str,
    created_at: str,
) -> pd.DataFrame:
    working = frame.copy()
    rename_map = {}
    if "instrument" in working.columns:
        rename_map["instrument"] = "symbol"
    if "date" in working.columns and "datetime" not in working.columns:
        rename_map["date"] = "datetime"
    if "pred" in working.columns and "score" not in working.columns:
        rename_map["pred"] = "score"
    working = working.rename(columns=rename_map)
    required = {"datetime", "symbol", "score"}
    missing = sorted(required - set(working.columns))
    if missing:
        raise QlibAdapterError(f"Prediction score frame is missing columns: {missing}")
    working["datetime"] = pd.to_datetime(working["datetime"], utc=True)
    working["symbol"] = working["symbol"].astype(str).str.upper()
    working["score"] = pd.to_numeric(working["score"], errors="coerce")
    working = working.dropna(subset=["datetime", "symbol", "score"]).copy()
    if working.empty:
        raise QlibAdapterError("Prediction score frame is empty after normalization.")

    symbol_to_version = {
        str(item.get("symbol", "")).upper(): str(item.get("data_version", ""))
        for item in dataset_manifest.get("source_manifests", [])
    }
    universe = str(dataset_manifest.get("universe", {}).get("universe_id", ""))
    feature_set = str(working["feature_set"].iloc[0]) if "feature_set" in working.columns and not working.empty else ""
    label = str(working["label"].iloc[0]) if "label" in working.columns and not working.empty else ""
    model_id = str(working["model_id"].iloc[0]) if "model_id" in working.columns and not working.empty else "qlib_model"
    return pd.DataFrame(
        {
            "run_id": run_id,
            "model_id": model_id,
            "source": "qlib",
            "data_version": working["symbol"].map(symbol_to_version).fillna(working.get("data_version", "")).astype(str),
            "datetime": working["datetime"],
            "symbol": working["symbol"],
            "score": working["score"].astype(float),
            "universe": working.get("universe", universe),
            "feature_set": working.get("feature_set", feature_set),
            "label": working.get("label", label),
            "created_at": pd.Timestamp(created_at),
        }
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Import Qlib pred_score into research_model_scores.parquet.")
    parser.add_argument("--run-id", required=True, help="Run id to import.")
    parser.add_argument("--artifacts-root", default="artifacts/qlib_runs", help="Qlib artifacts root.")
    parser.add_argument("--pred-score-path", default="", help="Optional override path to pred_score parquet.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = import_pred_score(
        run_id=args.run_id,
        artifacts_root=args.artifacts_root,
        pred_score_path=args.pred_score_path or None,
    )
    print(json.dumps(asdict(result), sort_keys=True))
    return 0 if result.status == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
