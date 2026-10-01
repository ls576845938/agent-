from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

import pytest

from quant_crypto.oms.okx_mode_transport import (
    OKXAmbiguousSubmitError,
    OKXCapabilityError,
    OKXInjectedLocalAttestationVerifier,
    OKXCredentialReference,
    OKXLiveReadOnlyPreflightAttestation,
    OKXLiveTransport,
    OKXLiveOptInRequired,
    OKXLiveTransportOptIn,
    OKXModeIsolationConfig,
    OKXModeIsolationError,
    OKXNoTransport,
    OKXTransportMode,
    OKXTransportError,
    OKXTransportRegistry,
    OKXTransportCapabilitySnapshot,
    OKXTransportStatus,
    OKXTransportUnavailable,
    assert_okx_mode_isolated,
    validate_okx_mode_isolation,
)


def _configs(tmp_path):
    demo = OKXModeIsolationConfig.demo(
        account_hash="a" * 64,
        state_root=tmp_path / "demo-state",
        client_order_namespace="btc-okx-demo-orders",
    )
    live = OKXModeIsolationConfig.live(
        account_hash="b" * 64,
        state_root=tmp_path / "live-state",
        client_order_namespace="btc-okx-live-orders",
        private_endpoint_allowed=True,
        order_endpoint_allowed=True,
    )
    return demo, live


def _live_config(
    tmp_path,
    *,
    private_endpoint_allowed: bool = True,
    order_endpoint_allowed: bool = True,
):
    return OKXModeIsolationConfig.live(
        account_hash="b" * 64,
        state_root=tmp_path / "live",
        client_order_namespace="btc-okx-live-orders",
        private_endpoint_allowed=private_endpoint_allowed,
        order_endpoint_allowed=order_endpoint_allowed,
    )


def _opt_in() -> OKXLiveTransportOptIn:
    return OKXLiveTransportOptIn(
        ticket="BTC-OKX-LIVE-FAKE-01",
        operator="offline-contract-test",
        reason="injected fake only",
        confirmed=True,
        read_only=True,
    )


class _AllowAuthorizer:
    def __init__(self, decisions=True) -> None:
        self.decisions = list(decisions) if isinstance(decisions, (list, tuple)) else [decisions]
        self.calls = []

    def authorize_dispatch(self, *, request):
        self.calls.append(request)
        if len(self.decisions) == 1:
            return self.decisions[0]
        return self.decisions.pop(0)


class _MutableCapabilityProvider:
    def __init__(self, **state) -> None:
        self.state = {
            "transport_enabled": True,
            "private_endpoint_allowed": True,
            "order_endpoint_allowed": True,
            "capability_digest": "capability-v1",
            **state,
        }

    def __call__(self):
        return dict(self.state)


class _FlipCapabilityAuthorizer(_AllowAuthorizer):
    def __init__(self, provider, *, field: str, value) -> None:
        super().__init__(True)
        self.provider = provider
        self.field = field
        self.value = value

    def authorize_dispatch(self, *, request):
        self.calls.append(request)
        self.provider.state[self.field] = self.value
        return True


class _SequenceCapabilityProvider:
    def __init__(self, *states) -> None:
        self.states = [dict(state) for state in states]
        self.last = dict(self.states[-1]) if self.states else {}
        self.calls = 0

    def __call__(self):
        self.calls += 1
        if self.states:
            state = self.states.pop(0)
        else:
            state = self.last
        self.last = dict(state)
        return dict(state)


class _IssuedPermit:
    revoked = False

    def __init__(self, *, client_order_id: str) -> None:
        self.client_order_id = client_order_id

    def valid_for(self, **kwargs):
        return True

    def to_dict(self):
        return {
            "action": "submit_new_order",
            "client_order_id": self.client_order_id,
            "client_order_namespace": "btc-okx-live-orders",
            "account_identity": "b" * 64,
            "source_head": "a" * 40,
            "session_id": "",
            "key_namespace": "",
            "epoch": 1,
        }


class _IssueAuthorizer:
    def __init__(self, *, deny_after: int | None = None) -> None:
        self.calls = []
        self.deny_after = deny_after

    def issue(self, action, *, order_intent, risk_decision, risk_evidence=None):
        self.calls.append((action, order_intent, risk_decision, risk_evidence))
        if self.deny_after is not None and len(self.calls) > self.deny_after:
            raise RuntimeError("canonical state changed")
        return _IssuedPermit(client_order_id=getattr(order_intent, "client_order_id", ""))


