from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
import math
import os
import threading
from functools import wraps
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
    resolve_git_commit,
    utc_now_iso,
    write_json,
)


_WORKFLOW_LOCK = threading.Lock()


def _exclusive_workflow(function):
    @wraps(function)
    def guarded(**kwargs):
        if not _WORKFLOW_LOCK.acquire(blocking=False):
            raise QlibAdapterError("Qlib global research context is busy; concurrent workflows are blocked.")
        lock_path = None
        owned = False
        try:
            root = kwargs.get("artifacts_root", "artifacts/qlib_runs")
            config = load_yaml_file(kwargs["config_path"])
            identity = resolve_run_id(kwargs.get("run_id") or _config_run_id(config), root)
            paths = build_run_paths(identity, root)
            paths.run_root.mkdir(parents=True, exist_ok=True)
            lock_path = paths.run_root / ".workflow_writer.lock"
            descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            owned = True
            with os.fdopen(descriptor, "w", encoding="utf-8") as lock:
                json.dump({"run_id":identity,"pid":os.getpid()},lock)
            return function(**{**kwargs,"run_id":identity})
        finally:
            if owned:
                lock_path.unlink()
            _WORKFLOW_LOCK.release()
    return guarded


@_exclusive_workflow
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
    if config.get("mode", "research_only") != "research_only" or config.get("live_enabled") or config.get("paper_enabled"):
        raise QlibAdapterError("Qlib research cannot grant execution permission.")
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
    if workflow_result_path.exists() and read_json(workflow_result_path).get("status") == "completed":
        raise QlibAdapterError("Completed research run is immutable; build a new run_id to retrain.")

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
            "code_version": resolve_git_commit(Path(__file__).resolve().parents[2]),
            "config_sha256": hashlib.sha256(Path(config_path).read_bytes()).hexdigest(),
            "profile": config.get("profile", "us_equity_daily"),
            "asset_class": config.get("data", {}).get("asset_class", "equity"),
            "bar_size": config.get("data", {}).get("bar_size", "1d"),
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

    if config.get("evaluation", {}).get("kind") == "time_series":
        from .time_series_evaluation import validate_time_series_config
        validate_time_series_config(config, dataset_manifest)

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
    if "exp_manager" in qlib_init:
        qlib_init["exp_manager"] = {**qlib_init["exp_manager"], "class": "ResearchExpManager",
            "module_path": "integrations.qlib_adapter.recorder"}
    qlib_init["provider_uri"] = str(run_paths.qlib_provider_dir.resolve())
    if config.get("evaluation", {}).get("kind") in {"time_series", "alpha_factory"}:
        # Keep each experiment's tracking database inside this exact run.
        qlib_init["exp_manager"]["kwargs"]["uri"] = "sqlite:///" + (run_paths.run_root.resolve() / "mlflow.db").as_posix()
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
    if config.get("evaluation", {}).get("kind") in {"time_series", "alpha_factory"}:
        from mlflow.tracking import MlflowClient
        client = MlflowClient(tracking_uri=qlib_init["exp_manager"]["kwargs"]["uri"])
        if client.get_experiment_by_name(experiment_name) is None:
            client.create_experiment(experiment_name, artifact_location=(run_paths.run_root.resolve() / "mlflow_artifacts").as_uri())

    try:
        portfolio_analysis_error: str | None = None
        with R.start(experiment_name=experiment_name):
            R.log_params(**flatten_dict(task))
            evaluation = config.get("evaluation", {})
            is_factory = evaluation.get("kind") == "alpha_factory"
            is_factory_final = is_factory and evaluation.get("phase") == "final"
            fit_started_at = utc_now_iso() if is_factory_final else None
            model.fit(dataset, **config.get("workflow", {}).get("fit_kwargs", {}))
            fit_completed_at = utc_now_iso() if is_factory_final else None
            recorder = R.get_recorder()
            finalization_receipt = None
            if is_factory_final:
                contract = evaluation.get("research_contract")
                delivery_policy = config.get("delivery_policy")
                if (not isinstance(contract, dict)
                    or contract.get("schema_version") != "btc_real_candidate_research_contract_v1"
                    or contract.get("calibration") != {"kind": "ols_validation_only", "slope_clip": .05, "applications": 1}
                    or delivery_policy != {"policies": {key: contract.get(key) for key in ("position", "exit", "cost", "output")},
                        "clip_fraction": .05, "frozen_at": contract.get("policy_committed_at")}):
                    raise QlibAdapterError("factory_final_research_contract_invalid")
                if getattr(model, "model", None) is None:
                    raise QlibAdapterError("factory_final_model_missing_after_fit")
                model_path = run_paths.run_root / "model.txt"
                model_text = model.model.model_to_string()
                feature_names = list(pd.read_parquet(run_paths.run_root / "factory_features.parquet").columns)
                old_header = "feature_names=" + " ".join(model.model.feature_name())
                new_header = "feature_names=" + " ".join(feature_names)
                if model_text.count(old_header) != 1 or any(not isinstance(name, str) or not name or " " in name
                        for name in feature_names):
                    raise QlibAdapterError("factory_final_model_feature_names_invalid")
                model_path.write_bytes(model_text.replace(old_header, new_header, 1).encode("utf-8"))
                model_sha256 = hashlib.sha256(model_path.read_bytes()).hexdigest()
                model_sealed_at = utc_now_iso()
                validation_prediction_started_at = utc_now_iso()
                validation_prediction = model.predict(dataset, segment="valid")
                validation_prediction_completed_at = utc_now_iso()
                validation_rows = _factory_evidence_rows(run_paths.run_root, validation_prediction)
                calibration = _factory_ols_calibration(validation_rows, clip_fraction=.05)
                calibration_sealed_at = utc_now_iso()
                calibration_seal = {
                    "schema_version": "factory_calibration_seal_v1", "run_id": resolved_run_id,
                    "candidate_id": evaluation.get("candidate_id"), "fit_scope": "validation_only",
                    "prediction_call": 1, "validation_rows": validation_rows,
                    "validation_rows_sha256": _json_digest(validation_rows), "calibration": calibration,
                    "model_sha256": model_sha256, "source_head": contract.get("source_head"),
                    "policy_sha256": _json_digest(delivery_policy),
                    "quality_passed": calibration["quality"]["ic"] > 0 and calibration["quality"]["hit_rate"] > .5,
                    "sealed_at": calibration_sealed_at,
                }
                if not calibration_seal["quality_passed"]:
                    write_json(run_paths.run_root / "factory_calibration_seal.json", calibration_seal)
                    raise QlibAdapterError("factory_final_calibration_quality_not_passed")
                write_json(run_paths.run_root / "factory_calibration_seal.json", calibration_seal)
                audit_prediction_started_at = utc_now_iso()
                prediction = model.predict(dataset, segment="test")
                audit_prediction_completed_at = utc_now_iso()
                audit_rows = _factory_evidence_rows(run_paths.run_root, prediction)
                wall_operations = {"policy_committed_at": contract["policy_committed_at"],
                    "final_fit_started_at": fit_started_at, "final_fit_completed_at": fit_completed_at,
                    "model_sealed_at": model_sealed_at,
                    "validation_prediction_started_at": validation_prediction_started_at,
                    "validation_prediction_completed_at": validation_prediction_completed_at,
                    "calibration_sealed_at": calibration_sealed_at,
                    "audit_prediction_started_at": audit_prediction_started_at,
                    "audit_prediction_completed_at": audit_prediction_completed_at}
                finalization_receipt = {
                    "schema_version": "factory_finalization_receipt_v1", "run_id": resolved_run_id,
                    "candidate_id": evaluation.get("candidate_id"), "fit_count": 1,
                    "prediction_calls": ["validation_once", "audit_once"],
                    "model_sha256": model_sha256, "source_head": contract.get("source_head"),
                    "policy_sha256": _json_digest(delivery_policy), "wall_operations": wall_operations,
                    "operation_order": ["policy_freeze", "final_fit", "model_seal", "validation_prediction",
                        "calibration_seal", "audit_prediction"],
                    "calibration_seal_sha256": hashlib.sha256(
                        (run_paths.run_root / "factory_calibration_seal.json").read_bytes()).hexdigest(),
                    "validation_rows_sha256": calibration_seal["validation_rows_sha256"],
                    "audit_rows": audit_rows, "audit_rows_sha256": _json_digest(audit_rows),
                    "calibration": calibration, "audit_opened_after_calibration_seal": True,
                    "signal_record_generated": False,
                }
                write_json(run_paths.run_root / "factory_finalization_receipt.json", finalization_receipt)
            else:
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
            if config.get("evaluation", {}).get("kind") == "time_series":
                from .time_series_evaluation import evaluate_time_series
                evaluation = evaluate_time_series(model, dataset, config, resolved_run_id)
                write_json(run_paths.run_root / "signal_evaluation.json", evaluation)
            if not is_factory_final and getattr(model, "model", None) is not None:
                # LightGBM's native Windows file writer cannot reliably open Unicode paths.
                (run_paths.run_root / "model.txt").write_text(model.model.model_to_string(), encoding="utf-8")

            # Alpha-factory prediction is already materialized above. Calling
            # SignalRecord would invoke model.predict a second time and make the
            # fit/prediction audit receipt false. Other workflows retain Qlib's
            # native record generator unchanged.
            if not is_factory:
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


