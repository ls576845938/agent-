from __future__ import annotations

from datetime import datetime, timedelta, timezone
from dataclasses import replace
from pathlib import Path

import pytest

from quant_crypto.exchange.runtime import (
    BTCExchangeRuntimeStatus,
    BTCRestStatus,
    BTCStreamStatus,
)
from quant_crypto.oms.okx_live_preflight import OKXOfflineFakeReadOnlyPreflightProvider
from quant_crypto.oms.okx_mode_transport import OKXModeIsolationConfig, build_okx_client_order_id
from quant_crypto.oms.runtime_store import BTCRuntimeStore
from quant_crypto.oms.shared_runtime_live import (
    BTCOKXSharedRuntimeLiveCanary,
    DeadManArmedEvidence,
    LedgerUOWFacts,
    ProtectionPlan,
    SharedRuntimeLimitFacts,
    SharedRuntimeLiveCandidate,
    SharedRuntimeLiveDependencies,
    _stable_outbound_digest,
    _fixture_evidence_bundle,
    _fixture_okx_transport,
)
from quant_crypto.runtime.control_plane import (
    BTCBrokerTruth,
    BTCClientOrderLifecycleStore,
    BTCDemoExecutionDispatcher,
    BTCEndpointCapability,
    BTCExecutionDispatchFacts,
    BTCExecutionIdentity,
    BTCExecutionMode,
    BTCLedgerFreshness,
)
from quant_crypto.trading_contracts import OrderIntent, OrderSide, RiskDecision
from quant_shared.runtime.permissions import RuntimeAuthoritativeRiskResult, RuntimeAction, RuntimeRiskEvidenceAuthority


HEAD = "a" * 40
ACCOUNT = "b" * 64
SESSION = "btc-live-contract-session"
EPOCH = 3


def _clock() -> datetime:
    """Return one current test clock for each composed evidence bundle."""

    return datetime.now(timezone.utc).replace(microsecond=0)


class FakeProvider:
    status = "available"

    class Capability:
        transport_enabled = True
        private_endpoint_allowed = True
        order_endpoint_allowed = True

    capability_snapshot = Capability()
    safety = {"network_accessed": False, "private_endpoint_accessed": False, "order_endpoint_accessed": False}

    def __init__(self, *, error: BaseException | None = None) -> None:
        self.error = error
        self.calls: list[str] = []
        self.queries: list[str] = []

    def submit(self, order_intent: OrderIntent) -> dict[str, str]:
        self.calls.append(order_intent.client_order_id)
        if self.error is not None:
            raise self.error
        return {"status": "accepted", "broker_order_id": "broker-1"}

    def query_by_client_order_id(self, client_order_id: str) -> dict[str, str]:
        self.queries.append(client_order_id)
        return {"status": "accepted", "broker_order_id": "broker-ambiguous"}


def _intent(
    local_id: str = "fixture-001",
    *,
    metadata: dict[str, object] | None = None,
    now: datetime | None = None,
) -> OrderIntent:
    return OrderIntent(
        timestamp_utc=now or _clock(),
        strategy_id="contract-strategy",
        symbol="BTC-USDT-SWAP",
        side=OrderSide.BUY,
        quantity=0.001,
        client_order_id=local_id,
        metadata=metadata or {"ready": True, "risk_approved": True, "notional": 0.001},
    )


def _identity(root: Path, *, mode: BTCExecutionMode | str = BTCExecutionMode.LIVE) -> BTCExecutionIdentity:
    mode_text = mode.value if isinstance(mode, BTCExecutionMode) else str(mode)
    return BTCExecutionIdentity(
        mode=mode_text,
        state_directory=str(root),
        account_identity=ACCOUNT,
        key_namespace="quant-system.okx-live.trade",
        client_order_namespace="btc-okx-live-contract",
        account_verified=True,
        transport_enabled=True,
        live_execution_allowed=True,
        auto_start=False,
        auto_scale=False,
        session_id=SESSION,
        epoch=EPOCH,
        source_head=HEAD,
    )


