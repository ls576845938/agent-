"""Recomputable package receipts. No files, model loading, fitting or execution.

Hashes bind content; they are not a substitute for the source adapter verifying
that the content is in the nominated immutable research audit.
"""
from __future__ import annotations

import math
from datetime import timedelta
from .models import DeliveryError, digest, utc


def paired_metrics(rows):
    if not isinstance(rows, list) or len(rows) < 30:
        raise DeliveryError("evidence_insufficient_samples")
    pairs = [(r["raw_score"], r["label"]) for r in rows]
    if any(type(v) not in (int, float) or not math.isfinite(v) for pair in pairs for v in pair):
        raise DeliveryError("evidence_nonfinite_sample")
    n = len(pairs)
    mx, my = (math.fsum(p[i] for p in pairs) / n for i in (0, 1))
    xx = math.fsum((x-mx)**2 for x, _ in pairs)
    yy = math.fsum((y-my)**2 for _, y in pairs)
    xy = math.fsum((x-mx)*(y-my) for x, y in pairs)
    if xx <= 0 or yy <= 0: raise DeliveryError("evidence_degenerate_samples")
    slope = xy / xx
    return {"intercept": my-slope*mx, "slope": slope,
            "quality": {"ic": xy/math.sqrt(xx*yy),
                        "hit_rate": sum((x > 0)-(x < 0) == (y > 0)-(y < 0) for x,y in pairs)/n}}


def policy_payload(contracts):
    return {k: contracts[k] for k in ("position", "exit", "cost", "output")}


def calibrated_quality(rows, calibration):
    limit = calibration["clip_fraction"]
    transformed = [{**r,"raw_score":max(-limit,min(limit,
        calibration["intercept"]+calibration["slope"]*r["raw_score"]))} for r in rows]
    return paired_metrics(transformed)["quality"]


