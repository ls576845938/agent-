from __future__ import annotations

import json
import sys
import threading
import time
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, Mapping

import pytest

from quant_crypto.oms.okx_demo import OkxDemoCredentials
from quant_crypto.oms.okx_demo_private_ws import (
    OKX_DEMO_PRIVATE_WS_SUBSCRIPTIONS,
    OKX_DEMO_PRIVATE_WS_URL,
    OkxDemoPrivateWS,
    OkxDemoPrivateWSError,
    _WebsocketClientFactory,
)


HEAD = "a" * 40
NOW = datetime(2026, 7, 30, 3, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    ("proxy_url", "expected_host"),
    (
        ("http://127.0.0.1:15421", "127.0.0.1"),
        ("http://localhost:15421", "localhost"),
    ),
)
def test_websocket_factory_uses_dedicated_loopback_proxy(
    monkeypatch: pytest.MonkeyPatch,
    proxy_url: str,
    expected_host: str,
) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []
    connection = object()

    def create_connection(url: str, **kwargs: Any) -> object:
        calls.append((url, kwargs))
        return connection

    monkeypatch.setenv("QS_OKX_DEMO_WS_PROXY_URL", proxy_url)
    monkeypatch.setitem(
        sys.modules,
        "websocket",
        SimpleNamespace(create_connection=create_connection),
    )

    result = _WebsocketClientFactory()(
        url=OKX_DEMO_PRIVATE_WS_URL,
        timeout_seconds=12.5,
    )

    assert result is connection
    assert calls == [
        (
            OKX_DEMO_PRIVATE_WS_URL,
            {
                "timeout": 12.5,
                "http_proxy_host": expected_host,
                "http_proxy_port": 15421,
                "proxy_type": "http",
                "http_proxy_timeout": 12.5,
            },
        )
    ]


@pytest.mark.parametrize(
    "proxy_url",
    (
        "",
        "https://127.0.0.1:15421",
        "socks5://127.0.0.1:15421",
        "http://proxy.example:15421",
        "REDACTED_SENSITIVE_PATTERN127.0.0.1:15421",
        "http://127.0.0.1",
        "http://127.0.0.1:0",
        "http://127.0.0.1:65536",
        "http://127.0.0.1:not-a-port",
        "http://127.0.0.1:15421/path",
    ),
)
def test_websocket_factory_rejects_invalid_dedicated_proxy(
    monkeypatch: pytest.MonkeyPatch,
    proxy_url: str,
) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def create_connection(url: str, **kwargs: Any) -> object:
        calls.append((url, kwargs))
        return object()

    monkeypatch.setenv("QS_OKX_DEMO_WS_PROXY_URL", proxy_url)
    monkeypatch.setitem(
        sys.modules,
        "websocket",
        SimpleNamespace(create_connection=create_connection),
    )

    with pytest.raises(
        OkxDemoPrivateWSError,
        match="okx_demo_private_ws_proxy_invalid",
    ):
        _WebsocketClientFactory()(
            url=OKX_DEMO_PRIVATE_WS_URL,
            timeout_seconds=12.5,
        )

    assert calls == []


def test_websocket_factory_without_dedicated_proxy_keeps_existing_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []
    connection = object()

    def create_connection(url: str, **kwargs: Any) -> object:
        calls.append((url, kwargs))
        return connection

    monkeypatch.delenv("QS_OKX_DEMO_WS_PROXY_URL", raising=False)
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:12334")
    monkeypatch.setitem(
        sys.modules,
        "websocket",
        SimpleNamespace(create_connection=create_connection),
    )

    result = _WebsocketClientFactory()(
        url=OKX_DEMO_PRIVATE_WS_URL,
        timeout_seconds=12.5,
    )

    assert result is connection
    assert calls == [
        (OKX_DEMO_PRIVATE_WS_URL, {"timeout": 12.5})
    ]


