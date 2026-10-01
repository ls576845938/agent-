"""BTC-only read-model API contract; shared app wiring is integrator-owned."""

from __future__ import annotations

from typing import Any, Callable, Protocol

from fastapi import APIRouter, Depends, Response


class BTCDomainReadModelServiceProtocol(Protocol):
    def read(self) -> dict[str, Any]: ...


def build_btc_domain_read_model_router(
    *,
    service: BTCDomainReadModelServiceProtocol,
    verify_api_key: Callable[..., Any],
):
    router = APIRouter(prefix="/research/btc", tags=["btc-domain-read-model"])

    @router.get("/domain-read-model", dependencies=[Depends(verify_api_key)])
    def get_btc_domain_read_model(response: Response) -> dict[str, Any]:
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
        return service.read()

    return router


__all__ = ["build_btc_domain_read_model_router"]
