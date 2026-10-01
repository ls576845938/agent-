"""One shared Qlib research workflow, stage receipts and sealed read-only evidence."""
from __future__ import annotations

import hashlib
import json
import os
from collections import deque
from pathlib import Path
from typing import Any, Mapping

from .schemas import QlibAdapterError, build_run_paths, read_json, resolve_git_commit, to_jsonable, utc_now_iso, write_json
from .profiles import REPO, resolve_pipeline_request

STAGES = ("dataset", "training", "scores", "metrics", "candidate", "decisions")
SAFETY = {key: False for key in ("execution_permission", "runtime_observed", "promotion", "paper", "live", "private", "order")}
SEALED_EVIDENCE_FILES = (
    "trend_environment.json", "trend_environment_observations.jsonl",
    "factory_trial.json", "factory_features.parquet", "factory_labels.parquet", "factory_config.yaml",
    "factory_calibration_seal.json", "factory_finalization_receipt.json",
    "pipeline_result.json", "failure_report.json", "qlib_input/dataset_manifest.json", "provider_manifest.json",
    "qlib_run_metadata.json", "qlib_workflow_config.yaml", "workflow_run_result.json", "pred_score.parquet",
    "research_model_scores.parquet", "signal_evaluation.json", "model.txt", "qlib_strategy_manifest.json",
    "research_trace.json", "research_decisions.jsonl", "research_ledger.jsonl", "recorder_metrics.json",
    "imported_recorder_metrics.json", "qlib_backtest_summary.json", "pred_score_import_result.json",
    "recorder_metrics_import_result.json")


def checked_result(result, stage: str) -> dict:
    payload = to_jsonable(result)
    if not isinstance(payload, dict) or payload.get("status") not in {"completed", "dry_run"}:
        raise QlibAdapterError(f"{stage}: {payload.get('error', 'stage_not_completed') if isinstance(payload, dict) else payload}")
    return payload


def run_research_pipeline(request: dict, *, artifacts_root: str | Path = "artifacts/qlib_runs", progress=None) -> dict:
    from .build_qlib_dataset import build_qlib_dataset
    from .run_qlib_workflow import run_qlib_workflow
    from .import_pred_score import import_pred_score
    from .import_recorder_metrics import import_recorder_metrics
    from .compile_qlib_strategy_manifest import compile_qlib_strategy_manifest

    profile = resolve_pipeline_request(request)
    run_id = profile["run_id"]
    paths = build_run_paths(run_id, artifacts_root)
    if paths.run_root.exists():
        raise QlibAdapterError("Run ID already exists; immutable runs cannot be overwritten.")
    root = Path(artifacts_root)
    root.mkdir(parents=True, exist_ok=True)
    lock_path = root / ".qlib_pipeline_writer.lock"
    try:
        descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise QlibAdapterError("Another Qlib pipeline writer holds the research lock; no concurrent write permitted.") from exc
    with os.fdopen(descriptor, "w", encoding="utf-8") as lock:
        json.dump({"run_id": run_id, "pid": os.getpid(), "created_at": utc_now_iso()}, lock)
    receipt = {"schema_version": "qlib_pipeline_v1", "run_id": run_id, "profile_id": profile["profile_id"],
        "asset_class": profile["asset_class"], "bar_size": profile["bar_size"], "data_version": profile["data_version"],
        "source_head": resolve_git_commit(REPO), "created_at": utc_now_iso(), "status": "running",
        "stages": {stage: {"status": "not_run"} for stage in STAGES}, **SAFETY}
    stage = "dataset"
    def update(name, status, detail=None):
        receipt["stages"][name] = {"status": status, "detail": detail or {}}
        if progress:
            progress(stage=name, message=f"Qlib {name}: {status}", progress=STAGES.index(name) * 15 + (12 if status == "completed" else 1))
        # Export owns creation of the empty run root.
        if paths.run_root.exists():
            write_json(paths.run_root / "pipeline_result.json", receipt)
    try:
        update(stage, "running")
        result = build_qlib_dataset(universe_path=REPO / profile["universe"], start_date=profile["start_date"],
            end_date=profile["end_date"], data_version=profile["data_version"], run_id=run_id,
            artifacts_root=root, source=profile["source"], asset_class=profile["asset_class"],
            bar_size=profile["bar_size"], dry_run=profile["dry_run"])
        update(stage, result.status, checked_result(result, stage))
        if profile["dry_run"]:
            receipt["status"] = "dry_run"
        else:
            actions = {
                "training": lambda: run_qlib_workflow(config_path=REPO / profile["config"], run_id=run_id, artifacts_root=root),
                "scores": lambda: import_pred_score(run_id=run_id, artifacts_root=root),
                "metrics": lambda: import_recorder_metrics(run_id=run_id, artifacts_root=root),
                "candidate": lambda: {"status": "completed", "path": str(compile_qlib_strategy_manifest(
                    run_id=run_id, config_path=REPO / profile["config"], artifacts_root=root))},
            }
            for stage, action in actions.items():
                update(stage, "running")
                result = checked_result(action(), stage)
                update(stage, "completed", result)
            stage = "decisions"
            config = read_json(paths.run_root / "qlib_run_metadata.json")
            if profile["asset_class"] == "crypto":
                from .research_trace import build_research_trace
                update(stage, "running")
                result = build_research_trace(run_id=run_id, artifacts_root=root)
                update(stage, "completed", {"trace_status": result["status"]})
                receipt["research_flow_status"] = result["status"]
            else:
                update(stage, "not_run", {"reason": "Use the existing equity portfolio handoff."})
            receipt["status"] = "completed"
            from .trend_environment import build_sidecar
            receipt["environment_observation"] = build_sidecar(paths.run_root)
        write_json(paths.run_root / "pipeline_result.json", receipt)
        seal_run(paths.run_root)
        return receipt
    except Exception as exc:
        receipt.update({"status": "failed", "failure_stage": stage, "error": str(exc)})
        update(stage, "failed", {"error": str(exc)})
        write_json(paths.run_root / "pipeline_result.json", receipt)
        write_json(paths.run_root / "failure_report.json", receipt)
        if not (paths.run_root / "run_seal.json").exists():
            seal_run(paths.run_root)
        raise QlibAdapterError(f"qlib_pipeline_failed:{run_id}:{stage}:{exc}") from exc
    finally:
        lock_path.unlink()