class FakeConnection:
    def __init__(
        self,
        *,
        login_code: str = "0",
        login_message: str = "",
        subscribe_error: dict[str, str] | None = None,
    ) -> None:
        self.sent: list[str] = []
        self.closed = False
        self._messages: list[str] = [
            json.dumps(
                {"event": "login", "code": login_code, "msg": login_message}
            )
        ]
        if subscribe_error is not None:
            self._messages.append(
                json.dumps({"event": "error", **dict(subscribe_error)})
            )
        else:
            self._messages.extend(
                [
                    json.dumps(
                        {"event": "subscribe", "arg": dict(subscription)}
                    )
                    for subscription in OKX_DEMO_PRIVATE_WS_SUBSCRIPTIONS
                ]
            )

    def send(self, payload: str) -> None:
        self.sent.append(payload)

    def recv(self) -> str:
        if not self._messages:
            raise RuntimeError("socket_closed")
        return self._messages.pop(0)

    def close(self) -> None:
        self.closed = True


class FakeFactory:
    def __init__(
        self,
        *,
        login_codes: tuple[str, ...] = ("0", "0"),
        login_messages: tuple[str, ...] = (),
        subscribe_errors: tuple[dict[str, str], ...] = (),
    ) -> None:
        self.login_codes = list(login_codes)
        self.login_messages = list(login_messages)
        self.subscribe_errors = list(subscribe_errors)
        self.calls: list[dict[str, Any]] = []
        self.connections: list[FakeConnection] = []

    def __call__(self, *, url: str, timeout_seconds: float) -> FakeConnection:
        connection = FakeConnection(
            login_code=self.login_codes.pop(0),
            login_message=(
                self.login_messages.pop(0) if self.login_messages else ""
            ),
            subscribe_error=(
                self.subscribe_errors.pop(0) if self.subscribe_errors else None
            ),
        )
        self.calls.append({"url": url, "timeout_seconds": timeout_seconds})
        self.connections.append(connection)
        return connection


def _credentials() -> OkxDemoCredentials:
    return OkxDemoCredentials(
        api_key="REDACTED_CREDENTIAL_LITERAL",
        secret_key="REDACTED_CREDENTIAL_LITERAL",
        passphrase="REDACTED_CREDENTIAL_LITERAL",
    )


def _snapshot() -> dict[str, object]:
    return {
        "captured_at_utc": NOW.isoformat(),
        "pending_orders": [],
        "fills": [],
        "positions": [],
        "balance": {"equity_usdt": "100"},
        "bills": [],
    }


def test_startup_probe_disconnects_reconnects_and_rest_reconciles() -> None:
    factory = FakeFactory()
    disconnects: list[str] = []
    reconciled: list[dict[str, Any]] = []
    connector = OkxDemoPrivateWS(
        credentials=_credentials(),
        source_head=HEAD,
        runtime_version="okx-demo-runtime-v1",
        snapshot_loader=_snapshot,
        owned_client_order_ids=lambda: (),
        on_disconnect=disconnects.append,
        on_reconciled=reconciled.append,
        connection_factory=factory,
        clock=lambda: NOW,
    )

    receipt = connector.run_startup_reconnect_probe()

    assert [call["url"] for call in factory.calls] == [
        OKX_DEMO_PRIVATE_WS_URL,
        OKX_DEMO_PRIVATE_WS_URL,
    ]
    assert disconnects == ["private_ws_startup_probe_local_disconnect"]
    assert factory.connections[0].closed is True
    assert receipt["startup_reconciled"] is True
    assert receipt["disconnect_cancel_only_observed"] is True
    assert receipt["reconnect_login_observed"] is True
    assert receipt["reconnect_resubscribed"] is True
    assert receipt["reconnect_rest_reconciled"] is True
    assert receipt["opening_allowed_after_reconciliation"] is True
    assert receipt["private_ws_promotion_gate_retired"] is False
    assert receipt["promotion_evidence_ready"] is False
    assert reconciled == [receipt]


