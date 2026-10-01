"""Time-series validation within the common Qlib workflow (not a trading engine)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .schemas import QlibAdapterError


def validate_time_series_config(config: dict, manifest: dict) -> None:
    if config.get("mode") != "research_only" or config.get("live_enabled") or config.get("paper_enabled"):
        raise QlibAdapterError("Time-series workflow is research-only.")
    evaluation = config["evaluation"]
    data = config["task"]["dataset"]["kwargs"]
    handler = data["handler"]["kwargs"]
    actual_label = handler["data_loader"]["kwargs"]["config"]["label"][0][0]
    if actual_label != config["model"]["label"]:
        raise QlibAdapterError("Actual Qlib label differs from recorded label.")
    processors = handler.get("infer_processors", []) + handler.get("learn_processors", [])
    if any(str(p.get("class", "")).startswith("CS") for p in processors):
        raise QlibAdapterError("Cross-sectional processors are invalid for single-series research.")
    calendar = pd.DatetimeIndex(pd.to_datetime(manifest["calendar"]["trading_days"]))
    horizon, delay = evaluation["label_horizon_bars"], evaluation["entry_delay_bars"]
    if type(horizon) is not int or type(delay) is not int or horizon <= 0 or delay <= 0:
        raise QlibAdapterError("Label horizon and delay must be positive integer bars.")
    gap = horizon + delay
    expected_label = f"Ref($open, -{gap}) / Ref($open, -{delay}) - 1"
    if actual_label != expected_label:
        raise QlibAdapterError("Unsupported label: actual offsets must match the declared horizon and delay.")
    segments = data["segments"]
    previous_end = None
    for name in ("train", "valid", "test"):
        start, end = map(pd.Timestamp, segments[name])
        selected = calendar[(calendar >= start) & (calendar <= end)]
        if len(selected) < int(evaluation.get("minimum_segment_rows", 30)):
            raise QlibAdapterError(f"Insufficient covered observations in {name}.")
        if previous_end is not None:
            last_index = calendar.get_indexer([previous_end])[0]
            if last_index + gap >= len(calendar) or calendar[last_index + gap] >= selected[0]:
                raise QlibAdapterError("Overlapping forward labels: purge/embargo gap required.")
        previous_end = selected[-1]
    if calendar.get_indexer([previous_end])[0] + gap >= len(calendar):
        raise QlibAdapterError("Final test labels extend beyond available price history.")
    train_start, train_end = map(pd.Timestamp, segments["train"])
    for processor in processors:
        kwargs = processor.get("kwargs", {})
        if "fit_end_time" in kwargs and not (train_start <= pd.Timestamp(kwargs["fit_start_time"])
                <= pd.Timestamp(kwargs["fit_end_time"]) <= train_end):
            raise QlibAdapterError("Processor fit window extends beyond training segment.")
    contract = manifest.get("input_contract", {})
    if config["data"]["asset_class"] != contract.get("asset_class") or config["data"]["bar_size"] != contract.get("bar_size"):
        raise QlibAdapterError("Workflow and dataset market/timeframe mismatch.")


def prediction_quality(prediction: pd.Series, label: pd.Series) -> dict:
    pair = pd.concat([prediction.rename("prediction"), label.rename("label")], axis=1).dropna()
    if pair.empty or not np.isfinite(pair.to_numpy()).all():
        raise QlibAdapterError("No finite aligned predictions and labels.")
    correlation = pair.prediction.corr(pair.label) if pair.prediction.std() > 0 and pair.label.std() > 0 else None
    return {"sample_size": len(pair), "time_series_ic": float(correlation) if correlation is not None and np.isfinite(correlation) else None,
        "mse": float(((pair.prediction - pair.label) ** 2).mean()),
        "zero_forecast_mse": float((pair.label ** 2).mean()),
        "direction_hit_rate": float((np.sign(pair.prediction) == np.sign(pair.label)).mean()),
        "mean_predicted_return": float(pair.prediction.mean()), "mean_realized_label": float(pair.label.mean())}


def evaluate_time_series(model, dataset, config: dict, run_id: str) -> dict:
    from qlib.data.dataset.handler import DataHandlerLP
    results = {}
    pairs = {}
    for segment in ("valid", "test"):
        prediction = model.predict(dataset, segment=segment)
        labels = dataset.prepare(segment, col_set="label", data_key=DataHandlerLP.DK_R).iloc[:, 0]
        results[segment] = prediction_quality(prediction, labels)
        pairs[segment] = pd.concat([prediction.rename("score"), labels.rename("label")], axis=1).dropna()
    valid = pairs["valid"]
    if len(valid) < int(config["evaluation"].get("minimum_calibration_samples", 300)):
        raise QlibAdapterError("Insufficient OOS validation predictions for calibration.")
    design = np.column_stack([np.ones(len(valid)), valid.score.to_numpy()])
    intercept, slope = np.linalg.lstsq(design, valid.label.to_numpy(), rcond=None)[0]
    calibrated_valid = intercept + slope * valid.score
    calibrated_test = (intercept + slope * pairs["test"].score).clip(-0.05, 0.05)
    calibration_quality = prediction_quality(calibrated_valid, valid.label)
    calibration = {"method": "validation_ols", "intercept": float(intercept), "slope": float(slope),
        "sample_size": len(valid), "fit_segment": "valid", "fit_end": str(valid.index.get_level_values("datetime").max()),
        "score_units": "forward_return_12h", "test_used_for_fit": False,
        "quality_passed": bool(slope > 0 and calibration_quality["mse"] < calibration_quality["zero_forecast_mse"]),
        "quality": calibration_quality, "limitation": "validation_reused_for_early_stopping_not_independent_calibration_holdout"}
    importance = getattr(model, "model", None)
    feature_names = list(dataset.prepare("train", col_set="feature").columns)
    gains = importance.feature_importance(importance_type="gain").tolist() if importance is not None else []
    total = sum(gains)
    features = sorted([{"feature": str(name), "gain": float(gain), "share": float(gain / total) if total else 0.0}
        for name, gain in zip(feature_names, gains)], key=lambda row: -row["gain"])
    return {"schema_version": "qlib_time_series_evaluation_v1", "run_id": run_id,
        "status": "completed_research_only", "validation": results["valid"], "test": results["test"],
        "calibrated_test": prediction_quality(calibrated_test, pairs["test"].label),
        "test_metric_semantics": "test=raw_score; calibrated_test=frozen_validation_ols_clipped_as_replayed",
        "calibration": calibration,
        "feature_importance": features, "segments": config["task"]["dataset"]["kwargs"]["segments"],
        "label": config["model"]["label"], "label_horizon_bars": config["evaluation"]["label_horizon_bars"],
        "entry_delay_bars": config["evaluation"]["entry_delay_bars"],
        "trial_count": 1, "selection_rule": "fixed_config_early_stopping_on_validation_only",
        "validation_method": "purged_chronological_train_validation_test",
        "confirmatory_holdout": False, "walk_forward_status": "not_run",
        "signal_quality_passed": results["test"]["mse"] < results["test"]["zero_forecast_mse"],
        "limitations": ["historical_oos_not_live_forecast", "overlapping_labels_are_not_independent_bets",
            "no_paper_or_live_authorization", "no_claim_of_profitable_alpha"]}
