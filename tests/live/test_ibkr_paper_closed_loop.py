from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import jsonschema
import pytest

from quant_us.core.enums import SignalDirection
from quant_us.core.events import MarketEvent
from quant_us.core.types import Signal
from quant_us.core.enums import OrderSide, OrderType, TimeInForce
from quant_us.core.types import OrderIntent
from quant_us.execution.ibkr_paper_execution_adapter import IBKRAdapterError, account_id_hash
from quant_us.execution.ibkr_insync_facade import IBInsyncClientFacade
from quant_us.live.ibkr_runtime_market_data import (
    IBKRRuntimeMarketDataAdapter,
    IBKRRuntimeMarketDataConfig,
    stable_payload_sha256,
)
from quant_us.live.paper_runtime import PaperRuntime, PaperRuntimeConfig, PaperSessionMetrics
from quant_us.risk.pre_trade import PreTradeRiskConfig, PreTradeRiskEngine
from quant_us.risk.data_freshness import DataFreshnessConfig, DataFreshnessGuard
from quant_us.strategies.base import Strategy, StrategyContext
from scripts.run_us_equity_ibkr_paper import compose_ibkr_paper_runtime, main as cli_main


ACCOUNT_ID = "DU-OFFLINE-REPLAY-01"
HEAD = "a" * 40
CLOSE = datetime(2026, 8, 6, 20, 0, tzinfo=timezone.utc)


class OfflineExecutionClient:
    offline_replay = True
    network_access = False

    def __init__(self) -> None:
        self.connected = False
        self.connect_calls: list[dict[str, object]] = []
        self.disconnect_calls = 0
        self.place_order_calls: list[tuple[object, object]] = []
        self.cancel_order_calls: list[object] = []
        self.trades: list[SimpleNamespace] = []
        self.fill_rows: list[SimpleNamespace] = []
        self.cash = 100_000.0
        self.positions_by_symbol: dict[str, tuple[float, float]] = {}
        self.next_order_id = 900

    def connect(
        self,
        host: str,
        port: int,
        *,
        clientId: int,
        readonly: bool,
        timeout: float,
    ) -> bool:
        self.connect_calls.append(
            {
                "host": host,
                "port": port,
                "clientId": clientId,
                "readonly": readonly,
                "timeout": timeout,
            }
        )
        self.connected = True
        return True

    def disconnect(self) -> None:
        self.disconnect_calls += 1
        self.connected = False

    def isConnected(self) -> bool:
        return self.connected

    def accountSummary(self) -> list[SimpleNamespace]:
        equity = self.cash + sum(quantity * price for quantity, price in self.positions_by_symbol.values())
        return [
            SimpleNamespace(account=ACCOUNT_ID, tag="TotalCashValue", value=str(self.cash)),
            SimpleNamespace(account=ACCOUNT_ID, tag="NetLiquidation", value=str(equity)),
            SimpleNamespace(account=ACCOUNT_ID, tag="BuyingPower", value=str(max(0.0, self.cash * 2))),
        ]

    def positions(self) -> list[SimpleNamespace]:
        return [
            SimpleNamespace(
                contract=SimpleNamespace(symbol=symbol),
                position=quantity,
                avgCost=price,
                marketPrice=price,
                unrealizedPNL=0.0,
            )
            for symbol, (quantity, price) in self.positions_by_symbol.items()
        ]

    def openTrades(self) -> list[SimpleNamespace]:
        return list(self.trades)

    def fills(self) -> list[SimpleNamespace]:
        return list(self.fill_rows)

    def placeOrder(self, contract: object, payload: object) -> SimpleNamespace:
        self.place_order_calls.append((contract, payload))
        order_id = self.next_order_id
        self.next_order_id += 1
        quantity = float(getattr(payload, "totalQuantity"))
        price = 505.0
        commission = 1.25
        self.cash -= quantity * price + commission
        self.positions_by_symbol[str(getattr(contract, "symbol"))] = (quantity, price)
        response = SimpleNamespace(
            contract=contract,
            order=SimpleNamespace(
                orderId=order_id,
                action=getattr(payload, "action"),
                totalQuantity=quantity,
                orderType=getattr(payload, "orderType"),
                tif=getattr(payload, "tif"),
                lmtPrice=getattr(payload, "lmtPrice"),
                orderRef=getattr(payload, "orderRef"),
            ),
            orderStatus=SimpleNamespace(
                status="Filled",
                filled=quantity,
                remaining=0.0,
                avgFillPrice=price,
            ),
        )
        self.trades.append(response)
        self.fill_rows.append(
            SimpleNamespace(
                contract=contract,
                execution=SimpleNamespace(
                    execId=f"exec-{order_id}",
                    orderId=order_id,
                    side="BOT",
                    shares=quantity,
                    price=price,
                    time=CLOSE,
                ),
                commissionReport=SimpleNamespace(commission=commission),
            )
        )
        return response

    def cancelOrder(self, payload: object) -> SimpleNamespace:
        self.cancel_order_calls.append(payload)
        return SimpleNamespace(orderStatus=SimpleNamespace(status="Cancelled"))


