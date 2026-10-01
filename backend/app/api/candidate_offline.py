"""Opaque-reference offline commands; no HTTP supplied market data or paths."""
import sqlite3
from urllib.parse import urlsplit
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import Field, StrictInt
from .candidate_delivery import CommandModel
from quant_shared.strategy_delivery.models import DeliveryError
from quant_shared.strategy_delivery.offline_contract import safety
from backend.app.core.candidate_local_auth import MODE, verify_local_request


class Start(CommandModel):
    registration_id: str = Field(pattern=r"^delivery_[0-9a-f]{32}$")
    content_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_revision: StrictInt = Field(ge=1)
    input_revision_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,159}$")
    input_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class Revision(CommandModel):
    expected_revision: StrictInt = Field(ge=1)


class Publish(CommandModel):
    source_revision_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,159}$")
    expected_revision: StrictInt = Field(ge=0)


def build_candidate_offline_router(service):
    router = APIRouter(prefix="/candidate-offline", tags=["candidate-offline"])

    def local(request: Request, host: str = Header(default="", alias="Host"), origin: str | None = Header(default=None, alias="Origin")):
        context = None
        if service is not None and service.auth_mode == MODE:
            context = verify_local_request(request)
        if context is None and urlsplit("//" + host).hostname not in {"localhost", "127.0.0.1", "::1", "testserver"}:
            raise HTTPException(403, "candidate_management_local_only")
        if context is None and origin is not None and origin not in {"http://127.0.0.1:3000", "http://localhost:3000"}:
            raise HTTPException(403, "candidate_management_origin_rejected")
        allowed = {"before"} if request.method == "GET" and request.url.path.endswith("/result") else set()
        if set(request.query_params) - allowed or any(len(request.query_params.getlist(k)) != 1 for k in request.query_params):
            raise HTTPException(422, "offline_query_fields_invalid")
        return context

    def invoke(call):
        if service is None: raise HTTPException(423, "candidate_offline_not_configured")
        try: return call()
        except DeliveryError as exc: raise HTTPException(exc.status, exc.code) from exc
        except sqlite3.Error as exc: raise HTTPException(503, "candidate_offline_store_unavailable") from exc
        except (OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
            raise HTTPException(409, "candidate_offline_evidence_invalid_or_unavailable") from exc

    def reader(key: str | None = Header(default=None, alias="X-API-Key"), context=Depends(local)):
        credential = context if context is not None else key
        invoke(lambda: service.authorize(credential, write=False))
        return credential

    def writer(key=Depends(reader)):
        invoke(lambda: service.authorize(key, write=True))
        return key

    @router.get("/capabilities")
    def capabilities(key: str | None = Header(default=None, alias="X-API-Key"), context=Depends(local)):
        if service is None:
            return {**safety(), "source_implemented": True, "deployed_configured": False,
                    "capability_enabled": False, "offline_commands_enabled": False,
                    "offline_start_allowed": False, "blockers": ["candidate_offline_not_configured"]}
        return service.capabilities(context if context is not None else key)

    @router.get("/catalog")
    def catalog(_=Depends(reader)):
        return invoke(lambda: {**service.inputs.list(), "publications": service.index.entries(), **safety()})

    @router.post("/publish")
    def publish(body: Publish, credential=Depends(writer), key: str = Header(alias="Idempotency-Key")):
        return invoke(lambda: service.index.publish(service.delivery, body.source_revision_id,
            expected_revision=body.expected_revision, key=key, actor=service.authorize(credential, write=True)))

    @router.get("/jobs")
    def jobs(_=Depends(reader)): return invoke(lambda: service.list())

    @router.get("/jobs/{identity}")
    def status(identity: str, _=Depends(reader)): return invoke(lambda: service.status(identity))

    @router.get("/jobs/{identity}/result")
    def result(identity: str, before: int = Query(default=2147483647, ge=1, le=2147483647), _=Depends(reader)):
        return invoke(lambda: service.result(identity, before=before))

    @router.post("/jobs", status_code=202)
    def start(body: Start, credential=Depends(writer), key: str = Header(alias="Idempotency-Key")):
        return invoke(lambda: service.start(body.model_dump(), key=key, credential=credential))

    @router.post("/jobs/{identity}/stop")
    def stop(identity: str, body: Revision, credential=Depends(writer), key: str = Header(alias="Idempotency-Key")):
        return invoke(lambda: service.command(identity, "stop", expected_revision=body.expected_revision, key=key, credential=credential))

    @router.post("/jobs/{identity}/resume", status_code=202)
    def resume(identity: str, body: Revision, credential=Depends(writer), key: str = Header(alias="Idempotency-Key")):
        return invoke(lambda: service.command(identity, "resume", expected_revision=body.expected_revision, key=key, credential=credential))

    return router
