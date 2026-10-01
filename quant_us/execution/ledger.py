from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from enum import Enum
import json
from pathlib import Path
import hashlib
import threading
from typing import Any

from quant_us.core.enums import OrderSide
from quant_us.core.types import Fill, Position

try:
    import fcntl as _fcntl
except ImportError:  # pragma: no cover - exercised on non-POSIX platforms.
    _fcntl = None


class _RootLockState:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.file_lock_depth = 0
        self.file_lock_handle: Any | None = None


_LOCK_STATES_LOCK = threading.Lock()
_LOCK_STATES_BY_ROOT: dict[Path, _RootLockState] = {}


def _root_lock_state(root: Path) -> _RootLockState:
    resolved_root = root.resolve()
    with _LOCK_STATES_LOCK:
        state = _LOCK_STATES_BY_ROOT.get(resolved_root)
        if state is None:
            state = _RootLockState()
            _LOCK_STATES_BY_ROOT[resolved_root] = state
        return state


class _FillIdempotencyFileLock:
    def __init__(self, state: _RootLockState, path: Path) -> None:
        self._state = state
        self._path = path

    def __enter__(self) -> _FillIdempotencyFileLock:
        self._state.lock.acquire()
        try:
            if self._state.file_lock_depth == 0 and _fcntl is not None:
                handle = self._path.open("a+", encoding="utf-8")
                try:
                    _fcntl.flock(handle.fileno(), _fcntl.LOCK_EX)
                except BaseException:
                    handle.close()
                    raise
                self._state.file_lock_handle = handle
            self._state.file_lock_depth += 1
            return self
        except BaseException:
            self._state.lock.release()
            raise

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        try:
            self._state.file_lock_depth -= 1
            if self._state.file_lock_depth == 0:
                handle = self._state.file_lock_handle
                self._state.file_lock_handle = None
                if handle is not None:
                    try:
                        _fcntl.flock(handle.fileno(), _fcntl.LOCK_UN)
                    finally:
                        handle.close()
        finally:
            self._state.lock.release()


class JsonlLedgerStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock_state = _root_lock_state(self.root)
        self._lock = self._lock_state.lock
        self._fill_idempotency_lock_path = self.root / ".fill_idempotency.lock"

    def fill_idempotency_lock(self) -> Any:
        return _FillIdempotencyFileLock(self._lock_state, self._fill_idempotency_lock_path)

    def append_order(self, order: Any) -> None:
        self._append("orders.jsonl", order)

    def append_fill(self, fill: Any) -> None:
        self._append("fills.jsonl", fill)

    def append_fill_idempotent(self, fill: Any) -> Any:
        from quant_us.execution.fill_idempotency import append_fill_idempotent

        return append_fill_idempotent(self, fill)

    def append_snapshot(self, snapshot: Any) -> None:
        self._append("portfolio_snapshots.jsonl", snapshot)

    def append_event(self, event: Any) -> None:
        self._append("events.jsonl", event)

    def write_result(self, result: Any, include_events: bool = False) -> None:
        for order in result.orders:
            self.append_order(order)
        for fill in result.fills:
            self.append_fill(fill)
        for snapshot in result.snapshots:
            self.append_snapshot(snapshot)
        if include_events:
            for event in result.events:
                self.append_event(event)

    def read_records(self, name: str) -> list[dict[str, Any]]:
        path = self.root / name
        with self._lock:
            if not path.exists():
                return []
            return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def read_fills(self) -> list[Fill]:
        return [_fill_from_record(row) for row in self.read_records("fills.jsonl")]

    def records_hash(self, name: str) -> str:
        return stable_json_hash(self.read_records(name))

    def ledger_hash(self, names: tuple[str, ...] = ("orders.jsonl", "fills.jsonl", "portfolio_snapshots.jsonl")) -> str:
        return stable_json_hash({name: self.read_records(name) for name in names})

    def write_reconciliation_artifact(self, artifact: Any) -> Path:
        recon_dir = self.root / "reconciliation"
        data = artifact.to_dict() if hasattr(artifact, "to_dict") else artifact
        jsonable = _to_jsonable(data)
        artifact_hash = str(jsonable.get("artifact_hash") or stable_json_hash(jsonable))
        path = recon_dir / f"ledger_recon_artifact_{artifact_hash[:16]}.json"
        with self._lock:
            recon_dir.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(jsonable, sort_keys=True, indent=2, default=str) + "\n",
                encoding="utf-8",
            )
        return path

    def latest_cash_from_fills(self, initial_cash: float = 0.0) -> float:
        """Derive current cash from all fill records starting from *initial_cash*."""
        cash = initial_cash
        for row in self.read_records("fills.jsonl"):
            fill = _fill_from_record(row)
            signed_qty = fill.quantity if fill.side == OrderSide.BUY else -fill.quantity
            cash -= signed_qty * fill.price
            cash -= fill.commission
        return cash

    def latest_positions_from_fills(self) -> dict[str, Position]:
        positions: dict[str, Position] = {}
        for row in self.read_records("fills.jsonl"):
            fill = _fill_from_record(row)
            position = positions.get(fill.symbol, Position(symbol=fill.symbol, market_price=fill.price))
            signed_quantity = fill.quantity if fill.side == OrderSide.BUY else -fill.quantity
            old_quantity = position.quantity
            new_quantity = old_quantity + signed_quantity
            if new_quantity == 0:
                position.quantity = 0.0
                position.avg_price = 0.0
            elif signed_quantity > 0:
                position.avg_price = ((old_quantity * position.avg_price) + (fill.quantity * fill.price)) / new_quantity
                position.quantity = new_quantity
            else:
                position.quantity = new_quantity
            position.market_price = fill.price
            position.unrealized_pnl = (position.market_price - position.avg_price) * position.quantity if position.avg_price else 0.0
            positions[fill.symbol] = position
        return positions

    def _append(self, name: str, value: Any) -> None:
        path = self.root / name
        with self._lock:
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(_to_jsonable(value), sort_keys=True) + "\n")


def _to_jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return _to_jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(key): _to_jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_to_jsonable(item) for item in value]
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    return value


def stable_json_hash(value: Any) -> str:
    payload = json.dumps(
        _to_jsonable(value),
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _fill_from_record(row: dict[str, Any]) -> Fill:
    return Fill(
        order_id=str(row.get("order_id", "")),
        symbol=str(row.get("symbol", "")),
        side=OrderSide(str(row.get("side", "buy"))),
        quantity=float(row.get("quantity", 0.0)),
        price=float(row.get("price", 0.0)),
        commission=float(row.get("commission", 0.0)),
        filled_at=datetime.fromisoformat(str(row.get("filled_at")).replace("Z", "+00:00")),
        broker=str(row.get("broker", "")),
        broker_order_id=str(row.get("broker_order_id", "")),
        fill_id=str(row.get("fill_id", "")),
    )
