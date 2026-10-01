"""Management only: explicit synthetic inputs, no exchange or economic writes."""
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta

import pytest

from quant_shared.strategy_delivery.models import DeliveryError, digest
from quant_shared.strategy_delivery.service import DeliveryService
from backend.app.services.candidate_delivery_store import DeliveryStore


def package():
    value = {
        "schema_version": "strategy_delivery_package_v2",
        "source": {"kind": "qlib", "run_id": "fixture-run", "candidate_id": "fixture-candidate"},
        "strategy_id": "fixture", "strategy_version": "1", "source_head": "a" * 40,
        "market": "crypto", "instrument": "BTC-USDT-SWAP", "bar_size": "1h",
        "settlement_currency": "USDT",
        "data_version": "fixture-data", "params_hash": "b" * 64,
        "artifacts": {"model.txt": "c" * 64},
        "contracts": {name: {"version": "fixture-1"} for name in (
            "features", "preprocessing", "output", "calibration", "position", "exit", "cost", "time", "state")},
        "supported_targets": ["offline"], "adapter_id": "fixture-offline-v1",
        "admission_blockers": [], "limitations": ["synthetic_software_test_not_trading_evidence"],
    }
    value["contracts"]["output"].update(kind="return_forecast", unit="return_fraction", horizon_bars=12, valid_for_bars=1)
    return value


class Sources:
    def __init__(self):
        self.value = package()
        self.reads = 0

    def compile(self, source):
        self.reads += 1
        assert source == self.value["source"]
        return deepcopy(self.value)


class Accounts:
    def __init__(self):
        self.value = {"account_ref": "fixture-account", "environment": "offline",
                      "identity_hash": "d" * 64, "revision": 1, "market": "crypto",
                      "instruments": ["BTC-USDT-SWAP"], "currency": "USDT",
                      "evidence_ref": "fixture-explicit-simulation", "verified": True,
                      "expires_at": "2027-01-01T00:00:00+00:00"}

    def get(self, ref):
        if ref != self.value["account_ref"]:
            raise DeliveryError("account_unknown", 404)
        return deepcopy(self.value)

    def list(self):
        return [deepcopy(self.value)]


@pytest.fixture
def setup(tmp_path):
    now = [datetime(2026, 9, 24, tzinfo=timezone.utc)]
    sources, accounts = Sources(), Accounts()
    store = DeliveryStore(tmp_path / "delivery", "fixture-owner")
    service = DeliveryService(store, sources, accounts, head="e" * 40, clock=lambda: now[0])
    return service, store, sources, accounts, now


def create(service, key="create-1", target="offline"):
    return service.create(package()["source"], target, key=key, actor="operator")


def command(service, row, action, **kwargs):
    return service.command(row["id"], action, expected_revision=row["revision"],
                           key=f"{row['id']}-{action}-{row['revision']}", actor="operator", **kwargs)


def approve(service):
    row = create(service)
    row = command(service, row, "bind", account_ref="fixture-account")
    return command(service, row, "review", decision="approve", reason="Fixture review only")


def test_complete_persistent_flow_and_exact_resolution(setup):
    service, store, sources, accounts, now = setup
    row = command(service, approve(service), "register")
    assert row["status"] == "registered"
    assert not any(row["permissions"].values())
    restarted = DeliveryService(DeliveryStore(store.root, "fixture-owner"), sources, accounts,
                                head="e" * 40, clock=lambda: now[0])
    assert restarted.get(row["id"]) == row
    resolved = restarted.resolve(row["id"], content_digest=row["content_digest"],
                                 account_identity_hash="d" * 64, adapter_id="fixture-offline-v1")
    assert resolved["package"]["source"] == package()["source"]
    assert len(store.history(row["id"])) == 4


def test_get_never_compiles_or_creates_storage(setup):
    service, store, sources, _, _ = setup
    assert service.list() == []
    assert not store.root.exists()
    row = create(service)
    reads = sources.reads
    service.get(row["id"])
    service.list()
    assert sources.reads == reads


