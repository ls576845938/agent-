from __future__ import annotations

import ast
import hashlib
import inspect
import json
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any

import pytest

from quant_crypto.oms.shared_platform_v3 import (
    OMSAttachedProtection,
    OMSContractError,
    OMSOrderSubmissionBundle,
    OMSProofIdentity,
    SharedPlatformV3OMS,
    order_intent_execution_digest,
)
from quant_crypto.oms.okx_demo_paper_runtime import (
    OkxDemoPaperRuntimeController,
    ServerSideProtectionPolicy,
)
from quant_crypto.portfolio.decision import (
    BTC_RISK_REDUCTION_PLAN_VERSION,
    BTCPortfolioDecision,
    RiskReductionPlan,
)
from quant_crypto.risk import ActionRiskEffect, RiskAssessment
from quant_crypto.trading_contracts import (
    OrderIntent,
    OrderSide,
    OrderType,
    Signal,
    SignalDirection,
    TargetPosition,
    TimeInForce,
)
from quant_shared.runtime.permissions import (
    RuntimeAction,
    RuntimeAuthoritativeRiskResult,
    RuntimeRiskEffect,
    RuntimeRiskEvidenceAuthority,
)


NOW = datetime(2026, 8, 23, 1, 0, tzinfo=timezone.utc)


def _signal() -> Signal:
    return Signal(
        timestamp_utc=NOW,
        strategy_id="t5_strategy",
        symbol="BTC-USDT-SWAP",
        direction=SignalDirection.LONG,
        strength=1.0,
        horizon="completed_1h",
        signal_id="sig_t5",
        metadata={"source": "t5_contract"},
    )


def _proof(intent: OrderIntent | None = None) -> OMSProofIdentity:
    if intent is None:
        intent = OrderIntent(
            timestamp_utc=NOW,
            strategy_id="t5_strategy",
            symbol="BTC-USDT-SWAP",
            side=OrderSide.BUY,
            quantity=0.01,
            order_type=OrderType.LIMIT,
            limit_price=60000.0,
            time_in_force=TimeInForce.FOK,
            signal_id="sig_t5",
            target_position_id="target-t5",
            client_order_id="btcDPt50001",
            order_intent_id="intent-t5",
        )
    return OMSProofIdentity(
        source_head="a8f1aa7e1a5e43e68bfb1dab3f7b16b9fa48a1ad",
        account_identity="a" * 64,
        session_id="run-t5",
        key_namespace="quant-system.okx-demo.trade",
        client_order_namespace="btcDPt5",
        epoch=3,
        intent_digest=order_intent_execution_digest(intent),
    )


def _target(quantity: float, *, allowed: bool = True) -> TargetPosition:
    signal = _signal()
    return TargetPosition(
        timestamp_utc=NOW,
        strategy_id=signal.strategy_id,
        symbol=signal.symbol,
        target_weight=quantity,
        target_quantity=quantity,
        signal_id=signal.signal_id,
        target_position_id="target-t5",
        metadata={
            "order_generation_allowed": allowed,
            "forecast_id": "sig_t5",
        },
    )


def _signal_target(quantity: float, *, allowed: bool = False) -> TargetPosition:
    signal = _signal()
    return TargetPosition(
        timestamp_utc=NOW,
        strategy_id=signal.strategy_id,
        symbol=signal.symbol,
        target_weight=quantity,
        target_quantity=quantity,
        signal_id=signal.signal_id,
        target_position_id="target-t5-signal",
        metadata={
            "order_generation_allowed": allowed,
            "source_kind": "signal",
            "source_signal_id": signal.signal_id,
        },
    )


def _assessment(
    *,
    before: float,
    after: float,
    approved: bool = True,
    requires_reduction: bool = False,
    effect: ActionRiskEffect = ActionRiskEffect.INCREASE_ABS_EXPOSURE,
    blockers: tuple[str, ...] = (),
) -> RiskAssessment:
    return RiskAssessment(
        approved=approved,
        status="approved" if approved else "blocked",
        effect=effect,
        blockers=blockers,
        reasons=blockers,
        requires_reduction=requires_reduction,
        max_safe_quantity=abs(after),
        metadata={
            "position_before": before,
            "position_after": after,
            "execution_permission": False,
        },
    )


