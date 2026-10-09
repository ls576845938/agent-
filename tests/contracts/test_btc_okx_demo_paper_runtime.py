from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import threading
import time
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping

import pytest

import quant_crypto.oms.okx_demo_paper_runtime as okx_demo_runtime_module
import quant_crypto.runtime.control_plane as btc_control_plane_module
import quant_shared.runtime.permissions as runtime_permissions_module
from backend.app.services.btc_demo_runtime import (
    BtcDemoRuntimeService as BackendBtcDemoRuntimeService,
)
from quant_crypto.application.btc_strategy_registry import btc_strategy_registry
from quant_crypto.application.btc_demo_start_attempt import (
    account_identity_hash,
    authoritative_account_identity_snapshot,
)
from quant_crypto.application.btc_okx_demo_fault_drill import (
    BtcOkxDemoFailedReceiptBinding,
    FaultDrillReceiptError,
)
from quant_crypto.application.btc_demo_runtime import (
    BtcDemoRuntimeService as ApplicationBtcDemoRuntimeService,
)
from quant_crypto.oms.okx_demo import (
    OkxDemoClient,
    OkxDemoClientConfig,
    OkxDemoCredentials,
    OkxDemoResponse,
    OkxDemoTransportError,
)
from quant_crypto.oms.okx_demo_paper_runtime import (
    OKX_DEMO_APPROVED_PROTECTION_POLICY,
    OKX_DEMO_PAPER_MAX_CLOCK_OFFSET_MS,
    OKX_DEMO_PAPER_AUTHORIZATION_TICKET,
    OKX_DEMO_PAPER_CONFIRMATION,
    OKX_DEMO_STOP_AND_FLATTEN_CONFIRMATION,
    OKX_NATIVE_LEGACY_SHARED_DATA_SCHEMA,
    OKX_NATIVE_SHARED_DATA_SCHEMA,
    OkxDemoPaperRuntimeConfig,
    OkxDemoPaperRuntimeController,
    OkxDemoPaperRuntimeError,
    OkxDemoSafetyError,
    ServerSideProtectionPolicy,
    inspect_okx_native_demo_signal_data,
    load_completed_okx_native_hourly_frame,
    load_btc_chart_payload,
)
from quant_crypto.oms.runtime_store import BTCRuntimeRecovery, BTCRuntimeStore
from quant_crypto.runtime.control_plane import (
    BTCDemoExecutionDispatcher,
    BTCEndpointCapability,
    BTCExecutionDispatchFacts,
    BTCExecutionMode,
)
from quant_shared.runtime.permissions import RuntimeAction
from quant_crypto.trading_contracts import (
    OrderIntent,
    OrderSide,
    OrderType,
    RiskDecision,
)
from quant_crypto.oms.private_ws_reconciliation import (
    BTCPrivateWSRuntimeReconciler,
    BTCPrivateWSStartupSnapshot,
)
from tools.agent_governance.shared_data import (
    MANIFEST_NAME,
    build_manifest,
    inventory_directory,
)


@pytest.mark.parametrize(
    ("raw_reduce_only", "expected_value", "expected_status"),
    [
        (None, None, "unknown"),
        ("false", False, "false"),
        ("true", True, "true"),
    ],
)
def test_algo_sanitizer_preserves_close_side_and_reduce_only_tristate(
    raw_reduce_only: str | None,
    expected_value: bool | None,
    expected_status: str,
) -> None:
    raw = {
        "algoId": "algo-long",
        "algoClOrdId": "btc-parent-longA",
        "parentClOrdId": "btc-parent-long",
        "instId": "BTC-USDT-SWAP",
        "side": "sell",
        "posSide": "long",
        "sz": "0.01",
        "ordType": "oco",
        "state": "live",
    }
    if raw_reduce_only is not None:
        raw["reduceOnly"] = raw_reduce_only

    sanitized = okx_demo_runtime_module._sanitize_algo_order(raw)

    assert sanitized["side"] == "sell"
    assert sanitized["reduce_only"] is expected_value
    assert sanitized["reduce_only_status"] == expected_status


def test_hosted_protection_projection_is_redacted_and_does_not_mutate_snapshot() -> None:
    controller = object.__new__(OkxDemoPaperRuntimeController)
    controller._runtime_identity = "runtime-owned"
    binding = {
        "runtime_identity": "runtime-owned",
        "run_id": "run-protection",
        "source_head": "a" * 40,
        "account_identity_hash": "b" * 64,
        "liveness_epoch": 3,
        "strategy_id": "long_short_donchian_top5",
        "strategy_version": "v1",
    }
    controller._state = {
        "runtime": {
            "run_id": "run-protection",
            "source_head": "a" * 40,
            "authoritative_liveness_epoch": 3,
        },
        "strategy": {
            "strategy_id": "long_short_donchian_top5",
            "strategy_version": "v1",
        },
        "risk_control": {
            "owned_attached_algos": {
                "parentA": {
                    "algo_id": "algo-1",
                    "algo_client_order_id": "parentA",
                    "parent_client_order_id": "parent",
                    "instrument_id": "BTC-USDT-SWAP",
                    "opening_intent": True,
                    "status": "active",
                    "fact_binding": binding,
                    "private_note": "must-not-leak",
                }
            },
            "active_protection": {
                "status": "exchange_accepted",
                "parent_client_order_id": "parent",
                "algo_id": "algo-1",
                "algo_client_order_id": "parentA",
                "instrument_id": "BTC-USDT-SWAP",
                "position_side": "long",
                "contracts": "0.01",
                "fact_binding": binding,
                "policy": {"internal": "must-not-leak"},
            },
            "pending_order_intents": {
                "parent": {
                    "status": "terminal",
                    "client_order_id": "parent",
                    "risk_reducing_only": False,
                    "order": {
                        "instId": "BTC-USDT-SWAP",
                        "side": "buy",
                        "posSide": "long",
                        "sz": "0.01",
                    },
                    "fact_binding": binding,
                    "outcome_probe": {"must": "not-leak"},
                }
            },
        },
    }
    snapshot = {
        "account": {
            "position_mode": "long_short_mode",
            "identity": {"hash": "b" * 64},
        },
        "positions": [],
        "pending_orders": [],
        "pending_algo_orders": [],
        "orders": [],
        "fills": [],
        "bills": [],
        "balance": {},
    }
    before = json.loads(json.dumps(snapshot))
    before_hash = okx_demo_runtime_module.canonical_ledger_snapshot_sha256(snapshot)

    projection = controller._hosted_protection_fact_projection(snapshot)

    assert snapshot == before
    assert okx_demo_runtime_module.canonical_ledger_snapshot_sha256(snapshot) == before_hash
    assert projection["snapshot_sha256"] == before_hash
    assert projection["fact_binding"] == binding
    assert "private_note" not in projection["owned_attached_algos"]["parentA"]
    assert "policy" not in projection["active_protection"]
    assert "outcome_probe" not in projection["parent_order_intents"]["parent"]
    assert "offline_residual_protection_revision" not in projection
from quant_crypto.research.btc_demo_observation_accumulator import (
    append_hourly_observation_receipt,
    build_hourly_observation_receipt,
)


class FakeTransport:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def send(
        self,
        *,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout_seconds: float,
    ) -> OkxDemoResponse:
        self.calls.append({"method": method, "url": url, "headers": dict(headers), "body": body})
        return OkxDemoResponse(method=method, path=url, http_status=200, code="0", message="", data=())


class SnapshotClient:
    def __init__(
        self,
        *,
        candle_rows: list[list[str]] | None = None,
        server_time_ms: str = "1",
        account_uid: str = "demo-account-a",
        account_main_uid: str = "demo-main-a",
    ) -> None:
        self.private_calls: list[dict[str, Any]] = []
        self.public_calls: list[dict[str, Any]] = []
        self.order_calls: list[dict[str, Any]] = []
        self.cancel_calls: list[dict[str, Any]] = []
        self.dead_man_calls: list[dict[str, Any]] = []
        self.candle_rows = candle_rows
        self.server_time_ms = server_time_ms
        self.account_uid = account_uid
        self.account_main_uid = account_main_uid

    def submit_order(self, payload: Mapping[str, Any]) -> OkxDemoResponse:
        self.order_calls.append(dict(payload))
        raise AssertionError("start_must_not_submit_orders")

    def cancel_order(self, **payload: Any) -> OkxDemoResponse:
        self.cancel_calls.append(dict(payload))
        raise AssertionError("start_must_not_cancel_orders")

    def cancel_all_after(self, **payload: Any) -> OkxDemoResponse:
        self.dead_man_calls.append(dict(payload))
        timeout_seconds = int(payload["timeout_seconds"])
        return OkxDemoResponse(
            method="POST",
            path="/api/v5/trade/cancel-all-after",
            http_status=200,
            code="0",
            message="",
            data=(
                {
                    "triggerTime": "0" if timeout_seconds == 0 else "2",
                    "tag": str(payload["tag"]),
                    "ts": "1",
                },
            ),
        )

    def private_get(self, path: str, params: Mapping[str, Any] | None = None) -> OkxDemoResponse:
        self.private_calls.append({"path": path, "params": dict(params or {})})
        rows: list[dict[str, Any]]
        if path == "/api/v5/account/config":
            rows = [{
                "acctLv": "2",
                "posMode": "long_short_mode",
                "perm": "read_only,trade",
                "uid": self.account_uid,
                "mainUid": self.account_main_uid,
            }]
        elif path == "/api/v5/account/balance":
            rows = [{"totalEq": "5000", "details": [{"ccy": "USDT", "eq": "5000"}]}]
        elif path in {
            "/api/v5/account/positions",
            "/api/v5/trade/orders-pending",
            "/api/v5/trade/orders-algo-pending",
            "/api/v5/trade/orders-history",
            "/api/v5/trade/fills",
            "/api/v5/account/bills",
        }:
            rows = []
        elif path == "/api/v5/account/trade-fee":
            rows = [{"makerU": "-0.0002", "takerU": "-0.0005"}]
        elif path == "/api/v5/account/leverage-info":
            rows = [
                {"instId": "BTC-USDT-SWAP", "mgnMode": "isolated", "posSide": "long", "lever": "3"},
                {"instId": "BTC-USDT-SWAP", "mgnMode": "isolated", "posSide": "short", "lever": "3"},
            ]
        else:
            raise AssertionError(path)
        return OkxDemoResponse(method="GET", path=path, http_status=200, code="0", message="", data=tuple(rows))

    def public_get(self, path: str, params: Mapping[str, Any] | None = None) -> OkxDemoResponse:
        self.public_calls.append({"path": path, "params": dict(params or {})})
        if path == "/api/v5/market/candles":
            if self.candle_rows is None:
                raise AssertionError(path)
            return OkxDemoResponse(
                method="GET",
                path=path,
                http_status=200,
                code="0",
                message="",
                data=tuple(self.candle_rows),
            )
        rows_by_path = {
            "/api/v5/public/instruments": [{
                "instId": "BTC-USDT-SWAP", "state": "live", "ctVal": "0.01", "lotSz": "0.01", "minSz": "0.01",
            }],
            "/api/v5/market/ticker": [{"bidPx": "60000", "askPx": "60000.1", "ts": "1"}],
            "/api/v5/public/mark-price": [{"markPx": "60000", "ts": "1"}],
            "/api/v5/market/index-tickers": [{"idxPx": "60000", "ts": "1"}],
            "/api/v5/public/price-limit": [{"buyLmt": "70000", "sellLmt": "50000"}],
            "/api/v5/market/books": [{"bids": [["60000", "1"]], "asks": [["60000.1", "1"]]}],
            "/api/v5/public/time": [{"ts": self.server_time_ms}],
            "/api/v5/public/funding-rate": [{"fundingRate": "0.0001", "fundingTime": "1"}],
        }
        return OkxDemoResponse(
            method="GET",
            path=path,
            http_status=200,
            code="0",
            message="",
            data=tuple(rows_by_path[path]),
        )


class OrderScenarioClient:
    def __init__(
        self,
        *,
        submit_exception: Exception | None = None,
        order_visible: bool = True,
        final_state: str = "filled",
        filled_size: str = "0.01",
        protection_active: bool = True,
        private_exceptions: Mapping[str, Exception] | None = None,
    ) -> None:
        self.submit_exception = submit_exception
        self.order_visible = order_visible
        self.final_state = final_state
        self.filled_size = filled_size
        self.protection_active = protection_active
        self.private_exceptions = dict(private_exceptions or {})
        self.submit_calls: list[dict[str, Any]] = []
        self.private_calls: list[dict[str, Any]] = []
        self.before_submit: Any = None

    def submit_order(self, payload: Mapping[str, Any]) -> OkxDemoResponse:
        order = dict(payload)
        self.submit_calls.append(order)
        if self.before_submit is not None:
            self.before_submit(order)
        if self.submit_exception is not None:
            raise self.submit_exception
        return OkxDemoResponse(
            method="POST",
            path="/api/v5/trade/order",
            http_status=200,
            code="0",
            message="",
            data=(
                {
                    "ordId": "order-1",
                    "clOrdId": order["clOrdId"],
                    "sCode": "0",
                    "sMsg": "",
                },
            ),
        )

    def private_get(
        self,
        path: str,
        params: Mapping[str, Any] | None = None,
    ) -> OkxDemoResponse:
        query = dict(params or {})
        self.private_calls.append({"path": path, "params": query})
        if path in self.private_exceptions:
            raise self.private_exceptions[path]
        order = self.submit_calls[-1] if self.submit_calls else {}
        if path == "/api/v5/trade/order":
            rows = [self._final_order(order)] if self.order_visible else []
        elif path in {
            "/api/v5/trade/orders-pending",
            "/api/v5/trade/orders-history",
            "/api/v5/account/positions",
        }:
            rows = []
        elif path == "/api/v5/trade/fills":
            rows = (
                [
                    {
                        "tradeId": "fill-1",
                        "ordId": "order-1",
                        "clOrdId": order.get("clOrdId", ""),
                        "instId": "BTC-USDT-SWAP",
                        "side": "buy",
                        "posSide": "long",
                        "fillPx": "60000",
                        "fillSz": self.filled_size,
                        "fee": "-0.001",
                        "feeCcy": "USDT",
                        "ts": "1",
                    }
                ]
                if Decimal(self.filled_size) > 0
                else []
            )
        elif path == "/api/v5/trade/order-algo":
            protection = self._protection(order)
            rows = [protection] if self.protection_active else []
        else:
            raise AssertionError(path)
        return OkxDemoResponse(
            method="GET",
            path=path,
            http_status=200,
            code="0",
            message="",
            data=tuple(rows),
        )

    def _final_order(self, order: Mapping[str, Any]) -> dict[str, Any]:
        protection = self._protection(order)
        attached = []
        if protection:
            attached = [
                {
                    "attachAlgoId": "algo-1",
                    "attachAlgoClOrdId": protection["algoClOrdId"],
                    "failCode": "0",
                }
            ]
        return {
            "ordId": "order-1",
            "clOrdId": str(order.get("clOrdId") or ""),
            "instId": str(order.get("instId") or ""),
            "side": str(order.get("side") or ""),
            "posSide": str(order.get("posSide") or ""),
            "ordType": str(order.get("ordType") or ""),
            "sz": str(order.get("sz") or ""),
            "tag": str(order.get("tag") or ""),
            "state": self.final_state,
            "accFillSz": self.filled_size,
            "avgPx": "60000",
            "attachAlgoOrds": attached,
        }

    @staticmethod
    def _protection(order: Mapping[str, Any]) -> dict[str, Any]:
        rows = order.get("attachAlgoOrds")
        if not isinstance(rows, list) or not rows:
            return {}
        row = rows[0]
        return {
            "algoId": "algo-1",
            "algoClOrdId": str(row.get("attachAlgoClOrdId") or ""),
            "instId": str(order.get("instId") or ""),
            "posSide": str(order.get("posSide") or ""),
            "sz": str(order.get("sz") or ""),
            "state": "live",
            "tpTriggerPx": str(row.get("tpTriggerPx") or ""),
            "tpTriggerPxType": str(row.get("tpTriggerPxType") or ""),
            "tpOrdPx": str(row.get("tpOrdPx") or ""),
            "slTriggerPx": str(row.get("slTriggerPx") or ""),
            "slTriggerPxType": str(row.get("slTriggerPxType") or ""),
            "slOrdPx": str(row.get("slOrdPx") or ""),
        }


class FakePrivateWS:
    instances: list["FakePrivateWS"] = []

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.monitoring_started = False
        self.stopped = False
        self.__class__.instances.append(self)

    def run_startup_reconnect_probe(self) -> dict[str, Any]:
        self.kwargs["on_disconnect"](
            "private_ws_startup_probe_local_disconnect"
        )
        receipt = {
            "schema_version": "btc_okx_demo_private_ws_reconnect_probe_v1",
            "source_head": self.kwargs["source_head"],
            "runtime_version": self.kwargs["runtime_version"],
            "opening_allowed_after_reconciliation": True,
            "credentials_redacted": True,
            "promotion_evidence_ready": False,
        }
        self.kwargs["on_reconciled"](receipt)
        return receipt

    def start_monitoring(self) -> None:
        self.monitoring_started = True

    def status(self) -> dict[str, Any]:
        return {
            "connected": self.monitoring_started,
            "listener_alive": self.monitoring_started,
            "opening_allowed_after_reconciliation": self.monitoring_started,
            "blockers": [],
        }

    def stop(self) -> None:
        self.stopped = True


class MissingListenerMonitoringStatusPrivateWS(FakePrivateWS):
    def status(self) -> dict[str, Any]:
        return {
            "connected": self.monitoring_started,
            "opening_allowed_after_reconciliation": self.monitoring_started,
            "blockers": [],
        }


class FalseListenerMonitoringStatusPrivateWS(FakePrivateWS):
    def status(self) -> dict[str, Any]:
        return {
            "connected": self.monitoring_started,
            "listener_alive": False,
            "opening_allowed_after_reconciliation": self.monitoring_started,
            "blockers": ["listener_not_alive"],
        }


class CurrentPrivateWS:
    def __init__(self) -> None:
        self.reconcile_calls = 0

    def reconcile_current(self) -> dict[str, Any]:
        self.reconcile_calls += 1
        return {
            "schema_version": "btc_okx_demo_private_ws_current_reconciliation_v1",
            "source_head": "a" * 40,
            "runtime_version": "okx_demo_paper_runtime_v1",
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "connected": True,
            "listener_alive": True,
            "reconnect_rest_reconciled": True,
            "opening_allowed_after_reconciliation": True,
            "blockers": [],
            "promotion_evidence_ready": False,
        }

    def status(self) -> dict[str, Any]:
        return {
            "connected": True,
            "listener_alive": True,
            "opening_allowed_after_reconciliation": True,
            "blockers": [],
        }


class StepStopEvent:
    def __init__(self, waits: list[bool]) -> None:
        self._waits = list(waits)
        self._set = False

    def is_set(self) -> bool:
        return self._set

    def set(self) -> None:
        self._set = True

    def clear(self) -> None:
        self._set = False

    def wait(self, _timeout: float) -> bool:
        if self._set:
            return True
        return self._waits.pop(0)


class _AliveHandle:
    def is_alive(self) -> bool:
        return True


class _TransientDeadManClient(SnapshotClient):
    def __init__(self, *, server_time_ms: str) -> None:
        super().__init__(server_time_ms=server_time_ms)
        self._codes = ["50011", "0"]

    def cancel_all_after(self, **payload: Any) -> OkxDemoResponse:
        self.dead_man_calls.append(dict(payload))
        code = self._codes.pop(0) if self._codes else "0"
        return OkxDemoResponse(
            method="POST",
            path="/api/v5/trade/cancel-all-after",
            http_status=200,
            code=code,
            message="",
            data=(
                {
                    "triggerTime": "2",
                    "tag": str(payload["tag"]),
                    "ts": "1",
                },
            ),
        )


def _install_full_recovery_evidence_stubs(
    controller: OkxDemoPaperRuntimeController,
) -> SnapshotClient:
    client = SnapshotClient()
    controller._client = client  # type: ignore[assignment]

    def commit_ledger_reconciliation(
        *,
        snapshot: Mapping[str, Any],
        trigger: str,
        order_record: Mapping[str, Any] | None = None,
    ) -> None:
        del snapshot, order_record
        controller._state["ledger_reconciliation"] = {
            "status": "reconciled",
            "trigger": trigger,
            "current_state_exchange_snapshot_match": True,
            "funding_cashflow_reconciled": True,
            "promotion_evidence_ready": False,
        }

    controller._commit_ledger_reconciliation = (  # type: ignore[method-assign]
        commit_ledger_reconciliation
    )
    return client


def _credentials() -> OkxDemoCredentials:
    return OkxDemoCredentials(api_key="a" * 36, secret_key="b" * 32, passphrase="Pass1234")


def _valid_start_payload() -> dict[str, Any]:
    spec = btc_strategy_registry.list_specs()[0]
    return _start_payload_for(spec)


def _protection_policy() -> dict[str, Any]:
    return dict(OKX_DEMO_APPROVED_PROTECTION_POLICY)


def _owned_id_restore_archive(
    tmp_path: Path,
    *,
    include_lifecycle: bool = True,
    include_ledger: bool = True,
) -> tuple[Path, dict[str, str]]:
    """Build a tiny immutable archive with a real BTCRuntimeStore chain."""

    archive = (tmp_path / "owned-id-archive").resolve()
    source_root = tmp_path / "source-runtime"
    source_root.mkdir(parents=True, exist_ok=True)
    run_id = "owned-run-01"
    rows = [
        {
            "client_order_id": "btcDPowned-ru0001",
            "order_id": "order-owned-1",
            "fill_id": "fill-owned-1",
            "side": "buy",
        },
        {
            "client_order_id": "btcDPowned-ru0002",
            "order_id": "order-owned-2",
            "fill_id": "fill-owned-2",
            "side": "sell",
        },
    ]
    exchange_orders = [
        {
            "client_order_id": row["client_order_id"],
            "order_id": row["order_id"],
            "instrument_id": "BTC-USDT-SWAP",
            "state": "filled",
        }
        for row in rows
    ]
    exchange_fills = [
        {
            "client_order_id": row["client_order_id"],
            "order_id": row["order_id"],
            "fill_id": row["fill_id"],
            "instrument_id": "BTC-USDT-SWAP",
        }
        for row in rows
    ]
    state = {
        "environment": "OKX Demo",
        "instrument_id": "BTC-USDT-SWAP",
        "limits": {"margin_mode": "isolated"},
        "exchange": {
            "account": {
                "account_level": "2",
                "permissions": ["read_only", "trade"],
                "position_mode": "long_short_mode",
                "withdraw_permission_present": False,
            },
            "orders": exchange_orders,
            "fills": exchange_fills,
            "positions": [],
            "pending_orders": [],
            "pending_algo_orders": [],
        },
    }
    store = BTCRuntimeStore(source_root)
    for row in rows:
        fill = {
            "client_order_id": row["client_order_id"],
            "order_id": row["order_id"],
            "fill_id": row["fill_id"],
            "instrument_id": "BTC-USDT-SWAP",
        }
        order = {
            "client_order_id": row["client_order_id"],
            "order_id": row["order_id"],
            "instrument_id": "BTC-USDT-SWAP",
            "state": "filled",
        }
        if include_lifecycle:
            store.append(
                event_type="order_lifecycle",
                payload={
                    "exchange_order_id": row["order_id"],
                    "exchange_state": "filled",
                    "oms": {
                        "client_order_id": row["client_order_id"],
                        "broker_order_id": row["order_id"],
                        "status": "reconciled",
                        "symbol": "BTC-USDT-SWAP",
                    },
                    "fills": [fill],
                },
                state_after=state,
                idempotency_key=f"lifecycle:{row['client_order_id']}",
                timestamp_utc="2026-08-09T00:00:00+00:00",
                run_id=run_id,
                safety={
                    "demo_environment_only": True,
                    "live_order_allowed": False,
                    "real_money_order_allowed": False,
                    "transfer_allowed": False,
                    "withdraw_allowed": False,
                },
            )
        if include_ledger:
            store.commit_ledger_uow(
                idempotency_key=f"ledger:{row['client_order_id']}",
                timestamp_utc="2026-08-09T00:00:01+00:00",
                run_id=run_id,
                order={"orders": [order]},
                fills=[fill],
                position={"positions": []},
                cash={"equity_usdt": "5000"},
                funding={"bills": [], "cashflow_reconciled": True},
                risk_context={
                    "mark_price": "60000",
                    "index_price": "60000",
                    "liquidation_buffer_bps": "not_applicable_flat_position",
                    "venue_rules": {"instrument_id": "BTC-USDT-SWAP"},
                },
                state_after=state,
                safety={
                    "demo_environment_only": True,
                    "live_order_allowed": False,
                    "real_money_order_allowed": False,
                    "transfer_allowed": False,
                    "withdraw_allowed": False,
                },
            )
    store.checkpoint(state)
    if not (source_root / "events.jsonl").exists():
        (source_root / "events.jsonl").write_bytes(b"")
    archive.mkdir(parents=True, exist_ok=False)
    snapshot_root = archive / "source_snapshots"
    snapshot_root.mkdir()
    (source_root / "events.jsonl").replace(snapshot_root / "runtime_events.jsonl")
    (source_root / "state.json").replace(snapshot_root / "runtime_state.json")
    (snapshot_root / "receipt_ledger.jsonl").write_bytes(b"")
    owner = tmp_path / "owner.json"
    owner.write_text(
        json.dumps(
            {
                "repository_owner_identity": "owner-fingerprint",
                "immutable_archives_only": True,
            },
            sort_keys=True,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    event_rows = [
        json.loads(line)
        for line in (snapshot_root / "runtime_events.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
    ]
    state_document = json.loads(
        (snapshot_root / "runtime_state.json").read_text(encoding="utf-8")
    )
    files: list[dict[str, Any]] = []
    for relative, kind in (
        ("source_snapshots/runtime_events.jsonl", "runtime_events"),
        ("source_snapshots/runtime_state.json", "runtime_state"),
        ("source_snapshots/receipt_ledger.jsonl", "receipt_ledger"),
    ):
        path = archive / relative
        files.append(
            {
                "archive_relative_path": relative,
                "kind": kind,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "size_bytes": path.stat().st_size,
            }
        )
    source_head = "160a4820377260cfa1118c0f2e8ae90c7a3533da"
    verification = {
        "status": "blocked_fail_closed",
        "source_head": source_head,
        "safety": {
            "live_allowed": False,
            "network_used": False,
            "order_endpoint_allowed": False,
            "paper_allowed": False,
            "private_endpoint_allowed": False,
            "promotion_allowed": False,
            "secret_read": False,
            "withdraw_allowed": False,
        },
    }
    verification_path = archive / "verification.json"
    verification_path.write_text(
        json.dumps(verification, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    verification_sha = hashlib.sha256(verification_path.read_bytes()).hexdigest()
    manifest = {
        "schema_version": "btc_demo_cross_head_compatibility_archive_v2",
        "archive_id": "owned-id-restore-fixture",
        "manifest_hash": "a" * 64,
        "immutable": True,
        "unique_directory_no_overwrite": True,
        "status": "blocked_fail_closed",
        "current_head": source_head,
        "verification_sha256": verification_sha,
        "owner_marker": {
            "immutable_archives_only": True,
            "path": str(owner),
            "repository_owner_identity": "owner-fingerprint",
            "sha256": hashlib.sha256(owner.read_bytes()).hexdigest(),
        },
        "execution_identity": {
            "account_identity": "a" * 64,
            "credential_identity": "quant-system.okx-demo.trade",
        },
        "files": files,
        "event_chain": {
            "event_count": len(event_rows),
            "hash_chain_valid": True,
            "last_event_hash": event_rows[-1]["event_hash"] if event_rows else "",
        },
        "safety": verification["safety"],
    }
    manifest_path = archive / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    manifest_sha = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    (archive / "COMPLETED.json").write_text(
        json.dumps(
            {
                "manifest_sha256": manifest_sha,
                "verification_sha256": verification_sha,
                "immutable_after_write": True,
            },
            sort_keys=True,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    current_head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=True,
        cwd=Path.cwd(),
        capture_output=True,
        text=True,
    ).stdout.strip()
    return archive, {
        "current_head": current_head,
        "source_head": source_head,
        "account_identity": "a" * 64,
        "credential_identity": "quant-system.okx-demo.trade",
        "client_order_namespace": "btcDPowned-ru",
    }


def _p0_order_snapshot() -> dict[str, Any]:
    return {
        "ticker": {"bid": "60000", "ask": "60000.1"},
        "instrument": {"tick_size": "0.1"},
        "price_limit": {"buy": "70000", "sell": "50000"},
        "book": {
            "bids": [["60000", "1"]],
            "asks": [["60000.1", "1"]],
            "timestamp_ms": "1",
        },
        "fee_schedule": {"taker_rate": "-0.0005"},
        "funding": {"funding_rate": "0.0001"},
        "leverage": [
            {
                "instrument_id": "BTC-USDT-SWAP",
                "position_side": "long",
                "margin_mode": "isolated",
                "leverage": "3",
            },
            {
                "instrument_id": "BTC-USDT-SWAP",
                "position_side": "short",
                "margin_mode": "isolated",
                "leverage": "3",
            },
        ],
    }


def _p0_order_decision() -> dict[str, Any]:
    return {
        "strategy_id": "long_short_donchian_top5",
        "candidate_id": "fixture",
        "direction": "long",
        "raw_signal": "1",
        "target_contracts": "0.01",
        "decision_bar_close_utc": datetime.now(timezone.utc).isoformat(),
    }


def _p0_order_controller(
    tmp_path: Path,
) -> tuple[OkxDemoPaperRuntimeController, dict[str, Any], dict[str, Any]]:
    controller = OkxDemoPaperRuntimeController(
        config=OkxDemoPaperRuntimeConfig(
            repo_root=Path.cwd(),
            data_db_path=tmp_path / "unused.sqlite",
            output_dir=tmp_path / "output" / "btc_demo_paper_runtime",
            order_poll_interval_seconds=0.01,
            order_poll_attempts=1,
            authoritative_oms_bundle_provider=_test_authoritative_oms_bundle_provider,
        ),
        credential_loader=lambda _: _credentials(),
        start_worker=False,
    )
    policy = ServerSideProtectionPolicy.from_mapping(_protection_policy())
    assert policy.validate() == []
    controller._protection_policy = policy
    controller._state["risk_control"]["protection_policy"] = policy.to_dict()
    controller._state["runtime"].update(
        {
            "run_id": "p0drill",
            "active": True,
            "status": "running",
            "opening_allowed": True,
            "cancel_only": False,
        }
    )
    controller._state["risk_control"]["mode"] = "RUNNING"
    controller._state["risk_control"]["write_path_trusted"] = True
    controller._state["private_ws"].update(
        {
            "connected": True,
            "listener_alive": True,
            "opening_allowed_after_reconciliation": True,
        }
    )
    controller._state["risk_control"]["dead_man"].update(
        {
            "armed": True,
            "last_ack_utc": datetime.now(timezone.utc).isoformat(),
        }
    )
    controller._state["ledger_reconciliation"].update(
        {
            "status": "reconciled",
            "current_state_exchange_snapshot_match": True,
        }
    )
    snapshot = _p0_order_snapshot()
    order_plan = controller._build_order_plan(
        snapshot,
        current_quantity=Decimal("0"),
        target_quantity=Decimal("0.01"),
    )
    assert order_plan is not None
    return controller, snapshot, order_plan


def test_submit_requires_composed_authoritative_t2_t3_bundle_before_lifecycle_or_post(
    tmp_path: Path,
) -> None:
    controller, snapshot, order_plan = _p0_order_controller(tmp_path)
    controller.config = replace(
        controller.config,
        authoritative_oms_bundle_provider=None,
    )
    client = OrderScenarioClient()
    with pytest.raises(
        OkxDemoPaperRuntimeError,
        match="okx_demo_t5_authoritative_oms_bundle_required",
    ):
        controller._submit_order_plan(
            client,
            snapshot=snapshot,
            decision=_p0_order_decision(),
            order_plan=order_plan,
        )
    assert client.submit_calls == []
    assert controller.status()["risk_control"]["pending_order_intents"] == {}


def test_submit_delegates_explicit_authoritative_t2_t3_bundle_to_oms(
    tmp_path: Path,
) -> None:
    controller, snapshot, order_plan = _p0_order_controller(tmp_path)
    delegated: list[dict[str, Any]] = []
    original_provider = controller.config.authoritative_oms_bundle_provider

    def provider(**kwargs: Any):
        delegated.append(dict(kwargs))
        assert original_provider is not None
        return original_provider(**kwargs)

    controller.config = replace(
        controller.config,
        authoritative_oms_bundle_provider=provider,
    )
    client = OrderScenarioClient()
    _install_order_followup(controller, client, order_plan)
    result = controller._submit_order_plan(
        client,
        snapshot=snapshot,
        decision=_p0_order_decision(),
        order_plan=order_plan,
    )
    assert delegated and delegated[0]["intent"].client_order_id == order_plan["client_order_id"]
    assert len(client.submit_calls) == 1
    assert result["orders_posted"] == 1
    ordinary_order_record = controller.status()["audit"][0]
    assert "offline_residual_protection_revision" not in ordinary_order_record


def _install_order_followup(
    controller: OkxDemoPaperRuntimeController,
    client: OrderScenarioClient,
    order_plan: Mapping[str, Any],
    *,
    preflight_blockers: list[str] | None = None,
) -> None:
    protection = dict(order_plan["attached_protection"])
    pending_algo_orders = []
    if client.protection_active:
        pending_algo_orders = [
            {
                "algo_id": "algo-1",
                "algo_client_order_id": protection["attachAlgoClOrdId"],
                "instrument_id": "BTC-USDT-SWAP",
                "position_side": str(order_plan["position_side"]),
                "size": str(order_plan["contracts"]),
                "state": "live",
                "take_profit_trigger": protection["tpTriggerPx"],
                "take_profit_trigger_type": "mark",
                "take_profit_order_price": "-1",
                "stop_loss_trigger": protection["slTriggerPx"],
                "stop_loss_trigger_type": "mark",
                "stop_loss_order_price": "-1",
            }
        ]
    followup = {
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "positions": [
            {
                "position_side": "long",
                "contracts": client.filled_size,
            }
        ],
        "pending_orders": [],
        "pending_algo_orders": pending_algo_orders,
    }
    controller._collect_exchange_snapshot = lambda _client: followup  # type: ignore[method-assign]
    controller._preflight_blockers = (  # type: ignore[method-assign]
        lambda _snapshot, require_flat: list(preflight_blockers or [])
    )
    controller._commit_ledger_reconciliation = (  # type: ignore[method-assign]
        lambda **_kwargs: None
    )


def _start_payload_for(spec) -> dict[str, Any]:
    return {
        "authorization_ticket": OKX_DEMO_PAPER_AUTHORIZATION_TICKET,
        "strategy_id": spec.strategy_id,
        "candidate_id": spec.candidate_id,
        "strategy_version": spec.strategy_version,
        "instrument_id": "BTC-USDT-SWAP",
        "margin_mode": "isolated",
        "order_contracts": 0.01,
        "max_net_contracts": 0.01,
        "max_notional_usdt": 10,
        "confirmation_text": OKX_DEMO_PAPER_CONFIRMATION,
        "confirm_demo_only": True,
        "confirm_automatic_orders": True,
        "confirm_risk_limits": True,
        "confirm_cancel_only_on_error": True,
        "confirm_dedicated_demo_account": True,
        "dead_man_tag": "btcP0Demo",
        "server_side_protection_policy": _protection_policy(),
    }


def test_partial_start_request_accepts_only_0p03_and_25_cap() -> None:
    payload = _valid_start_payload()
    payload.update(
        {
            "order_contracts": "0.03",
            "max_net_contracts": "0.03",
            "max_notional_usdt": "25",
            "fault_drill_scenario": "partial_fill_disconnect",
        }
    )

    request = okx_demo_runtime_module.OkxDemoPaperStartRequest.from_mapping(
        payload
    )

    assert request.validate() == []


def _test_authoritative_oms_bundle_provider(**kwargs: Any):
    """Explicit test composition seam; production has no default provider."""

    from quant_crypto.oms.shared_platform_v3 import (
        OMSOrderSubmissionBundle,
        OMSProofIdentity,
        SharedPlatformV3OMS,
        order_intent_execution_digest,
    )
    from quant_crypto.portfolio.decision import (
        BTCPortfolioDecision,
        RiskReductionPlan,
    )
    from quant_crypto.risk import ActionRiskEffect, RiskAssessment

    signal = kwargs["signal"]
    target = kwargs["target_position"]
    intent = kwargs["intent"]
    before = float(kwargs["position_before"])
    after = float(kwargs["position_after"])
    action = kwargs["action"]
    opening = action is RuntimeAction.SUBMIT_NEW_ORDER
    effect = (
        ActionRiskEffect.INCREASE_ABS_EXPOSURE
        if abs(after) > abs(before)
        else ActionRiskEffect.DECREASE_ABS_EXPOSURE
    )
    blockers = () if opening else ("test_authoritative_reduction",)
    assessment = RiskAssessment(
        approved=opening,
        status="approved" if opening else "blocked",
        effect=effect,
        blockers=blockers,
        reasons=blockers,
        requires_reduction=not opening,
        max_safe_quantity=abs(after),
        notional=float(kwargs["price"]) * abs(after),
        metadata={
            "position_before": before,
            "position_after": after,
            "execution_permission": False,
            "authority": "test_fixture_t2",
        },
    )
    plan = None
    if not opening:
        plan = RiskReductionPlan(
            symbol=target.symbol,
            strategy_id=target.strategy_id,
            decision_time_utc=signal.timestamp_utc,
            source_forecast_id=signal.signal_id,
            source_target_position_id=target.target_position_id,
            current_quantity=before,
            target_quantity=after,
            reduction_quantity=abs(before) - abs(after),
            max_safe_quantity=abs(after),
            reason_codes=blockers,
        )
    decision = BTCPortfolioDecision(
        target_position=target,
        risk_assessment=assessment,
        reduction_plan=plan,
        decision_time_utc=signal.timestamp_utc,
        source="test_authoritative_t3",
        reason_codes=blockers,
        order_generation_allowed=opening,
    )
    protection = None
    if opening:
        protection = SharedPlatformV3OMS().build_attached_protection(
            policy=_protection_policy(),
            entry_price=kwargs["price"],
            tick_size="0.1",
            position_side=str(kwargs["venue_facts"]["position_side"]),
            client_order_id=intent.client_order_id,
            contracts=kwargs["quantity"],
        )
    proof = OMSProofIdentity(
        source_head="a" * 40,
        account_identity="a" * 64,
        session_id=intent.run_id or "test-authoritative-session",
        key_namespace="quant-system.okx-demo.trade",
        client_order_namespace="btcDPtest",
        epoch=1,
        intent_digest=order_intent_execution_digest(intent),
    )
    return OMSOrderSubmissionBundle(
        signal=signal,
        target_position=target,
        risk_assessment=assessment,
        portfolio_decision=decision,
        position_before=before,
        position_after=after,
        action=action,
        risk_effect=effect.value,
        proof_identity=proof,
        price=kwargs["price"],
        quantity=kwargs["quantity"],
        venue_facts=kwargs["venue_facts"],
        cost_facts=kwargs["cost_facts"],
        intent=intent,
        protection=protection,
        guardian_health=kwargs.get("guardian_health") or {
            "passed": True,
            "healthy": True,
            "source": "test_authoritative_t4",
        },
        guardian_latch=kwargs.get("guardian_latch") or {"tripped": False},
    )


def _controller(tmp_path: Path, credential_loader) -> OkxDemoPaperRuntimeController:
    return OkxDemoPaperRuntimeController(
        config=OkxDemoPaperRuntimeConfig(
            repo_root=tmp_path,
            data_db_path=tmp_path / "missing.sqlite",
            output_dir=tmp_path / "output" / "btc_demo_paper_runtime",
            authoritative_oms_bundle_provider=_test_authoritative_oms_bundle_provider,
        ),
        credential_loader=credential_loader,
        start_worker=False,
    )


def _prime_authoritative_account_identity(
    controller: OkxDemoPaperRuntimeController,
    *,
    account_uid: str = "demo-account-a",
    account_main_uid: str = "demo-main-a",
) -> SnapshotClient:
    """Refresh the controller from a fake account-config snapshot only."""

    client = SnapshotClient(
        account_uid=account_uid,
        account_main_uid=account_main_uid,
    )
    snapshot = controller._collect_exchange_snapshot(client)  # type: ignore[arg-type]
    controller._apply_snapshot(snapshot)
    return client


def test_durable_start_operation_is_fast_idempotent_and_single_owner(
    tmp_path: Path,
) -> None:
    started = threading.Event()
    release = threading.Event()
    controller = OkxDemoPaperRuntimeController(
        config=OkxDemoPaperRuntimeConfig(
            repo_root=Path.cwd(),
            data_db_path=tmp_path / "missing.sqlite",
            output_dir=tmp_path / "output" / "btc_demo_paper_runtime",
        ),
        credential_loader=lambda _: _credentials(),
        start_worker=False,
        start_capability_checker=lambda: {"ready": True, "incident_category": "none", "blockers": []},
    )

    def slow_start(_payload: Mapping[str, Any]) -> dict[str, Any]:
        started.set()
        release.wait(2.0)
        return controller.status()

    controller.start = slow_start  # type: ignore[method-assign]
    _prime_authoritative_account_identity(controller)
    begin = time.monotonic()
    first = controller.start_operation(
        _valid_start_payload(),
        idempotency_key="start-op-1",
    )
    elapsed = time.monotonic() - begin

    assert elapsed < 1.0
    assert first["accepted"] is True
    assert first["state"] in {"queued", "running"}
    assert first["revision"] >= 2
    assert first["start_operation"]["source_head"] == _repo_head_for_test()
    assert started.wait(1.0) is True
    same = controller.start_operation(
        _valid_start_payload(),
        idempotency_key="start-op-1",
    )
    assert same["operation_id"] == first["operation_id"]
    mismatched = dict(_valid_start_payload())
    mismatched["max_notional_usdt"] = 9
    with pytest.raises(
        OkxDemoPaperRuntimeError,
        match="idempotency_key_reuse_mismatch",
    ):
        controller.start_operation(mismatched, idempotency_key="start-op-1")
    with pytest.raises(OkxDemoPaperRuntimeError, match="start_operation_conflict"):
        controller.start_operation(
            _valid_start_payload(),
            idempotency_key="start-op-2",
        )
    release.set()
    assert controller._start_operation_thread is not None
    controller._start_operation_thread.join(2.0)
    assert controller.status()["start_operation"]["state"] == "completed"


def test_start_attempt_policy_binding_is_immutable_and_authoritative(
    tmp_path: Path,
) -> None:
    """Failure-first contract: old starts had no server policy/identity binding."""

    controller = OkxDemoPaperRuntimeController(
        config=OkxDemoPaperRuntimeConfig(
            repo_root=Path.cwd(),
            data_db_path=tmp_path / "missing.sqlite",
            output_dir=tmp_path / "output" / "btc_demo_paper_runtime",
        ),
        credential_loader=lambda _: _credentials(),
        start_worker=False,
        start_capability_checker=lambda: {
            "ready": False,
            "incident_category": "local_environment",
            "blockers": ["synthetic_start_blocked"],
        },
    )
    _prime_authoritative_account_identity(controller)

    accepted = controller.start_operation(
        _valid_start_payload(),
        idempotency_key="policy-binding-old-code",
    )
    attempt = accepted["start_operation"]
    assert attempt["runtime_identity"]
    assert attempt["effective_policy_digest"]
    assert attempt["risk_profile"] == "baseline_1x"
    assert attempt["expected_leverage"] == "1"
    assert attempt["account_identity_hash"]
    assert attempt["parent_operation_id"]


def test_start_attempt_policy_digest_changes_with_effective_risk_profile(
    tmp_path: Path,
) -> None:
    def make_controller(name: str, profile: str, leverage: str):
        return OkxDemoPaperRuntimeController(
            config=OkxDemoPaperRuntimeConfig(
                repo_root=Path.cwd(),
                data_db_path=tmp_path / f"{name}.sqlite",
                output_dir=tmp_path / name,
                risk_profile=profile,
                max_configured_leverage=Decimal(leverage),
            ),
            credential_loader=lambda _: _credentials(),
            start_worker=False,
            start_capability_checker=lambda: {
                "ready": False,
                "incident_category": "local_environment",
                "blockers": ["synthetic_start_blocked"],
            },
        )

    baseline = make_controller("baseline", "baseline_1x", "1")
    stress = make_controller("stress", "stress_3x", "3")
    _prime_authoritative_account_identity(baseline)
    _prime_authoritative_account_identity(stress)
    baseline_attempt = baseline.start_operation(
        _valid_start_payload(), idempotency_key="policy-baseline-001"
    )["start_operation"]
    stress_attempt = stress.start_operation(
        _valid_start_payload(), idempotency_key="policy-stress-001"
    )["start_operation"]
    assert baseline_attempt["risk_profile"] == "baseline_1x"
    assert baseline_attempt["expected_leverage"] == "1"
    assert stress_attempt["risk_profile"] == "stress_3x"
    assert stress_attempt["expected_leverage"] == "3"
    assert baseline_attempt["effective_policy_digest"] != stress_attempt["effective_policy_digest"]


def test_restart_and_policy_switch_keep_old_attempt_historical(
    tmp_path: Path,
) -> None:
    output = tmp_path / "shared-output"

    def make(profile: str, leverage: str) -> OkxDemoPaperRuntimeController:
        return OkxDemoPaperRuntimeController(
            config=OkxDemoPaperRuntimeConfig(
                repo_root=Path.cwd(),
                data_db_path=tmp_path / f"{profile}.sqlite",
                output_dir=output,
                risk_profile=profile,
                max_configured_leverage=Decimal(leverage),
            ),
            credential_loader=lambda _: _credentials(),
            start_worker=False,
            start_capability_checker=lambda: {
                "ready": False,
                "incident_category": "local_environment",
                "blockers": ["synthetic_start_blocked"],
            },
        )

    baseline = make("baseline_1x", "1")
    _prime_authoritative_account_identity(baseline)
    old = baseline.start_operation(
        _valid_start_payload(), idempotency_key="history-baseline-001"
    )["start_operation"]
    assert old["current_attempt"] is True
    stress = make("stress_3x", "3")
    _prime_authoritative_account_identity(stress)
    recovered = stress.status()["start_operation"]
    assert recovered["current_attempt"] is False
    assert recovered["historical"] is True
    assert "runtime_identity_changed" in recovered["historical_reason_codes"]
    new = stress.start_operation(
        _valid_start_payload(), idempotency_key="history-stress-001"
    )["start_operation"]
    assert new["current_attempt"] is True
    assert new["historical"] is False
    assert new["risk_profile"] == "stress_3x"
    assert new["effective_policy_digest"] != old["effective_policy_digest"]
    historical = stress.status()["historical_start_operations"]
    assert historical
    assert sum(
        row.get("operation_id") == old["operation_id"]
        for row in historical
    ) == 1


def test_policy_switch_does_not_reproject_old_leverage_blocker_as_current(
    tmp_path: Path,
) -> None:
    """A 1x restart failure remains audit history after a 3x policy switch."""

    output = tmp_path / "policy-switch-current-facts"

    def make(profile: str, leverage: str, blocker: str) -> OkxDemoPaperRuntimeController:
        return OkxDemoPaperRuntimeController(
            config=OkxDemoPaperRuntimeConfig(
                repo_root=Path.cwd(),
                data_db_path=tmp_path / f"{profile}.sqlite",
                output_dir=output,
                risk_profile=profile,
                max_configured_leverage=Decimal(leverage),
            ),
            credential_loader=lambda _: _credentials(),
            start_worker=False,
            start_capability_checker=lambda: {
                "ready": False,
                "incident_category": "local_environment",
                "blockers": [blocker],
            },
        )

    baseline = make(
        "baseline_1x",
        "1",
        "okx_demo_paper_exact_isolated_1x_leverage_required",
    )
    _prime_authoritative_account_identity(baseline)
    old = baseline.start_operation(
        _valid_start_payload(), idempotency_key="policy-switch-old-1x"
    )["start_operation"]
    assert old["state"] == "blocked"
    assert "okx_demo_paper_exact_isolated_1x_leverage_required" in baseline.status()["runtime"]["blockers"]

    stress = make(
        "stress_3x",
        "3",
        "okx_demo_paper_exact_isolated_3x_leverage_required",
    )
    _prime_authoritative_account_identity(stress)
    recovered = stress.status()
    runtime = recovered["runtime"]
    old_blocker = "okx_demo_paper_exact_isolated_1x_leverage_required"
    assert old_blocker not in runtime["blockers"]
    assert old_blocker not in str(runtime["last_error"])
    assert old_blocker not in str(recovered["risk_control"].get("reason") or "")
    assert recovered["start_operation"]["current_attempt"] is False
    assert recovered["start_operation"]["historical"] is True
    history = recovered["historical_start_operations"]
    assert any(row.get("operation_id") == old["operation_id"] for row in history)
    assert old_blocker not in json.dumps(
        recovered["start_capability"],
        sort_keys=True,
    )
    control = BackendBtcDemoRuntimeService(controller=stress).status()[
        "operator_control"
    ]
    assert old_blocker not in json.dumps(control["incident"], sort_keys=True)
    assert old_blocker not in json.dumps(
        control["preflight_stages"],
        sort_keys=True,
    )


def test_policy_switch_historical_start_blocker_is_not_current_but_independent_safety_remains(
    tmp_path: Path,
) -> None:
    """A historical start failure cannot masquerade as a serving blocker."""

    output = tmp_path / "private-ws-switch-current-facts"
    old_blocker = "okx_demo_private_ws_startup_reconnect_probe_failed"
    independent_blocker = "okx_demo_ledger_reconciliation_required"

    def make(profile: str, leverage: str) -> OkxDemoPaperRuntimeController:
        return OkxDemoPaperRuntimeController(
            config=OkxDemoPaperRuntimeConfig(
                repo_root=Path.cwd(),
                data_db_path=tmp_path / f"{profile}.sqlite",
                output_dir=output,
                risk_profile=profile,
                max_configured_leverage=Decimal(leverage),
            ),
            credential_loader=lambda _: _credentials(),
            start_worker=False,
            start_capability_checker=lambda: {
                "ready": False,
                "incident_category": "runtime_fault",
                "blockers": [old_blocker],
            },
        )

    baseline = make("baseline_1x", "1")
    _prime_authoritative_account_identity(baseline)
    old = baseline.start_operation(
        _valid_start_payload(), idempotency_key="private-ws-switch-old"
    )["start_operation"]
    assert old["state"] == "blocked"
    baseline._state["runtime"]["blockers"].append(independent_blocker)
    baseline._state["runtime"]["last_error"] = old_blocker
    baseline._state["risk_control"]["reason"] = old_blocker
    baseline._persist_state()

    stress = make("stress_3x", "3")
    _prime_authoritative_account_identity(stress)
    recovered = stress.status()
    runtime = recovered["runtime"]
    assert old_blocker not in runtime["blockers"]
    assert old_blocker not in str(runtime["last_error"])
    assert old_blocker not in str(recovered["risk_control"].get("reason") or "")
    assert independent_blocker in runtime["blockers"]
    assert "okx_demo_previous_cancel_only_state_restored" in runtime["blockers"]
    historical = recovered["historical_start_operations"]
    historical_row = next(
        row for row in historical if row.get("operation_id") == old["operation_id"]
    )
    assert old_blocker in historical_row["blockers"]


def test_authoritative_account_identity_ignores_namespace_and_mutable_balance() -> None:
    account_a = {
        "uid": "uid-a",
        "mainUid": "main-a",
        "perm": "read_only,trade",
        "balance": "1000",
    }
    account_a_after_balance_change = {**account_a, "balance": "900"}
    account_b = {**account_a, "uid": "uid-b"}
    projected_a = authoritative_account_identity_snapshot(
        account_a,
        captured_at_utc="2026-08-25T00:00:00+00:00",
    )
    projected_a_after_balance = authoritative_account_identity_snapshot(
        account_a_after_balance_change,
        captured_at_utc="2026-08-25T01:00:00+00:00",
    )
    projected_b = authoritative_account_identity_snapshot(
        account_b,
        captured_at_utc="2026-08-25T00:00:00+00:00",
    )

    assert projected_a["hash"]
    assert projected_a["hash"] == projected_a_after_balance["hash"]
    assert projected_a["hash"] != projected_b["hash"]
    assert projected_a["hash"] != account_identity_hash(
        "okx-demo-paper:BTC-USDT-SWAP"
    )
    with pytest.raises(
        OkxDemoSafetyError,
        match="btc_demo_authoritative_account_identity_must_come_from_snapshot",
    ):
        OkxDemoPaperRuntimeConfig(
            repo_root=Path.cwd(),
            data_db_path=Path.cwd() / "missing.sqlite",
            account_identity_hash=projected_a["hash"],
        )


def test_missing_authoritative_account_identity_blocks_before_inner_durable_begin(
    tmp_path: Path,
) -> None:
    controller = OkxDemoPaperRuntimeController(
        config=OkxDemoPaperRuntimeConfig(
            repo_root=Path.cwd(),
            data_db_path=tmp_path / "missing.sqlite",
            output_dir=tmp_path / "output" / "btc_demo_paper_runtime",
        ),
        credential_loader=lambda _: _credentials(),
        start_worker=False,
    )
    create_calls: list[dict[str, Any]] = []

    def forbidden_create(*args: Any, **kwargs: Any) -> dict[str, Any]:
        create_calls.append({"args": args, "kwargs": kwargs})
        raise AssertionError("durable_begin_must_not_run_without_account_identity")

    controller._create_start_operation = forbidden_create  # type: ignore[method-assign]
    with pytest.raises(
        OkxDemoPaperRuntimeError,
        match="btc_demo_authoritative_account_identity_hash_missing",
    ):
        controller.start_operation(
            _valid_start_payload(),
            idempotency_key="missing-authoritative-identity",
        )
    assert create_calls == []
    assert controller.status()["runtime"]["start_operation"]["operation_id"] == ""


def test_account_snapshot_refresh_changes_policy_and_historicalizes_old_attempt(
    tmp_path: Path,
) -> None:
    controller = OkxDemoPaperRuntimeController(
        config=OkxDemoPaperRuntimeConfig(
            repo_root=Path.cwd(),
            data_db_path=tmp_path / "missing.sqlite",
            output_dir=tmp_path / "output" / "btc_demo_paper_runtime",
        ),
        credential_loader=lambda _: _credentials(),
        start_worker=False,
        start_capability_checker=lambda: {
            "ready": False,
            "incident_category": "local_environment",
            "blockers": ["synthetic_start_blocked"],
        },
    )
    _prime_authoritative_account_identity(
        controller,
        account_uid="uid-a",
        account_main_uid="main-a",
    )
    first_identity = controller.current_start_attempt_identity()
    first = controller.start_operation(
        _valid_start_payload(),
        idempotency_key="account-a-attempt",
    )["start_operation"]

    _prime_authoritative_account_identity(
        controller,
        account_uid="uid-b",
        account_main_uid="main-b",
    )
    second_identity = controller.current_start_attempt_identity()
    status = controller.status()
    serialized = json.dumps(status, sort_keys=True)

    assert second_identity["account_identity_hash"] != first_identity["account_identity_hash"]
    assert second_identity["effective_policy_digest"] != first_identity["effective_policy_digest"]
    assert status["runtime"]["account_identity"]["hash"] == second_identity["account_identity_hash"]
    assert status["start_operation"]["current_attempt"] is False
    assert status["start_operation"]["historical"] is True
    assert any(
        row.get("operation_id") == first["operation_id"]
        for row in status["historical_start_operations"]
    )
    assert "uid-a" not in serialized
    assert "main-a" not in serialized
    assert "uid-b" not in serialized
    assert "main-b" not in serialized
    controller._persist_state()
    persisted = (controller.config.output_dir / "state.json").read_text(
        encoding="utf-8"
    )
    assert "uid-a" not in persisted
    assert "main-a" not in persisted
    assert "uid-b" not in persisted
    assert "main-b" not in persisted


def test_missing_uid_snapshot_is_redacted_and_fail_closed(tmp_path: Path) -> None:
    controller = OkxDemoPaperRuntimeController(
        config=OkxDemoPaperRuntimeConfig(
            repo_root=Path.cwd(),
            data_db_path=tmp_path / "missing.sqlite",
            output_dir=tmp_path / "output" / "btc_demo_paper_runtime",
        ),
        credential_loader=lambda _: _credentials(),
        start_worker=False,
    )
    snapshot = controller._collect_exchange_snapshot(  # type: ignore[arg-type]
        SnapshotClient(account_uid="", account_main_uid="")
    )
    controller._apply_snapshot(snapshot)
    assert "btc_demo_authoritative_account_identity_hash_missing" in controller._preflight_blockers(
        snapshot,
        require_flat=True,
    )
    with pytest.raises(
        OkxDemoPaperRuntimeError,
        match="btc_demo_authoritative_account_identity_hash_missing",
    ):
        controller.start_operation(
            _valid_start_payload(),
            idempotency_key="missing-uid",
        )
    serialized = json.dumps(controller.status(), sort_keys=True)
    assert "uid" not in serialized
    assert "mainUid" not in serialized


def test_start_attempt_aborts_before_private_ws_when_fresh_account_changes(
    tmp_path: Path,
) -> None:
    """A bound A attempt must not continue after the fresh snapshot is B."""

    private_ws_calls: list[dict[str, Any]] = []

    def forbidden_private_ws(**kwargs: Any) -> Any:
        private_ws_calls.append(dict(kwargs))
        raise AssertionError("private_ws_must_not_start_after_account_change")

    client_b = SnapshotClient(
        account_uid="demo-account-b",
        account_main_uid="demo-main-b",
    )
    clock = lambda: datetime(
        1970,
        1,
        1,
        0,
        0,
        0,
        1000,
        tzinfo=timezone.utc,
    )
    controller = OkxDemoPaperRuntimeController(
        config=OkxDemoPaperRuntimeConfig(
            repo_root=Path.cwd(),
            data_db_path=tmp_path / "missing.sqlite",
            output_dir=tmp_path / "output" / "btc_demo_paper_runtime",
        ),
        credential_loader=lambda _: _credentials(),
        client_factory=lambda _config, _credentials_value: client_b,
        private_ws_factory=forbidden_private_ws,
        clock=clock,
        start_worker=False,
        start_capability_checker=lambda: {
            "ready": True,
            "incident_category": "none",
            "blockers": [],
        },
    )
    controller._signal_decision = lambda _strategy, **_kwargs: {
        "signal": "flat",
        "target_contracts": "0",
        "decision_bar_close_utc": clock().isoformat(),
    }
    _prime_authoritative_account_identity(
        controller,
        account_uid="demo-account-a",
        account_main_uid="demo-main-a",
    )
    accepted = controller.start_operation(
        _valid_start_payload(),
        idempotency_key="fresh-account-swap-before-private-ws",
    )
    assert controller._start_operation_thread is not None
    controller._start_operation_thread.join(5.0)

    status = controller.status()
    identity_b = controller.current_start_attempt_identity()
    operation = status["start_operation"]
    assert accepted["start_operation"]["account_identity_hash"] != identity_b[
        "account_identity_hash"
    ]
    assert status["runtime"]["account_identity"]["hash"] == identity_b[
        "account_identity_hash"
    ]
    assert operation["current_attempt"] is False
    assert operation["historical"] is True
    assert operation["state"] == "blocked"
    assert "btc_demo_start_attempt_account_identity_changed_during_preflight" in (
        status["runtime"]["last_error"]
    )
    assert "btc_demo_start_attempt_effective_policy_changed_during_preflight" in (
        status["runtime"]["last_error"]
    )
    assert operation["effective_policy_digest"] != identity_b[
        "effective_policy_digest"
    ]
    assert any(
        row.get("operation_id") == operation["operation_id"]
        for row in status["historical_start_operations"]
    )
    assert private_ws_calls == []
    assert client_b.order_calls == []
    assert client_b.cancel_calls == []
    assert client_b.dead_man_calls == []
    assert controller._private_ws is None
    serialized = json.dumps(status, sort_keys=True)
    assert "demo-account-a" not in serialized
    assert "demo-main-a" not in serialized
    assert "demo-account-b" not in serialized
    assert "demo-main-b" not in serialized


def test_bound_start_attempt_same_account_reaches_fake_private_ws_gate(
    tmp_path: Path,
) -> None:
    """A same-account fresh snapshot must retain the existing fake gate path."""

    FakePrivateWS.instances.clear()
    client = SnapshotClient(
        account_uid="demo-account-a",
        account_main_uid="demo-main-a",
    )
    clock = lambda: datetime(
        1970,
        1,
        1,
        0,
        0,
        0,
        1000,
        tzinfo=timezone.utc,
    )
    controller = OkxDemoPaperRuntimeController(
        config=OkxDemoPaperRuntimeConfig(
            repo_root=Path.cwd(),
            data_db_path=tmp_path / "missing.sqlite",
            output_dir=tmp_path / "output" / "btc_demo_paper_runtime",
        ),
        credential_loader=lambda _: _credentials(),
        client_factory=lambda _config, _credentials_value: client,
        private_ws_factory=FakePrivateWS,
        clock=clock,
        start_worker=False,
        start_capability_checker=lambda: {
            "ready": True,
            "incident_category": "none",
            "blockers": [],
        },
    )
    controller._signal_decision = lambda _strategy, **_kwargs: {
        "signal": "flat",
        "target_contracts": "0",
        "decision_bar_close_utc": clock().isoformat(),
    }
    _prime_authoritative_account_identity(
        controller,
        account_uid="demo-account-a",
        account_main_uid="demo-main-a",
    )
    accepted = controller.start_operation(
        _valid_start_payload(),
        idempotency_key="fresh-account-same-before-private-ws",
    )
    assert controller._start_operation_thread is not None
    controller._start_operation_thread.join(5.0)

    status = controller.status()
    assert accepted["start_operation"]["account_identity_hash"] == status[
        "runtime"
    ]["account_identity"]["hash"]
    assert status["start_operation"]["state"] == "completed"
    assert status["runtime"]["active"] is True
    assert status["runtime"]["opening_allowed"] is True
    assert FakePrivateWS.instances and FakePrivateWS.instances[0].monitoring_started
    try:
        assert client.order_calls == []
        assert client.cancel_calls == []
    finally:
        controller.stop({"confirmation_text": OKX_DEMO_PAPER_CONFIRMATION})


def test_start_operation_blocks_missing_local_keyring_capability_before_credentials(
    tmp_path: Path,
) -> None:
    credential_calls = 0

    def load_credentials(_service: str) -> Mapping[str, Any]:
        nonlocal credential_calls
        credential_calls += 1
        return _credentials()

    controller = OkxDemoPaperRuntimeController(
        config=OkxDemoPaperRuntimeConfig(
            repo_root=Path.cwd(),
            data_db_path=tmp_path / "missing.sqlite",
            output_dir=tmp_path / "output" / "btc_demo_paper_runtime",
        ),
        credential_loader=load_credentials,
        start_worker=False,
        start_capability_checker=lambda: {
            "ready": False,
            "incident_category": "local_environment",
            "blockers": ["python_keyring_not_installed"],
        },
    )
    _prime_authoritative_account_identity(controller)

    accepted = controller.start_operation(
        _valid_start_payload(),
        idempotency_key="missing-keyring",
    )

    assert accepted["accepted"] is True
    assert accepted["state"] == "blocked"
    assert accepted["phase"] == "blocked"
    assert accepted["start_operation"]["incident"]["category"] == "local_environment"
    assert accepted["start_operation"]["blockers"] == ["python_keyring_not_installed"]
    assert credential_calls == 0
    status = controller.status()
    assert status["runtime"]["opening_allowed"] is False
    assert status["runtime"]["cancel_only"] is True


def test_local_start_capability_accepts_windows_vault_backend_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend_type = type("WinVaultKeyring", (), {})
    backend_type.__module__ = "keyring.backends.Windows"
    backend = backend_type()
    fake_keyring = type(
        "FakeKeyringModule",
        (),
        {"get_keyring": staticmethod(lambda: backend)},
    )()
    monkeypatch.setitem(sys.modules, "keyring", fake_keyring)
    monkeypatch.setattr(
        okx_demo_runtime_module.importlib.util,
        "find_spec",
        lambda name: object() if name == "keyring" else None,
    )

    capability = OkxDemoPaperRuntimeController._local_start_capability()

    assert capability == {
        "ready": True,
        "incident_category": "none",
        "blockers": [],
    }


@pytest.mark.parametrize("backend", [None, object()])
def test_local_start_capability_rejects_null_or_non_windows_backend(
    monkeypatch: pytest.MonkeyPatch,
    backend: Any,
) -> None:
    fake_keyring = type(
        "FakeKeyringModule",
        (),
        {"get_keyring": staticmethod(lambda: backend)},
    )()
    monkeypatch.setitem(sys.modules, "keyring", fake_keyring)
    monkeypatch.setattr(
        okx_demo_runtime_module.importlib.util,
        "find_spec",
        lambda name: object() if name == "keyring" else None,
    )

    capability = OkxDemoPaperRuntimeController._local_start_capability()

    assert capability["ready"] is False
    assert capability["incident_category"] == "local_environment"
    assert capability["blockers"] == ["windows_keyring_backend_required"]


def test_local_start_capability_rejects_keyring_backend_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_get_keyring() -> Any:
        raise RuntimeError("backend probe failed")

    fake_keyring = type(
        "FakeKeyringModule",
        (),
        {"get_keyring": staticmethod(fail_get_keyring)},
    )()
    monkeypatch.setitem(sys.modules, "keyring", fake_keyring)
    monkeypatch.setattr(
        okx_demo_runtime_module.importlib.util,
        "find_spec",
        lambda name: object() if name == "keyring" else None,
    )

    capability = OkxDemoPaperRuntimeController._local_start_capability()

    assert capability["ready"] is False
    assert capability["incident_category"] == "local_environment"
    assert capability["blockers"] == ["windows_keyring_backend_unavailable"]


def test_unfinished_start_operation_restarts_interrupted_fail_closed(
    tmp_path: Path,
) -> None:
    started = threading.Event()
    release = threading.Event()
    output_dir = tmp_path / "output" / "btc_demo_paper_runtime"
    controller = OkxDemoPaperRuntimeController(
        config=OkxDemoPaperRuntimeConfig(
            repo_root=Path.cwd(),
            data_db_path=tmp_path / "missing.sqlite",
            output_dir=output_dir,
        ),
        credential_loader=lambda _: _credentials(),
        start_worker=False,
        start_capability_checker=lambda: {"ready": True, "incident_category": "none", "blockers": []},
    )

    def slow_start(_payload: Mapping[str, Any]) -> dict[str, Any]:
        started.set()
        release.wait(2.0)
        return controller.status()

    controller.start = slow_start  # type: ignore[method-assign]
    _prime_authoritative_account_identity(controller)
    controller.start_operation(_valid_start_payload(), idempotency_key="restart-op")
    assert started.wait(1.0) is True

    restarted = OkxDemoPaperRuntimeController(
        config=OkxDemoPaperRuntimeConfig(
            repo_root=Path.cwd(),
            data_db_path=tmp_path / "missing.sqlite",
            output_dir=output_dir,
        ),
        credential_loader=lambda _: _credentials(),
        start_worker=False,
        start_capability_checker=lambda: {"ready": True, "incident_category": "none", "blockers": []},
    )
    status = restarted.status()
    assert status["start_operation"]["state"] == "interrupted"
    assert status["start_operation"]["phase"] == "interrupted_fail_closed"
    assert status["runtime"]["status"] == "unclean_restart_fail_closed"
    assert status["runtime"]["opening_allowed"] is False
    assert status["runtime"]["cancel_only"] is True
    release.set()
    assert controller._start_operation_thread is not None
    controller._start_operation_thread.join(2.0)


def _startup_controller_with_private_ws(
    tmp_path: Path,
    private_ws_factory: type[FakePrivateWS],
) -> tuple[OkxDemoPaperRuntimeController, SnapshotClient]:
    client = SnapshotClient()
    clock = lambda: datetime(
        1970,
        1,
        1,
        0,
        0,
        0,
        1000,
        tzinfo=timezone.utc,
    )
    controller = OkxDemoPaperRuntimeController(
        config=OkxDemoPaperRuntimeConfig(
            repo_root=Path.cwd(),
            data_db_path=tmp_path / "unused.sqlite",
            output_dir=tmp_path / "output" / "btc_demo_paper_runtime",
        ),
        credential_loader=lambda _: _credentials(),
        client_factory=lambda _config, _credentials_value: client,
        private_ws_factory=private_ws_factory,
        clock=clock,
        start_worker=False,
    )
    controller._signal_decision = lambda _strategy, **_kwargs: {
        "signal": "flat",
        "target_contracts": "0",
        "decision_bar_close_utc": clock().isoformat(),
    }
    return controller, client


def test_status_is_local_only_and_never_loads_credentials(tmp_path: Path) -> None:
    credential_calls: list[str] = []
    controller = _controller(tmp_path, credential_calls.append)

    status = controller.status()

    assert credential_calls == []
    assert status["runtime"]["active"] is False
    assert status["runtime"]["opening_allowed"] is False
    assert status["safety"]["auto_start_on_backend_launch"] is False
    assert status["safety"]["live_order_allowed"] is False
    assert status["safety"]["real_money_order_allowed"] is False
    assert status["safety"]["transfer_allowed"] is False
    assert status["safety"]["withdraw_allowed"] is False


def test_restart_rehydrates_cumulative_observation_projection_without_backfill(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "output" / "btc_demo_paper_runtime"
    previous: str | None = None
    for offset in range(3):
        receipt = build_hourly_observation_receipt(
            source_head="a" * 40,
            strategy_version="btc-trend@1",
            data_version="btc-data-v1",
            runtime_version="okx_demo_paper_runtime_v1",
            observed_at_utc=datetime(2026, 1, 1, offset, 30, tzinfo=timezone.utc),
            heartbeat_status="healthy",
            natural_sample_count=1,
            fill_count=0,
            funding_observation_count=1,
            funding_cashflow=0.0,
            reconciliation_status="reconciled",
            outage_count=0,
            previous_receipt_sha256=previous,
            authorized_runtime_observed=True,
            runtime_run_id="demo-run",
        )
        append_hourly_observation_receipt(
            ledger_path=output_dir / "observation" / "hourly_observation_receipts.jsonl",
            receipt=receipt,
        )
        previous = str(receipt["receipt_sha256"])

    controller = _controller(tmp_path, lambda _: _credentials())
    observation = controller.status()["observation"]

    assert observation["observation_receipt_count"] == 3
    assert observation["cumulative_observation_hours"] == 3
    assert observation["cumulative_window_25h_complete"] is False
    assert observation["consecutive_hours"] == 3
    assert observation["window_complete"] is False
    assert observation["cumulative_blockers"] == [
        "btc_okx_native:25_hour_demo_observation_window_incomplete"
    ]


def test_status_projects_legacy_events_without_traversing_state_after(
    tmp_path: Path,
) -> None:
    class PoisonStateAfter:
        def __str__(self) -> str:
            raise AssertionError("status_must_not_traverse_legacy_state_after")

    controller = _controller(tmp_path, lambda _: _credentials())
    preserved_sections = (
        "runtime",
        "private_ws",
        "signal",
        "exchange",
        "observation",
        "ledger_reconciliation",
        "safety",
    )
    for section in preserved_sections:
        controller._state[section]["unknown_projection_marker"] = section
    expected_sections = {
        section: json.loads(json.dumps(controller._state[section]))
        for section in preserved_sections
    }
    expected_sections["runtime"]["worker_alive"] = False

    huge_legacy_value = "x" * (1024 * 1024)
    legacy_events = []
    for index in range(40):
        event = {
            "timestamp_utc": f"2026-08-01T00:{index:02d}:00+00:00",
            "event_type": "legacy_runtime_event",
            "payload": {"index": index},
            "sequence": index + 1,
            "state_after": {
                "huge": huge_legacy_value,
                "poison": PoisonStateAfter(),
            },
        }
        if index == 0:
            event["event_id"] = "legacy-explicit-event-id"
        elif index == 1:
            event["event_hash"] = "legacy-event-hash"
        legacy_events.append(event)
    controller._state["events"] = legacy_events

    first_status = controller.status()
    second_status = controller.status()
    encoded = json.dumps(first_status, separators=(",", ":")).encode("utf-8")

    assert len(encoded) <= 256 * 1024
    assert "state_after" not in encoded.decode("utf-8")
    assert len(first_status["events"]) == 40
    assert all(
        set(event) == {"event_id", "timestamp_utc", "event_type", "payload"}
        for event in first_status["events"]
    )
    assert first_status["events"][0]["event_id"] == "legacy-explicit-event-id"
    assert first_status["events"][1]["event_id"] == "legacy-event-hash"
    assert first_status["events"][2]["event_id"]
    assert (
        first_status["events"][2]["event_id"]
        == second_status["events"][2]["event_id"]
    )
    for section, expected in expected_sections.items():
        assert first_status[section] == expected


def test_append_and_checkpoint_use_event_free_durable_snapshot(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "output" / "btc_demo_paper_runtime"
    controller = _controller(tmp_path, lambda _: _credentials())
    controller._state["runtime"].update({"run_id": "compact", "active": True})

    controller._append_event("first", {"marker": 1})
    controller._append_event("second", {"marker": 2})
    controller._persist_state()

    persisted_events = [
        json.loads(line)
        for line in (output_dir / "events.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
    ]
    checkpoint = json.loads(
        (output_dir / "state.json").read_text(encoding="utf-8")
    )
    assert len(persisted_events) == 2
    assert all("events" not in event["state_after"] for event in persisted_events)
    assert "events" not in checkpoint["state"]

    recovered = _controller(tmp_path, lambda _: _credentials())
    recovered_status = recovered.status()
    assert recovered_status["runtime"]["cancel_only"] is True
    assert recovered_status["runtime"]["opening_allowed"] is False
    assert "okx_demo_paper_previous_runtime_not_cleanly_stopped" in (
        recovered_status["runtime"]["blockers"]
    )
    assert [event["payload"] for event in recovered_status["events"]] == [
        {"marker": 2},
        {"marker": 1},
    ]
    assert all(
        set(event) == {"event_id", "timestamp_utc", "event_type", "payload"}
        for event in recovered_status["events"]
    )


def test_restart_restores_exact_persisted_cancel_only_for_emergency_prestate(
    tmp_path: Path,
) -> None:
    controller = _controller(tmp_path, lambda _: _credentials())
    controller._state["risk_control"]["write_path_trusted"] = True
    controller._state["risk_control"]["dead_man"].update(
        {
            "armed": True,
            "heartbeat_thread_alive": True,
            "watchdog_renews_dead_man": True,
        }
    )
    controller._state["safety"]["okx_demo_order_capability_enabled"] = True

    # This is the same offline public transition used before a backend
    # restart; its lock is released, leaving only the durable state for the
    # next controller instance to recover.
    controller.enter_cancel_only({"confirmation_text": "CANCEL ONLY"})
    assert controller._fault_drill_lock_handle is None

    recovered = _controller(tmp_path, lambda _: _credentials())
    status = recovered.status()
    runtime = status["runtime"]
    assert runtime["active"] is False
    assert runtime["opening_allowed"] is False
    assert runtime["cancel_only"] is True
    assert runtime["status"] == "blocked_fail_closed"
    assert "okx_demo_previous_cancel_only_state_restored" in runtime["blockers"]
    assert status["risk_control"]["mode"] == "FROZEN_UNKNOWN"
    assert status["risk_control"]["write_path_trusted"] is False
    assert status["risk_control"]["dead_man"]["armed"] is False
    assert status["risk_control"]["dead_man"]["heartbeat_thread_alive"] is False
    assert status["risk_control"]["dead_man"]["watchdog_renews_dead_man"] is False
    assert status["safety"]["okx_demo_order_capability_enabled"] is False
    assert status["safety"]["live_order_allowed"] is False
    assert status["safety"]["real_money_order_allowed"] is False
    assert status["safety"]["transfer_allowed"] is False
    assert status["safety"]["withdraw_allowed"] is False
    assert recovered._thread is None
    assert recovered._dead_man_thread is None
    assert recovered._client is None
    assert recovered._private_ws is None


def test_restart_does_not_promote_normal_clean_stopped_to_cancel_only(
    tmp_path: Path,
) -> None:
    controller = _controller(tmp_path, lambda _: _credentials())
    controller._state["runtime"].update(
        {
            "status": "stopped",
            "active": False,
            "opening_allowed": False,
            "cancel_only": False,
        }
    )
    controller._state["risk_control"]["mode"] = "FROZEN_UNKNOWN"
    controller._persist_state()

    recovered = _controller(tmp_path, lambda _: _credentials())
    runtime = recovered.status()["runtime"]
    assert runtime["status"] == "stopped"
    assert runtime["active"] is False
    assert runtime["opening_allowed"] is False
    assert runtime["cancel_only"] is False


@pytest.mark.parametrize(
    ("runtime_patch", "risk_mode"),
    [
        ({"active": True, "opening_allowed": True, "cancel_only": False}, "RUNNING"),
        ({"active": False, "opening_allowed": True, "cancel_only": True}, "FROZEN_UNKNOWN"),
        ({"active": False, "opening_allowed": False, "cancel_only": True}, "RUNNING"),
    ],
)
def test_restart_rejects_incomplete_cancel_only_combinations_fail_closed(
    tmp_path: Path,
    runtime_patch: Mapping[str, Any],
    risk_mode: str,
) -> None:
    controller = _controller(tmp_path, lambda _: _credentials())
    controller._state["runtime"].update(runtime_patch)
    controller._state["risk_control"]["mode"] = risk_mode
    controller._persist_state()

    recovered = _controller(tmp_path, lambda _: _credentials())
    status = recovered.status()
    runtime = status["runtime"]
    assert runtime["status"] == "unclean_restart_fail_closed"
    assert runtime["active"] is False
    assert runtime["opening_allowed"] is False
    assert runtime["cancel_only"] is True
    assert status["risk_control"]["mode"] == "FROZEN_UNKNOWN"
    assert status["risk_control"]["write_path_trusted"] is False
    assert status["risk_control"]["dead_man"]["armed"] is False
    assert status["safety"]["okx_demo_order_capability_enabled"] is False
    assert status["safety"]["live_order_allowed"] is False
    assert status["safety"]["real_money_order_allowed"] is False
    assert status["safety"]["transfer_allowed"] is False
    assert status["safety"]["withdraw_allowed"] is False
    assert recovered._thread is None
    assert recovered._dead_man_thread is None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("active", None),
        ("opening_allowed", None),
        ("cancel_only", None),
        ("active", 0),
    ],
)
def test_restart_rejects_missing_or_non_boolean_runtime_flags_fail_closed(
    tmp_path: Path,
    field: str,
    value: Any,
) -> None:
    controller = _controller(tmp_path, lambda _: _credentials())
    controller._state["runtime"].update(
        {
            "status": "blocked_fail_closed",
            "active": False,
            "opening_allowed": False,
            "cancel_only": True,
        }
    )
    controller._state["risk_control"]["mode"] = "FROZEN_UNKNOWN"
    if value is None:
        del controller._state["runtime"][field]
    else:
        controller._state["runtime"][field] = value
    controller._persist_state()

    recovered = _controller(tmp_path, lambda _: _credentials())
    status = recovered.status()
    runtime = status["runtime"]

    assert runtime["status"] == "unclean_restart_fail_closed"
    assert runtime["active"] is False
    assert runtime["opening_allowed"] is False
    assert runtime["cancel_only"] is True
    assert (
        "okx_demo_previous_runtime_flags_not_strict_boolean"
        in runtime["blockers"]
    )
    assert status["risk_control"]["mode"] == "FROZEN_UNKNOWN"
    assert status["risk_control"]["write_path_trusted"] is False
    assert status["risk_control"]["dead_man"]["armed"] is False
    assert status["safety"]["okx_demo_order_capability_enabled"] is False
    assert status["safety"]["live_order_allowed"] is False
    assert status["safety"]["real_money_order_allowed"] is False
    assert status["safety"]["transfer_allowed"] is False
    assert status["safety"]["withdraw_allowed"] is False
    assert recovered._thread is None
    assert recovered._dead_man_thread is None
    assert recovered._client is None
    assert recovered._private_ws is None


def test_legacy_recursive_event_log_recovers_fail_closed_without_status_bloat(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "output" / "btc_demo_paper_runtime"
    legacy_state = {
        "runtime": {"active": True, "status": "running"},
        "exchange": {"legacy_snapshot_marker": "preserved"},
        "audit": [{"legacy_audit_marker": "preserved"}],
        "events": [
            {
                "event_type": "older_recursive_event",
                "state_after": {"huge": "x" * (1024 * 1024)},
            }
        ],
    }
    stored_event = BTCRuntimeStore(output_dir).append(
        event_type="legacy_runtime_event",
        payload={"legacy_payload_marker": "preserved"},
        state_after=legacy_state,
        idempotency_key="legacy-runtime-event",
        timestamp_utc="2026-08-01T00:00:00+00:00",
        run_id="legacy",
        safety={"live_order_allowed": False},
    )
    assert "events" in stored_event["state_after"]

    recovered = _controller(tmp_path, lambda _: _credentials())
    status = recovered.status()
    encoded = json.dumps(status, separators=(",", ":")).encode("utf-8")

    assert status["exchange"] == {"legacy_snapshot_marker": "preserved"}
    assert status["audit"] == [{"legacy_audit_marker": "preserved"}]
    assert status["runtime"]["status"] == "unclean_restart_fail_closed"
    assert status["runtime"]["cancel_only"] is True
    assert status["runtime"]["opening_allowed"] is False
    assert "okx_demo_paper_previous_runtime_not_cleanly_stopped" in (
        status["runtime"]["blockers"]
    )
    assert status["events"] == [
        {
            "event_id": stored_event["event_hash"],
            "timestamp_utc": "2026-08-01T00:00:00+00:00",
            "event_type": "legacy_runtime_event",
            "payload": {"legacy_payload_marker": "preserved"},
        }
    ]
    assert b"state_after" not in encoded
    assert len(encoded) <= 256 * 1024


def test_restart_restores_only_ledger_proven_order_ids_for_private_ws(
    tmp_path: Path,
) -> None:
    known_client_order_id = "btcDPknown0001"
    controller = _controller(tmp_path, lambda _: _credentials())
    controller._state["runtime"]["run_id"] = "run-known"
    controller._append_event(
        "order_lifecycle",
        {
            "oms": {"client_order_id": known_client_order_id},
            "fills": [{"client_order_id": known_client_order_id}],
        },
    )
    controller._append_event(
        "ledger_uow_committed",
        {
            "order_ledger": {"orders": [{"client_order_id": known_client_order_id}]},
            "fill_ledger": [{"client_order_id": known_client_order_id}],
        },
    )

    recovered = _controller(tmp_path, lambda _: _credentials())

    assert known_client_order_id in recovered._owned_client_order_ids
    assert "btcDPexternal0001" not in recovered._owned_client_order_ids

    class SnapshotTransport:
        def __init__(self, snapshot: BTCPrivateWSStartupSnapshot) -> None:
            self.snapshot = snapshot

        def fetch_startup_snapshot(self) -> BTCPrivateWSStartupSnapshot:
            return self.snapshot

    def snapshot(fill_client_order_id: str) -> BTCPrivateWSStartupSnapshot:
        return BTCPrivateWSStartupSnapshot(
            open_orders=(),
            fills=({"client_order_id": fill_client_order_id},),
            positions=(),
            balance={"equity_usdt": "5000"},
            funding_bills=(),
            last_sequence=0,
            private_ws_status="connected",
            rest_status="ok",
            captured_at_utc=datetime.now(timezone.utc),
        )

    known_receipt = BTCPrivateWSRuntimeReconciler(
        transport=SnapshotTransport(snapshot(known_client_order_id)),
        owned_client_order_ids=tuple(recovered._owned_client_order_ids),
    ).startup()
    assert known_receipt.opening_allowed is True
    assert known_receipt.blockers == ()

    unknown_receipt = BTCPrivateWSRuntimeReconciler(
        transport=SnapshotTransport(snapshot("btcDPexternal0001")),
        owned_client_order_ids=tuple(recovered._owned_client_order_ids),
    ).startup()
    assert unknown_receipt.opening_allowed is False
    assert "btc_private_ws:unknown_fill" in unknown_receipt.blockers


def test_owned_id_restore_uses_same_run_three_way_intersection_only(
    tmp_path: Path,
) -> None:
    archive, identity = _owned_id_restore_archive(tmp_path)

    projection = okx_demo_runtime_module._build_owned_id_restore_projection(
        archive_root=archive,
        repo_root=Path.cwd(),
        credential_service="quant-system.okx-demo.trade",
        **identity,
    )

    assert projection["owned_triples"] == [
        {
            "client_order_id": "btcDPowned-ru0001",
            "order_id": "order-owned-1",
            "fill_id": "fill-owned-1",
            "run_id": "owned-run-01",
        },
        {
            "client_order_id": "btcDPowned-ru0002",
            "order_id": "order-owned-2",
            "fill_id": "fill-owned-2",
            "run_id": "owned-run-01",
        },
    ]
    assert projection["identity_only"] is True
    assert projection["opening_allowed"] is False
    assert projection["position_restored"] is False
    assert projection["order_capability_restored"] is False
    assert projection["receipt_ledger_not_used_as_ownership_proof"] is True
    assert projection["exchange_snapshot_not_used_as_ownership_proof"] is True


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("current_head", "f" * 40),
        ("source_head", "f" * 40),
        ("account_identity", "wrong-account"),
        ("credential_identity", "wrong-credential"),
        ("client_order_namespace", "foreign"),
    ),
)
def test_owned_id_restore_identity_mismatch_is_zero_ownership(
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    archive, identity = _owned_id_restore_archive(tmp_path)
    identity[field] = value

    with pytest.raises(OkxDemoPaperRuntimeError):
        okx_demo_runtime_module._build_owned_id_restore_projection(
            archive_root=archive,
            repo_root=Path.cwd(),
            credential_service="quant-system.okx-demo.trade",
            **identity,
        )


@pytest.mark.parametrize(
    "namespace",
    (
        "btc",
        "btcDP",
        "BTCDPowned-ru",
        "btcDPowned-r",
        "btcDPowned-ru0",
        "foreign-namespace",
    ),
)
def test_owned_id_restore_namespace_must_be_exact_authoritative_run_projection(
    tmp_path: Path,
    namespace: str,
) -> None:
    archive, identity = _owned_id_restore_archive(tmp_path)
    identity["client_order_namespace"] = namespace

    with pytest.raises(OkxDemoPaperRuntimeError):
        okx_demo_runtime_module._build_owned_id_restore_projection(
            archive_root=archive,
            repo_root=Path.cwd(),
            credential_service="quant-system.okx-demo.trade",
            **identity,
        )


def test_owned_id_restore_tamper_and_counts_only_never_establish_ownership(
    tmp_path: Path,
) -> None:
    archive, identity = _owned_id_restore_archive(tmp_path)
    events_path = archive / "source_snapshots" / "runtime_events.jsonl"
    events_path.write_bytes(events_path.read_bytes() + b"\n")
    with pytest.raises(OkxDemoPaperRuntimeError):
        okx_demo_runtime_module._build_owned_id_restore_projection(
            archive_root=archive,
            repo_root=Path.cwd(),
            credential_service="quant-system.okx-demo.trade",
            **identity,
        )

    ledger_only, ledger_identity = _owned_id_restore_archive(
        tmp_path / "ledger-only", include_lifecycle=False
    )
    with pytest.raises(OkxDemoPaperRuntimeError):
        okx_demo_runtime_module._build_owned_id_restore_projection(
            archive_root=ledger_only,
            repo_root=Path.cwd(),
            credential_service="quant-system.okx-demo.trade",
            **ledger_identity,
        )

    exchange_only, exchange_identity = _owned_id_restore_archive(
        tmp_path / "exchange-only", include_lifecycle=False, include_ledger=False
    )
    with pytest.raises(OkxDemoPaperRuntimeError):
        okx_demo_runtime_module._build_owned_id_restore_projection(
            archive_root=exchange_only,
            repo_root=Path.cwd(),
            credential_service="quant-system.okx-demo.trade",
            **exchange_identity,
        )


def test_owned_id_restore_missing_archived_identities_rejects_after_self_consistent_rehash(
    tmp_path: Path,
) -> None:
    archive, identity = _owned_id_restore_archive(tmp_path)
    manifest_path = archive / "manifest.json"
    completed_path = archive / "COMPLETED.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    execution_identity = manifest["execution_identity"]
    assert isinstance(execution_identity, dict)
    del execution_identity["account_identity"]
    del execution_identity["credential_identity"]
    manifest_path.write_text(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    completed = json.loads(completed_path.read_text(encoding="utf-8"))
    completed["manifest_sha256"] = hashlib.sha256(
        manifest_path.read_bytes()
    ).hexdigest()
    completed_path.write_text(
        json.dumps(completed, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )

    with pytest.raises(OkxDemoPaperRuntimeError):
        okx_demo_runtime_module._build_owned_id_restore_projection(
            archive_root=archive,
            repo_root=Path.cwd(),
            credential_service="quant-system.okx-demo.trade",
            **identity,
        )


def test_owned_id_restore_applies_ids_without_position_or_capability_restore(
    tmp_path: Path,
) -> None:
    archive, identity = _owned_id_restore_archive(tmp_path)
    payload = _valid_start_payload()
    payload.update(
        {
            "owned_id_restore_archive_root": str(archive),
            "owned_id_restore_current_head": identity["current_head"],
            "owned_id_restore_source_head": identity["source_head"],
            "owned_id_restore_account_identity": identity["account_identity"],
            "owned_id_restore_credential_identity": identity[
                "credential_identity"
            ],
            "owned_id_restore_client_order_namespace": identity[
                "client_order_namespace"
            ],
        }
    )
    request = okx_demo_runtime_module.OkxDemoPaperStartRequest.from_mapping(payload)
    controller = OkxDemoPaperRuntimeController(
        config=OkxDemoPaperRuntimeConfig(
            repo_root=Path.cwd(),
            data_db_path=tmp_path / "controller" / "unused.sqlite",
            output_dir=tmp_path / "controller" / "output",
        ),
        credential_loader=lambda _: _credentials(),
        start_worker=False,
    )

    controller._apply_owned_id_restore(request)

    assert controller._owned_client_order_ids == {
        "btcDPowned-ru0001",
        "btcDPowned-ru0002",
    }
    assert controller._state["exchange"]["positions"] == []
    assert controller._state["runtime"]["opening_allowed"] is False
    assert controller._state["runtime"]["cancel_only"] is False
    assert controller._state["safety"]["okx_demo_order_capability_enabled"] is False
    assert controller._state["safety"]["live_order_allowed"] is False
    assert controller._state["risk_control"]["owned_id_restore"][
        "identity_only"
    ] is True


def test_no_restore_arguments_do_not_scan_external_archives(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        okx_demo_runtime_module,
        "_build_owned_id_restore_projection",
        lambda **_: (_ for _ in ()).throw(
            AssertionError("restore_scanned_without_explicit_arguments")
        ),
    )
    controller = _controller(tmp_path, lambda _: _credentials())
    controller._apply_owned_id_restore(
        okx_demo_runtime_module.OkxDemoPaperStartRequest.from_mapping(
            _valid_start_payload()
        )
    )


def test_demo_clock_guard_keeps_margin_inside_exchange_auth_window(tmp_path: Path) -> None:
    controller = _controller(tmp_path, lambda _: _credentials())

    assert controller.config.max_clock_offset_ms == OKX_DEMO_PAPER_MAX_CLOCK_OFFSET_MS
    assert controller.config.max_clock_offset_ms == 15_000
    assert controller.config.max_clock_offset_ms < 30_000


def test_demo_clock_guard_anchors_to_snapshot_capture_after_slow_cycle(
    tmp_path: Path,
) -> None:
    captured_at = datetime(2026, 8, 6, 15, 20, tzinfo=timezone.utc)
    controller = _controller(tmp_path, lambda _: _credentials())
    controller._clock = lambda: captured_at + timedelta(minutes=5)

    blockers = controller._preflight_blockers(
        {
            "captured_at_utc": captured_at.isoformat(),
            "server_time_ms": str(int((captured_at + timedelta(seconds=1)).timestamp() * 1000)),
        },
        require_flat=False,
    )

    assert "okx_demo_paper_clock_offset_breached" not in blockers


def test_demo_clock_guard_uses_adjacent_server_time_sample_after_slow_collection(
    tmp_path: Path,
) -> None:
    collection_started = datetime(2026, 8, 25, 10, 0, tzinfo=timezone.utc)
    time_request_started = collection_started + timedelta(seconds=30)
    time_response_received = time_request_started + timedelta(milliseconds=200)
    exchange_server_time = time_request_started + timedelta(milliseconds=100)
    clock_samples = iter(
        (collection_started, time_request_started, time_response_received)
    )
    controller = _controller(tmp_path, lambda _: _credentials())
    controller._clock = lambda: next(clock_samples)
    client = SnapshotClient(
        server_time_ms=str(int(exchange_server_time.timestamp() * 1000))
    )

    snapshot = controller._collect_exchange_snapshot(client)  # type: ignore[arg-type]
    blockers = controller._preflight_blockers(snapshot, require_flat=False)

    assert snapshot["captured_at_utc"] == collection_started.isoformat()
    assert snapshot["server_time_local_midpoint_ms"] == str(
        int(exchange_server_time.timestamp() * 1000)
    )
    assert snapshot["server_time_round_trip_ms"] == "200"
    assert "okx_demo_paper_clock_offset_breached" not in blockers


def test_demo_clock_guard_still_rejects_true_offset_with_adjacent_sample(
    tmp_path: Path,
) -> None:
    collection_started = datetime(2026, 8, 25, 10, 0, tzinfo=timezone.utc)
    time_request_started = collection_started + timedelta(seconds=30)
    time_response_received = time_request_started + timedelta(milliseconds=200)
    exchange_server_time = time_request_started + timedelta(seconds=20)
    clock_samples = iter(
        (collection_started, time_request_started, time_response_received)
    )
    controller = _controller(tmp_path, lambda _: _credentials())
    controller._clock = lambda: next(clock_samples)
    client = SnapshotClient(
        server_time_ms=str(int(exchange_server_time.timestamp() * 1000))
    )

    snapshot = controller._collect_exchange_snapshot(client)  # type: ignore[arg-type]
    blockers = controller._preflight_blockers(snapshot, require_flat=False)

    assert "okx_demo_paper_clock_offset_breached" in blockers


def test_valid_start_fails_on_missing_okx_native_signal_seed_before_private_calls(tmp_path: Path) -> None:
    credential_calls: list[str] = []
    controller = _controller(tmp_path, credential_calls.append)

    with pytest.raises(
        OkxDemoPaperRuntimeError,
        match="okx_demo_paper_okx_native_pointer_missing",
    ):
        controller.start(_valid_start_payload())

    assert credential_calls == [controller.config.credential_service]
    status = controller.status()
    assert status["runtime"]["status"] == "start_blocked_fail_closed"
    assert status["runtime"]["cancel_only"] is True
    assert status["safety"]["okx_demo_private_read_enabled"] is False
    assert status["safety"]["okx_demo_order_capability_enabled"] is False
    assert controller._fault_drill_lock_handle is None
    probe = _controller(tmp_path, lambda _: _credentials())
    assert probe.acquire_fault_drill_process_lock(nonce="failureprobe")[
        "acquired"
    ] is True
    probe.release_fault_drill_process_lock()


def test_stable_start_uses_okx_public_tail_before_private_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The legacy line must not use stale/local 1h data as a start gate."""

    now = datetime(2026, 7, 30, 4, 5, tzinfo=timezone.utc)
    stable_spec = next(
        spec
        for spec in btc_strategy_registry.list_specs()
        if spec.strategy_id == "long_short_donchian_top5"
    )
    baseline = _large_hourly_frame(now - timedelta(hours=1))
    client = SnapshotClient()
    stages: list[str] = []

    def load_seed(*_args: Any, **_kwargs: Any) -> Any:
        stages.append("seed")
        return baseline

    def merge_tail(*, baseline: Any, client: Any, now: datetime) -> tuple[Any, dict[str, Any]]:
        del client, now
        stages.append("public_tail")
        return baseline, {
            "source": "okx_public_rest",
            "sample_end_utc": baseline.index[-1].isoformat(),
            "confirmed_only": True,
            "integrity_passed": True,
        }

    monkeypatch.setattr(
        okx_demo_runtime_module,
        "load_completed_okx_native_hourly_frame",
        load_seed,
    )
    monkeypatch.setattr(
        okx_demo_runtime_module,
        "_merge_okx_native_public_candle_tail",
        merge_tail,
    )
    monkeypatch.setattr(
        okx_demo_runtime_module,
        "load_completed_btc_hourly_frame",
        lambda *_args, **_kwargs: pytest.fail(
            "legacy local completed-1h loader used during Demo start"
        ),
    )
    controller = OkxDemoPaperRuntimeController(
        config=OkxDemoPaperRuntimeConfig(
            repo_root=Path.cwd(),
            data_db_path=tmp_path / "unused.sqlite",
            output_dir=tmp_path / "output" / "btc_demo_paper_runtime",
        ),
        credential_loader=lambda _: _credentials(),
        client_factory=lambda _config, _credentials_value: client,
        clock=lambda: now,
        start_worker=False,
    )
    controller._collect_exchange_snapshot = lambda _client: (_ for _ in ()).throw(
        OkxDemoPaperRuntimeError("stop_after_public_tail")
    )  # type: ignore[method-assign]

    with pytest.raises(OkxDemoPaperRuntimeError, match="stop_after_public_tail"):
        controller.start(_start_payload_for(stable_spec))

    assert stages == ["seed", "public_tail"]
    assert client.private_calls == []


def test_explicit_demo_start_runs_private_ws_reconnect_probe_before_opening(
    tmp_path: Path,
) -> None:
    FakePrivateWS.instances.clear()
    client = SnapshotClient()
    clock = lambda: datetime(1970, 1, 1, 0, 0, 0, 1000, tzinfo=timezone.utc)
    controller = OkxDemoPaperRuntimeController(
        config=OkxDemoPaperRuntimeConfig(
            repo_root=Path.cwd(),
            data_db_path=tmp_path / "unused.sqlite",
            output_dir=tmp_path / "output" / "btc_demo_paper_runtime",
        ),
        credential_loader=lambda _: _credentials(),
        client_factory=lambda _config, _credentials_value: client,
        private_ws_factory=FakePrivateWS,
        clock=clock,
        start_worker=False,
    )
    controller._signal_decision = lambda _strategy, **_kwargs: {
        "signal": "flat",
        "target_contracts": "0",
        "decision_bar_close_utc": clock().isoformat(),
    }

    status = controller.start(_valid_start_payload())

    assert controller._fault_drill_lock_handle is not None
    assert status["runtime"]["active"] is True
    assert status["runtime"]["opening_allowed"] is True
    assert status["runtime"]["cancel_only"] is False
    assert status["private_ws"]["opening_allowed_after_reconciliation"] is True
    assert status["private_ws"]["promotion_evidence_ready"] is False
    assert FakePrivateWS.instances[0].monitoring_started is True
    assert status["risk_control"]["dead_man"][
        "heartbeat_thread_alive"
    ] is True
    assert status["risk_control"]["dead_man"][
        "watchdog_renews_dead_man"
    ] is True
    assert status["safety"]["live_order_allowed"] is False
    assert status["safety"]["real_money_order_allowed"] is False

    stopped = controller.stop({"confirmation_text": OKX_DEMO_PAPER_CONFIRMATION})
    assert stopped["runtime"]["active"] is False
    assert stopped["risk_control"]["dead_man"][
        "heartbeat_thread_alive"
    ] is False
    assert stopped["risk_control"]["dead_man"]["armed"] is False
    assert FakePrivateWS.instances[0].stopped is True
    assert controller._fault_drill_lock_handle is None


def test_slow_private_ws_probe_refreshes_boundary_projection_before_dead_man(
    tmp_path: Path,
) -> None:
    """A healthy probe may outlive the boundary's 30-second freshness TTL."""

    FakePrivateWS.instances.clear()
    current = datetime.now(timezone.utc)
    observed_at = [current - timedelta(minutes=2)]

    class ClockedSnapshotClient(SnapshotClient):
        def public_get(
            self,
            path: str,
            params: Mapping[str, Any] | None = None,
        ) -> OkxDemoResponse:
            if path == "/api/v5/public/time":
                self.public_calls.append(
                    {"path": path, "params": dict(params or {})}
                )
                return OkxDemoResponse(
                    method="GET",
                    path=path,
                    http_status=200,
                    code="0",
                    message="",
                    data=(
                        {
                            "ts": str(
                                int(observed_at[0].timestamp() * 1000)
                            )
                        },
                    ),
                )
            return super().public_get(path, params)

    class SlowPrivateWS(FakePrivateWS):
        def run_startup_reconnect_probe(self) -> dict[str, Any]:
            observed_at[0] = current
            return super().run_startup_reconnect_probe()

    class DemoAdapter:
        def capability_for(self, *, action, transport_context):
            assert action is RuntimeAction.DEAD_MAN
            assert isinstance(transport_context, ClockedSnapshotClient)
            return BTCEndpointCapability(
                mode=BTCExecutionMode.DEMO,
                transport_enabled=True,
                submit_new_order=True,
                cancel_order=True,
                reduce_only=True,
                attach_protection=True,
                dead_man=True,
                private_endpoint_allowed=True,
                order_endpoint_allowed=True,
            )

    source_head = _repo_head_for_test()
    dispatcher = BTCDemoExecutionDispatcher(
        expected_source_head=source_head,
        state_directory=tmp_path / "btc-demo-boundary",
        capability_adapter=DemoAdapter(),
        credential_service="quant-system.okx-demo.trade",
    )
    client = ClockedSnapshotClient()
    controller = OkxDemoPaperRuntimeController(
        config=OkxDemoPaperRuntimeConfig(
            repo_root=Path.cwd(),
            data_db_path=tmp_path / "unused.sqlite",
            output_dir=tmp_path / "output" / "btc_demo_paper_runtime",
            dead_man_heartbeat_seconds=5,
            execution_dispatcher=dispatcher,
        ),
        credential_loader=lambda _: _credentials(),
        client_factory=lambda _config, _credentials_value: client,
        private_ws_factory=SlowPrivateWS,
        clock=lambda: observed_at[0],
        start_worker=False,
    )
    controller._signal_decision = lambda _strategy, **_kwargs: {
        "signal": "flat",
        "target_contracts": "0",
        "decision_bar_close_utc": observed_at[0].isoformat(),
    }

    status = controller.start(_valid_start_payload())
    try:
        assert status["runtime"]["active"] is True
        assert status["runtime"]["opening_allowed"] is True
        assert status["private_ws"]["connected"] is True
        assert status["private_ws"]["listener_alive"] is True
        assert status["ledger_reconciliation"]["trigger"] == (
            "startup_post_private_ws_reconciliation"
        )
        assert status["exchange"]["captured_at_utc"] == current.isoformat()
        assert client.dead_man_calls == [
            {"timeout_seconds": 30, "tag": "btcP0Demo"}
        ]
        controller._arm_dead_man(client, trigger="heartbeat")
        controller._arm_dead_man(client, trigger="heartbeat")
        assert client.dead_man_calls == [
            {"timeout_seconds": 30, "tag": "btcP0Demo"},
            {"timeout_seconds": 30, "tag": "btcP0Demo"},
            {"timeout_seconds": 30, "tag": "btcP0Demo"},
        ]
        lifecycle_files = list(
            (tmp_path / "btc-demo-boundary").glob(
                "demo-namespace-*/client_order_lifecycle.jsonl"
            )
        )
        assert len(lifecycle_files) == 1
        lifecycle_rows = [
            json.loads(line)
            for line in lifecycle_files[0].read_text(
                encoding="utf-8"
            ).splitlines()
        ]
        lifecycle_ids = {
            str(row["client_order_id"])
            for row in lifecycle_rows
        }
        expected_namespace = f"btcDP{status['runtime']['run_id'][:8]}"
        assert len(lifecycle_ids) == 3
        assert all(
            client_order_id.startswith(expected_namespace)
            for client_order_id in lifecycle_ids
        )
        assert client.order_calls == []
        assert client.cancel_calls == []
    finally:
        controller.stop(
            {"confirmation_text": OKX_DEMO_PAPER_CONFIRMATION}
        )


def test_start_persists_complete_monitoring_status_for_durable_opening_gate(
    tmp_path: Path,
) -> None:
    FakePrivateWS.instances.clear()
    controller, client = _startup_controller_with_private_ws(
        tmp_path,
        FakePrivateWS,
    )

    status = controller.start(_valid_start_payload())
    try:
        assert status["private_ws"]["connected"] is True
        assert status["private_ws"]["listener_alive"] is True
        assert status["private_ws"][
            "opening_allowed_after_reconciliation"
        ] is True
        controller._assert_order_submit_path(is_opening=True)
        durable = controller._durable_state_snapshot()["private_ws"]
        assert durable["connected"] is True
        assert durable["listener_alive"] is True
        assert durable["opening_allowed_after_reconciliation"] is True
        assert client.order_calls == []
    finally:
        controller.stop(
            {"confirmation_text": OKX_DEMO_PAPER_CONFIRMATION}
        )


@pytest.mark.parametrize(
    "private_ws_factory",
    [
        MissingListenerMonitoringStatusPrivateWS,
        FalseListenerMonitoringStatusPrivateWS,
    ],
)
def test_start_fails_closed_when_monitoring_status_is_incomplete_or_false(
    tmp_path: Path,
    private_ws_factory: type[FakePrivateWS],
) -> None:
    FakePrivateWS.instances.clear()
    controller, client = _startup_controller_with_private_ws(
        tmp_path,
        private_ws_factory,
    )

    try:
        with pytest.raises(
            OkxDemoPaperRuntimeError,
            match="okx_demo_private_ws_monitoring_status_not_trusted",
        ):
            controller.start(_valid_start_payload())
    finally:
        if controller.status()["runtime"]["active"] is True:
            controller.stop(
                {"confirmation_text": OKX_DEMO_PAPER_CONFIRMATION}
            )

    status = controller.status()
    assert status["runtime"]["active"] is False
    assert status["runtime"]["opening_allowed"] is False
    assert status["runtime"]["cancel_only"] is True
    assert status["private_ws"]["connected"] is False
    assert status["private_ws"]["listener_alive"] is False
    assert status["private_ws"][
        "opening_allowed_after_reconciliation"
    ] is False
    assert status["risk_control"]["dead_man"]["armed"] is False
    assert status["safety"]["okx_demo_private_read_enabled"] is False
    assert status["safety"]["okx_demo_order_capability_enabled"] is False
    assert status["safety"]["okx_demo_cancel_capability_enabled"] is False
    assert client.order_calls == []
    assert client.cancel_calls == []
    assert FakePrivateWS.instances[0].stopped is True
    assert controller._fault_drill_lock_handle is None


def test_start_commits_fresh_ledger_reconciliation_before_opening(
    tmp_path: Path,
) -> None:
    FakePrivateWS.instances.clear()
    client = SnapshotClient()
    clock = lambda: datetime(1970, 1, 1, 0, 0, 0, 1000, tzinfo=timezone.utc)
    controller = OkxDemoPaperRuntimeController(
        config=OkxDemoPaperRuntimeConfig(
            repo_root=Path.cwd(),
            data_db_path=tmp_path / "unused.sqlite",
            output_dir=tmp_path / "output" / "btc_demo_paper_runtime",
        ),
        credential_loader=lambda _: _credentials(),
        client_factory=lambda _config, _credentials_value: client,
        private_ws_factory=FakePrivateWS,
        clock=clock,
        start_worker=False,
    )
    controller._signal_decision = lambda _strategy, **_kwargs: {
        "signal": "flat",
        "target_contracts": "0",
        "decision_bar_close_utc": clock().isoformat(),
    }
    opening_at_commit: list[bool] = []
    original_commit = controller._runtime_store.commit_ledger_uow

    def observe_commit(**kwargs: Any) -> dict[str, Any]:
        opening_at_commit.append(
            controller._state["runtime"]["opening_allowed"]
        )
        return original_commit(**kwargs)

    controller._runtime_store.commit_ledger_uow = observe_commit

    status = controller.start(_valid_start_payload())

    assert opening_at_commit == [False, False]
    assert status["ledger_reconciliation"]["status"] == "reconciled"
    assert status["ledger_reconciliation"][
        "current_state_exchange_snapshot_match"
    ] is True
    assert status["ledger_reconciliation"]["position_count"] == 0
    assert status["ledger_reconciliation"]["pending_order_count"] == 0
    assert status["ledger_reconciliation"]["fill_count"] == 0
    assert status["ledger_reconciliation"]["funding_bill_count"] == 0
    assert status["ledger_reconciliation"][
        "funding_cashflow_reconciled"
    ] is True
    assert status["runtime"]["opening_allowed"] is True
    assert client.order_calls == []
    assert client.cancel_calls == []


def test_start_ledger_mismatch_is_blocked_without_order_or_cancel(
    tmp_path: Path,
) -> None:
    FakePrivateWS.instances.clear()
    client = SnapshotClient()
    clock = lambda: datetime(1970, 1, 1, 0, 0, 0, 1000, tzinfo=timezone.utc)
    controller = OkxDemoPaperRuntimeController(
        config=OkxDemoPaperRuntimeConfig(
            repo_root=Path.cwd(),
            data_db_path=tmp_path / "unused.sqlite",
            output_dir=tmp_path / "output" / "btc_demo_paper_runtime",
        ),
        credential_loader=lambda _: _credentials(),
        client_factory=lambda _config, _credentials_value: client,
        private_ws_factory=FakePrivateWS,
        clock=clock,
        start_worker=False,
    )
    controller._signal_decision = lambda _strategy, **_kwargs: {
        "signal": "flat",
        "target_contracts": "0",
        "decision_bar_close_utc": clock().isoformat(),
    }
    original_apply = controller._apply_snapshot

    def apply_with_mismatch(snapshot: Mapping[str, Any]) -> None:
        original_apply(snapshot)
        controller._state["exchange"]["fills"] = [{"fill_id": "unexpected"}]

    controller._apply_snapshot = apply_with_mismatch

    with pytest.raises(
        OkxDemoPaperRuntimeError,
        match="current_state_exchange_snapshot_mismatch",
    ):
        controller.start(_valid_start_payload())

    status = controller.status()
    assert status["ledger_reconciliation"]["status"] == "mismatch"
    assert status["runtime"]["active"] is False
    assert status["runtime"]["opening_allowed"] is False
    assert status["runtime"]["cancel_only"] is True
    assert FakePrivateWS.instances == []
    assert client.order_calls == []
    assert client.cancel_calls == []
    assert controller._fault_drill_lock_handle is None


def test_start_ledger_persistence_failure_preserves_previous_evidence_and_blocks(
    tmp_path: Path,
) -> None:
    client = SnapshotClient()
    clock = lambda: datetime(1970, 1, 1, 0, 0, 0, 1000, tzinfo=timezone.utc)
    controller = OkxDemoPaperRuntimeController(
        config=OkxDemoPaperRuntimeConfig(
            repo_root=Path.cwd(),
            data_db_path=tmp_path / "unused.sqlite",
            output_dir=tmp_path / "output" / "btc_demo_paper_runtime",
        ),
        credential_loader=lambda _: _credentials(),
        client_factory=lambda _config, _credentials_value: client,
        private_ws_factory=FakePrivateWS,
        clock=clock,
        start_worker=False,
    )
    controller._signal_decision = lambda _strategy, **_kwargs: {
        "signal": "flat",
        "target_contracts": "0",
        "decision_bar_close_utc": clock().isoformat(),
    }
    previous = {
        **controller._state["ledger_reconciliation"],
        "status": "reconciled",
        "trigger": "manual_reconciliation",
        "current_state_exchange_snapshot_match": True,
        "exchange_snapshot_sha256": "previous-ledger-evidence",
    }
    controller._state["ledger_reconciliation"] = previous

    def fail_commit(**_kwargs: Any) -> dict[str, Any]:
        raise OSError("ledger_persistence_failed")

    controller._runtime_store.commit_ledger_uow = fail_commit

    with pytest.raises(OkxDemoPaperRuntimeError, match="ledger_persistence_failed"):
        controller.start(_valid_start_payload())

    status = controller.status()
    assert status["ledger_reconciliation"] == previous
    assert status["runtime"]["active"] is False
    assert status["runtime"]["opening_allowed"] is False
    assert status["runtime"]["cancel_only"] is True
    assert client.order_calls == []
    assert client.cancel_calls == []


def test_private_ws_startup_failure_retains_committed_ledger_but_blocks_opening(
    tmp_path: Path,
) -> None:
    client = SnapshotClient()
    clock = lambda: datetime(1970, 1, 1, 0, 0, 0, 1000, tzinfo=timezone.utc)

    class FailingPrivateWS(FakePrivateWS):
        def run_startup_reconnect_probe(self) -> dict[str, Any]:
            raise OkxDemoPaperRuntimeError("private_ws_probe_failed")

    controller = OkxDemoPaperRuntimeController(
        config=OkxDemoPaperRuntimeConfig(
            repo_root=Path.cwd(),
            data_db_path=tmp_path / "unused.sqlite",
            output_dir=tmp_path / "output" / "btc_demo_paper_runtime",
        ),
        credential_loader=lambda _: _credentials(),
        client_factory=lambda _config, _credentials_value: client,
        private_ws_factory=FailingPrivateWS,
        clock=clock,
        start_worker=False,
    )
    controller._signal_decision = lambda _strategy, **_kwargs: {
        "signal": "flat",
        "target_contracts": "0",
        "decision_bar_close_utc": clock().isoformat(),
    }

    with pytest.raises(OkxDemoPaperRuntimeError, match="private_ws_probe_failed"):
        controller.start(_valid_start_payload())

    status = controller.status()
    assert status["ledger_reconciliation"]["status"] == "reconciled"
    assert status["ledger_reconciliation"][
        "current_state_exchange_snapshot_match"
    ] is True
    assert status["runtime"]["active"] is False
    assert status["runtime"]["opening_allowed"] is False
    assert status["runtime"]["cancel_only"] is True
    assert status["runtime"]["probe_diagnostics"][0]["stage"] == "connect"
    assert (
        status["runtime"]["probe_diagnostics"][0]["exception_type"]
        == "OkxDemoPaperRuntimeError"
    )
    ledger_events = [
        json.loads(line)
        for line in (
            tmp_path / "output" / "btc_demo_paper_runtime" / "events.jsonl"
        ).read_text(encoding="utf-8").splitlines()
        if json.loads(line)["event_type"] == "ledger_uow_committed"
    ]
    assert len(ledger_events) == 1
    assert client.order_calls == []
    assert client.cancel_calls == []


def test_private_ws_probe_diagnostics_are_persisted_redacted_and_fail_closed(
    tmp_path: Path,
) -> None:
    FakePrivateWS.instances.clear()
    client = SnapshotClient()
    clock = lambda: datetime(1970, 1, 1, 0, 0, 0, 1000, tzinfo=timezone.utc)

    class FailingPrivateWS(FakePrivateWS):
        def run_startup_reconnect_probe(self) -> dict[str, Any]:
            return {
                "schema_version": "btc_okx_demo_private_ws_reconnect_probe_v1",
                "source_head": self.kwargs["source_head"],
                "runtime_version": self.kwargs["runtime_version"],
                "opening_allowed_after_reconciliation": False,
                "credentials_redacted": True,
                "blockers": ["btc_private_ws:unknown_fill"],
                "probe_diagnostics": [
                    {
                        "stage": "login",
                        "exception_type": "ProtocolError",
                        "message": (
                            "apiKey="
                            + "a" * 36
                            + " proxy=http://127.0.0.1:17309 accountId=acct-42"
                        ),
                        "protocol": {
                            "sCode": "60009",
                            "msg": (
                                "passphrase=Pass1234 "
                                "proxy=http://127.0.0.1:17309 accountId=acct-42"
                            ),
                        },
                        "subscription_progress": {
                            "observed_channels": [],
                            "expected_channels": [
                                "account",
                                "balance_and_position",
                                "orders",
                                "positions",
                            ],
                            "complete": False,
                        },
                    }
                ],
            }

    controller = OkxDemoPaperRuntimeController(
        config=OkxDemoPaperRuntimeConfig(
            repo_root=Path.cwd(),
            data_db_path=tmp_path / "unused.sqlite",
            output_dir=tmp_path / "output" / "btc_demo_paper_runtime",
        ),
        credential_loader=lambda _: _credentials(),
        client_factory=lambda _config, _credentials_value: client,
        private_ws_factory=FailingPrivateWS,
        clock=clock,
        start_worker=False,
    )
    controller._signal_decision = lambda _strategy, **_kwargs: {
        "signal": "flat",
        "target_contracts": "0",
        "decision_bar_close_utc": clock().isoformat(),
    }

    with pytest.raises(
        OkxDemoPaperRuntimeError,
        match="okx_demo_private_ws_startup_reconnect_probe_failed",
    ):
        controller.start(_valid_start_payload())

    status = controller.status()
    assert status["runtime"]["active"] is False
    assert status["runtime"]["opening_allowed"] is False
    assert status["runtime"]["cancel_only"] is True
    assert status["private_ws"]["probe_diagnostics"]
    detail = status["private_ws"]["probe_diagnostics"][0]
    assert detail["stage"] == "login"
    assert detail["exception_type"] == "ProtocolError"
    assert detail["protocol"]["sCode"] == "60009"
    assert detail["subscription_progress"]["complete"] is False
    assert detail["reconciliation_blocker_codes"] == [
        "btc_private_ws:unknown_fill"
    ]
    assert detail["reconciliation_blocker_categories"] == ["identity"]
    assert status["runtime"]["probe_diagnostics"] == status["private_ws"][
        "probe_diagnostics"
    ]

    event_rows = [
        json.loads(line)
        for line in (
            tmp_path / "output" / "btc_demo_paper_runtime" / "events.jsonl"
        ).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    blocked = [row for row in event_rows if row["event_type"] == "start_blocked"]
    assert len(blocked) == 1
    assert blocked[0]["payload"]["probe_diagnostics"][0]["stage"] == "login"
    assert blocked[0]["payload"]["probe_diagnostics"][0][
        "reconciliation_blocker_codes"
    ] == detail["reconciliation_blocker_codes"]
    assert blocked[0]["payload"]["probe_diagnostics"] == status["runtime"][
        "probe_diagnostics"
    ]
    encoded = json.dumps({"status": status, "events": event_rows}, sort_keys=True)
    for token in (
        "a" * 36,
        "b" * 32,
        "Pass1234",
        "http://127.0.0.1:17309",
        "127.0.0.1",
        "17309",
        "acct-42",
    ):
        assert token not in encoded
    assert client.order_calls == []
    assert client.cancel_calls == []
    assert client.dead_man_calls == []
    assert FakePrivateWS.instances[0].stopped is True


def test_private_ws_probe_wallclock_timeout_converges_runtime_fail_closed(
    tmp_path: Path,
) -> None:
    client = SnapshotClient()
    clock = lambda: datetime(1970, 1, 1, 0, 0, 0, 1000, tzinfo=timezone.utc)

    class WallclockTimedOutPrivateWS(FakePrivateWS):
        def run_startup_reconnect_probe(self) -> dict[str, Any]:
            return {
                "schema_version": "btc_okx_demo_private_ws_reconnect_probe_v1",
                "source_head": self.kwargs["source_head"],
                "runtime_version": self.kwargs["runtime_version"],
                "startup_reconciled": True,
                "disconnect_cancel_only_observed": True,
                "reconnect_login_observed": False,
                "reconnect_resubscribed": False,
                "reconnect_rest_reconciled": False,
                "probe_generation": 2,
                "opening_allowed_after_reconciliation": False,
                "blockers": [
                    "btc_okx_demo_private_ws:probe_wallclock_timeout"
                ],
                "credentials_redacted": True,
                "probe_diagnostics": [
                    {
                        "stage": "reconnect",
                        "exception_type": "ProbeWallClockTimeout",
                        "message": "okx_demo_private_ws_probe_wallclock_timeout",
                        "protocol": {"sCode": "", "msg": ""},
                        "subscription_progress": {
                            "observed_channels": ["orders"],
                            "expected_channels": [
                                "account",
                                "balance_and_position",
                                "orders",
                                "positions",
                            ],
                            "complete": False,
                        },
                    }
                ],
            }

    controller = OkxDemoPaperRuntimeController(
        config=OkxDemoPaperRuntimeConfig(
            repo_root=Path.cwd(),
            data_db_path=tmp_path / "unused.sqlite",
            output_dir=tmp_path / "output" / "btc_demo_paper_runtime",
        ),
        credential_loader=lambda _: _credentials(),
        client_factory=lambda _config, _credentials_value: client,
        private_ws_factory=WallclockTimedOutPrivateWS,
        clock=clock,
        start_worker=False,
    )
    controller._signal_decision = lambda _strategy, **_kwargs: {
        "signal": "flat",
        "target_contracts": "0",
        "decision_bar_close_utc": clock().isoformat(),
    }

    with pytest.raises(
        OkxDemoPaperRuntimeError,
        match="okx_demo_private_ws_startup_reconnect_probe_failed",
    ):
        controller.start(_valid_start_payload())

    status = controller.status()
    assert status["runtime"]["active"] is False
    assert status["runtime"]["opening_allowed"] is False
    assert status["runtime"]["cancel_only"] is True
    assert status["risk_control"]["mode"] == "FROZEN_UNKNOWN"
    assert status["runtime"]["probe_diagnostics"][0]["stage"] == "reconnect"
    assert status["safety"]["formal_paper_runtime_started"] is False
    assert status["safety"]["live_order_allowed"] is False
    assert status["safety"]["real_money_order_allowed"] is False
    assert status["safety"]["transfer_allowed"] is False
    assert status["safety"]["withdraw_allowed"] is False
    assert client.order_calls == []
    assert client.cancel_calls == []
    assert client.dead_man_calls == []


def test_runtime_projects_only_allowlisted_reconciliation_blocker_evidence() -> None:
    projected = okx_demo_runtime_module._project_probe_diagnostics(
        [
            {
                "stage": "startup_snapshot",
                "exception_type": "ReconciliationBlocked",
                "message": "accountId=acct-42 proxy=http://127.0.0.1:17309",
                "reconciliation_blocker_codes": [
                    "btc_private_ws:unknown_fill",
                    "foreign-client-id=should-not-persist",
                ],
                "identity_projection": {
                    "leaked_order_id": "foreign-order-id",
                },
            }
        ]
    )

    assert len(projected) == 1
    detail = projected[0]
    assert detail["reconciliation_blocker_codes"] == [
        "btc_private_ws:unknown_fill",
        "unknown_reconciliation_blocker",
    ]
    assert detail["reconciliation_blocker_categories"] == [
        "identity",
        "unknown",
    ]
    assert detail["reconciliation_blocker_count"] == 2
    assert len(detail["reconciliation_blocker_set_sha256"]) == 64
    assert set(detail["identity_projection"]) == {
        "account_blocker_present",
        "blocker_code_count",
        "identity_blocker_present",
        "snapshot_blocker_present",
        "transport_blocker_present",
        "unknown_blocker_present",
    }
    encoded = json.dumps(detail, sort_keys=True)
    for token in (
        "acct-42",
        "127.0.0.1",
        "17309",
        "foreign-client-id",
        "foreign-order-id",
    ):
        assert token not in encoded


def test_private_ws_factory_failure_redacts_exception_status_blocker_and_event(
    tmp_path: Path,
) -> None:
    factory_calls: list[dict[str, Any]] = []
    client = SnapshotClient()

    def leaky_private_ws_factory(**kwargs: Any) -> Any:
        factory_calls.append(dict(kwargs))
        raise RuntimeError(
            json.dumps(
                {
                    "apiKey": "REDACTED_CREDENTIAL_LITERAL",
                    "secretKey": "REDACTED_CREDENTIAL_LITERAL",
                    "passphrase": "REDACTED_CREDENTIAL_LITERAL",
                    "accountId": "FACTORY_ACCOUNT_SENTINEL",
                    "proxy": {
                        "url": "http://proxy.sentinel:17309",
                        "host": "proxy.sentinel",
                        "port": 17309,
                    },
                    "sCode": "FACTORY_SCODE_SENTINEL",
                }
            )
        )

    controller, _ = _startup_controller_with_private_ws(
        tmp_path,
        leaky_private_ws_factory,  # type: ignore[arg-type]
    )

    with pytest.raises(OkxDemoPaperRuntimeError) as raised:
        controller.start(_valid_start_payload())

    status = controller.status()
    event_rows = [
        json.loads(line)
        for line in (
            tmp_path / "output" / "btc_demo_paper_runtime" / "events.jsonl"
        ).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    encoded = json.dumps(
        {
            "raised": str(raised.value),
            "status": status,
            "events": event_rows,
        },
        sort_keys=True,
    )
    for sentinel in (
        "FACTORY_API_SENTINEL",
        "FACTORY_SECRET_SENTINEL",
        "FACTORY_PASS_SENTINEL",
        "FACTORY_ACCOUNT_SENTINEL",
        "proxy.sentinel",
        "17309",
        "FACTORY_SCODE_SENTINEL",
    ):
        assert sentinel not in encoded
    assert status["runtime"]["opening_allowed"] is False
    assert status["runtime"]["cancel_only"] is True
    assert status["runtime"]["last_error"]
    assert status["runtime"]["blockers"]
    assert status["runtime"]["probe_diagnostics"][0]["stage"] == "connect"
    assert status["runtime"]["probe_diagnostics"][0]["message"]
    blocked_events = [
        row for row in event_rows if row["event_type"] == "start_blocked"
    ]
    assert len(blocked_events) == 1
    assert blocked_events[0]["payload"]["error"]
    assert client.order_calls == []
    assert client.cancel_calls == []
    assert client.dead_man_calls == []
    assert len(factory_calls) == 1


def test_probe_projection_redacts_unknown_scode_and_subscription_channels(
    tmp_path: Path,
) -> None:
    client = SnapshotClient()

    class UnknownProtocolPrivateWS(FakePrivateWS):
        def run_startup_reconnect_probe(self) -> dict[str, Any]:
            return {
                "schema_version": "btc_okx_demo_private_ws_reconnect_probe_v1",
                "source_head": self.kwargs["source_head"],
                "runtime_version": self.kwargs["runtime_version"],
                "opening_allowed_after_reconciliation": False,
                "credentials_redacted": True,
                "probe_diagnostics": [
                    {
                        "stage": "subscribe",
                        "exception_type": "ProtocolError",
                        "message": (
                            "sCode=UNKNOWN_SCODE_SENTINEL "
                            "channel=UNKNOWN_CHANNEL_SENTINEL"
                        ),
                        "protocol": {
                            "sCode": "UNKNOWN_SCODE_SENTINEL",
                            "msg": "UNKNOWN_SCODE_SENTINEL",
                        },
                        "subscription_progress": {
                            "observed_channels": [
                                "orders",
                                "UNKNOWN_CHANNEL_SENTINEL",
                            ],
                            "expected_channels": [
                                "positions",
                                "UNKNOWN_CHANNEL_SENTINEL",
                            ],
                            "complete": False,
                        },
                    }
                ],
            }

    controller = OkxDemoPaperRuntimeController(
        config=OkxDemoPaperRuntimeConfig(
            repo_root=Path.cwd(),
            data_db_path=tmp_path / "unused.sqlite",
            output_dir=tmp_path / "output" / "btc_demo_paper_runtime",
        ),
        credential_loader=lambda _: _credentials(),
        client_factory=lambda _config, _credentials_value: client,
        private_ws_factory=UnknownProtocolPrivateWS,
        clock=lambda: datetime(
            1970, 1, 1, 0, 0, 0, 1000, tzinfo=timezone.utc
        ),
        start_worker=False,
    )
    controller._signal_decision = lambda _strategy, **_kwargs: {
        "signal": "flat",
        "target_contracts": "0",
        "decision_bar_close_utc": datetime.now(timezone.utc).isoformat(),
    }

    with pytest.raises(
        OkxDemoPaperRuntimeError,
        match="okx_demo_private_ws_startup_reconnect_probe_failed",
    ):
        controller.start(_valid_start_payload())

    status = controller.status()
    event_rows = [
        json.loads(line)
        for line in (
            tmp_path / "output" / "btc_demo_paper_runtime" / "events.jsonl"
        ).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    encoded = json.dumps({"status": status, "events": event_rows}, sort_keys=True)
    assert "UNKNOWN_SCODE_SENTINEL" not in encoded
    assert "UNKNOWN_CHANNEL_SENTINEL" not in encoded
    detail = status["private_ws"]["probe_diagnostics"][0]
    assert detail["protocol"]["sCode"] == "<redacted-code>"
    assert detail["subscription_progress"]["observed_channels"] == [
        "<redacted-channel>",
        "orders",
    ]
    assert detail["subscription_progress"]["expected_channels"] == [
        "<redacted-channel>",
        "positions",
    ]
    assert status["runtime"]["opening_allowed"] is False
    assert status["runtime"]["cancel_only"] is True
    assert client.order_calls == []
    assert client.cancel_calls == []
    assert client.dead_man_calls == []


def test_demo_start_safety_flags_never_enable_live_money_or_asset_movement(
    tmp_path: Path,
) -> None:
    FakePrivateWS.instances.clear()
    client = SnapshotClient()
    clock = lambda: datetime(1970, 1, 1, 0, 0, 0, 1000, tzinfo=timezone.utc)
    controller = OkxDemoPaperRuntimeController(
        config=OkxDemoPaperRuntimeConfig(
            repo_root=Path.cwd(),
            data_db_path=tmp_path / "unused.sqlite",
            output_dir=tmp_path / "output" / "btc_demo_paper_runtime",
        ),
        credential_loader=lambda _: _credentials(),
        client_factory=lambda _config, _credentials_value: client,
        private_ws_factory=FakePrivateWS,
        clock=clock,
        start_worker=False,
    )
    controller._signal_decision = lambda _strategy, **_kwargs: {
        "signal": "flat",
        "target_contracts": "0",
        "decision_bar_close_utc": clock().isoformat(),
    }

    status = controller.start(_valid_start_payload())

    for flag in (
        "live_order_allowed",
        "real_money_order_allowed",
        "transfer_allowed",
        "withdraw_allowed",
        "permission_upgrade_allowed",
    ):
        assert status["safety"][flag] is False


def test_start_requires_explicit_hash_bound_server_side_protection_policy(
    tmp_path: Path,
) -> None:
    credential_calls: list[str] = []
    controller = _controller(
        tmp_path,
        lambda service: credential_calls.append(service) or _credentials(),
    )
    payload = _valid_start_payload()
    payload.pop("server_side_protection_policy")

    with pytest.raises(
        OkxDemoPaperRuntimeError,
        match="okx_demo_server_side_protection_policy_missing",
    ):
        controller.start(payload)

    assert credential_calls == []


def test_start_rejects_self_hashed_but_not_risk_approved_protection_policy(
    tmp_path: Path,
) -> None:
    controller = _controller(tmp_path, lambda _: _credentials())
    payload = _valid_start_payload()
    canonical = {
        **{
            key: value
            for key, value in _protection_policy().items()
            if key != "policy_sha256"
        },
        "sl_distance_bps": "150",
    }
    payload["server_side_protection_policy"] = {
        **canonical,
        "policy_sha256": hashlib.sha256(
            json.dumps(
                canonical,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest(),
    }

    with pytest.raises(
        OkxDemoPaperRuntimeError,
        match="okx_demo_server_side_protection_policy_not_approved",
    ):
        controller.start(payload)


@pytest.mark.parametrize("intent_status", ("accepted", "reconciled_open"))
def test_start_rejects_every_nonterminal_exchange_intent_before_credentials(
    tmp_path: Path,
    intent_status: str,
) -> None:
    credential_calls: list[str] = []
    controller = _controller(
        tmp_path,
        lambda service: credential_calls.append(service) or _credentials(),
    )
    controller._state["risk_control"]["pending_order_intents"] = {
        "btcDPopen0001": {
            "client_order_id": "btcDPopen0001",
            "status": intent_status,
            "retry_without_query_allowed": False,
        }
    }

    with pytest.raises(
        OkxDemoPaperRuntimeError,
        match=(
            "okx_demo_previous_ambiguous_order_requires_"
            "clordid_reconciliation"
        ),
    ):
        controller.start(_valid_start_payload())

    assert credential_calls == []


@pytest.mark.parametrize("intent_status", ("accepted", "reconciled_open"))
def test_restart_recovers_every_nonterminal_exchange_intent_fail_closed(
    tmp_path: Path,
    intent_status: str,
) -> None:
    first = _controller(tmp_path, lambda _: _credentials())
    first._state["risk_control"]["pending_order_intents"] = {
        "btcDPrestart001": {
            "client_order_id": "btcDPrestart001",
            "status": intent_status,
            "retry_without_query_allowed": False,
        }
    }
    first._persist_state()

    recovered = _controller(tmp_path, lambda _: _credentials())
    runtime = recovered.status()["runtime"]

    assert runtime["status"] == "unclean_restart_fail_closed"
    assert runtime["opening_allowed"] is False
    assert runtime["cancel_only"] is True
    assert (
        "okx_demo_previous_ambiguous_order_requires_clordid_reconciliation"
        in runtime["blockers"]
    )


@pytest.mark.parametrize("intent_status", ("accepted", "reconciled_open"))
def test_reconcile_nonterminal_exchange_intent_to_terminal_state(
    tmp_path: Path,
    intent_status: str,
) -> None:
    controller = _controller(tmp_path, lambda _: _credentials())
    client_order_id = "btcDPopen0002"
    controller._state["risk_control"]["pending_order_intents"] = {
        client_order_id: {
            "client_order_id": client_order_id,
            "status": intent_status,
            "retry_without_query_allowed": False,
        }
    }

    class TerminalOrderClient:
        def private_get(
            self,
            path: str,
            params: Mapping[str, Any] | None = None,
        ) -> OkxDemoResponse:
            assert path == "/api/v5/trade/order"
            assert params == {
                "instId": "BTC-USDT-SWAP",
                "clOrdId": client_order_id,
            }
            return OkxDemoResponse(
                method="GET",
                path=path,
                http_status=200,
                code="0",
                message="",
                data=(
                    {
                        "clOrdId": client_order_id,
                        "ordId": "order-terminal-1",
                        "state": "canceled",
                        "accFillSz": "0",
                    },
                ),
            )

    blockers = controller._reconcile_ambiguous_order_intents(
        TerminalOrderClient(),  # type: ignore[arg-type]
        {
            "orders": [],
            "pending_orders": [],
            "fills": [],
            "positions": [],
        },
    )

    assert blockers == []
    pending = controller.status()["risk_control"]["pending_order_intents"]
    assert pending[client_order_id]["status"] == "reconciled_terminal"
    assert pending[client_order_id]["exchange_state"] == "canceled"


@pytest.mark.parametrize(
    ("intent_status", "expected_terminal"),
    (
        ("reconciled_terminal", True),
        ("unknown", False),
        ("accepted", False),
        ("reconciled_open", False),
    ),
)
def test_fault_drill_postflight_accepts_only_reconciled_terminal_as_new_terminal(
    tmp_path: Path,
    intent_status: str,
    expected_terminal: bool,
) -> None:
    """A query-reconciled terminal intent is safe; unresolved states are not."""

    controller = _controller(tmp_path, lambda _: _credentials())
    controller._state["risk_control"]["pending_order_intents"] = {
        "btcDPreconciled0001": {"status": intent_status}
    }
    controller._state["ledger_reconciliation"] = {
        "status": "reconciled",
        "current_state_exchange_snapshot_match": True,
    }

    blockers = controller._fault_drill_postflight_blockers(
        {
            "positions": [],
            "pending_orders": [],
            "pending_algo_orders": [],
        }
    )

    assert (
        "okx_demo_fault_drill_postflight_intent_not_terminal" not in blockers
    ) is expected_terminal


def test_shared_fault_drill_terminal_projection_requires_unique_durable_truth(
    tmp_path: Path,
) -> None:
    controller = _controller(tmp_path, lambda _: _credentials())
    controller._state["risk_control"]["pending_order_intents"] = {
        "btcDPfailed0001": {"status": "terminal", "risk_reducing_only": False},
        "btcDPrecover0002": {
            "status": "reconciled_terminal",
            "risk_reducing_only": True,
        },
    }
    controller._state["risk_control"]["owned_attached_algos"] = {
        "btcDPfailed0001A": {
            "algo_client_order_id": "btcDPfailed0001A",
            "algo_id": "algo-incident-1",
            "parent_client_order_id": "btcDPfailed0001",
        }
    }
    controller._state["ledger_reconciliation"] = {
        "status": "reconciled",
        "current_state_exchange_snapshot_match": True,
    }
    controller._state["private_ws"] = {
        "connected": True,
        "listener_alive": True,
        "opening_allowed_after_reconciliation": True,
    }
    snapshot = _incident_recovery_snapshot()
    snapshot["positions"] = []
    snapshot["pending_algo_orders"] = []
    snapshot["orders"].append(
        {
            "order_id": "close-order-1",
            "client_order_id": "btcDPrecover0002",
            "instrument_id": "BTC-USDT-SWAP",
            "side": "sell",
            "position_side": "long",
            "order_type": "ioc",
            "size": "0.01",
            "state": "filled",
        }
    )
    snapshot["fills"].append(
        {
            "fill_id": "close-fill-1",
            "order_id": "close-order-1",
            "client_order_id": "btcDPrecover0002",
            "size": "0.01",
        }
    )

    projection = controller._fault_drill_terminal_projection(
        snapshot,
        opening_cl_ord_id="btcDPfailed0001",
        close_cl_ord_id="btcDPrecover0002",
        algo_cl_ord_id="btcDPfailed0001A",
    )

    assert projection["final_no_unresolved_intents"] is True
    assert projection["final_ledger_reconciled"] is True
    assert projection["final_private_ws_reconciled"] is True
    assert projection["entry_order_id"] == "opening-order-1"
    assert projection["close_order_id"] == "close-order-1"
    assert projection["close_fill_ids"] == ["close-fill-1"]
    assert projection["algo_id"] == "algo-incident-1"

    snapshot["fills"].append(dict(snapshot["fills"][-1]))
    ambiguous = controller._fault_drill_terminal_projection(
        snapshot,
        opening_cl_ord_id="btcDPfailed0001",
        close_cl_ord_id="btcDPrecover0002",
        algo_cl_ord_id="btcDPfailed0001A",
    )
    assert ambiguous["close_order_id"] == ""
    assert ambiguous["close_fill_ids"] == []


def test_reconcile_live_exchange_intent_remains_explicit_blocker(
    tmp_path: Path,
) -> None:
    controller = _controller(tmp_path, lambda _: _credentials())
    client_order_id = "btcDPopen0004"
    controller._state["risk_control"]["pending_order_intents"] = {
        client_order_id: {
            "client_order_id": client_order_id,
            "status": "accepted",
            "retry_without_query_allowed": False,
        }
    }

    class LiveOrderClient:
        def private_get(
            self,
            path: str,
            params: Mapping[str, Any] | None = None,
        ) -> OkxDemoResponse:
            del params
            return OkxDemoResponse(
                method="GET",
                path=path,
                http_status=200,
                code="0",
                message="",
                data=(
                    {
                        "clOrdId": client_order_id,
                        "ordId": "order-live-1",
                        "state": "live",
                        "accFillSz": "0",
                    },
                ),
            )

    blockers = controller._reconcile_ambiguous_order_intents(
        LiveOrderClient(),  # type: ignore[arg-type]
        {
            "orders": [],
            "pending_orders": [],
            "fills": [],
            "positions": [],
        },
    )

    assert blockers == [
        "okx_demo_ambiguous_order_still_open:btcDPopen0004:live"
    ]
    pending = controller.status()["risk_control"]["pending_order_intents"]
    assert pending[client_order_id]["status"] == "reconciled_open"


def test_submit_timeout_queries_by_durable_clordid_and_never_reposts(
    tmp_path: Path,
) -> None:
    controller, snapshot, order_plan = _p0_order_controller(tmp_path)
    client = OrderScenarioClient(
        submit_exception=OkxDemoTransportError("response_lost"),
    )
    checkpoint_path = (
        tmp_path / "output" / "btc_demo_paper_runtime" / "state.json"
    )

    def assert_durable_before_post(order: Mapping[str, Any]) -> None:
        checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        pending = checkpoint["state"]["risk_control"]["pending_order_intents"]
        assert pending[order["clOrdId"]]["status"] == "submit_pending"
        assert pending[order["clOrdId"]]["persisted_before_post"] is True

    client.before_submit = assert_durable_before_post
    _install_order_followup(controller, client, order_plan)

    controller._submit_order_plan(
        client,  # type: ignore[arg-type]
        snapshot=snapshot,
        decision=_p0_order_decision(),
        order_plan=order_plan,
    )

    assert len(client.submit_calls) == 1
    clordid = order_plan["client_order_id"]
    order_queries = [
        call
        for call in client.private_calls
        if call["path"] == "/api/v5/trade/order"
    ]
    assert order_queries
    assert all(call["params"]["clOrdId"] == clordid for call in order_queries)
    pending = controller.status()["risk_control"]["pending_order_intents"]
    assert pending[clordid]["status"] == "terminal"
    assert controller.status()["risk_control"]["active_protection"]["status"] == (
        "exchange_accepted"
    )


def test_backend_composed_dispatcher_executes_only_after_current_facts_and_permit(
    tmp_path: Path,
) -> None:
    """The backend-owned dispatcher, not OMS, owns proof issuance."""

    class DemoAdapter:
        def capability_for(self, *, action, transport_context):
            assert action is RuntimeAction.SUBMIT_NEW_ORDER
            assert transport_context == "demo-client"
            return BTCEndpointCapability(
                mode=BTCExecutionMode.DEMO,
                transport_enabled=True,
                submit_new_order=True,
                cancel_order=True,
                reduce_only=True,
                attach_protection=True,
                dead_man=True,
                private_endpoint_allowed=True,
                order_endpoint_allowed=True,
            )

    source_head = "a" * 40
    dispatcher = BTCDemoExecutionDispatcher(
        expected_source_head=source_head,
        state_directory=tmp_path / "btc-demo-boundary",
        capability_adapter=DemoAdapter(),
        credential_service="quant-system.okx-demo.trade",
    )
    intent = OrderIntent(
        timestamp_utc=datetime.now(timezone.utc),
        strategy_id="demo-boundary",
        symbol="BTC-USDT-SWAP",
        side=OrderSide.BUY,
        quantity=0.01,
        order_type=OrderType.LIMIT,
        limit_price=60000.0,
        client_order_id="btcDP012345670001",
    )
    risk = RiskDecision(
        approved=True,
        reason="current-demo-risk",
        order_intent_id=intent.order_intent_id,
        threshold=10.0,
    )
    facts = BTCExecutionDispatchFacts(
        exchange_snapshot={
            "captured_at_utc": datetime.now(timezone.utc).isoformat(),
            "account": {
                "account_level": "2",
                "position_mode": "long_short_mode",
                "permissions": ["trade"],
            },
            "instrument": {"contract_value_btc": "0.01"},
            "ticker": {"bid": "60000", "ask": "60000.1"},
            "book": {"bids": [["60000", "1"]], "asks": [["60000.1", "1"]]},
        },
        private_ws={
            "connected": True,
            "listener_alive": True,
            "opening_allowed_after_reconciliation": True,
        },
        ledger_reconciliation={
            "status": "reconciled",
            "current_state_exchange_snapshot_match": True,
            "funding_cashflow_reconciled": True,
        },
        credential_service="quant-system.okx-demo.trade",
        runtime_run_id="0123456789abcdef",
        source_head=source_head,
        epoch=1,
        runtime_active=True,
        opening_allowed=True,
        cancel_only=False,
        risk_mode="RUNNING",
        attached_protection={
            "attachAlgoClOrdId": f"{intent.client_order_id}A",
            "tpTriggerPx": "61200",
            "tpOrdPx": "-1",
            "tpTriggerPxType": "mark",
            "slTriggerPx": "59400",
            "slOrdPx": "-1",
            "slTriggerPxType": "mark",
            "policy": {"policy_id": "exact"},
        },
    )
    calls: list[str] = []

    result = dispatcher.dispatch(
        action=RuntimeAction.SUBMIT_NEW_ORDER,
        order_intent=intent,
        risk_decision=risk,
        facts=facts,
        transport_context="demo-client",
        callback=lambda submitted: calls.append(submitted.client_order_id)
        or {"status": "accepted"},
    )

    assert result.decision.allowed is True
    assert result.transport_called is True
    assert calls == [intent.client_order_id]

    sealed_observation = datetime(2020, 1, 1, tzinfo=timezone.utc)
    sealed_intent = OrderIntent(
        timestamp_utc=sealed_observation,
        strategy_id=intent.strategy_id,
        symbol=intent.symbol,
        side=intent.side,
        quantity=intent.quantity,
        order_type=intent.order_type,
        limit_price=intent.limit_price,
        client_order_id="btcDPsealedclock01",
    )
    sealed_risk = replace(
        risk,
        order_intent_id=sealed_intent.order_intent_id,
    )
    sealed_snapshot = dict(facts.exchange_snapshot)
    sealed_snapshot["captured_at_utc"] = sealed_observation.isoformat()
    sealed_facts = replace(
        facts,
        exchange_snapshot=sealed_snapshot,
        attached_protection={
            **facts.attached_protection,
            "attachAlgoClOrdId": f"{sealed_intent.client_order_id}A",
        },
    )
    sealed_calls: list[str] = []
    sealed_result = BTCDemoExecutionDispatcher(
        expected_source_head=source_head,
        state_directory=tmp_path / "sealed-observation-boundary",
        capability_adapter=DemoAdapter(),
        credential_service="quant-system.okx-demo.trade",
        clock=lambda: sealed_observation,
    ).dispatch(
        action=RuntimeAction.SUBMIT_NEW_ORDER,
        order_intent=sealed_intent,
        risk_decision=sealed_risk,
        facts=sealed_facts,
        transport_context="demo-client",
        callback=lambda submitted: sealed_calls.append(submitted.client_order_id)
        or {"status": "accepted"},
    )
    assert sealed_result.decision.allowed is True
    assert sealed_calls == [sealed_intent.client_order_id]

    expired_calls: list[str] = []
    with pytest.raises(Exception, match="btc_demo_dispatch_projection_blocked"):
        BTCDemoExecutionDispatcher(
            expected_source_head=source_head,
            state_directory=tmp_path / "expired-observation-boundary",
            capability_adapter=DemoAdapter(),
            credential_service="quant-system.okx-demo.trade",
            clock=lambda: sealed_observation + timedelta(seconds=31),
        ).dispatch(
            action=RuntimeAction.SUBMIT_NEW_ORDER,
            order_intent=sealed_intent,
            risk_decision=sealed_risk,
            facts=sealed_facts,
            transport_context="demo-client",
            callback=lambda submitted: expired_calls.append(
                submitted.client_order_id
            ),
        )
    assert expired_calls == []


def test_backend_dispatcher_projects_verified_reduce_only_without_unlocking_new_risk(
    tmp_path: Path,
) -> None:
    """A verified reduction is distinct from a real exchange cancel-only state."""

    class DemoAdapter:
        def capability_for(self, *, action, transport_context):
            assert transport_context == "demo-client"
            return BTCEndpointCapability(
                mode=BTCExecutionMode.DEMO,
                transport_enabled=True,
                submit_new_order=True,
                cancel_order=True,
                reduce_only=True,
                attach_protection=True,
                dead_man=True,
                private_endpoint_allowed=True,
                order_endpoint_allowed=True,
            )

    source_head = "a" * 40
    captured_at = datetime.now(timezone.utc)

    def intent(client_order_id: str) -> OrderIntent:
        return OrderIntent(
            timestamp_utc=captured_at,
            strategy_id="demo-boundary-reduction",
            symbol="BTC-USDT-SWAP",
            side=OrderSide.SELL,
            quantity=0.01,
            order_type=OrderType.LIMIT,
            limit_price=60000.0,
            client_order_id=client_order_id,
        )

    reduction_facts = BTCExecutionDispatchFacts(
        exchange_snapshot={
            "captured_at_utc": captured_at.isoformat(),
            "account": {
                "account_level": "2",
                "position_mode": "long_short_mode",
                "permissions": ["trade"],
            },
            "instrument": {"contract_value_btc": "0.01"},
            "ticker": {"bid": "60000", "ask": "60000.1"},
            "book": {
                "bids": [["60000", "1"]],
                "asks": [["60000.1", "1"]],
            },
        },
        private_ws={
            "connected": True,
            "listener_alive": True,
            "opening_allowed_after_reconciliation": True,
        },
        ledger_reconciliation={
            "status": "reconciled",
            "current_state_exchange_snapshot_match": True,
            "funding_cashflow_reconciled": True,
        },
        credential_service="quant-system.okx-demo.trade",
        runtime_run_id="verified-reduction-01",
        source_head=source_head,
        epoch=3,
        runtime_active=True,
        opening_allowed=False,
        cancel_only=False,
        risk_mode="RISK_REDUCING",
    )
    reduce_intent = intent("btcDPreduceonly001")
    reduce_risk = RiskDecision(
        approved=True,
        reason="verified-reduction",
        order_intent_id=reduce_intent.order_intent_id,
        threshold=10.0,
    )
    calls: list[str] = []
    dispatcher = BTCDemoExecutionDispatcher(
        expected_source_head=source_head,
        state_directory=tmp_path / "verified-reduction",
        capability_adapter=DemoAdapter(),
        credential_service="quant-system.okx-demo.trade",
    )

    result = dispatcher.dispatch(
        action=RuntimeAction.REDUCE_ONLY,
        order_intent=reduce_intent,
        risk_decision=reduce_risk,
        facts=reduction_facts,
        transport_context="demo-client",
        callback=lambda submitted: calls.append(submitted.client_order_id)
        or {"status": "accepted"},
    )

    assert result.decision.allowed is True
    assert result.transport_called is True
    assert calls == [reduce_intent.client_order_id]

    new_risk_intent = intent("btcDPnewriskblock01")
    with pytest.raises(
        Exception,
        match="btc_demo_dispatch_opening_runtime_not_permitted",
    ):
        BTCDemoExecutionDispatcher(
            expected_source_head=source_head,
            state_directory=tmp_path / "new-risk-blocked",
            capability_adapter=DemoAdapter(),
            credential_service="quant-system.okx-demo.trade",
        ).dispatch(
            action=RuntimeAction.SUBMIT_NEW_ORDER,
            order_intent=new_risk_intent,
            risk_decision=RiskDecision(
                approved=True,
                reason="new-risk-must-stay-blocked",
                order_intent_id=new_risk_intent.order_intent_id,
                threshold=10.0,
            ),
            facts=reduction_facts,
            transport_context="demo-client",
            callback=lambda _submitted: pytest.fail(
                "reduction-only state reached new-risk transport"
            ),
        )

    cancel_only_facts = replace(
        reduction_facts,
        cancel_only=True,
        risk_mode="FROZEN_UNKNOWN",
    )
    for action, client_order_id in (
        (RuntimeAction.CANCEL_ORDER, "btcDPcancelkeep001"),
        (RuntimeAction.DEAD_MAN, "btcDPdeadmankeep01"),
    ):
        protective_intent = intent(client_order_id)
        protective_calls: list[str] = []
        protective_result = BTCDemoExecutionDispatcher(
            expected_source_head=source_head,
            state_directory=tmp_path / f"protective-{action.value}",
            capability_adapter=DemoAdapter(),
            credential_service="quant-system.okx-demo.trade",
        ).dispatch(
            action=action,
            order_intent=protective_intent,
            risk_decision=RiskDecision(
                approved=True,
                reason="existing-protective-action",
                order_intent_id=protective_intent.order_intent_id,
                threshold=10.0,
            ),
            facts=cancel_only_facts,
            transport_context="demo-client",
            callback=lambda submitted: protective_calls.append(
                submitted.client_order_id
            )
            or {"status": "accepted"},
        )
        assert protective_result.decision.allowed is True
        assert protective_result.transport_called is True
        assert protective_calls == [protective_intent.client_order_id]


@pytest.mark.parametrize(
    ("mutation", "expected"),
    (
        ("cancel_only", "projection_blocked"),
        ("frozen", "projection_blocked"),
        ("startup", "projection_blocked"),
        ("private_ws", "projection_blocked"),
        ("ledger", "projection_blocked"),
        ("account", "projection_blocked"),
        ("withdraw", "projection_blocked"),
        ("stale", "projection_blocked"),
        ("capability", "projection_blocked"),
    ),
)
def test_backend_dispatcher_reduce_only_preserves_authority_blockers(
    tmp_path: Path,
    mutation: str,
    expected: str,
) -> None:
    current = datetime.now(timezone.utc)

    class DemoAdapter:
        def capability_for(self, **_kwargs):
            return BTCEndpointCapability(
                mode=BTCExecutionMode.DEMO,
                transport_enabled=True,
                reduce_only=mutation != "capability",
                private_endpoint_allowed=True,
                order_endpoint_allowed=True,
            )

    snapshot = {
        "captured_at_utc": current.isoformat(),
        "account": {
            "account_level": "2",
            "position_mode": "long_short_mode",
            "permissions": ["trade"],
        },
        "instrument": {"contract_value_btc": "0.01"},
        "ticker": {"bid": "60000", "ask": "60000.1"},
        "book": {"bids": [["60000", "1"]], "asks": [["60000.1", "1"]]},
    }
    facts = BTCExecutionDispatchFacts(
        exchange_snapshot=snapshot,
        private_ws={
            "connected": True,
            "listener_alive": True,
            "opening_allowed_after_reconciliation": True,
        },
        ledger_reconciliation={
            "status": "reconciled",
            "current_state_exchange_snapshot_match": True,
            "funding_cashflow_reconciled": True,
        },
        credential_service="quant-system.okx-demo.trade",
        runtime_run_id=f"reduce-block-{mutation}",
        source_head="a" * 40,
        epoch=4,
        runtime_active=True,
        opening_allowed=False,
        cancel_only=False,
        risk_mode="RISK_REDUCING",
    )
    if mutation == "cancel_only":
        facts = replace(facts, cancel_only=True)
    elif mutation == "frozen":
        facts = replace(facts, risk_mode="FROZEN_UNKNOWN")
    elif mutation == "startup":
        # Contradictory opening_allowed input must not let a STARTUP reduction
        # fall through to the generic healthy-opening projection.
        facts = replace(
            facts,
            risk_mode="STARTUP_RECONCILING",
            opening_allowed=True,
        )
    elif mutation == "private_ws":
        facts = replace(facts, private_ws={})
    elif mutation == "ledger":
        facts = replace(facts, ledger_reconciliation={})
    elif mutation == "account":
        changed = dict(snapshot)
        changed["account"] = {
            "account_level": "2",
            "position_mode": "long_short_mode",
            "permissions": ["read_only"],
        }
        facts = replace(facts, exchange_snapshot=changed)
    elif mutation == "withdraw":
        changed = dict(snapshot)
        changed["account"] = {
            "account_level": "2",
            "position_mode": "long_short_mode",
            "permissions": ["trade", "withdraw"],
        }
        facts = replace(facts, exchange_snapshot=changed)
    elif mutation == "stale":
        changed = dict(snapshot)
        changed["captured_at_utc"] = (current - timedelta(seconds=121)).isoformat()
        facts = replace(facts, exchange_snapshot=changed)

    blocked_intent = OrderIntent(
        timestamp_utc=current,
        strategy_id="demo-boundary-reduction",
        symbol="BTC-USDT-SWAP",
        side=OrderSide.SELL,
        quantity=0.01,
        order_type=OrderType.LIMIT,
        limit_price=60000.0,
        client_order_id=f"btcDPblock{hashlib.sha256(mutation.encode()).hexdigest()[:10]}",
    )
    dispatcher = BTCDemoExecutionDispatcher(
        expected_source_head="a" * 40,
        state_directory=tmp_path / mutation,
        capability_adapter=DemoAdapter(),
        credential_service="quant-system.okx-demo.trade",
    )

    def dispatch():
        return dispatcher.dispatch(
            action=RuntimeAction.REDUCE_ONLY,
            order_intent=blocked_intent,
            risk_decision=RiskDecision(
                approved=True,
                reason="blocked-reduction-authority",
                order_intent_id=blocked_intent.order_intent_id,
                threshold=10.0,
            ),
            facts=facts,
            transport_context="demo-client",
            callback=lambda _submitted: pytest.fail(
                "blocked reduction reached transport"
            ),
        )
    with pytest.raises(Exception, match=expected):
        dispatch()


def test_backend_composed_dispatcher_isolates_lifecycle_by_demo_namespace(
    tmp_path: Path,
) -> None:
    """A persistent dispatcher must not cross prior clOrdId namespaces."""

    class DemoAdapter:
        def capability_for(self, *, action, transport_context):
            assert action is RuntimeAction.DEAD_MAN
            assert transport_context == "demo-client"
            return BTCEndpointCapability(
                mode=BTCExecutionMode.DEMO,
                transport_enabled=True,
                submit_new_order=True,
                cancel_order=True,
                reduce_only=True,
                attach_protection=True,
                dead_man=True,
                private_endpoint_allowed=True,
                order_endpoint_allowed=True,
            )

    source_head = "a" * 40
    state_root = tmp_path / "btc-demo-boundary"
    dispatcher = BTCDemoExecutionDispatcher(
        expected_source_head=source_head,
        state_directory=state_root,
        capability_adapter=DemoAdapter(),
        credential_service="quant-system.okx-demo.trade",
    )
    calls: list[str] = []

    for client_order_id in (
        "btcDP012345679999",
        "btcDP89abcdef9999",
    ):
        intent = OrderIntent(
            timestamp_utc=datetime.now(timezone.utc),
            strategy_id="demo-boundary-control",
            symbol="BTC-USDT-SWAP",
            side=OrderSide.SELL,
            quantity=0.01,
            order_type=OrderType.LIMIT,
            limit_price=60000.0,
            client_order_id=client_order_id,
        )
        risk = RiskDecision(
            approved=True,
            reason="current-demo-risk",
            order_intent_id=intent.order_intent_id,
            threshold=10.0,
        )
        facts = BTCExecutionDispatchFacts(
            exchange_snapshot={
                "captured_at_utc": datetime.now(timezone.utc).isoformat(),
                "account": {
                    "account_level": "2",
                    "position_mode": "long_short_mode",
                    "permissions": ["trade"],
                },
                "instrument": {"contract_value_btc": "0.01"},
                "ticker": {"bid": "60000", "ask": "60000.1"},
                "book": {
                    "bids": [["60000", "1"]],
                    "asks": [["60000.1", "1"]],
                },
            },
            private_ws={
                "connected": True,
                "listener_alive": True,
                "opening_allowed_after_reconciliation": True,
            },
            ledger_reconciliation={
                "status": "reconciled",
                "current_state_exchange_snapshot_match": True,
                "funding_cashflow_reconciled": True,
            },
            credential_service="quant-system.okx-demo.trade",
            runtime_run_id="0123456789abcdef",
            source_head=source_head,
            epoch=1,
            runtime_active=True,
            opening_allowed=False,
            cancel_only=True,
            risk_mode="FROZEN_UNKNOWN",
        )

        result = dispatcher.dispatch(
            action=RuntimeAction.DEAD_MAN,
            order_intent=intent,
            risk_decision=risk,
            facts=facts,
            transport_context="demo-client",
            callback=lambda submitted: calls.append(
                submitted.client_order_id
            )
            or {"status": "accepted"},
        )
        assert result.decision.allowed is True
        assert result.transport_called is True

    lifecycle_files = sorted(
        state_root.glob("demo-namespace-*/client_order_lifecycle.jsonl")
    )
    assert len(lifecycle_files) == 2
    assert not (state_root / "client_order_lifecycle.jsonl").exists()
    assert calls == [
        "btcDP012345679999",
        "btcDP89abcdef9999",
    ]


def test_backend_dispatcher_keeps_stale_snapshot_fail_closed_for_new_risk_but_allows_dead_man(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Slow authority collection must not disable an already-needed CAA."""

    current = datetime.now(timezone.utc)
    captured = current - timedelta(seconds=45)
    monkeypatch.setattr(btc_control_plane_module, "utc_now", lambda: current)

    class DemoAdapter:
        def capability_for(self, *, action, transport_context):
            assert transport_context == "demo-client"
            return BTCEndpointCapability(
                mode=BTCExecutionMode.DEMO,
                transport_enabled=True,
                submit_new_order=True,
                cancel_order=True,
                reduce_only=True,
                attach_protection=True,
                dead_man=True,
                private_endpoint_allowed=True,
                order_endpoint_allowed=True,
            )

    source_head = "a" * 40

    def facts(*, opening_allowed: bool, cancel_only: bool, risk_mode: str):
        return BTCExecutionDispatchFacts(
            exchange_snapshot={
                "captured_at_utc": captured.isoformat(),
                "account": {
                    "account_level": "2",
                    "position_mode": "long_short_mode",
                    "permissions": ["trade"],
                },
                "instrument": {"contract_value_btc": "0.01"},
                "ticker": {"bid": "60000", "ask": "60000.1"},
                "book": {
                    "bids": [["60000", "1"]],
                    "asks": [["60000.1", "1"]],
                },
            },
            private_ws={
                "connected": True,
                "listener_alive": True,
                "opening_allowed_after_reconciliation": True,
            },
            ledger_reconciliation={
                "status": "reconciled",
                "current_state_exchange_snapshot_match": True,
                "funding_cashflow_reconciled": True,
            },
            credential_service="quant-system.okx-demo.trade",
            runtime_run_id="slow-authority-run-01",
            source_head=source_head,
            epoch=7,
            runtime_active=True,
            opening_allowed=opening_allowed,
            cancel_only=cancel_only,
            risk_mode=risk_mode,
        )

    def intent(client_order_id: str) -> OrderIntent:
        return OrderIntent(
            timestamp_utc=current,
            strategy_id="demo-boundary-control",
            symbol="BTC-USDT-SWAP",
            side=OrderSide.SELL,
            quantity=0.01,
            order_type=OrderType.LIMIT,
            limit_price=60000.0,
            client_order_id=client_order_id,
        )

    dead_man_intent = intent("btcDPslowdeadman01")
    dead_man_risk = RiskDecision(
        approved=True,
        reason="protective-dead-man",
        order_intent_id=dead_man_intent.order_intent_id,
        threshold=10.0,
    )
    dead_man_dispatcher = BTCDemoExecutionDispatcher(
        expected_source_head=source_head,
        state_directory=tmp_path / "dead-man-boundary",
        capability_adapter=DemoAdapter(),
        credential_service="quant-system.okx-demo.trade",
    )
    calls: list[str] = []

    protective_facts = facts(
        opening_allowed=False,
        cancel_only=True,
        risk_mode="FROZEN_UNKNOWN",
    )
    result = dead_man_dispatcher.dispatch(
        action=RuntimeAction.DEAD_MAN,
        order_intent=dead_man_intent,
        risk_decision=dead_man_risk,
        facts=protective_facts,
        transport_context="demo-client",
        callback=lambda submitted: calls.append(submitted.client_order_id)
        or {"status": "accepted"},
    )

    assert result.decision.allowed is True
    assert result.transport_called is True
    assert calls == [dead_man_intent.client_order_id]

    stale_exchange = dict(protective_facts.exchange_snapshot)
    stale_exchange["captured_at_utc"] = (
        current - timedelta(seconds=121)
    ).isoformat()
    unverified_exchange = dict(protective_facts.exchange_snapshot)
    unverified_exchange["account"] = {
        "account_level": "2",
        "position_mode": "long_short_mode",
        "permissions": ["read_only"],
    }
    for index, incomplete_facts in enumerate(
        (
            replace(protective_facts, private_ws={}),
            replace(protective_facts, ledger_reconciliation={}),
            replace(protective_facts, exchange_snapshot=unverified_exchange),
            replace(protective_facts, exchange_snapshot=stale_exchange),
        ),
        start=1,
    ):
        blocked_intent = intent(f"btcDPdeadmanblock{index:02d}")
        blocked_risk = RiskDecision(
            approved=True,
            reason="incomplete-protective-authority",
            order_intent_id=blocked_intent.order_intent_id,
            threshold=10.0,
        )
        blocked_calls: list[str] = []
        blocked_dispatcher = BTCDemoExecutionDispatcher(
            expected_source_head=source_head,
            state_directory=tmp_path / f"blocked-dead-man-{index}",
            capability_adapter=DemoAdapter(),
            credential_service="quant-system.okx-demo.trade",
        )
        with pytest.raises(Exception, match="projection_blocked"):
            blocked_dispatcher.dispatch(
                action=RuntimeAction.DEAD_MAN,
                order_intent=blocked_intent,
                risk_decision=blocked_risk,
                facts=incomplete_facts,
                transport_context="demo-client",
                callback=lambda submitted: blocked_calls.append(
                    submitted.client_order_id
                ),
            )
        assert blocked_calls == []

    for action, client_order_id in (
        (RuntimeAction.SUBMIT_NEW_ORDER, "btcDPstalesubmit01"),
        (RuntimeAction.ATTACH_PROTECTION, "btcDPstaleprotect1"),
    ):
        new_risk_intent = intent(client_order_id)
        new_risk = RiskDecision(
            approved=True,
            reason="new-risk-must-remain-fresh",
            order_intent_id=new_risk_intent.order_intent_id,
            threshold=10.0,
        )
        dispatcher = BTCDemoExecutionDispatcher(
            expected_source_head=source_head,
            state_directory=tmp_path / action.value,
            capability_adapter=DemoAdapter(),
            credential_service="quant-system.okx-demo.trade",
        )
        with pytest.raises(Exception, match="projection_blocked"):
            dispatcher.dispatch(
                action=action,
                order_intent=new_risk_intent,
                risk_decision=new_risk,
                facts=facts(
                    opening_allowed=True,
                    cancel_only=False,
                    risk_mode="RUNNING",
                ),
                transport_context="demo-client",
                callback=lambda _submitted: pytest.fail(
                    "stale new-risk action reached transport"
                ),
            )


def test_backend_composed_dispatcher_refuses_unverified_raw_facts_before_callback(
    tmp_path: Path,
) -> None:
    class DeniedAdapter:
        def capability_for(self, **_kwargs):
            return BTCEndpointCapability(mode=BTCExecutionMode.DEMO)

    dispatcher = BTCDemoExecutionDispatcher(
        expected_source_head="a" * 40,
        state_directory=tmp_path / "btc-demo-boundary",
        capability_adapter=DeniedAdapter(),
        credential_service="quant-system.okx-demo.trade",
    )
    intent = OrderIntent(
        timestamp_utc=datetime.now(timezone.utc),
        strategy_id="demo-boundary",
        symbol="BTC-USDT-SWAP",
        side=OrderSide.BUY,
        quantity=0.01,
        order_type=OrderType.LIMIT,
        limit_price=60000.0,
        client_order_id="btcDP012345670002",
    )
    risk = RiskDecision(
        approved=True,
        reason="current-demo-risk",
        order_intent_id=intent.order_intent_id,
        threshold=10.0,
    )
    with pytest.raises(Exception, match="projection_blocked"):
        dispatcher.dispatch(
            action=RuntimeAction.SUBMIT_NEW_ORDER,
            order_intent=intent,
            risk_decision=risk,
            facts=BTCExecutionDispatchFacts(
                exchange_snapshot={
                    "captured_at_utc": datetime.now(timezone.utc).isoformat(),
                    "account": {
                        "account_level": "2",
                        "position_mode": "long_short_mode",
                        "permissions": ["trade"],
                    },
                "instrument": {"contract_value_btc": "0.01"},
                "ticker": {"bid": "60000", "ask": "60000.1"},
                "book": {"bids": [["60000", "1"]], "asks": [["60000.1", "1"]]},
                },
                private_ws={},
                ledger_reconciliation={},
                credential_service="quant-system.okx-demo.trade",
                runtime_run_id="0123456789abcdef",
                source_head="a" * 40,
                epoch=1,
                runtime_active=True,
                opening_allowed=True,
                cancel_only=False,
                risk_mode="RUNNING",
                attached_protection={
                    "attachAlgoClOrdId": f"{intent.client_order_id}A",
                    "tpTriggerPx": "61200",
                    "tpOrdPx": "-1",
                    "tpTriggerPxType": "mark",
                    "slTriggerPx": "59400",
                    "slOrdPx": "-1",
                    "slTriggerPxType": "mark",
                    "policy": {"policy_id": "exact"},
                },
            ),
            transport_context="demo-client",
            callback=lambda _intent: pytest.fail("callback_must_not_run"),
        )


def test_real_demo_client_cannot_bypass_missing_composed_dispatcher(
    tmp_path: Path,
) -> None:
    """A direct controller has no production transport path without a permit."""

    controller = OkxDemoPaperRuntimeController(
        config=OkxDemoPaperRuntimeConfig(
            repo_root=Path.cwd(),
            data_db_path=tmp_path / "unused.sqlite",
            output_dir=tmp_path / "btc_demo_paper_runtime",
        ),
        credential_loader=lambda _: _credentials(),
        start_worker=False,
    )
    intent = OrderIntent(
        timestamp_utc=datetime.now(timezone.utc),
        strategy_id="demo-boundary",
        symbol="BTC-USDT-SWAP",
        side=OrderSide.SELL,
        quantity=0.01,
        order_type=OrderType.LIMIT,
        limit_price=60000.0,
        client_order_id="btcDP012345670003",
    )
    risk = RiskDecision(
        approved=True,
        reason="current-demo-risk",
        order_intent_id=intent.order_intent_id,
        threshold=10.0,
    )
    real_client = OkxDemoClient(
        config=OkxDemoClientConfig(),
        credentials=_credentials(),
    )

    with pytest.raises(
        OkxDemoPaperRuntimeError,
        match="execution_boundary_dispatcher_required",
    ):
        controller._dispatch_execution_action(
            action=RuntimeAction.REDUCE_ONLY,
            client=real_client,
            intent=intent,
            risk=risk,
            snapshot={},
            callback=lambda _intent: pytest.fail("real_client_bypass"),
        )


def test_frozen_mode_blocks_opening_before_any_post(tmp_path: Path) -> None:
    controller, snapshot, order_plan = _p0_order_controller(tmp_path)
    client = OrderScenarioClient()
    controller._set_risk_mode(
        "FROZEN_UNKNOWN",
        "fault_injected_private_write_unknown",
    )

    with pytest.raises(
        OkxDemoPaperRuntimeError,
        match="okx_demo_order_submit_mode_not_allowed:FROZEN_UNKNOWN",
    ):
        controller._submit_order_plan(
            client,  # type: ignore[arg-type]
            snapshot=snapshot,
            decision=_p0_order_decision(),
            order_plan=order_plan,
        )

    assert client.submit_calls == []
    assert controller.status()["risk_control"]["pending_order_intents"] == {}


def test_risk_mode_flip_after_durable_intent_blocks_post(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller, snapshot, order_plan = _p0_order_controller(tmp_path)
    client = OrderScenarioClient()
    original_persist = controller._persist_state
    flipped = False

    def persist_then_freeze() -> None:
        nonlocal flipped
        original_persist()
        pending = controller._state["risk_control"]["pending_order_intents"]
        if pending and not flipped:
            flipped = True
            controller._set_risk_mode(
                "FROZEN_UNKNOWN",
                "fault_injected_dead_man_ack_lost",
            )

    monkeypatch.setattr(controller, "_persist_state", persist_then_freeze)

    with pytest.raises(
        OkxDemoPaperRuntimeError,
        match="okx_demo_order_submit_mode_not_allowed:FROZEN_UNKNOWN",
    ):
        controller._submit_order_plan(
            client,  # type: ignore[arg-type]
            snapshot=snapshot,
            decision=_p0_order_decision(),
            order_plan=order_plan,
        )

    clordid = order_plan["client_order_id"]
    pending = controller.status()["risk_control"]["pending_order_intents"][
        clordid
    ]
    assert client.submit_calls == []
    assert pending["status"] == "blocked_before_post"
    assert pending["retry_without_query_allowed"] is False


def test_authorization_fence_blocks_state_flip_after_final_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller, snapshot, order_plan = _p0_order_controller(tmp_path)
    client = OrderScenarioClient()
    original_assert = controller._assert_order_submit_path
    assertion_calls = 0

    def assert_then_flip(**kwargs: Any) -> None:
        nonlocal assertion_calls
        original_assert(**kwargs)
        assertion_calls += 1
        if assertion_calls == 2:
            controller._set_risk_mode(
                "FROZEN_UNKNOWN",
                "fault_injected_gate_return_state_flip",
            )

    monkeypatch.setattr(
        controller,
        "_assert_order_submit_path",
        assert_then_flip,
    )

    with pytest.raises(
        OkxDemoPaperRuntimeError,
        match="okx_demo_order_submit_authorization_fence_changed",
    ):
        controller._submit_order_plan(
            client,  # type: ignore[arg-type]
            snapshot=snapshot,
            decision=_p0_order_decision(),
            order_plan=order_plan,
        )

    pending = controller.status()["risk_control"]["pending_order_intents"][
        order_plan["client_order_id"]
    ]
    assert assertion_calls == 2
    assert client.submit_calls == []
    assert pending["status"] == "blocked_before_post"
    assert pending["retry_without_query_allowed"] is False
    assert controller.status()["risk_control"]["mode"] == "FROZEN_UNKNOWN"


@pytest.mark.parametrize(
    ("runtime_patch", "private_ws_patch", "dead_man_patch", "expected_error"),
    [
        (
            {"cancel_only": True},
            {},
            {},
            "okx_demo_opening_submit_cancel_only_active",
        ),
        (
            {},
            {"connected": False},
            {},
            "okx_demo_opening_submit_private_ws_not_reconciled",
        ),
        (
            {},
            {"listener_alive": False},
            {},
            "okx_demo_opening_submit_private_ws_not_reconciled",
        ),
        (
            {},
            {"opening_allowed_after_reconciliation": False},
            {},
            "okx_demo_opening_submit_private_ws_not_reconciled",
        ),
        (
            {},
            {},
            {"armed": False},
            "okx_demo_opening_submit_dead_man_not_armed",
        ),
    ],
)
def test_opening_submit_requires_stable_full_safety_baseline(
    tmp_path: Path,
    runtime_patch: Mapping[str, Any],
    private_ws_patch: Mapping[str, Any],
    dead_man_patch: Mapping[str, Any],
    expected_error: str,
) -> None:
    controller, snapshot, order_plan = _p0_order_controller(tmp_path)
    controller._state["runtime"].update(runtime_patch)
    controller._state["private_ws"].update(private_ws_patch)
    controller._state["risk_control"]["dead_man"].update(dead_man_patch)
    client = OrderScenarioClient()

    with pytest.raises(OkxDemoPaperRuntimeError, match=expected_error):
        controller._submit_order_plan(
            client,  # type: ignore[arg-type]
            snapshot=snapshot,
            decision=_p0_order_decision(),
            order_plan=order_plan,
        )

    assert client.submit_calls == []
    assert controller.status()["risk_control"][
        "pending_order_intents"
    ] == {}


def test_reduce_only_gate_remains_available_with_private_ws_disconnected(
    tmp_path: Path,
) -> None:
    controller, _, _ = _p0_order_controller(tmp_path)
    controller._state["runtime"].update(
        {"opening_allowed": False, "cancel_only": True}
    )
    controller._state["risk_control"]["mode"] = "RISK_REDUCING"
    controller._state["private_ws"].update(
        {
            "connected": False,
            "listener_alive": False,
            "opening_allowed_after_reconciliation": False,
        }
    )

    controller._assert_order_submit_path(is_opening=False)


def test_unresolved_submit_timeout_freezes_unknown_without_blind_retry(
    tmp_path: Path,
) -> None:
    controller, snapshot, order_plan = _p0_order_controller(tmp_path)
    client = OrderScenarioClient(
        submit_exception=OkxDemoTransportError("response_lost"),
        order_visible=False,
        filled_size="0",
    )

    with pytest.raises(
        OkxDemoPaperRuntimeError,
        match="okx_demo_submit_outcome_unknown_no_retry",
    ):
        controller._submit_order_plan(
            client,  # type: ignore[arg-type]
            snapshot=snapshot,
            decision=_p0_order_decision(),
            order_plan=order_plan,
        )

    status = controller.status()
    clordid = order_plan["client_order_id"]
    assert len(client.submit_calls) == 1
    assert status["risk_control"]["mode"] == "FROZEN_UNKNOWN"
    assert status["risk_control"]["pending_order_intents"][clordid]["status"] == (
        "unknown"
    )
    assert status["risk_control"]["pending_order_intents"][clordid][
        "retry_without_query_allowed"
    ] is False
    queried_paths = {call["path"] for call in client.private_calls}
    assert {
        "/api/v5/trade/order",
        "/api/v5/trade/orders-pending",
        "/api/v5/trade/orders-history",
        "/api/v5/trade/fills",
        "/api/v5/account/positions",
    } <= queried_paths
    outcome_probe = status["risk_control"]["pending_order_intents"][clordid][
        "outcome_probe"
    ]
    assert outcome_probe["blind_retry_allowed"] is False
    assert outcome_probe["fill_matches"] == 0
    assert outcome_probe["signed_position_contracts"] == "0"
    assert outcome_probe["gross_position_contracts"] == "0"


def test_manual_reconciliation_refuses_unproven_absent_ambiguous_clordid(
    tmp_path: Path,
) -> None:
    controller = _controller(tmp_path, lambda _: _credentials())
    controller._state["risk_control"]["pending_order_intents"] = {
        "btcDPmissing0001": {
            "client_order_id": "btcDPmissing0001",
            "status": "unknown",
            "retry_without_query_allowed": False,
        }
    }

    class MissingOrderClient:
        def private_get(
            self,
            path: str,
            params: Mapping[str, Any] | None = None,
        ) -> OkxDemoResponse:
            assert path == "/api/v5/trade/order"
            assert params == {
                "instId": "BTC-USDT-SWAP",
                "clOrdId": "btcDPmissing0001",
            }
            return OkxDemoResponse(
                method="GET",
                path=path,
                http_status=200,
                code="0",
                message="",
                data=(),
            )

    blockers = controller._reconcile_ambiguous_order_intents(
        MissingOrderClient(),  # type: ignore[arg-type]
        {
            "orders": [],
            "pending_orders": [],
            "fills": [],
            "positions": [],
        },
    )

    assert blockers == [
        "okx_demo_ambiguous_order_absence_unproven:btcDPmissing0001:gross=0"
    ]
    pending = controller.status()["risk_control"]["pending_order_intents"]
    assert pending["btcDPmissing0001"]["status"] == "unknown"
    assert pending["btcDPmissing0001"]["retry_without_query_allowed"] is False


def test_submit_and_direct_clordid_query_loss_still_freezes_without_repost(
    tmp_path: Path,
) -> None:
    controller, snapshot, order_plan = _p0_order_controller(tmp_path)
    client = OrderScenarioClient(
        submit_exception=OkxDemoTransportError("submit_response_lost"),
        order_visible=False,
        filled_size="0",
        private_exceptions={
            "/api/v5/trade/order": OkxDemoTransportError(
                "clordid_query_response_lost"
            )
        },
    )

    with pytest.raises(
        OkxDemoPaperRuntimeError,
        match="okx_demo_submit_outcome_unknown_no_retry",
    ):
        controller._submit_order_plan(
            client,  # type: ignore[arg-type]
            snapshot=snapshot,
            decision=_p0_order_decision(),
            order_plan=order_plan,
        )

    clordid = order_plan["client_order_id"]
    status = controller.status()
    pending = status["risk_control"]["pending_order_intents"][clordid]
    assert len(client.submit_calls) == 1
    assert status["risk_control"]["mode"] == "FROZEN_UNKNOWN"
    assert pending["status"] == "unknown"
    assert pending["retry_without_query_allowed"] is False
    assert pending["outcome_probe"]["blind_retry_allowed"] is False
    assert pending["outcome_probe"]["direct_order_match"] is False
    assert pending["outcome_probe"]["read_errors"] == [
        "/api/v5/trade/order:clordid_query_response_lost"
    ]
    queried_paths = {call["path"] for call in client.private_calls}
    assert {
        "/api/v5/trade/order",
        "/api/v5/trade/orders-pending",
        "/api/v5/trade/orders-history",
        "/api/v5/trade/fills",
        "/api/v5/account/positions",
    } <= queried_paths


@pytest.mark.parametrize(
    ("include_position", "position_value"),
    [
        (True, "malformed"),
        (True, None),
        (True, ""),
        (False, None),
    ],
)
def test_invalid_position_evidence_after_submit_timeout_stays_ambiguous(
    tmp_path: Path,
    include_position: bool,
    position_value: Any,
) -> None:
    controller, snapshot, order_plan = _p0_order_controller(tmp_path)

    class MalformedPositionClient(OrderScenarioClient):
        def private_get(
            self,
            path: str,
            params: Mapping[str, Any] | None = None,
        ) -> OkxDemoResponse:
            if path == "/api/v5/account/positions":
                self.private_calls.append(
                    {"path": path, "params": dict(params or {})}
                )
                position_row: dict[str, Any] = {
                    "instId": "BTC-USDT-SWAP",
                    "posSide": "long",
                }
                if include_position:
                    position_row["pos"] = position_value
                return OkxDemoResponse(
                    method="GET",
                    path=path,
                    http_status=200,
                    code="0",
                    message="",
                    data=(position_row,),
                )
            return super().private_get(path, params)

    client = MalformedPositionClient(
        submit_exception=OkxDemoTransportError("response_lost"),
        order_visible=True,
        filled_size="0.01",
    )

    with pytest.raises(
        OkxDemoPaperRuntimeError,
        match="okx_demo_submit_outcome_unknown_no_retry",
    ):
        controller._submit_order_plan(
            client,  # type: ignore[arg-type]
            snapshot=snapshot,
            decision=_p0_order_decision(),
            order_plan=order_plan,
        )

    pending = controller.status()["risk_control"]["pending_order_intents"][
        order_plan["client_order_id"]
    ]
    assert pending["status"] == "unknown"
    assert pending["outcome_probe"]["position_evidence_valid"] is False
    assert pending["outcome_probe"]["signed_position_contracts"] == "invalid"
    assert pending["outcome_probe"]["gross_position_contracts"] == "invalid"
    assert client.submit_calls and len(client.submit_calls) == 1
    assert controller.status()["risk_control"]["mode"] == "FROZEN_UNKNOWN"


def test_hedged_positions_cannot_masquerade_as_flat_for_ambiguous_intent(
    tmp_path: Path,
) -> None:
    controller = _controller(tmp_path, lambda _: _credentials())
    controller._state["risk_control"]["pending_order_intents"] = {
        "btcDPmissing0002": {
            "client_order_id": "btcDPmissing0002",
            "status": "unknown",
        }
    }

    class MissingOrderClient:
        def private_get(
            self,
            path: str,
            params: Mapping[str, Any] | None = None,
        ) -> OkxDemoResponse:
            del params
            return OkxDemoResponse(
                method="GET",
                path=path,
                http_status=200,
                code="0",
                message="",
                data=(),
            )

    blockers = controller._reconcile_ambiguous_order_intents(
        MissingOrderClient(),  # type: ignore[arg-type]
        {
            "orders": [],
            "pending_orders": [],
            "fills": [],
            "positions": [
                {"position_side": "long", "contracts": "0.01"},
                {"position_side": "short", "contracts": "0.01"},
            ],
        },
    )

    assert blockers == [
        "okx_demo_ambiguous_order_absence_unproven:"
        "btcDPmissing0002:gross=0.02"
    ]
    pending = controller.status()["risk_control"]["pending_order_intents"]
    assert pending["btcDPmissing0002"]["status"] == "unknown"


def test_exchange_protection_check_fails_closed_on_malformed_position(
    tmp_path: Path,
) -> None:
    controller = _controller(tmp_path, lambda _: _credentials())

    blockers = controller._exchange_hosted_protection_blockers(
        {
            "positions": [
                {"position_side": "long", "contracts": "malformed"}
            ],
            "pending_algo_orders": [],
        }
    )

    assert blockers == ["okx_demo_paper_position_evidence_invalid"]


def test_single_protection_cannot_cover_equal_long_short_hedge(
    tmp_path: Path,
) -> None:
    controller = _controller(tmp_path, lambda _: _credentials())
    controller._state["risk_control"]["active_protection"] = {
        "status": "exchange_accepted",
        "algo_client_order_id": "protect-hedge",
        "instrument_id": "BTC-USDT-SWAP",
        "position_side": "long",
        "contracts": "0.01",
        "market_exit": True,
        "tp_trigger_px": "60600",
        "sl_trigger_px": "59400",
    }

    blockers = controller._exchange_hosted_protection_blockers(
        {
            "positions": [
                {"position_side": "long", "contracts": "0.005"},
                {"position_side": "short", "contracts": "0.005"},
            ],
            "pending_algo_orders": [
                {
                    "algo_client_order_id": "protect-hedge",
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
        }
    )

    assert blockers == [
        "okx_demo_paper_hedged_position_shape_unsupported"
    ]


@pytest.mark.parametrize(
    ("active_position_side", "algo_position_side"),
    [
        ("long", "long"),
        ("", "short"),
        ("short", ""),
    ],
)
def test_short_position_rejects_stale_or_incomplete_protection_direction(
    tmp_path: Path,
    active_position_side: str,
    algo_position_side: str,
) -> None:
    controller = _controller(tmp_path, lambda _: _credentials())
    controller._state["risk_control"]["active_protection"] = {
        "status": "exchange_accepted",
        "algo_client_order_id": "protect-short",
        "instrument_id": "BTC-USDT-SWAP",
        "position_side": active_position_side,
        "contracts": "0.01",
        "market_exit": True,
        "tp_trigger_px": "59400",
        "sl_trigger_px": "60600",
    }

    blockers = controller._exchange_hosted_protection_blockers(
        {
            "positions": [
                {"position_side": "short", "contracts": "0.01"}
            ],
            "pending_algo_orders": [
                {
                    "algo_client_order_id": "protect-short",
                    "instrument_id": "BTC-USDT-SWAP",
                    "position_side": algo_position_side,
                    "size": "0.01",
                    "state": "live",
                    "take_profit_trigger": "59400",
                    "take_profit_trigger_type": "mark",
                    "take_profit_order_price": "-1",
                    "stop_loss_trigger": "60600",
                    "stop_loss_trigger_type": "mark",
                    "stop_loss_order_price": "-1",
                }
            ],
        }
    )

    assert blockers == [
        "okx_demo_exchange_protection_position_side_mismatch"
    ]


def test_cycle_rejects_non_market_exit_exchange_protection(
    tmp_path: Path,
) -> None:
    controller = _controller(tmp_path, lambda _: _credentials())
    controller._state["risk_control"]["active_protection"] = {
        "status": "exchange_accepted",
        "algo_client_order_id": "protect-long",
        "instrument_id": "BTC-USDT-SWAP",
        "position_side": "long",
        "contracts": "0.01",
        "market_exit": True,
        "tp_trigger_px": "60600",
        "sl_trigger_px": "59400",
    }

    blockers = controller._exchange_hosted_protection_blockers(
        {
            "positions": [
                {"position_side": "long", "contracts": "0.01"}
            ],
            "pending_algo_orders": [
                {
                    "algo_client_order_id": "protect-long",
                    "instrument_id": "BTC-USDT-SWAP",
                    "position_side": "long",
                    "size": "0.01",
                    "state": "live",
                    "take_profit_trigger": "60600",
                    "take_profit_trigger_type": "mark",
                    "take_profit_order_price": "60610",
                    "stop_loss_trigger": "59400",
                    "stop_loss_trigger_type": "mark",
                    "stop_loss_order_price": "-1",
                }
            ],
        }
    )

    assert blockers == [
        "okx_demo_exchange_protection_market_exit_unconfirmed"
    ]


def test_attached_protection_accepts_empty_parent_fail_code_only_with_empty_reason_and_exact_live_oco(
    tmp_path: Path,
) -> None:
    controller, _, order_plan = _p0_order_controller(tmp_path)
    expected = dict(order_plan["attached_protection"])
    algo = {
        "algoId": "algo-1",
        "algoClOrdId": expected["attachAlgoClOrdId"],
        "instId": "BTC-USDT-SWAP",
        "posSide": "long",
        "sz": "0.01",
        "state": "live",
        "tpTriggerPx": expected["tpTriggerPx"],
        "tpTriggerPxType": "mark",
        "tpOrdPx": "-1",
        "slTriggerPx": expected["slTriggerPx"],
        "slTriggerPxType": "mark",
        "slOrdPx": "-1",
    }

    class ExactLiveAlgoClient:
        def private_get(
            self,
            path: str,
            params: Mapping[str, Any] | None = None,
        ) -> OkxDemoResponse:
            assert path == "/api/v5/trade/order-algo"
            assert params == {
                "algoClOrdId": expected["attachAlgoClOrdId"]
            }
            return OkxDemoResponse(
                method="GET",
                path=path,
                http_status=200,
                code="0",
                message="",
                data=(algo,),
            )

    receipt = controller._verify_attached_protection(
        ExactLiveAlgoClient(),  # type: ignore[arg-type]
        final_order={
            "clOrdId": str(order_plan["client_order_id"]),
            "attachAlgoOrds": [
                {
                    "attachAlgoClOrdId": expected["attachAlgoClOrdId"],
                    "failCode": "",
                    "failReason": "",
                }
            ]
        },
        order_plan=order_plan,
    )

    assert receipt["status"] == "exchange_accepted"
    assert receipt["algo_id"] == "algo-1"
    assert receipt["algo_client_order_id"] == expected["attachAlgoClOrdId"]
    assert receipt["parent_acknowledged"] is True
    assert receipt["parent_conflict_reconciled"] is False
    assert receipt["parent_fail_code"] == ""
    assert receipt["readback_source"] == "order_algo"
    assert receipt["query_only_readback_attempts"] == 1
    assert all(receipt["checks"].values())


def test_attached_protection_reconciles_explicit_parent_conflict_by_exact_client_id_query(
    tmp_path: Path,
) -> None:
    """A non-zero parent code is not decisive when exact broker OCO exists."""
    controller, _, order_plan = _p0_order_controller(tmp_path)
    expected = dict(order_plan["attached_protection"])
    algo = {
        "algoId": "algo-live-after-parent-conflict",
        "algoClOrdId": expected["attachAlgoClOrdId"],
        "instId": "BTC-USDT-SWAP",
        "posSide": "long",
        "sz": "0.01",
        "state": "live",
        "tpTriggerPx": expected["tpTriggerPx"],
        "tpTriggerPxType": "mark",
        "tpOrdPx": "-1",
        "slTriggerPx": expected["slTriggerPx"],
        "slTriggerPxType": "mark",
        "slOrdPx": "-1",
    }

    class ConflictClient:
        calls: list[tuple[str, Mapping[str, Any] | None]] = []

        def private_get(
            self,
            path: str,
            params: Mapping[str, Any] | None = None,
        ) -> OkxDemoResponse:
            self.calls.append((path, params))
            assert path == "/api/v5/trade/order-algo"
            assert params == {"algoClOrdId": expected["attachAlgoClOrdId"]}
            return OkxDemoResponse(
                method="GET",
                path=path,
                http_status=200,
                code="0",
                message="",
                data=(algo,),
            )

    client = ConflictClient()
    receipt = controller._verify_attached_protection(
        client,  # type: ignore[arg-type]
        final_order={
            "attachAlgoOrds": [
                {
                    "attachAlgoId": "untrusted-parent-algo-id",
                    "attachAlgoClOrdId": expected["attachAlgoClOrdId"],
                    "failCode": "51603",
                }
            ]
        },
        order_plan=order_plan,
    )

    assert client.calls == [
        ("/api/v5/trade/order-algo", {"algoClOrdId": expected["attachAlgoClOrdId"]})
    ]
    assert receipt["status"] == "exchange_accepted"
    assert receipt["algo_id"] == "algo-live-after-parent-conflict"
    assert receipt["parent_acknowledged"] is False
    assert receipt["parent_conflict_reconciled"] is True
    assert receipt["parent_fail_code"] == "51603"


def test_attached_protection_reconciles_51603_exact_readback_from_unique_live_pending_oco(
    tmp_path: Path,
) -> None:
    """A delayed OCO is accepted only after the mandatory exact query."""
    controller, _, order_plan = _p0_order_controller(tmp_path)
    expected = dict(order_plan["attached_protection"])
    algo = {
        "algoId": "algo-live-after-51603",
        "algoClOrdId": expected["attachAlgoClOrdId"],
        "instId": "BTC-USDT-SWAP",
        "posSide": "long",
        "sz": "0.01",
        "state": "live",
        "ordType": "oco",
        "parentClOrdId": str(order_plan["client_order_id"]),
        "tpTriggerPx": expected["tpTriggerPx"],
        "tpTriggerPxType": "mark",
        "tpOrdPx": "-1",
        "slTriggerPx": expected["slTriggerPx"],
        "slTriggerPxType": "mark",
        "slOrdPx": "-1",
    }

    class DelayedPendingAlgoClient:
        calls: list[tuple[str, Mapping[str, Any] | None]] = []
        order_posts: list[Mapping[str, Any]] = []
        cancel_posts: list[Mapping[str, Any]] = []

        def submit_order(self, payload: Mapping[str, Any]) -> OkxDemoResponse:
            self.order_posts.append(payload)
            raise AssertionError("attached_protection_must_not_submit")

        def cancel_order(self, **payload: Any) -> OkxDemoResponse:
            self.cancel_posts.append(payload)
            raise AssertionError("attached_protection_must_not_cancel")

        def private_get(
            self,
            path: str,
            params: Mapping[str, Any] | None = None,
        ) -> OkxDemoResponse:
            self.calls.append((path, params))
            if path == "/api/v5/trade/order-algo":
                assert params == {
                    "algoClOrdId": expected["attachAlgoClOrdId"]
                }
                return OkxDemoResponse(
                    method="GET",
                    path=path,
                    http_status=200,
                    code="51603",
                    message="",
                    data=(),
                )
            assert path == "/api/v5/trade/orders-algo-pending"
            assert params == {
                "instId": "BTC-USDT-SWAP",
                "ordType": "oco",
            }
            return OkxDemoResponse(
                method="GET",
                path=path,
                http_status=200,
                code="0",
                message="",
                data=(algo,),
            )

    client = DelayedPendingAlgoClient()
    receipt = controller._verify_attached_protection(
        client,  # type: ignore[arg-type]
        final_order={
            "clOrdId": str(order_plan["client_order_id"]),
            "attachAlgoOrds": [
                {
                    "attachAlgoId": "untrusted-parent-algo-id",
                    "attachAlgoClOrdId": expected["attachAlgoClOrdId"],
                    "failCode": "51603",
                }
            ]
        },
        order_plan=order_plan,
    )

    assert client.calls == [
        (
            "/api/v5/trade/order-algo",
            {"algoClOrdId": expected["attachAlgoClOrdId"]},
        ),
        (
            "/api/v5/trade/orders-algo-pending",
            {"instId": "BTC-USDT-SWAP", "ordType": "oco"},
        ),
    ]
    assert receipt["status"] == "exchange_accepted"
    assert receipt["algo_id"] == "algo-live-after-51603"
    assert receipt["query_first"] is True
    assert (
        receipt["readback_source"]
        == "orders_algo_pending_after_order_algo_51603"
    )
    assert receipt["query_only_readback_attempts"] == 2
    assert receipt["parent_acknowledged"] is False
    assert receipt["parent_conflict_reconciled"] is True
    assert receipt["parent_fail_code"] == "51603"
    assert client.order_posts == []
    assert client.cancel_posts == []


def test_attached_protection_51603_pending_readback_does_not_submit_or_cancel_again(
    tmp_path: Path,
) -> None:
    controller, snapshot, order_plan = _p0_order_controller(tmp_path)

    class OneEntryDelayedProtectionClient(OrderScenarioClient):
        cancel_calls: list[Mapping[str, Any]] = []
        dead_man_calls: list[Mapping[str, Any]] = []
        algo_create_calls: list[Mapping[str, Any]] = []

        def private_get(
            self,
            path: str,
            params: Mapping[str, Any] | None = None,
        ) -> OkxDemoResponse:
            if path == "/api/v5/trade/order-algo":
                self.private_calls.append({"path": path, "params": dict(params or {})})
                return OkxDemoResponse(
                    method="GET", path=path, http_status=200, code="51603",
                    message="", data=(),
                )
            if path == "/api/v5/trade/orders-algo-pending":
                self.private_calls.append({"path": path, "params": dict(params or {})})
                order = self.submit_calls[-1]
                protection = self._protection(order)
                return OkxDemoResponse(
                    method="GET", path=path, http_status=200, code="0",
                    message="", data=({
                        **protection,
                        "ordType": "oco",
                        "parentClOrdId": order["clOrdId"],
                    },),
                )
            return super().private_get(path, params)

        def _final_order(self, order: Mapping[str, Any]) -> dict[str, Any]:
            final = super()._final_order(order)
            final["attachAlgoOrds"][0]["failCode"] = "51603"
            return final

        def cancel_order(self, **payload: Any) -> OkxDemoResponse:
            self.cancel_calls.append(payload)
            raise AssertionError("pending_readback_must_not_cancel")

        def cancel_all_after(self, **payload: Any) -> OkxDemoResponse:
            self.dead_man_calls.append(payload)
            raise AssertionError("pending_readback_must_not_arm_dead_man")

        def create_algo_order(self, payload: Mapping[str, Any]) -> OkxDemoResponse:
            self.algo_create_calls.append(payload)
            raise AssertionError("pending_readback_must_not_create_algo")

    client = OneEntryDelayedProtectionClient()
    _install_order_followup(controller, client, order_plan)

    result = controller._submit_order_plan(
        client,
        snapshot=snapshot,
        decision=_p0_order_decision(),
        order_plan=order_plan,
    )

    assert result["orders_posted"] == 1
    assert result["protection_verified"] is True
    assert len(client.submit_calls) == 1
    assert client.cancel_calls == []
    assert client.dead_man_calls == []
    assert client.algo_create_calls == []
    assert [
        row["path"] for row in client.private_calls
        if row["path"] in {
            "/api/v5/trade/order-algo",
            "/api/v5/trade/orders-algo-pending",
        }
    ] == [
        "/api/v5/trade/order-algo",
        "/api/v5/trade/orders-algo-pending",
    ]


def test_attached_protection_51603_pending_readback_rejects_final_order_identity_mismatch(
    tmp_path: Path,
) -> None:
    controller, _, order_plan = _p0_order_controller(tmp_path)
    expected = dict(order_plan["attached_protection"])

    class IdentityMismatchClient:
        calls: list[str] = []

        def private_get(
            self,
            path: str,
            params: Mapping[str, Any] | None = None,
        ) -> OkxDemoResponse:
            self.calls.append(path)
            assert path == "/api/v5/trade/order-algo"
            assert params == {"algoClOrdId": expected["attachAlgoClOrdId"]}
            return OkxDemoResponse(
                method="GET", path=path, http_status=200, code="51603",
                message="", data=(),
            )

    client = IdentityMismatchClient()
    with pytest.raises(
        OkxDemoPaperRuntimeError,
        match="okx_demo_attached_algo_parent_order_identity_mismatch",
    ):
        controller._verify_attached_protection(
            client,  # type: ignore[arg-type]
            final_order={
                "clOrdId": "foreign-parent",
                "attachAlgoOrds": [{
                    "attachAlgoClOrdId": expected["attachAlgoClOrdId"],
                    "failCode": "51603",
                }],
            },
            order_plan=order_plan,
        )
    assert client.calls == ["/api/v5/trade/order-algo"]


@pytest.mark.parametrize(
    "mutation",
    [
        {"algoId": ""},
        {"sz": "0.02"},
        {"tpTriggerPx": "1"},
        {"slTriggerPx": "1"},
        {"tpTriggerPxType": "last"},
        {"slTriggerPxType": "last"},
        {"tpOrdPx": "1"},
        {"slOrdPx": "1"},
        {"posSide": "short"},
    ],
)
def test_attached_protection_51603_pending_readback_reuses_strict_contract_checks(
    tmp_path: Path,
    mutation: Mapping[str, str],
) -> None:
    controller, _, order_plan = _p0_order_controller(tmp_path)
    expected = dict(order_plan["attached_protection"])
    algo = {
        "algoId": "algo-pending-contract",
        "algoClOrdId": expected["attachAlgoClOrdId"],
        "instId": "BTC-USDT-SWAP",
        "posSide": "long",
        "sz": "0.01",
        "state": "live",
        "ordType": "oco",
        "tpTriggerPx": expected["tpTriggerPx"],
        "tpTriggerPxType": "mark",
        "tpOrdPx": "-1",
        "slTriggerPx": expected["slTriggerPx"],
        "slTriggerPxType": "mark",
        "slOrdPx": "-1",
    }
    algo.update(mutation)

    class MismatchPendingClient:
        calls: list[str] = []

        def private_get(
            self,
            path: str,
            params: Mapping[str, Any] | None = None,
        ) -> OkxDemoResponse:
            self.calls.append(path)
            if path == "/api/v5/trade/order-algo":
                return OkxDemoResponse(
                    method="GET", path=path, http_status=200, code="51603",
                    message="", data=(),
                )
            assert path == "/api/v5/trade/orders-algo-pending"
            assert params == {"instId": "BTC-USDT-SWAP", "ordType": "oco"}
            return OkxDemoResponse(
                method="GET", path=path, http_status=200, code="0", message="",
                data=(algo,),
            )

    client = MismatchPendingClient()
    with pytest.raises(
        OkxDemoPaperRuntimeError,
        match="okx_demo_attached_algo_contract_mismatch",
    ):
        controller._verify_attached_protection(
            client,  # type: ignore[arg-type]
            final_order={
                "clOrdId": str(order_plan["client_order_id"]),
                "attachAlgoOrds": [{
                    "attachAlgoClOrdId": expected["attachAlgoClOrdId"],
                    "failCode": "51603",
                }],
            },
            order_plan=order_plan,
        )
    assert client.calls == [
        "/api/v5/trade/order-algo",
        "/api/v5/trade/orders-algo-pending",
    ]


def test_attached_protection_51603_pending_readback_polls_boundedly(
    tmp_path: Path,
) -> None:
    controller, _, order_plan = _p0_order_controller(tmp_path)
    controller.config = replace(
        controller.config,
        order_poll_attempts=2,
        order_poll_interval_seconds=0.001,
    )
    expected = dict(order_plan["attached_protection"])
    algo = {
        "algoId": "algo-live-after-poll",
        "algoClOrdId": expected["attachAlgoClOrdId"],
        "instId": "BTC-USDT-SWAP",
        "posSide": "long",
        "sz": "0.01",
        "state": "live",
        "order_type": "oco",
        "tpTriggerPx": expected["tpTriggerPx"],
        "tpTriggerPxType": "mark",
        "tpOrdPx": "-1",
        "slTriggerPx": expected["slTriggerPx"],
        "slTriggerPxType": "mark",
        "slOrdPx": "-1",
    }

    class PendingPollClient:
        calls: list[str] = []
        pending_calls = 0

        def private_get(
            self,
            path: str,
            params: Mapping[str, Any] | None = None,
        ) -> OkxDemoResponse:
            self.calls.append(path)
            if path == "/api/v5/trade/order-algo":
                return OkxDemoResponse(
                    method="GET", path=path, http_status=200, code="51603",
                    message="", data=(),
                )
            assert path == "/api/v5/trade/orders-algo-pending"
            assert params == {"instId": "BTC-USDT-SWAP", "ordType": "oco"}
            self.pending_calls += 1
            return OkxDemoResponse(
                method="GET", path=path, http_status=200, code="0", message="",
                data=() if self.pending_calls == 1 else (algo,),
            )

    client = PendingPollClient()
    receipt = controller._verify_attached_protection(
        client,  # type: ignore[arg-type]
        final_order={
            "clOrdId": str(order_plan["client_order_id"]),
            "attachAlgoOrds": [{
                "attachAlgoClOrdId": expected["attachAlgoClOrdId"],
                "failCode": "51603",
            }]
        },
        order_plan=order_plan,
    )

    assert client.calls == [
        "/api/v5/trade/order-algo",
        "/api/v5/trade/orders-algo-pending",
        "/api/v5/trade/orders-algo-pending",
    ]
    assert receipt["query_only_readback_attempts"] == 3


@pytest.mark.parametrize(
    "pending_rows",
    [
        (), "duplicate", "foreign", "canceled", "effective",
        "partially_effective", "wrong_type", "wrong_parent",
    ],
)
def test_attached_protection_51603_pending_readback_remains_fail_closed(
    tmp_path: Path,
    pending_rows: object,
) -> None:
    controller, _, order_plan = _p0_order_controller(tmp_path)
    controller.config = replace(
        controller.config,
        order_poll_attempts=1,
        order_poll_interval_seconds=0.001,
    )
    expected = dict(order_plan["attached_protection"])
    algo = {
        "algoId": "algo-pending",
        "algoClOrdId": expected["attachAlgoClOrdId"],
        "instId": "BTC-USDT-SWAP",
        "posSide": "long",
        "sz": "0.01",
        "state": "live",
        "ordType": "oco",
        "tpTriggerPx": expected["tpTriggerPx"],
        "tpTriggerPxType": "mark",
        "tpOrdPx": "-1",
        "slTriggerPx": expected["slTriggerPx"],
        "slTriggerPxType": "mark",
        "slOrdPx": "-1",
    }
    if pending_rows == "duplicate":
        rows = (algo, dict(algo))
    elif pending_rows == "foreign":
        rows = ({**algo, "algoClOrdId": "foreign"},)
    elif pending_rows in {"canceled", "effective", "partially_effective"}:
        rows = ({**algo, "state": pending_rows},)
    elif pending_rows == "wrong_type":
        rows = ({**algo, "ordType": "conditional"},)
    elif pending_rows == "wrong_parent":
        rows = ({**algo, "parentClOrdId": "foreign-parent"},)
    else:
        rows = ()

    class FailingPendingClient:
        calls: list[str] = []

        def private_get(
            self,
            path: str,
            params: Mapping[str, Any] | None = None,
        ) -> OkxDemoResponse:
            self.calls.append(path)
            if path == "/api/v5/trade/order-algo":
                return OkxDemoResponse(
                    method="GET", path=path, http_status=200, code="51603",
                    message="", data=(),
                )
            assert path == "/api/v5/trade/orders-algo-pending"
            return OkxDemoResponse(
                method="GET", path=path, http_status=200, code="0", message="",
                data=rows,
            )

    client = FailingPendingClient()
    with pytest.raises(OkxDemoPaperRuntimeError):
        controller._verify_attached_protection(
            client,  # type: ignore[arg-type]
            final_order={"clOrdId": str(order_plan["client_order_id"]), "attachAlgoOrds": [{
                "attachAlgoClOrdId": expected["attachAlgoClOrdId"],
                "failCode": "51603",
            }]},
            order_plan=order_plan,
        )
    assert client.calls == [
        "/api/v5/trade/order-algo",
        "/api/v5/trade/orders-algo-pending",
    ]


def test_attached_protection_51603_pending_readback_honors_stop_event(
    tmp_path: Path,
) -> None:
    controller, _, order_plan = _p0_order_controller(tmp_path)
    expected = dict(order_plan["attached_protection"])

    class StoppedPendingClient:
        calls: list[str] = []

        def private_get(
            self,
            path: str,
            params: Mapping[str, Any] | None = None,
        ) -> OkxDemoResponse:
            self.calls.append(path)
            assert path == "/api/v5/trade/order-algo"
            return OkxDemoResponse(
                method="GET", path=path, http_status=200, code="51603",
                message="", data=(),
            )

    controller._stop_event.set()
    client = StoppedPendingClient()
    with pytest.raises(
        OkxDemoPaperRuntimeError,
        match="okx_demo_attached_algo_pending_readback_stopped",
    ):
        controller._verify_attached_protection(
            client,  # type: ignore[arg-type]
            final_order={"clOrdId": str(order_plan["client_order_id"]), "attachAlgoOrds": [{
                "attachAlgoClOrdId": expected["attachAlgoClOrdId"],
                "failCode": "51603",
            }]},
            order_plan=order_plan,
        )
    assert client.calls == ["/api/v5/trade/order-algo"]


@pytest.mark.parametrize(
    ("http_status", "code"),
    [(200, "51000"), (404, "51603")],
)
def test_attached_protection_51603_does_not_fallback_for_other_exact_query_code(
    tmp_path: Path,
    http_status: int,
    code: str,
) -> None:
    controller, _, order_plan = _p0_order_controller(tmp_path)
    expected = dict(order_plan["attached_protection"])

    class OtherCodeClient:
        calls: list[str] = []

        def private_get(
            self,
            path: str,
            params: Mapping[str, Any] | None = None,
        ) -> OkxDemoResponse:
            self.calls.append(path)
            assert path == "/api/v5/trade/order-algo"
            return OkxDemoResponse(
                method="GET", path=path, http_status=http_status, code=code,
                message="", data=(),
            )

    client = OtherCodeClient()
    with pytest.raises(
        OkxDemoPaperRuntimeError,
        match=f"okx_demo_paper_attached_protection_failed:{code}",
    ):
        controller._verify_attached_protection(
            client,  # type: ignore[arg-type]
            final_order={"clOrdId": str(order_plan["client_order_id"]), "attachAlgoOrds": [{
                "attachAlgoClOrdId": expected["attachAlgoClOrdId"],
                "failCode": "51603",
            }]},
            order_plan=order_plan,
        )
    assert client.calls == ["/api/v5/trade/order-algo"]


@pytest.mark.parametrize(
    ("parent_rows", "response_data", "expected_error"),
    [
        (
            "duplicate",
            (),
            "okx_demo_attached_algo_parent_reports_failure",
        ),
        (
            "single",
            (),
            "okx_demo_paper_attached_protection_empty",
        ),
        (
            "single",
            "duplicate",
            "okx_demo_attached_algo_readback_ambiguous",
        ),
        (
            "single",
            "canceled",
            "okx_demo_attached_algo_not_active",
        ),
        (
            "single",
            "mismatch",
            "okx_demo_attached_algo_contract_mismatch",
        ),
    ],
)
def test_attached_protection_conflict_readback_remains_fail_closed(
    tmp_path: Path,
    parent_rows: str,
    response_data: object,
    expected_error: str,
) -> None:
    controller, _, order_plan = _p0_order_controller(tmp_path)
    expected = dict(order_plan["attached_protection"])
    algo = {
        "algoId": "algo-conflict",
        "algoClOrdId": expected["attachAlgoClOrdId"],
        "instId": "BTC-USDT-SWAP",
        "posSide": "long",
        "sz": "0.01",
        "state": "live",
        "tpTriggerPx": expected["tpTriggerPx"],
        "tpTriggerPxType": "mark",
        "tpOrdPx": "-1",
        "slTriggerPx": expected["slTriggerPx"],
        "slTriggerPxType": "mark",
        "slOrdPx": "-1",
    }
    if response_data == "duplicate":
        rows = (algo, dict(algo))
    elif response_data == "canceled":
        rows = ({**algo, "state": "canceled"},)
    elif response_data == "mismatch":
        rows = ({**algo, "algoClOrdId": "foreign"},)
    else:
        rows = ()

    class ConflictReadbackClient:
        calls: list[tuple[str, Mapping[str, Any] | None]] = []

        def private_get(
            self,
            path: str,
            params: Mapping[str, Any] | None = None,
        ) -> OkxDemoResponse:
            self.calls.append((path, params))
            assert path == "/api/v5/trade/order-algo"
            assert params == {"algoClOrdId": expected["attachAlgoClOrdId"]}
            return OkxDemoResponse(
                method="GET",
                path=path,
                http_status=200,
                code="0",
                message="",
                data=rows,
            )

    parent = {
        "attachAlgoId": "untrusted-parent-algo-id",
        "attachAlgoClOrdId": expected["attachAlgoClOrdId"],
        "failCode": "51603",
    }
    attached = [parent]
    if parent_rows == "duplicate":
        attached.append(dict(parent))
    client = ConflictReadbackClient()

    with pytest.raises(OkxDemoPaperRuntimeError, match=expected_error):
        controller._verify_attached_protection(
            client,  # type: ignore[arg-type]
            final_order={"attachAlgoOrds": attached},
            order_plan=order_plan,
        )

    if parent_rows == "duplicate":
        assert client.calls == []
    else:
        assert client.calls == [
            ("/api/v5/trade/order-algo", {"algoClOrdId": expected["attachAlgoClOrdId"]})
        ]


def test_attached_protection_conflict_readback_exception_remains_fail_closed(
    tmp_path: Path,
) -> None:
    controller, _, order_plan = _p0_order_controller(tmp_path)
    expected = dict(order_plan["attached_protection"])

    class RaisingConflictClient:
        calls = 0

        def private_get(
            self,
            path: str,
            params: Mapping[str, Any] | None = None,
        ) -> OkxDemoResponse:
            self.calls += 1
            assert path == "/api/v5/trade/order-algo"
            assert params == {"algoClOrdId": expected["attachAlgoClOrdId"]}
            raise OkxDemoPaperRuntimeError("okx_demo_transport_readback_failed")

    client = RaisingConflictClient()
    with pytest.raises(
        OkxDemoPaperRuntimeError,
        match="okx_demo_transport_readback_failed",
    ):
        controller._verify_attached_protection(
            client,  # type: ignore[arg-type]
            final_order={
                "attachAlgoOrds": [
                    {
                        "attachAlgoClOrdId": expected["attachAlgoClOrdId"],
                        "failCode": "51603",
                    }
                ]
            },
            order_plan=order_plan,
        )
    assert client.calls == 1


def test_attached_protection_rejects_missing_parent_fail_code(
    tmp_path: Path,
) -> None:
    controller, _, order_plan = _p0_order_controller(tmp_path)
    expected = dict(order_plan["attached_protection"])

    with pytest.raises(
        OkxDemoPaperRuntimeError,
        match="okx_demo_attached_algo_parent_reports_failure",
    ):
        controller._verify_attached_protection(
            object(),  # type: ignore[arg-type]
            final_order={
                "attachAlgoOrds": [
                    {
                        "attachAlgoClOrdId": expected["attachAlgoClOrdId"],
                        "failReason": "",
                    }
                ]
            },
            order_plan=order_plan,
        )


@pytest.mark.parametrize(
    ("parent_mutation", "algo_mutation", "expected_error"),
    [
        (
            {"failCode": None},
            {},
            "okx_demo_attached_algo_parent_reports_failure",
        ),
        (
            {"failCode": ""},
            {},
            "okx_demo_attached_algo_parent_reports_failure",
        ),
        (
            {"failCode": "", "failReason": "venue rejected"},
            {},
            "okx_demo_attached_algo_parent_reports_failure",
        ),
        (
            {"failCode": "0", "failReason": "venue rejected"},
            {},
            "okx_demo_attached_algo_parent_reports_failure",
        ),
        (
            {"failCode": "0", "failReason": []},
            {},
            "okx_demo_attached_algo_parent_reports_failure",
        ),
        (
            {},
            {"algoClOrdId": None},
            "okx_demo_attached_algo_contract_mismatch",
        ),
        (
            {},
            {"algoId": "wrong-algo"},
            "okx_demo_attached_algo_contract_mismatch",
        ),
        (
            {},
            {"tpOrdPx": "60610"},
            "okx_demo_attached_algo_contract_mismatch",
        ),
        (
            {},
            {"instId": "ETH-USDT-SWAP"},
            "okx_demo_attached_algo_contract_mismatch",
        ),
        (
            {},
            {"posSide": "short"},
            "okx_demo_attached_algo_contract_mismatch",
        ),
        (
            {},
            {"sz": "0.02"},
            "okx_demo_attached_algo_contract_mismatch",
        ),
        (
            {},
            {"tpTriggerPx": "60601"},
            "okx_demo_attached_algo_contract_mismatch",
        ),
        (
            {},
            {"tpTriggerPxType": "last"},
            "okx_demo_attached_algo_contract_mismatch",
        ),
        (
            {},
            {"slTriggerPx": "59399"},
            "okx_demo_attached_algo_contract_mismatch",
        ),
        (
            {},
            {"slTriggerPxType": "last"},
            "okx_demo_attached_algo_contract_mismatch",
        ),
        (
            {},
            {"slOrdPx": "59390"},
            "okx_demo_attached_algo_contract_mismatch",
        ),
        (
            {},
            {"state": "canceled"},
            "okx_demo_attached_algo_not_active",
        ),
    ],
)
def test_attached_protection_requires_explicit_strict_exchange_ack(
    tmp_path: Path,
    parent_mutation: Mapping[str, Any],
    algo_mutation: Mapping[str, Any],
    expected_error: str,
) -> None:
    controller, _, order_plan = _p0_order_controller(tmp_path)
    expected = dict(order_plan["attached_protection"])
    parent = {
        "attachAlgoId": "algo-1",
        "attachAlgoClOrdId": expected["attachAlgoClOrdId"],
        "failCode": "0",
    }
    parent.update(parent_mutation)
    algo = {
        "algoId": "algo-1",
        "algoClOrdId": expected["attachAlgoClOrdId"],
        "instId": "BTC-USDT-SWAP",
        "posSide": "long",
        "sz": "0.01",
        "state": "live",
        "tpTriggerPx": expected["tpTriggerPx"],
        "tpTriggerPxType": "mark",
        "tpOrdPx": "-1",
        "slTriggerPx": expected["slTriggerPx"],
        "slTriggerPxType": "mark",
        "slOrdPx": "-1",
    }
    algo.update(algo_mutation)

    class StrictAlgoClient:
        def private_get(
            self,
            path: str,
            params: Mapping[str, Any] | None = None,
        ) -> OkxDemoResponse:
            assert path == "/api/v5/trade/order-algo"
            assert params == {"algoId": "algo-1"}
            return OkxDemoResponse(
                method="GET",
                path=path,
                http_status=200,
                code="0",
                message="",
                data=(algo,),
            )

    with pytest.raises(OkxDemoPaperRuntimeError, match=expected_error):
        controller._verify_attached_protection(
            StrictAlgoClient(),  # type: ignore[arg-type]
            final_order={"attachAlgoOrds": [parent]},
            order_plan=order_plan,
        )


def test_fok_partial_fill_enters_risk_reducing_only(
    tmp_path: Path,
) -> None:
    controller, snapshot, order_plan = _p0_order_controller(tmp_path)
    client = OrderScenarioClient(
        final_state="canceled",
        filled_size="0.005",
        protection_active=False,
    )
    _install_order_followup(
        controller,
        client,
        order_plan,
        preflight_blockers=[
            "okx_demo_nonflat_position_has_no_verified_protection"
        ],
    )

    with pytest.raises(
        OkxDemoPaperRuntimeError,
        match="okx_demo_fok_partial_fill_requires_risk_reduction",
    ):
        controller._submit_order_plan(
            client,  # type: ignore[arg-type]
            snapshot=snapshot,
            decision=_p0_order_decision(),
            order_plan=order_plan,
        )

    status = controller.status()
    assert status["risk_control"]["mode"] == "RISK_REDUCING"
    assert status["runtime"]["opening_allowed"] is False
    assert len(client.submit_calls) == 1


def test_filled_open_without_verified_protection_enters_risk_reducing_only(
    tmp_path: Path,
) -> None:
    controller, snapshot, order_plan = _p0_order_controller(tmp_path)
    client = OrderScenarioClient(protection_active=False)
    _install_order_followup(
        controller,
        client,
        order_plan,
        preflight_blockers=[
            "okx_demo_nonflat_position_has_no_verified_protection"
        ],
    )

    with pytest.raises(
        OkxDemoPaperRuntimeError,
        match="okx_demo_exchange_hosted_protection_unconfirmed",
    ):
        controller._submit_order_plan(
            client,  # type: ignore[arg-type]
            snapshot=snapshot,
            decision=_p0_order_decision(),
            order_plan=order_plan,
        )

    status = controller.status()
    assert status["risk_control"]["mode"] == "RISK_REDUCING"
    assert status["runtime"]["opening_allowed"] is False
    assert status["risk_control"]["active_protection"] == {}


def test_private_ws_disconnect_uses_risk_reducing_when_write_and_ledger_trusted(
    tmp_path: Path,
) -> None:
    now = datetime.now(timezone.utc)
    controller = OkxDemoPaperRuntimeController(
        config=OkxDemoPaperRuntimeConfig(
            repo_root=Path.cwd(),
            data_db_path=tmp_path / "unused.sqlite",
            output_dir=tmp_path / "output" / "btc_demo_paper_runtime",
        ),
        credential_loader=lambda _: _credentials(),
        clock=lambda: now,
        start_worker=False,
    )
    controller._state["runtime"].update(
        {"active": True, "opening_allowed": True, "cancel_only": False}
    )
    controller._state["ledger_reconciliation"] = {
        "status": "reconciled",
        "current_state_exchange_snapshot_match": True,
    }
    controller._state["risk_control"]["write_path_trusted"] = True
    controller._state["risk_control"]["dead_man"].update(
        {"armed": True, "last_ack_utc": now.isoformat()}
    )

    controller._on_private_ws_disconnect("socket_closed")

    status = controller.status()
    assert status["risk_control"]["mode"] == "RISK_REDUCING"
    assert status["runtime"]["opening_allowed"] is False
    assert status["runtime"]["cancel_only"] is True


def test_private_ws_disconnect_freezes_when_order_outcome_is_unresolved(
    tmp_path: Path,
) -> None:
    controller, _, _ = _p0_order_controller(tmp_path)
    controller._state["risk_control"]["pending_order_intents"] = {
        "btcDPunknownws01": {
            "client_order_id": "btcDPunknownws01",
            "status": "unknown",
            "retry_without_query_allowed": False,
        }
    }

    controller._on_private_ws_disconnect("socket_closed")

    status = controller.status()
    assert status["risk_control"]["mode"] == "FROZEN_UNKNOWN"
    assert status["runtime"]["opening_allowed"] is False
    assert status["runtime"]["cancel_only"] is True


def test_dead_man_heartbeat_failure_freezes_and_emits_critical_alert(
    tmp_path: Path,
) -> None:
    controller = _controller(tmp_path, lambda _: _credentials())

    class RejectingDeadManClient:
        def cancel_all_after(self, **_payload: Any) -> OkxDemoResponse:
            return OkxDemoResponse(
                method="POST",
                path="/api/v5/trade/cancel-all-after",
                http_status=200,
                code="0",
                message="",
                data=({"sCode": "51000", "sMsg": "rejected"},),
            )

    controller._client = RejectingDeadManClient()  # type: ignore[assignment]
    controller._state["runtime"]["active"] = True
    controller._stop_event = StepStopEvent([False])

    controller._dead_man_loop()

    status = controller.status()
    assert status["risk_control"]["mode"] == "FROZEN_UNKNOWN"
    assert status["risk_control"]["write_path_trusted"] is False
    assert status["runtime"]["opening_allowed"] is False
    assert status["runtime"]["cancel_only"] is True
    assert status["risk_control"]["alerts"][0]["severity"] == "critical"


def test_dead_man_expiry_freezes_before_any_renewal_attempt(
    tmp_path: Path,
) -> None:
    now = datetime.now(timezone.utc)
    controller = OkxDemoPaperRuntimeController(
        config=OkxDemoPaperRuntimeConfig(
            repo_root=tmp_path,
            data_db_path=tmp_path / "missing.sqlite",
            output_dir=tmp_path / "output" / "btc_demo_paper_runtime",
        ),
        credential_loader=lambda _: _credentials(),
        clock=lambda: now,
        start_worker=False,
    )
    client = SnapshotClient()
    controller._client = client  # type: ignore[assignment]
    controller._state["runtime"]["active"] = True
    controller._state["risk_control"]["write_path_trusted"] = True
    controller._state["risk_control"]["dead_man"].update(
        {
            "armed": True,
            "last_ack_utc": (
                now
                - timedelta(
                    seconds=controller.config.dead_man_timeout_seconds + 1
                )
            ).isoformat(),
        }
    )
    controller._stop_event = StepStopEvent([False])

    controller._dead_man_loop()

    status = controller.status()
    assert client.dead_man_calls == []
    assert status["risk_control"]["mode"] == "FROZEN_UNKNOWN"
    assert status["risk_control"]["write_path_trusted"] is False
    assert "dead_man_expired" in status["runtime"]["last_error"]


def test_status_derives_fail_closed_from_stale_durable_liveness_without_writing(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 8, 5, 12, 0, tzinfo=timezone.utc)
    controller = OkxDemoPaperRuntimeController(
        config=OkxDemoPaperRuntimeConfig(
            repo_root=tmp_path,
            data_db_path=tmp_path / "missing.sqlite",
            output_dir=tmp_path / "output" / "btc_demo_paper_runtime",
        ),
        credential_loader=lambda _: _credentials(),
        clock=lambda: now,
        start_worker=False,
    )
    stale = now - timedelta(
        seconds=controller.config.dead_man_timeout_seconds + 1
    )
    controller._state["runtime"].update(
        {
            "active": True,
            "status": "running",
            "opening_allowed": True,
            "cancel_only": False,
                "last_heartbeat_utc": stale.isoformat(),
                "authoritative_liveness_required": True,
                "authoritative_liveness_worker_required": True,
        }
    )
    controller._state["risk_control"].update(
        {"mode": "RUNNING", "write_path_trusted": True}
    )
    controller._state["risk_control"]["dead_man"].update(
        {
            "armed": True,
            "last_ack_utc": stale.isoformat(),
            "heartbeat_thread_alive": True,
            "watchdog_renews_dead_man": True,
            "renewal_owner": {"nonce": "test-owner"},
        }
    )
    controller._persist_state()
    checkpoint = (controller.config.output_dir / "state.json").read_bytes()

    status = controller.status()

    assert status["runtime"]["opening_allowed"] is False
    assert status["runtime"]["cancel_only"] is True
    assert status["risk_control"]["mode"] == "FROZEN_UNKNOWN"
    assert "okx_demo_authoritative_liveness_dead_man_ack_stale" in (
        status["runtime"]["blockers"]
    )
    assert (controller.config.output_dir / "state.json").read_bytes() == checkpoint


def test_fault_drill_without_worker_accepts_fresh_dead_man_despite_stale_worker_heartbeat(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 8, 12, 8, 0, tzinfo=timezone.utc)
    controller = OkxDemoPaperRuntimeController(
        config=OkxDemoPaperRuntimeConfig(
            repo_root=tmp_path,
            data_db_path=tmp_path / "missing.sqlite",
            output_dir=tmp_path / "output" / "btc_demo_paper_runtime",
        ),
        credential_loader=lambda _: _credentials(),
        clock=lambda: now,
        start_worker=False,
    )

    class AliveDeadManThread:
        def is_alive(self) -> bool:
            return True

    stale = now - timedelta(seconds=controller.config.dead_man_timeout_seconds + 1)
    runtime = controller._state["runtime"]
    runtime.update(
        {
            "active": True,
            "last_heartbeat_utc": stale.isoformat(),
            "authoritative_liveness_required": True,
            "authoritative_liveness_worker_required": False,
            "authoritative_liveness_epoch": 3,
            "worker_alive": False,
        }
    )
    controller._state["risk_control"]["write_path_trusted"] = True
    controller._state["risk_control"]["dead_man"].update(
        {
            "armed": True,
            "last_ack_utc": now.isoformat(),
            "heartbeat_thread_alive": True,
            "watchdog_renews_dead_man": True,
            "renewal_owner": controller._authoritative_renewal_owner(epoch=3),
        }
    )
    controller._dead_man_thread = AliveDeadManThread()  # type: ignore[assignment]

    blockers = controller._authoritative_liveness_blockers(
        controller._state,
        worker_alive=False,
        dead_man_thread_alive=True,
    )

    assert "okx_demo_authoritative_liveness_worker_heartbeat_stale" not in blockers
    assert "okx_demo_authoritative_liveness_worker_dead" not in blockers
    assert blockers == []
    assert controller._write_path_is_trusted() is True


def test_worker_required_liveness_rejects_progress_older_than_bounded_timeout(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 8, 12, 8, 0, tzinfo=timezone.utc)
    controller = OkxDemoPaperRuntimeController(
        config=OkxDemoPaperRuntimeConfig(
            repo_root=tmp_path,
            data_db_path=tmp_path / "missing.sqlite",
            output_dir=tmp_path / "output" / "btc_demo_paper_runtime",
        ),
        credential_loader=lambda _: _credentials(),
        clock=lambda: now,
        start_worker=False,
    )
    stale = now - timedelta(seconds=121)
    controller._state["runtime"].update(
        {
            "active": True,
            "last_heartbeat_utc": stale.isoformat(),
            "authoritative_liveness_required": True,
            "authoritative_liveness_worker_required": True,
            "authoritative_liveness_epoch": 4,
        }
    )
    controller._state["risk_control"]["dead_man"].update(
        {
            "armed": True,
            "last_ack_utc": now.isoformat(),
            "heartbeat_thread_alive": True,
            "watchdog_renews_dead_man": True,
            "renewal_owner": controller._authoritative_renewal_owner(epoch=4),
        }
    )

    blockers = controller._authoritative_liveness_blockers(
        controller._state,
        worker_alive=True,
        dead_man_thread_alive=True,
    )

    assert "okx_demo_authoritative_liveness_worker_heartbeat_stale" in blockers


@pytest.mark.parametrize(
    ("failure", "expected_blocker"),
    [
        ("ack", "okx_demo_authoritative_liveness_dead_man_ack_stale"),
        ("thread", "okx_demo_authoritative_liveness_renewal_thread_dead"),
        ("owner", "okx_demo_authoritative_liveness_renewal_owner_mismatch"),
    ],
)
def test_fault_drill_without_worker_keeps_every_dead_man_liveness_guard(
    tmp_path: Path,
    failure: str,
    expected_blocker: str,
) -> None:
    now = datetime(2026, 8, 12, 8, 0, tzinfo=timezone.utc)
    controller = OkxDemoPaperRuntimeController(
        config=OkxDemoPaperRuntimeConfig(
            repo_root=tmp_path,
            data_db_path=tmp_path / "missing.sqlite",
            output_dir=tmp_path / "output" / "btc_demo_paper_runtime",
        ),
        credential_loader=lambda _: _credentials(),
        clock=lambda: now,
        start_worker=False,
    )
    stale = now - timedelta(seconds=controller.config.dead_man_timeout_seconds + 1)
    controller._state["runtime"].update(
        {
            "active": True,
            "last_heartbeat_utc": stale.isoformat(),
            "authoritative_liveness_required": True,
            "authoritative_liveness_worker_required": False,
            "authoritative_liveness_epoch": 5,
        }
    )
    owner = controller._authoritative_renewal_owner(epoch=5)
    if failure == "owner":
        owner["nonce"] = "stale-owner"
    controller._state["risk_control"]["dead_man"].update(
        {
            "armed": True,
            "last_ack_utc": (
                stale if failure == "ack" else now
            ).isoformat(),
            "heartbeat_thread_alive": failure != "thread",
            "watchdog_renews_dead_man": True,
            "renewal_owner": owner,
        }
    )

    blockers = controller._authoritative_liveness_blockers(
        controller._state,
        worker_alive=False,
        dead_man_thread_alive=failure != "thread",
    )

    assert expected_blocker in blockers
    assert "okx_demo_authoritative_liveness_worker_heartbeat_stale" not in blockers


def test_fault_drill_dead_man_loop_renews_without_worker_heartbeat(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 8, 12, 8, 0, tzinfo=timezone.utc)
    controller = OkxDemoPaperRuntimeController(
        config=OkxDemoPaperRuntimeConfig(
            repo_root=tmp_path,
            data_db_path=tmp_path / "missing.sqlite",
            output_dir=tmp_path / "output" / "btc_demo_paper_runtime",
        ),
        credential_loader=lambda _: _credentials(),
        clock=lambda: now,
        start_worker=False,
    )
    client = SnapshotClient()

    class AliveDeadManThread:
        def is_alive(self) -> bool:
            return True

    stale = now - timedelta(seconds=controller.config.dead_man_timeout_seconds + 1)
    controller._client = client  # type: ignore[assignment]
    controller._state["runtime"].update(
        {
            "active": True,
            "last_heartbeat_utc": stale.isoformat(),
            "authoritative_liveness_required": True,
            "authoritative_liveness_worker_required": False,
            "authoritative_liveness_epoch": 6,
        }
    )
    controller._state["risk_control"]["write_path_trusted"] = True
    controller._state["risk_control"]["dead_man"].update(
        {
            "armed": True,
            "last_ack_utc": now.isoformat(),
            "heartbeat_thread_alive": True,
            "watchdog_renews_dead_man": True,
            "renewal_owner": controller._authoritative_renewal_owner(epoch=6),
        }
    )
    controller._dead_man_thread = AliveDeadManThread()  # type: ignore[assignment]
    controller._stop_event = StepStopEvent([False, True])

    controller._dead_man_loop()

    assert len(client.dead_man_calls) == 1
    assert controller._state["risk_control"]["dead_man"]["last_error"] != (
        "okx_demo_dead_man_expired_before_renewal"
    )
    assert controller._state["risk_control"]["write_path_trusted"] is False


def test_transient_recovery_restarts_exactly_one_worker_after_authority_recovers(
    tmp_path: Path,
) -> None:
    """A stopped worker must be recreated only after the authority gates pass."""

    now = datetime(2026, 8, 21, 8, 0, tzinfo=timezone.utc)
    client = SnapshotClient(server_time_ms=str(int(now.timestamp() * 1000)))
    controller = OkxDemoPaperRuntimeController(
        config=OkxDemoPaperRuntimeConfig(
            repo_root=Path.cwd(),
            data_db_path=tmp_path / "missing.sqlite",
            output_dir=tmp_path / "output" / "btc_demo_paper_runtime",
        ),
        credential_loader=lambda _: _credentials(),
        clock=lambda: now,
        start_worker=True,
    )
    controller._client = client  # type: ignore[assignment]
    controller._private_ws = CurrentPrivateWS()
    controller._dead_man_thread = _AliveHandle()  # type: ignore[assignment]
    controller._state["runtime"].update(
        {
            "run_id": "transient-recovery-worker-01",
            "active": True,
            "status": "cancel_only",
            "opening_allowed": False,
            "cancel_only": True,
            "authoritative_liveness_required": True,
            "authoritative_liveness_worker_required": True,
            "authoritative_liveness_epoch": 1,
        }
    )
    controller._state["risk_control"].update(
        {"mode": "FROZEN_UNKNOWN", "write_path_trusted": False}
    )

    def commit_ledger_reconciliation(
        *,
        snapshot: Mapping[str, Any],
        trigger: str,
        order_record: Mapping[str, Any] | None = None,
        apply_snapshot: bool = True,
    ) -> None:
        del order_record, apply_snapshot
        controller._state["ledger_reconciliation"] = {
            "status": "reconciled",
            "trigger": trigger,
            "current_state_exchange_snapshot_match": True,
            "funding_cashflow_reconciled": True,
            "promotion_evidence_ready": False,
        }
        controller._state["exchange"] = json.loads(json.dumps(dict(snapshot)))

    controller._commit_ledger_reconciliation = (  # type: ignore[method-assign]
        commit_ledger_reconciliation
    )

    def arm_dead_man(
        _client: SnapshotClient,
        *,
        trigger: str,
        snapshot: Mapping[str, Any] | None = None,
    ) -> None:
        del _client, trigger, snapshot
        controller._state["risk_control"]["dead_man"].update(
            {
                "armed": True,
                "last_ack_utc": now.isoformat(),
                "heartbeat_thread_alive": True,
                "watchdog_renews_dead_man": True,
                "renewal_owner": controller._authoritative_renewal_owner(epoch=1),
                "last_error": "",
            }
        )
        controller._state["risk_control"]["write_path_trusted"] = True

    controller._arm_dead_man = arm_dead_man  # type: ignore[method-assign]
    controller._boundary_snapshot_requires_refresh = (  # type: ignore[method-assign]
        lambda _snapshot: False
    )
    worker_started = threading.Event()
    worker_release = threading.Event()

    def worker() -> None:
        controller._state["runtime"]["last_heartbeat_utc"] = now.isoformat()
        worker_started.set()
        worker_release.wait(2)

    controller._worker_loop = worker  # type: ignore[method-assign]
    controller._recover_transient_cycle()

    assert worker_started.wait(1)
    assert controller._state["runtime"]["worker_generation"] == 1
    assert controller._state["runtime"]["worker_recovery"]["status"] == "recovered"
    assert controller._state["runtime"]["opening_allowed"] is True
    assert controller._state["runtime"]["cancel_only"] is False
    assert client.order_calls == []
    assert client.cancel_calls == []

    worker_release.set()
    controller._stop_event.set()
    assert controller._thread is not None
    controller._thread.join(1)


def test_dead_man_50011_uses_bounded_recovery_and_clears_historical_latch(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 8, 21, 8, 0, tzinfo=timezone.utc)
    client = _TransientDeadManClient(
        server_time_ms=str(int(now.timestamp() * 1000))
    )
    controller = OkxDemoPaperRuntimeController(
        config=OkxDemoPaperRuntimeConfig(
            repo_root=Path.cwd(),
            data_db_path=tmp_path / "missing.sqlite",
            output_dir=tmp_path / "output" / "btc_demo_paper_runtime",
        ),
        credential_loader=lambda _: _credentials(),
        clock=lambda: now,
        start_worker=False,
    )
    controller._client = client  # type: ignore[assignment]
    controller._dead_man_thread = _AliveHandle()  # type: ignore[assignment]
    controller._state["runtime"].update(
        {
            "run_id": "transient-recovery-deadman-01",
            "active": True,
            "status": "running",
            "opening_allowed": True,
            "cancel_only": False,
            "authoritative_liveness_required": True,
            "authoritative_liveness_worker_required": False,
            "authoritative_liveness_epoch": 1,
        }
    )
    controller._state["risk_control"].update(
        {
            "mode": "RUNNING",
            "write_path_trusted": True,
            "dead_man": {
                "armed": True,
                "last_ack_utc": now.isoformat(),
                "heartbeat_thread_alive": True,
                "watchdog_renews_dead_man": True,
                "renewal_owner": controller._authoritative_renewal_owner(epoch=1),
                "last_error": "",
                "tag": "btcP0Demo",
                "timeout_seconds": 30,
            },
        }
    )
    recovery_calls: list[bool] = []

    def recover(*, resume_opening: bool = True) -> None:
        recovery_calls.append(resume_opening)
        controller._renew_dead_man_once(client)  # type: ignore[arg-type]
        controller._stop_event.set()

    controller._recover_transient_cycle = recover  # type: ignore[method-assign]
    controller._stop_event = StepStopEvent([False, False])

    controller._dead_man_loop()

    assert recovery_calls == [True]
    assert len(client.dead_man_calls) == 2
    assert client.order_calls == []
    assert client.cancel_calls == []
    assert controller._state["risk_control"]["dead_man"]["last_error"] == ""


def test_transient_recovery_keeps_cancel_only_when_private_ws_authority_is_incomplete(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 8, 21, 8, 0, tzinfo=timezone.utc)
    client = SnapshotClient(server_time_ms=str(int(now.timestamp() * 1000)))

    class BlockedPrivateWS(CurrentPrivateWS):
        def reconcile_current(self) -> dict[str, Any]:
            return {
                "connected": False,
                "listener_alive": False,
                "opening_allowed_after_reconciliation": False,
                "blockers": ["private_ws_reconnect_unavailable"],
            }

    controller = OkxDemoPaperRuntimeController(
        config=OkxDemoPaperRuntimeConfig(
            repo_root=Path.cwd(),
            data_db_path=tmp_path / "missing.sqlite",
            output_dir=tmp_path / "output" / "btc_demo_paper_runtime",
        ),
        credential_loader=lambda _: _credentials(),
        clock=lambda: now,
        start_worker=True,
    )
    controller._client = client  # type: ignore[assignment]
    controller._private_ws = BlockedPrivateWS()
    controller._state["runtime"].update(
        {
            "active": True,
            "status": "cancel_only",
            "opening_allowed": False,
            "cancel_only": True,
            "authoritative_liveness_required": True,
            "authoritative_liveness_worker_required": True,
            "authoritative_liveness_epoch": 1,
        }
    )

    with pytest.raises(OkxDemoPaperRuntimeError):
        controller._recover_transient_cycle()

    assert controller._thread is None
    assert controller._state["runtime"]["worker_generation"] == 0
    assert controller._state["runtime"]["opening_allowed"] is False
    assert controller._state["runtime"]["cancel_only"] is True
    assert client.order_calls == []
    assert client.cancel_calls == []


def test_worker_liveness_progress_is_persisted_before_loop_exits(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 8, 5, 12, 0, tzinfo=timezone.utc)
    controller = OkxDemoPaperRuntimeController(
        config=OkxDemoPaperRuntimeConfig(
            repo_root=tmp_path,
            data_db_path=tmp_path / "missing.sqlite",
            output_dir=tmp_path / "output" / "btc_demo_paper_runtime",
        ),
        credential_loader=lambda _: _credentials(),
        clock=lambda: now,
        start_worker=False,
    )
    controller._state["runtime"].update(
        {"active": True, "last_heartbeat_utc": ""}
    )
    controller._persist_state()
    controller.run_cycle = lambda: controller._state["runtime"].update(  # type: ignore[method-assign]
        {"last_heartbeat_utc": now.isoformat()}
    )
    controller._stop_event = StepStopEvent([True])

    controller._worker_loop()

    recovered = BTCRuntimeStore(controller.config.output_dir).recover()
    assert not recovered.blockers
    assert recovered.state["runtime"]["last_heartbeat_utc"] == now.isoformat()
    assert recovered.state["runtime"]["worker_alive"] is False


def test_status_event_projection_deduplicates_event_identity_in_order(
    tmp_path: Path,
) -> None:
    controller = _controller(tmp_path, lambda _: _credentials())
    controller._state["events"] = [
        {
            "event_id": "same-event",
            "timestamp_utc": "2026-08-05T12:00:00+00:00",
            "event_type": "first",
            "payload": {"sequence": 1},
        },
        {
            "event_id": "same-event",
            "timestamp_utc": "2026-08-05T12:00:01+00:00",
            "event_type": "duplicate",
            "payload": {"sequence": 2},
        },
        {
            "event_id": "later-event",
            "timestamp_utc": "2026-08-05T12:00:02+00:00",
            "event_type": "later",
            "payload": {"sequence": 3},
        },
    ]

    assert [event["event_id"] for event in controller.status()["events"]] == [
        "same-event",
        "later-event",
    ]


@pytest.mark.parametrize("mismatch", ("owner", "epoch", "thread"))
def test_authoritative_liveness_mismatch_never_restores_old_ack(
    tmp_path: Path,
    mismatch: str,
) -> None:
    now = datetime(2026, 8, 5, 12, 0, tzinfo=timezone.utc)
    controller = OkxDemoPaperRuntimeController(
        config=OkxDemoPaperRuntimeConfig(
            repo_root=tmp_path,
            data_db_path=tmp_path / "missing.sqlite",
            output_dir=tmp_path / "output" / "btc_demo_paper_runtime",
        ),
        credential_loader=lambda _: _credentials(),
        clock=lambda: now,
        start_worker=False,
    )
    runtime = controller._state["runtime"]
    runtime.update(
        {
            "active": True,
            "status": "running",
            "opening_allowed": True,
            "cancel_only": False,
            "last_heartbeat_utc": now.isoformat(),
            "authoritative_liveness_required": True,
            "authoritative_liveness_worker_required": False,
            "authoritative_liveness_epoch": 7,
        }
    )
    owner = controller._authoritative_renewal_owner(epoch=7)
    if mismatch == "owner":
        owner["nonce"] = "old-owner"
    elif mismatch == "epoch":
        owner["epoch"] = 6
    controller._state["risk_control"].update(
        {"mode": "RUNNING", "write_path_trusted": True}
    )
    controller._state["risk_control"]["dead_man"].update(
        {
            "armed": True,
            "last_ack_utc": now.isoformat(),
            "heartbeat_thread_alive": mismatch != "thread",
            "watchdog_renews_dead_man": True,
            "renewal_owner": owner,
        }
    )
    controller._stop_event = StepStopEvent([False])

    controller._dead_man_loop()

    recovered = BTCRuntimeStore(controller.config.output_dir).recover()
    assert not recovered.blockers
    assert recovered.state["runtime"]["opening_allowed"] is False
    assert recovered.state["runtime"]["cancel_only"] is True
    assert recovered.state["risk_control"]["mode"] == "FROZEN_UNKNOWN"
    assert recovered.state["risk_control"]["write_path_trusted"] is False


@pytest.mark.parametrize("failure", ("event", "checkpoint"))
def test_dead_man_ack_event_or_checkpoint_failure_stays_frozen(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    now = datetime(2026, 8, 5, 12, 0, tzinfo=timezone.utc)
    controller = OkxDemoPaperRuntimeController(
        config=OkxDemoPaperRuntimeConfig(
            repo_root=tmp_path,
            data_db_path=tmp_path / "missing.sqlite",
            output_dir=tmp_path / "output" / "btc_demo_paper_runtime",
        ),
        credential_loader=lambda _: _credentials(),
        clock=lambda: now,
        start_worker=False,
    )
    controller._state["runtime"]["active"] = True
    original_persist = controller._persist_state
    controller._persist_state()
    calls = 0

    def fail_ack_checkpoint() -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("checkpoint interrupted")
        original_persist()

    if failure == "event":
        def fail_ack_event(*_args: Any, **_kwargs: Any) -> None:
            raise OSError("event append interrupted")

        monkeypatch.setattr(controller, "_append_event", fail_ack_event)
    else:
        monkeypatch.setattr(controller, "_persist_state", fail_ack_checkpoint)

    with pytest.raises(
        OkxDemoPaperRuntimeError,
        match="okx_demo_dead_man_ack_persistence_failed",
    ):
        controller._arm_dead_man(SnapshotClient(), trigger="heartbeat")

    recovered = BTCRuntimeStore(controller.config.output_dir).recover()
    assert not recovered.blockers
    assert recovered.state["runtime"]["opening_allowed"] is False
    assert recovered.state["runtime"]["cancel_only"] is True
    assert recovered.state["risk_control"]["write_path_trusted"] is False


def test_repeated_dead_man_ack_and_status_preserve_event_chain_bytes(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 8, 5, 12, 0, tzinfo=timezone.utc)
    controller = OkxDemoPaperRuntimeController(
        config=OkxDemoPaperRuntimeConfig(
            repo_root=tmp_path,
            data_db_path=tmp_path / "missing.sqlite",
            output_dir=tmp_path / "output" / "btc_demo_paper_runtime",
        ),
        credential_loader=lambda _: _credentials(),
        clock=lambda: now,
        start_worker=False,
    )
    client = SnapshotClient()

    controller._arm_dead_man(client, trigger="heartbeat")
    state_path = controller.config.output_dir / "state.json"
    events_path = controller.config.output_dir / "events.jsonl"
    first_state = state_path.read_bytes()
    first_events = events_path.read_bytes()
    first_status = controller.status()
    second_status = controller.status()
    controller._arm_dead_man(client, trigger="heartbeat")

    assert first_status["events"] == second_status["events"]
    assert state_path.read_bytes() == first_state
    assert events_path.read_bytes() == first_events
    assert len(controller.status()["events"]) == 1


def test_dead_man_empty_ack_never_marks_write_path_trusted(
    tmp_path: Path,
) -> None:
    controller = _controller(tmp_path, lambda _: _credentials())

    class EmptyAckClient:
        def cancel_all_after(self, **_payload: Any) -> OkxDemoResponse:
            return OkxDemoResponse(
                method="POST",
                path="/api/v5/trade/cancel-all-after",
                http_status=200,
                code="0",
                message="",
                data=(),
            )

    with pytest.raises(
        OkxDemoPaperRuntimeError,
        match="okx_demo_dead_man_heartbeat_rejected",
    ):
        controller._arm_dead_man(  # type: ignore[arg-type]
            EmptyAckClient(),
            trigger="test",
        )

    status = controller.status()
    assert status["risk_control"]["write_path_trusted"] is False
    assert status["risk_control"]["dead_man"]["armed"] is False


@pytest.mark.parametrize(
    "intent_status",
    ("terminal", "rejected", "canceled", "cancelled"),
)
def test_dead_man_disarms_only_for_exact_terminal_durable_intent_statuses(
    tmp_path: Path,
    intent_status: str,
) -> None:
    controller, _, _ = _p0_order_controller(tmp_path)
    client = SnapshotClient()
    controller._state["exchange"].update(
        {"positions": [], "pending_orders": [], "pending_algo_orders": []}
    )
    controller._state["risk_control"]["active_protection"] = {}
    controller._state["risk_control"]["pending_order_intents"] = {
        "btcDPopen0003": {"status": intent_status}
    }

    blockers = controller._disarm_dead_man_if_safe(
        client,  # type: ignore[arg-type]
        stop_query_current=True,
    )

    assert blockers == []
    assert client.dead_man_calls[-1]["timeout_seconds"] == 0
    assert controller.status()["risk_control"]["dead_man"]["armed"] is False


@pytest.mark.parametrize(
    ("case", "intent_record"),
    (
        ("missing_status", {}),
        ("empty_status", {"status": ""}),
        ("malformed_record", ["not", "a", "mapping"]),
        ("future_unknown", {"status": "terminal_v2"}),
        ("known_unresolved", {"status": "accepted"}),
    ),
)
def test_dead_man_disarm_blocks_every_non_whitelisted_durable_intent(
    tmp_path: Path,
    case: str,
    intent_record: Any,
) -> None:
    del case
    controller, _, _ = _p0_order_controller(tmp_path)
    client = SnapshotClient()
    controller._state["exchange"].update(
        {"positions": [], "pending_orders": [], "pending_algo_orders": []}
    )
    controller._state["risk_control"]["active_protection"] = {}
    controller._state["risk_control"]["pending_order_intents"] = {
        "btcDPopen0003": intent_record
    }

    blockers = controller._disarm_dead_man_if_safe(
        client,  # type: ignore[arg-type]
        stop_query_current=True,
    )

    assert blockers == [
        "okx_demo_dead_man_remains_armed_stop_state_not_proven_safe"
    ]
    assert client.dead_man_calls == []
    assert controller.status()["risk_control"]["dead_man"]["armed"] is True


@pytest.mark.parametrize(
    "unsafe_stop_state",
    ("pending_algo", "active_protection", "history_unknown", "cleanup_timeout"),
)
def test_stop_never_disarms_or_claims_clean_when_algo_state_is_not_terminal_current(
    tmp_path: Path,
    unsafe_stop_state: str,
) -> None:
    controller = _controller(tmp_path, lambda _: _credentials())
    client = SnapshotClient()
    controller._client = client  # type: ignore[assignment]
    controller._state["runtime"]["active"] = True
    controller._state["risk_control"]["dead_man"].update(
        {"armed": True, "last_ack_utc": datetime.now(timezone.utc).isoformat()}
    )
    controller._state["risk_control"]["write_path_trusted"] = True
    controller._state["ledger_reconciliation"].update(
        {
            "status": "reconciled",
            "current_state_exchange_snapshot_match": True,
        }
    )
    pending = _algo_snapshot(
        contracts="0",
        algo_id="owned1",
        algo_client_id="ownedAlgo1",
    )
    empty = {"positions": [], "pending_orders": [], "pending_algo_orders": []}
    controller._collect_exchange_snapshot = lambda _client: (  # type: ignore[method-assign]
        pending if unsafe_stop_state != "active_protection" else empty
    )
    controller._commit_ledger_reconciliation = lambda **_kwargs: controller._state[  # type: ignore[method-assign]
        "ledger_reconciliation"
    ].update(
        {
            "status": "reconciled",
            "current_state_exchange_snapshot_match": True,
        }
    )
    if unsafe_stop_state == "active_protection":
        controller._state["risk_control"]["active_protection"] = {
            "algo_id": "owned1",
            "algo_client_order_id": "ownedAlgo1",
        }
        controller._cleanup_owned_flat_algos = lambda *_args, **_kwargs: (  # type: ignore[method-assign]
            empty,
            {},
        )
    elif unsafe_stop_state == "pending_algo":
        controller._cleanup_owned_flat_algos = lambda *_args, **_kwargs: (  # type: ignore[method-assign]
            pending,
            {},
        )
    else:
        error = (
            "okx_demo_fault_drill_cancel_algos_history_not_terminal"
            if unsafe_stop_state == "history_unknown"
            else "okx_demo_fault_drill_cancel_algos_readback_timeout_unknown"
        )
        controller._cleanup_owned_flat_algos = lambda *_args, **_kwargs: (  # type: ignore[method-assign]
            (_ for _ in ()).throw(OkxDemoPaperRuntimeError(error))
        )

    stopped = controller.stop(
        {"confirmation_text": OKX_DEMO_PAPER_CONFIRMATION}
    )

    assert client.dead_man_calls == []
    assert stopped["runtime"]["status"] == "frozen_unknown_stop_incomplete"
    assert stopped["risk_control"]["mode"] == "FROZEN_UNKNOWN"
    assert stopped["risk_control"]["dead_man"]["armed"] is True


def test_stop_disarms_only_after_algo_cleanup_and_query_current_ledger_commit(
    tmp_path: Path,
) -> None:
    controller = _controller(tmp_path, lambda _: _credentials())
    client = SnapshotClient()
    controller._client = client  # type: ignore[assignment]
    controller._state["runtime"]["active"] = True
    controller._state["risk_control"]["dead_man"].update(
        {"armed": True, "last_ack_utc": datetime.now(timezone.utc).isoformat()}
    )
    controller._state["risk_control"]["write_path_trusted"] = True
    controller._state["ledger_reconciliation"].update(
        {
            "status": "reconciled",
            "current_state_exchange_snapshot_match": True,
        }
    )
    pending = _algo_snapshot(
        contracts="0",
        algo_id="owned1",
        algo_client_id="ownedAlgo1",
    )
    empty = {"positions": [], "pending_orders": [], "pending_algo_orders": []}
    controller._collect_exchange_snapshot = lambda _client: pending  # type: ignore[method-assign]

    def cleanup(*_args: Any, **_kwargs: Any) -> tuple[dict[str, Any], dict[str, Any]]:
        controller._state["risk_control"]["active_protection"] = {}
        return empty, {"history_terminal_verified": True}

    controller._cleanup_owned_flat_algos = cleanup  # type: ignore[method-assign]
    commit_triggers: list[str] = []

    def commit(**kwargs: Any) -> None:
        commit_triggers.append(str(kwargs["trigger"]))
        controller._state["ledger_reconciliation"].update(
            {
                "status": "reconciled",
                "current_state_exchange_snapshot_match": True,
            }
        )

    controller._commit_ledger_reconciliation = commit  # type: ignore[method-assign]

    stopped = controller.stop(
        {"confirmation_text": OKX_DEMO_PAPER_CONFIRMATION}
    )

    assert commit_triggers == ["runtime_stop_query_current"]
    assert client.dead_man_calls[-1]["timeout_seconds"] == 0
    assert stopped["runtime"]["status"] == "stopped"
    assert stopped["risk_control"]["dead_man"]["armed"] is False


@pytest.mark.parametrize(
    "cycle_error",
    [
        OkxDemoPaperRuntimeError("okx_demo_paper_ticker_failed:50001"),
        OkxDemoTransportError("URLError"),
    ],
)
def test_worker_recovers_transient_cycle_and_continues_after_full_reconciliation(
    tmp_path: Path,
    cycle_error: Exception,
) -> None:
    controller = OkxDemoPaperRuntimeController(
        config=OkxDemoPaperRuntimeConfig(
            repo_root=Path.cwd(),
            data_db_path=tmp_path / "unused.sqlite",
            output_dir=tmp_path / "output" / "btc_demo_paper_runtime",
        ),
        credential_loader=lambda _: _credentials(),
        start_worker=False,
    )
    private_ws = CurrentPrivateWS()
    client = _install_full_recovery_evidence_stubs(controller)
    controller._private_ws = private_ws
    controller._state["runtime"].update(
        {"active": True, "opening_allowed": True, "cancel_only": False}
    )
    controller._state["strategy"] = {"strategy_id": "fixture"}
    controller._stop_event = StepStopEvent([False, True])
    snapshots = [
        cycle_error,
        {"captured_at_utc": datetime.now(timezone.utc).isoformat()},
    ]

    def collect(_client: object) -> dict[str, Any]:
        value = snapshots.pop(0)
        if isinstance(value, Exception):
            raise value
        return value

    controller._collect_exchange_snapshot = collect
    controller._preflight_blockers = lambda _snapshot, require_flat: []
    controller._worker_loop()

    status = controller.status()
    assert private_ws.reconcile_calls == 1
    assert status["runtime"]["active"] is True
    assert status["runtime"]["cancel_only"] is False
    assert status["runtime"]["opening_allowed"] is True
    assert status["runtime"]["last_heartbeat_utc"]
    assert len(client.dead_man_calls) == 1
    assert not any(
        str(blocker).startswith("okx_demo_transient:")
        for blocker in status["runtime"]["blockers"]
    )


def test_fault_drill_reconnect_recovery_remains_reduce_only_after_full_caa(
    tmp_path: Path,
) -> None:
    controller = OkxDemoPaperRuntimeController(
        config=OkxDemoPaperRuntimeConfig(
            repo_root=Path.cwd(),
            data_db_path=tmp_path / "unused.sqlite",
            output_dir=tmp_path / "output" / "btc_demo_paper_runtime",
        ),
        credential_loader=lambda _: _credentials(),
        start_worker=False,
    )
    controller._private_ws = CurrentPrivateWS()
    _install_full_recovery_evidence_stubs(controller)
    controller._state["runtime"].update(
        {"active": True, "opening_allowed": False, "cancel_only": True}
    )
    controller._state["risk_control"]["mode"] = "RISK_REDUCING"
    controller._collect_exchange_snapshot = lambda _client: {  # type: ignore[method-assign]
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "positions": [{"position_side": "long", "contracts": "0.01"}],
        "pending_orders": [],
        "pending_algo_orders": [],
    }
    controller._preflight_blockers = lambda *_args, **_kwargs: []  # type: ignore[method-assign]

    controller._recover_transient_cycle(resume_opening=False)

    status = controller.status()
    assert status["risk_control"]["mode"] == "RISK_REDUCING"
    assert status["runtime"]["opening_allowed"] is False
    assert status["runtime"]["cancel_only"] is True


def test_attached_oco_identity_is_durable_before_parent_order_post(
    tmp_path: Path,
) -> None:
    controller, snapshot, order_plan = _p0_order_controller(tmp_path)
    client = OrderScenarioClient()
    _install_order_followup(controller, client, order_plan)
    observed: list[dict[str, Any]] = []

    def before_submit(order: Mapping[str, Any]) -> None:
        algo_client_id = str(order["attachAlgoOrds"][0]["attachAlgoClOrdId"])
        observed.append(
            dict(
                controller._state["risk_control"]["owned_attached_algos"][
                    algo_client_id
                ]
            )
        )

    client.before_submit = before_submit
    controller._submit_order_plan(
        client,  # type: ignore[arg-type]
        snapshot=snapshot,
        decision=_p0_order_decision(),
        order_plan=order_plan,
    )

    assert observed == [
        {
            "algo_client_order_id": order_plan["attached_protection"][
                "attachAlgoClOrdId"
            ],
            "parent_client_order_id": order_plan["client_order_id"],
            "instrument_id": "BTC-USDT-SWAP",
            "opening_intent": True,
            "status": "submit_pending",
        }
    ]


def test_startup_monitoring_failure_prevents_dead_man_arm(
    tmp_path: Path,
) -> None:
    FakePrivateWS.instances.clear()
    client = SnapshotClient()
    clock = lambda: datetime(1970, 1, 1, 0, 0, 0, 1000, tzinfo=timezone.utc)

    class FailingMonitoringPrivateWS(FakePrivateWS):
        def start_monitoring(self) -> None:
            self.monitoring_started = True
            raise RuntimeError("listener_start_failed_after_arm")

    controller = OkxDemoPaperRuntimeController(
        config=OkxDemoPaperRuntimeConfig(
            repo_root=Path.cwd(),
            data_db_path=tmp_path / "unused.sqlite",
            output_dir=tmp_path / "output" / "btc_demo_paper_runtime",
        ),
        credential_loader=lambda _: _credentials(),
        client_factory=lambda _config, _credentials_value: client,
        private_ws_factory=FailingMonitoringPrivateWS,
        clock=clock,
        start_worker=False,
    )
    controller._signal_decision = lambda _strategy, **_kwargs: {
        "signal": "flat",
        "target_contracts": "0",
        "decision_bar_close_utc": clock().isoformat(),
    }

    with pytest.raises(
        OkxDemoPaperRuntimeError,
        match="listener_start_failed_after_arm",
    ):
        controller.start(_valid_start_payload())

    status = controller.status()
    assert client.dead_man_calls == []
    assert FakePrivateWS.instances[0].stopped is True
    assert status["runtime"]["active"] is False
    assert status["runtime"]["status"] == "start_blocked_fail_closed"
    assert status["risk_control"]["dead_man"]["armed"] is False
    assert status["risk_control"]["dead_man"][
        "heartbeat_thread_alive"
    ] is False
    assert controller._fault_drill_lock_handle is None


@pytest.mark.parametrize(
    "leverage_rows",
    (
        [
            {
                "instrument_id": "BTC-USDT-SWAP",
                "position_side": "long",
                "margin_mode": "isolated",
                "leverage": "2",
            },
            {
                "instrument_id": "BTC-USDT-SWAP",
                "position_side": "short",
                "margin_mode": "isolated",
                "leverage": "3",
            },
        ],
        [
            {
                "instrument_id": "BTC-USDT-SWAP",
                "position_side": "long",
                "margin_mode": "isolated",
                "leverage": "3",
            }
        ],
    ),
)
def test_preflight_requires_exact_isolated_three_x_for_long_and_short_before_post(
    tmp_path: Path,
    leverage_rows: list[dict[str, Any]],
) -> None:
    now = datetime(1970, 1, 1, 0, 0, 0, 1000, tzinfo=timezone.utc)
    controller = OkxDemoPaperRuntimeController(
        config=OkxDemoPaperRuntimeConfig(
            repo_root=tmp_path,
            data_db_path=tmp_path / "unused.sqlite",
            output_dir=tmp_path / "output" / "btc_demo_paper_runtime",
        ),
        credential_loader=lambda _: _credentials(),
        clock=lambda: now,
        start_worker=False,
    )
    snapshot = controller._collect_exchange_snapshot(SnapshotClient())  # type: ignore[arg-type]
    snapshot["leverage"] = leverage_rows

    blockers = controller._preflight_blockers(snapshot, require_flat=True)

    assert "okx_demo_paper_exact_isolated_3x_leverage_required" in blockers


def test_mixed_owned_and_unknown_flat_oco_cancels_none(tmp_path: Path) -> None:
    controller = _repo_controller(tmp_path, lambda _: _credentials())
    client = AlgoCleanupClient()
    controller._state["risk_control"]["owned_attached_algos"] = {
        "ownedAlgo1": {
            "algo_id": "owned1",
            "algo_client_order_id": "ownedAlgo1",
            "parent_client_order_id": "btcDPowned1",
            "instrument_id": "BTC-USDT-SWAP",
            "opening_intent": True,
            "status": "active",
        }
    }
    snapshot = _algo_snapshot(
        contracts="0",
        algo_id="owned1",
        algo_client_id="ownedAlgo1",
    )
    snapshot["pending_algo_orders"].append(
        {
            "algo_id": "unknown1",
            "algo_client_order_id": "unknownAlgo1",
            "instrument_id": "BTC-USDT-SWAP",
            "state": "live",
        }
    )

    with pytest.raises(
        OkxDemoPaperRuntimeError,
        match="unknown_algo_not_cancelled",
    ):
        controller._cleanup_owned_flat_algos(  # type: ignore[arg-type]
            client,
            snapshot=snapshot,
        )

    assert client.cancel_algo_calls == []


def test_transient_recovery_cannot_reopen_with_nonterminal_order_intent(
    tmp_path: Path,
) -> None:
    controller = _controller(tmp_path, lambda _: _credentials())
    client = _install_full_recovery_evidence_stubs(controller)
    private_ws = CurrentPrivateWS()
    controller._private_ws = private_ws
    controller._state["runtime"].update(
        {
            "active": True,
            "status": "cancel_only",
            "opening_allowed": False,
            "cancel_only": True,
            "blockers": ["okx_demo_transient:response_lost"],
        }
    )
    controller._state["risk_control"]["mode"] = "FROZEN_UNKNOWN"
    controller._state["risk_control"]["pending_order_intents"] = {
        "btcDPrecovery001": {
            "client_order_id": "btcDPrecovery001",
            "status": "accepted",
            "retry_without_query_allowed": False,
        }
    }
    controller._collect_exchange_snapshot = lambda _client: {  # type: ignore[method-assign]
        "orders": [],
        "pending_orders": [
            {
                "client_order_id": "btcDPrecovery001",
                "state": "live",
            }
        ],
        "fills": [],
        "positions": [],
    }
    controller._preflight_blockers = lambda _snapshot, require_flat: []

    with pytest.raises(
        OkxDemoPaperRuntimeError,
        match="okx_demo_ambiguous_order_query_failed",
    ):
        controller._recover_transient_cycle()

    status = controller.status()
    assert private_ws.reconcile_calls == 0
    assert status["risk_control"]["mode"] == "FROZEN_UNKNOWN"
    assert status["runtime"]["opening_allowed"] is False
    assert status["runtime"]["cancel_only"] is True
    assert status["risk_control"]["pending_order_intents"][
        "btcDPrecovery001"
    ]["status"] == "accepted"
    assert client.order_calls == []


def test_transient_recovery_rejects_private_ws_disconnect_during_caa(
    tmp_path: Path,
) -> None:
    controller = _controller(tmp_path, lambda _: _credentials())
    _install_full_recovery_evidence_stubs(controller)
    private_ws = CurrentPrivateWS()
    controller._private_ws = private_ws
    controller._state["runtime"].update(
        {
            "active": True,
            "status": "cancel_only",
            "opening_allowed": False,
            "cancel_only": True,
            "blockers": ["okx_demo_transient:response_lost"],
        }
    )
    controller._state["risk_control"]["mode"] = "FROZEN_UNKNOWN"
    controller._collect_exchange_snapshot = lambda _client: {  # type: ignore[method-assign]
        "orders": [],
        "pending_orders": [],
        "fills": [],
        "positions": [],
    }
    controller._preflight_blockers = lambda _snapshot, require_flat: []

    def disconnect_during_dead_man(
        _client: object,
        *,
        trigger: str,
    ) -> None:
        assert trigger == "frozen_state_reconciliation"
        private_ws.status = lambda: {  # type: ignore[method-assign]
            "connected": False,
            "listener_alive": False,
            "opening_allowed_after_reconciliation": False,
            "blockers": ["btc_okx_demo_private_ws:not_connected"],
        }
        controller._on_private_ws_disconnect("fault_injected_caa_window")

    controller._arm_dead_man = disconnect_during_dead_man  # type: ignore[method-assign]

    with pytest.raises(
        OkxDemoPaperRuntimeError,
        match="okx_demo_private_ws_generation_changed_during_recovery",
    ):
        controller._recover_transient_cycle()

    status = controller.status()
    assert private_ws.reconcile_calls == 1
    assert status["risk_control"]["mode"] == "FROZEN_UNKNOWN"
    assert status["runtime"]["opening_allowed"] is False
    assert status["runtime"]["cancel_only"] is True
    assert status["private_ws"]["connected"] is False
    assert status["private_ws"]["listener_alive"] is False
    with pytest.raises(
        OkxDemoPaperRuntimeError,
        match="okx_demo_(order_submit_mode_not_allowed|opening_submit)",
    ):
        controller._assert_order_submit_path(is_opening=True)


def test_worker_continues_once_when_failure_transitions_to_risk_reducing(
    tmp_path: Path,
) -> None:
    controller = _controller(tmp_path, lambda _: _credentials())
    controller._state["runtime"].update(
        {"active": True, "opening_allowed": True, "cancel_only": False}
    )
    controller._state["risk_control"]["mode"] = "RUNNING"
    controller._stop_event = StepStopEvent([False])
    calls: list[str] = []

    def run_cycle() -> dict[str, Any]:
        calls.append(controller._state["risk_control"]["mode"])
        if len(calls) == 1:
            controller._set_risk_mode(
                "RISK_REDUCING",
                "okx_demo_exchange_hosted_protection_unconfirmed",
            )
            raise OkxDemoPaperRuntimeError(
                "okx_demo_exchange_hosted_protection_unconfirmed"
            )
        controller._stop_event.set()
        return controller.status()

    controller.run_cycle = run_cycle  # type: ignore[method-assign]

    controller._worker_loop()

    assert calls == ["RUNNING", "RISK_REDUCING"]


def test_risk_reduction_freezes_unsupported_equal_long_short_shape(
    tmp_path: Path,
) -> None:
    controller, _, _ = _p0_order_controller(tmp_path)
    controller._set_risk_mode(
        "RISK_REDUCING",
        "fault_injected_position_reconciliation",
    )
    controller._collect_exchange_snapshot = lambda _client: {  # type: ignore[method-assign]
        "positions": [
            {"position_side": "long", "contracts": "0.005"},
            {"position_side": "short", "contracts": "0.005"},
        ],
        "pending_orders": [],
    }

    with pytest.raises(
        OkxDemoPaperRuntimeError,
        match="okx_demo_paper_hedged_position_shape_unsupported",
    ):
        controller._run_risk_reduction_cycle(
            object(),  # type: ignore[arg-type]
            strategy={"strategy_id": "long_short_donchian_top5"},
        )

    status = controller.status()
    assert status["risk_control"]["mode"] == "FROZEN_UNKNOWN"
    assert status["runtime"]["opening_allowed"] is False


def test_risk_reduction_never_submits_while_order_intent_is_nonterminal(
    tmp_path: Path,
) -> None:
    controller, _, _ = _p0_order_controller(tmp_path)
    controller._set_risk_mode(
        "RISK_REDUCING",
        "fault_injected_private_ws_disconnect",
    )
    client_order_id = "btcDPriskreduce01"
    controller._owned_client_order_ids.add(client_order_id)
    controller._state["risk_control"]["pending_order_intents"] = {
        client_order_id: {
            "client_order_id": client_order_id,
            "status": "accepted",
            "retry_without_query_allowed": False,
        }
    }
    controller._collect_exchange_snapshot = lambda _client: {  # type: ignore[method-assign]
        "orders": [],
        "pending_orders": [
            {
                "client_order_id": client_order_id,
                "state": "live",
            }
        ],
        "fills": [],
        "positions": [
            {"position_side": "long", "contracts": "0.01"}
        ],
    }
    submit_attempts: list[dict[str, Any]] = []
    controller._submit_order_plan = (  # type: ignore[method-assign]
        lambda *_args, **kwargs: submit_attempts.append(dict(kwargs))
    )

    with pytest.raises(
        OkxDemoPaperRuntimeError,
        match="okx_demo_ambiguous_order_query_failed",
    ):
        controller._run_risk_reduction_cycle(
            SnapshotClient(),  # type: ignore[arg-type]
            strategy={"strategy_id": "long_short_donchian_top5"},
        )

    status = controller.status()
    assert submit_attempts == []
    assert status["risk_control"]["mode"] == "FROZEN_UNKNOWN"
    assert status["runtime"]["opening_allowed"] is False


@pytest.mark.parametrize(
    ("position_side", "contracts", "expected_error"),
    [
        (
            "long",
            "malformed",
            "okx_demo_paper_position_contracts_invalid",
        ),
        (
            "unknown",
            "0.01",
            "okx_demo_paper_position_side_unknown",
        ),
    ],
)
def test_risk_reduction_freezes_unrepresentable_position_evidence(
    tmp_path: Path,
    position_side: str,
    contracts: str,
    expected_error: str,
) -> None:
    controller, _, _ = _p0_order_controller(tmp_path)
    controller._set_risk_mode(
        "RISK_REDUCING",
        "fault_injected_position_reconciliation",
    )
    controller._collect_exchange_snapshot = lambda _client: {  # type: ignore[method-assign]
        "orders": [],
        "pending_orders": [],
        "fills": [],
        "positions": [
            {"position_side": position_side, "contracts": contracts}
        ],
    }

    with pytest.raises(OkxDemoPaperRuntimeError, match=expected_error):
        controller._run_risk_reduction_cycle(
            SnapshotClient(),  # type: ignore[arg-type]
            strategy={"strategy_id": "long_short_donchian_top5"},
        )

    status = controller.status()
    assert status["risk_control"]["mode"] == "FROZEN_UNKNOWN"
    assert status["runtime"]["opening_allowed"] is False


def test_worker_retries_private_ws_current_reconciliation_until_explicit_success(
    tmp_path: Path,
) -> None:
    controller = OkxDemoPaperRuntimeController(
        config=OkxDemoPaperRuntimeConfig(
            repo_root=Path.cwd(),
            data_db_path=tmp_path / "unused.sqlite",
            output_dir=tmp_path / "output" / "btc_demo_paper_runtime",
        ),
        credential_loader=lambda _: _credentials(),
        start_worker=False,
    )
    private_ws = CurrentPrivateWS()
    client = _install_full_recovery_evidence_stubs(controller)
    controller._private_ws = private_ws
    controller._state["runtime"].update(
        {"active": True, "opening_allowed": True, "cancel_only": False}
    )
    controller._state["strategy"] = {"strategy_id": "fixture"}
    controller._stop_event = StepStopEvent([False, False, True])
    snapshots = [
        OkxDemoTransportError("URLError"),
        {"captured_at_utc": datetime.now(timezone.utc).isoformat()},
        {"captured_at_utc": datetime.now(timezone.utc).isoformat()},
    ]

    def collect(_client: object) -> dict[str, Any]:
        value = snapshots.pop(0)
        if isinstance(value, Exception):
            raise value
        return value

    receipts = [
        {
            "connected": False,
            "listener_alive": False,
            "opening_allowed_after_reconciliation": False,
            "blockers": [
                "btc_private_ws:snapshot_transport_failed:OkxDemoTransportError"
            ],
        },
        {
            "connected": True,
            "listener_alive": True,
            "opening_allowed_after_reconciliation": True,
            "blockers": [],
        },
    ]
    opening_states_during_reconciliation: list[bool] = []

    def reconcile_current() -> dict[str, Any]:
        private_ws.reconcile_calls += 1
        opening_states_during_reconciliation.append(
            controller._state["runtime"]["opening_allowed"] is True
        )
        return receipts.pop(0)

    order_calls: list[str] = []
    private_ws.reconcile_current = reconcile_current  # type: ignore[method-assign]
    controller._collect_exchange_snapshot = collect
    controller._preflight_blockers = lambda _snapshot, require_flat: []
    controller._submit_order_plan = lambda *_args, **_kwargs: order_calls.append(
        "submitted"
    )

    controller._worker_loop()

    status = controller.status()
    event_types = [event["event_type"] for event in status["events"]]
    assert private_ws.reconcile_calls == 2
    assert opening_states_during_reconciliation == [False, False]
    assert order_calls == []
    assert status["runtime"]["active"] is True
    assert status["runtime"]["cancel_only"] is False
    assert status["runtime"]["opening_allowed"] is True
    assert len(client.dead_man_calls) == 1
    assert "runtime_transient_recovery_failed" in event_types
    assert "runtime_transient_recovered" in event_types
    assert not any(
        str(blocker).startswith("okx_demo_transient:")
        for blocker in status["runtime"]["blockers"]
    )


@pytest.mark.parametrize(
    "blocker",
    [
        "btc_private_ws:snapshot_transport_failed:OkxDemoTransportError",
        "btc_private_ws:snapshot_transport_failed:50001",
    ],
)
def test_private_ws_snapshot_transport_receipt_allowlists_exact_recoverable_codes(
    blocker: str,
) -> None:
    assert okx_demo_runtime_module._private_ws_reconciliation_receipt_is_transient(
        {"blockers": [blocker]}
    )


@pytest.mark.parametrize(
    "blockers",
    [
        ["btc_private_ws:snapshot_transport_failed:unknown_error"],
        ["btc_private_ws:snapshot_transport_failed:OkxDemoTransportError:extra"],
        ["btc_private_ws:snapshot_transport_failed:50001x"],
        ["btc_private_ws:unknown_fill"],
        ["btc_private_ws:unknown_open_order"],
        ["btc_private_ws:identity_mismatch"],
        ["btc_private_ws:ledger_semantic_mismatch:50001"],
        ["btc_private_ws:position_mismatch"],
        ["btc_okx_demo_private_ws:snapshot_transport_failed:OkxDemoTransportError"],
        [
            "btc_private_ws:snapshot_transport_failed:OkxDemoTransportError",
            "btc_private_ws:unknown_fill",
        ],
    ],
)
def test_private_ws_snapshot_transport_receipt_rejects_unknown_or_mixed_blockers(
    blockers: list[str],
) -> None:
    assert not okx_demo_runtime_module._private_ws_reconciliation_receipt_is_transient(
        {"blockers": blockers}
    )


def test_worker_does_not_retry_non_transient_private_ws_receipt_blocker(
    tmp_path: Path,
) -> None:
    controller = OkxDemoPaperRuntimeController(
        config=OkxDemoPaperRuntimeConfig(
            repo_root=Path.cwd(),
            data_db_path=tmp_path / "unused.sqlite",
            output_dir=tmp_path / "output" / "btc_demo_paper_runtime",
        ),
        credential_loader=lambda _: _credentials(),
        start_worker=False,
    )
    private_ws = CurrentPrivateWS()
    controller._client = object()
    controller._private_ws = private_ws
    controller._state["runtime"].update(
        {"active": True, "opening_allowed": True, "cancel_only": False}
    )
    controller._state["strategy"] = {"strategy_id": "fixture"}
    controller._stop_event = StepStopEvent([False])
    snapshots = [
        OkxDemoTransportError("URLError"),
        {"captured_at_utc": datetime.now(timezone.utc).isoformat()},
    ]

    def collect(_client: object) -> dict[str, Any]:
        value = snapshots.pop(0)
        if isinstance(value, Exception):
            raise value
        return value

    def reconcile_current() -> dict[str, Any]:
        private_ws.reconcile_calls += 1
        return {
            "opening_allowed_after_reconciliation": False,
            "blockers": [
                "btc_okx_demo_private_ws:ledger_semantic_mismatch:50001"
            ],
        }

    private_ws.reconcile_current = reconcile_current  # type: ignore[method-assign]
    controller._collect_exchange_snapshot = collect
    controller._preflight_blockers = lambda _snapshot, require_flat: []

    controller._worker_loop()

    status = controller.status()
    assert private_ws.reconcile_calls == 1
    assert status["runtime"]["cancel_only"] is True
    assert status["runtime"]["opening_allowed"] is False
    assert status["runtime"]["last_error"] == (
        "okx_demo_private_ws_current_reconciliation_failed:"
        "btc_okx_demo_private_ws:ledger_semantic_mismatch:50001"
    )


def test_worker_does_not_retry_permanent_position_or_ledger_blocker(
    tmp_path: Path,
) -> None:
    controller = OkxDemoPaperRuntimeController(
        config=OkxDemoPaperRuntimeConfig(
            repo_root=Path.cwd(),
            data_db_path=tmp_path / "unused.sqlite",
            output_dir=tmp_path / "output" / "btc_demo_paper_runtime",
        ),
        credential_loader=lambda _: _credentials(),
        start_worker=False,
    )
    controller._client = object()
    controller._private_ws = CurrentPrivateWS()
    controller._state["runtime"].update(
        {"active": True, "opening_allowed": True, "cancel_only": False}
    )
    controller._state["strategy"] = {"strategy_id": "fixture"}
    controller._stop_event = StepStopEvent([False])
    controller._collect_exchange_snapshot = lambda _client: {
        "captured_at_utc": datetime.now(timezone.utc).isoformat()
    }
    controller._preflight_blockers = lambda _snapshot, require_flat: [
        "okx_demo_ledger_reconciliation_mismatch",
        "okx_demo_position_not_flat",
    ]

    controller._worker_loop()

    status = controller.status()
    assert status["runtime"]["cancel_only"] is True
    assert status["runtime"]["opening_allowed"] is False
    assert "okx_demo_ledger_reconciliation_mismatch" in status["runtime"]["last_error"]
    assert "okx_demo_position_not_flat" in status["runtime"]["last_error"]
    assert not str(status["runtime"]["last_error"]).startswith(
        "okx_demo_transient:"
    )
    assert controller._private_ws.reconcile_calls == 0


def test_private_ws_disconnect_blocks_opening_without_automatic_cancel(
    tmp_path: Path,
) -> None:
    controller = _controller(tmp_path, lambda _: _credentials())
    cancel_calls: list[str] = []
    controller._client = object()
    controller._state["runtime"].update(
        {"active": True, "opening_allowed": True, "cancel_only": False}
    )
    controller._cancel_owned_pending = lambda _client: (
        cancel_calls.append("called"),
        [],
    )

    controller._on_private_ws_disconnect("socket_closed")

    status = controller.status()
    assert status["runtime"]["cancel_only"] is True
    assert status["runtime"]["opening_allowed"] is False
    assert status["private_ws"]["connected"] is False
    assert status["private_ws"]["opening_allowed_after_reconciliation"] is False
    assert cancel_calls == []


def test_partial_fill_order_plan_uses_one_ioc_entry_with_0p03_cap(tmp_path: Path) -> None:
    controller, snapshot, _ = _p0_order_controller(tmp_path)
    controller._state["limits"].update(
        {
            "order_contracts": "0.03",
            "max_net_contracts": "0.03",
            "max_notional_usdt": "25",
        }
    )

    plan = controller._build_order_plan(
        snapshot,
        current_quantity=Decimal("0"),
        target_quantity=Decimal("0.03"),
    )

    assert plan is not None
    assert plan["contracts"] == "0.03"
    assert plan["entry_order_type"] == "ioc"
    assert plan["partial_fill_recovery"] is True
    assert plan["risk"]["max_net_contracts"] == "0.03"
    assert plan["risk"]["max_notional_usdt"] == "25"


def test_partial_authoritative_receipt_binds_ids_to_run_and_is_immutable(
    tmp_path: Path,
) -> None:
    controller = _controller(tmp_path, lambda _: _credentials())
    controller._state["runtime"]["run_id"] = "runtime-1"
    projection = okx_demo_runtime_module._partial_authoritative_identity_projection(
        runtime_run_id="runtime-1",
        source_head="a" * 40,
        opening_clord_id="btcDPruntime-0001",
        close_clord_id="btcDPruntime-0002",
        algo_clord_id="btcDPruntime-0001A",
        entry_order_id="order-authoritative",
        close_order_id="close-authoritative",
        entry_fill_ids=["fill-authoritative"],
        close_fill_ids=["close-fill-authoritative"],
        entry_fill_order_ids=["order-authoritative"],
        close_fill_order_ids=["close-authoritative"],
        entry_fill_client_order_ids=["btcDPruntime-0001"],
        close_fill_client_order_ids=["btcDPruntime-0002"],
        algo_id="algo-authoritative",
        algo_parent_clord_id="btcDPruntime-0001",
        entry_fill_contracts="0.01",
        close_fill_contracts="0.01",
        pre_reconciliation_sha256="a" * 64,
        post_reconciliation_sha256="b" * 64,
        final_flat=True,
        final_no_pending_orders=True,
        final_no_pending_algo_orders=True,
        final_ledger_reconciled=True,
        final_private_ws_reconciled=True,
    )

    receipt = controller._bind_fault_drill_authoritative_receipt(projection)
    attestation = controller.fault_drill_runtime_provenance()

    assert receipt["identity_namespace"] == "btcDPruntime-"
    assert receipt["receipt_sha256"] == (
        okx_demo_runtime_module._partial_authoritative_receipt_sha256(
            projection
        )
    )
    assert attestation["authoritative_receipt_sha256"] == receipt["receipt_sha256"]
    assert attestation["authoritative_identity_projection"] == projection
    assert attestation["source_head"] == "a" * 40

    conflicting_projection = dict(projection)
    conflicting_projection["entry_order_id"] = "order-foreign"
    with pytest.raises(
        OkxDemoPaperRuntimeError,
        match="authoritative_receipt_immutable_conflict",
    ):
        controller._bind_fault_drill_authoritative_receipt(
            conflicting_projection
        )


def test_partial_entry_truth_requires_matching_order_fill_position_and_oco() -> None:
    snapshot = {
        "orders": [
            {
                "order_id": "order-partial",
                "client_order_id": "btcDPpartial0001",
                "instrument_id": "BTC-USDT-SWAP",
                "side": "buy",
                "position_side": "long",
                "order_type": "ioc",
                "state": "canceled",
                "size": "0.03",
                "filled_size": "0.01",
            }
        ],
        "pending_orders": [],
        "fills": [
            {
                "fill_id": "fill-partial",
                "order_id": "order-partial",
                "client_order_id": "btcDPpartial0001",
                "instrument_id": "BTC-USDT-SWAP",
                "side": "buy",
                "position_side": "long",
                "size": "0.01",
            }
        ],
        "positions": [
            {
                "instrument_id": "BTC-USDT-SWAP",
                "position_side": "long",
                "contracts": "0.01",
            }
        ],
        "pending_algo_orders": [
            {
                "algo_id": "algo-partial",
                "algo_client_order_id": "btcDPpartial0001A",
                "parent_client_order_id": "btcDPpartial0001",
                "instrument_id": "BTC-USDT-SWAP",
                "position_side": "long",
                "size": "0.01",
                "state": "live",
                "take_profit_order_price": "-1",
                "stop_loss_order_price": "-1",
            }
        ],
    }

    truth = okx_demo_runtime_module._partial_entry_truth(
        snapshot,
        client_order_id="btcDPpartial0001",
        algo_client_order_id="btcDPpartial0001A",
        requested_contracts=Decimal("0.03"),
    )

    assert truth["classification"] == "partial_fill"
    assert truth["synthetic"] is False
    assert truth["filled_contracts"] == "0.01"
    assert truth["protection_verified"] is True


def test_partial_entry_truth_rejects_duplicate_fill_identity_before_deduplication() -> None:
    snapshot = {
        "orders": [
            {
                "order_id": "order-duplicate-fill",
                "client_order_id": "btcDPduplicatef1",
                "instrument_id": "BTC-USDT-SWAP",
                "side": "buy",
                "position_side": "long",
                "order_type": "ioc",
                "state": "canceled",
                "size": "0.03",
                "filled_size": "0.01",
            }
        ],
        "pending_orders": [],
        "fills": [
            {
                "fill_id": "f1",
                "order_id": "order-duplicate-fill",
                "client_order_id": "btcDPduplicatef1",
                "instrument_id": "BTC-USDT-SWAP",
                "side": "buy",
                "position_side": "long",
                "size": "0.005",
            },
            {
                "fill_id": "f1",
                "order_id": "order-duplicate-fill",
                "client_order_id": "btcDPduplicatef1",
                "instrument_id": "BTC-USDT-SWAP",
                "side": "buy",
                "position_side": "long",
                "size": "0.005",
            },
        ],
        "positions": [
            {
                "instrument_id": "BTC-USDT-SWAP",
                "position_side": "long",
                "contracts": "0.01",
            }
        ],
        "pending_algo_orders": [
            {
                "algo_id": "algo-duplicate-fill",
                "algo_client_order_id": "btcDPduplicatef1A",
                "parent_client_order_id": "btcDPduplicatef1",
                "instrument_id": "BTC-USDT-SWAP",
                "position_side": "long",
                "size": "0.01",
                "state": "live",
                "take_profit_order_price": "-1",
                "stop_loss_order_price": "-1",
            }
        ],
    }
    truth = okx_demo_runtime_module._partial_entry_truth(
        snapshot,
        client_order_id="btcDPduplicatef1",
        algo_client_order_id="btcDPduplicatef1A",
        requested_contracts=Decimal("0.03"),
    )

    assert truth["classification"] == "broker_truth_discrepancy"
    assert truth["duplicate_fill_identity"] is True
    assert truth["identity_discrepancy"] is True
    assert truth["fill_ids"] == ["f1", "f1"]


def test_partial_entry_truth_rejects_duplicate_order_identity() -> None:
    snapshot = {
        "orders": [
            {
                "order_id": "order-duplicate-order",
                "client_order_id": "btcDPduplicateo1",
                "instrument_id": "BTC-USDT-SWAP",
                "side": "buy",
                "position_side": "long",
                "order_type": "ioc",
                "state": "canceled",
                "size": "0.03",
                "filled_size": "0.01",
            },
            {
                "order_id": "order-duplicate-order",
                "client_order_id": "btcDPduplicateo1",
                "instrument_id": "BTC-USDT-SWAP",
                "side": "buy",
                "position_side": "long",
                "order_type": "ioc",
                "state": "canceled",
                "size": "0.03",
                "filled_size": "0.01",
            },
        ],
        "pending_orders": [],
        "fills": [],
        "positions": [],
        "pending_algo_orders": [],
    }
    truth = okx_demo_runtime_module._partial_entry_truth(
        snapshot,
        client_order_id="btcDPduplicateo1",
        algo_client_order_id="btcDPduplicateo1A",
        requested_contracts=Decimal("0.03"),
    )

    assert truth["classification"] == "broker_truth_discrepancy"
    assert truth["duplicate_order_identity"] is True
    assert truth["identity_discrepancy"] is True


def test_partial_reconciliation_covers_order_fill_position_oco_ledger_and_ws() -> None:
    snapshot = {
        "orders": [
            {
                "order_id": "order-partial",
                "client_order_id": "btcDPpartial0001",
                "instrument_id": "BTC-USDT-SWAP",
                "side": "buy",
                "position_side": "long",
                "order_type": "ioc",
                "state": "canceled",
                "size": "0.03",
                "filled_size": "0.01",
            }
        ],
        "pending_orders": [],
        "fills": [
            {
                "fill_id": "fill-partial",
                "order_id": "order-partial",
                "client_order_id": "btcDPpartial0001",
                "instrument_id": "BTC-USDT-SWAP",
                "side": "buy",
                "position_side": "long",
                "size": "0.01",
            }
        ],
        "positions": [
            {
                "instrument_id": "BTC-USDT-SWAP",
                "position_side": "long",
                "contracts": "0.01",
            }
        ],
        "pending_algo_orders": [
            {
                "algo_id": "algo-partial",
                "algo_client_order_id": "btcDPpartial0001A",
                "parent_client_order_id": "btcDPpartial0001",
                "instrument_id": "BTC-USDT-SWAP",
                "position_side": "long",
                "size": "0.01",
                "state": "live",
                "take_profit_order_price": "-1",
                "stop_loss_order_price": "-1",
            }
        ],
    }
    ledger = {
        "status": "reconciled",
        "current_state_exchange_snapshot_match": True,
        "exchange_snapshot_sha256": okx_demo_runtime_module._fault_ledger_snapshot_sha256(snapshot),
    }
    reconciliation = okx_demo_runtime_module._partial_reconciliation(
        before=snapshot,
        after=snapshot,
        client_order_id="btcDPpartial0001",
        algo_client_order_id="btcDPpartial0001A",
        expected_filled_contracts=Decimal("0.01"),
        ledger=ledger,
        private_ws={
            "connected": True,
            "listener_alive": True,
            "opening_allowed_after_reconciliation": True,
            "reconnect_rest_reconciled": True,
        },
    )

    assert reconciliation["match"] is True
    assert all(
        reconciliation[key] is True
        for key in (
            "order_sync",
            "fill_sync",
            "position_sync",
            "oco_sync",
            "ledger_sync",
            "private_ws_sync",
        )
    )


def _partial_preflight_snapshot(balance_timestamp_ms: str) -> dict[str, Any]:
    return {
        "captured_at_utc": "2026-08-12T00:00:00+00:00",
        "orders": [],
        "pending_orders": [],
        "pending_algo_orders": [],
        "fills": [],
        "positions": [],
        "bills": [],
        "balance": {
            "equity_usdt": "5000",
            "available_usdt": "5000",
            "unrealized_pnl_usdt": "0",
            "timestamp_ms": balance_timestamp_ms,
        },
        "mark": {"mark_price": "60000"},
        "index": {"index_price": "60000"},
        "instrument": {
            "instrument_id": "BTC-USDT-SWAP",
            "contract_value_btc": "0.01",
            "tick_size": "0.1",
            "lot_size": "0.01",
            "minimum_size": "0.01",
        },
    }


class _PartialPreflightNoPostClient:
    def __init__(self) -> None:
        self.submit_calls: list[dict[str, Any]] = []
        self.cancel_calls: list[dict[str, Any]] = []
        self.dead_man_calls: list[dict[str, Any]] = []

    def submit_order(self, payload: Mapping[str, Any]) -> None:
        self.submit_calls.append(dict(payload))
        raise AssertionError("partial_preflight_must_not_submit")

    def cancel_order(self, **payload: Any) -> None:
        self.cancel_calls.append(dict(payload))
        raise AssertionError("partial_preflight_must_not_cancel")

    def cancel_all_after(self, **payload: Any) -> None:
        self.dead_man_calls.append(dict(payload))
        raise AssertionError("partial_preflight_must_not_touch_dead_man")


def _partial_preflight_controller(
    tmp_path: Path,
    *,
    stale: Mapping[str, Any],
) -> tuple[OkxDemoPaperRuntimeController, _PartialPreflightNoPostClient]:
    controller = OkxDemoPaperRuntimeController(
        config=OkxDemoPaperRuntimeConfig(
            repo_root=Path.cwd(),
            data_db_path=tmp_path / "unused.sqlite",
            output_dir=tmp_path / "output" / "btc_demo_paper_runtime",
        ),
        credential_loader=lambda _: _credentials(),
        start_worker=False,
    )
    client = _PartialPreflightNoPostClient()
    controller._client = client  # type: ignore[assignment]
    controller._private_ws = CurrentPrivateWS()
    controller._state["runtime"].update(
        {
            "active": True,
            "opening_allowed": True,
            "cancel_only": False,
            "run_id": "partial-preflight-runtime",
        }
    )
    controller._state["risk_control"]["mode"] = "RUNNING"
    controller._state["risk_control"]["dead_man"] = {"armed": True}
    controller._state["private_ws"] = {
        "connected": True,
        "listener_alive": True,
        "opening_allowed_after_reconciliation": True,
    }
    controller._state["exchange"] = json.loads(json.dumps(stale))
    controller._state["ledger_reconciliation"] = {
        "status": "reconciled",
        "current_state_exchange_snapshot_match": True,
        "exchange_snapshot_sha256": (
            okx_demo_runtime_module._fault_ledger_snapshot_sha256(stale)
        ),
        "funding_cashflow_reconciled": True,
    }
    return controller, client


def _partial_preflight_authorization() -> dict[str, Any]:
    return {
        "authorization_ticket": "BTC-OKX-P0-DRILL-SUPERVISOR-FRONTEND-01",
        "source_head": _repo_head_for_test(),
        "scenario": "partial_fill_disconnect",
        "environment": "OKX Demo",
        "instrument_id": "BTC-USDT-SWAP",
        "margin_mode": "isolated",
        "leverage": "3",
        "order_contracts": "0.03",
        "max_notional_usdt": "25",
        "confirm_dedicated_demo_account": True,
        "execute_demo": True,
        "evidence_class": "demo_fault_drill_evidence",
    }


def test_partial_fill_preflight_refreshes_ledger_from_same_fresh_snapshot(
    tmp_path: Path,
) -> None:
    stale = _partial_preflight_snapshot("1")
    fresh = _partial_preflight_snapshot("2")
    baseline, baseline_client = _partial_preflight_controller(
        tmp_path / "baseline",
        stale=stale,
    )

    # Failure-first condition: the existing strict S2 hash check rejects a
    # harmless balance provenance update before an opening intent is built.
    with pytest.raises(
        OkxDemoPaperRuntimeError,
        match="okx_demo_partial_fill_preflight_ledger_not_current",
    ):
        baseline._run_partial_fill_disconnect(
            client=baseline_client,  # type: ignore[arg-type]
            private_ws=baseline._private_ws,
            strategy={},
            initial=fresh,
            orders_before=0,
            fault_injector=object(),
            authorization=_partial_preflight_authorization(),
        )
    assert baseline_client.submit_calls == []
    assert baseline_client.cancel_calls == []
    assert baseline_client.dead_man_calls == []

    controller, client = _partial_preflight_controller(
        tmp_path / "fixed",
        stale=stale,
    )
    entered: list[Mapping[str, Any]] = []
    controller._collect_exchange_snapshot = lambda _client: fresh  # type: ignore[method-assign]
    controller._preflight_blockers = lambda _snapshot, require_flat: []  # type: ignore[method-assign]
    controller._run_partial_fill_disconnect = (  # type: ignore[method-assign]
        lambda **kwargs: entered.append(kwargs) or {"entered": True}
    )

    result = controller.run_fault_drill_scenario(
        "partial_fill_disconnect",
        fault_injector=object(),
        authorization=_partial_preflight_authorization(),
    )

    assert result == {"entered": True}
    assert entered and entered[0]["initial"] is fresh
    ledger = controller._state["ledger_reconciliation"]
    assert ledger["trigger"] == "fault_drill_partial_fill_preflight"
    assert ledger["exchange_snapshot_sha256"] == (
        okx_demo_runtime_module._fault_ledger_snapshot_sha256(fresh)
    )
    assert [event["event_type"] for event in controller._state["events"]].count(
        "ledger_uow_committed"
    ) == 1
    assert client.submit_calls == []
    assert client.cancel_calls == []
    assert client.dead_man_calls == []


@pytest.mark.parametrize("failure", ["apply", "commit"])
def test_partial_fill_preflight_refresh_failure_freezes_before_entering_s2(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    stale = _partial_preflight_snapshot("1")
    fresh = _partial_preflight_snapshot("2")
    controller, client = _partial_preflight_controller(tmp_path, stale=stale)
    controller._collect_exchange_snapshot = lambda _client: fresh  # type: ignore[method-assign]
    controller._preflight_blockers = lambda _snapshot, require_flat: []  # type: ignore[method-assign]
    entered: list[str] = []
    controller._run_partial_fill_disconnect = (  # type: ignore[method-assign]
        lambda **_kwargs: entered.append("entered")
    )

    if failure == "apply":
        monkeypatch.setattr(
            controller,
            "_apply_snapshot",
            lambda _snapshot: (_ for _ in ()).throw(RuntimeError("apply_failed")),
        )
    else:
        monkeypatch.setattr(
            controller,
            "_commit_ledger_reconciliation",
            lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("commit_failed")),
        )

    with pytest.raises(
        OkxDemoPaperRuntimeError,
        match="okx_demo_partial_fill_preflight_ledger_refresh_failed",
    ):
        controller.run_fault_drill_scenario(
            "partial_fill_disconnect",
            fault_injector=object(),
            authorization=_partial_preflight_authorization(),
        )

    assert entered == []
    assert controller._state["runtime"]["opening_allowed"] is False
    assert controller._state["runtime"]["cancel_only"] is True
    assert controller._state["risk_control"]["mode"] == "FROZEN_UNKNOWN"
    assert client.submit_calls == []
    assert client.cancel_calls == []
    assert client.dead_man_calls == []


def test_partial_fill_preflight_rejects_nonflat_before_ledger_refresh(
    tmp_path: Path,
) -> None:
    stale = _partial_preflight_snapshot("1")
    controller, client = _partial_preflight_controller(tmp_path, stale=stale)
    commit_calls: list[dict[str, Any]] = []
    entered: list[str] = []
    controller._collect_exchange_snapshot = lambda _client: stale  # type: ignore[method-assign]
    controller._preflight_blockers = lambda _snapshot, require_flat: [  # type: ignore[method-assign]
        "okx_demo_paper_start_requires_flat_account"
    ]
    controller._commit_ledger_reconciliation = (  # type: ignore[method-assign]
        lambda **kwargs: commit_calls.append(kwargs)
    )
    controller._run_partial_fill_disconnect = (  # type: ignore[method-assign]
        lambda **_kwargs: entered.append("entered")
    )

    with pytest.raises(
        OkxDemoPaperRuntimeError,
        match="okx_demo_paper_start_requires_flat_account",
    ):
        controller.run_fault_drill_scenario(
            "partial_fill_disconnect",
            fault_injector=object(),
            authorization=_partial_preflight_authorization(),
        )

    assert commit_calls == []
    assert entered == []
    assert client.submit_calls == []
    assert client.cancel_calls == []
    assert client.dead_man_calls == []


def _repo_controller(tmp_path: Path, credential_loader) -> OkxDemoPaperRuntimeController:
    return OkxDemoPaperRuntimeController(
        config=OkxDemoPaperRuntimeConfig(
            repo_root=Path.cwd(),
            data_db_path=tmp_path / "missing.sqlite",
            output_dir=tmp_path / "output" / "btc_demo_paper_runtime",
        ),
        credential_loader=credential_loader,
        start_worker=False,
    )


def test_post_response_loss_reconciliation_uses_injected_event_and_exchange_readback() -> None:
    injector = type(
        "Injector",
        (),
        {
            "timeline": [
                {
                    "sequence": 1,
                    "event": "post_response_lost_after_exchange_response",
                    "clOrdId": "btcDPowned0001",
                }
            ]
        },
    )()

    assert okx_demo_runtime_module._fault_drill_post_response_loss_reconciled(
        injector,
        opening_error="",
        client_order_id="btcDPowned0001",
        order_observed=True,
        fill_observed=True,
    ) is True
    assert okx_demo_runtime_module._fault_drill_post_response_loss_reconciled(
        injector,
        opening_error="",
        client_order_id="btcDPowned0001",
        order_observed=False,
        fill_observed=True,
    ) is False


def _incident_recovery_snapshot(
    *,
    extra_pending: bool = False,
    oco_mutation: tuple[str, Any] | None = None,
) -> dict[str, Any]:
    now_ms = str(int(datetime.now(timezone.utc).timestamp() * 1000))
    snapshot = {
        **_p0_order_snapshot(),
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "account": {
            "account_level": "2",
            "position_mode": "long_short_mode",
            "permissions": ["trade"],
        },
        "balance": {"equity_usdt": "100", "available_usdt": "100"},
        "positions": [
            {
                "instrument_id": "BTC-USDT-SWAP",
                "position_side": "long",
                "margin_mode": "isolated",
                "leverage": "3",
                "contracts": "0.01",
            }
        ],
        "pending_orders": (
            [
                {
                    "order_id": "unknown-live",
                    "client_order_id": "unknown-live-client",
                    "state": "live",
                }
            ]
            if extra_pending
            else []
        ),
        "pending_algo_orders": [
            {
                "algo_id": "algo-incident-1",
                "algo_client_order_id": "btcDPfailed0001A",
                "instrument_id": "BTC-USDT-SWAP",
                "position_side": "long",
                "size": "0.01",
                "order_type": "oco",
                "state": "live",
                "take_profit_trigger": "65867.3",
                "take_profit_trigger_type": "mark",
                "take_profit_order_price": "-1",
                "stop_loss_trigger": "63929.9",
                "stop_loss_trigger_type": "mark",
                "stop_loss_order_price": "-1",
                "parent_client_order_id": "btcDPfailed0001",
            }
        ],
        "orders": [
            {
                "order_id": "opening-order-1",
                "client_order_id": "btcDPfailed0001",
                "instrument_id": "BTC-USDT-SWAP",
                "side": "buy",
                "position_side": "long",
                "order_type": "fok",
                "price": "64575.7",
                "size": "0.01",
                "state": "filled",
            }
        ],
        "fills": [
            {
                "fill_id": "opening-fill-1",
                "order_id": "opening-order-1",
                "client_order_id": "btcDPfailed0001",
                "instrument_id": "BTC-USDT-SWAP",
                "side": "buy",
                "position_side": "long",
                "size": "0.01",
            }
        ],
        "bills": [],
        "mark": {"mark_price": "60000"},
        "index": {"index_price": "60000"},
        "instrument": {
            "instrument_id": "BTC-USDT-SWAP",
            "state": "live",
            "contract_value_btc": "0.01",
            "tick_size": "0.1",
            "lot_size": "0.01",
            "minimum_size": "0.01",
        },
        "server_time_ms": now_ms,
    }
    if oco_mutation is not None:
        field, value = oco_mutation
        snapshot["pending_algo_orders"][0][field] = value
    return snapshot


class IncidentRecoveryClient:
    def __init__(self) -> None:
        self.posts: list[str] = []
        self.close_order: dict[str, Any] = {}
        self.private_get_calls: list[tuple[str, dict[str, Any]]] = []

    def submit_order(self, payload: Mapping[str, Any]) -> OkxDemoResponse:
        self.posts.append("order")
        self.close_order = dict(payload)
        return OkxDemoResponse(
            method="POST",
            path="/api/v5/trade/order",
            http_status=200,
            code="0",
            message="",
            data=(
                {
                    "ordId": "close-order-1",
                    "clOrdId": payload["clOrdId"],
                    "sCode": "0",
                    "sMsg": "",
                },
            ),
        )

    def cancel_algo_orders(
        self,
        orders: list[Mapping[str, Any]],
    ) -> OkxDemoResponse:
        assert self.posts == ["order"]
        assert orders == [
            {"algoId": "algo-incident-1", "instId": "BTC-USDT-SWAP"}
        ]
        self.posts.append("cancel-algos")
        return OkxDemoResponse(
            method="POST",
            path="/api/v5/trade/cancel-algos",
            http_status=200,
            code="0",
            message="",
            data=(({"algoId": "algo-incident-1", "sCode": "0", "sMsg": ""}),),
        )

    def cancel_all_after(self, **_payload: Any) -> OkxDemoResponse:
        self.posts.append("cancel-all-after")
        raise AssertionError("incident recovery must never POST cancel-all-after")

    def private_get(
        self,
        path: str,
        params: Mapping[str, Any] | None = None,
    ) -> OkxDemoResponse:
        self.private_get_calls.append((path, dict(params or {})))
        if path == "/api/v5/trade/order":
            rows = (
                {
                    "ordId": "close-order-1",
                    "clOrdId": self.close_order["clOrdId"],
                    "instId": "BTC-USDT-SWAP",
                    "side": "sell",
                    "posSide": "long",
                    "ordType": "ioc",
                    "sz": "0.01",
                    "tag": "btcP0Demo",
                    "state": "filled",
                    "accFillSz": "0.01",
                    "avgPx": "60000",
                },
            )
        elif path == "/api/v5/trade/fills":
            rows = (
                {
                    "tradeId": "close-fill-1",
                    "ordId": "close-order-1",
                    "clOrdId": self.close_order["clOrdId"],
                    "instId": "BTC-USDT-SWAP",
                    "side": "sell",
                    "posSide": "long",
                    "fillPx": "60000",
                    "fillSz": "0.01",
                },
            )
        elif path == "/api/v5/trade/orders-algo-pending":
            rows = () if "cancel-algos" in self.posts else (
                {
                    "algoId": "algo-incident-1",
                    "algoClOrdId": "btcDPfailed0001A",
                    "instId": "BTC-USDT-SWAP",
                    "ordType": "oco",
                    "state": "live",
                },
            )
        elif path == "/api/v5/trade/orders-algo-history":
            rows = (
                {
                    "algoId": "unrelated-algo",
                    "algoClOrdId": "unrelatedAlgoClient",
                    "instId": "BTC-USDT-SWAP",
                    "ordType": "oco",
                    "state": "canceled",
                },
                {
                    "algoId": "algo-incident-1",
                    "algoClOrdId": "btcDPfailed0001A",
                    "instId": "BTC-USDT-SWAP",
                    "ordType": "oco",
                    "state": "canceled",
                },
            )
        else:
            rows = ()
        return OkxDemoResponse(
            method="GET",
            path=path,
            http_status=200,
            code="0",
            message="",
            data=tuple(rows),
        )


class IncidentRecoveryPrivateWS:
    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.stopped = False

    def run_startup_reconnect_probe(self) -> dict[str, Any]:
        self.kwargs["snapshot_loader"]()
        return {"opening_allowed_after_reconciliation": True}

    def start_monitoring(self) -> None:
        return None

    def status(self) -> dict[str, Any]:
        return {
            "connected": True,
            "listener_alive": True,
            "opening_allowed_after_reconciliation": True,
        }

    def reconcile_current(self) -> dict[str, Any]:
        self.kwargs["snapshot_loader"]()
        return {
            "connected": True,
            "listener_alive": True,
            "opening_allowed_after_reconciliation": True,
        }

    def stop(self) -> dict[str, Any]:
        self.stopped = True
        return {"listener_joined": True}


def _incident_recovery_controller(
    tmp_path: Path,
    *,
    extra_pending: bool = False,
    oco_mutation: tuple[str, Any] | None = None,
    client: IncidentRecoveryClient | None = None,
    private_ws_factory: Any = IncidentRecoveryPrivateWS,
) -> tuple[OkxDemoPaperRuntimeController, IncidentRecoveryClient]:
    client = client or IncidentRecoveryClient()
    controller = OkxDemoPaperRuntimeController(
        config=OkxDemoPaperRuntimeConfig(
            repo_root=Path.cwd(),
            data_db_path=tmp_path / "unused.sqlite",
            output_dir=tmp_path / "output" / "btc_demo_paper_runtime",
            order_poll_interval_seconds=0.01,
            order_poll_attempts=1,
            authoritative_oms_bundle_provider=_test_authoritative_oms_bundle_provider,
        ),
        credential_loader=lambda _service: _credentials(),
        client_factory=lambda _config, _credentials_value: client,  # type: ignore[arg-type]
        private_ws_factory=private_ws_factory,
        start_worker=False,
    )
    controller._state["runtime"].update(
        {"run_id": "recover", "order_sequence": 1}
    )
    controller._sequence = 1
    controller._state["risk_control"]["pending_order_intents"] = {
        "btcDPfailed0001": {
            "client_order_id": "btcDPfailed0001",
            "status": "submit_pending",
            "action": "open_long",
            "risk_reducing_only": False,
            "order": {
                "instId": "BTC-USDT-SWAP",
                "side": "buy",
                "posSide": "long",
                "ordType": "fok",
                "sz": "0.01",
                "clOrdId": "btcDPfailed0001",
                "tag": "btcP0Demo",
            },
        }
    }
    controller._state["risk_control"]["protection_policy"] = _protection_policy()
    controller._owned_client_order_ids.add("btcDPfailed0001")
    controller._state["risk_control"]["owned_attached_algos"] = {
        "btcDPfailed0001A": {
            "algo_client_order_id": "btcDPfailed0001A",
            "parent_client_order_id": "btcDPfailed0001",
            "instrument_id": "BTC-USDT-SWAP",
            "opening_intent": True,
            "status": "submit_pending",
        }
    }
    controller._state["risk_control"]["active_protection"] = {}

    def collect(_client: Any) -> dict[str, Any]:
        snapshot = _incident_recovery_snapshot(
            extra_pending=extra_pending,
            oco_mutation=oco_mutation,
        )
        if "order" in client.posts:
            snapshot["positions"] = []
            snapshot["orders"].append(
                {
                    "order_id": "close-order-1",
                    "client_order_id": "btcDPrecover0002",
                    "instrument_id": "BTC-USDT-SWAP",
                    "side": "sell",
                    "position_side": "long",
                    "order_type": "ioc",
                    "price": "64570",
                    "size": "0.01",
                    "state": "filled",
                }
            )
            snapshot["fills"].append(
                {
                    "fill_id": "close-fill-1",
                    "order_id": "close-order-1",
                    "client_order_id": "btcDPrecover0002",
                    "instrument_id": "BTC-USDT-SWAP",
                    "side": "sell",
                    "position_side": "long",
                    "size": "0.01",
                }
            )
        if "cancel-algos" in client.posts:
            snapshot["pending_algo_orders"] = []
        return snapshot

    controller._collect_exchange_snapshot = collect  # type: ignore[method-assign]

    def commit(
        *,
        snapshot: Mapping[str, Any],
        trigger: str,
        order_record: Mapping[str, Any] | None = None,
    ) -> None:
        del trigger, order_record
        controller._state["ledger_reconciliation"] = {
            "status": "reconciled",
            "current_state_exchange_snapshot_match": True,
            "exchange_snapshot_sha256": (
                okx_demo_runtime_module._fault_ledger_snapshot_sha256(snapshot)
            ),
            "order_count": len(snapshot.get("orders", [])),
            "pending_order_count": len(snapshot.get("pending_orders", [])),
            "pending_algo_order_count": len(
                snapshot.get("pending_algo_orders", [])
            ),
            "fill_count": len(snapshot.get("fills", [])),
            "position_count": len(snapshot.get("positions", [])),
        }

    controller._commit_ledger_reconciliation = commit  # type: ignore[method-assign]
    return controller, client


def _incident_recovery_authorization() -> dict[str, str]:
    return {
        "authorization_ticket": "BTC-OKX-DEMO-INCIDENT-RECOVERY-AND-RECEIPT-05",
        "runtime_source_head": subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip(),
        "failed_receipt_sha256": "a" * 64,
        "failed_receipt_source_head": "b" * 40,
        "failed_receipt_scenario": "post_response_loss",
        "failed_receipt_run_id": "failed-run-1",
        "opening_cl_ord_id": "btcDPfailed0001",
        "opening_order_id": "opening-order-1",
        "opening_fill_id": "opening-fill-1",
        "algo_cl_ord_id": "btcDPfailed0001A",
        "algo_id": "algo-incident-1",
        "expected_close_cl_ord_id": "btcDPrecover0002",
    }


def _repo_head_for_test() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _flat_incident_recovery_controller(
    tmp_path: Path,
) -> tuple[OkxDemoPaperRuntimeController, IncidentRecoveryClient, dict[str, str]]:
    controller, client = _incident_recovery_controller(tmp_path)
    snapshot = json.loads(
        json.dumps(_incident_recovery_snapshot())
    )
    snapshot["positions"] = [
        {
            "instrument_id": "BTC-USDT-SWAP",
            "position_side": "long",
            "margin_mode": "isolated",
            "leverage": "3",
            "contracts": "0",
        }
    ]
    snapshot["pending_algo_orders"] = []
    snapshot["orders"].append(
        {
            "order_id": "close-order-1",
            "client_order_id": "btcDPrecover0002",
            "instrument_id": "BTC-USDT-SWAP",
            "side": "sell",
            "position_side": "long",
            "order_type": "ioc",
            "price": "64570",
            "size": "0.01",
            "state": "filled",
        }
    )
    snapshot["fills"].append(
        {
            "fill_id": "close-fill-1",
            "order_id": "close-order-1",
            "client_order_id": "btcDPrecover0002",
            "instrument_id": "BTC-USDT-SWAP",
            "side": "sell",
            "position_side": "long",
            "size": "0.01",
        }
    )

    def collect(_client: Any) -> dict[str, Any]:
        return json.loads(json.dumps(snapshot))

    controller._collect_exchange_snapshot = collect  # type: ignore[method-assign]
    authorization = _incident_recovery_authorization()
    authorization.update(
        {
            "recovery_mode": "already_flat",
            "flat_identity_sha256": (
                okx_demo_runtime_module._incident_recovery_flat_identity_sha256(
                    snapshot,
                    owned_client_order_ids=(
                        "btcDPfailed0001",
                        "btcDPrecover0002",
                    ),
                )
            ),
        }
    )
    return controller, client, authorization


@pytest.mark.parametrize("already_flat", [False, True], ids=["ordinary", "already_flat"])
def test_incident_recovery_failed_private_ws_probe_never_starts_monitoring(
    tmp_path: Path,
    already_flat: bool,
) -> None:
    """A blocked probe must be the terminal recovery error, not a listener error."""

    class BlockedProbeWS(IncidentRecoveryPrivateWS):
        instances: list["BlockedProbeWS"] = []

        def __init__(self, **kwargs: Any) -> None:
            super().__init__(**kwargs)
            self.start_monitoring_calls = 0
            self.__class__.instances.append(self)

        def run_startup_reconnect_probe(self) -> dict[str, Any]:
            self.kwargs["snapshot_loader"]()
            return {
                "opening_allowed_after_reconciliation": False,
                "probe_generation": 2,
                "blockers": [
                    "btc_okx_demo_private_ws:probe_wallclock_timeout"
                ],
                "probe_diagnostics": [
                    {
                        "stage": "reconnect",
                        "exception_type": "ProbeWallClockTimeout",
                        "error_code": "btc_okx_demo_private_ws:probe_wallclock_timeout",
                    }
                ],
            }

        def start_monitoring(self) -> None:
            self.start_monitoring_calls += 1

    if already_flat:
        controller, client, authorization = _flat_incident_recovery_controller(
            tmp_path
        )
    else:
        controller, client = _incident_recovery_controller(tmp_path)
        authorization = _incident_recovery_authorization()
    controller._private_ws_factory = BlockedProbeWS

    with pytest.raises(
        OkxDemoPaperRuntimeError,
        match="okx_demo_private_ws_startup_reconnect_probe_failed",
    ):
        controller.recover_fault_drill_incident(authorization=authorization)

    assert len(BlockedProbeWS.instances) == 1
    assert BlockedProbeWS.instances[0].start_monitoring_calls == 0
    assert client.posts == []
    status = controller.status()
    assert status["runtime"]["active"] is False
    assert status["runtime"]["opening_allowed"] is False
    assert status["runtime"]["cancel_only"] is True
    assert status["risk_control"]["mode"] == "FROZEN_UNKNOWN"
    assert "okx_demo_private_ws_startup_reconnect_probe_failed" in status[
        "runtime"
    ]["blockers"]
    assert status["private_ws"]["probe_diagnostics"][0]["stage"] == "reconnect"
    assert status["private_ws"]["probe_diagnostics"][0]["generation"]["after"] == "2"


def _hosted_oco_terminal_exit_snapshot() -> dict[str, Any]:
    """Exact, normalized read-only shape of the fixed hosted-OCO incident."""

    entry_client = "btcDP20a8d1650001"
    entry_order = "3816659792351170560"
    exit_client = "O3821053454550453248"
    exit_order = "3821053454707298304"
    snapshot = _incident_recovery_snapshot()
    snapshot.update(
        {
            "positions": [],
            "pending_orders": [],
            "pending_algo_orders": [],
            "orders": [
                {
                    "order_id": entry_order,
                    "client_order_id": entry_client,
                    "instrument_id": "BTC-USDT-SWAP",
                    "side": "buy",
                    "position_side": "long",
                    "order_type": "fok",
                    "size": "0.01",
                    "filled_size": "0.01",
                    "state": "filled",
                    "created_at_ms": "1786267484916",
                    "updated_at_ms": "1786267484916",
                },
                {
                    "order_id": exit_order,
                    "client_order_id": exit_client,
                    "instrument_id": "BTC-USDT-SWAP",
                    "side": "sell",
                    "position_side": "long",
                    "order_type": "market",
                    "size": "0.01",
                    "filled_size": "0.01",
                    "state": "filled",
                    "reduce_only": True,
                    "algo_id": "3816659794069377024",
                    "algo_client_order_id": "btcDP20a8d1650001A",
                    "created_at_ms": "1786378666917",
                    "updated_at_ms": "1786378666918",
                },
            ],
            "fills": [
                {
                    "fill_id": "4318943831",
                    "order_id": entry_order,
                    "client_order_id": entry_client,
                    "instrument_id": "BTC-USDT-SWAP",
                    "side": "buy",
                    "position_side": "long",
                    "size": "0.01",
                    "timestamp_ms": "1786267484916",
                },
                {
                    "fill_id": "hosted-oco-exit-fill-1",
                    "order_id": exit_order,
                    "client_order_id": exit_client,
                    "instrument_id": "BTC-USDT-SWAP",
                    "side": "sell",
                    "position_side": "long",
                    "size": "0.01",
                    "timestamp_ms": "1786378666918",
                },
            ],
        }
    )
    return snapshot


def test_hosted_oco_terminal_exit_projection_requires_exact_field_linkage() -> None:
    snapshot = _hosted_oco_terminal_exit_snapshot()
    authorization = {
        "opening_cl_ord_id": "btcDP20a8d1650001",
        "opening_order_id": "3816659792351170560",
        "opening_fill_id": "4318943831",
        "algo_cl_ord_id": "btcDP20a8d1650001A",
        "algo_id": "3816659794069377024",
        "expected_close_cl_ord_id": "O3821053454550453248",
        "failed_receipt_sha256": "a" * 64,
        "failed_receipt_source_head": "b" * 40,
        "flat_identity_sha256": "c" * 64,
    }

    projection, blockers = okx_demo_runtime_module._hosted_oco_terminal_exit_projection(
        snapshot,
        authorization=authorization,
        current_head=_repo_head_for_test(),
    )

    assert blockers == []
    assert projection is not None
    assert projection["exit"]["client_order_id"] == "O3821053454550453248"
    assert projection["identity_digest_sha256"]

    authorization["recovery_binding_source"] = (
        "immutable_flat_hosted_exit_receipt_bundle"
    )
    projection, blockers = okx_demo_runtime_module._hosted_oco_terminal_exit_projection(
        snapshot,
        authorization=authorization,
        current_head=_repo_head_for_test(),
    )
    assert blockers == []
    assert projection is not None
    assert projection["binding_source"] == "immutable_flat_hosted_exit_receipt_bundle"

    snapshot["orders"][1]["algo_id"] = "foreign-algo"
    projection, blockers = okx_demo_runtime_module._hosted_oco_terminal_exit_projection(
        snapshot,
        authorization=authorization,
        current_head=_repo_head_for_test(),
    )
    assert projection is None
    assert "okx_demo_hosted_oco_exit_algo_link_mismatch" in blockers


def test_hosted_oco_terminal_exit_identity_digest_excludes_volatile_snapshot_audit() -> None:
    authorization = {
        "opening_cl_ord_id": "btcDP20a8d1650001",
        "opening_order_id": "3816659792351170560",
        "opening_fill_id": "4318943831",
        "algo_cl_ord_id": "btcDP20a8d1650001A",
        "algo_id": "3816659794069377024",
        "expected_close_cl_ord_id": "O3821053454550453248",
        "failed_receipt_sha256": "a" * 64,
        "failed_receipt_source_head": "b" * 40,
        "flat_identity_sha256": "c" * 64,
    }
    first, first_blockers = okx_demo_runtime_module._hosted_oco_terminal_exit_projection(
        _hosted_oco_terminal_exit_snapshot(),
        authorization=authorization,
        current_head=_repo_head_for_test(),
    )
    changed_snapshot = json.loads(
        json.dumps(_hosted_oco_terminal_exit_snapshot())
    )
    changed_snapshot["balance"]["available_usdt"] = "99.99"
    second, second_blockers = okx_demo_runtime_module._hosted_oco_terminal_exit_projection(
        changed_snapshot,
        authorization=authorization,
        current_head=_repo_head_for_test(),
    )

    assert first_blockers == []
    assert second_blockers == []
    assert first is not None
    assert second is not None
    assert first["snapshot_sha256"] != second["snapshot_sha256"]
    assert first["identity_digest_sha256"] == second["identity_digest_sha256"]

    identity_changed = json.loads(json.dumps(_hosted_oco_terminal_exit_snapshot()))
    identity_changed["orders"][1]["order_id"] = "foreign-exit-order"
    projection, blockers = okx_demo_runtime_module._hosted_oco_terminal_exit_projection(
        identity_changed,
        authorization=authorization,
        current_head=_repo_head_for_test(),
    )
    assert projection is None
    assert "okx_demo_hosted_oco_exit_fill_mismatch" in blockers


@pytest.mark.parametrize(
    ("mutate", "expected_blocker"),
    [
        (
            lambda snapshot: snapshot["orders"][1].update({"reduce_only": False}),
            "okx_demo_hosted_oco_exit_order_mismatch",
        ),
        (
            lambda snapshot: snapshot["orders"][1].update({"size": "0.02"}),
            "okx_demo_hosted_oco_exit_order_mismatch",
        ),
        (
            lambda snapshot: snapshot.update(
                {
                    "positions": [
                        {
                            "instrument_id": "BTC-USDT-SWAP",
                            "position_side": "long",
                            "contracts": "0.01",
                        }
                    ]
                }
            ),
            "okx_demo_hosted_oco_exit_position_not_flat",
        ),
        (
            lambda snapshot: snapshot.update(
                {"pending_algo_orders": [{"algo_id": "foreign"}]}
            ),
            "okx_demo_hosted_oco_exit_pending_oco_present",
        ),
        (
            lambda snapshot: snapshot["fills"].append(
                {
                    "fill_id": "foreign-fill",
                    "order_id": "foreign-order",
                    "client_order_id": "btcDPforeign0001",
                    "instrument_id": "BTC-USDT-SWAP",
                    "side": "sell",
                    "position_side": "long",
                    "size": "0.01",
                    "timestamp_ms": "1786378666919",
                }
            ),
            "okx_demo_hosted_oco_exit_foreign_or_duplicate_fill",
        ),
    ],
)
def test_hosted_oco_terminal_exit_projection_fails_closed_on_truth_drift(
    mutate: Any,
    expected_blocker: str,
) -> None:
    snapshot = _hosted_oco_terminal_exit_snapshot()
    mutate(snapshot)
    projection, blockers = okx_demo_runtime_module._hosted_oco_terminal_exit_projection(
        snapshot,
        authorization={
            "opening_cl_ord_id": "btcDP20a8d1650001",
            "opening_order_id": "3816659792351170560",
            "algo_cl_ord_id": "btcDP20a8d1650001A",
            "algo_id": "3816659794069377024",
            "expected_close_cl_ord_id": "O3821053454550453248",
            "failed_receipt_sha256": "a" * 64,
            "failed_receipt_source_head": "b" * 40,
            "flat_identity_sha256": "c" * 64,
        },
        current_head=_repo_head_for_test(),
    )

    assert projection is None
    assert expected_blocker in blockers


def test_hosted_oco_terminal_exit_projection_is_append_only_and_restores_owned_id(
    tmp_path: Path,
) -> None:
    controller = _controller(tmp_path, lambda _: _credentials())
    snapshot = _hosted_oco_terminal_exit_snapshot()
    authorization = {
        "opening_cl_ord_id": "btcDP20a8d1650001",
        "opening_order_id": "3816659792351170560",
        "opening_fill_id": "4318943831",
        "algo_cl_ord_id": "btcDP20a8d1650001A",
        "algo_id": "3816659794069377024",
        "expected_close_cl_ord_id": "O3821053454550453248",
        "failed_receipt_sha256": "a" * 64,
        "failed_receipt_source_head": "904296e6a0758a138964f3fb801ceeba8cd9ad7e",
        "flat_identity_sha256": "c" * 64,
    }
    projection, blockers = okx_demo_runtime_module._hosted_oco_terminal_exit_projection(
        snapshot,
        authorization=authorization,
        current_head=_repo_head_for_test(),
    )
    assert blockers == []
    assert projection is not None

    controller._persist_hosted_oco_terminal_exit_projection(projection)

    assert "O3821053454550453248" in controller._owned_client_order_ids
    assert controller.status()["events"][0]["event_type"] == (
        "hosted_oco_terminal_exit_ownership_projection"
    )
    recovered = controller._runtime_store.recover()
    restored_ids = (
        OkxDemoPaperRuntimeController._hosted_oco_terminal_exit_ids_from_recovered_events(
            recovered.events,
            current_head=_repo_head_for_test(),
        )
    )
    assert restored_ids == {
        "btcDP20a8d1650001",
        "O3821053454550453248",
    }

    audit_only_changed = json.loads(json.dumps(recovered.events[0]))
    audit_only_changed["payload"]["snapshot_sha256"] = "d" * 64
    assert (
        OkxDemoPaperRuntimeController._hosted_oco_terminal_exit_ids_from_recovered_events(
            [audit_only_changed],
            current_head=_repo_head_for_test(),
        )
        == {"btcDP20a8d1650001", "O3821053454550453248"}
    )
    identity_tampered = json.loads(json.dumps(audit_only_changed))
    identity_tampered["payload"]["entry"]["order_id"] = "foreign-entry-order"
    assert (
        OkxDemoPaperRuntimeController._hosted_oco_terminal_exit_ids_from_recovered_events(
            [identity_tampered],
            current_head=_repo_head_for_test(),
        )
        == set()
    )


def test_immutable_hosted_exit_projection_restores_exact_owned_ids_on_restart(
    tmp_path: Path,
) -> None:
    controller = _controller(tmp_path, lambda _: _credentials())
    controller._state["risk_control"]["pending_order_intents"] = {
        "btcDP20a8d1650001": {"status": "terminal"}
    }
    projection, blockers = okx_demo_runtime_module._hosted_oco_terminal_exit_projection(
        _hosted_oco_terminal_exit_snapshot(),
        authorization={
            "opening_cl_ord_id": "btcDP20a8d1650001",
            "opening_order_id": "3816659792351170560",
            "opening_fill_id": "4318943831",
            "algo_cl_ord_id": "btcDP20a8d1650001A",
            "algo_id": "3816659794069377024",
            "expected_close_cl_ord_id": "O3821053454550453248",
            "failed_receipt_sha256": "a" * 64,
            "failed_receipt_source_head": "904296e6a0758a138964f3fb801ceeba8cd9ad7e",
            "flat_identity_sha256": "c" * 64,
            "recovery_binding_source": (
                "immutable_flat_hosted_exit_receipt_bundle"
            ),
        },
        current_head=_repo_head_for_test(),
    )
    assert blockers == []
    assert projection is not None
    controller._persist_hosted_oco_terminal_exit_projection(projection)

    restored = OkxDemoPaperRuntimeController(
        config=OkxDemoPaperRuntimeConfig(
            repo_root=Path.cwd(),
            data_db_path=tmp_path / "missing.sqlite",
            output_dir=controller.config.output_dir,
        ),
        credential_loader=lambda _: _credentials(),
        start_worker=False,
    )

    assert {
        "btcDP20a8d1650001",
        "O3821053454550453248",
    }.issubset(restored._owned_client_order_ids)

    recovered = controller._runtime_store.recover()
    forged = json.loads(json.dumps(recovered.events[0]))
    forged["payload"]["binding_source"] = "immutable_flat_hosted_exit_receipt_bundle_extra"
    forged["payload"]["identity_digest_sha256"] = (
        okx_demo_runtime_module._hosted_oco_terminal_exit_identity_digest(
            forged["payload"]
        )
    )
    assert (
        OkxDemoPaperRuntimeController._hosted_oco_terminal_exit_ids_from_recovered_events(
            [forged],
            current_head=_repo_head_for_test(),
        )
        == set()
    )


def test_cross_head_hosted_exit_projection_restores_only_verified_entry_and_exit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A prior verified hosted exit stays owned only across real Git ancestry."""

    current_head = _repo_head_for_test()
    projection, blockers = okx_demo_runtime_module._hosted_oco_terminal_exit_projection(
        _hosted_oco_terminal_exit_snapshot(),
        authorization={
            "opening_cl_ord_id": "btcDP20a8d1650001",
            "opening_order_id": "3816659792351170560",
            "opening_fill_id": "4318943831",
            "algo_cl_ord_id": "btcDP20a8d1650001A",
            "algo_id": "3816659794069377024",
            "expected_close_cl_ord_id": "O3821053454550453248",
            "failed_receipt_sha256": "a" * 64,
            "failed_receipt_source_head": "904296e6a0758a138964f3fb801ceeba8cd9ad7e",
            "flat_identity_sha256": "c" * 64,
            "recovery_binding_source": (
                "immutable_flat_hosted_exit_receipt_bundle"
            ),
        },
        current_head="cf58b54b3f96cd0319e6aa321325a975f359e8f8",
    )
    assert blockers == []
    assert projection is not None
    event = {
        "event_type": "hosted_oco_terminal_exit_ownership_projection",
        "payload": projection,
    }

    restored_ids = (
        OkxDemoPaperRuntimeController._hosted_oco_terminal_exit_ids_from_recovered_events(
            [event],
            current_head=current_head,
        )
    )

    assert restored_ids == {
        "btcDP20a8d1650001",
        "O3821053454550453248",
    }

    class SnapshotTransport:
        def fetch_startup_snapshot(self) -> BTCPrivateWSStartupSnapshot:
            return BTCPrivateWSStartupSnapshot(
                open_orders=(),
                fills=(
                    {"client_order_id": "btcDP20a8d1650001"},
                    {"client_order_id": "O3821053454550453248"},
                    {"client_order_id": "btcDP51b9d4340001"},
                ),
                positions=(),
                balance={"equity_usdt": "5000"},
                funding_bills=(),
                last_sequence=0,
                private_ws_status="connected",
                rest_status="ok",
                captured_at_utc=datetime.now(timezone.utc),
            )

    receipt = BTCPrivateWSRuntimeReconciler(
        transport=SnapshotTransport(),
        owned_client_order_ids=tuple(restored_ids | {"btcDP51b9d4340001"}),
    ).startup()
    assert receipt.opening_allowed is True
    assert receipt.blockers == ()

    foreign_receipt = BTCPrivateWSRuntimeReconciler(
        transport=SnapshotTransport(),
        owned_client_order_ids=tuple(restored_ids),
    ).startup()
    assert foreign_receipt.opening_allowed is False
    assert "btc_private_ws:unknown_fill" in foreign_receipt.blockers

    non_ancestor = json.loads(json.dumps(event))
    non_ancestor["payload"]["recovery_code_head"] = "f" * 40
    non_ancestor["payload"]["identity_digest_sha256"] = (
        okx_demo_runtime_module._hosted_oco_terminal_exit_identity_digest(
            non_ancestor["payload"]
        )
    )
    assert (
        OkxDemoPaperRuntimeController._hosted_oco_terminal_exit_ids_from_recovered_events(
            [non_ancestor],
            current_head=current_head,
        )
        == set()
    )

    source_mismatch = json.loads(json.dumps(event))
    source_mismatch["payload"]["incident_source_head"] = "f" * 40
    source_mismatch["payload"]["identity_digest_sha256"] = (
        okx_demo_runtime_module._hosted_oco_terminal_exit_identity_digest(
            source_mismatch["payload"]
        )
    )
    assert (
        OkxDemoPaperRuntimeController._hosted_oco_terminal_exit_ids_from_recovered_events(
            [source_mismatch],
            current_head=current_head,
        )
        == set()
    )

    def git_timeout(*args: Any, **kwargs: Any) -> Any:
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=kwargs["timeout"])

    monkeypatch.setattr(okx_demo_runtime_module.subprocess, "run", git_timeout)
    assert (
        OkxDemoPaperRuntimeController._hosted_oco_terminal_exit_ids_from_recovered_events(
            [event],
            current_head=current_head,
        )
        == set()
    )


def test_incident_recovery_already_flat_binds_hosted_oco_exit_before_private_ws(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = _hosted_oco_terminal_exit_snapshot()
    controller, client, authorization = _flat_incident_recovery_controller(tmp_path)
    authorization.update(
        {
            "opening_cl_ord_id": "btcDP20a8d1650001",
            "opening_order_id": "3816659792351170560",
            "opening_fill_id": "4318943831",
            "opening_fill_id": "4318943831",
            "algo_cl_ord_id": "btcDP20a8d1650001A",
            "algo_id": "3816659794069377024",
                "expected_close_cl_ord_id": "O3821053454550453248",
                "failed_receipt_source_head": (
                    "904296e6a0758a138964f3fb801ceeba8cd9ad7e"
                ),
                "recovery_binding_path": "opaque-test-binding",
            "recovery_binding_schema_version": (
                "btc_okx_demo_flat_hosted_exit_binding_v1"
            ),
            "recovery_binding_source": (
                "immutable_flat_hosted_exit_receipt_bundle"
            ),
            "flat_identity_sha256": (
                okx_demo_runtime_module._incident_recovery_flat_identity_sha256(
                    snapshot,
                    owned_client_order_ids=(
                        "btcDP20a8d1650001",
                        "O3821053454550453248",
                    ),
                )
            ),
        }
    )
    controller._state["risk_control"]["mode"] = "FROZEN_UNKNOWN"
    controller._state["risk_control"]["pending_order_intents"] = {
        "btcDP20a8d1650001": {
            "client_order_id": "btcDP20a8d1650001",
            "risk_reducing_only": False,
            "action": "open_long",
            "status": "terminal",
            "order": {
                "instId": "BTC-USDT-SWAP",
                "side": "buy",
                "posSide": "long",
                "ordType": "fok",
                "sz": "0.01",
                "clOrdId": "btcDP20a8d1650001",
                "tag": "btcP0Demo",
            },
        }
    }
    controller._state["risk_control"]["owned_attached_algos"] = {
        "btcDP20a8d1650001A": {
            "algo_id": "3816659794069377024",
            "algo_client_order_id": "btcDP20a8d1650001A",
            "parent_client_order_id": "btcDP20a8d1650001",
            "instrument_id": "BTC-USDT-SWAP",
            "opening_intent": True,
            "status": "terminal",
        }
    }
    controller._collect_exchange_snapshot = lambda _client: json.loads(  # type: ignore[method-assign]
        json.dumps(snapshot)
    )
    monkeypatch.setattr(
        controller,
        "_incident_recovery_binding_blockers",
        lambda _auth, **_kwargs: [],
    )
    monkeypatch.setattr(controller, "_incident_recovery_flat_durable_identity_blockers", lambda _auth: [])

    class HostedExitPrivateWS(IncidentRecoveryPrivateWS):
        def run_startup_reconnect_probe(self) -> dict[str, Any]:
            owned_ids = set(self.kwargs["owned_client_order_ids"]())
            assert "btcDP20a8d1650001" in owned_ids
            assert "O3821053454550453248" in owned_ids
            assert "btcDPforeign0001" not in owned_ids
            return super().run_startup_reconnect_probe()

    controller._private_ws_factory = HostedExitPrivateWS
    result = controller.recover_fault_drill_incident(authorization=authorization)

    assert result["decision"] == "incident_recovery_completed_safe_flat"
    assert client.posts == []
    assert "O3821053454550453248" in controller._owned_client_order_ids
    assert any(
        event["event_type"] == "hosted_oco_terminal_exit_ownership_projection"
        for event in controller.status()["events"]
    )

    controller.finalize_incident_recovery_local()
    restarted = OkxDemoPaperRuntimeController(
        config=OkxDemoPaperRuntimeConfig(
            repo_root=Path.cwd(),
            data_db_path=controller.config.data_db_path,
            output_dir=controller.config.output_dir,
        ),
        start_worker=False,
    )
    restarted_status = restarted.status()
    assert restarted_status["runtime"]["status"] == "blocked_fail_closed"
    assert "okx_demo_previous_cancel_only_state_invalid" not in (
        restarted_status["runtime"]["blockers"]
    )
    assert "okx_demo_previous_runtime_risk_mode_not_frozen" not in (
        restarted_status["runtime"]["blockers"]
    )
    assert restarted_status["risk_control"]["owned_id_restore"]["enabled"] is False
    assert (
        restarted_status["risk_control"]["owned_id_restore"]
        ["order_capability_restored"]
        is False
    )
    assert "btcDP20a8d1650001" in restarted._owned_client_order_ids
    assert "O3821053454550453248" in restarted._owned_client_order_ids
    assert restarted._thread is None
    assert restarted._dead_man_thread is None
    assert restarted._client is None
    assert restarted._private_ws is None


def test_incident_recovery_already_flat_is_read_only_and_clears_freeze(
    tmp_path: Path,
) -> None:
    controller, client, authorization = _flat_incident_recovery_controller(
        tmp_path
    )

    result = controller.recover_fault_drill_incident(
        authorization=authorization
    )

    assert result["decision"] == "incident_recovery_completed_safe_flat"
    assert result["orders_posted"] == 0
    assert result["no_order_or_cancel_post"] is True
    assert result["private_ws_reconciled"] is True
    assert result["ledger_reconciled"] is True
    assert result["final_flat"] is True
    assert result["final_no_pending_orders"] is True
    assert result["final_no_pending_algo_orders"] is True
    assert result["final_no_unresolved_intents"] is True
    assert result["final_ledger_reconciled"] is True
    assert result["final_private_ws_reconciled"] is True
    assert result["entry_order_id"] == "opening-order-1"
    assert result["close_order_id"] == "close-order-1"
    assert result["entry_fill_ids"] == ["opening-fill-1"]
    assert result["close_fill_ids"] == ["close-fill-1"]
    assert result["algo_id"] == "algo-incident-1"
    assert client.posts == []
    assert (
        controller.status()["risk_control"]["mode"]
        == "STARTUP_RECONCILING"
    )
    assert controller.status()["runtime"]["opening_allowed"] is False

    finalized = controller.finalize_incident_recovery_local()
    assert finalized["risk_control"]["mode"] == "FROZEN_UNKNOWN"
    assert finalized["runtime"]["active"] is False
    assert finalized["runtime"]["opening_allowed"] is False
    assert finalized["runtime"]["cancel_only"] is True
    assert finalized["private_ws"]["cleanup_complete"] is True
    assert client.posts == []

    restarted = OkxDemoPaperRuntimeController(
        config=controller.config,
        start_worker=False,
    )
    restarted_status = restarted.status()
    assert restarted_status["runtime"]["active"] is False
    assert restarted_status["runtime"]["opening_allowed"] is False
    assert restarted_status["runtime"]["cancel_only"] is True
    assert restarted_status["runtime"]["status"] == "blocked_fail_closed"
    assert "okx_demo_previous_cancel_only_state_invalid" not in (
        restarted_status["runtime"]["blockers"]
    )
    assert "okx_demo_previous_runtime_risk_mode_not_frozen" not in (
        restarted_status["runtime"]["blockers"]
    )
    assert restarted_status["risk_control"]["mode"] == "FROZEN_UNKNOWN"
    assert restarted_status["risk_control"]["owned_id_restore"]["enabled"] is False
    assert (
        restarted_status["risk_control"]["owned_id_restore"]
        ["order_capability_restored"]
        is False
    )
    assert "btcDPfailed0001" in restarted._owned_client_order_ids
    assert restarted._thread is None
    assert restarted._dead_man_thread is None
    assert restarted._client is None
    assert restarted._private_ws is None


def test_incident_recovery_already_flat_applies_latest_ledger_snapshot(
    tmp_path: Path,
) -> None:
    controller, client, authorization = _flat_incident_recovery_controller(
        tmp_path
    )
    controller._commit_ledger_reconciliation = (  # type: ignore[method-assign]
        OkxDemoPaperRuntimeController._commit_ledger_reconciliation.__get__(
            controller,
            OkxDemoPaperRuntimeController,
        )
    )
    original_collect = controller._collect_exchange_snapshot
    collect_calls = 0

    def collect_with_dynamic_ledger_fact(read_client: Any) -> dict[str, Any]:
        nonlocal collect_calls
        collect_calls += 1
        snapshot = original_collect(read_client)
        if collect_calls >= 3:
            snapshot["balance"]["equity_usdt"] = "101"
        return snapshot

    controller._collect_exchange_snapshot = (  # type: ignore[method-assign]
        collect_with_dynamic_ledger_fact
    )

    result = controller.recover_fault_drill_incident(
        authorization=authorization
    )

    ledger = controller._state["ledger_reconciliation"]
    assert result["decision"] == "incident_recovery_completed_safe_flat"
    assert result["ledger_reconciled"] is True
    assert controller._state["exchange"]["balance"]["equity_usdt"] == "101"
    assert ledger["status"] == "reconciled"
    assert ledger["current_state_exchange_snapshot_match"] is True
    assert client.posts == []


def test_incident_recovery_already_flat_identity_drift_is_zero_post(
    tmp_path: Path,
) -> None:
    controller, client, authorization = _flat_incident_recovery_controller(
        tmp_path
    )
    original_collect = controller._collect_exchange_snapshot
    call_count = 0

    def collect_with_drift(read_client: Any) -> dict[str, Any]:
        nonlocal call_count
        call_count += 1
        snapshot = original_collect(read_client)
        if call_count >= 2:
            snapshot["fills"][0]["fill_id"] = "drifted-fill"
        return snapshot

    controller._collect_exchange_snapshot = collect_with_drift  # type: ignore[method-assign]

    with pytest.raises(
        OkxDemoPaperRuntimeError,
        match="incident_recovery_flat_snapshot_changed",
    ):
        controller.recover_fault_drill_incident(
            authorization=authorization
        )
    assert client.posts == []


def test_flat_identity_missing_fill_order_ids_matches_current_snapshot() -> None:
    historical_snapshot = _incident_recovery_snapshot()
    historical_snapshot["positions"] = [
        {
            "instrument_id": "BTC-USDT-SWAP",
            "position_side": "long",
            "contracts": "0",
        }
    ]
    historical_snapshot["pending_algo_orders"] = []
    historical_snapshot["orders"].append(
        {
            "order_id": "close-order-1",
            "client_order_id": "btcDPrecover0002",
            "instrument_id": "BTC-USDT-SWAP",
            "side": "sell",
            "position_side": "long",
            "order_type": "ioc",
            "size": "0.01",
            "state": "filled",
        }
    )
    historical_snapshot["fills"].append(
        {
            "fill_id": "close-fill-1",
            "client_order_id": "btcDPrecover0002",
            "instrument_id": "BTC-USDT-SWAP",
            "side": "sell",
            "position_side": "long",
            "size": "0.01",
        }
    )
    for fill in historical_snapshot["fills"]:
        fill.pop("order_id", None)
    current_snapshot = json.loads(json.dumps(historical_snapshot))
    current_snapshot["fills"][0]["order_id"] = "opening-order-1"
    current_snapshot["fills"][1]["order_id"] = "close-order-1"
    owned_ids = ("btcDPfailed0001", "btcDPrecover0002")

    assert okx_demo_runtime_module._incident_recovery_flat_identity_sha256(
        historical_snapshot,
        owned_client_order_ids=owned_ids,
    ) == okx_demo_runtime_module._incident_recovery_flat_identity_sha256(
        current_snapshot,
        owned_client_order_ids=owned_ids,
    )


def test_flat_identity_missing_fill_order_id_ambiguous_mapping_is_zero_post(
    tmp_path: Path,
) -> None:
    controller, client, authorization = _flat_incident_recovery_controller(
        tmp_path
    )
    original_collect = controller._collect_exchange_snapshot

    def collect_with_ambiguous_mapping(read_client: Any) -> dict[str, Any]:
        snapshot = original_collect(read_client)
        snapshot["fills"][0].pop("order_id", None)
        snapshot["orders"].append(
            {
                **dict(snapshot["orders"][0]),
                "order_id": "opening-order-duplicate",
            }
        )
        return snapshot

    controller._collect_exchange_snapshot = collect_with_ambiguous_mapping  # type: ignore[method-assign]

    with pytest.raises(
        OkxDemoPaperRuntimeError,
        match=(
            "okx_demo_flat_fill_order_id_mapping_ambiguous:"
            "btcDPfailed0001"
        ),
    ):
        controller.recover_fault_drill_incident(
            authorization=authorization
        )
    assert client.posts == []


def test_incident_recovery_allows_only_dynamic_valuation_drift_before_post(
    tmp_path: Path,
) -> None:
    controller, client = _incident_recovery_controller(tmp_path)
    original_collect = controller._collect_exchange_snapshot
    query_number = 0

    def collect_with_dynamic_valuation_drift(read_client: Any) -> dict[str, Any]:
        nonlocal query_number
        query_number += 1
        snapshot = original_collect(read_client)
        dynamic_suffix = str(query_number)
        server_time_ms = int(snapshot["server_time_ms"]) + query_number
        snapshot["captured_at_utc"] = (
            datetime.now(timezone.utc) + timedelta(microseconds=query_number)
        ).isoformat()
        snapshot["server_time_ms"] = str(server_time_ms)
        snapshot["balance"].update(
            {
                "equity_usdt": f"100.{dynamic_suffix}",
                "available_usdt": f"99.{dynamic_suffix}",
                "unrealized_pnl_usdt": f"0.{dynamic_suffix}",
                "timestamp_ms": str(server_time_ms),
            }
        )
        snapshot["mark"]["mark_price"] = f"60000.{dynamic_suffix}"
        snapshot["index"]["index_price"] = f"59999.{dynamic_suffix}"
        for position in snapshot["positions"]:
            position.update(
                {
                    "mark_price": f"60000.{dynamic_suffix}",
                    "liquidation_price": f"40000.{dynamic_suffix}",
                    "unrealized_pnl": f"0.{dynamic_suffix}",
                    "updated_at_ms": str(server_time_ms),
                }
            )
        return snapshot

    controller._collect_exchange_snapshot = collect_with_dynamic_valuation_drift  # type: ignore[method-assign]

    result = controller.recover_fault_drill_incident(
        authorization=_incident_recovery_authorization()
    )

    assert result["decision"] == "incident_recovery_completed_safe_flat"
    assert result["final_flat"] is True
    assert result["final_no_pending_orders"] is True
    assert result["final_no_pending_algo_orders"] is True
    assert result["final_ledger_reconciled"] is True
    assert result["final_private_ws_reconciled"] is True
    assert client.posts == ["order", "cancel-algos"]


@pytest.mark.parametrize(
    ("mutation", "expected_error"),
    [
        ("order_state", "incident_recovery_opening_fill_mismatch"),
        ("fill_id", "incident_recovery_opening_fill_mismatch"),
        ("fill_state", "incident_recovery_snapshot_changed"),
        ("position_contracts", "incident_recovery_position_mismatch"),
        ("position_average_price", "incident_recovery_snapshot_changed"),
        ("pending_order_identity", "incident_recovery_extra_pending_order"),
        ("oco_identity", "incident_recovery_pending_oco_mismatch"),
        ("oco_state", "incident_recovery_pending_oco_mismatch"),
        ("oco_size", "incident_recovery_pending_oco_mismatch"),
        ("oco_take_profit", "incident_recovery_pending_oco_mismatch"),
        ("oco_stop_loss", "incident_recovery_pending_oco_mismatch"),
        ("funding_ledger_fact", "incident_recovery_snapshot_changed"),
    ],
)
def test_incident_recovery_stable_identity_drift_is_zero_post_fail_closed(
    tmp_path: Path,
    mutation: str,
    expected_error: str,
) -> None:
    controller, client = _incident_recovery_controller(tmp_path)
    original_collect = controller._collect_exchange_snapshot
    query_number = 0

    def collect_with_stable_identity_drift(read_client: Any) -> dict[str, Any]:
        nonlocal query_number
        query_number += 1
        snapshot = original_collect(read_client)
        if query_number == 1 or client.posts:
            return snapshot
        if mutation == "order_state":
            snapshot["orders"][0]["state"] = "canceled"
        elif mutation == "fill_id":
            snapshot["fills"][0]["fill_id"] = "different-fill-id"
        elif mutation == "fill_state":
            snapshot["fills"][0]["state"] = "reversed"
        elif mutation == "position_contracts":
            snapshot["positions"][0]["contracts"] = "0.02"
        elif mutation == "position_average_price":
            snapshot["positions"][0]["average_price"] = "64575.8"
        elif mutation == "pending_order_identity":
            snapshot["pending_orders"] = [
                {
                    "order_id": "unknown-order",
                    "client_order_id": "unknown-client",
                    "instrument_id": "BTC-USDT-SWAP",
                    "state": "live",
                    "size": "0.01",
                }
            ]
        elif mutation == "oco_identity":
            snapshot["pending_algo_orders"][0]["algo_id"] = "different-algo"
        elif mutation == "oco_state":
            snapshot["pending_algo_orders"][0]["state"] = "effective"
        elif mutation == "oco_size":
            snapshot["pending_algo_orders"][0]["size"] = "0.02"
        elif mutation == "oco_take_profit":
            snapshot["pending_algo_orders"][0]["take_profit_trigger"] = "65867.2"
        elif mutation == "oco_stop_loss":
            snapshot["pending_algo_orders"][0]["stop_loss_order_price"] = "63929.9"
        elif mutation == "funding_ledger_fact":
            snapshot["bills"] = [
                {
                    "bill_id": "funding-drift-1",
                    "instrument_id": "BTC-USDT-SWAP",
                    "currency": "USDT",
                    "type": "8",
                    "sub_type": "173",
                    "balance_change": "-0.001",
                    "fee": "0",
                    "pnl": "0",
                    "timestamp_ms": "1786000000000",
                }
            ]
        else:  # pragma: no cover - parametrization owns the cases
            raise AssertionError(f"unknown mutation: {mutation}")
        return snapshot

    controller._collect_exchange_snapshot = collect_with_stable_identity_drift  # type: ignore[method-assign]

    with pytest.raises(OkxDemoPaperRuntimeError, match=expected_error):
        controller.recover_fault_drill_incident(
            authorization=_incident_recovery_authorization()
        )

    assert client.posts == []


def test_incident_recovery_binding_missing_blocks_before_private_read_or_post(
    tmp_path: Path,
) -> None:
    controller, client = _incident_recovery_controller(tmp_path)
    authorization = _incident_recovery_authorization()
    runtime_root = Path(controller.config.output_dir).resolve()
    controller._persist_state()
    (runtime_root / "events.jsonl").write_bytes(b"")
    state_hash = hashlib.sha256((runtime_root / "state.json").read_bytes()).hexdigest()
    events_hash = hashlib.sha256((runtime_root / "events.jsonl").read_bytes()).hexdigest()
    authorization.update(
        {
            "recovery_binding_path": str(tmp_path / "missing-binding.json"),
            "recovery_binding_sha256": "a" * 64,
            "recovery_runtime_root": str(
                tmp_path / "output" / "btc_demo_paper_runtime"
            ),
        }
    )
    with pytest.raises(
        OkxDemoPaperRuntimeError,
        match="incident_recovery_binding_missing",
    ):
        controller.recover_fault_drill_incident(authorization=authorization)
    assert client.private_get_calls == []
    assert client.posts == []
    assert hashlib.sha256((runtime_root / "state.json").read_bytes()).hexdigest() == state_hash
    assert hashlib.sha256((runtime_root / "events.jsonl").read_bytes()).hexdigest() == events_hash
    assert not (runtime_root / ".btc_okx_demo_fault_drill_writer.lock").exists()


def test_cross_head_writer_lock_preserves_incident_source_before_rewrite(
    tmp_path: Path,
) -> None:
    controller, client = _incident_recovery_controller(tmp_path)
    root = Path(controller.config.output_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    lock_path = root / ".btc_okx_demo_fault_drill_writer.lock"
    incident_source_head = "b" * 40
    lock_path.write_text(
        json.dumps(
            {
                "nonce": "original",
                "process_id": 1,
                "source_head": incident_source_head,
                "runtime_root_sha256": okx_demo_runtime_module._canonical_sha256(
                    str(root)
                ),
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    controller.acquire_fault_drill_process_lock(
        nonce="crosshead",
        writer_context={"incident_source_head": incident_source_head},
    )
    controller.release_fault_drill_process_lock()
    marker = json.loads(lock_path.read_text(encoding="utf-8"))
    assert marker["source_head"] == incident_source_head
    assert marker["recovery_code_head"] == _repo_head_for_test()
    assert client.private_get_calls == []
    assert client.posts == []


def test_cross_head_writer_lock_rejects_preexisting_current_source_marker(
    tmp_path: Path,
) -> None:
    controller, client = _incident_recovery_controller(tmp_path)
    root = Path(controller.config.output_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    lock_path = root / ".btc_okx_demo_fault_drill_writer.lock"
    lock_path.write_text(
        json.dumps(
            {
                "nonce": "original",
                "process_id": 1,
                "source_head": _repo_head_for_test(),
                "runtime_root_sha256": okx_demo_runtime_module._canonical_sha256(
                    str(root)
                ),
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    with pytest.raises(
        OkxDemoPaperRuntimeError,
        match="runtime_root_writer_lock_source_mismatch",
    ):
        controller.acquire_fault_drill_process_lock(
            nonce="crosshead",
            writer_context={"incident_source_head": "b" * 40},
        )
    marker = json.loads(lock_path.read_text(encoding="utf-8"))
    assert marker["source_head"] == _repo_head_for_test()
    assert "recovery_code_head" not in marker
    assert client.private_get_calls == []
    assert client.posts == []


def test_canonical_recovery_session_preserves_owner_provenance_and_locked_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    controller, client = _incident_recovery_controller(tmp_path)
    controller._persist_state()
    root = Path(controller.config.output_dir).resolve()
    (root / "events.jsonl").write_bytes(b"")
    root.mkdir(parents=True, exist_ok=True)
    lock_path = root / ".btc_okx_demo_fault_drill_writer.lock"
    incident_source_head = "b" * 40
    original_marker = {
        "nonce": "incident-owner",
        "process_id": 4321,
        "source_head": incident_source_head,
        "runtime_root_sha256": okx_demo_runtime_module._canonical_sha256(
            str(root)
        ),
    }
    original_raw = json.dumps(
        original_marker,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    lock_path.write_bytes(original_raw)
    binding_path = tmp_path / "binding.json"
    binding_path.write_bytes(b"binding")
    preflight = {
        "owner_marker": okx_demo_runtime_module.OkxDemoPaperRuntimeController._owner_marker_snapshot(
            original_raw
        ),
        "binding_path": str(binding_path.resolve()),
        "binding_sha256": hashlib.sha256(binding_path.read_bytes()).hexdigest(),
        "state_sha256": hashlib.sha256((root / "state.json").read_bytes()).hexdigest(),
        "events_sha256": hashlib.sha256((root / "events.jsonl").read_bytes()).hexdigest(),
    }
    state_hash = hashlib.sha256((root / "state.json").read_bytes()).hexdigest()
    events_hash = hashlib.sha256((root / "events.jsonl").read_bytes()).hexdigest()

    controller.acquire_fault_drill_process_lock(
        nonce="canonicalowner",
        writer_context={"incident_source_head": incident_source_head},
        preflight=preflight,
    )
    marker = dict(controller._fault_drill_owner_marker_session["marker"])
    assert marker["source_head"] == incident_source_head
    assert marker["recovery_code_head"] == _repo_head_for_test()
    assert marker["original_owner_marker_sha256"] == hashlib.sha256(
        original_raw
    ).hexdigest()
    assert marker["original_owner_marker"]["nonce"] == "incident-owner"

    original_read_text = Path.read_text

    def reject_locked_path_read(path: Path, *args: Any, **kwargs: Any) -> str:
        if path.resolve() == lock_path.resolve():
            raise AssertionError("locked owner marker must use the held handle")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", reject_locked_path_read)
    # A re-entrant canonical check must use the already locked handle, not a
    # second Path read that is denied on Windows while the lock is held.
    assert controller.acquire_fault_drill_process_lock(
        nonce="canonicalowner",
        writer_context={"incident_source_head": incident_source_head},
        preflight=preflight,
    )["acquired"] is True
    controller.release_fault_drill_process_lock()

    assert lock_path.read_bytes() == original_raw
    assert hashlib.sha256((root / "state.json").read_bytes()).hexdigest() == state_hash
    assert hashlib.sha256((root / "events.jsonl").read_bytes()).hexdigest() == events_hash
    assert client.private_get_calls == []
    assert client.posts == []


def test_flat_hosted_exit_lock_accepts_only_current_empty_bootstrap_marker(
    tmp_path: Path,
) -> None:
    """A fresh flat-hosted-exit root may need the one-byte Windows lock seed.

    The seed is acceptable only when this acquire call created it from the
    empty preflight marker.  A retained NUL marker is not an owner marker and
    must remain fail-closed; changes to the state captured by preflight must
    remain a TOCTOU failure.
    """

    def lock_inputs(
        *,
        existing_lock: bytes | None,
        missing_events: bool = False,
        nonzero_checkpoint: bool = False,
    ) -> tuple[
        OkxDemoPaperRuntimeController,
        IncidentRecoveryClient,
        Path,
        dict[str, Any],
        dict[str, str],
    ]:
        controller, client = _incident_recovery_controller(tmp_path)
        root = Path(controller.config.output_dir).resolve()
        if nonzero_checkpoint:
            controller._append_event(
                "preflight_test_event",
                {"test_only": True},
            )
        controller._persist_state()
        events_path = root / "events.jsonl"
        if missing_events:
            if events_path.exists():
                events_path.unlink()
        else:
            events_path.write_bytes(b"locked-event")
        lock_path = root / ".btc_okx_demo_fault_drill_writer.lock"
        if lock_path.exists():
            lock_path.unlink()
        if existing_lock is not None:
            lock_path.write_bytes(existing_lock)
        binding_path = tmp_path / "flat-hosted-exit-binding.json"
        binding_path.write_bytes(b"immutable-binding")
        raw = existing_lock if existing_lock is not None else b""
        preflight = {
            "owner_marker": (
                OkxDemoPaperRuntimeController._owner_marker_snapshot(raw)
            ),
            "binding_path": str(binding_path.resolve()),
            "binding_sha256": hashlib.sha256(binding_path.read_bytes()).hexdigest(),
            "state_sha256": hashlib.sha256((root / "state.json").read_bytes()).hexdigest(),
            "events_sha256": (
                hashlib.sha256(events_path.read_bytes()).hexdigest()
                if events_path.is_file()
                else ""
            ),
            "events_file_missing": missing_events,
        }
        context = {
            "incident_source_head": "b" * 40,
            "recovery_binding_schema_version": (
                "btc_okx_demo_flat_hosted_exit_binding_v1"
            ),
            "recovery_binding_source": (
                "immutable_flat_hosted_exit_receipt_bundle"
            ),
        }
        return controller, client, lock_path, preflight, context

    for existing_lock in (None, b""):
        controller, client, lock_path, preflight, context = lock_inputs(
            existing_lock=existing_lock
        )
        assert controller.acquire_fault_drill_process_lock(
            nonce="freshflatbootstrap",
            writer_context=context,
            preflight=preflight,
        )["acquired"] is True
        controller.release_fault_drill_process_lock()
        assert lock_path.read_bytes() == b""
        assert client.private_get_calls == []
        assert client.posts == []

    controller, client, lock_path, preflight, context = lock_inputs(
        existing_lock=None,
        missing_events=True,
    )
    assert controller.acquire_fault_drill_process_lock(
        nonce="freshflatmissingevents",
        writer_context=context,
        preflight=preflight,
    )["acquired"] is True
    controller.release_fault_drill_process_lock()
    assert not (Path(controller.config.output_dir) / "events.jsonl").exists()
    assert lock_path.read_bytes() == b""
    assert client.private_get_calls == []
    assert client.posts == []

    # This is the external fresh-root shape: no checkpoint and no event log
    # existed before this same acquire seeded its Windows NUL lock byte.
    fresh_controller, fresh_client = _incident_recovery_controller(
        tmp_path / "fresh-no-state-or-events"
    )
    fresh_root = Path(fresh_controller.config.output_dir).resolve()
    fresh_root.mkdir(parents=True, exist_ok=True)
    fresh_binding = tmp_path / "fresh-no-state-or-events-binding.json"
    fresh_binding.write_bytes(b"immutable-binding")
    fresh_preflight = {
        "owner_marker": (
            OkxDemoPaperRuntimeController._owner_marker_snapshot(b"")
        ),
        "binding_path": str(fresh_binding.resolve()),
        "binding_sha256": hashlib.sha256(fresh_binding.read_bytes()).hexdigest(),
        "state_sha256": "",
        "events_sha256": "",
        "events_file_missing": True,
    }
    assert fresh_controller.acquire_fault_drill_process_lock(
        nonce="freshflatmissingstate",
        writer_context=context,
        preflight=fresh_preflight,
    )["acquired"] is True
    fresh_controller.release_fault_drill_process_lock()
    assert not (fresh_root / "state.json").exists()
    assert not (fresh_root / "events.jsonl").exists()
    assert (fresh_root / ".btc_okx_demo_fault_drill_writer.lock").read_bytes() == b""
    assert fresh_client.private_get_calls == []
    assert fresh_client.posts == []

    # The narrow exception is lost as soon as either absent durable file
    # appears after preflight; it must not become a generic empty-root bypass.
    state_after_preflight = fresh_root / "state.json"
    state_after_preflight.write_bytes(b"state-created-after-preflight")
    with pytest.raises(
        OkxDemoPaperRuntimeError,
        match="runtime_root_writer_lock_preflight_changed",
    ):
        fresh_controller.acquire_fault_drill_process_lock(
            nonce="freshflatstatecreated",
            writer_context=context,
            preflight=fresh_preflight,
        )
    state_after_preflight.unlink()
    events_after_preflight = fresh_root / "events.jsonl"
    events_after_preflight.write_bytes(b"event-created-after-preflight")
    with pytest.raises(
        OkxDemoPaperRuntimeError,
        match="runtime_root_writer_lock_preflight_changed",
    ):
        fresh_controller.acquire_fault_drill_process_lock(
            nonce="freshflateventscreated",
            writer_context=context,
            preflight=fresh_preflight,
        )
    assert fresh_client.private_get_calls == []
    assert fresh_client.posts == []

    controller, client, lock_path, preflight, context = lock_inputs(
        existing_lock=b"\0"
    )
    with pytest.raises(
        OkxDemoPaperRuntimeError,
        match="runtime_root_writer_lock_preflight_changed",
    ):
        controller.acquire_fault_drill_process_lock(
            nonce="retainednulmarker",
            writer_context=context,
            preflight=preflight,
        )
    assert lock_path.read_bytes() == b"\0"
    assert client.private_get_calls == []
    assert client.posts == []

    controller, client, _lock_path, preflight, context = lock_inputs(
        existing_lock=None,
        missing_events=True,
        nonzero_checkpoint=True,
    )
    with pytest.raises(
        OkxDemoPaperRuntimeError,
        match="runtime_root_writer_lock_preflight_changed",
    ):
        controller.acquire_fault_drill_process_lock(
            nonce="nonzeroeventchain",
            writer_context=context,
            preflight=preflight,
        )
    assert client.private_get_calls == []
    assert client.posts == []

    controller, client, _lock_path, preflight, context = lock_inputs(
        existing_lock=None
    )
    root = Path(controller.config.output_dir).resolve()
    (root / "state.json").write_bytes(b"state-tampered-after-preflight")
    with pytest.raises(
        OkxDemoPaperRuntimeError,
        match="runtime_root_writer_lock_preflight_changed",
    ):
        controller.acquire_fault_drill_process_lock(
            nonce="preflighttoctou",
            writer_context=context,
            preflight=preflight,
        )
    assert client.private_get_calls == []
    assert client.posts == []

    controller, client, _lock_path, preflight, context = lock_inputs(
        existing_lock=None,
        missing_events=True,
    )
    (Path(controller.config.output_dir) / "events.jsonl").write_bytes(
        b"event-created-after-preflight"
    )
    with pytest.raises(
        OkxDemoPaperRuntimeError,
        match="runtime_root_writer_lock_preflight_changed",
    ):
        controller.acquire_fault_drill_process_lock(
            nonce="eventstoctou",
            writer_context=context,
            preflight=preflight,
        )
    assert client.private_get_calls == []
    assert client.posts == []

    controller, client, _lock_path, preflight, _context = lock_inputs(
        existing_lock=None
    )
    with pytest.raises(
        OkxDemoPaperRuntimeError,
        match="runtime_root_writer_lock_preflight_changed",
    ):
        controller.acquire_fault_drill_process_lock(
            nonce="ordinaryv2bootstrap",
            writer_context={"incident_source_head": "b" * 40},
            preflight=preflight,
        )
    assert client.private_get_calls == []
    assert client.posts == []


def test_v1_binding_cannot_be_consumed_as_cross_head_canonical_binding(
    tmp_path: Path,
) -> None:
    controller, client = _incident_recovery_controller(tmp_path)
    authorization = _incident_recovery_authorization()
    root = Path(controller.config.output_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    (root / ".btc_okx_demo_fault_drill_writer.lock").write_text(
        json.dumps(
            {
                "nonce": "original",
                "process_id": 1,
                "source_head": authorization["failed_receipt_source_head"],
                "runtime_root_sha256": okx_demo_runtime_module._canonical_sha256(
                    str(root)
                ),
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    authorization.update(
        {
            "recovery_binding_path": str(tmp_path / "v1-binding.json"),
            "recovery_binding_sha256": "a" * 64,
            "recovery_runtime_root": str(
                tmp_path / "output" / "btc_demo_paper_runtime"
            ),
            "recovery_binding_schema_version": (
                "btc_okx_demo_recovery_binding_v1"
            ),
            "incident_source_head": authorization["failed_receipt_source_head"],
            "recovery_code_head": authorization["runtime_source_head"],
            "recovery_ancestry_proof": "{}",
        }
    )
    with pytest.raises(
        OkxDemoPaperRuntimeError,
        match="incident_recovery_binding_missing",
    ):
        controller.recover_fault_drill_incident(authorization=authorization)
    assert client.private_get_calls == []
    assert client.posts == []


def test_incident_recovery_consumer_accepts_only_ticket24_multihop_ancestry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The runtime consumer must mirror Ticket24's bounded two-edge proof."""

    del tmp_path
    current_head = _repo_head_for_test()
    marker_head = subprocess.run(
        ["git", "rev-parse", "HEAD~1"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    incident_head = subprocess.run(
        ["git", "rev-parse", "HEAD~2"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    def merge_base(ancestor: str, descendant: str) -> str:
        return subprocess.run(
            ["git", "merge-base", ancestor, descendant],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    proof = {
        "method": "git merge-base and git merge-base --is-ancestor",
        "incident_source_head": incident_head,
        "recovery_code_head": current_head,
        "merge_base": merge_base(incident_head, current_head),
        "incident_is_ancestor": True,
        "recovery_is_ancestor_of_incident": False,
        "owner_marker_multihop": {
            "method": "git merge-base and git merge-base --is-ancestor",
            "incident_source_head": incident_head,
            "marker_recovery_code_head": marker_head,
            "recovery_code_head": current_head,
            "incident_to_marker_merge_base": merge_base(incident_head, marker_head),
            "marker_to_recovery_merge_base": merge_base(marker_head, current_head),
            "incident_is_marker_ancestor": True,
            "marker_is_recovery_ancestor": True,
        },
    }
    assert okx_demo_runtime_module._incident_recovery_ancestry_proof_is_valid(
        repo_root=Path.cwd(),
        incident_source_head=incident_head,
        marker_recovery_code_head=marker_head,
        current_head=current_head,
        proof=proof,
    )

    single_hop_proof = {
        key: value for key, value in proof.items() if key != "owner_marker_multihop"
    }
    assert okx_demo_runtime_module._incident_recovery_ancestry_proof_is_valid(
        repo_root=Path.cwd(),
        incident_source_head=incident_head,
        marker_recovery_code_head=incident_head,
        current_head=current_head,
        proof=single_hop_proof,
    )
    same_head_proof = {
        "method": "git merge-base and git merge-base --is-ancestor",
        "incident_source_head": current_head,
        "recovery_code_head": current_head,
        "merge_base": merge_base(current_head, current_head),
        "incident_is_ancestor": True,
        "recovery_is_ancestor_of_incident": True,
    }
    assert okx_demo_runtime_module._incident_recovery_ancestry_proof_is_valid(
        repo_root=Path.cwd(),
        incident_source_head=current_head,
        marker_recovery_code_head=current_head,
        current_head=current_head,
        proof=same_head_proof,
    )

    tampered = json.loads(json.dumps(proof))
    tampered["owner_marker_multihop"]["marker_is_recovery_ancestor"] = False
    assert not okx_demo_runtime_module._incident_recovery_ancestry_proof_is_valid(
        repo_root=Path.cwd(),
        incident_source_head=incident_head,
        marker_recovery_code_head=marker_head,
        current_head=current_head,
        proof=tampered,
    )

    monkeypatch.setattr(
        okx_demo_runtime_module,
        "_bounded_git_ancestry_probe",
        lambda *_args: None,
        raising=False,
    )
    assert not okx_demo_runtime_module._incident_recovery_ancestry_proof_is_valid(
        repo_root=Path.cwd(),
        incident_source_head=incident_head,
        marker_recovery_code_head=marker_head,
        current_head=current_head,
        proof=proof,
    )


def test_incident_recovery_binding_consumer_accepts_verified_multihop_marker_and_append_only_recovery_tail(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A legacy state may rely on the verified terminal event-head segment."""

    controller, client = _incident_recovery_controller(tmp_path)
    root = Path(controller.config.output_dir).resolve()
    root.mkdir(parents=True)
    current_head = _repo_head_for_test()
    historical_head = "cf58b54b3f96cd0319e6aa321325a975f359e8f8"
    intermediate_head = "8ccc2b3d3377eadcf14afc21414432ccff372083"
    incident_head = "42254df953a31881c532c653c0f0e72a7bd70224"
    marker_head = subprocess.run(
        ["git", "rev-parse", "HEAD~1"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert subprocess.run(
        ["git", "merge-base", "--is-ancestor", incident_head, current_head],
        check=False,
    ).returncode == 0
    run_id = "c6bc287f4bc44c8a97333eac88caf77e"
    namespace = "btcDPc6bc287f"
    root_sha = okx_demo_runtime_module._canonical_sha256(str(root))
    state_path = root / "state.json"
    events_path = root / "events.jsonl"
    state_path.write_bytes(b"offline-state")
    events_path.write_bytes(b"offline-events")
    lock = {
        "nonce": "multihop-owner",
        "process_id": 1,
        "source_head": incident_head,
        "recovery_code_head": marker_head,
        "runtime_root_sha256": root_sha,
    }
    lock_raw = json.dumps(lock, sort_keys=True).encode("utf-8")
    (root / ".btc_okx_demo_fault_drill_writer.lock").write_bytes(lock_raw)

    def merge_base(ancestor: str, descendant: str) -> str:
        return subprocess.run(
            ["git", "merge-base", ancestor, descendant],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    ancestry = {
        "method": "git merge-base and git merge-base --is-ancestor",
        "incident_source_head": incident_head,
        "recovery_code_head": current_head,
        "merge_base": merge_base(incident_head, current_head),
        "incident_is_ancestor": True,
        "recovery_is_ancestor_of_incident": False,
        "owner_marker_multihop": {
            "method": "git merge-base and git merge-base --is-ancestor",
            "incident_source_head": incident_head,
            "marker_recovery_code_head": marker_head,
            "recovery_code_head": current_head,
            "incident_to_marker_merge_base": merge_base(incident_head, marker_head),
            "marker_to_recovery_merge_base": merge_base(marker_head, current_head),
            "incident_is_marker_ancestor": True,
            "marker_is_recovery_ancestor": True,
        },
    }
    identity = {
        "opening_cl_ord_id": f"{namespace}0001",
        "opening_order_id": "opening-order",
        "opening_fill_id": "opening-fill",
        "algo_cl_ord_id": f"{namespace}0001A",
        "algo_id": "algo-id",
        "expected_close_cl_ord_id": f"{namespace}0002",
        "client_order_namespace": namespace,
        "account_identity": "account-identity",
        "credential_identity": "credential-identity",
    }
    runtime_doc = {
        "path": str(root),
        "sha256": root_sha,
        "source_head": incident_head,
        "recovery_code_head": current_head,
        "run_id": run_id,
        "state_sha256": hashlib.sha256(state_path.read_bytes()).hexdigest(),
        "events_sha256": hashlib.sha256(events_path.read_bytes()).hexdigest(),
        "ledger_sha256": okx_demo_runtime_module._canonical_sha256([]),
        "last_event_hash": "a" * 64,
        "last_sequence": 6,
    }
    document: dict[str, Any] = {
        "schema_version": "btc_okx_demo_recovery_binding_v2",
        "source_head": incident_head,
        "incident_source_head": incident_head,
        "recovery_code_head": current_head,
        "runtime_source_head": current_head,
        "ancestry_proof": ancestry,
        "runtime_root": runtime_doc,
        "failed_receipt": {
            "sha256": "b" * 64,
            "source_head": incident_head,
            "scenario": "post_response_loss",
            "run_id": "failed-run",
        },
        "identity": identity,
        "owner_marker": {
            "sha256": hashlib.sha256(lock_raw).hexdigest(),
            "source_head": incident_head,
            "recovery_code_head": marker_head,
            "runtime_root_sha256": root_sha,
        },
        "safety": {"opening_allowed": False, "live_allowed": False},
    }
    document["content_sha256"] = okx_demo_runtime_module._canonical_sha256(document)
    binding_path = tmp_path / "multihop-binding.json"
    binding_path.write_text(json.dumps(document, sort_keys=True), encoding="utf-8")
    authorization = {
        "recovery_binding_path": str(binding_path),
        "recovery_binding_sha256": hashlib.sha256(binding_path.read_bytes()).hexdigest(),
        "recovery_runtime_root": str(root),
        "recovery_binding_schema_version": document["schema_version"],
        "recovery_runtime_root_sha256": root_sha,
        "recovery_runtime_run_id": run_id,
        "recovery_runtime_state_sha256": runtime_doc["state_sha256"],
        "recovery_runtime_events_sha256": runtime_doc["events_sha256"],
        "recovery_runtime_ledger_sha256": runtime_doc["ledger_sha256"],
        "recovery_runtime_last_event_hash": runtime_doc["last_event_hash"],
        "recovery_runtime_last_sequence": "6",
        "recovery_client_order_namespace": namespace,
        "recovery_account_identity": identity["account_identity"],
        "recovery_credential_identity": identity["credential_identity"],
        "incident_source_head": incident_head,
        "recovery_code_head": current_head,
        "recovery_ancestry_proof": json.dumps(ancestry, sort_keys=True),
        "recovery_original_owner_marker_sha256": document["owner_marker"]["sha256"],
        "recovery_original_owner_marker_source_head": incident_head,
        "recovery_original_owner_marker_recovery_code_head": marker_head,
        "recovery_original_owner_marker_runtime_root_sha256": root_sha,
        "failed_receipt_sha256": "b" * 64,
        "failed_receipt_source_head": incident_head,
        "failed_receipt_scenario": "post_response_loss",
        "failed_receipt_run_id": "failed-run",
        **identity,
    }

    runtime_state = {
        "runtime": {"run_id": run_id, "source_head": marker_head}
    }

    class FakeRuntimeStore:
        def __init__(self, _root: Path) -> None:
            pass

        def recover(self) -> BTCRuntimeRecovery:
            return BTCRuntimeRecovery(
                state=runtime_state,
                events=(
                    {
                        "run_id": "legacy-historical-a",
                        "payload": {"source_head": historical_head},
                    },
                    {
                        "run_id": "legacy-historical-b",
                        "payload": {"source_head": intermediate_head},
                    },
                    {
                        "run_id": run_id,
                        "payload": {"source_head": incident_head},
                    },
                    {
                        "run_id": run_id,
                        "payload": {"source_head": incident_head},
                    },
                    {
                        "run_id": run_id,
                        "payload": {"source_head": marker_head},
                    },
                    {
                        "run_id": run_id,
                        "payload": {"source_head": marker_head},
                    },
                ),
                blockers=(),
                truncated_tail=False,
                last_sequence=6,
                last_event_hash="a" * 64,
            )

    monkeypatch.setattr(okx_demo_runtime_module, "BTCRuntimeStore", FakeRuntimeStore)
    blockers = controller._incident_recovery_binding_blockers(authorization)
    assert blockers == []
    assert client.private_get_calls == []
    assert client.posts == []

    runtime_state["runtime"]["source_head"] = ""
    assert controller._incident_recovery_binding_blockers(authorization) == [
        "okx_demo_incident_recovery_runtime_source_mismatch"
    ]
    assert client.private_get_calls == []
    assert client.posts == []


@pytest.mark.parametrize("state_source_head", (None, "", 7, "f" * 40))
def test_incident_recovery_source_chain_rejects_present_invalid_state_head(
    state_source_head: Any,
) -> None:
    current_head = _repo_head_for_test()
    run_id = "c6bc287f4bc44c8a97333eac88caf77e"
    events = (
        {
            "run_id": run_id,
            "payload": {"source_head": current_head},
        },
    )
    assert not okx_demo_runtime_module._incident_recovery_runtime_source_chain_is_valid(
        state={"runtime": {"run_id": run_id, "source_head": state_source_head}},
        events=events,
        incident_head=current_head,
        runtime_run_id=run_id,
        repo_root=Path.cwd(),
    )


def test_incident_recovery_source_chain_ignores_owned_id_restore_archive_provenance() -> None:
    current_head = _repo_head_for_test()
    archive_head = "904296e6a0758a138964f3fb801ceeba8cd9ad7e"
    run_id = "c6bc287f4bc44c8a97333eac88caf77e"
    events = (
        {
            "run_id": run_id,
            "event_type": "runtime_status",
            "payload": {"source_head": current_head},
        },
        {
            "run_id": run_id,
            "event_type": "owned_id_restore_applied",
            "payload": {"source_head": archive_head},
            "state_after": {
                "risk_control": {
                    "owned_id_restore": {"source_head": archive_head}
                }
            },
        },
        {
            "run_id": run_id,
            "payload": {"private_ws": {"source_head": current_head}},
            "state_after": {
                "risk_control": {
                    "owned_id_restore": {"source_head": archive_head}
                }
            },
        },
    )

    assert okx_demo_runtime_module._incident_recovery_runtime_source_chain_is_valid(
        state={"runtime": {"run_id": run_id, "source_head": current_head}},
        events=events,
        incident_head=current_head,
        runtime_run_id=run_id,
        repo_root=Path.cwd(),
    )


def test_incident_recovery_source_chain_ignores_owner_marker_audit_provenance() -> None:
    """S5 binding shape: runtime code head plus stale marker audit provenance."""

    incident_head = "509a1bf959e7f2895da130b4cb205af0f286c074"
    historical_marker_head = "b830fc862813fdcb965ad95b97208d3e7790ac9c"
    recovery_head = _repo_head_for_test()
    run_id = "718bddde0c5b4e7396d5b8d8e473423b"
    assert subprocess.run(
        ["git", "merge-base", "--is-ancestor", incident_head, recovery_head],
        check=False,
    ).returncode == 0
    events = (
        {
            "run_id": run_id,
            "event_type": "runtime_status",
            "payload": {"source_head": incident_head},
        },
        {
            "run_id": run_id,
            "event_type": "private_ws_reconciled",
            "payload": {"source_head": recovery_head},
            "state_after": {
                "runtime": {
                    "fresh_state_emergency_exit": {
                        "owner_marker_audit": {
                            "source_head": historical_marker_head,
                            "process_id": 40360,
                        }
                    }
                }
            },
        },
    )

    assert okx_demo_runtime_module._incident_recovery_runtime_source_chain_is_valid(
        state={"runtime": {"run_id": run_id, "source_head": recovery_head}},
        events=events,
        incident_head=incident_head,
        recovery_head=recovery_head,
        runtime_run_id=run_id,
        repo_root=Path.cwd(),
    )


def test_incident_recovery_source_chain_rejects_nested_mismatch_and_audit_only_head() -> None:
    current_head = _repo_head_for_test()
    historical_marker_head = "b830fc862813fdcb965ad95b97208d3e7790ac9c"
    run_id = "718bddde0c5b4e7396d5b8d8e473423b"

    assert okx_demo_runtime_module._incident_recovery_event_source_head(
        {
            "event_type": "runtime_status",
            "payload": {
                "source_head": current_head,
                "runtime_status": {"source_head": historical_marker_head},
            },
        }
    ) is None
    assert okx_demo_runtime_module._incident_recovery_event_source_head(
        {
            "event_type": "runtime_status",
            "payload": {
                "fresh_state_emergency_exit": {
                    "owner_marker_audit": {
                        "source_head": historical_marker_head,
                    }
                }
            },
        }
    ) == ""
    assert not okx_demo_runtime_module._incident_recovery_runtime_source_chain_is_valid(
        state={"runtime": {"run_id": run_id, "source_head": current_head}},
        events=(
            {
                "run_id": run_id,
                "event_type": "runtime_status",
                "payload": {
                    "fresh_state_emergency_exit": {
                        "owner_marker_audit": {
                            "source_head": historical_marker_head,
                        }
                    }
                },
            },
        ),
        incident_head=current_head,
        runtime_run_id=run_id,
        repo_root=Path.cwd(),
    )


def test_incident_recovery_source_chain_accepts_ancestry_interval_append_only_tail() -> None:
    incident_head = "0ed51dba33a526d643350b53dca542f7f7ecf44c"
    recovery_head = _repo_head_for_test()
    terminal_head = "4a7d6702dad4ae068abe122ded10fef2ce6c7711"
    run_id = "06c05f1d28b0455daa646c1f9e5482a9"
    events = (
        {"run_id": run_id, "payload": {"source_head": incident_head}},
        {"run_id": run_id, "payload": {"source_head": incident_head}},
        {"run_id": run_id, "payload": {"source_head": terminal_head}},
        {"run_id": run_id, "payload": {"source_head": terminal_head}},
    )

    assert okx_demo_runtime_module._incident_recovery_runtime_source_chain_is_valid(
        state={"runtime": {"run_id": run_id, "source_head": terminal_head}},
        events=events,
        incident_head=incident_head,
        recovery_head=recovery_head,
        runtime_run_id=run_id,
        repo_root=Path.cwd(),
    )


def test_incident_recovery_source_chain_rejects_terminal_outside_ancestry_interval() -> None:
    incident_head = "0ed51dba33a526d643350b53dca542f7f7ecf44c"
    recovery_head = _repo_head_for_test()
    outside_head = "f" * 40
    run_id = "06c05f1d28b0455daa646c1f9e5482a9"
    events = (
        {"run_id": run_id, "payload": {"source_head": incident_head}},
        {"run_id": run_id, "payload": {"source_head": outside_head}},
    )

    assert not okx_demo_runtime_module._incident_recovery_runtime_source_chain_is_valid(
        state={"runtime": {"run_id": run_id, "source_head": outside_head}},
        events=events,
        incident_head=incident_head,
        recovery_head=recovery_head,
        runtime_run_id=run_id,
        repo_root=Path.cwd(),
    )


def test_incident_recovery_source_chain_rejects_state_source_head_not_equal_to_terminal() -> None:
    incident_head = "0ed51dba33a526d643350b53dca542f7f7ecf44c"
    recovery_head = _repo_head_for_test()
    terminal_head = "4a7d6702dad4ae068abe122ded10fef2ce6c7711"
    run_id = "06c05f1d28b0455daa646c1f9e5482a9"
    events = (
        {"run_id": run_id, "payload": {"source_head": incident_head}},
        {"run_id": run_id, "payload": {"source_head": terminal_head}},
    )

    assert not okx_demo_runtime_module._incident_recovery_runtime_source_chain_is_valid(
        state={"runtime": {"run_id": run_id, "source_head": incident_head}},
        events=events,
        incident_head=incident_head,
        recovery_head=recovery_head,
        runtime_run_id=run_id,
        repo_root=Path.cwd(),
    )


def test_incident_recovery_source_chain_rejects_archive_source_in_ordinary_event() -> None:
    current_head = _repo_head_for_test()
    archive_head = "904296e6a0758a138964f3fb801ceeba8cd9ad7e"
    run_id = "c6bc287f4bc44c8a97333eac88caf77e"
    events = (
        {
            "run_id": run_id,
            "event_type": "runtime_status",
            "payload": {"source_head": current_head},
        },
        {
            "run_id": run_id,
            "event_type": "runtime_status",
            "payload": {"source_head": archive_head},
            "state_after": {
                "risk_control": {
                    "owned_id_restore": {"source_head": archive_head}
                }
            },
        },
        {
            "run_id": run_id,
            "event_type": "private_ws_reconciled",
            "payload": {"private_ws": {"source_head": current_head}},
            "state_after": {
                "risk_control": {
                    "owned_id_restore": {"source_head": archive_head}
                }
            },
        },
    )

    assert not okx_demo_runtime_module._incident_recovery_runtime_source_chain_is_valid(
        state={"runtime": {"run_id": run_id, "source_head": current_head}},
        events=events,
        incident_head=current_head,
        runtime_run_id=run_id,
        repo_root=Path.cwd(),
    )


def test_incident_recovery_source_chain_rejects_missing_run_or_unavailable_git(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current_head = _repo_head_for_test()
    predecessor = subprocess.run(
        ["git", "rev-parse", "HEAD~1"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    run_id = "c6bc287f4bc44c8a97333eac88caf77e"
    state = {"runtime": {"run_id": run_id}}
    events = (
        {"run_id": "historical", "payload": {"source_head": predecessor}},
        {"run_id": run_id, "payload": {"source_head": current_head}},
    )
    assert okx_demo_runtime_module._incident_recovery_runtime_source_chain_is_valid(
        state=state,
        events=events,
        incident_head=current_head,
        runtime_run_id=run_id,
        repo_root=Path.cwd(),
    )
    assert okx_demo_runtime_module._incident_recovery_runtime_source_chain_is_valid(
        state={"runtime": {"run_id": run_id, "source_head": current_head}},
        events=events,
        incident_head=current_head,
        runtime_run_id=run_id,
        repo_root=Path.cwd(),
    )
    assert not okx_demo_runtime_module._incident_recovery_runtime_source_chain_is_valid(
        state=state,
        events=(
            {"run_id": run_id, "payload": {"source_head": current_head}},
            {"run_id": "foreign-tail", "payload": {"source_head": predecessor}},
        ),
        incident_head=current_head,
        runtime_run_id=run_id,
        repo_root=Path.cwd(),
    )
    assert not okx_demo_runtime_module._incident_recovery_runtime_source_chain_is_valid(
        state=state,
        events=({"run_id": run_id, "payload": {"source_head": [current_head]}},),
        incident_head=current_head,
        runtime_run_id=run_id,
        repo_root=Path.cwd(),
    )
    assert not okx_demo_runtime_module._incident_recovery_runtime_source_chain_is_valid(
        state=state,
        events=({"run_id": "missing-current-run", "payload": {"source_head": current_head}},),
        incident_head=current_head,
        runtime_run_id=run_id,
        repo_root=Path.cwd(),
    )
    monkeypatch.setattr(
        okx_demo_runtime_module,
        "_bounded_git_ancestry_probe",
        lambda *_args: None,
    )
    assert not okx_demo_runtime_module._incident_recovery_runtime_source_chain_is_valid(
        state=state,
        events=events,
        incident_head=current_head,
        runtime_run_id=run_id,
        repo_root=Path.cwd(),
    )


def test_incident_recovery_posts_only_one_ioc_then_exact_oco_cancel(
    tmp_path: Path,
) -> None:
    controller, client = _incident_recovery_controller(tmp_path)

    result = controller.recover_fault_drill_incident(
        authorization=_incident_recovery_authorization()
    )

    assert result["decision"] == "incident_recovery_completed_safe_flat"
    assert result["final_flat"] is True
    assert result["final_no_pending_orders"] is True
    assert result["final_no_pending_algo_orders"] is True
    assert result["final_no_unresolved_intents"] is True
    assert result["final_ledger_reconciled"] is True
    assert result["final_private_ws_reconciled"] is True
    assert result["entry_order_id"] == "opening-order-1"
    assert result["close_order_id"] == "close-order-1"
    assert result["entry_fill_ids"] == ["opening-fill-1"]
    assert result["close_fill_ids"] == ["close-fill-1"]
    assert result["algo_id"] == "algo-incident-1"
    assert client.posts == ["order", "cancel-algos"]
    assert [
        call
        for call in client.private_get_calls
        if call[0]
        in {
            "/api/v5/trade/orders-algo-pending",
            "/api/v5/trade/orders-algo-history",
        }
    ] == [
        (
            "/api/v5/trade/orders-algo-pending",
            {"instId": "BTC-USDT-SWAP", "ordType": "oco"},
        ),
        (
            "/api/v5/trade/orders-algo-history",
            {
                "instId": "BTC-USDT-SWAP",
                "ordType": "oco",
                "algoId": "algo-incident-1",
            },
        ),
    ]
    assert client.close_order["side"] == "sell"
    assert client.close_order["posSide"] == "long"
    assert client.close_order["ordType"] == "ioc"
    assert client.close_order["sz"] == "0.01"
    assert client.close_order["clOrdId"] == "btcDPrecover0002"
    checkpoint = json.loads(
        (
            tmp_path / "output" / "btc_demo_paper_runtime" / "state.json"
        ).read_text(encoding="utf-8")
    )["state"]
    recovery = checkpoint["risk_control"]["incident_recovery_intents"][
        "a" * 64
    ]
    assert recovery["persisted_before_any_post"] is True
    cancel_intent = checkpoint["risk_control"]["incident_algo_cancel_intents"][
        "btcDPfailed0001A"
    ]
    assert cancel_intent["persisted_before_post"] is True
    assert (
        checkpoint["risk_control"]["owned_attached_algos"][
            "btcDPfailed0001A"
        ]["status"]
        == "cancelled_terminal"
    )

    with pytest.raises(
        OkxDemoPaperRuntimeError,
        match="incident_recovery_already_consumed",
    ):
        controller.recover_fault_drill_incident(
            authorization=_incident_recovery_authorization()
        )
    assert client.posts == ["order", "cancel-algos"]
    controller._state["risk_control"]["dead_man"].update(
        {
            "armed": True,
            "timeout_seconds": 10,
            "last_ack_utc": "2026-01-01T00:00:00+00:00",
        }
    )
    terminal = controller.finalize_incident_recovery_local()
    assert terminal["runtime"]["active"] is False
    assert terminal["private_ws"]["cleanup_complete"] is True
    assert terminal["risk_control"]["dead_man"]["armed"] is False
    assert (
        terminal["risk_control"]["dead_man"]["disarm_mode"]
        == "expired_timeout_readonly_evidence"
    )
    assert terminal["risk_control"]["dead_man"]["disarm_post_sent"] is False
    assert terminal["risk_control"]["dead_man"]["caa_post_count"] == 0
    assert terminal["risk_control"]["dead_man"]["prior_armed_state"] is True
    assert terminal["risk_control"]["dead_man"]["final_flat"] is True
    assert terminal["risk_control"]["dead_man"]["final_pending_order_count"] == 0
    assert (
        terminal["risk_control"]["dead_man"]["final_pending_algo_order_count"]
        == 0
    )
    assert (
        terminal["risk_control"]["dead_man"]["ledger_snapshot_sha256"]
        == terminal["risk_control"]["dead_man"]["private_ws_snapshot_sha256"]
        == terminal["risk_control"]["dead_man"]["exchange_snapshot_sha256"]
    )
    assert client.posts == ["order", "cancel-algos"]


def test_incident_recovery_close_response_loss_queries_without_repost(
    tmp_path: Path,
) -> None:
    class CloseResponseLossClient(IncidentRecoveryClient):
        def submit_order(self, payload: Mapping[str, Any]) -> OkxDemoResponse:
            super().submit_order(payload)
            raise ConnectionError("close response lost after exchange accept")

    client = CloseResponseLossClient()
    controller, client = _incident_recovery_controller(tmp_path, client=client)

    result = controller.recover_fault_drill_incident(
        authorization=_incident_recovery_authorization()
    )

    assert result["decision"] == "incident_recovery_completed_safe_flat"
    assert client.posts == ["order", "cancel-algos"]


def test_incident_recovery_cancel_response_loss_uses_terminal_readback_once(
    tmp_path: Path,
) -> None:
    class CancelResponseLossClient(IncidentRecoveryClient):
        def cancel_algo_orders(
            self,
            orders: list[Mapping[str, Any]],
        ) -> OkxDemoResponse:
            assert orders == [
                {"algoId": "algo-incident-1", "instId": "BTC-USDT-SWAP"}
            ]
            self.posts.append("cancel-algos")
            raise ConnectionError("cancel response lost after exchange accept")

    client = CancelResponseLossClient()
    controller, client = _incident_recovery_controller(tmp_path, client=client)

    result = controller.recover_fault_drill_incident(
        authorization=_incident_recovery_authorization()
    )

    assert client.posts == ["order", "cancel-algos"]
    assert result["cancel_receipt"]["ack_recovered_by_readback"] is True


def test_incident_recovery_nonterminal_history_readback_never_reposts_cancel(
    tmp_path: Path,
) -> None:
    class NonterminalHistoryClient(IncidentRecoveryClient):
        def private_get(
            self,
            path: str,
            params: Mapping[str, Any] | None = None,
        ) -> OkxDemoResponse:
            response = super().private_get(path, params)
            if path != "/api/v5/trade/orders-algo-history":
                return response
            rows = []
            for item in response.data:
                row = dict(item)
                if row.get("algoId") == "algo-incident-1":
                    row["state"] = "effective"
                rows.append(row)
            return OkxDemoResponse(
                method=response.method,
                path=response.path,
                http_status=response.http_status,
                code=response.code,
                message=response.message,
                data=tuple(rows),
            )

    client = NonterminalHistoryClient()
    controller, client = _incident_recovery_controller(tmp_path, client=client)

    with pytest.raises(
        OkxDemoPaperRuntimeError,
        match="incident_recovery_cancel_readback_not_terminal",
    ):
        controller.recover_fault_drill_incident(
            authorization=_incident_recovery_authorization()
        )

    assert client.posts == ["order", "cancel-algos"]
    assert (
        "/api/v5/trade/orders-algo-history",
        {
            "instId": "BTC-USDT-SWAP",
            "ordType": "oco",
            "algoId": "algo-incident-1",
        },
    ) in client.private_get_calls


def test_incident_recovery_never_cancels_before_flat_fill_ledger_ws_proof(
    tmp_path: Path,
) -> None:
    controller, client = _incident_recovery_controller(tmp_path)
    original_commit = controller._commit_ledger_reconciliation

    def fail_flat_commit(**kwargs: Any) -> None:
        if kwargs.get("trigger") == "incident_recovery_flat_before_algo_cancel":
            raise OkxDemoPaperRuntimeError("flat ledger proof unavailable")
        original_commit(**kwargs)

    controller._commit_ledger_reconciliation = fail_flat_commit  # type: ignore[method-assign]

    with pytest.raises(OkxDemoPaperRuntimeError, match="flat ledger proof"):
        controller.recover_fault_drill_incident(
            authorization=_incident_recovery_authorization()
        )

    assert client.posts == ["order"]


def test_incident_recovery_mismatch_is_zero_post_fail_closed(
    tmp_path: Path,
) -> None:
    controller, client = _incident_recovery_controller(
        tmp_path,
        extra_pending=True,
    )

    with pytest.raises(
        OkxDemoPaperRuntimeError,
        match="incident_recovery_extra_pending_order",
    ):
        controller.recover_fault_drill_incident(
            authorization=_incident_recovery_authorization()
        )

    assert client.posts == []


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("algo_id", "wrong-algo"),
        ("algo_client_order_id", "wrong-client"),
        ("instrument_id", "ETH-USDT-SWAP"),
        ("position_side", "short"),
        ("size", "0.02"),
        ("order_type", "conditional"),
        ("state", "effective"),
        ("take_profit_trigger", "65867.2"),
        ("take_profit_trigger_type", "last"),
        ("take_profit_order_price", "65867.3"),
        ("stop_loss_trigger", "63930"),
        ("stop_loss_trigger_type", "last"),
        ("stop_loss_order_price", "63929.9"),
        ("parent_client_order_id", "wrong-parent"),
    ],
)
def test_incident_recovery_exact_legacy_state_rejects_oco_mutations_zero_post(
    tmp_path: Path,
    field: str,
    value: Any,
) -> None:
    controller, client = _incident_recovery_controller(
        tmp_path,
        oco_mutation=(field, value),
    )

    with pytest.raises(
        OkxDemoPaperRuntimeError,
        match="incident_recovery_pending_oco_mismatch",
    ):
        controller.recover_fault_drill_incident(
            authorization=_incident_recovery_authorization()
        )

    assert client.posts == []


def test_incident_recovery_legacy_durable_shape_mismatch_is_zero_post(
    tmp_path: Path,
) -> None:
    controller, client = _incident_recovery_controller(tmp_path)
    controller._state["risk_control"]["owned_attached_algos"][
        "btcDPfailed0001A"
    ]["algo_id"] = "algo-incident-1"

    with pytest.raises(
        OkxDemoPaperRuntimeError,
        match="incident_recovery_owned_oco_mismatch",
    ):
        controller.recover_fault_drill_incident(
            authorization=_incident_recovery_authorization()
        )

    assert client.posts == []


def test_incident_recovery_abnormal_exit_stops_ws_and_releases_writer_lock(
    tmp_path: Path,
) -> None:
    controller, client = _incident_recovery_controller(tmp_path)
    authorization = _incident_recovery_authorization()
    authorization["expected_close_cl_ord_id"] = "btcDPwrong0002"
    cleanup_persist_lock_states: list[bool] = []
    original_persist = controller._persist_state

    def observe_cleanup_persist() -> None:
        if (
            controller._state["runtime"].get("status")
            == "incident_recovery_blocked_fail_closed"
        ):
            cleanup_persist_lock_states.append(
                controller._fault_drill_lock_handle is not None
            )
        original_persist()

    controller._persist_state = observe_cleanup_persist  # type: ignore[method-assign]

    with pytest.raises(
        OkxDemoPaperRuntimeError,
        match="incident_recovery_close_identity_mismatch",
    ):
        controller.recover_fault_drill_incident(authorization=authorization)

    status = controller.status()
    assert client.posts == []
    assert controller._private_ws is None
    assert controller._fault_drill_lock_handle is None
    assert cleanup_persist_lock_states == [True]
    assert status["runtime"]["active"] is False
    assert status["private_ws"]["listener_alive"] is False


@pytest.mark.parametrize("failure_phase", ["start", "status"])
def test_incident_recovery_ws_failure_and_stop_failure_remains_cleanup_blocked(
    tmp_path: Path,
    failure_phase: str,
) -> None:
    class FailingLifecycleWS(IncidentRecoveryPrivateWS):
        def start_monitoring(self) -> None:
            if failure_phase == "start":
                raise RuntimeError("monitor lifecycle failed")

        def status(self) -> dict[str, Any]:
            if failure_phase == "status":
                raise RuntimeError("monitor lifecycle failed")
            return super().status()

        def stop(self) -> dict[str, Any]:
            raise RuntimeError("monitor stop failed")

    controller, client = _incident_recovery_controller(
        tmp_path,
        private_ws_factory=FailingLifecycleWS,
    )

    with pytest.raises(RuntimeError, match="monitor lifecycle failed"):
        controller.recover_fault_drill_incident(
            authorization=_incident_recovery_authorization()
        )

    status = controller.status()
    assert client.posts == []
    assert controller._fault_drill_lock_handle is None
    assert status["private_ws"]["cleanup_complete"] is False
    assert "monitor stop failed" in status["private_ws"]["cleanup_error"]


@pytest.mark.parametrize(
    "stop_receipt",
    [{}, {"listener_joined": False}, "not-a-mapping"],
)
def test_incident_recovery_local_finalize_requires_joined_ws_receipt(
    tmp_path: Path,
    stop_receipt: Any,
) -> None:
    controller, client = _incident_recovery_controller(tmp_path)
    controller.recover_fault_drill_incident(
        authorization=_incident_recovery_authorization()
    )
    assert controller._private_ws is not None
    controller._private_ws.stop = lambda: stop_receipt  # type: ignore[method-assign]

    with pytest.raises(
        OkxDemoPaperRuntimeError,
        match="private_ws_listener_join_not_proven",
    ):
        controller.finalize_incident_recovery_local()

    status = controller.status()
    assert client.posts == ["order", "cancel-algos"]
    assert status["private_ws"]["cleanup_complete"] is False
    assert (
        status["private_ws"]["cleanup_error"]
        == "private_ws_listener_join_not_proven"
    )


@pytest.mark.parametrize(
    "stop_receipt",
    [{}, {"listener_joined": False}, "not-a-mapping"],
)
def test_incident_recovery_failed_cleanup_requires_joined_ws_receipt(
    tmp_path: Path,
    stop_receipt: Any,
) -> None:
    class InvalidStopReceiptWS(IncidentRecoveryPrivateWS):
        def status(self) -> dict[str, Any]:
            raise RuntimeError("status failed before any post")

        def stop(self) -> Any:
            return stop_receipt

    controller, client = _incident_recovery_controller(
        tmp_path,
        private_ws_factory=InvalidStopReceiptWS,
    )

    with pytest.raises(RuntimeError, match="status failed before any post"):
        controller.recover_fault_drill_incident(
            authorization=_incident_recovery_authorization()
        )

    status = controller.status()
    assert client.posts == []
    assert controller._fault_drill_lock_handle is None
    assert status["private_ws"]["cleanup_complete"] is False
    assert (
        status["private_ws"]["cleanup_error"]
        == "private_ws_listener_join_not_proven"
    )


def test_status_overlays_current_private_ws_liveness_not_historical_probe(
    tmp_path: Path,
) -> None:
    controller = _controller(tmp_path, lambda _: _credentials())
    controller._state["private_ws"] = {
        "opening_allowed_after_reconciliation": True,
        "reconnect_login_observed": True,
        "reconnect_resubscribed": True,
        "reconnect_rest_reconciled": True,
    }
    controller._private_ws = type(
        "DisconnectedPrivateWS",
        (),
        {
            "status": lambda self: {
                "connected": False,
                "listener_alive": False,
                "opening_allowed_after_reconciliation": False,
                "blockers": ["btc_okx_demo_private_ws:disconnected"],
            }
        },
    )()

    status = controller.status()

    assert status["private_ws"]["connected"] is False
    assert status["private_ws"]["listener_alive"] is False
    assert status["private_ws"]["opening_allowed_after_reconciliation"] is False


class AlgoCleanupClient:
    def __init__(
        self,
        *,
        pending_rounds: int = 0,
        history_nonterminal_rounds: int = 0,
    ) -> None:
        self.cancel_algo_calls: list[list[dict[str, Any]]] = []
        self.pending_rounds = pending_rounds
        self.history_nonterminal_rounds = history_nonterminal_rounds
        self.pending_get_calls = 0
        self.history_get_calls = 0
        self.history_params: list[dict[str, Any]] = []

    def cancel_algo_orders(
        self,
        orders: list[Mapping[str, Any]],
    ) -> OkxDemoResponse:
        self.cancel_algo_calls.append([dict(row) for row in orders])
        return OkxDemoResponse(
            method="POST",
            path="/api/v5/trade/cancel-algos",
            http_status=200,
            code="0",
            message="",
            data=tuple(
                {"algoId": row["algoId"], "sCode": "0", "sMsg": ""}
                for row in orders
            ),
        )

    def private_get(
        self,
        path: str,
        params: Mapping[str, Any] | None = None,
    ) -> OkxDemoResponse:
        if path == "/api/v5/trade/orders-algo-pending":
            self.pending_get_calls += 1
            rows: tuple[Mapping[str, Any], ...] = (
                tuple(
                    {
                        "algoId": row["algoId"],
                        "algoClOrdId": "ownedAlgo1",
                        "instId": "BTC-USDT-SWAP",
                        "state": "live",
                    }
                    for batch in self.cancel_algo_calls
                    for row in batch
                )
                if self.pending_get_calls <= self.pending_rounds
                else ()
            )
        elif path == "/api/v5/trade/orders-algo-history":
            self.history_get_calls += 1
            self.history_params.append(dict(params or {}))
            rows = tuple(
                {
                    "algoId": row["algoId"],
                    "state": (
                        "effective"
                        if self.history_get_calls
                        <= self.history_nonterminal_rounds
                        else "canceled"
                    ),
                }
                for batch in self.cancel_algo_calls
                for row in batch
            )
        else:
            raise AssertionError(path)
        return OkxDemoResponse(
            method="GET",
            path=path,
            http_status=200,
            code="0",
            message="",
            data=rows,
        )


def _algo_snapshot(*, contracts: str, algo_id: str, algo_client_id: str) -> dict[str, Any]:
    return {
        "positions": (
            []
            if contracts == "0"
            else [{"position_side": "long", "contracts": contracts}]
        ),
        "pending_orders": [],
        "pending_algo_orders": [
            {
                "algo_id": algo_id,
                "algo_client_order_id": algo_client_id,
                "instrument_id": "BTC-USDT-SWAP",
                "state": "live",
            }
        ],
    }


def _record_owned_algo(
    controller: OkxDemoPaperRuntimeController,
    *,
    algo_id: str,
    algo_client_id: str,
) -> None:
    parent_client_id = "btcDPownedparent"
    controller._state["risk_control"]["pending_order_intents"] = {
        parent_client_id: {
            "client_order_id": parent_client_id,
            "status": "terminal",
            "risk_reducing_only": False,
        }
    }
    controller._state["risk_control"]["owned_attached_algos"] = {
        algo_client_id: {
            "algo_id": algo_id,
            "algo_client_order_id": algo_client_id,
            "parent_client_order_id": parent_client_id,
            "instrument_id": "BTC-USDT-SWAP",
            "opening_intent": True,
            "status": "active",
        }
    }


def test_unknown_algo_is_never_cancelled(tmp_path: Path) -> None:
    controller = _repo_controller(tmp_path, lambda _: _credentials())
    client = AlgoCleanupClient()
    _record_owned_algo(
        controller,
        algo_id="owned-1",
        algo_client_id="ownedAlgo1",
    )

    with pytest.raises(OkxDemoPaperRuntimeError, match="unknown_algo_not_cancelled"):
        controller._cleanup_owned_flat_algos(  # type: ignore[arg-type]
            client,
            snapshot=_algo_snapshot(
                contracts="0",
                algo_id="unknown-1",
                algo_client_id="unknownAlgo1",
            ),
        )

    assert client.cancel_algo_calls == []


def test_nonflat_position_never_cancels_protection(tmp_path: Path) -> None:
    controller = _controller(tmp_path, lambda _: _credentials())
    client = AlgoCleanupClient()
    _record_owned_algo(
        controller,
        algo_id="owned-1",
        algo_client_id="ownedAlgo1",
    )

    with pytest.raises(
        OkxDemoPaperRuntimeError,
        match="nonflat_protection_cancel_forbidden",
    ):
        controller._cleanup_owned_flat_algos(  # type: ignore[arg-type]
            client,
            snapshot=_algo_snapshot(
                contracts="0.01",
                algo_id="owned-1",
                algo_client_id="ownedAlgo1",
            ),
        )

    assert client.cancel_algo_calls == []


def test_owned_flat_algo_requires_ack_pending_and_history_readback(
    tmp_path: Path,
) -> None:
    controller = _controller(tmp_path, lambda _: _credentials())
    client = AlgoCleanupClient()
    _record_owned_algo(
        controller,
        algo_id="owned1",
        algo_client_id="ownedAlgo1",
    )
    final = {
        "positions": [],
        "pending_orders": [],
        "pending_algo_orders": [],
    }
    controller._collect_exchange_snapshot = lambda _client: final  # type: ignore[method-assign]

    refreshed, receipt = controller._cleanup_owned_flat_algos(  # type: ignore[arg-type]
        client,
        snapshot=_algo_snapshot(
            contracts="0",
            algo_id="owned1",
            algo_client_id="ownedAlgo1",
        ),
    )

    assert client.cancel_algo_calls == [
        [{"algoId": "owned1", "instId": "BTC-USDT-SWAP"}]
    ]
    assert refreshed == final
    assert receipt["pending_readback_empty"] is True
    assert receipt["history_terminal_verified"] is True
    assert client.history_params == [
        {
            "instId": "BTC-USDT-SWAP",
            "ordType": "oco",
            "algoId": "owned1",
        }
    ]


def test_owned_flat_algo_cancel_waits_for_delayed_query_only_convergence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    controller = _controller(tmp_path, lambda _: _credentials())
    client = AlgoCleanupClient(pending_rounds=2, history_nonterminal_rounds=3)
    _record_owned_algo(
        controller,
        algo_id="owned1",
        algo_client_id="ownedAlgo1",
    )
    controller._collect_exchange_snapshot = lambda _client: {  # type: ignore[method-assign]
        "positions": [],
        "pending_orders": [],
        "pending_algo_orders": [],
    }
    monkeypatch.setattr(okx_demo_runtime_module.time, "sleep", lambda _seconds: None)

    _, receipt = controller._cleanup_owned_flat_algos(  # type: ignore[arg-type]
        client,
        snapshot=_algo_snapshot(
            contracts="0",
            algo_id="owned1",
            algo_client_id="ownedAlgo1",
        ),
    )

    assert client.cancel_algo_calls == [
        [{"algoId": "owned1", "instId": "BTC-USDT-SWAP"}]
    ]
    assert client.pending_get_calls == 4
    assert client.history_get_calls == 4
    assert receipt["query_only_readback_attempts"] == 4


def test_owned_flat_algo_cancel_timeout_never_reposts_cancel(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    controller = _controller(tmp_path, lambda _: _credentials())
    client = AlgoCleanupClient(pending_rounds=99, history_nonterminal_rounds=99)
    _record_owned_algo(
        controller,
        algo_id="owned1",
        algo_client_id="ownedAlgo1",
    )
    monkeypatch.setattr(okx_demo_runtime_module.time, "sleep", lambda _seconds: None)

    with pytest.raises(
        OkxDemoPaperRuntimeError,
        match="cancel_algos_readback_timeout_unknown",
    ):
        controller._cleanup_owned_flat_algos(  # type: ignore[arg-type]
            client,
            snapshot=_algo_snapshot(
                contracts="0",
                algo_id="owned1",
                algo_client_id="ownedAlgo1",
            ),
        )

    assert client.cancel_algo_calls == [
        [{"algoId": "owned1", "instId": "BTC-USDT-SWAP"}]
    ]
    assert client.pending_get_calls == (
        okx_demo_runtime_module.OKX_DEMO_FAULT_DRILL_ALGO_CANCEL_READBACK_ATTEMPTS
    )


def test_owned_flat_algo_cancel_requires_every_ack_row_success(
    tmp_path: Path,
) -> None:
    controller = _controller(tmp_path, lambda _: _credentials())

    class PartialAckClient(AlgoCleanupClient):
        def cancel_algo_orders(
            self,
            orders: list[Mapping[str, Any]],
        ) -> OkxDemoResponse:
            self.cancel_algo_calls.append([dict(row) for row in orders])
            return OkxDemoResponse(
                method="POST",
                path="/api/v5/trade/cancel-algos",
                http_status=200,
                code="0",
                message="",
                data=(
                    {
                        "algoId": orders[0]["algoId"],
                        "sCode": "51000",
                        "sMsg": "rejected",
                    },
                ),
            )

    client = PartialAckClient()
    _record_owned_algo(
        controller,
        algo_id="owned1",
        algo_client_id="ownedAlgo1",
    )

    with pytest.raises(
        OkxDemoPaperRuntimeError,
        match="cancel_algos_ack_incomplete",
    ):
        controller._cleanup_owned_flat_algos(  # type: ignore[arg-type]
            client,
            snapshot=_algo_snapshot(
                contracts="0",
                algo_id="owned1",
                algo_client_id="ownedAlgo1",
            ),
        )

    assert client.cancel_algo_calls == [
        [{"algoId": "owned1", "instId": "BTC-USDT-SWAP"}]
    ]
    assert client.pending_get_calls == 0


def test_worker_without_verified_protection_cannot_be_accepted_as_killed(
    tmp_path: Path,
) -> None:
    controller = _repo_controller(tmp_path, lambda _: _credentials())
    marker = {
        "schema_version": "btc_okx_demo_worker_ready_v1",
        "scenario": "worker_kill",
        "process_id": 43210,
        "position_observed": True,
        "protection_verified": False,
    }
    marker["marker_sha256"] = hashlib.sha256(
        json.dumps(
            marker,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    controller._state["runtime"]["fault_drill_worker_ready"] = marker

    with pytest.raises(
        OkxDemoPaperRuntimeError,
        match="worker_termination_evidence_invalid",
    ):
        controller.recover_fault_drill_after_worker_kill(
            authorization={
                "authorization_ticket": "BTC-OKX-P0-DRILL-SUPERVISOR-FRONTEND-01",
                "scenario": "worker_kill",
                "execute_demo": True,
            },
            child_termination={
                "process_id": 43210,
                "external": True,
                "terminated": True,
                "wait_confirmed": True,
            },
        )


@pytest.mark.parametrize(
    ("expected_nonce", "expected_create_time"),
    (("differentnonce", "123"), ("nonce1", "456")),
)
def test_parent_rejects_worker_nonce_or_pid_reuse_identity_before_private_read(
    tmp_path: Path,
    expected_nonce: str,
    expected_create_time: str,
) -> None:
    credential_calls: list[str] = []
    controller = _repo_controller(tmp_path, credential_calls.append)
    marker = {
        "worker_nonce": "nonce1",
        "process_id": 43210,
        "process_create_time": "123",
        "source_head": subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip(),
        "runtime_root_sha256": hashlib.sha256(
            json.dumps(
                str(Path(controller.config.output_dir).resolve()),
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest(),
        "position_observed": True,
        "protection_verified": True,
    }
    marker["marker_sha256"] = hashlib.sha256(
        json.dumps(
            marker,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()

    with pytest.raises(
        OkxDemoPaperRuntimeError,
        match="worker_marker_identity_mismatch",
    ):
        controller.verify_fault_drill_worker_ready(
            marker,
            expected_nonce=expected_nonce,
            expected_process_id=43210,
            expected_process_create_time=expected_create_time,
        )

    assert credential_calls == []


def test_read_only_status_and_worker_get_verifier_do_not_lock_or_persist(
    tmp_path: Path,
) -> None:
    writer = _repo_controller(tmp_path, lambda _: _credentials())
    writer.acquire_fault_drill_process_lock(nonce="writerreadonlyprobe")
    writer._state["runtime"].update({"run_id": "readonly-run", "order_sequence": 1})
    writer._sequence = 1
    writer._append_event("worker_prepared", {"query_only": True})
    writer._persist_state()
    previous_event_hash = writer._status_event_projection(
        writer._state["events"][0]
    )["event_id"]
    snapshot = {
        "orders": [{"client_order_id": "open1"}],
        "fills": [{"client_order_id": "open1"}],
        "positions": [{"position_side": "long", "contracts": "0.01"}],
        "pending_orders": [],
        "pending_algo_orders": [
            {
                "algo_id": "algo1",
                "algo_client_order_id": "algoClient1",
                "instrument_id": "BTC-USDT-SWAP",
            }
        ],
        "balance": {},
        "bills": [],
    }
    marker = {
        "schema_version": "btc_okx_demo_worker_ready_v1",
        "scenario": "worker_kill",
        "process_id": 43210,
        "process_create_time": "123",
        "worker_nonce": "readonlynonce",
        "source_head": subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip(),
        "runtime_root_sha256": okx_demo_runtime_module._canonical_sha256(
            str(Path(writer.config.output_dir).resolve())
        ),
        "run_id": "readonly-run",
        "order_sequence": 1,
        "clOrdId": "open1",
        "algoClOrdId": "algoClient1",
        "algoId": "algo1",
        "held_reconciliation_sha256": okx_demo_runtime_module._canonical_sha256(
            okx_demo_runtime_module._fault_reconciliation_facts(snapshot)
        ),
        "ledger_snapshot_sha256": okx_demo_runtime_module._fault_ledger_snapshot_sha256(
            snapshot
        ),
        "committed_ledger_snapshot_sha256": okx_demo_runtime_module._fault_ledger_snapshot_sha256(
            snapshot
        ),
        "runtime_state_sha256": okx_demo_runtime_module._canonical_sha256(
            writer._durable_state_snapshot()
        ),
        "previous_event_hash": previous_event_hash,
        "position_observed": True,
        "protection_verified": True,
        "persisted_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    marker["marker_sha256"] = okx_demo_runtime_module._canonical_sha256(marker)
    writer._state["runtime"]["fault_drill_worker_ready"] = marker
    writer._append_event("fault_drill_worker_ready", marker)
    writer._persist_state()
    output = Path(writer.config.output_dir)
    state_hash = hashlib.sha256((output / "state.json").read_bytes()).hexdigest()
    event_hash = hashlib.sha256((output / "events.jsonl").read_bytes()).hexdigest()

    verifier = _repo_controller(tmp_path, lambda _: _credentials())
    get_calls: list[str] = []
    verifier._read_only_client = lambda: object()  # type: ignore[method-assign]
    verifier._collect_exchange_snapshot = lambda _client: (  # type: ignore[method-assign]
        get_calls.append("GET") or snapshot
    )

    assert verifier.status()["runtime"]["run_id"] == "readonly-run"
    verified = verifier.verify_fault_drill_worker_ready(
        marker,
        expected_nonce="readonlynonce",
        expected_process_id=43210,
        expected_process_create_time="123",
    )

    assert verified["verified"] is True
    assert verified["methods"] == ["GET"]
    assert get_calls == ["GET"]
    assert verifier._fault_drill_lock_handle is None
    assert hashlib.sha256((output / "state.json").read_bytes()).hexdigest() == state_hash
    assert hashlib.sha256((output / "events.jsonl").read_bytes()).hexdigest() == event_hash
    writer.release_fault_drill_process_lock()


def test_fault_drill_runtime_root_lock_is_single_writer_and_reacquirable(
    tmp_path: Path,
) -> None:
    first = _repo_controller(tmp_path, lambda _: _credentials())
    second = _repo_controller(tmp_path, lambda _: _credentials())

    assert first.acquire_fault_drill_process_lock(nonce="nonce1")["acquired"] is True
    if os.name == "nt":
        lock_path = (
            Path(first.config.output_dir).resolve()
            / ".btc_okx_demo_fault_drill_writer.lock"
        )
        probe = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import msvcrt,sys;"
                    "h=open(sys.argv[1],'r+b');h.seek(0);"
                    "\ntry: msvcrt.locking(h.fileno(),msvcrt.LK_NBLCK,1)"
                    "\nexcept OSError: raise SystemExit(3)"
                ),
                str(lock_path),
            ],
            check=False,
        )
        assert probe.returncode == 3
    with pytest.raises(
        OkxDemoPaperRuntimeError,
        match="runtime_root_writer_lock_unavailable",
    ):
        second.acquire_fault_drill_process_lock(nonce="nonce1")
    first.release_fault_drill_process_lock()
    assert second.acquire_fault_drill_process_lock(nonce="nonce1")["acquired"] is True
    second.release_fault_drill_process_lock()


def test_canonical_btc_demo_service_second_writer_fails_before_private_or_state_write(
    tmp_path: Path,
) -> None:
    FakePrivateWS.instances.clear()
    output = tmp_path / "output" / "btc_demo_paper_runtime"
    client = SnapshotClient()
    clock = lambda: datetime(
        1970, 1, 1, 0, 0, 0, 1000, tzinfo=timezone.utc
    )
    writer = OkxDemoPaperRuntimeController(
        config=OkxDemoPaperRuntimeConfig(
            repo_root=Path.cwd(),
            data_db_path=tmp_path / "unused.sqlite",
            output_dir=output,
        ),
        credential_loader=lambda _: _credentials(),
        client_factory=lambda _config, _credentials_value: client,
        private_ws_factory=FakePrivateWS,
        clock=clock,
        start_worker=False,
    )
    writer._signal_decision = lambda _strategy, **_kwargs: {
        "signal": "flat",
        "target_contracts": "0",
        "decision_bar_close_utc": clock().isoformat(),
    }
    service = BackendBtcDemoRuntimeService(controller=writer)

    service.start(_valid_start_payload())

    assert writer._fault_drill_lock_handle is not None
    state_hash = hashlib.sha256((output / "state.json").read_bytes()).hexdigest()
    event_hash = hashlib.sha256((output / "events.jsonl").read_bytes()).hexdigest()
    credential_calls: list[str] = []
    contender = _repo_controller(tmp_path, credential_calls.append)
    contender_service = BackendBtcDemoRuntimeService(controller=contender)

    with pytest.raises(
        OkxDemoPaperRuntimeError,
        match="runtime_root_writer_lock_unavailable",
    ):
        contender_service.start(_valid_start_payload())

    assert credential_calls == []
    assert contender.status()["runtime"]["active"] is False
    assert hashlib.sha256((output / "state.json").read_bytes()).hexdigest() == state_hash
    assert hashlib.sha256((output / "events.jsonl").read_bytes()).hexdigest() == event_hash
    assert contender._fault_drill_lock_handle is None
    service.stop({"confirmation_text": OKX_DEMO_PAPER_CONFIRMATION})
    assert writer._fault_drill_lock_handle is None


def test_recovery_restores_exact_run_id_and_order_sequence(tmp_path: Path) -> None:
    controller = _controller(tmp_path, lambda _: _credentials())
    controller._state["runtime"].update(
        {"run_id": "durable-run-1", "order_sequence": 7, "active": False}
    )
    controller._sequence = 7
    controller._persist_state()

    recovered = _controller(tmp_path, lambda _: _credentials())

    assert recovered._state["runtime"]["run_id"] == "durable-run-1"
    assert recovered._state["runtime"]["order_sequence"] == 7
    assert recovered._sequence == 7


def test_stable_strategy_signal_binds_empty_native_tail_evidence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    now = datetime(2026, 7, 30, 4, 5, tzinfo=timezone.utc)
    stable_spec = next(
        spec
        for spec in btc_strategy_registry.list_specs()
        if spec.strategy_id == "long_short_donchian_top5"
    )
    client = SnapshotClient()
    baseline = _large_hourly_frame(now - timedelta(hours=1))
    monkeypatch.setattr(
        okx_demo_runtime_module,
        "load_completed_okx_native_hourly_frame",
        lambda *_args, **_kwargs: baseline,
    )
    monkeypatch.setattr(
        okx_demo_runtime_module,
        "_merge_okx_native_public_candle_tail",
        lambda *, baseline, client, now: (
            baseline,
            {
                "source": "okx_public_rest",
                "sample_end_utc": baseline.index[-1].isoformat(),
                "confirmed_only": True,
                "integrity_passed": True,
            },
        ),
    )
    controller = OkxDemoPaperRuntimeController(
        config=OkxDemoPaperRuntimeConfig(
            repo_root=tmp_path,
            data_db_path=tmp_path / "unused.sqlite",
            output_dir=tmp_path / "output" / "btc_demo_paper_runtime",
        ),
        credential_loader=lambda _: _credentials(),
        clock=lambda: now,
        start_worker=False,
    )

    decision = controller._signal_decision(stable_spec.identity(), client=client)

    assert decision["strategy_id"] == "long_short_donchian_top5"
    assert decision["source"] == "local_okx_native_completed_swap_1h_manifest_verified"
    assert decision["runtime_public_candle_tail"]["source"] == "okx_public_rest"
    assert client.public_calls == []


def _baseline_frame(end: datetime):
    closes = [
        end - timedelta(hours=2),
        end - timedelta(hours=1),
        end,
    ]
    return okx_demo_runtime_module.pd.DataFrame(
        {
            "open_time": [
                close - timedelta(hours=1) for close in closes
            ],
            "open": [100.0, 101.0, 102.0],
            "high": [101.0, 102.0, 103.0],
            "low": [99.0, 100.0, 101.0],
            "close": [100.5, 101.5, 102.5],
            "volume": [1.0, 1.0, 1.0],
        },
        index=okx_demo_runtime_module.pd.DatetimeIndex(closes),
    )


def _large_hourly_frame(end: datetime, *, periods: int = 4_800):
    closes = okx_demo_runtime_module.pd.date_range(
        end=end,
        periods=periods,
        freq="h",
    )
    values = okx_demo_runtime_module.pd.Series(
        range(periods),
        dtype="float64",
    ).to_numpy()
    return okx_demo_runtime_module.pd.DataFrame(
        {
            "open_time": closes - okx_demo_runtime_module.pd.Timedelta(hours=1),
            "open": 60_000 + values,
            "high": 60_001 + values,
            "low": 59_999 + values,
            "close": 60_000.5 + values,
            "volume": 1.0,
        },
        index=closes,
    )


def _candle_row(open_time: datetime, *, confirm: str = "1") -> list[str]:
    return [
        str(int(open_time.timestamp() * 1000)),
        "100",
        "101",
        "99",
        "100.5",
        "1",
        "1",
        "100",
        confirm,
    ]


class PublicCandleClient:
    def __init__(self, rows: list[list[str]]) -> None:
        self.rows = rows
        self.calls: list[dict[str, Any]] = []

    def public_get(
        self,
        path: str,
        params: Mapping[str, Any] | None = None,
    ) -> OkxDemoResponse:
        self.calls.append({"path": path, "params": dict(params or {})})
        return OkxDemoResponse(
            method="GET",
            path=path,
            http_status=200,
            code="0",
            message="",
            data=tuple(self.rows),
        )


class PaginatedPublicCandleClient:
    def __init__(self, pages: Mapping[str | None, list[list[str]]]) -> None:
        self.pages = dict(pages)
        self.calls: list[dict[str, Any]] = []

    def public_get(
        self,
        path: str,
        params: Mapping[str, Any] | None = None,
    ) -> OkxDemoResponse:
        normalized = dict(params or {})
        self.calls.append({"path": path, "params": normalized})
        cursor = str(normalized["after"]) if "after" in normalized else None
        return OkxDemoResponse(
            method="GET",
            path=path,
            http_status=200,
            code="0",
            message="",
            data=tuple(self.pages.get(cursor, [])),
        )


def test_stale_okx_native_baseline_is_loadable_only_as_explicit_public_tail_seed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    baseline_end = datetime(2026, 7, 30, 0, 0, tzinfo=timezone.utc)
    now = baseline_end + timedelta(hours=4)
    baseline = _large_hourly_frame(baseline_end)
    monkeypatch.setattr(
        okx_demo_runtime_module,
        "inspect_okx_native_demo_signal_data",
        lambda *_args, **_kwargs: {"eligible": True, "blockers": []},
    )
    monkeypatch.setattr(
        okx_demo_runtime_module,
        "_resolve_okx_native_demo_bundle",
        lambda *_args, **_kwargs: (
            tmp_path,
            {},
            {"layout_schema": OKX_NATIVE_SHARED_DATA_SCHEMA},
            tmp_path / "candles.jsonl",
        ),
    )
    monkeypatch.setattr(
        okx_demo_runtime_module,
        "_load_generic_public_swap_hourly_frame",
        lambda _path: baseline,
    )

    with pytest.raises(
        OkxDemoPaperRuntimeError,
        match="okx_native_completed_1h_stale",
    ):
        load_completed_okx_native_hourly_frame(tmp_path, now=now)

    seeded = load_completed_okx_native_hourly_frame(
        tmp_path,
        now=now,
        allow_stale_baseline=True,
    )

    assert seeded.index[-1] == baseline_end


def test_okx_native_start_uses_stale_bundle_only_as_seed_then_signals_from_fresh_tail(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    baseline_end = datetime(2026, 7, 30, 0, 0, tzinfo=timezone.utc)
    now = baseline_end + timedelta(hours=4, minutes=5)
    baseline = _large_hourly_frame(baseline_end)
    client = SnapshotClient(
        candle_rows=[
            _candle_row(baseline_end + timedelta(hours=4), confirm="0"),
            _candle_row(baseline_end + timedelta(hours=3)),
            _candle_row(baseline_end + timedelta(hours=2)),
            _candle_row(baseline_end + timedelta(hours=1)),
            _candle_row(baseline_end),
        ],
        server_time_ms=str(int(now.timestamp() * 1000)),
    )
    native_spec = next(
        spec
        for spec in btc_strategy_registry.list_specs()
        if spec.strategy_id == "long_short_donchian_top5_okx_native"
    )
    load_calls: list[bool] = []
    observed_stages: list[str] = []
    controller: OkxDemoPaperRuntimeController

    def load_seed(*_args, allow_stale_baseline: bool = False, **_kwargs):
        load_calls.append(allow_stale_baseline)
        state = controller.status()
        assert state["runtime"]["opening_allowed"] is False
        assert state["safety"]["okx_demo_order_capability_enabled"] is False
        assert state["signal"] == {}
        if not allow_stale_baseline:
            raise OkxDemoPaperRuntimeError(
                "okx_demo_paper_okx_native_completed_1h_stale"
            )
        observed_stages.append("bundle_integrity_preflight")
        return baseline

    monkeypatch.setattr(
        okx_demo_runtime_module,
        "load_completed_okx_native_hourly_frame",
        load_seed,
    )

    class ObservingPrivateWS(FakePrivateWS):
        def run_startup_reconnect_probe(self) -> dict[str, Any]:
            state = controller.status()
            assert state["runtime"]["opening_allowed"] is False
            assert (
                state["safety"]["okx_demo_order_capability_enabled"] is False
            )
            assert state["signal"]["runtime_public_candle_tail"][
                "sample_end_utc"
            ] == (baseline_end + timedelta(hours=4)).isoformat()
            observed_stages.append("private_ws_reconciliation")
            return super().run_startup_reconnect_probe()

    controller = OkxDemoPaperRuntimeController(
        config=OkxDemoPaperRuntimeConfig(
            repo_root=Path.cwd(),
            data_db_path=tmp_path / "unused.sqlite",
            output_dir=tmp_path / "output" / "btc_demo_paper_runtime",
        ),
        credential_loader=lambda _: _credentials(),
        client_factory=lambda _config, _credentials_value: client,
        private_ws_factory=ObservingPrivateWS,
        clock=lambda: now,
        start_worker=False,
    )

    status = controller.start(_start_payload_for(native_spec))

    assert load_calls == [True, True]
    assert observed_stages == [
        "bundle_integrity_preflight",
        "bundle_integrity_preflight",
        "private_ws_reconciliation",
    ]
    assert status["signal"]["decision_bar_close_utc"] == (
        baseline_end + timedelta(hours=4)
    ).isoformat()
    assert status["runtime"]["opening_allowed"] is True
    assert status["safety"]["okx_demo_order_capability_enabled"] is True
    assert status["safety"]["live_order_allowed"] is False
    assert status["safety"]["real_money_order_allowed"] is False
    controller.stop({"confirmation_text": OKX_DEMO_PAPER_CONFIRMATION})


def test_stale_for_opening_snapshot_renews_dead_man_from_durable_authority(
    tmp_path: Path,
) -> None:
    current = datetime.now(timezone.utc) - timedelta(seconds=26)
    observed_at = [current]

    class DemoAdapter:
        def capability_for(self, *, action, transport_context):
            assert action is RuntimeAction.DEAD_MAN
            assert isinstance(transport_context, SnapshotClient)
            return BTCEndpointCapability(
                mode=BTCExecutionMode.DEMO,
                transport_enabled=True,
                submit_new_order=True,
                cancel_order=True,
                reduce_only=True,
                attach_protection=True,
                dead_man=True,
                private_endpoint_allowed=True,
                order_endpoint_allowed=True,
            )

    source_head = _repo_head_for_test()
    dispatcher = BTCDemoExecutionDispatcher(
        expected_source_head=source_head,
        state_directory=tmp_path / "btc-demo-boundary",
        capability_adapter=DemoAdapter(),
        credential_service="quant-system.okx-demo.trade",
    )
    client = SnapshotClient()
    controller = OkxDemoPaperRuntimeController(
        config=OkxDemoPaperRuntimeConfig(
            repo_root=Path.cwd(),
            data_db_path=tmp_path / "unused.sqlite",
            output_dir=tmp_path / "output" / "btc_demo_paper_runtime",
            execution_dispatcher=dispatcher,
        ),
        credential_loader=lambda _: _credentials(),
        clock=lambda: observed_at[0],
        start_worker=False,
    )

    class ReconciledPrivateWS:
        reconcile_calls = 0

        def reconcile_current(self) -> dict[str, Any]:
            self.reconcile_calls += 1
            return {
                "schema_version": "btc_okx_demo_private_ws_current_reconciliation_v1",
                "source_head": source_head,
                "runtime_version": "okx_demo_paper_runtime_v1",
                "generated_at_utc": observed_at[0].isoformat(),
                "connected": True,
                "listener_alive": True,
                "reconnect_login_observed": True,
                "reconnect_resubscribed": True,
                "reconnect_rest_reconciled": True,
                "opening_allowed_after_reconciliation": True,
                "blockers": [],
                "promotion_evidence_ready": False,
            }

        def status(self) -> dict[str, Any]:
            return {
                "connected": True,
                "listener_alive": True,
                "opening_allowed_after_reconciliation": True,
                "blockers": [],
            }

    private_ws = ReconciledPrivateWS()
    stale_snapshot = controller._collect_exchange_snapshot(client)
    controller._commit_ledger_reconciliation(
        snapshot=stale_snapshot,
        trigger="fixture_startup",
        apply_snapshot=True,
    )
    controller._client = client  # type: ignore[assignment]
    controller._private_ws = private_ws
    controller._private_ws_generation = 4
    controller._state["private_ws"].update(
        {
            "connected": True,
            "listener_alive": True,
            "opening_allowed_after_reconciliation": True,
            "blockers": [],
        }
    )
    controller._state["runtime"].update(
        {
            "run_id": "btc-demo-run-refresh-01",
            "active": True,
            "opening_allowed": True,
            "cancel_only": False,
            "authoritative_liveness_epoch": 1,
        }
    )
    controller._state["risk_control"].update(
        {"mode": "RUNNING", "write_path_trusted": True}
    )
    observed_at[0] = datetime.now(timezone.utc)
    client.server_time_ms = str(int(observed_at[0].timestamp() * 1000))

    controller._renew_dead_man_once(client)

    status = controller.status()
    assert client.dead_man_calls == [
        {"timeout_seconds": 30, "tag": "btcP0Demo"}
    ]
    assert private_ws.reconcile_calls == 0
    assert status["exchange"]["captured_at_utc"] == current.isoformat()
    assert status["ledger_reconciliation"]["trigger"] == "fixture_startup"
    assert status["runtime"]["opening_allowed"] is True
    assert status["runtime"]["cancel_only"] is False
    assert status["risk_control"]["mode"] == "RUNNING"


def _bounded_protective_authority_controller(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[
    OkxDemoPaperRuntimeController,
    SnapshotClient,
    list[datetime],
    datetime,
]:
    captured_at = datetime(2026, 8, 17, 8, 0, tzinfo=timezone.utc)
    current = [captured_at]

    class DemoAdapter:
        def capability_for(self, *, action, transport_context):
            assert action is RuntimeAction.DEAD_MAN
            assert isinstance(transport_context, SnapshotClient)
            return BTCEndpointCapability(
                mode=BTCExecutionMode.DEMO,
                transport_enabled=True,
                submit_new_order=True,
                cancel_order=True,
                reduce_only=True,
                attach_protection=True,
                dead_man=True,
                private_endpoint_allowed=True,
                order_endpoint_allowed=True,
            )

    monkeypatch.setattr(
        btc_control_plane_module,
        "utc_now",
        lambda: current[0],
    )
    monkeypatch.setattr(
        runtime_permissions_module,
        "utc_now",
        lambda: current[0],
    )
    dispatcher = BTCDemoExecutionDispatcher(
        expected_source_head=_repo_head_for_test(),
        state_directory=tmp_path / "btc-demo-boundary",
        capability_adapter=DemoAdapter(),
        credential_service="quant-system.okx-demo.trade",
    )
    client = SnapshotClient(
        server_time_ms=str(int(captured_at.timestamp() * 1000))
    )
    controller = OkxDemoPaperRuntimeController(
        config=OkxDemoPaperRuntimeConfig(
            repo_root=Path.cwd(),
            data_db_path=tmp_path / "unused.sqlite",
            output_dir=tmp_path / "output" / "btc_demo_paper_runtime",
            execution_dispatcher=dispatcher,
        ),
        credential_loader=lambda _: _credentials(),
        clock=lambda: current[0],
        start_worker=False,
    )
    snapshot = controller._collect_exchange_snapshot(client)
    controller._commit_ledger_reconciliation(
        snapshot=snapshot,
        trigger="fixture_startup",
        apply_snapshot=True,
    )
    controller._client = client  # type: ignore[assignment]
    controller._state["private_ws"].update(
        {
            "connected": True,
            "listener_alive": True,
            "opening_allowed_after_reconciliation": True,
            "blockers": [],
        }
    )
    controller._state["runtime"].update(
        {
            "run_id": "bounded-protective-authority-01",
            "active": True,
            "status": "running",
            "opening_allowed": True,
            "cancel_only": False,
            "authoritative_liveness_epoch": 8,
        }
    )
    controller._state["risk_control"].update(
        {"mode": "RUNNING", "write_path_trusted": True}
    )
    return controller, client, current, captured_at


def test_dead_man_renews_twice_from_bounded_durable_authority_without_slow_refresh(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller, client, current, captured_at = (
        _bounded_protective_authority_controller(tmp_path, monkeypatch)
    )
    private_calls_before = len(client.private_calls)
    public_calls_before = len(client.public_calls)

    def forbidden_refresh(_client: SnapshotClient) -> dict[str, Any]:
        raise AssertionError("protective_renewal_must_not_wait_for_slow_refresh")

    controller._refresh_dead_man_authoritative_snapshot = (  # type: ignore[method-assign]
        forbidden_refresh
    )

    current[0] = captured_at + timedelta(seconds=45)
    controller._renew_dead_man_once(client)
    current[0] = captured_at + timedelta(seconds=75)
    controller._renew_dead_man_once(client)

    assert client.dead_man_calls == [
        {"timeout_seconds": 30, "tag": "btcP0Demo"},
        {"timeout_seconds": 30, "tag": "btcP0Demo"},
    ]
    assert len(client.private_calls) == private_calls_before
    assert len(client.public_calls) == public_calls_before
    assert client.order_calls == []
    assert client.cancel_calls == []


@pytest.mark.parametrize("authority_failure", ["expired", "private_ws", "ledger"])
def test_dead_man_loop_fails_closed_without_caa_when_durable_authority_is_invalid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    authority_failure: str,
) -> None:
    controller, client, current, captured_at = (
        _bounded_protective_authority_controller(tmp_path, monkeypatch)
    )
    current[0] = captured_at + timedelta(
        seconds=121 if authority_failure == "expired" else 45
    )
    if authority_failure == "private_ws":
        controller._state["private_ws"]["connected"] = False
    if authority_failure == "ledger":
        controller._state["ledger_reconciliation"]["status"] = "not_observed"
    controller._state["runtime"]["authoritative_liveness_required"] = False
    controller._state["risk_control"]["dead_man"].update(
        {
            "armed": True,
            "last_ack_utc": current[0].isoformat(),
            "heartbeat_thread_alive": True,
            "watchdog_renews_dead_man": True,
        }
    )
    controller._stop_event = StepStopEvent([False])

    def forbidden_refresh(_client: SnapshotClient) -> dict[str, Any]:
        raise AssertionError("invalid_durable_authority_must_not_trigger_refresh")

    controller._refresh_dead_man_authoritative_snapshot = (  # type: ignore[method-assign]
        forbidden_refresh
    )

    controller._dead_man_loop()

    status = controller.status()
    assert client.dead_man_calls == []
    assert client.order_calls == []
    assert client.cancel_calls == []
    assert status["runtime"]["opening_allowed"] is False
    assert status["runtime"]["cancel_only"] is True
    assert status["risk_control"]["mode"] == "FROZEN_UNKNOWN"
    assert "okx_demo_dead_man_heartbeat_unknown" in status["runtime"]["last_error"]


def test_worker_progress_liveness_is_decoupled_from_dead_man_ttl_but_thread_is_mandatory(
    tmp_path: Path,
) -> None:
    current = datetime(2026, 8, 17, 8, 0, tzinfo=timezone.utc)
    controller = OkxDemoPaperRuntimeController(
        config=OkxDemoPaperRuntimeConfig(
            repo_root=tmp_path,
            data_db_path=tmp_path / "missing.sqlite",
            output_dir=tmp_path / "output" / "btc_demo_paper_runtime",
        ),
        credential_loader=lambda _: _credentials(),
        clock=lambda: current,
        start_worker=False,
    )
    controller._state["runtime"].update(
        {
            "active": True,
            "last_heartbeat_utc": (current - timedelta(seconds=90)).isoformat(),
            "authoritative_liveness_required": True,
            "authoritative_liveness_worker_required": True,
            "authoritative_liveness_epoch": 9,
            "worker_alive": True,
        }
    )
    controller._state["risk_control"]["dead_man"].update(
        {
            "armed": True,
            "last_ack_utc": current.isoformat(),
            "heartbeat_thread_alive": True,
            "watchdog_renews_dead_man": True,
            "renewal_owner": controller._authoritative_renewal_owner(epoch=9),
        }
    )

    blockers = controller._authoritative_liveness_blockers(
        controller._state,
        worker_alive=True,
        dead_man_thread_alive=True,
    )
    assert "okx_demo_authoritative_liveness_worker_heartbeat_stale" not in blockers

    dead_thread_blockers = controller._authoritative_liveness_blockers(
        controller._state,
        worker_alive=False,
        dead_man_thread_alive=True,
    )
    assert "okx_demo_authoritative_liveness_worker_dead" in dead_thread_blockers

    controller._state["runtime"]["last_heartbeat_utc"] = (
        current - timedelta(seconds=121)
    ).isoformat()
    stale_blockers = controller._authoritative_liveness_blockers(
        controller._state,
        worker_alive=True,
        dead_man_thread_alive=True,
    )
    assert "okx_demo_authoritative_liveness_worker_heartbeat_stale" in stale_blockers


@pytest.mark.parametrize("stale_final_snapshot", [False, True])
def test_slow_authoritative_recovery_renews_dead_man_then_recollects_before_opening(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    stale_final_snapshot: bool,
) -> None:
    """A slow WS/ledger chain may protect, but never reopen from old facts."""

    current = [datetime.now(timezone.utc) - timedelta(seconds=45)]
    source_head = _repo_head_for_test()
    collected_at: list[datetime] = []

    class ClockedClient(SnapshotClient):
        def public_get(
            self,
            path: str,
            params: Mapping[str, Any] | None = None,
        ) -> OkxDemoResponse:
            if path == "/api/v5/public/time":
                self.server_time_ms = str(
                    int(current[0].timestamp() * 1000)
                )
            return super().public_get(path, params)

    class SlowCurrentPrivateWS:
        reconcile_calls = 0

        def reconcile_current(self) -> dict[str, Any]:
            self.reconcile_calls += 1
            current[0] = datetime.now(timezone.utc)
            return {
                "schema_version": "btc_okx_demo_private_ws_current_reconciliation_v1",
                "source_head": source_head,
                "runtime_version": "okx_demo_paper_runtime_v1",
                "generated_at_utc": current[0].isoformat(),
                "connected": True,
                "listener_alive": True,
                "reconnect_login_observed": True,
                "reconnect_resubscribed": True,
                "reconnect_rest_reconciled": True,
                "opening_allowed_after_reconciliation": True,
                "blockers": [],
                "promotion_evidence_ready": False,
            }

        def status(self) -> dict[str, Any]:
            return {
                "connected": True,
                "listener_alive": True,
                "opening_allowed_after_reconciliation": True,
                "blockers": [],
            }

    class DemoAdapter:
        def capability_for(self, *, action, transport_context):
            assert action is RuntimeAction.DEAD_MAN
            assert isinstance(transport_context, ClockedClient)
            return BTCEndpointCapability(
                mode=BTCExecutionMode.DEMO,
                transport_enabled=True,
                submit_new_order=True,
                cancel_order=True,
                reduce_only=True,
                attach_protection=True,
                dead_man=True,
                private_endpoint_allowed=True,
                order_endpoint_allowed=True,
            )

    monkeypatch.setattr(
        btc_control_plane_module,
        "utc_now",
        lambda: current[0],
    )
    dispatcher = BTCDemoExecutionDispatcher(
        expected_source_head=source_head,
        state_directory=tmp_path / "btc-demo-boundary",
        capability_adapter=DemoAdapter(),
        credential_service="quant-system.okx-demo.trade",
    )
    client = ClockedClient()
    private_ws = SlowCurrentPrivateWS()
    controller = OkxDemoPaperRuntimeController(
        config=OkxDemoPaperRuntimeConfig(
            repo_root=Path.cwd(),
            data_db_path=tmp_path / "unused.sqlite",
            output_dir=tmp_path / "output" / "btc_demo_paper_runtime",
            execution_dispatcher=dispatcher,
        ),
        credential_loader=lambda _: _credentials(),
        clock=lambda: current[0],
        start_worker=False,
    )
    controller._client = client  # type: ignore[assignment]
    controller._private_ws = private_ws
    controller._private_ws_generation = 3
    controller._state["runtime"].update(
        {
            "run_id": "slow-authority-recovery-01",
            "active": True,
            "status": "cancel_only",
            "opening_allowed": False,
            "cancel_only": True,
            "authoritative_liveness_epoch": 4,
            "blockers": ["okx_demo_transient:authority_chain_slow"],
        }
    )
    controller._state["risk_control"].update(
        {"mode": "FROZEN_UNKNOWN", "write_path_trusted": False}
    )
    controller._state["private_ws"].update(
        {
            "connected": False,
            "listener_alive": False,
            "opening_allowed_after_reconciliation": False,
        }
    )
    original_collect = controller._collect_exchange_snapshot

    def collect(active_client: SnapshotClient) -> dict[str, Any]:
        snapshot = original_collect(active_client)
        captured_at = datetime.fromisoformat(snapshot["captured_at_utc"])
        collected_at.append(captured_at)
        return snapshot

    controller._collect_exchange_snapshot = collect  # type: ignore[method-assign]
    original_commit = controller._commit_ledger_reconciliation

    def commit(**kwargs: Any) -> None:
        original_commit(**kwargs)
        if (
            stale_final_snapshot
            and kwargs.get("trigger")
            == "frozen_state_opening_snapshot_refresh"
        ):
            current[0] += timedelta(seconds=31)

    controller._commit_ledger_reconciliation = commit  # type: ignore[method-assign]

    if stale_final_snapshot:
        with pytest.raises(
            OkxDemoPaperRuntimeError,
            match="authoritative_opening_snapshot_stale",
        ):
            controller._recover_transient_cycle()
    else:
        controller._recover_transient_cycle()

    status = controller.status()
    assert private_ws.reconcile_calls == 1
    assert client.dead_man_calls == [
        {"timeout_seconds": 30, "tag": "btcP0Demo"}
    ]
    assert len(collected_at) == 2
    assert collected_at[0] <= current[0] - timedelta(seconds=30)
    if stale_final_snapshot:
        assert current[0] - collected_at[1] > timedelta(seconds=30)
        assert status["runtime"]["opening_allowed"] is False
        assert status["runtime"]["cancel_only"] is True
        assert status["risk_control"]["mode"] == "FROZEN_UNKNOWN"
    else:
        assert current[0] - collected_at[1] <= timedelta(seconds=30)
        assert status["exchange"]["captured_at_utc"] == collected_at[1].isoformat()
        assert status["runtime"]["opening_allowed"] is True
        assert status["runtime"]["cancel_only"] is False
        assert status["risk_control"]["mode"] == "RUNNING"
    assert client.order_calls == []


def test_incomplete_durable_authority_never_refreshes_or_calls_caa(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller, client, current, captured_at = (
        _bounded_protective_authority_controller(tmp_path, monkeypatch)
    )
    current[0] = captured_at + timedelta(seconds=45)
    controller._state["private_ws"]["listener_alive"] = False

    def forbidden_refresh(_client: SnapshotClient) -> dict[str, Any]:
        raise AssertionError("protective_path_must_not_refresh")

    controller._refresh_dead_man_authoritative_snapshot = (  # type: ignore[method-assign]
        forbidden_refresh
    )

    with pytest.raises(
        OkxDemoPaperRuntimeError,
        match="execution_boundary_dispatch_failed",
    ):
        controller._renew_dead_man_once(client)

    assert client.dead_man_calls == []
    assert client.order_calls == []
    assert client.cancel_calls == []
    assert controller._state["exchange"]["captured_at_utc"] == captured_at.isoformat()


def test_okx_native_tail_merge_failure_blocks_before_private_ws_or_order_capability(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    baseline_end = datetime(2026, 7, 30, 0, 0, tzinfo=timezone.utc)
    now = baseline_end + timedelta(hours=4)
    baseline = _large_hourly_frame(baseline_end)
    client = SnapshotClient(
        candle_rows=[_candle_row(baseline_end - timedelta(hours=1))],
        server_time_ms=str(int(now.timestamp() * 1000)),
    )
    native_spec = next(
        spec
        for spec in btc_strategy_registry.list_specs()
        if spec.strategy_id == "long_short_donchian_top5_okx_native"
    )
    monkeypatch.setattr(
        okx_demo_runtime_module,
        "load_completed_okx_native_hourly_frame",
        lambda *_args, **_kwargs: baseline,
    )
    FakePrivateWS.instances.clear()
    controller = OkxDemoPaperRuntimeController(
        config=OkxDemoPaperRuntimeConfig(
            repo_root=tmp_path,
            data_db_path=tmp_path / "unused.sqlite",
            output_dir=tmp_path / "output" / "btc_demo_paper_runtime",
        ),
        credential_loader=lambda _: _credentials(),
        client_factory=lambda _config, _credentials_value: client,
        private_ws_factory=FakePrivateWS,
        clock=lambda: now,
        start_worker=False,
    )

    with pytest.raises(
        OkxDemoPaperRuntimeError,
        match="okx_demo_public_candle_tail_stale",
    ):
        controller.start(_start_payload_for(native_spec))

    status = controller.status()
    assert status["runtime"]["opening_allowed"] is False
    assert status["runtime"]["status"] == "start_blocked_fail_closed"
    assert status["safety"]["okx_demo_order_capability_enabled"] is False
    assert status["safety"]["live_order_allowed"] is False
    assert status["safety"]["real_money_order_allowed"] is False
    # Native public completed-1h tail admission precedes every private snapshot
    # read.  A stale/gapped tail must therefore fail before a credentialed REST
    # call, not merely before WS/order capability becomes available.
    assert client.private_calls == []
    assert FakePrivateWS.instances == []


def test_public_candle_tail_keeps_25h_runtime_fresh_beyond_baseline_2h() -> None:
    baseline_end = datetime(2026, 7, 30, 0, 0, tzinfo=timezone.utc)
    baseline = _baseline_frame(baseline_end)
    client = PublicCandleClient(
        [
            _candle_row(baseline_end + timedelta(hours=2), confirm="0"),
            _candle_row(baseline_end + timedelta(hours=1), confirm="1"),
            _candle_row(baseline_end, confirm="1"),
        ]
    )

    combined, evidence = (
        okx_demo_runtime_module._merge_okx_native_public_candle_tail(
            baseline=baseline,
            client=client,
            now=baseline_end + timedelta(hours=2, minutes=5),
        )
    )

    assert combined.index[-1] == baseline_end + timedelta(hours=2)
    assert evidence["sample_end_utc"] == (
        baseline_end + timedelta(hours=2)
    ).isoformat()
    assert evidence["unconfirmed_rows_excluded"] == 1
    assert evidence["api_key_used"] is False
    assert evidence["persisted_market_rows"] is False
    assert client.calls == [
        {
            "path": "/api/v5/market/candles",
            "params": {
                "instId": "BTC-USDT-SWAP",
                "bar": "1H",
                "limit": "100",
            },
        }
    ]


def test_public_candle_tail_paginates_backward_until_baseline_overlap() -> None:
    baseline_end = datetime(2026, 7, 30, 11, 0, tzinfo=timezone.utc)
    baseline = _baseline_frame(baseline_end)
    first_page_oldest_open = baseline_end + timedelta(hours=1)
    first_page_oldest_ms = str(int(first_page_oldest_open.timestamp() * 1_000))
    first_page = [
        _candle_row(
            baseline_end + timedelta(hours=offset),
            confirm="0" if offset == 101 else "1",
        )
        for offset in range(101, 0, -1)
    ]
    client = PaginatedPublicCandleClient(
        {
            None: first_page,
            first_page_oldest_ms: [
                _candle_row(first_page_oldest_open),
                _candle_row(baseline_end - timedelta(hours=1), confirm="0"),
                _candle_row(baseline_end),
                _candle_row(baseline_end - timedelta(hours=1)),
            ],
        }
    )

    combined, evidence = (
        okx_demo_runtime_module._merge_okx_native_public_candle_tail(
            baseline=baseline,
            client=client,
            now=baseline_end + timedelta(hours=101, minutes=5),
        )
    )

    recent = combined.loc[combined.index >= baseline_end]
    assert recent.index.tolist() == [
        baseline_end + timedelta(hours=offset) for offset in range(102)
    ]
    assert recent.index.is_unique
    assert evidence["unconfirmed_rows_excluded"] == 2
    assert evidence["bounded_row_count"] == 100
    assert evidence["sample_end_utc"] == (
        baseline_end + timedelta(hours=101)
    ).isoformat()
    assert client.calls == [
        {
            "path": "/api/v5/market/candles",
            "params": {
                "instId": "BTC-USDT-SWAP",
                "bar": "1H",
                "limit": "100",
            },
        },
        {
            "path": "/api/v5/market/candles",
            "params": {
                "instId": "BTC-USDT-SWAP",
                "bar": "1H",
                "limit": "100",
                "after": first_page_oldest_ms,
            },
        },
    ]


def test_public_candle_tail_pagination_fails_closed_on_no_progress() -> None:
    baseline_end = datetime(2026, 7, 30, 11, 0, tzinfo=timezone.utc)
    client = PublicCandleClient(
        [
            _candle_row(baseline_end + timedelta(hours=3)),
            _candle_row(baseline_end + timedelta(hours=2)),
        ]
    )

    with pytest.raises(
        OkxDemoPaperRuntimeError,
        match="pagination_no_progress",
    ):
        okx_demo_runtime_module._merge_okx_native_public_candle_tail(
            baseline=_baseline_frame(baseline_end),
            client=client,
            now=baseline_end + timedelta(hours=5),
        )

    assert len(client.calls) == 2


def test_public_candle_tail_pagination_has_bounded_page_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline_end = datetime(2026, 7, 30, 11, 0, tzinfo=timezone.utc)
    first_oldest_open = baseline_end + timedelta(hours=5)
    second_oldest_open = baseline_end + timedelta(hours=3)
    client = PaginatedPublicCandleClient(
        {
            None: [
                _candle_row(first_oldest_open + timedelta(hours=1)),
                _candle_row(first_oldest_open),
            ],
            str(int(first_oldest_open.timestamp() * 1_000)): [
                _candle_row(second_oldest_open + timedelta(hours=1)),
                _candle_row(second_oldest_open),
            ],
        }
    )
    monkeypatch.setattr(
        okx_demo_runtime_module,
        "OKX_DEMO_PUBLIC_CANDLE_MAX_PAGES",
        2,
    )

    with pytest.raises(
        OkxDemoPaperRuntimeError,
        match="pagination_limit_reached",
    ):
        okx_demo_runtime_module._merge_okx_native_public_candle_tail(
            baseline=_baseline_frame(baseline_end),
            client=client,
            now=baseline_end + timedelta(hours=8),
        )

    assert len(client.calls) == 2


@pytest.mark.parametrize(
    ("rows", "error"),
    [
        (
            [_candle_row(datetime(2026, 7, 30, 0, 0, tzinfo=timezone.utc), confirm="0")],
            "confirmed_rows_missing",
        ),
        (
            [
                _candle_row(datetime(2026, 7, 30, 0, 0, tzinfo=timezone.utc)),
                _candle_row(datetime(2026, 7, 30, 2, 0, tzinfo=timezone.utc)),
            ],
            "tail_gap",
        ),
        (
            [_candle_row(datetime(2026, 7, 29, 23, 0, tzinfo=timezone.utc))],
            "tail_stale",
        ),
        (
            [_candle_row(datetime(2026, 7, 30, 2, 0, tzinfo=timezone.utc))],
            "pagination_no_progress",
        ),
    ],
)
def test_public_candle_tail_unconfirmed_or_gap_fails_closed(
    rows: list[list[str]],
    error: str,
) -> None:
    baseline_end = datetime(2026, 7, 30, 0, 0, tzinfo=timezone.utc)
    with pytest.raises(OkxDemoPaperRuntimeError, match=error):
        okx_demo_runtime_module._merge_okx_native_public_candle_tail(
            baseline=_baseline_frame(baseline_end),
            client=PublicCandleClient(rows),
            now=baseline_end + timedelta(hours=4),
        )


def test_runtime_auto_captures_one_receipt_per_completed_hour_until_25h(
    tmp_path: Path,
) -> None:
    current = [datetime(2026, 7, 30, 0, 0, tzinfo=timezone.utc)]
    controller = OkxDemoPaperRuntimeController(
        config=OkxDemoPaperRuntimeConfig(
            repo_root=Path.cwd(),
            data_db_path=tmp_path / "unused.sqlite",
            output_dir=tmp_path / "output" / "btc_demo_paper_runtime",
        ),
        credential_loader=lambda _: _credentials(),
        clock=lambda: current[0],
        start_worker=False,
    )
    spec = btc_strategy_registry.list_specs()[0]
    controller._state["runtime"].update(
        {
            "run_id": "natural-25h",
            "active": True,
            "opening_allowed": True,
            "cancel_only": False,
            "started_at_utc": current[0].isoformat(),
        }
    )
    controller._state["strategy"] = spec.identity()
    controller._state["private_ws"] = {
        "opening_allowed_after_reconciliation": True,
        "reconnect_rest_reconciled": True,
        "promotion_evidence_ready": False,
    }
    decision = {
        "strategy_version": spec.strategy_version,
        "runtime_data_version": "okx_public_candles_1h_v1",
        "runtime_public_candle_tail": {
            "source": "okx_public_rest",
            "confirmed_only": True,
            "integrity_passed": True,
        },
    }
    snapshot = {
        "fills": [],
        "bills": [],
    }

    for hour in range(1, 26):
        current[0] = datetime(2026, 7, 30, 0, 0, tzinfo=timezone.utc) + timedelta(hours=hour)
        controller._capture_completed_hour_receipt(
            snapshot=snapshot,
            decision=decision,
        )
        controller._capture_completed_hour_receipt(
            snapshot=snapshot,
            decision=decision,
        )

    observation = controller.status()["observation"]
    assert observation["observation_receipt_count"] == 25
    assert observation["consecutive_hours"] == 25
    assert observation["window_complete"] is True
    assert len(observation["ledger_hash"]) == 64
    assert observation["promotion_evidence_ready"] is False


def test_runtime_hour_gap_restarts_observation_segment(tmp_path: Path) -> None:
    started = datetime(2026, 7, 30, 0, 0, tzinfo=timezone.utc)
    current = [started]
    controller = OkxDemoPaperRuntimeController(
        config=OkxDemoPaperRuntimeConfig(
            repo_root=Path.cwd(),
            data_db_path=tmp_path / "unused.sqlite",
            output_dir=tmp_path / "output" / "btc_demo_paper_runtime",
        ),
        credential_loader=lambda _: _credentials(),
        clock=lambda: current[0],
        start_worker=False,
    )
    spec = btc_strategy_registry.list_specs()[0]
    controller._state["runtime"].update(
        {
            "run_id": "gap",
            "active": True,
            "opening_allowed": True,
            "cancel_only": False,
            "started_at_utc": started.isoformat(),
        }
    )
    controller._state["strategy"] = spec.identity()
    controller._state["private_ws"] = {
        "opening_allowed_after_reconciliation": True,
        "reconnect_rest_reconciled": True,
    }
    decision = {
        "strategy_version": spec.strategy_version,
        "runtime_data_version": "okx_public_candles_1h_v1",
    }
    for hour in (1, 3):
        current[0] = started + timedelta(hours=hour)
        controller._capture_completed_hour_receipt(
            snapshot={"fills": [], "bills": []},
            decision=decision,
        )

    observation = controller.status()["observation"]
    assert observation["observation_receipt_count"] == 2
    assert observation["consecutive_hours"] == 1
    assert observation["window_complete"] is False
    assert "btc_demo_observation_gap_present" in observation["blockers"]


def test_runtime_commits_atomic_funding_ledger_uow_and_exchange_reconciliation(
    tmp_path: Path,
) -> None:
    controller = OkxDemoPaperRuntimeController(
        config=OkxDemoPaperRuntimeConfig(
            repo_root=Path.cwd(),
            data_db_path=tmp_path / "unused.sqlite",
            output_dir=tmp_path / "output" / "btc_demo_paper_runtime",
        ),
        credential_loader=lambda _: _credentials(),
        start_worker=False,
    )
    controller._state["runtime"].update(
        {"run_id": "ledger", "active": True}
    )
    snapshot = {
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "orders": [{"order_id": "order-1", "state": "filled"}],
        "pending_orders": [],
        "fills": [
            {
                "fill_id": "fill-1",
                "order_id": "order-1",
                "price": "60000",
                "size": "0.01",
            }
        ],
        "positions": [],
        "balance": {"equity_usdt": "100", "available_usdt": "99"},
        "bills": [
            {
                "bill_id": "funding-1",
                "instrument_id": "BTC-USDT-SWAP",
                "type": "8",
                "sub_type": "173",
                "balance_change": "-0.001",
            }
        ],
        "mark": {"mark_price": "60000"},
        "index": {"index_price": "59999"},
        "instrument": {
            "instrument_id": "BTC-USDT-SWAP",
            "contract_value_btc": "0.01",
            "tick_size": "0.1",
            "lot_size": "0.01",
            "minimum_size": "0.01",
        },
        "ticker": {},
        "book": {},
        "funding": {},
    }
    with controller._lock:
        controller._apply_snapshot(snapshot)

    controller._commit_new_funding_if_observed(snapshot=snapshot)
    controller._commit_new_funding_if_observed(snapshot=snapshot)

    state = controller.status()
    assert state["ledger_reconciliation"][
        "current_state_exchange_snapshot_match"
    ] is True
    assert state["ledger_reconciliation"][
        "funding_cashflow_reconciled"
    ] is True
    assert state["ledger_reconciliation"]["funding_cashflow"] == "-0.001"
    events = [
        json.loads(line)
        for line in (
            tmp_path
            / "output"
            / "btc_demo_paper_runtime"
            / "events.jsonl"
        ).read_text(encoding="utf-8").splitlines()
    ]
    ledger_events = [
        event for event in events if event["event_type"] == "ledger_uow_committed"
    ]
    assert len(ledger_events) == 1
    payload = ledger_events[0]["payload"]
    assert payload["order_ledger"]["orders"][0]["order_id"] == "order-1"
    assert payload["fill_ledger"][0]["fill_id"] == "fill-1"
    assert payload["position_ledger"]["reconciliation_match"] is True
    assert payload["cash_ledger"]["reconciliation_match"] is True
    assert payload["funding_ledger"]["cashflow"] == "-0.001"
    assert payload["funding_ledger"]["fixture"] is False
    assert payload["risk_context"]["mark_price"] == "60000"
    assert payload["risk_context"]["index_price"] == "59999"
    assert payload["risk_context"]["venue_rules"]["minimum_size"] == "0.01"
    assert "events" not in ledger_events[0]["state_after"]
    checkpoint = json.loads(
        (
            tmp_path
            / "output"
            / "btc_demo_paper_runtime"
            / "state.json"
        ).read_text(encoding="utf-8")
    )
    assert "events" not in checkpoint["state"]


def test_identity_only_strategy_is_rejected_fail_closed(tmp_path: Path) -> None:
    controller = _controller(tmp_path, lambda _: _credentials())
    payload = _valid_start_payload()
    identity_only = next(spec for spec in btc_strategy_registry.list_specs() if spec.strategy_id == "high_yield_donchian_v2")
    payload.update(
        {
            "strategy_id": identity_only.strategy_id,
            "candidate_id": identity_only.candidate_id,
            "strategy_version": identity_only.strategy_version,
        }
    )

    with pytest.raises(OkxDemoPaperRuntimeError, match="strategy_not_allowlisted"):
        controller.start(payload)


def test_adapter_allows_authorized_short_and_public_funding_query() -> None:
    transport = FakeTransport()
    client = OkxDemoClient(
        config=OkxDemoClientConfig(
            allow_demo_orders=True,
            allow_demo_cancels=True,
            authorization_ticket=OKX_DEMO_PAPER_AUTHORIZATION_TICKET,
            max_order_contracts=Decimal("0.01"),
            max_notional_usdt=Decimal("10"),
            contract_value_btc=Decimal("0.01"),
        ),
        credentials=_credentials(),
        transport=transport,
    )

    client.public_get("/api/v5/public/funding-rate", {"instId": "BTC-USDT-SWAP"})
    client.submit_order(
        {
            "instId": "BTC-USDT-SWAP",
            "tdMode": "isolated",
            "side": "sell",
            "posSide": "short",
            "ordType": "fok",
            "px": "60000",
            "sz": "0.01",
            "clOrdId": "btcDemoShortV1",
            "tag": "btcP0Demo",
            "attachAlgoOrds": [
                {
                    "attachAlgoClOrdId": "btcDemoShortAlgoV1",
                    "tpTriggerPx": "58800",
                    "tpOrdPx": "-1",
                    "tpTriggerPxType": "mark",
                    "slTriggerPx": "60600",
                    "slOrdPx": "-1",
                    "slTriggerPxType": "mark",
                }
            ],
        }
    )

    assert transport.calls[0]["method"] == "GET"
    assert "/api/v5/public/funding-rate" in transport.calls[0]["url"]
    assert "x-simulated-trading" not in {key.lower(): value for key, value in transport.calls[0]["headers"].items()}
    assert transport.calls[1]["method"] == "POST"
    assert transport.calls[1]["headers"]["x-simulated-trading"] == "1"
    assert json.loads(transport.calls[1]["body"].decode("utf-8"))["posSide"] == "short"


def test_snapshot_queries_swap_fee_by_instrument_family(tmp_path: Path) -> None:
    controller = _controller(tmp_path, lambda _: _credentials())
    client = SnapshotClient()

    controller._collect_exchange_snapshot(client)

    fee_call = next(call for call in client.private_calls if call["path"] == "/api/v5/account/trade-fee")
    assert fee_call["params"] == {"instType": "SWAP", "instFamily": "BTC-USDT"}
    assert "instId" not in fee_call["params"]


def test_chart_falls_back_only_to_manifest_hash_verified_mark_rows(tmp_path: Path) -> None:
    database = tmp_path / "data" / "market_data.sqlite"
    database.parent.mkdir(parents=True)
    connection = sqlite3.connect(database)
    try:
        connection.execute(
            """
            CREATE TABLE market_klines (
                exchange TEXT, symbol TEXT, interval TEXT, open_time_ms INTEGER,
                open_time TEXT, open REAL, high REAL, low REAL, close REAL,
                volume REAL, quote_volume REAL, trade_count INTEGER
            )
            """
        )
        connection.commit()
    finally:
        connection.close()
    mark_path = tmp_path / "shared" / "mark_price_klines_1h.csv"
    mark_path.parent.mkdir(parents=True)
    mark_path.write_text(
        "timestamp,open_time_ms,open,high,low,close,volume,close_time_ms,source_record_id\n"
        "2026-07-14T00:00:00Z,1783987200000,100,110,90,105,12,1783990799999,row-1\n",
        encoding="utf-8",
    )
    mark_hash = hashlib.sha256(mark_path.read_bytes()).hexdigest()
    data_manifest_path = tmp_path / "artifacts" / "source" / "data_manifest.json"
    data_manifest_path.parent.mkdir(parents=True)
    data_manifest_path.write_text(
        json.dumps({"execution_cost_proxy": {"mark_price_path": str(mark_path), "mark_price_sha256": mark_hash}}),
        encoding="utf-8",
    )
    run_manifest_path = tmp_path / "artifacts" / "revalidation" / "run_manifest.json"
    run_manifest_path.parent.mkdir(parents=True)
    run_manifest_path.write_text(
        json.dumps({"outputs": {"source_data_manifest": str(data_manifest_path)}}),
        encoding="utf-8",
    )
    latest_path = tmp_path / "artifacts" / "btc_strategy_backtest_runs" / "latest_manifest.json"
    latest_path.parent.mkdir(parents=True)
    latest_path.write_text(
        json.dumps({"canonical_manifest": {"path": str(run_manifest_path)}}),
        encoding="utf-8",
    )

    payload = load_btc_chart_payload(repo_root=tmp_path, db_path=database, limit=10)

    assert payload["source_kind"] == "canonical_manifest_verified_mark_price_1h"
    assert payload["source_sha256"] == mark_hash
    assert payload["strategy_signal_compatible"] is False
    assert payload["schema_maintenance_performed"] is False
    assert payload["rows"][0]["close"] == 105.0


def test_chart_pointer_missing_never_silently_falls_back_to_binance_sqlite(
    tmp_path: Path,
) -> None:
    database = tmp_path / "data" / "market_data.sqlite"
    database.parent.mkdir(parents=True)
    connection = sqlite3.connect(database)
    try:
        connection.execute(
            """
            CREATE TABLE market_klines (
                exchange TEXT, symbol TEXT, interval TEXT, open_time_ms INTEGER,
                open_time TEXT, open REAL, high REAL, low REAL, close REAL,
                volume REAL, quote_volume REAL, trade_count INTEGER
            )
            """
        )
        connection.execute(
            """
            INSERT INTO market_klines VALUES (
                'binance_spot', 'BTCUSDT', '1h', 1783987200000,
                '2026-07-14T00:00:00Z', 100, 110, 90, 105, 12, 1260, 4
            )
            """
        )
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(
        OkxDemoPaperRuntimeError,
        match="btc_chart_okx_completed_1h_unavailable",
    ):
        load_btc_chart_payload(
            repo_root=tmp_path,
            db_path=database,
            limit=10,
        )


def test_active_runtime_chart_cache_returns_latest_confirmed_okx_completed_hour(
    tmp_path: Path,
) -> None:
    controller = _controller(tmp_path, lambda _: _credentials())
    first_close = datetime(2026, 8, 16, 10, 0, tzinfo=timezone.utc)
    second_close = first_close + timedelta(hours=1)
    frame = okx_demo_runtime_module.pd.DataFrame(
        [
            {
                "open_time": first_close - timedelta(hours=1),
                "open": 60000,
                "high": 60100,
                "low": 59900,
                "close": 60050,
                "volume": 10,
            },
            {
                "open_time": second_close - timedelta(hours=1),
                "open": 60050,
                "high": 60200,
                "low": 60000,
                "close": 60150,
                "volume": 12,
            },
        ],
        index=okx_demo_runtime_module.pd.DatetimeIndex(
            [first_close, second_close],
            name="close_time",
        ),
    )

    controller._cache_runtime_completed_chart_frame(
        frame,
        evidence={
            "source": "okx_public_rest_market_candles",
            "sample_end_utc": second_close.isoformat(),
            "tail_sha256": "a" * 64,
            "unconfirmed_rows_excluded": 1,
        },
    )
    payload = controller.readonly_chart_payload(limit=1)

    assert payload is not None
    assert payload["source_kind"] == "okx_runtime_confirmed_completed_swap_1h"
    assert payload["strategy_signal_compatible"] is True
    assert payload["sample_end"] == second_close.isoformat()
    assert payload["rows"] == [
        {
            "exchange": "okx_swap",
            "symbol": "BTC-USDT-SWAP",
            "interval": "1h",
            "time": (second_close - timedelta(hours=1)).isoformat(),
            "open_time_ms": int(
                (second_close - timedelta(hours=1)).timestamp() * 1000
            ),
            "open": 60050.0,
            "high": 60200.0,
            "low": 60000.0,
            "close": 60150.0,
            "volume": 12.0,
            "quote_volume": 0.0,
            "trade_count": 0,
        }
    ]
    assert payload["runtime_public_candle_tail"]["unconfirmed_rows_excluded"] == 1


def test_chart_freshness_uses_completed_close_time_for_okx_native_rows(
    tmp_path: Path,
) -> None:
    latest_open = datetime.now(timezone.utc) - timedelta(hours=2, minutes=30)
    latest_open_ms = int(latest_open.timestamp() * 1000)
    latest_close = latest_open + timedelta(hours=1)
    bundle = tmp_path / "data" / "native"
    bundle.mkdir(parents=True)
    candle_path = bundle / "completed_swap_klines_1h.csv"
    candle_path.write_text(
        "open_time_ms,open_time_utc,close_time_ms,close_time_utc,open,high,low,close,volume_contracts,volume_base,volume_quote,confirm,source,captured_at_utc\n"
        f"{latest_open_ms},{latest_open.isoformat()},{latest_open_ms + 3_600_000},{latest_close.isoformat()},100,110,90,105,12,12,1260,1,okx_public_history_candles,{datetime.now(timezone.utc).isoformat()}\n",
        encoding="utf-8",
    )
    candle_hash = hashlib.sha256(candle_path.read_bytes()).hexdigest()
    (bundle / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "btc_okx_native_research_data_manifest_v1",
                "status": "verified",
                "blockers": [],
                "source": "OKX public REST",
                "instrument_id": "BTC-USDT-SWAP",
                "signal_timeframe": "completed_1h",
                "row_count": 4_800,
                "data_version": "fixture-data-v1",
                "sample_end_utc": latest_close.isoformat(),
                "checks": {
                    "completed_1h_only": True,
                    "hourly_unique": True,
                    "hourly_contiguous": True,
                    "public_rest_only": True,
                    "api_key_not_used": True,
                    "private_endpoint_not_used": True,
                    "order_endpoint_not_used": True,
                },
                "files": {
                    candle_path.name: {
                        "sha256": candle_hash,
                        "size_bytes": candle_path.stat().st_size,
                    }
                },
                "safety": {
                    "paper_start": False,
                    "private_endpoint_used": False,
                    "order_endpoint_used": False,
                    "real_order_submitted": False,
                },
            }
        ),
        encoding="utf-8",
    )
    latest_path = tmp_path / "artifacts" / "btc_okx_native_backtest_evidence" / "latest_manifest.json"
    latest_path.parent.mkdir(parents=True, exist_ok=True)
    latest_path.write_text(
        json.dumps(
            {
                "data_bundle_dir": str(bundle.relative_to(tmp_path)).replace("\\", "/"),
                "data_version": "fixture-data-v1",
                "source_code_commit": "stale-promotion-head",
                "demo_default_eligible": False,
            }
        ),
        encoding="utf-8",
    )

    readiness = inspect_okx_native_demo_signal_data(tmp_path)
    payload = load_btc_chart_payload(repo_root=tmp_path, db_path=tmp_path / "missing.sqlite", limit=10)

    assert readiness["eligible"] is True
    assert readiness["promotion_current_head_required"] is False
    assert payload["source_kind"] == "okx_native_manifest_verified_completed_swap_1h"
    assert payload["strategy_signal_compatible"] is True
    assert payload["freshness_status"] == "pass"
    assert payload["sample_end"] == datetime.fromtimestamp(
        (latest_open_ms + 3_600_000) / 1000,
        tz=timezone.utc,
    ).isoformat()
    assert payload["source_sha256"] == hashlib.sha256(candle_path.read_bytes()).hexdigest()
    assert payload["rows"][0]["symbol"] == "BTC-USDT-SWAP"


def test_okx_native_signal_data_resolves_verified_shared_dataset_without_physical_root_leak(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shared_root = tmp_path / "shared-data"
    bundle = (
        shared_root
        / "datasets"
        / "btc-okx-public-swap-research-bundle"
        / "fixture-v1"
    )
    bundle.mkdir(parents=True)
    current = datetime.now(timezone.utc)
    candle_path = bundle / "completed_swap_klines_1h.csv"
    candle_path.write_text(
        "open_time_ms,open_time_utc,close_time_ms,close_time_utc,open,high,low,close,volume_contracts,volume_base,volume_quote,confirm,source,captured_at_utc\n"
        f"1,{current.isoformat()},2,{current.isoformat()},100,101,99,100,1,1,100,1,okx_public_history_candles,{current.isoformat()}\n",
        encoding="utf-8",
    )
    candle_hash = hashlib.sha256(candle_path.read_bytes()).hexdigest()
    (bundle / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "btc_okx_native_research_data_manifest_v1",
                "status": "verified",
                "blockers": [],
                "source": "OKX public REST",
                "instrument_id": "BTC-USDT-SWAP",
                "signal_timeframe": "completed_1h",
                "row_count": 4800,
                "data_version": "fixture-v1",
                "sample_end_utc": current.isoformat(),
                "checks": {
                    "completed_1h_only": True,
                    "hourly_unique": True,
                    "hourly_contiguous": True,
                    "public_rest_only": True,
                    "api_key_not_used": True,
                    "private_endpoint_not_used": True,
                    "order_endpoint_not_used": True,
                },
                "files": {
                    candle_path.name: {
                        "sha256": candle_hash,
                        "size_bytes": candle_path.stat().st_size,
                    }
                },
                "safety": {
                    "paper_start": False,
                    "private_endpoint_used": False,
                    "order_endpoint_used": False,
                    "real_order_submitted": False,
                },
            }
        ),
        encoding="utf-8",
    )
    files, aggregate_hash, total_bytes = inventory_directory(bundle)
    shared_manifest = build_manifest(
        dataset_id="btc-okx-public-swap-research-bundle",
        dataset_version="fixture-v1",
        readiness_class="quality_checked",
        quality_status="pass_with_research_only_warnings",
        files=files,
        aggregate_sha256=aggregate_hash,
        total_bytes=total_bytes,
        producer_commit="1" * 40,
        schema_name=OKX_NATIVE_LEGACY_SHARED_DATA_SCHEMA,
        known_gaps=("research_only_fixture_gap",),
    )
    (bundle / MANIFEST_NAME).write_text(
        json.dumps(shared_manifest, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        okx_demo_runtime_module,
        "load_manifest_from_git",
        lambda repo_root, git_spec: shared_manifest,
    )

    readiness = inspect_okx_native_demo_signal_data(
        tmp_path,
        shared_manifest_git_spec=(
            f"{'1' * 40}:.agent/data_manifests/btc-okx-native-demo-signal.json"
        ),
        shared_data_root=shared_root,
        expected_dataset_id="btc-okx-public-swap-research-bundle",
    )

    assert readiness["eligible"] is True
    assert readiness["logical_data_id"] == "btc-okx-public-swap-research-bundle"
    assert readiness["bundle_dir"] == ""
    assert readiness["physical_root_redacted"] is True
    assert readiness["readiness_class"] == "quality_checked"
    assert readiness["quality_status"] == "pass_with_research_only_warnings"
    assert readiness["promotion_evidence_ready"] is False
    assert readiness["known_gaps"] == ["research_only_fixture_gap"]
    assert readiness["layout_schema"] == OKX_NATIVE_LEGACY_SHARED_DATA_SCHEMA
    assert str(shared_root) not in json.dumps(readiness)

    wrong_layout = {
        **shared_manifest,
        "data_schema": OKX_NATIVE_SHARED_DATA_SCHEMA,
    }
    (bundle / MANIFEST_NAME).write_text(
        json.dumps(wrong_layout, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        okx_demo_runtime_module,
        "load_manifest_from_git",
        lambda repo_root, git_spec: wrong_layout,
    )
    rejected = inspect_okx_native_demo_signal_data(
        tmp_path,
        shared_manifest_git_spec=(
            f"{'1' * 40}:.agent/data_manifests/btc-okx-native-demo-signal.json"
        ),
        shared_data_root=shared_root,
        expected_dataset_id="btc-okx-public-swap-research-bundle",
    )
    assert rejected["eligible"] is False
    assert rejected["blockers"] == [
        "okx_demo_paper_generic_public_swap_manifest_unavailable:"
        "FileNotFoundError"
    ]


def test_okx_native_signal_data_reads_explicit_generic_public_swap_bundle_layout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shared_root = tmp_path / "shared-data"
    bundle = (
        shared_root
        / "datasets"
        / "btc-okx-public-swap-research-bundle"
        / "generic-v1"
    )
    bundle.mkdir(parents=True)
    current = datetime(2026, 7, 29, 14, 0, tzinfo=timezone.utc)
    candle_path = bundle / "klines_1h.csv"
    rows = [
        "timestamp,event_time,available_time,ingested_at,processed_at,open_time,symbol,open,high,low,close,volume_contracts,volume_base,volume_quote,confirm,source_record_id"
    ]
    first_open = current - timedelta(hours=4_800)
    for index in range(4_800):
        opened = first_open + timedelta(hours=index)
        available = opened + timedelta(hours=1)
        open_ms = int(opened.timestamp() * 1_000)
        rows.append(
            f"{opened.isoformat().replace('+00:00', 'Z')},"
            f"{opened.isoformat().replace('+00:00', 'Z')},"
            f"{available.isoformat().replace('+00:00', 'Z')},"
            f"{available.isoformat().replace('+00:00', 'Z')},"
            f"{available.isoformat().replace('+00:00', 'Z')},"
            f"{open_ms},BTCUSDT,100,101,99,100,1,1,100,1,"
            f"okx:BTC-USDT-SWAP:{open_ms}"
        )
    candle_path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    supporting = {
        "mark_price_klines_1h.csv": "timestamp,confirm\n2026-07-29T13:00:00Z,1\n",
        "premium_index_klines_1h.csv": "timestamp,confirm\n2026-07-29T13:00:00Z,1\n",
        "funding_rate.csv": "timestamp,fundingRate\n2026-07-29T08:00:00Z,0.0001\n",
    }
    for name, content in supporting.items():
        (bundle / name).write_text(content, encoding="utf-8")
    generic_files = [
        {
            "path": "klines_1h.csv",
            "role": "klines_1h",
            "record_count": 4_800,
            "sample_start": first_open.isoformat().replace("+00:00", "Z"),
            "sample_end": (current - timedelta(hours=1)).isoformat().replace(
                "+00:00", "Z"
            ),
            "available_end": current.isoformat().replace("+00:00", "Z"),
            "interval": "1h",
            "sha256": hashlib.sha256(candle_path.read_bytes()).hexdigest(),
            "blockers": [],
            "pit_contract": {
                "present": True,
                "required": True,
                "missing_fields": [],
                "invalid_time_fields": [],
                "available_time_order_violation_count": 0,
                "blockers": [],
                "row_count_checked": 4_800,
            },
        }
    ]
    for name, role in (
        ("mark_price_klines_1h.csv", "mark_price_klines_1h"),
        ("premium_index_klines_1h.csv", "premium_index_klines_1h"),
        ("funding_rate.csv", "funding_rate"),
    ):
        path = bundle / name
        generic_files.append(
            {
                "path": name,
                "role": role,
                "record_count": 1,
                "sample_start": "2026-07-29T08:00:00Z",
                "sample_end": "2026-07-29T13:00:00Z",
                "available_end": "2026-07-29T13:00:00Z",
                "interval": "1h" if role != "funding_rate" else None,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "blockers": [],
                "pit_contract": {
                    "present": True,
                    "required": True,
                    "missing_fields": [],
                    "invalid_time_fields": [],
                    "available_time_order_violation_count": 0,
                    "blockers": [],
                    "row_count_checked": 1,
                },
            }
        )
    (bundle / "btc_perpetual_bundle_manifest.json").write_text(
        json.dumps(
            {
                "bundle_id": "generic-v1",
                "source_provider": "okx_swap",
                "source_type": "production",
                "exchange": "okx",
                "symbol": "BTCUSDT",
                "market_type": "usds_m_perpetual",
                "sample_start": first_open.isoformat().replace("+00:00", "Z"),
                "sample_end": current.isoformat().replace("+00:00", "Z"),
                "files": generic_files,
                "blockers": [
                    "btc_open_interest_history_not_verified_diagnostic_partial",
                    "btc_liquidation_snapshots_missing_diagnostic_only",
                ],
                "promotion_clean_allowed": False,
            }
        ),
        encoding="utf-8",
    )
    files, aggregate_hash, total_bytes = inventory_directory(bundle)
    shared_manifest = build_manifest(
        dataset_id="btc-okx-public-swap-research-bundle",
        dataset_version="generic-v1",
        readiness_class="quality_checked",
        quality_status="pass_with_research_only_warnings",
        files=files,
        aggregate_sha256=aggregate_hash,
        total_bytes=total_bytes,
        producer_commit="2" * 40,
        schema_name="btc_okx_public_swap_research_bundle_v1",
        known_gaps=("funding_history_limited_warning",),
    )
    (bundle / MANIFEST_NAME).write_text(
        json.dumps(shared_manifest, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        okx_demo_runtime_module,
        "load_manifest_from_git",
        lambda repo_root, git_spec: shared_manifest,
    )
    arguments = {
        "shared_manifest_git_spec": (
            f"{'2' * 40}:.agent/data_manifests/"
            "btc-okx-public-swap-research-bundle/generic-v1.json"
        ),
        "shared_data_root": shared_root,
        "expected_dataset_id": "btc-okx-public-swap-research-bundle",
    }

    readiness = inspect_okx_native_demo_signal_data(
        tmp_path,
        now=current,
        **arguments,
    )
    frame = load_completed_okx_native_hourly_frame(
        tmp_path,
        now=current,
        **arguments,
    )

    assert readiness["eligible"] is True
    assert readiness["integrity_passed"] is True
    assert readiness["layout_schema"] == "btc_okx_public_swap_research_bundle_v1"
    assert readiness["source_sha256"] == hashlib.sha256(
        candle_path.read_bytes()
    ).hexdigest()
    assert readiness["warnings"] == [
        "funding_history_limited_warning",
        "btc_open_interest_history_not_verified_diagnostic_partial",
        "btc_liquidation_snapshots_missing_diagnostic_only",
    ]
    assert readiness["validation"] == {
        "full_shared_data_hash_verified": True,
        "bundle_manifest_verified": True,
        "completed_1h_row_count": 4_800,
        "confirmed_only": True,
        "duplicate_count": 0,
        "gap_count": 0,
        "mark_price_present": True,
        "index_price_present": True,
        "funding_present": True,
    }
    assert readiness["bundle_dir"] == ""
    assert readiness["physical_root_redacted"] is True
    assert len(frame) == 4_800
    assert frame.index.is_unique
    assert str(shared_root) not in json.dumps(readiness)


def test_chart_rejects_manifest_mark_hash_mismatch(tmp_path: Path) -> None:
    database = tmp_path / "data" / "market_data.sqlite"
    database.parent.mkdir(parents=True)
    connection = sqlite3.connect(database)
    try:
        connection.execute(
            """
            CREATE TABLE market_klines (
                exchange TEXT, symbol TEXT, interval TEXT, open_time_ms INTEGER,
                open_time TEXT, open REAL, high REAL, low REAL, close REAL,
                volume REAL, quote_volume REAL, trade_count INTEGER
            )
            """
        )
        connection.commit()
    finally:
        connection.close()
    mark_path = tmp_path / "mark.csv"
    mark_path.write_text("timestamp,open_time_ms,open,high,low,close,volume\n", encoding="utf-8")
    data_manifest_path = tmp_path / "data_manifest.json"
    data_manifest_path.write_text(
        json.dumps({"execution_cost_proxy": {"mark_price_path": str(mark_path), "mark_price_sha256": "0" * 64}}),
        encoding="utf-8",
    )
    run_manifest_path = tmp_path / "run_manifest.json"
    run_manifest_path.write_text(json.dumps({"outputs": {"source_data_manifest": str(data_manifest_path)}}), encoding="utf-8")
    latest_path = tmp_path / "artifacts" / "btc_strategy_backtest_runs" / "latest_manifest.json"
    latest_path.parent.mkdir(parents=True)
    latest_path.write_text(json.dumps({"canonical_manifest": {"path": str(run_manifest_path)}}), encoding="utf-8")

    with pytest.raises(OkxDemoPaperRuntimeError, match="sha256_mismatch"):
        load_btc_chart_payload(repo_root=tmp_path, db_path=database, limit=10)


_S4_DYNAMIC_FRESH_IDENTITY = {
    "entry_cl_ord_id": "btcDP3a66f20f0003",
    "entry_ord_id": "3826277010441474048",
    "entry_fill_id": "4327176102",
    "oco_algo_cl_ord_id": "btcDP3a66f20f0003A",
    "oco_algo_id": "3826277010452819968",
}


def _fresh_operator_payload(**overrides: Any) -> dict[str, Any]:
    payload = {
        "operator_action": "fresh_state_emergency_reduce_only_exit",
        "confirmation_text": OKX_DEMO_PAPER_CONFIRMATION,
        "expected_environment": "OKX Demo",
        "expected_instrument_id": "BTC-USDT-SWAP",
        "expected_margin_mode": "isolated",
        "expected_position_side": "long",
        "expected_entry_cl_ord_id": "btcDP20a8d1650001",
        "expected_entry_ord_id": "3816659792351170560",
        "expected_oco_algo_cl_ord_id": "btcDP20a8d1650001A",
        "expected_oco_algo_id": "3816659794069377024",
        "expected_position_contracts": "0.01",
        "max_position_contracts": "0.01",
    }
    payload.update(overrides)
    return payload


class FreshEmergencyWS:
    def __init__(self) -> None:
        self.stopped = False
        self.reconcile_calls = 0
        self.monitoring_started = False

    def start_monitoring(self) -> None:
        self.monitoring_started = True

    def reconcile_current(self) -> dict[str, Any]:
        self.reconcile_calls += 1
        return {
            "connected": True,
            "listener_alive": True,
            "reconnect_login_observed": True,
            "reconnect_resubscribed": True,
            "reconnect_rest_reconciled": True,
            "opening_allowed_after_reconciliation": True,
            "source_head": _repo_head_for_test(),
            "blockers": [],
        }

    def run_startup_reconnect_probe(self) -> dict[str, Any]:
        return {
            "source_head": _repo_head_for_test(),
            "runtime_version": "test",
            "environment": "OKX Demo",
            "instrument_id": "BTC-USDT-SWAP",
            "startup_reconciled": True,
            "disconnect_cancel_only_observed": True,
            "reconnect_login_observed": True,
            "reconnect_resubscribed": True,
            "reconnect_rest_reconciled": True,
            "opening_allowed_after_reconciliation": True,
            "subscribed_channels": [
                "account",
                "orders",
                "orders-algo",
                "positions",
            ],
            "blockers": [],
            "credentials_redacted": True,
            "promotion_evidence_ready": False,
            "paper_allowed": False,
            "live_allowed": False,
        }

    def status(self) -> dict[str, Any]:
        if self.stopped:
            return {
                "connected": False,
                "listener_alive": False,
                "reconnect_login_observed": True,
                "reconnect_resubscribed": True,
                "reconnect_rest_reconciled": True,
                "opening_allowed_after_reconciliation": False,
                "blockers": [],
            }
        return self.reconcile_current()

    def stop(self) -> dict[str, Any]:
        self.stopped = True
        return {"listener_joined": True}


class FreshEmergencyClient:
    def __init__(
        self,
        *,
        clock: Any,
        partial: bool = False,
        response_lost: bool = False,
        algo_id: str = "3816659794069377024",
    ) -> None:
        self.clock = clock
        self.partial = partial
        self.response_lost = response_lost
        self.algo_id = algo_id
        self.submit_calls: list[dict[str, Any]] = []
        self.private_calls: list[dict[str, Any]] = []
        self.cancel_algo_calls: list[Any] = []
        self.dead_man_calls: list[dict[str, Any]] = []
        self.algo_cancelled = False
        self.snapshot_calls = 0
        self.snapshot_loader: Any = None

    def submit_order(self, payload: Mapping[str, Any]) -> OkxDemoResponse:
        self.submit_calls.append(dict(payload))
        if self.response_lost:
            raise OkxDemoTransportError("fresh_emergency_response_lost")
        return OkxDemoResponse(
            method="POST",
            path="/api/v5/trade/order",
            http_status=200,
            code="0",
            message="",
            data=(
                {
                    "ordId": "fresh-close-order",
                    "clOrdId": payload["clOrdId"],
                    "sCode": "0",
                    "sMsg": "",
                },
            ),
        )

    def cancel_algo_orders(self, payload: Any) -> OkxDemoResponse:
        self.cancel_algo_calls.append(payload)
        self.algo_cancelled = True
        return OkxDemoResponse(
            method="POST",
            path="/api/v5/trade/cancel-algos",
            http_status=200,
            code="0",
            message="",
            data=tuple(
                {"algoId": str(row.get("algoId") or ""), "sCode": "0"}
                for row in payload
            ),
        )

    def cancel_all_after(self, **payload: Any) -> OkxDemoResponse:
        self.dead_man_calls.append(dict(payload))
        timeout = int(payload["timeout_seconds"])
        return OkxDemoResponse(
            method="POST",
            path="/api/v5/trade/cancel-all-after",
            http_status=200,
            code="0",
            message="",
            data=(
                {
                    "triggerTime": "0" if timeout == 0 else "2",
                    "tag": payload["tag"],
                    "ts": "1",
                },
            ),
        )

    def private_get(
        self,
        path: str,
        params: Mapping[str, Any] | None = None,
    ) -> OkxDemoResponse:
        query = dict(params or {})
        self.private_calls.append({"path": path, "params": query})
        if path == "/api/v5/trade/order":
            cl_ord_id = str(query.get("clOrdId") or "")
            return OkxDemoResponse(
                method="GET",
                path=path,
                http_status=200,
                code="0",
                message="",
                data=(
                    {
                        "ordId": "fresh-close-order",
                        "clOrdId": cl_ord_id,
                        "instId": "BTC-USDT-SWAP",
                        "side": "sell",
                        "posSide": "long",
                        "ordType": "ioc",
                        "px": str(self.submit_calls[-1].get("px") or "50000"),
                        "sz": "0.01",
                        "tag": "btcP0Demo",
                        "state": "filled",
                        "accFillSz": "0.005" if self.partial else "0.01",
                        "avgPx": "60000",
                    },
                ),
            )
        if path == "/api/v5/trade/fills":
            cl_ord_id = str(
                self.submit_calls[-1].get("clOrdId") if self.submit_calls else ""
            )
            return OkxDemoResponse(
                method="GET",
                path=path,
                http_status=200,
                code="0",
                message="",
                data=(
                    {
                        "tradeId": "fresh-close-fill",
                        "ordId": "fresh-close-order",
                        "clOrdId": cl_ord_id,
                        "instId": "BTC-USDT-SWAP",
                        "side": "sell",
                        "posSide": "long",
                        "fillPx": "60000",
                        "fillSz": "0.005" if self.partial else "0.01",
                        "fee": "0",
                        "feeCcy": "USDT",
                        "ts": "1",
                    },
                ),
            )
        if path in {
            "/api/v5/trade/orders-pending",
            "/api/v5/trade/orders-history",
            "/api/v5/account/positions",
        }:
            return OkxDemoResponse(
                method="GET",
                path=path,
                http_status=200,
                code="0",
                message="",
                data=(),
            )
        if path == "/api/v5/trade/orders-algo-pending":
            return OkxDemoResponse(
                method="GET",
                path=path,
                http_status=200,
                code="0",
                message="",
                data=(),
            )
        if path == "/api/v5/trade/orders-algo-history":
            return OkxDemoResponse(
                method="GET",
                path=path,
                http_status=200,
                code="0",
                message="",
                data=({"algoId": self.algo_id, "state": "canceled"},),
            )
        raise AssertionError(path)


def _fresh_emergency_snapshot(
    clock: Any,
    *,
    nonflat: bool = True,
    foreign_algo: bool = False,
    partial: bool = False,
    algo_present: bool = True,
    empty_parent: bool = False,
    identity: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    identity = dict(identity or {})
    entry_cl_ord_id = str(identity.get("entry_cl_ord_id") or "btcDP20a8d1650001")
    entry_ord_id = str(identity.get("entry_ord_id") or "3816659792351170560")
    entry_fill_id = str(identity.get("entry_fill_id") or "entry-fill-20a8d1650001")
    oco_algo_cl_ord_id = str(
        identity.get("oco_algo_cl_ord_id") or "btcDP20a8d1650001A"
    )
    oco_algo_id = str(identity.get("oco_algo_id") or "3816659794069377024")
    quantity = "0.005" if partial and nonflat else "0.01" if nonflat else "0"
    positions = (
        [
            {
                "instrument_id": "BTC-USDT-SWAP",
                "position_side": "long",
                "margin_mode": "isolated",
                "contracts": quantity,
                "liquidation_price": "50000",
            }
        ]
        if nonflat
        else []
    )
    algos = (
        [
            {
                "algo_id": "foreign-algo" if foreign_algo else oco_algo_id,
                "algo_client_order_id": "foreign-protect"
                if foreign_algo
                else oco_algo_cl_ord_id,
                "parent_client_order_id": (
                    "foreign-parent"
                    if foreign_algo
                    else ""
                    if empty_parent
                    else entry_cl_ord_id
                ),
                "instrument_id": "BTC-USDT-SWAP",
                "position_side": "long",
                "size": "0.01",
                "order_type": "oco",
                "state": "live",
                "take_profit_order_price": "-1",
                "stop_loss_order_price": "-1",
            }
        ]
        if nonflat and algo_present
        else []
    )
    now_ms = str(int(clock().timestamp() * 1000))
    return {
        "captured_at_utc": clock().isoformat(),
        "account": {
            "account_level": "2",
            "position_mode": "long_short_mode",
            "permissions": ["read_only", "trade"],
            "withdraw_permission_present": False,
        },
        "balance": {"equity_usdt": "5000"},
        "positions": positions,
        "pending_orders": [],
        "pending_algo_orders": algos,
        "orders": [
            {
                "order_id": entry_ord_id,
                "client_order_id": entry_cl_ord_id,
                "instrument_id": "BTC-USDT-SWAP",
                "side": "buy",
                "position_side": "long",
                "state": "filled",
                "price": "60000",
                "size": "0.01",
                "filled_size": "0.01",
                "tag": "btcP0Demo",
            }
        ],
        "fills": [
            {
                "fill_id": entry_fill_id,
                "order_id": entry_ord_id,
                "client_order_id": entry_cl_ord_id,
                "instrument_id": "BTC-USDT-SWAP",
                "side": "buy",
                "position_side": "long",
                "price": "60000",
                "size": "0.01",
            }
        ],
        "bills": [],
        "fee_schedule": {"taker_rate": "-0.0005"},
        "leverage": [
            {
                "instrument_id": "BTC-USDT-SWAP",
                "position_side": "long",
                "margin_mode": "isolated",
                "leverage": "3",
            },
            {
                "instrument_id": "BTC-USDT-SWAP",
                "position_side": "short",
                "margin_mode": "isolated",
                "leverage": "3",
            },
        ],
        "instrument": {
            "instrument_id": "BTC-USDT-SWAP",
            "state": "live",
            "contract_value_btc": "0.01",
            "tick_size": "0.1",
            "lot_size": "0.01",
            "minimum_size": "0.01",
        },
        "ticker": {"bid": "60000", "ask": "60000.1"},
        "mark": {"mark_price": "60000", "timestamp_ms": now_ms},
        "index": {"index_price": "60000", "timestamp_ms": now_ms},
        "price_limit": {"buy": "70000", "sell": "50000"},
        "book": {
            "bids": [["60000", "1"]],
            "asks": [["60000.1", "1"]],
            "timestamp_ms": now_ms,
        },
        "funding": {"funding_rate": "0.0001"},
        "server_time_ms": now_ms,
    }


def _fresh_emergency_controller(
    tmp_path: Path,
    *,
    partial: bool = False,
    response_lost: bool = False,
    foreign_algo: bool = False,
    algo_present: bool = True,
    bootstrap: bool = False,
    empty_parent: bool = False,
    identity: Mapping[str, str] | None = None,
    owned_algo_id: str | None = None,
    owned_algo_status: str = "active",
) -> tuple[OkxDemoPaperRuntimeController, FreshEmergencyClient, FreshEmergencyWS]:
    fixed_now = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)
    clock = lambda: fixed_now
    controller = OkxDemoPaperRuntimeController(
        config=OkxDemoPaperRuntimeConfig(
            repo_root=Path.cwd(),
            data_db_path=tmp_path / "unused.sqlite",
            output_dir=tmp_path / "output" / "btc_demo_paper_runtime",
            order_poll_interval_seconds=0.001,
            order_poll_attempts=1,
            authoritative_oms_bundle_provider=_test_authoritative_oms_bundle_provider,
        ),
        credential_loader=lambda _: _credentials(),
        clock=clock,
        start_worker=False,
    )
    identity = dict(identity or {})
    entry_cl_ord_id = str(identity.get("entry_cl_ord_id") or "btcDP20a8d1650001")
    entry_ord_id = str(identity.get("entry_ord_id") or "3816659792351170560")
    oco_algo_cl_ord_id = str(
        identity.get("oco_algo_cl_ord_id") or "btcDP20a8d1650001A"
    )
    oco_algo_id = str(identity.get("oco_algo_id") or "3816659794069377024")
    client = FreshEmergencyClient(
        clock=clock,
        partial=partial,
        response_lost=response_lost,
        algo_id=oco_algo_id,
    )
    private_ws = FreshEmergencyWS()
    controller._client = client  # type: ignore[assignment]
    controller._private_ws = private_ws
    controller._state["runtime"].update(
        {
            "run_id": "fresh-run-0001",
            "active": False,
            "opening_allowed": False,
            "cancel_only": True,
            "status": "blocked_fail_closed",
        }
    )
    controller._state["risk_control"].update(
        {"mode": "FROZEN_UNKNOWN", "write_path_trusted": False}
    )
    controller._state["risk_control"]["pending_order_intents"] = {
        entry_cl_ord_id: {
            "client_order_id": entry_cl_ord_id,
            "status": "terminal",
            "risk_reducing_only": False,
            "action": "open_long",
        }
    }
    controller._state["risk_control"]["owned_attached_algos"] = {
        oco_algo_cl_ord_id: {
            "algo_id": oco_algo_id if owned_algo_id is None else owned_algo_id,
            "algo_client_order_id": oco_algo_cl_ord_id,
            "parent_client_order_id": entry_cl_ord_id,
            "instrument_id": "BTC-USDT-SWAP",
            "opening_intent": True,
            "status": owned_algo_status,
        }
    }
    snapshots = [
        _fresh_emergency_snapshot(
            clock,
            nonflat=True,
            foreign_algo=foreign_algo,
            partial=False,
            algo_present=algo_present,
            empty_parent=empty_parent,
            identity=identity,
        ),
        _fresh_emergency_snapshot(
            clock,
            nonflat=partial,
            partial=partial,
            algo_present=algo_present and not foreign_algo,
            empty_parent=empty_parent,
            identity=identity,
        ),
    ]
    if bootstrap:
        snapshots.insert(
            1,
            _fresh_emergency_snapshot(
                clock,
                nonflat=True,
                foreign_algo=foreign_algo,
                partial=False,
                algo_present=algo_present,
                empty_parent=empty_parent,
                identity=identity,
            ),
        )
        snapshots[2]["pending_algo_orders"] = json.loads(
            json.dumps(snapshots[0]["pending_algo_orders"])
        )
    calls = {"count": 0}

    def collect(_client: Any) -> dict[str, Any]:
        calls["count"] += 1
        if calls["count"] == 1:
            return json.loads(json.dumps(snapshots[0]))
        if calls["count"] == 2:
            return json.loads(json.dumps(snapshots[1]))
        if client.algo_cancelled:
            row = json.loads(
                json.dumps(snapshots[2] if bootstrap else snapshots[1])
            )
            row["pending_algo_orders"] = []
            return row
        if bootstrap and calls["count"] >= 3:
            return json.loads(json.dumps(snapshots[2]))
        row = json.loads(json.dumps(snapshots[1]))
        if snapshots[0]["pending_algo_orders"]:
            row["pending_algo_orders"] = json.loads(
                json.dumps(snapshots[0]["pending_algo_orders"])
            )
        return row

    controller._collect_exchange_snapshot = collect  # type: ignore[method-assign]

    def commit(*, snapshot: Mapping[str, Any], trigger: str, order_record: Any = None) -> None:
        del snapshot, order_record
        controller._state["ledger_reconciliation"] = {
            "status": "reconciled",
            "trigger": trigger,
            "current_state_exchange_snapshot_match": True,
            "funding_cashflow_reconciled": True,
        }

    controller._commit_ledger_reconciliation = commit  # type: ignore[method-assign]
    return controller, client, private_ws


def _write_owner_marker_for_liveness(
    controller: OkxDemoPaperRuntimeController,
    *,
    process_id: int = 32532,
) -> Path:
    root = Path(controller.config.output_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    lock_path = root / ".btc_okx_demo_fault_drill_writer.lock"
    marker = {
        "nonce": "dead-pid-probe",
        "process_id": process_id,
        "source_head": "a" * 40,
        "runtime_root_sha256": okx_demo_runtime_module._canonical_sha256(str(root)),
    }
    lock_path.write_bytes(
        json.dumps(marker, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    return lock_path


def _write_owner_marker_with_process_identity(
    controller: OkxDemoPaperRuntimeController,
    *,
    process_id: int = 43210,
    process_create_time: str = "111",
) -> Path:
    root = Path(controller.config.output_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    lock_path = root / ".btc_okx_demo_fault_drill_writer.lock"
    marker = {
        "nonce": "pid-reuse-probe",
        "process_id": process_id,
        "process_create_time": process_create_time,
        "source_head": "a" * 40,
        "runtime_root_sha256": okx_demo_runtime_module._canonical_sha256(
            str(root)
        ),
    }
    lock_path.write_bytes(
        json.dumps(marker, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    return lock_path


@pytest.mark.skipif(os.name != "nt", reason="Windows PID liveness contract")
@pytest.mark.parametrize(
    ("second_probe", "expected_error"),
    [
        (False, None),
        (True, "okx_demo_fresh_state_owner_marker_active"),
        (None, "okx_demo_fresh_state_owner_marker_liveness_unknown"),
    ],
)
def test_fresh_state_owner_marker_winerror87_requires_canonical_second_probe(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    second_probe: bool | None,
    expected_error: str | None,
) -> None:
    credential_calls: list[str] = []
    controller = _controller(tmp_path, credential_calls.append)
    _write_owner_marker_for_liveness(controller)

    def raise_winerror87(_process_id: int, _sig: int) -> None:
        error = OSError(22, "invalid argument")
        error.winerror = 87
        raise error

    monkeypatch.setattr(okx_demo_runtime_module.os, "kill", raise_winerror87)
    monkeypatch.setattr(
        okx_demo_runtime_module,
        "_canonical_windows_process_liveness",
        lambda _process_id: second_probe,
        raising=False,
    )

    if expected_error is None:
        audit = controller._fresh_state_emergency_owner_marker_preflight()
        assert audit["stale"] is True
    else:
        with pytest.raises(OkxDemoPaperRuntimeError, match=expected_error):
            controller._fresh_state_emergency_owner_marker_preflight()
    assert credential_calls == []
    assert controller._client is None
    assert controller._private_ws is None
    assert controller._state["risk_control"]["pending_order_intents"] == {}


def test_fresh_state_owner_marker_process_lookup_error_remains_stale(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    controller = _controller(tmp_path, lambda _: _credentials())
    _write_owner_marker_for_liveness(controller)

    def raise_process_lookup(_process_id: int, _sig: int) -> None:
        raise ProcessLookupError()

    monkeypatch.setattr(okx_demo_runtime_module.os, "kill", raise_process_lookup)
    monkeypatch.setattr(
        okx_demo_runtime_module,
        "_canonical_windows_process_liveness",
        lambda _process_id: (_ for _ in ()).throw(
            AssertionError("second probe is not used for ProcessLookupError")
        ),
        raising=False,
    )

    audit = controller._fresh_state_emergency_owner_marker_preflight()
    assert audit["stale"] is True
    assert controller._client is None
    assert controller._private_ws is None
    assert controller._state["risk_control"]["pending_order_intents"] == {}


@pytest.mark.skipif(os.name != "nt", reason="Windows PID reuse identity contract")
def test_fresh_state_owner_marker_pid_reuse_birth_mismatch_is_stale(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    controller = _controller(tmp_path, lambda _: _credentials())
    _write_owner_marker_with_process_identity(controller)
    monkeypatch.setattr(
        okx_demo_runtime_module.os,
        "kill",
        lambda _process_id, _sig: None,
    )
    monkeypatch.setattr(
        okx_demo_runtime_module,
        "_canonical_windows_process_liveness",
        lambda _process_id: True,
        raising=False,
    )
    monkeypatch.setattr(
        okx_demo_runtime_module,
        "_canonical_windows_process_create_time",
        lambda _process_id: "222",
        raising=False,
    )

    audit = controller._fresh_state_emergency_owner_marker_preflight()

    assert audit["stale"] is True
    assert controller._client is None
    assert controller._private_ws is None


@pytest.mark.skipif(os.name != "nt", reason="Windows PID reuse identity contract")
def test_fresh_state_owner_marker_matching_birth_identity_remains_active(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    controller = _controller(tmp_path, lambda _: _credentials())
    _write_owner_marker_with_process_identity(controller)
    monkeypatch.setattr(
        okx_demo_runtime_module.os,
        "kill",
        lambda _process_id, _sig: None,
    )
    monkeypatch.setattr(
        okx_demo_runtime_module,
        "_canonical_windows_process_liveness",
        lambda _process_id: True,
        raising=False,
    )
    monkeypatch.setattr(
        okx_demo_runtime_module,
        "_canonical_windows_process_create_time",
        lambda _process_id: "111",
        raising=False,
    )

    with pytest.raises(
        OkxDemoPaperRuntimeError,
        match="okx_demo_fresh_state_owner_marker_active",
    ):
        controller._fresh_state_emergency_owner_marker_preflight()

    assert controller._client is None
    assert controller._private_ws is None


@pytest.mark.skipif(os.name != "nt", reason="Windows PID reuse identity contract")
def test_fresh_state_owner_marker_birth_identity_unknown_remains_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    controller = _controller(tmp_path, lambda _: _credentials())
    _write_owner_marker_with_process_identity(controller)
    monkeypatch.setattr(
        okx_demo_runtime_module.os,
        "kill",
        lambda _process_id, _sig: None,
    )
    monkeypatch.setattr(
        okx_demo_runtime_module,
        "_canonical_windows_process_liveness",
        lambda _process_id: True,
        raising=False,
    )
    monkeypatch.setattr(
        okx_demo_runtime_module,
        "_canonical_windows_process_create_time",
        lambda _process_id: None,
        raising=False,
    )

    with pytest.raises(
        OkxDemoPaperRuntimeError,
        match="okx_demo_fresh_state_owner_marker_liveness_unknown",
    ):
        controller._fresh_state_emergency_owner_marker_preflight()

    assert controller._client is None
    assert controller._private_ws is None


@pytest.mark.skipif(os.name != "nt", reason="Windows PID reuse identity contract")
def test_fresh_state_owner_marker_identity_match_ignores_source_head_drift(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    controller = _controller(tmp_path, lambda _: _credentials())
    _write_owner_marker_with_process_identity(controller)
    monkeypatch.setattr(
        okx_demo_runtime_module.os,
        "kill",
        lambda _process_id, _sig: None,
    )
    monkeypatch.setattr(
        okx_demo_runtime_module,
        "_canonical_windows_process_liveness",
        lambda _process_id: True,
        raising=False,
    )
    monkeypatch.setattr(
        okx_demo_runtime_module,
        "_canonical_windows_process_create_time",
        lambda _process_id: "111",
        raising=False,
    )

    with pytest.raises(
        OkxDemoPaperRuntimeError,
        match="okx_demo_fresh_state_owner_marker_active",
    ):
        controller._fresh_state_emergency_owner_marker_preflight()


def test_fresh_state_emergency_exit_happy_path_is_one_shot_and_flat(
    tmp_path: Path,
) -> None:
    controller, client, private_ws = _fresh_emergency_controller(tmp_path)

    result = controller.emergency_reduce_only_exit(_fresh_operator_payload())

    assert result["orders_posted"] == 1
    assert result["final_flat"] is True
    assert result["private_ws_stopped"] is True
    assert result["ledger_reconciled"] is True
    assert len(client.submit_calls) == 1


def test_fresh_state_emergency_exit_accepts_empty_parent_with_fixed_identity_binding(
    tmp_path: Path,
) -> None:
    controller, client, _ = _fresh_emergency_controller(
        tmp_path,
        empty_parent=True,
    )

    result = controller.emergency_reduce_only_exit(_fresh_operator_payload())

    assert result["orders_posted"] == 1
    assert result["final_flat"] is True
    assert len(client.submit_calls) == 1
    projection = controller.status()["runtime"]["fresh_state_emergency_exit"][
        "projection"
    ]
    assert projection["oco_ownership_proof"]["parent_binding"] == (
        "current_main_fixed_incident_identity_projection"
    )
    entry_proof = projection["oco_ownership_proof"]["entry"]
    assert entry_proof["order_id"] == "3816659792351170560"
    assert "exchange_order_id" not in entry_proof
    assert projection["oco_ownership_proof"]["identity_digest_sha256"]
    assert any(
        event.get("event_type") == "fresh_state_emergency_identity_projection_bound"
        and event.get("payload", {}).get("identity_digest_sha256")
        for event in controller.status()["events"]
    )


def test_fresh_state_emergency_exit_accepts_s4_dynamic_parentless_owned_proof(
    tmp_path: Path,
) -> None:
    """A current S4 identity is proved by fresh truth plus its durable owner."""

    controller, client, _ = _fresh_emergency_controller(
        tmp_path,
        empty_parent=True,
        identity=_S4_DYNAMIC_FRESH_IDENTITY,
        owned_algo_id="",
        owned_algo_status="submit_pending",
    )
    payload = _fresh_operator_payload(
        expected_entry_cl_ord_id=_S4_DYNAMIC_FRESH_IDENTITY["entry_cl_ord_id"],
        expected_entry_ord_id=_S4_DYNAMIC_FRESH_IDENTITY["entry_ord_id"],
        expected_oco_algo_cl_ord_id=_S4_DYNAMIC_FRESH_IDENTITY[
            "oco_algo_cl_ord_id"
        ],
        expected_oco_algo_id=_S4_DYNAMIC_FRESH_IDENTITY["oco_algo_id"],
    )

    result = controller.emergency_reduce_only_exit(payload)

    assert result["orders_posted"] == 1
    assert result["final_flat"] is True
    assert len(client.submit_calls) == 1
    projection = controller.status()["runtime"]["fresh_state_emergency_exit"][
        "projection"
    ]
    proof = projection["oco_ownership_proof"]
    assert proof["schema_version"] == "okx_demo_fresh_state_oco_ownership_proof_v2"
    assert proof["binding_source"] == "fresh_state_dynamic_identity_projection"
    assert proof["parent_binding"] == "durable_owned_attached_algo"
    assert proof["entry"]["client_order_id"] == _S4_DYNAMIC_FRESH_IDENTITY[
        "entry_cl_ord_id"
    ]
    assert proof["oco"]["algo_id"] == _S4_DYNAMIC_FRESH_IDENTITY["oco_algo_id"]
    assert client.cancel_algo_calls


@pytest.mark.parametrize(
    ("payload_mutation", "state_mutation", "snapshot_mutation"),
    [
        (
            {"expected_oco_algo_cl_ord_id": "btcDP3a66f20f0003B"},
            None,
            None,
        ),
        (
            {"expected_entry_cl_ord_id": "btcDP3A66F20F0003"},
            None,
            None,
        ),
        (
            {"expected_entry_ord_id": "not-numeric"},
            None,
            None,
        ),
        (
            None,
            lambda controller: controller._state["risk_control"][
                "owned_attached_algos"
            ].clear(),
            None,
        ),
        (
            None,
            lambda controller: controller._state["risk_control"][
                "owned_attached_algos"
            ]["btcDP3a66f20f0003A"].update(
                {"parent_client_order_id": "wrong-parent"}
            ),
            None,
        ),
        (
            None,
            lambda controller: controller._state["risk_control"][
                "owned_attached_algos"
            ]["btcDP3a66f20f0003A"].update({"algo_id": "999999999999"}),
            None,
        ),
        (
            None,
            lambda controller: controller._state["risk_control"][
                "owned_attached_algos"
            ]["btcDP3a66f20f0003A"].update({"status": "rejected"}),
            None,
        ),
        (
            None,
            lambda controller: controller._state["risk_control"][
                "owned_attached_algos"
            ]["btcDP3a66f20f0003A"].update({"opening_intent": False}),
            None,
        ),
        (
            None,
            None,
            lambda snapshot: snapshot["pending_algo_orders"].append(
                dict(snapshot["pending_algo_orders"][0])
            ),
        ),
        (
            None,
            None,
            lambda snapshot: snapshot["pending_algo_orders"][0].update(
                {"algo_client_order_id": "btcDPffffffff0003A"}
            ),
        ),
        (
            None,
            None,
            lambda snapshot: snapshot["orders"][0].update(
                {"order_id": "3826277010441474000"}
            ),
        ),
    ],
)
def test_fresh_state_emergency_exit_dynamic_s4_identity_mutations_are_zero_post(
    tmp_path: Path,
    payload_mutation: Mapping[str, Any] | None,
    state_mutation: Callable[[OkxDemoPaperRuntimeController], None] | None,
    snapshot_mutation: Callable[[dict[str, Any]], None] | None,
) -> None:
    controller, client, _ = _fresh_emergency_controller(
        tmp_path,
        empty_parent=True,
        identity=_S4_DYNAMIC_FRESH_IDENTITY,
        owned_algo_id="",
        owned_algo_status="submit_pending",
    )
    payload = _fresh_operator_payload(
        expected_entry_cl_ord_id=_S4_DYNAMIC_FRESH_IDENTITY["entry_cl_ord_id"],
        expected_entry_ord_id=_S4_DYNAMIC_FRESH_IDENTITY["entry_ord_id"],
        expected_oco_algo_cl_ord_id=_S4_DYNAMIC_FRESH_IDENTITY[
            "oco_algo_cl_ord_id"
        ],
        expected_oco_algo_id=_S4_DYNAMIC_FRESH_IDENTITY["oco_algo_id"],
    )
    if payload_mutation:
        payload.update(payload_mutation)
    if state_mutation:
        state_mutation(controller)
    if snapshot_mutation:
        original_collect = controller._collect_exchange_snapshot
        applied = False

        def collect(client_value: Any) -> dict[str, Any]:
            nonlocal applied
            snapshot = original_collect(client_value)
            if not applied:
                snapshot_mutation(snapshot)
                applied = True
            return snapshot

        controller._collect_exchange_snapshot = collect  # type: ignore[method-assign]

    with pytest.raises(OkxDemoPaperRuntimeError):
        controller.emergency_reduce_only_exit(payload)

    assert client.submit_calls == []
    assert client.cancel_algo_calls == []


@pytest.mark.parametrize(
    "mutation",
    [
        lambda snapshot: snapshot["orders"].clear(),
        lambda snapshot: snapshot["orders"][0].update(
            {"client_order_id": "foreign-entry"}
        ),
        lambda snapshot: snapshot["orders"][0].update(
            {"order_id": "wrong-entry-order"}
        ),
        lambda snapshot: snapshot["orders"][0].pop("order_id"),
        lambda snapshot: snapshot["fills"].clear(),
        lambda snapshot: snapshot["fills"][0].update(
            {"order_id": "wrong-entry-order"}
        ),
        lambda snapshot: snapshot["orders"][0].update(
            {"size": "0.02"}
        ),
        lambda snapshot: snapshot["orders"][0].update(
            {"instrument_id": "ETH-USDT-SWAP"}
        ),
        lambda snapshot: snapshot["orders"][0].update({"side": "sell"}),
        lambda snapshot: snapshot["pending_algo_orders"][0].update(
            {"algo_id": "foreign-algo"}
        ),
        lambda snapshot: snapshot["pending_algo_orders"][0].update(
            {"size": "0.02"}
        ),
        lambda snapshot: snapshot["pending_algo_orders"][0].update(
            {"instrument_id": "ETH-USDT-SWAP"}
        ),
        lambda snapshot: snapshot["pending_algo_orders"][0].update(
            {"position_side": "short"}
        ),
        lambda snapshot: snapshot["pending_algo_orders"][0].update(
            {"order_type": "trigger"}
        ),
        lambda snapshot: snapshot["pending_algo_orders"][0].update(
            {"state": "canceled"}
        ),
        lambda snapshot: snapshot["pending_algo_orders"].append(
            dict(snapshot["pending_algo_orders"][0])
        ),
        lambda snapshot: snapshot["positions"].append(
            dict(snapshot["positions"][0])
        ),
        lambda snapshot: snapshot["pending_algo_orders"][0].update(
            {"parent_client_order_id": "wrong-parent"}
        ),
    ],
)
def test_fresh_state_emergency_exit_oco_identity_mutations_are_zero_post(
    tmp_path: Path,
    mutation: Any,
) -> None:
    controller, client, _ = _fresh_emergency_controller(tmp_path)
    original_collect = controller._collect_exchange_snapshot
    applied = False

    def collect(client_value: Any) -> dict[str, Any]:
        nonlocal applied
        snapshot = original_collect(client_value)
        if not applied:
            mutation(snapshot)
            applied = True
        return snapshot

    controller._collect_exchange_snapshot = collect  # type: ignore[method-assign]

    with pytest.raises(OkxDemoPaperRuntimeError):
        controller.emergency_reduce_only_exit(_fresh_operator_payload())

    assert client.submit_calls == []
    assert client.cancel_algo_calls == []


def test_fresh_state_emergency_exit_empty_parent_requires_fixed_owner_binding(
    tmp_path: Path,
) -> None:
    controller, client, _ = _fresh_emergency_controller(
        tmp_path,
        empty_parent=True,
    )
    controller._state["risk_control"]["owned_attached_algos"][
        "btcDP20a8d1650001A"
    ]["parent_client_order_id"] = "wrong-parent"

    with pytest.raises(
        OkxDemoPaperRuntimeError,
        match="(foreign_algo_present|oco_parent_binding_mismatch)",
    ):
        controller.emergency_reduce_only_exit(_fresh_operator_payload())

    assert client.submit_calls == []
    assert client.cancel_algo_calls == []


def test_fresh_state_emergency_exit_empty_parent_without_owner_map_uses_fixed_projection(
    tmp_path: Path,
) -> None:
    controller, client, _ = _fresh_emergency_controller(
        tmp_path,
        empty_parent=True,
    )
    controller._state["risk_control"]["owned_attached_algos"] = {}

    result = controller.emergency_reduce_only_exit(_fresh_operator_payload())

    assert result["orders_posted"] == 1
    assert result["final_flat"] is True
    assert len(client.submit_calls) == 1
    proof = controller.status()["runtime"]["fresh_state_emergency_exit"][
        "projection"
    ]["oco_ownership_proof"]
    assert proof["binding_source"] == (
        "current_main_fixed_incident_identity_projection"
    )
    assert proof["parent_binding"] == (
        "current_main_fixed_incident_identity_projection"
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("parent_client_order_id", "wrong-parent"),
        ("algo_id", "wrong-algo-id"),
        ("algo_client_order_id", "wrong-algo-client-id"),
        ("status", "closed"),
    ],
)
def test_fresh_state_emergency_exit_empty_parent_conflicting_owner_map_is_zero_post(
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    controller, client, _ = _fresh_emergency_controller(
        tmp_path,
        empty_parent=True,
    )
    controller._state["risk_control"]["owned_attached_algos"][
        "btcDP20a8d1650001A"
    ][field] = value

    with pytest.raises(OkxDemoPaperRuntimeError):
        controller.emergency_reduce_only_exit(_fresh_operator_payload())

    assert client.submit_calls == []
    assert client.cancel_algo_calls == []


def test_fresh_state_emergency_exit_requires_current_ledger_before_dead_man_or_post(
    tmp_path: Path,
) -> None:
    controller, client, _ = _fresh_emergency_controller(tmp_path)

    def commit(*, snapshot: Mapping[str, Any], trigger: str, order_record: Any = None) -> None:
        del snapshot, trigger, order_record
        controller._state["ledger_reconciliation"] = {
            "status": "blocked",
            "current_state_exchange_snapshot_match": False,
            "funding_cashflow_reconciled": False,
        }

    controller._commit_ledger_reconciliation = commit  # type: ignore[method-assign]

    with pytest.raises(
        OkxDemoPaperRuntimeError,
        match="fresh_state_ledger_not_current",
    ):
        controller.emergency_reduce_only_exit(_fresh_operator_payload())

    assert client.dead_man_calls == []
    assert client.submit_calls == []
    assert client.cancel_algo_calls == []


def test_fresh_state_emergency_exit_requires_current_private_ws_before_dead_man_or_post(
    tmp_path: Path,
) -> None:
    controller, client, private_ws = _fresh_emergency_controller(tmp_path)

    def stale_reconcile() -> dict[str, Any]:
        return {
            "connected": False,
            "listener_alive": False,
            "reconnect_login_observed": True,
            "reconnect_resubscribed": True,
            "reconnect_rest_reconciled": True,
            "opening_allowed_after_reconciliation": False,
            "source_head": _repo_head_for_test(),
            "blockers": ["stale"],
        }

    private_ws.reconcile_current = stale_reconcile  # type: ignore[method-assign]

    with pytest.raises(
        OkxDemoPaperRuntimeError,
        match="private_ws_not_current",
    ):
        controller.emergency_reduce_only_exit(_fresh_operator_payload())

    assert client.dead_man_calls == []
    assert client.submit_calls == []
    assert client.cancel_algo_calls == []


def test_fresh_state_emergency_exit_bootstraps_stopped_missing_client_and_ws(
    tmp_path: Path,
) -> None:
    controller, client, private_ws = _fresh_emergency_controller(
        tmp_path,
        bootstrap=True,
    )
    controller._client = None
    controller._private_ws = None
    created: list[Any] = []

    def load_credentials(service: str) -> Any:
        assert service == "quant-system.okx-demo.trade"
        return _credentials()

    def build_client(config: Any, credentials: Any) -> Any:
        created.append(config)
        assert credentials == _credentials()
        return client

    controller._credential_loader = load_credentials
    controller._client_factory = build_client
    controller._private_ws_factory = lambda **_: private_ws

    result = controller.emergency_reduce_only_exit(_fresh_operator_payload())

    assert result["orders_posted"] == 1
    assert result["final_flat"] is True
    assert len(created) == 1
    assert created[0].credential_service == "quant-system.okx-demo.trade"
    assert created[0].allow_private_read is True
    assert created[0].allow_demo_orders is True
    assert created[0].allow_demo_cancels is True
    assert controller.status()["runtime"]["opening_allowed"] is False
    assert controller.status()["runtime"]["cancel_only"] is True
    assert client.submit_calls[0]["side"] == "sell"
    assert client.submit_calls[0]["posSide"] == "long"
    assert client.submit_calls[0]["ordType"] == "ioc"
    assert len(client.cancel_algo_calls) == 1
    assert controller.status()["runtime"]["active"] is False
    assert controller.status()["runtime"]["opening_allowed"] is False
    assert controller.status()["runtime"]["cancel_only"] is True
    assert controller.status()["risk_control"]["mode"] == "FROZEN_UNKNOWN"
    assert private_ws.stopped is True

    with pytest.raises(
        OkxDemoPaperRuntimeError,
        match="already_attempted",
    ):
        controller.emergency_reduce_only_exit(_fresh_operator_payload())
    assert len(client.submit_calls) == 1


def test_fresh_state_bootstrap_probe_exception_persists_structured_diagnostics(
    tmp_path: Path,
) -> None:
    controller, client, _ = _fresh_emergency_controller(
        tmp_path,
        bootstrap=True,
    )
    controller._client = None
    controller._private_ws = None

    class FailingBootstrapWS(FreshEmergencyWS):
        def run_startup_reconnect_probe(self) -> dict[str, Any]:
            raise RuntimeError(
                json.dumps(
                    {
                        "stage": "login",
                        "apiKey": "REDACTED_CREDENTIAL_LITERAL",
                        "secretKey": "REDACTED_CREDENTIAL_LITERAL",
                        "passphrase": "REDACTED_CREDENTIAL_LITERAL",
                        "accountId": "BOOTSTRAP_ACCOUNT_SENTINEL",
                        "proxy": "http://bootstrap.proxy.sentinel:17309",
                    }
                )
            )

    controller._credential_loader = lambda _: _credentials()
    controller._client_factory = lambda _config, _credentials_value: client
    controller._private_ws_factory = lambda **_: FailingBootstrapWS()

    with pytest.raises(
        OkxDemoPaperRuntimeError,
        match="okx_demo_fresh_state_bootstrap_private_ws_probe_failed",
    ):
        controller.emergency_reduce_only_exit(_fresh_operator_payload())

    status = controller.status()
    diagnostics = status["runtime"]["probe_diagnostics"]
    assert diagnostics
    detail = diagnostics[0]
    assert detail["stage"] == "login"
    assert detail["error_code"] == "okx_demo_private_ws_probe_exception"
    assert detail["receipt_verification"]["valid"] is False
    assert detail["generation"]["match"] is True
    assert status["private_ws"]["probe_diagnostics"] == diagnostics
    assert status["runtime"]["opening_allowed"] is False
    assert status["runtime"]["cancel_only"] is True
    assert status["risk_control"]["mode"] == "FROZEN_UNKNOWN"
    assert status["risk_control"]["alerts"][0]["probe_diagnostics"] == diagnostics
    blocked = [
        row
        for row in status["events"]
        if row["event_type"] == "fresh_state_emergency_reduce_only_exit_blocked"
    ]
    assert blocked
    assert blocked[0]["payload"]["probe_diagnostics"] == diagnostics
    encoded = json.dumps(status, sort_keys=True)
    for sentinel in (
        "BOOTSTRAP_API_SENTINEL",
        "BOOTSTRAP_SECRET_SENTINEL",
        "BOOTSTRAP_PASS_SENTINEL",
        "BOOTSTRAP_ACCOUNT_SENTINEL",
        "bootstrap.proxy.sentinel",
        "17309",
    ):
        assert sentinel not in encoded
    assert client.submit_calls == []
    assert client.cancel_algo_calls == []
    assert client.dead_man_calls == []


def test_fresh_state_bootstrap_non_opening_probe_keeps_receipt_and_progress(
    tmp_path: Path,
) -> None:
    controller, client, _ = _fresh_emergency_controller(
        tmp_path,
        bootstrap=True,
    )
    controller._client = None
    controller._private_ws = None

    class NonOpeningBootstrapWS(FreshEmergencyWS):
        def run_startup_reconnect_probe(self) -> dict[str, Any]:
            return {
                "source_head": _repo_head_for_test(),
                "startup_reconciled": False,
                "disconnect_cancel_only_observed": False,
                "reconnect_login_observed": False,
                "reconnect_resubscribed": False,
                "reconnect_rest_reconciled": False,
                "opening_allowed_after_reconciliation": False,
                "probe_diagnostics": [
                    {
                        "stage": "reconnect",
                        "exception_type": "ProtocolError",
                        "message": "okx_demo_private_ws_reconnect_failed",
                        "protocol": {"sCode": "60009", "msg": "reconnect failed"},
                        "subscription_progress": {
                            "observed_channels": ["orders"],
                            "expected_channels": ["orders", "positions"],
                            "complete": False,
                        },
                    }
                ],
            }

    controller._credential_loader = lambda _: _credentials()
    controller._client_factory = lambda _config, _credentials_value: client
    controller._private_ws_factory = lambda **_: NonOpeningBootstrapWS()

    with pytest.raises(
        OkxDemoPaperRuntimeError,
        match="okx_demo_fresh_state_bootstrap_private_ws_probe_failed",
    ):
        controller.emergency_reduce_only_exit(_fresh_operator_payload())

    status = controller.status()
    detail = status["runtime"]["probe_diagnostics"][0]
    assert detail["stage"] == "reconnect"
    assert detail["protocol"]["sCode"] == "60009"
    assert detail["reconciliation_progress"]["reconnect_rest_reconciled"] is False
    assert detail["receipt_verification"]["opening_allowed"] is False
    assert status["runtime"]["opening_allowed"] is False
    assert status["runtime"]["cancel_only"] is True
    assert client.submit_calls == []
    assert client.cancel_algo_calls == []


def test_fresh_state_bootstrap_generation_change_is_diagnostic_and_zero_post(
    tmp_path: Path,
) -> None:
    controller, client, _ = _fresh_emergency_controller(
        tmp_path,
        bootstrap=True,
    )
    controller._client = None
    controller._private_ws = None

    class GenerationChangingBootstrapWS(FreshEmergencyWS):
        def start_monitoring(self) -> None:
            super().start_monitoring()
            controller._private_ws_generation += 1

    controller._credential_loader = lambda _: _credentials()
    controller._client_factory = lambda _config, _credentials_value: client
    controller._private_ws_factory = lambda **_: GenerationChangingBootstrapWS()

    with pytest.raises(
        OkxDemoPaperRuntimeError,
        match="okx_demo_fresh_state_bootstrap_private_ws_generation_mismatch",
    ):
        controller.emergency_reduce_only_exit(_fresh_operator_payload())

    status = controller.status()
    detail = status["runtime"]["probe_diagnostics"][0]
    assert detail["stage"] == "reconciliation"
    assert detail["error_code"] == "okx_demo_private_ws_generation_mismatch"
    assert detail["generation"]["match"] is False
    assert status["runtime"]["opening_allowed"] is False
    assert status["runtime"]["cancel_only"] is True
    assert client.submit_calls == []
    assert client.cancel_algo_calls == []


@pytest.mark.parametrize(
    "mutation",
    [
        lambda controller: controller._state["runtime"].update(
            {"active": True}
        ),
        lambda controller: controller._state["runtime"].update(
            {"cancel_only": False}
        ),
        lambda controller: controller._state["risk_control"].update(
            {"mode": "RUNNING"}
        ),
        lambda controller: setattr(controller, "_client", None),
    ],
)
def test_fresh_state_emergency_exit_all_state_gates_are_zero_order_post(
    tmp_path: Path,
    mutation: Any,
) -> None:
    controller, client, _ = _fresh_emergency_controller(tmp_path)
    mutation(controller)

    with pytest.raises(OkxDemoPaperRuntimeError):
        controller.emergency_reduce_only_exit(_fresh_operator_payload())

    assert client.submit_calls == []
    assert client.cancel_algo_calls == []


def test_fresh_state_emergency_exit_response_loss_queries_by_clordid_once(
    tmp_path: Path,
) -> None:
    controller, client, _ = _fresh_emergency_controller(
        tmp_path,
        response_lost=True,
    )

    result = controller.emergency_reduce_only_exit(_fresh_operator_payload())

    assert result["orders_posted"] == 1
    assert len(client.submit_calls) == 1
    cl_ord_id = client.submit_calls[0]["clOrdId"]
    assert any(
        call["path"] == "/api/v5/trade/order"
        and call["params"].get("clOrdId") == cl_ord_id
        for call in client.private_calls
    )


def test_fresh_state_emergency_exit_partial_fill_remains_frozen_and_no_retry(
    tmp_path: Path,
) -> None:
    controller, client, _ = _fresh_emergency_controller(
        tmp_path,
        partial=True,
    )

    with pytest.raises(
        OkxDemoPaperRuntimeError,
        match="position_not_flat|nonflat|position_lot_invalid|partially_filled",
    ):
        controller.emergency_reduce_only_exit(_fresh_operator_payload())

    assert len(client.submit_calls) == 1
    assert controller.status()["runtime"]["active"] is False
    assert controller.status()["runtime"]["opening_allowed"] is False
    assert controller.status()["runtime"]["cancel_only"] is True
    assert controller.status()["risk_control"]["mode"] == "FROZEN_UNKNOWN"
    assert controller.status()["runtime"]["fresh_state_emergency_exit"][
        "status"
    ] == "blocked"


def test_fresh_state_emergency_exit_rejects_foreign_oco_without_cancel_or_order(
    tmp_path: Path,
) -> None:
    controller, client, _ = _fresh_emergency_controller(
        tmp_path,
        foreign_algo=True,
    )

    with pytest.raises(
        OkxDemoPaperRuntimeError,
        match="foreign_algo",
    ):
        controller.emergency_reduce_only_exit(_fresh_operator_payload())

    assert client.submit_calls == []
    assert client.cancel_algo_calls == []
    assert controller.status()["runtime"]["opening_allowed"] is False
    assert controller.status()["runtime"]["cancel_only"] is True


def test_fresh_state_emergency_exit_never_auto_starts_or_unlocks_opening(
    tmp_path: Path,
) -> None:
    controller, client, _ = _fresh_emergency_controller(tmp_path)
    controller._private_ws = None

    with pytest.raises(OkxDemoPaperRuntimeError):
        controller.emergency_reduce_only_exit(_fresh_operator_payload())

    assert client.submit_calls == []
    assert controller._thread is None
    assert controller._dead_man_thread is None
    assert controller.status()["runtime"]["opening_allowed"] is False
    assert controller.status()["safety"]["auto_start_on_backend_launch"] is False


def _stop_and_flatten_snapshot(*, nonflat: bool = False) -> dict[str, Any]:
    snapshot = _p0_order_snapshot()
    snapshot.update(
        {
            "captured_at_utc": datetime.now(timezone.utc).isoformat(),
            "account": {"account_level": "2", "withdraw_permission_present": False},
            "balance": {"equity_usdt": "5000", "timestamp_ms": "1"},
            "positions": (
                [{"instrument_id": "BTC-USDT-SWAP", "position_side": "long", "margin_mode": "isolated", "contracts": "0.01", "average_price": "60000", "mark_price": "60000", "unrealized_pnl": "0"}]
                if nonflat
                else []
            ),
            "pending_orders": [],
            "pending_algo_orders": [],
            "orders": [],
            "fills": [],
            "bills": [],
            "mark": {"mark_price": "60000", "timestamp_ms": "1"},
        }
    )
    return snapshot


class _StopAndFlattenWS:
    def __init__(self) -> None:
        self.stopped = False

    def stop(self) -> dict[str, Any]:
        self.stopped = True
        return {"listener_joined": True}

    def status(self) -> dict[str, Any]:
        return {"connected": False, "listener_alive": False}


def _prepare_stop_and_flatten_controller(
    tmp_path: Path,
    *,
    nonflat: bool = False,
) -> tuple[OkxDemoPaperRuntimeController, SnapshotClient, _StopAndFlattenWS, dict[str, Any]]:
    controller = _controller(tmp_path, lambda _: _credentials())
    client = SnapshotClient()
    private_ws = _StopAndFlattenWS()
    snapshot = _stop_and_flatten_snapshot(nonflat=nonflat)
    controller._client = client  # type: ignore[assignment]
    controller._private_ws = private_ws  # type: ignore[assignment]
    controller._state["runtime"].update(
        {
            "run_id": "stop-flatten-run",
            "active": True,
            "status": "running",
            "opening_allowed": True,
            "cancel_only": False,
        }
    )
    controller._state["risk_control"]["mode"] = "RUNNING"
    controller._state["risk_control"]["write_path_trusted"] = True
    controller._state["private_ws"].update(
        {
            "connected": True,
            "listener_alive": True,
            "opening_allowed_after_reconciliation": True,
        }
    )
    controller._state["ledger_reconciliation"].update(
        {
            "status": "reconciled",
            "current_state_exchange_snapshot_match": True,
            "funding_cashflow_reconciled": True,
        }
    )
    controller._collect_exchange_snapshot = lambda _client: dict(snapshot)  # type: ignore[method-assign]
    controller._commit_ledger_reconciliation = lambda **_kwargs: None  # type: ignore[method-assign]
    controller._cleanup_owned_flat_algos = lambda _client, *, snapshot: (  # type: ignore[method-assign]
        dict(snapshot),
        {"attempted": False, "cancelled_algo_ids": []},
    )
    controller._disarm_dead_man_if_safe = lambda *_args, **_kwargs: []  # type: ignore[method-assign]
    return controller, client, private_ws, snapshot


def test_stop_preserves_position_but_stop_and_flatten_flat_is_zero_order_and_idempotent(
    tmp_path: Path,
) -> None:
    controller, client, private_ws, _ = _prepare_stop_and_flatten_controller(tmp_path)
    controller._run_risk_reduction_cycle = lambda *_args, **_kwargs: None  # type: ignore[method-assign]

    result = controller.stop_and_flatten(
        {"confirmation_text": OKX_DEMO_STOP_AND_FLATTEN_CONFIRMATION}
    )

    assert result["runtime"]["status"] == "stopped_and_flattened"
    assert result["runtime"]["stop_and_flatten"]["status"] == "completed"
    assert result["runtime"]["stop_and_flatten"]["orders_posted"] == 0
    assert result["runtime"]["stop_and_flatten"]["final_flat"] is True
    assert client.order_calls == []
    assert client.cancel_calls == []
    assert private_ws.stopped is True
    with pytest.raises(OkxDemoPaperRuntimeError, match="already_attempted"):
        controller.stop_and_flatten(
            {"confirmation_text": OKX_DEMO_STOP_AND_FLATTEN_CONFIRMATION}
        )


def test_stop_and_flatten_persists_close_clord_before_one_reduce_only_post(
    tmp_path: Path,
) -> None:
    controller, snapshot, order_plan = _p0_order_controller(tmp_path)
    client = OrderScenarioClient()
    controller._state["runtime"]["stop_and_flatten"].update(
        {"status": "preflight", "post_attempts": 0}
    )
    close_plan = controller._build_order_plan(
        snapshot,
        current_quantity=Decimal("0.01"),
        target_quantity=Decimal("0"),
    )
    assert close_plan is not None and close_plan["risk_reducing_only"] is True
    controller._collect_exchange_snapshot = lambda _client: dict(snapshot)  # type: ignore[method-assign]
    controller._preflight_blockers = lambda _snapshot, require_flat: []  # type: ignore[method-assign]
    controller._commit_ledger_reconciliation = lambda **_kwargs: None  # type: ignore[method-assign]

    result = controller._submit_order_plan(
        client,
        snapshot=snapshot,
        decision={
            "strategy_id": "long_short_donchian_top5",
            "direction": "flat",
            "raw_signal": "0",
            "target_contracts": "0",
        },
        order_plan=close_plan,
    )

    marker = controller.status()["runtime"]["stop_and_flatten"]
    assert marker["client_order_id"] == close_plan["client_order_id"]
    assert marker["close_intent_persisted"] is True
    assert marker["post_attempts"] == 1
    assert len(client.submit_calls) == 1
    assert result["exchange_order_id"] == "order-1"


def test_stop_and_flatten_partial_or_identity_failure_stays_fail_closed_without_cleanup(
    tmp_path: Path,
) -> None:
    controller, client, private_ws, _ = _prepare_stop_and_flatten_controller(
        tmp_path,
        nonflat=True,
    )
    cleanup_calls: list[bool] = []
    controller._cleanup_owned_flat_algos = lambda *_args, **_kwargs: (  # type: ignore[method-assign]
        cleanup_calls.append(True) or ({}, {})
    )
    controller._run_risk_reduction_cycle = lambda *_args, **_kwargs: (_ for _ in ()).throw(  # type: ignore[method-assign]
        OkxDemoPaperRuntimeError("okx_demo_reduce_only_exit_partially_filled")
    )

    with pytest.raises(OkxDemoPaperRuntimeError, match="partially_filled"):
        controller.stop_and_flatten(
            {"confirmation_text": OKX_DEMO_STOP_AND_FLATTEN_CONFIRMATION}
        )

    marker = controller.status()["runtime"]["stop_and_flatten"]
    assert marker["status"] == "blocked"
    assert marker["post_attempts"] == 0
    assert marker["blind_retry_allowed"] is False
    assert cleanup_calls == []
    assert client.order_calls == []
    assert client.cancel_calls == []
    assert private_ws.stopped is False
    assert controller.status()["runtime"]["opening_allowed"] is False
    assert controller.status()["runtime"]["cancel_only"] is True


def test_stop_and_flatten_foreign_oco_is_rejected_before_any_post(
    tmp_path: Path,
) -> None:
    controller, client, private_ws, _ = _prepare_stop_and_flatten_controller(
        tmp_path,
        nonflat=True,
    )
    fixed_now = datetime(2026, 8, 19, 0, 0, tzinfo=timezone.utc)
    snapshot = _fresh_emergency_snapshot(
        lambda: fixed_now,
        nonflat=True,
        foreign_algo=True,
    )
    controller._collect_exchange_snapshot = lambda _client: dict(snapshot)  # type: ignore[method-assign]

    with pytest.raises(
        OkxDemoPaperRuntimeError,
        match=(
            "(stop_and_flatten_foreign_algo_present|"
            "stop_and_flatten_algo_owner_missing|"
            "nonflat_position_has_no_verified_protection)"
        ),
    ):
        controller.stop_and_flatten(
            {"confirmation_text": OKX_DEMO_STOP_AND_FLATTEN_CONFIRMATION}
        )

    assert client.order_calls == []
    assert client.cancel_calls == []
    assert private_ws.stopped is False
    assert controller.status()["runtime"]["stop_and_flatten"]["status"] == "blocked"


def test_snapshot_sanitizers_keep_missing_pnl_and_funding_unknown() -> None:
    balance = okx_demo_runtime_module._sanitize_balance({
        "details": [{"ccy": "USDT", "eq": "5000"}],
    })
    position = okx_demo_runtime_module._sanitize_position({
        "instId": "BTC-USDT-SWAP",
        "posSide": "long",
        "pos": "0.01",
    })
    fill = okx_demo_runtime_module._sanitize_fill({
        "tradeId": "fill-1",
        "instId": "BTC-USDT-SWAP",
    })
    bill = okx_demo_runtime_module._sanitize_bill({
        "billId": "bill-1",
        "instId": "BTC-USDT-SWAP",
    })
    assert balance["unrealized_pnl_usdt"] == ""
    assert balance["unrealized_pnl_observed"] is False
    assert position["unrealized_pnl"] == ""
    assert position["realized_pnl"] == ""
    assert position["unrealized_pnl_observed"] is False
    assert position["realized_pnl_observed"] is False
    assert fill["pnl"] == ""
    assert fill["pnl_observed"] is False
    assert bill["balance_change"] == ""
    assert bill["pnl"] == ""
    assert bill["balance_change_observed"] is False
    assert bill["pnl_observed"] is False
    with pytest.raises(OkxDemoPaperRuntimeError, match="funding_cashflow_unknown"):
        okx_demo_runtime_module._observed_decimal_total(
            [bill],
            field="balance_change",
            observed_flag="balance_change_observed",
            error_code="okx_demo_funding_cashflow_unknown",
        )