def test_registry_defaults_to_no_transport_and_ignores_demo_environment(monkeypatch) -> None:
    monkeypatch.setenv("OKX_MODE", "live")
    monkeypatch.setenv("OKX_LIVE_ENABLED", "1")
    registry = OKXTransportRegistry()

    resolved = registry.resolve(OKXTransportMode.LIVE)
    assert isinstance(resolved, OKXNoTransport)
    assert resolved.status is OKXTransportStatus.NO_TRANSPORT
    assert registry.live_provider is None
    assert registry.capability_matrix()["live_unlock_allowed"] is False
    with pytest.raises(OKXTransportUnavailable):
        resolved.request(method="GET", path="/api/v5/account/config")


def test_live_provider_requires_auditable_explicit_opt_in(tmp_path) -> None:
    live = OKXModeIsolationConfig.live(
        account_hash="b" * 64,
        state_root=tmp_path / "live",
        client_order_namespace="btc-okx-live-orders",
    )
    with pytest.raises(OKXLiveOptInRequired):
        OKXLiveTransport(config=live)

    demo, live_pair = _configs(tmp_path)
    fake = OKXLiveTransport(
        config=live_pair,
        opt_in=_opt_in(),
        canonical_authorizer=_AllowAuthorizer(),
    )
    registry = OKXTransportRegistry(demo_config=demo, live_config=live_pair)
    registry.register_live(
        fake,
        opt_in=_opt_in(),
        demo_config=demo,
        live_config=live_pair,
    )
    assert registry.resolve("live") is fake
    assert registry.capability_matrix()["network_accessed"] is False

    missing_pair = OKXTransportRegistry()
    assert isinstance(missing_pair.register_live(fake, opt_in=_opt_in()), OKXNoTransport)
    assert missing_pair.resolve_live().status is OKXTransportStatus.NO_TRANSPORT
    assert "okx_live_activation_mode_pair_missing" in missing_pair.activation_blockers


def test_demo_live_identity_and_storage_namespaces_are_disjoint(tmp_path) -> None:
    demo, live = _configs(tmp_path)
    assert validate_okx_mode_isolation(demo, live) == ()
    assert_okx_mode_isolated(demo, live)

    same_account = replace(
        live,
        credential_reference=OKXCredentialReference(
            mode=OKXTransportMode.LIVE,
            service_namespace="quant-system.okx-live.trade",
            account_hash="a" * 64,
        ),
    )
    blockers = validate_okx_mode_isolation(demo, same_account)
    assert "okx_demo_live_account_identity_reused" in blockers
    with pytest.raises(OKXModeIsolationError):
        assert_okx_mode_isolated(demo, same_account)


def test_live_transport_blocks_withdraw_and_transfer_before_fake_dispatch(tmp_path) -> None:
    live = OKXModeIsolationConfig.live(
        account_hash="b" * 64,
        state_root=tmp_path / "live",
        client_order_namespace="btc-okx-live-orders",
    )
    calls = []
    transport = OKXLiveTransport(
        config=live,
        opt_in=_opt_in(),
        responder=lambda request: calls.append(request),
    )
    for path in ("/api/v5/asset/transfer", "/api/v5/asset/withdrawal"):
        with pytest.raises(OKXCapabilityError):
            transport.request(method="POST", path=path, body={"clOrdId": "safe-test-1"})
    assert calls == []
    assert transport.safety["withdraw_transfer_accessed"] is True
    assert transport.safety["real_order_submitted"] is False


def test_non_get_order_write_is_dispatched_once_and_becomes_ambiguous(tmp_path) -> None:
    live = _live_config(tmp_path)
    calls = []

    def fail_once(request):
        calls.append(request)
        raise TimeoutError("injected timeout")

    transport = OKXLiveTransport(
        config=live,
        opt_in=_opt_in(),
        responder=fail_once,
        canonical_authorizer=_AllowAuthorizer(),
    )
    with pytest.raises(OKXAmbiguousSubmitError) as exc_info:
        transport.request(
            method="POST",
            path="/api/v5/trade/order",
            body={"instId": "BTC-USDT-SWAP", "clOrdId": "durable-clord-001"},
        )
    assert len(calls) == 1
    assert len(transport.attempts) == 1
    assert exc_info.value.client_order_id == "durable-clord-001"
    assert exc_info.value.reconciliation_required is True
    assert exc_info.value.retry_performed is False


