"""Exact registration resolution and explicitly invoked offline-only execution.

Resolution/verification is read-only. Only the explicit open entrypoint constructs
the existing in-process replay; registration and HTTP GET never auto-start it.
"""
from quant_shared.strategy_delivery.models import DeliveryError, digest
from weakref import WeakSet

_ISSUE_KEY = object()
_ISSUED_CONTEXTS = WeakSet()


def _has_instance_method_override(value):
    return any(callable(getattr(type(value), name, None)) for name in vars(value))


def _require_trusted_service(service):
    """Supported public composition boundary, not an arbitrary-code sandbox."""
    from pathlib import Path
    from quant_shared.strategy_delivery.service import DeliveryService
    from backend.app.services.candidate_delivery_sources import ResearchDeliverySources
    from backend.app.services.candidate_delivery_accounts import DeliveryAccounts
    from backend.app.services.candidate_delivery_store import DeliveryStore
    from backend.app.services.alpha_factory import AlphaFactoryService
    from backend.app.services.research_archive_discovery import ResearchArchiveCatalog
    from backend.app.services.candidate_delivery_bootstrap import (
        CandidateResearchArchiveGuard,
        CandidateResearchRoots,
    )
    from backend.app.services.candidate_offline_inputs import OfflineInputs
    from integrations.qlib_adapter.factory_delivery import FactoryDeliveryReader
    for obj,cls in ((service,DeliveryService),(getattr(service,"sources",None),ResearchDeliverySources),
            (getattr(service,"accounts",None),DeliveryAccounts),(getattr(service,"store",None),DeliveryStore)):
        if type(obj) is not cls or _has_instance_method_override(obj):
            raise DeliveryError("registered_trusted_service_required")
    sources=service.sources
    configured_reader=sources.factory_reader
    reader=configured_reader
    if type(configured_reader) is FactoryDeliveryReader:
        if _has_instance_method_override(configured_reader):
            raise DeliveryError("registered_trusted_source_required")
        reader=configured_reader.factory_reader
    if (type(reader) is not AlphaFactoryService or _has_instance_method_override(reader)
        or getattr(sources,"legacy_factory_reader",None) is not reader):
        raise DeliveryError("registered_trusted_source_required")
    archive=sources.archive
    if type(archive) is ResearchArchiveCatalog:
        # The legacy bare catalogue keeps its supported constructor injection
        # semantics; only method shadowing is rejected as before.
        if _has_instance_method_override(archive):
            raise DeliveryError("registered_trusted_source_required")
        return service
    if type(archive) is not CandidateResearchArchiveGuard or _has_instance_method_override(archive):
        raise DeliveryError("registered_trusted_source_required")
    roots=getattr(archive,"roots",None)
    inputs=getattr(roots,"inputs",None)
    internal_archive=getattr(archive,"archive",None)
    if (type(roots) is not CandidateResearchRoots or roots.configured is not True
        or type(inputs) is not OfflineInputs or type(internal_archive) is not ResearchArchiveCatalog
        or any(_has_instance_method_override(obj) for obj in (roots,inputs,internal_archive))):
        raise DeliveryError("registered_trusted_source_required")
    from tools.agent_governance.shared_data import load_manifest_from_git, resolve_manifest_payload
    if (getattr(internal_archive,"_manifest_loader",None) is not load_manifest_from_git
        or getattr(internal_archive,"_manifest_resolver",None) is not resolve_manifest_payload):
        raise DeliveryError("registered_trusted_source_required")
    if (not all(isinstance(value,Path) for value in (
            roots.factory_root,roots.qlib_root,inputs.path,inputs.repo,sources.repo,
            sources.qlib_root,reader.root,reader.qlib_root,internal_archive.repo_root))
        or type(inputs.checksum) is not str or type(inputs.revision) is not str):
        raise DeliveryError("registered_trusted_source_required")
    # This is the authoritative owner/revision/hash/path check. It is invoked
    # only after rejecting instance method overrides, so a supplied callable
    # cannot replace the official revalidation implementation.
    if roots.revalidate() is not roots:
        raise DeliveryError("registered_trusted_source_required")
    try:
        repo=sources.repo.resolve()
        factory_root=roots.factory_root.resolve()
        qlib_root=roots.qlib_root.resolve()
        if (inputs.repo.resolve()!=repo or internal_archive.repo_root.resolve()!=repo
            or sources.qlib_root.resolve()!=qlib_root or reader.root.resolve()!=factory_root
            or reader.qlib_root.resolve()!=qlib_root or reader.readonly_archive is not archive):
            raise DeliveryError("registered_trusted_source_required")
    except (OSError,RuntimeError,TypeError) as exc:
        raise DeliveryError("registered_trusted_source_required") from exc
    return service