def _json_digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=True, allow_nan=False).encode()).hexdigest()


def _factory_evidence_rows(run_root: Path, prediction: Any) -> list[dict[str, Any]]:
    """Bind one explicit prediction call to exact features and labels."""
    features = pd.read_parquet(run_root / "factory_features.parquet")
    labels = pd.read_parquet(run_root / "factory_labels.parquet")
    if isinstance(prediction, pd.DataFrame):
        if "score" in prediction:
            scores = prediction["score"]
        elif prediction.shape[1] == 1:
            scores = prediction.iloc[:, 0]
        else:
            raise QlibAdapterError("factory_prediction_score_ambiguous")
    elif isinstance(prediction, pd.Series):
        scores = prediction
    else:
        raise QlibAdapterError("factory_prediction_type_invalid")
    for frame in (features, labels):
        if frame.index.names != ["datetime", "instrument"] or frame.index.duplicated().any():
            raise QlibAdapterError("factory_evidence_index_invalid")
        frame.index = pd.MultiIndex.from_arrays([
            pd.to_datetime(frame.index.get_level_values("datetime"), utc=True),
            frame.index.get_level_values("instrument").astype(str)], names=["datetime", "instrument"])
    if scores.index.names != ["datetime", "instrument"] or scores.index.duplicated().any():
        raise QlibAdapterError("factory_prediction_index_invalid")
    scores.index = pd.MultiIndex.from_arrays([
        pd.to_datetime(scores.index.get_level_values("datetime"), utc=True),
        scores.index.get_level_values("instrument").astype(str)], names=["datetime", "instrument"])
    scores = pd.to_numeric(scores, errors="coerce").sort_index()
    if not scores.index.isin(features.index).all() or not scores.index.isin(labels.index).all():
        raise QlibAdapterError("factory_prediction_outside_frozen_frame")
    rows = []
    for key, raw_score in scores.items():
        label = labels.at[key, "label"]
        values = features.loc[key].tolist()
        if not math.isfinite(float(raw_score)) or not math.isfinite(float(label)):
            raise QlibAdapterError("factory_prediction_or_label_nonfinite")
        rows.append({"event_time": key[0].isoformat(), "instrument": key[1],
            "features": [None if pd.isna(value) else float(value) for value in values],
            "raw_score": float(raw_score), "label": float(label)})
    if len(rows) < 30:
        raise QlibAdapterError("factory_final_evidence_insufficient_samples")
    return rows


