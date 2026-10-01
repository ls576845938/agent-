from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping, Protocol, Sequence


FORECASTING_CONTRACT_VERSION = "shared_forecasting_v1"


class ForecastUsage(str, Enum):
    RESEARCH_ONLY = "research_only"
    RISK_AUXILIARY = "risk_auxiliary"


class ModelUnavailableError(RuntimeError):
    """Raised when an optional forecasting backend is not available."""


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _as_usage(value: ForecastUsage | str) -> ForecastUsage:
    if isinstance(value, ForecastUsage):
        return value
    try:
        return ForecastUsage(str(value))
    except ValueError as exc:
        raise ValueError(
            "Forecast usage must be research_only or risk_auxiliary; "
            "paper/live/OMS usage is not allowed by this contract."
        ) from exc


def _immutable_metadata(value: Mapping[str, Any] | None) -> dict[str, Any]:
    return dict(value or {})


@dataclass(frozen=True)
class ForecastQualityEvidence:
    sample_size: int = 0
    oos_ic: float | None = None
    hit_rate: float | None = None
    max_drawdown: float | None = None
    evidence_path: str = ""
    evidence_hash: str = ""
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "sample_size", int(self.sample_size))
        if self.sample_size < 0:
            raise ValueError("sample_size must be non-negative.")
        for field_name in ["oos_ic", "hit_rate", "max_drawdown"]:
            value = getattr(self, field_name)
            if value is not None and not math.isfinite(float(value)):
                raise ValueError(f"{field_name} must be finite when provided.")
        object.__setattr__(self, "notes", tuple(str(item) for item in self.notes))

    @property
    def has_oos_evidence(self) -> bool:
        return self.sample_size > 0 and (self.oos_ic is not None or self.hit_rate is not None)


@dataclass(frozen=True)
class ForecastQuantile:
    step: int
    quantile: float
    value: float

    def __post_init__(self) -> None:
        step = int(self.step)
        quantile = float(self.quantile)
        value = float(self.value)
        if step <= 0:
            raise ValueError("quantile step must be positive.")
        if not 0.0 < quantile < 1.0:
            raise ValueError("quantile must be in (0, 1).")
        if not math.isfinite(value):
            raise ValueError("quantile value must be finite.")
        object.__setattr__(self, "step", step)
        object.__setattr__(self, "quantile", quantile)
        object.__setattr__(self, "value", value)


@dataclass(frozen=True)
class TimeSeriesForecastRequest:
    instrument_id: str
    decision_time_utc: datetime
    history_timestamps_utc: Sequence[datetime]
    history_values: Sequence[float]
    horizon_steps: int
    frequency: str
    asset_namespace: str = "shared"
    series_name: str = "close"
    allowed_usage: ForecastUsage | str = ForecastUsage.RESEARCH_ONLY
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        decision_time = ensure_utc(self.decision_time_utc)
        timestamps = tuple(ensure_utc(item) for item in self.history_timestamps_utc)
        values = tuple(float(item) for item in self.history_values)
        usage = _as_usage(self.allowed_usage)

        if not self.instrument_id:
            raise ValueError("instrument_id is required.")
        if not self.asset_namespace:
            raise ValueError("asset_namespace is required.")
        if not self.series_name:
            raise ValueError("series_name is required.")
        if not self.frequency:
            raise ValueError("frequency is required.")
        if int(self.horizon_steps) <= 0:
            raise ValueError("horizon_steps must be positive.")
        if len(timestamps) != len(values):
            raise ValueError("history timestamps and values must have the same length.")
        if len(values) < 2:
            raise ValueError("at least two historical observations are required.")

        previous: datetime | None = None
        for timestamp, value in zip(timestamps, values):
            if previous is not None and timestamp <= previous:
                raise ValueError("history timestamps must be strictly increasing.")
            if timestamp > decision_time:
                raise ValueError("history contains observations after decision_time.")
            if not math.isfinite(value):
                raise ValueError("history values must be finite.")
            previous = timestamp

        object.__setattr__(self, "decision_time_utc", decision_time)
        object.__setattr__(self, "history_timestamps_utc", timestamps)
        object.__setattr__(self, "history_values", values)
        object.__setattr__(self, "horizon_steps", int(self.horizon_steps))
        object.__setattr__(self, "instrument_id", self.instrument_id.upper())
        object.__setattr__(self, "asset_namespace", str(self.asset_namespace))
        object.__setattr__(self, "series_name", str(self.series_name))
        object.__setattr__(self, "frequency", str(self.frequency))
        object.__setattr__(self, "allowed_usage", usage)
        object.__setattr__(self, "metadata", _immutable_metadata(self.metadata))

    @property
    def visible_history_end_time_utc(self) -> datetime:
        return self.history_timestamps_utc[-1]