def _opening_bundle() -> OMSOrderSubmissionBundle:
    oms = SharedPlatformV3OMS()
    signal = _signal()
    target = _target(0.01)
    assessment = _assessment(before=0.0, after=0.01)
    decision = BTCPortfolioDecision(
        target_position=target,
        risk_assessment=assessment,
        reduction_plan=None,
        decision_time_utc=NOW,
        source="t5_contract",
        reason_codes=(),
        order_generation_allowed=True,
    )
    protection = oms.build_attached_protection(
        policy={
            "policy_id": "t5-policy",
            "version": "1",
            "sl_distance_bps": "100",
            "tp_distance_bps": "200",
            "trigger": "mark",
        },
        entry_price="60000",
        tick_size="0.1",
        position_side="long",
        client_order_id="btcDPt50001",
        contracts="0.01",
    )
    intent = OrderIntent(
        timestamp_utc=NOW,
        strategy_id=signal.strategy_id,
        symbol=signal.symbol,
        side=OrderSide.BUY,
        quantity=0.01,
        order_type=OrderType.LIMIT,
        limit_price=60000.0,
        time_in_force=TimeInForce.FOK,
        signal_id=signal.signal_id,
        target_position_id=target.target_position_id,
        client_order_id="btcDPt50001",
        order_intent_id="intent-t5",
    )
    return oms.build_order_submission_bundle(
        signal=signal,
        target_position=target,
        risk_assessment=assessment,
        portfolio_decision=decision,
        position_before=0.0,
        position_after=0.01,
        action=RuntimeAction.SUBMIT_NEW_ORDER,
        risk_effect=RuntimeRiskEffect.INCREASE_ABS_EXPOSURE,
        proof_identity=_proof(intent),
        price="60000",
        quantity="0.01",
        venue_facts={"instrument_id": "BTC-USDT-SWAP", "margin_mode": "isolated", "position_side": "long"},
        cost_facts={"fee_bps": "5", "impact_bps": "1"},
        intent=intent,
        protection=protection,
        guardian_health={"passed": True, "healthy": True},
    )


def _signal_reduction_bundle(
    *,
    plan_signal_id: str = "sig_t5",
    target_source_signal_id: str = "sig_t5",
    target_forecast_id: str = "",
    target_declared_forecast_id: str = "",
) -> OMSOrderSubmissionBundle:
    oms = SharedPlatformV3OMS()
    signal = _signal()
    target = _signal_target(0.0)
    target.metadata["source_signal_id"] = target_source_signal_id
    if target_forecast_id:
        target.metadata["forecast_id"] = target_forecast_id
    if target_declared_forecast_id:
        target.metadata["source_forecast_id"] = target_declared_forecast_id
    assessment = _assessment(
        before=0.01,
        after=0.0,
        approved=False,
        requires_reduction=True,
        effect=ActionRiskEffect.DECREASE_ABS_EXPOSURE,
        blockers=("risk_reduction_required",),
    )
    plan = RiskReductionPlan(
        symbol=target.symbol,
        strategy_id=target.strategy_id,
        decision_time_utc=NOW,
        source_forecast_id="",
        source_target_position_id=target.target_position_id,
        current_quantity=0.01,
        target_quantity=0.0,
        reduction_quantity=0.01,
        max_safe_quantity=0.0,
        reason_codes=("risk_reduction_required",),
        source_kind="signal",
        source_signal_id=plan_signal_id,
        plan_version=BTC_RISK_REDUCTION_PLAN_VERSION,
    )
    decision = BTCPortfolioDecision(
        target_position=target,
        risk_assessment=assessment,
        reduction_plan=plan,
        decision_time_utc=NOW,
        source="t5_signal_contract",
        reason_codes=("risk_reduction_required",),
        order_generation_allowed=False,
    )
    intent = OrderIntent(
        timestamp_utc=NOW,
        strategy_id=signal.strategy_id,
        symbol=signal.symbol,
        side=OrderSide.SELL,
        quantity=0.01,
        order_type=OrderType.LIMIT,
        limit_price=60000.0,
        time_in_force=TimeInForce.IOC,
        signal_id=signal.signal_id,
        target_position_id=target.target_position_id,
        client_order_id="btcDPt5sig01",
        order_intent_id="intent-t5-signal-reduce",
    )
    return oms.build_order_submission_bundle(
        signal=signal,
        target_position=target,
        risk_assessment=assessment,
        portfolio_decision=decision,
        position_before=0.01,
        position_after=0.0,
        action=RuntimeAction.REDUCE_ONLY,
        risk_effect=RuntimeRiskEffect.DECREASE_ABS_EXPOSURE,
        proof_identity=_proof(intent),
        price="60000",
        quantity="0.01",
        venue_facts={
            "instrument_id": "BTC-USDT-SWAP",
            "margin_mode": "isolated",
            "position_side": "long",
        },
        cost_facts={"fee_bps": "5"},
        intent=intent,
    )


