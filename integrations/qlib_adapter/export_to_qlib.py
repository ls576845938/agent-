from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import date, datetime, time, timedelta
import json
from pathlib import Path
from typing import Any

import pandas as pd

from quant_us.core.calendar import USEquityCalendar
from quant_us.core.clock import UTC
from quant_us.data.storage.data_manifest import DataManifest, DataManifestStore
from quant_us.data.storage.parquet_store import ParquetBarStore

from .schemas import (
    ExportResult,
    QlibAdapterError,
    build_run_paths,
    ensure_daily_only_bar_size,
    ensure_empty_or_missing,
    load_universe_config,
    make_run_id,
    parse_iso_date,
    to_jsonable,
    utc_now_iso,
    write_json,
)

REQUIRED_COLUMNS = ("timestamp_utc", "symbol", "open", "high", "low", "close", "volume")


def export_to_qlib_input(
    *,
    universe_path: str | Path,
    start_date: str,
    end_date: str,
    data_version: str = "latest",
    run_id: str | None = None,
    data_root: str | Path = "data",
    artifacts_root: str | Path = "artifacts/qlib_runs",
    source: str | None = None,
    asset_class: str = "equity",
    bar_size: str = "1d",
    allow_existing_run_root: bool = False,
) -> ExportResult:
    universe = load_universe_config(universe_path)
    requested_source = str(source or universe.source)
    ensure_daily_only_bar_size(bar_size, context="export request")
    ensure_daily_only_bar_size(universe.bar_size, context="universe config")
    if asset_class != "equity":
        raise QlibAdapterError(f"Qlib adapter phase one only supports equity data, received {asset_class!r}.")

    created_at = utc_now_iso()
    resolved_run_id = run_id or make_run_id("qlib")
    run_paths = build_run_paths(resolved_run_id, artifacts_root, create=False)
    if allow_existing_run_root:
        run_paths.run_root.mkdir(parents=True, exist_ok=True)
    else:
        ensure_empty_or_missing(run_paths.run_root)
    run_paths.qlib_input_csv_dir.mkdir(parents=True, exist_ok=True)

    manifest_path = run_paths.qlib_input_dir / "dataset_manifest.json"
    combined_path = run_paths.qlib_input_dir / "daily_bars.parquet"
    status = "failed"
    error: str | None = None
    symbols_exported: list[str] = []
    rows_exported = 0

    try:
        start = parse_iso_date(start_date)
        end = parse_iso_date(end_date)
        if end < start:
            raise QlibAdapterError("end_date must be on or after start_date")

        manifest_store = DataManifestStore(Path(data_root) / "manifests")
        bar_store = ParquetBarStore(Path(data_root) / "cleaned")
        expected_dates = _expected_trading_dates(start=start, end=end)
        if not expected_dates:
            raise QlibAdapterError(f"No US trading days in requested window {start}..{end}")

        exported_frames: list[pd.DataFrame] = []
        source_manifest_payloads: list[dict[str, Any]] = []
        validation_by_symbol: dict[str, Any] = {}
        missing_symbols: list[str] = []

        for symbol in universe.symbols:
            manifest = _resolve_source_manifest(
                manifest_store=manifest_store,
                symbol=symbol,
                data_version=data_version,
                source=requested_source,
                interval=bar_size,
            )
            if manifest is None:
                missing_symbols.append(symbol)
                continue
            _validate_manifest_contract(manifest=manifest, symbol=symbol, source=requested_source, asset_class=asset_class, bar_size=bar_size)
            frame = _read_cleaned_symbol_frame(
                bar_store=bar_store,
                symbol=symbol,
                source=requested_source,
                asset_class=asset_class,
                bar_size=bar_size,
                start=start,
                end=end,
                requested_data_version=data_version,
            )
            if frame.empty:
                raise QlibAdapterError(
                    f"Cleaned daily parquet is missing for {symbol} in {start.isoformat()}..{end.isoformat()}."
                )
            prepared, validation = _prepare_symbol_export(
                frame=frame,
                symbol=symbol,
                expected_dates=expected_dates,
                source_manifest=manifest,
            )
            exported_frames.append(prepared)
            symbols_exported.append(symbol)
            rows_exported += int(len(prepared))
            validation_by_symbol[symbol] = validation
            source_manifest_payloads.append(
                {
                    "symbol": symbol,
                    "data_version": manifest.data_version,
                    "manifest_path": str((Path(data_root) / "manifests" / f"{manifest.data_version}.json").resolve()),
                    "checksum": manifest.effective_checksum,
                    "quality_score": manifest.quality_score,
                    "coverage_pct": manifest.coverage_pct,
                    "cleaned_path": manifest.cleaned_path,
                }
            )
            _write_symbol_csv(prepared, run_paths.qlib_input_csv_dir / f"{symbol}.csv")

        if missing_symbols:
            raise QlibAdapterError(
                f"Universe requested symbols with no bound daily manifest: {missing_symbols}. "
                "Qlib adapter forbids implicit downloads."
            )
        if not exported_frames:
            raise QlibAdapterError("No symbol data was exported.")
        if universe.strict_calendar_coverage:
            missing_date_summary = {
                symbol: validation["missing_dates"]
                for symbol, validation in validation_by_symbol.items()
                if int(validation.get("missing_rows", 0)) > 0
            }
            if missing_date_summary:
                raise QlibAdapterError(
                    "Universe daily coverage is incomplete for requested window: "
                    f"{_format_missing_date_summary(missing_date_summary)}. "
                    "Qlib adapter fails closed on missing daily bars."
                )

        combined = pd.concat(exported_frames, ignore_index=True).sort_values(["datetime", "symbol"]).reset_index(drop=True)
        duplicate_count = int(combined.duplicated(subset=["datetime", "symbol"]).sum())
        if duplicate_count:
            raise QlibAdapterError(f"Exported dataset has duplicate datetime-symbol rows: {duplicate_count}")
        combined.to_parquet(combined_path, index=False)

        overall_expected = len(expected_dates) * len(universe.symbols)
        overall_missing = sum(int(item["missing_rows"]) for item in validation_by_symbol.values())
        status = "completed"
        dataset_manifest = {
            "run_id": resolved_run_id,
            "status": status,
            "created_at": created_at,
            "mode": "research_only",
            "daily_only": True,
            "input_contract": {
                "source": requested_source,
                "asset_class": asset_class,
                "bar_size": bar_size,
                "data_version_request": data_version,
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
            },
            "universe": to_jsonable(universe),
            "symbols_requested": list(universe.symbols),
            "symbols_exported": list(symbols_exported),
            "missing_symbols": [],
            "calendar": {
                "trading_days": [item.isoformat() for item in expected_dates],
                "expected_rows_per_symbol": len(expected_dates),
                "overall_expected_rows": overall_expected,
                "overall_missing_rows": overall_missing,
                "overall_missing_rate": round((overall_missing / overall_expected) if overall_expected else 0.0, 6),
            },
            "validation": {
                "required_columns": list(REQUIRED_COLUMNS),
                "duplicate_datetime_symbol_rows": duplicate_count,
                "symbols": validation_by_symbol,
            },
            "source_manifests": source_manifest_payloads,
            "files": {
                "dataset_manifest": str(manifest_path.resolve()),
                "daily_bars_parquet": str(combined_path.resolve()),
                "input_csv_dir": str(run_paths.qlib_input_csv_dir.resolve()),
            },
        }
        write_json(manifest_path, dataset_manifest)
        return ExportResult(
            run_id=resolved_run_id,
            status=status,
            dataset_manifest_path=str(manifest_path),
            daily_bars_path=str(combined_path),
            rows_exported=rows_exported,
            symbols_requested=list(universe.symbols),
            symbols_exported=symbols_exported,
            created_at=created_at,
        )
    except Exception as exc:
        error = str(exc)
        failure_manifest = {
            "run_id": resolved_run_id,
            "status": status,
            "created_at": created_at,
            "mode": "research_only",
            "daily_only": True,
            "symbols_requested": list(load_universe_config(universe_path).symbols),
            "symbols_exported": list(symbols_exported),
            "files": {
                "dataset_manifest": str(manifest_path.resolve()),
                "daily_bars_parquet": str(combined_path.resolve()),
                "input_csv_dir": str(run_paths.qlib_input_csv_dir.resolve()),
            },
            "error": error,
        }
        write_json(manifest_path, failure_manifest)
        return ExportResult(
            run_id=resolved_run_id,
            status="failed",
            dataset_manifest_path=str(manifest_path),
            daily_bars_path=str(combined_path),
            rows_exported=rows_exported,
            symbols_requested=list(load_universe_config(universe_path).symbols),
            symbols_exported=symbols_exported,
            created_at=created_at,
            error=error,
        )