def test_probe_fetches_one_fresh_snapshot_per_authenticated_generation() -> None:
    snapshots: list[dict[str, object]] = []
    factory = FakeFactory()

    def fresh_snapshot() -> dict[str, object]:
        snapshot = _snapshot()
        snapshots.append(snapshot)
        return snapshot

    connector = OkxDemoPrivateWS(
        credentials=_credentials(), source_head=HEAD,
        runtime_version="okx-demo-runtime-v1", snapshot_loader=fresh_snapshot,
        owned_client_order_ids=lambda: (), on_disconnect=lambda _: None,
        connection_factory=factory, clock=lambda: NOW,
    )
    receipt = connector.run_startup_reconnect_probe()
    assert receipt["opening_allowed_after_reconciliation"] is True
    assert len(factory.connections) == 2
    assert len(snapshots) == 2, "reconnect must not repeat a synthetic startup REST snapshot"
    assert snapshots[0] is not snapshots[1], "never reuse the pre-disconnect snapshot"
    connector.stop()


@pytest.mark.parametrize("field,value", [
    ("pending_orders", [{"clOrdId": "foreign-order"}]),
    ("fills", [{"clOrdId": "foreign-fill"}]),
    ("positions", [{}, {}]),
    ("balance", {}),
])
def test_new_reconnect_snapshot_still_blocks_unsafe_account_facts(field, value) -> None:
    calls = 0
    reconciled: list[dict[str, Any]] = []

    def snapshot_after_disconnect() -> dict[str, object]:
        nonlocal calls
        calls += 1
        snapshot = _snapshot()
        if calls > 1:
            snapshot[field] = value
        return snapshot

    connector = OkxDemoPrivateWS(
        credentials=_credentials(), source_head=HEAD,
        runtime_version="okx-demo-runtime-v1", snapshot_loader=snapshot_after_disconnect,
        owned_client_order_ids=lambda: (), on_disconnect=lambda _: None,
        on_reconciled=reconciled.append, connection_factory=FakeFactory(), clock=lambda: NOW,
    )
    receipt = connector.run_startup_reconnect_probe()
    assert receipt["startup_reconciled"] is True
    assert receipt["opening_allowed_after_reconciliation"] is False
    assert receipt["blockers"]
    assert reconciled == []
    assert calls == 2
    connector.stop()


def test_probe_does_not_spend_deadline_on_redundant_third_snapshot() -> None:
    release = threading.Event()
    calls = 0

    def slow_redundant_snapshot() -> dict[str, object]:
        nonlocal calls
        calls += 1
        if calls > 2:
            release.wait(3.0)
        return _snapshot()

    connector = OkxDemoPrivateWS(
        credentials=_credentials(), source_head=HEAD,
        runtime_version="okx-demo-runtime-v1", snapshot_loader=slow_redundant_snapshot,
        owned_client_order_ids=lambda: (), on_disconnect=lambda _: None,
        connection_factory=FakeFactory(), clock=lambda: NOW,
        startup_reconnect_probe_timeout_seconds=1.0,
    )
    try:
        receipt = connector.run_startup_reconnect_probe()
        assert receipt["opening_allowed_after_reconciliation"] is True
        assert receipt["reconnect_rest_reconciled"] is True
        assert calls == 2
    finally:
        release.set()
        connector.stop()


def test_startup_reconnect_probe_default_wallclock_budget_is_calibrated() -> None:
    """The default must cover two authenticated WS generations and REST reads."""

    connector = OkxDemoPrivateWS(
        credentials=_credentials(),
        source_head=HEAD,
        runtime_version="okx-demo-runtime-v1",
        snapshot_loader=_snapshot,
        owned_client_order_ids=lambda: (),
        on_disconnect=lambda _: None,
        connection_factory=FakeFactory(),
        clock=lambda: NOW,
        timeout_seconds=20.0,
    )

    assert connector._startup_reconnect_probe_timeout_seconds == 160.0


