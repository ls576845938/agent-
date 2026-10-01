from __future__ import annotations

import importlib
from datetime import datetime, timedelta, timezone

import pytest

from quant_crypto.exchange.runtime import (
    BTCExchangeRuntimeSnapshot,
    BTCExchangeRuntimeStatus,
    BTCRestStatus,
    BTCStreamStatus,
)
from quant_crypto.runtime import (
    BTCBrokerTruth,
    BTCClientOrderLifecycleStore,
    BTCEndpointCapability,
    BTCExecutionBlocked,
    BTCExecutionBoundary,
    BTCExecutionIdentity,
    BTCExecutionMode,
    BTCDispatchAuthorization,
    BTCDispatchAuthorizer,
    BTCLedgerFreshness,
    BTCOrderLifecycleStatus,
    project_btc_runtime_snapshot,
)
from quant_crypto.trading_contracts import OrderIntent, OrderSide, RiskDecision
from quant_shared.runtime import (
    PermissionEvaluator,
    RuntimeAction,
    RuntimeRiskEvidence,
    RuntimeSnapshot,
    RuntimeState,
    TradingMode,
)
from quant_shared.runtime.permissions import (
    RuntimeAuthoritativeRiskResult,
    RuntimeRiskEvidenceAuthority,
    RuntimeRiskEvidenceError,
    RuntimeRiskEvidenceProducer,
)


TS = datetime(2026, 8, 8, 1, 0, tzinfo=timezone.utc)
CURRENT_HEAD = "a" * 40
SESSION_ID = "btc-paper-session-001"
EPOCH = 7
_CANONICAL_AUTHORITY = RuntimeRiskEvidenceAuthority(name="canonical-fixture")
_CANONICAL_PRODUCER, _CANONICAL_VERIFIER = _CANONICAL_AUTHORITY.bind()


def _evaluator(snapshot: RuntimeSnapshot) -> PermissionEvaluator:
    return PermissionEvaluator(snapshot, risk_verifier=_CANONICAL_VERIFIER)


def _exchange(**overrides: object) -> BTCExchangeRuntimeSnapshot:
    values: dict[str, object] = {
        "venue": "okx",
        "instrument_id": "BTC-USDT-SWAP",
        "observed_at_utc": TS,
        "exchange_status": BTCExchangeRuntimeStatus.OK,
        "public_ws_status": BTCStreamStatus.CONNECTED,
        "private_ws_status": BTCStreamStatus.CONNECTED,
        "rest_status": BTCRestStatus.OK,
        "server_time_offset_ms": 0,
        "rate_limit_budget_remaining": 100,
        "order_rate_budget_remaining": 100,
        "last_market_data_time_utc": TS - timedelta(seconds=1),
        "last_private_event_time_utc": TS - timedelta(seconds=1),
        "last_reconciliation_time_utc": TS - timedelta(seconds=1),
        "metadata_version": "okx-rules-v1",
        "mode": "paper",
    }
    values.update(overrides)
    return BTCExchangeRuntimeSnapshot(**values)


def _identity(root, *, mode: BTCExecutionMode | str = BTCExecutionMode.PAPER, transport_enabled: bool = True) -> BTCExecutionIdentity:
    mode_value = mode.value if isinstance(mode, BTCExecutionMode) else str(mode)
    return BTCExecutionIdentity(
        mode=mode_value,
        state_directory=str(root),
        account_identity="a" * 64,
        key_namespace=(f"quant-system.okx-{mode_value}.fixture" if mode_value in {"demo", "live"} else f"quant-system.{mode_value}.fixture"),
        client_order_namespace=f"btc-{mode_value}-fixture",
        account_verified=True,
        transport_enabled=transport_enabled,
        live_execution_allowed=False,
        session_id=SESSION_ID if mode_value == "paper" else f"btc-{mode_value}-session-001",
        epoch=EPOCH,
        source_head=CURRENT_HEAD,
    )


def _evidence(mode: str = "paper") -> tuple[BTCBrokerTruth, BTCLedgerFreshness, BTCEndpointCapability]:
    return (
        BTCBrokerTruth(
            fresh=True,
            valid=True,
            account_verified=True,
            authoritative_account_verified=True,
            account_verification_source="fixture-authoritative-account-observation",
            venue="okx",
            observed_at_utc=TS,
            source_head=CURRENT_HEAD,
            session_id=SESSION_ID,
            epoch=EPOCH,
        ),
        BTCLedgerFreshness(fresh=True, reconciled=True, observed_at_utc=TS),
        BTCEndpointCapability(
            mode=mode,
            transport_enabled=True,
            submit_new_order=True,
            cancel_order=True,
            replace_order=True,
            reduce_only=True,
            attach_protection=True,
            dead_man=True,
            private_endpoint_allowed=True,
            order_endpoint_allowed=True,
        ),
    )


