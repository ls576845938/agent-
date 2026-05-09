"""Reconciliation service with full stop-alert-report flow.

Checks ALL FOUR dimensions (cash, positions, orders, fills) and implements
the halt-alert-report flow on mismatch.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from quant_us.core.enums import OrderSide
from quant_us.core.types import Fill, Position
from quant_us.execution.broker_base import BrokerBase
from quant_us.execution.ledger import JsonlLedgerStore
from quant_us.live.state_reconciler import StateReconciler
from quant_us.monitoring.telegram_alerts import AlertPriority, TelegramAlertService

_logger = logging.getLogger("reconciliation")


@dataclass
class ReconciliationReport:
    """Full reconciliation result across all four dimensions.

    Attributes:
        status: "clean" or "breaks_detected"
        cash_diff: broker_cash - local_cash
        position_diffs: dict keyed by symbol
        order_diffs: dict keyed by order_id
        fill_diffs: dict keyed by fill_id
        halt_new_orders: True when any break is detected
        alert_sent: True when alert was dispatched
        report_path: filesystem path to the JSON report file
    """
    status: str = "clean"
    cash_diff: float = 0.0
    position_diffs: dict[str, dict[str, float]] = field(default_factory=dict)
    order_diffs: dict[str, dict[str, Any]] = field(default_factory=dict)
    fill_diffs: dict[str, dict[str, Any]] = field(default_factory=dict)
    halt_new_orders: bool = False
    alert_sent: bool = False
    report_path: str = ""


class ReconciliationService:
    """Reconcile broker state against local ledger state.

    Usage:
        service = ReconciliationService(ledger_dir, broker)
        report = service.reconcile_all(initial_cash=100_000.0)
    """

    def __init__(self, ledger_dir: str | Path, broker: BrokerBase) -> None:
        self.ledger = JsonlLedgerStore(ledger_dir)
        self.broker = broker
        self.reconciler = StateReconciler()

    def reconcile_positions(self, tolerance: float = 1e-6) -> dict[str, object]:
        """Legacy: positions-only reconciliation. Returns dict for backward compat."""
        local_positions = self.ledger.latest_positions_from_fills()
        broker_positions = self.broker.get_positions()
        report = self.reconciler.report(local_positions, broker_positions, tolerance=tolerance)
        return asdict(report)

    # ------------------------------------------------------------------
    # Full four-dimensional reconciliation
    # ------------------------------------------------------------------

    def reconcile_all(
        self,
        initial_cash: float,
        telegram_alerts: TelegramAlertService | None = None,
        position_tolerance: float = 1e-6,
    ) -> ReconciliationReport:
        """Check ALL FOUR dimensions against broker.

        Args:
            initial_cash: Starting cash, used to compute expected local cash
                          from ledger fills.
            telegram_alerts: Optional alert service. If provided and breaks
                             are detected, a CRITICAL alert is sent.
            position_tolerance: Tolerance for quantity comparison (default 1e-6).

        Returns:
            ReconciliationReport with full diff details.
        """
        # 1) Broker state
        broker_account = self.broker.get_account()
        broker_cash = broker_account.cash
        broker_positions = self.broker.get_positions()
        broker_orders = self.broker.get_orders()
        broker_fills = self.broker.get_fills()

        # 2) Local (ledger) state
        local_cash = self._compute_local_cash(initial_cash)
        local_positions = self.ledger.latest_positions_from_fills()
        local_order_records = self.ledger.read_records("orders.jsonl")
        local_fill_records = self.ledger.read_records("fills.jsonl")

        # 3) Compare each dimension
        cash_diff = broker_cash - local_cash
        position_diffs = self._compare_positions(local_positions, broker_positions, position_tolerance)
        order_diffs = self._compare_orders(local_order_records, broker_orders)
        fill_diffs = self._compare_fills(local_fill_records, broker_fills)

        has_breaks = (
            abs(cash_diff) > 1e-6
            or bool(position_diffs)
            or bool(order_diffs)
            or bool(fill_diffs)
        )

        status = "breaks_detected" if has_breaks else "clean"
        halt_new_orders = has_breaks
        alert_sent = False

        # 4) Write JSON report file
        report_dir = Path(self.ledger.root) / "reconciliation"
        report_dir.mkdir(parents=True, exist_ok=True)
        now = datetime.now(timezone.utc)
        report_filename = f"recon_{now.strftime('%Y%m%d_%H%M%S')}.json"
        report_path = report_dir / report_filename

        report_data: dict[str, Any] = {
            "timestamp": now.isoformat(),
            "status": status,
            "cash_diff": cash_diff,
            "position_diffs": position_diffs,
            "order_diffs": order_diffs,
            "fill_diffs": fill_diffs,
            "halt_new_orders": halt_new_orders,
            "alert_sent": alert_sent,
        }
        report_path.write_text(json.dumps(report_data, indent=2, default=str))

        # 5) Alert if breaks and alert service available
        if has_breaks and telegram_alerts is not None:
            self._send_recon_alert(telegram_alerts, report_data)
            alert_sent = True
            report_data["alert_sent"] = True
            report_path.write_text(json.dumps(report_data, indent=2, default=str))

        return ReconciliationReport(
            status=status,
            cash_diff=cash_diff,
            position_diffs=position_diffs,
            order_diffs=order_diffs,
            fill_diffs=fill_diffs,
            halt_new_orders=halt_new_orders,
            alert_sent=alert_sent,
            report_path=str(report_path),
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _compute_local_cash(self, initial_cash: float) -> float:
        """Reconstruct cash balance from ledger fills independently of broker."""
        cash = initial_cash
        for row in self.ledger.read_records("fills.jsonl"):
            qty = float(row.get("quantity", 0.0))
            price = float(row.get("price", 0.0))
            commission = float(row.get("commission", 0.0))
            side = str(row.get("side", ""))
            if side in ("buy", OrderSide.BUY.value):
                cash -= qty * price + commission
            else:
                cash += qty * price - commission
        return cash

    @staticmethod
    def _compare_positions(
        local: dict[str, Position],
        broker: dict[str, Position],
        tolerance: float,
    ) -> dict[str, dict[str, float]]:
        """Return per-symbol diffs where quantity differs beyond tolerance."""
        symbols = set(local) | set(broker)
        diffs: dict[str, dict[str, float]] = {}
        for sym in symbols:
            local_qty = local.get(sym, Position(sym)).quantity
            broker_qty = broker.get(sym, Position(sym)).quantity
            diff = broker_qty - local_qty
            if abs(diff) > tolerance:
                local_pos = local.get(sym, Position(sym))
                broker_pos = broker.get(sym, Position(sym))
                diffs[sym] = {
                    "local_quantity": local_qty,
                    "broker_quantity": broker_qty,
                    "quantity_diff": diff,
                    "local_market_value": local_pos.market_value,
                    "broker_market_value": broker_pos.market_value,
                }
        return diffs

    @staticmethod
    def _compare_orders(
        local_records: list[dict[str, Any]],
        broker_orders: list[Any],
    ) -> dict[str, dict[str, Any]]:
        """Compare order status and quantity by order_id."""
        local_groups: dict[str, list[dict[str, Any]]] = {}
        for record in local_records:
            order_id = str(record.get("order_id", "") or "")
            if order_id:
                local_groups.setdefault(order_id, []).append(record)
        local_by_id = {order_id: records[-1] for order_id, records in local_groups.items()}
        broker_by_id = {
            str(getattr(o, "order_id", "") or ""): o
            for o in broker_orders
            if str(getattr(o, "order_id", "") or "")
        }
        all_ids = set(local_by_id) | set(broker_by_id)
        diffs: dict[str, dict[str, Any]] = {}
        for oid in sorted(all_ids):
            local = local_by_id.get(oid)
            broker = broker_by_id.get(oid)
            local_group = local_groups.get(oid, [])
            if len(local_group) > 1:
                statuses = sorted({str(r.get("status", "N/A")) for r in local_group})
                quantities = sorted({float(r.get("quantity", 0.0)) for r in local_group})
                if len(statuses) > 1 or len(quantities) > 1:
                    diffs.setdefault(oid, {}).update({
                        "local_conflict": True,
                        "local_statuses": statuses,
                        "local_quantities": quantities,
                    })
            local_status = str(local.get("status", "N/A")) if local else "MISSING"
            broker_status = (
                ReconciliationService._enum_value(getattr(broker, "status", ""))
                if broker
                else "MISSING"
            )
            local_quantity = float(local.get("quantity", 0.0)) if local else 0.0
            broker_quantity = float(getattr(broker, "quantity", 0.0)) if broker else 0.0
            status_mismatch = local_status != broker_status
            quantity_diff = broker_quantity - local_quantity
            quantity_mismatch = abs(quantity_diff) > 1e-8
            if status_mismatch or quantity_mismatch:
                diffs.setdefault(oid, {}).update({
                    "local_status": local_status,
                    "broker_status": broker_status,
                    "local_quantity": local_quantity,
                    "broker_quantity": broker_quantity,
                })
                if status_mismatch:
                    diffs[oid]["status_mismatch"] = True
                if quantity_mismatch:
                    diffs[oid]["quantity_diff"] = quantity_diff
        return diffs

    @staticmethod
    def _compare_fills(
        local_records: list[dict[str, Any]],
        broker_fills: list[Fill],
    ) -> dict[str, dict[str, Any]]:
        """Compare fill payload by fill_id (fallback to order_id)."""
        local_groups: dict[str, list[dict[str, Any]]] = {}
        for r in local_records:
            fid = r.get("fill_id", "") or r.get("order_id", "")
            if not fid:
                continue
            local_groups.setdefault(str(fid), []).append(r)
        local_by_id: dict[str, dict[str, Any]] = {
            fill_id: records[-1] for fill_id, records in local_groups.items()
        }

        broker_by_id: dict[str, Fill] = {}
        for f in broker_fills:
            fid = str(getattr(f, "fill_id", "") or getattr(f, "order_id", "") or "")
            if fid:
                broker_by_id[fid] = f

        all_ids = set(local_by_id) | set(broker_by_id)
        diffs: dict[str, dict[str, Any]] = {}
        for fid in sorted(all_ids):
            local = local_by_id.get(fid)
            broker = broker_by_id.get(fid)
            local_group = local_groups.get(fid, [])
            if len(local_group) > 1:
                quantities = sorted({float(r.get("quantity", 0.0)) for r in local_group})
                prices = sorted({float(r.get("price", 0.0)) for r in local_group})
                commissions = sorted({float(r.get("commission", 0.0)) for r in local_group})
                sides = sorted({str(r.get("side", "") or "") for r in local_group})
                symbols = sorted({str(r.get("symbol", "") or "").upper() for r in local_group})
                if (
                    len(quantities) > 1
                    or len(prices) > 1
                    or len(commissions) > 1
                    or len(sides) > 1
                    or len(symbols) > 1
                ):
                    diffs.setdefault(fid, {}).update({
                        "local_conflict": True,
                        "local_quantities": quantities,
                        "local_prices": prices,
                        "local_commissions": commissions,
                        "local_sides": sides,
                        "local_symbols": symbols,
                    })
            if local and broker:
                local_qty = float(local.get("quantity", 0.0))
                broker_qty = float(getattr(broker, "quantity", 0.0))
                local_price = float(local.get("price", 0.0))
                broker_price = float(getattr(broker, "price", 0.0))
                local_commission = float(local.get("commission", 0.0))
                broker_commission = float(getattr(broker, "commission", 0.0))
                local_side = str(local.get("side", "") or "")
                broker_side = ReconciliationService._enum_value(getattr(broker, "side", ""))
                local_symbol = str(local.get("symbol", "") or "").upper()
                broker_symbol = str(getattr(broker, "symbol", "") or "").upper()

                quantity_diff = broker_qty - local_qty
                price_diff = broker_price - local_price
                commission_diff = broker_commission - local_commission

                if (
                    abs(quantity_diff) > 1e-8
                    or abs(price_diff) > 1e-8
                    or abs(commission_diff) > 1e-8
                    or local_side != broker_side
                    or local_symbol != broker_symbol
                ):
                    diffs.setdefault(fid, {}).update({
                        "local_quantity": local_qty,
                        "broker_quantity": broker_qty,
                        "local_price": local_price,
                        "broker_price": broker_price,
                        "local_commission": local_commission,
                        "broker_commission": broker_commission,
                        "local_side": local_side,
                        "broker_side": broker_side,
                        "local_symbol": local_symbol,
                        "broker_symbol": broker_symbol,
                    })
                    if abs(quantity_diff) > 1e-8:
                        diffs[fid]["quantity_diff"] = quantity_diff
                    if abs(price_diff) > 1e-8:
                        diffs[fid]["price_diff"] = price_diff
                    if abs(commission_diff) > 1e-8:
                        diffs[fid]["commission_diff"] = commission_diff
                    if local_side != broker_side:
                        diffs[fid]["side_mismatch"] = True
                    if local_symbol != broker_symbol:
                        diffs[fid]["symbol_mismatch"] = True
            elif local and not broker:
                diffs[fid] = {
                    "local_only": True,
                    "local_quantity": float(local.get("quantity", 0.0)),
                    "local_price": float(local.get("price", 0.0)),
                    "local_commission": float(local.get("commission", 0.0)),
                    "local_side": str(local.get("side", "") or ""),
                    "local_symbol": str(local.get("symbol", "") or "").upper(),
                }
            elif broker and not local:
                diffs[fid] = {
                    "broker_only": True,
                    "broker_quantity": float(getattr(broker, "quantity", 0.0)),
                    "broker_price": float(getattr(broker, "price", 0.0)),
                    "broker_commission": float(getattr(broker, "commission", 0.0)),
                    "broker_side": ReconciliationService._enum_value(
                        getattr(broker, "side", "")
                    ),
                    "broker_symbol": str(getattr(broker, "symbol", "") or "").upper(),
                }
        return diffs

    @staticmethod
    def _enum_value(value: Any) -> str:
        return str(getattr(value, "value", value) or "")

    @staticmethod
    def _send_recon_alert(alerts: TelegramAlertService, report_data: dict[str, Any]) -> None:
        """Send a single CRITICAL alert summarising all breaks."""
        lines: list[str] = [
            "*Reconciliation Breaks Detected*",
            "",
        ]
        cash_diff = report_data.get("cash_diff", 0.0)
        if abs(cash_diff) > 1e-6:
            lines.append(f"*Cash diff:* {cash_diff:+.2f}")

        pos_diffs = report_data.get("position_diffs", {})
        if pos_diffs:
            lines.append(f"*Position diffs:* {len(pos_diffs)} symbols")
            for sym, d in list(pos_diffs.items())[:5]:
                lines.append(f"  {sym}: broker={d['broker_quantity']} local={d['local_quantity']}")
            if len(pos_diffs) > 5:
                lines.append(f"  ... and {len(pos_diffs) - 5} more")

        ord_diffs = report_data.get("order_diffs", {})
        if ord_diffs:
            lines.append(f"*Order diffs:* {len(ord_diffs)} orders")

        fill_diffs = report_data.get("fill_diffs", {})
        if fill_diffs:
            lines.append(f"*Fill diffs:* {len(fill_diffs)} fills")

        lines.extend(["", "Trading halted until resolved."])
        alerts.send("\n".join(lines), priority=AlertPriority.CRITICAL)