def test_failure_first_naked_approved_bool_is_not_an_oms_record() -> None:
    with pytest.raises(OMSContractError, match="t2_risk_assessment_missing_or_invalid"):
        SharedPlatformV3OMS().build_order_submission_bundle(  # type: ignore[arg-type]
            signal=_signal(),
            target_position=_target(0.01),
            risk_assessment={"approved": True},
            portfolio_decision={"approved": True},
            position_before=0.0,
            position_after=0.01,
            action=RuntimeAction.SUBMIT_NEW_ORDER,
            risk_effect=RuntimeRiskEffect.INCREASE_ABS_EXPOSURE,
            proof_identity=_proof(),
            price="60000",
            quantity="0.01",
            venue_facts={},
            cost_facts={"fee_bps": "5"},
            protection=None,
            guardian_health={"passed": True, "healthy": True},
        )


def test_legacy_compatibility_builder_is_disabled_without_real_t2_t3() -> None:
    bundle = _opening_bundle()
    with pytest.raises(OMSContractError, match="legacy_compatibility_bundle_disabled"):
        SharedPlatformV3OMS().build_legacy_compatibility_bundle(
            signal=bundle.signal,
            target_position=bundle.target_position,
            current_quantity=bundle.position_before,
            target_quantity=bundle.position_after,
            action=bundle.action,
            quantity=bundle.quantity,
            price=bundle.price,
            venue_facts=bundle.venue_facts,
            cost_facts=bundle.cost_facts,
            proof_identity=bundle.proof_identity,
            protection=bundle.protection,
            intent=bundle.intent,
        )


def test_proof_identity_is_pending_until_dispatcher_authority() -> None:
    pending = _opening_bundle().proof_identity
    wire = pending.to_dict()
    assert wire["authority_verified"] is False
    assert wire["execution_permission"] is False
    assert wire["evidence_status"] == "pending_dispatcher_authority"
    assert wire["evidence_identity"] == "pending_dispatcher_authority"
    assert wire["evidence_digest"] == ""
    with pytest.raises(OMSContractError, match="proof_pending_authority_required"):
        OMSProofIdentity(
            source_head="a" * 40,
            account_identity="a" * 64,
            session_id="run",
            key_namespace="quant-system.okx-demo.trade",
            client_order_namespace="btcDPtest",
            epoch=1,
            intent_digest="b" * 64,
            evidence_identity="dispatcher:fake",
        )
    with pytest.raises(OMSContractError, match="proof_evidence_not_issued"):
        OMSProofIdentity(
            source_head="a" * 40,
            account_identity="a" * 64,
            session_id="run",
            key_namespace="quant-system.okx-demo.trade",
            client_order_namespace="btcDPtest",
            epoch=1,
            intent_digest="b" * 64,
            evidence_digest="b" * 64,
        )
    with pytest.raises(OMSContractError, match="proof_authority_verification_forbidden"):
        OMSProofIdentity(
            source_head="a" * 40,
            account_identity="a" * 64,
            session_id="run",
            key_namespace="quant-system.okx-demo.trade",
            client_order_namespace="btcDPtest",
            epoch=1,
            intent_digest="b" * 64,
            authority_verified=True,
        )


