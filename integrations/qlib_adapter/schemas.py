from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import date, datetime
import importlib
import json
from pathlib import Path
import subprocess
from typing import Any

import yaml

from quant_us.core.clock import utc_now
from quant_us.core.types import new_id


class QlibAdapterError(RuntimeError):
    """Base exception for adapter failures."""


class MissingDependencyError(QlibAdapterError):
    """Raised when an optional dependency is required at runtime."""


@dataclass(frozen=True)
class UniverseConfig:
    universe_id: str
    description: str
    market: str
    asset_class: str
    bar_size: str
    timezone: str
    source: str
    research_only: bool
    allow_live: bool
    allow_minute_data: bool
    allow_implicit_downloads: bool
    strict_missing_symbols: bool
    strict_calendar_coverage: bool
    expected_symbol_count: int = 0
    survivorship_bias_risk: str = "clean"
    symbols: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RunPaths:
    run_id: str
    run_root: Path
    qlib_input_dir: Path
    qlib_input_csv_dir: Path
    qlib_provider_dir: Path


@dataclass(frozen=True)
class ExportResult:
    run_id: str
    status: str
    dataset_manifest_path: str
    daily_bars_path: str
    rows_exported: int
    symbols_requested: list[str]
    symbols_exported: list[str]
    created_at: str
    error: str | None = None


@dataclass(frozen=True)
class BuildQlibDatasetResult:
    run_id: str
    status: str
    dataset_manifest_path: str
    provider_manifest_path: str
    provider_dir: str
    created_at: str
    error: str | None = None


@dataclass(frozen=True)
class PrepareDailyDataResult:
    run_id: str
    status: str
    prepare_manifest_path: str
    dataset_manifest_path: str
    provider_manifest_path: str
    provider_dir: str
    created_at: str
    error: str | None = None


@dataclass(frozen=True)
class WorkflowRunResult:
    run_id: str
    status: str
    model_id: str
    pred_score_path: str
    recorder_metrics_path: str
    backtest_summary_path: str
    created_at: str
    error: str | None = None


@dataclass(frozen=True)
class PredScoreImportResult:
    run_id: str
    status: str
    research_model_scores_path: str
    rows_written: int
    created_at: str
    error: str | None = None


@dataclass(frozen=True)
class RecorderMetricsImportResult:
    run_id: str
    status: str
    imported_metrics_path: str
    created_at: str
    error: str | None = None


@dataclass(frozen=True)
class QlibStrategyManifest:
    manifest_id: str
    run_id: str
    source: str
    status: str
    promotion_status: str
    mode: str
    timeframe: str
    created_at: str
    universe_id: str
    symbols: list[str]
    strategy_version: str
    model_id: str
    feature_set: str
    label: str
    data_versions: list[str]
    dataset_manifest_path: str
    qlib_config_path: str
    pred_score_path: str
    research_model_scores_path: str
    recorder_metrics_path: str
    imported_recorder_metrics_path: str
    qlib_backtest_summary_path: str
    params: dict[str, Any] = field(default_factory=dict)
    cost_model: dict[str, Any] = field(default_factory=dict)
    slippage_model: dict[str, Any] = field(default_factory=dict)
    commit_hash: str = ""
    restrictions: list[str] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)


def load_yaml_file(path: str | Path) -> dict[str, Any]:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise QlibAdapterError(f"Expected mapping at config path: {path}")
    return payload


def write_json(path: str | Path, payload: Any) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(to_jsonable(payload), indent=2, sort_keys=True), encoding="utf-8")
    return target


def read_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def to_jsonable(payload: Any) -> Any:
    if is_dataclass(payload):
        return {key: to_jsonable(value) for key, value in asdict(payload).items()}
    if isinstance(payload, dict):
        return {str(key): to_jsonable(value) for key, value in payload.items()}
    if isinstance(payload, (list, tuple, set)):
        return [to_jsonable(value) for value in payload]
    if isinstance(payload, Path):
        return str(payload)
    if isinstance(payload, (datetime, date)):
        return payload.isoformat()
    item = getattr(payload, "item", None)
    if callable(item):
        try:
            return to_jsonable(item())
        except Exception:
            pass
    return payload


def normalize_symbol_list(values: list[str]) -> list[str]:
    unique: list[str] = []
    seen: set[str] = set()
    for value in values:
        symbol = str(value).strip().upper()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        unique.append(symbol)
    return unique


