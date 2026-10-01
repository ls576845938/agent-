from __future__ import annotations

import csv
import io
import json
import sys
import time
import zipfile
from dataclasses import dataclass
from datetime import date, datetime, time as dt_time, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from quant_crypto.monitoring.artifact_schema import stable_payload_hash


BINANCE_VISION_DERIVATIVES_VERSION = "btc_binance_vision_derivatives_sentiment_v1"
BINANCE_VISION_BASE = "https://data.binance.vision/data/futures/um"
SYMBOL = "BTCUSDT"
HOUR_MS = 60 * 60 * 1000
GITHUB_DAILY_LIQUIDATION_URLS = {
    "long_liquidations_usd_daily": (
        "https://raw.githubusercontent.com/ErcinDedeoglu/crypto-market-data/main/"
        "data/daily/btc_long_liquidations_usd.json"
    ),
    "short_liquidations_usd_daily": (
        "https://raw.githubusercontent.com/ErcinDedeoglu/crypto-market-data/main/"
        "data/daily/btc_short_liquidations_usd.json"
    ),
}


@dataclass(frozen=True)
class BinanceVisionDerivativesBuildResult:
    rows: list[dict[str, Any]]
    audit: dict[str, Any]


def build_binance_vision_derivatives_sentiment_rows(
    *,
    metrics_rows_5m: Sequence[Mapping[str, Any]],
    funding_rows: Sequence[Mapping[str, Any]],
    okx_tail_rows: Sequence[Mapping[str, Any]] | None,
    generated_at_utc: datetime,
    symbol: str = SYMBOL,
) -> BinanceVisionDerivativesBuildResult:
    generated_at = _ensure_utc(generated_at_utc)
    metrics_rows = aggregate_metrics_5m_to_1h(
        metrics_rows_5m,
        generated_at_utc=generated_at,
        symbol=symbol,
    )
    funding_by_hour = _funding_by_hour(funding_rows)
    okx_by_event = _okx_tail_by_event(okx_tail_rows or [])
    merged_rows: list[dict[str, Any]] = []
    for row in metrics_rows:
        event_time = _parse_utc(row["event_time"])
        event_key = event_time.isoformat()
        okx = okx_by_event.get(event_key, {})
        funding_rate = _optional_float(okx.get("funding_rate"))
        if funding_rate is None:
            funding_rate = funding_by_hour.get(_to_ms(event_time))
        long_liq = _optional_float(okx.get("long_liquidation_usd"))
        short_liq = _optional_float(okx.get("short_liquidation_usd"))
        component_payload = {
            "binance_vision_metrics": {
                key: value
                for key, value in row.items()
                if key
                in {
                    "open_interest",
                    "open_interest_usd",
                    "long_short_ratio",
                    "top_trader_long_short_ratio",
                    "top_trader_long_short_position_ratio",
                    "taker_buy_sell_ratio",
                }
            },
            "binance_vision_funding_rate": funding_rate,
            "okx_tail_liquidation": {
                "long_liquidation_usd": long_liq,
                "short_liquidation_usd": short_liq,
            },
        }
        merged = dict(row)
        merged.update(
            {
                "source_provider": "binance_vision_metrics_5m_hourly_okx_tail",
                "funding_rate": funding_rate,
                "long_liquidation_usd": long_liq,
                "short_liquidation_usd": short_liq,
                "liquidation_source": "okx_720h_tail" if long_liq is not None or short_liq is not None else None,
                "funding_source": "okx_tail" if okx.get("funding_rate") is not None else "binance_vision_monthly",
                "source_raw_payload_hash": stable_payload_hash(component_payload),
            }
        )
        merged_rows.append(merged)
    audit = build_binance_vision_derivatives_audit(
        rows=merged_rows,
        generated_at_utc=generated_at,
        metrics_raw_count=len(metrics_rows_5m),
        funding_raw_count=len(funding_rows),
        okx_tail_raw_count=len(okx_tail_rows or []),
        github_daily_liquidation_diagnostics={},
    )
    return BinanceVisionDerivativesBuildResult(rows=merged_rows, audit=audit)


