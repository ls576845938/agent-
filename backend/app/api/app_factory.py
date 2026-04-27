from __future__ import annotations

from typing import Any

from backend.app import __version__
from backend.app.api.schemas import (
    ChartSeriesPayload,
    DataCoverageItem,
    DataSyncRequest,
    DataSyncRunResponse,
    DatabaseStatusResponse,
    HealthResponse,
    KlinePreviewResponse,
    LatestDataUpdateRequest,
    PortfolioBacktestRequest,
    RunStatusResponse,
    SchedulerStartRequest,
    SchedulerStatusResponse,
    SingleBacktestRequest,
    StrategyInfo,
)
from backend.app.core.config import settings
from backend.app.core.deps import data_update_scheduler, market_data_service, research_service, run_registry
from backend.app.core.exceptions import QuantStationError, RunNotFoundError


def _serialize_run(record: Any):
    from backend.app.api.schemas import RunStatusResponse

    result = record.result
    return RunStatusResponse(
        run_id=record.run_id,
        mode=record.mode,
        status=record.status,
        created_at=record.created_at,
        completed_at=record.completed_at,
        error=record.error,
        summary=result.summary if result else None,
        strategy_details=result.strategy_details if result else [],
        latest_weights=result.latest_weights if result else [],
        diagnostics=result.diagnostics if result else {},
    )


def _serialize_data_sync_result(result: Any):
    from backend.app.api.schemas import DataSyncRunResponse

    return DataSyncRunResponse(
        run_id=result.run_id,
        status=result.status,
        db_path=result.db_path,
        exchange=result.exchange,
        symbol=result.symbol,
        interval=result.interval,
        start=result.start,
        end=result.end,
        rows_received=result.rows_received,
        rows_written=result.rows_written,
        requests=result.requests,
        created_at=result.created_at,
        completed_at=result.completed_at,
        error=result.error,
    )


