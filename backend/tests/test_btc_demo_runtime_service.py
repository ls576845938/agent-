from __future__ import annotations

import json
import threading
from dataclasses import replace
from decimal import Decimal

import pytest

from quant_crypto.application.btc_strategy_registry import OKX_NATIVE_STRATEGY_LINE
from quant_crypto.application.btc_demo_production_composition import canonical_ledger_snapshot_sha256
from quant_crypto.runtime.control_plane import BTCDemoExecutionDispatcher
from quant_crypto.oms.account_risk_facts import (
    reviewed_account_facts_approval_digest,
)

from backend.app.services import btc_demo_runtime


class FakeController:
    def __init__(self) -> None:
        self.stop_and_flatten_calls: list[dict] = []

    def status(self) -> dict:
        return {}

    def emergency_reduce_only_exit(self, payload: dict) -> dict:
        return {
            "decision": "fresh_state_emergency_reduce_only_exit_completed",
            "request": dict(payload),
            "orders_posted": 1,
            "opening_allowed": False,
            "cancel_only": True,
        }

    def stop_and_flatten(self, payload: dict) -> dict:
        self.stop_and_flatten_calls.append(dict(payload))
        return {
            "decision": "stopped_and_flattened",
            "orders_posted": 0,
            "final_flat": True,
            "opening_allowed": False,
            "cancel_only": True,
        }


class StatusController(FakeController):
    def __init__(self, payload: dict) -> None:
        super().__init__()
        self.payload = payload

    def status(self) -> dict:
        return self.payload


def _reviewed_account_facts_record(*, unit: str = "ratio", value: str = "0.1") -> dict:
    snapshot_sha256 = "b" * 64
    row = {
        "schema_version": "btc_account_facts_approval_v1",
        "approval_id": "approval-20260913-service-001",
        "status": "approved",
        "reviewer_identity": "human-reviewer-1",
        "approval_ticket": "BTC-ACCOUNT-FACTS-BASELINE-20260913",
        "reviewed_at_utc": "2026-09-13T00:00:00Z",
        "account_identity_hash": "a" * 64,
        "account_scope": "dedicated_demo_account",
        "currency": "USDT",
        "source_head": "c" * 40,
        "runtime_identity": "btc-demo-runtime:reviewed-service",
        "snapshot_sha256": snapshot_sha256,
        "observed_at_utc": "2026-09-13T00:00:00Z",
        "equity_usdt": "100",
        "history_complete": False,
        "baseline_authority": "explicit_reviewed_account_baseline_v1",
        "flatness_evidence": {
            "schema_version": "btc_reviewed_account_flatness_v1",
            "scope": "dedicated_trading_account_account_wide",
            "positions_complete": True,
            "pending_orders_complete": True,
            "pending_algo_orders_complete": True,
            "pending_intents_complete": True,
            "snapshot_sha256": snapshot_sha256,
        },
        "drawdown_policy": {
            "schema_version": "btc_reviewed_drawdown_policy_v1",
            "value": value,
            "unit": unit,
        },
    }
    row["approval_digest"] = reviewed_account_facts_approval_digest(row)
    return row


def test_account_facts_default_composition_is_unknown_and_does_not_resolve_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict = {}

    def controller_factory(*, config):
        captured["config"] = config
        return FakeController()

    monkeypatch.setattr(
        btc_demo_runtime,
        "settings",
        replace(
            btc_demo_runtime.settings,
            btc_demo_account_facts_approval_registry="",
            btc_demo_account_facts_approval_id="",
            btc_demo_runtime_identity="",
        ),
    )
    monkeypatch.setattr(
        btc_demo_runtime,
        "load_reviewed_account_facts_approval",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("default_config_must_not_read_approval_registry")
        ),
    )
    monkeypatch.setattr(
        btc_demo_runtime,
        "OkxDemoPaperRuntimeController",
        controller_factory,
    )

    service = btc_demo_runtime.BtcDemoRuntimeService()

    assert service._production_composition.guardian_config.max_drawdown_unit == "unknown"
    assert captured["config"].account_facts_approval_resolver is None
    assert captured["config"].account_facts_approval_id == ""
    assert (
        captured["config"].account_cashflow_evidence_provider
        is btc_demo_runtime.collect_okx_account_cashflow_evidence
    )


