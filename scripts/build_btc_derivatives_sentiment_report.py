#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from quant_crypto.data.derivatives_sentiment import build_btc_derivatives_sentiment_report


DEFAULT_OUTPUT = Path("artifacts/btc_derivatives_sentiment/latest/btc_derivatives_sentiment_report.json")


def build_btc_derivatives_sentiment_report_file(
    *,
    rows_path: Path | None = None,
    output: Path = DEFAULT_OUTPUT,
    provider: str = "coinglass_or_equivalent",
    generated_at_utc: datetime | None = None,
    decision_time_utc: datetime | None = None,
    min_rows_for_strategy_gate: int = 720,
    write_sample: bool = False,
) -> dict[str, Any]:
    generated_at = generated_at_utc or datetime.now(timezone.utc)
    decision_time = decision_time_utc or generated_at
    if write_sample:
        rows_path = rows_path or Path("artifacts/btc_derivatives_sentiment/latest/btc_derivatives_sentiment.sample.json")
        _write_sample_rows(rows_path, generated_at)
    rows = _read_rows(rows_path) if rows_path is not None else []
    payload = build_btc_derivatives_sentiment_report(
        rows=rows,
        generated_at_utc=generated_at,
        decision_time_utc=decision_time,
        source_path=rows_path or Path("missing_derivatives_sentiment_rows.json"),
        provider=provider,
        min_rows_for_strategy_gate=min_rows_for_strategy_gate,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return payload


def _read_rows(path: Path | None) -> list[Mapping[str, Any]]:
    if path is None or not path.exists():
        return []
    if path.suffix.lower() == ".csv":
        with path.open(newline="", encoding="utf-8") as handle:
            return [dict(row) for row in csv.DictReader(handle)]
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, Mapping)]
    if isinstance(payload, Mapping) and isinstance(payload.get("rows"), list):
        return [row for row in payload["rows"] if isinstance(row, Mapping)]
    return []


def _write_sample_rows(path: Path, end_time: datetime) -> None:
    rows = []
    start = end_time - timedelta(hours=47)
    for index in range(48):
        event_time = start + timedelta(hours=index)
        available_time = event_time + timedelta(minutes=2)
        rows.append(
            {
                "event_time": event_time.isoformat(),
                "available_time": available_time.isoformat(),
                "ingested_at": (available_time + timedelta(seconds=5)).isoformat(),
                "processed_at": (available_time + timedelta(seconds=10)).isoformat(),
                "venue": "okx",
                "symbol": "BTCUSDT",
                "source_provider": "coinglass_or_equivalent_sample",
                "is_final": True,
                "open_interest_usd": 10_000_000_000 + index * 1_000_000,
                "funding_rate": 0.0001 + index * 0.000001,
                "long_liquidation_usd": 1_000_000 + index * 10_000,
                "short_liquidation_usd": 900_000 + index * 8_000,
                "long_short_ratio": 1.0 + index * 0.002,
                "source_raw_payload_hash": "a" * 64,
            }
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"rows": rows}, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--provider", default="coinglass_or_equivalent")
    parser.add_argument("--generated-at", default="")
    parser.add_argument("--decision-time", default="")
    parser.add_argument("--min-rows-for-strategy-gate", type=int, default=720)
    parser.add_argument("--write-sample", action="store_true")
    args = parser.parse_args()
    generated_at = datetime.fromisoformat(args.generated_at.replace("Z", "+00:00")) if args.generated_at else None
    decision_time = datetime.fromisoformat(args.decision_time.replace("Z", "+00:00")) if args.decision_time else None
    payload = build_btc_derivatives_sentiment_report_file(
        rows_path=args.rows,
        output=args.output,
        provider=args.provider,
        generated_at_utc=generated_at,
        decision_time_utc=decision_time,
        min_rows_for_strategy_gate=args.min_rows_for_strategy_gate,
        write_sample=args.write_sample,
    )
    print(json.dumps({"output": str(args.output), "status": payload["status"], "blockers": payload["blockers"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
