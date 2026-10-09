"""One durable offline use case; HTTP and CLI share this coordinator.

Threads schedule work, SQLite persists orchestration, the original runtime owns
economics and fencing. Restart NEVER dispatches work automatically.
"""
import os
import secrets
import threading
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from uuid import uuid4

from quant_shared.strategy_delivery.models import DeliveryError, digest, identifier, HASH
from quant_shared.strategy_delivery.offline_contract import (
    job_id, require_job, safety, seal_job_identity, identity_fields,
    require_job_identity, require_bound_identity, seal_cohort_job_identity,
    cohort_identity_fields, require_cohort_job_identity, require_cohort_bound_identity,
    require_any_job_identity, require_any_bound_identity)
from .candidate_offline_views import projection, cohort_projection
from backend.app.core.candidate_local_auth import MODE, is_local_context
from quant_shared.strategy_delivery.runtime_contract import CAPABILITY as FACTORY_OFFLINE_ADAPTER
from quant_crypto.application.btc_registered_donchian import ADAPTER_ID as DONCHIAN_OFFLINE_ADAPTER

SUPPORTED_ADAPTER_IDS = (FACTORY_OFFLINE_ADAPTER, DONCHIAN_OFFLINE_ADAPTER)
COHORT_SCHEMAS = {"candidate_offline_cohort_proposal_v1","candidate_offline_cohort_review_v1",
                  "candidate_offline_cohort_start_v1"}


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
                    "cohort_unattributed_hosted_protection_fill_blocks_recovery",
                ],
                "supported_adapter_ids": list(SUPPORTED_ADAPTER_IDS),
                "cohort_source_supported": True,
                "cohort_schema_version": "candidate_offline_cohort_binding_v1",
                "cohort_execution_policy_compatible": False,
                "cohort_execution_blocker": "cohort_member_execution_policy_incompatible",
                "cohort_protection_policy_compatible": False,
                "cohort_protection_blocker": "multi_strategy_cohort_protection_policy_incompatible",
                "cohort_support_scope": "exact2_source_contract_implemented_execution_policy_blocked"}

    def cohort_bindings(self):
        """Read-only projection; never creates the store or reconciles economics."""
        return [{key:value for key,value in row.items() if key not in {"worker"}}
                for row in self.store.read("cohort_binding")]

    def _start_row(self, body):
        row = self.delivery.get(body["registration_id"])
        if (row["revision"] != body["expected_revision"] or row["content_digest"] != body["content_digest"]
            or row["status"] != "registered" or row["target"] != "offline"):
            raise DeliveryError("offline_registration_revision_mismatch")
        if row.get("package", {}).get("adapter_id") not in SUPPORTED_ADAPTER_IDS:
            raise DeliveryError("offline_runtime_adapter_unsupported")
        return row

    @staticmethod
    def _input_supports(row, adapter_id):
        donchian=row.get("schema_version")=="candidate_offline_donchian_history_v1"
        return (adapter_id==DONCHIAN_OFFLINE_ADAPTER and donchian) or (adapter_id==FACTORY_OFFLINE_ADAPTER and not donchian)

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
        require_any_job_identity(job, identity)
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
        authority = require_any_job_identity(status, identity)
        if result is not None:
            require_any_bound_identity(result, authority)
            expected_schema=("candidate_offline_cohort_result_v1"
                if status.get("schema_version")=="candidate_offline_cohort_job_v1" else "candidate_offline_result_v2")
            if result.get("schema_version") != expected_schema:
                raise DeliveryError("offline_result_identity_legacy")
        decisions = self.store.decisions(identity, before)
        if result is not None and result.get("sha256") != digest({k:v for k,v in result.items() if k != "sha256"}):
            raise DeliveryError("offline_result_integrity_mismatch")
        for decision in decisions:
            require_any_bound_identity(decision, authority)
            expected_decision=("candidate_offline_cohort_decision_v1"
                if status.get("schema_version")=="candidate_offline_cohort_job_v1" else "candidate_offline_decision_v2")
            if (decision.get("schema_version") != expected_decision
                or decision.get("receipt_sha256") != digest(decision.get("receipt"))):
                raise DeliveryError("offline_decision_identity_mismatch")
        return {"job": status, "result": result, "result_bound": result is not None,
                "decisions": decisions, "next_before": min((d["cursor"] for d in decisions), default=None), **safety()}

    def _cohort_member(self, source):
        row=self.delivery.get(source["registration_id"])
        if (row["revision"]!=source["expected_revision"] or row["content_digest"]!=source["content_digest"]
            or row["status"]!="registered" or row["target"]!="offline"):
            raise DeliveryError("offline_cohort_registration_revision_mismatch")
        adapter=row.get("package",{}).get("adapter_id")
        if adapter not in SUPPORTED_ADAPTER_IDS: raise DeliveryError("offline_runtime_adapter_unsupported")
        ref=self.inputs.ref(source["input_revision_id"],source["input_digest"])
        if not self._input_supports(ref,adapter): raise DeliveryError("offline_input_adapter_mismatch")
        package=row["package"]; bound=row["binding"]
        return row,ref,{"member_id":row["id"],"registration_id":row["id"],"registration_revision":row["revision"],
            "content_digest":row["content_digest"],"binding_digest":row["binding_digest"],
            "source_account_ref":bound["account_ref"],"source_account_identity_hash":bound["identity_hash"],
            "adapter_id":adapter,"input_revision_id":ref["input_revision_id"],
            "input_digest":ref["content_digest"],"input_head":ref["input_head"],
            "input_evidence_kind":ref["evidence_kind"],"source_head":package["source_head"],
            "strategy_id":package["strategy_id"],"strategy_version":package["strategy_version"]}

    @staticmethod
    def _require_cohort_entry_compatible():
        # The currently supported exact pair is known incompatible before any
        # binding/job persistence: Donchian t+1 versus Qlib t+2 execution, and
        # distinct original protection policy hashes. Existing sealed jobs may
        # still use resume solely to repair an already committed projection.
        raise DeliveryError("cohort_member_execution_policy_incompatible")

    def _propose_cohort(self, body, *, key, credential):
        actor=self.authorize(credential,write=True);identifier(key)
        self._require_cohort_entry_compatible()
        if not body["reason"].strip():raise DeliveryError("cohort_binding_reason_required")
        request=digest({"cohort_proposal":body,"actor":actor})
        members=[];rows=[]
        for source in body["members"]:
            row,ref,member=self._cohort_member(source);rows.append((row,ref,source));members.append(member)
        members=sorted(members,key=lambda value:value["registration_id"])
        if (len(members)!=2 or len({m["registration_id"] for m in members})!=2
            or {m["adapter_id"] for m in members}!=set(SUPPORTED_ADAPTER_IDS)):
            raise DeliveryError("cohort_member_identity_or_adapter_set_invalid")
        common=self.delivery.accounts.get(body["common_account_ref"])
        runtime=common.get("offline_runtime",{})
        from quant_crypto.application.btc_registered_cohort import validate_common_runtime
        validate_common_runtime(runtime)
        if common["account_ref"] in {m["source_account_ref"] for m in members}:
            raise DeliveryError("cohort_common_account_must_be_distinct_from_source_accounts")
        from quant_crypto.portfolio.multi_strategy import ExplicitBudgetPolicy,MultiStrategyCoordinationError
        member_notional={source["registration_id"]:Decimal(str(source["member_max_notional_usdt"])) for _,_,source in rows}
        member_loss={source["registration_id"]:Decimal(str(source["member_max_loss_usdt"])) for _,_,source in rows}
        try:
            budget=ExplicitBudgetPolicy(member_notional,member_loss,
                Decimal(str(body["account_max_notional_usdt"])),Decimal(str(body["account_max_loss_usdt"]))).normalized(
                    tuple(member["registration_id"] for member in members))
        except (ValueError,ArithmeticError,MultiStrategyCoordinationError) as exc:
            raise DeliveryError(str(exc) or "cohort_budget_invalid") from exc
        event_clock={"schema_version":"candidate_offline_cohort_event_clock_v1",
            "authority":"registered_qlib_market_v2","conflict_policy":"reject_same_event_price_or_funding_mismatch",
            "member_inputs":[{"registration_id":member["registration_id"],"input_revision_id":member["input_revision_id"],
                "input_digest":member["input_digest"]} for member in members]}
        authority={"schema_version":"candidate_offline_cohort_authority_v1","members":members,
            "common_account":{"account_ref":common["account_ref"],"identity_hash":common["identity_hash"],
                "offline_runtime":runtime},"budget_policy":budget,"event_clock":event_clock,
            "execution_head":self.delivery.head,"catalog_sha256":self.inputs.checksum}
        authority_sha=digest(authority);binding_id="cbnd_"+authority_sha[:32]
        created=datetime.now(timezone.utc).isoformat()
        record={"schema_version":"candidate_offline_cohort_binding_v1","id":binding_id,"revision":1,
            "status":"proposed","members":members,"common_account":authority["common_account"],
            "budget_policy":budget,"event_clock":event_clock,"member_list_sha256":digest(members),
            "budget_policy_sha256":digest(budget),"event_clock_sha256":digest(event_clock),
            "cohort_authority_sha256":authority_sha,"execution_head":self.delivery.head,
            "catalog_sha256":self.inputs.checksum,"actor":actor,"reason":body["reason"].strip(),
            "created_at":created,"review":None}
        unsigned={k:v for k,v in record.items() if k not in {"binding_digest","revision","status","review"}}
        record["binding_digest"]=digest(unsigned)
        response={"cohort_binding_id":binding_id,"status":"proposed","revision":1,
            "binding_digest":record["binding_digest"],**safety()}
        with self.store.transaction() as conn:
            cached=self.store.cached(conn,key,request)
            if cached is not None:return cached
            if conn.execute("SELECT 1 FROM records WHERE kind='cohort_binding' AND id=?",(binding_id,)).fetchone():
                raise DeliveryError("cohort_binding_already_proposed")
            self.store.put(conn,"cohort_binding",binding_id,record)
            self.store.put(conn,"cohort_binding_event",binding_id+":0000000001",record)
            self.store.cache(conn,key,request,response)
        return response

    def _review_cohort(self, body, *, key, credential):
        actor=self.authorize(credential,write=True);identifier(key);identifier(body["cohort_binding_id"])
        self._require_cohort_entry_compatible()
        if not body["reason"].strip():raise DeliveryError("cohort_binding_reason_required")
        request=digest({"cohort_review":body,"actor":actor})
        with self.store.transaction() as conn:
            cached=self.store.cached(conn,key,request)
            if cached is not None:return cached
            record=self.store.get(conn,"cohort_binding",body["cohort_binding_id"])
            if (record["status"]!="proposed" or record["revision"]!=body["expected_revision"]
                or record["binding_digest"]!=body["binding_digest"]):
                raise DeliveryError("cohort_binding_review_revision_mismatch")
            unsigned={name:value for name,value in record.items()
                if name not in {"binding_digest","revision","status","review"}}
            if digest(unsigned)!=record["binding_digest"]:raise DeliveryError("offline_cohort_binding_integrity_invalid")
            from quant_shared.strategy_delivery.models import utc
            expires=utc(body["expires_at"]);now=self.delivery.clock()
            if expires<=now or expires>now+timedelta(days=31): raise DeliveryError("cohort_binding_review_expiry_invalid")
            status="approved" if body["decision"]=="approve" else "rejected"
            record={**record,"revision":2,"status":status,"review":{"decision":body["decision"],
                "actor":actor,"reason":body["reason"].strip(),"expires_at":expires.isoformat()}}
            if status=="approved":
                member_ids={member["registration_id"] for member in record["members"]}
                # Jobs created before registration reservations were added
                # still own their single-strategy economic authority.  A new
                # cohort review may not bypass that ownership via a new lease.
                for encoded in conn.execute("SELECT payload,sha FROM records WHERE kind='job'").fetchall():
                    prior=self.store.decode(encoded)
                    owned={str(prior.get("registration_id") or "")}
                    if prior.get("schema_version")=="candidate_offline_cohort_job_v1":
                        try:
                            prior_binding=self.store.get(conn,"cohort_binding",prior["cohort_binding_id"])
                            owned={member["registration_id"] for member in prior_binding["members"]}
                        except (DeliveryError,KeyError,TypeError):
                            raise DeliveryError("offline_existing_job_authority_ambiguous")
                    if member_ids & owned:
                        raise DeliveryError("offline_state_already_reserved")
                resources=["account:"+record["common_account"]["identity_hash"],
                    "state:"+record["common_account"]["offline_runtime"]["state_directory_sha256"]]
                resources += ["registration:"+member["registration_id"] for member in record["members"]]
                for resource in resources:self.store.reserve(conn,resource,record["id"])
            self.store.put(conn,"cohort_binding",record["id"],record)
            self.store.put(conn,"cohort_binding_event",record["id"]+":0000000002",record)
            response={"cohort_binding_id":record["id"],"status":status,"revision":2,
                "binding_digest":record["binding_digest"],**safety()}
            self.store.cache(conn,key,request,response)
        return response

    def _verify_cohort_binding(self,record):
        if (record.get("status")!="approved" or record.get("execution_head")!=self.delivery.head
            or record.get("catalog_sha256")!=self.inputs.checksum):
            raise DeliveryError("offline_cohort_binding_identity_changed")
        from quant_shared.strategy_delivery.models import utc
        if utc(record["review"]["expires_at"])<=self.delivery.clock():
            raise DeliveryError("offline_cohort_binding_expired")
        rebuilt=[]
        for member in record["members"]:
            row=self.delivery.get(member["registration_id"])
            source={"registration_id":member["registration_id"],"expected_revision":member["registration_revision"],
                "content_digest":member["content_digest"],"input_revision_id":member["input_revision_id"],
                "input_digest":member["input_digest"]}
            _,_,current=self._cohort_member(source);rebuilt.append(current)
        if sorted(rebuilt,key=lambda value:value["registration_id"])!=record["members"]:
            raise DeliveryError("offline_cohort_binding_identity_changed")
        common=self.delivery.accounts.get(record["common_account"]["account_ref"])
        if ({"account_ref":common["account_ref"],"identity_hash":common["identity_hash"],
             "offline_runtime":common["offline_runtime"]}!=record["common_account"]):
            raise DeliveryError("offline_cohort_binding_identity_changed")
        return record

    def _start_cohort(self, body, *, key, credential):
        actor=self.authorize(credential,write=True);identifier(key);identifier(body["cohort_binding_id"])
        self._require_cohort_entry_compatible()
        request=digest({"cohort_start":body,"actor":actor});generation=uuid4().hex
        with self.store.transaction() as conn:
            cached=self.store.cached(conn,key,request)
            if cached is not None:
                require_cohort_job_identity(self.store.get(conn,"job",cached["job_id"]),cached["job_id"]);return cached
            record=self.store.get(conn,"cohort_binding",body["cohort_binding_id"])
            if (record["revision"]!=body["expected_revision"] or record["binding_digest"]!=body["binding_digest"]):
                raise DeliveryError("offline_cohort_binding_revision_mismatch")
            self._verify_cohort_binding(record)
            sealed=seal_cohort_job_identity(record,execution_head=self.delivery.head,catalog_sha256=self.inputs.checksum)
            identity=sealed["job_id"]
            if conn.execute("SELECT 1 FROM records WHERE kind='job' AND id=?",(identity,)).fetchone():
                raise DeliveryError("offline_existing_job_requires_resume")
            job={"schema_version":"candidate_offline_cohort_job_v1","id":identity,**cohort_identity_fields(sealed),
                "cohort_binding_id":record["id"],"cohort_binding_digest":record["binding_digest"],
                "actor":actor,"revision":1,"status":"queued","created_at":datetime.now(timezone.utc).isoformat(),
                "cursor":0,"total":None,"blocker":None,"stop_requested":False,
                "worker":{"pid":os.getpid(),"instance":self._instance,"generation":generation}}
            self.store.put(conn,"job",identity,job)
            response={"job_id":identity,"status":"queued","revision":1,**safety()};self.store.cache(conn,key,request,response)
        self._dispatch(identity,generation);return response

    def start(self, body, *, key, credential):
        if isinstance(body,dict) and body.get("schema_version") in COHORT_SCHEMAS:
            action=body["schema_version"]
            if action=="candidate_offline_cohort_proposal_v1":
                return self._propose_cohort(body,key=key,credential=credential)
            if action=="candidate_offline_cohort_review_v1":
                return self._review_cohort(body,key=key,credential=credential)
            return self._start_cohort(body,key=key,credential=credential)
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
            adapter_id=row["package"]["adapter_id"]
            if not self._input_supports(rows[0],adapter_id):
                raise DeliveryError("offline_input_adapter_mismatch")
            if ((adapter_id==DONCHIAN_OFFLINE_ADAPTER
                    and (runtime.get("schema_version")!="delivery_offline_runtime_v2"
                        or runtime.get("adapter_id")!=DONCHIAN_OFFLINE_ADAPTER
                        or runtime.get("initial_equity_usdt")!=5000 or runtime.get("currency")!="USDT"))
                or (adapter_id==FACTORY_OFFLINE_ADAPTER
                    and runtime.get("schema_version")!="delivery_offline_runtime_v1")):
                raise DeliveryError("offline_account_adapter_mismatch")
            sealed = seal_job_identity(identity, row, rows[0], self.delivery.head, self.inputs.checksum)
            for resource in ("account:" + bound["identity_hash"], "state:" + runtime["state_directory_sha256"]):
                self.store.reserve(conn, resource, identity)
            self.store.reserve(conn,"registration:"+row["id"],identity)
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
                require_any_job_identity(self.store.get(conn, "job", identity), identity)
                return cached
            job = self.store.get(conn, "job", identity)
            require_any_job_identity(job, identity)
            if job["revision"] != expected_revision: raise DeliveryError("offline_job_revision_conflict")
            alive = self._alive(job)
            if action == "stop":
                if job["status"] == "complete": raise DeliveryError("offline_job_already_complete")
                job["stop_requested"] = True
                job["status"] = "stop_requested" if alive else "interrupted"
            elif action == "resume":
                if alive: raise DeliveryError("offline_worker_active")
                if job["status"] == "complete": raise DeliveryError("offline_job_already_complete")
                if job["status"] == "blocked": raise DeliveryError("offline_job_terminal_blocked")
                if job.get("protection_blocked"): raise DeliveryError("offline_protection_execution_unsupported")
                if job["execution_head"] != self.delivery.head or job["catalog_sha256"] != self.inputs.checksum:
                    raise DeliveryError("offline_resume_identity_changed")
                if job.get("schema_version")=="candidate_offline_cohort_job_v1":
                    # Resume first reopens the sealed job authority. Mutable
                    # review expiry/revocation is checked before any new
                    # decision in the worker, after an already committed UOW
                    # has had one chance to repair its missing projection.
                    binding=self.store.get(conn,"cohort_binding",job["cohort_binding_id"])
                    expected=seal_cohort_job_identity(binding,execution_head=job["execution_head"],catalog_sha256=job["catalog_sha256"])
                    require_cohort_bound_identity(job,expected)
                else:
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

    def _update_cohort(self,identity,generation,*,committed=None,member_states=None,pending=None,**changes):
        with self.store.transaction() as conn:
            job=self.store.get(conn,"job",identity);sealed=require_cohort_job_identity(job,identity)
            if job["worker"]["generation"]!=generation:raise DeliveryError("offline_worker_fenced")
            job.update(changes,revision=job["revision"]+1,updated_at=datetime.now(timezone.utc).isoformat())
            require_cohort_bound_identity(job,sealed);require_cohort_job_identity(job,identity)
            self.store.put(conn,"job",identity,job)
            if committed is not None:
                view=cohort_projection(job,None,committed);require_cohort_bound_identity(view,sealed)
                self.store.put(conn,"result",identity,view)
                entry={"schema_version":"candidate_offline_cohort_decision_v1",**cohort_identity_fields(sealed),
                    "cursor":job["cursor"],"receipt":committed,"receipt_sha256":digest(committed)}
                decision_id=identity+":"+str(job["cursor"]).zfill(10)
                prior=conn.execute("SELECT payload,sha FROM records WHERE kind='decision' AND id=?",(decision_id,)).fetchone()
                if prior is not None and self.store.decode(prior)!=entry:raise DeliveryError("offline_decision_projection_conflict")
                self.store.put(conn,"decision",decision_id,entry)
            for registration,state in (member_states or {}).items():
                self.store.put(conn,"member_state",identity+":"+registration,state)
            if pending is not None:self.store.put(conn,"pending",identity+":"+str(pending["cursor"]).zfill(10),pending)
            return job

    def _save_cohort_pending(self,identity,generation,prepared):
        durable=prepared.durable();value={"schema_version":"candidate_offline_cohort_pending_v1",
            "job_id":identity,"cursor":prepared.cursor,"status":"prepared","prepared":durable}
        value["sha256"]=digest(value)
        with self.store.transaction() as conn:
            job=self.store.get(conn,"job",identity);require_cohort_job_identity(job,identity)
            if job["worker"]["generation"]!=generation:raise DeliveryError("offline_worker_fenced")
            key=identity+":"+str(prepared.cursor).zfill(10)
            prior=conn.execute("SELECT payload,sha FROM records WHERE kind='pending' AND id=?",(key,)).fetchone()
            if prior is not None and self.store.decode(prior)!=value:raise DeliveryError("cohort_pending_decision_conflict")
            self.store.put(conn,"pending",key,value)
        return value

    def _work_cohort(self,identity,generation):
        runtime=None;job=None
        try:
            job=self._update_cohort(identity,generation,status="running")
            if self.profile!="candidate_management" or not self.enabled:raise DeliveryError("candidate_offline_commands_disabled")
            binding=self.store.read("cohort_binding",job["cohort_binding_id"])
            expected=seal_cohort_job_identity(binding,execution_head=job["execution_head"],catalog_sha256=job["catalog_sha256"])
            require_cohort_bound_identity(job,expected)
            common=binding["common_account"];location=self.delivery.accounts.offline_cohort_location(
                common["account_ref"],common["offline_runtime"]["contract_digest"])
            state=location["state_dir"]
            if job.get("constructor_attempted") and not state.is_dir():
                raise DeliveryError("offline_prior_state_missing_no_balance_reset")
            # Economic authority precedes the mutable management projection.
            # Repair exactly one already-committed pending UOW from the sealed
            # job/binding before expiry, revocation or registration drift may
            # block all subsequent strategy/risk decisions.
            pending_key=identity+":"+str(job["cursor"]+1).zfill(10)
            try:recovery_pending=self.store.read("pending",pending_key)
            except DeliveryError as exc:
                if exc.status!=404:raise
                recovery_pending=None
            if recovery_pending is not None and state.is_dir():
                from quant_crypto.application.btc_registered_cohort import RegisteredCohortReplay,cohort_data_version
                prepared=recovery_pending.get("prepared") or {}
                recovery=RegisteredCohortReplay.open_projection_recovery(
                    runtime_binding=common["offline_runtime"],state_dir=state,
                    repo_root=self.delivery.sources.repo,
                    decision_time_utc=prepared.get("decision_time_utc"),
                    data_version=cohort_data_version(
                        donchian_input_digest=next(member["input_digest"] for member in binding["members"]
                            if member["adapter_id"]==DONCHIAN_OFFLINE_ADAPTER),
                        qlib_input_digest=next(member["input_digest"] for member in binding["members"]
                            if member["adapter_id"]==FACTORY_OFFLINE_ADAPTER),
                    ))
                try:committed=recovery.repair_committed(recovery_pending)
                finally:recovery.close()
                if committed is not None:
                    recovery_pending={**recovery_pending,"status":"committed","projection_sha256":committed["sha256"]}
                    recovery_pending["sha256"]=digest({k:v for k,v in recovery_pending.items() if k!="sha256"})
                    job=self._update_cohort(identity,generation,cursor=committed["cursor"],
                        last_completed_event=committed["event_time_utc"],committed=committed,
                        member_states=committed["member_states"],pending=recovery_pending)
                    if job.get("total") is not None and job["cursor"]>=job["total"]:
                        self._update_cohort(identity,generation,status="complete")
                        return
            binding=self._verify_cohort_binding(binding)
            expected=seal_cohort_job_identity(binding,execution_head=self.delivery.head,catalog_sha256=self.inputs.checksum)
            require_cohort_bound_identity(job,expected)
            loaded={}
            rows=[]
            for member in binding["members"]:
                row=self.delivery.get(member["registration_id"]);ref,args=self.inputs.load(member["input_revision_id"],member["input_digest"])
                if ref["input_revision_id"]!=member["input_revision_id"]:raise DeliveryError("offline_cohort_binding_identity_changed")
                rows.append(row);loaded[member["adapter_id"]]=(ref,args,row)
            qref,qargs,qrow=loaded[FACTORY_OFFLINE_ADAPTER]
            if qargs.get("input_kind")!="forecast_observations":raise DeliveryError("offline_input_adapter_mismatch")
            from quant_crypto.application.btc_registered_candidate import verify_registered_candidate_inputs
            verified=verify_registered_candidate_inputs(self.delivery,qrow["id"],content_digest=qrow["content_digest"],
                account_identity_hash=qrow["binding"]["identity_hash"],adapter_id=FACTORY_OFFLINE_ADAPTER,
                bars=qargs["bars"],market_manifest=qargs["market_manifest"],
                market_manifest_digest=qargs["market_manifest_digest"],observations=qargs["observations"],state_dir=state,
                decision_only=True,runtime_binding=common["offline_runtime"])
            dref,dargs,_=loaded[DONCHIAN_OFFLINE_ADAPTER]
            if dargs.get("input_kind")!="donchian_history":raise DeliveryError("offline_input_adapter_mismatch")
            job=self._update_cohort(identity,generation,constructor_attempted=True)
            from quant_crypto.application.btc_registered_cohort import RegisteredCohortReplay
            runtime=RegisteredCohortReplay(service=self.delivery,members=rows,runtime_binding=common["offline_runtime"],
                state_dir=state,repo_root=self.delivery.sources.repo,
                donchian_input={"input_ref":dref,"history_spec":dargs["history_spec"],"historical_input":dargs["historical_input"]},
                qlib_input={"input_ref":qref,"verified_inputs":verified},budgets=binding["budget_policy"])
            job=self._update_cohort(identity,generation,total=runtime.total)
            while job["cursor"]<job["total"]:
                current=self.store.read("job",identity);require_cohort_job_identity(current,identity)
                require_cohort_bound_identity(current,job["job_identity"])
                if current["worker"]["generation"]!=generation:raise DeliveryError("offline_worker_fenced")
                if current["stop_requested"]:
                    runtime.close();runtime=None;self._update_cohort(identity,generation,status="stopped");return
                member_states={}
                for member in binding["members"]:
                    try:member_states[member["registration_id"]]=self.store.read("member_state",identity+":"+member["registration_id"])
                    except DeliveryError as exc:
                        if exc.status!=404:raise
                        member_states[member["registration_id"]]=None
                pending_key=identity+":"+str(job["cursor"]+1).zfill(10)
                try:pending=self.store.read("pending",pending_key)
                except DeliveryError as exc:
                    if exc.status!=404:raise
                    pending=None
                committed=runtime.repair_committed(pending) if pending is not None else None
                if committed is None:
                    prepared=runtime.prepare(cursor=job["cursor"],member_states=member_states)
                    if pending is not None and prepared.durable()!=pending["prepared"]:
                        raise DeliveryError("cohort_pending_decision_reconstruction_mismatch")
                    if pending is None:pending=self._save_cohort_pending(identity,generation,prepared)
                    committed=runtime.execute(prepared)
                pending={**pending,"status":"committed","projection_sha256":committed["sha256"]}
                pending["sha256"]=digest({k:v for k,v in pending.items() if k!="sha256"})
                job=self._update_cohort(identity,generation,cursor=committed["cursor"],
                    last_completed_event=committed["event_time_utc"],committed=committed,
                    member_states=committed["member_states"],pending=pending)
            runtime.close();runtime=None;self._update_cohort(identity,generation,status="complete")
        except BaseException as exc:
            code=exc.code if isinstance(exc,DeliveryError) else "offline_runtime_interrupted_requires_reconcile"
            if job is not None:
                self._update_cohort(identity,generation,status="blocked" if isinstance(exc,DeliveryError) else "interrupted",
                    blocker=code,protection_blocked=(code in {"registered_protection_execution_unsupported",
                        "cohort_unattributed_hosted_protection_fill"}))
        finally:
            if runtime is not None:runtime.close()

    def _work(self, identity, generation):
        initial=self.store.read("job",identity)
        if initial.get("schema_version")=="candidate_offline_cohort_job_v1":
            self._work_cohort(identity,generation);return
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
            adapter_id=row["package"]["adapter_id"]
            runtime_binding=binding["offline_runtime"]
            if adapter_id==DONCHIAN_OFFLINE_ADAPTER:
                location=self.delivery.accounts.offline_runtime_location(
                    binding["account_ref"],runtime_binding["contract_digest"],adapter_id)
                state=(location["output_root"]/location["run_id"]).resolve()
                if job.get("constructor_attempted") and not state.is_dir():
                    raise DeliveryError("offline_prior_state_missing_no_balance_reset")
            else:
                state=self.delivery.accounts.offline_state_directory(
                    binding["account_ref"],runtime_binding["contract_digest"])
                if job.get("constructor_attempted") and not (state/"runtime").is_dir():
                    raise DeliveryError("offline_prior_state_missing_no_balance_reset")
            from quant_shared.strategy_delivery.models import utc
            recovery = (row["status"] == "revoked" or utc(row["review"]["expires_at"]) <= self.delivery.clock()
                        or utc(binding["expires_at"]) <= self.delivery.clock())
            job = self._update(identity, generation, constructor_attempted=True)
            input_kind=args.pop("input_kind")
            if adapter_id==DONCHIAN_OFFLINE_ADAPTER:
                if input_kind!="donchian_history": raise DeliveryError("offline_input_adapter_mismatch")
                from quant_crypto.application.btc_registered_donchian import open_btc_registered_donchian_offline
                runtime=open_btc_registered_donchian_offline(self.delivery,row["id"],
                    content_digest=job["content_digest"],account_identity_hash=binding["identity_hash"],
                    adapter_id=adapter_id,runtime_binding=runtime_binding,output_root=location["output_root"],
                    run_id=location["run_id"],repo_root=self.delivery.sources.repo,
                    history_spec=args["history_spec"],historical_input=args["historical_input"],recovery_only=recovery)
            else:
                if input_kind!="forecast_observations": raise DeliveryError("offline_input_adapter_mismatch")
                from quant_crypto.application.btc_registered_candidate import open_btc_registered_candidate_offline
                runtime = open_btc_registered_candidate_offline(self.delivery, row["id"], **args,
                    content_digest=job["content_digest"], account_identity_hash=binding["identity_hash"],
                    adapter_id=adapter_id, state_dir=state, repo_root=self.delivery.sources.repo,
                    recovery_only=recovery)
            if recovery:
                receipt = runtime.reconcile_registered()
                view = None if adapter_id==DONCHIAN_OFFLINE_ADAPTER else projection(job, runtime, receipt)
                runtime.close()
                runtime = None
                self._update(identity, generation, status="blocked", blocker="safety_reconciled_no_new_risk",
                             receipt=view)
                return
            if adapter_id==DONCHIAN_OFFLINE_ADAPTER:
                artifact,persisted_cursor,persisted_projection=runtime.persisted()
                if persisted_cursor<job["cursor"]:
                    raise DeliveryError("offline_persisted_cursor_regressed")
                if persisted_cursor>job["cursor"]:
                    if persisted_projection is None: raise DeliveryError("offline_persisted_projection_missing")
                    event=persisted_projection["event"]
                    job=self._update(identity,generation,cursor=persisted_cursor,
                        last_completed_event=event["event_time_utc"],receipt=projection(job,runtime,persisted_projection))
                job=self._update(identity,generation,total=runtime.total)
                def before_event(_next_cursor,_row):
                    current=self.store.read("job",identity)
                    require_job_identity(current,identity)
                    require_bound_identity(current,job["job_identity"])
                    if current["worker"]["generation"]!=generation: raise DeliveryError("offline_worker_fenced")
                    if current["stop_requested"]: return False
                    runtime.check()
                    return True
                def after_event(cursor,committed):
                    nonlocal job
                    event=committed["event"]
                    job=self._update(identity,generation,cursor=cursor,
                        last_completed_event=event["event_time_utc"],receipt=projection(job,runtime,committed))
                artifact=runtime.run(before_event=before_event,after_event=after_event)
                current=self.store.read("job",identity)
                if artifact.get("status")=="blocked":
                    self._update(identity,generation,status="blocked",
                        blocker=(artifact.get("blockers") or ["historical_replay_blocked"])[-1])
                elif current.get("stop_requested"):
                    self._update(identity,generation,status="stopped")
                elif artifact.get("status")=="complete":
                    final=runtime.finalized_projection(artifact)
                    self._update(identity,generation,status="complete",
                        receipt=projection(job,runtime,final))
                else:
                    self._update(identity,generation,status="interrupted",
                        blocker="explicit_resume_required_no_automatic_restart")
                runtime.close();runtime=None
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
            controller=getattr(runtime,"controller",None) if runtime is not None else None
            protection = controller is not None and bool(controller._state.get("registered_protection_blocker"))
            if protection: code = "registered_protection_execution_unsupported"
            receipt = (projection(job, runtime, {"blocker": code, "protection_blocker": controller._state.get("registered_protection_blocker")})
                       if protection else None)
            self._update(identity, generation, status="blocked" if isinstance(exc, DeliveryError) or protection else "interrupted",
                         blocker=code, protection_blocked=protection, receipt=receipt)
        finally:
            if runtime is not None: runtime.close()
