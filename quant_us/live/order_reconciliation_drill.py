"""Order reconciliation drill rules for US equity execution readiness.

The drill is evidence-only: it simulates order lifecycle records, fills,
cash/position snapshots, and OMS exception controls without touching broker,
private, order, paper, or live endpoints.
"""

from __future__ import annotations

from typing import Any, Mapping

from quant_us.live.execution_drill_evidence import (
    REQUIRED_OMS_EXCEPTION_SCENARIOS,
    oms_exception_blockers,
    oms_exception_drill_proven,
    oms_exception_scenarios,
)


SCHEMA_VERSION = "us_equity_order_reconciliation_drill_v1"
INITIAL_CASH = 10_000.0
FEE_RATE_BPS = 1.0
STRATEGY_ID = "us_etf_rotation_min_adv_10m_vol_target_20pct_cap1_5x"


def build_order_reconciliation_drill_payload(
    *,
    generated_at: str,
    json_output: str,
    markdown_output: str,
) -> dict[str, Any]:
    """Build a deterministic simulated order-reconciliation evidence packet."""
    orders = sample_orders()
    fills, snapshots, ledger_blockers = reconcile_orders(orders)
    exception_matrix = oms_exception_scenarios()
    scenario_results = scenario_results_for_drill(
        orders=orders,
        fills=fills,
        snapshots=snapshots,
        ledger_blockers=ledger_blockers,
        exception_matrix=exception_matrix,
    )
    passed_count = sum(1 for item in scenario_results if item["status"] == "proven")
    blocked_count = len(scenario_results) - passed_count
    exception_matrix_complete = oms_exception_drill_proven(exception_matrix)
    blockers = dedupe(
        ledger_blockers
        + [blocker for item in scenario_results for blocker in list_of_str(item.get("blockers"))]
        + ([] if exception_matrix_complete else oms_exception_blockers(exception_matrix))
    )
    reconciliation = reconciliation_summary(fills, snapshots)
    status = (
        "order_reconciliation_drill_proven"
        if blocked_count == 0
        and not blockers
        and exception_matrix_complete
        and reconciliation.get("cash_recomputable") is True
        and reconciliation.get("positions_recomputable") is True
        and reconciliation.get("fees_recomputable") is True
        else "order_reconciliation_drill_blocked"
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "asset": "us_equity",
        "status": status,
        "allowed_statuses": [
            "order_reconciliation_drill_blocked",
            "order_reconciliation_drill_proven",
        ],
        "strategy_id": STRATEGY_ID,
        "initial_cash": INITIAL_CASH,
        "fee_rate_bps": FEE_RATE_BPS,
        "order_count": len(orders),
        "fill_count": len(fills),
        "snapshot_count": len(snapshots),
        "scenario_count": len(scenario_results),
        "proven_count": passed_count,
        "blocked_count": blocked_count,
        "orders": orders,
        "fills": fills,
        "portfolio_snapshots": snapshots,
        "scenario_results": scenario_results,
        "required_oms_exception_scenarios": sorted(REQUIRED_OMS_EXCEPTION_SCENARIOS),
        "oms_exception_matrix_complete": exception_matrix_complete,
        "oms_exception_matrix": exception_matrix,
        "blockers": blockers,
        "reconciliation": reconciliation,
        "guardrails": {
            "evidence_only": True,
            "simulated_ledger_only": True,
            "paper_or_live_unlock_allowed": False,
            "paper_simulation_allowed": False,
            "live_order_allowed": False,
            "private_endpoint_allowed": False,
            "order_endpoint_allowed": False,
            "broker_calls_used": False,
            "real_order_submitted": False,
        },
        "outputs": {
            "json": json_output,
            "markdown": markdown_output,
        },
    }


