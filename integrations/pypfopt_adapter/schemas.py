from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from quant_us.core.clock import utc_now
from quant_us.core.types import new_id

QLIB_RUNS_ROOT = Path("artifacts/qlib_runs")
PORTFOLIO_RUNS_ROOT = Path("artifacts/portfolio_runs")
DEFAULT_DATA_ROOT = Path("data")

SCORE_REQUIRED_COLUMNS = frozenset({"datetime", "symbol", "score"})
EXPECTED_RETURNS_REQUIRED_COLUMNS = frozenset(
    {
        "portfolio_run_id",
        "source_score_run_id",
        "datetime",
        "symbol",
        "score",
        "rank",
        "expected_return",
        "created_at",
    }
)
COVARIANCE_REQUIRED_COLUMNS = frozenset(
    {
        "portfolio_run_id",
        "source_score_run_id",
        "datetime",
        "symbol",
        "peer_symbol",
        "covariance",
        "lookback_days",
        "observation_count",
        "returns_start",
        "returns_end",
        "created_at",
    }
)
TARGET_WEIGHTS_REQUIRED_COLUMNS = frozenset(
    {
        "portfolio_run_id",
        "source_score_run_id",
        "datetime",
        "symbol",
        "target_weight",
        "raw_weight",
        "clipped_weight",
        "optimizer",
        "constraints_hash",
        "fallback",
        "created_at",
    }
)


class AdapterError(RuntimeError):
    """Base adapter error."""


class ConfigError(AdapterError):
    """Raised when adapter config is invalid."""


class ArtifactError(AdapterError):
    """Raised when an adapter artifact is missing or malformed."""


class MissingDependencyError(AdapterError):
    """Raised when an optional dependency is unavailable."""