def _intent(*, client_order_id: str = "btc-paper-fixture-001", metadata: dict[str, object] | None = None) -> OrderIntent:
    return OrderIntent(
        timestamp_utc=TS,
        strategy_id="btc-fixture-strategy",
        symbol="BTC-USDT-SWAP",
        side=OrderSide.BUY,
        quantity=0.01,
        metadata=(metadata or {"ready": True, "risk_approved": True, "notional": 0.01}),
        client_order_id=client_order_id,
    )


def _risk(intent: OrderIntent, *, approved: bool = True) -> RiskDecision:
    return RiskDecision(
        approved=approved,
        reason="fixture-risk-approved" if approved else "fixture-risk-rejected",
        order_intent_id=intent.order_intent_id,
        checked_at=TS,
    )


def _risk_evidence(
    intent: OrderIntent,
    *,
    approved: bool = True,
    source_head: str = CURRENT_HEAD,
    producer: RuntimeRiskEvidenceProducer = _CANONICAL_PRODUCER,
    ttl_seconds: float = 5.0,
    issued_at: datetime | None = None,
) -> RuntimeRiskEvidence:
    authoritative_result = RuntimeAuthoritativeRiskResult.from_order_intent(
        intent,
        approved=approved,
        actual_notional=100.0,
        venue="okx",
        liquidation_safe=True,
        exposure=100.0,
    )
    return producer.issue_from_authoritative(
        order_intent=intent,
        authoritative_result=authoritative_result,
        source_head=source_head,
        account_identity="a" * 64,
        session_id=SESSION_ID,
        key_namespace="quant-system.paper.fixture",
        client_order_namespace="btc-paper-fixture",
        epoch=EPOCH,
        ttl_seconds=ttl_seconds,
        issued_at=issued_at,
        evidence_id=f"risk-evidence-{intent.client_order_id}",
    )


def test_btc_projection_reaches_canonical_ready_only_from_observed_evidence(tmp_path) -> None:
    identity = _identity(tmp_path / "btc-paper-state")
    broker, ledger, capability = _evidence()

    projected = project_btc_runtime_snapshot(
        _exchange(),
        identity=identity,
        broker_truth=broker,
        ledger_freshness=ledger,
        endpoint_capability=capability,
        return_result=True,
    )

    assert projected.snapshot.state is RuntimeState.READY
    assert projected.snapshot.trading_mode is TradingMode.NORMAL
    assert projected.snapshot.block_new_orders is False
    assert projected.snapshot.broker_truth_fresh is True
    assert projected.snapshot.reconciliation_passed is True
    assert projected.snapshot.blockers == ()
    assert projected.to_dict()["safety"]["network_accessed"] is False


def test_live_projection_defaults_to_no_transport_and_never_auto_starts(tmp_path) -> None:
    identity = _identity(tmp_path / "btc-live-state", mode=BTCExecutionMode.LIVE, transport_enabled=False)
    broker, ledger, capability = _evidence("live")

    projected = project_btc_runtime_snapshot(
        _exchange(mode="live"),
        identity=identity,
        broker_truth=broker,
        ledger_freshness=ledger,
        endpoint_capability=capability,
        return_result=True,
    )

    assert projected.snapshot.state is RuntimeState.OFFLINE
    assert projected.snapshot.trading_mode is TradingMode.NO_TRANSPORT
    assert projected.snapshot.block_new_orders is True
    assert "btc_live_default_no_transport" in projected.blockers
    assert projected.to_dict()["safety"]["live_allowed"] is False


