from __future__ import annotations

from copy import copy, deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json

import pytest

from quant_shared.runtime.models import RuntimeSnapshot, RuntimeState, TradingMode
from quant_shared.runtime.permissions import (
    PermissionEvaluator,
    RuntimeAction,
    RuntimeAuthoritativeRiskResult,
    RuntimeRiskEffect,
    RuntimeRiskEvidenceError,
    RuntimeRiskEvidenceAuthority,
    RuntimeRiskEvidenceProducer,
)


HEAD = "a" * 40
ACCOUNT = "b" * 64
SESSION = "session-v3"
EPOCH = 7
HASHES = {
    "broker_snapshot_hash": "1" * 64,
    "ledger_snapshot_hash": "2" * 64,
    "strategy_snapshot_hash": "3" * 64,
    "risk_snapshot_hash": "4" * 64,
}


def _snapshot(*, kill: bool = False, risk_valid: bool = True) -> RuntimeSnapshot:
    return RuntimeSnapshot(
        state=RuntimeState.READY,
        trading_mode=TradingMode.NORMAL,
        block_new_orders=False,
        connected=True,
        account_verified=True,
        reconciliation_status="pass",
        broker_truth_fresh=True,
        kill_switch_tripped=kill,
        risk_state_valid=risk_valid,
    )


def _intent(quantity: float = 0.01, *, side: str = "SELL", **overrides: object) -> dict[str, object]:
    intent: dict[str, object] = {
        "order_intent_id": "intent-v3-001",
        "client_order_id": "client-v3-001",
        "symbol": "BTC-USDT-SWAP",
        "side": side,
        "quantity": quantity,
        "order_type": "market",
        "strategy_id": "fixture",
        "run_id": "run-v3",
        "signal_id": "signal-v3",
        "target_position_id": "position-v3",
    }
    intent.update(overrides)
    return intent


def _base_evidence(intent: dict[str, object]) -> dict[str, object]:
    return {
        "order_intent": intent,
        "risk_decision": {
            "approved": True,
            "reason": "trusted-risk-v3",
            "order_intent_id": intent["order_intent_id"],
        },
        "broker_truth": {
            "fresh": True,
            "valid": True,
            "account_verified": True,
            "authoritative_account_verified": True,
            "account_verification_source": "fixture-authority",
            "venue": "okx",
        },
        "ledger_freshness": {"fresh": True, "reconciled": True},
        "endpoint_capability": {
            "submit_new_order": True,
            "cancel_order": True,
            "replace_order": True,
            "reduce_only": True,
            "attach_protection": True,
            "dead_man": True,
            "transport_enabled": True,
            "private_endpoint_allowed": True,
            "order_endpoint_allowed": True,
        },
        "execution_identity": {
            "mode": "paper",
            "state_directory": "runtime/paper-v3",
            "account_identity": ACCOUNT,
            "key_namespace": "quant-system.paper.fixture",
            "client_order_namespace": "btc-paper-fixture",
            "session_id": SESSION,
            "epoch": EPOCH,
            "transport_enabled": True,
            "auto_start": False,
            "auto_scale": False,
        },
        "expected_mode": "paper",
        "current_head": HEAD,
        "session_id": SESSION,
        "epoch": EPOCH,
        **HASHES,
    }


def _producer() -> tuple[RuntimeRiskEvidenceProducer, object]:
    authority = RuntimeRiskEvidenceAuthority(name="t1-test")
    producer, verifier = authority.bind()
    return producer, verifier


