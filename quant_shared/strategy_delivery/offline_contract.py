"""Offline orchestration identifiers, not execution permissions."""
import re
from .models import DeliveryError, digest, identifier, permissions, HASH, HEAD

JOB = re.compile(r"^coff_[0-9a-f]{32}$")
IDENTITY_SCHEMA = "candidate_offline_job_identity_v1"
COHORT_IDENTITY_SCHEMA = "candidate_offline_cohort_job_identity_v1"
IDENTITY_FIELDS = ("job_id", "registration_id", "content_digest", "binding_digest",
    "account_ref", "account_identity_hash", "runtime_contract_digest", "state_directory_sha256",
    "input_revision_id", "input_digest", "input_head", "input_evidence_kind",
    "source_head", "execution_head", "catalog_sha256")
HASH_FIELDS = ("content_digest", "binding_digest", "account_identity_hash",
    "runtime_contract_digest", "state_directory_sha256", "input_digest", "catalog_sha256")
COHORT_MEMBER_FIELDS = ("member_id", "registration_id", "registration_revision", "content_digest", "binding_digest",
    "source_account_ref", "source_account_identity_hash", "adapter_id", "input_revision_id",
    "input_digest", "input_head", "input_evidence_kind", "source_head", "strategy_id",
    "strategy_version")
COHORT_IDENTITY_FIELDS = ("job_id", "cohort_binding_id", "cohort_binding_digest",
    "cohort_authority_sha256", "account_ref", "account_identity_hash", "runtime_contract_digest",
    "state_directory_sha256", "run_id", "members", "member_list_sha256", "budget_policy_sha256",
    "event_clock_sha256", "execution_head", "catalog_sha256")


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


def validate_cohort_identity(value):
    if (not isinstance(value, dict) or set(value) != {"schema_version", *COHORT_IDENTITY_FIELDS}
        or value.get("schema_version") != COHORT_IDENTITY_SCHEMA
        or not isinstance(value.get("members"), list) or len(value["members"]) != 2):
        raise DeliveryError("offline_cohort_job_identity_missing_or_invalid")
    members = value["members"]
    if any(not isinstance(row, dict) or set(row) != set(COHORT_MEMBER_FIELDS) for row in members):
        raise DeliveryError("offline_cohort_member_identity_invalid")
    if members != sorted(members, key=lambda row: row["registration_id"]):
        raise DeliveryError("offline_cohort_member_order_invalid")
    if (len({row["registration_id"] for row in members}) != 2
        or len({row["adapter_id"] for row in members}) != 2):
        raise DeliveryError("offline_cohort_member_identity_invalid")
    for row in members:
        for key in tuple(key for key in COHORT_MEMBER_FIELDS if key != "registration_revision"):
            if not isinstance(row.get(key), str) or not row[key]:
                raise DeliveryError("offline_cohort_member_identity_invalid")
        if type(row.get("registration_revision")) is not int or row["registration_revision"]<1:
            raise DeliveryError("offline_cohort_member_identity_invalid")
        for key in ("content_digest", "binding_digest", "source_account_identity_hash", "input_digest"):
            if not HASH.fullmatch(row[key]): raise DeliveryError("offline_cohort_member_identity_invalid")
        for key in ("input_head", "source_head"):
            if not HEAD.fullmatch(row[key]): raise DeliveryError("offline_cohort_member_identity_invalid")
        for key in ("member_id", "registration_id", "source_account_ref", "input_revision_id", "strategy_id", "strategy_version"):
            identifier(row[key])
        if row["input_evidence_kind"] not in {"synthetic_fixture", "verified_historical_observations"}:
            raise DeliveryError("offline_cohort_member_identity_invalid")
    for key in ("cohort_binding_digest", "cohort_authority_sha256", "account_identity_hash",
            "runtime_contract_digest", "state_directory_sha256", "member_list_sha256",
            "budget_policy_sha256", "event_clock_sha256", "catalog_sha256"):
        if not isinstance(value.get(key), str) or not HASH.fullmatch(value[key]):
            raise DeliveryError("offline_cohort_job_identity_invalid")
    if not isinstance(value.get("execution_head"), str) or not HEAD.fullmatch(value["execution_head"]):
        raise DeliveryError("offline_cohort_job_identity_invalid")
    for key in ("cohort_binding_id", "account_ref", "run_id"):
        identifier(value.get(key))
    if not isinstance(value.get("job_id"), str) or not JOB.fullmatch(value["job_id"]):
        raise DeliveryError("offline_cohort_job_identity_invalid")
    authority = {key: value[key] for key in COHORT_IDENTITY_FIELDS if key != "job_id"}
    if value["job_id"] != cohort_job_id(authority):
        raise DeliveryError("offline_cohort_job_identity_mismatch")
    return value


