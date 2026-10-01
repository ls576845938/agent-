from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from quant_cn.execution.models import Fill, OrderIntent
from quant_cn.execution.oms import OfflineOMS
from quant_cn.execution.qmt_adapter_contract import (
    CONTRACT_VERSION,
    QMT_REQUIRED_BLOCKERS,
    QMTContractViolation,
    QMTFieldMapping,
    QMTFixtureCallback,
    QMTOfflineAdapterContract,
    QMTStatusMapping,
    canonical_qmt_json,
    normalize_qmt_callbacks,
    qmt_contract_summary,
    qmt_runtime_capabilities,
    reconcile_qmt_fixture,
)
from quant_cn.execution.qmt_sdk_fixture_binding import OfflineQMTFixtureAdapter
from quant_cn.ledger import (
    InMemoryLedgerStore,
    post_fill,
    post_opening_cash,
    reconcile,
)


NOW = datetime(2026, 7, 24, 6, 0, tzinfo=timezone.utc)
SOURCE_VERSION = "synthetic-qmt-recording-v1"
MAPPING_VERSION = "synthetic-qmt-mapping-v1"
HASH_A = "a" * 64


def field_mappings(
    *,
    available_at: datetime = NOW - timedelta(days=1),
) -> tuple[QMTFieldMapping, ...]:
    common = {
        "mapping_version": MAPPING_VERSION,
        "source_version": "fixture-field-contract-v1",
        "effective_from": NOW - timedelta(days=30),
        "available_at": available_at,
    }
    specs = (
        ("order", "client_order_ref", "client_order_id", "text", True),
        ("order", "external_order_ref", "external_order_id_hash", "sha256", True),
        ("order", "security_ref", "stable_security_id", "text", True),
        ("order", "status_code", "status", "status", True),
        ("order", "ordered_qty", "ordered_quantity", "integer", True),
        ("order", "filled_qty", "filled_quantity", "integer", True),
        ("fill", "fill_ref", "fill_id", "text", True),
        ("fill", "client_order_ref", "client_order_id", "text", True),
        ("fill", "external_order_ref", "external_order_id_hash", "sha256", True),
        ("fill", "security_ref", "stable_security_id", "text", True),
        ("fill", "side_code", "side", "side", True),
        ("fill", "fill_qty", "quantity", "integer", True),
        ("fill", "fill_price", "price", "decimal", True),
        ("fill", "fill_fee", "fee", "decimal", True),
        ("fill", "fill_time", "occurred_at", "timestamp", True),
    )
    return tuple(
        QMTFieldMapping(
            callback_type=callback_type,
            external_field=external,
            canonical_field=canonical,
            value_kind=value_kind,
            required=required,
            **common,
        )
        for callback_type, external, canonical, value_kind, required in specs
    )


def status_mappings(
    *,
    available_at: datetime = NOW - timedelta(days=1),
) -> tuple[QMTStatusMapping, ...]:
    return tuple(
        QMTStatusMapping(
            external_status=external,
            canonical_status=canonical,
            mapping_version=MAPPING_VERSION,
            source_version="fixture-status-contract-v1",
            effective_from=NOW - timedelta(days=30),
            available_at=available_at,
        )
        for external, canonical in (
            ("fixture_accepted", "accepted"),
            ("fixture_partial", "partially_filled"),
            ("fixture_filled", "filled"),
            ("fixture_cancel_requested", "cancel_requested"),
            ("fixture_cancelled", "cancelled"),
            ("fixture_rejected", "rejected"),
            ("fixture_expired", "expired"),
        )
    )


def order_callback(
    *,
    callback_id: str = "callback-order-1",
    sequence: int = 10,
    status: str = "fixture_partial",
    filled_quantity: object = "100",
) -> QMTFixtureCallback:
    return QMTFixtureCallback.from_mapping(
        callback_id=callback_id,
        callback_type="order",
        sequence=sequence,
        occurred_at=NOW + timedelta(minutes=2),
        received_at=NOW + timedelta(minutes=3),
        source_kind="synthetic_fixture",
        source_version=SOURCE_VERSION,
        payload={
            "client_order_ref": "client-1",
            "external_order_ref": HASH_A,
            "security_ref": "CN:600000",
            "status_code": status,
            "ordered_qty": "200",
            "filled_qty": filled_quantity,
        },
    )