def _proof(
    intent: dict[str, object],
    *,
    action: RuntimeAction | str,
    effect: RuntimeRiskEffect | str,
    before: float = 0.01,
    after: float = 0.0,
    quantity: float = 0.01,
    max_quantity: float = 0.01,
    max_abs_position: float = 0.01,
    max_notional: float = 10.0,
    leverage: float = 1.0,
    max_leverage: float = 1.0,
    producer: RuntimeRiskEvidenceProducer | None = None,
    **overrides: object,
):
    if producer is None:
        producer, _ = _producer()
    issued_at = overrides.pop("issued_at", None)
    ttl_seconds = overrides.pop("ttl_seconds", 5.0)
    evidence_id = overrides.pop("evidence_id", f"evidence-{action}-{effect}")
    values = dict(HASHES)
    values.update(overrides)
    result = RuntimeAuthoritativeRiskResult.from_order_intent(
        intent,
        approved=True,
        actual_notional=0.01,
        venue="okx",
        liquidation_safe=True,
        exposure=abs(before) if before is not None else 0.0,
        action=action,
        risk_effect=effect,
        position_before=before,
        position_after=after,
        quantity=quantity,
        max_quantity=max_quantity,
        max_abs_position=max_abs_position,
        max_notional=max_notional,
        leverage=leverage,
        max_leverage=max_leverage,
        **values,
    )
    return producer.issue_from_authoritative(
        order_intent=intent,
        authoritative_result=result,
        source_head=HEAD,
        account_identity=ACCOUNT,
        session_id=SESSION,
        key_namespace="quant-system.paper.fixture",
        client_order_namespace="btc-paper-fixture",
        epoch=EPOCH,
        ttl_seconds=ttl_seconds,
        issued_at=issued_at,
        evidence_id=str(evidence_id),
    )


def test_failure_first_probe_semantics_are_closed() -> None:
    assert PermissionEvaluator(_snapshot(risk_valid=False)).can_submit_new_order() is False
    evaluator = PermissionEvaluator(_snapshot(kill=True))
    # Legacy booleans remain the final fail-closed gate for US paper callers.
    assert evaluator.can_reduce_position() is False
    assert evaluator.can_cancel_order() is False
    # Explicitly named capabilities are not execution authorization; strict
    # evaluate_action still needs a paired signed proof.
    assert evaluator.can_reduce_transport() is True
    assert evaluator.can_cancel_transport() is True


def test_kill_final_boundary_requires_proof_even_when_coarse_transport_allows() -> None:
    intent = _intent()
    evidence = _base_evidence(intent)
    evidence["lifecycle"] = {"client_order_id": intent["client_order_id"], "status": "prepared"}
    decision = PermissionEvaluator(_snapshot(kill=True)).evaluate_action(RuntimeAction.REDUCE_ONLY, **evidence)
    assert decision.allowed is False
    assert "kill_exception_proof_required" in decision.reasons


@pytest.mark.parametrize(
    ("action", "effect", "before", "after"),
    [
        (RuntimeAction.REDUCE_ONLY, RuntimeRiskEffect.DECREASE_ABS_EXPOSURE, 0.01, 0.0),
        (RuntimeAction.CANCEL_ORDER, RuntimeRiskEffect.NO_POSITION_EFFECT, 0.01, 0.01),
        (RuntimeAction.ATTACH_PROTECTION, RuntimeRiskEffect.ADD_PROTECTION, 0.01, 0.01),
    ],
)
def test_kill_allows_only_proven_safe_actions(action, effect, before, after) -> None:
    intent = _intent()
    producer, verifier = _producer()
    proof = _proof(intent, action=action, effect=effect, before=before, after=after, producer=producer)
    evidence = _base_evidence(intent)
    evidence.update(
        risk_evidence=proof,
        lifecycle={"client_order_id": intent["client_order_id"], "status": "prepared"},
    )
    decision = PermissionEvaluator(_snapshot(kill=True), risk_verifier=verifier).evaluate_action(action, **evidence)
    assert decision.allowed is True, decision.reasons


def test_kill_allows_cancel_of_reduce_order_only_after_signed_flat_proof() -> None:
    intent = _intent()
    producer, verifier = _producer()
    proof = _proof(
        intent,
        action=RuntimeAction.CANCEL_ORDER,
        effect=RuntimeRiskEffect.DECREASE_ABS_EXPOSURE,
        before=0.0,
        after=0.0,
        producer=producer,
    )
    evidence = _base_evidence(intent)
    evidence.update(risk_evidence=proof, lifecycle={"client_order_id": intent["client_order_id"], "status": "prepared"})
    decision = PermissionEvaluator(_snapshot(kill=True), risk_verifier=verifier).evaluate_action(
        RuntimeAction.CANCEL_ORDER, **evidence
    )
    assert decision.allowed is True, decision.reasons


