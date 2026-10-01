from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, time
import json
from pathlib import Path
from typing import Any

from quant_us.core.clock import UTC
from quant_us.data.pipeline import DataLakeConfig, DataLakeService
from quant_us.data.storage.data_manifest import DataManifestStore

from .build_qlib_dataset import build_qlib_provider
from .export_to_qlib import export_to_qlib_input
from .schemas import (
    PrepareDailyDataResult,
    QlibAdapterError,
    build_run_paths,
    load_universe_config,
    make_run_id,
    parse_iso_date,
    utc_now_iso,
    write_json,
)


def prepare_real_daily_data(
    *,
    universe_path: str | Path,
    start_date: str,
    end_date: str,
    run_id: str | None = None,
    data_root: str | Path = "data",
    artifacts_root: str | Path = "artifacts/qlib_runs",
    source: str | None = None,
    asset_class: str = "equity",
    bar_size: str = "1d",
    sync_yfinance: bool = False,
    build_provider: bool = False,
    dry_run: bool = False,
    max_workers: int = 4,
) -> PrepareDailyDataResult:
    created_at = utc_now_iso()
    universe = load_universe_config(universe_path)
    requested_source = str(source or universe.source)
    if requested_source != "yfinance":
        raise QlibAdapterError(
            f"prepare_real_daily_data only supports explicit yfinance sync, received {requested_source!r}."
        )
    if asset_class != "equity":
        raise QlibAdapterError(f"prepare_real_daily_data only supports equity data, received {asset_class!r}.")
    if bar_size.lower() != "1d":
        raise QlibAdapterError(f"prepare_real_daily_data is daily-only, received {bar_size!r}.")

    start = parse_iso_date(start_date)
    end = parse_iso_date(end_date)
    if end < start:
        raise QlibAdapterError("end_date must be on or after start_date")

    resolved_run_id = run_id or make_run_id("qlib_prepare")
    run_paths = build_run_paths(resolved_run_id, artifacts_root, create=False)
    prepare_manifest_path = run_paths.run_root / "daily_data_prepare_manifest.json"
    provider_manifest_path = run_paths.run_root / "provider_manifest.json"
    dataset_manifest_path = run_paths.qlib_input_dir / "dataset_manifest.json"
    run_paths.run_root.mkdir(parents=True, exist_ok=True)

    manifest_store = DataManifestStore(Path(data_root) / "manifests")
    manifest_candidates_before = _collect_manifest_candidates(
        manifest_store=manifest_store,
        symbols=universe.symbols,
        source=requested_source,
        bar_size=bar_size,
        start_date=start.isoformat(),
        end_date=end.isoformat(),
        data_root=data_root,
    )

    sync_results: list[dict[str, Any]] = []
    export_result = None
    provider_result = None
    status = "failed"
    error: str | None = None

    try:
        if sync_yfinance and not dry_run:
            service = DataLakeService(DataLakeConfig(data_root=Path(data_root)))
            sync_start = datetime.combine(start, time.min, tzinfo=UTC)
            sync_end = datetime.combine(end, time.max, tzinfo=UTC)
            for symbol in universe.symbols:
                sync_result = service.sync_bars(
                    symbol=symbol,
                    start=sync_start,
                    end=sync_end,
                    bar_size=bar_size,
                    vendor=requested_source,
                    asset_class=asset_class,
                )
                sync_results.append(
                    {
                        "symbol": sync_result.symbol,
                        "status": sync_result.status,
                        "rows_received": sync_result.rows_received,
                        "rows_cleaned": sync_result.rows_cleaned,
                        "data_version": sync_result.data_version,
                        "data_manifest_path": sync_result.data_manifest_path,
                        "error": sync_result.error,
                    }
                )
            sync_failures = [item for item in sync_results if item.get("error")]
            if sync_failures:
                raise QlibAdapterError(
                    "Explicit yfinance sync failed for: "
                    + ", ".join(f"{item['symbol']} ({item['error']})" for item in sync_failures)
                )
        elif sync_yfinance and dry_run:
            sync_results = [{"symbol": symbol, "status": "planned"} for symbol in universe.symbols]

        manifest_candidates_after = _collect_manifest_candidates(
            manifest_store=manifest_store,
            symbols=universe.symbols,
            source=requested_source,
            bar_size=bar_size,
            start_date=start.isoformat(),
            end_date=end.isoformat(),
            data_root=data_root,
        )

        export_result = export_to_qlib_input(
            universe_path=universe_path,
            start_date=start.isoformat(),
            end_date=end.isoformat(),
            data_version="latest",
            run_id=resolved_run_id,
            data_root=data_root,
            artifacts_root=artifacts_root,
            source=requested_source,
            asset_class=asset_class,
            bar_size=bar_size,
            allow_existing_run_root=True,
        )
        if export_result.status != "completed":
            raise QlibAdapterError(export_result.error or "Qlib export failed.")

        if build_provider:
            provider_result = build_qlib_provider(
                export_result=export_result,
                artifacts_root=artifacts_root,
                dry_run=dry_run,
                max_workers=max_workers,
            )
            if provider_result.status not in {"completed", "dry_run"}:
                raise QlibAdapterError(provider_result.error or "Qlib provider build failed.")

        status = "dry_run" if dry_run else "completed"
        payload = _prepare_manifest_payload(
            run_id=resolved_run_id,
            status=status,
            created_at=created_at,
            universe_path=universe_path,
            source=requested_source,
            start_date=start.isoformat(),
            end_date=end.isoformat(),
            sync_yfinance=sync_yfinance,
            build_provider=build_provider,
            dry_run=dry_run,
            manifest_candidates_before=manifest_candidates_before,
            manifest_candidates_after=manifest_candidates_after,
            sync_results=sync_results,
            export_result=asdict(export_result),
            provider_result=asdict(provider_result) if provider_result is not None else None,
        )
        write_json(prepare_manifest_path, payload)
        return PrepareDailyDataResult(
            run_id=resolved_run_id,
            status=status,
            prepare_manifest_path=str(prepare_manifest_path),
            dataset_manifest_path=export_result.dataset_manifest_path,
            provider_manifest_path=str(provider_manifest_path),
            provider_dir=str(run_paths.qlib_provider_dir),
            created_at=created_at,
        )
    except Exception as exc:
        error = str(exc)
        manifest_candidates_after = _collect_manifest_candidates(
            manifest_store=manifest_store,
            symbols=universe.symbols,
            source=requested_source,
            bar_size=bar_size,
            start_date=start.isoformat(),
            end_date=end.isoformat(),
            data_root=data_root,
        )
        payload = _prepare_manifest_payload(
            run_id=resolved_run_id,
            status="failed",
            created_at=created_at,
            universe_path=universe_path,
            source=requested_source,
            start_date=start.isoformat(),
            end_date=end.isoformat(),
            sync_yfinance=sync_yfinance,
            build_provider=build_provider,
            dry_run=dry_run,
            manifest_candidates_before=manifest_candidates_before,
            manifest_candidates_after=manifest_candidates_after,
            sync_results=sync_results,
            export_result=asdict(export_result) if export_result is not None else None,
            provider_result=asdict(provider_result) if provider_result is not None else None,
            error=error,
        )
        write_json(prepare_manifest_path, payload)
        return PrepareDailyDataResult(
            run_id=resolved_run_id,
            status="failed",
            prepare_manifest_path=str(prepare_manifest_path),
            dataset_manifest_path=str(dataset_manifest_path),
            provider_manifest_path=str(provider_manifest_path),
            provider_dir=str(run_paths.qlib_provider_dir),
            created_at=created_at,
            error=error,
        )


