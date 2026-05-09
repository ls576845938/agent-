from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from backend.app.core.logging import configure_logger


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _env_csv(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    value = os.getenv(name)
    if value is None:
        return default
    return tuple(item.strip() for item in value.split(",") if item.strip())


@dataclass(frozen=True)
class Settings:
    repo_root: Path
    backend_root: Path
    frontend_root: Path
    logs_dir: Path
    reports_dir: Path
    default_data_source: str
    data_db_path: str
    binance_base_url: str
    binance_fallback_base_urls: tuple[str, ...]
    binance_request_sleep_seconds: float
    http_timeout_seconds: float
    data_update_interval_seconds: int
    data_default_backfill_days: int
    default_symbol: str
    default_interval: str
    timezone_name: str
    web_api_key: str
    api_host: str
    api_port: int
    default_commission_rate: float
    default_slippage: float
    default_leverage: float
    default_capital: float
    allow_fixture_fallback: bool

    @property
    def resolved_data_db_path(self) -> Path | None:
        if not self.data_db_path:
            return None
        return Path(self.data_db_path).expanduser().resolve()

    def periods_per_year(self, interval: str) -> float:
        lookup = {
            "1m": 365.0 * 24 * 60,
            "5m": 365.0 * 24 * 12,
            "15m": 365.0 * 24 * 4,
            "1h": 365.0 * 24,
            "4h": 365.0 * 6,
            "1d": 365.0,
        }
        return lookup.get(interval, lookup[self.default_interval])


def load_settings() -> Settings:
    repo_root = Path(__file__).resolve().parents[3]
    backend_root = repo_root / "backend"
    frontend_root = repo_root / "frontend"
    reports_dir = Path(os.getenv("QS_REPORT_DIR", repo_root / "reports"))
    logs_dir = repo_root / "logs"

    return Settings(
        repo_root=repo_root,
        backend_root=backend_root,
        frontend_root=frontend_root,
        logs_dir=logs_dir,
        reports_dir=reports_dir,
        default_data_source=os.getenv("QS_DEFAULT_DATA_SOURCE", "yfinance"),
        data_db_path=os.getenv("QS_DATA_DB_PATH", str(repo_root / "data" / "market_data.sqlite")),
        binance_base_url=os.getenv("QS_BINANCE_BASE_URL", "https://api.binance.com"),
        binance_fallback_base_urls=_env_csv(
            "QS_BINANCE_FALLBACK_BASE_URLS",
            ("https://api.binance.us",),
        ),
        binance_request_sleep_seconds=_env_float("QS_BINANCE_REQUEST_SLEEP_SECONDS", 0.15),
        http_timeout_seconds=_env_float("QS_HTTP_TIMEOUT_SECONDS", 20.0),
        data_update_interval_seconds=_env_int("QS_DATA_UPDATE_INTERVAL_SECONDS", 86400),
        data_default_backfill_days=_env_int("QS_DATA_DEFAULT_BACKFILL_DAYS", 30),
        default_symbol=os.getenv("QS_DEFAULT_SYMBOL", "SPY"),
        default_interval=os.getenv("QS_DEFAULT_INTERVAL", "1d"),
        timezone_name=os.getenv("QS_TIMEZONE", "UTC"),
        web_api_key=os.getenv("QS_WEB_API_KEY", ""),
        api_host=os.getenv("QS_API_HOST", "127.0.0.1"),
        api_port=_env_int("QS_API_PORT", 8000),
        default_commission_rate=_env_float("QS_DEFAULT_COMMISSION_RATE", 0.0001),
        default_slippage=_env_float("QS_DEFAULT_SLIPPAGE", 1.0),
        default_leverage=_env_float("QS_DEFAULT_LEVERAGE", 1.0),
        default_capital=_env_float("QS_DEFAULT_CAPITAL", 100000.0),
        allow_fixture_fallback=_env_bool("QS_ALLOW_FIXTURE_FALLBACK", False),
    )


settings = load_settings()
logger = configure_logger(log_dir=settings.logs_dir)