def require_registered_context(value):
    if type(value) is not VerifiedRegisteredInputs or value not in _ISSUED_CONTEXTS:
        raise DeliveryError("registered_issued_context_required")
    _require_trusted_service(value.service)
    return value


def check_registered_inputs(value):
    return VerifiedRegisteredInputs.check(require_registered_context(value))


def registered_forecast(value,index):
    return VerifiedRegisteredInputs.forecast(require_registered_context(value),index)


def resolve_btc_registered_candidate(service, registration_id, *, content_digest,
                                     account_identity_hash, adapter_id):
    row = service.resolve(registration_id, content_digest=content_digest,
                          account_identity_hash=account_identity_hash, adapter_id=adapter_id)
    package = row["package"]
    if package["market"] != "crypto" or package["instrument"] != "BTC-USDT-SWAP" or row["target"] != "offline":
        raise DeliveryError("btc_registered_environment_unsupported")
    from quant_shared.strategy_delivery.runtime_contract import CAPABILITY, validate_runtime_contract
    if adapter_id == CAPABILITY:
        blockers = validate_runtime_contract(package)
        if blockers: raise DeliveryError("registered_package_invalid:" + ",".join(blockers))
        return {"registration_id": row["id"], "content_digest": content_digest,
                "adapter_id": adapter_id, "entrypoint": "open_btc_registered_candidate_offline", "binding": package,
                "binding_digest": digest(package), "permissions": row["permissions"],
                "execution_status": "not_executed", "blockers": []}
    binding = package.get("execution_binding")
    if not isinstance(binding, dict): raise DeliveryError("execution_binding_missing")
    if adapter_id == "btc_donchian_history_offline_v1":
        from quant_crypto.application.btc_strategy_registry import btc_strategy_registry
        from quant_crypto.application.donchian_history_spec import HistorySpec
        spec = btc_strategy_registry.get(package["strategy_id"], package["source"]["candidate_id"])
        if spec.params_hash != package["params_hash"] or spec.strategy_version != package["strategy_version"]:
            raise DeliveryError("registered_strategy_identity_changed")
        HistorySpec.from_payload(binding)
        entrypoint = "existing_donchian_history_replay"
    elif adapter_id == "btc_frozen_qlib_offline_v1":
        from integrations.qlib_adapter.frozen_inference import _validate_static_binding
        _validate_static_binding(binding)
        if binding["artifact_sha256"]["model.txt"] != package["artifacts"]["model.txt"]:
            raise DeliveryError("registered_model_identity_changed")
        entrypoint = "existing_frozen_qlib_offline_replay"
    else: raise DeliveryError("btc_registered_adapter_unsupported")
    return {"registration_id": row["id"], "content_digest": content_digest,
            "adapter_id": adapter_id, "entrypoint": entrypoint, "binding": binding,
            "binding_digest": digest(binding), "permissions": row["permissions"]}


def offline_simulated_account_identity():
    """Identity of the existing in-process fixture venue, never an actual account."""
    from .btc_demo_start_attempt import authoritative_account_identity_snapshot
    return authoritative_account_identity_snapshot({"uid":"offline-account", "mainUid":"offline-main"})["hash"]


def registered_offline_run_id(registration_id):
    # The persisted management word 'delivery' contains 'live'. It must not be
    # reused verbatim as an execution namespace under the existing mode guard.
    return "qlibreg" + digest(registration_id)[:16]


