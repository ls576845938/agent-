from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from quant_shared.core.time import ensure_utc

from quant_crypto.data.pit_contract import parse_utc
from quant_crypto.monitoring.artifact_schema import apply_btc_artifact_schema, stable_payload_hash


BTC_DERIVATIVES_SENTIMENT_VERSION = "btc_derivatives_sentiment_v1"
REQUIRED_ROLES = ("open_interest", "funding_rate", "liquidation", "long_short_ratio")
FEATURE_FIELDS = (
    "open_interest_usd",
    "funding_rate",
    "long_liquidation_usd",
    "short_liquidation_usd",
    "long_short_ratio",
)


@dataclass(frozen=True)
class BTCDerivativesSentimentRow:
    event_time: datetime
    available_time: datetime
    ingested_at: datetime
    processed_at: datetime
    venue: str
    symbol: str
    source_provider: str
    is_final: bool
    open_interest_usd: float | None = None
    funding_rate: float | None = None
    long_liquidation_usd: float | None = None
    short_liquidation_usd: float | None = None
    long_short_ratio: float | None = None
    source_raw_payload_hash: str = ""

    @classmethod
    def from_mapping(cls, row: Mapping[str, Any]) -> "BTCDerivativesSentimentRow":
        return cls(
            event_time=parse_utc(row.get("event_time")),
            available_time=parse_utc(row.get("available_time")),
            ingested_at=parse_utc(row.get("ingested_at")),
            processed_at=parse_utc(row.get("processed_at")),
            venue=str(row.get("venue") or ""),
            symbol=str(row.get("symbol") or ""),
            source_provider=str(row.get("source_provider") or ""),
            is_final=_bool(row.get("is_final")),
            open_interest_usd=_optional_float(row.get("open_interest_usd")),
            funding_rate=_optional_float(row.get("funding_rate")),
            long_liquidation_usd=_optional_float(row.get("long_liquidation_usd")),
            short_liquidation_usd=_optional_float(row.get("short_liquidation_usd")),
            long_short_ratio=_optional_float(row.get("long_short_ratio")),
            source_raw_payload_hash=str(row.get("source_raw_payload_hash") or ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_time": self.event_time.isoformat(),
            "available_time": self.available_time.isoformat(),
            "ingested_at": self.ingested_at.isoformat(),
            "processed_at": self.processed_at.isoformat(),
            "venue": self.venue,
            "symbol": self.symbol,
            "source_provider": self.source_provider,
            "is_final": self.is_final,
            "open_interest_usd": self.open_interest_usd,
            "funding_rate": self.funding_rate,
            "long_liquidation_usd": self.long_liquidation_usd,
            "short_liquidation_usd": self.short_liquidation_usd,
            "long_short_ratio": self.long_short_ratio,
            "source_raw_payload_hash": self.source_raw_payload_hash,
        }


def build_btc_derivatives_sentiment_report(
    *,
    rows: list[Mapping[str, Any]],
    generated_at_utc: datetime,
    decision_time_utc: datetime,
    source_path: Path,
    provider: str = "coinglass_or_equivalent",
    min_rows_for_strategy_gate: int = 720,
) -> dict[str, Any]:
    parsed_rows: list[BTCDerivativesSentimentRow] = []
    blockers: list[str] = []
    for index, raw in enumerate(rows):
        try:
            parsed_rows.append(BTCDerivativesSentimentRow.from_mapping(raw))
        except (TypeError, ValueError) as exc:
            blockers.append(f"btc_derivatives_sentiment_row_invalid:{index}:{type(exc).__name__}")
    parsed_rows.sort(key=lambda item: item.event_time)
    quality = _quality_report(parsed_rows)
    features = build_btc_derivatives_sentiment_features(parsed_rows, decision_time_utc=decision_time_utc)
    blockers.extend(quality["blockers"])
    if len(parsed_rows) < min_rows_for_strategy_gate:
        blockers.append("btc_derivatives_sentiment_history_too_short_for_strategy_gate")
    if not features["feature_available"]:
        blockers.append("btc_derivatives_sentiment_feature_unavailable")

    strategy_enhancement_ready = not blockers
    payload = {
        "derivatives_sentiment_version": BTC_DERIVATIVES_SENTIMENT_VERSION,
        "status": "complete" if strategy_enhancement_ready else "blocked",
        "provider": provider,
        "source_path": str(source_path).replace("\\", "/"),
        "row_count": len(parsed_rows),
        "min_rows_for_strategy_gate": min_rows_for_strategy_gate,
        "quality": quality,
        "features": features,
        "strategy_enhancement": {
            "enabled_for_alpha_claims": strategy_enhancement_ready,
            "allowed_uses": [
                "risk_filter",
                "position_size_modifier",
                "crowding_regime_feature",
                "liquidation_shock_recovery_hypothesis",
            ],
            "forbidden_uses_until_gate": [
                "live_order_unlock",
                "paper_candidate_promotion_without_forward_observation",
                "using_vendor_publication_time_after_decision_time",
            ],
        },
        "blockers": _dedupe(blockers),
    }
    return apply_btc_artifact_schema(
        payload,
        decision="derivatives_sentiment_strategy_gate_ready"
        if strategy_enhancement_ready
        else "derivatives_sentiment_data_gate_blocked",
        generated_at_utc=generated_at_utc,
        as_of_utc=decision_time_utc,
        blockers=_dedupe(blockers),
        warnings=[],
        input_hashes={"rows": stable_payload_hash({"rows": [row.to_dict() for row in parsed_rows]})},
    )


def build_btc_derivatives_sentiment_features(
    rows: list[BTCDerivativesSentimentRow],
    *,
    decision_time_utc: datetime,
) -> dict[str, Any]:
    decision_time = ensure_utc(decision_time_utc)
    visible = [row for row in rows if row.available_time <= decision_time and row.is_final]
    if not visible:
        return {
            "feature_available": False,
            "visible_row_count": 0,
            "latest_event_time": None,
            "crowding_score": None,
            "risk_state": "blocked",
            "signals": {},
            "blockers": ["btc_derivatives_sentiment_no_visible_final_rows"],
        }
    latest = visible[-1]
    prior = visible[:-1]
    oi_window = [row.open_interest_usd for row in prior[-24:] if row.open_interest_usd is not None]
    funding_window = [row.funding_rate for row in prior[-24:] if row.funding_rate is not None]
    liquidation_window = [
        (row.long_liquidation_usd or 0.0) + (row.short_liquidation_usd or 0.0)
        for row in prior[-24:]
        if row.long_liquidation_usd is not None or row.short_liquidation_usd is not None
    ]
    oi_z = _zscore(latest.open_interest_usd, oi_window)
    funding_z = _zscore(latest.funding_rate, funding_window)
    liquidation_total = (latest.long_liquidation_usd or 0.0) + (latest.short_liquidation_usd or 0.0)
    liquidation_z = _zscore(liquidation_total, liquidation_window)
    long_short_pressure = None if latest.long_short_ratio is None else latest.long_short_ratio - 1.0
    components = [value for value in (oi_z, funding_z, liquidation_z, long_short_pressure) if value is not None]
    crowding_score = round(sum(components) / len(components), 6) if components else None
    risk_state = _risk_state(crowding_score=crowding_score, liquidation_z=liquidation_z, funding_z=funding_z)
    return {
        "feature_available": crowding_score is not None,
        "visible_row_count": len(visible),
        "latest_event_time": latest.event_time.isoformat(),
        "latest_available_time": latest.available_time.isoformat(),
        "crowding_score": crowding_score,
        "risk_state": risk_state,
        "signals": {
            "open_interest_z_24": oi_z,
            "funding_rate_z_24": funding_z,
            "liquidation_shock_z_24": liquidation_z,
            "long_short_pressure": None if long_short_pressure is None else round(long_short_pressure, 6),
        },
        "blockers": [] if crowding_score is not None else ["btc_derivatives_sentiment_feature_components_missing"],
    }


def _quality_report(rows: list[BTCDerivativesSentimentRow]) -> dict[str, Any]:
    blockers: list[str] = []
    if not rows:
        blockers.append("btc_derivatives_sentiment_no_rows")
    if any(row.symbol != "BTCUSDT" for row in rows):
        blockers.append("btc_derivatives_sentiment_symbol_not_btcusdt")
    if any(not row.venue for row in rows):
        blockers.append("btc_derivatives_sentiment_venue_missing")
    if any(not row.source_provider for row in rows):
        blockers.append("btc_derivatives_sentiment_source_provider_missing")
    if any(row.available_time < row.event_time for row in rows):
        blockers.append("btc_derivatives_sentiment_available_time_before_event_time")
    if any(not row.is_final for row in rows):
        blockers.append("btc_derivatives_sentiment_non_final_rows_present")
    event_times = [row.event_time for row in rows]
    if event_times != sorted(event_times):
        blockers.append("btc_derivatives_sentiment_event_time_not_monotonic")
    if len(set(event_times)) != len(event_times):
        blockers.append("btc_derivatives_sentiment_duplicate_event_time")
    role_coverage = {
        "open_interest": any(row.open_interest_usd is not None for row in rows),
        "funding_rate": any(row.funding_rate is not None for row in rows),
        "liquidation": any(
            row.long_liquidation_usd is not None or row.short_liquidation_usd is not None for row in rows
        ),
        "long_short_ratio": any(row.long_short_ratio is not None for row in rows),
    }
    for role, present in role_coverage.items():
        if not present:
            blockers.append(f"btc_derivatives_sentiment_role_missing:{role}")
    if any(row.source_raw_payload_hash and not _looks_like_sha256(row.source_raw_payload_hash) for row in rows):
        blockers.append("btc_derivatives_sentiment_raw_payload_hash_invalid")
    return {
        "pit_required": True,
        "role_coverage": role_coverage,
        "monotonic_time_pass": "btc_derivatives_sentiment_event_time_not_monotonic" not in blockers,
        "duplicate_time_check_pass": "btc_derivatives_sentiment_duplicate_event_time" not in blockers,
        "finalization_pass": "btc_derivatives_sentiment_non_final_rows_present" not in blockers,
        "source_hash_present_ratio": _ratio(
            sum(1 for row in rows if row.source_raw_payload_hash),
            len(rows),
        ),
        "blockers": _dedupe(blockers),
    }


def _zscore(value: float | None, history: list[float | None]) -> float | None:
    if value is None:
        return None
    clean = [float(item) for item in history if item is not None]
    if len(clean) < 2:
        return None
    mean = sum(clean) / len(clean)
    variance = sum((item - mean) ** 2 for item in clean) / (len(clean) - 1)
    if variance <= 0:
        return 0.0
    return round((float(value) - mean) / (variance**0.5), 6)


def _risk_state(*, crowding_score: float | None, liquidation_z: float | None, funding_z: float | None) -> str:
    if crowding_score is None:
        return "blocked"
    if liquidation_z is not None and liquidation_z >= 3.0:
        return "liquidation_shock"
    if funding_z is not None and funding_z >= 2.0 and crowding_score >= 1.5:
        return "crowded_long_risk"
    if funding_z is not None and funding_z <= -2.0 and crowding_score <= -1.5:
        return "crowded_short_risk"
    if abs(crowding_score) >= 1.5:
        return "crowded"
    return "normal"


def _optional_float(value: Any) -> float | None:
    if value in {None, ""}:
        return None
    return float(value)


def _bool(value: Any) -> bool:
    if value is True:
        return True
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes"}
    return bool(value)


def _ratio(numerator: int, denominator: int) -> float:
    return 0.0 if denominator <= 0 else round(numerator / denominator, 6)


def _looks_like_sha256(value: str) -> bool:
    return len(value) == 64 and all(char in "0123456789abcdefABCDEF" for char in value)


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result
