"""Create-only publications, explicit revision CAS, pinned package lookup."""
from quant_shared.strategy_delivery.models import DeliveryError, digest, identifier
from .candidate_offline_inputs import read_json


class DeliveryIndex:
    def __init__(self, inputs, store):
        self.inputs, self.store = inputs, store

    def entries(self):
        # Small explicit revisions only, no directory traversal/latest discovery.
        return self.store.read("publication")

    def artifacts(self, run_id, candidate_id=None, package_digest=None):
        rows = [r for r in self.entries() if r["source"]["run_id"] == run_id
                and (candidate_id is None or r["source"]["candidate_id"] == candidate_id)
                and (package_digest is None or r["package_digest"] == package_digest)]
        if package_digest is None:
            selected = []
            for r in rows:
                active = self.store.read("source_index", digest(r["source"]))
                if active["publication_id"] == r["publication_id"]: selected.append(r)
            rows = selected
        if len(rows) != 1: raise DeliveryError("factory_delivery_revision_missing_or_ambiguous")
        row = rows[0]
        return [(self.store.root / "publications" / (row["publication_id"] + ".json"), row["artifact_digest"])]

    def publish(self, service, identity, *, expected_revision, key, actor):
        from integrations.qlib_adapter.factory_delivery import publish_factory_delivery
        source = self.inputs.source(identity)
        request = digest({"actor": actor, "publish": identity, "expected_revision": expected_revision,
                          "catalog": self.inputs.checksum})
        identifier(key)
        with self.store.transaction() as conn:
            old = self.store.cached(conn, key, request)
            if old is not None: return old
            for encoded in conn.execute("SELECT payload,sha FROM records WHERE kind='publication'"):
                existing = self.store.decode(encoded)
                if existing["source_revision_id"] == identity and existing["catalog_sha256"] != self.inputs.checksum:
                    raise DeliveryError("offline_source_revision_rebound")
            index_id = digest(source["source"])
            try: previous = self.store.get(conn, "source_index", index_id)
            except DeliveryError as exc:
                if exc.status != 404: raise
                previous = {"revision": 0}
            if previous["revision"] != expected_revision: raise DeliveryError("offline_index_revision_conflict")
            envelope = service.sources.legacy_factory_reader.get(source["source"]["run_id"])
            if envelope.get("integrity_status") != "passed": raise DeliveryError("factory_integrity_blocked")
            candidates = [r for r in envelope["result"]["candidates"] if r["candidate_id"] == source["source"]["candidate_id"]]
            if len(candidates) != 1: raise DeliveryError("factory_candidate_unknown_or_ambiguous")
            location = service.sources.archive.resolve_qlib_run(service.sources.qlib_root, candidates[0]["qlib_run_id"])
            if location is None: raise DeliveryError("research_source_not_found", 404)
            evidence = read_json(self.inputs.path_for(source["frozen_evidence"]), source["frozen_evidence_sha256"], limit=64_000_000)
            publication = digest({"source": source, "catalog": self.inputs.checksum})
            directory = self.store.root / "publications"
            if directory.is_symlink() or (hasattr(directory, "is_junction") and directory.is_junction()):
                raise DeliveryError("offline_publication_path_invalid")
            directory.mkdir(exist_ok=True)
            path = directory / (publication + ".json")
            # A crash may leave an unpublished immutable artifact. Do not adopt
            # it or overwrite it: explicit operator reconciliation is required.
            if path.exists(): raise DeliveryError("offline_publication_exists_unindexed")
            published = publish_factory_delivery(source["source"], envelope, location.run_root,
                destination=path, frozen_evidence=evidence)
            result = {"publication_id": publication, "source_revision_id": identity,
                "source": source["source"], "catalog_revision": self.inputs.revision,
                "catalog_sha256": self.inputs.checksum, "revision": expected_revision + 1,
                "artifact_digest": published["content_digest"], "package_digest": published["package_digest"],
                "actor": actor}
            self.store.put(conn, "publication", publication, result)
            self.store.put(conn, "source_index", index_id, result)
            self.store.cache(conn, key, request, result)
            return result
