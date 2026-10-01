from __future__ import annotations

from dataclasses import asdict
from typing import Any

from quant_us.backtest.engine import BacktestConfig
from quant_us.portfolio.allocation import AllocationConfig
from quant_us.portfolio.position_sizer import PositionSizerConfig
from quant_us.portfolio.rebalance import RebalanceConfig
from quant_us.risk.pre_trade import PreTradeRiskConfig


def build_backtest_config(
    capital: float = 100_000.0,
    commission_rate: float = 0.0001,
    slippage_bps: float = 1.0,
    parameters: dict[str, Any] | None = None,
) -> BacktestConfig:
    params = parameters or {}
    max_symbol_weight = float(params.get("max_symbol_weight", 0.10))
    long_only = bool(params.get("long_only", True))
    return BacktestConfig(
        initial_cash=float(params.get("capital", capital)),
        commission_rate=float(params.get("commission_rate", commission_rate)),
        slippage_bps=float(params.get("slippage_bps", slippage_bps)),
        risk=PreTradeRiskConfig(
            max_symbol_weight=max_symbol_weight,
            max_gross_exposure=float(params.get("max_gross_exposure", 1.0)),
            max_order_notional_pct=float(params.get("max_order_notional_pct", 0.10)),
            min_cash_buffer_pct=float(params.get("min_cash_buffer_pct", 0.02)),
            long_only=long_only,
            blacklisted_symbols={str(symbol).upper() for symbol in params.get("blacklisted_symbols", [])},
        ),
        sizing=PositionSizerConfig(
            strategy_allocations={str(key): float(value) for key, value in dict(params.get("strategy_allocations", {})).items()},
            default_strategy_weight=float(params.get("default_strategy_weight", 0.10)),
            max_symbol_weight=max_symbol_weight,
            long_only=long_only,
        ),
        allocation=AllocationConfig(
            max_symbol_weight=max_symbol_weight,
            cash_reserve_weight=float(params.get("cash_reserve_weight", 0.05)),
            max_group_weight=None if params.get("max_group_weight") is None else float(params.get("max_group_weight")),
            group_map={str(key).upper(): str(value) for key, value in dict(params.get("group_map", {})).items()},
        ),
        rebalance=RebalanceConfig(
            min_trade_notional=float(params.get("min_trade_notional", 25.0)),
            min_quantity=float(params.get("min_quantity", 1e-6)),
            min_weight_change=float(params.get("min_weight_change", 0.0)),
        ),
    )


def config_to_metadata(config: BacktestConfig) -> dict[str, Any]:
    payload = asdict(config)
    payload["risk"]["allowed_sessions"] = sorted(str(item.value) for item in config.risk.allowed_sessions)
    payload["risk"]["blacklisted_symbols"] = sorted(config.risk.blacklisted_symbols)
    return payload
