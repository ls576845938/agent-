from __future__ import annotations

from typing import Any, Callable, Mapping, Protocol


class DemoRuntimeControllerPort(Protocol):
    def status(self) -> dict[str, Any]: ...

    def start(self, payload: Mapping[str, Any]) -> dict[str, Any]: ...

    def stop(self, payload: Mapping[str, Any]) -> dict[str, Any]: ...

    def reconcile(self, payload: Mapping[str, Any]) -> dict[str, Any]: ...

    def enter_cancel_only(self, payload: Mapping[str, Any]) -> dict[str, Any]: ...


NativeDemoDataInspector = Callable[[], dict[str, Any]]
ReadonlyChartLoader = Callable[[int], dict[str, Any]]
