from __future__ import annotations

import json
import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from quant_crypto.application.btc_demo_private_readonly_observation import (
    BTC_DEMO_PRIVATE_READONLY_RUNTIME_VERSION,
    BTCPrivateReadonlyObservationConfig,
    BTCPrivateReadonlyObservationError,
    BTCPrivateReadonlyObservationRunner,
    PrivateReadonlyCapability,
    PrivateReadonlySafeError,
    _response_rows,
)
from quant_crypto.oms.okx_demo import OkxDemoResponse
from quant_crypto.research.btc_demo_observation_accumulator import (
    load_observation_receipt_ledger,
)


HEAD = "0" * 40


def _string_values(value: object) -> set[str]:
    if isinstance(value, dict):
        return {
            item
            for nested in value.values()
            for item in _string_values(nested)
        }
    if isinstance(value, list):
        return {item for nested in value for item in _string_values(nested)}
    return {value} if isinstance(value, str) else set()


class FakeClock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value


class FakeSnapshotProvider:
    capability = PrivateReadonlyCapability()

    def __init__(
        self,
        *,
        uid: str = "demo-account-1",
        permission: str | None = "read_only",
    ) -> None:
        self.uid = uid
        self.permission = permission
        self.calls = 0

    def read_snapshot(self) -> dict[str, object]:
        self.calls += 1
        return {
            "environment": "OKX Demo",
            "instrument_id": "BTC-USDT-SWAP",
            "captured_at_utc": "2026-08-29T00:00:00+00:00",
            "account_config": {
                "uid": self.uid,
                "mainUid": "demo-main-1",
                **({"perm": self.permission} if self.permission is not None else {}),
            },
            "balance": {"total_equity": "1000"},
            "positions": [],
            "pending_orders": [],
            "pending_algo_orders": [],
            "orders": [],
            "fills": [],
            "bills": [
                {
                    "bill_id": "funding-1",
                    "type": "8",
                    "sub_type": "173",
                    "balance_change": "0.25",
                    "balance_change_observed": True,
                    "timestamp": "2026-08-29T00:30:00+00:00",
                }
            ],
            "funding": {"funding_rate": "0.0001"},
        }


class FakePrivateWS:
    capability = PrivateReadonlyCapability(
        private_get_paths=(),
        websocket_operations=("subscribe", "read"),
    )

    def __init__(self) -> None:
        self.started = False
        self.stopped = False
        self.events: list[dict[str, object]] = []

    def start(self) -> dict[str, object]:
        self.started = True
        return self.status()

    def status(self) -> dict[str, object]:
        return {
            "connected": self.started and not self.stopped,
            "listener_alive": self.started and not self.stopped,
            "reconnect_login_observed": self.started,
            "reconnect_resubscribed": self.started,
            "blockers": [],
        }

    def reconcile_current(self) -> dict[str, object]:
        return {
            "reconciled": self.started and not self.stopped,
            "blockers": [],
        }

    def drain_events(self) -> list[dict[str, object]]:
        events = list(self.events)
        self.events.clear()
        return events

    def stop(self) -> dict[str, object]:
        self.stopped = True
        return {"stopped": True}


class FakeErrorSnapshotProvider:
    capability = PrivateReadonlyCapability()

    def __init__(self, response: OkxDemoResponse) -> None:
        self.response = response

    def read_snapshot(self) -> dict[str, object]:
        _response_rows(self.response, path="/api/v5/account/config")
        raise AssertionError("unreachable")


def _config(root: Path) -> BTCPrivateReadonlyObservationConfig:
    return BTCPrivateReadonlyObservationConfig(
        runtime_root=root,
        source_head=HEAD,
        run_id="btc-demo-private-readonly-observation-test",
        private_read_authorized=True,
        private_authorization_ticket_hash="a" * 64,
    )


