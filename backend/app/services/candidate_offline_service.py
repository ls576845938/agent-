"""One durable offline use case; HTTP and CLI share this coordinator.

Threads schedule work, SQLite persists orchestration, the original runtime owns
economics and fencing. Restart NEVER dispatches work automatically.
"""
import os
import secrets
import threading
from datetime import datetime, timezone
from uuid import uuid4

from quant_shared.strategy_delivery.models import DeliveryError, digest, identifier, HASH
from quant_shared.strategy_delivery.offline_contract import (
    job_id, require_job, safety, seal_job_identity, identity_fields,
    require_job_identity, require_bound_identity)
from .candidate_offline_views import projection
from backend.app.core.candidate_local_auth import MODE, is_local_context
from quant_shared.strategy_delivery.runtime_contract import CAPABILITY as FACTORY_OFFLINE_ADAPTER

SUPPORTED_ADAPTER_IDS = (FACTORY_OFFLINE_ADAPTER,)


class CandidateOfflineService:
    def __init__(self, delivery, inputs, index, store, *, profile, enabled, operator, management_key, auth_mode="key"):
        self.delivery, self.inputs, self.index, self.store = delivery, inputs, index, store
        self.profile, self.enabled, self.operator = profile, enabled, operator
        self._management_key = management_key
        self.auth_mode = auth_mode
        self._instance = uuid4().hex
        self._threads = {}
        self._lock = threading.Lock()

    def authorize(self, key, *, write):
        local = self.auth_mode == MODE and self.profile == "candidate_management"
        if not self.operator or (not local and (self.auth_mode != "key" or not self._management_key)):
            raise DeliveryError("candidate_offline_not_configured", 423)
        identifier(self.operator)
        authenticated = (is_local_context(key) if local else
            isinstance(key, str) and bool(key) and len(key) <= 1024
            and secrets.compare_digest(key.encode(), self._management_key.encode()))
        if not authenticated:
            raise DeliveryError("candidate_management_authentication_required", 403)
        if write and (self.profile != "candidate_management" or not self.enabled):
            raise DeliveryError("candidate_offline_commands_disabled", 423)
        return self.operator

    def capabilities(self, key=None):
        try: self.authorize(key, write=False); authenticated = True
        except DeliveryError: authenticated = False
        allowed = authenticated and self.profile == "candidate_management" and self.enabled
        return {**safety(), "source_implemented": True, "deployed_configured": True, "auth_mode": self.auth_mode,
                "capability_enabled": self.enabled and self.profile == "candidate_management",
                "authenticated": authenticated, "offline_commands_enabled": allowed,
                "offline_start_allowed": allowed, "deployment_head": self.delivery.head,
                "blockers": [] if allowed else ["candidate_offline_commands_disabled_or_unauthenticated"],
                "protection_execution_supported": True,
                "protection_execution_scope": "new_current_code_runs_explicit_sampled_mark_only",
                "protection_execution_limitations": [
                    "intrainterval_mark_path_not_inferred",
                    "legacy_blocked_results_remain_authoritative",
                ],
                "supported_adapter_ids": list(SUPPORTED_ADAPTER_IDS)}

    def _start_row(self, body):
        row = self.delivery.get(body["registration_id"])
        if (row["revision"] != body["expected_revision"] or row["content_digest"] != body["content_digest"]
            or row["status"] != "registered" or row["target"] != "offline"):
            raise DeliveryError("offline_registration_revision_mismatch")
        if row.get("package", {}).get("adapter_id") not in SUPPORTED_ADAPTER_IDS:
            raise DeliveryError("offline_runtime_adapter_unsupported")
        return row

    def _alive(self, job):
        if not job.get("worker"): return False
        worker = job["worker"]
        if worker["instance"] == self._instance:
            with self._lock:
                t = self._threads.get((job["id"], worker["generation"]))
                return t is not None and t.is_alive()
        # Never steal from a different surviving process. PID reuse is conservative.
        if job["status"] not in {"queued", "running", "stop_requested"}: return False
        if os.name == "nt":
            import ctypes
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.OpenProcess.restype = ctypes.c_void_p
            handle = kernel.OpenProcess(0x1000, False, worker["pid"])
            if not handle: return ctypes.get_last_error() == 5
            kernel.CloseHandle.argtypes = [ctypes.c_void_p]
            kernel.CloseHandle(handle)
            return True
        try: os.kill(worker["pid"], 0); return True
        except ProcessLookupError: return False
        except PermissionError: return True

    def status(self, identity):
        job = self.store.read("job", require_job(identity))
        require_job_identity(job, identity)
        if job["status"] in {"queued", "running", "stop_requested"} and not self._alive(job):
            job = {**job, "status": "interrupted", "blocker": "explicit_resume_required_no_automatic_restart"}
        return {**{k:v for k,v in job.items() if k != "worker"}, "deployment_head": self.delivery.head,
                "offline_job_executed": job["cursor"] > 0, **safety()}

    def list(self):
        return {"jobs": [self.status(j["id"]) for j in self.store.read("job")], **safety()}

    def result(self, identity, *, before=2147483647):
        status = self.status(identity)
        try: result = self.store.read("result", identity)
        except DeliveryError as exc:
            if exc.status != 404: raise
            result = None
        authority = require_job_identity(status, identity)
        if result is not None:
            require_bound_identity(result, authority)
            if result.get("schema_version") != "candidate_offline_result_v2":
                raise DeliveryError("offline_result_identity_legacy")
        decisions = self.store.decisions(identity, before)
        if result is not None and result.get("sha256") != digest({k:v for k,v in result.items() if k != "sha256"}):
            raise DeliveryError("offline_result_integrity_mismatch")
        for decision in decisions:
            require_bound_identity(decision, authority)
            if (decision.get("schema_version") != "candidate_offline_decision_v2"
                or decision.get("receipt_sha256") != digest(decision.get("receipt"))):
                raise DeliveryError("offline_decision_identity_mismatch")
        return {"job": status, "result": result, "result_bound": result is not None,
                "decisions": decisions, "next_before": min((d["cursor"] for d in decisions), default=None), **safety()}

    def start(self, body, *, key, credential):
        actor = self.authorize(credential, write=True)
        if (not isinstance(body, dict) or set(body) != {"registration_id", "content_digest", "expected_revision", "input_revision_id", "input_digest"}
            or type(body["expected_revision"]) is not int or body["expected_revision"] < 1
            or any(not isinstance(body[k], str) or not HASH.fullmatch(body[k]) for k in ("content_digest", "input_digest"))):
            raise DeliveryError("offline_start_fields_invalid", 422)
        identifier(body["input_revision_id"])
        identifier(key)
        identity = job_id(body["registration_id"])
        request = digest({"start": body, "actor": actor})
        generation = uuid4().hex
        with self.store.transaction() as conn:
            cached = self.store.cached(conn, key, request)
            if cached is not None:
                require_job_identity(self.store.get(conn, "job", identity), identity)
                return cached
            row = self._start_row(body)
            if conn.execute("SELECT 1 FROM records WHERE kind='job' AND id=?", (identity,)).fetchone():
                raise DeliveryError("offline_existing_job_requires_resume")
            # Small catalog lookup only. Heavy model/input validation runs before
            # the worker constructs any economic state, not in the HTTP request.
            rows = [r for r in self.inputs.catalog()["inputs"] if r["input_revision_id"] == body["input_revision_id"]]
            if len(rows) != 1 or rows[0]["content_digest"] != body["input_digest"]:
                raise DeliveryError("offline_input_revision_mismatch")
            bound = row["binding"]
            runtime = bound.get("offline_runtime", {})
            if not runtime.get("state_directory_sha256"): raise DeliveryError("offline_account_runtime_missing")
            sealed = seal_job_identity(identity, row, rows[0], self.delivery.head, self.inputs.checksum)
            for resource in ("account:" + bound["identity_hash"], "state:" + runtime["state_directory_sha256"]):
                self.store.reserve(conn, resource, identity)
            job = {"schema_version": "candidate_offline_job_v2", "id": identity, **body,
                **identity_fields(sealed), "actor": actor, "revision": 1, "status": "queued",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "cursor": 0, "total": None, "blocker": None, "stop_requested": False,
                "worker": {"pid": os.getpid(), "instance": self._instance, "generation": generation}}
            self.store.put(conn, "job", identity, job)
            response = {"job_id": identity, "status": "queued", "revision": 1, **safety()}
            self.store.cache(conn, key, request, response)
        self._dispatch(identity, generation)
        return response

    def command(self, identity, action, *, expected_revision, key, credential):
        actor = self.authorize(credential, write=True)
        require_job(identity); identifier(key)
        request = digest({"job": identity, "action": action, "revision": expected_revision, "actor": actor})
        dispatch = None
        with self.store.transaction() as conn:
            cached = self.store.cached(conn, key, request)
            if cached is not None:
                require_job_identity(self.store.get(conn, "job", identity), identity)
                return cached
            job = self.store.get(conn, "job", identity)
            require_job_identity(job, identity)
            if job["revision"] != expected_revision: raise DeliveryError("offline_job_revision_conflict")
            alive = self._alive(job)
            if action == "stop":
                if job["status"] == "complete": raise DeliveryError("offline_job_already_complete")
                job["stop_requested"] = True
                job["status"] = "stop_requested" if alive else "interrupted"
            elif action == "resume":
                if alive: raise DeliveryError("offline_worker_active")
                if job["status"] == "complete": raise DeliveryError("offline_job_already_complete")
                if job.get("protection_blocked"): raise DeliveryError("offline_protection_execution_unsupported")
                if job["execution_head"] != self.delivery.head or job["catalog_sha256"] != self.inputs.checksum:
                    raise DeliveryError("offline_resume_identity_changed")
                refs = [r for r in self.inputs.catalog()["inputs"] if r["input_revision_id"] == job["input_revision_id"]]
                if len(refs) != 1: raise DeliveryError("offline_resume_identity_changed")
                expected = seal_job_identity(identity, self.delivery.get(job["registration_id"]),
                                             refs[0], self.delivery.head, self.inputs.checksum)
                require_bound_identity(job, expected)
                dispatch = uuid4().hex
                job.update(status="queued", stop_requested=False, blocker=None,
                    worker={"pid": os.getpid(), "instance": self._instance, "generation": dispatch})
            else: raise DeliveryError("offline_command_invalid", 422)
            job["revision"] += 1
            job["updated_at"] = datetime.now(timezone.utc).isoformat()
            self.store.put(conn, "job", identity, job)
            result = {"job_id": identity, "status": job["status"], "revision": job["revision"], **safety()}
            self.store.cache(conn, key, request, result)
        if dispatch: self._dispatch(identity, dispatch)
        return result

    def _dispatch(self, identity, generation):
        thread = threading.Thread(target=self._work, args=(identity, generation), daemon=True,
                                  name="candidate-offline-" + identity[-8:])
        with self._lock:
            self._threads[(identity, generation)] = thread
            thread.start()

    def _update(self, identity, generation, *, receipt=None, **changes):
        with self.store.transaction() as conn:
            job = self.store.get(conn, "job", identity)
            sealed = require_job_identity(job, identity)
            if job["worker"]["generation"] != generation: raise DeliveryError("offline_worker_fenced")
            job.update(changes, revision=job["revision"] + 1)
            require_bound_identity(job, sealed)
            require_job_identity(job, identity)
            if receipt is not None:
                require_bound_identity(receipt, sealed)
            job["updated_at"] = datetime.now(timezone.utc).isoformat()
            self.store.put(conn, "job", identity, job)
            if receipt is not None: self.store.put(conn, "result", identity, receipt)
            if receipt is not None and "cursor" in changes:
                entry = {"schema_version": "candidate_offline_decision_v2", **identity_fields(sealed),
                         "cursor": job["cursor"], "receipt": receipt["decision_receipt"],
                         "receipt_sha256": receipt["decision_receipt_sha256"]}
                key = identity + ":" + str(job["cursor"]).zfill(10)
                prior = conn.execute("SELECT payload,sha FROM records WHERE kind='decision' AND id=?", (key,)).fetchone()
                if prior is not None and self.store.decode(prior) != entry: raise DeliveryError("offline_decision_projection_conflict")
                self.store.put(conn, "decision", key, entry)
            return job

    def _work(self, identity, generation):
        runtime = None
        try:
            job = self._update(identity, generation, status="running")
            if self.profile != "candidate_management" or not self.enabled:
                raise DeliveryError("candidate_offline_commands_disabled")
            if job["execution_head"] != self.delivery.head or job["catalog_sha256"] != self.inputs.checksum:
                raise DeliveryError("offline_resume_identity_changed")
            row = self.delivery.get(job["registration_id"])
            if row["binding_digest"] != job["binding_digest"]: raise DeliveryError("account_binding_changed")
            ref, args = self.inputs.load(job["input_revision_id"], job["input_digest"])
            expected = seal_job_identity(identity, row, ref, self.delivery.head, self.inputs.checksum)
            require_bound_identity(job, expected)
            binding = row["binding"]
            state = self.delivery.accounts.offline_state_directory(binding["account_ref"], binding["offline_runtime"]["contract_digest"])
            if job.get("constructor_attempted") and not (state / "runtime").is_dir():
                raise DeliveryError("offline_prior_state_missing_no_balance_reset")
            from quant_crypto.application.btc_registered_candidate import open_btc_registered_candidate_offline
            from quant_shared.strategy_delivery.models import utc
            recovery = (row["status"] == "revoked" or utc(row["review"]["expires_at"]) <= self.delivery.clock()
                        or utc(binding["expires_at"]) <= self.delivery.clock())
            job = self._update(identity, generation, constructor_attempted=True)
            runtime = open_btc_registered_candidate_offline(self.delivery, row["id"], **args,
                content_digest=job["content_digest"], account_identity_hash=binding["identity_hash"],
                adapter_id=row["package"]["adapter_id"], state_dir=state, repo_root=self.delivery.sources.repo,
                recovery_only=recovery)
            if recovery:
                receipt = runtime.reconcile_registered()
                view = projection(job, runtime, receipt)
                runtime.close()
                runtime = None
                self._update(identity, generation, status="blocked", blocker="safety_reconciled_no_new_risk",
                             receipt=view)
                return
            job = self._update(identity, generation, total=len(args["observations"]))
            for step in range(job["cursor"], job["total"]):
                current = self.store.read("job", identity)
                require_job_identity(current, identity)
                require_bound_identity(current, job["job_identity"])
                if current["worker"]["generation"] != generation: raise DeliveryError("offline_worker_fenced")
                if current["stop_requested"]:
                    runtime.close()
                    runtime = None
                    self._update(identity, generation, status="stopped")
                    return
                receipt = runtime.execute_registered(step)
                job = self._update(identity, generation, cursor=step + 1,
                    last_completed_event=args["observations"][step].event_time_utc.isoformat(),
                    receipt=projection(job, runtime, {**receipt, "event_time_utc": args["observations"][step].event_time_utc.isoformat()}))
            runtime.close()
            runtime = None
            self._update(identity, generation, status="complete")
        except BaseException as exc:
            code = exc.code if isinstance(exc, DeliveryError) else "offline_runtime_interrupted_requires_reconcile"
            # No exception repr/path/credentials in public projections.
            protection = runtime is not None and bool(runtime.controller._state.get("registered_protection_blocker"))
            if protection: code = "registered_protection_execution_unsupported"
            receipt = (projection(job, runtime, {"blocker": code, "protection_blocker": runtime.controller._state.get("registered_protection_blocker")})
                       if protection else None)
            self._update(identity, generation, status="blocked" if isinstance(exc, DeliveryError) or protection else "interrupted",
                         blocker=code, protection_blocked=protection, receipt=receipt)
        finally:
            if runtime is not None: runtime.close()
