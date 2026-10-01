from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Mapping, Protocol
from urllib.parse import urlsplit

from backend.app.api.btc_outbound_path_redaction import (
    sanitize_btc_outbound_payload,
)
from backend.app.services.btc_private_readonly_observation import (
    BTCPrivateReadonlyObservationProjectionError,
)
from quant_crypto.application.btc_operator_contract_v2 import (
    OperatorContractError,
    validate_idempotency_key,
)


LOCAL_HOSTS = frozenset({"127.0.0.1", "::1", "localhost", "testserver"})
LOCAL_BROWSER_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})
FRESH_STATE_EMERGENCY_EXIT_FIELDS = frozenset(
    {
        "operator_action",
        "confirmation_text",
        "expected_environment",
        "expected_instrument_id",
        "expected_margin_mode",
        "expected_position_side",
        "expected_entry_cl_ord_id",
        "expected_entry_ord_id",
        "expected_oco_algo_cl_ord_id",
        "expected_oco_algo_id",
        "expected_position_contracts",
        "max_position_contracts",
    }
)
STOP_AND_FLATTEN_FIELDS = frozenset({"confirmation_text"})


class BtcDemoRuntimeServiceProtocol(Protocol):
    def catalog(self) -> dict[str, Any]: ...

    def status(self) -> dict[str, Any]: ...

    def readonly_klines(self, *, limit: int) -> dict[str, Any]: ...

    def readonly_market_view(self, *, timeframe: str, limit: int) -> dict[str, Any]: ...

    def readonly_market_ticker(self) -> dict[str, Any]: ...

    def public_market_stream(self) -> Any: ...

    def start(self, payload: Mapping[str, Any]) -> dict[str, Any]: ...

    def start_operation(
        self,
        payload: Mapping[str, Any],
        *,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]: ...

    def stop(self, payload: Mapping[str, Any]) -> dict[str, Any]: ...

    def reconcile(self, payload: Mapping[str, Any]) -> dict[str, Any]: ...

    def cancel_only(self, payload: Mapping[str, Any]) -> dict[str, Any]: ...

    def emergency_reduce_only_exit(
        self,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]: ...

    def stop_and_flatten(
        self,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]: ...

    def operator_contract_v2(self) -> dict[str, Any]: ...

    def operator_operation_v2(self, operation_id: str) -> dict[str, Any]: ...

    def acknowledge_operator_operation_v2(
        self,
        operation_id: str,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]: ...

    def execute_operator_action_v2(
        self,
        action: str,
        payload: Mapping[str, Any],
        *,
        idempotency_key: str | None,
    ) -> dict[str, Any]: ...


class BTCPrivateReadonlyObservationProjectionProtocol(Protocol):
    def read(self) -> dict[str, Any]: ...


