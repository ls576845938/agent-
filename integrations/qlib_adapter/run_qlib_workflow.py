from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from .schemas import (
    MissingDependencyError,
    QlibAdapterError,
    WorkflowRunResult,
    build_run_paths,
    load_yaml_file,
    optional_import,
    read_json,
    render_templates,
    to_jsonable,
    resolve_run_id,
    utc_now_iso,
    write_json,
)


def run_qlib_workflow(
    *,
    config_path: str | Path,
    run_id: str | None = None,
    artifacts_root: str | Path = "artifacts/qlib_runs",
    dry_run: bool = False,
) -> WorkflowRunResult:
    created_at = utc_now_iso()
    raw_config = load_yaml_file(config_path)
    resolved_run_id = resolve_run_id(run_id or _config_run_id(raw_config), artifacts_root)
    variables = {"run_id": resolved_run_id}
    config = render_templates(raw_config, variables)
    run_paths = build_run_paths(resolved_run_id, artifacts_root, create=False)
    provider_manifest_path = run_paths.run_root / "provider_manifest.json"
    dataset_manifest_path = run_paths.qlib_input_dir / "dataset_manifest.json"
    pred_score_path = run_paths.run_root / "pred_score.parquet"
    recorder_metrics_path = run_paths.run_root / "recorder_metrics.json"
    backtest_summary_path = run_paths.run_root / "qlib_backtest_summary.json"
    workflow_result_path = run_paths.run_root / "workflow_run_result.json"
    workflow_config_path = run_paths.run_root / "qlib_workflow_config.yaml"
    run_metadata_path = run_paths.run_root / "qlib_run_metadata.json"
    failure_report_path = run_paths.run_root / "failure_report.json"
    model_id = _config_model_id(config)

    run_paths.run_root.mkdir(parents=True, exist_ok=True)
    workflow_config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    write_json(
        run_metadata_path,
        {
            "run_id": resolved_run_id,
            "created_at": created_at,
            "mode": str(config.get("mode", "research_only")),
            "daily_only": bool(config.get("daily_only", True)),
            "live_enabled": bool(config.get("live_enabled", False)),
            "paper_enabled": bool(config.get("paper_enabled", False)),
            "provider_uri": str(run_paths.qlib_provider_dir),
            "config_path": str(Path(config_path).resolve()),
            "workflow_config_path": str(workflow_config_path.resolve()),
        },
    )

    qlib_module = None
    if not dry_run:
        try:
            qlib_module = optional_import(
                "qlib",
                required_by="run_qlib_workflow",
                install_hint="Install pyqlib before running the workflow.",
            )
            optional_import(
                "lightgbm",
                required_by="run_qlib_workflow",
                install_hint="Install lightgbm before running the workflow.",
            )
        except MissingDependencyError as exc:
            return _failed_workflow_result(
                run_id=resolved_run_id,
                model_id=model_id,
                pred_score_path=pred_score_path,
                recorder_metrics_path=recorder_metrics_path,
                backtest_summary_path=backtest_summary_path,
                workflow_result_path=workflow_result_path,
                failure_report_path=failure_report_path,
                created_at=created_at,
                error=str(exc),
            )

    if not provider_manifest_path.exists():
        return _failed_workflow_result(
            run_id=resolved_run_id,
            model_id=model_id,
            pred_score_path=pred_score_path,
            recorder_metrics_path=recorder_metrics_path,
            backtest_summary_path=backtest_summary_path,
            workflow_result_path=workflow_result_path,
            failure_report_path=failure_report_path,
            created_at=created_at,
            error=f"Provider manifest not found for run {resolved_run_id}: {provider_manifest_path}",
        )
    if not dataset_manifest_path.exists():
        return _failed_workflow_result(
            run_id=resolved_run_id,
            model_id=model_id,
            pred_score_path=pred_score_path,
            recorder_metrics_path=recorder_metrics_path,
            backtest_summary_path=backtest_summary_path,
            workflow_result_path=workflow_result_path,
            failure_report_path=failure_report_path,
            created_at=created_at,
            error=f"Dataset manifest not found for run {resolved_run_id}: {dataset_manifest_path}",
        )

    dataset_manifest = read_json(dataset_manifest_path)
    if dataset_manifest.get("status") != "completed":
        return _failed_workflow_result(
            run_id=resolved_run_id,
            model_id=model_id,
            pred_score_path=pred_score_path,
            recorder_metrics_path=recorder_metrics_path,
            backtest_summary_path=backtest_summary_path,
            workflow_result_path=workflow_result_path,
            failure_report_path=failure_report_path,
            created_at=created_at,
            error=f"Dataset manifest status is not completed: {dataset_manifest.get('status')}",
        )
    if not run_paths.qlib_provider_dir.exists():
        return _failed_workflow_result(
            run_id=resolved_run_id,
            model_id=model_id,
            pred_score_path=pred_score_path,
            recorder_metrics_path=recorder_metrics_path,
            backtest_summary_path=backtest_summary_path,
            workflow_result_path=workflow_result_path,
            failure_report_path=failure_report_path,
            created_at=created_at,
            error=f"Qlib provider directory not found: {run_paths.qlib_provider_dir}",
        )

    if dry_run:
        result = WorkflowRunResult(
            run_id=resolved_run_id,
            status="dry_run",
            model_id=model_id,
            pred_score_path=str(pred_score_path),
            recorder_metrics_path=str(recorder_metrics_path),
            backtest_summary_path=str(backtest_summary_path),
            created_at=created_at,
        )
        write_json(
            workflow_result_path,
            {
                **asdict(result),
                "config_path": str(Path(config_path).resolve()),
                "workflow_config_path": str(workflow_config_path.resolve()),
                "run_metadata_path": str(run_metadata_path.resolve()),
                "provider_manifest_path": str(provider_manifest_path.resolve()),
                "dataset_manifest_path": str(dataset_manifest_path.resolve()),
            },
        )
        return result

    constant_module = optional_import("qlib.constant", required_by="run_qlib_workflow", install_hint="Install pyqlib.")
    utils_module = optional_import("qlib.utils", required_by="run_qlib_workflow", install_hint="Install pyqlib.")
    workflow_module = optional_import("qlib.workflow", required_by="run_qlib_workflow", install_hint="Install pyqlib.")
    record_module = optional_import(
        "qlib.workflow.record_temp",
        required_by="run_qlib_workflow",
        install_hint="Install pyqlib.",
    )

    qlib_init = dict(config.get("qlib_init", {}))
    qlib_init["provider_uri"] = str(run_paths.qlib_provider_dir.resolve())
    qlib_init["region"] = _resolve_region(constant_module, qlib_init.get("region", config.get("qlib", {}).get("region", "us")))
    init_instance_by_config = getattr(utils_module, "init_instance_by_config")
    flatten_dict = getattr(utils_module, "flatten_dict")
    R = getattr(workflow_module, "R")
    SignalRecord = getattr(record_module, "SignalRecord")
    SigAnaRecord = getattr(record_module, "SigAnaRecord")
    PortAnaRecord = getattr(record_module, "PortAnaRecord")

    task = config.get("task", {})
    if not isinstance(task, dict) or "model" not in task or "dataset" not in task:
        raise QlibAdapterError("Workflow config must define task.model and task.dataset.")

    getattr(qlib_module, "init")(**qlib_init)
    model = init_instance_by_config(task["model"])
    dataset = init_instance_by_config(task["dataset"])
    experiment_name = str(config.get("workflow", {}).get("experiment_name", config.get("run_id_prefix", "qs_qlib_workflow")))

    try:
        portfolio_analysis_error: str | None = None
        with R.start(experiment_name=experiment_name):
            R.log_params(**flatten_dict(task))
            model.fit(dataset)
            recorder = R.get_recorder()
            prediction = model.predict(dataset)
            pred_frame = _normalize_prediction_frame(
                prediction=prediction,
                run_id=resolved_run_id,
                model_id=model_id,
                dataset_manifest=dataset_manifest,
                config=config,
                created_at=created_at,
            )
            pred_frame.to_parquet(pred_score_path, index=False)

            SignalRecord(model, dataset, recorder).generate()
            if bool(config.get("workflow", {}).get("enable_signal_analysis", True)):
                SigAnaRecord(recorder).generate()
            if bool(config.get("workflow", {}).get("enable_portfolio_analysis", True)):
                try:
                    port_config = _portfolio_analysis_config(config=config, model=model, dataset=dataset)
                    PortAnaRecord(recorder, port_config, "day").generate()
                except Exception as exc:
                    portfolio_analysis_error = str(exc)

            metrics_payload = _collect_recorder_payload(recorder)
            write_json(recorder_metrics_path, metrics_payload)
            write_json(
                backtest_summary_path,
                _backtest_summary(
                    metrics_payload=metrics_payload,
                    config=config,
                    run_id=resolved_run_id,
                    portfolio_analysis_error=portfolio_analysis_error,
                ),
            )
        result = WorkflowRunResult(
            run_id=resolved_run_id,
            status="completed",
            model_id=model_id,
            pred_score_path=str(pred_score_path),
            recorder_metrics_path=str(recorder_metrics_path),
            backtest_summary_path=str(backtest_summary_path),
            created_at=created_at,
        )
        write_json(
            workflow_result_path,
            {
                **asdict(result),
                "config_path": str(Path(config_path).resolve()),
                "workflow_config_path": str(workflow_config_path.resolve()),
                "run_metadata_path": str(run_metadata_path.resolve()),
                "dataset_manifest_path": str(dataset_manifest_path.resolve()),
                "provider_manifest_path": str(provider_manifest_path.resolve()),
            },
        )
        return result
    except Exception as exc:
        return _failed_workflow_result(
            run_id=resolved_run_id,
            model_id=model_id,
            pred_score_path=pred_score_path,
            recorder_metrics_path=recorder_metrics_path,
            backtest_summary_path=backtest_summary_path,
            workflow_result_path=workflow_result_path,
            failure_report_path=failure_report_path,
            created_at=created_at,
            error=str(exc),
        )


