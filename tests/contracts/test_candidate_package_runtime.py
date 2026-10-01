"""Synthetic package identities only; never registers current service accounts."""
from copy import deepcopy
import hashlib
import json

import pytest

from quant_shared.strategy_delivery.models import DeliveryError, digest, validate_package
from quant_shared.strategy_delivery.runtime_contract import CAPABILITY, PACKAGE_SCHEMA, validate_runtime_contract
from tests.contracts.test_strategy_delivery import package as legacy_package, setup, command


def portable_package(model_text="fixture-model-not-loadable"):
    from quant_shared.alpha_factory.contracts import FactorSpec
    from integrations.qlib_adapter.package_inference import feature_implementation
    from quant_shared.strategy_delivery.models import permissions
    spec = FactorSpec({"op": "primitive", "primitive": "momentum_20d"}, "registered", "momentum").to_dict()
    p = legacy_package()
    p.update(schema_version=PACKAGE_SCHEMA, adapter_id=CAPABILITY,
        source={"kind": "factory", "run_id": "factory-a", "candidate_id": "candidate-a"},
        model={"format": "lightgbm_text_v1", "text": model_text,
               "sha256": hashlib.sha256(model_text.encode()).hexdigest(),
               "dependencies": {"lightgbm": "4.7.0"}},
        audit_binding={"qlib_run_id": "audit-a", "seal_sha256": "a"*64,
                       "factory_result_sha256": "b"*64, "final_audit": True},
        capabilities=["factory_lgbm_ast_v1"], execution_binding=None,
        feature_implementation=feature_implementation(), permissions=permissions())
    p["artifacts"] = {"model.txt": p["model"]["sha256"]}
    p["contracts"] = {
        "features": {"version": "factory_safe_ast_v1", "specs": [spec], "names": [spec["factor_id"]],
                     "primitive_version": "factory_primitives_v1", "warmup_bars": 80,
                     "annualization": 8760, "input_instrument": "BTC-USDT-SWAP"},
        "preprocessing": {"version": "factory_processors_v1", "infer_processors": [], "fitted_state": None,
                          "missing": "native_nan", "dtype": "float64"},
        "output": {"version": "return_forecast_v1", "kind": "return_forecast", "unit": "return_fraction",
                   "horizon_bars": 12, "valid_for_bars": 2,"score_rule":"absolute_return_fraction_unit_multiplier"},
        "calibration": {"version": "candidate_ols_v1", "intercept": 0., "slope": 1., "clip_fraction": .05,
                        "evidence": {"candidate_id": "candidate-a", "qlib_run_id": "audit-a",
                        "model_sha256": p["model"]["sha256"], "fit_scope": "validation_only",
                        "fitted_through": "2020-01-01T00:00:00Z", "sample_size": 100,
                        "quality": {"ic": .03, "hit_rate": .55}, "quality_passed": True}},
        "position": {"version": "qlib_candidate_policy_v1", "risk_budget_fraction": .01,
                     "max_weight": .1, "volatility_target_annual_configured": .2, "volatility_target_applied": False},
        "exit": {"version": "qlib_candidate_policy_v1", "hard_stop_fraction": .04,
                 "trailing_stop_fraction": .03, "maximum_holding_bars": 12},
        "cost": {"version": "qlib_candidate_policy_v1", "fee_bps_per_side": 5., "slippage_bps_per_side": 2.,
                 "spread_bps_per_side": 2., "impact_bps_per_side": 2., "funding": "visible_rate",
                 "execution_delay_bars": 2},
        "time": {"version": "factory_decision_time_v1", "event_time": "completed_bar_open_utc",
                 "available_time": "event_time_plus_1h", "feature_time": "decision_time",
                 "prediction_start": "2020-02-01T00:00:00Z"},
        "state": {"version": "candidate_state_v1", "authority": "existing_btc_offline_runtime_and_ledger"}}
    p["contracts"]["calibration"]["evidence_sha256"] = digest(p["contracts"]["calibration"]["evidence"])
    evidence = p["contracts"]["calibration"]["evidence"]
    evidence.update(feature_specs_sha256=digest([spec]), data_version=p["data_version"], output_sha256=digest(p["contracts"]["output"]))
    p["contracts"]["calibration"]["evidence_sha256"] = digest(evidence)
    p["settlement_evidence"] = {"currency": "USDT", "instrument": p["instrument"], "source": "candidate_final_audit"}
    attach_test_receipt(p)
    return p


