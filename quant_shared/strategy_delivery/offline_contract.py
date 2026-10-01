"""Offline orchestration identifiers, not execution permissions."""
import re
from .models import DeliveryError, digest, identifier, permissions, HASH, HEAD

JOB = re.compile(r"^coff_[0-9a-f]{32}$")
IDENTITY_SCHEMA = "candidate_offline_job_identity_v1"
IDENTITY_FIELDS = ("job_id", "registration_id", "content_digest", "binding_digest",
    "account_ref", "account_identity_hash", "runtime_contract_digest", "state_directory_sha256",
    "input_revision_id", "input_digest", "input_head", "input_evidence_kind",
    "source_head", "execution_head", "catalog_sha256")
HASH_FIELDS = ("content_digest", "binding_digest", "account_identity_hash",
    "runtime_contract_digest", "state_directory_sha256", "input_digest", "catalog_sha256")


def validate_identity(value):
    if (not isinstance(value, dict) or set(value) != {"schema_version", *IDENTITY_FIELDS}
        or value.get("schema_version") != IDENTITY_SCHEMA
        or any(not isinstance(value.get(k), str) for k in IDENTITY_FIELDS)):
        raise DeliveryError("offline_job_identity_missing_or_invalid")
    if (any(not HASH.fullmatch(value[k]) for k in HASH_FIELDS)
        or any(not HEAD.fullmatch(value[k]) for k in ("source_head", "execution_head", "input_head"))
        or value["input_evidence_kind"] not in {"synthetic_fixture", "verified_historical_observations"}):
        raise DeliveryError("offline_job_identity_invalid")
    for key in ("registration_id", "account_ref", "input_revision_id"): identifier(value[key])
    if value["job_id"] != job_id(value["registration_id"]):
        raise DeliveryError("offline_job_identity_mismatch")
    return value


def seal_job_identity(identity, row, input_ref, execution_head, catalog_sha256):
    """Only server registration/binding/catalog metadata; no mutable job state."""
    bound = row.get("binding") or {}
    runtime = bound.get("offline_runtime") or {}
    if (digest(bound) != row.get("binding_digest") or digest(row["package"]) != row["content_digest"]
        or digest({k:v for k,v in runtime.items() if k != "contract_digest"}) != runtime.get("contract_digest")
        or digest({k:v for k,v in input_ref.items() if k != "content_digest"}) != input_ref.get("content_digest")):
        raise DeliveryError("offline_job_identity_source_invalid")
    return validate_identity({"schema_version": IDENTITY_SCHEMA, "job_id": identity,
        "registration_id": row["id"], "content_digest": row["content_digest"],
        "binding_digest": row["binding_digest"], "account_ref": bound.get("account_ref"),
        "account_identity_hash": bound.get("identity_hash"),
        "runtime_contract_digest": runtime.get("contract_digest"),
        "state_directory_sha256": runtime.get("state_directory_sha256"),
        "input_revision_id": input_ref["input_revision_id"], "input_digest": input_ref["content_digest"],
        "input_head": input_ref["input_head"], "input_evidence_kind": input_ref["evidence_kind"],
        "source_head": row["package"]["source_head"], "execution_head": execution_head,
        "catalog_sha256": catalog_sha256})


def identity_fields(identity):
    identity = validate_identity(identity)
    return {**{k: identity[k] for k in IDENTITY_FIELDS},
            "job_identity": dict(identity), "job_identity_digest": digest(identity)}


def require_bound_identity(value, authority):
    """Evidence self-hashes are integrity only; the stored job is the authority."""
    if not isinstance(value, dict):
        raise DeliveryError("offline_evidence_identity_missing")
    actual = validate_identity(value.get("job_identity"))
    expected = validate_identity(authority)
    if (actual != expected or value.get("job_identity_digest") != digest(expected)
        or any(value.get(k) != expected[k] for k in IDENTITY_FIELDS)):
        raise DeliveryError("offline_evidence_identity_mismatch")


def require_job_identity(job, identity):
    if not isinstance(job, dict) or job.get("schema_version") != "candidate_offline_job_v2":
        raise DeliveryError("offline_job_identity_missing_or_legacy")
    sealed = validate_identity(job.get("job_identity"))
    if job.get("id") != identity or sealed["job_id"] != identity:
        raise DeliveryError("offline_job_identity_mismatch")
    require_bound_identity(job, sealed)
    return sealed


def job_id(registration):
    return "coff_" + digest(identifier(registration))[:32]


def require_job(value):
    if not isinstance(value, str) or not JOB.fullmatch(value):
        raise DeliveryError("offline_job_id_invalid", 422)
    return value


def safety():
    return {"permissions": permissions(), "start_allowed": False,
            "evidence_kind": "registered_candidate_offline_only",
            "research_completion_grants_trading": False}
