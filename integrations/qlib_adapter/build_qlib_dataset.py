from __future__ import annotations

import argparse
from dataclasses import asdict
from pathlib import Path
import shutil

import numpy as np
import pandas as pd

from .export_to_qlib import export_to_qlib_input
from .schemas import (
    BuildQlibDatasetResult,
    ExportResult,
    MissingDependencyError,
    QlibAdapterError,
    build_run_paths,
    optional_import_any,
    optional_import,
    read_json,
    utc_now_iso,
    write_json,
)


def build_qlib_dataset(
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
    dry_run: bool = False,
    max_workers: int = 4,
) -> BuildQlibDatasetResult:
    export_result = export_to_qlib_input(
        universe_path=universe_path,
        start_date=start_date,
        end_date=end_date,
        data_version=data_version,
        run_id=run_id,
        data_root=data_root,
        artifacts_root=artifacts_root,
        source=source,
        asset_class=asset_class,
        bar_size=bar_size,
    )
    return build_qlib_provider(
        export_result=export_result,
        artifacts_root=artifacts_root,
        dry_run=dry_run,
        max_workers=max_workers,
    )


def build_qlib_provider(
    *,
    export_result: ExportResult,
    artifacts_root: str | Path = "artifacts/qlib_runs",
    dry_run: bool = False,
    max_workers: int = 4,
) -> BuildQlibDatasetResult:
    created_at = utc_now_iso()
    run_paths = build_run_paths(export_result.run_id, artifacts_root, create=False)
    provider_manifest_path = run_paths.run_root / "provider_manifest.json"

    if export_result.status != "completed":
        failure = BuildQlibDatasetResult(
            run_id=export_result.run_id,
            status="failed",
            dataset_manifest_path=export_result.dataset_manifest_path,
            provider_manifest_path=str(provider_manifest_path),
            provider_dir=str(run_paths.qlib_provider_dir),
            created_at=created_at,
            error=export_result.error or "export failed",
        )
        write_json(provider_manifest_path, asdict(failure))
        return failure

    dump_module = None
    provider_builder = "qlib_dump_bin"
    if not dry_run:
        try:
            dump_module = optional_import_any(
                ["scripts.dump_bin", "qlib.scripts.dump_bin"],
                required_by="build_qlib_dataset",
                install_hint="Install pyqlib and ensure the dump_bin module is available.",
            )
        except MissingDependencyError as exc:
            try:
                optional_import(
                    "qlib",
                    required_by="build_qlib_dataset",
                    install_hint="Install pyqlib before building a Qlib provider.",
                )
                provider_builder = "native_file_provider"
            except MissingDependencyError:
                failure = BuildQlibDatasetResult(
                    run_id=export_result.run_id,
                    status="failed",
                    dataset_manifest_path=export_result.dataset_manifest_path,
                    provider_manifest_path=str(provider_manifest_path),
                    provider_dir=str(run_paths.qlib_provider_dir),
                    created_at=created_at,
                    error=str(exc),
                )
                write_json(
                    provider_manifest_path,
                    {
                        **asdict(failure),
                        "dry_run": False,
                        "dependency_status": "missing",
                    },
                )
                return failure
            write_json(
                provider_manifest_path.with_suffix(".fallback_reason.json"),
                {
                    "run_id": export_result.run_id,
                    "fallback": "native_file_provider",
                    "reason": str(exc),
                    "created_at": created_at,
                },
            )

    run_paths.qlib_provider_dir.mkdir(parents=True, exist_ok=True)
    dataset_manifest = read_json(export_result.dataset_manifest_path)
    if dry_run:
        result = BuildQlibDatasetResult(
            run_id=export_result.run_id,
            status="dry_run",
            dataset_manifest_path=export_result.dataset_manifest_path,
            provider_manifest_path=str(provider_manifest_path),
            provider_dir=str(run_paths.qlib_provider_dir),
            created_at=created_at,
        )
        write_json(
            provider_manifest_path,
            {
                **asdict(result),
                "dry_run": True,
                "dependency_status": "skipped",
                "input_csv_dir": dataset_manifest["files"]["input_csv_dir"],
            },
        )
        return result

    if provider_builder == "qlib_dump_bin":
        dump_class = getattr(dump_module, "DumpDataAll", None)
        if dump_class is None:
            raise QlibAdapterError("Qlib dump_bin module does not expose DumpDataAll.")
        dumper = dump_class(
            data_path=dataset_manifest["files"]["input_csv_dir"],
            qlib_dir=str(run_paths.qlib_provider_dir),
            freq="day",
            max_workers=max_workers,
            date_field_name="date",
            file_suffix=".csv",
            symbol_field_name="symbol",
            include_fields="open,high,low,close,volume,factor",
        )
        dumper.dump()
    else:
        _build_native_file_provider(dataset_manifest=dataset_manifest, provider_dir=run_paths.qlib_provider_dir)
    result = BuildQlibDatasetResult(
        run_id=export_result.run_id,
        status="completed",
        dataset_manifest_path=export_result.dataset_manifest_path,
        provider_manifest_path=str(provider_manifest_path),
        provider_dir=str(run_paths.qlib_provider_dir),
        created_at=created_at,
    )
    write_json(
        provider_manifest_path,
        {
            **asdict(result),
            "dry_run": False,
            "dependency_status": "available",
            "provider_builder": provider_builder,
            "input_csv_dir": dataset_manifest["files"]["input_csv_dir"],
        },
    )
    return result


