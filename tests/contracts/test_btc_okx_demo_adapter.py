from __future__ import annotations

import json
from decimal import Decimal
from typing import Any, Mapping

import pytest

from quant_crypto.oms.okx_demo import (
    OkxDemoClient,
    OkxDemoClientConfig,
    OkxDemoCredentials,
    OkxDemoPublicMarketClient,
    OkxDemoResponse,
    OkxDemoSafetyError,
    OkxDemoTransportError,
    OkxDemoReadOnlyClient,
    OkxDemoFaultInjectingClient,
    UrllibOkxDemoTransport,
    build_btc_usdt_swap_demo_probe_plan,
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
        self.calls.append(
            {
                "method": method,
                "url": url,
                "headers": dict(headers),
                "body": body,
                "timeout_seconds": timeout_seconds,
            }
        )
        return OkxDemoResponse(
            method=method,
            path="/api/v5/market/candles",
            http_status=200,
            code="0",
            message="",
            data=(),
        )


class SequenceTransport(FakeTransport):
    def __init__(self, codes: tuple[str, ...]) -> None:
        super().__init__()
        self._codes = list(codes)

    def send(self, **kwargs: Any) -> OkxDemoResponse:
        self.calls.append(dict(kwargs))
        code = self._codes.pop(0)
        return OkxDemoResponse(
            method=str(kwargs["method"]),
            path="/api/v5/market/ticker",
            http_status=200,
            code=code,
            message="transient" if code != "0" else "",
            data=({"bidPx": "60000", "askPx": "60001"},) if code == "0" else (),
        )


class TransportErrorSequence(FakeTransport):
    def __init__(self, outcomes: tuple[str, ...]) -> None:
        super().__init__()
        self._outcomes = list(outcomes)

    def send(self, **kwargs: Any) -> OkxDemoResponse:
        self.calls.append(dict(kwargs))
        outcome = self._outcomes.pop(0)
        if outcome != "0":
            raise OkxDemoTransportError(outcome)
        return OkxDemoResponse(
            method=str(kwargs["method"]),
            path="/api/v5/account/config",
            http_status=200,
            code="0",
            message="",
            data=({"acctLv": "2"},),
        )


class DeadManSequenceTransport(FakeTransport):
    def __init__(self, codes: tuple[str, ...]) -> None:
        super().__init__()
        self._codes = list(codes)

    def send(self, **kwargs: Any) -> OkxDemoResponse:
        self.calls.append(dict(kwargs))
        code = self._codes.pop(0)
        return OkxDemoResponse(
            method=str(kwargs["method"]),
            path="/api/v5/trade/cancel-all-after",
            http_status=200,
            code=code,
            message="transient" if code != "0" else "",
            data=(
                {"triggerTime": "2", "tag": "btcP0Demo", "ts": "1"},
            ) if code == "0" else (),
        )


class FakeUrlResponse:
    def __init__(self, payload: bytes, *, status: int = 200) -> None:
        self._payload = payload
        self.status = status

    def __enter__(self) -> FakeUrlResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._payload


def _client(transport: FakeTransport) -> OkxDemoClient:
    return OkxDemoClient(
        config=OkxDemoClientConfig(allow_private_read=False),
        credentials=OkxDemoCredentials(
            api_key="demo-key",
            secret_key="demo-secret",
            passphrase="REDACTED_CREDENTIAL_LITERAL",
        ),
        transport=transport,
    )


def _retrying_client(
    transport: FakeTransport,
    sleepers: list[float],
    *,
    allow_orders: bool = False,
) -> OkxDemoClient:
    return OkxDemoClient(
        config=OkxDemoClientConfig(
            allow_private_read=False,
            allow_demo_orders=allow_orders,
            authorization_ticket="BTC-OKX-DEMO-TRANSIENT-RECOVERY-01" if allow_orders else "",
            max_order_contracts=1 if allow_orders else 0,
            max_notional_usdt=100_000 if allow_orders else 0,
            contract_value_btc=Decimal("0.01") if allow_orders else 0,
        ),
        credentials=OkxDemoCredentials(
            api_key="demo-key",
            secret_key="demo-secret",
            passphrase="REDACTED_CREDENTIAL_LITERAL",
        ),
        transport=transport,
        sleeper=sleepers.append,
    )


def _protected_long_order(**overrides: Any) -> dict[str, Any]:
    order: dict[str, Any] = {
        "instId": "BTC-USDT-SWAP",
        "tdMode": "isolated",
        "side": "buy",
        "posSide": "long",
        "ordType": "fok",
        "px": "60000",
        "sz": "0.01",
        "clOrdId": "protectedEntryV1",
        "tag": "btcP0Demo",
        "attachAlgoOrds": [
            {
                "attachAlgoClOrdId": "protectedAlgoV1",
                "tpTriggerPx": "61200",
                "tpOrdPx": "-1",
                "tpTriggerPxType": "mark",
                "slTriggerPx": "59400",
                "slOrdPx": "-1",
                "slTriggerPxType": "mark",
            }
        ],
    }
    order.update(overrides)
    return order


def test_read_only_get_retries_recoverable_okx_code_then_succeeds() -> None:
    transport = SequenceTransport(("50001", "0"))
    sleepers: list[float] = []

    response = _retrying_client(transport, sleepers).public_get(
        "/api/v5/market/ticker",
        {"instId": "BTC-USDT-SWAP"},
    )

    assert response.ok is True
    assert len(transport.calls) == 2
    assert sleepers == [0.25]


def test_private_get_retries_transport_error_in_place_then_succeeds() -> None:
    transport = TransportErrorSequence(("URLError", "0"))
    sleepers: list[float] = []
    client = OkxDemoClient(
        config=OkxDemoClientConfig(allow_private_read=True),
        credentials=OkxDemoCredentials(
            api_key="demo-key",
            secret_key="demo-secret",
            passphrase="REDACTED_CREDENTIAL_LITERAL",
        ),
        transport=transport,
        sleeper=sleepers.append,
    )

    response = client.private_get("/api/v5/account/config")

    assert response.ok is True
    assert len(transport.calls) == 2
    assert sleepers == [0.25]


def test_private_get_transport_error_stops_after_bounded_retry_budget() -> None:
    transport = TransportErrorSequence(("URLError", "URLError", "URLError"))
    sleepers: list[float] = []
    client = OkxDemoClient(
        config=OkxDemoClientConfig(allow_private_read=True),
        credentials=OkxDemoCredentials(
            api_key="demo-key",
            secret_key="demo-secret",
            passphrase="REDACTED_CREDENTIAL_LITERAL",
        ),
        transport=transport,
        sleeper=sleepers.append,
    )

    with pytest.raises(OkxDemoTransportError, match="URLError"):
        client.private_get("/api/v5/account/config")

    assert len(transport.calls) == 3
    assert sleepers == [0.25, 1.0]


@pytest.mark.parametrize("code", ["50004", "50011", "50013", "50026"])
def test_all_explicit_recoverable_get_codes_share_bounded_budget(code: str) -> None:
    transport = SequenceTransport((code, "0"))
    sleepers: list[float] = []

    response = _retrying_client(transport, sleepers).public_get(
        "/api/v5/market/ticker",
        {"instId": "BTC-USDT-SWAP"},
    )

    assert response.ok is True
    assert len(transport.calls) == 2


def test_read_only_get_stops_after_retry_budget() -> None:
    transport = SequenceTransport(("50001", "50001", "50001"))
    sleepers: list[float] = []

    response = _retrying_client(transport, sleepers).public_get(
        "/api/v5/market/ticker",
        {"instId": "BTC-USDT-SWAP"},
    )

    assert response.code == "50001"
    assert len(transport.calls) == 3
    assert sleepers == [0.25, 1.0]


def test_unrecoverable_get_code_is_not_retried() -> None:
    transport = SequenceTransport(("51000",))
    sleepers: list[float] = []

    response = _retrying_client(transport, sleepers).public_get(
        "/api/v5/market/ticker",
        {"instId": "BTC-USDT-SWAP"},
    )

    assert response.code == "51000"
    assert len(transport.calls) == 1
    assert sleepers == []


def test_order_post_is_never_retried_for_recoverable_response_code() -> None:
    transport = SequenceTransport(("50001",))
    sleepers: list[float] = []

    response = _retrying_client(
        transport,
        sleepers,
        allow_orders=True,
    ).submit_order(_protected_long_order(clOrdId="noRetryWriteV1"))

    assert response.code == "50001"
    assert len(transport.calls) == 1
    assert sleepers == []


def test_fault_injected_response_loss_occurs_after_exactly_one_real_post() -> None:
    transport = SequenceTransport(("0",))
    underlying = _retrying_client(transport, [], allow_orders=True)
    timeline: list[dict[str, Any]] = []
    client = OkxDemoFaultInjectingClient(
        underlying,
        scenario="post_response_loss",
        timeline=timeline,
    )

    with pytest.raises(Exception, match="fault_injected_post_response_loss"):
        client.submit_order(_protected_long_order(clOrdId="responseLossV1"))

    assert len(transport.calls) == 1
    assert timeline[-1]["event"] == "post_response_lost_after_exchange_response"


def test_read_only_client_registers_no_order_cancel_or_post_methods() -> None:
    client = OkxDemoReadOnlyClient(
        config=OkxDemoClientConfig(allow_private_read=True),
        credentials=OkxDemoCredentials("demo-key", "demo-secret", "demo-passphrase"),
        transport=FakeTransport(),
    )

    assert not hasattr(client, "submit_order")
    assert not hasattr(client, "cancel_order")
    assert not hasattr(client, "cancel_all_after")


def test_opening_order_requires_fok_tag_and_exchange_hosted_protection() -> None:
    client = _retrying_client(FakeTransport(), [], allow_orders=True)

    with pytest.raises(OkxDemoSafetyError, match="opening_order_must_be_fok"):
        client.submit_order(_protected_long_order(ordType="ioc"))
    without_tag = _protected_long_order()
    without_tag.pop("tag")
    with pytest.raises(OkxDemoSafetyError, match="order_tag_invalid"):
        client.submit_order(without_tag)
    without_protection = _protected_long_order()
    without_protection.pop("attachAlgoOrds")
    with pytest.raises(OkxDemoSafetyError, match="attached_protection_required"):
        client.submit_order(without_protection)


def test_partial_fill_drill_opt_in_allows_only_0p03_ioc_opening() -> None:
    transport = FakeTransport()
    client = OkxDemoClient(
        config=OkxDemoClientConfig(
            allow_private_read=False,
            allow_demo_orders=True,
            allow_partial_fill_opening=True,
            authorization_ticket="BTC-OKX-P0-DRILL-SUPERVISOR-FRONTEND-01",
            max_order_contracts=Decimal("0.03"),
            max_notional_usdt=Decimal("25"),
            contract_value_btc=Decimal("0.01"),
        ),
        credentials=OkxDemoCredentials("demo-key", "demo-secret", "demo-passphrase"),
        transport=transport,
    )

    client.submit_order(
        _protected_long_order(
            ordType="ioc",
            sz="0.03",
            clOrdId="partialEntryV1",
        )
    )

    assert len(transport.calls) == 1
    body = json.loads((transport.calls[0]["body"] or b"{}").decode("utf-8"))
    assert body["ordType"] == "ioc"
    assert body["sz"] == "0.03"


@pytest.mark.parametrize(
    ("override", "error"),
    [
        ({"tpTriggerPxType": "last"}, "trigger_must_be_mark"),
        ({"slOrdPx": "59000"}, "exit_must_be_market"),
        ({"slTriggerPx": "60500"}, "price_direction_invalid"),
    ],
)
def test_attached_protection_rejects_unsafe_semantics(
    override: dict[str, str],
    error: str,
) -> None:
    client = _retrying_client(FakeTransport(), [], allow_orders=True)
    order = _protected_long_order()
    order["attachAlgoOrds"] = [{**order["attachAlgoOrds"][0], **override}]

    with pytest.raises(OkxDemoSafetyError, match=error):
        client.submit_order(order)


def test_closing_order_is_ioc_tagged_and_has_no_attached_protection() -> None:
    transport = FakeTransport()
    client = _retrying_client(transport, [], allow_orders=True)

    client.submit_order(
        {
            "instId": "BTC-USDT-SWAP",
            "tdMode": "isolated",
            "side": "sell",
            "posSide": "long",
            "ordType": "ioc",
            "px": "60000",
            "sz": "0.01",
            "clOrdId": "riskExitV1",
            "tag": "btcP0Demo",
        }
    )

    assert len(transport.calls) == 1


@pytest.mark.parametrize("timeout_seconds", [-1, 1, 9, 121])
def test_cancel_all_after_rejects_unbounded_timeout(timeout_seconds: int) -> None:
    transport = FakeTransport()
    client = OkxDemoClient(
        config=OkxDemoClientConfig(
            allow_private_read=False,
            allow_demo_cancels=True,
            authorization_ticket="BTC-OKX-P0-DISCONNECT-SAFETY-01",
        ),
        credentials=OkxDemoCredentials("demo-key", "demo-secret", "demo-passphrase"),
        transport=transport,
    )

    with pytest.raises(OkxDemoSafetyError, match="timeout_out_of_bounds"):
        client.cancel_all_after(timeout_seconds=timeout_seconds, tag="btcP0Demo")
    assert transport.calls == []


def test_cancel_all_after_is_tagged_and_unknown_code_is_posted_once() -> None:
    transport = SequenceTransport(("51000",))
    client = OkxDemoClient(
        config=OkxDemoClientConfig(
            allow_private_read=False,
            allow_demo_cancels=True,
            authorization_ticket="BTC-OKX-P0-DISCONNECT-SAFETY-01",
        ),
        credentials=OkxDemoCredentials("demo-key", "demo-secret", "demo-passphrase"),
        transport=transport,
        sleeper=lambda _: pytest.fail("unknown CAA code must not sleep or retry"),
    )

    response = client.cancel_all_after(timeout_seconds=30, tag="btcP0Demo")

    assert response.code == "51000"
    assert len(transport.calls) == 1
    assert transport.calls[0]["method"] == "POST"
    assert transport.calls[0]["url"].endswith("/api/v5/trade/cancel-all-after")
    assert json.loads(transport.calls[0]["body"].decode("utf-8")) == {
        "timeOut": "30",
        "tag": "btcP0Demo",
    }


def test_cancel_all_after_retries_only_transient_50001_then_accepts_ack() -> None:
    transport = DeadManSequenceTransport(("50001", "0"))
    sleepers: list[float] = []
    client = OkxDemoClient(
        config=OkxDemoClientConfig(
            allow_private_read=False,
            allow_demo_cancels=True,
            authorization_ticket="BTC-OKX-P0-DISCONNECT-SAFETY-01",
        ),
        credentials=OkxDemoCredentials("demo-key", "demo-secret", "demo-passphrase"),
        transport=transport,
        sleeper=sleepers.append,
    )

    response = client.cancel_all_after(timeout_seconds=30, tag="btcP0Demo")

    assert response.action_ok is True
    assert len(transport.calls) == 2
    assert sleepers == [0.25]
    assert [json.loads(call["body"].decode("utf-8")) for call in transport.calls] == [
        {"timeOut": "30", "tag": "btcP0Demo"},
        {"timeOut": "30", "tag": "btcP0Demo"},
    ]


def test_cancel_all_after_exhausts_transient_50001_budget_fail_closed() -> None:
    transport = DeadManSequenceTransport(("50001", "50001", "50001"))
    sleepers: list[float] = []
    client = OkxDemoClient(
        config=OkxDemoClientConfig(
            allow_private_read=False,
            allow_demo_cancels=True,
            authorization_ticket="BTC-OKX-P0-DISCONNECT-SAFETY-01",
        ),
        credentials=OkxDemoCredentials("demo-key", "demo-secret", "demo-passphrase"),
        transport=transport,
        sleeper=sleepers.append,
    )

    response = client.cancel_all_after(timeout_seconds=30, tag="btcP0Demo")

    assert response.code == "50001"
    assert response.action_ok is False
    assert len(transport.calls) == 3
    assert sleepers == [0.25, 1.0]


def test_cancel_all_after_unknown_code_is_not_retried() -> None:
    transport = DeadManSequenceTransport(("51000", "0"))
    sleepers: list[float] = []
    client = OkxDemoClient(
        config=OkxDemoClientConfig(
            allow_private_read=False,
            allow_demo_cancels=True,
            authorization_ticket="BTC-OKX-P0-DISCONNECT-SAFETY-01",
        ),
        credentials=OkxDemoCredentials("demo-key", "demo-secret", "demo-passphrase"),
        transport=transport,
        sleeper=sleepers.append,
    )

    response = client.cancel_all_after(timeout_seconds=30, tag="btcP0Demo")

    assert response.code == "51000"
    assert len(transport.calls) == 1
    assert sleepers == []


def test_cancel_all_after_transport_error_is_not_retried() -> None:
    class RaisingTransport(FakeTransport):
        def send(self, **kwargs: Any) -> OkxDemoResponse:
            self.calls.append(dict(kwargs))
            raise OkxDemoTransportError("connection_reset")

    transport = RaisingTransport()
    sleepers: list[float] = []
    client = OkxDemoClient(
        config=OkxDemoClientConfig(
            allow_private_read=False,
            allow_demo_cancels=True,
            authorization_ticket="BTC-OKX-P0-DISCONNECT-SAFETY-01",
        ),
        credentials=OkxDemoCredentials("demo-key", "demo-secret", "demo-passphrase"),
        transport=transport,
        sleeper=sleepers.append,
    )

    with pytest.raises(OkxDemoTransportError, match="connection_reset"):
        client.cancel_all_after(timeout_seconds=30, tag="btcP0Demo")
    assert len(transport.calls) == 1
    assert sleepers == []


def test_cancel_algos_requires_exact_identifiers_and_posts_bounded_array() -> None:
    transport = FakeTransport()
    client = OkxDemoClient(
        config=OkxDemoClientConfig(
            allow_private_read=True,
            allow_demo_cancels=True,
            authorization_ticket="BTC-OKX-P0-DRILL-SUPERVISOR-FRONTEND-01",
        ),
        credentials=OkxDemoCredentials("demo-key", "demo-secret", "demo-passphrase"),
        transport=transport,
    )

    client.cancel_algo_orders(
        [{"algoId": "12345", "instId": "BTC-USDT-SWAP"}]
    )

    assert len(transport.calls) == 1
    assert transport.calls[0]["method"] == "POST"
    assert transport.calls[0]["url"].endswith("/api/v5/trade/cancel-algos")
    assert json.loads(transport.calls[0]["body"].decode("utf-8")) == [
        {"algoId": "12345", "instId": "BTC-USDT-SWAP"}
    ]
    with pytest.raises(OkxDemoSafetyError, match="fields_invalid"):
        client.cancel_algo_orders(
            [{"algoId": "12345", "instId": "BTC-USDT-SWAP", "secret": "x"}]
        )
    with pytest.raises(OkxDemoSafetyError, match="batch_size_invalid"):
        client.cancel_algo_orders([])
    with pytest.raises(OkxDemoSafetyError, match="batch_size_invalid"):
        client.cancel_algo_orders(
            [
                {"algoId": str(index), "instId": "BTC-USDT-SWAP"}
                for index in range(11)
            ]
        )


def test_algo_order_reads_are_strictly_allowlisted() -> None:
    transport = FakeTransport()
    client = OkxDemoClient(
        config=OkxDemoClientConfig(allow_private_read=True),
        credentials=OkxDemoCredentials("demo-key", "demo-secret", "demo-passphrase"),
        transport=transport,
    )

    client.private_get("/api/v5/trade/order-algo", {"algoClOrdId": "protectedAlgoV1"})
    client.private_get(
        "/api/v5/trade/orders-algo-pending",
        {"instId": "BTC-USDT-SWAP", "ordType": "oco"},
    )
    client.private_get(
        "/api/v5/trade/orders-algo-history",
        {
            "instId": "BTC-USDT-SWAP",
            "ordType": "oco",
            "state": "canceled",
        },
    )
    client.private_get(
        "/api/v5/trade/orders-algo-history",
        {
            "instId": "BTC-USDT-SWAP",
            "ordType": "oco",
            "algoId": "protectedAlgoV1",
        },
    )
    with pytest.raises(OkxDemoSafetyError, match="pending_algo_query_params_invalid"):
        client.private_get(
            "/api/v5/trade/orders-algo-pending",
            {
                "instId": "BTC-USDT-SWAP",
                "ordType": "oco",
                "state": "canceled",
            },
        )
    with pytest.raises(OkxDemoSafetyError, match="algo_history_query_params_invalid"):
        client.private_get(
            "/api/v5/trade/orders-algo-history",
            {"instId": "BTC-USDT-SWAP", "ordType": "oco"},
        )
    with pytest.raises(OkxDemoSafetyError, match="algo_history_query_params_invalid"):
        client.private_get(
            "/api/v5/trade/orders-algo-history",
            {
                "instId": "BTC-USDT-SWAP",
                "ordType": "oco",
                "state": "canceled",
                "algoId": "protectedAlgoV1",
            },
        )
    with pytest.raises(OkxDemoSafetyError, match="algo_history_query_params_invalid"):
        client.private_get(
            "/api/v5/trade/orders-algo-history",
            {
                "instId": "BTC-USDT-SWAP",
                "ordType": "oco",
                "state": "canceled",
                "secret": "x",
            },
        )
    with pytest.raises(OkxDemoSafetyError, match="algo_history_state_not_allowlisted"):
        client.private_get(
            "/api/v5/trade/orders-algo-history",
            {
                "instId": "BTC-USDT-SWAP",
                "ordType": "oco",
                "state": "live",
            },
        )
    with pytest.raises(OkxDemoSafetyError, match="algo_history_identifier_invalid"):
        client.private_get(
            "/api/v5/trade/orders-algo-history",
            {
                "instId": "BTC-USDT-SWAP",
                "ordType": "oco",
                "algoId": "bad-id",
            },
        )
    with pytest.raises(OkxDemoSafetyError, match="query_params_invalid"):
        client.private_get("/api/v5/trade/order-algo", {"algoId": "1", "secret": "x"})

    assert len(transport.calls) == 4


def test_public_candles_is_bounded_keyless_and_exact_instrument_1h() -> None:
    transport = FakeTransport()
    client = _client(transport)

    client.public_get(
        "/api/v5/market/candles",
        {"instId": "BTC-USDT-SWAP", "bar": "1H", "limit": "100"},
    )

    call = transport.calls[0]
    assert call["method"] == "GET"
    assert "instId=BTC-USDT-SWAP" in call["url"]
    assert "bar=1H" in call["url"]
    assert "limit=100" in call["url"]
    assert not {
        "OK-ACCESS-KEY",
        "OK-ACCESS-SIGN",
        "OK-ACCESS-PASSPHRASE",
        "x-simulated-trading",
    }.intersection(call["headers"])
    assert call["body"] is None


@pytest.mark.parametrize(
    ("timeframe", "expected_bar"),
    [
        ("1m", "1m"),
        ("5m", "5m"),
        ("15m", "15m"),
        ("1h", "1H"),
        ("4h", "4H"),
        ("1d", "1Dutc"),
        ("1w", "1Wutc"),
        ("1M", "1Mutc"),
    ],
)
def test_public_market_view_is_keyless_allows_visual_timeframes_and_marks_unconfirmed_bar(
    timeframe: str,
    expected_bar: str,
) -> None:
    class PublicMarketTransport(FakeTransport):
        def send(self, **kwargs: Any) -> OkxDemoResponse:
            self.calls.append(dict(kwargs))
            if "/ticker" in str(kwargs["url"]):
                return OkxDemoResponse(
                    method="GET", path="/api/v5/market/ticker", http_status=200,
                    code="0", message="", data=({"bidPx": "65000", "askPx": "65001", "last": "65000.5", "ts": "1760000000000"},),
                )
            return OkxDemoResponse(
                method="GET", path="/api/v5/market/candles", http_status=200,
                code="0", message="", data=(
                    ["1760000000000", "64999", "65002", "64998", "65000", "12", "0", "0", "0"],
                    ["1759999940000", "64990", "65000", "64980", "64999", "11", "0", "0", "1"],
                ),
            )

    transport = PublicMarketTransport()
    payload = OkxDemoPublicMarketClient(transport=transport).market_view(
        timeframe=timeframe, limit=120,
    )

    assert payload["public_only"] is True
    assert payload["strategy_signal_compatible"] is False
    assert payload["private_endpoint_used"] is False
    assert payload["candles"][-1]["in_progress"] is True
    candle_call = next(call for call in transport.calls if "/candles" in str(call["url"]))
    assert f"bar={expected_bar}" in str(candle_call["url"])
    assert {"ticker", "candles"} == {
        "ticker" if "/ticker" in str(call["url"]) else "candles"
        for call in transport.calls
    }
    assert all(not {"OK-ACCESS-KEY", "OK-ACCESS-SIGN", "OK-ACCESS-PASSPHRASE"}.intersection(call["headers"]) for call in transport.calls)


def test_public_books_is_keyless_strict_btcusdt_books5_and_normalizes_depth() -> None:
    class PublicBooksTransport(FakeTransport):
        def send(self, **kwargs: Any) -> OkxDemoResponse:
            self.calls.append(dict(kwargs))
            return OkxDemoResponse(
                method="GET",
                path="/api/v5/market/books",
                http_status=200,
                code="0",
                message="",
                data=(
                    {
                        "bids": [["62043", "2", "0", "3"], ["62042", "3", "0", "2"], ["62041", "4", "0", "1"], ["62040", "5", "0", "1"], ["62039", "6", "0", "1"]],
                        "asks": [["62045", "2", "0", "4"], ["62046", "3", "0", "3"], ["62047", "4", "0", "2"], ["62048", "5", "0", "1"], ["62049", "6", "0", "1"]],
                        "ts": "1783994400000",
                        "seqId": "7",
                        "checksum": "123",
                    },
                ),
            )

    transport = PublicBooksTransport()
    depth = OkxDemoPublicMarketClient(transport=transport).books()

    assert depth["source"] == "okx_public_rest_books5"
    assert depth["instrument_id"] == "BTC-USDT-SWAP"
    assert len(depth["bids"]) == 5
    assert len(depth["asks"]) == 5
    assert depth["bids"][0]["price"] == "62043"
    assert depth["asks"][0]["price"] == "62045"
    assert depth["sequence"] == 7
    assert depth["checksum"] == "123"
    call = transport.calls[0]
    assert call["method"] == "GET"
    assert "instId=BTC-USDT-SWAP" in call["url"]
    assert "sz=5" in call["url"]
    assert not {"OK-ACCESS-KEY", "OK-ACCESS-SIGN", "OK-ACCESS-PASSPHRASE", "x-simulated-trading"}.intersection(call["headers"])


@pytest.mark.parametrize(
    "payload",
    [
        {"bids": [], "asks": [], "ts": "1783994400000"},
        {"bids": [["62043", "2", "0", "3"]] * 5, "asks": [["62040", "2", "0", "3"]] * 5, "ts": "1783994400000"},
        {"bids": [["62043", "2", "0", "3"]] * 5, "asks": [["62045", "2", "0", "3"]] * 5, "ts": "not-a-timestamp", "seqId": "7"},
    ],
)
def test_public_books_rejects_invalid_or_crossed_books5(payload: dict[str, Any]) -> None:
    class InvalidBooksTransport(FakeTransport):
        def send(self, **kwargs: Any) -> OkxDemoResponse:
            self.calls.append(dict(kwargs))
            return OkxDemoResponse(
                method="GET",
                path="/api/v5/market/books",
                http_status=200,
                code="0",
                message="",
                data=(payload,),
            )

    with pytest.raises(OkxDemoSafetyError, match="public_market_books"):
        OkxDemoPublicMarketClient(transport=InvalidBooksTransport()).books()


@pytest.mark.parametrize("timeframe", ["2m", "1H", "4H", "1D", "1W", "1Mutc"])
def test_public_market_view_rejects_non_visual_timeframe(timeframe: str) -> None:
    transport = FakeTransport()
    with pytest.raises(OkxDemoSafetyError, match="public_market_timeframe"):
        OkxDemoPublicMarketClient(transport=transport).market_view(timeframe=timeframe, limit=20)
    assert transport.calls == []


def test_public_candles_accepts_strict_backward_pagination_cursor() -> None:
    transport = FakeTransport()

    _client(transport).public_get(
        "/api/v5/market/candles",
        {
            "instId": "BTC-USDT-SWAP",
            "bar": "1H",
            "limit": "100",
            "after": "1785398400000",
        },
    )

    call = transport.calls[0]
    assert "after=1785398400000" in call["url"]
    assert not {
        "OK-ACCESS-KEY",
        "OK-ACCESS-SIGN",
        "OK-ACCESS-PASSPHRASE",
        "x-simulated-trading",
    }.intersection(call["headers"])


@pytest.mark.parametrize(
    "params",
    [
        {"instId": "ETH-USDT-SWAP", "bar": "1H", "limit": "100"},
        {"instId": "BTC-USDT-SWAP", "bar": "1m", "limit": "100"},
        {"instId": "BTC-USDT-SWAP", "bar": "1H", "limit": "101"},
        {
            "instId": "BTC-USDT-SWAP",
            "bar": "1H",
            "limit": "100",
            "before": "1785398400000",
        },
        {"instId": "BTC-USDT-SWAP", "bar": "1H", "limit": "100", "after": ""},
        {"instId": "BTC-USDT-SWAP", "bar": "1H", "limit": "100", "after": "0"},
        {"instId": "BTC-USDT-SWAP", "bar": "1H", "limit": "100", "after": "-1"},
        {"instId": "BTC-USDT-SWAP", "bar": "1H", "limit": "100", "after": " 1785398400000"},
        {"instId": "BTC-USDT-SWAP", "bar": "1H", "limit": "100", "after": "01785398400000"},
        {"instId": "BTC-USDT-SWAP", "bar": "1H", "limit": "100", "after": "1785398400000.0"},
        {"instId": "BTC-USDT-SWAP", "bar": "1H", "limit": "100", "after": "10000000000000"},
    ],
)
def test_public_candles_rejects_unbounded_or_non_allowlisted_params(
    params: dict[str, str],
) -> None:
    transport = FakeTransport()
    with pytest.raises(OkxDemoSafetyError):
        _client(transport).public_get("/api/v5/market/candles", params)
    assert transport.calls == []


def test_urllib_transport_preserves_public_candle_array_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = (
        b'{"code":"0","msg":"","data":'
        b'[["1753862400000","118000","118100","117900","118050","12.5","1"]]}'
    )
    monkeypatch.setattr(
        "quant_crypto.oms.okx_demo.urllib.request.urlopen",
        lambda request, timeout: FakeUrlResponse(payload),
    )

    response = UrllibOkxDemoTransport().send(
        method="GET",
        url="https://www.okx.com/api/v5/market/candles",
        headers={},
        body=None,
        timeout_seconds=1.0,
    )

    assert response.data == (
        ["1753862400000", "118000", "118100", "117900", "118050", "12.5", "1"],
    )
    assert response.action_ok is False
    assert response.action_errors == ()


def test_action_status_ignores_sequence_rows_but_keeps_order_mapping_errors() -> None:
    empty = OkxDemoResponse(
        method="POST",
        path="/api/v5/trade/cancel-all-after",
        http_status=200,
        code="0",
        message="",
        data=(),
    )
    success = OkxDemoResponse(
        method="POST",
        path="/api/v5/trade/order",
        http_status=200,
        code="0",
        message="",
        data=({"sCode": "0", "sMsg": ""},),
    )
    response = OkxDemoResponse(
        method="POST",
        path="/api/v5/trade/order",
        http_status=200,
        code="0",
        message="",
        data=(
            ["public", "sequence", "row"],
            {"sCode": "51000", "sMsg": "Parameter error"},
        ),
    )

    assert empty.action_ok is False
    assert success.action_ok is True
    assert success.action_errors == ()
    assert response.action_ok is False
    assert response.action_errors == ("51000:Parameter error",)


@pytest.mark.parametrize(
    ("position_mode", "expected_status"),
    (
        ("net_mode", "blocked_fail_closed"),
        ("long_short_mode", "ready_for_explicit_demo_order_authorization"),
    ),
)
def test_legacy_probe_matches_p0_runtime_position_mode_contract(
    position_mode: str,
    expected_status: str,
) -> None:
    plan = build_btc_usdt_swap_demo_probe_plan(
        account_config={
            "acctLv": "2",
            "perm": "read_only,trade",
            "posMode": position_mode,
        },
        instrument={
            "instId": "BTC-USDT-SWAP",
            "state": "live",
            "ctType": "linear",
            "settleCcy": "USDT",
            "tickSz": "0.1",
            "lotSz": "0.01",
            "minSz": "0.01",
            "ctVal": "0.01",
        },
        ticker={"bidPx": "60000", "askPx": "60000.1"},
    )

    assert plan.status == expected_status
    if position_mode == "net_mode":
        assert "okx_demo_p0_runtime_requires_long_short_mode" in plan.blockers
    else:
        assert plan.blockers == ()
