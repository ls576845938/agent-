"""OKX Demo adapter kept inside the BTC OMS boundary."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Callable, Mapping, Protocol, Sequence


OKX_DEMO_ADAPTER_VERSION = "okx_demo_adapter_v1"
OKX_DEMO_BASE_URLS = {"https://www.okx.com", "https://openapi.okx.com"}
OKX_DEMO_INSTRUMENT_ID = "BTC-USDT-SWAP"
OKX_DEMO_PRIVATE_READ_PATHS = {
    "/api/v5/account/config",
    "/api/v5/account/balance",
    "/api/v5/account/positions",
    "/api/v5/account/trade-fee",
    "/api/v5/account/leverage-info",
    "/api/v5/trade/order",
    "/api/v5/trade/order-algo",
    "/api/v5/trade/orders-algo-pending",
    "/api/v5/trade/orders-algo-history",
    "/api/v5/trade/orders-pending",
    "/api/v5/trade/orders-history",
    "/api/v5/trade/fills",
    "/api/v5/account/bills",
}
OKX_DEMO_PUBLIC_PATHS = {
    "/api/v5/public/instruments",
    "/api/v5/public/funding-rate",
    "/api/v5/public/mark-price",
    "/api/v5/public/price-limit",
    "/api/v5/market/ticker",
    "/api/v5/market/index-tickers",
    "/api/v5/market/books",
    "/api/v5/market/candles",
    "/api/v5/public/time",
}
OKX_DEMO_RECOVERABLE_READ_CODES = frozenset(
    {"50001", "50004", "50011", "50013", "50026"}
)
OKX_DEMO_READ_RETRY_DELAYS_SECONDS = (0.25, 1.0)
OKX_DEMO_DEAD_MAN_50001_RETRY_DELAYS_SECONDS = (0.25, 1.0)


class OkxDemoSafetyError(RuntimeError):
    pass


class OkxDemoTransportError(RuntimeError):
    pass


@dataclass(frozen=True, repr=False)
class OkxDemoCredentials:
    api_key: str
    secret_key: str
    passphrase: str

    def __post_init__(self) -> None:
        for name in ("api_key", "secret_key", "passphrase"):
            value = getattr(self, name)
            if not value:
                raise OkxDemoSafetyError(f"okx_demo_{name}_missing")
            if not value.isascii():
                raise OkxDemoSafetyError(f"okx_demo_{name}_not_ascii")
            if value != value.strip():
                raise OkxDemoSafetyError(f"okx_demo_{name}_has_edge_whitespace")

    def __repr__(self) -> str:
        return "OkxDemoCredentials(api_key=<redacted>, secret_key=<redacted>, passphrase=<redacted>)"


@dataclass(frozen=True)
class OkxDemoClientConfig:
    base_url: str = "https://www.okx.com"
    credential_service: str = "quant-system.okx-demo.trade"
    instrument_id: str = OKX_DEMO_INSTRUMENT_ID
    allow_private_read: bool = True
    allow_demo_orders: bool = False
    allow_demo_cancels: bool = False
    allow_partial_fill_opening: bool = False
    authorization_ticket: str = ""
    max_order_contracts: Decimal = Decimal("0")
    max_notional_usdt: Decimal = Decimal("0")
    contract_value_btc: Decimal = Decimal("0")
    timeout_seconds: float = 20.0
    order_expiry_ms: int = 5_000

    def __post_init__(self) -> None:
        if self.base_url not in OKX_DEMO_BASE_URLS:
            raise OkxDemoSafetyError("okx_demo_base_url_not_allowlisted")
        if self.instrument_id != OKX_DEMO_INSTRUMENT_ID:
            raise OkxDemoSafetyError("okx_demo_instrument_not_allowlisted")
        if not self.credential_service.startswith("quant-system.okx-demo."):
            raise OkxDemoSafetyError("okx_demo_credential_service_not_namespaced")
        if self.timeout_seconds <= 0:
            raise OkxDemoSafetyError("okx_demo_timeout_must_be_positive")
        if self.order_expiry_ms <= 0:
            raise OkxDemoSafetyError("okx_demo_order_expiry_must_be_positive")
        order_capability = self.allow_demo_orders or self.allow_demo_cancels
        if order_capability and not self.authorization_ticket.strip():
            raise OkxDemoSafetyError("okx_demo_order_authorization_ticket_missing")
        if self.allow_demo_orders:
            if Decimal(self.max_order_contracts) <= 0:
                raise OkxDemoSafetyError("okx_demo_max_order_contracts_missing")
            if Decimal(self.max_notional_usdt) <= 0:
                raise OkxDemoSafetyError("okx_demo_max_notional_missing")
            if Decimal(self.contract_value_btc) <= 0:
                raise OkxDemoSafetyError("okx_demo_contract_value_missing")
        if self.allow_partial_fill_opening:
            if not self.allow_demo_orders:
                raise OkxDemoSafetyError(
                    "okx_demo_partial_fill_opening_requires_order_capability"
                )
            if (
                self.authorization_ticket
                != "BTC-OKX-P0-DRILL-SUPERVISOR-FRONTEND-01"
            ):
                raise OkxDemoSafetyError(
                    "okx_demo_partial_fill_opening_authorization_ticket_invalid"
                )
            if Decimal(self.max_order_contracts) != Decimal("0.03"):
                raise OkxDemoSafetyError(
                    "okx_demo_partial_fill_opening_contract_cap_invalid"
                )
            if not Decimal("0") < Decimal(self.max_notional_usdt) <= Decimal("25"):
                raise OkxDemoSafetyError(
                    "okx_demo_partial_fill_opening_notional_cap_invalid"
                )


@dataclass(frozen=True)
class OkxDemoResponse:
    method: str
    path: str
    http_status: int | None
    code: str
    message: str
    data: tuple[Any, ...] = ()
    duration_ms: float = 0.0

    @property
    def ok(self) -> bool:
        return self.http_status == 200 and self.code == "0"

    @property
    def action_ok(self) -> bool:
        return self.ok and bool(self.data) and all(
            isinstance(item, Mapping) and str(item.get("sCode") or "0") == "0"
            for item in self.data
        )

    @property
    def action_errors(self) -> tuple[str, ...]:
        return tuple(
            f"{str(item.get('sCode') or 'unknown')}:{str(item.get('sMsg') or '')[:120]}"
            for item in self.data
            if isinstance(item, Mapping) and str(item.get("sCode") or "0") != "0"
        )

    def to_audit_dict(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "path": self.path,
            "http_status": self.http_status,
            "code": self.code,
            "message": self.message,
            "duration_ms": self.duration_ms,
            "record_count": len(self.data),
        }


class OkxDemoTransport(Protocol):
    def send(
        self,
        *,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout_seconds: float,
    ) -> OkxDemoResponse: ...


class UrllibOkxDemoTransport:
    def send(
        self,
        *,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout_seconds: float,
    ) -> OkxDemoResponse:
        path = urllib.parse.urlsplit(url).path
        started = time.perf_counter()
        request = urllib.request.Request(url, headers=dict(headers), data=body, method=method)
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
                return _response(
                    method=method,
                    path=path,
                    http_status=response.status,
                    payload=payload,
                    duration_ms=(time.perf_counter() - started) * 1_000,
                )
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                payload = {"code": "http_error", "msg": "non_json_error_response", "data": []}
            return _response(
                method=method,
                path=path,
                http_status=exc.code,
                payload=payload,
                duration_ms=(time.perf_counter() - started) * 1_000,
            )
        except Exception as exc:
            raise OkxDemoTransportError(type(exc).__name__) from exc


@dataclass(frozen=True)
class OkxDemoProbePlan:
    status: str
    blockers: tuple[str, ...]
    instrument_id: str
    position_mode: str
    minimum_contracts: Decimal
    contract_value_btc: Decimal
    estimated_notional_usdt: Decimal
    max_notional_usdt: Decimal
    stages: tuple[Mapping[str, Any], ...]
    safety: Mapping[str, bool] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "okx_demo_probe_plan_v1",
            "status": self.status,
            "blockers": list(self.blockers),
            "instrument_id": self.instrument_id,
            "position_mode": self.position_mode,
            "minimum_contracts": _decimal_text(self.minimum_contracts),
            "contract_value_btc": _decimal_text(self.contract_value_btc),
            "estimated_notional_usdt": _decimal_text(self.estimated_notional_usdt),
            "max_notional_usdt": _decimal_text(self.max_notional_usdt),
            "stages": [dict(stage) for stage in self.stages],
            "safety": dict(self.safety),
        }


class OkxDemoPublicMarketClient:
    """Credential-free, GET-only market view for the BTC Demo UI.

    This is deliberately separate from :class:`OkxDemoClient`: it cannot sign
    requests, cannot reach private paths, and never exposes an order surface.
    Its rows are visual-only; completed 1h strategy data remains owned by the
    runtime's existing confirmed-bar loader.
    """

    # UI values are deliberately distinct from the OKX bar enum.  In
    # particular, `1M` means a calendar month and must never collapse into
    # the minute value `1m`; UTC bars avoid the exchange's UTC+8 variants.
    _TIMEFRAMES = {
        "1m": "1m",
        "5m": "5m",
        "15m": "15m",
        "1h": "1H",
        "4h": "4H",
        "1d": "1Dutc",
        "1w": "1Wutc",
        "1M": "1Mutc",
    }

    def __init__(
        self,
        *,
        transport: OkxDemoTransport | None = None,
        base_url: str = "https://www.okx.com",
        timeout_seconds: float = 20.0,
        now_ms: Callable[[], int] | None = None,
    ) -> None:
        if base_url not in OKX_DEMO_BASE_URLS:
            raise OkxDemoSafetyError("okx_demo_public_market_base_url_not_allowlisted")
        if timeout_seconds <= 0:
            raise OkxDemoSafetyError("okx_demo_public_market_timeout_must_be_positive")
        self._transport = transport or UrllibOkxDemoTransport()
        self._base_url = base_url
        self._timeout_seconds = float(timeout_seconds)
        self._now_ms = now_ms or (lambda: int(time.time() * 1_000))

    def market_view(self, *, timeframe: str, limit: int) -> dict[str, Any]:
        if str(timeframe) not in self._TIMEFRAMES:
            raise OkxDemoSafetyError("okx_demo_public_market_timeframe_not_allowlisted")
        if not isinstance(limit, int) or limit < 2 or limit > 300:
            raise OkxDemoSafetyError("okx_demo_public_market_limit_out_of_bounds")
        ticker = self.ticker()
        candles = self.candles(timeframe=timeframe, limit=limit)
        return {
            "schema_version": "okx_public_market_view_v1",
            "source_kind": "okx_public_market_view_v1",
            "instrument_id": OKX_DEMO_INSTRUMENT_ID,
            "timeframe": timeframe,
            "read_only": True,
            "public_only": True,
            "private_endpoint_used": False,
            "order_endpoint_used": False,
            "strategy_signal_compatible": False,
            "persisted_market_rows": False,
            "captured_at_ms": self._now_ms(),
            "ticker": ticker,
            "candles": candles,
        }

    def ticker(self) -> dict[str, Any]:
        """Return the current public ticker without credentials or state writes."""
        return self._normalize_ticker(self._get(
            "/api/v5/market/ticker",
            {"instId": OKX_DEMO_INSTRUMENT_ID},
        ))

    def books(self) -> dict[str, Any]:
        """Return a strict, credential-free OKX books5 snapshot for display."""
        return self._normalize_books(self._get(
            "/api/v5/market/books",
            {"instId": OKX_DEMO_INSTRUMENT_ID, "sz": "5"},
        ))

    def candles(self, *, timeframe: str, limit: int) -> list[dict[str, Any]]:
        """Return visual candles, including the exchange's current unconfirmed bar."""
        bar = self._TIMEFRAMES.get(str(timeframe))
        if bar is None:
            raise OkxDemoSafetyError("okx_demo_public_market_timeframe_not_allowlisted")
        if not isinstance(limit, int) or limit < 2 or limit > 300:
            raise OkxDemoSafetyError("okx_demo_public_market_limit_out_of_bounds")
        response = self._get(
            "/api/v5/market/candles",
            {"instId": OKX_DEMO_INSTRUMENT_ID, "bar": bar, "limit": str(limit)},
        )
        return self._normalize_candles(response)

    def _get(self, path: str, params: Mapping[str, str]) -> OkxDemoResponse:
        if path not in {"/api/v5/market/ticker", "/api/v5/market/candles", "/api/v5/market/books"}:
            raise OkxDemoSafetyError("okx_demo_public_market_path_not_allowlisted")
        if path == "/api/v5/market/books":
            if set(params) != {"instId", "sz"} or params.get("instId") != OKX_DEMO_INSTRUMENT_ID or params.get("sz") != "5":
                raise OkxDemoSafetyError("okx_demo_public_market_books_params_not_allowlisted")
        query = urllib.parse.urlencode(dict(params))
        response = self._transport.send(
            method="GET",
            url=f"{self._base_url}{path}?{query}",
            headers={
                "Accept": "application/json",
                "User-Agent": "quant-system-okx-public-market/1.0",
            },
            body=None,
            timeout_seconds=self._timeout_seconds,
        )
        if not response.ok:
            raise OkxDemoTransportError(
                f"okx_demo_public_market_get_failed:{path}:{response.code}"
            )
        return response

    @staticmethod
    def _normalize_ticker(response: OkxDemoResponse) -> dict[str, Any]:
        if len(response.data) != 1 or not isinstance(response.data[0], Mapping):
            raise OkxDemoSafetyError("okx_demo_public_market_ticker_shape_invalid")
        row = response.data[0]
        timestamp_ms = _public_timestamp_ms(row.get("ts"), "okx_demo_public_market_ticker_timestamp_invalid")
        return {
            "bid": _decimal_text(_decimal(row.get("bidPx"), "okx_demo_public_market_bid_invalid")),
            "ask": _decimal_text(_decimal(row.get("askPx"), "okx_demo_public_market_ask_invalid")),
            "last": _decimal_text(_decimal(row.get("last"), "okx_demo_public_market_last_invalid")),
            "timestamp_ms": timestamp_ms,
        }

    @staticmethod
    def _normalize_candles(response: OkxDemoResponse) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        seen: set[int] = set()
        for raw in response.data:
            if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)) or len(raw) < 9:
                raise OkxDemoSafetyError("okx_demo_public_market_candle_shape_invalid")
            timestamp_ms = _public_timestamp_ms(raw[0], "okx_demo_public_market_candle_timestamp_invalid")
            if timestamp_ms in seen:
                raise OkxDemoSafetyError("okx_demo_public_market_candle_duplicate_timestamp")
            seen.add(timestamp_ms)
            confirm = str(raw[8])
            if confirm not in {"0", "1"}:
                raise OkxDemoSafetyError("okx_demo_public_market_candle_confirm_invalid")
            normalized.append(
                {
                    "open_time_ms": timestamp_ms,
                    "open": float(_decimal(raw[1], "okx_demo_public_market_candle_open_invalid")),
                    "high": float(_decimal(raw[2], "okx_demo_public_market_candle_high_invalid")),
                    "low": float(_decimal(raw[3], "okx_demo_public_market_candle_low_invalid")),
                    "close": float(_decimal(raw[4], "okx_demo_public_market_candle_close_invalid")),
                    "volume": float(_decimal(raw[5], "okx_demo_public_market_candle_volume_invalid")),
                    "confirmed": confirm == "1",
                    "in_progress": confirm == "0",
                }
            )
        if not normalized:
            raise OkxDemoSafetyError("okx_demo_public_market_candles_empty")
        return sorted(normalized, key=lambda row: int(row["open_time_ms"]))

    @staticmethod
    def _normalize_books(response: OkxDemoResponse) -> dict[str, Any]:
        if len(response.data) != 1 or not isinstance(response.data[0], Mapping):
            raise OkxDemoSafetyError("okx_demo_public_market_books_shape_invalid")
        row = response.data[0]
        bids = OkxDemoPublicMarketClient._normalize_book_levels(
            row.get("bids"), reverse=True,
        )
        asks = OkxDemoPublicMarketClient._normalize_book_levels(
            row.get("asks"), reverse=False,
        )
        if len(bids) != 5 or len(asks) != 5:
            raise OkxDemoSafetyError("okx_demo_public_market_books5_depth_invalid")
        if Decimal(bids[0]["price"]) >= Decimal(asks[0]["price"]):
            raise OkxDemoSafetyError("okx_demo_public_market_books_crossed")
        timestamp_ms = _public_timestamp_ms(
            row.get("ts"),
            "okx_demo_public_market_books_timestamp_invalid",
        )
        sequence: int | None = None
        if row.get("seqId") not in (None, ""):
            try:
                sequence = int(str(row["seqId"]))
            except (TypeError, ValueError) as exc:
                raise OkxDemoSafetyError("okx_demo_public_market_books_sequence_invalid") from exc
            if sequence < 0:
                raise OkxDemoSafetyError("okx_demo_public_market_books_sequence_invalid")
        checksum: str | None = None
        if row.get("checksum") not in (None, ""):
            checksum = str(row["checksum"])
            if not checksum or not checksum.lstrip("-").isdigit():
                raise OkxDemoSafetyError("okx_demo_public_market_books_checksum_invalid")
        bid_total = sum(Decimal(item["size"]) for item in bids)
        ask_total = sum(Decimal(item["size"]) for item in asks)
        total = bid_total + ask_total
        return {
            "source": "okx_public_rest_books5",
            "instrument_id": OKX_DEMO_INSTRUMENT_ID,
            "bids": bids,
            "asks": asks,
            "spread": _decimal_text(Decimal(asks[0]["price"]) - Decimal(bids[0]["price"])),
            "top5_imbalance": float(bid_total / total) if total else 0.0,
            "timestamp_ms": timestamp_ms,
            "sequence": sequence,
            "checksum": checksum,
        }

    @staticmethod
    def _normalize_book_levels(value: Any, *, reverse: bool) -> list[dict[str, str]]:
        if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
            raise OkxDemoSafetyError("okx_demo_public_market_books_levels_invalid")
        rows: list[dict[str, str]] = []
        for raw in value:
            if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)) or len(raw) < 2:
                raise OkxDemoSafetyError("okx_demo_public_market_books_levels_invalid")
            price = _decimal(raw[0], "okx_demo_public_market_books_price_invalid")
            size = _decimal(raw[1], "okx_demo_public_market_books_size_invalid")
            if not price.is_finite() or price <= 0 or not size.is_finite() or size <= 0:
                raise OkxDemoSafetyError("okx_demo_public_market_books_level_not_positive")
            count = "0"
            if len(raw) > 3 and raw[3] not in (None, ""):
                try:
                    parsed_count = int(str(raw[3]))
                except (TypeError, ValueError) as exc:
                    raise OkxDemoSafetyError("okx_demo_public_market_books_count_invalid") from exc
                if parsed_count < 0:
                    raise OkxDemoSafetyError("okx_demo_public_market_books_count_invalid")
                count = str(parsed_count)
            rows.append({"price": _decimal_text(price), "size": _decimal_text(size), "count": count})
        if rows != sorted(rows, key=lambda item: Decimal(item["price"]), reverse=reverse):
            raise OkxDemoSafetyError("okx_demo_public_market_books_not_sorted")
        return rows


