"""In-memory, offline-only CN order state machine."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from quant_cn.data.contracts import ensure_aware_timestamp, require_non_empty
from quant_cn.execution.models import Fill, OrderIntent, OrderState


class OMSConflictError(ValueError):
    """An idempotency key was reused with different immutable content."""


class OMSStateError(ValueError):
    """An invalid lifecycle transition was requested."""


class OfflineOMS:
    def __init__(self) -> None:
        self._orders: dict[str, OrderState] = {}
        self._client_ids: dict[str, tuple[str, str]] = {}
        self._fills: dict[str, str] = {}

    def submit(self, intent: OrderIntent) -> OrderState:
        prior_client = self._client_ids.get(intent.client_order_id)
        if prior_client is not None:
            order_id, fingerprint = prior_client
            if fingerprint != intent.fingerprint:
                raise OMSConflictError("client_order_id_conflict")
            return self._orders[order_id]
        if intent.order_id in self._orders:
            raise OMSConflictError("order_id_conflict")
        state = OrderState(intent=intent)
        self._orders[intent.order_id] = state
        self._client_ids[intent.client_order_id] = (intent.order_id, intent.fingerprint)
        return state

    def get(self, order_id: str) -> OrderState:
        try:
            return self._orders[require_non_empty(order_id, "order_id")]
        except KeyError as error:
            raise KeyError("order_not_found") from error

    def reject(self, order_id: str, blockers: tuple[str, ...]) -> OrderState:
        state = self.get(order_id)
        if state.terminal:
            raise OMSStateError("terminal_order_cannot_be_rejected")
        canonical = tuple(sorted(set(blockers)))
        if not canonical:
            raise ValueError("rejection_blocker_required")
        updated = replace(
            state,
            status="rejected",
            blockers=canonical,
            audit_events=state.audit_events + ("rejected",),
        )
        self._orders[order_id] = updated
        return updated

    def apply_fill(self, fill: Fill) -> OrderState:
        state = self.get(fill.order_id)
        prior = self._fills.get(fill.fill_id)
        if prior is not None:
            if prior != fill.fingerprint:
                raise OMSConflictError("fill_id_conflict")
            return state
        if state.status in {"cancelled", "rejected", "expired"}:
            raise OMSStateError("fill_for_terminal_order")
        if fill.stable_security_id != state.intent.stable_security_id:
            raise OMSConflictError("fill_security_mismatch")
        if fill.side != state.intent.side:
            raise OMSConflictError("fill_side_mismatch")
        new_quantity = state.filled_quantity + fill.quantity
        if new_quantity > state.intent.quantity:
            raise OMSStateError("overfill_blocked")
        fills = tuple(sorted(state.fills + (fill,), key=lambda item: (item.occurred_at, item.fill_id)))
        status = "filled" if new_quantity == state.intent.quantity else "partially_filled"
        updated = replace(
            state,
            status=status,
            filled_quantity=new_quantity,
            fills=fills,
            audit_events=state.audit_events + (f"fill:{fill.fill_id}", status),
        )
        self._orders[fill.order_id] = updated
        self._fills[fill.fill_id] = fill.fingerprint
        return updated

    def request_cancel(self, order_id: str, *, requested_at: datetime) -> OrderState:
        ensure_aware_timestamp(requested_at, "requested_at")
        state = self.get(order_id)
        if state.terminal:
            raise OMSStateError("terminal_order_cannot_cancel")
        updated = replace(
            state,
            status="cancel_requested",
            audit_events=state.audit_events + ("cancel_requested",),
        )
        self._orders[order_id] = updated
        return updated

    def confirm_cancel(self, order_id: str, *, confirmed_at: datetime) -> OrderState:
        ensure_aware_timestamp(confirmed_at, "confirmed_at")
        state = self.get(order_id)
        if state.status != "cancel_requested":
            raise OMSStateError("cancel_confirmation_without_request")
        updated = replace(
            state,
            status="cancelled",
            audit_events=state.audit_events + ("cancelled",),
        )
        self._orders[order_id] = updated
        return updated

    def expire(self, order_id: str, *, expired_at: datetime) -> OrderState:
        ensure_aware_timestamp(expired_at, "expired_at")
        state = self.get(order_id)
        if state.terminal:
            raise OMSStateError("terminal_order_cannot_expire")
        updated = replace(
            state,
            status="expired",
            audit_events=state.audit_events + ("expired",),
        )
        self._orders[order_id] = updated
        return updated

    def states(self) -> tuple[OrderState, ...]:
        return tuple(self._orders[key] for key in sorted(self._orders))
