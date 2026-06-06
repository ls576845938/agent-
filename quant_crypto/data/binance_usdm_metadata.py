from __future__ import annotations

import csv
import json
import math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from quant_crypto.data.funding_rate_coverage import funding_rate_coverage_status


SYMBOL = "BTCUSDT"
FUNDING_INTERVAL_TOLERANCE_SECONDS = 300


def evaluate_funding_info(bundle_dir: Path, manifest: Mapping[str, Any] | None = None) -> dict[str, Any]:
    path = bundle_dir / "funding_info.json"
    manifest = manifest or {}
    payload = _read_json(path)
    funding_rate_path = bundle_dir / "funding_rate.csv"
    diagnostics = funding_spacing_diagnostics(funding_rate_path)
    source_method = _funding_source_method(payload)
    raw_response = _funding_raw_response(payload)
    endpoint_response_blockers = _funding_endpoint_response_blockers(raw_response)
    endpoint_response_available = bool(
        payload
        and (
            payload.get("endpoint_response_available") is True
            or source_method == "public_rest_response"
        )
        and not endpoint_response_blockers
    )
    endpoint_source_method = source_method in {"public_rest_response", "manual_offline_capture"}
    symbol_adjustment_record = _find_symbol_record(raw_response, SYMBOL)
    interval_from_record = _positive_float(symbol_adjustment_record.get("fundingIntervalHours")) if symbol_adjustment_record else None
    interval_hours = interval_from_record or diagnostics["dominant_interval_hours"]
    interval_source = (
        "funding_info_endpoint"
        if interval_from_record
        else "inferred_from_funding_rate_spacing"
        if interval_hours
        else "none"
    )
    confidence = "high" if interval_from_record else diagnostics["inference_confidence"]
    coverage_aligned = _funding_rate_coverage_aligned(funding_rate_path, manifest)
    blockers: list[str] = []
    if not path.exists():
        blockers.append("btc_funding_info_missing")
    if not payload:
        blockers.append("btc_funding_info_json_missing_or_invalid")
    if source_method not in {"public_rest_response", "manual_offline_capture", "inferred_from_funding_rate_spacing"}:
        blockers.append("btc_funding_info_source_method_missing_or_invalid")
    if source_method in {"public_rest_response", "manual_offline_capture"}:
        if not _is_utc_z_timestamp(payload.get("captured_at")):
            blockers.append("btc_funding_info_captured_at_missing")
    if source_method == "manual_offline_capture":
        if not _has_source_provenance(payload, ("source_url", "source_url_or_doc")):
            blockers.append("btc_funding_info_source_url_missing")
        if not _non_empty_text(payload.get("operator_note")):
            blockers.append("btc_funding_info_operator_note_missing")
    if source_method == "inferred_from_funding_rate_spacing":
        blockers.append("btc_funding_info_endpoint_not_verified_inferred_only")
    blockers.extend(endpoint_response_blockers)
    if endpoint_source_method and not endpoint_response_available:
        blockers.append("btc_funding_info_endpoint_response_not_available")
    if confidence != "high":
        blockers.append("btc_funding_interval_inference_not_high_confidence")
    if not coverage_aligned:
        blockers.append("btc_funding_rate_coverage_incomplete_for_funding_info_verification")
    verified = bool(endpoint_response_available and confidence == "high" and coverage_aligned and not blockers)
    return {
        "source_method": source_method,
        "endpoint_response_available": endpoint_response_available,
        "symbol_adjustment_record_present": bool(symbol_adjustment_record),
        "funding_interval_hours": interval_hours,
        "funding_interval_source": interval_source,
        "inference_confidence": confidence,
        "spacing_diagnostics": diagnostics,
        "funding_info_verified": verified,
        "blockers": _dedupe(blockers),
    }


