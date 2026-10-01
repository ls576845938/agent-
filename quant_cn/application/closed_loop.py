"""Pure Signal -> Forecast -> TargetPosition orchestration."""

from __future__ import annotations

from quant_cn.strategy.contracts import (
    DecisionChain,
    DecisionSnapshot,
    Forecast,
    ForecastModel,
    Signal,
    Strategy,
    TargetBuilder,
    TargetPosition,
)


def build_decision_chain(
    *,
    strategy: Strategy,
    forecast_model: ForecastModel,
    target_builder: TargetBuilder,
    snapshot: DecisionSnapshot,
    current_quantity: int,
    capacity_quantity: int,
) -> DecisionChain:
    signal = strategy.generate_signal(snapshot)
    if not isinstance(signal, Signal):
        raise TypeError("strategy_must_return_signal")
    forecast = forecast_model.forecast(signal, snapshot)
    if not isinstance(forecast, Forecast):
        raise TypeError("forecast_model_must_return_forecast")
    target = target_builder.build_target(
        forecast,
        snapshot,
        current_quantity=current_quantity,
        capacity_quantity=capacity_quantity,
    )
    if not isinstance(target, TargetPosition):
        raise TypeError("target_builder_must_return_target_position")
    return DecisionChain(snapshot=snapshot, signal=signal, forecast=forecast, target=target)
