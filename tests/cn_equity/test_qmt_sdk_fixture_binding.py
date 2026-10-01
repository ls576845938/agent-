from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import inspect

import pytest

from quant_cn.execution import qmt_adapter_contract as contract_module
from quant_cn.execution import qmt_sdk_fixture_binding as binding_module
from quant_cn.execution.qmt_adapter_contract import (
    QMT_REQUIRED_BLOCKERS,
    QMTFieldMapping,
    QMTFixtureCallback,
    QMTStatusMapping,
)
from quant_cn.execution.qmt_sdk_fixture_binding import (
    OfflineQMTFixtureAdapter,
    QMTFixtureEnvelope,
    bind_qmt_fixture,
    qmt_fixture_binding_summary,
)


NOW = datetime(2026, 7, 24, 8, 0, tzinfo=timezone.utc)
AS_OF = NOW + timedelta(days=1)
SOURCE_VERSION = "recorded-redacted-qmt-fixture-v1"
MAPPING_VERSION = "recorded-redacted-qmt-map-v1"
HASH_A = "a" * 64


def mappings() -> tuple[QMTFieldMapping, ...]:
    common = {
        "mapping_version": MAPPING_VERSION,
        "source_version": "recorded-fixture-concept-catalog-v1",
        "effective_from": NOW - timedelta(days=10),
        "available_at": NOW - timedelta(days=1),
    }
    specs = (
        ("order", "client_ref", "client_order_id", "text"),
        ("order", "external_ref", "external_order_id_hash", "sha256"),
        ("order", "security_ref", "stable_security_id", "text"),
        ("order", "status", "status", "status"),
        ("order", "order_qty", "ordered_quantity", "integer"),
        ("order", "filled_qty", "filled_quantity", "integer"),
        ("fill", "fill_ref", "fill_id", "text"),
        ("fill", "client_ref", "client_order_id", "text"),
        ("fill", "external_ref", "external_order_id_hash", "sha256"),
        ("fill", "security_ref", "stable_security_id", "text"),
        ("fill", "side", "side", "side"),
        ("fill", "qty", "quantity", "integer"),
        ("fill", "price", "price", "decimal"),
        ("fill", "fee", "fee", "decimal"),
        ("fill", "event_time", "occurred_at", "timestamp"),
    )
    return tuple(
        QMTFieldMapping(
            callback_type=callback_type,
            external_field=external,
            canonical_field=canonical,
            value_kind=value_kind,
            required=True,
            **common,
        )
        for callback_type, external, canonical, value_kind in specs
    )


def statuses() -> tuple[QMTStatusMapping, ...]:
    return (
        QMTStatusMapping(
            external_status="recorded_partial",
            canonical_status="partially_filled",
            mapping_version=MAPPING_VERSION,
            source_version="recorded-fixture-status-catalog-v1",
            effective_from=NOW - timedelta(days=10),
            available_at=NOW - timedelta(days=1),
        ),
    )


def callbacks(
    *,
    source_kind: str = "recorded_fixture",
) -> tuple[QMTFixtureCallback, ...]:
    fill_time = NOW + timedelta(minutes=1)
    order = QMTFixtureCallback.from_mapping(
        callback_id="recorded-order-1",
        callback_type="order",
        sequence=20,
        occurred_at=NOW + timedelta(minutes=2),
        received_at=NOW + timedelta(minutes=3),
        source_kind=source_kind,
        source_version=SOURCE_VERSION,
        payload={
            "client_ref": "client-1",
            "external_ref": HASH_A,
            "security_ref": "CN:600000",
            "status": "recorded_partial",
            "order_qty": "200",
            "filled_qty": "100",
        },
    )
    fill = QMTFixtureCallback.from_mapping(
        callback_id="recorded-fill-1",
        callback_type="fill",
        sequence=21,
        occurred_at=fill_time,
        received_at=NOW + timedelta(minutes=2),
        source_kind=source_kind,
        source_version=SOURCE_VERSION,
        payload={
            "fill_ref": "fill-1",
            "client_ref": "client-1",
            "external_ref": HASH_A,
            "security_ref": "CN:600000",
            "side": "buy",
            "qty": "100",
            "price": Decimal("10.00"),
            "fee": Decimal("1.00"),
            "event_time": fill_time,
        },
    )
    return order, fill


def fixture(
    *,
    source_kind: str = "recorded_fixture",
    available_at: datetime = NOW + timedelta(minutes=4),
) -> QMTFixtureEnvelope:
    return QMTFixtureEnvelope.create(
        fixture_id=f"{source_kind}-qmt-1",
        source_kind=source_kind,
        source_version=SOURCE_VERSION,
        mapping_version=MAPPING_VERSION,
        available_at=available_at,
        recorded_at=NOW,
        first_sequence=20,
        callbacks=callbacks(source_kind=source_kind),
    )


def bind(value: QMTFixtureEnvelope, *, as_of: datetime = AS_OF):
    return bind_qmt_fixture(
        value,
        field_mappings=mappings(),
        status_mappings=statuses(),
        as_of=as_of,
    )