def build_inferred_funding_info_overlay(
    *,
    bundle_dir: Path,
    captured_at: str | None = None,
    operator_note: str = "Inferred from local funding_rate.csv fundingTime spacing; endpoint response unavailable.",
) -> dict[str, Any]:
    diagnostics = funding_spacing_diagnostics(bundle_dir / "funding_rate.csv")
    confidence = diagnostics["inference_confidence"]
    blockers: list[str] = []
    if confidence != "high":
        blockers.append("btc_funding_interval_inference_not_high_confidence")
    return {
        "source_method": "inferred_from_funding_rate_spacing",
        "source_endpoint": "/fapi/v1/fundingInfo",
        "captured_at": captured_at or _utc_z_now(),
        "symbol": SYMBOL,
        "endpoint_response_available": False,
        "raw_response": [],
        "symbol_adjustment_record_present": False,
        "funding_interval_hours": diagnostics["dominant_interval_hours"],
        "funding_interval_source": "inferred_from_funding_rate_spacing",
        "inference_confidence": confidence,
        "spacing_diagnostics": diagnostics,
        "operator_note": operator_note,
        "blockers": _dedupe(["btc_funding_info_endpoint_not_verified_inferred_only", *blockers]),
    }


def build_funding_info_endpoint_overlay(
    *,
    bundle_dir: Path,
    raw_response: Any,
    source_method: str,
    source_url_or_doc: str,
    captured_at: str | None = None,
    operator_note: str = "",
) -> dict[str, Any]:
    if source_method not in {"public_rest_response", "manual_offline_capture"}:
        raise ValueError("source_method must be public_rest_response or manual_offline_capture")
    diagnostics = funding_spacing_diagnostics(bundle_dir / "funding_rate.csv")
    symbol_adjustment_record = _find_symbol_record(raw_response, SYMBOL)
    interval_from_record = _positive_float(symbol_adjustment_record.get("fundingIntervalHours")) if symbol_adjustment_record else None
    interval_hours = interval_from_record or diagnostics["dominant_interval_hours"]
    interval_source = "funding_info_endpoint" if interval_from_record else "inferred_from_funding_rate_spacing"
    confidence = "high" if interval_from_record else diagnostics["inference_confidence"]
    blockers: list[str] = []
    blockers.extend(_funding_endpoint_response_blockers(raw_response))
    if confidence != "high":
        blockers.append("btc_funding_interval_inference_not_high_confidence")
    if source_method == "manual_offline_capture" and not _non_empty_text(operator_note):
        blockers.append("btc_funding_info_operator_note_missing")
    if not _non_empty_text(source_url_or_doc):
        blockers.append("btc_funding_info_source_url_missing")
    return {
        "source_method": source_method,
        "source_endpoint": "/fapi/v1/fundingInfo",
        "source_url_or_doc": source_url_or_doc,
        "captured_at": captured_at or _utc_z_now(),
        "symbol": SYMBOL,
        "endpoint_response_available": not _funding_endpoint_response_blockers(raw_response),
        "raw_response": raw_response,
        "symbol_adjustment_record_present": bool(symbol_adjustment_record),
        "funding_interval_hours": interval_hours,
        "funding_interval_source": interval_source,
        "inference_confidence": confidence,
        "spacing_diagnostics": diagnostics,
        "operator_note": operator_note,
        "blockers": _dedupe(blockers),
    }


def funding_spacing_diagnostics(path: Path) -> dict[str, Any]:
    times = _funding_times(path)
    if len(times) < 2:
        return {
            "observed_intervals_hours": [],
            "dominant_interval_hours": None,
            "dominant_interval_count": 0,
            "irregular_interval_count": 0,
            "duplicate_funding_time_count": 0,
            "monotonic_time_pass": bool(times),
            "inference_confidence": "none",
        }
    ordered = sorted(times)
    duplicate_count = len(times) - len(set(times))
    deltas = [(right - left).total_seconds() for left, right in zip(ordered, ordered[1:])]
    rounded_hours = [round(delta / 3600) for delta in deltas if delta > 0]
    counts = Counter(rounded_hours)
    dominant_interval_hours, dominant_count = counts.most_common(1)[0]
    irregular = sum(
        1
        for delta in deltas
        if abs(delta - dominant_interval_hours * 3600) > FUNDING_INTERVAL_TOLERANCE_SECONDS
    )
    monotonic = times == ordered
    confidence = "high" if dominant_count >= 100 and irregular == 0 and duplicate_count == 0 and monotonic else "low"
    return {
        "observed_intervals_hours": sorted(counts),
        "dominant_interval_hours": float(dominant_interval_hours),
        "dominant_interval_count": int(dominant_count),
        "irregular_interval_count": int(irregular),
        "duplicate_funding_time_count": int(duplicate_count),
        "monotonic_time_pass": bool(monotonic),
        "inference_confidence": confidence,
    }