def state_directory_digest(path):
    from pathlib import Path
    import os
    return digest(os.path.normcase(str(Path(path).resolve())))


def market_frame_digest(bars):
    import hashlib
    columns = ["event_time", "available_time", "decision_time", "instrument", "open", "high", "low", "close", "volume"]
    return hashlib.sha256(bars[columns].to_json(orient="split",date_format="iso",double_precision=15,index=False).encode()).hexdigest()


def observation_digest(observations):
    from dataclasses import asdict
    import json
    return digest(json.loads(json.dumps([asdict(o) for o in observations],default=str)))


def _validate_v2_instrument_contract(value):
    from decimal import Decimal, InvalidOperation
    from datetime import datetime, timezone
    expected_keys={"venue","instrument_id","contract_value_btc","lot_size_contracts",
        "minimum_size_contracts","maximum_market_size_contracts","source_record_id","source_version",
        "source_sha256","observed_at","available_time","historical_availability_assumption"}
    try:
        if set(value)!=expected_keys or value["venue"]!="OKX" or value["instrument_id"]!="BTC-USDT-SWAP": raise ValueError()
        exact={"contract_value_btc":Decimal("0.01"),"lot_size_contracts":Decimal("0.01"),
            "minimum_size_contracts":Decimal("0.01"),"maximum_market_size_contracts":Decimal("35000")}
        if any(Decimal(str(value[key]))!=expected for key,expected in exact.items()): raise ValueError()
        if value["source_sha256"]!="1a3be93ab5be07d8d0625ff37c077a461cba075876e44e8517266c9a28e336e8": raise ValueError()
        if value["historical_availability_assumption"]!="frozen_engineering_contract_assumption_not_june_pit_proof": raise ValueError()
        observed=datetime.fromisoformat(value["observed_at"].replace("Z","+00:00"))
        available=datetime.fromisoformat(value["available_time"].replace("Z","+00:00"))
        if observed.tzinfo is None or available.tzinfo is None or observed.astimezone(timezone.utc)!=available.astimezone(timezone.utc): raise ValueError()
        if not value["source_record_id"] or not value["source_version"]: raise ValueError()
    except (AttributeError,KeyError,TypeError,ValueError,InvalidOperation) as exc:
        raise DeliveryError("registered_instrument_contract_invalid") from exc
    return value


def registered_protection_policy(package):
    """Map frozen candidate OCO capability, never substitute Demo defaults."""
    from decimal import Decimal, InvalidOperation
    from .qlib_offline_replay import ServerSideProtectionPolicy
    try:
        policy=package["contracts"]["exit"]
        if policy.get("protection")!={"version":"registered_offline_oco_v1","trigger":"mark",
            "reference_price":"aggressive_limit_at_order_construction","effective":"attached_after_fill"}:
            raise ValueError()
        sl=Decimal(str(policy["hard_stop_fraction"]))*10000
        tp=Decimal(str(policy["take_profit_fraction"]))*10000
        if not sl.is_finite() or not tp.is_finite(): raise ValueError()
        mapping={"policy_id":"registered-"+digest(policy)[:24],"version":"1","trigger":"mark",
            "sl_distance_bps":str(sl),"tp_distance_bps":str(tp),"policy_sha256":""}
        value=ServerSideProtectionPolicy.from_mapping(mapping)
        mapping["policy_sha256"]=value.expected_sha256()
        value=ServerSideProtectionPolicy.from_mapping(mapping)
        if value.validate(): raise ValueError()
        return value
    except (KeyError,TypeError,ValueError,InvalidOperation) as exc:
        raise DeliveryError("registered_protection_contract_unsupported") from exc


