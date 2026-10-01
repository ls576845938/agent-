from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from quant_crypto.application.btc_next_stage_engineering_evidence import (
    BUILDER_CHAIN,
    CURRENT_HEAD_LAYERS,
    DATA_HANDOFF_TICKET,
    DATA_INTEGRATED_EVENT_ID,
    DATA_PUBLISHED_EVENT_ID,
    build_btc_next_stage_engineering_evidence,
    resolve_selected_public_ws_dependency,
)
from quant_crypto.backtest.funding_cashflow_evidence import (
    build_offline_funding_cashflow_evidence,
)
from quant_crypto.backtest.funding_ledger import FundingFill, FundingRateEvent
from quant_crypto.monitoring.artifact_schema import (
    stable_payload_hash,
    validate_btc_artifact_schema,
)
from quant_crypto.oms.private_ws_reconciliation import (
    BTCPrivateWSEventKind,
    BTCPrivateWSFixtureEvent,
    reconcile_private_ws_offline_fixture,
)


HEAD = "a" * 40
DATA_PRODUCER_COMMIT = "b" * 40
INTEGRATION_COMMIT = "c" * 40
DIGEST = "d" * 64
NOW = datetime(2026, 7, 27, 8, 0, tzinfo=timezone.utc)
DATA_EVENT_PATH = Path(
    ".agent/handoffs/DATA-BTC-V3-IMMUTABLE-PUBLIC-MARKET-EVIDENCE-01/"
    "integrated-data-btc-v3-immutable-public-market-evidence-01.json"
)
DATA_MANIFEST_PATH = Path(
    ".agent/data_manifests/btc-okx-v3-immutable-public-market-evidence/"
    "btc-okx-v3-public-btcusdt-20260727T075929750Z-src311c5ec7.json"
)


def test_next_stage_accepts_distinct_committed_data_producer_and_consumer_head() -> None:
    funding = _funding_evidence()
    private_ws = _private_ws_evidence()
    payload = build_btc_next_stage_engineering_evidence(
        current_head=HEAD,
        generated_at_utc=NOW,
        source_evidence=_source_evidence(),
        public_market_handoff=_handoff(),
        public_ws_dependency=_public_ws_dependency(),
        l2_evidence=_l2_evidence(),
        builder_chain=_builder_chain(),
        funding_evidence=funding,
        private_ws_evidence=private_ws,
    )

    assert payload["engineering_contracts_valid"] is True
    assert payload["public_market_handoff"]["accepted"] is True
    assert (
        payload["public_market_handoff"]["deliverable_commit"]
        == INTEGRATION_COMMIT
    )
    assert (
        payload["public_market_handoff"]["data_producer_commit"]
        == DATA_PRODUCER_COMMIT
    )
    assert payload["l2_evidence"]["producer_commit"] == DATA_PRODUCER_COMMIT
    assert payload["l2_evidence"]["consumer_source_head"] == HEAD
    assert payload["l2_evidence"]["valid"] is True
    assert payload["status"] == "blocked"
    assert payload["promotion_evidence_ready"] is False
    assert payload["paper_ready"] is False
    assert payload["live_ready"] is False
    assert all(value is False for value in payload["safety"].values())
    assert "btc_next_stage:real_funding_cashflow_evidence_missing" in payload["blockers"]
    assert (
        "btc_next_stage:real_private_ws_reconciliation_evidence_missing"
        in payload["blockers"]
    )
    assert "btc_next_stage:real_non_flat_fill_evidence_missing" in payload["blockers"]
    assert (
        "btc_okx_native:25_hour_demo_observation_window_incomplete"
        in payload["blockers"]
    )
    assert (
        "btc_next_stage:natural_observation_window_30_60d_incomplete"
        not in payload["blockers"]
    )
    assert "btc_next_stage:manual_promotion_approval_missing" in payload["blockers"]
    assert validate_btc_artifact_schema(payload) == []


