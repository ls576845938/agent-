"""Registered, offline-only driver for the original Donchian history replay.

The driver verifies immutable registration/input/account identity before it
constructs the existing replay.  It does not synthesize a Forecast: the
original Donchian Signal -> TargetPosition -> Risk -> OMS -> Fill/Ledger chain
remains the sole economic authority.
"""
from copy import deepcopy
import os
from pathlib import Path

from quant_shared.strategy_delivery.models import DeliveryError, digest

ADAPTER_ID="btc_donchian_history_offline_v1"


def _verify_runtime_location(runtime, *, output_root, run_id):
    normalized_root=Path(os.path.normcase(str(Path(output_root).resolve())))
    normalized_state=(normalized_root/str(run_id)).resolve()
    if (str(run_id)!=str(runtime.get("run_id") or "")
        or digest(str(normalized_root))!=runtime.get("output_root_sha256")
        or digest(str(normalized_state))!=runtime.get("state_directory_sha256")):
        raise DeliveryError("registered_donchian_runtime_location_mismatch")
    return normalized_root


def _verify(service, registration_id, *, content_digest, account_identity_hash,
            runtime, spec, historical_input, recovery_only=False):
    from .btc_registered_candidate import _require_trusted_service
    _require_trusted_service(service)
    resolve=service.resolve_recovery if recovery_only else service.resolve
    row=resolve(registration_id,content_digest=content_digest,
        account_identity_hash=account_identity_hash,adapter_id=ADAPTER_ID)
    binding=row["binding"]
    expected_runtime=binding.get("offline_runtime",{})
    if (row["target"]!="offline" or row["package"].get("adapter_id")!=ADAPTER_ID
        or row["package"].get("execution_binding")!=spec.payload
        or row["package"].get("source_head")!=spec.git_spec.split(":",1)[0]
        or runtime!=expected_runtime
        or runtime.get("schema_version")!="delivery_offline_runtime_v2"
        or runtime.get("adapter_id")!=ADAPTER_ID
        or runtime.get("venue_adapter")!="donchian_historical_replay_v1"
        or runtime.get("initial_equity_usdt")!=5000
        or runtime.get("currency")!="USDT" or runtime.get("equity_unit")!="USDT"):
        raise DeliveryError("registered_donchian_binding_mismatch")
    data=spec.payload["data"]
    manifest=historical_input.manifest
    if (historical_input.manifest_sha256!=data["manifest_sha256"]
        or manifest.get("aggregate_sha256")!=data["aggregate_sha256"]
        or manifest.get("dataset_id")!=data["dataset_id"]
        or manifest.get("dataset_version")!=data["dataset_version"]):
        raise DeliveryError("registered_donchian_input_mismatch")
    return row


def verify_registered_donchian_cohort_member(service, registration_id, *, content_digest,
        account_identity_hash, common_runtime, spec, historical_input, recovery_only=False):
    """Decision-only source verification; the common runtime owns economics."""
    from .btc_registered_candidate import _require_trusted_service, offline_simulated_account_identity
    _require_trusted_service(service)
    resolve=service.resolve_recovery if recovery_only else service.resolve
    row=resolve(registration_id,content_digest=content_digest,
        account_identity_hash=account_identity_hash,adapter_id=ADAPTER_ID)
    runtime=dict(common_runtime or {})
    if (row["target"]!="offline" or row["package"].get("adapter_id")!=ADAPTER_ID
        or row["package"].get("execution_binding")!=spec.payload
        or row["package"].get("source_head")!=spec.git_spec.split(":",1)[0]
        or runtime.get("schema_version")!="delivery_offline_runtime_v3"
        or runtime.get("adapter_ids")!=[ADAPTER_ID,"factory_lgbm_ast_v1"]
        or runtime.get("initial_equity_usdt")!=5000 or runtime.get("currency")!="USDT"
        or runtime.get("equity_unit")!="USDT"
        or runtime.get("simulated_venue_identity_hash")!=offline_simulated_account_identity()
        or runtime.get("contract_digest")!=digest({k:v for k,v in runtime.items() if k!="contract_digest"})):
        raise DeliveryError("registered_donchian_cohort_binding_mismatch")
    data=spec.payload["data"]; manifest=historical_input.manifest
    if (historical_input.manifest_sha256!=data["manifest_sha256"]
        or manifest.get("aggregate_sha256")!=data["aggregate_sha256"]
        or manifest.get("dataset_id")!=data["dataset_id"]
        or manifest.get("dataset_version")!=data["dataset_version"]):
        raise DeliveryError("registered_donchian_input_mismatch")
    return row