def test_failure_first_write_capability_is_rejected_before_any_snapshot(tmp_path: Path) -> None:
    provider = FakeSnapshotProvider()
    provider.capability = PrivateReadonlyCapability(allow_demo_orders=True)
    runner = BTCPrivateReadonlyObservationRunner(
        config=_config(tmp_path),
        snapshot_provider=provider,
        private_ws=FakePrivateWS(),
    )

    with pytest.raises(
        BTCPrivateReadonlyObservationError,
        match="private_readonly_write_capability_forbidden",
    ):
        runner.start()

    assert provider.calls == 0
    assert not (tmp_path / "state.json").exists()


def test_runner_persists_identity_reconciliation_funding_and_hourly_receipt(
    tmp_path: Path,
) -> None:
    clock = FakeClock(datetime(2026, 8, 29, 0, 0, tzinfo=timezone.utc))
    provider = FakeSnapshotProvider()
    ws = FakePrivateWS()
    runner = BTCPrivateReadonlyObservationRunner(
        config=_config(tmp_path),
        snapshot_provider=provider,
        private_ws=ws,
        clock=clock,
    )

    started = runner.start()
    assert started["phase"] == "observing"
    assert started["safety"]["allow_demo_orders"] is False
    assert started["safety"]["allow_demo_cancels"] is False
    assert started["runtime_version"] == BTC_DEMO_PRIVATE_READONLY_RUNTIME_VERSION

    clock.value += timedelta(hours=1)
    polled = runner.poll()
    assert polled["phase"] == "observing"

    persisted_text = (tmp_path / "state.json").read_text(encoding="utf-8")
    assert "demo-account-1" not in persisted_text
    state = json.loads(persisted_text)
    assert len(state["account_identity_hash"]) == 64
    assert state["reconciliation"]["snapshot_reconciled"] is True
    assert state["funding"]["cashflow"] == 0.25
    assert state["funding"]["observation_count"] == 1

    receipts = load_observation_receipt_ledger(
        tmp_path / "observation" / "hourly_observation_receipts.jsonl"
    )
    assert len(receipts) == 1
    assert receipts[0]["counts_toward_25_hour_window"] is True
    assert receipts[0]["private_readonly_observation"][
        "account_identity_hash"
    ] == state["account_identity_hash"]
    assert receipts[0]["access"]["private_read_authorized"] is True
    assert receipts[0]["access"]["private_read_used"] is True
    assert receipts[0]["access"]["private_endpoint_called"] is True
    assert receipts[0]["access"]["network_used"] is True
    assert receipts[0]["access"]["secret_read"] is True
    assert receipts[0]["safety"]["order_endpoint_called"] is False
    assert receipts[0]["safety"]["cancel_endpoint_called"] is False
    runner.stop()


def test_restart_recovers_same_identity_and_rejects_account_change(tmp_path: Path) -> None:
    clock = FakeClock(datetime(2026, 8, 29, 0, 0, tzinfo=timezone.utc))
    first = BTCPrivateReadonlyObservationRunner(
        config=_config(tmp_path),
        snapshot_provider=FakeSnapshotProvider(),
        private_ws=FakePrivateWS(),
        clock=clock,
    )
    first.start()
    first.stop()

    recovered_runner = BTCPrivateReadonlyObservationRunner(
        config=_config(tmp_path),
        snapshot_provider=FakeSnapshotProvider(),
        private_ws=FakePrivateWS(),
        clock=clock,
    )
    recovered = recovered_runner.start()
    assert recovered["restart_count"] == 1
    recovered_runner.stop()

    changed = BTCPrivateReadonlyObservationRunner(
        config=_config(tmp_path),
        snapshot_provider=FakeSnapshotProvider(uid="different-account"),
        private_ws=FakePrivateWS(),
        clock=clock,
    )
    with pytest.raises(
        BTCPrivateReadonlyObservationError,
        match="private_readonly_account_identity_changed",
    ):
        changed.start()

    state = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert state["phase"] == "blocked"
    assert state["safety"]["allow_demo_orders"] is False
    assert state["safety"]["allow_demo_cancels"] is False