def test_missing_data_handoff_keeps_precise_fail_closed_blocker() -> None:
    payload = build_btc_next_stage_engineering_evidence(
        current_head=HEAD,
        generated_at_utc=NOW,
        source_evidence=_source_evidence(),
        public_market_handoff=None,
        public_ws_dependency=_public_ws_dependency(),
        l2_evidence=_l2_evidence(producer_commit=""),
        builder_chain=_builder_chain(),
    )

    assert (
        "btc_next_stage:data_btc_v3_immutable_public_market_evidence_handoff_missing"
        in payload["blockers"]
    )
    assert payload["public_market_handoff"]["accepted"] is False
    assert payload["promotion_evidence_ready"] is False


def test_current_main_integrated_data_handoff_is_consumed_with_all_blockers() -> None:
    event_raw = DATA_EVENT_PATH.read_bytes()
    event = json.loads(event_raw)
    manifest = json.loads(DATA_MANIFEST_PATH.read_text(encoding="utf-8"))
    receipt = {
        **event,
        "handoff_event_sha256": hashlib.sha256(event_raw).hexdigest(),
        "readiness_class": "quality_checked",
        "data_producer_commit": manifest["producer_commit"],
    }

    payload = build_btc_next_stage_engineering_evidence(
        current_head=HEAD,
        generated_at_utc=NOW,
        source_evidence=_source_evidence(),
        public_market_handoff=receipt,
        public_ws_dependency=None,
        l2_evidence=None,
        builder_chain=_builder_chain(),
    )

    handoff = payload["public_market_handoff"]
    assert handoff["accepted"] is True
    assert handoff["event_id"] == DATA_INTEGRATED_EVENT_ID
    assert handoff["transition_for"] == DATA_PUBLISHED_EVENT_ID
    assert handoff["deliverable_commit"] == event["deliverable_commit"]
    assert handoff["data_producer_commit"] == manifest["producer_commit"]
    assert handoff["upstream_gate_blocked"] is True
    assert (
        "btc_next_stage:data_btc_v3_immutable_public_market_evidence_handoff_missing"
        not in payload["blockers"]
    )
    for blocker in event["blockers"]:
        assert blocker in payload["blockers"]
    assert "btc_okx_websocket_client_dependency_missing" in payload["blockers"]
    assert "btc_okx_l2_sequence_continuity_unverified" in payload["blockers"]
    assert "l2_lt_30_natural_days" in payload["blockers"]
    assert (
        "btc_open_interest_history_not_verified_diagnostic_partial"
        in payload["blockers"]
    )
    assert "btc_okx_server_time_offset_exceeds_threshold" in payload["blockers"]
    assert "manifest_data_schema_mismatch" in payload["blockers"]
    assert "manifest_quality_status_not_pass" in payload["blockers"]
    assert "l2_manifest_attestation_readiness_mismatch" in payload["blockers"]
    assert (
        "runtime_pointer_immutable_snapshot_not_published" in payload["blockers"]
    )
    assert (
        "runtime_pointer_data_steward_attestation_required" in payload["blockers"]
    )
    assert "btc_next_stage:real_funding_cashflow_evidence_missing" in payload["blockers"]
    assert (
        "btc_next_stage:real_private_ws_reconciliation_evidence_missing"
        in payload["blockers"]
    )
    assert "btc_next_stage:real_non_flat_fill_evidence_missing" in payload["blockers"]
    assert (
        "btc_okx_native:25_hour_demo_observation_window_incomplete"
        in payload["blockers"]
    )
    assert "btc_next_stage:manual_promotion_approval_missing" in payload["blockers"]
    assert payload["promotion_evidence_ready"] is False
    assert payload["paper_ready"] is False
    assert payload["live_ready"] is False
    assert all(value is False for value in payload["safety"].values())