def fill_callback(
    *,
    callback_id: str = "callback-fill-1",
    sequence: int = 11,
    quantity: object = "100",
) -> QMTFixtureCallback:
    fill_time = NOW + timedelta(minutes=1)
    return QMTFixtureCallback.from_mapping(
        callback_id=callback_id,
        callback_type="fill",
        sequence=sequence,
        occurred_at=fill_time,
        received_at=NOW + timedelta(minutes=2),
        source_kind="synthetic_fixture",
        source_version=SOURCE_VERSION,
        payload={
            "fill_ref": "fill-1",
            "client_order_ref": "client-1",
            "external_order_ref": HASH_A,
            "security_ref": "CN:600000",
            "side_code": "buy",
            "fill_qty": quantity,
            "fill_price": "10.00",
            "fill_fee": "1.00",
            "fill_time": fill_time,
        },
    )


def normalized_batch(*callbacks: QMTFixtureCallback):
    return normalize_qmt_callbacks(
        callbacks,
        first_sequence=10,
        field_mappings=field_mappings(),
        status_mappings=status_mappings(),
        as_of=NOW + timedelta(days=1),
    )


def offline_state():
    intent = OrderIntent(
        order_id="order-1",
        client_order_id="client-1",
        risk_decision_id="risk-1",
        target_id="target-1",
        run_id="run-1",
        stable_security_id="CN:600000",
        side="buy",
        quantity=200,
        limit_price=Decimal("10.00"),
        order_type="limit",
        time_in_force="day",
        decision_time=NOW,
        created_at=NOW,
        session_sequence=42,
        rule_versions=(("fixture_rules", "v1"),),
        evidence_hash="b" * 64,
    )
    fill = Fill(
        fill_id="fill-1",
        order_id="order-1",
        stable_security_id="CN:600000",
        side="buy",
        quantity=100,
        price=Decimal("10.00"),
        fee_components=(("commission", Decimal("1.00")),),
        occurred_at=NOW + timedelta(minutes=1),
        received_at=NOW + timedelta(minutes=2),
        session_sequence=42,
    )
    oms = OfflineOMS()
    oms.submit(intent)
    state = oms.apply_fill(fill)
    ledger = InMemoryLedgerStore()
    post_opening_cash(
        ledger,
        record_id="opening",
        amount=Decimal("100000"),
        occurred_at=NOW - timedelta(minutes=1),
        source_hash="c" * 64,
    )
    post_fill(ledger, fill)
    ledger_result = reconcile(
        orders=(state,),
        ledger=ledger,
        opening_cash=Decimal("100000"),
    )
    assert ledger_result.status == "reconciled"
    return state, ledger_result


def test_contract_surface_has_only_disabled_runtime_capabilities() -> None:
    adapter = OfflineQMTFixtureAdapter()
    assert isinstance(adapter, QMTOfflineAdapterContract)
    assert adapter.contract_version == CONTRACT_VERSION
    assert all(not item.enabled and not item.authorized for item in qmt_runtime_capabilities())
    assert all(value is False for value in adapter.safety_flags.values())
    summary = qmt_contract_summary()
    assert summary["required_blockers"] == list(QMT_REQUIRED_BLOCKERS)
    assert summary["runtime_eligible"] is False
    assert summary["promotion_eligible"] is False


def test_callback_arrival_order_and_exact_duplicate_are_deterministic() -> None:
    order = order_callback()
    fill = fill_callback()
    first = normalized_batch(fill, order, fill)
    second = normalized_batch(order, fill, fill)
    assert [item.sequence for item in first.callbacks] == [10, 11]
    assert first.duplicate_count == 1
    assert first == second
    assert first.fingerprint == second.fingerprint


