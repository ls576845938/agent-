from __future__ import annotations

import inspect
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _stable_strings(values: list[Any]) -> list[str]:
    return [str(value) for value in values if str(value).strip()]


@dataclass(slots=True)
class TaskContext:
    task_id: str
    _service: "TaskQueueService" = field(repr=False)

    def update(
        self,
        *,
        stage: str | None = None,
        message: str | None = None,
        progress: int | None = None,
    ) -> None:
        self._service.update(self.task_id, stage=stage, message=message, progress=progress)


@dataclass
class TaskRecord:
    task_id: str
    kind: str
    label: str
    request: dict[str, Any]
    status: str
    stage: str = ""
    progress: int = 0
    message: str = ""
    blockers: list[str] = field(default_factory=list)
    result: Any = None
    error: str | None = None
    created_at: datetime = field(default_factory=_now)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    updated_at: datetime = field(default_factory=_now)


class TaskQueueService:
    def __init__(self, max_workers: int = 4) -> None:
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="quant-task")
        self._tasks: dict[str, TaskRecord] = {}
        self._lock = threading.RLock()

    def submit(
        self,
        *,
        kind: str,
        label: str,
        request: dict[str, Any] | None = None,
        job: Callable[[TaskContext], Any],
    ) -> dict[str, Any]:
        task_id = uuid.uuid4().hex
        record = TaskRecord(
            task_id=task_id,
            kind=str(kind),
            label=str(label),
            request=dict(request or {}),
            status="queued",
            message="queued",
            progress=0,
        )
        with self._lock:
            self._tasks[task_id] = record

        def runner() -> None:
            self.update(task_id, status="running", stage="running", message=record.label, progress=5)
            context = TaskContext(task_id=task_id, _service=self)
            try:
                result = job(context)
                blockers = self._derive_blockers(result)
                self.finish(
                    task_id,
                    status="completed",
                    stage="completed",
                    message="completed",
                    progress=100,
                    result=result,
                    blockers=blockers,
                )
            except Exception as exc:  # pragma: no cover - exercised through API tests
                self.finish(
                    task_id,
                    status="failed",
                    stage="failed",
                    message="failed",
                    progress=100,
                    error=str(exc),
                    blockers=[str(exc)],
                )

        self._executor.submit(runner)
        return self.get(task_id)

    def update(
        self,
        task_id: str,
        *,
        status: str | None = None,
        stage: str | None = None,
        message: str | None = None,
        progress: int | None = None,
    ) -> None:
        with self._lock:
            record = self._tasks[task_id]
            if status is not None:
                record.status = str(status)
            if stage is not None:
                record.stage = str(stage)
            if message is not None:
                record.message = str(message)
            if progress is not None:
                record.progress = max(0, min(100, int(progress)))
            record.updated_at = _now()
            if record.started_at is None and record.status == "running":
                record.started_at = record.updated_at

    def finish(
        self,
        task_id: str,
        *,
        status: str,
        stage: str,
        message: str,
        progress: int,
        result: Any = None,
        error: str | None = None,
        blockers: list[str] | None = None,
    ) -> None:
        with self._lock:
            record = self._tasks[task_id]
            record.status = str(status)
            record.stage = str(stage)
            record.message = str(message)
            record.progress = max(0, min(100, int(progress)))
            record.result = result
            record.error = error
            record.blockers = _stable_strings(blockers or [])
            now = _now()
            record.completed_at = now
            if record.started_at is None:
                record.started_at = now
            record.updated_at = now

    def get(self, task_id: str) -> dict[str, Any]:
        with self._lock:
            if task_id not in self._tasks:
                raise KeyError(f"Unknown task id: {task_id}")
            return self._snapshot(self._tasks[task_id])

    def list(self, *, kind: str = "", limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            records = list(self._tasks.values())
        if kind:
            normalized = str(kind).strip()
            records = [record for record in records if record.kind == normalized]
        records.sort(key=lambda record: record.created_at, reverse=True)
        return [self._snapshot(record) for record in records[: max(1, min(int(limit), 100))]]

    def _snapshot(self, record: TaskRecord) -> dict[str, Any]:
        payload = asdict(record)
        payload["blockers"] = _stable_strings(payload.get("blockers") or [])
        return payload

    def _derive_blockers(self, result: Any) -> list[str]:
        if isinstance(result, dict):
            blockers: list[str] = []
            raw_blockers = result.get("blockers")
            if isinstance(raw_blockers, list):
                blockers.extend(_stable_strings(raw_blockers))
            if not blockers and isinstance(result.get("gates"), list):
                for gate in result["gates"]:
                    if not isinstance(gate, dict):
                        continue
                    if str(gate.get("status", "")).lower() != "pass":
                        name = str(gate.get("name") or "gate")
                        message = str(gate.get("message") or "")
                        blockers.append(f"{name}: {message}".strip())
            if not blockers and isinstance(result.get("promotion_gate"), dict):
                promotion_gate = result["promotion_gate"]
                for gate in promotion_gate.get("gates", []):
                    if not isinstance(gate, dict):
                        continue
                    if str(gate.get("status", "")).lower() != "pass":
                        name = str(gate.get("name") or "gate")
                        message = str(gate.get("message") or "")
                        blockers.append(f"{name}: {message}".strip())
            return _stable_strings(blockers)

        if result is None:
            return []
        if inspect.isawaitable(result):  # pragma: no cover - defensive guard
            return ["task returned awaitable result"]
        return []
