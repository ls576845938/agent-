from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from quant_us.live.ibkr_runtime_market_data import (
    IBKRMarketDataTransportConfig,
    IBKRRuntimeMarketDataAdapter,
    IBKRRuntimeMarketDataConfig,
    IBKRSDKNeutralMarketDataTransport,
    stable_payload_sha256,
)


class FakeMarketDataClient:
    def __init__(self) -> None:
        self.connected = True
        self.connect_calls = 0
        self.rows: list[dict[str, object]] = []

    def isConnected(self) -> bool:
        return self.connected

    def connect(self, *_args: object, **_kwargs: object) -> None:
        self.connect_calls += 1

    def poll_completed_bars(self) -> list[dict[str, object]]:
        rows, self.rows = self.rows, []
        return rows


def _bar(
    timestamp: datetime,
    *,
    sequence: int = 1,
    epoch: str = "epoch-1",
    market_data_type: object = 1,
    completed: bool = True,
    source: str = "IBKR-TWS",
    received_at: datetime | None = None,
    session: str = "regular",
    split_factor: float = 1.0,
    dividend: float = 0.0,
    corporate_action_status: str = "none_observed",
    adjusted: bool = True,
    semantic_parity_verified: bool = True,
    normalization_provenance: str = "IBKR_ADJUSTED_LAST_TEST",
    entitlement_verified: bool = True,
) -> dict[str, object]:
    row: dict[str, object] = {
        "contract": SimpleNamespace(
            conId=320227571,
            symbol="QQQ",
            secType="STK",
            exchange="SMART",
            currency="USD",
        ),
        "event_timestamp_utc": timestamp,
        "receive_timestamp_utc": received_at or timestamp + timedelta(seconds=1),
        "source_sequence": sequence,
        "connection_epoch": epoch,
        "source_identity": source,
        "market_data_type": market_data_type,
        "completed": completed,
        "session": session,
        "open": 500.0,
        "high": 506.0,
        "low": 498.0,
        "close": 505.0,
        "volume": 10_000.0,
        "split_factor": split_factor,
        "dividend": dividend,
        "corporate_action_status": corporate_action_status,
        "corporate_action_entitlement_verified": entitlement_verified,
        "adjusted": adjusted,
        "semantic_parity_verified": semantic_parity_verified,
        "normalization_provenance": normalization_provenance,
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
            "trading_date_et": timestamp.astimezone(ZoneInfo("America/New_York")).date().isoformat(),
            "open": 500.0,
            "high": 506.0,
            "low": 498.0,
            "close": 505.0,
            "volume": 10_000.0,
            "provenance": normalization_provenance,
        }
    )
    return row


def _adapter(client: FakeMarketDataClient, now: datetime) -> IBKRRuntimeMarketDataAdapter:
    return IBKRRuntimeMarketDataAdapter(
        IBKRRuntimeMarketDataConfig(
            symbols=("QQQ",),
            bar_size="1d",
            corporate_action_entitlement_verified=True,
        ),
        client=client,
        now=lambda: now,
    )


def test_import_constructor_and_default_state_never_connect_or_create_socket() -> None:
    client = FakeMarketDataClient()
    adapter = _adapter(client, datetime(2026, 8, 6, 20, 1, tzinfo=timezone.utc))

    assert client.connect_calls == 0
    assert adapter.last_status is None
    assert adapter.semantic_contract["contract"]["runtime_source"]["role"] == "runtime_only"


def test_unverified_corporate_action_entitlement_is_default_fail_closed() -> None:
    now = datetime(2026, 8, 6, 20, 1, tzinfo=timezone.utc)
    client = FakeMarketDataClient()
    client.rows = [
        _bar(
            datetime(2026, 8, 6, 20, 0, tzinfo=timezone.utc),
            entitlement_verified=False,
        )
    ]
    adapter = IBKRRuntimeMarketDataAdapter(
        IBKRRuntimeMarketDataConfig(symbols=("QQQ",), bar_size="1d"),
        client=client,
        now=lambda: now,
    )

    status = adapter.run_once()

    assert status.fresh is False
    assert "ibkr_corporate_action_entitlement_unverified" in status.blockers