@dataclass(frozen=True)
class PortfolioAdapterConfig:
    optimizer: str = "max_sharpe"
    fallback_optimizer: str = "equal_weight_topk"
    expected_return_method: str = "rank_zscore"
    covariance_method: str = "sample"
    top_k: int = 10
    lookback_days: int = 252
    min_observations: int = 60
    annualization: int = 252
    rebalance_freq: str = "daily"
    long_only: bool = True
    max_weight: float = 0.15
    cash_buffer: float = 0.02
    max_turnover: float = 0.30
    risk_free_rate: float = 0.0
    min_expected_return: float = 0.02
    max_expected_return: float = 0.20
    strategy_id: str = "pypfopt_daily_only"
    vendor: str = "yfinance"
    asset_class: str = "equity"
    bar_size: str = "1d"
    data_root: Path = field(default_factory=lambda: DEFAULT_DATA_ROOT)
    score_runs_root: Path = field(default_factory=lambda: QLIB_RUNS_ROOT)
    portfolio_runs_root: Path = field(default_factory=lambda: PORTFOLIO_RUNS_ROOT)
    current_weights_path: str = ""
    portfolio_run_id: str = ""

    def __post_init__(self) -> None:
        optimizer = str(self.optimizer).strip().lower()
        fallback = str(self.fallback_optimizer).strip().lower()
        expected_return_method = str(self.expected_return_method).strip().lower()
        covariance_method = str(self.covariance_method).strip().lower()
        rebalance_freq = str(self.rebalance_freq).strip().lower()
        object.__setattr__(self, "optimizer", optimizer)
        object.__setattr__(self, "fallback_optimizer", fallback)
        object.__setattr__(self, "expected_return_method", expected_return_method)
        object.__setattr__(self, "covariance_method", covariance_method)
        object.__setattr__(self, "rebalance_freq", rebalance_freq)
        object.__setattr__(self, "strategy_id", str(self.strategy_id).strip() or "pypfopt_daily_only")
        object.__setattr__(self, "vendor", str(self.vendor).strip().lower() or "yfinance")
        object.__setattr__(self, "asset_class", str(self.asset_class).strip().lower() or "equity")
        object.__setattr__(self, "bar_size", str(self.bar_size).strip().lower() or "1d")
        object.__setattr__(self, "data_root", Path(self.data_root))
        object.__setattr__(self, "score_runs_root", Path(self.score_runs_root))
        object.__setattr__(self, "portfolio_runs_root", Path(self.portfolio_runs_root))
        object.__setattr__(self, "portfolio_run_id", str(self.portfolio_run_id).strip())
        self.validate()

    def validate(self) -> None:
        supported_optimizers = {"max_sharpe", "min_volatility", "hrp", "equal_weight_topk"}
        if self.optimizer not in supported_optimizers:
            raise ConfigError(f"Unsupported optimizer: {self.optimizer}")
        if self.fallback_optimizer and self.fallback_optimizer not in {"equal_weight_topk"}:
            raise ConfigError(f"Unsupported fallback optimizer: {self.fallback_optimizer}")
        supported_expected_return_methods = {"rank_zscore", "score_zscore", "forward_return_fit"}
        if self.expected_return_method not in supported_expected_return_methods:
            raise ConfigError(f"Unsupported expected_return_method: {self.expected_return_method}")
        supported_covariance_methods = {"sample", "shrinkage", "exponential"}
        if self.covariance_method not in supported_covariance_methods:
            raise ConfigError(f"Unsupported covariance_method: {self.covariance_method}")
        if self.rebalance_freq not in {"daily", "weekly"}:
            raise ConfigError("rebalance_freq must be daily or weekly.")
        if self.bar_size != "1d":
            raise ConfigError("PyPortfolioOpt adapter is daily-only and requires bar_size=1d.")
        if self.asset_class != "equity":
            raise ConfigError("PyPortfolioOpt adapter currently supports asset_class=equity only.")
        if not self.long_only:
            raise ConfigError("PyPortfolioOpt adapter currently supports long_only=True only.")
        if self.top_k <= 0:
            raise ConfigError("top_k must be positive.")
        if self.lookback_days <= 1:
            raise ConfigError("lookback_days must be greater than 1.")
        if self.min_observations <= 1:
            raise ConfigError("min_observations must be greater than 1.")
        if self.min_observations > self.lookback_days:
            raise ConfigError("min_observations cannot exceed lookback_days.")
        if self.annualization <= 0:
            raise ConfigError("annualization must be positive.")
        if not 0.0 <= self.cash_buffer < 1.0:
            raise ConfigError("cash_buffer must be in [0, 1).")
        if self.max_weight <= 0.0:
            raise ConfigError("max_weight must be positive.")
        if self.max_turnover < 0.0:
            raise ConfigError("max_turnover must be non-negative.")
        if self.max_expected_return < self.min_expected_return:
            raise ConfigError("max_expected_return must be >= min_expected_return.")
        if self.gross_cap <= 0.0:
            raise ConfigError("cash_buffer leaves no investable capital.")

    @property
    def gross_cap(self) -> float:
        return max(0.0, 1.0 - self.cash_buffer)

    def with_overrides(
        self,
        *,
        optimizer: str | None = None,
        fallback_optimizer: str | None = None,
        portfolio_run_id: str | None = None,
    ) -> "PortfolioAdapterConfig":
        payload = asdict(self)
        if optimizer is not None:
            payload["optimizer"] = optimizer
        if fallback_optimizer is not None:
            payload["fallback_optimizer"] = fallback_optimizer
        if portfolio_run_id is not None:
            payload["portfolio_run_id"] = portfolio_run_id
        return PortfolioAdapterConfig(**payload)


def load_portfolio_config(path: str | Path | None) -> PortfolioAdapterConfig:
    if path is None:
        return PortfolioAdapterConfig()

    config_path = Path(path)
    if not config_path.exists():
        raise ConfigError(f"Portfolio config not found: {config_path}")

    payload = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ConfigError(f"Portfolio config must be a mapping: {config_path}")

    supported_keys = {
        "optimizer",
        "fallback_optimizer",
        "expected_return_method",
        "covariance_method",
        "top_k",
        "lookback_days",
        "min_observations",
        "annualization",
        "rebalance_freq",
        "long_only",
        "max_weight",
        "cash_buffer",
        "max_turnover",
        "risk_free_rate",
        "min_expected_return",
        "max_expected_return",
        "strategy_id",
        "vendor",
        "asset_class",
        "bar_size",
        "data_root",
        "score_runs_root",
        "portfolio_runs_root",
        "current_weights_path",
        "portfolio_run_id",
    }
    unknown_keys = sorted(set(payload) - supported_keys)
    if unknown_keys:
        raise ConfigError(f"Unknown config keys in {config_path}: {', '.join(unknown_keys)}")

    return PortfolioAdapterConfig(**payload)


def resolve_portfolio_run_id(config: PortfolioAdapterConfig, portfolio_run_id: str | None = None) -> str:
    candidate = str(portfolio_run_id or config.portfolio_run_id).strip()
    return candidate or new_id("pfrun")


