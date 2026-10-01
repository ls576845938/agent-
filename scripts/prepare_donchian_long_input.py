"""One fixed data-only binding for Donchian history. Never trains or runs a strategy.

Reuse the shared Qlib normalizers; retain the immutable upstream and append only
the real funding settlement at the evaluation's right boundary in a new dataset.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import pandas as pd
from integrations.qlib_adapter.market_data import (
    bind_instrument_identity, normalize_hourly_input, normalize_funding_input,
    validate_instrument_metadata,
)
from quant_crypto.data.okx_swap_public import OkxSwapPublicCollector
from quant_crypto.application.donchian_history_spec import HistorySpec, legacy_spec, validate_tables
from tools.agent_governance.shared_data import load_manifest_from_git, resolve_manifest_payload, default_shared_data_root

UPSTREAM = "03989606cebe675559b5cdcc9929baae96e8daec:.agent/data_manifests/okx-btc-long-history/okx-btc-1h-20250213-20260901-v2.json"
MANIFEST_SHA = "ad4645697aa9b9c92f7781ddbe6d9f7bd52acd0488392f517d361adf08fb5d89"
AGGREGATE = "beb549f989173170ed2a4a99386f07e879aa565dbbfb27b6e0336cea3d1a5815"
BOUNDARY_SOURCE = "56d6bd340116591d74f1bdb61614a0d4f2e9a014:.agent/data_manifests/donchian-long-input/donchian-long-input-20260921-v1.json"
END = pd.Timestamp("2026-09-01T00:00:00Z")
WINDOW = {"warmup_start": "2025-02-13T00:00:00+00:00", "evaluation_start": "2025-09-01T00:00:00+00:00",
          "evaluation_end": END.isoformat(), "requested_months": 12,
          "selection_reason": "fixed_complete_calendar_year_before_collection_not_selected_by_returns"}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def dump(path, value):
    path.write_text(json.dumps(value, sort_keys=True, indent=2, allow_nan=False)+"\n", encoding="utf-8")


def terminal_funding_row(receipt, prior):
    payload = receipt["payload"]
    if payload.get("code") != "0" or not isinstance(payload.get("data"), list):
        raise ValueError("public_funding_response_invalid")
    prior_rates = {int(pd.Timestamp(r.event_time).timestamp()*1000): Decimal(str(r.fundingRate))
                   for r in prior.itertuples()}
    seen, selected, overlap = set(), None, 0
    for r in payload["data"]:
        stamp, rate = int(r["fundingTime"]), Decimal(r["fundingRate"])
        if r["instId"] != "BTC-USDT-SWAP" or stamp % 28800000 or not rate.is_finite() or stamp in seen:
            raise ValueError("public_funding_identity_time_rate_or_duplicate_invalid")
        seen.add(stamp)
        if stamp in prior_rates:
            if abs(rate-prior_rates[stamp]) > Decimal("1e-14"):
                raise ValueError("terminal_funding_overlap_conflict")
            overlap += 1
        if stamp == int(END.timestamp()*1000):
            selected = r
    if selected is None or overlap == 0:
        raise ValueError("terminal_funding_actual_record_and_overlap_required")
    # No fake settlement mark and no future-hour price. The frozen history
    # engine already uses explicitly labelled t-1h visible mark approximation.
    row = {"symbol": "BTCUSDT", "venue": "okx", "instId": "BTC-USDT-SWAP",
           "event_time": END.isoformat(), "available_time": END.isoformat(),
           "ingested_at": receipt["captured_at"], "fundingTime": int(selected["fundingTime"]),
           "fundingRate": selected["fundingRate"],
           "realizedRate": float(selected["realizedRate"]) if selected.get("realizedRate") else None,
           "markPrice": None, "source_record_id": f"okx-funding:BTC-USDT-SWAP:{selected['fundingTime']}",
           "source_raw_payload_hash": sha(json.dumps(payload, sort_keys=True).encode()),
           "funding_source": "okx_public_rest_terminal_boundary",
           "availability_basis": "historical_event_schedule_not_archival_publication_time",
           "quality_flags": "settlement_mark_missing;historical_availability_assumption",
           "data_version": "donchian-long-input-20260921-v2", "adjustment_policy": "none"}
    return row, overlap


def funding_numeric_missing(frame):
    # A wholly empty object column serializes as Arrow null / Python None.
    # The reviewed consumer expects a numeric missing mark (NaN), never zero.
    frame = frame.copy()
    frame["markPrice"] = pd.to_numeric(frame["markPrice"], errors="raise").astype(float)
    return frame


def prepare(output, network=False):
    output = Path(output).resolve()
    shared = default_shared_data_root(REPO).resolve()
    if shared / ".staging" not in output.parents or shutil.disk_usage(output.anchor).free < 20*1024**3:
        raise ValueError("dedicated_external_staging_and_20gib_required")
    raw = subprocess.check_output(["git", "show", UPSTREAM], cwd=REPO)
    if sha(raw) != MANIFEST_SHA:
        raise ValueError("upstream_manifest_hash_mismatch")
    manifest = load_manifest_from_git(REPO, UPSTREAM)
    if manifest["aggregate_sha256"] != AGGREGATE:
        raise ValueError("upstream_aggregate_mismatch")
    source = resolve_manifest_payload(manifest, shared_root=shared, verify_files=True)
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip()
    identity = {"upstream": UPSTREAM, "manifest_sha256": MANIFEST_SHA, "aggregate_sha256": AGGREGATE,
                "code_version": head, "window": WINDOW, "boundary_source": BOUNDARY_SOURCE}
    output.mkdir(parents=True, exist_ok=True)
    lock = output.parent / (output.name+".lock")
    fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    try:
        identity_path = output / "binding_identity.json"
        if identity_path.exists() and json.loads(identity_path.read_text()) != identity:
            raise ValueError("binding_identity_changed")
        if not identity_path.exists(): dump(identity_path, identity)
        seal_path = output / "binding_seal.json"
        if seal_path.exists():
            seal = json.loads(seal_path.read_text())
            if any(not (output/p).is_file() or sha((output/p).read_bytes()) != h for p,h in seal["files"].items()):
                raise ValueError("binding_seal_mismatch")
            return seal
        inputs = source / "qlib_input"
        validate_instrument_metadata(json.loads((inputs/"exchange_info.json").read_text()),
                                     canonical_symbol="BTCUSDT", instrument="BTC-USDT-SWAP")
        prior = pd.read_csv(inputs/"funding_rate.csv")
        receipt_path = output/"terminal_funding_public_receipt.json"
        if not receipt_path.exists():
            # The single public response was already published. Reuse verified
            # immutable bytes rather than calling the network again.
            boundary_manifest = load_manifest_from_git(REPO, BOUNDARY_SOURCE)
            boundary_root = resolve_manifest_payload(boundary_manifest, shared_root=shared, verify_files=True)
            shutil.copyfile(boundary_root/receipt_path.name, receipt_path)
        receipt = json.loads(receipt_path.read_text())
        terminal, overlap = terminal_funding_row(receipt, prior)
        frames = {}
        for kind, name in (("bars","klines_1h.csv"), ("mark","mark_price_klines_1h.csv"),
                           ("premium","premium_index_klines_1h.csv"), ("funding","funding_rate.csv")):
            frame = pd.read_csv(inputs/name)
            if kind == "funding": frame = pd.concat([frame, pd.DataFrame([terminal])], ignore_index=True)
            frame = bind_instrument_identity(frame, canonical_symbol="BTCUSDT", instrument="BTC-USDT-SWAP", kind=kind)
            frames[kind] = normalize_funding_input(frame, symbol="BTC-USDT-SWAP") if kind == "funding" else normalize_hourly_input(frame, symbol="BTC-USDT-SWAP", kind=kind)
            if kind == "funding": frames[kind] = funding_numeric_missing(frames[kind])
        payload = legacy_spec().payload
        payload["window"] = WINDOW
        validate_tables(HistorySpec.from_payload(payload), *(frames[k] for k in ("bars","mark","premium","funding")))
        target = output/"history_input"
        target.mkdir(exist_ok=True)
        for kind, frame in frames.items():
            frame.to_parquet(target/("daily_bars.parquet" if kind == "bars" else kind+".parquet"), index=False)
        seal = {"status": "quality_checked", "network_accessed_this_transform": False, "terminal_records_added": 1,
                "rest_overlap_matches": overlap, "warmup_hours":4800, "evaluation_hours":8760,
                "settlements_after_start_through_terminal":1095, "funding_input_rows":len(frames["funding"]),
                "strategy_executed":False, "permissions_granted":False, "upstream":identity,
                "limitations":["reconstructed_availability_not_original_receipt", "settlement_mark_missing",
                               "derived_basis_not_official_premium_index", "no_historical_depth_or_rule_lineage"],
                "files":{p.relative_to(output).as_posix():sha(p.read_bytes()) for p in sorted(output.rglob("*")) if p.is_file()}}
        dump(seal_path, seal)
        return seal
    finally:
        os.close(fd)
        lock.unlink()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--execute-public-network", action="store_true")
    args = parser.parse_args()
    print(json.dumps(prepare(args.output, args.execute_public_network), sort_keys=True, indent=2))