def _factory_ols_calibration(rows: list[dict[str, Any]], *, clip_fraction: float) -> dict[str, Any]:
    pairs = [(row["raw_score"], row["label"]) for row in rows]
    count = len(pairs)
    mean_x = math.fsum(x for x, _ in pairs) / count
    mean_y = math.fsum(y for _, y in pairs) / count
    xx = math.fsum((x - mean_x) ** 2 for x, _ in pairs)
    yy = math.fsum((y - mean_y) ** 2 for _, y in pairs)
    xy = math.fsum((x - mean_x) * (y - mean_y) for x, y in pairs)
    if xx <= 0 or yy <= 0:
        raise QlibAdapterError("factory_final_calibration_degenerate")
    slope = xy / xx
    intercept = mean_y - slope * mean_x
    transformed = [max(-clip_fraction, min(clip_fraction, intercept + slope * x)) for x, _ in pairs]
    mt = math.fsum(transformed) / count
    xt = math.fsum((x - mt) ** 2 for x in transformed)
    yt = yy
    xyt = math.fsum((x - mt) * (y - mean_y) for x, (_, y) in zip(transformed, pairs))
    quality = {"ic": xyt / math.sqrt(xt * yt) if xt > 0 else 0.0,
        "hit_rate": sum(((x > 0) - (x < 0)) == ((y > 0) - (y < 0)) for x, (_, y) in zip(transformed, pairs)) / count}
    return {"intercept": intercept, "slope": slope, "clip_fraction": clip_fraction,
        "quality": quality, "sample_size": count}


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
            "asset_class": config.get("data", {}).get("asset_class", "equity"),
            "bar_size": config.get("data", {}).get("bar_size", "1d"),
            "profile_id": config.get("profile", "us_equity_daily"),
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
        "portfolio_analysis_status": ("not_run" if not config.get("workflow", {}).get("enable_portfolio_analysis", True)
            else "failed" if portfolio_analysis_error else "completed"),
        "signal_analysis_status": "requested" if config.get("workflow", {}).get("enable_signal_analysis", True) else "not_run",
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