@pytest.mark.parametrize("action", list(RuntimeAction))
def test_every_btc_action_uses_actual_intent_risk_truth_ledger_and_endpoint_evidence(tmp_path, action: RuntimeAction) -> None:
    identity = _identity(tmp_path / "btc-paper-state")
    broker, ledger, capability = _evidence()
    projected = project_btc_runtime_snapshot(
        _exchange(),
        identity=identity,
        broker_truth=broker,
        ledger_freshness=ledger,
        endpoint_capability=capability,
        return_result=True,
    )
    intent = _intent()
    risk = _risk(intent)
    evidence = _risk_evidence(intent)
    store = BTCClientOrderLifecycleStore(identity.state_directory, identity=identity)
    lifecycle = store.prepare(intent)
    evaluator = _evaluator(projected.snapshot)

    decision = evaluator.evaluate_action(
        action,
        order_intent=intent,
        risk_decision=risk,
        broker_truth=broker,
        ledger_freshness=ledger,
        endpoint_capability=capability,
        execution_identity=identity,
        expected_mode="paper",
        risk_evidence=evidence,
        current_head=CURRENT_HEAD,
        session_id=SESSION_ID,
        epoch=EPOCH,
        lifecycle=None if action is RuntimeAction.SUBMIT_NEW_ORDER else lifecycle,
    )

    assert decision.allowed is True, (action, decision.reasons)


def test_permission_ignores_self_reported_risk_ready_and_notional(tmp_path) -> None:
    identity = _identity(tmp_path / "btc-paper-state")
    broker, ledger, capability = _evidence()
    projected = project_btc_runtime_snapshot(
        _exchange(),
        identity=identity,
        broker_truth=broker,
        ledger_freshness=ledger,
        endpoint_capability=capability,
        return_result=True,
    )
    intent = _intent()
    rejected = _risk(intent, approved=False)
    evidence = _risk_evidence(intent)
    decision = _evaluator(projected.snapshot).evaluate_action(
        RuntimeAction.SUBMIT_NEW_ORDER,
        order_intent=intent,
        risk_decision=rejected,
        broker_truth=broker,
        ledger_freshness=ledger,
        endpoint_capability=capability,
        execution_identity=identity,
        expected_mode="paper",
        risk_evidence=evidence,
        current_head=CURRENT_HEAD,
        session_id=SESSION_ID,
        epoch=EPOCH,
    )

    assert decision.allowed is False
    assert "risk_decision_not_approved" in decision.reasons


def test_permission_blocks_stale_truth_ledger_and_missing_endpoint_capability(tmp_path) -> None:
    identity = _identity(tmp_path / "btc-paper-state")
    broker, ledger, capability = _evidence()
    projected = project_btc_runtime_snapshot(
        _exchange(),
        identity=identity,
        broker_truth=broker,
        ledger_freshness=ledger,
        endpoint_capability=capability,
        return_result=True,
    )
    intent = _intent()
    risk = _risk(intent)
    evidence = _risk_evidence(intent)

    decision = _evaluator(projected.snapshot).evaluate_action(
        RuntimeAction.SUBMIT_NEW_ORDER,
        order_intent=intent,
        risk_decision=risk,
        broker_truth=BTCBrokerTruth(fresh=False, valid=False),
        ledger_freshness=BTCLedgerFreshness(fresh=False, reconciled=False),
        endpoint_capability=BTCEndpointCapability(mode="paper", transport_enabled=False),
        execution_identity=identity,
        expected_mode="paper",
        risk_evidence=evidence,
        current_head=CURRENT_HEAD,
        session_id=SESSION_ID,
        epoch=EPOCH,
    )

    assert decision.allowed is False
    assert "broker_truth_not_fresh" in decision.reasons
    assert "ledger_not_fresh" in decision.reasons
    assert "endpoint_capability_not_allowed:submit_new_order" in decision.reasons


