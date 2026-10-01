from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from quant_crypto.data.derivatives_sentiment import (
    BTCDerivativesSentimentRow,
    build_btc_derivatives_sentiment_features,
    build_btc_derivatives_sentiment_report,
)
from quant_crypto.monitoring.artifact_schema import validate_btc_artifact_schema
from scripts.build_btc_derivatives_sentiment_report import build_btc_derivatives_sentiment_report_file


TS = datetime(2026, 6, 27, 0, 0, tzinfo=timezone.utc)
HASH = "a" * 64


def _row(ts: datetime, index: int, *, is_final: bool = True) -> dict[str, object]:
    return {
        "event_time": ts.isoformat(),
        "available_time": (ts + timedelta(minutes=2)).isoformat(),
        "ingested_at": (ts + timedelta(minutes=3)).isoformat(),
        "processed_at": (ts + timedelta(minutes=4)).isoformat(),
        "venue": "okx",
        "symbol": "BTCUSDT",
        "source_provider": "coinglass_or_equivalent",
        "is_final": is_final,
        "open_interest_usd": 10_000_000_000 + index * 1_000_000,
        "funding_rate": 0.0001 + index * 0.000001,
        "long_liquidation_usd": 1_000_000 + index * 10_000,
        "short_liquidation_usd": 900_000 + index * 8_000,
        "long_short_ratio": 1.0 + index * 0.002,
        "source_raw_payload_hash": HASH,
    }


def test_derivatives_sentiment_blocks_missing_rows_without_promoting_strategy(tmp_path: Path) -> None:
    payload = build_btc_derivatives_sentiment_report(
        rows=[],
        generated_at_utc=TS,
        decision_time_utc=TS,
        source_path=tmp_path / "missing.json",
    )

    assert payload["status"] == "blocked"
    assert payload["strategy_enhancement"]["enabled_for_alpha_claims"] is False
    assert "btc_derivatives_sentiment_no_rows" in payload["blockers"]
    assert validate_btc_artifact_schema(payload) == []


def test_derivatives_sentiment_requires_pit_finalized_all_roles_and_history(tmp_path: Path) -> None:
    rows = [_row(TS, 0, is_final=False)]
    payload = build_btc_derivatives_sentiment_report(
        rows=rows,
        generated_at_utc=TS,
        decision_time_utc=TS + timedelta(hours=1),
        source_path=tmp_path / "rows.json",
    )

    assert payload["status"] == "blocked"
    assert "btc_derivatives_sentiment_non_final_rows_present" in payload["blockers"]
    assert "btc_derivatives_sentiment_history_too_short_for_strategy_gate" in payload["blockers"]


def test_derivatives_sentiment_can_build_visible_crowding_features() -> None:
    rows = [
        BTCDerivativesSentimentRow.from_mapping(_row(TS + timedelta(hours=index), index))
        for index in range(30)
    ]
    features = build_btc_derivatives_sentiment_features(
        rows,
        decision_time_utc=TS + timedelta(hours=30),
    )

    assert features["feature_available"] is True
    assert features["visible_row_count"] == 30
    assert features["crowding_score"] is not None
    assert features["risk_state"] in {"normal", "crowded", "crowded_long_risk", "liquidation_shock"}
    assert features["signals"]["open_interest_z_24"] is not None
    assert features["signals"]["funding_rate_z_24"] is not None


def test_derivatives_sentiment_strategy_gate_passes_only_with_enough_history(tmp_path: Path) -> None:
    rows = [_row(TS + timedelta(hours=index), index) for index in range(32)]
    payload = build_btc_derivatives_sentiment_report(
        rows=rows,
        generated_at_utc=TS + timedelta(hours=32),
        decision_time_utc=TS + timedelta(hours=32),
        source_path=tmp_path / "rows.json",
        min_rows_for_strategy_gate=30,
    )

    assert payload["status"] == "complete"
    assert payload["decision"] == "derivatives_sentiment_strategy_gate_ready"
    assert payload["strategy_enhancement"]["enabled_for_alpha_claims"] is True
    assert payload["blockers"] == []


def test_build_script_writes_sample_as_blocked_diagnostic_until_history_is_long_enough(tmp_path: Path) -> None:
    output = tmp_path / "report.json"
    sample = tmp_path / "sample.json"
    payload = build_btc_derivatives_sentiment_report_file(
        rows_path=sample,
        output=output,
        generated_at_utc=TS,
        decision_time_utc=TS,
        write_sample=True,
    )

    assert output.exists()
    assert sample.exists()
    assert payload["status"] == "blocked"
    assert "btc_derivatives_sentiment_history_too_short_for_strategy_gate" in payload["blockers"]
