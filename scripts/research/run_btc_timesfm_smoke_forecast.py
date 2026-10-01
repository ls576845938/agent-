from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Sequence

from quant_shared.forecasting.contracts import ForecastUsage, TimeSeriesForecastRequest
from quant_shared.forecasting.timesfm_adapter import (
    TIMESFM_DEFAULT_CHECKPOINT,
    TimesFMForecastAdapter,
    inspect_timesfm_environment,
)


SCHEMA_VERSION = "btc_timesfm_1h_smoke_forecast_v1"
DEFAULT_DB_PATH = Path("data/market_data.sqlite")
DEFAULT_OUTPUT_DIR = Path("artifacts/shared_forecasting/timesfm/btc_1h_smoke_latest")


@dataclass(frozen=True)
class KlineRow:
    exchange: str
    symbol: str
    interval: str
    open_time_utc: datetime
    close_time_utc: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


def parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def ceil_to_patch_multiple(value: int, patch: int = 32) -> int:
    value = int(value)
    if value <= 0:
        raise ValueError("value must be positive.")
    return ((value + patch - 1) // patch) * patch


def load_latest_completed_klines(
    *,
    db_path: Path,
    exchange: str,
    symbol: str,
    interval: str,
    lookback_hours: int,
    decision_time_utc: datetime | None = None,
) -> list[KlineRow]:
    if not db_path.exists():
        raise FileNotFoundError(f"market data sqlite not found: {db_path}")
    if lookback_hours < 2:
        raise ValueError("lookback_hours must be >= 2.")

    conn = sqlite3.connect(db_path)
    try:
        params: list[Any] = [exchange, symbol.upper(), interval]
        decision_clause = ""
        if decision_time_utc is not None:
            decision_time_utc = decision_time_utc.astimezone(timezone.utc)
            decision_clause = "and close_time <= ?"
            params.append(decision_time_utc.isoformat())
        params.append(int(lookback_hours))
        rows = conn.execute(
            f"""
            select exchange, symbol, interval, open_time, close_time, open, high, low, close, volume
            from market_klines
            where exchange = ?
              and upper(symbol) = ?
              and interval = ?
              {decision_clause}
            order by open_time_ms desc
            limit ?
            """,
            params,
        ).fetchall()
    finally:
        conn.close()

    klines = [
        KlineRow(
            exchange=str(row[0]),
            symbol=str(row[1]).upper(),
            interval=str(row[2]),
            open_time_utc=parse_utc(str(row[3])),
            close_time_utc=parse_utc(str(row[4])),
            open=float(row[5]),
            high=float(row[6]),
            low=float(row[7]),
            close=float(row[8]),
            volume=float(row[9]),
        )
        for row in reversed(rows)
    ]
    if len(klines) < lookback_hours:
        raise ValueError(f"insufficient BTC 1H rows: need {lookback_hours}, got {len(klines)}.")
    return klines


def summarize_input_rows(rows: Sequence[KlineRow]) -> dict[str, Any]:
    gaps: list[dict[str, Any]] = []
    for previous, current in zip(rows, rows[1:]):
        delta_seconds = (current.close_time_utc - previous.close_time_utc).total_seconds()
        if abs(delta_seconds - 3600.0) > 0.01:
            gaps.append(
                {
                    "previous_close_time_utc": previous.close_time_utc.isoformat(),
                    "current_close_time_utc": current.close_time_utc.isoformat(),
                    "delta_seconds": delta_seconds,
                }
            )
    payload = [
        {
            "close_time_utc": row.close_time_utc.isoformat(),
            "close": row.close,
            "volume": row.volume,
        }
        for row in rows
    ]
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return {
        "row_count": len(rows),
        "first_open_time_utc": rows[0].open_time_utc.isoformat(),
        "last_close_time_utc": rows[-1].close_time_utc.isoformat(),
        "close_min": min(row.close for row in rows),
        "close_max": max(row.close for row in rows),
        "close_last": rows[-1].close,
        "volume_sum": sum(row.volume for row in rows),
        "hourly_gap_count": len(gaps),
        "hourly_gap_sample": gaps[:5],
        "input_sha256": digest,
    }


def build_forecast_rows(result: Any, last_close_time_utc: datetime) -> list[dict[str, Any]]:
    quantiles_by_step: dict[int, dict[str, float]] = {}
    for item in result.quantiles:
        quantiles_by_step.setdefault(item.step, {})[f"q{int(item.quantile * 100):02d}"] = item.value
    forecast_rows: list[dict[str, Any]] = []
    for index, value in enumerate(result.point_forecast, start=1):
        forecast_rows.append(
            {
                "step": index,
                "forecast_time_utc": (last_close_time_utc + timedelta(hours=index)).isoformat(),
                "point_forecast_close": value,
                "quantiles": quantiles_by_step.get(index, {}),
            }
        )
    return forecast_rows


def write_forecast_csv(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    quantile_keys = sorted({key for row in rows for key in row["quantiles"].keys()})
    fieldnames = ["step", "forecast_time_utc", "point_forecast_close", *quantile_keys]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            flattened = {
                "step": row["step"],
                "forecast_time_utc": row["forecast_time_utc"],
                "point_forecast_close": row["point_forecast_close"],
            }
            flattened.update(row["quantiles"])
            writer.writerow(flattened)


def run_btc_timesfm_smoke_forecast(
    *,
    db_path: Path = DEFAULT_DB_PATH,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    exchange: str = "binance_spot",
    symbol: str = "BTCUSDT",
    interval: str = "1h",
    lookback_hours: int = 720,
    horizon_hours: int = 24,
    checkpoint_repo_id: str = TIMESFM_DEFAULT_CHECKPOINT,
) -> dict[str, Any]:
    generated_at = datetime.now(timezone.utc)
    rows = load_latest_completed_klines(
        db_path=db_path,
        exchange=exchange,
        symbol=symbol,
        interval=interval,
        lookback_hours=lookback_hours,
    )
    input_summary = summarize_input_rows(rows)
    request = TimeSeriesForecastRequest(
        asset_namespace="btc",
        instrument_id=symbol,
        series_name="close",
        frequency=interval,
        decision_time_utc=rows[-1].close_time_utc,
        history_timestamps_utc=[row.close_time_utc for row in rows],
        history_values=[row.close for row in rows],
        horizon_steps=int(horizon_hours),
        allowed_usage=ForecastUsage.RESEARCH_ONLY,
        metadata={
            "exchange": exchange,
            "source_table": "market_klines",
            "completed_bar_policy": "close_time <= decision_time",
        },
    )
    adapter = TimesFMForecastAdapter(
        checkpoint_repo_id=checkpoint_repo_id,
        max_context=ceil_to_patch_multiple(lookback_hours),
        max_horizon=ceil_to_patch_multiple(horizon_hours),
        torch_compile=False,
    )
    result = adapter.forecast(request)
    forecast_rows = build_forecast_rows(result, rows[-1].close_time_utc)

    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "btc_timesfm_1h_smoke_forecast_report.json"
    rows_path = output_dir / "btc_timesfm_1h_smoke_forecast_rows.csv"
    audit_path = output_dir / "btc_timesfm_1h_smoke_forecast_audit.json"
    write_forecast_csv(rows_path, forecast_rows)
    audit_path.write_text(json.dumps(result.to_audit_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    report = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS_RESEARCH_ONLY_SMOKE",
        "generated_at_utc": generated_at.isoformat(),
        "scope": "btc_1h_offline_timesfm_smoke_forecast",
        "input": {
            "db_path": str(db_path),
            "exchange": exchange,
            "symbol": symbol,
            "interval": interval,
            "lookback_hours": lookback_hours,
            "decision_time_utc": rows[-1].close_time_utc.isoformat(),
            **input_summary,
        },
        "model": {
            "model_id": result.model_id,
            "model_version": result.model_version,
            "checkpoint_repo_id": checkpoint_repo_id,
            "environment": inspect_timesfm_environment(),
        },
        "forecast": {
            "horizon_hours": horizon_hours,
            "row_count": len(forecast_rows),
            "rows": forecast_rows,
        },
        "safety_flags": {
            "paper_queue_write_allowed": False,
            "live_unlock_allowed": False,
            "oms_access_allowed": False,
            "broker_access_allowed": False,
            "order_intent_allowed": False,
        },
        "gate": {
            "paper_candidate_allowed": False,
            "live_allowed": False,
            "reason": "smoke forecast only; no OOS validation, no baseline comparison, no regime/drawdown attribution",
        },
        "report_paths": {
            "json": str(report_path),
            "forecast_rows_csv": str(rows_path),
            "forecast_audit_json": str(audit_path),
        },
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Run BTCUSDT 1H TimesFM offline smoke forecast.")
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--exchange", default="binance_spot")
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--interval", default="1h")
    parser.add_argument("--lookback-hours", type=int, default=720)
    parser.add_argument("--horizon-hours", type=int, default=24)
    parser.add_argument("--checkpoint-repo-id", default=TIMESFM_DEFAULT_CHECKPOINT)
    args = parser.parse_args()
    report = run_btc_timesfm_smoke_forecast(
        db_path=args.db_path,
        output_dir=args.output_dir,
        exchange=args.exchange,
        symbol=args.symbol,
        interval=args.interval,
        lookback_hours=args.lookback_hours,
        horizon_hours=args.horizon_hours,
        checkpoint_repo_id=args.checkpoint_repo_id,
    )
    print(json.dumps({"status": report["status"], "report_paths": report["report_paths"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
