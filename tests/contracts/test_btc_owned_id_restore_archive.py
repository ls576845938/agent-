from __future__ import annotations

import json
import shutil
import subprocess
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

from quant_crypto.application import btc_owned_id_restore_archive as publisher
from quant_crypto.oms.okx_demo_paper_runtime import _build_owned_id_restore_projection


SOURCE_ARCHIVE = (
    Path(r"D:\vibe coding\Obsidian\量化系统\immutable-evidence\btc-demo-observation-compatibility")
    / "btc-cumulative-25h-compatibility-01-160a482-20260808T112140Z-verified"
)
EXPECTED_HEAD = subprocess.check_output(
    ["git", "rev-parse", "HEAD"],
    cwd=Path.cwd(),
    text=True,
).strip()
CREDENTIAL_IDENTITY = "quant-system.okx-demo.trade"


def _source_exchange() -> dict:
    state_document = json.loads(
        (SOURCE_ARCHIVE / "source_snapshots/runtime_state.json").read_text(
            encoding="utf-8"
        )
    )
    return state_document["state"]["exchange"]


def _snapshot(**changes):
    exchange = _source_exchange()
    account = dict(exchange["account"])
    account["account_identifier"] = "demo-account-opaque"
    value = {
        "environment": "OKX Demo",
        "instrument_id": "BTC-USDT-SWAP",
        "margin_mode": "isolated",
        "account": account,
        "positions": [],
        "pending_orders": [],
        "pending_algo_orders": [],
        "orders": [dict(row) for row in exchange["orders"]],
        "fills": [dict(row) for row in exchange["fills"]],
        "captured_at_utc": "2026-08-09T00:00:00+00:00",
        "fresh": True,
        "safety": {"secret_read": False},
    }
    value.update(changes)
    return publisher.DemoPrivateReadSnapshot(**value)


def _history_rows(field, client_ids):
    rows = {
        str(row["client_order_id"]): dict(row)
        for row in _source_exchange()[field]
    }
    return [rows[client_id] for client_id in client_ids]


def _rewrite_archive_hashes(root: Path, mutate_event) -> None:
    """Rebuild every allowed source hash after a deterministic event mutation."""

    events_path = root / "source_snapshots/runtime_events.jsonl"
    events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]
    mutate_event(events)
    event_lines = publisher._rebuild_event_chain(events)
    events_path.write_text("\n".join(event_lines) + "\n", encoding="utf-8")

    state_path = root / "source_snapshots/runtime_state.json"
    state_document = json.loads(state_path.read_text(encoding="utf-8"))
    checkpoint = publisher._rebuild_checkpoint(state_document["state"], event_lines)
    publisher._write_json(state_path, checkpoint)

    manifest_path = root / "manifest.json"
    verification_path = root / "verification.json"
    completed_path = root / "COMPLETED.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    verification = json.loads(verification_path.read_text(encoding="utf-8"))
    completed = json.loads(completed_path.read_text(encoding="utf-8"))
    last_event_hash = json.loads(event_lines[-1])["event_hash"]
    event_sha = publisher._sha256_file(events_path)
    state_sha = publisher._sha256_file(state_path)
    for document in (manifest["event_chain"], verification["event_identity"]):
        document["last_event_hash"] = last_event_hash
        document["file_sha256"] = event_sha
    for item in manifest["files"]:
        if item["archive_relative_path"] == "source_snapshots/runtime_events.jsonl":
            item["sha256"] = event_sha
            item["size_bytes"] = events_path.stat().st_size
        elif item["archive_relative_path"] == "source_snapshots/runtime_state.json":
            item["sha256"] = state_sha
            item["size_bytes"] = state_path.stat().st_size
    publisher._write_json(verification_path, verification)
    verification_sha = publisher._sha256_file(verification_path)
    manifest["verification_sha256"] = verification_sha
    for item in manifest["files"]:
        if item["archive_relative_path"] == "verification.json":
            item["sha256"] = verification_sha
            item["size_bytes"] = verification_path.stat().st_size
    manifest["manifest_hash"] = publisher._canonical_sha256(
        {key: value for key, value in manifest.items() if key != "manifest_hash"}
    )
    publisher._write_json(manifest_path, manifest)
    completed["manifest_sha256"] = publisher._sha256_file(manifest_path)
    completed["verification_sha256"] = verification_sha
    publisher._write_json(completed_path, completed)


