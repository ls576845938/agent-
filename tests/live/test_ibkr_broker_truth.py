from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from quant_us.execution.ibkr_broker_truth import (
    BrokerExecutionIdentity,
    BrokerExecutionTruth,
    BrokerOrderIdentity,
    BrokerTruthSnapshot,
    account_id_hash,
    map_broker_execution_identity,
    map_broker_order_identity,
)
from quant_us.execution.ibkr_paper_execution_adapter import (
    IBKRAdapterError,
    IBKRPaperAdapterMode,
    IBKRPaperExecutionAdapter,
    IBKRPaperExecutionConfig,
)


ACCOUNT_ID = "DU-PAPER-TRUTH-001"


class FakeBrokerTruthClient:
    def __init__(self, *, connection_error: str | None = None) -> None:
        self.account_id = ACCOUNT_ID
        self.connected = False
        self.connection_error = connection_error
        self.connect_calls = 0
        self.disconnect_calls = 0
        self.global_cancel_calls = 0
        self.open_orders = [
            SimpleNamespace(
                contract=SimpleNamespace(symbol="AAPL"),
                order=SimpleNamespace(
                    orderId=17,
                    permId=1700,
                    clientId=11,
                    action="BUY",
                    totalQuantity=2,
                    orderType="MKT",
                    tif="DAY",
                    orderRef="strategy-order-17",
                ),
                orderStatus=SimpleNamespace(status="Submitted", filled=0, remaining=2, sequence=8),
                connection_epoch=1,
            )
        ]
        self.execution_rows = [
            SimpleNamespace(
                contract=SimpleNamespace(symbol="AAPL"),
                execution=SimpleNamespace(
                    execId="exec-17",
                    orderId=17,
                    permId=1700,
                    clientId=11,
                    side="BOT",
                    shares=1,
                    price=190.25,
                    time=datetime(2026, 8, 7, 1, 0, tzinfo=timezone.utc),
                    sequence=9,
                ),
                commissionReport=SimpleNamespace(commission=0.15),
            )
        ]
        self.position_rows = [
            SimpleNamespace(
                contract=SimpleNamespace(symbol="AAPL"),
                position=1,
                avgCost=190.25,
                marketPrice=191.0,
                unrealizedPNL=0.75,
                sequence=10,
            )
        ]

    def connect(self, host: str, port: int, *, clientId: int, readonly: bool, timeout: float) -> bool:
        del host, port, clientId, readonly, timeout
        self.connect_calls += 1
        if self.connection_error:
            raise RuntimeError(self.connection_error)
        self.connected = True
        return True

    def disconnect(self) -> None:
        self.disconnect_calls += 1
        self.connected = False

    def isConnected(self) -> bool:
        return self.connected

    def accountSummary(self) -> list[SimpleNamespace]:
        return [
            SimpleNamespace(account=ACCOUNT_ID, tag="TotalCashValue", value="10000"),
            SimpleNamespace(account=ACCOUNT_ID, tag="NetLiquidation", value="12000"),
            SimpleNamespace(account=ACCOUNT_ID, tag="BuyingPower", value="20000"),
            SimpleNamespace(account=ACCOUNT_ID, tag="MaintMarginReq", value="3000"),
        ]

    def openTrades(self) -> list[SimpleNamespace]:
        return list(self.open_orders)

    def fills(self) -> list[SimpleNamespace]:
        return list(self.execution_rows)

    def positions(self) -> list[SimpleNamespace]:
        return list(self.position_rows)

    def reqGlobalCancel(self) -> dict[str, object]:
        self.global_cancel_calls += 1
        return {"accepted": True}


def _adapter(client: FakeBrokerTruthClient, *, mode: IBKRPaperAdapterMode = IBKRPaperAdapterMode.READONLY) -> IBKRPaperExecutionAdapter:
    return IBKRPaperExecutionAdapter(
        IBKRPaperExecutionConfig(
            mode=mode,
            client_id=11,
            account_hash_allowlist=(account_id_hash(ACCOUNT_ID),),
            reconnect_attempts=3,
        ),
        client=client,
    )


def test_identity_mapping_keeps_client_and_perm_components_explicit() -> None:
    order = map_broker_order_identity(
        {"order": {"orderId": 17, "permId": 1700, "clientId": 11, "orderRef": "coid-17"}},
    )
    assert order.stable_key == "ibkr:11:perm:1700"
    assert BrokerOrderIdentity(ibkr_order_id="17").stable_key == ""

    execution = map_broker_execution_identity(
        {"execution": {"execId": "exec-17", "orderId": 17, "clientId": 11}},
    )
    assert execution.stable_key == "ibkr:11:exec:exec-17"
    assert isinstance(execution, BrokerExecutionIdentity)


def test_snapshot_semantics_are_immutable_and_public_model_has_hash_only() -> None:
    captured = datetime.now(timezone.utc)
    complete = BrokerTruthSnapshot(
        connection_epoch=4,
        captured_at=captured,
        broker_server_time=captured,
        client_id=11,
        account_hash=account_id_hash(ACCOUNT_ID),
        transport_connected=True,
        account_verified=True,
        open_orders=({"order": {"orderId": 17, "permId": 1700, "clientId": 11, "orderRef": "coid"}},),
        executions=({"execution": {"execId": "exec-1", "orderId": 17, "clientId": 11}},),
        positions=({"symbol": "AAPL", "position": 1},),
        cash=100.0,
        net_liquidation=120.0,
        buying_power=200.0,
        margin=20.0,
        orders_snapshot_complete=True,
        executions_snapshot_complete=True,
        positions_snapshot_complete=True,
        account_snapshot_complete=True,
        freshness="fresh",
    )
    assert complete.complete is True
    assert complete.status == "complete"
    public = complete.to_dict()
    assert public["account_hash"] == account_id_hash(ACCOUNT_ID)
    assert ACCOUNT_ID not in str(public)
    with pytest.raises(Exception):
        complete.status_flags += ("unexpected",)  # type: ignore[misc]


