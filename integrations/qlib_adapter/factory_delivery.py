"""Content verification and explicit create-only factory delivery production.

No training, model selection, old seal rewrite or inferred policy defaults.
"""
from copy import deepcopy
from io import BytesIO
import json
import os
from pathlib import Path
import subprocess
import sys

import numpy as np
import pandas as pd

from quant_shared.strategy_delivery.models import DeliveryError, canonical, digest
from quant_shared.strategy_delivery.package_evidence import paired_metrics, policy_payload, calibrated_quality


def _stamp(value):
    t = pd.Timestamp(value)
    return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")


def _sealed_model_predict(model_text, frame):
    payload = {"model_text": model_text.replace("\r\n", "\n").replace("\r", "\n"),
        "values": [[None if pd.isna(value) else float(value) for value in row]
            for row in frame.to_numpy(dtype=float)]}
    script = ("import json,sys,numpy as np,lightgbm as lgb;"
        "p=json.load(sys.stdin);b=lgb.Booster(model_str=p['model_text']);"
        "sys.stdout.write(json.dumps({'feature_names':b.feature_name(),"
        "'predictions':b.predict(np.asarray(p['values'],dtype=float),num_threads=1).tolist()},"
        "sort_keys=True,separators=(',',':')))" )
    try:
        completed = subprocess.run([sys.executable, "-c", script], input=json.dumps(payload),
            text=True, capture_output=True, timeout=120, check=False)
        if completed.returncode != 0:
            raise DeliveryError("factory_final_model_verification_process_failed")
        value = json.loads(completed.stdout)
        return value["feature_names"], np.asarray(value["predictions"], dtype=float)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise DeliveryError("factory_final_model_verification_process_failed") from exc


def _reproduce_v2_rows(package, read, rows_by_segment, windows):
    features = pd.read_parquet(BytesIO(read("factory_features.parquet")))
    labels = pd.read_parquet(BytesIO(read("factory_labels.parquet")))
    for frame in (features, labels):
        if frame.index.names != ["datetime", "instrument"] or frame.index.duplicated().any():
            raise DeliveryError("final_audit_index_invalid")
        frame.index = pd.MultiIndex.from_arrays([
            pd.to_datetime(frame.index.get_level_values("datetime"), utc=True),
            frame.index.get_level_values("instrument").astype(str)], names=["datetime", "instrument"])
    if (not features.index.equals(labels.index) or list(labels) != ["label"]
        or list(features) != package["contracts"]["features"]["names"]):
        raise DeliveryError("final_audit_feature_label_alignment_invalid")
    reproduced = {}
    for segment, rows in rows_by_segment.items():
        try:
            index = pd.MultiIndex.from_tuples([(_stamp(row["event_time"]), str(row["instrument"])) for row in rows],
                names=["datetime", "instrument"])
            if index.duplicated().any() or not index.isin(features.index).all():
                raise DeliveryError("factory_final_rows_outside_sealed_features")
            start, end = map(_stamp, windows[segment])
            if any(not start <= when <= end for when in index.get_level_values("datetime")):
                raise DeliveryError("factory_final_rows_outside_segment")
            frame = features.reindex(index)
            claimed = np.asarray([[np.nan if value is None else float(value) for value in row["features"]]
                for row in rows], dtype=float)
            if claimed.shape != frame.shape or not np.allclose(claimed, frame.to_numpy(dtype=float),
                    rtol=0, atol=0, equal_nan=True):
                raise DeliveryError("factory_final_feature_rows_changed")
            feature_names, predicted = _sealed_model_predict(package["model"]["text"], frame)
            if list(features) != feature_names:
                raise DeliveryError("final_audit_model_features_mismatch")
            raw = np.asarray([float(row["raw_score"]) for row in rows])
            label = np.asarray([float(row["label"]) for row in rows])
            if (not np.isfinite(predicted).all() or not np.allclose(predicted, raw, rtol=1e-12, atol=1e-14)
                or not np.allclose(labels.label.reindex(index).to_numpy(dtype=float), label, rtol=0, atol=0)):
                raise DeliveryError("factory_final_model_row_reproduction_failed")
            reproduced[segment] = pd.Series(predicted, index=index, name="score")
        except (KeyError, TypeError, ValueError) as exc:
            raise DeliveryError("factory_final_rows_invalid") from exc
    return reproduced, labels


