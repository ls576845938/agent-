from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from quant_crypto.monitoring.okx_demo_execution_watchdog import (
    OkxDemoExecutionWatchdogConfig,
    evaluate_okx_demo_execution_state,
    inspect_okx_demo_execution_runtime,
)
from quant_crypto.oms.runtime_store import BTCRuntimeStore


NOW = datetime(2026, 8, 5, 12, 0, tzinfo=timezone.utc)


def _healthy_state() -> dict:
    return {
        "runtime": {
            "run_id": "demo-p0",
            "active": True,
            "last_heartbeat_utc": (NOW - timedelta(seconds=10)).isoformat(),
        },
        "risk_control": {
            "mode": "RUNNING",
            "pending_order_intents": {},
            "active_protection": {
                "status": "exchange_accepted",
                "algo_client_order_id": "protect-1",
                "instrument_id": "BTC-USDT-SWAP",
                "position_side": "long",
                "contracts": "0.01",
                "market_exit": True,
                "tp_trigger_px": "60600",
                "sl_trigger_px": "59400",
            },
            "dead_man": {
                "armed": True,
                "timeout_seconds": 30,
                "last_ack_utc": (NOW - timedelta(seconds=5)).isoformat(),
            },
        },
        "exchange": {
            "positions": [
                {
                    "position_side": "long",
                    "contracts": "0.01",
                }
            ],
            "pending_algo_orders": [
                {
                    "algo_client_order_id": "protect-1",
                    "instrument_id": "BTC-USDT-SWAP",
                    "position_side": "long",
                    "size": "0.01",
                    "state": "live",
                    "take_profit_trigger": "60600",
                    "take_profit_trigger_type": "mark",
                    "take_profit_order_price": "-1",
                    "stop_loss_trigger": "59400",
                    "stop_loss_trigger_type": "mark",
                    "stop_loss_order_price": "-1",
                }
            ],
        },
        "ledger_reconciliation": {
            "status": "reconciled",
            "current_state_exchange_snapshot_match": True,
        },
        "private_ws": {"connected": True, "listener_alive": True},
        "safety": {
            "live_order_allowed": False,
            "real_money_order_allowed": False,
            "transfer_allowed": False,
            "withdraw_allowed": False,
            "permission_upgrade_allowed": False,
        },
    }


def test_watchdog_accepts_current_worker_with_exchange_hosted_protection() -> None:
    report = evaluate_okx_demo_execution_state(
        _healthy_state(),
        observed_at_utc=NOW,
    )

    assert report["status"] == "healthy"
    assert report["signed_contracts"] == "0.01"
    assert report["gross_contracts"] == "0.01"
    assert report["exchange_protection_verified"] is True
    assert report["alerts"] == []
    assert report["capabilities"] == {
        "same_host_only": True,
        "process_isolation_only": True,
        "power_redundancy": False,
        "network_redundancy": False,
        "loads_credentials": False,
        "renews_dead_man": False,
        "calls_private_endpoint": False,
        "calls_order_endpoint": False,
        "calls_transfer_endpoint": False,
        "calls_withdraw_endpoint": False,
    }


def test_watchdog_detects_killed_worker_and_nonflat_unprotected_position() -> None:
    state = _healthy_state()
    state["runtime"]["last_heartbeat_utc"] = (
        NOW - timedelta(minutes=5)
    ).isoformat()
    state["risk_control"]["dead_man"]["last_ack_utc"] = (
        NOW - timedelta(minutes=5)
    ).isoformat()
    state["risk_control"]["active_protection"] = {}
    state["exchange"]["pending_algo_orders"] = []

    report = evaluate_okx_demo_execution_state(
        state,
        observed_at_utc=NOW,
    )

    assert report["status"] == "critical"
    codes = {row["code"] for row in report["alerts"]}
    assert "okx_demo_watchdog_worker_heartbeat_stale" in codes
    assert "okx_demo_watchdog_dead_man_ack_stale" in codes
    assert "okx_demo_watchdog_nonflat_without_exchange_protection" in codes


