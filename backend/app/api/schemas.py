from __future__ import annotations

from datetime import date, datetime
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
        allowed = {"fixture", "sqlite", "auto", "yfinance", "alpaca"}
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


class StrategyOptimizationRequest(BaseBacktestRequest):
    strategy_id: str = "trend_macd"
    max_candidates: int = Field(default=18, ge=1, le=64)


class StrategyOptimizationResponse(BaseModel):
    status: str
    selected_priority: str
    framework: List[Dict[str, Any]] = Field(default_factory=list)
    split: Dict[str, Any] = Field(default_factory=dict)
    baseline: Optional[Dict[str, Any]] = None
    best: Optional[Dict[str, Any]] = None
    candidates: List[Dict[str, Any]] = Field(default_factory=list)
    recommendations: List[str] = Field(default_factory=list)


class CostStressRequest(BaseBacktestRequest):
    strategy_id: str = "trend_macd"
    strategy_params: dict[str, float] = Field(default_factory=dict)
    max_scenarios: int = Field(default=5, ge=1, le=6)


class CostStressResponse(BaseModel):
    status: str
    selected_priority: str
    framework: List[Dict[str, Any]] = Field(default_factory=list)
    strategy_id: str
    strategy_params: Dict[str, Any] = Field(default_factory=dict)
    baseline: Optional[Dict[str, Any]] = None
    scenarios: List[Dict[str, Any]] = Field(default_factory=list)
    survival_rate_pct: float
    worst_case: Optional[Dict[str, Any]] = None
    recommendations: List[str] = Field(default_factory=list)


class WalkForwardRequest(BaseBacktestRequest):
    strategy_id: str = "trend_macd"
    strategy_params: dict[str, float] = Field(default_factory=dict)
    windows: int = Field(default=4, ge=1, le=8)
    max_candidates: int = Field(default=6, ge=1, le=32)
    symbols: list[str] = Field(default_factory=list)


class WalkForwardResponse(BaseModel):
    status: str
    selected_priority: str
    framework: List[Dict[str, Any]] = Field(default_factory=list)
    strategy_id: str
    strategy_params: Dict[str, Any] = Field(default_factory=dict)
    windows: List[Dict[str, Any]] = Field(default_factory=list)
    regimes: List[Dict[str, Any]] = Field(default_factory=list)
    stability: Dict[str, Any] = Field(default_factory=dict)
    recommendations: List[str] = Field(default_factory=list)


class PortfolioOptimizationRequest(BaseBacktestRequest):
    weights: list[StrategyWeight] = Field(default_factory=list)
    max_single_weight: float = Field(default=0.35, ge=0.05, le=1.0)
    correlation_penalty: float = Field(default=0.75, ge=0.0, le=2.0)
    cash_reserve_pct: float = Field(default=0.0, ge=0.0, le=80.0)


class PortfolioOptimizationResponse(BaseModel):
    status: str
    selected_priority: str
    framework: List[Dict[str, Any]] = Field(default_factory=list)
    baseline_weights: Dict[str, float] = Field(default_factory=dict)
    optimized_weights: Dict[str, float] = Field(default_factory=dict)
    optimized_weight_rows: List[Dict[str, Any]] = Field(default_factory=list)
    baseline_summary: Dict[str, Any] = Field(default_factory=dict)
    optimized_summary: Dict[str, Any] = Field(default_factory=dict)
    improvement: Dict[str, Any] = Field(default_factory=dict)
    strategy_allocations: List[Dict[str, Any]] = Field(default_factory=list)
    correlation_matrix: List[Dict[str, Any]] = Field(default_factory=list)
    correlation_pairs: List[Dict[str, Any]] = Field(default_factory=list)
    risk_budget: Dict[str, Any] = Field(default_factory=dict)
    risk_overlay: Dict[str, Any] = Field(default_factory=dict)
    recommendations: List[str] = Field(default_factory=list)