def test_snapshot_marks_incomplete_stale_sequence_duplicate_and_epoch_mismatch() -> None:
    old = datetime.now(timezone.utc) - timedelta(hours=1)
    stale = BrokerTruthSnapshot(
        captured_at=old,
        freshness="fresh",
        max_age_seconds=1,
        transport_connected=True,
        account_verified=True,
        account_hash=account_id_hash(ACCOUNT_ID),
    )
    assert stale.stale is True
    assert stale.incomplete is True

    gap = BrokerTruthSnapshot(
        connection_epoch=1,
        captured_at=datetime.now(timezone.utc),
        freshness="fresh",
        account_hash=account_id_hash(ACCOUNT_ID),
        transport_connected=True,
        account_verified=True,
        executions=(
            BrokerExecutionTruth(identity=BrokerExecutionIdentity(ibkr_exec_id="e1", client_id=1), sequence=1),
            BrokerExecutionTruth(identity=BrokerExecutionIdentity(ibkr_exec_id="e2", client_id=1), sequence=3),
        ),
        executions_snapshot_complete=True,
        account_snapshot_complete=True,
    )
    assert gap.sequence_gap is True

    duplicate = BrokerTruthSnapshot(
        connection_epoch=1,
        captured_at=datetime.now(timezone.utc),
        freshness="fresh",
        account_hash=account_id_hash(ACCOUNT_ID),
        transport_connected=True,
        account_verified=True,
        executions=(
            BrokerExecutionTruth(identity=BrokerExecutionIdentity(ibkr_exec_id="same", client_id=1)),
            BrokerExecutionTruth(identity=BrokerExecutionIdentity(ibkr_exec_id="same", client_id=1)),
        ),
        executions_snapshot_complete=True,
        account_snapshot_complete=True,
    )
    assert duplicate.duplicate is True

    epoch = BrokerTruthSnapshot(
        connection_epoch=1,
        expected_connection_epoch=2,
        captured_at=datetime.now(timezone.utc),
        freshness="fresh",
        account_hash=account_id_hash(ACCOUNT_ID),
        transport_connected=True,
        account_verified=True,
    )
    assert epoch.epoch_mismatch is True


def test_adapter_captures_truth_and_advances_epoch_only_after_verified_connect() -> None:
    client = FakeBrokerTruthClient()
    adapter = _adapter(client)
    assert adapter.connection_epoch == 0
    report = adapter.connect()
    assert report["connection_epoch"] == 1
    assert adapter.connection_epoch == 1
    snapshot = adapter.capture_broker_truth()
    assert snapshot.connection_epoch == 1
    assert snapshot.account_hash == account_id_hash(ACCOUNT_ID)
    assert snapshot.complete is True
    assert snapshot.open_orders[0].identity.stable_key == "ibkr:11:perm:1700"
    assert snapshot.executions[0].identity.stable_key == "ibkr:11:exec:exec-17"

    adapter.disconnect()
    assert client.global_cancel_calls == 0
    assert adapter.broker_truth_snapshot is None


@pytest.mark.parametrize("message", ["authentication failed", "configuration error"])
def test_nonrecoverable_reconnect_errors_stop_after_one_attempt(message: str) -> None:
    client = FakeBrokerTruthClient(connection_error=message)
    adapter = _adapter(client)
    with pytest.raises(IBKRAdapterError) as exc_info:
        adapter.reconnect(max_attempts=3)
    assert exc_info.value.code in {"authentication_failed", "configuration_error"}
    assert client.connect_calls == 1


def test_old_epoch_snapshot_is_rejected_fail_closed() -> None:
    client = FakeBrokerTruthClient()
    adapter = _adapter(client)
    adapter.connect()
    old = BrokerTruthSnapshot(
        connection_epoch=0,
        captured_at=datetime.now(timezone.utc),
        freshness="fresh",
        account_hash=account_id_hash(ACCOUNT_ID),
        transport_connected=True,
        account_verified=True,
    )
    with pytest.raises(IBKRAdapterError, match="epoch_mismatch"):
        adapter.accept_broker_truth(old)


def test_global_cancel_is_explicit_and_requires_audit_authorization_confirmation_and_reconcile() -> None:
    client = FakeBrokerTruthClient()
    adapter = _adapter(client, mode=IBKRPaperAdapterMode.PAPER_SUBMIT)
    adapter.connect()
    audit: list[dict[str, object]] = []
    result = adapter.request_global_cancel(
        reason="operator emergency test",
        policy_authorized=True,
        operator_authorized=True,
        audit=audit.append,
        confirmation=True,
        reconciliation=True,
    )
    assert result["accepted"] is True
    assert result["confirmed"] is True
    assert result["reconciled"] is True
    assert client.global_cancel_calls == 1
    assert audit[0]["reason"] == "operator emergency test"
    adapter.disconnect()
    assert client.global_cancel_calls == 1


def test_global_cancel_without_confirmation_never_calls_broker() -> None:
    client = FakeBrokerTruthClient()
    adapter = _adapter(client, mode=IBKRPaperAdapterMode.PAPER_SUBMIT)
    adapter.connect()
    with pytest.raises(IBKRAdapterError, match="global_cancel_confirmation_required"):
        adapter.request_global_cancel(
            reason="missing confirmation",
            policy_authorized=True,
            operator_authorized=True,
            audit={},
            reconciliation=True,
        )
    assert client.global_cancel_calls == 0