def test_idempotency_and_concurrent_registration(setup):
    service, store, _, _, _ = setup
    first = create(service)
    assert create(service) == first
    with pytest.raises(DeliveryError, match="idempotency_conflict"):
        create(service, target="okx_demo")
    row = command(service, first, "bind", account_ref="fixture-account")
    row = command(service, row, "review", decision="approve", reason="fixture")
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: command(service, row, "register"), range(2)))
    assert results[0] == results[1]
    assert len(store.history(row["id"])) == 4


@pytest.mark.parametrize("damage", ["package", "account", "expiry", "head"])
def test_drift_cannot_register(setup, damage):
    service, _, sources, accounts, now = setup
    row = approve(service)
    if damage == "package": sources.value["artifacts"]["model.txt"] = "f" * 64
    if damage == "account": accounts.value["revision"] = 2
    if damage == "expiry": now[0] += timedelta(days=2)
    if damage == "head": service.head = "f" * 40
    with pytest.raises(DeliveryError):
        command(service, row, "register")
    assert service.get(row["id"])["status"] == "reviewed"


def test_invalid_package_is_recorded_not_approved(setup):
    service, _, sources, _, _ = setup
    del sources.value["contracts"]["exit"]
    row = create(service)
    assert row["status"] == "validation_blocked"
    assert "contract_missing:exit" in row["validation"]["blockers"]
    with pytest.raises(DeliveryError):
        command(service, row, "review", decision="approve", reason="cannot override")
    rejected = command(service, row, "review", decision="reject", reason="missing exit")
    assert rejected["status"] == "rejected"


def test_research_blockers_and_unsupported_demo_preserved(setup):
    service, _, sources, _, _ = setup
    sources.value["admission_blockers"] = ["quality_not_proven"]
    row = create(service, target="okx_demo")
    assert "quality_not_proven" in row["validation"]["blockers"]
    assert "target_adapter_unsupported" in row["validation"]["blockers"]


def test_supported_demo_target_never_uses_offline_diagnostic_admission(setup):
    service, _, sources, _, _ = setup
    sources.value["supported_targets"] = ["offline", "okx_demo"]
    row = create(service, target="okx_demo")
    assert row["status"] == "validation_blocked"
    assert row["diagnostic_admission"]["status"] == "blocked"
    assert row["diagnostic_admission"]["research_blockers"] == []
    assert row["diagnostic_admission"]["blocking_reasons"] == ["offline_diagnostic_target_required"]
    with pytest.raises(DeliveryError, match="package_not_validated"):
        command(service, row, "bind", account_ref="fixture-account")


def test_new_offline_record_separates_diagnostic_admission_from_research_blockers(setup):
    service, _, sources, _, _ = setup
    sources.value["admission_blockers"] = ["no_simulated_fills", "research_admission_not_proven"]
    row = create(service)
    assert row["status"] == "validated"
    assert row["validation"] == {
        "validator": "strategy_delivery_validator_v2",
        "blockers": [],
        "status": "passed",
    }
    decision = row["diagnostic_admission"]
    assert decision["schema_version"] == "strategy_delivery_diagnostic_admission_v1"
    assert decision["status"] == "admitted"
    assert decision["blocking_reasons"] == []
    assert decision["research_blockers"] == ["no_simulated_fills", "research_admission_not_proven"]
    assert decision["strict_package_blockers"] == ["no_simulated_fills", "research_admission_not_proven"]
    assert len(decision["decision_digest"]) == 64
    assert row["package"]["admission_blockers"] == ["no_simulated_fills", "research_admission_not_proven"]

    row = command(service, row, "bind", account_ref="fixture-account")
    row = command(service, row, "review", decision="approve", reason="diagnostic only; research blocked")
    row = command(service, row, "register")
    resolved = service.resolve(row["id"], content_digest=row["content_digest"],
        account_identity_hash="d" * 64, adapter_id="fixture-offline-v1")
    assert resolved["diagnostic_admission"] == decision
    assert resolved["registration"]["start_allowed"] is False
    assert not any(resolved["permissions"].values())