def _candidate(intent: OrderIntent, *, now: datetime | None = None) -> SharedRuntimeLiveCandidate:
    return SharedRuntimeLiveCandidate(
        order_intent=intent,
        risk_decision=RiskDecision(
            approved=True,
            reason="candidate-only",
            order_intent_id=intent.order_intent_id,
            checked_at=now or _clock(),
        ),
        current_head=HEAD,
        session_id=SESSION,
        epoch=EPOCH,
        account_hash=ACCOUNT,
        credential_namespace="quant-system.okx-live.trade",
        state_root="",
        client_order_namespace="btc-okx-live-contract",
        permission_set=("account_readonly", "data_readonly"),
        expected_ip_allowlist=("203.0.113.10",),
        observed_egress=("203.0.113.10",),
    )


def _exchange(*, now: datetime | None = None) -> dict[str, object]:
    # A mapping is used deliberately: the current exchange snapshot treats a
    # live mode observation as non-authorizing.  The projection still requires
    # every status and reconciliation fact below.
    return {
        "venue": "okx",
        "instrument_id": "BTC-USDT-SWAP",
        "observed_at_utc": now or _clock(),
        "exchange_status": BTCExchangeRuntimeStatus.OK,
        "public_ws_status": BTCStreamStatus.CONNECTED,
        "private_ws_status": BTCStreamStatus.CONNECTED,
        "rest_status": BTCRestStatus.OK,
        "last_reconciliation_time_utc": now or _clock(),
        "mode": "live",
        "account_verified": True,
        "authoritative_account_verified": True,
        "account_verification_source": "fixture-authoritative-account",
        "account_identity": ACCOUNT,
        "source_head": HEAD,
        "session_id": SESSION,
        "epoch": EPOCH,
    }