@pytest.mark.parametrize("market_data_type", [2, 3, 4, "unknown"])
def test_delayed_frozen_and_unknown_market_data_fail_closed(market_data_type: object) -> None:
    now = datetime(2026, 8, 6, 20, 1, tzinfo=timezone.utc)
    client = FakeMarketDataClient()
    client.rows = [_bar(datetime(2026, 8, 6, 20, 0, tzinfo=timezone.utc), market_data_type=market_data_type)]

    status = _adapter(client, now).run_once()

    assert status.fresh is False
    assert any(reason.startswith("ibkr_market_data_type_not_live") for reason in status.blockers)


def test_stale_unknown_source_incomplete_and_future_bars_never_enter_runtime() -> None:
    now = datetime(2026, 8, 6, 20, 10, tzinfo=timezone.utc)
    client = FakeMarketDataClient()
    client.rows = [
        _bar(
            datetime(2026, 8, 6, 20, 0, tzinfo=timezone.utc),
            received_at=now - timedelta(minutes=6),
        ),
        _bar(datetime(2026, 8, 6, 20, 0, tzinfo=timezone.utc), sequence=2, source="Yahoo"),
        _bar(datetime(2026, 8, 6, 20, 0, tzinfo=timezone.utc), sequence=3, completed=False),
        _bar(datetime(2026, 8, 7, 20, 0, tzinfo=timezone.utc), sequence=4),
    ]
    adapter = _adapter(client, now)

    status = adapter.run_once()

    assert status.fresh is False
    assert adapter.fetch_latest_bars().empty
    assert "ibkr_market_data_stale" in status.blockers
    assert "ibkr_runtime_research_or_unknown_source_forbidden" in status.blockers
    assert "ibkr_market_data_incomplete_bar" in status.blockers
    assert "ibkr_market_data_future_bar" in status.blockers


def test_duplicate_out_of_order_gap_and_reconnect_are_deduplicated_fail_closed() -> None:
    first_close = datetime(2026, 8, 5, 20, 0, tzinfo=timezone.utc)
    second_close = datetime(2026, 8, 6, 20, 0, tzinfo=timezone.utc)
    client = FakeMarketDataClient()
    adapter = _adapter(client, second_close + timedelta(minutes=1))
    received_at = second_close + timedelta(seconds=30)

    client.rows = [_bar(first_close, sequence=1, received_at=received_at)]
    assert adapter.run_once().fresh is True

    client.rows = [_bar(first_close, sequence=1, received_at=received_at)]
    duplicate = adapter.run_once()
    assert adapter.fetch_latest_bars().empty
    assert duplicate.fresh is True
    assert duplicate.dropped_count == 1
    assert duplicate.blockers == []

    adapter._now = lambda: received_at + timedelta(minutes=6)
    client.rows = [_bar(first_close, sequence=1, received_at=received_at)]
    stale_duplicate = adapter.run_once()
    assert stale_duplicate.fresh is False
    assert "ibkr_market_data_stale" in stale_duplicate.blockers
    adapter._now = lambda: second_close + timedelta(minutes=1)

    client.rows = [
        _bar(first_close - timedelta(days=1), sequence=2, received_at=received_at)
    ]
    out_of_order = adapter.run_once()
    assert "ibkr_market_data_out_of_order" in out_of_order.blockers

    client.rows = [_bar(second_close, sequence=3, received_at=received_at)]
    gap = adapter.run_once()
    assert "ibkr_market_data_sequence_gap" in gap.blockers

    client.rows = [
        _bar(second_close, sequence=1, epoch="epoch-2", received_at=received_at)
    ]
    reconnected = adapter.run_once()
    assert reconnected.fresh is True
    assert len(adapter.fetch_latest_bars()) == 1