def test_kill_allows_protection_removal_only_with_atomic_replacement_proof() -> None:
    intent = _intent()
    producer, verifier = _producer()
    proof = _proof(
        intent,
        action=RuntimeAction.CANCEL_ORDER,
        effect=RuntimeRiskEffect.REMOVE_PROTECTION,
        before=0.01,
        after=0.01,
        producer=producer,
        atomic_protection_replacement=True,
    )
    evidence = _base_evidence(intent)
    evidence.update(risk_evidence=proof, lifecycle={"client_order_id": intent["client_order_id"], "status": "prepared"})
    decision = PermissionEvaluator(_snapshot(kill=True), risk_verifier=verifier).evaluate_action(
        RuntimeAction.CANCEL_ORDER, **evidence
    )
    assert decision.allowed is True, decision.reasons


@pytest.mark.parametrize("action", [RuntimeAction.SUBMIT_NEW_ORDER, RuntimeAction.REPLACE_ORDER])
def test_kill_never_allows_new_risk_or_replace_even_with_proof(action) -> None:
    intent = _intent()
    producer, verifier = _producer()
    proof = _proof(intent, action=action, effect=RuntimeRiskEffect.NO_POSITION_EFFECT, before=0.01, after=0.01, producer=producer)
    evidence = _base_evidence(intent)
    evidence.update(risk_evidence=proof, lifecycle={"client_order_id": intent["client_order_id"], "status": "prepared"})
    decision = PermissionEvaluator(_snapshot(kill=True), risk_verifier=verifier).evaluate_action(action, **evidence)
    assert decision.allowed is False
    assert "kill_switch_blocks_new_risk" in decision.reasons or "kill_switch_blocks_replace" in decision.reasons


@pytest.mark.parametrize(
    ("action", "effect", "before", "after", "expected"),
    [
        (RuntimeAction.CANCEL_ORDER, RuntimeRiskEffect.REMOVE_PROTECTION, 0.01, 0.01, "kill_exception_protection_removal_not_safe"),
        (RuntimeAction.ATTACH_PROTECTION, RuntimeRiskEffect.REMOVE_PROTECTION, 0.01, 0.01, "kill_exception_effect_mismatch"),
        (RuntimeAction.REDUCE_ONLY, RuntimeRiskEffect.UNKNOWN, 0.01, 0.0, "kill_exception_effect_unknown"),
        (RuntimeAction.REDUCE_ONLY, RuntimeRiskEffect.DECREASE_ABS_EXPOSURE, None, 0.0, "kill_exception_position_unknown"),
        (RuntimeAction.REDUCE_ONLY, RuntimeRiskEffect.DECREASE_ABS_EXPOSURE, 0.01, 0.02, "kill_exception_position_increase"),
        (RuntimeAction.REDUCE_ONLY, RuntimeRiskEffect.DECREASE_ABS_EXPOSURE, 0.01, -0.01, "kill_exception_position_cross_zero"),
    ],
)
def test_kill_rejects_unsafe_effects_and_position_transitions(action, effect, before, after, expected) -> None:
    intent = _intent()
    producer, verifier = _producer()
    proof = _proof(intent, action=action, effect=effect, before=before, after=after, producer=producer)
    evidence = _base_evidence(intent)
    evidence.update(risk_evidence=proof, lifecycle={"client_order_id": intent["client_order_id"], "status": "prepared"})
    decision = PermissionEvaluator(_snapshot(kill=True), risk_verifier=verifier).evaluate_action(action, **evidence)
    assert decision.allowed is False
    assert expected in decision.reasons


