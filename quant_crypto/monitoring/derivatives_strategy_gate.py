from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from quant_crypto.monitoring.artifact_schema import apply_btc_artifact_schema, stable_payload_hash


BTC_DERIVATIVES_STRATEGY_GATE_VERSION = "btc_derivatives_strategy_gate_v1"


def build_btc_derivatives_strategy_gate(
    *,
    derivatives_sentiment_report: Mapping[str, Any],
    generated_at_utc: datetime,
    strategy_ids: list[str] | None = None,
    source_report_path: Path = Path("artifacts/btc_derivatives_sentiment/latest/btc_derivatives_sentiment_report.json"),
) -> dict[str, Any]:
    blockers: list[str] = []
    strategy_ids = strategy_ids or [
        "btc_trend_raw_t01_twelve_month_momentum",
        "btc_pullback_reclaim_intraday_high_vol_non_expansion_trend_guard_v1",
    ]
    if derivatives_sentiment_report.get("status") != "complete":
        blockers.append("btc_derivatives_strategy_gate_sentiment_data_not_complete")
    if not _mapping(derivatives_sentiment_report.get("strategy_enhancement")).get("enabled_for_alpha_claims"):
        blockers.append("btc_derivatives_strategy_gate_alpha_claims_not_enabled")
    features = _mapping(derivatives_sentiment_report.get("features"))
    if not features.get("feature_available"):
        blockers.append("btc_derivatives_strategy_gate_features_unavailable")
    if not strategy_ids:
        blockers.append("btc_derivatives_strategy_gate_strategy_ids_missing")
    payload = {
        "derivatives_strategy_gate_version": BTC_DERIVATIVES_STRATEGY_GATE_VERSION,
        "status": "complete" if not blockers else "blocked",
        "source_report_path": str(source_report_path).replace("\\", "/"),
        "candidate_strategy_ids": strategy_ids,
        "feature_contract": {
            "feature_set": "btc_derivatives_crowding_v1",
            "inputs": [
                "open_interest_usd",
                "funding_rate",
                "long_liquidation_usd",
                "short_liquidation_usd",
                "long_short_ratio",
            ],
            "derived_features": [
                "open_interest_z_24",
                "funding_rate_z_24",
                "liquidation_shock_z_24",
                "long_short_pressure",
                "crowding_score",
                "risk_state",
            ],
            "allowed_strategy_uses": [
                "risk_filter",
                "position_size_modifier",
                "crowding_regime_feature",
                "liquidation_shock_recovery_hypothesis",
            ],
            "forbidden_until_forward_observation": [
                "paper_promotion",
                "live_promotion",
                "order_endpoint_access",
            ],
        },
        "latest_feature_snapshot": features,
        "blockers": _dedupe(blockers),
    }
    return apply_btc_artifact_schema(
        payload,
        decision="derivatives_strategy_enhancement_ready"
        if not blockers
        else "derivatives_strategy_enhancement_blocked",
        generated_at_utc=generated_at_utc,
        as_of_utc=generated_at_utc,
        blockers=_dedupe(blockers),
        warnings=[],
        input_hashes={"derivatives_sentiment_report": stable_payload_hash(dict(derivatives_sentiment_report))},
    )


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result