def test_get_retry_budget_is_separate_from_non_get_retry_policy(tmp_path) -> None:
    live = _live_config(tmp_path)
    calls = []

    def flaky_get(request):
        calls.append(request)
        if len(calls) == 1:
            raise TimeoutError("read-only transient")
        return {"ok": True}

    transport = OKXLiveTransport(
        config=live,
        opt_in=_opt_in(),
        responder=flaky_get,
        canonical_authorizer=_AllowAuthorizer(),
        max_get_attempts=2,
    )
    assert transport.request(method="GET", path="/api/v5/account/config") == {"ok": True}
    assert len(calls) == 2


def test_order_write_requires_durable_client_order_id(tmp_path) -> None:
    live = _live_config(tmp_path)
    transport = OKXLiveTransport(config=live, opt_in=_opt_in(), responder=lambda request: request)
    with pytest.raises(OKXCapabilityError, match="durable_clordid"):
        transport.request(method="POST", path="/api/v5/trade/order", body={"instId": "BTC-USDT-SWAP"})


def test_missing_canonical_authorizer_has_zero_responder_calls(tmp_path) -> None:
    live = _live_config(tmp_path)
    calls = []
    transport = OKXLiveTransport(
        config=live,
        opt_in=_opt_in(),
        responder=lambda request: calls.append(request),
    )
    with pytest.raises(OKXTransportError, match="canonical_authorizer_missing"):
        transport.request(method="GET", path="/api/v5/account/config")
    assert calls == []


def test_authorizer_is_called_per_dispatch_and_denial_invalidates_old_decision(tmp_path) -> None:
    live = _live_config(tmp_path)
    authorizer = _AllowAuthorizer([True, False])
    calls = []
    transport = OKXLiveTransport(
        config=live,
        opt_in=_opt_in(),
        responder=lambda request: calls.append(request) or {"ok": True},
        canonical_authorizer=authorizer,
    )
    assert transport.request(method="GET", path="/api/v5/account/config") == {"ok": True}
    with pytest.raises(OKXTransportError, match="authorization_denied"):
        transport.request(method="GET", path="/api/v5/account/config")
    assert len(authorizer.calls) == 2
    assert len(calls) == 1


def test_committed_canonical_issue_contract_is_consumed_without_local_permit_cache(tmp_path) -> None:
    live = _live_config(tmp_path)
    canonical = _IssueAuthorizer(deny_after=1)
    calls = []
    transport = OKXLiveTransport(
        config=live,
        opt_in=_opt_in(),
        responder=lambda request: calls.append(request) or {"ok": True},
        canonical_authorizer=canonical,
        canonical_context_provider=lambda request: {
            "action": "submit_new_order",
            "order_intent": type("Intent", (), {"client_order_id": request.client_order_id})(),
            "risk_decision": object(),
            "risk_evidence": {"source_head": "a" * 40, "epoch": 1},
        },
    )
    assert transport.request(
        method="POST",
        path="/api/v5/trade/order",
        body={"instId": "BTC-USDT-SWAP", "clOrdId": "canonical-clord-001"},
    ) == {"ok": True}
    with pytest.raises(OKXTransportError, match="canonical_authorization_denied"):
        transport.request(
            method="POST",
            path="/api/v5/trade/order",
            body={"instId": "BTC-USDT-SWAP", "clOrdId": "canonical-clord-002"},
        )
    assert len(canonical.calls) == 2
    assert len(calls) == 1


