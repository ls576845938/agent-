"""Independent failure-first checks for the cohort entry/recovery handoff.

These tests intentionally exercise invariants that the producer seam-double
tests do not prove.  They are not candidate, promotion, paper, or live
evidence.
"""

from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace

import pandas as pd
import pytest

from quant_crypto.application.btc_registered_cohort import (
    COHORT_DECISION_SCHEMA,
    RegisteredCohortReplay,
    _object_payload,
)
from quant_shared.strategy_delivery.models import DeliveryError, digest


def test_rebuilding_same_donchian_member_decision_preserves_source_object_identity():
    """A persisted pending decision must be reproducible before any retry."""

    runtime = RegisteredCohortReplay.__new__(RegisteredCohortReplay)
    decision_time = datetime(2026, 6, 16, 1, tzinfo=timezone.utc)
    frame = pd.DataFrame(
        [{"close": 60_000.0}],
        index=pd.DatetimeIndex([decision_time]),
    )
    runtime.historical_input = SimpleNamespace(frame=frame)
    runtime.replay = SimpleNamespace(
        evaluate_frame=lambda *_args, **_kwargs: {
            "direction": "long",
            "target_contracts": "1",
            "raw_signal": "1",
        }
    )
    runtime.don_row = {
        "package": {
            "strategy_id": "registered-donchian",
        }
    }

    first, _ = runtime._donchian_objects(decision_time)
    second, _ = runtime._donchian_objects(decision_time)

    assert first["signal"].signal_id == second["signal"].signal_id
    assert first["target"].target_position_id == second["target"].target_position_id
    assert digest(_object_payload(first["signal"])) == digest(_object_payload(second["signal"]))
    assert digest(_object_payload(first["target"])) == digest(_object_payload(second["target"]))


def test_projection_repair_rejects_ledger_uow_from_different_allocation_plan():
    """A matching client id/member list alone is not allocation authority."""

    member_list_sha256 = "m" * 64
    expected_allocation_sha256 = "a" * 64
    foreign_allocation_sha256 = "b" * 64
    client_order_id = "cohort-order"
    event = {
        "event_type": "ledger_uow_committed",
        "event_hash": "e" * 64,
        "payload": {
            "order_ledger": {"orders": [{"client_order_id": client_order_id}]},
            "fill_ledger": [{"client_order_id": client_order_id, "fill_id": "fill-1"}],
            "strategy_allocation": {
                "member_list_sha256": member_list_sha256,
                "allocation_plan_sha256": foreign_allocation_sha256,
                "member_contracts": {
                    "delivery_" + "1" * 32: "1",
                    "delivery_" + "2" * 32: "1",
                },
            },
        },
    }
    allocation = dict(event["payload"]["strategy_allocation"])
    replay = SimpleNamespace(
        controller=SimpleNamespace(
            _runtime_store=SimpleNamespace(
                recover=lambda: SimpleNamespace(
                    events=[event], blockers=(), truncated_tail=False
                )
            ),
            _state={"strategy_allocations": allocation},
        ),
        venue=SimpleNamespace(
            state={"position": "2", "orders": [{}], "fills": [{}]}
        ),
    )
    runtime = RegisteredCohortReplay.__new__(RegisteredCohortReplay)
    runtime.replay = replay
    prepared = {
        "schema_version": COHORT_DECISION_SCHEMA,
        "cursor": 1,
        "event_time_utc": "2026-06-16T00:00:00+00:00",
        "decision_time_utc": "2026-06-16T01:00:00+00:00",
        "allocation_plan": {
            "member_list_sha256": member_list_sha256,
            "allocation_plan_sha256": expected_allocation_sha256,
        },
        "member_objects": {},
        "next_member_states": {},
        "common_market_facts": {},
        "order_plan": {"client_order_id": client_order_id},
        "execution_context_issued": True,
        "binding": {},
    }
    prepared["sha256"] = digest(prepared)
    pending = {
        "schema_version": "candidate_offline_cohort_pending_v1",
        "job_id": "coff_" + "d" * 32,
        "cursor": 1,
        "status": "prepared",
        "prepared": prepared,
    }

    with pytest.raises(
        DeliveryError, match="cohort_committed_allocation_identity_mismatch"
    ):
        runtime.repair_committed(pending)


