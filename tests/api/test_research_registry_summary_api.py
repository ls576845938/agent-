from __future__ import annotations

import ast
import asyncio
from pathlib import Path
import threading
import time

from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest


def test_registry_summary_view_is_explicit_and_full_view_stays_compatible(monkeypatch):
    source = Path("backend/app/api/app_factory.py").read_text(encoding="utf-8")
    frontend = Path("frontend/src/lib/research-api.ts").read_text(encoding="utf-8")

    assert 'view: str = "full"' in source
    assert "async def get_research_evidence_registry(" in source
    assert "request: Request" in source
    assert 'if view == "summary"' in source
    assert "asyncio.to_thread(" in source
    assert "_run_cancellable_registry_inspection(" in source
    assert "request.is_disconnected()" in source
    assert "cancel_event.set()" in source
    assert "should_cancel=cancel_event.is_set" in source
    assert "EvidenceRegistryInspectionCancelled" in source
    assert '"code": "research_evidence_read_cancelled"' in source
    assert "else inspect_saved_evidence_registry" in source
    assert '"code": "registry_view_invalid"' in source
    assert "view: 'summary'" in frontend


def test_registry_route_cancellation_retrieves_worker_exception() -> None:
    source_path = Path("backend/app/api/app_factory.py")
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(source_path))
    helper_node = next(
        node
        for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef)
        and node.name == "_run_cancellable_registry_inspection"
    )
    namespace: dict[str, object] = {}
    exec(
        compile(ast.Module(body=[helper_node], type_ignores=[]), str(source_path), "exec"),
        namespace,
    )
    helper = namespace["_run_cancellable_registry_inspection"]
    started = threading.Event()
    stopped = threading.Event()

    class ConnectedRequest:
        async def is_disconnected(self) -> bool:
            await asyncio.sleep(0)
            return False

    class InspectionCancelled(RuntimeError):
        pass

    def inspector(_data_root: str, *, should_cancel):
        started.set()
        while not should_cancel():
            time.sleep(0.001)
        stopped.set()
        raise InspectionCancelled("cancelled after route task")

    async def scenario() -> None:
        loop = asyncio.get_running_loop()
        unhandled: list[dict[str, object]] = []
        previous_handler = loop.get_exception_handler()
        loop.set_exception_handler(lambda _loop, context: unhandled.append(context))
        try:
            route_task = asyncio.create_task(
                helper(ConnectedRequest(), inspector, "data")
            )
            for _ in range(100):
                if started.is_set():
                    break
                await asyncio.sleep(0.001)
            assert started.is_set()
            route_task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await route_task
            await asyncio.sleep(0)
            assert stopped.is_set()
            assert not [
                context
                for context in unhandled
                if "Task exception was never retrieved" in str(context.get("message", ""))
            ]
        finally:
            loop.set_exception_handler(previous_handler)

    asyncio.run(scenario())


def test_registry_route_actual_read_and_fail_closed_statuses(
    tmp_path: Path,
) -> None:
    from backend.app.api import app_factory
    from quant_us.research.evidence_registry import rebuild_evidence_registry

    rebuild_evidence_registry(tmp_path)
    client = TestClient(app_factory.create_app())
    normal = client.get(
        "/api/research/evidence-registry",
        params={"data_root": str(tmp_path), "view": "summary"},
    )
    assert normal.status_code == 200
    assert normal.json()["response_view"] == "summary"
    assert normal.json()["registry_integrity_status"] == "PASS/STABLE"

    registry_path = tmp_path / "research" / "evidence_registry.json"
    registry_path.write_bytes(b"\xff")
    damaged = client.get(
        "/api/research/evidence-registry",
        params={"data_root": str(tmp_path), "view": "summary"},
    )
    assert damaged.status_code == 409
    assert damaged.json()["detail"]["code"] == "research_evidence_unreadable"
    assert damaged.json()["detail"]["promotion_eligible"] is False

    rebuild_rejected = client.get(
        "/api/research/evidence-registry",
        params={"data_root": str(tmp_path), "rebuild": "true", "view": "summary"},
    )
    assert rebuild_rejected.status_code == 405
    assert rebuild_rejected.json()["detail"]["code"] == "registry_rebuild_requires_post"

    invalid_view = client.get(
        "/api/research/evidence-registry",
        params={"data_root": str(tmp_path), "view": "partial"},
    )
    assert invalid_view.status_code == 400
    assert invalid_view.json()["detail"]["code"] == "registry_view_invalid"