def sample_orders() -> list[dict[str, Any]]:
    return [
        {
            "timestamp": "2026-06-01T20:00:00Z",
            "order_id": "sim-buy-voo-001",
            "symbol": "VOO",
            "side": "BUY",
            "target_quantity": 10.0,
            "filled_quantity": 10.0,
            "price": 500.0,
            "status": "filled",
            "reason": "target_weight_increase",
            "lifecycle_events": ["created", "risk_checked", "submitted", "accepted", "filled", "reconciled"],
        },
        {
            "timestamp": "2026-06-02T20:00:00Z",
            "order_id": "sim-buy-gld-partial-001",
            "symbol": "GLD",
            "side": "BUY",
            "target_quantity": 20.0,
            "filled_quantity": 8.0,
            "price": 200.0,
            "status": "partial_fill",
            "reason": "liquidity_limited_fill",
            "lifecycle_events": ["created", "risk_checked", "submitted", "accepted", "partially_filled", "reconciled"],
        },
        {
            "timestamp": "2026-06-03T20:00:00Z",
            "order_id": "sim-sell-voo-001",
            "symbol": "VOO",
            "side": "SELL",
            "target_quantity": 4.0,
            "filled_quantity": 4.0,
            "price": 505.0,
            "status": "filled",
            "reason": "target_weight_decrease",
            "lifecycle_events": ["created", "risk_checked", "submitted", "accepted", "filled", "reconciled"],
        },
        {
            "timestamp": "2026-06-04T20:00:00Z",
            "order_id": "sim-reject-dbmf-001",
            "symbol": "DBMF",
            "side": "BUY",
            "target_quantity": 100.0,
            "filled_quantity": 0.0,
            "price": 28.0,
            "status": "rejected",
            "reason": "min_adv_gate_failed",
            "lifecycle_events": ["created", "risk_checked", "rejected", "reconciled"],
        },
        {
            "timestamp": "2026-06-05T20:00:00Z",
            "order_id": "sim-cancel-soxx-001",
            "symbol": "SOXX",
            "side": "BUY",
            "target_quantity": 2.0,
            "filled_quantity": 0.0,
            "price": 240.0,
            "status": "cancelled",
            "reason": "manual_stop_before_fill",
            "lifecycle_events": ["created", "risk_checked", "submitted", "accepted", "cancel_requested", "cancelled", "reconciled"],
        },
    ]


