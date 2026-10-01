"""Deterministic historical venue facts for the Donchian offline replay.

This module is deliberately an adapter around the existing V1 runtime.  It is
not an OMS and it never opens a socket.  Every economic mutation is represented
by an exchange-shaped fill or funding bill before the existing runtime ledger
observes it.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Mapping, Sequence

from quant_crypto.application.donchian_offline_replay import _OfflineVenue
from quant_crypto.oms.account_risk_facts import build_okx_account_cashflow_evidence
from quant_crypto.oms.okx_demo import OkxDemoResponse


CONTRACT_VALUE_BTC = Decimal("0.01")
TAKER_FEE_RATE = Decimal("0.0005")
HALF_SPREAD_BPS = Decimal("0.5")
_OPEN_DECISION_PROCESSING_BUDGET = timedelta(seconds=10)
PROTECTION_TIME_POLICY = {
    "version": "attached_parent_open_fill_before_bar_path_v1",
    "economic_order": "parent_open_fill_then_attached_protection_then_bar_path",
    "receipt_time": "processing_clock_only_not_market_latency",
    "opening_decision_processing_budget_seconds": 10,
    "unproven_intrabar": "blocked_ambiguous",
}
VENUE_STATE_SCHEMA_VERSION = "btc_donchian_historical_venue_state_v1"
_VENUE_REQUIRED_DECIMALS = (
    "position",
    "equity",
    "cash",
    "avg_price",
    "realized_pnl",
    "unrealized_pnl",
    "fee_total",
    "funding_total",
    "mark_price",
    "index_price",
    "funding_rate",
)
_VENUE_REQUIRED_LISTS = (
    "orders",
    "fills",
    "bills",
    "algos",
    "algo_history",
    "historical_events",
    "blocked_events",
)


def _text(value: Decimal) -> str:
    rendered = format(value.normalize(), "f")
    return "0" if rendered in {"", "-0"} else rendered


def _utc(value: datetime | str) -> datetime:
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("historical_timestamp_timezone_required")
    return value.astimezone(timezone.utc)


def _stable_numeric_id(prefix: str, value: str) -> str:
    digest = hashlib.sha256(f"{prefix}:{value}".encode("utf-8")).hexdigest()
    return str(int(digest[:15], 16))


class ProtectionTriggerAmbiguous(RuntimeError):
    """An OHLC bar touched both OCO legs and cannot prove their ordering."""


def _proof_decimal(value: Any, name: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ProtectionTriggerAmbiguous(f"historical_protection_numeric_invalid:{name}") from exc
    if not parsed.is_finite():
        raise ProtectionTriggerAmbiguous(f"historical_protection_numeric_invalid:{name}")
    return parsed


@dataclass(frozen=True)
class MarkProtectionTouch:
    """Pure mark-price OCO classification shared by historical adapters.

    This object says only which frozen mark trigger was visible and which
    mark-derived reference price applies.  It does not create an order, a fill
    or ledger state; those remain responsibilities of the owning venue and the
    existing runtime authority chain.
    """

    stop_hit: bool
    take_hit: bool
    gap_kind: str
    stop_reference_price: Decimal
    take_reference_price: Decimal


def classify_mark_protection_touch(
    *,
    position_side: str,
    mark_open: Any,
    mark_high: Any,
    mark_low: Any,
    stop_trigger: Any,
    take_trigger: Any,
) -> MarkProtectionTouch:
    """Classify an observed mark range without deciding event ordering.

    A point observation is represented by equal open/high/low values.  An OHLC
    caller must still reject double touches or an unproved intrabar creation
    order.  Keeping those decisions outside this pure classifier preserves the
    historical venue's existing fail-closed timing policy.
    """

    opening = _proof_decimal(mark_open, "mark_open")
    high = _proof_decimal(mark_high, "mark_high")
    low = _proof_decimal(mark_low, "mark_low")
    stop = _proof_decimal(stop_trigger, "stop")
    take = _proof_decimal(take_trigger, "take")
    if (
        min(opening, high, low, stop, take) <= 0
        or not low <= opening <= high
    ):
        raise ProtectionTriggerAmbiguous("historical_protection_mark_range_invalid")
    if position_side == "long":
        stop_hit = low <= stop
        take_hit = high >= take
        stop_price = min(stop, opening) if opening <= stop else stop
        take_price = max(take, opening) if opening >= take else take
        gap_kind = "stop_loss" if opening <= stop else "take_profit" if opening >= take else ""
    elif position_side == "short":
        stop_hit = high >= stop
        take_hit = low <= take
        stop_price = max(stop, opening) if opening >= stop else stop
        take_price = min(take, opening) if opening <= take else take
        gap_kind = "stop_loss" if opening >= stop else "take_profit" if opening <= take else ""
    else:
        raise ProtectionTriggerAmbiguous("historical_protection_position_side_invalid")
    return MarkProtectionTouch(stop_hit, take_hit, gap_kind, stop_price, take_price)


def validate_historical_venue_state(payload: object) -> tuple[str, ...]:
    if not isinstance(payload, Mapping):
        return ("historical_venue_state_not_mapping",)
    errors: list[str] = []
    if payload.get("schema_version") != VENUE_STATE_SCHEMA_VERSION:
        errors.append("historical_venue_state_schema_invalid")
    if payload.get("initial_equity_usdt") != "5000":
        errors.append("historical_venue_initial_equity_invalid")
    for name in _VENUE_REQUIRED_DECIMALS:
        try:
            value = Decimal(str(payload[name]))
        except (KeyError, ValueError, TypeError):
            errors.append(f"historical_venue_decimal_missing_or_invalid:{name}")
            continue
        if not value.is_finite():
            errors.append(f"historical_venue_decimal_non_finite:{name}")
    for name in _VENUE_REQUIRED_LISTS:
        if not isinstance(payload.get(name), list):
            errors.append(f"historical_venue_list_missing_or_invalid:{name}")
    for name in ("submit_count", "cancel_algo_count"):
        if not isinstance(payload.get(name), int) or int(payload[name]) < 0:
            errors.append(f"historical_venue_count_missing_or_invalid:{name}")
    if not isinstance(payload.get("quote"), Mapping):
        errors.append("historical_venue_quote_missing_or_invalid")
    return tuple(errors)


def load_historical_venue_state(path: Path) -> tuple[dict[str, Any] | None, tuple[str, ...]]:
    if not path.is_file():
        return None, ("historical_venue_state_file_missing",)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return None, (f"historical_venue_state_unreadable:{type(exc).__name__}",)
    errors = validate_historical_venue_state(payload)
    return (dict(payload) if not errors else None), errors


@dataclass(frozen=True)
class HistoricalBar:
    event_time_utc: datetime
    available_time_utc: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    mark_open: Decimal
    mark_high: Decimal
    mark_low: Decimal
    mark_close: Decimal
    index_close: Decimal

    def __post_init__(self) -> None:
        event = _utc(self.event_time_utc)
        available = _utc(self.available_time_utc)
        if available < event:
            raise ValueError("historical_bar_available_before_event")
        values = tuple(
            Decimal(str(value))
            for value in (
                self.open,
                self.high,
                self.low,
                self.close,
                self.mark_open,
                self.mark_high,
                self.mark_low,
                self.mark_close,
                self.index_close,
            )
        )
        if any(not value.is_finite() or value <= 0 for value in values):
            raise ValueError("historical_bar_price_invalid")
        if self.high < max(self.open, self.close) or self.low > min(self.open, self.close):
            raise ValueError("historical_trade_ohlc_invalid")
        if self.mark_high < max(self.mark_open, self.mark_close) or self.mark_low > min(self.mark_open, self.mark_close):
            raise ValueError("historical_mark_ohlc_invalid")
        object.__setattr__(self, "event_time_utc", event)
        object.__setattr__(self, "available_time_utc", available)


@dataclass(frozen=True)
class HistoricalFundingEvent:
    settlement_time_utc: datetime
    available_time_utc: datetime
    rate: Decimal
    mark_price: Decimal
    source_record_id: str
    mark_price_policy: str

    def __post_init__(self) -> None:
        settlement = _utc(self.settlement_time_utc)
        available = _utc(self.available_time_utc)
        rate = Decimal(str(self.rate))
        mark = Decimal(str(self.mark_price))
        if available > settlement:
            raise ValueError("historical_funding_not_available_at_settlement")
        if not rate.is_finite() or not mark.is_finite() or mark <= 0:
            raise ValueError("historical_funding_value_invalid")
        if self.mark_price_policy not in {
            "reported_mark_price",
            "funding_mark_sampling_approximation_t_minus_1h_close",
        }:
            raise ValueError("historical_funding_mark_policy_invalid")
        if not self.source_record_id:
            raise ValueError("historical_funding_source_required")
        object.__setattr__(self, "settlement_time_utc", settlement)
        object.__setattr__(self, "available_time_utc", available)
        object.__setattr__(self, "rate", rate)
        object.__setattr__(self, "mark_price", mark)


class HistoricalOfflineVenue(_OfflineVenue):
    """File-backed exchange simulation using only injected historical facts."""

    def __init__(self, path: Path, *, now: datetime) -> None:
        existed = path.exists()
        super().__init__(path, now=_utc(now))
        if existed:
            errors = validate_historical_venue_state(self.state)
            if errors:
                raise ValueError(
                    "historical_persistent_venue_state_missing_or_invalid:"
                    + ",".join(errors)
                )
            return
        self.state.update(
            {
                "schema_version": VENUE_STATE_SCHEMA_VERSION,
                "initial_equity_usdt": "5000",
                "cash": self.state["equity"],
                "avg_price": "0",
                "realized_pnl": "0",
                "unrealized_pnl": "0",
                "fee_total": "0",
                "funding_total": "0",
                "bills": [],
                "historical_events": [],
                "blocked_events": [],
                "quote": {},
                "mark_price": "0",
                "index_price": "0",
                "funding_rate": "0",
            }
        )
        self._persist()

    def _mark_equity(self, mark: Decimal) -> None:
        position = Decimal(self.state["position"])
        average = Decimal(self.state["avg_price"])
        unrealized = position * CONTRACT_VALUE_BTC * (mark - average) if position else Decimal("0")
        self.state["unrealized_pnl"] = _text(unrealized)
        self.state["equity"] = _text(Decimal(self.state["cash"]) + unrealized)
        self.state["mark_price"] = _text(mark)

    def _settle_funding(self, event: HistoricalFundingEvent) -> None:
        bill_id = _stable_numeric_id("funding", event.source_record_id)
        if any(str(row.get("billId")) == bill_id for row in self.state["bills"]):
            return
        position = Decimal(self.state["position"])
        cashflow = -(position * CONTRACT_VALUE_BTC * event.mark_price * event.rate)
        self.state["cash"] = _text(Decimal(self.state["cash"]) + cashflow)
        self.state["funding_total"] = _text(Decimal(self.state["funding_total"]) + cashflow)
        self.state["funding_rate"] = _text(event.rate)
        self.state["bills"].append(
            {
                "billId": bill_id,
                "instId": "BTC-USDT-SWAP",
                "ccy": "USDT",
                "type": "8",
                "subType": "173",
                "balChg": _text(cashflow),
                "pnl": _text(cashflow),
                "ts": str(int(event.settlement_time_utc.timestamp() * 1000)),
                "fundingRate": _text(event.rate),
                "markPx": _text(event.mark_price),
                "sourceRecordId": event.source_record_id,
                "markPricePolicy": event.mark_price_policy,
            }
        )

    def _attached_open_proof(self, bar: HistoricalBar, algo: Mapping[str, Any]) -> bool:
        """Recheck persisted local quote, parent order and fill before using a phase.

        A timestamp or a field on an algo alone cannot establish that a stop
        existed at the open.  The proof is restricted to this venue's own
        next-open execution and the immediately following OHLC bar.
        """
        names = (
            "economicTimePolicy", "economicEffectiveBarEventUtc",
            "economicSourceEventUtc", "economicSourceFingerprint",
            "economicParentOrderId", "economicParentFillId", "economicParentFillTs",
            "economicOpenQuoteOpen", "economicOpenQuotePx",
        )
        if not any(name in algo for name in names):
            return False
        def invalid() -> None:
            raise ProtectionTriggerAmbiguous("historical_attached_open_proof_invalid")

        if algo.get("economicTimePolicy") != PROTECTION_TIME_POLICY["version"]:
            invalid()
        event = str(algo.get("economicEffectiveBarEventUtc") or "")
        try:
            effective_at = _utc(event)
        except (TypeError, ValueError):
            invalid()
        if effective_at > bar.event_time_utc:
            invalid()
        quote = self.state.get("quote")
        if not isinstance(quote, Mapping):
            invalid()
        source_event = str(algo.get("economicSourceEventUtc") or "")
        source_fingerprint = str(algo.get("economicSourceFingerprint") or "")
        if effective_at == bar.event_time_utc:
            if (quote.get("openEventUtc") != event
                or quote.get("sourceEventUtc") != source_event
                or quote.get("sourceFingerprint") != source_fingerprint
                or quote.get("processingPhase") != "next_open_decision"
                or quote.get("open") != algo.get("economicOpenQuoteOpen")
                or _proof_decimal(quote.get("open"), "quote_open") != bar.open):
                invalid()
        sources = [row for row in self.state["historical_events"]
                   if row.get("event_time_utc") == source_event]
        if (len(sources) != 1 or sources[0].get("available_time_utc") != event
            or sources[0].get("fingerprint") != source_fingerprint
            or sources[0].get("next_open") != algo.get("economicOpenQuoteOpen")):
            invalid()
        client_id = str(algo.get("parentClOrdId") or "")
        order_id = _stable_numeric_id("order", client_id)
        fill_id = _stable_numeric_id("fill", f"{order_id}:{client_id}")
        algo_id = _stable_numeric_id("algo", str(algo.get("algoClOrdId") or ""))
        if (not client_id or algo.get("economicParentOrderId") != order_id
            or algo.get("economicParentFillId") != fill_id
            or str(algo.get("algoId")) != algo_id):
            invalid()
        orders = [row for row in self.state["orders"] if row.get("clOrdId") == client_id]
        fills = [row for row in self.state["fills"] if row.get("tradeId") == fill_id]
        if len(orders) != 1 or len(fills) != 1:
            invalid()
        order, fill = orders[0], fills[0]
        attached = order.get("attachAlgoOrds")
        terms = order.get("attachedHistoricalTerms")
        term_fields = (
            "tpTriggerPx", "tpTriggerPxType", "tpOrdPx",
            "slTriggerPx", "slTriggerPxType", "slOrdPx",
        )
        if not isinstance(terms, list) or any(not isinstance(row, Mapping) for row in terms):
            invalid()
        matching_terms = [row for row in terms if row.get("algoId") == algo_id]
        if (len(matching_terms) != 1
            or matching_terms[0].get("algoClOrdId") != algo.get("algoClOrdId")
            or any(matching_terms[0].get(name) != algo.get(name) for name in term_fields)
            or algo.get("tpTriggerPxType") != "mark"
            or algo.get("slTriggerPxType") != "mark"
            or algo.get("tpOrdPx") != "-1"
            or algo.get("slOrdPx") != "-1"
            or _proof_decimal(algo.get("tpTriggerPx"), "take") <= 0
            or _proof_decimal(algo.get("slTriggerPx"), "stop") <= 0):
            invalid()
        if (order.get("ordId") != order_id or order.get("state") != "filled"
            or order.get("instId") != "BTC-USDT-SWAP"
            or order.get("posSide") != algo.get("posSide")
            or order.get("sz") != algo.get("sz")
            or order.get("accFillSz") != algo.get("sz")
            or not isinstance(attached, list)
            or len([row for row in attached if row.get("attachAlgoId") == algo_id
                    and row.get("attachAlgoClOrdId") == algo.get("algoClOrdId")
                    and row.get("failCode") == "0"]) != 1
            or fill.get("ordId") != order_id or fill.get("clOrdId") != client_id
            or fill.get("instId") != "BTC-USDT-SWAP"
            or fill.get("posSide") != algo.get("posSide")
            or fill.get("fillSz") != algo.get("sz")
            or fill.get("execType") != "historical_next_bar_open_spread_aware"
            or fill.get("fillPx") != order.get("avgPx")
            or fill.get("economicEffectiveAtUtc") != event
            or fill.get("economicEffectivePhase") != "parent_open_fill"
            or fill.get("ts") != algo.get("uTime")
            or fill.get("ts") != algo.get("economicParentFillTs")):
            invalid()
        expected_side = "buy" if algo.get("posSide") == "long" else "sell"
        try:
            quote_open = _proof_decimal(algo.get("economicOpenQuoteOpen"), "stored_open")
            quote_px = _proof_decimal(algo.get("economicOpenQuotePx"), "stored_quote")
            half = quote_open * HALF_SPREAD_BPS / Decimal("10000")
            expected_px = quote_open + half if expected_side == "buy" else quote_open - half
        except (TypeError, ValueError):
            invalid()
        expected_position = _proof_decimal(algo.get("sz"), "size") * (1 if expected_side == "buy" else -1)
        if (order.get("side") != expected_side or fill.get("side") != expected_side
            or algo.get("side") != ("sell" if expected_side == "buy" else "buy")
            or quote_open <= 0 or quote_px != expected_px
            or quote_px != _proof_decimal(fill.get("fillPx"), "parent_fill_price")
            or _proof_decimal(self.state["position"], "position") != expected_position):
            invalid()
        return True

    def _protection_trigger(
        self, bar: HistoricalBar, algo: Mapping[str, Any]
    ) -> tuple[str, Decimal, Mapping[str, str]] | None:
        side = str(algo.get("posSide") or "")
        stop = _proof_decimal(algo.get("slTriggerPx"), "stop")
        take = _proof_decimal(algo.get("tpTriggerPx"), "take")
        if stop <= 0 or take <= 0:
            raise ProtectionTriggerAmbiguous("historical_protection_trigger_nonpositive")
        try:
            created_at = datetime.fromtimestamp(
                int(str(algo.get("uTime") or "")) / 1000,
                tz=timezone.utc,
            )
        except (TypeError, ValueError, OSError) as exc:
            raise ProtectionTriggerAmbiguous(
                "historical_protection_creation_time_missing_or_invalid"
            ) from exc
        if created_at > bar.available_time_utc:
            raise ProtectionTriggerAmbiguous(
                "historical_protection_creation_time_from_future"
            )
        touch = classify_mark_protection_touch(
            position_side=side,
            mark_open=bar.mark_open,
            mark_high=bar.mark_high,
            mark_low=bar.mark_low,
            stop_trigger=stop,
            take_trigger=take,
        )
        stop_hit, take_hit = touch.stop_hit, touch.take_hit
        stop_price, take_price, gap_kind = (
            touch.stop_reference_price,
            touch.take_reference_price,
            touch.gap_kind,
        )
        attached_open_proven = self._attached_open_proof(bar, algo)
        same_open_bar = (
            attached_open_proven
            and algo["economicEffectiveBarEventUtc"] == bar.event_time_utc.isoformat()
        )
        existed_at_open = created_at < bar.event_time_utc
        if attached_open_proven and not _utc(str(algo["economicEffectiveBarEventUtc"])) <= created_at <= bar.available_time_utc:
            raise ProtectionTriggerAmbiguous("historical_attached_open_receipt_outside_bar")
        if same_open_bar and gap_kind:
            if stop_hit and take_hit:
                raise ProtectionTriggerAmbiguous("historical_protection_double_touch_ambiguous")
            price = stop_price if gap_kind == "stop_loss" else take_price
            return (
                gap_kind,
                price,
                {
                    "effectiveTimePolicy": PROTECTION_TIME_POLICY["version"],
                    "effectiveAtUtc": bar.event_time_utc.isoformat(),
                    "effectivePhase": "after_parent_open_fill",
                    "protectionEconomicEffectiveAtUtc": bar.event_time_utc.isoformat(),
                    "protectionEconomicEffectivePhase": "after_parent_open_fill",
                    "protectionCreatedAtUtc": created_at.isoformat(),
                    "observedAtUtc": bar.available_time_utc.isoformat(),
                    "receiptAtUtc": self.now.isoformat(),
                },
            )
        if not existed_at_open and not same_open_bar and (stop_hit or take_hit):
            raise ProtectionTriggerAmbiguous(
                "historical_protection_created_intrabar_trigger_order_ambiguous"
            )
        if gap_kind and existed_at_open:
            price = stop_price if gap_kind == "stop_loss" else take_price
            return (
                gap_kind,
                price,
                {
                    "effectiveTimePolicy": "bar_open_gap",
                    "effectiveAtUtc": bar.event_time_utc.isoformat(),
                    "protectionCreatedAtUtc": created_at.isoformat(),
                    "observedAtUtc": bar.available_time_utc.isoformat(),
                    "receiptAtUtc": self.now.isoformat(),
                },
            )
        if stop_hit and take_hit:
            raise ProtectionTriggerAmbiguous("historical_protection_double_touch_ambiguous")
        timing = {
            "effectiveTimePolicy": "intrabar_time_unknown",
            "effectiveWindowStartUtc": bar.event_time_utc.isoformat(),
            "effectiveWindowEndUtc": bar.available_time_utc.isoformat(),
            "protectionCreatedAtUtc": created_at.isoformat(),
            "observedAtUtc": bar.available_time_utc.isoformat(),
            "receiptAtUtc": self.now.isoformat(),
        }
        if same_open_bar:
            timing["protectionEconomicEffectiveAtUtc"] = bar.event_time_utc.isoformat()
            timing["protectionEconomicEffectivePhase"] = "after_parent_open_fill"
        if stop_hit:
            return "stop_loss", stop_price, timing
        if take_hit:
            return "take_profit", take_price, timing
        return None

    def _apply_fill(
        self,
        *,
        client_id: str,
        order_id: str,
        side: str,
        position_side: str,
        size: Decimal,
        price: Decimal,
        execution_type: str,
        timing: Mapping[str, str] | None = None,
    ) -> dict[str, str]:
        current = Decimal(self.state["position"])
        delta = size if position_side == "long" and side == "buy" else -size if position_side == "short" and side == "sell" else -size if position_side == "long" else size
        if current and delta and (current > 0) != (delta > 0):
            close_size = min(abs(current), abs(delta))
            realized = close_size * CONTRACT_VALUE_BTC * (price - Decimal(self.state["avg_price"])) * (Decimal("1") if current > 0 else Decimal("-1"))
        else:
            close_size = Decimal("0")
            realized = Decimal("0")
        new_position = current + delta
        if not current or (current > 0) == (delta > 0):
            total = abs(current) + abs(delta)
            average = ((abs(current) * Decimal(self.state["avg_price"])) + (abs(delta) * price)) / total
        elif new_position == 0:
            average = Decimal("0")
        elif (new_position > 0) == (current > 0):
            average = Decimal(self.state["avg_price"])
        else:
            average = price
        fee = abs(size * CONTRACT_VALUE_BTC * price) * TAKER_FEE_RATE
        self.state["cash"] = _text(Decimal(self.state["cash"]) + realized - fee)
        self.state["realized_pnl"] = _text(Decimal(self.state["realized_pnl"]) + realized)
        self.state["fee_total"] = _text(Decimal(self.state["fee_total"]) + fee)
        self.state["position"] = _text(new_position)
        self.state["avg_price"] = _text(average)
        fill_id = _stable_numeric_id("fill", f"{order_id}:{client_id}")
        fill = {
            "tradeId": fill_id,
            "ordId": order_id,
            "clOrdId": client_id,
            "instId": "BTC-USDT-SWAP",
            "side": side,
            "posSide": position_side,
            "fillPx": _text(price),
            "fillSz": _text(size),
            "fee": _text(-fee),
            "feeCcy": "USDT",
            "pnl": _text(realized),
            "execType": execution_type,
            "ts": str(int(self.now.timestamp() * 1000)),
            **dict(timing or {}),
        }
        self.state["fills"].append(fill)
        self._mark_equity(Decimal(self.state["mark_price"]) if Decimal(self.state["mark_price"]) > 0 else price)
        return fill

    def _trigger_protection(self, bar: HistoricalBar) -> None:
        for algo in list(self.state["algos"]):
            triggered = self._protection_trigger(bar, algo)
            if triggered is None:
                continue
            trigger_kind, price, timing = triggered
            order_id = _stable_numeric_id("protection-order", str(algo["algoId"]))
            client_id = str(algo["algoClOrdId"])
            order = {
                "ordId": order_id,
                "clOrdId": client_id,
                "instId": "BTC-USDT-SWAP",
                "side": str(algo["side"]),
                "posSide": str(algo["posSide"]),
                "ordType": "market",
                "sz": str(algo["sz"]),
                "state": "filled",
                "accFillSz": str(algo["sz"]),
                "avgPx": _text(price),
                "triggerKind": trigger_kind,
                "parentClOrdId": str(algo.get("parentClOrdId") or ""),
                **dict(timing),
            }
            self.state["orders"].append(order)
            self._apply_fill(
                client_id=client_id,
                order_id=order_id,
                side=order["side"],
                position_side=order["posSide"],
                size=Decimal(order["sz"]),
                price=price,
                execution_type=f"historical_oco_{trigger_kind}",
                timing=timing,
            )
            self.state["algo_history"].append(
                {**dict(algo), "state": "effective", "triggerKind": trigger_kind, "uTime": str(int(self.now.timestamp() * 1000))}
            )
            self.state["algos"] = [row for row in self.state["algos"] if row["algoId"] != algo["algoId"]]

    def advance(
        self,
        *,
        completed_bar: HistoricalBar,
        next_bar_open: Decimal | None,
        funding_events: Sequence[HistoricalFundingEvent] = (),
    ) -> None:
        if completed_bar.available_time_utc > self.now:
            raise ValueError("historical_bar_not_yet_available")
        event_key = completed_bar.event_time_utc.isoformat()
        event_fingerprint = hashlib.sha256(
            "|".join(
                (
                    event_key,
                    _text(completed_bar.open),
                    _text(completed_bar.high),
                    _text(completed_bar.low),
                    _text(completed_bar.close),
                    _text(completed_bar.mark_open),
                    _text(completed_bar.mark_high),
                    _text(completed_bar.mark_low),
                    _text(completed_bar.mark_close),
                    _text(completed_bar.index_close),
                    completed_bar.available_time_utc.isoformat(),
                    "" if next_bar_open is None else _text(Decimal(next_bar_open)),
                    json.dumps([
                        [item.source_record_id, item.settlement_time_utc.isoformat(),
                         item.available_time_utc.isoformat(), _text(item.rate),
                         _text(item.mark_price), item.mark_price_policy]
                        for item in funding_events
                    ], separators=(",", ":")),
                )
            ).encode("utf-8")
        ).hexdigest()
        prior = next((row for row in self.state["historical_events"] if row["event_time_utc"] == event_key), None)
        if prior is not None:
            if prior["fingerprint"] != event_fingerprint:
                raise ValueError("historical_same_event_input_conflict")
            return
        # The completed bar already happened before its availability/decision
        # boundary.  Protection effective in that bar must therefore mutate the
        # simulated position before funding settled at the boundary.  New
        # decisions and fills occur only after advance returns.
        self._trigger_protection(completed_bar)
        for funding in sorted(funding_events, key=lambda row: row.settlement_time_utc):
            if funding.settlement_time_utc > self.now:
                raise ValueError("historical_funding_from_future")
            self._settle_funding(funding)
        self.state["index_price"] = _text(completed_bar.index_close)
        self._mark_equity(completed_bar.mark_close)
        if next_bar_open is None:
            self.state["quote"] = {}
        else:
            open_price = Decimal(str(next_bar_open))
            half = open_price * HALF_SPREAD_BPS / Decimal("10000")
            self.state["quote"] = {
                "open": _text(open_price),
                "bid": _text(open_price - half),
                "ask": _text(open_price + half),
                "openEventUtc": completed_bar.available_time_utc.isoformat(),
                "sourceEventUtc": event_key,
                "sourceFingerprint": event_fingerprint,
                "processingPhase": "next_open_decision",
                "processingObservedAtUtc": self.now.isoformat(),
            }
        self.state["historical_events"].append(
            {"event_time_utc": event_key, "available_time_utc": completed_bar.available_time_utc.isoformat(),
             "fingerprint": event_fingerprint,
             "next_open": None if next_bar_open is None else _text(Decimal(str(next_bar_open)))}
        )
        self._persist()

    def public_get(self, path: str, params: Mapping[str, Any] | None = None) -> OkxDemoResponse:
        del params
        timestamp = str(int(self.now.timestamp() * 1000))
        quote = self.state.get("quote", {})
        bid = str(quote.get("bid") or "0")
        ask = str(quote.get("ask") or "0")
        mark = str(self.state.get("mark_price") or "0")
        index = str(self.state.get("index_price") or "0")
        rows = {
            "/api/v5/public/instruments": [{"instId": "BTC-USDT-SWAP", "state": "live", "ctVal": "0.01", "tickSz": "0.1", "lotSz": "0.01", "minSz": "0.01"}],
            "/api/v5/market/ticker": [{"bidPx": bid, "askPx": ask, "ts": timestamp}],
            "/api/v5/public/mark-price": [{"markPx": mark, "ts": timestamp}],
            "/api/v5/market/index-tickers": [{"idxPx": index, "ts": timestamp}],
            "/api/v5/public/price-limit": [{"buyLmt": _text(Decimal(ask or "0") * Decimal("1.1")), "sellLmt": _text(Decimal(bid or "0") * Decimal("0.9"))}],
            "/api/v5/market/books": [{"bids": [[bid, "1"]], "asks": [[ask, "1"]], "ts": timestamp}],
            "/api/v5/public/time": [{"ts": timestamp}],
            "/api/v5/public/funding-rate": [{"fundingRate": str(self.state.get("funding_rate") or "0"), "fundingTime": timestamp}],
        }
        if path not in rows:
            raise AssertionError(f"historical public path not implemented: {path}")
        return OkxDemoResponse("GET", path, 200, "0", "", tuple(rows[path]))

    def _position_rows(self) -> list[dict[str, str]]:
        position = Decimal(self.state["position"])
        mark = str(self.state.get("mark_price") or "0")
        average = str(self.state.get("avg_price") or "0")
        return [{
            "instId": "BTC-USDT-SWAP",
            "posSide": "long" if position >= 0 else "short",
            "mgnMode": "isolated",
            "pos": _text(abs(position)),
            "avgPx": average,
            "markPx": mark,
            "upl": str(self.state.get("unrealized_pnl") or "0"),
            "realizedPnl": str(self.state.get("realized_pnl") or "0"),
            "liqPx": "" if position == 0 else _text(Decimal(mark) * (Decimal("0.5") if position > 0 else Decimal("1.5"))),
            "lever": "1",
            "uTime": str(int(self.now.timestamp() * 1000)),
        }]

    def private_get(self, path: str, params: Mapping[str, Any] | None = None) -> OkxDemoResponse:
        query = dict(params or {})
        if path == "/api/v5/account/balance":
            rows = [{"totalEq": self.state["equity"], "details": [{"ccy": "USDT", "eq": self.state["equity"], "cashBal": self.state["cash"], "upl": self.state["unrealized_pnl"]}]}]
            return OkxDemoResponse("GET", path, 200, "0", "", tuple(rows))
        if path == "/api/v5/account/bills":
            begin = int(str(query.get("begin") or "0"))
            end = int(str(query.get("end") or "9999999999999"))
            rows = [row for row in self.state["bills"] if begin <= int(row["ts"]) <= end]
            rows.sort(key=lambda row: (int(row["ts"]), int(row["billId"])), reverse=True)
            after = str(query.get("after") or "")
            if after:
                index = next((idx for idx, row in enumerate(rows) if str(row["billId"]) == after), len(rows) - 1)
                rows = rows[index + 1 :]
            limit = int(str(query.get("limit") or "100"))
            return OkxDemoResponse("GET", path, 200, "0", "", tuple(rows[:limit]))
        return super().private_get(path, query)

    def cashflow_evidence(self, **kwargs: Any) -> Mapping[str, Any]:
        start = _utc(kwargs["coverage_start_utc"])
        end = _utc(kwargs["coverage_end_utc"])
        begin_ms = str(int(start.timestamp() * 1000))
        end_ms = str(int(end.timestamp() * 1000))
        rows = [row for row in self.state["bills"] if int(begin_ms) <= int(row["ts"]) <= int(end_ms)]
        rows.sort(key=lambda row: (int(row["ts"]), int(row["billId"])), reverse=True)
        pages: list[dict[str, Any]] = []
        for offset in range(0, len(rows), 100):
            request = {"begin": begin_ms, "end": end_ms, "limit": "100"}
            if offset:
                request["after"] = str(rows[offset - 1]["billId"])
            pages.append({"request": request, "rows": rows[offset : offset + 100]})
        if not pages or len(pages[-1]["rows"]) == 100:
            request = {"begin": begin_ms, "end": end_ms, "limit": "100"}
            if rows:
                request["after"] = str(rows[-1]["billId"])
            pages.append({"request": request, "rows": []})
        return build_okx_account_cashflow_evidence(
            pages=pages,
            account_identity_hash=kwargs["account_identity_hash"],
            snapshot_sha256=kwargs["snapshot_sha256"],
            coverage_start_utc=start,
            coverage_end_utc=end,
            reference_time_utc=_utc(kwargs["reference_time_utc"]),
        )

    def submit_order(self, payload: Mapping[str, Any]) -> OkxDemoResponse:
        order = dict(payload)
        client_id = str(order["clOrdId"])
        existing = next((row for row in self.state["orders"] if row["clOrdId"] == client_id), None)
        if existing is not None:
            return OkxDemoResponse("POST", "/api/v5/trade/order", 200, "0", "", ({"ordId": existing["ordId"], "clOrdId": client_id, "sCode": "0", "sMsg": ""},))
        quote = self.state.get("quote", {})
        side = str(order["side"])
        requested_attached = order.get("attachAlgoOrds")
        if requested_attached:
            if not isinstance(quote, Mapping) or side not in {"buy", "sell"}:
                raise ProtectionTriggerAmbiguous("historical_attached_open_quote_missing_or_invalid")
            opening = _proof_decimal(quote.get("open"), "quote_open")
            bid = _proof_decimal(quote.get("bid"), "quote_bid")
            ask = _proof_decimal(quote.get("ask"), "quote_ask")
            half = opening * HALF_SPREAD_BPS / Decimal("10000")
            if (opening <= 0 or bid <= 0 or ask <= 0
                or bid != opening - half or ask != opening + half):
                raise ProtectionTriggerAmbiguous("historical_attached_open_quote_missing_or_invalid")
            if not isinstance(requested_attached, list) or any(
                not isinstance(raw, Mapping)
                or not raw.get("attachAlgoClOrdId")
                or raw.get("tpTriggerPxType") != "mark"
                or raw.get("slTriggerPxType") != "mark"
                or raw.get("tpOrdPx") != "-1"
                or raw.get("slOrdPx") != "-1"
                or _proof_decimal(raw.get("tpTriggerPx"), "take") <= 0
                or _proof_decimal(raw.get("slTriggerPx"), "stop") <= 0
                for raw in requested_attached
            ):
                raise ProtectionTriggerAmbiguous("historical_attached_terms_invalid")
        executable = Decimal(str(quote.get("ask") if side == "buy" else quote.get("bid") or "0"))
        limit = Decimal(str(order.get("px") or "0"))
        marketable = executable > 0 and ((side == "buy" and limit >= executable) or (side == "sell" and limit <= executable))
        size = Decimal(str(order["sz"]))
        # Current authority chain sends FOK entries / IOC reductions. They
        # are marketable limit instructions, not a different strategy. The
        # frozen simulated book has one contract: reject unsupported depth,
        # never silently turn a partial/insufficient fill into a full fill.
        if (str(order.get("ordType") or "") not in {"limit", "fok", "ioc"}
            or not marketable or not size.is_finite() or not Decimal("0") < size <= Decimal("1")):
            return OkxDemoResponse("POST", "/api/v5/trade/order", 200, "0", "", ({"ordId": "", "clOrdId": client_id, "sCode": "51008", "sMsg": "historical_limit_not_marketable"},))
        if order.get("attachAlgoOrds"):
            event = str(quote.get("openEventUtc") or "")
            source = str(quote.get("sourceEventUtc") or "")
            matching_sources = [row for row in self.state["historical_events"]
                                if row.get("event_time_utc") == source]
            try:
                event_time = _utc(event)
                observed_at = _utc(str(quote.get("processingObservedAtUtc") or ""))
            except (TypeError, ValueError) as exc:
                raise ProtectionTriggerAmbiguous("historical_attached_open_quote_missing_or_invalid") from exc
            if (len(matching_sources) != 1
                or matching_sources[0].get("available_time_utc") != event
                or matching_sources[0].get("fingerprint") != quote.get("sourceFingerprint")
                or matching_sources[0].get("next_open") != quote.get("open")
                or quote.get("processingPhase") != "next_open_decision"
                or not event_time <= observed_at <= event_time + _OPEN_DECISION_PROCESSING_BUDGET
                or observed_at > self.now
                or self.now - observed_at > _OPEN_DECISION_PROCESSING_BUDGET):
                raise ProtectionTriggerAmbiguous("historical_attached_open_quote_missing_or_invalid")
        self.state["submit_count"] += 1
        order_id = _stable_numeric_id("order", client_id)
        parent_fill = self._apply_fill(
            client_id=client_id,
            order_id=order_id,
            side=side,
            position_side=str(order["posSide"]),
            size=size,
            price=executable,
            execution_type="historical_next_bar_open_spread_aware",
            timing={
                "economicEffectiveAtUtc": quote["openEventUtc"],
                "economicEffectivePhase": "parent_open_fill",
                "processingObservedAtUtc": quote["processingObservedAtUtc"],
            } if quote.get("openEventUtc") else None,
        )
        attached = []
        attached_terms = []
        for raw in order.get("attachAlgoOrds", []):
            algo_id = _stable_numeric_id("algo", str(raw["attachAlgoClOrdId"]))
            attached_terms.append({
                "algoId": algo_id,
                "algoClOrdId": raw["attachAlgoClOrdId"],
                **{name: raw[name] for name in (
                    "tpTriggerPx", "tpTriggerPxType", "tpOrdPx",
                    "slTriggerPx", "slTriggerPxType", "slOrdPx",
                )},
            })
            algo = {
                "algoId": algo_id,
                "algoClOrdId": raw["attachAlgoClOrdId"],
                "parentClOrdId": client_id,
                "instId": "BTC-USDT-SWAP",
                "side": "sell" if order["posSide"] == "long" else "buy",
                "posSide": order["posSide"],
                "sz": order["sz"],
                "state": "live",
                "ordType": "oco",
                "tpTriggerPx": raw["tpTriggerPx"],
                "tpTriggerPxType": raw["tpTriggerPxType"],
                "tpOrdPx": raw["tpOrdPx"],
                "slTriggerPx": raw["slTriggerPx"],
                "slTriggerPxType": raw["slTriggerPxType"],
                "slOrdPx": raw["slOrdPx"],
                "uTime": str(int(self.now.timestamp() * 1000)),
                "economicTimePolicy": PROTECTION_TIME_POLICY["version"],
                "economicEffectiveBarEventUtc": quote["openEventUtc"],
                "economicSourceEventUtc": quote["sourceEventUtc"],
                "economicSourceFingerprint": quote["sourceFingerprint"],
                "economicParentOrderId": order_id,
                "economicParentFillId": parent_fill["tradeId"],
                "economicParentFillTs": parent_fill["ts"],
                "economicOpenQuoteOpen": quote["open"],
                "economicOpenQuotePx": _text(executable),
            }
            self.state["algos"] = [algo]
            attached.append({"attachAlgoId": algo_id, "attachAlgoClOrdId": algo["algoClOrdId"], "failCode": "0", "failReason": ""})
        final = {**order, "ordId": order_id, "state": "filled", "accFillSz": order["sz"], "avgPx": _text(executable), "attachAlgoOrds": attached, "attachedHistoricalTerms": attached_terms}
        self.state["orders"].append(final)
        self._persist()
        return OkxDemoResponse("POST", "/api/v5/trade/order", 200, "0", "", ({"ordId": order_id, "clOrdId": client_id, "sCode": "0", "sMsg": ""},))


__all__ = [
    "HistoricalBar",
    "HistoricalFundingEvent",
    "HistoricalOfflineVenue",
    "MarkProtectionTouch",
    "ProtectionTriggerAmbiguous",
    "classify_mark_protection_touch",
    "load_historical_venue_state",
    "validate_historical_venue_state",
]
