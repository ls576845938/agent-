from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from quant_us.core.enums import OrderSide
from quant_us.core.types import AccountState, OrderIntent, Position, TargetPosition
from quant_us.portfolio.rebalance import RebalanceConfig, RebalancePlanner
from quant_us.risk.pre_trade import PortfolioRiskPolicy


@dataclass(frozen=True)
class AllocationConfig:
    max_symbol_weight: float = 0.1
    cash_reserve_weight: float = 0.05
    max_gross_exposure: float = 0.95
    max_daily_turnover: float = 1.0
    max_group_weight: float | None = None
    group_map: dict[str, str] = field(default_factory=dict)
    strategy_weights: dict[str, float] = field(default_factory=dict)
    default_strategy_weight: float = 1.0


@dataclass(frozen=True)
class PortfolioConstraintReason:
    rule_name: str
    message: str
    before: float
    after: float
    symbol: str = ""


@dataclass(frozen=True)
class PortfolioTargetDecision:
    symbol: str
    raw_weight: float
    final_weight: float
    strategies: tuple[str, ...]
    reasons: tuple[PortfolioConstraintReason, ...] = ()


@dataclass(frozen=True)
class PortfolioIntentDecision:
    symbol: str
    raw_delta_quantity: float
    final_delta_quantity: float
    side: OrderSide | None
    reasons: tuple[PortfolioConstraintReason, ...] = ()


@dataclass(frozen=True)
class PortfolioAllocationResult:
    targets: list[TargetPosition]
    target_decisions: list[PortfolioTargetDecision]
    intents: list[OrderIntent] = field(default_factory=list)
    intent_decisions: list[PortfolioIntentDecision] = field(default_factory=list)


@dataclass(frozen=True)
class _SymbolState:
    timestamp_target: TargetPosition
    raw_weight: float
    weighted_weight: float
    strategies: tuple[str, ...]
    contributions: tuple[dict[str, object], ...]
    reasons: tuple[PortfolioConstraintReason, ...]