def test_kill_rejects_forged_mappings_action_mismatch_and_identity_mismatch() -> None:
    intent = _intent()
    producer, verifier = _producer()
    proof = _proof(intent, action=RuntimeAction.REDUCE_ONLY, effect=RuntimeRiskEffect.DECREASE_ABS_EXPOSURE, producer=producer)
    evidence = _base_evidence(intent)
    evidence.update(risk_evidence=proof, lifecycle={"client_order_id": intent["client_order_id"], "status": "prepared"})
    forged = dict(proof.to_dict())
    forged["action"] = RuntimeAction.CANCEL_ORDER.value
    mapped = PermissionEvaluator(_snapshot(kill=True), risk_verifier=verifier).evaluate_action(RuntimeAction.REDUCE_ONLY, **{**evidence, "risk_evidence": forged})
    assert mapped.allowed is False
    assert "risk_evidence_untrusted_issuer" in mapped.reasons

    mismatch = PermissionEvaluator(_snapshot(kill=True), risk_verifier=verifier).evaluate_action(
        RuntimeAction.CANCEL_ORDER, **evidence
    )
    assert mismatch.allowed is False
    assert "kill_exception_action_mismatch" in mismatch.reasons

    for field, value, expected in (
        ("current_head", "c" * 40, "risk_evidence_source_head_mismatch"),
        ("session_id", "other-session", "risk_evidence_session_id_mismatch"),
        ("epoch", EPOCH + 1, "risk_evidence_epoch_mismatch"),
        ("broker_snapshot_hash", "9" * 64, "kill_exception_snapshot_hash_mismatch"),
    ):
        changed = {**evidence, field: value}
        result = PermissionEvaluator(_snapshot(kill=True), risk_verifier=verifier).evaluate_action(
            RuntimeAction.REDUCE_ONLY, **changed
        )
        assert result.allowed is False
        assert expected in result.reasons


def test_kill_rejects_expired_proof_and_risk_invalid_blocks_opening() -> None:
    intent = _intent()
    producer, verifier = _producer()
    expired = _proof(
        intent,
        action=RuntimeAction.REDUCE_ONLY,
        effect=RuntimeRiskEffect.DECREASE_ABS_EXPOSURE,
        producer=producer,
        issued_at=datetime.now(timezone.utc) - timedelta(seconds=2),
        ttl_seconds=0.1,
    )
    evidence = _base_evidence(intent)
    evidence.update(risk_evidence=expired, lifecycle={"client_order_id": intent["client_order_id"], "status": "prepared"})
    result = PermissionEvaluator(_snapshot(kill=True), risk_verifier=verifier).evaluate_action(RuntimeAction.REDUCE_ONLY, **evidence)
    assert result.allowed is False
    assert "risk_evidence_proof_invalid" in result.reasons

    open_evidence = _base_evidence(intent)
    open_evidence["risk_evidence"] = _proof(intent, action=RuntimeAction.SUBMIT_NEW_ORDER, effect=RuntimeRiskEffect.INCREASE_ABS_EXPOSURE, producer=producer)
    result = PermissionEvaluator(_snapshot(risk_valid=False), risk_verifier=verifier).evaluate_action(
        RuntimeAction.SUBMIT_NEW_ORDER, **open_evidence
    )
    assert result.allowed is False
    assert "risk_state_invalid" in result.reasons


