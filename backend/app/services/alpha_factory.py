"""Server-owned persistent factory repository and composition; no trading API."""
from __future__ import annotations

import hashlib
from importlib.metadata import PackageNotFoundError, version as distribution_version
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import time
import uuid

import pandas as pd

from quant_shared.alpha_factory.contracts import (FactoryError, SAFETY, STAGES, digest, validate_budget,
    REAL_ACCEPTANCE_PROFILE, REAL_ACCEPTANCE_PRIMITIVES, REAL_ACCEPTANCE_FIT_LIMIT)
from quant_shared.alpha_factory.engine import run_campaign
from integrations.qlib_adapter.factory_data import market_profiles, resolve_profile, load_factory_input, read_factory_input
from integrations.qlib_adapter.factory_factors import build_primitives, seed_factors, crossover
from integrations.qlib_adapter.factory_trainer import MODEL_CATALOG, train_feature_trial
from integrations.qlib_adapter.profiles import REPO
from integrations.qlib_adapter.research_pipeline import read_sealed_evidence
from integrations.qlib_adapter.schemas import read_json, resolve_git_commit, to_jsonable, utc_now_iso
from backend.app.services.research_archive_discovery import (
    M1_FACTORY_RUN_IDS,
    ReadonlyRunLocation,
    ResearchArchiveCatalog,
    ResearchArchiveUnavailable,
)


REAL_ACCEPTANCE_PROTECTION_POLICY = {
    "version": "registered_offline_oco_v1",
    "trigger": "mark",
    "reference_price": "aggressive_limit_at_order_construction",
    "effective": "attached_after_fill",
}


def _atomic_json(path: Path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(to_jsonable(value), sort_keys=True, ensure_ascii=True, allow_nan=False), encoding="utf-8")
    # A short concurrent Windows GET may still hold a read handle on the old
    # file. Keep atomic replacement, retry only this bounded sharing failure.
    for attempt in range(10):
        try:
            os.replace(temporary, path)
            return
        except PermissionError:
            if attempt == 9: raise
            time.sleep(.01 * (attempt + 1))


def _run_path(root: Path, run_id: str) -> Path:
    if not isinstance(run_id, str) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,79}", run_id) or run_id.lower() == "latest":
        raise FactoryError("invalid_factory_run_id")
    if run_id.upper() in {"CON", "PRN", "AUX", "NUL", *[f"COM{i}" for i in range(1,10)], *[f"LPT{i}" for i in range(1,10)]}:
        raise FactoryError("invalid_factory_run_id")
    candidate = (root / run_id).resolve()
    if candidate.parent != root.resolve(): raise FactoryError("factory_path_escape")
    return candidate


def _owner_alive(owner: dict) -> bool:
    import psutil
    try: return abs(psutil.Process(owner["pid"]).create_time() - owner["process_created"]) < .01
    except (KeyError, psutil.NoSuchProcess): return False
    except psutil.Error: return True  # unable to prove a dead owner => fail closed


@contextmanager
def _claim_guard(root: Path):
    """OS-owned mutex: process death releases it; no stale guard reclamation."""
    stream = (root / ".writer.guard").open("a+b")
    locked = False
    try:
        if stream.seek(0, os.SEEK_END) == 0:
            stream.write(b"0"); stream.flush()
        for attempt in range(100):
            try:
                stream.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                locked = True
                break
            except OSError:
                if attempt == 99: raise FactoryError("factory_claim_guard_busy")
                time.sleep(.01)
        yield
    finally:
        if locked:
            stream.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        stream.close()


def _release_owned_lock(path: Path, expected: dict):
    with _claim_guard(path.parent):
        if path.exists() and read_json(path) == expected:
            path.unlink()


def _research_dependency_versions():
    versions = {}
    for key, distribution in (("numpy", "numpy"), ("pandas", "pandas"),
        ("lightgbm", "lightgbm"), ("qlib", "pyqlib")):
        try:
            value = distribution_version(distribution)
        except PackageNotFoundError as exc:
            raise FactoryError("acceptance_dependency_missing:" + key) from exc
        if not value:
            raise FactoryError("acceptance_dependency_version_missing:" + key)
        versions[key] = value
    return versions


