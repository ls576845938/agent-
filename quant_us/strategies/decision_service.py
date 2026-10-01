from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace

from quant_shared.strategy_runtime import (
    StrategyDecisionCapability,
    StrategyStateKey,
    StrategyStateSnapshot,
    StrategyStateStore,
)
from quant_us.core.events import MarketEvent
from quant_us.core.types import Signal, TargetPosition
from quant_us.strategies.base import Strategy, StrategyContext, StrategyDecision


class StrategyDecisionContractError(RuntimeError):
    pass


@dataclass(frozen=True)
class AppliedStrategyDecision:
    context: StrategyContext
    signals: tuple[Signal, ...]
    target_positions: tuple[TargetPosition, ...]
    state: StrategyStateSnapshot
    duplicate: bool = False


class StrategyDecisionService:
    """Bind identity/state, evaluate one strategy, then CAS-commit its transition."""

    def __init__(self, state_store: StrategyStateStore) -> None:
        self.state_store = state_store

    def decide(
        self,
        strategy: Strategy,
        event: MarketEvent,
        base_context: StrategyContext,
    ) -> AppliedStrategyDecision:
        strategy_id = str(
            getattr(strategy, "strategy_id", "") or type(strategy).__name__
        ).strip()
        strategy_version = str(
            getattr(strategy, "version", "") or "unbound_strategy_version"
        ).strip()
        bound_identity = replace(
            base_context.identity,
            strategy_id=strategy_id,
            strategy_version=strategy_version,
        )
        key = StrategyStateKey(
            run_id=base_context.identity.run_id,
            strategy_id=strategy_id,
            identity_digest=bound_identity.digest,
        )
        current_state = self.state_store.load(key)
        context = base_context.for_strategy(
            strategy_id=strategy_id,
            strategy_version=strategy_version,
            state=current_state,
        )
        decision_id = self._decision_id(event, context)
        if current_state.last_decision_id == decision_id:
            return AppliedStrategyDecision(
                context=context,
                signals=(),
                target_positions=(),
                state=current_state,
                duplicate=True,
            )
        decide = getattr(strategy, "decide", None)
        if callable(decide):
            decision = decide(event, context)
        else:
            on_bar = getattr(strategy, "on_bar", None)
            if not callable(on_bar):
                raise StrategyDecisionContractError(
                    "strategy must expose decide() or on_bar()"
                )
            decision = StrategyDecision(signals=tuple(on_bar(event, context)))
        if not isinstance(decision, StrategyDecision):
            raise StrategyDecisionContractError(
                "strategy.decide must return StrategyDecision"
            )
        self._validate_outputs(decision, context)
        transition = decision.state_transition or current_state.transition(
            current_state.payload,
            reason="strategy_decision_watermark",
        )
        if transition.key != key:
            raise StrategyDecisionContractError(
                "strategy transition identity does not match bound context"
            )
        transition = replace(
            transition,
            decision_id=decision_id,
            transition_id="",
        )
        next_state = self.state_store.apply(transition)
        return AppliedStrategyDecision(
            context=context,
            signals=decision.signals,
            target_positions=decision.target_positions,
            state=next_state,
        )

    @staticmethod
    def _decision_id(event: MarketEvent, context: StrategyContext) -> str:
        bar = event.bar
        payload = {
            "identity_digest": context.identity.digest,
            "event_type": str(event.event_type.value),
            "event_time": event.timestamp_utc.isoformat(),
            "bar": None,
        }
        if bar is not None:
            payload["bar"] = {
                "timestamp_utc": bar.timestamp_utc.isoformat(),
                "symbol": bar.symbol,
                "open": float(bar.open),
                "high": float(bar.high),
                "low": float(bar.low),
                "close": float(bar.close),
                "volume": float(bar.volume),
                "vwap": None if bar.vwap is None else float(bar.vwap),
                "trade_count": bar.trade_count,
                "source": bar.source,
                "bar_size": bar.bar_size,
                "session": bar.session,
                "adjusted": bool(bar.adjusted),
            }
        canonical = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()

    @staticmethod
    def _validate_outputs(
        decision: StrategyDecision,
        context: StrategyContext,
    ) -> None:
        if decision.signals and (
            StrategyDecisionCapability.SIGNAL not in context.capabilities
        ):
            raise StrategyDecisionContractError("signal output capability denied")
        if decision.target_positions and (
            StrategyDecisionCapability.TARGET_POSITION not in context.capabilities
        ):
            raise StrategyDecisionContractError(
                "target_position output capability denied"
            )
        if any(not isinstance(signal, Signal) for signal in decision.signals):
            raise StrategyDecisionContractError("signals must contain Signal values")
        if any(
            not isinstance(target, TargetPosition)
            for target in decision.target_positions
        ):
            raise StrategyDecisionContractError(
                "target_positions must contain TargetPosition values"
            )
        decision_time = context.clock.decision_time
        if decision_time is not None:
            for output in (*decision.signals, *decision.target_positions):
                if output.timestamp_utc > decision_time:
                    raise StrategyDecisionContractError(
                        "strategy output timestamp is later than decision_time"
                    )
