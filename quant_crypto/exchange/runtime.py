from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Sequence

from quant_shared.core.time import ensure_utc

from quant_crypto.monitoring.artifact_schema import apply_btc_artifact_schema, stable_payload_hash


BTC_EXCHANGE_RUNTIME_CONTRACT_VERSION = "btc_exchange_runtime_contract_v1"
BTC_EXCHANGE_RUNTIME_LOCAL_PROBE_VERSION = "btc_exchange_runtime_local_probe_v1"


class BTCExchangeRuntimeStatus(str, Enum):
    OK = "ok"
    DEGRADED = "degraded"
    CANCEL_ONLY = "cancel_only"
    DATA_STALE = "data_stale"
    OUTAGE = "outage"
    MAINTENANCE = "maintenance"
    UNKNOWN = "unknown"


class BTCStreamStatus(str, Enum):
    CONNECTED = "connected"
    DEGRADED = "degraded"
    STALE = "stale"
    DISCONNECTED = "disconnected"
    UNKNOWN = "unknown"


class BTCRestStatus(str, Enum):
    OK = "ok"
    DEGRADED = "degraded"
    ORDER_ENTRY_DOWN = "order_entry_down"
    OUTAGE = "outage"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class BTCRuntimeStateTransition:
    step_id: int
    event: str
    from_state: str
    to_state: str
    reason: str
    blockers_added: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": int(self.step_id),
            "event": self.event,
            "from_state": self.from_state,
            "to_state": self.to_state,
            "reason": self.reason,
            "blockers_added": list(self.blockers_added),
        }


@dataclass(frozen=True)
class BTCWSSequenceGapfillReplay:
    stream: str
    observed_sequences: tuple[int, ...]
    gapfill_sequences: tuple[int, ...]
    expected_start_sequence: int | None
    expected_end_sequence: int | None
    missing_sequences: tuple[int, ...]
    recovered_sequences: tuple[int, ...]
    unrecovered_sequences: tuple[int, ...]
    recovery_method: str = "local_fixture_gapfill_replay"
    trading_blocked_during_gapfill: bool = True

    @classmethod
    def from_sequences(
        cls,
        *,
        stream: str,
        observed_sequences: Sequence[int],
        gapfill_sequences: Sequence[int] = (),
        recovery_method: str = "local_fixture_gapfill_replay",
        trading_blocked_during_gapfill: bool = True,
    ) -> "BTCWSSequenceGapfillReplay":
        observed = tuple(sorted({int(value) for value in observed_sequences}))
        gapfill = tuple(sorted({int(value) for value in gapfill_sequences}))
        if not observed:
            return cls(
                stream=stream,
                observed_sequences=observed,
                gapfill_sequences=gapfill,
                expected_start_sequence=None,
                expected_end_sequence=None,
                missing_sequences=(),
                recovered_sequences=(),
                unrecovered_sequences=(),
                recovery_method=recovery_method,
                trading_blocked_during_gapfill=trading_blocked_during_gapfill,
            )
        expected = set(range(min(observed), max(observed) + 1))
        missing = tuple(sorted(expected.difference(observed)))
        recovered = tuple(value for value in missing if value in set(gapfill))
        unrecovered = tuple(value for value in missing if value not in set(gapfill))
        return cls(
            stream=stream,
            observed_sequences=observed,
            gapfill_sequences=gapfill,
            expected_start_sequence=min(observed),
            expected_end_sequence=max(observed),
            missing_sequences=missing,
            recovered_sequences=recovered,
            unrecovered_sequences=unrecovered,
            recovery_method=recovery_method,
            trading_blocked_during_gapfill=trading_blocked_during_gapfill,
        )

    @property
    def gap_detected(self) -> bool:
        return bool(self.missing_sequences)

    @property
    def recovered(self) -> bool:
        return not self.unrecovered_sequences

    def to_gapfill_state(self) -> "BTCGapfillState":
        return BTCGapfillState(
            stream=self.stream,
            gap_detected=self.gap_detected,
            recovered=self.recovered,
            recovery_method=self.recovery_method if self.gap_detected else "",
            events_backfilled=len(self.recovered_sequences),
            trading_blocked=self.trading_blocked_during_gapfill,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "stream": self.stream,
            "observed_sequences": list(self.observed_sequences),
            "gapfill_sequences": list(self.gapfill_sequences),
            "expected_start_sequence": self.expected_start_sequence,
            "expected_end_sequence": self.expected_end_sequence,
            "gap_detected": self.gap_detected,
            "gap_ranges": _sequence_ranges(self.missing_sequences),
            "missing_sequences": list(self.missing_sequences),
            "recovered_sequences": list(self.recovered_sequences),
            "unrecovered_sequences": list(self.unrecovered_sequences),
            "recovered": self.recovered,
            "recovery_method": self.recovery_method if self.gap_detected else "",
            "trading_blocked_during_gapfill": bool(self.trading_blocked_during_gapfill),
        }