def _config_run_id(config: dict[str, Any]) -> str | None:
    workflow = config.get("workflow", {})
    if isinstance(workflow, dict) and workflow.get("run_id"):
        return str(workflow.get("run_id"))
    return None


def _model_config(config: dict[str, Any]) -> dict[str, Any]:
    model = config.get("model", {})
    if isinstance(model, dict):
        return model
    if model is None:
        return {}
    return {"name": str(model)}


def _config_model_id(config: dict[str, Any]) -> str:
    return str(_model_config(config).get("name", "qlib_model"))


def _failed_workflow_result(
    *,
    run_id: str,
    model_id: str,
    pred_score_path: Path,
    recorder_metrics_path: Path,
    backtest_summary_path: Path,
    workflow_result_path: Path,
    failure_report_path: Path,
    created_at: str,
    error: str,
) -> WorkflowRunResult:
    failure = WorkflowRunResult(
        run_id=run_id,
        status="failed",
        model_id=model_id,
        pred_score_path=str(pred_score_path),
        recorder_metrics_path=str(recorder_metrics_path),
        backtest_summary_path=str(backtest_summary_path),
        created_at=created_at,
        error=error,
    )
    payload = asdict(failure)
    write_json(workflow_result_path, payload)
    write_json(
        failure_report_path,
        {
            **payload,
            "failure_stage": "qlib_workflow",
            "research_only": True,
            "live_enabled": False,
            "paper_enabled": False,
        },
    )
    return failure


