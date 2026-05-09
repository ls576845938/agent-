from __future__ import annotations

from typing import Any

from backend.app import __version__
from backend.app.api.schemas import (
    ChartSeriesPayload,
    CostStressRequest,
    CostStressResponse,
    DataCoverageItem,
    EventDrivenCostStressResponse,
    PaperBacktestResponse,
    PaperResetResponse,
    DataQualityRequest,
    DataQualityResponse,
    DataSyncRequest,
    DataSyncRunResponse,
    DatabaseStatusResponse,
    HealthResponse,
    KlinePreviewResponse,
    LatestDataUpdateRequest,
    PortfolioBacktestRequest,
    PortfolioOptimizationRequest,
    PortfolioOptimizationResponse,
    ResearchPromotionGateRequest,
    ResearchPromotionGateResponse,
    RunStatusResponse,
    SchedulerStartRequest,
    SchedulerStatusResponse,
    SingleBacktestRequest,
    StrategyOptimizationRequest,
    StrategyOptimizationResponse,
    StrategyInfo,
    USDataSyncRequest,
    USDataSyncResponse,
    USEventBacktestRequest,
    USEventBacktestResponse,
    USFeatureBuildRequest,
    USFeatureBuildResponse,
    USPaperDayResultResponse,
    USPaperRunDayRequest,
    USPaperStatusResponse,
    USReconciliationRequest,
    USReconciliationResponse,
    USUnifiedBacktestResponse,
    WalkForwardRequest,
    WalkForwardResponse,
)
from backend.app.core.config import settings
from backend.app.core.deps import data_update_scheduler, market_data_service, promotion_gate_service, research_service, run_registry, us_quant_service
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
        from fastapi import APIRouter, Depends, FastAPI, HTTPException, Response, Security
        from fastapi.middleware.cors import CORSMiddleware
        from fastapi.security import APIKeyHeader
    except ImportError as exc:
        from backend.app.core.exceptions import DependencyUnavailableError

        raise DependencyUnavailableError(
            "FastAPI is not installed. Install project dependencies from pyproject.toml before starting the API."
        ) from exc

    from backend.app.services.data_management import DataSyncSpec, LatestUpdateSpec, resolve_data_db_path
    from backend.app.services.market_data import inspect_market_data_quality

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

    @app.get("/metrics")
    async def metrics() -> Response:
        from quant_us.monitoring.metrics import MetricsCollector

        collector = MetricsCollector()
        return Response(
            collector.to_prometheus_text(),
            media_type="text/plain; version=0.0.4",
        )

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

    @router.post("/data/quality", response_model=DataQualityResponse, dependencies=[Depends(verify_api_key)])
    async def inspect_data_quality(request: DataQualityRequest) -> DataQualityResponse:
        try:
            return DataQualityResponse.model_validate(
                inspect_market_data_quality(
                    source=request.source,
                    symbol=request.symbol,
                    interval=request.interval,
                    start=request.start,
                    end=request.end,
                    db_path=request.data_db_path,
                )
            )
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

    @router.post("/us/data/quality-report", dependencies=[Depends(verify_api_key)])
    async def us_data_quality_report(request: USDataSyncRequest):
        """Generate 6-type data quality report for a symbol."""
        try:
            result = us_quant_service.data_quality_report(request.model_dump())
            return result
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    @router.post("/us/data/sync", response_model=USDataSyncResponse, dependencies=[Depends(verify_api_key)])
    async def sync_us_market_data(request: USDataSyncRequest) -> USDataSyncResponse:
        try:
            result = us_quant_service.sync_data(request.model_dump())
            if result["status"] != "completed":
                raise HTTPException(status_code=400, detail=result.get("error") or "US data sync failed")
            return USDataSyncResponse.model_validate(result)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/us/features/build", response_model=USFeatureBuildResponse, dependencies=[Depends(verify_api_key)])
    async def build_us_features(request: USFeatureBuildRequest) -> USFeatureBuildResponse:
        try:
            result = us_quant_service.build_features(request.model_dump())
            if result["status"] != "completed":
                raise HTTPException(status_code=400, detail=result.get("error") or "US feature build failed")
            return USFeatureBuildResponse.model_validate(result)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/us/backtests/event", response_model=USEventBacktestResponse, dependencies=[Depends(verify_api_key)])
    async def run_us_event_backtest(request: USEventBacktestRequest) -> USEventBacktestResponse:
        try:
            result = us_quant_service.run_event_backtest(request.model_dump())
            return USEventBacktestResponse.model_validate(result)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/us/reconcile", response_model=USReconciliationResponse, dependencies=[Depends(verify_api_key)])
    async def reconcile_us_ledger(request: USReconciliationRequest) -> USReconciliationResponse:
        try:
            result = us_quant_service.reconcile_local_ledger(request.model_dump())
            return USReconciliationResponse.model_validate(result)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/us/backtests/unified", response_model=USUnifiedBacktestResponse, dependencies=[Depends(verify_api_key)])
    async def run_us_unified_backtest(request: USEventBacktestRequest) -> USUnifiedBacktestResponse:
        try:
            result = us_quant_service.run_unified_backtest(request.model_dump())
            return USUnifiedBacktestResponse.model_validate(result)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/us/paper/run-day", response_model=USPaperDayResultResponse, dependencies=[Depends(verify_api_key)])
    async def run_us_paper_day(request: USPaperRunDayRequest) -> USPaperDayResultResponse:
        try:
            result = us_quant_service.run_paper_day(request.model_dump())
            return USPaperDayResultResponse.model_validate(result)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/us/paper/status", response_model=USPaperStatusResponse, dependencies=[Depends(verify_api_key)])
    async def us_paper_status() -> USPaperStatusResponse:
        try:
            result = us_quant_service.paper_status()
            return USPaperStatusResponse.model_validate(result)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/us/paper/daily-results", response_model=list[USPaperDayResultResponse], dependencies=[Depends(verify_api_key)])
    async def us_paper_daily_results() -> list[USPaperDayResultResponse]:
        try:
            results = us_quant_service.paper_daily_results()
            return [USPaperDayResultResponse.model_validate(r) for r in results]
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/us/paper/backtest", response_model=PaperBacktestResponse, dependencies=[Depends(verify_api_key)])
    async def run_us_paper_backtest(request: USEventBacktestRequest) -> PaperBacktestResponse:
        try:
            result = us_quant_service.run_paper_backtest(request.model_dump())
            return PaperBacktestResponse.model_validate(result)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/us/paper/reset", response_model=PaperResetResponse, dependencies=[Depends(verify_api_key)])
    async def reset_us_paper_loop() -> PaperResetResponse:
        try:
            result = us_quant_service.reset_paper_loop()
            return PaperResetResponse.model_validate(result)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

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

    @router.post("/backtests/portfolio-optimize", response_model=PortfolioOptimizationResponse, dependencies=[Depends(verify_api_key)])
    async def optimize_portfolio(request: PortfolioOptimizationRequest) -> PortfolioOptimizationResponse:
        try:
            return PortfolioOptimizationResponse.model_validate(research_service.optimize_portfolio(request.model_dump()))
        except (QuantStationError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/research/promotion-gate", response_model=ResearchPromotionGateResponse, dependencies=[Depends(verify_api_key)])
    async def evaluate_research_promotion_gate(request: ResearchPromotionGateRequest) -> ResearchPromotionGateResponse:
        try:
            return ResearchPromotionGateResponse.model_validate(promotion_gate_service.evaluate(request.model_dump()))
        except (QuantStationError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/backtests/optimize", response_model=StrategyOptimizationResponse, dependencies=[Depends(verify_api_key)])
    async def optimize_strategy(request: StrategyOptimizationRequest) -> StrategyOptimizationResponse:
        try:
            return StrategyOptimizationResponse.model_validate(research_service.optimize_strategy(request.model_dump()))
        except (QuantStationError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/backtests/cost-stress", response_model=CostStressResponse, dependencies=[Depends(verify_api_key)])
    async def run_cost_stress(request: CostStressRequest) -> CostStressResponse:
        try:
            return CostStressResponse.model_validate(research_service.run_cost_stress(request.model_dump()))
        except (QuantStationError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/backtests/cost-stress/event-driven", response_model=EventDrivenCostStressResponse, dependencies=[Depends(verify_api_key)])
    async def run_event_driven_cost_stress(request: CostStressRequest) -> EventDrivenCostStressResponse:
        try:
            return EventDrivenCostStressResponse.model_validate(
                research_service.run_event_driven_cost_stress(request.model_dump())
            )
        except (QuantStationError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/backtests/walk-forward", response_model=WalkForwardResponse, dependencies=[Depends(verify_api_key)])
    async def run_walk_forward(request: WalkForwardRequest) -> WalkForwardResponse:
        try:
            return WalkForwardResponse.model_validate(research_service.run_walk_forward(request.model_dump()))
        except (QuantStationError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

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

    # ------------------------------------------------------------------
    # R-series: Research & Portfolio endpoints
    # ------------------------------------------------------------------

    @router.get("/research/experiments")
    async def list_research_experiments():
        """List research experiments from the lab."""
        try:
            from quant_us.research.lab.manifest import ExperimentManager
            mgr = ExperimentManager()
            return mgr.list_experiments()
        except Exception:
            return []

    @router.get("/research/candidates")
    async def list_research_candidates():
        """List strategy candidates from the lab."""
        try:
            from quant_us.research.lab.manifest import ExperimentManager
            mgr = ExperimentManager()
            return mgr.list_candidates()
        except Exception:
            return []

    @router.get("/research/experiments/{experiment_id}/ranking")
    async def experiment_ranking(experiment_id: str):
        """Get ranked candidates for an experiment."""
        from quant_us.research.automation.scorer import CandidateScorer
        scorer = CandidateScorer()
        scores = scorer.score(experiment_id)
        ranked = scorer.rank(scores)
        return [s.__dict__ for s in ranked]

    @router.post("/research/experiments/compare")
    async def compare_experiments(request: dict):
        """Compare multiple experiments. Body: {experiment_ids: [...], metric: "score"}"""
        from quant_us.research.lab.manifest import ExperimentManager
        mgr = ExperimentManager()
        return mgr.compare_experiments(
            request.get("experiment_ids", []),
            request.get("metric", "score"),
        )

    @router.get("/research/candidates/{candidate_id}/lineage")
    async def candidate_lineage(candidate_id: str):
        """Get candidate lineage chain."""
        from quant_us.research.lab.manifest import ExperimentManager
        mgr = ExperimentManager()
        return mgr.get_lineage(candidate_id)

    @router.post("/research/candidates/{candidate_id}/promotion-gate")
    async def check_promotion_gate(candidate_id: str):
        """Evaluate candidate through research promotion gate."""
        from quant_us.research.automation.promotion_gate import ResearchPromotionGate
        gate = ResearchPromotionGate()
        result = gate.evaluate(candidate_id)
        return result.__dict__

    @router.get("/portfolio/status")
    async def portfolio_status():
        """Return current portfolio construction status."""
        try:
            from quant_us.portfolio.construction.engine import PortfolioConstructionEngine
            engine = PortfolioConstructionEngine()
            # Return a summary - look for saved portfolio targets
            import json
            from pathlib import Path
            target_dir = Path("data/portfolio/targets")
            if target_dir.exists():
                targets = sorted(target_dir.glob("*.json"))
                if targets:
                    latest = json.loads(targets[-1].read_text())
                    return {
                        "status": "ok",
                        "portfolio_count": len(targets),
                        "latest_portfolio": latest,
                    }
            return {"status": "ok", "portfolio_count": 0, "latest_portfolio": None}
        except Exception as exc:
            return {"status": "error", "detail": str(exc)}

    app.include_router(router)
    return app