class OkxDemoClient:
    def __init__(
        self,
        *,
        config: OkxDemoClientConfig,
        credentials: OkxDemoCredentials,
        transport: OkxDemoTransport | None = None,
        now_ms: Callable[[], int] | None = None,
        sleeper: Callable[[float], None] | None = None,
    ) -> None:
        self.config = config
        self._credentials = credentials
        self._transport = transport or UrllibOkxDemoTransport()
        self._now_ms = now_ms or (lambda: int(time.time() * 1_000))
        self._sleeper = sleeper or time.sleep

    def public_get(self, path: str, params: Mapping[str, Any] | None = None) -> OkxDemoResponse:
        if path not in OKX_DEMO_PUBLIC_PATHS:
            raise OkxDemoSafetyError("okx_demo_public_path_not_allowlisted")
        if path == "/api/v5/market/candles":
            normalized = dict(params or {})
            required = {"instId", "bar", "limit"}
            if set(normalized) not in (required, required | {"after"}):
                raise OkxDemoSafetyError(
                    "okx_demo_public_candles_params_not_allowlisted"
                )
            if normalized.get("instId") != OKX_DEMO_INSTRUMENT_ID:
                raise OkxDemoSafetyError(
                    "okx_demo_public_candles_instrument_not_allowlisted"
                )
            if normalized.get("bar") != "1H":
                raise OkxDemoSafetyError(
                    "okx_demo_public_candles_bar_must_be_1h"
                )
            try:
                limit = int(str(normalized.get("limit") or ""))
            except ValueError as exc:
                raise OkxDemoSafetyError(
                    "okx_demo_public_candles_limit_invalid"
                ) from exc
            if limit < 2 or limit > 100:
                raise OkxDemoSafetyError(
                    "okx_demo_public_candles_limit_out_of_bounds"
                )
            if "after" in normalized:
                after = normalized["after"]
                if (
                    not isinstance(after, str)
                    or len(after) != 13
                    or not after.isascii()
                    or not after.isdigit()
                    or after.startswith("0")
                    or int(after) > 9_999_999_999_999
                ):
                    raise OkxDemoSafetyError(
                        "okx_demo_public_candles_after_invalid"
                    )
        return self._request(method="GET", path=path, params=params, private=False)

    def private_get(self, path: str, params: Mapping[str, Any] | None = None) -> OkxDemoResponse:
        if not self.config.allow_private_read:
            raise OkxDemoSafetyError("okx_demo_private_read_disabled")
        if path not in OKX_DEMO_PRIVATE_READ_PATHS:
            raise OkxDemoSafetyError("okx_demo_private_read_path_not_allowlisted")
        normalized = self._validate_private_read_params(path, params)
        return self._request(method="GET", path=path, params=normalized, private=True)

    def submit_order(self, order: Mapping[str, Any]) -> OkxDemoResponse:
        if not self.config.allow_demo_orders:
            raise OkxDemoSafetyError("okx_demo_order_submit_disabled")
        normalized = self._validate_order(order)
        return self._request(method="POST", path="/api/v5/trade/order", body=normalized, private=True, order_request=True)

    def cancel_order(self, *, order_id: str = "", client_order_id: str = "") -> OkxDemoResponse:
        if not self.config.allow_demo_cancels:
            raise OkxDemoSafetyError("okx_demo_cancel_disabled")
        if not order_id and not client_order_id:
            raise OkxDemoSafetyError("okx_demo_cancel_identifier_missing")
        if client_order_id and (len(client_order_id) > 32 or not client_order_id.isalnum()):
            raise OkxDemoSafetyError("okx_demo_cancel_client_order_id_invalid")
        body: dict[str, Any] = {"instId": self.config.instrument_id}
        if order_id:
            body["ordId"] = order_id
        else:
            body["clOrdId"] = client_order_id
        return self._request(method="POST", path="/api/v5/trade/cancel-order", body=body, private=True)

    def cancel_algo_orders(
        self,
        orders: Sequence[Mapping[str, Any]],
    ) -> OkxDemoResponse:
        """Cancel an exact, bounded set of Demo algo orders without retrying.

        Ownership and flatness are deliberately *not* inferred here; the OMS
        controller must prove both before it can call this capability.
        """

        if not self.config.allow_demo_cancels:
            raise OkxDemoSafetyError("okx_demo_cancel_disabled")
        if isinstance(orders, (str, bytes)) or not 1 <= len(orders) <= 10:
            raise OkxDemoSafetyError("okx_demo_cancel_algos_batch_size_invalid")
        body: list[dict[str, str]] = []
        for row in orders:
            normalized = {str(key): str(value) for key, value in row.items()}
            if set(normalized) != {"algoId", "instId"}:
                raise OkxDemoSafetyError("okx_demo_cancel_algos_fields_invalid")
            algo_id = normalized["algoId"]
            if not algo_id or len(algo_id) > 32 or not algo_id.isalnum():
                raise OkxDemoSafetyError("okx_demo_cancel_algos_identifier_invalid")
            if normalized["instId"] != self.config.instrument_id:
                raise OkxDemoSafetyError(
                    "okx_demo_cancel_algos_instrument_not_allowlisted"
                )
            body.append({"algoId": algo_id, "instId": self.config.instrument_id})
        return self._request(
            method="POST",
            path="/api/v5/trade/cancel-algos",
            body=body,
            private=True,
        )

    def cancel_all_after(self, *, timeout_seconds: int, tag: str) -> OkxDemoResponse:
        """Arm or disarm the tagged dead-man switch with a narrow 50001 retry.

        ``cancel-all-after`` is the dedicated protective heartbeat path.  A
        transient OKX ``50001`` is retried only here, with the exact same
        timeout/tag payload and a bounded two-delay budget.  All other response
        codes and transport errors return/raise immediately; ordinary order,
        cancel, and algo POSTs continue to use the no-retry write path.
        """

        if not self.config.allow_demo_cancels:
            raise OkxDemoSafetyError("okx_demo_cancel_disabled")
        if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, int):
            raise OkxDemoSafetyError("okx_demo_cancel_all_after_timeout_invalid")
        if timeout_seconds != 0 and not 10 <= timeout_seconds <= 120:
            raise OkxDemoSafetyError("okx_demo_cancel_all_after_timeout_out_of_bounds")
        normalized_tag = _validate_order_tag(tag)
        body = {"timeOut": str(timeout_seconds), "tag": normalized_tag}
        for attempt in range(len(OKX_DEMO_DEAD_MAN_50001_RETRY_DELAYS_SECONDS) + 1):
            response = self._request(
                method="POST",
                path="/api/v5/trade/cancel-all-after",
                body=body,
                private=True,
                order_request=True,
            )
            if (
                response.code != "50001"
                or attempt >= len(OKX_DEMO_DEAD_MAN_50001_RETRY_DELAYS_SECONDS)
            ):
                return response
            self._sleeper(OKX_DEMO_DEAD_MAN_50001_RETRY_DELAYS_SECONDS[attempt])
        raise AssertionError("unreachable")

    def _validate_private_read_params(
        self,
        path: str,
        params: Mapping[str, Any] | None,
    ) -> dict[str, Any] | None:
        if path == "/api/v5/trade/order-algo":
            normalized = {str(key): value for key, value in (params or {}).items()}
            if set(normalized) not in ({"algoId"}, {"algoClOrdId"}):
                raise OkxDemoSafetyError("okx_demo_order_algo_query_params_invalid")
            identifier = str(next(iter(normalized.values())) or "")
            if not identifier or len(identifier) > 32 or not identifier.isalnum():
                raise OkxDemoSafetyError("okx_demo_order_algo_query_identifier_invalid")
            return normalized
        if path == "/api/v5/trade/orders-algo-pending":
            normalized = {str(key): value for key, value in (params or {}).items()}
            if set(normalized) != {"instId", "ordType"}:
                raise OkxDemoSafetyError("okx_demo_pending_algo_query_params_invalid")
            if normalized.get("instId") != self.config.instrument_id:
                raise OkxDemoSafetyError("okx_demo_pending_algo_instrument_not_allowlisted")
            if normalized.get("ordType") not in {"conditional", "oco"}:
                raise OkxDemoSafetyError("okx_demo_pending_algo_type_not_allowlisted")
            return normalized
        if path == "/api/v5/trade/orders-algo-history":
            normalized = {str(key): value for key, value in (params or {}).items()}
            selector_keys = set(normalized) - {"instId", "ordType"}
            if (
                not {"instId", "ordType"}.issubset(normalized)
                or selector_keys not in ({"state"}, {"algoId"})
            ):
                raise OkxDemoSafetyError("okx_demo_algo_history_query_params_invalid")
            if normalized.get("instId") != self.config.instrument_id:
                raise OkxDemoSafetyError("okx_demo_algo_history_instrument_not_allowlisted")
            if normalized.get("ordType") not in {"conditional", "oco"}:
                raise OkxDemoSafetyError("okx_demo_algo_history_type_not_allowlisted")
            if "state" in selector_keys:
                if normalized.get("state") not in {
                    "effective",
                    "canceled",
                    "order_failed",
                }:
                    raise OkxDemoSafetyError(
                        "okx_demo_algo_history_state_not_allowlisted"
                    )
            else:
                algo_id = str(normalized.get("algoId") or "")
                if not algo_id or len(algo_id) > 32 or not algo_id.isalnum():
                    raise OkxDemoSafetyError(
                        "okx_demo_algo_history_identifier_invalid"
                    )
                normalized["algoId"] = algo_id
            return normalized
        return dict(params) if params is not None else None

    def _validate_order(self, order: Mapping[str, Any]) -> dict[str, Any]:
        normalized = {str(key): value for key, value in order.items()}
        allowed_keys = {
            "instId",
            "tdMode",
            "side",
            "posSide",
            "ordType",
            "px",
            "sz",
            "clOrdId",
            "tag",
            "reduceOnly",
            "attachAlgoOrds",
        }
        if not set(normalized).issubset(allowed_keys):
            raise OkxDemoSafetyError("okx_demo_order_fields_not_allowlisted")
        if normalized.get("instId") != self.config.instrument_id:
            raise OkxDemoSafetyError("okx_demo_order_instrument_not_allowlisted")
        if normalized.get("tdMode") != "isolated":
            raise OkxDemoSafetyError("okx_demo_order_must_be_isolated")
        if normalized.get("ordType") not in {"fok", "ioc"}:
            raise OkxDemoSafetyError("okx_demo_order_type_not_allowlisted")
        if normalized.get("side") not in {"buy", "sell"}:
            raise OkxDemoSafetyError("okx_demo_order_side_not_allowlisted")
        if normalized.get("posSide") not in {"long", "short", "net"}:
            raise OkxDemoSafetyError("okx_demo_order_position_side_not_allowlisted")
        if not normalized.get("px"):
            raise OkxDemoSafetyError("okx_demo_order_price_required")
        client_order_id = str(normalized.get("clOrdId") or "")
        if not client_order_id or len(client_order_id) > 32 or not client_order_id.isalnum():
            raise OkxDemoSafetyError("okx_demo_client_order_id_invalid")
        normalized["tag"] = _validate_order_tag(normalized.get("tag"))
        contracts = _decimal(normalized.get("sz"), "okx_demo_order_size_invalid")
        if contracts <= 0 or contracts > Decimal(self.config.max_order_contracts):
            raise OkxDemoSafetyError("okx_demo_order_size_exceeds_cap")
        price = _decimal(normalized.get("px"), "okx_demo_order_price_invalid")
        notional = contracts * Decimal(self.config.contract_value_btc) * price
        if notional > Decimal(self.config.max_notional_usdt):
            raise OkxDemoSafetyError("okx_demo_order_notional_exceeds_cap")
        pos_side = str(normalized["posSide"])
        side = str(normalized["side"])
        reduce_only = normalized.get("reduceOnly") is True
        if pos_side == "net":
            is_opening = not reduce_only
        else:
            if "reduceOnly" in normalized:
                raise OkxDemoSafetyError("okx_demo_long_short_reduce_only_field_forbidden")
            is_opening = (pos_side == "long" and side == "buy") or (
                pos_side == "short" and side == "sell"
            )
        attached = normalized.get("attachAlgoOrds")
        if is_opening:
            if normalized.get("ordType") != "fok" and not (
                normalized.get("ordType") == "ioc"
                and self.config.allow_partial_fill_opening
            ):
                raise OkxDemoSafetyError("okx_demo_opening_order_must_be_fok")
            normalized["attachAlgoOrds"] = _validate_attached_protection(
                attached,
                entry_price=price,
                position_side=pos_side,
            )
        else:
            if normalized.get("ordType") != "ioc":
                raise OkxDemoSafetyError("okx_demo_closing_order_must_be_ioc")
            if attached not in (None, (), []):
                raise OkxDemoSafetyError("okx_demo_closing_order_cannot_attach_protection")
        return normalized

    def _request(
        self,
        *,
        method: str,
        path: str,
        params: Mapping[str, Any] | None = None,
        body: Any = None,
        private: bool,
        order_request: bool = False,
    ) -> OkxDemoResponse:
        query = urllib.parse.urlencode({str(key): str(value) for key, value in (params or {}).items()})
        request_path = path + (("?" + query) if query else "")
        body_text = "" if body is None else json.dumps(body, ensure_ascii=False, separators=(",", ":"))
        retry_delays = (
            OKX_DEMO_READ_RETRY_DELAYS_SECONDS if method == "GET" else ()
        )
        for attempt in range(len(retry_delays) + 1):
            headers = {
                "Accept": "application/json",
                "User-Agent": "quant-system-okx-demo/1.0",
            }
            if body is not None:
                headers["Content-Type"] = "application/json"
            if private:
                timestamp = datetime.now(timezone.utc).isoformat(
                    timespec="milliseconds"
                ).replace("+00:00", "Z")
                prehash = timestamp + method + request_path + body_text
                signature = base64.b64encode(
                    hmac.new(
                        self._credentials.secret_key.encode(),
                        prehash.encode(),
                        hashlib.sha256,
                    ).digest()
                ).decode()
                headers.update(
                    {
                        "OK-ACCESS-KEY": self._credentials.api_key,
                        "OK-ACCESS-SIGN": signature,
                        "OK-ACCESS-TIMESTAMP": timestamp,
                        "OK-ACCESS-PASSPHRASE": self._credentials.passphrase,
                        "x-simulated-trading": "1",
                    }
                )
            if order_request:
                headers["expTime"] = str(
                    self._now_ms() + int(self.config.order_expiry_ms)
                )
            try:
                response = self._transport.send(
                    method=method,
                    url=self.config.base_url + request_path,
                    headers=headers,
                    body=body_text.encode("utf-8") if body is not None else None,
                    timeout_seconds=float(self.config.timeout_seconds),
                )
            except OkxDemoTransportError:
                # A read can be repeated without creating exchange-side state.
                # Retry the failed request in place so one proxy/TLS reset does
                # not force the runtime to replay an entire authoritative
                # snapshot.  POST paths retain an empty retry budget and are
                # therefore still raised immediately without a blind retry.
                if attempt >= len(retry_delays):
                    raise
                self._sleeper(retry_delays[attempt])
                continue
            if (
                response.code not in OKX_DEMO_RECOVERABLE_READ_CODES
                or attempt >= len(retry_delays)
            ):
                return response
            self._sleeper(retry_delays[attempt])
        raise AssertionError("unreachable")