@pytest.mark.parametrize(
    ("session_close", "received_at"),
    [
        (
            datetime(2026, 1, 5, 21, 0, tzinfo=timezone.utc),
            datetime(2026, 1, 5, 21, 0, 1, tzinfo=timezone.utc),
        ),
        (
            datetime(2026, 3, 9, 20, 0, tzinfo=timezone.utc),
            datetime(2026, 3, 9, 20, 0, 1, tzinfo=timezone.utc),
        ),
        (
            datetime(2026, 11, 27, 18, 0, tzinfo=timezone.utc),
            datetime(2026, 11, 27, 18, 0, 1, tzinfo=timezone.utc),
        ),
    ],
)
def test_rth_dst_and_half_day_close_map_to_new_york_trading_date(
    session_close: datetime,
    received_at: datetime,
) -> None:
    client = FakeMarketDataClient()
    client.rows = [_bar(session_close, received_at=received_at)]
    adapter = _adapter(client, received_at + timedelta(seconds=1))

    status = adapter.run_once()
    frame = adapter.fetch_latest_bars()

    assert status.fresh is True
    assert frame.iloc[0]["trading_date_et"] == session_close.astimezone(
        ZoneInfo("America/New_York")
    ).date().isoformat()
    assert frame.iloc[0]["session"] == "regular"


def test_extended_hours_and_unverified_corporate_actions_fail_closed() -> None:
    now = datetime(2026, 8, 6, 20, 1, tzinfo=timezone.utc)
    client = FakeMarketDataClient()
    client.rows = [
        _bar(
            datetime(2026, 8, 6, 20, 0, tzinfo=timezone.utc),
            session="after_hours",
            split_factor=2.0,
        )
    ]
    status = _adapter(client, now).run_once()

    assert "ibkr_market_data_extended_hours_forbidden" in status.blockers
    assert "ibkr_corporate_action_not_normalized_fail_closed" in status.blockers


def test_verified_split_status_cannot_release_unadjusted_raw_bar() -> None:
    now = datetime(2026, 8, 6, 20, 1, tzinfo=timezone.utc)
    client = FakeMarketDataClient()
    client.rows = [
        _bar(
            datetime(2026, 8, 6, 20, 0, tzinfo=timezone.utc),
            split_factor=2.0,
            corporate_action_status="verified",
            adjusted=False,
            semantic_parity_verified=False,
            normalization_provenance="",
        )
    ]

    status = _adapter(client, now).run_once()

    assert status.fresh is False
    assert "ibkr_adjusted_daily_bar_required" in status.blockers
    assert "ibkr_runtime_semantic_parity_not_verified" in status.blockers
    assert "ibkr_corporate_action_not_normalized_fail_closed" in status.blockers


class FakeNativeIBKRMarketClient:
    def __init__(self) -> None:
        self.connected = True
        self.market_data_type = 1
        self.connect_calls = 0
        self.requested_market_data_types: list[int] = []
        self.ticker = SimpleNamespace(marketDataType=1)
        self.realtime: list[SimpleNamespace] = []
        self.cancelled_realtime: list[object] = []
        self.cancelled_market_data: list[object] = []
        self.realtime_requests = 0
        self.history_requests: list[str] = []

    def isConnected(self) -> bool:
        return self.connected

    def connect(self, *_args: object, **_kwargs: object) -> None:
        self.connect_calls += 1

    def reqMarketDataType(self, value: int) -> None:
        self.requested_market_data_types.append(value)

    def qualifyContracts(self, contract: object) -> list[object]:
        return [contract]

    def reqMktData(self, *_args: object, **_kwargs: object) -> object:
        return self.ticker

    def reqRealTimeBars(self, *_args: object, **_kwargs: object) -> list[SimpleNamespace]:
        self.realtime_requests += 1
        return self.realtime

    def cancelRealTimeBars(self, handle: object) -> None:
        self.cancelled_realtime.append(handle)

    def cancelMktData(self, contract: object) -> None:
        self.cancelled_market_data.append(contract)

    def waitOnUpdate(self, *, timeout: float) -> None:
        assert timeout == 1.0

    def reqHistoricalData(self, _contract: object, **kwargs: object) -> list[SimpleNamespace]:
        duration = str(kwargs["durationStr"])
        assert kwargs["whatToShow"] == "ADJUSTED_LAST"
        self.history_requests.append(duration)
        if duration == "2 Y":
            return [
                SimpleNamespace(date="2026-08-04", open=490, high=496, low=488, close=495, volume=9000),
                SimpleNamespace(date="2026-08-05", open=495, high=501, low=494, close=500, volume=9500),
            ]
        return [
            SimpleNamespace(date="2026-08-06", open=500, high=506, low=498, close=505, volume=10_000)
        ]


