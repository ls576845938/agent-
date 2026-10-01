"""Causal, asset-neutral market-state descriptions for research and replay.

This module is intentionally pure.  It owns neither files nor training nor an
execution permission.  Calendar owners feed one expected close at a time; the
bounded stream makes batch, incremental and restored calculations identical.
"""
from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime
import hashlib
import json
import math
from statistics import median, pstdev
from typing import Any, Iterable, Mapping, Sequence

from .model import Bar, digest, utc


STATE_VERSION = "market_state_descriptive_v2"
SNAPSHOT_VERSION = "market_state_stream_snapshot_v2"
OPTIONAL_INPUTS = ("funding", "open_interest", "depth")


def _hex(value: str, length: int, reason: str) -> str:
    if not isinstance(value, str) or len(value) != length or any(c not in "0123456789abcdef" for c in value):
        raise ValueError(reason)
    return value


def _finite(value: Any, reason: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(reason) from exc
    if not math.isfinite(number):
        raise ValueError(reason)
    return number


@dataclass(frozen=True)
class StateSourceBinding:
    data_version: str
    manifest_git_spec: str
    manifest_sha256: str
    aggregate_sha256: str
    source_evidence_hash: str

    def __post_init__(self) -> None:
        if not self.data_version or self.data_version == "latest":
            raise ValueError("state_exact_data_version_required")
        ref, separator, path = self.manifest_git_spec.partition(":")
        if not separator or len(ref) != 40 or not path.startswith(".agent/data_manifests/") or ".." in path:
            raise ValueError("state_manifest_binding_invalid")
        _hex(ref, 40, "state_manifest_binding_invalid")
        for value in (self.manifest_sha256, self.aggregate_sha256, self.source_evidence_hash):
            _hex(value, 64, "state_source_hash_invalid")

    @property
    def binding_hash(self) -> str:
        return digest(asdict(self))


@dataclass(frozen=True)
class StateDefinitionV2:
    horizons: tuple[int, ...] = (24, 72, 168)
    primary_horizon: int = 72
    volatility_history_bars: int = 720
    state_history_bars: int = 72
    minimum_history_observations: int = 24
    calendar: str = "UTC_24x7"
    periods_per_year: int = 8760
    max_age_seconds: int = 3600
    definition_version: str = STATE_VERSION

    def __post_init__(self) -> None:
        if (self.definition_version != STATE_VERSION or not isinstance(self.horizons, tuple)
                or not self.horizons or tuple(sorted(set(self.horizons))) != self.horizons
                or any(type(value) is not int or value < 2 or value > 4096 for value in self.horizons)
                or self.primary_horizon not in self.horizons
                or type(self.volatility_history_bars) is not int
                or type(self.state_history_bars) is not int
                or type(self.minimum_history_observations) is not int
                or self.minimum_history_observations < 2
                or self.volatility_history_bars < self.minimum_history_observations
                or self.state_history_bars < self.minimum_history_observations
                or not self.calendar or self.calendar == "unknown"
                or type(self.periods_per_year) is not int or self.periods_per_year <= 0
                or type(self.max_age_seconds) is not int or self.max_age_seconds <= 0):
            raise ValueError("invalid_state_v2_definition")

    @property
    def definition_hash(self) -> str:
        return digest(asdict(self))


@dataclass(frozen=True)
class MarketStateV2:
    asset: str
    decision_time: datetime
    cutoff_time: datetime
    status: str
    reasons: tuple[str, ...]
    direction_score: float | None
    direction_label: str | None
    normalized_trend_strength: float | None
    path_efficiency_by_horizon: Mapping[str, float | None]
    multi_scale_agreement: float | None
    bar_volatility: float | None
    annualized_volatility: float | None
    volatility_relative_position: float | None
    volatility_expansion_ratio: float | None
    volatility_regime: str | None
    shock_score: float | None
    direction_persistence: float | None
    switching_frequency: float | None
    optional_inputs: Mapping[str, Mapping[str, Any]]
    definition_version: str
    definition_hash: str
    source_binding_hash: str
    input_hash: str
    cache_key: str
    content_hash: str

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["decision_time"] = utc(self.decision_time).isoformat()
        value["cutoff_time"] = utc(self.cutoff_time).isoformat()
        return value


def _optional_inputs(values: Mapping[str, Any] | None, *, decision_time: datetime) -> dict[str, dict[str, Any]]:
    supplied = dict(values or {})
    unknown = sorted(set(supplied) - set(OPTIONAL_INPUTS))
    if unknown:
        raise ValueError("state_optional_input_unknown:" + ",".join(unknown))
    output: dict[str, dict[str, Any]] = {}
    for name in OPTIONAL_INPUTS:
        if name not in supplied or supplied[name] is None:
            output[name] = {"status": "missing", "value": None}
        elif isinstance(supplied[name], Mapping):
            item = supplied[name]
            if set(item) != {"value", "observed_time"}:
                raise ValueError("state_optional_input_contract_invalid")
            observed_time = utc(datetime.fromisoformat(str(item["observed_time"])))
            if observed_time > decision_time:
                raise ValueError("state_optional_input_from_future")
            output[name] = {"status": "observed", "value": _finite(item["value"], "state_optional_input_invalid"),
                            "observed_time": observed_time.isoformat()}
        else:
            output[name] = {"status": "unverified_time", "value": _finite(supplied[name], "state_optional_input_invalid")}
    return output


def _direction(total: float) -> tuple[int, str]:
    if total > 1e-12:
        return 1, "up"
    if total < -1e-12:
        return -1, "down"
    return 0, "flat"


def _percentile_rank(prior: Sequence[float], current: float) -> float:
    below = sum(value < current for value in prior)
    equal = sum(value == current for value in prior)
    return (below + 0.5 * equal) / len(prior)


class CausalStateStreamV2:
    """One asset per instance; memory is bounded by the frozen definition."""

    def __init__(self, *, asset: str, definition: StateDefinitionV2,
                 source: StateSourceBinding) -> None:
        if not asset:
            raise ValueError("state_asset_required")
        self.asset = asset
        self.definition = definition
        self.source = source
        self._bars: deque[dict[str, Any]] = deque(maxlen=max(definition.horizons) + 2)
        self._volatility_history: deque[float] = deque(maxlen=definition.volatility_history_bars)
        self._direction_history: deque[int] = deque(maxlen=definition.state_history_bars)
        self._last_expected_close: datetime | None = None

    def push(self, bar: Bar | None, *, expected_close_time: datetime,
             decision_time: datetime, optional_inputs: Mapping[str, Any] | None = None) -> MarketStateV2:
        expected = utc(expected_close_time)
        decision = utc(decision_time)
        if self._last_expected_close is not None and expected <= self._last_expected_close:
            raise ValueError("state_expected_close_not_strictly_increasing")
        if bar is not None and bar.asset != self.asset:
            raise ValueError("state_asset_mismatch")
        optional = _optional_inputs(optional_inputs, decision_time=decision)
        reasons: list[str] = []
        self._last_expected_close = expected
        if bar is None:
            reasons.append("missing_expected_bar")
        else:
            event, close, available = utc(bar.event_time), utc(bar.close_time), utc(bar.available_time)
            if close != expected:
                reasons.append("missing_expected_bar")
            if event > close or available < close:
                reasons.append("invalid_availability")
            if available > decision or close > decision:
                reasons.append("future_or_unavailable_bar")
            if (decision - available).total_seconds() > self.definition.max_age_seconds:
                reasons.append("stale")
            if not bar.completed:
                reasons.append("incomplete_bar")
            try:
                close_value = _finite(bar.close, "state_invalid_price")
                if close_value <= 0:
                    raise ValueError("state_invalid_price")
            except ValueError:
                reasons.append("invalid_price")
            else:
                if not reasons:
                    self._bars.append({
                        "event_time": event.isoformat(), "close_time": close.isoformat(),
                        "available_time": available.isoformat(), "close": close_value,
                    })

        # A missing or unusable expected bar is a real path discontinuity.  It
        # must not be compressed into a longer return on the next observation.
        # Keep the accepted schedule cursor, but require a fresh bounded warmup.
        if reasons:
            self._bars.clear()
            self._volatility_history.clear()
            self._direction_history.clear()

        metrics: dict[int, dict[str, float | int | str]] = {}
        if len(self._bars) < max(self.definition.horizons) + 1:
            reasons.append("warmup")
        else:
            closes = [row["close"] for row in self._bars]
            returns = [math.log(closes[index] / closes[index - 1]) for index in range(1, len(closes))]
            for horizon in self.definition.horizons:
                values = returns[-horizon:]
                total = sum(values)
                distance = sum(abs(value) for value in values)
                sign, label = _direction(total)
                volatility = pstdev(values)
                efficiency = min(1.0, abs(total) / distance) if distance else 0.0
                scale = volatility * math.sqrt(horizon)
                normalized = abs(math.tanh(total / scale)) if scale > 1e-15 else (1.0 if abs(total) > 1e-12 else 0.0)
                metrics[horizon] = {
                    "total": total, "sign": sign, "label": label,
                    "volatility": volatility, "efficiency": efficiency,
                    "normalized": normalized,
                }

        primary = metrics.get(self.definition.primary_horizon)
        prior_volatility = list(self._volatility_history)
        if primary is not None:
            if len(prior_volatility) < self.definition.minimum_history_observations:
                reasons.append("volatility_history_warmup")
            if len(self._direction_history) + 1 < self.definition.minimum_history_observations:
                reasons.append("state_history_warmup")

        direction_score = normalized_strength = agreement = None
        bar_volatility = annualized = relative = expansion = shock = None
        volatility_regime = persistence = switching = direction_label = None
        if primary is not None:
            primary_sign = int(primary["sign"])
            direction_label = str(primary["label"])
            direction_score = primary_sign * float(primary["efficiency"])
            normalized_strength = float(primary["normalized"])
            nonflat_signs = [int(row["sign"]) for row in metrics.values() if int(row["sign"]) != 0]
            agreement = abs(sum(nonflat_signs)) / len(nonflat_signs) if nonflat_signs else 1.0
            bar_volatility = float(primary["volatility"])
            annualized = bar_volatility * math.sqrt(self.definition.periods_per_year)
            if prior_volatility:
                relative = _percentile_rank(prior_volatility, bar_volatility)
                baseline = median(prior_volatility)
                expansion = bar_volatility / baseline if baseline > 1e-15 else None
                if expansion is not None:
                    volatility_regime = "expanding" if expansion > 1.25 else "contracting" if expansion < 0.8 else "stable"
            closes = [row["close"] for row in self._bars]
            returns = [math.log(closes[index] / closes[index - 1]) for index in range(1, len(closes))]
            prior = returns[-self.definition.primary_horizon:-1]
            prior_sigma = pstdev(prior) if len(prior) > 1 else 0.0
            shock = abs(returns[-1]) / prior_sigma if prior_sigma > 1e-15 else None
            history = list(self._direction_history) + [primary_sign]
            if history:
                persistence = sum(sign == primary_sign for sign in history) / len(history)
                switching = (sum(history[index] != history[index - 1] for index in range(1, len(history))) /
                             (len(history) - 1) if len(history) > 1 else 0.0)

        status = "unknown" if reasons else "observed"
        visible_payload = {
            "asset": self.asset,
            "decision_time": decision.isoformat(),
            "cutoff_time": expected.isoformat(),
            "bars": list(self._bars),
            "volatility_history": prior_volatility,
            "direction_history": list(self._direction_history),
            "optional_inputs": optional,
        }
        input_hash = digest(visible_payload)
        cache_key = digest({
            "data_version": self.source.data_version,
            "definition_hash": self.definition.definition_hash,
            "input_hash": input_hash,
        })
        content = {
            "asset": self.asset, "decision_time": decision.isoformat(),
            "cutoff_time": expected.isoformat(), "status": status,
            "reasons": sorted(set(reasons)), "direction_score": direction_score,
            "direction_label": direction_label,
            "normalized_trend_strength": normalized_strength,
            "path_efficiency_by_horizon": {
                str(horizon): (float(metrics[horizon]["efficiency"]) if horizon in metrics else None)
                for horizon in self.definition.horizons
            },
            "multi_scale_agreement": agreement, "bar_volatility": bar_volatility,
            "annualized_volatility": annualized,
            "volatility_relative_position": relative,
            "volatility_expansion_ratio": expansion,
            "volatility_regime": volatility_regime, "shock_score": shock,
            "direction_persistence": persistence, "switching_frequency": switching,
            "optional_inputs": optional, "definition_version": STATE_VERSION,
            "definition_hash": self.definition.definition_hash,
            "source_binding_hash": self.source.binding_hash,
            "input_hash": input_hash, "cache_key": cache_key,
        }
        content_hash = digest(content)
        observation_payload = dict(content)
        observation_payload.update(
            decision_time=decision,
            cutoff_time=expected,
            reasons=tuple(content["reasons"]),
            content_hash=content_hash,
        )
        observation = MarketStateV2(**observation_payload)
        if primary is not None:
            self._volatility_history.append(float(primary["volatility"]))
            self._direction_history.append(int(primary["sign"]))
        return observation

    def freeze(self) -> dict[str, Any]:
        payload = {
            "schema_version": SNAPSHOT_VERSION,
            "asset": self.asset,
            "definition_hash": self.definition.definition_hash,
            "source_binding_hash": self.source.binding_hash,
            "bars": list(self._bars),
            "volatility_history": list(self._volatility_history),
            "direction_history": list(self._direction_history),
            "last_expected_close": self._last_expected_close.isoformat() if self._last_expected_close else None,
        }
        return {**payload, "snapshot_hash": digest(payload)}

    @classmethod
    def restore(cls, frozen: Mapping[str, Any], *, definition: StateDefinitionV2,
                source: StateSourceBinding) -> "CausalStateStreamV2":
        payload = dict(frozen)
        snapshot_hash = payload.pop("snapshot_hash", None)
        if digest(payload) != snapshot_hash or payload.get("schema_version") != SNAPSHOT_VERSION:
            raise ValueError("state_snapshot_integrity_mismatch")
        if payload.get("definition_hash") != definition.definition_hash:
            raise ValueError("state_definition_mismatch")
        if payload.get("source_binding_hash") != source.binding_hash:
            raise ValueError("state_source_binding_mismatch")
        stream = cls(asset=str(payload.get("asset") or ""), definition=definition, source=source)
        bars = payload.get("bars")
        volatility = payload.get("volatility_history")
        directions = payload.get("direction_history")
        if not isinstance(bars, list) or not isinstance(volatility, list) or not isinstance(directions, list):
            raise ValueError("state_snapshot_shape_invalid")
        if len(bars) > stream._bars.maxlen or len(volatility) > stream._volatility_history.maxlen or len(directions) > stream._direction_history.maxlen:
            raise ValueError("state_snapshot_unbounded")
        parsed_bars = []
        prior_close_time = None
        for row in bars:
            if not isinstance(row, Mapping) or set(row) != {"event_time", "close_time", "available_time", "close"}:
                raise ValueError("state_snapshot_bar_shape_invalid")
            try:
                event = utc(datetime.fromisoformat(str(row["event_time"])))
                close_time = utc(datetime.fromisoformat(str(row["close_time"])))
                available = utc(datetime.fromisoformat(str(row["available_time"])))
            except (TypeError, ValueError) as exc:
                raise ValueError("state_snapshot_bar_time_invalid") from exc
            close_value = _finite(row["close"], "state_snapshot_bar_value_invalid")
            if close_value <= 0 or event > close_time or available < close_time or (prior_close_time and close_time <= prior_close_time):
                raise ValueError("state_snapshot_bar_causality_invalid")
            prior_close_time = close_time
            parsed_bars.append({"event_time": event.isoformat(), "close_time": close_time.isoformat(),
                                "available_time": available.isoformat(), "close": close_value})
        parsed_volatility = [_finite(value, "state_snapshot_value_invalid") for value in volatility]
        if any(value < 0 for value in parsed_volatility):
            raise ValueError("state_snapshot_value_invalid")
        if any(type(value) is not int or value not in {-1, 0, 1} for value in directions):
            raise ValueError("state_snapshot_direction_invalid")
        last = payload.get("last_expected_close")
        try:
            parsed_last = utc(datetime.fromisoformat(last)) if last else None
        except (TypeError, ValueError) as exc:
            raise ValueError("state_snapshot_last_time_invalid") from exc
        if parsed_bars and parsed_last != datetime.fromisoformat(parsed_bars[-1]["close_time"]):
            raise ValueError("state_snapshot_last_time_mismatch")
        stream._bars.extend(parsed_bars)
        stream._volatility_history.extend(parsed_volatility)
        stream._direction_history.extend(directions)
        stream._last_expected_close = parsed_last
        return stream


def batch_estimate_v2(bars: Sequence[Bar | None], *, expected_close_times: Sequence[datetime],
                      definition: StateDefinitionV2, source: StateSourceBinding,
                      optional_inputs: Sequence[Mapping[str, Any] | None] | None = None) -> list[MarketStateV2]:
    if len(bars) != len(expected_close_times):
        raise ValueError("state_batch_length_mismatch")
    if optional_inputs is not None and len(optional_inputs) != len(bars):
        raise ValueError("state_optional_batch_length_mismatch")
    asset = next((bar.asset for bar in bars if bar is not None), None)
    if not asset:
        raise ValueError("state_asset_required")
    stream = CausalStateStreamV2(asset=asset, definition=definition, source=source)
    output: list[MarketStateV2] = []
    for index, (bar, expected) in enumerate(zip(bars, expected_close_times)):
        decision = bar.available_time if bar is not None else expected
        supplied = None if optional_inputs is None else optional_inputs[index]
        output.append(stream.push(bar, expected_close_time=expected,
                                  decision_time=decision, optional_inputs=supplied))
    return output
