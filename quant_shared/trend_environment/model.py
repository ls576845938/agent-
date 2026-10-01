"""A frozen rolling efficiency/volatility baseline, not a learned probability model.

Calendar owners supply expected closes and annualization. No downloads, state,
feature injection, fitting, trading permission or implicit market defaults here.
"""
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
from statistics import pstdev
from typing import Sequence

MODEL_VERSION = "trend_environment_descriptive_v1"


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timezone_aware_time_required")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class Bar:
    asset: str
    event_time: datetime
    close_time: datetime
    available_time: datetime
    close: float
    completed: bool = True


@dataclass(frozen=True)
class EnvironmentConfig:
    horizons: tuple[int, ...]
    calendar: str
    periods_per_year: int
    max_age_seconds: int

    def __post_init__(self):
        if (not isinstance(self.horizons, tuple) or not self.horizons or len(set(self.horizons)) != len(self.horizons)
            or any(type(n) is not int or not 2 <= n <= 512 for n in self.horizons)
            or not self.calendar or self.calendar == "unknown"
            or type(self.periods_per_year) is not int or self.periods_per_year <= 0
            or type(self.max_age_seconds) is not int or self.max_age_seconds <= 0):
            raise ValueError("invalid_environment_configuration")

    @property
    def config_hash(self):
        return digest(asdict(self))


def estimate(bars: Sequence[Bar], *, asset: str, decision_time: datetime,
             expected_close_times: Sequence[datetime], config: EnvironmentConfig) -> list[dict]:
    """Read only completed, visible history for one asset at one decision.

    Future values, other assets and later calendar entries never enter rolling
    values or their hashes. Explicit schedule gaps cannot be compressed away.
    """
    decision = utc(decision_time)
    if not asset: raise ValueError("asset_identity_required")
    relevant = [b for b in bars if b.asset == asset]
    visible = [b for b in relevant if utc(b.available_time) <= decision and utc(b.close_time) <= decision and b.completed]
    schedule = sorted(set(utc(t) for t in expected_close_times if utc(t) <= decision))
    global_reasons = []
    times = [utc(b.close_time) for b in visible]
    if times != sorted(set(times)): global_reasons.append("duplicate_or_unordered")
    if any(utc(b.event_time) > utc(b.close_time) or utc(b.available_time) < utc(b.close_time) for b in visible):
        global_reasons.append("invalid_availability")
    if not visible or not schedule: global_reasons.append("missing_data")
    if visible and (decision - utc(visible[-1].available_time)).total_seconds() > config.max_age_seconds:
        global_reasons.append("stale")
    output = []
    for horizon in config.horizons:
        window = visible[-(horizon+2):]
        required = schedule[-(horizon+1):]
        reasons = list(global_reasons)
        if [utc(b.close_time) for b in visible[-len(required):]] != required:
            reasons.append("missing_expected_bar")
        if len(window) < horizon+2: reasons.append("warmup")
        if any(not math.isfinite(b.close) or b.close <= 0 for b in window): reasons.append("invalid_price")
        identity = {"asset": asset, "decision_time": decision.isoformat(), "horizon_bars": horizon,
                    "model_version": MODEL_VERSION, "config_hash": config.config_hash, "calendar": config.calendar}
        row = {**identity, "status": "unknown" if reasons else "observed", "reasons": sorted(set(reasons)),
               "usage": "observation_only", "direction": None, "trend_fit": None,
               "bar_volatility": None, "annualized_volatility": None, "shock_score": None,
               "transition_score": None, "input_hash": None}
        if not reasons:
            returns = [math.log(window[i].close / window[i-1].close) for i in range(1, len(window))]
            def direction(values):
                total = sum(values)
                return "up" if total > 1e-12 else "down" if total < -1e-12 else "flat"
            def fit(values):
                distance = sum(abs(r) for r in values)
                return min(1., abs(sum(values)) / distance) if distance else 0.
            current, previous = returns[-horizon:], returns[-horizon-1:-1]
            volatility = pstdev(current)
            prior_volatility = pstdev(previous)
            row.update(direction=direction(current), trend_fit=fit(current), bar_volatility=volatility,
                       annualized_volatility=volatility * math.sqrt(config.periods_per_year),
                       shock_score=abs(current[-1]) / prior_volatility if prior_volatility > 1e-12 else None,
                       transition_score=max(abs(fit(current)-fit(previous)), float(direction(current) != direction(previous))))
            if prior_volatility <= 1e-12: row["reasons"].append("shock_unidentified_zero_variance")
            row["input_hash"] = digest({**identity, "bars": [[utc(b.event_time).isoformat(), utc(b.close_time).isoformat(),
                utc(b.available_time).isoformat(), b.close] for b in window], "expected": [t.isoformat() for t in required]})
        output.append(row)
    return output