class ResearchPromotionGateRequest(BaseBacktestRequest):
    mode: str = "portfolio"
    strategy_id: str = "trend_macd"
    strategy_params: Dict[str, float] = Field(default_factory=dict)
    weights: list[StrategyWeight] = Field(default_factory=list)
    symbols: list[str] = Field(default_factory=list)
    skip_deep_checks: bool = False
    persist_manifest: bool = True
    register_experiment: bool = False
    experiment_name: str = ""
    notes: str = ""
    max_scenarios: int = Field(default=2, ge=1, le=6)
    windows: int = Field(default=2, ge=1, le=8)
    max_candidates: int = Field(default=1, ge=1, le=32)
    max_single_weight: float = Field(default=0.35, ge=0.05, le=1.0)
    correlation_penalty: float = Field(default=0.75, ge=0.0, le=2.0)
    cash_reserve_pct: float = Field(default=5.0, ge=0.0, le=80.0)

    @field_validator("mode")
    @classmethod
    def validate_gate_mode(cls, value: str) -> str:
        allowed = {"single", "portfolio"}
        if value not in allowed:
            raise ValueError(f"mode must be one of {sorted(allowed)}")
        return value


class ResearchPromotionGateResponse(BaseModel):
    status: str
    selected_priority: str
    framework: List[Dict[str, Any]] = Field(default_factory=list)
    decision: str
    next_stage: str
    manifest_id: str
    manifest_path: str = ""
    strategy_version: str = ""
    experiment_record: Dict[str, Any] = Field(default_factory=dict)
    data_quality: Dict[str, Any] = Field(default_factory=dict)
    backtest_summary: Dict[str, Any] = Field(default_factory=dict)
    gates: List[Dict[str, Any]] = Field(default_factory=list)
    recommendations: List[str] = Field(default_factory=list)


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
    turnover: List[Dict[str, Union[float, int]]] = Field(default_factory=list)
    leverage: List[Dict[str, Union[float, int]]] = Field(default_factory=list)


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


class DataQualityRequest(BaseModel):
    source: str = "fixture"
    symbol: str = "BTCUSDT"
    interval: str = "1h"
    start: datetime
    end: datetime
    data_db_path: str = ""

    @field_validator("source")
    @classmethod
    def validate_quality_source(cls, value: str) -> str:
        allowed = {"fixture", "sqlite", "auto", "yfinance", "alpaca"}
        if value not in allowed:
            raise ValueError(f"source must be one of {sorted(allowed)}")
        return value

    @field_validator("interval")
    @classmethod
    def validate_quality_interval(cls, value: str) -> str:
        allowed = {"1m", "5m", "15m", "1h", "4h", "1d"}
        if value not in allowed:
            raise ValueError(f"interval must be one of {sorted(allowed)}")
        return value

    @field_validator("end")
    @classmethod
    def validate_quality_dates(cls, value: datetime, info: Any) -> datetime:
        start = info.data.get("start")
        if start is not None and value <= start:
            raise ValueError("end must be later than start")
        return value


class DataQualityResponse(BaseModel):
    status: str
    selected_priority: str
    framework: List[Dict[str, Any]] = Field(default_factory=list)
    source: str
    actual_source: str
    symbol: str
    interval: str
    row_count: int
    raw_row_count: int = 0
    expected_rows: int
    coverage_pct: float
    missing_bars: int
    duplicate_timestamps: int
    cleaning_loss_rows: int
    invalid_ohlc: int
    non_positive_prices: int
    non_positive_volume: int
    large_price_jumps: int
    volume_anomalies: int
    max_gap_bars: int
    max_price_jump_pct: float
    first_timestamp: Optional[str] = None
    last_timestamp: Optional[str] = None
    quality_score: float
    is_usable: bool
    fingerprint: str
    data_version: str
    issues: List[Dict[str, str]] = Field(default_factory=list)


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


class USDataQualityResponse(BaseModel):
    row_count: int
    duplicate_timestamps: int
    non_positive_prices: int
    invalid_ohlc: int
    missing_bars: int
    is_usable: bool


class USDataSyncRequest(BaseModel):
    vendor: str = "yfinance"
    asset_class: str = "equity"
    symbol: str = "AAPL"
    bar_size: str = "1d"
    start: datetime
    end: datetime
    data_root: str = "data"

    @field_validator("vendor")
    @classmethod
    def validate_us_vendor(cls, value: str) -> str:
        if value != "yfinance":
            raise ValueError("only yfinance is currently wired as the auxiliary MVP data source")
        return value

    @field_validator("bar_size")
    @classmethod
    def validate_us_bar_size(cls, value: str) -> str:
        allowed = {"1m", "2m", "5m", "15m", "30m", "1h", "1d"}
        if value not in allowed:
            raise ValueError(f"bar_size must be one of {sorted(allowed)}")
        return value

    @field_validator("end")
    @classmethod
    def validate_us_dates(cls, value: datetime, info: Any) -> datetime:
        start = info.data.get("start")
        if start is not None and value <= start:
            raise ValueError("end must be later than start")
        return value


