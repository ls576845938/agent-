"""Delivery command boundary. Injected source/account ports, no runtime imports."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from .models import (DeliveryError, VALIDATOR, HEAD, digest, identifier, permissions,
                     source_ref, utc, validate_account, validate_package)
from .admission import build_diagnostic_admission


class DeliveryService:
    def __init__(self, store, sources, accounts, *, head, clock=None, head_provider=None):
        if not HEAD.fullmatch(head): raise DeliveryError("consumer_head_invalid")
        self.store, self.sources, self.accounts, self.head = store, sources, accounts, head
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.head_provider = head_provider

    def _request(self, actor, key, payload):
        if self.head_provider is not None and self.head_provider() != self.head:
            raise DeliveryError("deployment_changed_restart_required")
        identifier(actor)
        identifier(key)
        return digest({"actor": actor, "request": payload})

    def create(self, source, target, *, key, actor):
        source = source_ref(source)
        if target not in {"offline", "okx_demo"}: raise DeliveryError("target_not_supported", 422)
        request_digest = self._request(actor, key, {"create": source, "target": target})
        def perform(conn):
            package = self.sources.compile(source)
            if package.get("source") != source: raise DeliveryError("source_identity_mismatch")
            package_digest = digest(package)
            strict_blockers = validate_package(package, target)
            admission = build_diagnostic_admission(package_digest=package_digest, target=target,
                consumer_head=self.head, strict_blockers=strict_blockers)
            blockers = admission["blocking_reasons"]
            from .runtime_contract import PACKAGE_SCHEMA
            validator = "strategy_delivery_validator_v3" if package.get("schema_version") == PACKAGE_SCHEMA else VALIDATOR
            now = self.clock().isoformat()
            row = {"schema_version": "strategy_delivery_record_v1", "id": "delivery_" + uuid4().hex,
                   "revision": 1, "source": source, "target": target, "package": package,
                   "content_digest": package_digest, "consumer_head": self.head,
                   "status": "validation_blocked" if blockers else "validated",
                   "validation": {"validator": validator, "blockers": blockers,
                                  "status": "blocked" if blockers else "passed"},
                   "diagnostic_admission": admission,
                   "binding": None, "review": None, "registration": None,
                   "created_at": now, "updated_at": now, "actor": actor,
                   "permissions": permissions(), "last_action": "validate"}
            self.store.save(conn, row)
            return row
        return self.store.transact(key, request_digest, perform)

    def _fresh(self, row, *, account=True):
        if self.head_provider is not None and self.head_provider() != self.head:
            raise DeliveryError("deployment_changed_restart_required")
        if row["consumer_head"] != self.head: raise DeliveryError("consumer_head_changed")
        recompile = getattr(self.sources, "recompile", None)
        pinned = getattr(self.sources, "recompile_record", None)
        package = (pinned(row) if pinned is not None else
                   recompile(row["source"], package_schema=row["package"]["schema_version"])
                   if recompile is not None else self.sources.compile(row["source"]))
        if digest(package) != row["content_digest"]: raise DeliveryError("package_changed")
        strict_blockers = validate_package(package, row["target"])
        admission = row.get("diagnostic_admission")
        if admission is None:
            if strict_blockers: raise DeliveryError("package_admission_blocked")
        else:
            expected = build_diagnostic_admission(package_digest=row["content_digest"], target=row["target"],
                consumer_head=row["consumer_head"], strict_blockers=strict_blockers)
            if admission != expected: raise DeliveryError("diagnostic_admission_changed")
            if admission["status"] != "admitted" or admission["blocking_reasons"]:
                raise DeliveryError("package_admission_blocked")
        if account:
            if not row["binding"]: raise DeliveryError("account_not_bound")
            current = self.accounts.get(row["binding"]["account_ref"])
            validate_account(current, package, row["target"], self.clock())
            if digest(current) != row["binding_digest"]: raise DeliveryError("account_binding_changed")

    @staticmethod
    def _review_binding(row):
        value = {"content_digest": row["content_digest"], "target": row["target"],
                       "binding_digest": row["binding_digest"], "consumer_head": row["consumer_head"],
                       "validator": row["validation"]["validator"], "adapter_id": row["package"]["adapter_id"]}
        if row.get("diagnostic_admission") is not None:
            value["diagnostic_admission_digest"] = row["diagnostic_admission"]["decision_digest"]
        return digest(value)

    def command(self, identity, action, *, expected_revision, key, actor, **payload):
        identifier(identity)
        if type(expected_revision) is not int or expected_revision < 1: raise DeliveryError("revision_invalid", 422)
        allowed = {"bind": {"account_ref"}, "review": {"decision", "reason"}, "register": set(), "revoke": {"reason"}}
        if action not in allowed or set(payload) != allowed[action]: raise DeliveryError("command_fields_invalid", 422)
        request_digest = self._request(actor, key, {"id": identity, "action": action, "revision": expected_revision, **payload})
        def perform(conn):
            row = self.store.load(conn, identity)
            if row["revision"] != expected_revision: raise DeliveryError("revision_conflict")
            if row["status"] == "revoked": raise DeliveryError("registration_inactive")
            if row["status"] == "registered" and action != "revoke": raise DeliveryError("registered_record_immutable")
            if action == "bind":
                if row["status"] not in {"validated", "bound", "reviewed"}: raise DeliveryError("package_not_validated")
                self._fresh(row, account=False)
                binding = self.accounts.get(identifier(payload["account_ref"]))
                validate_account(binding, row["package"], row["target"], self.clock())
                row.update(binding=binding, binding_digest=digest(binding), review=None, status="bound")
            elif action == "review":
                reason = payload["reason"]
                if not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 500: raise DeliveryError("review_reason_required", 422)
                if payload["decision"] not in {"approve", "reject"}: raise DeliveryError("review_decision_invalid", 422)
                if payload["decision"] == "approve":
                    if row["status"] != "bound": raise DeliveryError("review_requires_bound_package")
                    self._fresh(row)
                    binding = self._review_binding(row)
                else: binding = None
                row["review"] = {"decision": payload["decision"], "actor": actor, "reason": reason,
                                 "binding_digest": binding, "reviewed_at": self.clock().isoformat(),
                                 "expires_at": (self.clock() + timedelta(hours=24)).isoformat()}
                row["status"] = "reviewed" if payload["decision"] == "approve" else "rejected"
            elif action == "register":
                if row["status"] != "reviewed": raise DeliveryError("review_required")
                self._fresh(row)
                if row["review"]["binding_digest"] != self._review_binding(row): raise DeliveryError("review_binding_mismatch")
                if utc(row["review"]["expires_at"]) <= self.clock(): raise DeliveryError("review_expired")
                self.store.reserve(conn, row)
                row["registration"] = {"registration_id": row["id"], "registered_at": self.clock().isoformat(),
                                       "adapter_id": row["package"]["adapter_id"], "environment": row["target"],
                                       "start_allowed": False, "runtime_observed": False,
                                       "diagnostic_admission_digest": (row.get("diagnostic_admission") or {}).get("decision_digest")}
                row["status"] = "registered"
            elif action == "revoke":
                if not isinstance(payload["reason"], str) or not 1 <= len(payload["reason"].strip()) <= 500:
                    raise DeliveryError("revoke_reason_required", 422)
                row.update(status="revoked", revocation={"actor": actor, "reason": payload["reason"]})
                self.store.release(conn, identity)
            row.update(revision=row["revision"] + 1, updated_at=self.clock().isoformat(), actor=actor, last_action=action)
            self.store.save(conn, row)
            return row
        return self.store.transact(key, request_digest, perform)

    def get(self, identity):
        return self.store.read(identifier(identity))

    def list(self):
        return self.store.read()

    def resolve(self, identity, *, content_digest, account_identity_hash, adapter_id):
        row = self.get(identity)
        if row["status"] != "registered": raise DeliveryError("registration_inactive")
        if (row["content_digest"], row["binding"]["identity_hash"], row["package"]["adapter_id"]) != (
            content_digest, account_identity_hash, adapter_id): raise DeliveryError("resolution_binding_mismatch")
        self._fresh(row)
        if utc(row["review"]["expires_at"]) <= self.clock(): raise DeliveryError("review_expired")
        return row  # loading contract only; no inference, controller construction or start

    def resolve_recovery(self, identity, *, content_digest, account_identity_hash, adapter_id):
        """Exact historical binding for safety reconciliation, never new orders.

        Revocation/expiry remove new-risk authority, not the economic identity.
        Source, code, immutable approval binding and current account still match.
        The offline consumer separately requires an existing durable state.
        """
        row = self.get(identity)
        if row["status"] not in {"registered","revoked"} or not row.get("registration"):
            raise DeliveryError("recovery_registration_missing")
        if (row["content_digest"],row["binding"]["identity_hash"],row["package"]["adapter_id"]) != (
                content_digest,account_identity_hash,adapter_id):
            raise DeliveryError("resolution_binding_mismatch")
        self._fresh(row,account=False)
        if (digest(self.accounts.get(row["binding"]["account_ref"])) != row["binding_digest"]
            or row["review"]["decision"] != "approve"
            or row["review"]["binding_digest"] != self._review_binding(row)):
            raise DeliveryError("recovery_account_or_review_binding_changed")
        return row