def aggregate_metrics_5m_to_1h(
    rows: Sequence[Mapping[str, Any]],
    *,
    generated_at_utc: datetime,
    symbol: str = SYMBOL,
) -> list[dict[str, Any]]:
    generated_at = _ensure_utc(generated_at_utc)
    buckets: dict[int, list[Mapping[str, Any]]] = {}
    for row in rows:
        if str(row.get("symbol") or symbol).upper() != symbol.upper():
            continue
        event_time = _parse_binance_create_time(row.get("create_time"))
        bucket = _hour_ms(_to_ms(event_time))
        buckets.setdefault(bucket, []).append(row)
    output: list[dict[str, Any]] = []
    for hour in sorted(buckets):
        bucket_rows = sorted(buckets[hour], key=lambda item: _parse_binance_create_time(item.get("create_time")))
        last = bucket_rows[-1]
        hour_start = datetime.fromtimestamp(hour / 1000, tz=timezone.utc)
        decision_event_time = hour_start + timedelta(hours=1)
        available_time = decision_event_time + timedelta(minutes=5)
        component_payload = {"rows": list(bucket_rows)}
        output.append(
            {
                "event_time": decision_event_time.isoformat(),
                "available_time": available_time.isoformat(),
                "ingested_at": generated_at.isoformat(),
                "processed_at": generated_at.isoformat(),
                "venue": "binance_usdm",
                "symbol": symbol,
                "source_provider": "binance_vision_metrics_5m_hourly",
                "is_final": True,
                "aggregation_policy": "5m metrics in [hour,hour+1h) assigned to next 1h decision timestamp; last 5m observation wins",
                "metrics_window_start": hour_start.isoformat(),
                "metrics_window_end": decision_event_time.isoformat(),
                "metrics_5m_row_count": len(bucket_rows),
                "open_interest": _optional_float(last.get("sum_open_interest")),
                "open_interest_usd": _optional_float(last.get("sum_open_interest_value")),
                "long_short_ratio": _optional_float(last.get("count_long_short_ratio")),
                "top_trader_long_short_ratio": _optional_float(last.get("count_toptrader_long_short_ratio")),
                "top_trader_long_short_position_ratio": _optional_float(last.get("sum_toptrader_long_short_ratio")),
                "taker_buy_sell_ratio": _optional_float(last.get("sum_taker_long_short_vol_ratio")),
                "long_liquidation_usd": None,
                "short_liquidation_usd": None,
                "funding_rate": None,
                "source_raw_payload_hash": stable_payload_hash(component_payload),
            }
        )
    return output


def fetch_binance_vision_metrics_rows(
    *,
    start_date: date,
    end_date: date,
    raw_dir: Path,
    symbol: str = SYMBOL,
    sleep_seconds: float = 0.02,
    request_timeout_seconds: int = 30,
    progress_every: int = 0,
) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    rows: list[dict[str, str]] = []
    attempts: list[dict[str, Any]] = []
    days = _days(start_date, end_date)
    for index, day in enumerate(days, start=1):
        url = f"{BINANCE_VISION_BASE}/daily/metrics/{symbol}/{symbol}-metrics-{day:%Y-%m-%d}.zip"
        try:
            downloaded = _read_archive_csv(url, raw_dir, request_timeout_seconds=request_timeout_seconds)
            rows.extend(downloaded)
            attempts.append(_attempt("binance_vision_metrics_daily", url, day.isoformat(), 200, len(downloaded), None))
            time.sleep(sleep_seconds)
        except (HTTPError, URLError, TimeoutError) as exc:
            attempts.append(_attempt("binance_vision_metrics_daily", url, day.isoformat(), _status_code(exc), 0, exc))
        _emit_download_progress(
            enabled_every=progress_every,
            index=index,
            total=len(days),
            label="binance_vision_metrics_daily",
            latest_attempt=attempts[-1],
        )
    return rows, attempts