def evaluate_exchange_info(path: Path | None) -> dict[str, Any]:
    payload = _read_json(path) if path else {}
    source_method = str(payload.get("source_method") or ("public_rest_response" if payload.get("source_endpoint") else ""))
    raw = payload.get("raw_symbol_info") or payload.get("payload") or payload
    okx_instrument = _find_okx_instrument_info(raw)
    symbol_info = _canonical_okx_symbol_info(okx_instrument, payload) if okx_instrument else _find_exchange_symbol_info(raw, SYMBOL)
    filters = {
        str(item.get("filterType")): item
        for item in symbol_info.get("filters", [])
        if isinstance(item, Mapping)
    } if symbol_info else {}
    price_filter = filters.get("PRICE_FILTER", {})
    lot_filter = filters.get("LOT_SIZE", {})
    min_notional_filter = filters.get("MIN_NOTIONAL", {})
    min_notional = min_notional_filter.get("notional", min_notional_filter.get("minNotional"))
    blockers: list[str] = []
    if not payload:
        blockers.append("btc_exchange_info_missing")
    if source_method not in {"public_rest_response", "manual_offline_capture", "official_public_rest_capture"}:
        blockers.append("btc_exchange_info_source_method_missing_or_invalid")
    if source_method == "manual_offline_capture" and not _has_source_provenance(payload, ("source_url_or_doc",)):
        blockers.append("btc_exchange_info_source_url_missing")
    if source_method == "manual_offline_capture" and not _exchange_info_manual_provenance_mentions_allowed_endpoint(
        payload.get("source_url_or_doc")
    ):
        blockers.append("btc_exchange_info_source_endpoint_missing_or_invalid")
    if source_method != "manual_offline_capture" and not _has_source_provenance(payload, ("source_url_or_doc", "source_endpoint")):
        blockers.append("btc_exchange_info_source_url_missing")
    if not _is_utc_z_timestamp(payload.get("captured_at") or payload.get("fetched_at")):
        blockers.append("btc_exchange_info_captured_at_missing")
    if payload.get("api_key_used") is not False:
        blockers.append("btc_exchange_info_api_key_usage_not_explicitly_false")
    if payload.get("private_endpoint_used") is not False:
        blockers.append("btc_exchange_info_private_endpoint_usage_not_explicitly_false")
    if payload.get("auth_headers_present") is not False:
        blockers.append("btc_exchange_info_auth_headers_not_explicitly_false")
    if source_method == "manual_offline_capture" and not _non_empty_text(payload.get("operator_note")):
        blockers.append("btc_exchange_info_operator_note_missing")
    if not symbol_info:
        blockers.append("btc_exchange_info_btcusdt_symbol_missing")
    if symbol_info and symbol_info.get("contractType") != "PERPETUAL":
        blockers.append("btc_exchange_info_contract_type_not_perpetual")
    if symbol_info and symbol_info.get("status") != "TRADING":
        blockers.append("btc_exchange_info_status_not_trading")
    if not _positive_float(price_filter.get("tickSize")):
        blockers.append("btc_exchange_info_tick_size_missing")
    if not _positive_float(lot_filter.get("stepSize")):
        blockers.append("btc_exchange_info_step_size_missing")
    if not _positive_float(lot_filter.get("minQty")):
        blockers.append("btc_exchange_info_min_qty_missing")
    if not _positive_float(min_notional):
        blockers.append("btc_exchange_info_min_notional_missing")
    if symbol_info and symbol_info.get("pricePrecision") is None:
        blockers.append("btc_exchange_info_price_precision_missing")
    if symbol_info and symbol_info.get("quantityPrecision") is None:
        blockers.append("btc_exchange_info_quantity_precision_missing")
    verified = not blockers
    return {
        "source_method": source_method or None,
        "captured_at": payload.get("captured_at") or payload.get("fetched_at"),
        "symbol": SYMBOL if symbol_info else None,
        "contractType": symbol_info.get("contractType") if symbol_info else None,
        "status": symbol_info.get("status") if symbol_info else None,
        "tickSize": _positive_float(price_filter.get("tickSize")),
        "stepSize": _positive_float(lot_filter.get("stepSize")),
        "minQty": _positive_float(lot_filter.get("minQty")),
        "minNotional": _positive_float(min_notional),
        "pricePrecision": _int_or_none(symbol_info.get("pricePrecision")) if symbol_info else None,
        "quantityPrecision": _int_or_none(symbol_info.get("quantityPrecision")) if symbol_info else None,
        "historical_rule_lineage_available": bool(
            payload.get("historical_rule_lineage_available", payload.get("historical_rule_lineage", False))
        ),
        "api_key_used": payload.get("api_key_used"),
        "private_endpoint_used": payload.get("private_endpoint_used"),
        "auth_headers_present": payload.get("auth_headers_present"),
        "exchange_info_verified": bool(verified),
        "blockers": _dedupe(blockers),
    }


