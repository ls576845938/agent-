from __future__ import annotations

from dataclasses import dataclass

from quant_us.core.enums import OrderSide, OrderType, TimeInForce
from quant_us.core.types import AccountState, OrderIntent, TargetPosition


@dataclass(frozen=True)
class RebalanceConfig:
    min_trade_notional: float = 25.0
    min_quantity: float = 1e-6
    min_weight_change: float = 0.0


class RebalancePlanner:
    def __init__(self, config: RebalanceConfig | None = None) -> None:
        self.config = config or RebalanceConfig()

    def plan(
        self,
        targets: list[TargetPosition],
        account: AccountState,
        prices: dict[str, float],
        run_id: str,
    ) -> list[OrderIntent]:
        intents: list[OrderIntent] = []
        for target in targets:
            price = float(prices.get(target.symbol, 0.0))
            if price <= 0:
                continue
            current = account.positions.get(target.symbol)
            current_quantity = current.quantity if current else 0.0
            current_weight = current_quantity * price / max(account.equity, 1.0)
            if abs(target.target_weight - current_weight) < self.config.min_weight_change:
                continue
            target_quantity = target.target_quantity
            if target_quantity is None:
                target_quantity = account.equity * target.target_weight / price
            delta = target_quantity - current_quantity
            notional = abs(delta) * price
            if abs(delta) < self.config.min_quantity or notional < self.config.min_trade_notional:
                continue
            intents.append(
                OrderIntent(
                    timestamp_utc=target.timestamp_utc,
                    strategy_id=target.strategy_id,
                    symbol=target.symbol,
                    side=OrderSide.BUY if delta > 0 else OrderSide.SELL,
                    quantity=abs(delta),
                    order_type=OrderType.MARKET,
                    time_in_force=TimeInForce.DAY,
                    run_id=run_id,
                    signal_id=target.signal_id,
                    target_position_id=target.target_position_id,
                    metadata={"target_weight": target.target_weight, "target_quantity": target_quantity},
                )
            )
        return intents