def test_selected_bundle_resolver_requires_one_public_import_safe_package() -> None:
    selected_bundle = "d" * 64
    resolved = resolve_selected_public_ws_dependency(
        selected_bundle_sha256=selected_bundle,
        package_receipts=[
            {
                "selected_bundle_sha256": "0" * 64,
                "package_sha256": "1" * 64,
                "public_only": True,
                "import_safe": True,
                "package_name": "unselected",
            },
            {
                "selected_bundle_sha256": selected_bundle,
                "package_sha256": "e" * 64,
                "public_only": True,
                "import_safe": True,
                "package_name": "okx-public-ws",
                "distribution_name": "websocket-client",
                "distribution_version": "1.9.0",
                "distribution_root": "C:/canonical/site-packages",
                "module_name": "websocket",
                "module_version": "1.9.0",
                "module_path": "C:/canonical/site-packages/websocket/__init__.py",
                "module_sha256": "a" * 64,
                "allowlist_roots": ["C:/canonical/site-packages"],
                "allowlist_valid": True,
            },
        ],
    )

    assert resolved["valid"] is True
    assert resolved["selected_bundle_sha256"] == selected_bundle
    assert resolved["package_sha256"] == "e" * 64
    assert resolved["package_name"] == "okx-public-ws"
    assert resolved["blockers"] == []


def test_selected_bundle_resolver_rejects_ambiguous_or_private_package() -> None:
    selected_bundle = "d" * 64
    resolved = resolve_selected_public_ws_dependency(
        selected_bundle_sha256=selected_bundle,
        package_receipts=[
            {
                "selected_bundle_sha256": selected_bundle,
                "package_sha256": "e" * 64,
                "public_only": False,
                "import_safe": True,
                "distribution_name": "websocket-client",
                "distribution_version": "1.9.0",
                "module_path": "C:/canonical/site-packages/websocket/__init__.py",
                "module_sha256": "a" * 64,
                "allowlist_valid": True,
            },
            {
                "selected_bundle_sha256": selected_bundle,
                "package_sha256": "f" * 64,
                "public_only": True,
                "import_safe": True,
                "distribution_name": "websocket-client",
                "distribution_version": "1.9.0",
                "module_path": "C:/canonical/site-packages/websocket/__init__.py",
                "module_sha256": "b" * 64,
                "allowlist_valid": True,
            },
        ],
    )

    assert resolved["valid"] is False
    assert (
        "btc_next_stage:public_ws_package_not_unique_for_selected_bundle"
        in resolved["blockers"]
    )
    assert "btc_next_stage:public_ws_dependency_not_public_only" in resolved["blockers"]


def test_l2_sequence_and_two_sided_contracts_fail_closed() -> None:
    payload = build_btc_next_stage_engineering_evidence(
        current_head=HEAD,
        generated_at_utc=NOW,
        source_evidence=_source_evidence(),
        public_market_handoff=_handoff(),
        public_ws_dependency=_public_ws_dependency(),
        l2_evidence=_l2_evidence(sequence_contiguous=False, two_sided=False),
        builder_chain=_builder_chain(),
    )

    assert payload["engineering_contracts_valid"] is False
    assert "btc_next_stage:l2_sequence_continuity_unproven" in payload["blockers"]
    assert "btc_next_stage:l2_two_sided_book_unproven" in payload["blockers"]


def test_builder_chain_and_domain_sources_must_all_match_current_head() -> None:
    sources = _source_evidence()
    sources["oms"] = {**sources["oms"], "source_head": "d" * 40}
    chain = _builder_chain()
    chain[1] = {**chain[1], "source_head": "d" * 40}
    payload = build_btc_next_stage_engineering_evidence(
        current_head=HEAD,
        generated_at_utc=NOW,
        source_evidence=sources,
        public_market_handoff=_handoff(),
        public_ws_dependency=_public_ws_dependency(),
        l2_evidence=_l2_evidence(),
        builder_chain=chain,
    )

    assert "btc_next_stage:source_head_mismatch:oms" in payload["blockers"]
    assert (
        "btc_next_stage:builder_source_head_mismatch:promotion_evidence"
        in payload["blockers"]
    )
    assert payload["engineering_contracts_valid"] is False