def test_t5_digest_matches_instance_scoped_t1_evidence_and_semantic_tamper() -> None:
    intent = OrderIntent(
        timestamp_utc=NOW,
        strategy_id="t5_strategy",
        symbol="BTC-USDT-SWAP",
        side=OrderSide.BUY,
        quantity=0.01,
        order_type=OrderType.LIMIT,
        limit_price=60000.0,
        time_in_force=TimeInForce.FOK,
        run_id="run-t5",
        signal_id="sig_t5",
        target_position_id="target-t5",
        client_order_id="btcDPt50001",
        order_intent_id="intent-t5-canonical",
        metadata={
            "reduce_only": False,
            "position_side": "long",
            "trigger_type": "mark",
            "parent_order_id": "btcDPparent",
            "oco_id": "btcDPparentA",
        },
    )
    authority = RuntimeRiskEvidenceAuthority(name="t5-correction-02")
    producer, verifier = authority.bind()
    result = RuntimeAuthoritativeRiskResult.from_order_intent(
        intent,
        approved=True,
        actual_notional=600.0,
        venue="okx_demo",
        liquidation_safe=True,
        exposure=0.01,
    )
    evidence = producer.issue_from_authoritative(
        order_intent=intent,
        authoritative_result=result,
        source_head="a" * 40,
        account_identity="a" * 64,
        session_id="run-t5",
        key_namespace="quant-system.okx-demo.trade",
        client_order_namespace="btcDPt5",
        epoch=3,
        issued_at=NOW,
    )
    assert order_intent_execution_digest(intent) == evidence.intent_digest
    assert verifier.verify(
        evidence,
        order_intent=intent,
        source_head="a" * 40,
        account_identity="a" * 64,
        session_id="run-t5",
        key_namespace="quant-system.okx-demo.trade",
        client_order_namespace="btcDPt5",
        epoch=3,
        now=NOW,
    )

    semantic_fields = (
        "order_intent_id",
        "position_side",
        "reduce_only",
        "trigger_type",
        "parent_order_id",
        "oco_id",
    )
    for field_name in semantic_fields:
        if field_name == "order_intent_id":
            tampered = replace(intent, order_intent_id="intent-tampered")
        else:
            metadata = dict(intent.metadata)
            metadata[field_name] = f"tampered-{field_name}"
            tampered = replace(intent, metadata=metadata)
        assert order_intent_execution_digest(tampered) != evidence.intent_digest
        assert not verifier.verify(
            evidence,
            order_intent=tampered,
            source_head="a" * 40,
            account_identity="a" * 64,
            session_id="run-t5",
            key_namespace="quant-system.okx-demo.trade",
            client_order_namespace="btcDPt5",
            epoch=3,
            now=NOW,
        )


