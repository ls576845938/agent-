"""Immutable market inputs for the shared Qlib provider. No network or execution API."""
from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd

from .schemas import (ExportResult, QlibAdapterError, build_run_paths, read_json,
    ensure_empty_or_missing, make_run_id, to_jsonable, utc_now_iso, write_json)


def validate_instrument_metadata(metadata: dict, *, canonical_symbol: str, instrument: str) -> None:
    raw = metadata.get("raw_symbol_info", {})
    if (not canonical_symbol or not instrument or not isinstance(raw, dict)
        or metadata.get("symbol") != canonical_symbol or metadata.get("venue_symbol") != instrument
        or raw.get("instId") != instrument or raw.get("instType") != "SWAP"
        or raw.get("ctType") != "linear" or raw.get("settleCcy") != "USDT"):
        raise QlibAdapterError("Immutable instrument metadata identity/type mismatch.")


def bind_instrument_identity(rows: pd.DataFrame, *, canonical_symbol: str, instrument: str, kind: str) -> pd.DataFrame:
    prefixes = {"bars": "okx", "mark": "okx-mark", "premium": "okx-premium", "funding": "okx-funding"}
    required = {"symbol", "event_time", "source_record_id"}
    if kind == "funding":
        required.add("instId")
    if not canonical_symbol or not instrument or kind not in prefixes or rows.empty or not required.issubset(rows.columns):
        raise QlibAdapterError(f"{kind}: immutable instrument identity fields missing.")
    times = pd.to_datetime(rows.event_time, utc=True, errors="raise")
    expected_ids = times.map(lambda stamp: f"{prefixes[kind]}:{instrument}:{stamp.value // 1_000_000}")
    if (times.isna().any() or not rows.symbol.eq(canonical_symbol).all()
        or not rows.source_record_id.eq(expected_ids).all()
        or ("instId" in rows and not rows.instId.eq(instrument).all())):
        raise QlibAdapterError(f"{kind}: immutable instrument identity mismatch.")
    frame = rows.copy()
    frame["source_symbol"] = frame.symbol
    frame["symbol"] = instrument
    return frame


def normalize_hourly_input(rows: pd.DataFrame, *, symbol: str, kind: str = "bars") -> pd.DataFrame:
    frame = rows.copy()
    prices = ["mark_close", "index_close"] if kind == "premium" else ["open", "high", "low", "close"]
    required = {"event_time", "available_time", "symbol", "confirm", *prices}
    if kind == "bars":
        required.add("volume_base")
    if not required.issubset(frame.columns) or frame.empty:
        raise QlibAdapterError(f"{kind}: required input fields missing or input empty.")
    if not (frame.symbol.eq(symbol) & pd.to_numeric(frame.confirm).eq(1)).all():
        raise QlibAdapterError(f"{kind}: symbol/finalized contract failed.")
    for key in ("event_time", "available_time"):
        frame[key] = pd.to_datetime(frame[key], utc=True, errors="raise")
    if (frame.event_time.isna().any() or frame.available_time.isna().any()
        or frame.event_time.duplicated().any() or not frame.event_time.is_monotonic_increasing
        or not frame.event_time.eq(frame.event_time.dt.floor("h")).all()
        or not frame.event_time.diff().dropna().eq(pd.Timedelta(hours=1)).all()):
        raise QlibAdapterError(f"{kind}: duplicate, unordered or missing UTC hourly bars.")
    # OKX timestamps denote bar OPEN; completed bar is usable only after its close.
    if not frame.available_time.eq(frame.event_time + pd.Timedelta(hours=1)).all():
        raise QlibAdapterError(f"{kind}: completed-hour availability contract failed.")
    numeric = frame[prices].astype(float)
    if not np.isfinite(numeric.to_numpy()).all() or numeric.le(0).any().any():
        raise QlibAdapterError(f"{kind}: invalid prices.")
    frame[prices] = numeric
    if kind != "premium" and (frame.high.lt(frame[["open", "close", "low"]].max(axis=1)).any()
        or frame.low.gt(frame[["open", "close"]].min(axis=1)).any()):
        raise QlibAdapterError(f"{kind}: invalid OHLC bounds.")
    if kind == "bars":
        frame["volume"] = pd.to_numeric(frame.volume_base, errors="raise")
        if not np.isfinite(frame.volume).all() or frame.volume.lt(0).any():
            raise QlibAdapterError("Invalid base-currency volume.")
        frame["factor"] = 1.0
        frame["datetime"] = frame.event_time
        frame["decision_time"] = frame.available_time
        # Qlib calendar is timezone-naive storage explicitly representing UTC.
        frame["date"] = frame.event_time.dt.strftime("%Y-%m-%d %H:%M:%S")
    return frame


