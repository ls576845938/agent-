from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from quant_crypto.data.derivatives_sentiment import build_btc_derivatives_sentiment_report
from quant_crypto.monitoring.artifact_schema import validate_btc_artifact_schema
from quant_crypto.monitoring.derivatives_strategy_gate import build_btc_derivatives_strategy_gate
from scripts.build_btc_derivatives_strategy_gate_report import build_btc_derivatives_strategy_gate_report_file


TS = datetime(2026, 6, 27, 0, 0, tzinfo=timezone.utc)


def _row(ts: datetime, index: int) -> dict[str, object]:
    return {
        "event_time": ts.isoformat(),
        "available_time": (ts + timedelta(minutes=2)).isoformat(),
        "ingested_at": (ts + timedelta(minutes=3)).isoformat(),
        "processed_at": (ts + timedelta(minutes=4)).isoformat(),
        "venue": "okx",
        "symbol": "BTCUSDT",
        "source_provider": "coinglass_or_equivalent",
        "is_final": True,
        "open_interest_usd": 10_000_000_000 + index * 1_000_000,
        "funding_rate": 0.0001 + index * 0.000001,
        "long_liquidation_usd": 1_000_000 + index * 10_000,
        "short_liquidation_usd": 900_000 + index * 8_000,
        "long_short_ratio": 1.0 + index * 0.002,
        "source_raw_payload_hash": "a" * 64,
    }


def test_derivatives_strategy_gate_blocks_when_sentiment_data_not_complete(tmp_path: Path) -> None:
    source = build_btc_derivatives_sentiment_report(
        rows=[],
        generated_at_utc=TS,
        decision_time_utc=TS,
        source_path=tmp_path / "missing.json",
    )
    payload = build_btc_derivatives_strategy_gate(
        derivatives_sentiment_report=source,
        generated_at_utc=TS,
    )

    assert payload["status"] == "blocked"
    assert "btc_derivatives_strategy_gate_sentiment_data_not_complete" in payload["blockers"]
    assert validate_btc_artifact_schema(payload) == []


def test_derivatives_strategy_gate_passes_with_complete_sentiment_contract(tmp_path: Path) -> None:
    rows = [_row(TS + timedelta(hours=index), index) for index in range(32)]
    source = build_btc_derivatives_sentiment_report(
        rows=rows,
        generated_at_utc=TS + timedelta(hours=32),
        decision_time_utc=TS + timedelta(hours=32),
        source_path=tmp_path / "rows.json",
        min_rows_for_strategy_gate=30,
    )
    payload = build_btc_derivatives_strategy_gate(
        derivatives_sentiment_report=source,
        generated_at_utc=TS + timedelta(hours=32),
    )

    assert payload["status"] == "complete"
    assert payload["decision"] == "derivatives_strategy_enhancement_ready"
    assert payload["feature_contract"]["feature_set"] == "btc_derivatives_crowding_v1"
    assert payload["blockers"] == []


def test_derivatives_strategy_gate_script_reads_report_and_writes_blocked_gate(tmp_path: Path) -> None:
    source_path = tmp_path / "sentiment.json"
    output = tmp_path / "gate.json"
    source = build_btc_derivatives_sentiment_report(
        rows=[],
        generated_at_utc=TS,
        decision_time_utc=TS,
        source_path=tmp_path / "missing.json",
    )
    source_path.write_text(__import__("json").dumps(source), encoding="utf-8")

    payload = build_btc_derivatives_strategy_gate_report_file(input_path=source_path, output=output, generated_at_utc=TS)

    assert output.exists()
    assert payload["status"] == "blocked"
