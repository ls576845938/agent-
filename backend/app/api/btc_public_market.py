"""Explicitly reviewed public display reads, independent of Demo routes."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse

from backend.app.services.btc_public_market_stream import BtcPublicMarketStreamHub
from backend.app.services.btc_public_market_view import BTCPublicMarketViewService


def build_btc_public_market_router(
    *,
    service: BTCPublicMarketViewService,
    stream_service: BtcPublicMarketStreamHub,
    verify_api_key,
):
    router = APIRouter(prefix="/research/btc/public-market", dependencies=[Depends(verify_api_key)])

    def read(request: Request, response: Response, allowed_query: set[str], load):
        if set(request.query_params) - allowed_query:
            raise HTTPException(status_code=422, detail="okx_public_market_query_invalid")
        response.headers["Cache-Control"] = "no-store"
        try:
            return load()
        except RuntimeError as exc:
            # Never expose exception text, paths, proxies or upstream payloads.
            raise HTTPException(status_code=503, detail="okx_public_market_unavailable", headers={"Cache-Control": "no-store"}) from exc

    @router.get("/view")
    def view(request: Request, response: Response,
             timeframe: str = Query("1m", pattern=r"^(1m|5m|15m|1h|4h|1d|1w|1M)$"),
             limit: int = Query(300, ge=2, le=300)):
        return read(request, response, {"timeframe", "limit"}, lambda: service.view(timeframe=timeframe, limit=limit))

    @router.get("/ticker")
    def ticker(request: Request, response: Response):
        return read(request, response, set(), service.ticker)

    @router.get("/stream")
    def stream() -> StreamingResponse:
        """Local SSE bridge for public-only market display data.

        This route shares the same bounded, credential-free upstream hub as
        the Demo display route while remaining outside the Demo router. It
        never constructs runtime, private, order, risk, strategy, or ledger
        state, and it only becomes active while a browser is subscribed.
        """
        try:
            token = stream_service.subscribe()
            return StreamingResponse(
                stream_service.sse_events(token),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache, no-transform",
                    "X-Accel-Buffering": "no",
                },
            )
        except RuntimeError as exc:
            raise HTTPException(
                status_code=503,
                detail="okx_public_market_stream_unavailable",
                headers={"Cache-Control": "no-store"},
            ) from exc

    return router