def test_conflicting_duplicate_and_sequence_gap_fail_closed() -> None:
    conflict = replace(order_callback(), payload=order_callback(status="fixture_filled").payload)
    with pytest.raises(QMTContractViolation) as duplicate:
        normalized_batch(order_callback(), conflict)
    assert duplicate.value.error.code == "qmt_duplicate_callback_conflict"
    assert duplicate.value.error.retryable is False
    with pytest.raises(QMTContractViolation) as gap:
        normalized_batch(order_callback(), fill_callback(sequence=12))
    assert gap.value.error.code == "qmt_callback_sequence_gap_or_conflict"


def test_unknown_status_unmapped_field_and_future_mapping_fail_closed() -> None:
    with pytest.raises(QMTContractViolation) as unknown_status:
        normalized_batch(order_callback(status="unverified_vendor_status"), fill_callback())
    assert unknown_status.value.error.code == "qmt_unknown_order_status"

    payload = dict(order_callback().payload)
    payload["future_field"] = "not-mapped"
    unknown_field = replace(order_callback(), payload=tuple(payload.items()))
    with pytest.raises(QMTContractViolation) as unmapped:
        normalized_batch(unknown_field, fill_callback())
    assert unmapped.value.error.code == "qmt_unmapped_field"

    with pytest.raises(QMTContractViolation) as invisible:
        normalize_qmt_callbacks(
            (order_callback(), fill_callback()),
            first_sequence=10,
            field_mappings=field_mappings(available_at=NOW + timedelta(days=2)),
            status_mappings=status_mappings(),
            as_of=NOW + timedelta(days=1),
        )
    assert invisible.value.error.code == "qmt_unmapped_field"


@pytest.mark.parametrize(
    ("order_quantity", "fill_quantity", "expected_code"),
    [
        ("201", "100", "qmt_order_quantity_state_invalid"),
        ("100", "0", "qmt_fill_economics_invalid"),
    ],
)
def test_invalid_order_state_or_fill_economics_fail_closed(
    order_quantity: object,
    fill_quantity: object,
    expected_code: str,
) -> None:
    with pytest.raises(QMTContractViolation) as error:
        normalized_batch(
            order_callback(filled_quantity=order_quantity),
            fill_callback(quantity=fill_quantity),
        )
    assert error.value.error.code == expected_code


def test_float_and_sensitive_material_never_enter_fixture_contract() -> None:
    with pytest.raises(TypeError, match="qmt_float_forbidden"):
        canonical_qmt_json({"price": 1.5})
    with pytest.raises(ValueError, match="qmt_fixture_sensitive_field_forbidden"):
        QMTFixtureCallback.from_mapping(
            callback_id="sensitive",
            callback_type="order",
            sequence=10,
            occurred_at=NOW,
            received_at=NOW,
            source_kind="recorded_fixture",
            source_version=SOURCE_VERSION,
            payload={"account_id": "raw-account"},
        )


def test_fixture_reconciliation_matches_oms_and_ledger_but_gate_stays_blocked() -> None:
    state, ledger_result = offline_state()
    decision = reconcile_qmt_fixture(
        batch=normalized_batch(order_callback(), fill_callback()),
        orders=(state,),
        ledger_result=ledger_result,
    )
    assert decision.fixture_status == "reconciled"
    assert decision.fixture_reconciled is True
    assert decision.differences == ()
    assert decision.gate_status == "blocked"
    assert set(QMT_REQUIRED_BLOCKERS).issubset(decision.blockers)
    assert "cn_qmt_reconciliation_unproven" in decision.blockers
    assert all(value is False for _, value in decision.safety_flags)
    assert decision.promotion_eligible is False


def test_reconciliation_difference_is_hashed_and_blocks_gate() -> None:
    state, ledger_result = offline_state()
    batch = normalized_batch(order_callback(filled_quantity="0"), fill_callback(quantity="99"))
    decision = reconcile_qmt_fixture(
        batch=batch,
        orders=(state,),
        ledger_result=ledger_result,
    )
    assert decision.fixture_status == "difference"
    assert decision.fixture_reconciled is False
    assert {item.code for item in decision.differences} == {
        "qmt_fill_reconciliation_mismatch",
        "qmt_order_reconciliation_mismatch",
    }
    assert "qmt_fixture_reconciliation_difference" in decision.blockers
    assert all(len(item.identity_sha256) == 64 for item in decision.differences)