def test_client_order_id_is_durable_before_fake_transport_and_timeout_requires_query(tmp_path) -> None:
    identity = _identity(tmp_path / "btc-paper-state")
    broker, ledger, capability = _evidence()
    projected = project_btc_runtime_snapshot(
        _exchange(),
        identity=identity,
        broker_truth=broker,
        ledger_freshness=ledger,
        endpoint_capability=capability,
        return_result=True,
    )
    intent = _intent()
    risk = _risk(intent)
    evidence = _risk_evidence(intent)

    class FakeTimeoutTransport:
        def __init__(self, store: BTCClientOrderLifecycleStore) -> None:
            self.store = store
            self.calls: list[str] = []

        def submit(self, order_intent: OrderIntent) -> object:
            self.calls.append(order_intent.client_order_id)
            assert self.store.get(order_intent.client_order_id) is not None
            assert self.store.get(order_intent.client_order_id).status is BTCOrderLifecycleStatus.PREPARED
            raise TimeoutError("fixture timeout")

    store = BTCClientOrderLifecycleStore(identity.state_directory, identity=identity)
    transport = FakeTimeoutTransport(store)
    boundary = BTCExecutionBoundary(
        evaluator=_evaluator(projected.snapshot),
        lifecycle_store=store,
        identity=identity,
        broker_truth=broker,
        ledger_freshness=ledger,
        endpoint_capability=capability,
        risk_evidence=evidence,
        current_head=CURRENT_HEAD,
        session_id=SESSION_ID,
        epoch=EPOCH,
        transport=transport,
    )

    result = boundary.submit(order_intent=intent, risk_decision=risk)
    assert result.transport_called is True
    assert transport.calls == [intent.client_order_id]
    assert result.lifecycle is not None
    assert result.lifecycle.status is BTCOrderLifecycleStatus.AMBIGUOUS
    assert store.retry_decision(intent.client_order_id)["action"] == "query_by_client_order_id"
    assert store.retry_decision(intent.client_order_id)["allowed"] is False

    second = boundary.submit(order_intent=intent, risk_decision=risk)
    assert second.transport_called is False
    assert second.decision.allowed is False
    assert "blind_resend_forbidden" in second.decision.reasons
    assert transport.calls == [intent.client_order_id]

    queried = store.query_by_client_order_id(intent, lambda clord_id: {"status": "accepted", "ordId": "fixture-1"})
    assert queried.status is BTCOrderLifecycleStatus.ACCEPTED
    assert store.retry_decision(intent.client_order_id)["allowed"] is False


def test_demo_live_identity_and_state_directory_crossing_is_fail_closed(tmp_path) -> None:
    demo = _identity(tmp_path / "btc-demo-state", mode=BTCExecutionMode.DEMO)
    live = _identity(tmp_path / "btc-live-state", mode=BTCExecutionMode.LIVE, transport_enabled=False)
    assert demo.isolation_blockers(live)
    with pytest.raises(BTCExecutionBlocked, match="state_directory_mismatch"):
        BTCClientOrderLifecycleStore(demo.state_directory, identity=live)


def test_projection_rejects_unverified_broker_endpoint_and_caller_account_assertion(tmp_path) -> None:
    identity = _identity(tmp_path / "btc-paper-state")
    _, ledger, capability = _evidence()
    invalid_broker = BTCBrokerTruth(
        fresh=True,
        valid=False,
        account_verified=True,
        authoritative_account_verified=False,
        account_verification_source="",
        observed_at_utc=TS,
    )
    projected = project_btc_runtime_snapshot(
        _exchange(),
        identity=identity,
        broker_truth=invalid_broker,
        ledger_freshness=ledger,
        endpoint_capability=capability,
        account_verified=True,
        return_result=True,
    )
    assert projected.snapshot.ready_for_new_orders is False
    assert "btc_broker_truth_invalid" in projected.blockers
    assert "btc_authoritative_account_verification_missing" in projected.blockers
    assert "btc_caller_account_verification_untrusted" in projected.blockers

    missing_capability = BTCEndpointCapability(mode="paper", transport_enabled=False)
    broker, _, _ = _evidence()
    blocked = project_btc_runtime_snapshot(
        _exchange(),
        identity=identity,
        broker_truth=broker,
        ledger_freshness=ledger,
        endpoint_capability=missing_capability,
        return_result=True,
    )
    assert "btc_endpoint_transport_disabled" in blocked.blockers
    assert "btc_private_endpoint_capability_missing" in blocked.blockers
    assert "btc_order_endpoint_capability_missing" in blocked.blockers


def test_kill_switch_is_projected_and_blocks_every_action(tmp_path) -> None:
    identity = _identity(tmp_path / "btc-paper-state")
    _, ledger, capability = _evidence()
    broker = BTCBrokerTruth(
        fresh=True,
        valid=True,
        account_verified=True,
        authoritative_account_verified=True,
        account_verification_source="fixture-authoritative-account-observation",
        venue="okx",
        kill_switch_tripped=True,
        observed_at_utc=TS,
    )
    projected = project_btc_runtime_snapshot(
        _exchange(),
        identity=identity,
        broker_truth=broker,
        ledger_freshness=ledger,
        endpoint_capability=capability,
        return_result=True,
    )
    assert projected.snapshot.kill_switch_tripped is True
    assert "btc_kill_switch_tripped" in projected.blockers
    intent = _intent()
    decision = _evaluator(projected.snapshot).evaluate_action(
        RuntimeAction.SUBMIT_NEW_ORDER,
        order_intent=intent,
        risk_decision=_risk(intent),
        risk_evidence=_risk_evidence(intent),
        broker_truth=broker,
        ledger_freshness=ledger,
        endpoint_capability=capability,
        execution_identity=identity,
        expected_mode="paper",
        current_head=CURRENT_HEAD,
        session_id=SESSION_ID,
        epoch=EPOCH,
    )
    assert decision.allowed is False
    assert "kill_switch_tripped" in decision.reasons


