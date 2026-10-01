from __future__ import annotations

from backend.app.services.strategy_history_catalog import StrategyHistoryCatalogService


def build_strategy_history_catalog_router(
    service: StrategyHistoryCatalogService | None = None,
):
    from fastapi import APIRouter

    router = APIRouter(prefix="/research")
    catalog_service = service or StrategyHistoryCatalogService()

    @router.get("/strategy-history/catalog")
    def get_strategy_history_catalog():
        return catalog_service.get_catalog()

    return router
