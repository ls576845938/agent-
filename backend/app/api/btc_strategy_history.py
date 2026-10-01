from __future__ import annotations

import hashlib
import inspect
import textwrap
from typing import Any, Callable

from backend.app.services.strategy_parameter_evidence import (
    ParameterEvidenceError,
    configured_history_reader,
    load_parameter_evidence,
)

from quant_crypto.application.btc_strategy_history import (
    BTCStrategyHistoryInvalid,
    BTCStrategyHistoryNotFound,
    BTCStrategyHistoryUnavailable,
    load_btc_strategy_history,
    load_btc_strategy_history_catalog,
)
from backend.app.services.strategy_workbench_versions import (
    StrategyWorkbenchVersionError,
    StrategyWorkbenchVersionStore,
)


def build_btc_strategy_history_router(
    artifact_reader: Any | None,
    *,
    version_store: StrategyWorkbenchVersionStore | None = None,
    backtest_runner: Callable[[dict[str, Any]], Any] | None = None,
    write_dependency: Callable[..., Any] | None = None,
):
    from fastapi import APIRouter, Depends, HTTPException

    if write_dependency is None:
        raise ValueError("strategy workbench write dependency is required")
    router = APIRouter(prefix="/research/btc")
    workbench_versions = version_store or StrategyWorkbenchVersionStore()
    write_dependencies = [Depends(write_dependency)]
    # Historical research has its own explicit root; it does not inherit the
    # current-HEAD promotion requirement or silently scan alternate directories.
    history_configuration_invalid = False
    try:
        artifact_reader = configured_history_reader(artifact_reader)
    except (OSError, RuntimeError, ValueError):
        artifact_reader = None
        history_configuration_invalid = True

    @router.get("/strategy-parameter-map/{strategy_id}")
    def get_parameter_map(strategy_id: str):
        if artifact_reader is None:
            raise HTTPException(status_code=503, detail="历史研究目录未配置或校验失败；请检查独立历史报告配置")
        try:
            return load_parameter_evidence(artifact_reader, strategy_id=strategy_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ParameterEvidenceError, ValueError) as exc:
            raise HTTPException(status_code=422, detail="参数报告校验失败") from exc
        except (OSError, RuntimeError) as exc:
            raise HTTPException(status_code=503, detail="参数网格尚未发布或不可读取") from exc

    @router.get("/strategy-history/catalog")
    def get_catalog():
        if artifact_reader is None:
            raise HTTPException(
                status_code=503,
                detail="BTC strategy history immutable artifact reader unavailable: history root invalid" if history_configuration_invalid else "BTC strategy history immutable artifact reader unavailable: history root not configured",
            )
        try:
            return load_btc_strategy_history_catalog(artifact_reader)
        except BTCStrategyHistoryNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except BTCStrategyHistoryInvalid as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except BTCStrategyHistoryUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @router.get("/strategy-history/{strategy_id}/{candidate_id}")
    def get_history(strategy_id: str, candidate_id: str, run_id: str = ""):
        if artifact_reader is None:
            raise HTTPException(
                status_code=503,
                detail="BTC strategy history immutable artifact reader unavailable: history root invalid" if history_configuration_invalid else "BTC strategy history immutable artifact reader unavailable: history root not configured",
            )
        try:
            return load_btc_strategy_history(
                artifact_reader,
                strategy_id=strategy_id,
                candidate_id=candidate_id,
                run_id=run_id,
            )
        except BTCStrategyHistoryNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except BTCStrategyHistoryInvalid as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except BTCStrategyHistoryUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    def canonical_strategy_source(strategy_id: str, candidate_id: str) -> dict[str, Any]:
        """Publish only source held by an exact canonical registry candidate.

        This intentionally does not accept a path, root, module, or symbol from
        the caller.  The two returned segments are allowlisted implementation
        objects already loaded by the current registry.
        """
        from quant_crypto.application.btc_strategy_registry import (
            BTCStrategyIdentityError,
            btc_strategy_registry,
        )
        from quant_crypto.research.long_short_trend_following_lab import (
            _signal_symmetric_donchian,
            raw_long_short_trend_signal,
        )

        try:
            spec = btc_strategy_registry.get(strategy_id, candidate_id)
        except BTCStrategyIdentityError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if not spec.canonical_signal_available or spec.signal_callable is None:
            raise HTTPException(
                status_code=409,
                detail="canonical strategy source is unavailable for identity-only candidate",
            )
        signal_type = str(spec.params.get("signal_type") or "")
        if signal_type != "symmetric_donchian":
            raise HTTPException(
                status_code=409,
                detail="canonical strategy source mapping is unavailable for this signal type",
            )
        try:
            signal_content = textwrap.dedent(inspect.getsource(spec.signal_callable)).strip()
            helper_content = textwrap.dedent(inspect.getsource(raw_long_short_trend_signal)).strip()
            donchian_content = textwrap.dedent(
                inspect.getsource(_signal_symmetric_donchian)
            ).strip()
        except (OSError, TypeError) as exc:
            raise HTTPException(
                status_code=409,
                detail="canonical strategy source is unavailable from the loaded callable",
            ) from exc
        if not signal_content or not helper_content or not donchian_content:
            raise HTTPException(
                status_code=409,
                detail="canonical strategy source is empty",
            )

        sections = [
            {
                "symbol": spec.signal_callable.__name__,
                "source_ref": "quant_crypto/application/btc_strategy_registry.py",
                "content": signal_content,
                "content_sha256": hashlib.sha256(signal_content.encode("utf-8")).hexdigest(),
            },
            {
                "symbol": "raw_long_short_trend_signal",
                "source_ref": "quant_crypto/research/long_short_trend_following_lab.py",
                "content": helper_content,
                "content_sha256": hashlib.sha256(helper_content.encode("utf-8")).hexdigest(),
            },
            {
                "symbol": "_signal_symmetric_donchian",
                "source_ref": "quant_crypto/research/long_short_trend_following_lab.py",
                "content": donchian_content,
                "content_sha256": hashlib.sha256(donchian_content.encode("utf-8")).hexdigest(),
            },
        ]
        content = "\n\n".join(item["content"] for item in sections)
        return {
            "schema_version": "btc_canonical_strategy_source_v1",
            "strategy_id": spec.strategy_id,
            "candidate_id": spec.candidate_id,
            "strategy_version": spec.strategy_version,
            "canonical_signal_available": True,
            "source_ref": sections[0]["source_ref"],
            "content_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
            "content": content,
            "sections": sections,
            "safety": {
                "paper": False,
                "live": False,
                "order": False,
                "private": False,
                "real_order": False,
            },
        }

    @router.get("/strategy-source/{strategy_id}/{candidate_id}")
    def get_strategy_source(strategy_id: str, candidate_id: str):
        return canonical_strategy_source(strategy_id, candidate_id)

    @router.get("/strategy-versions")
    def list_strategy_versions(strategy_id: str, candidate_id: str):
        try:
            return workbench_versions.list_versions(
                strategy_id=strategy_id,
                candidate_id=candidate_id,
            )
        except StrategyWorkbenchVersionError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/strategy-versions", dependencies=write_dependencies)
    def create_strategy_version(payload: dict[str, Any]):
        try:
            source = canonical_strategy_source(
                str(payload.get("strategy_id") or ""),
                str(payload.get("candidate_id") or ""),
            )
            return workbench_versions.create_version(
                payload=payload,
                canonical_source=source,
            )
        except HTTPException:
            raise
        except StrategyWorkbenchVersionError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.get("/strategy-versions/{version_id}")
    def get_strategy_version(version_id: str):
        try:
            return workbench_versions.get_version(version_id=version_id)
        except StrategyWorkbenchVersionError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.post("/strategy-versions/{version_id}/backtests", dependencies=write_dependencies)
    def run_strategy_version_backtest(version_id: str, payload: dict[str, Any]):
        try:
            version = workbench_versions.get_version(version_id=version_id)
            source = canonical_strategy_source(
                str(version.get("strategy_id") or ""),
                str(version.get("candidate_id") or ""),
            )
            if backtest_runner is None:
                raise StrategyWorkbenchVersionError("registered research backtest service is unavailable")
            return workbench_versions.run_backtest(
                version_id=version_id,
                payload=payload,
                canonical_source=source,
                runner=backtest_runner,
            )
        except HTTPException:
            raise
        except StrategyWorkbenchVersionError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/strategy-versions/{version_id}/approve", dependencies=write_dependencies)
    def approve_strategy_version(version_id: str, payload: dict[str, Any]):
        try:
            if set(payload) != {"confirmation"}:
                raise StrategyWorkbenchVersionError("approval request keys are not allowlisted")
            return workbench_versions.approve(
                version_id=version_id,
                confirmation=str(payload.get("confirmation") or ""),
            )
        except StrategyWorkbenchVersionError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/strategy-versions/{version_id}/select-runnable", dependencies=write_dependencies)
    def select_strategy_version(version_id: str, payload: dict[str, Any]):
        try:
            if set(payload) != {"confirmation"}:
                raise StrategyWorkbenchVersionError("selection request keys are not allowlisted")
            return workbench_versions.select_runnable_candidate(
                version_id=version_id,
                confirmation=str(payload.get("confirmation") or ""),
            )
        except StrategyWorkbenchVersionError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    return router