def test_sealed_proof_rejects_field_mutation_and_copy() -> None:
    intent = _intent()
    producer, verifier = _producer()
    proof = _proof(intent, action=RuntimeAction.REDUCE_ONLY, effect=RuntimeRiskEffect.DECREASE_ABS_EXPOSURE, producer=producer)
    for field, value in (
        ("_issuer_capability", object()),
        ("_action", RuntimeAction.CANCEL_ORDER.value),
        ("_risk_effect", RuntimeRiskEffect.UNKNOWN.value),
        ("_position_before", 0.02),
        ("_position_after", 0.01),
        ("_broker_snapshot_hash", "9" * 64),
        ("_max_quantity", 1.0),
        ("_signature", "0" * 64),
    ):
        with pytest.raises(RuntimeRiskEvidenceError, match="risk_evidence_sealed"):
            setattr(proof, field, value)
    with pytest.raises(RuntimeRiskEvidenceError, match="risk_evidence_copy_forbidden"):
        copy(proof)
    with pytest.raises(RuntimeRiskEvidenceError, match="risk_evidence_copy_forbidden"):
        deepcopy(proof)

    # Even a low-level mutation followed by public signature recomputation is
    # rejected by the issuer capability's sealed record.
    tampered = _proof(intent, action=RuntimeAction.REDUCE_ONLY, effect=RuntimeRiskEffect.DECREASE_ABS_EXPOSURE, producer=producer)
    object.__setattr__(tampered, "_action", RuntimeAction.CANCEL_ORDER.value)
    tampered_signature = hashlib.sha256(
        json.dumps(tampered._signed_payload(), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    object.__setattr__(tampered, "_signature", tampered_signature)
    assert verifier.verify(
        tampered,
        order_intent=intent,
        source_head=HEAD,
        account_identity=ACCOUNT,
        session_id=SESSION,
        key_namespace="quant-system.paper.fixture",
        client_order_namespace="btc-paper-fixture",
        epoch=EPOCH,
    ) is False


@pytest.mark.parametrize(
    "mutation",
    [
        {"reduce_only": True},
        {"close_position": True},
        {"post_only": True},
        {"position_side": "short"},
        {"order_role": "protection"},
        {"trigger_type": "market"},
        {"trigger_price": 100.0},
        {"stop_price": 99.0},
        {"trigger_direction": "down"},
        {"parent_order_id": "parent-1"},
        {"protection_order_id": "protect-1"},
        {"algo_id": "algo-1"},
        {"oco_id": "oco-1"},
        {"metadata": {"reduce_only": True}},
        {"metadata": {"posSide": "short"}},
        {"metadata": {"algoClOrdId": "algo-2"}},
    ],
)
def test_intent_digest_binds_execution_semantics(mutation: dict[str, object]) -> None:
    intent = _intent()
    producer, verifier = _producer()
    proof = _proof(intent, action=RuntimeAction.REDUCE_ONLY, effect=RuntimeRiskEffect.DECREASE_ABS_EXPOSURE, producer=producer)
    mutated = dict(intent)
    if "metadata" in mutation:
        mutated["metadata"] = mutation["metadata"]
    else:
        mutated.update(mutation)
    assert verifier.verify(
        proof,
        order_intent=mutated,
        source_head=HEAD,
        account_identity=ACCOUNT,
        session_id=SESSION,
        key_namespace="quant-system.paper.fixture",
        client_order_namespace="btc-paper-fixture",
        epoch=EPOCH,
    ) is False


@pytest.mark.parametrize(
    ("side", "before", "after", "expected_allowed"),
    [
        ("SELL", 0.01, 0.0, True),
        ("BUY", -0.01, 0.0, True),
        ("BUY", 0.01, 0.0, False),
        ("SELL", 0.01, -0.01, False),
        ("HOLD", 0.01, 0.0, False),
    ],
)
def test_reduce_proof_requires_side_quantity_position_transition(side, before, after, expected_allowed) -> None:
    intent = _intent(side=side, order_role="reduction", reduce_only=True)
    producer, verifier = _producer()
    proof = _proof(
        intent,
        action=RuntimeAction.REDUCE_ONLY,
        effect=RuntimeRiskEffect.DECREASE_ABS_EXPOSURE,
        before=before,
        after=after,
        producer=producer,
    )
    evidence = _base_evidence(intent)
    evidence.update(risk_evidence=proof, lifecycle={"client_order_id": intent["client_order_id"], "status": "prepared"})
    decision = PermissionEvaluator(_snapshot(kill=True), risk_verifier=verifier).evaluate_action(
        RuntimeAction.REDUCE_ONLY, **evidence
    )
    assert decision.allowed is expected_allowed, decision.reasons


def test_reduce_proof_rejects_quantity_mismatch() -> None:
    intent = _intent(side="SELL", order_role="reduction", reduce_only=True)
    producer, verifier = _producer()
    proof = _proof(
        intent,
        action=RuntimeAction.REDUCE_ONLY,
        effect=RuntimeRiskEffect.DECREASE_ABS_EXPOSURE,
        before=0.01,
        after=0.0,
        quantity=0.005,
        max_quantity=0.01,
        producer=producer,
    )
    evidence = _base_evidence(intent)
    evidence.update(risk_evidence=proof, lifecycle={"client_order_id": intent["client_order_id"], "status": "prepared"})
    decision = PermissionEvaluator(_snapshot(kill=True), risk_verifier=verifier).evaluate_action(
        RuntimeAction.REDUCE_ONLY, **evidence
    )
    assert decision.allowed is False
    assert "kill_exception_quantity_intent_mismatch" in decision.reasons