@dataclass(frozen=True)
class BTCGapfillState:
    stream: str
    gap_detected: bool
    recovered: bool
    recovery_method: str = ""
    events_backfilled: int = 0
    bars_rebuilt: int = 0
    orders_reconciled: int = 0
    fills_reconciled: int = 0
    trading_blocked: bool = True

    def blockers(self) -> list[str]:
        if not self.gap_detected:
            return []
        blockers: list[str] = []
        if not self.recovered:
            blockers.append(f"btc_exchange_gapfill_not_recovered:{self.stream}")
        if not self.recovery_method:
            blockers.append(f"btc_exchange_gapfill_method_missing:{self.stream}")
        if not self.trading_blocked:
            blockers.append(f"btc_exchange_gapfill_did_not_block_trading:{self.stream}")
        return blockers

    def to_dict(self) -> dict[str, Any]:
        return {
            "stream": self.stream,
            "gap_detected": bool(self.gap_detected),
            "recovered": bool(self.recovered),
            "recovery_method": self.recovery_method,
            "events_backfilled": int(self.events_backfilled),
            "bars_rebuilt": int(self.bars_rebuilt),
            "orders_reconciled": int(self.orders_reconciled),
            "fills_reconciled": int(self.fills_reconciled),
            "trading_blocked": bool(self.trading_blocked),
        }


