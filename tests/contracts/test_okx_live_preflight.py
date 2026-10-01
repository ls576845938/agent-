from __future__ import annotations

import copy
import hashlib
import json
import pickle
from dataclasses import replace
from dataclasses import fields
from datetime import datetime, timedelta, timezone

import pytest

from quant_crypto.oms.okx_live_preflight import (
    OKX_DATA_READONLY_PERMISSION,
    OKX_LIVE_API_BASE,
    OKXLivePreflightError,
    OKXLivePreflightPolicy,
    OKXLivePreflightReceipt,
    OKXLivePreflightRequest,
    OKXLivePreflightStatus,
    OKXOfflineFakeReadOnlyPreflightProvider,
)


NOW = datetime(2026, 8, 8, 13, 0, tzinfo=timezone.utc)


def _request(**overrides) -> OKXLivePreflightRequest:
    payload = {
        "current_head": "f8b366bc5759dff64bf2c86aa2d0b39ea799091a",
        "session_id": "live-preflight-session-001",
        "epoch": 7,
        "mode": "live",
        "api_base": OKX_LIVE_API_BASE,
        "credential_namespace": "quant-system.okx-live.preflight",
        "account_hash": "b" * 64,
        "state_root": "C:/quant-state/btc-okx-live",
        "client_order_namespace": "btc-okx-live-orders",
        "policy": OKXLivePreflightPolicy(),
        "permission_set": (OKX_DATA_READONLY_PERMISSION,),
        "expected_ip_allowlist": ("192.0.2.10",),
        "observed_egress": ("192.0.2.10",),
        "withdraw_allowed": False,
        "transfer_allowed": False,
        "nonce": "preflight-nonce-001",
        "observed_at_utc": NOW,
    }
    payload.update(overrides)
    return OKXLivePreflightRequest(**payload)


def _forged_receipt(receipt: OKXLivePreflightReceipt, **changes) -> OKXLivePreflightReceipt:
    """Build the kind of object an attacker could make with object.__new__.

    This is deliberately test-only: the production receipt has no issuance
    seam, and the provider must reject even a clone with a valid recomputed
    digest and the original nonce.
    """

    forged = object.__new__(OKXLivePreflightReceipt)
    for receipt_field in fields(OKXLivePreflightReceipt):
        value = changes.get(receipt_field.name, getattr(receipt, receipt_field.name))
        object.__setattr__(forged, receipt_field.name, value)
    payload = forged._payload()
    forged_digest = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    object.__setattr__(forged, "digest", forged_digest)
    return forged


def test_provider_issues_opaque_read_only_receipt_and_verifies_offline() -> None:
    provider = OKXOfflineFakeReadOnlyPreflightProvider()
    request = _request()

    receipt = provider.issue(request)
    result = provider.verify(receipt, request, now_utc=NOW + timedelta(seconds=1))

    assert result.status == OKXLivePreflightStatus.PASS_READ_ONLY
    assert result.passed is True
    assert result.order_capability_allowed is False
    assert receipt.digest_valid() is True
    assert receipt.to_dict()["live_unlock_allowed"] is False
    assert receipt.to_dict()["secrets_read"] is False
    assert provider.safety == {
        "network_accessed": False,
        "private_endpoint_called": False,
        "order_endpoint_called": False,
        "withdraw_called": False,
        "transfer_called": False,
        "post_provider_registered": False,
        "order_capability_allowed": False,
        "live_unlock_allowed": False,
    }


def test_receipt_cannot_be_constructed_from_mapping_or_json_view() -> None:
    provider = OKXOfflineFakeReadOnlyPreflightProvider()
    request = _request()
    receipt = provider.issue(request)
    view = receipt.to_dict()

    with pytest.raises(TypeError, match="provider_issued_only"):
        OKXLivePreflightReceipt(**view)
    blocked = provider.verify(view, request, now_utc=NOW + timedelta(seconds=1))
    assert blocked.status == OKXLivePreflightStatus.BLOCKED
    assert "receipt_must_be_provider_opaque_instance" in blocked.blockers