def test_offline_funding_replay_reconciles_but_does_not_clear_real_cashflow() -> None:
    payload = _funding_evidence()

    assert payload["offline_fixture_validated"] is True
    assert payload["ledger_reconciled"] is True
    assert payload["total_funding_payment"] == -2.0
    assert payload["status"] == "blocked"
    assert payload["fixture_only"] is True
    assert payload["real_observation"] is False
    assert payload["promotion_evidence_ready"] is False
    assert (
        "btc_funding_cashflow:real_current_head_cashflow_observation_missing"
        in payload["blockers"]
    )
    assert all(value is False for value in payload["safety"].values())
    assert validate_btc_artifact_schema(payload) == []


def test_offline_private_ws_reconciles_sequence_and_fill_without_endpoint_access() -> None:
    payload = _private_ws_evidence()

    assert payload["offline_fixture_validated"] is True
    assert payload["state"] == "offline_reconciled"
    assert payload["fill_count"] == 1
    assert payload["status"] == "blocked"
    assert payload["fixture_only"] is True
    assert payload["real_observation"] is False
    assert payload["promotion_evidence_ready"] is False
    assert (
        "btc_private_ws:real_current_head_private_ws_observation_missing"
        in payload["blockers"]
    )
    assert all(value is False for value in payload["safety"].values())
    assert validate_btc_artifact_schema(payload) == []


def test_offline_private_ws_gap_and_unknown_order_fail_closed() -> None:
    events = [
        BTCPrivateWSFixtureEvent(
            sequence=10,
            event_id="event-10",
            kind=BTCPrivateWSEventKind.ORDER_ACK,
            client_order_id="unknown-order",
        ),
        BTCPrivateWSFixtureEvent(
            sequence=12,
            event_id="event-12",
            kind=BTCPrivateWSEventKind.FILL,
            client_order_id="unknown-order",
            fill_id="fill-12",
            filled_quantity=0.01,
            fill_price=100_000.0,
        ),
    ]
    rows = [_private_event_row(row) for row in events]
    payload = reconcile_private_ws_offline_fixture(
        current_head=HEAD,
        source_head=HEAD,
        generated_at_utc=NOW,
        events=events,
        expected_order_ids=["expected-order"],
        source_receipt={
            "fixture_version": "private-ws-fixture-v1",
            "events_sha256": stable_payload_hash(rows),
        },
    )

    assert payload["offline_fixture_validated"] is False
    assert payload["state"] == "blocked"
    assert "btc_private_ws:sequence_gap" in payload["blockers"]
    assert "btc_private_ws:unknown_client_order_id" in payload["blockers"]
    assert "btc_private_ws:order_ack_missing" in payload["blockers"]


def _source_evidence() -> dict[str, dict[str, object]]:
    return {
        layer: {
            "path": f"committed/{layer}.json",
            "sha256": stable_payload_hash({"layer": layer}),
            "source_head": HEAD,
            "status": "complete_research_only",
            "blockers": [],
        }
        for layer in CURRENT_HEAD_LAYERS
    }


def _handoff() -> dict[str, object]:
    return {
        "ticket_id": DATA_HANDOFF_TICKET,
        "event_id": DATA_INTEGRATED_EVENT_ID,
        "event_type": "integrated",
        "transition_for": DATA_PUBLISHED_EVENT_ID,
        "deliverable_commit": INTEGRATION_COMMIT,
        "data_producer_commit": DATA_PRODUCER_COMMIT,
        "handoff_event_sha256": DIGEST,
        "schema_version": "agent_handoff_envelope_v1",
        "readiness_class": "quality_checked",
        "blockers": [],
    }