def test_startup_probe_reconnect_wallclock_timeout_is_terminal_and_late_worker_isolated() -> None:
    """A hung generation-2 snapshot must not leave the probe without a receipt."""

    release_reconnect = threading.Event()
    reconnect_started = threading.Event()
    snapshot_calls = 0
    reconciled: list[dict[str, Any]] = []

    def blocking_reconnect_snapshot() -> dict[str, object]:
        nonlocal snapshot_calls
        snapshot_calls += 1
        if snapshot_calls >= 2:
            reconnect_started.set()
            release_reconnect.wait(2.0)
        return _snapshot()

    factory = FakeFactory()
    connector = OkxDemoPrivateWS(
        credentials=_credentials(),
        source_head=HEAD,
        runtime_version="okx-demo-runtime-v1",
        snapshot_loader=blocking_reconnect_snapshot,
        owned_client_order_ids=lambda: (),
        on_disconnect=lambda _: None,
        on_reconciled=reconciled.append,
        connection_factory=factory,
        clock=lambda: NOW,
        timeout_seconds=1.0,
        startup_reconnect_probe_timeout_seconds=0.05,
    )

    started_at = time.monotonic()
    receipt = connector.run_startup_reconnect_probe()
    elapsed = time.monotonic() - started_at

    assert reconnect_started.is_set()
    assert elapsed < 0.5
    assert receipt["opening_allowed_after_reconciliation"] is False
    assert receipt["blockers"] == [
        "btc_okx_demo_private_ws:probe_wallclock_timeout"
    ]
    detail = receipt["probe_diagnostics"][-1]
    assert detail["stage"] == "reconnect"
    assert detail["exception_type"] == "ProbeWallClockTimeout"
    assert detail["message"] == "okx_demo_private_ws_probe_wallclock_timeout"
    assert receipt["probe_generation"] == 2
    assert reconciled == []
    assert connector.status()["connected"] is False
    assert connector.status()["listener_alive"] is False
    assert connector.status()["opening_allowed_after_reconciliation"] is False

    # The timed-out worker may finish only after it has been fenced off.  It
    # must not resurrect the socket or call the success callback late.
    release_reconnect.set()
    time.sleep(0.05)
    assert reconciled == []
    assert connector.status()["connected"] is False
    assert connector.status()["opening_allowed_after_reconciliation"] is False
    assert all(connection.closed for connection in factory.connections)


def test_login_and_subscribe_messages_never_contain_order_operation() -> None:
    factory = FakeFactory()
    connector = OkxDemoPrivateWS(
        credentials=_credentials(),
        source_head=HEAD,
        runtime_version="okx-demo-runtime-v1",
        snapshot_loader=_snapshot,
        owned_client_order_ids=lambda: (),
        on_disconnect=lambda _: None,
        connection_factory=factory,
        clock=lambda: NOW,
    )
    connector.run_startup_reconnect_probe()

    for connection in factory.connections:
        messages = [json.loads(payload) for payload in connection.sent]
        assert [message["op"] for message in messages] == [
            "login",
            "subscribe",
        ]
        subscription = messages[1]
        assert {row["channel"] for row in subscription["args"]} == {
            "orders",
            "positions",
            "balance_and_position",
            "account",
        }
        assert all(message["op"] not in {"order", "cancel-order"} for message in messages)


def test_failed_login_is_fail_closed_and_credentials_are_not_in_receipt() -> None:
    factory = FakeFactory(login_codes=("60009",))
    disconnects: list[str] = []
    connector = OkxDemoPrivateWS(
        credentials=_credentials(),
        source_head=HEAD,
        runtime_version="okx-demo-runtime-v1",
        snapshot_loader=_snapshot,
        owned_client_order_ids=lambda: (),
        on_disconnect=disconnects.append,
        connection_factory=factory,
        clock=lambda: NOW,
    )

    receipt = connector.run_startup_reconnect_probe()
    encoded = json.dumps(receipt, sort_keys=True)

    assert receipt["opening_allowed_after_reconciliation"] is False
    assert receipt["credentials_redacted"] is True
    assert "demo-api-key" not in encoded
    assert "demo-secret-key" not in encoded
    assert "demo-passphrase" not in encoded
    assert disconnects


