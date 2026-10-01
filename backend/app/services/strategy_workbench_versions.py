"""Append-only, research-only strategy-workbench version records.

The workbench deliberately never evaluates edited source.  A version can call
the existing registered crypto-event runner only when its immutable source is
byte-for-byte equal to the current allowlisted canonical source.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import uuid
from functools import wraps
from threading import Lock, RLock
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Mapping


VERSION_ID_PATTERN = re.compile(r"^swv_[0-9a-f]{24}$")
RUN_ID_PATTERN = re.compile(r"^swr_[0-9a-f]{24}$")
MAX_SOURCE_BYTES = 256_000
REQUIRED_REPORT_SUMMARY = {
    "total_return_pct",
    "annual_return_pct",
    "max_drawdown_pct",
    "sharpe_ratio",
    "trade_count",
}


class StrategyWorkbenchVersionError(ValueError):
    """Raised for a fail-closed version, backtest, approval, or selection request."""


def _serialized(method):
    """Serialize mutable journal operations for FastAPI's in-process thread pool."""
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        with self._writer_lock:
            return method(self, *args, **kwargs)
    return wrapped


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _safe_name(value: str, *, label: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,180}", value):
        raise StrategyWorkbenchVersionError(f"invalid {label}")
    return value


def _json_clone(value: Any) -> Any:
    try:
        return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))
    except (TypeError, ValueError) as exc:
        raise StrategyWorkbenchVersionError("backtest result is not JSON serializable") from exc