def seal_run(run_root: Path) -> dict:
    if (run_root / "run_seal.json").exists():
        raise QlibAdapterError("Run is already sealed.")
    names = list(SEALED_EVIDENCE_FILES)
    names += [path.relative_to(run_root).as_posix() for path in (run_root / "qlib_input").glob("*.parquet")]
    names += [path.relative_to(run_root).as_posix() for path in (run_root / "qlib_provider").rglob("*") if path.is_file()]
    payload = {"schema_version": "qlib_run_seal_v1", "run_id": run_root.name,
        "source_head": resolve_git_commit(REPO), "created_at": utc_now_iso(), "files": {
            name: hashlib.sha256((run_root / name).read_bytes()).hexdigest() for name in names if (run_root / name).is_file()}}
    write_json(run_root / "run_seal.json", payload)
    return payload


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_decisions(
    path: Path,
    *,
    run_id: str,
    include_preview: bool,
) -> tuple[str, list[dict]]:
    digest = hashlib.sha256()
    preview: deque[dict] = deque(maxlen=48)
    with path.open("rb") as source:
        for raw_line in source:
            digest.update(raw_line)
            row = json.loads(raw_line.decode("utf-8"))
            if not isinstance(row, dict) or row.get("qlib_run_id") != run_id:
                raise QlibAdapterError("decision_identity_mismatch")
            if include_preview:
                preview.append(row)
    return digest.hexdigest(), list(preview)


def _validate_sidecar_summary(run_root: Path, seal: dict) -> None:
    path = run_root / "trend_environment.json"
    if not path.exists():
        return
    payload = read_json(path)
    if payload.get("schema_version") != "trend_environment_evidence_v1" or payload.get("usage") != "observation_only":
        raise QlibAdapterError("environment_schema_mismatch")
    if payload.get("status") not in {"completed", "blocked", "disabled"}:
        raise QlibAdapterError("environment_status_mismatch")
    sidecar_safety_keys = (
        *SAFETY,
        "real_order",
        "transfer",
        "withdraw",
    )
    if any(payload.get(key) is not False for key in sidecar_safety_keys):
        raise QlibAdapterError("environment_safety_mismatch")
    identity = payload.get("identity", {})
    if not isinstance(identity, dict) or identity.get("run_id") != run_root.name:
        raise QlibAdapterError("environment_run_identity_mismatch")
    code_version = str(identity.get("code_version", ""))
    if code_version and code_version != str(seal.get("source_head", "")):
        raise QlibAdapterError("environment_binding_mismatch")