class RegisteredDonchianReplay:
    def __init__(self, *, service, registration_id, content_digest,
            account_identity_hash, runtime_binding, output_root, run_id,
            repo_root, spec, historical_input, recovery_only=False):
        from .donchian_historical_replay import DonchianHistoricalReplay
        self.service=service
        self.registration_id=registration_id
        self.content_digest=content_digest
        self.account_identity_hash=account_identity_hash
        self.runtime_binding=deepcopy(runtime_binding)
        self.spec=spec
        self.historical_input=historical_input
        self.recovery_only=recovery_only
        self.output_root=_verify_runtime_location(
            self.runtime_binding,output_root=output_root,run_id=run_id)
        self.run_id=str(run_id)
        self.row=_verify(service,registration_id,content_digest=content_digest,
            account_identity_hash=account_identity_hash,runtime=self.runtime_binding,
            spec=spec,historical_input=historical_input,recovery_only=recovery_only)
        self.replay=DonchianHistoricalReplay(repo_root=Path(repo_root),output_root=self.output_root,
            run_id=self.run_id,spec=spec,historical_input=historical_input,
            coordination_projection_enabled=True)
        if self.replay.source_head!=self.row["package"]["source_head"]:
            raise DeliveryError("registered_donchian_code_identity_changed")
        self.total=self.replay.expected_event_count
        self.last_committed=None

    @property
    def run_root(self): return self.replay.run_root

    def check(self):
        _verify_runtime_location(self.runtime_binding,output_root=self.output_root,
            run_id=self.run_id)
        self.row=_verify(self.service,self.registration_id,content_digest=self.content_digest,
            account_identity_hash=self.account_identity_hash,runtime=self.runtime_binding,
            spec=self.spec,historical_input=self.historical_input,recovery_only=False)
        if self.replay.source_head!=self.row["package"]["source_head"]:
            raise DeliveryError("registered_donchian_code_identity_changed")
        return self.row

    def persisted(self):
        value=self.replay.status(output_root=self.replay.output_root,run_id=self.replay.run_id)
        cursor=len(value.get("events") or [])
        projection=None
        path=self.replay.coordination_projection_path
        if path.is_file():
            import json
            projection=json.loads(path.read_text(encoding="utf-8"))
            expected=projection.pop("sha256",None)
            if (expected!=digest(projection) or projection.get("cursor")!=cursor
                or projection.get("artifact_identity_digest")!=value.get("identity_digest")):
                raise DeliveryError("registered_donchian_projection_integrity_invalid")
            projection["sha256"]=expected
        return value,cursor,projection

    def run(self, *, before_event, after_event):
        def committed(cursor,payload):
            self.last_committed=deepcopy(payload)
            after_event(cursor,self.last_committed)
        return self.replay.run(before_event=before_event,after_event=committed)

    def finalized_projection(self, artifact):
        """Bind job completion to the original replay's persisted terminal facts."""
        from .donchian_historical_replay import load_historical_venue_state
        observed,cursor,projection=self.persisted()
        if observed!=artifact or artifact.get("status")!="complete" or projection is None:
            raise DeliveryError("registered_donchian_final_artifact_invalid")
        venue,errors=load_historical_venue_state(
            self.run_root/"state"/"offline_venue.json")
        marked=artifact.get("marked_state") or {}
        pairs={"position_contracts":"position","cash_usdt":"cash",
            "equity_usdt":"equity","fees_usdt":"fee_total",
            "funding_usdt":"funding_total"}
        ledger=projection.get("ledger") or {}
        if (venue is None or errors or cursor!=self.total
            or any(marked.get(left)!=venue.get(right) for left,right in pairs.items())
            or ledger.get("status")!="reconciled" or ledger.get("reconciled") is not True
            or ledger.get("position_contracts")!=venue.get("position")
            or ledger.get("final_equity_usdt")!=venue.get("equity")
            or ledger.get("fill_count")!=len(venue.get("fills") or [])
            or ledger.get("funding_bill_count")!=len(venue.get("bills") or [])):
            raise DeliveryError("registered_donchian_final_economics_unreconciled")
        committed=deepcopy(projection)
        committed.update(venue=deepcopy(venue),ledger=deepcopy(ledger),
            finalized=True,artifact_status="complete",
            marked_state=deepcopy(marked),artifact_counts=deepcopy(artifact.get("counts")))
        committed.pop("sha256",None)
        committed["sha256"]=digest(committed)
        return committed

    def reconcile_registered(self):
        artifact,cursor,_=self.persisted()
        return {"adapter_id":ADAPTER_ID,"status":artifact.get("status"),"cursor":cursor,
            "blocker":"safety_reconciled_no_new_risk","artifact_identity_digest":artifact.get("identity_digest")}

    def offline_projection(self,job,receipt):
        from quant_shared.strategy_delivery.offline_contract import safety,identity_fields,require_job_identity
        venue=receipt.get("venue") or {}
        event=receipt.get("event") or {}
        value={"schema_version":"candidate_offline_result_v2",**safety(),
            **identity_fields(require_job_identity(job,job["id"])),"adapter_id":ADAPTER_ID,
            "run_id":self.replay.run_id,"verified_through_event":event.get("event_time_utc") or job.get("last_completed_event"),
            "decision_receipt":event,"decision_receipt_sha256":digest(event),
            "position_contracts":venue.get("position"),"order_count":len(venue.get("orders") or []),
            "fill_count":len(venue.get("fills") or []),"orders":list(venue.get("orders") or [])[-20:],
            "fills":list(venue.get("fills") or [])[-20:],"protection":list(venue.get("algos") or []),
            "ledger":receipt.get("ledger"),"artifact_identity_digest":receipt.get("artifact_identity_digest"),
            "finalized":receipt.get("finalized",False),
            "artifact_status":receipt.get("artifact_status"),
            "marked_state":receipt.get("marked_state"),
            "artifact_counts":receipt.get("artifact_counts"),
            "history_phases":list(event.get("phases") or []),
            "limitations":["historical_reconstructed_offline_only","simulated_not_real_fills",
                "bounded_last_20_orders_and_fills","terminal_no_forced_close"]}
        value["sha256"]=digest(value)
        return value

    def close(self): return None


def open_btc_registered_donchian_offline(service, registration_id, *, content_digest,
        account_identity_hash, adapter_id, runtime_binding, output_root, run_id,
        repo_root, history_spec, historical_input, recovery_only=False):
    if adapter_id!=ADAPTER_ID: raise DeliveryError("registered_donchian_adapter_required")
    return RegisteredDonchianReplay(service=service,registration_id=registration_id,
        content_digest=content_digest,account_identity_hash=account_identity_hash,
        runtime_binding=runtime_binding,output_root=output_root,run_id=run_id,
        repo_root=repo_root,spec=history_spec,historical_input=historical_input,
        recovery_only=recovery_only)