def _facts(
    *, now: datetime | None = None
) -> tuple[BTCBrokerTruth, BTCLedgerFreshness, BTCEndpointCapability]:
    observed_at = now or _clock()
    return (
        BTCBrokerTruth(
            fresh=True,
            valid=True,
            account_verified=True,
            authoritative_account_verified=True,
            account_verification_source="fixture-authoritative-account",
            account_identity=ACCOUNT,
            venue="okx",
            source_head=HEAD,
            session_id=SESSION,
            epoch=EPOCH,
            observed_at_utc=observed_at,
        ),
        BTCLedgerFreshness(fresh=True, reconciled=True, observed_at_utc=observed_at),
        BTCEndpointCapability(
            mode="live",
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


def _ledger_facts(*, now: datetime | None = None) -> LedgerUOWFacts:
    return LedgerUOWFacts(
        idempotency_key="ledger-contract-1",
        timestamp_utc=now or _clock(),
        run_id="run-contract-1",
        order={"order_id": "o-1"},
        fills=({"fill_id": "f-1", "qty": 0.001},),
        position={"symbol": "BTC-USDT-SWAP", "qty": 0.001},
        cash={"currency": "USDT", "available": 100.0},
        funding={"currency": "USDT", "amount": 0.0},
        risk_context={"mark_price": 100.0, "index_price": 100.0, "liquidation_buffer_bps": 1000, "venue_rules": "fixture"},
        state_after={"last_order": "o-1"},
        safety={"network_accessed": False, "real_order_submitted": False},
        order_reconciled=True,
        fill_reconciled=True,
        position_reconciled=True,
        operator_acknowledged=True,
    )


def _dependencies(
    tmp_path: Path,
    *,
    provider: object | None = None,
    limit_facts: SharedRuntimeLimitFacts | None = None,
    intent: OrderIntent | None = None,
    **overrides: object,
) -> SharedRuntimeLiveDependencies:
    now = _clock()
    broker, ledger, endpoint = _facts(now=now)
    state_root = tmp_path / "btc-live-state"
    identity = _identity(state_root)
    config = OKXModeIsolationConfig.live(
        account_hash=ACCOUNT,
        state_root=state_root,
        client_order_namespace="btc-okx-live-contract",
        credential_identity="quant-system.okx-live.trade",
        private_endpoint_allowed=True,
        order_endpoint_allowed=True,
    )
    intent = intent or _intent(now=now)
    final_intent = replace(intent, client_order_id=build_okx_client_order_id(config, intent.client_order_id))
    raw_limit_facts = limit_facts
    facts = raw_limit_facts if type(raw_limit_facts) is SharedRuntimeLimitFacts else SharedRuntimeLimitFacts(
        instrument_id="BTC-USDT-SWAP",
        margin_mode="isolated",
        leverage=1.0,
        position_count=0,
        active_order_count=0,
        daily_new_orders=0,
        daily_loss_usdt=0.0,
        authoritative=True,
    )
    dead_man = DeadManArmedEvidence(
        armed=True,
        evidence_id="deadman-1",
        expires_at=now + timedelta(minutes=5),
        client_order_namespace="btc-okx-live-contract",
        session_id=SESSION,
        epoch=EPOCH,
        source_head=HEAD,
    )
    protection = ProtectionPlan(
        params={"tpTriggerPx": "101", "slTriggerPx": "99"},
        acknowledged=True,
        client_order_namespace="btc-okx-live-contract",
        session_id=SESSION,
        epoch=EPOCH,
        source_head=HEAD,
    )
    risk_result = RuntimeAuthoritativeRiskResult.from_order_intent(
        final_intent,
        approved=True,
        actual_notional=5.0,
        venue="okx",
        liquidation_safe=True,
        exposure=5.0,
    )
    evidence_values: dict[str, object] = {
        "identity": identity,
        "exchange_runtime": _exchange(now=now),
        "broker_truth": broker,
        "ledger_freshness": ledger,
        "endpoint_capability": endpoint,
        "limit_facts": facts,
        "ledger_facts": _ledger_facts(now=now),
        "dead_man_evidence": dead_man,
        "protection_plan": protection,
        "operator_acknowledged": True,
        "recovery_requires_ack": False,
        "risk_result": risk_result,
    }
    # Valid fixture evidence is placed in the private capsule.  Attack
    # overrides (plain mappings/dataclasses/bools) remain ordinary dependency
    # payloads so the composition root rejects them before provider dispatch.
    valid_types = {
        "limit_facts": SharedRuntimeLimitFacts,
        "dead_man_evidence": DeadManArmedEvidence,
        "protection_plan": ProtectionPlan,
        "risk_result": RuntimeAuthoritativeRiskResult,
        "ledger_facts": LedgerUOWFacts,
    }
    for name, expected_type in valid_types.items():
        if name in overrides and (overrides[name] is None or type(overrides[name]) is expected_type):
            evidence_values[name] = overrides[name]
    if "operator_acknowledged" in overrides and overrides["operator_acknowledged"] is not True:
        evidence_values["operator_acknowledged"] = overrides["operator_acknowledged"]
    bundle = _fixture_evidence_bundle(**evidence_values)
    deps = SharedRuntimeLiveDependencies(
        evidence_bundle=bundle,
        preflight_provider=OKXOfflineFakeReadOnlyPreflightProvider(),
        lifecycle_store=None,
        runtime_store=BTCRuntimeStore(tmp_path / "runtime-live"),
        transport=provider,
        okx_config=config,
        now=now,
    )
    if raw_limit_facts is not None and type(raw_limit_facts) is not SharedRuntimeLimitFacts:
        deps.limit_facts = raw_limit_facts  # type: ignore[assignment]
    capsule_names = set(valid_types) | {"operator_acknowledged"}
    for name, value in overrides.items():
        if name not in capsule_names or (name in valid_types and type(value) is not valid_types[name]) or (name == "operator_acknowledged" and value is True):
            setattr(deps, name, value)
    return deps


def _canonical_provider(
    tmp_path: Path,
    *,
    error: BaseException | None = None,
    calls: list[object] | None = None,
):
    config = OKXModeIsolationConfig.live(
        account_hash=ACCOUNT,
        state_root=tmp_path / "btc-live-state",
        client_order_namespace="btc-okx-live-contract",
        credential_identity="quant-system.okx-live.trade",
        private_endpoint_allowed=True,
        order_endpoint_allowed=True,
    )

    def responder(request):
        if calls is not None:
            calls.append(request)
        if str(getattr(request, "method", "")).upper() == "GET":
            return {"status": "accepted", "broker_order_id": "broker-query"}
        if error is not None:
            raise error
        return {"status": "accepted", "broker_order_id": "broker-1"}

    return _fixture_okx_transport(config=config, responder=responder)


def _post_attempts(provider) -> list[tuple[str, str]]:
    return [attempt for attempt in provider.attempts if attempt[0] == "POST"]


def _run(
    tmp_path: Path,
    *,
    provider: object | None = None,
    action: RuntimeAction | str = RuntimeAction.SUBMIT_NEW_ORDER,
    **overrides: object,
):
    intent = _intent()
    candidate = _candidate(intent)
    candidate = replace(candidate, state_root=str(tmp_path / "btc-live-state"))
    identity = _identity(Path(candidate.state_root))
    deps = _dependencies(tmp_path, provider=provider, intent=intent, **overrides)
    return BTCOKXSharedRuntimeLiveCanary(candidate=candidate, identity=identity, dependencies=deps).execute(action)


def test_default_no_transport_has_zero_provider_calls(tmp_path: Path) -> None:
    result = _run(tmp_path)
    assert result.allowed is False
    assert "okx_live_no_transport" in result.blockers
    assert result.transport_called is False


def test_read_only_data_permission_never_becomes_an_order_permit(tmp_path: Path) -> None:
    provider = _canonical_provider(tmp_path)
    intent = _intent()
    candidate = replace(_candidate(intent), state_root=str(tmp_path / "btc-live-state"), permission_set=("data_readonly",))
    identity = _identity(Path(candidate.state_root))
    result = BTCOKXSharedRuntimeLiveCanary(candidate=candidate, identity=identity, dependencies=_dependencies(tmp_path, provider=provider, intent=intent)).execute()
    assert result.allowed is False
    assert "preflight_only_data_readonly" in result.blockers
    assert _post_attempts(provider) == []


def test_candidate_metadata_and_risk_decision_cannot_bypass_authoritative_risk(tmp_path: Path) -> None:
    provider = FakeProvider()
    authority = RuntimeRiskEvidenceAuthority(name="caller-built")
    result = _run(
        tmp_path,
        provider=provider,
        risk_authority=authority,
        risk_result_supplier=lambda intent: RuntimeAuthoritativeRiskResult.from_order_intent(intent, approved=True, actual_notional=1e12, venue="okx", liquidation_safe=True, exposure=1e12),
    )
    assert result.allowed is False
    assert any("caller_risk_" in blocker for blocker in result.blockers)
    assert provider.calls == []


@pytest.mark.parametrize(
    "mutator, expected",
    [
        (lambda c: replace(c, expected_ip_allowlist=("203.0.113.10",), observed_egress=("203.0.113.11",)), "okx_live_preflight_failed"),
        (lambda c: replace(c, credential_namespace="quant-system.okx-demo.trade"), "execution_key_namespace"),
    ],
)
def test_preflight_identity_or_fixed_ip_mismatch_is_fail_closed(tmp_path: Path, mutator, expected: str) -> None:
    intent = _intent()
    base = _candidate(intent)
    base = replace(base, state_root=str(tmp_path / "btc-live-state"))
    candidate = mutator(base)
    identity = _identity(Path(base.state_root))
    provider = FakeProvider()
    result = BTCOKXSharedRuntimeLiveCanary(candidate=candidate, identity=identity, dependencies=_dependencies(tmp_path, provider=provider, intent=intent)).execute()
    assert result.allowed is False
    assert any(expected in blocker for blocker in result.blockers)
    assert provider.calls == []


def test_two_layer_runtime_limits_block_before_provider(tmp_path: Path) -> None:
    provider = FakeProvider()
    result = _run(
        tmp_path,
        provider=provider,
        limit_facts=SharedRuntimeLimitFacts(
            instrument_id="BTC-USDT-SWAP",
            margin_mode="isolated",
            leverage=1.0,
            position_count=2,
            active_order_count=0,
            daily_new_orders=0,
            daily_loss_usdt=0.0,
            authoritative=True,
        ),
    )
    assert result.allowed is False
    assert "runtime_position_count_exceeds_hard_limit" in result.blockers
    assert provider.calls == []


def test_preflight_receipt_mapping_forgery_is_rejected(tmp_path: Path) -> None:
    provider = FakeProvider()
    result = _run(tmp_path, provider=provider, preflight_receipt={"status": "PASS_READ_ONLY_PREFLIGHT"})
    assert result.allowed is False
    assert "okx_live_preflight_blocked" in result.blockers
    assert provider.calls == []


def test_clordid_is_durable_before_provider_call_and_ledger_is_idempotent(tmp_path: Path) -> None:
    provider = _canonical_provider(tmp_path)
    result = _run(tmp_path, provider=provider)
    assert result.allowed is True
    assert result.cl_ord_id == "btc-okx-live-contractfixture-001"
    assert len(_post_attempts(provider)) == 1
    lifecycle_path = Path(tmp_path / "btc-live-state" / "client_order_lifecycle.jsonl")
    assert lifecycle_path.exists()
    assert result.lifecycle is not None and result.lifecycle.reconciliation_complete is True
    store = BTCRuntimeStore(tmp_path / "ledger-idempotent")
    facts = _ledger_facts()
    first = store.commit_ledger_uow(
        idempotency_key=facts.idempotency_key,
        timestamp_utc=_clock().isoformat(),
        run_id=facts.run_id,
        order=facts.order,
        fills=list(facts.fills),
        position=facts.position,
        cash=facts.cash,
        funding=facts.funding,
        risk_context=facts.risk_context,
        state_after=facts.state_after,
        safety=facts.safety,
    )
    second = store.commit_ledger_uow(
        idempotency_key=facts.idempotency_key,
        timestamp_utc=_clock().isoformat(),
        run_id=facts.run_id,
        order=facts.order,
        fills=list(facts.fills),
        position=facts.position,
        cash=facts.cash,
        funding=facts.funding,
        risk_context=facts.risk_context,
        state_after=facts.state_after,
        safety=facts.safety,
    )
    assert first == second
    assert len(store.recover().events) == 1


def test_ambiguous_dispatch_queries_once_by_clordid_and_never_retries(tmp_path: Path) -> None:
    provider = _canonical_provider(tmp_path, error=ConnectionError("fixture timeout"))
    result = _run(tmp_path, provider=provider)
    assert result.allowed is False
    assert result.ambiguous is True
    assert result.query_called is True
    assert len(_post_attempts(provider)) == 1
    assert len(provider.attempts) == 2


@pytest.mark.parametrize("action", list(RuntimeAction))
def test_all_six_actions_share_the_same_final_canonical_boundary(tmp_path: Path, action: RuntimeAction) -> None:
    # pytest's generated test directory contains the token ``all``; the
    # preflight contract intentionally rejects wildcard-like path tokens.
    root = tmp_path.parent / f"actions-{action.value}"
    provider = _canonical_provider(root)
    result = _run(root, provider=provider, action=action)
    assert result.allowed is True, (action, result.blockers)
    assert result.action == action.value
    assert len(_post_attempts(provider)) == 1


def test_demo_dead_man_renewal_mints_risk_proof_at_dispatch_time(
    tmp_path: Path,
) -> None:
    """A fresh exchange snapshot must not pre-expire the short-lived permit."""

    class DemoAdapter:
        def capability_for(self, *, action, transport_context):
            assert action is RuntimeAction.DEAD_MAN
            assert transport_context == "demo-client"
            return BTCEndpointCapability(
                mode=BTCExecutionMode.DEMO,
                transport_enabled=True,
                cancel_order=True,
                reduce_only=True,
                dead_man=True,
                private_endpoint_allowed=True,
                order_endpoint_allowed=True,
            )

    source_head = "a" * 40
    snapshot_at = datetime.now(timezone.utc) - timedelta(seconds=10)
    intent = _intent("btcDP012345679998", now=snapshot_at)
    risk = RiskDecision(
        approved=True,
        reason="current-demo-risk",
        order_intent_id=intent.order_intent_id,
        threshold=10.0,
    )
    facts = BTCExecutionDispatchFacts(
        exchange_snapshot={
            "captured_at_utc": snapshot_at.isoformat(),
            "account": {
                "account_level": "2",
                "position_mode": "long_short_mode",
                "permissions": ["trade"],
            },
            "instrument": {"contract_value_btc": "0.01"},
            "ticker": {"bid": "60000", "ask": "60000.1"},
            "book": {
                "bids": [["60000", "1"]],
                "asks": [["60000.1", "1"]],
            },
        },
        private_ws={
            "connected": True,
            "listener_alive": True,
            "opening_allowed_after_reconciliation": True,
        },
        ledger_reconciliation={
            "status": "reconciled",
            "current_state_exchange_snapshot_match": True,
            "funding_cashflow_reconciled": True,
        },
        credential_service="quant-system.okx-demo.trade",
        runtime_run_id="0123456789abcdef",
        source_head=source_head,
        epoch=1,
        runtime_active=True,
        opening_allowed=False,
        cancel_only=True,
        risk_mode="FROZEN_UNKNOWN",
    )
    callbacks: list[str] = []
    dispatcher = BTCDemoExecutionDispatcher(
        expected_source_head=source_head,
        state_directory=tmp_path / "btc-demo-boundary",
        capability_adapter=DemoAdapter(),
        credential_service="quant-system.okx-demo.trade",
    )

    result = dispatcher.dispatch(
        action=RuntimeAction.DEAD_MAN,
        order_intent=intent,
        risk_decision=risk,
        facts=facts,
        transport_context="demo-client",
        callback=lambda submitted: callbacks.append(submitted.client_order_id)
        or {"status": "accepted"},
    )

    assert result.decision.allowed is True, result.blockers
    assert result.transport_called is True
    assert callbacks == [intent.client_order_id]


@pytest.mark.parametrize(
    "field, value",
    [
        ("request_digest", "tampered-request-digest"),
        ("source_head", "b" * 40),
        ("session_id", "tampered-session"),
        ("epoch", EPOCH + 1),
    ],
)
def test_canonical_permit_context_tamper_blocks_before_responder(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    calls: list[object] = []
    provider = _canonical_provider(tmp_path, calls=calls)
    config = provider.config
    body = {"instId": "BTC-USDT-SWAP", "clOrdId": "btc-okx-live-contract-permit-001", "sz": "0.001"}
    path = "/api/v5/trade/order"
    authorizer = provider.canonical_authorizer
    digest = _stable_outbound_digest(
        method="POST",
        path=path,
        body=body,
        client_order_id=body["clOrdId"],
        client_order_namespace=config.client_order_namespace,
        state_root=str(config.state_root),
        account_identity=ACCOUNT,
        key_namespace=config.credential_reference.service_namespace,
    )
    authorizer.arm(
        provider=provider,
        action="submit_new_order",
        client_order_id=body["clOrdId"],
        request_digest=digest,
        method="POST",
        path=path,
        body=body,
        source_head=HEAD,
        session_id=SESSION,
        epoch=EPOCH,
        account_identity=ACCOUNT,
        key_namespace=config.credential_reference.service_namespace,
        state_root=str(config.state_root),
        client_order_namespace=config.client_order_namespace,
    )
    authorizer._permit[field] = value
    with pytest.raises(Exception):
        provider.request(method="POST", path=path, body=body, client_order_id=body["clOrdId"])
    assert calls == []
    assert field in authorizer.last_blocker


def test_canonical_permit_is_one_shot_and_valid_once(tmp_path: Path) -> None:
    calls: list[object] = []
    provider = _canonical_provider(tmp_path, calls=calls)
    config = provider.config
    body = {"instId": "BTC-USDT-SWAP", "clOrdId": "btc-okx-live-contract-permit-002", "sz": "0.001"}
    path = "/api/v5/trade/order"
    authorizer = provider.canonical_authorizer
    digest = _stable_outbound_digest(
        method="POST",
        path=path,
        body=body,
        client_order_id=body["clOrdId"],
        client_order_namespace=config.client_order_namespace,
        state_root=str(config.state_root),
        account_identity=ACCOUNT,
        key_namespace=config.credential_reference.service_namespace,
    )
    authorizer.arm(
        provider=provider,
        action="submit_new_order",
        client_order_id=body["clOrdId"],
        request_digest=digest,
        method="POST",
        path=path,
        body=body,
        source_head=HEAD,
        session_id=SESSION,
        epoch=EPOCH,
        account_identity=ACCOUNT,
        key_namespace=config.credential_reference.service_namespace,
        state_root=str(config.state_root),
        client_order_namespace=config.client_order_namespace,
    )
    first = provider.request(method="POST", path=path, body=body, client_order_id=body["clOrdId"])
    assert first["status"] == "accepted"
    assert len(calls) == 1
    with pytest.raises(Exception):
        provider.request(method="POST", path=path, body=body, client_order_id=body["clOrdId"])
    assert len(calls) == 1
    assert "replayed" in authorizer.last_blocker


def test_deadman_and_oco_are_required_before_outbound(tmp_path: Path) -> None:
    provider = _canonical_provider(tmp_path)
    result = _run(tmp_path, provider=provider, dead_man_evidence=None)
    assert result.allowed is False
    assert any(blocker in result.blockers for blocker in ("dead_man_not_armed_or_expired", "canonical_dead_man_evidence_evidence_missing"))
    assert _post_attempts(provider) == []
    provider = _canonical_provider(tmp_path)
    result = _run(tmp_path, provider=provider, protection_plan=None)
    assert result.allowed is False
    assert any(blocker in result.blockers for blocker in ("oco_protection_ack_missing_or_namespace_mismatch", "canonical_protection_plan_evidence_missing"))


def test_demo_live_state_and_client_namespace_cannot_cross(tmp_path: Path) -> None:
    intent = _intent()
    candidate = replace(_candidate(intent), state_root=str(tmp_path / "btc-demo-state"), client_order_namespace="btc-okx-demo-contract")
    identity = _identity(Path(candidate.state_root), mode=BTCExecutionMode.DEMO)
    result = BTCOKXSharedRuntimeLiveCanary(candidate=candidate, identity=identity, dependencies=_dependencies(tmp_path, provider=FakeProvider(), intent=intent)).execute()
    assert result.allowed is False
    assert any("live" in blocker or "mode" in blocker or "identity" in blocker for blocker in result.blockers)


@pytest.mark.parametrize(
    "field, value, expected",
    [
        ("exchange_runtime", {"ready": True}, "caller_exchange_runtime_evidence_untrusted"),
        ("broker_truth", {"fresh": True, "valid": True}, "caller_broker_truth_evidence_untrusted"),
        ("ledger_freshness", {"fresh": True, "reconciled": True}, "caller_ledger_freshness_evidence_untrusted"),
        ("endpoint_capability", {"transport_enabled": True}, "caller_endpoint_capability_evidence_untrusted"),
        ("limit_facts", {"position_count": 0}, "caller_limit_facts_evidence_untrusted"),
        ("ledger_facts", {"order": {"id": "x"}}, "caller_ledger_facts_evidence_untrusted"),
        ("dead_man_evidence", {"armed": True}, "caller_dead_man_evidence_untrusted"),
        ("protection_plan", {"acknowledged": True}, "caller_protection_plan_evidence_untrusted"),
        ("operator_acknowledged", True, "operator_ack_plain_untrusted"),
    ],
)
def test_plain_runtime_evidence_is_structured_fail_closed(tmp_path: Path, field: str, value: object, expected: str) -> None:
    provider = FakeProvider()
    result = _run(tmp_path, provider=provider, **{field: value})
    assert result.allowed is False
    assert expected in result.blockers
    assert provider.calls == []


def test_boolean_dispatch_capability_and_arbitrary_provider_cannot_authorize(tmp_path: Path) -> None:
    provider = FakeProvider()
    result = _run(tmp_path, provider=provider, dispatch_capability=True)
    assert result.allowed is False
    assert "dispatch_capability_bool_forbidden" in result.blockers
    assert provider.calls == []

    provider = FakeProvider()
    result = _run(tmp_path / "arbitrary-provider", provider=provider)
    assert result.allowed is False
    assert "okx_live_provider_must_be_canonical_transport" in result.blockers
    assert provider.calls == []


def test_provider_safety_order_endpoint_access_is_blocked(tmp_path: Path) -> None:
    provider = _canonical_provider(tmp_path)
    provider.order_endpoint_accessed = True
    result = _run(tmp_path, provider=provider)
    assert result.allowed is False
    assert "provider_order_endpoint_accessed_forbidden" in result.blockers
    assert _post_attempts(provider) == []


def test_public_default_without_opaque_evidence_bundle_blocks_without_attribute_error(tmp_path: Path) -> None:
    deps = SharedRuntimeLiveDependencies(
        preflight_provider=OKXOfflineFakeReadOnlyPreflightProvider(),
        transport=FakeProvider(),
        dispatch_capability=True,
    )
    intent = _intent()
    candidate = replace(_candidate(intent), state_root=str(tmp_path / "btc-live-state"))
    result = BTCOKXSharedRuntimeLiveCanary(candidate=candidate, identity=_identity(Path(candidate.state_root)), dependencies=deps).execute()
    assert result.allowed is False
    assert "canonical_runtime_evidence_bundle_missing" in result.blockers
    assert "AttributeError" not in " ".join(result.blockers)