def build_btc_demo_runtime_router(
    *,
    service: BtcDemoRuntimeServiceProtocol,
    verify_api_key: Callable[..., Any],
    repo_root: Path,
    control_enabled: bool = False,
    private_readonly_observation: (
        BTCPrivateReadonlyObservationProjectionProtocol | None
    ) = None,
):
    """Build the BTC-owned API router without mutating the shared app factory.

    Read-only endpoints are available after API-key and local-machine checks.
    Control endpoints stay fail-closed unless an integrator explicitly wires
    ``control_enabled=True`` in a separately reviewed shared-entry change.
    """

    from fastapi import APIRouter, Depends, Header, HTTPException
    from fastapi.responses import JSONResponse

    router = APIRouter(prefix="/research/btc/demo-paper", tags=["btc-demo-paper"])

    async def verify_local_demo_control(
        host: str | None = Header(default=None, alias="Host"),
        origin: str | None = Header(default=None, alias="Origin"),
        referer: str | None = Header(default=None, alias="Referer"),
    ) -> bool:
        host_name = str(urlsplit(f"//{host or ''}").hostname or "")
        if host_name not in LOCAL_HOSTS:
            raise HTTPException(status_code=403, detail="BTC Demo control is local-machine only")
        browser_source = str(origin or referer or "")
        if browser_source:
            origin_host = str(urlsplit(browser_source).hostname or "")
            if origin_host not in LOCAL_BROWSER_HOSTS:
                raise HTTPException(status_code=403, detail="BTC Demo control rejects non-local browser origins")
        return True

    guarded = [Depends(verify_api_key), Depends(verify_local_demo_control)]

    def require_control_enabled() -> None:
        if not control_enabled:
            raise HTTPException(status_code=423, detail="btc_demo_control_not_enabled_by_integrator")

    def outbound(payload: Any) -> Any:
        return sanitize_btc_outbound_payload(
            payload,
            repo_root=repo_root,
        )

    def operator_error(exc: OperatorContractError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "schema_version": "btc_demo_operator_error_v2",
                "error_code": exc.code,
                "allowed": False,
                "execution_permission": False,
                "blocker_codes": list(exc.blockers),
                "reason_codes": list(exc.reasons),
                "safety_flags": {
                    "promotion_eligible": False,
                    "paper": False,
                    "live": False,
                    "private": False,
                    "order": False,
                    "real_order": False,
                    "transfer": False,
                    "withdraw": False,
                },
            },
        )

    @router.get("/catalog", dependencies=guarded)
    def get_catalog() -> dict[str, Any]:
        return outbound(service.catalog())

    @router.get("/status", dependencies=guarded)
    def get_status() -> dict[str, Any]:
        return outbound(service.status())

    @router.get("/private-readonly-observation", dependencies=guarded)
    def get_private_readonly_observation() -> Any:
        if private_readonly_observation is None:
            raise HTTPException(
                status_code=503,
                detail="private_readonly_projection_not_configured",
                headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
            )
        try:
            payload = outbound(private_readonly_observation.read())
        except BTCPrivateReadonlyObservationProjectionError as exc:
            raise HTTPException(
                status_code=503,
                detail=str(exc),
                headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
            ) from exc
        return JSONResponse(
            content=payload,
            headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
        )

    @router.get("/operator-v2", dependencies=guarded)
    @router.get("/operator-v2/contract", dependencies=guarded)
    def get_operator_contract_v2() -> dict[str, Any]:
        method = getattr(service, "operator_contract_v2", None)
        if not callable(method):
            return {
                "schema_version": "btc_demo_operator_contract_v2",
                "allowed": False,
                "execution_permission": False,
                "blockers": ["operator_contract_capability_missing"],
                "actions": [],
                "safety_flags": {
                    "promotion_eligible": False,
                    "paper": False,
                    "live": False,
                    "private": False,
                    "order": False,
                    "real_order": False,
                    "transfer": False,
                    "withdraw": False,
                },
            }
        try:
            return outbound(method())
        except Exception:
            return operator_error(
                OperatorContractError(
                    "operator_contract_unavailable",
                    blockers=("operator_contract_unavailable",),
                    status_code=423,
                )
            )

    @router.get("/operator-v2/operations/{operation_id}", dependencies=guarded)
    def get_operator_operation_v2(operation_id: str) -> Any:
        method = getattr(service, "operator_operation_v2", None)
        if not callable(method):
            return operator_error(
                OperatorContractError(
                    "operator_operation_capability_missing",
                    blockers=("operator_operation_capability_missing",),
                    status_code=404,
                )
            )
        try:
            return outbound(method(operation_id))
        except OperatorContractError as exc:
            return operator_error(exc)
        except Exception:
            return operator_error(
                OperatorContractError(
                    "operator_action_failed",
                    blockers=("operator_action_failed",),
                    status_code=400,
                )
            )

    @router.post(
        "/operator-v2/operations/{operation_id}/acknowledge",
        dependencies=guarded,
    )
    def acknowledge_operator_operation_v2(
        operation_id: str,
        payload: dict[str, Any],
    ) -> Any:
        require_control_enabled()
        method = getattr(service, "acknowledge_operator_operation_v2", None)
        if not callable(method):
            return operator_error(
                OperatorContractError(
                    "operator_operation_acknowledgement_capability_missing",
                    blockers=("operator_operation_acknowledgement_capability_missing",),
                    status_code=423,
                )
            )
        try:
            return outbound(method(operation_id, payload))
        except OperatorContractError as exc:
            return operator_error(exc)
        except Exception:
            return operator_error(
                OperatorContractError(
                    "operator_operation_acknowledgement_failed",
                    blockers=("operator_operation_acknowledgement_failed",),
                    status_code=400,
                )
            )

    @router.post("/operator-v2/actions/{action}", dependencies=guarded)
    @router.post("/operator-v2/{action}", dependencies=guarded)
    def post_operator_action_v2(
        action: str,
        payload: dict[str, Any],
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> Any:
        require_control_enabled()
        if not validate_idempotency_key(idempotency_key):
            return operator_error(
                OperatorContractError(
                    "idempotency_key_required",
                    blockers=("idempotency_key_required",),
                    status_code=400,
                )
            )
        method = getattr(service, "execute_operator_action_v2", None)
        if not callable(method):
            return operator_error(
                OperatorContractError(
                    "operator_action_capability_missing",
                    blockers=("operator_action_capability_missing",),
                    status_code=423,
                )
            )
        try:
            return outbound(
                method(
                    action,
                    payload,
                    idempotency_key=idempotency_key,
                )
            )
        except OperatorContractError as exc:
            return operator_error(exc)
        except Exception:
            return operator_error(
                OperatorContractError(
                    "operator_action_failed",
                    blockers=("operator_action_failed",),
                    status_code=400,
                )
            )

    @router.get("/klines", dependencies=guarded)
    def get_klines(limit: int = 1_000) -> dict[str, Any]:
        try:
            return outbound(service.readonly_klines(limit=limit))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/market-view", dependencies=guarded)
    def get_market_view(timeframe: str = "1m", limit: int = 120) -> dict[str, Any]:
        if timeframe not in {"1m", "5m", "15m", "1h", "4h", "1d", "1w", "1M"} or limit < 2 or limit > 300:
            raise HTTPException(status_code=400, detail="okx_demo_public_market_query_invalid")
        try:
            return outbound(service.readonly_market_view(timeframe=timeframe, limit=limit))
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @router.get("/market-ticker", dependencies=guarded)
    def get_market_ticker() -> dict[str, Any]:
        try:
            return outbound(service.readonly_market_ticker())
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @router.get("/market-stream", dependencies=guarded)
    def get_market_stream() -> Any:
        """Local SSE bridge for one public-only upstream market stream."""
        from fastapi.responses import StreamingResponse

        try:
            hub = service.public_market_stream()
            token = hub.subscribe()
            return StreamingResponse(
                hub.sse_events(token),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache, no-transform",
                    "X-Accel-Buffering": "no",
                },
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @router.post("/start", dependencies=guarded)
    def start(
        payload: dict[str, Any],
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> Any:
        require_control_enabled()
        try:
            operation_method = getattr(service, "start_operation", None)
            if callable(operation_method):
                accepted = outbound(
                    operation_method(payload, idempotency_key=idempotency_key)
                )
                return JSONResponse(status_code=202, content=accepted)
            return outbound(service.start(payload))
        except RuntimeError as exc:
            status_code = (
                409
                if any(
                    token in str(exc)
                    for token in (
                        "already_active",
                        "operation_conflict",
                        "idempotency_key_reuse_mismatch",
                    )
                )
                else 400
            )
            raise HTTPException(status_code=status_code, detail=str(exc)) from exc

    @router.post("/stop", dependencies=guarded)
    def stop(payload: dict[str, Any]) -> dict[str, Any]:
        require_control_enabled()
        try:
            return outbound(service.stop(payload))
        except RuntimeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/stop-and-flatten", dependencies=guarded)
    def stop_and_flatten(payload: dict[str, Any]) -> dict[str, Any]:
        require_control_enabled()
        if set(payload) != STOP_AND_FLATTEN_FIELDS:
            raise HTTPException(
                status_code=400,
                detail="okx_demo_stop_and_flatten_operator_payload_fields_invalid",
            )
        try:
            return outbound(service.stop_and_flatten(payload))
        except RuntimeError as exc:
            status_code = (
                409
                if "already_attempted" in str(exc)
                else 400
            )
            raise HTTPException(status_code=status_code, detail=str(exc)) from exc

    @router.post("/reconcile", dependencies=guarded)
    def reconcile(payload: dict[str, Any]) -> dict[str, Any]:
        require_control_enabled()
        try:
            return outbound(service.reconcile(payload))
        except RuntimeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/cancel-only", dependencies=guarded)
    def cancel_only(payload: dict[str, Any]) -> dict[str, Any]:
        require_control_enabled()
        try:
            return outbound(service.cancel_only(payload))
        except RuntimeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/emergency-reduce-only-exit", dependencies=guarded)
    def emergency_reduce_only_exit(payload: dict[str, Any]) -> dict[str, Any]:
        require_control_enabled()
        if set(payload) != FRESH_STATE_EMERGENCY_EXIT_FIELDS:
            raise HTTPException(
                status_code=400,
                detail="okx_demo_fresh_state_operator_payload_fields_invalid",
            )
        try:
            return outbound(service.emergency_reduce_only_exit(payload))
        except RuntimeError as exc:
            status_code = (
                409
                if "already_attempted" in str(exc)
                else 400
            )
            raise HTTPException(status_code=status_code, detail=str(exc)) from exc

    return router