class FakeProvider:
    capability = publisher.DemoPrivateReadCapability()

    def __init__(self, snapshot=None):
        self.snapshot = snapshot or _snapshot()
        self.calls = 0

    def read_snapshot(self):
        self.calls += 1
        return self.snapshot


class WriteCapableProvider(FakeProvider):
    def submit_order(self, *_args, **_kwargs):
        raise AssertionError("provider write path must never be called")


def _publish(tmp_path: Path, provider=None, **kwargs):
    provider = provider or FakeProvider()
    output = tmp_path / "btc-owned-id-derived-20260809"
    source_archive_root = kwargs.pop("source_archive_root", SOURCE_ARCHIVE)
    credential_identity = kwargs.pop("credential_identity", CREDENTIAL_IDENTITY)
    expected_current_head = kwargs.pop("expected_current_head", EXPECTED_HEAD)
    result = publisher.publish_owned_id_restore_archive(
        source_archive_root=source_archive_root,
        output_root=output,
        repo_root=Path.cwd(),
        provider=provider,
        credential_identity=credential_identity,
        expected_current_head=expected_current_head,
        **kwargs,
    )
    return result, output, provider


def test_happy_path_is_identity_only_and_current_restore_consumes_it(tmp_path):
    result, output, provider = _publish(tmp_path)

    assert provider.calls == 1
    assert result["owned_triples"] == [
        {
            "client_order_id": "btcDP37bc2ebb0001",
            "order_id": "3806692760012689408",
            "fill_id": "4318943831",
            "run_id": "37bc2ebb12f34a0c8f9a983e477de28d",
        },
        {
            "client_order_id": "btcDP37bc2ebb0002",
            "order_id": "3807973567142531072",
            "fill_id": "4319419253",
            "run_id": "37bc2ebb12f34a0c8f9a983e477de28d",
        },
    ]
    assert result["client_order_namespace"] == "btcDP37bc2ebb"
    assert result["identity_only"] is True
    assert result["opening_allowed"] is False
    assert output.is_dir()

    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["execution_identity"]["credential_identity"] == CREDENTIAL_IDENTITY
    assert manifest["client_order_namespace"] == "btcDP37bc2ebb"
    assert manifest["promotion_evidence_ready"] is False
    assert all(value is False for value in manifest["safety"].values())

    projection = _build_owned_id_restore_projection(
        archive_root=output,
        repo_root=Path.cwd(),
        current_head=EXPECTED_HEAD,
        source_head=EXPECTED_HEAD,
        account_identity=result["account_identity"],
        credential_identity=CREDENTIAL_IDENTITY,
        client_order_namespace=result["client_order_namespace"],
        credential_service=CREDENTIAL_IDENTITY,
    )
    assert projection["owned_client_order_ids"] == [
        "btcDP37bc2ebb0001",
        "btcDP37bc2ebb0002",
    ]
    assert projection["identity_only"] is True
    assert projection["opening_allowed"] is False


def test_source_triples_follow_lifecycle_sequence_not_mapping_or_id_order():
    facts = publisher._validate_source_archive(SOURCE_ARCHIVE, repo_root=Path.cwd())
    _run_id, _namespace, rows, _events = publisher._select_source_run(facts)
    assert list(facts.source_orders) == [
        "btcDP37bc2ebb0002",
        "btcDP37bc2ebb0001",
    ]
    assert [row["client_order_id"] for row in rows] == [
        "btcDP37bc2ebb0001",
        "btcDP37bc2ebb0002",
    ]

    # The opaque IDs intentionally sort opposite to their authoritative event
    # sequence; lifecycle sequence, not lexical ID order, is canonical.
    synthetic_run = "37bc2ebb12f34a0c8f9a983e477de28d"
    synthetic = {
        "btcDP37bc2ebbzz": {"sequence": 4},
        "btcDP37bc2ebbaa": {"sequence": 9},
    }
    ordered = publisher._ordered_source_triples(
        {
            ("btcDP37bc2ebbaa", "order-a", "fill-a"),
            ("btcDP37bc2ebbzz", "order-z", "fill-z"),
        },
        {synthetic_run: synthetic},
        synthetic_run,
    )
    assert ordered == (
        ("btcDP37bc2ebbzz", "order-z", "fill-z"),
        ("btcDP37bc2ebbaa", "order-a", "fill-a"),
    )


