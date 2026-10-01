from __future__ import annotations

from typing import Any, Mapping

from quant_us.backtest.us_etf_rotation_execution import (
    UsEtfBacktestExecutionResult,
    simulate_us_etf_rotation_backtest_execution,
)


def target_from_validation_report(validation: Mapping[str, Any]) -> dict[str, Any]:
    profile = _mapping(validation.get("small_account_10k_profile"))
    target = _mapping(profile.get("constrained_latest_target"))
    rows = list(target.get("targets", []))
    weights = {str(row["symbol"]): float(row["target_weight"]) for row in rows if isinstance(row, Mapping)}
    notionals = {str(row["symbol"]): float(row["target_notional"]) for row in rows if isinstance(row, Mapping)}
    shares = {str(row["symbol"]): float(row["shares"]) for row in rows if isinstance(row, Mapping)}
    prices = {str(row["symbol"]): float(row["price"]) for row in rows if isinstance(row, Mapping)}
    return {
        "date": str(target.get("date", "")),
        "gross_exposure": float(target.get("gross_exposure", 0.0)),
        "net_exposure": float(target.get("net_exposure", 0.0)),
        "target_count": int(target.get("target_count", len(rows))),
        "weights": weights,
        "notionals": notionals,
        "shares": shares,
        "prices": prices,
    }


def calculate_rebalance_delta(
    current: Mapping[str, Any],
    target: Mapping[str, Any],
    equity: float,
    slippage_bps: float,
    validation: Mapping[str, Any],
) -> dict[str, Any]:
    current_weights = _mapping(current.get("weights"))
    target_weights = _mapping(target.get("weights"))
    symbols = sorted(set(current_weights) | set(target_weights))
    deltas = {symbol: float(target_weights.get(symbol, 0.0)) - float(current_weights.get(symbol, 0.0)) for symbol in symbols}
    turnover = sum(abs(value) for value in deltas.values())
    trade_notional = turnover * equity
    slippage = trade_notional * float(slippage_bps) / 10_000.0
    financing = estimate_financing_daily(equity, target, validation)
    return {
        "deltas": deltas,
        "turnover": float(turnover),
        "estimated_trade_notional": float(trade_notional),
        "slippage_bps": float(slippage_bps),
        "estimated_slippage": float(slippage),
        "estimated_financing_daily": float(financing),
        "simulated_only": True,
        "layer": "execution_simulation",
    }


def estimate_financing_daily(equity: float, target: Mapping[str, Any], validation: Mapping[str, Any]) -> float:
    financing_model = _mapping(validation.get("financing_model"))
    avg_rate = _float_or(financing_model.get("average_annual_rate"), 0.0)
    borrow_exposure = max(0.0, float(target.get("gross_exposure", 0.0)) - 1.0)
    return equity * borrow_exposure * avg_rate / 252.0


def build_simulated_fills(
    timestamp: str,
    target: Mapping[str, Any],
    equity: float,
    rebalance: Mapping[str, Any],
    generated_at: str,
    *,
    strategy_id: str,
    candidate_variant: str,
) -> list[dict[str, Any]]:
    prices = _mapping(target.get("prices"))
    fills = []
    for symbol, delta_weight in _mapping(rebalance.get("deltas")).items():
        delta = float(delta_weight)
        if abs(delta) <= 1e-12:
            continue
        price = _float_or(prices.get(symbol), 0.0)
        notional = abs(delta) * equity
        fills.append(
            {
                "timestamp": timestamp,
                "strategy_id": strategy_id,
                "candidate_variant": candidate_variant,
                "symbol": symbol,
                "side": "buy" if delta > 0 else "sell",
                "price": round(price, 6),
                "quantity": round(notional / price, 10) if price > 0 else 0.0,
                "notional": round(notional, 6),
                "delta_weight": round(delta, 10),
                "simulated_only": True,
                "broker_order_id": "",
                "exchange_order_id": "",
                "generated_at": generated_at,
                "layer": "execution_simulation",
            }
        )
    return fills


def reconcile_simulated_snapshot(
    *,
    snapshot: Mapping[str, Any],
    prior_equity: float,
    rebalance: Mapping[str, Any],
) -> dict[str, Any]:
    expected = prior_equity - float(rebalance["estimated_slippage"]) - float(rebalance["estimated_financing_daily"])
    actual = _float_or(snapshot.get("equity"), 0.0)
    diff = abs(expected - actual)
    return {
        "status": "clean" if diff <= 0.01 else "mismatch",
        "passed": diff <= 0.01,
        "expected_equity": round(expected, 6),
        "actual_equity": round(actual, 6),
        "difference": round(diff, 8),
        "layer": "execution_simulation",
    }


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _float_or(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