def test_independent_risk_evidence_rejects_metadata_notional_venue_liquidation_claims(tmp_path) -> None:
    identity = _identity(tmp_path / "btc-paper-state")
    broker, ledger, capability = _evidence()
    projected = project_btc_runtime_snapshot(
        _exchange(),
        identity=identity,
        broker_truth=broker,
        ledger_freshness=ledger,
        endpoint_capability=capability,
        return_result=True,
    )
    intent = _intent(
        metadata={
            "ready": True,
            "risk_approved": True,
            "approved": True,
            "notional": 0.000001,
            "venue": "okx",
            "liquidation": False,
            "liquidation_safe": True,
        }
    )
    unapproved = _risk_evidence(intent, approved=False)
    decision = _evaluator(projected.snapshot).evaluate_action(
        RuntimeAction.SUBMIT_NEW_ORDER,
        order_intent=intent,
        risk_decision=_risk(intent),
        risk_evidence=unapproved,
        broker_truth=broker,
        ledger_freshness=ledger,
        endpoint_capability=capability,
        execution_identity=identity,
        expected_mode="paper",
        current_head=CURRENT_HEAD,
        session_id=SESSION_ID,
        epoch=EPOCH,
    )
    assert decision.allowed is False
    assert "risk_evidence_not_approved" in decision.reasons

    mismatched = _risk_evidence(intent, source_head="b" * 40)
    mismatch_decision = _evaluator(projected.snapshot).evaluate_action(
        RuntimeAction.SUBMIT_NEW_ORDER,
        order_intent=intent,
        risk_decision=_risk(intent),
        risk_evidence=mismatched,
        broker_truth=broker,
        ledger_freshness=ledger,
        endpoint_capability=capability,
        execution_identity=identity,
        expected_mode="paper",
        current_head=CURRENT_HEAD,
        session_id=SESSION_ID,
        epoch=EPOCH,
    )
    assert mismatch_decision.allowed is False
    assert "risk_evidence_source_head_mismatch" in mismatch_decision.reasons


def test_single_final_boundary_dispatches_all_six_actions(tmp_path) -> None:
    identity = _identity(tmp_path / "btc-paper-state")
    broker, ledger, capability = _evidence()
    projected = project_btc_runtime_snapshot(
        _exchange(),
        identity=identity,
        broker_truth=broker,
        ledger_freshness=ledger,
        endpoint_capability=capability,
        return_result=True,
    )

    class FakeTransport:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def _record(self, action: str, intent: OrderIntent) -> dict[str, str]:
            self.calls.append(action)
            return {"action": action, "clOrdId": intent.client_order_id}

        def submit(self, intent: OrderIntent) -> object:
            return self._record("submit_new_order", intent)

        def cancel(self, intent: OrderIntent) -> object:
            return self._record("cancel_order", intent)

        def replace(self, intent: OrderIntent) -> object:
            return self._record("replace_order", intent)

        def reduce_only(self, intent: OrderIntent) -> object:
            return self._record("reduce_only", intent)

        def attach_protection(self, intent: OrderIntent) -> object:
            return self._record("attach_protection", intent)

        def dead_man(self, intent: OrderIntent) -> object:
            return self._record("dead_man", intent)

    transport = FakeTransport()
    for action in RuntimeAction:
        intent = _intent(client_order_id=f"btc-paper-{action.value}")
        risk = _risk(intent)
        evidence = _risk_evidence(intent)
        store = BTCClientOrderLifecycleStore(identity.state_directory, identity=identity)
        boundary = BTCExecutionBoundary(
            evaluator=_evaluator(projected.snapshot),
            lifecycle_store=store,
            identity=identity,
            broker_truth=broker,
            ledger_freshness=ledger,
            endpoint_capability=capability,
            risk_evidence=evidence,
            current_head=CURRENT_HEAD,
            session_id=SESSION_ID,
            epoch=EPOCH,
            transport=transport,
        )
        result = boundary.execute_action(action, order_intent=intent, risk_decision=risk)
        assert result.decision.allowed is True, (action, result.decision.reasons)
        assert result.transport_called is True
        assert result.action == action.value
    assert transport.calls == [action.value for action in RuntimeAction]