class OkxDemoReadOnlyClient:
    """Capability-minimal OKX Demo reader with no order or cancel methods.

    The wrapped transport may authenticate private GET requests, but this public
    surface cannot register or dispatch POST, cancel, transfer, or withdraw
    operations.  Remote supervision depends on this smaller capability object.
    """

    def __init__(
        self,
        *,
        config: OkxDemoClientConfig,
        credentials: OkxDemoCredentials,
        transport: OkxDemoTransport | None = None,
        now_ms: Callable[[], int] | None = None,
        sleeper: Callable[[float], None] | None = None,
    ) -> None:
        if config.allow_demo_orders or config.allow_demo_cancels:
            raise OkxDemoSafetyError(
                "okx_demo_read_only_client_write_capability_forbidden"
            )
        self._client = OkxDemoClient(
            config=config,
            credentials=credentials,
            transport=transport,
            now_ms=now_ms,
            sleeper=sleeper,
        )

    def public_get(
        self,
        path: str,
        params: Mapping[str, Any] | None = None,
    ) -> OkxDemoResponse:
        return self._client.public_get(path, params)

    def private_get(
        self,
        path: str,
        params: Mapping[str, Any] | None = None,
    ) -> OkxDemoResponse:
        return self._client.private_get(path, params)


class OkxDemoFaultInjectingClient:
    """Dependency-injection wrapper for bounded OKX Demo fault drills.

    It never retries a write.  ``post_response_loss`` delegates one actual Demo
    POST and drops only the returned acknowledgement.  Protection failure keeps
    the submitted attachment unchanged, then hides its activation on readback so
    the runtime's existing protection verification and risk-reduction path owns
    the safety response.
    """

    def __init__(
        self,
        client: Any,
        *,
        scenario: str,
        timeline: list[dict[str, Any]],
    ) -> None:
        self._client = client
        self._scenario = str(scenario)
        self._timeline = timeline
        self._post_response_dropped = False
        self._order_posted = False

    def public_get(
        self,
        path: str,
        params: Mapping[str, Any] | None = None,
    ) -> OkxDemoResponse:
        return self._client.public_get(path, params)

    def private_get(
        self,
        path: str,
        params: Mapping[str, Any] | None = None,
    ) -> OkxDemoResponse:
        if (
            self._scenario == "protection_creation_failure"
            and self._order_posted
            and path in {
                "/api/v5/trade/order-algo",
                "/api/v5/trade/orders-algo-pending",
            }
        ):
            self._timeline.append(
                {
                    "sequence": len(self._timeline) + 1,
                    "event": "attachment_activation_readback_missing",
                    "path": path,
                }
            )
            return OkxDemoResponse(
                method="GET",
                path=path,
                http_status=200,
                code="0",
                message="",
                data=(),
            )
        return self._client.private_get(path, params)

    def submit_order(self, order: Mapping[str, Any]) -> OkxDemoResponse:
        response = self._client.submit_order(order)
        self._order_posted = True
        self._timeline.append(
            {
                "sequence": len(self._timeline) + 1,
                "event": "demo_order_post_returned",
                "clOrdId": str(order.get("clOrdId") or ""),
                "algoClOrdId": str(
                    (
                        (order.get("attachAlgoOrds") or [{}])[0]
                        if isinstance(order.get("attachAlgoOrds"), list)
                        and order.get("attachAlgoOrds")
                        else {}
                    ).get("attachAlgoClOrdId")
                    or ""
                ),
            }
        )
        if (
            self._scenario == "post_response_loss"
            and not self._post_response_dropped
        ):
            self._post_response_dropped = True
            self._timeline.append(
                {
                    "sequence": len(self._timeline) + 1,
                    "event": "post_response_lost_after_exchange_response",
                    "clOrdId": str(order.get("clOrdId") or ""),
                }
            )
            raise OkxDemoTransportError(
                "okx_demo_fault_injected_post_response_loss"
            )
        return response

    def cancel_order(self, **payload: Any) -> OkxDemoResponse:
        return self._client.cancel_order(**payload)

    def cancel_algo_orders(self, orders: Sequence[Mapping[str, Any]]) -> OkxDemoResponse:
        return self._client.cancel_algo_orders(orders)

    def cancel_all_after(self, **payload: Any) -> OkxDemoResponse:
        return self._client.cancel_all_after(**payload)


