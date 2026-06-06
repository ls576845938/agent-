#!/usr/bin/env python3
"""Build or validate a BTC USD-M perpetual local bundle manifest."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


REQUIRED_FILES: dict[str, str] = {
    "klines_1h.csv": "klines_1h",
    "klines_4h.csv": "klines_4h",
    "klines_1d.csv": "klines_1d",
    "mark_price_klines_1h.csv": "mark_price_klines_1h",
    "premium_index_klines_1h.csv": "premium_index_klines_1h",
    "funding_rate.csv": "funding_rate",
    "funding_info.json": "funding_info",
    "exchange_info.json": "exchange_info",
}
DIAGNOSTIC_FILES: dict[str, str] = {
    "open_interest_hist_1h.csv": "open_interest_hist_1h",
    "open_interest_current.json": "open_interest_current",
    "agg_trades.csv": "agg_trades",
    "liquidation_snapshots.csv": "liquidation_snapshots",
}
FILE_ROLES: dict[str, str] = {**REQUIRED_FILES, **DIAGNOSTIC_FILES}
INTERVAL_BY_ROLE: dict[str, str | None] = {
    "klines_1h": "1h",
    "klines_4h": "4h",
    "klines_1d": "1d",
    "mark_price_klines_1h": "1h",
    "premium_index_klines_1h": "1h",
    "open_interest_hist_1h": "1h",
}
BINANCE_ROLE_SOURCE_HINTS: dict[str, str] = {
    "klines_1h": "/fapi/v1/klines",
    "klines_4h": "/fapi/v1/klines",
    "klines_1d": "/fapi/v1/klines",
    "mark_price_klines_1h": "/fapi/v1/markPriceKlines",
    "premium_index_klines_1h": "/fapi/v1/premiumIndexKlines",
    "funding_rate": "/fapi/v1/fundingRate",
    "funding_info": "/fapi/v1/fundingInfo",
    "exchange_info": "/fapi/v1/exchangeInfo",
    "open_interest_hist_1h": "/futures/data/openInterestHist",
    "open_interest_current": "/fapi/v1/openInterest",
    "agg_trades": "/fapi/v1/aggTrades",
    "liquidation_snapshots": "diagnostic_local_archive",
}
OKX_ROLE_SOURCE_HINTS: dict[str, str] = {
    "klines_1h": "/api/v5/market/history-candles",
    "klines_4h": "/api/v5/market/history-candles",
    "klines_1d": "/api/v5/market/history-candles",
    "mark_price_klines_1h": "/api/v5/market/history-mark-price-candles",
    "premium_index_klines_1h": "derived_from_okx_mark_and_index_history",
    "funding_rate": "/api/v5/public/funding-rate-history",
    "funding_info": "/api/v5/public/funding-rate",
    "exchange_info": "/api/v5/public/instruments",
    "open_interest_hist_1h": "/api/v5/rubik/stat/contracts/open-interest-volume",
    "open_interest_current": "/api/v5/public/open-interest",
    "agg_trades": "diagnostic_local_archive",
    "liquidation_snapshots": "diagnostic_local_archive",
}
ROLE_SOURCE_HINTS_BY_PROVIDER: dict[str, dict[str, str]] = {
    "binance_usdm": BINANCE_ROLE_SOURCE_HINTS,
    "okx_swap": OKX_ROLE_SOURCE_HINTS,
}
TIME_SERIES_ROLES = {
    "klines_1h",
    "klines_4h",
    "klines_1d",
    "mark_price_klines_1h",
    "premium_index_klines_1h",
    "funding_rate",
    "open_interest_hist_1h",
    "agg_trades",
    "liquidation_snapshots",
}
REQUIRED_ROLES = set(REQUIRED_FILES.values())
DIAGNOSTIC_ROLES = set(DIAGNOSTIC_FILES.values())


def build_btc_perpetual_data_bundle_manifest(
    *,
    bundle_dir: Path,
    bundle_id: str,
    source_type: str = "sample",
    source_provider: str = "binance_usdm",
    exchange: str | None = None,
    symbol: str = "BTCUSDT",
    market_type: str = "usds_m_perpetual",
    promotion_clean_allowed: bool = False,
    sample_start: str | None = None,
    sample_end: str | None = None,
    license_note: str = "",
    created_at: str | None = None,
) -> dict[str, Any]:
    generated = created_at or datetime.now(timezone.utc).isoformat()
    blockers: list[str] = []
    if source_type not in {"fixture", "sample", "production"}:
        blockers.append("btc_perpetual_bundle_source_type_invalid")
    if source_type in {"fixture", "sample"} and promotion_clean_allowed:
        blockers.append("btc_perpetual_bundle_non_production_promotion_clean_allowed")
    if source_type == "production" and not promotion_clean_allowed:
        blockers.append("btc_perpetual_bundle_promotion_clean_not_allowed")
    if not license_note:
        blockers.append("btc_perpetual_bundle_license_note_missing")
    files = []
    derived_starts: list[str] = []
    derived_ends: list[str] = []
    for filename, role in FILE_ROLES.items():
        path = bundle_dir / filename
        if not path.exists():
            if filename in REQUIRED_FILES:
                blockers.append(f"btc_perpetual_bundle_required_file_missing:{filename}")
            elif role == "liquidation_snapshots":
                blockers.append("btc_liquidation_snapshots_missing_diagnostic_only")
            elif role.startswith("open_interest"):
                blockers.append("btc_open_interest_history_not_verified_diagnostic_partial")
            continue
        metadata = _file_metadata(path, role, source_provider=source_provider)
        if metadata["sample_start"]:
            derived_starts.append(str(metadata["sample_start"]))
        if metadata["sample_end"]:
            derived_ends.append(str(metadata["sample_end"]))
        files.append(metadata)
    effective_sample_start = sample_start or (min(derived_starts) if derived_starts else None)
    effective_sample_end = sample_end or (max(derived_ends) if derived_ends else None)
    if not effective_sample_start or not effective_sample_end:
        blockers.append("btc_perpetual_bundle_sample_range_missing")
    return {
        "bundle_id": bundle_id,
        "source_provider": source_provider,
        "source_type": source_type,
        "symbol": symbol,
        "market_type": market_type,
        "exchange": exchange or source_provider,
        "sample_start": effective_sample_start,
        "sample_end": effective_sample_end,
        "intervals": ["1h", "4h", "1d"],
        "created_at": generated,
        "license_note": license_note,
        "promotion_clean_allowed": bool(promotion_clean_allowed),
        "files": files,
        "blockers": _dedupe(blockers),
    }


def validate_btc_perpetual_data_bundle_manifest(bundle_dir: Path, manifest: Mapping[str, Any]) -> dict[str, Any]:
    blockers: list[str] = []
    files = manifest.get("files", [])
    by_path = {str(item.get("path")): item for item in files if isinstance(item, Mapping)}
    for filename, role in REQUIRED_FILES.items():
        entry = by_path.get(filename)
        if not entry:
            blockers.append(f"btc_perpetual_bundle_manifest_file_entry_missing:{filename}")
            continue
        path = bundle_dir / filename
        if not path.exists():
            blockers.append(f"btc_perpetual_bundle_required_file_missing:{filename}")
            continue
        if str(entry.get("role", "")) != role:
            blockers.append(f"btc_perpetual_bundle_role_mismatch:{filename}")
        if str(entry.get("sha256", "")) != _sha256(path):
            blockers.append(f"btc_perpetual_bundle_sha256_mismatch:{filename}")
        if entry.get("sha256") in {None, ""}:
            blockers.append(f"btc_perpetual_bundle_sha256_missing:{filename}")
        if entry.get("record_count") in {None, ""}:
            blockers.append(f"btc_perpetual_bundle_record_count_missing:{filename}")
        elif int(entry.get("record_count", -1) or -1) != _record_count(path):
            blockers.append(f"btc_perpetual_bundle_record_count_mismatch:{filename}")
        if role in TIME_SERIES_ROLES and (not entry.get("sample_start") or not entry.get("sample_end")):
            blockers.append(f"btc_perpetual_bundle_file_sample_range_missing:{filename}")
        if entry.get("source_endpoint_or_archive") in {None, ""}:
            blockers.append(f"btc_perpetual_bundle_source_missing:{filename}")
    if manifest.get("source_type") in {"fixture", "sample"} and manifest.get("promotion_clean_allowed"):
        blockers.append("btc_perpetual_bundle_non_production_promotion_clean_allowed")
    if not manifest.get("license_note"):
        blockers.append("btc_perpetual_bundle_license_note_missing")
    if not manifest.get("sample_start") or not manifest.get("sample_end"):
        blockers.append("btc_perpetual_bundle_sample_range_missing")
    if str(manifest.get("source_type")) not in {"fixture", "sample", "production"}:
        blockers.append("btc_perpetual_bundle_source_type_invalid")
    if "liquidation_snapshots.csv" in by_path and by_path["liquidation_snapshots.csv"].get("role") != "liquidation_snapshots":
        blockers.append("btc_liquidation_snapshots_role_must_be_diagnostic_only")
    return {"valid": not blockers, "blockers": _dedupe(blockers)}


def write_manifest(payload: Mapping[str, Any], bundle_dir: Path) -> str:
    bundle_dir.mkdir(parents=True, exist_ok=True)
    output = bundle_dir / "btc_perpetual_bundle_manifest.json"
    output.write_text(json.dumps(dict(payload), indent=2, sort_keys=True), encoding="utf-8")
    return str(output)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle-dir", required=True)
    parser.add_argument("--bundle-id", required=True)
    parser.add_argument("--source-type", default="sample", choices=["fixture", "sample", "production"])
    parser.add_argument("--source-provider", default="binance_usdm")
    parser.add_argument("--exchange", default="")
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--market-type", default="usds_m_perpetual")
    parser.add_argument("--license-note", default="")
    parser.add_argument("--promotion-clean-allowed", action="store_true")
    parser.add_argument("--sample-start", default="")
    parser.add_argument("--sample-end", default="")
    args = parser.parse_args()
    payload = build_btc_perpetual_data_bundle_manifest(
        bundle_dir=Path(args.bundle_dir),
        bundle_id=args.bundle_id,
        source_type=args.source_type,
        source_provider=args.source_provider,
        exchange=args.exchange or None,
        symbol=args.symbol,
        market_type=args.market_type,
        license_note=args.license_note,
        promotion_clean_allowed=args.promotion_clean_allowed,
        sample_start=args.sample_start or None,
        sample_end=args.sample_end or None,
    )
    print(write_manifest(payload, Path(args.bundle_dir)))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _record_count(path: Path) -> int:
    if path.suffix.lower() == ".csv":
        with path.open(newline="", encoding="utf-8") as handle:
            reader = csv.reader(handle)
            rows = list(reader)
        return max(len(rows) - 1, 0)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return len(payload)
    if isinstance(payload, dict) and isinstance(payload.get("rows"), list):
        return len(payload["rows"])
    return 1 if payload else 0


def _file_metadata(path: Path, role: str, *, source_provider: str = "binance_usdm") -> dict[str, Any]:
    sample_start, sample_end = _sample_range(path)
    blockers: list[str] = []
    if role in TIME_SERIES_ROLES and (not sample_start or not sample_end):
        blockers.append("btc_perpetual_bundle_file_sample_range_missing")
    if role == "liquidation_snapshots":
        blockers.append("diagnostic_only_not_gate_evidence")
    return {
        "path": path.name,
        "role": role,
        "sha256": _sha256(path),
        "record_count": _record_count(path),
        "sample_start": sample_start,
        "sample_end": sample_end,
        "interval": INTERVAL_BY_ROLE.get(role),
        "source_endpoint_or_archive": ROLE_SOURCE_HINTS_BY_PROVIDER.get(source_provider, BINANCE_ROLE_SOURCE_HINTS).get(
            role,
            "local_archive_import",
        ),
        "downloaded_at": None,
        "imported_at": datetime.now(timezone.utc).isoformat(),
        "checksum_source": "local_sha256",
        "blockers": blockers,
    }


def _sample_range(path: Path) -> tuple[str | None, str | None]:
    values: list[str] = []
    if path.suffix.lower() == ".csv":
        with path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                value = _first_time_value(row)
                if value:
                    values.append(value)
    else:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload = None
        for row in _json_rows(payload):
            value = _first_time_value(row)
            if value:
                values.append(value)
    normalized = sorted(_normalize_time(value) for value in values if _normalize_time(value))
    if not normalized:
        return None, None
    return normalized[0], normalized[-1]


def _json_rows(payload: Any) -> list[Mapping[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, Mapping)]
    if isinstance(payload, Mapping):
        if isinstance(payload.get("rows"), list):
            return [row for row in payload["rows"] if isinstance(row, Mapping)]
        return [payload]
    return []


def _first_time_value(row: Mapping[str, Any]) -> str | None:
    for key in (
        "timestamp",
        "open_time",
        "openTime",
        "close_time",
        "closeTime",
        "fundingTime",
        "funding_time",
        "time",
        "date",
    ):
        value = row.get(key)
        if value not in {None, ""}:
            return str(value)
    return None


def _normalize_time(value: str) -> str | None:
    text = str(value).strip()
    if not text:
        return None
    if text.isdigit():
        number = int(text)
        if number > 10_000_000_000:
            number = number / 1000
        return datetime.fromtimestamp(float(number), tz=timezone.utc).isoformat().replace("+00:00", "Z")
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc).isoformat().replace(
            "+00:00", "Z"
        )
    except ValueError:
        return text


def _dedupe(values: list[str]) -> list[str]:
    result = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


if __name__ == "__main__":
    main()