def test_recording_safety_is_single_sourced_after_private_and_order_access(tmp_path) -> None:
    live = _live_config(tmp_path)
    transport = OKXLiveTransport(
        config=live,
        opt_in=_opt_in(),
        responder=lambda request: {"ok": True},
        canonical_authorizer=_AllowAuthorizer(),
    )
    transport.request(method="GET", path="/api/v5/account/config")
    assert transport.safety["private_endpoint_accessed"] is True
    assert transport.safety["order_endpoint_accessed"] is False
    transport.request(
        method="POST",
        path="/api/v5/trade/order",
        body={"instId": "BTC-USDT-SWAP", "clOrdId": "safety-clord-001"},
    )
    assert transport.safety["private_endpoint_accessed"] is True
    assert transport.safety["order_endpoint_accessed"] is True


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("GET", "/api/v5/account/config", None),
        ("POST", "/api/v5/trade/order", {"clOrdId": "dispatch-order-001"}),
        ("POST", "/api/v5/trade/cancel-order", {"clOrdId": "dispatch-cancel-001"}),
        ("POST", "/api/v5/trade/amend-order", {"clOrdId": "dispatch-replace-001"}),
        ("POST", "/api/v5/trade/order", {"clOrdId": "dispatch-reduce-001", "reduceOnly": True}),
        ("POST", "/api/v5/trade/order-algo", {"clOrdId": "dispatch-protection-001"}),
        ("POST", "/api/v5/trade/cancel-all-after", {"clOrdId": "dispatch-deadman-001"}),
    ],
)
def test_private_and_all_write_capabilities_cross_canonical_fence(
    tmp_path, method, path, body
) -> None:
    live = _live_config(tmp_path)
    authorizer = _AllowAuthorizer()
    calls = []
    transport = OKXLiveTransport(
        config=live,
        opt_in=_opt_in(),
        responder=lambda request: calls.append(request) or {"ok": True},
        canonical_authorizer=authorizer,
    )
    transport.request(method=method, path=path, body=body)
    assert len(authorizer.calls) == 1
    assert len(calls) == 1


def test_b_private_capability_false_blocks_even_when_canonical_permit_is_true(tmp_path) -> None:
    live = _live_config(tmp_path, private_endpoint_allowed=False, order_endpoint_allowed=True)
    authorizer = _AllowAuthorizer(True)
    calls = []
    transport = OKXLiveTransport(
        config=live,
        opt_in=_opt_in(),
        responder=lambda request: calls.append(request),
        canonical_authorizer=authorizer,
    )
    with pytest.raises(OKXCapabilityError, match="private_endpoint_disabled"):
        transport.request(method="GET", path="/api/v5/account/config")
    assert authorizer.calls == []
    assert calls == []
    assert transport.requests == []


def test_b_order_capability_false_blocks_every_write_even_when_canonical_permit_is_true(tmp_path) -> None:
    live = _live_config(tmp_path, private_endpoint_allowed=True, order_endpoint_allowed=False)
    authorizer = _AllowAuthorizer(True)
    calls = []
    transport = OKXLiveTransport(
        config=live,
        opt_in=_opt_in(),
        responder=lambda request: calls.append(request),
        canonical_authorizer=authorizer,
    )
    with pytest.raises(OKXCapabilityError, match="order_endpoint_disabled:submit_new_order"):
        transport.request(
            method="POST",
            path="/api/v5/trade/order",
            body={"clOrdId": "b-capability-order-001"},
        )
    assert authorizer.calls == []
    assert calls == []
    assert transport.requests == []


def test_b_transport_capability_false_blocks_before_canonical_permit(tmp_path) -> None:
    live = _live_config(tmp_path)
    provider = _MutableCapabilityProvider(transport_enabled=False)
    authorizer = _AllowAuthorizer(True)
    calls = []
    transport = OKXLiveTransport(
        config=live,
        opt_in=_opt_in(),
        responder=lambda request: calls.append(request),
        canonical_authorizer=authorizer,
        capability_provider=provider,
    )
    with pytest.raises(OKXCapabilityError, match="transport_disabled"):
        transport.request(method="GET", path="/api/v5/account/config")
    assert authorizer.calls == []
    assert calls == []


def test_b_capability_state_change_during_canonical_authorization_invalidates_permit(tmp_path) -> None:
    live = _live_config(tmp_path)
    provider = _MutableCapabilityProvider()
    authorizer = _FlipCapabilityAuthorizer(
        provider,
        field="order_endpoint_allowed",
        value=False,
    )
    calls = []
    transport = OKXLiveTransport(
        config=live,
        opt_in=_opt_in(),
        responder=lambda request: calls.append(request),
        canonical_authorizer=authorizer,
        capability_provider=provider,
    )
    with pytest.raises(OKXTransportError, match="capability_changed"):
        transport.request(
            method="POST",
            path="/api/v5/trade/order",
            body={"clOrdId": "b-capability-toctou-001"},
        )
    assert len(authorizer.calls) == 1
    assert calls == []