class USDataSyncResponse(BaseModel):
    run_id: str
    status: str
    vendor: str
    asset_class: str
    symbol: str
    bar_size: str
    start: datetime
    end: datetime
    rows_received: int
    rows_cleaned: int
    raw_files: List[str] = Field(default_factory=list)
    cleaned_files: List[str] = Field(default_factory=list)
    quality: USDataQualityResponse
    created_at: datetime
    completed_at: Optional[datetime] = None
    error: Optional[str] = None


class USFeatureBuildRequest(BaseModel):
    vendor: str = "yfinance"
    asset_class: str = "equity"
    symbol: str = "AAPL"
    bar_size: str = "1d"
    start: datetime
    end: datetime
    data_root: str = "data"
    universe: str = "default"
    version: str = "v1"
    auto_sync: bool = False


class USFeatureBuildResponse(BaseModel):
    run_id: str
    status: str
    rows_written: int
    files_written: List[str] = Field(default_factory=list)
    version: str
    created_at: datetime
    error: Optional[str] = None


class USCorporateActionInput(BaseModel):
    symbol: str
    action_type: str
    ex_date: date
    ratio: float = Field(default=1.0, gt=0.0)
    cash_amount: float = Field(default=0.0, ge=0.0)
    source: str = ""

    @field_validator("action_type")
    @classmethod
    def validate_action_type(cls, value: str) -> str:
        normalized = value.lower()
        allowed = {"split", "dividend"}
        if normalized not in allowed:
            raise ValueError(f"action_type must be one of {sorted(allowed)}")
        return normalized


class USEarningsEventInput(BaseModel):
    symbol: str
    event_date: date
    source: str = ""


class USEventBacktestRequest(BaseModel):
    vendor: str = "yfinance"
    asset_class: str = "equity"
    symbol: str = "AAPL"
    symbols: List[str] = Field(default_factory=list)
    bar_size: str = "1d"
    strategy_id: str = "trend_momentum"
    strategy_params: Dict[str, Any] = Field(default_factory=dict)
    feature_names: List[str] = Field(default_factory=list)
    feature_version: str = "v1"
    feature_universe: str = "default"
    start: datetime
    end: datetime
    data_root: str = "data"
    capital: float = Field(default=100000.0, gt=0)
    commission_rate: float = Field(default=0.0001, ge=0.0, le=0.05)
    slippage_bps: float = Field(default=1.0, ge=0.0, le=500.0)
    max_symbol_weight: float = Field(default=0.10, gt=0.0, le=1.0)
    max_order_notional_pct: float = Field(default=0.10, gt=0.0, le=1.0)
    max_gross_exposure: float = Field(default=1.0, gt=0.0, le=5.0)
    min_cash_buffer_pct: float = Field(default=0.02, ge=0.0, le=1.0)
    default_strategy_weight: float = Field(default=0.10, gt=0.0, le=1.0)
    strategy_allocations: Dict[str, float] = Field(default_factory=dict)
    cash_reserve_weight: float = Field(default=0.05, ge=0.0, le=1.0)
    max_group_weight: Optional[float] = Field(default=None, gt=0.0, le=1.0)
    group_map: Dict[str, str] = Field(default_factory=dict)
    min_trade_notional: float = Field(default=25.0, ge=0.0)
    min_weight_change: float = Field(default=0.0, ge=0.0, le=1.0)
    blacklisted_symbols: List[str] = Field(default_factory=list)
    long_only: bool = True
    auto_sync: bool = True
    corporate_actions: List[USCorporateActionInput] = Field(default_factory=list)
    earnings_events: List[USEarningsEventInput] = Field(default_factory=list)

    @field_validator("strategy_id")
    @classmethod
    def validate_us_strategy(cls, value: str) -> str:
        allowed = {"trend_momentum", "short_reversion", "factor_rank", "earnings_drift", "etf_rotation"}
        if value not in allowed:
            raise ValueError(f"strategy_id must be one of {sorted(allowed)}")
        return value


