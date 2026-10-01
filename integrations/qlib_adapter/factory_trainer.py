"""Generated feature frames run through the EXISTING Qlib workflow and recorder."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import shutil

import pandas as pd
import yaml

from quant_shared.alpha_factory.contracts import FactoryError, SAFETY, digest
from .schemas import build_run_paths, read_json, resolve_git_commit, write_json
from .profiles import REPO
from .research_pipeline import seal_run, read_sealed_evidence


MODEL_CATALOG = (
    {"model_id": "lgbm_small", "num_leaves": 7, "learning_rate": .035, "min_data_in_leaf": 80},
    {"model_id": "lgbm_medium", "num_leaves": 15, "learning_rate": .035, "min_data_in_leaf": 80},
    {"model_id": "lgbm_smooth", "num_leaves": 7, "learning_rate": .02, "min_data_in_leaf": 120},
)


def train_feature_trial(*, features, labels, segments, profile, lineage, model_spec, seed,
    qlib_root: Path, run_id: str, factory_run_id: str, trial_number: int,
    phase: str = "selection", candidate_id: str | None = None, research_contract: dict | None = None):
    from .run_qlib_workflow import run_qlib_workflow
    paths = build_run_paths(run_id, qlib_root)
    if paths.run_root.exists():
        raise FactoryError("qlib_trial_already_exists")
    source_root = build_run_paths(lineage["input_run_id"], qlib_root).run_root
    if read_sealed_evidence(source_root)["integrity_status"] != "passed":
        raise FactoryError("input_seal_invalid_before_training")
    paths.run_root.mkdir(parents=True)
    frame = features.copy()
    frame.index = pd.MultiIndex.from_arrays([frame.index.get_level_values("datetime").tz_convert("UTC").tz_localize(None),
        frame.index.get_level_values("instrument")], names=["datetime", "instrument"])
    target = labels.copy(); target.index = frame.index
    # Persist only the declared evaluation interval, not the final campaign audit
    # when fitting model-selection folds. No untrusted pickle/class is loaded.
    end = pd.Timestamp(segments["test"][1]).tz_convert("UTC").tz_localize(None)
    visible = frame.index.get_level_values("datetime") <= end
    frame.loc[visible].to_parquet(paths.run_root / "factory_features.parquet")
    target.loc[visible].to_frame("label").to_parquet(paths.run_root / "factory_labels.parquet")
    manifest = lineage["dataset_manifest"]
    trial_manifest = {**manifest, "run_id": run_id, "factory_run_id": factory_run_id,
        "source_input_run_id": lineage["input_run_id"], "source_input_seal_sha256": lineage["input_seal_sha256"],
        "files": {"features": "factory_features.parquet", "labels": "factory_labels.parquet"}}
    write_json(paths.qlib_input_dir / "dataset_manifest.json", trial_manifest)
    shutil.copytree(source_root / "qlib_provider", paths.qlib_provider_dir)
    write_json(paths.run_root / "provider_manifest.json", {"status": "completed", "run_id": run_id,
        "source_input_run_id": lineage["input_run_id"], "provider_format": "qlib_file_storage"})
    naive_segments = {name: [pd.Timestamp(value).tz_convert("UTC").tz_localize(None).isoformat() for value in window]
        for name, window in segments.items()}
    params = {key: value for key, value in model_spec.items() if key != "model_id"}
    config = {"mode": "research_only", "profile": profile["profile_id"], "daily_only": profile["bar_size"] == "1d",
        "live_enabled": False, "paper_enabled": False,
        "data": {"asset_class": profile["asset_class"], "bar_size": profile["bar_size"]},
        "evaluation": {"kind": "alpha_factory", "phase": phase, "candidate_id": candidate_id,
            "research_contract": research_contract},
        "model": {"name": model_spec["model_id"], "feature_set": "factory_" + digest(list(frame.columns))[:20],
            "label": lineage["split_plan"]["label"], "strategy_version": "shared_alpha_factory_v1"},
        "workflow": {"experiment_name": "shared_alpha_factory", "enable_signal_analysis": False,
            "enable_portfolio_analysis": False,
            "fit_kwargs": {"num_boost_round": 100, "early_stopping_rounds": 12, "verbose_eval": False}},
        "qlib_init": {"region": "us", "kernels": 1, "joblib_backend": "threading",
            "expression_cache": None, "dataset_cache": None,
            "exp_manager": {"class": "ResearchExpManager", "module_path": "integrations.qlib_adapter.recorder",
                "kwargs": {"uri": "sqlite:///" + (paths.run_root.resolve() / "mlflow.db").as_posix(),
                    "default_exp_name": "shared_alpha_factory"}}},
        "task": {"model": {"class": "LGBModel", "module_path": "qlib.contrib.model.gbdt",
            "kwargs": {"loss": "mse", "seed": seed, "num_threads": 2, "verbosity": -1, "lambda_l2": 5, **params}},
            "dataset": {"class": "DatasetH", "module_path": "qlib.data.dataset", "kwargs": {
                "handler": {"class": "DataHandlerLP", "module_path": "qlib.data.dataset.handler", "kwargs": {
                    "data_loader": {"class": "FactoryParquetLoader", "module_path": "integrations.qlib_adapter.factory_loader", "kwargs": {
                        "features": str(paths.run_root / "factory_features.parquet"),
                        "labels": str(paths.run_root / "factory_labels.parquet")}},
                    "learn_processors": [{"class": "DropnaLabel"}], "infer_processors": []}},
                "segments": naive_segments}}}}
    if phase == "final" and research_contract is not None:
        config["delivery_policy"] = {
            "policies": {key: research_contract[key] for key in ("position", "exit", "cost", "output")},
            "clip_fraction": research_contract["calibration"]["slope_clip"],
            "frozen_at": research_contract["policy_committed_at"],
        }
    config_path = paths.run_root / "factory_config.yaml"
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    receipt = {"schema_version": "qlib_factory_trial_v1", "run_id": run_id, "factory_run_id": factory_run_id,
        "trial_number": trial_number, "phase": phase, "candidate_id": candidate_id,
        "model_spec": model_spec, "segments": segments, "feature_ids": list(frame),
        "source_head": resolve_git_commit(REPO), "profile_hash": profile["profile_hash"], **SAFETY}
    try:
        result = run_qlib_workflow(config_path=config_path, run_id=run_id, artifacts_root=qlib_root)
        if result.status != "completed": raise FactoryError(str(result.error))
        receipt["status"] = "completed"
        write_json(paths.run_root / "factory_trial.json", receipt)
        write_json(paths.run_root / "pipeline_result.json", {**receipt, "asset_class": profile["asset_class"],
            "bar_size": profile["bar_size"], "profile_id": profile["profile_id"], "research_only": True})
        scores = pd.read_parquet(paths.run_root / "pred_score.parquet")
        prediction = scores.rename(columns={"symbol": "instrument"}).set_index(["datetime", "instrument"]).score
        from .trend_environment import build_sidecar
        environment_reference = build_sidecar(paths.run_root)
        seal = seal_run(paths.run_root)
        reference = {"qlib_run_id": run_id, "seal_sha256": digest(seal), "model_spec": model_spec,
            "environment_observation": environment_reference,
            "recorder_id": read_json(paths.run_root / "recorder_metrics.json").get("id"),
            "feature_ids": list(frame), "segments": segments}
        if phase == "final":
            finalization = read_json(paths.run_root / "factory_finalization_receipt.json")
            reference["finalization_receipt_sha256"] = digest(finalization)
            reference["calibration"] = finalization["calibration"]
            dependencies = research_contract["dependency_versions"]
            reference["acceptance_delivery_evidence"] = {
                "receipt_version": "factory_delivery_evidence_v2",
                "frozen_policy": {"candidate_id": candidate_id, "qlib_run_id": run_id,
                    "data_version": lineage["data_version"],
                    "model_sha256": seal["files"]["model.txt"],
                    "feature_specs_sha256": None,
                    "policies": {key: research_contract[key] for key in ("position", "exit", "cost", "output")},
                    "clip_fraction": research_contract["calibration"]["slope_clip"],
                    "frozen_at": research_contract["policy_committed_at"]},
                "calibration": {"version": "candidate_ols_v1",
                    **{key: finalization["calibration"][key] for key in ("intercept", "slope", "clip_fraction")}},
                "wall_operations": deepcopy(finalization["wall_operations"]),
                "operation_order": list(finalization["operation_order"]),
                "model_dependencies": {"lightgbm": dependencies["lightgbm"], "qlib": dependencies["qlib"]},
                "feature_dependencies": {"numpy": dependencies["numpy"], "pandas": dependencies["pandas"]},
                "settlement_evidence": {"currency": "USDT", "instrument": "BTC-USDT-SWAP",
                    "source": "candidate_final_audit"},
            }
        return prediction, reference
    except Exception as exc:
        write_json(paths.run_root / "factory_trial.json", {**receipt, "status": "failed", "error": str(exc)})
        if not (paths.run_root / "run_seal.json").exists(): seal_run(paths.run_root)
        raise
