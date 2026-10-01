#!/usr/bin/env python3
"""Prepare the fixed-window public OKX inputs for the 2026-09-30 BTC ticket.

This is a task assembler, not a new collector platform.  It reuses the
repository public-only OKX collector and its pagination/selection helpers.
It never reads credentials and never calls account, private, or order APIs.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from quant_crypto.data.okx_swap_public import OkxSwapPublicCollector
from scripts.fetch_btc_okx_swap_public_data import (
    _candle_component_coverage,
    _fetch_paginated_okx_rows,
    _okx_request,
    _row_time_ms,
    _select_candles,
)

UTC = timezone.utc
INTERVAL_MS = 60_000
WINDOW_START = datetime(2026, 6, 15, 23, 59, tzinfo=UTC)
WINDOW_END = datetime(2026, 6, 18, 3, 0, tzinfo=UTC)
DECISION_START = datetime(2026, 6, 16, 1, 0, tzinfo=UTC)
DECISION_END = datetime(2026, 6, 18, 1, 0, tzinfo=UTC)
EXPECTED_MINUTES = 3_061
VENUE = "OKX"
SWAP_INSTRUMENT = "BTC-USDT-SWAP"
INDEX_INSTRUMENT = "BTC-USDT"
DATASET_ID = "btc-okx-real-candidate-minute-inputs"
BOUND_DATASET_ID = "btc-okx-public-swap-research-bundle"
BOUND_VERSION = "btc-okx-public-swap-btcusdt-demo25h-tail-20260730T1145Z-src6cea196b4-corr1"
BOUND_MANIFEST_SHA256 = "6c5dd8036da320062002b839792852c1aa53971fecdd20b1ba7ae3ec6c2260c9"
BOUND_AGGREGATE_SHA256 = "3a61fc915da66994294113cc7b2334a1da4c0e08bccf428a743564c863c8d680"
BOUND_FUNDING_SHA256 = "ba745f622ff9753ecd6b0a7a828ba308cebcc151c22c5b9424ed9c12de324d19"
BOUND_INSTRUMENT_SHA256 = "1a3be93ab5be07d8d0625ff37c077a461cba075876e44e8517266c9a28e336e8"
HISTORICAL_AVAILABILITY_ASSUMPTION = "bar_close_reconstructed_not_original_receipt"
VALUATION_POLICY = "minute_close_sampled_valuation_not_exchange_actual_settlement"


def utc_z(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"timezone_required:{value}")
    return parsed.astimezone(UTC)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_sha256(payload: object) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def git_blob_sha256(repo_root: Path, relative_path: str) -> str:
    raw = subprocess.check_output(["git", "show", f"HEAD:{relative_path}"], cwd=repo_root)
    return hashlib.sha256(raw).hexdigest()


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_csv(path: Path, fieldnames: Sequence[str], rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fieldnames))
        writer.writeheader()
        writer.writerows({name: row.get(name, "") for name in fieldnames} for row in rows)


class RecordingCollector(OkxSwapPublicCollector):
    """Record canonical raw response payloads while retaining public guards."""

    def __init__(self, *, output_root: Path) -> None:
        super().__init__(output_root=output_root, dry_run=False, allow_network=True)
        self.responses: list[dict[str, Any]] = []

    def request_by_name(self, name: str, params: Mapping[str, Any] | None = None) -> dict[str, Any]:
        fetched_at = utc_z(datetime.now(UTC))
        response = super().request_by_name(name, params)
        payload = response.get("payload")
        self.responses.append(
            {
                "name": name,
                "endpoint": response.get("endpoint"),
                "params": dict(params or {}),
                "url": response.get("url"),
                "fetched_at": fetched_at,
                "duration_ms": response.get("duration_ms"),
                "payload_canonical_sha256": canonical_sha256(payload),
                "hash_basis": "canonical_json_of_raw_response_payload",
                "payload": payload,
            }
        )
        return response


def fetch_window(
    collector: RecordingCollector,
    *,
    name: str,
    instrument_id: str,
    start_ms: int,
    end_ms: int,
    sleep_seconds: float,
) -> list[list[str]]:
    params = {"instId": instrument_id, "bar": "1m", "limit": "100"}
    seed = _okx_request(collector, name, {**params, "after": str(end_ms)})
    initial_rows = seed["payload"].get("data", [])
    rows = _fetch_paginated_okx_rows(
        collector,
        name,
        params,
        timestamp_getter=_row_time_ms,
        target_start_ms=start_ms,
        initial_rows=initial_rows,
        sleep_seconds=sleep_seconds,
        max_pages=100,
    )
    return _select_candles(rows, start_ms, end_ms, INTERVAL_MS)


def exact_minute_quality(rows: Sequence[Sequence[Any]], *, start_ms: int, end_ms: int, confirm_index: int) -> dict[str, Any]:
    timestamps = [int(row[0]) for row in rows]
    expected = list(range(start_ms, end_ms, INTERVAL_MS))
    missing = sorted(set(expected) - set(timestamps))
    unexpected = sorted(set(timestamps) - set(expected))
    duplicates = len(timestamps) - len(set(timestamps))
    unconfirmed = [int(row[0]) for row in rows if len(row) <= confirm_index or str(row[confirm_index]) != "1"]
    gaps = [right - left for left, right in zip(timestamps, timestamps[1:]) if right - left > 90_000]
    blockers: list[str] = []
    if len(rows) != EXPECTED_MINUTES:
        blockers.append(f"row_count_expected_{EXPECTED_MINUTES}_actual_{len(rows)}")
    if missing:
        blockers.append(f"missing_minutes:{len(missing)}")
    if unexpected:
        blockers.append(f"unexpected_minutes:{len(unexpected)}")
    if duplicates:
        blockers.append(f"duplicate_minutes:{duplicates}")
    if unconfirmed:
        blockers.append(f"unconfirmed_minutes:{len(unconfirmed)}")
    if gaps:
        blockers.append(f"boundary_or_adjacent_gap_over_90s:{len(gaps)}")
    return {
        "row_count": len(rows),
        "expected_row_count": EXPECTED_MINUTES,
        "first_open_time": utc_z(datetime.fromtimestamp(timestamps[0] / 1000, UTC)) if timestamps else "",
        "last_open_time": utc_z(datetime.fromtimestamp(timestamps[-1] / 1000, UTC)) if timestamps else "",
        "missing_count": len(missing),
        "unexpected_count": len(unexpected),
        "duplicate_count": duplicates,
        "unconfirmed_count": len(unconfirmed),
        "max_adjacent_gap_seconds": max([60.0, *(gap / 1000 for gap in gaps)]),
        "start_boundary_gap_seconds": ((timestamps[0] - start_ms) / 1000) if timestamps else None,
        "end_boundary_gap_seconds": ((end_ms - INTERVAL_MS - timestamps[-1]) / 1000) if timestamps else None,
        "blockers": blockers,
    }


def raw_duplicate_quality(responses: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    by_timestamp: dict[int, str] = {}
    duplicate_observation_count = 0
    conflicting_duplicate_count = 0
    for response in responses:
        payload = response.get("payload") if isinstance(response, Mapping) else None
        data = payload.get("data", []) if isinstance(payload, Mapping) else []
        for row in data if isinstance(data, list) else []:
            if not isinstance(row, list) or not row or not str(row[0]).isdigit():
                continue
            timestamp = int(row[0])
            fingerprint = canonical_sha256(row)
            previous = by_timestamp.get(timestamp)
            if previous is not None:
                duplicate_observation_count += 1
                if previous != fingerprint:
                    conflicting_duplicate_count += 1
            else:
                by_timestamp[timestamp] = fingerprint
    return {
        "raw_unique_timestamp_count": len(by_timestamp),
        "raw_duplicate_observation_count": duplicate_observation_count,
        "raw_conflicting_duplicate_count": conflicting_duplicate_count,
    }


def candle_rows(rows: Sequence[Sequence[Any]], *, instrument_id: str, price_type: str, fetched_at: str) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    trade = price_type == "trade"
    confirm_index = 8 if trade else 5
    for row in rows:
        opened = datetime.fromtimestamp(int(row[0]) / 1000, UTC)
        closed = opened + timedelta(minutes=1)
        output.append(
            {
                "venue": VENUE,
                "instrument_id": instrument_id,
                "price_type": price_type,
                "open_time": utc_z(opened),
                "event_time": utc_z(opened),
                "close_time": utc_z(closed),
                "available_time": utc_z(closed),
                "ingested_at": fetched_at,
                "processed_at": fetched_at,
                "open": row[1],
                "high": row[2],
                "low": row[3],
                "close": row[4],
                "volume": row[5] if trade else "",
                "volume_base": row[6] if trade and len(row) > 6 else "",
                "volume_quote": row[7] if trade and len(row) > 7 else "",
                "confirm": row[confirm_index],
                "source_record_id": f"okx:{price_type}:{instrument_id}:{row[0]}",
                "historical_availability_assumption": HISTORICAL_AVAILABILITY_ASSUMPTION,
            }
        )
    return output


def validate_bound_inputs(repo_root: Path, shared_root: Path) -> tuple[Path, dict[str, Any]]:
    manifest_relative = f".agent/data_manifests/{BOUND_DATASET_ID}/{BOUND_VERSION}.json"
    manifest_path = repo_root / manifest_relative
    if git_blob_sha256(repo_root, manifest_relative) != BOUND_MANIFEST_SHA256:
        raise RuntimeError("bound_manifest_sha256_mismatch")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("aggregate_sha256") != BOUND_AGGREGATE_SHA256 or manifest.get("file_count") != 15:
        raise RuntimeError("bound_manifest_aggregate_or_file_count_mismatch")
    dataset_root = shared_root / "datasets" / BOUND_DATASET_ID / BOUND_VERSION
    funding = dataset_root / "funding_rate.csv"
    instrument = dataset_root / "exchange_info.json"
    if sha256_file(funding) != BOUND_FUNDING_SHA256:
        raise RuntimeError("bound_funding_sha256_mismatch")
    if sha256_file(instrument) != BOUND_INSTRUMENT_SHA256:
        raise RuntimeError("bound_instrument_sha256_mismatch")
    return dataset_root, manifest


def funding_rows(dataset_root: Path) -> list[dict[str, Any]]:
    source = dataset_root / "funding_rate.csv"
    selected: list[dict[str, Any]] = []
    with source.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            event_time = parse_utc(row["event_time"])
            if DECISION_START < event_time <= DECISION_END:
                selected.append(
                    {
                        "venue": VENUE,
                        "instrument_id": SWAP_INSTRUMENT,
                        "event_time": utc_z(event_time),
                        "available_time": utc_z(event_time),
                        "rate": row["fundingRate"],
                        "source_record_id": row["source_record_id"],
                        "source_dataset": BOUND_DATASET_ID,
                        "source_version": BOUND_VERSION,
                        "source_sha256": BOUND_FUNDING_SHA256,
                        "valuation_policy": VALUATION_POLICY,
                    }
                )
    if len(selected) != 6:
        raise RuntimeError(f"funding_event_count_expected_6_actual_{len(selected)}")
    if any("mark" in key.lower() or "amount" in key.lower() or "cash" in key.lower() for key in selected[0]):
        raise RuntimeError("funding_forbidden_value_field_present")
    return selected


def instrument_contract(dataset_root: Path) -> dict[str, Any]:
    source = json.loads((dataset_root / "exchange_info.json").read_text(encoding="utf-8"))
    raw = source["raw_symbol_info"]
    if raw.get("instId") != SWAP_INSTRUMENT or raw.get("ctValCcy") != "BTC":
        raise RuntimeError("bound_instrument_identity_or_contract_currency_mismatch")
    return {
        "venue": VENUE,
        "instrument_id": SWAP_INSTRUMENT,
        "authority": "OKX public instruments exchange_info snapshot",
        "contract_value_btc": str(Decimal(str(raw["ctVal"]))),
        "lot_size_contracts": str(Decimal(str(raw["lotSz"]))),
        "minimum_size_contracts": str(Decimal(str(raw["minSz"]))),
        "maximum_market_size_contracts": str(Decimal(str(raw["maxMktSz"]))),
        "source_record_id": f"okx-public-instruments:{SWAP_INSTRUMENT}:{source['captured_at']}",
        "source_dataset": BOUND_DATASET_ID,
        "source_version": BOUND_VERSION,
        "source_sha256": BOUND_INSTRUMENT_SHA256,
        "observed_at": source["captured_at"],
        "available_time": source["available_time"],
        "historical_availability_assumption": "frozen_engineering_contract_assumption_not_june_pit_proof",
    }


def git_head(repo_root: Path) -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo_root, text=True, encoding="utf-8").strip()


def prepare(*, repo_root: Path, shared_root: Path, output_dir: Path, sleep_seconds: float) -> dict[str, Any]:
    if output_dir.exists() and any(output_dir.iterdir()):
        raise RuntimeError(f"output_dir_not_empty:{output_dir}")
    if str(output_dir.resolve()).startswith(str(repo_root.resolve())):
        raise RuntimeError("output_dir_must_be_outside_worktree")
    free_bytes = shutil.disk_usage(shared_root).free
    if free_bytes < 20 * 1024**3:
        raise RuntimeError(f"shared_data_disk_free_below_20gib:{free_bytes}")
    output_dir.mkdir(parents=True, exist_ok=True)
    dataset_root, bound_manifest = validate_bound_inputs(repo_root, shared_root)
    collector = RecordingCollector(output_root=output_dir)
    start_ms = int(WINDOW_START.timestamp() * 1000)
    end_ms = int(WINDOW_END.timestamp() * 1000)
    fetched: dict[str, list[list[str]]] = {}
    specs = {
        "trade": ("candles", SWAP_INSTRUMENT, 8),
        "mark": ("mark_price_candles", SWAP_INSTRUMENT, 5),
        "index": ("index_candles", INDEX_INSTRUMENT, 5),
    }
    quality: dict[str, Any] = {}
    response_start = 0
    for price_type, (name, instrument_id, confirm_index) in specs.items():
        fetched[price_type] = fetch_window(
            collector,
            name=name,
            instrument_id=instrument_id,
            start_ms=start_ms,
            end_ms=end_ms,
            sleep_seconds=sleep_seconds,
        )
        component_responses = collector.responses[response_start:]
        response_start = len(collector.responses)
        for page, response in enumerate(component_responses, start=1):
            write_json(output_dir / "raw" / price_type / f"page-{page:03d}.json", response)
        quality[price_type] = exact_minute_quality(
            fetched[price_type], start_ms=start_ms, end_ms=end_ms, confirm_index=confirm_index
        )
        quality[price_type]["existing_helper_coverage"] = _candle_component_coverage(
            fetched[price_type], interval_ms=INTERVAL_MS, captured_at=WINDOW_END
        )
        quality[price_type]["raw_response_count"] = len(component_responses)
        quality[price_type].update(raw_duplicate_quality(component_responses))
        if quality[price_type]["raw_conflicting_duplicate_count"]:
            quality[price_type]["blockers"].append(
                f"raw_conflicting_duplicate_minutes:{quality[price_type]['raw_conflicting_duplicate_count']}"
            )

    all_blockers = [blocker for component in quality.values() for blocker in component["blockers"]]
    timestamps = {kind: [int(row[0]) for row in rows] for kind, rows in fetched.items()}
    if timestamps["trade"] != timestamps["mark"] or timestamps["trade"] != timestamps["index"]:
        all_blockers.append("trade_mark_index_timestamp_pairing_mismatch")
    if all_blockers:
        write_json(output_dir / "quality_report.json", {"status": "blocked", "components": quality, "blockers": all_blockers})
        raise RuntimeError("minute_input_quality_blocked:" + ";".join(all_blockers))

    fetched_at = max(response["fetched_at"] for response in collector.responses)
    common_fields = [
        "venue", "instrument_id", "price_type", "open_time", "event_time", "close_time", "available_time",
        "ingested_at", "processed_at", "open", "high", "low", "close", "volume", "volume_base",
        "volume_quote", "confirm", "source_record_id", "historical_availability_assumption",
    ]
    for price_type, instrument_id in (("trade", SWAP_INSTRUMENT), ("mark", SWAP_INSTRUMENT), ("index", INDEX_INSTRUMENT)):
        write_csv(
            output_dir / f"{price_type}_1m.csv",
            common_fields,
            candle_rows(fetched[price_type], instrument_id=instrument_id, price_type=price_type, fetched_at=fetched_at),
        )
    funding = funding_rows(dataset_root)
    write_csv(output_dir / "funding_events.csv", list(funding[0]), funding)
    contract = instrument_contract(dataset_root)
    contract_payload = {
        "schema_version": "btc_real_candidate_minute_inputs_contract_v1",
        "dataset_id": DATASET_ID,
        "source_head": git_head(repo_root),
        "window": {
            "open_interval_start": utc_z(WINDOW_START),
            "open_interval_end": utc_z(WINDOW_END),
            "expected_minutes_per_component": EXPECTED_MINUTES,
            "decision_interval_start": utc_z(DECISION_START),
            "decision_interval_end": utc_z(DECISION_END),
            "terminal_tail_is_not_a_new_decision": True,
        },
        "instrument_contract": contract,
        "instrument_contract_context": {
            "settlement_currency": "USDT",
            "maximum_market_size_source_field": "maxMktSz",
            "venue_filter_is_not_strategy_or_risk_permission": True,
            "historical_effective_time_proven": False,
        },
        "funding_policy": {
            "event_count": len(funding),
            "pre_t0_boundary_event_excluded": "2026-06-16T00:00:00Z",
            "valuation_policy": VALUATION_POLICY,
            "amount_precomputed": False,
            "actual_exchange_settlement_mark_available": False,
            "strategy_visibility_role": "settlement_accounting_event_only_not_alpha_input",
        },
        "availability_policy": HISTORICAL_AVAILABILITY_ASSUMPTION,
        "private_endpoint_used": False,
        "order_endpoint_used": False,
    }
    write_json(output_dir / "dataset_contract.json", contract_payload)
    response_inventory = [
        {
            "name": item["name"],
            "endpoint": item["endpoint"],
            "params": item["params"],
            "fetched_at": item["fetched_at"],
            "payload_canonical_sha256": item["payload_canonical_sha256"],
            "hash_basis": item["hash_basis"],
        }
        for item in collector.responses
    ]
    quality_report = {
        "schema_version": "btc_real_candidate_minute_quality_report_v1",
        "status": "pass",
        "generated_at": utc_z(datetime.now(UTC)),
        "window": contract_payload["window"],
        "components": quality,
        "common_timestamp_pair_count": len(timestamps["trade"]),
        "funding_event_count": len(funding),
        "instrument_contract": contract,
        "bound_source": {
            "manifest_sha256": BOUND_MANIFEST_SHA256,
            "aggregate_sha256": bound_manifest["aggregate_sha256"],
            "funding_sha256": BOUND_FUNDING_SHA256,
            "instrument_sha256": BOUND_INSTRUMENT_SHA256,
        },
        "raw_response_inventory": response_inventory,
        "blockers": [],
        "readiness_class": "quality_checked",
        "promotion_evidence_ready": False,
        "paper_or_live_ready": False,
    }
    write_json(output_dir / "quality_report.json", quality_report)
    return quality_report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--shared-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--execute-network", action="store_true")
    parser.add_argument("--request-sleep-seconds", type=float, default=0.12)
    args = parser.parse_args()
    if not args.execute_network:
        print(json.dumps({"status": "dry_run", "network_called": False}, indent=2))
        return 0
    report = prepare(
        repo_root=args.repo_root.resolve(),
        shared_root=args.shared_root.resolve(),
        output_dir=args.output_dir.resolve(),
        sleep_seconds=max(0.0, args.request_sleep_seconds),
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