@pytest.mark.parametrize(
    "field, mutated",
    [
        ("current_head", "0" * 40),
        ("session_id", "live-preflight-session-002"),
        ("epoch", 8),
        ("credential_namespace", "quant-system.okx-live.other"),
        ("account_hash", "c" * 64),
        ("state_root", "C:/quant-state/btc-okx-live-other"),
        ("client_order_namespace", "btc-okx-live-orders-v2"),
        ("policy", OKXLivePreflightPolicy(max_notional_usdt=9.0)),
        ("permission_set", ("account_readonly", OKX_DATA_READONLY_PERMISSION)),
        ("expected_ip_allowlist", ("192.0.2.11",)),
        ("observed_egress", ("192.0.2.11",)),
        ("nonce", "preflight-nonce-002"),
    ],
)
def test_receipt_digest_binds_identity_policy_permission_and_egress_fields(field, mutated) -> None:
    baseline = _request()
    if field in {"expected_ip_allowlist", "observed_egress"}:
        changed = replace(
            baseline,
            expected_ip_allowlist=("192.0.2.11",),
            observed_egress=("192.0.2.11",),
        )
    else:
        changed = replace(baseline, **{field: mutated})
    baseline_receipt = OKXOfflineFakeReadOnlyPreflightProvider().issue(baseline)
    changed_receipt = OKXOfflineFakeReadOnlyPreflightProvider().issue(changed)

    assert baseline_receipt.digest != changed_receipt.digest


def test_receipt_digest_binds_expiry() -> None:
    request = _request()
    short = OKXOfflineFakeReadOnlyPreflightProvider(ttl_seconds=1).issue(request)
    long = OKXOfflineFakeReadOnlyPreflightProvider(ttl_seconds=2).issue(request)
    assert short.expires_at_utc != long.expires_at_utc
    assert short.digest != long.digest


@pytest.mark.parametrize(
    "field, value, blocker",
    [
        ("expected_ip_allowlist", ("*",), "expected_ip_allowlist_wildcard_forbidden"),
        ("expected_ip_allowlist", ("0.0.0.0/0",), "expected_ip_allowlist_wildcard_forbidden"),
        ("expected_ip_allowlist", (), "expected_ip_allowlist_missing"),
        ("observed_egress", ("192.0.2.11",), "expected_observed_egress_mismatch"),
    ],
)
def test_ip_allowlist_is_fixed_and_observed_egress_must_match(field, value, blocker) -> None:
    request = _request(**{field: value})
    with pytest.raises(OKXLivePreflightError, match=blocker):
        OKXOfflineFakeReadOnlyPreflightProvider().issue(request)


@pytest.mark.parametrize(
    "field, value, blocker",
    [
        ("withdraw_allowed", None, "withdraw_must_be_explicitly_false"),
        ("withdraw_allowed", True, "withdraw_must_be_explicitly_false"),
        ("transfer_allowed", None, "transfer_must_be_explicitly_false"),
        ("transfer_allowed", True, "transfer_must_be_explicitly_false"),
    ],
)
def test_withdraw_and_transfer_must_be_explicitly_disabled(field, value, blocker) -> None:
    with pytest.raises(OKXLivePreflightError, match=blocker):
        OKXOfflineFakeReadOnlyPreflightProvider().issue(_request(**{field: value}))


def test_data_readonly_receipt_cannot_upgrade_to_order_capability() -> None:
    provider = OKXOfflineFakeReadOnlyPreflightProvider()
    receipt = provider.issue(_request())
    assert receipt.order_capability_allowed is False
    assert provider.verify(receipt, _request(), now_utc=NOW + timedelta(seconds=1)).passed is True

    with pytest.raises(OKXLivePreflightError, match="order_or_write_permission_forbidden"):
        provider.issue(
            _request(
                nonce="preflight-order-nonce-001",
                permission_set=(OKX_DATA_READONLY_PERMISSION, "trade"),
            )
        )


def test_expiry_is_fail_closed() -> None:
    provider = OKXOfflineFakeReadOnlyPreflightProvider(ttl_seconds=1)
    request = _request()
    receipt = provider.issue(request)

    result = provider.verify(receipt, request, now_utc=NOW + timedelta(seconds=1))
    assert result.status == OKXLivePreflightStatus.BLOCKED
    assert "receipt_expired" in result.blockers


def test_nonce_replay_is_fail_closed_after_first_acceptance() -> None:
    provider = OKXOfflineFakeReadOnlyPreflightProvider()
    request = _request()
    receipt = provider.issue(request)

    first = provider.verify(receipt, request, now_utc=NOW + timedelta(seconds=1))
    replay = provider.verify(receipt, request, now_utc=NOW + timedelta(seconds=2))
    assert first.passed is True
    assert replay.status == OKXLivePreflightStatus.BLOCKED
    assert "receipt_nonce_replay" in replay.blockers