def read_sealed_evidence(
    run_root: Path,
    *,
    summary_only: bool = False,
    verified_manifest_files: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict:
    # GET path: never create, train, migrate or select another run.
    if not (run_root / "run_seal.json").exists():
        return {"integrity_status": "unknown", "blockers": ["run_not_sealed"], **SAFETY}
    try:
        seal = read_json(run_root / "run_seal.json")
        if seal.get("schema_version") != "qlib_run_seal_v1":
            raise QlibAdapterError("seal_schema_mismatch")
        files = seal.get("files")
        if not isinstance(files, dict):
            raise QlibAdapterError("seal_files_invalid")
        if any(
            not isinstance(name, str)
            or not name
            or not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
            for name, digest in files.items()
        ):
            raise QlibAdapterError("seal_files_invalid")
        if seal["run_id"] != run_root.name or not files:
            raise QlibAdapterError("seal_identity_mismatch")
        manifest_files = None
        if verified_manifest_files is not None:
            manifest_files = dict(verified_manifest_files)
            seal_attestation = manifest_files.get("run_seal.json")
            if not isinstance(seal_attestation, Mapping):
                raise QlibAdapterError("manifest_attestation_missing:run_seal.json")
            seal_path = run_root / "run_seal.json"
            if int(seal_attestation.get("bytes", -1)) != seal_path.stat().st_size:
                raise QlibAdapterError("manifest_file_size_mismatch:run_seal.json")
            if str(seal_attestation.get("sha256", "")) != _hash_file(seal_path):
                raise QlibAdapterError("manifest_file_hash_mismatch:run_seal.json")
        for name in SEALED_EVIDENCE_FILES:
            if (run_root / name).exists() and name not in files:
                raise QlibAdapterError("evidence_file_not_sealed:" + name)
        preview: list[dict] = []
        for name, digest in files.items():
            path = (run_root / name).resolve()
            if not path.is_relative_to(run_root.resolve()) or not path.is_file():
                raise QlibAdapterError("run_file_hash_mismatch:" + name)
            if name == "research_decisions.jsonl":
                actual_digest, preview = _verify_decisions(
                    path,
                    run_id=run_root.name,
                    include_preview=not summary_only,
                )
            else:
                if manifest_files is None:
                    actual_digest = _hash_file(path)
                else:
                    attestation = manifest_files.get(name)
                    if not isinstance(attestation, Mapping):
                        raise QlibAdapterError(
                            "manifest_attestation_missing:" + name
                        )
                    if int(attestation.get("bytes", -1)) != path.stat().st_size:
                        raise QlibAdapterError(
                            "manifest_file_size_mismatch:" + name
                        )
                    actual_digest = str(attestation.get("sha256", ""))
                    if actual_digest != digest:
                        raise QlibAdapterError(
                            "manifest_and_seal_hash_mismatch:" + name
                        )
            if actual_digest != digest:
                raise QlibAdapterError("run_file_hash_mismatch:" + name)
        trace = read_json(run_root / "research_trace.json") if (run_root / "research_trace.json").exists() else {}
        if trace and trace.get("identity", {}).get("qlib_run_id") != run_root.name:
            raise QlibAdapterError("trace_identity_mismatch")
        if summary_only:
            _validate_sidecar_summary(run_root, seal)
            return {
                "integrity_status": "passed",
                "seal": seal,
                "validation_scope": (
                    "manifest_hashes_and_summary_identity"
                    if manifest_files is not None
                    else "seal_and_summary_identity"
                ),
                **SAFETY,
            }
        from .trend_environment import read_sidecar
        environment = read_sidecar(run_root, seal)
        return {"integrity_status": "passed", "seal": seal, "research_trace": trace, "trend_environment": environment,
            "decision_trace_preview": preview, **SAFETY}
    except (OSError, UnicodeError, ValueError, KeyError, TypeError, QlibAdapterError) as exc:
        return {"integrity_status": "blocked", "blockers": [str(exc)], **SAFETY}