class PortfolioAllocator:
    def __init__(
        self,
        config: AllocationConfig | None = None,
        risk_policy: PortfolioRiskPolicy | None = None,
        rebalance_config: RebalanceConfig | None = None,
    ) -> None:
        self.config = config or AllocationConfig()
        self.risk_policy = risk_policy or PortfolioRiskPolicy(
            cash_reserve_weight=self.config.cash_reserve_weight,
            max_symbol_weight=self.config.max_symbol_weight,
            max_gross_exposure=self.config.max_gross_exposure,
            max_daily_turnover=self.config.max_daily_turnover,
        )
        self.rebalance = RebalancePlanner(rebalance_config or RebalanceConfig())

    def allocate_targets(
        self,
        targets: list[TargetPosition],
        account: AccountState | None = None,
        prices: dict[str, float] | None = None,
        run_id: str = "",
    ) -> PortfolioAllocationResult:
        if not targets:
            return PortfolioAllocationResult(targets=[], target_decisions=[])

        symbol_states = self._combine_weighted_targets(targets)
        target_weights = {symbol: state.weighted_weight for symbol, state in symbol_states.items()}
        weight_reasons = {symbol: list(state.reasons) for symbol, state in symbol_states.items()}
        capped_weights = self._apply_weight_caps(target_weights, weight_reasons)

        if account is not None and prices is not None:
            capped_weights = self._apply_turnover_cap(capped_weights, account, prices, weight_reasons)

        final_targets = self._build_targets(symbol_states, capped_weights, weight_reasons)
        target_decisions = [
            PortfolioTargetDecision(
                symbol=target.symbol,
                raw_weight=symbol_states[target.symbol].raw_weight,
                final_weight=target.target_weight,
                strategies=symbol_states[target.symbol].strategies,
                reasons=tuple(weight_reasons[target.symbol]),
            )
            for target in final_targets
        ]

        intents: list[OrderIntent] = []
        intent_decisions: list[PortfolioIntentDecision] = []
        if account is not None and prices is not None:
            intents = self.rebalance.plan(final_targets, account, prices, run_id=run_id)
            intent_decisions = self._build_intent_decisions(final_targets, intents, account, prices, weight_reasons)

        return PortfolioAllocationResult(
            targets=final_targets,
            target_decisions=target_decisions,
            intents=intents,
            intent_decisions=intent_decisions,
        )

    def merge_order_intents(
        self,
        intents: list[OrderIntent],
        account: AccountState,
        prices: dict[str, float],
        run_id: str,
    ) -> PortfolioAllocationResult:
        if not intents:
            return PortfolioAllocationResult(targets=[], target_decisions=[], intents=[], intent_decisions=[])

        target_inputs = self._targets_from_order_intents(intents, account, prices)
        return self.allocate_targets(target_inputs, account=account, prices=prices, run_id=run_id)

    def _combine_weighted_targets(self, targets: list[TargetPosition]) -> dict[str, _SymbolState]:
        raw_by_symbol: dict[str, float] = defaultdict(float)
        weighted_by_symbol: dict[str, float] = defaultdict(float)
        latest_by_symbol: dict[str, TargetPosition] = {}
        strategies_by_symbol: dict[str, set[str]] = defaultdict(set)
        contributions_by_symbol: dict[str, list[dict[str, object]]] = defaultdict(list)
        reasons_by_symbol: dict[str, list[PortfolioConstraintReason]] = defaultdict(list)

        for target in targets:
            symbol = target.symbol.upper()
            raw_by_symbol[symbol] += target.target_weight
            strategy_weight = self.config.strategy_weights.get(target.strategy_id, self.config.default_strategy_weight)
            weighted_value = target.target_weight * strategy_weight
            weighted_by_symbol[symbol] += weighted_value
            latest_by_symbol[symbol] = target
            strategies_by_symbol[symbol].add(target.strategy_id)
            contributions_by_symbol[symbol].append(
                {
                    "strategy_id": target.strategy_id,
                    "raw_weight": target.target_weight,
                    "strategy_weight": strategy_weight,
                    "weighted_weight": weighted_value,
                    "signal_id": target.signal_id,
                    "target_position_id": target.target_position_id,
                }
            )
            if abs(strategy_weight - 1.0) > 1e-12:
                reasons_by_symbol[symbol].append(
                    PortfolioConstraintReason(
                        rule_name="strategy_weight",
                        message=f"applied strategy weight {strategy_weight:.4f} to {target.strategy_id}",
                        before=target.target_weight,
                        after=weighted_value,
                        symbol=symbol,
                    )
                )

        return {
            symbol: _SymbolState(
                timestamp_target=latest_by_symbol[symbol],
                raw_weight=raw_by_symbol[symbol],
                weighted_weight=weighted_by_symbol[symbol],
                strategies=tuple(sorted(strategies_by_symbol[symbol])),
                contributions=tuple(contributions_by_symbol[symbol]),
                reasons=tuple(reasons_by_symbol[symbol]),
            )
            for symbol in weighted_by_symbol
        }

    def _apply_weight_caps(
        self,
        weights: dict[str, float],
        reasons: dict[str, list[PortfolioConstraintReason]],
    ) -> dict[str, float]:
        output = dict(weights)
        for symbol, weight in list(output.items()):
            capped = self.risk_policy.clamp_symbol_weight(weight)
            if abs(capped - weight) > 1e-12:
                reasons[symbol].append(
                    PortfolioConstraintReason(
                        rule_name="max_symbol_weight",
                        message="clamped symbol target weight",
                        before=weight,
                        after=capped,
                        symbol=symbol,
                    )
                )
                output[symbol] = capped

        output = self._scale_to_gross_cap(output, reasons)
        output = self._scale_group_exposure(output, reasons)
        return self._scale_to_gross_cap(output, reasons)

    def _scale_to_gross_cap(
        self,
        weights: dict[str, float],
        reasons: dict[str, list[PortfolioConstraintReason]],
    ) -> dict[str, float]:
        gross = sum(abs(weight) for weight in weights.values())
        gross_cap = self.risk_policy.gross_cap()
        if gross <= gross_cap or gross <= 0:
            return weights
        scale = gross_cap / gross
        scaled = {symbol: weight * scale for symbol, weight in weights.items()}
        for symbol, weight in weights.items():
            reasons[symbol].append(
                PortfolioConstraintReason(
                    rule_name="max_gross_exposure",
                    message="scaled portfolio to gross exposure cap",
                    before=weight,
                    after=scaled[symbol],
                    symbol=symbol,
                )
            )
        return scaled

    def _scale_group_exposure(
        self,
        weights: dict[str, float],
        reasons: dict[str, list[PortfolioConstraintReason]],
    ) -> dict[str, float]:
        if self.config.max_group_weight is None:
            return weights

        output = dict(weights)
        by_group: dict[str, list[str]] = defaultdict(list)
        for symbol in output:
            by_group[self._group_for(symbol)].append(symbol)

        for symbols in by_group.values():
            exposure = sum(abs(output[symbol]) for symbol in symbols)
            if exposure <= self.config.max_group_weight or exposure <= 0:
                continue
            scale = self.config.max_group_weight / exposure
            for symbol in symbols:
                before = output[symbol]
                output[symbol] = before * scale
                reasons[symbol].append(
                    PortfolioConstraintReason(
                        rule_name="max_group_weight",
                        message="scaled group exposure to cap",
                        before=before,
                        after=output[symbol],
                        symbol=symbol,
                    )
                )
        return output

    def _apply_turnover_cap(
        self,
        target_weights: dict[str, float],
        account: AccountState,
        prices: dict[str, float],
        reasons: dict[str, list[PortfolioConstraintReason]],
    ) -> dict[str, float]:
        current_weights = self._current_weights(account, prices)
        scaled_weights, turnover_scale = self.risk_policy.scale_target_weights_for_turnover(current_weights, target_weights)
        if turnover_scale >= 1.0 - 1e-12:
            return scaled_weights

        for symbol, before in target_weights.items():
            after = scaled_weights[symbol]
            if abs(after - before) <= 1e-12:
                continue
            reasons[symbol].append(
                PortfolioConstraintReason(
                    rule_name="max_daily_turnover",
                    message="scaled target change to daily turnover cap",
                    before=before,
                    after=after,
                    symbol=symbol,
                )
            )
        return {symbol: scaled_weights[symbol] for symbol in target_weights}

    def _build_targets(
        self,
        states: dict[str, _SymbolState],
        weights: dict[str, float],
        reasons: dict[str, list[PortfolioConstraintReason]],
    ) -> list[TargetPosition]:
        combined: list[TargetPosition] = []
        for symbol in sorted(weights):
            source = states[symbol].timestamp_target
            strategies = states[symbol].strategies
            combined.append(
                TargetPosition(
                    timestamp_utc=source.timestamp_utc,
                    strategy_id=strategies[0] if len(strategies) == 1 else "portfolio",
                    symbol=symbol,
                    target_weight=weights[symbol],
                    signal_id=source.signal_id,
                    metadata={
                        "raw_weight": states[symbol].raw_weight,
                        "weighted_weight": states[symbol].weighted_weight,
                        "group": self._group_for(symbol),
                        "strategies": list(strategies),
                        "strategy_contributions": list(states[symbol].contributions),
                        "reasons": [reason.__dict__ for reason in reasons[symbol]],
                    },
                )
            )
        return combined

    def _build_intent_decisions(
        self,
        targets: list[TargetPosition],
        intents: list[OrderIntent],
        account: AccountState,
        prices: dict[str, float],
        reasons: dict[str, list[PortfolioConstraintReason]],
    ) -> list[PortfolioIntentDecision]:
        by_symbol = {intent.symbol: intent for intent in intents}
        decisions: list[PortfolioIntentDecision] = []
        equity = max(account.equity, 1.0)
        for target in targets:
            price = float(prices.get(target.symbol, 0.0))
            current_quantity = account.positions.get(target.symbol, Position(symbol=target.symbol)).quantity
            raw_target_quantity = current_quantity
            if price > 0:
                raw_target_quantity = target.metadata.get("weighted_weight", target.target_weight) * equity / price
            raw_delta = raw_target_quantity - current_quantity
            intent = by_symbol.get(target.symbol)
            final_delta = 0.0
            side: OrderSide | None = None
            if intent is not None:
                final_delta = intent.quantity if intent.side == OrderSide.BUY else -intent.quantity
                side = intent.side
            decisions.append(
                PortfolioIntentDecision(
                    symbol=target.symbol,
                    raw_delta_quantity=raw_delta,
                    final_delta_quantity=final_delta,
                    side=side,
                    reasons=tuple(reasons[target.symbol]),
                )
            )
        return decisions

    def _targets_from_order_intents(
        self,
        intents: list[OrderIntent],
        account: AccountState,
        prices: dict[str, float],
    ) -> list[TargetPosition]:
        deltas: dict[str, float] = defaultdict(float)
        latest: dict[str, OrderIntent] = {}
        equity = max(account.equity, 1.0)
        targets: list[TargetPosition] = []

        for intent in intents:
            symbol = intent.symbol.upper()
            direction = 1.0 if intent.side == OrderSide.BUY else -1.0
            strategy_weight = self.config.strategy_weights.get(intent.strategy_id, self.config.default_strategy_weight)
            deltas[symbol] += direction * intent.quantity * strategy_weight
            latest[symbol] = intent

        for symbol, signed_quantity in deltas.items():
            price = float(prices.get(symbol, 0.0))
            current_quantity = account.positions.get(symbol, Position(symbol=symbol)).quantity
            target_quantity = current_quantity + signed_quantity
            target_weight = 0.0
            if price > 0:
                target_weight = target_quantity * price / equity
            source = latest[symbol]
            targets.append(
                TargetPosition(
                    timestamp_utc=source.timestamp_utc,
                    strategy_id="portfolio",
                    symbol=symbol,
                    target_weight=target_weight,
                    target_quantity=target_quantity,
                    signal_id=source.signal_id,
                    metadata={"source": "order_intent_merge", "raw_signed_quantity": signed_quantity},
                )
            )
        return targets

    def _current_weights(self, account: AccountState, prices: dict[str, float]) -> dict[str, float]:
        equity = max(account.equity, 1.0)
        weights: dict[str, float] = {}
        for symbol, position in account.positions.items():
            price = float(prices.get(symbol, position.market_price))
            if price <= 0:
                continue
            weights[symbol.upper()] = position.quantity * price / equity
        return weights

    def _group_for(self, symbol: str) -> str:
        return self.config.group_map.get(symbol.upper(), "ungrouped")


class AllocationCombiner:
    def __init__(self, config: AllocationConfig | None = None) -> None:
        self.config = config or AllocationConfig()
        self._allocator = PortfolioAllocator(self.config)

    def combine(self, targets: list[TargetPosition]) -> list[TargetPosition]:
        return self._allocator.allocate_targets(targets).targets
