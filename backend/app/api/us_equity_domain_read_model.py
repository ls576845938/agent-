"""US equity read-only domain read-model router; integrator owns app wiring."""

from __future__ import annotations

from typing import Any, Callable, Protocol

from fastapi import APIRouter, Depends, Response


class USEquityDomainReadModelServiceProtocol(Protocol):
    def read(self) -> dict[str, Any]: ...


def build_us_equity_domain_read_model_router(
    *,
    service: USEquityDomainReadModelServiceProtocol,
    verify_api_key: Callable[..., Any],
) -> APIRouter:
    router = APIRouter(
        prefix="/research/us-equity",
        tags=["us-equity-domain-read-model"],
    )

    @router.get("/domain-read-model", dependencies=[Depends(verify_api_key)])
    def get_us_equity_domain_read_model(response: Response) -> dict[str, Any]:
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
        return service.read()

    return router


__all__ = ["build_us_equity_domain_read_model_router"]