def _assert_probe_diagnostic_is_structured_and_redacted(
    detail: Mapping[str, Any],
    *,
    stage: str,
    secret_tokens: tuple[str, ...] = (
        "demo-api-key",
        "demo-secret-key",
        "demo-passphrase",
        "http://127.0.0.1:17309",
        "127.0.0.1",
        "17309",
        "acct-42",
    ),
) -> None:
    assert detail["stage"] == stage
    assert str(detail["exception_type"])
    assert isinstance(detail["message"], str)
    assert isinstance(detail["protocol"], Mapping)
    assert set(detail["protocol"]) == {"sCode", "msg"}
    progress = detail["subscription_progress"]
    assert isinstance(progress, Mapping)
    assert set(progress) == {
        "observed_channels",
        "expected_channels",
        "complete",
    }
    encoded = json.dumps(detail, sort_keys=True)
    for token in secret_tokens:
        assert token not in encoded


def test_probe_preserves_login_protocol_diagnostic_and_subscription_progress() -> None:
    factory = FakeFactory(
        login_codes=("60009",),
        login_messages=(
            "apiKey=demo-api-key proxy=http://127.0.0.1:17309 accountId=acct-42",
        ),
    )
    connector = OkxDemoPrivateWS(
        credentials=_credentials(),
        source_head=HEAD,
        runtime_version="okx-demo-runtime-v1",
        snapshot_loader=_snapshot,
        owned_client_order_ids=lambda: (),
        on_disconnect=lambda _: None,
        connection_factory=factory,
        clock=lambda: NOW,
    )

    receipt = connector.run_startup_reconnect_probe()

    assert receipt["opening_allowed_after_reconciliation"] is False
    assert receipt["blockers"] == [
        "btc_okx_demo_private_ws:OkxDemoPrivateWSError"
    ]
    details = receipt["probe_diagnostics"]
    assert len(details) == 1
    detail = details[0]
    _assert_probe_diagnostic_is_structured_and_redacted(
        detail,
        stage="login",
    )
    assert detail["exception_type"] == "ProtocolError"
    assert detail["protocol"]["sCode"] == "60009"
    assert detail["subscription_progress"]["complete"] is False


def test_probe_preserves_subscribe_protocol_diagnostic_and_progress() -> None:
    factory = FakeFactory(
        subscribe_errors=(
            {
                "sCode": "60012",
                "msg": "proxy=http://127.0.0.1:17309 accountId=acct-42",
            },
        )
    )
    connector = OkxDemoPrivateWS(
        credentials=_credentials(),
        source_head=HEAD,
        runtime_version="okx-demo-runtime-v1",
        snapshot_loader=_snapshot,
        owned_client_order_ids=lambda: (),
        on_disconnect=lambda _: None,
        connection_factory=factory,
        clock=lambda: NOW,
    )

    receipt = connector.run_startup_reconnect_probe()

    assert receipt["opening_allowed_after_reconciliation"] is False
    detail = receipt["probe_diagnostics"][0]
    _assert_probe_diagnostic_is_structured_and_redacted(
        detail,
        stage="subscribe",
    )
    assert detail["exception_type"] == "ProtocolError"
    assert detail["protocol"]["sCode"] == "60012"
    assert detail["subscription_progress"]["observed_channels"] == []
    assert detail["subscription_progress"]["complete"] is False


def test_probe_preserves_startup_snapshot_exception_diagnostic() -> None:
    def failing_snapshot() -> dict[str, object]:
        raise RuntimeError(
            "secret=demo-secret-key proxy=http://127.0.0.1:17309 accountId=acct-42"
        )

    factory = FakeFactory()
    connector = OkxDemoPrivateWS(
        credentials=_credentials(),
        source_head=HEAD,
        runtime_version="okx-demo-runtime-v1",
        snapshot_loader=failing_snapshot,
        owned_client_order_ids=lambda: (),
        on_disconnect=lambda _: None,
        connection_factory=factory,
        clock=lambda: NOW,
    )

    receipt = connector.run_startup_reconnect_probe()

    assert receipt["opening_allowed_after_reconciliation"] is False
    detail = receipt["probe_diagnostics"][0]
    _assert_probe_diagnostic_is_structured_and_redacted(
        detail,
        stage="startup_snapshot",
    )
    assert detail["exception_type"] == "RuntimeError"
    assert detail["subscription_progress"]["complete"] is True
    assert detail["reconciliation_blocker_codes"] == [
        "btc_private_ws:snapshot_transport_failed"
    ]
    assert detail["reconciliation_blocker_categories"] == ["transport"]