@pytest.mark.parametrize("error", [TimeoutError("timeout"), ConnectionError("connection"), ValueError("bad http"), RuntimeError("unknown")])
def test_any_post_dispatch_exception_is_ambiguous_and_never_blind_resends(tmp_path, error: Exception) -> None:
    identity = _identity(tmp_path / "btc-paper-state")
    broker, ledger, capability = _evidence()
    projected = project_btc_runtime_snapshot(
        _exchange(),
        identity=identity,
        broker_truth=broker,
        ledger_freshness=ledger,
        endpoint_capability=capability,
        return_result=True,
    )
    intent = _intent(client_order_id=f"btc-error-{type(error).__name__}")
    risk = _risk(intent)
    evidence = _risk_evidence(intent)

    class FailingTransport:
        def __init__(self) -> None:
            self.calls = 0

        def submit(self, _: OrderIntent) -> object:
            self.calls += 1
            raise error

    transport = FailingTransport()
    store = BTCClientOrderLifecycleStore(identity.state_directory, identity=identity)
    boundary = BTCExecutionBoundary(
        evaluator=_evaluator(projected.snapshot),
        lifecycle_store=store,
        identity=identity,
        broker_truth=broker,
        ledger_freshness=ledger,
        endpoint_capability=capability,
        risk_evidence=evidence,
        current_head=CURRENT_HEAD,
        session_id=SESSION_ID,
        epoch=EPOCH,
        transport=transport,
    )
    result = boundary.submit(order_intent=intent, risk_decision=risk)
    assert result.transport_called is True
    assert result.lifecycle is not None
    assert result.lifecycle.status is BTCOrderLifecycleStatus.AMBIGUOUS
    assert f"transport_dispatch_exception:{type(error).__name__}" in result.decision.reasons
    second = boundary.submit(order_intent=intent, risk_decision=risk)
    assert second.transport_called is False
    assert transport.calls == 1


def test_dispatch_authorization_is_private_short_lived_and_revocable(tmp_path) -> None:
    identity = _identity(tmp_path / "btc-paper-state")
    broker, ledger, capability = _evidence()
    projected = project_btc_runtime_snapshot(
        _exchange(),
        identity=identity,
        broker_truth=broker,
        ledger_freshness=ledger,
        endpoint_capability=capability,
        return_result=True,
    )
    intent = _intent()
    risk = _risk(intent)
    evidence = _risk_evidence(intent)
    store = BTCClientOrderLifecycleStore(identity.state_directory, identity=identity)
    with pytest.raises(BTCExecutionBlocked, match="dispatch_authorization_private"):
        BTCDispatchAuthorization(action="submit_new_order")  # type: ignore[call-arg]
    with pytest.raises(BTCExecutionBlocked, match="dispatch_authorizer_private"):
        BTCDispatchAuthorizer()  # type: ignore[call-arg]

    class FakeTransport:
        def __init__(self) -> None:
            self.calls = 0

        def submit(self, _: OrderIntent) -> object:
            self.calls += 1
            return {"ok": True}

    transport = FakeTransport()
    boundary = BTCExecutionBoundary(
        evaluator=_evaluator(projected.snapshot),
        lifecycle_store=store,
        identity=identity,
        broker_truth=broker,
        ledger_freshness=ledger,
        endpoint_capability=capability,
        risk_evidence=evidence,
        current_head=CURRENT_HEAD,
        session_id=SESSION_ID,
        epoch=EPOCH,
        transport=transport,
    )
    store.prepare(intent)
    authorization = boundary.dispatch_authorizer.issue(
        RuntimeAction.SUBMIT_NEW_ORDER,
        order_intent=intent,
        risk_decision=risk,
        risk_evidence=evidence,
    )
    assert authorization.revoked is False
    authorization.revoke()
    blocked = boundary.submit(order_intent=intent, risk_decision=risk, authorization=authorization)
    assert blocked.transport_called is False
    assert "ambiguous_order_query_required_before_retry" not in blocked.decision.reasons
    assert "dispatch_authorization_invalid" in blocked.decision.reasons
    assert transport.calls == 0