def load_windows_keyring_credentials(service_name: str) -> OkxDemoCredentials:
    try:
        import keyring
    except ImportError as exc:
        raise OkxDemoSafetyError("python_keyring_not_installed") from exc
    backend = keyring.get_keyring()
    backend_name = f"{type(backend).__module__}.{type(backend).__name__}"
    if not backend_name.startswith("keyring.backends.Windows."):
        raise OkxDemoSafetyError("windows_keyring_backend_required")
    values = {name: keyring.get_password(service_name, name) for name in ("api_key", "secret_key", "passphrase")}
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise OkxDemoSafetyError("okx_demo_credential_entries_missing:" + ",".join(missing))
    return OkxDemoCredentials(
        api_key=str(values["api_key"]),
        secret_key=str(values["secret_key"]),
        passphrase=str(values["passphrase"]),
    )


def build_btc_usdt_swap_demo_probe_plan(
    *,
    account_config: Mapping[str, Any],
    instrument: Mapping[str, Any],
    ticker: Mapping[str, Any],
    max_notional_usdt: Decimal = Decimal("10"),
) -> OkxDemoProbePlan:
    blockers: list[str] = []
    permissions = {item.strip() for item in str(account_config.get("perm") or "").split(",") if item.strip()}
    position_mode = str(account_config.get("posMode") or "")
    if account_config.get("acctLv") != "2":
        blockers.append("okx_demo_account_not_contract_mode")
    if "trade" not in permissions:
        blockers.append("okx_demo_trade_permission_missing")
    if "withdraw" in permissions:
        blockers.append("okx_demo_withdraw_permission_present")
    if position_mode != "long_short_mode":
        blockers.append("okx_demo_p0_runtime_requires_long_short_mode")
    if instrument.get("instId") != OKX_DEMO_INSTRUMENT_ID:
        blockers.append("okx_demo_instrument_identity_mismatch")
    if instrument.get("state") != "live":
        blockers.append("okx_demo_instrument_not_live")
    if instrument.get("ctType") != "linear" or instrument.get("settleCcy") != "USDT":
        blockers.append("okx_demo_instrument_not_linear_usdt")

    tick_size = _positive_decimal(instrument.get("tickSz"), "okx_demo_tick_size_invalid", blockers)
    lot_size = _positive_decimal(instrument.get("lotSz"), "okx_demo_lot_size_invalid", blockers)
    min_size = _positive_decimal(instrument.get("minSz"), "okx_demo_min_size_invalid", blockers)
    contract_value = _positive_decimal(instrument.get("ctVal"), "okx_demo_contract_value_invalid", blockers)
    bid = _positive_decimal(ticker.get("bidPx"), "okx_demo_bid_missing", blockers)
    ask = _positive_decimal(ticker.get("askPx"), "okx_demo_ask_missing", blockers)
    minimum_contracts = max(lot_size, min_size)
    estimated_notional = minimum_contracts * contract_value * ask
    if estimated_notional > Decimal(max_notional_usdt):
        blockers.append("okx_demo_minimum_order_exceeds_notional_cap")
    if bid >= ask and bid > 0:
        blockers.append("okx_demo_ticker_crossed_or_invalid")

    stages: list[Mapping[str, Any]] = [
        {
            "stage": "oms_dry_run",
            "network_call": False,
            "order_endpoint_called": False,
            "purpose": "validate intent, venue rules, risk envelope, and audit linkage",
        },
        {
            "stage": "dead_man_contract_probe",
            "network_call": False,
            "planned_request": {
                "path": "/api/v5/trade/cancel-all-after",
                "timeOut": "30",
                "tag": "btcP0Demo",
            },
            "response_contract": "non_empty_triggerTime_tag_ts_ack_required",
            "positions_are_not_closed": True,
        },
        {
            "stage": "runtime_owned_protected_fok_open",
            "network_call": False,
            "direct_probe_order_disabled": True,
            "runtime_contract": (
                "durable_clOrdId_then_fok_with_hash_bound_attachAlgoOrds"
            ),
            "estimated_notional_usdt": _decimal_text(estimated_notional),
        },
        {
            "stage": "runtime_owned_ioc_risk_exit",
            "network_call": False,
            "direct_probe_order_disabled": True,
            "close_semantics": (
                "long_short_mode_opposite_side_same_posSide_ioc"
                if position_mode == "long_short_mode"
                else "net_mode_reduce_only_true_ioc"
            ),
        },
    ]
    safety = {
        "demo_environment_required": True,
        "private_read_used": True,
        "order_endpoint_called": False,
        "cancel_endpoint_called": False,
        "live_endpoint_called": False,
        "real_order_submitted": False,
        "paper_start": False,
        "paper_queue_write_allowed": False,
        "promotion_unlock_allowed": False,
    }
    return OkxDemoProbePlan(
        status="ready_for_explicit_demo_order_authorization" if not blockers else "blocked_fail_closed",
        blockers=tuple(dict.fromkeys(blockers)),
        instrument_id=OKX_DEMO_INSTRUMENT_ID,
        position_mode=position_mode,
        minimum_contracts=minimum_contracts,
        contract_value_btc=contract_value,
        estimated_notional_usdt=estimated_notional,
        max_notional_usdt=Decimal(max_notional_usdt),
        stages=tuple(stages),
        safety=safety,
    )