class VerifiedRegisteredInputs:
    """Application-owned verified inputs. Rechecked against registration per use.

    Construction is performed by verify_registered_candidate_inputs; a supplied
    boolean, prediction table or caller-authored risk object cannot substitute.
    """
    __slots__=("service","row","recovery_only","decision_only","runtime_binding","state_dir","package","manifest","bars",
               "observations","predictions","digest","__weakref__")

    def __init_subclass__(cls, **kwargs):
        raise TypeError("registered_context_cannot_be_subclassed")

    def __setattr__(self,name,value):
        raise AttributeError("registered_context_is_immutable")

    def __init__(self, *, service, row, bars, manifest, observations, predictions, state_dir, recovery_only=False,
            decision_only=False, runtime_binding=None, _issuer=None):
        if _issuer is not _ISSUE_KEY: raise DeliveryError("registered_issued_context_required")
        from copy import deepcopy
        stored_row=deepcopy(row)
        values={"service":service,"row":stored_row,"recovery_only":recovery_only,"decision_only":decision_only,
            "runtime_binding":deepcopy(runtime_binding),"state_dir":state_dir,
            "package":stored_row["package"],"manifest":deepcopy(manifest),"bars":bars.copy(deep=True),
            "observations":tuple(observations),"predictions":predictions,
            "digest":digest({"registration_id":row["id"], "package":row["content_digest"],
            "binding":row["binding_digest"], "runtime":runtime_binding, "manifest":manifest})
        }
        for name,value in values.items(): object.__setattr__(self,name,value)
        _ISSUED_CONTEXTS.add(self)

    def check(self):
        require_registered_context(self)
        import pandas as pd
        resolve = self.service.resolve_recovery if self.recovery_only else self.service.resolve
        row = resolve(self.row["id"],content_digest=self.row["content_digest"],
            account_identity_hash=self.row["binding"]["identity_hash"],adapter_id=self.package["adapter_id"])
        if (row["binding_digest"] != self.row["binding_digest"] or digest(self.package) != row["content_digest"]
            or market_frame_digest(self.bars) != self.manifest["bars_sha256"]
            or observation_digest(self.observations) != self.manifest["observations_sha256"]
            or self.digest != digest({"registration_id":row["id"],"package":row["content_digest"],
                "binding":row["binding_digest"],"runtime":self.runtime_binding,"manifest":self.manifest})):
            raise DeliveryError("registered_verified_inputs_changed")
        # Re-run the public verifier rather than trusting this Python type's
        # constructor or caller-rehashed fields as an authority token.
        actual = verify_registered_candidate_inputs(self.service,row["id"],
            content_digest=row["content_digest"],account_identity_hash=row["binding"]["identity_hash"],
            adapter_id=self.package["adapter_id"],bars=self.bars,market_manifest=self.manifest,
            market_manifest_digest=digest(self.manifest),observations=self.observations,
            state_dir=self.state_dir,recovery_only=self.recovery_only,decision_only=self.decision_only,
            runtime_binding=self.runtime_binding)
        pd.testing.assert_frame_equal(actual.predictions["rows"],self.predictions["rows"])
        return row

    def forecast(self, index):
        require_registered_context(self)
        from quant_crypto.portfolio.forecast import BTCForecast, BTCForecastQuality
        from quant_crypto.trading_contracts import SignalDirection
        observation = self.observations[index]
        rows = self.predictions["rows"]
        matches = rows.loc[rows.event_time == observation.event_time_utc]
        if len(matches) != 1: raise DeliveryError("registered_prediction_missing_or_ambiguous")
        r = matches.iloc[0]
        p, c = self.package, self.package["contracts"]
        e = c["calibration"]["evidence"]
        identity = digest({"inputs":self.digest,"event_time":observation.event_time_utc.isoformat()})
        return BTCForecast(timestamp_utc=r.decision_time.to_pydatetime(),strategy_id=p["strategy_id"],symbol=p["instrument"],
            direction=SignalDirection.LONG if r.prediction>0 else SignalDirection.SHORT if r.prediction<0 else SignalDirection.FLAT,
            score=abs(float(r.prediction)),horizon=str(c["output"]["horizon_bars"])+"h",unit="bps",
            expected_return_bps=float(r.prediction)*10000,
            confidence=1.,  # unit multiplier, not a claim of trading probability
            expiry_utc=r.expires_at.to_pydatetime(),source_signal_id="registered-signal-"+identity,
            quality=BTCForecastQuality(ic=e["quality"]["ic"],hit_rate=e["quality"]["hit_rate"],
                sample_size=len(p["evidence_receipt"]["fit_rows"]),evidence_path="package:evidence_receipt:validation_only",
                evidence_hash=p["evidence_receipt_sha256"]),forecast_id="registered-forecast-"+identity,
            metadata={"registered_inputs_digest":self.digest,"model_sha256":p["model"]["sha256"],
                      "data_version":p["data_version"],"research_only":True,"fixture_only":False})