def test_projection_repair_selects_original_uow_from_cumulative_ledger_snapshots():
    """A later reconciliation snapshot must not make the original fill ambiguous."""

    first_member = "delivery_" + "1" * 32
    second_member = "delivery_" + "2" * 32
    member_list_sha256 = "m" * 64
    allocation_plan_sha256 = "a" * 64
    client_order_id = "cohort-order"
    order = {"client_order_id": client_order_id, "order_id": "order-1"}
    fill = {
        "client_order_id": client_order_id,
        "order_id": "order-1",
        "fill_id": "fill-1",
        "timestamp_ms": 1_781_568_000_000,
    }
    allocation = {
        "member_list_sha256": member_list_sha256,
        "member_contracts": {first_member: "1", second_member: "1"},
        "fill_allocations": {
            "fill-1": {
                "allocation_plan_sha256": allocation_plan_sha256,
                "members": {
                    first_member: {"signed_contracts": "1"},
                    second_member: {"signed_contracts": "1"},
                },
            }
        },
    }
    original = {
        "event_type": "ledger_uow_committed",
        "event_hash": "e" * 64,
        "payload": {
            "order_ledger": {"orders": [order]},
            "fill_ledger": [fill],
            "strategy_allocation": allocation,
        },
    }
    later_reconciliation = {
        "event_type": "ledger_uow_committed",
        "event_hash": "f" * 64,
        "payload": {
            # Runtime ledger payloads are cumulative, so the old order/fill
            # remain present even when this UOW only reconciles later facts.
            "order_ledger": {
                "orders": [
                    order,
                    {"client_order_id": "later-order", "order_id": "order-2"},
                ]
            },
            "fill_ledger": [
                fill,
                {
                    "client_order_id": "later-order",
                    "order_id": "order-2",
                    "fill_id": "fill-2",
                    "timestamp_ms": 1_781_568_060_000,
                },
            ],
            "strategy_allocation": allocation,
        },
    }
    durable = {
        "decision_time_utc": "2026-06-16T00:00:00+00:00",
        "order_plan": {"client_order_id": client_order_id},
        "allocation_plan": {
            "member_list_sha256": member_list_sha256,
            "allocation_plan_sha256": allocation_plan_sha256,
            "desired_member_contracts": {first_member: "1", second_member: "1"},
            "member_delta_contracts": {first_member: "1", second_member: "1"},
        },
    }

    assert RegisteredCohortReplay._matching_committed_event(
        durable, [original, later_reconciliation]
    ) is original


def test_common_clock_rejects_partial_member_observation_overlap():
    """Every cohort event must be observed compatibly by both member inputs."""

    first = pd.Timestamp("2026-06-16T00:00:00Z")
    second = pd.Timestamp("2026-06-16T01:00:00Z")
    observations = (
        SimpleNamespace(
            event_time_utc=first,
            close_price=60_000,
            mark_price=60_001,
            funding_settlements=(),
        ),
        SimpleNamespace(
            event_time_utc=second,
            close_price=60_100,
            mark_price=60_101,
            funding_settlements=(),
        ),
    )
    runtime = RegisteredCohortReplay.__new__(RegisteredCohortReplay)
    runtime.observations = observations
    runtime.verified_qlib = SimpleNamespace(
        manifest={"schema_version": "registered_offline_market_v2"}
    )
    runtime.historical_input = SimpleNamespace(
        signal_rows=pd.DataFrame(
            [{"event_time": first, "close": 60_000}]
        ),
        mark_by_event={first.to_pydatetime(): {"close": 60_001}},
        funding_events=(),
    )

    with pytest.raises(DeliveryError, match="cohort_member_clocks_do_not_match"):
        runtime._verify_common_sources()


def test_real_app_factory_readonly_middleware_blocks_management_writes_and_reads(
    monkeypatch, tmp_path
):
    """The composed app, not a bare router, must enforce research-readonly."""

    from fastapi.testclient import TestClient
    from backend.app.api import app_factory
    from tests.contracts.test_candidate_offline_access import empty_service

    settings, service = empty_service(tmp_path)
    overrides = {
        key: value for key, value in vars(settings).items() if key != "repo_root"
    }
    overrides.update(
        backend_evidence_profile="research_readonly",
        candidate_offline_enabled=True,
    )
    monkeypatch.setattr(
        app_factory,
        "settings",
        replace(app_factory.settings, **overrides),
    )
    client = TestClient(app_factory.create_app())

    capability = client.get("/api/candidate-offline/capabilities")
    assert capability.status_code == 200
    assert capability.json()["offline_commands_enabled"] is False
    blocked_write = client.post("/api/candidate-offline/jobs", json={})
    assert blocked_write.status_code == 423
    assert blocked_write.json()["error"] == "backend_research_readonly_route_blocked"
    for path in (
        "/api/strategy-delivery/accounts",
        "/api/strategy-delivery/packages",
    ):
        blocked_read = client.get(path)
        assert blocked_read.status_code == 423
        assert blocked_read.json()["controls_disabled"] is True
    assert not service.store.path.exists()
