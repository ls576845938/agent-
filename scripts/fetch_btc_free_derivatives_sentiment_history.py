#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from quant_crypto.data.free_derivatives_sources import (
    HOUR_MS,
    fetch_binance_free_derivatives_payloads,
    fetch_okx_free_derivatives_payloads,
    normalize_binance_derivatives_sentiment_rows,
    normalize_okx_derivatives_sentiment_rows,
)
from scripts.build_btc_derivatives_sentiment_report import build_btc_derivatives_sentiment_report_file
from scripts.build_btc_derivatives_strategy_gate_report import build_btc_derivatives_strategy_gate_report_file


DEFAULT_ROWS = Path("data/external/btc_derivatives_sentiment/free_sources/free_public_btcusdt_1h_latest/derivatives_sentiment_1h.json")
DEFAULT_AUDIT = Path("artifacts/btc_derivatives_sentiment/latest/btc_free_derivatives_history_fetch_report.json")


def fetch_btc_free_derivatives_sentiment_history(
    *,
    rows_output: Path = DEFAULT_ROWS,
    audit_output: Path = DEFAULT_AUDIT,
    symbol: str = "BTCUSDT",
    lookback_hours: int = 744,
    execute_network: bool = False,
    generated_at_utc: datetime | None = None,
    sleep_seconds: float = 0.1,
) -> dict:
    generated_at = generated_at_utc or datetime.now(timezone.utc)
    end_hour = int((generated_at - timedelta(hours=1)).timestamp() * 1000) // HOUR_MS * HOUR_MS
    start_hour = end_hour - (lookback_hours - 1) * HOUR_MS
    if not execute_network:
        payload = _audit_payload(
            status="planned",
            generated_at=generated_at,
            rows_output=rows_output,
            row_count=0,
            lookback_hours=lookback_hours,
            start_hour=start_hour,
            end_hour=end_hour,
            blockers=[],
            network_called=False,
        )
        _write_json(audit_output, payload)
        return payload
    provider = "binance_usdm_free_public"
    fallback_errors: list[str] = []
    try:
        raw = fetch_binance_free_derivatives_payloads(
            symbol=symbol,
            start_hour_ms=start_hour,
            end_hour_ms=end_hour,
            sleep_seconds=sleep_seconds,
        )
        rows = normalize_binance_derivatives_sentiment_rows(
            open_interest_hist=raw["open_interest_hist"],
            long_short_ratio=raw["long_short_ratio"],
            funding_rates=raw["funding_rates"],
            force_orders=raw["force_orders"],
            start_hour_ms=start_hour,
            end_hour_ms=end_hour,
            generated_at_utc=generated_at,
            symbol=symbol,
        )
    except Exception as exc:  # noqa: BLE001 - fallback is recorded in the audit artifact.
        fallback_errors.append(f"binance_usdm_free_public_failed:{type(exc).__name__}:{exc}")
        provider = "okx_free_public"
        try:
            raw = fetch_okx_free_derivatives_payloads(
                symbol=symbol,
                start_hour_ms=start_hour,
                end_hour_ms=end_hour,
                sleep_seconds=sleep_seconds,
            )
            rows = normalize_okx_derivatives_sentiment_rows(
                open_interest_volume=raw["open_interest_volume"],
                long_short_ratio=raw["long_short_ratio"],
                funding_rates=raw["funding_rates"],
                liquidation_orders=raw["liquidation_orders"],
                start_hour_ms=start_hour,
                end_hour_ms=end_hour,
                generated_at_utc=generated_at,
                symbol=symbol,
            )
        except Exception as fallback_exc:  # noqa: BLE001 - fail closed into audit artifact.
            fallback_errors.append(f"okx_free_public_failed:{type(fallback_exc).__name__}:{fallback_exc}")
            payload = _audit_payload(
                status="blocked",
                generated_at=generated_at,
                rows_output=rows_output,
                row_count=0,
                lookback_hours=lookback_hours,
                start_hour=start_hour,
                end_hour=end_hour,
                blockers=["btc_free_derivatives_history_fetch_failed_all_public_sources"],
                network_called=True,
            )
            payload["provider"] = "none"
            payload["fallback_errors"] = fallback_errors
            payload["raw_counts"] = {}
            payload["field_non_null_counts"] = _field_non_null_counts([])
            _write_json(audit_output, payload)
            return payload
    _write_json(rows_output, {"rows": rows})
    sentiment = build_btc_derivatives_sentiment_report_file(
        rows_path=rows_output,
        provider=provider,
        generated_at_utc=generated_at,
        decision_time_utc=generated_at,
        min_rows_for_strategy_gate=720,
    )
    gate = build_btc_derivatives_strategy_gate_report_file(generated_at_utc=generated_at)
    blockers = []
    if len(rows) < 720:
        blockers.append("btc_free_derivatives_history_rows_below_720")
    if sentiment.get("status") != "complete":
        blockers.append("btc_free_derivatives_sentiment_gate_not_complete")
    payload = _audit_payload(
        status="complete" if not blockers else "blocked",
        generated_at=generated_at,
        rows_output=rows_output,
        row_count=len(rows),
        lookback_hours=lookback_hours,
        start_hour=start_hour,
        end_hour=end_hour,
        blockers=blockers,
        network_called=True,
    )
    payload["provider"] = provider
    payload["fallback_errors"] = fallback_errors
    payload["raw_counts"] = {key: len(value) for key, value in raw.items()}
    payload["field_non_null_counts"] = _field_non_null_counts(rows)
    payload["sentiment_status"] = sentiment.get("status")
    payload["strategy_gate_status"] = gate.get("status")
    _write_json(audit_output, payload)
    return payload


def _audit_payload(
    *,
    status: str,
    generated_at: datetime,
    rows_output: Path,
    row_count: int,
    lookback_hours: int,
    start_hour: int,
    end_hour: int,
    blockers: list[str],
    network_called: bool,
) -> dict:
    return {
        "schema_version": "btc_free_derivatives_history_fetch_report_v1",
        "status": status,
        "generated_at": generated_at.isoformat(),
        "network_called": network_called,
        "public_market_data_only": True,
        "api_key_used": False,
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "rows_output": str(rows_output).replace("\\", "/"),
        "row_count": row_count,
        "lookback_hours": lookback_hours,
        "sample_start": datetime.fromtimestamp(start_hour / 1000, tz=timezone.utc).isoformat(),
        "sample_end": datetime.fromtimestamp(end_hour / 1000, tz=timezone.utc).isoformat(),
        "blockers": blockers,
    }


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _field_non_null_counts(rows: list[dict]) -> dict[str, int]:
    fields = (
        "open_interest_usd",
        "funding_rate",
        "long_liquidation_usd",
        "short_liquidation_usd",
        "long_short_ratio",
    )
    return {field: sum(1 for row in rows if row.get(field) is not None) for field in fields}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows-output", type=Path, default=DEFAULT_ROWS)
    parser.add_argument("--audit-output", type=Path, default=DEFAULT_AUDIT)
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--lookback-hours", type=int, default=744)
    parser.add_argument("--execute-network", action="store_true")
    parser.add_argument("--sleep-seconds", type=float, default=0.1)
    args = parser.parse_args()
    payload = fetch_btc_free_derivatives_sentiment_history(
        rows_output=args.rows_output,
        audit_output=args.audit_output,
        symbol=args.symbol,
        lookback_hours=args.lookback_hours,
        execute_network=args.execute_network,
        sleep_seconds=args.sleep_seconds,
    )
    print(json.dumps({"status": payload["status"], "row_count": payload["row_count"], "blockers": payload["blockers"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