@pytest.mark.parametrize(
    ("order_clients", "fill_clients", "accepted"),
    [
        (
            ["btcDP37bc2ebb0001", "btcDP37bc2ebb0002"],
            ["btcDP37bc2ebb0001", "btcDP37bc2ebb0002"],
            True,
        ),
        (
            ["btcDP37bc2ebb0001", "btcDP37bc2ebb0002"],
            ["btcDP37bc2ebb0002"],
            True,
        ),
        (
            ["btcDP37bc2ebb0002"],
            ["btcDP37bc2ebb0002"],
            True,
        ),
        (
            ["btcDP37bc2ebb0001"],
            ["btcDP37bc2ebb0001"],
            False,
        ),
        (
            ["btcDP37bc2ebb0001", "btcDP37bc2ebb0002"],
            ["btcDP37bc2ebb0001"],
            False,
        ),
        (
            ["btcDP37bc2ebb0001"],
            ["btcDP37bc2ebb0002"],
            False,
        ),
        (
            ["btcDP37bc2ebb0001", "btcDP37bc2ebb0002"],
            [],
            False,
        ),
    ],
)
def test_current_history_must_be_nonempty_latest_contiguous_suffix(
    tmp_path,
    order_clients,
    fill_clients,
    accepted,
):
    provider = FakeProvider(
        _snapshot(
            orders=_history_rows("orders", order_clients),
            fills=_history_rows("fills", fill_clients),
        )
    )
    if accepted:
        result, output, _provider = _publish(tmp_path, provider)
        assert result["owned_triples"][0]["client_order_id"] == "btcDP37bc2ebb0001"
        assert provider.calls == 1
        assert output.is_dir()
    else:
        with pytest.raises(publisher.OwnedIDRestoreArchiveError):
            _publish(tmp_path, provider)
        assert provider.calls == 1
        assert not (tmp_path / "btc-owned-id-derived-20260809").exists()


def test_suffix_readback_is_current_but_runtime_state_keeps_full_source_projection(tmp_path):
    provider = FakeProvider(
        _snapshot(
            orders=_history_rows(
                "orders",
                ["btcDP37bc2ebb0001", "btcDP37bc2ebb0002"],
            ),
            fills=_history_rows("fills", ["btcDP37bc2ebb0002"]),
        )
    )
    result, output, _provider = _publish(tmp_path, provider)
    assert provider.calls == 1
    checkpoint = json.loads(
        (output / "source_snapshots/runtime_state.json").read_text(encoding="utf-8")
    )
    state_exchange = checkpoint["state"]["exchange"]
    assert [row["client_order_id"] for row in state_exchange["orders"]] == [
        "btcDP37bc2ebb0001",
        "btcDP37bc2ebb0002",
    ]
    assert [row["client_order_id"] for row in state_exchange["fills"]] == [
        "btcDP37bc2ebb0001",
        "btcDP37bc2ebb0002",
    ]
    current_readback = json.loads(
        (output / "source_snapshots/current_private_readback.json").read_text(
            encoding="utf-8"
        )
    )
    assert [row["client_order_id"] for row in current_readback["orders"]] == [
        "btcDP37bc2ebb0001",
        "btcDP37bc2ebb0002",
    ]
    assert [row["client_order_id"] for row in current_readback["fills"]] == [
        "btcDP37bc2ebb0002",
    ]
    projection = _build_owned_id_restore_projection(
        archive_root=output,
        repo_root=Path.cwd(),
        current_head=EXPECTED_HEAD,
        source_head=EXPECTED_HEAD,
        account_identity=result["account_identity"],
        credential_identity=CREDENTIAL_IDENTITY,
        client_order_namespace=result["client_order_namespace"],
        credential_service=CREDENTIAL_IDENTITY,
    )
    assert [row["client_order_id"] for row in projection["owned_triples"]] == [
        "btcDP37bc2ebb0001",
        "btcDP37bc2ebb0002",
    ]


