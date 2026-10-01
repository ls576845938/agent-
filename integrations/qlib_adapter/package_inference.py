"""Causal, version-selected LightGBM inference on injected visible market bars.

No training, archive prediction-table reads, persistence or execution imports.
The original fixed 13-feature adapter remains a separate supported contract.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import hashlib
from pathlib import Path
import subprocess

from quant_shared.alpha_factory.evaluation import validate_panel, evaluate_expression
from quant_shared.strategy_delivery.models import DeliveryError, digest, permissions
from quant_shared.strategy_delivery.runtime_contract import validate_runtime_contract
from .factory_factors import build_primitives

FEATURE_IMPLEMENTATION_PATHS = (
    "integrations/qlib_adapter/factory_factors.py", "quant_shared/alpha_factory/evaluation.py",
    "quant_shared/alpha_factory/contracts.py", "quant_us/factors/definition.py",
    "quant_us/factors/pipeline.py", "quant_us/factors/momentum.py", "quant_us/factors/volatility.py",
    "quant_us/factors/liquidity.py",
)


def feature_implementation(*, source_head=None):
    """Pin actual shared factor code and numeric libraries, not claimed flags."""
    root = Path(__file__).resolve().parents[2]
    files = {}
    for name in FEATURE_IMPLEMENTATION_PATHS:
        try:
            raw = (root / name).read_bytes() if source_head is None else subprocess.check_output(
                ["git", "show", source_head + ":" + name], cwd=root, stderr=subprocess.DEVNULL, timeout=10)
        except (OSError, subprocess.SubprocessError) as exc:
            raise DeliveryError("feature_implementation_source_unavailable") from exc
        files[name] = hashlib.sha256(raw.replace(b"\r\n", b"\n")).hexdigest()
    return {"files": files, "dependencies": {"numpy": np.__version__, "pandas": pd.__version__}}


def load_package_model(package):
    blockers = validate_runtime_contract(package)
    if blockers: raise DeliveryError("package_load_blocked:" + ",".join(blockers))
    if package.get("feature_implementation") != feature_implementation():
        raise DeliveryError("package_feature_implementation_mismatch")
    try:
        import lightgbm as lgb
    except ImportError as exc:
        raise DeliveryError("package_lightgbm_dependency_missing") from exc
    if package["model"]["dependencies"]["lightgbm"] != lgb.__version__:
        raise DeliveryError("package_lightgbm_version_mismatch")
    try:
        model = lgb.Booster(model_str=package["model"]["text"])
        names = package["contracts"]["features"]["names"]
        if model.feature_name() != names or model.num_feature() != len(names):
            raise DeliveryError("package_model_feature_mismatch")
        if model.num_trees() < 1 or model.num_model_per_iteration() != 1:
            raise DeliveryError("package_model_output_unsupported")
        if model.dump_model().get("objective", "").split(" ")[0] not in {"regression", "regression_l1"}:
            raise DeliveryError("package_model_objective_unsupported")
        return model
    except DeliveryError:
        raise
    except Exception as exc:
        raise DeliveryError("package_model_format_invalid") from exc


def _utc(value):
    try:
        timestamp = pd.Timestamp(value)
        if timestamp.tzinfo is None or timestamp.utcoffset() != pd.Timedelta(0) or pd.isna(timestamp):
            raise ValueError()
        return timestamp.tz_convert("UTC")
    except (ValueError, TypeError, OverflowError) as exc:
        raise DeliveryError("package_market_timestamp_invalid") from exc


def infer_package(package, bars: pd.DataFrame, *, data_version: str, visible_through, mode="batch"):
    """Recompute the exact factory primitives/ASTs on the visible prefix.

    Stateless by design: restart takes the same explicit history and package;
    no hidden feature cache or implicit latest data can change past predictions.
    """
    model = load_package_model(package)
    if (package["market"] != "crypto" or package["instrument"] != "BTC-USDT-SWAP"
        or package["bar_size"] != "1h" or package["settlement_currency"] != "USDT"):
        raise DeliveryError("package_market_capability_unsupported")
    if data_version != package["data_version"]: raise DeliveryError("package_data_version_mismatch")
    if mode not in {"batch", "one_by_one"}: raise DeliveryError("package_prediction_mode_invalid")
    required = {"event_time", "available_time", "decision_time", "instrument", "open", "high", "low", "close", "volume"}
    if required - set(bars): raise DeliveryError("package_market_columns_missing")
    cutoff = _utc(visible_through)
    frame = bars.copy()
    for key in ("event_time", "available_time", "decision_time"):
        frame[key] = pd.to_datetime([_utc(value) for value in frame[key]], utc=True)
    frame = frame.loc[frame.decision_time <= cutoff].copy()
    if frame.empty: raise DeliveryError("package_no_visible_bars")
    if (not frame.event_time.is_monotonic_increasing or frame.event_time.duplicated().any()
        or not (frame.event_time == frame.event_time.dt.floor("h")).all()
        or not (frame.decision_time == frame.event_time + pd.Timedelta(hours=1)).all()
        or not (frame.available_time == frame.decision_time).all()
        or (frame.event_time.diff().dropna() != pd.Timedelta(hours=1)).any()):
        raise DeliveryError("package_market_time_or_gap_invalid")
    spec = package["contracts"]["features"]
    if set(frame.instrument) != {spec["input_instrument"]}: raise DeliveryError("package_market_instrument_mismatch")
    if spec["annualization"] != 8760: raise DeliveryError("package_annualization_mismatch")
    try:
        panel = validate_panel(frame.assign(datetime=frame.decision_time))
        # Only OHLCV primitives are in this capability. Additional supplied fields
        # cannot silently become available-time-aligned derivative primitives.
        panel = panel[["open", "high", "low", "close", "volume"]]
        primitives, _ = build_primitives(panel, bar_size="1h", annualization=spec["annualization"])
        features = pd.DataFrame({s["factor_id"]: evaluate_expression(s["expression"], primitives) for s in spec["specs"]})
        start = _utc(package["contracts"]["time"]["prediction_start"])
        features = features.iloc[spec["warmup_bars"] - 1:]
        features = features.loc[features.index.get_level_values("datetime") >= start]
        if features.empty: raise DeliveryError("package_feature_warmup_or_window_missing")
        values = features[spec["names"]].to_numpy(dtype=np.float64)
        if np.isinf(values).any(): raise DeliveryError("package_feature_infinite")
        scores = model.predict(values, num_threads=1) if mode == "batch" else [
            model.predict(row.reshape(1, -1), num_threads=1)[0] for row in values]
        scores = np.asarray(scores, dtype=float)
        if scores.shape != (len(features),) or not np.isfinite(scores).all():
            raise DeliveryError("package_prediction_invalid")
        calibration = package["contracts"]["calibration"]
        rows = features.reset_index().rename(columns={"datetime": "decision_time"})
        rows["event_time"] = rows.decision_time - pd.Timedelta(hours=1)
        rows["available_time"] = rows.decision_time
        rows["raw_score"] = scores
        rows["prediction"] = np.clip(calibration["intercept"] + calibration["slope"] * scores,
            -calibration["clip_fraction"], calibration["clip_fraction"])
        rows["expires_at"] = rows.decision_time + pd.Timedelta(hours=package["contracts"]["output"]["valid_for_bars"])
        def frame_hash(value):
            return hashlib.sha256(value.to_json(orient="split", date_format="iso", double_precision=15, index=False).encode()).hexdigest()
        return {"schema_version": "candidate_package_predictions_v1", "rows": rows,
            "package_digest": digest(package), "model_sha256": package["model"]["sha256"],
            "visible_input_sha256": frame_hash(frame[sorted(required)].reset_index(drop=True)),
            "features_sha256": frame_hash(features.reset_index()), "predictions_sha256": frame_hash(rows),
            "source": package["source"], "data_version": data_version,
            "output": package["contracts"]["output"], "permissions": permissions(),
            "execution_status": "not_executed", "research_admission_blockers": list(package["admission_blockers"])}
    except DeliveryError:
        raise
    except (ValueError, TypeError, KeyError, OverflowError) as exc:
        raise DeliveryError("package_feature_computation_failed") from exc
