from __future__ import annotations

import hashlib
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any


SCHEMA_VERSION = "strategy_history_catalog_v1"
_GIT_PREFIXES = {
    "experiments": "data/research/experiments",
    "candidates": "data/research/candidates",
    "manifests": "data/research/manifests",
}
_TERMINAL_RESEARCH_STATUSES = {
    "COMPLETED",
    "PROMOTED",
    "PROMOTED_TO_CANDIDATE",
}
_METRIC_KEYS = (
    "total_return_pct",
    "cagr_pct",
    "annual_return_pct",
    "annual_volatility_pct",
    "sharpe_ratio",
    "sortino_ratio",
    "max_drawdown_pct",
    "calmar_ratio",
    "win_rate_pct",
    "profit_factor",
    "turnover_pct",
    "trade_count",
    "engine",
)
_MAX_FILES_PER_SOURCE = 256
_MAX_JSON_BYTES = 1_048_576
_GIT_TIMEOUT_SECONDS = 10
_RUN_MANIFEST_RE = re.compile(r"^data/manifests/run_([A-Za-z0-9_.-]+)\.json$")
_CANDIDATE_RUN_MANIFEST_RE = re.compile(
    r"^data/research/backtests/[A-Za-z0-9_.-]+/run_manifest\.json$"
)


class StrategyHistorySourceUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class _JsonObject:
    path: str
    payload: dict[str, Any]
    sha256: str


def _code_repository_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _run_git(repo_root: Path, args: list[str], *, binary: bool = False) -> bytes | str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(repo_root), *args],
            check=True,
            capture_output=True,
            text=not binary,
            timeout=_GIT_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise StrategyHistorySourceUnavailable("git_command_failed") from exc
    return completed.stdout


def _registered_main() -> tuple[Path, str]:
    code_root = _code_repository_root()
    raw = bytes(
        _run_git(
            code_root,
            ["-c", "core.quotePath=false", "worktree", "list", "--porcelain"],
            binary=True,
        )
    ).decode("utf-8")
    blocks = [block for block in raw.split("\n\n") if block.strip()]
    for block in blocks:
        fields: dict[str, str] = {}
        for line in block.splitlines():
            key, _, value = line.partition(" ")
            fields[key] = value
        if fields.get("branch") != "refs/heads/main":
            continue
        root_text = fields.get("worktree", "")
        if not root_text:
            continue
        root = Path(root_text).resolve()
        head = fields.get("HEAD", "").strip().lower()
        main_head = str(
            _run_git(code_root, ["rev-parse", "refs/heads/main"])
        ).strip().lower()
        if not re.fullmatch(r"[0-9a-f]{40}", head) or head != main_head:
            raise StrategyHistorySourceUnavailable("registered_main_identity_mismatch")
        return root, head
    raise StrategyHistorySourceUnavailable("registered_main_worktree_not_found")


def _is_safe_repo_path(value: Any) -> bool:
    if not isinstance(value, str) or not value or "\\" in value:
        return False
    path = PurePosixPath(value)
    return not path.is_absolute() and ".." not in path.parts and "." not in path.parts


def _valid_evidence_paths(experiment: dict[str, Any]) -> bool:
    experiment_id = str(experiment.get("experiment_id", ""))
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", experiment_id):
        return False
    result_path = experiment.get("run_result_path")
    manifest_path = experiment.get("backtest_manifest_path")
    if not _is_safe_repo_path(result_path) or not _is_safe_repo_path(manifest_path):
        return False
    if result_path != f"data/research/experiments/{experiment_id}/run_result.json":
        return False
    return bool(
        _RUN_MANIFEST_RE.fullmatch(str(manifest_path))
        or _CANDIDATE_RUN_MANIFEST_RE.fullmatch(str(manifest_path))
    )


def _run_id(backtest_manifest_path: str) -> str:
    match = _RUN_MANIFEST_RE.fullmatch(backtest_manifest_path)
    if match:
        return match.group(1)
    if _CANDIDATE_RUN_MANIFEST_RE.fullmatch(backtest_manifest_path):
        return PurePosixPath(backtest_manifest_path).parent.name
    return ""