def cohort_job_id(authority):
    if not isinstance(authority, dict): raise DeliveryError("offline_cohort_authority_invalid")
    return "coff_" + digest(authority)[:32]


def seal_cohort_job_identity(binding, *, execution_head, catalog_sha256):
    if (not isinstance(binding, dict) or binding.get("schema_version") != "candidate_offline_cohort_binding_v1"
        or binding.get("status") != "approved"):
        raise DeliveryError("offline_cohort_binding_not_approved")
    unsigned = {key: value for key, value in binding.items() if key not in {"binding_digest", "revision", "status", "review"}}
    if binding.get("binding_digest") != digest(unsigned):
        raise DeliveryError("offline_cohort_binding_integrity_invalid")
    runtime = binding.get("common_account", {}).get("offline_runtime") or {}
    members = [dict(row) for row in binding.get("members", [])]
    authority = {
        "cohort_binding_id": binding["id"], "cohort_binding_digest": binding["binding_digest"],
        "cohort_authority_sha256": binding["cohort_authority_sha256"],
        "account_ref": binding["common_account"]["account_ref"],
        "account_identity_hash": binding["common_account"]["identity_hash"],
        "runtime_contract_digest": runtime["contract_digest"],
        "state_directory_sha256": runtime["state_directory_sha256"], "run_id": runtime["run_id"],
        "members": members, "member_list_sha256": binding["member_list_sha256"],
        "budget_policy_sha256": binding["budget_policy_sha256"],
        "event_clock_sha256": binding["event_clock_sha256"],
        "execution_head": execution_head, "catalog_sha256": catalog_sha256,
    }
    return validate_cohort_identity({"schema_version": COHORT_IDENTITY_SCHEMA,
        "job_id": cohort_job_id(authority), **authority})


def cohort_identity_fields(identity):
    identity = validate_cohort_identity(identity)
    return {**{key: identity[key] for key in COHORT_IDENTITY_FIELDS},
            "job_identity": dict(identity), "job_identity_digest": digest(identity)}


def require_cohort_bound_identity(value, authority):
    if not isinstance(value, dict): raise DeliveryError("offline_cohort_evidence_identity_missing")
    actual, expected = validate_cohort_identity(value.get("job_identity")), validate_cohort_identity(authority)
    if (actual != expected or value.get("job_identity_digest") != digest(expected)
        or any(value.get(key) != expected[key] for key in COHORT_IDENTITY_FIELDS)):
        raise DeliveryError("offline_cohort_evidence_identity_mismatch")


def require_cohort_job_identity(job, identity):
    if not isinstance(job, dict) or job.get("schema_version") != "candidate_offline_cohort_job_v1":
        raise DeliveryError("offline_cohort_job_identity_missing_or_legacy")
    sealed = validate_cohort_identity(job.get("job_identity"))
    if job.get("id") != identity or sealed["job_id"] != identity:
        raise DeliveryError("offline_cohort_job_identity_mismatch")
    require_cohort_bound_identity(job, sealed)
    return sealed


def require_any_job_identity(job, identity):
    if isinstance(job, dict) and job.get("schema_version") == "candidate_offline_cohort_job_v1":
        return require_cohort_job_identity(job, identity)
    return require_job_identity(job, identity)


def require_any_bound_identity(value, authority):
    if isinstance(authority, dict) and authority.get("schema_version") == COHORT_IDENTITY_SCHEMA:
        return require_cohort_bound_identity(value, authority)
    return require_bound_identity(value, authority)


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