def _native_contract(symbol: str) -> SimpleNamespace:
    return SimpleNamespace(
        conId=320227571,
        symbol=symbol,
        secType="STK",
        exchange="SMART",
        currency="USD",
    )


def test_native_transport_subscribes_warms_aggregates_normalizes_and_cancels() -> None:
    now = datetime(2026, 8, 6, 20, 0, 10, tzinfo=timezone.utc)
    client = FakeNativeIBKRMarketClient()
    transport = IBKRSDKNeutralMarketDataTransport(
        IBKRMarketDataTransportConfig(symbols=("QQQ",), warmup_min_bars=2),
        client=client,
        contract_factory=_native_contract,
        now=lambda: now,
    )
    adapter = IBKRRuntimeMarketDataAdapter(
        IBKRRuntimeMarketDataConfig(symbols=("QQQ",), require_warmup=True),
        client=transport,
        now=lambda: now,
    )

    assert client.connect_calls == 0
    start = adapter.start()
    assert start["warmup_ready"] is True
    assert len(adapter.fetch_warmup_bars()) == 2
    client.realtime.extend(
        [
            SimpleNamespace(time=datetime(2026, 8, 6, 13, 30, tzinfo=timezone.utc), open=500, high=501, low=499, close=500.5, volume=100),
            SimpleNamespace(time=datetime(2026, 8, 6, 19, 59, 55, tzinfo=timezone.utc), open=504, high=506, low=503, close=505, volume=200),
        ]
    )

    status = adapter.run_once()
    frame = adapter.fetch_latest_bars()

    assert status.fresh is True
    assert frame.iloc[0]["adjusted"]
    assert frame.iloc[0]["semantic_parity_verified"]
    assert frame.iloc[0]["normalization_provenance"] == "IBKR_ADJUSTED_LAST_CLOSE_REFRESH"
    assert adapter.semantic_gate_status()["ok"] is True
    assert client.history_requests == ["2 Y", "5 D"]
    adapter.stop()
    assert len(client.cancelled_realtime) == 1
    assert len(client.cancelled_market_data) == 1


def test_native_transport_reconnect_restores_once_without_duplicate_session() -> None:
    now = datetime(2026, 8, 6, 20, 0, 10, tzinfo=timezone.utc)
    client = FakeNativeIBKRMarketClient()
    transport = IBKRSDKNeutralMarketDataTransport(
        IBKRMarketDataTransportConfig(symbols=("QQQ",), warmup_min_bars=2),
        client=client,
        contract_factory=_native_contract,
        now=lambda: now,
    )
    transport.start()
    client.realtime.append(
        SimpleNamespace(time=datetime(2026, 8, 6, 19, 59, 55, tzinfo=timezone.utc), open=500, high=506, low=498, close=505, volume=100)
    )
    assert len(transport.poll_completed_bars()) == 1

    restored = transport.restore_after_reconnect()

    assert restored["subscription_count"] == 1
    assert client.realtime_requests == 2
    assert transport.poll_completed_bars() == []