@pytest.mark.parametrize(
    "field, value, blocker",
    [
        ("current_head", "0" * 40, "request_current_head_mismatch"),
        ("session_id", "live-preflight-session-002", "request_session_id_mismatch"),
        ("epoch", 8, "request_epoch_mismatch"),
        ("credential_namespace", "quant-system.okx-live.other", "request_credential_namespace_mismatch"),
        ("client_order_namespace", "btc-okx-live-orders-v2", "request_client_order_namespace_mismatch"),
    ],
)
def test_current_identity_namespace_head_session_epoch_mismatch_blocks(field, value, blocker) -> None:
    provider = OKXOfflineFakeReadOnlyPreflightProvider()
    original = _request()
    receipt = provider.issue(original)
    current = replace(original, **{field: value})

    result = provider.verify(receipt, current, now_utc=NOW + timedelta(seconds=1))
    assert result.status == OKXLivePreflightStatus.BLOCKED
    assert blocker in result.blockers


def test_receipt_from_another_provider_authority_is_rejected() -> None:
    request = _request()
    issuer = OKXOfflineFakeReadOnlyPreflightProvider()
    other = OKXOfflineFakeReadOnlyPreflightProvider()
    receipt = issuer.issue(request)

    result = other.verify(receipt, request, now_utc=NOW + timedelta(seconds=1))
    assert result.status == OKXLivePreflightStatus.BLOCKED
    assert "receipt_provider_authority_mismatch" in result.blockers


@pytest.mark.parametrize(
    "policy, blocker",
    [
        (OKXLivePreflightPolicy(instrument_id="ETH-USDT-SWAP"), "policy_instrument_must_be_BTC-USDT-SWAP"),
        (OKXLivePreflightPolicy(margin_mode="cross"), "policy_margin_mode_must_be_isolated"),
        (OKXLivePreflightPolicy(leverage=2.0), "policy_leverage_must_be_1x"),
        (OKXLivePreflightPolicy(max_notional_usdt=10.01), "policy_max_notional_must_be_at_most_10USDT"),
        (OKXLivePreflightPolicy(max_positions=2), "policy_max_positions_must_be_1"),
        (OKXLivePreflightPolicy(max_active_orders=2), "policy_max_active_orders_must_be_1"),
        (OKXLivePreflightPolicy(max_daily_loss_usdt=1.01), "policy_daily_loss_must_be_1USDT"),
        (OKXLivePreflightPolicy(max_daily_new_orders=3), "policy_max_daily_new_orders_must_be_2"),
        (OKXLivePreflightPolicy(auto_start=True), "policy_auto_start_must_be_false"),
        (OKXLivePreflightPolicy(auto_scale=True), "policy_auto_scale_must_be_false"),
    ],
)
def test_mandatory_policy_facts_are_enforced(policy, blocker) -> None:
    with pytest.raises(OKXLivePreflightError, match=blocker):
        OKXOfflineFakeReadOnlyPreflightProvider().issue(
            _request(policy=policy, nonce="policy-nonce-001")
        )


@pytest.mark.parametrize(
    "field, value, blocker",
    [
        ("mode", "demo", "mode_must_be_live"),
        ("api_base", "https://www.okx.com", "live_api_base_mismatch"),
        ("credential_namespace", "quant-system.okx-demo.trade", "credential_namespace_must_be_live"),
        ("account_hash", "bad", "account_hash_missing_or_invalid"),
        ("state_root", "relative/live-state", "live_state_root_missing_or_not_absolute"),
        ("client_order_namespace", "btc-okx-demo-orders", "client_order_namespace_must_be_live"),
        ("current_head", "*", "current_head_missing_or_invalid"),
        ("session_id", "", "session_id_missing_or_invalid"),
        ("epoch", 0, "epoch_missing_or_invalid"),
        ("nonce", "", "nonce_missing_or_invalid"),
    ],
)
def test_missing_or_cross_mode_identity_is_fail_closed(field, value, blocker) -> None:
    with pytest.raises(OKXLivePreflightError, match=blocker):
        OKXOfflineFakeReadOnlyPreflightProvider().issue(_request(**{field: value}))


def test_provider_has_no_network_or_post_surface() -> None:
    provider = OKXOfflineFakeReadOnlyPreflightProvider()
    assert provider.safety["network_accessed"] is False
    assert provider.safety["post_provider_registered"] is False
    assert not hasattr(provider, "post")
    assert not hasattr(provider, "send")