def test_provider_and_ws_surfaces_with_order_or_cancel_members_are_rejected(
    tmp_path: Path,
) -> None:
    class UnsafeProvider(FakeSnapshotProvider):
        def submit_order(self) -> None:
            raise AssertionError("unreachable")

    class UnsafeWS(FakePrivateWS):
        def cancel_order(self) -> None:
            raise AssertionError("unreachable")

    for provider, ws in (
        (UnsafeProvider(), FakePrivateWS()),
        (FakeSnapshotProvider(), UnsafeWS()),
    ):
        runner = BTCPrivateReadonlyObservationRunner(
            config=_config(tmp_path / str(type(provider).__name__) / str(type(ws).__name__)),
            snapshot_provider=provider,
            private_ws=ws,
        )
        with pytest.raises(
            BTCPrivateReadonlyObservationError,
            match="private_readonly_write_surface_reachable",
        ):
            runner.start()


def test_private_permission_and_exact_source_identity_are_mandatory(tmp_path: Path) -> None:
    provider = FakeSnapshotProvider()
    ws = FakePrivateWS()
    config = BTCPrivateReadonlyObservationConfig(
        runtime_root=tmp_path,
        source_head=HEAD,
        run_id="btc-demo-private-readonly-observation-test",
        private_read_authorized=False,
        private_authorization_ticket_hash="a" * 64,
    )
    runner = BTCPrivateReadonlyObservationRunner(
        config=config,
        snapshot_provider=provider,
        private_ws=ws,
    )
    with pytest.raises(
        BTCPrivateReadonlyObservationError,
        match="private_readonly_private_permission_required",
    ):
        runner.start()
    assert provider.calls == 0


def test_single_writer_lease_blocks_concurrent_runner(tmp_path: Path) -> None:
    first = BTCPrivateReadonlyObservationRunner(
        config=_config(tmp_path),
        snapshot_provider=FakeSnapshotProvider(),
        private_ws=FakePrivateWS(),
    )
    second = BTCPrivateReadonlyObservationRunner(
        config=_config(tmp_path),
        snapshot_provider=FakeSnapshotProvider(),
        private_ws=FakePrivateWS(),
    )
    first.start()
    with pytest.raises(
        BTCPrivateReadonlyObservationError,
        match="private_readonly_single_writer_lease_held",
    ):
        second.start()
    first.stop()


def test_restart_and_private_ws_gap_make_incomplete_hour_ineligible(
    tmp_path: Path,
) -> None:
    clock = FakeClock(datetime(2026, 8, 29, 0, 0, tzinfo=timezone.utc))
    first = BTCPrivateReadonlyObservationRunner(
        config=_config(tmp_path),
        snapshot_provider=FakeSnapshotProvider(),
        private_ws=FakePrivateWS(),
        clock=clock,
    )
    first.start()
    clock.value += timedelta(minutes=30)
    first.stop()

    ws = FakePrivateWS()
    restarted = BTCPrivateReadonlyObservationRunner(
        config=_config(tmp_path),
        snapshot_provider=FakeSnapshotProvider(),
        private_ws=ws,
        clock=clock,
    )
    restarted.start()
    ws.events.append({"kind": "private_ws_disconnected"})
    clock.value += timedelta(minutes=30)
    restarted.poll()
    receipts = load_observation_receipt_ledger(
        tmp_path / "observation" / "hourly_observation_receipts.jsonl"
    )
    assert len(receipts) == 1
    assert receipts[0]["counts_toward_25_hour_window"] is False
    assert receipts[0]["outage_count"] == 1
    assert "private_readonly_incomplete_hour" in receipts[0]["gap_flags"]
    assert "private_readonly_private_ws_gap_observed" in receipts[0]["gap_flags"]

    clock.value += timedelta(hours=1)
    restarted.poll()
    receipts = load_observation_receipt_ledger(
        tmp_path / "observation" / "hourly_observation_receipts.jsonl"
    )
    assert len(receipts) == 2
    assert receipts[1]["counts_toward_25_hour_window"] is True
    assert receipts[1]["previous_receipt_sha256"] == receipts[0]["receipt_sha256"]
    restarted.stop()