def _build_native_file_provider(*, dataset_manifest: dict, provider_dir: Path) -> None:
    """Write Qlib's file-storage provider format when dump_bin is unavailable.

    PyPI pyqlib exposes the file storage reader but not always the historical
    ``qlib.scripts.dump_bin`` helper.  This writer keeps the same on-disk
    contract: calendars/day.txt, instruments/all.txt, and one float32 binary
    file per instrument-field with the first float storing the start index.
    """

    calendar = list(dataset_manifest.get("calendar", {}).get("trading_days", []))
    symbols = [str(symbol).upper() for symbol in dataset_manifest.get("symbols_exported", [])]
    daily_bars_path = Path(dataset_manifest.get("files", {}).get("daily_bars_parquet", ""))
    if not calendar:
        raise QlibAdapterError("Dataset manifest has no trading day calendar.")
    if not symbols:
        raise QlibAdapterError("Dataset manifest has no exported symbols.")
    if not daily_bars_path.exists():
        raise QlibAdapterError(f"Daily bars parquet not found for native provider build: {daily_bars_path}")

    frame = pd.read_parquet(daily_bars_path)
    required = {"date", "symbol", "open", "high", "low", "close", "volume", "factor"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise QlibAdapterError(f"Daily bars parquet is missing required provider columns: {missing}")

    if provider_dir.exists():
        shutil.rmtree(provider_dir)
    (provider_dir / "calendars").mkdir(parents=True, exist_ok=True)
    (provider_dir / "instruments").mkdir(parents=True, exist_ok=True)
    (provider_dir / "features").mkdir(parents=True, exist_ok=True)

    (provider_dir / "calendars" / "day.txt").write_text("\n".join(calendar) + "\n", encoding="utf-8")
    first_day = calendar[0]
    last_day = calendar[-1]
    instruments_payload = "".join(f"{symbol}\t{first_day}\t{last_day}\n" for symbol in symbols)
    (provider_dir / "instruments" / "all.txt").write_text(instruments_payload, encoding="utf-8")

    working = frame.copy()
    working["date"] = pd.to_datetime(working["date"]).dt.strftime("%Y-%m-%d")
    working["symbol"] = working["symbol"].astype(str).str.upper()
    fields = ["open", "high", "low", "close", "volume", "factor"]
    calendar_index = pd.Index(calendar, name="date")

    for symbol in symbols:
        symbol_frame = (
            working[working["symbol"] == symbol]
            .drop_duplicates(subset=["date"], keep="last")
            .set_index("date")
            .reindex(calendar_index)
        )
        if symbol_frame[fields].isna().any().any():
            missing_dates = symbol_frame.index[symbol_frame[fields].isna().any(axis=1)].tolist()
            raise QlibAdapterError(
                f"Native provider build found missing daily bars for {symbol}: {missing_dates[:5]}"
            )
        symbol_dir = provider_dir / "features" / symbol.lower()
        symbol_dir.mkdir(parents=True, exist_ok=True)
        for field in fields:
            values = pd.to_numeric(symbol_frame[field], errors="raise").astype("float32").to_numpy()
            output = np.hstack([np.array([0.0], dtype="<f4"), values.astype("<f4")])
            output.tofile(symbol_dir / f"{field}.day.bin")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Export daily bars and build a Qlib provider directory.")
    parser.add_argument("--universe", required=True, help="Path to the universe YAML config.")
    parser.add_argument("--start-date", required=True, help="Start date in YYYY-MM-DD.")
    parser.add_argument("--end-date", required=True, help="End date in YYYY-MM-DD.")
    parser.add_argument("--data-version", default="latest", help="Specific data_version or 'latest'.")
    parser.add_argument("--run-id", default="", help="Optional run id.")
    parser.add_argument("--data-root", default="data", help="Project data root.")
    parser.add_argument("--artifacts-root", default="artifacts/qlib_runs", help="Qlib artifacts root.")
    parser.add_argument("--source", default="", help="Optional source override.")
    parser.add_argument("--asset-class", default="equity", help="Asset class. Phase one only supports equity.")
    parser.add_argument("--bar-size", default="1d", help="Bar size. Phase one only supports 1d.")
    parser.add_argument("--dry-run", action="store_true", help="Validate export inputs without importing Qlib.")
    parser.add_argument("--max-workers", type=int, default=4, help="Worker count for qlib dump_bin.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = build_qlib_dataset(
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
        dry_run=args.dry_run,
        max_workers=args.max_workers,
    )
    import json

    print(json.dumps(asdict(result), sort_keys=True))
    return 0 if result.status in {"completed", "dry_run"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