def attach_test_receipt(p, *, fit_rows=None, audit_rows=None):
    """Explicit synthetic samples, not declarations of real research quality."""
    from datetime import datetime, timedelta, timezone
    from integrations.qlib_adapter.factory_delivery import bind_receipt
    from quant_shared.strategy_delivery.package_evidence import policy_payload
    def rows(month):
        return [{"event_time":(datetime(2020,month,1,tzinfo=timezone.utc)+timedelta(hours=i)).isoformat(),
                 "instrument":"BTC-USDT-SWAP", "features":[(i-50)/10000],
                 "raw_score":(i-50)/10000, "label":(i-50)/10000} for i in range(100)]
    verified = {"schema_version":"factory_delivery_evidence_v1",
        "identity":{k:p[k] for k in ("data_version","instrument","bar_size","source_head")},
        "model_sha256":p["model"]["sha256"], "feature_specs_sha256":digest(p["contracts"]["features"]["specs"]),
        "windows":{"train":["2018-01-01T00:00:00Z","2018-06-01T00:00:00Z"],
                   "valid":["2020-01-01T00:00:00Z","2020-01-31T00:00:00Z"],
                   "test":["2020-02-01T00:00:00Z","2020-03-01T00:00:00Z"]},
        "fit_rows":fit_rows or rows(1), "audit_rows":audit_rows or rows(2)}
    frozen = {"candidate_id":p["source"]["candidate_id"], "qlib_run_id":p["audit_binding"]["qlib_run_id"],
        "data_version":p["data_version"], "model_sha256":p["model"]["sha256"],
        "feature_specs_sha256":verified["feature_specs_sha256"], "policies":policy_payload(p["contracts"]),
        "clip_fraction":p["contracts"]["calibration"]["clip_fraction"], "frozen_at":"2020-01-31T00:00:00Z"}
    p["contracts"]["time"].update(prediction_start="2020-02-01T01:00:00Z", label_time="bar_open_index",
        data_cutoff="decision_time", prediction_time_offset_bars=1)
    bind_receipt(p, verified, frozen)
    return p


def test_old_contract_is_unchanged_and_new_package_is_separately_loadable():
    assert validate_package(legacy_package(), "offline") == []
    p = portable_package()
    assert validate_runtime_contract(p) == []
    assert validate_package(p, "offline") == []
    p["admission_blockers"] = ["research_quality_failed"]
    assert validate_runtime_contract(p) == []
    assert "research_quality_failed" in validate_package(p, "offline")


def test_temporal_receipt_v2_uses_audit_decision_start_without_reinterpreting_wall_time():
    p=portable_package()
    receipt=p["evidence_receipt"]
    receipt["schema_version"]="factory_delivery_evidence_v2"
    start=receipt["windows"]["test"][0]
    frozen=p["evidence_receipt"]["frozen_policy"]
    frozen["frozen_at"]="2026-09-30T01:00:00Z"
    p["contracts"]["time"].update(version="factory_decision_time_v1",prediction_start=start,
        temporal_receipt={"schema_version":"factory_temporal_receipt_v2",
            "wall_operations":{"policy_committed_at":frozen["frozen_at"],
                "final_fit_started_at":"2026-09-30T01:01:00Z","final_fit_completed_at":"2026-09-30T01:02:00Z",
                "model_sealed_at":"2026-09-30T01:03:00Z",
                "validation_prediction_started_at":"2026-09-30T01:04:00Z",
                "validation_prediction_completed_at":"2026-09-30T01:05:00Z",
                "calibration_sealed_at":"2026-09-30T01:06:00Z",
                "audit_prediction_started_at":"2026-09-30T01:07:00Z",
                "audit_prediction_completed_at":"2026-09-30T01:08:00Z"},
            "historical_data_time":{"audit_decision_start":start,
                "audit_decision_end":receipt["windows"]["test"][1]},
            "operation_order":["policy_freeze","final_fit","model_seal","validation_prediction",
                "calibration_seal","audit_prediction"]})
    receipt["frozen_policy_sha256"]=digest(frozen)
    p["evidence_receipt_sha256"]=digest(receipt)
    assert validate_runtime_contract(p)==[]
    changed=deepcopy(p);changed["contracts"]["time"]["prediction_start"]="2020-02-01T01:00:00Z"
    assert "prediction_not_final_audit_start" in validate_runtime_contract(changed)


