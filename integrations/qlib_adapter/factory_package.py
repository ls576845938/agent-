"""Export nominated final-audit artifacts without mutating a research seal.

The source service supplies its verified factory envelope. A candidate may carry
its own delivery_contract in that envelope; missing policy/calibration evidence
is reported, never synthesized from the old fixed Qlib fixture.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path

from quant_shared.strategy_delivery.models import DeliveryError, canonical, digest, source_ref, permissions, HEAD, utc
from quant_shared.strategy_delivery.runtime_contract import CAPABILITY, PACKAGE_SCHEMA, validate_runtime_contract
from .research_pipeline import read_sealed_evidence


def compile_factory_package(reference, envelope, run_root: Path, *, produce_evidence=False):
    ref = source_ref(reference)
    if ref["kind"] != "factory" or envelope.get("integrity_status") != "passed" or envelope.get("run_id") != ref["run_id"]:
        raise DeliveryError("factory_source_integrity_invalid")
    result = envelope.get("result", {})
    matches = [c for c in result.get("candidates", []) if c.get("candidate_id") == ref["candidate_id"]]
    if len(matches) != 1: raise DeliveryError("factory_candidate_unknown_or_ambiguous")
    candidate = matches[0]
    audit = candidate.get("audit_qlib_reference", {})
    root = Path(run_root).resolve()
    if candidate.get("factory_run_id") != ref["run_id"] or candidate.get("qlib_run_id") != audit.get("qlib_run_id") or root.name != audit.get("qlib_run_id"):
        raise DeliveryError("factory_final_audit_binding_invalid")
    sealed = read_sealed_evidence(root)
    if sealed.get("integrity_status") != "passed" or digest(sealed["seal"]) != audit.get("seal_sha256"):
        raise DeliveryError("factory_final_seal_mismatch")
    files = sealed["seal"]["files"]
    def read(name):
        if name not in files: raise DeliveryError("package_artifact_missing:" + name)
        path = (root / name).resolve()
        if not path.is_relative_to(root): raise DeliveryError("package_artifact_path_escape")
        if path.stat().st_size > 256_000_000: raise DeliveryError("package_artifact_oversized:" + name)
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != files[name]: raise DeliveryError("source_changed_during_export")
        return raw
    try:
        import yaml
        trial = json.loads(read("factory_trial.json"))
        config = yaml.safe_load(read("factory_config.yaml"))
        model_text = read("model.txt").decode("utf-8")
        handler = config["task"]["dataset"]["kwargs"]["handler"]["kwargs"]
        expected_windows = {"train": [result["split_plan"]["segments"]["train"][0], result["split_plan"]["segments"]["valid"][1]],
            "valid": result["split_plan"]["segments"]["selection"], "test": result["split_plan"]["segments"]["audit"]}
        if (trial["status"] != "completed" or trial["run_id"] != root.name or trial["factory_run_id"] != ref["run_id"]
            or audit["segments"] != expected_windows or trial["segments"] != expected_windows
            or trial["model_spec"] != audit["model_spec"] or trial["model_spec"] != candidate["frozen_champion"]["model_spec"]
            or candidate["frozen_champion"].get("audit_used_for_selection") is not False):
            raise DeliveryError("factory_final_model_not_proven")
        has_finalization_receipt = "factory_finalization_receipt.json" in files
        if has_finalization_receipt and (trial.get("phase") != "final" or trial.get("candidate_id") != ref["candidate_id"]):
            raise DeliveryError("factory_finalization_identity_mismatch")
        specs = candidate["feature_specs"]
        names = [s["factor_id"] for s in specs]
        if (names != trial["feature_ids"] or names != audit["feature_ids"]
            or digest(specs) != candidate["frozen_champion"]["feature_spec_hash"]
            or specs != result["factor_specs"]): raise DeliveryError("factory_feature_binding_mismatch")
        if (handler["data_loader"]["class"] != "FactoryParquetLoader"
            or handler["data_loader"]["module_path"] != "integrations.qlib_adapter.factory_loader"
            or handler["infer_processors"] != [] or config["task"]["model"]["class"] != "LGBModel"
            or config["task"]["model"]["module_path"] != "qlib.contrib.model.gbdt"
            or config.get("mode") != "research_only" or config.get("paper_enabled") is not False
            or config.get("live_enabled") is not False): raise DeliveryError("factory_model_loader_unsupported")
        profile = result["profile"]
        if candidate["data_version"] != profile["data_version"]: raise DeliveryError("factory_data_identity_mismatch")
        if (not HEAD.fullmatch(str(trial.get("source_head", "")))
            or trial["source_head"] != sealed["seal"].get("source_head")
            or trial["source_head"] != envelope.get("source_head")
            or trial["source_head"] != result.get("source_head")):
            raise DeliveryError("factory_code_identity_mismatch")
        authored = envelope.get("delivery_contract", candidate.get("delivery_contract")) or {}
        if authored:
            frozen_policy = authored.get("frozen_policy", {})
            config_policy = {k:frozen_policy.get(k) for k in ("policies","clip_fraction","frozen_at")}
            if config.get("delivery_policy") != config_policy:
                raise DeliveryError("candidate_policy_not_bound_to_sealed_research_config")
        contracts = deepcopy(authored.get("contracts", {}))
        output = contracts.get("output")
        if output and (output.get("horizon_bars") != result["split_plan"]["horizon_bars"]
            or output.get("horizon_bars") != profile["label_horizon"]
            or result["split_plan"]["entry_delay_bars"] != profile["entry_delay"]
            or contracts.get("cost", {}).get("execution_delay_bars") != profile["entry_delay"]
            or config["model"].get("label") != result["split_plan"]["label"]):
            raise DeliveryError("factory_label_contract_mismatch")
        features = contracts.get("features")
        if features and features.get("annualization") != profile["annualization"]:
            raise DeliveryError("factory_annualization_mismatch")
        if contracts.get("features", {}).get("specs", specs) != specs or contracts.get("features", {}).get("names", names) != names:
            raise DeliveryError("factory_delivery_feature_mismatch")
        # Preserve known source facts even if the candidate has no runtime contract.
        contracts.setdefault("features", {"version": "factory_safe_ast_v1", "specs": specs, "names": names})
        contracts.setdefault("preprocessing", {"version": "factory_processors_v1", "infer_processors": [],
            "fitted_state": None, "missing": "native_nan", "dtype": "float64"})
        authored_model_dependencies = authored.get("model_dependencies")
        runtime_model_dependencies = ({"lightgbm": authored_model_dependencies["lightgbm"]}
            if isinstance(authored_model_dependencies, dict)
            and isinstance(authored_model_dependencies.get("lightgbm"), str)
            and authored_model_dependencies["lightgbm"] else {})
        package = {"schema_version": PACKAGE_SCHEMA, "source": ref,
            "strategy_id": candidate["strategy_config"]["strategy_id"], "strategy_version": config["model"]["strategy_version"],
            "source_head": trial["source_head"], "market": profile["market"], "instrument": ",".join(profile["symbols"]),
            "bar_size": profile["bar_size"], "data_version": candidate["data_version"], "params_hash": digest(trial["model_spec"]),
            "settlement_currency": authored.get("settlement_evidence", {}).get("currency"),
            "settlement_evidence": deepcopy(authored.get("settlement_evidence")),
            "model": {"format": "lightgbm_text_v1", "text": model_text, "sha256": files["model.txt"],
                "dependencies": runtime_model_dependencies},
            "feature_implementation": deepcopy(authored.get("feature_implementation")),
            "contracts": contracts, "artifacts": dict(files), "adapter_id": CAPABILITY, "capabilities": [CAPABILITY],
            "audit_binding": {"qlib_run_id": root.name, "seal_sha256": digest(sealed["seal"]),
                "factory_result_sha256": digest(result), "final_audit": True},
            "supported_targets": ["offline"], "admission_blockers": list(candidate.get("gate", {}).get("blockers", [])),
            "limitations": ["research_candidate_not_trading_authority", "explicit_registered_offline_call_required",
                "existing_0p01_fok_only_no_candidate_partial_open", "offline_cost_must_match_existing_simulator"],
            "permissions": permissions()}
        # Seal completeness is not audit success. Verify every content dependency
        # and reproduce the final audit before looking at authored assertions.
        from .factory_delivery import verify_final_audit, bind_receipt
        verified = verify_final_audit(package, read, candidate, expected_windows, profile,
            authored.get("frozen_policy", {}))
        if authored:
            expected = deepcopy(package)
            bind_receipt(expected, verified, authored.get("frozen_policy", {}))
            if not produce_evidence and (
                authored.get("evidence_receipt") != expected["evidence_receipt"]
                or authored.get("evidence_receipt_sha256") != expected["evidence_receipt_sha256"]
                or contracts.get("calibration") != expected["contracts"]["calibration"]):
                raise DeliveryError("factory_delivery_receipt_not_reproducible")
            package = expected
            contracts = package["contracts"]
        if candidate.get("gate", {}).get("status") not in {"research_candidate", "exploratory_nomination"}:
            package["admission_blockers"].append("research_admission_not_proven")
        if contracts.get("calibration", {}).get("evidence", {}).get("quality_passed") is not True:
            package["admission_blockers"].append("candidate_calibration_quality_not_passed")
        from .package_inference import feature_implementation
        if authored.get("feature_implementation"):
            implementation = feature_implementation(source_head=trial["source_head"])
            # Dependency versions come from the candidate's immutable contract;
            # current versions are checked separately when loading.
            if authored["feature_implementation"].get("files") != implementation["files"]:
                raise DeliveryError("factory_feature_implementation_mismatch")
        if contracts.get("calibration", {}).get("evidence"):
            fitted = utc(contracts["calibration"]["evidence"]["fitted_through"])
            # Factory Qlib segments are UTC even when stored without an offset.
            def timestamp(value):
                from datetime import datetime, timezone
                t = datetime.fromisoformat(value.replace("Z", "+00:00"))
                return t.replace(tzinfo=timezone.utc) if t.tzinfo is None else t.astimezone(timezone.utc)
            if not timestamp(expected_windows["valid"][0]) <= fitted <= timestamp(expected_windows["valid"][1]):
                raise DeliveryError("factory_calibration_outside_validation")
            if utc(contracts["time"]["prediction_start"]) <= fitted:
                raise DeliveryError("factory_calibration_not_prior")
        package["package_validation"] = {"status": "blocked", "blockers": validate_runtime_contract(package)}
        package["evidence_validation"] = {"status":"blocked" if package["package_validation"]["blockers"] else "passed",
            "blockers":list(package["package_validation"]["blockers"])}
        if not package["package_validation"]["blockers"]:
            from .package_inference import load_package_model
            load_package_model(package)  # format/feature/dependency checks only; no prediction
            package["package_validation"]["status"] = "passed"
        return package
    except DeliveryError:
        raise
    except (OSError, UnicodeError, ValueError, KeyError, TypeError, AttributeError) as exc:
        raise DeliveryError("factory_package_source_malformed") from exc


def export_package(package, destination: Path):
    """Explicit create-only export; GET/source compilation never invokes this."""
    blockers = validate_runtime_contract(package)
    if blockers: raise DeliveryError("package_export_blocked:" + ",".join(blockers))
    from .package_inference import load_package_model
    load_package_model(package)
    raw = canonical(package).encode("utf-8")
    destination = Path(destination)
    # Caller owns a new explicit destination; never overwrite an old package/seal.
    with destination.open("xb") as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    return {"sha256": hashlib.sha256(raw).hexdigest(), "content_digest": digest(package), "bytes": len(raw)}