def _collect_manifest_candidates(
    *,
    manifest_store: DataManifestStore,
    symbols: list[str],
    source: str,
    bar_size: str,
    start_date: str,
    end_date: str,
    data_root: str | Path,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for symbol in symbols:
        manifest = manifest_store.read_latest(source=source, symbol=symbol, interval=bar_size)
        if manifest is None:
            candidates.append({"symbol": symbol, "status": "missing"})
            continue
        candidates.append(
            {
                "symbol": symbol,
                "status": "available",
                "data_version": manifest.data_version,
                "manifest_path": str((Path(data_root) / "manifests" / f"{manifest.data_version}.json").resolve()),
                "coverage_pct": manifest.coverage_pct,
                "quality_score": manifest.quality_score,
                "start": manifest.start,
                "end": manifest.end,
                "covers_requested_window": bool(manifest.start <= start_date and manifest.end >= end_date),
            }
        )
    return candidates


def _prepare_manifest_payload(
    *,
    run_id: str,
    status: str,
    created_at: str,
    universe_path: str | Path,
    source: str,
    start_date: str,
    end_date: str,
    sync_yfinance: bool,
    build_provider: bool,
    dry_run: bool,
    manifest_candidates_before: list[dict[str, Any]],
    manifest_candidates_after: list[dict[str, Any]],
    sync_results: list[dict[str, Any]],
    export_result: dict[str, Any] | None,
    provider_result: dict[str, Any] | None,
    error: str | None = None,
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "status": status,
        "created_at": created_at,
        "mode": "research_only",
        "daily_only": True,
        "prepare_command": {
            "source": source,
            "sync_yfinance": sync_yfinance,
            "build_provider": build_provider,
            "dry_run": dry_run,
            "universe_path": str(Path(universe_path).resolve()),
            "start_date": start_date,
            "end_date": end_date,
        },
        "manifest_candidates_before_sync": manifest_candidates_before,
        "manifest_candidates_after_sync": manifest_candidates_after,
        "sync_results": sync_results,
        "export_result": export_result,
        "provider_result": provider_result,
        "error": error,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Explicitly sync real daily yfinance data, generate manifests, and export to Qlib artifacts."
    )
    parser.add_argument("--universe", required=True, help="Path to the universe YAML config.")
    parser.add_argument("--start-date", required=True, help="Start date in YYYY-MM-DD.")
    parser.add_argument("--end-date", required=True, help="End date in YYYY-MM-DD.")
    parser.add_argument("--run-id", default="", help="Optional run id.")
    parser.add_argument("--data-root", default="data", help="Project data root.")
    parser.add_argument("--artifacts-root", default="artifacts/qlib_runs", help="Qlib artifacts root.")
    parser.add_argument("--source", default="", help="Optional source override. Only yfinance is supported.")
    parser.add_argument("--asset-class", default="equity", help="Asset class. Daily preparation only supports equity.")
    parser.add_argument("--bar-size", default="1d", help="Bar size. Daily preparation only supports 1d.")
    parser.add_argument(
        "--sync-yfinance",
        action="store_true",
        help="Explicitly allow yfinance downloads before exporting. Never implied by default.",
    )
    parser.add_argument(
        "--build-provider",
        action="store_true",
        help="Also build the Qlib provider directory after export.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Skip network sync and Qlib imports.")
    parser.add_argument("--max-workers", type=int, default=4, help="Worker count for qlib dump_bin.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = prepare_real_daily_data(
        universe_path=args.universe,
        start_date=args.start_date,
        end_date=args.end_date,
        run_id=args.run_id or None,
        data_root=args.data_root,
        artifacts_root=args.artifacts_root,
        source=args.source or None,
        asset_class=args.asset_class,
        bar_size=args.bar_size,
        sync_yfinance=bool(args.sync_yfinance),
        build_provider=bool(args.build_provider),
        dry_run=bool(args.dry_run),
        max_workers=args.max_workers,
    )
    print(json.dumps(asdict(result), sort_keys=True))
    return 0 if result.status in {"completed", "dry_run"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