def _expected_trading_dates(*, start: date, end: date) -> list[date]:
    calendar = USEquityCalendar.with_holidays()
    current = start
    trading_days: list[date] = []
    while current <= end:
        if calendar.is_trading_day(current):
            trading_days.append(current)
        current = current + timedelta(days=1)
    return trading_days


def _resolve_source_manifest(
    *,
    manifest_store: DataManifestStore,
    symbol: str,
    data_version: str,
    source: str,
    interval: str,
) -> DataManifest | None:
    if data_version == "latest":
        return manifest_store.read_latest(source=source, symbol=symbol, interval=interval)
    manifest = manifest_store.read(data_version)
    if manifest is None:
        raise QlibAdapterError(f"Data manifest not found: {data_version}")
    if manifest.symbol.upper() != symbol.upper():
        raise QlibAdapterError(
            f"Requested symbol {symbol} does not match manifest {manifest.data_version} symbol {manifest.symbol}."
        )
    return manifest


def _validate_manifest_contract(
    *,
    manifest: DataManifest,
    symbol: str,
    source: str,
    asset_class: str,
    bar_size: str,
) -> None:
    if manifest.symbol.upper() != symbol.upper():
        raise QlibAdapterError(f"Manifest symbol mismatch for {symbol}: {manifest.symbol}")
    if manifest.source != source:
        raise QlibAdapterError(f"Manifest source mismatch for {symbol}: expected {source}, got {manifest.source}")
    if manifest.asset_class != asset_class:
        raise QlibAdapterError(
            f"Manifest asset class mismatch for {symbol}: expected {asset_class}, got {manifest.asset_class}"
        )
    if manifest.interval != bar_size:
        raise QlibAdapterError(f"Manifest interval mismatch for {symbol}: expected {bar_size}, got {manifest.interval}")