def verify_final_audit(package, read, candidate, windows, profile, frozen_policy=None):
    """Reproduce sealed audit scores with the sealed final model, never refit."""
    try:
        finalization = json.loads(read("factory_finalization_receipt.json"))
    except DeliveryError as exc:
        if "package_artifact_missing:factory_finalization_receipt.json" not in str(exc):
            raise
        finalization = None
    if finalization is not None:
        calibration_seal_raw = read("factory_calibration_seal.json")
        calibration_seal = json.loads(calibration_seal_raw)
        operation_order = ["policy_freeze", "final_fit", "model_seal", "validation_prediction",
            "calibration_seal", "audit_prediction"]
        wall = finalization.get("wall_operations", {})
        wall_names = ("policy_committed_at", "final_fit_started_at", "final_fit_completed_at", "model_sealed_at",
            "validation_prediction_started_at", "validation_prediction_completed_at", "calibration_sealed_at",
            "audit_prediction_started_at", "audit_prediction_completed_at")
        expected_policy = {"policies": policy_payload(package["contracts"]),
            "clip_fraction": package["contracts"]["calibration"]["clip_fraction"],
            "frozen_at": (frozen_policy or {}).get("frozen_at")}
        if (finalization.get("schema_version") != "factory_finalization_receipt_v1"
            or calibration_seal.get("schema_version") != "factory_calibration_seal_v1"
            or finalization.get("run_id") != package["audit_binding"]["qlib_run_id"]
            or finalization.get("candidate_id") != package["source"]["candidate_id"]
            or finalization.get("fit_count") != 1
            or finalization.get("prediction_calls") != ["validation_once", "audit_once"]
            or finalization.get("signal_record_generated") is not False
            or finalization.get("audit_opened_after_calibration_seal") is not True
            or finalization.get("calibration_seal_sha256") != __import__("hashlib").sha256(
                calibration_seal_raw).hexdigest()
            or finalization.get("validation_rows_sha256") != calibration_seal.get("validation_rows_sha256")
            or finalization.get("audit_rows_sha256") != digest(finalization.get("audit_rows"))
            or calibration_seal.get("quality_passed") is not True
            or calibration_seal.get("prediction_call") != 1
            or finalization.get("model_sha256") != package["model"]["sha256"]
            or calibration_seal.get("model_sha256") != package["model"]["sha256"]
            or finalization.get("source_head") != package["source_head"]
            or calibration_seal.get("source_head") != package["source_head"]
            or finalization.get("policy_sha256") != digest(expected_policy)
            or calibration_seal.get("policy_sha256") != digest(expected_policy)
            or finalization.get("operation_order") != operation_order
            or set(wall) != set(wall_names)
            or calibration_seal.get("sealed_at") != wall.get("calibration_sealed_at")):
            raise DeliveryError("factory_finalization_receipt_invalid")
        try:
            operation_times = [_stamp(wall[name]) for name in wall_names]
        except (TypeError, ValueError):
            raise DeliveryError("factory_finalization_operation_time_invalid")
        if operation_times != sorted(operation_times):
            raise DeliveryError("factory_finalization_operation_order_invalid")
        validation_rows = calibration_seal.get("validation_rows")
        audit_rows = finalization.get("audit_rows")
        if digest(validation_rows) != calibration_seal.get("validation_rows_sha256"):
            raise DeliveryError("factory_calibration_rows_changed")
        scores = pd.read_parquet(BytesIO(read("pred_score.parquet"))).rename(columns={"symbol":"instrument"})
        observed = [{"event_time": _stamp(row.datetime).isoformat(), "instrument": row.instrument,
            "raw_score": float(row.score)} for row in scores.itertuples(index=False)]
        expected = [{key: row[key] for key in ("event_time", "instrument", "raw_score")} for row in audit_rows]
        if observed != expected:
            raise DeliveryError("factory_final_audit_prediction_binding_mismatch")
        reproduced, labels = _reproduce_v2_rows(package, read,
            {"valid": validation_rows, "test": audit_rows}, windows)
        from quant_shared.alpha_factory.evaluation import signal_metrics
        audit_metric = signal_metrics(reproduced["test"], labels.label.reindex(reproduced["test"].index), profile["metric_mode"])
        if digest(audit_metric) != digest(candidate.get("audit_metrics")):
            raise DeliveryError("factory_final_audit_metrics_mismatch")
        return {"schema_version":"factory_delivery_evidence_v2",
            "identity": {k:package[k] for k in ("data_version","instrument","bar_size","source_head")},
            "model_sha256":package["model"]["sha256"],
            "feature_specs_sha256":digest(package["contracts"]["features"]["specs"]),
            "windows":{k:[_stamp(v).isoformat() for v in w] for k,w in windows.items()},
            "fit_rows":validation_rows, "audit_rows":audit_rows,
            "audit_metrics":candidate.get("audit_metrics"),
            "finalization_receipt_sha256":digest(finalization),
            "calibration_seal_sha256":digest(calibration_seal),
            "prediction_reproduction":"sealed_model_recomputed_validation_and_audit"}
    import lightgbm as lgb
    from quant_shared.alpha_factory.evaluation import signal_metrics
    features = pd.read_parquet(BytesIO(read("factory_features.parquet")))
    labels = pd.read_parquet(BytesIO(read("factory_labels.parquet")))
    scores = pd.read_parquet(BytesIO(read("pred_score.parquet")))
    manifest = json.loads(read("qlib_input/dataset_manifest.json"))
    recorder = json.loads(read("recorder_metrics.json"))
    if (manifest.get("run_id") != package["audit_binding"]["qlib_run_id"]
        or manifest.get("data_version") != package["data_version"]
        or manifest.get("bar_size") != package["bar_size"]
        or manifest.get("symbols") != [package["instrument"]]
        or manifest.get("files") != {"features":"factory_features.parquet", "labels":"factory_labels.parquet"}
        or not recorder.get("id") or not isinstance(recorder.get("metrics"), dict)):
        raise DeliveryError("final_audit_input_identity_mismatch")
    for frame in (features, labels):
        if frame.index.names != ["datetime", "instrument"] or frame.index.duplicated().any():
            raise DeliveryError("final_audit_index_invalid")
        frame.index = pd.MultiIndex.from_arrays([
            pd.to_datetime(frame.index.get_level_values("datetime"), utc=True),
            frame.index.get_level_values("instrument")], names=["datetime", "instrument"])
        if set(frame.index.get_level_values("instrument")) != {package["instrument"]}:
            raise DeliveryError("final_audit_asset_mismatch")
    if (not features.index.equals(labels.index) or list(labels) != ["label"]
        or list(features) != package["contracts"]["features"]["names"]):
        raise DeliveryError("final_audit_feature_label_alignment_invalid")
    model = lgb.Booster(model_str=package["model"]["text"])
    if list(features) != model.feature_name(): raise DeliveryError("final_audit_model_features_mismatch")
    scores = scores.rename(columns={"symbol":"instrument"})
    scores["datetime"] = pd.to_datetime(scores.datetime, utc=True)
    scores = scores.set_index(["datetime", "instrument"])["score"].sort_index()
    times = features.index.get_level_values("datetime")
    audit_features = features.loc[(times >= _stamp(windows["test"][0])) & (times <= _stamp(windows["test"][1]))]
    if not audit_features.index.equals(scores.index) or scores.index.duplicated().any():
        raise DeliveryError("final_audit_prediction_window_mismatch")
    predicted = model.predict(audit_features, num_threads=1)
    if not np.isfinite(predicted).all() or not np.allclose(predicted, scores, rtol=1e-12, atol=1e-14):
        raise DeliveryError("final_audit_prediction_reproduction_failed")
    metric = signal_metrics(scores, labels.label.reindex(scores.index), profile["metric_mode"])
    if digest(metric) != digest(candidate.get("audit_metrics")):
        raise DeliveryError("final_audit_metrics_mismatch")
    # Recorder metrics may omit signal analysis in factory workflows. The
    # authoritative factory metrics above must still reproduce in full.
    def rows(window):
        f = features.loc[(times >= _stamp(window[0])) & (times <= _stamp(window[1]))]
        y = labels.label.reindex(f.index)
        keep = y.notna()
        f, y = f.loc[keep], y.loc[keep]
        raw = model.predict(f, num_threads=1)
        if not np.isfinite(raw).all() or np.isinf(f.to_numpy()).any():
            raise DeliveryError("final_audit_nonfinite_features_or_scores")
        return [{"event_time": t.isoformat(), "instrument": inst,
                 "features": [None if pd.isna(v) else float(v) for v in values],
                 "raw_score": float(x), "label": float(label)}
                for (t,inst),values,x,label in zip(f.index, f.to_numpy(), raw, y)]
    return {"schema_version":"factory_delivery_evidence_v1",
        "identity": {k:package[k] for k in ("data_version","instrument","bar_size","source_head")},
        "model_sha256":package["model"]["sha256"],
        "feature_specs_sha256":digest(package["contracts"]["features"]["specs"]),
        "windows":{k:[_stamp(v).isoformat() for v in w] for k,w in windows.items()},
        "fit_rows":rows(windows["valid"]), "audit_rows":rows(windows["test"]),
        "audit_metrics":metric, "dataset_manifest_sha256":digest(manifest),
        "recorder_sha256":digest(recorder)}