@pytest.mark.parametrize("source_kind", ["synthetic_fixture", "recorded_fixture"])
def test_synthetic_and_recorded_fixture_bind_offline_only(source_kind: str) -> None:
    decision = bind(fixture(source_kind=source_kind))
    assert decision.fixture_eligible is True
    assert decision.normalized_batch is not None
    assert decision.runtime_eligible is False
    assert decision.gate_status == "blocked"
    assert decision.errors == ()
    assert set(QMT_REQUIRED_BLOCKERS) == set(decision.blockers)
    assert all(value is False for _, value in decision.safety_flags)
    assert decision.promotion_eligible is False


def test_binding_is_byte_semantic_deterministic_and_frozen() -> None:
    value = fixture()
    first = bind(value)
    second = bind(value)
    assert first == second
    assert first.input_sha256 == value.calculated_payload_sha256
    assert first.normalized_batch == second.normalized_batch
    with pytest.raises(FrozenInstanceError):
        value.fixture_id = "changed"  # type: ignore[misc]


def test_future_fixture_and_unknown_mapping_version_return_structured_blocker() -> None:
    future = bind(fixture(), as_of=NOW + timedelta(minutes=3))
    assert future.fixture_eligible is False
    assert future.errors[0].code == "qmt_fixture_not_available"
    assert future.errors[0].retryable is False
    assert future.fixture_id is None
    assert future.normalized_batch is None

    wrong_version = replace(mappings()[0], mapping_version="other-map")
    value = fixture()
    decision = bind_qmt_fixture(
        value,
        field_mappings=(wrong_version,),
        status_mappings=statuses(),
        as_of=AS_OF,
    )
    assert decision.fixture_eligible is False
    assert decision.errors[0].code == "qmt_fixture_field_mapping_version_missing"


def test_redaction_and_runtime_action_attestations_are_mandatory_false() -> None:
    with pytest.raises(ValueError, match="qmt_fixture_redaction_attestation_required"):
        QMTFixtureEnvelope.create(
            fixture_id="not-redacted",
            source_kind="recorded_fixture",
            source_version=SOURCE_VERSION,
            mapping_version=MAPPING_VERSION,
            available_at=AS_OF,
            recorded_at=NOW,
            first_sequence=20,
            callbacks=callbacks(),
            redaction_attested=False,
        )
    actions = dict(fixture().runtime_actions)
    actions["sdk_imported"] = True
    with pytest.raises(
        ValueError, match="qmt_fixture_runtime_action_attestation_invalid"
    ):
        QMTFixtureEnvelope.create(
            fixture_id="sdk-used",
            source_kind="recorded_fixture",
            source_version=SOURCE_VERSION,
            mapping_version=MAPPING_VERSION,
            available_at=AS_OF,
            recorded_at=NOW,
            first_sequence=20,
            callbacks=callbacks(),
            runtime_actions=actions,
        )


def test_payload_hash_and_source_identity_are_immutable_contracts() -> None:
    value = fixture()
    with pytest.raises(ValueError, match="qmt_fixture_payload_hash_mismatch"):
        replace(value, payload_sha256="f" * 64)
    mismatched_callback = replace(callbacks()[0], source_version="other-source")
    with pytest.raises(
        ValueError, match="qmt_fixture_callback_source_version_mismatch"
    ):
        QMTFixtureEnvelope.create(
            fixture_id="source-mismatch",
            source_kind="recorded_fixture",
            source_version=SOURCE_VERSION,
            mapping_version=MAPPING_VERSION,
            available_at=AS_OF,
            recorded_at=NOW,
            first_sequence=20,
            callbacks=(mismatched_callback, callbacks()[1]),
        )


def test_adapter_rejects_non_envelope_without_echo_or_runtime_unlock() -> None:
    adapter = OfflineQMTFixtureAdapter()
    decision = adapter.bind_fixture(
        {"not": "an envelope"},
        field_mappings=mappings(),
        status_mappings=statuses(),
        as_of=AS_OF,
    )
    assert decision.fixture_eligible is False
    assert decision.errors[0].code == "qmt_fixture_envelope_required"
    assert decision.runtime_eligible is False
    assert all(value is False for _, value in decision.safety_flags)


def test_modules_have_no_sdk_network_file_or_order_call_surface() -> None:
    forbidden_imports = {
        "importlib",
        "os",
        "pathlib",
        "requests",
        "socket",
        "subprocess",
        "urllib",
        "xtquant",
    }
    forbidden_calls = {
        "cancel_order",
        "connect",
        "get_account_state",
        "get_open_orders",
        "get_positions",
        "place_order",
        "send_order",
        "submit_order",
    }
    for module in (contract_module, binding_module):
        tree = ast.parse(inspect.getsource(module))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        calls = {
            node.func.id if isinstance(node.func, ast.Name) else node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, (ast.Name, ast.Attribute))
        }
        definitions = {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        assert imported.isdisjoint(forbidden_imports)
        assert calls.isdisjoint(forbidden_calls)
        assert definitions.isdisjoint(forbidden_calls)


def test_summary_keeps_all_runtime_actions_and_safety_flags_false() -> None:
    summary = qmt_fixture_binding_summary()
    assert summary["fixture_only"] is True
    assert summary["runtime_eligible"] is False
    assert summary["promotion_eligible"] is False
    assert all(value is False for value in summary["runtime_actions"].values())
    assert all(value is False for value in summary["safety_flags"].values())