def test_late_poll_records_actual_time_and_does_not_repeat_last_100_events(
    tmp_path: Path,
) -> None:
    clock = FakeClock(datetime(2026, 8, 29, 0, 0, tzinfo=timezone.utc))

    class FillProvider(FakeSnapshotProvider):
        def read_snapshot(self) -> dict[str, object]:
            snapshot = super().read_snapshot()
            snapshot["fills"] = [
                {
                    "fill_id": "fill-1",
                    "timestamp": "2026-08-29T00:45:00+00:00",
                }
            ]
            return snapshot

    runner = BTCPrivateReadonlyObservationRunner(
        config=_config(tmp_path),
        snapshot_provider=FillProvider(),
        private_ws=FakePrivateWS(),
        clock=clock,
    )
    runner.start()
    clock.value = datetime(2026, 8, 29, 1, 5, tzinfo=timezone.utc)
    runner.poll()
    clock.value = datetime(2026, 8, 29, 2, 5, tzinfo=timezone.utc)
    runner.poll()
    receipts = load_observation_receipt_ledger(
        tmp_path / "observation" / "hourly_observation_receipts.jsonl"
    )
    assert receipts[0]["observed_at_utc"] == "2026-08-29T01:05:00+00:00"
    assert receipts[0]["observation_hour_utc"] == "2026-08-29T01:00:00+00:00"
    assert receipts[0]["fill_count"] == 1
    assert receipts[0]["funding"]["observation_count"] == 1
    assert receipts[0]["funding"]["cashflow"] == 0.25
    assert receipts[1]["fill_count"] == 0
    assert receipts[1]["funding"]["observation_count"] == 0
    assert receipts[1]["funding"]["cashflow"] == 0.0
    runner.stop()


def test_invalid_event_timestamp_blocks_hour_without_manufacturing_outage(
    tmp_path: Path,
) -> None:
    clock = FakeClock(datetime(2026, 8, 29, 0, 0, tzinfo=timezone.utc))

    class InvalidTimestampProvider(FakeSnapshotProvider):
        def read_snapshot(self) -> dict[str, object]:
            snapshot = super().read_snapshot()
            snapshot["bills"][0].pop("timestamp")
            return snapshot

    runner = BTCPrivateReadonlyObservationRunner(
        config=_config(tmp_path),
        snapshot_provider=InvalidTimestampProvider(),
        private_ws=FakePrivateWS(),
        clock=clock,
    )
    runner.start()
    clock.value += timedelta(hours=1)
    runner.poll()
    receipt = load_observation_receipt_ledger(
        tmp_path / "observation" / "hourly_observation_receipts.jsonl"
    )[0]
    assert receipt["counts_toward_25_hour_window"] is False
    assert "private_readonly_funding_timestamp_invalid" in receipt["gap_flags"]
    assert receipt["outage_count"] == 0
    assert receipt["reconciliation_status"] == "reconciled"
    runner.stop()


@pytest.mark.parametrize("permission", [None, "", "trade", "read_only,trade", "withdraw"])
def test_unknown_or_write_account_permission_blocks_without_persisting_raw_permission(
    tmp_path: Path,
    permission: str | None,
) -> None:
    runner = BTCPrivateReadonlyObservationRunner(
        config=_config(tmp_path),
        snapshot_provider=FakeSnapshotProvider(permission=permission),
        private_ws=FakePrivateWS(),
    )
    with pytest.raises(
        BTCPrivateReadonlyObservationError,
        match="private_readonly_start_reconciliation_failed",
    ):
        runner.start()
    state = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    if permission:
        assert permission not in _string_values(state)
    assert state["reconciliation"]["permission"]["readonly_proven"] is False
    assert any(
        blocker.startswith("private_readonly_account_permission_")
        for blocker in state["blockers"]
    )