def exchange_rules_from_status(status: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "rules_available": bool(status.get("exchange_info_verified")),
        "tick_size": status.get("tickSize"),
        "step_size": status.get("stepSize"),
        "min_qty": status.get("minQty"),
        "min_notional": status.get("minNotional"),
        "price_precision": status.get("pricePrecision"),
        "quantity_precision": status.get("quantityPrecision"),
        "historical_rule_lineage_available": bool(status.get("historical_rule_lineage_available", False)),
        "blockers": list(status.get("blockers", [])),
    }


def _funding_times(path: Path) -> list[datetime]:
    if not path.exists():
        return []
    times: list[datetime] = []
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            parsed = _parse_time(row.get("fundingTime") or row.get("funding_time") or row.get("timestamp"))
            if parsed:
                times.append(parsed)
    return times


def _funding_rate_coverage_aligned(path: Path, manifest: Mapping[str, Any]) -> bool:
    start = _parse_time(manifest.get("sample_start"))
    end = _parse_time(manifest.get("sample_end"))
    if not start or not end:
        return False
    return bool(funding_rate_coverage_status(path, sample_start=start, sample_end=end).get("coverage_complete", False))


def _funding_source_method(payload: Mapping[str, Any]) -> str | None:
    if not payload:
        return None
    if payload.get("source_method"):
        return str(payload["source_method"])
    if payload.get("source_endpoint") == "/fapi/v1/fundingInfo":
        return "public_rest_response"
    return None


def _funding_raw_response(payload: Mapping[str, Any]) -> Any:
    if not payload:
        return []
    if "raw_response" in payload:
        return payload["raw_response"]
    if "payload" in payload:
        return payload["payload"]
    if "rows" in payload:
        return payload["rows"]
    return payload


def _funding_endpoint_response_blockers(payload: Any) -> list[str]:
    blockers: list[str] = []
    if _looks_like_endpoint_error(payload):
        blockers.append("btc_funding_info_endpoint_error_response")
    if not isinstance(payload, list):
        blockers.append("btc_funding_info_endpoint_response_not_array")
    else:
        if any(not isinstance(item, Mapping) for item in payload):
            blockers.append("btc_funding_info_endpoint_array_item_not_object")
        if any(_looks_like_endpoint_error(item) for item in payload):
            blockers.append("btc_funding_info_endpoint_error_response")
        rows = [item for item in payload if isinstance(item, Mapping)]
        if any(not isinstance(item.get("symbol"), str) or not item.get("symbol") for item in rows):
            blockers.append("btc_funding_info_endpoint_row_symbol_missing")
        symbol_record = _find_symbol_record(rows, SYMBOL)
        if symbol_record:
            if not _positive_float(symbol_record.get("fundingIntervalHours")):
                blockers.append("btc_funding_info_btcusdt_funding_interval_missing")
            if _float_or_none(symbol_record.get("adjustedFundingRateCap")) is None:
                blockers.append("btc_funding_info_btcusdt_adjusted_cap_missing")
            if _float_or_none(symbol_record.get("adjustedFundingRateFloor")) is None:
                blockers.append("btc_funding_info_btcusdt_adjusted_floor_missing")
    return blockers


def _looks_like_endpoint_error(payload: Any) -> bool:
    if isinstance(payload, Mapping):
        keys = {str(key).lower() for key in payload}
        if "code" in keys and ("msg" in keys or "message" in keys):
            return True
        if "error" in keys:
            return True
    return False


def _find_symbol_record(payload: Any, symbol: str) -> Mapping[str, Any]:
    if isinstance(payload, Mapping):
        if payload.get("symbol") == symbol:
            return payload
        for key in ("rows", "symbols", "data"):
            found = _find_symbol_record(payload.get(key), symbol)
            if found:
                return found
    if isinstance(payload, list):
        for item in payload:
            found = _find_symbol_record(item, symbol)
            if found:
                return found
    return {}