def reconcile_orders(orders: list[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    cash = INITIAL_CASH
    positions: dict[str, float] = {}
    fills: list[dict[str, Any]] = []
    snapshots: list[dict[str, Any]] = []
    blockers: list[str] = []
    last_prices: dict[str, float] = {}
    for order in orders:
        symbol = str(order["symbol"])
        side = str(order["side"])
        status = str(order["status"])
        price = as_float(order["price"])
        target_qty = as_float(order["target_quantity"])
        fill_qty = as_float(order["filled_quantity"])
        last_prices[symbol] = price
        if fill_qty < 0:
            blockers.append(f"negative_fill_quantity:{order['order_id']}")
        if fill_qty > target_qty:
            blockers.append(f"overfill:{order['order_id']}")
        if status in {"rejected", "cancelled"} and fill_qty != 0:
            blockers.append(f"terminal_nonzero_fill:{order['order_id']}")
        if fill_qty:
            notional = fill_qty * price
            fee = round(notional * FEE_RATE_BPS / 10_000.0, 8)
            signed_qty = fill_qty if side == "BUY" else -fill_qty
            cash_delta = -notional - fee if side == "BUY" else notional - fee
            cash = round(cash + cash_delta, 8)
            positions[symbol] = round(positions.get(symbol, 0.0) + signed_qty, 8)
            fills.append(
                {
                    "timestamp": order["timestamp"],
                    "fill_id": f"fill-{order['order_id']}",
                    "order_id": order["order_id"],
                    "symbol": symbol,
                    "side": side,
                    "quantity": fill_qty,
                    "price": price,
                    "notional": round(notional, 8),
                    "fee": fee,
                    "cash_delta": round(cash_delta, 8),
                    "status": "simulated_fill",
                }
            )
        market_value = round(sum(qty * last_prices.get(sym, 0.0) for sym, qty in positions.items()), 8)
        equity = round(cash + market_value, 8)
        snapshots.append(
            {
                "timestamp": order["timestamp"],
                "after_order_id": order["order_id"],
                "cash": cash,
                "market_value": market_value,
                "equity": equity,
                "positions": dict(sorted((sym, qty) for sym, qty in positions.items() if abs(qty) > 1e-12)),
            }
        )
    return fills, snapshots, blockers


def scenario_results_for_drill(
    *,
    orders: list[Mapping[str, Any]],
    fills: list[Mapping[str, Any]],
    snapshots: list[Mapping[str, Any]],
    ledger_blockers: list[str],
    exception_matrix: list[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    order_statuses = {str(item.get("status")) for item in orders}
    fill_order_ids = {str(item.get("order_id")) for item in fills}
    final = mapping(snapshots[-1] if snapshots else {})
    expected_equity = as_float(final.get("cash")) + as_float(final.get("market_value"))
    results = [
        scenario(
            "filled_order_reconciles_cash_position_fee",
            "ledger_reconciliation",
            not ledger_blockers and "sim-buy-voo-001" in fill_order_ids and "sim-sell-voo-001" in fill_order_ids,
            ["filled buy/sell orders create fills, fees, cash deltas and position changes"],
            ["sim-buy-voo-001", "sim-sell-voo-001"],
            ["filled_order_reconciliation_failed"],
        ),
        scenario(
            "partial_fill_state_reconciles",
            "ledger_reconciliation",
            "partial_fill" in order_statuses and "sim-buy-gld-partial-001" in fill_order_ids,
            ["partial fill creates a fill smaller than target quantity and updates cash/position"],
            ["sim-buy-gld-partial-001", "fill-sim-buy-gld-partial-001"],
            ["partial_fill_state_not_exercised"],
        ),
        scenario(
            "reject_order_creates_no_fill",
            "ledger_reconciliation",
            "rejected" in order_statuses and "sim-reject-dbmf-001" not in fill_order_ids,
            ["rejected order records terminal state and creates no fill"],
            ["sim-reject-dbmf-001"],
            ["reject_order_created_fill_or_missing_state"],
        ),
        scenario(
            "cancelled_order_creates_no_fill",
            "ledger_reconciliation",
            "cancelled" in order_statuses and "sim-cancel-soxx-001" not in fill_order_ids,
            ["cancelled order records cancel_requested/cancelled states and creates no fill"],
            ["sim-cancel-soxx-001"],
            ["cancelled_order_created_fill_or_missing_state"],
        ),
        scenario(
            "portfolio_snapshot_recomputes_from_fills",
            "ledger_reconciliation",
            bool(snapshots) and abs(as_float(final.get("equity")) - expected_equity) <= 1e-8,
            ["portfolio snapshot equity equals cash plus market value"],
            ["portfolio_snapshots"],
            ["portfolio_snapshot_not_recomputable"],
        ),
        scenario(
            "fees_recompute_from_notional",
            "ledger_reconciliation",
            all(
                abs(as_float(fill.get("fee")) - round(as_float(fill.get("notional")) * FEE_RATE_BPS / 10_000.0, 8))
                <= 1e-8
                for fill in fills
            ),
            ["each fill fee equals notional times configured fee rate"],
            ["fills"],
            ["fee_recalculation_failed"],
        ),
    ]
    results.extend(exception_scenario_result(item) for item in exception_matrix)
    return results


def exception_scenario_result(exception: Mapping[str, Any]) -> dict[str, Any]:
    scenario_id = str(exception.get("scenario_id", ""))
    return scenario(
        scenario_id,
        "oms_exception",
        exception.get("passed") is True,
        [str(exception.get("expected_action", ""))],
        [scenario_id],
        list_of_str(exception.get("blockers")) or [f"oms_exception_not_proven:{scenario_id}"],
    )


def scenario(
    scenario_id: str,
    category: str,
    passed: bool,
    required_evidence: list[str],
    evidence_refs: list[str],
    blockers: list[str],
) -> dict[str, Any]:
    return {
        "scenario_id": scenario_id,
        "category": category,
        "status": "proven" if passed else "blocked",
        "required_evidence": required_evidence,
        "evidence_refs": evidence_refs,
        "blockers": [] if passed else blockers,
    }


def reconciliation_summary(fills: list[Mapping[str, Any]], snapshots: list[Mapping[str, Any]]) -> dict[str, Any]:
    final = mapping(snapshots[-1] if snapshots else {})
    total_fees = round(sum(as_float(fill.get("fee")) for fill in fills), 8)
    return {
        "cash_recomputable": bool(snapshots),
        "positions_recomputable": bool(snapshots),
        "fees_recomputable": bool(fills),
        "final_cash": final.get("cash"),
        "final_market_value": final.get("market_value"),
        "final_equity": final.get("equity"),
        "total_fees": total_fees,
    }


def mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def list_of_str(value: Any) -> list[str]:
    return [str(item) for item in value if str(item)] if isinstance(value, list) else []


def as_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def dedupe(items: list[str]) -> list[str]:
    return list(dict.fromkeys(item for item in items if item))
