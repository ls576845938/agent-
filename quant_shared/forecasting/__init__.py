"""Shared forecasting contracts and optional model adapters."""

from quant_shared.forecasting.contracts import (
    ForecastModelAdapter,
    ForecastQualityEvidence,
    ForecastQuantile,
    ForecastUsage,
    ModelUnavailableError,
    TimeSeriesForecastRequest,
    TimeSeriesForecastResult,
)
from quant_shared.forecasting.baseline_adapter import DriftForecastAdapter

__all__ = [
    "DriftForecastAdapter",
    "ForecastModelAdapter",
    "ForecastQualityEvidence",
    "ForecastQuantile",
    "ForecastUsage",
    "ModelUnavailableError",
    "TimeSeriesForecastRequest",
    "TimeSeriesForecastResult",
]