class OfflineMarketDataClient:
    def __init__(self) -> None:
        self.connected = True
        self.connect_calls = 0
        self.rows = [_market_bar()]

    def isConnected(self) -> bool:
        return self.connected

    def connect(self, *_args: object, **_kwargs: object) -> None:
        self.connect_calls += 1

    def poll_completed_bars(self) -> list[dict[str, object]]:
        rows, self.rows = self.rows, []
        return rows


class OneSignalStrategy(Strategy):
    strategy_id = "offline-chain-strategy"

    def on_bar(self, event: MarketEvent, context: StrategyContext) -> list[Signal]:
        return [
            Signal(
                timestamp_utc=event.timestamp_utc,
                strategy_id=self.strategy_id,
                symbol=event.bar.symbol,
                direction=SignalDirection.LONG,
                strength=1.0,
                horizon="1d",
                reason="offline_closed_loop_fixture",
            )
        ]


class BrokerCallingStrategy(Strategy):
    strategy_id = "forbidden-broker-caller"

    def __init__(self, broker: object) -> None:
        self.broker = broker

    def on_bar(self, event: MarketEvent, context: StrategyContext) -> list[Signal]:
        self.broker.submit_order(None)
        return []


def _market_bar() -> dict[str, object]:
    provenance = "IBKR_ADJUSTED_LAST_OFFLINE_REPLAY"
    row: dict[str, object] = {
        "contract": SimpleNamespace(
            conId=320227571,
            symbol="QQQ",
            secType="STK",
            exchange="SMART",
            currency="USD",
        ),
        "event_timestamp_utc": CLOSE,
        "receive_timestamp_utc": CLOSE + timedelta(seconds=1),
        "source_sequence": 1,
        "connection_epoch": "offline-epoch-1",
        "source_identity": "IBKR-OFFLINE-REPLAY",
        "market_data_type": 1,
        "completed": True,
        "session": "regular",
        "open": 500.0,
        "high": 506.0,
        "low": 498.0,
        "close": 505.0,
        "volume": 10_000.0,
        "adjusted": True,
        "corporate_action_status": "normalized",
        "corporate_action_entitlement_verified": True,
        "semantic_parity_verified": True,
        "normalization_provenance": provenance,
    }
    row["normalization_sha256"] = stable_payload_sha256(
        {
            "identity": {
                "conId": 320227571,
                "symbol": "QQQ",
                "secType": "STK",
                "exchange": "SMART",
                "currency": "USD",
            },
            "trading_date_et": "2026-08-06",
            "open": 500.0,
            "high": 506.0,
            "low": 498.0,
            "close": 505.0,
            "volume": 10_000.0,
            "provenance": provenance,
        }
    )
    return row


def _runtime(tmp_path: Path) -> tuple[PaperRuntime, OfflineExecutionClient, OfflineMarketDataClient]:
    execution_client = OfflineExecutionClient()
    market_client = OfflineMarketDataClient()
    config = PaperRuntimeConfig(
        symbols=["QQQ"],
        strategy_id=OneSignalStrategy.strategy_id,
        capital=100_000.0,
        paper_broker="ibkr_paper",
        data_vendor="ibkr",
        bar_size="1d",
        bar_sizes=["1d"],
        ledger_root=str(tmp_path / "ledger"),
        data_root=str(tmp_path / "data"),
        audit_log_path=str(tmp_path / "audit" / "runtime.jsonl"),
        submit_orders=True,
        explicit_paper_submit=True,
        allow_live_orders=False,
        ibkr_port=4002,
        ibkr_client_id=77,
        ibkr_adapter_mode="paper-submit",
        ibkr_account_hash_allowlist=(account_id_hash(ACCOUNT_ID),),
        ibkr_connect_on_bootstrap=True,
        ibkr_offline_replay=True,
    )

    def market_factory() -> IBKRRuntimeMarketDataAdapter:
        return IBKRRuntimeMarketDataAdapter(
            IBKRRuntimeMarketDataConfig(
                symbols=("QQQ",),
                bar_size="1d",
                corporate_action_entitlement_verified=True,
            ),
            client=market_client,
            now=lambda: CLOSE + timedelta(seconds=2),
        )

    runtime = PaperRuntime(
        config,
        ibkr_paper_client_factory=lambda: execution_client,
        ibkr_market_data_adapter_factory=market_factory,
        runtime_head_resolver=lambda: HEAD,
        registered_main_head_resolver=lambda: HEAD,
    )
    return runtime, execution_client, market_client