def test_quantity_side_position_and_protection_bindings_fail_closed() -> None:
    opening = _opening_bundle()
    assert opening.intent is not None
    bad_quantity_intent = replace(opening.intent, quantity=0.02)
    bad_quantity_proof = replace(
        opening.proof_identity,
        intent_digest=order_intent_execution_digest(bad_quantity_intent),
    )
    with pytest.raises(OMSContractError, match="order_quantity_position_delta_mismatch"):
        SharedPlatformV3OMS().build_order_submission_bundle(
            signal=opening.signal,
            target_position=opening.target_position,
            risk_assessment=opening.risk_assessment,
            portfolio_decision=opening.portfolio_decision,
            position_before=0.0,
            position_after=0.01,
            action=opening.action,
            risk_effect=opening.risk_effect,
            proof_identity=bad_quantity_proof,
            price=opening.price,
            quantity="0.02",
            venue_facts=opening.venue_facts,
            cost_facts=opening.cost_facts,
            intent=bad_quantity_intent,
            protection=opening.protection,
            guardian_health=opening.guardian_health,
        )

    bad_side_intent = replace(opening.intent, side=OrderSide.SELL)
    bad_side_proof = replace(
        opening.proof_identity,
        intent_digest=order_intent_execution_digest(bad_side_intent),
    )
    with pytest.raises(OMSContractError, match="intent_side_position_delta_mismatch"):
        SharedPlatformV3OMS().build_order_submission_bundle(
            signal=opening.signal,
            target_position=opening.target_position,
            risk_assessment=opening.risk_assessment,
            portfolio_decision=opening.portfolio_decision,
            position_before=0.0,
            position_after=0.01,
            action=opening.action,
            risk_effect=opening.risk_effect,
            proof_identity=bad_side_proof,
            price=opening.price,
            quantity=opening.quantity,
            venue_facts=opening.venue_facts,
            cost_facts=opening.cost_facts,
            intent=bad_side_intent,
            protection=opening.protection,
            guardian_health=opening.guardian_health,
        )

    with pytest.raises(OMSContractError, match="venue_position_side_missing_or_mismatch"):
        SharedPlatformV3OMS().build_order_submission_bundle(
            signal=opening.signal,
            target_position=opening.target_position,
            risk_assessment=opening.risk_assessment,
            portfolio_decision=opening.portfolio_decision,
            position_before=opening.position_before,
            position_after=opening.position_after,
            action=opening.action,
            risk_effect=opening.risk_effect,
            proof_identity=opening.proof_identity,
            price=opening.price,
            quantity=opening.quantity,
            venue_facts={**dict(opening.venue_facts), "position_side": "short"},
            cost_facts=opening.cost_facts,
            intent=opening.intent,
            protection=opening.protection,
            guardian_health=opening.guardian_health,
        )

    foreign_parent = SharedPlatformV3OMS().build_attached_protection(
        policy={
            "policy_id": "t5-policy",
            "version": "1",
            "sl_distance_bps": "100",
            "tp_distance_bps": "200",
            "trigger": "mark",
        },
        entry_price="60000",
        tick_size="0.1",
        position_side="long",
        client_order_id="btcDPforeign",
        contracts="0.01",
    )
    with pytest.raises(OMSContractError, match="protection_parent_intent_mismatch"):
        SharedPlatformV3OMS().build_order_submission_bundle(
            signal=opening.signal,
            target_position=opening.target_position,
            risk_assessment=opening.risk_assessment,
            portfolio_decision=opening.portfolio_decision,
            position_before=opening.position_before,
            position_after=opening.position_after,
            action=opening.action,
            risk_effect=opening.risk_effect,
            proof_identity=opening.proof_identity,
            price=opening.price,
            quantity=opening.quantity,
            venue_facts=opening.venue_facts,
            cost_facts=opening.cost_facts,
            intent=opening.intent,
            protection=foreign_parent,
            guardian_health=opening.guardian_health,
        )

    payload_tampered = OMSAttachedProtection(
        payload={**dict(opening.protection.payload), "sz": "0.02"},
        parent_client_order_id=opening.protection.parent_client_order_id,
        contracts=opening.protection.contracts,
        position_side=opening.protection.position_side,
        policy_digest=opening.protection.policy_digest,
    )
    with pytest.raises(OMSContractError, match="protection_payload_quantity_mismatch"):
        SharedPlatformV3OMS().build_order_submission_bundle(
            signal=opening.signal,
            target_position=opening.target_position,
            risk_assessment=opening.risk_assessment,
            portfolio_decision=opening.portfolio_decision,
            position_before=opening.position_before,
            position_after=opening.position_after,
            action=opening.action,
            risk_effect=opening.risk_effect,
            proof_identity=opening.proof_identity,
            price=opening.price,
            quantity=opening.quantity,
            venue_facts=opening.venue_facts,
            cost_facts=opening.cost_facts,
            intent=opening.intent,
            protection=payload_tampered,
            guardian_health=opening.guardian_health,
        )


def test_t1_execution_digest_tamper_fails_closed() -> None:
    opening = _opening_bundle()
    assert opening.intent is not None
    tampered_intent = replace(opening.intent, limit_price=60001.0)
    with pytest.raises(OMSContractError, match="proof_intent_digest_mismatch"):
        SharedPlatformV3OMS().build_order_submission_bundle(
            signal=opening.signal,
            target_position=opening.target_position,
            risk_assessment=opening.risk_assessment,
            portfolio_decision=opening.portfolio_decision,
            position_before=opening.position_before,
            position_after=opening.position_after,
            action=opening.action,
            risk_effect=opening.risk_effect,
            proof_identity=opening.proof_identity,
            price="60001",
            quantity=opening.quantity,
            venue_facts=opening.venue_facts,
            cost_facts=opening.cost_facts,
            intent=tampered_intent,
            protection=opening.protection,
            guardian_health=opening.guardian_health,
        )


def test_opening_bundle_requires_t2_t3_and_attached_protection() -> None:
    bundle = _opening_bundle()
    assert bundle.to_dict()["execution_permission"] is False
    assert bundle.to_dict()["order_allowed"] is False
    assert bundle.digest == _opening_bundle().digest
    assert bundle.proof_identity.digest

    with pytest.raises(OMSContractError, match="opening_attached_protection_required"):
        SharedPlatformV3OMS().build_order_submission_bundle(
            signal=bundle.signal,
            target_position=bundle.target_position,
            risk_assessment=bundle.risk_assessment,
            portfolio_decision=bundle.portfolio_decision,
            position_before=0.0,
            position_after=0.01,
            action=RuntimeAction.SUBMIT_NEW_ORDER,
            risk_effect=RuntimeRiskEffect.INCREASE_ABS_EXPOSURE,
            proof_identity=bundle.proof_identity,
            price="60000",
            quantity="0.01",
            venue_facts={"instrument_id": "BTC-USDT-SWAP", "margin_mode": "isolated", "position_side": "long"},
            cost_facts={"fee_bps": "5"},
            protection=None,
            guardian_health={"passed": True, "healthy": True},
        )