def fetch_binance_vision_funding_rows(
    *,
    start_date: date,
    end_date: date,
    raw_dir: Path,
    symbol: str = SYMBOL,
    sleep_seconds: float = 0.02,
    request_timeout_seconds: int = 30,
    progress_every: int = 0,
) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    rows: list[dict[str, str]] = []
    attempts: list[dict[str, Any]] = []
    months = _months(start_date, end_date)
    for index, (year, month) in enumerate(months, start=1):
        url = f"{BINANCE_VISION_BASE}/monthly/fundingRate/{symbol}/{symbol}-fundingRate-{year:04d}-{month:02d}.zip"
        try:
            downloaded = _read_archive_csv(url, raw_dir, request_timeout_seconds=request_timeout_seconds)
            rows.extend(downloaded)
            attempts.append(_attempt("binance_vision_funding_monthly", url, f"{year:04d}-{month:02d}", 200, len(downloaded), None))
            time.sleep(sleep_seconds)
        except (HTTPError, URLError, TimeoutError) as exc:
            attempts.append(
                _attempt("binance_vision_funding_monthly", url, f"{year:04d}-{month:02d}", _status_code(exc), 0, exc)
            )
        _emit_download_progress(
            enabled_every=progress_every,
            index=index,
            total=len(months),
            label="binance_vision_funding_monthly",
            latest_attempt=attempts[-1],
        )
    return rows, attempts


def fetch_github_daily_liquidation_diagnostics(*, timeout_seconds: int = 30) -> dict[str, Any]:
    diagnostics: dict[str, Any] = {
        "source": "ErcinDedeoglu/crypto-market-data",
        "frequency": "daily",
        "gate_eligible": False,
        "used_for_1h_liquidation_history": False,
        "datasets": {},
        "warnings": ["github_daily_liquidation_fallback_diagnostic_only_not_gate_eligible"],
    }
    for name, url in GITHUB_DAILY_LIQUIDATION_URLS.items():
        try:
            request = Request(url, headers={"User-Agent": "QuantStationVNEXT-binance-vision-derivatives/1.0"})
            with urlopen(request, timeout=timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
            data = payload.get("data") if isinstance(payload, Mapping) else []
            rows = data if isinstance(data, list) else []
            diagnostics["datasets"][name] = {
                "status": "available",
                "row_count": len(rows),
                "granularity": payload.get("granularity"),
                "first_data_date": payload.get("first_data_date"),
                "last_data_date": payload.get("last_data_date"),
                "url": url,
            }
        except Exception as exc:  # noqa: BLE001 - diagnostic only, never blocks primary import.
            diagnostics["datasets"][name] = {
                "status": "blocked",
                "error": f"{type(exc).__name__}:{exc}",
                "url": url,
            }
    return diagnostics


def build_binance_vision_derivatives_audit(
    *,
    rows: Sequence[Mapping[str, Any]],
    generated_at_utc: datetime,
    metrics_raw_count: int,
    funding_raw_count: int,
    okx_tail_raw_count: int,
    github_daily_liquidation_diagnostics: Mapping[str, Any],
    download_attempts: Sequence[Mapping[str, Any]] | None = None,
    rows_output: Path | None = None,
    network_route_label: str = "",
) -> dict[str, Any]:
    generated_at = _ensure_utc(generated_at_utc)
    sorted_rows = sorted(rows, key=lambda item: str(item.get("event_time") or ""))
    event_times = [str(row.get("event_time")) for row in sorted_rows if row.get("event_time")]
    field_counts = _field_non_null_counts(sorted_rows)
    extra_counts = _extra_field_non_null_counts(sorted_rows)
    blockers: list[str] = []
    if len(sorted_rows) < 24 * 180:
        blockers.append("btc_binance_vision_derivatives_rows_below_180d")
    if field_counts["open_interest_usd"] < 24 * 180:
        blockers.append("btc_binance_vision_open_interest_usd_below_180d")
    if field_counts["long_short_ratio"] < 24 * 180:
        blockers.append("btc_binance_vision_long_short_ratio_below_180d")
    payload = {
        "schema_version": BINANCE_VISION_DERIVATIVES_VERSION,
        "status": "complete" if not blockers else "blocked",
        "generated_at": generated_at.isoformat(),
        "network_called": bool(download_attempts),
        "network_route_label": network_route_label,
        "public_market_data_only": True,
        "api_key_used": False,
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "real_order_submitted": False,
        "source_provider": "binance_vision_metrics_5m_hourly_okx_tail",
        "rows_output": str(rows_output).replace("\\", "/") if rows_output else None,
        "row_count": len(sorted_rows),
        "event_start": event_times[0] if event_times else None,
        "event_end": event_times[-1] if event_times else None,
        "metrics_raw_5m_count": metrics_raw_count,
        "funding_raw_count": funding_raw_count,
        "okx_tail_raw_count": okx_tail_raw_count,
        "field_non_null_counts": field_counts,
        "extra_field_non_null_counts": extra_counts,
        "field_mapping": {
            "open_interest": "Binance Vision metrics.sum_open_interest",
            "open_interest_usd": "Binance Vision metrics.sum_open_interest_value",
            "long_short_ratio": "Binance Vision metrics.count_long_short_ratio",
            "top_trader_long_short_ratio": "Binance Vision metrics.count_toptrader_long_short_ratio",
            "top_trader_long_short_position_ratio": "Binance Vision metrics.sum_toptrader_long_short_ratio",
            "taker_buy_sell_ratio": "Binance Vision metrics.sum_taker_long_short_vol_ratio",
            "funding_rate": "Binance Vision monthly fundingRate plus OKX 720h tail override",
            "long_liquidation_usd": "OKX 720h tail only",
            "short_liquidation_usd": "OKX 720h tail only",
        },
        "pit_policy": {
            "metrics_aggregation": "5m metrics in [hour,hour+1h) assigned to the next 1h decision timestamp",
            "available_time_rule": "available_time is next 1h decision timestamp plus five minutes",
            "no_full_sample_standardization": True,
        },
        "funding_policy": {
            "binance_vision_monthly_archive_used": True,
            "okx_720h_tail_used": okx_tail_raw_count > 0,
            "funding_not_carried_indefinitely": True,
        },
        "liquidation_policy": {
            "one_hour_history_complete": False,
            "source": "OKX 720h tail only",
            "github_daily_fallback_diagnostic_only": bool(github_daily_liquidation_diagnostics),
            "gate_eligible": False,
            "do_not_claim_full_1h_liquidation_coverage": True,
        },
        "github_daily_liquidation_diagnostics": dict(github_daily_liquidation_diagnostics),
        "download_attempts": [dict(item) for item in (download_attempts or [])],
        "blockers": blockers,
    }
    payload["input_hashes"] = {
        "rows": stable_payload_hash({"rows": list(sorted_rows)}),
        "download_attempts": stable_payload_hash({"download_attempts": payload["download_attempts"]}),
        "github_daily_liquidation_diagnostics": stable_payload_hash(dict(github_daily_liquidation_diagnostics)),
    }
    payload["artifact_hash"] = stable_payload_hash(payload)
    return payload


def read_derivatives_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, Mapping) and isinstance(payload.get("rows"), list):
        return [dict(row) for row in payload["rows"] if isinstance(row, Mapping)]
    if isinstance(payload, list):
        return [dict(row) for row in payload if isinstance(row, Mapping)]
    return []