def test_fake_ibkr_event_to_strategy_risk_oms_fill_ledger_reconciliation_receipt(
    tmp_path: Path,
) -> None:
    runtime, execution_client, market_client = _runtime(tmp_path)

    with patch.dict("os.environ", {"QUANT_ENABLE_IBKR_PAPER_ADAPTER": "true"}, clear=True):
        runtime.bootstrap(strategy=OneSignalStrategy())
        assert runtime.data_loop.run_once().fresh is True
        bars = runtime._new_bars_from_cache()
        assert len(bars) == 1

        runtime.config.ibkr_offline_replay = False
        external_allowed, external_reason, _ = runtime._paper_submit_gate_allows(
            OrderIntent(
                timestamp_utc=CLOSE,
                strategy_id=OneSignalStrategy.strategy_id,
                symbol="QQQ",
                side=OrderSide.BUY,
                quantity=1.0,
                order_type=OrderType.MARKET,
                time_in_force=TimeInForce.DAY,
            )
        )
        assert external_allowed is False
        assert "ibkr_integration_receipt_missing" in external_reason
        assert "ibkr_operator_paper_submit_authorization_missing" in external_reason
        runtime.config.ibkr_offline_replay = True

        # The frozen daily decision is normally scheduled for the next bar.
        # This injected offline fixture isolates the risk/OMS/execution chain.
        risk = PreTradeRiskEngine(PreTradeRiskConfig(skip_session_check=True))
        runtime.risk_engine = risk
        runtime.oms.risk_engine = risk
        runtime.data_freshness = DataFreshnessGuard(
            DataFreshnessConfig(max_delay_seconds=10**9)
        )
        metrics = PaperSessionMetrics()
        runtime._process_bars(bars, metrics)
        runtime._sync_ibkr_execution_updates(stage="offline_test")
        runtime.on_session_close()

    orders = runtime.ledger.read_records("orders.jsonl")
    fills = runtime.ledger.read_records("fills.jsonl")
    receipt_path = Path(runtime.config.ledger_root) / "audit" / "ibkr_paper_closed_loop_receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    schema = json.loads(
        Path("schemas/us_ibkr_paper_closed_loop_receipt.schema.json").read_text(encoding="utf-8")
    )
    jsonschema.Draft202012Validator(schema).validate(receipt)

    assert metrics.signals_generated == 1
    assert metrics.intents_created == 1
    assert metrics.intents_submitted == 1
    assert len(execution_client.place_order_calls) == 1
    assert len(fills) == 1
    assert orders[-1]["status"] == "filled"
    assert runtime._last_reconciliation_summary["status"] == "clean"
    assert receipt["ledger"]["state_derived_from_fills_cash_positions"] is True
    assert receipt["counts_toward_30_day_window"] is False
    assert all(value is False for value in receipt["safety_flags"].values())
    assert receipt["broker"]["gateway_connected"] is False
    assert receipt["runtime"]["connection_kind"] == "offline_replay"
    unsigned = dict(receipt)
    expected_hash = unsigned.pop("receipt_sha256")
    actual_hash = hashlib.sha256(
        json.dumps(unsigned, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()
    assert actual_hash == expected_hash
    assert market_client.connect_calls == 0
    assert execution_client.cancel_order_calls == []
    assert not hasattr(execution_client, "globalCancel")
    runtime.shutdown()


def test_runtime_rejects_strategy_that_holds_direct_broker_reference(tmp_path: Path) -> None:
    runtime, _, _ = _runtime(tmp_path)
    runtime.broker = object()
    runtime.strategies = [BrokerCallingStrategy(runtime.broker)]

    with pytest.raises(TypeError, match="paper_runtime_strategy_broker_reference_forbidden"):
        runtime._validate_strategy_broker_isolation()


def test_missing_integration_receipt_and_operator_authority_keep_external_submit_closed(
    tmp_path: Path,
) -> None:
    runtime, _, _ = _runtime(tmp_path)
    runtime.config.ibkr_offline_replay = False
    runtime.config.ibkr_operator_paper_submit_authorized = False

    status = runtime._ibkr_integration_receipt_status()

    assert status["ok"] is False
    assert status["reason"] == "ibkr_integration_receipt_missing"


def test_integration_receipt_head_binding_accepts_current_envelope_parent() -> None:
    deliverable = "a" * 40
    envelope = "b" * 40

    assert (
        PaperRuntime._ibkr_integration_receipt_head_binding_mode(
            receipt_head=deliverable,
            current_head=envelope,
            receipt_commit=envelope,
            receipt_parent=deliverable,
        )
        == "current_envelope_parent"
    )


@pytest.mark.parametrize(
    ("receipt_head", "current_head", "receipt_commit", "receipt_parent"),
    [
        ("a" * 40, "c" * 40, "b" * 40, "a" * 40),
        ("a" * 40, "b" * 40, "b" * 40, "c" * 40),
        ("", "b" * 40, "b" * 40, "a" * 40),
    ],
)
def test_integration_receipt_head_binding_rejects_stale_or_unrelated_envelope(
    receipt_head: str,
    current_head: str,
    receipt_commit: str,
    receipt_parent: str,
) -> None:
    assert (
        PaperRuntime._ibkr_integration_receipt_head_binding_mode(
            receipt_head=receipt_head,
            current_head=current_head,
            receipt_commit=receipt_commit,
            receipt_parent=receipt_parent,
        )
        == ""
    )


def test_forged_untracked_integration_receipt_fails_closed(tmp_path: Path) -> None:
    runtime, _, _ = _runtime(tmp_path)
    receipt_path = tmp_path / "integrated-receipt.json"
    receipt_path.write_text(
        json.dumps(
            {
                "event_type": "integrated",
                "integrated_head": "b" * 40,
                "event_id": "integrated-us-ibkr-offline-fixture",
            }
        ),
        encoding="utf-8",
    )
    runtime.config.ibkr_integration_receipt_path = str(receipt_path)

    status = runtime._ibkr_integration_receipt_status()

    assert status["ok"] is False
    assert status["reason"] == "ibkr_integration_receipt_outside_repo"
    assert status["current_head"] == HEAD


def test_tracked_published_handoff_cannot_impersonate_integrated_receipt(tmp_path: Path) -> None:
    runtime, _, _ = _runtime(tmp_path)
    current_head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    receipt_path = Path(
        ".agent/handoffs/US-IBKR-REALTIME-PAPER-CLOSED-LOOP-01/"
        "published-us-ibkr-realtime-paper-closed-loop-01-0e40d88ce.json"
    ).resolve()
    runtime.config.ibkr_integration_receipt_path = str(receipt_path)
    runtime._runtime_head_resolver = lambda: current_head

    status = runtime._ibkr_integration_receipt_status()

    assert status["ok"] is False
    assert "ibkr_integration_receipt_event_type_mismatch" in status["reasons"]
    assert "ibkr_integration_receipt_role_mismatch" in status["reasons"]
    assert "ibkr_integration_receipt_ticket_mismatch" in status["reasons"]


def test_conflicting_duplicate_fill_halts_runtime_fail_closed(tmp_path: Path) -> None:
    runtime, execution_client, _ = _runtime(tmp_path)
    with patch.dict("os.environ", {"QUANT_ENABLE_IBKR_PAPER_ADAPTER": "true"}, clear=True):
        runtime.bootstrap(strategy=OneSignalStrategy())
        assert runtime.data_loop.run_once().fresh is True
        bars = runtime._new_bars_from_cache()
        risk = PreTradeRiskEngine(PreTradeRiskConfig(skip_session_check=True))
        runtime.risk_engine = risk
        runtime.oms.risk_engine = risk
        runtime.data_freshness = DataFreshnessGuard(
            DataFreshnessConfig(max_delay_seconds=10**9)
        )
        runtime._process_bars(bars, PaperSessionMetrics())
        runtime._sync_ibkr_execution_updates(stage="first_fill")
        execution_client.fill_rows[0].commissionReport.commission = 9.99

        with pytest.raises(IBKRAdapterError, match="duplicate_fill_conflict"):
            runtime._sync_ibkr_execution_updates(stage="conflicting_duplicate")

    assert runtime._halt_reconciliation is True
    assert runtime.oms.reduce_only is True
    assert runtime.kill_switch.triggered is True


def test_broker_disconnect_halts_new_orders_fail_closed(tmp_path: Path) -> None:
    runtime, execution_client, _ = _runtime(tmp_path)
    with patch.dict("os.environ", {"QUANT_ENABLE_IBKR_PAPER_ADAPTER": "true"}, clear=True):
        runtime.bootstrap(strategy=OneSignalStrategy())
        execution_client.disconnect()
        with pytest.raises(RuntimeError, match="ibkr_paper_client_not_connected"):
            runtime._sync_ibkr_execution_updates(stage="disconnect_test")

    assert runtime._halt_reconciliation is True
    assert runtime.oms.reduce_only is True
    assert runtime.kill_switch.triggered is True


def test_composition_and_cli_are_local_only_and_live_ports_are_rejected(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    execution_client = OfflineExecutionClient()
    market_client = OfflineMarketDataClient()
    runtime = compose_ibkr_paper_runtime(
        paper_client_factory=lambda: execution_client,
        market_data_client_factory=lambda: market_client,
        market_data_contract_factory=lambda symbol: SimpleNamespace(symbol=symbol),
        account_hash_allowlist=(account_id_hash(ACCOUNT_ID),),
        ledger_root=tmp_path / "ledger",
        data_root=tmp_path / "data",
    )

    assert execution_client.connect_calls == []
    assert market_client.connect_calls == 0
    assert runtime.config.ibkr_adapter_mode == "disabled"
    assert cli_main(["describe-runtime", "--mode", "readonly", "--port", "7497"]) == 0
    described = json.loads(capsys.readouterr().out)
    assert described["gateway_connected"] is False
    assert described["paper_submit_allowed"] is False
    with pytest.raises(ValueError, match="ibkr_live_endpoint_forbidden"):
        compose_ibkr_paper_runtime(
            paper_client_factory=lambda: execution_client,
            market_data_client_factory=lambda: market_client,
            market_data_contract_factory=lambda symbol: SimpleNamespace(symbol=symbol),
            account_hash_allowlist=(account_id_hash(ACCOUNT_ID),),
            ledger_root=tmp_path / "other-ledger",
            data_root=tmp_path / "other-data",
            port=4001,
        )


class FakeIBInsync:
    def __init__(self) -> None:
        self.connect_calls: list[tuple[object, ...]] = []
        self.place_calls: list[tuple[object, object]] = []
        self.cancel_calls: list[object] = []

    def connect(self, *args: object, **kwargs: object) -> bool:
        self.connect_calls.append((*args, kwargs))
        return True

    def disconnect(self) -> None:
        return None

    def isConnected(self) -> bool:
        return False

    def placeOrder(self, contract: object, order: object) -> SimpleNamespace:
        self.place_calls.append((contract, order))
        return SimpleNamespace()

    def cancelOrder(self, order: object) -> SimpleNamespace:
        self.cancel_calls.append(order)
        return SimpleNamespace()

    def openTrades(self) -> list[object]:
        return []


def test_ib_insync_facade_construction_is_disconnected_and_translates_payloads() -> None:
    ib = FakeIBInsync()
    facade = IBInsyncClientFacade(
        ib=ib,
        stock_factory=lambda symbol, exchange, currency: SimpleNamespace(
            symbol=symbol, exchange=exchange, currency=currency
        ),
        order_factory=lambda **kwargs: SimpleNamespace(**kwargs),
    )
    from quant_us.execution.ibkr_paper_execution_adapter import (
        IBKRCancelPayload,
        IBKRContractPayload,
        IBKROrderPayload,
    )

    assert ib.connect_calls == []
    facade.placeOrder(
        IBKRContractPayload(symbol="QQQ"),
        IBKROrderPayload(
            action="BUY",
            totalQuantity=1.0,
            orderType="MKT",
            tif="DAY",
            orderRef="paper-test",
        ),
    )
    facade.cancelOrder(IBKRCancelPayload(orderId="7"))

    assert ib.place_calls[0][0].symbol == "QQQ"
    assert ib.place_calls[0][1].orderRef == "paper-test"
    assert ib.cancel_calls[0].orderId == 7