def verify_registered_candidate_inputs(service, registration_id, *, content_digest, account_identity_hash,
        adapter_id, bars, market_manifest, market_manifest_digest, observations, state_dir, recovery_only=False,
        decision_only=False, runtime_binding=None):
    """Validate before any replay constructor, state directory or economic write."""
    _require_trusted_service(service)
    from pathlib import Path
    import math
    import pandas as pd
    from integrations.qlib_adapter.package_inference import infer_package
    from quant_shared.strategy_delivery.runtime_contract import CAPABILITY
    resolve = service.resolve_recovery if recovery_only else service.resolve
    row = resolve(registration_id,content_digest=content_digest,
        account_identity_hash=account_identity_hash,adapter_id=adapter_id)
    p, b, m = row["package"], row["binding"], market_manifest
    runtime=dict(runtime_binding if decision_only else b.get("offline_runtime",{}))
    if recovery_only and not decision_only and not (Path(state_dir)/"runtime").is_dir():
        raise DeliveryError("registered_recovery_existing_state_required")
    if adapter_id != CAPABILITY or row["target"] != "offline": raise DeliveryError("registered_offline_adapter_required")
    expected_schema="delivery_offline_runtime_v3" if decision_only else "delivery_offline_runtime_v1"
    if (runtime.get("schema_version")!=expected_schema
        or runtime.get("simulated_venue_identity_hash") != offline_simulated_account_identity()
        or (not decision_only and runtime.get("account_ref")!=b["account_ref"])
        or (decision_only and runtime.get("adapter_ids") != ["btc_donchian_history_offline_v1","factory_lgbm_ast_v1"])
        or runtime.get("contract_digest")!=digest({k:v for k,v in runtime.items() if k!="contract_digest"})
        or runtime.get("state_directory_sha256") != state_directory_digest(state_dir)):
        raise DeliveryError("registered_simulated_account_identity_mismatch")
    market_schema=m.get("schema_version")
    if (digest(m) != market_manifest_digest or market_schema not in {"registered_offline_market_v1","registered_offline_market_v2"}
        or any(m.get(k) != p[k] for k in ("data_version","instrument","bar_size","settlement_currency"))
        or m.get("bars_sha256") != market_frame_digest(bars)
        or m.get("observations_sha256") != observation_digest(observations)
        or m.get("initial_equity_usdt") != runtime.get("initial_equity_usdt")
        or not math.isfinite(float(m.get("initial_equity_usdt",0))) or float(m["initial_equity_usdt"]) <= 0):
        raise DeliveryError("registered_market_manifest_mismatch")
    if market_schema=="registered_offline_market_v2":
        contract=_validate_v2_instrument_contract(m.get("instrument_contract"))
        if (m.get("valuation_policy")!="minute_close_sampled_valuation_not_exchange_actual_settlement"
            or m.get("funding_event_count")!=6
            or not isinstance(m.get("dataset_contract_sha256"),str) or len(m["dataset_contract_sha256"])!=64
            or not isinstance(m.get("funding_events_sha256"),str) or len(m["funding_events_sha256"])!=64
            or not isinstance(m.get("funding_rate_history_sha256"),str) or len(m["funding_rate_history_sha256"])!=64):
            raise DeliveryError("registered_market_v2_binding_invalid")
    c = p["contracts"]
    registered_protection_policy(p)
    if c["output"]["valid_for_bars"] <= c["cost"]["execution_delay_bars"]-1:
        raise DeliveryError("registered_forecast_expires_before_execution")
    if (c["cost"]["fee_bps_per_side"] != 5
        or sum(c["cost"][k] for k in ("spread_bps_per_side","slippage_bps_per_side","impact_bps_per_side")) != 6):
        raise DeliveryError("registered_cost_not_supported_by_existing_simulator")
    if c["output"].get("score_rule") != "absolute_return_fraction_unit_multiplier":
        raise DeliveryError("registered_forecast_score_rule_missing")
    if not observations: raise DeliveryError("registered_observations_missing")
    times = [o.event_time_utc for o in observations]
    if times != sorted(set(times)): raise DeliveryError("registered_observations_unordered")
    for o in observations:
        at = bars.loc[bars.event_time == o.event_time_utc]
        delayed = bars.loc[bars.event_time == o.event_time_utc + pd.Timedelta(hours=2)]
        if len(at)!=1 or len(delayed)!=1 or float(at.iloc[0].close)!=o.close_price or float(delayed.iloc[0].open)!=o.delayed_open_price:
            raise DeliveryError("registered_market_price_or_timing_mismatch")
        if not o.maintenance_facts: raise DeliveryError("registered_maintenance_facts_missing")
        # This adapter accepts explicitly observed intrahour quotes at <=90s
        # gaps, inside the supplied replay interval. This is an input capability
        # restriction, not a change to the authority chain's 100s stale checks.
        fact_times=[f.observed_at_utc for f in o.maintenance_facts]
        end=o.event_time_utc+pd.Timedelta(hours=2)
        if any(t<=o.event_time_utc or t>end for t in fact_times):
            raise DeliveryError("registered_maintenance_time_outside_execution_window")
        edges=[o.event_time_utc,*fact_times,end]
        if any(b-a>pd.Timedelta(seconds=90) for a,b in zip(edges,edges[1:])):
            raise DeliveryError("registered_maintenance_coverage_missing")
    if market_schema=="registered_offline_market_v2":
        settlements=[fact for observation in observations for fact in observation.funding_settlements]
        expected_times={pd.Timestamp(value).to_pydatetime() for value in (
            "2026-06-16T08:00:00Z","2026-06-16T16:00:00Z","2026-06-17T00:00:00Z",
            "2026-06-17T08:00:00Z","2026-06-17T16:00:00Z","2026-06-18T00:00:00Z")}
        if (len(settlements)!=6 or len({fact.event_id for fact in settlements})!=6
            or {fact.event_time_utc for fact in settlements}!=expected_times
            or any(observation.funding_cashflow_usdt!=0 for observation in observations)
            or any(fact.valuation_policy!=m["valuation_policy"] for fact in settlements)):
            raise DeliveryError("registered_funding_events_invalid")
    elif any(observation.funding_settlements for observation in observations):
        raise DeliveryError("registered_funding_v2_requires_market_v2")
    predictions = infer_package(p,bars,data_version=p["data_version"],visible_through=observations[-1].event_time_utc+pd.Timedelta(hours=1))
    verified = VerifiedRegisteredInputs(service=service,row=row,bars=bars,manifest=m,observations=observations,
        predictions=predictions,state_dir=state_dir,recovery_only=recovery_only,decision_only=decision_only,
        runtime_binding=runtime_binding,_issuer=_ISSUE_KEY)
    for i in range(len(observations)): verified.forecast(i)
    return verified