def bind_receipt(package, verified, frozen_policy):
    """Bind existing candidate parameters; recomputation is validation, not fitting."""
    c = package["contracts"]
    receipt = deepcopy(verified)
    for name in ("fit_rows", "audit_rows"): receipt[name+"_sha256"] = digest(receipt[name])
    receipt.update(frozen_policy=deepcopy(frozen_policy), frozen_policy_sha256=digest(frozen_policy))
    cal = c["calibration"]
    calculated = paired_metrics(receipt["fit_rows"])
    if any(not np.isclose(cal[k], calculated[k], rtol=1e-10, atol=1e-12) for k in ("intercept","slope")):
        raise DeliveryError("candidate_calibration_does_not_reproduce")
    # Evidence metadata is derived, never accepted from a submitted quality flag.
    q = calibrated_quality(receipt["fit_rows"], cal)
    e = {"candidate_id":package["source"]["candidate_id"], "qlib_run_id":package["audit_binding"]["qlib_run_id"],
        "model_sha256":package["model"]["sha256"], "feature_specs_sha256":receipt["feature_specs_sha256"],
        "data_version":package["data_version"], "output_sha256":digest(c["output"]), "fit_scope":"validation_only",
        "fitted_through":max(r["event_time"] for r in receipt["fit_rows"]), "sample_size":len(receipt["fit_rows"]),
        "quality":q, "quality_passed":q["ic"]>0 and q["hit_rate"]>.5,
        "parameters_sha256":digest({k:cal[k] for k in ("intercept","slope","clip_fraction")}),
        "fit_rows_sha256":receipt["fit_rows_sha256"], "audit_rows_sha256":receipt["audit_rows_sha256"]}
    cal.update(evidence=e, evidence_sha256=digest(e))
    package.update(evidence_receipt=receipt, evidence_receipt_sha256=digest(receipt))
    return package