def _safe_metrics(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {
        key: value[key]
        for key in _METRIC_KEYS
        if key in value and isinstance(value[key], (str, int, float, bool))
    }


def _params_hash(experiment: dict[str, Any], candidate: dict[str, Any]) -> str:
    candidate_hash = candidate.get("params_hash")
    if isinstance(candidate_hash, str) and candidate_hash:
        return candidate_hash
    params = experiment.get("params")
    if not isinstance(params, dict):
        params = {}
    canonical = json.dumps(params, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _promotion_status(candidate: dict[str, Any], manifest: dict[str, Any]) -> str:
    for key in ("promotion_gate_decision", "promotion_status"):
        value = manifest.get(key)
        if isinstance(value, str) and value:
            return value.lower()
    value = candidate.get("promotion_status")
    if isinstance(value, str) and value:
        return value.lower()
    return "research_only"


def _record(
    experiment_object: _JsonObject,
    *,
    candidate: dict[str, Any],
    strategy_manifest: dict[str, Any],
    source: str,
    head: str,
) -> dict[str, Any] | None:
    experiment = experiment_object.payload
    status = str(experiment.get("status", "")).upper()
    metrics = _safe_metrics(experiment.get("metrics"))
    if status not in _TERMINAL_RESEARCH_STATUSES or not metrics:
        return None
    if not _valid_evidence_paths(experiment):
        return None
    run_id = _run_id(str(experiment["backtest_manifest_path"]))
    if not run_id:
        return None
    experiment_id = str(experiment["experiment_id"])
    strategy_id = str(experiment.get("strategy_id", ""))
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", strategy_id):
        return None
    candidate_id = str(candidate.get("candidate_id", ""))
    if candidate_id and not re.fullmatch(r"[A-Za-z0-9_.-]+", candidate_id):
        candidate_id = ""
    family = str(experiment.get("strategy_family", "") or strategy_id)
    freshness_state = "current_head" if source == "tracked_git_object" else "runtime_uncommitted"
    return {
        "catalog_key": f"us_equity:{run_id}",
        "source": source,
        "domain": "us_equity",
        "record_kind": "research_run",
        "strategy_id": strategy_id,
        "candidate_id": candidate_id,
        "experiment_id": experiment_id,
        "run_id": run_id,
        "params_hash": _params_hash(experiment, candidate),
        "display_name": family,
        "system_category": "us_equity_research",
        "metrics": metrics,
        "research_status": status.lower(),
        "promotion_status": _promotion_status(candidate, strategy_manifest),
        "backtest_supported": True,
        "paper_allowed": False,
        "live_allowed": False,
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "real_order_submitted": False,
        "report_href": "",
        "artifact_path": experiment_object.path,
        "artifact_sha256": experiment_object.sha256,
        "freshness": {
            "status": freshness_state,
            "source": source,
            "head": head,
        },
    }


def _expected_git_path(prefix: str, path: str, filename: str) -> bool:
    prefix_parts = PurePosixPath(prefix).parts
    parts = PurePosixPath(path).parts
    return (
        len(parts) == len(prefix_parts) + 2
        and parts[: len(prefix_parts)] == prefix_parts
        and parts[-1] == filename
        and bool(re.fullmatch(r"[A-Za-z0-9_.-]+", parts[-2]))
    )


def _git_objects(main_root: Path, head: str, kind: str) -> list[_JsonObject]:
    prefix = _GIT_PREFIXES[kind]
    filename = "candidate.json" if kind == "candidates" else "manifest.json"
    raw_paths = bytes(
        _run_git(
            main_root,
            ["ls-tree", "-r", "--name-only", "-z", head, "--", prefix],
            binary=True,
        )
    )
    paths = [item.decode("utf-8") for item in raw_paths.split(b"\0") if item]
    paths = [path for path in paths if _expected_git_path(prefix, path, filename)]
    if len(paths) > _MAX_FILES_PER_SOURCE:
        raise StrategyHistorySourceUnavailable(f"{kind}_git_file_limit_exceeded")
    objects: list[_JsonObject] = []
    for path in sorted(paths):
        size_text = str(_run_git(main_root, ["cat-file", "-s", f"{head}:{path}"])).strip()
        if not size_text.isdigit() or int(size_text) > _MAX_JSON_BYTES:
            raise StrategyHistorySourceUnavailable(f"{kind}_git_object_size_rejected")
        raw = bytes(_run_git(main_root, ["cat-file", "blob", f"{head}:{path}"], binary=True))
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise StrategyHistorySourceUnavailable(f"{kind}_git_json_invalid") from exc
        if not isinstance(payload, dict):
            raise StrategyHistorySourceUnavailable(f"{kind}_git_json_not_object")
        objects.append(_JsonObject(path, payload, hashlib.sha256(raw).hexdigest()))
    return objects


def _runtime_objects(main_root: Path, kind: str) -> list[_JsonObject]:
    prefix = main_root.joinpath(*PurePosixPath(_GIT_PREFIXES[kind]).parts)
    if not prefix.exists():
        return []
    main_resolved = main_root.resolve(strict=True)
    if prefix.is_symlink():
        raise StrategyHistorySourceUnavailable(f"{kind}_runtime_symlink_rejected")
    try:
        prefix_resolved = prefix.resolve(strict=True)
    except OSError as exc:
        raise StrategyHistorySourceUnavailable(f"{kind}_runtime_root_invalid") from exc
    if not prefix_resolved.is_relative_to(main_resolved) or not prefix_resolved.is_dir():
        raise StrategyHistorySourceUnavailable(f"{kind}_runtime_root_outside_repository")
    filename = "candidate.json" if kind == "candidates" else "manifest.json"
    candidates = sorted(prefix.glob(f"*/{filename}"))
    if len(candidates) > _MAX_FILES_PER_SOURCE:
        raise StrategyHistorySourceUnavailable(f"{kind}_runtime_file_limit_exceeded")
    objects: list[_JsonObject] = []
    for path in candidates:
        if path.is_symlink() or path.parent.is_symlink():
            raise StrategyHistorySourceUnavailable(f"{kind}_runtime_symlink_rejected")
        try:
            resolved = path.resolve(strict=True)
        except OSError as exc:
            raise StrategyHistorySourceUnavailable(f"{kind}_runtime_path_invalid") from exc
        if not resolved.is_relative_to(prefix_resolved) or not resolved.is_file():
            raise StrategyHistorySourceUnavailable(f"{kind}_runtime_path_outside_repository")
        size = resolved.stat().st_size
        if size > _MAX_JSON_BYTES:
            raise StrategyHistorySourceUnavailable(f"{kind}_runtime_object_size_rejected")
        try:
            raw = resolved.read_bytes()
            payload = json.loads(raw.decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise StrategyHistorySourceUnavailable(f"{kind}_runtime_json_invalid") from exc
        if not isinstance(payload, dict):
            raise StrategyHistorySourceUnavailable(f"{kind}_runtime_json_not_object")
        relative = resolved.relative_to(main_resolved).as_posix()
        objects.append(_JsonObject(relative, payload, hashlib.sha256(raw).hexdigest()))
    return objects


def _records_from_objects(
    experiments: list[_JsonObject],
    candidates: list[_JsonObject],
    manifests: list[_JsonObject],
    *,
    source: str,
    head: str,
) -> list[dict[str, Any]]:
    candidates_by_experiment: dict[str, dict[str, Any]] = {}
    for item in candidates:
        experiment_id = str(item.payload.get("experiment_id", ""))
        candidates_by_experiment.setdefault(experiment_id, item.payload)
    manifests_by_experiment: dict[str, dict[str, Any]] = {}
    for item in manifests:
        experiment_id = str(item.payload.get("source_experiment_id", ""))
        manifests_by_experiment.setdefault(experiment_id, item.payload)
    records: list[dict[str, Any]] = []
    for experiment in experiments:
        experiment_id = str(experiment.payload.get("experiment_id", ""))
        candidate = candidates_by_experiment.get(experiment_id, {})
        strategy_manifest = manifests_by_experiment.get(experiment_id, {})
        record = _record(
            experiment,
            candidate=candidate,
            strategy_manifest=strategy_manifest,
            source=source,
            head=head,
        )
        if record is not None:
            records.append(record)
    return records


class StrategyHistoryCatalogService:
    """Build a GET-only strategy history catalog from registered-main evidence."""

    def get_catalog(self) -> dict[str, Any]:
        errors: list[str] = []
        try:
            main_root, head = _registered_main()
        except StrategyHistorySourceUnavailable as exc:
            return self._unavailable_catalog(str(exc))

        git_groups: dict[str, list[_JsonObject]] = {}
        git_root = _code_repository_root()
        for kind in _GIT_PREFIXES:
            try:
                git_groups[kind] = _git_objects(git_root, head, kind)
            except StrategyHistorySourceUnavailable as exc:
                git_groups[kind] = []
                errors.append(str(exc))
        git_records = _records_from_objects(
            git_groups["experiments"],
            git_groups["candidates"],
            git_groups["manifests"],
            source="tracked_git_object",
            head=head,
        )

        runtime_errors: list[str] = []
        runtime_groups: dict[str, list[_JsonObject]] = {}
        for kind in _GIT_PREFIXES:
            try:
                runtime_groups[kind] = _runtime_objects(main_root, kind)
            except StrategyHistorySourceUnavailable as exc:
                runtime_groups[kind] = []
                runtime_errors.append(str(exc))
        runtime_records = _records_from_objects(
            runtime_groups["experiments"],
            runtime_groups["candidates"],
            runtime_groups["manifests"],
            source="registered_main_runtime",
            head=head,
        )

        by_run_key = {(record["domain"], record["run_id"]): record for record in git_records}
        runtime_added = 0
        for record in runtime_records:
            key = (record["domain"], record["run_id"])
            if key not in by_run_key:
                by_run_key[key] = record
                runtime_added += 1
        records = sorted(
            by_run_key.values(),
            key=lambda record: (record["domain"], record["strategy_id"], record["run_id"]),
        )
        all_errors = sorted(set(errors + runtime_errors))
        us_status = "complete" if not all_errors else "partial"
        runtime_status = "partial" if runtime_errors else ("available" if runtime_added else "empty")
        return {
            "schema_version": SCHEMA_VERSION,
            "status": us_status,
            "head": head,
            "records": records,
            "coverage": {
                "us_equity": {
                    "status": us_status,
                    "source": "tracked_git_object",
                    "git_record_count": len(git_records),
                    "runtime_record_count": runtime_added,
                    "runtime_user_runs": runtime_status,
                    "record_count": len(records),
                    "errors": all_errors,
                },
                "btc": {
                    "status": "existing_endpoint_separate",
                    "source": "existing_endpoint_separate",
                    "endpoint": "/api/research/btc/strategy-history/catalog",
                    "record_count": 0,
                },
                "cn": {
                    "status": "unavailable",
                    "source": "unavailable",
                    "record_count": 0,
                },
            },
            "paper_allowed": False,
            "live_allowed": False,
            "broker_or_order_allowed": False,
            "private_endpoint_used": False,
            "order_endpoint_used": False,
            "real_order_submitted": False,
        }

    @staticmethod
    def _unavailable_catalog(error: str) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "partial",
            "head": "",
            "records": [],
            "coverage": {
                "us_equity": {
                    "status": "partial",
                    "source": "tracked_git_object",
                    "git_record_count": 0,
                    "runtime_record_count": 0,
                    "runtime_user_runs": "unavailable",
                    "record_count": 0,
                    "errors": [error],
                },
                "btc": {
                    "status": "existing_endpoint_separate",
                    "source": "existing_endpoint_separate",
                    "endpoint": "/api/research/btc/strategy-history/catalog",
                    "record_count": 0,
                },
                "cn": {"status": "unavailable", "source": "unavailable", "record_count": 0},
            },
            "paper_allowed": False,
            "live_allowed": False,
            "broker_or_order_allowed": False,
            "private_endpoint_used": False,
            "order_endpoint_used": False,
            "real_order_submitted": False,
        }
