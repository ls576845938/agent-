"""CN domain read-model router; app wiring remains integrator-owned."""

from __future__ import annotations

from typing import Any, Callable, Protocol

from fastapi import APIRouter, Depends, Response
from fastapi.responses import JSONResponse

from backend.app.services.cn_equity_read_model import (
    CNEquityReadModelUnavailable,
    cn_equity_fail_closed_payload,
)


class CNEquityReadModelServiceProtocol(Protocol):
    def read(self) -> dict[str, Any]: ...


def build_cn_equity_router(
    *,
    service: CNEquityReadModelServiceProtocol,
    verify_api_key: Callable[..., Any],
) -> APIRouter:
    router = APIRouter(
        prefix="/research/cn-equity",
        tags=["cn-equity-domain-read-model"],
    )

    @router.get(
        "/domain-read-model",
        dependencies=[Depends(verify_api_key)],
    )
    def get_cn_equity_domain_read_model(response: Response):
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
        try:
            return service.read()
        except CNEquityReadModelUnavailable as error:
            return JSONResponse(
                status_code=503,
                content=cn_equity_fail_closed_payload(error.blocker),
                headers={
                    "Cache-Control": "no-store",
                    "Pragma": "no-cache",
                },
            )

    return router


__all__ = ["build_cn_equity_router"]