def test_private_get_rejects_http_failure_even_when_venue_code_is_zero() -> None:
    response = OkxDemoResponse(
        method="GET",
        path="/api/v5/account/config",
        http_status=503,
        code="0",
        message="",
        data=({"perm": "read_only"},),
    )

    with pytest.raises(
        BTCPrivateReadonlyObservationError,
        match="private_readonly_get_response_invalid",
    ) as captured:
        _response_rows(response, path="/api/v5/account/config")
    assert captured.value.safe_error is not None
    assert captured.value.safe_error.http_status == 503
    assert captured.value.safe_error.okx_code == "0"


@pytest.mark.parametrize(
    ("code", "expected_demo_status", "expected_clock_status"),
    [
        ("50101", "environment_mismatch", "unverified"),
        ("50102", "simulated_trading", "timestamp_expired"),
        ("50113", "simulated_trading", "unverified"),
        ("50110", "simulated_trading", "unverified"),
    ],
)
def test_private_get_safe_error_preserves_only_bounded_venue_diagnostics(
    code: str,
    expected_demo_status: str,
    expected_clock_status: str,
) -> None:
    response = OkxDemoResponse(
        method="GET",
        path="/api/v5/account/config?credential=must-not-persist",
        http_status=401,
        code=code,
        message="venue authentication rejected",
        data=({"account": "must-not-persist"},),
    )

    with pytest.raises(BTCPrivateReadonlyObservationError) as captured:
        _response_rows(response, path="/api/v5/account/config")

    safe_error = captured.value.safe_error
    assert isinstance(safe_error, PrivateReadonlySafeError)
    payload = safe_error.to_dict()
    assert set(payload) == {
        "endpoint",
        "http_status",
        "okx_code",
        "message",
        "demo_status",
        "region",
        "clock_status",
    }
    assert payload == {
        "endpoint": "/api/v5/account/config",
        "http_status": 401,
        "okx_code": code,
        "message": "venue authentication rejected",
        "demo_status": expected_demo_status,
        "region": "global",
        "clock_status": expected_clock_status,
    }
    serialized = json.dumps(payload, sort_keys=True)
    assert "credential" not in serialized
    assert "must-not-persist" not in serialized


