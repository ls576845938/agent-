"""Bounded, credential-free display reads; no Demo runtime or durable state."""
from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
from threading import RLock
import time
from typing import Any, Callable

from quant_crypto.oms.okx_demo import OKX_DEMO_INSTRUMENT_ID, OkxDemoPublicMarketClient


class BTCPublicMarketViewService:
    TIMEFRAMES = frozenset({"1m", "5m", "15m", "1h", "4h", "1d", "1w", "1M"})

    def __init__(
        self, *, client: OkxDemoPublicMarketClient | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        now_ms: Callable[[], int] | None = None,
    ) -> None:
        # This existing client has only allowlisted unsigned public GETs. In
        # particular, constructing this service never constructs Demo runtime.
        self._client = client or OkxDemoPublicMarketClient(timeout_seconds=5.0)
        self._monotonic = monotonic
        self._now_ms = now_ms or (lambda: int(time.time() * 1000))
        self._cache: OrderedDict[tuple, tuple[float, dict[str, Any]]] = OrderedDict()
        self._lock = RLock()

    def _envelope(self, kind: str, ticker: dict[str, Any]) -> dict[str, Any]:
        timestamp = int(ticker["timestamp_ms"])
        now = self._now_ms()
        stale = timestamp > now + 5000 or now - timestamp > 30000
        return {
            "schema_version": kind, "source_kind": kind,
            "instrument_id": OKX_DEMO_INSTRUMENT_ID,
            "read_only": True, "public_only": True,
            "private_endpoint_used": False, "order_endpoint_used": False,
            "strategy_signal_compatible": False, "persisted_market_rows": False,
            "captured_at_ms": now, "ticker": ticker,
            "stale": stale,
            "last_error_code": "okx_public_market_timestamp_stale" if stale else "",
        }

    def _cached(self, key: tuple, ttl: float, loader: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        # Serialize this small, display-only cache. No threads, subscriptions,
        # database writes, log replay or background retries are started here.
        with self._lock:
            cached = self._cache.get(key)
            now = self._monotonic()
            if cached is not None and now - cached[0] <= ttl:
                self._cache.move_to_end(key)
                return {**deepcopy(cached[1]), "cache_age_ms": max(0, int((now - cached[0]) * 1000))}
            try:
                payload = loader()
            except Exception as exc:
                if cached is not None:
                    return {
                        **deepcopy(cached[1]), "stale": True,
                        "cache_age_ms": max(0, int((self._monotonic() - cached[0]) * 1000)),
                        "last_error_code": "okx_public_market_unavailable",
                    }
                raise RuntimeError("okx_public_market_unavailable") from exc
            self._cache[key] = (self._monotonic(), deepcopy(payload))
            self._cache.move_to_end(key)
            while len(self._cache) > 32:
                self._cache.popitem(last=False)
            return {**payload, "cache_age_ms": 0}

    def view(self, *, timeframe: str, limit: int) -> dict[str, Any]:
        if timeframe not in self.TIMEFRAMES or type(limit) is not int or not 2 <= limit <= 300:
            raise ValueError("okx_public_market_query_invalid")

        def load() -> dict[str, Any]:
            payload = self._envelope("okx_public_market_view_v1", self._client.ticker())
            payload.update({"timeframe": timeframe, "candles": self._client.candles(timeframe=timeframe, limit=limit)})
            try:
                depth = self._client.books()
                age = self._now_ms() - int(depth["timestamp_ms"])
                if not -5000 <= age <= 30000:
                    raise ValueError("depth_timestamp_stale")
                payload.update({"depth": depth, "depth_source": "okx_public_rest_books5", "depth_error_code": ""})
            except Exception:
                # Missing depth does not invent a book or erase valid candles.
                payload.update({"depth": None, "depth_source": "unavailable", "depth_error_code": "okx_public_depth_unavailable"})
            return payload

        return self._cached(("view", timeframe, limit), 5.0 if timeframe == "1m" else 15.0, load)

    def ticker(self) -> dict[str, Any]:
        return self._cached(("ticker",), 2.0, lambda: self._envelope("okx_public_market_ticker_v1", self._client.ticker()))