def test_guardian_latch_blocks_opening_but_not_risk_reducing_bundle() -> None:
    opening = _opening_bundle()
    with pytest.raises(OMSContractError, match="guardian_latch_blocked"):
        SharedPlatformV3OMS().build_order_submission_bundle(
            signal=opening.signal,
            target_position=opening.target_position,
            risk_assessment=opening.risk_assessment,
            portfolio_decision=opening.portfolio_decision,
            position_before=opening.position_before,
            position_after=opening.position_after,
            action=opening.action,
            risk_effect=opening.risk_effect,
            proof_identity=opening.proof_identity,
            price=opening.price,
            quantity=opening.quantity,
            venue_facts=opening.venue_facts,
            cost_facts=opening.cost_facts,
            intent=opening.intent,
            protection=opening.protection,
            guardian_health=opening.guardian_health,
            guardian_latch={"tripped": True},
        )

    signal = _signal()
    target = _target(0.005, allowed=False)
    assessment = _assessment(
        before=0.01,
        after=0.005,
        approved=False,
        requires_reduction=True,
        effect=ActionRiskEffect.DECREASE_ABS_EXPOSURE,
        blockers=("guardian_latch",),
    )
    plan = RiskReductionPlan(
        symbol=target.symbol,
        strategy_id=target.strategy_id,
        decision_time_utc=NOW,
        source_forecast_id=signal.signal_id,
        source_target_position_id=target.target_position_id,
        current_quantity=0.01,
        target_quantity=0.005,
        reduction_quantity=0.005,
        max_safe_quantity=0.005,
        reason_codes=("guardian_latch",),
    )
    decision = BTCPortfolioDecision(
        target_position=target,
        risk_assessment=assessment,
        reduction_plan=plan,
        decision_time_utc=NOW,
        source="t5_contract",
        reason_codes=("guardian_latch",),
        order_generation_allowed=False,
    )
    intent = OrderIntent(
        timestamp_utc=NOW,
        strategy_id=signal.strategy_id,
        symbol=signal.symbol,
        side=OrderSide.SELL,
        quantity=0.005,
        order_type=OrderType.LIMIT,
        limit_price=60000.0,
        time_in_force=TimeInForce.IOC,
        signal_id=signal.signal_id,
        target_position_id=target.target_position_id,
        client_order_id="btcDPt50002",
        order_intent_id="intent-t5-guardian-reduce",
    )
    reduced = SharedPlatformV3OMS().build_order_submission_bundle(
        signal=signal,
        target_position=target,
        risk_assessment=assessment,
        portfolio_decision=decision,
        position_before=0.01,
        position_after=0.005,
        action=RuntimeAction.REDUCE_ONLY,
        risk_effect=RuntimeRiskEffect.DECREASE_ABS_EXPOSURE,
        proof_identity=_proof(intent),
        price="60000",
        quantity="0.005",
        venue_facts={"instrument_id": "BTC-USDT-SWAP", "margin_mode": "isolated", "position_side": "long"},
        cost_facts={"fee_bps": "5"},
        intent=intent,
        guardian_latch={"tripped": True},
    )
    assert reduced.position_after == 0.005


def test_signal_reduction_plan_binds_exact_signal_and_target_identity() -> None:
    bundle = _signal_reduction_bundle()
    assert bundle.portfolio_decision.reduction_plan is not None
    assert bundle.portfolio_decision.reduction_plan.source_kind == "signal"
    assert bundle.portfolio_decision.reduction_plan.source_signal_id == bundle.signal.signal_id
    assert bundle.portfolio_decision.reduction_plan.source_forecast_id == ""


@pytest.mark.parametrize(
    ("plan_signal_id", "target_signal_id", "expected"),
    [
        ("sig_tampered", "sig_t5", "reduction_signal_source_mismatch"),
        ("sig_t5", "sig_tampered", "reduction_signal_source_mismatch"),
    ],
)
def test_signal_reduction_source_tampering_fails_closed(
    plan_signal_id: str,
    target_signal_id: str,
    expected: str,
) -> None:
    with pytest.raises(OMSContractError, match=expected):
        _signal_reduction_bundle(
            plan_signal_id=plan_signal_id,
            target_source_signal_id=target_signal_id,
        )


