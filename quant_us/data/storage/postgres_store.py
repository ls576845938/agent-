from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


@dataclass(frozen=True)
class PostgresConfig:
    dsn: str
    schema: str = "quant"


class PostgresStateStore:
    def __init__(self, config: PostgresConfig, connection: Any | None = None) -> None:
        self.config = config
        self._connection = connection

    def connect(self):
        if self._connection is not None:
            return self._connection
        try:
            import psycopg
        except ImportError as exc:
            raise RuntimeError("psycopg is required for PostgresStateStore") from exc
        self._connection = psycopg.connect(self.config.dsn)
        return self._connection

    def write_orders(self, orders: list[Any]) -> int:
        if not orders:
            return 0
        rows = [_order_row(order) for order in orders]
        sql = f"""
            insert into {self.config.schema}.orders (
                order_id, client_order_id, strategy_id, run_id, signal_id, risk_check_id,
                broker_order_id, symbol, side, order_type, quantity, limit_price,
                status, broker, created_at, updated_at
            ) values (
                %(order_id)s, %(client_order_id)s, %(strategy_id)s, %(run_id)s, %(signal_id)s, %(risk_check_id)s,
                %(broker_order_id)s, %(symbol)s, %(side)s, %(order_type)s, %(quantity)s, %(limit_price)s,
                %(status)s, %(broker)s, %(created_at)s, %(updated_at)s
            )
            on conflict (order_id) do update set
                broker_order_id = excluded.broker_order_id,
                status = excluded.status,
                updated_at = excluded.updated_at
        """
        self._executemany(sql, rows)
        return len(rows)

    def write_fills(self, fills: list[Any]) -> int:
        if not fills:
            return 0
        rows = [_fill_row(fill) for fill in fills]
        sql = f"""
            insert into {self.config.schema}.fills (
                fill_id, order_id, symbol, side, quantity, price, commission,
                filled_at, broker, broker_order_id
            ) values (
                %(fill_id)s, %(order_id)s, %(symbol)s, %(side)s, %(quantity)s, %(price)s, %(commission)s,
                %(filled_at)s, %(broker)s, %(broker_order_id)s
            )
            on conflict (fill_id) do nothing
        """
        self._executemany(sql, rows)
        return len(rows)

    def write_snapshots(self, snapshots: list[Any], account_id: str = "default") -> int:
        if not snapshots:
            return 0
        rows = [_snapshot_row(snapshot, account_id=account_id) for snapshot in snapshots]
        sql = f"""
            insert into {self.config.schema}.portfolio_snapshots (
                timestamp, account_id, equity, cash, gross_exposure,
                net_exposure, daily_pnl, drawdown
            ) values (
                %(timestamp)s, %(account_id)s, %(equity)s, %(cash)s, %(gross_exposure)s,
                %(net_exposure)s, %(daily_pnl)s, %(drawdown)s
            )
            on conflict (timestamp, account_id) do update set
                equity = excluded.equity,
                cash = excluded.cash,
                gross_exposure = excluded.gross_exposure,
                net_exposure = excluded.net_exposure,
                daily_pnl = excluded.daily_pnl,
                drawdown = excluded.drawdown
        """
        self._executemany(sql, rows)
        return len(rows)

    def write_result(self, result: Any, account_id: str = "default") -> dict[str, int]:
        return {
            "orders": self.write_orders(list(result.orders)),
            "fills": self.write_fills(list(result.fills)),
            "snapshots": self.write_snapshots(list(result.snapshots), account_id=account_id),
        }

    def _executemany(self, sql: str, rows: list[dict[str, Any]]) -> None:
        connection = self.connect()
        with connection.cursor() as cursor:
            cursor.executemany(sql, rows)
        connection.commit()


def _order_row(order: Any) -> dict[str, Any]:
    return {
        "order_id": order.order_id,
        "client_order_id": order.client_order_id,
        "strategy_id": order.strategy_id,
        "run_id": order.run_id,
        "signal_id": order.signal_id,
        "risk_check_id": order.risk_check_id,
        "broker_order_id": order.broker_order_id,
        "symbol": order.symbol,
        "side": _value(order.side),
        "order_type": _value(order.order_type),
        "quantity": order.quantity,
        "limit_price": order.limit_price,
        "status": _value(order.status),
        "broker": getattr(order, "broker", ""),
        "created_at": order.created_at,
        "updated_at": order.updated_at,
    }


def _fill_row(fill: Any) -> dict[str, Any]:
    return {
        "fill_id": fill.fill_id,
        "order_id": fill.order_id,
        "symbol": fill.symbol,
        "side": _value(fill.side),
        "quantity": fill.quantity,
        "price": fill.price,
        "commission": fill.commission,
        "filled_at": fill.filled_at,
        "broker": fill.broker,
        "broker_order_id": fill.broker_order_id,
    }


def _snapshot_row(snapshot: Any, account_id: str) -> dict[str, Any]:
    return {
        "timestamp": snapshot.timestamp_utc,
        "account_id": account_id,
        "equity": snapshot.equity,
        "cash": snapshot.cash,
        "gross_exposure": snapshot.gross_exposure,
        "net_exposure": snapshot.net_exposure,
        "daily_pnl": snapshot.daily_pnl,
        "drawdown": snapshot.drawdown,
    }


def _value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    return value