def test_watchdog_uses_persisted_stale_liveness_even_when_opening_flag_is_true(
    tmp_path: Path,
) -> None:
    runtime_root = tmp_path / "runtime"
    state = _healthy_state()
    state["runtime"].update(
        {
            "opening_allowed": True,
            "last_heartbeat_utc": (
                NOW - timedelta(minutes=5)
            ).isoformat(),
        }
    )
    state["risk_control"]["dead_man"]["last_ack_utc"] = (
        NOW - timedelta(minutes=5)
    ).isoformat()
    store = BTCRuntimeStore(runtime_root)
    store.recover()
    store.checkpoint(state)
    checkpoint_before = (runtime_root / "state.json").read_bytes()

    report = inspect_okx_demo_execution_runtime(
        OkxDemoExecutionWatchdogConfig(runtime_root=runtime_root),
        now=NOW,
        write_alert=False,
    )

    assert report["status"] == "critical"
    assert {
        row["code"] for row in report["alerts"]
    } >= {
        "okx_demo_watchdog_worker_heartbeat_stale",
        "okx_demo_watchdog_dead_man_ack_stale",
    }
    assert (runtime_root / "state.json").read_bytes() == checkpoint_before


def test_watchdog_detects_stale_reconciliation_and_unknown_exchange_order() -> None:
    state = _healthy_state()
    state["runtime"]["last_reconciled_at_utc"] = "2026-08-04T23:00:00+00:00"
    state["risk_control"]["owned_client_order_ids"] = ["owned-order"]
    state["exchange"]["pending_orders"] = [
        {"client_order_id": "unknown-order", "state": "live"}
    ]

    report = evaluate_okx_demo_execution_state(
        state,
        observed_at_utc=datetime(2026, 8, 5, tzinfo=timezone.utc),
        reconcile_stale_seconds=120,
        detect_unknown_orders=True,
    )
    codes = {alert["code"] for alert in report["alerts"]}

    assert "okx_demo_watchdog_reconciliation_stale" in codes
    assert "okx_demo_watchdog_unknown_exchange_order" in codes


def test_watchdog_detects_response_ambiguity_and_inactive_open_position() -> None:
    state = _healthy_state()
    state["runtime"]["active"] = False
    state["risk_control"]["mode"] = "FROZEN_UNKNOWN"
    state["risk_control"]["pending_order_intents"] = {
        "btcDPunknown": {"status": "unknown"}
    }

    report = evaluate_okx_demo_execution_state(
        state,
        observed_at_utc=NOW,
    )

    assert report["status"] == "critical"
    codes = {row["code"] for row in report["alerts"]}
    assert "okx_demo_watchdog_ambiguous_order_intent" in codes
    assert "okx_demo_watchdog_worker_inactive_with_open_position" in codes
    assert "okx_demo_watchdog_runtime_frozen_unknown" in codes


@pytest.mark.parametrize("intent_status", ("accepted", "reconciled_open"))
def test_watchdog_treats_every_nonterminal_exchange_intent_as_ambiguous(
    intent_status: str,
) -> None:
    state = _healthy_state()
    state["risk_control"]["pending_order_intents"] = {
        "btcDPopen": {"status": intent_status}
    }

    report = evaluate_okx_demo_execution_state(
        state,
        observed_at_utc=NOW,
    )

    codes = {row["code"] for row in report["alerts"]}
    assert report["status"] == "critical"
    assert "okx_demo_watchdog_ambiguous_order_intent" in codes


def test_watchdog_detects_equal_long_short_positions_as_nonflat_hedge() -> None:
    state = _healthy_state()
    state["exchange"]["positions"] = [
        {"position_side": "long", "contracts": "0.01"},
        {"position_side": "short", "contracts": "0.01"},
    ]
    state["risk_control"]["active_protection"] = {}
    state["exchange"]["pending_algo_orders"] = []

    report = evaluate_okx_demo_execution_state(
        state,
        observed_at_utc=NOW,
    )

    codes = {row["code"] for row in report["alerts"]}
    assert report["status"] == "critical"
    assert report["signed_contracts"] == "0.00"
    assert report["gross_contracts"] == "0.02"
    assert "okx_demo_watchdog_hedged_position_detected" in codes
    assert "okx_demo_watchdog_nonflat_without_exchange_protection" in codes