def _read_cleaned_symbol_frame(
    *,
    bar_store: ParquetBarStore,
    symbol: str,
    source: str,
    asset_class: str,
    bar_size: str,
    start: date,
    end: date,
    requested_data_version: str,
) -> pd.DataFrame:
    frame = bar_store.read_bars(
        vendor=source,
        asset_class=asset_class,
        bar_size=bar_size,
        symbol=symbol,
        start=datetime.combine(start, time.min, tzinfo=UTC),
        end=datetime.combine(end, time.max, tzinfo=UTC),
    )
    if frame.empty:
        return frame
    working = frame.copy()
    if requested_data_version != "latest" and "data_version" in working.columns:
        working = working[working["data_version"] == requested_data_version]
    return working.reset_index(drop=True)


def _prepare_symbol_export(
    *,
    frame: pd.DataFrame,
    symbol: str,
    expected_dates: list[date],
    source_manifest: DataManifest,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    _validate_required_columns(frame=frame, symbol=symbol)

    working = frame.copy()
    working["timestamp_utc"] = pd.to_datetime(working["timestamp_utc"], utc=True)
    working["symbol"] = working["symbol"].astype(str).str.upper()
    working = working[working["symbol"] == symbol.upper()].copy()
    if working.empty:
        raise QlibAdapterError(f"Cleaned frame for {symbol} has no rows after symbol normalization.")

    for column in ("open", "high", "low", "close", "volume"):
        working[column] = pd.to_numeric(working[column], errors="coerce")
    if working[["open", "high", "low", "close", "volume"]].isna().any().any():
        raise QlibAdapterError(f"Cleaned frame for {symbol} contains non-numeric OHLCV values.")

    if int(working.duplicated(subset=["timestamp_utc", "symbol"]).sum()) > 0:
        raise QlibAdapterError(f"Cleaned frame for {symbol} contains duplicate timestamp-symbol rows.")
    if not ((working["open"] > 0) & (working["high"] > 0) & (working["low"] > 0) & (working["close"] > 0)).all():
        raise QlibAdapterError(f"Cleaned frame for {symbol} contains non-positive OHLC values.")
    if not (working["volume"] >= 0).all():
        raise QlibAdapterError(f"Cleaned frame for {symbol} contains negative volume.")
    if not (working["high"] >= working[["open", "close"]].max(axis=1)).all():
        raise QlibAdapterError(f"Cleaned frame for {symbol} violates high >= max(open, close).")
    if not (working["low"] <= working[["open", "close"]].min(axis=1)).all():
        raise QlibAdapterError(f"Cleaned frame for {symbol} violates low <= min(open, close).")

    working["date"] = working["timestamp_utc"].dt.date
    expected_set = set(expected_dates)
    if not set(working["date"]).issubset(expected_set):
        unexpected = sorted(set(working["date"]) - expected_set)
        raise QlibAdapterError(f"Cleaned frame for {symbol} contains rows outside requested trading calendar: {unexpected[:5]}")

    observed_dates = set(working["date"])
    missing_dates = [item.isoformat() for item in expected_dates if item not in observed_dates]
    missing_rows = len(missing_dates)
    working["datetime"] = working["timestamp_utc"]
    working["factor"] = 1.0
    working["data_version"] = source_manifest.data_version
    working["source_manifest_hash"] = source_manifest.effective_checksum
    export_frame = working[
        [
            "datetime",
            "date",
            "symbol",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "factor",
            "data_version",
            "source_manifest_hash",
        ]
    ].sort_values(["date", "symbol"]).reset_index(drop=True)
    validation = {
        "rows": int(len(export_frame)),
        "expected_rows": len(expected_dates),
        "missing_rows": missing_rows,
        "missing_rate": round((missing_rows / len(expected_dates)) if expected_dates else 0.0, 6),
        "missing_dates": missing_dates,
    }
    return export_frame, validation


def _validate_required_columns(*, frame: pd.DataFrame, symbol: str) -> None:
    missing = [name for name in REQUIRED_COLUMNS if name not in frame.columns]
    if missing:
        raise QlibAdapterError(f"Cleaned frame for {symbol} is missing required columns: {missing}")


def _write_symbol_csv(frame: pd.DataFrame, path: Path) -> None:
    output = frame[["date", "symbol", "open", "high", "low", "close", "volume", "factor"]].copy()
    output["date"] = pd.to_datetime(output["date"]).dt.strftime("%Y-%m-%d")
    output.to_csv(path, index=False)


def _format_missing_date_summary(missing_date_summary: dict[str, list[str]]) -> str:
    parts: list[str] = []
    for symbol in sorted(missing_date_summary):
        missing_dates = missing_date_summary[symbol]
        preview = ",".join(missing_dates[:5])
        suffix = "" if len(missing_dates) <= 5 else f"...(+{len(missing_dates) - 5} more)"
        parts.append(f"{symbol}[{preview}{suffix}]")
    return "; ".join(parts)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Export cleaned daily parquet data into Qlib adapter input artifacts.")
    parser.add_argument("--universe", required=True, help="Path to the universe YAML config.")
    parser.add_argument("--start-date", required=True, help="Start date in YYYY-MM-DD.")
    parser.add_argument("--end-date", required=True, help="End date in YYYY-MM-DD.")
    parser.add_argument("--data-version", default="latest", help="Specific data_version or 'latest'.")
    parser.add_argument("--run-id", default="", help="Optional run id. Default creates a new qlib_* run id.")
    parser.add_argument("--data-root", default="data", help="Project data root.")
    parser.add_argument("--artifacts-root", default="artifacts/qlib_runs", help="Qlib artifacts root.")
    parser.add_argument("--source", default="", help="Optional source override. Defaults to universe source.")
    parser.add_argument("--asset-class", default="equity", help="Asset class. Phase one only supports equity.")
    parser.add_argument("--bar-size", default="1d", help="Bar size. Phase one only supports 1d.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = export_to_qlib_input(
        universe_path=args.universe,
        start_date=args.start_date,
        end_date=args.end_date,
        data_version=args.data_version,
        run_id=args.run_id or None,
        data_root=args.data_root,
        artifacts_root=args.artifacts_root,
        source=args.source or None,
        asset_class=args.asset_class,
        bar_size=args.bar_size,
    )
    print(json.dumps(asdict(result), sort_keys=True))
    return 0 if result.status == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
