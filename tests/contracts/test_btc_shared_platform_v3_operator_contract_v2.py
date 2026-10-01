"""Failure-first contract tests for the additive BTC operator V2 surface."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

import jsonschema
import pytest

from backend.app.services import btc_demo_runtime as btc_demo_runtime_service
from backend.app.services.btc_demo_runtime import _DurableOperatorOperationStore
from quant_crypto.application.btc_operator_contract_v2 import (
    ALLOWLISTED_OPERATOR_ACTIONS,
    BtcOperatorContractV2,
    OperationReadModel,
    OperatorContractError,
    authorize_operator_action,
    build_operator_contract_v2,
    canonical_request_digest,
    project_operator_contract_v2,
    validate_idempotency_key,
)
from quant_crypto.application.btc_demo_start_attempt import START_ATTEMPT_SCHEMA_VERSION
from quant_crypto.application.btc_strategy_registry import btc_strategy_registry
from quant_crypto.oms.okx_demo_paper_runtime import (
    OKX_DEMO_APPROVED_PROTECTION_POLICY,
    OKX_DEMO_PAPER_AUTHORIZATION_TICKET,
    OKX_DEMO_PAPER_CONFIRMATION,
    OKX_DEMO_PAPER_CONTRACTS,
    OKX_DEMO_PAPER_MAX_NET_CONTRACTS,
    OKX_DEMO_PAPER_MAX_NOTIONAL_USDT,
    OKX_DEMO_PAPER_ORDER_TAG,
    OkxDemoPaperStartRequest,
)


HEAD = "a" * 40
DIGEST = "b" * 64
AS_OF = "2026-08-23T00:00:00Z"
REPO_ROOT = Path(__file__).resolve().parents[2]


def _status(**overrides):
    value = {
        "source_head": HEAD,
        "state_digest": DIGEST,
        "state_revision": 7,
        "as_of_utc": AS_OF,
        "runtime_identity": "demo-run-7",
        "runtime": {
            "run_id": "demo-run-7",
            "status": "stopped",
            "active": False,
            "opening_allowed": False,
            "cancel_only": False,
            "blockers": [],
        },
        "start_capability": {"ready": True, "blockers": []},
        "safety": {
            "promotion_eligible": False,
            "paper": False,
            "live": False,
            "private": False,
            "order": False,
            "real_order": False,
            "transfer": False,
            "withdraw": False,
        },
    }
    for key, value_override in overrides.items():
        value[key] = value_override
    return value


def test_base_identity_and_action_order_are_explicit():
    contract = build_operator_contract_v2(_status())
    assert contract is not None
    assert tuple(row.action for row in contract.actions) == ALLOWLISTED_OPERATOR_ACTIONS
    assert contract.action_map["authoritative_preflight_start"].allowed is True
    assert contract.action_map["stop_keep_position"].allowed is False
    assert all(not flag for flag in contract.to_dict()["safety_flags"].values())


def test_python311_default_safety_flags_are_isolated_frozen_and_fail_closed():
    first = build_operator_contract_v2(_status())
    second = build_operator_contract_v2(_status())
    assert first is not None and second is not None
    assert first.safety_flags == second.safety_flags
    assert first.safety_flags is not second.safety_flags
    assert all(value is False for value in first.safety_flags.values())
    with pytest.raises(TypeError):
        first.safety_flags["live"] = True

    operation_first = OperationReadModel(
        operation_id="op-1",
        action="authoritative_preflight_start",
        request_digest=DIGEST,
        state="queued",
        phase="requested",
        blocker_codes=(),
        created_at_utc=AS_OF,
        updated_at_utc=AS_OF,
        state_revision=1,
    )
    operation_second = OperationReadModel(
        operation_id="op-2",
        action="authoritative_preflight_start",
        request_digest=DIGEST,
        state="queued",
        phase="requested",
        blocker_codes=(),
        created_at_utc=AS_OF,
        updated_at_utc=AS_OF,
        state_revision=1,
    )
    assert operation_first.safety_flags is not operation_second.safety_flags
    assert all(value is False for value in operation_first.safety_flags.values())
    with pytest.raises(TypeError):
        operation_first.safety_flags["paper"] = True

    with pytest.raises(ValueError, match="safety_flag"):
        BtcOperatorContractV2(
            schema_version=first.schema_version,
            source=first.source,
            runtime_identity=first.runtime_identity,
            source_head=first.source_head,
            state_revision=first.state_revision,
            state_digest=first.state_digest,
            as_of_utc=first.as_of_utc,
            actions=first.actions,
            safety_flags={"live": True},
        )


@pytest.mark.parametrize(
    "field,value,blocker",
    [
        ("source_head", "not-a-head", "source_head_invalid"),
        ("state_digest", "bad", "state_digest_invalid"),
        ("runtime_identity", "", "runtime_identity_missing"),
        ("as_of_utc", "not-time", "as_of_utc_invalid"),
        ("state_revision", -1, "state_revision_invalid"),
    ],
)
def test_missing_or_tampered_identity_is_structured_and_denied(field, value, blocker):
    status = _status(**{field: value})
    if field == "runtime_identity":
        status["runtime"]["run_id"] = ""
    projection = project_operator_contract_v2(status)
    assert projection["allowed"] is False
    assert projection["execution_permission"] is False
    assert blocker in projection["blockers"]
    assert all(row["allowed"] is False for row in projection["actions"])


def test_unknown_action_and_missing_key_fail_before_dispatch():
    with pytest.raises(OperatorContractError) as unknown:
        authorize_operator_action(_status(), "open_position", idempotency_key="valid-key-1")
    assert unknown.value.code == "operator_action_not_allowlisted"
    with pytest.raises(OperatorContractError) as missing:
        authorize_operator_action(_status(), "authoritative_preflight_start", idempotency_key=None)
    assert missing.value.code == "idempotency_key_required"


def test_idempotency_key_is_allowlisted_and_digest_excludes_secret():
    assert validate_idempotency_key("operator-key-001")
    assert not validate_idempotency_key("")
    first = canonical_request_digest({"strategy": "x", "secret": "one"})
    second = canonical_request_digest({"strategy": "x", "secret": "two"})
    assert first == second
    assert canonical_request_digest({"key": "business-a"}) != canonical_request_digest(
        {"key": "business-b"}
    )
    for field in ("api_key", "token", "secret", "passphrase"):
        assert canonical_request_digest({field: "one"}) == canonical_request_digest(
            {field: "two"}
        )


def test_active_runtime_authorizes_only_stop_family():
    status = _status(
        runtime={
            "run_id": "demo-run-7",
            "status": "running",
            "active": True,
            "opening_allowed": True,
            "cancel_only": False,
            "blockers": [],
        }
    )
    contract = build_operator_contract_v2(status)
    assert contract is not None
    assert contract.action_map["authoritative_preflight_start"].allowed is False
    assert contract.action_map["stop_keep_position"].allowed is True
    assert contract.action_map["stop_and_flatten"].allowed is False
    protected = build_operator_contract_v2(
        _status(
            runtime=status["runtime"],
            protective_capabilities={
                "stop_and_flatten": {
                    "allowed": True,
                    "reduction_proof": True,
                    "effect": "decrease",
                }
            },
        )
    )
    assert protected is not None
    assert protected.action_map["stop_and_flatten"].allowed is True


def test_emergency_needs_explicit_authoritative_capability():
    denied = build_operator_contract_v2(_status())
    assert denied is not None
    assert denied.action_map["emergency_reduce_only_exit"].allowed is False
    allowed = build_operator_contract_v2(
        _status(
            emergency_reduce_only_exit_allowed=True,
            emergency_reduce_only_exit_reduction_proof=True,
            emergency_reduce_only_exit_effect="decrease",
        )
    )
    assert allowed is not None
    assert allowed.action_map["emergency_reduce_only_exit"].allowed is True


@pytest.mark.parametrize(
    "capability, blocker",
    [
        (
            {"allowed": True, "reduction_proof": True},
            "reduction_effect_unknown",
        ),
        (
            {"allowed": True, "effect": "decrease"},
            "reduction_proof_missing",
        ),
    ],
)
def test_protective_authority_rejects_unknown_effect_or_missing_reduction_proof(
    capability,
    blocker,
):
    contract = build_operator_contract_v2(
        _status(protective_capabilities={"stop_and_flatten": capability})
    )
    assert contract is not None
    record = contract.action_map["stop_and_flatten"]
    assert record.allowed is False
    assert blocker in record.blocker_codes


def test_nested_safety_projection_is_copy_not_shared():
    projection = project_operator_contract_v2(_status())
    projection["safety_flags"]["live"] = True
    again = project_operator_contract_v2(_status())
    assert again["safety_flags"]["live"] is False


def test_durable_operation_store_deduplicates_and_rejects_mismatch(tmp_path: Path):
    store = _DurableOperatorOperationStore(tmp_path)
    first, replay = store.begin(
        action="authoritative_preflight_start",
        payload={"instrument": "BTC-USDT-SWAP"},
        idempotency_key="operator-key-001",
    )
    assert not replay
    second, replay = store.begin(
        action="authoritative_preflight_start",
        payload={"instrument": "BTC-USDT-SWAP"},
        idempotency_key="operator-key-001",
    )
    assert replay and second.operation_id == first.operation_id
    with pytest.raises(OperatorContractError) as mismatch:
        store.begin(
            action="stop_keep_position",
            payload={"instrument": "BTC-USDT-SWAP"},
            idempotency_key="operator-key-001",
        )
    assert mismatch.value.code == "idempotency_key_reuse_mismatch"
    store.begin(
        action="authoritative_preflight_start",
        payload={"key": "business-a"},
        idempotency_key="operator-key-business",
    )
    with pytest.raises(OperatorContractError) as business_key_mismatch:
        store.begin(
            action="authoritative_preflight_start",
            payload={"key": "business-b"},
            idempotency_key="operator-key-business",
        )
    assert business_key_mismatch.value.status_code == 409
    assert business_key_mismatch.value.code == "idempotency_key_reuse_mismatch"


def test_concurrent_claim_executes_one_operation(tmp_path: Path):
    store = _DurableOperatorOperationStore(tmp_path)

    def claim():
        return store.begin(
            action="authoritative_preflight_start",
            payload={"instrument": "BTC-USDT-SWAP"},
            idempotency_key="operator-key-002",
        )

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(lambda _: claim(), range(4)))
    assert len({item[0].operation_id for item in results}) == 1
    assert sum(1 for _, replay in results if not replay) == 1


def test_concurrent_claim_across_independent_store_instances(tmp_path: Path):
    stores = [_DurableOperatorOperationStore(tmp_path) for _ in range(2)]

    def claim(index: int):
        return stores[index % 2].begin(
            action="authoritative_preflight_start",
            payload={"instrument": "BTC-USDT-SWAP"},
            idempotency_key="operator-key-cross-instance",
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(lambda index: claim(index), range(8)))
    assert len({item[0].operation_id for item in results}) == 1
    assert sum(1 for _, replay in results if not replay) == 1


def test_operation_transitions_are_monotonic(tmp_path: Path):
    store = _DurableOperatorOperationStore(tmp_path)
    operation, _ = store.begin(
        action="authoritative_preflight_start",
        payload={},
        idempotency_key="operator-key-003",
    )
    completed = store.transition(
        operation.operation_id,
        state="succeeded",
        phase="completed",
        result_present=True,
    )
    replay = store.transition(
        operation.operation_id,
        state="running",
        phase="late",
    )
    assert completed.state == replay.state == "succeeded"
    assert completed.state_revision == replay.state_revision


def test_terminal_operation_acknowledgement_is_persisted_and_idempotent(tmp_path: Path):
    store = _DurableOperatorOperationStore(tmp_path)
    operation, _ = store.begin(
        action="authoritative_preflight_start",
        payload={"instrument": "BTC-USDT-SWAP"},
        idempotency_key="operator-key-terminal-ack",
    )
    terminal = store.transition(
        operation.operation_id,
        state="failed",
        phase="dispatch_failed",
        blockers=("btc_demo_runtime_output_root_not_configured",),
    )

    discovered = store.latest_unacknowledged()
    assert discovered is not None
    assert discovered.operation_id == terminal.operation_id
    assert discovered.acknowledged is False

    acknowledged = store.acknowledge(
        operation.operation_id,
        action="authoritative_preflight_start",
        expected_state_revision=terminal.state_revision,
    )
    assert acknowledged.acknowledged is True
    assert acknowledged.acknowledged_at_utc
    assert acknowledged.state_revision == terminal.state_revision + 1
    assert store.latest_unacknowledged() is None

    replay = store.acknowledge(
        operation.operation_id,
        action="authoritative_preflight_start",
        expected_state_revision=terminal.state_revision,
    )
    assert replay.to_dict() == acknowledged.to_dict()


def test_legacy_terminal_row_without_ack_fields_is_recovered_as_unacknowledged(
    tmp_path: Path,
):
    store = _DurableOperatorOperationStore(tmp_path)
    operation, _ = store.begin(
        action="authoritative_preflight_start",
        payload={},
        idempotency_key="operator-key-legacy-terminal",
    )
    store.transition(
        operation.operation_id,
        state="failed",
        phase="failed",
        blockers=("operator_action_failed",),
    )
    path = tmp_path / "operator-contract-v2" / "operations.json"
    rows = json.loads(path.read_text(encoding="utf-8"))
    rows[0].pop("acknowledged")
    rows[0].pop("acknowledged_at_utc")
    path.write_text(json.dumps(rows), encoding="utf-8")

    recovered = _DurableOperatorOperationStore(tmp_path).latest_unacknowledged()
    assert recovered is not None
    assert recovered.operation_id == operation.operation_id
    assert recovered.acknowledged is False


def test_operation_acknowledgement_rejects_pending_or_stale_identity(tmp_path: Path):
    store = _DurableOperatorOperationStore(tmp_path)
    operation, _ = store.begin(
        action="authoritative_preflight_start",
        payload={},
        idempotency_key="operator-key-terminal-ack-reject",
    )
    with pytest.raises(OperatorContractError) as pending:
        store.acknowledge(
            operation.operation_id,
            action="authoritative_preflight_start",
            expected_state_revision=operation.state_revision,
        )
    assert pending.value.code == "operator_operation_not_terminal"

    terminal = store.transition(
        operation.operation_id,
        state="blocked",
        phase="blocked",
        blockers=("preflight_denied",),
    )
    with pytest.raises(OperatorContractError) as stale:
        store.acknowledge(
            operation.operation_id,
            action="authoritative_preflight_start",
            expected_state_revision=terminal.state_revision + 1,
        )
    assert stale.value.status_code == 409
    assert stale.value.code == "operator_operation_acknowledgement_conflict"


def test_operation_model_rejects_enabled_safety_flag():
    with pytest.raises(ValueError, match="safety_flag"):
        OperationReadModel(
            operation_id="op",
            action="authoritative_preflight_start",
            request_digest=DIGEST,
            state="queued",
            phase="requested",
            blocker_codes=(),
            created_at_utc=AS_OF,
            updated_at_utc=AS_OF,
            state_revision=1,
            safety_flags={"live": True},
        )


def test_unacknowledged_operation_is_discoverable_and_blocks_only_same_action(
    tmp_path: Path,
):
    service = object.__new__(btc_demo_runtime_service.BtcDemoRuntimeService)
    service.status = lambda: _status()
    service._operator_operation_store = _DurableOperatorOperationStore(tmp_path)
    operation, _ = service._operator_operation_store.begin(
        action="authoritative_preflight_start",
        payload={"mode": "demo"},
        idempotency_key="operator-key-contract-terminal",
    )
    terminal = service._operator_operation_store.transition(
        operation.operation_id,
        state="failed",
        phase="dispatch_failed",
        blockers=("btc_demo_runtime_output_root_not_configured",),
    )

    projection = service.operator_contract_v2()
    assert projection["operation"]["operation_id"] == terminal.operation_id
    assert projection["operation"]["acknowledged"] is False
    action_map = {row["action"]: row for row in projection["actions"]}
    assert action_map["authoritative_preflight_start"]["allowed"] is False
    assert "operator_terminal_operation_unacknowledged" in action_map[
        "authoritative_preflight_start"
    ]["blocker_codes"]
    assert action_map["refresh_account_snapshot"]["allowed"] is True

    snapshot = service._operator_contract_status()
    replay = service.execute_operator_action_v2(
        "authoritative_preflight_start",
        {
            "mode": "demo",
            "expected_runtime_identity": snapshot["runtime_identity"],
            "expected_state_revision": snapshot["state_revision"],
            "expected_state_digest": snapshot["state_digest"],
        },
        idempotency_key="operator-key-contract-terminal",
    )
    assert replay["operation_id"] == terminal.operation_id
    assert replay["state"] == "failed"
    assert replay["idempotent_replay"] is True

    with pytest.raises(OperatorContractError) as new_attempt:
        service.execute_operator_action_v2(
            "authoritative_preflight_start",
            {
                "mode": "demo",
                "expected_runtime_identity": snapshot["runtime_identity"],
                "expected_state_revision": snapshot["state_revision"],
                "expected_state_digest": snapshot["state_digest"],
            },
            idempotency_key="operator-key-contract-terminal-new",
        )
    assert "operator_terminal_operation_unacknowledged" in new_attempt.value.blockers

    acknowledged = service.acknowledge_operator_operation_v2(
        terminal.operation_id,
        {
            "action": "authoritative_preflight_start",
            "expected_state_revision": terminal.state_revision,
        },
    )
    assert acknowledged["acknowledged"] is True
    refreshed = service.operator_contract_v2()
    assert refreshed["operation"] is None
    refreshed_actions = {row["action"]: row for row in refreshed["actions"]}
    assert refreshed_actions["authoritative_preflight_start"]["allowed"] is True


def test_tampered_durable_operation_is_fail_closed(tmp_path: Path):
    store = _DurableOperatorOperationStore(tmp_path)
    (tmp_path / "operator-contract-v2").mkdir(parents=True)
    (tmp_path / "operator-contract-v2" / "operations.json").write_text(
        "[{\"operation_id\":\"bad\",\"action\":\"open_position\"}]",
        encoding="utf-8",
    )
    with pytest.raises(OperatorContractError) as error:
        store.get("bad")
    assert error.value.code == "operator_operation_store_invalid"


def test_lock_unavailable_is_structured_423(monkeypatch, tmp_path: Path):
    def unavailable(self, owner_id, fence_token):
        raise PermissionError("lock denied")

    monkeypatch.setattr(
        btc_demo_runtime_service.FileGuardianLatchStore,
        "acquire",
        unavailable,
    )
    store = _DurableOperatorOperationStore(tmp_path)
    with pytest.raises(OperatorContractError) as error:
        store.begin(
            action="authoritative_preflight_start",
            payload={},
            idempotency_key="operator-key-lock-fail",
        )
    assert error.value.status_code == 423
    assert error.value.code == "operator_operation_lock_unavailable"


def test_backend_adapter_does_not_fabricate_identity_time_or_revision(monkeypatch):
    service = object.__new__(btc_demo_runtime_service.BtcDemoRuntimeService)
    service.status = lambda: {
        "runtime": {
            "status": "stopped",
            "active": False,
            "blockers": ["guardian_latch_tripped"],
        },
        "events": None,
    }
    monkeypatch.setattr(
        btc_demo_runtime_service,
        "_current_repo_head",
        lambda repo_root: "a" * 40,
    )
    status = service._operator_contract_status()
    projection = project_operator_contract_v2(status)
    assert projection["allowed"] is False
    assert "runtime_identity_missing" in projection["blockers"]
    assert "as_of_utc_invalid" in projection["blockers"]
    assert "state_revision_invalid" in projection["blockers"]


def test_backend_missing_identity_blocks_get_and_post_before_controller(
    monkeypatch,
    tmp_path: Path,
):
    """The adapter must expose structured GET blockers and never dispatch POST."""

    service = object.__new__(btc_demo_runtime_service.BtcDemoRuntimeService)
    service.status = lambda: {
        "runtime": {
            "status": "stopped",
            "active": False,
            "blockers": ["guardian_latch_tripped"],
        },
        "events": None,
    }
    service._operator_operation_store = _DurableOperatorOperationStore(tmp_path)
    dispatch_calls: list[tuple[str, Mapping[str, object]]] = []

    def dispatch(action, payload, *, idempotency_key):
        dispatch_calls.append((action, payload))
        return {"accepted": True}

    service._dispatch_operator_action_v2 = dispatch
    monkeypatch.setattr(
        btc_demo_runtime_service,
        "_current_repo_head",
        lambda repo_root: "a" * 40,
    )

    projection = service.operator_contract_v2()
    assert projection["allowed"] is False
    assert set(("runtime_identity_missing", "as_of_utc_invalid", "state_revision_invalid")) <= set(
        projection["blockers"]
    )

    with pytest.raises(OperatorContractError) as error:
        service.execute_operator_action_v2(
            "authoritative_preflight_start",
            {},
            idempotency_key="operator-key-missing-identity",
        )
    assert error.value.status_code == 409
    assert error.value.code == "operator_stale_snapshot"
    assert dispatch_calls == []


def test_execute_blocked_claim_is_terminal_and_replay_skips_dispatch(tmp_path: Path):
    service = object.__new__(btc_demo_runtime_service.BtcDemoRuntimeService)
    state = _status(
        runtime={
            "run_id": "demo-run-7",
            "status": "running",
            "active": True,
            "opening_allowed": True,
            "cancel_only": False,
            "blockers": [],
        }
    )
    service.status = lambda: state
    service._operator_operation_store = _DurableOperatorOperationStore(tmp_path)
    dispatch_calls: list[tuple[str, Mapping[str, object]]] = []

    def dispatch(action, payload, *, idempotency_key):
        dispatch_calls.append((action, payload))
        return {"accepted": True}

    service._dispatch_operator_action_v2 = dispatch
    blocked_payload = {
        "mode": "demo",
        **{
            "expected_runtime_identity": service._operator_contract_status()["runtime_identity"],
            "expected_state_revision": service._operator_contract_status()["state_revision"],
            "expected_state_digest": service._operator_contract_status()["state_digest"],
        },
    }
    with pytest.raises(OperatorContractError) as blocked:
        service.execute_operator_action_v2(
            "authoritative_preflight_start",
            blocked_payload,
            idempotency_key="operator-key-blocked-replay",
        )
    assert blocked.value.status_code == 423
    assert blocked.value.code == "operator_action_blocked"

    state["runtime"] = {
        "run_id": "demo-run-7",
        "status": "stopped",
        "active": False,
        "opening_allowed": False,
        "cancel_only": False,
        "blockers": [],
    }
    replay_snapshot = service._operator_contract_status()
    blocked_payload.update(
        {
            "expected_runtime_identity": replay_snapshot["runtime_identity"],
            "expected_state_revision": replay_snapshot["state_revision"],
            "expected_state_digest": replay_snapshot["state_digest"],
        }
    )
    replay = service.execute_operator_action_v2(
        "authoritative_preflight_start",
        blocked_payload,
        idempotency_key="operator-key-blocked-replay",
    )
    assert replay["state"] == "succeeded"
    assert replay["replayed"] is False
    assert replay["idempotent_replay"] is False
    assert replay["result_present"] is True
    assert len(dispatch_calls) == 1


def test_execute_success_replay_preserves_operation_fields_and_result_marker(
    tmp_path: Path,
):
    service = object.__new__(btc_demo_runtime_service.BtcDemoRuntimeService)
    service.status = lambda: _status()
    service._operator_operation_store = _DurableOperatorOperationStore(tmp_path)
    dispatch_calls: list[tuple[str, Mapping[str, object]]] = []

    def dispatch(action, payload, *, idempotency_key):
        dispatch_calls.append((action, payload))
        return {"accepted": True, "non_persistent_detail": "ignored"}

    service._dispatch_operator_action_v2 = dispatch
    contract_snapshot = service._operator_contract_status()
    payload = {
        "mode": "demo",
        "key": "business-a",
        "expected_runtime_identity": contract_snapshot["runtime_identity"],
        "expected_state_revision": contract_snapshot["state_revision"],
        "expected_state_digest": contract_snapshot["state_digest"],
    }
    first = service.execute_operator_action_v2(
        "authoritative_preflight_start",
        payload,
        idempotency_key="operator-key-success-replay",
    )
    replay = service.execute_operator_action_v2(
        "authoritative_preflight_start",
        payload,
        idempotency_key="operator-key-success-replay",
    )
    operation_fields = (
        "schema_version",
        "operation_id",
        "action",
        "request_digest",
        "state",
        "phase",
        "blocker_codes",
        "created_at_utc",
        "updated_at_utc",
        "state_revision",
        "result_present",
        "retryable",
        "acknowledged",
        "acknowledged_at_utc",
        "safety_flags",
    )
    assert all(first[field] == replay[field] for field in operation_fields)
    assert first["state"] == replay["state"] == "succeeded"
    assert first["result_present"] is True
    assert replay["result_present"] is True
    assert first["replayed"] is False
    assert first["idempotent_replay"] is False
    assert replay["replayed"] is True
    assert replay["idempotent_replay"] is True
    assert len(dispatch_calls) == 1
    with pytest.raises(OperatorContractError) as mismatch:
        service.execute_operator_action_v2(
            "authoritative_preflight_start",
            {
                "mode": "demo",
                "key": "business-b",
                "expected_runtime_identity": contract_snapshot["runtime_identity"],
                "expected_state_revision": contract_snapshot["state_revision"],
                "expected_state_digest": contract_snapshot["state_digest"],
            },
            idempotency_key="operator-key-success-replay",
        )
    assert mismatch.value.status_code == 409
    assert mismatch.value.code == "idempotency_key_reuse_mismatch"
    assert len(dispatch_calls) == 1


@pytest.mark.parametrize(
    "runtime_error,expected_blockers",
    [
        (
            "btc_demo_runtime_output_root_not_configured; "
            "okx_demo_guardian_supervisor_unavailable",
            (
                "btc_demo_runtime_output_root_not_configured",
                "okx_demo_guardian_supervisor_unavailable",
            ),
        ),
        ("C:\\private\\unexpected failure detail", ("operator_action_failed",)),
    ],
)
def test_dispatch_failure_persists_only_safe_machine_codes(
    tmp_path: Path,
    runtime_error: str,
    expected_blockers: tuple[str, ...],
):
    service = object.__new__(btc_demo_runtime_service.BtcDemoRuntimeService)
    service.status = lambda: _status()
    service._operator_operation_store = _DurableOperatorOperationStore(tmp_path)

    def fail_dispatch(action, payload, *, idempotency_key):
        raise RuntimeError(runtime_error)

    service._dispatch_operator_action_v2 = fail_dispatch
    snapshot = service._operator_contract_status()
    with pytest.raises(OperatorContractError) as error:
        service.execute_operator_action_v2(
            "authoritative_preflight_start",
            {
                "mode": "demo",
                "expected_runtime_identity": snapshot["runtime_identity"],
                "expected_state_revision": snapshot["state_revision"],
                "expected_state_digest": snapshot["state_digest"],
            },
            idempotency_key=f"operator-key-safe-error-{len(runtime_error)}",
        )

    assert error.value.blockers == expected_blockers
    persisted = service._operator_operation_store.latest_unacknowledged()
    assert persisted is not None
    assert persisted.phase == "dispatch_failed"
    assert persisted.blocker_codes == expected_blockers
    assert runtime_error not in persisted.to_dict().values()


def test_snapshot_fence_is_required_and_never_reaches_controller(tmp_path: Path):
    service = object.__new__(btc_demo_runtime_service.BtcDemoRuntimeService)
    service.status = lambda: _status()
    service._operator_operation_store = _DurableOperatorOperationStore(tmp_path)
    dispatch_calls: list[Mapping[str, object]] = []
    service._dispatch_operator_action_v2 = lambda action, payload, *, idempotency_key: dispatch_calls.append(dict(payload)) or {"accepted": True}
    snapshot = service._operator_contract_status()
    payload = {
        "mode": "demo",
        "expected_runtime_identity": snapshot["runtime_identity"],
        "expected_state_revision": snapshot["state_revision"],
        "expected_state_digest": snapshot["state_digest"],
    }
    result = service.execute_operator_action_v2(
        "authoritative_preflight_start",
        payload,
        idempotency_key="snapshot-fence-key-001",
    )
    assert result["state"] == "succeeded"
    assert len(dispatch_calls) == 1
    assert dispatch_calls[0]["mode"] == "demo"
    assert dispatch_calls[0]["authorization_ticket"] == OKX_DEMO_PAPER_AUTHORIZATION_TICKET
    assert dispatch_calls[0]["parent_operation_id"]

    stale = dict(payload)
    stale["expected_state_digest"] = "c" * 64
    with pytest.raises(OperatorContractError) as error:
        service.execute_operator_action_v2(
            "authoritative_preflight_start",
            stale,
            idempotency_key="snapshot-fence-key-002",
        )
    assert error.value.status_code == 409
    assert error.value.code == "operator_stale_snapshot"
    assert len(dispatch_calls) == 1

    duplicate_mismatch = dict(payload)
    duplicate_mismatch["snapshot_fence"] = {
        "runtime_identity": snapshot["runtime_identity"],
        "state_revision": snapshot["state_revision"],
        "state_digest": "d" * 64,
    }
    with pytest.raises(OperatorContractError) as duplicate_error:
        service.execute_operator_action_v2(
            "authoritative_preflight_start",
            duplicate_mismatch,
            idempotency_key="snapshot-fence-key-003",
        )
    assert duplicate_error.value.status_code == 409
    assert duplicate_error.value.code == "operator_stale_snapshot"
    assert len(dispatch_calls) == 1


def test_execute_operator_action_uses_one_fenced_status_projection(tmp_path: Path):
    service = object.__new__(btc_demo_runtime_service.BtcDemoRuntimeService)
    state = _status()
    reads = 0

    def read_status():
        nonlocal reads
        reads += 1
        if reads > 1:
            state["runtime"] = {
                "run_id": "demo-run-7",
                "status": "running",
                "active": True,
                "opening_allowed": True,
                "cancel_only": False,
                "blockers": ["state_changed_after_fence"],
            }
        return state

    service.status = read_status
    service._operator_operation_store = _DurableOperatorOperationStore(tmp_path)
    dispatch_calls: list[Mapping[str, object]] = []
    service._dispatch_operator_action_v2 = lambda action, payload, *, idempotency_key: dispatch_calls.append(dict(payload)) or {"accepted": True}

    snapshot = service._operator_contract_status()
    reads = 0
    payload = {
        "mode": "demo",
        "expected_runtime_identity": snapshot["runtime_identity"],
        "expected_state_revision": snapshot["state_revision"],
        "expected_state_digest": snapshot["state_digest"],
    }
    result = service.execute_operator_action_v2(
        "authoritative_preflight_start",
        payload,
        idempotency_key="single-projection-race-001",
    )
    assert result["state"] == "succeeded"
    assert reads == 1
    assert len(dispatch_calls) == 1
    assert dispatch_calls[0]["mode"] == "demo"
    assert dispatch_calls[0]["authorization_ticket"] == OKX_DEMO_PAPER_AUTHORIZATION_TICKET
    assert dispatch_calls[0]["parent_operation_id"]

def test_guardian_or_ledger_blocker_does_not_disable_protective_actions():
    status = _status(
        runtime={
            "run_id": "demo-run-7",
            "status": "running",
            "active": True,
            "opening_allowed": False,
            "cancel_only": False,
            "blockers": ["guardian_latch_tripped"],
        },
        risk_control={"mode": "FROZEN_UNKNOWN", "blockers": ["guardian_latch_tripped"]},
        private_ws={"status": "failed", "blockers": ["private_ws_fault"]},
        ledger_reconciliation={"status": "mismatch", "blockers": ["ledger_mismatch"]},
        protective_capabilities={
            "stop_and_flatten": {
                "allowed": True,
                "reduction_proof": True,
                "effect": "decrease",
            },
            "emergency_reduce_only_exit": {
                "allowed": True,
                "reduction_proof": True,
                "effect": "decrease",
            },
        },
    )
    contract = build_operator_contract_v2(status)
    assert contract is not None
    assert contract.action_map["authoritative_preflight_start"].allowed is False
    assert contract.action_map["refresh_account_snapshot"].allowed is True
    assert contract.action_map["enter_cancel_only"].allowed is True
    assert contract.action_map["stop_and_flatten"].allowed is True
    assert contract.action_map["emergency_reduce_only_exit"].allowed is True


def test_cancel_only_is_stable_and_refresh_remains_available():
    contract = build_operator_contract_v2(
        _status(
            runtime={
                "run_id": "demo-run-7",
                "status": "running",
                "active": True,
                "opening_allowed": False,
                "cancel_only": True,
                "blockers": ["guardian_latch_tripped"],
            }
        )
    )
    assert contract is not None
    assert contract.action_map["refresh_account_snapshot"].allowed is True
    assert contract.action_map["enter_cancel_only"].allowed is False
    assert "already_cancel_only" in contract.action_map["enter_cancel_only"].blocker_codes


def _unclean_restart_recovery_status(*, with_timestamp: bool = True) -> dict:
    """A stopped, frozen runtime whose only current timestamp is durable operation state."""

    operation = {
        "state": "completed",
        "phase": "running",
        "revision": 12,
        "source_head": "d" * 40,
        "updated_at_utc": "2026-08-22T09:20:52.350193+08:00",
    }
    if not with_timestamp:
        operation.pop("updated_at_utc")
    return {
        "runtime_identity": "ee50-restart-recovery",
        "runtime": {
            "status": "unclean_restart_fail_closed",
            "active": False,
            "opening_allowed": False,
            "cancel_only": True,
            "source_head": "d" * 40,
            "blockers": ["previous_runtime_not_cleanly_stopped"],
        },
        "start_operation": operation,
        "start_capability": {"ready": True, "blockers": []},
        "risk_control": {
            "mode": "FROZEN_UNKNOWN",
            "reason": "runtime_not_started",
            "blockers": ["risk_state_requires_recheck"],
        },
        "private_ws": {
            "status": "not_started",
            "connected": False,
            "listener_alive": False,
            "blockers": ["private_ws_requires_recheck"],
        },
        "ledger_reconciliation": {
            "status": "mismatch",
            "current_state_exchange_snapshot_match": False,
            "funding_cashflow_reconciled": False,
            "blockers": ["ledger_requires_recheck"],
        },
        "exchange": {
            "captured_at_utc": "",
            "positions": [],
            "pending_orders": [],
            "pending_algo_orders": [],
        },
        "safety": {name: False for name in (
            "promotion_eligible", "paper", "live", "private", "order",
            "real_order", "transfer", "withdraw",
        )},
    }


def test_restart_recovery_adapter_uses_current_head_and_durable_operation_timestamp(monkeypatch):
    service = object.__new__(btc_demo_runtime_service.BtcDemoRuntimeService)
    service.status = lambda: _unclean_restart_recovery_status()
    monkeypatch.setattr(btc_demo_runtime_service, "_current_repo_head", lambda repo_root: "a" * 40)

    enriched = service._operator_contract_status()
    projection = project_operator_contract_v2(enriched)

    assert enriched["source_head"] == "a" * 40
    assert enriched["as_of_utc"] == "2026-08-22T09:20:52.350193+08:00"
    assert projection["source_head"] == "a" * 40
    assert projection["as_of_utc"] == "2026-08-22T01:20:52.350193Z"
    assert projection["actions"][0]["allowed"] is True
    assert projection["actions"][0]["execution_permission"] is True


def test_restart_recovery_without_any_authoritative_timestamp_stays_blocked(monkeypatch):
    service = object.__new__(btc_demo_runtime_service.BtcDemoRuntimeService)
    service.status = lambda: _unclean_restart_recovery_status(with_timestamp=False)
    monkeypatch.setattr(btc_demo_runtime_service, "_current_repo_head", lambda repo_root: "a" * 40)

    projection = project_operator_contract_v2(service._operator_contract_status())

    assert projection["allowed"] is False
    assert "as_of_utc_invalid" in projection["blockers"]
    assert all(row["allowed"] is False for row in projection["actions"])


def test_restart_recovery_preflight_admission_ignores_stale_runtime_safety_gates():
    status = _unclean_restart_recovery_status()
    status.update({
        "source_head": "a" * 40,
        "state_digest": "b" * 64,
        "state_revision": 12,
        "as_of_utc": "2026-08-22T01:20:52.350193Z",
    })

    contract = build_operator_contract_v2(status)

    assert contract is not None
    assert contract.action_map["authoritative_preflight_start"].allowed is True
    assert "risk_state_requires_recheck" in status["risk_control"]["blockers"]
    assert "private_ws_requires_recheck" in status["private_ws"]["blockers"]
    assert "ledger_requires_recheck" in status["ledger_reconciliation"]["blockers"]


def test_restart_recovery_rejects_ready_capability_with_blockers():
    status = _unclean_restart_recovery_status()
    status.update({
        "source_head": "a" * 40,
        "state_digest": "b" * 64,
        "state_revision": 12,
        "as_of_utc": "2026-08-22T01:20:52.350193Z",
    })
    status["start_capability"] = {
        "ready": True,
        "blockers": ["capability_snapshot_contradictory"],
    }

    contract = build_operator_contract_v2(status)

    assert contract is not None
    record = contract.action_map["authoritative_preflight_start"]
    assert record.allowed is False
    assert "capability_snapshot_contradictory" in record.blocker_codes


def test_restart_recovery_rejects_invalid_capability_blocker_shape():
    status = _unclean_restart_recovery_status()
    status.update({
        "source_head": "a" * 40,
        "state_digest": "b" * 64,
        "state_revision": 12,
        "as_of_utc": "2026-08-22T01:20:52.350193Z",
    })
    status["start_capability"] = {
        "ready": True,
        "blockers": {"unexpected": "shape"},
    }

    contract = build_operator_contract_v2(status)

    assert contract is not None
    record = contract.action_map["authoritative_preflight_start"]
    assert record.allowed is False
    assert "blocker_code_invalid" in record.blocker_codes


@pytest.mark.parametrize("operation_state", ["queued", "running"])
def test_restart_recovery_blocks_queued_or_running_start_operation(operation_state):
    status = _unclean_restart_recovery_status()
    status.update({
        "source_head": "a" * 40,
        "state_digest": "b" * 64,
        "state_revision": 12,
        "as_of_utc": "2026-08-22T01:20:52.350193Z",
    })
    status["start_operation"]["state"] = operation_state

    contract = build_operator_contract_v2(status)

    assert contract is not None
    assert contract.action_map["authoritative_preflight_start"].allowed is False


def test_restart_recovery_dispatches_existing_start_operation_once(monkeypatch, tmp_path: Path):
    service = object.__new__(btc_demo_runtime_service.BtcDemoRuntimeService)
    service.status = lambda: _unclean_restart_recovery_status()
    service._operator_operation_store = _DurableOperatorOperationStore(tmp_path)
    monkeypatch.setattr(btc_demo_runtime_service, "_current_repo_head", lambda repo_root: "a" * 40)
    dispatch_calls: list[tuple[dict, str]] = []

    def start_operation(payload, *, idempotency_key):
        dispatch_calls.append((dict(payload), str(idempotency_key)))
        return {"accepted": True}

    service.start_operation = start_operation
    snapshot = service._operator_contract_status()
    result = service.execute_operator_action_v2(
        "authoritative_preflight_start",
        {
            **_authoritative_start_intent(),
            "mode": "demo",
            "operator_action": "authoritative_preflight_start",
            "expected_runtime_identity": snapshot["runtime_identity"],
            "expected_state_revision": snapshot["state_revision"],
            "expected_state_digest": snapshot["state_digest"],
        },
        idempotency_key="restart-recovery-key-001",
    )

    assert result["state"] == "succeeded"
    assert len(dispatch_calls) == 1


def _authoritative_start_intent(**overrides) -> dict:
    spec = btc_strategy_registry.list_specs()[0]
    payload = {
        "strategy_id": spec.strategy_id,
        "candidate_id": spec.candidate_id,
        "strategy_version": spec.strategy_version,
        "instrument_id": "BTC-USDT-SWAP",
        "confirmation_text": OKX_DEMO_PAPER_CONFIRMATION,
        "confirm_demo_only": True,
        "confirm_automatic_orders": True,
        "confirm_risk_limits": True,
        "confirm_cancel_only_on_error": True,
        "confirm_dedicated_demo_account": True,
    }
    payload.update(overrides)
    return payload


def test_authoritative_start_dispatch_composes_server_policy_and_overrides_client_values():
    service = object.__new__(btc_demo_runtime_service.BtcDemoRuntimeService)
    calls: list[tuple[dict, str]] = []

    def start_operation(payload, *, idempotency_key):
        calls.append((dict(payload), str(idempotency_key)))
        return {"accepted": True}

    service.start_operation = start_operation
    client_payload = _authoritative_start_intent(
        authorization_ticket="client-must-not-authorize",
        margin_mode="cross",
        order_contracts="999",
        max_net_contracts="999",
        max_notional_usdt="999999",
        dead_man_tag="clientTag",
        server_side_protection_policy={"policy_id": "client-policy"},
    )

    result = service._dispatch_operator_action_v2(
        "authoritative_preflight_start",
        client_payload,
        idempotency_key="authoritative-start-compose-001",
    )

    assert result == {"accepted": True}
    assert len(calls) == 1
    composed, key = calls[0]
    assert key == "authoritative-start-compose-001"
    assert composed["authorization_ticket"] == OKX_DEMO_PAPER_AUTHORIZATION_TICKET
    assert composed["margin_mode"] == "isolated"
    assert composed["order_contracts"] == OKX_DEMO_PAPER_CONTRACTS
    assert composed["max_net_contracts"] == OKX_DEMO_PAPER_MAX_NET_CONTRACTS
    assert composed["max_notional_usdt"] == OKX_DEMO_PAPER_MAX_NOTIONAL_USDT
    assert composed["dead_man_tag"] == OKX_DEMO_PAPER_ORDER_TAG
    assert composed["server_side_protection_policy"] == OKX_DEMO_APPROVED_PROTECTION_POLICY
    assert OkxDemoPaperStartRequest.from_mapping(composed).validate() == []
    assert client_payload["authorization_ticket"] == "client-must-not-authorize"


def test_refresh_dispatch_composes_server_owned_demo_read_command():
    service = object.__new__(btc_demo_runtime_service.BtcDemoRuntimeService)
    calls: list[dict] = []
    service.reconcile = lambda payload: calls.append(dict(payload)) or {"accepted": True}

    result = service._dispatch_operator_action_v2(
        "refresh_account_snapshot",
        {
            "confirmation_text": "client-must-not-authorize",
            "environment": "live",
            "instrument_id": "ETH-USDT-SWAP",
            "order_submission_allowed": True,
        },
        idempotency_key="refresh-server-command-001",
    )

    assert result == {"accepted": True}
    assert calls == [
        {
            "schema_version": "btc_demo_refresh_account_snapshot_command_v1",
            "environment": "demo",
            "instrument_id": "BTC-USDT-SWAP",
            "confirmation_text": OKX_DEMO_PAPER_CONFIRMATION,
            "read_scope": "account_positions_orders_ledger",
            "confirm_demo_only": True,
            "read_only": True,
            "order_submission_allowed": False,
            "safety_flags": {
                "promotion_eligible": False,
                "paper": False,
                "live": False,
                "private": False,
                "order": False,
                "real_order": False,
                "transfer": False,
                "withdraw": False,
            },
        }
    ]


def test_non_start_terminal_operation_serializes_nullable_start_attempt(tmp_path: Path):
    store = _DurableOperatorOperationStore(tmp_path)
    operation, _ = store.begin(
        action="refresh_account_snapshot",
        payload={"mode": "demo"},
        idempotency_key="refresh-null-start-attempt-001",
    )
    terminal = store.transition(
        operation.operation_id,
        state="failed",
        phase="dispatch_failed",
        blockers=("okx_demo_paper_confirmation_text_invalid",),
    )

    payload = terminal.to_dict()
    assert payload["start_attempt"] is None
    assert payload["result_present"] is True


def test_python_serializer_and_typescript_fixture_share_operation_schema():
    schema = json.loads(
        (REPO_ROOT / "schemas/btc_demo_operator_operation_v2.schema.json").read_text(
            encoding="utf-8"
        )
    )
    fixtures = json.loads(
        (REPO_ROOT / "tests/fixtures/btc_demo_operator_operation_v2.json").read_text(
            encoding="utf-8"
        )
    )
    jsonschema.Draft202012Validator.check_schema(schema)
    validator = jsonschema.Draft202012Validator(schema)

    for fixture in fixtures.values():
        model = OperationReadModel(
            operation_id=fixture["operation_id"],
            action=fixture["action"],
            request_digest=fixture["request_digest"],
            state=fixture["state"],
            phase=fixture["phase"],
            blocker_codes=tuple(fixture["blocker_codes"]),
            created_at_utc=fixture["created_at_utc"],
            updated_at_utc=fixture["updated_at_utc"],
            state_revision=fixture["state_revision"],
            result_present=fixture["result_present"],
            retryable=fixture["retryable"],
            replayed=fixture["replayed"],
            idempotent_replay=fixture["idempotent_replay"],
            acknowledged=fixture["acknowledged"],
            acknowledged_at_utc=fixture["acknowledged_at_utc"],
            safety_flags=fixture["safety_flags"],
            start_attempt=fixture["start_attempt"] or {},
        )
        serialized = model.to_dict()
        assert serialized == fixture
        validator.validate(serialized)


def test_refresh_failure_is_decodable_acknowledgeable_and_action_scoped(
    tmp_path: Path,
):
    service = object.__new__(btc_demo_runtime_service.BtcDemoRuntimeService)
    status = _status(
        start_capability={
            "ready": False,
            "blockers": ["btc_demo_authoritative_account_identity_hash_missing"],
        },
        account_identity_hash="",
    )
    status["runtime"].update(
        {"active": True, "opening_allowed": True, "cancel_only": False}
    )
    service.status = lambda: json.loads(json.dumps(status))
    service._runtime_identity = "demo-run-7"
    service._risk_profile = "stress_3x"
    service._account_identity_hash = ""
    service._operator_operation_store = _DurableOperatorOperationStore(tmp_path)
    calls: list[dict] = []
    fail_refresh = True

    def reconcile(payload):
        nonlocal fail_refresh
        calls.append(dict(payload))
        if fail_refresh:
            raise RuntimeError("fake_refresh_transport_failure")
        service._account_identity_hash = "c" * 64
        status["account_identity_hash"] = "c" * 64
        status["start_capability"] = {"ready": True, "blockers": []}
        status["runtime"].update(
            {"active": False, "opening_allowed": False, "cancel_only": True}
        )
        return json.loads(json.dumps(status))

    service.reconcile = reconcile
    snapshot = service._operator_contract_status()
    fenced = {
        "expected_runtime_identity": snapshot["runtime_identity"],
        "expected_state_revision": snapshot["state_revision"],
        "expected_state_digest": snapshot["state_digest"],
        "confirmation_text": "client-must-not-authorize",
        "environment": "live",
        "order_submission_allowed": True,
    }

    with pytest.raises(OperatorContractError) as failed:
        service.execute_operator_action_v2(
            "refresh_account_snapshot",
            fenced,
            idempotency_key="refresh-failure-recovery-001",
        )
    assert failed.value.code == "fake_refresh_transport_failure"
    assert len(calls) == 1

    operation = service._operator_operation_store.latest_unacknowledged(
        action="refresh_account_snapshot"
    )
    assert operation is not None
    read_model = service.operator_operation_v2(operation.operation_id)
    assert read_model["state"] == "failed"
    assert read_model["result_present"] is True
    assert read_model["start_attempt"] is None
    assert read_model["request_digest"] == canonical_request_digest(
        service._refresh_account_snapshot_command_payload()
    )
    assert calls[0]["environment"] == "demo"
    assert calls[0]["confirmation_text"] == OKX_DEMO_PAPER_CONFIRMATION
    assert calls[0]["order_submission_allowed"] is False
    assert len(calls) == 1, "GET/read-model recovery must never replay the POST"

    first_contract = service.operator_contract_v2()
    second_contract = service.operator_contract_v2()
    assert first_contract["state_revision"] == second_contract["state_revision"]
    assert first_contract["state_digest"] == second_contract["state_digest"]
    action_map = {row["action"]: row for row in first_contract["actions"]}
    assert action_map["refresh_account_snapshot"]["allowed"] is False
    assert "operator_terminal_operation_unacknowledged" in action_map[
        "refresh_account_snapshot"
    ]["blocker_codes"]
    assert action_map["enter_cancel_only"]["allowed"] is True

    acknowledged = service.acknowledge_operator_operation_v2(
        operation.operation_id,
        {
            "action": "refresh_account_snapshot",
            "expected_state_revision": operation.state_revision,
        },
    )
    assert acknowledged["acknowledged"] is True
    assert service._operator_operation_store.latest_unacknowledged(
        action="refresh_account_snapshot"
    ) is None

    fail_refresh = False
    refreshed_snapshot = service._operator_contract_status()
    succeeded = service.execute_operator_action_v2(
        "refresh_account_snapshot",
        {
            "expected_runtime_identity": refreshed_snapshot["runtime_identity"],
            "expected_state_revision": refreshed_snapshot["state_revision"],
            "expected_state_digest": refreshed_snapshot["state_digest"],
        },
        idempotency_key="refresh-failure-recovery-002",
    )
    assert succeeded["state"] == "succeeded"
    assert len(calls) == 2
    after_refresh = service.operator_contract_v2()
    after_action_map = {row["action"]: row for row in after_refresh["actions"]}
    assert after_action_map["authoritative_preflight_start"]["allowed"] is True
    assert all(value is False for value in after_refresh["safety_flags"].values())


def test_outer_start_operation_projects_inner_state_and_parent_binding(tmp_path: Path):
    service = object.__new__(btc_demo_runtime_service.BtcDemoRuntimeService)
    service.status = lambda: _status()
    service._operator_operation_store = _DurableOperatorOperationStore(tmp_path)
    service._runtime_identity = "runtime-policy-binding"
    service._account_identity_hash = "c" * 64
    service._risk_profile = "stress_3x"
    inner = {
        "operation_id": "inner-start-001",
        "attempt_id": "attempt-001",
        "state": "queued",
        "phase": "requested",
        "updated_at_utc": AS_OF,
        "blockers": [],
    }
    service._dispatch_operator_action_v2 = lambda action, payload, *, idempotency_key: {
        "accepted": True,
        "state": "queued",
        "phase": "requested",
        "operation_id": inner["operation_id"],
        "attempt_id": inner["attempt_id"],
        "start_operation": inner,
    }
    snapshot = service._operator_contract_status()
    result = service.execute_operator_action_v2(
        "authoritative_preflight_start",
        {
            **_authoritative_start_intent(),
            "expected_runtime_identity": snapshot["runtime_identity"],
            "expected_state_revision": snapshot["state_revision"],
            "expected_state_digest": snapshot["state_digest"],
        },
        idempotency_key="outer-inner-binding-001",
    )
    assert result["state"] == "queued"
    assert result["result_present"] is False
    binding = result["start_attempt"]
    assert binding["parent_operation_id"] == result["operation_id"]
    assert binding["inner_operation_id"] == "inner-start-001"
    assert binding["attempt_id"] == "attempt-001"
    assert binding["risk_profile"] == "stress_3x"
    assert binding["expected_leverage"] == "3"
    assert binding["effective_policy_digest"]


def test_missing_authoritative_account_identity_fails_before_operator_durable_begin(
    tmp_path: Path,
):
    class MissingIdentityController:
        def status(self):
            return _status()

        def current_start_attempt_identity(self):
            return {
                "runtime_identity": "runtime-missing-account",
                "source_head": HEAD,
                "effective_policy_digest": DIGEST,
                "risk_profile": "stress_3x",
                "expected_leverage": "3",
                "account_identity_hash": "",
            }

    service = object.__new__(btc_demo_runtime_service.BtcDemoRuntimeService)
    service.controller = MissingIdentityController()
    service.status = service.controller.status
    service._runtime_identity = "runtime-missing-account"
    service._account_identity_hash = ""
    service._risk_profile = "stress_3x"
    service._operator_operation_store = _DurableOperatorOperationStore(tmp_path)
    begin_calls: list[dict] = []
    original_begin = service._operator_operation_store.begin

    def tracked_begin(*args, **kwargs):
        begin_calls.append({"args": args, "kwargs": kwargs})
        return original_begin(*args, **kwargs)

    service._operator_operation_store.begin = tracked_begin  # type: ignore[method-assign]
    snapshot = service._operator_contract_status()
    with pytest.raises(OperatorContractError) as error:
        service.execute_operator_action_v2(
            "authoritative_preflight_start",
            {
                **_authoritative_start_intent(),
                "expected_runtime_identity": snapshot["runtime_identity"],
                "expected_state_revision": snapshot["state_revision"],
                "expected_state_digest": snapshot["state_digest"],
            },
            idempotency_key="missing-account-before-begin",
        )
    assert error.value.code == "btc_demo_authoritative_account_identity_hash_missing"
    assert begin_calls == []
    assert service._operator_operation_store._read() == []


def test_backend_start_policy_reads_latest_controller_account_hash() -> None:
    class DynamicIdentityController:
        def __init__(self) -> None:
            self.account_hash = "c" * 64

        def current_start_attempt_identity(self):
            return {
                "runtime_identity": "runtime-dynamic-account",
                "source_head": HEAD,
                "effective_policy_digest": "",
                "risk_profile": "stress_3x",
                "expected_leverage": "3",
                "account_identity_hash": self.account_hash,
            }

    controller = DynamicIdentityController()
    service = object.__new__(btc_demo_runtime_service.BtcDemoRuntimeService)
    service.controller = controller
    service._runtime_identity = "runtime-dynamic-account"
    service._account_identity_hash = "d" * 64
    service._risk_profile = "stress_3x"

    first = service._authoritative_start_request_payload(
        _authoritative_start_intent(),
        status=_status(),
    )
    controller.account_hash = "e" * 64
    second = service._authoritative_start_request_payload(
        _authoritative_start_intent(),
        status=_status(),
    )
    assert first["account_identity_hash"] == "c" * 64
    assert second["account_identity_hash"] == "e" * 64
    assert first["effective_policy_digest"] != second["effective_policy_digest"]


def test_terminal_outer_operation_from_old_identity_is_historical_not_current(
    tmp_path: Path,
):
    """A policy/runtime switch cannot leave a durable terminal row current."""

    service = object.__new__(btc_demo_runtime_service.BtcDemoRuntimeService)
    service.status = lambda: _status()
    service._operator_operation_store = _DurableOperatorOperationStore(tmp_path)
    service._runtime_identity = "current-runtime"
    service._account_identity_hash = "d" * 64
    service._risk_profile = "stress_3x"
    operation, _ = service._operator_operation_store.begin(
        action="authoritative_preflight_start",
        payload={"mode": "demo"},
        idempotency_key="identity-switch-terminal-001",
    )
    terminal = service._operator_operation_store.transition(
        operation.operation_id,
        state="blocked",
        phase="blocked",
        blockers=("okx_demo_paper_exact_isolated_1x_leverage_required",),
    )
    service._operator_operation_store.bind_start_attempt(
        terminal.operation_id,
        {
            "schema_version": START_ATTEMPT_SCHEMA_VERSION,
            "parent_operation_id": terminal.operation_id,
            "inner_operation_id": "old-inner-001",
            "attempt_id": "old-attempt-001",
            "runtime_identity": "old-runtime",
            "source_head": "a" * 40,
            "effective_policy_digest": "b" * 64,
            "risk_profile": "baseline_1x",
            "expected_leverage": "1",
            "account_identity_hash": "c" * 64,
            "created_at_utc": AS_OF,
            "updated_at_utc": AS_OF,
            "state": "blocked",
            "phase": "blocked",
            "current_attempt": True,
            "historical": False,
            "historical_reason_codes": [],
        },
    )

    projection = service.operator_contract_v2()

    assert projection["operation"] is None
    persisted = service._operator_operation_store.get(terminal.operation_id)
    assert persisted.start_attempt["current_attempt"] is False
    assert persisted.start_attempt["historical"] is True
    assert "runtime_identity_changed" in persisted.start_attempt["historical_reason_codes"]


@pytest.mark.parametrize("state", ["queued", "running"])
def test_nonterminal_outer_operation_from_old_identity_is_interrupted(
    tmp_path: Path,
    state: str,
):
    service = object.__new__(btc_demo_runtime_service.BtcDemoRuntimeService)
    store = _DurableOperatorOperationStore(tmp_path)
    operation, _ = store.begin(
        action="authoritative_preflight_start",
        payload={"mode": "demo"},
        idempotency_key=f"identity-switch-{state}-001",
    )
    if state == "running":
        operation = store.transition(
            operation.operation_id,
            state="running",
            phase="dispatching",
        )
    store.bind_start_attempt(
        operation.operation_id,
        {
            "schema_version": START_ATTEMPT_SCHEMA_VERSION,
            "parent_operation_id": operation.operation_id,
            "inner_operation_id": "old-inner-nonterminal",
            "attempt_id": "old-attempt-nonterminal",
            "runtime_identity": "old-runtime",
            "source_head": "a" * 40,
            "effective_policy_digest": "b" * 64,
            "risk_profile": "baseline_1x",
            "expected_leverage": "1",
            "account_identity_hash": "c" * 64,
            "created_at_utc": AS_OF,
            "updated_at_utc": AS_OF,
            "state": state,
            "phase": "requested",
            "current_attempt": True,
            "historical": False,
            "historical_reason_codes": [],
        },
    )

    store.reconcile_start_attempt_identity(
        {
            "runtime_identity": "new-runtime",
            "source_head": "d" * 40,
            "effective_policy_digest": "e" * 64,
            "risk_profile": "stress_3x",
            "expected_leverage": "3",
            "account_identity_hash": "f" * 64,
        }
    )

    persisted = store.get(operation.operation_id)
    assert persisted.state == "interrupted"
    assert persisted.start_attempt["current_attempt"] is False
    assert persisted.start_attempt["historical"] is True
    assert store.latest_unacknowledged() is None


def test_legacy_outer_operation_without_start_identity_is_fail_closed_historical(
    tmp_path: Path,
):
    store = _DurableOperatorOperationStore(tmp_path)
    operation, _ = store.begin(
        action="authoritative_preflight_start",
        payload={"mode": "demo"},
        idempotency_key="identity-missing-legacy-001",
    )
    store.transition(
        operation.operation_id,
        state="blocked",
        phase="blocked",
        blockers=("legacy_blocker",),
    )

    store.reconcile_start_attempt_identity(
        {
            "runtime_identity": "new-runtime",
            "source_head": "d" * 40,
            "effective_policy_digest": "e" * 64,
            "risk_profile": "stress_3x",
            "expected_leverage": "3",
            "account_identity_hash": "f" * 64,
        }
    )

    rows = json.loads(
        (tmp_path / "operator-contract-v2" / "operations.json").read_text(
            encoding="utf-8"
        )
    )
    assert rows[0]["historical"] is True
    assert "operator_start_attempt_identity_missing" in rows[0][
        "historical_reason_codes"
    ]
    assert store.latest_unacknowledged() is None


def test_authoritative_start_dispatch_returns_exact_request_blockers_before_controller():
    service = object.__new__(btc_demo_runtime_service.BtcDemoRuntimeService)
    calls: list[dict] = []
    service.start_operation = (
        lambda payload, *, idempotency_key: calls.append(dict(payload))
        or {"accepted": True}
    )

    with pytest.raises(OperatorContractError) as error:
        service._dispatch_operator_action_v2(
            "authoritative_preflight_start",
            _authoritative_start_intent(confirm_automatic_orders=False),
            idempotency_key="authoritative-start-invalid-001",
        )

    assert error.value.status_code == 400
    assert error.value.code == "okx_demo_paper_automatic_orders_not_confirmed"
    assert error.value.blockers == ("okx_demo_paper_automatic_orders_not_confirmed",)
    assert calls == []


def test_authoritative_start_request_blocker_is_persisted_as_blocked_operation(
    tmp_path: Path,
):
    service = object.__new__(btc_demo_runtime_service.BtcDemoRuntimeService)
    service.status = lambda: _status()
    store = _DurableOperatorOperationStore(tmp_path)
    transitions: list[dict] = []
    original_transition = store.transition

    def transition(operation_id, **kwargs):
        transitions.append(dict(kwargs))
        return original_transition(operation_id, **kwargs)

    store.transition = transition
    service._operator_operation_store = store
    controller_calls: list[dict] = []
    service.start_operation = (
        lambda payload, *, idempotency_key: controller_calls.append(dict(payload))
        or {"accepted": True}
    )
    snapshot = service._operator_contract_status()
    payload = {
        **_authoritative_start_intent(confirm_automatic_orders=False),
        "expected_runtime_identity": snapshot["runtime_identity"],
        "expected_state_revision": snapshot["state_revision"],
        "expected_state_digest": snapshot["state_digest"],
    }

    with pytest.raises(OperatorContractError) as error:
        service.execute_operator_action_v2(
            "authoritative_preflight_start",
            payload,
            idempotency_key="authoritative-start-blocked-001",
        )

    assert error.value.code == "okx_demo_paper_automatic_orders_not_confirmed"
    assert transitions[-1] == {
        "state": "blocked",
        "phase": "blocked",
        "blockers": ("okx_demo_paper_automatic_orders_not_confirmed",),
    }
    assert controller_calls == []


@pytest.mark.parametrize(
    "status,expected_allowed",
    [
        (_status(runtime={"run_id": "demo-run-7", "status": "starting", "active": False, "blockers": []}), False),
        (_status(start_capability={"ready": False, "blockers": ["python_keyring_not_installed"]}), False),
        (_status(safety={"live": True}), False),
    ],
)
def test_restart_recovery_does_not_admit_active_transitioning_or_explicit_safety_failure(status, expected_allowed):
    contract = build_operator_contract_v2(status)
    if contract is None:
        assert expected_allowed is False
    else:
        assert contract.action_map["authoritative_preflight_start"].allowed is expected_allowed
