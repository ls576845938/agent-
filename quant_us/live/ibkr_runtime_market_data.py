"""Fail-closed, SDK-neutral IBKR runtime market-data boundary.

The adapter consumes an explicitly injected client.  Importing or constructing
it never imports an IBKR SDK, creates a socket, connects a Gateway, or falls
back to a research provider.  It accepts only completed IBKR bars whose
identity, market-data type, timing, session and sequence satisfy the semantic
contract used by the paper runtime.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import pandas as pd

from quant_us.core.calendar import USEquityCalendar
from quant_us.core.clock import ET, ensure_utc, utc_now
from quant_us.live.market_data_loop import MarketDataStatus


DEFAULT_SEMANTIC_CONTRACT_PATH = (
    Path(__file__).resolve().parents[2]
    / "configs"
    / "data"
    / "us_ibkr_yahoo_runtime_semantic_contract_v1.json"
)


class IBKRMarketDataType(str, Enum):
    LIVE = "live"
    FROZEN = "frozen"
    DELAYED = "delayed"
    DELAYED_FROZEN = "delayed-frozen"
    UNKNOWN = "unknown"


_MARKET_DATA_TYPE_BY_CODE = {
    1: IBKRMarketDataType.LIVE,
    2: IBKRMarketDataType.FROZEN,
    3: IBKRMarketDataType.DELAYED,
    4: IBKRMarketDataType.DELAYED_FROZEN,
}


@dataclass(frozen=True)
class IBKRRuntimeMarketDataConfig:
    symbols: tuple[str, ...]
    bar_size: str = "1d"
    require_live: bool = True
    use_rth: bool = True
    stale_after_seconds: float = 300.0
    expected_sec_type: str = "STK"
    expected_exchange: str = "SMART"
    expected_currency: str = "USD"
    provider_identity: str = "IBKR"
    corporate_action_entitlement_verified: bool = False
    require_adjusted_daily_bars: bool = True
    require_warmup: bool = False
    semantic_contract_path: Path = DEFAULT_SEMANTIC_CONTRACT_PATH

    def __post_init__(self) -> None:
        symbols = tuple(sorted({str(value).strip().upper() for value in self.symbols if value}))
        if not symbols:
            raise ValueError("ibkr_runtime_symbols_required")
        if str(self.bar_size).lower() not in {"1m", "5m", "15m", "30m", "1h", "1d"}:
            raise ValueError(f"ibkr_runtime_bar_size_not_supported:{self.bar_size}")
        if self.stale_after_seconds <= 0:
            raise ValueError("ibkr_runtime_stale_after_seconds_must_be_positive")
        object.__setattr__(self, "symbols", symbols)
        object.__setattr__(self, "bar_size", str(self.bar_size).lower())
        object.__setattr__(self, "semantic_contract_path", Path(self.semantic_contract_path))


@dataclass(frozen=True)
class IBKRMarketDataTransportConfig:
    """Public-market-data transport settings for an injected IBKR client.

    The transport deliberately has no connection method.  A caller must inject
    an already connected paper-session client and explicitly call ``start``.
    Daily strategy bars are triggered by IBKR real-time bars, then normalized
    from IBKR ``ADJUSTED_LAST`` history before they can reach the strategy.
    """

    symbols: tuple[str, ...]
    bar_size: str = "1d"
    use_rth: bool = True
    realtime_bar_seconds: int = 5
    warmup_duration: str = "2 Y"
    warmup_min_bars: int = 252

    def __post_init__(self) -> None:
        symbols = tuple(sorted({str(value).strip().upper() for value in self.symbols if value}))
        if not symbols:
            raise ValueError("ibkr_transport_symbols_required")
        if str(self.bar_size).lower() != "1d":
            raise ValueError("ibkr_transport_frozen_candidate_requires_1d")
        if self.realtime_bar_seconds != 5:
            raise ValueError("ibkr_transport_realtime_bar_seconds_must_be_5")
        if self.warmup_min_bars < 2:
            raise ValueError("ibkr_transport_warmup_min_bars_must_be_at_least_2")
        object.__setattr__(self, "symbols", symbols)
        object.__setattr__(self, "bar_size", "1d")


class IBKRSDKNeutralMarketDataTransport:
    """Lifecycle wrapper around injected IBKR public market-data surfaces.

    Supported client methods intentionally match the ib_insync/IB API names:
    ``reqMarketDataType``, ``reqMktData``, ``reqHistoricalData``,
    ``reqRealTimeBars``, ``cancelMktData`` and ``cancelRealTimeBars``.  No SDK
    is imported here and construction never connects or subscribes.
    """

    vendor = "ibkr"
    bar_size = "1d"

    def __init__(
        self,
        config: IBKRMarketDataTransportConfig,
        *,
        client: Any,
        contract_factory: Callable[[str], Any],
        now: Callable[[], datetime] = utc_now,
        calendar: USEquityCalendar | None = None,
    ) -> None:
        if not callable(contract_factory):
            raise TypeError("ibkr_transport_contract_factory_required")
        self.config = config
        self.symbols = list(config.symbols)
        self._client = client
        self._contract_factory = contract_factory
        self._now = now
        self._calendar = calendar or USEquityCalendar.with_holidays()
        self._started = False
        self._connection_epoch = 0
        self._contracts: dict[str, Any] = {}
        self._realtime_handles: dict[str, Any] = {}
        self._market_type_handles: dict[str, Any] = {}
        self._handle_cursors: dict[str, int] = {}
        self._buckets: dict[tuple[str, date], dict[str, float]] = {}
        self._emitted_sessions: set[tuple[str, date]] = set()
        self._warmup_rows: list[dict[str, Any]] = []
        self._completed_rows: list[dict[str, Any]] = []
        self._blockers: list[str] = []
        self._sequence = 0

    @property
    def started(self) -> bool:
        return self._started

    @property
    def connection_epoch(self) -> str:
        return f"ibkr-md-{self._connection_epoch}"

    @property
    def market_data_type(self) -> int:
        observed: list[int] = []
        for handle in self._market_type_handles.values():
            value = _int(_field(handle, "marketDataType", "market_data_type"))
            if value is not None:
                observed.append(value)
        fallback = _int(getattr(self._client, "market_data_type", None))
        if fallback is not None and fallback > 0:
            observed.append(fallback)
        if not observed or any(value != 1 for value in observed):
            return next((value for value in observed if value != 1), 0)
        return 1

    def isConnected(self) -> bool:  # noqa: N802 - mirrors the IB client surface
        return self._client_is_connected()

    def start(self) -> dict[str, Any]:
        if self._started:
            return self.transport_status()
        if not self._client_is_connected():
            raise RuntimeError("ibkr_market_data_client_disconnected")
        self._blockers = []
        self._warmup_rows = []
        self._connection_epoch += 1
        self._request_live_market_data_type()
        for symbol in self.symbols:
            contract = self._contract_factory(symbol)
            qualifier = getattr(self._client, "qualifyContracts", None) or getattr(
                self._client, "qualify_contracts", None
            )
            if callable(qualifier):
                qualified = list(qualifier(contract) or [])
                if qualified:
                    contract = qualified[0]
            self._contracts[symbol] = contract
            self._load_warmup(symbol, contract)
            self._market_type_handles[symbol] = self._request_market_type_probe(contract)
            handle = self._request_realtime_bars(contract)
            self._realtime_handles[symbol] = handle
            self._handle_cursors[symbol] = len(list(handle)) if _is_iterable_handle(handle) else 0
        waiter = getattr(self._client, "waitOnUpdate", None)
        if callable(waiter):
            try:
                waiter(timeout=1.0)
            except TimeoutError:
                pass
        self._started = True
        if self.market_data_type != 1:
            self._blockers.append("ibkr_market_data_type_not_confirmed_live")
        return self.transport_status()

    def stop(self) -> None:
        for symbol, handle in list(self._realtime_handles.items()):
            self._cancel_surface("cancelRealTimeBars", "cancel_realtime_bars", payload=handle)
            probe = self._market_type_handles.get(symbol)
            if probe is not None:
                self._cancel_surface("cancelMktData", "cancel_market_data", payload=self._contracts[symbol])
        self._realtime_handles.clear()
        self._market_type_handles.clear()
        self._handle_cursors.clear()
        self._started = False

    def restore_after_reconnect(self) -> dict[str, Any]:
        if not self._client_is_connected():
            raise RuntimeError("ibkr_market_data_client_disconnected")
        try:
            self.stop()
        except Exception:
            self._realtime_handles.clear()
            self._market_type_handles.clear()
            self._handle_cursors.clear()
            self._started = False
        return self.start()

    def poll_completed_bars(self) -> list[dict[str, Any]]:
        if not self._started:
            raise RuntimeError("ibkr_market_data_transport_not_started")
        if not self._client_is_connected():
            self._blockers = _dedupe([*self._blockers, "ibkr_market_data_client_disconnected"])
            return []
        if self.market_data_type != 1:
            self._blockers = _dedupe([*self._blockers, "ibkr_market_data_type_not_confirmed_live"])
        for symbol, handle in self._realtime_handles.items():
            rows = list(handle) if _is_iterable_handle(handle) else []
            cursor = self._handle_cursors.get(symbol, 0)
            for raw in rows[cursor:]:
                self._accumulate_realtime_bar(symbol, raw)
            self._handle_cursors[symbol] = len(rows)
        self._finalize_closed_sessions()
        rows, self._completed_rows = self._completed_rows, []
        return rows

    def fetch_warmup_bars(self) -> pd.DataFrame:
        return pd.DataFrame(self._warmup_rows).copy()

    def transport_status(self) -> dict[str, Any]:
        warmup_counts = {
            symbol: sum(1 for row in self._warmup_rows if row.get("symbol") == symbol)
            for symbol in self.symbols
        }
        warmup_ready = all(
            count >= self.config.warmup_min_bars for count in warmup_counts.values()
        )
        blockers = list(self._blockers)
        if not warmup_ready:
            blockers.append("ibkr_adjusted_warmup_insufficient")
        if self._started and self.market_data_type != 1:
            blockers.append("ibkr_market_data_type_not_confirmed_live")
        return {
            "started": self._started,
            "connected": self._client_is_connected(),
            "market_data_type": _market_data_type(self.market_data_type).value,
            "warmup_ready": warmup_ready,
            "warmup_counts": warmup_counts,
            "subscription_count": len(self._realtime_handles),
            "connection_epoch": self.connection_epoch,
            "blockers": _dedupe(blockers),
        }

    def _client_is_connected(self) -> bool:
        checker = getattr(self._client, "isConnected", None) or getattr(
            self._client, "is_connected", None
        )
        if callable(checker):
            try:
                return bool(checker())
            except Exception:
                return False
        return bool(getattr(self._client, "connected", False))

    def _request_live_market_data_type(self) -> None:
        method = getattr(self._client, "reqMarketDataType", None) or getattr(
            self._client, "request_market_data_type", None
        )
        if not callable(method):
            raise RuntimeError("ibkr_market_data_type_surface_missing")
        method(1)

    def _request_market_type_probe(self, contract: Any) -> Any:
        method = getattr(self._client, "reqMktData", None) or getattr(
            self._client, "request_market_data", None
        )
        if not callable(method):
            raise RuntimeError("ibkr_market_data_probe_surface_missing")
        return method(contract, "", False, False, [])

    def _request_realtime_bars(self, contract: Any) -> Any:
        method = getattr(self._client, "reqRealTimeBars", None) or getattr(
            self._client, "request_realtime_bars", None
        )
        if not callable(method):
            raise RuntimeError("ibkr_realtime_bar_surface_missing")
        return method(
            contract,
            self.config.realtime_bar_seconds,
            "TRADES",
            self.config.use_rth,
            [],
        )

    def _cancel_surface(self, *names: str, payload: Any) -> None:
        for name in names:
            method = getattr(self._client, name, None)
            if callable(method):
                method(payload)
                return

    def _request_adjusted_history(self, contract: Any, *, duration: str) -> list[Any]:
        method = getattr(self._client, "reqHistoricalData", None) or getattr(
            self._client, "request_historical_data", None
        )
        if not callable(method):
            raise RuntimeError("ibkr_adjusted_history_surface_missing")
        rows = method(
            contract,
            endDateTime="",
            durationStr=duration,
            barSizeSetting="1 day",
            whatToShow="ADJUSTED_LAST",
            useRTH=self.config.use_rth,
            formatDate=2,
            keepUpToDate=False,
        )
        return list(rows or [])

    def _load_warmup(self, symbol: str, contract: Any) -> None:
        now = ensure_utc(self._now())
        rows = self._request_adjusted_history(contract, duration=self.config.warmup_duration)
        normalized: list[dict[str, Any]] = []
        for raw in rows:
            session_date = _historical_session_date(_field(raw, "date", "time"))
            if session_date is None or not self._calendar.is_trading_day(session_date):
                continue
            close_timestamp = _session_close_utc(self._calendar, session_date)
            if close_timestamp >= now:
                continue
            row = _adjusted_history_row(
                raw,
                symbol=symbol,
                contract=contract,
                close_timestamp=close_timestamp,
                received_at=now,
                sequence=len(normalized) + 1,
                connection_epoch=self.connection_epoch,
                provenance="IBKR_ADJUSTED_LAST_WARMUP",
                warmup=True,
            )
            if row is not None:
                normalized.append(row)
        self._warmup_rows.extend(normalized)
        if len(normalized) < self.config.warmup_min_bars:
            self._blockers.append(f"ibkr_adjusted_warmup_insufficient:{symbol}")

    def _accumulate_realtime_bar(self, symbol: str, raw: Any) -> None:
        timestamp = _datetime(_field(raw, "time", "date", "timestamp"))
        if timestamp is None or not self._calendar.is_regular_session(timestamp):
            return
        session_date = timestamp.astimezone(ET).date()
        values = {name: _float(_field(raw, name)) for name in ("open", "high", "low", "close", "volume")}
        if any(value is None for value in values.values()):
            self._blockers.append("ibkr_realtime_bar_non_finite")
            return
        key = (symbol, session_date)
        bucket = self._buckets.get(key)
        if bucket is None:
            self._buckets[key] = {
                "open": float(values["open"]),
                "high": float(values["high"]),
                "low": float(values["low"]),
                "close": float(values["close"]),
                "volume": float(values["volume"]),
            }
            return
        bucket["high"] = max(bucket["high"], float(values["high"]))
        bucket["low"] = min(bucket["low"], float(values["low"]))
        bucket["close"] = float(values["close"])
        bucket["volume"] += float(values["volume"])

    def _finalize_closed_sessions(self) -> None:
        now = ensure_utc(self._now())
        for (symbol, session_date), _bucket in sorted(self._buckets.items()):
            key = (symbol, session_date)
            if key in self._emitted_sessions:
                continue
            close_timestamp = _session_close_utc(self._calendar, session_date)
            if now < close_timestamp + timedelta(seconds=self.config.realtime_bar_seconds):
                continue
            adjusted = self._adjusted_close_row(symbol, session_date, close_timestamp, now)
            if adjusted is None:
                self._blockers.append(f"ibkr_adjusted_close_missing:{symbol}:{session_date}")
                continue
            self._sequence += 1
            adjusted["source_sequence"] = self._sequence
            self._completed_rows.append(adjusted)
            self._emitted_sessions.add(key)

    def _adjusted_close_row(
        self,
        symbol: str,
        session_date: date,
        close_timestamp: datetime,
        received_at: datetime,
    ) -> dict[str, Any] | None:
        contract = self._contracts[symbol]
        for raw in reversed(self._request_adjusted_history(contract, duration="5 D")):
            if _historical_session_date(_field(raw, "date", "time")) != session_date:
                continue
            return _adjusted_history_row(
                raw,
                symbol=symbol,
                contract=contract,
                close_timestamp=close_timestamp,
                received_at=received_at,
                sequence=self._sequence + 1,
                connection_epoch=self.connection_epoch,
                provenance="IBKR_ADJUSTED_LAST_CLOSE_REFRESH",
                warmup=False,
            )
        return None


@dataclass(frozen=True)
class IBKRCanonicalBar:
    con_id: int
    symbol: str
    sec_type: str
    exchange: str
    currency: str
    event_timestamp_utc: datetime
    receive_timestamp_utc: datetime
    source_sequence: int
    source_identity: str
    market_data_type: IBKRMarketDataType
    connection_epoch: str
    trading_date_et: date
    session: str
    bar_size: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    completed: bool = True
    adjusted: bool = False
    corporate_action_status: str = "none_observed"
    semantic_parity_verified: bool = False
    normalization_provenance: str = ""
    normalization_sha256: str = ""

    def to_row(self) -> dict[str, Any]:
        return {
            "con_id": self.con_id,
            "symbol": self.symbol,
            "sec_type": self.sec_type,
            "exchange": self.exchange,
            "currency": self.currency,
            "timestamp_utc": self.event_timestamp_utc,
            "event_timestamp_utc": self.event_timestamp_utc,
            "receive_timestamp_utc": self.receive_timestamp_utc,
            "source_sequence": self.source_sequence,
            "source": self.source_identity,
            "source_identity": self.source_identity,
            "market_data_type": self.market_data_type.value,
            "connection_epoch": self.connection_epoch,
            "trading_date_et": self.trading_date_et.isoformat(),
            "session": self.session,
            "bar_size": self.bar_size,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "completed": self.completed,
            "adjusted": self.adjusted,
            "corporate_action_status": self.corporate_action_status,
            "semantic_parity_verified": self.semantic_parity_verified,
            "normalization_provenance": self.normalization_provenance,
            "normalization_sha256": self.normalization_sha256,
        }


@dataclass(frozen=True)
class SemanticParityResult:
    status: str
    contract_id: str
    contract_version: str
    contract_sha256: str
    sessions_compared: int
    return_pairs_compared: int
    maximum_return_difference: float | None
    blockers: tuple[str, ...] = field(default_factory=tuple)

    @property
    def passed(self) -> bool:
        return self.status == "passed"

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "contract_id": self.contract_id,
            "contract_version": self.contract_version,
            "contract_sha256": self.contract_sha256,
            "sessions_compared": self.sessions_compared,
            "return_pairs_compared": self.return_pairs_compared,
            "maximum_return_difference": self.maximum_return_difference,
            "blockers": list(self.blockers),
            "paper_submit_allowed": False,
            "live_allowed": False,
            "promotion_allowed": False,
        }


def stable_payload_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def load_semantic_contract(path: str | Path = DEFAULT_SEMANTIC_CONTRACT_PATH) -> dict[str, Any]:
    contract_path = Path(path)
    payload = json.loads(contract_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("contract"), dict):
        raise ValueError("ibkr_semantic_contract_object_required")
    actual = stable_payload_sha256(payload["contract"])
    if actual != str(payload.get("contract_sha256", "")):
        raise ValueError("ibkr_semantic_contract_hash_mismatch")
    return payload


class IBKRRuntimeMarketDataAdapter:
    """Normalize injected IBKR bars into the canonical PaperRuntime cache shape."""

    def __init__(
        self,
        config: IBKRRuntimeMarketDataConfig,
        *,
        client: Any | None = None,
        now: Callable[[], datetime] = utc_now,
        calendar: USEquityCalendar | None = None,
    ) -> None:
        self.config = config
        self.symbols = list(config.symbols)
        self.vendor = "ibkr"
        self.bar_size = config.bar_size
        self._client = client
        self._now = now
        self._calendar = calendar or USEquityCalendar.with_holidays()
        self._contract = load_semantic_contract(config.semantic_contract_path)
        self._contract_hash = str(self._contract["contract_sha256"])
        self._last_status: MarketDataStatus | None = None
        self._last_frame = pd.DataFrame()
        self._last_sequence: dict[tuple[str, str], int] = {}
        self._last_timestamp: dict[tuple[str, str], datetime] = {}
        self._last_receive_timestamp: dict[tuple[str, str], datetime] = {}
        self._last_epoch: dict[tuple[str, str], str] = {}
        self._accepted_keys: set[tuple[str, str, datetime]] = set()

    @property
    def semantic_contract(self) -> dict[str, Any]:
        return dict(self._contract)

    @property
    def semantic_contract_hash(self) -> str:
        return self._contract_hash

    @property
    def last_status(self) -> MarketDataStatus | None:
        return self._last_status

    def start(self) -> dict[str, Any]:
        starter = getattr(self._client, "start", None)
        if not callable(starter):
            return {"started": False, "blockers": ["ibkr_market_data_transport_start_surface_missing"]}
        return dict(starter())

    def stop(self) -> None:
        stopper = getattr(self._client, "stop", None)
        if callable(stopper):
            stopper()

    def restore_after_reconnect(self) -> dict[str, Any]:
        restore = getattr(self._client, "restore_after_reconnect", None)
        if not callable(restore):
            raise RuntimeError("ibkr_market_data_restore_surface_missing")
        self._accepted_keys.clear()
        self._last_sequence.clear()
        self._last_epoch.clear()
        return dict(restore())

    def fetch_warmup_bars(self) -> pd.DataFrame:
        fetcher = getattr(self._client, "fetch_warmup_bars", None)
        if not callable(fetcher):
            return pd.DataFrame()
        values = fetcher()
        return values.copy() if isinstance(values, pd.DataFrame) else pd.DataFrame(values)

    def semantic_gate_status(self) -> dict[str, Any]:
        transport = self._transport_status()
        blockers = list(getattr(self._last_status, "blockers", []) or [])
        blockers.extend(transport.get("blockers", []))
        if self.config.require_warmup and not transport.get("warmup_ready", False):
            blockers.append("ibkr_adjusted_warmup_not_ready")
        frame = self._last_frame
        if not frame.empty and not bool(frame["semantic_parity_verified"].all()):
            blockers.append("ibkr_runtime_semantic_parity_not_verified")
        return {
            "ok": self._last_status is not None
            and bool(self._last_status.fresh)
            and not _dedupe(blockers),
            "semantic_parity_verified": bool(
                not frame.empty and frame["semantic_parity_verified"].all()
            ),
            "adjusted_daily_bars": bool(not frame.empty and frame["adjusted"].all()),
            "transport": transport,
            "blockers": _dedupe(blockers),
        }

    def run_once(self) -> MarketDataStatus:
        blockers: list[str] = []
        accepted: list[IBKRCanonicalBar] = []
        dropped = 0
        transport = self._transport_status()
        blockers.extend(transport.get("blockers", []))
        if not self._client_is_connected():
            blockers.append("ibkr_market_data_client_disconnected")
        else:
            try:
                raw_bars = self._poll_raw_bars()
            except Exception as exc:
                raw_bars = []
                blockers.append(f"ibkr_market_data_poll_failed:{type(exc).__name__}")
            for raw in raw_bars:
                bar, reasons = self._normalise(raw)
                if reasons:
                    blockers.extend(reasons)
                    dropped += 1
                    continue
                assert bar is not None
                accepted_now, sequence_reason = self._sequence_accepts(bar)
                if not accepted_now:
                    dropped += 1
                    if sequence_reason and sequence_reason != "duplicate_replay":
                        blockers.append(sequence_reason)
                    continue
                accepted.append(bar)

        symbols_updated = sorted({bar.symbol for bar in accepted})
        missing = sorted(set(self.symbols) - set(symbols_updated))
        if missing and accepted:
            blockers.append("ibkr_market_data_missing_symbols:" + ",".join(missing))
        now = ensure_utc(self._now())
        latest = max((bar.event_timestamp_utc for bar in accepted), default=None)
        stale_seconds = max(
            (max(0.0, (now - bar.receive_timestamp_utc).total_seconds()) for bar in accepted),
            default=float("inf"),
        )
        blockers = _dedupe(blockers)
        duplicate_replay_only = not accepted and dropped > 0 and not blockers
        if duplicate_replay_only:
            latest = max(self._last_timestamp.values(), default=None)
            stale_seconds = max(
                (
                    max(0.0, (now - received_at).total_seconds())
                    for received_at in self._last_receive_timestamp.values()
                ),
                default=float("inf"),
            )
            if stale_seconds > self.config.stale_after_seconds:
                blockers.append("ibkr_market_data_stale")
        self._last_frame = pd.DataFrame([bar.to_row() for bar in accepted])
        self._last_status = MarketDataStatus(
            fresh=(bool(accepted) or duplicate_replay_only) and not blockers,
            stale_seconds=stale_seconds,
            latest_timestamp=latest,
            symbols_updated=symbols_updated,
            error=";".join(blockers) if blockers else None,
            source="ibkr",
            market_data_type=(
                accepted[0].market_data_type.value
                if accepted
                else IBKRMarketDataType.LIVE.value
                if duplicate_replay_only
                else IBKRMarketDataType.UNKNOWN.value
            ),
            semantic_contract_hash=self._contract_hash,
            blockers=blockers,
            dropped_count=dropped,
        )
        return self._last_status

    def fetch_latest_bars(self) -> pd.DataFrame:
        """Return only the bars accepted by the most recent poll.

        This deliberately never queries Yahoo or another fallback and does not
        re-poll the injected client, so a PaperRuntime cycle sees each source
        batch exactly once.
        """

        return self._last_frame.copy()

    def write_to_cache(self, _bars: pd.DataFrame) -> None:
        """The injected runtime adapter is read-through; persistence is external."""

    def _client_is_connected(self) -> bool:
        if self._client is None:
            return False
        for name in ("isConnected", "is_connected"):
            checker = getattr(self._client, name, None)
            if callable(checker):
                try:
                    return bool(checker())
                except Exception:
                    return False
        return bool(getattr(self._client, "connected", False))

    def _transport_status(self) -> dict[str, Any]:
        getter = getattr(self._client, "transport_status", None)
        if callable(getter):
            try:
                value = getter()
            except Exception as exc:
                return {
                    "warmup_ready": False,
                    "blockers": [f"ibkr_market_data_transport_status_failed:{type(exc).__name__}"],
                }
            return dict(value) if isinstance(value, Mapping) else {
                "warmup_ready": False,
                "blockers": ["ibkr_market_data_transport_status_invalid"],
            }
        return {"warmup_ready": not self.config.require_warmup, "blockers": []}

    def _poll_raw_bars(self) -> list[Any]:
        if self._client is None:
            return []
        for name in ("poll_completed_bars", "completed_bars", "poll_bars"):
            value = getattr(self._client, name, None)
            if callable(value):
                value = value()
            if value is not None:
                return list(value)
        raise RuntimeError("ibkr_market_data_poll_surface_missing")

    def _normalise(self, raw: Any) -> tuple[IBKRCanonicalBar | None, list[str]]:
        reasons: list[str] = []
        contract = _field(raw, "contract", default=raw)
        con_id = _int(_field(contract, "conId", "con_id", default=_field(raw, "conId", "con_id")))
        symbol = str(_field(contract, "symbol", default=_field(raw, "symbol", default=""))).upper()
        sec_type = str(_field(contract, "secType", "sec_type", default="")).upper()
        exchange = str(_field(contract, "exchange", default="")).upper()
        currency = str(_field(contract, "currency", default="")).upper()
        source_identity = str(
            _field(raw, "source_identity", "provider", "source", default=self.config.provider_identity)
        ).strip()
        completed = bool(_field(raw, "completed", "is_complete", "final", default=False))
        sequence = _int(_field(raw, "source_sequence", "sequence", "seq"))
        epoch = str(_field(raw, "connection_epoch", "subscription_epoch", default="0"))
        event_timestamp = _datetime(
            _field(raw, "event_timestamp_utc", "timestamp_utc", "timestamp", "time")
        )
        receive_timestamp = _datetime(
            _field(raw, "receive_timestamp_utc", "received_at", default=self._now())
        )
        market_data_type = _market_data_type(
            _field(raw, "market_data_type", "marketDataType", default=getattr(self._client, "market_data_type", None))
        )

        if con_id is None or con_id <= 0:
            reasons.append("ibkr_market_data_con_id_invalid")
        if symbol not in set(self.symbols):
            reasons.append("ibkr_market_data_symbol_mismatch")
        if sec_type != self.config.expected_sec_type:
            reasons.append("ibkr_market_data_sec_type_mismatch")
        if exchange != self.config.expected_exchange:
            reasons.append("ibkr_market_data_exchange_mismatch")
        if currency != self.config.expected_currency:
            reasons.append("ibkr_market_data_currency_mismatch")
        if not source_identity.upper().startswith("IBKR"):
            reasons.append("ibkr_runtime_research_or_unknown_source_forbidden")
        if not completed:
            reasons.append("ibkr_market_data_incomplete_bar")
        if sequence is None or sequence < 0:
            reasons.append("ibkr_market_data_sequence_missing")
        if event_timestamp is None or receive_timestamp is None:
            reasons.append("ibkr_market_data_timestamp_invalid")
        if self.config.require_live and market_data_type is not IBKRMarketDataType.LIVE:
            reasons.append(f"ibkr_market_data_type_not_live:{market_data_type.value}")
        if reasons:
            return None, reasons

        assert con_id is not None and sequence is not None
        assert event_timestamp is not None and receive_timestamp is not None
        now = ensure_utc(self._now())
        if event_timestamp > now:
            reasons.append("ibkr_market_data_future_bar")
        stale_seconds = max(0.0, (now - receive_timestamp).total_seconds())
        if stale_seconds > self.config.stale_after_seconds:
            reasons.append("ibkr_market_data_stale")
        trading_date = event_timestamp.astimezone(ET).date()
        session = str(_field(raw, "session", default="regular")).lower()
        if self.config.use_rth:
            if session not in {"regular", "rth"}:
                reasons.append("ibkr_market_data_extended_hours_forbidden")
            if not self._calendar.is_trading_day(trading_date):
                reasons.append("ibkr_market_data_non_trading_day")
            if not self._is_valid_completed_rth_bar(event_timestamp, trading_date):
                reasons.append("ibkr_market_data_rth_close_mismatch")

        values = {
            name: _float(_field(raw, name))
            for name in ("open", "high", "low", "close", "volume")
        }
        if any(value is None for value in values.values()):
            reasons.append("ibkr_market_data_non_finite_ohlcv")
        elif (
            values["open"] <= 0
            or values["high"] <= 0
            or values["low"] <= 0
            or values["close"] <= 0
            or values["volume"] < 0
            or values["high"] < max(values["open"], values["close"], values["low"])
            or values["low"] > min(values["open"], values["close"], values["high"])
        ):
            reasons.append("ibkr_market_data_ohlcv_invariant_failed")

        action_status = str(_field(raw, "corporate_action_status", default="none_observed"))
        split_factor = _float(_field(raw, "split_factor", default=1.0))
        dividend = _float(_field(raw, "dividend", default=0.0))
        action_present = (split_factor not in {None, 1.0}) or (dividend not in {None, 0.0})
        entitlement_verified = bool(
            _field(
                raw,
                "corporate_action_entitlement_verified",
                default=self.config.corporate_action_entitlement_verified,
            )
        )
        adjusted = bool(_field(raw, "adjusted", default=False))
        semantic_parity_verified = bool(
            _field(raw, "semantic_parity_verified", default=False)
        )
        normalization_provenance = str(
            _field(raw, "normalization_provenance", default="")
        ).strip()
        normalization_sha256 = str(
            _field(raw, "normalization_sha256", default="")
        ).strip().lower()
        if not entitlement_verified:
            reasons.append("ibkr_corporate_action_entitlement_unverified")
        if self.config.bar_size == "1d" and self.config.require_adjusted_daily_bars:
            if not adjusted:
                reasons.append("ibkr_adjusted_daily_bar_required")
            if not semantic_parity_verified:
                reasons.append("ibkr_runtime_semantic_parity_not_verified")
            if not normalization_provenance.upper().startswith("IBKR_ADJUSTED_LAST"):
                reasons.append("ibkr_adjusted_daily_provenance_invalid")
            if len(normalization_sha256) != 64 or any(
                char not in "0123456789abcdef" for char in normalization_sha256
            ):
                reasons.append("ibkr_adjusted_daily_hash_invalid")
            else:
                expected_normalization_sha256 = stable_payload_sha256(
                    {
                        "identity": {
                            "conId": con_id,
                            "symbol": symbol,
                            "secType": sec_type,
                            "exchange": exchange,
                            "currency": currency,
                        },
                        "trading_date_et": trading_date.isoformat(),
                        "open": float(values["open"]),
                        "high": float(values["high"]),
                        "low": float(values["low"]),
                        "close": float(values["close"]),
                        "volume": float(values["volume"]),
                        "provenance": normalization_provenance,
                    }
                )
                if normalization_sha256 != expected_normalization_sha256:
                    reasons.append("ibkr_adjusted_daily_hash_mismatch")
        if action_present and (
            action_status not in {"verified", "normalized"}
            or not adjusted
            or not semantic_parity_verified
        ):
            reasons.append("ibkr_corporate_action_not_normalized_fail_closed")
        if reasons:
            return None, reasons

        return IBKRCanonicalBar(
            con_id=con_id,
            symbol=symbol,
            sec_type=sec_type,
            exchange=exchange,
            currency=currency,
            event_timestamp_utc=event_timestamp,
            receive_timestamp_utc=receive_timestamp,
            source_sequence=sequence,
            source_identity=source_identity,
            market_data_type=market_data_type,
            connection_epoch=epoch,
            trading_date_et=trading_date,
            session="regular" if session == "rth" else session,
            bar_size=self.config.bar_size,
            open=float(values["open"]),
            high=float(values["high"]),
            low=float(values["low"]),
            close=float(values["close"]),
            volume=float(values["volume"]),
            adjusted=adjusted,
            corporate_action_status=action_status,
            semantic_parity_verified=semantic_parity_verified,
            normalization_provenance=normalization_provenance,
            normalization_sha256=normalization_sha256,
        ), []

    def _is_valid_completed_rth_bar(self, timestamp_utc: datetime, trading_date: date) -> bool:
        if self.config.bar_size != "1d":
            return self._calendar.is_regular_session(timestamp_utc - timedelta(microseconds=1))
        close_time = self._calendar.early_close_time if self._calendar.is_early_close(trading_date) else time(16, 0)
        expected = datetime.combine(trading_date, close_time, tzinfo=ET).astimezone(timezone.utc)
        return timestamp_utc == expected

    def _sequence_accepts(self, bar: IBKRCanonicalBar) -> tuple[bool, str]:
        key = (bar.symbol, bar.bar_size)
        replay_key = (bar.symbol, bar.bar_size, bar.event_timestamp_utc)
        last_timestamp = self._last_timestamp.get(key)
        last_sequence = self._last_sequence.get(key)
        last_epoch = self._last_epoch.get(key)
        if replay_key in self._accepted_keys:
            return False, "duplicate_replay"
        if last_timestamp is not None and bar.event_timestamp_utc <= last_timestamp:
            return False, "ibkr_market_data_out_of_order"
        if last_epoch == bar.connection_epoch and last_sequence is not None:
            if bar.source_sequence <= last_sequence:
                return False, "ibkr_market_data_out_of_order"
            if bar.source_sequence > last_sequence + 1:
                return False, "ibkr_market_data_sequence_gap"
        self._last_timestamp[key] = bar.event_timestamp_utc
        self._last_receive_timestamp[key] = bar.receive_timestamp_utc
        self._last_sequence[key] = bar.source_sequence
        self._last_epoch[key] = bar.connection_epoch
        self._accepted_keys.add(replay_key)
        return True, ""


def compare_yahoo_research_to_ibkr_runtime(
    yahoo_bars: Sequence[Mapping[str, Any]] | pd.DataFrame,
    ibkr_bars: Sequence[Mapping[str, Any]] | pd.DataFrame,
    *,
    corporate_actions: Sequence[Mapping[str, Any]] = (),
    corporate_action_entitlement_verified: bool = False,
    contract_path: str | Path = DEFAULT_SEMANTIC_CONTRACT_PATH,
) -> SemanticParityResult:
    """Compare session return semantics, never adjusted/raw absolute prices."""

    contract_envelope = load_semantic_contract(contract_path)
    contract = contract_envelope["contract"]
    blockers: list[str] = []
    if not corporate_action_entitlement_verified:
        blockers.append("semantic_parity_corporate_action_entitlement_unverified_fail_closed")
    yahoo = _session_close_map(
        yahoo_bars,
        expected_source="yahoo",
        blockers=blockers,
        require_adjusted=False,
    )
    ibkr = _session_close_map(
        ibkr_bars,
        expected_source="ibkr",
        blockers=blockers,
        require_adjusted=True,
    )
    shared = sorted(set(yahoo) & set(ibkr))
    missing_yahoo = sorted(set(ibkr) - set(yahoo))
    missing_ibkr = sorted(set(yahoo) - set(ibkr))
    if missing_yahoo:
        blockers.append("semantic_parity_yahoo_session_missing")
    if missing_ibkr:
        blockers.append("semantic_parity_ibkr_session_missing")

    for action in corporate_actions:
        action_type = str(action.get("action_type", "")).lower()
        if action_type not in {"split", "dividend"}:
            continue
        if str(action.get("status", "")).lower() != "verified":
            blockers.append(f"semantic_parity_{action_type}_unverified_fail_closed")

    tolerance = float(contract["numerical_parity_tolerance"]["session_return_absolute"])
    diffs: list[float] = []
    for previous, current in zip(shared, shared[1:]):
        yahoo_return = yahoo[current] / yahoo[previous] - 1.0
        ibkr_return = ibkr[current] / ibkr[previous] - 1.0
        difference = abs(yahoo_return - ibkr_return)
        diffs.append(difference)
        if difference > tolerance:
            blockers.append("semantic_parity_session_return_tolerance_breached")
    if len(shared) < 2:
        blockers.append("semantic_parity_insufficient_shared_sessions")
    blockers = _dedupe(blockers)
    return SemanticParityResult(
        status="blocked_fail_closed" if blockers else "passed",
        contract_id=str(contract_envelope["contract_id"]),
        contract_version=str(contract_envelope["contract_version"]),
        contract_sha256=str(contract_envelope["contract_sha256"]),
        sessions_compared=len(shared),
        return_pairs_compared=len(diffs),
        maximum_return_difference=max(diffs) if diffs else None,
        blockers=tuple(blockers),
    )


def _session_close_map(
    values: Sequence[Mapping[str, Any]] | pd.DataFrame,
    *,
    expected_source: str,
    blockers: list[str],
    require_adjusted: bool,
) -> dict[date, float]:
    rows = values.to_dict("records") if isinstance(values, pd.DataFrame) else list(values)
    result: dict[date, float] = {}
    for row in rows:
        source = str(row.get("source", expected_source)).lower()
        if expected_source not in source:
            blockers.append(f"semantic_parity_{expected_source}_source_identity_mismatch")
            continue
        if require_adjusted:
            if not bool(row.get("adjusted", False)):
                blockers.append("semantic_parity_ibkr_adjusted_daily_required")
                continue
            if not bool(row.get("semantic_parity_verified", False)):
                blockers.append("semantic_parity_ibkr_normalization_unverified")
                continue
            provenance = str(row.get("normalization_provenance", ""))
            digest = str(row.get("normalization_sha256", ""))
            if not provenance.upper().startswith("IBKR_ADJUSTED_LAST"):
                blockers.append("semantic_parity_ibkr_normalization_provenance_invalid")
                continue
            if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest.lower()):
                blockers.append("semantic_parity_ibkr_normalization_hash_invalid")
                continue
        session = str(row.get("session", "regular")).lower()
        if session not in {"regular", "rth"}:
            continue
        trading_date = row.get("trading_date_et") or row.get("trading_date")
        if isinstance(trading_date, date):
            session_date = trading_date
        else:
            try:
                session_date = date.fromisoformat(str(trading_date))
            except ValueError:
                blockers.append("semantic_parity_trading_date_invalid")
                continue
        close = _float(row.get("close"))
        if close is None or close <= 0:
            blockers.append("semantic_parity_close_invalid")
            continue
        if session_date in result:
            blockers.append("semantic_parity_duplicate_session")
            continue
        result[session_date] = close
    return result


def _field(value: Any, *names: str, default: Any = None) -> Any:
    for name in names:
        if isinstance(value, Mapping) and name in value:
            candidate = value[name]
        else:
            candidate = getattr(value, name, None)
        if candidate is not None:
            return candidate
    return default


def _float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return None
        return ensure_utc(value)
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return None
        return ensure_utc(parsed)
    return None


def _market_data_type(value: Any) -> IBKRMarketDataType:
    if isinstance(value, IBKRMarketDataType):
        return value
    if isinstance(value, int):
        return _MARKET_DATA_TYPE_BY_CODE.get(value, IBKRMarketDataType.UNKNOWN)
    normalized = str(value or "").strip().lower().replace("_", "-")
    for item in IBKRMarketDataType:
        if normalized == item.value:
            return item
    return IBKRMarketDataType.UNKNOWN


def _is_iterable_handle(value: Any) -> bool:
    if isinstance(value, (str, bytes, Mapping)):
        return False
    try:
        iter(value)
    except TypeError:
        return False
    return True


def _historical_session_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.date()
        return ensure_utc(value).astimezone(ET).date()
    if isinstance(value, date):
        return value
    raw = str(value or "").strip()
    if not raw:
        return None
    for candidate in (raw, raw[:10]):
        try:
            return date.fromisoformat(candidate)
        except ValueError:
            pass
    if len(raw) >= 8 and raw[:8].isdigit():
        try:
            return datetime.strptime(raw[:8], "%Y%m%d").date()
        except ValueError:
            return None
    return None


def _session_close_utc(calendar: USEquityCalendar, session_date: date) -> datetime:
    close_time = calendar.early_close_time if calendar.is_early_close(session_date) else time(16, 0)
    return datetime.combine(session_date, close_time, tzinfo=ET).astimezone(timezone.utc)


def _adjusted_history_row(
    raw: Any,
    *,
    symbol: str,
    contract: Any,
    close_timestamp: datetime,
    received_at: datetime,
    sequence: int,
    connection_epoch: str,
    provenance: str,
    warmup: bool,
) -> dict[str, Any] | None:
    values = {name: _float(_field(raw, name)) for name in ("open", "high", "low", "close", "volume")}
    if any(value is None for value in values.values()):
        return None
    if (
        values["open"] <= 0
        or values["high"] <= 0
        or values["low"] <= 0
        or values["close"] <= 0
        or values["volume"] < 0
        or values["high"] < max(values["open"], values["close"], values["low"])
        or values["low"] > min(values["open"], values["close"], values["high"])
    ):
        return None
    identity = {
        "conId": _int(_field(contract, "conId", "con_id")),
        "symbol": str(_field(contract, "symbol", default=symbol)).upper(),
        "secType": str(_field(contract, "secType", "sec_type", default="STK")).upper(),
        "exchange": str(_field(contract, "exchange", default="SMART")).upper(),
        "currency": str(_field(contract, "currency", default="USD")).upper(),
    }
    normalized = {
        "identity": identity,
        "trading_date_et": close_timestamp.astimezone(ET).date().isoformat(),
        "open": float(values["open"]),
        "high": float(values["high"]),
        "low": float(values["low"]),
        "close": float(values["close"]),
        "volume": float(values["volume"]),
        "provenance": provenance,
    }
    return {
        "contract": identity,
        "symbol": identity["symbol"],
        "event_timestamp_utc": close_timestamp,
        "timestamp_utc": close_timestamp,
        "receive_timestamp_utc": received_at,
        "source_sequence": sequence,
        "connection_epoch": connection_epoch,
        "source_identity": provenance,
        "source": provenance,
        "market_data_type": 1,
        "completed": True,
        "session": "regular",
        "bar_size": "1d",
        "open": normalized["open"],
        "high": normalized["high"],
        "low": normalized["low"],
        "close": normalized["close"],
        "volume": normalized["volume"],
        "adjusted": True,
        "corporate_action_status": "normalized",
        "corporate_action_entitlement_verified": True,
        "semantic_parity_verified": True,
        "normalization_provenance": provenance,
        "normalization_sha256": stable_payload_sha256(normalized),
        "warmup": warmup,
        "trading_date_et": normalized["trading_date_et"],
    }


def _dedupe(values: Sequence[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result