def create_app():
    try:
        from fastapi import APIRouter, Depends, FastAPI, HTTPException, Security
        from fastapi.middleware.cors import CORSMiddleware
        from fastapi.security import APIKeyHeader
    except ImportError as exc:
        from backend.app.core.exceptions import DependencyUnavailableError

        raise DependencyUnavailableError(
            "FastAPI is not installed. Install project dependencies from pyproject.toml before starting the API."
        ) from exc

    from backend.app.services.data_management import DataSyncSpec, LatestUpdateSpec, resolve_data_db_path

    api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

    async def verify_api_key(api_key: str = Security(api_key_header)) -> bool:
        if not settings.web_api_key:
            return True
        if api_key != settings.web_api_key:
            raise HTTPException(status_code=403, detail="Invalid API key")
        return True

    app = FastAPI(title="QuantStation vNext", version=__version__)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    router = APIRouter(prefix="/api")

    @router.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return HealthResponse(
            status="ok",
            service="quantstation-vnext",
            data_source_default=settings.default_data_source,
            fastapi_available=True,
        )

    @router.get("/data/database", response_model=DatabaseStatusResponse, dependencies=[Depends(verify_api_key)])
    async def database_status(db_path: str = "") -> DatabaseStatusResponse:
        try:
            return DatabaseStatusResponse.model_validate(market_data_service.database_status(db_path=db_path))
        except QuantStationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/data/coverage", response_model=list[DataCoverageItem], dependencies=[Depends(verify_api_key)])
    async def data_coverage(
        db_path: str = "",
        exchange: str = "",
        symbol: str = "",
        interval: str = "",
    ) -> list[DataCoverageItem]:
        try:
            rows = market_data_service.coverage(
                db_path=db_path,
                exchange=exchange,
                symbol=symbol.upper() if symbol else "",
                interval=interval,
            )
            return [DataCoverageItem.model_validate(row) for row in rows]
        except QuantStationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/data/klines", response_model=KlinePreviewResponse, dependencies=[Depends(verify_api_key)])
    async def preview_klines(
        db_path: str = "",
        exchange: str = "binance_spot",
        symbol: str = "",
        interval: str = "",
        limit: int = 100,
    ) -> KlinePreviewResponse:
        try:
            rows = market_data_service.preview_klines(
                db_path=db_path,
                exchange=exchange,
                symbol=symbol.upper() if symbol else "",
                interval=interval,
                limit=limit,
            )
            return KlinePreviewResponse(db_path=str(resolve_data_db_path(db_path)), rows=rows)
        except QuantStationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/data/sync-runs", response_model=list[DataSyncRunResponse], dependencies=[Depends(verify_api_key)])
    async def list_data_sync_runs(db_path: str = "", limit: int = 20) -> list[DataSyncRunResponse]:
        try:
            rows = market_data_service.list_sync_runs(db_path=db_path, limit=limit)
            resolved = str(resolve_data_db_path(db_path))
            return [
                DataSyncRunResponse(
                    run_id=row["run_id"],
                    status=row["status"],
                    db_path=resolved,
                    exchange=row["exchange"],
                    symbol=row["symbol"],
                    interval=row["interval"],
                    start=row["start_time"],
                    end=row["end_time"],
                    rows_received=row["rows_received"],
                    rows_written=row["rows_written"],
                    requests=row["requests"],
                    created_at=row["created_at"],
                    completed_at=row["completed_at"],
                    error=row["error"],
                )
                for row in rows
            ]
        except QuantStationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/data/sync", response_model=DataSyncRunResponse, dependencies=[Depends(verify_api_key)])
    async def sync_market_data(request: DataSyncRequest) -> DataSyncRunResponse:
        try:
            result = market_data_service.sync_binance_klines(
                DataSyncSpec(
                    exchange=request.exchange,
                    symbol=request.symbol,
                    interval=request.interval,
                    start=request.start,
                    end=request.end,
                    db_path=request.db_path,
                    limit=request.limit,
                    closed_only=request.closed_only,
                )
            )
            return _serialize_data_sync_result(result)
        except QuantStationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/data/update-latest", response_model=DataSyncRunResponse, dependencies=[Depends(verify_api_key)])
    async def update_latest_market_data(request: LatestDataUpdateRequest) -> DataSyncRunResponse:
        try:
            result = market_data_service.update_latest(
                LatestUpdateSpec(
                    exchange=request.exchange,
                    symbol=request.symbol,
                    interval=request.interval,
                    db_path=request.db_path,
                    lookback_days=request.lookback_days,
                    limit=request.limit,
                )
            )
            return _serialize_data_sync_result(result)
        except QuantStationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/data/scheduler", response_model=SchedulerStatusResponse, dependencies=[Depends(verify_api_key)])
    async def data_scheduler_status() -> SchedulerStatusResponse:
        return SchedulerStatusResponse.model_validate(data_update_scheduler.status())

    @router.post("/data/scheduler/start", response_model=SchedulerStatusResponse, dependencies=[Depends(verify_api_key)])
    async def start_data_scheduler(request: SchedulerStartRequest) -> SchedulerStatusResponse:
        status = data_update_scheduler.start(
            service=market_data_service,
            spec=LatestUpdateSpec(
                exchange=request.exchange,
                symbol=request.symbol,
                interval=request.interval,
                db_path=request.db_path,
                lookback_days=request.lookback_days,
                limit=request.limit,
            ),
            interval_seconds=request.interval_seconds,
            run_immediately=request.run_immediately,
        )
        return SchedulerStatusResponse.model_validate(status)

    @router.post("/data/scheduler/stop", response_model=SchedulerStatusResponse, dependencies=[Depends(verify_api_key)])
    async def stop_data_scheduler() -> SchedulerStatusResponse:
        return SchedulerStatusResponse.model_validate(data_update_scheduler.stop())

    @router.get("/strategies", response_model=list[StrategyInfo], dependencies=[Depends(verify_api_key)])
    async def list_strategies() -> list[StrategyInfo]:
        return [StrategyInfo.model_validate(descriptor.__dict__) for descriptor in research_service.list_strategies()]

    @router.post("/backtests/single", response_model=RunStatusResponse, dependencies=[Depends(verify_api_key)])
    async def run_single_backtest(request: SingleBacktestRequest) -> RunStatusResponse:
        payload = request.model_dump()
        try:
            result = research_service.run_single(payload)
            record = run_registry.create_completed_run(mode="single", request=payload, result=result)
        except QuantStationError as exc:
            record = run_registry.create_failed_run(mode="single", request=payload, error=str(exc))
        return _serialize_run(record)

    @router.post("/backtests/portfolio", response_model=RunStatusResponse, dependencies=[Depends(verify_api_key)])
    async def run_portfolio_backtest(request: PortfolioBacktestRequest) -> RunStatusResponse:
        payload = request.model_dump()
        try:
            result = research_service.run_portfolio(payload)
            record = run_registry.create_completed_run(mode="portfolio", request=payload, result=result)
        except QuantStationError as exc:
            record = run_registry.create_failed_run(mode="portfolio", request=payload, error=str(exc))
        return _serialize_run(record)

    @router.get("/runs/{run_id}", response_model=RunStatusResponse, dependencies=[Depends(verify_api_key)])
    async def get_run(run_id: str) -> RunStatusResponse:
        try:
            return _serialize_run(run_registry.get(run_id))
        except RunNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.get("/runs/{run_id}/chart", response_model=ChartSeriesPayload, dependencies=[Depends(verify_api_key)])
    async def get_run_chart(run_id: str) -> ChartSeriesPayload:
        try:
            record = run_registry.get(run_id)
        except RunNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if record.result is None:
            raise HTTPException(status_code=404, detail="No chart data available for this run")
        return ChartSeriesPayload.model_validate(record.result.chart)

    app.include_router(router)
    return app
