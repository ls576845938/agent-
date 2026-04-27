from __future__ import annotations

import uuid
from datetime import datetime, timezone

from backend.app.core.exceptions import RunNotFoundError
from backend.app.domain.models import BacktestArtifacts, RunRecord


class RunRegistry:
    def __init__(self) -> None:
        self._runs: dict[str, RunRecord] = {}

    def create_completed_run(
        self,
        mode: str,
        request: dict,
        result: BacktestArtifacts,
    ) -> RunRecord:
        run_id = uuid.uuid4().hex
        now = datetime.now(tz=timezone.utc)
        record = RunRecord(
            run_id=run_id,
            mode=mode,
            request=request,
            status="completed",
            created_at=now,
            completed_at=now,
            result=result,
        )
        self._runs[run_id] = record
        return record

    def create_failed_run(self, mode: str, request: dict, error: str) -> RunRecord:
        run_id = uuid.uuid4().hex
        now = datetime.now(tz=timezone.utc)
        record = RunRecord(
            run_id=run_id,
            mode=mode,
            request=request,
            status="failed",
            created_at=now,
            completed_at=now,
            error=error,
        )
        self._runs[run_id] = record
        return record

    def get(self, run_id: str) -> RunRecord:
        if run_id not in self._runs:
            raise RunNotFoundError(f"Unknown run id: {run_id}")
        return self._runs[run_id]