@pytest.mark.parametrize("blocker", [
    "calibration_quality_not_passed", "final_position_not_flat", "pending_intents",
    "unknown_future_gate",
])
def test_offline_diagnostic_admission_allowlist_is_fail_closed(setup, blocker):
    service, _, sources, _, _ = setup
    sources.value["admission_blockers"] = ["no_simulated_fills", blocker]
    row = create(service)
    assert row["status"] == "validation_blocked"
    assert blocker in row["validation"]["blockers"]
    assert row["diagnostic_admission"]["status"] == "blocked"
    assert row["diagnostic_admission"]["research_blockers"] == ["no_simulated_fills"]
    assert blocker in row["diagnostic_admission"]["blocking_reasons"]
    with pytest.raises(DeliveryError, match="package_not_validated"):
        command(service, row, "bind", account_ref="fixture-account")


def test_legacy_record_without_versioned_diagnostic_decision_stays_strict(setup):
    service, _, sources, _, _ = setup
    sources.value["admission_blockers"] = ["no_simulated_fills"]
    row = create(service)
    assert row["status"] == "validated"
    row.pop("diagnostic_admission")
    with pytest.raises(DeliveryError, match="package_admission_blocked"):
        service._fresh(row, account=False)


def test_diagnostic_decision_tampering_and_rejection_never_promote(setup):
    service, _, sources, _, _ = setup
    sources.value["admission_blockers"] = ["research_admission_not_proven"]
    row = create(service)
    tampered = deepcopy(row)
    tampered["diagnostic_admission"]["research_blockers"] = []
    with pytest.raises(DeliveryError, match="diagnostic_admission_changed"):
        service._fresh(tampered, account=False)
    rejected = command(service, row, "review", decision="reject", reason="operator rejected")
    assert rejected["status"] == "rejected"
    with pytest.raises(DeliveryError, match="package_not_validated"):
        command(service, rejected, "bind", account_ref="fixture-account")


def test_revision_and_revoke_and_wrong_consumption(setup):
    service, _, _, _, _ = setup
    row = command(service, approve(service), "register")
    with pytest.raises(DeliveryError, match="resolution_binding_mismatch"):
        service.resolve(row["id"], content_digest="0" * 64, account_identity_hash="d" * 64,
                        adapter_id="fixture-offline-v1")
    with pytest.raises(DeliveryError, match="revision_conflict"):
        service.command(row["id"], "revoke", expected_revision=1, key="stale", actor="operator", reason="test")
    revoked = command(service, row, "revoke", reason="fixture revoke")
    assert revoked["status"] == "revoked"
    with pytest.raises(DeliveryError, match="registration_inactive"):
        service.resolve(row["id"], content_digest=row["content_digest"], account_identity_hash="d" * 64,
                        adapter_id="fixture-offline-v1")


def test_sqlite_transaction_rolls_back_partial_write(setup):
    service, store, _, _, _ = setup
    row = create(service)
    def fail(conn):
        conn.execute("DELETE FROM workflows")
        raise RuntimeError("injected crash")
    with pytest.raises(RuntimeError):
        store.transact("crash", digest({"crash": True}), fail)
    assert service.get(row["id"]) == row


def test_same_account_cannot_register_two_packages(setup):
    service, _, _, _, _ = setup
    command(service, approve(service), "register")
    second = create(service, key="create-2")
    second = command(service, second, "bind", account_ref="fixture-account")
    second = command(service, second, "review", decision="approve", reason="fixture")
    with pytest.raises(DeliveryError, match="account_registration_conflict"):
        command(service, second, "register")


def test_running_service_rejects_head_change(setup):
    service, _, _, _, _ = setup
    row = approve(service)
    service.head_provider = lambda: "f" * 40
    with pytest.raises(DeliveryError, match="deployment_changed_restart_required"):
        command(service, row, "register")
    with pytest.raises(DeliveryError, match="deployment_changed_restart_required"):
        create(service, key="new-head-create")