def _validate_acceptance_fit_budget(value, *, campaign_id):
    if (not isinstance(value, dict)
        or set(value) != {"schema_version", "campaign_id", "maximum_actual_fits", "reservations"}
        or value.get("schema_version") != "alpha_factory_fit_budget_v1"
        or value.get("campaign_id") != campaign_id
        or value.get("maximum_actual_fits") != REAL_ACCEPTANCE_FIT_LIMIT
        or not isinstance(value.get("reservations"), list)
        or len(value["reservations"]) > REAL_ACCEPTANCE_FIT_LIMIT):
        raise FactoryError("acceptance_fit_budget_invalid")
    for attempt, row in enumerate(value["reservations"], 1):
        required = {"attempt", "fit_key", "phase", "status", "reserved_at", "run_id"}
        status = row.get("status") if isinstance(row, dict) else None
        if status in {"failed", "completed"}: required.add("finished_at")
        if status == "completed": required.add("qlib_run_id")
        if (not isinstance(row, dict) or set(row) != required or row.get("attempt") != attempt
            or status not in {"reserved", "failed", "completed"}
            or any(not isinstance(row.get(name), str) or not row[name] for name in required - {"attempt"})):
            raise FactoryError("acceptance_fit_budget_invalid")
    return value


class AlphaFactoryService:
    def __init__(
        self,
        *,
        root: Path,
        qlib_root: Path,
        queue,
        readonly_archive: ResearchArchiveCatalog | None = None,
    ):
        self.root, self.qlib_root, self.queue = Path(root), Path(qlib_root), queue
        self.readonly_archive = readonly_archive

    def profiles(self):
        return {"profiles": market_profiles(), "model_catalog": list(MODEL_CATALOG),
            "budget_limits": {"population": 32, "generations": 4, "max_features": 12, "model_trials": 3},
            "source_head": resolve_git_commit(REPO), **SAFETY}

    def list_runs(self, limit=20):
        if self.readonly_archive is None:
            if not self.root.exists(): return []
            candidates = [p.name for p in self.root.iterdir() if p.is_dir() and (p / "state.json").is_file()]
            rows = [self.get(run_id, summary_only=True) for run_id in candidates]
        else:
            locations = self.readonly_archive.list_factory_runs(self.root, self.qlib_root)
            rows = [self._get_from_location(location, summary_only=True) for location in locations]
        return sorted(rows, key=lambda row: row.get("created_at", ""), reverse=True)[:max(1, min(limit, 100))]

    def _events(self, root, committed_count=None):
        events, previous = [], ""
        path = root / "events.jsonl"
        if not path.exists(): return events
        lines = path.read_text(encoding="utf-8").splitlines()
        if committed_count is not None:
            if len(lines) < committed_count: raise FactoryError("factory_event_watermark_missing")
            lines = lines[:committed_count]
        for line in lines:
            row = json.loads(line)
            claimed = row.pop("event_hash")
            if row.get("previous_hash") != previous or digest(row) != claimed:
                raise FactoryError("factory_event_chain_invalid")
            row["event_hash"] = claimed; previous = claimed; events.append(row)
        return events

    def get(self, run_id, summary_only=False):
        _run_path(self.root, run_id)
        if self.readonly_archive is not None:
            location = self.readonly_archive.resolve_factory_run(self.root, self.qlib_root, run_id)
            if location is None:
                raise FileNotFoundError(run_id)
            return self._get_from_location(location, summary_only=summary_only)
        root = _run_path(self.root, run_id)
        if not (root / "state.json").exists(): raise FileNotFoundError(run_id)
        return self._read_run(
            run_id=run_id,
            root=root,
            qlib_root=self.qlib_root,
            summary_only=summary_only,
            provenance=None,
            archived=False,
        )

    def _get_from_location(self, location: ReadonlyRunLocation, *, summary_only=False):
        if not (location.run_root / "state.json").exists():
            if location.archived:
                raise ResearchArchiveUnavailable(
                    f"readonly_archive_factory_state_missing:{location.run_id}"
                )
            raise FileNotFoundError(location.run_id)
        return self._read_run(
            run_id=location.run_id,
            root=location.run_root,
            qlib_root=location.qlib_root,
            summary_only=summary_only,
            provenance=dict(location.provenance),
            archived=location.archived,
        )

    def _read_run(self, *, run_id, root, qlib_root, summary_only, provenance, archived):
        try:
            state = read_json(root / "state.json")
            if state["run_id"] != run_id: raise FactoryError("factory_identity_mismatch")
            seal_path = root / "seal.json"
            integrity = "unsealed_running"
            if seal_path.exists():
                seal = read_json(seal_path)
                if seal["run_id"] != run_id: raise FactoryError("factory_seal_identity_mismatch")
                for name, checksum in seal["files"].items():
                    path = (root / name).resolve()
                    if path.parent != root.resolve() or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != checksum:
                        raise FactoryError("factory_seal_mismatch:" + name)
                if not {"state.json", "request.json", "events.jsonl", "profile.json"}.issubset(seal["files"]):
                    raise FactoryError("factory_seal_incomplete")
                if state["status"] == "completed" and "result.json" not in seal["files"]:
                    raise FactoryError("factory_result_not_sealed")
                for name in ("lineage.json", "trial_cache.json", "result.json"):
                    if (root / name).exists() and name not in seal["files"]:
                        raise FactoryError("factory_reference_not_sealed:" + name)
                integrity = "passed"
                if (root / "lineage.json").exists():
                    lineage = read_json(root / "lineage.json")
                    input_evidence = read_sealed_evidence(_run_path(qlib_root, lineage["input_run_id"]))
                    if input_evidence["integrity_status"] != "passed" or digest(input_evidence["seal"]) != lineage["input_seal_sha256"]:
                        raise FactoryError("referenced_input_seal_invalid")
                if (root / "trial_cache.json").exists():
                    for reference in read_json(root / "trial_cache.json").values():
                        child = _run_path(qlib_root, reference["qlib_run_id"])
                        child_evidence = read_sealed_evidence(child)
                        if child_evidence["integrity_status"] != "passed" or digest(child_evidence["seal"]) != reference["seal_sha256"]:
                            raise FactoryError("referenced_qlib_seal_invalid")
            events = self._events(root, state.get("event_count", 0))
            if events and state.get("last_event_hash") != events[-1]["event_hash"]:
                raise FactoryError("factory_event_watermark_mismatch")
            if state["status"] in {"running", "queued"} and not _owner_alive(state["owner"]):
                state = {**state, "status": "interrupted", "blockers": ["owner_process_not_running_explicit_resume_required"]}
            elif state["status"] in {"completed", "failed"} and integrity == "unsealed_running":
                state = {**state, "status": "running" if _owner_alive(state["owner"]) else "interrupted"}
            summary = {key: state.get(key) for key in ("run_id", "profile_id", "status", "created_at", "updated_at",
                "source_head", "task_id", "decision", "blockers", "stages", "request_hash", "parent_run_id")}
            summary.update(integrity_status=integrity, current_source_head=resolve_git_commit(REPO),
                source_stale=state["source_head"] != resolve_git_commit(REPO), **SAFETY)
            if provenance is not None:
                summary["evidence_provenance"] = provenance
            if summary_only: return summary
            result = read_json(root / "result.json") if (root / "result.json").is_file() else None
            return {**summary, "request": read_json(root / "request.json"), "profile": read_json(root / "profile.json"),
                "events": events, "result": result, "event_count": len(events),
                "recovery": {"explicit_resume_required": state["status"] in {"failed", "interrupted"},
                    "automatic_restart": False}, **SAFETY}
        except (ValueError, KeyError, OSError) as exc:
            if archived:
                raise ResearchArchiveUnavailable(
                    f"readonly_archive_factory_seal_invalid:{run_id}"
                ) from exc
            return {"run_id": run_id, "status": "blocked", "integrity_status": "blocked", "blockers": [str(exc)], **SAFETY}

    def submit(self, request: dict, *, parent_run_id=None):
        request = validate_budget(request)
        request["run_id"] = request.get("run_id") or "af-" + uuid.uuid4().hex
        if self.readonly_archive is not None and request["run_id"] in M1_FACTORY_RUN_IDS:
            raise FactoryError("factory_archive_run_id_reserved")
        root = _run_path(self.root, request["run_id"])
        if len(request["run_id"]) > 64: raise FactoryError("factory_run_id_too_long")
        profile = resolve_profile(request.get("profile_id"))
        request_hash = digest(request)
        if root.exists():
            existing = self.get(request["run_id"])
            if existing.get("request_hash") == request_hash and existing.get("integrity_status") != "blocked":
                return existing  # run id is the idempotency key, not a new trial
            raise FactoryError("factory_run_id_conflict")
        import psutil
        self.root.mkdir(parents=True, exist_ok=True)
        lock_path = self.root / ".writer.lock"
        owner = {"pid": os.getpid(), "process_created": psutil.Process().create_time(), "run_id": request["run_id"]}
        state = {"schema_version": "alpha_factory_state_v1", "run_id": request["run_id"], "profile_id": profile["profile_id"],
            "request_hash": request_hash, "source_head": resolve_git_commit(REPO), "owner": owner,
            "created_at": utc_now_iso(), "updated_at": utc_now_iso(), "status": "queued", "decision": "not_evaluated",
            "parent_run_id": parent_run_id, "stages": {stage: "not_run" for stage in STAGES}, "blockers": [], **SAFETY}
        claimed = initialized = False
        try:
            with _claim_guard(self.root):
                if lock_path.exists():
                    previous_owner = read_json(lock_path)
                    if not parent_run_id or previous_owner.get("run_id") != parent_run_id or _owner_alive(previous_owner):
                        raise FactoryError("factory_writer_busy_or_recovery_required")
                    lock_path.unlink()  # exact dead owner; guard covers reclaim AND claim
                # A crash before initialized state cannot leave an orphan writer
                # lock: publish ownership last, while the OS mutex still holds.
                root.mkdir()
                _atomic_json(root / "request.json", request); _atomic_json(root / "profile.json", profile)
                _atomic_json(root / "state.json", state)
                initialized = True
                self._emit(root, state, "data", "queued", {"request_hash": request_hash})
                _atomic_json(lock_path, owner)
                claimed = True
            task = self.queue.submit(kind="alpha_factory", label="Alpha Factory " + profile["profile_id"], request=request,
                job=lambda context: self._run(root, request, profile, state, context))
            # The worker alone owns state after queue submission. Task id is the
            # queue mirror; persisted run_id is the durable recovery key.
            return {"run_id": request["run_id"], "task_id": task["task_id"], "status": task["status"], **SAFETY}
        except Exception as exc:
            if initialized:
                try:
                    reason = "queue_submission_failed:" if claimed else "factory_initialization_failed:"
                    state.update(status="failed", decision="blocked", blockers=[reason + str(exc)])
                    self._emit(root, state, "data", "failed", {"error": state["blockers"][0]})
                    self._seal(root)
                finally:
                    if claimed: _release_owned_lock(lock_path, owner)
            raise

    def resume(self, run_id):
        existing = self.get(run_id)
        if existing.get("evidence_provenance", {}).get("storage") == "immutable_shared_data":
            raise FactoryError("factory_archive_run_is_read_only")
        if existing.get("integrity_status") == "blocked" or existing.get("status") not in {"failed", "interrupted"}:
            raise FactoryError("only_verified_failed_or_interrupted_run_can_resume")
        if existing["source_stale"]: raise FactoryError("resume_source_head_changed_new_statistical_campaign_required")
        profile = resolve_profile(existing["profile_id"])
        if profile["profile_hash"] != existing["profile"]["profile_hash"]: raise FactoryError("resume_profile_changed")
        if digest(existing["request"]) != existing["request_hash"]: raise FactoryError("resume_request_hash_mismatch")
        request = {**existing["request"], "run_id": "af-" + uuid.uuid4().hex}
        return self.submit(request, parent_run_id=run_id)

    def _emit(self, root, state, stage, status, detail):
        events = self._events(root)
        row = {"sequence": len(events) + 1, "time": utc_now_iso(), "stage": stage, "status": status,
            "detail": to_jsonable(detail), "previous_hash": events[-1]["event_hash"] if events else ""}
        row["event_hash"] = digest(row)
        with (root / "events.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(row, ensure_ascii=True, allow_nan=False) + "\n"); stream.flush(); os.fsync(stream.fileno())
        if status in {"queued", "running", "completed", "failed"}: state["stages"][stage] = status
        state["event_count"] = len(events) + 1
        state["last_event_hash"] = row["event_hash"]
        state["updated_at"] = utc_now_iso()
        _atomic_json(root / "state.json", state)

    def _seal(self, root):
        names = ["request.json", "profile.json", "state.json", "events.jsonl", "result.json", "lineage.json", "trial_cache.json",
            "research_contract.json", "fit_budget.json"]
        _atomic_json(root / "seal.json", {"schema_version": "alpha_factory_seal_v1", "run_id": root.name,
            "files": {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in names if (root / name).is_file()}})

    def _run(self, root, request, profile, state, context):
        state.update(status="running", task_id=context.task_id)
        qlib_lock = self.qlib_root / ".qlib_pipeline_writer.lock"
        owns_qlib_lock = False
        def emit(stage, status, detail):
            self._emit(root, state, stage, status, detail)
            context.update(stage=stage, message=f"Alpha {stage}: {status}", progress=STAGES.index(stage) * 16 + 3)
        try:
            self.qlib_root.mkdir(parents=True, exist_ok=True)
            if qlib_lock.exists() and state.get("parent_run_id"):
                owner = read_json(qlib_lock)
                if owner.get("factory_run_id") == state["parent_run_id"] and not _owner_alive(owner): qlib_lock.unlink()
            try: descriptor = os.open(qlib_lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError as exc: raise FactoryError("shared_qlib_writer_busy") from exc
            owns_qlib_lock = True
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump({**state["owner"], "factory_run_id": root.name}, stream)
            emit("data", "running", {"profile_hash": profile["profile_hash"]})
            parent = _run_path(self.root, state["parent_run_id"]) if state.get("parent_run_id") else None
            if parent and (parent / "lineage.json").exists():
                old_lineage = read_json(parent / "lineage.json")
                panel, lineage = read_factory_input(profile, qlib_root=self.qlib_root, input_run_id=old_lineage["input_run_id"])
                if lineage["input_sha256"] != old_lineage["input_sha256"]: raise FactoryError("resume_input_hash_changed")
            else:
                panel, lineage = load_factory_input(profile, qlib_root=self.qlib_root, input_run_id=root.name + "-input")
            _atomic_json(root / "lineage.json", lineage)
            emit("data", "completed", {"input_run_id": lineage["input_run_id"], "input_sha256": lineage["input_sha256"],
                "data_version": lineage["data_version"], "rows": len(panel), "as_of": lineage["as_of"]})
            acceptance = request.get("acceptance_profile") == REAL_ACCEPTANCE_PROFILE
            if acceptance:
                dependency_versions = _research_dependency_versions()
                if parent:
                    if not (parent / "research_contract.json").is_file() or not (parent / "fit_budget.json").is_file():
                        raise FactoryError("acceptance_parent_budget_or_contract_missing")
                    research_contract = read_json(parent / "research_contract.json")
                    if research_contract.get("schema_version") != "btc_real_candidate_research_contract_v1":
                        raise FactoryError("acceptance_parent_research_contract_invalid")
                else:
                    research_contract = {
                        "schema_version": "btc_real_candidate_research_contract_v1",
                        "acceptance_profile": REAL_ACCEPTANCE_PROFILE,
                        "policy_committed_at": utc_now_iso(),
                        "campaign_id": state.get("parent_run_id") or root.name,
                        "source_head": state["source_head"], "profile_hash": profile["profile_hash"],
                        "input_run_id": lineage["input_run_id"], "input_sha256": lineage["input_sha256"],
                        "data_version": lineage["data_version"], "dependency_versions": dependency_versions,
                        "dependency_fingerprint": digest(dependency_versions),
                        "primitives": list(REAL_ACCEPTANCE_PRIMITIVES), "primitive_bar_semantics": "d_suffix_means_1h_bars",
                        "generator_policy": "registered_only", "maximum_features": 6,
                        "model": {"model_id": "lgbm_small", "seed": 17, "num_leaves": 7, "learning_rate": .035,
                            "min_data_in_leaf": 80, "lambda_l2": 5, "num_boost_round": 100,
                            "early_stopping_rounds": 12, "num_threads": 2},
                        "fit_budget": {"selection_folds": 4, "final_fits": 1, "maximum_actual_fits": REAL_ACCEPTANCE_FIT_LIMIT},
                        "calibration": {"kind": "ols_validation_only", "slope_clip": .05, "applications": 1},
                        "cost_scenarios_bps": {"base": 24, "conservative": 36, "stress": 48},
                        "position": {"version": "qlib_candidate_policy_v1", "risk_budget_fraction": .01,
                            "max_weight": .10, "volatility_target_annual_configured": .20,
                            "volatility_target_applied": False},
                        "exit": {"version": "qlib_candidate_policy_v1", "hard_stop_fraction": .04, "take_profit_fraction": .08,
                            "trailing_stop_fraction": .03, "maximum_holding_bars": 12,
                            "protection": dict(REAL_ACCEPTANCE_PROTECTION_POLICY)},
                        "output": {"version": "return_forecast_v1", "kind": "return_forecast",
                            "unit": "return_fraction", "horizon_bars": 12, "valid_for_bars": 2,
                            "score_rule": "absolute_return_fraction_unit_multiplier"},
                        "cost": {"version": "qlib_candidate_policy_v1", "execution_delay_bars": 2, "fee_bps_per_side": 5,
                            "slippage_bps_per_side": 2, "spread_bps_per_side": 2,
                            "impact_bps_per_side": 2, "funding": "visible_rate"},
                        "decision_window": {"start": "2026-06-16T01:00:00Z", "end_exclusive": "2026-06-18T01:00:00Z",
                            "decision_count": 48},
                        "permissions": dict(SAFETY),
                    }
                if (research_contract.get("source_head") != state["source_head"]
                    or research_contract.get("input_sha256") != lineage["input_sha256"]
                    or research_contract.get("data_version") != lineage["data_version"]
                    or research_contract.get("dependency_versions") != dependency_versions
                    or research_contract.get("dependency_fingerprint") != digest(dependency_versions)):
                    raise FactoryError("acceptance_frozen_research_contract_changed")
                _atomic_json(root / "research_contract.json", research_contract)
                if parent:
                    fit_budget = _validate_acceptance_fit_budget(read_json(parent / "fit_budget.json"),
                        campaign_id=research_contract["campaign_id"])
                else:
                    fit_budget = {"schema_version": "alpha_factory_fit_budget_v1", "campaign_id": research_contract["campaign_id"],
                        "maximum_actual_fits": REAL_ACCEPTANCE_FIT_LIMIT, "reservations": []}
                _atomic_json(root / "fit_budget.json", fit_budget)
            else:
                research_contract = None
                fit_budget = None
            primitives, catalog = build_primitives(panel, bar_size=profile["bar_size"], annualization=profile["annualization"])
            cache = read_json(parent / "trial_cache.json") if parent and (parent / "trial_cache.json").exists() else {}
            _atomic_json(root / "trial_cache.json", cache)
            def trainer(**kwargs):
                if resolve_git_commit(REPO) != state["source_head"]: raise FactoryError("source_head_changed_during_campaign")
                features, labels = kwargs["features"], kwargs["labels"]
                key = digest({"segments": kwargs["segments"], "model": kwargs["model_spec"], "seed": request["seed"],
                    "input": lineage["input_sha256"], "feature_columns": list(features),
                    "feature_values": hashlib.sha256(pd.util.hash_pandas_object(features, index=True).values.tobytes()).hexdigest()})
                if key in cache:
                    reference = cache[key]
                    run_root = self.qlib_root / reference["qlib_run_id"]
                    verified = read_sealed_evidence(run_root)
                    if verified["integrity_status"] != "passed" or digest(verified["seal"]) != reference["seal_sha256"]:
                        raise FactoryError("resume_qlib_trial_seal_invalid")
                    scores = pd.read_parquet(run_root / "pred_score.parquet")
                    prediction = scores.rename(columns={"symbol": "instrument"}).set_index(["datetime", "instrument"]).score
                    return prediction, {**reference, "reused_sealed_trial": True}
                reservation = None
                if acceptance:
                    if len(fit_budget["reservations"]) >= REAL_ACCEPTANCE_FIT_LIMIT:
                        raise FactoryError("acceptance_actual_fit_budget_exhausted")
                    reservation = {"attempt": len(fit_budget["reservations"]) + 1, "fit_key": key,
                        "phase": kwargs["phase"], "status": "reserved", "reserved_at": utc_now_iso(),
                        "run_id": root.name}
                    fit_budget["reservations"].append(reservation)
                    _atomic_json(root / "fit_budget.json", fit_budget)
                trial_id = f"{root.name}-t{kwargs['trial_number']}-{kwargs['phase']}"
                try:
                    prediction, reference = train_feature_trial(features=features, labels=labels, segments=kwargs["segments"],
                        profile=profile, lineage={**lineage, "split_plan": kwargs["plan"]}, model_spec=kwargs["model_spec"],
                        seed=request["seed"], qlib_root=self.qlib_root, run_id=trial_id, factory_run_id=root.name,
                        trial_number=kwargs["trial_number"], phase=kwargs["phase"],
                        candidate_id=kwargs.get("candidate_id"), research_contract=research_contract)
                except BaseException:
                    if reservation is not None:
                        reservation["status"] = "failed"
                        reservation["finished_at"] = utc_now_iso()
                        _atomic_json(root / "fit_budget.json", fit_budget)
                    raise
                if reservation is not None:
                    reservation["status"] = "completed"
                    reservation["finished_at"] = utc_now_iso()
                    reservation["qlib_run_id"] = reference["qlib_run_id"]
                    _atomic_json(root / "fit_budget.json", fit_budget)
                cache[key] = reference; _atomic_json(root / "trial_cache.json", cache)
                return prediction, reference
            result = run_campaign(panel=panel, profile=profile, request=request, primitives=primitives,
                primitive_catalog=catalog, seed_specs=seed_factors(list(primitives)), crossover=crossover,
                model_catalog=MODEL_CATALOG, trainer=trainer, emit=emit)
            if acceptance:
                result["research_contract"] = research_contract
                result["fit_budget"] = fit_budget
            result.update(source_head=state["source_head"], lineage=lineage, parent_run_id=state["parent_run_id"])
            if resolve_git_commit(REPO) != state["source_head"]: raise FactoryError("source_head_changed_during_campaign")
            state.update(status="completed", decision=result["decision"], blockers=result.get("blockers", []))
            _atomic_json(root / "result.json", result); _atomic_json(root / "state.json", state)
            self._seal(root)
            return {"run_id": root.name, "decision": result["decision"], "blockers": result.get("blockers", []), **SAFETY}
        except Exception as exc:
            state.update(status="failed", decision="blocked", blockers=[str(exc)])
            stage = next((s for s in reversed(STAGES) if state["stages"][s] == "running"), "data")
            emit(stage, "failed", {"error": str(exc)}); self._seal(root)
            raise
        finally:
            if owns_qlib_lock:
                _release_owned_lock(qlib_lock, {**state["owner"], "factory_run_id": root.name})
            _release_owned_lock(self.root / ".writer.lock", state["owner"])