def test_registry_actual_route_asgi_cancellation_is_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.app.api import app_factory
    import quant_us.research.evidence_registry as registry_module

    app = app_factory.create_app()
    candidate_routes = list(app.routes)
    for outer_route in app.routes:
        nested_app = getattr(outer_route, "app", None)
        if hasattr(nested_app, "routes"):
            candidate_routes.extend(nested_app.routes)
        included_router = getattr(outer_route, "original_router", None)
        if hasattr(included_router, "routes"):
            candidate_routes.extend(included_router.routes)
    endpoint = next(
        route.endpoint
        for route in candidate_routes
        if getattr(route, "path", "") == "/api/research/evidence-registry"
    )

    class ConnectedRequest:
        async def is_disconnected(self) -> bool:
            await asyncio.sleep(0)
            return False

    class DisconnectedRequest:
        async def is_disconnected(self) -> bool:
            return True

    def blocking_inspector(started: threading.Event, stopped: threading.Event):
        def inspect(_data_root: str, *, should_cancel):
            started.set()
            while not should_cancel():
                time.sleep(0.001)
            stopped.set()
            raise registry_module.EvidenceRegistryInspectionCancelled("cancelled")

        return inspect

    async def scenario() -> None:
        loop = asyncio.get_running_loop()
        unhandled: list[dict[str, object]] = []
        previous_handler = loop.get_exception_handler()
        loop.set_exception_handler(lambda _loop, context: unhandled.append(context))
        try:
            started = threading.Event()
            stopped = threading.Event()
            monkeypatch.setattr(
                registry_module,
                "inspect_saved_evidence_registry_summary",
                blocking_inspector(started, stopped),
            )
            route_task = asyncio.create_task(
                endpoint(
                    request=ConnectedRequest(),
                    data_root="fixture-only",
                    rebuild=False,
                    view="summary",
                )
            )
            for _ in range(100):
                if started.is_set():
                    break
                await asyncio.sleep(0.001)
            assert started.is_set()
            route_task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await route_task
            assert stopped.is_set()
            await asyncio.sleep(0)
            assert not [
                context
                for context in unhandled
                if "Task exception was never retrieved" in str(context.get("message", ""))
            ]

            disconnected_started = threading.Event()
            disconnected_stopped = threading.Event()
            monkeypatch.setattr(
                registry_module,
                "inspect_saved_evidence_registry_summary",
                blocking_inspector(disconnected_started, disconnected_stopped),
            )
            with pytest.raises(HTTPException) as exc_info:
                await endpoint(
                    request=DisconnectedRequest(),
                    data_root="fixture-only",
                    rebuild=False,
                    view="summary",
                )
            assert exc_info.value.status_code == 499
            assert exc_info.value.detail["code"] == "research_evidence_read_cancelled"
            assert exc_info.value.detail["promotion_eligible"] is False
            assert disconnected_stopped.is_set()
        finally:
            loop.set_exception_handler(previous_handler)

    asyncio.run(scenario())


def test_registry_full_asgi_stack_disconnect_cancels_worker_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.app.api import app_factory
    import quant_us.research.evidence_registry as registry_module

    started = threading.Event()
    stopped = threading.Event()

    def blocking_inspector(_data_root: str, *, should_cancel):
        started.set()
        while not should_cancel():
            time.sleep(0.001)
        stopped.set()
        raise registry_module.EvidenceRegistryInspectionCancelled("disconnected")

    monkeypatch.setattr(
        registry_module,
        "inspect_saved_evidence_registry_summary",
        blocking_inspector,
    )
    app = app_factory.create_app()

    async def scenario() -> None:
        receive_queue: asyncio.Queue[dict[str, object]] = asyncio.Queue()
        await receive_queue.put({"type": "http.request", "body": b"", "more_body": False})
        sent: list[dict[str, object]] = []

        async def receive() -> dict[str, object]:
            return await receive_queue.get()

        async def send(message: dict[str, object]) -> None:
            sent.append(message)

        scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/api/research/evidence-registry",
            "raw_path": b"/api/research/evidence-registry",
            "query_string": b"data_root=data&rebuild=false&view=summary",
            "root_path": "",
            "headers": [(b"host", b"testserver")],
            "client": ("127.0.0.1", 50000),
            "server": ("testserver", 80),
            "state": {},
        }
        request_task = asyncio.create_task(app(scope, receive, send))
        for _ in range(200):
            if started.is_set():
                break
            await asyncio.sleep(0.005)
        assert started.is_set()
        await receive_queue.put({"type": "http.disconnect"})
        await asyncio.wait_for(request_task, timeout=2.0)
        assert stopped.is_set()
        starts = [message for message in sent if message.get("type") == "http.response.start"]
        assert starts
        assert all(message.get("status") != 200 for message in starts)
        assert starts[-1].get("status") == 499

    asyncio.run(scenario())