@dataclass(frozen=True)
class BTCExchangeRuntimeSnapshot:
    venue: str
    instrument_id: str
    observed_at_utc: datetime
    exchange_status: BTCExchangeRuntimeStatus
    public_ws_status: BTCStreamStatus
    private_ws_status: BTCStreamStatus
    rest_status: BTCRestStatus
    server_time_offset_ms: int
    rate_limit_budget_remaining: int
    order_rate_budget_remaining: int
    last_market_data_time_utc: datetime | None
    last_private_event_time_utc: datetime | None
    last_reconciliation_time_utc: datetime | None
    unreconciled_order_count: int = 0
    unreconciled_fill_count: int = 0
    metadata_version: str = ""
    cancel_only: bool = False
    private_endpoints_enabled: bool = False
    order_endpoints_enabled: bool = False
    public_ws_gapfill: BTCGapfillState | None = None
    private_ws_gapfill: BTCGapfillState | None = None
    max_server_time_offset_ms: int = 1_000
    min_rate_limit_budget_remaining: int = 10
    min_order_rate_budget_remaining: int = 5
    max_market_data_age_ms: int = 60_000
    max_private_event_age_ms: int = 120_000
    max_reconciliation_age_ms: int = 300_000
    mode: str = "paper"
    notes: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.venue:
            raise ValueError("BTC exchange runtime venue is required.")
        if not self.instrument_id:
            raise ValueError("BTC exchange runtime instrument_id is required.")
        object.__setattr__(self, "observed_at_utc", ensure_utc(self.observed_at_utc))
        for field_name in ("last_market_data_time_utc", "last_private_event_time_utc", "last_reconciliation_time_utc"):
            value = getattr(self, field_name)
            if value is not None:
                object.__setattr__(self, field_name, ensure_utc(value))
        if self.mode not in {"read_only", "paper", "live"}:
            raise ValueError("BTC exchange runtime mode must be read_only/paper/live.")

    def validate(self) -> list[str]:
        blockers: list[str] = []
        warnings: list[str] = []
        if self.mode != "live" and (self.private_endpoints_enabled or self.order_endpoints_enabled):
            blockers.append("btc_exchange_runtime_non_live_private_or_order_endpoint_enabled")
        if self.mode == "live":
            blockers.append("btc_exchange_runtime_live_mode_not_authorized")
        if self.exchange_status in {
            BTCExchangeRuntimeStatus.DATA_STALE,
            BTCExchangeRuntimeStatus.OUTAGE,
            BTCExchangeRuntimeStatus.MAINTENANCE,
            BTCExchangeRuntimeStatus.UNKNOWN,
        }:
            blockers.append(f"btc_exchange_status_not_tradeable:{self.exchange_status.value}")
        if self.cancel_only or self.exchange_status == BTCExchangeRuntimeStatus.CANCEL_ONLY:
            blockers.append("btc_exchange_cancel_only_blocks_new_orders")
        if self.public_ws_status != BTCStreamStatus.CONNECTED:
            blockers.append(f"btc_exchange_public_ws_not_connected:{self.public_ws_status.value}")
        if self.private_ws_status != BTCStreamStatus.CONNECTED:
            blockers.append(f"btc_exchange_private_ws_not_connected:{self.private_ws_status.value}")
        if self.rest_status != BTCRestStatus.OK:
            blockers.append(f"btc_exchange_rest_not_ok:{self.rest_status.value}")
        if abs(int(self.server_time_offset_ms)) > int(self.max_server_time_offset_ms):
            blockers.append("btc_exchange_server_time_offset_exceeds_tolerance")
        if int(self.rate_limit_budget_remaining) < int(self.min_rate_limit_budget_remaining):
            blockers.append("btc_exchange_rate_limit_budget_below_threshold")
        if int(self.order_rate_budget_remaining) < int(self.min_order_rate_budget_remaining):
            blockers.append("btc_exchange_order_rate_budget_below_threshold")
        if not self.metadata_version:
            blockers.append("btc_exchange_metadata_version_missing")
        if self._age_ms(self.last_market_data_time_utc) is None:
            blockers.append("btc_exchange_last_market_data_time_missing")
        elif self._age_ms(self.last_market_data_time_utc) > int(self.max_market_data_age_ms):
            blockers.append("btc_exchange_market_data_stale")
        if self._age_ms(self.last_private_event_time_utc) is None:
            blockers.append("btc_exchange_last_private_event_time_missing")
        elif self._age_ms(self.last_private_event_time_utc) > int(self.max_private_event_age_ms):
            blockers.append("btc_exchange_private_event_stale")
        if self._age_ms(self.last_reconciliation_time_utc) is None:
            blockers.append("btc_exchange_last_reconciliation_time_missing")
        elif self._age_ms(self.last_reconciliation_time_utc) > int(self.max_reconciliation_age_ms):
            blockers.append("btc_exchange_reconciliation_stale")
        if int(self.unreconciled_order_count) > 0:
            blockers.append("btc_exchange_unreconciled_orders")
        if int(self.unreconciled_fill_count) > 0:
            blockers.append("btc_exchange_unreconciled_fills")
        if self.public_ws_gapfill is not None:
            blockers.extend(self.public_ws_gapfill.blockers())
        if self.private_ws_gapfill is not None:
            blockers.extend(self.private_ws_gapfill.blockers())
        return _dedupe(blockers + warnings)

    def to_artifact(self) -> dict[str, Any]:
        blockers = self.validate()
        payload = {
            "exchange_runtime_contract_version": BTC_EXCHANGE_RUNTIME_CONTRACT_VERSION,
            "status": "blocked" if blockers else "complete",
            "venue": self.venue,
            "instrument_id": self.instrument_id,
            "mode": self.mode,
            "exchange_status": self.exchange_status.value,
            "public_ws_status": self.public_ws_status.value,
            "private_ws_status": self.private_ws_status.value,
            "rest_status": self.rest_status.value,
            "server_time_offset_ms": int(self.server_time_offset_ms),
            "rate_limit_budget_remaining": int(self.rate_limit_budget_remaining),
            "order_rate_budget_remaining": int(self.order_rate_budget_remaining),
            "last_market_data_time_utc": _iso_or_none(self.last_market_data_time_utc),
            "last_private_event_time_utc": _iso_or_none(self.last_private_event_time_utc),
            "last_reconciliation_time_utc": _iso_or_none(self.last_reconciliation_time_utc),
            "unreconciled_order_count": int(self.unreconciled_order_count),
            "unreconciled_fill_count": int(self.unreconciled_fill_count),
            "metadata_version": self.metadata_version,
            "cancel_only": bool(self.cancel_only),
            "private_endpoints_enabled": bool(self.private_endpoints_enabled),
            "order_endpoints_enabled": bool(self.order_endpoints_enabled),
            "public_ws_gapfill": None if self.public_ws_gapfill is None else self.public_ws_gapfill.to_dict(),
            "private_ws_gapfill": None if self.private_ws_gapfill is None else self.private_ws_gapfill.to_dict(),
            "allows_live_orders": False,
            "real_order_submitted": False,
            "private_endpoint_used": False,
            "order_endpoint_used": False,
            "blockers": blockers,
            "notes": dict(self.notes),
        }
        return apply_btc_artifact_schema(
            payload,
            decision="runtime_tradeable_for_simulated_paper" if not blockers else "runtime_fail_closed",
            generated_at_utc=self.observed_at_utc,
            as_of_utc=self.observed_at_utc,
            blockers=blockers,
            warnings=[],
            input_hashes={"runtime_snapshot": stable_payload_hash(payload)},
        )

    def _age_ms(self, timestamp: datetime | None) -> int | None:
        if timestamp is None:
            return None
        return int((self.observed_at_utc - timestamp).total_seconds() * 1000)