def test_source_tamper_fails_before_provider_and_no_output(tmp_path):
    tampered = tmp_path / "source-tampered"
    shutil.copytree(SOURCE_ARCHIVE, tampered)
    events = tampered / "source_snapshots/runtime_events.jsonl"
    events.write_text(events.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    provider = FakeProvider()
    with pytest.raises(publisher.OwnedIDRestoreArchiveError):
        _publish(tmp_path, provider, source_archive_root=tampered)
    assert provider.calls == 0
    assert not (tmp_path / "btc-owned-id-derived-20260809").exists()


def test_reviewer_order_ledger_conflict_rehashed_archive_fails_before_provider(tmp_path):
    tampered = tmp_path / "source-ledger-conflict"
    shutil.copytree(SOURCE_ARCHIVE, tampered)

    def mutate(events):
        for event in events:
            if (
                event.get("event_type") == "ledger_uow_committed"
                and event.get("run_id") == "37bc2ebb12f34a0c8f9a983e477de28d"
                and event["payload"]["order_ledger"].get("orders")
            ):
                event["payload"]["order_ledger"]["orders"][0]["order_id"] = (
                    "ledger-conflict-order"
                )
                return
        raise AssertionError("selected non-empty ledger UOW not found")

    _rewrite_archive_hashes(tampered, mutate)
    provider = FakeProvider()
    with pytest.raises(publisher.OwnedIDRestoreArchiveError):
        _publish(tmp_path, provider, source_archive_root=tampered)
    assert provider.calls == 0
    assert not (tmp_path / "btc-owned-id-derived-20260809").exists()
    assert not list(tmp_path.glob("*.publish.lock"))
    assert not list(tmp_path.glob("*.tmp-*"))


@pytest.mark.parametrize(
    "malformation",
    [
        "payload_missing",
        "order_ledger_missing",
        "order_ledger_wrong_type",
        "orders_missing",
        "orders_wrong_type",
        "fill_ledger_wrong_type",
        "orders_empty",
        "fills_empty",
        "duplicate_order",
        "duplicate_fill",
        "mapping_conflict",
        "partial_history",
    ],
)
def test_malformed_ledger_uow_is_never_silently_skipped(malformation):
    facts = publisher._validate_source_archive(SOURCE_ARCHIVE, repo_root=Path.cwd())
    events = deepcopy(list(facts.events))
    target = next(
        event
        for event in events
        if (
            event.get("event_type") == "ledger_uow_committed"
            and event.get("run_id") == "37bc2ebb12f34a0c8f9a983e477de28d"
            and event["payload"]["order_ledger"].get("orders")
        )
    )
    payload = target["payload"]
    order_ledger = payload["order_ledger"]
    if malformation == "payload_missing":
        target.pop("payload")
    elif malformation == "order_ledger_missing":
        payload.pop("order_ledger")
    elif malformation == "order_ledger_wrong_type":
        payload["order_ledger"] = []
    elif malformation == "orders_missing":
        order_ledger.pop("orders")
    elif malformation == "orders_wrong_type":
        order_ledger["orders"] = {}
    elif malformation == "fill_ledger_wrong_type":
        payload["fill_ledger"] = {}
    elif malformation == "orders_empty":
        order_ledger["orders"] = []
    elif malformation == "fills_empty":
        payload["fill_ledger"] = []
    elif malformation == "duplicate_order":
        order_ledger["orders"].append(deepcopy(order_ledger["orders"][0]))
    elif malformation == "duplicate_fill":
        payload["fill_ledger"].append(deepcopy(payload["fill_ledger"][0]))
    elif malformation == "mapping_conflict":
        payload["fill_ledger"][0]["order_id"] = "ledger-conflict-order"
    elif malformation == "partial_history":
        multi = next(
            event
            for event in events
            if (
                event.get("event_type") == "ledger_uow_committed"
                and event["payload"]["order_ledger"].get("orders")
                and len(event["payload"]["order_ledger"]["orders"]) > 1
            )
        )
        multi["payload"]["order_ledger"]["orders"].pop()
    else:  # pragma: no cover - exhaustive parameter list
        raise AssertionError(malformation)
    with pytest.raises(publisher.OwnedIDRestoreArchiveError):
        publisher._ledger_triples(events)


@pytest.mark.parametrize(
    "changes",
    [
        {"environment": "OKX Live"},
        {"instrument_id": "ETH-USDT-SWAP"},
        {"margin_mode": "cross"},
        {"positions": [{"instId": "BTC-USDT-SWAP", "pos": "1"}]},
        {"pending_orders": [{"ordId": "foreign"}]},
        {"pending_algo_orders": [{"algoId": "foreign"}]},
        {"account": {"account_level": "2", "permissions": ["trade"], "position_mode": "long_short_mode", "withdraw_permission_present": True}},
    ],
)
def test_provider_state_guards_fail_closed(tmp_path, changes):
    provider = FakeProvider(_snapshot(**changes))
    with pytest.raises(publisher.OwnedIDRestoreArchiveError):
        _publish(tmp_path, provider)
    assert provider.calls == 1
    assert not (tmp_path / "btc-owned-id-derived-20260809").exists()


def test_foreign_history_and_secret_field_fail_closed(tmp_path):
    snapshot = _snapshot(
        orders=_snapshot().as_mapping()["orders"]
        + [
            {
                "client_order_id": "btcDPforeign0001",
                "order_id": "foreign-order",
                "instrument_id": "BTC-USDT-SWAP",
                "state": "filled",
            }
        ],
    )
    provider = FakeProvider(snapshot)
    with pytest.raises(publisher.OwnedIDRestoreArchiveError):
        _publish(tmp_path, provider)
    assert provider.calls == 1

    foreign_fill = _snapshot().as_mapping()
    foreign_fill["fills"] = foreign_fill["fills"] + [
        {
            "client_order_id": "btcDPforeign0001",
            "order_id": "foreign-order",
            "fill_id": "foreign-fill",
            "instrument_id": "BTC-USDT-SWAP",
        }
    ]
    provider = FakeProvider(foreign_fill)
    with pytest.raises(publisher.OwnedIDRestoreArchiveError):
        _publish(tmp_path, provider)
    assert provider.calls == 1

    secret_snapshot = _snapshot()
    secret_mapping = secret_snapshot.as_mapping()
    secret_mapping["account"]["api_key"] = "sentinel-secret"
    provider = FakeProvider(secret_mapping)
    with pytest.raises(publisher.OwnedIDRestoreArchiveError):
        _publish(tmp_path, provider)
    assert provider.calls == 1


def test_identity_and_provider_capability_guards_are_zero_call(tmp_path):
    provider = FakeProvider()
    with pytest.raises(publisher.OwnedIDRestoreArchiveError):
        _publish(tmp_path, provider, credential_identity="quant-system.okx-demo.secret")
    assert provider.calls == 0

    provider = FakeProvider()
    with pytest.raises(publisher.OwnedIDRestoreArchiveError):
        _publish(tmp_path, provider, expected_current_head="0" * 40)
    assert provider.calls == 0

    provider = FakeProvider()
    with pytest.raises(publisher.OwnedIDRestoreArchiveError):
        publisher.publish_owned_id_restore_archive(
            source_archive_root=SOURCE_ARCHIVE,
            output_root=Path.cwd() / "repo-local-owned-id",
            repo_root=Path.cwd(),
            provider=provider,
            credential_identity=CREDENTIAL_IDENTITY,
        )
    assert provider.calls == 0

    provider = FakeProvider()
    with pytest.raises(publisher.OwnedIDRestoreArchiveError):
        _publish(tmp_path, WriteCapableProvider())
    assert provider.calls == 0

    bad_capability = FakeProvider()
    bad_capability.capability = publisher.DemoPrivateReadCapability(post_allowed=True)
    with pytest.raises(publisher.OwnedIDRestoreArchiveError):
        _publish(tmp_path, bad_capability)
    assert bad_capability.calls == 0

    live_capability = FakeProvider()
    live_capability.capability = publisher.DemoPrivateReadCapability(live_allowed=True)
    with pytest.raises(publisher.OwnedIDRestoreArchiveError):
        _publish(tmp_path, live_capability)
    assert live_capability.calls == 0

    missing_account_identity = _snapshot().as_mapping()
    missing_account_identity["account"].pop("account_identifier")
    missing_identity_provider = FakeProvider(missing_account_identity)
    with pytest.raises(publisher.OwnedIDRestoreArchiveError):
        _publish(tmp_path, missing_identity_provider)
    assert missing_identity_provider.calls == 1


def test_output_is_unique_and_overwrite_is_rejected(tmp_path):
    first, output, first_provider = _publish(tmp_path)
    assert first_provider.calls == 1
    second_provider = FakeProvider()
    with pytest.raises(publisher.OwnedIDRestoreArchiveError):
        publisher.publish_owned_id_restore_archive(
            source_archive_root=SOURCE_ARCHIVE,
            output_root=output,
            repo_root=Path.cwd(),
            provider=second_provider,
            credential_identity=CREDENTIAL_IDENTITY,
            expected_current_head=EXPECTED_HEAD,
        )
    assert second_provider.calls == 0


def test_publication_failure_leaves_no_partial_output(tmp_path, monkeypatch):
    provider = FakeProvider()

    def fail_publish(_temp_root, _output_root):
        raise publisher.OwnedIDRestoreArchiveError("forced_publication_failure")

    monkeypatch.setattr(publisher, "_publish_directory", fail_publish)
    with pytest.raises(publisher.OwnedIDRestoreArchiveError):
        _publish(tmp_path, provider)
    assert provider.calls == 1
    assert not (tmp_path / "btc-owned-id-derived-20260809").exists()
    assert not list(tmp_path.glob("*.publish.lock"))
    assert not list(tmp_path.glob("*.tmp-*"))


def test_weak_namespace_is_never_caller_selected(tmp_path):
    result, _output, _provider = _publish(tmp_path)
    assert result["client_order_namespace"] == "btcDP37bc2ebb"
    assert result["client_order_namespace"] not in {"btc", "btcDP"}
    assert all(
        row["client_order_id"].startswith("btcDP37bc2ebb")
        for row in result["owned_triples"]
    )


def test_none_and_multi_run_selection_fail_closed():
    facts = publisher._validate_source_archive(SOURCE_ARCHIVE, repo_root=Path.cwd())
    selected_run = "37bc2ebb12f34a0c8f9a983e477de28d"
    other_run = "aaaaaaaa12f34a0c8f9a983e477de28d"
    snapshot = _snapshot().as_mapping()

    none_events = []
    for event in facts.events:
        value = dict(event)
        if (
            value.get("event_type") == "order_lifecycle"
            and value.get("run_id") == selected_run
        ):
            value["run_id"] = other_run
        none_events.append(value)
    with pytest.raises(publisher.OwnedIDRestoreArchiveError):
        publisher._select_run(replace(facts, events=tuple(none_events)), snapshot)

    duplicate_events = list(facts.events)
    for event in facts.events:
        if (
            event.get("event_type") in {"order_lifecycle", "ledger_uow_committed"}
            and event.get("run_id") == selected_run
        ):
            value = dict(event)
            value["run_id"] = other_run
            duplicate_events.append(value)
    with pytest.raises(publisher.OwnedIDRestoreArchiveError):
        publisher._select_run(replace(facts, events=tuple(duplicate_events)), snapshot)


def test_output_cannot_be_published_inside_source_archive(tmp_path):
    provider = FakeProvider()
    with pytest.raises(publisher.OwnedIDRestoreArchiveError):
        publisher.publish_owned_id_restore_archive(
            source_archive_root=SOURCE_ARCHIVE,
            output_root=SOURCE_ARCHIVE / "derived-owned-id",
            repo_root=Path.cwd(),
            provider=provider,
            credential_identity=CREDENTIAL_IDENTITY,
            expected_current_head=EXPECTED_HEAD,
        )
    assert provider.calls == 0


def test_cli_has_no_write_or_live_switches():
    from scripts.build_btc_owned_id_restore_archive import build_parser

    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["--source-archive", "x", "--output-root", "y", "--execute-demo"])
