"""Deterministic, read-only IBKR paper-state reconciliation.

This module deliberately accepts injected snapshots and local ledger records.
It has no broker imports, network surface, order surface, or ledger writer.  A
reconciliation result is an immutable decision record: every mismatch is
fail-closed and only reports what needs operator review.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
from math import isfinite
from re import fullmatch
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = "us_equity_ibkr_paper_reconciliation_v1"
DEFAULT_MAX_SNAPSHOT_AGE_SECONDS = 300.0

_ACTIVE_LOCAL_STATUSES = frozenset(
    {"submitted", "accepted", "partially_filled", "cancel_pending", "unknown"}
)
_TERMINAL_LOCAL_STATUSES = frozenset(
    {"filled", "cancelled", "rejected", "expired"}
)
_NON_SUBMITTED_LOCAL_STATUSES = frozenset({"created", "risk_checked"})
_ACTIVE_BROKER_STATUSES = frozenset(
    {"submitted", "accepted", "partially_filled", "cancel_pending"}
)


@dataclass(frozen=True)
class IBKRAccountSnapshot:
    """Account values captured by an upstream adapter and injected here."""

    account_hash: str = ""
    cash: float = 0.0
    commission_total: float | None = None
    cash_present: bool = True
    commission_present: bool = False

    def __post_init__(self) -> None:
        if self.commission_total is not None:
            object.__setattr__(self, "commission_present", True)


@dataclass(frozen=True)
class IBKRPositionSnapshot:
    symbol: str = ""
    quantity: float = 0.0
    average_cost: float = 0.0
    sequence: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", _normalise_symbol(self.symbol))


@dataclass(frozen=True)
class IBKROpenOrderSnapshot:
    order_id: str = ""
    client_order_id: str = ""
    broker_order_id: str = ""
    symbol: str = ""
    side: str = ""
    quantity: float = 0.0
    status: str = "unknown"
    filled_quantity: float = 0.0
    sequence: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", _normalise_symbol(self.symbol))
        object.__setattr__(self, "side", _normalise_side(self.side))
        object.__setattr__(self, "status", _normalise_status(self.status))


@dataclass(frozen=True)
class IBKRExecutionSnapshot:
    execution_id: str = ""
    order_id: str = ""
    client_order_id: str = ""
    broker_order_id: str = ""
    symbol: str = ""
    side: str = ""
    quantity: float = 0.0
    price: float = 0.0
    commission: float = 0.0
    sequence: int | None = None
    executed_at: datetime | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", _normalise_symbol(self.symbol))
        object.__setattr__(self, "side", _normalise_side(self.side))
        if self.executed_at is not None:
            object.__setattr__(self, "executed_at", _datetime(self.executed_at))


@dataclass(frozen=True)
class IBKRBrokerSnapshot:
    """A complete broker snapshot; it is data, never a broker client."""

    snapshot_id: str = ""
    sequence: int | None = None
    captured_at: datetime | None = None
    account: IBKRAccountSnapshot = field(default_factory=IBKRAccountSnapshot)
    positions: tuple[IBKRPositionSnapshot, ...] = ()
    open_orders: tuple[IBKROpenOrderSnapshot, ...] = ()
    fills: tuple[IBKRExecutionSnapshot, ...] = ()
    complete: bool = True
    reconnect: bool = False
    replay: bool = False
    captured_at_missing: bool = False

    def __post_init__(self) -> None:
        captured_at = _datetime(self.captured_at)
        object.__setattr__(self, "captured_at", captured_at)
        object.__setattr__(self, "captured_at_missing", captured_at is None)
        if not isinstance(self.account, IBKRAccountSnapshot):
            object.__setattr__(self, "account", _normalise_account(self.account))
        object.__setattr__(
            self,
            "positions",
            tuple(
                item if isinstance(item, IBKRPositionSnapshot) else _normalise_position(item)
                for item in _sequence_values(self.positions)
            ),
        )
        object.__setattr__(
            self,
            "open_orders",
            tuple(
                item if isinstance(item, IBKROpenOrderSnapshot) else _normalise_order_snapshot(item)
                for item in _sequence_values(self.open_orders)
            ),
        )
        object.__setattr__(
            self,
            "fills",
            tuple(
                item if isinstance(item, IBKRExecutionSnapshot) else _normalise_execution(item)
                for item in _sequence_values(self.fills)
            ),
        )


@dataclass(frozen=True)
class OMSOrderLifecycleRecord:
    """One local OMS lifecycle state or lifecycle event."""

    order_id: str = ""
    client_order_id: str = ""
    broker_order_id: str = ""
    symbol: str = ""
    side: str = ""
    quantity: float = 0.0
    status: str = "unknown"
    sequence: int | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True)
class FillLedgerRecord:
    """A local fill-ledger execution identity and its accounting values."""

    execution_id: str = ""
    order_id: str = ""
    client_order_id: str = ""
    broker_order_id: str = ""
    symbol: str = ""
    side: str = ""
    quantity: float = 0.0
    price: float = 0.0
    commission: float = 0.0
    sequence: int | None = None
    executed_at: datetime | None = None


@dataclass(frozen=True)
class PositionLedgerRecord:
    symbol: str = ""
    quantity: float = 0.0
    average_cost: float = 0.0
    sequence: int | None = None


@dataclass(frozen=True)
class CashLedgerRecord:
    entry_id: str = ""
    sequence: int | None = None
    cash_balance: float | None = None
    cash_delta: float | None = None
    commission_total: float | None = None
    commission: float | None = None
    starting_cash: float | None = None


@dataclass(frozen=True)
class IBKRPaperReconciliationInput:
    """All state needed by the deterministic reconciliation function."""

    broker_snapshot: Any = field(default_factory=IBKRBrokerSnapshot)
    oms_orders: Sequence[Any] = ()
    fill_ledger: Sequence[Any] = ()
    position_ledger: Sequence[Any] = ()
    cash_ledger: Sequence[Any] = ()
    current_head: str = ""
    run_id: str = ""
    account_hash: str = ""
    last_snapshot_sequence: int | None = None
    expected_snapshot_sequence: int | None = None
    last_execution_sequence: int | None = None
    expected_execution_sequence: int | None = None
    now: datetime | str | None = None
    max_snapshot_age_seconds: float = DEFAULT_MAX_SNAPSHOT_AGE_SECONDS
    restart: bool = False
    replay: bool = False


@dataclass(frozen=True)
class IBKRPaperReconciliationReport:
    """Serializable four-way reconciliation result.

    ``block_new_orders`` is intentionally independent from any caller's OMS
    state.  A consumer must explicitly apply this decision; this module never
    mutates that state itself.
    """

    schema_version: str
    current_head: str
    run_id: str
    account_hash: str
    status: str
    decision: str
    fail_closed: bool
    block_new_orders: bool
    snapshot: dict[str, Any]
    orders: dict[str, Any]
    fills: dict[str, Any]
    positions: dict[str, Any]
    cash: dict[str, Any]
    restart_blockers: tuple[str, ...]
    replay_blockers: tuple[str, ...]
    blockers: tuple[str, ...]
    safety_flags: dict[str, bool]

    @property
    def is_clean(self) -> bool:
        return not self.block_new_orders

    @property
    def halt_new_orders(self) -> bool:
        """Compatibility alias for existing reconciliation consumers."""

        return self.block_new_orders

    @property
    def matched_orders(self) -> list[dict[str, Any]]:
        return list(self.orders["matched"])

    @property
    def unmatched_orders(self) -> dict[str, list[dict[str, Any]]]:
        return {
            "local": list(self.orders["unmatched_local"]),
            "broker": list(self.orders["unmatched_broker"]),
        }

    @property
    def matched_fills(self) -> list[dict[str, Any]]:
        return list(self.fills["matched"])

    @property
    def unmatched_fills(self) -> dict[str, list[dict[str, Any]]]:
        return {
            "local": list(self.fills["unmatched_local"]),
            "broker": list(self.fills["unmatched_broker"]),
        }

    @property
    def duplicate_fills(self) -> list[dict[str, Any]]:
        return list(self.fills["duplicates"])

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "current_head": self.current_head,
            "run_id": self.run_id,
            "account_hash": self.account_hash,
            "status": self.status,
            "decision": self.decision,
            "fail_closed": self.fail_closed,
            "block_new_orders": self.block_new_orders,
            "snapshot": self.snapshot,
            "orders": self.orders,
            "fills": self.fills,
            "positions": self.positions,
            "cash": self.cash,
            "restart_blockers": list(self.restart_blockers),
            "replay_blockers": list(self.replay_blockers),
            "blockers": list(self.blockers),
            "safety_flags": self.safety_flags,
        }


@dataclass(frozen=True)
class _NormalisedCash:
    cash: Decimal | None
    commission: Decimal | None
    records: tuple[CashLedgerRecord, ...]


# Friendly aliases keep the data-only API discoverable without coupling it to
# the IBKR adapter's implementation names.
BrokerAccountSnapshot = IBKRAccountSnapshot
BrokerPositionSnapshot = IBKRPositionSnapshot
BrokerOrderSnapshot = IBKROpenOrderSnapshot
BrokerFillSnapshot = IBKRExecutionSnapshot
BrokerSnapshot = IBKRBrokerSnapshot
OMSOrderRecord = OMSOrderLifecycleRecord
FillLedgerEntry = FillLedgerRecord
PositionLedgerEntry = PositionLedgerRecord
CashLedgerEntry = CashLedgerRecord
ReconciliationInput = IBKRPaperReconciliationInput
ReconciliationReport = IBKRPaperReconciliationReport


def reconcile_ibkr_paper_snapshot(
    broker_snapshot: Any,
    *,
    oms_orders: Sequence[Any] = (),
    fill_ledger: Sequence[Any] = (),
    position_ledger: Sequence[Any] = (),
    cash_ledger: Sequence[Any] = (),
    current_head: str,
    run_id: str,
    account_hash: str,
    last_snapshot_sequence: int | None = None,
    expected_snapshot_sequence: int | None = None,
    last_execution_sequence: int | None = None,
    expected_execution_sequence: int | None = None,
    now: datetime | str | None = None,
    max_snapshot_age_seconds: float = DEFAULT_MAX_SNAPSHOT_AGE_SECONDS,
    restart: bool = False,
    replay: bool = False,
    tolerance: float = 1e-6,
) -> IBKRPaperReconciliationReport:
    """Reconcile injected IBKR state against local four-way ledger state.

    The function is deterministic for the same inputs.  It sorts every
    emitted collection by stable identities, uses ``abs(diff) <= tolerance``
    semantics at the caller's chosen tolerance, and performs no writes or
    broker calls.  Numeric tolerance is supplied in the record as
    ``tolerance`` only through :func:`reconcile_ibkr_paper`; the public
    function uses the safe default of one micro-unit for quantities and money.
    """

    request = IBKRPaperReconciliationInput(
        broker_snapshot=broker_snapshot,
        oms_orders=oms_orders,
        fill_ledger=fill_ledger,
        position_ledger=position_ledger,
        cash_ledger=cash_ledger,
        current_head=current_head,
        run_id=run_id,
        account_hash=account_hash,
        last_snapshot_sequence=last_snapshot_sequence,
        expected_snapshot_sequence=expected_snapshot_sequence,
        last_execution_sequence=last_execution_sequence,
        expected_execution_sequence=expected_execution_sequence,
        now=now,
        max_snapshot_age_seconds=max_snapshot_age_seconds,
        restart=restart,
        replay=replay,
    )
    decimal_tolerance = _decimal(tolerance, default=Decimal("0.000001"))
    if decimal_tolerance is None or decimal_tolerance < 0:
        decimal_tolerance = Decimal("0.000001")
    return _reconcile(request, tolerance=decimal_tolerance)


def reconcile_ibkr_paper(
    request: IBKRPaperReconciliationInput | Any,
    *,
    tolerance: float = 1e-6,
) -> IBKRPaperReconciliationReport:
    """Reconcile a request object, with an explicit numeric tolerance."""

    if not isinstance(request, IBKRPaperReconciliationInput):
        request = IBKRPaperReconciliationInput(
            broker_snapshot=_get(request, "broker_snapshot", "snapshot", default=request),
            oms_orders=_get(request, "oms_orders", "order_lifecycle", default=()),
            fill_ledger=_get(request, "fill_ledger", "fills", default=()),
            position_ledger=_get(request, "position_ledger", "positions", default=()),
            cash_ledger=_get(request, "cash_ledger", "cash", default=()),
            current_head=str(_get(request, "current_head", default="") or ""),
            run_id=str(_get(request, "run_id", default="") or ""),
            account_hash=str(_get(request, "account_hash", default="") or ""),
            last_snapshot_sequence=_get(request, "last_snapshot_sequence", default=None),
            expected_snapshot_sequence=_get(request, "expected_snapshot_sequence", default=None),
            last_execution_sequence=_get(request, "last_execution_sequence", default=None),
            expected_execution_sequence=_get(request, "expected_execution_sequence", default=None),
            now=_get(request, "now", "evaluated_at", default=None),
            max_snapshot_age_seconds=float(
                _get(
                    request,
                    "max_snapshot_age_seconds",
                    default=DEFAULT_MAX_SNAPSHOT_AGE_SECONDS,
                )
            ),
            restart=bool(_get(request, "restart", default=False)),
            replay=bool(_get(request, "replay", default=False)),
        )
    decimal_tolerance = _decimal(tolerance, default=Decimal("0.000001"))
    if decimal_tolerance is None or decimal_tolerance < 0:
        decimal_tolerance = Decimal("0.000001")
    return _reconcile(request, tolerance=decimal_tolerance)


reconcile_four_way = reconcile_ibkr_paper


class IBKRPaperReconciler:
    """Stateless façade for callers that prefer an object API."""

    def __init__(self, *, tolerance: float = 1e-6) -> None:
        value = _decimal(tolerance, default=Decimal("0.000001"))
        self._tolerance = value if value is not None and value >= 0 else Decimal("0.000001")

    def reconcile(
        self,
        request: IBKRPaperReconciliationInput | Any,
    ) -> IBKRPaperReconciliationReport:
        return reconcile_ibkr_paper(request, tolerance=float(self._tolerance))


def _reconcile(
    request: IBKRPaperReconciliationInput,
    *,
    tolerance: Decimal,
) -> IBKRPaperReconciliationReport:
    blockers: set[str] = set()
    restart_blockers: set[str] = set()
    replay_blockers: set[str] = set()
    try:
        snapshot = _normalise_snapshot(request.broker_snapshot)
        local_orders = _latest_orders(request.oms_orders, blockers)
        local_fills, local_duplicates = _unique_fills(
            request.fill_ledger,
            source="local",
            blockers=blockers,
        )
        broker_fills, broker_duplicates = _unique_fills(
            snapshot.fills,
            source="broker",
            blockers=blockers,
        )
        local_positions = _latest_positions(request.position_ledger, blockers)
        local_cash = _normalise_cash(request.cash_ledger, local_fills)
    except (TypeError, ValueError, InvalidOperation):
        # Malformed injected state is itself a fail-closed input blocker.  Do
        # not expose raw values because upstream records may contain account
        # identifiers or other sensitive metadata.
        return _empty_blocked_report(
            request,
            blockers=("invalid_reconciliation_input",),
        )

    if not request.current_head or not fullmatch(r"[0-9a-f]{40}", request.current_head):
        blockers.add("current_head_invalid")
    if not request.run_id:
        blockers.add("run_id_missing")
    if not request.account_hash:
        blockers.add("account_hash_missing")
    if not snapshot.account.account_hash:
        blockers.add("broker_account_hash_missing")
    elif request.account_hash and snapshot.account.account_hash != request.account_hash:
        blockers.add("account_hash_mismatch")
    if not snapshot.account.cash_present:
        blockers.add("broker_cash_missing")

    snapshot_meta = _check_snapshot_freshness_and_sequence(
        snapshot,
        request,
        blockers,
        restart_blockers,
        replay_blockers,
    )
    execution_out_of_order = _check_execution_sequence(
        snapshot.fills,
        request,
        blockers,
        restart_blockers,
        replay_blockers,
    )
    execution_out_of_order = execution_out_of_order or "execution_out_of_order" in blockers

    broker_orders = tuple(
        item if isinstance(item, IBKROpenOrderSnapshot) else _normalise_order_snapshot(item)
        for item in snapshot.open_orders
    )
    orders = _reconcile_orders(
        local_orders,
        broker_orders,
        local_fills,
        tolerance,
        blockers,
    )
    fills = _reconcile_fills(
        local_fills,
        broker_fills,
        tolerance,
        blockers,
        duplicates=local_duplicates + broker_duplicates,
        out_of_order=execution_out_of_order,
    )
    positions = _reconcile_positions(
        local_positions,
        _latest_positions(snapshot.positions, blockers),
        local_fills,
        tolerance,
        blockers,
    )
    cash = _reconcile_cash(
        snapshot.account,
        local_cash,
        local_fills,
        broker_fills,
        tolerance,
        blockers,
    )

    all_blockers = blockers | restart_blockers | replay_blockers
    blocked = bool(all_blockers)
    if blocked:
        status = "blocked_fail_closed"
        decision = "block_new_orders"
    else:
        status = "clean"
        decision = "allow_new_orders"

    return IBKRPaperReconciliationReport(
        schema_version=SCHEMA_VERSION,
        current_head=request.current_head,
        run_id=request.run_id,
        account_hash=request.account_hash,
        status=status,
        decision=decision,
        fail_closed=blocked,
        block_new_orders=blocked,
        snapshot=snapshot_meta,
        orders=orders,
        fills=fills,
        positions=positions,
        cash=cash,
        restart_blockers=tuple(sorted(restart_blockers)),
        replay_blockers=tuple(sorted(replay_blockers)),
        blockers=tuple(sorted(all_blockers)),
        safety_flags=_safety_flags(),
    )


def _empty_blocked_report(
    request: IBKRPaperReconciliationInput,
    *,
    blockers: tuple[str, ...],
) -> IBKRPaperReconciliationReport:
    empty = {
        "matched": [],
        "unmatched_local": [],
        "unmatched_broker": [],
    }
    return IBKRPaperReconciliationReport(
        schema_version=SCHEMA_VERSION,
        current_head=request.current_head,
        run_id=request.run_id,
        account_hash=request.account_hash,
        status="blocked_fail_closed",
        decision="block_new_orders",
        fail_closed=True,
        block_new_orders=True,
        snapshot={
            "snapshot_id": "",
            "sequence": None,
            "captured_at": None,
            "age_seconds": None,
            "max_age_seconds": max(float(request.max_snapshot_age_seconds), 0.0),
            "stale": True,
            "stale_snapshot": True,
            "missing_sequence": True,
            "complete": False,
            "reconnect": False,
            "replay": False,
            "sequence_blockers": ["invalid_reconciliation_input"],
        },
        orders={**empty, "status_drift": [], "duplicates": []},
        fills={
            **empty,
            "duplicates": [],
            "conflicts": [],
            "out_of_order": False,
        },
        positions={"matched": [], "drifts": [], "ledger_consistency": []},
        cash={
            "matched": False,
            "broker_cash": None,
            "local_cash": None,
            "cash_drift": None,
            "broker_commission": None,
            "local_commission": None,
            "commission_drift": None,
        },
        restart_blockers=(),
        replay_blockers=(),
        blockers=blockers,
        safety_flags=_safety_flags(),
    )


def _normalise_snapshot(raw: Any) -> IBKRBrokerSnapshot:
    if isinstance(raw, IBKRBrokerSnapshot):
        return raw
    account_raw = _get(raw, "account", default=None)
    if account_raw is None:
        account_raw = raw
    captured_raw = _get(
        raw,
        "captured_at",
        "as_of",
        "timestamp_utc",
        "timestamp",
        default=None,
    )
    return IBKRBrokerSnapshot(
        snapshot_id=str(_get(raw, "snapshot_id", "id", default="") or ""),
        sequence=_sequence(_get(raw, "sequence", "snapshot_sequence", "seq", default=None)),
        captured_at=_datetime(captured_raw),
        account=_normalise_account(account_raw),
        positions=tuple(
            _normalise_position(item)
            for item in _sequence_values(_get(raw, "positions", default=()))
        ),
        open_orders=tuple(
            _normalise_order_snapshot(item)
            for item in _sequence_values(_get(raw, "open_orders", "orders", default=()))
        ),
        fills=tuple(
            _normalise_execution(item)
            for item in _sequence_values(_get(raw, "fills", "executions", default=()))
        ),
        complete=bool(_get(raw, "complete", "is_complete", default=True)),
        reconnect=bool(_get(raw, "reconnect", "reconnected", default=False)),
        replay=bool(_get(raw, "replay", "is_replay", default=False)),
        captured_at_missing=captured_raw is None,
    )


def _normalise_account(raw: Any) -> IBKRAccountSnapshot:
    if isinstance(raw, IBKRAccountSnapshot):
        return raw
    cash_raw = _get(raw, "cash", "cash_balance", "total_cash", default=None)
    commission_raw = _get(
        raw,
        "commission_total",
        "commission",
        "commissions",
        default=None,
    )
    return IBKRAccountSnapshot(
        account_hash=str(_get(raw, "account_hash", "accountHash", default="") or ""),
        cash=float(_decimal(cash_raw, default=Decimal("0")) or Decimal("0")),
        commission_total=(
            float(_decimal(commission_raw, default=Decimal("0")))
            if commission_raw is not None
            else None
        ),
        cash_present=cash_raw is not None,
        commission_present=commission_raw is not None,
    )


def _normalise_order_snapshot(raw: Any) -> IBKROpenOrderSnapshot:
    return IBKROpenOrderSnapshot(
        order_id=str(_get(raw, "order_id", "id", default="") or ""),
        client_order_id=str(
            _get(raw, "client_order_id", "client_id", "order_ref", default="") or ""
        ),
        broker_order_id=str(
            _get(raw, "broker_order_id", "perm_id", "permId", default="") or ""
        ),
        symbol=_normalise_symbol(_get(raw, "symbol", "ticker", default="")),
        side=_normalise_side(_get(raw, "side", "action", default="")),
        quantity=float(
            _decimal(
                _get(raw, "quantity", "total_quantity", "totalQuantity", default=0),
                default=Decimal("0"),
            )
            or Decimal("0")
        ),
        status=_normalise_status(_get(raw, "status", default="unknown")),
        filled_quantity=float(
            _decimal(
                _get(raw, "filled_quantity", "filled_qty", "filledQuantity", default=0),
                default=Decimal("0"),
            )
            or Decimal("0")
        ),
        sequence=_sequence(_get(raw, "sequence", "order_sequence", default=None)),
    )


def _normalise_execution(raw: Any) -> IBKRExecutionSnapshot:
    executed_raw = _get(
        raw,
        "executed_at",
        "filled_at",
        "time",
        "timestamp_utc",
        default=None,
    )
    return IBKRExecutionSnapshot(
        execution_id=str(
            _get(raw, "execution_id", "exec_id", "execId", "fill_id", "id", default="")
            or ""
        ),
        order_id=str(_get(raw, "order_id", "orderId", default="") or ""),
        client_order_id=str(
            _get(raw, "client_order_id", "client_id", "order_ref", default="") or ""
        ),
        broker_order_id=str(
            _get(raw, "broker_order_id", "perm_id", "permId", default="") or ""
        ),
        symbol=_normalise_symbol(_get(raw, "symbol", "ticker", default="")),
        side=_normalise_side(_get(raw, "side", "action", default="")),
        quantity=float(
            _decimal(
                _get(raw, "quantity", "shares", "qty", default=0),
                default=Decimal("0"),
            )
            or Decimal("0")
        ),
        price=float(
            _decimal(_get(raw, "price", "execution_price", default=0), default=Decimal("0"))
            or Decimal("0")
        ),
        commission=float(
            _decimal(
                _get(raw, "commission", "commission_amount", default=0),
                default=Decimal("0"),
            )
            or Decimal("0")
        ),
        sequence=_sequence(
            _get(raw, "sequence", "execution_sequence", "exec_sequence", default=None)
        ),
        executed_at=_datetime(executed_raw),
    )


def _normalise_orders(raw_items: Sequence[Any]) -> tuple[OMSOrderLifecycleRecord, ...]:
    return tuple(
        OMSOrderLifecycleRecord(
            order_id=str(_get(item, "order_id", "id", default="") or ""),
            client_order_id=str(
                _get(item, "client_order_id", "client_id", "order_ref", default="") or ""
            ),
            broker_order_id=str(
                _get(item, "broker_order_id", "perm_id", "permId", default="") or ""
            ),
            symbol=_normalise_symbol(_get(item, "symbol", "ticker", default="")),
            side=_normalise_side(_get(item, "side", "action", default="")),
            quantity=float(
                _decimal(
                    _get(item, "quantity", "total_quantity", "totalQuantity", default=0),
                    default=Decimal("0"),
                )
                or Decimal("0")
            ),
            status=_normalise_status(_get(item, "status", default="unknown")),
            sequence=_sequence(
                _get(item, "sequence", "event_sequence", "lifecycle_sequence", default=None)
            ),
            updated_at=_datetime(_get(item, "updated_at", "timestamp_utc", default=None)),
        )
        for item in _sequence_values(raw_items)
    )


def _normalise_fills(raw_items: Sequence[Any]) -> tuple[FillLedgerRecord, ...]:
    return tuple(
        FillLedgerRecord(
            execution_id=str(
                _get(item, "execution_id", "exec_id", "execId", "fill_id", "id", default="")
                or ""
            ),
            order_id=str(_get(item, "order_id", "orderId", default="") or ""),
            client_order_id=str(
                _get(item, "client_order_id", "client_id", "order_ref", default="") or ""
            ),
            broker_order_id=str(
                _get(item, "broker_order_id", "perm_id", "permId", default="") or ""
            ),
            symbol=_normalise_symbol(_get(item, "symbol", "ticker", default="")),
            side=_normalise_side(_get(item, "side", "action", default="")),
            quantity=float(
                _decimal(
                    _get(item, "quantity", "shares", "qty", default=0),
                    default=Decimal("0"),
                )
                or Decimal("0")
            ),
            price=float(
                _decimal(
                    _get(item, "price", "execution_price", default=0),
                    default=Decimal("0"),
                )
                or Decimal("0")
            ),
            commission=float(
                _decimal(
                    _get(item, "commission", "commission_amount", default=0),
                    default=Decimal("0"),
                )
                or Decimal("0")
            ),
            sequence=_sequence(
                _get(item, "sequence", "execution_sequence", "exec_sequence", default=None)
            ),
            executed_at=_datetime(
                _get(item, "executed_at", "filled_at", "time", "timestamp_utc", default=None)
            ),
        )
        for item in _sequence_values(raw_items)
    )


def _normalise_position(raw: Any) -> IBKRPositionSnapshot:
    return IBKRPositionSnapshot(
        symbol=_normalise_symbol(_get(raw, "symbol", "ticker", default="")),
        quantity=float(
            _decimal(_get(raw, "quantity", "position", "qty", default=0), default=Decimal("0"))
            or Decimal("0")
        ),
        average_cost=float(
            _decimal(
                _get(raw, "average_cost", "avg_cost", "avgCost", "avg_price", default=0),
                default=Decimal("0"),
            )
            or Decimal("0")
        ),
        sequence=_sequence(_get(raw, "sequence", "position_sequence", default=None)),
    )


def _normalise_cash(
    raw_items: Sequence[Any],
    local_fills: Mapping[str, FillLedgerRecord],
) -> _NormalisedCash:
    records = tuple(
        CashLedgerRecord(
            entry_id=str(_get(item, "entry_id", "id", default="") or ""),
            sequence=_sequence(_get(item, "sequence", "entry_sequence", default=None)),
            cash_balance=_optional_float(
                _get(item, "cash_balance", "cash_after", "balance", "cash", default=None)
            ),
            cash_delta=_optional_float(_get(item, "cash_delta", "delta", default=None)),
            commission_total=_optional_float(
                _get(
                    item,
                    "commission_total",
                    "commission_after",
                    "commission_balance",
                    default=None,
                )
            ),
            commission=_optional_float(
                _get(item, "commission", "commission_amount", default=None)
            ),
            starting_cash=_optional_float(_get(item, "starting_cash", default=None)),
        )
        for item in _sequence_values(raw_items)
    )
    ordered = tuple(sorted(records, key=_cash_sort_key))
    explicit_cash = [record.cash_balance for record in ordered if record.cash_balance is not None]
    if explicit_cash:
        cash = _decimal(explicit_cash[-1], default=Decimal("0"))
    else:
        deltas = [record.cash_delta for record in ordered if record.cash_delta is not None]
        starts = [record.starting_cash for record in ordered if record.starting_cash is not None]
        cash = None
        if deltas and starts:
            cash = (_decimal(starts[-1], default=Decimal("0")) or Decimal("0")) + sum(
                (_decimal(delta, default=Decimal("0")) or Decimal("0")) for delta in deltas
            )
    explicit_commission = [
        record.commission_total for record in ordered if record.commission_total is not None
    ]
    if explicit_commission:
        commission = _decimal(explicit_commission[-1], default=Decimal("0"))
    else:
        commission_values = [record.commission for record in ordered if record.commission is not None]
        if commission_values:
            commission = sum(
                (_decimal(value, default=Decimal("0")) or Decimal("0"))
                for value in commission_values
            )
        else:
            commission = sum(
                (_decimal(fill.commission, default=Decimal("0")) or Decimal("0"))
                for fill in local_fills.values()
            )
    return _NormalisedCash(cash=cash, commission=commission, records=ordered)


def _latest_orders(
    raw_items: Sequence[Any],
    blockers: set[str],
) -> tuple[OMSOrderLifecycleRecord, ...]:
    records = _normalise_orders(raw_items)
    groups: dict[str, list[OMSOrderLifecycleRecord]] = {}
    for record in records:
        key = _order_identity(record)
        if not key:
            blockers.add("local_order_identity_missing")
            continue
        groups.setdefault(key, []).append(record)
    latest: list[OMSOrderLifecycleRecord] = []
    for key, group in sorted(groups.items()):
        ordered = sorted(group, key=_order_sort_key)
        max_sequence = ordered[-1].sequence
        latest_at_sequence = [
            item for item in ordered if item.sequence == max_sequence and max_sequence is not None
        ]
        if len(latest_at_sequence) > 1 and len({_order_signature(item) for item in latest_at_sequence}) > 1:
            blockers.add("oms_order_lifecycle_conflict")
        latest.append(ordered[-1])
    return tuple(sorted(latest, key=_order_sort_key))


def _latest_positions(
    raw_items: Sequence[Any],
    blockers: set[str],
) -> tuple[PositionLedgerRecord | IBKRPositionSnapshot, ...]:
    records: list[PositionLedgerRecord | IBKRPositionSnapshot] = []
    for item in _sequence_values(raw_items):
        if isinstance(item, IBKRPositionSnapshot):
            records.append(item)
        elif isinstance(item, PositionLedgerRecord):
            records.append(item)
        else:
            records.append(
                PositionLedgerRecord(
                    symbol=_normalise_symbol(_get(item, "symbol", "ticker", default="")),
                    quantity=float(
                        _decimal(
                            _get(item, "quantity", "position", "qty", default=0),
                            default=Decimal("0"),
                        )
                        or Decimal("0")
                    ),
                    average_cost=float(
                        _decimal(
                            _get(
                                item,
                                "average_cost",
                                "avg_cost",
                                "avgCost",
                                "avg_price",
                                default=0,
                            ),
                            default=Decimal("0"),
                        )
                        or Decimal("0")
                    ),
                    sequence=_sequence(_get(item, "sequence", "position_sequence", default=None)),
                )
            )
    groups: dict[str, list[PositionLedgerRecord | IBKRPositionSnapshot]] = {}
    for record in records:
        symbol = _normalise_symbol(record.symbol)
        if not symbol:
            blockers.add("position_symbol_missing")
            continue
        groups.setdefault(symbol, []).append(record)
    latest: list[PositionLedgerRecord | IBKRPositionSnapshot] = []
    for symbol, group in sorted(groups.items()):
        ordered = sorted(group, key=_position_sort_key)
        if len(ordered) > 1 and len({_position_signature(item) for item in ordered}) > 1:
            # Multiple position snapshots are only valid when they carry an
            # explicit sequence; otherwise the authoritative row is unclear.
            if any(item.sequence is None for item in ordered):
                blockers.add("position_snapshot_ambiguous")
        latest.append(ordered[-1])
    return tuple(sorted(latest, key=lambda item: _normalise_symbol(item.symbol)))


def _unique_fills(
    raw_items: Sequence[Any],
    *,
    source: str,
    blockers: set[str],
) -> tuple[
    dict[str, FillLedgerRecord | IBKRExecutionSnapshot],
    list[dict[str, Any]],
]:
    records = (
        tuple(raw_items)
        if source == "broker" and all(isinstance(item, IBKRExecutionSnapshot) for item in raw_items)
        else _normalise_fills(raw_items)
    )
    groups: dict[str, list[FillLedgerRecord | IBKRExecutionSnapshot]] = {}
    duplicates: list[dict[str, Any]] = []
    sequence_values = [record.sequence for record in records if record.sequence is not None]
    if any(
        next_value < current
        for current, next_value in zip(sequence_values, sequence_values[1:])
    ):
        blockers.add("execution_out_of_order")
    for record in records:
        execution_id = str(record.execution_id or "")
        if not execution_id:
            blockers.add("execution_id_missing")
            continue
        groups.setdefault(execution_id, []).append(record)
    unique: dict[str, FillLedgerRecord | IBKRExecutionSnapshot] = {}
    for execution_id, group in sorted(groups.items()):
        ordered = sorted(group, key=_fill_sort_key)
        unique[execution_id] = ordered[0]
        if len(group) > 1:
            blockers.add("duplicate_execution")
            conflicting = len({_fill_signature(item) for item in group}) > 1
            if conflicting:
                blockers.add("fill_duplicate_content_conflict")
            duplicates.append(
                {
                    "source": source,
                    "execution_id": execution_id,
                    "count": len(group),
                    "conflicting_content": conflicting,
                    "records": [_fill_view(item) for item in ordered],
                }
            )
    return unique, duplicates


def _reconcile_orders(
    local_orders: Sequence[OMSOrderLifecycleRecord],
    broker_orders: Sequence[IBKROpenOrderSnapshot],
    local_fills: Mapping[str, FillLedgerRecord | IBKRExecutionSnapshot],
    tolerance: Decimal,
    blockers: set[str],
) -> dict[str, Any]:
    local_by_client: dict[str, OMSOrderLifecycleRecord] = {}
    local_by_order: dict[str, OMSOrderLifecycleRecord] = {}
    local_by_broker: dict[str, OMSOrderLifecycleRecord] = {}
    for order in local_orders:
        if order.client_order_id:
            local_by_client[order.client_order_id] = order
        if order.order_id:
            local_by_order[order.order_id] = order
        if order.broker_order_id:
            local_by_broker[order.broker_order_id] = order

    broker_groups: dict[str, list[IBKROpenOrderSnapshot]] = {}
    for order in broker_orders:
        key = _broker_order_identity(order)
        if not key:
            blockers.add("broker_order_identity_missing")
            continue
        broker_groups.setdefault(key, []).append(order)
    canonical_broker: list[IBKROpenOrderSnapshot] = []
    for key, group in sorted(broker_groups.items()):
        canonical_broker.append(sorted(group, key=_broker_order_sort_key)[0])
        if len(group) > 1:
            blockers.add("duplicate_broker_order")

    matched: list[dict[str, Any]] = []
    unmatched_local: list[dict[str, Any]] = []
    unmatched_broker: list[dict[str, Any]] = []
    status_drift: list[dict[str, Any]] = []
    matched_local_ids: set[str] = set()

    for broker_order in sorted(canonical_broker, key=_broker_order_sort_key):
        local = _find_local_order(broker_order, local_by_client, local_by_broker, local_by_order)
        if local is None:
            unmatched_broker.append(_broker_order_view(broker_order))
            blockers.add("order_unmatched_broker")
            continue
        local_key = _order_identity(local)
        matched_local_ids.add(local_key)
        diffs = _order_diffs(local, broker_order, local_fills, tolerance)
        if diffs:
            status_drift.append({**_order_match_view(local, broker_order), "drifts": diffs})
            for drift in diffs:
                blockers.add(f"order_{drift}")
        matched.append(
            {
                **_order_match_view(local, broker_order),
                "match_status": "matched" if not diffs else "drifted",
            }
        )

    for local in sorted(local_orders, key=_order_sort_key):
        local_key = _order_identity(local)
        fill_quantity = _filled_quantity_for_order(local, local_fills)
        if fill_quantity - _d(local.quantity) > tolerance:
            blockers.add("local_fill_overfill")
        if local.status == "filled" and abs(fill_quantity - _d(local.quantity)) > tolerance:
            blockers.add("local_filled_quantity_mismatch")
        if local.status == "rejected" and fill_quantity > tolerance:
            blockers.add("rejected_order_has_fill")
        if local.status == "unknown":
            blockers.add("local_order_status_unknown")
        if local_key in matched_local_ids:
            continue
        if _local_requires_broker(local):
            unmatched_local.append(_local_order_view(local))
            blockers.add("order_unmatched_local")
        elif local.status in _TERMINAL_LOCAL_STATUSES:
            matched.append(
                {
                    **_local_order_view(local),
                    "broker_open_order_present": False,
                    "match_status": "terminal_not_in_open_snapshot",
                }
            )
        elif local.status in _NON_SUBMITTED_LOCAL_STATUSES:
            matched.append(
                {
                    **_local_order_view(local),
                    "broker_open_order_present": False,
                    "match_status": "not_submitted_local_only",
                }
            )

    return {
        "matched": sorted(matched, key=lambda item: str(item.get("order_id", ""))),
        "unmatched_local": sorted(unmatched_local, key=lambda item: str(item.get("order_id", ""))),
        "unmatched_broker": sorted(
            unmatched_broker,
            key=lambda item: str(item.get("order_id", item.get("client_order_id", ""))),
        ),
        "status_drift": sorted(status_drift, key=lambda item: str(item.get("order_id", ""))),
        "duplicates": [],
    }


def _reconcile_fills(
    local_fills: Mapping[str, FillLedgerRecord | IBKRExecutionSnapshot],
    broker_fills: Mapping[str, FillLedgerRecord | IBKRExecutionSnapshot],
    tolerance: Decimal,
    blockers: set[str],
    *,
    duplicates: Sequence[dict[str, Any]] = (),
    out_of_order: bool = False,
) -> dict[str, Any]:
    matched: list[dict[str, Any]] = []
    unmatched_local: list[dict[str, Any]] = []
    unmatched_broker: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    for execution_id in sorted(set(local_fills) | set(broker_fills)):
        local = local_fills.get(execution_id)
        broker = broker_fills.get(execution_id)
        if local is None:
            unmatched_broker.append(_fill_view(broker))
            blockers.add("fill_unmatched_broker")
        elif broker is None:
            unmatched_local.append(_fill_view(local))
            blockers.add("fill_unmatched_local")
        else:
            diffs = _fill_diffs(local, broker, tolerance)
            if diffs:
                conflicts.append(
                    {
                        "execution_id": execution_id,
                        "local": _fill_view(local),
                        "broker": _fill_view(broker),
                        "drifts": diffs,
                    }
                )
                blockers.add("fill_content_drift")
            matched.append(
                {
                    "execution_id": execution_id,
                    "match_status": "matched" if not diffs else "drifted",
                    "local": _fill_view(local),
                    "broker": _fill_view(broker),
                }
            )
    return {
        "matched": matched,
        "unmatched_local": unmatched_local,
        "unmatched_broker": unmatched_broker,
        "duplicates": sorted(
            duplicates,
            key=lambda item: (str(item.get("source", "")), str(item.get("execution_id", ""))),
        ),
        "conflicts": conflicts,
        "out_of_order": out_of_order,
    }


def _reconcile_positions(
    local_positions: Sequence[PositionLedgerRecord | IBKRPositionSnapshot],
    broker_positions: Sequence[PositionLedgerRecord | IBKRPositionSnapshot],
    local_fills: Mapping[str, FillLedgerRecord | IBKRExecutionSnapshot],
    tolerance: Decimal,
    blockers: set[str],
) -> dict[str, Any]:
    local_map = {_normalise_symbol(item.symbol): item for item in local_positions}
    broker_map = {_normalise_symbol(item.symbol): item for item in broker_positions}
    matched: list[dict[str, Any]] = []
    drifts: list[dict[str, Any]] = []
    for symbol in sorted(set(local_map) | set(broker_map)):
        local = local_map.get(symbol)
        broker = broker_map.get(symbol)
        local_qty = _d(local.quantity if local is not None else 0)
        broker_qty = _d(broker.quantity if broker is not None else 0)
        local_avg = _d(local.average_cost if local is not None else 0)
        broker_avg = _d(broker.average_cost if broker is not None else 0)
        quantity_diff = broker_qty - local_qty
        average_cost_diff = broker_avg - local_avg
        quantity_drift = abs(quantity_diff) > tolerance
        average_cost_drift = (
            abs(average_cost_diff) > tolerance
            and (abs(local_qty) > tolerance or abs(broker_qty) > tolerance)
        )
        view = {
            "symbol": symbol,
            "local_quantity": _number(local_qty),
            "broker_quantity": _number(broker_qty),
            "quantity_diff": _number(quantity_diff),
            "local_average_cost": _number(local_avg),
            "broker_average_cost": _number(broker_avg),
            "average_cost_diff": _number(average_cost_diff),
        }
        if quantity_drift or average_cost_drift:
            drifts.append(
                {
                    **view,
                    "quantity_drift": quantity_drift,
                    "average_cost_drift": average_cost_drift,
                }
            )
            if quantity_drift:
                blockers.add("position_quantity_drift")
            if average_cost_drift:
                blockers.add("position_average_cost_drift")
        else:
            matched.append(view)

    ledger_consistency: list[dict[str, Any]] = []
    derived = _derive_positions(local_fills)
    for symbol in sorted(set(derived) | set(local_map)):
        derived_qty, derived_avg = derived.get(symbol, (Decimal("0"), Decimal("0")))
        ledger_position = local_map.get(symbol)
        ledger_qty = _d(ledger_position.quantity if ledger_position is not None else 0)
        ledger_avg = _d(ledger_position.average_cost if ledger_position is not None else 0)
        quantity_diff = ledger_qty - derived_qty
        average_cost_diff = ledger_avg - derived_avg
        quantity_drift = abs(quantity_diff) > tolerance
        average_cost_drift = (
            abs(average_cost_diff) > tolerance
            and (abs(ledger_qty) > tolerance or abs(derived_qty) > tolerance)
        )
        if quantity_drift or average_cost_drift:
            ledger_consistency.append(
                {
                    "symbol": symbol,
                    "ledger_quantity": _number(ledger_qty),
                    "fill_derived_quantity": _number(derived_qty),
                    "quantity_diff": _number(quantity_diff),
                    "ledger_average_cost": _number(ledger_avg),
                    "fill_derived_average_cost": _number(derived_avg),
                    "average_cost_diff": _number(average_cost_diff),
                    "quantity_drift": quantity_drift,
                    "average_cost_drift": average_cost_drift,
                }
            )
            blockers.add("position_ledger_fill_drift")
    return {
        "matched": matched,
        "drifts": drifts,
        "ledger_consistency": ledger_consistency,
    }


def _reconcile_cash(
    account: IBKRAccountSnapshot,
    local_cash: _NormalisedCash,
    local_fills: Mapping[str, FillLedgerRecord | IBKRExecutionSnapshot],
    broker_fills: Mapping[str, FillLedgerRecord | IBKRExecutionSnapshot],
    tolerance: Decimal,
    blockers: set[str],
) -> dict[str, Any]:
    broker_cash = _d(account.cash) if account.cash_present else None
    expected_cash = local_cash.cash
    cash_drift = broker_cash - expected_cash if broker_cash is not None and expected_cash is not None else None
    if expected_cash is None:
        blockers.add("cash_ledger_missing")
    if cash_drift is not None and abs(cash_drift) > tolerance:
        blockers.add("cash_drift")

    if account.commission_present and account.commission_total is not None:
        broker_commission = _d(account.commission_total)
    else:
        broker_commission = sum(
            (_d(item.commission) for item in broker_fills.values()),
            Decimal("0"),
        )
        if (
            not broker_fills
            and local_cash.commission is not None
            and abs(local_cash.commission) > tolerance
        ):
            blockers.add("broker_commission_missing")
    local_commission = local_cash.commission
    if local_commission is None:
        local_commission = sum(
            (_d(item.commission) for item in local_fills.values()),
            Decimal("0"),
        )
    commission_drift = broker_commission - local_commission
    if abs(commission_drift) > tolerance:
        blockers.add("commission_drift")

    cash_matched = cash_drift is not None and abs(cash_drift) <= tolerance
    commission_matched = abs(commission_drift) <= tolerance
    return {
        "matched": cash_matched and commission_matched,
        "broker_cash": _number(broker_cash),
        "local_cash": _number(expected_cash),
        "cash_drift": _number(cash_drift),
        "broker_commission": _number(broker_commission),
        "local_commission": _number(local_commission),
        "commission_drift": _number(commission_drift),
        "cash_matched": cash_matched,
        "commission_matched": commission_matched,
    }


def _check_snapshot_freshness_and_sequence(
    snapshot: IBKRBrokerSnapshot,
    request: IBKRPaperReconciliationInput,
    blockers: set[str],
    restart_blockers: set[str],
    replay_blockers: set[str],
) -> dict[str, Any]:
    sequence_blockers: set[str] = set()
    max_age_seconds = max(float(request.max_snapshot_age_seconds), 0.0)
    if snapshot.captured_at_missing or snapshot.captured_at is None:
        sequence_blockers.add("snapshot_timestamp_missing")
        blockers.add("snapshot_timestamp_missing")
        age_seconds: float | None = None
    else:
        reference = _datetime(request.now) or snapshot.captured_at
        age_seconds = (reference - snapshot.captured_at).total_seconds()
        if age_seconds < 0:
            sequence_blockers.add("snapshot_timestamp_in_future")
            blockers.add("snapshot_timestamp_in_future")
        elif age_seconds > max_age_seconds:
            sequence_blockers.add("stale_snapshot")
            blockers.add("stale_snapshot")
    if not snapshot.complete:
        sequence_blockers.add("snapshot_incomplete")
        blockers.add("snapshot_incomplete")
    if snapshot.sequence is None:
        sequence_blockers.add("snapshot_sequence_missing")
        blockers.add("snapshot_sequence_missing")
    else:
        if request.expected_snapshot_sequence is not None and snapshot.sequence != request.expected_snapshot_sequence:
            reason = (
                "snapshot_sequence_missing"
                if snapshot.sequence < request.expected_snapshot_sequence
                else "snapshot_sequence_unexpected"
            )
            sequence_blockers.add(reason)
            blockers.add(reason)
        if request.last_snapshot_sequence is not None:
            if snapshot.sequence == request.last_snapshot_sequence:
                reason = "snapshot_replayed"
                sequence_blockers.add(reason)
                replay_blockers.add(reason)
                blockers.add(reason)
            elif snapshot.sequence < request.last_snapshot_sequence:
                reason = "snapshot_sequence_regressed"
                sequence_blockers.add(reason)
                replay_blockers.add(reason)
                blockers.add(reason)
            elif snapshot.sequence > request.last_snapshot_sequence + 1:
                reason = "snapshot_sequence_gap"
                sequence_blockers.add(reason)
                blockers.add(reason)
    if request.restart and request.last_snapshot_sequence is None:
        restart_blockers.add("restart_sequence_baseline_missing")
        blockers.add("restart_sequence_baseline_missing")
    if request.replay and request.last_snapshot_sequence is None:
        replay_blockers.add("replay_sequence_baseline_missing")
        blockers.add("replay_sequence_baseline_missing")
    if snapshot.reconnect and request.last_snapshot_sequence is not None and snapshot.sequence is not None:
        if snapshot.sequence <= request.last_snapshot_sequence:
            reason = "reconnect_replayed_snapshot"
            replay_blockers.add(reason)
            blockers.add(reason)
    if snapshot.replay:
        reason = "broker_replay_snapshot"
        replay_blockers.add(reason)
        blockers.add(reason)
    stale = bool(
        "stale_snapshot" in sequence_blockers
        or "snapshot_timestamp_missing" in sequence_blockers
        or "snapshot_incomplete" in sequence_blockers
    )
    return {
        "snapshot_id": snapshot.snapshot_id,
        "sequence": snapshot.sequence,
        "captured_at": _iso(snapshot.captured_at),
        "age_seconds": age_seconds,
        "max_age_seconds": max_age_seconds,
        "stale": stale,
        "stale_snapshot": stale,
        "missing_sequence": "snapshot_sequence_missing" in sequence_blockers,
        "complete": snapshot.complete,
        "reconnect": snapshot.reconnect,
        "replay": snapshot.replay,
        "sequence_blockers": sorted(sequence_blockers),
    }


def _check_execution_sequence(
    broker_fills: Sequence[IBKRExecutionSnapshot],
    request: IBKRPaperReconciliationInput,
    blockers: set[str],
    restart_blockers: set[str],
    replay_blockers: set[str],
) -> bool:
    sequences = [item.sequence for item in broker_fills]
    present = [value for value in sequences if value is not None]
    if not present:
        return False
    out_of_order = any(next_value < current for current, next_value in zip(present, present[1:]))
    if out_of_order:
        blockers.add("execution_out_of_order")
    unique = sorted(set(present))
    if len(unique) > 1 and unique[-1] - unique[0] + 1 != len(unique):
        blockers.add("execution_sequence_gap")
    if request.expected_execution_sequence is not None and min(unique) != request.expected_execution_sequence:
        reason = (
            "execution_sequence_missing"
            if min(unique) < request.expected_execution_sequence
            else "execution_sequence_unexpected"
        )
        blockers.add(reason)
    if request.last_execution_sequence is not None and any(
        value <= request.last_execution_sequence for value in present
    ):
        reason = "execution_replayed"
        replay_blockers.add(reason)
        blockers.add(reason)
    if request.restart and request.last_execution_sequence is None:
        restart_blockers.add("restart_execution_baseline_missing")
        blockers.add("restart_execution_baseline_missing")
    return out_of_order


def _order_diffs(
    local: OMSOrderLifecycleRecord,
    broker: IBKROpenOrderSnapshot,
    local_fills: Mapping[str, FillLedgerRecord | IBKRExecutionSnapshot],
    tolerance: Decimal,
) -> list[str]:
    diffs: list[str] = []
    if local.symbol and broker.symbol and local.symbol != broker.symbol:
        diffs.append("symbol_drift")
    if local.side and broker.side and local.side != broker.side:
        diffs.append("side_drift")
    if abs(_d(local.quantity) - _d(broker.quantity)) > tolerance:
        diffs.append("quantity_drift")
    if not _order_status_compatible(local.status, broker.status):
        diffs.append("status_drift")
    local_filled = _filled_quantity_for_order(local, local_fills)
    if abs(local_filled - _d(broker.filled_quantity)) > tolerance:
        diffs.append("filled_quantity_drift")
    return sorted(set(diffs))


def _order_status_compatible(local_status: str, broker_status: str) -> bool:
    if local_status == broker_status:
        return True
    if local_status in {"submitted", "accepted"} and broker_status in {"submitted", "accepted"}:
        return True
    if local_status == "cancel_pending" and broker_status in _ACTIVE_BROKER_STATUSES:
        return True
    return False


def _fill_diffs(
    local: FillLedgerRecord | IBKRExecutionSnapshot,
    broker: FillLedgerRecord | IBKRExecutionSnapshot,
    tolerance: Decimal,
) -> list[str]:
    diffs: list[str] = []
    if local.order_id and broker.order_id and local.order_id != broker.order_id:
        diffs.append("order_id_drift")
    if local.client_order_id and broker.client_order_id and local.client_order_id != broker.client_order_id:
        diffs.append("client_order_id_drift")
    if local.symbol and broker.symbol and local.symbol != broker.symbol:
        diffs.append("symbol_drift")
    if local.side and broker.side and local.side != broker.side:
        diffs.append("side_drift")
    for field_name in ("quantity", "price", "commission"):
        if abs(_d(getattr(local, field_name)) - _d(getattr(broker, field_name))) > tolerance:
            diffs.append(f"{field_name}_drift")
    return sorted(set(diffs))


def _filled_quantity_for_order(
    order: OMSOrderLifecycleRecord,
    fills: Mapping[str, FillLedgerRecord | IBKRExecutionSnapshot],
) -> Decimal:
    values = [
        _d(fill.quantity)
        for fill in fills.values()
        if (
            (order.order_id and fill.order_id == order.order_id)
            or (order.client_order_id and fill.client_order_id == order.client_order_id)
            or (order.broker_order_id and fill.broker_order_id == order.broker_order_id)
        )
    ]
    return sum(values, Decimal("0"))


def _derive_positions(
    fills: Mapping[str, FillLedgerRecord | IBKRExecutionSnapshot],
) -> dict[str, tuple[Decimal, Decimal]]:
    state: dict[str, tuple[Decimal, Decimal]] = {}
    ordered = sorted(fills.values(), key=_fill_sort_key)
    for fill in ordered:
        symbol = _normalise_symbol(fill.symbol)
        if not symbol:
            continue
        quantity = _d(fill.quantity)
        if quantity < 0:
            continue
        signed = quantity if fill.side == "buy" else -quantity
        current_quantity, current_average = state.get(symbol, (Decimal("0"), Decimal("0")))
        price = _d(fill.price)
        if current_quantity == 0:
            state[symbol] = (signed, price if signed != 0 else Decimal("0"))
            continue
        if (current_quantity > 0 and signed > 0) or (current_quantity < 0 and signed < 0):
            total = abs(current_quantity) + abs(signed)
            average = (
                abs(current_quantity) * current_average + abs(signed) * price
            ) / total
            state[symbol] = (current_quantity + signed, average)
        elif abs(signed) < abs(current_quantity):
            state[symbol] = (current_quantity + signed, current_average)
        elif abs(signed) == abs(current_quantity):
            state[symbol] = (Decimal("0"), Decimal("0"))
        else:
            state[symbol] = (current_quantity + signed, price)
    return state


def _find_local_order(
    broker: IBKROpenOrderSnapshot,
    by_client: Mapping[str, OMSOrderLifecycleRecord],
    by_broker: Mapping[str, OMSOrderLifecycleRecord],
    by_order: Mapping[str, OMSOrderLifecycleRecord],
) -> OMSOrderLifecycleRecord | None:
    for key, mapping in (
        (broker.client_order_id, by_client),
        (broker.broker_order_id, by_broker),
        (broker.order_id, by_order),
    ):
        if key and key in mapping:
            return mapping[key]
    return None


def _local_requires_broker(order: OMSOrderLifecycleRecord) -> bool:
    return order.status in _ACTIVE_LOCAL_STATUSES


def _order_identity(order: OMSOrderLifecycleRecord) -> str:
    return order.client_order_id or order.order_id or order.broker_order_id


def _broker_order_identity(order: IBKROpenOrderSnapshot) -> str:
    return order.client_order_id or order.broker_order_id or order.order_id


def _order_signature(order: OMSOrderLifecycleRecord) -> tuple[Any, ...]:
    return (
        order.order_id,
        order.client_order_id,
        order.broker_order_id,
        order.symbol,
        order.side,
        _number(_d(order.quantity)),
        order.status,
    )


def _position_signature(item: PositionLedgerRecord | IBKRPositionSnapshot) -> tuple[Any, ...]:
    return (_number(_d(item.quantity)), _number(_d(item.average_cost)), item.sequence)


def _fill_signature(item: FillLedgerRecord | IBKRExecutionSnapshot) -> tuple[Any, ...]:
    return (
        item.order_id,
        item.client_order_id,
        item.symbol,
        item.side,
        _number(_d(item.quantity)),
        _number(_d(item.price)),
        _number(_d(item.commission)),
        item.sequence,
    )


def _order_sort_key(order: OMSOrderLifecycleRecord) -> tuple[Any, ...]:
    return (
        order.sequence is None,
        order.sequence if order.sequence is not None else -1,
        _iso(order.updated_at) or "",
        _order_identity(order),
        order.status,
    )


def _broker_order_sort_key(order: IBKROpenOrderSnapshot) -> tuple[Any, ...]:
    return (
        _broker_order_identity(order),
        order.sequence is None,
        order.sequence if order.sequence is not None else -1,
        order.status,
    )


def _fill_sort_key(item: FillLedgerRecord | IBKRExecutionSnapshot) -> tuple[Any, ...]:
    return (
        item.sequence is None,
        item.sequence if item.sequence is not None else -1,
        _iso(item.executed_at) or "",
        item.execution_id,
        item.order_id,
    )


def _position_sort_key(item: PositionLedgerRecord | IBKRPositionSnapshot) -> tuple[Any, ...]:
    return (
        item.sequence is None,
        item.sequence if item.sequence is not None else -1,
        _number(_d(item.quantity)),
        _number(_d(item.average_cost)),
    )


def _cash_sort_key(item: CashLedgerRecord) -> tuple[Any, ...]:
    return (
        item.sequence is None,
        item.sequence if item.sequence is not None else -1,
        item.entry_id,
    )


def _order_match_view(
    local: OMSOrderLifecycleRecord,
    broker: IBKROpenOrderSnapshot,
) -> dict[str, Any]:
    return {
        "order_id": local.order_id or broker.order_id,
        "client_order_id": local.client_order_id or broker.client_order_id,
        "broker_order_id": local.broker_order_id or broker.broker_order_id,
        "symbol": local.symbol or broker.symbol,
        "local_status": local.status,
        "broker_status": broker.status,
        "local_quantity": _number(_d(local.quantity)),
        "broker_quantity": _number(_d(broker.quantity)),
    }


def _local_order_view(order: OMSOrderLifecycleRecord) -> dict[str, Any]:
    return {
        "order_id": order.order_id,
        "client_order_id": order.client_order_id,
        "broker_order_id": order.broker_order_id,
        "symbol": order.symbol,
        "side": order.side,
        "quantity": _number(_d(order.quantity)),
        "status": order.status,
    }


def _broker_order_view(order: IBKROpenOrderSnapshot) -> dict[str, Any]:
    return {
        "order_id": order.order_id,
        "client_order_id": order.client_order_id,
        "broker_order_id": order.broker_order_id,
        "symbol": order.symbol,
        "side": order.side,
        "quantity": _number(_d(order.quantity)),
        "status": order.status,
        "filled_quantity": _number(_d(order.filled_quantity)),
    }


def _fill_view(item: FillLedgerRecord | IBKRExecutionSnapshot | None) -> dict[str, Any]:
    if item is None:
        return {}
    return {
        "execution_id": item.execution_id,
        "order_id": item.order_id,
        "client_order_id": item.client_order_id,
        "broker_order_id": item.broker_order_id,
        "symbol": item.symbol,
        "side": item.side,
        "quantity": _number(_d(item.quantity)),
        "price": _number(_d(item.price)),
        "commission": _number(_d(item.commission)),
        "sequence": item.sequence,
        "executed_at": _iso(item.executed_at),
    }


def _get(obj: Any, *names: str, default: Any = None) -> Any:
    if isinstance(obj, Mapping):
        for name in names:
            if name in obj:
                return obj[name]
        return default
    for name in names:
        if hasattr(obj, name):
            return getattr(obj, name)
    return default


def _sequence_values(value: Any) -> tuple[Any, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes, bytearray)):
        return (value,)
    try:
        return tuple(value)
    except TypeError:
        return (value,)


def _normalise_symbol(value: Any) -> str:
    return _text(value).upper()


def _normalise_side(value: Any) -> str:
    text = _text(value).lower()
    return {"bot": "buy", "bought": "buy", "sld": "sell", "sold": "sell"}.get(text, text)


def _normalise_status(value: Any) -> str:
    text = _text(value).lower().replace(" ", "_").replace("-", "_")
    aliases = {
        "partial": "partially_filled",
        "partiallyfilled": "partially_filled",
        "cancel": "cancelled",
        "canceled": "cancelled",
        "pending_cancel": "cancel_pending",
        "pendingcancel": "cancel_pending",
        "submitted": "submitted",
        "presubmitted": "submitted",
        "filled": "filled",
        "rejected": "rejected",
        "reject": "rejected",
    }
    return aliases.get(text, text or "unknown")


def _text(value: Any) -> str:
    if isinstance(value, Enum):
        value = value.value
    return str(value or "").strip()


def _sequence(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError, InvalidOperation) as exc:
        raise ValueError("invalid_sequence") from exc


def _datetime(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _decimal(value: Any, *, default: Decimal | None = None) -> Decimal | None:
    if isinstance(value, Decimal):
        result = value
    elif value is None or value == "":
        return default
    else:
        try:
            result = Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError) as exc:
            raise ValueError("invalid_numeric") from exc
    if not result.is_finite():
        raise ValueError("non_finite_numeric")
    return result


def _d(value: Any) -> Decimal:
    return _decimal(value, default=Decimal("0")) or Decimal("0")


def _optional_float(value: Any) -> float | None:
    decimal = _decimal(value, default=None)
    return float(decimal) if decimal is not None else None


def _number(value: Decimal | None) -> float | None:
    if value is None:
        return None
    result = float(value)
    if not isfinite(result):
        raise ValueError("non_finite_numeric")
    return 0.0 if result == 0.0 else result


def _safety_flags() -> dict[str, bool]:
    return {
        "broker_called": False,
        "broker_endpoint_used": False,
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "network_used": False,
        "order_submitted": False,
        "order_cancelled": False,
        "ledger_mutated": False,
        "paper_order_allowed": False,
        "live_order_allowed": False,
        "secret_read": False,
    }
