#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from quant_crypto.data.binance_vision_derivatives import (
    build_binance_vision_derivatives_audit,
    build_binance_vision_derivatives_sentiment_rows,
    default_date_window,
    fetch_binance_vision_funding_rows,
    fetch_binance_vision_metrics_rows,
    fetch_github_daily_liquidation_diagnostics,
    read_derivatives_rows,
    write_derivatives_rows,
)
from scripts.build_btc_derivatives_sentiment_report import build_btc_derivatives_sentiment_report_file
from scripts.build_btc_derivatives_strategy_gate_report import build_btc_derivatives_strategy_gate_report_file


DEFAULT_ROWS_OUTPUT = Path(
    "data/external/btc_derivatives_sentiment/free_sources/free_public_btcusdt_1h_latest/"
    "derivatives_sentiment_1h.json"
)
DEFAULT_OKX_TAIL_ROWS = DEFAULT_ROWS_OUTPUT
DEFAULT_RAW_DIR = Path("data/external/btc_derivatives_sentiment/free_sources/binance_vision_btcusdt/raw_archives")
DEFAULT_AUDIT_OUTPUT = Path("artifacts/btc_derivatives_sentiment/latest/btc_binance_vision_derivatives_fetch_report.json")


def fetch_btc_binance_vision_derivatives_sentiment(
    *,
    rows_output: Path = DEFAULT_ROWS_OUTPUT,
    okx_tail_rows_path: Path = DEFAULT_OKX_TAIL_ROWS,
    raw_dir: Path = DEFAULT_RAW_DIR,
    audit_output: Path = DEFAULT_AUDIT_OUTPUT,
    lookback_days: int = 180,
    execute_network: bool = False,
    generated_at_utc: datetime | None = None,
    sleep_seconds: float = 0.02,
    request_timeout_seconds: int = 30,
    progress_every: int = 0,
    execute_github_diagnostic: bool = True,
    network_route_label: str = "",
) -> dict:
    generated_at = generated_at_utc or datetime.now(timezone.utc)
    start_day, end_day = default_date_window(generated_at_utc=generated_at, lookback_days=lookback_days)
    okx_tail_rows = read_derivatives_rows(okx_tail_rows_path)
    if not execute_network:
        audit = build_binance_vision_derivatives_audit(
            rows=[],
            generated_at_utc=generated_at,
            metrics_raw_count=0,
            funding_raw_count=0,
            okx_tail_raw_count=len(okx_tail_rows),
            github_daily_liquidation_diagnostics={},
            download_attempts=[],
            rows_output=rows_output,
            network_route_label=network_route_label,
        )
        audit.update(
            {
                "status": "planned",
                "blockers": [],
                "lookback_days": lookback_days,
                "sample_start_date": start_day.isoformat(),
                "sample_end_date": end_day.isoformat(),
                "network_called": False,
            }
        )
        _write_json(audit_output, audit)
        return audit

    metrics_rows, metrics_attempts = fetch_binance_vision_metrics_rows(
        start_date=start_day,
        end_date=end_day,
        raw_dir=raw_dir,
        sleep_seconds=sleep_seconds,
        request_timeout_seconds=request_timeout_seconds,
        progress_every=progress_every,
    )
    funding_rows, funding_attempts = fetch_binance_vision_funding_rows(
        start_date=start_day,
        end_date=end_day,
        raw_dir=raw_dir,
        sleep_seconds=sleep_seconds,
        request_timeout_seconds=request_timeout_seconds,
        progress_every=progress_every,
    )
    github_diagnostics = fetch_github_daily_liquidation_diagnostics() if execute_github_diagnostic else {}
    result = build_binance_vision_derivatives_sentiment_rows(
        metrics_rows_5m=metrics_rows,
        funding_rows=funding_rows,
        okx_tail_rows=okx_tail_rows,
        generated_at_utc=generated_at,
    )
    write_derivatives_rows(rows_output, result.rows)
    sentiment = build_btc_derivatives_sentiment_report_file(
        rows_path=rows_output,
        provider="binance_vision_metrics_5m_hourly_okx_tail",
        generated_at_utc=generated_at,
        decision_time_utc=generated_at,
        min_rows_for_strategy_gate=720,
    )
    gate = build_btc_derivatives_strategy_gate_report_file(generated_at_utc=generated_at)
    audit = build_binance_vision_derivatives_audit(
        rows=result.rows,
        generated_at_utc=generated_at,
        metrics_raw_count=len(metrics_rows),
        funding_raw_count=len(funding_rows),
        okx_tail_raw_count=len(okx_tail_rows),
        github_daily_liquidation_diagnostics=github_diagnostics,
        download_attempts=[*metrics_attempts, *funding_attempts],
        rows_output=rows_output,
        network_route_label=network_route_label,
    )
    blockers = list(audit.get("blockers", []))
    if sentiment.get("status") != "complete":
        blockers.append("btc_binance_vision_derivatives_sentiment_report_not_complete")
    if gate.get("status") != "complete":
        blockers.append("btc_binance_vision_derivatives_strategy_gate_not_complete")
    audit.update(
        {
            "status": "complete" if not blockers else "blocked",
            "blockers": blockers,
            "lookback_days": lookback_days,
            "sample_start_date": start_day.isoformat(),
            "sample_end_date": end_day.isoformat(),
            "sentiment_status": sentiment.get("status"),
            "strategy_gate_status": gate.get("status"),
        }
    )
    _write_json(audit_output, audit)
    return audit


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows-output", type=Path, default=DEFAULT_ROWS_OUTPUT)
    parser.add_argument("--okx-tail-rows-path", type=Path, default=DEFAULT_OKX_TAIL_ROWS)
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW_DIR)
    parser.add_argument("--audit-output", type=Path, default=DEFAULT_AUDIT_OUTPUT)
    parser.add_argument("--lookback-days", type=int, default=180)
    parser.add_argument("--execute-network", action="store_true")
    parser.add_argument("--sleep-seconds", type=float, default=0.02)
    parser.add_argument("--request-timeout-seconds", type=int, default=30)
    parser.add_argument("--progress-every", type=int, default=0)
    parser.add_argument("--skip-github-diagnostic", action="store_true")
    parser.add_argument("--network-route-label", default="")
    args = parser.parse_args()
    payload = fetch_btc_binance_vision_derivatives_sentiment(
        rows_output=args.rows_output,
        okx_tail_rows_path=args.okx_tail_rows_path,
        raw_dir=args.raw_dir,
        audit_output=args.audit_output,
        lookback_days=args.lookback_days,
        execute_network=args.execute_network,
        sleep_seconds=args.sleep_seconds,
        request_timeout_seconds=args.request_timeout_seconds,
        progress_every=args.progress_every,
        execute_github_diagnostic=not args.skip_github_diagnostic,
        network_route_label=args.network_route_label,
    )
    print(
        json.dumps(
            {
                "status": payload["status"],
                "row_count": payload["row_count"],
                "field_non_null_counts": payload["field_non_null_counts"],
                "extra_field_non_null_counts": payload["extra_field_non_null_counts"],
                "blockers": payload["blockers"],
                "rows_output": str(args.rows_output).replace("\\", "/"),
                "audit_output": str(args.audit_output).replace("\\", "/"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