def build_factory_delivery_contract(reference, envelope, frozen_evidence):
    """Assemble a complete runtime contract from source facts + explicit policy.

    Dependency versions and calibration parameters must already be frozen by
    the candidate owner; this function does not estimate them or supply defaults.
    """
    from quant_shared.strategy_delivery.runtime_contract import feature_warmup
    from .package_inference import feature_implementation
    result=envelope["result"]
    matches=[c for c in result["candidates"] if c["candidate_id"]==reference["candidate_id"]]
    if len(matches)!=1: raise DeliveryError("factory_candidate_unknown_or_ambiguous")
    candidate=matches[0]
    try:
        frozen=deepcopy(frozen_evidence["frozen_policy"])
        if (frozen["candidate_id"]!=candidate["candidate_id"]
            or frozen["qlib_run_id"]!=candidate["qlib_run_id"]
            or frozen["data_version"]!=candidate["data_version"]):
            raise DeliveryError("factory_frozen_evidence_candidate_mismatch")
        specs=candidate["feature_specs"]
        receipt_version = ("factory_delivery_evidence_v2"
            if result.get("request", {}).get("acceptance_profile") == "btc_real_candidate_offline_20260930_v1"
            else "factory_delivery_evidence_v1")
        if frozen_evidence.get("receipt_version", receipt_version) != receipt_version:
            raise DeliveryError("factory_delivery_receipt_version_mismatch")
        is_v2 = receipt_version == "factory_delivery_evidence_v2"
        model_dependencies = deepcopy(frozen_evidence["model_dependencies"])
        feature_dependencies = deepcopy(frozen_evidence["feature_dependencies"])
        if is_v2 and (not isinstance(model_dependencies, dict)
            or not isinstance(feature_dependencies, dict)
            or set(model_dependencies) != {"lightgbm", "qlib"}
            or set(feature_dependencies) != {"numpy", "pandas"}
            or not all(isinstance(value, str) and value for value in
                [*model_dependencies.values(), *feature_dependencies.values()])):
            raise DeliveryError("factory_frozen_dependency_versions_invalid")
        contracts={**deepcopy(frozen["policies"]),
            "calibration":deepcopy(frozen_evidence["calibration"]),
            "features":{"version":"factory_safe_ast_v1","primitive_version":"factory_primitives_v1",
                "specs":specs,"names":[s["factor_id"] for s in specs],"warmup_bars":feature_warmup(specs),
                "annualization":result["profile"]["annualization"],"input_instrument":",".join(result["profile"]["symbols"])},
            "preprocessing":{"version":"factory_processors_v1","infer_processors":[],"fitted_state":None,
                "missing":"native_nan","dtype":"float64"},
            "time":{"version":"factory_decision_time_v1","event_time":"completed_bar_open_utc",
                "available_time":"event_time_plus_1h","feature_time":"decision_time","data_cutoff":"decision_time",
                "label_time":"bar_open_index","prediction_time_offset_bars":1,
                "prediction_start":(_stamp(result["split_plan"]["segments"]["audit"][0])
                    + (pd.Timedelta(0) if is_v2 else pd.Timedelta(hours=1))).isoformat(),
                **({"temporal_receipt":{"schema_version":"factory_temporal_receipt_v2",
                    "wall_operations":deepcopy(frozen_evidence["wall_operations"]),
                    "historical_data_time":{"audit_decision_start":_stamp(result["split_plan"]["segments"]["audit"][0]).isoformat(),
                        "audit_decision_end":_stamp(result["split_plan"]["segments"]["audit"][1]).isoformat()},
                    "operation_order":list(frozen_evidence["operation_order"])}}
                    if is_v2 else {})},
            "state":{"version":"candidate_state_v1","authority":"existing_btc_offline_runtime_and_ledger"}}
        return {"contracts":contracts,"frozen_policy":frozen,
            "model_dependencies":model_dependencies,
            "feature_implementation":{**feature_implementation(source_head=envelope["source_head"]),
                "dependencies":feature_dependencies},
            "settlement_evidence":deepcopy(frozen_evidence["settlement_evidence"])}
    except (KeyError,TypeError) as exc:
        raise DeliveryError("factory_frozen_delivery_evidence_missing") from exc