def portfolio_run_dir(config: PortfolioAdapterConfig, portfolio_run_id: str) -> Path:
    path = config.portfolio_runs_root / portfolio_run_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def qlib_score_path(config: PortfolioAdapterConfig, score_run_id: str) -> Path:
    return config.score_runs_root / score_run_id / "research_model_scores.parquet"


def target_weights_path(config: PortfolioAdapterConfig, portfolio_run_id: str) -> Path:
    return portfolio_run_dir(config, portfolio_run_id) / "target_weights.parquet"


def expected_returns_path(config: PortfolioAdapterConfig, portfolio_run_id: str) -> Path:
    return portfolio_run_dir(config, portfolio_run_id) / "expected_returns.parquet"


def covariance_path(config: PortfolioAdapterConfig, portfolio_run_id: str) -> Path:
    return portfolio_run_dir(config, portfolio_run_id) / "covariance.parquet"


def run_manifest_path(config: PortfolioAdapterConfig, portfolio_run_id: str) -> Path:
    return portfolio_run_dir(config, portfolio_run_id) / "run_manifest.json"


def target_positions_parquet_path(config: PortfolioAdapterConfig, portfolio_run_id: str) -> Path:
    return portfolio_run_dir(config, portfolio_run_id) / "target_positions.parquet"


def target_positions_json_path(config: PortfolioAdapterConfig, portfolio_run_id: str) -> Path:
    return portfolio_run_dir(config, portfolio_run_id) / "target_positions.json"


def read_score_frame(config: PortfolioAdapterConfig, score_run_id: str) -> pd.DataFrame:
    path = qlib_score_path(config, score_run_id)
    if not path.exists():
        raise ArtifactError(
            f"Qlib score artifact not found: {path}. Expected artifacts/qlib_runs/<run_id>/research_model_scores.parquet."
        )
    frame = pd.read_parquet(path)
    ensure_columns(frame, SCORE_REQUIRED_COLUMNS, f"score artifact {path}")
    working = frame.copy()
    working["datetime"] = pd.to_datetime(working["datetime"], utc=True)
    working["symbol"] = working["symbol"].astype(str).str.upper()
    working["score"] = pd.to_numeric(working["score"], errors="raise")
    duplicates = working.duplicated(subset=["datetime", "symbol"])
    if duplicates.any():
        dupes = working.loc[duplicates, ["datetime", "symbol"]].head(5).to_dict(orient="records")
        raise ArtifactError(f"score artifact has duplicate datetime+symbol rows: {dupes}")
    return working.sort_values(["datetime", "symbol"]).reset_index(drop=True)


def read_expected_returns_frame(config: PortfolioAdapterConfig, portfolio_run_id: str) -> pd.DataFrame:
    path = expected_returns_path(config, portfolio_run_id)
    if not path.exists():
        raise ArtifactError(f"expected return artifact not found: {path}")
    frame = pd.read_parquet(path)
    ensure_columns(frame, EXPECTED_RETURNS_REQUIRED_COLUMNS, f"expected returns artifact {path}")
    working = frame.copy()
    working["datetime"] = pd.to_datetime(working["datetime"], utc=True)
    working["symbol"] = working["symbol"].astype(str).str.upper()
    working["expected_return"] = pd.to_numeric(working["expected_return"], errors="raise")
    return working.sort_values(["datetime", "symbol"]).reset_index(drop=True)


def read_covariance_frame(config: PortfolioAdapterConfig, portfolio_run_id: str) -> pd.DataFrame:
    path = covariance_path(config, portfolio_run_id)
    if not path.exists():
        raise ArtifactError(f"covariance artifact not found: {path}")
    frame = pd.read_parquet(path)
    ensure_columns(frame, COVARIANCE_REQUIRED_COLUMNS, f"covariance artifact {path}")
    working = frame.copy()
    working["datetime"] = pd.to_datetime(working["datetime"], utc=True)
    working["symbol"] = working["symbol"].astype(str).str.upper()
    working["peer_symbol"] = working["peer_symbol"].astype(str).str.upper()
    working["covariance"] = pd.to_numeric(working["covariance"], errors="raise")
    return working.sort_values(["datetime", "symbol", "peer_symbol"]).reset_index(drop=True)