@pytest.mark.parametrize("mutation,reason", [
    (lambda p: p["model"].update(text="tampered"), "model_hash_mismatch"),
    (lambda p: p["contracts"]["features"].update(warmup_bars=0), "feature_warmup_invalid"),
    (lambda p: p["contracts"]["output"].update(unit="contracts"), "forecast_unit_unsupported"),
    (lambda p: p["contracts"]["preprocessing"].update(infer_processors=[{"class":"evil"}]), "preprocessing_unsupported"),
    (lambda p: p.update(settlement_currency="USD"), "settlement_evidence_mismatch"),
    (lambda p: p["audit_binding"].update(final_audit=False), "final_audit_required"),
    (lambda p: p["contracts"].pop("calibration"), "calibration_contract_missing"),
    (lambda p: p.update(adapter_id="unknown"), "adapter_capability_unsupported"),
    (lambda p: p["permissions"].update(order=0), "runtime_permissions_invalid"),
    (lambda p: p["contracts"]["calibration"]["evidence"].update(candidate_id="other"), "calibration_source_mismatch"),
    (lambda p: p["contracts"]["features"]["specs"][0].update(expression={"op":"python", "value":"eval()"}), "runtime_contract_malformed"),
])
def test_portable_contract_rejects_incomplete_or_inconsistent_facts(mutation, reason):
    p = portable_package(); mutation(p)
    assert reason in validate_runtime_contract(p)


def test_new_registration_preserves_execution_blocker_and_exact_binding(setup):
    from quant_crypto.application.btc_registered_candidate import resolve_btc_registered_candidate
    service, store, sources, accounts, now = setup
    sources.value = portable_package()
    row = service.create(sources.value["source"], "offline", key="portable", actor="operator")
    row = command(service, row, "bind", account_ref="fixture-account")
    row = command(service, row, "review", decision="approve", reason="synthetic only")
    row = command(service, row, "register")
    resolved = resolve_btc_registered_candidate(service, row["id"], content_digest=row["content_digest"],
        account_identity_hash=accounts.value["identity_hash"], adapter_id=CAPABILITY)
    assert resolved["execution_status"] == "not_executed"
    assert resolved["blockers"] == []
    assert resolved["entrypoint"] == "open_btc_registered_candidate_offline" and not any(resolved["permissions"].values())
    before = len(store.history(row["id"]))
    assert service.get(row["id"])["registration"]["start_allowed"] is False
    assert len(store.history(row["id"])) == before
    from datetime import timedelta
    now[0] += timedelta(days=2)
    with pytest.raises(DeliveryError, match="review_expired"):
        resolve_btc_registered_candidate(service, row["id"], content_digest=row["content_digest"],
            account_identity_hash=accounts.value["identity_hash"], adapter_id=CAPABILITY)


@pytest.mark.parametrize("field,value", [("intercept", .1), ("slope", 5.), ("clip_fraction", .5)])
def test_review_calibration_parameter_tamper_cannot_reuse_evidence(field, value):
    p = portable_package()
    p["contracts"]["calibration"][field] = value
    assert validate_runtime_contract(p), "parameter changes must invalidate original evidence"


@pytest.mark.parametrize("damage", ["cross_asset", "audit_start", "quality", "zero_cost", "risk"])
def test_review_self_declared_market_quality_and_policy_are_rejected(damage):
    p = portable_package()
    c = p["contracts"]
    if damage == "cross_asset": c["features"]["input_instrument"] = "ETH-USDT-SWAP"
    if damage == "audit_start": c["time"]["prediction_start"] = "2020-01-02T00:00:00Z"
    if damage == "quality":
        c["calibration"]["evidence"].update(sample_size=1, quality={"ic":1., "hit_rate":1.})
        c["calibration"]["evidence_sha256"] = digest(c["calibration"]["evidence"])
    if damage == "zero_cost":
        for k in ("fee_bps_per_side", "slippage_bps_per_side", "spread_bps_per_side", "impact_bps_per_side"):
            c["cost"][k] = 0.
    if damage == "risk": c["position"]["risk_budget_fraction"] = 1.
    assert validate_runtime_contract(p), "self-declared replacement is not frozen source evidence"


def test_historical_factory_v2_record_uses_versioned_recompile_for_resolve_and_recovery(setup):
    service,store,sources,accounts,now=setup
    old=legacy_package();old["source"]["kind"]="factory"
    sources.value=old
    row=service.create(old["source"],"offline",key="legacy-factory",actor="operator")
    row=command(service,row,"bind",account_ref="fixture-account")
    row=command(service,row,"review",decision="approve",reason="old factory record")
    row=command(service,row,"register")
    versions=[]
    def recompile(source,*,package_schema):
        versions.append(package_schema)
        assert source==old["source"]
        return deepcopy(old)
    sources.recompile=recompile
    sources.value=portable_package()  # new creates would now select V3
    args={"content_digest":row["content_digest"],"account_identity_hash":accounts.value["identity_hash"],"adapter_id":old["adapter_id"]}
    assert service.resolve(row["id"],**args)["package"]==old
    row=command(service,row,"revoke",reason="still revoke without migration")
    assert service.resolve_recovery(row["id"],**args)["package"]==old
    assert versions==["strategy_delivery_package_v2"]*2