def normalize_funding_input(rows: pd.DataFrame, *, symbol: str) -> pd.DataFrame:
    frame = rows.copy()
    if frame.empty or not {"event_time", "available_time", "symbol", "fundingRate"}.issubset(frame):
        raise QlibAdapterError("Funding fields missing.")
    for key in ("event_time", "available_time"):
        frame[key] = pd.to_datetime(frame[key], utc=True, errors="raise")
    rate = pd.to_numeric(frame.fundingRate, errors="raise")
    if (not frame.symbol.eq(symbol).all() or frame.event_time.isna().any()
        or frame.available_time.isna().any() or frame.event_time.duplicated().any()
        or not frame.event_time.is_monotonic_increasing or not np.isfinite(rate).all()
        or not frame.available_time.ge(frame.event_time).all()
        or not frame.event_time.diff().dropna().eq(pd.Timedelta(hours=8)).all()):
        raise QlibAdapterError("Funding identity/time/coverage contract failed.")
    frame["fundingRate"] = rate
    return frame


def export_immutable_input(*, universe, start_date, end_date, data_version,
                           run_id, artifacts_root, requested_source) -> ExportResult:
    from tools.agent_governance.shared_data import (load_manifest_from_git,
        resolve_manifest_payload, default_shared_data_root)
    binding = universe.data_binding
    if requested_source != universe.source or data_version != binding.get("dataset_version"):
        raise QlibAdapterError("Exact configured source and immutable data_version required.")
    if len(universe.symbols) != 1 or universe.bar_size != "1h":
        raise QlibAdapterError("This immutable profile binds one hourly instrument.")
    repo = Path(__file__).resolve().parents[2]
    git_path = str(binding.get("manifest_path", ""))
    if not git_path.startswith(".agent/data_manifests/") or ".." in git_path.split("/"):
        raise QlibAdapterError("Invalid committed data manifest reference.")
    raw = subprocess.check_output(["git", "show", f"HEAD:{git_path}"], cwd=repo)
    if hashlib.sha256(raw).hexdigest() != binding.get("manifest_sha256"):
        raise QlibAdapterError("Committed manifest hash mismatch.")
    manifest = load_manifest_from_git(repo, f"HEAD:{git_path}")
    if manifest.get("dataset_version") != data_version or manifest.get("dataset_id") != binding.get("dataset_id"):
        raise QlibAdapterError("Manifest dataset identity mismatch.")
    if not binding.get("aggregate_sha256") or manifest.get("aggregate_sha256") != binding["aggregate_sha256"]:
        raise QlibAdapterError("Manifest aggregate hash mismatch.")
    root = resolve_manifest_payload(manifest, shared_root=default_shared_data_root(repo), verify_files=True)
    canonical_symbol = str(binding.get("canonical_symbol", ""))
    instrument = str(binding.get("instrument_id", ""))
    if instrument != universe.symbols[0]:
        raise QlibAdapterError("Configured venue instrument differs from Qlib universe.")
    metadata_record = binding.get("instrument_metadata", {})
    metadata_path = (root / metadata_record.get("path", "")).resolve()
    if (not metadata_path.is_relative_to(root.resolve()) or not metadata_path.is_file()
        or hashlib.sha256(metadata_path.read_bytes()).hexdigest() != metadata_record.get("sha256")):
        raise QlibAdapterError("Immutable instrument metadata hash/path mismatch.")
    validate_instrument_metadata(read_json(metadata_path), canonical_symbol=canonical_symbol, instrument=instrument)
    inputs = {}
    for kind, record in binding["files"].items():
        path = (root / record["path"]).resolve()
        if not path.is_relative_to(root.resolve()) or path == root.resolve():
            raise QlibAdapterError("Input file escapes immutable dataset.")
        if hashlib.sha256(path.read_bytes()).hexdigest() != record["sha256"]:
            raise QlibAdapterError(f"{kind}: input hash mismatch.")
        frame = pd.read_csv(path)
        frame = bind_instrument_identity(frame, canonical_symbol=canonical_symbol, instrument=instrument, kind=kind)
        inputs[kind] = (normalize_funding_input(frame, symbol=universe.symbols[0]) if kind == "funding"
            else normalize_hourly_input(frame, symbol=universe.symbols[0], kind=kind))
    expected = pd.date_range(start_date, end_date, freq="h", tz="UTC")
    selected = inputs["bars"][inputs["bars"].datetime.isin(expected)].copy()
    if expected.empty or len(selected) != len(expected):
        raise QlibAdapterError("Requested window is not fully covered by complete UTC hours.")
    for kind in ("mark", "premium"):
        if not inputs[kind].event_time.equals(inputs["bars"].event_time):
            raise QlibAdapterError(f"{kind}: price calendar identity mismatch.")
    identity = run_id or make_run_id("qlib")
    paths = build_run_paths(identity, artifacts_root)
    ensure_empty_or_missing(paths.run_root)
    paths.qlib_input_csv_dir.mkdir(parents=True, exist_ok=True)
    bars_path = paths.qlib_input_dir / "daily_bars.parquet"  # retain legacy API field/file
    selected.to_parquet(bars_path, index=False)
    selected.to_csv(paths.qlib_input_csv_dir / f"{universe.symbols[0]}.csv", index=False)
    files = {"daily_bars_parquet": str(bars_path.resolve()), "input_csv_dir": str(paths.qlib_input_csv_dir.resolve())}
    hashes = {"daily_bars_parquet": hashlib.sha256(bars_path.read_bytes()).hexdigest()}
    for kind in ("funding", "mark", "premium"):
        path = paths.qlib_input_dir / f"{kind}.parquet"
        inputs[kind].to_parquet(path, index=False)
        files[kind] = str(path.resolve())
        hashes[kind] = hashlib.sha256(path.read_bytes()).hexdigest()
    created = utc_now_iso()
    manifest_path = paths.qlib_input_dir / "dataset_manifest.json"
    payload = {"run_id": identity, "status": "completed", "created_at": created,
        "mode": "research_only", "daily_only": False, "universe": to_jsonable(universe),
        "symbols_requested": universe.symbols, "symbols_exported": universe.symbols,
        "input_contract": {"asset_class": "crypto", "instrument_type": "linear_perpetual", "bar_size": "1h",
            "source": universe.source, "start_date": start_date, "end_date": end_date,
            "data_version_request": data_version, "aggregate_sha256": binding["aggregate_sha256"],
            "instrument_identity": {"source_symbol": canonical_symbol, "venue_instrument_id": instrument,
                "qlib_instrument": universe.symbols[0],
                "metadata_path": metadata_record["path"], "metadata_sha256": metadata_record["sha256"],
                "row_binding": "exact_kind_venue_instrument_event_epoch_ms", "source_symbol_preserved": True},
            "annualization": 8760, "volume_unit": "BTC"},
        "calendar": {"name": "UTC_24x7", "qlib_freq": "60min", "trading_days": selected.date.tolist(),
            "expected_rows_per_symbol": len(expected), "overall_missing_rows": 0},
        "validation": {"finalized_only": True, "funding_events": len(inputs["funding"]),
            "funding_start": inputs["funding"].event_time.min().isoformat(),
            "funding_end": inputs["funding"].event_time.max().isoformat(),
            "available_time_semantics": "reconstructed_bar_close_not_original_receipt",
            "missing_funding_policy": "unknown_never_zero_fill"},
        "source_manifests": [{"symbol": universe.symbols[0], "data_version": data_version,
            "manifest_path": git_path, "checksum": binding["files"]["bars"]["sha256"],
            "manifest_sha256": binding["manifest_sha256"], "aggregate_sha256": binding["aggregate_sha256"],
            "readiness": "quality_checked"}],
        "files": {"dataset_manifest": str(manifest_path.resolve()), **files}, "file_hashes": hashes,
        "input_sha256": hashes["daily_bars_parquet"],
        "restrictions": ["historical_perpetual_research", "funding_cost_overlap_only", "no_historical_oi_or_liquidation_evidence",
            "no_original_receipt_time_evidence", "no_paper_or_live_permission"]}
    write_json(manifest_path, payload)
    return ExportResult(identity, "completed", str(manifest_path), str(bars_path), len(selected),
                        universe.symbols, universe.symbols, created)