def read_target_weights_frame(config: PortfolioAdapterConfig, portfolio_run_id: str) -> pd.DataFrame:
    path = target_weights_path(config, portfolio_run_id)
    if not path.exists():
        raise ArtifactError(f"target weights artifact not found: {path}")
    frame = pd.read_parquet(path)
    ensure_columns(frame, TARGET_WEIGHTS_REQUIRED_COLUMNS, f"target weights artifact {path}")
    working = frame.copy()
    working["datetime"] = pd.to_datetime(working["datetime"], utc=True)
    working["symbol"] = working["symbol"].astype(str).str.upper()
    working["target_weight"] = pd.to_numeric(working["target_weight"], errors="raise")
    return working.sort_values(["datetime", "symbol"]).reset_index(drop=True)


def ensure_columns(frame: pd.DataFrame, required: set[str] | frozenset[str], label: str) -> None:
    missing = sorted(set(required) - set(frame.columns))
    if missing:
        raise ArtifactError(f"{label} is missing required columns: {', '.join(missing)}")


def write_frame(frame: pd.DataFrame, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path, index=False)
    return path


def write_json(path: Path, payload: dict[str, Any] | list[dict[str, Any]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=False), encoding="utf-8")
    return path


def constraints_hash(config: PortfolioAdapterConfig) -> str:
    payload = {
        "optimizer": config.optimizer,
        "expected_return_method": config.expected_return_method,
        "covariance_method": config.covariance_method,
        "top_k": config.top_k,
        "lookback_days": config.lookback_days,
        "min_observations": config.min_observations,
        "annualization": config.annualization,
        "rebalance_freq": config.rebalance_freq,
        "long_only": config.long_only,
        "max_weight": config.max_weight,
        "cash_buffer": config.cash_buffer,
        "max_turnover": config.max_turnover,
        "risk_free_rate": config.risk_free_rate,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


def load_current_weights(path: str) -> dict[str, float]:
    cleaned_path = str(path).strip()
    if not cleaned_path:
        return {}

    source = Path(cleaned_path)
    if not source.exists():
        raise ArtifactError(f"current weights file not found: {source}")

    if source.suffix.lower() == ".parquet":
        frame = pd.read_parquet(source)
        return _weights_from_frame(frame, source)
    if source.suffix.lower() == ".csv":
        frame = pd.read_csv(source)
        return _weights_from_frame(frame, source)
    if source.suffix.lower() == ".json":
        payload = json.loads(source.read_text(encoding="utf-8"))
        if isinstance(payload, dict) and "weights" in payload and isinstance(payload["weights"], dict):
            return {str(symbol).upper(): float(weight) for symbol, weight in payload["weights"].items()}
        if isinstance(payload, dict):
            return {str(symbol).upper(): float(weight) for symbol, weight in payload.items()}
        if isinstance(payload, list):
            return _weights_from_frame(pd.DataFrame(payload), source)
    raise ArtifactError(f"Unsupported current weights file format: {source}")


def normalize_current_weights(weights: dict[str, float], config: PortfolioAdapterConfig) -> dict[str, float]:
    cleaned = {symbol.upper(): max(0.0, float(weight)) for symbol, weight in weights.items() if abs(float(weight)) > 1e-12}
    clipped = {symbol: min(weight, config.max_weight) for symbol, weight in cleaned.items()}
    total = sum(clipped.values())
    if total <= config.gross_cap + 1e-12:
        return {symbol: weight for symbol, weight in clipped.items() if weight > 1e-12}
    return project_long_only_weights(clipped, gross_cap=config.gross_cap, max_weight=config.max_weight)


def project_long_only_weights(weights: dict[str, float], *, gross_cap: float, max_weight: float) -> dict[str, float]:
    if gross_cap <= 0.0 or max_weight <= 0.0:
        return {}

    current = {symbol.upper(): max(0.0, float(weight)) for symbol, weight in weights.items() if float(weight) > 0.0}
    if not current:
        return {}

    total = sum(current.values())
    if total <= 0.0:
        return {}

    remaining = {symbol: value / total * gross_cap for symbol, value in current.items()}
    result: dict[str, float] = {}
    available_cap = gross_cap

    while remaining and available_cap > 1e-12:
        remaining_total = sum(remaining.values())
        if remaining_total <= 0.0:
            break
        scaled = {symbol: value / remaining_total * available_cap for symbol, value in remaining.items()}
        newly_capped = {symbol: value for symbol, value in scaled.items() if value > max_weight + 1e-12}
        if not newly_capped:
            for symbol, value in scaled.items():
                result[symbol] = value
            available_cap = 0.0
            break
        for symbol in newly_capped:
            result[symbol] = max_weight
        available_cap = max(0.0, gross_cap - sum(result.values()))
        remaining = {symbol: remaining[symbol] for symbol in remaining if symbol not in newly_capped}

    return {symbol: weight for symbol, weight in result.items() if weight > 1e-12}


def scale_weights_for_turnover(
    current_weights: dict[str, float],
    target_weights: dict[str, float],
    max_turnover: float,
) -> tuple[dict[str, float], float, float]:
    symbols = set(current_weights) | set(target_weights)
    turnover = sum(abs(target_weights.get(symbol, 0.0) - current_weights.get(symbol, 0.0)) for symbol in symbols)
    if turnover <= max_turnover or turnover <= 0.0:
        return dict(target_weights), 1.0, turnover

    scale = max_turnover / turnover
    scaled = {
        symbol: current_weights.get(symbol, 0.0)
        + (target_weights.get(symbol, 0.0) - current_weights.get(symbol, 0.0)) * scale
        for symbol in symbols
    }
    realized_turnover = sum(abs(scaled.get(symbol, 0.0) - current_weights.get(symbol, 0.0)) for symbol in symbols)
    return {symbol: weight for symbol, weight in scaled.items() if weight > 1e-12}, scale, realized_turnover


def missing_pypfopt_error() -> MissingDependencyError:
    return MissingDependencyError(
        "PyPortfolioOpt is not installed. Install it before using optimizer modes "
        "`max_sharpe`, `min_volatility`, or `hrp`, or pass `--fallback-optimizer equal_weight_topk`."
    )


def build_run_manifest(
    *,
    portfolio_run_id: str,
    score_run_id: str,
    config: PortfolioAdapterConfig,
    output_files: dict[str, str],
    dependency_available: bool,
    fallback_used: bool,
    generated_at: str | None = None,
) -> dict[str, Any]:
    return {
        "portfolio_run_id": portfolio_run_id,
        "source_score_run_id": score_run_id,
        "status": "completed",
        "research_only": True,
        "daily_only": True,
        "live_enabled": False,
        "order_generation": "disabled",
        "generated_at": generated_at or utc_now().isoformat(),
        "dependency_available": dependency_available,
        "fallback_used": fallback_used,
        "config": {
            "optimizer": config.optimizer,
            "fallback_optimizer": config.fallback_optimizer,
            "expected_return_method": config.expected_return_method,
            "covariance_method": config.covariance_method,
            "top_k": config.top_k,
            "lookback_days": config.lookback_days,
            "min_observations": config.min_observations,
            "annualization": config.annualization,
            "rebalance_freq": config.rebalance_freq,
            "long_only": config.long_only,
            "max_weight": config.max_weight,
            "cash_buffer": config.cash_buffer,
            "max_turnover": config.max_turnover,
            "risk_free_rate": config.risk_free_rate,
            "min_expected_return": config.min_expected_return,
            "max_expected_return": config.max_expected_return,
            "strategy_id": config.strategy_id,
            "vendor": config.vendor,
            "asset_class": config.asset_class,
            "bar_size": config.bar_size,
            "current_weights_path": config.current_weights_path,
            "constraints_hash": constraints_hash(config),
        },
        "output_files": output_files,
    }


def now_iso() -> str:
    return utc_now().isoformat()


def read_run_manifest(config: PortfolioAdapterConfig, portfolio_run_id: str) -> dict[str, Any]:
    path = run_manifest_path(config, portfolio_run_id)
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ArtifactError(f"run manifest is malformed: {path}")
    return payload


def _weights_from_frame(frame: pd.DataFrame, source: Path) -> dict[str, float]:
    if "symbol" not in frame.columns:
        raise ArtifactError(f"current weights file {source} must include a symbol column.")
    for weight_column in ("weight", "current_weight", "target_weight", "raw_weight", "clipped_weight"):
        if weight_column in frame.columns:
            working = frame[["symbol", weight_column]].copy()
            working["symbol"] = working["symbol"].astype(str).str.upper()
            working[weight_column] = pd.to_numeric(working[weight_column], errors="raise")
            return {
                row["symbol"]: float(row[weight_column])
                for row in working.to_dict(orient="records")
                if abs(float(row[weight_column])) > 1e-12
            }
    raise ArtifactError(
        f"current weights file {source} must include one of: weight, current_weight, target_weight, raw_weight, clipped_weight."
    )