@dataclass(frozen=True)
class TimeSeriesForecastResult:
    request: TimeSeriesForecastRequest
    model_id: str
    model_version: str
    generated_at_utc: datetime
    point_forecast: Sequence[float]
    quantiles: Sequence[ForecastQuantile] = ()
    confidence: float | None = None
    quality: ForecastQualityEvidence = field(default_factory=ForecastQualityEvidence)
    metadata: Mapping[str, Any] = field(default_factory=dict)
    paper_queue_write_allowed: bool = False
    live_unlock_allowed: bool = False
    order_intent_allowed: bool = False

    def __post_init__(self) -> None:
        generated_at = ensure_utc(self.generated_at_utc)
        point_forecast = tuple(float(item) for item in self.point_forecast)
        quantiles = tuple(self.quantiles)
        if not self.model_id:
            raise ValueError("model_id is required.")
        if not self.model_version:
            raise ValueError("model_version is required.")
        if len(point_forecast) != self.request.horizon_steps:
            raise ValueError("point_forecast length must equal request.horizon_steps.")
        for value in point_forecast:
            if not math.isfinite(value):
                raise ValueError("point_forecast values must be finite.")
        if self.confidence is not None:
            confidence = float(self.confidence)
            if not 0.0 <= confidence <= 1.0:
                raise ValueError("confidence must be in [0, 1].")
            object.__setattr__(self, "confidence", confidence)
        if self.paper_queue_write_allowed or self.live_unlock_allowed or self.order_intent_allowed:
            raise ValueError("shared forecasting results cannot write paper/live/order outputs.")
        object.__setattr__(self, "generated_at_utc", generated_at)
        object.__setattr__(self, "point_forecast", point_forecast)
        object.__setattr__(self, "quantiles", quantiles)
        object.__setattr__(self, "metadata", _immutable_metadata(self.metadata))

    def to_audit_dict(self) -> dict[str, Any]:
        return {
            "schema_version": FORECASTING_CONTRACT_VERSION,
            "asset_namespace": self.request.asset_namespace,
            "instrument_id": self.request.instrument_id,
            "series_name": self.request.series_name,
            "decision_time_utc": self.request.decision_time_utc.isoformat(),
            "visible_history_end_time_utc": self.request.visible_history_end_time_utc.isoformat(),
            "frequency": self.request.frequency,
            "horizon_steps": self.request.horizon_steps,
            "allowed_usage": self.request.allowed_usage.value,
            "model_id": self.model_id,
            "model_version": self.model_version,
            "generated_at_utc": self.generated_at_utc.isoformat(),
            "point_forecast": list(self.point_forecast),
            "quantiles": [
                {"step": item.step, "quantile": item.quantile, "value": item.value}
                for item in self.quantiles
            ],
            "confidence": self.confidence,
            "quality": {
                "sample_size": self.quality.sample_size,
                "oos_ic": self.quality.oos_ic,
                "hit_rate": self.quality.hit_rate,
                "max_drawdown": self.quality.max_drawdown,
                "evidence_path": self.quality.evidence_path,
                "evidence_hash": self.quality.evidence_hash,
                "has_oos_evidence": self.quality.has_oos_evidence,
                "notes": list(self.quality.notes),
            },
            "safety_flags": {
                "paper_queue_write_allowed": self.paper_queue_write_allowed,
                "live_unlock_allowed": self.live_unlock_allowed,
                "order_intent_allowed": self.order_intent_allowed,
            },
            "metadata": dict(self.metadata),
        }


class ForecastModelAdapter(Protocol):
    model_id: str
    model_version: str

    def forecast(self, request: TimeSeriesForecastRequest) -> TimeSeriesForecastResult:
        """Return a research/risk auxiliary forecast without trading side effects."""