def write_derivatives_rows(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"rows": list(rows)}, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def default_date_window(*, generated_at_utc: datetime, lookback_days: int) -> tuple[date, date]:
    generated = _ensure_utc(generated_at_utc)
    end_day = generated.date() - timedelta(days=1)
    start_day = end_day - timedelta(days=max(1, int(lookback_days)) - 1)
    return start_day, end_day


def _read_archive_csv(url: str, raw_dir: Path, *, request_timeout_seconds: int) -> list[dict[str, str]]:
    raw_dir.mkdir(parents=True, exist_ok=True)
    target = raw_dir / url.rsplit("/", 1)[-1]
    if not target.exists():
        request = Request(url, headers={"User-Agent": "QuantStationVNEXT-binance-vision-derivatives/1.0"})
        with urlopen(request, timeout=request_timeout_seconds) as response:
            target.write_bytes(response.read())
    with zipfile.ZipFile(target) as archive:
        data = archive.read(archive.namelist()[0]).decode("utf-8")
    return list(csv.DictReader(io.StringIO(data)))


def _emit_download_progress(
    *,
    enabled_every: int,
    index: int,
    total: int,
    label: str,
    latest_attempt: Mapping[str, Any],
) -> None:
    if enabled_every <= 0:
        return
    if index != total and index % enabled_every != 0:
        return
    status = latest_attempt.get("status_code")
    rows = latest_attempt.get("rows")
    period = latest_attempt.get("date_or_month")
    error = latest_attempt.get("error")
    suffix = f" error={error}" if error else ""
    print(f"[{label}] {index}/{total} period={period} status={status} rows={rows}{suffix}", file=sys.stderr, flush=True)