def test_probe_projects_reconciliation_blockers_without_identity_leakage() -> None:
    def unknown_fill_snapshot() -> dict[str, object]:
        snapshot = _snapshot()
        snapshot["fills"] = [
            {
                "clOrdId": "foreign-client-order-accountId=acct-42",
                "ordId": "foreign-order-id",
            }
        ]
        return snapshot

    connector = OkxDemoPrivateWS(
        credentials=_credentials(),
        source_head=HEAD,
        runtime_version="okx-demo-runtime-v1",
        snapshot_loader=unknown_fill_snapshot,
        owned_client_order_ids=lambda: (),
        on_disconnect=lambda _: None,
        connection_factory=FakeFactory(),
        clock=lambda: NOW,
    )

    receipt = connector.run_startup_reconnect_probe()

    detail = next(
        row
        for row in receipt["probe_diagnostics"]
        if row["stage"] == "startup_snapshot"
    )
    assert detail["reconciliation_blocker_codes"] == [
        "btc_private_ws:unknown_fill"
    ]
    assert detail["reconciliation_blocker_categories"] == ["identity"]
    assert detail["reconciliation_blocker_count"] == 1
    assert len(detail["reconciliation_blocker_set_sha256"]) == 64
    assert detail["identity_projection"] == {
        "account_blocker_present": False,
        "blocker_code_count": 1,
        "identity_blocker_present": True,
        "snapshot_blocker_present": False,
        "transport_blocker_present": False,
        "unknown_blocker_present": False,
    }
    encoded = json.dumps(detail, sort_keys=True)
    for token in ("foreign-client-order", "foreign-order-id", "acct-42"):
        assert token not in encoded


def test_probe_preserves_reconnect_exception_diagnostic() -> None:
    snapshot_calls = 0

    def reconnect_failing_snapshot() -> dict[str, object]:
        nonlocal snapshot_calls
        snapshot_calls += 1
        if snapshot_calls >= 2:
            raise ConnectionError(
                "passphrase=demo-passphrase proxy=http://127.0.0.1:17309 accountId=acct-42"
            )
        return _snapshot()

    factory = FakeFactory()
    connector = OkxDemoPrivateWS(
        credentials=_credentials(),
        source_head=HEAD,
        runtime_version="okx-demo-runtime-v1",
        snapshot_loader=reconnect_failing_snapshot,
        owned_client_order_ids=lambda: (),
        on_disconnect=lambda _: None,
        connection_factory=factory,
        clock=lambda: NOW,
    )

    receipt = connector.run_startup_reconnect_probe()

    assert snapshot_calls == 2
    assert receipt["opening_allowed_after_reconciliation"] is False
    detail = next(
        row for row in receipt["probe_diagnostics"] if row["stage"] == "reconnect"
    )
    _assert_probe_diagnostic_is_structured_and_redacted(
        detail,
        stage="reconnect",
    )
    assert detail["exception_type"] == "ConnectionError"
    assert detail["subscription_progress"]["complete"] is True


def test_runtime_disconnect_retries_with_backoff_until_current_reconciliation() -> None:
    factory = FakeFactory(login_codes=("0", "0", "60009", "60009", "0"))
    runtime_reconciled = threading.Event()
    receipts: list[dict[str, Any]] = []
    holder: dict[str, OkxDemoPrivateWS] = {}

    def on_reconciled(receipt: dict[str, Any]) -> None:
        receipts.append(receipt)
        if receipt.get("schema_version") == "btc_okx_demo_private_ws_runtime_reconnect_v1":
            runtime_reconciled.set()
            holder["connector"].stop()

    connector = OkxDemoPrivateWS(
        credentials=_credentials(),
        source_head=HEAD,
        runtime_version="okx-demo-runtime-v1",
        snapshot_loader=_snapshot,
        owned_client_order_ids=lambda: (),
        on_disconnect=lambda _: None,
        on_reconciled=on_reconciled,
        connection_factory=factory,
        clock=lambda: NOW,
        reconnect_initial_delay_seconds=0.001,
        reconnect_max_delay_seconds=0.002,
    )
    holder["connector"] = connector
    assert connector.run_startup_reconnect_probe()[
        "opening_allowed_after_reconciliation"
    ] is True

    connector.start_monitoring()

    assert runtime_reconciled.wait(3.0) is True
    assert len(factory.calls) == 5
    assert connector.status()["reconnect_attempt_count"] == 3
    assert any(
        receipt.get("schema_version")
        == "btc_okx_demo_private_ws_runtime_reconnect_v1"
        for receipt in receipts
    )


