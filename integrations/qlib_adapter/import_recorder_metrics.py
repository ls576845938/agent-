from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path

from .schemas import (
    RecorderMetricsImportResult,
    QlibAdapterError,
    build_run_paths,
    read_json,
    resolve_run_id,
    utc_now_iso,
    write_json,
)


def import_recorder_metrics(
    *,
    run_id: str,
    artifacts_root: str | Path = "artifacts/qlib_runs",
    recorder_metrics_path: str | Path | None = None,
) -> RecorderMetricsImportResult:
    created_at = utc_now_iso()
    resolved_run_id = resolve_run_id(run_id, artifacts_root)
    run_paths = build_run_paths(resolved_run_id, artifacts_root, create=False)
    source_path = Path(recorder_metrics_path) if recorder_metrics_path else run_paths.run_root / "recorder_metrics.json"
    backtest_summary_path = run_paths.run_root / "qlib_backtest_summary.json"
    output_path = run_paths.run_root / "imported_recorder_metrics.json"

    try:
        if not source_path.exists():
            raise QlibAdapterError(f"Recorder metrics file not found: {source_path}")
        metrics_payload = read_json(source_path)
        backtest_summary = read_json(backtest_summary_path) if backtest_summary_path.exists() else {}
        payload = {
            "run_id": resolved_run_id,
            "source": "qlib",
            "status": "completed",
            "imported_at": created_at,
            "recorder_metrics_path": str(source_path.resolve()),
            "metric_count": len(metrics_payload.get("metrics", {})),
            "normalized_metrics": _extract_normalized_metrics(metrics_payload, backtest_summary),
            "metrics_payload": metrics_payload,
            "backtest_summary_path": str(backtest_summary_path.resolve()),
            "backtest_summary": backtest_summary,
        }
        write_json(output_path, payload)
        return RecorderMetricsImportResult(
            run_id=resolved_run_id,
            status="completed",
            imported_metrics_path=str(output_path),
            created_at=created_at,
        )
    except Exception as exc:
        failure = RecorderMetricsImportResult(
            run_id=resolved_run_id,
            status="failed",
            imported_metrics_path=str(output_path),
            created_at=created_at,
            error=str(exc),
        )
        write_json(output_path, asdict(failure))
        return failure


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Import Qlib recorder metrics into a normalized adapter artifact.")
    parser.add_argument("--run-id", required=True, help="Run id to import.")
    parser.add_argument("--artifacts-root", default="artifacts/qlib_runs", help="Qlib artifacts root.")
    parser.add_argument("--recorder-metrics-path", default="", help="Optional override path to recorder_metrics.json.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = import_recorder_metrics(
        run_id=args.run_id,
        artifacts_root=args.artifacts_root,
        recorder_metrics_path=args.recorder_metrics_path or None,
    )
    print(json.dumps(asdict(result), sort_keys=True))
    return 0 if result.status == "completed" else 1


def _extract_normalized_metrics(metrics_payload: dict, backtest_summary: dict) -> dict:
    raw_metrics = metrics_payload.get("metrics", {})
    if not isinstance(raw_metrics, dict):
        raw_metrics = {}
    selected_metrics = backtest_summary.get("selected_metrics", {})
    if isinstance(selected_metrics, dict):
        raw_metrics = {**raw_metrics, **selected_metrics}

    aliases = {
        "IC": ("ic", "information_coefficient"),
        "Rank IC": ("rank_ic", "rank ic", "rankic"),
        "ICIR": ("icir", "ic_ir"),
        "annualized_return": ("annualized_return", "annual_return", "return annualized"),
        "max_drawdown": ("max_drawdown", "max drawdown", "mdd"),
        "information_ratio": ("information_ratio", "ir"),
        "turnover": ("turnover",),
        "cost_adjusted_return": ("cost_adjusted_return", "net_return", "return_with_cost"),
        "benchmark": ("benchmark",),
        "train_start": ("train_start",),
        "train_end": ("train_end",),
        "valid_start": ("valid_start",),
        "valid_end": ("valid_end",),
        "test_start": ("test_start",),
        "test_end": ("test_end",),
    }
    lowered = {str(key).lower(): value for key, value in raw_metrics.items()}
    normalized = {}
    for canonical, candidates in aliases.items():
        value = None
        for candidate in candidates:
            if candidate in lowered:
                value = lowered[candidate]
                break
        normalized[canonical] = value
    return normalized


if __name__ == "__main__":
    raise SystemExit(main())