def test_raw_authority_token_and_receipt_issue_seams_are_absent() -> None:
    provider = OKXOfflineFakeReadOnlyPreflightProvider()

    assert not hasattr(provider, "_authority_token")
    assert not hasattr(provider, "authority_token")
    assert not hasattr(provider, "get_authority_token")
    assert not hasattr(provider, "_signer")
    assert not hasattr(provider, "signer")
    assert not hasattr(OKXLivePreflightReceipt, "_issue")


def test_agent7_same_nonce_tampered_forgery_is_rejected_and_does_not_consume_original() -> None:
    provider = OKXOfflineFakeReadOnlyPreflightProvider()
    original_request = _request()
    original = provider.issue(original_request)
    forged_request = replace(
        original_request,
        session_id="forged-session-002",
        account_hash="c" * 64,
        state_root="C:/quant-state/forged",
    )
    forged = _forged_receipt(
        original,
        session_id=forged_request.session_id,
        account_hash=forged_request.account_hash,
        state_root=forged_request.state_root,
    )

    result = provider.verify(forged, forged_request, now_utc=NOW + timedelta(seconds=1))

    assert forged.nonce == original.nonce
    assert result.status == OKXLivePreflightStatus.BLOCKED
    assert "receipt_object_identity_mismatch" in result.blockers
    assert "receipt_opaque_capability_mismatch" in result.blockers
    assert "receipt_payload_does_not_match_issued_record" in result.blockers
    accepted_original = provider.verify(
        original, original_request, now_utc=NOW + timedelta(seconds=1)
    )
    assert accepted_original.passed is True


def test_receipt_copy_deepcopy_pickle_and_same_payload_reconstruction_are_rejected() -> None:
    provider = OKXOfflineFakeReadOnlyPreflightProvider()
    request = _request()
    receipt = provider.issue(request)

    with pytest.raises(TypeError, match="copy_forbidden"):
        copy.copy(receipt)
    with pytest.raises(TypeError, match="deepcopy_forbidden"):
        copy.deepcopy(receipt)
    with pytest.raises(TypeError, match="pickle_forbidden"):
        pickle.dumps(receipt)

    reconstructed = _forged_receipt(receipt)
    result = provider.verify(reconstructed, request, now_utc=NOW + timedelta(seconds=1))
    assert result.status == OKXLivePreflightStatus.BLOCKED
    assert "receipt_object_identity_mismatch" in result.blockers
    assert "receipt_opaque_capability_mismatch" in result.blockers


def test_in_place_receipt_tampering_is_rejected_by_issued_digest_and_payload() -> None:
    provider = OKXOfflineFakeReadOnlyPreflightProvider()
    request = _request()
    receipt = provider.issue(request)
    object.__setattr__(receipt, "account_hash", "c" * 64)

    result = provider.verify(receipt, request, now_utc=NOW + timedelta(seconds=1))

    assert result.status == OKXLivePreflightStatus.BLOCKED
    assert "receipt_digest_does_not_match_issued_record" in result.blockers
    assert "receipt_payload_does_not_match_issued_record" in result.blockers


@pytest.mark.parametrize(
    "field, value",
    [
        ("current_head", "0" * 40),
        ("session_id", "forged-session-003"),
        ("epoch", 8),
        ("mode", "demo"),
        ("api_base", "https://www.okx.com"),
        ("credential_namespace", "quant-system.okx-live.other"),
        ("account_hash", "c" * 64),
        ("state_root", "C:/quant-state/forged"),
        ("client_order_namespace", "btc-okx-live-forged"),
        ("policy_digest", "0" * 64),
        ("permission_set", ("account_readonly", OKX_DATA_READONLY_PERMISSION)),
        ("expected_ip_allowlist", ("192.0.2.11",)),
        ("observed_egress", ("192.0.2.11",)),
        ("expires_at_utc", (NOW + timedelta(hours=1)).isoformat()),
    ],
)
def test_reconstructed_receipt_identity_fields_cannot_be_tampered(field, value) -> None:
    provider = OKXOfflineFakeReadOnlyPreflightProvider()
    request = _request()
    receipt = provider.issue(request)
    forged = _forged_receipt(receipt, **{field: value})

    result = provider.verify(forged, request, now_utc=NOW + timedelta(seconds=1))

    assert result.status == OKXLivePreflightStatus.BLOCKED
    assert "receipt_object_identity_mismatch" in result.blockers