@pytest.mark.parametrize("code", ["50101", "50102", "50113", "50110"])
def test_failed_snapshot_persists_safe_blocked_state_before_private_ws(
    tmp_path: Path,
    code: str,
) -> None:
    secret_literals = {
        "FAKE_API_KEY_123",
        "FAKE_SECRET_456",
        "FAKE_PASSPHRASE_789",
        "FAKE_SIGNATURE_012",
        "FAKE_TOKEN_345",
        "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
    }
    message = (
        "api_key=FAKE_API_KEY_123 secret=FAKE_SECRET_456 "
        "passphrase=FAKE_PASSPHRASE_789 signature=FAKE_SIGNATURE_012 "
        "token=FAKE_TOKEN_345\nABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    )
    response = OkxDemoResponse(
        method="GET",
        path="/api/v5/account/config",
        http_status=401,
        code=code,
        message=message,
    )
    ws = FakePrivateWS()
    runner = BTCPrivateReadonlyObservationRunner(
        config=_config(tmp_path),
        snapshot_provider=FakeErrorSnapshotProvider(response),
        private_ws=ws,
    )

    with pytest.raises(
        BTCPrivateReadonlyObservationError,
        match="private_readonly_snapshot_failed",
    ) as captured:
        runner.start()

    assert ws.started is False
    state_text = (tmp_path / "state.json").read_text(encoding="utf-8")
    state = json.loads(state_text)
    assert state["phase"] == "blocked"
    assert state["blockers"] == ["private_readonly_snapshot_failed"]
    assert set(state["safe_error"]) == {
        "endpoint",
        "http_status",
        "okx_code",
        "message",
        "demo_status",
        "region",
        "clock_status",
    }
    assert state["safe_error"]["okx_code"] == code
    assert len(state["safe_error"]["message"]) <= 160
    assert "\n" not in state["safe_error"]["message"]
    assert captured.value.safe_error is not None
    for secret in secret_literals:
        assert secret not in state_text
        assert secret not in repr(captured.value)
    assert state["safety"]["allow_demo_orders"] is False
    assert state["safety"]["allow_demo_cancels"] is False


def test_cli_emits_one_redacted_structured_error_to_stderr(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.run_btc_demo_private_readonly_observation as entrypoint

    safe_error = PrivateReadonlySafeError(
        endpoint="/api/v5/account/config",
        http_status=401,
        okx_code="50113",
        message="<redacted>",
        demo_status="simulated_trading",
        region="global",
        clock_status="unverified",
    )

    class FailingRunner:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def start(self) -> dict[str, object]:
            raise BTCPrivateReadonlyObservationError(
                "private_readonly_snapshot_failed",
                safe_error=safe_error,
            )

        def stop(self) -> dict[str, object]:
            return {"stopped": True}

    monkeypatch.setattr(
        entrypoint,
        "authorize_runner_process",
        lambda **_kwargs: entrypoint.RunnerProcessAuthorization(
            True,
            "private_readonly_runner_process_authorized",
            receipt_id="a" * 32,
            source_head=HEAD,
            runner_git_blob="b" * 40,
            runner_sha256="c" * 64,
            runtime_root=tmp_path,
            run_id="offline-cli-failure-test",
            confirmation=entrypoint.CONFIRMATION,
            authorization_ticket_hash="d" * 64,
        ),
    )
    monkeypatch.setattr(
        entrypoint,
        "load_windows_keyring_credentials",
        lambda _service: object(),
    )
    monkeypatch.setattr(entrypoint, "OkxDemoReadOnlyClient", lambda **_kwargs: object())
    monkeypatch.setattr(
        entrypoint,
        "OkxDemoPrivateReadObservationProvider",
        lambda _client: object(),
    )
    monkeypatch.setattr(
        entrypoint,
        "OkxDemoPrivateReadonlyWSAdapter",
        lambda _factory: object(),
    )
    monkeypatch.setattr(entrypoint, "BTCPrivateReadonlyObservationRunner", FailingRunner)

    assert entrypoint.main(argv=[], run_once=True) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    lines = captured.err.splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload == {
        "error_code": "private_readonly_snapshot_failed",
        "safe_error": safe_error.to_dict(),
    }
    assert "Traceback" not in captured.err
    assert "a" * 32 not in captured.err


def test_dedicated_entrypoint_registers_only_readonly_client_and_no_regular_start() -> None:
    path = Path("scripts/run_btc_demo_private_readonly_observation.py")
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_names = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    assert "OkxDemoReadOnlyClient" in imported_names
    assert "OkxDemoClient" not in imported_names
    assert "OkxDemoPaperRuntime" not in imported_names
    assert "start_btc_demo" not in source
    assert "allow_demo_orders=False" in source
    assert "allow_demo_cancels=False" in source
    assert "--private-authorization-ticket" not in source
    assert source.index("authorize_runner_process(") < source.index(
        "load_windows_keyring_credentials("
    )


def test_dedicated_entrypoint_accepts_zero_security_arguments() -> None:
    import scripts.run_btc_demo_private_readonly_observation as entrypoint

    args = entrypoint._parse_args([])

    assert vars(args) == {}


def test_dedicated_entrypoint_denial_precedes_keyring_and_provider(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.run_btc_demo_private_readonly_observation as entrypoint

    monkeypatch.setattr(
        entrypoint,
        "authorize_runner_process",
        lambda **_kwargs: entrypoint.RunnerProcessAuthorization(
            False, "private_readonly_receipt_expired"
        ),
    )
    monkeypatch.setattr(
        entrypoint,
        "load_windows_keyring_credentials",
        lambda _service: pytest.fail("keyring must remain unreachable"),
    )
    monkeypatch.setattr(
        entrypoint,
        "OkxDemoReadOnlyClient",
        lambda **_kwargs: pytest.fail("provider/network must remain unreachable"),
    )

    assert entrypoint.main(argv=[], run_once=True) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err) == {
        "error_code": "private_readonly_receipt_expired"
    }
