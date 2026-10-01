"""Fail-closed US paper OMS lifecycle, ledger UoW, and reconciliation service.

The service consumes injected fixture callbacks and broker snapshots.  It has
no broker SDK, environment-variable, network, paper-queue, or order endpoint
dependency.  Durable mutations are committed through the existing paper ledger
unit of work so order, fill, position, cash, audit, and state evidence advance
atomically.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from quant_shared.core.serialization import canonical_payload_hash
from quant_us.live.paper_ledger_uow import (
    PaperLedgerCommitError,
    ReplaceFn,
    commit_paper_ledger_cycle,
    prepare_paper_ledger_transaction,
    recover_incomplete_paper_ledger_transactions,
)


SCHEMA_VERSION = "us_v3_paper_oms_reconciliation_v1"
STATE_SCHEMA_VERSION = "us_v3_paper_oms_state_v1"
REQUIRED_LIFECYCLE_STATES: tuple[str, ...] = (
    "created",
    "risk_checked",
    "accepted",
    "partial",
    "filled",
    "cancel",
    "rejected",
    "expired",
    "unknown",
    "reconciled",
)
OPERATIONAL_LIFECYCLE_STATES: tuple[str, ...] = (
    *REQUIRED_LIFECYCLE_STATES,
    "cancel_pending",
)
TERMINAL_BEFORE_RECONCILIATION = {"filled", "cancel", "rejected", "expired"}
CALLBACK_STATES = {
    "accepted",
    "partial",
    "filled",
    "cancel_pending",
    "cancel",
    "rejected",
    "expired",
    "unknown",
}
ALLOWED_TRANSITIONS: dict[str | None, set[str]] = {
    None: {"created"},
    "created": {"risk_checked"},
    "risk_checked": {"accepted", "rejected", "expired", "unknown"},
    "accepted": {
        "partial",
        "filled",
        "cancel_pending",
        "rejected",
        "expired",
        "unknown",
    },
    "partial": {
        "partial",
        "filled",
        "cancel_pending",
        "expired",
        "unknown",
    },
    "cancel_pending": {"partial", "filled", "cancel", "unknown"},
    "filled": {"reconciled"},
    "cancel": {"reconciled"},
    "rejected": {"reconciled"},
    "expired": {"reconciled"},
    "unknown": {"reconciled"},
    "reconciled": set(),
}
LEDGER_PATHS = {
    "orders": "orders.jsonl",
    "fills": "fills.jsonl",
    "positions": "positions.jsonl",
    "cash": "cash_ledger.jsonl",
    "audit": "audit.jsonl",
}


class PaperOmsRecoveryError(RuntimeError):
    """Raised when durable paper evidence cannot be safely recovered."""

    def __init__(self, blockers: Sequence[str]) -> None:
        self.blockers = list(dict.fromkeys(str(item) for item in blockers if item))
        super().__init__("paper_oms_recovery_blocked:" + ",".join(self.blockers))


@dataclass(frozen=True)
class PaperOmsResult:
    status: str
    order_id: str
    lifecycle_state: str
    duplicate: bool
    ledger_mutated: bool
    halt_new_orders: bool
    blockers: tuple[str, ...]
    uow_operation_count: int = 0
    recovered_transaction_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "order_id": self.order_id,
            "lifecycle_state": self.lifecycle_state,
            "duplicate": self.duplicate,
            "ledger_mutated": self.ledger_mutated,
            "halt_new_orders": self.halt_new_orders,
            "blockers": list(self.blockers),
            "uow_operation_count": self.uow_operation_count,
            "recovered_transaction_ids": list(self.recovered_transaction_ids),
        }


class FilePaperOmsRepository:
    """Strict file adapter backed by the paper ledger unit of work."""

    def __init__(
        self,
        ledger_root: Path,
        *,
        initial_cash: float,
        apply_replace: ReplaceFn | None = None,
    ) -> None:
        self.ledger_root = ledger_root.resolve()
        self.initial_cash = float(initial_cash)
        self.apply_replace = apply_replace
        self.last_recovery = recover_incomplete_paper_ledger_transactions(
            self.ledger_root
        )
        if self.last_recovery.blockers:
            raise PaperOmsRecoveryError(self.last_recovery.blockers)
        self.state = self._load_state()

    def snapshot(self) -> dict[str, Any]:
        return deepcopy(self.state)

    def commit(
        self,
        *,
        timestamp: str,
        generated_at: str,
        next_state: Mapping[str, Any],
        rows: Mapping[str, Sequence[Mapping[str, Any]]],
    ) -> dict[str, Any]:
        state = deepcopy(dict(next_state))
        counts = dict(state.get("ledger_counts", {}))
        jsonl_rows: dict[str, Sequence[Mapping[str, Any]]] = {}
        for ledger_name, relative_path in LEDGER_PATHS.items():
            new_rows = list(rows.get(ledger_name, []))
            if new_rows:
                jsonl_rows[relative_path] = new_rows
                counts[ledger_name] = int(counts.get(ledger_name, 0)) + len(new_rows)
            else:
                counts.setdefault(ledger_name, 0)
        state["ledger_counts"] = counts
        state["updated_at"] = generated_at
        state["state_hash"] = _state_hash(state)
        summary = commit_paper_ledger_cycle(
            ledger_root=self.ledger_root,
            timestamp=timestamp,
            generated_at=generated_at,
            jsonl_rows=jsonl_rows,
            json_documents={"oms_state.json": state},
            apply_replace=self.apply_replace,
        )
        self.state = state
        return summary

    def _load_state(self) -> dict[str, Any]:
        rows_by_ledger = {
            name: _read_jsonl_strict(self.ledger_root / relative)
            for name, relative in LEDGER_PATHS.items()
        }
        state_path = self.ledger_root / "oms_state.json"
        if not state_path.exists():
            if any(rows_by_ledger.values()):
                raise PaperOmsRecoveryError(["oms_state_missing_with_existing_ledgers"])
            return _new_state(self.initial_cash)
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            raise PaperOmsRecoveryError(
                [f"oms_state_unreadable:{type(exc).__name__}"]
            ) from exc
        blockers = _validate_recovered_state(
            state=state,
            rows_by_ledger=rows_by_ledger,
            initial_cash=self.initial_cash,
        )
        if blockers:
            raise PaperOmsRecoveryError(blockers)
        return dict(state)


class PaperOmsReconciliationService:
    """Application service for injected, local-only US paper lifecycle evidence."""

    def __init__(
        self,
        repository: FilePaperOmsRepository,
        *,
        clock: Callable[[], str],
    ) -> None:
        self.repository = repository
        self.clock = clock

    def snapshot(self) -> dict[str, Any]:
        return self.repository.snapshot()

    def begin_order(
        self,
        *,
        order_id: str,
        client_order_id: str,
        symbol: str,
        side: str,
        quantity: float,
        risk_approved: bool,
        market_open: bool,
    ) -> PaperOmsResult:
        state = self.repository.snapshot()
        if state.get("halt_new_orders") is True:
            return self._block_without_fill(
                state=state,
                order_id=order_id,
                blocker=f"new_order_blocked_while_halted:{order_id}",
                event_id=f"halted-order:{order_id}",
            )
        existing = _mapping(state.get("orders")).get(order_id)
        if existing is not None:
            if str(existing.get("client_order_id")) == client_order_id:
                return self._result(
                    status="duplicate_order_ignored",
                    order_id=order_id,
                    state=state,
                    duplicate=True,
                    mutated=False,
                )
            return self._block_without_fill(
                state=state,
                order_id=order_id,
                blocker=f"order_id_conflict:{order_id}",
                event_id=f"order-conflict:{order_id}",
            )
        if quantity <= 0 or not math.isfinite(quantity):
            raise ValueError("paper_order_quantity_must_be_positive")
        normalized_side = side.lower()
        if normalized_side not in {"buy", "sell"}:
            raise ValueError("paper_order_side_invalid")
        now = self.clock()
        order = {
            "order_id": order_id,
            "client_order_id": client_order_id,
            "symbol": symbol,
            "side": normalized_side,
            "quantity": float(quantity),
            "filled_quantity": 0.0,
            "average_fill_price": 0.0,
            "status": "created",
            "lifecycle": ["created"],
            "created_at": now,
            "updated_at": now,
        }
        next_state = deepcopy(state)
        orders = _mapping(next_state.get("orders"))
        orders[order_id] = order
        next_state["orders"] = orders
        order_rows = [_order_event(order, "created", now, "order_created")]
        _transition(order, "risk_checked", now)
        order_rows.append(
            _order_event(order, "risk_checked", now, "risk_check_completed")
        )
        if not risk_approved:
            _transition(order, "rejected", now)
            order_rows.append(
                _order_event(order, "rejected", now, "risk_rejected")
            )
        elif not market_open:
            _transition(order, "rejected", now)
            order_rows.append(
                _order_event(order, "rejected", now, "market_closed")
            )
        audit = {
            "event_id": f"begin:{order_id}",
            "event_type": "order_begin",
            "order_id": order_id,
            "occurred_at": now,
            "risk_approved": bool(risk_approved),
            "market_open": bool(market_open),
            "broker_call_used": False,
            "order_endpoint_used": False,
        }
        summary = self.repository.commit(
            timestamp=now,
            generated_at=now,
            next_state=next_state,
            rows={"orders": order_rows, "audit": [audit]},
        )
        return self._result(
            status="order_started",
            order_id=order_id,
            state=self.repository.snapshot(),
            duplicate=False,
            mutated=True,
            summary=summary,
        )

    def process_callback(self, callback: Mapping[str, Any]) -> PaperOmsResult:
        event_id = str(callback.get("event_id", "")).strip()
        order_id = str(callback.get("order_id", "")).strip()
        desired = str(callback.get("status", "")).strip()
        if not event_id or not order_id:
            raise ValueError("paper_callback_event_and_order_id_required")
        if desired not in CALLBACK_STATES:
            raise ValueError(f"paper_callback_status_invalid:{desired}")
        state = self.repository.snapshot()
        processed_events = set(_string_list(state.get("processed_event_ids")))
        if event_id in processed_events:
            return self._result(
                status="duplicate_callback_ignored",
                order_id=order_id,
                state=state,
                duplicate=True,
                mutated=False,
            )
        order = _mapping(state.get("orders")).get(order_id)
        if order is None:
            return self._block_without_fill(
                state=state,
                order_id=order_id,
                blocker=f"unknown_local_order:{order_id}",
                event_id=event_id,
            )

        now = self.clock()
        next_state = deepcopy(state)
        next_order = _mapping(next_state["orders"])[order_id]
        rows: dict[str, list[dict[str, Any]]] = {
            "orders": [],
            "fills": [],
            "positions": [],
            "cash": [],
            "audit": [],
        }
        processed_events.add(event_id)
        next_state["processed_event_ids"] = sorted(processed_events)

        current = str(next_order.get("status", ""))
        if desired not in ALLOWED_TRANSITIONS.get(current, set()):
            blocker = f"out_of_order_callback:{order_id}:{current}->{desired}"
            _force_unknown(next_order, now)
            _add_blocker(next_state, blocker)
            rows["orders"].append(
                _order_event(next_order, "unknown", now, blocker)
            )
            rows["audit"].append(
                _callback_audit(callback, now, accepted=False, blocker=blocker)
            )
            summary = self.repository.commit(
                timestamp=now,
                generated_at=now,
                next_state=next_state,
                rows=rows,
            )
            return self._result(
                status="callback_blocked_fail_closed",
                order_id=order_id,
                state=self.repository.snapshot(),
                duplicate=False,
                mutated=True,
                summary=summary,
            )

        fill_id = str(callback.get("fill_id", "")).strip()
        processed_fills = set(_string_list(next_state.get("processed_fill_ids")))
        if desired in {"partial", "filled"} and fill_id in processed_fills:
            rows["audit"].append(
                _callback_audit(
                    callback,
                    now,
                    accepted=False,
                    blocker=f"duplicate_fill_ignored:{fill_id}",
                )
            )
            summary = self.repository.commit(
                timestamp=now,
                generated_at=now,
                next_state=next_state,
                rows=rows,
            )
            return self._result(
                status="duplicate_fill_ignored",
                order_id=order_id,
                state=self.repository.snapshot(),
                duplicate=True,
                mutated=True,
                summary=summary,
            )

        if desired in {"partial", "filled"}:
            fill_blocker = _apply_fill(
                state=next_state,
                order=next_order,
                callback=callback,
                now=now,
                rows=rows,
            )
            if fill_blocker:
                _force_unknown(next_order, now)
                _add_blocker(next_state, fill_blocker)
                rows["orders"].append(
                    _order_event(next_order, "unknown", now, fill_blocker)
                )
                rows["audit"].append(
                    _callback_audit(
                        callback,
                        now,
                        accepted=False,
                        blocker=fill_blocker,
                    )
                )
                summary = self.repository.commit(
                    timestamp=now,
                    generated_at=now,
                    next_state=next_state,
                    rows=rows,
                )
                return self._result(
                    status="fill_blocked_fail_closed",
                    order_id=order_id,
                    state=self.repository.snapshot(),
                    duplicate=False,
                    mutated=True,
                    summary=summary,
                )
            processed_fills.add(fill_id)
            next_state["processed_fill_ids"] = sorted(processed_fills)

        _transition(next_order, desired, now)
        rows["orders"].append(
            _order_event(next_order, desired, now, "callback_accepted")
        )
        rows["audit"].append(
            _callback_audit(callback, now, accepted=True, blocker="")
        )
        if desired in {"unknown", "cancel_pending"}:
            next_state["halt_new_orders"] = True
        elif desired == "cancel":
            _refresh_halt_state(next_state)
        summary = self.repository.commit(
            timestamp=now,
            generated_at=now,
            next_state=next_state,
            rows=rows,
        )
        return self._result(
            status="callback_committed",
            order_id=order_id,
            state=self.repository.snapshot(),
            duplicate=False,
            mutated=True,
            summary=summary,
        )

    def reconcile(self, broker_snapshot: Mapping[str, Any]) -> dict[str, Any]:
        """Compare an injected broker snapshot and fail closed on any break."""

        state = self.repository.snapshot()
        next_state = deepcopy(state)
        now = self.clock()
        breaks = _reconciliation_breaks(next_state, broker_snapshot)
        audit = {
            "event_id": str(broker_snapshot.get("snapshot_id", "reconciliation")),
            "event_type": "reconciliation",
            "occurred_at": now,
            "breaks": breaks,
            "broker_call_used": False,
            "snapshot_injected": True,
        }
        order_rows: list[dict[str, Any]] = []
        if breaks:
            blocker = "reconciliation_break:" + "|".join(breaks)
            _add_blocker(next_state, blocker)
            next_state["last_reconciliation"] = {
                "status": "breaks_detected",
                "breaks": breaks,
                "reconciled_at": now,
            }
            status = "breaks_detected_fail_closed"
        else:
            snapshot_orders = _mapping(broker_snapshot.get("orders"))
            for order_id, order in _mapping(next_state.get("orders")).items():
                current = str(order.get("status", ""))
                external = str(snapshot_orders.get(order_id, ""))
                if current in TERMINAL_BEFORE_RECONCILIATION or (
                    current in {"unknown", "cancel_pending"}
                    and external in TERMINAL_BEFORE_RECONCILIATION
                ):
                    _transition(order, "reconciled", now)
                    order_rows.append(
                        _order_event(
                            order,
                            "reconciled",
                            now,
                            f"injected_snapshot_confirmed:{external}",
                        )
                    )
            next_state["blockers"] = []
            next_state["halt_new_orders"] = False
            next_state["last_reconciliation"] = {
                "status": "clean",
                "breaks": [],
                "reconciled_at": now,
            }
            status = "reconciled_clean"
        summary = self.repository.commit(
            timestamp=now,
            generated_at=now,
            next_state=next_state,
            rows={"orders": order_rows, "audit": [audit]},
        )
        return {
            "status": status,
            "breaks": breaks,
            "halt_new_orders": self.repository.state["halt_new_orders"],
            "reconciled_order_ids": [
                str(row["order_id"]) for row in order_rows
            ],
            "uow_operation_count": summary["operation_count"],
        }

    def _block_without_fill(
        self,
        *,
        state: Mapping[str, Any],
        order_id: str,
        blocker: str,
        event_id: str,
    ) -> PaperOmsResult:
        next_state = deepcopy(dict(state))
        now = self.clock()
        _add_blocker(next_state, blocker)
        processed_events = set(_string_list(next_state.get("processed_event_ids")))
        processed_events.add(event_id)
        next_state["processed_event_ids"] = sorted(processed_events)
        audit = {
            "event_id": event_id,
            "event_type": "callback_blocked",
            "order_id": order_id,
            "occurred_at": now,
            "blocker": blocker,
            "broker_call_used": False,
            "fill_created": False,
        }
        summary = self.repository.commit(
            timestamp=now,
            generated_at=now,
            next_state=next_state,
            rows={"audit": [audit]},
        )
        return self._result(
            status="blocked_fail_closed",
            order_id=order_id,
            state=self.repository.snapshot(),
            duplicate=False,
            mutated=True,
            summary=summary,
        )

    def _result(
        self,
        *,
        status: str,
        order_id: str,
        state: Mapping[str, Any],
        duplicate: bool,
        mutated: bool,
        summary: Mapping[str, Any] | None = None,
    ) -> PaperOmsResult:
        order = _mapping(state.get("orders")).get(order_id, {})
        return PaperOmsResult(
            status=status,
            order_id=order_id,
            lifecycle_state=str(order.get("status", "unknown")),
            duplicate=duplicate,
            ledger_mutated=mutated,
            halt_new_orders=state.get("halt_new_orders") is True,
            blockers=tuple(_string_list(state.get("blockers"))),
            uow_operation_count=int((summary or {}).get("operation_count", 0)),
            recovered_transaction_ids=tuple(
                self.repository.last_recovery.recovered_transaction_ids
            ),
        )


def credential_review_metadata(review: Mapping[str, Any]) -> dict[str, Any]:
    """Validate metadata-only broker review without accessing credentials."""

    allowed = {
        "reviewer",
        "reviewed_at",
        "broker",
        "account_hash",
        "approval_ticket",
        "permission_conclusion",
    }
    unknown = sorted(set(str(key) for key in review) - allowed)
    secret_tokens = ("secret", "token", "password", "api_key", "passphrase")
    secret_like = sorted(
        str(key)
        for key in review
        if any(token in str(key).lower() for token in secret_tokens)
    )
    account_hash = str(review.get("account_hash", "")).strip()
    hash_value = (
        account_hash.removeprefix("sha256:")
        if account_hash.startswith("sha256:")
        else account_hash
    )
    blockers: list[str] = []
    for field in (
        "reviewer",
        "reviewed_at",
        "broker",
        "account_hash",
        "approval_ticket",
        "permission_conclusion",
    ):
        if not str(review.get(field, "")).strip():
            blockers.append(f"credential_review_field_missing:{field}")
    if len(hash_value) != 64 or any(ch not in "0123456789abcdef" for ch in hash_value):
        blockers.append("credential_review_account_hash_invalid")
    if unknown:
        blockers.append("credential_review_unknown_fields:" + ",".join(unknown))
    if secret_like:
        blockers.append("credential_review_secret_like_fields:" + ",".join(secret_like))
    return {
        "metadata_only": True,
        "status": "quality_checked" if not blockers else "blocked",
        "reviewer": str(review.get("reviewer", "")),
        "reviewed_at": str(review.get("reviewed_at", "")),
        "broker": str(review.get("broker", "")),
        "account_hash": (
            f"sha256:{hash_value}" if not blockers or len(hash_value) == 64 else ""
        ),
        "approval_ticket": str(review.get("approval_ticket", "")),
        "permission_conclusion": str(review.get("permission_conclusion", "")),
        "blockers": blockers,
        "secret_values_recorded": False,
        "secret_read": False,
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "can_unlock_paper": False,
    }


def build_fixture_evidence(
    *,
    work_root: Path,
    generated_at: str,
    code_commit: str,
    code_tree_hash: str,
    config_sha256: str,
    initial_cash: float,
    commission_bps: float,
) -> dict[str, Any]:
    """Run deterministic fixture drills and return bounded quality evidence."""

    timestamps = iter(
        f"2026-07-24T13:{minute:02d}:00Z" for minute in range(60)
    )
    service = PaperOmsReconciliationService(
        FilePaperOmsRepository(
            work_root / "fixture_runtime",
            initial_cash=initial_cash,
        ),
        clock=lambda: next(timestamps),
    )
    begin_results: list[PaperOmsResult] = []
    begin_results.append(
        service.begin_order(
            order_id="filled-order",
            client_order_id="client-filled",
            symbol="QQQ",
            side="buy",
            quantity=10.0,
            risk_approved=True,
            market_open=True,
        )
    )
    service.process_callback(
        _callback("accept-filled", "filled-order", "accepted")
    )
    partial_result = service.process_callback(
        _callback(
            "partial-filled",
            "filled-order",
            "partial",
            fill_id="fill-partial",
            quantity=4.0,
            price=100.0,
            commission_bps=commission_bps,
        )
    )
    filled_result = service.process_callback(
        _callback(
            "finish-filled",
            "filled-order",
            "filled",
            fill_id="fill-final",
            quantity=6.0,
            price=101.0,
            commission_bps=commission_bps,
        )
    )

    begin_results.append(
        service.begin_order(
            order_id="cancel-order",
            client_order_id="client-cancel",
            symbol="GLD",
            side="buy",
            quantity=2.0,
            risk_approved=True,
            market_open=True,
        )
    )
    service.process_callback(_callback("accept-cancel", "cancel-order", "accepted"))
    cancel_pending = service.process_callback(
        _callback("pending-cancel", "cancel-order", "cancel_pending")
    )
    cancel_result = service.process_callback(
        _callback("confirm-cancel", "cancel-order", "cancel")
    )

    begin_results.append(
        service.begin_order(
            order_id="reject-order",
            client_order_id="client-reject",
            symbol="TLT",
            side="buy",
            quantity=1.0,
            risk_approved=True,
            market_open=True,
        )
    )
    service.process_callback(_callback("reject", "reject-order", "rejected"))

    begin_results.append(
        service.begin_order(
            order_id="expired-order",
            client_order_id="client-expired",
            symbol="IEF",
            side="buy",
            quantity=1.0,
            risk_approved=True,
            market_open=True,
        )
    )
    service.process_callback(_callback("accept-expired", "expired-order", "accepted"))
    service.process_callback(_callback("expire", "expired-order", "expired"))

    market_closed_result = service.begin_order(
        order_id="market-closed-order",
        client_order_id="client-market-closed",
        symbol="DIA",
        side="buy",
        quantity=1.0,
        risk_approved=True,
        market_open=False,
    )

    begin_results.append(
        service.begin_order(
            order_id="outage-order",
            client_order_id="client-outage",
            symbol="SPY",
            side="buy",
            quantity=1.0,
            risk_approved=True,
            market_open=True,
        )
    )
    outage_result = service.process_callback(
        _callback("broker-outage", "outage-order", "unknown")
    )

    halted_new_order = service.begin_order(
        order_id="halted-order",
        client_order_id="client-halted",
        symbol="IWM",
        side="buy",
        quantity=1.0,
        risk_approved=True,
        market_open=True,
    )

    # Reconciliation resolves the outage before the separate out-of-order drill.
    outage_state = service.snapshot()
    outage_reconciliation = service.reconcile(
        {
            "snapshot_id": "outage-recovery",
            "cash": outage_state["cash"],
            "positions": outage_state["positions"],
            "orders": {
                order_id: (
                    "rejected"
                    if order_id == "outage-order"
                    else str(order["status"])
                )
                for order_id, order in outage_state["orders"].items()
            },
        }
    )

    begin_results.append(
        service.begin_order(
            order_id="out-of-order",
            client_order_id="client-out-of-order",
            symbol="VTI",
            side="buy",
            quantity=1.0,
            risk_approved=True,
            market_open=True,
        )
    )
    out_of_order_result = service.process_callback(
        _callback(
            "filled-before-accepted",
            "out-of-order",
            "filled",
            fill_id="forbidden-out-of-order-fill",
            quantity=1.0,
            price=200.0,
            commission_bps=commission_bps,
        )
    )

    restarted = PaperOmsReconciliationService(
        FilePaperOmsRepository(
            work_root / "fixture_runtime",
            initial_cash=initial_cash,
        ),
        clock=lambda: next(timestamps),
    )
    duplicate_result = restarted.process_callback(
        _callback(
            "finish-filled",
            "filled-order",
            "filled",
            fill_id="fill-final",
            quantity=6.0,
            price=101.0,
            commission_bps=commission_bps,
        )
    )
    pre_reconciliation = restarted.snapshot()
    snapshot_orders = {
        "filled-order": "filled",
        "cancel-order": "cancel",
        "reject-order": "rejected",
        "expired-order": "expired",
        "outage-order": "rejected",
        "out-of-order": "rejected",
        "market-closed-order": "rejected",
    }
    broken_snapshot = {
        "snapshot_id": "broken-snapshot",
        "cash": float(pre_reconciliation["cash"]) + 1.0,
        "positions": dict(pre_reconciliation["positions"]),
        "orders": snapshot_orders,
    }
    broken_reconciliation = restarted.reconcile(broken_snapshot)
    clean_snapshot = {
        "snapshot_id": "clean-snapshot",
        "cash": float(pre_reconciliation["cash"]),
        "positions": dict(pre_reconciliation["positions"]),
        "orders": snapshot_orders,
    }
    clean_reconciliation = restarted.reconcile(clean_snapshot)
    final_state = restarted.snapshot()

    observed_states = sorted(
        {
            str(state)
            for order in _mapping(final_state.get("orders")).values()
            for state in _string_list(order.get("lifecycle"))
        }
    )
    lifecycle_complete = set(REQUIRED_LIFECYCLE_STATES).issubset(observed_states)
    atomic_rollback = _probe_atomic_rollback(
        work_root / "atomic_rollback",
        initial_cash=initial_cash,
    )
    crash_recovery = _probe_crash_recovery(
        work_root / "crash_recovery",
        initial_cash=initial_cash,
    )
    truncated_log = _probe_truncated_log_fail_closed(
        work_root / "truncated_log",
        initial_cash=initial_cash,
    )
    credential_review = credential_review_metadata(
        {
            "reviewer": "fixture-reviewer",
            "reviewed_at": "2026-07-24T13:00:00Z",
            "broker": "fixture-broker",
            "account_hash": "sha256:" + "a" * 64,
            "approval_ticket": "FIXTURE-NO-PAPER-START",
            "permission_conclusion": "paper_order_permission_not_authorized",
        }
    )
    scenario_results = {
        "idempotency": duplicate_result.duplicate
        and not duplicate_result.ledger_mutated,
        "restart_idempotency": duplicate_result.duplicate,
        "partial_fill": partial_result.lifecycle_state == "partial",
        "filled": filled_result.lifecycle_state == "filled",
        "cancel_pending_fail_closed": cancel_pending.halt_new_orders,
        "cancel_confirmation": cancel_result.lifecycle_state == "cancel",
        "market_closed": market_closed_result.lifecycle_state == "rejected",
        "broker_outage": outage_result.lifecycle_state == "unknown"
        and outage_result.halt_new_orders,
        "halted_new_order_blocked": halted_new_order.status
        == "blocked_fail_closed"
        and "halted-order" not in _mapping(service.snapshot().get("orders"))
        and outage_reconciliation["status"] == "reconciled_clean",
        "out_of_order_callback": out_of_order_result.lifecycle_state == "unknown"
        and "forbidden-out-of-order-fill"
        not in set(_string_list(pre_reconciliation.get("processed_fill_ids"))),
        "reconciliation_break": broken_reconciliation["status"]
        == "breaks_detected_fail_closed"
        and broken_reconciliation["halt_new_orders"] is True,
        "reconciliation_recovery": clean_reconciliation["status"]
        == "reconciled_clean"
        and clean_reconciliation["halt_new_orders"] is False,
        "atomic_uow_rollback": atomic_rollback["passed"],
        "crash_restart_recovery": crash_recovery["passed"],
        "truncated_log_fail_closed": truncated_log["passed"],
        "credential_review_metadata_only": credential_review["status"]
        == "quality_checked",
    }
    engineering_complete = (
        lifecycle_complete
        and all(scenario_results.values())
        and credential_review["secret_read"] is False
    )
    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "asset": "us_equity",
        "status": (
            "complete_quality_checked_paper_blocked"
            if engineering_complete
            else "blocked_engineering_evidence_incomplete"
        ),
        "decision": (
            "fixture_execution_drill_complete_paper_not_started"
            if engineering_complete
            else "fixture_execution_drill_blocked"
        ),
        "code_binding": {
            "code_commit": code_commit,
            "code_tree_hash": code_tree_hash,
            "config_sha256": config_sha256,
        },
        "fixture_run": {
            "run_id": "us-v3-paper-oms-reconciliation-fixture-v1",
            "fake_adapter": True,
            "injected_callbacks_only": True,
            "injected_broker_snapshots_only": True,
            "full_runtime_ledger_persisted_in_git": False,
            "network_access": False,
        },
        "lifecycle": {
            "required_states": list(REQUIRED_LIFECYCLE_STATES),
            "operational_states": list(OPERATIONAL_LIFECYCLE_STATES),
            "observed_states": observed_states,
            "complete": lifecycle_complete,
        },
        "scenario_results": scenario_results,
        "uow": {
            "implementation": "quant_us.live.paper_ledger_uow",
            "atomic_ledgers": [
                "orders",
                "fills",
                "positions",
                "cash",
                "audit",
                "state",
            ],
            "fill_commit_operation_count": filled_result.uow_operation_count,
            "rollback_probe": atomic_rollback,
        },
        "recovery": {
            "restart_duplicate_result": duplicate_result.to_dict(),
            "crash_recovery_probe": crash_recovery,
            "truncated_log_probe": truncated_log,
        },
        "reconciliation": {
            "broken_snapshot": broken_reconciliation,
            "clean_snapshot": clean_reconciliation,
            "final_status": final_state["last_reconciliation"]["status"],
            "ledger_derived_cash": final_state["cash"],
            "ledger_derived_positions": final_state["positions"],
        },
        "credential_review": credential_review,
        "evidence_classification": {
            "classification": "fixture_execution_drill_quality_checked",
            "quality_checked": engineering_complete,
            "real_paper_evidence": False,
            "production_event_ledger": False,
            "can_unlock_paper": False,
            "can_unlock_live": False,
        },
        "blockers": [
            "paper_start_not_authorized",
            "real_paper_evidence_missing",
            "production_event_ledger_missing",
            "manual_paper_start_approval_missing",
        ],
        "guardrails": _guardrails(),
    }
    report["artifact_identity_sha256"] = canonical_payload_hash(
        {
            key: value
            for key, value in report.items()
            if key not in {"generated_at", "artifact_identity_sha256"}
        }
    )
    return report


def _callback(
    event_id: str,
    order_id: str,
    status: str,
    *,
    fill_id: str = "",
    quantity: float = 0.0,
    price: float = 0.0,
    commission_bps: float = 0.0,
) -> dict[str, Any]:
    return {
        "event_id": event_id,
        "order_id": order_id,
        "status": status,
        "fill_id": fill_id,
        "quantity": quantity,
        "price": price,
        "commission_bps": commission_bps,
    }


def _apply_fill(
    *,
    state: dict[str, Any],
    order: dict[str, Any],
    callback: Mapping[str, Any],
    now: str,
    rows: dict[str, list[dict[str, Any]]],
) -> str:
    fill_id = str(callback.get("fill_id", "")).strip()
    quantity = _finite_float(callback.get("quantity"))
    price = _finite_float(callback.get("price"))
    commission_bps = _finite_float(callback.get("commission_bps", 0.0))
    if not fill_id:
        return f"fill_id_missing:{order['order_id']}"
    if quantity <= 0 or price <= 0 or commission_bps < 0:
        return f"fill_values_invalid:{order['order_id']}"
    existing = float(order.get("filled_quantity", 0.0))
    target = float(order["quantity"])
    if existing + quantity > target + 1e-9:
        return f"overfill_blocked:{order['order_id']}"
    desired = str(callback["status"])
    if desired == "filled" and not math.isclose(
        existing + quantity, target, abs_tol=1e-9
    ):
        return f"filled_quantity_incomplete:{order['order_id']}"
    if desired == "partial" and existing + quantity >= target - 1e-9:
        return f"partial_quantity_not_partial:{order['order_id']}"

    notional = quantity * price
    commission = notional * commission_bps / 10_000.0
    side = str(order["side"])
    signed_quantity = quantity if side == "buy" else -quantity
    cash_delta = (
        -(notional + commission)
        if side == "buy"
        else notional - commission
    )
    previous_notional = float(order.get("average_fill_price", 0.0)) * existing
    order["filled_quantity"] = existing + quantity
    order["average_fill_price"] = (
        previous_notional + notional
    ) / order["filled_quantity"]
    positions = {
        str(symbol): float(value)
        for symbol, value in _mapping(state.get("positions")).items()
    }
    symbol = str(order["symbol"])
    positions[symbol] = positions.get(symbol, 0.0) + signed_quantity
    positions = {
        key: value
        for key, value in sorted(positions.items())
        if not math.isclose(value, 0.0, abs_tol=1e-12)
    }
    state["positions"] = positions
    state["cash"] = float(state["cash"]) + cash_delta
    rows["fills"].append(
        {
            "event_id": str(callback["event_id"]),
            "fill_id": fill_id,
            "order_id": str(order["order_id"]),
            "symbol": symbol,
            "side": side,
            "quantity": quantity,
            "price": price,
            "notional": notional,
            "commission": commission,
            "cash_delta": cash_delta,
            "filled_at": now,
            "fixture": True,
        }
    )
    rows["positions"].append(
        {
            "event_id": str(callback["event_id"]),
            "fill_id": fill_id,
            "order_id": str(order["order_id"]),
            "symbol": symbol,
            "quantity": positions.get(symbol, 0.0),
            "updated_at": now,
            "derived_from_fill": True,
        }
    )
    rows["cash"].append(
        {
            "event_id": str(callback["event_id"]),
            "fill_id": fill_id,
            "order_id": str(order["order_id"]),
            "cash_delta": cash_delta,
            "cash_balance": state["cash"],
            "updated_at": now,
            "derived_from_fill": True,
        }
    )
    return ""


def _reconciliation_breaks(
    state: Mapping[str, Any],
    broker_snapshot: Mapping[str, Any],
) -> list[str]:
    breaks: list[str] = []
    try:
        broker_cash = float(broker_snapshot["cash"])
    except (KeyError, TypeError, ValueError):
        return ["broker_snapshot_cash_invalid"]
    if not math.isclose(
        broker_cash,
        float(state["cash"]),
        rel_tol=0.0,
        abs_tol=1e-8,
    ):
        breaks.append("cash_mismatch")
    local_positions = {
        str(key): float(value)
        for key, value in _mapping(state.get("positions")).items()
    }
    broker_positions = {
        str(key): float(value)
        for key, value in _mapping(broker_snapshot.get("positions")).items()
    }
    if local_positions != broker_positions:
        breaks.append("position_mismatch")
    snapshot_orders = _mapping(broker_snapshot.get("orders"))
    if set(snapshot_orders) != set(_mapping(state.get("orders"))):
        breaks.append("order_set_mismatch")
    for order_id, order in _mapping(state.get("orders")).items():
        external = str(snapshot_orders.get(order_id, ""))
        local = str(order.get("status", ""))
        if local in TERMINAL_BEFORE_RECONCILIATION and external != local:
            breaks.append(f"order_status_mismatch:{order_id}")
        elif local == "reconciled" and external not in TERMINAL_BEFORE_RECONCILIATION:
            breaks.append(f"reconciled_order_external_status_invalid:{order_id}")
        elif local in {"accepted", "partial"} and external != local:
            breaks.append(f"open_order_status_mismatch:{order_id}")
        elif local in {"unknown", "cancel_pending"} and external not in (
            TERMINAL_BEFORE_RECONCILIATION | {local}
        ):
            breaks.append(f"unresolved_order_status_invalid:{order_id}")
    return list(dict.fromkeys(breaks))


def _validate_recovered_state(
    *,
    state: Any,
    rows_by_ledger: Mapping[str, Sequence[Mapping[str, Any]]],
    initial_cash: float,
) -> list[str]:
    if not isinstance(state, Mapping):
        return ["oms_state_not_object"]
    blockers: list[str] = []
    if state.get("schema_version") != STATE_SCHEMA_VERSION:
        blockers.append("oms_state_schema_invalid")
    if not math.isclose(
        float(state.get("initial_cash", float("nan"))),
        initial_cash,
        abs_tol=1e-9,
    ):
        blockers.append("oms_state_initial_cash_mismatch")
    if str(state.get("state_hash", "")) != _state_hash(state):
        blockers.append("oms_state_hash_mismatch")
    counts = _mapping(state.get("ledger_counts"))
    for name, rows in rows_by_ledger.items():
        if int(counts.get(name, 0)) != len(rows):
            blockers.append(f"ledger_count_mismatch:{name}")
    recomputed_cash = initial_cash + sum(
        float(row.get("cash_delta", 0.0))
        for row in rows_by_ledger["fills"]
    )
    if not math.isclose(
        recomputed_cash,
        float(state.get("cash", float("nan"))),
        abs_tol=1e-8,
    ):
        blockers.append("ledger_cash_recompute_mismatch")
    positions: dict[str, float] = {}
    for row in rows_by_ledger["fills"]:
        symbol = str(row.get("symbol", ""))
        quantity = float(row.get("quantity", 0.0))
        signed = quantity if str(row.get("side", "")) == "buy" else -quantity
        positions[symbol] = positions.get(symbol, 0.0) + signed
    positions = {
        key: value
        for key, value in sorted(positions.items())
        if not math.isclose(value, 0.0, abs_tol=1e-12)
    }
    state_positions = {
        str(key): float(value)
        for key, value in _mapping(state.get("positions")).items()
    }
    if positions != state_positions:
        blockers.append("ledger_position_recompute_mismatch")
    return blockers


def _read_jsonl_strict(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for index, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except Exception as exc:  # noqa: BLE001
            raise PaperOmsRecoveryError(
                [
                    f"jsonl_unreadable:{path.name}:line:{index}:"
                    f"{type(exc).__name__}"
                ]
            ) from exc
        if not isinstance(value, Mapping):
            raise PaperOmsRecoveryError(
                [f"jsonl_row_not_object:{path.name}:line:{index}"]
            )
        rows.append(dict(value))
    return rows


def _new_state(initial_cash: float) -> dict[str, Any]:
    state: dict[str, Any] = {
        "schema_version": STATE_SCHEMA_VERSION,
        "initial_cash": float(initial_cash),
        "cash": float(initial_cash),
        "positions": {},
        "orders": {},
        "processed_event_ids": [],
        "processed_fill_ids": [],
        "ledger_counts": {name: 0 for name in LEDGER_PATHS},
        "halt_new_orders": False,
        "blockers": [],
        "last_reconciliation": {
            "status": "not_run",
            "breaks": [],
            "reconciled_at": "",
        },
        "updated_at": "",
    }
    state["state_hash"] = _state_hash(state)
    return state


def _state_hash(state: Mapping[str, Any]) -> str:
    return canonical_payload_hash(
        {key: value for key, value in state.items() if key != "state_hash"}
    )


def _transition(order: dict[str, Any], desired: str, now: str) -> None:
    current = str(order.get("status", ""))
    if desired not in ALLOWED_TRANSITIONS.get(current, set()):
        raise ValueError(f"paper_lifecycle_transition_invalid:{current}->{desired}")
    order["status"] = desired
    lifecycle = _string_list(order.get("lifecycle"))
    lifecycle.append(desired)
    order["lifecycle"] = lifecycle
    order["updated_at"] = now


def _force_unknown(order: dict[str, Any], now: str) -> None:
    order["status"] = "unknown"
    lifecycle = _string_list(order.get("lifecycle"))
    lifecycle.append("unknown")
    order["lifecycle"] = lifecycle
    order["updated_at"] = now


def _order_event(
    order: Mapping[str, Any],
    status: str,
    occurred_at: str,
    reason: str,
) -> dict[str, Any]:
    return {
        "order_id": str(order["order_id"]),
        "client_order_id": str(order["client_order_id"]),
        "symbol": str(order["symbol"]),
        "side": str(order["side"]),
        "quantity": float(order["quantity"]),
        "filled_quantity": float(order.get("filled_quantity", 0.0)),
        "status": status,
        "occurred_at": occurred_at,
        "reason": reason,
        "fixture": True,
    }


def _callback_audit(
    callback: Mapping[str, Any],
    occurred_at: str,
    *,
    accepted: bool,
    blocker: str,
) -> dict[str, Any]:
    return {
        "event_id": str(callback.get("event_id", "")),
        "event_type": "broker_callback_fixture",
        "order_id": str(callback.get("order_id", "")),
        "callback_status": str(callback.get("status", "")),
        "occurred_at": occurred_at,
        "accepted": accepted,
        "blocker": blocker,
        "broker_call_used": False,
        "private_endpoint_used": False,
        "order_endpoint_used": False,
    }


def _add_blocker(state: dict[str, Any], blocker: str) -> None:
    state["blockers"] = list(
        dict.fromkeys([*_string_list(state.get("blockers")), blocker])
    )
    state["halt_new_orders"] = True


def _refresh_halt_state(state: dict[str, Any]) -> None:
    unresolved = any(
        str(order.get("status", "")) in {"unknown", "cancel_pending"}
        for order in _mapping(state.get("orders")).values()
    )
    state["halt_new_orders"] = bool(_string_list(state.get("blockers"))) or unresolved


def _probe_atomic_rollback(
    root: Path,
    *,
    initial_cash: float,
) -> dict[str, Any]:
    replace_count = 0

    def fail_second_replace(source: Any, destination: Any) -> None:
        nonlocal replace_count
        replace_count += 1
        if replace_count == 2:
            raise OSError("fixture_interruption")
        os.replace(source, destination)

    repository = FilePaperOmsRepository(
        root,
        initial_cash=initial_cash,
        apply_replace=fail_second_replace,
    )
    service = PaperOmsReconciliationService(
        repository,
        clock=lambda: "2026-07-24T14:00:00Z",
    )
    try:
        service.begin_order(
            order_id="atomic-order",
            client_order_id="atomic-client",
            symbol="QQQ",
            side="buy",
            quantity=1.0,
            risk_approved=True,
            market_open=True,
        )
    except PaperLedgerCommitError as exc:
        files_absent = all(
            not (root / relative).exists()
            for relative in [*LEDGER_PATHS.values(), "oms_state.json"]
        )
        return {
            "passed": exc.rollback_succeeded and files_absent,
            "rollback_succeeded": exc.rollback_succeeded,
            "partial_ledger_files_present": not files_absent,
        }
    return {
        "passed": False,
        "rollback_succeeded": False,
        "partial_ledger_files_present": True,
    }


def _probe_crash_recovery(
    root: Path,
    *,
    initial_cash: float,
) -> dict[str, Any]:
    repository = FilePaperOmsRepository(root, initial_cash=initial_cash)
    transaction = prepare_paper_ledger_transaction(
        ledger_root=root,
        timestamp="2026-07-24T14:01:00Z",
        generated_at="2026-07-24T14:01:00Z",
        jsonl_rows={"audit.jsonl": [{"event_id": "crash-probe"}]},
        json_documents={},
    )
    recovered = FilePaperOmsRepository(root, initial_cash=initial_cash)
    return {
        "passed": recovered.last_recovery.status == "recovered"
        and transaction.transaction_id
        in recovered.last_recovery.recovered_transaction_ids
        and not (root / "audit.jsonl").exists(),
        "status": recovered.last_recovery.status,
        "recovered_transaction_count": len(
            recovered.last_recovery.recovered_transaction_ids
        ),
        "initial_state_preserved": repository.snapshot()
        == recovered.snapshot(),
    }


def _probe_truncated_log_fail_closed(
    root: Path,
    *,
    initial_cash: float,
) -> dict[str, Any]:
    root.mkdir(parents=True, exist_ok=True)
    (root / "orders.jsonl").write_bytes(b'{"order_id":"truncated"')
    try:
        FilePaperOmsRepository(root, initial_cash=initial_cash)
    except PaperOmsRecoveryError as exc:
        return {
            "passed": any(
                blocker.startswith("jsonl_unreadable:orders.jsonl")
                for blocker in exc.blockers
            ),
            "status": "blocked_fail_closed",
            "blockers": exc.blockers,
        }
    return {"passed": False, "status": "unexpectedly_loaded", "blockers": []}


def _guardrails() -> dict[str, bool]:
    return {
        "paper_runner_started": False,
        "paper_queue_write_allowed": False,
        "paper_order_allowed": False,
        "paper_simulation_allowed": False,
        "paper_or_live_unlock_allowed": False,
        "live_allowed": False,
        "live_order_allowed": False,
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "broker_endpoint_used": False,
        "broker_call_used": False,
        "network_used": False,
        "secret_read": False,
        "withdraw_allowed": False,
        "demo_allowed": False,
        "real_order_submitted": False,
    }


def _finite_float(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return float("nan")
    return number if math.isfinite(number) else float("nan")


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _string_list(value: Any) -> list[str]:
    return [str(item) for item in value] if isinstance(value, list) else []