def registered_candidate_cohort_decision(*, verified, index, controller, venue, member_contracts, member_state):
    """Evaluate the registered model and unchanged frozen policy for one member share."""
    require_registered_context(verified)
    if not verified.decision_only: raise DeliveryError("registered_cohort_decision_context_required")
    from dataclasses import replace
    from decimal import Decimal
    import math
    from integrations.qlib_adapter.candidate_policy import (CandidateExitObservation, CandidateExitPolicy,
        CandidateExitState, CandidatePolicyFacts, CandidatePolicyVersions, POLICY_VERSION)
    from quant_crypto.application.qlib_offline_replay import evaluate_candidate_step
    from quant_crypto.portfolio.forecast import BTCRiskBudget, BTCRiskState
    from quant_crypto.portfolio.order_intent import BTCExecutionCostEstimate
    from quant_crypto.risk import CombinedLossAssessment, RiskConstitution
    from quant_crypto.risk.liquidation import BTCReferencePriceState
    from quant_crypto.trading_contracts import Signal, SignalDirection
    forecast=verified.forecast(index); observation=verified.observations[index]
    contracts=verified.package["contracts"]
    position_policy,exit_policy,cost=contracts["position"],contracts["exit"],contracts["cost"]
    member_btc=float(Decimal(str(member_contracts))*Decimal("0.01"))
    common_btc=float(Decimal(str(venue.state["position"]))*Decimal("0.01"))
    equity=float(venue.state["equity"])
    if not math.isfinite(equity) or equity<=0: raise DeliveryError("registered_cohort_equity_invalid")
    risk=controller._state.get("risk_control",{})
    exit_raw=member_state.get("exit_state") or {"quantity":member_btc,"average_price":0.0,
        "favorable_price":None,"holding_bars":0}
    try: exit_state=CandidateExitState(**exit_raw)
    except (TypeError,ValueError) as exc: raise DeliveryError("registered_cohort_member_exit_state_invalid") from exc
    constitution=RiskConstitution(max_abs_position=equity/observation.mark_price,
        max_quantity=equity/observation.mark_price,max_notional=equity*position_policy["max_weight"],max_leverage=1.0,
        min_liquidation_buffer_bps=1000,max_daily_loss=equity*.03,max_drawdown=.12,
        max_combined_loss=equity*.12,protection_required=True)
    facts=CandidatePolicyFacts(decision_id=digest({"verified":verified.digest,"index":index,"member_state":member_state}),
        forecast=forecast,expected_source_signal_id=forecast.source_signal_id,
        risk_budget=BTCRiskBudget(max_btc_exposure=position_policy["max_weight"],
            strategy_risk_budget=position_policy["risk_budget_fraction"],
            target_volatility=position_policy["volatility_target_annual_configured"],
            current_weight=member_btc*observation.mark_price/equity,min_cash_fraction=1-position_policy["max_weight"],
            max_turnover=position_policy["max_weight"],max_daily_loss_pct=.03,max_drawdown_pct=.12,
            max_abs_funding_rate=1.0,require_funding_rate=True),
        risk_state=BTCRiskState(cash_fraction=1-abs(common_btc*observation.mark_price/equity),
            daily_loss_pct=float(risk.get("daily_loss_pct",0)),current_drawdown_pct=float(risk.get("drawdown_ratio",0)),
            funding_rate=observation.funding_rate,data_anomaly=bool(observation.blockers)),
        account_equity=equity,mark_price=observation.mark_price,current_quantity=member_btc,
        reference_prices=lambda proposed: BTCReferencePriceState(observed_at_utc=forecast.timestamp_utc,
            signal_price=observation.close_price,execution_price=observation.close_price*(1+math.copysign(.0006,
                float(proposed.target_quantity or 0)-member_btc)),mark_price=observation.mark_price,
            index_price=observation.index_price,current_mark_price=observation.mark_price,
            primary_mid=observation.close_price,spread_bps=2.0,data_age_ms=0,
            source="registered_cohort_common_observation"),constitution=constitution,
        combined_loss=CombinedLossAssessment(0.0,0.0,0.0,(),0.0,0.0,observation.funding_cashflow_usdt,0.0,0.0,0.0),
        protection_before=None if not member_btc else {"present":True,"quantity":abs(member_btc),
            "side":"sell" if member_btc>0 else "buy","trigger_price":observation.mark_price*(1-float(exit_policy["hard_stop_fraction"]))},
        protection_after=lambda q: None if abs(q)<1e-12 else {"present":True,"quantity":abs(q),
            "side":"sell" if q>0 else "buy","trigger_price":observation.mark_price*(
                1-float(exit_policy["hard_stop_fraction"]) if q>0 else 1+float(exit_policy["hard_stop_fraction"]))},
        cost_estimate=BTCExecutionCostEstimate(fee_bps=2*cost["fee_bps_per_side"],
            spread_bps=2*cost["spread_bps_per_side"],slippage_bps=2*cost["slippage_bps_per_side"],
            impact_bps=2*cost["impact_bps_per_side"],funding_bps=abs(observation.funding_rate)*20000,
            source="registered_frozen_cost_matches_offline_simulator"),min_quantity=.00001,
        blockers=observation.blockers,exit_state=exit_state,
        exit_observation=CandidateExitObservation(observation.close_price,forecast.expected_return_bps/10000,True,observation.end_of_window),
        exit_policy=CandidateExitPolicy(exit_policy["hard_stop_fraction"],exit_policy["trailing_stop_fraction"],exit_policy["maximum_holding_bars"]),
        versions=CandidatePolicyVersions(POLICY_VERSION,*(digest(contracts[name]) for name in ("position","exit","cost"))))
    step=evaluate_candidate_step(facts,venue={"contract_value_btc":"0.01","lot_size_contracts":"0.01",
        "minimum_size_contracts":"0.01","maximum_absolute_contracts":str(equity/observation.mark_price/0.01)})
    if step.execution_blockers or step.conversion is None:
        raise DeliveryError("registered_cohort_policy_conversion_blocked")
    target_metadata={**step.policy.target.metadata,"quantity_unit":"btc","registered_source":True}
    quantity=Decimal(str(step.policy.target.target_quantity or 0))
    direction=SignalDirection.LONG if quantity>0 else SignalDirection.SHORT if quantity<0 else SignalDirection.FLAT
    signal=Signal(timestamp_utc=forecast.timestamp_utc,strategy_id=forecast.strategy_id,symbol=forecast.symbol,
        direction=direction,strength=forecast.score,horizon=forecast.horizon,
        reason="registered_forecast_through_original_frozen_policy",metadata={"source_kind":"forecast",
            "forecast_id":forecast.forecast_id,"registered_source":True},signal_id=forecast.source_signal_id)
    target_identity=digest({"schema_version":"registered_cohort_qlib_target_identity_v1",
        "verified_digest":verified.digest,"index":index,"member_state_sha256":member_state.get("sha256"),
        "forecast_id":forecast.forecast_id,"signal_id":signal.signal_id,
        "target_weight":step.policy.target.target_weight,"target_quantity":step.policy.target.target_quantity,
        "metadata":target_metadata})
    target=replace(step.policy.target,signal_id=signal.signal_id,
        target_position_id="tgt_"+target_identity[:16],metadata=target_metadata)
    return {"signal":signal,"forecast":forecast,"target":target},{"exit_state":step.policy.exit_state.__dict__,
        "approved":step.policy.approved,"policy_reasons":list(step.policy.reasons),
        "exit_reasons":list(step.policy.exit_reasons)}


