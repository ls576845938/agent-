"""Read-only FastAPI routes for the US IBKR runtime operator view.

The router is intentionally not registered here.  The shared app factory and
route ownership belong to the integration ticket; an integrator can include
``build_us_ibkr_runtime_router(...)`` under the repository's ``/api`` prefix.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Callable, Protocol

from fastapi import APIRouter, HTTPException, Response

from backend.app.api.us_ibkr_runtime_schemas import (
    AccountStatus,
    BrokerTruthStatus,
    GatewayStatus,
    IBKRIncidentsResponse,
    IBKRRuntimeStatusResponse,
    IncidentRecord,
    KillSwitchStatus,
    MarketDataStatus,
    OMSStatus,
    ReconciliationStatus,
    RecoveryStatus,
    RuntimeBlocker,
    RuntimeSafetyFlags,
)


class USIBKRRuntimeReadServiceProtocol(Protocol):
    def status(self) -> Mapping[str, Any] | IBKRRuntimeStatusResponse: ...

    def reconciliation(self) -> Mapping[str, Any] | ReconciliationStatus: ...

    def incidents(self) -> Mapping[str, Any] | IBKRIncidentsResponse: ...


def _payload(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        try:
            return value.model_dump(mode="json")
        except TypeError:
            return value.model_dump()
    if isinstance(value, Mapping):
        return dict(value)
    return value


def _read_dependencies(verify_api_key: Callable[..., Any] | None) -> list[Any]:
    if verify_api_key is None:
        return []
    from fastapi import Depends

    return [Depends(verify_api_key)]


def build_us_ibkr_runtime_router(
    *,
    service: USIBKRRuntimeReadServiceProtocol,
    verify_api_key: Callable[..., Any] | None = None,
):
    """Build the IBKR read-only router without mutating shared app wiring."""

    router = APIRouter(prefix="/us/ibkr", tags=["us-ibkr-runtime"])
    guarded = _read_dependencies(verify_api_key)

    def no_store(response: Response) -> None:
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"

    @router.get(
        "/runtime",
        response_model=IBKRRuntimeStatusResponse,
        response_model_exclude_none=False,
        dependencies=guarded,
    )
    def get_runtime(response: Response) -> Any:
        no_store(response)
        try:
            return _payload(service.status())
        except Exception as exc:
            # Do not leak provider errors or imply that another local loop is
            # healthy when IBKR runtime status cannot be read.
            raise HTTPException(
                status_code=503,
                detail="ibkr_runtime_status_unavailable_fail_closed",
            ) from exc

    @router.get(
        "/reconciliation",
        response_model=ReconciliationStatus,
        response_model_exclude_none=False,
        dependencies=guarded,
    )
    def get_reconciliation(response: Response) -> Any:
        no_store(response)
        try:
            return _payload(service.reconciliation())
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail="ibkr_reconciliation_status_unavailable_fail_closed",
            ) from exc

    @router.get(
        "/incidents",
        response_model=IBKRIncidentsResponse,
        response_model_exclude_none=False,
        dependencies=guarded,
    )
    def get_incidents(response: Response) -> Any:
        no_store(response)
        try:
            return _payload(service.incidents())
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail="ibkr_incident_status_unavailable_fail_closed",
            ) from exc

    return router


__all__ = [
    "AccountStatus",
    "BrokerTruthStatus",
    "GatewayStatus",
    "IBKRIncidentsResponse",
    "IBKRRuntimeStatusResponse",
    "IncidentRecord",
    "KillSwitchStatus",
    "MarketDataStatus",
    "OMSStatus",
    "ReconciliationStatus",
    "RecoveryStatus",
    "RuntimeBlocker",
    "RuntimeSafetyFlags",
    "USIBKRRuntimeReadServiceProtocol",
    "build_us_ibkr_runtime_router",
]