def load_universe_config(path: str | Path) -> UniverseConfig:
    payload = load_yaml_file(path)
    symbols = normalize_symbol_list(list(payload.get("symbols", [])))
    if not symbols:
        raise QlibAdapterError(f"Universe config has no symbols: {path}")
    config = UniverseConfig(
        universe_id=str(payload.get("universe_id", "")),
        description=str(payload.get("description", "")),
        market=str(payload.get("market", "us")),
        asset_class=str(payload.get("asset_class", "equity")),
        bar_size=str(payload.get("bar_size", "1d")).lower(),
        timezone=str(payload.get("timezone", "UTC")),
        source=str(payload.get("source", "yfinance")),
        research_only=bool(payload.get("research_only", True)),
        allow_live=bool(payload.get("allow_live", False)),
        allow_minute_data=bool(payload.get("allow_minute_data", False)),
        allow_implicit_downloads=bool(payload.get("allow_implicit_downloads", False)),
        strict_missing_symbols=bool(payload.get("strict_missing_symbols", True)),
        strict_calendar_coverage=bool(payload.get("strict_calendar_coverage", True)),
        expected_symbol_count=int(payload.get("expected_symbol_count", 0) or 0),
        survivorship_bias_risk=str(payload.get("survivorship_bias_risk", "clean")),
        symbols=symbols,
    )
    ensure_daily_only_bar_size(config.bar_size, context="universe config")
    if config.allow_minute_data:
        raise QlibAdapterError("Qlib adapter phase one is daily-only; universe config enables minute data.")
    if config.allow_live:
        raise QlibAdapterError("Qlib adapter is research-only; universe config must not allow live use.")
    if config.allow_implicit_downloads:
        raise QlibAdapterError("Qlib adapter forbids implicit downloads.")
    if config.expected_symbol_count and len(config.symbols) != config.expected_symbol_count:
        raise QlibAdapterError(
            f"Universe config expected {config.expected_symbol_count} symbols, found {len(config.symbols)}."
        )
    return config


def ensure_daily_only_bar_size(bar_size: str, *, context: str) -> None:
    if str(bar_size).lower() != "1d":
        raise QlibAdapterError(f"{context} must use daily bars only (received {bar_size!r}).")


def build_run_paths(run_id: str, artifacts_root: str | Path = "artifacts/qlib_runs", *, create: bool = False) -> RunPaths:
    run_root = Path(artifacts_root) / run_id
    paths = RunPaths(
        run_id=run_id,
        run_root=run_root,
        qlib_input_dir=run_root / "qlib_input",
        qlib_input_csv_dir=run_root / "qlib_input" / "csv",
        qlib_provider_dir=run_root / "qlib_provider",
    )
    if create:
        paths.qlib_input_csv_dir.mkdir(parents=True, exist_ok=True)
        paths.qlib_provider_dir.mkdir(parents=True, exist_ok=True)
    return paths


def make_run_id(prefix: str = "qlib") -> str:
    return new_id(prefix)


def parse_iso_date(value: str) -> date:
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise QlibAdapterError(f"Invalid ISO date: {value}") from exc


def resolve_latest_run_id(artifacts_root: str | Path = "artifacts/qlib_runs") -> str:
    root = Path(artifacts_root)
    candidates = [path for path in root.iterdir() if path.is_dir()] if root.exists() else []
    if not candidates:
        raise QlibAdapterError(f"No Qlib runs found under {root}")
    latest = max(candidates, key=lambda path: path.stat().st_mtime)
    return latest.name


def resolve_run_id(run_id: str | None, artifacts_root: str | Path = "artifacts/qlib_runs") -> str:
    if run_id and run_id != "latest":
        return run_id
    return resolve_latest_run_id(artifacts_root)


def render_templates(payload: Any, variables: dict[str, str]) -> Any:
    if isinstance(payload, str):
        return payload.format(**variables)
    if isinstance(payload, dict):
        return {str(key): render_templates(value, variables) for key, value in payload.items()}
    if isinstance(payload, list):
        return [render_templates(value, variables) for value in payload]
    return payload


def optional_import(module_name: str, *, required_by: str, install_hint: str):
    try:
        return importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        raise MissingDependencyError(
            f"{required_by} requires optional dependency '{module_name}'. {install_hint}"
        ) from exc


def optional_import_any(module_names: list[str], *, required_by: str, install_hint: str):
    errors: list[str] = []
    for name in module_names:
        try:
            return importlib.import_module(name)
        except ModuleNotFoundError as exc:
            errors.append(f"{name}: {exc}")
    joined = "; ".join(errors) or "module not found"
    raise MissingDependencyError(
        f"{required_by} requires one of {module_names}. {install_hint}. Import errors: {joined}"
    )


def resolve_git_commit(repo_root: str | Path = ".") -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(repo_root),
            check=True,
            capture_output=True,
            text=True,
        )
    except Exception:
        return ""
    return result.stdout.strip()


def utc_now_iso() -> str:
    return utc_now().isoformat()


def ensure_empty_or_missing(path: str | Path) -> None:
    target = Path(path)
    if target.exists() and any(target.iterdir()):
        raise QlibAdapterError(f"Run directory already exists and is not empty: {target}")
