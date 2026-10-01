#!/usr/bin/env python3
"""Build a research-only report for the imported US ETF macro rotation strategy."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from quant_us.research.us_etf_macro_momentum_rotation import (  # noqa: E402
    MACRO_COLUMNS,
    UsEtfMacroMomentumRotationConfig,
    build_price_matrix_from_bars,
    performance_summary,
    run_us_etf_macro_momentum_rotation,
)


DEFAULT_OUTPUT_ROOT = Path("artifacts/us_equity_etf_macro_rotation/latest")
DEFAULT_CLEANED_ROOT = Path("data/cleaned/vendor=yfinance/asset_class=equity/bar_size=1d")
DEFAULT_TIINGO_EOD_LAKE = Path("data/external/us_equity_eod/tiingo")
DEFAULT_TIINGO_IMPORT_REPORT = Path("artifacts/us_equity_data_status/latest/tiingo_eod_import_report.json")
DEFAULT_EXTERNAL_DATA_LAKE = Path("D:/Trading/PythonApplication1/data_cache_lake")
DEFAULT_DATA_STATUS_REPORT = Path("artifacts/us_equity_data_status/latest/data_status_report.json")
DEFAULT_EXTERNAL_QUALITY_REPORT = Path(
    "artifacts/us_equity_etf_macro_rotation/latest/external_etf_kline_quality_report.json"
)
DEFAULT_MACRO_PATHS = (
    Path("data/external/us_equity_macro/fred_macro.parquet"),
    Path("data/external/us_equity_macro/fred_macro.csv"),
)
SOURCE_PROJECT_FILES = (
    "配置参数.py",
    "策略逻辑.py",
    "量化引擎.py",
    "数据拼接.py",
    "数据抓取.py",
    "可视化分析.py",
    "主程序.py",
)


def build_us_etf_macro_rotation_research_report(
    *,
    repo_root: Path | None = None,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    generated_at: str | None = None,
    cleaned_root: Path = DEFAULT_CLEANED_ROOT,
    tiingo_data_lake: Path | None = DEFAULT_TIINGO_EOD_LAKE,
    external_data_lake: Path | None = DEFAULT_EXTERNAL_DATA_LAKE,
    macro_path: Path | None = None,
    config: UsEtfMacroMomentumRotationConfig | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    cfg = config or UsEtfMacroMomentumRotationConfig()
    generated = generated_at or datetime.now(timezone.utc).isoformat()
    report_output_root = root / output_root
    data_status_path = root / DEFAULT_DATA_STATUS_REPORT
    data_status = _read_json(data_status_path)
    external_quality_path = root / DEFAULT_EXTERNAL_QUALITY_REPORT
    external_quality = _read_json(external_quality_path)
    tiingo_import_path = root / DEFAULT_TIINGO_IMPORT_REPORT
    tiingo_import = _read_json(tiingo_import_path)
    source_project_path = Path(cfg.source_project_path)
    source_inventory = _source_inventory(source_project_path)
    canonical_bars, canonical_available_symbols, canonical_coverage = _load_cleaned_bars(
        root / cleaned_root, cfg.required_symbols()
    )
    tiingo_lake_root = tiingo_data_lake if tiingo_data_lake else None
    tiingo_bars, tiingo_available_symbols, tiingo_coverage = _load_eod_kline_lake_bars(
        _resolve(root, tiingo_lake_root) if tiingo_lake_root else None,
        cfg.required_symbols(),
    )
    external_lake_root = external_data_lake if external_data_lake else None
    external_bars, external_available_symbols, external_coverage = _load_external_data_lake_bars(
        external_lake_root, cfg.required_symbols()
    )
    bars, available_symbols, coverage, price_source, price_root, fallback_sources = _select_price_source(
        cfg.required_symbols(),
        candidates=[
            ("tiingo_eod", tiingo_bars, tiingo_available_symbols, tiingo_coverage, str(tiingo_lake_root) if tiingo_lake_root else None),
            ("external_data_lake", external_bars, external_available_symbols, external_coverage, str(external_lake_root) if external_lake_root else None),
            ("canonical_cleaned_bars", canonical_bars, canonical_available_symbols, canonical_coverage, str(cleaned_root)),
        ],
    )
    missing_symbols = sorted(set(cfg.required_symbols()) - set(available_symbols))
    blockers = _base_blockers(data_status)
    if missing_symbols:
        blockers.append("us_etf_macro_rotation_required_price_symbols_missing")
    price_rows_ok = False
    price_matrix = pd.DataFrame()
    if not missing_symbols:
        price_matrix = build_price_matrix_from_bars(bars, cfg.required_symbols())
        row_counts = price_matrix[list(cfg.required_symbols())].dropna(how="any").shape[0]
        price_rows_ok = row_counts >= cfg.min_rows
        if not price_rows_ok:
            blockers.append("us_etf_macro_rotation_insufficient_common_price_history")
    macro_df, macro_status, macro_used_path = _load_macro_data(
        root,
        macro_path,
        external_data_lake=external_lake_root,
    )
    if macro_status != "available":
        blockers.append("us_etf_macro_rotation_macro_data_missing_neutral_regime_used")
    freshness = _price_data_freshness(coverage, cfg.required_symbols(), generated)
    if freshness.get("staleness_days") is not None and int(freshness["staleness_days"]) > 30:
        blockers.append("us_etf_macro_rotation_price_data_stale")
    if price_source == "tiingo_eod" and tiingo_import.get("blockers"):
        blockers.append("us_etf_macro_rotation_tiingo_import_report_has_blockers")
        blockers.extend(str(item) for item in tiingo_import.get("blockers", []) if item)
    if not external_bars.empty and external_quality:
        if not bool(external_quality.get("promotion_clean", False)):
            blockers.append("us_etf_macro_rotation_external_kline_quality_not_promotion_clean")
        blockers.extend(str(item) for item in external_quality.get("blockers", []) if item)

    outputs: dict[str, str | None] = {
        "target_weights_csv": None,
        "daily_returns_csv": None,
    }
    backtest: dict[str, Any] = {}
    signal_integrity = {
        "t_plus_1_execution": False,
        "no_private_endpoint": True,
        "no_order_endpoint": True,
        "live_order_allowed": False,
        "paper_queue_status": "locked",
    }
    if not missing_symbols and price_rows_ok:
        result = run_us_etf_macro_momentum_rotation(price_matrix, macro_df, cfg)
        metrics = performance_summary(result.strategy_returns, price_matrix[cfg.benchmark])
        backtest = {
            "status": "complete",
            "metrics": metrics,
            "diagnostics": result.diagnostics,
            "latest_weights": _latest_weights(result.daily_weights),
        }
        signal_integrity["t_plus_1_execution"] = bool(result.diagnostics.get("t_plus_1_execution", False))
        if not signal_integrity["t_plus_1_execution"]:
            blockers.append("us_etf_macro_rotation_t_plus_1_check_failed")
        report_output_root.mkdir(parents=True, exist_ok=True)
        weights_path = report_output_root / "target_weights.csv"
        returns_path = report_output_root / "daily_returns.csv"
        result.daily_weights.to_csv(weights_path, encoding="utf-8")
        result.strategy_returns.rename("strategy_daily_return").to_csv(returns_path, encoding="utf-8")
        outputs = {
            "target_weights_csv": _relpath(weights_path, root),
            "daily_returns_csv": _relpath(returns_path, root),
        }
    else:
        backtest = {
            "status": "blocked",
            "reason": "missing_price_symbols" if missing_symbols else "insufficient_common_history",
            "metrics": {},
            "diagnostics": {},
            "latest_weights": {},
        }

    blockers = _dedupe(blockers)
    status = "blocked" if missing_symbols or not price_rows_ok else ("partial" if blockers else "complete")
    report = {
        "schema_version": "us_etf_macro_momentum_rotation_research_report_v1",
        "generated_at": generated,
        "commit": _git(["rev-parse", "--short", "HEAD"], cwd=root),
        "branch": _git(["branch", "--show-current"], cwd=root),
        "asset": "us_equity",
        "strategy_id": cfg.strategy_id,
        "status": status,
        "allowed_next_action": "research_only",
        "promotion_ready": False,
        "paper_ready": False,
        "live_ready": False,
        "source_project": {
            "path": cfg.source_project_path,
            "files": source_inventory,
            "integration_mode": "ported_math_only_no_network_or_scheduler",
        },
        "parameters": cfg.to_report_dict(),
        "data": {
            "price_source": price_source,
            "price_root": price_root,
            "price_source_precedence": ["tiingo_eod", "external_data_lake", "canonical_cleaned_bars"],
            "fallback_price_sources": fallback_sources,
            "cleaned_root": str(cleaned_root),
            "tiingo_eod_lake": str(tiingo_lake_root) if tiingo_lake_root else None,
            "external_data_lake": str(external_lake_root) if external_lake_root else None,
            "data_status_report": _relpath(data_status_path, root) if data_status_path.exists() else None,
            "data_lineage_grade": data_status.get("data_lineage_grade", {}),
            "promotion_clean": bool(data_status.get("promotion_clean", False)),
            "required_symbols": list(cfg.required_symbols()),
            "available_symbols": available_symbols,
            "missing_symbols": missing_symbols,
            "coverage": coverage,
            "tiingo_eod_coverage": tiingo_coverage,
            "canonical_cleaned_coverage": canonical_coverage,
            "external_data_lake_coverage": external_coverage,
            "tiingo_eod_import_report": _relpath(tiingo_import_path, root) if tiingo_import_path.exists() else None,
            "tiingo_eod_import": {
                "status": tiingo_import.get("status"),
                "provider": tiingo_import.get("provider"),
                "summary": tiingo_import.get("summary", {}),
                "blockers": tiingo_import.get("blockers", []),
                "guardrails": tiingo_import.get("guardrails", {}),
            }
            if tiingo_import
            else {},
            "external_kline_quality_report": _relpath(external_quality_path, root)
            if external_quality_path.exists()
            else None,
            "external_kline_quality": {
                "status": external_quality.get("status"),
                "promotion_clean": external_quality.get("promotion_clean"),
                "blockers": external_quality.get("blockers", []),
            }
            if external_quality
            else {},
            "freshness": freshness,
        },
        "macro_data": {
            "status": macro_status,
            "path": _relpath(macro_used_path, root) if macro_used_path else None,
            "required_columns": list(MACRO_COLUMNS),
            "neutral_regime_used": macro_status != "available",
        },
        "architecture": {
            "separation_status": "signals_portfolio_execution_decoupled",
            "alpha_signal_module": "quant_us.signals.us_etf_rotation_alpha",
            "portfolio_construction_module": "quant_us.portfolio.us_etf_rotation_portfolio",
            "execution_simulation_module": "quant_us.execution.us_etf_rotation_execution",
            "orchestrator": "scripts/build_us_etf_macro_rotation_research_report.py",
            "layer_contract": "data_loader_orchestrator -> alpha_signal -> portfolio_construction -> execution_simulation -> report_writer",
            "core_layers_forbidden_responsibilities": {
                "alpha_signal": [
                    "target_weight_decision",
                    "leverage_decision",
                    "simulated_fill_generation",
                    "live_readiness_decision"
                ],
                "portfolio_construction": [
                    "market_data_download",
                    "broker_or_order_endpoint",
                    "fill_generation",
                    "live_readiness_decision"
                ],
                "execution_simulation": [
                    "alpha_signal_generation",
                    "strategy_parameter_optimization",
                    "live_readiness_decision"
                ]
            },
        },
        "backtest": backtest,
        "signal_integrity": signal_integrity,
        "guardrails": {
            "research_only": True,
            "private_endpoint_used": False,
            "order_endpoint_used": False,
            "broker_endpoint_used": False,
            "live_order_allowed": False,
            "paper_or_live_unlock_allowed": False,
            "external_scheduler_imported": False,
            "network_fetcher_imported": False,
        },
        "outputs": outputs,
        "blockers": blockers,
    }
    return report


def write_report(report: dict[str, Any], output_root: Path) -> Path:
    output_root.mkdir(parents=True, exist_ok=True)
    path = output_root / "us_etf_macro_rotation_research_report.json"
    path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--cleaned-root", default=str(DEFAULT_CLEANED_ROOT))
    parser.add_argument("--tiingo-data-lake", default=str(DEFAULT_TIINGO_EOD_LAKE))
    parser.add_argument("--external-data-lake", default=str(DEFAULT_EXTERNAL_DATA_LAKE))
    parser.add_argument("--macro-path", default="")
    parser.add_argument("--generated-at", default="")
    args = parser.parse_args()
    root = Path(args.repo_root).resolve()
    output_root = Path(args.output_root)
    report = build_us_etf_macro_rotation_research_report(
        repo_root=root,
        output_root=output_root,
        generated_at=args.generated_at or None,
        cleaned_root=Path(args.cleaned_root),
        tiingo_data_lake=Path(args.tiingo_data_lake) if args.tiingo_data_lake else None,
        external_data_lake=Path(args.external_data_lake) if args.external_data_lake else None,
        macro_path=Path(args.macro_path) if args.macro_path else None,
    )
    path = write_report(report, root / output_root)
    print(json.dumps({"report": _relpath(path, root), "status": report["status"]}, indent=2, sort_keys=True))


def _load_cleaned_bars(cleaned_root: Path, symbols: tuple[str, ...]) -> tuple[pd.DataFrame, list[str], dict[str, Any]]:
    symbol_parts: dict[str, list[Path]] = {}
    frames: list[pd.DataFrame] = []
    available: list[str] = []
    coverage: dict[str, Any] = {}
    for symbol in symbols:
        symbol_dir = cleaned_root / f"symbol={symbol}"
        parts = sorted(symbol_dir.glob("date=*.parquet"))
        if not parts:
            coverage[symbol] = {"status": "missing", "rows": 0}
            continue
        symbol_parts[symbol] = parts
        available.append(symbol)
        coverage[symbol] = {
            "status": "available_unread",
            "rows": None,
            "partition_count": len(parts),
        }

    if len(available) < len(symbols):
        return pd.DataFrame(), available, coverage

    for symbol, parts in symbol_parts.items():
        frame = _read_symbol_parquet_parts(parts)
        if frame.empty:
            coverage[symbol] = {"status": "empty", "rows": 0}
            continue
        frame["timestamp_utc"] = pd.to_datetime(frame["timestamp_utc"], utc=True)
        frame["symbol"] = frame["symbol"].astype(str).str.upper()
        frame = frame.sort_values("timestamp_utc").drop_duplicates(["timestamp_utc", "symbol"], keep="last")
        frames.append(frame)
        coverage[symbol] = {
            "status": "available",
            "rows": int(len(frame)),
            "start": str(frame["timestamp_utc"].min().date()),
            "end": str(frame["timestamp_utc"].max().date()),
        }
    if not frames:
        return pd.DataFrame(), available, coverage
    return pd.concat(frames, ignore_index=True), available, coverage


def _load_external_data_lake_bars(
    data_lake_root: Path | None,
    symbols: tuple[str, ...],
) -> tuple[pd.DataFrame, list[str], dict[str, Any]]:
    return _load_eod_kline_lake_bars(data_lake_root, symbols)


def _load_eod_kline_lake_bars(
    data_lake_root: Path | None,
    symbols: tuple[str, ...],
) -> tuple[pd.DataFrame, list[str], dict[str, Any]]:
    if data_lake_root is None:
        return pd.DataFrame(), [], {}
    kline_root = data_lake_root / "kline"
    available: list[str] = []
    coverage: dict[str, Any] = {}
    symbol_paths: dict[str, Path] = {}
    for symbol in symbols:
        path = kline_root / f"{symbol}.parquet"
        if not path.exists():
            coverage[symbol] = {"status": "missing", "rows": 0}
            continue
        available.append(symbol)
        symbol_paths[symbol] = path
        coverage[symbol] = {"status": "available_unread", "rows": None, "path": str(path)}
    if len(available) < len(symbols):
        return pd.DataFrame(), available, coverage
    frames: list[pd.DataFrame] = []
    for symbol, path in symbol_paths.items():
        frame = pd.read_parquet(path)
        normalized = _normalize_external_kline_frame(frame, symbol)
        frames.append(normalized)
        coverage[symbol] = {
            "status": "available",
            "rows": int(len(normalized)),
            "start": str(normalized["timestamp_utc"].min().date()) if not normalized.empty else "",
            "end": str(normalized["timestamp_utc"].max().date()) if not normalized.empty else "",
            "path": str(path),
        }
    return pd.concat(frames, ignore_index=True), available, coverage


def _select_price_source(
    required_symbols: tuple[str, ...],
    *,
    candidates: list[tuple[str, pd.DataFrame, list[str], dict[str, Any], str | None]],
) -> tuple[pd.DataFrame, list[str], dict[str, Any], str, str | None, list[dict[str, Any]]]:
    required = set(required_symbols)
    fallback_sources: list[dict[str, Any]] = []
    first_non_empty: tuple[pd.DataFrame, list[str], dict[str, Any], str, str | None] | None = None
    for name, bars, available, coverage, root in candidates:
        missing = sorted(required - set(available))
        complete = not missing and not bars.empty
        fallback_sources.append(
            {
                "source": name,
                "root": root,
                "available_symbol_count": len(available),
                "missing_symbols": missing,
                "complete": complete,
            }
        )
        if not bars.empty and first_non_empty is None:
            first_non_empty = (bars, available, coverage, name, root)
        if complete:
            return bars, available, coverage, name, root, fallback_sources
    if first_non_empty is not None:
        bars, available, coverage, name, root = first_non_empty
        return bars, available, coverage, name, root, fallback_sources
    return pd.DataFrame(), [], {}, "missing", None, fallback_sources


def _normalize_external_kline_frame(frame: pd.DataFrame, symbol: str) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=["timestamp_utc", "symbol", "open", "high", "low", "close", "volume"])
    required = {
        "datetime": "timestamp_utc",
        "Open": "open",
        "High": "high",
        "Low": "low",
        "Close": "close",
        "Volume": "volume",
    }
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(f"external kline frame for {symbol} missing columns: {missing}")
    working = frame.rename(columns=required)[list(required.values())].copy()
    working["timestamp_utc"] = pd.to_datetime(working["timestamp_utc"], utc=True)
    working["symbol"] = symbol
    working = working[["timestamp_utc", "symbol", "open", "high", "low", "close", "volume"]]
    return working.sort_values("timestamp_utc").drop_duplicates(["timestamp_utc", "symbol"], keep="last")


def _read_symbol_parquet_parts(parts: list[Path]) -> pd.DataFrame:
    columns = ["timestamp_utc", "symbol", "open", "high", "low", "close", "volume"]
    try:
        import pyarrow.dataset as ds

        dataset = ds.dataset([str(path) for path in parts], format="parquet")
        return dataset.to_table(columns=columns).to_pandas()
    except Exception:
        return pd.concat((pd.read_parquet(path, columns=columns) for path in parts), ignore_index=True)


def _load_macro_data(
    root: Path,
    explicit_path: Path | None,
    *,
    external_data_lake: Path | None = None,
) -> tuple[pd.DataFrame, str, Path | None]:
    if explicit_path:
        candidates = [explicit_path]
    else:
        candidates = []
        if external_data_lake:
            candidates.append(external_data_lake / "macro/FRED_MACRO.parquet")
        candidates.extend(DEFAULT_MACRO_PATHS)
    for candidate in candidates:
        if candidate is None:
            continue
        path = candidate if candidate.is_absolute() else root / candidate
        if not path.exists():
            continue
        frame = pd.read_parquet(path) if path.suffix.lower() == ".parquet" else pd.read_csv(path)
        if frame.empty:
            return pd.DataFrame(), "empty", path
        time_col = "timestamp_utc" if "timestamp_utc" in frame.columns else ("datetime" if "datetime" in frame.columns else frame.columns[0])
        frame[time_col] = pd.to_datetime(frame[time_col], utc=True)
        frame = frame.set_index(time_col).sort_index()
        missing = [column for column in MACRO_COLUMNS if column not in frame.columns]
        if missing:
            return frame, "missing_columns", path
        return frame[list(MACRO_COLUMNS)], "available", path
    return pd.DataFrame(), "missing", None


def _source_inventory(path: Path) -> dict[str, Any]:
    files: dict[str, Any] = {}
    for filename in SOURCE_PROJECT_FILES:
        file_path = path / filename
        files[filename] = {
            "exists": file_path.exists(),
            "size": file_path.stat().st_size if file_path.exists() else 0,
        }
    return files


def _price_data_freshness(coverage: dict[str, Any], symbols: tuple[str, ...], generated_at: str) -> dict[str, Any]:
    end_dates: list[pd.Timestamp] = []
    for symbol in symbols:
        row = coverage.get(symbol, {})
        end_value = row.get("end") if isinstance(row, dict) else None
        if end_value:
            end_dates.append(pd.Timestamp(end_value).tz_localize(None))
    if not end_dates:
        return {
            "latest_common_price_date": None,
            "latest_any_price_date": None,
            "staleness_days": None,
        }
    latest_common = min(end_dates)
    latest_any = max(end_dates)
    generated_ts = pd.Timestamp(generated_at).tz_localize(None) if pd.Timestamp(generated_at).tzinfo else pd.Timestamp(generated_at)
    return {
        "latest_common_price_date": str(latest_common.date()),
        "latest_any_price_date": str(latest_any.date()),
        "staleness_days": int((generated_ts.normalize() - latest_common.normalize()).days),
    }


def _base_blockers(data_status: dict[str, Any]) -> list[str]:
    blockers: list[str] = ["us_etf_macro_rotation_research_only_import"]
    if not data_status:
        blockers.append("us_equity_data_status_report_missing")
        return blockers
    if not bool(data_status.get("promotion_clean", False)):
        blockers.append("us_equity_data_not_promotion_clean")
    blockers.extend(str(item) for item in data_status.get("blockers", []) if item)
    return blockers


def _latest_weights(weights: pd.DataFrame) -> dict[str, float]:
    if weights.empty:
        return {}
    latest = weights.iloc[-1]
    return {
        str(symbol): round(float(weight), 10)
        for symbol, weight in latest.items()
        if abs(float(weight)) > 1e-12
    }


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        value = str(item)
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _git(args: list[str], *, cwd: Path) -> str:
    try:
        completed = subprocess.run(["git", *args], cwd=cwd, check=False, capture_output=True, text=True)
    except OSError:
        return "unknown"
    if completed.returncode != 0:
        return "unknown"
    return completed.stdout.strip() or "unknown"


def _relpath(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
    except ValueError:
        return str(path)


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


if __name__ == "__main__":
    main()
