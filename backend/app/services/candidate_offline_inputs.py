"""Explicit immutable server-side catalogue. Never accepts client paths/facts."""
import hashlib
import json
import math
from pathlib import Path
import re

from quant_shared.strategy_delivery.models import DeliveryError, digest, identifier, source_ref, HEAD


def read_json(path, expected, *, limit=2_000_000):
    path = Path(path)
    if path.stat().st_size > limit: raise DeliveryError("offline_input_oversized")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected: raise DeliveryError("offline_input_hash_mismatch")
    return json.loads(raw)


class OfflineInputs:
    def __init__(self, path, checksum, revision, *, repo):
        self.path, self.checksum, self.revision = Path(path), checksum, revision
        self.repo = Path(repo).resolve()

    def catalog(self):
        from quant_crypto.adapters.btc_runtime_artifact_store import git_worktree_roots
        p = self.path
        if not p.is_absolute() or p.is_symlink() or any(p.resolve().is_relative_to(r) for r in git_worktree_roots(self.repo)):
            raise DeliveryError("offline_catalog_must_be_external")
        value = read_json(p, self.checksum)
        if (set(value) != {"schema_version", "repository_owner", "revision", "factory_root", "qlib_root", "sources", "inputs"}
            or value["schema_version"] != "candidate_offline_catalog_v1"
            or value["repository_owner"] != digest({"repository": str(self.repo)})
            or value["revision"] != self.revision):
            raise DeliveryError("offline_catalog_identity_mismatch")
        for collection, field in (("sources", "source_revision_id"), ("inputs", "input_revision_id")):
            rows = value[collection]
            if not isinstance(rows, list) or len(rows) > 100: raise DeliveryError("offline_catalog_invalid")
            ids = [identifier(r[field]) for r in rows]
            if len(ids) != len(set(ids)): raise DeliveryError("offline_catalog_ambiguous")
        return value

    def path_for(self, relative):
        if not isinstance(relative, str) or "\\" in relative or ":" in relative:
            raise DeliveryError("offline_input_path_invalid")
        part = Path(relative)
        if part.is_absolute() or ".." in part.parts or (not part.parts and relative != "."):
            raise DeliveryError("offline_input_path_invalid")
        base = self.path.parent.resolve()
        target = base / part
        if not target.resolve().is_relative_to(base): raise DeliveryError("offline_input_path_escape")
        # Reject existing symlink/junction components, not just final filenames.
        for p in (target, *target.parents):
            if p == base: break
            if p.is_symlink() or (hasattr(p, "is_junction") and p.is_junction()):
                raise DeliveryError("offline_input_link_rejected")
        return target

    def source(self, identity):
        rows = [r for r in self.catalog()["sources"] if r["source_revision_id"] == identifier(identity)]
        if len(rows) != 1: raise DeliveryError("offline_source_revision_unknown", 404)
        row = rows[0]
        if set(row) != {"source_revision_id", "source", "frozen_evidence", "frozen_evidence_sha256"}:
            raise DeliveryError("offline_source_revision_invalid")
        source_ref(row["source"])
        return row

    def list(self):
        value = self.catalog()
        return {"revision": self.revision, "sha256": self.checksum,
                "sources": [{"source_revision_id": r["source_revision_id"], "source": r["source"]} for r in value["sources"]],
                "inputs": [{k: r[k] for k in ("input_revision_id", "content_digest", "evidence_kind", "input_head")} for r in value["inputs"]]}

    def load(self, identity, expected):
        import pandas as pd
        from quant_crypto.application.qlib_offline_replay import (CandidateMarketObservation, OfflineMaintenanceFact,
            FundingSettlementFact)
        rows = [r for r in self.catalog()["inputs"] if r["input_revision_id"] == identifier(identity)]
        if len(rows) != 1: raise DeliveryError("offline_input_revision_unknown", 404)
        row = rows[0]
        version = row.get("schema_version", "candidate_offline_input_v1")
        v1_fields = {"input_revision_id", "content_digest", "evidence_kind", "input_head", "manifest", "bars", "observations"}
        v2_fields = v1_fields | {"schema_version", "dataset_contract", "funding_rate_history"}
        if (set(row) != (v2_fields if version == "candidate_offline_input_v2" else v1_fields)
            or row["content_digest"] != expected or expected != digest({k:v for k,v in row.items() if k != "content_digest"})
            or row["evidence_kind"] not in {"synthetic_fixture", "verified_historical_observations"}
            or not isinstance(row["input_head"], str) or not HEAD.fullmatch(row["input_head"])):
            raise DeliveryError("offline_input_revision_mismatch")
        if version == "candidate_offline_input_v2" and row["evidence_kind"] != "verified_historical_observations":
            raise DeliveryError("offline_input_v2_requires_verified_historical_observations")
        data = {}
        for name in (("manifest", "bars", "observations", "dataset_contract", "funding_rate_history") if version == "candidate_offline_input_v2"
            else ("manifest", "bars", "observations")):
            ref = row[name]
            if set(ref) != {"path", "sha256"}: raise DeliveryError("offline_input_reference_invalid")
            data[name] = read_json(self.path_for(ref["path"]), ref["sha256"], limit=64_000_000)
        if version == "candidate_offline_input_v2":
            contract = data["dataset_contract"]
            if (set(contract) != {"schema_version", "instrument_contract"}
                or contract["schema_version"] != "btc_real_candidate_dataset_contract_v1"
                or data["manifest"].get("schema_version") != "registered_offline_market_v2"
                or data["manifest"].get("dataset_contract_sha256") != row["dataset_contract"]["sha256"]
                or data["manifest"].get("funding_rate_history_sha256") != row["funding_rate_history"]["sha256"]
                or data["manifest"].get("instrument_contract") != contract["instrument_contract"]):
                raise DeliveryError("offline_dataset_contract_binding_invalid")
            history = data["funding_rate_history"]
            history_fields = {"event_time", "available_time", "rate", "source_record_id", "source_dataset",
                "source_version", "source_sha256"}
            if (not isinstance(history, list) or not history or any(set(fact) != history_fields for fact in history)):
                raise DeliveryError("offline_funding_rate_history_invalid")
            for fact in history:
                for field in ("event_time", "available_time"):
                    if pd.Timestamp(fact[field]).tzinfo is None:
                        raise DeliveryError("offline_funding_rate_history_timezone_missing")
                    fact[field] = pd.Timestamp(fact[field]).tz_convert("UTC")
                if (fact["available_time"] < fact["event_time"]
                    or isinstance(fact["rate"], bool) or not isinstance(fact["rate"], (int, float))
                    or not math.isfinite(float(fact["rate"]))
                    or any(not isinstance(fact[name], str) or not fact[name].strip()
                        for name in ("source_record_id", "source_dataset", "source_version"))
                    or not isinstance(fact["source_sha256"], str)
                    or re.fullmatch(r"[0-9a-f]{64}", fact["source_sha256"]) is None):
                    raise DeliveryError("offline_funding_rate_history_invalid")
            event_times = [fact["event_time"] for fact in history]
            source_identities = [(fact["source_dataset"], fact["source_version"], fact["source_record_id"])
                for fact in history]
            if len(set(event_times)) != len(history) or len(set(source_identities)) != len(history):
                raise DeliveryError("offline_funding_rate_history_invalid")
            history.sort(key=lambda fact: (fact["available_time"], fact["event_time"], fact["source_record_id"]))
        bars = pd.DataFrame(data["bars"])
        for field in ("event_time", "available_time", "decision_time"):
            if any(pd.Timestamp(value).tzinfo is None for value in bars[field]):
                raise DeliveryError("offline_bar_timestamp_timezone_missing")
            bars[field] = pd.to_datetime(bars[field], utc=True)
        observations = []
        for raw in data["observations"]:
            v1_observation_fields = set(CandidateMarketObservation.__dataclass_fields__) - {"funding_settlements"}
            expected_observation_fields = (set(CandidateMarketObservation.__dataclass_fields__)
                if version == "candidate_offline_input_v2" else v1_observation_fields)
            if set(raw) != expected_observation_fields:
                raise DeliveryError("offline_observation_facts_missing_or_extra")
            if (type(raw["end_of_window"]) is not bool or not isinstance(raw["blockers"], list)
                or any(not isinstance(b, str) for b in raw["blockers"])):
                raise DeliveryError("offline_observation_types_invalid")
            if any(set(f) != set(OfflineMaintenanceFact.__dataclass_fields__) for f in raw["maintenance_facts"]):
                raise DeliveryError("offline_maintenance_facts_missing_or_extra")
            values = dict(raw)
            values["event_time_utc"] = pd.Timestamp(values["event_time_utc"]).to_pydatetime()
            values["maintenance_facts"] = tuple(OfflineMaintenanceFact(
                observed_at_utc=pd.Timestamp(f["observed_at_utc"]).to_pydatetime(),
                mark_price=f["mark_price"], index_price=f["index_price"]) for f in values["maintenance_facts"])
            if version == "candidate_offline_input_v2":
                funding_fields = set(FundingSettlementFact.__dataclass_fields__)
                if any(set(fact) != funding_fields for fact in values["funding_settlements"]):
                    raise DeliveryError("offline_funding_facts_missing_or_extra")
                values["funding_settlements"] = tuple(FundingSettlementFact(
                    **{**fact, "event_time_utc": pd.Timestamp(fact["event_time_utc"]).to_pydatetime()})
                    for fact in values["funding_settlements"])
            else:
                values["funding_settlements"] = ()
            values["blockers"] = tuple(values.get("blockers", ()))
            observations.append(CandidateMarketObservation(**values))
        if version == "candidate_offline_input_v2":
            for observation in observations:
                decision = pd.Timestamp(observation.event_time_utc) + pd.Timedelta(hours=1)
                known = [fact for fact in history if fact["available_time"] <= decision and fact["event_time"] <= decision]
                if not known or float(observation.funding_rate) != float(known[-1]["rate"]):
                    raise DeliveryError("offline_funding_rate_not_latest_known")
        return row, {"bars": bars, "observations": observations, "market_manifest": data["manifest"],
                     "market_manifest_digest": digest(data["manifest"])}