def publish_factory_delivery(reference, envelope, run_root, *, destination, frozen_contract=None, frozen_evidence=None):
    """Explicit producer, separate immutable delivery artifact beside old research.

    The input must be candidate-owned, already frozen contract and policy. Missing
    calibration/policy evidence is rejected, never sourced from another candidate.
    The artifact contains the generated candidate.delivery_contract plus package.
    Callers must retain its digest as the explicit source revision.
    """
    from .factory_package import compile_factory_package
    if (frozen_contract is None)==(frozen_evidence is None):
        raise DeliveryError("factory_exactly_one_frozen_evidence_input_required")
    if frozen_evidence is not None:
        frozen_contract=build_factory_delivery_contract(reference,envelope,frozen_evidence)
    original = deepcopy(envelope)
    rows = [c for c in original["result"]["candidates"] if c["candidate_id"] == reference["candidate_id"]]
    if len(rows) != 1: raise DeliveryError("factory_candidate_unknown_or_ambiguous")
    original["delivery_contract"] = deepcopy(frozen_contract)
    package = compile_factory_package(reference, original, run_root, produce_evidence=True)
    from quant_shared.strategy_delivery.models import validate_package
    blockers = validate_package(package, "offline")
    if blockers: raise DeliveryError("factory_delivery_blocked:" + ",".join(blockers))
    generated = deepcopy(frozen_contract)
    generated.update(contracts=package["contracts"], evidence_receipt=package["evidence_receipt"],
                     evidence_receipt_sha256=package["evidence_receipt_sha256"])
    artifact = {"schema_version":"factory_candidate_delivery_v1", "source":reference,
        "factory_source_result_sha256":digest(envelope["result"]),
        "candidate":{"candidate_id":reference["candidate_id"], "delivery_contract":generated},
        "package":package}
    raw = canonical(artifact).encode()
    with Path(destination).open("xb") as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    return {"content_digest":digest(artifact), "package_digest":digest(package), "artifact":artifact}