def validate_package_evidence(package):
    errors = []
    def require(ok, reason):
        if not ok: errors.append(reason)
    try:
        c = package["contracts"]
        cal, clock = c["calibration"], c["time"]
        e = cal["evidence"]
        receipt = package["evidence_receipt"]
        receipt_schema = receipt["schema_version"]
        require(receipt_schema in {"factory_delivery_evidence_v1", "factory_delivery_evidence_v2"}, "evidence_schema_invalid")
        require(package["evidence_receipt_sha256"] == digest(receipt), "evidence_receipt_hash_mismatch")
        identity = {k: package[k] for k in ("data_version", "instrument", "bar_size", "source_head")}
        require(receipt["identity"] == identity, "evidence_market_identity_mismatch")
        require(c["features"]["input_instrument"] == package["instrument"], "feature_market_identity_mismatch")
        require(receipt["model_sha256"] == package["model"]["sha256"]
            and receipt["feature_specs_sha256"] == digest(c["features"]["specs"]), "evidence_model_identity_mismatch")
        windows = receipt["windows"]
        start, end = map(utc, windows["test"])
        expected_prediction_start = start if receipt_schema == "factory_delivery_evidence_v2" else start + timedelta(hours=1)
        require(utc(clock["prediction_start"]) == expected_prediction_start, "prediction_not_final_audit_start")
        if receipt_schema == "factory_delivery_evidence_v2":
            temporal = clock.get("temporal_receipt", {})
            wall = temporal.get("wall_operations", {})
            wall_names = ("policy_committed_at", "final_fit_started_at", "final_fit_completed_at", "model_sealed_at",
                "validation_prediction_started_at", "validation_prediction_completed_at", "calibration_sealed_at",
                "audit_prediction_started_at", "audit_prediction_completed_at")
            try:
                wall_times = [utc(wall[name]) for name in wall_names]
            except (KeyError, TypeError, ValueError):
                wall_times = []
            require(clock.get("version") == "factory_decision_time_v1"
                and temporal.get("schema_version") == "factory_temporal_receipt_v2"
                and temporal.get("operation_order") == ["policy_freeze", "final_fit", "model_seal",
                    "validation_prediction", "calibration_seal", "audit_prediction"]
                and set(wall) == set(wall_names) and wall_times == sorted(wall_times)
                and utc(temporal.get("historical_data_time", {}).get("audit_decision_start")) == start,
                "temporal_receipt_v2_invalid")
        require(clock.get("label_time") == "bar_open_index"
            and clock.get("data_cutoff") == "decision_time"
            and clock.get("prediction_time_offset_bars") == 1, "prediction_time_offset_invalid")
        require(utc(windows["valid"][1]) < start <= end, "evidence_windows_overlap")
        for name, window in (("fit_rows", windows["valid"]), ("audit_rows", windows["test"])):
            rows = receipt[name]
            paired_metrics(rows)
            times = [utc(r["event_time"]) for r in rows]
            require(times == sorted(set(times)) and all(utc(window[0]) <= t <= utc(window[1]) for t in times),
                    "evidence_sample_time_mismatch:" + name)
            require(all(r["instrument"] == package["instrument"] for r in rows), "evidence_sample_asset_mismatch")
            require(receipt[name + "_sha256"] == digest(rows), "evidence_samples_hash_mismatch")
        fit = paired_metrics(receipt["fit_rows"])
        for k in ("intercept", "slope"):
            require(math.isclose(cal[k], fit[k], rel_tol=1e-10, abs_tol=1e-12), "calibration_recompute_mismatch")
        parameters = {k: cal[k] for k in ("intercept", "slope", "clip_fraction")}
        require(e.get("parameters_sha256") == digest(parameters), "calibration_parameter_binding_mismatch")
        require(e.get("fit_rows_sha256") == receipt["fit_rows_sha256"]
            and e.get("audit_rows_sha256") == receipt["audit_rows_sha256"]
            and e.get("sample_size") == len(receipt["fit_rows"]), "calibration_samples_binding_mismatch")
        require(utc(e["fitted_through"]) == max(utc(r["event_time"]) for r in receipt["fit_rows"]), "calibration_fit_end_mismatch")
        # Runtime quality is validation-only and therefore known before audit.
        # Final audit metrics are verified separately, never backfilled into a
        # forecast's sizing/quality facts at an earlier decision time.
        q = calibrated_quality(receipt["fit_rows"], cal)
        require(e.get("quality") == q and e.get("quality_passed") is True
                and q["ic"] > 0 and q["hit_rate"] > .5, "calibration_quality_not_passed")
        frozen = receipt["frozen_policy"]
        require(frozen["candidate_id"] == package["source"]["candidate_id"]
            and frozen["qlib_run_id"] == package["audit_binding"]["qlib_run_id"]
            and frozen["data_version"] == package["data_version"]
            and frozen["model_sha256"] == package["model"]["sha256"]
            and frozen["feature_specs_sha256"] == digest(c["features"]["specs"])
            and frozen["policies"] == policy_payload(c)
            and frozen["clip_fraction"] == cal["clip_fraction"]
            and (receipt_schema == "factory_delivery_evidence_v2"
                or utc(frozen["frozen_at"]) < start), "frozen_policy_binding_mismatch")
        if receipt_schema == "factory_delivery_evidence_v2":
            require(clock["temporal_receipt"]["wall_operations"]["policy_committed_at"] == frozen["frozen_at"],
                "frozen_policy_wall_time_mismatch")
        require(receipt["frozen_policy_sha256"] == digest(frozen), "frozen_policy_hash_mismatch")
        require(c["cost"]["fee_bps_per_side"] > 0
            and sum(c["cost"][k] for k in ("slippage_bps_per_side", "spread_bps_per_side", "impact_bps_per_side")) > 0,
            "zero_cost_not_supported")
    except (AttributeError, KeyError, TypeError, ValueError, OverflowError):
        errors.append("package_recomputable_evidence_missing_or_invalid")
    return sorted(set(errors))
