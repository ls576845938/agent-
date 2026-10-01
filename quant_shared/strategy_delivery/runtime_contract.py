"""Versioned, asset-neutral package validation; no loading or execution side effects."""
from __future__ import annotations

import hashlib
import math

from quant_shared.alpha_factory.contracts import FactoryError, digest, validate_expression
from .models import HASH, HEAD, utc, source_ref

PACKAGE_SCHEMA = "strategy_delivery_package_v3"
CAPABILITY = "factory_lgbm_ast_v1"
PRIMITIVE_LOOKBACK = {"momentum_20d": 20, "momentum_60d": 60, "momentum_120d": 120,
    "volatility_20d": 20, "volatility_60d": 60, "liquidity_20d": 19, "reversal_1d": 1, "volume_20d": 59}


def feature_warmup(specs):
    def lookback(node):
        if node["op"] == "primitive": return PRIMITIVE_LOOKBACK[node["primitive"]] + 59
        if node["op"] == "const": return 0
        return max(lookback(child) for child in node["args"]) + (node["window"] - 1 if node["op"] == "rolling_z" else 0)
    # Number of bars including the first usable row, not an index offset.
    return max(lookback(spec["expression"]) for spec in specs) + 1


def validate_runtime_contract(package: dict) -> list[str]:
    errors = []
    def require(ok, reason):
        if not ok: errors.append(reason)
    def finite(value, low=None, high=None):
        return (type(value) in (int, float) and math.isfinite(value)
            and (low is None or value >= low) and (high is None or value <= high))
    try:
        require(package.get("schema_version") == PACKAGE_SCHEMA, "runtime_package_schema_unsupported")
        source = source_ref(package.get("source"))
        require(source["kind"] == "factory" and HEAD.fullmatch(str(package.get("source_head", "")))
            and HASH.fullmatch(str(package.get("params_hash", "")))
            and all(isinstance(package.get(k), str) and bool(package[k]) for k in ("data_version", "strategy_id", "strategy_version")), "runtime_identity_invalid")
        require(package.get("adapter_id") == CAPABILITY and package.get("capabilities") == [CAPABILITY], "adapter_capability_unsupported")
        require(package.get("market") == "crypto" and package.get("instrument") == "BTC-USDT-SWAP"
            and package.get("bar_size") == "1h" and package.get("settlement_currency") == "USDT", "market_capability_unsupported")
        implementation = package.get("feature_implementation") or {}
        require(isinstance(implementation.get("files"), dict) and len(implementation["files"]) == 8
            and all(HASH.fullmatch(str(v)) for v in implementation["files"].values())
            and isinstance(implementation.get("dependencies"), dict)
            and set(implementation["dependencies"]) == {"numpy", "pandas"}, "feature_implementation_missing")
        from .models import FALSE_PERMISSIONS
        flags = package.get("permissions")
        require(isinstance(flags, dict) and set(flags) == set(FALSE_PERMISSIONS)
            and all(flags[k] is False for k in flags), "runtime_permissions_invalid")
        model = package.get("model") or {}
        require(model.get("format") == "lightgbm_text_v1", "model_format_unsupported")
        text = model.get("text")
        require(isinstance(text, str) and 0 < len(text.encode()) <= 4_000_000, "model_text_missing_or_oversized")
        model_hash = hashlib.sha256(text.encode()).hexdigest() if isinstance(text, str) else None
        require(model_hash == model.get("sha256") == package.get("artifacts", {}).get("model.txt") and model_hash is not None, "model_hash_mismatch")
        deps = model.get("dependencies")
        require(isinstance(deps, dict) and set(deps) == {"lightgbm"}
                and isinstance(deps.get("lightgbm"), str) and bool(deps["lightgbm"]), "model_dependency_missing")
        audit = package.get("audit_binding") or {}
        require(audit.get("final_audit") is True and isinstance(audit.get("qlib_run_id"), str)
            and audit["qlib_run_id"] != "latest" and bool(audit["qlib_run_id"])
            and HASH.fullmatch(str(audit.get("seal_sha256", ""))) is not None
            and HASH.fullmatch(str(audit.get("factory_result_sha256", ""))) is not None, "final_audit_required")
        contracts = package.get("contracts") or {}
        features = contracts.get("features") or {}
        require(features.get("version") == "factory_safe_ast_v1" and features.get("primitive_version") == "factory_primitives_v1", "feature_version_unsupported")
        specs, names = features.get("specs"), features.get("names")
        require(isinstance(specs, list) and 1 <= len(specs) <= 12, "feature_specs_missing")
        if isinstance(specs, list) and specs:
            for spec in specs:
                validate_expression(spec["expression"], set(PRIMITIVE_LOOKBACK))
                require(spec.get("expression_hash") == digest(spec["expression"])
                    and spec.get("factor_id") == "af_" + digest(spec["expression"])[:20], "feature_identity_mismatch")
            require(names == [spec["factor_id"] for spec in specs] and len(set(names)) == len(names), "feature_order_mismatch")
            require(type(features.get("warmup_bars")) is int and features["warmup_bars"] == feature_warmup(specs), "feature_warmup_invalid")
        require(finite(features.get("annualization"), 1) and features.get("input_instrument") == package.get("instrument"), "feature_market_binding_missing")
        require(contracts.get("preprocessing") == {"version": "factory_processors_v1", "infer_processors": [],
            "fitted_state": None, "missing": "native_nan", "dtype": "float64"}, "preprocessing_unsupported")
        output = contracts.get("output") or {}
        require(output.get("version") == "return_forecast_v1" and output.get("kind") == "return_forecast"
            and output.get("unit") == "return_fraction"
            and output.get("score_rule") == "absolute_return_fraction_unit_multiplier", "forecast_unit_unsupported")
        require(all(type(output.get(key)) is int and output[key] > 0 for key in ("horizon_bars", "valid_for_bars")), "forecast_horizon_invalid")
        calibration = contracts.get("calibration") or {}
        require(calibration.get("version") == "candidate_ols_v1", "calibration_contract_missing")
        require(finite(calibration.get("intercept")) and finite(calibration.get("slope"))
            and finite(calibration.get("clip_fraction"), 1e-12, 1), "calibration_parameters_invalid")
        evidence = calibration.get("evidence") or {}
        require(calibration.get("evidence_sha256") == digest(evidence) and bool(evidence), "calibration_evidence_hash_invalid")
        require(evidence.get("candidate_id") == package.get("source", {}).get("candidate_id")
            and evidence.get("qlib_run_id") == audit.get("qlib_run_id")
            and evidence.get("model_sha256") == model_hash
            and evidence.get("feature_specs_sha256") == digest(specs)
            and evidence.get("data_version") == package.get("data_version")
            and evidence.get("output_sha256") == digest(output)
            and evidence.get("fit_scope") == "validation_only", "calibration_source_mismatch")
        quality = evidence.get("quality") or {}
        require(type(evidence.get("sample_size")) is int and evidence["sample_size"] > 0
            and finite(quality.get("ic"), -1, 1) and finite(quality.get("hit_rate"), 0, 1)
            and type(evidence.get("quality_passed")) is bool, "calibration_quality_missing")
        clock = contracts.get("time") or {}
        require(clock.get("version") == "factory_decision_time_v1"
            and clock.get("event_time") == "completed_bar_open_utc"
            and clock.get("available_time") == "event_time_plus_1h"
            and clock.get("feature_time") == "decision_time", "time_contract_unsupported")
        if evidence.get("fitted_through") and clock.get("prediction_start"):
            require(utc(evidence["fitted_through"]) < utc(clock["prediction_start"]), "calibration_not_prior_to_inference")
        else: errors.append("calibration_time_evidence_missing")
        for name in ("position", "exit", "cost"):
            require((contracts.get(name) or {}).get("version") == "qlib_candidate_policy_v1", "policy_missing:" + name)
        position, exit, cost = (contracts.get(n) or {} for n in ("position", "exit", "cost"))
        require(all(finite(position.get(k), 1e-12, 1) for k in ("risk_budget_fraction", "max_weight", "volatility_target_annual_configured"))
            and position.get("volatility_target_applied") is False, "position_policy_invalid")
        require(all(finite(exit.get(k), 1e-12, 1-1e-12) for k in ("hard_stop_fraction", "trailing_stop_fraction"))
            and type(exit.get("maximum_holding_bars")) is int and exit["maximum_holding_bars"] > 0, "exit_policy_invalid")
        require(all(finite(cost.get(k), 0) for k in ("fee_bps_per_side", "slippage_bps_per_side", "spread_bps_per_side", "impact_bps_per_side"))
            and cost.get("funding") == "visible_rate" and cost.get("execution_delay_bars") == 2, "cost_policy_invalid")
        require(contracts.get("state") == {"version": "candidate_state_v1", "authority": "existing_btc_offline_runtime_and_ledger"}, "state_contract_unsupported")
        settlement = package.get("settlement_evidence") or {}
        require(settlement.get("currency") == package.get("settlement_currency")
            and settlement.get("instrument") == package.get("instrument")
            and settlement.get("source") == "candidate_final_audit", "settlement_evidence_mismatch")
    except (AttributeError, KeyError, TypeError, ValueError, OverflowError, FactoryError):
        errors.append("runtime_contract_malformed")
    from .package_evidence import validate_package_evidence
    errors.extend(validate_package_evidence(package))
    return sorted(set(errors))