class FactoryDeliveryReader:
    """Explicit immutable revisions, never discovers a newest package.

    Each configured item is (artifact_path, expected_digest). This adapter only
    reads; publication is a separate explicit command. Original factory evidence
    remains the source of identity and audit hashes on every resolve/restart.
    """
    def __init__(self, factory_reader, artifacts):
        self.factory_reader = factory_reader
        self.artifacts = artifacts if hasattr(artifacts, "artifacts") else tuple(artifacts)

    def get(self, run_id, *, candidate_id=None, package_digest=None):
        envelope = deepcopy(self.factory_reader.get(run_id))
        found = []
        items = (self.artifacts.artifacts(run_id, candidate_id, package_digest)
                 if hasattr(self.artifacts, "artifacts") else self.artifacts)
        for path, expected_digest in items:
            raw = Path(path).read_bytes()
            if len(raw) > 64_000_000: raise DeliveryError("factory_delivery_oversized")
            artifact = json.loads(raw)
            if digest(artifact) != expected_digest: raise DeliveryError("factory_delivery_artifact_changed")
            if (artifact["source"]["run_id"] == run_id
                and (candidate_id is None or artifact["source"]["candidate_id"] == candidate_id)
                and (package_digest is None or digest(artifact["package"]) == package_digest)):
                found.append(artifact)
        if len(found) != 1: raise DeliveryError("factory_delivery_revision_missing_or_ambiguous")
        artifact = found[0]
        if (artifact.get("schema_version") != "factory_candidate_delivery_v1"
            or artifact["factory_source_result_sha256"] != digest(envelope["result"])):
            raise DeliveryError("factory_delivery_original_source_changed")
        candidate = artifact["candidate"]
        if candidate["candidate_id"] != artifact["source"]["candidate_id"]:
            raise DeliveryError("factory_delivery_candidate_mismatch")
        envelope["delivery_contract"] = candidate["delivery_contract"]
        envelope["delivery_expected_package_digest"] = digest(artifact["package"])
        return envelope