def build_btc_exchange_runtime_local_probe_artifact(
    *,
    observed_at_utc: datetime,
    local_receive_time_utc: datetime,
    exchange_server_time_utc: datetime,
    venue: str = "okx",
    instrument_id: str = "BTC-USDT-SWAP",
    public_ws_sequences: Sequence[int] = (),
    public_gapfill_sequences: Sequence[int] = (),
    metadata_version: str = "",
    rate_limit_budget_remaining: int = 0,
    order_rate_budget_remaining: int = 0,
    cancel_only: bool = True,
    mode: str = "read_only",
    max_server_time_offset_ms: int = 1_000,
    min_rate_limit_budget_remaining: int = 10,
    min_order_rate_budget_remaining: int = 5,
) -> dict[str, Any]:
    observed_at = ensure_utc(observed_at_utc)
    local_receive = ensure_utc(local_receive_time_utc)
    exchange_server_time = ensure_utc(exchange_server_time_utc)
    offset_ms = int((exchange_server_time - local_receive).total_seconds() * 1000)
    public_replay = BTCWSSequenceGapfillReplay.from_sequences(
        stream="public_market_data",
        observed_sequences=public_ws_sequences,
        gapfill_sequences=public_gapfill_sequences,
        recovery_method="local_fixture_gapfill_replay",
        trading_blocked_during_gapfill=True,
    )
    public_ws_status = BTCStreamStatus.CONNECTED if public_replay.recovered and public_replay.observed_sequences else BTCStreamStatus.DEGRADED
    exchange_status = BTCExchangeRuntimeStatus.CANCEL_ONLY if cancel_only else BTCExchangeRuntimeStatus.OK
    rest_status = BTCRestStatus.ORDER_ENTRY_DOWN if cancel_only else BTCRestStatus.OK
    last_market_data_time = observed_at if public_replay.observed_sequences else None

    snapshot = BTCExchangeRuntimeSnapshot(
        venue=venue,
        instrument_id=instrument_id,
        observed_at_utc=observed_at,
        exchange_status=exchange_status,
        public_ws_status=public_ws_status,
        private_ws_status=BTCStreamStatus.DISCONNECTED,
        rest_status=rest_status,
        server_time_offset_ms=offset_ms,
        rate_limit_budget_remaining=rate_limit_budget_remaining,
        order_rate_budget_remaining=order_rate_budget_remaining,
        last_market_data_time_utc=last_market_data_time,
        last_private_event_time_utc=None,
        last_reconciliation_time_utc=observed_at,
        unreconciled_order_count=0,
        unreconciled_fill_count=0,
        metadata_version=metadata_version,
        cancel_only=cancel_only,
        private_endpoints_enabled=False,
        order_endpoints_enabled=False,
        public_ws_gapfill=public_replay.to_gapfill_state(),
        private_ws_gapfill=None,
        max_server_time_offset_ms=max_server_time_offset_ms,
        min_rate_limit_budget_remaining=min_rate_limit_budget_remaining,
        min_order_rate_budget_remaining=min_order_rate_budget_remaining,
        mode=mode,
        notes={
            "evidence_type": "local_replay_probe",
            "scope": "local deterministic replay/probe only; no private/order endpoint touched",
            "private_endpoint_used": False,
            "order_endpoint_used": False,
            "real_order_submitted": False,
        },
    )
    snapshot_artifact = snapshot.to_artifact()
    blockers = list(snapshot_artifact.get("blockers", []))
    warnings = _local_probe_warnings(cancel_only=cancel_only, private_ws_status=snapshot.private_ws_status)
    transitions = _local_probe_transitions(
        offset_ms=offset_ms,
        max_server_time_offset_ms=max_server_time_offset_ms,
        metadata_version=metadata_version,
        rate_limit_budget_remaining=rate_limit_budget_remaining,
        min_rate_limit_budget_remaining=min_rate_limit_budget_remaining,
        order_rate_budget_remaining=order_rate_budget_remaining,
        min_order_rate_budget_remaining=min_order_rate_budget_remaining,
        public_replay=public_replay,
        cancel_only=cancel_only,
        blockers=blockers,
    )
    payload = {
        "schema_version": BTC_EXCHANGE_RUNTIME_LOCAL_PROBE_VERSION,
        "exchange_runtime_local_probe_version": BTC_EXCHANGE_RUNTIME_LOCAL_PROBE_VERSION,
        "status": "blocked_research_only" if blockers else "complete_research_only",
        "scope": "btc_exchange_runtime_local_replay_probe_no_private_no_order_endpoint",
        "venue": venue,
        "instrument_id": instrument_id,
        "mode": mode,
        "server_time_offset_diagnostics": {
            "local_receive_time_utc": local_receive.isoformat(),
            "exchange_server_time_utc": exchange_server_time.isoformat(),
            "offset_ms": offset_ms,
            "abs_offset_ms": abs(offset_ms),
            "threshold_ms": int(max_server_time_offset_ms),
            "within_threshold": abs(offset_ms) <= int(max_server_time_offset_ms),
            "explanation": "exchange_server_time_utc - local_receive_time_utc; positive means exchange clock is ahead",
        },
        "cancel_only_state": {
            "cancel_only": bool(cancel_only),
            "new_orders_blocked": bool(cancel_only),
            "allowed_runtime_actions": ["local_replay", "public_probe", "cancel_intent_validation"],
            "forbidden_runtime_actions": ["private_account_read", "order_submit", "order_replace", "position_increase"],
            "explanation": "cancel-only is a fail-closed runtime state; it can validate cancellation paths but cannot permit new orders.",
        },
        "ws_sequence_gapfill_replay": public_replay.to_dict(),
        "metadata_version_diagnostics": {
            "metadata_version": metadata_version,
            "present": bool(metadata_version),
            "explanation": "metadata version must identify the exchange instrument/rule snapshot used by this probe.",
        },
        "rate_limit_budget_explanation": {
            "public_rest_or_ws_budget": _budget_diagnostic(
                remaining=rate_limit_budget_remaining,
                threshold=min_rate_limit_budget_remaining,
                budget_name="public_rest_or_ws_budget",
            ),
            "order_entry_budget": _budget_diagnostic(
                remaining=order_rate_budget_remaining,
                threshold=min_order_rate_budget_remaining,
                budget_name="order_entry_budget",
            ),
            "source": "local fixture/probe values; no private/order endpoint queried",
        },
        "state_machine": {
            "initial_state": "initialized",
            "final_state": "fail_closed" if blockers else "local_probe_complete",
            "transition_count": len(transitions),
            "transitions": [transition.to_dict() for transition in transitions],
        },
        "runtime_snapshot": snapshot_artifact,
        "gate": _local_probe_gate(),
        "guardrails": _local_probe_guardrails(),
        "allows_live_orders": False,
        "real_order_submitted": False,
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "blockers": blockers,
        "warnings": warnings,
    }
    return apply_btc_artifact_schema(
        payload,
        decision=(
            "exchange_runtime_local_probe_fail_closed_no_paper_no_live"
            if blockers
            else "exchange_runtime_local_probe_complete_research_only_no_paper_no_live"
        ),
        generated_at_utc=observed_at,
        as_of_utc=observed_at,
        blockers=blockers,
        warnings=warnings,
        input_hashes={
            "local_probe_inputs": stable_payload_hash(
                {
                    "venue": venue,
                    "instrument_id": instrument_id,
                    "local_receive_time_utc": local_receive.isoformat(),
                    "exchange_server_time_utc": exchange_server_time.isoformat(),
                    "public_ws_sequences": list(public_ws_sequences),
                    "public_gapfill_sequences": list(public_gapfill_sequences),
                    "metadata_version": metadata_version,
                    "rate_limit_budget_remaining": rate_limit_budget_remaining,
                    "order_rate_budget_remaining": order_rate_budget_remaining,
                    "cancel_only": cancel_only,
                }
            ),
            "runtime_snapshot": stable_payload_hash(snapshot_artifact),
        },
    )


