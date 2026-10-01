"""Read-only inference for one explicitly bound, sealed Qlib research package.

This adapter deliberately stops at features, raw model scores and the frozen
research calibration.  It never trains, selects a model, constructs a target
position, calls an execution adapter, or writes into the sealed archive.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from numbers import Real
from pathlib import Path
import re
import subprocess
from typing import Any, Mapping

import numpy as np
import pandas as pd

from tools.agent_governance.shared_data import (
    default_shared_data_root,
    load_manifest_from_git,
    resolve_manifest_payload,
)

from .research_pipeline import read_sealed_evidence


_FALSE_PERMISSION_KEYS = (
    "promotion",
    "paper",
    "live",
    "private",
    "order",
    "real_order",
    "transfer",
    "withdraw",
    "execution_permission",
    "runtime_observed",
)
_TIME_SEMANTICS = {
    "event_time": "completed_bar_open_utc",
    "available_time": "event_time_plus_1h",
    "decision_time": "event_time_plus_1h",
    "hypothetical_execution_time": "event_time_plus_2h_not_decision_time_plus_2h",
}
_COMMIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_CALIBRATION_EVIDENCE_PATH = "tests/fixtures/strategy_v0/baseline.json"


class FrozenInferenceError(RuntimeError):
    """A sealed package or caller binding is incomplete or inconsistent."""


@dataclass(frozen=True)
class FrozenInferenceResult:
    usage: str
    output_kind: str
    run_id: str
    candidate_id: str
    strategy_id: str
    strategy_version: str
    package_digest: str
    model_sha256: str
    feature_names: tuple[str, ...]
    rows: pd.DataFrame
    reference_parity: Mapping[str, str]
    calibration: Mapping[str, Any]
    policy_bindings: Mapping[str, Mapping[str, Any]]
    policy_digests: Mapping[str, str]
    evidence_refs: tuple[str, ...]
    execution_binding_status: str
    permissions: Mapping[str, bool]


def _fail(reason: str) -> None:
    raise FrozenInferenceError(reason)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_digest(payload: Mapping[str, Any]) -> str:
    raw = json.dumps(dict(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FrozenInferenceError(f"package_json_unreadable:{path.name}") from exc
    if not isinstance(value, dict):
        _fail(f"package_json_not_object:{path.name}")
    return value


def _required_mapping(binding: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = binding.get(key)
    if not isinstance(value, Mapping):
        _fail(f"binding_{key}_invalid")
    return value


def _required_list(binding: Mapping[str, Any], key: str) -> list[Any]:
    value = binding.get(key)
    if not isinstance(value, list):
        _fail(f"binding_{key}_invalid")
    return value


def _immutable_git_spec(
    value: Any,
    *,
    required_prefix: str | None = None,
    required_path: str | None = None,
) -> tuple[str, str]:
    if not isinstance(value, str):
        _fail("git_spec_invalid")
    ref, separator, path = value.partition(":")
    if (
        not separator
        or _COMMIT_SHA_RE.fullmatch(ref) is None
        or not path
        or "\\" in path
        or path.startswith("/")
        or any(part in {"", ".", ".."} for part in path.split("/"))
        or (required_prefix is not None and not path.startswith(required_prefix))
        or (required_path is not None and path != required_path)
    ):
        _fail("git_spec_invalid")
    return ref, path


def _read_immutable_git_json(
    repo_root: Path,
    *,
    git_spec: str,
    expected_sha256: str,
    required_path: str,
) -> dict[str, Any]:
    _immutable_git_spec(git_spec, required_path=required_path)
    if _SHA256_RE.fullmatch(expected_sha256) is None:
        _fail("calibration_evidence_sha256_invalid")
    try:
        raw = subprocess.run(
            ["git", "show", git_spec],
            cwd=repo_root,
            check=True,
            capture_output=True,
        ).stdout
        payload = json.loads(raw.decode("utf-8"))
    except (OSError, subprocess.CalledProcessError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FrozenInferenceError("calibration_evidence_unreadable") from exc
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        _fail("calibration_evidence_sha256_mismatch")
    if not isinstance(payload, dict):
        _fail("calibration_evidence_not_object")
    return payload


def _validate_frozen_calibration(
    binding: Mapping[str, Any],
    *,
    repo_root: Path,
) -> None:
    calibration = _required_mapping(binding, "calibration")
    clip_fraction = calibration.get("clip_fraction")
    if (
        isinstance(clip_fraction, bool)
        or not isinstance(clip_fraction, Real)
        or not math.isfinite(float(clip_fraction))
        or not 0.0 < float(clip_fraction) <= 1.0
    ):
        _fail("calibration_clip_fraction_invalid")

    evidence = _required_mapping(binding, "calibration_evidence")
    if set(evidence) != {"git_spec", "sha256"}:
        _fail("calibration_evidence_invalid")
    git_spec = evidence.get("git_spec")
    expected_sha256 = evidence.get("sha256")
    if not isinstance(git_spec, str) or not isinstance(expected_sha256, str):
        _fail("calibration_evidence_invalid")
    try:
        frozen = _read_immutable_git_json(
            repo_root,
            git_spec=git_spec,
            expected_sha256=expected_sha256,
            required_path=_CALIBRATION_EVIDENCE_PATH,
        )
    except FrozenInferenceError as exc:
        if str(exc) == "git_spec_invalid":
            raise FrozenInferenceError("calibration_evidence_git_spec_invalid") from exc
        raise
    qlib = frozen.get("qlib")
    if not isinstance(qlib, Mapping):
        _fail("calibration_evidence_qlib_missing")
    identity_pairs = {
        "run_id": (binding.get("run_id"), "run_id_mismatch"),
        "candidate_id": (binding.get("candidate_id"), "candidate_id_mismatch"),
        "strategy_version": (binding.get("strategy_version"), "strategy_version_mismatch"),
        "source_code_version": (binding.get("source_code_version"), "source_code_version_mismatch"),
        "archive_manifest_git_spec": (
            binding.get("archive_manifest_git_spec"),
            "archive_manifest_git_spec_mismatch",
        ),
        "archive_aggregate_sha256": (
            binding.get("archive_aggregate_sha256"),
            "archive_aggregate_sha256_mismatch",
        ),
        "data_version": (binding.get("data_version"), "data_version_mismatch"),
        "data_aggregate_sha256": (
            binding.get("data_aggregate_sha256"),
            "data_aggregate_sha256_mismatch",
        ),
        "features_in_order": (binding.get("features_in_order"), "feature_names_mismatch"),
        "infer_processors": (binding.get("infer_processors"), "infer_processors_mismatch"),
        "segments": (binding.get("segments"), "segments_mismatch"),
    }
    for key, (expected, reason) in identity_pairs.items():
        if qlib.get(key) != expected:
            _fail(reason)
    frozen_calibration = qlib.get("calibration")
    if not isinstance(frozen_calibration, Mapping):
        _fail("calibration_evidence_calibration_missing")
    if frozen_calibration.get("clip_fraction") != clip_fraction:
        _fail("calibration_clip_fraction_mismatch")


def _validate_static_binding(binding: Mapping[str, Any]) -> None:
    if binding.get("schema_version") != "strategy_v2_frozen_inference_contract_v1":
        _fail("binding_schema_mismatch")
    if binding.get("usage") != "research_only":
        _fail("usage_mismatch")
    if binding.get("output_kind") != "frozen_inference":
        _fail("output_kind_mismatch")
    spec = binding.get("archive_manifest_git_spec")
    try:
        _, manifest_path = _immutable_git_spec(spec, required_prefix=".agent/data_manifests/")
    except FrozenInferenceError as exc:
        raise FrozenInferenceError("archive_manifest_git_spec_invalid") from exc
    if not manifest_path.endswith(".json"):
        _fail("archive_manifest_git_spec_invalid")
    for key in (
        "domain",
        "source",
        "source_instrument",
        "venue_instrument",
        "qlib_instrument",
        "bar_size",
        "qlib_frequency",
    ):
        if not isinstance(binding.get(key), str) or not str(binding[key]).strip():
            _fail(f"{key}_invalid")
    time_semantics = _required_mapping(binding, "time_semantics")
    if any(time_semantics.get(key) != value for key, value in _TIME_SEMANTICS.items()):
        _fail("time_semantics_mismatch")
    if time_semantics.get("label_horizon_bars") != 12 or time_semantics.get("entry_delay_bars") != 2:
        _fail("time_semantics_mismatch")
    names = _required_list(binding, "features_in_order")
    expressions = _required_list(binding, "feature_expressions")
    if len(names) != 13 or len(expressions) != 13:
        _fail("feature_count_mismatch")
    if len(set(str(name) for name in names)) != 13:
        _fail("feature_names_mismatch")
    if _required_list(binding, "infer_processors") != [
        {"class": "Fillna", "kwargs": {"fields_group": "feature"}}
    ]:
        _fail("infer_processors_mismatch")
    comparison = _required_mapping(binding, "comparison")
    if comparison != {
        "prediction_atol": 1e-10,
        "prediction_rtol": 1e-8,
        "feature_atol": 0.0,
        "feature_rtol": 0.0,
        "tolerance_policy": "frozen_no_auto_widen",
    }:
        _fail("comparison_tolerance_mismatch")
    permissions = _required_mapping(binding, "permissions")
    if set(permissions) != set(_FALSE_PERMISSION_KEYS) or any(permissions[key] is not False for key in _FALSE_PERMISSION_KEYS):
        _fail("permission_mismatch")


def _utc_timestamp(value: Any, *, field: str) -> pd.Timestamp:
    try:
        timestamp = pd.Timestamp(value)
    except (TypeError, ValueError) as exc:
        raise FrozenInferenceError(f"{field}_invalid") from exc
    if timestamp.tz is None or timestamp.utcoffset() != pd.Timedelta(0):
        _fail(f"{field}_must_be_utc")
    return timestamp.tz_convert("UTC")


def _load_feature_frame(
    provider_dir: Path,
    *,
    feature_spec: list[list[str]],
    instrument: str,
    start_time: Any,
    end_time: Any,
) -> pd.DataFrame:
    """Load the exact Qlib expressions with a physically selected visible end."""

    if not provider_dir.is_dir():
        _fail("provider_missing")
    if len(feature_spec) != 2 or len(feature_spec[0]) != 13 or len(feature_spec[1]) != 13:
        _fail("feature_count_mismatch")
    try:
        import qlib
        from qlib.constant import REG_US
        from qlib.data.dataset.loader import QlibDataLoader
        from qlib.data.dataset.processor import Fillna
    except ImportError as exc:
        raise FrozenInferenceError("qlib_dependency_missing") from exc

    qlib.init(
        provider_uri=str(provider_dir.resolve()),
        region=REG_US,
        kernels=1,
        expression_cache=None,
        dataset_cache=None,
        clear_mem_cache=True,
    )
    try:
        loaded = QlibDataLoader(config={"feature": feature_spec}, freq="60min").load(
            instruments=[instrument],
            start_time=str(pd.Timestamp(start_time)),
            end_time=str(pd.Timestamp(end_time)),
        )
        loaded = Fillna(fields_group="feature")(loaded)
    except Exception as exc:
        raise FrozenInferenceError(f"qlib_feature_load_failed:{type(exc).__name__}") from exc
    if "feature" not in loaded.columns.get_level_values(0):
        _fail("feature_group_missing")
    features = loaded["feature"].reset_index()
    expected_columns = ["datetime", "instrument", *feature_spec[1]]
    if list(features.columns) != expected_columns:
        _fail("feature_names_mismatch")
    if features.empty or features["instrument"].astype(str).ne(instrument).any():
        _fail("qlib_instrument_mismatch")
    features["datetime"] = pd.to_datetime(features["datetime"], utc=True)
    features = features.sort_values(["datetime", "instrument"], kind="stable").reset_index(drop=True)
    numeric = features[feature_spec[1]].to_numpy(dtype=float, copy=False)
    if not np.isfinite(numeric).all():
        _fail("nonfinite_feature")
    if not all(dtype == np.dtype("float32") for dtype in features[feature_spec[1]].dtypes):
        _fail("feature_dtype_mismatch")
    if features.duplicated(["datetime", "instrument"]).any():
        _fail("feature_row_duplicate")
    return features


def _package_policy_bindings(config: Mapping[str, Any], strategy_manifest: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    research = config.get("research_simulation", {})
    cost = strategy_manifest.get("cost_model", {})
    slippage = strategy_manifest.get("slippage_model", {})
    return {
        "position": {
            "engine": research.get("engine"),
            "risk_budget_fraction": research.get("risk_budget_fraction"),
            "max_weight": research.get("max_weight"),
            "volatility_target_annual_configured": research.get("volatility_target_annual"),
            "volatility_target_applied": False,
        },
        "exit": {
            "hard_stop_fraction": research.get("hard_stop_fraction"),
            "trailing_stop_fraction": research.get("trailing_stop_fraction"),
            "maximum_holding_bars": research.get("maximum_holding_bars"),
        },
        "cost": {
            "fee_bps_per_side": cost.get("fee_bps_per_side"),
            "funding": cost.get("funding"),
            "slippage_bps_per_side": slippage.get("bps_per_side"),
            "spread_bps_per_side": research.get("spread_bps"),
            "impact_bps_per_side": research.get("impact_bps"),
            "fill": slippage.get("fill"),
            "execution_delay_bars": slippage.get("execution_delay_bars"),
        },
    }


def _reference_decisions(path: Path, *, run_id: str) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as source:
            for line in source:
                payload = json.loads(line)
                if payload.get("qlib_run_id") != run_id:
                    _fail("decision_run_id_mismatch")
                alpha = payload.get("layers", {}).get("alpha", {})
                decision_time = _utc_timestamp(payload.get("decision_time"), field="decision_time")
                rows.append(
                    {
                        "event_time": decision_time - pd.Timedelta(hours=1),
                        "decision_time": decision_time,
                        "reference_raw_score": float(alpha["raw_score"]),
                        "reference_calibrated_prediction": float(alpha["expected_return_bps"]) / 10_000.0,
                    }
                )
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise FrozenInferenceError("research_decisions_unreadable") from exc
    result = pd.DataFrame(rows)
    if result.empty or result.duplicated("event_time").any():
        _fail("research_decisions_invalid")
    return result.sort_values("event_time", kind="stable").reset_index(drop=True)


def _predict(model: Any, values: np.ndarray, *, mode: str) -> np.ndarray:
    if mode == "batch":
        result = np.asarray(model.predict(values), dtype=float)
    elif mode == "one_by_one":
        result = np.asarray([float(model.predict(row.reshape(1, -1))[0]) for row in values], dtype=float)
    else:
        _fail("prediction_mode_invalid")
    if result.ndim != 1 or len(result) != len(values) or not np.isfinite(result).all():
        _fail("model_prediction_invalid")
    return result


def run_frozen_inference(
    binding: Mapping[str, Any],
    *,
    repo_root: Path,
    shared_root: Path | None = None,
    visible_through: Any | None = None,
    prediction_mode: str = "batch",
) -> FrozenInferenceResult:
    """Resolve, verify and replay one sealed research-only inference package."""

    if not isinstance(binding, Mapping):
        _fail("binding_not_object")
    _validate_static_binding(binding)
    repo_root = Path(repo_root).resolve()
    _validate_frozen_calibration(binding, repo_root=repo_root)
    manifest = load_manifest_from_git(repo_root, str(binding["archive_manifest_git_spec"]))
    if manifest.get("aggregate_sha256") != binding.get("archive_aggregate_sha256"):
        _fail("archive_aggregate_sha256_mismatch")
    archive_root = resolve_manifest_payload(
        manifest,
        shared_root=(Path(shared_root).resolve() if shared_root is not None else default_shared_data_root(repo_root)),
        verify_files=True,
    ).resolve()
    run_root = (archive_root / "qlib_runs" / str(binding["run_id"])).resolve()
    try:
        run_root.relative_to(archive_root)
    except ValueError as exc:
        raise FrozenInferenceError("run_root_outside_archive") from exc
    sealed = read_sealed_evidence(run_root)
    if sealed.get("integrity_status") != "passed":
        blockers = ",".join(str(value) for value in sealed.get("blockers", []))
        _fail(f"sealed_evidence_blocked:{blockers}")

    artifact_hashes = _required_mapping(binding, "artifact_sha256")
    for name, expected in artifact_hashes.items():
        path = (run_root / str(name)).resolve()
        try:
            path.relative_to(run_root)
        except ValueError as exc:
            raise FrozenInferenceError("artifact_path_outside_run") from exc
        if not path.is_file() or _sha256(path) != expected:
            _fail(f"artifact_sha256_mismatch:{name}")

    try:
        import lightgbm as lgb
        import yaml
    except ImportError as exc:
        raise FrozenInferenceError("inference_dependency_missing") from exc
    try:
        config = yaml.safe_load((run_root / "qlib_workflow_config.yaml").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise FrozenInferenceError("workflow_config_unreadable") from exc
    if not isinstance(config, dict):
        _fail("workflow_config_not_object")
    strategy_manifest = _read_json(run_root / "qlib_strategy_manifest.json")
    dataset_manifest = _read_json(run_root / "qlib_input/dataset_manifest.json")
    trace = _read_json(run_root / "research_trace.json")

    identity_checks = {
        "candidate_id": (trace.get("identity", {}).get("candidate_id"), binding.get("candidate_id")),
        "source_code_version": (trace.get("identity", {}).get("code_version"), binding.get("source_code_version")),
        "strategy_id": (strategy_manifest.get("strategy_id"), binding.get("strategy_id")),
        "strategy_version": (strategy_manifest.get("strategy_version"), binding.get("strategy_version")),
        "model_id": (strategy_manifest.get("model_id"), binding.get("model_id")),
        "profile_id": (strategy_manifest.get("profile_id"), binding.get("profile_id")),
        "feature_set": (strategy_manifest.get("feature_set"), binding.get("feature_set")),
        "data_version": ((strategy_manifest.get("data_versions") or [None])[0], binding.get("data_version")),
    }
    for name, (actual, expected) in identity_checks.items():
        if actual != expected:
            _fail(f"{name}_mismatch")
    input_contract = dataset_manifest.get("input_contract", {})
    instrument_identity = input_contract.get("instrument_identity", {})
    archive_identity_checks = {
        "domain": (input_contract.get("asset_class"), binding.get("domain")),
        "source": (input_contract.get("source"), binding.get("source")),
        "source_instrument": (instrument_identity.get("source_symbol"), binding.get("source_instrument")),
        "venue_instrument": (instrument_identity.get("venue_instrument_id"), binding.get("venue_instrument")),
        "qlib_instrument": (instrument_identity.get("qlib_instrument"), binding.get("qlib_instrument")),
        "bar_size": (input_contract.get("bar_size"), binding.get("bar_size")),
        "data_aggregate_sha256": (input_contract.get("aggregate_sha256"), binding.get("data_aggregate_sha256")),
    }
    for name, (actual, expected) in archive_identity_checks.items():
        if actual != expected:
            _fail(f"{name}_mismatch")
    if config.get("mode") != "research_only" or config.get("paper_enabled") or config.get("live_enabled"):
        _fail("workflow_permission_mismatch")

    handler = config.get("task", {}).get("dataset", {}).get("kwargs", {}).get("handler", {}).get("kwargs", {})
    feature_spec = handler.get("data_loader", {}).get("kwargs", {}).get("config", {}).get("feature")
    expected_feature_spec = [binding["feature_expressions"], binding["features_in_order"]]
    if not isinstance(feature_spec, list) or len(feature_spec) != 2:
        _fail("feature_contract_missing")
    if handler.get("data_loader", {}).get("kwargs", {}).get("freq") != binding.get("qlib_frequency"):
        _fail("qlib_frequency_mismatch")
    if feature_spec[1] != expected_feature_spec[1]:
        _fail("feature_names_mismatch")
    if feature_spec[0] != expected_feature_spec[0]:
        _fail("feature_expressions_mismatch")
    if handler.get("infer_processors") != binding.get("infer_processors"):
        _fail("infer_processors_mismatch")
    if handler.get("learn_processors") != [{"class": "DropnaLabel"}]:
        _fail("learn_processors_mismatch")
    if config.get("task", {}).get("dataset", {}).get("kwargs", {}).get("segments") != binding.get("segments"):
        _fail("segments_mismatch")
    if [handler.get("start_time"), handler.get("end_time")] != binding.get("handler_range"):
        _fail("handler_range_mismatch")

    policies = _package_policy_bindings(config, strategy_manifest)
    if policies != binding.get("policy_bindings"):
        _fail("policy_bindings_mismatch")
    calibration = dict(binding["calibration"])
    trace_calibration = trace.get("calibration", {})
    for key in ("method", "intercept", "slope", "sample_size", "score_units", "limitation"):
        if trace_calibration.get(key) != calibration.get(key):
            _fail(f"calibration_{key}_mismatch")

    model = lgb.Booster(model_str=(run_root / "model.txt").read_text(encoding="utf-8"))
    if model.num_trees() != binding.get("loaded_tree_count") or model.num_feature() != 13:
        _fail("model_shape_mismatch")
    if model.feature_name() != binding.get("model_internal_feature_names"):
        _fail("model_feature_names_mismatch")

    test_start, test_end = binding["segments"]["test"]
    visible_end = pd.Timestamp(test_end)
    if visible_through is not None:
        decision_cutoff = _utc_timestamp(visible_through, field="visible_through")
        if decision_cutoff.floor("h") != decision_cutoff:
            _fail("visible_through_not_hour_aligned")
        visible_end = min(visible_end, decision_cutoff.tz_localize(None) - pd.Timedelta(hours=1))
    if visible_end < pd.Timestamp(test_start):
        _fail("no_visible_test_rows")

    features = _load_feature_frame(
        run_root / "qlib_provider",
        feature_spec=expected_feature_spec,
        instrument=str(binding["qlib_instrument"]),
        start_time=binding["handler_range"][0],
        end_time=visible_end,
    )
    features = features.loc[
        (features["datetime"] >= pd.Timestamp(test_start, tz="UTC"))
        & (features["datetime"] <= visible_end.tz_localize("UTC"))
    ].reset_index(drop=True)
    if features.empty:
        _fail("no_visible_test_rows")
    values = features[binding["features_in_order"]].to_numpy(copy=False)
    raw_scores = _predict(model, values, mode=prediction_mode)
    calibrated = np.clip(
        calibration["intercept"] + calibration["slope"] * raw_scores,
        -calibration["clip_fraction"],
        calibration["clip_fraction"],
    )

    reference_scores = pd.read_parquet(run_root / "pred_score.parquet")
    reference_scores["event_time"] = pd.to_datetime(reference_scores["datetime"], utc=True)
    reference_scores = reference_scores.loc[
        (reference_scores["event_time"] >= pd.Timestamp(test_start, tz="UTC"))
        & (reference_scores["event_time"] <= visible_end.tz_localize("UTC"))
    ]
    if reference_scores["run_id"].astype(str).ne(binding["run_id"]).any():
        _fail("reference_run_id_mismatch")
    if reference_scores["symbol"].astype(str).ne(binding["qlib_instrument"]).any():
        _fail("reference_instrument_mismatch")
    reference_scores = reference_scores[["event_time", "score"]].rename(columns={"score": "reference_raw_score"})
    reference_decisions = _reference_decisions(run_root / "research_decisions.jsonl", run_id=str(binding["run_id"]))
    reference_decisions = reference_decisions.loc[reference_decisions["event_time"] <= visible_end.tz_localize("UTC")]

    rows = features.rename(columns={"datetime": "event_time"}).drop(columns="instrument")
    rows["available_time"] = rows["event_time"] + pd.Timedelta(hours=1)
    rows["decision_time"] = rows["available_time"]
    rows["raw_score"] = raw_scores
    rows["calibrated_prediction"] = calibrated
    rows = rows.merge(reference_scores, on="event_time", how="left", validate="one_to_one")
    rows = rows.merge(
        reference_decisions[["event_time", "decision_time", "reference_calibrated_prediction"]],
        on=["event_time", "decision_time"],
        how="left",
        validate="one_to_one",
    )
    if rows[["reference_raw_score", "reference_calibrated_prediction"]].isna().any().any():
        _fail("reference_prediction_missing")
    atol = float(binding["comparison"]["prediction_atol"])
    rtol = float(binding["comparison"]["prediction_rtol"])
    if not np.allclose(rows["raw_score"], rows["reference_raw_score"], atol=atol, rtol=rtol):
        _fail("raw_score_parity_failed")
    if not np.allclose(
        rows["calibrated_prediction"], rows["reference_calibrated_prediction"], atol=atol, rtol=rtol
    ):
        _fail("calibrated_prediction_parity_failed")
    if visible_through is None and len(rows) != int(binding["decision_count"]):
        _fail("decision_count_mismatch")

    rows.insert(3, "output_kind", "frozen_inference")
    rows.insert(4, "prediction_unit", calibration["score_units"])
    return FrozenInferenceResult(
        usage="research_only",
        output_kind="frozen_inference",
        run_id=str(binding["run_id"]),
        candidate_id=str(binding["candidate_id"]),
        strategy_id=str(binding["strategy_id"]),
        strategy_version=str(binding["strategy_version"]),
        package_digest=str(binding["archive_aggregate_sha256"]),
        model_sha256=str(artifact_hashes["model.txt"]),
        feature_names=tuple(str(value) for value in binding["features_in_order"]),
        rows=rows,
        reference_parity={
            "features": "passed_same_sealed_provider_config_and_order",
            "raw_score": "passed",
            "calibrated_prediction": "passed",
        },
        calibration=calibration,
        policy_bindings=policies,
        policy_digests={name: _canonical_digest(value) for name, value in policies.items()},
        evidence_refs=(
            str(binding["archive_manifest_git_spec"]),
            "run_seal.json",
            "qlib_workflow_config.yaml",
            "model.txt",
            "pred_score.parquet",
            "research_decisions.jsonl",
        ),
        execution_binding_status="not_bound_research_only",
        permissions={key: False for key in _FALSE_PERMISSION_KEYS},
    )