def test_account_facts_reviewed_policy_is_bound_into_runtime_and_guardian(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict = {}
    approval = _reviewed_account_facts_record(unit="ratio", value="0.1")

    def controller_factory(*, config):
        captured["config"] = config
        return FakeController()

    def load_approval(**kwargs):
        captured["load"] = kwargs
        return dict(approval)

    monkeypatch.setattr(
        btc_demo_runtime,
        "settings",
        replace(
            btc_demo_runtime.settings,
            btc_demo_account_facts_approval_registry="D:/external/reviewed.json",
            btc_demo_account_facts_approval_id=approval["approval_id"],
            btc_demo_runtime_identity=approval["runtime_identity"],
        ),
    )
    monkeypatch.setattr(
        btc_demo_runtime,
        "load_reviewed_account_facts_approval",
        load_approval,
    )
    monkeypatch.setattr(
        btc_demo_runtime,
        "_current_repo_head",
        lambda _repo_root: approval["source_head"],
    )
    monkeypatch.setattr(
        btc_demo_runtime,
        "OkxDemoPaperRuntimeController",
        controller_factory,
    )

    service = btc_demo_runtime.BtcDemoRuntimeService()

    assert captured["load"]["approval_id"] == approval["approval_id"]
    assert captured["config"].runtime_identity == approval["runtime_identity"]
    assert captured["config"].account_facts_approval_id == approval["approval_id"]
    assert captured["config"].account_facts_approval_resolver(
        approval["approval_id"]
    )["approval_digest"] == approval["approval_digest"]
    assert service._production_composition.guardian_config.max_drawdown == 0.1
    assert service._production_composition.guardian_config.max_drawdown_unit == "ratio"


def _operator_status_fixture(
    *,
    runtime_status: str = "stopped",
    active: bool = False,
    opening_allowed: bool = False,
    cancel_only: bool = False,
    risk_mode: str = "FROZEN_UNKNOWN",
    risk_reason: str = "runtime_not_started",
    last_error: str = "",
    blockers: list[str] | None = None,
    private_ws_status: str = "not_started",
    private_ws_blockers: list[str] | None = None,
    worker_alive: bool | None = None,
    authoritative_liveness_required: bool = False,
    positions: list[dict] | None = None,
    pending_orders: list[dict] | None = None,
    pending_algo_orders: list[dict] | None = None,
    ledger_status: str = "reconciled",
    ledger_matches: bool = True,
    funding_reconciled: bool = True,
    observation_blockers: list[str] | None = None,
    start_capability: dict | None = None,
) -> dict:
    positions = positions or []
    pending_orders = pending_orders or []
    pending_algo_orders = pending_algo_orders or []
    connected = private_ws_status == "connected"
    effective_worker_alive = active if worker_alive is None else worker_alive
    account_identity = {
        "hash": "a" * 64,
        "source": "okx_demo_account_config_uid_main_uid",
        "captured_at_utc": "2026-08-20T00:00:00Z",
    }
    return {
        "schema_version": "btc_okx_demo_paper_runtime_status_v1",
        "start_capability": start_capability or {},
        "runtime": {
            "status": runtime_status,
            "active": active,
            "worker_alive": effective_worker_alive,
            "authoritative_liveness_required": authoritative_liveness_required,
            "opening_allowed": opening_allowed,
            "cancel_only": cancel_only,
            "last_error": last_error,
            "blockers": blockers or [],
            "account_identity": dict(account_identity),
        },
        "risk_control": {
            "mode": risk_mode,
            "reason": risk_reason,
            "write_path_trusted": opening_allowed,
            "pending_order_intents": {},
            "dead_man": {
                "armed": opening_allowed,
                "heartbeat_thread_alive": active,
                "watchdog_renews_dead_man": opening_allowed,
                "last_error": "",
            },
        },
        "private_ws": {
            "status": private_ws_status,
            "connected": connected,
            "listener_alive": connected,
            "opening_allowed_after_reconciliation": connected,
            "blockers": private_ws_blockers or [],
        },
        "ledger_reconciliation": {
            "status": ledger_status,
            "current_state_exchange_snapshot_match": ledger_matches,
            "funding_cashflow_reconciled": funding_reconciled,
        },
        "exchange": {
            "captured_at_utc": "2026-08-20T00:00:00Z",
            "account": {
                "account_level": "2",
                "withdraw_permission_present": False,
                "identity": dict(account_identity),
            },
            "positions": positions,
            "pending_orders": pending_orders,
            "pending_algo_orders": pending_algo_orders,
        },
        "observation": {
            "blockers": observation_blockers or [],
            "promotion_evidence_ready": not bool(observation_blockers),
        },
        "safety": {
            "live_order_allowed": False,
            "real_money_order_allowed": False,
            "transfer_allowed": False,
            "withdraw_allowed": False,
            "permission_upgrade_allowed": False,
        },
    }


def _production_reconciliation_status_fixture() -> dict:
    """Use the native commit-ledger shape, not synthetic consistency flags."""

    observed = "2026-08-24T12:00:00+00:00"
    status = {
        "runtime": {
            "run_id": "run-production-shaped",
            "last_heartbeat_utc": observed,
            "authoritative_liveness_epoch": 7,
            "credential_namespace": "quant-system.okx-demo.trade",
        },
        "strategy": {
            "strategy_id": "long_short_donchian_top5",
            "strategy_version": "v1",
        },
        "limits": {
            "max_net_contracts": "0.01",
            "max_notional_usdt": "10",
        },
        "as_of_utc": observed,
        "private_ws": {
            "connected": True,
            "listener_alive": True,
            "reconciled": True,
            "generation": 3,
            "current_generation": 3,
        },
        "exchange": {
            "captured_at_utc": observed,
            "balance": {
                "equity_usdt": "5000",
                "unrealized_pnl_usdt": "0",
                "unrealized_pnl_observed": True,
            },
            "mark": {"mark_price": "60000"},
            "index": {"index_price": "60000"},
            "instrument": {
                "instrument_id": "BTC-USDT-SWAP",
                "contract_value_btc": "0.01",
            },
            "orders": [],
            "positions": [{
                "instrument_id": "BTC-USDT-SWAP",
                "position_side": "long",
                "contracts": "0.01",
                "realized_pnl": "0",
                "realized_pnl_observed": True,
                "unrealized_pnl": "0",
                "unrealized_pnl_observed": True,
            }],
            "fills": [{"pnl": "0", "pnl_observed": True}],
            "bills": [],
            "pending_orders": [],
            "pending_algo_orders": [],
        },
        "ledger_reconciliation": {
            "status": "reconciled",
            "current_state_exchange_snapshot_match": True,
            "funding_cashflow": "0",
            "funding_cashflow_reconciled": True,
            "funding_bill_count": 0,
            "order_count": 0,
            "position_count": 1,
            "fill_count": 1,
            "pending_order_count": 0,
            "pending_algo_order_count": 0,
            "ledger_hash": "ledger-hash",
            "exchange_snapshot_sha256": "",
            "last_funding_ledger_hash": "funding-hash",
        },
    }
    status["ledger_reconciliation"]["exchange_snapshot_sha256"] = canonical_ledger_snapshot_sha256(status["exchange"])
    return status


def test_operator_contract_projects_raw_commit_ledger_shape_end_to_end() -> None:
    service = btc_demo_runtime.BtcDemoRuntimeService(
        controller=StatusController(_production_reconciliation_status_fixture())
    )

    status = service._operator_contract_status()
    capability = status["protective_capabilities"]["stop_and_flatten"]

    assert capability["allowed"] is True
    assert capability["reduction_proof"] is True
    assert capability["reconciliation_evidence"]["source"] == "btc_demo_commit_ledger_reconciliation_v1"
    assert capability["reconciliation_evidence"]["pnl_consistent"] is True


def test_operator_contract_snapshot_fence_is_stable_after_legacy_start_is_historicalized(
    tmp_path,
) -> None:
    service = btc_demo_runtime.BtcDemoRuntimeService(
        controller=StatusController(_operator_status_fixture()),
        operator_operation_root=tmp_path,
    )
    service._operator_contract_status()
    operation, _ = service._operator_operation_store.begin(
        action="authoritative_preflight_start",
        payload={"mode": "demo"},
        idempotency_key="legacy-snapshot-fence-stability-001",
    )
    service._operator_operation_store.transition(
        operation.operation_id,
        state="blocked",
        phase="blocked",
        blockers=("legacy_blocker",),
        result_present=True,
    )

    first = service._operator_contract_status()
    persisted_after_first = json.loads(
        (
            tmp_path / "operator-contract-v2" / "operations.json"
        ).read_text(encoding="utf-8")
    )
    second = service._operator_contract_status()
    persisted_after_second = json.loads(
        (
            tmp_path / "operator-contract-v2" / "operations.json"
        ).read_text(encoding="utf-8")
    )

    assert persisted_after_first == persisted_after_second
    assert first["state_revision"] == second["state_revision"]
    assert first["state_digest"] == second["state_digest"]
    historical = second["historical_operator_operations"]
    assert len(historical) == 1
    assert historical[0]["state_revision"] == 3
    assert historical[0]["historical"] is True
    assert historical[0]["historical_reason_codes"] == [
        "operator_start_attempt_identity_missing"
    ]


def test_status_projects_service_restart_as_preflight_not_account_failure() -> None:
    service = btc_demo_runtime.BtcDemoRuntimeService(
        controller=StatusController(_operator_status_fixture())
    )

    status = service.status()
    control = status["operator_control"]

    assert control["schema_version"] == "btc_demo_operator_control_v1"
    assert control["lifecycle"] == "stopped_needs_preflight"
    assert control["lifecycle_label"] == "等待重新预检"
    assert control["incident"]["category"] == "service_restart"
    assert control["incident"]["impact_scope"] == "demo_start"
    assert control["allowed_actions"]["authoritative_preflight_start"] is True
    assert control["new_risk_allowed"] is False
    assert control["safe_mode"] == "frozen_unknown"
    assert control["safe_mode_label"] == "权威状态待确认"
    assert control["incident"]["impact_label"] == "仅阻止 Demo 启动"
    assert control["primary_action"]["code"] == "authoritative_preflight_start"


def test_status_blocks_start_when_local_runtime_capability_is_unavailable() -> None:
    payload = _operator_status_fixture(
        start_capability={
            "ready": False,
            "incident_category": "local_environment",
            "blockers": ["python_keyring_not_installed"],
        }
    )
    service = btc_demo_runtime.BtcDemoRuntimeService(
        controller=StatusController(payload)
    )

    control = service.status()["operator_control"]

    assert control["incident"]["category"] == "local_environment"
    assert control["incident"]["reason_codes"] == ["runtime_not_started", "python_keyring_not_installed"]
    assert control["allowed_actions"]["authoritative_preflight_start"] is False
    assert control["primary_action"]["code"] == "none"
    assert control["start_capability"]["ready"] is False


def test_status_projects_account_identity_incident_and_historical_start_blocker_fail_closed() -> None:
    old_blocker = "okx_demo_private_ws_startup_reconnect_probe_failed"
    independent_blocker = "okx_demo_ledger_reconciliation_required"
    payload = _operator_status_fixture(
        last_error=old_blocker,
        risk_reason=old_blocker,
        blockers=[old_blocker, independent_blocker],
        start_capability={
            "ready": False,
            "incident_category": "account_identity",
            "blockers": ["btc_demo_authoritative_account_identity_hash_missing"],
        },
    )
    payload["runtime"]["start_operation"] = {
        "operation_id": "historical-inner-1",
        "state": "blocked",
        "current_attempt": False,
        "historical": True,
        "blockers": [old_blocker],
        "terminal_error": old_blocker,
        "incident": {"category": "runtime_fault", "code": old_blocker},
        "historical_reason_codes": ["runtime_identity_changed"],
    }
    payload["runtime"].pop("account_identity")
    payload["exchange"]["account"].pop("identity")

    control = btc_demo_runtime.BtcDemoRuntimeService(
        controller=StatusController(payload)
    ).status()["operator_control"]

    assert control["incident"]["category"] == "account_identity"
    assert old_blocker not in control["incident"]["reason_codes"]
    assert independent_blocker in control["incident"]["reason_codes"]
    stages = {row["key"]: row for row in control["preflight_stages"]}
    assert stages["account"]["state"] in {"blocked", "waiting"}
    assert stages["account"]["state"] != "ready"
    assert control["allowed_actions"]["authoritative_preflight_start"] is False
    assert control["allowed_actions"]["refresh_account_snapshot"] is True


def test_status_projects_network_transport_separately_from_account_risk() -> None:
    payload = _operator_status_fixture(
        runtime_status="start_blocked_fail_closed",
        cancel_only=True,
        risk_reason="okx_demo_private_ws:private_ws_startup_probe_local_disconnect",
        last_error="URLError: connection reset",
        blockers=["okx_demo_private_ws:private_ws_startup_probe_local_disconnect"],
        private_ws_status="blocked",
        private_ws_blockers=["okx_demo_private_ws:private_ws_startup_probe_local_disconnect"],
    )
    service = btc_demo_runtime.BtcDemoRuntimeService(
        controller=StatusController(payload)
    )

    control = service.status()["operator_control"]

    assert control["incident"]["category"] == "network_transport"
    assert control["incident"]["current_attempt"] is True
    assert control["incident"]["impact_scope"] == "demo_start"
    assert control["allowed_actions"]["authoritative_preflight_start"] is True
    stages = {row["key"]: row for row in control["preflight_stages"]}
    assert stages["account"]["state"] == "ready"
    assert stages["private_ws"]["state"] == "blocked"


def test_status_keeps_historical_transport_error_out_of_current_incident_before_fresh_attempt() -> None:
    payload = _operator_status_fixture(
        runtime_status="stopped",
        risk_reason="runtime_not_started",
        last_error="URLError: previous attempt connection reset",
        blockers=["URLError: previous attempt connection reset"],
        private_ws_status="not_started",
        private_ws_blockers=["URLError: previous attempt connection reset"],
    )
    service = btc_demo_runtime.BtcDemoRuntimeService(
        controller=StatusController(payload)
    )

    control = service.status()["operator_control"]

    assert control["incident"]["category"] != "network_transport"
    assert control["incident"]["current_attempt"] is False
    assert control["allowed_actions"]["authoritative_preflight_start"] is True
    stages = {row["key"]: row for row in control["preflight_stages"]}
    assert stages["private_ws"]["state"] == "waiting"


def test_status_projects_recovered_authority_with_stopped_worker_as_runtime_recovery() -> None:
    payload = _operator_status_fixture(
        runtime_status="cancel_only",
        active=True,
        opening_allowed=False,
        cancel_only=True,
        risk_mode="FROZEN_UNKNOWN",
        risk_reason="okx_demo_authoritative_liveness_worker_stopped",
        last_error="okx_demo_transient:URLError: connection reset",
        blockers=[
            "okx_demo_authoritative_liveness_worker_stopped",
            "okx_demo_transient:URLError: connection reset",
        ],
        private_ws_status="connected",
        worker_alive=False,
        authoritative_liveness_required=True,
    )
    service = btc_demo_runtime.BtcDemoRuntimeService(
        controller=StatusController(payload)
    )

    control = service.status()["operator_control"]

    assert control["incident"]["category"] == "runtime_recovery"
    assert control["incident"]["title"] == "运行时恢复中"
    assert "REST、Private WS 与账本已恢复" in control["incident"]["summary"]
    assert control["incident"]["impact_scope"] == "new_risk_only"
    stages = {row["key"]: row for row in control["preflight_stages"]}
    assert stages["private_ws"]["state"] == "ready"


def test_status_keeps_current_private_ws_loss_as_network_transport_even_with_stopped_worker() -> None:
    payload = _operator_status_fixture(
        runtime_status="cancel_only",
        active=True,
        opening_allowed=False,
        cancel_only=True,
        risk_mode="FROZEN_UNKNOWN",
        risk_reason="okx_demo_authoritative_liveness_worker_stopped",
        last_error="okx_demo_transient:URLError: connection reset",
        blockers=[
            "okx_demo_authoritative_liveness_worker_stopped",
            "okx_demo_transient:URLError: connection reset",
        ],
        private_ws_status="blocked",
        private_ws_blockers=["private_ws_reconnect_unavailable"],
        worker_alive=False,
        authoritative_liveness_required=True,
    )
    service = btc_demo_runtime.BtcDemoRuntimeService(
        controller=StatusController(payload)
    )

    control = service.status()["operator_control"]

    assert control["incident"]["category"] == "network_transport"
    stages = {row["key"]: row for row in control["preflight_stages"]}
    assert stages["private_ws"]["state"] == "blocked"


def test_status_projects_expected_startup_disconnect_as_preflight_progress() -> None:
    payload = _operator_status_fixture(
        runtime_status="starting",
        risk_reason="private_ws_startup_probe_local_disconnect",
        last_error="private_ws_startup_probe_local_disconnect",
        blockers=["private_ws_startup_probe_local_disconnect"],
        private_ws_status="starting",
        private_ws_blockers=["private_ws_startup_probe_local_disconnect"],
    )
    service = btc_demo_runtime.BtcDemoRuntimeService(
        controller=StatusController(payload)
    )

    control = service.status()["operator_control"]

    assert control["lifecycle"] == "starting_preflight"
    assert control["incident"]["category"] == "preflight_progress"
    assert control["incident"]["severity"] == "info"
    assert control["allowed_actions"]["authoritative_preflight_start"] is False
    assert control["new_risk_allowed"] is False


def test_status_limits_running_network_incident_to_new_risk_only() -> None:
    payload = _operator_status_fixture(
        runtime_status="running",
        active=True,
        opening_allowed=False,
        cancel_only=True,
        risk_mode="FROZEN_UNKNOWN",
        risk_reason="okx_demo_private_ws_reconnect_failed",
        last_error="URLError: connection reset",
        blockers=["okx_demo_private_ws_reconnect_failed"],
        private_ws_status="blocked",
        private_ws_blockers=["okx_demo_private_ws_reconnect_failed"],
    )
    service = btc_demo_runtime.BtcDemoRuntimeService(
        controller=StatusController(payload)
    )

    control = service.status()["operator_control"]

    assert control["lifecycle"] == "degraded_no_new_risk"
    assert control["incident"]["category"] == "network_transport"
    assert control["incident"]["impact_scope"] == "new_risk_only"
    assert control["new_risk_allowed"] is False
    assert control["allowed_actions"]["stop_keep_position"] is True


def test_status_projects_known_position_as_account_risk_without_direct_start() -> None:
    payload = _operator_status_fixture(
        runtime_status="blocked_fail_closed",
        cancel_only=True,
        risk_reason="okx_demo_nonflat_position_has_no_verified_protection",
        positions=[{"position_side": "long", "contracts": "0.01"}],
    )
    service = btc_demo_runtime.BtcDemoRuntimeService(
        controller=StatusController(payload)
    )

    control = service.status()["operator_control"]

    assert control["incident"]["category"] == "account_risk"
    assert control["incident"]["impact_scope"] == "account_and_order_safety"
    assert control["allowed_actions"]["authoritative_preflight_start"] is True
    assert control["allowed_actions"]["direct_start"] is False
    assert control["new_risk_allowed"] is False
    stages = {row["key"]: row for row in control["preflight_stages"]}
    assert stages["positions_orders_oco"]["state"] == "blocked"


def test_status_keeps_promotion_evidence_out_of_demo_start_incident() -> None:
    payload = _operator_status_fixture(
        runtime_status="running",
        active=True,
        opening_allowed=True,
        risk_mode="RUNNING",
        risk_reason="startup_complete",
        private_ws_status="connected",
        observation_blockers=["btc_okx_native:25_hour_demo_observation_window_incomplete"],
    )
    service = btc_demo_runtime.BtcDemoRuntimeService(
        controller=StatusController(payload)
    )

    control = service.status()["operator_control"]

    assert control["lifecycle"] == "running"
    assert control["incident"]["category"] == "none"
    assert control["evidence"]["status"] == "incomplete"
    assert control["evidence"]["impact_scope"] == "promotion_only"
    assert control["evidence"]["blocks_demo_start"] is False
    assert control["allowed_actions"]["stop_keep_position"] is True
    assert control["allowed_actions"]["stop_and_flatten"] is False


def test_status_does_not_label_a_running_protected_position_as_account_incident() -> None:
    payload = _operator_status_fixture(
        runtime_status="running",
        active=True,
        opening_allowed=True,
        risk_mode="RUNNING",
        risk_reason="startup_complete",
        private_ws_status="connected",
        positions=[{"position_side": "long", "contracts": "0.01"}],
        pending_algo_orders=[{
            "algo_id": "demo-protection-1",
            "order_type": "oco",
            "state": "live",
        }],
    )
    service = btc_demo_runtime.BtcDemoRuntimeService(
        controller=StatusController(payload)
    )

    control = service.status()["operator_control"]

    assert control["lifecycle"] == "running"
    assert control["incident"]["category"] == "none"
    assert control["new_risk_allowed"] is True
    assert control["allowed_actions"]["stop_keep_position"] is True
    # The fixture's attached algo has no owner/instrument/side/quantity
    # proof, so it is intentionally not actionable as a protective exit.
    assert control["allowed_actions"]["stop_and_flatten"] is False


def test_status_exposes_protective_projection_errors_without_latch_path_or_action_authority(monkeypatch) -> None:
    def raise_unexpected(*args, **kwargs):
        raise RuntimeError("unexpected projection failure")

    monkeypatch.setattr(btc_demo_runtime, "derive_protective_capabilities", raise_unexpected)
    service = btc_demo_runtime.BtcDemoRuntimeService(
        controller=StatusController(_operator_status_fixture())
    )

    status = service.status()
    control = status["operator_control"]
    assert control["protective_capability_blockers"] == [
        "protective_capability_projection_unexpected_error"
    ]
    assert control["allowed_actions"]["stop_and_flatten"] is False
    assert control["allowed_actions"]["emergency_reduce_only_exit"] is False
    assert "guardian_latch.json" not in str(status)
    assert status["protective_capabilities"]["projection_error_type"] == "RuntimeError"


def test_status_guardian_projection_is_get_only_and_does_not_create_latch_files(tmp_path) -> None:
    controller = StatusController(_operator_status_fixture())
    controller.config = type("Config", (), {"output_dir": tmp_path})()
    service = btc_demo_runtime.BtcDemoRuntimeService(controller=controller)

    status = service.status()
    assert status["guardian"]["persistence_state"] == "missing"
    assert not (tmp_path / "guardian_latch.json").exists()
    assert not (tmp_path / "guardian_latch.lock").exists()
    assert str(tmp_path) not in str(status)


def test_status_guardian_persistence_error_is_observable_without_physical_latch_path(monkeypatch, tmp_path) -> None:
    controller = StatusController(_operator_status_fixture())
    controller.config = type("Config", (), {"output_dir": tmp_path})()

    def raise_corrupt(*args, **kwargs):
        raise OSError(f"cannot read {tmp_path / 'guardian_latch.json'}")

    monkeypatch.setattr(btc_demo_runtime.FileGuardianLatchStore, "load_optional", raise_corrupt)
    status = btc_demo_runtime.BtcDemoRuntimeService(controller=controller).status()

    guardian = status["guardian"]
    assert guardian["persistence_state"] == "corrupt_or_unavailable"
    assert guardian["reason_codes"] == ["latch_persistence_read_failed"]
    assert guardian["persistence_error_code"] == "latch_persistence_read_failed"
    assert guardian["persistence_error_type"] == "OSError"
    assert str(tmp_path) not in str(status)
    assert "guardian_latch.json" not in str(status)


def test_emergency_exit_forwards_only_to_canonical_controller() -> None:
    service = btc_demo_runtime.BtcDemoRuntimeService(controller=FakeController())

    result = service.emergency_reduce_only_exit(
        {"operator_action": "fresh_state_emergency_reduce_only_exit"}
    )

    assert result["orders_posted"] == 1
    assert result["opening_allowed"] is False
    assert result["cancel_only"] is True


def test_stop_and_flatten_forwards_only_to_canonical_controller() -> None:
    controller = FakeController()
    service = btc_demo_runtime.BtcDemoRuntimeService(controller=controller)

    result = service.stop_and_flatten({"confirmation_text": "STOP AND FLATTEN"})

    assert result["final_flat"] is True
    assert result["orders_posted"] == 0
    assert controller.stop_and_flatten_calls == [{"confirmation_text": "STOP AND FLATTEN"}]


def test_stop_and_flatten_fails_closed_without_controller_capability() -> None:
    class NoFlattenController:
        def status(self) -> dict:
            return {}

    service = btc_demo_runtime.BtcDemoRuntimeService(controller=NoFlattenController())

    with pytest.raises(RuntimeError, match="stop_and_flatten_controller_capability_missing"):
        service.stop_and_flatten({"confirmation_text": "STOP AND FLATTEN"})


def test_emergency_exit_fails_closed_without_controller_capability() -> None:
    class NoEmergencyController:
        def status(self) -> dict:
            return {}

    service = btc_demo_runtime.BtcDemoRuntimeService(
        controller=NoEmergencyController()
    )

    with pytest.raises(
        RuntimeError,
        match="controller_capability_missing",
    ):
        service.emergency_reduce_only_exit({})


def test_readonly_chart_prefers_active_controller_okx_completed_hour_cache(
    monkeypatch,
) -> None:
    class CachedChartController(FakeController):
        def readonly_chart_payload(self, *, limit: int) -> dict:
            assert limit == 77
            return {
                "source_kind": "okx_runtime_confirmed_completed_swap_1h",
                "sample_end": "2026-08-16T11:00:00+00:00",
                "rows": [{"open_time_ms": 1}],
            }

    def unexpected_fallback(**_kwargs):
        raise AssertionError("active runtime chart must not fall back to disk")

    monkeypatch.setattr(
        btc_demo_runtime,
        "load_btc_chart_payload",
        unexpected_fallback,
    )
    service = btc_demo_runtime.BtcDemoRuntimeService(
        controller=CachedChartController()
    )

    payload = service.readonly_klines(limit=77)

    assert payload["source_kind"] == (
        "okx_runtime_confirmed_completed_swap_1h"
    )
    assert payload["sample_end"] == "2026-08-16T11:00:00+00:00"


def test_market_view_uses_public_loader_when_runtime_cache_is_absent_and_never_chart_fallback(monkeypatch) -> None:
    class InactiveController(FakeController):
        def readonly_chart_payload(self, *, limit: int) -> None:
            return None

    def unexpected_chart_fallback(**_kwargs):
        raise AssertionError("public market view must never masquerade as completed baseline")

    monkeypatch.setattr(btc_demo_runtime, "load_btc_chart_payload", unexpected_chart_fallback)
    service = btc_demo_runtime.BtcDemoRuntimeService(
        controller=InactiveController(),
        public_market_loader=lambda timeframe, limit: {
            "source_kind": "okx_public_market_view_v1",
            "timeframe": timeframe,
            "limit": limit,
            "public_only": True,
            "strategy_signal_compatible": False,
            "candles": [],
        },
    )

    payload = service.readonly_market_view(timeframe="1m", limit=120)

    assert payload["source_kind"] == "okx_public_market_view_v1"
    assert payload["strategy_signal_compatible"] is False
    assert payload["public_only"] is True


@pytest.mark.parametrize("timeframe", ["1m", "5m", "15m", "1h", "4h", "1d", "1w", "1M"])
def test_market_view_allowlist_is_consistent_for_all_public_visual_timeframes(
    timeframe: str,
) -> None:
    seen: list[str] = []
    service = btc_demo_runtime.BtcDemoRuntimeService(
        controller=FakeController(),
        public_market_loader=lambda received_timeframe, limit: (
            seen.append(received_timeframe)
            or {
                "source_kind": "okx_public_market_view_v1",
                "timeframe": received_timeframe,
                "limit": limit,
                "public_only": True,
                "strategy_signal_compatible": False,
                "candles": [],
            }
        ),
    )

    assert service.readonly_market_view(timeframe=timeframe, limit=120)["timeframe"] == timeframe
    assert seen == [timeframe]


def test_market_view_returns_stale_last_good_or_structured_unavailable(monkeypatch) -> None:
    class InactiveController(FakeController):
        def readonly_chart_payload(self, *, limit: int) -> None:
            return None

    now = [100.0]
    calls = [0]

    def loader(timeframe: str, limit: int) -> dict[str, object]:
        calls[0] += 1
        if calls[0] > 1:
            raise RuntimeError("mock_public_transport_down")
        return {
            "source_kind": "okx_public_market_view_v1",
            "timeframe": timeframe,
            "limit": limit,
            "public_only": True,
            "strategy_signal_compatible": False,
            "candles": [],
        }

    monkeypatch.setattr(btc_demo_runtime.time, "monotonic", lambda: now[0])
    service = btc_demo_runtime.BtcDemoRuntimeService(
        controller=InactiveController(),
        public_market_loader=loader,
    )

    assert service.readonly_market_view(timeframe="1m", limit=120)["stale"] is False
    now[0] += 6.0
    assert service.readonly_market_view(timeframe="1m", limit=120)["stale"] is True

    unavailable = btc_demo_runtime.BtcDemoRuntimeService(
        controller=InactiveController(),
        public_market_loader=lambda *_args: (_ for _ in ()).throw(RuntimeError("down")),
    )
    with pytest.raises(RuntimeError, match="okx_demo_public_market_unavailable"):
        unavailable.readonly_market_view(timeframe="1m", limit=120)


def test_market_view_refresh_has_one_leader_and_stale_follower(monkeypatch) -> None:
    now = [100.0]
    calls = [0]
    started = threading.Event()
    release = threading.Event()

    def loader(timeframe: str, limit: int) -> dict[str, object]:
        calls[0] += 1
        if calls[0] == 1:
            return {
                "source_kind": "okx_public_market_view_v1",
                "timeframe": timeframe,
                "limit": limit,
                "public_only": True,
                "strategy_signal_compatible": False,
                "candles": [],
            }
        started.set()
        assert release.wait(2.0)
        return {
            "source_kind": "okx_public_market_view_v1",
            "timeframe": timeframe,
            "limit": limit,
            "public_only": True,
            "strategy_signal_compatible": False,
            "candles": [],
        }

    monkeypatch.setattr(btc_demo_runtime.time, "monotonic", lambda: now[0])
    service = btc_demo_runtime.BtcDemoRuntimeService(
        controller=FakeController(),
        public_market_loader=loader,
    )
    assert service.readonly_market_view(timeframe="1m", limit=120)["stale"] is False
    now[0] += 6.0

    leader_result: list[dict[str, object]] = []
    leader = threading.Thread(
        target=lambda: leader_result.append(
            service.readonly_market_view(timeframe="1m", limit=120)
        ),
        daemon=True,
    )
    leader.start()
    assert started.wait(1.0)

    follower = service.readonly_market_view(timeframe="1m", limit=120)
    assert follower["stale"] is True
    assert follower["last_error_code"] == "okx_demo_public_market_refresh_in_flight"
    assert calls[0] == 2

    release.set()
    leader.join(2.0)
    assert not leader.is_alive()
    assert leader_result and leader_result[0]["stale"] is False


def test_cold_stopped_operator_contract_keeps_refresh_bootstrap_available(tmp_path) -> None:
    status = _operator_status_fixture(
        start_capability={
            "ready": False,
            "blockers": ["btc_demo_authoritative_account_identity_hash_missing"],
        },
    )
    status["runtime"].update(
        {
            "runtime_identity": "btc-demo-runtime:cold-start",
            "state_revision": 0,
            "started_at_utc": "",
            "stopped_at_utc": "",
            "last_heartbeat_utc": "",
        }
    )
    status["events"] = []
    service = btc_demo_runtime.BtcDemoRuntimeService(
        controller=StatusController(status),
        operator_operation_root=tmp_path,
    )

    first = service.operator_contract_v2()
    second = service.operator_contract_v2()
    refresh = next(
        row for row in first["actions"]
        if row["action"] == "refresh_account_snapshot"
    )
    start = next(
        row for row in first["actions"]
        if row["action"] == "authoritative_preflight_start"
    )

    assert first["as_of_utc"]
    assert first["as_of_utc"] == second["as_of_utc"]
    assert refresh["allowed"] is True
    assert start["allowed"] is False
    assert "btc_demo_authoritative_account_identity_hash_missing" in start["blocker_codes"]


def test_market_ticker_is_public_get_only_and_reuses_short_cache(monkeypatch) -> None:
    now = [100.0]
    calls = [0]

    class PublicClient:
        def ticker(self) -> dict[str, str | int]:
            calls[0] += 1
            return {
                "bid": "62043",
                "ask": "62045",
                "last": "62044",
                "timestamp_ms": 1783994400000,
            }

    monkeypatch.setattr(btc_demo_runtime.time, "monotonic", lambda: now[0])
    service = btc_demo_runtime.BtcDemoRuntimeService(controller=FakeController())
    service._public_market_client = PublicClient()  # type: ignore[assignment]

    first = service.readonly_market_ticker()
    now[0] += 1.0
    second = service.readonly_market_ticker()

    assert calls[0] == 1
    assert first["schema_version"] == "okx_public_market_ticker_v1"
    assert second["ticker"]["last"] == "62044"
    assert second["cache_age_ms"] == 1000
    assert second["public_only"] is True
    assert second["private_endpoint_used"] is False
    assert second["order_endpoint_used"] is False


def test_market_view_refresh_follower_without_cache_fails_fast(monkeypatch) -> None:
    started = threading.Event()
    release = threading.Event()
    calls = [0]

    def loader(_timeframe: str, _limit: int) -> dict[str, object]:
        calls[0] += 1
        started.set()
        assert release.wait(2.0)
        raise RuntimeError("down")

    service = btc_demo_runtime.BtcDemoRuntimeService(
        controller=FakeController(),
        public_market_loader=loader,
    )
    leader_errors: list[Exception] = []
    leader = threading.Thread(
        target=lambda: _capture_exception(
            lambda: service.readonly_market_view(timeframe="1m", limit=120),
            leader_errors,
        ),
        daemon=True,
    )
    leader.start()
    assert started.wait(1.0)

    with pytest.raises(RuntimeError, match="okx_demo_public_market_unavailable"):
        service.readonly_market_view(timeframe="1m", limit=120)
    assert calls[0] == 1

    release.set()
    leader.join(2.0)
    assert not leader.is_alive()
    assert leader_errors and isinstance(leader_errors[0], RuntimeError)


def _capture_exception(action, errors: list[Exception]) -> None:
    try:
        action()
    except Exception as exc:  # pragma: no cover - assertion is made by caller
        errors.append(exc)


def test_market_view_uses_public_rest_books_when_ws_depth_is_missing() -> None:
    class PublicClient:
        def ticker(self) -> dict[str, str | int]:
            return {"bid": "62043", "ask": "62045", "last": "62044", "timestamp_ms": 1783994400000}

        def candles(self, *, timeframe: str, limit: int) -> list[dict[str, object]]:
            return [{"open_time_ms": 1783994340000, "open": 62040, "high": 62045, "low": 62039, "close": 62044, "volume": 1, "confirmed": False, "in_progress": True}]

        def books(self) -> dict[str, object]:
            return {
                "source": "okx_public_rest_books5",
                "instrument_id": "BTC-USDT-SWAP",
                "bids": [{"price": "62043", "size": "2", "count": "3"}] * 5,
                "asks": [{"price": "62045", "size": "2", "count": "4"}] * 5,
                "spread": "2",
                "top5_imbalance": 0.5,
                "timestamp_ms": 1783994400000,
                "sequence": 7,
                "checksum": "123",
            }

    class StaleStream:
        def snapshot(self) -> dict[str, object]:
            return {"status": "stale", "depth": None}

    service = btc_demo_runtime.BtcDemoRuntimeService(controller=FakeController())
    service._public_market_client = PublicClient()  # type: ignore[assignment]
    service._public_market_stream = StaleStream()  # type: ignore[assignment]

    payload = service.readonly_market_view(timeframe="1m", limit=120)

    assert payload["depth_source"] == "okx_public_rest_books5"
    assert payload["depth"]["asks"][0]["price"] == "62045"
    assert payload["depth"]["bids"][0]["price"] == "62043"
    assert payload["public_only"] is True
    assert payload["private_endpoint_used"] is False
    assert payload["order_endpoint_used"] is False


def test_market_view_prefers_live_public_ws_depth_over_rest_fallback() -> None:
    class PublicClient:
        def ticker(self) -> dict[str, str | int]:
            return {"bid": "62043", "ask": "62045", "last": "62044", "timestamp_ms": 1783994400000}

        def candles(self, *, timeframe: str, limit: int) -> list[dict[str, object]]:
            return [{"open_time_ms": 1783994340000, "open": 62040, "high": 62045, "low": 62039, "close": 62044, "volume": 1, "confirmed": False, "in_progress": True}]

        def books(self) -> dict[str, object]:
            raise AssertionError("live WS depth must not trigger REST fallback")

    class LiveStream:
        def snapshot(self) -> dict[str, object]:
            return {
                "status": "live",
                "depth": {
                    "source": "okx_public_ws",
                    "instrument_id": "BTC-USDT-SWAP",
                    "bids": [{"price": "62043", "size": "2", "count": "3"}] * 5,
                    "asks": [{"price": "62045", "size": "2", "count": "4"}] * 5,
                    "spread": "2",
                    "top5_imbalance": 0.5,
                    "timestamp_ms": 1783994400000,
                    "sequence": 8,
                },
            }

    service = btc_demo_runtime.BtcDemoRuntimeService(controller=FakeController())
    service._public_market_client = PublicClient()  # type: ignore[assignment]
    service._public_market_stream = LiveStream()  # type: ignore[assignment]

    payload = service.readonly_market_view(timeframe="1m", limit=120)

    assert payload["depth_source"] == "okx_public_ws"
    assert payload["depth"]["sequence"] == 8


def test_catalog_uses_demo_data_gate_without_weakening_promotion_gate(monkeypatch) -> None:
    monkeypatch.setattr(
        btc_demo_runtime,
        "inspect_okx_native_demo_signal_data",
        lambda _root, **_kwargs: {
            "eligible": True,
            "integrity_passed": True,
            "freshness_status": "pass",
            "blockers": [],
            "promotion_current_head_required": False,
        },
    )

    catalog = btc_demo_runtime.BtcDemoRuntimeService(controller=FakeController()).catalog()
    native = next(row for row in catalog["strategies"] if row["strategy_id"] == OKX_NATIVE_STRATEGY_LINE)

    assert native["demo_selectable"] is True
    assert native["native_demo_data_readiness"]["eligible"] is True
    assert native["native_evidence_freshness"] == {
        "status": "separate_promotion_gate",
        "blocks_demo_start": False,
    }
    assert catalog["default_strategy_id"] == OKX_NATIVE_STRATEGY_LINE
    assert catalog["default_reason"] == "okx_native_demo_data_contract_passed"
    assert native["native_runtime_data_policy"] == {
        "baseline_role": "fresh_signal_source",
        "baseline_freshness_status": "pass",
        "runtime_public_tail_required": False,
        "runtime_public_tail_endpoint": "",
    }
    assert catalog["risk_profile"]["name"] == "baseline_1x"
    assert catalog["risk_profile"]["max_configured_leverage"] == "1"
    assert catalog["safety"]["live_order_allowed"] is False
    assert catalog["safety"]["real_money_order_allowed"] is False


def test_catalog_admits_integrity_verified_stale_native_seed_for_public_tail(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        btc_demo_runtime,
        "inspect_okx_native_demo_signal_data",
        lambda _root, **_kwargs: {
            "eligible": False,
            "integrity_passed": True,
            "freshness_status": "stale",
            "blockers": [
                "okx_demo_paper_okx_native_completed_1h_stale",
            ],
            "promotion_current_head_required": False,
        },
    )

    catalog = btc_demo_runtime.BtcDemoRuntimeService(
        controller=FakeController()
    ).catalog()
    native = next(
        row
        for row in catalog["strategies"]
        if row["strategy_id"] == OKX_NATIVE_STRATEGY_LINE
    )

    assert native["demo_selectable"] is True
    assert native["demo_blocker"] == ""
    assert native["native_demo_data_readiness"]["eligible"] is False
    assert native["native_demo_data_readiness"]["freshness_status"] == "stale"
    assert native["native_runtime_data_policy"] == {
        "baseline_role": "immutable_integrity_verified_stale_seed_only",
        "baseline_freshness_status": "stale",
        "runtime_public_tail_required": True,
        "runtime_public_tail_endpoint": "/api/v5/market/candles",
    }
    assert catalog["default_strategy_id"] == OKX_NATIVE_STRATEGY_LINE
    assert (
        catalog["default_reason"]
        == "okx_native_stale_seed_public_tail_required"
    )
    assert catalog["safety"]["live_order_allowed"] is False
    assert catalog["safety"]["real_money_order_allowed"] is False


@pytest.mark.parametrize(
    ("integrity_passed", "blockers"),
    [
        (
            True,
            [
                "okx_demo_paper_okx_native_completed_1h_stale",
                "okx_demo_paper_okx_native_history_gap",
            ],
        ),
        (
            False,
            ["okx_demo_paper_okx_native_completed_1h_stale"],
        ),
        (
            True,
            ["okx_demo_paper_okx_native_history_gap"],
        ),
    ],
)
def test_catalog_rejects_unsafe_native_stale_seed_admission(
    monkeypatch,
    integrity_passed,
    blockers,
) -> None:
    monkeypatch.setattr(
        btc_demo_runtime,
        "inspect_okx_native_demo_signal_data",
        lambda _root, **_kwargs: {
            "eligible": False,
            "integrity_passed": integrity_passed,
            "freshness_status": "stale",
            "blockers": blockers,
            "promotion_current_head_required": False,
        },
    )

    catalog = btc_demo_runtime.BtcDemoRuntimeService(
        controller=FakeController()
    ).catalog()
    native = next(
        row
        for row in catalog["strategies"]
        if row["strategy_id"] == OKX_NATIVE_STRATEGY_LINE
    )

    assert native["demo_selectable"] is False
    assert native["native_runtime_data_policy"]["baseline_role"] == "not_admitted"
    assert native["native_runtime_data_policy"]["runtime_public_tail_required"] is False
    assert catalog["default_strategy_id"] != OKX_NATIVE_STRATEGY_LINE
    assert catalog["default_reason"] == "binance_historical_fallback_fail_closed"


def test_backend_composition_caps_demo_runtime_at_one_x(monkeypatch) -> None:
    captured = {}

    class CapturingController(FakeController):
        def __init__(self, *, config) -> None:
            captured["config"] = config

    monkeypatch.setattr(
        btc_demo_runtime,
        "OkxDemoPaperRuntimeController",
        CapturingController,
    )

    btc_demo_runtime.BtcDemoRuntimeService()

    assert captured["config"].max_configured_leverage == Decimal("1")
    assert isinstance(
        captured["config"].execution_dispatcher,
        BTCDemoExecutionDispatcher,
    )
    assert callable(captured["config"].authoritative_oms_bundle_provider)


def test_backend_composition_selects_demo_only_three_x_stress_profile(
    monkeypatch,
) -> None:
    captured = {}

    class CapturingController(FakeController):
        def __init__(self, *, config) -> None:
            captured["config"] = config

    monkeypatch.setattr(
        btc_demo_runtime,
        "OkxDemoPaperRuntimeController",
        CapturingController,
    )

    service = btc_demo_runtime.BtcDemoRuntimeService(
        risk_profile="stress_3x"
    )
    status = service.status()

    assert captured["config"].max_configured_leverage == Decimal("3")
    assert callable(captured["config"].authoritative_oms_bundle_provider)
    assert (
        captured["config"].okx_native_shared_manifest_git_spec
        == btc_demo_runtime._OKX_NATIVE_DEMO_MANIFEST_GIT_SPEC
    )
    assert (
        captured["config"].okx_native_expected_dataset_id
        == btc_demo_runtime._OKX_NATIVE_DEMO_DATASET_ID
    )
    assert captured["config"].okx_native_shared_data_root is not None
    assert status["risk_profile"] == {
        "schema_version": "btc_demo_risk_profile_v1",
        "name": "stress_3x",
        "scope": "okx_demo_only",
        "instrument_id": "BTC-USDT-SWAP",
        "margin_mode": "isolated",
        "max_configured_leverage": "3",
        "max_order_notional_usdt": "10",
        "real_money_max_leverage_unchanged": "1",
        "auto_start_on_backend_launch": False,
        "live_order_allowed": False,
        "real_money_order_allowed": False,
    }


def test_unknown_demo_risk_profile_fails_closed_to_one_x(
    monkeypatch,
) -> None:
    captured = {}

    class CapturingController(FakeController):
        def __init__(self, *, config) -> None:
            captured["config"] = config

    monkeypatch.setattr(
        btc_demo_runtime,
        "OkxDemoPaperRuntimeController",
        CapturingController,
    )

    service = btc_demo_runtime.BtcDemoRuntimeService(
        risk_profile="unsafe_unknown_profile"
    )

    assert captured["config"].max_configured_leverage == Decimal("1")
    assert service.status()["risk_profile"]["name"] == "baseline_1x"


def test_official_catalog_inspector_uses_only_committed_corr1_manifest(
    monkeypatch,
) -> None:
    captured = {}

    def inspect(_root, **kwargs):
        captured.update(kwargs)
        return {
            "eligible": False,
            "blockers": [
                "btc_okx_native:25_hour_demo_observation_window_incomplete"
            ],
        }

    monkeypatch.setattr(
        btc_demo_runtime,
        "inspect_okx_native_demo_signal_data",
        inspect,
    )

    service = btc_demo_runtime.BtcDemoRuntimeService(
        controller=FakeController()
    )
    catalog = service.catalog()

    assert (
        captured["shared_manifest_git_spec"]
        == btc_demo_runtime._OKX_NATIVE_DEMO_MANIFEST_GIT_SPEC
    )
    assert (
        captured["expected_dataset_id"]
        == btc_demo_runtime._OKX_NATIVE_DEMO_DATASET_ID
    )
    assert captured["shared_data_root"].is_absolute()
    native = next(
        row
        for row in catalog["strategies"]
        if row["strategy_id"] == OKX_NATIVE_STRATEGY_LINE
    )
    assert native["demo_selectable"] is False