@pytest.mark.parametrize(
    ("include_contracts", "contracts"),
    [
        (True, "malformed"),
        (True, None),
        (True, ""),
        (False, None),
    ],
)
def test_watchdog_detects_invalid_position_as_critical_unknown_shape(
    include_contracts: bool,
    contracts: object,
) -> None:
    state = _healthy_state()
    position = {"position_side": "long"}
    if include_contracts:
        position["contracts"] = contracts
    state["exchange"]["positions"] = [position]

    report = evaluate_okx_demo_execution_state(
        state,
        observed_at_utc=NOW,
    )

    codes = {row["code"] for row in report["alerts"]}
    assert report["status"] == "critical"
    assert report["signed_contracts"] == "NaN"
    assert report["gross_contracts"] == "NaN"
    assert "okx_demo_watchdog_position_shape_invalid" in codes


@pytest.mark.parametrize(
    ("active_position_side", "algo_position_side"),
    [("short", "long"), ("long", ""), ("", "long")],
)
def test_watchdog_rejects_wrong_or_missing_protection_direction(
    active_position_side: str,
    algo_position_side: str,
) -> None:
    state = _healthy_state()
    state["risk_control"]["active_protection"][
        "position_side"
    ] = active_position_side
    state["exchange"]["pending_algo_orders"][0][
        "position_side"
    ] = algo_position_side

    report = evaluate_okx_demo_execution_state(
        state,
        observed_at_utc=NOW,
    )

    codes = {row["code"] for row in report["alerts"]}
    assert report["status"] == "critical"
    assert report["exchange_protection_verified"] is False
    assert "okx_demo_watchdog_nonflat_without_exchange_protection" in codes


def test_watchdog_rejects_non_market_exit_exchange_protection() -> None:
    state = _healthy_state()
    state["exchange"]["pending_algo_orders"][0][
        "take_profit_order_price"
    ] = "60610"

    report = evaluate_okx_demo_execution_state(
        state,
        observed_at_utc=NOW,
    )

    codes = {row["code"] for row in report["alerts"]}
    assert report["status"] == "critical"
    assert report["exchange_protection_verified"] is False
    assert "okx_demo_watchdog_nonflat_without_exchange_protection" in codes


def test_watchdog_reads_validated_runtime_chain_and_only_writes_own_alert(
    tmp_path: Path,
) -> None:
    runtime_root = tmp_path / "runtime"
    alert_path = tmp_path / "watchdog" / "alerts.jsonl"
    state = _healthy_state()
    state["runtime"]["last_heartbeat_utc"] = (
        NOW - timedelta(minutes=5)
    ).isoformat()
    store = BTCRuntimeStore(runtime_root)
    store.recover()
    store.checkpoint(state)
    checkpoint_before = (runtime_root / "state.json").read_bytes()

    config = OkxDemoExecutionWatchdogConfig(
        runtime_root=runtime_root,
        alert_path=alert_path,
    )
    first = inspect_okx_demo_execution_runtime(config, now=NOW)
    second = inspect_okx_demo_execution_runtime(config, now=NOW)

    assert first["status"] == "critical"
    assert first["alert_evidence"]["written"] is True
    assert second["alert_evidence"]["written"] is False
    assert (runtime_root / "state.json").read_bytes() == checkpoint_before
    rows = [json.loads(line) for line in alert_path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1
    assert rows[0]["capabilities"]["loads_credentials"] is False
    assert rows[0]["capabilities"]["calls_order_endpoint"] is False


def test_watchdog_fails_closed_when_runtime_checkpoint_is_invalid(
    tmp_path: Path,
) -> None:
    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir(parents=True)
    (runtime_root / "state.json").write_text(
        '{"checkpoint_hash":"tampered","state":{}}',
        encoding="utf-8",
    )

    report = inspect_okx_demo_execution_runtime(
        OkxDemoExecutionWatchdogConfig(runtime_root=runtime_root),
        now=NOW,
        write_alert=False,
    )

    assert report["status"] == "critical"
    codes = {row["code"] for row in report["alerts"]}
    assert "okx_demo_watchdog_runtime_evidence_invalid" in codes
    assert "okx_demo_watchdog_runtime_state_missing" in codes