def _iso_or_none(value: datetime | None) -> str | None:
    return None if value is None else ensure_utc(value).isoformat()


def _budget_diagnostic(*, remaining: int, threshold: int, budget_name: str) -> dict[str, Any]:
    remaining_int = int(remaining)
    threshold_int = int(threshold)
    ok = remaining_int >= threshold_int
    return {
        "budget_name": budget_name,
        "remaining": remaining_int,
        "threshold": threshold_int,
        "status": "ok" if ok else "blocked",
        "explanation": (
            f"{budget_name} remaining {remaining_int} is above threshold {threshold_int}."
            if ok
            else f"{budget_name} remaining {remaining_int} is below threshold {threshold_int}; fail-closed."
        ),
    }


def _local_probe_transitions(
    *,
    offset_ms: int,
    max_server_time_offset_ms: int,
    metadata_version: str,
    rate_limit_budget_remaining: int,
    min_rate_limit_budget_remaining: int,
    order_rate_budget_remaining: int,
    min_order_rate_budget_remaining: int,
    public_replay: BTCWSSequenceGapfillReplay,
    cancel_only: bool,
    blockers: list[str],
) -> list[BTCRuntimeStateTransition]:
    transitions: list[BTCRuntimeStateTransition] = []
    state = "initialized"

    def add(event: str, to_state: str, reason: str, blockers_added: tuple[str, ...] = ()) -> None:
        nonlocal state
        transitions.append(
            BTCRuntimeStateTransition(
                step_id=len(transitions) + 1,
                event=event,
                from_state=state,
                to_state=to_state,
                reason=reason,
                blockers_added=blockers_added,
            )
        )
        state = to_state

    add(
        "server_time_offset_diagnosed",
        "server_time_ok" if abs(offset_ms) <= int(max_server_time_offset_ms) else "server_time_blocked",
        f"offset_ms={offset_ms}, threshold_ms={max_server_time_offset_ms}",
        ("btc_exchange_server_time_offset_exceeds_tolerance",)
        if "btc_exchange_server_time_offset_exceeds_tolerance" in blockers
        else (),
    )
    add(
        "metadata_version_checked",
        "metadata_ok" if metadata_version else "metadata_blocked",
        f"metadata_version={metadata_version or '<missing>'}",
        ("btc_exchange_metadata_version_missing",) if "btc_exchange_metadata_version_missing" in blockers else (),
    )
    rate_blockers = tuple(
        item
        for item in ("btc_exchange_rate_limit_budget_below_threshold", "btc_exchange_order_rate_budget_below_threshold")
        if item in blockers
    )
    add(
        "rate_limit_budget_explained",
        "rate_budget_ok" if not rate_blockers else "rate_budget_blocked",
        (
            f"public_remaining={rate_limit_budget_remaining}/{min_rate_limit_budget_remaining}, "
            f"order_remaining={order_rate_budget_remaining}/{min_order_rate_budget_remaining}"
        ),
        rate_blockers,
    )
    gap_blockers = tuple(item for item in blockers if item.startswith("btc_exchange_gapfill_"))
    add(
        "public_ws_sequence_gapfill_replayed",
        "gapfill_recovered" if public_replay.recovered and public_replay.observed_sequences else "gapfill_blocked",
        (
            f"missing={list(public_replay.missing_sequences)}, "
            f"recovered={list(public_replay.recovered_sequences)}, "
            f"unrecovered={list(public_replay.unrecovered_sequences)}"
        ),
        gap_blockers,
    )
    add(
        "cancel_only_state_evaluated",
        "cancel_only" if cancel_only else "new_order_contract_not_cancel_only",
        "cancel-only blocks position increases and new orders" if cancel_only else "cancel-only is false",
        ("btc_exchange_cancel_only_blocks_new_orders",) if "btc_exchange_cancel_only_blocks_new_orders" in blockers else (),
    )
    add(
        "private_order_endpoints_guarded",
        "read_only_no_private_order_endpoint",
        "local probe intentionally skipped private/order endpoints",
        tuple(
            item
            for item in blockers
            if item
            in {
                "btc_exchange_private_ws_not_connected:disconnected",
                "btc_exchange_last_private_event_time_missing",
            }
        ),
    )
    add(
        "final_fail_closed_gate",
        "fail_closed" if blockers else "local_probe_complete",
        f"blocker_count={len(blockers)}",
        tuple(blockers),
    )
    return transitions