def _response(*, method: str, path: str, http_status: int, payload: Mapping[str, Any], duration_ms: float) -> OkxDemoResponse:
    rows = payload.get("data")
    data = (
        tuple(
            item
            for item in rows
            if isinstance(item, Mapping)
            or (path in OKX_DEMO_PUBLIC_PATHS and isinstance(item, (list, tuple)))
        )
        if isinstance(rows, list)
        else ()
    )
    return OkxDemoResponse(
        method=method,
        path=path,
        http_status=http_status,
        code=str(payload.get("code") if payload.get("code") is not None else ""),
        message=str(payload.get("msg") or "")[:160],
        data=data,
        duration_ms=round(float(duration_ms), 3),
    )


def _validate_order_tag(value: Any) -> str:
    tag = str(value or "")
    if not tag or len(tag) > 16 or not tag.isascii() or not tag.isalnum():
        raise OkxDemoSafetyError("okx_demo_order_tag_invalid")
    return tag


def _validate_attached_protection(
    value: Any,
    *,
    entry_price: Decimal,
    position_side: str,
) -> list[dict[str, str]]:
    if not isinstance(value, (list, tuple)) or len(value) != 1:
        raise OkxDemoSafetyError("okx_demo_attached_protection_required")
    raw = value[0]
    if not isinstance(raw, Mapping):
        raise OkxDemoSafetyError("okx_demo_attached_protection_invalid")
    allowed = {
        "attachAlgoClOrdId",
        "tpTriggerPx",
        "tpOrdPx",
        "tpTriggerPxType",
        "slTriggerPx",
        "slOrdPx",
        "slTriggerPxType",
    }
    normalized = {str(key): str(item) for key, item in raw.items()}
    if set(normalized) != allowed:
        raise OkxDemoSafetyError("okx_demo_attached_protection_fields_invalid")
    algo_client_order_id = normalized["attachAlgoClOrdId"]
    if (
        not algo_client_order_id
        or len(algo_client_order_id) > 32
        or not algo_client_order_id.isascii()
        or not algo_client_order_id.isalnum()
    ):
        raise OkxDemoSafetyError("okx_demo_attached_protection_id_invalid")
    if normalized["tpTriggerPxType"] != "mark" or normalized["slTriggerPxType"] != "mark":
        raise OkxDemoSafetyError("okx_demo_attached_protection_trigger_must_be_mark")
    if normalized["tpOrdPx"] != "-1" or normalized["slOrdPx"] != "-1":
        raise OkxDemoSafetyError("okx_demo_attached_protection_exit_must_be_market")
    take_profit = _decimal(
        normalized["tpTriggerPx"],
        "okx_demo_attached_take_profit_price_invalid",
    )
    stop_loss = _decimal(
        normalized["slTriggerPx"],
        "okx_demo_attached_stop_loss_price_invalid",
    )
    if take_profit <= 0 or stop_loss <= 0:
        raise OkxDemoSafetyError("okx_demo_attached_protection_price_not_positive")
    if position_side == "long":
        prices_valid = stop_loss < entry_price < take_profit
    elif position_side == "short":
        prices_valid = take_profit < entry_price < stop_loss
    else:
        raise OkxDemoSafetyError("okx_demo_net_opening_protection_not_supported")
    if not prices_valid:
        raise OkxDemoSafetyError("okx_demo_attached_protection_price_direction_invalid")
    return [normalized]


def _decimal(value: Any, blocker: str) -> Decimal:
    try:
        return Decimal(str(value))
    except Exception as exc:
        raise OkxDemoSafetyError(blocker) from exc


def _positive_decimal(value: Any, blocker: str, blockers: list[str]) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except Exception:
        blockers.append(blocker)
        return Decimal("0")
    if parsed <= 0:
        blockers.append(blocker)
        return Decimal("0")
    return parsed


def _public_timestamp_ms(value: Any, blocker: str) -> int:
    text = str(value or "")
    if len(text) != 13 or not text.isascii() or not text.isdigit() or text.startswith("0"):
        raise OkxDemoSafetyError(blocker)
    parsed = int(text)
    if parsed <= 0:
        raise OkxDemoSafetyError(blocker)
    return parsed


def _decimal_text(value: Decimal) -> str:
    return format(value.normalize(), "f")