def _public_ws_dependency() -> dict[str, object]:
    return {
        "resolver_contract_version": "btc_public_ws_dependency_v1",
        "selected_bundle_sha256": "d" * 64,
        "package_sha256": "e" * 64,
        "public_only": True,
        "import_safe": True,
        "package_name": "websocket-client",
        "distribution_name": "websocket-client",
        "distribution_version": "1.9.0",
        "distribution_root": "C:/canonical/site-packages",
        "module_name": "websocket",
        "module_version": "1.9.0",
        "module_path": "C:/canonical/site-packages/websocket/__init__.py",
        "module_sha256": "a" * 64,
        "allowlist_roots": ["C:/canonical/site-packages"],
        "allowlist_valid": True,
        "user_site_consumed": False,
    }


def _l2_evidence(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "consumer_source_head": HEAD,
        "producer_commit": DATA_PRODUCER_COMMIT,
        "sha256": "f" * 64,
        "sequence_contiguous": True,
        "two_sided": True,
    }
    row.update(overrides)
    return row


def _builder_chain() -> list[dict[str, object]]:
    return [
        {
            "name": name,
            "source_head": HEAD,
            "sha256": stable_payload_hash({"builder": name}),
            "immutable_output": True,
        }
        for name in BUILDER_CHAIN
    ]


def _funding_evidence() -> dict[str, object]:
    rates = [
        FundingRateEvent(
            funding_time=NOW,
            funding_rate=0.0001,
            mark_price=100_000.0,
            source_record_id="funding-1",
        )
    ]
    fills = [
        FundingFill(
            filled_at=datetime(2026, 7, 27, 7, 0, tzinfo=timezone.utc),
            side="buy",
            quantity=0.2,
            price=99_500.0,
            fill_id="fill-1",
        )
    ]
    rate_rows = [
        {
            "funding_time": NOW.isoformat(),
            "funding_rate": 0.0001,
            "mark_price": 100_000.0,
            "source_record_id": "funding-1",
        }
    ]
    fill_rows = [
        {
            "filled_at": datetime(
                2026, 7, 27, 7, 0, tzinfo=timezone.utc
            ).isoformat(),
            "side": "buy",
            "quantity": 0.2,
            "price": 99_500.0,
            "fill_id": "fill-1",
        }
    ]
    return build_offline_funding_cashflow_evidence(
        current_head=HEAD,
        source_head=HEAD,
        generated_at_utc=NOW,
        funding_rates=rates,
        fills=fills,
        source_receipt={
            "data_version": "offline-fixture-v1",
            "funding_rates_sha256": stable_payload_hash(rate_rows),
            "fills_sha256": stable_payload_hash(fill_rows),
        },
        expected_total_payment=-2.0,
    )


def _private_ws_evidence() -> dict[str, object]:
    events = [
        BTCPrivateWSFixtureEvent(
            sequence=1,
            event_id="event-1",
            kind=BTCPrivateWSEventKind.ORDER_ACK,
            client_order_id="order-1",
        ),
        BTCPrivateWSFixtureEvent(
            sequence=2,
            event_id="event-2",
            kind=BTCPrivateWSEventKind.FILL,
            client_order_id="order-1",
            fill_id="fill-1",
            filled_quantity=0.02,
            fill_price=100_000.0,
        ),
    ]
    rows = [_private_event_row(row) for row in events]
    return reconcile_private_ws_offline_fixture(
        current_head=HEAD,
        source_head=HEAD,
        generated_at_utc=NOW,
        events=events,
        expected_order_ids=["order-1"],
        source_receipt={
            "fixture_version": "private-ws-fixture-v1",
            "events_sha256": stable_payload_hash(rows),
        },
    )


def _private_event_row(row: BTCPrivateWSFixtureEvent) -> dict[str, object]:
    return {
        "sequence": row.sequence,
        "event_id": row.event_id,
        "kind": row.kind.value,
        "client_order_id": row.client_order_id,
        "fill_id": row.fill_id,
        "filled_quantity": row.filled_quantity,
        "fill_price": row.fill_price,
    }