def default_strategy_workbench_version_root() -> Path:
    configured = os.environ.get("QS_STRATEGY_WORKBENCH_VERSION_ROOT", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
    base = Path(local_app_data) if local_app_data else Path(tempfile.gettempdir())
    return (base / "QuantStation" / "strategy-workbench-versions").resolve()


class StrategyWorkbenchVersionStore:
    """Small external append-only journal for local research versions.

    Version payloads, backtest outcomes, approvals and selections are separate
    immutable JSON objects.  Nothing in this store is a promotion artifact or
    an execution/runtime configuration.
    """

    _locks_guard = Lock()
    _locks: dict[str, RLock] = {}

    def __init__(self, root: Path | None = None) -> None:
        self.root = (root or default_strategy_workbench_version_root()).resolve()
        with self._locks_guard:
            self._writer_lock = self._locks.setdefault(str(self.root), RLock())

    @staticmethod
    def canonical_identity(source: Mapping[str, Any]) -> dict[str, str]:
        strategy_id = _safe_name(str(source.get("strategy_id") or ""), label="strategy_id")
        candidate_id = _safe_name(str(source.get("candidate_id") or ""), label="candidate_id")
        content = source.get("content")
        content_sha256 = str(source.get("content_sha256") or "")
        if not isinstance(content, str) or not content or _sha256(content) != content_sha256:
            raise StrategyWorkbenchVersionError("canonical source identity is invalid")
        return {
            "strategy_id": strategy_id,
            "candidate_id": candidate_id,
            "source_content": content,
            "source_sha256": content_sha256,
            "strategy_version": str(source.get("strategy_version") or ""),
        }

    def list_versions(self, *, strategy_id: str, candidate_id: str) -> dict[str, Any]:
        strategy_id = _safe_name(strategy_id, label="strategy_id")
        candidate_id = _safe_name(candidate_id, label="candidate_id")
        versions = [
            self._projection(version)
            for version in self._objects("versions")
            if version.get("strategy_id") == strategy_id and version.get("candidate_id") == candidate_id
        ]
        versions.sort(key=lambda item: str(item["created_at"]), reverse=True)
        selected = self._selection_for_candidate(strategy_id, candidate_id)
        return {
            "schema_version": "strategy_workbench_versions_v1",
            "strategy_id": strategy_id,
            "candidate_id": candidate_id,
            "versions": versions,
            "selected_version_id": str(selected.get("version_id") or "") if selected else "",
            "safety": self._safety(),
        }

    def get_version(self, *, version_id: str) -> dict[str, Any]:
        """Return the public derived projection for an immutable version."""
        return self._projection(self._version(version_id))

    @_serialized
    def create_version(self, *, payload: Mapping[str, Any], canonical_source: Mapping[str, Any]) -> dict[str, Any]:
        canonical = self.canonical_identity(canonical_source)
        self._require_exact_keys(payload, {"strategy_id", "candidate_id", "base_source_sha256", "source_content", "label"})
        if str(payload.get("strategy_id") or "") != canonical["strategy_id"] or str(payload.get("candidate_id") or "") != canonical["candidate_id"]:
            raise StrategyWorkbenchVersionError("version identity does not match canonical source")
        if str(payload.get("base_source_sha256") or "") != canonical["source_sha256"]:
            raise StrategyWorkbenchVersionError("version base source hash does not match current canonical source")
        source_content = payload.get("source_content")
        if not isinstance(source_content, str) or not source_content.strip():
            raise StrategyWorkbenchVersionError("version source content is required")
        if len(source_content.encode("utf-8")) > MAX_SOURCE_BYTES:
            raise StrategyWorkbenchVersionError("version source content exceeds research draft limit")
        label = str(payload.get("label") or "").strip()[:120]
        version_id = "swv_" + uuid.uuid4().hex[:24]
        executable = source_content == canonical["source_content"]
        version = {
            "schema_version": "strategy_workbench_version_v1",
            "kind": "immutable_research_version",
            "version_id": version_id,
            "created_at": _now(),
            "strategy_id": canonical["strategy_id"],
            "candidate_id": canonical["candidate_id"],
            "strategy_version": canonical["strategy_version"],
            "label": label or "本机研究版本",
            "base_source_sha256": canonical["source_sha256"],
            "source_sha256": _sha256(source_content),
            "source_content": source_content,
            "execution": {
                "canonical_source_match": executable,
                "allowlisted_runner_only": True,
                "arbitrary_python_execution": False,
                "runnable": executable,
                "blocker": "" if executable else "edited_source_not_registered_for_execution",
            },
            "safety": self._safety(),
        }
        self._write("versions", version_id, version)
        return self._projection(version)

    @_serialized
    def run_backtest(
        self,
        *,
        version_id: str,
        payload: Mapping[str, Any],
        canonical_source: Mapping[str, Any],
        runner: Callable[[dict[str, Any]], Any],
    ) -> dict[str, Any]:
        version = self._version(version_id)
        canonical = self.canonical_identity(canonical_source)
        self._verify_current_execution_identity(version, canonical)
        self._require_exact_keys(payload, {"start", "end", "capital", "data_version"})
        start = self._utc_text(payload.get("start"), label="start")
        end = self._utc_text(payload.get("end"), label="end")
        if start >= end:
            raise StrategyWorkbenchVersionError("backtest end must be after start")
        capital = payload.get("capital")
        if not isinstance(capital, (int, float)) or isinstance(capital, bool) or not 1 <= float(capital) <= 10_000_000:
            raise StrategyWorkbenchVersionError("backtest capital is outside safe bounds")
        data_version = str(payload.get("data_version") or "").strip()[:160]
        run_id = "swr_" + uuid.uuid4().hex[:24]
        request = {
            "strategy_id": version["strategy_id"],
            "candidate_id": version["candidate_id"],
            "strategy_version": version["strategy_version"],
            "strategy_params": {},
            "source": "sqlite",
            "symbol": "BTCUSDT",
            "interval": "1h",
            "start": start,
            "end": end,
            "capital": float(capital),
            "data_version": data_version,
            "leverage": 1.0,
            "run_id": run_id,
            "manifest_root": str(self.root / "research-backtests"),
        }
        try:
            result = runner(request)
        except Exception as exc:
            run = self._run_record(version, run_id, request, status="failed", error=str(exc), report=None)
            self._write("runs", run_id, run)
            return self._run_projection(run)
        report = self._report_projection(result)
        run = self._run_record(version, run_id, request, status="completed", error="", report=report)
        self._write("runs", run_id, run)
        return self._run_projection(run)

    @_serialized
    def approve(self, *, version_id: str, confirmation: str) -> dict[str, Any]:
        version = self._version(version_id)
        if confirmation != "APPROVE RESEARCH VERSION":
            raise StrategyWorkbenchVersionError("research version approval confirmation is required")
        runs = [item for item in self._objects("runs") if item.get("version_id") == version_id and item.get("status") == "completed"]
        if not runs:
            raise StrategyWorkbenchVersionError("completed allowlisted backtest is required before approval")
        run = max(runs, key=lambda item: str(item.get("completed_at") or ""))
        if not self._has_basic_backtest_contract(run.get("report")):
            raise StrategyWorkbenchVersionError("completed backtest does not meet the basic report contract")
        event_id = "swa_" + uuid.uuid4().hex[:24]
        event = {
            "schema_version": "strategy_workbench_version_approval_v1",
            "kind": "research_version_approval",
            "event_id": event_id,
            "created_at": _now(),
            "version_id": version_id,
            "strategy_id": version["strategy_id"],
            "candidate_id": version["candidate_id"],
            "backtest_run_id": run["run_id"],
            "approved": True,
            "decision": "approved_research_only",
            "safety": self._safety(),
        }
        self._write("approvals", event_id, event)
        return self._projection(version)

    @_serialized
    def select_runnable_candidate(self, *, version_id: str, confirmation: str) -> dict[str, Any]:
        version = self._version(version_id)
        if confirmation != "SELECT RUNNABLE CANDIDATE":
            raise StrategyWorkbenchVersionError("runnable candidate selection confirmation is required")
        if not self._approval(version_id):
            raise StrategyWorkbenchVersionError("approved research version is required before selection")
        event_id = "sws_" + uuid.uuid4().hex[:24]
        event = {
            "schema_version": "strategy_workbench_candidate_selection_v1",
            "kind": "research_only_runnable_candidate_selection",
            "event_id": event_id,
            "created_at": _now(),
            "version_id": version_id,
            "strategy_id": version["strategy_id"],
            "candidate_id": version["candidate_id"],
            "selection_scope": "future_demo_reader_requires_separate_runtime_admission",
            "demo_start_requested": False,
            "safety": self._safety(),
        }
        self._write("selections", event_id, event)
        return self._projection(version)

    def _version(self, version_id: str) -> dict[str, Any]:
        if not VERSION_ID_PATTERN.fullmatch(version_id):
            raise StrategyWorkbenchVersionError("invalid strategy workbench version id")
        path = self.root / "versions" / f"{version_id}.json"
        if not path.is_file():
            raise StrategyWorkbenchVersionError("strategy workbench version was not found")
        record = self._read(path)
        if record.get("schema_version") != "strategy_workbench_version_v1" or record.get("version_id") != version_id:
            raise StrategyWorkbenchVersionError("strategy workbench version record is invalid")
        if _sha256(str(record.get("source_content") or "")) != record.get("source_sha256"):
            raise StrategyWorkbenchVersionError("strategy workbench version source hash mismatch")
        return record

    def _projection(self, version: Mapping[str, Any]) -> dict[str, Any]:
        version_id = str(version["version_id"])
        latest_run = self._latest_run(version_id)
        approval = self._approval(version_id)
        selection = self._selection_for_candidate(str(version["strategy_id"]), str(version["candidate_id"]))
        selected_here = selection is not None and selection.get("version_id") == version_id
        return {
            "version_id": version_id,
            "created_at": str(version["created_at"]),
            "strategy_id": str(version["strategy_id"]),
            "candidate_id": str(version["candidate_id"]),
            "strategy_version": str(version.get("strategy_version") or ""),
            "label": str(version.get("label") or ""),
            "base_source_sha256": str(version["base_source_sha256"]),
            "source_sha256": str(version["source_sha256"]),
            "source_content": str(version["source_content"]),
            "execution": _json_clone(version["execution"]),
            "latest_backtest": self._run_projection(latest_run) if latest_run else None,
            "approved_research_only": approval is not None,
            "selected_runnable_candidate": selected_here,
            "selection_scope": str(selection.get("selection_scope") or "") if selected_here else "",
            "safety": self._safety(),
        }

    def _latest_run(self, version_id: str) -> dict[str, Any] | None:
        runs = [item for item in self._objects("runs") if item.get("version_id") == version_id]
        return max(runs, key=lambda item: str(item.get("completed_at") or item.get("created_at") or "")) if runs else None

    def _approval(self, version_id: str) -> dict[str, Any] | None:
        approvals = [item for item in self._objects("approvals") if item.get("version_id") == version_id and item.get("approved") is True]
        return max(approvals, key=lambda item: str(item.get("created_at") or "")) if approvals else None

    def _selection_for_candidate(self, strategy_id: str, candidate_id: str) -> dict[str, Any] | None:
        """Return the latest append-only selection for one canonical candidate.

        Selection deliberately has no mutable pointer.  This keeps each state
        transition durable and means a thread-pool writer cannot expose a
        partially replaced "selected" file.  Older versions therefore derive
        false once a later immutable selection event chooses another version.
        """
        selections = [
            item
            for item in self._objects("selections")
            if item.get("strategy_id") == strategy_id and item.get("candidate_id") == candidate_id
        ]
        return max(selections, key=lambda item: str(item.get("created_at") or "")) if selections else None

    def _verify_current_execution_identity(self, version: Mapping[str, Any], canonical: Mapping[str, str]) -> None:
        if version.get("strategy_id") != canonical["strategy_id"] or version.get("candidate_id") != canonical["candidate_id"]:
            raise StrategyWorkbenchVersionError("version identity no longer matches canonical candidate")
        if version.get("base_source_sha256") != canonical["source_sha256"]:
            raise StrategyWorkbenchVersionError("current canonical source changed after version creation")
        if version.get("source_sha256") != canonical["source_sha256"] or version.get("source_content") != canonical["source_content"]:
            raise StrategyWorkbenchVersionError("edited source is not registered for allowlisted backtest execution")
        if not isinstance(version.get("execution"), Mapping) or version["execution"].get("runnable") is not True:
            raise StrategyWorkbenchVersionError("version is not runnable through the allowlisted backtest")

    def _run_record(self, version: Mapping[str, Any], run_id: str, request: Mapping[str, Any], *, status: str, error: str, report: dict[str, Any] | None) -> dict[str, Any]:
        return {
            "schema_version": "strategy_workbench_backtest_run_v1",
            "kind": "allowlisted_registered_strategy_backtest",
            "run_id": run_id,
            "version_id": version["version_id"],
            "strategy_id": version["strategy_id"],
            "candidate_id": version["candidate_id"],
            "created_at": _now(),
            "completed_at": _now(),
            "status": status,
            "request": _json_clone({key: request[key] for key in ("start", "end", "capital", "data_version", "strategy_id", "candidate_id", "strategy_version", "run_id")}),
            "report": report,
            "error": error[:500],
            "safety": self._safety(),
        }

    @staticmethod
    def _report_projection(result: Any) -> dict[str, Any]:
        source = result if isinstance(result, Mapping) else {
            "summary": getattr(result, "summary", None),
            "chart": getattr(result, "chart", None),
            "strategy_details": getattr(result, "strategy_details", None),
            "diagnostics": getattr(result, "diagnostics", None),
        }
        summary = source.get("summary") if isinstance(source, Mapping) else None
        chart = source.get("chart") if isinstance(source, Mapping) else None
        if not isinstance(summary, Mapping) or not isinstance(chart, Mapping):
            raise StrategyWorkbenchVersionError("allowlisted backtest did not return a report")
        return _json_clone({
            "summary": dict(summary),
            "chart": dict(chart),
            "strategy_details": list(source.get("strategy_details") or []),
            # The event-driven runner already records ledger/equity/cost and
            # research-boundary evidence in diagnostics.  Keep that evidence
            # in the immutable run projection; dropping it here made a
            # completed run look like an empty summary-only report.
            "diagnostics": dict(source.get("diagnostics") or {}),
            "report_scope": "research_only_registered_strategy_replay",
        })

    @staticmethod
    def _run_projection(run: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "run_id": str(run["run_id"]),
            "created_at": str(run["created_at"]),
            "completed_at": str(run["completed_at"]),
            "status": str(run["status"]),
            "request": _json_clone(run["request"]),
            "report": _json_clone(run["report"]) if run.get("report") else None,
            "error": str(run.get("error") or ""),
            "safety": StrategyWorkbenchVersionStore._safety(),
        }

    @staticmethod
    def _has_basic_backtest_contract(report: Any) -> bool:
        if not isinstance(report, Mapping):
            return False
        summary = report.get("summary")
        chart = report.get("chart")
        return isinstance(summary, Mapping) and REQUIRED_REPORT_SUMMARY.issubset(summary) and isinstance(chart, Mapping) and isinstance(chart.get("equity"), list) and isinstance(chart.get("drawdown"), list)

    @staticmethod
    def _utc_text(value: Any, *, label: str) -> str:
        if not isinstance(value, str) or not value:
            raise StrategyWorkbenchVersionError(f"backtest {label} is required")
        normalized = value.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError as exc:
            raise StrategyWorkbenchVersionError(f"backtest {label} must be ISO-8601") from exc
        if parsed.tzinfo is None:
            raise StrategyWorkbenchVersionError(f"backtest {label} must include timezone")
        return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")

    @staticmethod
    def _require_exact_keys(payload: Mapping[str, Any], keys: set[str]) -> None:
        if set(payload) != keys:
            raise StrategyWorkbenchVersionError("request keys are not allowlisted")

    @staticmethod
    def _safety() -> dict[str, bool]:
        return {"paper": False, "live": False, "order": False, "private": False, "real_order": False, "transfer": False, "withdraw": False, "demo_start": False}

    def _objects(self, category: str) -> list[dict[str, Any]]:
        directory = self.root / category
        if not directory.is_dir():
            return []
        records: list[dict[str, Any]] = []
        for path in sorted(directory.glob("*.json")):
            try:
                records.append(self._read(path))
            except StrategyWorkbenchVersionError:
                continue
        return records

    @staticmethod
    def _read(path: Path) -> dict[str, Any]:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise StrategyWorkbenchVersionError("strategy workbench record is unreadable") from exc
        if not isinstance(value, dict):
            raise StrategyWorkbenchVersionError("strategy workbench record is invalid")
        return value

    def _write(self, category: str, object_id: str, payload: Mapping[str, Any]) -> None:
        if category == "versions" and not VERSION_ID_PATTERN.fullmatch(object_id):
            raise StrategyWorkbenchVersionError("invalid immutable version id")
        if category == "runs" and not RUN_ID_PATTERN.fullmatch(object_id):
            raise StrategyWorkbenchVersionError("invalid immutable run id")
        directory = self.root / category
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / f"{object_id}.json"
        if target.exists():
            raise StrategyWorkbenchVersionError("immutable strategy workbench record already exists")
        temporary = directory / f".{object_id}.{uuid.uuid4().hex}.tmp"
        try:
            temporary.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")), encoding="utf-8")
            with temporary.open("r+", encoding="utf-8") as handle:
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
        finally:
            if temporary.exists():
                temporary.unlink(missing_ok=True)
