"""Explicit local candidate-management commands, separate from Demo controls."""
from __future__ import annotations

import secrets
import sqlite3
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from backend.app.core.candidate_local_auth import MODE, verify_local_request, is_local_context
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from quant_shared.strategy_delivery.models import DeliveryError, identifier, permissions

PREFIX = "/strategy-delivery"


class CommandModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Source(CommandModel):
    kind: str = Field(max_length=30)
    run_id: str = Field(max_length=160)
    candidate_id: str = Field(max_length=160)


class Create(CommandModel):
    source: Source
    target: str = Field(max_length=20)


class Revision(CommandModel):
    expected_revision: StrictInt = Field(ge=1)


class Bind(Revision):
    account_ref: str = Field(max_length=160)


class Review(Revision):
    decision: str = Field(max_length=10)
    reason: str = Field(min_length=1, max_length=500)


class Revoke(Revision):
    reason: str = Field(min_length=1, max_length=500)


def build_candidate_delivery_router(*, service, enabled=False, operator="", management_key="", auth_mode="key", profile="candidate_management"):
    """Key is the local Web management key, NEVER an exchange credential.

    No secrets enter records, responses, request bodies or log messages. A
    configured local operator is the principal; browser reviewer names ignored.
    """
    router = APIRouter(prefix=PREFIX, tags=["candidate-delivery"])
    try: identifier(operator)
    except DeliveryError: operator = ""
    local_mode = auth_mode == MODE and profile == "candidate_management"
    available = bool(enabled and service is not None and operator and
                     (local_mode or (auth_mode == "key" and management_key)))

    def local(request: Request, host: str = Header(default="", alias="Host"), origin: str | None = Header(default=None, alias="Origin")):
        if local_mode:
            return verify_local_request(request)
        if urlsplit("//" + host).hostname not in {"127.0.0.1", "localhost", "::1", "testserver"}:
            raise HTTPException(403, "candidate_management_local_only")
        if origin is not None and origin not in {"http://127.0.0.1:3000", "http://localhost:3000"}:
            raise HTTPException(403, "candidate_management_origin_rejected")

    def authorized(key: str | None, context=None):
        if local_mode:
            return available and is_local_context(context)
        return bool(available and key and len(key) <= 1024 and secrets.compare_digest(key.encode(), management_key.encode()))

    def actor(key: str | None = Header(default=None, alias="X-API-Key"), context=Depends(local)):
        if not available: raise HTTPException(423, "candidate_management_not_enabled_or_configured")
        if not authorized(key, context): raise HTTPException(403, "candidate_management_authentication_required")
        return operator

    def invoke(call):
        try: return call()
        except DeliveryError as exc: raise HTTPException(exc.status, exc.code) from exc
        except sqlite3.Error as exc: raise HTTPException(503, "candidate_management_store_unavailable") from exc
        except (OSError, ValueError, RuntimeError) as exc: raise HTTPException(409, "candidate_source_validation_unavailable") from exc

    @router.get("/capabilities")
    def capabilities(key: str | None = Header(default=None, alias="X-API-Key"), context=Depends(local)):
        return {"schema_version": "strategy_delivery_capabilities_v1", "management_configured": available,
                "auth_mode": auth_mode,
                "authenticated": authorized(key, context), "commands_enabled": authorized(key, context),
                "operator": operator if authorized(key, context) else None,
                "permissions": permissions(), "scope": "candidate_records_only_no_start"}

    @router.get("/accounts")
    def accounts(_=Depends(actor)):
        return invoke(lambda: {"accounts": service.accounts.list(), "permissions": permissions()})

    @router.get("/packages")
    def packages(_=Depends(actor)):
        return invoke(lambda: {"records": service.list(), "permissions": permissions()})

    @router.get("/packages/{identity}")
    def get(identity: str, _=Depends(actor)):
        return invoke(lambda: service.get(identity))

    @router.get("/catalog")
    def catalog(_=Depends(actor)):
        return invoke(lambda: {"records": [row for row in service.list() if row["status"] == "registered"],
                               "snapshot_only": True, "start_allowed": False, "permissions": permissions()})

    @router.get("/requests/{request_key}")
    def request_result(request_key: str, principal=Depends(actor)):
        return invoke(lambda: service.store.request_result(identifier(request_key), principal))

    @router.post("/packages")
    def create(body: Create, principal=Depends(actor), key: str = Header(alias="Idempotency-Key")):
        return invoke(lambda: service.create(body.source.model_dump(), body.target, key=key, actor=principal))

    def command(identity, action, body, principal, key):
        payload = body.model_dump()
        revision = payload.pop("expected_revision")
        return invoke(lambda: service.command(identity, action, expected_revision=revision, key=key, actor=principal, **payload))

    @router.post("/packages/{identity}/bind")
    def bind(identity: str, body: Bind, principal=Depends(actor), key: str = Header(alias="Idempotency-Key")):
        return command(identity, "bind", body, principal, key)

    @router.post("/packages/{identity}/review")
    def review(identity: str, body: Review, principal=Depends(actor), key: str = Header(alias="Idempotency-Key")):
        return command(identity, "review", body, principal, key)

    @router.post("/packages/{identity}/register")
    def register(identity: str, body: Revision, principal=Depends(actor), key: str = Header(alias="Idempotency-Key")):
        return command(identity, "register", body, principal, key)

    @router.post("/packages/{identity}/revoke")
    def revoke(identity: str, body: Revoke, principal=Depends(actor), key: str = Header(alias="Idempotency-Key")):
        return command(identity, "revoke", body, principal, key)

    return router
