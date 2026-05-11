from __future__ import annotations

import importlib
import importlib.util
import inspect
import io
import json
import runpy
import sys
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
import yaml

from quant_us.data.storage.data_manifest import DataManifest, DataManifestStore
from quant_us.data.storage.parquet_store import ParquetBarStore


UTC = timezone.utc


@dataclass(frozen=True)
class ModuleRunResult:
    exit_code: int
    stdout: str
    stderr: str
    return_value: Any = None


def adapter_module_or_xfail(module_name: str):
    try:
        spec = importlib.util.find_spec(module_name)
    except ModuleNotFoundError:
        spec = None
    if spec is None:
        pytest.xfail(f"pending adapter implementation: {module_name}")
    return importlib.import_module(module_name)


def invoke_adapter_callable(
    module_name: str,
    candidate_names: tuple[str, ...],
    **kwargs: Any,
) -> Any:
    module = adapter_module_or_xfail(module_name)
    for name in candidate_names:
        func = getattr(module, name, None)
        if not callable(func):
            continue
        signature = inspect.signature(func)
        accepted = {
            key: value
            for key, value in kwargs.items()
            if key in signature.parameters
        }
        return func(**accepted)
    pytest.fail(
        f"{module_name} is present, but none of {candidate_names!r} are callable"
    )


def run_module_main(
    module_name: str,
    argv: list[str],
) -> ModuleRunResult:
    try:
        spec = importlib.util.find_spec(module_name)
    except ModuleNotFoundError:
        spec = None
    if spec is None:
        pytest.xfail(f"pending adapter implementation: {module_name}")

    old_argv = sys.argv[:]
    stdout = io.StringIO()
    stderr = io.StringIO()
    exit_code = 0
    return_value: Any = None
    try:
        sys.argv = [module_name, *argv]
        with redirect_stdout(stdout), redirect_stderr(stderr):
            try:
                return_value = runpy.run_module(module_name, run_name="__main__")
            except SystemExit as exc:
                code = exc.code
                exit_code = code if isinstance(code, int) else 1
    finally:
        sys.argv = old_argv

    return ModuleRunResult(
        exit_code=exit_code,
        stdout=stdout.getvalue(),
        stderr=stderr.getvalue(),
        return_value=return_value,
    )


def locate_single_file(root: Path, filename: str) -> Path:
    matches = sorted(root.rglob(filename))
    assert matches, f"expected to find {filename} under {root}"
    assert len(matches) == 1, f"expected one {filename} under {root}, found {matches}"
    return matches[0]


def write_universe_yaml(path: Path, symbols: list[str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump({"symbols": symbols}), encoding="utf-8")
    return path


def write_portfolio_config(
    path: Path,
    *,
    optimizer: str = "max_sharpe",
    fallback_optimizer: str = "equal_weight_topk",
    cash_buffer: float = 0.05,
    max_weight: float = 0.60,
    max_turnover: float = 0.20,
    top_k: int = 2,
    lookback_days: int = 3,
    min_observations: int = 2,
    data_root: Path | None = None,
    score_runs_root: Path | None = None,
    portfolio_runs_root: Path | None = None,
    current_weights_path: Path | None = None,
    portfolio_run_id: str = "",
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            {
                "optimizer": optimizer,
                "fallback_optimizer": fallback_optimizer,
                "cash_buffer": cash_buffer,
                "max_weight": max_weight,
                "max_turnover": max_turnover,
                "top_k": top_k,
                "lookback_days": lookback_days,
                "min_observations": min_observations,
                "long_only": True,
                "data_root": str(data_root) if data_root is not None else "data",
                "score_runs_root": str(score_runs_root) if score_runs_root is not None else "artifacts/qlib_runs",
                "portfolio_runs_root": str(portfolio_runs_root) if portfolio_runs_root is not None else "artifacts/portfolio_runs",
                "current_weights_path": str(current_weights_path) if current_weights_path is not None else "",
                "portfolio_run_id": portfolio_run_id,
            }
        ),
        encoding="utf-8",
    )
    return path


def make_bar_frame(
    symbol: str,
    closes: list[float],
    *,
    start: str = "2026-01-05",
    volumes: list[float] | None = None,
) -> pd.DataFrame:
    dates = pd.bdate_range(start=start, periods=len(closes), tz="UTC")
    if volumes is None:
        volumes = [1_000_000.0 + 1_000.0 * idx for idx in range(len(closes))]
    rows: list[dict[str, Any]] = []
    for idx, (timestamp, close, volume) in enumerate(zip(dates, closes, volumes, strict=True)):
        open_ = close - 0.5
        rows.append(
            {
                "timestamp_utc": timestamp,
                "symbol": symbol,
                "open": open_,
                "high": close + 1.0,
                "low": open_ - 0.5,
                "close": close,
                "volume": volume,
                "source": "yfinance",
                "data_version": f"bars_{symbol.lower()}_{idx}",
            }
        )
    return pd.DataFrame(rows)