def test_conflicting_target_forecast_identity_fields_fail_closed_in_oms() -> None:
    with pytest.raises(OMSContractError, match="reduction_forecast_source_conflict"):
        _signal_reduction_bundle(
            target_forecast_id="fcst_one",
            target_declared_forecast_id="fcst_two",
        )


def test_t2_t3_target_and_proof_mismatches_fail_closed() -> None:
    bundle = _opening_bundle()
    wrong_target = TargetPosition(
        timestamp_utc=NOW,
        strategy_id="t5_strategy",
        symbol="BTC-USDT-SWAP",
        target_weight=0.02,
        target_quantity=0.02,
        signal_id="sig_t5",
        target_position_id="target-other",
    )
    with pytest.raises(OMSContractError, match="t3_target_identity_mismatch"):
        SharedPlatformV3OMS().build_order_submission_bundle(
            signal=bundle.signal,
            target_position=wrong_target,
            risk_assessment=bundle.risk_assessment,
            portfolio_decision=bundle.portfolio_decision,
            position_before=0.0,
            position_after=0.01,
            action=RuntimeAction.SUBMIT_NEW_ORDER,
            risk_effect=RuntimeRiskEffect.INCREASE_ABS_EXPOSURE,
            proof_identity=bundle.proof_identity,
            price="60000",
            quantity="0.01",
            venue_facts={},
            cost_facts={},
            protection=bundle.protection,
        )
    with pytest.raises(OMSContractError, match="proof_source_head_missing"):
        OMSProofIdentity(
            source_head="",
            account_identity="account",
            session_id="session",
            key_namespace="key",
            client_order_namespace="namespace",
            epoch=1,
            intent_digest="intent",
            evidence_digest="evidence",
        )


def test_reduction_requires_signed_plan_and_never_crosses_zero() -> None:
    oms = SharedPlatformV3OMS()
    signal = _signal()
    target = _target(0.005, allowed=False)
    assessment = _assessment(
        before=0.01,
        after=0.005,
        approved=False,
        requires_reduction=True,
        effect=ActionRiskEffect.DECREASE_ABS_EXPOSURE,
        blockers=("daily_loss_limit_breach",),
    )
    plan = RiskReductionPlan(
        symbol=target.symbol,
        strategy_id=target.strategy_id,
        decision_time_utc=NOW,
        source_forecast_id=signal.signal_id,
        source_target_position_id=target.target_position_id,
        current_quantity=0.01,
        target_quantity=0.005,
        reduction_quantity=0.005,
        max_safe_quantity=0.005,
        reason_codes=("daily_loss_limit_breach",),
    )
    decision = BTCPortfolioDecision(
        target_position=target,
        risk_assessment=assessment,
        reduction_plan=plan,
        decision_time_utc=NOW,
        source="t5_contract",
        reason_codes=("daily_loss_limit_breach",),
        order_generation_allowed=False,
    )
    intent = OrderIntent(
        timestamp_utc=NOW,
        strategy_id=signal.strategy_id,
        symbol=signal.symbol,
        side=OrderSide.SELL,
        quantity=0.005,
        order_type=OrderType.LIMIT,
        limit_price=60000.0,
        time_in_force=TimeInForce.IOC,
        signal_id=signal.signal_id,
        target_position_id=target.target_position_id,
        client_order_id="btcDPt50002",
        order_intent_id="intent-t5-reduce",
    )
    bundle = oms.build_order_submission_bundle(
        signal=signal,
        target_position=target,
        risk_assessment=assessment,
        portfolio_decision=decision,
        position_before=0.01,
        position_after=0.005,
        action=RuntimeAction.REDUCE_ONLY,
        risk_effect=RuntimeRiskEffect.DECREASE_ABS_EXPOSURE,
        proof_identity=_proof(intent),
        price="60000",
        quantity="0.005",
        venue_facts={"instrument_id": "BTC-USDT-SWAP", "margin_mode": "isolated", "position_side": "long"},
        cost_facts={"fee_bps": "5"},
        intent=intent,
    )
    assert bundle.to_risk_decision(  # dispatcher input is derived, not caller-approved
        bundle.intent
    ).approved is True

    with pytest.raises(OMSContractError, match="reduction_cross_zero"):
        oms.build_order_submission_bundle(
            signal=signal,
            target_position=target,
            risk_assessment=assessment,
            portfolio_decision=decision,
            position_before=0.01,
            position_after=-0.005,
            action=RuntimeAction.REDUCE_ONLY,
            risk_effect=RuntimeRiskEffect.DECREASE_ABS_EXPOSURE,
            proof_identity=_proof(intent),
            price="60000",
            quantity="0.005",
            venue_facts={"instrument_id": "BTC-USDT-SWAP", "margin_mode": "isolated", "position_side": "long"},
            cost_facts={"fee_bps": "5"},
            intent=intent,
        )


