"""Fixture-only portfolio event ledger plumbing for contract tests.

This module deliberately uses embedded fixture data. It proves that the
portfolio chain can carry targets, orders, fills, and ledger PnL, but it is not
alpha evidence and must never unlock paper or live gates.
"""

from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


INITIAL_CASH = 10_000.0
COMMISSION_PER_FILL = 1.0
SLIPPAGE_RATE = 0.0005


def build_portfolio_fixture_event_ledger_report(
    *,
    repo_root: Path | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at or datetime.now(timezone.utc).isoformat()
    alpha_scores = _alpha_scores()
    target_portfolio = _target_portfolio(alpha_scores)
    orders = _rebalance_orders(target_portfolio)
    fills = _simulated_fills(orders)
    ledger = _ledger_pnl(fills)
    ledger_validation = _ledger_validation(target_portfolio, orders, fills, ledger)
    return {
        "schema_version": "us_equity_portfolio_fixture_event_ledger_report_v1",
        "generated_at": generated,
        "commit": _git(["rev-parse", "--short", "HEAD"], cwd=root),
        "branch": _git(["branch", "--show-current"], cwd=root),
        "asset": "us_equity",
        "source_type": "fixture",
        "promotion_evidence": False,
        "event_ledger_validated": False,
        "paper_review_allowed": False,
        "candidate_passed_internal_gate": 0,
        "input_artifacts": {
            "alpha_scores": "embedded_fixture:alpha_scores",
            "target_portfolio": "embedded_fixture:target_portfolio",
            "rebalance_orders": "embedded_fixture:rebalance_orders",
            "fills": "embedded_fixture:simulated_fills",
            "ledger_pnl": "embedded_fixture:ledger_pnl",
        },
        "fixture_chain": {
            "alpha_scores": alpha_scores,
            "target_portfolio": target_portfolio,
            "rebalance_orders": orders,
            "fills": fills,
            "ledger_pnl": ledger,
        },
        "ledger_validation": ledger_validation,
        "metrics": {
            "gross_pnl": round(float(ledger["gross_pnl"]), 10),
            "net_pnl": round(float(ledger["net_pnl"]), 10),
            "turnover": round(float(ledger["turnover"]), 10),
            "commission": round(float(ledger["commission"]), 10),
            "slippage": round(float(ledger["slippage"]), 10),
            "max_drawdown": 0.0,
        },
        "promotion_ready": False,
        "paper_queue_status": "locked",
        "live_status": "frozen",
        "blockers": list(ledger_validation["blockers"]),
    }


def _alpha_scores() -> list[dict[str, Any]]:
    return [
        {"timestamp": "2026-01-02T14:30:00Z", "symbol": "AAPL", "score": 0.60},
        {"timestamp": "2026-01-02T14:30:00Z", "symbol": "MSFT", "score": 0.40},
    ]


def _target_portfolio(alpha_scores: list[dict[str, Any]]) -> list[dict[str, Any]]:
    total = sum(float(row["score"]) for row in alpha_scores)
    return [
        {
            "timestamp": row["timestamp"],
            "symbol": row["symbol"],
            "target_weight": round(0.98 * float(row["score"]) / total, 10),
        }
        for row in alpha_scores
    ]


def _rebalance_orders(target_portfolio: list[dict[str, Any]]) -> list[dict[str, Any]]:
    prices = {"AAPL": 100.0, "MSFT": 50.0}
    orders = []
    for row in target_portfolio:
        target_notional = INITIAL_CASH * float(row["target_weight"])
        quantity = target_notional / prices[str(row["symbol"])]
        orders.append(
            {
                "order_id": f"fixture-order-{row['symbol']}",
                "timestamp": row["timestamp"],
                "symbol": row["symbol"],
                "side": "buy",
                "quantity": round(quantity, 10),
                "reference_price": prices[str(row["symbol"])],
            }
        )
    return orders


def _simulated_fills(orders: list[dict[str, Any]]) -> list[dict[str, Any]]:
    fills = []
    for order in orders:
        reference_price = float(order["reference_price"])
        fill_price = reference_price * (1.0 + SLIPPAGE_RATE)
        quantity = float(order["quantity"])
        fills.append(
            {
                "fill_id": f"fixture-fill-{order['symbol']}",
                "order_id": order["order_id"],
                "timestamp": "2026-01-02T14:31:00Z",
                "symbol": order["symbol"],
                "side": order["side"],
                "quantity": round(quantity, 10),
                "fill_price": round(fill_price, 10),
                "commission": COMMISSION_PER_FILL,
                "slippage": round((fill_price - reference_price) * quantity, 10),
            }
        )
    return fills


def _ledger_pnl(fills: list[dict[str, Any]]) -> dict[str, Any]:
    mark_prices = {"AAPL": 101.0, "MSFT": 49.5}
    positions: dict[str, float] = {}
    cash = INITIAL_CASH
    commission = 0.0
    slippage = 0.0
    turnover_notional = 0.0
    for fill in fills:
        symbol = str(fill["symbol"])
        quantity = float(fill["quantity"])
        fill_price = float(fill["fill_price"])
        fill_commission = float(fill["commission"])
        fill_slippage = float(fill["slippage"])
        signed_quantity = quantity if fill["side"] == "buy" else -quantity
        positions[symbol] = positions.get(symbol, 0.0) + signed_quantity
        cash -= signed_quantity * fill_price + fill_commission
        commission += fill_commission
        slippage += fill_slippage
        turnover_notional += abs(signed_quantity * fill_price)
    ending_value = cash + sum(quantity * mark_prices[symbol] for symbol, quantity in positions.items())
    gross_pnl = ending_value - INITIAL_CASH + commission
    net_pnl = ending_value - INITIAL_CASH
    return {
        "initial_cash": INITIAL_CASH,
        "ending_cash": round(cash, 10),
        "positions": {symbol: round(quantity, 10) for symbol, quantity in sorted(positions.items())},
        "mark_prices": mark_prices,
        "ending_value": round(ending_value, 10),
        "gross_pnl": round(gross_pnl, 10),
        "net_pnl": round(net_pnl, 10),
        "commission": round(commission, 10),
        "slippage": round(slippage, 10),
        "turnover": round(turnover_notional / INITIAL_CASH, 10),
    }


def _ledger_validation(
    target_portfolio: list[dict[str, Any]],
    orders: list[dict[str, Any]],
    fills: list[dict[str, Any]],
    ledger: dict[str, Any],
) -> dict[str, Any]:
    target_weights = sum(float(row["target_weight"]) for row in target_portfolio)
    fill_order_ids = {str(fill["order_id"]) for fill in fills}
    order_ids = {str(order["order_id"]) for order in orders}
    cash_conservation = float(ledger["ending_cash"]) >= -1e-6
    position_conservation = order_ids == fill_order_ids and bool(ledger["positions"])
    long_only = all(float(quantity) >= 0 for quantity in ledger["positions"].values())
    cash_constrained = float(ledger["ending_cash"]) >= -1e-6
    return {
        "target_portfolio_available": bool(target_portfolio) and 0.0 < target_weights <= 1.0,
        "rebalance_orders_available": bool(orders),
        "fills_available": bool(fills),
        "ledger_pnl_available": bool(ledger),
        "cost_model_applied": True,
        "cash_conservation_check": cash_conservation,
        "position_conservation_check": position_conservation,
        "no_short_when_long_only_check": long_only,
        "no_negative_cash_if_cash_constrained_check": cash_constrained,
        "promotion_ready": False,
        "paper_review_allowed": False,
        "blockers": [
            "source_type_fixture",
            "production_data_missing",
            "not_event_ledger_candidate",
        ],
    }


def _git(args: list[str], *, cwd: Path) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=cwd, stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:
        return "unknown"
