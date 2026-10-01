from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone

from quant_shared.forecasting.contracts import TimeSeriesForecastRequest, TimeSeriesForecastResult


@dataclass(frozen=True)
class DriftForecastAdapter:
    """Deterministic research-only adapter for shared forecasting smoke tests."""

    lookback_steps: int = 20
    max_step_return_abs: float = 0.05
    model_id: str = "shared_drift_baseline"
    model_version: str = "v1"

    def __post_init__(self) -> None:
        if int(self.lookback_steps) < 1:
            raise ValueError("lookback_steps must be positive.")
        if float(self.max_step_return_abs) <= 0.0:
            raise ValueError("max_step_return_abs must be positive.")

    def forecast(self, request: TimeSeriesForecastRequest) -> TimeSeriesForecastResult:
        values = tuple(float(item) for item in request.history_values)
        window = values[-(int(self.lookback_steps) + 1) :]
        last_value = values[-1]
        step_return = 0.0
        if len(window) >= 2 and window[0] > 0.0 and last_value > 0.0:
            raw_step_return = (last_value / window[0]) ** (1.0 / (len(window) - 1)) - 1.0
            if math.isfinite(raw_step_return):
                cap = float(self.max_step_return_abs)
                step_return = max(-cap, min(cap, raw_step_return))
        forecast = [last_value * ((1.0 + step_return) ** step) for step in range(1, request.horizon_steps + 1)]
        return TimeSeriesForecastResult(
            request=request,
            model_id=self.model_id,
            model_version=self.model_version,
            generated_at_utc=datetime.now(timezone.utc),
            point_forecast=forecast,
            confidence=None,
            metadata={
                "adapter_boundary": "research_or_risk_auxiliary_only",
                "lookback_steps": int(self.lookback_steps),
                "max_step_return_abs": float(self.max_step_return_abs),
                "method": "geometric_drift_from_visible_history",
            },
        )