def test_runtime_risk_proof_requires_trusted_issuer_and_rejects_1e12_self_report(tmp_path) -> None:
    identity = _identity(tmp_path / "btc-paper-state")
    broker, ledger, capability = _evidence()
    projected = project_btc_runtime_snapshot(
        _exchange(),
        identity=identity,
        broker_truth=broker,
        ledger_freshness=ledger,
        endpoint_capability=capability,
        return_result=True,
    )
    huge_intent = _intent(
        metadata={
            "ready": True,
            "risk_approved": True,
            "approved": True,
            "notional": 1e12,
            "venue": "okx",
            "liquidation": True,
            "liquidation_safe": True,
            "exposure": 1e12,
        }
    )
    with pytest.raises(RuntimeRiskEvidenceError, match="direct_construction_forbidden"):
        RuntimeRiskEvidence(intent_id=huge_intent.order_intent_id)  # type: ignore[call-arg]
    with pytest.raises(RuntimeRiskEvidenceError, match="producer_requires_authority"):
        RuntimeRiskEvidenceProducer()

    permissions_module = importlib.import_module("quant_shared.runtime.permissions")
    for legacy_name in (
        "_make_authoritative_risk_result",
        "_issue_canonical_risk_evidence",
        "canonical_risk_evidence_producer",
        "get_runtime_risk_evidence_producer",
        "issue_runtime_risk_evidence",
    ):
        assert not hasattr(permissions_module, legacy_name)

    self_report = {
        "order_intent": huge_intent,
        "source_head": CURRENT_HEAD,
        "account_identity": "a" * 64,
        "session_id": SESSION_ID,
        "key_namespace": "quant-system.paper.fixture",
        "client_order_namespace": "btc-paper-fixture",
        "epoch": EPOCH,
        "approved": True,
        "actual_notional": 1e12,
        "venue": "okx",
        "liquidation_safe": True,
        "exposure": 1e12,
        "evidence_id": "caller-self-signed-1e12",
    }
    with pytest.raises(RuntimeRiskEvidenceError, match="public_risk_evidence_issuance_forbidden"):
        RuntimeRiskEvidence.issue(**self_report)

    caller_authority = RuntimeRiskEvidenceAuthority(name="caller-created")
    caller_producer, caller_verifier = caller_authority.bind()
    with pytest.raises(RuntimeRiskEvidenceError, match="public_risk_evidence_producer_issue_forbidden"):
        caller_producer.issue(**self_report)

    caller_result = RuntimeAuthoritativeRiskResult.from_order_intent(
        huge_intent,
        approved=True,
        actual_notional=1e12,
        venue="okx",
        liquidation_safe=True,
        exposure=1e12,
    )
    caller_proof = caller_producer.issue_from_authoritative(
        order_intent=huge_intent,
        authoritative_result=caller_result,
        source_head=CURRENT_HEAD,
        account_identity="a" * 64,
        session_id=SESSION_ID,
        key_namespace="quant-system.paper.fixture",
        client_order_namespace="btc-paper-fixture",
        epoch=EPOCH,
        evidence_id="caller-authority-1e12",
    )
    assert caller_proof.actual_notional == 1e12
    assert caller_proof.exposure == 1e12
    assert caller_proof.verify(
        verifier=caller_verifier,
        order_intent=huge_intent,
        source_head=CURRENT_HEAD,
        account_identity="a" * 64,
        session_id=SESSION_ID,
        key_namespace="quant-system.paper.fixture",
        client_order_namespace="btc-paper-fixture",
        epoch=EPOCH,
    ) is True

    caller_decision = _evaluator(projected.snapshot).evaluate_action(
        RuntimeAction.SUBMIT_NEW_ORDER,
        order_intent=huge_intent,
        risk_decision=_risk(huge_intent),
        risk_evidence=caller_proof,
        broker_truth=broker,
        ledger_freshness=ledger,
        endpoint_capability=capability,
        execution_identity=identity,
        expected_mode="paper",
        current_head=CURRENT_HEAD,
        session_id=SESSION_ID,
        epoch=EPOCH,
    )
    assert caller_decision.allowed is False
    assert "risk_evidence_verifier_mismatch" in caller_decision.reasons

    decision_without_proof = _evaluator(projected.snapshot).evaluate_action(
        RuntimeAction.SUBMIT_NEW_ORDER,
        order_intent=huge_intent,
        risk_decision=_risk(huge_intent),
        broker_truth=broker,
        ledger_freshness=ledger,
        endpoint_capability=capability,
        execution_identity=identity,
        expected_mode="paper",
        current_head=CURRENT_HEAD,
        session_id=SESSION_ID,
        epoch=EPOCH,
    )
    assert decision_without_proof.allowed is False
    assert "risk_evidence_missing" in decision_without_proof.reasons

    forged_mapping = {
        "intent_id": huge_intent.order_intent_id,
        "source_head": CURRENT_HEAD,
        "account_identity": "a" * 64,
        "session_id": SESSION_ID,
        "key_namespace": "quant-system.paper.fixture",
        "client_order_namespace": "btc-paper-fixture",
        "epoch": EPOCH,
        "approved": True,
        "actual_notional": 1e12,
        "venue": "okx",
        "liquidation_safe": True,
        "exposure": 1e12,
        "evidence_id": "caller-forged",
    }
    forged_decision = _evaluator(projected.snapshot).evaluate_action(
        RuntimeAction.SUBMIT_NEW_ORDER,
        order_intent=huge_intent,
        risk_decision=_risk(huge_intent),
        risk_evidence=forged_mapping,
        broker_truth=broker,
        ledger_freshness=ledger,
        endpoint_capability=capability,
        execution_identity=identity,
        expected_mode="paper",
        current_head=CURRENT_HEAD,
        session_id=SESSION_ID,
        epoch=EPOCH,
    )
    assert forged_decision.allowed is False
    assert "risk_evidence_untrusted_issuer" in forged_decision.reasons

    canonical_proof = _risk_evidence(huge_intent)
    canonical_decision = _evaluator(projected.snapshot).evaluate_action(
        RuntimeAction.SUBMIT_NEW_ORDER,
        order_intent=huge_intent,
        risk_decision=_risk(huge_intent),
        risk_evidence=canonical_proof,
        broker_truth=broker,
        ledger_freshness=ledger,
        endpoint_capability=capability,
        execution_identity=identity,
        expected_mode="paper",
        current_head=CURRENT_HEAD,
        session_id=SESSION_ID,
        epoch=EPOCH,
    )
    assert canonical_decision.allowed is True
    assert canonical_proof.actual_notional == 100.0
    assert canonical_proof.exposure == 100.0

    unbound_decision = PermissionEvaluator(projected.snapshot).evaluate_action(
        RuntimeAction.SUBMIT_NEW_ORDER,
        order_intent=huge_intent,
        risk_decision=_risk(huge_intent),
        risk_evidence=canonical_proof,
        broker_truth=broker,
        ledger_freshness=ledger,
        endpoint_capability=capability,
        execution_identity=identity,
        expected_mode="paper",
        current_head=CURRENT_HEAD,
        session_id=SESSION_ID,
        epoch=EPOCH,
    )
    assert unbound_decision.allowed is False
    assert "risk_evidence_verifier_missing" in unbound_decision.reasons

    assert canonical_proof.verify(
        verifier=_CANONICAL_VERIFIER,
        order_intent=_intent(client_order_id="different-intent"),
        source_head=CURRENT_HEAD,
        account_identity="a" * 64,
        session_id=SESSION_ID,
        key_namespace="quant-system.paper.fixture",
        client_order_namespace="btc-paper-fixture",
        epoch=EPOCH,
    ) is False
    assert canonical_proof.verify(
        verifier=_CANONICAL_VERIFIER,
        order_intent=huge_intent,
        source_head=CURRENT_HEAD,
        account_identity="b" * 64,
        session_id=SESSION_ID,
        key_namespace="quant-system.paper.fixture",
        client_order_namespace="btc-paper-fixture",
        epoch=EPOCH,
    ) is False
    expired_proof = _risk_evidence(huge_intent, ttl_seconds=0.1, issued_at=TS)
    assert expired_proof.verify(
        verifier=_CANONICAL_VERIFIER,
        order_intent=huge_intent,
        source_head=CURRENT_HEAD,
        account_identity="a" * 64,
        session_id=SESSION_ID,
        key_namespace="quant-system.paper.fixture",
        client_order_namespace="btc-paper-fixture",
        epoch=EPOCH,
        now=TS + timedelta(seconds=1),
    ) is False

    tampered_proof = _risk_evidence(huge_intent)
    with pytest.raises(RuntimeRiskEvidenceError, match="risk_evidence_sealed"):
        tampered_proof._actual_notional = 1e12  # type: ignore[attr-defined]
    assert tampered_proof.verify(
        verifier=_CANONICAL_VERIFIER,
        order_intent=huge_intent,
        source_head=CURRENT_HEAD,
        account_identity="a" * 64,
        session_id=SESSION_ID,
        key_namespace="quant-system.paper.fixture",
        client_order_namespace="btc-paper-fixture",
        epoch=EPOCH,
    ) is True