def open_btc_registered_candidate_offline(service, registration_id, *, content_digest,
        account_identity_hash, adapter_id, bars, market_manifest, market_manifest_digest, observations, state_dir, repo_root,recovery_only=False):
    from .qlib_offline_replay import QlibFixtureReplayConfig, QlibFixtureOfflineReplay
    verified = verify_registered_candidate_inputs(service,registration_id,content_digest=content_digest,
        account_identity_hash=account_identity_hash,adapter_id=adapter_id,bars=bars,market_manifest=market_manifest,
        market_manifest_digest=market_manifest_digest,observations=observations,state_dir=state_dir,recovery_only=recovery_only)
    p = verified.package
    config = QlibFixtureReplayConfig(repo_root=repo_root,state_dir=state_dir,run_id=registered_offline_run_id(registration_id),
        decision_time_utc=verified.forecast(0).timestamp_utc,strategy_id=p["strategy_id"],strategy_version=p["strategy_version"],
        candidate_id=p["source"]["candidate_id"],model_sha256=p["model"]["sha256"],data_version=p["data_version"],
        policy_sha256=digest({k:p["contracts"][k] for k in ("position","exit","cost")}),
        truth_kind="registered_candidate_offline_only",verified_package_sha256=content_digest,
        initial_equity_usdt=market_manifest["initial_equity_usdt"])
    return QlibFixtureOfflineReplay(config,registered_inputs=verified)