def _funding_by_hour(rows: Sequence[Mapping[str, Any]]) -> dict[int, float]:
    observed: dict[int, float] = {}
    for row in rows:
        ts = _int_or_none(row.get("calc_time") or row.get("fundingTime") or row.get("timestamp"))
        rate = _optional_float(row.get("last_funding_rate") or row.get("fundingRate") or row.get("funding_rate"))
        if ts is None or rate is None:
            continue
        start = _hour_ms(ts)
        for offset in range(0, 8 * HOUR_MS, HOUR_MS):
            observed[start + offset] = rate
    return observed


def _okx_tail_by_event(rows: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    for row in rows:
        event_time = row.get("event_time")
        if not event_time:
            continue
        try:
            key = _parse_utc(event_time).isoformat()
        except (TypeError, ValueError):
            continue
        output[key] = dict(row)
    return output


def _field_non_null_counts(rows: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    fields = (
        "open_interest_usd",
        "funding_rate",
        "long_liquidation_usd",
        "short_liquidation_usd",
        "long_short_ratio",
    )
    return {field: sum(1 for row in rows if row.get(field) is not None) for field in fields}


def _extra_field_non_null_counts(rows: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    fields = (
        "open_interest",
        "top_trader_long_short_ratio",
        "top_trader_long_short_position_ratio",
        "taker_buy_sell_ratio",
    )
    return {field: sum(1 for row in rows if row.get(field) is not None) for field in fields}


def _attempt(mode: str, url: str, date_or_month: str, status_code: int | None, rows: int, error: BaseException | None) -> dict[str, Any]:
    payload = {
        "mode": mode,
        "url": url,
        "date_or_month": date_or_month,
        "status_code": status_code,
        "rows": rows,
    }
    if error is not None:
        payload["error"] = f"{type(error).__name__}:{error}"
    return payload


def _status_code(exc: BaseException) -> int | None:
    return int(exc.code) if isinstance(exc, HTTPError) else None


def _days(start: date, end: date) -> list[date]:
    values: list[date] = []
    cursor = start
    while cursor <= end:
        values.append(cursor)
        cursor += timedelta(days=1)
    return values


def _months(start: date, end: date) -> list[tuple[int, int]]:
    values: list[tuple[int, int]] = []
    cursor = date(start.year, start.month, 1)
    end_month = date(end.year, end.month, 1)
    while cursor <= end_month:
        values.append((cursor.year, cursor.month))
        cursor = date(cursor.year + 1, 1, 1) if cursor.month == 12 else date(cursor.year, cursor.month + 1, 1)
    return values


def _parse_binance_create_time(value: Any) -> datetime:
    if value in {None, ""}:
        raise ValueError("create_time missing")
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value) / 1000.0, tz=timezone.utc)
    text = str(value).strip()
    if text.isdigit():
        return datetime.fromtimestamp(int(text) / 1000.0, tz=timezone.utc)
    return datetime.fromisoformat(text.replace(" ", "T")).replace(tzinfo=timezone.utc)


def _parse_utc(value: Any) -> datetime:
    if value in {None, ""}:
        raise ValueError("datetime missing")
    if isinstance(value, datetime):
        return _ensure_utc(value)
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)


def _ensure_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _hour_ms(value: int) -> int:
    return int(value // HOUR_MS * HOUR_MS)


def _to_ms(value: datetime) -> int:
    return int(_ensure_utc(value).timestamp() * 1000)


def _optional_float(value: Any) -> float | None:
    if value in {None, ""}:
        return None
    return float(value)


def _int_or_none(value: Any) -> int | None:
    if value in {None, ""}:
        return None
    return int(float(value))