def test_malformed_output_and_targets_fail_closed(setup):
    service, _, sources, _, _ = setup
    sources.value["contracts"]["output"] = None
    sources.value["supported_targets"] = None
    row = create(service)
    assert row["status"] == "validation_blocked"
    assert "target_adapter_unsupported" in row["validation"]["blockers"]


def test_binding_requires_instrument_list_and_invalidates_review(setup):
    service, _, _, accounts, _ = setup
    row = approve(service)
    accounts.value["instruments"] = "BTC-USDT-SWAP"
    with pytest.raises(DeliveryError, match="account_binding_incompatible"):
        command(service, row, "register")
    accounts.value["instruments"] = ["BTC-USDT-SWAP"]
    rebound = command(service, row, "bind", account_ref="fixture-account")
    assert rebound["status"] == "bound" and rebound["review"] is None
    with pytest.raises(DeliveryError, match="review_required"):
        command(service, rebound, "register")


def test_receipt_recovery_and_tampering_fail_closed(setup):
    import sqlite3
    service, store, _, _, _ = setup
    row = create(service)
    assert store.request_result("create-1", "operator") == row
    with pytest.raises(DeliveryError, match="request_not_found"):
        store.request_result("create-1", "different-operator")
    with sqlite3.connect(store.path) as conn:
        conn.execute("UPDATE workflows SET payload=? WHERE id=?", ('{}', row["id"]))
    with pytest.raises(DeliveryError, match="delivery_record_integrity_invalid"):
        service.get(row["id"])


@pytest.mark.parametrize("currency", [None, "", "usdt", " USDT ", "U$DT", 123])
def test_package_currency_must_be_explicit_and_canonical(setup, currency):
    service, _, sources, _, _ = setup
    if currency is None:
        sources.value.pop("settlement_currency")
    else:
        sources.value["settlement_currency"] = currency
    row = create(service)
    assert row["status"] == "validation_blocked"
    assert "settlement_currency_invalid" in row["validation"]["blockers"]


@pytest.mark.parametrize("currency", ["USD", "usdt", " USDT ", "", None])
def test_account_currency_mismatch_rejected_before_bind(setup, currency):
    service, store, _, accounts, _ = setup
    row = create(service)
    accounts.value["currency"] = currency
    with pytest.raises(DeliveryError, match="account_settlement_currency_mismatch"):
        command(service, row, "bind", account_ref="fixture-account")
    assert service.get(row["id"])["status"] == "validated"
    assert len(store.history(row["id"])) == 1


@pytest.mark.parametrize("stage", ["review", "register", "resolve"])
def test_account_currency_drift_rejected_at_each_boundary(setup, stage):
    service, _, _, accounts, _ = setup
    row = create(service)
    row = command(service, row, "bind", account_ref="fixture-account")
    if stage != "review":
        row = command(service, row, "review", decision="approve", reason="USDT fixture")
    if stage == "resolve":
        row = command(service, row, "register")
    accounts.value["currency"] = "USD"  # no other identity change to mask currency check
    with pytest.raises(DeliveryError, match="account_settlement_currency_mismatch"):
        if stage == "resolve":
            service.resolve(row["id"], content_digest=row["content_digest"], account_identity_hash="d"*64, adapter_id="fixture-offline-v1")
        elif stage == "review":
            command(service, row, "review", decision="approve", reason="must reject")
        else:
            command(service, row, "register")


def test_legacy_package_without_currency_is_not_silently_upgraded(setup):
    service, _, sources, _, _ = setup
    sources.value["schema_version"] = "strategy_delivery_package_v1"
    sources.value.pop("settlement_currency")
    row = create(service)
    assert row["status"] == "validation_blocked"
    assert "package_schema_invalid" in row["validation"]["blockers"]
    with pytest.raises(DeliveryError):
        command(service, row, "bind", account_ref="fixture-account")