def test_stop_interrupts_reconnect_backoff_and_start_monitoring_is_idempotent() -> None:
    attempted = threading.Event()

    class InterruptFactory(FakeFactory):
        def __call__(self, *, url: str, timeout_seconds: float) -> FakeConnection:
            if not self.login_codes:
                attempted.set()
                raise RuntimeError("connect_failed")
            return super().__call__(url=url, timeout_seconds=timeout_seconds)

    factory = InterruptFactory(login_codes=("0", "0"))
    connector = OkxDemoPrivateWS(
        credentials=_credentials(),
        source_head=HEAD,
        runtime_version="okx-demo-runtime-v1",
        snapshot_loader=_snapshot,
        owned_client_order_ids=lambda: (),
        on_disconnect=lambda _: None,
        connection_factory=factory,
        clock=lambda: NOW,
        reconnect_initial_delay_seconds=5.0,
        reconnect_max_delay_seconds=5.0,
    )
    assert connector.run_startup_reconnect_probe()[
        "opening_allowed_after_reconciliation"
    ] is True

    connector.start_monitoring()
    listener = connector._listener
    connector.start_monitoring()

    assert connector._listener is listener
    assert attempted.wait(3.0) is True
    connector.stop()
    assert listener is not None
    listener.join(1.0)
    assert listener.is_alive() is False
    assert connector.status()["opening_allowed_after_reconciliation"] is False


def test_controlled_disconnect_reconnects_without_setting_terminal_stop() -> None:
    class BlockingConnection(FakeConnection):
        def __init__(self, *, login_code: str = "0") -> None:
            super().__init__(login_code=login_code)
            self.closed_event = threading.Event()

        def recv(self) -> str:
            if self._messages:
                return self._messages.pop(0)
            self.closed_event.wait(3.0)
            raise RuntimeError("socket_closed")

        def close(self) -> None:
            super().close()
            self.closed_event.set()

    class BlockingFactory(FakeFactory):
        def __call__(
            self,
            *,
            url: str,
            timeout_seconds: float,
        ) -> BlockingConnection:
            connection = BlockingConnection(login_code=self.login_codes.pop(0))
            self.calls.append({"url": url, "timeout_seconds": timeout_seconds})
            self.connections.append(connection)
            return connection

    factory = BlockingFactory(login_codes=("0", "0", "0"))
    runtime_reconciled = threading.Event()
    disconnects: list[str] = []
    connector = OkxDemoPrivateWS(
        credentials=_credentials(),
        source_head=HEAD,
        runtime_version="okx-demo-runtime-v1",
        snapshot_loader=_snapshot,
        owned_client_order_ids=lambda: (),
        on_disconnect=disconnects.append,
        on_reconciled=lambda receipt: runtime_reconciled.set()
        if receipt.get("schema_version")
        == "btc_okx_demo_private_ws_runtime_reconnect_v1"
        else None,
        connection_factory=factory,
        clock=lambda: NOW,
        reconnect_initial_delay_seconds=0.001,
        reconnect_max_delay_seconds=0.002,
    )
    assert connector.run_startup_reconnect_probe()[
        "opening_allowed_after_reconciliation"
    ] is True
    connector.start_monitoring()

    receipt = connector.disconnect_for_reconnect("fault_drill_controlled")

    assert receipt["terminal_stop_requested"] is False
    assert connector._stop_event.is_set() is False
    assert runtime_reconciled.wait(3.0) is True
    status = connector.status()
    assert status["connected"] is True
    assert status["listener_alive"] is True
    assert disconnects[-1] == "fault_drill_controlled"
    connector.stop()
