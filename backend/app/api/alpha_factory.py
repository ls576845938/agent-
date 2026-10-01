from fastapi import APIRouter, Depends, HTTPException, Request

from quant_shared.alpha_factory.contracts import FactoryError, SAFETY
from backend.app.services.research_archive_discovery import (
    ResearchArchiveConflict,
    ResearchArchiveUnavailable,
)


def build_alpha_factory_router(*, service, verify_api_key):
    router = APIRouter(dependencies=[Depends(verify_api_key)])
    forbidden_archive_selectors = {
        "manifest",
        "manifest_git_spec",
        "path",
        "ref",
        "root",
        "shared_root",
    }

    def reject_archive_selectors(request: Request) -> None:
        if forbidden_archive_selectors.intersection(request.query_params):
            raise HTTPException(400, "readonly_archive_selector_is_server_owned")

    @router.get("/research/alpha-factory")
    def overview(request: Request, limit: int = 20):
        reject_archive_selectors(request)
        try:
            return {**service.profiles(), "runs": service.list_runs(limit), **SAFETY}
        except ResearchArchiveConflict as exc:
            raise HTTPException(409, str(exc)) from exc
        except ResearchArchiveUnavailable as exc:
            raise HTTPException(503, str(exc)) from exc

    @router.get("/research/alpha-factory/runs/{run_id}")
    def detail(run_id: str, request: Request):
        reject_archive_selectors(request)
        try: return service.get(run_id)
        except FileNotFoundError as exc: raise HTTPException(404, "factory_run_not_found") from exc
        except ResearchArchiveConflict as exc: raise HTTPException(409, str(exc)) from exc
        except ResearchArchiveUnavailable as exc: raise HTTPException(503, str(exc)) from exc
        except FactoryError as exc: raise HTTPException(400, str(exc)) from exc

    @router.post("/tasks/research/alpha-factory")
    def submit(request: dict):
        try: return service.submit(request)
        except FactoryError as exc: raise HTTPException(400, str(exc)) from exc

    @router.post("/tasks/research/alpha-factory/{run_id}/resume")
    def resume(run_id: str, request: dict):
        if request: raise HTTPException(400, "resume_does_not_accept_overrides")
        try: return service.resume(run_id)
        except FileNotFoundError as exc: raise HTTPException(404, "factory_run_not_found") from exc
        except FactoryError as exc: raise HTTPException(400, str(exc)) from exc

    return router