class USEventBacktestResponse(BaseModel):
    run_id: str
    status: str
    summary: Dict[str, Any]
    order_count: int
    fill_count: int
    snapshot_count: int
    event_count: int
    diagnostics: Dict[str, Any] = Field(default_factory=dict)


class USReconciliationRequest(BaseModel):
    ledger_dir: str = "data/ledger/paper"
    tolerance: float = Field(default=1e-6, ge=0.0)


class USReconciliationBreakResponse(BaseModel):
    symbol: str
    local_quantity: float
    broker_quantity: float
    local_market_value: float = 0.0
    broker_market_value: float = 0.0


class USReconciliationResponse(BaseModel):
    status: str
    break_count: int
    breaks: List[USReconciliationBreakResponse] = Field(default_factory=list)


class USUnifiedBacktestResponse(BaseModel):
    run_id: str
    status: str
    summary: Dict[str, Any]
    equity_consistent: bool
    equity_consistency_msg: str
    order_count: int
    fill_count: int
    snapshot_count: int
    event_count: int
    ledger_final_equity: float
    ledger_total_fees: float
    ledger_curve_points: int
    data_version: str = ""
    strategy_version: str = ""
    manifest_id: str = ""
    determinism_verified: bool = False
    equity_curve: List[Dict[str, Any]] = Field(default_factory=list)
    drawdown_curve: List[Dict[str, Any]] = Field(default_factory=list)
    turnover_report: Optional[Dict[str, Any]] = None
    gap_skipped_bars: List[Dict[str, Any]] = Field(default_factory=list)
    cost_summary: Optional[Dict[str, Any]] = None
    diagnostics: Dict[str, Any] = Field(default_factory=dict)


class USPaperRunDayRequest(BaseModel):
    vendor: str = "yfinance"
    asset_class: str = "equity"
    symbol: str = "AAPL"
    symbols: List[str] = Field(default_factory=list)
    bar_size: str = "1d"
    strategy_id: str = "trend_momentum"
    strategy_params: Dict[str, Any] = Field(default_factory=dict)
    feature_names: List[str] = Field(default_factory=list)
    feature_version: str = "v1"
    feature_universe: str = "default"
    target_date: date
    data_root: str = "data"
    capital: float = Field(default=100000.0, gt=0)
    commission_rate: float = Field(default=0.0001, ge=0.0, le=0.05)
    slippage_bps: float = Field(default=1.0, ge=0.0, le=500.0)

    @field_validator("strategy_id")
    @classmethod
    def validate_us_strategy(cls, value: str) -> str:
        allowed = {"trend_momentum", "short_reversion", "factor_rank", "etf_rotation"}
        if value not in allowed:
            raise ValueError(f"strategy_id must be one of {sorted(allowed)}")
        return value


class USPaperStatusResponse(BaseModel):
    equity: float
    cash: float
    buying_power: float
    positions: int
    kill_switch_triggered: bool
    kill_switch_reason: Optional[str] = None
    days_traded: int
    healthy: bool
    last_reconciliation_passed: Optional[bool] = None


class USPaperDayResultResponse(BaseModel):
    date: date
    starting_equity: float
    ending_equity: float
    daily_pnl: float
    daily_return_pct: float
    orders_submitted: int
    orders_filled: int
    orders_rejected: int
    orders_cancelled: int
    kill_switch_triggered: bool
    reconciliation_passed: bool
    reconciliation_diff: Dict[str, Any] = Field(default_factory=dict)
    errors: List[str] = Field(default_factory=list)


class EventDrivenCostStressResponse(BaseModel):
    status: str
    engine: str
    strategy_id: str
    symbol: str
    interval: str
    scenarios: List[Dict[str, Any]] = Field(default_factory=list)
    survival_rate_pct: float
    baseline_fill_count: int
    engine_note: str = ""


class PaperBacktestResponse(BaseModel):
    status: str
    days_processed: int
    total_pnl: float
    final_equity: float
    healthy: bool
    kill_switch_triggered: bool
    daily_results: List[Dict[str, Any]] = Field(default_factory=list)


class PaperResetResponse(BaseModel):
    status: str
    message: str
