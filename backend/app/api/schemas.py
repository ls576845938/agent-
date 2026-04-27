from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field, field_validator


class StrategyInfo(BaseModel):
    id: str
    display_name: str
    description: str
    category: str
    default_weight: float
    default_params: dict[str, float] = Field(default_factory=dict)


class StrategyWeight(BaseModel):
    strategy_id: str
    weight: float = Field(ge=0.0, le=1.0)


class BaseBacktestRequest(BaseModel):
    source: str = "fixture"
    symbol: str = "BTCUSDT"
    interval: str = "1h"
    start: datetime
    end: datetime
    capital: float = Field(default=100000.0, gt=0)
    commission_rate: float = Field(default=0.0004, ge=0.0, le=0.05)
    slippage: float = Field(default=4.0, ge=0.0)
    leverage: float = Field(default=1.0, gt=0.0, le=5.0)
    position_basis: str = Field(default="equity")
    data_db_path: str = ""

    @field_validator("source")
    @classmethod
    def validate_source(cls, value: str) -> str:
        allowed = {"fixture", "sqlite", "auto"}
        if value not in allowed:
            raise ValueError(f"source must be one of {sorted(allowed)}")
        return value

    @field_validator("interval")
    @classmethod
    def validate_interval(cls, value: str) -> str:
        allowed = {"1m", "5m", "15m", "1h", "4h", "1d"}
        if value not in allowed:
            raise ValueError(f"interval must be one of {sorted(allowed)}")
        return value

    @field_validator("position_basis")
    @classmethod
    def validate_position_basis(cls, value: str) -> str:
        allowed = {"equity", "capital"}
        if value not in allowed:
            raise ValueError(f"position_basis must be one of {sorted(allowed)}")
        return value

    @field_validator("end")
    @classmethod
    def validate_dates(cls, value: datetime, info: Any) -> datetime:
        start = info.data.get("start")
        if start is not None and value <= start:
            raise ValueError("end must be later than start")
        return value


class SingleBacktestRequest(BaseBacktestRequest):
    strategy_id: str
    strategy_params: dict[str, float] = Field(default_factory=dict)


class PortfolioBacktestRequest(BaseBacktestRequest):
    weights: list[StrategyWeight] = Field(default_factory=list)


class BacktestSummary(BaseModel):
    total_return_pct: float
    annual_return_pct: float
    annual_volatility_pct: float
    sharpe_ratio: float
    sortino_ratio: float
    max_drawdown_pct: float
    calmar_ratio: float
    win_rate_pct: float
    profit_factor: float
    trade_count: int


class ChartSeriesPayload(BaseModel):
    candles: List[Dict[str, Union[float, int]]]
    markers: List[Dict[str, Union[float, int, str]]]
    equity: List[Dict[str, Union[float, int]]]
    drawdown: List[Dict[str, Union[float, int]]]
    exposure: List[Dict[str, Union[float, int]]]
    net_units: List[Dict[str, Union[float, int]]]


class RunStatusResponse(BaseModel):
    run_id: str
    mode: str
    status: str
    created_at: datetime
    completed_at: Optional[datetime] = None
    error: Optional[str] = None
    summary: Optional[BacktestSummary] = None
    strategy_details: List[Dict[str, Any]] = Field(default_factory=list)
    latest_weights: List[Dict[str, Any]] = Field(default_factory=list)
    diagnostics: Dict[str, Any] = Field(default_factory=dict)


class HealthResponse(BaseModel):
    status: str
    service: str
    data_source_default: str
    fastapi_available: bool


class DataSyncRequest(BaseModel):
    exchange: str = "binance_spot"
    symbol: str = "BTCUSDT"
    interval: str = "1m"
    start: datetime
    end: datetime
    db_path: str = ""
    limit: int = Field(default=1000, ge=1, le=1000)
    closed_only: bool = True

    @field_validator("interval")
    @classmethod
    def validate_sync_interval(cls, value: str) -> str:
        allowed = {"1m", "5m", "15m", "1h", "4h", "1d"}
        if value not in allowed:
            raise ValueError(f"interval must be one of {sorted(allowed)}")
        return value

    @field_validator("exchange")
    @classmethod
    def validate_exchange(cls, value: str) -> str:
        if value != "binance_spot":
            raise ValueError("only binance_spot is supported by the built-in downloader")
        return value

    @field_validator("end")
    @classmethod
    def validate_sync_dates(cls, value: datetime, info: Any) -> datetime:
        start = info.data.get("start")
        if start is not None and value <= start:
            raise ValueError("end must be later than start")
        return value


class LatestDataUpdateRequest(BaseModel):
    exchange: str = "binance_spot"
    symbol: str = "BTCUSDT"
    interval: str = "1m"
    db_path: str = ""
    lookback_days: int = Field(default=30, ge=1, le=3650)
    limit: int = Field(default=1000, ge=1, le=1000)

    @field_validator("interval")
    @classmethod
    def validate_update_interval(cls, value: str) -> str:
        allowed = {"1m", "5m", "15m", "1h", "4h", "1d"}
        if value not in allowed:
            raise ValueError(f"interval must be one of {sorted(allowed)}")
        return value

    @field_validator("exchange")
    @classmethod
    def validate_update_exchange(cls, value: str) -> str:
        if value != "binance_spot":
            raise ValueError("only binance_spot is supported by the built-in updater")
        return value


class DataSyncRunResponse(BaseModel):
    run_id: str
    status: str
    db_path: str = ""
    exchange: str
    symbol: str
    interval: str
    start: datetime
    end: datetime
    rows_received: int = 0
    rows_written: int = 0
    requests: int = 0
    created_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error: Optional[str] = None


class DataCoverageItem(BaseModel):
    exchange: str
    symbol: str
    interval: str
    rows: int
    start: Optional[datetime] = None
    end: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class DatabaseStatusResponse(BaseModel):
    db_path: str
    exists: bool
    initialized: bool
    table_count: int
    coverage: List[DataCoverageItem] = Field(default_factory=list)


class KlineRow(BaseModel):
    exchange: str
    symbol: str
    interval: str
    time: datetime
    open_time_ms: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    quote_volume: float
    trade_count: int


class KlinePreviewResponse(BaseModel):
    db_path: str
    rows: List[KlineRow] = Field(default_factory=list)


class SchedulerStartRequest(LatestDataUpdateRequest):
    interval_seconds: int = Field(default=86400, ge=60)
    run_immediately: bool = True


class SchedulerStatusResponse(BaseModel):
    running: bool
    interval_seconds: int
    symbol: str = ""
    interval: str = ""
    db_path: str = ""
    last_started_at: Optional[datetime] = None
    next_run_at: Optional[datetime] = None
    last_error: Optional[str] = None
    last_result: Optional[Dict[str, Any]] = None