def test_b_capability_digest_change_with_same_flags_invalidates_permit(tmp_path) -> None:
    live = _live_config(tmp_path)
    provider = _MutableCapabilityProvider(capability_digest="capability-v1")
    authorizer = _FlipCapabilityAuthorizer(
        provider,
        field="capability_digest",
        value="capability-v2",
    )
    calls = []
    transport = OKXLiveTransport(
        config=live,
        opt_in=_opt_in(),
        responder=lambda request: calls.append(request),
        canonical_authorizer=authorizer,
        capability_provider=provider,
    )
    with pytest.raises(OKXTransportError, match="capability_changed"):
        transport.request(
            method="POST",
            path="/api/v5/trade/order",
            body={"clOrdId": "b-capability-digest-001"},
        )
    assert len(authorizer.calls) == 1
    assert calls == []
    assert provider.state["private_endpoint_allowed"] is True
    assert provider.state["order_endpoint_allowed"] is True


def test_b_final_capability_fence_rejects_change_after_permit_acceptance(tmp_path) -> None:
    live = _live_config(tmp_path)
    stable = {
        "transport_enabled": True,
        "private_endpoint_allowed": True,
        "order_endpoint_allowed": True,
        "capability_digest": "stable-v1",
    }
    changed = {**stable, "capability_digest": "stable-v2"}
    provider = _SequenceCapabilityProvider(stable, stable, stable, changed)
    authorizer = _AllowAuthorizer(True)
    calls = []
    transport = OKXLiveTransport(
        config=live,
        opt_in=_opt_in(),
        responder=lambda request: calls.append(request),
        canonical_authorizer=authorizer,
        capability_provider=provider,
    )
    with pytest.raises(OKXTransportError, match="capability_changed"):
        transport.request(method="GET", path="/api/v5/account/config")
    assert len(authorizer.calls) == 1
    assert calls == []
    assert provider.calls == 4


def test_read_only_attestation_is_strict_redacted_and_never_unlocks_live() -> None:
    attestation = OKXLiveReadOnlyPreflightAttestation(
        account_hash="c" * 64,
        credential_identity="quant-system.okx-live.readonly",
        withdraw_permission_disabled=True,
        transfer_permission_disabled=True,
        ip_whitelist_enforced=True,
        expected_ip_whitelist=("192.0.2.10",),
        attested_ip_whitelist=("192.0.2.10",),
        config_fingerprint="d" * 64,
        reviewer="operator",
        reviewed_at_utc=datetime(2026, 8, 8, tzinfo=timezone.utc),
        approval_ticket="BTC-OKX-READONLY-PREFLIGHT-01",
        external_proof_id="proof-001",
    )
    assert attestation.status == "BLOCKED_UNVERIFIED"
    assert "okx_live_attestation_trusted_local_verification_missing" in attestation.validate()
    verified = attestation.verify_with(OKXInjectedLocalAttestationVerifier())
    assert verified.validate() == []
    payload = verified.to_dict()
    assert verified.status == "PASS_READ_ONLY_ATTESTATION"
    assert payload["live_unlock_allowed"] is False
    assert payload["secrets_read"] is False
    assert payload["network_accessed"] is False
    serialized = str(payload).lower()
    assert "api_key" not in serialized
    assert "secret_key" not in serialized
    assert "passphrase" not in serialized


def test_invalid_attestation_keeps_all_live_capabilities_blocked() -> None:
    attestation = OKXLiveReadOnlyPreflightAttestation(
        account_hash="e" * 64,
        credential_identity="quant-system.okx-live.readonly",
        secrets_read=True,
        order_endpoint_accessed=True,
        live_orders_allowed=True,
    )
    blockers = attestation.validate()
    assert "okx_live_attestation_withdraw_must_be_disabled" in blockers
    assert "okx_live_attestation_ip_whitelist_not_enforced" in blockers
    assert "okx_live_attestation_secrets_read_forbidden" in blockers
    assert "okx_live_attestation_order_endpoint_accessed_forbidden" in blockers
    assert attestation.to_dict()["live_unlock_allowed"] is False