def _local_probe_gate() -> dict[str, Any]:
    return {
        "research_only": True,
        "paper_queue_write_allowed": False,
        "paper_candidate_created": False,
        "paper_allowed": False,
        "live_unlock_allowed": False,
        "live_order_allowed": False,
        "oms_access_allowed": False,
        "broker_access_allowed": False,
        "reason": "Local runtime probe validates deterministic SRE contracts only; it is not paper/live evidence.",
    }


def _local_probe_guardrails() -> dict[str, bool]:
    return {
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "real_order_submitted": False,
        "paper_queue_write_allowed": False,
        "paper_candidate_created": False,
        "paper_allowed": False,
        "live_unlock_allowed": False,
        "live_order_allowed": False,
        "oms_access_allowed": False,
        "broker_access_allowed": False,
    }


def _local_probe_warnings(*, cancel_only: bool, private_ws_status: BTCStreamStatus) -> list[str]:
    warnings = [
        "btc_exchange_runtime_local_probe_research_only_no_paper_no_live",
        "btc_exchange_runtime_local_probe_no_private_or_order_endpoint_touched",
    ]
    if cancel_only:
        warnings.append("btc_exchange_cancel_only_state_intentionally_blocks_new_orders")
    if private_ws_status != BTCStreamStatus.CONNECTED:
        warnings.append("btc_exchange_private_stream_not_probed_locally")
    return warnings


def _sequence_ranges(values: tuple[int, ...]) -> list[dict[str, int]]:
    if not values:
        return []
    ranges: list[dict[str, int]] = []
    start = values[0]
    previous = values[0]
    for value in values[1:]:
        if value == previous + 1:
            previous = value
            continue
        ranges.append({"start": int(start), "end": int(previous), "count": int(previous - start + 1)})
        start = value
        previous = value
    ranges.append({"start": int(start), "end": int(previous), "count": int(previous - start + 1)})
    return ranges


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