def write_cleaned_bars(
    data_root: Path,
    symbol: str,
    frame: pd.DataFrame,
    *,
    vendor: str = "yfinance",
    asset_class: str = "equity",
    bar_size: str = "1d",
    data_version: str | None = None,
) -> str:
    store = ParquetBarStore(data_root / "cleaned")
    store.write_bars(
        frame=frame,
        vendor=vendor,
        asset_class=asset_class,
        bar_size=bar_size,
        symbol=symbol,
    )
    resolved_version = data_version or f"qs-{vendor}-{symbol}-1d-test"
    manifest = DataManifest(
        data_version=resolved_version,
        source=vendor,
        symbol=symbol,
        interval=bar_size,
        asset_class=asset_class,
        timezone="UTC",
        adjustment="raw",
        adjustment_policy="raw",
        corporate_action_adjustment="raw",
        start=str(pd.to_datetime(frame["timestamp_utc"], utc=True).min().date()),
        end=str(pd.to_datetime(frame["timestamp_utc"], utc=True).max().date()),
        row_count=len(frame),
        expected_rows=len(frame),
        coverage_pct=100.0,
        fingerprint=f"fingerprint-{symbol.lower()}",
        checksum=f"checksum-{symbol.lower()}",
        quality_score=100.0,
        fields=["timestamp_utc", "symbol", "open", "high", "low", "close", "volume"],
        cleaned_path=str(
            data_root
            / "cleaned"
            / f"vendor={vendor}"
            / f"asset_class={asset_class}"
            / f"bar_size={bar_size}"
            / f"symbol={symbol}"
        ),
        raw_path="",
        universe_id="us-core-liquid-test",
        universe_source="tests",
        survivorship_bias_risk="unknown",
    )
    DataManifestStore(data_root / "manifests").write(manifest)
    return resolved_version


def write_qlib_run_inputs(
    artifacts_root: Path,
    run_id: str,
    scores: pd.DataFrame,
    *,
    recorder_metrics: dict[str, Any] | None = None,
    backtest_summary: dict[str, Any] | None = None,
) -> Path:
    run_root = artifacts_root / "qlib_runs" / run_id
    qlib_input_dir = run_root / "qlib_input"
    run_root.mkdir(parents=True, exist_ok=True)
    qlib_input_dir.mkdir(parents=True, exist_ok=True)
    scores_to_write = scores.copy()
    if "instrument" in scores_to_write.columns and "symbol" in scores_to_write.columns:
        scores_to_write = scores_to_write.drop(columns=["symbol"])
    scores_to_write.to_parquet(run_root / "pred_score.parquet", index=False)
    symbol_series = (
        scores.get("symbol")
        if "symbol" in scores.columns
        else scores.get("instrument", pd.Series(dtype=str))
    )
    symbols = sorted({str(symbol).upper() for symbol in symbol_series.tolist()})
    source_manifests = [
        {
            "symbol": symbol,
            "data_version": f"qs-yfinance-{symbol}-1d-test",
            "checksum": f"checksum-{symbol.lower()}",
        }
        for symbol in symbols
    ]
    (qlib_input_dir / "dataset_manifest.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "status": "completed",
                "universe": {"universe_id": "us-core-liquid-test"},
                "symbols_exported": symbols,
                "source_manifests": source_manifests,
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    (run_root / "recorder_metrics.json").write_text(
        json.dumps(recorder_metrics or {"ic": 0.12, "rank_ic": 0.10}, indent=2),
        encoding="utf-8",
    )
    (run_root / "qlib_backtest_summary.json").write_text(
        json.dumps(backtest_summary or {"sharpe": 0.8, "max_drawdown": 0.12}, indent=2),
        encoding="utf-8",
    )
    return run_root


def write_imported_scores(
    artifacts_root: Path,
    run_id: str,
    scores: pd.DataFrame,
    *,
    data_version: str = "qs-yfinance-universe-1d-test",
) -> Path:
    run_root = artifacts_root / "qlib_runs" / run_id
    run_root.mkdir(parents=True, exist_ok=True)
    imported = scores.copy()
    imported["run_id"] = run_id
    imported["model_id"] = "model_test"
    imported["source"] = "qlib"
    imported["data_version"] = data_version
    imported["universe"] = "us-core-liquid-test"
    imported["feature_set"] = "alpha158"
    imported["label"] = "fwd_1d"
    imported["created_at"] = datetime(2026, 5, 11, tzinfo=UTC)
    imported["rank"] = imported.groupby("datetime")["score"].rank(
        method="dense",
        ascending=False,
    )
    columns = [
        "run_id",
        "model_id",
        "source",
        "data_version",
        "datetime",
        "symbol",
        "score",
        "rank",
        "universe",
        "feature_set",
        "label",
        "created_at",
    ]
    imported[columns].to_parquet(run_root / "research_model_scores.parquet", index=False)
    return run_root