def _resolve_region(constant_module, region_value: Any):
    text = str(region_value).upper()
    return getattr(constant_module, f"REG_{text}", region_value)


def _portfolio_analysis_config(*, config: dict[str, Any], model: Any, dataset: Any) -> dict[str, Any]:
    payload = to_jsonable(config.get("portfolio_analysis", {}))
    if not payload:
        raise QlibAdapterError("Workflow config must define portfolio_analysis for recorder backtest output.")
    strategy = payload.get("strategy", {})
    kwargs = strategy.get("kwargs", {})
    if kwargs.get("signal") in {"<PRED>", "<MODEL_DATASET>"}:
        kwargs["signal"] = (model, dataset)
    return payload


def _normalize_prediction_frame(
    *,
    prediction: Any,
    run_id: str,
    model_id: str,
    dataset_manifest: dict[str, Any],
    config: dict[str, Any],
    created_at: str,
) -> pd.DataFrame:
    if isinstance(prediction, pd.Series):
        frame = prediction.rename("score").reset_index()
    elif isinstance(prediction, pd.DataFrame):
        frame = prediction.reset_index()
        if "score" not in frame.columns:
            numeric_columns = [col for col in frame.columns if pd.api.types.is_numeric_dtype(frame[col])]
            if not numeric_columns:
                raise QlibAdapterError("Qlib prediction frame has no numeric score column.")
            frame = frame.rename(columns={numeric_columns[0]: "score"})
    else:
        raise QlibAdapterError(f"Unsupported prediction type returned by Qlib model: {type(prediction)!r}")

    rename_map = {}
    if "instrument" in frame.columns:
        rename_map["instrument"] = "symbol"
    if "datetime" not in frame.columns and "date" in frame.columns:
        rename_map["date"] = "datetime"
    if "pred" in frame.columns and "score" not in frame.columns:
        rename_map["pred"] = "score"
    frame = frame.rename(columns=rename_map)
    required = {"datetime", "symbol", "score"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise QlibAdapterError(f"Qlib prediction output is missing required columns: {missing}")

    frame["datetime"] = pd.to_datetime(frame["datetime"], utc=True)
    frame["symbol"] = frame["symbol"].astype(str).str.upper()
    frame["score"] = pd.to_numeric(frame["score"], errors="coerce")
    frame = frame.dropna(subset=["datetime", "symbol", "score"]).copy()
    if frame.empty:
        raise QlibAdapterError("Qlib prediction output is empty after normalization.")

    symbol_to_version = {
        str(item.get("symbol", "")).upper(): str(item.get("data_version", ""))
        for item in dataset_manifest.get("source_manifests", [])
    }
    universe = dataset_manifest.get("universe", {}).get("universe_id", "")
    model_config = _model_config(config)
    feature_set = str(model_config.get("feature_set", ""))
    label = str(model_config.get("label", ""))

    return pd.DataFrame(
        {
            "run_id": run_id,
            "model_id": model_id,
            "source": "qlib",
            "datetime": frame["datetime"],
            "symbol": frame["symbol"],
            "score": frame["score"].astype(float),
            "data_version": frame["symbol"].map(symbol_to_version).fillna(""),
            "universe": universe,
            "feature_set": feature_set,
            "label": label,
            "created_at": pd.Timestamp(created_at),
        }
    ).sort_values(["datetime", "symbol"]).reset_index(drop=True)


def _collect_recorder_payload(recorder) -> dict[str, Any]:
    list_metrics = getattr(recorder, "list_metrics", None)
    list_params = getattr(recorder, "list_params", None)
    list_tags = getattr(recorder, "list_tags", None)
    list_artifacts = getattr(recorder, "list_artifacts", None)
    payload = {
        "id": str(getattr(recorder, "id", "")),
        "name": str(getattr(recorder, "name", "")),
        "metrics": dict(list_metrics() or {}) if callable(list_metrics) else {},
        "params": dict(list_params() or {}) if callable(list_params) else {},
        "tags": dict(list_tags() or {}) if callable(list_tags) else {},
        "artifacts": list(list_artifacts() or []) if callable(list_artifacts) else [],
    }
    return payload


def _backtest_summary(
    *,
    metrics_payload: dict[str, Any],
    config: dict[str, Any],
    run_id: str,
    portfolio_analysis_error: str | None = None,
) -> dict[str, Any]:
    metrics = metrics_payload.get("metrics", {})
    interesting = {
        key: metrics[key]
        for key in metrics
        if any(token in str(key).lower() for token in ("ic", "rank", "return", "sharp", "drawdown", "cost"))
    }
    return {
        "run_id": run_id,
        "source": "qlib",
        "mode": str(config.get("mode", "research_only")),
        "daily_only": bool(config.get("daily_only", True)),
        "metric_count": len(metrics),
        "selected_metrics": interesting,
        "portfolio_analysis_status": "failed" if portfolio_analysis_error else "completed",
        "portfolio_analysis_error": portfolio_analysis_error,
        "note": "Qlib portfolio analysis is diagnostic only and is not a promotion or trading gate.",
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a Qlib workflow against an exported daily-only provider.")
    parser.add_argument("--config", required=True, help="Path to the Qlib workflow YAML config.")
    parser.add_argument("--run-id", default="", help="Run id to execute. Defaults to workflow.run_id or latest.")
    parser.add_argument("--artifacts-root", default="artifacts/qlib_runs", help="Qlib artifacts root.")
    parser.add_argument("--dry-run", action="store_true", help="Validate inputs without importing qlib/lightgbm.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = run_qlib_workflow(
        config_path=args.config,
        run_id=args.run_id or None,
        artifacts_root=args.artifacts_root,
        dry_run=args.dry_run,
    )
    print(json.dumps(asdict(result), sort_keys=True))
    return 0 if result.status in {"completed", "dry_run"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