def _find_exchange_symbol_info(payload: Any, symbol: str) -> Mapping[str, Any]:
    if isinstance(payload, Mapping):
        if payload.get("symbol") == symbol:
            return payload
        if isinstance(payload.get("symbols"), list):
            for item in payload["symbols"]:
                found = _find_exchange_symbol_info(item, symbol)
                if found:
                    return found
        if isinstance(payload.get("rows"), list):
            for item in payload["rows"]:
                found = _find_exchange_symbol_info(item, symbol)
                if found:
                    return found
    if isinstance(payload, list):
        for item in payload:
            found = _find_exchange_symbol_info(item, symbol)
            if found:
                return found
    return {}


def _find_okx_instrument_info(payload: Any) -> Mapping[str, Any]:
    if isinstance(payload, Mapping):
        if payload.get("instId") == "BTC-USDT-SWAP" or payload.get("venue_symbol") == "BTC-USDT-SWAP":
            return payload
        for key in ("rows", "data", "symbols"):
            found = _find_okx_instrument_info(payload.get(key))
            if found:
                return found
    if isinstance(payload, list):
        for item in payload:
            found = _find_okx_instrument_info(item)
            if found:
                return found
    return {}


def _canonical_okx_symbol_info(instrument: Mapping[str, Any], payload: Mapping[str, Any]) -> dict[str, Any]:
    tick_size = instrument.get("tickSz")
    lot_size = instrument.get("lotSz")
    min_size = instrument.get("minSz") or lot_size
    mark_price = _positive_float(payload.get("mark_price_at_capture") or payload.get("last_price_at_capture"))
    contract_value = _positive_float(instrument.get("ctVal"))
    min_notional = _positive_float(payload.get("min_notional_estimate"))
    if min_notional is None and mark_price and contract_value and _positive_float(min_size):
        min_notional = float(min_size) * contract_value * mark_price
    return {
        "symbol": SYMBOL,
        "contractType": "PERPETUAL" if instrument.get("instType") == "SWAP" else instrument.get("instType"),
        "status": "TRADING" if instrument.get("state") == "live" else str(instrument.get("state", "")).upper(),
        "pricePrecision": _decimal_places(tick_size),
        "quantityPrecision": _decimal_places(lot_size),
        "filters": [
            {"filterType": "PRICE_FILTER", "tickSize": tick_size},
            {"filterType": "LOT_SIZE", "minQty": min_size, "stepSize": lot_size},
            {"filterType": "MIN_NOTIONAL", "notional": str(min_notional) if min_notional is not None else None},
        ],
    }


def _read_json(path: Path | None) -> dict[str, Any]:
    if not path or not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return dict(payload) if isinstance(payload, Mapping) else {"raw_response": payload}


def _parse_time(value: object) -> datetime | None:
    if value in {None, ""}:
        return None
    text = str(value).strip()
    if text.isdigit():
        number = int(text)
        if number > 10_000_000_000:
            number = number / 1000
        return datetime.fromtimestamp(float(number), tz=timezone.utc)
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def _is_utc_z_timestamp(value: object) -> bool:
    if not isinstance(value, str):
        return False
    text = value.strip()
    if not text.endswith("Z"):
        return False
    parsed = _parse_time(text)
    return parsed is not None and parsed.utcoffset() == timezone.utc.utcoffset(parsed)


def _utc_z_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _positive_float(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def _float_or_none(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _non_empty_text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _has_source_provenance(payload: Mapping[str, Any], keys: tuple[str, ...]) -> bool:
    return any(_non_empty_text(payload.get(key)) for key in keys)


def _exchange_info_manual_provenance_mentions_allowed_endpoint(value: object) -> bool:
    if not isinstance(value, str):
        return False
    text = value.strip()
    return "/fapi/v1/exchangeInfo" in text or "https://fapi.binance.com/fapi/v1/exchangeInfo" in text


def _int_or_none(value: object) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _decimal_places(value: object) -> int | None:
    text = str(value).strip()
    if not text:
        return None
    if "." not in text:
        return 0
    return len(text.rstrip("0").split(".", 1)[1])


def _dedupe(values: list[str]) -> list[str]:
    out: list[str] = []
    for value in values:
        if value and value not in out:
            out.append(value)
    return out
