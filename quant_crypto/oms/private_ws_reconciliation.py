"""Deterministic offline private-WS reconciliation contract.

No connector or endpoint exists in this module.  It accepts already supplied
fixtures, validates sequence/order/fill identity, and remains ineligible for
paper/live promotion.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Mapping, Protocol, Sequence

from quant_crypto.monitoring.artifact_schema import (
    apply_btc_artifact_schema,
    stable_payload_hash,
)
from quant_shared.core.time import ensure_utc


SCHEMA_VERSION = "btc_private_ws_offline_reconciliation_v2"
REAL_OBSERVATION_BLOCKER = (
    "btc_private_ws:real_current_head_private_ws_observation_missing"
)


class BTCPrivateWSOfflineState(str, Enum):
    DISCONNECTED = "disconnected"
    FIXTURE_LOADED = "fixture_loaded"
    RECONCILING = "reconciling"
    OFFLINE_RECONCILED = "offline_reconciled"
    BLOCKED = "blocked"


class BTCPrivateWSEventKind(str, Enum):
    ORDER_ACK = "order_ack"
    ORDER_UPDATE = "order_update"
    FILL = "fill"
    CANCEL_ACK = "cancel_ack"
    REJECT = "reject"
    OUTAGE = "outage"


class BTCPrivateWSRuntimeState(str, Enum):
    BLOCKED = "blocked"
    STARTUP_RECONCILING = "startup_reconciling"
    MONITORING = "monitoring"
    RECONNECT_RECONCILING = "reconnect_reconciling"
    CANCEL_ONLY = "cancel_only"


@dataclass(frozen=True)
class BTCPrivateWSFixtureEvent:
    sequence: int
    event_id: str
    kind: BTCPrivateWSEventKind
    client_order_id: str
    fill_id: str = ""
    filled_quantity: float = 0.0
    fill_price: float = 0.0
    remaining_quantity: float = 0.0
    order_status: str = ""
    idempotency_key: str = ""
    error_code: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.kind, BTCPrivateWSEventKind):
            object.__setattr__(self, "kind", BTCPrivateWSEventKind(str(self.kind)))


@dataclass(frozen=True)
class BTCPrivateWSStartupSnapshot:
    """REST-style account snapshot required before private-event consumption."""

    open_orders: tuple[Mapping[str, Any], ...]
    fills: tuple[Mapping[str, Any], ...]
    positions: tuple[Mapping[str, Any], ...]
    balance: Mapping[str, Any]
    funding_bills: tuple[Mapping[str, Any], ...]
    last_sequence: int
    private_ws_status: str
    rest_status: str
    captured_at_utc: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "last_sequence", int(self.last_sequence))
        object.__setattr__(
            self, "captured_at_utc", ensure_utc(self.captured_at_utc)
        )


class BTCPrivateWSReconciliationTransport(Protocol):
    """Injected private-state source.  The reconciler owns no socket or HTTP client."""

    def fetch_startup_snapshot(self) -> BTCPrivateWSStartupSnapshot: ...


@dataclass(frozen=True)
class BTCPrivateWSRuntimeReceipt:
    state: BTCPrivateWSRuntimeState
    opening_allowed: bool
    cancel_only: bool
    snapshot_reconciled: bool
    reconnect_reconciled: bool
    last_sequence: int
    duplicate_event_count: int
    lifecycle_coverage: Mapping[str, bool]
    blockers: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "btc_private_ws_runtime_reconciliation_v1",
            "state": self.state.value,
            "opening_allowed": self.opening_allowed,
            "cancel_only": self.cancel_only,
            "snapshot_reconciled": self.snapshot_reconciled,
            "reconnect_reconciled": self.reconnect_reconciled,
            "last_sequence": self.last_sequence,
            "duplicate_event_count": self.duplicate_event_count,
            "lifecycle_coverage": dict(self.lifecycle_coverage),
            "blockers": list(self.blockers),
            "network_owned_by_reconciler": False,
            "socket_created_by_reconciler": False,
            "http_client_created_by_reconciler": False,
        }


class BTCPrivateWSRuntimeReconciler:
    """Fail-closed state machine over an injected snapshot transport and events."""

    def __init__(
        self,
        *,
        transport: BTCPrivateWSReconciliationTransport,
        owned_client_order_ids: Sequence[str],
    ) -> None:
        self._transport = transport
        self._owned = {str(value) for value in owned_client_order_ids if str(value)}
        self._state = BTCPrivateWSRuntimeState.BLOCKED
        self._last_sequence = 0
        self._seen_events: dict[str, dict[str, Any]] = {}
        self._duplicate_event_count = 0
        self._coverage = {
            "partial": False,
            "fill": False,
            "reject": False,
            "cancel": False,
            "reconnect": False,
        }
        self._blockers: list[str] = []
        self._snapshot_reconciled = False
        self._reconnect_reconciled = False

    def startup(self) -> BTCPrivateWSRuntimeReceipt:
        self._state = BTCPrivateWSRuntimeState.STARTUP_RECONCILING
        self._reconcile_snapshot(reconnect=False)
        return self.receipt()

    def on_disconnect(self, *, reason: str = "private_ws_disconnected") -> None:
        self._enter_cancel_only(f"btc_private_ws:{reason}")

    def on_reconnect(self) -> BTCPrivateWSRuntimeReceipt:
        self._state = BTCPrivateWSRuntimeState.RECONNECT_RECONCILING
        self._reconnect_reconciled = False
        self._coverage["reconnect"] = True
        self._blockers = [
            blocker
            for blocker in self._blockers
            if blocker != "btc_private_ws:private_ws_disconnected"
        ]
        self._reconcile_snapshot(reconnect=True)
        return self.receipt()

    def consume(self, event: BTCPrivateWSFixtureEvent) -> BTCPrivateWSRuntimeReceipt:
        if self._state != BTCPrivateWSRuntimeState.MONITORING:
            self._enter_cancel_only(
                "btc_private_ws:event_received_before_snapshot_reconciliation"
            )
            return self.receipt()
        row = _event_row(event)
        prior = self._seen_events.get(event.event_id)
        if prior is not None:
            if prior == row:
                self._duplicate_event_count += 1
                return self.receipt()
            self._enter_cancel_only("btc_private_ws:conflicting_duplicate_event")
            return self.receipt()
        if event.sequence <= self._last_sequence:
            self._enter_cancel_only("btc_private_ws:out_of_order_event")
            return self.receipt()
        if event.sequence != self._last_sequence + 1:
            self._enter_cancel_only("btc_private_ws:sequence_gap")
            return self.receipt()
        if (
            event.kind != BTCPrivateWSEventKind.OUTAGE
            and event.client_order_id not in self._owned
        ):
            self._enter_cancel_only("btc_private_ws:unknown_client_order_id")
            return self.receipt()
        if event.kind == BTCPrivateWSEventKind.FILL and not event.fill_id:
            self._enter_cancel_only("btc_private_ws:fill_id_missing")
            return self.receipt()
        if event.kind == BTCPrivateWSEventKind.OUTAGE:
            self._enter_cancel_only("btc_private_ws:outage")
            return self.receipt()
        self._seen_events[event.event_id] = row
        self._last_sequence = event.sequence
        if event.kind == BTCPrivateWSEventKind.FILL:
            self._coverage["fill"] = True
            if (
                event.remaining_quantity > 0
                or event.order_status.strip().lower() == "partially_filled"
            ):
                self._coverage["partial"] = True
        elif event.kind == BTCPrivateWSEventKind.REJECT:
            self._coverage["reject"] = True
        elif event.kind == BTCPrivateWSEventKind.CANCEL_ACK:
            self._coverage["cancel"] = True
        return self.receipt()

    def receipt(self) -> BTCPrivateWSRuntimeReceipt:
        opening_allowed = (
            self._state == BTCPrivateWSRuntimeState.MONITORING
            and self._snapshot_reconciled
            and not self._blockers
        )
        return BTCPrivateWSRuntimeReceipt(
            state=self._state,
            opening_allowed=opening_allowed,
            cancel_only=self._state == BTCPrivateWSRuntimeState.CANCEL_ONLY,
            snapshot_reconciled=self._snapshot_reconciled,
            reconnect_reconciled=self._reconnect_reconciled,
            last_sequence=self._last_sequence,
            duplicate_event_count=self._duplicate_event_count,
            lifecycle_coverage=dict(self._coverage),
            blockers=tuple(_dedupe(self._blockers)),
        )

    def _reconcile_snapshot(self, *, reconnect: bool) -> None:
        try:
            snapshot = self._transport.fetch_startup_snapshot()
        except Exception as exc:
            self._enter_cancel_only(
                f"btc_private_ws:snapshot_transport_failed:{type(exc).__name__}"
            )
            return
        blockers = _startup_snapshot_blockers(
            snapshot, owned_client_order_ids=self._owned
        )
        if blockers:
            for blocker in blockers:
                self._enter_cancel_only(blocker)
            return
        self._last_sequence = snapshot.last_sequence
        self._snapshot_reconciled = True
        self._reconnect_reconciled = reconnect
        self._state = BTCPrivateWSRuntimeState.MONITORING

    def _enter_cancel_only(self, blocker: str) -> None:
        self._state = BTCPrivateWSRuntimeState.CANCEL_ONLY
        self._blockers.append(blocker)


def _startup_snapshot_blockers(
    snapshot: BTCPrivateWSStartupSnapshot,
    *,
    owned_client_order_ids: set[str],
) -> list[str]:
    blockers: list[str] = []
    if snapshot.private_ws_status != "connected":
        blockers.append("btc_private_ws:private_stream_not_connected")
    if snapshot.rest_status != "ok":
        blockers.append("btc_private_ws:rest_snapshot_not_ok")
    if snapshot.last_sequence < 0:
        blockers.append("btc_private_ws:snapshot_sequence_invalid")
    for row in snapshot.open_orders:
        order_id = str(row.get("client_order_id") or row.get("clOrdId") or "")
        if not order_id or order_id not in owned_client_order_ids:
            blockers.append("btc_private_ws:unknown_open_order")
    for row in snapshot.fills:
        order_id = str(row.get("client_order_id") or row.get("clOrdId") or "")
        if not order_id or order_id not in owned_client_order_ids:
            blockers.append("btc_private_ws:unknown_fill")
    if not isinstance(snapshot.balance, Mapping) or not snapshot.balance:
        blockers.append("btc_private_ws:balance_snapshot_missing")
    if len(snapshot.positions) > 1:
        blockers.append("btc_private_ws:multiple_positions_present")
    return _dedupe(blockers)


def reconcile_private_ws_offline_fixture(
    *,
    current_head: str,
    source_head: str,
    generated_at_utc: datetime,
    events: Sequence[BTCPrivateWSFixtureEvent],
    expected_order_ids: Sequence[str],
    source_receipt: Mapping[str, Any],
    expected_idempotency_keys: Mapping[str, str] | None = None,
    required_scenarios: Sequence[str] = (),
) -> dict[str, Any]:
    generated = ensure_utc(generated_at_utc)
    event_rows = [_event_row(row) for row in events]
    events_hash = stable_payload_hash(event_rows)
    transitions = [
        BTCPrivateWSOfflineState.DISCONNECTED.value,
        BTCPrivateWSOfflineState.FIXTURE_LOADED.value,
        BTCPrivateWSOfflineState.RECONCILING.value,
    ]
    blockers: list[str] = []
    if source_head != current_head:
        blockers.append("btc_private_ws:source_head_mismatch")
    if str(source_receipt.get("events_sha256") or "") != events_hash:
        blockers.append("btc_private_ws:fixture_hash_mismatch")
    if not str(source_receipt.get("fixture_version") or "").strip():
        blockers.append("btc_private_ws:fixture_version_missing")
    if not events:
        blockers.append("btc_private_ws:fixture_empty")
    blockers.extend(
        _event_blockers(
            events,
            expected_order_ids=expected_order_ids,
            expected_idempotency_keys=expected_idempotency_keys,
        )
    )
    coverage = _lifecycle_coverage(events)
    for scenario in required_scenarios:
        if coverage.get(str(scenario)) is not True:
            blockers.append(f"btc_private_ws:scenario_missing:{scenario}")
    engineering_blockers = _dedupe(blockers)
    final_state = (
        BTCPrivateWSOfflineState.OFFLINE_RECONCILED
        if not engineering_blockers
        else BTCPrivateWSOfflineState.BLOCKED
    )
    transitions.append(final_state.value)
    all_blockers = [*engineering_blockers, REAL_OBSERVATION_BLOCKER]
    fill_rows = [row for row in event_rows if row["kind"] == BTCPrivateWSEventKind.FILL.value]
    payload = {
        "schema_version": SCHEMA_VERSION,
        "status": "blocked",
        "source_head": source_head,
        "code_commit": current_head,
        "state": final_state.value,
        "state_transitions": transitions,
        "fixture_only": True,
        "offline_fixture_validated": not engineering_blockers,
        "real_observation": False,
        "private_ws_observed": False,
        "promotion_evidence_ready": False,
        "paper_ready": False,
        "live_ready": False,
        "source_receipt": {
            "fixture_version": str(source_receipt.get("fixture_version") or ""),
            "events_sha256": events_hash,
        },
        "event_count": len(event_rows),
        "fill_count": len(fill_rows),
        "reconciled_order_ids": sorted(set(expected_order_ids)),
        "fill_ledger_hash": stable_payload_hash(fill_rows),
        "lifecycle_coverage": coverage,
        "idempotency_keys_validated": expected_idempotency_keys is not None,
        "outage_fail_closed": coverage["outage"]
        and coverage["cancel_only"],
        "safety": {
            "network_accessed": False,
            "private_endpoint_accessed": False,
            "order_endpoint_accessed": False,
            "paper_queue_write_enabled": False,
            "real_orders_enabled": False,
            "secrets_read": False,
        },
        "blockers": all_blockers,
    }
    return apply_btc_artifact_schema(
        payload,
        decision="offline_fixture_reconciled_real_private_ws_still_blocked"
        if not engineering_blockers
        else "offline_fixture_reconciliation_failed_closed",
        generated_at_utc=generated,
        as_of_utc=generated,
        blockers=all_blockers,
        warnings=[],
        input_hashes={
            "private_ws_fixture": events_hash,
            "expected_order_ids": stable_payload_hash(sorted(expected_order_ids)),
        },
    )


def _event_row(row: BTCPrivateWSFixtureEvent) -> dict[str, Any]:
    payload = {
        "sequence": int(row.sequence),
        "event_id": row.event_id,
        "kind": row.kind.value,
        "client_order_id": row.client_order_id,
        "fill_id": row.fill_id,
        "filled_quantity": float(row.filled_quantity),
        "fill_price": float(row.fill_price),
    }
    optional = {
        "remaining_quantity": float(row.remaining_quantity),
        "order_status": row.order_status,
        "idempotency_key": row.idempotency_key,
        "error_code": row.error_code,
    }
    if any(
        value not in ("", 0.0)
        for value in optional.values()
    ):
        payload.update(optional)
    return payload


def _event_blockers(
    events: Sequence[BTCPrivateWSFixtureEvent],
    *,
    expected_order_ids: Sequence[str],
    expected_idempotency_keys: Mapping[str, str] | None,
) -> list[str]:
    blockers: list[str] = []
    sequences = [row.sequence for row in events]
    if sequences != sorted(sequences):
        blockers.append("btc_private_ws:sequence_not_monotonic")
    if sequences and sequences != list(range(sequences[0], sequences[0] + len(sequences))):
        blockers.append("btc_private_ws:sequence_gap")
    event_ids = [row.event_id for row in events]
    if any(not value for value in event_ids) or len(event_ids) != len(set(event_ids)):
        blockers.append("btc_private_ws:event_ids_invalid")
    expected = set(expected_order_ids)
    if not expected or any(not value for value in expected):
        blockers.append("btc_private_ws:expected_order_ids_invalid")
    if any(
        row.kind != BTCPrivateWSEventKind.OUTAGE
        and row.client_order_id not in expected
        for row in events
    ):
        blockers.append("btc_private_ws:unknown_client_order_id")
    fill_ids = [row.fill_id for row in events if row.kind == BTCPrivateWSEventKind.FILL]
    if any(not value for value in fill_ids) or len(fill_ids) != len(set(fill_ids)):
        blockers.append("btc_private_ws:fill_ids_invalid")
    if any(
        row.kind == BTCPrivateWSEventKind.FILL
        and (row.filled_quantity <= 0 or row.fill_price <= 0)
        for row in events
    ):
        blockers.append("btc_private_ws:fill_quantity_or_price_non_positive")
    acknowledged = {
        row.client_order_id
        for row in events
        if row.kind == BTCPrivateWSEventKind.ORDER_ACK
    }
    if expected - acknowledged:
        blockers.append("btc_private_ws:order_ack_missing")
    if expected_idempotency_keys is not None:
        expected_keys = {
            str(order_id): str(key)
            for order_id, key in expected_idempotency_keys.items()
        }
        if set(expected_keys) != expected or any(
            not key for key in expected_keys.values()
        ):
            blockers.append("btc_private_ws:idempotency_expectation_invalid")
        for row in events:
            if row.kind == BTCPrivateWSEventKind.OUTAGE:
                continue
            if row.idempotency_key != expected_keys.get(row.client_order_id):
                blockers.append("btc_private_ws:idempotency_key_mismatch")
        reverse: dict[str, str] = {}
        for order_id, key in expected_keys.items():
            other = reverse.setdefault(key, order_id)
            if other != order_id:
                blockers.append("btc_private_ws:idempotency_key_reused")
    return blockers


def _lifecycle_coverage(
    events: Sequence[BTCPrivateWSFixtureEvent],
) -> dict[str, bool]:
    fill_events = [
        row for row in events if row.kind == BTCPrivateWSEventKind.FILL
    ]
    partial = any(
        row.remaining_quantity > 0
        or row.order_status.strip().lower() == "partially_filled"
        for row in fill_events
    )
    outage = any(
        row.kind == BTCPrivateWSEventKind.OUTAGE for row in events
    )
    return {
        "ack": any(
            row.kind == BTCPrivateWSEventKind.ORDER_ACK for row in events
        ),
        "partial": partial,
        "fill": bool(fill_events),
        "reject": any(
            row.kind == BTCPrivateWSEventKind.REJECT for row in events
        ),
        "cancel": any(
            row.kind == BTCPrivateWSEventKind.CANCEL_ACK for row in events
        ),
        "outage": outage,
        "cancel_only": outage,
        "idempotency": all(
            row.kind == BTCPrivateWSEventKind.OUTAGE
            or bool(row.idempotency_key)
            for row in events
        ),
    }


def _dedupe(values: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(values))


__all__ = [
    "BTCPrivateWSEventKind",
    "BTCPrivateWSFixtureEvent",
    "BTCPrivateWSOfflineState",
    "BTCPrivateWSReconciliationTransport",
    "BTCPrivateWSRuntimeReceipt",
    "BTCPrivateWSRuntimeReconciler",
    "BTCPrivateWSRuntimeState",
    "BTCPrivateWSStartupSnapshot",
    "REAL_OBSERVATION_BLOCKER",
    "SCHEMA_VERSION",
    "reconcile_private_ws_offline_fixture",
]