def _intent_for(bundle: OMSOrderSubmissionBundle):
    assert bundle.intent is not None
    return bundle.intent


def test_protection_contract_is_mark_market_exit_and_immutable() -> None:
    protection = _opening_bundle().protection
    assert isinstance(protection, OMSAttachedProtection)
    assert protection["tpOrdPx"] == protection["slOrdPx"] == "-1"
    assert protection["tpTriggerPxType"] == protection["slTriggerPxType"] == "mark"
    assert protection["attachAlgoClOrdId"] == "btcDPt50001A"
    with pytest.raises(TypeError):
        protection.payload["tpOrdPx"] = "1"  # type: ignore[index]
    with pytest.raises(OMSContractError, match="protection_removal_forbidden"):
        SharedPlatformV3OMS().remove_attached_protection(protection)


def test_protection_policy_digest_and_trigger_are_strict() -> None:
    oms = SharedPlatformV3OMS()
    with pytest.raises(OMSContractError, match="protection_policy_digest_mismatch"):
        oms.build_attached_protection(
            policy={
                "policy_id": "t5-policy",
                "version": "1",
                "sl_distance_bps": "100",
                "tp_distance_bps": "200",
                "trigger": "mark",
                "policy_sha256": "0" * 64,
            },
            entry_price="60000",
            tick_size="0.1",
            position_side="long",
            client_order_id="btcDPt50004",
            contracts="0.01",
        )
    with pytest.raises(OMSContractError, match="protection_policy_invalid"):
        oms.build_attached_protection(
            policy={
                "policy_id": "t5-policy",
                "version": "1",
                "sl_distance_bps": "100",
                "tp_distance_bps": "200",
                "trigger": "last",
            },
            entry_price="60000",
            tick_size="0.1",
            position_side="long",
            client_order_id="btcDPt50004",
            contracts="0.01",
        )


def test_t5_module_has_no_transport_or_runtime_reverse_dependency() -> None:
    tree = ast.parse(inspect.getsource(__import__("quant_crypto.oms.shared_platform_v3", fromlist=["x"])))
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.add(node.module or "")
    forbidden = {
        "os",
        "pathlib",
        "socket",
        "requests",
        "httpx",
        "quant_crypto.oms.okx_demo",
        "quant_crypto.application",
        "quant_crypto.runtime",
        "backend",
    }
    assert not any(item == value or item.startswith(value + ".") for item in imports for value in forbidden)


def test_runtime_facade_protection_seam_delegates_to_pure_oms(monkeypatch: pytest.MonkeyPatch) -> None:
    canonical = {
        "policy_id": "t5-policy",
        "version": "1",
        "sl_distance_bps": "100",
        "tp_distance_bps": "200",
        "trigger": "mark",
    }
    policy = ServerSideProtectionPolicy.from_mapping(
        {
            **canonical,
            "policy_sha256": hashlib.sha256(
                json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
        }
    )
    controller = object.__new__(OkxDemoPaperRuntimeController)
    controller._protection_policy = policy
    controller._shared_platform_v3_oms = SharedPlatformV3OMS()
    called: list[dict[str, Any]] = []
    original = SharedPlatformV3OMS.build_attached_protection

    def spy(self: SharedPlatformV3OMS, **kwargs: Any) -> OMSAttachedProtection:
        called.append(dict(kwargs))
        return original(self, **kwargs)

    monkeypatch.setattr(SharedPlatformV3OMS, "build_attached_protection", spy)
    payload = controller._build_attached_protection(
        entry_price=60000,
        tick_size=0.1,
        position_side="long",
        client_order_id="btcDPt50003",
        contracts=0.01,
    )
    assert payload["attachAlgoClOrdId"] == "btcDPt50003A"
    assert called and called[0]["client_order_id"] == "btcDPt50003"
